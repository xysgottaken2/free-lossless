"""NeuralRenderer abstraction.

The pipeline only ever talks to this interface:

    renderer.process(frame) -> frame

Backends:

* :class:`DisabledRenderer` - always a no-op pass-through (used when DLSS 5 is
  switched off or unavailable).  It must never load any NVIDIA runtime.
* :class:`DLSS5Renderer` (``neural.dlss5``) - optional DLSS 5 Neural Rendering
  stage driven through the native bridge in ``native/``.

Future backends (e.g. another neural enhancer) can be added without touching
the capture / RIFE / overlay pipeline.
"""

from __future__ import annotations

import abc
import dataclasses
from typing import Any, Dict, Optional

import numpy as np

# Renderer states
STATE_DISABLED = "disabled"
STATE_READY = "ready"
STATE_UNAVAILABLE = "unavailable"
STATE_ERROR = "error"


@dataclasses.dataclass
class RendererStatus:
    """Human-readable status used by the UI and the logs."""

    state: str = STATE_DISABLED
    runtime: str = "Not Found"
    gpu: str = "unknown"
    driver: str = "unknown"
    backend: str = "none"
    model: str = "unknown"
    preset: str = "n/a"
    passes: int = 0
    resolution: str = "n/a"
    error: str = ""
    frames_processed: int = 0

    def summary(self) -> str:
        if self.state == STATE_ERROR and self.error:
            return f"Error: {self.error}"
        return self.state.capitalize()


class NeuralRenderer(abc.ABC):
    """Optional neural enhancement stage between capture and RIFE."""

    name: str = "NeuralRenderer"

    @abc.abstractmethod
    def initialize(self) -> bool:
        """Allocate resources / load runtime. Never raises; returns success."""

    @abc.abstractmethod
    def process(self, frame: np.ndarray) -> np.ndarray:
        """Enhance one RGB frame. Never raises; returns the frame unchanged
        when the backend is not ready or fails (fail-soft)."""

    @abc.abstractmethod
    def shutdown(self) -> None:
        """Release resources. Must be safe to call twice."""

    @abc.abstractmethod
    def status(self) -> RendererStatus:
        """Report current state for logs/UI."""

    def info(self) -> Dict[str, Any]:
        st = self.status()
        return {
            "backend": st.backend,
            "resolution": st.resolution,
            "model": st.model,
            "preset": st.preset,
            "passes": st.passes,
        }


class DisabledRenderer(NeuralRenderer):
    """Pass-through renderer. Guarantees: loads nothing, never fails."""

    name = "Disabled"

    def __init__(self, reason: str = "disabled by configuration"):
        self._reason = reason
        self._frames = 0

    def initialize(self) -> bool:
        return True

    def process(self, frame: np.ndarray) -> np.ndarray:
        self._frames += 1
        return frame

    def shutdown(self) -> None:
        return None

    def status(self) -> RendererStatus:
        return RendererStatus(
            state=STATE_DISABLED,
            runtime="Not loaded",
            backend="none",
            error=self._reason,
            frames_processed=self._frames,
        )


class FailingRenderer(NeuralRenderer):
    """Test helper: simulates a backend that dies after N frames."""

    name = "Failing"

    def __init__(self, fail_after: int = 1, wrapped: Optional[NeuralRenderer] = None):
        self.fail_after = fail_after
        self.wrapped = wrapped or DisabledRenderer("test")
        self.calls = 0
        self.disabled = False

    def initialize(self) -> bool:
        return True

    def process(self, frame: np.ndarray) -> np.ndarray:
        self.calls += 1
        if self.calls > self.fail_after:
            raise RuntimeError("simulated neural renderer crash")
        return self.wrapped.process(frame)

    def shutdown(self) -> None:
        self.disabled = True

    def status(self) -> RendererStatus:
        return RendererStatus(state=STATE_ERROR if self.disabled else STATE_READY)

"""Frame processing pipeline: Resize -> [DLSS 5 Neural Rendering] -> [RIFE].

This module is the testable core of ``main.processing_subroutine``.  It is
deliberately free of Windows / torch imports: the interpolation engine and the
neural renderer are injected, so unit tests can exercise every combination of
stages on any machine (including CI without any GPU):

    DLSS5 OFF + RIFE OFF
    DLSS5 ON  + RIFE OFF
    DLSS5 OFF + RIFE ON
    DLSS5 ON  + RIFE ON

Failure policy: a neural renderer error must never kill the pipeline.  The
stage disables itself and the frame continues to RIFE / overlay unchanged.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np

from neural.base import NeuralRenderer, DisabledRenderer
from neural.log import log_pipeline, log_rife

try:
    import cv2
except Exception:  # pragma: no cover - cv2 is a hard runtime dep, soft in tests
    cv2 = None


class FramePipeline:
    """Owns the per-frame stage chain. Single-threaded (one worker)."""

    def __init__(
        self,
        engine=None,
        renderer: Optional[NeuralRenderer] = None,
        internal_res: Tuple[int, int] = (800, 600),
        fg_enabled: bool = True,
        interpolation_backend=None,
    ):
        self.engine = engine
        self.renderer = renderer if renderer is not None else DisabledRenderer()
        self.internal_res = tuple(internal_res)
        self.fg_enabled = bool(fg_enabled)
        # interpolation_backend(frame_a, frame_b) -> mid frame; defaults to the
        # engine's ``interpolate`` method. Injectable for tests.
        self._interpolate = interpolation_backend
        self.last_frame: Optional[np.ndarray] = None
        self._neural_active = self.renderer.status().state != "disabled" if self.renderer else False
        self._log_banner()

    # ---------------------------------------------------------------- banner
    def _log_banner(self) -> None:
        state = self.renderer.status().state if self.renderer else "disabled"
        dlss = "ON" if state not in ("disabled",) else "OFF"
        rife = "ON" if self.fg_enabled else "OFF"
        log_pipeline(f"Capture -> DLSS5 {dlss} -> RIFE {rife} -> Overlay")
        if self.fg_enabled:
            log_rife("Frame Generation available")
        else:
            log_rife("Frame Generation disabled")
        if state == "ready":
            log_pipeline(f"DLSS5 stage ready: {self.renderer.info()}")
        elif state in ("unavailable", "error"):
            log_pipeline(f"DLSS5 stage inactive ({self.renderer.status().summary()})")

    # -------------------------------------------------------------- resize
    def _resize(self, frame: np.ndarray) -> np.ndarray:
        target_w, target_h = self.internal_res
        h, w = frame.shape[:2]
        if w > target_w or h > target_h:
            if cv2 is not None:
                return cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
            # Fallback used only in minimal test environments.
            ys = np.linspace(0, h - 1, target_h).astype(np.int32)
            xs = np.linspace(0, w - 1, target_w).astype(np.int32)
            return frame[ys][:, xs]
        return frame

    # --------------------------------------------------------------- neural
    def _apply_neural(self, frame: np.ndarray) -> np.ndarray:
        try:
            return self.renderer.process(frame)
        except Exception as exc:  # pragma: no cover - renderer should be fail-soft
            log_pipeline(f"DLSS5 stage raised ({exc}); continuing without it")
            self.renderer = DisabledRenderer(f"disabled after error: {exc}")
            self._neural_active = False
            return frame

    # ------------------------------------------------------- interpolation
    def _apply_interpolation(self, previous: np.ndarray, current: np.ndarray) -> np.ndarray:
        try:
            if self._interpolate is not None:
                return self._interpolate(previous, current)
            return self.engine.interpolate(previous, current)
        except Exception as exc:
            log_pipeline(f"RIFE interpolation failed ({exc}); emitting original frame")
            return current

    # ---------------------------------------------------------------- frame
    def process_frame(self, frame: np.ndarray) -> List[np.ndarray]:
        """Run one captured frame through the stages.

        Returns the list of frames to send to the overlay queue (the original
        plus, when frame generation is enabled, the interpolated one first).
        """
        frame = self._resize(frame)

        # Optional DLSS 5 Neural Rendering stage.
        frame = self._apply_neural(frame)

        if self.fg_enabled and self.last_frame is not None:
            inter = self._apply_interpolation(self.last_frame, frame)
            self.last_frame = frame
            return [inter, frame]

        self.last_frame = frame
        return [frame]

    def set_internal_res(self, internal_res: Sequence[int]) -> None:
        self.internal_res = (int(internal_res[0]), int(internal_res[1]))

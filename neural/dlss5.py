"""DLSS5Renderer - optional DLSS 5 Neural Rendering stage.

Design rules (from the project brief):

* The renderer NEVER raises out of ``process()``.  If anything fails at any
  point it disables itself and returns the frame unchanged, so the pipeline
  always continues as ``Capture -> RIFE -> Overlay``.
* The NVIDIA runtime is an external dependency (``native/nvngx_dlssnr.dll``)
  supplied by the user; nothing proprietary is bundled or downloaded.
* Availability is verified for real (bridge load + NGX init + CreateFeature(18)
  probe on a synthetic frame) before the first real frame is routed through.

Confirmed backend contract: NGX feature 18 ("Reserved18") via the standalone
worker sequence - see ``docs/dlss5-research.md``.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

import numpy as np

from .base import (
    NeuralRenderer,
    RendererStatus,
    STATE_ERROR,
    STATE_READY,
    STATE_UNAVAILABLE,
)
from . import bridge as bridge_mod
from .bridge import BridgeError, FlNrOptions, NativeBridge
from .log import log_dlss5
from .runtime import RuntimeLocator
from .system_info import query_display_driver_version, query_gpu_name


def _align8(value: int) -> int:
    return max(8, (int(value) // 8) * 8)


class DLSS5Renderer(NeuralRenderer):
    """Runs DLSS 5 Neural Rendering through the native bridge, fail-soft."""

    name = "DLSS5 Neural Rendering"

    def __init__(
        self,
        options: Optional[Dict[str, Any]] = None,
        native_dir: Optional[str] = None,
        locator: Optional[RuntimeLocator] = None,
        bridge_loader=None,
        expected_size: Optional[tuple] = None,
    ):
        self.options = dict(options or {})
        self.locator = locator or RuntimeLocator(native_dir)
        self._bridge_loader = bridge_loader or bridge_mod.load_bridge
        self._bridge: Optional[NativeBridge] = None
        self._expected_size = expected_size  # (width, height) or None

        self._state = STATE_UNAVAILABLE
        self._error = ""
        self._frames = 0
        self._failed = False
        self._init_time = 0.0
        self._size = None  # (w, h) currently configured in the bridge
        self._runtime_version = "unknown"
        self._gpu = query_gpu_name()
        self._driver = query_display_driver_version()
        self._backend = "none"
        self._report = None

    # ----------------------------------------------------------- lifecycle
    def initialize(self) -> bool:
        """Probe the runtime for real. Never raises. Returns True when ready."""
        if self._state == STATE_READY:
            return True
        if self._failed:
            return False

        log_dlss5("Initializing...")
        started = time.perf_counter()

        report = self.locator.report()
        self._report = report
        for note in report.notes:
            log_dlss5(note)

        if not report.dlssnr.present:
            log_dlss5(f"Runtime: {report.describe()}")
            log_dlss5("Runtime not found")
            log_dlss5("Neural Rendering disabled")
            self._state = STATE_UNAVAILABLE
            self._error = "runtime not found"
            return False

        self._runtime_version = report.dlssnr.version
        log_dlss5(f"Runtime: nvngx_dlssnr.dll ({report.dlssnr.version})")
        log_dlss5(f"GPU: {self._gpu}")
        log_dlss5(f"Driver: {self._driver}")

        try:
            self._bridge = self._bridge_loader(self.locator.native_dir)
        except BridgeError as exc:
            return self._fail_init(f"bridge unavailable: {exc}")
        except Exception as exc:  # pragma: no cover - defensive
            return self._fail_init(f"bridge load error: {exc}")

        width = int(self.options.get("width") or 0)
        height = int(self.options.get("height") or 0)
        if self._expected_size and (width <= 0 or height <= 0):
            width, height = self._expected_size
        if width <= 0 or height <= 0:
            width, height = 640, 360  # probe size; real size applied on first frame

        if not self._create_feature(width, height, probe=True):
            return False

        # Smoke-test one synthetic frame so we verify EvaluateFeature too.
        try:
            probe = np.zeros((height, width, 3), dtype=np.uint8)
            probe[:] = 16
            self._bridge.process(probe)
        except BridgeError as exc:
            return self._fail_init(
                f"probe frame failed: {exc.message} [{bridge_mod.ngx_result_help(self._last_ngx())}]"
            )
        except Exception as exc:  # pragma: no cover - defensive
            return self._fail_init(f"probe frame failed: {exc}")

        self._state = STATE_READY
        self._error = ""
        self._init_time = (time.perf_counter() - started) * 1000.0
        st = self._bridge.status()
        self._backend = st.backend.decode("utf-8", "replace") if st.backend else "ngx-direct"
        log_dlss5(f"Backend: {self._backend}")
        log_dlss5(f"Input: {width}x{height} RGB8")
        log_dlss5(f"Output: {width}x{height} RGB8")
        log_dlss5(f"Model: nvngx_dlssnr.dll ({self._runtime_version})")
        log_dlss5(f"Preset: {self.options.get('preset', 1)}")
        log_dlss5(f"Passes: {self.options.get('passes', 1)}")
        log_dlss5(f"Initialized successfully ({self._init_time:.0f} ms)")
        return True

    def _create_feature(self, width: int, height: int, probe: bool = False) -> bool:
        """Build the NGX feature for a given frame size. Never raises."""
        opts = self.options
        work_scale = float(opts.get("work_scale", 1.0))
        work_w = _align8(width * work_scale)
        work_h = _align8(height * work_scale)

        fl_opts = FlNrOptions()
        fl_opts.width = int(width)
        fl_opts.height = int(height)
        fl_opts.work_width = int(work_w)
        fl_opts.work_height = int(work_h)
        fl_opts.passes = int(opts.get("passes", 1))
        fl_opts.preset = int(opts.get("preset", 1))
        fl_opts.style = int(opts.get("style", 1))
        fl_opts.intensity = float(opts.get("intensity", 0.35))
        fl_opts.local_tone = float(opts.get("local_tone", 1.0))
        fl_opts.local_structure = float(opts.get("local_structure", 1.0))
        fl_opts.skin_structure = float(opts.get("skin_structure", 1.0))
        fl_opts.exposure = float(opts.get("exposure", 1.0))
        fl_opts.auto_mask = int(bool(opts.get("auto_mask", 1)))
        fl_opts.temporal = int(bool(opts.get("temporal", 0)))

        log_dir = os.path.join(self.locator.native_dir, "logs")
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            log_dir = self.locator.native_dir

        try:
            self._bridge.init(fl_opts, self.locator.native_dir, log_dir)
        except BridgeError as exc:
            hint = bridge_mod.ngx_result_help(self._last_ngx())
            return self._fail_init(f"{exc.message} [{hint}]")
        except Exception as exc:  # pragma: no cover - defensive
            return self._fail_init(f"init error: {exc}")

        self._size = (width, height)
        return True

    # ------------------------------------------------------------- process
    def process(self, frame: np.ndarray) -> np.ndarray:
        """Enhance one frame. Fail-soft: any error disables DLSS 5 and passes
        the original frame through so RIFE/overlay keep running."""
        if self._failed or self._state == STATE_UNAVAILABLE:
            return frame
        if frame is None or getattr(frame, "ndim", 0) != 3:
            return frame

        height, width = frame.shape[:2]
        try:
            if self._state != STATE_READY:
                return frame
            if self._size != (width, height):
                # Resolution changed (window resize): rebuild the feature.
                log_dlss5(f"Resolution changed -> {width}x{height}, rebuilding feature")
                if not self._create_feature(width, height):
                    return frame
            out, _ = self._bridge.process(frame)
            self._frames += 1
            return out
        except BridgeError as exc:
            self._disable_runtime_error(exc.message)
            return frame
        except Exception as exc:  # pragma: no cover - defensive
            self._disable_runtime_error(str(exc))
            return frame

    # ------------------------------------------------------------ teardown
    def shutdown(self) -> None:
        if self._bridge is not None:
            try:
                self._bridge.shutdown()
            except Exception:
                pass
            self._bridge = None
        if self._state == STATE_READY:
            log_dlss5("Shutdown")

    # -------------------------------------------------------------- status
    def status(self) -> RendererStatus:
        runtime = (
            f"Found ({self._runtime_version})"
            if self._report is not None and self._report.dlssnr.present
            else "Not Found"
        )
        size = self._size or self._expected_size
        return RendererStatus(
            state=self._state,
            runtime=runtime,
            gpu=self._gpu,
            driver=self._driver,
            backend=self._backend,
            model=f"nvngx_dlssnr.dll ({self._runtime_version})",
            preset=str(self.options.get("preset", 1)),
            passes=int(self.options.get("passes", 1)),
            resolution=f"{size[0]}x{size[1]}" if size else "n/a",
            error=self._error,
            frames_processed=self._frames,
        )

    # ------------------------------------------------------------- helpers
    def _last_ngx(self) -> int:
        if self._bridge is None:
            return 0
        try:
            return int(self._bridge.status().last_ngx_result)
        except Exception:
            return 0

    def _fail_init(self, reason: str) -> bool:
        self._state = STATE_UNAVAILABLE
        self._error = reason
        log_dlss5("Initialization failed")
        log_dlss5(f"Reason: {reason}")
        log_dlss5("Falling back to RIFE-only pipeline")
        if self._bridge is not None:
            try:
                self._bridge.shutdown()
            except Exception:
                pass
        return False

    def _disable_runtime_error(self, reason: str) -> None:
        self._failed = True
        self._state = STATE_ERROR
        self._error = reason
        log_dlss5(f"Runtime error: {reason}")
        log_dlss5("DLSS5 error -> Neural Rendering disabled")
        log_dlss5("Falling back to RIFE-only pipeline")
        if self._bridge is not None:
            try:
                self._bridge.shutdown()
            except Exception:
                pass
            self._bridge = None

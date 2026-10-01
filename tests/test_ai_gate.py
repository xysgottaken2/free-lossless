"""An AI filter that cannot keep up is dropped instead of slowing the overlay.

The FSRCNN upscale takes a few milliseconds on a GPU and hundreds on the CPU, so
the overlay measures it once and, when it does not fit the frame budget, turns the
filter off for the session with the reason in the log.
"""
import time
import unittest
from unittest.mock import MagicMock

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy ships in requirements.txt
    np = None

from helpers import load_module, stubs


class FakeUpscaler:
    def __init__(self, cost_seconds=0.0, session=None):
        self.cost = cost_seconds
        self.session = MagicMock() if session is None else session
        if self.session is not None:
            self.session.get_providers.return_value = ["DmlExecutionProvider", "CPUExecutionProvider"]

    def upscale(self, frame):
        if self.cost:
            time.sleep(self.cost)
        return frame


class AiUpscalerGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                         "filters", "win32gui", "win32api", "win32con", "tkinter")
        cls.module = load_module("main", cls.deps, runtime=True)

    def setUp(self):
        self.messages = []
        self.module.diagnostics.ENABLED = False
        original = self.module.diagnostics.write
        self.module.diagnostics.write = lambda message: self.messages.append(str(message))
        self.addCleanup(setattr, self.module.diagnostics, "write", original)
        self.addCleanup(setattr, self.module.diagnostics, "ENABLED", True)
        self.app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        self.app.ai_mode = True
        self.app.filters_enabled = True
        self.app.ai_upscaler = FakeUpscaler()
        self.app.internal_res = (800, 600)
        self.app.target_fps = 120

    def test_a_fast_filter_stays_on(self):
        self.app.ai_upscaler = FakeUpscaler(cost_seconds=0.001)
        self.app._prepare_ai_upscaler()
        self.assertTrue(self.app.ai_mode)
        self.assertTrue(any("ativo" in message for message in self.messages))

    def test_a_slow_filter_is_dropped_for_the_session(self):
        self.app.ai_upscaler = FakeUpscaler(cost_seconds=0.06)   # limit is 20 ms at 120 FPS
        self.app._prepare_ai_upscaler()
        self.assertFalse(self.app.ai_mode)
        self.assertTrue(any("desativado" in message for message in self.messages))

    def test_a_slow_filter_is_accepted_when_the_target_frame_rate_is_low(self):
        self.app.target_fps = 30                                    # limit becomes 66 ms
        self.app.ai_upscaler = FakeUpscaler(cost_seconds=0.05)
        self.app._prepare_ai_upscaler()
        self.assertTrue(self.app.ai_mode)

    def test_a_model_that_never_loaded_is_dropped_without_running_it(self):
        upscaler = FakeUpscaler()
        upscaler.session = None
        upscaler.upscale = MagicMock()
        self.app.ai_upscaler = upscaler
        self.app._prepare_ai_upscaler()
        self.assertFalse(self.app.ai_mode)
        upscaler.upscale.assert_not_called()

    def test_a_crashing_filter_does_not_break_the_overlay(self):
        upscaler = FakeUpscaler()
        upscaler.upscale = MagicMock(side_effect=RuntimeError("DirectML exploded"))
        self.app.ai_upscaler = upscaler
        self.app._prepare_ai_upscaler()
        self.assertFalse(self.app.ai_mode)

    def test_nothing_happens_when_ai_upscaling_is_off(self):
        upscaler = FakeUpscaler()
        upscaler.upscale = MagicMock()
        self.app.ai_mode = False
        self.app.ai_upscaler = upscaler
        self.app._prepare_ai_upscaler()
        upscaler.upscale.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class FilterToggleTests(unittest.TestCase):
    """The image filters can be switched off entirely, like frame interpolation."""

    @classmethod
    def setUpClass(cls):
        cls.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                         "filters", "win32gui", "win32api", "win32con", "tkinter")
        cls.module = load_module("main", cls.deps, runtime=True)

    def setUp(self):
        self.module.diagnostics.ENABLED = False
        self.app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        self.app.display_dim = (1920, 1080)
        self.app.ai_mode = True
        self.app.ai_upscaler = MagicMock()
        self.app.fsr_mode = True
        self.app.sharpness = 1.0
        self.app.upscale_algo = 1
        self.app.filters_enabled = False
        self.app.filter_chain = None
        self.deps["cv2"].reset_mock()
        self.deps["filters"].reset_mock()

    @staticmethod
    def frame():
        return np.zeros((600, 800, 3), dtype=np.uint8)

    def test_frames_are_only_resized_when_the_filters_are_off(self):
        self.app._render_for_display(self.frame())
        self.deps["filters"].AMDFilters.apply_cas.assert_not_called()
        self.deps["filters"].AMDFilters.apply_unsharp.assert_not_called()
        self.deps["filters"].AMDFilters.apply_easu.assert_not_called()
        self.app.ai_upscaler.upscale.assert_not_called()
        # A plain resize is all that is left, straight to the display size.
        self.assertEqual(self.deps["cv2"].resize.call_args.args[1], (1920, 1080))

    def test_the_image_chain_runs_when_the_filters_are_on(self):
        self.app.filters_enabled = True
        self.app._render_for_display(self.frame())
        self.app.ai_upscaler.upscale.assert_called_once()

    def test_the_filter_gate_is_skipped_when_the_filters_are_off(self):
        self.app.ai_upscaler = MagicMock()
        self.app.ai_upscaler.upscale = MagicMock()
        self.app.filters_enabled = False
        self.app._prepare_ai_upscaler()
        self.app.ai_upscaler.upscale.assert_not_called()

    def test_disabling_the_filters_clears_the_ai_and_fsr_modes(self):
        source = {"source_type": "window", "hwnd": 7, "title": "Game", "mode": "bitblt",
                  "fps": 120, "scale": "1.0", "algo": "NVIDIA AI SuperRes", "sharpness": 40,
                  "engine_type": "Fast (DIS Flow)", "filters_enabled": False, "fg_enabled": False}
        self.deps["ui"].GameSelectorUI.return_value.get_selection.return_value = source
        self.deps["selector"].get_source_rect.return_value = (0, 0, 640, 480)
        self.deps["selector"].get_source_monitor_rect.return_value = (0, 0, 1920, 1080)
        app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        self.assertTrue(app.select_game())
        self.assertFalse(app.filters_enabled)
        self.assertFalse(app.ai_mode)
        self.assertFalse(app.fsr_mode)
        self.assertIsNone(app.ai_upscaler)
        self.assertEqual(app.sharpness, 0.0)
        self.deps["filters"].NvidiaAIUpscaler.assert_not_called()

    def test_the_filters_stay_on_by_default(self):
        source = {"source_type": "window", "hwnd": 7, "title": "Game", "mode": "bitblt",
                  "fps": 120, "scale": "1.0", "algo": "Bicubic", "sharpness": 40,
                  "engine_type": "Fast (DIS Flow)", "fg_enabled": False}
        self.deps["ui"].GameSelectorUI.return_value.get_selection.return_value = source
        self.deps["selector"].get_source_rect.return_value = (0, 0, 640, 480)
        self.deps["selector"].get_source_monitor_rect.return_value = (0, 0, 1920, 1080)
        app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        self.assertTrue(app.select_game())
        self.assertTrue(app.filters_enabled)
        self.assertGreater(app.sharpness, 0)


if __name__ == "__main__":
    unittest.main()

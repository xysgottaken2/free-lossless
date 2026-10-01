"""An AI filter that cannot keep up is dropped instead of slowing the overlay.

The FSRCNN upscale takes a few milliseconds on a GPU and hundreds on the CPU, so
the overlay measures it once and, when it does not fit the frame budget, turns the
filter off for the session with the reason in the log.
"""
import time
import unittest
from unittest.mock import MagicMock

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

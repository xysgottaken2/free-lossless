"""The overlay window must stay click-through while it runs.

Windows re-applies styles when SDL recreates the window, and it can hand focus back
to the overlay after the Win key or Alt+Tab. Both cases used to leave a window the
user could click, drag and move, so the styles are asserted on every change and from
time to time while the overlay is up.
"""
import unittest
from unittest.mock import MagicMock, patch

from helpers import load_module, stubs


class OverlayWindowStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                         "filters", "win32gui", "win32api", "win32con", "tkinter")
        cls.module = load_module("main", cls.deps, runtime=True)

    def setUp(self):
        # The stubs are shared by the class, so every test starts from a clean mock.
        for name in ("win32gui", "win32api", "pygame"):
            # side_effect too: the stubs are shared, and a test that makes a call fail
            # must not affect the next one.
            self.deps[name].reset_mock(return_value=True, side_effect=True)
        self.ctypes = MagicMock()
        patch.object(self.module, "ctypes", self.ctypes).start()
        self.addCleanup(patch.stopall)
        self.deps["pygame"].display.get_wm_info.return_value = {"window": 4242}
        self.deps["win32gui"].GetWindowLong.return_value = 0
        self.deps["win32con"].GWL_EXSTYLE = -20
        self.deps["win32con"].HWND_TOPMOST = -1
        self.deps["win32con"].SWP_NOACTIVATE = 0x0010
        self.deps["win32con"].SWP_SHOWWINDOW = 0x0040
        self.app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        self.app._apply_overlay_window_style((10, 20), (1920, 1080))

    def test_the_window_becomes_click_through_and_never_activates(self):
        style = self.deps["win32gui"].SetWindowLong.call_args.args[2]
        self.assertTrue(style & self.module.WS_EX_TRANSPARENT)
        self.assertTrue(style & self.module.WS_EX_LAYERED)
        self.assertTrue(style & self.module.WS_EX_NOACTIVATE)

    def test_the_window_stays_on_top_without_stealing_focus(self):
        args = self.deps["win32gui"].SetWindowPos.call_args.args
        self.assertEqual(args[0], 4242)
        self.assertEqual(args[1], -1)                       # HWND_TOPMOST
        self.assertEqual(args[2:6], (10, 20, 1920, 1080))
        self.assertTrue(args[6] & 0x0010)                   # SWP_NOACTIVATE

    def test_the_overlay_is_excluded_from_screen_capture(self):
        self.assertEqual(self.ctypes.windll.user32.SetWindowDisplayAffinity.call_args.args,
                         (4242, self.module.WDA_EXCLUDEFROMCAPTURE))

    def test_existing_styles_are_preserved(self):
        self.deps["win32gui"].GetWindowLong.return_value = 0x00000080  # WS_EX_TOOLWINDOW
        self.app._apply_overlay_window_style((0, 0), (800, 600))
        style = self.deps["win32gui"].SetWindowLong.call_args.args[2]
        self.assertTrue(style & 0x00000080)

    def test_nothing_is_written_when_the_styles_are_already_right(self):
        self.deps["win32gui"].GetWindowLong.return_value = (
            self.module.WS_EX_LAYERED | self.module.WS_EX_TRANSPARENT | self.module.WS_EX_NOACTIVATE)
        self.deps["win32gui"].SetWindowLong.reset_mock()
        self.app._apply_overlay_window_style((0, 0), (800, 600))
        self.deps["win32gui"].SetWindowLong.assert_not_called()
        self.assertTrue(self.deps["win32gui"].SetWindowPos.called)   # topmost is cheap to redo

    def test_a_broken_window_handle_does_not_break_the_overlay(self):
        self.deps["pygame"].display.get_wm_info.side_effect = Exception("no window yet")
        self.app._apply_overlay_window_style((0, 0), (800, 600))

    def test_win32_failures_are_only_logged(self):
        self.deps["win32gui"].SetWindowLong.side_effect = Exception("access denied")
        self.app._apply_overlay_window_style((0, 0), (800, 600))


class StyleRefreshCadenceTests(unittest.TestCase):
    """The refresh happens while the overlay runs, not only when it opens."""

    @classmethod
    def setUpClass(cls):
        cls.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                         "filters", "win32gui", "win32api", "win32con", "tkinter")
        cls.module = load_module("main", cls.deps, runtime=True)

    def test_the_refresh_interval_is_a_fraction_of_a_second(self):
        self.assertGreater(self.module.WINDOW_STYLE_REFRESH_SECONDS, 0)
        self.assertLessEqual(self.module.WINDOW_STYLE_REFRESH_SECONDS, 1.0)

    def test_the_display_loop_calls_the_helper(self):
        import inspect
        source = inspect.getsource(self.module.FrameGenerationApp.run)
        self.assertIn("_apply_overlay_window_style", source)
        self.assertIn("WINDOW_STYLE_REFRESH_SECONDS", source)


if __name__ == "__main__":
    unittest.main()

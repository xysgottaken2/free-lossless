import unittest
from unittest.mock import MagicMock

from helpers import load_module, stubs


class AppSourceTests(unittest.TestCase):
    def setUp(self):
        self.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                          "filters", "win32gui", "win32api", "win32con", "tkinter")
        self.module = load_module("main", self.deps)
        self.app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        self.source = {
            "source_type": "display", "device": r"\\.\DISPLAY2", "title": "Display 2",
            "mode": "bitblt", "fps": 60, "scale": "Fullscreen", "algo": "Lanczos",
            "sharpness": 20, "engine_type": "Fast (DIS Flow)",
        }
        self.deps["ui"].GameSelectorUI.return_value.get_selection.return_value = self.source
        self.deps["selector"].get_source_rect.return_value = (-1920, -100, 0, 980)
        self.deps["selector"].get_source_monitor_rect.return_value = (-1920, -100, 0, 980)

    def test_fullscreen_uses_selected_display_not_primary_metrics(self):
        self.assertTrue(self.app.select_game())
        self.assertEqual(self.app.display_dim, (1920, 1080))
        self.deps["capture"].ScreenCapture.assert_called_once_with(
            region=(-1920, -100, 0, 980), mode="bitblt", desktop_coordinates=True,
        )
        self.deps["win32api"].GetSystemMetrics.assert_not_called()

    def test_window_source_retains_scale_and_mode(self):
        self.source.update(source_type="window", hwnd=10, scale="1.5", mode="dxcam")
        self.deps["selector"].get_source_rect.return_value = (100, 100, 500, 300)
        self.assertTrue(self.app.select_game())
        self.assertEqual(self.app.display_dim, (600, 300))
        self.deps["capture"].ScreenCapture.assert_called_once_with(
            region=(100, 100, 500, 300), mode="dxcam", desktop_coordinates=True,
        )

    def test_cancel_and_stale_source_do_not_initialize_capture(self):
        self.deps["ui"].GameSelectorUI.return_value.get_selection.return_value = None
        self.assertFalse(self.app.select_game())
        self.deps["capture"].ScreenCapture.assert_not_called()
        self.deps["ui"].GameSelectorUI.return_value.get_selection.return_value = self.source
        self.deps["selector"].get_source_rect.side_effect = ValueError("disconnected")
        self.assertFalse(self.app.select_game())
        self.deps["capture"].ScreenCapture.assert_not_called()
        self.module.messagebox.showerror.assert_called_once()

    def test_capture_worker_stops_when_display_is_unplugged(self):
        self.app.running = True
        self.app.target_source = self.source
        self.app.target_fps = 60
        self.app.capture = MagicMock()
        self.deps["selector"].get_source_rect.side_effect = ValueError("disconnected")
        self.app.capture_worker()
        self.assertFalse(self.app.running)
        self.app.capture.capture_frame.assert_not_called()

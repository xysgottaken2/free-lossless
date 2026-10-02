import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from helpers import load_module, stubs

try:
    import numpy as np
except ImportError:  # pragma: no cover - the CI image installs numpy
    np = None

try:
    import cv2 as real_cv2
except ImportError:  # pragma: no cover - the CI image installs OpenCV
    real_cv2 = None


def output(device, rect):
    return SimpleNamespace(devicename=device, desc=SimpleNamespace(
        DesktopCoordinates=SimpleNamespace(left=rect[0], top=rect[1], right=rect[2], bottom=rect[3]),
    ))


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.deps = stubs("dxcam", "numpy", "cv2", "win32gui", "win32api", "win32ui", "win32con")
        self.module = load_module("capture", self.deps)
        self.patch = patch.dict(sys.modules, self.deps)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.dxcam = self.deps["dxcam"]
        setattr(self.dxcam, "__factory", SimpleNamespace(outputs=[
            [output(r"\\.\DISPLAY2", (0, 0, 2560, 1440))],
            [output(r"\\.\DISPLAY1", (-1920, -200, 0, 880))],
        ]))
        self.deps["win32api"].GetMonitorInfo.return_value = {
            "Device": r"\\.\DISPLAY1", "Monitor": (-1920, -200, 0, 880),
        }

    def capture(self, rect, mode="dxcam"):
        return self.module.ScreenCapture(region=rect, mode=mode, desktop_coordinates=True)

    def test_display_on_second_gpu_uses_exact_output_and_local_coordinates(self):
        cap = self.capture((-1920, -200, 0, 880))
        cap.capture_frame()
        self.dxcam.create.assert_called_once_with(device_idx=1, output_idx=0, output_color="RGB")
        self.dxcam.create.return_value.grab.assert_called_once_with(region=(0, 0, 1920, 1080))

    def test_window_on_secondary_monitor(self):
        cap = self.capture((-1800, -100, -800, 600))
        cap.capture_frame()
        self.dxcam.create.return_value.grab.assert_called_once_with(region=(120, 100, 1120, 800))
        cap.capture_frame()
        self.dxcam.create.assert_called_once()

    def test_window_crossing_monitors_uses_bitblt_without_changing_source(self):
        cap = self.capture((-500, 0, 500, 600))
        cap._capture_bitblt = MagicMock(return_value="frame")
        self.assertEqual(cap.capture_frame(), "frame")
        self.dxcam.create.assert_not_called()
        self.assertEqual(cap.region, (-500, 0, 500, 600))
        self.assertEqual(cap.mode, "dxcam")

    def test_missing_dxgi_output_falls_back_instead_of_capturing_wrong_monitor(self):
        self.deps["win32api"].GetMonitorInfo.return_value["Device"] = "unavailable"
        cap = self.capture((-1920, -200, 0, 880))
        cap._capture_bitblt = MagicMock(return_value="frame")
        self.assertEqual(cap.capture_frame(), "frame")
        self.assertEqual(cap.mode, "bitblt")
        self.dxcam.create.assert_not_called()

    def test_unchanged_frame_never_blocks_waiting_for_unstarted_loop(self):
        cap = self.capture((-1920, -200, 0, 880))
        self.dxcam.create.return_value.grab.return_value = None
        self.assertIsNone(cap.capture_frame())
        self.dxcam.create.return_value.get_latest_frame.assert_not_called()
        self.assertEqual(cap.mode, "dxcam")

    def test_bitblt_preserves_negative_origin_and_uses_screen_dc(self):
        cap = self.capture((-1920, -200, 0, 880), mode="bitblt")
        cap.capture_frame()
        self.dxcam.create.assert_not_called()
        self.deps["win32gui"].GetDC.assert_called_once_with(0)
        cap._save_dc.BitBlt.assert_called_once_with(
            (0, 0), (1920, 1080), cap._mfc_dc, (-1920, -200), self.deps["win32con"].SRCCOPY,
        )
        cap.stop_capture()
        self.deps["win32gui"].ReleaseDC.assert_called_once_with(0, self.deps["win32gui"].GetDC.return_value)

    def test_switch_output_when_window_moves_to_another_monitor(self):
        cap = self.capture((-1920, -200, 0, 880))
        cap.capture_frame()
        self.deps["win32api"].GetMonitorInfo.return_value = {
            "Device": r"\\.\DISPLAY2", "Monitor": (0, 0, 2560, 1440),
        }
        cap.region = (10, 20, 510, 520)
        cap.capture_frame()
        self.dxcam.create.assert_called_with(device_idx=0, output_idx=0, output_color="RGB")
        self.dxcam.create.return_value.grab.assert_called_with(region=(10, 20, 510, 520))


class BitBltPixelFormatTests(unittest.TestCase):
    """The BitBlt path must hand BGRA buffers to OpenCV instead of slicing them."""

    def setUp(self):
        self.deps = stubs("dxcam", "win32gui", "win32api", "win32ui", "win32con", "cv2")
        self.module = load_module("capture", self.deps)
        self.patch = patch.dict(sys.modules, self.deps)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.module.np = np
        self.cap = self.module.ScreenCapture.__new__(self.module.ScreenCapture)
        self.cap.mode = "bitblt"
        self.cap.region = (0, 0, 2, 2)
        self.cap._last_dims = (2, 2)
        self.cap._save_dc = MagicMock()
        self.cap._save_bitmap = MagicMock()
        self.cap._mfc_dc = MagicMock()
        self.cap._hwnd_dc = MagicMock()
        # Four BGRA pixels (a 2x2 frame).
        self.cap._save_bitmap.GetBitmapBits.return_value = bytes([
            10, 20, 30, 255, 40, 50, 60, 255,
            70, 80, 90, 255, 100, 110, 120, 255,
        ])
        self.cv2 = self.deps["cv2"]
        self.cv2.cvtColor.return_value = "rgb-frame"

    def test_bitblt_hands_the_buffer_to_cvtcolor_once(self):
        self.assertEqual(self.cap._capture_bitblt(), "rgb-frame")
        self.cv2.cvtColor.assert_called_once()
        frame, conversion = self.cv2.cvtColor.call_args.args
        self.assertEqual(conversion, self.cv2.COLOR_BGRA2RGB)
        self.assertEqual(frame.shape, (2, 2, 4))
        self.assertEqual(frame.dtype, np.uint8)

    def test_bitblt_keeps_using_the_cached_gdi_resources(self):
        self.cap._capture_bitblt()
        self.cap._capture_bitblt()
        self.assertEqual(self.cap._save_bitmap.GetBitmapBits.call_count, 2)
        self.deps["win32ui"].CreateCompatibleDC.assert_not_called()


@unittest.skipIf(real_cv2 is None or np is None, "OpenCV is not installed")
class RealConversionTests(unittest.TestCase):
    def test_cvtcolor_matches_the_manual_channel_reversal(self):
        """Same pixels as the old slicing, without the ~11 ms per 1080p frame."""
        rng = np.random.default_rng(3)
        bgra = rng.integers(0, 256, (32, 32, 4), dtype=np.uint8)
        expected = bgra[:, :, :3][:, :, ::-1]
        converted = real_cv2.cvtColor(bgra, real_cv2.COLOR_BGRA2RGB)
        self.assertTrue(np.array_equal(converted, expected))
        self.assertTrue(converted.flags["C_CONTIGUOUS"])


if __name__ == "__main__":
    unittest.main()

"""Sharpening/upscaling behaviour, checked against the real OpenCV when installed."""
import unittest

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - the CI image installs both
    cv2 = None
    np = None

from filters import AMDFilters


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class ContrastAdaptiveSharpeningTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(7)
        base = np.zeros((120, 160, 3), dtype=np.uint8)
        base[:, :] = (90, 110, 130)
        base = cv2.add(base, rng.integers(0, 12, base.shape, dtype=np.uint8))
        base = cv2.GaussianBlur(base, (3, 3), 0)  # soft texture, the case CAS repairs
        self.image = base

    def acutance(self, image):
        return float(cv2.Laplacian(cv2.cvtColor(image, cv2.COLOR_RGB2GRAY), cv2.CV_64F).var())

    def test_zero_amount_is_a_no_op(self):
        self.assertIs(AMDFilters.apply_cas(self.image, 0), self.image)
        self.assertIs(AMDFilters.apply_unsharp(self.image, 0), self.image)

    def test_result_keeps_shape_and_type(self):
        for amount in (0.1, 0.3, 0.8, 2.0, 5.0):
            with self.subTest(amount=amount):
                result = AMDFilters.apply_cas(self.image, amount)
                self.assertEqual(result.shape, self.image.shape)
                self.assertEqual(result.dtype, np.uint8)

    def test_sharpening_raises_acutance_without_drifting_the_mean(self):
        result = AMDFilters.apply_cas(self.image, 0.5)
        self.assertGreater(self.acutance(result), self.acutance(self.image))
        # Saturating uint8 maths must not shift the overall brightness.
        self.assertLess(abs(float(result.mean()) - float(self.image.mean())), 2.5)

    def test_hard_edges_are_not_oversharpened_into_halos(self):
        step = np.zeros((80, 80, 3), dtype=np.uint8)
        step[:, 40:] = 255
        result = AMDFilters.apply_cas(step, 1.0)
        dark_side = result[:, :30].max()
        bright_side = result[:, 50:].min()
        self.assertLessEqual(int(dark_side), 8)   # no bright fringe next to the edge
        self.assertGreaterEqual(int(bright_side), 247)  # no dark fringe either

    def test_garbage_amounts_are_ignored(self):
        for amount in (None, "sharp", -1):
            with self.subTest(amount=amount):
                result = AMDFilters.apply_cas(self.image, amount)
                self.assertEqual(result.shape, self.image.shape)

    def test_unsharp_mask_also_sharpens(self):
        result = AMDFilters.apply_unsharp(self.image, 0.6)
        self.assertGreater(self.acutance(result), self.acutance(self.image))


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class UpscaleTests(unittest.TestCase):
    def test_easu_reaches_the_requested_size(self):
        image = np.zeros((60, 80, 3), dtype=np.uint8)
        upscaled = AMDFilters.apply_easu(image, (320, 240))
        self.assertEqual(upscaled.shape, (240, 320, 3))
        self.assertEqual(upscaled.dtype, np.uint8)

    def test_easu_skips_work_when_the_size_already_matches(self):
        image = np.zeros((60, 80, 3), dtype=np.uint8)
        self.assertIs(AMDFilters.apply_easu(image, (80, 60)), image)

    def test_upscaling_is_cheap_enough_for_real_time(self):
        """The old Lanczos+CAS path cost ~127 ms/frame at 1080p; keep it far below that."""
        import time
        rng = np.random.default_rng(11)
        image = rng.integers(0, 255, (600, 800, 3), dtype=np.uint8)
        started = time.perf_counter()
        runs = 5
        for _ in range(runs):
            AMDFilters.apply_easu(AMDFilters.apply_cas(image, 0.4), (1920, 1080))
        average_ms = (time.perf_counter() - started) / runs * 1000
        self.assertLess(average_ms, 60.0, f"FSR path took {average_ms:.1f} ms per frame")


if __name__ == "__main__":
    unittest.main()

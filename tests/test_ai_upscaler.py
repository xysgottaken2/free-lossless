"""The AI SuperRes filter: the model that ships must actually work.

The repository used to carry a placeholder file that no runtime could load, so the
filter silently returned the frame unchanged. These tests fail if that comes back.
"""
import unittest
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - the CI image installs both
    cv2 = None
    np = None

try:
    import onnxruntime  # noqa: F401
except ImportError:  # pragma: no cover - ships with the app
    onnxruntime = None

from filters import NvidiaAIUpscaler

MODEL = Path(__file__).resolve().parents[1] / "models" / "fsrcnn_x2.onnx"


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
@unittest.skipIf(onnxruntime is None, "onnxruntime is not installed")
class ShippedModelTests(unittest.TestCase):
    def setUp(self):
        self.upscaler = NvidiaAIUpscaler(str(MODEL))
        if self.upscaler.session is None:
            self.fail("the shipped model could not be loaded by onnxruntime")

    def test_the_model_file_is_a_real_onnx_graph(self):
        self.assertGreater(MODEL.stat().st_size, 20_000)
        self.assertLess(MODEL.stat().st_size, 4_000_000)

    def test_upscaling_doubles_the_size_and_stays_uint8(self):
        image = np.random.default_rng(3).integers(0, 255, (48, 64, 3), dtype=np.uint8)
        result = self.upscaler.upscale(image)
        self.assertEqual(result.shape, (96, 128, 3))
        self.assertEqual(result.dtype, np.uint8)

    def test_the_input_size_is_not_fixed(self):
        for height, width in ((32, 32), (40, 72), (24, 100)):
            with self.subTest(size=(height, width)):
                image = np.zeros((height, width, 3), dtype=np.uint8)
                self.assertEqual(self.upscaler.upscale(image).shape, (height * 2, width * 2, 3))

    def test_the_result_is_a_sharper_upscale_and_not_a_copy(self):
        """A working network beats plain bicubic on a downscaled natural pattern."""
        rng = np.random.default_rng(5)
        base = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
        original = cv2.GaussianBlur(base, (0, 0), 1.2)
        small = cv2.resize(original, (32, 32), interpolation=cv2.INTER_AREA)
        ai = self.upscaler.upscale(small).astype(np.float32)
        bicubic = cv2.resize(small, (64, 64), interpolation=cv2.INTER_CUBIC).astype(np.float32)
        target = original.astype(np.float32)
        ai_error = float(np.mean((ai - target) ** 2))
        bicubic_error = float(np.mean((bicubic - target) ** 2))
        self.assertFalse(np.array_equal(ai, small.repeat(2, axis=0).repeat(2, axis=1)))
        self.assertLess(ai_error, bicubic_error)

    def test_the_same_input_always_gives_the_same_output(self):
        image = np.random.default_rng(9).integers(0, 255, (32, 32, 3), dtype=np.uint8)
        first = self.upscaler.upscale(image)
        second = self.upscaler.upscale(image)
        self.assertTrue(np.array_equal(first, second))


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class BrokenModelTests(unittest.TestCase):
    """A missing or invalid model degrades to 'no filter' instead of crashing."""

    def test_a_missing_file_leaves_the_filter_off(self):
        upscaler = NvidiaAIUpscaler(str(Path(__file__).resolve().parent / "no_model_here.onnx"))
        self.assertIsNone(upscaler.session)
        image = np.zeros((16, 16, 3), dtype=np.uint8)
        self.assertIs(upscaler.upscale(image), image)

    def test_a_corrupt_file_leaves_the_filter_off(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / "broken.onnx"
            broken.write_bytes(b"\n" * 4096)
            upscaler = NvidiaAIUpscaler(str(broken))
            self.assertIsNone(upscaler.session)
            image = np.full((16, 16, 3), 42, dtype=np.uint8)
            self.assertIs(upscaler.upscale(image), image)


if __name__ == "__main__":
    unittest.main()

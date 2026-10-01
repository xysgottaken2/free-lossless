"""The post-processing filters: what they promise, on the real OpenCV.

They are the ReShade-style looks (LumaSharpen, Vibrance, Clarity, Contrast) applied
by the overlay itself, so a broken filter must never wrap colours around or bias the
brightness of the frame.
"""
import time
import unittest

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - the CI image installs both
    cv2 = None
    np = None

import effects
from effects import EffectChain
from settings import FILTER_PRESETS


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class EffectBasicsTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(4)
        base = np.full((240, 320, 3), (110, 120, 140), dtype=np.uint8)
        base = cv2.add(base, rng.integers(0, 24, base.shape, dtype=np.uint8))
        texture = cv2.resize(rng.integers(0, 255, (120, 160), dtype=np.uint8), (320, 240))
        texture = cv2.GaussianBlur(texture, (0, 0), 0.8)
        weight = np.full((240, 320), 25, dtype=np.uint8)
        for channel in range(3):
            base[:, :, channel] = cv2.add(base[:, :, channel],
                                          cv2.multiply(texture, weight, scale=1.0 / 255.0))
        self.image = base

    def acutance(self, image):
        return float(cv2.Laplacian(cv2.cvtColor(image, cv2.COLOR_RGB2GRAY), cv2.CV_64F).var())

    def mean(self, image):
        return float(image.mean())

    def assert_sane(self, result):
        self.assertEqual(result.shape, self.image.shape)
        self.assertEqual(result.dtype, np.uint8)
        self.assertGreaterEqual(int(result.min()), 0)
        self.assertLessEqual(int(result.max()), 255)


class SingleEffectTests(EffectBasicsTests):
    def test_luma_sharpen_raises_detail_without_changing_brightness(self):
        result = effects.luma_sharpen(self.image, 0.6, 24)
        self.assertGreater(self.acutance(result), self.acutance(self.image) * 1.5)
        self.assertAlmostEqual(self.mean(result), self.mean(self.image), delta=0.5)
        self.assert_sane(result)

    def test_luma_sharpen_clamp_limits_halos(self):
        """A hard edge must not grow: the correction is clamped, not the whole image."""
        edge = np.zeros((60, 60, 3), dtype=np.uint8)
        edge[:, 30:] = 255
        free = effects.luma_sharpen(edge, 1.0, 255)
        clamped = effects.luma_sharpen(edge, 1.0, 8)
        self.assertLessEqual(int(clamped.max()) - int(edge.max()), 255)
        self.assertLessEqual(np.abs(clamped.astype(np.int16) - edge.astype(np.int16)).max(),
                             np.abs(free.astype(np.int16) - edge.astype(np.int16)).max())

    def test_luma_sharpen_without_amount_is_a_no_op(self):
        self.assertIs(effects.luma_sharpen(self.image, 0.0), self.image)

    def test_vibrance_boosts_muted_colours_more_than_saturated_ones(self):
        muted = self.image[:, :160].copy()
        saturated = np.zeros((240, 160, 3), dtype=np.uint8)
        saturated[:, :] = (230, 40, 40)
        image = np.concatenate([muted, saturated], axis=1)
        result = effects.vibrance(image, 0.6)

        def saturation(part):
            return float(cv2.cvtColor(part, cv2.COLOR_RGB2HSV)[:, :, 1].mean())

        muted_gain = saturation(result[:, :160]) - saturation(image[:, :160])
        saturated_gain = saturation(result[:, 160:]) - saturation(image[:, 160:])
        self.assertGreater(muted_gain, saturated_gain)
        self.assert_sane(result)

    def test_vibrance_keeps_greys_untouched(self):
        grey = np.full((60, 60, 3), 128, dtype=np.uint8)
        result = effects.vibrance(grey, 0.8)
        self.assertTrue(np.array_equal(result, grey))

    def test_clarity_adds_local_contrast(self):
        result = effects.clarity(self.image, 0.3)
        self.assertGreater(self.acutance(result), self.acutance(self.image))
        self.assertAlmostEqual(self.mean(result), self.mean(self.image), delta=0.5)
        self.assert_sane(result)

    def test_contrast_keeps_the_extremes_and_expands_the_middle(self):
        ramp = np.arange(256, dtype=np.uint8).repeat(2).reshape(1, 512, 1).repeat(3, axis=2)
        result = effects.contrast(ramp, 0.4)
        self.assertEqual(int(result[0, 0, 0]), 0)
        self.assertEqual(int(result[0, -1, 0]), 255)
        self.assertGreater(float(result.std()), float(ramp.std()))
        self.assertAlmostEqual(float(result.mean()), float(ramp.mean()), delta=1.0)

    def test_contrast_without_strength_is_a_no_op(self):
        self.assertIs(effects.contrast(self.image, 0.0), self.image)


class PresetTests(EffectBasicsTests):
    def test_the_presets_match_the_settings_choices(self):
        self.assertEqual(tuple(effects.PRESET_ORDER), FILTER_PRESETS)
        self.assertEqual(set(effects.PRESETS), set(FILTER_PRESETS))

    def test_off_returns_the_frame_untouched(self):
        chain = EffectChain("Off")
        self.assertFalse(chain.enabled)
        self.assertIs(chain.apply(self.image), self.image)

    def test_an_unknown_preset_falls_back_to_off(self):
        for value in ("Nope", None, 7, ""):
            with self.subTest(value=value):
                chain = EffectChain(value)
                self.assertEqual(chain.preset, "Off")
                self.assertFalse(chain.enabled)

    def test_every_preset_changes_the_image_and_keeps_it_valid(self):
        for name in ("Soft", "Sharp", "Vivid"):
            with self.subTest(preset=name):
                chain = EffectChain(name)
                result = chain.apply(self.image.copy())
                self.assertFalse(np.array_equal(result, self.image))
                self.assert_sane(result)
                self.assertGreater(self.acutance(result), self.acutance(self.image))

    def test_the_chain_can_be_switched_between_presets(self):
        chain = EffectChain("Soft")
        soft = chain.apply(self.image.copy())
        chain.set_preset("Vivid")
        vivid = chain.apply(self.image.copy())
        self.assertFalse(np.array_equal(soft, vivid))
        chain.set_preset("Off")
        self.assertIs(chain.apply(self.image), self.image)

    def test_a_failing_effect_is_skipped_and_reported(self):
        messages = []
        original = effects.diagnostics.write_now
        effects.diagnostics.write_now = lambda label, message: messages.append(f"{label}: {message}")
        self.addCleanup(setattr, effects.diagnostics, "write_now", original)
        self.addCleanup(effects.EFFECTS.pop, "explode", None)
        effects.EFFECTS["explode"] = lambda frame, **kwargs: 1 / 0
        effects.PRESETS["Broken"] = (("explode", {}), ("contrast", {"strength": 0.3}))
        self.addCleanup(effects.PRESETS.pop, "Broken", None)

        result = EffectChain("Broken").apply(self.image.copy())
        self.assertTrue(any("explode" in message for message in messages))
        self.assertFalse(np.array_equal(result, self.image))   # the rest still runs

    def test_the_presets_are_cheap_enough_for_real_time(self):
        """At the internal resolution a preset must fit in a frame's budget."""
        frame = np.zeros((600, 800, 3), dtype=np.uint8)
        for name in ("Soft", "Sharp", "Vivid"):
            with self.subTest(preset=name):
                chain = EffectChain(name)
                chain.apply(frame)
                start = time.perf_counter()
                for _ in range(3):
                    chain.apply(frame)
                cost = (time.perf_counter() - start) / 3 * 1000
                self.assertLess(cost, 25.0, f"{name} custou {cost:.1f} ms por quadro")


@unittest.skipIf(cv2 is None, "OpenCV is not installed")
class ReShadeDiscoveryTests(unittest.TestCase):
    def test_files_that_show_a_reshade_installation(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(effects.reshade_files(directory), [])
            (Path(directory) / "ReShade.ini").write_text("", encoding="utf-8")
            (Path(directory) / "dxgi.dll").write_bytes(b"")
            (Path(directory) / "reshade-shaders").mkdir()
            found = effects.reshade_files(directory)
            self.assertIn("ReShade.ini", found)
            self.assertIn("dxgi.dll", found)
            self.assertIn("reshade-shaders", found)

    def test_a_missing_folder_or_process_is_not_an_error(self):
        self.assertEqual(effects.reshade_files(None), [])
        self.assertEqual(effects.reshade_files("/pasta/que/nao/existe"), [])
        self.assertEqual(effects.reshade_installed(None), (None, []))

    def test_looking_up_a_game_that_is_not_running_reports_nothing(self):
        directory, files = effects.reshade_installed("jogo-que-nao-existe-12345.exe")
        self.assertIsNone(directory)
        self.assertEqual(files, [])


if __name__ == "__main__":
    unittest.main()

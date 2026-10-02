"""The resolution the overlay pipeline works at.

Everything used to be capped at 800x600, so a 1080p overlay showed a 2.4x blow-up of a
small image — the "144p" look the user reported. These rules keep at most one
resampling step, and none when the source already matches the display.
"""
import unittest
from unittest.mock import MagicMock

from helpers import load_module, stubs
from settings import DEFAULT_SETTINGS, INTERNAL_RESOLUTIONS, normalize_settings


class ResolutionRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                         "filters", "win32gui", "win32api", "win32con", "tkinter")
        cls.module = load_module("main", cls.deps, runtime=True)
        cls.rule = staticmethod(cls.module.internal_resolution_for)

    def test_a_fullscreen_game_is_processed_at_its_own_resolution(self):
        """1080p on a 1080p display: no resampling at all."""
        self.assertEqual(self.rule((1920, 1080), (1920, 1080), "Bicubic"), (1920, 1080))

    def test_the_window_is_never_scaled_up_before_the_filters(self):
        self.assertEqual(self.rule((1280, 720), (1920, 1080), "Lanczos"), (1280, 720))

    def test_a_window_larger_than_the_overlay_is_capped_at_the_overlay(self):
        self.assertEqual(self.rule((2560, 1440), (1280, 720), "Bicubic"), (1280, 720))

    def test_the_neural_upscaler_gets_half_of_the_display(self):
        """The model doubles the frame, so half the display lands exactly on it."""
        self.assertEqual(self.rule((1920, 1080), (1920, 1080), "NVIDIA AI SuperRes"), (960, 540))

    def test_the_neural_upscaler_never_works_above_the_source(self):
        """A 4:3 source keeps its shape: 720x540, not a squeezed 800x540."""
        self.assertEqual(self.rule((800, 600), (1920, 1080), "NVIDIA AI SuperRes"), (720, 540))

    def test_the_frame_shape_is_never_squeezed(self):
        for source, display in (((800, 600), (1920, 1080)), ((1024, 768), (1920, 1080)),
                                ((3440, 1440), (1920, 1080)), ((1366, 768), (2560, 1440))):
            for choice in ("Auto", "Performance", "HD", "Full HD", "Native"):
                with self.subTest(source=source, display=display, choice=choice):
                    width, height = self.rule(source, display, "NVIDIA AI SuperRes", choice)
                    source_ratio = source[0] / source[1]
                    self.assertAlmostEqual(width / height, source_ratio, delta=0.02)
                    self.assertLessEqual(width, source[0])
                    self.assertLessEqual(height, source[1])

    def test_the_neural_upscaler_target_is_always_even(self):
        width, height = self.rule((1920, 1080), (1919, 1079), "NVIDIA AI SuperRes")
        self.assertEqual((width % 2, height % 2), (0, 0))

    def test_the_performance_mode_lowers_the_automatic_choice(self):
        self.assertEqual(self.rule((1920, 1080), (1920, 1080), "Bicubic", performance_mode=True),
                         (1280, 720))
        self.assertEqual(self.rule((3840, 2160), (1920, 1080), "Bicubic", performance_mode=True),
                         (1280, 720))
        # A source that already matches the cap is left untouched.
        self.assertEqual(self.rule((1280, 720), (1920, 1080), "Bicubic", performance_mode=True),
                         (1280, 720))
        self.assertEqual(self.rule((1920, 1080), (1920, 1080), "NVIDIA AI SuperRes",
                                   performance_mode=True), (960, 540))

    def test_an_explicit_choice_wins_over_the_performance_mode(self):
        self.assertEqual(self.rule((1920, 1080), (1920, 1080), "Bicubic", "Full HD",
                                   performance_mode=True), (1920, 1080))

    def test_the_explicit_choices_are_used(self):
        # Targets are fitted to the source shape: 800x600 on a 16:9 game is 800x450.
        cases = {"Performance": (800, 450), "HD": (1280, 720), "Full HD": (1920, 1080),
                 "Native": (1920, 1080)}
        for choice, expected in cases.items():
            with self.subTest(choice=choice):
                self.assertEqual(self.rule((1920, 1080), (1920, 1080), "Bicubic", choice), expected)

    def test_an_explicit_choice_is_still_capped_at_the_source(self):
        self.assertEqual(self.rule((1024, 768), (1920, 1080), "Bicubic", "Full HD"), (1024, 768))

    def test_an_unknown_choice_behaves_like_auto(self):
        self.assertEqual(self.rule((1920, 1080), (1920, 1080), "Bicubic", "Qualquer coisa"),
                         (1920, 1080))

    def test_degenerate_sizes_do_not_break_the_rule(self):
        self.assertEqual(self.rule((0, 0), (1920, 1080), "Bicubic"), (1, 1))
        self.assertEqual(self.rule((1920, 1080), (0, 0), "Bicubic"), (1, 1))

    def test_the_reason_is_written_for_the_log(self):
        self.assertIn("metade da tela", self.module.internal_resolution_reason("Auto", "NVIDIA AI SuperRes"))
        self.assertIn("EASU", self.module.internal_resolution_reason("Auto", "FSR 1.0 / CAS (Nitidez)"))
        self.assertIn("sem reamostragem", self.module.internal_resolution_reason("Auto", "Bicubic"))
        self.assertIn("menu", self.module.internal_resolution_reason("HD", "Bicubic"))


class ResolutionSettingTests(unittest.TestCase):
    def test_the_default_is_auto(self):
        self.assertEqual(DEFAULT_SETTINGS["internal_resolution"], "Auto")
        self.assertIn("Auto", INTERNAL_RESOLUTIONS)

    def test_only_known_choices_are_kept(self):
        self.assertEqual(normalize_settings({"internal_resolution": "Full HD"})["internal_resolution"],
                         "Full HD")
        self.assertEqual(normalize_settings({"internal_resolution": "8K"})["internal_resolution"], "Auto")
        self.assertEqual(normalize_settings(None)["internal_resolution"], "Auto")


class AppliedResolutionTests(unittest.TestCase):
    """The app applies the rule to the real source and display sizes."""

    @classmethod
    def setUpClass(cls):
        cls.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                         "filters", "win32gui", "win32api", "win32con", "tkinter")
        cls.module = load_module("main", cls.deps, runtime=True)

    def app_with(self, source, choice="Auto", algorithm="Bicubic", performance=False):
        app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        app.display_dim = (1920, 1080)
        app.target_source = {"internal_resolution": choice, "algo": algorithm,
                             "performance_mode": performance}
        app.internal_res = (800, 600)
        app._set_internal_resolution((0, 0, source[0], source[1]))
        return app

    def test_1080p_fullscreen_needs_no_resampling(self):
        self.assertEqual(self.app_with((1920, 1080)).internal_res, (1920, 1080))

    def test_the_ai_path_is_switched_to_half_the_display(self):
        self.assertEqual(self.app_with((1920, 1080), algorithm="NVIDIA AI SuperRes").internal_res,
                         (960, 540))

    def test_the_choice_from_the_menu_is_respected(self):
        self.assertEqual(self.app_with((1920, 1080), choice="Performance").internal_res, (800, 450))

    def test_the_change_is_written_to_the_log(self):
        messages = []
        original = self.module.diagnostics.write_now
        self.module.diagnostics.write_now = lambda label, message: messages.append(message)
        self.addCleanup(setattr, self.module.diagnostics, "write_now", original)
        self.app_with((1920, 1080))
        self.assertTrue(any("resolução interna 1920x1080" in message for message in messages))


class PrepareFrameTests(unittest.TestCase):
    """Downscaling uses area averaging, which is what keeps texture out of noise."""

    @classmethod
    def setUpClass(cls):
        cls.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                         "filters", "win32gui", "win32api", "win32con", "tkinter")
        cls.module = load_module("main", cls.deps, runtime=True)

    def setUp(self):
        self.deps["cv2"].reset_mock(return_value=True, side_effect=True)
        self.app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        self.app.display_dim = (1920, 1080)

    def test_a_large_frame_is_averaged_down(self):
        import numpy as np
        self.app.internal_res = (960, 540)
        self.app._prepare_frame(np.zeros((1080, 1920, 3), dtype=np.uint8))
        self.assertEqual(self.deps["cv2"].resize.call_args.args[1], (960, 540))
        self.assertIs(self.deps["cv2"].resize.call_args.kwargs["interpolation"],
                      self.deps["cv2"].INTER_AREA)

    def test_the_frame_shape_is_kept_when_only_one_side_is_too_big(self):
        import numpy as np
        self.app.internal_res = (1920, 1080)
        self.app._prepare_frame(np.zeros((1200, 1920, 3), dtype=np.uint8))
        self.assertEqual(self.deps["cv2"].resize.call_args.args[1], (1728, 1080))

    def test_a_frame_that_already_fits_is_left_alone(self):
        import numpy as np
        self.app.internal_res = (1920, 1080)
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        self.assertIs(self.app._prepare_frame(frame), frame)
        self.assertFalse(self.deps["cv2"].resize.called)

    def test_nothing_is_scaled_up_before_the_filters(self):
        import numpy as np
        self.app.internal_res = (1920, 1080)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        self.assertIs(self.app._prepare_frame(frame), frame)


class SelectGameResolutionTests(unittest.TestCase):
    """A new session picks the resolution from the source the user chose."""

    @classmethod
    def setUpClass(cls):
        cls.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                         "filters", "win32gui", "win32api", "win32con", "tkinter")
        cls.module = load_module("main", cls.deps, runtime=True)

    def start_with(self, source, monitor=(0, 0, 1920, 1080)):
        deps = self.deps
        deps["ui"].GameSelectorUI.return_value.get_selection.return_value = source
        deps["selector"].get_source_rect.return_value = (0, 0, source["width"], source["height"])
        deps["selector"].get_source_monitor_rect.return_value = monitor
        app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        self.assertTrue(app.select_game())
        return app

    def test_a_fullscreen_game_is_not_downscaled(self):
        app = self.start_with({"source_type": "window", "hwnd": 1, "title": "Game", "mode": "bitblt",
                               "fps": 120, "scale": "Fullscreen", "algo": "Bicubic", "sharpness": 0,
                               "engine_type": "Fast (DIS Flow)", "fg_enabled": False,
                               "width": 1920, "height": 1080})
        self.assertEqual(app.internal_res, (1920, 1080))
        self.assertEqual(app.display_dim, (1920, 1080))

    def test_a_smaller_window_is_processed_at_its_own_size(self):
        app = self.start_with({"source_type": "window", "hwnd": 1, "title": "Game", "mode": "bitblt",
                               "fps": 60, "scale": "Fullscreen", "algo": "Bicubic", "sharpness": 0,
                               "engine_type": "Fast (DIS Flow)", "fg_enabled": False,
                               "width": 1024, "height": 768})
        self.assertEqual(app.internal_res, (1024, 768))


class AutoStepTests(unittest.TestCase):
    """The ladder Auto walks down when the generator cannot hold the rate."""

    @classmethod
    def setUpClass(cls):
        cls.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                         "filters", "win32gui", "win32api", "win32con", "tkinter")
        cls.module = load_module("main", cls.deps, runtime=True)

    def test_the_first_step_is_the_sharp_target(self):
        self.assertEqual(self.module.auto_resolution_scale(0), 1.0)
        self.assertEqual(self.module.auto_resolution_scale(-1), 1.0)

    def test_the_ladder_ends(self):
        self.assertIsNone(self.module.auto_resolution_scale(len(self.module.AUTO_RESOLUTION_STEPS)))
        self.assertIsNone(self.module.auto_resolution_scale(99))

    def test_every_step_shrinks_the_frame_keeping_its_shape(self):
        source, display = (2560, 1440), (1920, 1080)
        sizes = [self.module.internal_resolution_for(source, display, "Bicubic", "Auto",
                                                     auto_step=step)
                 for step in range(len(self.module.AUTO_RESOLUTION_STEPS))]
        for size in sizes[1:]:
            self.assertLess(size[0], sizes[0][0])
            self.assertLess(size[1], sizes[0][1])
        for size in sizes:
            self.assertAlmostEqual(size[0] / size[1], source[0] / source[1], delta=0.02)

    def test_an_explicit_choice_never_walks_the_ladder(self):
        self.assertEqual(self.module.internal_resolution_for((1920, 1080), (1920, 1080),
                                                             "Bicubic", "Native", auto_step=3),
                         (1920, 1080))


class AutoAdaptationTests(unittest.TestCase):
    """The measurement that protects the frame rate on a machine that cannot keep up."""

    @classmethod
    def setUpClass(cls):
        cls.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                         "filters", "win32gui", "win32api", "win32con", "tkinter")
        cls.module = load_module("main", cls.deps, runtime=True)

    def app(self, choice="Auto", multiplier=2, target_fps=120, algorithm="Bicubic"):
        app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        app.display_dim = (1920, 1080)
        app.target_source = {"internal_resolution": choice, "algo": algorithm,
                             "performance_mode": False}
        app.fg_enabled = True
        app.frame_multiplier = multiplier
        app.target_fps = target_fps
        app.capture = MagicMock(region=(0, 0, 1920, 1080))
        app.internal_res = (1920, 1080)
        app._auto_step = 0
        app._auto_probe_start = 0.0
        app._auto_probe_generated = 0
        return app

    def test_a_generator_that_cannot_keep_up_lowers_the_resolution(self):
        app = self.app()
        app._auto_probe_generated = 30                 # 3 frames/s in a 10 s window
        self.assertTrue(app._auto_adapt(10.0))
        self.assertEqual(app.internal_res, (1344, 756))
        self.assertEqual(app._auto_step, 1)

    def test_a_healthy_generator_keeps_the_sharp_resolution(self):
        app = self.app()
        app._auto_probe_generated = 600                # 60 frames/s: exactly what 2x asks
        self.assertFalse(app._auto_adapt(10.0))
        self.assertEqual(app.internal_res, (1920, 1080))
        self.assertEqual(app._auto_step, 0)
        self.assertEqual(app._auto_probe_generated, 0)  # window restarted

    def test_the_first_window_is_only_a_measurement(self):
        app = self.app()
        app._auto_probe_generated = 0
        self.assertFalse(app._auto_adapt(1.0))          # shorter than AUTO_PROBE_SECONDS
        self.assertEqual(app.internal_res, (1920, 1080))

    def test_the_automatic_adaptation_only_touches_auto(self):
        app = self.app(choice="Native")
        app._auto_probe_generated = 0
        self.assertFalse(app._auto_adapt(10.0))
        self.assertEqual(app.internal_res, (1920, 1080))

    def test_a_single_capture_pass_does_not_need_the_generator(self):
        for multiplier, fg in ((1, True), (2, False)):
            with self.subTest(multiplier=multiplier, fg=fg):
                app = self.app(multiplier=multiplier)
                app.fg_enabled = fg
                app._auto_probe_generated = 0
                self.assertFalse(app._auto_adapt(10.0))
                self.assertEqual(app.internal_res, (1920, 1080))

    def test_the_ladder_stops_at_its_last_step(self):
        app = self.app()
        for expected_step in (1, 2, 3):
            # Applying a new resolution starts the measuring window again.
            app._auto_probe_start = 0.0
            app._auto_probe_generated = 0
            self.assertTrue(app._auto_adapt(10.0))
            self.assertEqual(app._auto_step, expected_step)
        app._auto_probe_start = 0.0
        app._auto_probe_generated = 0
        self.assertFalse(app._auto_adapt(10.0))        # nothing left to give up
        self.assertEqual(app._auto_step, len(self.module.AUTO_RESOLUTION_STEPS) - 1)
        self.assertEqual(app.internal_res, (653, 367))

    def test_the_ai_path_also_adapts(self):
        app = self.app(algorithm="NVIDIA AI SuperRes")
        self.assertEqual(app.internal_res, (1920, 1080))   # set by hand in the helper
        app._auto_probe_generated = 10
        self.assertTrue(app._auto_adapt(10.0))
        self.assertEqual(app.internal_res, (672, 378))     # half the display, one step down

    def test_the_downgrade_is_explained_in_the_log(self):
        messages = []
        original = self.module.diagnostics.write_now
        self.module.diagnostics.write_now = lambda label, message: messages.append(message)
        self.addCleanup(setattr, self.module.diagnostics, "write_now", original)
        app = self.app()
        app._auto_probe_generated = 5
        app._auto_adapt(10.0)
        self.assertTrue(any("resolução interna reduzida" in message
                            and "1344x756" in message for message in messages), messages)
        self.assertTrue(any("resolução interna 1344x756" in message for message in messages), messages)


if __name__ == "__main__":
    unittest.main()

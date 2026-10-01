"""Frame-generation multiplier, configurable hotkeys and the capture cadence."""
import sys
import unittest
from unittest.mock import MagicMock, patch

from helpers import load_module, stubs

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy ships in requirements.txt
    np = None

from settings import normalize_settings


class FakeStopEvent:
    def __init__(self, iterations):
        self.iterations = iterations
        self.calls = 0

    def is_set(self):
        self.calls += 1
        return self.calls > self.iterations


class FakeCaptureQueue:
    def __init__(self, frames):
        self.frames = list(frames)

    def get(self, timeout=None):
        if not self.frames:
            raise TimeoutError("empty")
        return self.frames.pop(0)


class FrameGenerationHelpersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                         "filters", "win32gui", "win32api", "win32con", "tkinter")
        cls.module = load_module("main", cls.deps)

    def test_multiplier_timesteps_cover_the_pair_evenly(self):
        self.assertEqual(self.module.interpolation_timesteps(2), [0.5])
        self.assertEqual(self.module.interpolation_timesteps(4), [0.25, 0.5, 0.75])
        steps = self.module.interpolation_timesteps(20)
        self.assertEqual(len(steps), 19)
        self.assertAlmostEqual(steps[0], 0.05)
        self.assertAlmostEqual(steps[-1], 0.95)
        self.assertEqual(steps, sorted(steps))

    def test_multiplier_timesteps_handle_invalid_values(self):
        # Unusable values fall back to the default doubling.
        for value in (None, "x4"):
            with self.subTest(value=value):
                self.assertEqual(self.module.interpolation_timesteps(value), [0.5])
        # Multipliers below two generate nothing.
        for value in (0, -3, 1):
            with self.subTest(value=value):
                self.assertEqual(self.module.interpolation_timesteps(value), [])

    def test_capture_cadence_divides_the_target_fps(self):
        self.assertAlmostEqual(self.module.capture_interval(60, 2), 1 / 30)
        self.assertAlmostEqual(self.module.capture_interval(120, 4), 1 / 30)
        self.assertAlmostEqual(self.module.capture_interval(60, 20), 1 / 3)
        # Without a target FPS the worker falls back to a 30 FPS base rate.
        self.assertAlmostEqual(self.module.capture_interval(0, 2), 1 / 15)
        self.assertAlmostEqual(self.module.capture_interval(60, 0), 1 / 60)

    def test_capture_keeps_the_full_rate_when_generation_is_off(self):
        self.assertEqual(self.module.effective_capture_multiplier(True, 4), 4)
        self.assertEqual(self.module.effective_capture_multiplier(True, 20), 20)
        self.assertEqual(self.module.effective_capture_multiplier(False, 20), 1)
        self.assertEqual(self.module.effective_capture_multiplier(True, None), 2)
        self.assertEqual(self.module.effective_capture_multiplier(True, "x4"), 2)
        self.assertAlmostEqual(self.module.capture_interval(60, self.module.effective_capture_multiplier(False, 20)),
                               1 / 60)

    def test_hotkey_names_map_to_windows_virtual_keys(self):
        self.assertEqual(self.module.hotkey_vk_code("F9", 0x7A), 0x78)
        self.assertEqual(self.module.hotkey_vk_code("f11", 0x7A), 0x7A)
        self.assertEqual(self.module.hotkey_vk_code("F12", 0x7A), 0x7B)
        for value in ("F13", "F0", "", None, 9, "Ctrl", "F 1"):
            with self.subTest(value=value):
                self.assertEqual(self.module.hotkey_vk_code(value, 0x7A), 0x7A)


class ProcessingSubroutineTests(unittest.TestCase):
    def setUp(self):
        if np is None:
            self.skipTest("numpy is not installed")
        self.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                          "filters", "win32gui", "win32api", "win32con", "tkinter")
        self.module = load_module("main", self.deps)
        self.patch = patch.dict(sys.modules, self.deps)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.engine = MagicMock()
        self.engine.interpolate.side_effect = lambda first, second, timestep: ("interp", timestep)
        self.deps["engine"].RIFEONNXEngine.return_value = self.engine
        self.deps["engine"].RIFEEngine.return_value = self.engine
        self.frames = [np.zeros((8, 8, 3), dtype=np.uint8), np.full((8, 8, 3), 5, dtype=np.uint8)]
        self.process_queue = MagicMock()

    def run_worker(self, multiplier, fg_enabled=True):
        config = {"engine_type": "AI (RIFE ONNX)", "fg_enabled": fg_enabled,
                  "frame_multiplier": multiplier, "internal_res": (800, 600)}
        self.module.processing_subroutine(FakeCaptureQueue(self.frames), self.process_queue, config,
                                          FakeStopEvent(len(self.frames)))
        return [call.args[0] for call in self.process_queue.put.call_args_list]

    def test_multiplier_defines_how_many_frames_each_pair_becomes(self):
        queued = self.run_worker(2)
        self.assertEqual(len(queued), 3)
        self.assertIs(queued[0], self.frames[0])  # the first capture has nothing to interpolate
        self.assertEqual(queued[1], ("interp", 0.5))
        self.assertIs(queued[2], self.frames[1])
        self.engine.interpolate.assert_called_once()

    def test_higher_multipliers_spread_intermediate_frames_over_the_pair(self):
        queued = self.run_worker(6)
        self.assertEqual(len(queued), 7)  # the first capture plus a full batch of six
        self.assertIs(queued[0], self.frames[0])
        batch = queued[1:]
        self.assertEqual(len(batch), 6)  # 5 generated frames plus the captured one
        self.assertIs(batch[-1], self.frames[1])
        self.assertEqual([item[1] for item in batch[:-1]], self.module.interpolation_timesteps(6))

    def test_disabled_generation_keeps_the_real_frames_only(self):
        queued = self.run_worker(20, fg_enabled=False)
        self.assertEqual(len(queued), 2)
        self.assertIs(queued[0], self.frames[0])
        self.assertIs(queued[1], self.frames[1])
        self.engine.interpolate.assert_not_called()


class SelectionSettingsTests(unittest.TestCase):
    """`select_game` translates saved preferences into runtime behavior."""

    def setUp(self):
        self.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                          "filters", "win32gui", "win32api", "win32con", "tkinter")
        self.module = load_module("main", self.deps)
        self.app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        self.source = {"source_type": "window", "hwnd": 7, "title": "Game", "mode": "bitblt",
                       "fps": 120, "scale": "1.0", "algo": "Lanczos", "sharpness": 20,
                       "engine_type": "Fast (DIS Flow)"}
        self.deps["selector"].get_source_rect.return_value = (0, 0, 640, 480)
        self.deps["selector"].get_source_monitor_rect.return_value = (0, 0, 1920, 1080)
        self.select = lambda: self.app.select_game()

    def with_source(self, **overrides):
        source = dict(self.source, **overrides)
        self.deps["ui"].GameSelectorUI.return_value.get_selection.return_value = source
        return source

    def test_selected_multiplier_is_applied_and_capture_uses_it(self):
        self.with_source(frame_multiplier=6)
        self.assertTrue(self.select())
        self.assertEqual(self.app.frame_multiplier, 6)
        self.assertAlmostEqual(self.module.capture_interval(self.app.target_fps, self.app.frame_multiplier), 0.05)

    def test_invalid_multiplier_falls_back_to_doubling(self):
        for value in (0, 1, 21, 7, "x4", None):
            with self.subTest(value=value):
                self.with_source(frame_multiplier=value)
                self.assertTrue(self.select())
                self.assertEqual(self.app.frame_multiplier, 2)

    def test_hotkeys_are_read_and_invalid_names_keep_the_fallback(self):
        self.with_source(hotkey_stop="F5", hotkey_fps="F6", hotkey_fsr="F7")
        self.assertTrue(self.select())
        self.assertEqual(self.app.hotkeys, {"stop": 0x74, "fps": 0x75, "fsr": 0x76})
        self.assertEqual(self.app.hotkey_names["stop"], "F5")
        self.with_source(hotkey_stop="Ctrl+Q", hotkey_fps=None)
        self.assertTrue(self.select())
        self.assertEqual(self.app.hotkeys, {"stop": 0x7A, "fps": 0x79, "fsr": 0x78})

    def test_show_fps_preference_controls_the_initial_panel(self):
        self.with_source(show_fps=False)
        self.assertTrue(self.select())
        self.assertFalse(self.app.show_fps)
        self.with_source(show_fps=True)
        self.assertTrue(self.select())
        self.assertTrue(self.app.show_fps)

    def test_queues_grow_with_the_multiplier_and_stay_bounded(self):
        self.assertEqual(self.module.queue_sizes(2), (2, 3, 3))
        self.assertEqual(self.module.queue_sizes(20), (2, 8, 20))
        self.assertEqual(self.module.queue_sizes(20, low_latency=False), (2, 8, 40))
        self.assertEqual(self.module.queue_sizes(50, low_latency=False), (2, 8, 45))
        self.with_source(frame_multiplier=20)
        self.assertTrue(self.select())
        # multiprocessing.Queue exposes the requested size only through its private field.
        self.assertEqual(self.app.process_queue._maxsize, 8)
        self.assertEqual(self.app.display_queue.maxsize, 20)

    def test_saved_preferences_round_trip_into_the_selection(self):
        prefs = normalize_settings({"frame_multiplier": 8, "hotkey_stop": "F4",
                                    "hotkey_fps": "F6", "hotkey_fsr": "F8", "show_fps": False})
        self.with_source(**{key: prefs[key] for key in ("frame_multiplier", "hotkey_stop",
                                                        "hotkey_fps", "hotkey_fsr", "show_fps")})
        self.assertTrue(self.select())
        self.assertEqual(self.app.frame_multiplier, 8)
        self.assertEqual(self.app.hotkeys["stop"], 0x73)
        self.assertFalse(self.app.show_fps)

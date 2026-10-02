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


class GenerationBudgetTests(unittest.TestCase):
    """A generator slower than the capture rate must not queue stale frames."""

    @classmethod
    def setUpClass(cls):
        cls.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                         "filters", "win32gui", "win32api", "win32con", "tkinter")
        cls.module = load_module("main", cls.deps)

    def test_everything_fits_when_the_engine_is_fast(self):
        steps = self.module.interpolation_timesteps(6)
        self.assertEqual(self.module.affordable_timesteps(steps, 60.0, 5.0), steps)
        self.assertEqual(self.module.affordable_timesteps(steps, 60.0, 0.0), steps)

    def test_nothing_is_generated_when_even_one_frame_does_not_fit(self):
        steps = self.module.interpolation_timesteps(6)
        self.assertEqual(self.module.affordable_timesteps(steps, 16.0, 40.0), [])

    def test_partial_budget_spreads_the_generated_frames(self):
        steps = self.module.interpolation_timesteps(8)
        picked = self.module.affordable_timesteps(steps, 60.0, 20.0)  # room for three
        self.assertEqual(len(picked), 3)
        self.assertEqual(picked, sorted(set(picked)))
        self.assertTrue(set(picked).issubset(set(steps)))
        self.assertGreater(picked[-1], picked[0])

    def test_unknown_cost_keeps_the_requested_frames(self):
        steps = self.module.interpolation_timesteps(4)
        self.assertEqual(self.module.affordable_timesteps(steps, 0.0, 0.0), steps)
        self.assertEqual(self.module.affordable_timesteps([], 60.0, 5.0), [])


class GenerationBudgetFallbackTests(unittest.TestCase):
    """The worker switches away from an engine that cannot generate in real time."""

    def setUp(self):
        if np is None:
            self.skipTest("numpy is not installed")
        self.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                          "filters", "win32gui", "win32api", "win32con", "tkinter")
        self.module = load_module("main", self.deps)
        self.patch = patch.dict(sys.modules, self.deps)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.messages = []
        self.module.diagnostics.ENABLED = False
        self.module.diagnostics.write = lambda message: self.messages.append(str(message))
        self.addCleanup(setattr, self.module.diagnostics, "write", self.module.diagnostics.write)
        self.engine = MagicMock()
        self.engine.session = None
        self.engine.interpolate.side_effect = lambda a, b, step: ("interp", step)
        self.deps["engine"].RIFEONNXEngine.return_value = self.engine
        self.fast_engine = MagicMock()
        self.fast_engine.interpolate.side_effect = lambda a, b, step: ("fast", step)
        self.deps["engine"].RIFEEngine.return_value = self.fast_engine
        self.frames = [np.full((8, 8, 3), value, dtype=np.uint8) for value in (0, 5, 10, 15)]
        self.process_queue = MagicMock()

    def run_worker(self, engine_type="AI (RIFE ONNX)", frames=None, fg_enabled=True):
        frames = frames if frames is not None else self.frames
        config = {"engine_type": engine_type, "fg_enabled": fg_enabled,
                  "frame_multiplier": 2, "internal_res": (800, 600)}
        self.module.processing_subroutine(FakeCaptureQueue(frames), self.process_queue, config,
                                          FakeStopEvent(len(frames)))
        return [call.args[0] for call in self.process_queue.put_nowait.call_args_list]

    def test_slow_ai_engine_is_replaced_by_the_fast_one_in_the_same_session(self):
        def slow(first, second, timestep):
            import time as time_module
            time_module.sleep(0.3)
            return ("interp", timestep)

        self.engine.interpolate.side_effect = slow
        queued = self.run_worker()
        self.assertTrue(self.deps["engine"].RIFEEngine.called)
        self.assertTrue(any("Fast (DIS Flow)" in message for message in self.messages))
        self.assertTrue(any(isinstance(item, tuple) and item[0] == "fast" for item in queued))

    def test_fast_engine_is_left_alone(self):
        self.run_worker(engine_type="Fast (DIS Flow)")
        self.deps["engine"].RIFEONNXEngine.assert_not_called()

    def test_real_frames_always_reach_the_display(self):
        queued = self.run_worker()
        self.assertIs(queued[-1], self.frames[-1])

    def test_a_session_that_never_started_switches_to_the_fast_engine_at_once(self):
        self.run_worker()                            # setUp leaves the session as None
        self.engine.interpolate.assert_not_called()
        self.deps["engine"].RIFEEngine.assert_called()
        self.assertTrue(any("não iniciou" in message for message in self.messages))

    def test_slow_engine_gets_no_more_work_after_the_switch(self):
        self.engine.session = MagicMock()            # the session exists, it is just slow
        calls = []

        def slow(first, second, timestep):
            calls.append(timestep)
            import time as time_module
            time_module.sleep(0.3)
            return ("interp", timestep)

        self.engine.interpolate.side_effect = slow
        self.run_worker()
        # The first (slow) frame is what triggers the switch, nothing else is asked
        # of the AI engine afterwards.
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.fast_engine.interpolate.call_count, 3)  # the rest of the session


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
        self.frames = [np.full((8, 8, 3), value, dtype=np.uint8) for value in (0, 5)]
        self.process_queue = MagicMock()

    def run_worker(self, multiplier, fg_enabled=True):
        config = {"engine_type": "AI (RIFE ONNX)", "fg_enabled": fg_enabled,
                  "frame_multiplier": multiplier, "internal_res": (800, 600)}
        self.module.processing_subroutine(FakeCaptureQueue(self.frames), self.process_queue, config,
                                          FakeStopEvent(len(self.frames)))
        # Frames reach the display through put_nowait so a full queue drops the oldest.
        return [call.args[0] for call in self.process_queue.put_nowait.call_args_list]

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
        self.module = load_module("main", self.deps, runtime=True)
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

    def test_unlimited_is_applied_to_the_session(self):
        self.with_source(unlimited_fps=True)
        self.assertTrue(self.select())
        self.assertTrue(self.app.unlimited_fps)
        self.with_source(unlimited_fps=False)
        self.assertTrue(self.select())
        self.assertFalse(self.app.unlimited_fps)

    def test_saved_preferences_round_trip_into_the_selection(self):
        prefs = normalize_settings({"frame_multiplier": 8, "hotkey_stop": "F4",
                                    "hotkey_fps": "F6", "hotkey_fsr": "F8", "show_fps": False,
                                    "unlimited_fps": True})
        self.with_source(**{key: prefs[key] for key in ("frame_multiplier", "hotkey_stop",
                                                        "hotkey_fps", "hotkey_fsr", "show_fps",
                                                        "unlimited_fps")})
        self.assertTrue(self.select())
        self.assertEqual(self.app.frame_multiplier, 8)
        self.assertEqual(self.app.hotkeys["stop"], 0x73)
        self.assertFalse(self.app.show_fps)
        self.assertTrue(self.app.unlimited_fps)

class UnlimitedRateTests(unittest.TestCase):
    """Unlimited removes the output schedule instead of picking another rate."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_module("main", stubs("cv2", "numpy", "pygame", "capture", "engine",
                                               "ui", "selector", "filters", "win32gui",
                                               "win32api", "win32con", "tkinter"), runtime=True)

    def test_the_capture_has_no_schedule(self):
        self.assertEqual(self.module.capture_interval(120, 2, unlimited=True), 0.0)
        self.assertEqual(self.module.capture_interval(60, 20, unlimited=True), 0.0)

    def test_an_unlimited_capture_takes_every_real_frame(self):
        self.assertEqual(self.module.effective_capture_multiplier(True, 2, unlimited=True), 1)
        self.assertEqual(self.module.effective_capture_multiplier(True, 20, unlimited=True), 1)
        self.assertEqual(self.module.effective_capture_multiplier(False, 2, unlimited=True), 1)

    def test_the_display_has_no_pacing(self):
        self.assertEqual(self.module.display_interval(120, unlimited=True), 0.0)
        self.assertEqual(self.module.display_interval(30), 1 / 30)
        self.assertEqual(self.module.display_interval(0), 0.0)

    def test_unlimited_still_respects_the_multiplier(self):
        """x2 means two output frames for every captured frame, at any rate."""
        multiplier = self.module.effective_capture_multiplier(True, 2, unlimited=True)
        self.assertEqual(len(self.module.interpolation_timesteps(2)) + 1, 2 * multiplier)


class RepeatPresentationTests(unittest.TestCase):
    """The same picture is never presented twice while there is no fixed rate."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_module("main", stubs("cv2", "numpy", "pygame", "capture", "engine",
                                               "ui", "selector", "filters", "win32gui",
                                               "win32api", "win32con", "tkinter"), runtime=True)

    def app(self, unlimited):
        app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        app.unlimited_fps = unlimited
        app.last_presented_frame = None
        return app

    def test_a_new_frame_is_always_presented(self):
        app = self.app(True)
        image = object()
        self.assertFalse(app._repeat_of_presented(image))
        app.last_presented_frame = image
        self.assertTrue(app._repeat_of_presented(image))

    def test_a_fixed_rate_may_repeat_the_held_image(self):
        app = self.app(False)
        image = object()
        app.last_presented_frame = image
        self.assertFalse(app._repeat_of_presented(image))

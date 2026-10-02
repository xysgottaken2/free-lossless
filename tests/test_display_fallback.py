"""The overlay never stalls and its mode chip never flips frame by frame.

Two problems used to show up on screen at the same time: the displayed image
stopped whenever the frame generator could not keep up, and the status chip
alternated between FG and LIVE on every frame, which reads as flicker.
"""
import time
import unittest
from queue import Queue

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy ships in requirements.txt
    np = None

from helpers import load_module, stubs


class DisplayFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                         "filters", "win32gui", "win32api", "win32con", "tkinter")
        cls.module = load_module("main", cls.deps, runtime=True)

    def setUp(self):
        self.app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        self.app.display_queue = Queue(maxsize=8)
        self.app.live_display_queue = Queue(maxsize=1)
        self.app.last_live_display = None
        self.app.live_publish_time = 0.0
        self.app.want_live_frames = False
        self.app.starving_since = None
        self.app.healthy_since = None
        self.app.live_fallback = False
        self.app.last_frame_generated = False
        self.app.dropped_generated = 0
        self.app.frame_count = 1          # the first frame was already shown
        self.module.diagnostics.write = lambda message: None
        self.module.print = lambda *args, **kwargs: None

    def live(self, value):
        """Publish a captured frame the way the capture worker does."""
        self.app.last_live_display = value
        self.app.live_display_queue.put(value)

    def generated(self, value):
        self.app.display_queue.put(value)

    def pick(self, now, min_buffer=1, stall=0.5, delay=0.5):
        return self.app._pick_frame(now, min_buffer, stall, delay)


class ImageKeepsMovingTests(DisplayFallbackTests):
    def test_the_image_never_stalls_when_the_generator_is_behind(self):
        self.live("live")
        self.assertIs(self.pick(0.0), "live")        # shown right away
        self.assertFalse(self.app.live_fallback)     # while the chip still says FG
        self.assertIs(self.pick(0.01), "live")

    def test_a_generated_frame_is_preferred_over_the_capture(self):
        self.live("live")
        self.generated("generated")
        self.assertIs(self.pick(0.0), "generated")
        self.assertTrue(self.app.last_frame_generated)

    def test_the_previous_capture_is_reused_instead_of_showing_nothing(self):
        self.live("live")
        self.pick(0.0)
        self.assertIs(self.pick(0.01), "live")       # nothing new was captured

    def test_old_generated_frames_are_dropped_instead_of_being_displayed_late(self):
        self.live("live")
        for index in range(6):
            self.generated(f"generated-{index}")
        self.assertEqual(self.pick(0.0, min_buffer=1), "generated-5")  # the newest one
        self.assertTrue(self.app.display_queue.empty())
        self.assertEqual(self.app.dropped_generated, 5)

    def test_the_buffered_mode_keeps_a_small_backlog_only(self):
        for index in range(6):
            self.generated(f"generated-{index}")
        self.pick(0.0, min_buffer=3)
        self.assertEqual(self.app.display_queue.qsize(), 2)          # never grows further


class ModeChipTests(DisplayFallbackTests):
    def test_the_chip_only_says_live_after_a_sustained_stall(self):
        self.live("live")
        self.pick(0.0, stall=0.5)
        self.pick(0.2, stall=0.5)
        self.assertFalse(self.app.live_fallback)
        self.pick(0.6, stall=0.5)
        self.assertTrue(self.app.live_fallback)

    def test_one_generated_frame_does_not_flip_the_chip_back(self):
        self.live("live")
        self.pick(0.0, stall=0.5)
        self.pick(0.6, stall=0.5)
        self.assertTrue(self.app.live_fallback)
        self.generated("generated")
        self.assertIs(self.pick(0.7, stall=0.5, delay=0.5), "generated")
        self.assertTrue(self.app.live_fallback)      # still LIVE, no flicker

    def test_the_chip_returns_to_fg_after_the_generator_keeps_up(self):
        self.live("live")
        self.pick(0.0, stall=0.5)
        self.pick(0.6, stall=0.5)
        for step, moment in enumerate((0.7, 0.9, 1.1)):
            self.generated(f"generated-{step}")
            self.pick(moment, stall=0.5, delay=0.5)
            self.assertTrue(self.app.live_fallback)  # still recovering
        self.generated("generated-late")
        self.pick(1.2, stall=0.5, delay=0.5)         # half a second of good frames
        self.assertFalse(self.app.live_fallback)

    def test_the_chip_never_changes_twice_in_the_same_moment(self):
        """Half of the frames generated must still stay on a single chip."""
        self.live("live")
        self.pick(0.0, stall=0.03)
        self.pick(0.05, stall=0.03)                  # entered LIVE
        changes = 0
        previous = self.app.live_fallback
        for step in range(20):
            now = 0.1 + step * 0.01
            self.generated(f"generated-{step}")
            self.pick(now, stall=0.03, delay=0.5)
            if self.app.live_fallback != previous:
                changes += 1
                previous = self.app.live_fallback
        self.assertEqual(changes, 0)


if __name__ == "__main__":
    unittest.main()


class LiveRenderBudgetTests(DisplayFallbackTests):
    """Live frames keep coming even when rendering them costs too much.

    The capture thread renders them itself, so an expensive render there would hold
    every capture back and drop the frame rate the user sees.
    """

    def setUp(self):
        super().setUp()
        self.app.display_dim = (1920, 1080)
        self.app.filters_enabled = True
        self.app.fsr_mode = False
        self.app.ai_mode = False
        self.app.ai_upscaler = None
        self.app.sharpness = 1.0
        self.app.upscale_algo = 1
        self.app.filter_chain = None
        self.app.live_render_ms = 0.0
        self.app.live_render_budget_ms = 4.0
        self.app.live_degraded = False
        self.rendered = []
        self.app._render_for_display = lambda frame: (self.rendered.append("full"), frame)[1]

    def publish(self, frame="frame"):
        self.app._publish_live_frame(frame)

    def test_a_cheap_render_is_used_while_it_fits_the_budget(self):
        self.publish()
        self.assertEqual(self.rendered, ["full"])

    def test_rendering_is_downgraded_once_it_is_too_expensive(self):
        self.publish()
        for _ in range(40):                     # the smoothed cost climbs past the budget
            self.app._render_for_display = lambda frame: (time.sleep(0.012), frame)[1]
            self.publish()
        self.assertTrue(self.app.live_degraded)
        self.assertGreater(self.app.live_render_ms, self.app.live_render_budget_ms)
        # It stops asking for the expensive render and only resizes.
        self.app._render_for_display = lambda frame: (self.rendered.append("full"), frame)[1]
        before = len(self.rendered)
        self.publish()
        self.assertEqual(len(self.rendered), before)

    def test_the_cheap_path_only_resizes(self):
        frame = np.zeros((600, 800, 3), dtype=np.uint8)
        self.app._cheap_render(frame)
        # One resize straight to the display size and nothing else.
        self.assertEqual(self.deps["cv2"].resize.call_args.args[1], (1920, 1080))

    def test_a_frame_already_at_display_size_is_passed_through(self):
        frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        self.assertIs(self.app._cheap_render(frame), frame)


class QueueReportTests(unittest.TestCase):
    """The periodic diagnostics line must not crash with real queues.

    ``multiprocessing.Queue`` has no ``maxsize`` attribute — it keeps the bound in
    ``_maxsize`` — and reading it crashed the overlay five seconds into a session.
    """

    @classmethod
    def setUpClass(cls):
        import multiprocessing
        cls.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                         "filters", "win32gui", "win32api", "win32con", "tkinter")
        cls.module = load_module("main", cls.deps, runtime=True)
        cls.multiprocessing = multiprocessing

    def queue_capacity(self, size):
        process_queue = self.multiprocessing.Queue(maxsize=size)
        self.addCleanup(process_queue.close)
        return self.module.queue_capacity(process_queue)

    def test_a_process_queue_reports_its_capacity(self):
        self.assertEqual(self.queue_capacity(2), 2)
        self.assertEqual(self.queue_capacity(7), 7)

    def test_a_thread_queue_reports_its_capacity(self):
        from queue import Queue
        self.assertEqual(self.module.queue_capacity(Queue(maxsize=3)), 3)

    def test_an_unknown_object_reports_zero_instead_of_raising(self):
        self.assertEqual(self.module.queue_capacity(object()), 0)
        self.assertEqual(self.module.queue_capacity(None), 0)

    def test_the_report_line_works_with_the_queues_the_app_really_uses(self):
        from queue import Queue
        app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        app.capture_queue = self.multiprocessing.Queue(maxsize=2)
        app.process_queue = self.multiprocessing.Queue(maxsize=3)
        app.display_queue = Queue(maxsize=5)
        self.addCleanup(app.capture_queue.close)
        self.addCleanup(app.process_queue.close)
        line = app._queue_report()
        self.assertIn("captura 0/2", line)
        self.assertIn("pós 0/3", line)
        self.assertIn("exibição 0/5", line)

    def test_the_report_line_counts_what_is_waiting(self):
        from queue import Queue
        app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        app.capture_queue = self.multiprocessing.Queue(maxsize=2)
        app.process_queue = self.multiprocessing.Queue(maxsize=3)
        app.display_queue = Queue(maxsize=5)
        self.addCleanup(app.capture_queue.close)
        self.addCleanup(app.process_queue.close)
        app.display_queue.put("frame")
        app.display_queue.put("frame")
        self.assertIn("exibição 2/5", app._queue_report())

    def test_the_loop_uses_the_report_helper(self):
        """No direct ``.maxsize`` on a process queue may sneak back into the loop."""
        import inspect
        source = inspect.getsource(self.module.FrameGenerationApp.run)
        self.assertNotIn(".maxsize", source)
        self.assertIn("_log_periodic_status", source)

    def test_no_direct_queue_attribute_access_survives_anywhere(self):
        """``.maxsize`` may only be read through ``queue_capacity``.

        Checked on the syntax tree, not on the text: a docstring that mentions the
        attribute is fine, an access is not.
        """
        import ast
        import inspect
        import textwrap

        def attribute_names(source):
            tree = ast.parse(textwrap.dedent(source))
            return {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}

        for name in ("run", "_log_periodic_status", "_queue_report"):
            with self.subTest(method=name):
                attributes = attribute_names(inspect.getsource(getattr(self.module.FrameGenerationApp, name)))
                self.assertNotIn("maxsize", attributes)


class PeriodicReportTests(unittest.TestCase):
    """The periodic status report is cosmetic: it must never stop the overlay."""

    @classmethod
    def setUpClass(cls):
        cls.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                         "filters", "win32gui", "win32api", "win32con", "tkinter")
        cls.module = load_module("main", cls.deps, runtime=True)

    def setUp(self):
        self.messages = []
        self.original = self.module.diagnostics.write_now
        self.module.diagnostics.write_now = lambda label, message: self.messages.append(
            f"{label}: {message}")
        self.addCleanup(setattr, self.module.diagnostics, "write_now", self.original)
        self.app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        self.app.current_fps = 118.6
        self.app.generated_fps = 118.6
        self.app.live_fallback = False
        self.app.frame_multiplier = 2
        self.app.dropped_generated = 0
        self.app.display_queue = Queue(maxsize=5)
        self.app.display_queue.put("frame")
        self.app._queue_report = lambda size=None: "filas teste"

    def test_nothing_is_written_before_the_interval(self):
        self.assertEqual(self.app._log_periodic_status(1.0, 0.0), 0.0)
        self.assertEqual(self.messages, [])

    def test_the_timestamp_advances_when_it_reports(self):
        self.assertEqual(self.app._log_periodic_status(6.0, 0.0), 6.0)
        self.assertTrue(any("FPS exibidos" in message for message in self.messages))

    def test_a_broken_report_does_not_raise_and_keeps_the_schedule(self):
        self.app._queue_report = lambda size=None: 1 / 0
        self.assertEqual(self.app._log_periodic_status(6.0, 0.0), 6.0)
        self.assertTrue(any("relatório periódico falhou" in message for message in self.messages))



    def test_the_log_says_where_the_frames_came_from(self):
        self.app.live_fallback = True
        self.app._log_periodic_status(6.0, 0.0)
        self.assertTrue(any("live" in message for message in self.messages))

    def test_the_report_reads_the_real_display_queue(self):
        """The queue size is measured inside the report, not passed by the caller."""
        self.app.__dict__.pop("_queue_report", None)      # use the real method
        self.app.capture_queue = Queue(maxsize=2)
        self.app.process_queue = Queue(maxsize=3)
        self.app._log_periodic_status(6.0, 0.0)
        self.assertTrue(any("exibição 1/5" in message for message in self.messages))

    def test_a_broken_queue_is_reported_and_the_schedule_continues(self):
        self.app.display_queue = object()          # no qsize() at all
        self.assertEqual(self.app._log_periodic_status(6.0, 0.0), 6.0)
        self.assertTrue(any("relatório periódico falhou" in message for message in self.messages))

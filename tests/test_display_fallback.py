"""The overlay never stalls and its mode chip never flips frame by frame.

Two problems used to show up on screen at the same time: the displayed image
stopped whenever the frame generator could not keep up, and the status chip
alternated between FG and LIVE on every frame, which reads as flicker.
"""
import unittest
from queue import Queue

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

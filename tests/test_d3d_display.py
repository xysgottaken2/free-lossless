"""The overlay's presentation backends.

The D3D11 mode exists so ReShade can hook the overlay, so it must present real frames
and must never take the overlay down with it: when the machine cannot provide a
swapchain, the caller falls back to GDI.
"""
import os
import unittest
from unittest.mock import patch

try:
    import pygame
except ImportError:  # pragma: no cover - pygame ships in requirements.txt
    pygame = None

import d3d_display


class DisplayTestBase(unittest.TestCase):
    """Keeps the video environment exactly as it was found.

    The overlay tests that need a real window run later in the same process, so a
    driver forced here (or a pygame.quit()) would break them on a real desktop.
    """

    @classmethod
    def setUpClass(cls):
        if pygame is None:
            raise unittest.SkipTest("pygame não está instalado")
        cls.driver_before = os.environ.get("SDL_VIDEODRIVER")
        cls.pygame_was_ready = pygame.get_init()
        if os.name != "nt":
            # A headless Linux machine has no window to open; Windows has one.
            os.environ["SDL_VIDEODRIVER"] = "offscreen"
        pygame.init()

    @classmethod
    def tearDownClass(cls):
        if cls.driver_before is None:
            os.environ.pop("SDL_VIDEODRIVER", None)
        else:
            os.environ["SDL_VIDEODRIVER"] = cls.driver_before
        if not cls.pygame_was_ready:
            pygame.quit()


@unittest.skipIf(pygame is None or d3d_display._video is None, "pygame sem os módulos SDL2")
class RendererDisplayTests(DisplayTestBase):

    def make(self, size=(320, 240)):
        display = d3d_display.RendererDisplay("FreeLossless teste", size)
        self.addCleanup(display.close)
        return display

    def test_it_picks_a_working_backend(self):
        display = self.make()
        self.assertIn(display.driver, d3d_display.DRIVERS)

    def test_the_canvas_is_the_requested_size(self):
        display = self.make((400, 300))
        self.assertEqual(display.canvas.get_size(), (400, 300))
        self.assertEqual(display.size, (400, 300))

    def test_present_uploads_what_was_drawn(self):
        display = self.make()
        display.canvas.fill((10, 200, 30))
        display.present()
        presented = display.renderer.to_surface()
        self.assertEqual(presented.get_at((5, 5))[:3], (10, 200, 30))

    def test_present_survives_many_frames(self):
        display = self.make()
        for value in range(0, 60, 6):
            display.canvas.fill((value, 0, 0))
            display.present()
        display.present()

    def test_resize_returns_a_canvas_of_the_new_size(self):
        display = self.make((320, 240))
        canvas = display.resize((640, 480))
        self.assertEqual(canvas.get_size(), (640, 480))
        self.assertIs(canvas, display.canvas)
        self.assertEqual(tuple(display.window.size), (640, 480))
        canvas.fill((200, 100, 50))
        display.present()
        self.assertEqual(display.renderer.to_surface().get_at((5, 5))[:3], (200, 100, 50))

    def test_resizing_to_the_same_size_keeps_the_canvas(self):
        display = self.make((320, 240))
        self.assertIs(display.resize((320, 240)), display.canvas)

    def test_the_window_handle_is_absent_outside_windows(self):
        """The HWND lookup must fail quietly where there is no Win32."""
        display = self.make()
        if os.name != "nt":
            self.assertIsNone(display.hwnd())

    def test_an_explicit_driver_order_is_respected(self):
        display = d3d_display.RendererDisplay("FreeLossless teste", (64, 64),
                                              drivers=("software",))
        self.addCleanup(display.close)
        self.assertEqual(display.driver, "software")


@unittest.skipIf(pygame is None or d3d_display._video is None, "pygame sem os módulos SDL2")
class CreateDisplayTests(DisplayTestBase):

    def test_gdi_returns_a_display_surface_and_no_presenter(self):
        surface, presenter, description = d3d_display.create_display("GDI", "t", (160, 120))
        self.assertIsNone(presenter)
        self.assertEqual(surface.get_size(), (160, 120))
        self.assertIn("GDI", description)

    def test_d3d11_returns_a_canvas_and_a_presenter(self):
        canvas, presenter, description = d3d_display.create_display("D3D11", "t", (160, 120))
        self.addCleanup(presenter.close)
        self.assertIs(presenter.canvas, canvas)
        self.assertIn("SDL", description)
        presenter.present()

    def test_an_unknown_mode_falls_back_to_gdi(self):
        surface, presenter, description = d3d_display.create_display("Qualquer", "t", (160, 120))
        self.assertIsNone(presenter)
        self.assertIn("GDI", description)

    def test_the_failure_to_open_a_renderer_is_raised_for_the_caller(self):
        """The caller decides the fallback; a broken backend must not be silent."""
        with patch.object(d3d_display, "_video", None):
            with self.assertRaises(RuntimeError):
                d3d_display.create_display("D3D11", "t", (160, 120))

    def test_describe_mentions_both_modes(self):
        self.assertIn("D3D11", d3d_display.describe("D3D11"))
        self.assertIn("GDI", d3d_display.describe("GDI"))


class WindowHandleTests(unittest.TestCase):
    def test_a_window_without_an_id_has_no_handle(self):
        self.assertIsNone(d3d_display._window_handle(None))
        self.assertIsNone(d3d_display._window_handle(0))

    def test_outside_windows_there_is_no_handle(self):
        if os.name == "nt":
            self.skipTest("no Windows o handle é resolvido de verdade")
        self.assertIsNone(d3d_display._window_handle(1))


if __name__ == "__main__":
    unittest.main()

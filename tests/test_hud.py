import types
import unittest
from unittest.mock import MagicMock

import i18n
from helpers import load_module, stubs


class FakeSurface:
    def __init__(self, size=(0, 0), flags=0):
        self.size = tuple(size)
        self.blits = []
        self.fill_color = None

    def get_width(self):
        return self.size[0]

    def get_height(self):
        return self.size[1]

    def fill(self, color):
        self.fill_color = color

    def blit(self, source, position, **options):
        self.blits.append((source.size, tuple(position)))


class FakeFont:
    """Renders proportional-looking text without pygame."""

    char_width = 9

    def __init__(self):
        self.rendered = []

    def render(self, text, antialias, color):
        self.rendered.append(text)
        surface = FakeSurface((len(text) * self.char_width, 20))
        surface.color = color
        return surface


class FakeDraw:
    def __init__(self):
        self.rects = []

    def rect(self, surface, color, rect, width=0, **options):
        self.rects.append({"color": color, "rect": tuple(rect), "width": width,
                           "border_radius": options.get("border_radius")})


class OverlayHudTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "en")
        self.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                          "filters", "win32gui", "win32api", "win32con", "tkinter")
        self.module = load_module("main", self.deps)
        self.draw = FakeDraw()
        self.module.pygame = types.SimpleNamespace(Surface=FakeSurface, draw=self.draw, SRCALPHA=0x10000)

    def make_app(self, **state):
        app = self.module.FrameGenerationApp.__new__(self.module.FrameGenerationApp)
        app.current_fps = state.get("current_fps", 87.4)
        app.fsr_mode = state.get("fsr_mode", False)
        app.ai_mode = state.get("ai_mode", True)
        app.ultra_smooth = state.get("ultra_smooth", False)
        app.live_fallback = state.get("live_fallback", False)
        app.generated_fps = state.get("generated_fps", 60.4)
        app.hotkey_names = dict(self.module.DEFAULT_HOTKEY_NAMES)
        return app

    def draw_hud(self, app, size=(640, 360)):
        screen = FakeSurface(size)
        app._draw_hud(screen, FakeFont(), FakeFont())
        return screen

    def test_chips_reflect_the_selected_modes(self):
        self.assertEqual(self.module.hud_chips(True, True, True),
                         [("FSR", "ON", "on"), ("AI", "ON", "on"), ("MODE", "SMOOTH", "mode"),
                          ("", "FG", "on")])
        self.assertEqual(self.module.hud_chips(False, False, False),
                         [("FSR", "OFF", "off"), ("AI", "OFF", "off"), ("MODE", "STD", "off"),
                          ("", "FG", "on")])

    def test_chips_say_when_frames_come_straight_from_the_capture(self):
        chips = self.module.hud_chips(False, False, False, live=True)
        self.assertEqual(chips[-1], ("", "LIVE", "mode"))

    def test_chips_report_how_fast_frames_are_generated(self):
        self.assertEqual(self.module.hud_chips(False, False, False, generated_fps=118.6)[-1],
                         ("", "FG 119/s", "on"))
        self.assertEqual(self.module.hud_chips(False, False, False, live=True, generated_fps=0.4)[-1],
                         ("", "LIVE", "mode"))  # nothing generated: no rate to show

    def test_chips_follow_the_selected_language(self):
        i18n.set_language("pt-BR")
        self.assertEqual(self.module.hud_chips(True, False, True)[2], ("MODO", "SMOOTH", "mode"))
        i18n.set_language("zh-CN")
        self.assertEqual(self.module.hud_chips(False, False, False)[2], ("模式", "标准", "off"))

    def test_panel_and_every_label_stay_inside_the_overlay(self):
        screen = self.draw_hud(self.make_app())
        self.assertEqual(len(screen.blits), 12)  # panel, fps value+label, 4 chips + 4 texts, hint
        for size, (x, y) in screen.blits:
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + size[0], 640)
            self.assertLessEqual(y + size[1], 360)

    def test_panel_is_drawn_first_with_rounded_borders(self):
        screen = self.draw_hud(self.make_app())
        panel_size, panel_position = screen.blits[0]
        self.assertEqual(panel_position, (16, 16))
        self.assertEqual(panel_size, self.draw.rects[0]["rect"][2:])
        self.assertEqual(self.draw.rects[0]["border_radius"], 12)
        self.assertEqual(len(self.draw.rects), 5)  # panel outline plus one per chip
        self.assertTrue(all(entry["border_radius"] for entry in self.draw.rects))
        self.assertEqual([entry["width"] for entry in self.draw.rects], [1, 1, 1, 1, 1])

    def test_panel_grows_with_the_content_and_fits_a_small_window(self):
        small = self.draw_hud(self.make_app(ultra_smooth=False), size=(320, 200))
        panel = small.blits[0][0]
        self.assertLessEqual(panel[0], 320)
        self.assertLessEqual(panel[1], 200)
        self.assertEqual(small.blits[0][1], (16, 16))
        # Chips are laid out left to right without overlapping or leaving the panel.
        chip_rects = [entry["rect"] for entry in self.draw.rects[1:]]
        self.assertEqual(len(chip_rects), 4)
        for previous, following in zip(chip_rects, chip_rects[1:]):
            self.assertLessEqual(previous[0] + previous[2], following[0])
        self.assertLessEqual(chip_rects[-1][0] + chip_rects[-1][2], 16 + panel[0])

    def test_text_is_rendered_once_per_status_change(self):
        app = self.make_app(current_fps=87.4)
        font, small_font = FakeFont(), FakeFont()
        screen = FakeSurface((640, 360))
        app._draw_hud(screen, font, small_font)
        first_frame = (tuple(font.rendered), tuple(small_font.rendered))
        self.assertIn("87", font.rendered)
        self.assertIn("F11  menu", small_font.rendered)
        app._draw_hud(screen, font, small_font)
        self.assertEqual((tuple(font.rendered), tuple(small_font.rendered)), first_frame)
        # A new FPS value or a mode toggle has to refresh the panel.
        app.current_fps = 91.2
        app._draw_hud(screen, font, small_font)
        self.assertIn("91", font.rendered)
        app.fsr_mode = True
        app._draw_hud(screen, font, small_font)
        self.assertIn("FSR ON", small_font.rendered)

    def test_hint_uses_the_configured_stop_key(self):
        app = self.make_app()
        app.hotkey_names = {"stop": "F4", "fps": "F6", "fsr": "F8"}
        small_font = FakeFont()
        app._draw_hud(FakeSurface((640, 360)), FakeFont(), small_font)
        self.assertIn("F4  menu", small_font.rendered)

    def test_hud_errors_are_contained_by_the_caller(self):
        # The overlay loop disables the panel instead of crashing when drawing fails.
        app = self.make_app()
        app.show_fps = True
        self.deps["pygame"].draw = MagicMock()
        with self.assertRaises(Exception):
            app._draw_hud(FakeSurface((640, 360)), MagicMock(get_width=MagicMock(side_effect=RuntimeError("boom"))),
                          FakeFont())

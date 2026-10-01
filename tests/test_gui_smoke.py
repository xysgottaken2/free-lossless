"""Exercise actual Tk widgets on the Windows runner (or xvfb-run on Linux)."""
import os
from pathlib import Path
import tempfile
import unittest

from helpers import load_module, stubs
from settings import SettingsStore, normalize_settings

try:
    import tkinter as tk
except ImportError:
    tk = None


@unittest.skipIf(tk is None, "Tk is not installed")
class RealTkSmokeTests(unittest.TestCase):
    def setUp(self):
        if os.name != "nt" and not os.environ.get("DISPLAY"):
            self.skipTest("Requires a desktop; run with xvfb-run on Linux")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = SettingsStore(Path(directory.name) / "settings.json")
        self.dependencies = stubs("selector")
        self.dependencies["selector"].WindowSelector.return_value.get_visible_windows.return_value = [
            {"hwnd": 42, "title": "Game", "process": "game.exe"},
        ]
        self.dependencies["selector"].DisplaySelector.get_displays.return_value = [
            {"source_type": "display", "device": r"\\.\DISPLAY1", "title": "Display 1 (Monitor principal)",
             "rect": (0, 0, 1920, 1080)},
            {"source_type": "display", "device": r"\\.\DISPLAY2", "title": "Display 2",
             "rect": (-1920, 0, 0, 1080)},
        ]
        self.module = load_module("ui", self.dependencies)

    def make_ui(self):
        ui = self.module.GameSelectorUI(settings_store=self.store)
        callback_errors = []
        ui.root.report_callback_exception = lambda kind, error, trace: callback_errors.append(error)
        self.addCleanup(self.assertEqual, callback_errors, [])
        self.addCleanup(lambda: ui._close_root() if not ui._closing else None)
        ui.root.update()
        return ui

    def display_button(self, ui):
        def walk(widget):
            for child in widget.winfo_children():
                yield child
                yield from walk(child)
        return next(widget for widget in walk(ui.root)
                    if isinstance(widget, tk.Radiobutton) and widget.cget("value") == "display")

    def run_pending_save(self, ui):
        ui.root.after(ui.SAVE_DELAY_MS + 100, ui.root.quit)
        ui.root.mainloop()

    def test_source_buttons_refresh_real_tree_and_select_a_display(self):
        ui = self.make_ui()
        self.assertEqual(ui.tree.item("0", "values"), ("Game", "game.exe"))
        ui.tree.selection_set("0")
        self.display_button(ui).invoke()
        self.assertEqual(ui.source_var.get(), "display")
        self.assertEqual(ui.tree.selection(), ())
        self.assertEqual(len(ui.tree.get_children()), 2)
        self.assertEqual(ui.tree.item("1", "values"), ("Display 2", "1920 x 1080 (-1920, 0)"))
        ui.tree.selection_set("1")
        ui._on_select()
        self.assertEqual(ui.selected_source["source_type"], "display")
        self.assertEqual(ui.selected_source["device"], r"\\.\DISPLAY2")
        self.assertNotIn("hwnd", ui.selected_source)
        reopened = self.make_ui()
        self.assertEqual(reopened.source_var.get(), "display")
        self.assertEqual(reopened.tree.selection(), ("1",))

    def test_overlay_start_restores_every_preference_when_returning_to_menu(self):
        preferences = normalize_settings({
            "source_type": "display", "mode": "dxcam", "fps": 120, "scale": "Fullscreen",
            "algo": "NVIDIA AI SuperRes", "sharpness": 80, "fg_enabled": False,
            "engine_type": "Fast (DIS Flow)", "ultra_smooth": True,
            "performance_mode": True, "low_latency": False,
            "preferred_sources": {"display": {"device": r"\\.\DISPLAY2"}},
        })
        self.store.save(preferences)
        ui = self.make_ui()
        self.assertEqual(ui._collect_settings(), preferences)
        self.assertEqual(str(ui.engine_combo.cget("state")), "disabled")
        ui.fps_var.set(90)
        ui._on_select()
        self.assertEqual(ui.selected_source["fps"], 90)
        reopened = self.make_ui()
        preferences["fps"] = 90
        self.assertEqual(reopened._collect_settings(), preferences)
        self.assertEqual(reopened.tree.selection(), ("1",))

    def test_window_manager_close_saves_without_waiting_for_debounce(self):
        ui = self.make_ui()
        ui.fps_var.set(90)
        ui.sharp_var.set(45)
        ui.fg_check.invoke()
        self.assertFalse(ui.fg_var.get())
        self.assertEqual(str(ui.engine_combo.cget("state")), "disabled")
        # Invoke the actual registered WM_DELETE_WINDOW handler, not just the method.
        ui.root.tk.call(ui.root.protocol("WM_DELETE_WINDOW"))
        self.assertTrue(ui._closing)
        self.assertIsNone(ui.selected_source)
        reopened = self.make_ui()
        self.assertEqual(reopened.fps_var.get(), 90)
        self.assertEqual(reopened.sharp_var.get(), 45)
        self.assertFalse(reopened.fg_var.get())

    def test_setting_changes_autosave_while_menu_stays_open(self):
        ui = self.make_ui()
        ui.fps_presets[120].invoke()
        ui.low_latency_check.invoke()
        self.run_pending_save(ui)
        self.assertTrue(ui.root.winfo_exists())
        saved = self.store.load()
        self.assertEqual(saved["fps"], 120)
        self.assertFalse(saved["low_latency"])
        self.assertEqual(ui.save_status_var.get(), "Todas as preferências salvas")

    def test_source_only_change_autosaves_and_reopens_with_new_handle(self):
        ui = self.make_ui()
        ui.tree.selection_set("0")
        self.run_pending_save(ui)
        self.assertEqual(self.store.load()["preferred_sources"]["window"], {"title": "Game", "process": "game.exe"})
        ui._close_root()
        self.dependencies["selector"].WindowSelector.return_value.get_visible_windows.return_value = [
            {"hwnd": 100, "title": "Game — new session", "process": "game.exe"},
        ]
        reopened = self.make_ui()
        self.assertEqual(reopened.tree.selection(), ("0",))
        self.assertEqual(reopened.sources["0"]["hwnd"], 100)
        self.assertEqual(reopened.selected_title_var.get(), "Game — new session")

    def test_small_window_keeps_start_visible_and_advanced_controls_scrollable(self):
        ui = self.make_ui()
        ui.root.geometry("940x620")
        ui.root.update()
        root_bottom = ui.root.winfo_rooty() + ui.root.winfo_height()
        button_bottom = ui.start_button.winfo_rooty() + ui.start_button.winfo_height()
        self.assertLessEqual(button_bottom, root_bottom)
        self.assertGreater(ui.tree.winfo_height(), 35)
        ui.low_latency_check.focus_force()
        ui.root.update()
        canvas_top = ui.settings_canvas.winfo_rooty()
        canvas_bottom = canvas_top + ui.settings_canvas.winfo_height()
        switch_top = ui.low_latency_check.winfo_rooty()
        self.assertGreaterEqual(switch_top, canvas_top)
        self.assertLessEqual(switch_top + ui.low_latency_check.winfo_height(), canvas_bottom)

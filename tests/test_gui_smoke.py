"""Exercise actual Tk widgets on the Windows runner (or xvfb-run on Linux)."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock

from helpers import load_module, stubs
from settings import HOTKEY_OPTIONS, SettingsStore, normalize_settings

try:
    import tkinter as tk
    from tkinter import ttk
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
        # Real message boxes would block the runner.
        self.module.messagebox = MagicMock()

    def make_ui(self):
        ui = self.module.GameSelectorUI(settings_store=self.store)
        callback_errors = []
        ui.root.report_callback_exception = lambda kind, error, trace: callback_errors.append(error)
        self.addCleanup(self.assertEqual, callback_errors, [])
        self.addCleanup(lambda: ui._close_root() if not ui._closing else None)
        ui.root.update()
        return ui

    def widgets(self, parent):
        for child in parent.winfo_children():
            yield child
            yield from self.widgets(child)

    def find(self, parent, kind, label=None):
        for widget in self.widgets(parent):
            if isinstance(widget, kind) and (label is None or widget.cget("text") == label):
                return widget
        raise AssertionError(f"{kind} {label!r} not found")

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
            "performance_mode": True, "low_latency": False, "frame_multiplier": 6,
            "show_fps": False, "hotkey_stop": "F4", "hotkey_fps": "F6", "hotkey_fsr": "F8",
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

    def test_frame_generation_slider_saves_and_reaches_the_overlay(self):
        ui = self.make_ui()
        # Only even multipliers up to twenty are offered.
        self.assertEqual(float(ui.multiplier_scale.cget("from")), 2)
        self.assertEqual(float(ui.multiplier_scale.cget("to")), 20)
        self.assertEqual(float(ui.multiplier_scale.cget("resolution")), 2)
        ui.multiplier_var.set(20)
        ui.root.update()
        self.assertEqual(ui.multiplier_value_var.get(), "x20")
        self.assertIn("19 frame(s) extra(s)", ui.multiplier_hint_var.get())
        self.run_pending_save(ui)
        self.assertEqual(self.store.load()["frame_multiplier"], 20)
        ui.tree.selection_set("0")
        ui._on_select()
        self.assertEqual(ui.selected_source["frame_multiplier"], 20)
        reopened = self.make_ui()
        self.assertEqual(reopened.multiplier_var.get(), 20)

    def test_settings_dialog_applies_hotkeys_and_saves_them(self):
        ui = self.make_ui()
        ui._open_settings_dialog()
        dialog = ui._settings_dialog
        self.assertIsNotNone(dialog)
        combos = [widget for widget in self.widgets(dialog) if isinstance(widget, ttk.Combobox)]
        self.assertEqual([list(combo.cget("values")) for combo in combos],
                         [list(HOTKEY_OPTIONS)] * 3)
        combos[0].set("F5")
        combos[1].set("F6")
        combos[2].set("F7")
        self.find(dialog, tk.Button, "Salvar").invoke()
        self.assertIsNone(ui._settings_dialog)
        ui.root.update()
        saved = self.store.load()
        self.assertEqual([saved[key] for key in ("hotkey_stop", "hotkey_fps", "hotkey_fsr")],
                         ["F5", "F6", "F7"])
        self.assertEqual(ui.hotkey_stop_var.get(), "F5")
        self.assertIn("F5 menu", ui.shortcuts_hint_var.get())
        ui.tree.selection_set("0")
        ui._on_select()
        self.assertEqual(ui.selected_source["hotkey_stop"], "F5")

    def test_settings_dialog_rejects_repeated_keys_and_cancel_changes_nothing(self):
        ui = self.make_ui()
        ui._open_settings_dialog()
        dialog = ui._settings_dialog
        combos = [widget for widget in self.widgets(dialog) if isinstance(widget, ttk.Combobox)]
        combos[1].set("F11")  # already used to stop the overlay
        self.find(dialog, tk.Button, "Salvar").invoke()
        ui.root.update()
        self.assertIsNotNone(ui._settings_dialog)  # the dialog stays open for a fix
        self.module.messagebox.showwarning.assert_called_once()
        self.assertEqual(ui.hotkey_fps_var.get(), "F10")
        combos[1].set("F6")
        self.find(dialog, tk.Button, "Cancelar").invoke()
        self.assertIsNone(ui._settings_dialog)
        self.assertEqual(self.store.load()["hotkey_fps"], "F10")
        self.assertEqual(ui.hotkey_fps_var.get(), "F10")

    def test_settings_dialog_reset_restores_defaults_in_the_form(self):
        ui = self.make_ui()
        ui._open_settings_dialog()
        dialog = ui._settings_dialog
        combos = [widget for widget in self.widgets(dialog) if isinstance(widget, ttk.Combobox)]
        combos[0].set("F2")
        self.find(dialog, tk.Button, "Restaurar padrões").invoke()
        ui.root.update()
        self.assertEqual([combo.get() for combo in combos], ["F11", "F10", "F9"])
        self.find(dialog, tk.Button, "Salvar").invoke()
        self.assertEqual(self.store.load()["hotkey_stop"], "F11")

    def test_small_window_keeps_start_visible_and_advanced_controls_scrollable(self):
        ui = self.make_ui()
        ui.root.geometry("940x620")
        ui.root.update()
        root_bottom = ui.root.winfo_rooty() + ui.root.winfo_height()
        button_bottom = ui.start_button.winfo_rooty() + ui.start_button.winfo_height()
        self.assertLessEqual(button_bottom, root_bottom)
        self.assertGreaterEqual(ui.tree.winfo_height(), 110)
        # The compaction must fit the whole source card: nothing may spill outside it.
        detail_bottom = ui.selected_detail_label.winfo_rooty() + ui.selected_detail_label.winfo_height()
        self.assertLessEqual(detail_bottom, root_bottom)
        ui.low_latency_check.focus_force()
        ui.root.update()
        canvas_top = ui.settings_canvas.winfo_rooty()
        canvas_bottom = canvas_top + ui.settings_canvas.winfo_height()
        switch_top = ui.low_latency_check.winfo_rooty()
        self.assertGreaterEqual(switch_top, canvas_top)
        self.assertLessEqual(switch_top + ui.low_latency_check.winfo_height(), canvas_bottom)

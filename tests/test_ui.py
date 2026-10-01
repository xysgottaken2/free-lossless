import unittest
from unittest.mock import MagicMock, call

from helpers import load_module, stubs
from settings import normalize_settings


class SelectionUITests(unittest.TestCase):
    def setUp(self):
        self.deps = stubs("tkinter", "tkinter.ttk", "tkinter.messagebox", "selector")
        self.module = load_module("ui", self.deps)
        self.ui = self.module.GameSelectorUI.__new__(self.module.GameSelectorUI)
        for name in ("root", "tree", "list_label", "selector", "source_count_var", "empty_label",
                     "start_button", "selected_title_var", "selected_detail_var", "save_status_var", "save_dot",
                     "settings_store", "fps_value_var", "sharp_value_var", "engine_combo", "session_summary_var"):
            setattr(self.ui, name, MagicMock())
        self.ui.tree.get_children.return_value = ["stale-window"]
        self.ui.tree.selection.return_value = []
        self.ui.selected_source = None
        self.ui.sources = {}
        self.ui.preferred_sources = {}
        self.ui.fps_presets = {}
        self.ui._save_job = None
        self.ui._closing = False
        self.ui._loading_settings = False
        self.ui._last_saved_settings = normalize_settings(None)
        settings = {
            "source_type": "window", "mode": "dxcam", "fps": 90, "scale": "Fullscreen", "algo": "Lanczos",
            "sharpness": 20, "fg_enabled": True, "engine_type": "Fast (DIS Flow)", "ultra_smooth": False,
            "performance_mode": False, "low_latency": True,
        }
        for key, name in self.ui.SETTING_VARIABLES.items():
            variable = MagicMock()
            variable.get.return_value = settings[key]
            setattr(self.ui, name, variable)

    def test_switch_to_display_clears_stale_sources_and_preserves_settings(self):
        self.ui.source_var.get.return_value = "display"
        source = {"source_type": "display", "device": r"\\.\DISPLAY2", "title": "Display 2",
                  "rect": (-1920, 0, 0, 1080)}
        self.deps["selector"].DisplaySelector.get_displays.return_value = [source]
        self.ui._refresh_list()
        self.ui.tree.delete.assert_called_once_with("stale-window")
        self.ui.selector.get_visible_windows.assert_not_called()
        self.ui.tree.selection.return_value = ["0"]
        self.ui._on_select()
        self.assertEqual(self.ui.selected_source["source_type"], "display")
        self.assertEqual(self.ui.selected_source["device"], r"\\.\DISPLAY2")
        self.assertNotIn("hwnd", self.ui.selected_source)
        self.assertEqual(self.ui.selected_source["mode"], "dxcam")
        self.assertEqual(self.ui.selected_source["fps"], 90)
        self.assertEqual(self.ui.selected_source["scale"], "Fullscreen")
        self.ui.root.destroy.assert_called_once()
        saved = self.ui.settings_store.save.call_args.args[0]
        self.assertEqual(saved["preferred_sources"], {"display": {"device": r"\\.\DISPLAY2"}})
        self.assertNotIn("rect", saved["preferred_sources"]["display"])

    def test_window_selection_still_keeps_live_hwnd_but_never_saves_it(self):
        self.ui.selector.get_visible_windows.return_value = [{"hwnd": 42, "title": "Game", "process": "game.exe"}]
        self.ui._refresh_list()
        self.ui.tree.selection.return_value = ["0"]
        self.ui._on_select()
        self.assertEqual(self.ui.selected_source["source_type"], "window")
        self.assertEqual(self.ui.selected_source["hwnd"], 42)
        saved = self.ui.settings_store.save.call_args.args[0]
        self.assertEqual(saved["preferred_sources"]["window"], {"title": "Game", "process": "game.exe"})

    def test_empty_selection_does_not_close_menu(self):
        self.ui._on_select()
        self.assertIsNone(self.ui.selected_source)
        self.ui.root.destroy.assert_not_called()
        self.ui.settings_store.save.assert_not_called()
        self.module.messagebox.showinfo.assert_called_once()

    def test_closing_without_starting_saves_every_setting_before_destroying_root(self):
        order = MagicMock()
        order.attach_mock(self.ui.settings_store.save, "save")
        order.attach_mock(self.ui.root.destroy, "destroy")
        self.ui._save_job = "pending-save"
        self.ui._on_close()
        saved = self.ui._collect_settings()
        self.assertEqual(order.mock_calls, [call.save(saved), call.destroy()])
        self.ui.root.after_cancel.assert_called_once_with("pending-save")
        self.assertIsNone(self.ui.selected_source)
        self.assertTrue(self.ui._closing)
        self.assertEqual(saved["engine_type"], "Fast (DIS Flow)")
        self.assertEqual(saved["low_latency"], True)

    def test_starting_overlay_flushes_pending_save_before_destroying_root(self):
        self.ui.sources = {"0": {"hwnd": 42, "title": "Game", "process": "game.exe", "source_type": "window"}}
        self.ui.tree.selection.return_value = ["0"]
        self.ui._save_job = "pending-save"
        order = MagicMock()
        order.attach_mock(self.ui.settings_store.save, "save")
        order.attach_mock(self.ui.root.destroy, "destroy")
        self.ui._on_select()
        self.assertEqual([item[0] for item in order.mock_calls], ["save", "destroy"])
        self.ui.root.after_cancel.assert_called_once_with("pending-save")
        self.assertEqual(self.ui.selected_source["fps"], 90)
        self.assertNotIn("preferred_sources", self.ui.selected_source)

    def test_setting_changes_debounce_autosave_and_update_summary(self):
        self.ui.root.after.return_value = "save-job"
        self.ui._on_settings_change()
        self.ui.root.after.assert_called_once_with(500, self.ui._autosave)
        self.ui.settings_store.save.assert_not_called()
        self.ui.fps_value_var.set.assert_called_with("90 FPS")
        self.ui._on_settings_change()
        self.ui.root.after_cancel.assert_called_once_with("save-job")
        self.ui._autosave()
        self.ui.settings_store.save.assert_called_once_with(self.ui._collect_settings())
        self.assertIsNone(self.ui._save_job)

    def test_reverting_a_pending_change_cancels_save_and_clears_pending_status(self):
        self.ui._last_saved_settings = self.ui._collect_settings()
        self.ui._save_job = "pending-save"
        self.ui._schedule_save()
        self.ui.root.after_cancel.assert_called_once_with("pending-save")
        self.ui.root.after.assert_not_called()
        self.ui.save_status_var.set.assert_called_with("Nenhuma alteração pendente")

    def test_save_failure_warns_but_does_not_prevent_closing(self):
        self.ui.settings_store.save.side_effect = PermissionError("read-only directory")
        self.ui._on_close()
        self.module.messagebox.showwarning.assert_called_once()
        self.ui.save_status_var.set.assert_called_with("Não foi possível salvar")
        self.ui.root.destroy.assert_called_once()

    def test_background_save_failure_does_not_open_repeated_dialogs(self):
        self.ui.settings_store.save.side_effect = OSError("disk full")
        self.ui._autosave()
        self.module.messagebox.showwarning.assert_not_called()
        self.ui.root.destroy.assert_not_called()
        self.ui.save_status_var.set.assert_called_with("Não foi possível salvar")

    def test_refresh_restores_source_using_new_handle(self):
        self.ui.preferred_sources = {"window": {"title": "Game", "process": "game.exe"}}
        self.ui.selector.get_visible_windows.return_value = [{"hwnd": 100, "title": "Game", "process": "game.exe"}]
        self.ui._refresh_list()
        self.ui.tree.selection_set.assert_called_once_with("0")
        self.assertEqual(self.ui.sources["0"]["hwnd"], 100)

    def test_changed_window_title_restores_only_an_unambiguous_process(self):
        self.ui.preferred_sources = {"window": {"title": "Old title", "process": "game.exe"}}
        self.ui.sources = {"0": {"hwnd": 100, "title": "New title", "process": "GAME.EXE"}}
        self.assertEqual(self.ui._find_remembered_source(), "0")
        self.ui.sources["1"] = {"hwnd": 101, "title": "Launcher", "process": "game.exe"}
        self.assertIsNone(self.ui._find_remembered_source())

    def test_missing_source_leaves_preferences_intact_and_start_disabled(self):
        self.ui.source_var.get.return_value = "display"
        self.ui.preferred_sources = {"display": {"device": r"\\.\DISPLAY2"}}
        self.deps["selector"].DisplaySelector.get_displays.return_value = []
        self.ui._refresh_list()
        self.ui.tree.selection_set.assert_not_called()
        self.ui.start_button.config.assert_called_with(state=self.module.tk.DISABLED, bg=self.module.COLORS["input"])
        self.assertEqual(self.ui.preferred_sources, {"display": {"device": r"\\.\DISPLAY2"}})
        self.ui.empty_label.place.assert_called_once()

    def test_disabling_generation_disables_engine_without_resetting_preference(self):
        self.ui.fg_var.get.return_value = False
        self.ui._update_setting_display()
        self.ui.engine_combo.configure.assert_called_with(state="disabled")
        self.assertEqual(self.ui._collect_settings()["engine_type"], "Fast (DIS Flow)")
        self.assertFalse(self.ui._collect_settings()["fg_enabled"])

    def test_source_only_change_schedules_save_without_mutating_saved_snapshot(self):
        snapshot = self.ui._collect_settings()
        self.ui._last_saved_settings = snapshot
        self.ui.sources = {"0": {"hwnd": 42, "title": "Game", "process": "game.exe", "source_type": "window"}}
        self.ui.tree.selection.return_value = ["0"]
        self.ui._on_source_change()
        self.assertEqual(snapshot["preferred_sources"], {})
        self.ui.root.after.assert_called_once_with(500, self.ui._autosave)
        self.ui._autosave()
        saved = self.ui.settings_store.save.call_args.args[0]
        self.assertEqual(saved["preferred_sources"]["window"], {"title": "Game", "process": "game.exe"})

    def test_keyboard_focus_scrolls_hidden_advanced_controls_into_view(self):
        self.ui._ui_scale = 1.0
        self.ui.settings_canvas = MagicMock()
        self.ui.settings_content = MagicMock()
        self.ui.settings_content.winfo_height.return_value = 800
        self.ui.settings_content.winfo_rooty.return_value = 100
        self.ui.settings_canvas.winfo_height.return_value = 300
        self.ui.settings_canvas.canvasy.return_value = 0
        event = MagicMock()
        event.widget.winfo_rooty.return_value = 500
        event.widget.winfo_height.return_value = 40
        self.ui._reveal_setting(event)
        self.ui.settings_canvas.yview_moveto.assert_called_once_with(164 / 800)
        self.ui.settings_canvas.yview_moveto.reset_mock()
        event.widget.winfo_rooty.return_value = 110
        self.ui._reveal_setting(event)
        self.ui.settings_canvas.yview_moveto.assert_not_called()

    def test_menu_close_writes_real_preferences_that_a_new_store_can_restore(self):
        from pathlib import Path
        import tempfile
        from settings import SettingsStore

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            self.ui.settings_store = SettingsStore(path)
            self.ui.sharp_var.get.return_value = 0
            self.ui.fg_var.get.return_value = False
            self.ui.low_latency_var.get.return_value = False
            self.ui.ultra_smooth_var.get.return_value = True
            self.ui.perf_mode_var.get.return_value = True
            self.ui._on_close()
            self.assertEqual(SettingsStore(path).load(), self.ui._collect_settings())
            self.assertEqual(SettingsStore(path).load()["sharpness"], 0)
            self.assertFalse(SettingsStore(path).load()["fg_enabled"])

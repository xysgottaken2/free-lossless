import unittest
from unittest.mock import MagicMock, call

import i18n
from helpers import load_module, stubs
from settings import normalize_settings


class FakeVar:
    """Minimal stand-in for a tkinter variable."""

    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class SelectionUITests(unittest.TestCase):

    def setUp(self):
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "en")
        self.deps = stubs("tkinter", "tkinter.ttk", "tkinter.messagebox", "selector")
        self.module = load_module("ui", self.deps)
        self.ui = self.module.GameSelectorUI.__new__(self.module.GameSelectorUI)
        self.ui._choice_displays = []
        for name in ("root", "tree", "list_label", "selector", "source_count_var", "empty_label",
                     "start_button", "selected_title_var", "selected_detail_var", "save_status_var", "save_dot",
                     "settings_store", "fps_value_var", "sharp_value_var", "engine_combo", "session_summary_var",
                     "algo_hint_var", "algo_combo", "sharp_scale", "filters_hint_var", "filters_hint_label",
                     "filter_combo", "filter_hint_var", "reshade_hint_var", "reshade_hint_label",
                     "internal_res_combo", "unlimited_button", "fps_scale"):
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
        # Start from the real defaults so new preferences cannot break this suite.
        settings = {**normalize_settings(None), "mode": "dxcam", "fps": 90, "scale": "Fullscreen",
                    "engine_type": "Fast (DIS Flow)"}
        for key, name in self.ui.SETTING_VARIABLES.items():
            setattr(self.ui, name, FakeVar(settings[key]))
        for name in ("multiplier_value_var", "multiplier_hint_var", "shortcuts_hint_var", "dialog_error_var"):
            setattr(self.ui, name, MagicMock())
        self.ui.multiplier_hint_label = MagicMock()
        self.ui.multiplier_scale = MagicMock()
        self.ui.dialog_error_label = MagicMock()
        self.ui._settings_dialog = None
        self.ui.root.winfo_exists.return_value = True

    def test_switch_to_display_clears_stale_sources_and_preserves_settings(self):
        self.ui.source_var.value = "display"
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
        self.ui.save_status_var.set.assert_called_with("No pending changes")

    def test_save_failure_warns_but_does_not_prevent_closing(self):
        self.ui.settings_store.save.side_effect = PermissionError("read-only directory")
        self.ui._on_close()
        self.module.messagebox.showwarning.assert_called_once()
        self.ui.save_status_var.set.assert_called_with("Could not save")
        self.ui.root.destroy.assert_called_once()

    def test_background_save_failure_does_not_open_repeated_dialogs(self):
        self.ui.settings_store.save.side_effect = OSError("disk full")
        self.ui._autosave()
        self.module.messagebox.showwarning.assert_not_called()
        self.ui.root.destroy.assert_not_called()
        self.ui.save_status_var.set.assert_called_with("Could not save")

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
        self.ui.source_var.value = "display"
        self.ui.preferred_sources = {"display": {"device": r"\\.\DISPLAY2"}}
        self.deps["selector"].DisplaySelector.get_displays.return_value = []
        self.ui._refresh_list()
        self.ui.tree.selection_set.assert_not_called()
        self.ui.start_button.config.assert_called_with(state=self.module.tk.DISABLED, bg=self.module.COLORS["input"])
        self.assertEqual(self.ui.preferred_sources, {"display": {"device": r"\\.\DISPLAY2"}})
        self.ui.empty_label.place.assert_called_once()

    def test_disabling_generation_disables_engine_without_resetting_preference(self):
        self.ui.fg_var.value = False
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

    def test_multiplier_slider_shows_the_selected_factor_and_cadence(self):
        self.ui.multiplier_var.value = 6
        self.ui._update_setting_display()
        self.ui.multiplier_value_var.set.assert_called_with("x6")
        hint = self.ui.multiplier_hint_var.set.call_args.args[0]
        self.assertIn("5 extra frame(s)", hint)
        self.assertIn("capture at 15 FPS", hint)
        self.assertIn("output at 90 FPS", hint)
        self.ui.multiplier_hint_label.config.assert_called_with(fg=self.module.COLORS["muted"])

    def test_high_multipliers_warn_about_the_cost(self):
        self.ui.multiplier_var.value = 20
        self.ui._update_setting_display()
        hint = self.ui.multiplier_hint_var.set.call_args.args[0]
        self.assertIn("19 extra frame(s)", hint)
        self.assertIn("capture at 4 FPS", hint)
        self.assertIn("GPU", hint)
        self.ui.multiplier_hint_label.config.assert_called_with(fg=self.module.COLORS["warning"])

    def test_the_filter_toggle_disables_the_algorithm_and_the_sharpness(self):
        self.ui.filters_var.value = False
        self.ui._update_setting_display()
        self.assertEqual(str(self.ui.algo_combo.configure.call_args.kwargs["state"]), "disabled")
        self.assertEqual(self.ui.sharp_scale.configure.call_args.kwargs["state"],
                         self.deps["tkinter"].DISABLED)
        self.assertEqual(self.ui.filters_hint_var.set.call_args.args[0],
                         "Image filters are off in this session.")

    def test_the_filter_toggle_keeps_the_algorithm_when_it_is_on(self):
        self.ui.filters_var.value = True
        self.ui._update_setting_display()
        self.assertEqual(str(self.ui.algo_combo.configure.call_args.kwargs["state"]), "readonly")
        self.assertEqual(self.ui.filters_hint_var.set.call_args.args[0], "")

    def test_the_filter_preference_is_saved_and_reloaded(self):
        self.ui.filters_var.value = False
        self.assertFalse(self.ui._collect_settings()["filters_enabled"])
        self.ui.filters_var.value = True
        self.assertTrue(self.ui._collect_settings()["filters_enabled"])

    def test_unlimited_turns_off_the_rate_controls(self):
        self.ui.unlimited_var.value = True
        self.ui._update_setting_display()
        self.assertEqual(str(self.ui.fps_scale.configure.call_args.kwargs["state"]),
                         str(self.deps["tkinter"].DISABLED))
        self.assertEqual(self.ui.fps_value_var.set.call_args.args[0], "Unlimited")

    def test_the_rate_controls_come_back_when_unlimited_is_off(self):
        self.ui.unlimited_var.value = False
        self.ui._update_setting_display()
        self.assertEqual(str(self.ui.fps_scale.configure.call_args.kwargs["state"]),
                         str(self.deps["tkinter"].NORMAL))
        self.assertIn("90", self.ui.fps_value_var.set.call_args.args[0])

    def test_unlimited_is_saved_and_reloaded(self):
        self.ui.unlimited_var.value = True
        self.assertTrue(self.ui._collect_settings()["unlimited_fps"])
        self.ui.unlimited_var.value = False
        self.assertFalse(self.ui._collect_settings()["unlimited_fps"])

    def test_the_multiplier_hint_has_no_capture_schedule_in_unlimited(self):
        self.ui.unlimited_var.value = True
        self.ui._update_setting_display()
        self.assertIn("unlimited", str(self.ui.multiplier_hint_var.set.call_args).lower())

    def test_the_internal_resolution_is_saved_and_reloaded(self):
        self.ui.internal_res_var.value = "HD"
        self.assertEqual(self.ui._collect_settings()["internal_resolution"], "HD")
        self.ui.internal_res_var.value = "Nada"
        self.assertEqual(self.ui._collect_settings()["internal_resolution"], "Auto")

    def test_the_internal_resolution_is_locked_when_the_filters_are_off(self):
        self.ui.filters_var.value = False
        self.ui._update_setting_display()
        self.assertEqual(str(self.ui.internal_res_combo.configure.call_args.kwargs["state"]),
                         "disabled")

    def test_the_filter_preset_is_saved_and_reloaded(self):
        self.ui.filter_var.value = "Sharp"
        self.assertEqual(self.ui._collect_settings()["filter_preset"], "Sharp")
        self.ui.filter_var.value = "Nope"          # a hand-edited file falls back to Off
        self.assertEqual(self.ui._collect_settings()["filter_preset"], "Off")

    def test_the_reshade_hint_appears_only_for_a_game_that_has_it(self):
        from unittest.mock import patch
        self.ui.selected_source = {"source_type": "window", "process": "game.exe"}
        with patch.object(self.module, "reshade") as reshade:
            reshade.installed_for_process.return_value = (r"C:\Game", ["ReShade.ini", "dxgi.dll"])
            self.ui._refresh_reshade_hint()
            self.assertIn("ReShade.ini", self.ui.reshade_hint_var.set.call_args.args[0])
            reshade.installed_for_process.return_value = (None, [])
            self.ui._refresh_reshade_hint()
            self.assertEqual(self.ui.reshade_hint_var.set.call_args.args[0], "")

    def test_a_display_source_never_looks_for_reshade(self):
        from unittest.mock import patch
        self.ui.selected_source = {"source_type": "display", "device": r"\\.\DISPLAY1"}
        with patch.object(self.module, "reshade") as reshade:
            self.ui._refresh_reshade_hint()
            reshade.installed_for_process.assert_not_called()
            self.assertEqual(self.ui.reshade_hint_var.set.call_args.args[0], "")

    def test_generation_settings_are_disabled_without_interpolation(self):
        self.ui.fg_var.value = False
        self.ui._update_setting_display()
        self.ui.multiplier_scale.configure.assert_called_with(state=self.module.tk.DISABLED)
        self.assertIn("Enable frame interpolation", self.ui.multiplier_hint_var.set.call_args.args[0])
        self.ui.fg_var.value = True
        self.ui._update_setting_display()
        self.ui.multiplier_scale.configure.assert_called_with(state=self.module.tk.NORMAL)

    def test_summary_and_shortcuts_follow_the_multiplication_and_hotkeys(self):
        self.ui.multiplier_var.value = 4
        self.ui.hotkey_stop_var.value = "F2"
        self.ui.hotkey_fps_var.value = "F3"
        self.ui.hotkey_fsr_var.value = "F4"
        self.ui._update_setting_display()
        self.assertIn("x4 interpolation", self.ui.session_summary_var.set.call_args.args[0])
        self.assertEqual(self.ui.shortcuts_hint_var.set.call_args.args[0],
                         "F2 menu  ·  F3 FPS  ·  F4 FSR  ·  Ctrl + Enter starts the overlay")

    def make_dialog_vars(self, stop="F11", fps="F10", fsr="F9", show_fps=True, language="English (US)"):
        return {"hotkey_stop": FakeVar(stop), "hotkey_fps": FakeVar(fps),
                "hotkey_fsr": FakeVar(fsr), "show_fps": FakeVar(show_fps),
                "language": FakeVar(language)}

    def test_dialog_hotkey_validation_flags_repeated_keys(self):
        self.assertTrue(self.ui._validate_dialog_hotkeys(self.make_dialog_vars()))
        self.assertIn("its own key", self.ui.dialog_error_var.set.call_args.args[0])
        self.assertFalse(self.ui._validate_dialog_hotkeys(self.make_dialog_vars(fsr="F11")))
        message = self.ui.dialog_error_var.set.call_args.args[0]
        self.assertIn("different key", message)
        self.ui.dialog_error_label.config.assert_called_with(fg=self.module.COLORS["warning"])

    def test_applying_the_dialog_updates_settings_saves_and_closes(self):
        self.ui._close_settings_dialog = MagicMock()
        self.ui._save_settings = MagicMock(return_value=True)
        self.ui._apply_dialog_settings(self.make_dialog_vars(stop="F1", fps="F2", fsr="F3", show_fps=False))
        self.assertEqual(self.ui.hotkey_stop_var.value, "F1")
        self.assertEqual(self.ui.hotkey_fps_var.value, "F2")
        self.assertEqual(self.ui.hotkey_fsr_var.value, "F3")
        self.assertFalse(self.ui.show_fps_var.value)
        self.ui._close_settings_dialog.assert_called_once()
        self.ui._save_settings.assert_called_once_with(notify=True)

    def test_applying_the_dialog_refuses_duplicate_keys(self):
        self.ui._close_settings_dialog = MagicMock()
        self.ui._save_settings = MagicMock(return_value=True)
        self.ui._apply_dialog_settings(self.make_dialog_vars(fps="F11"))
        self.ui._close_settings_dialog.assert_not_called()
        self.ui._save_settings.assert_not_called()
        self.assertEqual(self.ui.hotkey_fps_var.value, "F10")
        self.module.messagebox.showwarning.assert_called_once()

    def test_reset_restores_hotkeys_and_overlay_defaults_in_the_dialog(self):
        variables = self.make_dialog_vars(stop="F1", fps="F2", fsr="F3", show_fps=False)
        self.ui._reset_dialog(variables)
        self.assertEqual(variables["hotkey_stop"].value, "F11")
        self.assertEqual(variables["hotkey_fps"].value, "F10")
        self.assertEqual(variables["hotkey_fsr"].value, "F9")
        self.assertTrue(variables["show_fps"].value)
        self.assertEqual(variables["language"].value, "English (US)")

    def test_stored_language_is_saved_and_kept_in_the_selection(self):
        self.ui.language_var = FakeVar("pt-BR")
        self.assertEqual(self.ui._collect_settings()["language"], "pt-BR")

    def test_switching_language_rebuilds_the_menu_and_keeps_the_preferences(self):
        self.ui.language_var = FakeVar("en")
        self.ui._setup_ui = MagicMock()
        self.ui._refresh_list = MagicMock()
        self.ui._update_setting_display = MagicMock()
        self.ui._set_save_status = MagicMock()
        self.ui._apply_language("pt-BR")
        self.assertEqual(i18n.get_language(), "pt-BR")
        self.assertEqual(self.ui.language_var.value, "pt-BR")
        self.ui._setup_ui.assert_called_once()
        self.ui._refresh_list.assert_called_once()
        self.ui._update_setting_display.assert_called_once()
        self.assertTrue(self.ui._loading_settings is False)

    def test_dialog_language_choice_is_applied_and_persisted(self):
        self.ui._close_settings_dialog = MagicMock()
        self.ui._save_settings = MagicMock(return_value=True)
        self.ui._setup_ui = MagicMock()
        self.ui._refresh_list = MagicMock()
        self.ui._update_setting_display = MagicMock()
        self.ui._set_save_status = MagicMock()
        self.ui.language_var = FakeVar("en")
        self.ui._apply_dialog_settings(self.make_dialog_vars(language="简体中文"))
        self.assertEqual(self.ui.language_var.value, "zh-CN")
        self.assertEqual(i18n.get_language(), "zh-CN")
        self.ui._save_settings.assert_called_once_with(notify=True)
        self.ui._setup_ui.assert_called_once()

    def test_saving_without_changing_the_language_does_not_rebuild_the_window(self):
        self.ui._close_settings_dialog = MagicMock()
        self.ui._save_settings = MagicMock(return_value=True)
        self.ui._setup_ui = MagicMock()
        self.ui.language_var = FakeVar("en")
        self.ui._apply_dialog_settings(self.make_dialog_vars(language="English (US)"))
        self.ui._setup_ui.assert_not_called()

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
            self.ui.sharp_var.value = 0
            self.ui.fg_var.value = False
            self.ui.low_latency_var.value = False
            self.ui.ultra_smooth_var.value = True
            self.ui.perf_mode_var.value = True
            self.ui._on_close()
            self.assertEqual(SettingsStore(path).load(), self.ui._collect_settings())
            self.assertEqual(SettingsStore(path).load()["sharpness"], 0)
            self.assertFalse(SettingsStore(path).load()["fg_enabled"])


class ReshadeSectionTests(unittest.TestCase):
    """The menu shows the drawing mode and whether ReShade can hook the overlay."""

    def setUp(self):
        # Reuse the harness without inheriting its tests (which would run twice).
        SelectionUITests.setUp(self)
        for name in ("display_mode_combo", "reshade_status_var", "reshade_status_label",
                     "reshade_button"):
            setattr(self.ui, name, MagicMock())

    def test_the_drawing_mode_is_saved_and_reloaded(self):
        self.ui.display_mode_var.value = "D3D11"
        self.assertEqual(self.ui._collect_settings()["display_mode"], "D3D11")
        self.ui.display_mode_var.value = "Outro"
        self.assertEqual(self.ui._collect_settings()["display_mode"], "GDI")

    def test_the_status_reports_reshade_next_to_the_app(self):
        from unittest.mock import patch
        with patch.object(self.module, "reshade") as reshade:
            reshade.detect.return_value = ["ReShade.ini", "dxgi.dll"]
            self.ui._refresh_reshade_status()
            message = self.ui.reshade_status_var.set.call_args.args[0]
            self.assertIn("ReShade.ini", message)
            reshade.detect.return_value = []
            self.ui._refresh_reshade_status()
            self.assertIn("not installed", self.ui.reshade_status_var.set.call_args.args[0])

    def test_the_download_starts_in_a_thread_and_the_menu_polls(self):
        from unittest.mock import patch
        self.ui.root = MagicMock()
        self.ui._closing = False
        with patch.object(self.module, "threading") as threading, \
                patch.object(self.module, "reshade"):
            self.ui._download_reshade()
            self.assertTrue(threading.Thread.return_value.start.called)
        self.ui.reshade_button.config.assert_called_with(state=self.deps["tkinter"].DISABLED)
        self.assertIn("Downloading", self.ui.reshade_status_var.set.call_args.args[0])
        self.assertTrue(self.ui.root.after.called)

    def test_the_poll_waits_while_the_download_is_running(self):
        self.ui.root = MagicMock()
        self.ui._closing = False
        self.ui.root.after.reset_mock()
        self.ui._reshade_result = None
        self.ui._poll_reshade_download()
        self.assertEqual(self.ui.root.after.call_args.args[1].__name__, "_poll_reshade_download")
        self.assertEqual(self.ui.root.after.call_args.args[0], self.module.RESHADE_POLL_MS)

    def test_a_finished_download_updates_the_menu(self):
        from unittest.mock import patch
        self.ui._reshade_result = (r"C:\App\ReShade_Setup.exe", None)
        with patch.object(self.ui, "_reshade_download_finished") as finished:
            self.ui._poll_reshade_download()
        finished.assert_called_once_with(r"C:\App\ReShade_Setup.exe", None)
        self.assertIsNone(self.ui._reshade_result)

    def test_the_menu_shows_where_the_installer_was_saved(self):
        from unittest.mock import patch
        with patch.object(self.module, "reshade") as reshade:
            self.ui._reshade_download_finished(r"C:\App\ReShade_Setup.exe", None)
            reshade.open_folder.assert_called_once()
        self.assertIn("ReShade_Setup.exe", self.ui.reshade_status_var.set.call_args.args[0])

    def test_a_failed_download_is_shown_and_the_button_comes_back(self):
        self.ui._reshade_download_finished(None, "sem rede")
        self.assertIn("sem rede", self.ui.reshade_status_var.set.call_args.args[0])
        self.ui.reshade_button.config.assert_called_with(state=self.deps["tkinter"].NORMAL)

    def test_the_poll_stops_when_the_menu_is_closing(self):
        self.ui.root = MagicMock()
        self.ui._closing = True
        self.ui._reshade_result = None
        self.ui._poll_reshade_download()
        self.assertFalse(self.ui.root.after.called)

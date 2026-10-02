import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from settings import (
    DEFAULT_SETTINGS, HOTKEY_OPTIONS, HOTKEY_SETTING_KEYS, SettingsStore, get_settings_path,
    hotkey_conflicts, normalize_settings, source_identity, unique_hotkeys,
)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "FreeLossless" / "settings.json"
        self.store = SettingsStore(self.path)

    def test_missing_file_uses_independent_defaults_without_creating_file(self):
        first = self.store.load()
        first["preferred_sources"]["window"] = {"title": "Game", "process": "game.exe"}
        second = self.store.load()
        self.assertEqual(second["fps"], 60)
        self.assertEqual(second["preferred_sources"], {})
        self.assertIsNone(self.store.load_error)
        self.assertFalse(self.path.exists())

    def test_all_preferences_round_trip_in_new_store(self):
        preferences = {
            "source_type": "display", "mode": "dxcam", "fps": 120, "scale": "Fullscreen",
            "algo": "FSR 1.0 / CAS (Nitidez)", "sharpness": 0, "fg_enabled": False,
            "engine_type": "Fast (DIS Flow)", "ultra_smooth": True,
            "performance_mode": True, "low_latency": False,
            "preferred_sources": {
                "window": {"title": "Jogo — ação", "process": "game.exe", "hwnd": 42},
                "display": {"device": r"\\.\DISPLAY2", "rect": [-1920, 0, 0, 1080]},
            },
        }
        self.store.save(preferences)
        self.assertEqual(SettingsStore(self.path).load(), normalize_settings(preferences))
        serialized = self.path.read_text(encoding="utf-8")
        self.assertIn("ação", serialized)
        self.assertNotIn("hwnd", serialized)
        self.assertNotIn("rect", serialized)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_invalid_values_fall_back_but_valid_fields_survive(self):
        result = normalize_settings({
            "source_type": "camera", "mode": "unknown", "fps": True, "scale": 2.0,
            "algo": None, "sharpness": 101, "fg_enabled": "false",
            "engine_type": "unknown", "ultra_smooth": True, "performance_mode": False,
            "low_latency": 0, "unknown": "ignored",
            "preferred_sources": {"display": {"device": 2}, "window": {"hwnd": 42}},
        })
        expected = normalize_settings(None)
        expected["ultra_smooth"] = True
        self.assertEqual(result, expected)
        for value in (0, 29, 121, 60.5, "90", None):
            with self.subTest(fps=value):
                self.assertEqual(normalize_settings({"fps": value})["fps"], 60)

    def test_partial_file_keeps_defaults_for_missing_fields(self):
        self.path.parent.mkdir()
        self.path.write_text('{"fps": 90, "low_latency": false}', encoding="utf-8")
        loaded = self.store.load()
        self.assertEqual(loaded["fps"], 90)
        self.assertFalse(loaded["low_latency"])
        self.assertEqual(loaded["algo"], "Lanczos")
        self.assertTrue(loaded["fg_enabled"])

    def test_corrupt_files_do_not_block_startup_and_can_be_repaired(self):
        self.path.parent.mkdir()
        for content in (b'{"fps":', b'[]', b'null', b'\xff\xfe'):
            with self.subTest(content=content):
                self.path.write_bytes(content)
                self.assertEqual(self.store.load(), normalize_settings(None))
                self.assertIsNotNone(self.store.load_error)
                self.assertEqual(self.path.read_bytes(), content)
                self.store.save({"fps": 90})
                self.assertIsNone(self.store.load_error)
                self.assertEqual(json.loads(self.path.read_text())["fps"], 90)

    def test_unreadable_file_falls_back_with_visible_error(self):
        with patch.object(Path, "open", side_effect=PermissionError("access denied")):
            self.assertEqual(self.store.load(), normalize_settings(None))
        self.assertIn("access denied", self.store.load_error)

    def test_failed_atomic_replace_preserves_previous_file_and_cleans_temporary_file(self):
        self.store.save({"fps": 60})
        previous = self.path.read_bytes()
        with patch("settings.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaisesRegex(PermissionError, "locked"):
                self.store.save({"fps": 120})
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertEqual(self.store.load()["fps"], 60)

    def test_failed_write_preserves_previous_file_and_cleans_temporary_file(self):
        self.store.save({"fps": 60})
        previous = self.path.read_bytes()
        with patch("settings.json.dump", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.store.save({"fps": 90})
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_windows_path_is_per_user_and_independent_of_executable(self):
        with patch("settings.sys.platform", "win32"), patch.dict(os.environ, {"LOCALAPPDATA": str(self.path.parent)}, clear=True):
            self.assertEqual(get_settings_path(), self.path.parent / "FreeLossless" / "settings.json")
        with patch("settings.sys.platform", "win32"), patch.dict(os.environ, {"APPDATA": str(self.path.parent)}, clear=True):
            self.assertEqual(get_settings_path(), self.path.parent / "FreeLossless" / "settings.json")
        with patch("settings.sys.platform", "win32"), patch.dict(os.environ, {}, clear=True), patch("settings.Path.home", return_value=self.path.parent):
            self.assertEqual(get_settings_path(), self.path.parent / "AppData" / "Local" / "FreeLossless" / "settings.json")

    def test_non_windows_path_respects_xdg_config_home(self):
        with patch("settings.sys.platform", "linux"), patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.path.parent)}):
            self.assertEqual(get_settings_path(), self.path.parent / "free-lossless" / "settings.json")

    def test_frame_multiplier_defaults_to_doubling(self):
        self.assertEqual(normalize_settings(None)["frame_multiplier"], 2)

    def test_frame_multiplier_accepts_even_values_within_range(self):
        for value in (2, 4, 6, 10, 20):
            with self.subTest(value=value):
                self.assertEqual(normalize_settings({"frame_multiplier": value})["frame_multiplier"], value)

    def test_invalid_frame_multipliers_fall_back_to_doubling(self):
        for value in (0, 1, 21, 22, 7, 3.0, True, "4", None):
            with self.subTest(value=value):
                self.assertEqual(normalize_settings({"frame_multiplier": value})["frame_multiplier"], 2)

    def test_hotkeys_default_to_f11_f10_f9(self):
        loaded = normalize_settings(None)
        self.assertEqual({key: loaded[key] for key in HOTKEY_SETTING_KEYS},
                         {"hotkey_stop": "F11", "hotkey_fps": "F10", "hotkey_fsr": "F9"})

    def test_hotkeys_keep_valid_choices_and_reject_unknown_keys(self):
        loaded = normalize_settings({"hotkey_stop": "F4", "hotkey_fps": "Ctrl+Q", "hotkey_fsr": "f8"})
        self.assertEqual(loaded["hotkey_stop"], "F4")
        self.assertEqual(loaded["hotkey_fps"], "F10")  # unknown name keeps the default
        self.assertEqual(loaded["hotkey_fsr"], "F9")   # names are case sensitive
        self.assertEqual(len(set(HOTKEY_OPTIONS)), 12)
        self.assertTrue(all(option.startswith("F") for option in HOTKEY_OPTIONS))

    def test_duplicate_hotkeys_are_split_onto_free_keys(self):
        resolved = unique_hotkeys({"hotkey_stop": "F5", "hotkey_fps": "F5", "hotkey_fsr": "F5"})
        self.assertEqual(resolved["hotkey_stop"], "F5")
        self.assertEqual(len(set(resolved.values())), 3)
        self.assertTrue(all(value in HOTKEY_OPTIONS for value in resolved.values()))

    def test_conflicting_hotkeys_can_be_reported_to_the_user(self):
        self.assertEqual(hotkey_conflicts({"hotkey_stop": "F5", "hotkey_fps": "F6", "hotkey_fsr": "F7"}), [])
        conflicts = hotkey_conflicts({"hotkey_stop": "F5", "hotkey_fps": "F6", "hotkey_fsr": "F5"})
        self.assertEqual(set(conflicts), {"hotkey_stop", "hotkey_fsr"})

    def test_show_fps_preference_is_loaded_and_saved(self):
        self.assertTrue(normalize_settings(None)["show_fps"])
        self.assertFalse(normalize_settings({"show_fps": False})["show_fps"])
        self.assertEqual(normalize_settings({"show_fps": "no"})["show_fps"], DEFAULT_SETTINGS["show_fps"])

    def test_new_preferences_survive_a_full_round_trip(self):
        preferences = normalize_settings({"frame_multiplier": 12, "hotkey_stop": "F3",
                                          "hotkey_fps": "F5", "hotkey_fsr": "F7", "show_fps": False})
        self.store.save(preferences)
        self.assertEqual(SettingsStore(self.path).load(), preferences)

    def test_source_identity_never_includes_runtime_handles(self):
        self.assertEqual(source_identity({"hwnd": 99, "title": "Game", "process": "game.exe"}),
                         {"title": "Game", "process": "game.exe"})
        self.assertEqual(source_identity({"source_type": "display", "device": r"\\.\DISPLAY1", "rect": (0, 0, 1920, 1080)}),
                         {"device": r"\\.\DISPLAY1"})
        for source in (None, {"hwnd": 99}, {"title": " ", "process": "game.exe"},
                       {"source_type": "display", "device": ""}):
            with self.subTest(source=source):
                self.assertIsNone(source_identity(source))

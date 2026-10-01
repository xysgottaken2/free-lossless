import unittest
from unittest.mock import MagicMock

from helpers import load_module, stubs


class SelectionUITests(unittest.TestCase):
    def setUp(self):
        self.deps = stubs("tkinter", "tkinter.ttk", "tkinter.messagebox", "selector")
        self.module = load_module("ui", self.deps)
        self.ui = self.module.GameSelectorUI.__new__(self.module.GameSelectorUI)
        self.ui.root = MagicMock()
        self.ui.tree = MagicMock()
        self.ui.tree.get_children.return_value = ["stale-window"]
        self.ui.list_label = MagicMock()
        self.ui.selector = MagicMock()
        self.ui.selected_source = None
        self.ui.source_var = MagicMock()
        settings = {
            "mode": "dxcam", "fps": 90, "scale": "Fullscreen", "algo": "Lanczos",
            "sharp": 20, "fg": True, "engine": "Fast (DIS Flow)", "ultra_smooth": False,
            "perf_mode": False, "low_latency": True,
        }
        for key, value in settings.items():
            variable = MagicMock()
            variable.get.return_value = value
            setattr(self.ui, f"{key}_var", variable)

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

    def test_window_selection_still_keeps_hwnd(self):
        self.ui.source_var.get.return_value = "window"
        self.ui.selector.get_visible_windows.return_value = [{"hwnd": 42, "title": "Game", "process": "game.exe"}]
        self.ui._refresh_list()
        self.ui.tree.selection.return_value = ["0"]
        self.ui._on_select()
        self.assertEqual(self.ui.selected_source["source_type"], "window")
        self.assertEqual(self.ui.selected_source["hwnd"], 42)

    def test_empty_selection_does_not_close_menu(self):
        self.ui.tree.selection.return_value = []
        self.ui._on_select()
        self.assertIsNone(self.ui.selected_source)
        self.ui.root.destroy.assert_not_called()
        self.module.messagebox.showinfo.assert_called_once()

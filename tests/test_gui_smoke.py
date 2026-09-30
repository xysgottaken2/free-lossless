"""Exercise the actual Tk widgets on the Windows build runner (no GPU required)."""
import unittest

from helpers import load_module, stubs

try:
    import tkinter as tk
except ImportError:
    tk = None


@unittest.skipIf(tk is None, "Tk is not installed")
class RealTkSmokeTests(unittest.TestCase):
    def test_source_buttons_refresh_the_real_tree_and_select_a_display(self):
        dependencies = stubs("selector")
        dependencies["selector"].WindowSelector.return_value.get_visible_windows.return_value = [
            {"hwnd": 42, "title": "Game", "process": "game.exe"},
        ]
        dependencies["selector"].DisplaySelector.get_displays.return_value = [
            {"source_type": "display", "device": r"\\.\DISPLAY1", "title": "Display 1 (Monitor principal)",
             "rect": (0, 0, 1920, 1080)},
            {"source_type": "display", "device": r"\\.\DISPLAY2", "title": "Display 2",
             "rect": (-1920, 0, 0, 1080)},
        ]
        module = load_module("ui", dependencies)
        ui = module.GameSelectorUI()
        self.addCleanup(lambda: ui.root.destroy() if ui.selected_source is None else None)
        ui.root.update_idletasks()
        self.assertEqual(ui.tree.item("0", "values"), ("Game", "game.exe"))
        ui.tree.selection_set("0")

        def walk(widget):
            for child in widget.winfo_children():
                yield child
                yield from walk(child)

        display_button = next(widget for widget in walk(ui.root)
                              if isinstance(widget, tk.Radiobutton) and widget.cget("value") == "display")
        display_button.invoke()
        self.assertEqual(ui.source_var.get(), "display")
        self.assertEqual(ui.tree.selection(), ())
        self.assertEqual(len(ui.tree.get_children()), 2)
        self.assertEqual(ui.tree.item("1", "values"), ("Display 2", "1920 x 1080 (-1920, 0)"))
        ui.tree.selection_set("1")
        ui._on_select()
        self.assertEqual(ui.selected_source["source_type"], "display")
        self.assertEqual(ui.selected_source["device"], r"\\.\DISPLAY2")
        self.assertNotIn("hwnd", ui.selected_source)

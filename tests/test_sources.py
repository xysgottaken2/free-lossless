import sys
import unittest
from unittest.mock import patch

import i18n
from helpers import load_module, stubs


class SourceTests(unittest.TestCase):
    def setUp(self):
        # These tests describe the Portuguese (Brazil) build; the catalog is checked below.
        i18n.set_language("pt-BR")
        self.addCleanup(i18n.set_language, "en")
        self.deps = stubs("win32gui", "win32process", "psutil", "win32api")
        self.module = load_module("selector", self.deps)
        self.patch = patch.dict(sys.modules, self.deps)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.api = self.deps["win32api"]
        self.api.EnumDisplayMonitors.return_value = [(2, None, None), (1, None, None)]
        self.monitors = {
            1: {"Device": r"\\.\DISPLAY1", "Flags": 0, "Monitor": (-1920, -200, 0, 880)},
            2: {"Device": r"\\.\DISPLAY2", "Flags": 1, "Monitor": (0, 0, 2560, 1440)},
        }
        self.api.GetMonitorInfo.side_effect = self.monitors.__getitem__

    def test_windows_display_numbers_and_actual_primary(self):
        displays = self.module.DisplaySelector.get_displays()
        self.assertEqual([item["number"] for item in displays], [1, 2])
        self.assertEqual(displays[0]["title"], "Display 1")
        self.assertEqual(displays[1]["title"], "Display 2 (Monitor principal)")
        self.assertEqual(displays[0]["rect"], (-1920, -200, 0, 880))

    def test_display_titles_follow_the_selected_language(self):
        self.assertEqual(self.module.DisplaySelector.get_displays()[1]["title"],
                         "Display 2 (Monitor principal)")
        i18n.set_language("en")
        self.assertEqual(self.module.DisplaySelector.get_displays()[0]["title"], "Display 1")
        i18n.set_language("zh-CN")
        self.assertEqual(self.module.DisplaySelector.get_displays()[1]["title"], "显示器 2（主显示器）")
        i18n.set_language("pt-BR")

    def test_display_source_does_not_require_hwnd(self):
        source = {"source_type": "display", "device": r"\\.\DISPLAY1"}
        self.assertEqual(self.module.get_source_rect(source), (-1920, -200, 0, 880))
        self.deps["win32gui"].GetWindowRect.assert_not_called()
        self.monitors[1]["Monitor"] = (-1280, 0, 0, 720)
        self.assertEqual(self.module.get_source_rect(source), (-1280, 0, 0, 720))
        self.assertEqual(self.module.get_source_monitor_rect(source), (-1280, 0, 0, 720))

    def test_unplugged_display(self):
        with self.assertRaisesRegex(ValueError, "desconectado"):
            self.module.get_source_rect({"source_type": "display", "device": "missing"})

    def test_existing_window_selection_and_fullscreen_monitor(self):
        self.deps["win32gui"].GetWindowRect.return_value = (-1000, 50, -100, 600)
        self.assertEqual(self.module.get_source_rect({"hwnd": 99}), (-1000, 50, -100, 600))
        self.deps["win32gui"].GetWindowRect.assert_called_once_with(99)
        self.api.MonitorFromWindow.return_value = 1
        self.assertEqual(self.module.get_source_monitor_rect({"hwnd": 99}), (-1920, -200, 0, 880))

    def test_no_monitors(self):
        self.api.EnumDisplayMonitors.return_value = []
        self.assertEqual(self.module.DisplaySelector.get_displays(), [])

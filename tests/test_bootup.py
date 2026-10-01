"""The app must show the splash first, then open the menu in the saved language."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import i18n
from helpers import load_module, stubs
from settings import SettingsStore, normalize_settings


class BootupTests(unittest.TestCase):
    def setUp(self):
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "en")
        self.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                          "filters", "win32gui", "win32api", "win32con", "tkinter")
        self.module = load_module("main", self.deps)
        # load_runtime() imports these again later, while the splash is on screen.
        self.patch = patch.dict(sys.modules, self.deps)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = SettingsStore(Path(self.directory.name) / "settings.json")
        self.events = []

        def splash(loader):
            self.events.append(("splash", None))
            loader()  # the real runner blocks until the loader finishes
            self.events.append(("loaded", self.module.runtime_loaded()))
            return 0.1

        self.module.run_splash = splash
        self.module.SettingsStore = lambda: self.store

        class FakeApp:
            def __init__(self, target_fps=60):
                self.events_source = None

            def run(self):
                self.__class__.last = self
                return False  # leave the menu loop after one selection round

        self.app_class = FakeApp
        self.module.FrameGenerationApp = FakeApp

    def test_splash_runs_before_the_overlay_modules_are_needed(self):
        self.module.main()
        kinds = [event[0] for event in self.events]
        self.assertEqual(kinds, ["splash", "loaded"])
        # The menu and the overlay are only usable once the runtime finished loading.
        self.assertTrue(self.events[1][1])

    def test_saved_language_is_applied_before_the_splash_is_drawn(self):
        self.store.save({**normalize_settings(None), "language": "pt-BR"})
        self.module.main()
        self.assertEqual(i18n.get_language(), "pt-BR")

    def test_first_launch_starts_in_english(self):
        self.module.main()
        self.assertEqual(i18n.get_language(), "en")

    def test_broken_preferences_never_block_startup(self):
        self.module.SettingsStore = MagicMock(side_effect=OSError("read-only"))
        self.module.main()
        self.assertEqual(i18n.get_language(), "en")
        self.assertTrue(self.module.runtime_loaded())

    def test_the_loop_keeps_the_menu_open_until_the_user_exits(self):
        runs = []

        class LoopApp:
            def __init__(self, target_fps=60):
                pass

            def run(self):
                runs.append(True)
                return len(runs) < 3

        self.module.FrameGenerationApp = LoopApp
        self.module.main()
        self.assertEqual(len(runs), 3)


if __name__ == "__main__":
    unittest.main()

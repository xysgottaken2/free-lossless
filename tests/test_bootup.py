"""The app must show the splash first, then open the menu in the saved language."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import diagnostics
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


class StartupFailureTests(unittest.TestCase):
    """A heavy import that Windows refuses must not end in a silent, unexplained exit."""

    def setUp(self):
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "en")
        self.deps = stubs("cv2", "numpy", "pygame", "capture", "engine", "ui", "selector",
                          "filters", "win32gui", "win32api", "win32con", "tkinter")
        self.module = load_module("main", self.deps)
        self.patch = patch.dict(sys.modules, self.deps)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        # No waiting between attempts in the suite, and no dialog on a headless box.
        self.module.STARTUP_RETRY_SECONDS = 0
        self.module.ctypes = MagicMock()
        # diagnostics is a real, shared module: the originals are restored by hand so a
        # leftover lambda cannot swallow the messages of the tests that run after this.
        self.messages = []
        original_write_now, original_write = diagnostics.write_now, diagnostics.write
        self.addCleanup(setattr, diagnostics, "write", original_write)
        self.addCleanup(setattr, diagnostics, "write_now", original_write_now)
        diagnostics.write_now = lambda label, message: self.messages.append(str(message))
        diagnostics.write = lambda message: self.messages.append(str(message))

    def commit_error(self, module="cv2"):
        error = ImportError(f"DLL load failed while importing {module}: "
                            f"O arquivo de paginação é muito pequeno para que esta operação "
                            f"seja concluída.")
        error.name = module
        return error

    def test_a_transient_failure_is_retried_and_the_app_starts(self):
        attempts = []
        real = self.module._import_runtime

        def flaky():
            attempts.append(True)
            if len(attempts) == 1:
                raise self.commit_error()
            real()

        self.module._import_runtime = flaky
        self.module.load_runtime()
        self.assertEqual(len(attempts), 2)
        self.assertTrue(self.module.runtime_loaded())
        self.assertTrue(any("tentativa 1/3" in message for message in self.messages))
        self.assertTrue(any("carregado na tentativa 2" in message for message in self.messages))

    def test_a_permanent_failure_keeps_the_module_name_and_the_reason(self):
        self.module._import_runtime = lambda: (_ for _ in ()).throw(self.commit_error("cv2"))
        with self.assertRaises(self.module.RuntimeLoadError) as caught:
            self.module.load_runtime()
        self.assertEqual(caught.exception.module_name, "cv2")
        self.assertIn("paginação", str(caught.exception.error))
        self.assertIsInstance(caught.exception.__cause__, ImportError)

    def test_the_module_name_is_read_from_the_message_when_the_error_has_none(self):
        error = ImportError("DLL load failed while importing win32gui: erro 1455")
        self.assertEqual(self.module._failing_module(error), "win32gui")

    def test_the_failure_is_explained_in_the_dialog_and_written_to_the_log(self):
        error = self.module.RuntimeLoadError("cv2", self.commit_error())
        body = self.module.report_startup_failure(error, "Traceback (most recent call last): ...")
        dialog = self.module.ctypes.windll.user32.MessageBoxW
        self.assertTrue(dialog.called)
        self.assertEqual(dialog.call_args.args[1], body)
        self.assertIn("cv2", body)
        self.assertIn("paging file", body)          # what the user has to change
        self.assertIn("overlay.log", body)          # where the traceback went
        self.assertTrue(any("inicialização falhou ao carregar cv2" in m for m in self.messages))
        self.assertTrue(any("Traceback" in m for m in self.messages))

    def test_the_language_of_the_saved_preferences_is_used(self):
        i18n.set_language("pt-BR")
        error = self.module.RuntimeLoadError("cv2", self.commit_error())
        body = self.module.report_startup_failure(error, "")
        self.assertIn("não conseguiu carregar cv2", body)
        self.assertIn("arquivo de paginação", body)

    def test_main_reports_a_failed_load_instead_of_raising(self):
        self.module.run_splash = lambda loader: (_ for _ in ()).throw(self.commit_error())
        self.module.FrameGenerationApp = MagicMock()
        reported = []
        self.module.report_startup_failure = lambda error, text: reported.append((error, text))
        self.assertEqual(self.module.main(), 1)
        self.assertEqual(len(reported), 1)
        self.assertIsInstance(reported[0][0], ImportError)
        self.assertFalse(self.module.FrameGenerationApp.called)

    def test_an_unexpected_error_is_reported_and_logged(self):
        error = RuntimeError("pygame não inicializou")
        body = self.module.report_crash(error, "Traceback (most recent call last): boom")
        dialog = self.module.ctypes.windll.user32.MessageBoxW
        self.assertEqual(dialog.call_args.args[1], body)
        self.assertIn("pygame não inicializou", body)
        self.assertIn("overlay.log", body)
        self.assertTrue(any("erro inesperado: pygame não inicializou" in m for m in self.messages))
        self.assertTrue(any("boom" in m for m in self.messages))

    def test_main_reports_an_unexpected_error_instead_of_vanishing(self):
        class Exploding:
            def __init__(self, target_fps=60):
                raise RuntimeError("sem memória para as filas")

        self.module.run_splash = lambda loader: None
        self.module.FrameGenerationApp = Exploding
        reported = []
        self.module.report_crash = lambda error, text: reported.append(str(error))
        self.assertEqual(self.module.main(), 1)
        self.assertEqual(reported, ["sem memória para as filas"])

    def test_a_broken_dialog_does_not_hide_the_failure(self):
        self.module.ctypes.windll.user32.MessageBoxW.side_effect = OSError("sem desktop")
        body = self.module.report_startup_failure(self.module.RuntimeLoadError("cv2", self.commit_error()))
        self.assertIn("cv2", body)                  # still returned, so the caller can log it


class MemoryReportTests(unittest.TestCase):
    """The numbers that make a Windows commit failure diagnosable from the log."""

    def setUp(self):
        self.module = load_module("main", stubs("cv2", "numpy", "pygame", "capture", "engine",
                                                "ui", "selector", "filters", "win32gui",
                                                "win32api", "win32con", "tkinter"))

    def fake_psutil(self, total=8 * 2**30, available=3 * 2**30, page_total=4 * 2**30, page_used=1 * 2**30):
        memory = MagicMock(total=total, available=available)
        page = MagicMock(total=page_total, used=page_used)
        return MagicMock(virtual_memory=MagicMock(return_value=memory),
                         swap_memory=MagicMock(return_value=page))

    def test_it_reports_ram_and_the_pagefile(self):
        with patch.dict(sys.modules, {"psutil": self.fake_psutil()}):
            report = self.module.startup_memory_report()
        self.assertIn("3.0 GB livres de 8.0 GB", report)
        self.assertIn("arquivo de paginação 1.0 GB de 4.0 GB", report)

    def test_a_missing_psutil_does_not_break_the_report(self):
        with patch.dict(sys.modules, {"psutil": None}):
            report = self.module.startup_memory_report()
        self.assertIn("memória", report)


if __name__ == "__main__":
    unittest.main()

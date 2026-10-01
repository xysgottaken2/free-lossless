import threading
import time
import unittest

import i18n
from splash import SplashWindow, run_splash


class FakeSplash:
    def __init__(self):
        self.updates = 0
        self.closed = False

    def update(self):
        self.updates += 1

    def close(self):
        self.closed = True


class FakeClock:
    """Monotonic clock that only moves when the splash asks for the time."""

    def __init__(self, step=0.01):
        self.now = 0.0
        self.step = step

    def __call__(self):
        self.now += self.step
        return self.now


class SplashRunnerTests(unittest.TestCase):
    def test_splash_stays_until_the_loader_finishes(self):
        splash = FakeSplash()
        started = threading.Event()

        def loader():
            started.set()
            time.sleep(0.05)

        elapsed = run_splash(loader, factory=lambda: splash, minimum_seconds=0.1,
                             clock=FakeClock(), poll_seconds=0.001)
        self.assertTrue(started.is_set())
        self.assertGreater(splash.updates, 0)
        self.assertTrue(splash.closed)
        self.assertGreaterEqual(elapsed, 0.1)

    def test_splash_closes_and_reraises_when_loading_fails(self):
        splash = FakeSplash()

        def loader():
            raise ImportError("pygame missing")

        with self.assertRaises(ImportError):
            run_splash(loader, factory=lambda: splash, minimum_seconds=0,
                       clock=FakeClock(), poll_seconds=0.001)
        self.assertTrue(splash.closed)

    def test_a_missing_display_never_blocks_startup(self):
        state = []

        def factory():
            raise RuntimeError("no display")

        run_splash(lambda: state.append(True), factory=factory, minimum_seconds=10,
                   clock=FakeClock(), poll_seconds=0.001)
        self.assertEqual(state, [True])

    def test_the_menu_opens_only_after_the_minimum_time(self):
        splash = FakeSplash()
        finished = []
        run_splash(lambda: finished.append(i18n.get_language()), factory=lambda: splash,
                   minimum_seconds=0.2, clock=FakeClock(), poll_seconds=0.001)
        self.assertEqual(finished, ["en"])


class SplashWindowTests(unittest.TestCase):
    """The splash itself needs a real display; skip where Tk cannot open one."""

    def make_splash(self, language="pt-BR"):
        try:
            splash = SplashWindow(language=language, minimum_seconds=0)
        except Exception as exc:  # no Tk, or a headless Linux session without Xvfb
            self.skipTest(f"splash unavailable: {exc}")
        self.addCleanup(splash.close)
        return splash

    def test_splash_shows_the_logo_name_and_tagline_in_the_app_colours(self):
        splash = self.make_splash()
        splash.update()
        self.assertEqual(splash.root.title(), "Free Lossless")
        self.assertEqual(splash.title_label.cget("text"), "Free Lossless")
        self.assertEqual(splash.subtitle_label.cget("text"), "Mais fluidez. Sem modificar seu jogo.")
        self.assertEqual(splash.root.cget("bg"), "#0C111B")
        self.assertTrue(splash.root.overrideredirect())
        self.assertGreater(splash.bar.winfo_width(), 0)

    def test_splash_uses_the_saved_language(self):
        splash = self.make_splash(language="zh-CN")
        splash.update()
        self.assertEqual(splash.subtitle_label.cget("text"), "更流畅，无需修改游戏。")

    def test_closing_the_splash_twice_is_harmless(self):
        splash = self.make_splash()
        splash.update()
        splash.close()
        splash.close()
        self.assertTrue(splash._closed)


if __name__ == "__main__":
    unittest.main()

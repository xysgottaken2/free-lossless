"""Startup splash: shows instantly while the heavy modules are imported."""
import threading
import time

try:  # Tk is missing on headless Linux; the runner below still works without it.
    import tkinter as tk
except ImportError:  # pragma: no cover - exercised only without Tk
    tk = None

import i18n
from theme import COLORS, draw_logo

SPLASH_WIDTH = 460
SPLASH_HEIGHT = 232
MINIMUM_SECONDS = 2.4
SLOW_HINT_SECONDS = 6.0
POLL_SECONDS = 0.02
BAR_HEIGHT = 4


class SplashWindow:
    """Borderless, always-on-top window in the app's background color."""

    def __init__(self, language=None, minimum_seconds=MINIMUM_SECONDS):
        if tk is None:
            raise RuntimeError("Tk is not available")
        self.language = i18n.normalize_language(language or i18n.get_language())
        self.minimum_seconds = minimum_seconds
        self._t = lambda key, **fields: i18n.translate(key, self.language, **fields)
        self._closed = False
        self._started = time.monotonic()
        self._offset = 0.0

        self.root = tk.Tk()
        self.root.title(self._t("app.title"))
        self.root.configure(bg=COLORS["background"])
        self.root.overrideredirect(True)
        try:
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass
        width, height = SPLASH_WIDTH, SPLASH_HEIGHT
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self._build(width, height)
        self.update()

    def _build(self, width, height):
        outer = tk.Frame(self.root, bg=COLORS["background"],
                         highlightbackground=COLORS["border"], highlightthickness=1)
        outer.pack(fill=tk.BOTH, expand=True)
        logo = tk.Canvas(outer, width=64, height=64, bg=COLORS["background"], highlightthickness=0)
        logo.pack(pady=(30, 12))
        draw_logo(logo, 10, 10, 44)
        self.title_label = tk.Label(outer, text=self._t("app.title"), bg=COLORS["background"],
                                   fg=COLORS["text"], font=("Segoe UI", 20, "bold"))
        self.title_label.pack()
        self.subtitle_label = tk.Label(outer, text=self._t("app.subtitle"), bg=COLORS["background"],
                                       fg=COLORS["muted"], font=("Segoe UI", 10))
        self.subtitle_label.pack(pady=(6, 16))
        self.bar = tk.Canvas(outer, width=width - 90, height=BAR_HEIGHT, bg=COLORS["input"],
                             highlightthickness=0)
        self.bar.pack()
        self.status = tk.Label(outer, text=self._t("splash.loading"), bg=COLORS["background"],
                               fg=COLORS["muted"], font=("Segoe UI", 9))
        self.status.pack(pady=(10, 0))

    def update(self):
        """Pump the event loop and animate the progress bar."""
        if self._closed:
            return
        try:
            self._animate()
            self.root.update()
        except tk.TclError:
            self._closed = True

    def _animate(self):
        elapsed = time.monotonic() - self._started
        width = max(1, self.bar.winfo_width())
        segment = width * 0.32
        travel = max(1.0, width - segment)
        # Ping-pong so the bar keeps giving feedback without pretending to know progress.
        phase = (self._offset % 2.0)
        position = (phase if phase <= 1.0 else 2.0 - phase) * travel
        self.bar.delete("segment")
        self.bar.create_rectangle(position, 0, position + segment, BAR_HEIGHT,
                                  fill=COLORS["accent"], width=0, tags="segment")
        self._offset = (self._offset + 0.045) % 2.0
        if elapsed >= SLOW_HINT_SECONDS and self.status.cget("text") != self._t("splash.slow"):
            self.status.config(text=self._t("splash.slow"))

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def run_splash(loader, factory=None, minimum_seconds=MINIMUM_SECONDS, clock=time.monotonic,
               poll_seconds=POLL_SECONDS, on_event=None):
    """Show the splash while ``loader`` runs; always closes it before returning.

    ``loader`` runs in a background thread so the window keeps animating no matter how
    long the imports take. Errors are re-raised after the splash is closed.
    """
    make_splash = factory or (lambda: SplashWindow(minimum_seconds=minimum_seconds))
    splash = None
    try:
        splash = make_splash()
    except Exception as exc:  # a missing display must never block the app
        print(f"Splash unavailable: {exc}")
    errors = []

    def run_loader():
        try:
            loader()
        except BaseException as exc:  # re-raised in the main thread below
            errors.append(exc)

    thread = threading.Thread(target=run_loader, daemon=True)
    thread.start()
    started = clock()
    if splash is not None:
        while True:
            splash.update()
            if on_event is not None:
                on_event()
            elapsed = clock() - started
            if not thread.is_alive() and elapsed >= minimum_seconds:
                break
            time.sleep(poll_seconds)
        splash.close()
    else:
        thread.join()
    if errors:
        raise errors[0]
    return clock() - started

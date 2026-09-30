"""Capture targets: Window vs Full Screen, monitor enumeration.

Pure logic (stdlib only) so it is unit-testable on any machine; the Windows
monitor enumeration degrades gracefully when Win32 is unavailable (CI/linux):

* ``SOURCE_WINDOW``    - capture one application window (existing behaviour)
* ``SOURCE_FULLSCREEN``- capture a whole monitor (the desktop as displayed),
  regardless of which application is in the foreground.

The capture backends are reused unchanged:

* ``dxcam``   -> grabs a DXGI output (``output_idx`` = monitor index); in
  Full Screen mode the whole output is grabbed (``region=None``).
* ``bitblt``  -> grabs a region of the desktop DC in screen coordinates
  (the window rect, or the monitor rect).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence, Tuple

Rect = Tuple[int, int, int, int]  # (left, top, right, bottom) in screen coords

SOURCE_WINDOW = "window"
SOURCE_FULLSCREEN = "fullscreen"
SOURCE_VALUES = (SOURCE_WINDOW, SOURCE_FULLSCREEN)

BACKEND_DXCAM = "dxcam"
BACKEND_BITBLT = "bitblt"
BACKEND_VALUES = (BACKEND_DXCAM, BACKEND_BITBLT)

# Friendly labels used by the UI combo boxes.
SOURCE_LABELS = {SOURCE_WINDOW: "Window", SOURCE_FULLSCREEN: "Full Screen"}
BACKEND_LABELS = {BACKEND_DXCAM: "dxcam", BACKEND_BITBLT: "bitblt"}

_SOURCE_ALIASES = {
    "window": SOURCE_WINDOW,
    "win": SOURCE_WINDOW,
    "janela": SOURCE_WINDOW,
    "fullscreen": SOURCE_FULLSCREEN,
    "full screen": SOURCE_FULLSCREEN,
    "full_screen": SOURCE_FULLSCREEN,
    "screen": SOURCE_FULLSCREEN,
    "desktop": SOURCE_FULLSCREEN,
    "tela": SOURCE_FULLSCREEN,
    "tela inteira": SOURCE_FULLSCREEN,
}

_BACKEND_ALIASES = {
    "dxcam": BACKEND_DXCAM,
    "bitblt": BACKEND_BITBLT,
    "gdi": BACKEND_BITBLT,
}


def normalize_source(value) -> str:
    """Map user/config spellings to a canonical source id."""
    key = str(value or "").strip().lower()
    return _SOURCE_ALIASES.get(key, SOURCE_WINDOW)


def normalize_backend(value) -> str:
    key = str(value or "").strip().lower()
    return _BACKEND_ALIASES.get(key, BACKEND_DXCAM)


def source_label(source: str) -> str:
    return SOURCE_LABELS.get(normalize_source(source), str(source))


@dataclass
class MonitorInfo:
    index: int
    rect: Rect
    primary: bool = False
    name: str = ""

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]

    @property
    def label(self) -> str:
        name = self.name or f"Display {self.index + 1}"
        return f"{name} (Primary)" if self.primary else name


@dataclass
class CaptureTarget:
    """Everything the capture/overlay code needs to know about the source."""

    source: str
    rect: Rect
    output_idx: int = 0
    full_output: bool = False
    label: str = ""

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]


def _primary_monitor_fallback() -> List[MonitorInfo]:
    """One primary monitor using GetSystemMetrics when available."""
    width, height = 1920, 1080
    if sys.platform.startswith("win"):
        try:
            import win32api
            import win32con

            width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
            height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        except Exception:
            pass
    return [MonitorInfo(index=0, rect=(0, 0, width, height), primary=True, name="Display 1")]


def list_monitors() -> List[MonitorInfo]:
    """Enumerate monitors.

    Primary monitor first. On non-Windows platforms (or on any failure) a
    single synthetic primary monitor is returned so callers never crash.
    """
    if not sys.platform.startswith("win"):
        return _primary_monitor_fallback()
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        rects: List[Rect] = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HMONITOR,
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            wintypes.LPARAM,
        )

        def _callback(_hmon, _hdc, lprect, _lparam):
            r = lprect.contents
            rects.append((int(r.left), int(r.top), int(r.right), int(r.bottom)))
            return True

        user32.EnumDisplayMonitors(None, None, callback_type(_callback), 0)
        if not rects:
            return _primary_monitor_fallback()

        monitors = []
        for i, rect in enumerate(rects):
            primary = rect[0] <= 0 <= rect[2] and rect[1] <= 0 <= rect[3]
            monitors.append(MonitorInfo(index=i, rect=rect, primary=primary, name=f"Display {i + 1}"))
        # Primary first, stable order otherwise.
        monitors.sort(key=lambda m: (not m.primary, m.index))
        for i, monitor in enumerate(monitors):
            monitor.index = i
        return monitors
    except Exception:
        return _primary_monitor_fallback()


def resolve_capture_target(
    selection: dict,
    monitors: Optional[Sequence[MonitorInfo]] = None,
    window_rect_getter: Optional[Callable[[int], Rect]] = None,
) -> CaptureTarget:
    """Turn a UI selection dict into a :class:`CaptureTarget`.

    * ``source == window``     -> rect comes from ``window_rect_getter(hwnd)``.
    * ``source == fullscreen`` -> rect is the selected monitor (default 0 =
      primary); a bad/missing monitor index falls back to the primary.
    """
    source = normalize_source(selection.get("source", SOURCE_WINDOW))

    if source == SOURCE_WINDOW:
        if "hwnd" not in selection:
            raise ValueError("window source requires a selected window (hwnd)")
        if window_rect_getter is None:
            raise ValueError("window source requires a window_rect_getter")
        rect = tuple(window_rect_getter(selection["hwnd"]))
        return CaptureTarget(
            source=SOURCE_WINDOW,
            rect=rect,
            output_idx=0,
            full_output=False,
            label=str(selection.get("title") or "Window"),
        )

    monitor_list = list(monitors) if monitors is not None else list_monitors()
    if not monitor_list:
        monitor_list = _primary_monitor_fallback()
    try:
        index = int(selection.get("monitor", 0))
    except (TypeError, ValueError):
        index = 0
    if index < 0 or index >= len(monitor_list):
        index = 0
    monitor = monitor_list[index]
    return CaptureTarget(
        source=SOURCE_FULLSCREEN,
        rect=monitor.rect,
        output_idx=monitor.index,
        full_output=True,
        label=f"Full Screen ({monitor.label})",
    )


def capture_params_for(target: CaptureTarget, backend: str) -> dict:
    """Keyword arguments for ``ScreenCapture`` for this target/backend.

    Reuses the existing capture infrastructure: dxcam grabs a full DXGI
    output in Full Screen mode (monitor index via ``output_idx``) and a
    desktop-coordinate region in Window mode; bitblt always uses a
    screen-coordinate region.
    """
    backend = normalize_backend(backend)
    if backend == BACKEND_DXCAM:
        return {
            "region": None if target.full_output else target.rect,
            "output_idx": target.output_idx,
        }
    return {"region": target.rect, "output_idx": None}

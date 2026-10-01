"""Append-only log for the overlay, so a frozen build can still be diagnosed.

The Windows executable runs windowed (``--noconsole``), where ``print`` output is
lost. Every stage of the pipeline writes a line here at most a few times per
second, next to the preferences file.
"""
import os
import threading
import time
from pathlib import Path

from settings import get_settings_path

LOG_NAME = "overlay.log"
MAX_BYTES = 512 * 1024
# Tests and source runs can silence the file with FREE_LOSSLESS_LOG=0.
ENABLED = os.environ.get("FREE_LOSSLESS_LOG", "1") != "0"
_lock = threading.Lock()


def log_path():
    return Path(get_settings_path()).parent / LOG_NAME


def reset():
    """Start a fresh log for this overlay session."""
    if not ENABLED:
        return
    with _lock:
        try:
            path = log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"Free Lossless overlay log — {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
                            encoding="utf-8")
        except OSError:
            pass


def write(message):
    """Append one timestamped line; never raise, never block the pipeline."""
    if not ENABLED:
        return
    stamp = time.strftime("%H:%M:%S")
    with _lock:
        try:
            path = log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size > MAX_BYTES:
                path.write_text("", encoding="utf-8")
            with path.open("a", encoding="utf-8") as stream:
                stream.write(f"[{stamp}] {message}\n")
        except OSError:
            pass


def write_now(label, message):
    """Log a line prefixed with the stage that produced it."""
    write(f"{label}: {message}")

"""Best-effort GPU / driver queries (Windows), never fatal.

Used for the UI status lines:

    GPU: RTX 2060
    Driver: 32.0.15.6614

On non-Windows platforms (CI) everything degrades to ``"unknown"`` without
importing win32 modules.
"""

from __future__ import annotations

import re
import sys


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def query_gpu_name() -> str:
    """Primary display adapter name via ``EnumDisplayDevices``."""
    if not _is_windows():
        return "unknown"
    try:
        import win32api  # noqa: deferred import (Windows only)

        info = win32api.EnumDisplayDevices(None, 0)
        if info and getattr(info, "DeviceString", None):
            return info.DeviceString
    except Exception:
        pass
    return "unknown"


def query_display_driver_version() -> str:
    """Driver version from the display class registry key."""
    if not _is_windows():
        return "unknown"
    try:
        import winreg

        class_path = (
            r"SYSTEM\CurrentControlSet\Control\Class"
            r"\{4d36e968-3d45-11d2-9d05-0000f8004795}"
        )
        best = None
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, class_path) as base:
            index = 0
            while index < 64:
                try:
                    sub_name = winreg.EnumKey(base, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(base, sub_name) as sub:
                        desc, _ = winreg.QueryValueEx(sub, "DriverDesc")
                        version, _ = winreg.QueryValueEx(sub, "DriverVersion")
                except OSError:
                    continue
                if desc and "nvidia" in str(desc).lower():
                    best = str(version)
                    break
                if best is None and version:
                    best = str(version)
        return best or "unknown"
    except Exception:
        return "unknown"


def looks_like_nvidia_gpu(gpu_name: str) -> bool:
    return bool(re.search(r"nvidia|geforce|rtx|gtx|quadro|tesla", gpu_name or "", re.I))

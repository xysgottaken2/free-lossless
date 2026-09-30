"""Locate and describe the external NVIDIA DLSS 5 runtime files.

Distribution policy (also documented in ``native/README.txt``):

* This project NEVER ships, downloads or commits NVIDIA runtime binaries.
* The user places ``nvngx_dlssnr.dll`` (and optionally ``nvngx.dll``) into the
  ``native/`` folder next to the executable.
* The loader only *inspects* those files (existence, PE version resource).  The
  actual dynamic loading happens inside the native bridge
  (``native/freelossless-nvngx.dll``).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

# File names we expect in ``native/``.
DLSSNR_DLL = "nvngx_dlssnr.dll"
NGX_CORE_CANDIDATES = ("_nvngx.dll", "nvngx.dll")
BRIDGE_DLL = "freelossless-nvngx.dll"


@dataclass
class RuntimeFile:
    name: str
    path: str
    present: bool
    version: str = "unknown"
    size_bytes: int = 0


@dataclass
class RuntimeReport:
    native_dir: str
    dlssnr: RuntimeFile
    core: Optional[RuntimeFile] = None
    bridge: Optional[RuntimeFile] = None
    notes: List[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.dlssnr.present

    def describe(self) -> str:
        if not self.dlssnr.present:
            return "Not Found"
        return f"Found ({self.dlssnr.version})"


def pe_file_version(path: str) -> str:
    """Read the ``FileVersion`` string from a PE resources (Windows only)."""
    if not sys.platform.startswith("win"):
        return "unknown"
    try:
        import ctypes

        version = ctypes.WinDLL("version.dll")
        get_size = version.GetFileVersionInfoSizeW
        get_size.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
        get_info = version.GetFileVersionInfoW
        get_query = version.VerQueryValueW

        dummy = ctypes.c_uint32(0)
        size = get_size(path, ctypes.byref(dummy))
        if not size:
            return "unknown"
        buffer = ctypes.create_string_buffer(size)
        if not get_info(path, 0, size, buffer):
            return "unknown"

        class VS_FIXEDFILEINFO(ctypes.Structure):
            _fields_ = [
                ("dwSignature", ctypes.c_uint32),
                ("dwStrucVersion", ctypes.c_uint32),
                ("dwFileVersionMS", ctypes.c_uint32),
                ("dwFileVersionLS", ctypes.c_uint32),
                ("dwProductVersionMS", ctypes.c_uint32),
                ("dwProductVersionLS", ctypes.c_uint32),
                ("dwFileFlagsMask", ctypes.c_uint32),
                ("dwFileFlags", ctypes.c_uint32),
                ("dwFileOS", ctypes.c_uint32),
                ("dwFileType", ctypes.c_uint32),
                ("dwFileSubtype", ctypes.c_uint32),
                ("dwFileDateMS", ctypes.c_uint32),
                ("dwFileDateLS", ctypes.c_uint32),
            ]

        pointer = ctypes.c_void_p()
        length = ctypes.c_uint32()
        if not get_query(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)):
            return "unknown"
        info = ctypes.cast(pointer, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
        ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:
        return "unknown"


def _probe(path: str, name: str) -> RuntimeFile:
    present = os.path.isfile(path)
    size = os.path.getsize(path) if present else 0
    version = pe_file_version(path) if present else "unknown"
    return RuntimeFile(name=name, path=path, present=present, version=version, size_bytes=size)


class RuntimeLocator:
    """Inspects ``native/`` for the DLSS 5 runtime files."""

    def __init__(self, native_dir: Optional[str] = None):
        self.native_dir = native_dir or default_native_dir()

    def report(self) -> RuntimeReport:
        native = self.native_dir
        rep = RuntimeReport(
            native_dir=native,
            dlssnr=_probe(os.path.join(native, DLSSNR_DLL), DLSSNR_DLL),
        )
        for candidate in NGX_CORE_CANDIDATES:
            core = _probe(os.path.join(native, candidate), candidate)
            if core.present:
                rep.core = core
                break
        bridge = _probe(os.path.join(native, BRIDGE_DLL), BRIDGE_DLL)
        rep.bridge = bridge if bridge.present else None

        if not rep.dlssnr.present:
            rep.notes.append(
                f"{DLSSNR_DLL} not found in {os.path.basename(native) or native} - "
                "DLSS 5 Neural Rendering unavailable (this is fine; RIFE keeps working)"
            )
        if rep.dlssnr.present and rep.dlssnr.size_bytes < 10 * 1024 * 1024:
            rep.notes.append(
                f"{DLSSNR_DLL} is suspiciously small ({rep.dlssnr.size_bytes} bytes); "
                "the genuine runtime is ~150 MB"
            )
        return rep


def default_native_dir() -> str:
    """``<app dir>/native`` (portable layout next to the executable)."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "native")

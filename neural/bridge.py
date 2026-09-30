"""ctypes wrapper around the native DLSS 5 bridge (``native/freelossless-nvngx.dll``).

The bridge is our own code (see ``native/src/``).  It owns a private D3D12
device, loads the driver NGX core plus the user-supplied ``nvngx_dlssnr.dll``
and drives NGX feature 18 (DLSS 5 Neural Rendering).  This module only defines
the C ABI and validates inputs; all NVIDIA loading happens inside the bridge.

The C ABI (``native/src/flnr_api.h``) is deliberately tiny:

    flnr_init()      - probe + create the feature (never raises on failure)
    flnr_process()   - one RGB8 frame in, one RGB8 frame out
    flnr_get_status()- struct with runtime/GPU/counter information
    flnr_shutdown()  - release everything
"""

from __future__ import annotations

import ctypes
import os
import sys
from typing import Optional, Tuple

import numpy as np

# --- error codes (mirror of flnr_api.h) -------------------------------------
FLNR_OK = 0
FLNR_ERR_GENERIC = -1
FLNR_ERR_NO_D3D12 = -2
FLNR_ERR_NO_NVIDIA_GPU = -3
FLNR_ERR_CORE_LOAD = -4
FLNR_ERR_CORE_INIT = -5
FLNR_ERR_RUNTIME_LOAD = -6
FLNR_ERR_RUNTIME_INIT = -7
FLNR_ERR_FEATURE = -8
FLNR_ERR_BAD_ARG = -9
FLNR_ERR_GPU = -10

_ERROR_NAMES = {
    FLNR_ERR_GENERIC: "generic bridge error",
    FLNR_ERR_NO_D3D12: "D3D12 is not available on this system",
    FLNR_ERR_NO_NVIDIA_GPU: "no NVIDIA D3D12 adapter found",
    FLNR_ERR_CORE_LOAD: "NVIDIA NGX core (nvngx.dll) could not be loaded - install/update the NVIDIA driver",
    FLNR_ERR_CORE_INIT: "NGX core initialization failed",
    FLNR_ERR_RUNTIME_LOAD: "nvngx_dlssnr.dll could not be loaded (missing dependencies or blocked)",
    FLNR_ERR_RUNTIME_INIT: "nvngx_dlssnr.dll initialization failed (Init_Ext)",
    FLNR_ERR_FEATURE: "NGX CreateFeature(18) failed (Neural Rendering)",
    FLNR_ERR_BAD_ARG: "invalid argument",
    FLNR_ERR_GPU: "GPU command submission/readback failed",
}


def error_name(code: int) -> str:
    return _ERROR_NAMES.get(code, f"bridge error {code}")


# Known NVSDK_NGX result codes -> explanation (values from public nvsdk_ngx_defs.h)
NGX_RESULT_HELP = {
    0x00000001: "Success",
    0xBAD00000: "FAIL_Fail",
    0xBAD00001: "FAIL_FeatureNotSupported (architecture check: stock runtime on a pre-Blackwell GPU)",
    0xBAD00002: "FAIL_PlatformError (snippet not driven through the NGX core, module-name gate, or driver rejected an unsigned/modified runtime)",
    0xBAD00004: "FAIL_FeatureNotFound",
    0xBAD00005: "FAIL_InvalidParameter",
    0xBAD0000B: "FAIL_UnableToInitializeFeature",
    0xBAD0000C: "FAIL_OutOfDate",
    0xBAD0000E: "FAIL_NotInitialized",
}


def ngx_result_help(code: int) -> str:
    return NGX_RESULT_HELP.get(code & 0xFFFFFFFF, f"NGX result 0x{code & 0xFFFFFFFF:08X}")


# --- ABI structs -------------------------------------------------------------
class FlNrOptions(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("work_width", ctypes.c_int32),
        ("work_height", ctypes.c_int32),
        ("passes", ctypes.c_uint32),
        ("preset", ctypes.c_uint32),
        ("style", ctypes.c_uint32),
        ("intensity", ctypes.c_float),
        ("local_tone", ctypes.c_float),
        ("local_structure", ctypes.c_float),
        ("skin_structure", ctypes.c_float),
        ("exposure", ctypes.c_float),
        ("auto_mask", ctypes.c_uint32),
        ("temporal", ctypes.c_uint32),
    ]


class FlNrStatus(ctypes.Structure):
    _fields_ = [
        ("initialized", ctypes.c_int32),
        ("last_error", ctypes.c_int32),
        ("last_ngx_result", ctypes.c_uint32),
        ("frames_ok", ctypes.c_uint64),
        ("frames_failed", ctypes.c_uint64),
        ("passes_active", ctypes.c_uint32),
        ("width", ctypes.c_int32),
        ("height", ctypes.c_int32),
        ("work_width", ctypes.c_int32),
        ("work_height", ctypes.c_int32),
        ("gpu", ctypes.c_wchar * 128),
        ("runtime_version", ctypes.c_wchar * 64),
        ("core_path", ctypes.c_wchar * 260),
        ("runtime_path", ctypes.c_wchar * 260),
        ("backend", ctypes.c_char * 32),
    ]


class BridgeError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class NativeBridge:
    """Loaded ``freelossless-nvngx.dll`` with bound C functions."""

    _MAX_ERR = 1024

    def __init__(self, dll_path: str):
        if not sys.platform.startswith("win"):
            raise BridgeError(FLNR_ERR_GENERIC, "the DLSS 5 bridge requires Windows")
        if not os.path.isfile(dll_path):
            raise BridgeError(FLNR_ERR_RUNTIME_LOAD, f"bridge DLL not found: {dll_path}")
        try:
            loader = getattr(ctypes, "WinDLL", None) or ctypes.CDLL
            self._dll = loader(dll_path)
        except OSError as exc:
            raise BridgeError(FLNR_ERR_RUNTIME_LOAD, f"bridge DLL failed to load: {exc}") from exc
        self.path = dll_path
        self._bind()

    def _bind(self) -> None:
        dll = self._dll
        try:
            self._init = dll.flnr_init
            self._process = dll.flnr_process
            self._get_status = dll.flnr_get_status
            self._shutdown = dll.flnr_shutdown
        except AttributeError as exc:
            raise BridgeError(FLNR_ERR_GENERIC, f"bridge exports missing: {exc}") from exc

        self._init.argtypes = [
            ctypes.POINTER(FlNrOptions),
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.POINTER(FlNrStatus),
            ctypes.c_char_p,
            ctypes.c_int32,
        ]
        self._init.restype = ctypes.c_int32
        self._process.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int32,
            ctypes.c_void_p,
            ctypes.c_int32,
            ctypes.POINTER(FlNrStatus),
            ctypes.c_char_p,
            ctypes.c_int32,
        ]
        self._process.restype = ctypes.c_int32
        self._get_status.argtypes = [ctypes.POINTER(FlNrStatus)]
        self._get_status.restype = ctypes.c_int32
        self._shutdown.argtypes = []
        self._shutdown.restype = None

    # ------------------------------------------------------------------ init
    def init(self, options: FlNrOptions, native_dir: str, log_dir: str) -> FlNrStatus:
        status = FlNrStatus()
        err = ctypes.create_string_buffer(self._MAX_ERR)
        code = self._init(
            ctypes.byref(options),
            native_dir,
            log_dir,
            ctypes.byref(status),
            err,
            self._MAX_ERR,
        )
        if code != FLNR_OK:
            message = err.value.decode("utf-8", "replace") or error_name(code)
            raise BridgeError(code, message)
        return status

    # --------------------------------------------------------------- process
    def process(self, frame: np.ndarray) -> Tuple[np.ndarray, FlNrStatus]:
        if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
            raise BridgeError(FLNR_ERR_BAD_ARG, "expected HxWx3 uint8 RGB frame")
        if not frame.flags["C_CONTIGUOUS"]:
            frame = np.ascontiguousarray(frame)
        height, width = frame.shape[:2]
        out = np.empty_like(frame)
        status = FlNrStatus()
        err = ctypes.create_string_buffer(self._MAX_ERR)
        code = self._process(
            frame.ctypes.data_as(ctypes.c_void_p),
            width * 3,
            out.ctypes.data_as(ctypes.c_void_p),
            width * 3,
            ctypes.byref(status),
            err,
            self._MAX_ERR,
        )
        if code != FLNR_OK:
            message = err.value.decode("utf-8", "replace") or error_name(code)
            raise BridgeError(code, message)
        return out, status

    def status(self) -> FlNrStatus:
        status = FlNrStatus()
        self._get_status(ctypes.byref(status))
        return status

    def shutdown(self) -> None:
        try:
            self._shutdown()
        except Exception:
            pass


def load_bridge(native_dir: str) -> NativeBridge:
    """Load the bridge DLL from ``native/`` (documented portable layout)."""
    from .runtime import BRIDGE_DLL  # local import to avoid a cycle

    return NativeBridge(os.path.join(native_dir, BRIDGE_DLL))

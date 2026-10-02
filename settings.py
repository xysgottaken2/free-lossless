"""Validated, per-user preferences shared by the menu and future app sessions."""
import json
import os
from pathlib import Path
import sys
import tempfile

import i18n


CAPTURE_MODES = ("bitblt", "dxcam")
SCALE_OPTIONS = ("1.0", "1.25", "1.5", "2.0", "Fullscreen")
# Canonical preset names, kept here so the settings module never imports OpenCV.
FILTER_PRESETS = ("Off", "Soft", "Sharp", "Vivid")
# Resolution the pipeline works at: "Auto" decides by algorithm (see main.py).
INTERNAL_RESOLUTIONS = ("Auto", "Performance", "HD", "Full HD", "Native")
DISPLAY_MODES = ("GDI", "D3D11")

ALGORITHM_OPTIONS = (
    "Bilinear", "Bicubic", "Lanczos", "FSR 1.0 / CAS (Nitidez)", "NVIDIA AI SuperRes",
)
ENGINE_OPTIONS = ("AI (RIFE ONNX)", "Fast (DIS Flow)")
# Multiplier 2 doubles the source rate; the slider only offers even values.
MULTIPLIER_MIN = 2
MULTIPLIER_MAX = 20
MULTIPLIER_STEP = 2
HOTKEY_OPTIONS = tuple(f"F{number}" for number in range(1, 13))
HOTKEY_SETTING_KEYS = ("hotkey_stop", "hotkey_fps", "hotkey_fsr")
# The dialog labels live in the translation catalog (i18n keys "hotkey.stop",
# "hotkey.fps" and "hotkey.fsr") so they follow the selected language.
DEFAULT_HOTKEYS = {"hotkey_stop": "F11", "hotkey_fps": "F10", "hotkey_fsr": "F9"}
DEFAULT_SETTINGS = {
    "version": 1,
    # First launch opens in English (US); the menu lets the user switch languages.
    "language": i18n.DEFAULT_LANGUAGE,
    "source_type": "window",
    "mode": "bitblt",
    "fps": 60,
    "scale": "1.0",
    "algo": "Lanczos",
    "sharpness": 20,
    "frame_multiplier": 2,
    "fg_enabled": True,
    # Post-processing filters applied by the overlay itself (see effects.py).
    "filter_preset": "Off",
    "internal_resolution": "Auto",
    # How the overlay presents its image. "D3D11" gives the process a Direct3D
    # swapchain, which is what ReShade can hook; "GDI" is the compatible default.
    "display_mode": "GDI",
    # Image filters (sharpening and the upscale algorithm) can be switched off to
    # compare the raw image, exactly like frame generation can.
    "filters_enabled": True,
    "engine_type": "AI (RIFE ONNX)",
    "ultra_smooth": False,
    "performance_mode": False,
    "low_latency": True,
    "show_fps": True,
    **DEFAULT_HOTKEYS,
    "preferred_sources": {},
}


def get_settings_path():
    """Never write beside the executable or into PyInstaller's temporary bundle."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        directory = Path(base) if base else Path.home() / "AppData" / "Local"
        return directory / "FreeLossless" / "settings.json"
    base = os.environ.get("XDG_CONFIG_HOME")
    directory = Path(base) if base else Path.home() / ".config"
    return directory / "free-lossless" / "settings.json"


def source_identity(source):
    """Keep stable names only, never stale HWNDs, monitor bounds or process IDs."""
    if not isinstance(source, dict):
        return None
    keys = ("device",) if source.get("source_type") == "display" else ("title", "process")
    identity = {}
    for key in keys:
        value = source.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 4096:
            return None
        identity[key] = value
    return identity


def hotkey_conflicts(hotkeys):
    """Return the setting keys that share a key, so the menu can explain the clash."""
    seen = {}
    conflicts = []
    for key in HOTKEY_SETTING_KEYS:
        value = hotkeys.get(key)
        if value in seen:
            conflicts.extend([seen[value], key])
        else:
            seen[value] = key
    return conflicts


def unique_hotkeys(hotkeys):
    """Give every action its own key, keeping valid choices and filling the rest."""
    used = set()
    result = {}
    for key in HOTKEY_SETTING_KEYS:
        value = hotkeys.get(key)
        if value not in HOTKEY_OPTIONS or value in used:
            value = next((candidate for candidate in (DEFAULT_HOTKEYS[key], *HOTKEY_OPTIONS)
                          if candidate not in used), None)
        used.add(value)
        result[key] = value
    return result


def normalize_settings(data):
    """Ignore unknown/invalid fields while preserving every valid preference."""
    result = {**DEFAULT_SETTINGS, "preferred_sources": {}}
    if not isinstance(data, dict):
        return result
    choices = {
        "source_type": ("window", "display"),
        "mode": CAPTURE_MODES,
        "scale": SCALE_OPTIONS,
        "algo": ALGORITHM_OPTIONS,
        "engine_type": ENGINE_OPTIONS,
        "filter_preset": FILTER_PRESETS,
        "internal_resolution": INTERNAL_RESOLUTIONS,
        "display_mode": DISPLAY_MODES,
    }
    for key, options in choices.items():
        if isinstance(data.get(key), str) and data[key] in options:
            result[key] = data[key]
    for key, minimum, maximum in (("fps", 30, 120), ("sharpness", 0, 100),
                                  ("frame_multiplier", MULTIPLIER_MIN, MULTIPLIER_MAX)):
        value = data.get(key)
        if type(value) is int and minimum <= value <= maximum:
            result[key] = value
    if result["frame_multiplier"] % MULTIPLIER_STEP:
        result["frame_multiplier"] = DEFAULT_SETTINGS["frame_multiplier"]
    for key in ("fg_enabled", "filters_enabled", "ultra_smooth", "performance_mode",
                "low_latency", "show_fps"):
        if isinstance(data.get(key), bool):
            result[key] = data[key]
    result["language"] = i18n.normalize_language(data.get("language"))
    result.update(unique_hotkeys(data))
    preferences = data.get("preferred_sources")
    if isinstance(preferences, dict):
        for kind in ("window", "display"):
            source = preferences.get(kind)
            if isinstance(source, dict):
                identity = source_identity({**source, "source_type": kind})
                if identity:
                    result["preferred_sources"][kind] = identity
    return result


class SettingsStore:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else get_settings_path()
        self.load_error = None

    def load(self):
        self.load_error = None
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
            if not isinstance(data, dict):
                raise ValueError("O arquivo de preferências não contém um objeto JSON.")
        except FileNotFoundError:
            return normalize_settings(None)
        except (OSError, ValueError, UnicodeError) as exc:
            # A broken or unreadable configuration must not prevent app startup.
            self.load_error = str(exc)
            return normalize_settings(None)
        return normalize_settings(data)

    def save(self, data):
        """Atomically replace the file so interrupted writes keep the previous save."""
        preferences = normalize_settings(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=".settings-", suffix=".tmp", delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                json.dump(preferences, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
            self.load_error = None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

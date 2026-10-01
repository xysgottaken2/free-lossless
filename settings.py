"""Validated, per-user preferences shared by the menu and future app sessions."""
import json
import os
from pathlib import Path
import sys
import tempfile


CAPTURE_MODES = ("bitblt", "dxcam")
SCALE_OPTIONS = ("1.0", "1.25", "1.5", "2.0", "Fullscreen")
ALGORITHM_OPTIONS = (
    "Bilinear", "Bicubic", "Lanczos", "FSR 1.0 / CAS (Nitidez)", "NVIDIA AI SuperRes",
)
ENGINE_OPTIONS = ("AI (RIFE ONNX)", "Fast (DIS Flow)")
DEFAULT_SETTINGS = {
    "version": 1,
    "source_type": "window",
    "mode": "bitblt",
    "fps": 60,
    "scale": "1.0",
    "algo": "Lanczos",
    "sharpness": 20,
    "fg_enabled": True,
    "engine_type": "AI (RIFE ONNX)",
    "ultra_smooth": False,
    "performance_mode": False,
    "low_latency": True,
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
    }
    for key, options in choices.items():
        if isinstance(data.get(key), str) and data[key] in options:
            result[key] = data[key]
    for key, minimum, maximum in (("fps", 30, 120), ("sharpness", 0, 100)):
        value = data.get(key)
        if type(value) is int and minimum <= value <= maximum:
            result[key] = value
    for key in ("fg_enabled", "ultra_smooth", "performance_mode", "low_latency"):
        if isinstance(data.get(key), bool):
            result[key] = data[key]
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

"""Persistent application configuration for Free Lossless.

The configuration is stored as JSON (default: ``config/freelossless.json`` next
to the application).  Sections:

* ``dlss5``  - DLSS 5 Neural Rendering stage (optional, external NVIDIA runtime)
* ``rife``   - RIFE frame generation stage
* ``capture``- capture / processing defaults

Only options that are *confirmed* to exist in the real DLSSNR runtime contract
(see ``docs/dlss5-research.md``) are exposed here.  Unknown keys are preserved
on load/save so future versions can extend the file safely.
"""

from __future__ import annotations

import copy
import json
import os
import threading

CONFIG_VERSION = 1

DEFAULT_CONFIG = {
    "version": CONFIG_VERSION,
    "dlss5": {
        # Master switch. When false the runtime is never touched.
        "enabled": False,
        # Neural work resolution = frame resolution * work_scale (the
        # "processing scale" used by NeuralScreen-style standalone tools).
        "work_scale": 1.0,
        # Multi-pass: 1 = single evaluate, 2 = evaluate twice with the first
        # pass output fed back as color ("TWO_PASSES" mode in community tools).
        "passes": 1,
        # DLSSNR.Hint.Render.Preset - opaque uint; 1 is the value observed in
        # measured-working standalone logs. Semantics are undocumented.
        "preset": 1,
        # DLSSNR.Style - community reports 7 styles (0..6).
        "style": 1,
        # DLSSNR.Intensity - 0.0 .. 1.0 (community guidance: 0.20-0.35).
        "intensity": 0.35,
        # DLSSNR.LocalToneStrength / LocalStructureStrength / SkinStructureStrength
        "local_tone": 1.0,
        "local_structure": 1.0,
        "skin_structure": 1.0,
        # DLSSNR.UseAutoMask
        "auto_mask": 1,
        # DLSS.Exposure.Scale
        "exposure": 1.0,
        # 0 = stateless frames (DLSSNR.Reset=1 every frame; safe with the
        # zero-motion-vector contract of external capture), 1 = temporal.
        "temporal": 0,
    },
    "rife": {
        "enabled": True,
        "engine_type": "AI (RIFE ONNX)",
        "ultra_smooth": False,
    },
    "capture": {
        "mode": "dxcam",
        "target_fps": 60,
        "low_latency": True,
        "performance_mode": False,
        # Capture source: "window" (one app) or "fullscreen" (whole monitor).
        "source": "window",
        # Monitor index for Full Screen mode (0 = primary).
        "monitor": 0,
    },
}

# Ranges used to sanitize loaded values.
_CLAMPS = {
    ("dlss5", "work_scale"): (0.25, 1.0),
    ("dlss5", "passes"): (1, 2),
    ("dlss5", "preset"): (0, 255),
    ("dlss5", "style"): (0, 6),
    ("dlss5", "intensity"): (0.0, 1.0),
    ("dlss5", "local_tone"): (0.0, 2.0),
    ("dlss5", "local_structure"): (0.0, 2.0),
    ("dlss5", "skin_structure"): (0.0, 2.0),
    ("dlss5", "exposure"): (0.1, 4.0),
    ("dlss5", "temporal"): (0, 1),
    ("capture", "target_fps"): (10, 240),
    ("capture", "monitor"): (0, 15),
}


def _clamp(value, lo, hi, cast):
    try:
        value = cast(value)
    except (TypeError, ValueError):
        return None
    return max(lo, min(hi, value))


class AppConfig:
    """Load/save the JSON configuration, tolerating missing or bad values."""

    def __init__(self, path=None, data=None):
        self.path = path
        self._lock = threading.Lock()
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        if data is not None:
            self._merge(data)
        self.sanitize()

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, path=None):
        """Load ``path`` (or the default location). Missing file -> defaults."""
        if path is None:
            path = default_config_path()
        cfg = cls(path=path)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                cfg._merge(raw)
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[CONFIG] Could not read {path}: {exc} - using defaults")
        cfg.sanitize()
        return cfg

    def _merge(self, raw):
        for section, values in raw.items():
            if section == "version":
                continue
            if isinstance(values, dict):
                target = self.data.setdefault(section, {})
                for key, value in values.items():
                    target[key] = value

    # ----------------------------------------------------------------- save
    def save(self, path=None):
        with self._lock:
            target = path or self.path or default_config_path()
            directory = os.path.dirname(os.path.abspath(target))
            if directory:
                os.makedirs(directory, exist_ok=True)
            with open(target, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=4, sort_keys=True)
            self.path = target
            return target

    # ------------------------------------------------------------- sanitize
    def sanitize(self):
        """Fill defaults and clamp values in place."""
        self.data["version"] = CONFIG_VERSION
        for section, defaults in DEFAULT_CONFIG.items():
            if section == "version":
                continue
            target = self.data.setdefault(section, {})
            for key, value in defaults.items():
                if key not in target or target[key] is None:
                    target[key] = copy.deepcopy(value)
        for (section, key), (lo, hi) in _CLAMPS.items():
            value = self.data.get(section, {}).get(key)
            cast = int if isinstance(lo, int) else float
            clamped = _clamp(value, lo, hi, cast)
            if clamped is None:
                clamped = copy.deepcopy(DEFAULT_CONFIG[section][key])
            self.data[section][key] = clamped
        # Capture source string ("window" / "fullscreen", tolerant to aliases)
        from targets import normalize_source
        capture = self.data.get("capture", {})
        capture["source"] = normalize_source(capture.get("source", "window"))
        capture["mode"] = str(capture.get("mode", "dxcam"))
        # Booleans
        for (section, key) in (("dlss5", "enabled"), ("dlss5", "auto_mask"),
                               ("rife", "enabled"), ("rife", "ultra_smooth"),
                               ("capture", "low_latency"), ("capture", "performance_mode")):
            self.data[section][key] = bool(self.data[section][key])

    # -------------------------------------------------------------- helpers
    @property
    def dlss5(self):
        return self.data["dlss5"]

    @property
    def rife(self):
        return self.data["rife"]

    @property
    def capture(self):
        return self.data["capture"]

    def dlss5_options(self):
        """Dictionary copy suitable for shipping into a worker process."""
        return dict(self.data["dlss5"])


def default_config_path():
    """``<app dir>/config/freelossless.json`` (portable layout)."""
    base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "config", "freelossless.json")

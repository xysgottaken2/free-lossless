"""Post-processing filters applied by the overlay itself.

Why not load ReShade directly: ReShade is a DirectX hook that installs *inside the
game* and rewrites what the game presents. The overlay is a separate window that
captures the game's final image, so there is nothing for ReShade to hook there — and
injecting it into the game is exactly what anti-cheat systems block.

What this module does instead: it applies the visual work of the most used ReShade
effects to the image the overlay already owns, which works for every game (windowed,
borderless, exclusive, protected or not) because the game is never touched. The
effects are the same ideas with the same names:

* ``luma_sharpen`` — ReShade's LumaSharpen: sharpen only where the luma detail is
  real, with a clamp so halos cannot grow.
* ``vibrance`` — ReShade's Vibrance: raise saturation on muted colours and leave
  already saturated ones alone (this is what keeps skin tones natural).
* ``clarity`` — local contrast with a wide radius, the ReShade "Clarity" look.
* ``contrast`` — gentle S-curve, applied through a lookup table.

ReShade itself is handled by reshade.py: this module never touches the game, only the
frame the overlay is about to show.

Everything is 8-bit saturating maths at the internal resolution (before the
upscale), so a preset costs a few milliseconds per frame instead of tens.
"""
import cv2
import numpy as np

import diagnostics

# The presets keep the canonical English names in the settings file, like every
# other stored choice; the menu shows translated labels.
PRESETS = {
    "Off": (),
    "Soft": (("luma_sharpen", {"amount": 0.35, "clamp": 16}),
             ("vibrance", {"amount": 0.25})),
    "Sharp": (("luma_sharpen", {"amount": 0.6, "clamp": 24}),
              ("clarity", {"amount": 0.25})),
    "Vivid": (("vibrance", {"amount": 0.5}),
              ("contrast", {"strength": 0.35})),
}
PRESET_ORDER = ("Off", "Soft", "Sharp", "Vivid")


def _as_float(value, default, low, high):
    try:
        return min(max(float(value), low), high)
    except (TypeError, ValueError):
        return default


def _luma(frame):
    return cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)


def _detail(gray, radius=3):
    """Positive and negative detail of a grey image, in 8-bit."""
    blurred = cv2.blur(gray, (radius, radius))
    return cv2.subtract(gray, blurred), cv2.subtract(blurred, gray)


def _scale(values, factor):
    """Multiply by a scalar in 8-bit saturating maths (never wraps around)."""
    if factor <= 0:
        return None
    if factor >= 1.0:
        return values
    return cv2.convertScaleAbs(values, alpha=float(factor))


def _as_rgb(values):
    """Detail images are computed on one channel; arithmetic needs three."""
    return cv2.cvtColor(values, cv2.COLOR_GRAY2RGB) if values.ndim == 2 else values


def _apply_detail(frame, positive, negative, weight=None):
    """Add the positive detail to the frame and subtract the negative one.

    ``weight`` is a per-pixel 0-255 amount; without it the detail is applied as is.
    """
    if weight is None:
        return cv2.subtract(cv2.add(frame, _as_rgb(positive)), _as_rgb(negative))
    weight_rgb = _as_rgb(weight)
    brighter = cv2.add(frame, cv2.multiply(_as_rgb(positive), weight_rgb, scale=1.0 / 255.0))
    return cv2.subtract(brighter, cv2.multiply(_as_rgb(negative), weight_rgb, scale=1.0 / 255.0))


def _luma(frame):
    return cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)


def _detail(gray, radius=3):
    """Positive and negative detail of a grey image, in 8-bit."""
    blurred = cv2.blur(gray, (radius, radius))
    return cv2.subtract(gray, blurred), cv2.subtract(blurred, gray)


def luma_sharpen(frame, amount=0.5, clamp=20, radius=3):
    """Sharpen the luma detail only, with a clamp on how far it can go."""
    amount = _as_float(amount, 0.5, 0.0, 2.0)
    limit = int(_as_float(clamp, 20.0, 0.0, 255.0))
    if amount <= 0 or limit <= 0:
        return frame
    positive, negative = _detail(_luma(frame), radius)
    if limit < 255:
        # Clamping is what separates LumaSharpen from a plain sharpen: without it,
        # strong edges get the same boost as fine detail and grow white halos.
        positive = np.minimum(positive, limit)
        negative = np.minimum(negative, limit)
    return _apply_detail(frame, _scale(positive, amount), _scale(negative, amount))


def vibrance(frame, amount=0.4):
    """Saturation boost that protects colours that are already saturated."""
    amount = _as_float(amount, 0.4, 0.0, 2.0)
    if amount <= 0:
        return frame
    saturation = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)[:, :, 1]
    # Saturated pixels (saturation near 255) get no boost at all; muted ones get it all.
    weight = _scale(cv2.bitwise_not(saturation), amount)
    if weight is None:
        return frame
    gray = _as_rgb(_luma(frame))
    return _apply_detail(frame, cv2.subtract(frame, gray), cv2.subtract(gray, frame), weight)


def clarity(frame, amount=0.3, radius=9):
    """Local contrast with a wide radius: the ReShade Clarity look."""
    amount = _as_float(amount, 0.3, 0.0, 2.0)
    if amount <= 0:
        return frame
    gray = _luma(frame)
    blurred = cv2.GaussianBlur(gray, (0, 0), max(1.0, radius / 3.0))
    positive = _scale(cv2.subtract(gray, blurred), amount)
    negative = _scale(cv2.subtract(blurred, gray), amount)
    if positive is None:
        return frame
    return _apply_detail(frame, positive, negative)


def contrast(frame, strength=0.35):
    """Gentle S-curve around mid grey, through a 8-bit lookup table."""
    strength = _as_float(strength, 0.35, 0.0, 1.0)
    if strength <= 0:
        return frame
    values = np.arange(256, dtype=np.float32) / 255.0
    # Smooth S-curve: keeps black and white fixed, leaves mid grey almost untouched.
    curved = values + strength * (values - 0.5) * 4.0 * values * (1.0 - values)
    table = np.clip(curved * 255.0, 0, 255).astype(np.uint8)
    return cv2.LUT(frame, table)


EFFECTS = {
    "luma_sharpen": luma_sharpen,
    "vibrance": vibrance,
    "clarity": clarity,
    "contrast": contrast,
}


class EffectChain:
    """A named preset of effects, applied in order to each frame."""

    def __init__(self, preset="Off"):
        self.preset = "Off"
        self.steps = []
        self.set_preset(preset)

    def set_preset(self, preset):
        """Unknown names fall back to Off, so a hand-edited file cannot break it."""
        if preset not in PRESETS:
            preset = "Off"
        self.preset = preset
        self.steps = PRESETS[preset]

    @property
    def enabled(self):
        return bool(self.steps)

    def apply(self, frame):
        """Run the chain; a failing effect is skipped instead of stopping the overlay."""
        for name, parameters in self.steps:
            effect = EFFECTS.get(name)
            if effect is None:
                continue
            try:
                frame = effect(frame, **parameters)
            except Exception as exc:  # pragma: no cover - defensive
                # Never silent: a filter that fails would otherwise look like it ran.
                diagnostics.write_now("filtros", f"{name} falhou e foi ignorado: {exc}")
                continue
        return frame

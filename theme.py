"""Shared palette and logo drawing, used by the menu and the startup splash."""

COLORS = {
    "background": "#0C111B",
    "panel": "#141D2B",
    "input": "#1D293B",
    "border": "#2A3950",
    "text": "#F1F5FC",
    "muted": "#9CAEC7",
    "accent": "#7695FF",
    "accent_hover": "#92AAFF",
    "accent_dim": "#293D6B",
    "success": "#69DDB2",
    "warning": "#F0BC78",
}


def draw_logo(canvas, x, y, size, background=None):
    """Two offset frames with a spark line: the same mark used in the menu header."""
    background = background or COLORS["background"]
    unit = size / 44
    canvas.create_rectangle(x + 4 * unit, y + 4 * unit, x + 30 * unit, y + 30 * unit,
                            outline=COLORS["accent"], width=max(1, round(2 * unit)))
    canvas.create_rectangle(x + 14 * unit, y + 14 * unit, x + 40 * unit, y + 40 * unit,
                            fill=background, outline=COLORS["success"], width=max(1, round(2 * unit)))
    canvas.create_line(x + 20 * unit, y + 28 * unit, x + 25 * unit, y + 23 * unit,
                       x + 30 * unit, y + 28 * unit, x + 35 * unit, y + 23 * unit,
                       fill=COLORS["success"], width=max(1, round(2 * unit)))

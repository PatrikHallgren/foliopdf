"""Display-only geometry and Omarchy palette support (no document changes)."""
from pathlib import Path
import os
import re
import tomllib

FALLBACK = {
    "background": "#151821", "dark_background": "#10131b", "lighter_background": "#242936",
    "foreground": "#e7e9ee", "dark_foreground": "#a5abb8", "accent": "#9bafff",
    "selection": "#3b526f", "red": "#ec7979", "mode": "dark",
}


def omarchy_colors(home=None):
    home = Path(home) if home is not None else Path.home()
    state = Path(os.environ.get("XDG_STATE_HOME", home / ".local/state"))
    config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    # The active palette includes stock theme + user overlay, and survives renames.
    for root in (state / "omarchy/current/theme", config / "omarchy/current/theme"):
        try:
            with (root / "colors.toml").open("rb") as stream:
                raw = tomllib.load(stream)
            colors = FALLBACK.copy()
            for key in colors:
                value = raw.get(key)
                if isinstance(value, str) and (value in ("light", "dark") if key == "mode"
                                               else re.fullmatch(r"#[0-9a-fA-F]{6}", value)):
                    colors[key] = value
            return colors
        except (OSError, ValueError):
            continue
    return FALLBACK.copy()


def mix(a, b, weight):
    return "#" + "".join(f"{round(int(a[i:i+2], 16) * (1-weight) + int(b[i:i+2], 16) * weight):02x}"
                         for i in (1, 3, 5))


def fit_scale(page, viewport, mode="page", margin=40):
    width, height = page
    available_width, available_height = viewport
    scale = max(1, available_width - margin) / width
    if mode == "page":
        scale = min(scale, max(1, available_height - margin) / height)
    return max(.1, min(4., scale))

"""Persisted appearance for the always-on-top caption bar."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

MIN_FONT = 10
MAX_FONT = 36
MIN_OPACITY = 0.35
MAX_OPACITY = 1.0
MIN_WIDTH = 380
MAX_WIDTH = 1600
MIN_HEIGHT = 96
MAX_HEIGHT = 720


def settings_path() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    folder = root / "LiveFeed"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "overlay.json"


@dataclass
class OverlayPrefs:
    font_size: int = 14
    opacity: float = 0.94
    width: int = 760
    height: int = 120
    x: int | None = None
    y: int | None = None
    minimized: bool = False

    def clamp(self) -> OverlayPrefs:
        self.font_size = max(MIN_FONT, min(MAX_FONT, int(self.font_size)))
        self.opacity = max(MIN_OPACITY, min(MAX_OPACITY, float(self.opacity)))
        self.width = max(MIN_WIDTH, min(MAX_WIDTH, int(self.width)))
        self.height = max(MIN_HEIGHT, min(MAX_HEIGHT, int(self.height)))
        return self


def load_overlay_prefs() -> OverlayPrefs:
    path = settings_path()
    if not path.is_file():
        return OverlayPrefs()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return OverlayPrefs()
    allowed = {key: data[key] for key in OverlayPrefs.__dataclass_fields__ if key in data}
    return OverlayPrefs(**allowed).clamp()


def save_overlay_prefs(prefs: OverlayPrefs) -> None:
    path = settings_path()
    path.write_text(json.dumps(asdict(prefs.clamp()), indent=2), encoding="utf-8")


def update_overlay_prefs(**changes) -> OverlayPrefs:
    prefs = load_overlay_prefs()
    for key, value in changes.items():
        if hasattr(prefs, key) and value is not None:
            setattr(prefs, key, value)
    save_overlay_prefs(prefs)
    return prefs

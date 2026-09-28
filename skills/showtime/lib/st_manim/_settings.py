"""Run settings for the kit: written by `showtime manim render|check`, read here at import.

$SHOWTIME_MANIM points at a JSON file:
    {"theme": {...st.manim_run.palette...}, "colors": {"n": "hue1"}, "cues": {...} | null,
     "scenes": {"Name": {"log": "/abs/log.json", "poster": "/abs/poster.png"}}, "aspect": "16:9"}

Without it (a plain `manim render scenes.py` call) the kit resolves the theme from the current
folder's brand.json and runs without cues.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

ENV = "SHOWTIME_MANIM"
_LIB = Path(__file__).resolve().parents[1]
if str(_LIB) not in sys.path:          # the kit uses showtime's stdlib helpers (st.manim_run.palette, st.brand)
    sys.path.append(str(_LIB))


def _load() -> Dict[str, Any]:
    p = os.environ.get(ENV)
    if p and Path(p).is_file():
        try:
            data = json.loads(Path(p).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data["_file"] = p
                return data
        except (OSError, ValueError):
            pass
    return {}


S: Dict[str, Any] = _load()


def theme_dict() -> Dict[str, Any]:
    th = S.get("theme")
    if isinstance(th, dict) and th.get("bg"):
        return th
    from st.manim_run import palette
    th = palette.resolve(Path.cwd())
    S["theme"] = th
    return th


def cues() -> Optional[Dict[str, Any]]:
    c = S.get("cues")
    return c if isinstance(c, dict) and c.get("lines") else None


def scene_paths(name: str) -> Dict[str, Any]:
    return (S.get("scenes") or {}).get(name) or {}


def colors() -> Dict[str, str]:
    c = S.get("colors") or {}
    return {str(k): str(v) for k, v in c.items()} if isinstance(c, dict) else {}

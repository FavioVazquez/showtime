"""Which TTS engines exist and where their modules live (stdlib only).

Built in: kokoro (default), supertonic, piper. Extra local engines are Python
modules named `<name>.py` that expose `ENGINE`, an st.voice.engines.base.Engine
instance (Piper-shaped: `has_timings = False` gets the usual alignment). They
are found, in this order:

    $SHOWTIME_ENGINE_PATH       folders, separated like PATH (os.pathsep)
    <showtime home>/engines/    survives a showtime update
    st/voice/engines/           next to piper.py (replaced by an update)

A built-in name always means the built-in engine. Names must match
`^[a-z][a-z0-9_]{0,31}$`; nothing is imported until an engine is used.
This module is stdlib only, so `showtime doctor` can use it before the venv exists.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional

BUILTIN = ("kokoro", "supertonic", "piper")
ALIASES = {"st": "supertonic"}
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
PACKAGE_DIR = Path(__file__).resolve().parent / "engines"
_NOT_ENGINES = {"base"}


def valid_name(name: str) -> bool:
    return bool(NAME_RE.match(name or ""))


def search_dirs() -> List[Path]:
    """Folders searched for extra engines, first match wins (see the module docstring)."""
    from ..common import home
    out: List[Path] = []
    for part in (os.environ.get("SHOWTIME_ENGINE_PATH") or "").split(os.pathsep):
        if part.strip():
            out.append(Path(os.path.expanduser(part.strip())))
    out.append(home() / "engines")
    out.append(PACKAGE_DIR)
    return out


def discover() -> Dict[str, Path]:
    """Extra (non-built-in) engines found on disk: {name: module path}."""
    found: Dict[str, Path] = {}
    for d in search_dirs():
        try:
            files = sorted(d.glob("*.py")) if d.is_dir() else []
        except OSError:
            continue
        for f in files:
            name = f.stem
            if name in BUILTIN or name in _NOT_ENGINES or name in found or not valid_name(name):
                continue
            found[name] = f
    return found


def find(name: str) -> Optional[Path]:
    """The module file for extra engine `name`, or None."""
    return discover().get(name) if valid_name(name) and name not in BUILTIN else None


def engine_of(voice: str) -> str:
    """The engine a voice id names: `<engine>:<voice>` -> engine; Kokoro ids and blends -> kokoro.
    Does not check that the engine exists."""
    v = (voice or "").strip()
    head, sep, tail = v.partition(":")
    head = head.lower()
    if not sep or "+" in v:
        return "kokoro"
    head = ALIASES.get(head, head)
    if head in BUILTIN:
        return head
    from .voices import KOKORO_IDS
    if valid_name(head) and head not in KOKORO_IDS and not re.match(r"^\d+(?:\.\d+)?$", tail):
        return head
    return "kokoro"

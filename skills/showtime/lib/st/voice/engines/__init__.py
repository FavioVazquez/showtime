"""TTS engines. Each module exposes `ENGINE` (an Engine subclass instance).

Bundled: kokoro (default), supertonic (optional), piper (optional). Extra engines
load the same way (Piper-shaped: ``has_timings = False`` uses CTC align in tts.py)
from, in order:

1. this package (``st.voice.engines.<name>``)
2. directories in ``$SHOWTIME_ENGINE_PATH`` (``os.pathsep``-separated)
3. ``$SHOWTIME_HOME/engines/<name>.py`` (default ``~/.showtime/engines``)

A drop-in in the user folder survives a showtime update. Showtime never ships a
network engine; your module is your code on your machines.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...common import home
from .base import Engine, EngineResult  # noqa: F401

_CACHE: Dict[str, Engine] = {}
_ENGINE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_SKIP_MODS = frozenset({"base", "__init__"})
_USER_MOD_PREFIX = "st.voice.engines._user."


def bundled_names() -> Tuple[str, ...]:
    return ("kokoro", "supertonic", "piper")


def clear_cache() -> None:
    """Drop loaded engines (tests)."""
    _CACHE.clear()
    for key in [k for k in sys.modules if k.startswith(_USER_MOD_PREFIX)]:
        sys.modules.pop(key, None)


def _valid_name(name: str) -> bool:
    return bool(_ENGINE_NAME.match(name or ""))


def user_engine_dirs() -> List[Path]:
    """Directories that may hold drop-in ``<name>.py`` engines."""
    out: List[Path] = []
    seen = set()

    def add(p: Path) -> None:
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key in seen:
            return
        seen.add(key)
        out.append(p)

    for part in (os.environ.get("SHOWTIME_ENGINE_PATH") or "").split(os.pathsep):
        part = part.strip()
        if not part:
            continue
        p = Path(os.path.expanduser(part))
        if p.is_file() and p.suffix == ".py":
            add(p.parent)
        elif p.is_dir():
            add(p)
    home_dir = home() / "engines"
    if home_dir.is_dir():
        add(home_dir)
    return out


def _package_extra_names() -> List[str]:
    found: List[str] = []
    here = Path(__file__).resolve().parent
    for p in sorted(here.glob("*.py")):
        n = p.stem
        if n in _SKIP_MODS or n.startswith("_") or n in bundled_names():
            continue
        if _valid_name(n):
            found.append(n)
    return found


def _user_file_names() -> List[str]:
    found: List[str] = []
    for d in user_engine_dirs():
        try:
            files = sorted(d.glob("*.py"))
        except OSError:
            continue
        for p in files:
            n = p.stem
            if n.startswith("_") or not _valid_name(n):
                continue
            if n not in found and n not in bundled_names():
                found.append(n)
    return found


def names() -> Tuple[str, ...]:
    """Bundled engines plus every discoverable extra (package and user folders)."""
    found = list(bundled_names())
    for n in _package_extra_names() + _user_file_names():
        if n not in found:
            found.append(n)
    return tuple(found)


# Back-compat: tests and docs used a constant. Extra modules extend ``names()``.
NAMES = bundled_names()


def _hint_engines() -> str:
    found = names()
    return "engines found: " + (", ".join(found) if found else "(none)")


def _find_user_file(name: str) -> Optional[Path]:
    for d in user_engine_dirs():
        cand = d / (name + ".py")
        if cand.is_file():
            return cand
    return None


def _load_from_file(name: str, path: Path):
    mod_name = _USER_MOD_PREFIX + name
    spec = importlib.util.spec_from_file_location(mod_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError("cannot load engine from %s" % path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return mod


def _import_engine_module(name: str):
    """Load the module for ``name`` from the package, then user folders."""
    try:
        return importlib.import_module("." + name, __package__)
    except ImportError:
        path = _find_user_file(name)
        if path is None:
            raise
        return _load_from_file(name, path)


def get(name: str) -> Engine:
    """The engine instance for `name` (imports its module lazily)."""
    key = (name or "").strip().lower()
    if not _valid_name(key):
        from ...common import ShowtimeError
        raise ShowtimeError(
            "unknown TTS engine %r" % name,
            hint="engine names are [a-z][a-z0-9_]{0,31}. " + _hint_engines(),
        )
    if key not in _CACHE:
        try:
            mod = _import_engine_module(key)
        except Exception as e:  # ImportError and load failures
            from ...common import ShowtimeError
            raise ShowtimeError(
                "unknown TTS engine %r" % key,
                hint=_hint_engines() + ". Drop %s.py with an ENGINE instance under "
                     "$SHOWTIME_HOME/engines or $SHOWTIME_ENGINE_PATH (see piper.py)" % key,
            ) from e
        eng = getattr(mod, "ENGINE", None)
        if eng is None:
            from ...common import ShowtimeError
            raise ShowtimeError("engine module %r has no ENGINE" % key,
                                hint=_hint_engines())
        _CACHE[key] = eng
    return _CACHE[key]


def probe_extras() -> List[Dict[str, Any]]:
    """For doctor: each non-bundled engine name and whether ``get`` / import works."""
    rows: List[Dict[str, Any]] = []
    for n in names():
        if n in bundled_names():
            continue
        try:
            eng = get(n)
            detail = "imports (%s)" % (getattr(eng, "name", n) or n)
            ok = True
            err = ""
        except Exception as e:  # noqa: BLE001
            ok = False
            detail = "import failed: %s: %s" % (type(e).__name__, e)
            err = str(e)
        rows.append({"name": n, "ok": ok, "detail": detail, "error": err})
    return rows

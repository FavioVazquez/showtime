"""TTS engines. Each module exposes `ENGINE` (an Engine subclass instance).

    kokoro      default; 54 voices, 9 language variants (8 languages), exact word timings
    supertonic  optional; 31 languages (best fast Spanish), no timings (aligned)
    piper       optional fast fallback via sherpa-onnx; no timings (aligned)

Extra local engines are loaded by name from the folders st.voice.registry
lists (an engine of your own, Piper-shaped; see references/voice.md).
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from typing import Dict

from .. import registry
from .base import Engine, EngineResult  # noqa: F401

_CACHE: Dict[str, Engine] = {}

NAMES = registry.BUILTIN


def _hint() -> str:
    extra = sorted(registry.discover())
    return ("engines: %s%s; an engine of your own goes in %s/<name>.py (or $SHOWTIME_ENGINE_PATH)"
            % (", ".join(NAMES), (", " + ", ".join(extra)) if extra else "", registry.search_dirs()[-2]))


def get(name: str) -> Engine:
    """The engine instance for `name` (imports its module lazily)."""
    from ...common import ShowtimeError
    name = registry.ALIASES.get(name, name)
    if name in _CACHE:
        return _CACHE[name]
    if not registry.valid_name(name):
        raise ShowtimeError("bad TTS engine name %r" % name, why="engine names match ^[a-z][a-z0-9_]{0,31}$",
                            hint=_hint())
    if name in NAMES:
        mod = importlib.import_module("." + name, __name__)
    else:
        path = registry.find(name)
        if path is None:
            raise ShowtimeError("unknown TTS engine %r" % name, hint=_hint())
        # loaded as st.voice.engines.<name>, so a copy of piper.py keeps working: its relative imports
        # (from .base, from .. import models, from ...common) resolve as they do for the built-in engines
        full = "%s.%s" % (__name__, name)
        spec = importlib.util.spec_from_file_location(full, str(path))
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        sys.modules[full] = mod
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
        except Exception as e:  # noqa: BLE001 - the engine's own code
            sys.modules.pop(full, None)
            raise ShowtimeError("TTS engine %r failed to import: %s: %s" % (name, type(e).__name__, e),
                                why="its module is %s" % path, hint="fix that file, or pick another voice")
    eng = getattr(mod, "ENGINE", None)
    if not isinstance(eng, Engine):
        raise ShowtimeError("TTS engine %r has no ENGINE" % name,
                            why="%s must set ENGINE to an st.voice.engines.base.Engine instance" % mod.__file__,
                            hint="see the Piper engine (st/voice/engines/piper.py) for the shape")
    _CACHE[name] = eng
    return eng

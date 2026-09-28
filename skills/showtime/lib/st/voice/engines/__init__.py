"""TTS engines. Each module exposes `ENGINE` (an Engine subclass instance).

    kokoro      default; 54 voices, 9 languages, exact word timings
    supertonic  optional; 31 languages (best fast Spanish), no timings (aligned)
    piper       optional fast fallback via sherpa-onnx; no timings (aligned)
"""
from __future__ import annotations

from typing import Dict

from .base import Engine, EngineResult  # noqa: F401

_CACHE: Dict[str, Engine] = {}


def get(name: str) -> Engine:
    """The engine instance for `name` (imports its module lazily)."""
    if name not in _CACHE:
        if name == "kokoro":
            from .kokoro import ENGINE
        elif name == "supertonic":
            from .supertonic import ENGINE
        elif name == "piper":
            from .piper import ENGINE
        else:
            from ...common import ShowtimeError
            raise ShowtimeError("unknown TTS engine %r" % name, hint="engines: kokoro, supertonic, piper")
        _CACHE[name] = ENGINE
    return _CACHE[name]


NAMES = ("kokoro", "supertonic", "piper")

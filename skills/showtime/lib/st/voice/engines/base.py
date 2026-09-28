"""Engine interface shared by the TTS back-ends."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ..textnorm import Token
from ..voices import VoiceSpec


@dataclass
class EngineResult:
    audio: np.ndarray                          # mono float32
    sample_rate: int
    words: Optional[List[Dict[str, Any]]]      # [{text,start,end}] or None if the engine has no timings
    phonemes: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


class Engine:
    name = "base"
    has_timings = False
    speed_range: Tuple[float, float] = (0.5, 2.0)

    def available(self) -> Tuple[bool, str]:
        """(ok, reason). Cheap: must not load models."""
        raise NotImplementedError

    def prepare(self, spec: VoiceSpec) -> None:
        """Load models for `spec` ahead of synthesis (so timings exclude loading)."""

    def model_id(self, spec: VoiceSpec) -> str:
        """A string that changes whenever the model files change (cache key)."""
        return self.name

    def synth(self, tokens: List[Token], spec: VoiceSpec, speed: float, lexicon,
              sentence_pause: float = 0.3, clause_pause: float = 0.12) -> EngineResult:
        raise NotImplementedError


def check_speed(engine: Engine, speed: float) -> float:
    from ...common import ShowtimeError
    lo, hi = engine.speed_range
    if not (lo <= float(speed) <= hi):
        raise ShowtimeError("speed %.2f is outside %s's range %.1f-%.1f" % (speed, engine.name, lo, hi),
                            hint="1.0 is natural; 0.9 calm; 1.1 upbeat")
    return float(speed)

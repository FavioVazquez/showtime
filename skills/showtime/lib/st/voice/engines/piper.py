"""Piper voices through sherpa-onnx (optional fast fallback, ~20x real time).

Only voices whose training data allows commercial use are offered (see
voices.PIPER_VOICES); each downloads once (60-115 MB) on first use. The
sherpa-onnx runtime is Apache-2.0 and carries its own espeak-ng data, so the
GPL piper package is not needed. Plain text input: pronunciation fixes use
lexicon respellings ("say"). No word timings: tts.py aligns the output.
"""
from __future__ import annotations

import os
import threading
from typing import Dict, List, Tuple

import numpy as np

from ...common import ShowtimeError
from .. import models
from ..textnorm import Token
from ..voices import PIPER_VOICES, VoiceSpec
from .base import Engine, EngineResult, check_speed

_lock = threading.Lock()


class PiperEngine(Engine):
    name = "piper"
    has_timings = False
    speed_range = (0.5, 2.0)

    def __init__(self) -> None:
        self._tts: Dict[str, object] = {}

    def available(self) -> Tuple[bool, str]:
        try:
            import sherpa_onnx  # noqa: F401
        except Exception as e:  # noqa: BLE001
            return False, "sherpa-onnx is not installed (%s)" % type(e).__name__
        return True, "voices download on first use"

    def prepare(self, spec: VoiceSpec) -> None:
        self.load(spec.name)

    def model_id(self, spec: VoiceSpec) -> str:
        return "piper:%s:%s" % (spec.name, PIPER_VOICES[spec.name]["sha256"][:12])

    def load(self, name: str):
        if name in self._tts:
            return self._tts[name]
        import sherpa_onnx as so
        d = models.ensure_piper(name)
        onnx = d / (name + ".onnx")
        if not onnx.is_file():
            onnx = sorted(d.glob("*.onnx"))[0]
        thr = os.environ.get("SHOWTIME_THREADS")
        vits = so.OfflineTtsVitsModelConfig(model=str(onnx), tokens=str(d / "tokens.txt"),
                                            data_dir=str(d / "espeak-ng-data"))
        cfg = so.OfflineTtsConfig(model=so.OfflineTtsModelConfig(
            vits=vits, num_threads=int(thr) if thr and thr.isdigit() else 2, provider="cpu"))
        if not cfg.validate():
            raise ShowtimeError("Piper voice %s failed validation (files in %s)" % (name, d),
                                hint="delete that folder and run again to re-download")
        tts = so.OfflineTts(cfg)
        self._tts[name] = tts
        return tts

    def synth(self, tokens: List[Token], spec: VoiceSpec, speed: float, lexicon,
              sentence_pause: float = 0.3, clause_pause: float = 0.12) -> EngineResult:
        check_speed(self, speed)
        tts = self.load(spec.name)
        parts = []
        for t in tokens:
            say = t.say or (lexicon.say(t.core, spec.lang) if lexicon is not None else None)
            parts.append(t.lead + (say or t.spoken or t.core) + t.trail)
        with _lock:
            out = tts.generate(" ".join(parts), sid=0, speed=float(speed))
        audio = np.asarray(out.samples, dtype=np.float32)
        if audio.size == 0:
            raise ShowtimeError("Piper produced no audio for this text")
        return EngineResult(audio=audio, sample_rate=int(out.sample_rate), words=None,
                            meta={"model": "piper-" + spec.name, "license": PIPER_VOICES[spec.name]["license"]})


ENGINE = PiperEngine()

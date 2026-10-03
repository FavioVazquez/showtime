"""Supertonic 3 (optional): fast multilingual TTS, 31 languages, 10 presets.

Installed by `showtime setup --with supertonic` (package + weights in
~/.showtime/models/supertonic3). It reads plain text (no phoneme input), so
pronunciation fixes use lexicon respellings ("say"), not IPA. It reports no
word timings: tts.py aligns its output (Kokoro reference + DTW for most
languages, CTC for English).

Weights: OpenRAIL-M (commercial use allowed with use-based restrictions);
code: MIT. Quality steps: SHOWTIME_SUPERTONIC_STEPS (default 8; 5 is faster).
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import List, Tuple

import numpy as np

from ...common import ShowtimeError, ort_telemetry_off, paths
from ..textnorm import Token
from ..voices import VoiceSpec
from .base import Engine, EngineResult, check_speed

_lock = threading.Lock()


class SupertonicEngine(Engine):
    name = "supertonic"
    has_timings = False
    speed_range = (0.7, 2.0)

    def __init__(self) -> None:
        self._tts = None

    def model_dir(self):
        env = os.environ.get("SUPERTONIC_CACHE_DIR")
        return Path(env) if env else paths()["supertonic"]

    def available(self) -> Tuple[bool, str]:
        try:
            import supertonic  # noqa: F401
        except Exception as e:  # noqa: BLE001
            return False, "the supertonic package is not installed (%s)" % type(e).__name__
        d = self.model_dir()
        if not (d / "onnx" / "vocoder.onnx").is_file():
            return False, "Supertonic weights missing in %s" % d
        return True, "ok"

    def prepare(self, spec: VoiceSpec) -> None:
        self.load()

    def model_id(self, spec: VoiceSpec) -> str:
        steps = os.environ.get("SHOWTIME_SUPERTONIC_STEPS", "8")
        f = self.model_dir() / "onnx" / "vocoder.onnx"
        return "supertonic3:%s:%s" % (steps, f.stat().st_size if f.is_file() else 0)

    def load(self):
        if self._tts is None:
            ok, why = self.available()
            if not ok:
                raise ShowtimeError("Supertonic is not ready: " + why, hint="run `showtime setup --with supertonic`")
            import onnxruntime
            from supertonic import TTS
            ort_telemetry_off(onnxruntime)
            thr = os.environ.get("SHOWTIME_THREADS")
            self._tts = TTS(model="supertonic-3", model_dir=self.model_dir(), auto_download=False,
                            intra_op_num_threads=int(thr) if thr and thr.isdigit() else None)
        return self._tts

    def _text(self, tokens: List[Token], lexicon, lang: str) -> str:
        parts = []
        for t in tokens:
            say = t.say or (lexicon.say(t.core, lang) if lexicon is not None else None)
            core = say or t.spoken or t.core
            parts.append(t.lead + core + t.trail)
        return " ".join(parts)

    def synth(self, tokens: List[Token], spec: VoiceSpec, speed: float, lexicon,
              sentence_pause: float = 0.3, clause_pause: float = 0.12) -> EngineResult:
        check_speed(self, speed)
        tts = self.load()
        text = self._text(tokens, lexicon, spec.lang)
        ok, bad = tts.model.text_processor.validate_text(text)
        if not ok:
            text = "".join(ch for ch in text if ch not in set(bad))
        steps = int(os.environ.get("SHOWTIME_SUPERTONIC_STEPS", "8"))
        with _lock:
            style = tts.get_voice_style(spec.name)
            wav, _dur = tts.synthesize(text, voice_style=style, total_steps=steps, speed=float(speed),
                                       lang=spec.lang.split("-")[0], silence_duration=max(0.1, sentence_pause))
        audio = np.asarray(wav, dtype=np.float32).reshape(-1)
        # trim the model's leading/trailing near-silence so lines butt together cleanly
        from ..audio_io import speech_bounds
        a, b = speech_bounds(audio, tts.sample_rate, thr_db=-50.0)
        sr = int(tts.sample_rate)
        audio = audio[max(0, int((a - 0.02) * sr)):min(len(audio), int((b + 0.06) * sr))]
        return EngineResult(audio=audio, sample_rate=sr, words=None, phonemes=None,
                            meta={"model": "supertonic-3", "steps": steps})


ENGINE = SupertonicEngine()

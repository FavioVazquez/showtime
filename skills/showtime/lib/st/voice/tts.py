"""Text to speech with word timings, for any engine.

    speech = synthesize("Meet Showtime. [pause 0.3] It lives in your terminal.",
                        voice="af_heart", speed=1.0)
    speech.duration, speech.words        # [{"text","start","end"}...] in seconds
    speech.save("vo.wav")                # + vo.words.json (transcript format)

Every result carries word timings: exact from Kokoro's durations, otherwise
from st.voice.align (ctc / tts / whisper). Results are cached by content
hash in ~/.showtime/cache/voice/tts, so re-running an unchanged line is free.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from ..common import ShowtimeError, debug, home, write_json
from . import audio_io as aio
from . import lexicon as lexmod
from . import voices
from .engines import get as get_engine
from .textnorm import normalize_tokens, plain_text, split_pauses, tokenize

PathLike = Union[str, "os.PathLike[str]"]
CACHE_VERSION = 5

# Named delivery styles: speed multiplier and pause lengths.
STYLES: Dict[str, Dict[str, float]] = {
    "neutral": {"speed": 1.0, "sentence": 0.30, "clause": 0.12},
    "calm": {"speed": 0.92, "sentence": 0.45, "clause": 0.18},
    "warm": {"speed": 0.96, "sentence": 0.38, "clause": 0.15},
    "upbeat": {"speed": 1.08, "sentence": 0.22, "clause": 0.08},
    "energetic": {"speed": 1.15, "sentence": 0.16, "clause": 0.06},
    "tutorial": {"speed": 0.94, "sentence": 0.45, "clause": 0.16},
    "documentary": {"speed": 0.95, "sentence": 0.50, "clause": 0.18},
    "trailer": {"speed": 0.9, "sentence": 0.60, "clause": 0.22},
}


@dataclass
class Speech:
    audio: np.ndarray
    sample_rate: int
    words: List[Dict[str, Any]]
    text: str
    voice: str
    engine: str
    lang: str
    speed: float
    timing: str                     # exact | ctc | tts | whisper | even
    model: str = ""
    phonemes: Optional[str] = None
    synth_seconds: float = 0.0
    cached: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return len(self.audio) / float(self.sample_rate)

    @property
    def rtf(self) -> float:
        return self.synth_seconds / max(self.duration, 1e-6)

    def transcript(self, source: Optional[str] = None) -> Dict[str, Any]:
        """Transcript-format dict (same schema as `showtime transcribe`)."""
        words = []
        for w in self.words:
            item = {"text": w["text"], "start": w["start"], "end": w["end"], "type": "word",
                    "conf": 1.0 if self.timing == "exact" else 0.9}
            if w.get("estimated"):
                item["estimated"] = True
            words.append(item)
        return {"source": source or "", "duration": round(self.duration, 3), "language": self.lang.split("-")[0],
                "model": self.model or self.engine, "voice": self.voice, "engine": self.engine,
                "speed": self.speed, "timing": self.timing, "text": plain_text(self.text), "words": words}

    def save(self, path: PathLike, words: bool = True, sr: Optional[int] = None, bits: int = 16) -> Path:
        p = Path(path)
        x, rate = self.audio, self.sample_rate
        if sr and sr != rate:
            x, rate = aio.resample(x, rate, sr), sr
        aio.write(p, x, rate, bits=bits)
        if words:
            from ..common import portable_path
            write_json(words_path(p), self.transcript(portable_path(p, p.parent)))
        return p


def words_path(wav: PathLike) -> Path:
    p = Path(wav)
    return p.with_name(p.stem + ".words.json")


def _cache_dir() -> Path:
    return home() / "cache" / "voice" / "tts"


def _key(parts: Dict[str, Any]) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:32]


def _lexicon_fingerprint(lex) -> str:
    if lex is None:
        return "-"
    items = sorted((k, json.dumps(v, sort_keys=True, ensure_ascii=False)) for k, v in
                   list(lex.folded.items()) + list(lex.exact.items()))
    return hashlib.sha256(json.dumps(items, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def _cache_load(key: str) -> Optional[Tuple[np.ndarray, int, Dict[str, Any]]]:
    d = _cache_dir()
    wav, meta = d / (key + ".wav"), d / (key + ".json")
    if not (wav.is_file() and meta.is_file()):
        return None
    try:
        import soundfile as sf
        x, sr = sf.read(str(wav), dtype="float32")
        m = json.loads(meta.read_text(encoding="utf-8"))
        for f in (wav, meta):  # least-recently-used order for pruning
            try:
                os.utime(str(f), None)
            except OSError:
                pass
        return np.asarray(x, dtype=np.float32), int(sr), m
    except Exception:  # noqa: BLE001 - a broken cache entry is just a miss
        return None


def _cache_store(key: str, x: np.ndarray, sr: int, meta: Dict[str, Any]) -> None:
    if os.environ.get("SHOWTIME_NO_CACHE") == "1":
        return
    try:
        d = _cache_dir()
        d.mkdir(parents=True, exist_ok=True)
        aio.write(d / (key + ".wav"), x, sr, bits=32)
        write_json(d / (key + ".json"), meta)
        prune_cache()
    except OSError as e:
        debug("tts cache write failed: %s" % e)


def cache_limit_bytes() -> int:
    """Size cap of the TTS cache: SHOWTIME_TTS_CACHE_MB (default 1024 MB; 0 = no cap)."""
    try:
        mb = float(os.environ.get("SHOWTIME_TTS_CACHE_MB", "1024"))
    except ValueError:
        mb = 1024.0
    return int(max(0.0, mb) * 1024 * 1024)


def cache_stats() -> Dict[str, Any]:
    d = _cache_dir()
    files = [f for f in d.glob("*") if f.is_file()] if d.is_dir() else []
    return {"dir": str(d), "entries": len([f for f in files if f.suffix == ".wav"]),
            "bytes": sum(f.stat().st_size for f in files), "limit_bytes": cache_limit_bytes()}


def prune_cache(limit: Optional[int] = None, clear: bool = False) -> Dict[str, Any]:
    """Drop least-recently-used entries until the cache is under 80 % of its cap
    (or everything with clear=True). Returns {removed, freed_bytes}."""
    d = _cache_dir()
    removed, freed = 0, 0
    if not d.is_dir():
        return {"removed": 0, "freed_bytes": 0}
    limit = cache_limit_bytes() if limit is None else int(limit)
    entries: Dict[str, List[Path]] = {}
    for f in d.iterdir():
        if f.is_file() and f.suffix in (".wav", ".json"):
            entries.setdefault(f.stem, []).append(f)
    def size(fs): return sum(x.stat().st_size for x in fs if x.exists())
    total = sum(size(fs) for fs in entries.values())
    if not clear and (limit <= 0 or total <= limit):
        return {"removed": 0, "freed_bytes": 0}
    target = 0 if clear else int(limit * 0.8)
    order = sorted(entries.items(), key=lambda kv: max(x.stat().st_mtime for x in kv[1]))
    for _key, fs in order:
        if total <= target:
            break
        n = size(fs)
        for f in fs:
            try:
                f.unlink()
            except OSError:
                pass
        total -= n
        freed += n
        removed += 1
    if removed and not clear:
        debug("tts cache pruned: %d entries, %d bytes" % (removed, freed))
    return {"removed": removed, "freed_bytes": freed}


def synthesize(text: str, voice: Optional[str] = None, speed: float = 1.0, lang: Optional[str] = None,
               engine: Optional[str] = None, lexicon=None, style: Optional[str] = None,
               align_method: str = "auto", pad: Tuple[float, float] = (0.0, 0.12),
               sentence_pause: Optional[float] = None, clause_pause: Optional[float] = None,
               use_cache: bool = True) -> Speech:
    """Synthesize `text` (with [pause] markup) and return audio + word timings.

    align_method is used only when the engine has no native timings
    ("none" leaves such words empty; used internally for references).
    """
    if not text or not plain_text(text):
        raise ShowtimeError("nothing to say: the text is empty")
    spec = voices.resolve(voice, lang, engine)
    eng = get_engine(spec.engine)
    ok, why = eng.available()
    if not ok:
        raise ShowtimeError("the %s engine is not available: %s" % (spec.engine, why),
                            hint="run `showtime setup`" + (" --with supertonic" if spec.engine == "supertonic" else ""))
    st = STYLES.get(style or "neutral")
    if st is None:
        raise ShowtimeError("unknown style %r" % style, hint="styles: " + ", ".join(STYLES))
    eff_speed = round(float(speed) * st["speed"], 4)
    sp = st["sentence"] if sentence_pause is None else float(sentence_pause)
    cp = st["clause"] if clause_pause is None else float(clause_pause)
    if lexicon is None:
        lexicon = lexmod.load()

    key = _key({"v": CACHE_VERSION, "text": text, "voice": spec.id, "engine": spec.engine, "lang": spec.lang,
                "speed": eff_speed, "sp": sp, "cp": cp, "model": eng.model_id(spec),
                "lex": _lexicon_fingerprint(lexicon), "align": align_method, "pad": list(pad)})
    if use_cache and os.environ.get("SHOWTIME_NO_CACHE") != "1":
        hit = _cache_load(key)
        if hit:
            x, sr, m = hit
            return Speech(audio=x, sample_rate=sr, words=m["words"], text=text, voice=spec.id, engine=spec.engine,
                          lang=spec.lang, speed=eff_speed, timing=m["timing"], model=m.get("model", ""),
                          phonemes=m.get("phonemes"), synth_seconds=float(m.get("synth_seconds", 0.0)),
                          cached=True, meta=m.get("meta", {}))

    eng.prepare(spec)
    t0 = time.time()
    segments = split_pauses(text)
    parts: List[np.ndarray] = []
    words: List[Dict[str, Any]] = []
    phon: List[str] = []
    sr = 0
    offset = 0.0
    timing = "exact"
    model = ""
    head, tail = pad
    engine_s = 0.0
    for seg in segments:
        if seg.text.strip():
            tokens = tokenize(seg.text)
            normalize_tokens(tokens, spec.lang)
            if not tokens:
                continue
            te = time.time()
            res = eng.synth(tokens, spec, eff_speed, lexicon, sentence_pause=sp, clause_pause=cp)
            engine_s += time.time() - te
            if sr and res.sample_rate != sr:
                res.audio = aio.resample(res.audio, res.sample_rate, sr)
            sr = sr or res.sample_rate
            model = res.meta.get("model", model)
            seg_words = res.words
            if seg_words is not None:
                from .align import refine_onsets, snap
                seg_words = snap(seg_words, res.audio, sr, grow=False, trim_starts=False)
                seg_words = refine_onsets(seg_words, res.audio, sr)
            elif align_method != "none":
                from .align import align_audio
                seg_words, used = align_audio(res.audio, sr, plain_text(seg.text), spec.lang, align_method,
                                              voice=None)
                timing = used if timing == "exact" else timing
            else:
                timing = "none"
                seg_words = []
            for w in seg_words:
                w = dict(w)
                w["start"] = round(w["start"] + offset + head, 3)
                w["end"] = round(w["end"] + offset + head, 3)
                words.append(w)
            if res.phonemes:
                phon.append(res.phonemes)
            parts.append(aio.fade(res.audio, sr))
            offset += len(res.audio) / float(sr)
        if seg.pause_after:
            if not sr:
                sr = 24000
            parts.append(aio.silence(seg.pause_after, sr))
            offset += seg.pause_after
    if not parts or not sr:
        raise ShowtimeError("nothing to say: the text has no pronounceable words")
    audio = np.concatenate([aio.silence(head, sr)] + parts + [aio.silence(tail, sr)]).astype(np.float32)
    dt = time.time() - t0
    speech = Speech(audio=audio, sample_rate=sr, words=words, text=text, voice=spec.id, engine=spec.engine,
                    lang=spec.lang, speed=eff_speed, timing=timing, model=model,
                    phonemes=" | ".join(phon) if phon else None, synth_seconds=dt,
                    meta={"engine_seconds": round(engine_s, 3), "align_seconds": round(max(0.0, dt - engine_s), 3)})
    if use_cache and timing != "none":
        _cache_store(key, audio, sr, {"words": words, "timing": timing, "model": model, "phonemes": speech.phonemes,
                                      "synth_seconds": dt, "voice": spec.id, "created": time.time(),
                                      "meta": speech.meta})
    return speech


def fit_to(text: str, target: float, voice: Optional[str] = None, speed: float = 1.0, tolerance: float = 0.08,
           **kw) -> Speech:
    """Synthesize, then re-synthesize at an adjusted speed so the speech
    lasts about `target` seconds (speed clamped to the engine's range and to
    0.8-1.25x of the requested speed so the delivery stays natural)."""
    sp = synthesize(text, voice=voice, speed=speed, **kw)
    spec = voices.resolve(voice, kw.get("lang"), kw.get("engine"))
    lo, hi = get_engine(spec.engine).speed_range
    cur = speed
    for _ in range(3):
        err = sp.duration / max(target, 0.1)
        if abs(err - 1.0) <= tolerance:
            break
        new = min(max(cur * err, lo, speed * 0.8), hi, speed * 1.25)
        if abs(new - cur) < 1e-3:
            break
        cur = new
        sp = synthesize(text, voice=voice, speed=cur, **kw)
    return sp


def measure_rate(speech: Speech) -> Dict[str, float]:
    """Words per second / minute of a synthesized result (speech time only)."""
    n = len(speech.words)
    if not n:
        return {"words": 0, "wps": 0.0, "wpm": 0.0}
    span = speech.words[-1]["end"] - speech.words[0]["start"]
    return {"words": n, "wps": round(n / max(span, 1e-3), 3), "wpm": round(60.0 * n / max(span, 1e-3), 1)}


def batch(lines: Sequence[str], **kw) -> List[Speech]:
    return [synthesize(t, **kw) for t in lines]

"""Word-level, verbatim, local transcription.

Engines
  parakeet   NVIDIA Parakeet-TDT 0.6B int8 through sherpa-onnx (the default):
             v3 covers 25 European languages (English, Spanish, ...), v2 is
             English only. Verbatim: "um"/"uh" come out as words, no text
             normalisation. Fetched on first use (~490 MB, asr_models.py).
             Long files are chunked on pauses (Silero VAD, energy fallback).
  whisper    faster-whisper (CTranslate2, int8 on CPU): large-v3-turbo ("turbo"),
             small / small.en / base / medium ... for the languages Parakeet
             lacks, or when asked for. Word timestamps, a filler-preserving
             initial prompt, Silero VAD.
  crisper    CrisperWhisper 2.0 (opt-in "max accuracy", non-commercial weights,
             PyTorch; see crisper.py).

Pipeline per file: probe -> pick the audio track -> 16 kHz mono WAV (cached;
the dry narration stem instead when showtime mixed the file itself, or the
separated vocals when speech sits under loud music) -> refuse silent tracks
-> ASR -> token merge -> hallucination guards -> filler gap scan (fillers.py)
-> energy snap of word edges (refine.py) -> optional diarization and audio
events -> transcript JSON. Results are cached per (source content hash,
track, options), so re-running is instant unless the media changed.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import platform as plat
from ..common import ShowtimeError, debug, info, paths, read_json, warn, write_json
from . import TRANSCRIPT_VERSION
from . import util as U
from .asr_models import PARAKEET_V3_LANGS

ENGINE_REV = 6   # bump when the output of the pipeline changes (invalidates caches)

MODELS: Dict[str, Tuple[str, str]] = {
    "turbo": ("whisper", "large-v3-turbo"),
    "large-v3-turbo": ("whisper", "large-v3-turbo"),
    "large-v3": ("whisper", "large-v3"),
    "medium": ("whisper", "medium"),
    "medium.en": ("whisper", "medium.en"),
    "small": ("whisper", "small"),
    "small.en": ("whisper", "small.en"),
    "base": ("whisper", "base"),
    "base.en": ("whisper", "base.en"),
    "tiny.en": ("whisper", "tiny.en"),
    "parakeet": ("parakeet", "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"),
    "parakeet-v2": ("parakeet", "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"),
    "parakeet-v3": ("parakeet", "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"),
    "crisper": ("crisper", "small"),
    "crisper-small": ("crisper", "small"),
    "crisper-medium": ("crisper", "medium"),
    "crisper-turbo": ("crisper", "turbo"),
    "crisper-large": ("crisper", "large"),
}
PARAKEET_ITEMS = {"sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8": "parakeet-v2",
                  "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8": "parakeet-v3"}
HF_REPOS = {
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "large-v3": "Systran/faster-whisper-large-v3",
    "medium": "Systran/faster-whisper-medium", "medium.en": "Systran/faster-whisper-medium.en",
    "small": "Systran/faster-whisper-small", "small.en": "Systran/faster-whisper-small.en",
    "base": "Systran/faster-whisper-base", "base.en": "Systran/faster-whisper-base.en",
    "tiny.en": "Systran/faster-whisper-tiny.en",
}
SETUP_EXTRA = {"large-v3-turbo": "asr-turbo", "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8": "parakeet",
               "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8": "parakeet-v3"}
# Rough CPU cost (seconds of processing per second of audio on 6 cores, idle machine).
COST = {"large-v3-turbo": 0.45, "large-v3": 1.2, "medium": 0.6, "medium.en": 0.6, "small": 0.25, "small.en": 0.22,
        "base": 0.1, "base.en": 0.1, "tiny.en": 0.05, "parakeet": 0.18}   # parakeet: ASR + filler gap scan

# Disfluent example text that nudges Whisper to write fillers verbatim.
FILLER_PROMPTS = {
    "en": "Umm, let me think like, hmm... Okay, here's what I'm, like, thinking. Uh, so, um, yeah.",
    "es": "Eh, bueno, este... mmm, o sea, déjame pensar. Eh, entonces, pues, sí.",
    "fr": "Euh, bon, alors... hmm, tu vois, genre, euh, je pense que, ben, oui.",
    "de": "Ähm, also, na ja... hmm, sozusagen, äh, ich denke, ähm, ja.",
    "pt": "Hum, então, tipo... é, sabe, ahn, eu acho que, né, sim.",
    "it": "Ehm, allora, cioè... mmm, tipo, ehm, secondo me, ecco, sì.",
}
SPACELESS_LANGS = {"zh", "ja", "th", "lo", "my", "km", "yue", "bo"}
HALLUCINATION_PHRASES = [
    "thank you", "thanks for watching", "thank you for watching", "subtitles by", "please subscribe",
    "amara.org", "like and subscribe", "see you next time", "bye", "you",
]
_NONSPEECH = re.compile(r"^[\s♪♫♬#*~\-_.…]+$")
_BRACKET = re.compile(r"^[\[(（【]\s*([^\])）】]{1,40})\s*[\])）】]$")
_EVENT_NAMES = {"laughter": "laughter", "laughs": "laughter", "laughing": "laughter", "laugh": "laughter",
                "applause": "applause", "clapping": "applause", "music": "music", "cough": "cough",
                "coughs": "cough", "sighs": "sigh", "sigh": "sigh", "cheering": "cheering", "silence": None,
                "blank_audio": None, "inaudible": None, "no speech": None, "noise": None, "crosstalk": None}

_MODEL_CACHE: Dict[str, Any] = {}

# Seconds to load a model into memory on a 6-core CPU (the fixed cost of each run, paid before
# any audio is processed; shown so a short clip does not look hung).
LOAD_SECONDS = {"large-v3-turbo": 35, "large-v3": 60, "medium": 25, "medium.en": 25, "small": 8, "small.en": 8,
                "base": 3, "base.en": 3, "tiny": 2, "tiny.en": 2, "parakeet": 10}


def load_seconds(engine: str, name: str) -> int:
    """Rough model-load time (s) for the first transcription of a run."""
    if engine == "parakeet":
        return LOAD_SECONDS["parakeet"]
    return LOAD_SECONDS.get(os.path.basename(str(name)), 20)


def _announce_load(engine: str, name: str) -> float:
    info("loading model %s (first run can take ~%ds)" % (os.path.basename(str(name)), load_seconds(engine, name)))
    return time.time()


# --------------------------------------------------------------------------
# Model resolution
# --------------------------------------------------------------------------

def _whisper_dir(name: str) -> Path:
    return paths()["whisper"] / name


def _installed(engine: str, name: str) -> bool:
    if engine == "whisper":
        return (_whisper_dir(name) / "model.bin").is_file()
    return (paths()["sherpa"] / name / "encoder.int8.onnx").is_file()


def default_model() -> str:
    """The --model used for 'auto' (SHOWTIME_ASR_MODEL overrides it, e.g. turbo)."""
    return (os.environ.get("SHOWTIME_ASR_MODEL") or "parakeet").strip()


def choose_model(model: str, language: Optional[str]) -> Tuple[str, str]:
    """(engine, model name) for a --model value.

    'auto': Parakeet-TDT v3 (verbatim, keeps fillers; 25 European languages)
    unless the language is outside them, then Whisper: turbo when installed,
    else small (fetched on first use)."""
    m = (model or "auto").strip()
    lang = (language or "").split("-")[0].lower() or None
    if m == "auto":
        pick = default_model()
        if pick != "auto" and pick in MODELS and MODELS[pick][0] != "parakeet":
            return choose_model(pick, language)
        if lang is None or lang in PARAKEET_V3_LANGS:
            eng, name = MODELS.get(pick, MODELS["parakeet"]) if pick in MODELS else MODELS["parakeet"]
            if name.endswith("v2-int8") and lang not in (None, "en"):
                name = MODELS["parakeet-v3"][1]
            return eng, name
        if _installed("whisper", "large-v3-turbo"):
            info("language %r is outside Parakeet's 25; using Whisper large-v3-turbo" % lang)
            return MODELS["turbo"]
        info("language %r is outside Parakeet's 25; using Whisper small (for better accuracy: "
             "`showtime setup --with asr-turbo`)" % lang)
        return MODELS["small"]
    if m in MODELS:
        eng, name = MODELS[m]
    elif Path(m).expanduser().is_dir():
        return ("whisper", str(Path(m).expanduser().resolve()))
    else:
        raise ShowtimeError("unknown model %r" % model,
                            hint="choose auto, turbo, small, small.en, base.en, medium, parakeet or parakeet-v3")
    if eng == "whisper" and name.endswith(".en") and lang and lang != "en":
        alt = name[:-3]
        warn("%s is English-only; using the multilingual %s for language %r" % (name, alt, lang))
        name = alt
    if eng == "parakeet" and lang:
        ok_langs = PARAKEET_V3_LANGS if name.endswith("v3-int8") else {"en"}
        if lang not in ok_langs:
            raise ShowtimeError("%s does not support language %r" % (m, lang),
                                hint="use --model turbo (99 languages)" + (" or parakeet-v3 (25 European languages)"
                                                                          if lang in PARAKEET_V3_LANGS else ""))
    return eng, name


def _ensure_whisper(name: str) -> Path:
    from .. import lazy
    if os.path.isabs(name):
        lazy.ensure_asr("whisper", "*")
        return Path(name)
    d = _whisper_dir(name)
    lazy.ensure_asr("whisper", name)          # engine + pinned model on first use (announced, resumable)
    if (d / "model.bin").is_file():
        return d
    repo = HF_REPOS.get(name)
    if not repo:
        raise ShowtimeError("whisper model %r is not installed" % name)
    if name in SETUP_EXTRA:
        hint_setup = "`showtime setup --with %s`" % SETUP_EXTRA[name]
    else:
        hint_setup = None
    info("downloading whisper model %s (first use only, %s) into %s" % (
        name, {"large-v3-turbo": "~1.6 GB", "small": "~480 MB", "medium": "~1.5 GB", "base": "~150 MB",
               "large-v3": "~3 GB"}.get(name.replace(".en", ""), "a few hundred MB"), d))
    try:
        from huggingface_hub import snapshot_download
        tmp = d.with_name(d.name + ".part")
        snapshot_download(repo, local_dir=str(tmp),
                          allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*",
                                          "preprocessor_config.json"])
        if d.exists():
            shutil.rmtree(d)
        os.replace(str(tmp), str(d))
    except Exception as e:  # noqa: BLE001
        # unpinned sizes come straight from Hugging Face (no model mirror): name the mirrored default
        blocked = re.search(r"\b(403|407)\b|Tunnel connection failed|ProxyError", str(e))
        hint = ("Hugging Face is blocked here and this size has no mirror: use --model small.en (pinned, it falls "
                "back to the showtime model mirror) or allow huggingface.co in the sandbox's network settings"
                if blocked else ("run %s" % hint_setup) if hint_setup else "check your network connection")
        raise ShowtimeError("could not download whisper model %s: %s" % (name, e), hint=hint)
    return d


def _whisper_model(name: str, threads: int):
    key = "w:%s:%d" % (name, threads)
    if key not in _MODEL_CACHE:
        d = _ensure_whisper(name)
        from faster_whisper import WhisperModel
        device = os.environ.get("SHOWTIME_ASR_DEVICE", "cpu")
        compute = os.environ.get("SHOWTIME_ASR_COMPUTE", "int8" if device == "cpu" else "float16")
        t0 = _announce_load("whisper", name)
        _MODEL_CACHE[key] = WhisperModel(str(d), device=device, compute_type=compute, cpu_threads=threads,
                                         num_workers=1)
        info("model %s loaded in %.1fs" % (os.path.basename(str(name)), time.time() - t0))
    return _MODEL_CACHE[key]


def _parakeet_model(name: str, threads: int):
    key = "p:%s:%d" % (name, threads)
    if key not in _MODEL_CACHE:
        d = paths()["sherpa"] / name
        if not (d / "encoder.int8.onnx").is_file():
            # fetched on first use (announced with its size, resumable, sha256-verified): st/lazy.py
            from . import asr_models
            d = asr_models.ensure(PARAKEET_ITEMS.get(name, "parakeet-v3"), "transcription")
        import sherpa_onnx
        t0 = _announce_load("parakeet", name)
        _MODEL_CACHE[key] = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(d / "encoder.int8.onnx"), decoder=str(d / "decoder.int8.onnx"),
            joiner=str(d / "joiner.int8.onnx"), tokens=str(d / "tokens.txt"), num_threads=threads,
            model_type="nemo_transducer", decoding_method="greedy_search")
        info("model %s loaded in %.1fs" % (name, time.time() - t0))
    return _MODEL_CACHE[key]


# --------------------------------------------------------------------------
# Engines -> raw tokens [{"raw": str, "start", "end", "conf"?, "seg": int}]
# --------------------------------------------------------------------------

def _progress(duration: float, enabled: bool = True):
    """Progress over seconds of audio (`transcribing 12/64  18%  3.1 s/s  ETA 17 s`)."""
    from ..common import Progress
    return Progress(total=max(1.0, float(duration)), label="transcribing (s of audio)", unit="s/s",
                    enabled=enabled)


def _run_whisper(wav: Path, audio, name: str, language: Optional[str], prompt: Optional[str], vad: bool,
                 threads: int, duration: float, progress: bool = True) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    model = _whisper_model(name, threads)
    lang = language
    lang_prob = None
    multilingual = not name.endswith(".en")
    if lang is None and multilingual:
        try:
            lang, lang_prob, _ = model.detect_language(audio=audio, vad_filter=True, language_detection_segments=2)
            debug("detected language %s (p=%.2f)" % (lang, lang_prob))
        except Exception as e:  # noqa: BLE001 - fall back to in-transcribe detection
            debug("language detection failed: %s" % e)
            lang = None
    if not multilingual:
        lang = "en"
    base_prompt = FILLER_PROMPTS.get((lang or "en").split("-")[0]) if prompt != "" else None
    full_prompt = " ".join(x for x in (base_prompt, prompt if prompt else None) if x) or None
    kw: Dict[str, Any] = dict(language=lang, task="transcribe", beam_size=5, word_timestamps=True,
                              condition_on_previous_text=False, initial_prompt=full_prompt,
                              temperature=[0.0, 0.2, 0.4, 0.6, 0.8, 1.0], no_speech_threshold=0.6,
                              compression_ratio_threshold=2.4, log_prob_threshold=-1.0)
    if vad:
        kw.update(vad_filter=True, vad_parameters={"min_silence_duration_ms": 500, "speech_pad_ms": 300,
                                                   "threshold": 0.4})
    else:
        kw.update(hallucination_silence_threshold=2.0)
    segments, info_ = model.transcribe(audio, **kw)
    toks: List[Dict[str, Any]] = []
    with _progress(duration, enabled=progress) as pr:
        for si, seg in enumerate(segments):
            for w in seg.words or []:
                toks.append({"raw": w.word, "start": float(w.start), "end": float(w.end),
                             "conf": round(float(w.probability), 3), "seg": si})
            pr.set(min(float(seg.end), duration))
        pr.set(duration)
    meta = {"language": info_.language or lang, "language_probability":
            round(float(lang_prob if lang_prob is not None else (info_.language_probability or 0.0)), 3),
            "prompt": bool(full_prompt)}
    return toks, meta


def vad_spans(audio, sr: int, max_len: float = 30.0, min_silence: float = 0.3,
              threshold: float = 0.45) -> Optional[List[Tuple[float, float]]]:
    """Silero VAD speech spans in seconds, or None when the VAD model is missing/fails."""
    vad_model = paths()["sherpa"] / "silero_vad_v5.onnx"
    if not vad_model.is_file():
        return None
    dur = len(audio) / float(sr)
    spans: List[Tuple[float, float]] = []
    try:
        import numpy as np
        import sherpa_onnx
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = str(vad_model)
        cfg.silero_vad.threshold = threshold
        cfg.silero_vad.min_silence_duration = min_silence
        cfg.silero_vad.min_speech_duration = 0.1
        cfg.silero_vad.max_speech_duration = max_len
        cfg.sample_rate = sr
        cfg.num_threads = 1
        vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=int(dur) + 30)
        ws = cfg.silero_vad.window_size
        a = np.ascontiguousarray(audio, dtype=np.float32)
        for i in range(0, len(a) - ws + 1, ws):
            vad.accept_waveform(a[i:i + ws])
        vad.flush()
        while not vad.empty():
            f = vad.front
            spans.append((f.start / sr, (f.start + len(f.samples)) / sr))
            vad.pop()
    except Exception as e:  # noqa: BLE001
        debug("VAD failed (%s)" % e)
        return None
    return spans


def chunk_seconds() -> float:
    """Longest ASR chunk (s). Parakeet keeps more fillers with some context; 30 s by default."""
    try:
        return max(5.0, float(os.environ.get("SHOWTIME_ASR_CHUNK") or 30.0))
    except ValueError:
        return 30.0


def _speech_chunks(audio, sr: int, max_len: Optional[float] = None,
                   spans: Optional[List[Tuple[float, float]]] = None) -> List[Tuple[float, float]]:
    """Split long audio on pauses: Silero VAD when installed, else energy minima."""
    max_len = max_len or chunk_seconds()
    dur = len(audio) / float(sr)
    if dur <= max_len + 5:
        return [(0.0, dur)]
    if spans is None:
        spans = vad_spans(audio, sr, max_len=max_len) or []
    if not spans:
        db = U.frame_db(audio, sr, 0.05)
        cuts, t = [0.0], 0.0
        while dur - t > max_len + 2:
            lo, hi = int((t + max_len * 0.7) / 0.05), int((t + max_len) / 0.05)
            k = lo + int(db[lo:hi].argmin()) if hi > lo else hi
            t = k * 0.05
            cuts.append(t)
        cuts.append(dur)
        return list(zip(cuts[:-1], cuts[1:]))
    # merge VAD spans into chunks up to max_len, padded by 0.3 s
    chunks: List[Tuple[float, float]] = []
    for s, e in spans:
        s, e = max(0.0, s - 0.3), min(dur, e + 0.3)
        if chunks and e - chunks[-1][0] <= max_len and s - chunks[-1][1] < 1.5:
            chunks[-1] = (chunks[-1][0], e)
        else:
            chunks.append((s, e))
    return chunks


def parakeet_decoder(name: str, threads: int, sr: int = 16000):
    """decode(list of float32 arrays) -> per array [(piece, start_s, dur_s)] with the loaded model."""
    import numpy as np
    rec = _parakeet_model(name, threads)

    def decode(arrays):
        out = []
        for b0 in range(0, len(arrays), 16):
            streams = []
            for x in arrays[b0:b0 + 16]:
                st = rec.create_stream()
                x = np.ascontiguousarray(x, dtype=np.float32)
                if len(x) < sr // 10:
                    x = np.concatenate([x, np.zeros(sr // 10 - len(x), np.float32)])
                st.accept_waveform(sr, x)
                streams.append(st)
            rec.decode_streams(streams)
            for st in streams:
                r = st.result
                durs = list(getattr(r, "durations", []) or [])
                out.append([(t, float(t0), float(durs[i]) if i < len(durs) and durs[i] > 0 else 0.08)
                            for i, (t, t0) in enumerate(zip(r.tokens, r.timestamps))])
        return out
    return decode


def _run_parakeet(audio, sr: int, name: str, threads: int,
                  spans: Optional[List[Tuple[float, float]]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    import numpy as np
    rec = _parakeet_model(name, threads)
    chunks = _speech_chunks(audio, sr, spans=spans)
    toks: List[Dict[str, Any]] = []
    batch = 6
    duration = len(audio) / float(sr)
    pr = _progress(duration)
    for b0 in range(0, len(chunks), batch):
        part = chunks[b0:b0 + batch]
        streams = []
        for s, e in part:
            st = rec.create_stream()
            st.accept_waveform(sr, np.ascontiguousarray(audio[int(s * sr): int(e * sr)], dtype=np.float32))
            streams.append(st)
        rec.decode_streams(streams)
        for ci, ((s, e), st) in enumerate(zip(part, streams)):
            r = st.result
            tk, ts = list(r.tokens), list(r.timestamps)
            durs = list(getattr(r, "durations", []) or [])
            for i, (t, t0) in enumerate(zip(tk, ts)):
                d = durs[i] if i < len(durs) and durs[i] > 0 else 0.08
                raw = t.replace("▁", " ")
                toks.append({"raw": raw, "start": s + float(t0), "end": s + float(t0) + float(d), "seg": b0 + ci})
        pr.set(min(part[-1][1], duration))
    pr.set(duration)
    pr.close()
    return toks, {"language": "en" if name.endswith("v2-int8") else None, "chunks": len(chunks)}


def _guess_language(words: List[Dict[str, Any]]) -> Optional[str]:
    """en / es / None from common function words (Parakeet v3 does not report the language)."""
    en = {"the", "and", "to", "of", "a", "is", "that", "it", "we", "you", "i", "in", "was", "this", "for"}
    es = {"el", "la", "de", "que", "y", "en", "los", "las", "un", "una", "es", "por", "con", "para", "se", "lo"}
    b = [U.bare(w["text"]) for w in words if w.get("type") == "word"]
    ne, ns = sum(1 for x in b if x in en), sum(1 for x in b if x in es)
    if ne + ns < 5:
        return None
    return "en" if ne >= 2 * ns else ("es" if ns >= 2 * ne else None)


# --------------------------------------------------------------------------
# Token -> word normalisation
# --------------------------------------------------------------------------

_PUNCT_ONLY = re.compile(r"^[\.,!?;:'\"\)\]\}>…–—¡¿\-、。，！？：”’»]+$")
_CONTRACTION = re.compile(r"(?i)^'(t|m|s|ve|re|ll|d)$")


def merge_tokens(toks: List[Dict[str, Any]], lang: Optional[str], subword: bool = False) -> List[Dict[str, Any]]:
    """Glue sub-word pieces into words: a piece with no leading space in the
    same ASR segment ('90' + '%'), bare punctuation, or a contraction suffix.

    subword=True (sentencepiece engines such as Parakeet): the tokenizer's
    word-start marker is authoritative, so pieces glue regardless of timing;
    a bare marker token (' ') starts a new word at the next piece."""
    spaceless = (lang or "").split("-")[0] in SPACELESS_LANGS
    out: List[Dict[str, Any]] = []
    boundary = False
    for t in toks:
        raw = t["raw"]
        core = raw.strip()
        if not core:
            boundary = True
            continue
        starts_word = raw[:1].isspace() or boundary
        boundary = False
        glue = False
        if out and out[-1]["seg"] == t["seg"]:
            if _PUNCT_ONLY.match(core) or _CONTRACTION.match(core):
                glue = True
            elif not spaceless and not starts_word and (subword or t["start"] - out[-1]["end"] < 0.25):
                glue = True
        if glue:
            p = out[-1]
            p["text"] += core
            if not _PUNCT_ONLY.match(core):
                # punctuation pieces carry late timestamps (a '.' seconds into the next pause)
                p["end"] = max(p["end"], t["end"])
            if "conf" in t and "conf" in p:
                p["conf"] = round(min(p["conf"], t["conf"]), 3)
            continue
        w = {"text": core, "start": t["start"], "end": t["end"], "seg": t["seg"]}
        if "conf" in t:
            w["conf"] = t["conf"]
        out.append(w)
    # rejoin 'C' + 'aught' style fragments (single capital + lowercase word, same segment, touching)
    fixed: List[Dict[str, Any]] = []
    for w in out:
        if (fixed and re.fullmatch(r"[B-HJ-NP-Z]", fixed[-1]["text"]) and re.match(r"[a-z]", w["text"])
                and fixed[-1]["seg"] == w["seg"] and w["start"] - fixed[-1]["end"] < 0.05):
            fixed[-1]["text"] += w["text"]
            fixed[-1]["end"] = w["end"]
            continue
        fixed.append(w)
    return fixed


def classify(words: List[Dict[str, Any]], report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Mark bracketed tokens as audio events, drop non-speech glyph tokens."""
    out = []
    nonspeech = 0
    for w in words:
        t = w["text"]
        m = _BRACKET.match(t)
        if m:
            name = m.group(1).strip().lower().replace(" ", "_")
            key = name.replace("_", " ") if name.replace("_", " ") in _EVENT_NAMES else name
            ev = _EVENT_NAMES.get(key, name.replace("_", " "))
            if ev is None:
                nonspeech += 1
                continue
            out.append({"text": "(%s)" % ev, "start": w["start"], "end": w["end"], "type": "audio_event",
                        "seg": w["seg"]})
            continue
        if _NONSPEECH.match(t):
            nonspeech += 1
            if "♪" in t or "♫" in t:
                out.append({"text": "(music)", "start": w["start"], "end": w["end"], "type": "audio_event",
                            "seg": w["seg"]})
            continue
        w["type"] = "word"
        out.append(w)
    total = len(words)
    if total and nonspeech / total > 0.2:
        report["warnings"].append("%.0f%% of tokens were non-speech (music or noise?): the transcript may be "
                                  "unreliable; try --model turbo" % (100.0 * nonspeech / total))
    return out


# --------------------------------------------------------------------------
# Guards against hallucinated text
# --------------------------------------------------------------------------

def guard(words: List[Dict[str, Any]], audio, sr: int, duration: float, report: Dict[str, Any]) -> List[Dict[str, Any]]:
    import numpy as np
    hop = 0.01
    db = U.frame_db(audio, sr, hop)
    thr, _floor, _peak = U.voice_threshold(db)
    voiced = db > thr
    nf = len(voiced)
    dropped = report["dropped"]

    def voiced_in(a: float, b: float) -> float:
        i, j = max(0, int(a / hop)), min(nf, max(int(a / hop) + 1, int(math.ceil(b / hop))))
        return float(voiced[i:j].mean()) if j > i else 0.0

    # speech end (last voiced run >= 50 ms)
    idx = np.flatnonzero(voiced)
    speech_end = 0.0
    if len(idx):
        runs = np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)
        long_runs = [r for r in runs if len(r) >= 5]
        speech_end = ((long_runs[-1][-1] + 1) * hop) if long_runs else (idx[-1] + 1) * hop

    kept: List[Dict[str, Any]] = []
    for w in words:
        s = max(0.0, min(float(w["start"]), duration))
        e = max(s, min(float(w["end"]), duration))
        w["start"], w["end"] = s, e
        if w.get("type") == "audio_event":
            kept.append(w)
            continue
        near = voiced_in(s - 0.3, e + 0.3)
        own = voiced_in(s, e)
        low_conf = w.get("conf", 1.0) < 0.4
        phrase = U.bare(w["text"]) in HALLUCINATION_PHRASES
        reason = None
        if near == 0.0:
            reason = "no speech energy"
        elif s > speech_end + 0.5:
            reason = "after the audible end"
        elif own < 0.05 and (low_conf or phrase):
            reason = "silence + low confidence"
        if reason:
            dropped.append({"text": w["text"], "start": round(s, 3), "reason": reason})
            continue
        kept.append(w)

    # repetition loops ("the the the the the", or a phrase repeated 4+ times)
    kept = _drop_loops(kept, dropped)

    # zero / inverted durations: spread runs evenly between neighbours
    toks = [w for w in kept if w.get("type") == "word"]
    i = 0
    while i < len(toks):
        if toks[i]["end"] - toks[i]["start"] >= 0.02:
            i += 1
            continue
        j = i
        while j < len(toks) and toks[j]["end"] - toks[j]["start"] < 0.02:
            j += 1
        a = toks[i - 1]["end"] if i else max(0.0, toks[i]["start"] - 0.3 * (j - i))
        b = toks[j]["start"] if j < len(toks) else min(duration, a + 0.3 * (j - i))
        if b - a < 0.02 * (j - i):
            b = a + 0.05 * (j - i)
        step = (b - a) / (j - i)
        for k in range(i, j):
            toks[k]["start"], toks[k]["end"] = a + step * (k - i), a + step * (k - i + 1)
            toks[k]["estimated"] = True
        report["respread"] += j - i
        i = j
    low = [w for w in toks if w.get("conf", 1.0) < 0.35]
    report["low_confidence"] = len(low)
    return kept


def _drop_loops(words: List[Dict[str, Any]], dropped: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    toks = [U.bare(w["text"]) for w in words]
    remove = set()
    n_tok = len(toks)
    for n in (1, 2, 3, 4):
        min_reps = 5 if n == 1 else 4
        i = 0
        while i + n <= n_tok:
            gram = toks[i:i + n]
            if not all(gram):
                i += 1
                continue
            reps = 1
            j = i + n
            while j + n <= n_tok and toks[j:j + n] == gram:
                reps += 1
                j += n
            if reps >= min_reps:
                for k in range(i + 2 * n, j):
                    remove.add(k)
                i = j
            else:
                i += 1
    out = []
    for k, w in enumerate(words):
        if k in remove:
            dropped.append({"text": w["text"], "start": round(w["start"], 3), "reason": "repetition loop"})
        else:
            out.append(w)
    return out


# --------------------------------------------------------------------------
# Main entry
# --------------------------------------------------------------------------

def dry_stem(src: Path) -> Optional[Tuple[Path, float, str]]:
    """(speech-only stem, offset s, what) when showtime rendered `src` itself with music under the speech.

    - an edit render (`edit render`) writes <video>.report.json whose audio.speech_stem is the program
      audio before the music bed (same timeline);
    - a motion/voiced render writes render.json (next to the video or in work/) and its mixer writes
      work/audio/mix.voice.wav, the narration before any music (offset = the rendered range's start).
    None when there is no such report, the stem is gone, or the report is about another file."""
    def same(a: Any) -> bool:
        try:
            return Path(str(a)).expanduser().resolve() == src
        except (OSError, ValueError):
            return False
    rep = src.with_name(src.stem + ".report.json")
    if rep.is_file():
        try:
            d = read_json(rep)
        except ShowtimeError:
            d = {}
        st_ = ((d.get("audio") or {}).get("speech_stem")) if same(d.get("output")) else None
        if st_ and Path(st_).is_file():
            return Path(st_), 0.0, "the edit's speech before the music bed"
    cands = [src.parent / "render.json", src.parent / "work" / "render.json",
             src.parent / (src.stem + ".work") / "render.json"]          # render -o <file>: <file stem>.work/
    cands += [up / "work" / "renders" / (src.stem + ".work") / "render.json" for up in list(src.parents)[:4]]
    for cand in cands:
        if not cand.is_file():
            continue
        try:
            d = read_json(cand)
        except ShowtimeError:
            continue
        if not same(d.get("output")):
            continue
        stem = d.get("voice_stem")
        if not stem and d.get("log"):
            stem = Path(str(d["log"])).parent.parent / "audio" / "mix.voice.wav"
        if stem and Path(str(stem)).is_file():
            off = float((d.get("range") or [0.0])[0] or 0.0)
            return Path(str(stem)), off, "the narration before the music was mixed in"
    return None


def _cache_key(qh: str, track: int, engine: str, name: str, language: Optional[str], opts: Dict[str, Any]) -> str:
    blob = json.dumps({"qh": qh, "t": track, "e": engine, "m": os.path.basename(name), "l": language,
                       "o": opts, "rev": ENGINE_REV, "v": TRANSCRIPT_VERSION}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def transcribe(media, *, model: str = "auto", language: Optional[str] = None, speakers: Optional[str] = None,
               events: str = "auto", audio_track: int = 0, vad: bool = True, refine: bool = True,
               prompt: Optional[str] = None, edit_dir=None, force: bool = False, threads: Optional[int] = None,
               out_path=None, start: Optional[float] = None, end: Optional[float] = None, gap_scan: bool = True,
               accept_license: bool = False, use_stem: bool = True,
               separate: str = "auto") -> Tuple[Dict[str, Any], Path]:
    """Transcribe one media file. Returns (transcript, written path).

    start/end (seconds) transcribe only that part of the file: word times stay on the source's timeline
    (offset by `start`), the transcript records "range": [start, end] and its "duration" is `end`, so cuts
    planned from it drop everything outside the range. Range transcripts are cached per range and written
    as <name>.<start>-<end>.json next to the full one."""
    src = Path(media).expanduser().resolve()
    if not src.is_file():
        raise ShowtimeError("file not found: %s" % src)
    pr = U.probe(src)
    if not pr.get("has_audio"):
        raise ShowtimeError("%s has no audio track to transcribe" % src.name)
    n_tracks = len(pr.get("audio_streams") or [])
    if audio_track < 0 or audio_track >= n_tracks:
        raise ShowtimeError("audio track %d does not exist in %s (it has %d)" % (audio_track, src.name, n_tracks),
                            hint="tracks are numbered from 0")
    rng = _range(start, end, float(pr.get("duration") or 0.0), src.name)
    lang = (language or "").strip().lower() or None
    engine, name = choose_model(model, lang)
    if engine == "crisper":
        from . import crisper
        crisper.check(accept_license)      # platform + licence, before any work
    threads = threads or int(os.environ.get("SHOWTIME_THREADS") or 0) or plat.cpu_count()
    spk = None if speakers in (None, "", "1", 1) else str(speakers)
    ev_mode = events
    if events == "auto":
        from . import events as E
        ev_mode = "on" if E.available()[0] else "off"
    if separate not in ("auto", "on", "off"):
        raise ShowtimeError("--separate must be auto, on or off (got %r)" % separate)
    opts = {"vad": vad, "refine": refine, "prompt": prompt, "speakers": spk, "events": ev_mode, "sep": separate,
            "gap": bool(gap_scan and engine == "parakeet")}
    if engine == "parakeet":
        opts["chunk"] = chunk_seconds()
    if rng:
        opts["range"] = [round(rng[0], 3), round(rng[1], 3)]
    qh = U.quick_hash(src)
    stem = dry_stem(src) if (audio_track == 0 and use_stem) else None
    if stem:
        opts["stem"] = U.quick_hash(stem[0])
    key = _cache_key(qh, audio_track, engine, name, lang, opts)
    edit = Path(edit_dir) if edit_dir else U.default_edit_dir(src, create_job=not out_path)
    dst = Path(out_path) if out_path else U.transcript_path(edit, src, audio_track)
    if rng and not out_path:
        dst = dst.with_name("%s.%s-%s.json" % (dst.stem, _stamp(rng[0]), _stamp(rng[1])))
    cached = U.cache_dir("transcripts") / (key + ".json")
    if not force:
        for cand in (dst, cached):
            if cand.is_file():
                try:
                    doc = read_json(cand)
                except ShowtimeError:
                    continue
                if doc.get("cache_key") == key and doc.get("words") is not None:
                    doc["source"] = str(src)
                    if cand != dst:
                        write_json(dst, doc)
                    info("%s: cached transcript (%d words) -> %s" % (src.name, len(U.words_of(doc)), dst))
                    return doc, dst

    if stem:
        info("%s: transcribing %s (%s) instead of the final mix, so speech under the music is not missed"
             % (src.name, stem[2], stem[0].name))
        s0 = stem[1] + (rng[0] if rng else 0.0)
        dur_ = (rng[1] - rng[0]) if rng else float(pr.get("duration") or 0.0)
        wav = U.cache_dir("transcripts") / ("%s.stem%s.%s-%s.16k.wav" % (qh, opts["stem"][:8], _stamp(s0), _stamp(dur_)))
        if not wav.is_file():
            U.extract_wav(stem[0], wav, sr=16000, start=s0 if s0 > 0 else None, duration=dur_ or None)
    elif rng:
        wav = U.cache_dir("transcripts") / ("%s.t%d.%s-%s.16k.wav" % (qh, audio_track, _stamp(rng[0]), _stamp(rng[1])))
        if not wav.is_file():
            U.extract_wav(src, wav, sr=16000, track=audio_track, start=rng[0], duration=rng[1] - rng[0])
    else:
        wav = U.cache_dir("transcripts") / ("%s.t%d.16k.wav" % (qh, audio_track))
        if not wav.is_file():
            U.extract_wav(src, wav, sr=16000, track=audio_track)
    audio, sr = U.load_audio(wav, sr=16000)
    duration = len(audio) / float(sr)
    sep_info: Optional[Dict[str, Any]] = None
    if separate != "off" and not stem:
        from . import separate as S
        sep_info = S.music_likely(audio, sr, vad_spans(audio, sr))
        if separate == "on" or sep_info["separate"]:
            voc = wav.with_name(wav.stem + ".vocals.wav")
            if separate == "on":
                sep_info["why"] = "asked for (--separate on)"
            info("%s: %s; separating the voice first (UVR MDX-Net)" % (src.name, sep_info["why"]))
            if not voc.is_file():
                S.separate_wav(wav, voc, threads=threads)
            v_audio, _ = U.load_audio(voc, sr=16000)
            during = S.speech_time_snr_db(audio, v_audio, sr)
            sep_info["speech_time_snr_db"] = during
            if separate == "auto" and during is not None and during >= S.SNR_GATE_DB:
                # the bed is loud only between phrases (ducked under the voice): separating would only
                # add artefacts to clean speech
                sep_info["applied"] = False
                sep_info["why"] += ", but under the speech itself it is %.1f dB down (ducked): kept the " \
                                   "original audio" % during
                info("%s: the music is ducked under the speech (%.1f dB); transcribing the original audio"
                     % (src.name, during))
            else:
                wav, audio = voc, v_audio
                sep_info["applied"] = True
        else:
            sep_info["applied"] = False
    levels = U.audio_levels(audio, sr)
    if levels["peak_db"] < -60 or levels["active_ratio"] < 0.003:
        others = ""
        if n_tracks > 1:
            others = " This file has %d audio tracks; try --audio-track %s." % (
                n_tracks, " or ".join(str(i) for i in range(n_tracks) if i != audio_track))
        where = (" between %s and %s" % (U.fmt_time(rng[0]), U.fmt_time(rng[1]))) if rng else ""
        raise ShowtimeError("audio track %d of %s is silent%s (peak %.1f dBFS): nothing to transcribe.%s" % (
            audio_track, src.name, where, levels["peak_db"], others))

    est = duration * COST.get("parakeet" if engine == "parakeet" else name.split("/")[-1], 0.5) * 6.0 / max(1, threads)
    if ("w:%s:%d" % (name, threads) if engine == "whisper" else "p:%s:%d" % (name, threads)) not in _MODEL_CACHE:
        est += load_seconds(engine, name)
    if engine == "parakeet":
        # fetch before the estimate line: a first run downloads the model (announced with its size)
        _parakeet_model(name, threads)
    if est > 30:
        info("transcribing %s (%s of audio) with %s; estimated %s" % (
            src.name, U.fmt_time(duration), os.path.basename(name), U.fmt_time(est)))
    t0 = time.time()
    report: Dict[str, Any] = {"dropped": [], "warnings": [], "respread": 0}
    spans = vad_spans(audio, sr, max_len=chunk_seconds()) if engine == "parakeet" else None
    if engine == "whisper":
        toks, meta = _run_whisper(wav, audio, name, lang, prompt, vad, threads, duration)
    elif engine == "crisper":
        from . import crisper
        toks, meta = crisper.run(wav, name, lang, threads, accept_license=accept_license)
    else:
        toks, meta = _run_parakeet(audio, sr, name, threads, spans=spans)
    asr_seconds = time.time() - t0
    det_lang = meta.get("language") or lang or "en"
    words = merge_tokens(toks, det_lang, subword=(engine in ("parakeet",)))
    if engine == "parakeet" and not meta.get("language") and not lang:
        det_lang = _guess_language(words) or "en"
    words = classify(words, report)
    words = guard(words, audio, sr, duration, report)
    stats: Dict[str, Any] = {}
    if sep_info is not None:
        stats["separation"] = sep_info
    if opts["gap"] and words:
        from . import fillers as F
        t_gap = time.time()
        fine = vad_spans(audio, sr, max_len=chunk_seconds(), min_silence=0.1, threshold=0.4)
        g = F.scan(words, audio, sr, det_lang, parakeet_decoder(name, threads, sr), vad_spans=fine)
        stats["gap_scan"] = {k: g[k] for k in ("candidates", "elongated", "added", "widened", "added_acoustic", "missed_words", "skipped",
                                                "asr_fillers", "asr_fillers_checked") if k in g}
        stats["gap_scan"]["seconds"] = round(time.time() - t_gap, 2)
        report["gap_events"] = g["events"]
        if g["added"]:
            info("%s: filler scan added %d filler(s) the ASR missed" % (src.name, g["added"]))
    if refine and words:
        from .refine import snap_words
        stats["refine"] = snap_words(words, audio, sr)
    extra_events: List[Dict[str, Any]] = []
    if ev_mode == "on":
        from . import events as E
        try:
            extra_events = E.detect(audio, sr, threads=min(4, threads))
            E.merge_into(words, extra_events)
        except ShowtimeError as e:
            report["warnings"].append(str(e))
    if spk:
        from . import diarize as D
        n = None if spk in ("auto", "0") else int(spk)
        segs = D.diarize(audio, sr, num_speakers=n, threads=min(4, threads))
        stats["diarize"] = D.assign(words, segs)
    else:
        for w in words:
            if w.get("type") != "spacing":
                w.setdefault("speaker", "S0")
    off = rng[0] if rng else 0.0
    for w in words:
        w.pop("seg", None)
        # ASR ran on the range's audio: move every time onto the source's timeline
        w["start"], w["end"] = round(float(w["start"]) + off, 3), round(float(w["end"]) + off, 3)
    if off:
        for d in report["dropped"]:
            if "start" in d:
                d["start"] = round(float(d["start"]) + off, 3)
    words = U.add_spacing(words)
    U.ensure_ids(words)
    word_list = [w for w in words if w.get("type") == "word"]
    fillers = sum(1 for w in word_list if U.is_filler(w["text"], det_lang))
    if not word_list:
        report["warnings"].append("no speech was recognised")
    doc: Dict[str, Any] = {
        "source": str(src), "duration": round(off + duration, 3), "language": det_lang,
        "language_probability": meta.get("language_probability"),
        "model": os.path.basename(name),
        "engine": {"whisper": "faster-whisper", "crisper": "crisperwhisper"}.get(engine, "sherpa-onnx"),
        "audio_track": audio_track, "text": _plain_text(word_list), "version": TRANSCRIPT_VERSION,
        "cache_key": key, "source_hash": qh, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "asr_seconds": round(asr_seconds, 2),
        "stats": dict(stats, words=len(word_list), fillers=fillers, events=len([w for w in words if w.get("type") == "audio_event"]),
                      low_confidence=report.get("low_confidence", 0), respread=report["respread"], levels=levels),
        "guards": {"dropped": report["dropped"], "warnings": report["warnings"]},
        "filler_scan": report.get("gap_events"),
        "audio_from": (str(stem[0]) if stem else ("separated vocals" if sep_info and sep_info.get("applied")
                                                   else "source")),
        "words": words,
    }
    if rng:
        doc["range"] = [round(rng[0], 3), round(rng[0] + duration, 3)]
    write_json(cached, doc)
    write_json(dst, doc)
    for w_ in report["warnings"]:
        warn("%s: %s" % (src.name, w_))
    if report["dropped"]:
        info("%s: dropped %d likely-hallucinated token(s) (see guards.dropped)" % (src.name, len(report["dropped"])))
    info("%s%s: %d words (%d fillers), %s, language %s, %s in %.1fs -> %s" % (
        src.name, (" %s-%s" % (U.fmt_time(rng[0]), U.fmt_time(rng[1]))) if rng else "", len(word_list), fillers, U.fmt_time(duration), det_lang, os.path.basename(name),
        time.time() - t0, dst))
    return doc, dst


def _range(start: Optional[float], end: Optional[float], total: float, name: str) -> Optional[Tuple[float, float]]:
    """(start, end) in seconds for a partial transcription, or None for the whole file."""
    if start is None and end is None:
        return None
    s = max(0.0, float(start or 0.0))
    e = float(end) if end is not None else total
    if total and s >= total:
        raise ShowtimeError("--from %s is past the end of %s (%s)" % (U.fmt_time(s), name, U.fmt_time(total)))
    if total:
        e = min(e, total)
    if e - s < 0.5:
        raise ShowtimeError("the range %s-%s of %s is empty or shorter than half a second" % (
            U.fmt_time(s), U.fmt_time(e), name), hint="--from must be before --to (seconds or mm:ss)")
    if s <= 0.0 and total and e >= total - 0.01:
        return None   # the whole file: share the full transcript and its cache
    return s, e


def _stamp(t: float) -> str:
    """Seconds as a file-name part: 90 -> 90, 12.5 -> 12.5."""
    return ("%.2f" % t).rstrip("0").rstrip(".")


def _plain_text(words: List[Dict[str, Any]]) -> str:
    return " ".join(w["text"] for w in words)


def transcribe_many(items: Sequence, **kw) -> List[Tuple[Dict[str, Any], Path]]:
    files = U.collect_media(items)
    if not files:
        raise ShowtimeError("no media files found", hint="pass video/audio files or a folder")
    out = []
    failures = []
    for f in files:
        try:
            out.append(transcribe(f, **kw))
        except ShowtimeError as e:
            if len(files) == 1:
                raise
            failures.append((f, str(e)))
            warn("%s: %s" % (f.name, e))
    if failures and not out:
        raise ShowtimeError("every file failed to transcribe")
    return out

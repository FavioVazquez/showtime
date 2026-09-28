"""Audio events (laughter, applause, music, ...) with the CED-mini AudioSet
tagger through sherpa-onnx. Produces transcript entries of type
'audio_event' with text like "(laughter)".

Rule: a class group fires when its best class probability is at or above
its threshold in >= 2 consecutive 2 s windows (1 s hop), or once at twice
the threshold. Music needs 3 windows (speech alone rarely scores high on it).

Model: ~/.showtime/models/sherpa/sherpa-onnx-ced-mini-audio-tagging-2024-04-19/
(`showtime setup --with events`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..common import ShowtimeError, paths
from .. import platform as plat

GROUPS: Dict[str, Dict[str, Any]] = {
    "laughter": {"classes": ["Laughter", "Belly laugh", "Snicker", "Giggle", "Chuckle, chortle", "Baby laughter"],
                 "thr": 0.25, "min_windows": 2},
    "applause": {"classes": ["Applause", "Clapping"], "thr": 0.3, "min_windows": 2},
    "cheering": {"classes": ["Cheering", "Crowd"], "thr": 0.35, "min_windows": 2},
    "music": {"classes": ["Music", "Musical instrument", "Singing"], "thr": 0.45, "min_windows": 3},
    "cough": {"classes": ["Cough", "Throat clearing"], "thr": 0.3, "min_windows": 1},
    "sigh": {"classes": ["Sigh"], "thr": 0.3, "min_windows": 1},
    "crying": {"classes": ["Crying, sobbing"], "thr": 0.35, "min_windows": 2},
}


def model_dir() -> Path:
    return paths()["sherpa"] / "sherpa-onnx-ced-mini-audio-tagging-2024-04-19"


def available() -> Tuple[bool, str]:
    d = model_dir()
    if not (d / "class_labels_indices.csv").is_file() or not any((d / f).is_file() for f in ("model.int8.onnx", "model.onnx")):
        return False, "CED-mini model not installed"
    try:
        import sherpa_onnx  # noqa: F401
    except ImportError as e:
        return False, "sherpa-onnx not importable (%s)" % e
    return True, ""


def detect(audio, sr: int, window: float = 2.0, hop: Optional[float] = None,
           groups: Optional[List[str]] = None, threads: Optional[int] = None) -> List[Dict[str, Any]]:
    """[{"text": "(laughter)", "start", "end", "type": "audio_event", "conf"}]."""
    ok, why = available()
    if not ok:
        raise ShowtimeError("audio event tagging is not installed (%s)" % why, hint="run `showtime setup --with events`")
    import numpy as np
    import sherpa_onnx
    d = model_dir()
    model = d / "model.int8.onnx" if (d / "model.int8.onnx").is_file() else d / "model.onnx"
    at = sherpa_onnx.AudioTagging(sherpa_onnx.AudioTaggingConfig(
        model=sherpa_onnx.AudioTaggingModelConfig(ced=str(model), num_threads=threads or max(1, min(4, plat.cpu_count()))),
        labels=str(d / "class_labels_indices.csv"), top_k=25))
    dur = len(audio) / float(sr)
    if hop is None:
        hop = 1.0 if dur <= 600 else 2.0
    want = {g: GROUPS[g] for g in (groups or GROUPS) if g in GROUPS}
    starts = [float(v) for v in np.arange(0.0, max(dur - window, 0.0) + 1e-6, hop)] or [0.0]
    probs: Dict[str, List[float]] = {g: [] for g in want}
    for st in starts:
        a = audio[int(st * sr): int((st + window) * sr)]
        if len(a) < sr * 0.5:
            for g in want:
                probs[g].append(0.0)
            continue
        s = at.create_stream()
        s.accept_waveform(sr, np.ascontiguousarray(a, dtype=np.float32))
        res = {e.name: float(e.prob) for e in at.compute(s)}
        for g, spec in want.items():
            probs[g].append(max([res.get(c, 0.0) for c in spec["classes"]] or [0.0]))
    events: List[Dict[str, Any]] = []
    for g, spec in want.items():
        p = probs[g]
        i = 0
        while i < len(p):
            if p[i] < spec["thr"]:
                i += 1
                continue
            j = i
            while j + 1 < len(p) and p[j + 1] >= spec["thr"]:
                j += 1
            n = j - i + 1
            peak = max(p[i:j + 1])
            if n >= spec["min_windows"] or peak >= 2 * spec["thr"]:
                a = starts[i] + (0.5 if n > 1 else 0.0)
                b = min(dur, starts[j] + window - (0.5 if n > 1 else 0.0))
                events.append({"text": "(%s)" % g, "start": round(a, 3), "end": round(max(b, a + 0.3), 3),
                               "type": "audio_event", "conf": round(peak, 3)})
            i = j + 1
    events.sort(key=lambda e: e["start"])
    return events


def merge_into(words: List[Dict[str, Any]], events: List[Dict[str, Any]], drop_overlapping_music: bool = True) -> int:
    """Insert events into a transcript word list (time-ordered). Existing
    events of the same kind that overlap are kept once. Returns the count added."""
    have = [(w["text"], w["start"], w["end"]) for w in words if w.get("type") == "audio_event"]
    added = 0
    for ev in events:
        if any(t == ev["text"] and min(e, ev["end"]) > max(s, ev["start"]) for t, s, e in have):
            continue
        words.append(ev)
        added += 1
    words.sort(key=lambda w: (w["start"], w.get("type") == "spacing"))
    return added

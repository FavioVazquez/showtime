"""Snap ASR word edges to the audio energy envelope.

Whisper's attention-based word times start early and often run into the
following pause; transducer (Parakeet) ends overshoot. Both are off by
0.2-0.5 s exactly where editors cut. This pass works on 10 ms RMS frames:

1. trim unvoiced frames inside each word span;
2. grow the start backwards over voiced frames (<= 150 ms, never before the
   previous word's end);
3. grow the end forwards over voiced frames (<= 250 ms, never past the next
   word's start).

The voiced threshold is relative to both the peak and the noise floor
(see util.voice_threshold), so it works on studio audio and noisy rooms.
Words keep a minimum length of 50 ms. Audio events are left untouched.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .util import frame_db, voice_threshold

HOP = 0.01


def snap_words(words: List[Dict[str, Any]], audio, sr: int, *, grow_start: float = 0.15, grow_end: float = 0.25,
               min_len: float = 0.05, threshold_db: Optional[float] = None) -> Dict[str, Any]:
    """Refine `words` (dicts with start/end; type 'word') in place.

    Returns stats: {"moved": n, "mean_shift_ms": x, "threshold_db": t}.
    """
    import numpy as np
    db = frame_db(audio, sr, HOP)
    thr = threshold_db if threshold_db is not None else voice_threshold(db)[0]
    voiced = db > thr
    nf = len(voiced)
    toks = [w for w in words if w.get("type", "word") == "word"]
    toks.sort(key=lambda w: w["start"])
    shifts = []
    orig = [(w["start"], w["end"]) for w in toks]
    # fillers the gap scan added already carry decoder-bounded spans: trimming them to the loudest
    # frames would shrink a quiet "uh" to a sliver (they still bound their neighbours below)
    fixed = [bool(w.get("detected")) for w in toks]

    def fr(t: float) -> int:
        return max(0, min(nf, int(round(t / HOP))))

    # pass 1: trim + grow starts
    for i, w in enumerate(toks):
        if fixed[i]:
            continue
        s, e = float(w["start"]), float(w["end"])
        a, b = fr(s), max(fr(s) + 1, fr(e))
        seg = voiced[a:b]
        if seg.any():
            idx = np.flatnonzero(seg)
            s2, e2 = (a + idx[0]) * HOP, (a + idx[-1] + 1) * HOP
        else:
            s2, e2 = s, e
        prev_end = toks[i - 1]["end"] if i else 0.0
        k = fr(s2)
        limit = max(prev_end, s2 - grow_start)
        while k - 1 >= 0 and voiced[k - 1] and (k - 1) * HOP >= limit - 1e-9:
            k -= 1
        s2 = min(s2, k * HOP)
        w["start"] = s2
        w["end"] = max(e2, s2 + min_len)
    # pass 2: grow ends
    for i, w in enumerate(toks):
        if fixed[i]:
            continue
        nxt = toks[i + 1]["start"] if i + 1 < len(toks) else nf * HOP
        k = fr(w["end"])
        limit = min(nxt, w["end"] + grow_end)
        while k < nf and voiced[k] and (k + 1) * HOP <= limit + 1e-9:
            k += 1
        e = max(w["end"], k * HOP)
        if nxt > w["start"]:
            e = min(e, nxt)
        w["start"], w["end"] = round(w["start"], 3), round(max(e, w["start"] + 0.01), 3)
    for (s0, e0), w in zip(orig, toks):
        d = abs(w["start"] - s0) + abs(w["end"] - e0)
        if d > 0.005:
            shifts.append(d / 2)
    return {"moved": len(shifts), "words": len(toks),
            "mean_shift_ms": round(1000 * (sum(shifts) / len(shifts)), 1) if shifts else 0.0,
            "threshold_db": round(float(thr), 1)}


def snap_file(transcript: Dict[str, Any], wav_path, **kw) -> Dict[str, Any]:
    from .util import load_audio
    x, sr = load_audio(wav_path, sr=16000)
    return snap_words(transcript["words"], x, sr, **kw)

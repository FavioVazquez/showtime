"""Fit music to an exact length: loop on bar lines or trim to a musical ending.

- Longer than needed: keep the start, end after the last downbeat that leaves
  room for a short decay, fade over that decay, and pad to the exact length.
- Shorter than needed: repeat a bar-aligned loop region (head + n x body +
  outro) with short equal-power crossfades at the joins, then trim to length.
- Without a reliable beat grid (ambient, rubato) the loop points fall back to
  10 % / 90 % of the track with a long (1.5 s) crossfade.

- ending="song": trim by splicing the track's own last bars (its cadence and final hit) in at a
  downbeat, so a long track cut short still ends as written.

Beat information comes from a beats.json (composer or `audio beats`); when
none is given, the track is analysed on the fly.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from . import SR, dsp


def shift_beats(beats_doc: Optional[dict], offset: float) -> Optional[dict]:
    """The beat grid of a source that starts `offset` s later (its first `offset` s skipped)."""
    if not beats_doc or not offset:
        return beats_doc
    d = dict(beats_doc)
    for k in ("beats", "downbeats", "onsets"):
        if isinstance(d.get(k), list):
            d[k] = [round(float(t) - offset, 4) for t in d[k] if isinstance(t, (int, float)) and float(t) - offset >= 0]
    if isinstance(d.get("sections"), list):
        secs = []
        for sc in d["sections"]:
            if isinstance(sc, dict) and float(sc.get("end", 0)) - offset > 0:
                secs.append(dict(sc, start=round(max(0.0, float(sc.get("start", 0)) - offset), 3),
                                 end=round(float(sc["end"]) - offset, 3)))
        d["sections"] = secs
    if d.get("end_hit") is not None:
        eh = float(d["end_hit"]) - offset
        d["end_hit"] = round(eh, 3) if eh >= 0 else None
    if d.get("duration"):
        d["duration"] = round(max(0.0, float(d["duration"]) - offset), 3)
    return d


def snap_to_downbeat(beats_doc: Optional[dict], t: float) -> float:
    """The downbeat nearest to t (t itself when the grid is unknown)."""
    db, ok = _grid(beats_doc)
    if not ok or not db:
        return t
    return min(db, key=lambda x: abs(x - t))


def _grid(beats_doc: Optional[dict]) -> Tuple[list, bool]:
    if not beats_doc:
        return [], False
    db = [float(t) for t in (beats_doc.get("downbeats") or [])]
    ok = bool(beats_doc.get("rhythmic", True)) and len(db) >= 4
    return db, ok


def loop_points(duration: float, beats_doc: Optional[dict]) -> Dict[str, float]:
    """Choose (start, end, xfade) for a loop body inside a track of `duration` seconds."""
    db, ok = _grid(beats_doc)
    if ok:
        db = [t for t in db if t < duration - 0.05]
        # skip the intro (first ~15 %) and the outro (last ~15 %), keep whole groups of 4 bars if possible
        cands_s = [t for t in db if t >= 0.12 * duration] or db[:1]
        cands_e = [t for t in db if t <= 0.88 * duration] or db[-1:]
        s = cands_s[0]
        idx_s = db.index(s)
        best = None
        for e in reversed(cands_e):
            bars = db.index(e) - idx_s
            if bars >= 2:
                score = (bars % 4 == 0) * 10 + bars
                if best is None or score > best[0]:
                    best = (score, e)
        if best:
            return {"start": s, "end": best[1], "xfade": 0.03, "musical": True}
    return {"start": 0.1 * duration, "end": 0.9 * duration, "xfade": min(1.5, 0.1 * duration), "musical": False}


def _bar_of(db: list, t: float) -> Dict:
    """Where a cut at downbeat `t` falls: bars played before it and whether it closes a 4-bar phrase
    (counted from the first downbeat; a heuristic: most pop and library tracks phrase in 4s)."""
    i = min(range(len(db)), key=lambda k: abs(db[k] - t))
    bars = i                            # whole bars from the first downbeat to the cut
    return {"bars": bars, "phrase_end": bars % 4 == 0,
            "phrase_note": None if bars % 4 == 0 else
            "ends mid-phrase (%d bar%s into a 4-bar phrase); --ending song splices in the track's own ending"
            % (bars % 4, "" if bars % 4 == 1 else "s")}


def _song_ending(x: np.ndarray, target: float, db: list, ending_bars: int = 2, xfade: float = 0.05,
                 end_hit: Optional[float] = None) -> Tuple[Optional[np.ndarray], Dict]:
    """The track's own last `ending_bars` bars (its cadence and final hit) spliced in at a downbeat so the
    track ends as written, exactly `target` long (the ending's ring-out is kept; silence pads the rest)."""
    dur = len(x) / SR
    for k in range(ending_bars, 0, -1):
        if len(db) < k + 2:
            continue
        e = db[-k]
        tail_len = dur - e
        if tail_len >= target - 1.0:
            continue
        want = target - tail_len
        cands = [d for d in db if 1.0 <= d <= want + 1e-6 and d < e]
        if not cands:
            continue
        d = cands[-1]
        head = x[: int(round(d * SR))]
        tail = x[int(round(e * SR)):]
        y = dsp.crossfade_concat(head, tail, xfade)
        y = y[: int(round(target * SR))]
        if len(y) >= int(round(target * SR)) - 1:
            y = dsp.fade(y, 0.0, 0.05)
        out = {"ending": "song", "splice_at": round(d, 3), "ending_from": round(e, 3), "ending_bars": k}
        if end_hit is not None and float(end_hit) > e:
            out["end_hit"] = round(d + float(end_hit) - e, 3)      # the final hit on the output timeline
        return y, out
    return None, {"note": "the track has no usable ending of whole bars for this length; ended on a downbeat instead"}


def fit(x: np.ndarray, target: float, beats_doc: Optional[dict] = None, fade_out: Optional[float] = None,
        ending: str = "auto") -> Tuple[np.ndarray, Dict]:
    """Return (audio of exactly `target` seconds, info)."""
    x = dsp.to_stereo(x)
    N = int(round(target * SR))
    dur = len(x) / SR
    info: Dict = {"source_duration": round(dur, 3), "target": round(target, 3)}
    if dur >= target - 1e-3:
        y = x[:N]
        db, ok = _grid(beats_doc)
        fo = fade_out if fade_out is not None else min(2.0, max(0.3, 0.08 * target))
        if dur - target < 0.05:
            info.update(mode="trim", fade_out=0.0)
            return dsp.pad_to(y, N), info
        if ok and ending == "song":
            y, sinfo = _song_ending(x, target, db, end_hit=beats_doc.get("end_hit") if beats_doc else None)
            if y is not None:
                info.update(mode="trim", **sinfo)
                return dsp.pad_to(y, N), info
            info["note"] = sinfo.get("note")
        if ok and ending in ("auto", "downbeat", "song"):
            # end on a downbeat, then decay into silence before the target
            cands = [t for t in db if t <= target - 0.4]
            if cands:
                d = cands[-1]
                if target - d > 2 * fo + 1.0:
                    d = target - fo
                y = dsp.pad_to(x[: int(round(d * SR))], int(round(d * SR)))
                tail = x[int(round(d * SR)): int(round(d * SR)) + int(round((target - d) * SR))]
                tail = dsp.fade(tail, 0.0, max(0.05, (target - d)))
                y = dsp.pad_to(np.concatenate([y, tail]), N)
                info.update(mode="trim", ending="downbeat", ends_at=round(d, 3), **_bar_of(db, d))
                return y, info
        y = dsp.fade(y, 0.0, fo)
        info.update(mode="trim", ending="fade", fade_out=round(fo, 3))
        return dsp.pad_to(y, N), info
    lp = loop_points(dur, beats_doc)
    s, e, xf = lp["start"], lp["end"], lp["xfade"]
    si, ei = int(round(s * SR)), int(round(e * SR))
    if ei - si < SR * 0.5:
        si, ei, xf = 0, len(x), 0.05
    head = x[:ei]
    body = x[si:ei]
    outro = x[si:]
    out = head
    reps = 0
    while len(out) + (len(outro) - (ei - si)) < N and reps < 1000:
        out = dsp.crossfade_concat(out, body, xf) if xf > 0.001 else np.concatenate([out, body])
        reps += 1
    # finish with the outro so the track ends like it was written to (after the last body)
    tail = x[ei:]
    out = dsp.crossfade_concat(out, tail, xf) if len(tail) else out
    if len(out) > N:
        fo = fade_out if fade_out is not None else min(2.0, max(0.3, 0.06 * target))
        out = dsp.fade(out[:N], 0.0, fo)
    info.update(mode="loop", loop_start=round(s, 3), loop_end=round(e, 3), repeats=reps, xfade=xf,
                musical=lp["musical"])
    return dsp.pad_to(out, N), info

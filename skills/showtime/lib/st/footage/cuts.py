"""Transcript cut algebra: decide which parts of a take to keep.

Removals can be combined freely:
  - fillers         um / uh / erm ... (bare, case-folded match per language, plus
                    words the filler scan marked "filler": true); extra words or
                    phrases ("o sea") on request
  - word ids        "w12-w18", "w40"
  - time ranges     (3.2, 4.0)
  - long silences   gaps between kept words longer than `max_pause` are
                    shortened to `keep_pause` (half kept on each side)

Where fillers were cut, the pause left behind is capped at `filler_pause`
(0.2 s: 0.1 s each side). strict_fillers keeps the fillers whose isolated
re-decode did not confirm them ("checked": false). With the source audio (`snap_audio`), every cut
edge moves to the quietest 10 ms within +-40 ms, never into a kept word.

Cuts never land inside a kept word. Each kept word is padded (default 50 ms
before, 80 ms after; clamped to 30-200 ms) so plosives and breaths are not
clipped, but padding never re-admits a removed word. Kept pieces shorter
than `min_keep` that contain no word are dropped; pieces closer than
`min_cut` are merged (tiny cuts only add clicks).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ..common import ShowtimeError
from . import util as U


def _clamp_pad(v: float) -> float:
    return max(0.03, min(0.2, float(v)))


def parse_word_ids(spec: Iterable[str], words: List[Dict[str, Any]]) -> Set[str]:
    """'w12-w18', 'w40', '12-18' -> set of ids present in `words`."""
    order = [w["id"] for w in words if w.get("id")]
    pos = {wid: i for i, wid in enumerate(order)}
    out: Set[str] = set()
    for item in spec:
        for part in str(item).split(","):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"^w?(\d+)(?:\s*-\s*w?(\d+))?$", part)
            if not m:
                raise ShowtimeError("invalid word range %r (use w12-w18 or w40)" % part)
            a = "w%s" % m.group(1)
            b = "w%s" % (m.group(2) or m.group(1))
            if a not in pos or b not in pos:
                raise ShowtimeError("word id %s not in the transcript" % (a if a not in pos else b))
            i, j = sorted((pos[a], pos[b]))
            out.update(order[i:j + 1])
    return out


def plan_keep(transcript: Dict[str, Any], *, fillers: bool = True, extra_fillers: Sequence[str] = (),
              remove_ids: Iterable[str] = (), remove_times: Sequence[Tuple[float, float]] = (),
              keep_times: Optional[Sequence[Tuple[float, float]]] = None,
              max_pause: Optional[float] = None, keep_pause: float = 0.3,
              pad_before: float = 0.05, pad_after: float = 0.08, lead: float = 0.15, tail: float = 0.35,
              min_keep: float = 0.2, min_cut: float = 0.06, keep_events: bool = True,
              guard: float = 0.04, filler_pause: float = 0.2, snap_audio: Optional[Tuple[Any, int]] = None,
              snap_radius: float = 0.04, strict_fillers: bool = False) -> Dict[str, Any]:
    """Return {"keep": [(s, e)], "removed": [{"text","start","end","why"}], "before": dur, "after": dur}."""
    lang = transcript.get("language") or "en"
    duration = float(transcript.get("duration") or 0.0)
    toks = [w for w in transcript.get("words", []) if w.get("type") in ("word", "audio_event")]
    toks.sort(key=lambda w: w["start"])
    if not toks:
        raise ShowtimeError("the transcript has no words to cut by")
    if duration <= 0:
        duration = max(w["end"] for w in toks)
    pad_before, pad_after = _clamp_pad(pad_before), _clamp_pad(pad_after)
    ids = parse_word_ids(remove_ids, toks) if remove_ids else set()
    extra = {U.bare(x) for x in extra_fillers if len(str(x).split()) == 1}
    phrases = [[U.bare(p) for p in str(x).split()] for x in extra_fillers if len(str(x).split()) > 1]
    phrase_hit: Set[int] = set()
    if fillers and phrases:
        bw = [U.bare(w["text"]) if w.get("type") == "word" else None for w in toks]
        for ph in phrases:
            for i in range(len(toks) - len(ph) + 1):
                if bw[i:i + len(ph)] == ph:
                    phrase_hit.update(range(i, i + len(ph)))

    removed_why: Dict[int, str] = {}
    for i, w in enumerate(toks):
        why = None
        if w.get("id") in ids:
            why = "word range"
        elif fillers and w.get("type") == "word" and (U.is_filler(w["text"], lang, extra) or w.get("filler")
                                                       or i in phrase_hit) \
                and not (strict_fillers and w.get("checked") is False):
            why = "filler"
        elif w.get("type") == "audio_event" and not keep_events:
            why = "event"
        else:
            mid = (w["start"] + w["end"]) / 2
            if any(a <= mid <= b for a, b in remove_times):
                why = "time range"
            elif keep_times is not None and not any(a <= mid <= b for a, b in keep_times):
                why = "outside keep"
        if why:
            removed_why[i] = why

    kept_idx = [i for i in range(len(toks)) if i not in removed_why]
    if not kept_idx:
        raise ShowtimeError("every word would be removed; nothing left to keep")

    # Cut intervals between consecutive kept tokens.
    cuts: List[Tuple[float, float]] = []
    first, last = toks[kept_idx[0]], toks[kept_idx[-1]]
    head_end = max(0.0, first["start"] - max(lead, pad_before))
    if head_end > 0.0:
        cuts.append((0.0, head_end))
    for a_i, b_i in zip(kept_idx, kept_idx[1:]):
        a, b = toks[a_i], toks[b_i]
        between = [toks[k] for k in range(a_i + 1, b_i)]
        gap_s, gap_e = a["end"], b["start"]
        if gap_e <= gap_s:
            continue  # overlapping timestamps: any cut here would clip a kept word
        half = keep_pause / 2.0
        if between and all(removed_why.get(k) == "filler" for k in range(a_i + 1, b_i)):
            half = min(half, filler_pause / 2.0)
        if between:
            # Remove the words in between; keep up to keep_pause of the
            # surrounding silence (half on each side) so the join breathes.
            rs = min(w["start"] for w in between)
            re_ = max(w["end"] for w in between)
            # guard: removed words (fillers especially) have soft onsets/tails that
            # word timings miss, so the cut reaches a little beyond them
            s = max(gap_s, min(gap_s + max(pad_after, half), rs - guard))
            e = min(gap_e, max(gap_e - max(pad_before, half), re_ + guard))
            if e - s > min_cut:
                cuts.append((s, e))
        elif max_pause is not None and gap_e - gap_s > max_pause:
            s = gap_s + max(half, pad_after)
            e = gap_e - max(half, pad_before)
            if e - s > min_cut:
                cuts.append((s, e))
    tail_start = min(duration, last["end"] + max(tail, pad_after))
    if tail_start < duration:
        cuts.append((tail_start, duration))
    for a, b in remove_times:
        cuts.append((max(0.0, a), min(duration, b)))

    keep = invert(cuts, duration)
    # never cut inside a kept word: re-add any kept word span a time-range cut clipped
    spans = [(toks[i]["start"], toks[i]["end"]) for i in kept_idx]
    keep = _merge(keep + [(s, e) for s, e in spans if not _covered(s, e, keep) and not
                          any(a <= (s + e) / 2 <= b for a, b in remove_times)])
    # drop slivers without words, merge pieces separated by tiny cuts
    keep = [(s, e) for s, e in keep if e - s >= min_keep or any(s <= x <= e for x, _ in spans)]
    merged: List[Tuple[float, float]] = []
    for s, e in keep:
        if merged and s - merged[-1][1] < min_cut:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    snapped = 0
    if snap_audio is not None and len(merged) > 1:
        from .fillers import snap_edges
        merged, snapped = snap_edges(merged, snap_audio[0], snap_audio[1], [toks[i] for i in kept_idx],
                                     radius=snap_radius)
    removed = [{"id": toks[i].get("id"), "text": toks[i]["text"], "start": toks[i]["start"],
                "end": toks[i]["end"], "why": why} for i, why in sorted(removed_why.items())]
    after = sum(e - s for s, e in merged)
    return {"keep": [(round(s, 3), round(e, 3)) for s, e in merged], "removed": removed,
            "before": round(duration, 3), "after": round(after, 3), "cuts": max(0, len(merged) - 1),
            "snapped_edges": snapped}


def invert(cuts: List[Tuple[float, float]], duration: float) -> List[Tuple[float, float]]:
    cuts = _merge([(max(0.0, a), min(duration, b)) for a, b in cuts if b > a])
    keep, t = [], 0.0
    for a, b in cuts:
        if a > t:
            keep.append((t, a))
        t = max(t, b)
    if t < duration:
        keep.append((t, duration))
    return keep


def _merge(iv: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    out: List[Tuple[float, float]] = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1] + 1e-6:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _covered(s: float, e: float, iv: List[Tuple[float, float]]) -> bool:
    return any(a <= s + 1e-6 and e <= b + 1e-6 for a, b in iv)

"""Find the fillers a transcript missed, and check the ones it has.

A verbatim ASR (Parakeet) writes most "um"/"uh" as words, but it still drops
some, mostly short ones right after a sentence end or folded into the tail of
the previous word. This module runs after ASR, on the raw word times:

1. voiced mask: 10 ms frames above the noise-relative energy threshold, and
   inside Silero VAD speech when the VAD model is present;
2. gap scan: voiced runs of 150-800 ms (gaps under 50 ms bridged) that no
   word covers are candidates;
3. each candidate (and each filler the ASR wrote) is decoded again on its own,
   in a short window. The window's words decide it:
     - a filler (um/uh/erm/hmm/mm, per language) inside the region -> filler;
     - a real word inside it -> a missed word: never cut, reported only;
     - nothing -> the acoustic check decides (voiced, steady spectrum,
       pitched like a held vowel); only a clear pass becomes a filler;
4. a filler the ASR wrote whose span also holds a real word (the isolated
   decode says "uh we") is shortened to the filler's own piece.

Precision matters more than recall here: a false filler cuts a real word, a
missed one only leaves an "uh" in. Every added word carries
"filler": true, "detected": "gap-scan" | "gap-acoustic" and a "conf".
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import util as U

HOP = 0.01
MIN_GAP = 0.15
MAX_GAP = 0.80
BRIDGE = 0.05
WINDOW_PAD = 0.30
ELONG_MIN = 0.5          # a word this long ...
ELONG_PER_CHAR = 0.15    # ... and over 0.15 s per letter may hide a filler
NEXT_GUARD = 0.06        # a new filler stops this far before the next decoded word's onset
MIN_FILLER = 0.12
MERGE_GAP = 0.15         # a new filler this close to a transcript filler is the same hesitation
MIN_VOICED = 0.3         # share of loud frames a new filler needs (a breath is not an "uh")
MIN_PITCHED = 0.2        # ... and of pitched frames (an "uh" is a held vowel; PodcastFillers: 7 of 9 below were wrong)

# decode(list of float32 arrays at sr) -> per array: [(text_piece, start_s, dur_s)]
Decoder = Callable[[Sequence[Any]], List[List[Tuple[str, float, float]]]]


# --------------------------------------------------------------------------
# masks
# --------------------------------------------------------------------------

def voiced_mask(audio, sr: int, vad_spans: Optional[Sequence[Tuple[float, float]]] = None):
    """Boolean array per 10 ms frame: speech energy (and VAD speech when given)."""
    import numpy as np
    db = U.frame_db(audio, sr, HOP)
    thr = U.voice_threshold(db)[0]
    v = db > thr
    if vad_spans:
        m = np.zeros_like(v)
        for s, e in vad_spans:
            m[max(0, int(s / HOP) - 5): min(len(m), int(math.ceil(e / HOP)) + 5)] = True
        v &= m
    return v


def covered_mask(words: Sequence[Dict[str, Any]], n: int, pad: float = 0.02):
    import numpy as np
    c = np.zeros(n, dtype=bool)
    for w in words:
        a = max(0, int((float(w["start"]) - pad) / HOP))
        b = min(n, int(math.ceil((float(w["end"]) + pad) / HOP)))
        c[a:b] = True
    return c


def runs(mask) -> List[Tuple[int, int]]:
    """[(first, last+1)] of True runs."""
    import numpy as np
    idx = np.flatnonzero(mask)
    if not len(idx):
        return []
    br = np.flatnonzero(np.diff(idx) > 1)
    starts = np.concatenate([[idx[0]], idx[br + 1]])
    ends = np.concatenate([idx[br], [idx[-1]]]) + 1
    return list(zip(starts.tolist(), ends.tolist()))


def gap_candidates(words: Sequence[Dict[str, Any]], audio, sr: int,
                   vad_spans: Optional[Sequence[Tuple[float, float]]] = None,
                   min_len: float = MIN_GAP, max_len: float = MAX_GAP) -> List[Tuple[float, float]]:
    """Voiced regions no word covers, [min_len, max_len] seconds long."""
    v = voiced_mask(audio, sr, vad_spans)
    free = v & ~covered_mask([w for w in words if w.get("type", "word") in ("word", "audio_event")], len(v))
    rs = runs(free)
    merged: List[List[int]] = []
    for a, b in rs:
        if merged and a - merged[-1][1] <= int(BRIDGE / HOP):
            merged[-1][1] = b
        else:
            merged.append([a, b])
    out = []
    for a, b in merged:
        d = (b - a) * HOP
        if min_len - 1e-9 <= d <= max_len + 1e-9:
            out.append((round(a * HOP, 3), round(b * HOP, 3)))
    return out


# --------------------------------------------------------------------------
# acoustic check
# --------------------------------------------------------------------------

def acoustic(audio, sr: int, a: float, b: float) -> Dict[str, float]:
    """Held-vowel evidence for [a, b]: voicing ratio, spectral steadiness, pitch spread.

    voiced   share of 30 ms frames with a clear pitch (normalised autocorrelation >= 0.5, 70-400 Hz)
    steady   mean cosine similarity of consecutive log spectra (1 = unchanging)
    f0_cv    pitch coefficient of variation over the voiced frames
    score    0..1 combination; >= 0.6 reads as "uh"/"um"/"mm" rather than a word or a breath
    """
    import numpy as np
    x = np.asarray(audio[max(0, int(a * sr)): int(b * sr)], dtype=np.float64)
    win, hop = int(0.03 * sr), int(0.01 * sr)
    if len(x) < win * 2:
        return {"voiced": 0.0, "steady": 0.0, "f0_cv": 1.0, "score": 0.0}
    lo, hi = int(sr / 400), int(sr / 70)
    f0s, voiced, specs = [], 0, []
    w = np.hanning(win)
    frames = range(0, len(x) - win, hop)
    for i in frames:
        fr = x[i:i + win] - x[i:i + win].mean()
        e = float(np.dot(fr, fr))
        if e <= 1e-10:
            specs.append(None)
            continue
        ac = np.correlate(fr, fr, "full")[win - 1:]
        ac = ac / (ac[0] + 1e-12)
        seg = ac[lo:hi]
        k = int(np.argmax(seg)) if len(seg) else 0
        if len(seg) and seg[k] >= 0.5:
            voiced += 1
            f0s.append(sr / float(lo + k))
        sp = np.log(np.abs(np.fft.rfft(fr * w))[: win // 4] + 1e-6)
        specs.append(sp - sp.mean())
    n = len(frames)
    sims = []
    for p, q in zip(specs, specs[1:]):
        if p is None or q is None:
            continue
        den = float(np.linalg.norm(p) * np.linalg.norm(q)) + 1e-9
        sims.append(float(np.dot(p, q)) / den)
    vr = voiced / float(max(1, n))
    steady = float(np.mean(sims)) if sims else 0.0
    f0_cv = float(np.std(f0s) / (np.mean(f0s) + 1e-9)) if len(f0s) >= 3 else 1.0
    score = max(0.0, min(1.0, (vr - 0.4) / 0.4)) * max(0.0, min(1.0, (steady - 0.55) / 0.3)) \
        * max(0.0, min(1.0, (0.25 - f0_cv) / 0.15))
    return {"voiced": round(vr, 3), "steady": round(steady, 3), "f0_cv": round(f0_cv, 3), "score": round(score, 3)}


# --------------------------------------------------------------------------
# isolated re-decode
# --------------------------------------------------------------------------

def _pieces_to_words(pieces: List[Tuple[str, float, float]]) -> List[Dict[str, Any]]:
    """Sentencepiece pieces ('▁' or leading space = new word) -> [{text, start, end}]."""
    out: List[Dict[str, Any]] = []
    for text, t0, d in pieces:
        raw = text.replace("▁", " ")
        core = raw.strip()
        if not core:
            continue
        if U.bare(core) == "":
            continue   # punctuation
        if out and not raw[:1].isspace():
            out[-1]["text"] += core
            out[-1]["end"] = max(out[-1]["end"], t0 + max(d, 0.04))
            continue
        out.append({"text": core, "start": t0, "end": t0 + max(d, 0.04), "t0": t0})
    return out


def decode_windows(regions: Sequence[Tuple[float, float]], audio, sr: int, decode: Decoder,
                   pad: float = WINDOW_PAD) -> List[List[Dict[str, Any]]]:
    """Decode each region with `pad` s of context on each side -> words on the file's clock."""
    dur = len(audio) / float(sr)
    wins, offs = [], []
    for a, b in regions:
        s, e = max(0.0, a - pad), min(dur, b + pad)
        wins.append(audio[int(s * sr): int(e * sr)])
        offs.append(s)
    res = decode(wins) if wins else []
    return [[dict(w, start=w["start"] + off, end=w["end"] + off, t0=w["t0"] + off) for w in _pieces_to_words(p)]
            for off, p in zip(offs, res)]


def _same(a: str, b: str) -> bool:
    x, y = U.bare(a), U.bare(b)
    return bool(x) and bool(y) and (x == y or (len(x) >= 3 and len(y) >= 3 and (x.startswith(y) or y.startswith(x))))


def _voiced_share(voiced, s: float, e: float) -> float:
    i, j = max(0, int(s / HOP)), min(len(voiced), int(math.ceil(e / HOP)))
    return float(voiced[i:j].mean()) if j > i else 0.0


def elongated(words: Sequence[Dict[str, Any]], lang: str) -> List[Tuple[float, float]]:
    """Words far longer than their spelling allows: a filler folded into them ("nearly-uh", or an
    "uh we need" heard as one odd word). Regions = the word spans."""
    out = []
    for w in words:
        if w.get("type", "word") != "word" or U.is_filler(w["text"], lang):
            continue
        d = float(w["end"]) - float(w["start"])
        n = len(U.bare(w["text"]))
        if d >= max(ELONG_MIN, ELONG_PER_CHAR * max(1, n)):
            out.append((round(float(w["start"]), 3), round(float(w["end"]), 3)))
    return out


def judge(region: Tuple[float, float], decoded: List[Dict[str, Any]], transcript: Sequence[Dict[str, Any]],
          lang: str) -> Dict[str, Any]:
    """What a re-decoded window says about a region.

    Decoded words are matched to transcript words (same text, onset within 0.35 s). A decoded filler
    inside the region that matches no transcript filler is new; its span runs from its onset to just
    before the next decoded word (matched or not), so it never reaches into speech the decoder heard.
    Real words the transcript lacks are reported ("missed"); one that starts inside the region before
    the filler bounds the span from the left."""
    a, b = region
    near = [w for w in transcript if w.get("type", "word") == "word" and float(w["end"]) >= a - 1.0
            and float(w["start"]) <= b + 1.0]
    used: set = set()
    matched_ids = set()
    for d in decoded:
        best, bd = None, 0.36
        for k, t in enumerate(near):
            if k in used or not _same(d["text"], t["text"]):
                continue
            dd = abs(d["t0"] - float(t["start"]))
            if dd < bd:
                best, bd = k, dd
        if best is not None:
            used.add(best)
            matched_ids.add(id(d))
    new_fill = [d for d in decoded if id(d) not in matched_ids and U.is_filler(d["text"], lang)
                and U.is_hesitation(d["text"]) and a - 0.15 <= d["t0"] <= b + 0.05]
    missed = [d for d in decoded if id(d) not in matched_ids and not U.is_filler(d["text"], lang)
              and a - 0.05 <= d["t0"] <= b]
    out: Dict[str, Any] = {"new_fillers": new_fill, "missed": missed, "decoded": [d["text"] for d in decoded]}
    if new_fill:
        f = new_fill[0]
        before = [d["end"] for d in decoded if d is not f and d["t0"] < f["t0"] and not U.is_filler(d["text"], lang)]
        after = [d["t0"] for d in decoded if d["t0"] > f["t0"] + 0.02]
        s0 = max(a - 0.1, f["t0"] - 0.04, max(before, default=-1.0) + 0.02)
        e0 = min([b + 0.05] + [x - NEXT_GUARD for x in after])
        if e0 - s0 >= MIN_FILLER:
            out["span"] = (round(s0, 3), round(e0, 3))
    return out


def _make_room(words: List[Dict[str, Any]], s0: float, e0: float, lang: str) -> bool:
    """Trim transcript words that overlap a new filler span [s0, e0] so the cut can take it.

    A word that ends inside the span ends at s0; one that starts inside it starts at e0; each keeps
    >= 0.1 s. False (and nothing changed) when a word would be swallowed or squeezed."""
    plan = []
    for w in words:
        if w.get("type", "word") != "word":
            continue
        ws, we = float(w["start"]), float(w["end"])
        if we <= s0 + 1e-3 or ws >= e0 - 1e-3:
            continue
        if ws < s0 < we <= e0 + 0.05 and s0 - ws >= 0.1:
            plan.append((w, "end", s0))
        elif s0 - 0.05 <= ws < e0 < we and we - e0 >= 0.1:
            plan.append((w, "start", e0))
        elif ws < s0 and we > e0:
            return False          # the filler would sit inside a word: leave it
        else:
            return False
    for w, k, v in plan:
        w[k] = round(v, 3)
        w["estimated"] = True
    return True


def scan(words: List[Dict[str, Any]], audio, sr: int, lang: str, decode: Optional[Decoder],
         vad_spans: Optional[Sequence[Tuple[float, float]]] = None, acoustic_min: float = 0.75,
         allow_acoustic_only: bool = False) -> Dict[str, Any]:
    """Add missed fillers to `words` (in place, sorted).

    Candidates: voiced gaps no word covers, and words far longer than their spelling (a filler folded
    in). Returns stats {"candidates", "elongated", "added", "added_acoustic", "missed_words",
    "skipped", "events": [...]}."""
    stats: Dict[str, Any] = {"candidates": 0, "elongated": 0, "added": 0, "added_acoustic": 0, "missed_words": 0,
                             "skipped": 0, "widened": 0, "events": []}
    gaps = gap_candidates(words, audio, sr, vad_spans)
    longw = elongated(words, lang) if decode else []
    cands = [(a, b, "gap") for a, b in gaps] + [(a, b, "long-word") for a, b in longw]
    stats["candidates"] = len(gaps)
    stats["elongated"] = len(longw)
    voiced = voiced_mask(audio, sr)
    toks = [w for w in words if w.get("type", "word") == "word"]
    decoded = decode_windows([(a, b) for a, b, _ in cands], audio, sr, decode) if decode else [[] for _ in cands]
    added: List[Dict[str, Any]] = []
    for (a, b, kind), dec in zip(cands, decoded):
        ev: Dict[str, Any] = {"start": a, "end": b, "from": kind}
        j = judge((a, b), dec, toks, lang) if decode else {"new_fillers": [], "missed": [], "decoded": []}
        # a transcript word timed onto silence right next to the new filler, that the window did not hear:
        # its sound may be what the decoder called a filler, so leave it
        drift = []
        if j.get("span"):
            s0, e0 = j["span"]
            drift = [w["text"] for w in toks if not U.is_filler(w["text"], lang)
                     and s0 - 0.1 <= float(w["start"]) <= e0 + 0.1
                     and _voiced_share(voiced, float(w["start"]), float(w["end"])) < 0.3
                     and not any(_same(d["text"], w["text"]) for d in dec)]
        ev["decoded"] = " ".join(j["decoded"])
        if j["missed"]:
            stats["missed_words"] += 1
            ev["missed"] = " ".join(d["text"] for d in j["missed"])
        if drift:
            stats["skipped"] += 1
            ev.update(kind="skip-drift", text=" ".join(drift))
        elif j.get("span"):
            s0, e0 = j["span"]
            near = [w for w in toks + added if U.is_filler(w["text"], lang)
                    and float(w["start"]) < e0 + MERGE_GAP and float(w["end"]) > s0 - MERGE_GAP]
            vs = _voiced_share(voiced, s0, e0)
            pitched = acoustic(audio, sr, s0, e0)["voiced"]
            if near:
                # the same hesitation, longer than its transcript word: widen that word (one cut)
                w0 = near[0]
                ns, ne = min(float(w0["start"]), s0), max(float(w0["end"]), e0)
                if all(float(w["end"]) <= ns + 1e-3 or float(w["start"]) >= ne - 1e-3 or U.is_filler(w["text"], lang)
                       for w in toks):
                    w0["start"], w0["end"] = round(ns, 3), round(ne, 3)
                    stats["widened"] += 1
                ev.update(kind="widened", text=w0["text"])
            elif vs < MIN_VOICED or (kind == "gap" and pitched < MIN_PITCHED):
                # (a long word the decoder split into "uh" + words is evidence enough; a bare gap needs a pitch)
                stats["skipped"] += 1
                ev.update(kind="skip-unvoiced", voiced=round(vs, 3), pitched=pitched)
            elif _make_room(toks, s0, e0, lang):
                # the decoder emits a token a little after its onset: grow the start back over voiced
                # frames (<= 0.2 s), never into the previous word
                prev_end = max([float(w["end"]) for w in toks + added if float(w["end"]) <= s0 + 1e-3], default=0.0)
                k = int(round(s0 / HOP))
                lim = max(prev_end + 0.02, s0 - 0.2)
                while k - 1 >= 0 and k - 1 < len(voiced) and voiced[k - 1] and (k - 1) * HOP >= lim:
                    k -= 1
                s0 = round(min(s0, k * HOP), 3)
                w = {"text": U.bare(j["new_fillers"][0]["text"]) or "uh", "start": s0, "end": e0, "type": "word",
                     "filler": True, "detected": "gap-scan" if kind == "gap" else "long-word", "conf": 0.9,
                     "checked": True}
                added.append(w)
                ev.update(kind="filler", text=j["new_fillers"][0]["text"], span=[s0, e0])
            else:
                stats["skipped"] += 1
                ev.update(kind="skip-inside-word")
        elif j["new_fillers"]:
            stats["skipped"] += 1
            ev.update(kind="skip-short")
        elif kind == "gap" and not j["missed"]:
            ac = acoustic(audio, sr, a, b)
            ev.update(kind="empty", acoustic=ac)
            if allow_acoustic_only and ac["score"] >= acoustic_min:
                added.append({"text": "uh", "start": a, "end": b, "type": "word", "filler": True,
                              "detected": "gap-acoustic", "conf": round(0.5 + 0.4 * ac["score"], 3)})
                ev["kind"] = "filler-acoustic"
        else:
            ev.setdefault("kind", "missed-word" if j["missed"] else "nothing")
        stats["events"].append(ev)
    # second opinion on the fillers the ASR wrote: decode each on its own (0.35 s of context). A filler the
    # isolated decode does not hear again is marked "checked": false; `edit cut --strict-fillers` keeps
    # those (fewer false cuts, some real fillers left in).
    asr_f = [w for w in toks if U.is_filler(w["text"], lang) and not w.get("detected")]
    if decode and asr_f:
        res = decode_windows([(float(w["start"]), float(w["end"])) for w in asr_f], audio, sr, decode, pad=0.35)
        for w, ws in zip(asr_f, res):
            a, b = float(w["start"]), float(w["end"])
            w["checked"] = any(U.is_filler(d["text"], lang) and a - 0.2 <= d["t0"] <= b + 0.1 for d in ws)
        stats["asr_fillers_checked"] = sum(1 for w in asr_f if w["checked"])
        stats["asr_fillers"] = len(asr_f)
    stats["added"] = sum(1 for w in added if w["detected"] in ("gap-scan", "long-word"))
    stats["added_acoustic"] = sum(1 for w in added if w["detected"] == "gap-acoustic")
    if added:
        words.extend(added)
        words.sort(key=lambda w: (float(w["start"]), float(w["end"])))
    return stats


# --------------------------------------------------------------------------
# cut edges
# --------------------------------------------------------------------------

def snap_edges(keep: List[Tuple[float, float]], audio, sr: int, words: Sequence[Dict[str, Any]],
               radius: float = 0.04) -> Tuple[List[Tuple[float, float]], int]:
    """Move every inner cut edge to the quietest 10 ms frame within +-radius.

    An edge never moves into a kept word (kept words are the protected spans;
    their padding may shrink). Returns (keep, edges moved)."""
    import numpy as np
    if not keep:
        return keep, 0
    db = U.frame_db(audio, sr, HOP)
    n = len(db)
    kept_words = [w for w in words if w.get("type", "word") == "word"]
    moved = 0
    out: List[Tuple[float, float]] = []

    def best(t: float, lo_lim: float, hi_lim: float) -> float:
        lo = max(0, int(round(max(t - radius, lo_lim) / HOP)))
        hi = min(n, int(round(min(t + radius, hi_lim) / HOP)) + 1)
        if hi - lo < 2:
            return t
        k = lo + int(np.argmin(db[lo:hi]))
        # prefer the original time when it is (nearly) as quiet
        cur = min(n - 1, max(0, int(round(t / HOP))))
        if db[cur] <= db[k] + 1.0:
            return t
        return round(k * HOP + HOP / 2, 3)

    for i, (s, e) in enumerate(keep):
        ns, ne = s, e
        inside = [w for w in kept_words if float(w["start"]) >= s - 1e-6 and float(w["end"]) <= e + 1e-6]
        first_start = min((float(w["start"]) for w in inside), default=e)
        last_end = max((float(w["end"]) for w in inside), default=s)
        if i > 0:
            ns = best(s, out[-1][1] + 0.01, first_start)
        if i < len(keep) - 1:
            ne = best(e, last_end, keep[i + 1][0] - 0.01)
        if ns != s or ne != e:
            moved += (ns != s) + (ne != e)
        out.append((ns, max(ns + 0.02, ne)))
    return out, moved

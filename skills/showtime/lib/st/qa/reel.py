"""Showreel measures (the showreel tone, st.showreel): shots, the end card's hold, repeated shots, energy dips.

A showreel is judged on density, variety and an ending that lands (references/tones.md, showreel). The round-5
blind vote (2026-10-05) went to a reel with 13-14 shots, no technique twice and a name that kept moving to the
last frame; the two losing takes cut 9-11 shots and held their name still for 2.5-3.5 s of 15. These numbers
come from the frames qa already decodes for the edit rhythm (st.qa.rhythm.picture: a 64-bin colour histogram,
a 32x18 luma layout and the mean frame difference per frame):

  shots      a boundary where the colour histogram or the coarse layout of the 0.15 s before and after differ
             (score = max(histogram distance, (1 - layout correlation) / 2) >= SHOT_SCORE, at least 0.2 s apart).
             Finer than rhythm's hard cuts and layout changes: a flash cut, a whip or a match into a new
             composition is a shot too.
  end        the last shot's length and how long it holds still at the end (the trailing stretch whose 0.25 s
             windows move by less than STILL_MAD levels): a name that lands and keeps moving is not a hold.
  repeats    two shots of REPEAT_MIN_S or more, not neighbours, neither the last (an end card may echo the
             opening), whose middle halves look alike: histogram distance under repeat_hist_max and layout
             correlation over repeat_layout_min (thresholds.json "showreel"). A cheap signal for "the same trick
             twice": the same ground, palette and composition.
  dips       stretches before the last shot where the 0.5 s mean frame difference stays under STILL_MAD for
             longer than dip_max_s (the reel sags).

Numpy only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

SHOT_SCORE = 0.3        # a new composition: a third of the histogram changed, or the layout decorrelated
SHOT_WIN_S = 0.15       # compared windows either side of a boundary
SHOT_GAP_S = 0.2        # shots shorter than this are one flash, not two shots
STILL_MAD = 1.0         # mean frame difference (0-255 levels at 256x144) under which the picture reads as still
REPEAT_MIN_S = 0.4      # flash cuts (texture) are not judged for repeats


def _corr(a, b) -> float:
    import numpy as np
    sa, sb = float(a.std()), float(b.std())
    if sa < 1.0 and sb < 1.0:
        return 1.0 if abs(float(a.mean()) - float(b.mean())) < 8 else 0.0
    if sa < 1.0 or sb < 1.0:
        return 0.0
    return float(np.mean((a - a.mean()) * (b - b.mean())) / (sa * sb))


def shot_bounds(hists, sigs, fps: float) -> List[int]:
    """Frame indices where a new shot starts (0 excluded), from the per-frame histograms and layouts."""
    import numpy as np
    n = len(hists)
    k = max(2, int(round(SHOT_WIN_S * fps)))
    if n < 2 * k + 1:
        return []
    score = np.zeros(n)
    for i in range(k, n - k + 1):
        hd = 0.5 * float(np.abs(hists[i - k:i].mean(0) - hists[i:i + k].mean(0)).sum())
        c = _corr(sigs[i - k:i].mean(0), sigs[i:i + k].mean(0))
        score[i] = max(hd, (1.0 - c) * 0.5)
    gap = max(1, int(round(SHOT_GAP_S * fps)))
    out: List[int] = []
    for i in np.argsort(-score, kind="stable"):
        if score[i] < SHOT_SCORE:
            break
        if all(abs(int(i) - j) >= gap for j in out) and gap <= i <= n - gap:
            out.append(int(i))
    return sorted(out)


def analyze(hists, sigs, mad, fps: float, th: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """The showreel report: shots, end, repeats, dips (module docstring). th: st.showreel.thresholds()."""
    import numpy as np
    if th is None:
        from .. import showreel
        th = showreel.thresholds()
    hists = np.asarray(hists, dtype=np.float64)
    sigs = np.asarray(sigs, dtype=np.float64)
    mad = np.asarray(mad, dtype=np.float64)
    n = len(hists)
    if n == 0 or not fps:
        return {"shots": [], "n_shots": 0}
    edges = [0] + shot_bounds(hists, sigs, fps) + [n]
    segs = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]
    shots = [{"t": round(a / fps, 3), "s": round((b - a) / fps, 3)} for a, b in segs]
    # the end: the last shot, and how long it holds still at the very end
    a, b = segs[-1]
    w = max(1, int(round(0.25 * fps)))
    t = b
    while t - w >= a and float(mad[t - w:t].mean()) < STILL_MAD:
        t -= w
    end = {"t": round(a / fps, 3), "shot_s": round((b - a) / fps, 3), "still_s": round((b - t) / fps, 3)}
    # repeats: the middle half of each long-enough shot, compared with every shot but its neighbours and the last
    desc = []
    for (s0, s1) in segs:
        q = (s1 - s0) // 4
        m = slice(s0 + q, max(s0 + q + 1, s1 - q))
        desc.append((hists[m].mean(0), sigs[m].mean(0)))
    rep: List[Dict[str, Any]] = []
    long_ = [i for i, (s0, s1) in enumerate(segs[:-1]) if (s1 - s0) / fps >= REPEAT_MIN_S]
    for x in long_:
        for y in long_:
            if y < x + 2:
                continue
            hd = 0.5 * float(np.abs(desc[x][0] - desc[y][0]).sum())
            c = _corr(desc[x][1], desc[y][1])
            if hd < th["repeat_hist_max"] and c > th["repeat_layout_min"]:
                rep.append({"a": shots[x]["t"], "b": shots[y]["t"], "hist": round(hd, 3), "layout": round(c, 3)})
    # dips: the 0.5 s mean frame difference under STILL_MAD for longer than dip_max_s, before the last shot
    h = max(1, int(round(0.5 * fps)))
    roll = np.convolve(mad, np.ones(h) / h, mode="same") if len(mad) >= h else mad
    low = roll[:a] < STILL_MAD
    dips: List[Dict[str, Any]] = []
    i = 0
    while i < len(low):
        if not low[i]:
            i += 1
            continue
        j = i
        while j < len(low) and low[j]:
            j += 1
        if (j - i) / fps > th["dip_max_s"]:
            dips.append({"t": round(i / fps, 3), "s": round((j - i) / fps, 3)})
        i = j
    return {"shots": shots, "n_shots": len(shots), "end": end, "repeats": rep, "dips": dips}


def summary(r: Dict[str, Any]) -> str:
    """One line for the rhythm summary and the critic's rubric."""
    if not r or not r.get("n_shots"):
        return ""
    e = r.get("end") or {}
    parts = ["%d shots (median %.2fs)" % (r["n_shots"], _median([s["s"] for s in r["shots"]])),
             "last shot %.1fs, still for its last %.1fs" % (e.get("shot_s", 0), e.get("still_s", 0))]
    rp = r.get("repeats") or []
    parts.append("%d look-alike pair(s)%s" % (len(rp), (": " + ", ".join("%.1fs~%.1fs" % (x["a"], x["b"]) for x in rp[:4]))
                                              if rp else ""))
    dp = r.get("dips") or []
    parts.append("%d energy dip(s)%s" % (len(dp), (": " + ", ".join("%.1fs for %.1fs" % (x["t"], x["s"]) for x in dp[:4]))
                                          if dp else ""))
    return "; ".join(parts)


def _median(xs: Sequence[float]) -> float:
    xs = sorted(xs)
    if not xs:
        return 0.0
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else 0.5 * (xs[m - 1] + xs[m])

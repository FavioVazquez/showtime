"""Edit rhythm of a rendered video: hard cuts, shots, still stretches, how scene changes are made
(a cut or a continuous move) and whether the music breathes and swells with them.

These are the measures that separate a calm, premium launch film from a choppy one (the premium
reference films tell their story in 4-5 scenes with 0-5 hard cuts, hold each scene 3.5-21 s and sit
on a quiet bed with swells; a film with 17 layouts in 56 s and a flat bed reads as cheap):

  cuts          frames where the colour histogram jumps > 3.5x its +-8-frame neighbourhood and the
                picture changes by > 6 levels on average (hard cuts; dissolves and camera moves ramp
                and are not counted)
  layouts       stretches with one composition: the coarse luma layout (32x18 blocks) 0.5 s before and
                after a moment correlates < 0.6 at a layout change. Each change is a cut (one frame),
                fast (a push, wipe or whip under 0.6 s: the frame is replaced) or a move (0.6 s or
                more of continuous motion: a camera move, a match, a dissolve)
  shots         lengths between cuts
  still         frames that change by < 0.35 levels (nothing moves); the longest still stretch
  scenes        the project's top-level scenes (when the video has a project), and for each scene
                change whether it was a hard cut or continuous (a camera move, a match, a dissolve)
  music         loudness every 0.5 s (dB), its dynamics (10th-90th percentile), and for each scene
                change whether the music moves there too (an onset or a rise within 0.25 s)
  flashes       general flashes (photosensitivity, WCAG 2.3.1 style): a frame-to-frame change in linear
                luminance of 0.1 or more, over FLASH_AREA of the frame or more, the darker side under 0.8;
                a pair of opposing changes is one flash; the most in any 1 s window (more than 3 is a risk)

Numpy only; frames are decoded small (256x144) through the showtime ffmpeg.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .. import ff

W_, H_ = 256, 144
LAUNCH_KINDS = ("launch", "promo", "trailer", "teaser", "release")
LAUNCH_WORDS = re.compile(r"\b(launch|promo|promotional|trailer|teaser|release video|announcement|hype)\b", re.I)

# premium launch grammar (the rules qa and the critic check; see references/workflows/launch-video.md)
LIMITS = {"max_hard_cuts": 5, "max_scenes": 6, "min_music_range_db": 3.0, "max_still_s": 5.5}
# general flash threshold: a quarter of the frame (the share of a 10-degree field a phone or laptop screen fills is
# larger, so this is conservative), a 0.1 change in linear luminance, at most 3 flashes in any one second
FLASH_AREA, FLASH_DELTA, FLASH_DARK, FLASH_MAX_PER_S = 0.25, 0.1, 0.8, 3


def _flash_dirs(lum_prev, lum) -> int:
    """+1 / -1 when this frame is a general flash transition up / down (FLASH_* above), else 0."""
    import numpy as np
    d = lum - lum_prev
    dark = np.minimum(lum, lum_prev) < FLASH_DARK
    if float(((d >= FLASH_DELTA) & dark).mean()) >= FLASH_AREA:
        return 1
    if float(((d <= -FLASH_DELTA) & dark).mean()) >= FLASH_AREA:
        return -1
    return 0


def flash_rate(dirs: Sequence[int], fps: float) -> Dict[str, Any]:
    """The most flashes in any 1 s window: transitions in one direction in a row count once, a pair of opposing
    ones is a flash. dirs: one value per frame (+1, -1, 0)."""
    ev = [(i, d) for i, d in enumerate(dirs) if d]
    win = max(1, int(round(fps or 30)))
    best, at = 0, None
    for k, (i0, _) in enumerate(ev):
        seq = []
        for i, d in ev[k:]:
            if i - i0 >= win:
                break
            if not seq or seq[-1] != d:
                seq.append(d)
        n = len(seq) // 2
        if n > best:
            best, at = n, i0
    return {"max_per_s": best, "at": round(at / fps, 3) if at is not None and fps else None,
            "transitions": len(ev)}


def _frames(video: Path, max_seconds: Optional[float]):
    import numpy as np
    args = [ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error"]
    if max_seconds:
        args += ["-t", "%.3f" % max_seconds]
    args += ["-i", os.fspath(video), "-an", "-sn", "-vf", "scale=%d:%d:flags=area" % (W_, H_),
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = W_ * H_ * 3
    try:
        while True:
            buf = p.stdout.read(n)
            if not buf or len(buf) < n:
                break
            yield np.frombuffer(buf, np.uint8).reshape(H_, W_, 3)
    finally:
        p.stdout.close()
        p.wait()


def picture(video: Path, fps: float, max_seconds: Optional[float] = None, keep: bool = False) -> Dict[str, Any]:
    """keep: also return the per-frame histograms and layouts ("_hists", "_sigs") for st.qa.reel."""
    import numpy as np
    mads: List[float] = []
    kept: List[Any] = []
    hds: List[float] = []
    sigs: List[Any] = []
    prev_g = None
    prev_h = None
    prev_l = None
    dirs: List[int] = []
    for fr in _frames(video, max_seconds):
        g = fr.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
        lum = np.power(g / 255.0, 2.2)          # linear luminance, near enough for a flash count
        dirs.append(_flash_dirs(prev_l, lum) if prev_l is not None else 0)
        prev_l = lum
        sigs.append(g.reshape(18, H_ // 18, 32, W_ // 32).mean(axis=(1, 3)).ravel())
        q = (fr // 64).astype(np.int32)
        idx = q[..., 0] * 16 + q[..., 1] * 4 + q[..., 2]
        hist = np.bincount(idx.ravel(), minlength=64).astype(np.float64)
        hist /= hist.sum() or 1.0
        if keep:
            kept.append(hist)
        if prev_g is None:
            mads.append(0.0)
            hds.append(0.0)
        else:
            mads.append(float(np.abs(g - prev_g).mean()))
            hds.append(float(0.5 * np.abs(hist - prev_h).sum()))
        prev_g, prev_h = g, hist
    n = len(mads)
    mad = np.asarray(mads)
    hd = np.asarray(hds)
    cuts: List[int] = []
    for i in range(1, n):
        lo, hi = max(1, i - 8), min(n, i + 9)
        nb = np.concatenate([hd[lo:i], hd[i + 1:hi]])
        base = float(np.median(nb)) if len(nb) else 0.0
        # ... and concentrated in that one frame (a fast dissolve spreads the same change over several)
        near = max(mad[i - 1] if i > 1 else 0.0, mad[i + 1] if i + 1 < n else 0.0)
        if hd[i] > 0.28 and hd[i] > 3.5 * base + 0.05 and mad[i] > 6 and mad[i] > 2.0 * near:
            if not cuts or i - cuts[-1] > 3:
                cuts.append(i)
    dur = n / fps if fps else 0.0
    cut_t = [round(i / fps, 3) for i in cuts]
    bounds = [0.0] + cut_t + [dur]
    shots = [round(b - a, 3) for a, b in zip(bounds[:-1], bounds[1:]) if b - a > 0.02]
    still = mad < 0.35
    still[0] = False
    runs, r, start, longest_at = [], 0, 0, 0.0
    best = 0
    for i, v in enumerate(still):
        if v:
            if r == 0:
                start = i
            r += 1
            if r > best:
                best, longest_at = r, start / fps
        else:
            r = 0
    layouts = _layouts(np.asarray(sigs), mad, cuts, fps)
    extra = {"_hists": np.asarray(kept), "_sigs": np.asarray(sigs)} if keep else {}
    return {**extra, "frames": n, "hard_cuts": cut_t, "layout_changes": layouts, "n_layouts": len(layouts) + 1 if n else 0,
            "moving_fraction": round(float((mad >= 0.35).mean()), 3) if n else 0.0, "n_hard_cuts": len(cut_t), "cuts_per_s": round(len(cut_t) / dur, 3) if dur else 0,
            "shots": shots, "shot_mean_s": round(float(np.mean(shots)), 2) if shots else None,
            "shot_median_s": round(float(np.median(shots)), 2) if shots else None,
            "still_fraction": round(float(still.mean()), 3) if n else 0.0,
            "longest_still_s": round(best / fps, 2) if fps else 0.0, "longest_still_at": round(longest_at, 2),
            "flashes": flash_rate(dirs, fps), "_mad": mad}


def _corr(a, b) -> float:
    import numpy as np
    sa, sb = float(a.std()), float(b.std())
    if sa < 1.0 and sb < 1.0:
        return 1.0 if abs(float(a.mean()) - float(b.mean())) < 8 else 0.0
    if sa < 1.0 or sb < 1.0:
        return 0.0
    return float(np.mean((a - a.mean()) * (b - b.mean())) / (sa * sb))


def _layouts(sig, mad, cuts: List[int], fps: float) -> List[Dict[str, Any]]:
    """Layout changes: where the coarse composition 0.5 s before and after decorrelates."""
    import numpy as np
    n = len(sig)
    k = max(1, int(round(0.5 * fps)))
    c = np.ones(n)
    for i in range(k, n - k):
        c[i] = _corr(sig[i - k], sig[i + k])
    low = c < 0.6
    out: List[Dict[str, Any]] = []
    i = 0
    cutset = set(cuts)
    while i < n:
        if not low[i]:
            i += 1
            continue
        j = i
        while j < n and low[j]:
            j += 1
        if j - i < max(3, int(0.3 * fps)):
            i = j                    # a flash or a dip back to the same layout, not a new composition
            continue
        # the transition itself: the most changing frame in the low stretch and its moving neighbours
        mid = i + int(np.argmax(mad[i:j]))
        a = b = mid
        while a > 0 and mad[a] >= 0.8:
            a -= 1
        while b < n - 1 and mad[b + 1] >= 0.8:
            b += 1
        span = (b - a) / fps
        hard = any(i - 2 <= x <= j + 2 for x in cutset)       # a hard cut, even into moving footage
        kind = "cut" if hard else ("fast" if span < 0.6 else "move")
        out.append({"t": round(mid / fps, 3), "kind": kind, "seconds": round(span, 2), "corr": round(float(c[mid]), 2)})
        i = j
    return out


def music(video: Path, dur: float) -> Optional[Dict[str, Any]]:
    import numpy as np
    from . import media
    try:
        x = media.decode_audio(video, sr=22050)
    except Exception:  # noqa: BLE001 - no audio stream
        return None
    if x is None or len(x) < 22050:
        return None
    y = np.asarray(x, dtype=np.float32)
    if y.ndim > 1:
        y = y.mean(axis=1)
    hop = 11025
    k = len(y) // hop
    rms = np.array([np.sqrt(float((y[i * hop:(i + 1) * hop] ** 2).mean()) + 1e-12) for i in range(k)])
    db = 20 * np.log10(rms + 1e-9)
    sound = db[db > db.max() - 40] if len(db) else db
    rng = float(np.percentile(sound, 90) - np.percentile(sound, 10)) if len(sound) > 4 else 0.0
    # onsets: spectral flux peaks (shared with st.audio.beats)
    try:
        from ..audio import beats as bt
        f, S = bt._stft_mag(y if len(y) else np.zeros(1024, np.float32))
        env, _ = bt.onset_envelope(S, f)
        frames = bt.pick_onsets(env, delta=0.12)
        strong = frames[env[frames] >= np.percentile(env[frames], 60)] if len(frames) else frames
        onsets = (strong / bt.FPS).tolist()
    except Exception:  # noqa: BLE001
        onsets = []
    return {"rms_db_per_half_s": [round(float(v), 1) for v in db], "range_db": round(rng, 2),
            "mean_db": round(float(np.mean(sound)), 2) if len(sound) else None, "onsets": [round(t, 3) for t in onsets]}


def _rise(db: Sequence[float], t: float, hop: float = 0.5) -> float:
    i = int(round(t / hop))
    a = [v for v in db[i:i + 2]]
    b = [v for v in db[max(0, i - 2):i]]
    if not a or not b:
        return 0.0
    return sum(a) / len(a) - sum(b) / len(b)


def measure(video: Path, dur: float, fps: float, scenes: Optional[List[float]] = None,
            max_seconds: Optional[float] = None, showreel: bool = False) -> Dict[str, Any]:
    """The rhythm report. `scenes` = the project's scene start times (0 first), when known. showreel: add the
    showreel measures (st.qa.reel: shots, the end card's hold, repeats, energy dips) as rep["reel"]."""
    pic = picture(video, fps, max_seconds, keep=showreel)
    mad = pic.pop("_mad")
    hists, sigs = pic.pop("_hists", None), pic.pop("_sigs", None)
    mus = music(video, dur)
    rep: Dict[str, Any] = {"picture": pic, "music": {k: v for k, v in (mus or {}).items() if k != "onsets"} if mus else None}
    from .motion import dead_stops
    rep["dead_stops"] = dead_stops(mad, fps, pic["hard_cuts"])
    if showreel and hists is not None and len(hists):
        from . import reel
        rep["reel"] = reel.analyze(hists, sigs, mad, fps)
    if scenes:
        changes = []
        for s in scenes[1:]:
            hard = any(abs(c - s) <= 2.5 / fps for c in pic["hard_cuts"])
            i = int(round(s * fps))
            moving = bool(len(mad) and float(mad[max(0, i - 3):i + 4].mean()) >= 0.35)
            row = {"t": round(s, 3), "hard_cut": hard, "continuous": not hard, "moving": moving}
            if mus:
                row["music_rise_db"] = round(_rise(mus["rms_db_per_half_s"], s), 2)
                row["music_onset"] = any(abs(o - s) <= 0.25 for o in mus.get("onsets", []))
            changes.append(row)
        rep["scenes"] = {"count": len(scenes), "changes": changes,
                         "continuous": sum(1 for c in changes if not c["hard_cut"]),
                         "on_music": sum(1 for c in changes if c.get("music_onset") or (c.get("music_rise_db") or 0) >= 1.5)}
    return rep


def launch_like(cfg: Dict[str, Any], expect: Dict[str, Any], goal: Optional[str]) -> bool:
    kind = str(cfg.get("kind") or expect.get("style") or "").lower()
    if kind:
        return kind in LAUNCH_KINDS
    return bool(goal and LAUNCH_WORDS.search(goal))


def summary(r: Dict[str, Any]) -> str:
    p = r.get("picture") or {}
    lc = p.get("layout_changes") or []
    parts = ["%d layout(s): %d move(s), %d fast, %d cut(s)" % (
        p.get("n_layouts", 0), sum(1 for x in lc if x["kind"] == "move"), sum(1 for x in lc if x["kind"] == "fast"),
        sum(1 for x in lc if x["kind"] == "cut")), "%d hard cut(s)" % p.get("n_hard_cuts", 0)]
    if r.get("scenes"):
        s = r["scenes"]
        parts.append("%d scene(s), %d of %d changes continuous" % (s["count"], s["continuous"], len(s["changes"])))
    if p.get("shot_median_s") is not None:
        parts.append("median shot %.1fs" % p["shot_median_s"])
    parts.append("longest still %.1fs" % p.get("longest_still_s", 0))
    if r.get("reel"):
        from . import reel
        parts.append("showreel: " + reel.summary(r["reel"]))
    m = r.get("music")
    if m:
        parts.append("music dynamics %.1f dB" % m.get("range_db", 0))
        if r.get("scenes"):
            parts.append("%d scene change(s) on a music onset or swell" % r["scenes"]["on_music"])
    return ", ".join(parts)

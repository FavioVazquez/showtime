"""`showtime reference`: break a reference video into its grammar, never its content.

Measured locally from the file (ffmpeg decode + numpy), nothing is sent anywhere:

  changes     scene changes of every kind: hard cuts (ffmpeg scene detection, select=gt(scene,T)),
              composition changes (st.qa.rhythm: fast handoffs under 0.6 s, continuous moves such as a
              dissolve) and motion bursts (the window of a push or whip that keeps the layout); shots
              are the stretches between them -> shot lengths, their spread, pace (changes per 10 s)
  per shot    dominant palette (up to 5 colours with their share), mean brightness and saturation,
              motion energy (mean change between samples 1/4 s apart), the camera verb that best
              explains the motion (hold, push-in, pull-back, pan, tilt, or moving content), and a
              text-on-screen proxy (edge texture typical of type; no OCR) with the tallest text band
              as a share of the frame height (a rough type scale)
  sound       level every 0.5 s, loudness range, silence share, tempo and whether cuts land on beats
  sheet       a contact sheet at 1 frame per second, and one frame per shot

Writes reference.md (with the brief the storyboard uses), reference.json, sheet.jpg, shots.jpg and
fingerprint.npz (small grey frames for the near-copy guard) into the output folder.
"""
from __future__ import annotations

import math
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import ff
from ..common import ShowtimeError, debug, write_json

SAMPLE_FPS = 4.0           # analysis samples per second (<= 3 min); 2 above that
AW, AH_MAX = 384, 384      # analysis frame width (height follows the aspect)
FP_W, FP_H = 64, 36        # near-copy fingerprint frames
SCENE_T = 0.3              # ffmpeg scene score threshold for a cut
MIN_SHOT = 0.25
MAX_SHEET = 120            # 1 fps sheet: at most this many frames (evenly spread beyond that)
RIGHTS_NOTE = ("A reference is studied for its style (pace, shot lengths, palette, type sizes, layout, motion, "
               "sound shape), which a same-style video carries over. Its content never goes into your video: not "
               "its words, logos, footage, shots recreated frame by frame, characters or music track. Use "
               "references you are allowed to watch and keep; downloading from a site is subject to its terms, and "
               "showtime never bypasses a login or a bot wall.")


# ------------------------------------------------------------------ input

def is_url(s: str) -> bool:
    return bool(re.match(r"^https?://", str(s or ""), re.I))


def fetch(url: str, dest_dir: Path, max_mb: int = 500) -> Path:
    """A direct media file URL -> a local copy (through the same downloader asset fetches use).

    Only direct links to a video file work: showtime has no tool that extracts video from web pages or
    streaming sites, on purpose."""
    import urllib.parse
    from ..assets import net
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem)[:60] or "reference"
    tmp = dest_dir / (stem + ".download")
    try:
        info = net.download(url, tmp, max_bytes=max_mb << 20, timeout=180, progress=True)
    except Exception as e:  # noqa: BLE001 - network errors, HTML pages, size limit
        raise ShowtimeError("could not fetch the reference: %s" % (getattr(e, "message", None) or e),
                            why="showtime fetches direct links to a video file only (.../clip.mp4); it does not "
                                "extract video from web pages, social posts or streaming sites",
                            hint="save the video yourself where the site's terms allow it, then run "
                                 "`showtime reference <file>`")
    ext = (info.get("ext") or Path(name).suffix.lstrip(".") or "mp4").lower()
    out = dest_dir / ("source.%s" % ext)
    os.replace(str(tmp), str(out))
    return out


# ------------------------------------------------------------------ measuring

def scene_cuts(video: Path, seconds: float, threshold: float = SCENE_T, min_gap: float = MIN_SHOT) -> List[float]:
    """Cut times by ffmpeg scene detection, within the first `seconds`."""
    from ..qa import media
    vf = "scale=320:-2,select='gt(scene\\,%g)',showinfo" % threshold
    cp = ff.run_ffmpeg(["-t", "%.3f" % seconds, "-i", os.fspath(video), "-an", "-sn", "-vf", vf, "-f", "null", "-"],
                       loglevel="info", overwrite=False, check=False)
    times: List[float] = []
    for line in (cp.stderr or "").splitlines():
        if "Parsed_showinfo" not in line:
            continue
        m = media._SHOWINFO_T.search(line)
        if m:
            t = float(m.group(1))
            if t >= min_gap and (not times or t - times[-1] >= min_gap) and seconds - t >= 0.05:
                times.append(round(t, 3))
    return times


def _decode(video: Path, seconds: float, fps: float, w: int, h: int, start: float = 0.0):
    """Yield (t, rgb uint8 HxWx3) samples at `fps` (t from `start`)."""
    import numpy as np
    args = [ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error"]
    if start > 0:
        args += ["-ss", "%.3f" % start]
    args += ["-t", "%.3f" % seconds, "-i", os.fspath(video), "-an", "-sn",
            "-vf", "fps=%g,scale=%d:%d:flags=area,format=rgb24" % (fps, w, h), "-f", "rawvideo", "-"]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = w * h * 3
    i = 0
    try:
        while True:
            buf = p.stdout.read(n)
            if not buf or len(buf) < n:
                break
            yield i / fps, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            i += 1
    finally:
        p.stdout.close()
        p.wait()


def _gray(rgb):
    import numpy as np
    return rgb.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)


def _resize(g, w: int, h: int):
    """Area-average resize of a 2-D array to (h, w) (numpy only)."""
    import numpy as np
    H, W = g.shape
    ys = (np.arange(h + 1) * H / h).astype(int)
    xs = (np.arange(w + 1) * W / w).astype(int)
    c = np.cumsum(np.cumsum(np.pad(g, ((1, 0), (1, 0))), axis=0), axis=1)
    s = c[ys[1:]][:, xs[1:]] - c[ys[:-1]][:, xs[1:]] - c[ys[1:]][:, xs[:-1]] + c[ys[:-1]][:, xs[:-1]]
    area = np.outer(np.diff(ys), np.diff(xs)).astype(np.float32)
    return s / np.maximum(area, 1)


_WARP: Dict[Tuple[int, int], Any] = {}


def _warp_table(w: int, h: int):
    """Gather indices for every candidate global motion (scale about the centre, then shift)."""
    import numpy as np
    key = (w, h)
    if key in _WARP:
        return _WARP[key]
    m = 4
    yy, xx = np.mgrid[m:h - m, m:w - m]
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    cands, idx = [], []
    for s in (0.94, 0.97, 1.0, 1.03, 1.06):
        for dy in (-3, -2, -1, 0, 1, 2, 3):
            for dx in (-3, -2, -1, 0, 1, 2, 3):
                if s != 1.0 and (dx or dy) and (abs(dx) > 1 or abs(dy) > 1):
                    continue
                # next(y, x) ~ prev(cy + (y - cy) / s + dy, cx + (x - cx) / s + dx)
                sy = np.clip(np.rint(cy + (yy - cy) / s + dy), 0, h - 1).astype(int)
                sx = np.clip(np.rint(cx + (xx - cx) / s + dx), 0, w - 1).astype(int)
                cands.append((s, dx, dy))
                idx.append((sy * w + sx).ravel())
    tab = (cands, np.stack(idx), (yy * w + xx).ravel())
    _WARP[key] = tab
    return tab


def camera_step(prev, nxt) -> Tuple[str, float]:
    """The global motion between two small grey frames: (verb, strength). Verb: hold, push-in, pull-back,
    pan-left, pan-right, tilt-up, tilt-down or content (motion no single camera move explains)."""
    import numpy as np
    h, w = prev.shape
    cands, idx, inner = _warp_table(w, h)
    pf, nf = prev.ravel(), nxt.ravel()[inner]
    err = np.abs(pf[idx] - nf[None, :]).mean(axis=1)
    k0 = cands.index((1.0, 0, 0))
    e0 = float(err[k0])
    if e0 < 1.2:
        return "hold", e0
    k = int(np.argmin(err))
    s, dx, dy = cands[k]
    if k == k0 or float(err[k]) > 0.8 * e0:
        return "content", e0
    if s > 1.0:
        return "push-in", e0
    if s < 1.0:
        return "pull-back", e0
    # next(x) ~ prev(x + dx): the picture moved left by dx, so the camera panned right
    if abs(dx) >= abs(dy):
        return ("pan-right" if dx > 0 else "pan-left"), e0
    return ("tilt-down" if dy > 0 else "tilt-up"), e0


def text_measure(g) -> Tuple[float, float]:
    """(text-like share of the frame, tallest text band as a share of the frame height). A proxy: blocks
    with the dense, high-contrast, mostly vertical-stroke edges of type; bands are runs of such rows."""
    share, lines = text_lines(g)
    return share, max((ln["h"] for ln in lines), default=0.0)


def text_lines(g) -> Tuple[float, List[Dict[str, float]]]:
    """(text-like share of the frame, the lines of type: [{y0, y1, h, x0, x1}] as shares of the frame).
    Type-like blocks (dense vertical-stroke edges in horizontal runs) find where type is; the ink in those
    regions gives each line's height and extent."""
    import numpy as np
    H, W = g.shape
    gx = np.abs(np.diff(g, axis=1))
    edges = np.zeros_like(g, dtype=bool)
    edges[:, 1:] = gx > 48
    b = 8
    hb, wb = H // b, W // b
    if hb < 2 or wb < 2:
        return 0.0, []
    e = edges[:hb * b, :wb * b].reshape(hb, b, wb, b).mean(axis=(1, 3))
    s = g[:hb * b, :wb * b].reshape(hb, b, wb, b).std(axis=(1, 3))
    textish = (e > 0.10) & (e < 0.55) & (s > 35)
    # type sits in lines: keep blocks in horizontal runs of 3 or more (a product photo's edges are blobs)
    keep = np.zeros_like(textish)
    for r in range(hb):
        c = 0
        while c < wb:
            if not textish[r, c]:
                c += 1
                continue
            d = c
            while d < wb and textish[r, d]:
                d += 1
            if d - c >= 3:
                keep[r, c:d] = True
            c = d
    textish = keep
    share = float(textish.mean())
    # lines: regions of type-like blocks (block rows with gaps of up to 2 blocks merged), then the ink inside
    # each region (pixels far from the frame's ground) projected on the rows: a line is a run of rows with ink,
    # so its height is the cap (or x-height + ascenders) height even for heavy glyphs with horizontal bars
    rows = textish.any(axis=1)
    lines: List[Dict[str, float]] = []
    ground = float(np.median(g))
    ink = np.abs(g - ground) > 40
    # a flat ground (graphic frames): every run of ink rows is a line, so a single huge word (whose thick
    # strokes have too few edges to look like type) is measured too
    windows: List[Tuple[int, int, int, int]] = []
    if float((np.abs(g - ground) <= 20).mean()) >= 0.6 and ink.any():
        windows.append((0, H, 0, W))
    elif rows.any():
        rr = np.nonzero(rows)[0]
        groups: List[List[int]] = [[int(rr[0]), int(rr[0])]]
        for r in rr[1:]:
            if r - groups[-1][1] <= 3:
                groups[-1][1] = int(r)
            else:
                groups.append([int(r), int(r)])
        for r0, r1 in groups:
            xs = np.nonzero(textish[r0:r1 + 1].any(axis=0))[0]
            windows.append((max(0, (r0 - 1) * b), min(H, (r1 + 2) * b),
                            max(0, (int(xs[0]) - 1) * b), min(W, (int(xs[-1]) + 2) * b)))
    if windows:
        for y0, y1, c0, c1 in windows:
            win = ink[y0:y1, c0:c1]
            on = list(win.mean(axis=1) > 0.01) + [False]
            start = None
            for y, v in enumerate(on):
                if v and start is None:
                    start = y
                elif not v and start is not None:
                    if y - start >= 2 and (y - start) / float(H) <= 0.45:
                        cols = np.nonzero(win[start:y].any(axis=0))[0]
                        # type is strokes (part of its box inked) and never touches the frame edge; a bar,
                        # a panel or a picture edge fails one of the two
                        fill = float(win[start:y, cols[0]:cols[-1] + 1].mean()) if len(cols) else 1.0
                        edge = len(cols) and (c0 + int(cols[0]) <= 1 or c0 + int(cols[-1]) >= W - 2 or
                                              y0 + start <= 0 or y0 + y >= H)
                        if len(cols) and 0.08 <= fill <= 0.85 and not edge:
                            lines.append({"y0": round((y0 + start) / float(H), 4), "y1": round((y0 + y) / float(H), 4),
                                          "h": round((y - start) / float(H), 4),
                                          "x0": round((c0 + int(cols[0])) / float(W), 4),
                                          "x1": round((c0 + int(cols[-1]) + 1) / float(W), 4)})
                    start = None
    return share, lines


def dominant_colors(hist, n: int = 5, min_dist: float = 48.0, sums=None) -> List[Dict[str, Any]]:
    """Top colours of a 16x16x16 bin histogram, merged so no two are closer than min_dist. With `sums`
    (4096x3: the RGB sums of the pixels in each bin) each colour is the mean of its pixels, so a flat
    #F2EEE3 comes back as #f2eee3, not as its bin centre."""
    import numpy as np
    from .look import color_distance
    total = float(hist.sum()) or 1.0
    order = np.argsort(hist)[::-1]
    picked: List[List[Any]] = []     # [anchor hex (bin centre), pixel count, [(bin count, rgb sum)]]
    for b in order[:200]:
        c = float(hist[b])
        if c <= 0:
            break
        r, g, bb = (b >> 8) & 15, (b >> 4) & 15, b & 15
        centre = (r * 16 + 8, g * 16 + 8, bb * 16 + 8)
        hx = "#%02x%02x%02x" % centre
        s = np.asarray(sums[b], float) if sums is not None else np.asarray(centre, float) * c
        for p in picked:
            if color_distance(p[0], hx) < min_dist:
                p[1] += c
                p[2].append((c, s))
                break
        else:
            if len(picked) < n:
                picked.append([hx, c, [(c, s)]])
    picked.sort(key=lambda x: -x[1])
    out = []
    for anchor, c, parts in picked:
        if c / total < 0.02:
            continue
        # the colour is the mean of its core bins (a flat fill split across a bin edge by compression);
        # the thin tail of anti-aliased edge pixels would pull it toward the other colours
        top = max(pc for pc, _s in parts)
        core = [(pc, ps) for pc, ps in parts if pc >= 0.1 * top]
        n_core = sum(pc for pc, _s in core) or 1.0
        rgb = sum(ps for _pc, ps in core) / n_core
        mean = [int(round(min(255.0, max(0.0, v)))) for v in rgb]
        out.append({"hex": "#%02x%02x%02x" % tuple(mean), "share": round(c / total, 3)})
    return out


def _lum(hx: str) -> float:
    from .look import hex_rgb
    def ch(v: float) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = hex_rgb(hx)
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _sat(hx: str) -> float:
    from .look import hex_rgb
    c = hex_rgb(hx)
    return (max(c) - min(c)) / float(max(c) or 1)


def palette_roles(pal: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """{ground, ink, accent, flat}: the ground is the largest colour; ink the one with the most contrast on
    it among the low-saturation rest; accent the most saturated remaining colour. `flat` when the top
    colours cover >= 85 % of the pixels (flat fills, no photos, gradients or textures)."""
    pal = [c for c in pal if c.get("hex")]
    if not pal:
        return {}
    ground = pal[0]["hex"]
    rest = pal[1:]
    out: Dict[str, Any] = {"ground": ground}
    neutral = [c for c in rest if _sat(c["hex"]) < 0.35] or rest
    if neutral:
        out["ink"] = max(neutral, key=lambda c: contrast(c["hex"], ground))["hex"]
    colourful = [c for c in rest if c["hex"] != out.get("ink") and _sat(c["hex"]) >= 0.35]
    if colourful:
        out["accent"] = max(colourful, key=lambda c: (_sat(c["hex"]) * min(1.0, c["share"] * 20)))["hex"]
    out["flat"] = sum(c["share"] for c in pal[:4]) >= 0.85
    return out


def _motion_label(e: float) -> str:
    return "still" if e < 1.0 else "slow" if e < 4.0 else "medium" if e < 12.0 else "fast"


def measure(video: Path, *, max_seconds: float = 600.0, sheet_dir: Optional[Path] = None,
            title: str = "") -> Dict[str, Any]:
    import numpy as np
    video = Path(video)
    pr = ff.probe(video)
    if not pr.get("has_video"):
        raise ShowtimeError("%s has no video stream" % video.name, hint="pass a video file")
    dur = float(pr.get("duration") or 0.0)
    if dur <= 0.2:
        raise ShowtimeError("%s is too short to analyse (%.2fs)" % (video.name, dur))
    W, H = int(pr.get("width") or 16), int(pr.get("height") or 9)
    seconds = min(dur, float(max_seconds))
    cuts = scene_cuts(video, seconds)
    changes, pic = scene_changes(video, seconds, float(pr.get("fps") or 30.0), cuts)
    mad = pic.pop("_mad_series", None)
    changes = name_handoffs(video, changes)
    bounds = [0.0] + [c["t"] for c in changes] + [seconds]
    shots = [{"i": i + 1, "start": round(a, 3), "end": round(b, 3), "dur": round(b - a, 3)}
             for i, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])) if b - a > 0.02]

    fps = SAMPLE_FPS if seconds <= 180 else 2.0
    aw = AW if W >= H else int(round(AW * W / float(H) / 2) * 2)
    ah = int(round(aw * H / float(W) / 2) * 2) if W >= H else AW
    hists = [np.zeros(4096, np.float64) for _ in shots]
    sums = [np.zeros((4096, 3), np.float64) for _ in shots]
    layouts: List[List[Dict[str, float]]] = [[] for _ in shots]
    motion: List[List[float]] = [[] for _ in shots]
    verbs: List[Dict[str, int]] = [{} for _ in shots]
    texts: List[List[Tuple[float, float]]] = [[] for _ in shots]
    lum: List[List[float]] = [[] for _ in shots]
    sat: List[List[float]] = [[] for _ in shots]
    sheet_frames: List[Tuple[float, Any]] = []
    shot_frames: Dict[int, Tuple[float, Any]] = {}
    step_sheet = max(1, int(round(fps)))
    prev_small, prev_k = None, -1
    n = 0
    from PIL import Image

    def shot_of(t: float) -> int:
        for k, s in enumerate(shots):
            if s["start"] <= t < s["end"] or k == len(shots) - 1:
                return k
        return len(shots) - 1

    for t, rgb in _decode(video, seconds, fps, aw, ah):
        k = shot_of(t)
        q = (rgb >> 4).astype(np.int32)
        bins = (q[..., 0] * 256 + q[..., 1] * 16 + q[..., 2]).ravel()
        hists[k] += np.bincount(bins, minlength=4096)
        flat_rgb = rgb.reshape(-1, 3)
        for ch in range(3):
            sums[k][:, ch] += np.bincount(bins, weights=flat_rgb[:, ch], minlength=4096)
        g = _gray(rgb)
        mx, mn = rgb.max(axis=2).astype(np.float32), rgb.min(axis=2).astype(np.float32)
        sat[k].append(float(((mx - mn) / np.maximum(mx, 1)).mean()))
        lum[k].append(float(g.mean()))
        tshare, tlines = text_lines(g)
        texts[k].append((tshare, max((ln["h"] for ln in tlines), default=0.0)))
        if tlines:
            layouts[k].extend(dict(ln, t=round(t, 2)) for ln in tlines)
        small = _resize(g, 48, int(round(48 * ah / float(aw))) if aw >= ah else 48)
        if prev_small is not None and prev_k == k and prev_small.shape == small.shape:
            motion[k].append(float(np.abs(small - prev_small).mean()))
            v, _e = camera_step(prev_small, small)
            verbs[k][v] = verbs[k].get(v, 0) + 1
        prev_small, prev_k = small, k
        if sheet_dir is not None:
            if n % step_sheet == 0:
                sheet_frames.append((t, rgb))
            s = shots[k]
            mid = s["start"] + min(s["dur"] / 2.0, 1.0)
            if k not in shot_frames or abs(t - mid) < abs(shot_frames[k][0] - mid):
                shot_frames[k] = (t, rgb)
        n += 1
    if n == 0:
        raise ShowtimeError("could not decode frames from %s" % video.name, hint="is it a video ffmpeg can read?")

    for k, s in enumerate(shots):
        s["palette"] = dominant_colors(hists[k], n=4, sums=sums[k])
        s["brightness"] = round(float(np.mean(lum[k])), 1) if lum[k] else None
        s["saturation"] = round(float(np.mean(sat[k])), 3) if sat[k] else None
        e = float(np.mean(motion[k])) if motion[k] else 0.0
        s["motion"] = round(e, 2)
        s["motion_label"] = _motion_label(e)
        vs = verbs[k]
        if vs:
            top = sorted(vs.items(), key=lambda kv: -kv[1])[0][0]
            moving = {v: c for v, c in vs.items() if v not in ("hold", "content")}
            if moving and sum(moving.values()) >= 0.4 * sum(vs.values()):
                top = sorted(moving.items(), key=lambda kv: -kv[1])[0][0]
            s["camera"] = top
        else:
            s["camera"] = "hold"
        tx = texts[k]
        s["text_share"] = round(float(np.mean([a for a, _b in tx])), 3) if tx else 0.0
        s["text_band"] = round(float(max(b for _a, b in tx)), 3) if tx else 0.0

    overall = np.sum(hists, axis=0)
    shot_d = [s["dur"] for s in shots]
    dist = _distribution(shot_d)
    windows = []
    for w0 in range(0, int(math.ceil(seconds / 10.0))):
        a, b = w0 * 10.0, min(seconds, w0 * 10.0 + 10.0)
        if b - a >= 2.0:
            c = sum(1 for x in changes if a <= x["t"] < b)
            windows.append({"from": a, "to": round(b, 2), "changes": c, "per_10s": round(c * 10.0 / (b - a), 2)})

    rep: Dict[str, Any] = {
        "title": title or video.stem, "file": str(video.resolve()), "duration": round(dur, 3),
        "analysed_seconds": round(seconds, 3), "width": W, "height": H, "fps": pr.get("fps"),
        "aspect": _aspect(W, H), "cuts": cuts, "scene_changes": changes, "shots": shots, "shot_lengths": dist,
        "pace": {"changes": len(changes), "hard_cuts": len(cuts),
                 "per_10s": round(len(changes) * 10.0 / seconds, 2) if seconds else 0.0, "windows": windows},
        "palette": dominant_colors(overall, n=6, sums=np.sum(sums, axis=0)),
        "brightness": round(float(np.mean([x for s in lum for x in s])), 1),
        "motion": _motion_summary(shots),
        "camera": _camera_summary(shots),
        "text": _text_summary(texts, shots),
        "sample_fps": fps,
    }
    from . import spec as SP
    rep["moves"] = SP.find_moves(mad if mad is not None else [], float(pr.get("fps") or 30.0), changes)
    rep["palette_roles"] = palette_roles(rep["palette"])
    rep["layout"] = layout_summary([ln for lst in layouts for ln in lst], W, H)
    rep["changes"] = _changes(changes, pic)
    rep["sound"] = _sound(video, seconds, [c["t"] for c in changes])
    rep["_sheet"] = (sheet_frames, shot_frames)
    return rep


def _aspect(W: int, H: int) -> str:
    from .look import _aspect as a
    return a(W, H)


def _distribution(d: Sequence[float]) -> Dict[str, Any]:
    import numpy as np
    if not d:
        return {}
    arr = np.asarray(d, float)
    buckets = [("<1 s", 0, 1), ("1-2 s", 1, 2), ("2-4 s", 2, 4), ("4-8 s", 4, 8), ("8 s+", 8, 1e9)]
    return {"count": len(d), "min": round(float(arr.min()), 2), "median": round(float(np.median(arr)), 2),
            "mean": round(float(arr.mean()), 2), "max": round(float(arr.max()), 2),
            "cv": round(float(arr.std() / arr.mean()), 2) if arr.mean() else 0.0,
            "buckets": {name: int(((arr >= lo) & (arr < hi)).sum()) for name, lo, hi in buckets},
            "sequence": [round(float(x), 2) for x in d]}


def _text_summary(texts: List[List[Tuple[float, float]]], shots: List[Dict[str, Any]]) -> Dict[str, Any]:
    import numpy as np
    with_text = [s for s in shots if s["text_share"] >= 0.03]
    bands = [s["text_band"] for s in with_text if s["text_band"] > 0]
    return {"share": round(float(np.mean([a for s in texts for a, _b in s])), 3) if any(texts) else 0.0,
            "shots_with_text": len(with_text),
            "band_max": round(max(bands), 3) if bands else 0.0,
            "band_median": round(float(np.median(bands)), 3) if bands else 0.0,
            "method": "edge-texture proxy (no OCR): share of 8x8 blocks with type-like strokes; bands are runs of "
                      "rows with such strokes, as a share of the frame height (shots with text only)"}


def layout_summary(lines: List[Dict[str, float]], W: int, H: int) -> Dict[str, Any]:
    """Alignment, side margin, where type sits and the type sizes, from the lines of type seen in every
    sample (measured from the frames; no OCR). {} when there is too little type to say."""
    import numpy as np
    ls = [ln for ln in lines if ln["h"] >= 0.012 and ln["x1"] - ln["x0"] >= 0.03]
    if len(ls) < 3:
        return {}
    x0 = np.array([ln["x0"] for ln in ls])
    x1 = np.array([ln["x1"] for ln in ls])
    cx = (x0 + x1) / 2.0
    iqr = lambda a: float(np.percentile(a, 75) - np.percentile(a, 25))  # noqa: E731
    if float(np.median(np.abs(cx - 0.5))) <= 0.04 and iqr(x0) > 0.03:
        align, margin = "centre", float(min(np.percentile(x0, 10), 1 - np.percentile(x1, 90)))
    elif iqr(x0) <= 0.03:
        align, margin = "left", float(np.percentile(x0, 10))
    elif iqr(x1) <= 0.03:
        align, margin = "right", float(1 - np.percentile(x1, 90))
    else:
        align, margin = "mixed", float(np.percentile(x0, 10))
    # type sizes: line heights grouped where neighbours are within 25 % of each other
    hs = sorted(float(ln["h"]) for ln in ls)
    groups: List[List[float]] = [[hs[0]]]
    for h in hs[1:]:
        if h <= groups[-1][-1] * 1.25:
            groups[-1].append(h)
        else:
            groups.append([h])
    sizes = [{"h": round(float(np.median(g)), 3), "px_1080": int(round(float(np.median(g)) * 1080)),
              "share": round(len(g) / float(len(hs)), 2)} for g in groups if len(g) / float(len(hs)) >= 0.03]
    sizes.sort(key=lambda x: -x["h"])
    return {"align": align, "margin_x": round(margin, 3), "margin_px_1920": int(round(margin * 1920)),
            "top": round(float(np.percentile([ln["y0"] for ln in ls], 10)), 3),
            "sizes": sizes[:5], "smallest": round(hs[0], 3), "lines_seen": len(ls),
            "method": "type-like edge blocks locate the type (or a flat ground holds it); each line's ink gives its "
                      "height (cap height for capitals) and extent; no OCR"}


def _motion_summary(shots: List[Dict[str, Any]]) -> Dict[str, Any]:
    tot = sum(s["dur"] for s in shots) or 1.0
    out: Dict[str, float] = {}
    for s in shots:
        out[s["motion_label"]] = out.get(s["motion_label"], 0.0) + s["dur"]
    return {k: round(v / tot, 3) for k, v in sorted(out.items(), key=lambda kv: -kv[1])}


def _camera_summary(shots: List[Dict[str, Any]]) -> Dict[str, Any]:
    tot = sum(s["dur"] for s in shots) or 1.0
    out: Dict[str, float] = {}
    for s in shots:
        out[s["camera"]] = out.get(s["camera"], 0.0) + s["dur"]
    return {k: round(v / tot, 3) for k, v in sorted(out.items(), key=lambda kv: -kv[1])}


def motion_bursts(mad, fps: float) -> List[Tuple[float, float, str]]:
    """(peak time, length, kind) of short bursts of whole-frame change: the window of a push, whip, zoom
    or wipe between two scenes ("transition"), or a hard cut ("cut": over 60 % of the burst's change
    sits in one frame). A burst is 0.1-1.5 s where the change per frame (smoothed over 5 frames) is over
    2.5x its median of the surrounding +-2 s (and over 5 levels)."""
    import numpy as np
    mad = np.asarray(mad, float)
    n = len(mad)
    if n < 10 or not fps:
        return []
    sm = np.convolve(mad, np.ones(5) / 5.0, mode="same")
    w = int(2 * fps)
    base = np.array([np.median(sm[max(0, i - w):i + w + 1]) for i in range(n)])
    hot = (sm > np.maximum(2.5 * base, base + 4.0)) & (sm > 5.0)
    out: List[Tuple[float, float, str]] = []
    i = 0
    while i < n:
        if not hot[i]:
            i += 1
            continue
        j = i
        while j < n and hot[j]:
            j += 1
        ln = (j - i) / fps
        if 0.1 <= ln <= 1.5:
            a, b = max(0, i - 2), min(n, j + 2)
            raw = mad[a:b]
            spike = float(raw.max()) / (float(raw.sum()) or 1.0)
            k = a + int(np.argmax(raw)) if spike > 0.6 else i + int(np.argmax(sm[i:j]))
            out.append((round(k / fps, 3), round(ln, 2), "cut" if spike > 0.6 else "transition"))
        i = j
    return out


BEAT_CUT_GAP = 0.3         # hard cuts at least this far apart are separate scene changes
KIND_RANK = {"cut": 0, "fast": 1, "move": 2, "transition": 3, "scene-score": 4}


def scene_changes(video: Path, seconds: float, fps: float, cuts: Optional[Sequence[float]] = None
                  ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Scene changes of any kind: hard cuts (ffmpeg scene detection), composition changes (st.qa.rhythm:
    fast handoffs, continuous moves) and motion bursts (the window of a push or whip that keeps the
    layout). Changes closer than 0.6 s are one; a hard cut wins. -> ([{t, kind}], rhythm picture)."""
    if cuts is None:
        cuts = scene_cuts(video, seconds)
    # ffmpeg's scene score also fires inside a fast slide: on its own it is a cut, next to a composition
    # change or a transition burst it only confirms that one
    cands: List[Tuple[float, str]] = [(float(t), "scene-score") for t in cuts]
    pic: Dict[str, Any] = {}
    try:
        from ..qa import rhythm
        pic = rhythm.picture(video, fps, max_seconds=seconds)
        cands += [(float(t), "cut") for t in pic.get("hard_cuts") or []]
        cands += [(float(c["t"]), c["kind"]) for c in pic.get("layout_changes") or []]
        cands += [(t, k) for t, _ln, k in motion_bursts(pic.get("_mad"), fps)]
    except Exception as e:  # noqa: BLE001 - hard cuts still stand
        debug("reference: rhythm failed: %s" % e)
    pic["_mad_series"] = pic.pop("_mad", None)
    cands = [(t, k) for t, k in cands if MIN_SHOT <= t <= seconds - MIN_SHOT]
    cands.sort()
    groups: List[List[Tuple[float, str]]] = []
    for t, k in cands:
        if groups and t - groups[-1][-1][0] < 0.6:
            groups[-1].append((t, k))
        else:
            groups.append([(t, k)])
    out = []
    for g in groups:
        # hard cuts a beat apart (a word per beat, the ground flipping on every beat) chain into one group;
        # two or more distinct hard cuts are each a scene change (a slide or wipe has at most one)
        distinct: List[float] = []
        for t in sorted(t for t, k in g if k == "cut"):
            if not distinct or t - distinct[-1] >= BEAT_CUT_GAP:
                distinct.append(t)
        if len(distinct) >= 2:
            out += [{"t": round(t, 3), "kind": "cut"} for t in distinct]
            continue
        t, k = min(g, key=lambda x: (KIND_RANK.get(x[1], 9), x[0]))
        out.append({"t": round(t, 3), "kind": "cut" if k == "scene-score" else k})
    return out, pic


def classify_handoff(video: Path, t: float, span: float = 1.0) -> Optional[Dict[str, Any]]:
    """A colour panel wipe near scene change `t`: a full-height (or full-width) band of flat colour that is
    neither scene's ground sweeps across and leaves, inside +-span s.
    -> {kind: "wipe", panel, dir, seconds, at (the middle of the wipe)} or None."""
    import numpy as np
    t0 = max(0.0, t - span)
    fr = [rgb.astype(np.float32) for _t, rgb in _decode(video, 2 * span, 30.0, 96, 54, start=t0)]
    if len(fr) < 8:
        return None
    g0 = np.median(fr[0].reshape(-1, 3), axis=0)
    g1 = np.median(fr[-1].reshape(-1, 3), axis=0)
    best: Optional[Dict[str, Any]] = None
    for axis, dirs in ((0, ("left to right", "right to left")), (1, ("top to bottom", "bottom to top"))):
        covs: List[float] = []
        cents: List[Optional[float]] = []
        cols: List[Any] = []
        for f in fr:
            m = f.mean(axis=axis)                      # per column (axis 0) or per row (axis 1)
            flat = f.std(axis=axis).mean(axis=-1) < 10
            far = (np.linalg.norm(m - g0, axis=-1) > 60) & (np.linalg.norm(m - g1, axis=-1) > 60)
            cov = flat & far
            covs.append(float(cov.mean()))
            idx = np.nonzero(cov)[0]
            cents.append(float(idx.mean()) / len(cov) if len(idx) else None)
            cols.append(m[idx].mean(axis=0) if len(idx) else None)
        k = int(np.argmax(covs))
        if covs[k] < 0.25:
            continue
        a = k
        while a > 0 and covs[a - 1] > 0.03:
            a -= 1
        b = k
        while b < len(covs) - 1 and covs[b + 1] > 0.03:
            b += 1
        # the panel comes and goes inside the window, within 1.5 s
        if a == 0 or b == len(covs) - 1 or (b - a + 1) / 30.0 > 1.5:
            continue
        moving = [cents[i] for i in range(a, b + 1) if cents[i] is not None]
        if len(moving) < 2 or abs(moving[-1] - moving[0]) < 0.2:
            continue
        rgb = np.mean([cols[i] for i in range(a, b + 1) if cols[i] is not None], axis=0)
        cand = {"kind": "wipe", "panel": "#%02x%02x%02x" % tuple(int(round(v)) for v in rgb),
                "dir": dirs[0] if moving[-1] > moving[0] else dirs[1], "seconds": round((b - a + 1) / 30.0, 2),
                "at": round(t0 + (a + b) / 2.0 / 30.0, 3), "peak": round(covs[k], 2)}
        if best is None or cand["peak"] > best["peak"]:
            best = cand
    return best


def name_handoffs(video: Path, changes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Name the colour panel wipes among the soft scene changes; a wipe that shows up as two changes (the
    panel coming in, then leaving) is one change at the middle of the wipe."""
    out: List[Dict[str, Any]] = []
    for c in changes:
        if c["kind"] == "cut":
            out.append(c)
            continue
        try:
            w = classify_handoff(video, c["t"])
        except Exception as e:  # noqa: BLE001 - the change stands without a verb
            debug("reference: handoff at %.2f: %s" % (c["t"], e))
            w = None
        if not w:
            out.append(c)
            continue
        if any(o.get("kind") == "wipe" and abs(o["t"] - w["at"]) < 0.3 for o in out):
            continue
        out.append({"t": w["at"], "kind": "wipe", "panel": w["panel"], "dir": w["dir"], "seconds": w["seconds"]})
    out.sort(key=lambda c: c["t"])
    return out


def _changes(changes: List[Dict[str, Any]], pic: Dict[str, Any]) -> Dict[str, Any]:
    kinds: Dict[str, int] = {}
    for c in changes:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    return {"count": len(changes), "kinds": kinds, "still_fraction": pic.get("still_fraction"),
            "moving_fraction": pic.get("moving_fraction"), "longest_still_s": pic.get("longest_still_s")}


def _sound(video: Path, seconds: float, cuts: Sequence[float]) -> Optional[Dict[str, Any]]:
    import numpy as np
    try:
        from ..qa import rhythm
        mus = rhythm.music(video, seconds)
    except Exception as e:  # noqa: BLE001
        debug("reference: level curve failed: %s" % e)
        mus = None
    if not mus:
        return {"present": False}
    db = [x for x in mus["rms_db_per_half_s"]][: int(seconds * 2) + 1]
    arr = np.asarray(db, float)
    silent = float((arr < -50).mean()) if len(arr) else 1.0
    out: Dict[str, Any] = {"present": silent < 0.98, "level_db_per_half_s": db, "range_db": mus.get("range_db"),
                           "mean_db": mus.get("mean_db"), "silence_share": round(silent, 3),
                           "silent_runs": _runs(arr < -50, 0.5, 1.0)}
    try:
        ld = ff.measure_loudness(video)
        if math.isfinite(ld.get("input_i", float("nan"))):
            out["lufs"] = round(ld["input_i"], 1)
            out["lra"] = round(ld.get("input_lra", float("nan")), 1)
    except Exception:  # noqa: BLE001
        pass
    try:
        from ..audio import beats
        b = beats.analyze(video, max_seconds=seconds)
        out["bpm"] = b.get("bpm")
        out["rhythmic"] = bool(b.get("rhythmic"))
        bt = np.asarray(b.get("beats") or [], float)
        if len(bt) and cuts and out["rhythmic"]:
            on = sum(1 for c in cuts if float(np.min(np.abs(bt - c))) <= 0.1)
            out["cuts_on_beat"] = round(on / float(len(cuts)), 2)
        out["shape"] = sound_shape(video, seconds, b, db)
        out["beats"] = [round(float(x), 3) for x in bt][:2000]
        hits: List[Dict[str, Any]] = []
        for o in b.get("onsets") or []:
            if (o.get("strength") or 0) >= 0.2 and (not hits or o["t"] - hits[-1]["t"] >= 0.05):
                hits.append({"t": round(float(o["t"]), 3), "band": o.get("band")})
        out["hits"] = hits[:1000]
    except Exception as e:  # noqa: BLE001 - no audio, too short
        debug("reference: beats failed: %s" % e)
    return out


def sound_shape(video: Path, seconds: float, b: Dict[str, Any], db: Sequence[float]) -> Dict[str, Any]:
    """How the sound is built, from the beat analysis: a kick-like hit on the beats, an off-beat tick, how
    much of the energy is low end, the last big low hit, and the silence at the end."""
    import numpy as np
    bt = np.asarray(b.get("beats") or [], float)
    out: Dict[str, Any] = {}
    try:
        from ..audio import beats as B, wav
        from scipy import signal as sg
        y = wav.load(video, sr=B.AR, mono=True, duration=seconds)
        if len(y) > 4096:
            f, pxx = sg.welch(y, fs=B.AR, nperseg=4096)
            tot = float(pxx.sum()) or 1.0
            out["low_share"] = round(float(pxx[f < 150].sum()) / tot, 2)
            f2, S = B._stft_mag(y)
            low = np.sqrt(S[(f2 >= 20) & (f2 < 150)].sum(axis=0) + 1e-12)
            high = np.sqrt(S[f2 >= 2500].sum(axis=0) + 1e-12)
            if len(bt) >= 4:
                out["kick_on_beats"] = round(float(np.mean([_hit(low, x) for x in bt])), 2)
                halves = (bt[:-1] + bt[1:]) / 2.0
                out["offbeat_hits"] = round(float(np.mean([_hit(high, x) for x in halves])), 2)
            # the last big low hit: a low-band peak in the last 40 % well above the typical beat
            i0 = int(0.6 * seconds * B.FPS)
            if i0 < len(low) - 4:
                k = i0 + int(np.argmax(low[i0:]))
                beat_level = float(np.median([low[min(len(low) - 1, int(round(x * B.FPS)) + 1)] for x in bt])) if len(bt) else 0.0
                if low[k] >= 1.4 * max(beat_level, 1e-6):
                    out["last_hit"] = round(k / B.FPS, 2)
    except Exception as e:  # noqa: BLE001
        debug("reference: sound shape failed: %s" % e)
    arr = list(db or [])
    tail = 0
    for v in reversed(arr):
        if v < -50:
            tail += 1
        else:
            break
    out["tail_silence_s"] = round(tail * 0.5, 1)
    return out


def _hit(env, t: float) -> bool:
    """A hit at time t: the band's level rises by 2x (6 dB) or more within 70 ms of t."""
    from ..audio import beats as B
    i = int(round(t * B.FPS))
    if i < 3 or i + 3 >= len(env):
        return False
    pre = float(env[i - 3:i - 1].mean())
    post = float(env[i - 1:i + 3].max())
    return post >= 2.0 * pre and post > 1e-4


def sound_shape_text(sh: Dict[str, Any]) -> str:
    parts = []
    if sh.get("kick_on_beats") is not None:
        k = sh["kick_on_beats"]
        parts.append("a kick-like low hit on %s of the beats" % _pct(k) if k >= 0.2 else "no steady kick")
    if (sh.get("offbeat_hits") or 0) >= 0.4:
        parts.append("an off-beat tick on %s of the off-beats" % _pct(sh["offbeat_hits"]))
    if sh.get("low_share") is not None:
        parts.append("low end (under 150 Hz) %s of the energy" % _pct(sh["low_share"]))
    if sh.get("last_hit") is not None:
        parts.append("a last big low hit at %s" % _fmt(sh["last_hit"]))
    if sh.get("tail_silence_s"):
        parts.append("%g s of silence at the end" % sh["tail_silence_s"])
    return ", ".join(parts)


def _runs(mask, hop: float, min_len: float) -> List[List[float]]:
    out, start = [], None
    for i, v in enumerate(list(mask) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if (i - start) * hop >= min_len:
                out.append([round(start * hop, 2), round(i * hop, 2)])
            start = None
    return out


# ------------------------------------------------------------------ outputs

def write_sheets(rep: Dict[str, Any], out: Path) -> Dict[str, str]:
    from PIL import Image
    from ..qa import images
    sheet_frames, shot_frames = rep.pop("_sheet", ([], {}))
    res: Dict[str, str] = {}
    tmp = out / "frames"
    tmp.mkdir(parents=True, exist_ok=True)
    frames = sheet_frames
    if len(frames) > MAX_SHEET:
        idx = [int(round(i * (len(frames) - 1) / float(MAX_SHEET - 1))) for i in range(MAX_SHEET)]
        frames = [frames[i] for i in idx]
    items = []
    for t, rgb in frames:
        p = tmp / ("t%07.2f.jpg" % t)
        Image.fromarray(rgb).save(p, "JPEG", quality=82)
        items.append({"path": str(p), "label": _fmt(t)})
    if items:
        vertical = rep["height"] > rep["width"]
        cols = 10 if vertical else 8
        images.contact_sheet(items, out / "sheet.jpg", cols=min(cols, len(items)), thumb=120 if vertical else 180,
                             title="%s  %s  1 frame per second%s" % (rep["title"][:60], _fmt(rep["analysed_seconds"]),
                                                                     " (evenly spread)" if len(sheet_frames) > MAX_SHEET else ""))
        res["sheet"] = str(out / "sheet.jpg")
    items = []
    for k in sorted(shot_frames):
        t, rgb = shot_frames[k]
        s = rep["shots"][k]
        p = tmp / ("shot%03d.jpg" % (k + 1))
        Image.fromarray(rgb).save(p, "JPEG", quality=82)
        items.append({"path": str(p), "label": "#%d %s %.1fs" % (s["i"], _fmt(s["start"]), s["dur"]),
                      "sub": "%s %s" % (s["motion_label"], s["camera"] if s["camera"] not in ("hold", "content") else "")})
    if items:
        images.contact_sheet(items[:60], out / "shots.jpg", thumb=200 if rep["height"] <= rep["width"] else 130,
                             title="%s  %d shots%s" % (rep["title"][:60], len(rep["shots"]),
                                                       " (first 60)" if len(items) > 60 else ""))
        res["shots_sheet"] = str(out / "shots.jpg")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    return res


def write_fingerprint(video: Path, rep: Dict[str, Any], out: Path) -> Optional[str]:
    """fingerprint.npz for the near-copy guard: 64x36 grey frames at 4 per second, the shot lengths."""
    import numpy as np
    from . import guard
    fp = guard.fingerprint_video(video, max_seconds=rep["analysed_seconds"], fps=guard.REF_FPS, shots=False)
    if not len(fp["frames"]):
        return None
    p = out / "fingerprint.npz"
    np.savez_compressed(p, t=fp["t"], frames=fp["frames"],
                        shots=np.asarray(rep["shot_lengths"].get("sequence") or [], np.float32),
                        duration=np.float32(rep["analysed_seconds"]))
    return str(p)


def _fmt(t: float) -> str:
    t = max(0.0, float(t))
    return "%d:%04.1f" % (int(t // 60), t % 60)


def _pct(x: Optional[float]) -> str:
    return "-" if x is None else "%d%%" % int(round(100 * x))


def _tone_hint(rep: Dict[str, Any]) -> str:
    med = (rep.get("shot_lengths") or {}).get("median") or 0
    runs = fast_runs(rep.get("shots") or [])
    if runs:   # a beat run is a device, not the pace of the whole video
        rest = [s["dur"] for s in rep.get("shots") or [] if not any(r["start"] <= s["start"] < r["end"] for r in runs)]
        if rest:
            med = sorted(rest)[len(rest) // 2]
    snd = rep.get("sound") or {}
    if snd.get("present") and (snd.get("silence_share") or 0) > 0.5:
        return "deadpan or documentary (mostly silence)"
    if med and med < 1.5:
        return "chaotic (very short shots)"
    if med and med < 2.5:
        return "default or playful (brisk)"
    if med and med < 4.5:
        return "default or technical (measured)"
    return "polished, documentary or cinematic (long holds)"


def _transition_hint(rep: Dict[str, Any]) -> str:
    ch = (rep.get("changes") or {}).get("kinds") or {}
    tot = sum(ch.values())
    if not tot:
        return "no scene changes found: one continuous take; keep scene changes rare (a `match` or `pan` when one is needed)"
    cut, move, wipe = ch.get("cut", 0) / tot, ch.get("move", 0) / tot, ch.get("wipe", 0) / tot
    fast = (ch.get("fast", 0) + ch.get("transition", 0)) / tot
    parts = []
    if cut >= 0.25:
        snd = rep.get("sound") or {}
        on = snd.get("cuts_on_beat")
        parts.append("hard cuts (%s)%s: scenes without `data-transition`%s" % (
            _pct(cut), ", %s of changes on a beat" % _pct(on) if on is not None else "",
            ", each on a beat" if on is not None and on >= 0.5 else ""))
    wipes = [c for c in rep.get("scene_changes") or [] if c.get("kind") == "wipe"]
    if wipes:
        w = wipes[0]
        parts.append("colour panel wipes (%d, %s): a flat %s panel sweeps %s in about %.1f s and uncovers the next "
                     "scene; build it as a full-frame element that crosses the frame (or transition `wipe` "
                     "shape linear)" % (len(wipes), _pct(wipe), w.get("panel"), w.get("dir"), w.get("seconds") or 0.5))
    if fast >= 0.25:
        parts.append("fast handoffs (%s): `push` or `whip-pan` 0.3-0.5 s, one direction" % _pct(fast))
    if move >= 0.25:
        parts.append("continuous moves (%s): `blur-dissolve`, `match` or `pan` 0.6-1 s" % _pct(move))
    return "; ".join(parts) or "a mix of cuts and moves: one primary handoff plus one accent (references/transitions.md)"


CAMERA_MAP = {"push-in": "a camera push (`data-st=\"camera\"`, zoom up on a focus)",
              "pull-back": "a pull-back (camera zoom down, or `through` inverse)",
              "pan-left": "a pan (transition `pan`, or a camera path that travels)",
              "pan-right": "a pan (transition `pan`, or a camera path that travels)",
              "tilt-up": "a vertical camera travel (camera path)", "tilt-down": "a vertical camera travel (camera path)",
              "content": "motion inside the frame (animated elements, footage), camera still",
              "hold": "held frames"}


def fast_runs(shots: Sequence[Dict[str, Any]], max_len: float = 0.8, min_count: int = 3) -> List[Dict[str, Any]]:
    """Runs of min_count or more consecutive short shots (a word per beat, a flurry of cuts)."""
    out: List[Dict[str, Any]] = []
    run: List[Dict[str, Any]] = []
    for s in list(shots) + [{"dur": 1e9}]:
        if s["dur"] <= max_len:
            run.append(s)
            continue
        if len(run) >= min_count:
            ds = [x["dur"] for x in run]
            out.append({"start": run[0]["start"], "end": run[-1]["end"], "count": len(run),
                        "every": round(sorted(ds)[len(ds) // 2], 2)})
        run = []
    return out


def _house_styles() -> List[str]:
    """Composer styles with a kick on every beat."""
    try:
        from ..audio import compose
        return [n for n, v in compose.STYLES.items() if v.get("drums") == "house"]
    except Exception:  # noqa: BLE001
        return []


def brief_lines(rep: Dict[str, Any], target: Optional[float] = None) -> List[str]:
    """The storyboard brief: the style to carry over and what never to take."""
    sl = rep.get("shot_lengths") or {}
    med = sl.get("median") or rep["analysed_seconds"]
    pace = rep["pace"]["per_10s"]
    lines = ["**Carry over (the style):**", ""]
    if target:
        k = max(1, int(round(len(rep.get("shots") or [1]) * float(target) / max(0.5, float(rep["analysed_seconds"])))))
        lines.append("- Pace: %.1f scene changes per 10 s, median shot %.1f s -> about %d %s in a %g s video "
                     "(vary them like the reference: shortest %.1f s, longest %.1f s)." % (
                         pace, med, k, "shot or scene" if k == 1 else "shots or scenes", target, sl.get("min") or 0,
                         sl.get("max") or 0))
    else:
        lines.append("- Pace: %.1f scene changes per 10 s, median shot %.1f s (shortest %.1f s, longest %.1f s); scale the "
                     "scene count to your length." % (pace, med, sl.get("min") or 0, sl.get("max") or 0))
    seq = sl.get("sequence") or []
    if len(seq) >= 3:
        lines.append("- Rhythm: shot lengths run %s (spread %.2f: %s)." % (
            " / ".join("%.1f" % x for x in seq[:14]) + (" ..." if len(seq) > 14 else ""), sl.get("cv") or 0,
            "even, metronomic" if (sl.get("cv") or 0) < 0.3 else "varied"))
    snd = rep.get("sound") or {}
    bpm = snd.get("bpm")
    for r in fast_runs(rep.get("shots") or [])[:3]:
        beat = 60.0 / float(bpm) if bpm else None
        lines.append("- Beat run: %d changes from %s to %s, one every %.2f s%s: keep it (one word or image per beat; "
                     "a single word held one beat reads as part of the run)." % (
                         r["count"], _fmt(r["start"]), _fmt(r["end"]), r["every"],
                         " (one beat at %g BPM)" % round(float(bpm)) if beat and abs(r["every"] - beat) <= 0.08 else ""))
    lines.append("- Scene changes: %s." % _transition_hint(rep))
    cam = rep.get("camera") or {}
    moves = [(k, v) for k, v in cam.items() if k not in ("hold", "content") and v >= 0.1]
    if moves:
        lines.append("- Camera: %s." % "; ".join("%s for %s of the time" % (CAMERA_MAP.get(k, k), _pct(v)) for k, v in moves[:3]))
    else:
        lines.append("- Camera: mostly still (%s); the motion is in the elements." % ", ".join(
            "%s %s" % (k, _pct(v)) for k, v in list(cam.items())[:2]))
    mo = rep.get("motion") or {}
    lines.append("- Motion energy: %s." % ", ".join("%s %s" % (k, _pct(v)) for k, v in list(mo.items())[:3]))
    pal = rep.get("palette") or []
    roles = rep.get("palette_roles") or {}
    if pal:
        gl = _lum(roles["ground"]) if roles.get("ground") else None
        ground = ("dark" if gl < 0.1 else "light" if gl > 0.45 else "mid-tone") if gl is not None else (
            "dark" if rep.get("brightness", 128) < 90 else "light" if rep.get("brightness", 128) > 160 else "mid-tone")
        named = ", ".join("%s %s" % (k, roles[k]) for k in ("ground", "ink", "accent") if roles.get(k))
        lines.append("- Palette (sampled from the frames): %s (a %s ground; all: %s)%s. A same-style video keeps these "
                     "colours: they are the tokens in `style.css`. Use the brand's or the user's colours instead only "
                     "when there is a brand kit, the user asks, or the reference is another company's ad whose colours "
                     "are its brand." % (
                         named or " ".join(c["hex"] for c in pal[:5]), ground,
                         " ".join("%s %s" % (c["hex"], _pct(c["share"])) for c in pal[:5]),
                         "; flat fills only: no gradients, photos, glows or textures" if roles.get("flat") else ""))
    lay = rep.get("layout") or {}
    tx = rep.get("text") or {}
    if lay:
        sizes = lay.get("sizes") or []
        lines.append("- Type and layout: %s%s; type sizes (the ink height of a line: cap height for capitals) about %s of the frame height "
                     "(%s px at 1080). Keep every line of text at one of these sizes: no body copy smaller than the "
                     "smallest. Font size = that height / the face's cap-height ratio (about 0.7 for most sans, "
                     "0.86 for a tall condensed face). Match the face by eye in shots.jpg (weight, width, case) with "
                     "an installed font (`showtime assets font <family>`). Measured from the frames, no OCR." % (
                         {"left": "left-aligned", "right": "right-aligned", "centre": "centred"}.get(lay["align"], "mixed alignment"),
                         " on a side margin of about %s of the width (%d px at 1920)" % (_pct(lay["margin_x"]), lay["margin_px_1920"])
                         if lay["align"] != "centre" else "",
                         " / ".join(_pct(x["h"]) for x in sizes) or "?", " / ".join(str(x["px_1080"]) for x in sizes) or "?"))
    elif tx.get("shots_with_text"):
        lines.append("- Type: text on screen in %d of %d shots; the tallest text line is about %s of the frame height "
                     "(%d px at 1080) (an estimate from edge texture, no OCR)." % (
                         tx["shots_with_text"], len(rep["shots"]), _pct(tx.get("band_max")),
                         int(round((tx.get("band_max") or 0) * 1080))))
    else:
        lines.append("- Type: little or no text on screen; the picture carries it.")
    if snd.get("present"):
        s = "- Sound: %s LUFS, range %s dB, silence %s" % (snd.get("lufs", "?"), snd.get("range_db", "?"),
                                                            _pct(snd.get("silence_share")))
        if bpm:
            s += ", about %g BPM%s" % (round(float(bpm)), ", %s of scene changes on a beat" % _pct(snd.get("cuts_on_beat"))
                                       if snd.get("cuts_on_beat") is not None else "")
        sh = snd.get("shape") or {}
        desc = sound_shape_text(sh)
        if desc:
            s += ". Built from %s" % desc
        if (sh.get("kick_on_beats") or 0) >= 0.6 and bpm:
            styles = _house_styles()
            s += (". Make a new bed with the same build: a synth score (`ST.score`, references/synth-score.md) with a "
                  "kick on every beat at %g BPM%s%s%s, or `showtime audio compose --bpm %g%s`" % (
                      round(float(bpm)), ", an off-beat tick" if (sh.get("offbeat_hits") or 0) >= 0.4 else "",
                      ", the last low hit" if sh.get("last_hit") is not None else "",
                      ", silence at the end" if sh.get("tail_silence_s") else "", round(float(bpm)),
                      " --style %s" % "|".join(styles[:2]) if styles else ""))
            s += "; not a bed of another genre, and never the reference's own track."
        else:
            s += "; pick or make your own track with that shape (`showtime audio music pick`), never the reference's own."
        lines.append(s)
    else:
        lines.append("- Sound: silent reference; choose the sound on its own terms.")
    lines.append("- Tone to start from: %s (references/tones.md)." % _tone_hint(rep))
    lines += ["", "**Never (content):** its words and lines, logos and marks, footage, shots or compositions "
              "recreated frame by frame, characters, and its music track. Your subject, words and facts come from "
              "the user. `showtime qa` fails a render that comes too close (near-copy guard).", "",
              "**Build:** `showtime new <template> <job>/project --job <job>` links `style.css` after the theme, so "
              "the reference's colours and margins win over the template's. The reference wins over the look history "
              "too: `showtime check` does not flag a look that follows it (references/reference.md §2).", "",
              "**Credit:** \"Style reference: %s\" is in credits.txt and share.txt." % credit_title(rep)]
    return lines


def style_css(rep: Dict[str, Any]) -> str:
    """style.css: the reference's palette, margin and type sizes as CSS tokens; its theme-token lines make a
    template's page take the reference's look when linked after the theme."""
    roles = rep.get("palette_roles") or {}
    lay = rep.get("layout") or {}
    L = ["/* The look of the style reference \"%s\", measured by `showtime reference` (palette sampled from its" % (
        rep.get("title") or "reference").replace("*/", ""),
         "   frames; margin and type sizes measured from the ink of each line of type). Link it after the theme so these",
         "   tokens win over the template's: <link rel=\"stylesheet\" href=\"style.css\">. */", ":root {"]
    for k in ("ground", "ink", "accent"):
        if roles.get(k):
            L.append("  --ref-%s: %s;" % (k, roles[k]))
    if lay.get("margin_x") and lay.get("align") != "centre":
        L.append("  --ref-margin-x: %.2fcqw;" % (100 * lay["margin_x"]))
    for i, sz in enumerate(lay.get("sizes") or [], 1):
        L.append("  --ref-type-%d: %.2fcqh;   /* ink (cap) height ~%d px at 1080: font-size = this / cap ratio */" % (
            i, 100 * sz["h"], sz["px_1080"]))
    L.append("  /* theme tokens (references/components.md) */")
    if roles.get("ground"):
        L.append("  --bg: var(--ref-ground);")
    if roles.get("ink"):
        L.append("  --fg: var(--ref-ink);")
    if roles.get("accent"):
        L.append("  --accent: var(--ref-accent);")
        if roles.get("ground") and contrast(roles["ground"], roles["accent"]) >= 3.0:
            L.append("  --accent-ink: var(--ref-ground);")
    if lay.get("margin_x") and lay.get("align") != "centre":
        L.append("  --safe-x: var(--ref-margin-x);")
    if roles.get("flat"):
        L.append("  --grain: 0; --glow: 0;   /* flat fills: no texture or glow */")
    L += ["}", ""]
    return "\n".join(L)


def credit_title(rep: Dict[str, Any]) -> str:
    src = rep.get("source") or ""
    t = rep.get("title") or "reference"
    return "%s (%s)" % (t, src) if src and is_url(src) and src not in t else t


def credit_line(rep: Dict[str, Any]) -> str:
    return "Style reference: %s" % credit_title(rep)


def to_markdown(rep: Dict[str, Any], target: Optional[float] = None) -> str:
    sl = rep.get("shot_lengths") or {}
    L: List[str] = ["# Reference: %s" % rep["title"], ""]
    L.append("Source: %s. Analysed %s of %s, %dx%d (%s)%s." % (
        rep.get("source") or rep["file"], _fmt(rep["analysed_seconds"]), _fmt(rep["duration"]), rep["width"],
        rep["height"], rep["aspect"], ", %g fps" % rep["fps"] if rep.get("fps") else ""))
    L += ["", "> " + RIGHTS_NOTE, ""]
    L += ["## Brief for the storyboard", ""] + brief_lines(rep, target) + [""]
    if rep.get("spec"):
        from . import spec as SP
        L += SP.markdown(rep["spec"])
    L += ["## Grammar at a glance", "", "| | |", "|---|---|"]
    L.append("| Shots | %d; %d scene changes (%d hard cuts by ffmpeg scene detection), %.1f per 10 s |" % (
        len(rep["shots"]), rep["pace"]["changes"], rep["pace"]["hard_cuts"], rep["pace"]["per_10s"]))
    if sl:
        L.append("| Shot lengths | min %.1f, median %.1f, mean %.1f, max %.1f s; %s |" % (
            sl["min"], sl["median"], sl["mean"], sl["max"],
            ", ".join("%s: %d" % (k, v) for k, v in sl["buckets"].items() if v)))
    if rep["pace"]["windows"] and len(rep["pace"]["windows"]) > 1:
        L.append("| Pace over time | %s |" % " ".join("%d" % w["changes"] for w in rep["pace"]["windows"]) +
                 "")
    ch = rep.get("changes") or {}
    if ch:
        L.append("| Scene changes by kind | %d: %s; still %s of the time |" % (
            ch.get("count", 0), ", ".join("%s %d" % kv for kv in sorted((ch.get("kinds") or {}).items())) or "none",
            _pct(ch.get("still_fraction"))))
    L.append("| Motion | %s |" % ", ".join("%s %s" % (k, _pct(v)) for k, v in (rep.get("motion") or {}).items()))
    L.append("| Camera | %s |" % ", ".join("%s %s" % (k, _pct(v)) for k, v in (rep.get("camera") or {}).items()))
    L.append("| Palette | %s; mean brightness %s/255 |" % (
        ", ".join("%s %s" % (c["hex"], _pct(c["share"])) for c in rep.get("palette") or []), rep.get("brightness")))
    roles = rep.get("palette_roles") or {}
    if roles:
        L.append("| Palette roles | %s%s |" % (", ".join("%s %s" % (k, roles[k]) for k in ("ground", "ink", "accent") if roles.get(k)),
                                            "; flat fills" if roles.get("flat") else ""))
    tx = rep.get("text") or {}
    L.append("| Text on screen | %s of the frame is type-like on average; %d shots with text; largest band %s of the "
             "height (estimate) |" % (_pct(tx.get("share")), tx.get("shots_with_text", 0), _pct(tx.get("band_max"))))
    lay = rep.get("layout") or {}
    if lay:
        L.append("| Layout | %s, side margin %s of the width (%d px at 1920), type starts %s from the top; ink heights of lines %s "
                 "(estimate) |" % (lay["align"], _pct(lay["margin_x"]), lay["margin_px_1920"], _pct(lay.get("top")),
                                   ", ".join("%s (%d px, %s of lines)" % (_pct(x["h"]), x["px_1080"], _pct(x["share"]))
                                             for x in lay.get("sizes") or [])))
    wipes = [c for c in rep.get("scene_changes") or [] if c.get("kind") == "wipe"]
    if wipes:
        L.append("| Wipes | %s |" % ", ".join("%s %s panel %s" % (_fmt(c["t"]), c.get("panel"), c.get("dir")) for c in wipes))
    snd = rep.get("sound") or {}
    if snd.get("present"):
        L.append("| Sound | %s LUFS, level range %s dB, silence %s%s |" % (
            snd.get("lufs", "?"), snd.get("range_db", "?"), _pct(snd.get("silence_share")),
            ", about %g BPM" % round(float(snd["bpm"])) if snd.get("bpm") else ""))
        L.append("| Level curve (0.5 s) | `%s` |" % spark(snd.get("level_db_per_half_s") or []))
        if sound_shape_text(snd.get("shape") or {}):
            L.append("| Sound shape | %s |" % sound_shape_text(snd["shape"]))
    else:
        L.append("| Sound | none |")
    L += ["", "## Shots", "", "| # | start | length | palette | motion | camera | text |", "|---|---|---|---|---|---|---|"]
    for s in rep["shots"][:80]:
        L.append("| %d | %s | %.1f s | %s | %s | %s | %s |" % (
            s["i"], _fmt(s["start"]), s["dur"], " ".join(c["hex"] for c in s.get("palette") or []),
            s["motion_label"], s["camera"], _pct(s["text_share"]) if s["text_share"] >= 0.03 else "-"))
    if len(rep["shots"]) > 80:
        L.append("| ... | | %d more shots in reference.json | | | | |" % (len(rep["shots"]) - 80))
    L += ["", "Files: sheet.jpg (1 frame per second), shots.jpg (one frame per shot), style.css (the palette, margin "
          "and type sizes as CSS tokens), reference.json (all numbers), fingerprint.npz (small grey frames for the "
          "near-copy guard).", ""]
    return "\n".join(L)


def spark(db: Sequence[float], width: int = 60) -> str:
    """The level curve as text: one character per step, from silence to loud."""
    if not db:
        return ""
    chars = " .:-=+*#"
    step = max(1, int(math.ceil(len(db) / float(width))))
    vals = [max(db[i:i + step]) for i in range(0, len(db), step)]
    lo, hi = -60.0, max(-6.0, max(vals))
    return "".join(chars[max(0, min(len(chars) - 1, int((v - lo) / (hi - lo) * (len(chars) - 1))))] if v > lo else " "
                   for v in vals)


def analyze(src: str, out_dir: Path, *, title: Optional[str] = None, target: Optional[float] = None,
            max_seconds: float = 600.0) -> Dict[str, Any]:
    """Measure `src` (a file path or a direct media URL) and write the reference folder."""
    t0 = time.time()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    source = str(src)
    if is_url(source):
        video = fetch(source, out_dir)
    else:
        video = Path(source).expanduser()
        if not video.is_file():
            raise ShowtimeError("reference not found: %s" % video,
                                hint="pass a video file, or a direct https:// link to one")
        source = str(video.resolve())
    rep = measure(video, max_seconds=max_seconds, sheet_dir=out_dir, title=title or _title_of(source, video))
    rep["source"] = source
    rep["kept_copy"] = str(video) if is_url(src) else None
    rep["credit"] = credit_line(rep)
    rep["rights"] = RIGHTS_NOTE
    rep.update(write_sheets(rep, out_dir))
    fp = write_fingerprint(video, rep, out_dir)
    if fp:
        rep["fingerprint"] = fp
    from . import spec as SP
    rep["spec"] = SP.build(rep)
    rep["brief"] = brief_lines(rep, target)
    (out_dir / "style.css").write_text(style_css(rep), encoding="utf-8", newline="\n")
    rep["style_css"] = str(out_dir / "style.css")
    rep["seconds"] = round(time.time() - t0, 2)
    write_json(out_dir / "reference.json", rep)
    (out_dir / "reference.md").write_text(to_markdown(rep, target), encoding="utf-8", newline="\n")
    rep["reference_md"] = str(out_dir / "reference.md")
    rep["reference_json"] = str(out_dir / "reference.json")
    return rep


def _title_of(source: str, video: Path) -> str:
    if is_url(source):
        import urllib.parse
        name = Path(urllib.parse.unquote(urllib.parse.urlsplit(source).path)).stem
        return name or urllib.parse.urlsplit(source).hostname or "reference"
    return video.stem

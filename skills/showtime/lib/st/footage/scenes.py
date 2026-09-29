"""Shot detection and contact sheets (so your agent can *see* the footage).

Detection: PySceneDetect's adaptive detector on the PyAV backend (the
OpenCV 5 backend is avoided); falls back to ffmpeg's `scdet` filter.
Contact sheets: one labelled thumbnail per shot (middle frame), or one every
N seconds, tiled into a PNG.
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .. import ff
from ..common import ShowtimeError, debug, ensure_dir
from . import util as U


def detect(video, *, threshold: Optional[float] = None, min_len: float = 0.6, method: str = "adaptive") -> List[Dict[str, Any]]:
    """[{"i", "start", "end", "duration"}] covering the whole video."""
    p = Path(video)
    pr = U.probe(p)
    dur = float(pr.get("duration") or 0.0)
    fps = float(pr.get("fps") or 30.0)
    cuts: Optional[List[float]] = None
    if method in ("adaptive", "content"):
        try:
            cuts = _pyscenedetect(p, method, threshold, max(1, int(round(min_len * fps))))
        except Exception as e:  # noqa: BLE001 - optional dependency / decode issues
            debug("PySceneDetect failed (%s); using ffmpeg scdet" % e)
    if cuts is None:
        cuts = _scdet(p, threshold if threshold is not None and method == "scdet" else 10.0)
    cuts = sorted(c for c in cuts if min_len <= c <= dur - min_len / 2)
    merged: List[float] = []
    for c in cuts:
        if not merged or c - merged[-1] >= min_len:
            merged.append(c)
    edges = [0.0] + merged + [dur]
    return [{"i": i, "start": round(a, 3), "end": round(b, 3), "duration": round(b - a, 3)}
            for i, (a, b) in enumerate(zip(edges[:-1], edges[1:])) if b > a]


def _pyscenedetect(p: Path, method: str, threshold: Optional[float], min_frames: int) -> List[float]:
    from scenedetect import AdaptiveDetector, ContentDetector, SceneManager, open_video
    video = open_video(str(p), backend="pyav")
    sm = SceneManager()
    sm.auto_downscale = True
    if method == "content":
        det = ContentDetector(threshold=threshold or 27.0, min_scene_len=min_frames)
    else:
        det = AdaptiveDetector(adaptive_threshold=threshold or 3.0, min_scene_len=min_frames)
    sm.add_detector(det)
    sm.detect_scenes(video=video, show_progress=False)
    out = []
    for start, _end in sm.get_scene_list():
        sec = start.get_seconds() if hasattr(start, "get_seconds") else float(start.seconds)
        if sec > 0:
            out.append(float(sec))
    return out


def _scdet(p: Path, threshold: float) -> List[float]:
    fd, tmp = tempfile.mkstemp(prefix="st-scdet-", suffix=".txt")
    os.close(fd)
    try:
        ff.run_ffmpeg(["-i", str(p), "-an", "-vf", "scale=320:-2,scdet=threshold=%g,metadata=mode=print:file=%s"
                       % (threshold, ff.filter_path(tmp)), "-f", "null", "-"])
        text = Path(tmp).read_text(encoding="utf-8", errors="replace")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return [float(m.group(1)) for m in re.finditer(r"lavfi\.scd\.time=([\d.]+)", text)]


def grab(video, t: float, width: int = 320):
    """One frame at `t` seconds as a PIL image (accurate seek)."""
    from PIL import Image
    cp = subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-ss", "%.3f" % max(0.0, t),
                         "-i", str(video), "-frames:v", "1", "-vf", "scale=%d:-2" % width, "-f", "image2pipe",
                         "-c:v", "png", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if cp.returncode != 0 or not cp.stdout:
        return None
    return Image.open(io.BytesIO(cp.stdout)).convert("RGB")


def grab_many(video, times: Sequence[float], width: int = 320, jobs: int = 3) -> List[Any]:
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        return list(ex.map(lambda t: grab(video, t, width), times))


def contact_sheet(video, times: Sequence[float], out_png, labels: Optional[Sequence[str]] = None,
                  cols: int = 4, thumb_w: int = 320, title: Optional[str] = None) -> Path:
    from PIL import Image, ImageDraw
    from .fontfiles import pil_font
    imgs = grab_many(video, times, thumb_w)
    ok = [im for im in imgs if im is not None]
    if not ok:
        raise ShowtimeError("could not extract frames from %s" % Path(video).name)
    th = ok[0].height
    cols = max(1, min(cols, len(imgs)))
    rows = (len(imgs) + cols - 1) // cols
    pad, lab_h, head = 8, 24, 40 if title else 0
    W = cols * thumb_w + (cols + 1) * pad
    H = head + rows * (th + lab_h + pad) + pad
    sheet = Image.new("RGB", (W, H), (18, 18, 20))
    d = ImageDraw.Draw(sheet)
    f = pil_font(16)
    if title:
        d.text((pad, 10), title, fill=(235, 235, 235), font=pil_font(20))
    for k, im in enumerate(imgs):
        r, c = divmod(k, cols)
        x, y = pad + c * (thumb_w + pad), head + pad + r * (th + lab_h + pad)
        if im is not None:
            sheet.paste(im.resize((thumb_w, th)), (x, y))
        lab = labels[k] if labels and k < len(labels) else U.fmt_time(times[k])
        d.text((x + 2, y + th + 3), lab, fill=(220, 220, 220), font=f)
    out = Path(out_png)
    ensure_dir(out.parent)
    sheet.save(out)
    return out


def scenes_with_sheet(video, out_dir, **kw) -> Dict[str, Any]:
    p = Path(video)
    sc = detect(p, **kw)
    times = [s["start"] + min(s["duration"] / 2, 1.0 if s["duration"] > 2 else s["duration"] / 2) for s in sc]
    labels = ["#%d %s (%.1fs)" % (s["i"], U.fmt_time(s["start"]), s["duration"]) for s in sc]
    od = ensure_dir(out_dir)
    sheet = contact_sheet(p, times, od / (p.stem + ".scenes.png"), labels,
                          cols=5 if len(sc) > 12 else 4, title="%s - %d shot(s)" % (p.name, len(sc)))
    from ..common import write_json
    js = write_json(od / (p.stem + ".scenes.json"), {"source": str(p.resolve()), "scenes": sc})
    return {"scenes": sc, "sheet": str(sheet), "json": str(js)}


PERIODIC_MAX = 60


def periodic_plan(duration: float, every: float, start: float = 0.0, end: Optional[float] = None,
                  max_frames: int = PERIODIC_MAX) -> Dict[str, Any]:
    """Times for a periodic sheet over [start, end): one every `every` s, capped at max_frames
    (then spread evenly; `capped` says so)."""
    end = duration if end is None else min(float(end), duration)
    start = max(0.0, min(float(start), end))
    span = max(0.0, end - start)
    want = max(1, int(round(span / max(every, 0.02))))
    n = max(1, min(max_frames, want))
    step = span / n if n else span
    return {"times": [start + step * (i + 0.5) for i in range(n)], "step": step, "capped": want > max_frames,
            "wanted": want, "start": start, "end": end}


def periodic_sheet(video, out_png, every: float = 2.0, max_frames: int = PERIODIC_MAX,
                   start: float = 0.0, end: Optional[float] = None) -> Path:
    p = Path(video)
    dur = float(U.probe(p).get("duration") or 0.0)
    plan = periodic_plan(dur, every, start, end, max_frames)
    n = len(plan["times"])
    rng = "" if (plan["start"] <= 0 and plan["end"] >= dur) else " (%.2f-%.2fs)" % (plan["start"], plan["end"])
    return contact_sheet(p, plan["times"], out_png, cols=6 if n > 30 else 5 if n > 12 else 4,
                         title="%s%s - every %.2gs" % (p.name, rng, plan["step"]))

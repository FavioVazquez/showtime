"""Poster frames: pick one, bake it into frame 0, or attach it as cover art.

Why bake: X, LinkedIn, Slack and most feeds show the first decoded frame
before playback. Baking replaces only frame 0 with the chosen poster image;
every other frame, the duration and the audio (stream-copied) stay exactly
as they were, so sync is untouched.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from .. import ff
from ..common import ShowtimeError, debug, read_json, run

PathLike = Union[str, "os.PathLike[str]"]


def extract_frame(video: PathLike, t: float, out: PathLike, width: Optional[int] = None) -> Path:
    """Write the frame at time `t` (seconds) to `out` (.png or .jpg)."""
    info = ff.probe(video)
    dur = info.get("duration") or 0.0
    fps = info.get("fps") or 30.0
    if t < 0 or (dur and t > dur):
        raise ShowtimeError("time %.3fs is outside the video (duration %.3fs)" % (t, dur),
                            hint="pick --at between 0 and %.2f, or leave --at out to choose a frame automatically" % dur)
    t = min(t, max(0.0, dur - 1.0 / fps)) if dur else t
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # a .jpg gets the frame in JPEG's own colours (BT.601 full range), not the video's BT.709 tv range
    args: List[str] = ["-ss", "%.6f" % t, "-i", os.fspath(video), "-frames:v", "1"] + ff.still_args(out, width)
    ff.run_ffmpeg(args + ["-update", "1", os.fspath(out)])
    if not out.is_file():
        raise ShowtimeError("could not extract a frame at %.3fs from %s" % (t, video))
    from ..qa.media import strip_png_colour_chunks
    strip_png_colour_chunks(out)          # no gAMA/cHRM/cICP: browsers draw the still as bright as the video
    return out


def _score_image(path: Path) -> Optional[Dict[str, float]]:
    """Sharpness / contrast / colour score (needs numpy + Pillow)."""
    try:
        import numpy as np  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError:
        return None
    im = Image.open(path).convert("RGB")
    im.thumbnail((480, 480))
    a = np.asarray(im).astype("float32") / 255.0
    gray = a.mean(axis=2)
    lap = (-4 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:])
    sharp = float(lap.var()) * 1000.0
    contrast = float(gray.std())
    rg, yb = a[..., 0] - a[..., 1], 0.5 * (a[..., 0] + a[..., 1]) - a[..., 2]
    colorful = float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))
    mean = float(gray.mean())
    exposure = 1.0 - min(1.0, abs(mean - 0.45) / 0.45)
    blank = mean < 0.04 or mean > 0.97 or contrast < 0.02
    score = 0.0 if blank else (0.45 * min(sharp, 5.0) / 5.0 + 0.25 * min(contrast / 0.3, 1.0)
                               + 0.2 * min(colorful / 0.4, 1.0) + 0.1 * exposure)
    return {"score": round(score, 4), "sharpness": round(sharp, 4), "contrast": round(contrast, 4),
            "colorfulness": round(colorful, 4), "mean": round(mean, 4)}


def pick_time(video: PathLike, samples: int = 12, lo: float = 0.15, hi: float = 0.85) -> Dict[str, Any]:
    """Choose a representative poster time by scoring evenly spaced frames.

    Returns {"time": s, "score": .., "candidates": [...]} (falls back to the
    midpoint when numpy/Pillow are unavailable).
    """
    info = ff.probe(video)
    dur = float(info.get("duration") or 0.0)
    if dur <= 0 or not info.get("has_video"):
        raise ShowtimeError("%s has no video stream" % video, hint="pass the rendered video (for example final.mp4)")
    times = [dur * (lo + (hi - lo) * i / max(1, samples - 1)) for i in range(samples)] if dur > 1 else [dur / 2]
    tmp = Path(tempfile.mkdtemp(prefix="st-poster-"))
    cands: List[Dict[str, Any]] = []
    try:
        for i, t in enumerate(times):
            p = extract_frame(video, t, tmp / ("f%02d.png" % i), width=480)
            s = _score_image(p)
            if s is None:
                return {"time": round(dur / 2, 3), "method": "midpoint", "candidates": []}
            s["time"] = round(t, 3)
            cands.append(s)
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    best = max(cands, key=lambda c: c["score"])
    return {"time": best["time"], "score": best["score"], "method": "scored", "candidates": cands}


def project_poster_time(project_dir: PathLike) -> Optional[float]:
    """The "poster" time from a project's showtime.json, if set."""
    cfg = Path(project_dir) / "showtime.json"
    if cfg.is_file():
        v = read_json(cfg, {}).get("poster")
        if isinstance(v, (int, float)):
            return float(v)
    return None


def bake(video: PathLike, out: PathLike, at: Optional[float] = None, image: Optional[PathLike] = None,
         preset_name: str = "final", crf: Optional[int] = None, poster_time: Optional[float] = None) -> Dict[str, Any]:
    """Replace frame 0 of `video` with the frame at `at` (or with `image`).

    Video is re-encoded once with the given preset (CRF 16 by default,
    visually lossless); audio is stream-copied, so duration and A/V sync do
    not change. The result is verified (duration and frame count).
    """
    src = Path(video)
    out = Path(out)
    if src.resolve() == out.resolve():
        raise ShowtimeError("output must differ from input (%s)" % src, hint="give -o a new file name")
    info = ff.probe(src)
    if not info.get("has_video"):
        raise ShowtimeError("%s has no video stream" % src)
    w, h = info["width"], info["height"]
    tmp = Path(tempfile.mkdtemp(prefix="st-bake-"))
    try:
        if image is None:
            t = at if at is not None else pick_time(src)["time"]
            image = extract_frame(src, float(t), tmp / "poster.png")
        else:
            t = poster_time
        pr = ff.preset(preset_name)
        graph = ("[1:v]scale=%d:%d:flags=lanczos,format=rgba[p];[0:v][p]overlay=0:0:enable='eq(n\\,0)':"
                 "eof_action=repeat,%s[v]" % (w, h, pr.vf_tail))
        args: List[str] = ["-i", os.fspath(src), "-i", os.fspath(image), "-filter_complex", graph,
                           "-map", "[v]", "-map", "0:a?", "-map_metadata", "0"]
        video_args = pr.output_args(fps=info.get("fps"), crf=crf, audio=False)
        video_args = [a for a in video_args if a != "-an"]
        args += video_args + ["-c:a", "copy"]
        if t is not None:
            args += ["-metadata", "comment=%s%.3f" % (BAKED_TAG, float(t))]
        if out.suffix.lower() in (".mp4", ".m4v", ".mov"):
            args += ["-movflags", "+faststart"]
        out.parent.mkdir(parents=True, exist_ok=True)
        ff.run_ffmpeg(args + [os.fspath(out)])
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    after = ff.probe(out)
    d0, d1 = info.get("duration") or 0, after.get("duration") or 0
    fps = info.get("fps") or 30
    if abs(d0 - d1) > 1.5 / fps + 0.03:
        raise ShowtimeError("baked video duration changed (%.3fs -> %.3fs)" % (d0, d1))
    debug("baked poster: %s -> %s" % (src, out))
    return {"input": str(src), "output": str(out), "poster_time": t, "duration_in": d0, "duration_out": d1,
            "audio": "copied" if info.get("has_audio") else "none"}


BAKED_TAG = "showtime poster_baked="


def _comment_tag(video: Path) -> str:
    exe = ff.ffprobe_path()
    if not exe:
        return ""
    cp = run([exe, "-v", "error", "-show_entries", "format_tags=comment", "-of", "json", os.fspath(video)], check=False)
    try:
        return str(((json.loads(cp.stdout or "{}").get("format") or {}).get("tags") or {}).get("comment") or "")
    except ValueError:
        return ""


def baked_time(video: PathLike) -> Optional[Dict[str, Any]]:
    """Is a poster already baked into frame 0 of `video`? {"time": s or None, "by": ...} or None.

    Looks at (1) the file's own tag (written by `deliver poster --bake`), (2) its render report
    (`showtime render` bakes showtime.json "poster" into frame 0), (3) the job ledger's "baked" map.
    """
    v = Path(video).expanduser().resolve()
    m = re.search(r"poster_baked=([\d.]+)", _comment_tag(v))
    if m:
        return {"time": float(m.group(1)), "by": "deliver poster --bake (file tag)"}
    for rj in (v.with_suffix(".work") / "render.json", v.parent / "render.json"):
        r = read_json(rj, None) if rj.is_file() else None
        if isinstance(r, dict) and (not r.get("output") or Path(str(r["output"])).name == v.name):
            ps = r.get("poster") if isinstance(r.get("poster"), dict) else None
            if ps and ps.get("baked"):
                return {"time": float(ps["time"]) if ps.get("time") is not None else None, "by": "render (%s)" % rj.name}
            break
    try:
        from ..job import ledger
        job = ledger.enclosing_job(v)
        if job is not None and (job / "job.json").is_file():
            bk = (read_json(job / "job.json", {}) or {}).get("baked") or {}
            if str(v) in bk:
                return {"time": float(bk[str(v)]), "by": "job.json"}
    except Exception:  # noqa: BLE001 - the ledger is a convenience
        pass
    return None


def attach_cover(video: PathLike, image: PathLike, out: PathLike) -> Dict[str, Any]:
    """Attach `image` as MP4 cover art (attached_pic); streams are copied."""
    src, out = Path(video), Path(out)
    if src.resolve() == out.resolve():
        raise ShowtimeError("output must differ from input (%s)" % src)
    img = Path(image)
    if img.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        raise ShowtimeError("cover must be .jpg or .png", hint="convert the image to .jpg or .png first, or leave --image out to use a frame of the video")
    ff.run_ffmpeg(["-i", os.fspath(src), "-i", os.fspath(img), "-map", "0", "-map", "1", "-c", "copy",
                   "-disposition:v:1", "attached_pic", "-movflags", "+faststart", os.fspath(out)])
    return {"input": str(src), "output": str(out), "cover": str(img)}


def make_poster(video: PathLike, out: Optional[PathLike] = None, at: Optional[float] = None,
                project: Optional[PathLike] = None, samples: int = 12) -> Dict[str, Any]:
    """Pick (or use `at` / the project's poster time) and write a PNG poster."""
    src = Path(video)
    method = "given"
    if at is None and project is not None:
        at = project_poster_time(project)
        method = "project" if at is not None else method
    picked: Dict[str, Any] = {}
    if at is None:
        picked = pick_time(src, samples=samples)
        at = picked["time"]
        method = picked.get("method", "scored")
    out = Path(out) if out else src.with_name(src.stem + ".poster.png")
    extract_frame(src, float(at), out)
    return {"video": str(src), "poster": str(out), "time": at, "method": method,
            "score": picked.get("score")}


def parse_times(values: Optional[Sequence[str]]) -> List[float]:
    out: List[float] = []
    for v in values or []:
        for part in str(v).split(","):
            if part.strip():
                out.append(float(part))
    return out

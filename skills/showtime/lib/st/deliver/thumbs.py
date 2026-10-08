"""Thumbnails (default 1280x720 JPEG under 2 MB, the YouTube limit)."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from .. import ff
from ..common import ShowtimeError
from .exports import choose_fit, video_filter
from .poster import extract_frame, pick_time

PathLike = Union[str, "os.PathLike[str]"]
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
MAX_BYTES = 2 * 1024 * 1024


def parse_size(s: str) -> Tuple[int, int]:
    try:
        w, h = s.lower().split("x")
        wi, hi = int(w), int(h)
    except ValueError:
        raise ShowtimeError("invalid size %r (use WIDTHxHEIGHT, e.g. 1280x720)" % s)
    if wi < 16 or hi < 16 or wi > 8192 or hi > 8192:
        raise ShowtimeError("size out of range: %s" % s)
    return wi, hi


def thumbnail(src: PathLike, out: Optional[PathLike] = None, at: Optional[float] = None,
              size: str = "1280x720", fit: str = "auto", focus_x: float = 0.5, focus_y: float = 0.5,
              max_bytes: int = MAX_BYTES) -> Dict[str, Any]:
    """Make a thumbnail from a video (frame at `at`, or auto-picked) or an image."""
    src_p = Path(src)
    if not src_p.is_file():
        raise ShowtimeError("file not found: %s" % src_p, hint="pass the video (or an image) to make the thumbnail from")
    W, H = parse_size(size)
    out_p = Path(out) if out else src_p.with_name(src_p.stem + ".thumb.jpg")
    if out_p.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
        raise ShowtimeError("thumbnail must be .jpg, .png or .webp", hint="end the -o file name in .jpg, .png or .webp")
    tmp = Path(tempfile.mkdtemp(prefix="st-thumb-"))
    method = "image"
    try:
        if src_p.suffix.lower() in IMAGE_EXT:
            frame = src_p
        else:
            if at is None:
                at = pick_time(src_p)["time"]
                method = "auto"
            else:
                method = "given"
            frame = extract_frame(src_p, float(at), tmp / "frame.png")
        info = ff.probe(frame)
        sw, sh = int(info.get("width") or W), int(info.get("height") or H)
        mode = choose_fit(sw, sh, W, H, fit)
        graph = video_filter(sw, sh, W, H, mode, focus_x, focus_y).replace(
            "," + ff.BT709_VF + ",format=yuv420p", "")
        out_p.parent.mkdir(parents=True, exist_ok=True)
        ext = out_p.suffix.lower()
        if ext in (".jpg", ".jpeg") and graph.endswith("[v]"):
            graph = graph[:-3] + "," + ff.JPEG_VF + "[v]"     # JPEG's own colours (BT.601 full range), as posters
        q = 2
        while True:
            args = ["-i", os.fspath(frame), "-filter_complex", graph, "-map", "[v]", "-frames:v", "1"]
            if ext in (".jpg", ".jpeg"):
                args += ["-q:v", str(q)]
            elif ext == ".webp":
                args += ["-quality", str(max(50, 95 - 5 * (q - 2)))]
            ff.run_ffmpeg(args + ["-update", "1", os.fspath(out_p)])
            if out_p.stat().st_size <= max_bytes or ext == ".png" or q >= 12:
                break
            q += 2
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    n = out_p.stat().st_size
    return {"source": str(src_p), "output": str(out_p), "width": W, "height": H, "fit": mode,
            "time": at, "method": method, "size_bytes": n, "under_2mb": n <= MAX_BYTES}

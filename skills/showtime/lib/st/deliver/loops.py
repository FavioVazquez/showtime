"""Silent image loops for READMEs, docs and chat: animated WebP and GIF.

Both come from one master video, scaled to a width (never enlarged), at a
lower frame rate, optionally cut to a --from/--to window, and fitted under a
size cap:

  gif   two passes: palettegen builds the best 256 colours for the clip
        (stats_mode=diff weighs what moves), paletteuse maps each frame to
        it with ordered (Bayer) dithering, which keeps flat motion-graphics
        colours clean and compresses far better than error diffusion;
        diff_mode=rectangle only re-codes the part of a frame that changed.
  webp  libwebp lossy animation (quality 80 to start), much smaller than a
        GIF at the same size and supported by every current browser and by
        GitHub; ship the GIF next to it as the fallback.

When a file lands over the cap, the next attempt lowers the WebP quality,
then the frame rate, then the width, scaled by how far over it was, until it
fits or reaches the floor (240 px wide, 10 fps) and says what to change.
"""
from __future__ import annotations

import math
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .. import ff
from ..common import ShowtimeError, log

PathLike = Union[str, "os.PathLike[str]"]

MIN_WIDTH = 240
MIN_FPS = 10.0         # below this motion stutters; the width gives way first
MIN_QUALITY = 55       # WebP quality floor (below it text and edges smear)
MAX_ATTEMPTS = 6
LONG_LOOP_S = 15.0     # README loops read best short; longer ones get a note


def _even(x: float) -> int:
    return max(2, int(round(x / 2.0)) * 2)


def gif_fps(fps: float) -> float:
    """GIF frame delays are whole hundredths of a second: the nearest rate that keeps time exactly."""
    return 100.0 / max(2, round(100.0 / max(fps, 1.0)))


def _scale_chain(fps: float, width: int) -> str:
    return "fps=%s,scale=%d:-2:flags=lanczos" % (ff._fps_str(fps), width)


def _range_args(start: float, dur: Optional[float]) -> List[str]:
    a: List[str] = []
    if start > 0:
        a += ["-ss", "%.3f" % start]
    if dur:
        a += ["-t", "%.3f" % dur]
    return a


def encode_gif(src: PathLike, out: Path, start: float, dur: Optional[float], width: int, fps: float,
               colors: int = 256) -> None:
    chain = _scale_chain(fps, width)
    with tempfile.TemporaryDirectory(prefix="st-gif-") as td:
        pal = Path(td) / "palette.png"
        ff.run_ffmpeg(_range_args(start, dur) + ["-i", os.fspath(src), "-vf",
                      "%s,palettegen=max_colors=%d:stats_mode=diff" % (chain, colors), "-frames:v", "1",
                      "-update", "1", os.fspath(pal)])
        ff.run_ffmpeg(_range_args(start, dur) + ["-i", os.fspath(src), "-i", os.fspath(pal), "-filter_complex",
                      "[0:v]%s[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle" % chain,
                      "-an", "-loop", "0", "-f", "gif", os.fspath(out)])


def webp_encoder() -> str:
    for name in ("libwebp_anim", "libwebp"):
        if ff.has_encoder(name):
            return name
    raise ShowtimeError("this ffmpeg build has no WebP encoder (libwebp)",
                        why="animated WebP needs ffmpeg built with libwebp; the builds `showtime setup` "
                            "installs have it",
                        hint="run `showtime doctor` to see which ffmpeg is in use, or export `--targets gif`")


def encode_webp(src: PathLike, out: Path, start: float, dur: Optional[float], width: int, fps: float,
                quality: int = 80) -> None:
    ff.run_ffmpeg(_range_args(start, dur) + ["-i", os.fspath(src), "-vf", _scale_chain(fps, width),
                  "-an", "-c:v", webp_encoder(), "-lossless", "0", "-quality", str(int(quality)),
                  "-compression_level", "5", "-loop", "0", "-f", "webp", os.fspath(out)])


def export_loop(src: PathLike, kind: str, out: PathLike, *, width: int, fps: float,
                max_mb: Optional[float], start: Optional[float] = None, end: Optional[float] = None,
                info: Optional[Dict[str, Any]] = None, name: Optional[str] = None) -> Dict[str, Any]:
    """Write a looping `kind` ('gif' or 'webp') of src[start:end] to `out`. Returns a report dict."""
    if kind not in ("gif", "webp"):
        raise ShowtimeError("unknown loop format %r (gif or webp)" % kind)
    info = info or ff.probe(src)
    if not info.get("has_video"):
        raise ShowtimeError("%s has no video stream" % src, hint="pass the rendered video (for example final.mp4)")
    total = float(info.get("duration") or 0.0)
    s = max(0.0, float(start or 0.0))
    e = float(end) if end is not None else total
    if total and e > total + 0.05:
        raise ShowtimeError("--to %.2fs is past the end of %s (%.2fs)" % (e, Path(src).name, total))
    e = min(e, total) if total else e
    if e - s < 0.2:
        raise ShowtimeError("the loop window %.2f-%.2fs is empty or too short" % (s, e),
                            hint="--from must be before --to (seconds or mm:ss)")
    dur = e - s
    warnings: List[str] = []
    if dur > LONG_LOOP_S:
        warnings.append("%.1fs is long for a loop (size grows with length); a 3-12 s --from/--to window "
                        "reads better and stays small" % dur)
    sw = int(info.get("display_width") or info.get("width") or 0)
    src_fps = float(info.get("fps") or 30.0)
    w = _even(min(width, sw)) if sw else _even(width)
    f = min(float(fps), src_fps)
    q = 80
    window = dur if (s > 0 or e < total - 0.01) else None
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    attempts: List[Dict[str, Any]] = []
    rng = (" %.2f-%.2fs" % (s, e)) if (s > 0 or e < total - 0.05) else ""
    log("%s loop%s -> %s (%d px wide, %.3g fps%s)" % (kind, rng, out.name, w, f,
                                                    ", under %g MB" % max_mb if max_mb else ""))
    if kind == "gif":
        f = gif_fps(f)
    for _ in range(MAX_ATTEMPTS):
        if kind == "gif":
            encode_gif(src, out, s, window, w, f)
        else:
            encode_webp(src, out, s, window, w, f, q)
        size = out.stat().st_size
        attempts.append({"width": w, "fps": round(f, 3), "quality": q if kind == "webp" else None,
                         "size_bytes": size})
        if not max_mb or size <= max_mb * 1e6:
            break
        # bytes scale roughly with pixels x frames: shrink by how far over the cap it landed, with margin
        need = max_mb * 1e6 / size * 0.92
        if kind == "webp" and q > MIN_QUALITY and need >= 0.6:
            q = max(MIN_QUALITY, int(q - 50 * (1 - need)))   # mild overshoot: quality alone
            continue
        if kind == "webp":
            q = MIN_QUALITY
        f_new = max(MIN_FPS, round(f * math.sqrt(need) * 2) / 2.0)
        if kind == "gif":
            f_new = min(f, 100.0 / math.ceil(100.0 / f_new - 1e-9))
        rest = need / (f_new / f)
        w_new = min(w, _even(max(MIN_WIDTH, w * math.sqrt(rest))))
        if f_new >= f - 0.01 and w_new >= w:
            break   # at the floor
        f, w = f_new, w_new
    size = out.stat().st_size
    if max_mb and size > max_mb * 1e6:
        raise ShowtimeError("%s %s is %.2f MB, over the %g MB cap even at %d px and %.3g fps" % (
            kind.upper(), out.name, size / 1e6, max_mb, w, f),
            hint="loop a shorter window (--from/--to), or raise --max-mb")
    if len(attempts) > 1:
        a0 = attempts[0]
        warnings.append("fitted under %g MB: %d px / %.3g fps%s (first try %.2f MB)" % (
            max_mb, w, f, (" / quality %d" % q) if kind == "webp" else "", a0["size_bytes"] / 1e6))
    meta = read_loop_info(out)
    return {
        "target": name or kind, "format": kind, "output": str(out), "fit": "scale",
        "width": meta.get("width") or w, "height": meta.get("height"), "fps": round(f, 3),
        "frames": meta.get("frames"), "loops_forever": meta.get("loops_forever"), "duration": round(dur, 3),
        "from": round(s, 3), "to": round(e, 3), "size_bytes": size, "max_mb": max_mb,
        "quality": q if kind == "webp" else None, "attempts": attempts, "loudness": {},
        "warnings": warnings, "picture": None,
    }


def read_loop_info(path: PathLike) -> Dict[str, Any]:
    """Width, height, frame count and whether it loops forever, read from the GIF/WebP file itself
    (not every ffmpeg build decodes animated WebP, so this does not go through ffprobe)."""
    b = Path(path).read_bytes()
    out: Dict[str, Any] = {"format": None, "width": None, "height": None, "frames": 0, "loops_forever": False}
    if b[:6] in (b"GIF87a", b"GIF89a"):
        out["format"] = "gif"
        out["width"] = int.from_bytes(b[6:8], "little")
        out["height"] = int.from_bytes(b[8:10], "little")
        i = b.find(b"NETSCAPE2.0")
        out["loops_forever"] = i > 0 and b[i + 11:i + 13] == b"\x03\x01" and b[i + 13:i + 15] == b"\x00\x00"
        # image descriptors: 0x2C after a graphic control extension (21 F9 04 .. .. .. .. 00)
        k, n = 0, 0
        while True:
            k = b.find(b"\x21\xf9\x04", k)
            if k < 0:
                break
            if b[k + 7:k + 9] == b"\x00\x2c":
                n += 1
            k += 3
        out["frames"] = n
        return out
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        out["format"] = "webp"
        pos = 12
        while pos + 8 <= len(b):
            tag, size = b[pos:pos + 4], int.from_bytes(b[pos + 4:pos + 8], "little")
            body = b[pos + 8:pos + 8 + size]
            if tag == b"VP8X" and len(body) >= 10:
                out["width"] = 1 + int.from_bytes(body[4:7], "little")
                out["height"] = 1 + int.from_bytes(body[7:10], "little")
            elif tag == b"ANIM" and len(body) >= 6:
                out["loops_forever"] = int.from_bytes(body[4:6], "little") == 0
            elif tag == b"ANMF":
                out["frames"] += 1
            pos += 8 + size + (size & 1)
        return out
    return out

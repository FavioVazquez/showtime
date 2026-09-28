"""Colour correction and looks for real footage.

Order of operations: correct first (auto exposure/contrast/saturation from
measured frame statistics), then a look (preset or LUT at 40-70 %), then the
BT.709 output conversion. Motion graphics and UI captures should not be
graded at all (their colours are the design).

A grade spec (EDL "grade", or `footage grade` flags):
    "none" | "auto" | "<preset>" | "<look>"              (strings)
    {"auto": true, "preset": "punch", "lut": "teal-orange" | "file.cube",
     "strength": 0.6, "filter": "<raw ffmpeg filter>"}  (object; all optional)
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import ff
from ..common import ShowtimeError, debug
from . import luts as L

PRESETS: Dict[str, str] = {
    "none": "",
    "subtle": "eq=contrast=1.03:saturation=1.04",
    "punch": "eq=contrast=1.08:saturation=1.10,curves=master='0/0 0.25/0.22 0.75/0.79 1/1'",
    "warm": "colorbalance=rs=0.025:bs=-0.025:rm=0.02:bm=-0.02:rh=0.015:bh=-0.015,eq=saturation=1.03",
    "cool": "colorbalance=rs=-0.02:bs=0.03:rm=-0.01:bm=0.02,eq=saturation=0.97",
    "film": "curves=master='0/0.04 0.5/0.5 1/0.96',eq=saturation=0.9",
    "mono": "hue=s=0,eq=contrast=1.1",
    "webcam": "eq=contrast=1.05:saturation=1.06:gamma=1.04,unsharp=5:5:0.4:3:3:0.0",
    "lowlight": "hqdn3d=1.5:1.5:6:6,eq=gamma=1.12:saturation=1.05",
}
PRESET_HELP = {
    "none": "no grade", "subtle": "a touch of contrast and colour", "punch": "firmer contrast, richer colour",
    "warm": "warmer balance", "cool": "cooler balance", "film": "lifted blacks, softer highlights, muted colour",
    "mono": "black and white", "webcam": "brighten + sharpen typical webcam footage",
    "lowlight": "denoise + lift dark footage",
}


def analyze(src, start: float = 0.0, duration: Optional[float] = None, samples: int = 8) -> Dict[str, float]:
    """Mean/10th/90th percentile luma (0..1 of the video range) and mean
    saturation measured with ffmpeg signalstats on `samples` frames."""
    from .util import probe
    pr = probe(src)
    dur = duration or max(0.1, (pr.get("duration") or 1.0) - start)
    rate = max(0.2, samples / max(dur, 0.1))
    fd, tmp = tempfile.mkstemp(prefix="st-sigstats-", suffix=".txt")
    os.close(fd)
    try:
        ff.run_ffmpeg(["-ss", "%.3f" % start, "-t", "%.3f" % dur, "-i", str(src), "-an", "-vf",
                       "fps=%.4f,scale=320:-2,signalstats,metadata=mode=print:file=%s" % (rate, ff.filter_path(tmp)),
                       "-f", "null", "-"])
        text = Path(tmp).read_text(encoding="utf-8", errors="replace")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    vals: Dict[str, List[float]] = {}
    for m in re.finditer(r"lavfi\.signalstats\.(\w+)=([-\d.]+)", text):
        vals.setdefault(m.group(1), []).append(float(m.group(2)))
    if not vals.get("YAVG"):
        raise ShowtimeError("could not measure %s (no decodable frames?)" % Path(src).name)
    bits = int(vals.get("YBITDEPTH", [8])[0]) if vals.get("YBITDEPTH") else 8
    scale = float(1 << (bits - 8))
    full = str(pr.get("color_range") or "").lower() in ("pc", "jpeg", "full") or "yuvj" in str(pr.get("pix_fmt"))
    lo, hi = (0.0, 255.0) if full else (16.0, 235.0)

    def norm(v: float) -> float:
        return max(0.0, min(1.0, (v / scale - lo) / (hi - lo)))

    avg = lambda k: sum(vals[k]) / len(vals[k])  # noqa: E731
    return {"mean": round(norm(avg("YAVG")), 4), "low": round(norm(avg("YLOW")), 4),
            "high": round(norm(avg("YHIGH")), 4), "sat": round(avg("SATAVG") / scale, 2), "frames": len(vals["YAVG"])}


def auto_filter(stats: Dict[str, float]) -> str:
    """An `eq=` correction from measured stats (bounded, never extreme)."""
    import math
    mean, low, high, sat = stats["mean"], stats["low"], stats["high"], stats["sat"]
    gamma, contrast, saturation, bright = 1.0, 1.0, 1.0, 0.0
    target = 0.46
    if mean < 0.36:
        gamma = math.log(max(mean, 0.02)) / math.log(target)
    elif mean > 0.64:
        gamma = math.log(min(mean, 0.98)) / math.log(0.56)
    gamma = max(0.85, min(1.28, gamma))
    spread = high - low
    if spread < 0.5:
        contrast = min(1.15, 0.6 / max(spread, 0.1))
    elif spread > 0.92:
        contrast = 0.97
    if low > 0.14:                       # foggy / lifted blacks
        bright = -min(0.05, (low - 0.08) * 0.4)
        contrast = max(contrast, 1.05)
    if sat < 15:
        saturation = 1.12
    elif sat < 26:
        saturation = 1.06
    elif sat > 85:
        saturation = 0.94
    parts = []
    if abs(contrast - 1) > 0.005:
        parts.append("contrast=%.3f" % contrast)
    if abs(bright) > 0.002:
        parts.append("brightness=%.3f" % bright)
    if abs(saturation - 1) > 0.005:
        parts.append("saturation=%.3f" % saturation)
    if abs(gamma - 1) > 0.005:
        parts.append("gamma=%.3f" % gamma)
    return ("eq=" + ":".join(parts)) if parts else ""


def normalize_spec(spec: Any) -> Dict[str, Any]:
    if spec in (None, False, "", "none"):
        return {}
    if spec is True:
        return {"auto": True}
    if isinstance(spec, str):
        s = spec.strip()
        if s == "auto":
            return {"auto": True}
        if s in PRESETS:
            return {"preset": s}
        if s.lower().endswith(".cube"):
            return {"lut": s}
        try:
            return {"lut": L.canonical(s)}
        except ShowtimeError:
            if "=" in s:
                return {"filter": s}
            raise ShowtimeError("unknown grade %r" % spec,
                                hint="use none, auto, a preset (%s) or a look (%s)" % (", ".join(PRESETS),
                                                                                        ", ".join(L.LOOKS)))
    if isinstance(spec, dict):
        out = dict(spec)
        if out.get("preset") and out["preset"] not in PRESETS:
            raise ShowtimeError("unknown grade preset %r (%s)" % (out["preset"], ", ".join(PRESETS)))
        return out
    raise ShowtimeError("grade must be a string or an object")


def build_filter(spec: Any, src=None, start: float = 0.0, duration: Optional[float] = None,
                 base_dir: Optional[Path] = None, cache: Optional[Dict[str, str]] = None) -> str:
    """Filter chain (comma-joined, no labels) for a grade spec on one range."""
    g = normalize_spec(spec)
    if not g:
        return ""
    chain: List[str] = []
    if g.get("auto") and src is not None:
        key = "%s|%.3f|%s" % (src, start, duration)
        if cache is not None and key in cache:
            f = cache[key]
        else:
            try:
                f = auto_filter(analyze(src, start, duration))
            except ShowtimeError as e:
                debug("auto grade skipped: %s" % e)
                f = ""
            if cache is not None:
                cache[key] = f
        if f:
            chain.append(f)
    if g.get("preset"):
        p = PRESETS[g["preset"]]
        if p:
            chain.append(p)
    lut = g.get("lut")
    if lut:
        strength = float(g.get("strength", 0.6 if not str(lut).lower().endswith(".cube") else 1.0))
        if not ff.has_filter("lut3d"):
            from ..common import warn
            warn("this ffmpeg has no lut3d filter; skipping the %s look" % lut)
        elif str(lut).lower().endswith(".cube"):
            lp = Path(lut)
            if not lp.is_absolute() and base_dir:
                lp = base_dir / lp
            chain.append(L.cube_filter(L.user_lut(lp, strength)))
        else:
            chain.append(L.cube_filter(L.ensure(lut, strength)))
    if g.get("filter"):
        chain.append(str(g["filter"]))
    return ",".join(chain)

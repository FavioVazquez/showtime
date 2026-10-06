"""Contact sheets, the loudness graph and the hearing graph (Pillow + numpy, no system fonts).

Labels use the Inter font setup installs (Pillow's bundled font as a fallback), never system fonts.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

PathLike = Union[str, "os.PathLike[str]"]

BG = (22, 24, 29)
FG = (232, 234, 240)
DIM = (154, 160, 173)
GRID = (45, 48, 57)
SEV_COLORS = {"FAIL": (229, 72, 77), "WARN": (240, 180, 41), "INFO": (110, 160, 255), "PASS": (70, 190, 110)}


_FONTS: Dict[int, Any] = {}


def font(size: int):
    """Inter (installed by setup; covers accented Latin such as a, i, o with accents), else
    Pillow's bundled font, which draws those as boxes."""
    if size in _FONTS:
        return _FONTS[size]
    from PIL import ImageFont
    f = None
    try:
        from ..footage.fontfiles import find_font
        f = ImageFont.truetype(str(find_font("inter").path), size)
    except Exception:  # noqa: BLE001 - labels must never break a sheet
        try:
            f = ImageFont.load_default(size=size)
        except TypeError:  # Pillow < 10.1: fixed bitmap font
            f = ImageFont.load_default()
    _FONTS[size] = f
    return f


def contact_sheet(items: Sequence[Dict[str, Any]], out: PathLike, *, cols: Optional[int] = None,
                  thumb: int = 320, title: str = "") -> Path:
    """items: [{path, label, sub?, mark?}] -> labelled JPEG grid at `out`.

    `mark` ("FAIL"/"WARN"/"INFO") draws a coloured border around that frame.
    """
    from PIL import Image, ImageDraw
    frames = [it for it in items if it.get("path") and Path(it["path"]).is_file()]
    if not frames:
        raise ValueError("no frames for the contact sheet")
    first = Image.open(frames[0]["path"])
    ar = first.height / float(first.width or 1)
    vertical = ar > 1.1
    if thumb <= 0:
        thumb = 200 if vertical else 320
    n = len(frames)
    if cols is None:
        cols = n if n <= 4 else (min(8, math.ceil(math.sqrt(n * 1.8))) if vertical else (3 if n <= 9 else 4 if n <= 16 else 6))
    th = int(round(thumb * ar))
    pad, lab = 8, 22
    head = 30 if title else 0
    rows = math.ceil(n / cols)
    W = pad + cols * (thumb + pad)
    H = head + pad + rows * (th + lab + pad)
    sheet = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(sheet)
    f_t, f_l, f_s = font(16), font(13), font(11)
    if title:
        d.text((pad, 7), title[:160], fill=FG, font=f_t)
    for k, it in enumerate(frames):
        x = pad + (k % cols) * (thumb + pad)
        y = head + pad + (k // cols) * (th + lab + pad)
        try:
            im = Image.open(it["path"]).convert("RGB").resize((thumb, th), Image.LANCZOS)
        except OSError:
            continue
        sheet.paste(im, (x, y))
        col = SEV_COLORS.get(str(it.get("mark") or "").upper())
        if col:
            d.rectangle([x - 2, y - 2, x + thumb + 1, y + th + 1], outline=col, width=3)
        else:
            d.rectangle([x, y, x + thumb - 1, y + th - 1], outline=GRID, width=1)
        d.text((x + 2, y + th + 4), str(it.get("label", ""))[:40], fill=FG, font=f_l)
        sub = str(it.get("sub") or "")
        if sub:
            w = d.textlength(sub, font=f_s)
            d.text((x + thumb - w - 2, y + th + 6), sub, fill=DIM, font=f_s)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(os.fspath(out), "JPEG", quality=86)
    return out


def loudness_graph(t: Sequence[float], momentary: Sequence[Optional[float]], short: Sequence[Optional[float]],
                   out: PathLike, *, target: Optional[float] = None, integrated: Optional[float] = None,
                   true_peak: Optional[float] = None, gaps: Sequence[Tuple[float, float]] = (),
                   duration: Optional[float] = None, title: str = "", width: int = 1200, height: int = 420) -> Path:
    """Momentary (thin) and short-term (thick) loudness over time, with the target line."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(im)
    L, R, T, B = 58, 16, 34, 36
    pw, ph = width - L - R, height - T - B
    lo, hi = -50.0, 0.0
    dur = duration or (t[-1] if t else 1.0) or 1.0

    def X(s: float) -> float:
        return L + pw * max(0.0, min(1.0, s / dur))

    def Y(v: float) -> float:
        return T + ph * (1 - (max(lo, min(hi, v)) - lo) / (hi - lo))

    f = font(12)
    for v in range(int(lo), int(hi) + 1, 10):
        d.line([L, Y(v), L + pw, Y(v)], fill=GRID)
        d.text((6, Y(v) - 7), "%d" % v, fill=DIM, font=f)
    step = _nice_step(dur)
    s = 0.0
    while s <= dur + 1e-6:
        d.line([X(s), T, X(s), T + ph], fill=GRID)
        d.text((X(s) - 8, T + ph + 6), _fmt_t(s), fill=DIM, font=f)
        s += step
    for a, b in gaps:
        d.rectangle([X(a), T, X(b), T + ph], fill=(60, 36, 40))
    if target is not None:
        d.line([L, Y(target), L + pw, Y(target)], fill=SEV_COLORS["PASS"], width=1)
        d.text((L + pw - 110, Y(target) - 16), "target %.0f LUFS" % target, fill=SEV_COLORS["PASS"], font=f)

    def poly(vals: Sequence[Optional[float]], color, w: int) -> None:
        pts: List[Tuple[float, float]] = []
        for tt, v in zip(t, vals):
            if v is None or not math.isfinite(v) or v < lo - 20:
                if len(pts) > 1:
                    d.line(pts, fill=color, width=w)
                pts = []
                continue
            pts.append((X(tt), Y(v)))
        if len(pts) > 1:
            d.line(pts, fill=color, width=w)

    poly(momentary, (96, 110, 140), 1)
    poly(short, (110, 180, 255), 3)
    head = title + ("   " if title else "")
    if integrated is not None:
        head += "integrated %.1f LUFS" % integrated
    if true_peak is not None:
        head += "   true peak %.1f dBTP" % true_peak
    head += "   thin: momentary 400 ms, thick: short-term 3 s"
    if gaps:
        head += "   red: silence"
    d.text((L, 9), head, fill=FG, font=font(14))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(os.fspath(out), "PNG", optimize=True)
    return out


def hearing_graph(h: Dict[str, Any], blk: Dict[str, Any], out: PathLike, *, title: str = "",
                  width: int = 1400, height: int = 620) -> Path:
    """The hearing pass on one image (st.qa.hearing). Top: loudness over time (100 ms blocks, thin; a 1 s
    average, thick; the voice and the bed apart when the stem split them), scene changes as lines with their
    names, speech as a blue band, effects as ticks, quiet stretches, jumps at cuts and a cut-off ending in red.
    Bottom: each voice line's level over the music (bars, the threshold as a line) and its words per minute."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (width, height), BG)
    d = ImageDraw.Draw(im)
    dur = float(h.get("duration") or 0.0) or (len(blk.get("programme") or []) * float(blk.get("hop", 0.1))) or 1.0
    hop = float(blk.get("hop", 0.1))
    L, R = 58, 16
    pw = width - L - R
    T1, B1 = 40, 400                       # loudness panel
    T2, B2 = 440, height - 34              # voice panel
    lo, hi = -60.0, 0.0
    red, amber, blue = SEV_COLORS["FAIL"], SEV_COLORS["WARN"], (110, 160, 255)
    f, fs = font(12), font(11)

    def X(s: float) -> float:
        return L + pw * max(0.0, min(1.0, s / dur))

    def Y(v: float) -> float:
        return T1 + (B1 - T1) * (1 - (max(lo, min(hi, v)) - lo) / (hi - lo))

    for v in range(int(lo), int(hi) + 1, 10):
        d.line([L, Y(v), L + pw, Y(v)], fill=GRID)
        d.text((6, Y(v) - 7), "%d" % v, fill=DIM, font=f)
    step = _nice_step(dur)
    s = 0.0
    while s <= dur + 1e-6:
        d.line([X(s), T1, X(s), B2], fill=GRID)
        d.text((X(s) - 8, B2 + 6), _fmt_t(s), fill=DIM, font=f)
        s += step
    # speech band, quiet stretches
    for r in h.get("lines") or []:
        d.rectangle([X(r["start"]), B1 - 8, X(r["end"]), B1 - 2], fill=(52, 78, 130))
    for q in h.get("quiet") or []:
        d.rectangle([X(q["start"]), T1, X(q["end"]), B1], fill=(60, 36, 40) if q.get("silent") else (78, 40, 44))
    # scene changes and names
    for k, sc in enumerate(h.get("scenes") or []):
        x = X(sc["start"])
        if sc["start"] > 0.05:
            for yy in range(T1, B1, 6):
                d.line([x, yy, x, yy + 3], fill=DIM)
        if sc.get("name"):
            d.text((x + 3, T1 + 2 + 13 * (k % 2)), str(sc["name"])[:22], fill=DIM, font=fs)

    def smooth(vals: List[float], n: int = 10) -> List[Optional[float]]:
        out_: List[Optional[float]] = []
        p = [10 ** ((v + 0.691) / 10) if v > -119 else 0.0 for v in vals]
        acc = 0.0
        for i, v in enumerate(p):
            acc += v
            if i >= n:
                acc -= p[i - n]
            m = acc / min(i + 1, n)
            out_.append(-0.691 + 10 * math.log10(m) if m > 0 else None)
        return out_

    def poly(vals: Sequence[Optional[float]], color, w: int, shift: float = 0.0) -> None:
        pts: List[Tuple[float, float]] = []
        for i, v in enumerate(vals):
            if v is None or v < lo - 5:
                if len(pts) > 1:
                    d.line(pts, fill=color, width=w)
                pts = []
                continue
            pts.append((X((i + 0.5) * hop - shift), Y(v)))
        if len(pts) > 1:
            d.line(pts, fill=color, width=w)

    prog = [float(v) for v in blk.get("programme") or []]
    poly(prog, (80, 92, 118), 1)
    split = bool(blk.get("voice") and blk.get("bed"))
    if split:
        poly(smooth([float(v) for v in blk["bed"]]), (236, 160, 90), 2, shift=0.45)
        poly(smooth([float(v) for v in blk["voice"]]), blue, 2, shift=0.45)
    else:
        poly(smooth(prog), blue, 3, shift=0.45)
    I = h.get("integrated_lufs")
    if I is not None:
        d.line([L, Y(I), L + pw, Y(I)], fill=SEV_COLORS["PASS"], width=1)
        d.text((L + pw - 130, Y(I) - 16), "integrated %.1f LUFS" % I, fill=SEV_COLORS["PASS"], font=f)
    # effects: ticks at the top (red when under the rest of the mix)
    for fx in h.get("sfx") or []:
        x = X(fx["t"])
        d.line([x, T1 - 8, x, T1], fill=red if fx.get("flags") else (200, 200, 210), width=2)
    # jumps at cuts
    for j in h.get("cuts") or []:
        if j.get("jump") is None:
            continue
        x = X(j["t"])
        col = red if j.get("flagged") else DIM
        if j.get("flagged") or abs(j["jump"]) >= 3:
            d.text((x + 3, Y(max(j["before"], j["after"])) - 18), "%+.0f LU" % j["jump"], fill=col, font=f)
            d.line([x - 6, Y(j["before"]), x, Y(j["before"])], fill=col, width=2)
            d.line([x, Y(j["after"]), x + 6, Y(j["after"])], fill=col, width=2)
    e = h.get("ending") or {}
    if e.get("abrupt"):
        d.rectangle([X(dur) - 6, T1, X(dur), B1], fill=red)
        d.text((X(dur) - 70, T1 + 30), "cut off", fill=red, font=f)
    # voice panel: level over the music per line, words per minute
    lo2, hi2 = -10.0, 30.0
    th = (h.get("thresholds") or {}).get("voice_over_bed_min_db", 8.0)

    def Y2(v: float) -> float:
        return T2 + (B2 - T2) * (1 - (max(lo2, min(hi2, v)) - lo2) / (hi2 - lo2))
    for v in (0, 10, 20, 30):
        d.line([L, Y2(v), L + pw, Y2(v)], fill=GRID)
        d.text((10, Y2(v) - 7), "%+d" % v, fill=DIM, font=f)
    d.line([L, Y2(th), L + pw, Y2(th)], fill=amber, width=1)
    lab = "%g dB: the music competes under this" % th
    d.text((L + pw - d.textlength(lab, font=fs) - 4, Y2(th) - 15), lab, fill=amber, font=fs)
    for r in h.get("lines") or []:
        x0, x1 = X(r["start"]), max(X(r["end"]), X(r["start"]) + 2)
        v = r.get("voice_over_bed_db")
        if v is not None:
            col = red if v < th else (blue if r.get("method") == "stem" else (120, 130, 150))
            d.rectangle([x0, min(Y2(v), Y2(0)), x1, max(Y2(v), Y2(0))], fill=col)
        if r.get("wpm") and x1 - x0 >= 26:
            d.text((x0 + 2, T2 + 2), "%d" % r["wpm"], fill=red if "fast" in r.get("flags", []) else DIM, font=fs)
    head = (title + "   " if title else "") + "loudness, 100 ms blocks (thin) and 1 s (thick%s)" % (
        ": blue voice, orange music" if split else "")
    d.text((L, 9), head, fill=FG, font=font(14))
    d.text((L, T2 - 22), "voice over the music per line (dB%s); wpm above the bars" % (
        "" if split else ", grey = estimate from between the words"), fill=FG, font=font(13))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(os.fspath(out), "PNG", optimize=True)
    return out


def thumbnail_preview(src: PathLike, out: PathLike, size: Tuple[int, int] = (168, 94)) -> Path:
    """Tiny copy of a frame, the size platforms show in search and suggestions."""
    from PIL import Image
    im = Image.open(os.fspath(src)).convert("RGB")
    im.thumbnail(size, Image.LANCZOS)
    out = Path(out)
    im.save(os.fspath(out), "PNG")
    return out


def _nice_step(dur: float) -> float:
    for s in (0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600):
        if dur / s <= 14:
            return float(s)
    return 1200.0


def _fmt_t(s: float) -> str:
    if s < 60:
        return ("%.1f" % s).rstrip("0").rstrip(".") + "s"
    return "%d:%02d" % (int(s // 60), int(s % 60))

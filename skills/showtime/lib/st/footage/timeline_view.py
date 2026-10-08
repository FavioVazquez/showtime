"""Timeline views: a PNG with a filmstrip, the waveform, the words and the
pauses for a time range, so your agent can check a cut without watching it.

  view(media, start, end, out)          one range of any video/audio file
  view_edl(edl, rendered, out_dir)      every cut of a rendered edit: a window
                                        of +-1.5 s around each join, plus the
                                        first and last seconds, 4 per page

Silences >= 0.4 s are shaded, words >= 50 ms are labelled, cut points are
red lines. Transcripts are found automatically (edit/transcripts/<stem>.json)
or passed explicitly; for an EDL the words are mapped to the output timeline.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..common import ShowtimeError, ensure_dir, read_json
from . import util as U

BG = (16, 17, 20)
FG = (230, 230, 232)
DIM = (130, 134, 142)
WAVE = (92, 180, 255)
SIL = (60, 40, 40)
CUT = (255, 70, 70)
EVENT = (255, 190, 90)


def _auto_transcript(media: Path) -> Optional[Dict[str, Any]]:
    for c in U.transcript_candidates(media) + [media.parent / "transcripts" / (media.stem + ".json")]:
        if c.is_file():
            try:
                return U.load_transcript(c)
            except ShowtimeError:
                return None
    return None


def _envelope(media: Path, start: float, end: float, cols: int):
    import numpy as np
    pr = U.probe(media)
    if not pr.get("has_audio"):
        return None
    tmp = U.cache_dir("footage") / ("tv-%s-%.3f-%.3f.wav" % (U.quick_hash(media), start, end))
    if not tmp.is_file():
        U.extract_wav(media, tmp, sr=16000, start=start, duration=max(0.05, end - start))
    x, sr = U.load_audio(tmp, sr=16000)
    if len(x) == 0:
        return None
    n = len(x)
    edges = np.linspace(0, n, cols + 1).astype(int)
    mx = np.array([np.abs(x[a:b]).max() if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])])
    rms = np.array([np.sqrt(np.mean(x[a:b] ** 2)) if b > a else 0.0 for a, b in zip(edges[:-1], edges[1:])])
    peak = max(1e-4, float(mx.max()))
    return mx / peak, rms / peak


def render_band(media: Path, start: float, end: float, words: List[Dict[str, Any]], *, width: int = 1600,
                frames: int = 8, marks: Sequence[Tuple[float, str]] = (), title: str = ""):
    """One band image (PIL) for [start, end] of `media`."""
    from PIL import Image, ImageDraw
    from .fontfiles import pil_font
    from .scenes import grab_many
    span = max(0.05, end - start)
    pr = U.probe(media)
    head_h, wave_h, words_h, ruler_h = 30, 120, 58, 22
    strip_h = 0
    thumbs = []
    if pr.get("has_video") and frames > 0:
        tw = width // frames
        times = [start + span * (i + 0.5) / frames for i in range(frames)]
        thumbs = grab_many(media, times, width=max(64, tw))
        ar = (pr.get("display_height") or 9) / float(pr.get("display_width") or 16)
        strip_h = int(round(tw * ar))
        if strip_h > 260:
            strip_h = 260
    H = head_h + strip_h + wave_h + words_h + ruler_h
    img = Image.new("RGB", (width, H), BG)
    d = ImageDraw.Draw(img)
    f_small, f_word, f_head = pil_font(13), pil_font(15), pil_font(16)
    d.text((8, 7), title or "%s  %s - %s" % (media.name, U.fmt_time(start), U.fmt_time(end)), fill=FG, font=f_head)

    def x_of(t: float) -> int:
        return int(round((t - start) / span * (width - 1)))

    y = head_h
    if thumbs:
        tw = width // frames
        for i, im in enumerate(thumbs):
            if im is None:
                continue
            im = im.copy()
            im.thumbnail((tw, strip_h))
            img.paste(im, (i * tw + (tw - im.width) // 2, y + (strip_h - im.height) // 2))
        y += strip_h
    # silences (gaps between spoken tokens >= 0.4 s)
    toks = sorted([w for w in words if w.get("type", "word") in ("word", "audio_event")], key=lambda w: w["start"])
    gaps = []
    prev = start
    for w in toks:
        if w["end"] < start or w["start"] > end:
            continue
        if w["start"] - prev >= 0.4:
            gaps.append((prev, w["start"]))
        prev = max(prev, w["end"])
    if end - prev >= 0.4:
        gaps.append((prev, end))
    for a, b in gaps:
        d.rectangle([x_of(max(a, start)), y, x_of(min(b, end)), y + wave_h + words_h], fill=SIL)
        if b - a >= 0.6:
            d.text((x_of(max(a, start)) + 3, y + 3), "%.1fs" % (b - a), fill=DIM, font=f_small)
    env = _envelope(media, start, end, width)
    mid = y + wave_h // 2
    if env is not None:
        mx, rms = env
        for i in range(width):
            h = int(mx[i] * (wave_h / 2 - 4))
            d.line([(i, mid - h), (i, mid + h)], fill=(50, 90, 130))
            h2 = int(rms[i] * (wave_h / 2 - 4))
            d.line([(i, mid - h2), (i, mid + h2)], fill=WAVE)
    else:
        d.text((8, mid - 8), "(no audio)", fill=DIM, font=f_small)
    y += wave_h
    # words, alternating rows so neighbours do not collide
    last_x = [-1000, -1000]
    for w in toks:
        if w["end"] < start or w["start"] > end or w["end"] - w["start"] < 0.05:
            continue
        x = max(0, x_of(w["start"]))
        row = 0 if x - last_x[0] > 4 else 1
        if row == 1 and x - last_x[1] <= 4:
            row = 0
        color = EVENT if w.get("type") == "audio_event" else (FG if not U.is_filler(w["text"]) else (255, 140, 140))
        d.line([(x, y), (x, y + 6)], fill=DIM)
        d.text((x + 2, y + 4 + row * 24), str(w["text"]), fill=color, font=f_word)
        tw_ = d.textlength(str(w["text"]), font=f_word) if hasattr(d, "textlength") else 8 * len(str(w["text"]))
        last_x[row] = x + int(tw_)
    y += words_h
    # ruler
    step = next(s for s in (0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60, 300) if span / s <= 16)
    t = math.ceil(start / step) * step
    while t <= end + 1e-6:
        x = x_of(t)
        d.line([(x, y), (x, y + 6)], fill=DIM)
        d.text((x + 2, y + 5), ("%.2f" % t).rstrip("0").rstrip("."), fill=DIM, font=f_small)
        t += step
    for tm, lab in marks:
        if start <= tm <= end:
            x = x_of(tm)
            d.line([(x, head_h), (x, H - ruler_h)], fill=CUT, width=2)
            if lab:
                d.text((x + 4, head_h + 2), lab, fill=CUT, font=f_small)
    return img


def view(media, start: Optional[float] = None, end: Optional[float] = None, out_png=None, *,
         transcript=None, frames: int = 8, width: int = 1600, marks: Sequence[float] = ()) -> Path:
    p = Path(media).resolve()
    pr = U.probe(p)
    dur = float(pr.get("duration") or 0.0)
    s = max(0.0, start or 0.0)
    e = min(dur, end if end is not None else dur) if dur else (end or s + 10)
    if e <= s:
        raise ShowtimeError("empty range %.2f-%.2f (the file is %.2f s long)" % (s, e, dur))
    tr = U.load_transcript(transcript) if transcript else _auto_transcript(p)
    words = tr["words"] if tr else []
    img = render_band(p, s, e, words, width=width, frames=frames, marks=[(m, "") for m in marks])
    out = Path(out_png) if out_png else U.default_edit_dir(p, create_job=True) / "views" / ("%s_%.1f-%.1f.png" % (p.stem, s, e))
    ensure_dir(out.parent)
    img.save(out)
    return out


def view_edl(edl_path, rendered=None, out_dir=None, *, window: float = 1.5, per_page: int = 4,
             width: int = 1600, frames: int = 6) -> List[Path]:
    """Views of every join in a rendered edit (output timeline)."""
    from PIL import Image
    from . import edl as E
    edl_path = Path(edl_path).resolve()
    ed = E.load(edl_path)
    rendered = Path(rendered) if rendered else ed["dir"] / "final.mp4"
    if not rendered.is_file():
        prev = ed["dir"] / "preview.mp4"
        if prev.is_file():
            rendered = prev
        else:
            raise ShowtimeError("rendered video not found: %s" % rendered,
                                hint="run `showtime edit render %s` first or pass --video" % edl_path.name)
    rep_p = rendered.with_name(rendered.stem + ".report.json")
    rep = read_json(rep_p, None) if rep_p.is_file() else None
    if rep_p.is_file():
        segs = read_json(rep_p).get("segments") or []
        segs = [dict(s, start=s["src_start"], src_end=s["src_end"]) for s in segs]
    else:
        segs = E.plan(ed)
    trs = E.load_transcripts(ed)
    words = E.map_words(segs, trs) if trs else []
    total = float(U.probe(rendered).get("duration") or 0.0)
    joins = [s["out_start"] for s in segs[1:]]
    windows: List[Tuple[float, float, List[Tuple[float, str]], str]] = []
    windows.append((0.0, min(total, 2.5), [], "start"))
    for k, t in enumerate(joins, 1):
        windows.append((max(0.0, t - window), min(total, t + window), [(t, "cut %d" % k)],
                        "cut %d at %s" % (k, U.fmt_time(t))))
    windows.append((max(0.0, total - 2.5), total, [], "end"))
    out_dir = Path(out_dir) if out_dir else ed["dir"] / "views"
    ensure_dir(out_dir)
    pages: List[Path] = []
    for pg in range(0, len(windows), per_page):
        bands = [render_band(rendered, a, b, words, width=width, frames=frames, marks=mk,
                             title="%s  |  %s  (%s - %s)" % (rendered.name, lab, U.fmt_time(a), U.fmt_time(b)))
                 for a, b, mk, lab in windows[pg:pg + per_page]]
        H = sum(b.height for b in bands) + 6 * (len(bands) - 1)
        page = Image.new("RGB", (width, H), (0, 0, 0))
        y = 0
        for b in bands:
            page.paste(b, (0, y))
            y += b.height + 6
        pth = out_dir / ("%s-cuts-%d.png" % (rendered.stem, pg // per_page + 1))
        page.save(pth)
        pages.append(pth)
    # cards: one band per card (the frames while it is on screen, its words, its in and out marked), from the
    # render's own report (the times it drew them at)
    cards = ((rep or {}).get("cards") or {}).get("items") or []
    cwin = []
    for c in cards:
        a, b = max(0.0, c["start"] - 0.6), min(total, c["end"] + 0.4)
        mk = [(c["start"], "in: %s #%d" % (c["type"], c["i"])), (c["end"], "out")]
        mk += [(it["at"], "item %d" % (k + 1)) for k, it in enumerate(c.get("items") or [])]
        cwin.append((a, b, mk, "card #%d %s %s-%s \"%s\"" % (c["i"], c["type"], U.fmt_time(c["start"]),
                                                           U.fmt_time(c["end"]), str(c.get("said", ""))[:40])))
    for pg in range(0, len(cwin), per_page):
        bands = [render_band(rendered, a, b, words, width=width, frames=frames, marks=mk,
                             title="%s  |  %s" % (rendered.name, lab)) for a, b, mk, lab in cwin[pg:pg + per_page]]
        H = sum(b.height for b in bands) + 6 * (len(bands) - 1)
        page = Image.new("RGB", (width, H), (0, 0, 0))
        y = 0
        for b in bands:
            page.paste(b, (0, y))
            y += b.height + 6
        pth = out_dir / ("%s-cards-%d.png" % (rendered.stem, pg // per_page + 1))
        page.save(pth)
        pages.append(pth)
    return pages

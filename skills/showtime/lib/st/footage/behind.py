"""The "behind" card: a big word BEHIND the speaker (the plate, the word, then the speaker cut out on top).

    {"type": "behind", "say": "much faster than ever before", "text": "Faster", "background": "dim"}

It is a card like the others (cards.py: anchored to a phrase, the job's look, the card reel), plus three
layers the EDL renderer composites around the word, in this order, under every other card and the captions:

1. the plate: "footage" (the shot itself, default), "dim" (the shot darkened), "blur" (the shot blurred: a
   background blur behind the speaker), "ground" (the look's ground colour: a background swap), a colour
   ("#0b1d3a") or an image file (a picture behind the speaker), faded in and out with the word;
2. the word, from the card reel (the look's display face, sized to the frame, its own entrance);
3. the speaker, cut out of the render's own frames: a person matte per frame (cutout.matte_stream: MODNet on
   the CPU, smoothed over time and reset at the cuts, refined at full size) merged as alpha into the same
   frames, so the person is the shot's own pixels, never a re-encoded copy.

Placement (`layout`) follows the face (YuNet, cards.face_box). 16:9: a speaker off-centre gets the word on the
free side, running behind the head to the face's centre line (the word's end tucks behind the head); a centred
one gets it centred behind the head; the word's foot sits on the chin line, so the shoulders never cover it.
9:16 and square: the word sits at the top of the safe box with the head over its lower part; when the head
leaves no room above it (a close-up), the speaker moves down for the card (a reframe-only split, like a
panel) and the plate becomes the look's ground (an image or a colour when given): there is no shot above
the speaker to show.

The render measures what the viewer will see (`measure_hidden`): the share of the word's ink behind the
speaker (from the reel's alpha and the matte) and the widest stretch of the word hidden; `edit check`
estimates the same from the face before anything renders, and reports the last render's numbers.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .. import ff
from ..common import ShowtimeError, debug, ensure_dir, read_json, write_json

PLATES = ("footage", "dim", "blur", "ground")
COLORS = ("auto", "accent", "accent-2", "fg", "white")
HIDDEN_WARN = 0.45        # over this share of the word's ink behind the speaker it no longer reads
RUN_WARN = 0.4            # a hidden stretch over this share of the word's width loses whole letters
DIM_ALPHA = 0.45
PLATE_FADE = 0.3
LINE = 0.92               # line height of the word, in em
GLYPH_EM = 0.62           # average advance of a capital in a bold display face, when the font cannot be read
MAX_CHARS = 14            # a line longer than this is a sentence, not a word behind the speaker
BEHIND_REV = 1
_ROOM_TALL = 0.25         # where the head's top meets the word in a tall frame (share of the word's height)
TUCK = 0.5                # how much of the last letter goes behind the head (16:9, a speaker off-centre)


# --------------------------------------------------------------------------------------------- spec

def check_spec(c: Dict[str, Any], where: str, errs: List[str], base: Optional[Path] = None) -> None:
    """Validate a behind card's own keys (cards.normalize_specs calls it): background, color, text."""
    bg = c.get("background")
    if bg not in (None, "", "auto") and not (isinstance(bg, str) and (bg in PLATES or _hex(bg))):
        if not isinstance(bg, str):
            errs.append("%s.background must be footage, dim, blur, ground, a colour (#rrggbb) or an image file" % where)
        else:
            p = Path(bg).expanduser()
            if base is not None and not p.is_absolute():
                p = (base / p)
            from . import util as U
            if p.suffix.lower() not in U.IMAGE_EXTS:
                errs.append("%s.background %r is not footage, dim, blur, ground, a colour (#rrggbb) or an image file"
                            % (where, bg))
            elif base is not None and not p.is_file():
                errs.append("%s.background: image not found: %s" % (where, p))
    col = c.get("color")
    if col not in (None, "") and not (isinstance(col, str) and (col in COLORS or _hex(col))):
        errs.append("%s.color must be auto, accent, accent-2, fg, white or #rrggbb" % where)
    t = c.get("text")
    if t is not None and not isinstance(t, str):
        errs.append("%s.text must be a string (the word behind the speaker)" % where)


def _hex(v: str) -> bool:
    return bool(re.fullmatch(r"#[0-9a-fA-F]{6}", str(v or "")))


def plate_of(c: Dict[str, Any], base: Optional[Path] = None) -> Dict[str, Any]:
    """{"kind": footage|dim|blur|ground|color|image, "color": "#rrggbb"?, "file": Path?} for a card."""
    bg = c.get("background")
    if bg in (None, "", "auto", "footage"):
        return {"kind": "footage"}
    if bg in ("dim", "blur", "ground"):
        return {"kind": bg}
    if _hex(bg):
        return {"kind": "color", "color": bg.lower()}
    p = Path(str(bg)).expanduser()
    if base is not None and not p.is_absolute():
        p = base / p
    return {"kind": "image", "file": str(p)}


def lines_of(c: Dict[str, Any]) -> List[str]:
    """The word's lines: the card's `text` (a newline breaks it), else the words it is anchored to."""
    t = c.get("text")
    if not t:
        t = re.sub(r"[.,;:!?…\"“”]+", "", str(c.get("said") or c.get("say") or "")).strip()
    return [ln.strip() for ln in str(t).split("\n") if ln.strip()][:2] or ["?"]


# --------------------------------------------------------------------------------------------- type

_FONT_CACHE: Dict[str, Any] = {}


def _font_key(look: Optional[Dict[str, Any]]) -> Tuple[str, int]:
    t = (look or {}).get("tokens") or {}
    fam = str(t.get("--font-display") or "'Inter'").split(",")[0].strip().strip("'\"")
    try:
        wt = int(str(t.get("--weight-display") or "700").strip())
    except ValueError:
        wt = 700
    return re.sub(r"[^a-z0-9]+", "-", fam.lower()).strip("-"), wt


def text_em(text: str, look: Optional[Dict[str, Any]] = None) -> float:
    """The width of `text` in capitals, in em, set in the look's display face (its weight and tracking);
    an average glyph when the font file cannot be read."""
    t = (look or {}).get("tokens") or {}
    up = str(text).upper()
    track = 0.0
    m = re.match(r"\s*(-?[\d.]+)em", str(t.get("--tracking-display") or ""))
    if m:
        track = 0.6 * float(m.group(1))             # the reel sets 0.6 x the look's display tracking
    key, wt = _font_key(look)
    try:
        if key not in _FONT_CACHE:
            from PIL import ImageFont
            from .fontfiles import find_font
            f = ImageFont.truetype(str(find_font(key).path), 200)
            try:
                vals = []
                for a in f.get_variation_axes():
                    nm = a.get("name")
                    nm = nm.decode("latin-1") if isinstance(nm, bytes) else str(nm)
                    vals.append(max(a["minimum"], min(a["maximum"], wt)) if "weight" in nm.lower() or "wght" in nm.lower()
                                else a["default"])
                f.set_variation_by_axes(vals)
            except Exception:  # noqa: BLE001 - a static font has no axes
                pass
            _FONT_CACHE[key] = f
        f = _FONT_CACHE[key]
        if f is None:
            raise ShowtimeError("no font")
        return float(f.getlength(up)) / 200.0 + track * max(0, len(up) - 1)
    except Exception as e:  # noqa: BLE001 - placement falls back to an average glyph
        if _FONT_CACHE.get(key, 0) is not None:
            debug("behind: font %s not measured (%s)" % (key, e))
        _FONT_CACHE[key] = None
        return GLYPH_EM * len(up) + track * max(0, len(up) - 1)


def color_css(c: Dict[str, Any], look: Optional[Dict[str, Any]], plate: str) -> str:
    """The word's colour (a CSS value): `color` when given; else the look's accent when it reads on the plate
    (dark footage, the dimmed shot or the look's ground), else its foreground on the ground, else white."""
    from ..brand import contrast
    want = c.get("color") or "auto"
    if _hex(want):
        return want
    if want in ("accent", "accent-2", "fg"):
        return "var(--%s)" % want
    if want == "white":
        return "#ffffff"
    t = (look or {}).get("tokens") or {}
    acc = str(t.get("--accent") or "")
    bg = str(t.get("--bg") or "#000000")
    if plate in ("ground", "color", "image"):
        ref = bg if plate == "ground" else (c.get("background") if _hex(c.get("background") or "") else "#000000")
        if _hex(acc) and _hex(ref) and contrast(acc, ref) >= 3.0:
            return "var(--accent)"
        return "var(--fg)" if plate == "ground" else "#ffffff"
    if _hex(acc) and contrast(acc, "#000000") >= 7.0:
        return "var(--accent)"
    return "#ffffff"


# --------------------------------------------------------------------------------------------- layout

def _safe(w: int, h: int) -> Tuple[float, float, float, float]:
    from .. import captions_rules as R
    l, t, r, b = R.safe_box(w, h)
    return l / w, t / h, r / w, b / h


def head_half_width(face: Dict[str, float], W: int, H: int) -> float:
    """Half the head's width in frame-width fractions (a head is about 0.78 of its height wide)."""
    return 0.39 * (face["chin"] - face["top"]) * H / float(W)


def moved_face(face: Dict[str, float], y0: float) -> Dict[str, float]:
    """The face once the speaker is framed into the region below y0 (the full height of the shot scaled into
    it, the face centred across)."""
    k = 1.0 - y0
    out = {key: y0 + face[key] * k for key in ("top", "bottom", "eyes", "chin") if key in face}
    out["x"] = 0.5 + (face.get("x", 0.5) - 0.5) * k
    return out


def layout(card: Dict[str, Any], W: int, H: int, face: Optional[Dict[str, float]], kind: str,
           look: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The word's box (frame fractions), its alignment and size, and for a tall close-up the speaker's new
    region. Keys: box, align, font (font size, fraction of the frame height), lines, plate, moved,
    speaker (when moved), est_hidden, est_run, kind."""
    sl, st_, sr, sb = _safe(W, H)
    lines = lines_of(card)
    n_lines = len(lines)
    nch = float(max(2, max(len(ln) for ln in lines)))
    em = max(0.5, max(text_em(ln, look) for ln in lines))
    kick = 0.032 if card.get("kicker") else 0.0           # the kicker line (frame-height fraction)
    side = card.get("side") or "auto"
    plate = plate_of(card)["kind"]
    out: Dict[str, Any] = {"kind": kind, "lines": lines, "moved": False, "em": round(em, 4), "kick": kick}
    if isinstance(card.get("box"), dict):
        b = card["box"]
        box = {k: float(b.get(k, d)) for k, d in (("x", 0.06), ("y", 0.1), ("w", 0.6), ("h", 0.3))}
        fs = min(box["w"] * W / em, (box["h"] - kick) * H / (n_lines * LINE)) / H
        al = side if side in ("left", "right", "center") else "center"
        out.update(box=box, align=al, side={"left": "right", "right": "left"}.get(al, "center"), font=round(fs, 4),
                   plate=plate)
        out.update(_estimate(out, face, W, H))
        return out
    if kind == "wide":
        if face is None:
            x0, x1, align, foot = sl + 0.03, sr - 0.03, "center", 0.52
        else:
            hw = head_half_width(face, W, H)
            off = face["x"] - 0.5
            if side == "center" or (side == "auto" and abs(off) < 0.1):
                x0, x1, align = sl + 0.01, sr - 0.01, "center"
            elif side == "left" or (side == "auto" and off > 0):
                # the speaker on the right: the word on the left, its last letter half behind the head
                x0, align = sl + 0.01, "right"
                near = face["x"] - hw
                x1 = min(sr - 0.01, max(x0 + 0.2, (near - TUCK * x0 / nch) / (1.0 - TUCK / nch)))
            else:
                x1, align = sr - 0.01, "left"
                near = face["x"] + hw
                x0 = max(sl + 0.01, min(x1 - 0.2, (near - TUCK * x1 / nch) / (1.0 - TUCK / nch)))
            foot = min(face["chin"], sb - 0.03)
        top = st_ + 0.01
        fs = min((x1 - x0) * W / em, (foot - top - kick) * H / (n_lines * LINE)) / H
        fs = min(fs, 0.42)
        hgt = kick + n_lines * LINE * fs
        box = {"x": x0, "y": max(top, foot - hgt), "w": x1 - x0, "h": hgt}
        out.update(box=box, align=align, side={"left": "right", "right": "left"}.get(align, "center"),
                   font=round(fs, 4), plate=plate)
        out.update(_estimate(out, face, W, H))
        return out
    # tall and square: the word across the top of the safe box, the head over its lower part
    x0, x1 = sl + 0.005, sr - 0.005
    top = st_ + 0.008
    fs = min((x1 - x0) * W / em, 0.3 * H / (n_lines * LINE)) / H
    hgt = kick + n_lines * LINE * fs
    box = {"x": x0, "y": top, "w": x1 - x0, "h": hgt}
    out.update(box=box, align="center", side="center", font=round(fs, 4), plate=plate)
    want_head = top + kick + _ROOM_TALL * n_lines * LINE * fs     # where the head's top should be at the lowest
    if face is not None and face["top"] < want_head and card.get("layout") != "overlay" or card.get("layout") == "split":
        ftop = face["top"] if face is not None else 0.08
        y0 = (want_head - ftop) / max(0.2, 1.0 - ftop)
        y0 = round(min(0.45, max(0.08, y0)), 4)
        out.update(moved=True, speaker={"x": 0.0, "y": y0, "w": 1.0, "h": round(1.0 - y0, 4)},
                   plate=plate if plate in ("ground", "color", "image") else "ground",
                   plate_note=None if plate in ("ground", "color", "image", "footage") else
                   "the speaker moves down for the word: a %s plate has no shot above the speaker to show, so the "
                   "look's ground is used" % plate)
        if face is not None:
            out["face_moved"] = moved_face(face, y0)
    out.update(_estimate(out, out.get("face_moved") or face, W, H))
    return out


# --------------------------------------------------------------------------------------------- estimate

def person_mask(face: Dict[str, float], W: int, H: int, gx: int = 160, gy: int = 90):
    """A coarse silhouette from the face box (frame fractions -> a gy x gx boolean grid): the head (an
    ellipse from the hair to the chin), the neck, and the shoulders widening to the bottom of the frame."""
    import numpy as np
    ys, xs = np.mgrid[0:gy, 0:gx]
    x = (xs + 0.5) / gx
    y = (ys + 0.5) / gy
    hw = head_half_width(face, W, H)
    cy = (face["top"] + face["chin"]) / 2.0
    ry = max(1e-3, (face["chin"] - face["top"]) / 2.0)
    head = ((x - face["x"]) / max(1e-3, hw)) ** 2 + ((y - cy) / ry) ** 2 <= 1.0
    neck = (np.abs(x - face["x"]) <= 0.55 * hw) & (y >= cy) & (y <= face["chin"] + 0.5 * ry)
    sh_top = face["chin"] + 0.35 * ry
    grow = np.clip((y - sh_top) / max(1e-3, 0.6 * ry), 0.0, 1.0)
    shoulders = (y >= sh_top) & (np.abs(x - face["x"]) <= hw * (1.0 + 1.9 * grow))
    return head | neck | shoulders


def _word_extent(lay: Dict[str, Any], W: int, H: int) -> Dict[str, float]:
    """Where the word's ink is (frame fractions): its box narrowed to the set width, at its alignment."""
    b = lay["box"]
    ww = min(b["w"], lay["em"] * lay["font"] * H / float(W))
    if lay.get("align") == "right":
        x = b["x"] + b["w"] - ww
    elif lay.get("align") == "left":
        x = b["x"]
    else:
        x = b["x"] + (b["w"] - ww) / 2.0
    kick = lay.get("kick") or 0.0
    return {"x": x, "y": b["y"] + kick, "w": ww, "h": max(0.01, b["h"] - kick)}


def _estimate(lay: Dict[str, Any], face: Optional[Dict[str, float]], W: int, H: int) -> Dict[str, Any]:
    if face is None:
        return {"est_hidden": None, "est_run": None}
    gx, gy = 192, 108
    mask = person_mask(face, W, H, gx, gy)
    e = _word_extent(lay, W, H)
    x0, x1 = int(round(e["x"] * gx)), int(round((e["x"] + e["w"]) * gx))
    y0, y1 = int(round((e["y"] + 0.12 * e["h"]) * gy)), int(round((e["y"] + 0.88 * e["h"]) * gy))   # cap height
    x0, x1, y0, y1 = max(0, x0), min(gx, max(x0 + 1, x1)), max(0, y0), min(gy, max(y0 + 1, y1))
    sub = mask[y0:y1, x0:x1]
    if sub.size == 0:
        return {"est_hidden": None, "est_run": None}
    cols = sub.mean(axis=0) > 0.6
    return {"est_hidden": round(float(sub.mean()), 3), "est_run": round(_longest_run(cols) / float(len(cols)), 3)}


def _longest_run(flags: Iterable[bool]) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


# --------------------------------------------------------------------------------------------- reel page

CSS = r"""
/* behind: the word sits behind the speaker (the render cuts the speaker out over it) */
.behind { justify-content: flex-start; }
.behind.al-left { align-items: flex-start; text-align: left; }
.behind.al-right { align-items: flex-end; text-align: right; }
.behind.al-center { align-items: center; text-align: center; }
.behind .kicker { margin: 0 0 calc(var(--u) * 0.6); animation: fadeIn 0.4s linear 0.2s both, fadeOut 0.3s linear var(--out) forwards; }
.behind .bw { font-family: var(--font-display); font-weight: var(--weight-display); line-height: 0.92;
  letter-spacing: calc(var(--tracking-display) * 0.6); text-transform: uppercase; color: var(--bw-color, #fff);
  font-size: var(--bw-size); white-space: nowrap; margin: 0; width: 100%; transform-origin: 50% 100%;
  text-shadow: 0 0.02em 0.1em rgb(0 0 0 / 0.3);
  animation: bwIn 0.6s var(--ease-out) both, fadeOut 0.35s linear var(--out) forwards; }
@keyframes bwIn { from { opacity: 0; transform: translateY(10%) scale(0.94); } to { opacity: 1; transform: none; } }
"""


def html(c: Dict[str, Any], dur: float, box_style: str, esc) -> str:
    """The card's scene body in the reel: the kicker and the word, nothing else (the plate and the speaker
    are composited by the render, so the reel's alpha is the word's ink)."""
    # a moved speaker (9:16) sits on an opaque plate cut in and out with the card: the word holds to that cut
    # (fading it first left the speaker on a bare plate for the last frames); otherwise it fades with the plate
    out = dur if c.get("moved") else max(0.4, dur - 0.4)
    var = "--out:%.3fs;--end:%.3fs" % (out, max(0.0, dur - 0.034))
    kick = '<p class="kicker">%s</p>' % esc(c["kicker"]) if c.get("kicker") else ""
    # fit only narrows the word to its box (the height is set here: fit would count the face's full ascent)
    words = "".join('<p class="bw" data-st="fit" data-min="0.3" data-wrap="false" data-box=".scene">%s</p>' % esc(ln)
                    for ln in c["lines"])
    return ('<div class="box behind al-%s" style="%s;%s;--bw-size:%.3fcqh;--bw-color:%s">%s%s</div>' % (
        c.get("align", "center"), box_style, var, 100.0 * c["font"], c.get("color_css") or "#fff", kick, words))


# --------------------------------------------------------------------------------------------- render

def windows(cards: Sequence[Dict[str, Any]], fps: Fraction) -> List[Dict[str, Any]]:
    """Each behind card's frame window on the output timeline: {card, f0, f1}."""
    f = float(fps)
    return [{"card": c, "f0": int(round(c["start"] * f)), "f1": int(round(c["end"] * f))}
            for c in cards if c.get("type") == "behind"]


def _seg_parts(segs: Sequence[Dict[str, Any]], results: Sequence[Dict[str, Any]], f0: int, f1: int
               ) -> List[Tuple[str, int, int]]:
    """(segment file name, first, last frame) of every segment part inside f0..f1: the matte's cache key."""
    out, at = [], 0
    for s, r in zip(segs, results):
        n = int(r.get("frames") or s["frames"])
        a, b = max(f0, at), min(f1, at + n)
        if a < b:
            out.append((Path(str(r.get("path"))).name, a - at, b - at))
        at += n
    return out


def matte_for(base: Path, win: Dict[str, Any], segs: Sequence[Dict[str, Any]], results: Sequence[Dict[str, Any]],
              fps: Fraction, W: int, H: int, cuts: Sequence[float], work: Path, engine: Any = None
              ) -> Dict[str, Any]:
    """The person matte of a behind card's frames, from the render's own base video (so it follows every
    reframe, punch-in and grade): a lossless gray FFV1 file, cached by the segments it covers. Returns the
    stats (cutout.matte_stream) with "file" and "cached"."""
    from . import cutout as CO
    f0, f1 = win["f0"], win["f1"]
    n = max(1, f1 - f0)
    key = hashlib.sha256(json.dumps([BEHIND_REV, CO.MATTE_REV, CO.DEFAULT_SHORT, W, H, str(fps),
                                     _seg_parts(segs, results, f0, f1)]).encode()).hexdigest()[:16]
    d = ensure_dir(work)
    out = d / ("matte-%s.mkv" % key)
    side = d / ("matte-%s.json" % key)
    if out.is_file() and side.is_file():
        rec = read_json(side, None)
        if isinstance(rec, dict) and rec.get("frames") == n:
            return dict(rec, file=str(out), cached=True)
    f = float(fps)
    cut_frames = sorted({int(round(t * f)) - f0 for t in cuts if f0 < int(round(t * f)) < f1})
    tmp = out.with_name(out.stem + ".part.mkv")
    from . import util as U
    pipe = CO.Pipe(CO.matte_args(tmp, W, H, U.fps_str(fps), lossless=True), "matte")
    try:
        st = CO.matte_stream(base, start=CO.seek_for_frame(f0, fps), frames=n, size=(W, H), fps=None,
                             cuts=cut_frames, engine=engine, on_frame=lambda i, buf, m: pipe.write(m.tobytes()),
                             progress="behind card %d" % win["card"]["index"])
    except BaseException:
        try:
            pipe.close()
        except ShowtimeError:
            pass
        raise
    pipe.close()
    if st["frames"] != n:
        raise ShowtimeError("the behind card at %.2f s: the matte has %d frames, the card %d" % (
            win["card"]["start"], st["frames"], n))
    tmp.replace(out)
    write_json(side, st)
    return dict(st, file=str(out), cached=False)


def _gray_frames(path: Path, start: float, n: int, w: int, h: int, alpha: bool = False):
    """n frames of `path` from `start` as uint8 h x w planes (the alpha plane with alpha=True)."""
    import numpy as np
    vf = ("alphaextract," if alpha else "") + "scale=%d:%d:flags=area,format=gray" % (w, h)
    args = [ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error"]
    if start > 0:
        args += ["-ss", "%.6f" % start]
    args += ["-i", str(path), "-an", "-vf", vf, "-frames:v", str(int(n)), "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = w * h
    try:
        while True:
            buf = p.stdout.read(size) if p.stdout else b""
            if len(buf) < size:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(h, w)
    finally:
        if p.stdout:
            p.stdout.close()
        p.wait()


def measure_hidden(matte: Path, reel: Path, offset_frames: int, n: int, fps: Fraction, W: int, H: int
                   ) -> Dict[str, Any]:
    """How much of the word the speaker hides, frame by frame: the reel's alpha (the word's ink) against the
    matte, at a quarter of the size. Over the frames where the word is fully in: the mean and worst share of
    the ink hidden, and the widest hidden stretch (columns of the word more than 60 % covered) as a share
    of its width."""
    import numpy as np
    from . import cutout as CO
    w, h = max(32, W // 4 // 2 * 2), max(18, H // 4 // 2 * 2)
    alphas = _gray_frames(reel, CO.seek_for_frame(offset_frames, fps), n, w, h, alpha=True)
    mattes = _gray_frames(matte, 0.0, n, w, h)
    rows = []
    for a, m in zip(alphas, mattes):
        ink = a.astype(np.float32) / 255.0
        tot = float(ink.sum())
        if tot <= 1.0:
            rows.append(None)
            continue
        cov = (m.astype(np.float32) / 255.0) * ink
        colink = ink.sum(axis=0)
        cols = colink > 0.5
        hid_cols = (cov.sum(axis=0) > 0.6 * colink) & cols
        xs = np.nonzero(cols)[0]
        width = int(xs[-1] - xs[0] + 1) if len(xs) else 1
        run = _longest_run(hid_cols[xs[0]:xs[-1] + 1]) if len(xs) else 0
        rows.append((tot, float(cov.sum()) / tot, run / float(width)))
    full = [r for r in rows if r is not None]
    if not full:
        return {"hidden": None, "hidden_max": None, "hidden_run": None, "frames_measured": 0}
    top = max(r[0] for r in full)
    settled = [r for r in full if r[0] >= 0.9 * top] or full
    return {"hidden": round(float(np.mean([r[1] for r in settled])), 3),
            "hidden_max": round(float(max(r[1] for r in settled)), 3),
            "hidden_run": round(float(max(r[2] for r in settled)), 3), "frames_measured": len(settled)}


def plate_entry(c: Dict[str, Any], f0: int, f1: int, fps: Fraction, look: Optional[Dict[str, Any]],
                base_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """The internal overlay entry (render_edl._overlay_graph) for the card's plate, or None for the shot
    itself. A moved speaker's plate is opaque from the first frame (the reframe is already a cut)."""
    p = c.get("plate_spec") or plate_of(c, base_dir)
    kind = c.get("plate") or p["kind"]
    if kind == "footage":
        return None
    col = None
    if kind == "ground":
        g = str(((look or {}).get("tokens") or {}).get("--bg") or "#000000")
        col = g if _hex(g) else "#000000"
    elif kind == "color":
        col = p.get("color")
    elif kind == "dim":
        col = "#000000"
    fade = 0.0 if c.get("moved") else PLATE_FADE
    return {"kind": "plate", "plate": "color" if kind in ("ground", "color", "dim") else kind,
            "color": "0x" + col[1:] if col else None, "alpha": DIM_ALPHA if kind == "dim" else 1.0,
            "file": p.get("file") if kind == "image" else None, "f0": f0, "f1": f1,
            "start": float(Fraction(f0) / fps), "duration": float(Fraction(f1 - f0) / fps), "fade": fade,
            "audio": False, "card": c["index"], "to_end": bool(c.get("to_end"))}


def person_entry(c: Dict[str, Any], matte: str, f0: int, f1: int, fps: Fraction) -> Dict[str, Any]:
    return {"kind": "person", "matte": matte, "f0": f0, "f1": f1, "start": float(Fraction(f0) / fps),
            "duration": float(Fraction(f1 - f0) / fps), "audio": False, "card": c["index"]}


def fps_tb(fps: Fraction) -> str:
    """The time base of one frame, for settb (1/30, 1001/30000)."""
    return "%d/%d" % (fps.denominator, fps.numerator)


def plate_graph(o: Dict[str, Any], src: str, W: int, H: int, fps: Fraction, image_input: Optional[int]) -> str:
    """Filter chain (no output label) for a plate entry: `src` is a split of the base (blur), else unused."""
    from . import util as U
    d = o["duration"]
    fd = min(o.get("fade") or 0.0, d / 3.0)
    if o["plate"] == "blur":
        k = 4
        chain = ["trim=start_frame=%d:end_frame=%d" % (o["f0"], o["f1"]),
                 "scale=%d:%d:flags=area" % (max(2, W // k // 2 * 2), max(2, H // k // 2 * 2)),
                 "gblur=sigma=%.1f" % max(2.0, 0.012 * W / k), "scale=%d:%d:flags=bicubic" % (W, H),
                 "eq=brightness=-0.04:saturation=0.9", "format=yuva420p"]
        if fd:
            chain += ["fade=t=in:st=%.6f:d=%.3f:alpha=1" % (o["start"], fd),
                      "fade=t=out:st=%.6f:d=%.3f:alpha=1" % (o["start"] + d - fd, fd)]
        return src + ",".join(chain)
    if o["plate"] == "image":
        chain = ["scale=%d:%d:force_original_aspect_ratio=increase" % (W, H), "crop=%d:%d" % (W, H), "setsar=1",
                 "format=yuva420p"]
    else:
        chain = ["color=c=%s@%.3f:s=%dx%d:r=%s:d=%.6f" % (o["color"], o["alpha"], W, H, U.fps_str(fps), d),
                 "format=yuva420p"]
    if fd:
        chain += ["fade=t=in:st=0:d=%.3f:alpha=1" % fd]
        if not o.get("to_end"):
            chain += ["fade=t=out:st=%.6f:d=%.3f:alpha=1" % (max(0.0, d - fd), fd)]
    chain += ["settb=expr=%s" % fps_tb(fps), "setpts=N+%d" % o["f0"]]
    head = "[%d:v]" % image_input if o["plate"] == "image" else ""
    return head + ",".join(chain)


CHOKE = (0.25, 0.9)        # matte values mapped to 0 and 1 for the composite: the soft edge holds the old background


def person_graph(o: Dict[str, Any], src: str, matte_input: int, fps: Fraction, label: str) -> List[str]:
    """Filter parts that cut the speaker out of a split of the base (`src`) with the matte file
    (input `matte_input`): the same frames, renumbered to one time base so alphamerge pairs them exactly.
    The matte is choked a little (CHOKE): its faintest edge is mostly the shot's old background, which would
    ring the speaker over the word or a new background."""
    tb = fps_tb(fps)
    lo, hi = int(round(CHOKE[0] * 255)), int(round(CHOKE[1] * 255))
    lut = "lut=c0='clip((val-%d)*255/%d,0,255)'" % (lo, hi - lo)
    return ["%strim=start_frame=%d:end_frame=%d,settb=expr=%s,setpts=N[%s_f]" % (src, o["f0"], o["f1"], tb, label),
            "[%d:v]settb=expr=%s,setpts=N,format=gray,%s[%s_m]" % (matte_input, tb, lut, label),
            "[%s_f][%s_m]alphamerge,setpts=PTS+%d[%s]" % (label, label, o["f0"], label)]


# --------------------------------------------------------------------------------------------- the last render

def record(work: Path, rows: List[Dict[str, Any]], video: Path, preview: bool) -> None:
    """Keep the last render's measurements, so `edit check` can report them."""
    write_json(ensure_dir(work) / "behind.json", {"video": str(video), "preview": bool(preview),
                                                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cards": rows})


def last_measured(work: Path, card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    rec = read_json(work / "behind.json", None) if (work / "behind.json").is_file() else None
    if not isinstance(rec, dict):
        return None
    for r in rec.get("cards") or []:
        if r.get("i") == card["index"] and r.get("text") == " ".join(card.get("lines") or []) and \
                abs(float(r.get("start", -9)) - card["start"]) < 0.05 and abs(float(r.get("end", -9)) - card["end"]) < 0.05:
            return dict(r, video=rec.get("video"), preview=rec.get("preview"))
    return None


def problems(c: Dict[str, Any], measured: Optional[Dict[str, Any]] = None) -> List[str]:
    """What `edit check` and the render report say about one behind card (each line names the fix)."""
    from . import cutout as CO
    name = "cards[%d] behind at %.2f s" % (c["index"], c["start"])
    out = []
    longest = max(len(ln) for ln in c.get("lines") or ["?"])
    if longest > MAX_CHARS:
        out.append("%s: \"%s\" is %d characters on a line: a word behind the speaker reads at a glance; keep it to "
                   "a word or two (a newline in \"text\" makes two lines)" % (name, " / ".join(c["lines"]), longest))
    if measured and measured.get("hidden") is not None:
        h, run, how = measured["hidden"], measured.get("hidden_run") or 0.0, "measured"
    else:
        h, run, how = c.get("est_hidden"), c.get("est_run") or 0.0, "estimated from the face"
    if h is not None and (h > HIDDEN_WARN or run > RUN_WARN):
        out.append("%s: the text behind the speaker is %.0f %% hidden (%s; the widest hidden stretch is %.0f %% of "
                   "the word): give it the free side (\"side\"), fewer letters, or \"layout\": \"split\" in 9:16" % (
                       name, 100 * h, how, 100 * run))
    if measured and (measured.get("flicker") or 0.0) > CO.FLICKER_WARN:
        out.append("%s: the speaker's matte flickers (%.1f %% of the person's area jumps per still frame, over %.0f %%): "
                   "a busy or dark background; pick a calmer shot, or the \"blur\" or \"dim\" background, which hides "
                   "a ragged edge" % (name, 100 * measured["flicker"], 100 * CO.FLICKER_WARN))
    if measured and measured.get("coverage") is not None and measured["coverage"] < 0.01:
        out.append("%s: no person was found in the shot (the matte is empty): the word shows in front, not behind" % name)
    return out

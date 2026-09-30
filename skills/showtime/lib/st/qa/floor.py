"""The quality floor: four looks-cheap patterns `showtime qa` warns about (never a FAIL).

A video can pass every technical check and still look cheap at full size. These detectors look for the
four patterns seen in real runs, on a few frames sampled across the video (grey, at delivery size, up
to 1920 px wide; numpy and ffmpeg only):

  player_chrome   a web player's control strip recorded with the footage: a thin bar spanning over half
                  the frame's width, low in the frame (its bottom 15 %, or the bottom of a player inside a
                  recorded page), with small glyphs (play, time, fullscreen) at both ends, in the same
                  place on 2+ sampled frames
  soft_footage    footage whose edges are soft: an upscaled or low-resolution recording (edge sharpness,
                  the Laplacian against the gradient, below SOFT_RATIO on most detailed parts)
  caption_boxes   two stacked caption boxes of different widths (one box per line: the stepped look)
  empty_borders   a solid picture fills under 70 % of the frame (width x height) inside flat borders, for
                  over 30 % of the video (a small recording in a big frame)

Each is a WARN with the time range and a fix. Thresholds are the constants below; they were checked on
real renders (a clip with all of these looks, its approved re-cut, the shipped examples) and chosen to stay
quiet on designed frames (a title on a flat ground, a divider line, a single caption plate).
player_chrome, soft_footage and empty_borders run only when the video may hold footage.
"""
from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import ff
from ..common import debug

RULES = {
    "player_chrome": "a video player's control strip (progress bar, play and fullscreen glyphs) is in the footage",
    "soft_footage": "footage looks soft or upscaled at the delivery size",
    "caption_boxes": "caption lines sit in stacked boxes of different widths (stepped boxes)",
    "empty_borders": "the picture fills under 70 % of the frame, with flat borders, for much of the video",
}

MAX_SAMPLES = 20          # frames sampled per video (evenly spread, one per 1.5 s; fewer for short videos)
MAX_WIDTH = 1920          # analysis width cap (4K is judged at 1920, where softness still shows)
EDGE = 24                 # grey-level step that counts as an edge (0-255)

PLAYER_TOP = 0.25         # a control strip is looked for below this share of the height (the frame's bottom
                          # 15 % alone misses a player inside a recorded page, the case seen in real runs)
PLAYER_SPAN = 0.50        # the bar spans more than this share of the frame's width
PLAYER_BAR_MAX = 0.012    # the bar is at most this share of the height thick (a thin bar or line)
PLAYER_END_W = 0.08       # glyph windows reach this share of the width either side of each bar end
PLAYER_NEAR = 0.06        # and this share of the height above or below the bar
PLAYER_GLYPHS = (0.01, 0.30)  # edge density that reads as small glyphs (not empty, not a texture)
PLAYER_FRAMES = 2         # sampled frames with the strip in the same place (row within 3 px)
PLAYER_DARK = 110         # median grey (0-255) just above the bar: a player's controls sit on a dark overlay

SOFT_RATIO = 0.75         # edge sharpness sum|Laplacian| / sum|gradient| per detailed cell: crisp screen text
                          # ~1.5, a 2x upscale ~1.0, 3x ~0.7; crisp recordings measured 0.9-1.5 after encoding
SOFT_CELLS = 0.6          # share of detailed cells that must be soft
SOFT_MIN_CELLS = 6        # at least this many detailed cells per frame (else nothing to judge)
SOFT_DETAIL = 2.0         # mean |gradient| per pixel that makes a cell detailed
SOFT_SHARE = 0.5          # share of sampled frames (and at least 2) that must be soft

CAPTION_TOP = 0.45        # caption boxes are looked for below this share of the height
BOX_EDGE = 12             # a box's edge against the picture (a dark plate on a dark ground is a small step)
BOX_MIN_W = 0.12          # a caption box is at least this share of the width wide
BOX_H = (0.025, 0.15)     # and this share of the height tall (one line of text plus padding)
BOX_ALIGN = 0.04          # stacked boxes' centres within this share of the width
BOX_STEP = 0.10           # widths differing by more than this share of the wider box: stepped
BOX_SHARE = 2             # at least this many sampled frames show stepped boxes

BORDER_FILL = 0.70        # the picture fills under this share of the frame (width x height: a 16:9 recording
                          # across a square frame fills 56 %; a 4:3 one pillarboxed in 16:9 fills 75 %)
BORDER_MIN = 0.25         # a smaller solid block is a design element (a card, a logo plate), not the picture
BORDER_FLAT = 3.0         # a border row/column: grey std under this, mean within BORDER_TONE of the edge
BORDER_TONE = 6.0
BORDER_SOLID = 0.6        # two of the picture's sides differ from the ground over this share (else: loose content)
BORDER_SHARE = 0.30       # of the sampled frames (the duration), and at least 2 frames


# ------------------------------------------------------------------ sampling

def sample_times(dur: float) -> List[float]:
    n = int(max(3, min(MAX_SAMPLES, round(dur / 1.5))))
    return [round((k + 0.5) * dur / n, 3) for k in range(n)] if dur > 0 else []


def grab(video: Any, t: float, W: int, H: int, crop: Optional[Sequence[int]] = None) -> Any:
    """One grey frame at t as a uint8 array (h, w), at delivery size capped at MAX_WIDTH; None on failure."""
    import numpy as np
    if crop:
        W, H = int(crop[2]), int(crop[3])
    w = min(W, MAX_WIDTH)
    h = int(round(H * w / float(W))) if W else H
    w, h = w - w % 2, h - h % 2
    if w < 16 or h < 16:
        return None
    pre = ("crop=%d:%d:%d:%d," % (int(crop[2]), int(crop[3]), int(crop[0]), int(crop[1]))) if crop else ""
    try:
        cp = subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", "%.3f" % t,
                             "-i", os.fspath(video), "-frames:v", "1", "-an", "-sn",
                             "-vf", pre + "scale=%d:%d:flags=area,format=gray" % (w, h), "-f", "rawvideo", "-"],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        debug("floor: %s" % e)
        return None
    buf = cp.stdout or b""
    if len(buf) < w * h:
        return None
    return np.frombuffer(buf[: w * h], np.uint8).reshape(h, w)


# ------------------------------------------------------------------ helpers

def _runs(mask: Any, min_len: int, gap: int = 2) -> List[Tuple[int, int]]:
    """[start, end) runs of True in a 1-D mask, bridging gaps up to `gap`, at least min_len long."""
    import numpy as np
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    out = []
    s = p = int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i - p > gap + 1:
            if p + 1 - s >= min_len:
                out.append((s, p + 1))
            s = i
        p = i
    if p + 1 - s >= min_len:
        out.append((s, p + 1))
    return out


def _hsegments(g: Any, y0: int, y1: int, min_len: int, edge: int = EDGE) -> List[Tuple[int, int, int, int]]:
    """Long horizontal edges between rows y0..y1: (y, x0, x1, sign), where row y+1 differs from row y."""
    import numpy as np
    dy = g[y0 + 1:y1].astype(np.int16) - g[y0:y1 - 1].astype(np.int16)
    out = []
    for r in range(dy.shape[0]):
        row = dy[r]
        if int(np.abs(row).max()) <= edge:
            continue
        for sign in (1, -1):
            for a, b in _runs(row * sign > edge, min_len):
                out.append((y0 + r, a, b, sign))
    return out


def _edge_density(g: Any, y0: int, y1: int, x0: int, x1: int) -> float:
    import numpy as np
    y0, y1, x0, x1 = max(0, y0), min(g.shape[0], y1), max(0, x0), min(g.shape[1], x1)
    if y1 - y0 < 2 or x1 - x0 < 2:
        return 0.0
    a = g[y0:y1, x0:x1].astype(np.int16)
    e = (np.abs(np.diff(a, axis=1))[:-1] > EDGE) | (np.abs(np.diff(a, axis=0))[:, :-1] > EDGE)
    return float(e.mean())


# ------------------------------------------------------------------ player chrome

def player_strip(g: Any) -> Optional[Tuple[int, int, int]]:
    """(y, x0, x1) of a player's progress bar with glyphs at both ends in the bottom band, else None."""
    import numpy as np
    h, w = g.shape
    y0 = int(h * PLAYER_TOP)
    segs = _hsegments(g, y0, h, int(w * PLAYER_SPAN))
    thick = max(2, int(round(h * PLAYER_BAR_MAX)))
    ew = int(w * PLAYER_END_W)
    for (ya, xa0, xa1, sa) in segs:
        for (yb, xb0, xb1, sb) in segs:
            if not (0 < yb - ya <= thick and sb == -sa):
                continue
            x0, x1 = max(xa0, xb0), min(xa1, xb1)
            if x1 - x0 < w * PLAYER_SPAN:
                continue
            band = (ya - int(h * PLAYER_NEAR), yb + int(h * PLAYER_NEAR))
            ends = []
            for cx in (x0, x1):
                d = max(_edge_density(g, band[0], ya - 1, cx - ew, cx + ew),
                        _edge_density(g, yb + 2, band[1], cx - ew, cx + ew))
                ends.append(PLAYER_GLYPHS[0] <= d <= PLAYER_GLYPHS[1])
            above = g[max(0, ya - int(h * PLAYER_NEAR / 2)):max(1, ya - 1), x0:x1]   # where the play/time glyphs sit
            if all(ends) and above.size and float(np.median(above)) < PLAYER_DARK:  # a page's rule sits on a light page
                return ya, x0, x1
    return None


# ------------------------------------------------------------------ soft footage

def sharpness(g: Any, cell: int = 64) -> Dict[str, Any]:
    """Edge sharpness per detailed cell: sum|Laplacian| / sum|gradient| (scale-free; a crisp edge ~2)."""
    import numpy as np
    a = g.astype(np.float32)
    gx = np.abs(np.diff(a, axis=1))[1:-1, :-1]
    gy = np.abs(np.diff(a, axis=0))[:-1, 1:-1]
    grad = gx + gy
    lap = np.abs(4 * a[1:-1, 1:-1] - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:])
    grad = grad[:lap.shape[0], :lap.shape[1]]
    hh, ww = (lap.shape[0] // cell) * cell, (lap.shape[1] // cell) * cell
    if hh == 0 or ww == 0:
        return {"cells": 0, "soft_share": 0.0, "ratio": None}
    G = grad[:hh, :ww].reshape(hh // cell, cell, ww // cell, cell).sum(axis=(1, 3))
    L = lap[:hh, :ww].reshape(hh // cell, cell, ww // cell, cell).sum(axis=(1, 3))
    detailed = G / float(cell * cell) >= SOFT_DETAIL
    if not detailed.any():
        return {"cells": 0, "soft_share": 0.0, "ratio": None}
    r = L[detailed] / np.maximum(G[detailed], 1e-6)
    return {"cells": int(detailed.sum()), "soft_share": float((r < SOFT_RATIO).mean()),
            "ratio": round(float(np.median(r)), 3)}


def is_soft(g: Any) -> Tuple[bool, Dict[str, Any]]:
    s = sharpness(g)
    return s["cells"] >= SOFT_MIN_CELLS and s["soft_share"] >= SOFT_CELLS, s


# ------------------------------------------------------------------ stepped caption boxes

def _side_rows(g: Any, x: int, y: int, down: bool, max_h: int) -> int:
    """How many rows from y (down or up) column x keeps a vertical edge (within 2 px)."""
    import numpy as np
    h, w = g.shape
    x0, x1 = max(1, x - 2), min(w - 1, x + 3)
    n, miss = 0, 0
    rng = range(y + 1, min(h, y + 1 + max_h)) if down else range(y, max(-1, y - max_h), -1)
    for yy in rng:
        row = g[yy].astype(np.int16)
        if np.max(np.abs(row[x0:x1] - row[x0 - 1:x1 - 1])) > BOX_EDGE:
            n += 1 + miss
            miss = 0
        else:
            miss += 1
            if miss > 1:
                break
    return n


def caption_boxes(g: Any) -> List[Tuple[int, int, int, int]]:
    """Filled boxes (x0, y0, x1, y1) with text inside, below CAPTION_TOP."""
    import numpy as np
    h, w = g.shape
    top = int(h * CAPTION_TOP)
    segs = _hsegments(g, top, h, int(w * BOX_MIN_W), BOX_EDGE)
    hmin, hmax = int(h * BOX_H[0]), int(h * BOX_H[1])
    boxes: List[Tuple[int, int, int, int]] = []
    for (y, x0, x1, _s) in segs:
        for down in (True, False):
            n = min(_side_rows(g, x0, y, down, hmax + 2), _side_rows(g, x1 - 1, y, down, hmax + 2))
            if not (hmin <= n <= hmax):
                continue
            ya, yb = (y + 1, y + 1 + n) if down else (y + 1 - n, y + 1)
            inner = g[ya + 2:yb - 2, x0 + 3:x1 - 3]
            if inner.size == 0:
                continue
            med = float(np.median(inner))
            fill = float((np.abs(inner.astype(np.int16) - med) <= 14).mean())
            text = _edge_density(g, ya + 2, yb - 2, x0 + 3, x1 - 3)
            if fill >= 0.5 and 0.01 <= text <= 0.5:
                b = (x0, ya, x1, yb)
                if not any(abs(b[0] - c[0]) <= 4 and abs(b[2] - c[2]) <= 4 and abs(b[1] - c[1]) <= 4 for c in boxes):
                    boxes.append(b)
    return boxes


def stepped(boxes: Sequence[Tuple[int, int, int, int]], w: int) -> bool:
    """Two boxes stacked (touching or close) around one centre, with clearly different widths."""
    for a in boxes:
        for b in boxes:
            if b[1] <= a[1]:
                continue
            ha = a[3] - a[1]
            gap = b[1] - a[3]
            if not (-4 <= gap <= 0.6 * ha):
                continue
            if abs((a[0] + a[2]) / 2.0 - (b[0] + b[2]) / 2.0) > w * BOX_ALIGN:
                continue
            wa, wb = a[2] - a[0], b[2] - b[0]
            if abs(wa - wb) > BOX_STEP * max(wa, wb):
                return True
    return False


# ------------------------------------------------------------------ empty borders

def _largest_run(busy: Any) -> Tuple[int, int]:
    """[start, end) of the longest run of True (the picture, not a caption strip below it)."""
    best, s = (0, 0), None
    for i, v in enumerate(list(busy) + [False]):
        if v and s is None:
            s = i
        elif not v and s is not None:
            if i - s > best[1] - best[0]:
                best = (s, i)
            s = None
    return best


def picture_box(g: Any) -> Optional[Tuple[int, int, int, int]]:
    """(x0, y0, x1, y1) of a solid picture inside flat borders when it fills under BORDER_FILL of the
    frame; None when the frame is filled, the ground is not flat, or the content is loose (a title on a
    flat ground: its box's sides are mostly ground and so is its inside)."""
    import numpy as np
    a = g.astype(np.float32)
    h, w = a.shape
    ring = np.concatenate([a[:2].ravel(), a[-2:].ravel(), a[:, :2].ravel(), a[:, -2:].ravel()])
    ground = float(np.median(ring))
    if float(np.mean(np.abs(ring - ground) < BORDER_TONE)) < 0.9:
        return None
    rows = ~((a.std(axis=1) < BORDER_FLAT) & (np.abs(a.mean(axis=1) - ground) < BORDER_TONE))
    y0, y1 = _largest_run(rows)
    if y1 - y0 < 8:
        return None
    band = a[y0:y1]
    cols = ~((band.std(axis=0) < BORDER_FLAT) & (np.abs(band.mean(axis=0) - ground) < BORDER_TONE))
    x0, x1 = _largest_run(cols)
    if x1 - x0 < 8:
        return None
    if not (BORDER_MIN * w * h <= (x1 - x0) * (y1 - y0) < BORDER_FILL * w * h):
        return None
    off = np.abs(a[y0:y1, x0:x1] - ground) > BORDER_TONE
    sides = [off[min(2, off.shape[0] - 1)].mean(), off[-min(3, off.shape[0])].mean(),
             off[:, min(2, off.shape[1] - 1)].mean(), off[:, -min(3, off.shape[1])].mean()]
    if sum(1 for v in sides if v >= BORDER_SOLID) < 2:
        return None
    return x0, y0, x1, y1


# ------------------------------------------------------------------ the check

def _span(times: Sequence[float]) -> str:
    return "%.1f-%.1fs" % (min(times), max(times)) if len(times) > 1 else "%.1fs" % times[0]


def check(F: Any, video: Any, dur: float, W: int, H: int, *, crop: Optional[Sequence[int]] = None,
          footage: bool = True, frames: Optional[Sequence[Tuple[float, Any]]] = None) -> Dict[str, Any]:
    """Run the four detectors and add WARNs to F (st.qa.video.Findings). `frames` [(t, grey array)] skips
    decoding (tests). Returns what was measured, for qa.json."""
    if frames is None:
        from concurrent.futures import ThreadPoolExecutor
        times = sample_times(dur)
        with ThreadPoolExecutor(max_workers=4) as pool:      # one short ffmpeg seek per frame, 4 at a time
            got = list(pool.map(lambda t: grab(video, t, W, H, crop), times))
        frames = [(t, g) for t, g in zip(times, got) if g is not None]
    out: Dict[str, Any] = {"frames": len(frames)}
    if len(frames) < 2:
        return out
    n = len(frames)
    # player chrome: the same strip (bar row within 3 px, same ends within 2 % of the width) on 2+ frames
    if footage:
        groups: List[Tuple[Tuple[int, int, int], List[float]]] = []
        for t, g in frames:
            s = player_strip(g)
            if not s:
                continue
            tol = 0.02 * g.shape[1]
            for key, ts in groups:
                if abs(key[0] - s[0]) <= 3 and abs(key[1] - s[1]) <= tol and abs(key[2] - s[2]) <= tol:
                    ts.append(t)
                    break
            else:
                groups.append((s, [t]))
        best = max((ts for _k, ts in groups), key=len) if groups else []
        out["player_chrome"] = len(best)
        if len(best) >= PLAYER_FRAMES:
            F.add("player_chrome", "WARN",
                  "a video player's control strip (a progress bar with controls at both ends) is in the footage at %s"
                  % _span(best), t=min(best), end=max(best),
                  fix="crop the footage above the strip or cut those seconds; re-record with the player's controls "
                      "hidden (move the pointer away, or play the page's video without controls)")
        soft = []
        ratios = []
        for t, g in frames:
            box = picture_box(g)
            sub = g[box[1]:box[3], box[0]:box[2]] if box else g
            ok, s = is_soft(sub)
            if s.get("ratio") is not None:
                ratios.append(s["ratio"])
            if ok:
                soft.append(t)
        out["soft_footage"] = {"frames": len(soft), "ratio": round(sorted(ratios)[len(ratios) // 2], 3) if ratios else None}
        if len(soft) >= max(2, SOFT_SHARE * n):
            F.add("soft_footage", "WARN",
                  "footage looks soft or upscaled at %dx%d (edge sharpness %s, crisp is about 1 or more) at %s"
                  % (W, H, out["soft_footage"]["ratio"], _span(soft)), t=min(soft), end=max(soft),
                  fix="footage looks soft or upscaled; re-record at 2x device scale (or deliver at the source's size)")
    step = [t for t, g in frames if stepped(caption_boxes(g), g.shape[1])]
    out["caption_boxes"] = len(step)
    if len(step) >= BOX_SHARE:
        F.add("caption_boxes", "WARN",
              "captions sit in stacked boxes of different widths (one box per line: the stepped look) at %s" % _span(step),
              t=min(step), end=max(step),
              fix="one box for the whole caption: showtime captions --style boxed (a single plate), or no box with an outline")
    if footage and not crop:
        bordered, fill = [], []
        for t, g in frames:
            b = picture_box(g)
            if b:
                bordered.append(t)
                fill.append((b[2] - b[0]) * (b[3] - b[1]) / float(g.shape[0] * g.shape[1]))
        out["empty_borders"] = len(bordered)
        if len(bordered) >= 2 and len(bordered) > BORDER_SHARE * n:
            share = sorted(fill)[len(fill) // 2]
            F.add("empty_borders", "WARN",
                  "the picture fills only %d %% of the frame, inside flat borders, at %s (%d of %d sampled frames)"
                  % (round(share * 100), _span(bordered), len(bordered), n), t=min(bordered), end=max(bordered),
                  fix="fill the frame: crop the recording to its subject and scale it up, or make the video in the "
                      "recording's own aspect")
    return out

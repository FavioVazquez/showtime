"""Smooth auto zoom for screen recordings and `showtime demo record` output.

    showtime autozoom <demo-outdir>                       # uses events.json + frames/
    showtime autozoom screen.mp4 --cursor-log cursor.csv  # your own recording + cursor telemetry
    showtime autozoom screen.mp4                          # no telemetry: zooms where the screen changes
    showtime autozoom <demo-outdir> --look plain --size 1080x1920 --fit cover   # vertical follow-cam

Pipeline: actions (clicks, typing, scrolls, drags, explicit focus hints, cursor dwells or screen
changes) -> shots (merge rule, anticipation, holds) -> a damped spring camera (zoom in log space,
dead-zone cursor follow, clamped to the window) -> per-frame affine warp (OpenCV) -> synthetic
cursor, click ripples and keycaps -> ffmpeg (H.264, BT.709).

Rules (from screen-recording craft): zoom 1.5-2x on clicks and typing, ~1.3x for drags, never more
than --max-zoom (2.8 hard cap); start moving before the action (0.15 s click, 0.25 s scroll/drag,
0.4 s typing); hold at least ~1.6 s; merge actions closer than 1.5 s and 20% of the screen; stay
zoomed across gaps shorter than 1.8 s; zoom out after the hold. The camera only pans when the cursor
leaves the central 75% of the view (60% while typing).

Outputs <name>.autozoom.mp4 and <name>.camera.json (per-frame zoom/centre, usable as a CSS
transform on the recording layer of an HTML composition).
"""
from __future__ import annotations

import csv
import json
import math
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from ..common import ShowtimeError, debug, log, warn, write_json

HARD_MAX_ZOOM = 2.8
ANTICIPATE = {"click": 0.15, "type": 0.4, "scroll": 0.25, "drag": 0.25, "focus": 0.3, "hover": 0.2,
              "dwell": 0.2, "motion": 0.25}
HOLD = {"click": 1.6, "type": 1.2, "scroll": 0.8, "drag": 1.2, "focus": 0.0, "hover": 1.0, "dwell": 1.2,
        "motion": 1.4}


# --------------------------------------------------------------------------- data

@dataclass
class Action:
    t: float
    end: float
    kind: str
    x: float                      # focus point, source pixels
    y: float
    bbox: Optional[Tuple[float, float, float, float]] = None   # source pixels
    zoom: Optional[float] = None


@dataclass
class Shot:
    start: float
    end: float
    zoom: float
    x: float                      # focus, source pixels
    y: float
    kinds: List[str] = field(default_factory=list)
    typing: bool = False


@dataclass
class Source:
    kind: str                     # frames | video
    width: int
    height: int
    fps: float
    frames: int
    paths: List[Path] = field(default_factory=list)
    video: Optional[Path] = None
    has_audio: bool = False
    scale: float = 1.0            # event coordinate units -> source pixels
    name: str = "recording"
    base_dir: Path = Path(".")


# --------------------------------------------------------------------------- loading

def load_source(src: Path, events_path: Optional[Path] = None) -> Tuple[Source, Optional[Dict[str, Any]]]:
    """A demo folder (events.json + frames/) or a video file (+ optional events.json)."""
    src = Path(src)
    events = None
    if src.is_dir():
        ep = events_path or (src / "events.json")
        if not ep.is_file():
            raise ShowtimeError("%s has no events.json" % src,
                                hint="pass a folder written by `showtime demo record`, or a video file")
        events = json.loads(ep.read_text(encoding="utf-8"))
        pattern = events.get("frame_pattern", "frames/%05d.jpg")
        fdir = src / Path(pattern).parent
        paths = sorted(p for p in fdir.glob("*" + Path(pattern).suffix) if p.is_file())
        if not paths:
            vid = src / (events.get("video") or "demo.mp4")
            if vid.is_file():
                return _video_source(vid, events), events
            raise ShowtimeError("no frames found in %s" % fdir)
        import cv2
        first = cv2.imread(str(paths[0]))
        if first is None:
            raise ShowtimeError("cannot read %s" % paths[0])
        h, w = first.shape[:2]
        vw = (events.get("viewport") or {}).get("width") or w
        s = Source("frames", w, h, float(events.get("fps") or 30), len(paths), paths=paths,
                   scale=w / float(vw), name=src.name, base_dir=src)
        return s, events
    if not src.is_file():
        raise ShowtimeError("not found: %s" % src)
    if events_path:
        events = json.loads(Path(events_path).read_text(encoding="utf-8"))
    return _video_source(src, events), events


def _video_source(path: Path, events: Optional[Dict[str, Any]]) -> Source:
    from .. import ff
    info = ff.probe(path)
    if not info.get("has_video"):
        raise ShowtimeError("%s has no video stream" % path)
    w, h = int(info["display_width"]), int(info["display_height"])
    fps = float(info.get("fps") or 30)
    n = int(info.get("nb_frames") or round((info.get("duration") or 0) * fps))
    scale = 1.0
    if events and (events.get("viewport") or {}).get("width"):
        scale = w / float(events["viewport"]["width"])
    return Source("video", w, h, fps, n, video=path, has_audio=bool(info.get("has_audio")), scale=scale,
                  name=path.stem, base_dir=path.parent)


def iter_frames(src: Source) -> Iterator[Any]:
    import cv2
    import numpy as np
    if src.kind == "frames":
        for p in src.paths:
            img = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if img is None:
                raise ShowtimeError("cannot read frame %s" % p)
            if img.shape[1] != src.width or img.shape[0] != src.height:
                img = cv2.resize(img, (src.width, src.height), interpolation=cv2.INTER_AREA)
            yield img
        return
    from .. import ff
    cmd = [ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(src.video),
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    import tempfile
    errf = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf)
    size = src.width * src.height * 3
    got = 0
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            got += 1
            yield np.frombuffer(buf, np.uint8).reshape(src.height, src.width, 3)
        if got == 0:
            proc.wait()
            errf.seek(0)
            tail = errf.read().decode("utf-8", "replace").strip()[-600:]
            raise ShowtimeError("ffmpeg could not decode %s: %s" % (src.video, tail or "no frames"))
    finally:
        errf.close()
        try:
            proc.stdout.close()
        except OSError:
            pass
        proc.kill()
        proc.wait()


def read_cursor_log(path: Path, scale: float = 1.0) -> List[Tuple[float, float, float, int]]:
    """Cursor telemetry: JSON [[t,x,y,down],...] / [{t,x,y,down}] or CSV with a t,x,y[,down] header."""
    p = Path(path)
    rows: List[Tuple[float, float, float, int]] = []
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json" or text.lstrip().startswith(("[", "{")):
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("cursor") or data.get("samples") or []
        for r in data:
            if isinstance(r, dict):
                rows.append((float(r["t"]), float(r["x"]), float(r["y"]), int(bool(r.get("down", 0)))))
            else:
                rows.append((float(r[0]), float(r[1]), float(r[2]), int(bool(r[3])) if len(r) > 3 else 0))
    else:
        for r in csv.DictReader(text.splitlines()):
            rows.append((float(r["t"]), float(r["x"]), float(r["y"]), int(float(r.get("down") or 0) > 0)))
    rows.sort(key=lambda r: r[0])
    return [(t, x * scale, y * scale, d) for t, x, y, d in rows]


# --------------------------------------------------------------------------- actions

def actions_from_events(ev: Dict[str, Any], scale: float, zooms: Dict[str, float]) -> List[Action]:
    out: List[Action] = []
    for e in ev.get("events", []):
        k = e.get("type")
        if k not in ("click", "type", "scroll", "drag", "focus", "hover", "key"):
            continue
        t = float(e.get("t", 0))
        end = float(e.get("end", t))
        bb = e.get("bbox")
        bbox = tuple(float(v) * scale for v in bb) if bb else None
        if k == "key":
            out.append(Action(t, t, "key", float("nan"), float("nan")))
            continue
        if k == "scroll":
            out.append(Action(t, end, "scroll", float("nan"), float("nan")))
            continue
        x = e.get("x")
        y = e.get("y")
        if (x is None or y is None) and bbox:
            x, y = (bbox[0] + bbox[2] / 2) / scale, (bbox[1] + bbox[3] / 2) / scale
        if x is None or y is None:
            continue
        z = float(e["zoom"]) if k == "focus" and e.get("zoom") else zooms.get(k)
        out.append(Action(t, end, k, float(x) * scale, float(y) * scale, bbox, z))
    return out


def actions_from_cursor(samples: Sequence[Tuple[float, float, float, int]], w: int, h: int) -> List[Action]:
    """Clicks from button presses, dwells from the cursor resting (2% radius, 0.45-2.6 s)."""
    out: List[Action] = []
    prev = 0
    for t, x, y, d in samples:
        if d and not prev:
            out.append(Action(t, t, "click", x, y))
        prev = d
    diag = math.hypot(w, h)
    i = 0
    n = len(samples)
    while i < n:
        j = i
        while j + 1 < n and math.hypot(samples[j + 1][1] - samples[i][1], samples[j + 1][2] - samples[i][2]) < 0.02 * diag:
            j += 1
        dur = samples[j][0] - samples[i][0]
        if 0.45 <= dur <= 2.6:
            xs = [s[1] for s in samples[i:j + 1]]
            ys = [s[2] for s in samples[i:j + 1]]
            t = samples[i][0]
            if not any(abs(a.t - t) < 1.0 for a in out if a.kind == "click"):
                out.append(Action(t, samples[j][0], "dwell", sum(xs) / len(xs), sum(ys) / len(ys)))
        i = j + 1
    out.sort(key=lambda a: a.t)
    return out


def actions_from_motion(src: Source, sample_fps: float = 5.0) -> List[Action]:
    """No telemetry: find where the screen changes (small regions, not full-screen cuts)."""
    import cv2
    import numpy as np
    step = max(1, int(round(src.fps / sample_fps)))
    sw = 320
    sh = max(2, int(round(src.height * sw / float(src.width))))
    prev = None
    out: List[Action] = []
    for i, frame in enumerate(iter_frames(src)):
        if i % step:
            continue
        g = cv2.cvtColor(cv2.resize(frame, (sw, sh), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        if prev is not None:
            diff = cv2.absdiff(g, prev)
            mask = (diff > 18).astype(np.uint8)
            frac = float(mask.mean())
            if 0.002 < frac < 0.35:
                ys, xs = np.nonzero(mask)
                x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
                k = src.width / float(sw)
                t = i / src.fps
                if not out or t - out[-1].t >= 1.8:
                    out.append(Action(t, t, "motion", (x0 + x1) / 2 * k, (y0 + y1) / 2 * k,
                                      (x0 * k, y0 * k, (x1 - x0 + 1) * k, (y1 - y0 + 1) * k)))
        prev = g
    return out


# --------------------------------------------------------------------------- planning

def _zoom_for(a: Action, vw: float, vh: float, max_zoom: float, default: float) -> float:
    z = a.zoom if a.zoom else default
    if a.bbox and a.kind != "focus":
        bw, bh = max(8.0, a.bbox[2]), max(8.0, a.bbox[3])
        fit = min(0.7 * vw / bw, 0.7 * vh / bh)   # keep the element at ~70% of the view
        z = min(z, max(1.15, fit))
    return max(1.0, min(z, max_zoom, HARD_MAX_ZOOM))


def plan_shots(actions: Sequence[Action], w: int, h: int, *, max_zoom: float, zooms: Dict[str, float],
               merge_gap: float = 1.5, bridge_gap: float = 1.8, chapters: Sequence[float] = (),
               wides: Sequence[float] = ()) -> List[Shot]:
    """Shots from actions. A chapter marker between two shots keeps them apart (the camera goes wide
    for the new chapter); a `wide` event (demo.wide()) ends any shot running at that moment."""
    diag = math.hypot(w, h)
    shots: List[Shot] = []
    # chapter and wide markers: actions on either side of one never share a shot
    barriers = sorted(float(c) for c in list(chapters) + list(wides))

    def crosses(t0: float, t1: float) -> bool:
        return any(t0 < b <= t1 for b in barriers)

    # an explicit focus (demo.focus, a --hints focus) is the author's camera: clicks and typing inside
    # its span do not re-frame or shrink it (typing logs the whole editor box, whose fit zoom is ~1.15)
    focus_spans = [(a.t, max(a.end, a.t + 1.0)) for a in actions if a.kind == "focus"]

    def under_focus(a: Action) -> bool:
        return a.kind not in ("focus", "key", "scroll") and any(f0 <= a.t <= f1 for f0, f1 in focus_spans)

    for a in sorted(actions, key=lambda a: a.t):
        if under_focus(a):
            continue
        if a.kind == "key" or a.kind == "scroll":
            if shots and a.t - shots[-1].end < merge_gap and \
                    not crosses(shots[-1].end - HOLD.get(shots[-1].kinds[-1], 1.2), a.t):
                shots[-1].end = max(shots[-1].end, a.end + HOLD.get(a.kind, 0.6))
            continue
        z = _zoom_for(a, w, h, max_zoom, zooms.get(a.kind, 1.6))
        if z <= 1.02:
            continue
        start = a.t - ANTICIPATE.get(a.kind, 0.2)
        end = max(a.end, a.t) + HOLD.get(a.kind, 1.2)
        if a.kind == "focus":
            end = max(a.end, a.t + 1.0)
        last = shots[-1] if shots else None
        if last and start - (last.end - HOLD.get(last.kinds[-1], 1.2)) < merge_gap and \
                math.hypot(a.x - last.x, a.y - last.y) < 0.2 * diag and \
                not crosses(last.end - HOLD.get(last.kinds[-1], 1.2), a.t):
            n = len(last.kinds)
            if a.kind == "focus":
                # the explicit focus sets the frame; earlier actions only extend the shot
                last.x, last.y, last.zoom = a.x, a.y, z
            elif "focus" not in last.kinds:
                last.x = (last.x * n + a.x) / (n + 1)
                last.y = (last.y * n + a.y) / (n + 1)
                last.zoom = min(last.zoom, z)
            last.end = max(last.end, end)
            last.kinds.append(a.kind)
            last.typing = last.typing or a.kind == "type"
            continue
        shots.append(Shot(start, end, z, a.x, a.y, [a.kind], a.kind == "type"))
    # stay zoomed across short gaps (the camera pans instead of zooming out and back in), except
    # across a chapter change or a wide beat
    for s, nxt in zip(shots, shots[1:]):
        last_act = max(s.start, s.end - HOLD.get(s.kinds[-1], 1.2))
        if nxt.start - s.end < bridge_gap and not crosses(last_act - 0.05, nxt.start + 0.05):
            s.end = nxt.start
    for wv in wides:
        for s in shots:
            if s.start < wv < s.end:
                s.end = wv
    return [s for s in shots if s.end - s.start > 0.1]


# --------------------------------------------------------------------------- camera

class Spring:
    """Damped spring; `response` ~ settle time constant in seconds, zeta = damping ratio."""

    def __init__(self, x: float, response: float, zeta: float = 0.95):
        self.x = x
        self.v = 0.0
        self.w = 2 * math.pi / max(0.05, response)
        self.zeta = zeta

    def step(self, target: float, dt: float, substeps: int = 4) -> float:
        h = dt / substeps
        for _ in range(substeps):
            a = self.w * self.w * (target - self.x) - 2 * self.zeta * self.w * self.v
            self.v += a * h
            self.x += self.v * h
        return self.x


@dataclass
class Layout:
    out_w: int
    out_h: int
    wx: float                     # window rect (canvas = output pixels at zoom 1)
    wy: float
    ww: float
    wh: float
    ws: float                     # source px -> canvas px


def make_layout(src_w: int, src_h: int, out_w: int, out_h: int, look: str, fit: str, pad_frac: float) -> Layout:
    pad = int(round(pad_frac * min(out_w, out_h))) if look == "framed" else 0
    aw, ah = out_w - 2 * pad, out_h - 2 * pad
    s = (max if fit == "cover" else min)(aw / float(src_w), ah / float(src_h))
    ww, wh = src_w * s, src_h * s
    return Layout(out_w, out_h, (out_w - ww) / 2.0, (out_h - wh) / 2.0, ww, wh, s)


def _clamp_axis(c: float, half: float, lo: float, size: float, canvas: float) -> float:
    if 2 * half <= size:                       # view inside the window
        return min(max(c, lo + half), lo + size - half)
    a, b = lo + size - half, lo + half         # window fully visible
    a, b = max(a, half), min(b, canvas - half)
    if a > b:
        return canvas / 2.0
    return min(max(c, a), b)


def simulate_camera(n_frames: int, fps: float, shots: Sequence[Shot], lay: Layout,
                    cursor: Optional[Sequence[Tuple[float, float, float, int]]], *,
                    zoom_response: float = 0.55, pan_response: float = 0.42, zeta: float = 0.95,
                    dead_zone: float = 0.75, dead_zone_typing: float = 0.6) -> List[Tuple[float, float, float]]:
    """Per-frame (zoom, cx, cy) with cx/cy in canvas pixels."""
    cx0, cy0 = lay.wx + lay.ww / 2, lay.wy + lay.wh / 2
    zs = Spring(0.0, zoom_response, zeta)         # log zoom
    xs = Spring(cx0, pan_response, zeta)
    ys = Spring(cy0, pan_response, zeta)
    out = []
    dt = 1.0 / fps
    si = 0
    target_c = (cx0, cy0)
    for i in range(n_frames):
        t = i * dt
        while si < len(shots) and shots[si].end < t:
            si += 1
        shot = shots[si] if si < len(shots) and shots[si].start <= t <= shots[si].end else None
        if shot:
            z_t = shot.zoom
            fx, fy = lay.wx + shot.x * lay.ws, lay.wy + shot.y * lay.ws
            target_c = (fx, fy)
            if cursor is not None and i < len(cursor) and not math.isnan(cursor[i][1]):
                # dead zone: pan only as much as needed to keep the cursor inside the central area
                px, py = lay.wx + cursor[i][1] * lay.ws, lay.wy + cursor[i][2] * lay.ws
                dz = dead_zone_typing if shot.typing else dead_zone
                hx, hy = lay.out_w / (2 * z_t) * dz, lay.out_h / (2 * z_t) * dz
                tx, ty = target_c
                if px < tx - hx:
                    tx = px + hx
                elif px > tx + hx:
                    tx = px - hx
                if py < ty - hy:
                    ty = py + hy
                elif py > ty + hy:
                    ty = py - hy
                target_c = (tx, ty)
        else:
            z_t = 1.0
            target_c = (cx0, cy0)
        lz = zs.step(math.log(z_t), dt)
        z = math.exp(lz)
        hx, hy = lay.out_w / (2 * z), lay.out_h / (2 * z)
        # a target in a window corner may use the frame's padding (framed look) so it is not stuck
        # on the edge of the picture
        spx = lay.wx if shot and (shot.x * lay.ws < 0.05 * lay.ww or shot.x * lay.ws > 0.95 * lay.ww) else 0.0
        spy = lay.wy if shot and (shot.y * lay.ws < 0.05 * lay.wh or shot.y * lay.ws > 0.95 * lay.wh) else 0.0
        tx = _clamp_axis(target_c[0], hx, lay.wx - spx, lay.ww + 2 * spx, lay.out_w)
        ty = _clamp_axis(target_c[1], hy, lay.wy - spy, lay.wh + 2 * spy, lay.out_h)
        cx = xs.step(tx, dt)
        cy = ys.step(ty, dt)
        cx = _clamp_axis(cx, hx, lay.wx - spx, lay.ww + 2 * spx, lay.out_w)
        cy = _clamp_axis(cy, hy, lay.wy - spy, lay.wh + 2 * spy, lay.out_h)
        out.append((z, cx, cy))
    return out


# --------------------------------------------------------------------------- drawing

def _hex_bgr(h: str) -> Tuple[int, int, int]:
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ShowtimeError("bad colour %r (use #rrggbb)" % h)
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)


def make_background(lay: Layout, look: str, bg: str, radius_frac: float, shadow: bool):
    """(background canvas float32 BGR, window mask float32 0..1) at output size."""
    import cv2
    import numpy as np
    W, H = lay.out_w, lay.out_h
    cols = [_hex_bgr(c) for c in bg.split(",")] if bg else [(0, 0, 0)]
    if len(cols) == 1:
        canvas = np.empty((H, W, 3), np.float32)
        canvas[:] = cols[0]
    else:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        k = ((xx / W) * 0.6 + (yy / H) * 0.4)[..., None]
        a, b = np.array(cols[0], np.float32), np.array(cols[1], np.float32)
        canvas = a * (1 - k) + b * k
    ss = 4
    r = radius_frac * min(W, H) if look == "framed" else 0.0
    big = np.zeros((H * ss // 2, W * ss // 2), np.uint8)
    f = ss / 2.0
    x0, y0, x1, y1 = lay.wx * f, lay.wy * f, (lay.wx + lay.ww) * f, (lay.wy + lay.wh) * f
    rr = r * f
    if rr > 0.5:
        ri = int(round(rr))
        cv2.rectangle(big, (int(round(x0 + ri)), int(round(y0))), (int(round(x1 - ri)), int(round(y1))), 255, -1)
        cv2.rectangle(big, (int(round(x0)), int(round(y0 + ri))), (int(round(x1)), int(round(y1 - ri))), 255, -1)
        for cx, cy in ((x0 + ri, y0 + ri), (x1 - ri, y0 + ri), (x0 + ri, y1 - ri), (x1 - ri, y1 - ri)):
            cv2.circle(big, (int(round(cx)), int(round(cy))), ri, 255, -1, lineType=cv2.LINE_AA)
    else:
        cv2.rectangle(big, (int(round(x0)), int(round(y0))), (int(round(x1)) - 1, int(round(y1)) - 1), 255, -1)
    mask = cv2.resize(big, (W, H), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0
    if look == "framed" and shadow:
        sh = cv2.GaussianBlur(mask, (0, 0), sigmaX=max(2.0, 0.022 * H))
        off = int(round(0.012 * H))
        sh = np.roll(sh, off, axis=0)
        canvas = canvas * (1 - 0.38 * sh[..., None])
    return canvas, mask


ARROW = [(0, 0), (0, 17), (4.2, 13.2), (7.0, 19.5), (9.6, 18.4), (6.9, 12.2), (12.2, 12.2)]


def draw_cursor(img, x: float, y: float, size: float, alpha: float = 1.0) -> None:
    """Anti-aliased arrow cursor (white with a dark outline and soft shadow) with its tip at (x, y)."""
    import cv2
    import numpy as np
    if alpha <= 0.01:
        return
    k = size / 19.5
    pts = np.array([(x + px * k, y + py * k) for px, py in ARROW], np.float64)
    S = 16
    x0, y0 = int(max(0, math.floor(pts[:, 0].min() - 6 * k - 4))), int(max(0, math.floor(pts[:, 1].min() - 6 * k - 4)))
    x1 = int(min(img.shape[1], math.ceil(pts[:, 0].max() + 8 * k + 4)))
    y1 = int(min(img.shape[0], math.ceil(pts[:, 1].max() + 8 * k + 4)))
    if x1 <= x0 or y1 <= y0:
        return
    roi = img[y0:y1, x0:x1].astype(np.float32)
    h, w = roi.shape[:2]
    local = ((pts - [x0, y0]) * S).astype(np.int32)
    shadow = np.zeros((h, w), np.uint8)
    cv2.fillPoly(shadow, [local + int(1.2 * k * S)], 255, lineType=cv2.LINE_AA, shift=4)
    shadow = cv2.GaussianBlur(shadow, (0, 0), sigmaX=max(0.8, 1.4 * k)).astype(np.float32) / 255 * 0.45 * alpha
    roi *= (1 - shadow[..., None])
    outline = np.zeros((h, w), np.uint8)
    cv2.polylines(outline, [local], True, 255, thickness=max(1, int(round(1.6 * k))), lineType=cv2.LINE_AA, shift=4)
    fill = np.zeros((h, w), np.uint8)
    cv2.fillPoly(fill, [local], 255, lineType=cv2.LINE_AA, shift=4)
    fa = fill.astype(np.float32)[..., None] / 255 * alpha
    oa = outline.astype(np.float32)[..., None] / 255 * alpha
    roi = roi * (1 - fa) + 255 * fa
    roi = roi * (1 - oa) + 20 * oa
    img[y0:y1, x0:x1] = np.clip(roi, 0, 255).astype(np.uint8)


def draw_ripple(img, x: float, y: float, radius: float, alpha: float, color=(255, 255, 255)) -> None:
    import cv2
    import numpy as np
    if alpha <= 0.01 or radius < 1:
        return
    r = int(math.ceil(radius)) + 4
    x0, y0 = max(0, int(x) - r), max(0, int(y) - r)
    x1, y1 = min(img.shape[1], int(x) + r + 1), min(img.shape[0], int(y) + r + 1)
    if x1 <= x0 or y1 <= y0:
        return
    roi = img[y0:y1, x0:x1].astype(np.float32)
    m = np.zeros(roi.shape[:2], np.uint8)
    S = 16
    cv2.circle(m, (int((x - x0) * S), int((y - y0) * S)), int(radius * S), 255,
               thickness=max(2, int(radius * 0.12)), lineType=cv2.LINE_AA, shift=4)
    disc = np.zeros(roi.shape[:2], np.uint8)
    cv2.circle(disc, (int((x - x0) * S), int((y - y0) * S)), int(radius * S), 255, -1, lineType=cv2.LINE_AA, shift=4)
    a = (m.astype(np.float32) * alpha + disc.astype(np.float32) * alpha * 0.25)[..., None] / 255
    roi = roi * (1 - a) + np.array(color, np.float32) * a
    img[y0:y1, x0:x1] = np.clip(roi, 0, 255).astype(np.uint8)


MAC_GLYPHS = {"Cmd": "\u2318", "Opt": "\u2325", "Alt": "\u2325", "Shift": "\u21e7", "Ctrl": "\u2303",
              "Enter": "\u21b5", "Backspace": "\u232b", "Tab": "\u21e5", "Esc": "\u238b"}
KEY_POSITIONS = ("bottom", "top", "bottom-left", "bottom-right", "top-left", "top-right")

KEY_LABELS = {"meta": "Cmd", "command": "Cmd", "cmd": "Cmd", "control": "Ctrl", "ctrl": "Ctrl", "alt": "Alt",
              "option": "Opt", "shift": "Shift", "enter": "Enter", "return": "Enter", "escape": "Esc",
              "esc": "Esc", "tab": "Tab", "backspace": "Backspace", "delete": "Del", "space": "Space",
              " ": "Space", "arrowup": "\u2191", "arrowdown": "\u2193", "arrowleft": "\u2190",
              "arrowright": "\u2192", "controlormeta": "Ctrl"}
# a lone punctuation key is a speck on a keycap ("." is ~5 px at 1080p), so it carries its name too
PUNCT_NAMES = {".": "Period", ",": "Comma", "/": "Slash", "\\": "Backslash", ";": "Semicolon", "'": "Quote",
               "`": "Backtick", "-": "Minus", "=": "Equals", "[": "Bracket", "]": "Bracket", "?": "Question"}


class Keycaps:
    """Keycap / typed-text overlay rendered with PIL from an installed font file."""

    def __init__(self, out_w: int, out_h: int, font_path: Optional[str], position: str = "bottom",
                 glyphs: bool = False):
        from PIL import ImageFont
        self.W, self.H = out_w, out_h
        self.position = position if position in KEY_POSITIONS else "bottom"
        self.glyphs = glyphs and _font_has(font_path, "".join(MAC_GLYPHS.values()))
        size = max(14, int(round(out_h * 0.034)))
        try:
            self.font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default(size=size)
        except Exception:  # noqa: BLE001
            self.font = ImageFont.load_default()
        self.cache: Dict[str, Any] = {}

    def label(self, keys: str) -> List[str]:
        parts = [p for p in keys.replace("+", " ").split(" ") if p] if keys.strip() != "+" else ["+"]
        out = [KEY_LABELS.get(p.lower(), (p + " " + PUNCT_NAMES[p]) if p in PUNCT_NAMES
                              else (p.upper() if len(p) == 1 else p)) for p in parts]
        return [MAC_GLYPHS.get(x, x) for x in out] if self.glyphs else out

    def sprite(self, kind: str, text: str):
        key = kind + "\0" + text
        if key in self.cache:
            return self.cache[key]
        import numpy as np
        from PIL import Image, ImageDraw
        pad = int(self.H * 0.012)
        cap_h = int(self.H * 0.058)
        gap = int(self.H * 0.008)
        draw0 = ImageDraw.Draw(Image.new("RGBA", (4, 4)))
        items = self.label(text) if kind == "keys" else [text]   # "cap": one keycap with its own label
        widths = []
        for it in items:
            bb = draw0.textbbox((0, 0), it, font=self.font)
            widths.append(max(cap_h, bb[2] - bb[0] + 2 * pad + (0 if kind in ("keys", "cap") else pad)))
        total = sum(widths) + gap * (len(items) - 1)
        im = Image.new("RGBA", (total + 8, cap_h + 10), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        x = 4
        for it, w in zip(items, widths):
            r = int(cap_h * 0.22)
            d.rounded_rectangle([x, 6, x + w, 6 + cap_h], r, fill=(0, 0, 0, 90))
            d.rounded_rectangle([x, 2, x + w, 2 + cap_h], r, fill=(28, 28, 32, 235), outline=(90, 90, 100, 255), width=1)
            bb = d.textbbox((0, 0), it, font=self.font)
            d.text((x + (w - (bb[2] - bb[0])) / 2 - bb[0], 2 + (cap_h - (bb[3] - bb[1])) / 2 - bb[1]), it,
                   font=self.font, fill=(245, 245, 250, 255))
            x += w + gap
        arr = np.array(im)[..., [2, 1, 0, 3]]  # RGBA -> BGRA
        self.cache[key] = arr
        return arr

    def draw(self, img, kind: str, text: str, alpha: float) -> None:
        import numpy as np
        if alpha <= 0.01 or not text:
            return
        spr = self.sprite(kind, text)
        h, w = spr.shape[:2]
        if w > self.W - 20:
            spr = spr[:, :self.W - 20]
            w = spr.shape[1]
        margin = int(0.05 * self.W)
        pos = self.position
        x0 = margin if pos.endswith("left") else (self.W - w - margin if pos.endswith("right") else (self.W - w) // 2)
        y0 = int(self.H * (0.12 if pos.startswith("top") else 0.88) - h / 2)
        x0 = max(0, min(self.W - w, x0))
        y0 = max(0, min(self.H - h, y0))
        roi = img[y0:y0 + h, x0:x0 + w].astype(np.float32)
        a = spr[..., 3:4].astype(np.float32) / 255 * alpha
        roi = roi * (1 - a) + spr[..., :3].astype(np.float32) * a
        img[y0:y0 + h, x0:x0 + w] = roi.astype(np.uint8)


def _font_has(font_path: Optional[str], chars: str) -> bool:
    """True when the font file covers every character (glyph keycaps fall back to words otherwise)."""
    if not font_path:
        return False
    try:
        from .fontfiles import cmap_chars
        have = cmap_chars(Path(font_path).read_bytes())
        return all(ord(c) in have for c in chars)
    except Exception:  # noqa: BLE001
        return False


def apply_cursor_offsets(samples: List[Tuple[float, float, float, int]], specs: Sequence[str], scale: float,
                         ease_s: float = 0.3) -> List[Tuple[float, float, float, int]]:
    """Move the recorded pointer without a new take: "t0-t1:dx,dy" (CSS px) shifts it inside
    [t0, t1], eased in and out over `ease_s` (a parked pointer that covers a label)."""
    out = list(samples)
    for spec in specs or []:
        try:
            rng, _, d = str(spec).partition(":")
            t0, t1 = (float(v) for v in rng.split("-", 1))
            dx, dy = (float(v) * scale for v in d.split(",", 1))
        except ValueError:
            raise ShowtimeError("--cursor-offset %r: use t0-t1:dx,dy (seconds; CSS pixels), e.g. 22.6-24:36,12" % spec)
        for i, (t, x, y, down) in enumerate(out):
            if t < t0 - ease_s or t > t1 + ease_s:
                continue
            k = min(1.0, max(0.0, (t - (t0 - ease_s)) / ease_s), max(0.0, ((t1 + ease_s) - t) / ease_s))
            k = k * k * (3 - 2 * k)
            out[i] = (t, x + dx * k, y + dy * k, down)
    return out


def merge_hints(events: Dict[str, Any], hints: Any) -> Dict[str, Any]:
    """Camera edits without a new take: a hints file is a list of events in the demo format, merged
    into events.json at plan time: {"type": "focus", "t", "end", "x", "y", "zoom"} adds a shot,
    {"type": "wide", "t"} goes wide, {"type": "drop", "t", "end"} removes the actions in that span, and a
    {"type": "key", "t", "keys", "label"} after a drop re-adds a key with its keycap text as drawn."""
    items = hints.get("events", hints) if isinstance(hints, dict) else hints
    if not isinstance(items, list):
        raise ShowtimeError("--hints must be a JSON list of events (focus / wide / drop)")
    ev = dict(events or {})
    base = list(ev.get("events", []))
    for h in items:
        if not isinstance(h, dict) or "t" not in h:
            continue
        if h.get("type") == "drop":
            a, b = float(h["t"]), float(h.get("end", h["t"]))
            base = [e for e in base if not (e.get("type") not in ("chapter", "note", "wide") and a <= float(e.get("t", -1)) <= b)]
        else:
            base.append(dict(h))
    ev["events"] = sorted(base, key=lambda e: float(e.get("t", 0)))
    return ev


def keystroke_timeline(events: Optional[Dict[str, Any]], mode: str) -> List[Tuple[float, float, str, str]]:
    """[(start, end, kind, text)] for overlays: kind keys|text. Shown 1.5 s after the last key."""
    if not events or mode == "off":
        return []
    out = []
    for e in events.get("events", []):
        if e.get("type") == "key":
            if e.get("label"):   # the keycap text as drawn (a hints file can name a key the way the voice does)
                out.append((float(e["t"]), float(e["t"]) + 1.5, "cap", str(e["label"])))
            else:
                out.append((float(e["t"]), float(e["t"]) + 1.5, "keys", str(e.get("keys", ""))))
        elif e.get("type") == "type" and mode == "all":
            out.append((float(e["t"]), float(e.get("end", e["t"])) + 1.5, "text", str(e.get("text", ""))))
    out.sort()
    # a new overlay replaces the previous one
    for i in range(len(out) - 1):
        if out[i + 1][0] < out[i][1]:
            out[i] = (out[i][0], out[i + 1][0], out[i][2], out[i][3])
    return out


# --------------------------------------------------------------------------- render

def render(src_path: Path, *, out: Optional[Path] = None, events_path: Optional[Path] = None,
           cursor_log: Optional[Path] = None, cursor_scale: float = 1.0, size: Optional[str] = None,
           look: str = "framed", fit: str = "contain", bg: str = "#1e1b4b,#0f172a", pad: float = 0.045,
           radius: float = 0.013, shadow: bool = True, max_zoom: float = 2.0, zoom_click: float = 1.8,
           zoom_type: float = 1.6, zoom_drag: float = 1.4, zoom_scroll: float = 1.0, zoom_hover: float = 1.0,
           detect: str = "auto", cursor: str = "auto", cursor_size: float = 1.6, keys: str = "combos",
           preview: bool = False, plan_only: bool = False, crf: int = 18, keys_pos: str = "bottom",
           key_glyphs: bool = False, hints: Optional[Path] = None,
           cursor_offsets: Sequence[str] = ()) -> Dict[str, Any]:
    import cv2
    import numpy as np
    from .. import ff

    t0 = time.time()
    src, events = load_source(Path(src_path), Path(events_path) if events_path else None)
    if src.frames <= 0:
        raise ShowtimeError("no frames in %s" % src_path)
    if hints:
        events = merge_hints(events or {}, json.loads(Path(hints).read_text(encoding="utf-8")))
    max_zoom = min(float(max_zoom), HARD_MAX_ZOOM)
    zooms = {"click": zoom_click, "type": zoom_type, "drag": zoom_drag, "hover": zoom_hover, "dwell": 1.5,
             "motion": 1.6, "focus": 1.6, "scroll": zoom_scroll}
    # --- output size
    if size:
        try:
            ow, oh = (int(v) for v in size.lower().split("x"))
        except ValueError:
            raise ShowtimeError("--size must look like 1920x1080")
    else:
        ow, oh = (1920, 1080) if src.width >= src.height else (1080, 1920)
    if preview:
        ow, oh = ow // 2, oh // 2
    ow, oh = ow - ow % 2, oh - oh % 2
    # --- cursor track (source pixels, one sample per frame)
    track: Optional[List[Tuple[float, float, float, int]]] = None
    samples: List[Tuple[float, float, float, int]] = []
    if events and events.get("cursor"):
        samples = [(float(r[0]), float(r[1]) * src.scale, float(r[2]) * src.scale, int(r[3]) if len(r) > 3 else 0)
                   for r in events["cursor"]]
    elif cursor_log:
        samples = read_cursor_log(Path(cursor_log), cursor_scale)
    if samples and cursor_offsets:
        samples = apply_cursor_offsets(samples, cursor_offsets, src.scale if events else 1.0)
    if samples:
        track = _resample(samples, src.frames, src.fps)
    # --- actions
    if events:
        actions = actions_from_events(events, src.scale, zooms)
        source_kind = "events"
    elif samples:
        actions = actions_from_cursor(samples, src.width, src.height)
        source_kind = "cursor-log"
    elif detect in ("auto", "motion"):
        log("no events or cursor log: looking for screen changes to zoom on")
        actions = actions_from_motion(src)
        source_kind = "motion"
    else:
        actions = []
        source_kind = "none"
    evl = (events or {}).get("events", []) if events else []
    chapters = [float(e["t"]) for e in evl if e.get("type") == "chapter" and float(e.get("t", 0)) > 0.05]
    wides = [float(e["t"]) for e in evl if e.get("type") == "wide"]
    shots = plan_shots(actions, src.width, src.height, max_zoom=max_zoom, zooms=zooms, chapters=chapters, wides=wides)
    lay = make_layout(src.width, src.height, ow, oh, look, fit, pad)
    cam = simulate_camera(src.frames, src.fps, shots, lay, track)
    stem = src.name if src.kind == "frames" else src.video.stem
    base = src.base_dir
    default_name = ("%s.autozoom" % stem) if src.kind == "video" else "autozoom"
    wanted = base / ("%s%s.mp4" % (default_name, ".preview" if preview else ""))
    out_path = Path(out) if out else _fresh(wanted)
    if out_path.suffix.lower() != ".mp4":
        out_path = out_path.with_suffix(".mp4")
    if not out and out_path != wanted:
        log("%s exists: this run writes %s (and %s); use that name from now on" % (
            wanted.name, out_path.name, out_path.stem + ".camera.json"))
    elif not plan_only:
        log("writing %s" % out_path)
    cam_path = out_path.with_name(out_path.stem + ".camera.json")
    camera = {
        "version": 1, "fps": src.fps, "frames": src.frames, "source_size": [src.width, src.height],
        "output_size": [ow, oh], "look": look, "fit": fit, "window": [lay.wx, lay.wy, lay.ww, lay.wh],
        "source": source_kind, "actions": len(actions),
        "shots": [{"start": round(s.start, 3), "end": round(s.end, 3), "zoom": round(s.zoom, 3),
                   "x": round(s.x / src.width, 4), "y": round(s.y / src.height, 4), "kinds": s.kinds} for s in shots],
        "note": "per frame: [t, zoom, cx, cy]; cx/cy = view centre as a fraction of the SOURCE frame",
        "camera": [[round(i / src.fps, 4), round(z, 4), round((cx - lay.wx) / lay.ww, 5), round((cy - lay.wy) / lay.wh, 5)]
                   for i, (z, cx, cy) in enumerate(cam)],
    }
    write_json(cam_path, camera, indent=None)
    result = {"camera": str(cam_path), "shots": len(shots), "actions": len(actions), "source": source_kind,
              "frames": src.frames, "fps": src.fps, "size": [ow, oh], "shot_list": camera["shots"]}
    # the keycap timeline as data, so an HTML composition can draw its own keycaps in the page style
    ktl_all = keystroke_timeline(events, "all") if events else []
    if ktl_all:
        kp = out_path.with_name(out_path.stem + ".keys.json")
        glyph_labels = Keycaps.__new__(Keycaps)
        glyph_labels.glyphs = True
        write_json(kp, {"note": "keycaps and typed text on the recording's timeline (seconds); label = mac glyphs",
                        "items": [{"at": round(a, 3), "end": round(b, 3), "kind": "keys" if k == "cap" else k, "text": tx,
                                   "label": " ".join(glyph_labels.label(tx)) if k == "keys" else tx}
                                  for a, b, k, tx in ktl_all]})
        result["keys"] = str(kp)
    if plan_only:
        result["seconds"] = round(time.time() - t0, 2)
        return result
    if not shots:
        warn("nothing to zoom on (no clicks, typing or focus events found); the output is framed only")
    # --- overlays
    draw_cur = track is not None and (cursor == "on" or (cursor == "auto" and source_kind != "motion"))
    clicks = [(a.t, a.x, a.y) for a in actions if a.kind == "click"]
    ktl = keystroke_timeline(events, keys)
    keycaps = None
    if ktl:
        keycaps = Keycaps(ow, oh, _font_path(), position=keys_pos, glyphs=key_glyphs)
    css_px = src.scale  # source pixels per CSS pixel (demo dpr)
    # idle: hide the cursor after 2 s without movement
    idle = _idle_alpha(track, src.fps) if draw_cur else None
    bg_canvas, win_mask = make_background(lay, look, bg, radius, shadow)
    # --- encoder
    preset = ff.preset("preview" if preview else "final")
    enc = [ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "%dx%d" % (ow, oh), "-r", _fps_arg(src.fps), "-i", "-"]
    audio = src.kind == "video" and src.has_audio
    if audio:
        enc += ["-i", str(src.video), "-map", "0:v", "-map", "1:a?", "-shortest"]
    enc += ["-vf", preset.vf_tail] + preset.output_args(crf=None if preview else crf, audio=audio) + [str(out_path)]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(enc, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    last_note = time.time()
    n = 0
    try:
        for i, frame in enumerate(iter_frames(src)):
            if i >= len(cam):
                break
            z, cx, cy = cam[i]
            # canvas -> output: out = z*(p - c) + centre
            tx, ty = ow / 2.0 - z * cx, oh / 2.0 - z * cy
            s_total = z * lay.ws
            src_img = frame
            sx = s_total
            if s_total < 0.9:  # downscale with area filtering first (sharp text, no aliasing)
                f = min(1.0, s_total * 1.15)
                src_img = cv2.resize(frame, (max(1, int(src.width * f)), max(1, int(src.height * f))), interpolation=cv2.INTER_AREA)
                sx = s_total / f
            M_src = np.float32([[sx, 0, z * lay.wx + tx], [0, sx, z * lay.wy + ty]])
            warped = cv2.warpAffine(src_img, M_src, (ow, oh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            if abs(z - 1.0) < 1e-4 and abs(tx) < 1e-3 and abs(ty) < 1e-3:
                bgw, m = bg_canvas, win_mask
            else:
                M_bg = np.float32([[z, 0, tx], [0, z, ty]])
                bgw = cv2.warpAffine(bg_canvas, M_bg, (ow, oh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
                # replicate the mask's edge: with --fit cover the window runs past the canvas, and a camera
                # that follows an action out there must still see the window, not the background
                m = cv2.warpAffine(win_mask, M_bg, (ow, oh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
            m3 = m[..., None]
            img = (warped.astype(np.float32) * m3 + bgw * (1 - m3)).astype(np.uint8)
            t = i / src.fps
            if draw_cur and track is not None:
                _, px, py, down = track[i]
                if not math.isnan(px):
                    ox = z * (lay.wx + px * lay.ws) + tx
                    oy = z * (lay.wy + py * lay.ws) + ty
                    scale_px = z * lay.ws * css_px
                    for (ct, cxp, cyp) in clicks:
                        dtc = t - ct
                        if 0 <= dtc <= 0.35:
                            rx = z * (lay.wx + cxp * lay.ws) + tx
                            ry = z * (lay.wy + cyp * lay.ws) + ty
                            p = dtc / 0.35
                            draw_ripple(img, rx, ry, (6 + 22 * (1 - (1 - p) ** 3)) * scale_px, 0.45 * (1 - p))
                    dip = 1.0
                    for (ct, _, _) in clicks:
                        if 0 <= t - ct <= 0.12:
                            dip = 0.85
                    draw_cursor(img, ox, oy, 19.5 * cursor_size * scale_px * dip, idle[i] if idle else 1.0)
            if keycaps is not None:
                cur = [o for o in ktl if o[0] <= t]
                for (a, b, kind, text) in cur[-1:]:   # only the latest overlay (a new one replaces the old)
                    if a <= t <= b + 0.3:
                        alpha = min(1.0, (t - a) / 0.15) if t < a + 0.15 else (1.0 if t <= b else max(0.0, 1 - (t - b) / 0.3))
                        if kind == "text":
                            ev_end = b - 1.5
                            k = 1.0 if t >= ev_end or ev_end <= a else (t - a) / (ev_end - a)
                            text = text[:max(1, int(math.ceil(len(text) * k)))]
                        keycaps.draw(img, kind, text, alpha)
            proc.stdin.write(img.tobytes())
            n += 1
            if time.time() - last_note > 5:
                last_note = time.time()
                log("autozoom %d/%d frames" % (n, src.frames))
    except BrokenPipeError:
        pass
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        err = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
        rc = proc.wait()
    if rc != 0:
        raise ShowtimeError("ffmpeg failed while encoding %s:\n%s" % (out_path.name, err.strip()[-800:]))
    result.update({"output": str(out_path), "frames_written": n, "seconds": round(time.time() - t0, 2),
                   "cursor": bool(draw_cur), "keycaps": len(ktl)})
    if not out and out_path != wanted:
        # renders never overwrite: say it again at the end, where the next step is read
        result["renamed_from"] = str(wanted)
    return result


def _resample(samples: Sequence[Tuple[float, float, float, int]], n: int, fps: float) -> List[Tuple[float, float, float, int]]:
    """One cursor sample per frame (linear interpolation, button state held)."""
    out = []
    j = 0
    for i in range(n):
        t = i / fps
        while j + 1 < len(samples) and samples[j + 1][0] <= t:
            j += 1
        a = samples[j]
        if a[0] > t and j == 0:
            out.append((t, a[1], a[2], 0) if abs(a[0] - t) < 0.5 else (t, float("nan"), float("nan"), 0))
            continue
        if j + 1 < len(samples):
            b = samples[j + 1]
            k = 0.0 if b[0] <= a[0] else min(1.0, max(0.0, (t - a[0]) / (b[0] - a[0])))
            out.append((t, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k, a[3]))
        else:
            out.append((t, a[1], a[2], a[3]))
    return out


def _idle_alpha(track: Optional[Sequence[Tuple[float, float, float, int]]], fps: float) -> Optional[List[float]]:
    if not track:
        return None
    alpha = []
    still = 0.0
    prev = None
    for (_, x, y, d) in track:
        moved = prev is None or math.isnan(x) or abs(x - prev[0]) + abs(y - prev[1]) > 0.5 or d
        still = 0.0 if moved else still + 1.0 / fps
        prev = (x, y)
        alpha.append(1.0 if still < 2.0 else max(0.0, 1 - (still - 2.0) / 0.3))
    return alpha


def _font_path() -> Optional[str]:
    try:
        from ..assets import fonts
        return str(fonts.resolve("Inter", 600))
    except Exception as e:  # noqa: BLE001 - keycaps still work with PIL's built-in font
        debug("keycap font unavailable (%s); using the built-in font" % e)
        return None


def _fps_arg(fps: float) -> str:
    from fractions import Fraction
    fr = Fraction(fps).limit_denominator(1001)
    return "%d/%d" % (fr.numerator, fr.denominator) if fr.denominator != 1 else str(fr.numerator)


def _fresh(p: Path) -> Path:
    if not p.exists():
        return p
    stem, suf = p.name[:-len(p.suffix)] if p.suffix else p.name, p.suffix
    k = 2
    while (p.parent / ("%s-%d%s" % (stem, k, suf))).exists():
        k += 1
    return p.parent / ("%s-%d%s" % (stem, k, suf))


# --------------------------------------------------------------------------- CLI

def add_arguments(p) -> None:
    p.add_argument("source", help="demo folder (events.json + frames/) or a video file")
    p.add_argument("-o", "--output", help="output .mp4 (default: <source>/autozoom.mp4 or <video>.autozoom.mp4)")
    p.add_argument("--events", help="events.json for a video file (demo format)")
    p.add_argument("--cursor-log", help="cursor telemetry for a screen recording: JSON [[t,x,y,down]...] or CSV t,x,y,down")
    p.add_argument("--cursor-scale", type=float, default=1.0,
                   help="multiply cursor-log coordinates (e.g. 2 for macOS points on a Retina capture)")
    p.add_argument("--size", help="output WxH (default 1920x1080, or 1080x1920 for portrait sources)")
    p.add_argument("--look", choices=["framed", "plain"], default="framed",
                   help="framed: window on a gradient with rounded corners + shadow (default); plain: just the recording")
    p.add_argument("--fit", choices=["contain", "cover"], default="contain",
                   help="cover fills the frame (e.g. a 9:16 follow-cam from a 16:9 recording)")
    p.add_argument("--bg", default="#1e1b4b,#0f172a", help="background colour or two-colour gradient (default indigo/slate)")
    p.add_argument("--pad", type=float, default=0.045, help="padding around the window, fraction of the short side (default 0.045)")
    p.add_argument("--no-shadow", action="store_true", help="no drop shadow under the window")
    p.add_argument("--max-zoom", type=float, default=2.0, help="zoom limit (default 2.0, hard cap 2.8)")
    p.add_argument("--zoom-click", type=float, default=1.8, help="zoom for clicks (default 1.8)")
    p.add_argument("--zoom-type", type=float, default=1.6, help="zoom while typing (default 1.6)")
    p.add_argument("--zoom-drag", type=float, default=1.4, help="zoom for drags (default 1.4)")
    p.add_argument("--zoom-scroll", type=float, default=1.0, help="zoom while scrolling (default 1.0 = overview)")
    p.add_argument("--zoom-hover", type=float, default=1.0, help="zoom on hovers (default 1.0 = none)")
    p.add_argument("--detect", choices=["auto", "motion", "none"], default="auto",
                   help="without events/cursor log: zoom where the screen changes (auto) or not at all")
    p.add_argument("--cursor", choices=["auto", "on", "off"], default="auto", help="draw the synthetic cursor (default auto)")
    p.add_argument("--cursor-size", type=float, default=1.6, help="cursor scale vs a normal pointer (default 1.6)")
    p.add_argument("--keys", choices=["combos", "all", "off"], default="combos",
                   help="keycap overlay: key combos only (default), also typed text, or off")
    p.add_argument("--keys-pos", choices=list(KEY_POSITIONS), default="bottom",
                   help="where keycaps sit (default bottom centre, 88%% height)")
    p.add_argument("--key-glyphs", action="store_true", help="draw ⌘ ⌥ ⇧ ⌃ ↵ instead of Cmd/Opt/Shift/Ctrl/Enter")
    p.add_argument("--hints", help="JSON list of camera edits merged into events.json (focus / wide / drop), "
                                   "to change shots without a new take")
    p.add_argument("--cursor-offset", action="append", default=[], metavar="T0-T1:DX,DY",
                   help="move the recorded pointer by dx,dy CSS px inside t0-t1 s, eased (repeatable)")
    p.add_argument("--crf", type=int, default=18, help="x264 quality (default 18)")
    p.add_argument("--preview", action="store_true", help="half size, fast encode (quick look)")
    p.add_argument("--plan", action="store_true", help="only write the camera plan (.camera.json), no video")
    p.add_argument("--json", action="store_true", help="print a JSON report")


def run_cli(args) -> int:
    from ..common import print_json
    res = render(Path(args.source), out=Path(args.output) if args.output else None, events_path=args.events,
                 cursor_log=args.cursor_log, cursor_scale=args.cursor_scale, size=args.size, look=args.look,
                 fit=args.fit, bg=args.bg, pad=args.pad, shadow=not args.no_shadow, max_zoom=args.max_zoom,
                 zoom_click=args.zoom_click, zoom_type=args.zoom_type, zoom_drag=args.zoom_drag,
                 zoom_scroll=args.zoom_scroll, zoom_hover=args.zoom_hover, detect=args.detect, cursor=args.cursor,
                 cursor_size=args.cursor_size, keys=args.keys, preview=args.preview, plan_only=args.plan, crf=args.crf,
                 keys_pos=args.keys_pos, key_glyphs=args.key_glyphs, hints=Path(args.hints) if args.hints else None,
                 cursor_offsets=args.cursor_offset)
    if args.json:
        print_json(res)
    else:
        log("%d shot(s) from %d action(s) (%s) in %.1fs" % (res["shots"], res["actions"], res["source"], res["seconds"]))
        for sh in res.get("shot_list", [])[:20]:
            log("  %6.2f-%6.2fs  x%.2f at %.0f%%,%.0f%%  (%s)" % (sh["start"], sh["end"], sh["zoom"], sh["x"] * 100,
                                                               sh["y"] * 100, "+".join(sh["kinds"])))
        if res.get("renamed_from"):
            log("NOTE: %s already existed, so this take is %s: use the new name in the project (not %s)" % (
                Path(res["renamed_from"]).name, Path(res["output"]).name, Path(res["renamed_from"]).name))
        if res.get("output"):
            print(res["output"])
        print(res["camera"])
    return 0


def main(argv: Optional[Sequence[str]] = None, prog: str = "showtime footage autozoom") -> int:
    """Entry point used by `showtime footage autozoom ...` and `showtime autozoom ...`."""
    import argparse
    p = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n\n")[0] + "\n\n" + DESCRIPTION,
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=EXAMPLES)
    add_arguments(p)
    args = p.parse_args(list(argv) if argv is not None else None)
    return run_cli(args)


DESCRIPTION = (
    "Inputs: a folder from `showtime demo record` (best: exact clicks, typing and element boxes), a screen\n"
    "recording plus --cursor-log telemetry, or a bare recording (zooms where the screen changes).\n"
    "Writes <name>.autozoom.mp4 and <name>.camera.json (per-frame zoom/centre for HTML compositions).")
EXAMPLES = (
    "examples:\n"
    "  showtime autozoom showtime-out/walkthrough-20260926-101500\n"
    "  showtime autozoom rec/ --look plain --size 1080x1920 --fit cover     # vertical follow-cam\n"
    "  showtime autozoom screen.mp4 --cursor-log cursor.csv --cursor-scale 2\n"
    "  showtime autozoom rec/ --preview                                     # quick half-size check\n"
    "  showtime autozoom rec/ --plan --json                                 # camera plan only")

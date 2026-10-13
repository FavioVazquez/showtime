"""X-ray: measure what happened in a filmed clip (sound onsets, camera motion), then check a finished film against it.

`analyze` writes <job>/xray/xray.json (schema showtime.xray/1, the contract in references/workflows/xray.md) and
<job>/xray/check.jpg; `verify` reads a rendered film back: the sync marker in its corner, the audio against the
source, and (optionally) the smoothness of a scrolling band.

Onset detector: a high-passed copy of the sound, its RMS on a 1 ms grid, bursts above an adaptive floor, the onset
of a burst is its first millisecond within 6 dB of the burst's peak. numpy and scipy only (not st.audio.beats: that
one re-picks differently on loudness-normalised sound). Tracking: cv2 KLT + RANSAC homographies, seeded.
"""
from __future__ import annotations

import glob
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np

from . import ff
from .common import ShowtimeError, log, read_json, warn, write_json

SCHEMA = "showtime.xray/1"
SR = 48000
MARKER_SIZE = 6
MARKER_INSET = 10            # the marker's top-left is (width - 10, height - 10)
TRACK_MAX_BYTES = 1 << 30      # the gray frames --track keeps in memory; long clips are tracked at a smaller size, then refused
TRACK_MIN_WIDTH = 320
MARKER_SLACK = 2             # a marker frame this close to an expected one still counts as matched (reported with its offset)
LAG_LIMIT_MS = 20.0          # qa: audio more than this far from the source fails
AUDIO_SECONDS = 12.0
DETECT_HP_HZ = 500.0
FLOOR_PCT = 30               # the adaptive floor: this percentile of the envelope over FLOOR_WIN_S
FLOOR_WIN_S = 1.0
PEAK_DROP_DB = 6.0           # onset = first ms within this many dB of the burst's peak
RING_MS = 15                 # fragments of one burst closer than this are joined
PRECURSOR_DB = 10.0          # a burst this much louder within min_gap/2 after a weaker one makes the weaker its precursor
ABS_GATE_DB = -75.0          # nothing below this is a sound (digital silence)


# ------------------------------------------------------------------ small helpers

def frame_of(t: float, fps: float) -> int:
    """The source frame an event at t seconds lands on: floor(t * fps) (a hair of slack for float error)."""
    return int(math.floor(t * fps + 1e-9))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_points(text: str) -> List[List[float]]:
    """"x,y x,y x,y" -> [[x, y], ...] (at least 3 points)."""
    pts: List[List[float]] = []
    for tok in str(text).replace(";", " ").split():
        parts = tok.split(",")
        if len(parts) != 2:
            raise ShowtimeError("bad point %r (expected x,y)" % tok, hint='a region is "x,y x,y x,y ..." in source pixels')
        try:
            pts.append([float(parts[0]), float(parts[1])])
        except ValueError:
            raise ShowtimeError("bad point %r (expected numbers x,y)" % tok)
    if len(pts) < 3:
        raise ShowtimeError("a polygon needs at least 3 points (got %d)" % len(pts))
    return pts


# ------------------------------------------------------------------ onset detector

def envelope_db(x: np.ndarray, sr: int = SR, hp_hz: float = DETECT_HP_HZ) -> np.ndarray:
    """RMS of the high-passed sound on a 1 ms grid, in dB re full scale, smoothed over 3 ms."""
    from scipy import ndimage, signal
    x = np.asarray(x, dtype=np.float64)
    sos = signal.butter(2, hp_hz, "hp", fs=sr, output="sos")
    y = signal.sosfilt(sos, x)
    per = max(1, int(round(sr / 1000.0)))
    n = len(y) // per
    if n < 3:
        return np.full(max(n, 1), -120.0)
    e = np.sqrt((y[: n * per].reshape(n, per) ** 2).mean(axis=1) + 1e-12)
    return ndimage.uniform_filter1d(20.0 * np.log10(e), 3)


def _floor_db(env: np.ndarray) -> np.ndarray:
    """The adaptive floor: a low percentile of the envelope over about a second, per millisecond."""
    from scipy import ndimage
    step = 5
    coarse = env[::step]
    size = max(3, int(FLOOR_WIN_S * 1000 / step))
    fl = ndimage.percentile_filter(coarse, FLOOR_PCT, size=size, mode="nearest")
    return np.interp(np.arange(len(env)), np.arange(0, len(env), step)[: len(fl)], fl)


def _runs(mask: np.ndarray) -> List[Tuple[int, int]]:
    """[(first, last)] of every run of True."""
    if not mask.any():
        return []
    d = np.diff(np.concatenate(([0], mask.astype(np.int8), [0])))
    return list(zip(np.where(d == 1)[0].tolist(), (np.where(d == -1)[0] - 1).tolist()))


def _band_of(x: np.ndarray, i_ms: int, sr: int) -> str:
    """low (<300 Hz) / mid / high (>2 kHz): where the energy of the 24 ms after the onset is."""
    a = int(i_ms * sr / 1000.0)
    seg = np.asarray(x[a: a + int(0.024 * sr)], dtype=np.float64)
    if len(seg) < 32:
        return "mid"
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    f = np.fft.rfftfreq(len(seg), 1.0 / sr)
    e = (spec[f < 300].sum(), spec[(f >= 300) & (f <= 2000)].sum(), spec[f > 2000].sum())
    return ("low", "mid", "high")[int(np.argmax(e))]


def detect(x: np.ndarray, sr: int = SR, *, min_gap: float = 0.12, sensitivity: float = 0.5,
           t_from: float = 0.0, t_to: Optional[float] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(events, dropped) of a mono sound. Times are seconds from the start of `x` plus t_from (so pass the slice
    that starts at t_from). `sensitivity` 0..1: higher finds quieter and closer hits."""
    s = min(1.0, max(0.0, float(sensitivity)))
    env = envelope_db(x, sr)
    n = len(env)
    floor = _floor_db(env)
    k_db = 18.0 - 12.0 * s                    # how far over the floor a burst must rise
    rel_db = 15.0 + 20.0 * s                  # and how far under the loud events it may sit
    above = (env > floor + k_db) & (env > ABS_GATE_DB)
    runs = _runs(above)
    merged: List[List[int]] = []
    for a, b in runs:                                  # ringing of one click: fragments within 15 ms are one burst
        if merged and a - merged[-1][1] <= RING_MS:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    bursts = []
    for a, b in merged:
        seg = env[a: b + 1]
        pk = float(seg.max())
        on = a + int(np.argmax(seg >= pk - PEAK_DROP_DB))
        bursts.append({"i": on, "pk": pk})
    dropped: List[Dict[str, Any]] = []
    kept: List[Dict[str, Any]] = []
    for j, b in enumerate(bursts):
        nx = bursts[j + 1] if j + 1 < len(bursts) else None
        if nx is not None and (nx["i"] - b["i"]) / 1000.0 < min_gap / 2 and nx["pk"] - b["pk"] >= PRECURSOR_DB:
            dropped.append({"t": round(t_from + b["i"] / 1000.0, 3),
                            "why": "precursor of the louder click at %.3f" % (t_from + nx["i"] / 1000.0)})
        else:
            kept.append(b)
    bursts = kept
    if bursts:
        ref = float(np.percentile([b["pk"] for b in bursts], 85))
        keep = []
        for b in bursts:
            if b["pk"] < ref - rel_db:
                dropped.append({"t": round(t_from + b["i"] / 1000.0, 3),
                                "why": "%.0f dB under the loud events (below the sensitivity gate)" % (ref - b["pk"])})
            else:
                keep.append(b)
        bursts = keep
    events: List[Dict[str, Any]] = []
    for b in bursts:
        t = t_from + b["i"] / 1000.0
        if t_to is not None and t > t_to:
            continue
        if events and t - events[-1]["t"] < min_gap - 1e-9:
            dropped.append({"t": round(t, 3), "why": "within min_gap of event %d" % events[-1]["i"]})
            continue
        events.append({"i": len(events), "t": round(t, 3), "pk": b["pk"], "ms": b["i"]})
    top = max([10 ** (e["pk"] / 20.0) for e in events] or [1.0])
    out = []
    for e in events:
        out.append({"i": e["i"], "t": e["t"], "strength": round(min(1.0, 10 ** (e["pk"] / 20.0) / top), 3),
                    "band": _band_of(x, e["ms"], sr)})
    dropped.sort(key=lambda d: d["t"])
    return out, dropped


# ------------------------------------------------------------------ flux engine (dense or sustained sound)

FLUX_WIN = 2048              # STFT window (samples) and hop: the spectral-flux curve
FLUX_HOP = 256
FLUX_MEDIAN_S = 0.2          # the adaptive threshold: a moving median of the flux over this long ...
REFINE_MS = 20               # ... and each peak is refined on the 1 ms grid within +-20 ms
MIN_RISE_DB = 3.0
AUTO_RATE = 0.3              # auto: the envelope engine under this many events per second of a sustained sound -> flux
SUSTAINED = 0.5              # "sustained": at least this share of the sound is within 25 dB of its loud parts
DEFAULT_MIN_GAP = {"envelope": 0.12, "flux": 0.06}


def flux_curve(x: np.ndarray, sr: int = SR) -> Tuple[np.ndarray, np.ndarray]:
    """(times of the frame centres, half-wave rectified spectral flux summed over bins of a log-magnitude STFT)."""
    from scipy import signal
    f, t, Z = signal.stft(np.asarray(x, dtype=np.float32), sr, nperseg=FLUX_WIN, noverlap=FLUX_WIN - FLUX_HOP,
                          window="hann", boundary=None, padded=False)
    if Z.shape[1] < 3:
        return np.zeros(0), np.zeros(0)
    mag = np.log1p(1000.0 * np.abs(Z))
    d = np.concatenate([[0.0], np.maximum(mag[:, 1:] - mag[:, :-1], 0.0).sum(axis=0)])
    return t, d


def _refine(env: np.ndarray, ms: int) -> int:
    """The 1 ms bin of the onset near `ms`: the first ms of the final rise to the local peak within 6 dB of it
    (inside +-20 ms); `ms` itself when the envelope does not rise there."""
    a, b = max(0, ms - REFINE_MS), min(len(env), ms + REFINE_MS + 1)
    if b - a < 4:
        return ms
    seg = env[a:b]
    ip = int(np.argmax(seg))
    i0 = ip
    while i0 > 0 and seg[i0 - 1] < seg[i0]:
        i0 -= 1
    if seg[ip] - seg[i0] < MIN_RISE_DB:
        return ms
    return a + i0 + int(np.argmax(seg[i0: ip + 1] >= seg[ip] - PEAK_DROP_DB))


def detect_flux(x: np.ndarray, sr: int = SR, *, min_gap: float = 0.06, sensitivity: float = 0.5,
                t_from: float = 0.0, t_to: Optional[float] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(events, dropped) by spectral flux: peaks over a moving median + k robust deviations (k falls as
    `sensitivity` rises), at least `min_gap` apart (the stronger of two close peaks stays), each placed on the 1 ms grid."""
    from scipy import ndimage, signal
    s = min(1.0, max(0.0, float(sensitivity)))
    t, d = flux_curve(x, sr)
    if len(d) == 0:
        return [], []
    size = max(3, int(FLUX_MEDIAN_S * sr / FLUX_HOP) | 1)
    med = ndimage.median_filter(d, size=size, mode="nearest")
    scale = 1.4826 * float(np.median(np.abs(d - med))) + 1e-9
    k = 3.8 - 3.0 * s
    pk, _ = signal.find_peaks(d, height=med + k * scale)
    order = sorted(pk.tolist(), key=lambda i: -d[i])           # the strongest first: a weaker neighbour within min_gap goes
    kept: List[int] = []
    dropped: List[Dict[str, Any]] = []
    env = envelope_db(x, sr)
    for i in order:
        near = [j for j in kept if abs(t[i] - t[j]) < min_gap - 1e-9]
        if near:
            dropped.append({"t": round(t_from + t[i], 3), "why": "within min_gap of the stronger onset at %.3f" % (t_from + t[near[0]])})
        else:
            kept.append(i)
    kept.sort()
    top = float(max(d[i] for i in kept)) if kept else 1.0
    events: List[Dict[str, Any]] = []
    for i in kept:
        ms = _refine(env, int(round(t[i] * 1000.0)))
        tt = t_from + ms / 1000.0
        if t_to is not None and tt > t_to:
            continue
        events.append({"i": 0, "t": round(tt, 3), "strength": round(float(d[i]) / top, 3), "band": _band_of(x, ms, sr)})
    events.sort(key=lambda e: e["t"])
    spaced: List[Dict[str, Any]] = []
    for e in events:                                 # refining moved some: keep min_gap on the final times too
        if spaced and e["t"] - spaced[-1]["t"] < min_gap - 1e-9:
            if e["strength"] > spaced[-1]["strength"]:
                dropped.append({"t": spaced[-1]["t"], "why": "within min_gap of the stronger onset at %.3f" % e["t"]})
                spaced[-1] = e
            else:
                dropped.append({"t": e["t"], "why": "within min_gap of the stronger onset at %.3f" % spaced[-1]["t"]})
        else:
            spaced.append(e)
    events = spaced
    for n, e in enumerate(events):
        e["i"] = n
    dropped.sort(key=lambda d_: d_["t"])
    return events, dropped


def is_sustained(x: np.ndarray, sr: int = SR) -> bool:
    """Most of the sound is within 25 dB of its loud parts (music, a tone, a hum), unlike separate clicks in quiet."""
    env = envelope_db(x, sr)
    if len(env) < 100:
        return False
    top = float(np.percentile(env, 99))
    return bool(float(np.mean((env > top - 25.0) & (env > ABS_GATE_DB))) >= SUSTAINED)


def pick_engine(x: np.ndarray, engine: str, sr: int = SR, *, min_gap: Optional[float] = None, sensitivity: float = 0.5,
                t_from: float = 0.0, t_to: Optional[float] = None) -> Tuple[str, float, str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(engine that ran, its min_gap, why, events, dropped) for engine envelope | flux | auto."""
    if engine not in ("envelope", "flux", "auto"):
        raise ShowtimeError("--engine is envelope, flux or auto (got %r)" % engine)
    if engine == "flux":
        mg = min_gap if min_gap is not None else DEFAULT_MIN_GAP["flux"]
        ev, dr = detect_flux(x, sr, min_gap=mg, sensitivity=sensitivity, t_from=t_from, t_to=t_to)
        return "flux", mg, "asked for flux", ev, dr
    mg = min_gap if min_gap is not None else DEFAULT_MIN_GAP["envelope"]
    ev, dr = detect(x, sr, min_gap=mg, sensitivity=sensitivity, t_from=t_from, t_to=t_to)
    if engine == "envelope":
        return "envelope", mg, "asked for envelope", ev, dr
    secs = len(x) / float(sr)
    rate = len(ev) / secs if secs > 0 else 0.0
    if rate < AUTO_RATE and is_sustained(x, sr):
        mg2 = min_gap if min_gap is not None else DEFAULT_MIN_GAP["flux"]
        ev2, dr2 = detect_flux(x, sr, min_gap=mg2, sensitivity=sensitivity, t_from=t_from, t_to=t_to)
        return "flux", mg2, ("auto: the envelope engine found %d events in %.1f s (under %.1f per second) of sustained sound, "
                             "so spectral flux ran" % (len(ev), secs, AUTO_RATE)), ev2, dr2
    return "envelope", mg, "auto: separate hits (%d events in %.1f s), the envelope engine" % (len(ev), secs), ev, dr


# ------------------------------------------------------------------ analyze

def _source_info(clip: Path) -> Dict[str, Any]:
    pr = ff.probe(clip)
    if not pr.get("has_video"):
        raise ShowtimeError("%s has no video stream" % clip.name, hint="x-ray analyzes a filmed clip (video with its sound)")
    fps = pr.get("fps") or 30.0
    vfr = _is_vfr(pr)
    info = {"file": clip.name, "sha256": _sha256(clip), "fps": round(float(fps), 6) if fps != int(fps) else int(fps),
            "duration": round(float(pr.get("duration") or pr.get("video_duration") or 0.0), 3),
            "width": int(pr.get("width") or 0), "height": int(pr.get("height") or 0), "has_audio": bool(pr.get("has_audio"))}
    if vfr:
        info["vfr"] = True
    return info


def validate_clip(clip: Any) -> Path:
    """Refuse a clip that cannot be analyzed (missing, no picture, no sound) before anything is created for it."""
    clip = Path(clip)
    if not clip.is_file():
        raise ShowtimeError("clip not found: %s" % clip, hint="pass the video file you filmed")
    pr = ff.probe(clip)
    if not pr.get("has_video"):
        raise ShowtimeError("%s has no video stream" % clip.name, hint="x-ray analyzes a filmed clip (video with its sound)")
    if not pr.get("has_audio"):
        raise ShowtimeError("%s has no sound to analyze" % clip.name, hint="x-ray reads the events from the clip's audio")
    return clip


def _is_vfr(pr: Dict[str, Any]) -> bool:
    """A variable-frame-rate clip (a phone video): r_frame_rate and avg_frame_rate differ by more than 1 %."""
    r, a = pr.get("r_fps"), pr.get("avg_fps")
    return bool(r and a and abs(r - a) > 0.01 * max(r, a))


VFR_WARNING = ("the clip is variable frame rate (a phone video): event frames are counted at one rate and may drift. "
               "Run `showtime footage trim <clip> --webm` (constant 30 fps) and x-ray that file")


def analyze(clip: Any, out_dir: Any, *, t_from: float = 0.0, t_to: Optional[float] = None, min_gap: Optional[float] = None,
            sensitivity: float = 0.5, track: Optional[Dict[str, Any]] = None, engine: str = "auto") -> Dict[str, Any]:
    """Write <out_dir>/xray.json and check.jpg for a clip. `track`: {"region": [[x, y]...], "ref_time": T,
    "masks": [[[x, y]...]...]} to also track the object. Returns the xray.json dict."""
    from .audio import wav
    clip = Path(clip)
    if not clip.is_file():
        raise ShowtimeError("clip not found: %s" % clip, hint="pass the video file you filmed")
    out = Path(out_dir)
    src = _source_info(clip)
    if src.get("vfr"):
        warn(VFR_WARNING)
    if not src.pop("has_audio"):
        raise ShowtimeError("%s has no sound to analyze" % clip.name, hint="x-ray reads the hits from the clip's audio")
    if t_to is not None and t_to <= t_from:
        raise ShowtimeError("--to (%g) must be after --from (%g)" % (t_to, t_from))
    out.mkdir(parents=True, exist_ok=True)
    dur = (t_to - t_from) if t_to is not None else None
    x = wav.load(clip, sr=SR, mono=True, offset=max(0.0, t_from), duration=dur)
    ran, min_gap, why, events, dropped = pick_engine(x, engine, SR, min_gap=min_gap, sensitivity=sensitivity,
                                                    t_from=max(0.0, t_from), t_to=t_to)
    fps = float(src["fps"])
    for e in events:
        e["frame"] = frame_of(e["t"], fps)
    events = [{"i": e["i"], "t": e["t"], "frame": e["frame"], "strength": e["strength"], "band": e["band"]} for e in events]
    doc: Dict[str, Any] = {
        "schema": SCHEMA, "source": src,
        "detector": {"engine": ran, "min_gap": min_gap, "sensitivity": sensitivity, "from": t_from, "to": t_to, "note": why},
        "events": events, "dropped": dropped, "track": None}
    if track:
        doc["track"] = track_clip(clip, src, track["region"], track["ref_time"], track.get("masks") or [])
    write_json(out / "xray.json", doc)
    try:
        (out / "source.path").write_text(str(clip.resolve()), encoding="utf-8")   # local only: lets verify find the clip
    except OSError:
        pass
    check_sheet(clip, doc, x, max(0.0, t_from), out / "check.jpg")
    return doc


def check_sheet(clip: Path, doc: Dict[str, Any], x: np.ndarray, t0: float, dest: Path) -> Path:
    """check.jpg: the waveform with a numbered tick per event (dropped ones grey) and, with a track, the region on 6 frames."""
    from PIL import Image, ImageDraw
    W, H = 1800, 360
    img = Image.new("RGB", (W, H), (18, 20, 26))
    d = ImageDraw.Draw(img)
    dur = float(doc["source"]["duration"]) or (t0 + len(x) / SR)
    t1 = t0 + len(x) / SR
    left, right, top, bot = 30, W - 20, 40, H - 30
    mid = (top + bot) // 2

    def px(t: float) -> int:
        return int(left + (t / max(dur, 1e-6)) * (right - left))

    a, b = px(t0), px(t1)
    cols = max(1, b - a)
    n = len(x)
    if n:
        edges = np.linspace(0, n, cols + 1).astype(int)
        peak = max(float(np.abs(x).max()), 1e-9)
        for c in range(cols):
            seg = x[edges[c]: max(edges[c + 1], edges[c] + 1)]
            if len(seg):
                lo, hi = float(seg.min()) / peak, float(seg.max()) / peak
                d.line([(a + c, mid - hi * (mid - top)), (a + c, mid - lo * (mid - top))], fill=(120, 150, 200))
    for s in range(int(dur) + 1):
        d.line([(px(s), bot + 2), (px(s), bot + 8)], fill=(120, 120, 130))
        d.text((px(s) + 2, bot + 10), "%ds" % s, fill=(150, 150, 160))
    for dr in doc.get("dropped") or []:
        d.line([(px(dr["t"]), top), (px(dr["t"]), bot)], fill=(90, 90, 96))
    for e in doc["events"]:
        xx = px(e["t"])
        d.line([(xx, top - 8), (xx, bot)], fill=(255, 90, 60), width=1)
        d.text((xx + 2, 8 + (e["i"] % 2) * 12), str(e["i"]), fill=(255, 180, 160))
    d.text((left, H - 14), "%s  %d events (red), %d dropped (grey)  min_gap %.3g  sensitivity %.3g" % (
        doc["source"]["file"], len(doc["events"]), len(doc.get("dropped") or []),
        doc["detector"]["min_gap"], doc["detector"]["sensitivity"]), fill=(200, 200, 210))
    tr = doc.get("track")
    if tr:
        img = _with_track_row(img, clip, doc, tr)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dest), quality=88)
    return dest


def _with_track_row(img: Any, clip: Path, doc: Dict[str, Any], tr: Dict[str, Any]) -> Any:
    """Append the region outline drawn on 6 frames, projected by the tracked homographies."""
    import tempfile
    from PIL import Image, ImageDraw
    from .qa import media
    Hs = tr["H"]
    n = len(Hs)
    fps = float(doc["source"]["fps"])
    frames = sorted({int(round(i * (n - 1) / 5.0)) for i in range(6)})
    tile_w = img.width // 6
    sw, sh = doc["source"]["width"], doc["source"]["height"]
    tile_h = int(tile_w * sh / max(sw, 1))
    row = Image.new("RGB", (img.width, tile_h + 4), (18, 20, 26))
    with tempfile.TemporaryDirectory(prefix="st-xray-") as td:
        paths = media.extract_frames(clip, [(f + 0.5) / fps for f in frames], td, width=tile_w,
                                     duration=doc["source"]["duration"], fps=fps, names=["f%d.jpg" % f for f in frames])
        by_frame = {}                                    # extraction skips a failed frame: pair by the name it was written under
        for p in paths:
            try:
                by_frame[int(Path(p).stem[1:])] = p
            except ValueError:
                continue
        for k, f in enumerate(frames):
            if f not in by_frame:
                continue
            with Image.open(str(by_frame[f])) as raw:
                im = raw.convert("RGB")
            sc = im.width / float(sw)
            dr = ImageDraw.Draw(im)
            H = np.array(Hs[f], dtype=np.float64).reshape(3, 3)

            def proj(poly: Sequence[Sequence[float]]) -> List[Tuple[float, float]]:
                pts = np.hstack([np.array(poly, dtype=np.float64), np.ones((len(poly), 1))]) @ H.T
                return [(float(p[0] / p[2]) * sc, float(p[1] / p[2]) * sc) for p in pts]

            q = proj(tr["region"])
            dr.line(q + [q[0]], fill=(60, 255, 120), width=2)
            for m in tr.get("mask") or []:
                q = proj(m)
                dr.line(q + [q[0]], fill=(255, 200, 60), width=1)
            dr.text((4, 4), "frame %d" % f, fill=(255, 255, 255))
            row.paste(im, (k * tile_w, 0))
    out = Image.new("RGB", (img.width, img.height + row.height), (18, 20, 26))
    out.paste(img, (0, 0))
    out.paste(row, (0, img.height))
    return out


# ------------------------------------------------------------------ tracking

def read_gray_frames(clip: Path, width: int, height: int, scale_w: int) -> Iterator[np.ndarray]:
    """Every frame of the clip as a gray array scaled to scale_w pixels wide (the resolved ffmpeg, a pipe)."""
    import subprocess
    sh = max(2, int(round(scale_w * height / float(width) / 2.0)) * 2)
    args = [ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(clip), "-an",
            "-vf", "scale=%d:%d,format=gray" % (scale_w, sh), "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = scale_w * sh
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, dtype=np.uint8).reshape(sh, scale_w)
    finally:
        try:
            proc.stdout.close()
        except OSError:
            pass
        proc.kill()
        proc.wait()


def track_clip(clip: Path, src: Dict[str, Any], region: Sequence[Sequence[float]], ref_time: float,
               masks: Sequence[Sequence[Sequence[float]]]) -> Dict[str, Any]:
    """The `track` object of xray.json: homographies from the reference frame to every frame (source pixels)."""
    scale_w = min(int(src["width"]), 960)
    est = int(float(src.get("duration") or 0.0) * float(src.get("fps") or 30.0)) + 2
    while scale_w > TRACK_MIN_WIDTH and est * scale_w * scale_w * int(src["height"]) / float(src["width"]) > TRACK_MAX_BYTES:
        scale_w = max(TRACK_MIN_WIDTH, int(scale_w * 0.8) // 2 * 2)      # smaller pictures keep a long clip within memory
    s = scale_w / float(src["width"])
    cap = max(1, int(TRACK_MAX_BYTES // max(1.0, scale_w * scale_w * int(src["height"]) / float(src["width"]))))
    frames = []
    for fr in read_gray_frames(clip, int(src["width"]), int(src["height"]), scale_w):
        frames.append(fr)
        if len(frames) > cap:
            raise ShowtimeError("%s is too long to track in memory (over %d frames at %d px wide)" % (clip.name, cap, scale_w),
                                hint="trim the clip first: showtime footage trim <clip> --from A --to B --webm")
    if not frames:
        raise ShowtimeError("could not decode frames of %s for tracking" % clip.name)
    ref = frame_of(ref_time, float(src["fps"]))
    ref = min(max(ref, 0), len(frames) - 1)
    S = np.diag([s, s, 1.0])
    Hs = track_frames(frames, ref, np.array(region, dtype=np.float64) * s, [np.array(m, dtype=np.float64) * s for m in masks])
    full = [np.linalg.inv(S) @ H @ S for H in Hs]
    return {"ref_frame": ref, "region": [[float(a), float(b)] for a, b in region],
            "mask": [[[float(a), float(b)] for a, b in m] for m in masks],
            "H": [[round(float(v), 6) for v in (H / H[2, 2]).reshape(9)] for H in full]}


def _poly_mask(shape: Tuple[int, int], region: np.ndarray, masks: Sequence[np.ndarray], H: np.ndarray) -> np.ndarray:
    import cv2

    def warp(poly: np.ndarray) -> np.ndarray:
        p = np.hstack([poly, np.ones((len(poly), 1))]) @ H.T
        return np.round(p[:, :2] / p[:, 2:3]).astype(np.int32)

    m = np.zeros(shape, dtype=np.uint8)
    cv2.fillPoly(m, [warp(region)], 255)
    for hole in masks:
        cv2.fillPoly(m, [warp(hole)], 0)
    return m


def track_frames(frames: Sequence[np.ndarray], ref: int, region: np.ndarray, masks: Sequence[np.ndarray],
                 max_corners: int = 400) -> List[np.ndarray]:
    """3x3 homographies (reference-frame pixels -> frame pixels), one per frame, from KLT point tracks inside
    the region (minus the masks), composed frame to frame from the reference outwards. Deterministic."""
    import cv2
    cv2.setRNGSeed(0)
    cv2.setNumThreads(1)
    n = len(frames)
    Hs: List[Optional[np.ndarray]] = [None] * n
    Hs[ref] = np.eye(3)
    lk = dict(winSize=(21, 21), maxLevel=3, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))

    def feats(img: np.ndarray, H: np.ndarray) -> Optional[np.ndarray]:
        mk = _poly_mask(img.shape, region, masks, H)
        return cv2.goodFeaturesToTrack(img, max_corners, 0.01, 7, mask=mk)

    for step in (1, -1):
        H_cum = np.eye(3)
        prev = frames[ref]
        pts = feats(prev, H_cum)
        n0 = 0 if pts is None else len(pts)
        i = ref + step
        while 0 <= i < n:
            cur = frames[i]
            Hstep = np.eye(3)
            if pts is not None and len(pts) >= 4:
                nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev, cur, pts, None, **lk)
                good = st.reshape(-1) == 1
                a, b = pts[good], nxt[good]
                if len(a) >= 8:
                    M, inl = cv2.findHomography(a, b, cv2.RANSAC, 2.0)
                    if M is not None:
                        Hstep = M
                        keep = inl.reshape(-1) == 1
                        b = b[keep]
                pts = b.reshape(-1, 1, 2).astype(np.float32) if len(b) else None
            H_cum = Hstep @ H_cum
            Hs[i] = H_cum
            prev = cur
            if pts is None or len(pts) < max(12, n0 // 2):
                fresh = feats(cur, H_cum)
                if fresh is not None and len(fresh) >= 8:
                    pts, n0 = fresh, len(fresh)
            i += step
    return [H if H is not None else np.eye(3) for H in Hs]


# ------------------------------------------------------------------ verify

def _read_marker_levels(video: Path, width: int, height: int) -> np.ndarray:
    """Mean gray of the marker patch on every frame of the film (one value per frame)."""
    import subprocess
    x, y = width - MARKER_INSET, height - MARKER_INSET
    args = [ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(video), "-an",
            "-vf", "crop=%d:%d:%d:%d,format=gray" % (MARKER_SIZE, MARKER_SIZE, x, y),
            "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    cp = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if cp.returncode != 0:
        raise ShowtimeError("ffmpeg could not read the film %s: %s" % (video.name, cp.stderr.decode("utf-8", "replace")[-300:]))
    px = np.frombuffer(cp.stdout, dtype=np.uint8)
    per = MARKER_SIZE * MARKER_SIZE
    px = px[: (len(px) // per) * per].reshape(-1, per)
    return px.mean(axis=1) if len(px) else np.zeros(0)


def match_markers(expected: Sequence[int], on: Sequence[int], slack: int = MARKER_SLACK) -> Dict[str, Any]:
    """Pair expected marker frames with ON frames (exact first, then the nearest within `slack`)."""
    exp = sorted(set(int(e) for e in expected))
    onset = sorted(set(int(o) for o in on))
    free_on = set(onset)
    exact, near = [], []
    rest = []
    for e in exp:
        if e in free_on:
            free_on.discard(e)
            exact.append(e)
        else:
            rest.append(e)
    missing = []
    for e in rest:
        cand = sorted((abs(o - e), o) for o in free_on if abs(o - e) <= slack)
        if cand:
            d, o = cand[0]
            free_on.discard(o)
            near.append({"expected": e, "on": o, "offset": o - e})
        else:
            missing.append(e)
    return {"exact": exact, "near": near, "missing": missing, "extra": sorted(free_on),
            "max_offset": max([abs(n["offset"]) for n in near] or [0])}


def audio_lag(source: Path, film: Path, expected_ms: float = 0.0, seconds: float = AUDIO_SECONDS,
              sr: int = 16000) -> Dict[str, Any]:
    """How late the film's sound is against the source's (ms, positive = later), by cross-correlating the first
    `seconds` of both (high-passed, so the clicks lead). `expected_ms` is a deliberate delay (the film's offset)."""
    from scipy import signal
    from .audio import wav
    a = wav.load(source, sr=48000, mono=True, duration=seconds)
    b = wav.load(film, sr=48000, mono=True, duration=seconds + abs(expected_ms) / 1000.0 + 1.0)
    if len(a) < 4800 or len(b) < 4800 or float(np.abs(a).max()) < 1e-6 or float(np.abs(b).max()) < 1e-6:
        return {"lag_ms": None, "corr": 0.0, "note": "no usable sound in the source or the film"}
    q = 48000 // sr
    sos = signal.butter(2, 300.0, "hp", fs=48000, output="sos")
    a = signal.resample_poly(signal.sosfilt(sos, a), 1, q)
    b = signal.resample_poly(signal.sosfilt(sos, b), 1, q)
    a = a - a.mean()
    b = b - b.mean()
    cc = signal.correlate(b, a, mode="full", method="fft")
    lags = np.arange(-(len(a) - 1), len(b))
    limit = int((abs(expected_ms) / 1000.0 + 1.0) * sr)
    sel = np.abs(lags) <= limit
    ccs, lg = cc[sel], lags[sel]
    k = int(np.argmax(ccs))
    off = 0.0
    if 0 < k < len(ccs) - 1:
        y0, y1, y2 = ccs[k - 1], ccs[k], ccs[k + 1]
        den = y0 - 2 * y1 + y2
        off = 0.5 * (y0 - y2) / den if den != 0 else 0.0
    na, nb = float(np.sqrt((a ** 2).sum())), float(np.sqrt((b ** 2).sum()))
    # normalise by the overlapping part of b: the film is longer than the source window
    lagi = int(lg[k])
    lo, hi = max(0, lagi), min(len(b), len(a) + lagi)
    nb_o = float(np.sqrt((b[lo:hi] ** 2).sum())) if hi > lo else nb
    corr = float(ccs[k] / (na * nb_o + 1e-12))
    lag_ms = (lagi + off) / sr * 1000.0 - expected_ms
    return {"lag_ms": round(lag_ms, 1), "corr": round(corr, 3), "note": ""}


def smoothness(video: Path, band: Sequence[int], max_shift: int = 40) -> Dict[str, Any]:
    """Frame-to-frame horizontal shift of a band (x, y, w, h) of the film by cross-correlating its column profiles.
    Stalls: 0 px while the median speed is over 1 px; jumps: the shift changes by more than 3 px."""
    import subprocess
    x, y, w, h = [int(v) for v in band]
    pr = ff.probe(video)
    if x < 0 or y < 0 or w < 8 or h < 1 or x + w > int(pr["width"]) or y + h > int(pr["height"]):
        raise ShowtimeError("--band %s lies outside the %dx%d film" % (",".join(str(v) for v in band), pr["width"], pr["height"]),
                            hint="--band x,y,w,h in film pixels (w at least 8)")
    args = [ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(video), "-an",
            "-vf", "crop=%d:%d:%d:%d,format=gray" % (w, h, x, y), "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    rows, size = [], w * h
    try:                                   # one frame at a time: only its column profile is kept
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            rows.append(np.frombuffer(buf, dtype=np.uint8).reshape(h, w).astype(np.float64).mean(axis=0))
        err = proc.stderr.read()
    finally:
        proc.stdout.close()
        proc.stderr.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    if not rows and proc.returncode:
        raise ShowtimeError("ffmpeg could not read the film: %s" % err.decode("utf-8", "replace")[-300:])
    prof = np.array(rows) if rows else np.zeros((0, w))
    return smoothness_of_profiles(prof, max_shift)


def _shift(a: np.ndarray, b: np.ndarray, max_shift: int) -> Optional[float]:
    """Horizontal shift (px, sub-pixel) that moves profile a onto b; None when a profile is flat."""
    a = a - a.mean()
    b = b - b.mean()
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-6 or nb < 1e-6:
        return None
    w = len(a)
    m = min(max_shift, w // 2)
    best, scores = None, {}
    for s in range(-m, m + 1):
        if s >= 0:
            u, v = a[: w - s], b[s:]
        else:
            u, v = a[-s:], b[: w + s]
        if len(u) < 4:
            continue
        scores[s] = float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-12))
    if not scores:
        return None
    best = max(scores, key=lambda k: scores[k])
    if best - 1 in scores and best + 1 in scores:
        y0, y1, y2 = scores[best - 1], scores[best], scores[best + 1]
        den = y0 - 2 * y1 + y2
        return best + (0.5 * (y0 - y2) / den if den != 0 else 0.0)
    return float(best)


def smoothness_of_profiles(prof: np.ndarray, max_shift: int = 40) -> Dict[str, Any]:
    """The stall/jump report for per-frame column profiles (frames x width)."""
    shifts: List[Optional[float]] = [_shift(prof[i - 1], prof[i], max_shift) for i in range(1, len(prof))]
    vals = [abs(s) for s in shifts if s is not None]
    med = float(np.median(vals)) if vals else 0.0
    stalls, jumps = [], []
    if med > 1.0:
        for i, s in enumerate(shifts, start=1):
            if s is not None and abs(s) < 0.25:
                stalls.append(i)
        prev = None
        for i, s in enumerate(shifts, start=1):          # a change into or out of a stalled frame counts as the stall
            if s is not None and prev is not None and abs(s - prev) > 3.0 and abs(s) >= 0.25 and abs(prev) >= 0.25:
                jumps.append(i)
            if s is not None:
                prev = s
    return {"frames": len(prof), "median_px": round(med, 2), "stalls": len(stalls), "jumps": len(jumps),
            "stall_frames": stalls[:50], "jump_frames": jumps[:50]}


def project_config(job: Path) -> Dict[str, Any]:
    """The "xray" block of the job's project showtime.json ({"marker", "offset_frames", "band": [y0, y1]}):
    <job>/project/showtime.json first, then any */showtime.json under the job. {} when there is none."""
    job = Path(job)
    cands = [job / "project" / "showtime.json"]
    try:
        cands += sorted(p for p in job.glob("*/showtime.json") if p not in cands)
        cands += sorted(p for p in job.glob("*/*/showtime.json") if p not in cands and "node_modules" not in p.parts)[:20]
    except OSError:
        pass
    for p in cands:
        if p.is_file():
            d = read_json(p, {})
            x = d.get("xray") if isinstance(d, dict) else None
            if isinstance(x, dict):
                return x
    return {}


def find_film(job: Path) -> Optional[Path]:
    from .job import ledger
    try:
        data = ledger.load(job)
        lo = ledger.last_output(job, data)
        if lo:
            return Path(lo[0])
    except Exception:  # noqa: BLE001
        pass
    for pat in ("final*.mp4", "*.mp4"):
        hits = sorted(job.glob(pat), key=lambda p: p.stat().st_mtime, reverse=True)
        if hits:
            return hits[0]
    return None


def find_source(job: Path, doc: Dict[str, Any], given: Optional[Any] = None) -> Optional[Path]:
    if given:
        p = Path(given).expanduser()
        return p if p.is_file() else None
    side = job / "xray" / "source.path"
    if side.is_file():
        p = Path(side.read_text(encoding="utf-8").strip())
        if p.is_file():
            return p
    name = (doc.get("source") or {}).get("file")
    name = Path(str(name).replace("\\", "/")).name if name else ""      # a bare file name: never a path out of the job
    if name and name not in (".", ".."):
        root = job.resolve()
        for p in list(job.rglob(glob.escape(name)))[:5]:
            try:
                inside = p.is_file() and p.resolve().is_relative_to(root) if hasattr(Path, "is_relative_to") else p.is_file()
            except (OSError, ValueError):
                inside = False
            if inside:
                return p
    return None


def verify(job: Any, video: Optional[Any] = None, source: Optional[Any] = None, offset_frames: Optional[int] = None,
           band: Optional[Sequence[int]] = None, skip: Optional[Sequence[int]] = None) -> Dict[str, Any]:
    """Read a film back against <job>/xray/xray.json. Returns the `xray` receipt section (also saved as
    <job>/xray/verify.json), with `findings` ([(severity, rule, message)]) for qa."""
    job = Path(job)
    doc = read_json(job / "xray" / "xray.json", None)
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ShowtimeError("%s has no xray/xray.json" % job.name, hint="run `showtime xray analyze <clip> --job %s` first" % job.name)
    cfg = project_config(job)
    if offset_frames is None:
        try:
            offset_frames = int(cfg.get("offset_frames") or 0)
        except (TypeError, ValueError):
            offset_frames = 0
    film = Path(video) if video else find_film(job)
    if film is None or not Path(film).is_file():
        raise ShowtimeError("no film to verify in %s" % job.name, hint="pass the rendered file: --video final.mp4")
    film = Path(film)
    pr = ff.probe(film)
    W, H = int(pr["width"]), int(pr["height"])
    ffps = float(pr.get("fps") or 0)
    levels = _read_marker_levels(film, W, H)
    nfr = len(levels)
    on = [int(i) for i in np.where(levels > 128)[0]]
    if skip is None:                       # --skip, else the project's "xray".skip: events that are not the object's
        sk = cfg.get("skip")
        skip = list(sk) if isinstance(sk, (list, tuple)) else []
    skipset = set()
    bad_skip = []
    known = set(int(e["i"]) for e in doc["events"])
    for v in skip:
        if isinstance(v, bool) or not isinstance(v, int):
            bad_skip.append(repr(v))
        elif v not in known:
            bad_skip.append(str(v))
        else:
            skipset.add(v)
    src_fps = float((doc.get("source") or {}).get("fps") or 0)
    retime = bool(ffps and src_fps and abs(ffps - src_fps) > 0.01)     # a 29.97 clip in a 30 fps film: frames from times
    expected = [(frame_of(float(e["t"]), ffps) if retime else int(e["frame"])) + int(offset_frames)
                for e in doc["events"] if int(e["i"]) not in skipset]
    inside = [e for e in expected if 0 <= e < nfr]
    marker = bool(on) and len(on) < nfr       # a corner that is bright on every frame is a picture, not a marker
    m = match_markers(inside, on)
    res: Dict[str, Any] = {
        "events": len(inside), "on_frame": len(m["exact"]), "missing": m["missing"], "extra": m["extra"],
        "audio_lag_ms": None, "marker": marker, "off_by": m["near"], "max_offset": m["max_offset"],
        "outside_film": len(expected) - len(inside), "skipped": len(skipset), "film": film.name, "film_frames": nfr}
    findings: List[Tuple[str, str, str]] = []
    notes: List[str] = []
    if bad_skip:
        notes.append("WARN: skip entries ignored (not an event index of xray.json): %s" % ", ".join(bad_skip))
    if len(set(inside)) < len(inside):
        notes.append("%d event(s) share a film frame with another (frames %s): they count once on the film" % (
            len(inside) - len(set(inside)), sorted(set(f for f in inside if inside.count(f) > 1))[:6]))
    audio_unmatched = False
    if retime:
        notes.append("the film runs at %.4g fps, the clip at %.4g: expected film frames are floor(t * film fps) + offset" % (ffps, src_fps))
    src = find_source(job, doc, source)
    if src is None:
        notes.append("the source clip was not found (pass --source): audio not checked")
    elif not pr.get("has_audio"):
        notes.append("the film has no audio: audio not checked")
    else:
        al = audio_lag(src, film, expected_ms=1000.0 * offset_frames / (ffps or src_fps or 30.0))
        res["audio_lag_ms"] = al["lag_ms"]
        res["audio_corr"] = al["corr"]
        if al["lag_ms"] is None or al["corr"] < 0.05:
            res["audio_lag_ms"] = None
            notes.append("the film's sound does not match the clip's well enough to measure a lag (corr %.2f)" % al["corr"])
            audio_unmatched = True
    if not band and isinstance(cfg.get("band"), (list, tuple)) and len(cfg["band"]) == 2:
        try:
            y0, y1 = int(cfg["band"][0]), int(cfg["band"][1])
            band = [0, y0, W, y1 - y0]               # the scrolling band's rows, full width
        except (TypeError, ValueError):
            band = None
    res["offset_frames"] = int(offset_frames)
    if band:
        res["smoothness"] = smoothness(film, band)
    if not marker:
        findings.append(("WARN", "xray_unverified", "the film has no sync marker in its bottom-right corner, so the events are unverified"))
    else:
        if m["missing"] or m["extra"]:
            findings.append(("FAIL", "xray_sync", "%d missing marker frame(s) %s, %d extra %s" % (
                len(m["missing"]), m["missing"][:6], len(m["extra"]), m["extra"][:6])))
        if res["audio_lag_ms"] is not None and abs(res["audio_lag_ms"]) > LAG_LIMIT_MS:
            findings.append(("FAIL", "xray_sync", "the film's audio is %.1f ms from the original (limit %g ms)" % (res["audio_lag_ms"], LAG_LIMIT_MS)))
        if audio_unmatched:
            findings.append(("WARN", "xray_audio", "the film's sound could not be matched to the clip's"))
        if m["near"]:
            findings.append(("WARN", "xray_sync_off", "%d event(s) are off their frame by up to %d frame(s)" % (len(m["near"]), m["max_offset"])))
    sm = res.get("smoothness")
    if sm and (sm["stalls"] or sm["jumps"]):
        findings.append(("WARN", "xray_choppy", "the scrolling band has %d stall(s) and %d jump(s) (median %.1f px/frame)" % (
            sm["stalls"], sm["jumps"], sm["median_px"])))
    res["status"] = "FAIL" if any(f[0] == "FAIL" for f in findings) else "WARN" if findings else "PASS"
    res["line"] = end_card_line(res)
    res["notes"] = notes
    res["findings"] = [{"severity": s, "rule": r, "message": t} for s, r, t in findings]
    write_json(job / "xray" / "verify.json", res)
    return res


def end_card_line(res: Dict[str, Any]) -> str:
    """The one line for an end card."""
    if not res.get("marker"):
        return "%d events measured from the clip (sync not verified: no marker in the film)" % res.get("events", 0)
    lag = res.get("audio_lag_ms")
    tail = "audio %s ms from the original" % ("%.0f" % abs(lag) if abs(lag) >= 10 else "%.1f" % abs(lag)) if lag is not None \
        else "audio not compared"
    return "%d of %d events on their frame · %s" % (res["on_frame"], res["events"], tail)


RECEIPT_KEYS = ("events", "on_frame", "missing", "extra", "audio_lag_ms", "marker", "off_by", "max_offset", "outside_film", "skipped",
                "film", "smoothness", "status", "line", "notes")


def receipt_section(job: Path) -> Optional[Dict[str, Any]]:
    """The `xray` section of the job receipt, from <job>/xray/verify.json (None when verify has not run)."""
    d = read_json(Path(job) / "xray" / "verify.json", None)
    if not isinstance(d, dict) or "events" not in d:
        return None
    sec = {k: d[k] for k in RECEIPT_KEYS if k in d}
    cfg = project_config(job)
    if str(cfg.get("credit") or "").strip():
        sec["credit"] = str(cfg["credit"]).strip()
    elif cfg.get("own") is True:
        sec["own"] = True
    return sec


def add_to_receipt(job: Path) -> bool:
    """Rewrite the job's receipt (receipt.json carries the `xray` section). Quiet: a receipt never fails verify."""
    try:
        from .job import receipt
        receipt.write(Path(job))
        return True
    except Exception:  # noqa: BLE001
        return False

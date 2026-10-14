"""X-ray: measure what happened in a filmed clip (sound onsets, camera motion), then check a finished film against it.

`analyze` writes <job>/xray/xray.json (schema showtime.xray/1, the contract in references/workflows/xray.md) and
<job>/xray/check.jpg; the source may be a recording with no picture (a WAV: the page draws the picture side).
`import_events` writes the same file from a data stream (event times in a CSV or JSON, mapped to film time).
`verify` reads a rendered film back: the sync marker in its corner, the audio against the source, and (optionally)
the smoothness of a scrolling band.

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
import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

import numpy as np

from . import ff
from .common import ShowtimeError, log, read_json, warn, write_json

SCHEMA = "showtime.xray/1"
SR = 48000
DEFAULT_FPS = 30             # the frame grid of a recording with no picture (the film's fps when it is not 30: --fps)
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

def _fps_value(fps: float) -> Any:
    return int(fps) if float(fps) == int(fps) else round(float(fps), 6)


def _check_fps(fps: Optional[float]) -> None:
    if fps is not None and not 1.0 <= float(fps) <= 240.0:
        raise ShowtimeError("--fps must be 1..240 (got %g)" % fps)


def check_source(clip: Any, fps: Optional[float] = None, track: bool = False) -> None:
    """The refusals of _source_info and analyze, without reading the whole file: --fps on a video at another rate,
    --track on a recording with no picture."""
    _check_fps(fps)
    clip = Path(clip)
    pr = ff.probe(clip)
    if pr.get("has_video"):
        vfps = float(pr.get("fps") or 30.0)
        if fps is not None and abs(float(fps) - vfps) > 0.01:
            raise ShowtimeError("%s is a video at %g fps; --fps is only for a recording with no picture" % (clip.name, vfps),
                                hint="leave out --fps: the events land on the clip's own frames")
    elif track:
        raise ShowtimeError("%s has no picture to track" % clip.name, hint="leave out --track: the page draws the picture side")


def _source_info(clip: Path, fps: Optional[float] = None) -> Dict[str, Any]:
    """The `source` block of xray.json. A recording with no picture (a WAV, a sonified data stream) is a source too:
    its events land on a frame grid of `fps` (default 30), it has no width or height, and `audio_only` says so."""
    _check_fps(fps)
    pr = ff.probe(clip)
    if not pr.get("has_video"):
        info = {"file": clip.name, "sha256": _sha256(clip), "fps": _fps_value(fps or DEFAULT_FPS),
                "duration": round(float(pr.get("duration") or 0.0), 3), "width": 0, "height": 0, "audio_only": True,
                "has_audio": bool(pr.get("has_audio"))}
        return info
    vfps = pr.get("fps") or 30.0
    if fps is not None and abs(float(fps) - float(vfps)) > 0.01:
        raise ShowtimeError("%s is a video at %g fps; --fps is only for a recording with no picture" % (clip.name, float(vfps)),
                            hint="leave out --fps: the events land on the clip's own frames")
    vfr = _is_vfr(pr)
    info = {"file": clip.name, "sha256": _sha256(clip), "fps": _fps_value(vfps),
            "duration": round(float(pr.get("duration") or pr.get("video_duration") or 0.0), 3),
            "width": int(pr.get("width") or 0), "height": int(pr.get("height") or 0), "has_audio": bool(pr.get("has_audio"))}
    if vfr:
        info["vfr"] = True
    return info


def validate_clip(clip: Any) -> Path:
    """Refuse a clip that cannot be analyzed (missing, no sound) before anything is created for it. A recording with
    no picture is fine: the events come from the sound, and the page draws the picture side."""
    clip = Path(clip)
    if not clip.is_file():
        raise ShowtimeError("clip not found: %s" % clip, hint="pass the video you filmed, or the recording (a WAV)")
    pr = ff.probe(clip)
    if not pr.get("has_audio"):
        raise ShowtimeError("%s has no sound to analyze" % clip.name,
                            hint="x-ray reads the events from the sound; events from a data stream: showtime xray import")
    return clip


def _is_vfr(pr: Dict[str, Any]) -> bool:
    """A variable-frame-rate clip (a phone video): r_frame_rate and avg_frame_rate differ by more than 1 %."""
    r, a = pr.get("r_fps"), pr.get("avg_fps")
    return bool(r and a and abs(r - a) > 0.01 * max(r, a))


VFR_WARNING = ("the clip is variable frame rate (a phone video): event frames are counted at one rate and may drift. "
               "Run `showtime footage trim <clip> --webm` (constant 30 fps) and x-ray that file")


def analyze(clip: Any, out_dir: Any, *, t_from: float = 0.0, t_to: Optional[float] = None, min_gap: Optional[float] = None,
            sensitivity: float = 0.5, track: Optional[Dict[str, Any]] = None, engine: str = "auto",
            fps: Optional[float] = None) -> Dict[str, Any]:
    """Write <out_dir>/xray.json and check.jpg for a clip, or a recording with no picture (`fps`: its frame grid,
    default 30). `track`: {"region": [[x, y]...], "ref_time": T, "masks": [[[x, y]...]...]} to also track the
    object. Returns the xray.json dict."""
    from .audio import wav
    clip = Path(clip)
    if not clip.is_file():
        raise ShowtimeError("clip not found: %s" % clip, hint="pass the video you filmed, or the recording (a WAV)")
    out = Path(out_dir)
    src = _source_info(clip, fps)
    if src.get("vfr"):
        warn(VFR_WARNING)
    if not src.pop("has_audio"):
        raise ShowtimeError("%s has no sound to analyze" % clip.name, hint="x-ray reads the hits from the clip's audio")
    if track and src.get("audio_only"):
        raise ShowtimeError("%s has no picture to track" % clip.name, hint="leave out --track: the page draws the picture side")
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


# ------------------------------------------------------------------ import (events from a data stream)

TIME_KEYS = ("t", "time", "t_data", "time_s", "t_s", "seconds", "sec")
RESERVED = ("i", "t", "frame", "strength", "band", "t_data")
PAGE_TEXT_KEYS = ("kind", "ch")           # the live page reads these as text
PAGE_LIST_KEYS = ("notes", "pitches")     # ... and these as lists it built itself: a data column of that name is renamed
MAX_EVENTS_BYTES = 50 * 1024 * 1024       # an events file above this is refused, as is one with more events than ...
MAX_EVENTS = 100000
MAX_FILM_SECONDS = 24 * 3600              # no data-only film (no --source) is longer than this
MAX_LINES = 2 * 100000                    # every line read of a CSV (blank and comment lines too) counts against this
MAX_VALUES = 64 * 100000                  # commas in a JSON file (a bound on every value in it) before it is parsed
MAX_CONTAINERS = 8 * 100000               # "{" and "[" in a JSON file (each is a dict or list in memory) before it is parsed
MAX_DIGITS = 1000                         # a run of digits longer than this is not a number a film can hold
MAX_DEPTH = 32                            # JSON nesting an event may carry
MAX_FRAME = 10 ** 9                       # a film time past this many frames is a mistake in the time map, not a film


def _leaf(name: Any) -> str:
    """A file name without any folder (either slash), for text that lands on a page that gets shared."""
    return str(name).replace("\\", "/").rsplit("/", 1)[-1]


BIG = "has a number too large to hold (an infinity or a huge integer)"


def _json_problem(v: Any) -> Optional[str]:
    """Why a parsed JSON value cannot be held (an infinity, or nesting too deep), else None. Iterative."""
    stack = [(v, 0)]
    while stack:
        x, d = stack.pop()
        if isinstance(x, float):
            if not math.isfinite(x):
                return BIG
        elif isinstance(x, int) and not isinstance(x, bool):
            if abs(x) > 10 ** 308:
                return BIG
        elif isinstance(x, (dict, list)):
            if d >= MAX_DEPTH:
                return "is nested more than %d levels deep" % MAX_DEPTH
            stack.extend((y, d + 1) for y in (x.values() if isinstance(x, dict) else x))
    return None


def parse_time_map(text: Optional[str]) -> Dict[str, float]:
    """"SLOW,T0" or "slow=SLOW,t0=T0" (either part may be left out) -> {"slow", "t0"}: film t = (t_data - T0) x SLOW."""
    tm = {"slow": 1.0, "t0": 0.0}
    if text is None or not str(text).strip():
        return tm
    parts = [v.strip() for v in str(text).replace(";", ",").split(",")]      # an omitted part ("", ",5") keeps its default
    if len(parts) > 2:
        raise ShowtimeError("--time-map is SLOW,T0 (got %r)" % text, hint="e.g. --time-map 100,-0.14: 100 film seconds per "
                                                                         "data second, data time -0.14 s at film time 0")
    given = set()
    for k, part in enumerate(parts):
        if not part:
            continue
        key, _, val = part.rpartition("=")
        key = key.strip().lower() or ("slow", "t0")[k]
        if key not in tm:
            raise ShowtimeError("--time-map knows slow and t0 (got %r)" % key, hint="--time-map slow=100,t0=-0.14")
        if key in given:
            raise ShowtimeError("--time-map sets %s twice (got %r)" % (key, text), hint="give each of slow and t0 once: --time-map slow=100,t0=-0.14")
        given.add(key)
        try:
            tm[key] = float(val)
        except ValueError:
            raise ShowtimeError("--time-map %s=%r is not a number" % (key, val))
    if not (tm["slow"] > 0 and math.isfinite(tm["slow"])):
        raise ShowtimeError("--time-map slow must be a number above 0 (got %g)" % tm["slow"])
    if not math.isfinite(tm["t0"]):
        raise ShowtimeError("--time-map t0 must be a number (got %g)" % tm["t0"])
    return tm


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def read_event_rows(path: Path) -> Tuple[List[Dict[str, Any]], List[str]]:
    """(rows as dicts, column names in order) of a CSV (a header row; without one the first column is the time) or a
    JSON file (a list of times, a list of objects, or {"events": [...]})."""
    import csv
    try:
        size = path.stat().st_size
        if size > MAX_EVENTS_BYTES:
            raise ShowtimeError("%s is %.0f MB; an events file may be up to %d MB" % (path.name, size / 1048576.0, MAX_EVENTS_BYTES // 1048576),
                                hint="keep the events you want in the film (peaks, not the whole signal)")
        with open(path, "rb") as raw:                          # a NUL byte: csv reads it on some Pythons and drops the row on others
            at = 0
            while True:
                chunk = raw.read(1048576)
                if not chunk:
                    break
                k = chunk.find(b"\x00")
                if k >= 0:
                    raise ShowtimeError("%s has a NUL byte (at byte %d)" % (path.name, at + k),
                                        hint="save it as plain UTF-8 text (a file saved as UTF-16 has one in every character)")
                at += len(chunk)
        with open(path, encoding="utf-8-sig") as f:
            first = f.read(4096)
            as_json = path.suffix.lower() == ".json" or first.lstrip()[:1] in ("[", "{")
            f.seek(0)
            if as_json:
                return _json_rows(path, f.read())
            return _csv_rows(path, f, csv)
    except (OSError, UnicodeDecodeError) as e:
        raise ShowtimeError("cannot read %s: %s" % (path.name, e))
    except csv.Error as e:
        raise ShowtimeError("cannot read %s as a CSV file: %s" % (path.name, e),
                            hint="a cell may hold up to %d characters and no NUL byte; keep the events, not whole signals" % csv.field_size_limit())


def _json_rows(path: Path, text: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    if text.count(",") > MAX_VALUES:                          # bounds every value (numbers, nulls, strings, lists) before parsing
        raise ShowtimeError("%s holds too many values (over %d)" % (path.name, MAX_VALUES), hint="keep the peaks, not every sample")

    # a dict or list costs far more memory than a number: bound them on their own, so a small file of "{},{},..." is
    # refused before it is parsed, while a legitimate file (100,000 events, each with arrays of numbers) is not
    if text.count("{") + text.count("[") > MAX_CONTAINERS:
        raise ShowtimeError("%s holds too many lists or objects (over %d)" % (path.name, MAX_CONTAINERS), hint="keep the peaks, not every sample")
    if re.search(r"\d{%d,}" % MAX_DIGITS, text):                # before json.loads: older Pythons parse a huge integer in quadratic time
        raise ShowtimeError("%s %s" % (path.name, BIG), hint="remove or fix that value")

    def _bad(tok: str) -> Any:
        raise ValueError("%s is not allowed in JSON" % tok)
    try:
        data = json.loads(text, parse_constant=_bad)
    except RecursionError:
        raise ShowtimeError("%s is nested too deeply" % path.name)
    except ValueError as e:
        if "digits" in str(e) and "limit" in str(e):         # Python 3.10.7+ refuses a huge integer here; older ones parse it
            raise ShowtimeError("%s %s" % (path.name, BIG), hint="remove or fix that value")
        raise ShowtimeError("%s is not valid JSON: %s" % (path.name, e))
    why = _json_problem(data)
    if why:
        raise ShowtimeError("%s %s" % (path.name, why), hint="remove or fix that value")
    if isinstance(data, dict):
        data = data.get("events")
    if not isinstance(data, list):
        raise ShowtimeError("%s holds no list of events" % path.name, hint='a list of times, of objects with "t", or {"events": [...]}')
    if len(data) > MAX_EVENTS:                                # top-level events only
        raise ShowtimeError("%s has %d events; up to %d events are taken" % (path.name, len(data), MAX_EVENTS), hint="keep the peaks, not every sample")
    rows: List[Dict[str, Any]] = []
    cols: List[str] = []
    seen = set()
    for v in data:
        r = dict(v) if isinstance(v, dict) else {"t": v}
        rows.append(r)
        for k in r:
            if k not in seen:
                seen.add(k)
                cols.append(k)
    return rows, cols


def _csv_rows(path: Path, f: Any, csv: Any) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Read a CSV line by line: every line read counts against MAX_LINES, every kept row against MAX_EVENTS."""
    nlines = [0]

    def lines() -> Iterator[str]:
        for ln in f:
            nlines[0] += 1
            if nlines[0] > MAX_LINES:
                raise ShowtimeError("%s has more than %d lines" % (path.name, MAX_LINES), hint="keep the peaks, not every sample")
            yield ln
    kept: List[List[str]] = []
    limit = MAX_EVENTS + 1                                    # with a header row; one less without (decided at the first row)
    for ln in csv.reader(lines()):
        if ln and any(c.strip() for c in ln) and not ln[0].lstrip().startswith("#"):
            kept.append(ln)
            if len(kept) == 1:
                for c in ln:                                  # a number too big to hold is an error, not a reason to call the row a header
                    try:
                        big = math.isinf(float(c.strip())) and re.fullmatch(r"[+-]?[\d.]+(?:[eE][+-]?\d+)?", c.strip()) is not None
                    except ValueError:
                        big = False
                    if big:
                        raise ShowtimeError("%s %s" % (path.name, BIG), hint="remove or fix that value")
            if len(kept) == 1 and all(_num(c.strip()) is not None for c in ln):
                limit = MAX_EVENTS                            # no header: the first row is an event
            if len(kept) > limit:                             # stop reading as soon as the cap is passed
                raise ShowtimeError("%s has more than %d events" % (path.name, MAX_EVENTS), hint="keep the peaks, not every sample")
    if not kept:
        return [], []
    head = [c.strip() for c in kept[0]]
    if all(_num(c) is not None for c in head):            # no header: the first column is the time
        head = ["t"] + ["c%d" % k for k in range(1, len(head))]
        body = kept
    else:
        body = kept[1:]
    return [dict(zip(head, [c.strip() for c in ln])) for ln in body], head


def import_events(events_file: Any, out_dir: Any, **kw: Any) -> Dict[str, Any]:
    """Write <out_dir>/xray.json (detector.engine "data") and check.jpg from event times measured in a data stream
    (the options of build_import). Returns the xray.json dict."""
    doc, x = build_import(events_file, **kw)
    write_import(doc, x, events_file, out_dir, kw.get("source"))
    return doc


def write_import(doc: Dict[str, Any], x: np.ndarray, events_file: Any, out_dir: Any, source: Optional[Any] = None) -> None:
    """Write what build_import returned: xray.json, source.path (with a source) and check.jpg."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    try:
        json.dumps(doc, allow_nan=False)                    # no bare NaN or Infinity may reach xray.json
    except (ValueError, RecursionError) as e:
        raise ShowtimeError("the events cannot be written as JSON: %s" % e)
    write_json(out / "xray.json", doc)
    if source is not None:
        try:
            (out / "source.path").write_text(str(Path(source).resolve()), encoding="utf-8")   # local only: for verify
        except OSError:
            pass
    check_sheet(Path(source) if source is not None else Path(events_file), doc, x, 0.0, out / "check.jpg")


def build_import(events_file: Any, *, time_map: Optional[Dict[str, float]] = None, source: Optional[Any] = None,
                 fps: Optional[float] = None, duration: Optional[float] = None, column: Optional[str] = None,
                 strength: Optional[str] = None, note: Optional[str] = None) -> Tuple[Dict[str, Any], np.ndarray]:
    """(xray.json dict, the source's sound or an empty array) from event times measured in a data stream; writes
    nothing, so every refusal comes before a job or a folder exists. Film time t = (t_data - t0) x slow, frame =
    frame_of(t, fps). `source`: the clip or recording the film plays (its fps, duration and sha256; verify finds
    it), else `fps` (default 30) and `duration`."""
    from .audio import wav
    path = Path(events_file)
    if not path.is_file():
        raise ShowtimeError("events file not found: %s" % path, hint="a CSV with a time column, or a JSON list of times")
    tm = time_map or {"slow": 1.0, "t0": 0.0}
    _check_fps(fps)
    if duration is not None and not (0 < duration <= MAX_FILM_SECONDS):
        raise ShowtimeError("--duration must be above 0 and at most %d seconds (got %g)" % (MAX_FILM_SECONDS, duration))
    if source is not None and duration is not None:
        raise ShowtimeError("--duration is for an import without --source (the source has its own length)")
    rows, cols = read_event_rows(path)
    if not rows:
        raise ShowtimeError("%s has no events" % path.name)
    low = {c.lower(): c for c in cols}
    if column:
        if column not in cols:
            raise ShowtimeError("%s has no column %r (columns: %s)" % (path.name, column, ", ".join(cols)))
        tcol = column
    else:
        tcol = next((low[k] for k in TIME_KEYS if k in low), None)
        if tcol is None:
            raise ShowtimeError("%s has no time column (columns: %s)" % (path.name, ", ".join(cols)),
                                hint="name it with --column, or call it t or time")
    if strength and strength not in cols:
        raise ShowtimeError("%s has no column %r (columns: %s)" % (path.name, strength, ", ".join(cols)))
    times = []
    for n, r in enumerate(rows, start=1):
        v = _num(r.get(tcol))
        if v is None:
            raise ShowtimeError("%s, event %d: the time %r is not a number" % (path.name, n, r.get(tcol)))
        times.append(v)
    src: Dict[str, Any]
    x = np.zeros(0, dtype=np.float32)
    if source is not None:
        clip = Path(source)
        if not clip.is_file():
            raise ShowtimeError("--source not found: %s" % clip, hint="the clip or recording the film plays")
        src = _source_info(clip, fps)
        if src.pop("has_audio"):
            x = wav.load(clip, sr=SR, mono=True)
    else:
        src = {"file": None, "sha256": None, "fps": _fps_value(fps or DEFAULT_FPS),
               "duration": round(float(duration), 3) if duration else None, "width": 0, "height": 0}
    sfps = float(src["fps"])
    end = float(src["duration"]) if src.get("duration") else None
    sv: Optional[List[float]] = None
    if strength:
        sv = []
        for n, r in enumerate(rows, start=1):
            raw = r.get(strength)
            v = _num(raw)
            if v is None and raw is not None and str(raw).strip() != "":
                raise ShowtimeError("%s, event %d: the %s value %r is not a number" % (path.name, n, strength, raw))
            sv.append(abs(v) if v is not None else 0.0)
        blank = sum(1 for r in rows if r.get(strength) is None or str(r.get(strength)).strip() == "")
        if blank:
            warn("%d event(s) have no %s value: drawn at strength 0" % (blank, strength))
    top = max(sv or [0.0]) or 1.0
    order = sorted(range(len(rows)), key=lambda k: times[k])
    events: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    for k in order:
        r, td = rows[k], times[k]
        t = (td - tm["t0"]) * tm["slow"]
        if not math.isfinite(t) or t * sfps > MAX_FRAME:
            raise ShowtimeError("%s, event at data time %g: film time is too large to hold with this time map" % (path.name, td),
                                hint="check --time-map: film t = (t_data - t0) x slow")
        if end is None and t > MAX_FILM_SECONDS:
            raise ShowtimeError("%s, event at data time %g: film time %g s is past %d s (24 h)" % (path.name, td, t, MAX_FILM_SECONDS),
                                hint="check --time-map: film t = (t_data - t0) x slow")
        t = round(t, 4)
        if t < 0:
            dropped.append({"t": t, "t_data": td, "why": "before film time 0 (data time %g is before t0 %g)" % (td, tm["t0"])})
            continue
        if end is not None and t >= end:
            dropped.append({"t": t, "t_data": td, "why": "after the end of the source (%.3f s)" % end})
            continue
        if sv is not None:
            st = round(sv[k] / top, 3)
        else:
            own = _num(r.get("strength"))
            st = round(min(1.0, max(0.0, own)), 3) if own is not None else 1.0
        band = r.get("band") if r.get("band") in ("low", "mid", "high") else (_band_of(x, int(t * 1000), SR) if len(x) else "mid")
        e = {"i": len(events), "t": t, "frame": frame_of(t, sfps), "strength": st, "band": band, "t_data": td}
        for c, v in r.items():
            if c == tcol or c in RESERVED or v is None or v == "":
                continue
            nv = _num(v)
            val: Any = (int(nv) if nv.is_integer() and isinstance(v, int) else nv) if nv is not None else v
            if isinstance(v, float) and nv is None:
                continue                                    # a NaN or an infinity: not data, and not valid JSON
            if c in PAGE_TEXT_KEYS:
                if isinstance(v, (dict, list)):
                    c = c + "_data"
                else:
                    val = str(v)
            elif c in PAGE_LIST_KEYS:
                c = c + "_data"
            e[c] = val
        events.append(e)
    if not events:
        raise ShowtimeError("none of the %d events of %s lands inside the film" % (len(rows), path.name),
                            hint="check --time-map: film t = (t_data - t0) x slow must be 0 or more%s" % (
                                " and under the source's %.3f s" % end if end is not None else ""))
    frames = [e["frame"] for e in events]
    if len(set(frames)) < len(frames):
        warn("%d event(s) share a film frame with another: raise the time map's slow, or --fps" % (len(frames) - len(set(frames))))
    auto = "written from %s (column %s, %d rows), not from the sound: film time = (t - (%g s)) x %g" % (
        _leaf(path.name), tcol, len(rows), tm["t0"], tm["slow"])
    doc: Dict[str, Any] = {
        "schema": SCHEMA, "source": src,
        "detector": {"engine": "data", "min_gap": None, "sensitivity": None, "from": 0.0, "to": None,
                     "note": (note or "").strip() or auto, "time_map": {"slow": tm["slow"], "t0": tm["t0"]},
                     "input": {"file": _leaf(path.name), "sha256": _sha256(path), "column": tcol, "rows": len(rows)}},
        "events": events, "dropped": dropped, "track": None}
    return doc, x


def check_sheet(clip: Path, doc: Dict[str, Any], x: np.ndarray, t0: float, dest: Path) -> Path:
    """check.jpg: the waveform with a numbered tick per event (dropped ones grey) and, with a track, the region on 6 frames."""
    from PIL import Image, ImageDraw
    W, H = 1800, 360
    img = Image.new("RGB", (W, H), (18, 20, 26))
    d = ImageDraw.Draw(img)
    last = max([float(e["t"]) for e in doc["events"]] or [0.0])
    dur = float(doc["source"].get("duration") or 0.0) or max(t0 + len(x) / SR, last + 0.5)
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
    for s in range(0, int(dur) + 1, max(1, int(dur) // 600 + 1)):
        d.line([(px(s), bot + 2), (px(s), bot + 8)], fill=(120, 120, 130))
        d.text((px(s) + 2, bot + 10), "%ds" % s, fill=(150, 150, 160))
    for dr in doc.get("dropped") or []:
        d.line([(px(dr["t"]), top), (px(dr["t"]), bot)], fill=(90, 90, 96))
    for e in doc["events"]:
        xx = px(e["t"])
        d.line([(xx, top - 8), (xx, bot)], fill=(255, 90, 60), width=1)
        d.text((xx + 2, 8 + (e["i"] % 2) * 12), str(e["i"]), fill=(255, 180, 160))
    det = doc["detector"]
    how = ("from data, time map x%g from %g s" % (det["time_map"]["slow"], det["time_map"]["t0"]) if det.get("engine") == "data"
           else "min_gap %.3g  sensitivity %.3g" % (det["min_gap"], det["sensitivity"]))
    d.text((left, H - 14), "%s  %d events (red), %d dropped (grey)  %s" % (
        doc["source"].get("file") or "no sound", len(doc["events"]), len(doc.get("dropped") or []), how), fill=(200, 200, 210))
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

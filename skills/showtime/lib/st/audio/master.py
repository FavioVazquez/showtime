"""Mastering: exact loudness normalisation with a true-peak limiter.

Default engine "st" (numpy): optional tone/glue chain, then gain -> look-ahead
true-peak limiter -> re-measure, iterated until integrated loudness is within
0.05 LU of the target and the true peak is at or below the ceiling. It is
offline and non-causal, so the limiter needs no latency compensation.

Engine "loudnorm": ffmpeg's two-pass loudnorm (linear mode) followed by
aresample=48000, for users who prefer the ffmpeg reference implementation.

Platform targets (integrated LUFS / true peak dBTP):
  web, youtube, social: -14 / -1   podcast: -16 / -1   broadcast: -23 / -1
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
from scipy import signal
from scipy.ndimage import minimum_filter1d, uniform_filter1d

from .. import ff
from ..common import ShowtimeError, warn
from . import SR, dsp, meter, wav

TARGETS = {
    "web": (-14.0, -1.0), "youtube": (-14.0, -1.0), "social": (-14.0, -1.0), "tiktok": (-14.0, -1.0),
    "reels": (-14.0, -1.0), "x": (-14.0, -1.0), "linkedin": (-14.0, -1.0), "podcast": (-16.0, -1.0),
    "apple-podcasts": (-16.0, -1.0), "broadcast": (-23.0, -1.0), "atsc": (-24.0, -2.0),
    "music-bed": (-18.0, -1.0), "preview": (-16.0, -1.5),
}

PRESETS = {
    # (mode, fc, q, gain_db) biquads, then compressor settings (or None)
    "mix": ([("hp", 20.0, 0.707, 0.0)], None),
    "music": ([("hp", 25.0, 0.707, 0.0), ("lowshelf", 90.0, 0.707, 0.8), ("highshelf", 10000.0, 0.707, 1.2)],
              dict(threshold_db=-14.0, ratio=2.0, attack=0.025, release=0.2, knee_db=6.0)),
    "voice": ([("hp", 70.0, 0.707, 0.0), ("peak", 250.0, 1.2, -2.0), ("peak", 3000.0, 1.0, 1.5)],
              dict(threshold_db=-20.0, ratio=3.0, attack=0.008, release=0.12, knee_db=6.0)),
    "none": ([], None),
}


def limit(x: np.ndarray, ceiling_db: float = -1.0, lookahead: float = 0.005, release: float = 0.12,
          oversample: int = 8, hop: int = 16) -> Tuple[np.ndarray, float]:
    """Offline look-ahead true-peak limiter. Returns (y, max_gain_reduction_db)."""
    s = dsp.to_stereo(x).astype(np.float64)
    N = len(s)
    if N == 0:
        return s.astype(np.float32), 0.0
    c = 10 ** (ceiling_db / 20.0)
    # per-sample inter-sample peak estimate (max over the oversampled neighbourhood)
    up = np.abs(signal.resample_poly(s, oversample, 1, axis=0)).max(axis=1)
    pk = np.maximum(up[: N * oversample].reshape(N, oversample).max(axis=1), np.abs(s).max(axis=1))
    if pk.max() <= c:
        return s.astype(np.float32), 0.0
    req = np.minimum(1.0, c / np.maximum(pk, 1e-12))
    L = max(1, int(lookahead * SR))
    m = minimum_filter1d(req, size=2 * L + 1, mode="nearest")
    g = uniform_filter1d(m, size=L | 1, mode="nearest")
    g = np.minimum(g, m)  # guard the edges of the averaging window
    # release: the gain may rise at most `rate` dB per hop (block-level loop, then interpolate)
    k = int(math.ceil(N / hop))
    gb = np.pad(g, (0, k * hop - N), constant_values=1.0).reshape(k, hop).min(axis=1)
    gdb = 20 * np.log10(np.maximum(gb, 1e-9))
    rate = 10.0 * hop / (release * SR)  # recover about 10 dB per `release` seconds
    out_db = np.empty(k)
    prev = gdb[0]
    for i, v in enumerate(gdb.tolist()):
        prev = v if v < prev else min(v, prev + rate)
        out_db[i] = prev
    centers = (np.arange(k) + 0.5) * hop
    curve = 10 ** (np.interp(np.arange(N), centers, out_db) / 20.0)
    gain = np.minimum(curve, g)
    y = s * gain[:, None]
    return y.astype(np.float32), float(-20 * math.log10(max(gain.min(), 1e-9)))


def normalize(x: np.ndarray, lufs: float = -14.0, tp: float = -1.0, margin: float = 0.1,
              max_iter: int = 6) -> Tuple[np.ndarray, Dict[str, float]]:
    """Gain + true-peak limit until integrated loudness == lufs (+-0.05) and TP <= tp."""
    x = dsp.to_stereo(x)
    I0 = meter.integrated(x)
    if not math.isfinite(I0):
        return x.copy(), {"input_lufs": None, "gain_db": 0.0, "limiting_db": 0.0, "output_lufs": None,
                          "output_tp": None, "note": "silent input: left unchanged"}
    g = lufs - I0
    y, red = x, 0.0
    I = I0
    for _ in range(max_iter):
        y, red = limit(x * 10 ** (g / 20.0), tp - margin)
        I = meter.integrated(y)
        err = lufs - I
        if abs(err) <= 0.05:
            break
        g += err
    tpv = meter.true_peak(y)
    if tpv > tp:
        y = y * 10 ** ((tp - margin - tpv) / 20.0)
        tpv = meter.true_peak(y)
        I = meter.integrated(y)
    info = {"input_lufs": round(I0, 2), "gain_db": round(g, 2), "limiting_db": round(red, 2),
            "output_lufs": round(I, 2), "output_tp": round(tpv, 2)}
    if red > 6:
        info["warning"] = ("%.1f dB of peak limiting was needed to reach %s LUFS; the material is very "
                           "peaky (consider less gain on transient-heavy tracks)" % (red, lufs))
    return y.astype(np.float32), info


def process(x: np.ndarray, preset: str = "mix", lufs: float = -14.0, tp: float = -1.0) -> Tuple[np.ndarray, Dict]:
    """Preset tone chain + glue compression + exact loudness normalisation."""
    if preset not in PRESETS:
        raise ShowtimeError("unknown master preset %r (choose: %s)" % (preset, ", ".join(PRESETS)))
    bands, comp = PRESETS[preset]
    y = dsp.to_stereo(x)
    if bands:
        y = dsp.eq(y, bands)
    if comp:
        y = dsp.compress(y, **comp)
    y, info = normalize(y, lufs, tp)
    info["preset"] = preset
    return y, info


def loudnorm_file(src, dst, lufs: float = -14.0, tp: float = -1.0, lra: float = 11.0) -> Dict:
    """ffmpeg two-pass loudnorm (linear) -> 48 kHz output."""
    m = ff.measure_loudness(src, lufs, tp, lra)
    if not math.isfinite(m.get("input_i", float("nan"))) or m["input_i"] < -69:
        raise ShowtimeError("%s is silent; nothing to normalise" % src)
    af = ff.loudnorm_filter(m, lufs, tp, lra) + ",aresample=%d" % SR
    d = Path(dst)
    ext = d.suffix.lower()
    codec = {".wav": ["-c:a", "pcm_s24le"], ".flac": ["-c:a", "flac"], ".m4a": ["-c:a", "aac", "-aac_coder", "fast", "-b:a", "256k"],
             ".mp3": ["-c:a", "libmp3lame", "-b:a", "192k"], ".opus": ["-c:a", "libopus", "-b:a", "160k"]}.get(ext)
    if codec is None:
        raise ShowtimeError("unsupported output format %r" % ext)
    ff.run_ffmpeg(["-i", str(src), "-vn", "-af", af, "-ar", str(SR)] + codec + [str(d)])
    return {"engine": "loudnorm", "measured": m}


LOSSY = (".m4a", ".aac", ".mp3", ".opus", ".ogg")


def save_to_target(dst, y: np.ndarray, lufs: float, tp: float, bits: int = 24, sr: int = SR) -> np.ndarray:
    """Write y; for lossy formats re-measure what the encoder produced and correct
    the gain (encoders low-pass and add overshoot). Returns the decoded result."""
    d = Path(dst)
    wav.save(d, y, sr=sr, bits=bits)
    if d.suffix.lower() not in LOSSY:
        return y
    out = wav.load(d)
    for _ in range(2):
        I, T = meter.integrated(out), meter.true_peak(out)
        err = lufs - I
        if abs(err) <= 0.15 and T <= tp:
            break
        y2 = y * 10 ** (err / 20.0)
        head = tp - max(0.0, T + err - tp) - 0.3
        y2, _ = limit(y2, min(tp - 0.1, head))
        wav.save(d, y2, sr=sr, bits=bits)
        out = wav.load(d)
        y = y2
    return out


def master_file(src, dst, lufs: float = -14.0, tp: float = -1.0, preset: str = "mix", engine: str = "st",
                bits: int = 24) -> Dict:
    """Master a file to `lufs` / `tp`; returns a report with before/after measurements."""
    src, dst = Path(src), Path(dst)
    if src.resolve() == dst.resolve():
        raise ShowtimeError("output would overwrite the input: %s" % dst, hint="choose a different -o path")
    x = wav.load(src)
    before = meter.measure(x)
    if engine == "loudnorm":
        info = loudnorm_file(src, dst, lufs, tp)
        y = wav.load(dst)
    elif engine == "st":
        y, info = process(x, preset, lufs, tp)
        y = save_to_target(dst, y, lufs, tp, bits=bits)
    else:
        raise ShowtimeError("unknown engine %r (use st or loudnorm)" % engine)
    after = meter.measure(y)
    rep = {"input": str(src), "output": str(dst), "target": {"lufs": lufs, "true_peak": tp},
           "engine": engine, "process": info, "before": before, "after": after}
    ai, atp = after.get("integrated_lufs"), after.get("true_peak_dbtp")
    if ai is not None and abs(ai - lufs) > 0.5:
        warn("output is %.1f LUFS (target %.1f)" % (ai, lufs))
    if atp is not None and atp > tp + 0.05:
        warn("output true peak %.2f dBTP is above the %.1f ceiling (lossy encoding adds overshoot; "
             "master to WAV and encode once at the end)" % (atp, tp))
    return rep


def target_for(name: Optional[str]) -> Tuple[float, float]:
    if not name:
        return TARGETS["web"]
    key = name.lower()
    if key not in TARGETS:
        raise ShowtimeError("unknown loudness target %r (choose: %s)" % (name, ", ".join(sorted(TARGETS))))
    return TARGETS[key]

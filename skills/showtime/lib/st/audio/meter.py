"""Loudness and level metering (ITU-R BS.1770-4 / EBU R128), numpy only.

- integrated loudness (LUFS) with the -70 LUFS absolute and -10 LU relative gates
- momentary (400 ms) and short-term (3 s) loudness curves and maxima
- loudness range (LRA, EBU Tech 3342)
- true peak (4x oversampled, dBTP), sample peak, RMS, per-window RMS
- clipping (runs of full-scale samples), DC offset, silence ratio

`measure_file()` decodes any audio/video file via st.audio.wav; with
ffmpeg_check=True it also runs ffmpeg's ebur128 filter as an independent
cross-check.
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional, Sequence

import numpy as np
from scipy import signal

from . import SR

ABS_GATE = -70.0


def _k_filters(fs: int):
    """K-weighting (pre-filter shelf + RLB high-pass) for any sample rate."""
    f0, G, Q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    K = math.tan(math.pi * f0 / fs)
    Vh = 10 ** (G / 20.0)
    Vb = Vh ** 0.4996667741545416
    a0 = 1.0 + K / Q + K * K
    b1 = [(Vh + Vb * K / Q + K * K) / a0, 2.0 * (K * K - Vh) / a0, (Vh - Vb * K / Q + K * K) / a0]
    a1 = [1.0, 2.0 * (K * K - 1.0) / a0, (1.0 - K / Q + K * K) / a0]
    f0, Q = 38.13547087602444, 0.5003270373238773
    K = math.tan(math.pi * f0 / fs)
    d = 1.0 + K / Q + K * K
    a2 = [1.0, 2.0 * (K * K - 1.0) / d, (1.0 - K / Q + K * K) / d]
    b2 = [1.0, -2.0, 1.0]
    return (np.array(b1), np.array(a1)), (np.array(b2), np.array(a2))


def k_weight(x: np.ndarray, fs: int = SR) -> np.ndarray:
    (b1, a1), (b2, a2) = _k_filters(fs)
    y = signal.lfilter(b1, a1, np.asarray(x, dtype=np.float64), axis=0)
    return signal.lfilter(b2, a2, y, axis=0)


def _block_power(z: np.ndarray, fs: int, win: float, hop: float) -> np.ndarray:
    """Mean-square per block (summed over channels, weight 1 for L/R)."""
    if z.ndim == 1:
        z = z[:, None]
    wn, hn = int(round(win * fs)), int(round(hop * fs))
    sq = (z ** 2).sum(axis=1)
    if len(sq) < wn:
        # shorter than one block: pad with silence (conservative, like a meter would)
        sq = np.pad(sq, (0, wn - len(sq)))
    cs = np.concatenate([[0.0], np.cumsum(sq)])
    starts = np.arange(0, len(sq) - wn + 1, hn)
    return (cs[starts + wn] - cs[starts]) / wn


def _lufs(p: np.ndarray) -> np.ndarray:
    return -0.691 + 10 * np.log10(np.maximum(p, 1e-20))


def integrated_from_power(p: np.ndarray) -> float:
    if p.size == 0:
        return float("-inf")
    L = _lufs(p)
    g1 = p[L > ABS_GATE]
    if g1.size == 0:
        return float("-inf")
    rel = _lufs(np.array([g1.mean()]))[0] - 10.0
    g2 = p[(L > ABS_GATE) & (L > rel)]
    if g2.size == 0:
        return float("-inf")
    return float(_lufs(np.array([g2.mean()]))[0])


def integrated(x: np.ndarray, fs: int = SR) -> float:
    """Integrated loudness in LUFS (-inf for silence)."""
    z = k_weight(x, fs)
    return integrated_from_power(_block_power(z, fs, 0.4, 0.1))


def _highpass2(x: np.ndarray, fc: float, fs: int) -> np.ndarray:
    """Two 2-pole RBJ high-passes (Q 0.707) in a row: ffmpeg's `highpass=f=fc,highpass=f=fc`."""
    w0 = 2 * math.pi * fc / fs
    cw, alpha = math.cos(w0), math.sin(w0) / (2 * 0.707)
    b = np.array([(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]) / (1 + alpha)
    a = np.array([1 + alpha, -2 * cw, 1 - alpha]) / (1 + alpha)
    sos = np.vstack([np.concatenate([b, a])] * 2)
    return signal.sosfilt(sos, np.asarray(x, dtype=np.float64), axis=0)


SPEAKER_BANDS = {"300": 300.0, "1k": 1000.0}
# the speaker gap (full mix minus the mix above 300 Hz, both integrated): measured on the posted films (2026-10-07)
# 0.7-8.2 LU, a music-led showreel whose energy was kick and sub 13.6 LU (it played ~9 dB quieter on a phone
# than the voice-led films at the same -14 LUFS). qa warns over SPEAKER_GAP_LU, fails over SPEAKER_GAP_FAIL_LU
# (runtime/thresholds.json "hearing" can move qa's); the mixer's speaker-safe step brings a mix over
# SPEAKER_GAP_LU down to SPEAKER_TARGET_LU.
SPEAKER_GAP_LU = 10.0
SPEAKER_GAP_FAIL_LU = 18.0
SPEAKER_TARGET_LU = 8.0


def speaker_loudness(x: np.ndarray, fs: int = SR, integrated_lufs: Optional[float] = None,
                     bands: Sequence[str] = ("300", "1k")) -> Dict[str, Optional[float]]:
    """How loud the mix is on a phone or laptop speaker, which plays little under ~300 Hz: the integrated
    loudness (gated like LUFS) of the mix high-passed at 300 Hz and at 1 kHz, next to the full mix's, and the
    gaps. The same numbers as `ffmpeg -af "highpass=f=300,highpass=f=300,ebur128"` (within ~0.1 LU).
    {integrated_lufs, above_300_lufs, gap_300_lu, above_1k_lufs, gap_1k_lu} (None for silence)."""
    x = np.asarray(x)
    I = integrated_lufs if integrated_lufs is not None else (integrated(x, fs) if x.size else float("-inf"))
    out: Dict[str, Optional[float]] = {"integrated_lufs": _r(I)}
    for key in bands:
        v = integrated(_highpass2(x, SPEAKER_BANDS[key], fs), fs) if x.size else float("-inf")
        out["above_%s_lufs" % key] = _r(v)
        out["gap_%s_lu" % key] = _r(I - v) if (math.isfinite(v) and I is not None and math.isfinite(I)) else None
    return out


def curves(x: np.ndarray, fs: int = SR, hop: float = 0.1) -> Dict[str, np.ndarray]:
    """Momentary (400 ms) and short-term (3 s) loudness curves at `hop` resolution."""
    z = k_weight(x, fs)
    return {"momentary": _lufs(_block_power(z, fs, 0.4, hop)),
            "short_term": _lufs(_block_power(z, fs, 3.0, hop)), "hop": np.array(hop)}


def lra(st: np.ndarray) -> Optional[float]:
    """Loudness range from a short-term loudness curve (EBU Tech 3342)."""
    s = st[st > ABS_GATE]
    if s.size < 2:
        return None
    p = 10 ** ((s + 0.691) / 10)
    rel = -0.691 + 10 * math.log10(p.mean()) - 20.0
    s = s[s > rel]
    if s.size < 2:
        return None
    return float(np.percentile(s, 95) - np.percentile(s, 10))


def true_peak(x: np.ndarray, oversample: int = 8, chunk_s: float = 10.0) -> float:
    """True peak in dBTP (8x polyphase oversampling, processed in chunks; 4x can
    under-read inter-sample peaks of limited material by up to 0.7 dB)."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    if x.size == 0:
        return float("-inf")
    step = int(chunk_s * SR)
    pad = 64
    peak = 0.0
    for s in range(0, len(x), step):
        a, b = max(0, s - pad), min(len(x), s + step + pad)
        seg = x[a:b]
        up = signal.resample_poly(seg, oversample, 1, axis=0)
        lo = (s - a) * oversample
        hi = lo + (min(len(x), s + step) - s) * oversample
        peak = max(peak, float(np.abs(up[lo:hi]).max()) if hi > lo else 0.0)
    peak = max(peak, float(np.abs(x).max()))
    return 20 * math.log10(peak + 1e-12)


def clipping(x: np.ndarray, thresh: float = 0.9999, min_run: int = 3) -> Dict[str, int]:
    """Count full-scale samples and runs of >= min_run consecutive ones (a sign of clipping)."""
    a = np.abs(np.asarray(x)) >= thresh
    if a.ndim == 2:
        a = a.any(axis=1)
    total = int(a.sum())
    runs = 0
    if total:
        d = np.diff(np.concatenate([[0], a.astype(np.int8), [0]]))
        starts, ends = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
        runs = int(((ends - starts) >= min_run).sum())
    return {"full_scale_samples": total, "clip_runs": runs}


def window_rms(x: np.ndarray, window: float = 1.0, fs: int = SR) -> List[float]:
    """RMS level (dBFS) per non-overlapping window."""
    m = np.asarray(x, dtype=np.float64)
    m = m.mean(axis=1) if m.ndim == 2 else m
    w = max(1, int(window * fs))
    k = int(math.ceil(len(m) / w))
    out = []
    for i in range(k):
        seg = m[i * w:(i + 1) * w]
        out.append(round(20 * math.log10(math.sqrt(float((seg ** 2).mean())) + 1e-12), 2) if seg.size else -120.0)
    return out


def measure(x: np.ndarray, fs: int = SR, windows: Optional[float] = None) -> Dict[str, object]:
    """Full measurement of an in-memory signal."""
    x = np.asarray(x, dtype=np.float32)
    dur = len(x) / float(fs)
    z = k_weight(x, fs)
    pm = _block_power(z, fs, 0.4, 0.1)
    ps = _block_power(z, fs, 3.0, 0.1)
    mom, st = _lufs(pm), _lufs(ps)
    I = integrated_from_power(pm)
    mono = x.mean(axis=1) if x.ndim == 2 else x
    sp = float(np.abs(x).max()) if x.size else 0.0
    rms = float(np.sqrt((mono.astype(np.float64) ** 2).mean())) if x.size else 0.0
    silent = float((np.abs(mono) < 10 ** (-60 / 20)).mean()) if x.size else 1.0
    out: Dict[str, object] = {
        "duration": round(dur, 4),
        "integrated_lufs": _r(I),
        "lra": _r(lra(st) if dur >= 3.0 else None),
        "momentary_max_lufs": _r(float(mom.max()) if mom.size else None),
        "short_term_max_lufs": _r(float(st.max()) if st.size and dur >= 3.0 else None),
        "true_peak_dbtp": _r(true_peak(x)),
        "sample_peak_dbfs": _r(20 * math.log10(sp + 1e-12)),
        "rms_dbfs": _r(20 * math.log10(rms + 1e-12)),
        "crest_db": _r(20 * math.log10((sp + 1e-12) / (rms + 1e-12))),
        "dc_offset": round(float(mono.mean()) if x.size else 0.0, 6),
        "silence_ratio": round(silent, 4),
        "short_clip": dur < 0.4,
    }
    out.update(clipping(x))
    if windows:
        out["window_s"] = windows
        out["window_rms_dbfs"] = window_rms(x, windows, fs)
    return out


def measure_file(path, windows: Optional[float] = None, ffmpeg_check: bool = False) -> Dict[str, object]:
    from . import wav
    x = wav.load(path)
    out = measure(x, SR, windows)
    out["file"] = str(path)
    if ffmpeg_check:
        out["ffmpeg"] = ffmpeg_ebur128(path)
    return out


def ffmpeg_ebur128(path) -> Dict[str, Optional[float]]:
    """Independent measurement with ffmpeg's ebur128 filter (integrated, LRA, true peak)."""
    from .. import ff
    cp = ff.run_ffmpeg(["-nostats", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"],
                       loglevel="info", overwrite=False, check=False)
    e = cp.stderr or ""
    if cp.returncode != 0:      # a failed run still prints a Summary of zeros (I: 0.0 LUFS)
        return {"integrated_lufs": None, "lra": None, "true_peak_dbtp": None}
    summary = e[e.rfind("Summary:"):] if "Summary:" in e else e

    def g(pat: str) -> Optional[float]:
        m = re.findall(pat, summary)
        try:
            return float(m[-1]) if m else None
        except ValueError:
            return None
    return {"integrated_lufs": g(r"I:\s+(-?[\d.]+|-inf) LUFS"), "lra": g(r"LRA:\s+([\d.]+) LU"),
            "true_peak_dbtp": g(r"Peak:\s+(-?[\d.]+|-inf) dBFS")}


def _r(v, nd: int = 2):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isinf(f) or math.isnan(f):
        return None
    return round(f, nd)

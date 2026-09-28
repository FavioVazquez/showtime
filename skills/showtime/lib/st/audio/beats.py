"""Music analysis -> beats.json: tempo, beat grid, downbeats, onsets, energy
curve, sections, surges/drops, rhythmic-vs-ambient flag and key.

Native engine (default): numpy/scipy only, no JIT warm-up:
  onset envelope    log-magnitude spectral flux on 64 log bands (22.05 kHz, hop 512)
  tempo             autocorrelation of the envelope, log-normal prior around 120 bpm,
                    plus a harmonic check (half/double tempo)
  beats             dynamic-programming beat tracker (Ellis 2007)
  downbeats         the bar phase whose beats carry the most low-band (kick) energy
  onsets            peak picking on the envelope; each tagged kick/snare/hat by band flux
  energy            RMS every 0.5 s, normalised; levels VOID/LOW/MEDIUM/HIGH; phases,
                    SURGE/DROP moments (per-second jumps > 0.12)
  trust             `rhythmic` is true only when onsets really coincide with the grid;
                    `pacing` = beat_cut | phrase_flow tells an editor whether hard cuts
                    may sit on beats or should follow phrases/energy instead
  key               Krumhansl-Schmuckler on a chroma from the spectrogram

Engine "librosa" uses librosa's beat_track for the grid (first call can take
minutes while numba compiles). Output schema "showtime.beats/1" is shared with
the composer's beats.json (which is exact by construction).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import signal
from scipy.ndimage import maximum_filter1d, uniform_filter1d

from ..common import ShowtimeError
from . import dsp, wav

AR = 22050
HOP = 512
NFFT = 2048
FPS = AR / HOP

KS_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KS_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def _stft_mag(y: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    f, _, Z = signal.stft(y, fs=AR, nperseg=NFFT, noverlap=NFFT - HOP, boundary="even", padded=True)
    return f, np.abs(Z).astype(np.float32)


def _log_bands(f: np.ndarray, nb: int = 64, fmin: float = 30.0, fmax: float = 11000.0) -> np.ndarray:
    edges = fmin * (fmax / fmin) ** (np.arange(nb + 1) / nb)
    W = np.zeros((nb, len(f)), np.float32)
    for i in range(nb):
        m = (f >= edges[i]) & (f < edges[i + 1])
        if not m.any():
            m = np.zeros(len(f), bool)
            m[np.argmin(np.abs(f - (edges[i] + edges[i + 1]) / 2))] = True
        W[i, m] = 1.0 / m.sum()
    return W


def onset_envelope(S: np.ndarray, f: np.ndarray) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
    """Spectral-flux onset strength (normalised) + per-band flux (kick/snare/hat)."""
    W = _log_bands(f)
    B = np.log1p(1000.0 * (W @ S))
    flux = np.maximum(0.0, np.diff(B, axis=1, prepend=B[:, :1]))
    env = flux.mean(axis=0)
    env = env - uniform_filter1d(env, size=int(FPS), mode="nearest")
    env = np.maximum(env, 0.0)
    env /= (env.max() + 1e-9)

    def band(lo, hi):
        m = (f >= lo) & (f < hi)
        e = np.sqrt(S[m].sum(axis=0) + 1e-12)
        d = np.maximum(0.0, np.diff(e, prepend=e[:1]))
        return d / (d.max() + 1e-9)
    bands = {"kick": band(20, 150), "snare": band(150, 900), "hat": band(5000, 11025), "click": band(1500, 5000)}
    return env.astype(np.float32), bands


def estimate_tempo(env: np.ndarray, prior_bpm: float = 120.0, lo: float = 55.0, hi: float = 200.0) -> Tuple[float, float]:
    """(bpm, confidence 0..1) from the onset autocorrelation with a tempo prior."""
    n = len(env)
    if n < int(FPS * 4):
        return 0.0, 0.0
    x = env - env.mean()
    ac = signal.fftconvolve(x, x[::-1], mode="full")[n - 1:]
    ac = ac / (ac[0] + 1e-9)
    lags = np.arange(len(ac))
    lmin, lmax = int(FPS * 60 / hi), min(len(ac) - 1, int(FPS * 60 / lo))
    if lmax <= lmin + 2:
        return 0.0, 0.0
    L = lags[lmin:lmax + 1].astype(np.float64)
    bpm = 60.0 * FPS / L
    prior = np.exp(-0.5 * (np.log2(bpm / prior_bpm) / 0.9) ** 2)
    score = np.maximum(ac[lmin:lmax + 1], 0.0)
    # harmonic reinforcement: a true beat period also correlates at 2x lag
    two = np.clip((2 * L).astype(int), 0, len(ac) - 1)
    score = score + 0.5 * np.maximum(ac[two], 0.0)
    weighted = score * prior
    i = int(np.argmax(weighted))
    # parabolic refinement
    if 0 < i < len(weighted) - 1:
        a, b, c = weighted[i - 1], weighted[i], weighted[i + 1]
        den = a - 2 * b + c
        off = 0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0
    else:
        off = 0.0
    lag = L[i] + off
    # confidence: height of the beat-period autocorrelation peak above its neighbourhood
    raw = float(max(ac[lmin + i], 0.0))
    floor = float(np.median(np.maximum(ac[lmin:lmax + 1], 0.0)))
    conf = float(np.clip((raw - floor) * 2.5, 0.0, 1.0))
    return 60.0 * FPS / lag, conf


def track_beats(env: np.ndarray, bpm: float, tightness: float = 100.0) -> np.ndarray:
    """Ellis-style dynamic-programming beat tracking; returns beat frame indices."""
    n = len(env)
    if bpm <= 0 or n < 4:
        return np.array([], dtype=int)
    period = FPS * 60.0 / bpm
    local = np.convolve(env, np.exp(-0.5 * (np.arange(-int(period), int(period) + 1) * 32.0 / period) ** 2), "same")
    local = local / (local.std() + 1e-9)
    score = np.zeros(n)
    back = np.full(n, -1, dtype=int)
    lo, hi = int(round(period / 2)), int(round(2 * period))
    offs = np.arange(lo, hi + 1)
    pen = -tightness * np.log(offs / period) ** 2
    for t in range(n):
        prev = t - offs
        ok = prev >= 0
        if ok.any():
            cand = score[prev[ok]] + pen[ok]
            j = int(np.argmax(cand))
            score[t] = local[t] + cand[j]
            back[t] = prev[ok][j]
        else:
            score[t] = local[t]
    # end at the best-scoring frame near the end (within one period)
    tail = max(0, n - int(period) - 1)
    t = tail + int(np.argmax(score[tail:]))
    beats = []
    while t >= 0:
        beats.append(t)
        t = back[t]
    beats = np.array(beats[::-1], dtype=int)
    # trim weak leading/trailing beats (silence before the music starts)
    if beats.size:
        strength = local[beats]
        thr = 0.5 * np.median(np.abs(strength))
        keep = np.nonzero(strength > thr)[0]
        if keep.size:
            beats = beats[keep[0]: keep[-1] + 1]
    return beats


def pick_onsets(env: np.ndarray, delta: float = 0.07, wait: float = 0.05) -> np.ndarray:
    w = max(1, int(0.03 * FPS))
    mx = maximum_filter1d(env, size=2 * w + 1, mode="nearest")
    avg = uniform_filter1d(env, size=int(0.1 * FPS) * 2 + 1, mode="nearest")
    cand = np.nonzero((env == mx) & (env >= avg + delta))[0]
    out, last = [], -1e9
    gap = wait * FPS
    for c in cand:
        if c - last >= gap:
            out.append(c)
            last = c
    return np.array(out, dtype=int)


def estimate_key(S: np.ndarray, f: np.ndarray) -> Tuple[Optional[str], float]:
    m = (f >= 55) & (f <= 2000)
    if not m.any():
        return None, 0.0
    ff_ = f[m]
    pcs = np.round(12 * np.log2(ff_ / 440.0) + 69).astype(int) % 12
    E = (S[m] ** 2).sum(axis=1)
    chroma = np.zeros(12)
    np.add.at(chroma, pcs, E)
    if chroma.sum() <= 0:
        return None, 0.0
    chroma = np.log1p(chroma / chroma.max() * 100)
    best = (-2.0, None)
    for i in range(12):
        for mode, prof in (("major", KS_MAJ), ("minor", KS_MIN)):
            r = float(np.corrcoef(chroma, np.roll(prof, i))[0, 1])
            if r > best[0]:
                best = (r, dsp.key_name(i, mode))
    return best[1], round(max(0.0, best[0]), 3)


def _z(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    return (v - v.mean()) / (v.std() + 1e-9)


def _fix_phase(beats: np.ndarray, bpm: float, env: np.ndarray, bands: Dict[str, np.ndarray], n: int) -> np.ndarray:
    """Beat trackers often lock onto off-beats (open hats, offbeat bass, swung 8ths).
    Try fractional shifts of the grid and keep the one where kick-with-click and
    snare/clap attacks are strongest (hats count against a position)."""
    period = 60.0 / bpm
    w = max(1, int(0.025 * FPS))
    k, sn, ht, ck = bands["kick"], bands["snare"], bands["hat"], bands["click"]

    def strength(ts):
        idx = np.clip((ts * FPS).round().astype(int), 0, n - 1)
        vals = []
        for i in idx:
            a, b = max(0, i - w), i + w + 1
            vals.append(k[a:b].max() * (0.5 + 2.0 * ck[a:b].max()) + 0.8 * sn[a:b].max() - 0.4 * ht[a:b].max())
        return float(np.mean(vals)) if vals else -9.0
    best_ts, best = beats, strength(beats) + 0.03          # small preference for the tracker's own grid
    for frac in (0.25, 1 / 3, 0.5, 0.62, 2 / 3, 0.75):
        ts = beats + frac * period
        ts = ts[ts < n / FPS]
        if ts.size < max(4, beats.size // 2):
            continue
        v = strength(ts)
        if v > best:
            best_ts, best = ts, v
    return best_ts


def _chroma_frames(S: np.ndarray, f: np.ndarray) -> np.ndarray:
    m = (f >= 55) & (f <= 2000)
    pcs = np.round(12 * np.log2(f[m] / 440.0) + 69).astype(int) % 12
    C = np.zeros((12, S.shape[1]))
    np.add.at(C, pcs, S[m] ** 2)
    return C / (C.sum(axis=0, keepdims=True) + 1e-12)


def _downbeat_scores(beats: np.ndarray, S: np.ndarray, f: np.ndarray, bands: Dict[str, np.ndarray]) -> np.ndarray:
    """Bar phase: harmonic change (chords move on bar lines) + low-band weight + crashes."""
    n = S.shape[1]
    bi = np.clip((beats * FPS).astype(int), 0, n - 1)
    C = _chroma_frames(S, f)
    low = S[f < 150].sum(axis=0) / (S.sum(axis=0) + 1e-9)
    hat = bands["hat"]
    per = int(np.median(np.diff(bi))) if len(bi) > 1 else int(FPS / 2)
    per = max(2, per)
    hc, lw, cr = [], [], []
    for i in bi:
        a, b = max(0, i - per), min(n, i + per)
        before = C[:, a:i].mean(axis=1) if i > a else C[:, i]
        after = C[:, i:b].mean(axis=1)
        hc.append(float(np.abs(after - before).sum()))
        lw.append(float(low[max(0, i - 2): i + 3].mean()))
        cr.append(float(hat[max(0, i - 2): i + 3].max()))
    score = _z(np.array(hc)) + 0.6 * _z(np.array(lw)) + 0.3 * _z(np.array(cr))
    return score


def _downbeats(beats: np.ndarray, score: np.ndarray, win: int = 16) -> Tuple[List[float], int]:
    """Choose the bar phase per window of `win` beats (robust to a dropped/extra beat)."""
    nb = len(beats)
    out: List[float] = []
    first_phase = 0
    for w0 in range(0, nb, win // 2):
        a, b = max(0, w0 - win // 4), min(nb, w0 + win)
        idx = np.arange(a, b)
        sums = [score[idx[(idx - k) % 4 == 0]].mean() if (idx[(idx - k) % 4 == 0]).size else -9 for k in range(4)]
        k = int(np.argmax(sums))
        if w0 == 0:
            first_phase = k
        for i in range(w0, min(nb, w0 + win // 2)):
            if (i - k) % 4 == 0 and (not out or beats[i] - out[-1] > 2.5 * (beats[1] - beats[0] if nb > 1 else 0.5)):
                out.append(round(float(beats[i]), 4))
    return out, first_phase


def _levels(e: float) -> str:
    return "VOID" if e < 0.2 else ("LOW" if e < 0.4 else ("MEDIUM" if e < 0.65 else "HIGH"))


def analyze(path, engine: str = "native", prior_bpm: float = 120.0, max_seconds: Optional[float] = None,
            known_bpm: Optional[float] = None) -> Dict:
    """Analyse an audio/video file (see module doc). `known_bpm` (e.g. from
    catalog metadata) constrains the tempo search to +-8 % (or half/double)."""
    p = Path(path)
    y = wav.load(p, sr=AR, mono=True, duration=max_seconds)
    dur = len(y) / AR
    if dur < 1.0:
        raise ShowtimeError("%s is too short to analyse (%.2fs)" % (p, dur))
    f, S = _stft_mag(y)
    env, bands = onset_envelope(S, f)
    if engine == "librosa":
        bpm, conf, beats = _librosa_beats(y)
    else:
        if known_bpm:
            cands = [known_bpm, known_bpm * 2, known_bpm / 2]
            cands = [c for c in cands if 55 <= c <= 200] or [known_bpm]
            best = max(((estimate_tempo(env, c, c * 0.92, c * 1.08), c) for c in cands), key=lambda z: z[0][1])
            bpm, conf = best[0]
            if bpm <= 0:
                bpm, conf = float(known_bpm), 0.3
        else:
            bpm, conf = estimate_tempo(env, prior_bpm)
        bf = track_beats(env, bpm) if bpm > 0 else np.array([], dtype=int)
        beats = bf / FPS
    beats = np.asarray(beats, dtype=float)
    if engine != "librosa" and beats.size >= 4 and bpm > 0:
        beats = _fix_phase(beats, bpm, env, bands, len(env))
    onset_frames = pick_onsets(env)
    onsets = onset_frames / FPS
    # downbeat phase: which of the 4 phases puts the most kick energy on beat 1
    downbeats: List[float] = []
    phase = 0
    if beats.size >= 8:
        downbeats, phase = _downbeats(beats, _downbeat_scores(beats, S, f, bands))
    # beat/onset agreement -> trust
    coinc = 0.0
    if beats.size and onsets.size:
        d = np.abs(beats[:, None] - onsets[None, :]).min(axis=1)
        coinc = float((d < 0.07).mean())
    onset_rate = onsets.size / dur
    rhythmic = bool(beats.size >= 8 and conf >= 0.15 and coinc >= 0.45 and onset_rate >= 0.8)
    # classify onsets
    on_list = []
    for fr in onset_frames:
        a, b = max(0, fr - 1), min(len(env), fr + 2)
        vals = {k: float(v[a:b].max()) for k, v in bands.items() if k != "click"}
        lead = max(vals, key=vals.get)
        on_list.append({"t": round(fr / FPS, 4), "strength": round(float(env[fr]), 3),
                        "band": lead if vals[lead] >= 0.06 else "perc"})
    # energy curve (0.5 s) and phases
    hop_s = 0.5
    hop_n = int(hop_s * AR)
    k = max(1, int(math.ceil(len(y) / hop_n)))
    rms = np.array([math.sqrt(float((y[i * hop_n:(i + 1) * hop_n] ** 2).mean()) + 1e-12) for i in range(k)])
    en = rms / (rms.max() + 1e-12)
    phases = []
    cur = None
    for i, e in enumerate(en):
        lv = _levels(float(e))
        if cur is None or cur["level"] != lv:
            if cur is not None:
                cur["end"] = round(i * hop_s, 3)
                phases.append(cur)
            cur = {"level": lv, "start": round(i * hop_s, 3)}
    if cur is not None:
        cur["end"] = round(dur, 3)
        phases.append(cur)
    # merge phases shorter than 2 s into their neighbour
    merged: List[dict] = []
    for ph in phases:
        if merged and (ph["end"] - ph["start"] < 2.0 or merged[-1]["level"] == ph["level"]):
            merged[-1]["end"] = ph["end"]
        else:
            merged.append(dict(ph))
    for ph in merged:
        a, b = int(ph["start"] / hop_s), max(int(ph["start"] / hop_s) + 1, int(ph["end"] / hop_s))
        ph["energy"] = round(float(en[a:b].mean()), 3)
        ph["level"] = _levels(ph["energy"])
    per_s = np.array([en[i:i + 2].mean() for i in range(0, len(en), 2)])
    moments = []
    for i in range(1, len(per_s)):
        dlt = float(per_s[i] - per_s[i - 1])
        if abs(dlt) > 0.12:
            moments.append({"t": float(i), "type": "SURGE" if dlt > 0 else "DROP", "size": round(abs(dlt), 3)})
    moments = sorted(sorted(moments, key=lambda m: -m["size"])[:8], key=lambda m: m["t"])
    key, kconf = estimate_key(S, f)
    lufs = None
    try:
        from . import meter
        lufs = meter._r(meter.integrated(wav.load(p, duration=max_seconds)))
    except Exception:  # noqa: BLE001
        pass
    return {
        "schema": "showtime.beats/1", "source": "analyzed", "engine": engine, "file": str(p), "duration": round(dur, 3),
        "bpm": round(float(bpm), 2) if bpm else None, "bpm_confidence": round(float(conf), 3),
        "time_signature": 4, "downbeat_phase": phase,
        "beats": [round(float(t), 4) for t in beats], "downbeats": downbeats,
        "rhythmic": rhythmic, "pacing": "beat_cut" if rhythmic else "phrase_flow",
        "beat_onset_agreement": round(coinc, 3), "onset_rate": round(onset_rate, 2),
        "onsets": on_list,
        "energy": {"hop": hop_s, "values": [round(float(v), 3) for v in en]},
        "sections": merged, "moments": moments,
        "key": key, "key_confidence": kconf, "integrated_lufs": lufs,
    }


def _librosa_beats(y: np.ndarray):
    try:
        import librosa
    except Exception as e:  # noqa: BLE001
        raise ShowtimeError("librosa engine unavailable (%s)" % e, hint="use --engine native")
    tempo, frames = librosa.beat.beat_track(y=y, sr=AR, hop_length=HOP)
    bpm = float(np.atleast_1d(tempo)[0])
    return bpm, 0.5, librosa.frames_to_time(frames, sr=AR, hop_length=HOP)


def summary_text(d: Dict) -> str:
    """A short human/LLM-readable brief of an analysis."""
    lines = ["%s: %.1fs, %s bpm (confidence %.2f), key %s, %s -> %s" % (
        Path(d.get("file", "?")).name, d.get("duration", 0), d.get("bpm"), d.get("bpm_confidence", 0) or 0,
        d.get("key"), "rhythmic" if d.get("rhythmic") else "not reliably rhythmic", d.get("pacing"))]
    db_ = d.get("downbeats") or []
    if db_:
        lines.append("downbeats: " + ", ".join("%.2f" % t for t in db_[:16]) + (" ..." if len(db_) > 16 else ""))
    for s in d.get("sections", []):
        lines.append("  %6.2f-%6.2f  %-6s energy %.2f" % (s["start"], s["end"], s.get("level", s.get("kind", "")),
                                                          s.get("energy", 0)))
    for m in d.get("moments", []):
        lines.append("  %s at %.1fs (%.2f)" % (m["type"], m["t"], m["size"]))
    return "\n".join(lines)

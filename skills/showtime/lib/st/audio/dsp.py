"""DSP building blocks for showtime's procedural audio (numpy + scipy only).

Conventions: mono = 1-D float32, stereo = (n, 2) float32, sample rate SR
(48 kHz). Every generator takes an explicit seed, so output is deterministic
and fully owned (no samples, no third-party licenses).
"""
from __future__ import annotations

import math
import re
from typing import Optional, Sequence, Tuple, Union

import numpy as np
from scipy import signal

from . import SR

ArrayLike = Union[float, np.ndarray]

NOTE_NAMES = {"C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "F": 5, "F#": 6,
              "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9, "A#": 10, "BB": 10, "B": 11, "CB": 11,
              "E#": 5, "FB": 4, "B#": 0}
PC_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
MAJOR = [0, 2, 4, 5, 7, 9, 11]
MINOR = [0, 2, 3, 5, 7, 8, 10]


# --------------------------------------------------------------------------- basics
def n(sec: float) -> int:
    """Seconds -> sample count (at least 1)."""
    return max(1, int(round(sec * SR)))


def t_axis(dur: float) -> np.ndarray:
    return np.arange(n(dur)) / SR


def midi_to_hz(m: ArrayLike) -> ArrayLike:
    return 440.0 * 2 ** ((np.asarray(m, dtype=np.float64) - 69) / 12)


def parse_key(key: str) -> Tuple[int, str]:
    """'C', 'Am', 'F# minor', 'Eb major', 'Bbm', 'c#m' -> (pitch_class, 'major'|'minor')."""
    s = (key or "C").strip()
    m = re.match(r"^([A-Ga-g])([#b♯♭]?)\s*(.*)$", s)
    if not m:
        raise ValueError("bad key %r (use e.g. C, Am, F#, Ebm, 'D minor')" % key)
    acc = {"♯": "#", "♭": "B", "b": "B"}.get(m.group(2), m.group(2))
    root = m.group(1).upper() + acc.upper()
    rest = m.group(3).strip().lower()
    if rest in ("", "maj", "major", "ionian"):
        mode = "major"
    elif rest in ("m", "min", "minor", "-", "aeolian"):
        mode = "minor"
    else:
        raise ValueError("bad key %r (mode must be major or minor)" % key)
    return NOTE_NAMES[root], mode


def key_name(pc: int, mode: str) -> str:
    return PC_NAMES[pc % 12] + ("m" if mode == "minor" else "")


def scale_of(key: str) -> Tuple[int, list]:
    pc, mode = parse_key(key)
    return pc, (MAJOR if mode == "major" else MINOR)


def key_note(key: str, octave: int = 5, degree: int = 0) -> int:
    """MIDI note of a scale degree (0 = root) of `key` in `octave` (C4 = 60)."""
    pc, sc = scale_of(key)
    o, d = divmod(degree, 7)
    return 12 * (octave + 1 + o) + pc + sc[d]


def rng(seed) -> np.random.Generator:
    return np.random.default_rng(seed)


def db(x: float) -> float:
    return 20.0 * math.log10(max(float(x), 1e-12))


def undb(d: float) -> float:
    return 10.0 ** (d / 20.0)


# --------------------------------------------------------------------------- noise
def noise(num: int, color: str = "white", r: Optional[np.random.Generator] = None) -> np.ndarray:
    """white / pink (1/f) / brown (1/f^2) / blue noise, peak-normalised to ~1."""
    r = r if r is not None else rng(0)
    w = r.standard_normal(num)
    if color != "white":
        spec = np.fft.rfft(w)
        f = np.fft.rfftfreq(num, 1 / SR)
        f[0] = f[1] if len(f) > 1 else 1.0
        p = {"pink": 0.5, "brown": 1.0, "blue": -0.5}[color]
        spec /= f ** p
        w = np.fft.irfft(spec, num)
    w = w - w.mean()
    return (w / (np.abs(w).max() + 1e-12)).astype(np.float32)


# --------------------------------------------------------------------------- envelopes
def env_adsr(num: int, a: float, d: float, s: float, r: float, curve: float = 3.0) -> np.ndarray:
    """ADSR in seconds; the sustain fills whatever time is left."""
    na, nd, nr = int(a * SR), int(d * SR), int(r * SR)
    ns = max(0, num - na - nd - nr)
    att = np.linspace(0, 1, max(na, 1)) ** (1 / 1.5)
    dec = s + (1 - s) * np.exp(-curve * np.linspace(0, 1, max(nd, 1)))
    sus = np.full(ns, s)
    rel = s * np.exp(-curve * np.linspace(0, 1, max(nr, 1)))
    e = np.concatenate([att, dec, sus, rel])[:num]
    if len(e) < num:
        e = np.pad(e, (0, num - len(e)))
    return e.astype(np.float32)


def env_exp(num: int, attack: float, decay_t60: float) -> np.ndarray:
    """Percussive: linear attack (s), then exponential decay reaching -60 dB at decay_t60."""
    na = min(num, max(1, int(attack * SR)))
    tt = np.arange(num - na) / SR
    dec = np.exp(-6.9078 * tt / max(decay_t60, 1e-4))
    return np.concatenate([np.linspace(0, 1, na, endpoint=False), dec]).astype(np.float32)[:num]


def bell_curve(num: int, peak_frac: float, rise_pow: float = 2.0, fall_pow: float = 2.0) -> np.ndarray:
    """0 -> 1 -> 0 asymmetric raised-cosine curve peaking at peak_frac of its length."""
    p = min(num - 1, max(1, int(num * peak_frac)))
    up = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, p))) ** rise_pow
    dn = (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, num - p))) ** fall_pow
    return np.concatenate([up, dn]).astype(np.float32)


def fade(x: np.ndarray, fin: float = 0.002, fout: float = 0.005) -> np.ndarray:
    """Raised-cosine fade in/out (seconds) for click-free edges. Returns a copy."""
    x = np.array(x, dtype=np.float32, copy=True)
    a, b = min(len(x), int(fin * SR)), min(len(x), int(fout * SR))
    if a > 1:
        w = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, a))).astype(np.float32)
        x[:a] *= w if x.ndim == 1 else w[:, None]
    if b > 1:
        w = (0.5 + 0.5 * np.cos(np.linspace(0, np.pi, b))).astype(np.float32)
        x[-b:] *= w if x.ndim == 1 else w[:, None]
    return x


# --------------------------------------------------------------------------- oscillators
def phase_from_freq(freq: ArrayLike, num: int, phase0: float = 0.0) -> np.ndarray:
    f = np.broadcast_to(np.asarray(freq, dtype=np.float64), (num,))
    return phase0 + 2 * np.pi * np.cumsum(f) / SR


def _blep(t: np.ndarray, dt: np.ndarray) -> np.ndarray:
    y = np.zeros_like(t)
    m1 = t < dt
    x = t[m1] / dt[m1]
    y[m1] = x + x - x * x - 1
    m2 = t > 1 - dt
    x = (t[m2] - 1) / dt[m2]
    y[m2] = x * x + x + x + 1
    return y


def osc(shape: str, freq: ArrayLike, num: int, phase0: float = 0.0, pw: float = 0.5) -> np.ndarray:
    """Band-limited-ish oscillators: sine, triangle, saw and square/pulse (polyBLEP)."""
    f = np.broadcast_to(np.asarray(freq, dtype=np.float64), (num,))
    ph = phase_from_freq(f, num, phase0)
    if shape == "sine":
        return np.sin(ph).astype(np.float32)
    t = (ph / (2 * np.pi)) % 1.0
    dt = np.clip(f / SR, 1e-9, 0.5)
    if shape == "saw":
        return (2 * t - 1 - _blep(t, dt)).astype(np.float32)
    if shape in ("square", "pulse"):
        w = 0.5 if shape == "square" else float(pw)
        sq = np.where(t < w, 1.0, -1.0)
        sq += _blep(t, dt) - _blep((t + 1 - w) % 1.0, dt)
        return (sq - (2 * w - 1)).astype(np.float32)
    if shape == "triangle":
        return (2 * np.abs(2 * t - 1) - 1).astype(np.float32)
    raise ValueError("unknown oscillator shape %r" % shape)


def supersaw(freq: ArrayLike, num: int, voices: int = 7, detune_cents: float = 18,
             r: Optional[np.random.Generator] = None) -> np.ndarray:
    """Detuned saw stack spread across the stereo field -> (num, 2)."""
    r = r if r is not None else rng(1)
    out = np.zeros((num, 2), np.float32)
    half = (voices - 1) / 2 or 1
    for i in range(voices):
        c = detune_cents * (i - (voices - 1) / 2) / half
        v = osc("saw", np.asarray(freq) * 2 ** (c / 1200), num, r.uniform(0, 2 * np.pi))
        p = 0.5 + 0.45 * (i - (voices - 1) / 2) / half
        out[:, 0] += v * math.cos(p * math.pi / 2)
        out[:, 1] += v * math.sin(p * math.pi / 2)
    return out / voices


def fm_tone(freq: float, dur: float, index: float = 2.0, ratio: float = 1.0, decay: float = 0.6,
            idx_decay: float = 0.15, attack: float = 0.002) -> np.ndarray:
    """Two-operator FM bell/keys tone (mono)."""
    N = n(dur)
    tt = np.arange(N) / SR
    idx = index * np.exp(-tt / max(idx_decay, 1e-4))
    mod = np.sin(2 * np.pi * freq * ratio * tt) * idx
    return (np.sin(2 * np.pi * freq * tt + mod) * env_exp(N, attack, decay)).astype(np.float32)


def karplus(freq: float, dur: float, r: Optional[np.random.Generator] = None, bright: float = 0.5,
            decay: float = 0.996) -> np.ndarray:
    """Karplus-Strong plucked string (guitar / harp / pizzicato), vectorised per period."""
    r = r if r is not None else rng(0)
    N = n(dur)
    period = max(2, int(round(SR / max(freq, 20.0))))
    buf = r.uniform(-1, 1, period)
    if bright < 1:
        buf = signal.lfilter([1 - bright * 0.5], [1, -bright * 0.5], buf)
    reps = N // period + 2
    out = np.empty(reps * period)
    out[:period] = buf
    prev = buf
    for k in range(1, reps):
        nxt = decay * 0.5 * (prev + np.roll(prev, 1))
        out[k * period:(k + 1) * period] = nxt
        prev = nxt
    y = out[:N] * np.minimum(1, np.arange(N) / (0.001 * SR))
    return (y / (np.abs(y).max() + 1e-9)).astype(np.float32)


# --------------------------------------------------------------------------- filters
def butter(x: np.ndarray, fc, kind: str = "low", order: int = 4) -> np.ndarray:
    """Butterworth filter (kind: low, high, band, bandstop); axis 0."""
    fcs = np.clip(np.asarray(fc, dtype=np.float64), 5.0, SR * 0.49)
    sos = signal.butter(order, fcs, btype=kind, fs=SR, output="sos")
    return signal.sosfilt(sos, x, axis=0).astype(np.float32)


def resonator(x: np.ndarray, freq: float, q: float) -> np.ndarray:
    b, a = signal.iirpeak(min(freq, SR * 0.45), q, fs=SR)
    return signal.lfilter(b, a, x, axis=0).astype(np.float32)


def _rbj(mode: str, fc: float, q: float, gain_db: float = 0.0) -> Tuple[np.ndarray, np.ndarray]:
    """RBJ audio-EQ-cookbook biquad coefficients (b, a) normalised by a0."""
    fc = min(max(fc, 5.0), SR * 0.49)
    w0 = 2 * math.pi * fc / SR
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * max(q, 1e-3))
    A = 10 ** (gain_db / 40)
    if mode == "lp":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif mode == "hp":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif mode == "bp":
        b = [alpha, 0, -alpha]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif mode == "notch":
        b = [1, -2 * cw, 1]
        a = [1 + alpha, -2 * cw, 1 - alpha]
    elif mode == "peak":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif mode in ("lowshelf", "highshelf"):
        sq = 2 * math.sqrt(A) * alpha
        if mode == "lowshelf":
            b = [A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq)]
            a = [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq]
        else:
            b = [A * ((A + 1) + (A - 1) * cw + sq), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sq)]
            a = [(A + 1) - (A - 1) * cw + sq, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sq]
    else:
        raise ValueError("unknown biquad mode %r" % mode)
    b_, a_ = np.asarray(b, dtype=np.float64), np.asarray(a, dtype=np.float64)
    return b_ / a_[0], a_ / a_[0]


def biquad(x: np.ndarray, mode: str, fc: float, q: float = 0.707, gain_db: float = 0.0) -> np.ndarray:
    """Static biquad (lp, hp, bp, notch, peak, lowshelf, highshelf) along axis 0."""
    b, a = _rbj(mode, fc, q, gain_db)
    return signal.lfilter(b, a, x, axis=0).astype(np.float32)


def eq(x: np.ndarray, bands: Sequence[Tuple[str, float, float, float]]) -> np.ndarray:
    """Apply a list of (mode, fc, q, gain_db) biquads in order."""
    y = x
    for mode, fc, q, g in bands:
        y = biquad(y, mode, fc, q, g)
    return y


def svf(x: np.ndarray, cutoff: ArrayLike, q: ArrayLike = 0.707, mode: str = "lp", block: int = 32) -> np.ndarray:
    """Time-varying filter (lp, hp, bp): biquad coefficients updated every `block`
    samples with the filter state carried across blocks. `cutoff`/`q` may be
    scalars or per-sample arrays. Mono or stereo input."""
    x = np.asarray(x, dtype=np.float64)
    num = len(x)
    fc = np.broadcast_to(np.asarray(cutoff, dtype=np.float64), (num,))
    qq = np.broadcast_to(np.asarray(q, dtype=np.float64), (num,))
    if np.ptp(fc) < 1e-9 and np.ptp(qq) < 1e-9:
        return biquad(x, mode, float(fc[0]), float(qq[0])).astype(np.float32)
    out = np.empty_like(x)
    zi_shape = (2,) + x.shape[1:]
    zi = np.zeros(zi_shape)
    for s in range(0, num, block):
        e = min(num, s + block)
        b, a = _rbj(mode, float(fc[(s + e) // 2]), float(qq[(s + e) // 2]))
        out[s:e], zi = signal.lfilter(b, a, x[s:e], axis=0, zi=zi)
    return out.astype(np.float32)


def dc_block(x: np.ndarray, fc: float = 18.0) -> np.ndarray:
    return butter(x, fc, "high", 2)


# --------------------------------------------------------------------------- stereo
def pan(x: np.ndarray, p: ArrayLike) -> np.ndarray:
    """Equal-power pan; p in [-1, 1] (scalar or per-sample). mono -> stereo;
    stereo input is balanced (each side scaled)."""
    if x.ndim == 2:
        pp = (np.broadcast_to(np.asarray(p, dtype=np.float64), (len(x),)) + 1) * np.pi / 4
        g = np.stack([np.cos(pp), np.sin(pp)], axis=1) * math.sqrt(2)
        return (x * np.minimum(g, 1.0)).astype(np.float32)
    pp = (np.broadcast_to(np.asarray(p, dtype=np.float64), (len(x),)) + 1) * np.pi / 4
    return np.stack([x * np.cos(pp), x * np.sin(pp)], axis=1).astype(np.float32)


def to_stereo(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 2:
        if x.shape[1] == 2:
            return x
        if x.shape[1] == 1:
            return np.repeat(x, 2, axis=1)
        return x[:, :2]
    return np.stack([x, x], axis=1)


def to_mono(x: np.ndarray) -> np.ndarray:
    return x.mean(axis=1).astype(np.float32) if x.ndim == 2 else x.astype(np.float32)


def widen(x: np.ndarray, ms: float = 12.0, amount: float = 0.5) -> np.ndarray:
    """Haas-style decorrelation: a short-delayed copy feeds the side channel."""
    s = to_stereo(x)
    d = int(ms * SR / 1000)
    mid = s.mean(axis=1)
    delayed = np.concatenate([np.zeros(d, np.float32), mid[:-d]]) if 0 < d < len(mid) else mid
    side = (mid - delayed) * 0.5 * amount
    return np.stack([mid + side, mid - side], axis=1).astype(np.float32)


# --------------------------------------------------------------------------- effects
def synth_ir(t60: float = 2.0, predelay: float = 0.01, bright: float = 6000, seed: int = 7,
             early: bool = True) -> np.ndarray:
    """Synthetic stereo impulse response: decorrelated exponentially decaying
    noise with a darkening tail and optional early reflections."""
    r = rng(seed)
    num = n(t60 * 1.1)
    tt = np.arange(num) / SR
    e = np.exp(-6.9078 * tt / t60)
    ir = np.stack([r.standard_normal(num) * e, r.standard_normal(num) * e], 1).astype(np.float32)
    # frequency-dependent decay: split, and let the highs die faster
    hi = butter(ir, bright, "high", 2) * np.exp(-6.9078 * tt / max(t60 * 0.35, 0.05))[:, None]
    ir = butter(ir, bright, "low", 2) + hi
    if early:
        for k in range(6):
            dly = int(r.uniform(0.004, 0.035) * SR)
            if dly < num:
                ir[dly, k % 2] += r.uniform(0.3, 0.8) * (1 if r.random() < 0.5 else -1)
    ir = np.concatenate([np.zeros((n(predelay), 2), np.float32), ir])
    return (ir / (np.sqrt((ir ** 2).sum(axis=0)).max() + 1e-12)).astype(np.float32)


_IR_CACHE: dict = {}


def conv_reverb(x: np.ndarray, t60: float = 2.0, wet: float = 0.25, dry: float = 1.0, bright: float = 6000,
                seed: int = 7, predelay: float = 0.012, tail: bool = True) -> np.ndarray:
    """Convolution reverb with a synthetic IR (no GPL dependency). With tail=True
    the output grows by the reverb tail (trimmed at -70 dB); otherwise it keeps
    the input length."""
    key = (round(t60, 3), round(bright), seed, round(predelay, 4))
    ir = _IR_CACHE.get(key)
    if ir is None:
        ir = synth_ir(t60, predelay, bright, seed)
        _IR_CACHE[key] = ir
        if len(_IR_CACHE) > 32:
            _IR_CACHE.pop(next(iter(_IR_CACHE)))
    s = to_stereo(x)
    wetsig = np.stack([signal.fftconvolve(s[:, c], ir[:, c]) for c in range(2)], 1).astype(np.float32)
    out = np.zeros_like(wetsig)
    out[: len(s)] += s * dry
    out += wetsig * wet
    if not tail:
        return out[: len(s)]
    return trim_silence_end(out)


def delay(x: np.ndarray, time_s: float, feedback: float = 0.3, mix: float = 0.2, taps: int = 6,
          pingpong: bool = True, damp: float = 5000) -> np.ndarray:
    """Feedback echo as a sum of taps (each darker than the last); keeps length."""
    s = to_stereo(x)
    out = s.copy()
    d = max(1, int(time_s * SR))
    tap = s
    g = 1.0
    for k in range(1, taps + 1):
        g *= feedback
        if g < 0.01 or k * d >= len(s):
            break
        tap = butter(tap, damp, "low", 1)
        shifted = np.zeros_like(s)
        shifted[k * d:] = tap[: len(s) - k * d]
        if pingpong and k % 2 == 1:
            shifted = shifted[:, ::-1]
        out += shifted * (mix * g / feedback)
    return out.astype(np.float32)


def chorus(x: np.ndarray, rate: float = 0.4, depth_ms: float = 4.0, base_ms: float = 12.0, mix: float = 0.35) -> np.ndarray:
    """Stereo chorus: two modulated delay lines (linear interpolation)."""
    s = to_stereo(x)
    N = len(s)
    tt = np.arange(N) / SR
    out = s * (1 - mix * 0.5)
    for c, ph in ((0, 0.0), (1, math.pi / 2)):
        dl = (base_ms + depth_ms * np.sin(2 * np.pi * rate * tt + ph)) * SR / 1000
        pos = np.arange(N) - dl
        out[:, c] += np.interp(pos, np.arange(N), s[:, c], left=0.0) * mix
    return out.astype(np.float32)


def compress(x: np.ndarray, threshold_db: float = -18.0, ratio: float = 3.0, attack: float = 0.01,
             release: float = 0.15, knee_db: float = 6.0, makeup_db: float = 0.0, hop: int = 48,
             sidechain: Optional[np.ndarray] = None) -> np.ndarray:
    """Feed-forward RMS-ish compressor with a soft knee (gain computed per `hop`
    samples, smoothed with attack/release, interpolated per sample)."""
    s = to_stereo(x)
    sc = to_stereo(sidechain) if sidechain is not None else s
    N = len(s)
    k = max(1, N // hop)
    lvl = np.abs(sc[: k * hop]).max(axis=1).reshape(k, hop)
    lvl_db = 20 * np.log10(np.sqrt((lvl ** 2).mean(axis=1)) * 1.4142 + 1e-9)
    over = lvl_db - threshold_db
    gr = np.where(over <= -knee_db / 2, 0.0,
                  np.where(over >= knee_db / 2, over * (1 - 1 / ratio),
                           (1 - 1 / ratio) * (over + knee_db / 2) ** 2 / (2 * max(knee_db, 1e-6))))
    a_att = math.exp(-hop / (SR * max(attack, 1e-4)))
    a_rel = math.exp(-hop / (SR * max(release, 1e-4)))
    sm = np.empty(k)
    g = 0.0
    for i, v in enumerate(gr.tolist()):
        g = a_att * g + (1 - a_att) * v if v > g else a_rel * g + (1 - a_rel) * v
        sm[i] = g
    gain = 10 ** ((makeup_db - sm) / 20)
    idx = (np.arange(k) + 0.5) * hop
    g_s = np.interp(np.arange(N), idx, gain).astype(np.float32)
    return (s * g_s[:, None]).astype(np.float32)


def trim_silence_end(x: np.ndarray, thresh_db: float = -70) -> np.ndarray:
    a = np.abs(x) if x.ndim == 1 else np.abs(x).max(axis=1)
    if not len(a):
        return x
    idx = np.nonzero(a > 10 ** (thresh_db / 20) * (a.max() + 1e-12))[0]
    end = (idx[-1] + 1) if len(idx) else len(x)
    return fade(x[: min(len(x), end + n(0.01))], 0, 0.01)


def softclip(x: np.ndarray, drive: float = 1.0) -> np.ndarray:
    return (np.tanh(x * drive) / np.tanh(drive)).astype(np.float32)


def normalize_peak(x: np.ndarray, peak_db: float = -1.0) -> np.ndarray:
    return (x / (np.abs(x).max() + 1e-12) * 10 ** (peak_db / 20)).astype(np.float32)


def resample_varispeed(x: np.ndarray, speed: np.ndarray) -> np.ndarray:
    """Read x with a time-varying playback speed (1 = normal, 0 = stopped, <0 = reverse)."""
    pos = np.clip(np.cumsum(speed), 0, len(x) - 1)
    grid = np.arange(len(x))
    if x.ndim == 1:
        return np.interp(pos, grid, x).astype(np.float32)
    return np.stack([np.interp(pos, grid, x[:, c]) for c in range(x.shape[1])], 1).astype(np.float32)


def mix_at(dst: np.ndarray, src: np.ndarray, at_sample: int, gain: float = 1.0) -> np.ndarray:
    """Add src into dst (stereo) starting at sample index (may be negative). In place."""
    src = to_stereo(src)
    s0 = max(0, at_sample)
    k0 = s0 - at_sample
    e = min(len(dst), at_sample + len(src))
    if e > s0:
        dst[s0:e] += src[k0: k0 + (e - s0)] * gain
    return dst


def pad_to(x: np.ndarray, num: int) -> np.ndarray:
    """Zero-pad or cut to exactly num samples."""
    if len(x) >= num:
        return x[:num]
    pad = np.zeros((num - len(x),) + x.shape[1:], dtype=x.dtype)
    return np.concatenate([x, pad])


def crossfade_concat(a: np.ndarray, b: np.ndarray, xfade: float) -> np.ndarray:
    """Concatenate with an equal-power crossfade of `xfade` seconds."""
    a, b = to_stereo(a), to_stereo(b)
    k = min(n(xfade), len(a), len(b))
    if k <= 1:
        return np.concatenate([a, b])
    t = np.linspace(0, 1, k, dtype=np.float32)[:, None]
    mid = a[-k:] * np.cos(t * np.pi / 2) + b[:k] * np.sin(t * np.pi / 2)
    return np.concatenate([a[:-k], mid, b[k:]]).astype(np.float32)

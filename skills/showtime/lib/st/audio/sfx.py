"""Procedural sound effects: 50+ types synthesised from math (numpy/scipy).

Every generator returns stereo float32 at 48 kHz plus metadata. `render()`
cleans the result (DC blocker, click-free edges), loudness-matches it to its
category and measures the **hit**: the moment to align with a video frame.

  hit kinds:  onset  where the sound starts to hit (impacts, clicks, bells)
              peak   the loudest moment (whooshes passing by, sparkles)
              end    where a build-up lands (risers, reverse cymbals, swells)

Category levels (max momentary loudness, LUFS; `gain_db` in a mix is relative
to these): ui -24, foley -22, fx -20, transition -18, musical -16, impact -14,
ambience -32 (integrated). Sample peaks are capped per category (ui -8 dBFS,
foley -6, fx -4, transition -3, musical -2, impact -1), so very short clicks
land on their peak cap rather than their loudness target.

Everything is deterministic for a given (type, dur, intensity, seed, key), and
the output is ours (CC0-style): no samples are involved.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from ..common import ShowtimeError
from . import SR, dsp, meter
from .dsp import (bell_curve, butter, conv_reverb, env_adsr, env_exp, fade, fm_tone, key_note, midi_to_hz,
                  mix_at, n, noise, osc, pan, parse_key, resample_varispeed, resonator, rng, softclip,
                  supersaw, svf, t_axis, to_stereo, widen)

CATEGORY_LEVEL = {"ui": -24.0, "foley": -22.0, "fx": -20.0, "transition": -18.0, "musical": -16.0,
                  "impact": -14.0, "ambience": -32.0}
# sample-peak caps (dBFS): very short, peaky sounds (clicks, typing) reach these before their loudness
# target, which keeps them subtle next to voice (UI ticks should sit well under the narration)
CATEGORY_PEAK = {"ui": -8.0, "foley": -6.0, "fx": -4.0, "transition": -3.0, "musical": -2.0,
                 "impact": -1.0, "ambience": -6.0}


class Spec:
    def __init__(self, fn: Callable, kind: str, category: str, dur: float, dur_range: Tuple[float, float],
                 tonal: bool, doc: str, tags: List[str]):
        self.fn, self.kind, self.category, self.dur = fn, kind, category, dur
        self.dur_range, self.tonal, self.doc, self.tags = dur_range, tonal, doc, tags


REGISTRY: Dict[str, Spec] = {}


def sfx(kind: str, category: str, dur: float, dur_range=(0.05, 30.0), tonal: bool = False, tags=()):
    def deco(fn):
        name = fn.__name__.rstrip("_").replace("_", "-")
        doc = (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else name
        REGISTRY[name] = Spec(fn, kind, category, dur, dur_range, tonal, doc, list(tags))
        return fn
    return deco


def _rev(x, t60=1.2, wet=0.2, bright=6000, seed=7):
    return conv_reverb(x, t60=t60, wet=wet, bright=bright, seed=seed)


# ============================================================================ transitions
@sfx("peak", "transition", 1.2, (0.3, 6), tags=["whoosh", "swish", "pass-by", "transition", "air"])
def whoosh(dur, intensity, seed, key, direction=1.0):
    """Air pass-by: band-passed noise sweeping up then down, panned across."""
    r = rng(seed)
    N = n(dur)
    peak = 0.5 + 0.15 * (r.random() - 0.5)
    b = bell_curve(N, peak, 1.6, 1.2)
    lo, hi = 220 + 150 * r.random(), 1800 + 3000 * intensity
    fc = lo * (hi / lo) ** b
    src = 0.65 * noise(N, "pink", r) + 0.35 * noise(N, "white", r)
    body = svf(src, fc, 1.1 + 1.2 * intensity, "bp")
    air = svf(noise(N, "white", r), np.minimum(fc * 2.2, 16000), 0.9, "bp") * 0.3
    x = (body + air) * b ** 1.3
    st = pan(x, direction * np.tanh(4 * (np.linspace(0, 1, N) - peak)) * 0.85)
    return _rev(widen(fade(st, 0.01, 0.02), 9, 0.4), 0.8, 0.12), {}


@sfx("peak", "transition", 1.8, (0.6, 6), tags=["whoosh", "heavy", "cinematic", "transition", "low"])
def whoosh_heavy(dur, intensity, seed, key):
    """Low, heavy cinematic whoosh with a sub-bass body (big camera moves)."""
    r = rng(seed)
    N = n(dur)
    b = bell_curve(N, 0.6, 1.8, 1.4)
    fc = 90 * (1400 / 90) ** b
    body = svf(noise(N, "brown", r), fc, 1.4, "bp") * 1.6 + svf(noise(N, "pink", r), fc * 3, 1.0, "bp") * 0.5
    tt = np.arange(N) / SR
    sub = np.sin(2 * np.pi * np.cumsum(40 + 30 * b) / SR) * b ** 2 * 0.5 * intensity
    x = (body + sub) * b ** 1.2
    st = pan(x, np.tanh(3 * (tt / dur - 0.6)) * 0.6)
    return _rev(widen(fade(st, 0.02, 0.03), 14, 0.5), 1.6, 0.18, 3000), {}


@sfx("end", "transition", 0.45, (0.1, 3), tags=["swoosh", "whoosh-in", "transition", "rise"])
def swoosh_in(dur, intensity, seed, key):
    """Short fast rising swoosh that lands on its last sample."""
    r = rng(seed)
    N = n(dur)
    tt = np.linspace(0, 1, N)
    e = tt ** 2.5
    fc = 400 * (6000 * (0.6 + 0.4 * intensity) / 400) ** (tt ** 1.5)
    x = svf(noise(N, "white", r) * 0.6 + noise(N, "pink", r) * 0.4, fc, 1.6, "bp") * e
    return fade(pan(x, -0.6 + 1.2 * tt), 0.005, 0.004), {"hit": dur}


@sfx("onset", "transition", 0.6, (0.15, 3), tags=["swoosh", "whoosh-out", "transition", "exit"])
def swoosh_out(dur, intensity, seed, key):
    """Short falling swoosh that starts on the hit (exits, dismissals)."""
    r = rng(seed)
    N = n(dur)
    tt = np.linspace(0, 1, N)
    k = min(N, n(0.01))
    e = np.concatenate([np.linspace(0, 1, k), (1 - tt[k:]) ** 2.2])[:N]
    fc = 6000 * (300 / 6000) ** (tt ** 0.7)
    x = svf(noise(N, "white", r), fc, 1.5, "bp") * e
    return _rev(pan(x, 0.6 - 1.2 * tt), 0.6, 0.1), {}


@sfx("end", "transition", 3.0, (0.5, 16), tonal=True, tags=["riser", "build", "tension", "transition", "uplifter"])
def riser(dur, intensity, seed, key):
    """Tension riser: noise sweep, supersaw pitch-up and accelerating tremolo; lands at the end."""
    r = rng(seed)
    N = n(dur)
    tt = np.linspace(0, 1, N)
    root = key_note(key, 3)
    semis = -5 + (12 + 12 * intensity) * tt ** 1.8
    f = midi_to_hz(root) * 2 ** (semis / 12)
    saw = supersaw(f, N, 7, 22, r)
    cut = 300 * (9000 / 300) ** (tt ** 1.5)
    saw = svf(saw, cut, 1.3, "lp")
    nz = svf(noise(N, "white", r), 400 * (12000 / 400) ** tt, 1.0, "bp")
    trem_rate = 4 + 18 * tt ** 2
    trem = 0.75 + 0.25 * np.sin(2 * np.pi * np.cumsum(trem_rate) / SR)
    amp = (0.03 + 0.97 * tt ** 2.2) * trem
    x = (saw * 0.55 + to_stereo(nz) * 0.45) * amp[:, None]
    x = fade(widen(x, 11, 0.5), 0.05, 0.003)
    y = conv_reverb(x, t60=1.4, wet=0.2, seed=seed, tail=False)
    return y, {"hit": dur}


@sfx("end", "transition", 2.5, (0.5, 16), tags=["riser", "noise", "build", "sweep", "transition"])
def noise_riser(dur, intensity, seed, key):
    """Filtered white-noise sweep that opens up into the hit (EDM-style uplifter)."""
    r = rng(seed)
    N = n(dur)
    tt = np.linspace(0, 1, N)
    fc = 200 * (14000 / 200) ** (tt ** (1.6 - 0.6 * intensity))
    x = svf(noise(N, "white", r), fc, 2.5, "bp") * 0.7 + svf(noise(N, "pink", r), fc * 0.5, 1.2, "lp") * 0.4
    x = x * (0.02 + 0.98 * tt ** 2.0)
    st = widen(to_stereo(x), 8, 0.7)
    return fade(st, 0.03, 0.003), {"hit": dur}


@sfx("onset", "transition", 2.5, (0.5, 10), tonal=True, tags=["downlifter", "fall", "release", "transition"])
def downlifter(dur, intensity, seed, key):
    """Falling noise and pitch after a drop or into a calm section."""
    r = rng(seed)
    N = n(dur)
    tt = np.linspace(0, 1, N)
    e = env_exp(N, 0.005, dur * 0.9)
    nz = svf(noise(N, "white", r), 9000 * (150 / 9000) ** (tt ** 0.6), 1.3, "bp")
    f = midi_to_hz(key_note(key, 6)) * 2 ** (-36 * tt ** 0.7 / 12)
    tone = butter(supersaw(f, N, 5, 15, r), 5000, "low", 2)
    x = (to_stereo(nz) * 0.6 + tone * 0.4 * intensity) * e[:, None]
    return _rev(widen(x), 2.0, 0.25), {}


@sfx("end", "transition", 2.0, (0.4, 8), tags=["reverse-cymbal", "swell", "transition", "cymbal", "suck"])
def reverse_cymbal(dur, intensity, seed, key):
    """Metallic cymbal played backwards: swells into the hit."""
    r = rng(seed)
    N = n(dur)
    freqs = np.array([205.3, 304.4, 369.6, 522.7, 540.0, 800.0]) * 1.6
    metal = sum(osc("square", f * (1 + r.uniform(-.004, .004)), N, r.uniform(0, 6.28)) for f in freqs)
    metal = butter(butter(metal, 3500, "high", 4), 13000, "low", 2)
    nz = butter(noise(N, "white", r), 3000, "high", 2) * 0.7 + butter(noise(N, "pink", r), [1500, 6000], "band", 2) * 0.3
    body = butter(noise(N, "pink", r), [400, 2500], "band", 2) * 0.25
    e = env_exp(N, 0.002, dur * 1.1)
    x = (metal * 0.3 + nz * 0.6 + body) * e
    st = conv_reverb(widen(to_stereo(x), 7, 0.8), t60=1.2, wet=0.35, bright=11000, seed=seed, tail=False)
    st = st[::-1].copy()
    return fade(st, 0.05, 0.002), {"hit": len(st) / SR}


@sfx("end", "transition", 3.0, (0.8, 12), tonal=True, tags=["swell", "pad", "build", "transition", "tonal"])
def swell(dur, intensity, seed, key):
    """Tonal pad swell (root, fifth, third) with an opening filter, peaking at the end."""
    r = rng(seed)
    N = n(dur)
    tt = np.linspace(0, 1, N)
    pc, mode = parse_key(key)
    third = 3 if mode == "minor" else 4
    notes = [48 + pc, 55 + pc, 60 + pc, 60 + pc + third, 67 + pc]
    x = sum(supersaw(midi_to_hz(m), N, 5, 14, r) for m in notes) / len(notes)
    x = svf(x, 250 * (7000 / 250) ** (tt ** 1.6), 0.9, "lp")
    x = x * (tt ** 2.4)[:, None]
    return conv_reverb(fade(x, 0.02, 0.004), t60=2.2, wet=0.3, seed=seed, tail=False), {"hit": dur}


@sfx("end", "transition", 1.5, (0.4, 6), tags=["reverse", "reverse-hit", "suck", "transition", "cinematic"])
def reverse_hit(dur, intensity, seed, key):
    """A reversed boom tail sucking into the hit point (pairs with an impact)."""
    r = rng(seed)
    N = n(dur)
    tt = np.arange(N) / SR
    body = butter(noise(N, "brown", r), 400, "low", 2) * env_exp(N, 0.001, dur * 0.8)
    crack = butter(noise(N, "white", r), 2000, "high", 2) * env_exp(N, 0.0005, 0.15)
    sub = np.sin(2 * np.pi * np.cumsum(35 + 60 * np.exp(-tt / 0.08)) / SR) * env_exp(N, 0.001, dur)
    x = to_stereo(body + crack * 0.4 + sub * 0.8 * intensity)
    x = conv_reverb(x, t60=max(0.8, dur), wet=0.5, bright=3500, seed=seed, tail=False)
    y = x[::-1].copy()
    return fade(y, 0.03, 0.002), {"hit": dur}


@sfx("end", "transition", 1.2, (0.4, 4), tags=["rewind", "tape", "vhs", "transition", "retro"])
def tape_rewind(dur, intensity, seed, key):
    """Fast tape rewind chatter (warbling pitched noise) that stops on the hit."""
    r = rng(seed)
    N = n(dur)
    tt = np.linspace(0, 1, N)
    f = 900 + 2500 * tt ** 1.5 + 300 * np.sin(2 * np.pi * 23 * tt * dur)
    chat = svf(noise(N, "white", r), f, 6.0, "bp") * 1.5
    tone = osc("saw", 300 + 1800 * tt, N) * 0.15
    grain = (r.random(N) < 0.02 * (1 + 3 * tt)) * r.standard_normal(N) * 0.5
    x = (chat + tone + grain) * (0.4 + 0.6 * tt)
    return fade(pan(x.astype(np.float32), 0.2 * np.sin(2 * np.pi * 3 * tt)), 0.02, 0.003), {"hit": dur}


# ============================================================================ impacts
@sfx("onset", "impact", 2.4, (0.4, 8), tags=["impact", "hit", "boom", "cinematic", "reveal"])
def impact(dur, intensity, seed, key):
    """Cinematic hit: pitched sub sweep, noise crack, low body and a big room."""
    r = rng(seed)
    N = n(dur)
    tt = np.arange(N) / SR
    f = 32 + 70 * np.exp(-tt / 0.06)
    sub = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_exp(N, 0.001, min(1.8, dur))
    body = butter(noise(N, "brown", r), 250, "low", 2) * env_exp(N, 0.001, 0.5) * 1.5
    crack = butter(noise(N, "white", r), 1500, "high", 2) * env_exp(N, 0.0005, 0.06)
    x = softclip(sub + body * 0.6 + crack * (0.3 + 0.4 * intensity), 1.5 + intensity)
    st = conv_reverb(to_stereo(x), t60=min(2.4, dur), wet=0.3, bright=4000, seed=seed, tail=False)
    return fade(st, 0.0005, 0.05), {}


@sfx("onset", "impact", 3.0, (0.8, 10), tags=["boom", "sub", "trailer", "low", "impact"])
def boom(dur, intensity, seed, key):
    """Deep trailer boom: long sub decay and dark rumble, no crack."""
    r = rng(seed)
    N = n(dur)
    tt = np.arange(N) / SR
    f = 28 + 45 * np.exp(-tt / 0.12)
    sub = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_exp(N, 0.003, dur * 0.9)
    rumble = butter(noise(N, "brown", r), 120, "low", 4) * env_exp(N, 0.005, dur * 0.7) * 2.0
    x = softclip(sub * 1.2 + rumble * 0.7, 1.0 + 1.5 * intensity)
    return conv_reverb(to_stereo(x), t60=min(3.0, dur), wet=0.25, bright=1500, seed=seed, tail=False), {}


@sfx("onset", "impact", 2.5, (0.8, 8), tonal=True, tags=["braam", "brass", "trailer", "horn", "epic"])
def braam(dur, intensity, seed, key):
    """Trailer 'braam': detuned low brass-like saw stack with a growling filter."""
    r = rng(seed)
    N = n(dur)
    tt = np.arange(N) / SR
    root = key_note(key, 2)
    x = np.zeros((N, 2), np.float32)
    for m, g in ((root, 1.0), (root + 12, 0.6), (root + 7, 0.35), (root - 12, 0.5)):
        x += supersaw(midi_to_hz(m), N, 7, 25, r) * g
    cut = 180 + (1600 + 1400 * intensity) * env_exp(N, 0.04, dur * 0.8) + 60 * np.sin(2 * np.pi * 6 * tt)
    x = svf(x, cut, 2.2, "lp")
    x = softclip(x * env_adsr(N, 0.02, 0.4, 0.7, dur * 0.5)[:, None] * 1.8, 1.6)
    return conv_reverb(x, t60=2.0, wet=0.3, bright=3000, seed=seed, tail=False), {}


@sfx("onset", "impact", 2.0, (0.3, 6), tags=["sub-drop", "808", "bass-drop", "low", "impact"])
def sub_drop(dur, intensity, seed, key):
    """Falling sine sub-bass (saturated so small speakers still hear it)."""
    N = n(dur)
    tt = np.linspace(0, 1, N)
    f = 110 * (28 / 110) ** (tt ** 0.6)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_exp(N, 0.002, dur * 1.05)
    return to_stereo(fade(softclip(x, 1 + 2 * intensity), 0.001, 0.02)), {}


@sfx("onset", "impact", 0.3, (0.08, 1.5), tags=["thock", "wood", "knock", "land", "text"])
def thock(dur, intensity, seed, key, pitch=190.0):
    """Woody knock for text or cards landing."""
    r = rng(seed)
    N = n(dur)
    tt = np.arange(N) / SR
    p = pitch * (0.9 + 0.2 * r.random())
    f = p * (1 + 0.6 * np.exp(-tt / 0.008))
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_exp(N, 0.0005, 0.12)
    knock = resonator(noise(N, "white", r), p * 6.3, 6) * env_exp(N, 0.0003, 0.03)
    return to_stereo(fade(tone + knock * 0.8, 0.0003, 0.01)), {}


@sfx("onset", "impact", 0.5, (0.15, 2), tags=["punch", "hit", "slam", "body"])
def punch(dur, intensity, seed, key):
    """Short, punchy body hit (kick + snap) for slams and stamps."""
    r = rng(seed)
    N = n(dur)
    tt = np.arange(N) / SR
    kick = np.sin(2 * np.pi * np.cumsum(55 + 140 * np.exp(-tt / 0.02)) / SR) * env_exp(N, 0.0005, 0.25)
    snap = butter(noise(N, "white", r), [1200, 7000], "band", 2) * env_exp(N, 0.0003, 0.05)
    x = softclip(kick * 1.2 + snap * (0.3 + 0.4 * intensity), 2.0)
    return conv_reverb(to_stereo(x), t60=0.4, wet=0.12, seed=seed, tail=False), {}


@sfx("onset", "impact", 2.0, (0.3, 5), tags=["metal", "clang", "hit", "anvil", "industrial"])
def metal_hit(dur, intensity, seed, key):
    """Metallic clang (inharmonic partials) with a short attack burst."""
    r = rng(seed)
    N = n(dur)
    tt = np.arange(N) / SR
    f0 = 180 + 120 * r.random()
    x = np.zeros(N)
    for ratio, amp, dec in ((1.0, 1.0, 0.6), (2.76, 0.6, 0.35), (5.4, 0.4, 0.2), (8.93, 0.25, 0.12), (3.9, 0.3, 0.3)):
        x += amp * np.sin(2 * np.pi * f0 * ratio * tt + r.uniform(0, 6.28)) * np.exp(-tt / (dur * dec))
    x += butter(noise(N, "white", r), 2500, "high", 2) * env_exp(N, 0.0003, 0.04) * 0.8 * intensity
    x *= np.minimum(1, tt / 0.0005)
    return conv_reverb(widen(to_stereo(x.astype(np.float32) / 2), 5, 0.4), t60=1.2, wet=0.25, seed=seed, tail=False), {}


# ============================================================================ UI
@sfx("onset", "ui", 0.04, (0.01, 0.3), tags=["click", "ui", "tap", "button"])
def click(dur, intensity, seed, key, pitch=3200.0):
    """Crisp UI click."""
    r = rng(seed)
    N = n(dur)
    p = pitch * (0.85 + 0.3 * r.random())
    x = resonator(noise(N, "white", r), p, 4) * env_exp(N, 0.0002, 0.012)
    x += np.sin(2 * np.pi * p * 0.5 * t_axis(dur)) * env_exp(N, 0.0002, 0.008) * 0.5
    return to_stereo(fade(x, 0.0002, 0.003)), {}


@sfx("onset", "ui", 0.06, (0.02, 0.3), tags=["tick", "clock", "ui", "count"])
def tick(dur, intensity, seed, key):
    """Clock tick: two metallic resonances."""
    r = rng(seed)
    N = n(dur)
    ex = noise(N, "white", r) * env_exp(N, 0.0001, 0.004)
    x = resonator(ex, 2400, 25) + 0.6 * resonator(ex, 5900, 30) + 0.3 * ex
    x = x * env_exp(N, 0.0001, 0.05)
    return to_stereo(fade(x, 0.0001, 0.005)), {}


@sfx("onset", "ui", 0.12, (0.04, 0.5), tonal=True, tags=["pop", "bubble", "ui", "appear"])
def pop(dur, intensity, seed, key, pitch=None):
    """Bubble pop: a sine with a fast upward glide and a tiny click."""
    r = rng(seed)
    N = n(dur)
    tt = np.arange(N) / SR
    p0 = pitch or float(midi_to_hz(key_note(key, 5, int(r.integers(0, 5)))))
    f = p0 * (0.55 + 0.9 * (1 - np.exp(-tt / 0.02)))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_exp(N, 0.001, 0.07)
    x += butter(noise(N, "white", r), 3000, "high", 2) * env_exp(N, 0.0002, 0.004) * 0.3
    return to_stereo(fade(x, 0.0005, 0.01)), {}


@sfx("onset", "ui", 0.12, (0.05, 0.4), tags=["toggle", "switch", "ui", "on-off"])
def toggle(dur, intensity, seed, key):
    """Two-part switch toggle (press + latch)."""
    r = rng(seed)
    N = n(dur)
    out = np.zeros(N, np.float32)
    for at, p, g in ((0.0, 2600, 1.0), (0.035, 4100, 0.7)):
        k = n(0.04)
        ex = noise(k, "white", r) * env_exp(k, 0.0001, 0.006)
        c = resonator(ex, p * (0.9 + 0.2 * r.random()), 8) + ex * 0.2
        s = n(at) if at else 0
        e = min(N, s + k)
        out[s:e] += c[: e - s] * g
    return to_stereo(fade(out, 0.0002, 0.005)), {}


def _keyclick(r, heavy=False):
    N = n(0.09)
    down = butter(noise(N, "white", r), [2500, 7000], "band", 2) * env_exp(N, 0.0002, 0.006)
    body_f = r.uniform(380, 650) * (0.7 if heavy else 1.0)
    clack = resonator(noise(N, "white", r), body_f, 5) * env_exp(N, 0.0005, 0.035)
    off = int(r.uniform(0.006, 0.012) * SR)
    x = down * r.uniform(0.6, 1.0)
    x[off:] += clack[: N - off] * (1.4 if heavy else 1.0)
    return fade(x, 0.0002, 0.01)


@sfx("onset", "ui", 0.09, (0.05, 0.3), tags=["keyclick", "keyboard", "key", "typing"])
def keyclick(dur, intensity, seed, key):
    """One keyboard keystroke."""
    return to_stereo(_keyclick(rng(seed))), {}


@sfx("onset", "ui", 2.0, (0.3, 30), tags=["typing", "keyboard", "keys", "code"])
def typing(dur, intensity, seed, key, cps=None):
    """Keyboard typing bed; meta.events lists each keystroke time (for text sync)."""
    r = rng(seed)
    cps = cps or (6 + 6 * intensity)
    out = np.zeros((n(dur + 0.1), 2), np.float32)
    t, events = 0.01, []
    while t < dur:
        heavy = r.random() < 0.12
        k = pan(_keyclick(r, heavy) * r.uniform(0.6, 1.0), r.uniform(-0.3, 0.3))
        mix_at(out, k, int(t * SR))
        events.append(round(t, 4))
        t += r.gamma(4.0, 1 / (4.0 * cps)) + (0.15 if r.random() < 0.06 else 0)
    return out[: n(dur)], {"events": events}


@sfx("onset", "ui", 0.9, (0.3, 3), tonal=True, tags=["notification", "chime", "message", "ui", "alert"])
def notification(dur, intensity, seed, key):
    """Two-note soft chime in key (fifth then octave)."""
    a = float(midi_to_hz(key_note(key, 5, 4)))
    b = float(midi_to_hz(key_note(key, 6, 0)))
    out = np.zeros(n(dur), np.float32)
    out += fm_tone(a, dur, 1.5, 1.0, 0.5)[: len(out)]
    s = n(0.11)
    out[s:] += fm_tone(b, dur, 1.5, 1.0, 0.6)[: len(out) - s]
    return _rev(widen(fade(out * 0.5, 0.001, 0.05), 8, 0.4), 1.0, 0.16), {}


@sfx("onset", "ui", 1.1, (0.4, 3), tonal=True, tags=["success", "ta-da", "positive", "complete", "ui"])
def success(dur, intensity, seed, key):
    """Ascending arpeggio 'ta-da' (marimba-like FM)."""
    out = np.zeros(n(dur), np.float32)
    for i, deg in enumerate([0, 2, 4, 7]):
        f = float(midi_to_hz(key_note(key, 5, deg)))
        s = n(0.075 * i) if i else 0
        tone = fm_tone(f, dur, 3.0, 4.0, 0.35 + 0.15 * (i == 3), 0.02)
        out[s:] += tone[: len(out) - s] * (0.8 + 0.2 * i / 3)
    return _rev(widen(fade(out * 0.4, 0.001, 0.05)), 1.0, 0.18), {}


@sfx("onset", "ui", 0.45, (0.2, 1.5), tonal=True, tags=["error", "fail", "wrong", "negative", "ui"])
def error(dur, intensity, seed, key):
    """Two soft descending low notes: an unmistakable (but not harsh) 'nope'."""
    out = np.zeros(n(dur), np.float32)
    root = key_note(key, 3)
    for i, m in enumerate([root + 6, root]):
        s, d = n(0.13 * i), 0.14 if i == 0 else 0.28
        N = n(d)
        x = osc("square", float(midi_to_hz(m)), N) * 0.5 + osc("triangle", float(midi_to_hz(m)) * 1.003, N) * 0.5
        x = butter(x, 1200, "low", 2) * env_adsr(N, 0.004, 0.05, 0.6, 0.06)
        e = min(len(out), s + N)
        out[s:e] += x[: e - s]
    return to_stereo(fade(out * 0.5, 0.001, 0.02)), {}


@sfx("onset", "ui", 1.2, (0.3, 4), tonal=True, tags=["ding", "bell", "ui", "correct", "counter"])
def ding(dur, intensity, seed, key):
    """Single bright ding (FM bell on the key's third/root)."""
    f = float(midi_to_hz(key_note(key, 6, 2 if intensity > 0.5 else 0)))
    x = fm_tone(f, dur, 2.0, 3.5, dur * 0.45, 0.05) + fm_tone(f * 2, dur, 0.5, 1.0, dur * 0.2, 0.05) * 0.2
    return _rev(widen(fade(x * 0.5, 0.0005, 0.05), 6, 0.3), 1.2, 0.18), {}


@sfx("onset", "ui", 3.0, (0.5, 8), tonal=True, tags=["bell", "church", "tonal", "reveal"])
def bell(dur, intensity, seed, key, octave=5):
    """Inharmonic tubular-style bell tuned to the key root."""
    f0 = float(midi_to_hz(key_note(key, octave)))
    N = n(dur)
    tt = np.arange(N) / SR
    parts = [(0.56, 1.0, 1.0), (0.56 * 1.0018, 0.67, 0.9), (0.92, 1.0, 0.65), (0.92 * 1.0017, 1.8, 0.55),
             (1.19, 2.67, 0.325), (1.7, 1.67, 0.35), (2.0, 1.46, 0.25), (2.74, 1.33, 0.2),
             (3.0, 1.33, 0.15), (3.76, 1.0, 0.1), (4.07, 1.33, 0.075)]
    x = np.zeros(N)
    for ratio, amp, dec in parts:
        x += amp * np.sin(2 * np.pi * f0 * 2 * ratio * tt) * np.exp(-6.9 * tt / (dur * dec))
    x *= np.minimum(1, tt / 0.001)
    return _rev(widen(fade(x.astype(np.float32) / 6, 0.0005, 0.1), 6, 0.3), 1.5, 0.18), {}


@sfx("onset", "ui", 2.5, (0.5, 6), tonal=True, tags=["chime", "tubular", "tonal", "soft"])
def chime(dur, intensity, seed, key):
    """Tubular chime on the key's fifth."""
    f0 = float(midi_to_hz(key_note(key, 6, 4)))
    N = n(dur)
    tt = np.arange(N) / SR
    x = sum(a * np.sin(2 * np.pi * f0 * p * tt) * np.exp(-tt / (dur * d))
            for p, a, d in [(1, 1, .35), (2.76, .5, .2), (5.40, .25, .1), (8.93, .12, .05)])
    x *= np.minimum(1, tt / 0.0008)
    return _rev(widen(fade(x.astype(np.float32) / 2, 0.0005, 0.1)), 1.6, 0.2), {}


@sfx("peak", "ui", 1.6, (0.4, 5), tonal=True, tags=["shimmer", "sparkle", "magic", "glitter"])
def shimmer(dur, intensity, seed, key):
    """Magic sparkle: many high pentatonic pings, density peaking mid-way."""
    r = rng(seed)
    pc, mode = parse_key(key)
    penta = [0, 2, 4, 7, 9] if mode == "major" else [0, 3, 5, 7, 10]
    out = np.zeros((n(dur), 2), np.float32)
    count = int((30 + 50 * intensity) * dur / 1.6)
    for t0 in np.sort(r.beta(2.2, 2.0, count) * dur * 0.85):
        m = 12 * int(r.integers(7, 9)) + pc + penta[int(r.integers(0, 5))]
        d = r.uniform(0.15, 0.4)
        p = fm_tone(float(midi_to_hz(m)), d, 0.8, 3.5, d * 0.5, 0.02, 0.0008) * r.uniform(0.3, 1.0)
        mix_at(out, pan(p, r.uniform(-0.9, 0.9)), int(t0 * SR))
    return conv_reverb(out * 0.25, t60=1.6, wet=0.45, bright=12000, seed=seed, tail=False), {}


@sfx("end", "ui", 1.0, (0.3, 3), tonal=True, tags=["sparkle", "rise", "magic", "reveal", "glitter"])
def sparkle_up(dur, intensity, seed, key):
    """Rising glitter arpeggio that lands on the hit (reveals, 'ta-da' builds)."""
    pc, mode = parse_key(key)
    penta = [0, 2, 4, 7, 9] if mode == "major" else [0, 3, 5, 7, 10]
    out = np.zeros((n(dur + 0.4), 2), np.float32)
    steps = int(10 + 14 * intensity)
    for i in range(steps):
        frac = i / (steps - 1)
        t0 = dur * (frac ** 0.8) - 0.005
        m = 72 + pc + 12 * (i // 5) + penta[i % 5]
        p = fm_tone(float(midi_to_hz(min(m, 108))), 0.3, 0.8, 3.5, 0.18, 0.02, 0.0008) * (0.4 + 0.6 * frac)
        mix_at(out, pan(p, -0.7 + 1.4 * frac), int(max(0.0, t0) * SR))
    y = conv_reverb(out * 0.3, t60=1.2, wet=0.35, bright=12000, seed=seed, tail=False)
    return y, {"hit": dur}


@sfx("onset", "ui", 0.7, (0.3, 2), tonal=True, tags=["coin", "reward", "retro", "game", "pickup"])
def coin(dur, intensity, seed, key):
    """Retro coin pickup: two quick square notes (fourth up)."""
    out = np.zeros(n(dur), np.float32)
    root = key_note(key, 6, 4)
    for i, m in enumerate((root, root + 5)):
        s = n(0.07 * i)
        N = n(0.06 if i == 0 else dur - 0.07)
        x = osc("square", float(midi_to_hz(m)), N) * env_exp(N, 0.001, 0.08 if i == 0 else dur * 0.6)
        e = min(len(out), s + N)
        out[s:e] += x[: e - s]
    return to_stereo(fade(butter(out * 0.35, 9000, "low", 2), 0.0005, 0.02)), {}


@sfx("onset", "ui", 0.8, (0.3, 2.5), tonal=True, tags=["power-up", "level-up", "retro", "positive", "game"])
def power_up(dur, intensity, seed, key):
    """Rising chiptune arpeggio sweep (power-up / unlock)."""
    N = n(dur)
    tt = np.linspace(0, 1, N)
    pc, sc = dsp.scale_of(key)
    steps = np.floor(tt * 16).astype(int)
    notes = 60 + pc + np.array([sc[s % 7] + 12 * (s // 7) for s in steps])
    f = midi_to_hz(notes) * (1 + 0.02 * np.sin(2 * np.pi * 30 * tt))
    x = osc("pulse", f, N, pw=0.25) * 0.4 * env_adsr(N, 0.005, 0.1, 0.9, 0.1)
    return to_stereo(fade(butter(x, 8000, "low", 2), 0.001, 0.02)), {}


@sfx("onset", "ui", 0.8, (0.3, 2.5), tonal=True, tags=["power-down", "shutdown", "retro", "negative", "game"])
def power_down(dur, intensity, seed, key):
    """Falling pitch sweep with slowing vibrato (power-down / disable)."""
    N = n(dur)
    tt = np.linspace(0, 1, N)
    f0 = float(midi_to_hz(key_note(key, 5)))
    f = f0 * 2 ** (-24 * tt ** 1.3 / 12) * (1 + 0.03 * np.sin(2 * np.pi * (12 - 8 * tt) * tt * dur))
    x = osc("triangle", f, N) * 0.6 + osc("square", f, N) * 0.2
    x = x * env_adsr(N, 0.005, 0.1, 0.8, dur * 0.3)
    return to_stereo(fade(butter(x, 6000, "low", 2), 0.001, 0.02)), {}


@sfx("onset", "ui", 0.2, (0.08, 0.6), tonal=True, tags=["beep", "countdown", "timer", "ui"])
def countdown_beep(dur, intensity, seed, key):
    """Clean sine beep (countdowns, timers); high intensity = the final 'go' beep an octave up."""
    N = n(dur)
    f = float(midi_to_hz(key_note(key, 6 if intensity < 0.8 else 7)))
    tt = np.arange(N) / SR
    x = (np.sin(2 * np.pi * f * tt) + 0.2 * np.sin(4 * np.pi * f * tt)) * env_adsr(N, 0.003, 0.02, 0.8, 0.03)
    return to_stereo(fade(x.astype(np.float32) * 0.5, 0.002, 0.01)), {}


# ============================================================================ foley-ish
@sfx("onset", "foley", 0.35, (0.2, 1), tags=["camera", "shutter", "photo", "screenshot"])
def camera_shutter(dur, intensity, seed, key):
    """Camera shutter: mirror slap, curtain snap, mirror return."""
    r = rng(seed)
    out = np.zeros(n(dur), np.float32)
    for at, bright, body, g in [(0.0, 5000, 140, 1.0), (0.045, 7500, 220, 0.8), (0.11, 4000, 120, 0.6)]:
        N = n(0.08)
        ex = noise(N, "white", r) * env_exp(N, 0.0002, 0.012)
        x = butter(ex, [bright * 0.4, min(bright * 2, 20000)], "band", 2) + resonator(ex, 3200, 20) * 0.3
        x += np.sin(2 * np.pi * body * t_axis(0.08)) * env_exp(N, 0.0005, 0.03) * 0.5
        s = n(at) if at else 0
        e = min(len(out), s + N)
        out[s:e] += x[: e - s] * g
    return to_stereo(fade(out, 0.0002, 0.01)), {}


@sfx("onset", "foley", 1.6, (0.8, 3), tags=["cash-register", "ka-ching", "money", "sale", "price"])
def cash_register(dur, intensity, seed, key):
    """'Ka-ching': drawer rattle, then a bright bell (the hit is the bell)."""
    r = rng(seed)
    out = np.zeros(n(dur), np.float32)
    for i in range(6):
        N = n(0.03)
        c = resonator(noise(N, "white", r), r.uniform(1500, 3500), 8) * env_exp(N, 0.0002, 0.01)
        s = n(0.02 * i + r.uniform(0, 0.005))
        out[s: s + N] += c * 0.5
    N = n(0.15)
    out[n(0.1): n(0.1) + N] += np.sin(2 * np.pi * 90 * t_axis(0.15)) * env_exp(N, 0.001, 0.1) * 0.7
    bell_at = 0.16
    N = len(out) - n(bell_at)
    tt = np.arange(N) / SR
    b = sum(a * np.sin(2 * np.pi * 2093.0 * p * tt) * np.exp(-tt / d) for p, a, d in
            [(1, 1, .5), (2.32, .5, .25), (4.25, .3, .12), (1.003, .8, .45)])
    b *= (1 + 0.15 * np.sin(2 * np.pi * 7 * tt)) * np.minimum(1, tt / 0.0008)
    out[n(bell_at):] += b * 0.45
    return _rev(widen(fade(out, 0.0002, 0.05), 6, 0.3), 0.8, 0.12), {"hit": bell_at}


@sfx("onset", "foley", 3.4, (1, 30), tags=["heartbeat", "pulse", "tension", "suspense"])
def heartbeat(dur, intensity, seed, key, bpm=None):
    """Lub-dub heartbeat; intensity raises the rate (60-110 bpm)."""
    bpm = bpm or (60 + 50 * intensity)
    out = np.zeros(n(dur), np.float32)
    period, ev = 60 / bpm, []
    t = 0.0
    while t + 0.4 < dur:
        for off, f, g in [(0.0, 55, 1.0), (0.2, 65, 0.7)]:
            N = n(0.18)
            tt = np.arange(N) / SR
            fr = f * (1 + 0.5 * np.exp(-tt / 0.01))
            x = np.sin(2 * np.pi * np.cumsum(fr) / SR) * env_exp(N, 0.004, 0.12) * g
            s = n(t + off)
            e = min(len(out), s + N)
            out[s:e] += x[: e - s]
        ev.append(round(t, 4))
        t += period
    out = softclip(butter(out, 400, "low", 2) * 1.2, 1.5)
    return to_stereo(fade(out, 0.001, 0.05)), {"events": ev}


@sfx("peak", "foley", 0.5, (0.2, 1.5), tags=["paper", "page-turn", "swipe", "card", "slide"])
def paper_swipe(dur, intensity, seed, key):
    """Paper / card slide: dry filtered noise with a crinkle texture."""
    r = rng(seed)
    N = n(dur)
    tt = np.linspace(0, 1, N)
    e = bell_curve(N, 0.4, 1.2, 1.8)
    crinkle = (r.random(N) < 0.01) * r.standard_normal(N) * 0.6
    x = svf(noise(N, "white", r) * 0.6 + crinkle, 2500 + 3000 * e, 0.8, "bp") * e
    return fade(pan(x, -0.3 + 0.6 * tt), 0.005, 0.01), {}


@sfx("onset", "foley", 0.4, (0.15, 1.2), tags=["water-drop", "drip", "plop", "liquid"])
def water_drop(dur, intensity, seed, key):
    """Water drop / plop: resonant upward chirp."""
    r = rng(seed)
    N = n(dur)
    tt = np.arange(N) / SR
    f0 = 700 + 500 * r.random()
    f = f0 * (1 + 1.2 * (1 - np.exp(-tt / 0.012)))
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_exp(N, 0.0008, 0.09)
    x += resonator(noise(N, "white", r) * env_exp(N, 0.0002, 0.003), 3000, 5) * 0.3
    return _rev(to_stereo(fade(x.astype(np.float32), 0.0005, 0.02)), 0.6, 0.15), {}


@sfx("onset", "foley", 4.0, (1, 60), tags=["clock", "ticking", "tick-tock", "time", "deadline"])
def clock_ticking(dur, intensity, seed, key, bpm=60):
    """Tick-tock clock bed (events = tick times)."""
    r = rng(seed)
    out = np.zeros((n(dur), 2), np.float32)
    period = 60.0 / bpm
    t, i, ev = 0.0, 0, []
    while t < dur - 0.05:
        x, _ = tick(0.06, intensity, int(r.integers(1 << 30)), key)
        mix_at(out, pan(x[:, 0] * (1.0 if i % 2 == 0 else 0.7), 0.1 if i % 2 == 0 else -0.1), int(t * SR))
        ev.append(round(t, 4))
        t += period
        i += 1
    return _rev(out, 0.5, 0.1), {"events": ev}


# ============================================================================ fx
@sfx("onset", "fx", 0.6, (0.1, 3), tonal=True, tags=["glitch", "digital", "stutter", "error", "tech"])
def glitch(dur, intensity, seed, key):
    """Digital stutter: bit-crushed slices repeated and scattered in stereo."""
    r = rng(seed)
    pc, _ = parse_key(key)
    srcN = n(0.5)
    src = (osc("square", float(midi_to_hz(60 + pc)), srcN) * 0.4 + osc("saw", float(midi_to_hz(79 + pc)), srcN) * 0.3 +
           noise(srcN, "white", r) * 0.3)
    out = np.zeros((n(dur), 2), np.float32)
    pos = 0
    while pos < len(out):
        L = int(r.choice([0.008, 0.015, 0.03, 0.06]) * SR)
        a = int(r.integers(0, srcN - L))
        sl = src[a: a + L].copy()
        bits = int(r.integers(3, 8))
        sl = np.round(sl * 2 ** bits) / 2 ** bits
        hold = int(r.integers(1, 12))
        sl = np.repeat(sl[::hold], hold)[:L]
        reps = int(r.integers(1, 5))
        chunk = fade(np.tile(fade(sl, 0.0005, 0.0005), reps), 0.0005, 0.0005)
        mix_at(out, pan(chunk * r.uniform(0.4, 1), r.uniform(-0.8, 0.8)), pos)
        pos += len(chunk) + (int(r.integers(0, n(0.02))) if r.random() < 0.3 else 0)
    return fade(out * (0.5 + 0.5 * intensity), 0.001, 0.01), {}


@sfx("onset", "fx", 0.35, (0.1, 1.5), tags=["laser", "zap", "sci-fi", "shoot"])
def laser(dur, intensity, seed, key):
    """Sci-fi laser: FM tone with a fast falling pitch."""
    N = n(dur)
    tt = np.arange(N) / SR
    f = 200 + 3000 * np.exp(-tt / 0.05)
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph + 2.5 * np.sin(ph * 1.5)) * env_exp(N, 0.001, dur)
    return to_stereo(fade(x.astype(np.float32), 0.001, 0.02)), {}


@sfx("onset", "fx", 0.4, (0.1, 1.5), tags=["zap", "electric", "spark", "shock"])
def zap(dur, intensity, seed, key):
    """Electric zap: crackling noise bursts over a buzzing tone."""
    r = rng(seed)
    N = n(dur)
    tt = np.arange(N) / SR
    buzz = osc("saw", 120 * (1 + 0.5 * np.exp(-tt / 0.05)), N) * 0.3
    crackle = (r.random(N) < 0.08) * r.standard_normal(N)
    x = butter(buzz + butter(crackle, 1500, "high", 2), 12000, "low", 2) * env_exp(N, 0.001, dur * 0.8)
    return to_stereo(fade(softclip(x * (1 + intensity), 1.5), 0.001, 0.01)), {}


def tape_stop_fx(x: np.ndarray, stop_time: float = 1.0, curve: float = 1.6) -> np.ndarray:
    """Apply a tape stop (speed and pitch ramp to zero over stop_time) to the END of any audio."""
    x = to_stereo(x)
    Ns = n(stop_time)
    start = max(0, len(x) - int(Ns * 0.55))
    speed = (1 - np.linspace(0, 1, Ns)) ** curve
    tail = resample_varispeed(x[start:], speed)
    return fade(np.concatenate([x[:start], tail]), 0, 0.01)


@sfx("end", "fx", 1.2, (0.4, 3), tonal=True, tags=["tape-stop", "slowdown", "record-stop", "halt"])
def tape_stop(dur, intensity, seed, key):
    """A short synth chord that grinds to a halt (tape stop); the hit is the full stop."""
    r = rng(seed)
    pc, _ = parse_key(key)
    base = sum(supersaw(float(midi_to_hz(48 + pc + i)), n(1.6), 5, 12, r) for i in (0, 7, 12, 16)) / 4
    beat = np.zeros(n(1.6), np.float32)
    for b in range(4):
        k, _ = punch(0.3, 0.6, b, key)
        s = n(b * 0.4)
        e = min(len(beat), s + len(k))
        beat[s:e] += k[: e - s, 0] * 0.5
    y = tape_stop_fx(base * 0.5 + to_stereo(beat), dur)
    return y, {"hit": len(y) / SR}


@sfx("onset", "fx", 0.8, (0.3, 2), tonal=True, tags=["scratch", "vinyl", "dj", "record"])
def vinyl_scratch(dur, intensity, seed, key):
    """Vinyl scratch: a vowel-like tone scrubbed back and forth."""
    r = rng(seed)
    srcN = n(2.0)
    f0 = float(midi_to_hz(key_note(key, 3)))
    v = osc("saw", f0 * (1 + 0.01 * np.sin(2 * np.pi * 5 * t_axis(2.0))), srcN)
    form = sum(resonator(v, f, 8) * g for f, g in [(730, 1), (1090, .5), (2440, .3)])
    src = form / (np.abs(form).max() + 1e-9) + noise(srcN, "pink", r) * 0.15
    N = n(dur)
    tt = np.linspace(0, 1, N)
    speed = 3.5 * np.sin(2 * np.pi * 2.0 * tt) * intensity
    pos = srcN / 2 + np.cumsum(speed)
    x = np.interp(np.clip(pos, 0, srcN - 1), np.arange(srcN), src)
    x *= np.clip(np.abs(speed), 0, 1)
    crackle = (r.random(N) < 0.002) * r.standard_normal(N) * 0.3
    return to_stereo(fade(butter((x + crackle).astype(np.float32), 60, "high", 2), 0.002, 0.01)), {}


@sfx("onset", "fx", 0.5, (0.1, 3), tags=["static", "radio", "noise", "interference", "tv"])
def static_burst(dur, intensity, seed, key):
    """Radio / TV static burst with band-limited crackle."""
    r = rng(seed)
    N = n(dur)
    x = butter(noise(N, "white", r), [500, 7000], "band", 2) * (0.6 + 0.4 * (r.random(N) < 0.5))
    x += (r.random(N) < 0.01) * r.standard_normal(N) * 0.8
    x *= env_adsr(N, 0.003, 0.05, 0.8, min(0.1, dur / 3))
    return widen(to_stereo(fade(x.astype(np.float32), 0.002, 0.01)), 6, 0.6), {}


@sfx("onset", "fx", 2.0, (0.5, 6), tonal=True, tags=["sonar", "ping", "radar", "scan", "submarine"])
def sonar_ping(dur, intensity, seed, key):
    """Sonar ping: pure tone with a long echoey decay."""
    f = float(midi_to_hz(key_note(key, 6)))
    N = n(dur)
    tt = np.arange(N) / SR
    x = np.sin(2 * np.pi * f * tt) * env_exp(N, 0.002, dur * 0.4)
    y = dsp.delay(to_stereo(x.astype(np.float32) * 0.5), 0.28, 0.45, 0.5, taps=5)
    return conv_reverb(y, t60=min(2.5, dur), wet=0.35, bright=5000, seed=seed, tail=False), {}


# ============================================================================ ambience beds
@sfx("onset", "ambience", 10.0, (1, 600), tags=["room-tone", "air", "bed", "ambience", "silence"])
def room_tone(dur, intensity, seed, key):
    """Subtle room tone (so cuts to 'silence' don't sound like dropouts)."""
    r = rng(seed)
    N = n(dur)
    x = butter(noise(N, "pink", r), [60, 4000], "band", 2) * 0.5 + butter(noise(N, "brown", r), 200, "low", 2) * 0.5
    hum = np.sin(2 * np.pi * 50 * np.arange(N) / SR) * 0.01 * intensity
    st = widen(to_stereo(x + hum), 20, 0.9)
    return fade(st, 0.5, 0.5), {}


@sfx("onset", "ambience", 10.0, (1, 600), tags=["wind", "outdoor", "air", "ambience", "gust"])
def wind(dur, intensity, seed, key):
    """Wind bed with slow gusts (band-passed noise with a wandering centre)."""
    r = rng(seed)
    N = n(dur)
    tt = np.arange(N) / SR
    lfo = sum(np.sin(2 * np.pi * f * tt + r.uniform(0, 6.28)) * a for f, a in ((0.07, 1), (0.13, 0.6), (0.31, 0.3)))
    lfo = (lfo - lfo.min()) / (np.ptp(lfo) + 1e-9)
    fc = 250 + 900 * lfo * (0.5 + intensity)
    x = svf(noise(N, "pink", r), fc, 1.5, "bp", block=256) * (0.4 + 0.6 * lfo)
    hi = svf(noise(N, "white", r), fc * 4, 3.0, "bp", block=256) * 0.15 * lfo
    return fade(widen(to_stereo(x + hi), 25, 0.9), 1.0, 1.0), {}


@sfx("onset", "ambience", 10.0, (1, 600), tags=["rain", "weather", "outdoor", "ambience", "calm"])
def rain(dur, intensity, seed, key):
    """Rain bed: dense filtered noise plus individual droplet ticks."""
    r = rng(seed)
    N = n(dur)
    bed = butter(noise(N, "pink", r), [400, 9000], "band", 2) * 0.35
    drops = np.zeros(N, np.float32)
    count = int(dur * (80 + 400 * intensity))
    pos = r.integers(0, max(1, N - 400), count)
    k = n(0.006)
    shape = env_exp(k, 0.0001, 0.004) * r.choice([-1, 1])
    for p_, a in zip(pos, r.uniform(0.05, 0.4, count)):
        drops[p_:p_ + k] += shape * a
    drops = butter(drops, 1500, "high", 2)
    st = widen(to_stereo(bed), 15, 0.9) + pan(drops, r.uniform(-0.6, 0.6))
    return fade(st, 1.0, 1.0), {}


@sfx("onset", "ambience", 10.0, (1, 600), tonal=True, tags=["drone", "tension", "dark", "suspense", "ambience"])
def drone(dur, intensity, seed, key):
    """Dark tension drone in key: slowly beating low fifths with a moving filter."""
    r = rng(seed)
    N = n(dur)
    tt = np.arange(N) / SR
    root = key_note(key, 2)
    x = np.zeros((N, 2), np.float32)
    for m, g in ((root, 1.0), (root + 7, 0.6), (root + 12, 0.4), (root + 13, 0.12 * intensity)):
        x += supersaw(float(midi_to_hz(m)), N, 5, 8, r) * g
    fc = 200 + 500 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.05 * tt + r.uniform(0, 6)))
    x = svf(x, fc, 1.2, "lp", block=128)
    return fade(conv_reverb(x, t60=3.0, wet=0.35, bright=2500, seed=seed, tail=False), 1.5, 1.5), {}


# ============================================================================ musical
@sfx("onset", "musical", 2.5, (0.8, 6), tonal=True, tags=["stinger", "hit", "chord", "reveal", "logo"])
def stinger(dur, intensity, seed, key):
    """Orchestral-ish stinger: impact plus a bright chord stab in key."""
    r = rng(seed)
    N = n(dur)
    hit, _ = impact(dur, intensity, seed, key)
    pc, mode = parse_key(key)
    third = 3 if mode == "minor" else 4
    chord = np.zeros((N, 2), np.float32)
    for m in (48 + pc, 60 + pc, 60 + pc + third, 67 + pc, 72 + pc):
        chord += supersaw(float(midi_to_hz(m)), N, 5, 12, r)
    chord = butter(chord, 5000, "low", 2) * env_exp(N, 0.003, dur * 0.7)[:, None] * 0.35
    y = dsp.pad_to(hit, N) * 0.8 + conv_reverb(chord, t60=2.0, wet=0.35, seed=seed, tail=False)
    return fade(y, 0.0005, 0.05), {}


@sfx("onset", "musical", 2.2, (1.0, 5), tonal=True, tags=["logo", "sting", "jingle", "outro", "brand"])
def logo_sting(dur, intensity, seed, key):
    """Short three-note logo motif resolving to the tonic with a shimmer tail."""
    r = rng(seed)
    out = np.zeros((n(dur), 2), np.float32)
    motifs = [[4, 1, 0], [2, 4, 7], [0, 4, 7], [7, 4, 0], [5, 4, 0]]
    mot = motifs[int(r.integers(0, len(motifs)))]
    for i, deg in enumerate(mot):
        f = float(midi_to_hz(key_note(key, 5, deg)))
        s = n(0.14 * i)
        d = dur - 0.14 * i
        tone = fm_tone(f, d, 2.5, 1.0, 0.5 if i < 2 else d * 0.6, 0.08) + fm_tone(f * 2, d, 1.0, 3.5, 0.3, 0.03) * 0.3
        mix_at(out, pan(tone * (0.7 + 0.15 * i), -0.2 + 0.2 * i), s)
    bass = fm_tone(float(midi_to_hz(key_note(key, 3))), dur - 0.28, 1.0, 1.0, (dur - 0.28) * 0.6, 0.1)
    mix_at(out, to_stereo(bass * 0.6), n(0.28))
    return conv_reverb(out * 0.5, t60=1.8, wet=0.3, seed=seed, tail=False), {"hit": 0.28}


@sfx("end", "musical", 1.0, (0.3, 4), tags=["drum-fill", "snare-roll", "build", "roll", "transition"])
def drum_fill(dur, intensity, seed, key, bpm=120.0):
    """Accelerating snare/tom fill that lands on the hit (the next downbeat)."""
    r = rng(seed)
    out = np.zeros((n(dur), 2), np.float32)
    t, gap, i = 0.0, 60.0 / bpm / 2, 0
    hits = []
    while t < dur - 0.01:
        hits.append(t)
        frac = t / dur
        gap = max(0.03, (60.0 / bpm / 2) * (1 - 0.75 * frac))
        t += gap
        i += 1
    for j, t0 in enumerate(hits):
        N = n(0.25)
        tt = np.arange(N) / SR
        frac = t0 / dur
        body = np.sin(2 * np.pi * (190 - 60 * frac) * tt) * np.exp(-tt / 0.05) * 0.6
        rattle = butter(noise(N, "white", r), 1200, "high", 2) * np.exp(-tt / 0.08)
        x = (body + rattle) * (0.35 + 0.65 * frac) * (0.8 + 0.4 * intensity)
        mix_at(out, pan(x.astype(np.float32), 0.3 * math.sin(j)), int(t0 * SR))
    return conv_reverb(out, t60=0.6, wet=0.15, seed=seed, tail=False), {"hit": dur}


# ============================================================================ measurement / render
def hit_time(x: np.ndarray, kind: str, meta: Optional[dict] = None) -> float:
    """Seconds from the start of `x` to its perceptual hit (see module doc)."""
    meta = meta or {}
    if "hit" in meta:
        return float(meta["hit"])
    mono = np.abs(x).max(axis=1) if x.ndim == 2 else np.abs(x)
    if not mono.size or mono.max() <= 0:
        return 0.0
    hop = n(0.002)
    frames = max(1, len(mono) // hop)
    env = np.sqrt((mono[: frames * hop].reshape(frames, hop) ** 2).mean(1)) + 1e-12
    env_db = 20 * np.log10(env / env.max())
    if kind == "peak":
        sm = np.convolve(env, np.ones(25) / 25, mode="same")
        return int(np.argmax(sm)) * hop / SR
    if kind == "end":
        return len(x) / SR
    return int(np.argmax(env_db > -30)) * hop / SR


def max_momentary(x: np.ndarray) -> float:
    """Max momentary (400 ms) loudness in LUFS; short sounds are padded with silence."""
    y = to_stereo(x)
    if len(y) < n(0.4):
        y = dsp.pad_to(y, n(0.4))
    c = meter.curves(y, SR, hop=0.01)["momentary"]
    return float(c.max()) if c.size else float("-inf")


def level_match(x: np.ndarray, category: str, peak_ceiling_db: Optional[float] = None) -> Tuple[np.ndarray, Dict]:
    """Scale to the category's loudness; never above the category's peak cap."""
    target = CATEGORY_LEVEL.get(category, -20.0)
    if peak_ceiling_db is None:
        peak_ceiling_db = CATEGORY_PEAK.get(category, -1.0)
    if category == "ambience":
        cur = meter.integrated(x)
        if not math.isfinite(cur):
            cur = max_momentary(x)
    else:
        cur = max_momentary(x)
    g = (target - cur) if math.isfinite(cur) else 0.0
    y = x * 10 ** (g / 20)
    pk = float(np.abs(y).max()) if y.size else 0.0
    ceil = 10 ** (peak_ceiling_db / 20)
    limited = False
    if pk > ceil:
        y = y * (ceil / pk)
        limited = True
    return y.astype(np.float32), {"target_lufs": target, "measured_lufs": round(cur, 2) if math.isfinite(cur) else None,
                                  "gain_db": round(g, 2), "peak_limited": limited}


def list_types() -> List[Dict]:
    return [{"type": k, "kind": s.kind, "category": s.category, "default_dur": s.dur,
             "dur_range": list(s.dur_range), "tonal": s.tonal, "tags": s.tags, "description": s.doc}
            for k, s in sorted(REGISTRY.items(), key=lambda kv: (kv[1].category, kv[0]))]


def resolve_type(name: str) -> str:
    key = name.strip().lower().replace("_", "-")
    if key in REGISTRY:
        return key
    for k, s in REGISTRY.items():
        if key in s.tags:
            return k
    raise ShowtimeError("unknown sfx type %r" % name, hint="run `showtime audio sfx-types` for the list")


def render(name: str, dur: Optional[float] = None, intensity: float = 0.7, seed: int = 0, key: str = "C",
           level: bool = True, **extra) -> Tuple[np.ndarray, Dict]:
    """Generate, clean, loudness-match and measure one effect."""
    t = resolve_type(name)
    spec = REGISTRY[t]
    d = spec.dur if dur is None else float(dur)
    lo, hi = spec.dur_range
    if not lo <= d <= hi:
        raise ShowtimeError("%s: duration %.2fs is outside %.2f-%.2fs" % (t, d, lo, hi))
    if not 0.0 <= intensity <= 1.0:
        raise ShowtimeError("intensity must be between 0 and 1")
    parse_key(key)
    x, meta = spec.fn(d, float(intensity), int(seed), key, **extra)
    x = np.nan_to_num(to_stereo(np.asarray(x, dtype=np.float32)))
    # end-synced effects stop exactly on their hit; beds have exactly the requested length
    if spec.kind == "end":
        x = dsp.pad_to(x, n(float(meta.get("hit", d))))
    elif spec.category == "ambience":
        x = dsp.pad_to(x, n(d))
    x = butter(x, 18, "high", 2)
    x = fade(x, 0.0, 0.004)
    lv = {}
    if level:
        x, lv = level_match(x, spec.category)
    hit = hit_time(x, spec.kind, meta)
    out = {"type": t, "kind": spec.kind, "category": spec.category, "duration": round(len(x) / SR, 4),
           "hit": round(float(hit), 4), "hit_frame_30fps": int(round(hit * 30)), "hit_frame_60fps": int(round(hit * 60)),
           "key": key if spec.tonal else None, "intensity": intensity, "seed": seed, "level": lv,
           "peak_dbfs": round(20 * math.log10(float(np.abs(x).max()) + 1e-12), 2)}
    if "events" in meta:
        out["events"] = meta["events"]
    return x, out

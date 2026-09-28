"""Original colour looks as 3D LUTs (.cube), generated procedurally.

No third-party LUT files are shipped or downloaded (their licensing is often
unclear). Each look is a small numpy function of RGB; `ensure(name,
strength)` writes a 33^3 .cube into ~/.showtime/models/luts, with the
strength baked in (identity blended with the look), so applying it is one
`lut3d` filter.

Looks: teal-orange, warm-film, clean-punch, cool-tech, mono-contrast,
bleach, golden-hour, matte, night.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Dict, List

from ..common import ShowtimeError, ensure_dir, paths

import threading

_LOCK = threading.Lock()
LUT_SIZE = 33
LUT_REV = 2

DESCRIPTIONS = {
    "teal-orange": "teal shadows, warm skin/highlights, gentle S-curve (cinematic, popular for talking heads)",
    "warm-film": "lifted blacks, rolled-off highlights, warm and slightly desaturated (nostalgic film)",
    "clean-punch": "more contrast and vibrance, neutral colour (crisp product / tech look)",
    "cool-tech": "cool shadows, neutral skin, restrained saturation (modern tech / corporate)",
    "mono-contrast": "black and white with a firm contrast curve",
    "bleach": "bleach bypass: low saturation, hard contrast (gritty, dramatic)",
    "golden-hour": "warm glow in highlights, soft contrast (lifestyle, sunset feel)",
    "matte": "faded blacks, soft contrast, muted colour (editorial / vlog)",
    "night": "day-for-night: darker, blue, desaturated",
}


def _np():
    import numpy as np
    return np


def _luma(c):
    np = _np()
    return (c @ np.array([0.2126, 0.7152, 0.0722]))[:, None]


def _sig_contrast(x, amount: float):
    """S-curve around 0.5; amount 0 = identity, 1 = strong."""
    np = _np()
    if amount <= 0:
        return x
    a = 1.0 + 9.0 * amount
    s = lambda v: 1.0 / (1.0 + np.exp(-a * (v - 0.5)))  # noqa: E731
    lo, hi = s(0.0), s(1.0)
    return (s(x) - lo) / (hi - lo)


def _sat(c, s: float):
    y = _luma(c)
    return y + (c - y) * s


def _vibrance(c, v: float):
    np = _np()
    mx, mn = c.max(axis=1, keepdims=True), c.min(axis=1, keepdims=True)
    chroma = mx - mn
    y = _luma(c)
    return y + (c - y) * (1.0 + v * (1.0 - np.clip(chroma * 2.0, 0, 1)))


def _split(c, shadows, highlights, balance: float = 0.5):
    np = _np()
    y = _luma(c)
    ws = np.clip(1.0 - y / max(balance, 1e-3), 0, 1) ** 1.5
    wh = np.clip((y - balance) / max(1 - balance, 1e-3), 0, 1) ** 1.5
    return c + ws * np.array(shadows) + wh * np.array(highlights)


def _lift_gain(c, lift: float, gain: float):
    return lift + c * (gain - lift)


def teal_orange(c):
    c = _sig_contrast(c, 0.22)
    c = _split(c, (-0.035, 0.012, 0.045), (0.045, 0.012, -0.035), 0.45)
    return _vibrance(_sat(c, 1.04), 0.10)


def warm_film(c):
    np = _np()
    c = _lift_gain(c, 0.045, 0.955)
    c = _sig_contrast(c, 0.12)
    c = c * np.array([1.025, 1.0, 0.955])
    return _sat(c, 0.88)


def clean_punch(c):
    return _vibrance(_sig_contrast(c, 0.25), 0.14)


def cool_tech(c):
    c = _sig_contrast(c, 0.18)
    c = _split(c, (-0.02, 0.0, 0.035), (-0.005, 0.005, 0.015), 0.5)
    return _sat(c, 0.94)


def mono_contrast(c):
    np = _np()
    y = _sig_contrast(_luma(c), 0.32)
    return np.repeat(y, 3, axis=1)


def bleach(c):
    np = _np()
    y = _luma(c)
    ov = np.where(y < 0.5, 2 * c * y, 1 - 2 * (1 - c) * (1 - y))
    c = 0.45 * c + 0.55 * ov
    return _sat(_sig_contrast(c, 0.2), 0.55)


def golden_hour(c):
    np = _np()
    c = _lift_gain(c, 0.02, 0.99)
    c = _split(c, (0.01, -0.005, 0.02), (0.06, 0.03, -0.045), 0.4)
    c = c * np.array([1.02, 1.0, 0.97])
    return _sat(_sig_contrast(c, 0.08), 1.05)


def matte(c):
    c = _lift_gain(c, 0.075, 0.965)
    return _sat(_sig_contrast(c, 0.06), 0.9)


def night(c):
    np = _np()
    c = _sat(c, 0.45) * 0.62
    c = c * np.array([0.82, 0.95, 1.18])
    return _sig_contrast(c, 0.15)


LOOKS: Dict[str, Callable] = {
    "teal-orange": teal_orange, "warm-film": warm_film, "clean-punch": clean_punch, "cool-tech": cool_tech,
    "mono-contrast": mono_contrast, "bleach": bleach, "golden-hour": golden_hour, "matte": matte, "night": night,
}
ALIASES = {"teal_orange": "teal-orange", "tealorange": "teal-orange", "warm": "warm-film", "film": "warm-film",
           "punch": "clean-punch", "cool": "cool-tech", "mono": "mono-contrast", "bw": "mono-contrast",
           "golden": "golden-hour", "fade": "matte"}


def canonical(name: str) -> str:
    n = name.strip().lower().replace(" ", "-")
    n = ALIASES.get(n, n)
    if n not in LOOKS:
        raise ShowtimeError("unknown look %r" % name, hint="looks: " + ", ".join(LOOKS))
    return n


def lut_dir() -> Path:
    return ensure_dir(paths()["luts"])


def write_cube(path: Path, fn: Callable, strength: float = 1.0, title: str = "") -> Path:
    np = _np()
    n = LUT_SIZE
    r = np.linspace(0.0, 1.0, n)
    b, g, rr = np.meshgrid(r, r, r, indexing="ij")          # red varies fastest in .cube order
    rgb = np.stack([rr, g, b], axis=-1).reshape(-1, 3)
    out = np.clip(fn(rgb.copy()), 0.0, 1.0)
    s = max(0.0, min(1.0, float(strength)))
    out = rgb + (out - rgb) * s
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix="." + path.stem, suffix=".part", dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="ascii", newline="\n") as f:
        f.write('TITLE "%s"\n# showtime look rev %d, strength %.2f\nLUT_3D_SIZE %d\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n'
                % (title or path.stem, LUT_REV, s, n))
        np.savetxt(f, out, fmt="%.6f")
    os.replace(tmp, str(path))
    return path


def ensure(name: str, strength: float = 1.0) -> Path:
    """Path of the .cube for a look at a strength (0..1), creating it once."""
    n = canonical(name)
    s = max(0.0, min(1.0, float(strength)))
    p = lut_dir() / ("%s@%03d.r%d.cube" % (n, int(round(s * 100)), LUT_REV))
    with _LOCK:
        if not p.is_file():
            write_cube(p, LOOKS[n], s, n)
    return p


def cube_filter(path: Path) -> str:
    from ..ff import filter_path
    return "lut3d=file=%s:interp=tetrahedral" % filter_path(path)


def user_lut(path, strength: float = 1.0) -> Path:
    """A user-supplied 3D .cube; strength < 1 is baked in (blend with identity)."""
    import hashlib
    np = _np()
    p = Path(path).expanduser()
    if not p.is_file():
        raise ShowtimeError("LUT file not found: %s" % p)
    s = max(0.0, min(1.0, float(strength)))
    if s >= 0.999:
        return p
    key = hashlib.sha1(p.read_bytes()).hexdigest()[:12]
    out = lut_dir() / ("user-%s@%03d.cube" % (key, int(round(s * 100))))
    if out.is_file():
        return out
    size, lo, hi, rows = None, [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        up = t.upper()
        if up.startswith("LUT_3D_SIZE"):
            size = int(t.split()[1])
        elif up.startswith("LUT_1D_SIZE"):
            raise ShowtimeError("1D LUTs are not supported (%s)" % p.name)
        elif up.startswith("DOMAIN_MIN"):
            lo = [float(v) for v in t.split()[1:4]]
        elif up.startswith("DOMAIN_MAX"):
            hi = [float(v) for v in t.split()[1:4]]
        elif up.startswith("TITLE") or up[0].isalpha():
            continue
        else:
            rows.append([float(v) for v in t.split()[:3]])
    if not size or len(rows) != size ** 3:
        raise ShowtimeError("%s is not a valid 3D .cube LUT" % p.name)
    data = np.array(rows)
    r = np.linspace(0.0, 1.0, size)
    b, g, rr = np.meshgrid(r, r, r, indexing="ij")
    ident = np.stack([rr, g, b], axis=-1).reshape(-1, 3) * (np.array(hi) - np.array(lo)) + np.array(lo)
    mixed = ident + (data - ident) * s
    with open(out, "w", encoding="ascii", newline="\n") as f:
        f.write('TITLE "%s @%d%%"\nLUT_3D_SIZE %d\nDOMAIN_MIN %g %g %g\nDOMAIN_MAX %g %g %g\n'
                % (p.stem, round(s * 100), size, lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]))
        np.savetxt(f, mixed, fmt="%.6f")
    return out


def listing() -> List[Dict[str, str]]:
    return [{"name": k, "description": DESCRIPTIONS[k]} for k in LOOKS]

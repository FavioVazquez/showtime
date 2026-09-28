"""Small mono audio helpers for the voice module (soundfile + scipy).

Everything here is mono float32. Files that soundfile cannot read (mp3, m4a,
video) are decoded with the resolved ffmpeg through a pipe, so Windows paths
and odd characters are passed as plain arguments.
"""
from __future__ import annotations

import os
import subprocess
from math import gcd
from pathlib import Path
from typing import Tuple, Union

import numpy as np

from ..common import ShowtimeError, part_path

PathLike = Union[str, "os.PathLike[str]"]
_SF_EXT = {".wav", ".flac", ".aif", ".aiff", ".ogg", ".w64", ".rf64"}


def read(path: PathLike, sr: int = 0) -> Tuple[np.ndarray, int]:
    """Read any audio as mono float32. sr=0 keeps the file's rate."""
    p = Path(path)
    if not p.is_file():
        raise ShowtimeError("audio file not found: %s" % p)
    x = None
    rate = 0
    if p.suffix.lower() in _SF_EXT:
        try:
            import soundfile as sf
            x, rate = sf.read(str(p), dtype="float32", always_2d=True)
            x = x.mean(axis=1)
        except Exception:  # noqa: BLE001 - fall back to ffmpeg
            x = None
    if x is None:
        rate = sr or 48000
        x = _ffmpeg_decode(p, rate)
    if sr and rate != sr:
        x = resample(x, rate, sr)
        rate = sr
    return np.ascontiguousarray(x, dtype=np.float32), int(rate)


def _ffmpeg_decode(p: Path, sr: int) -> np.ndarray:
    from .. import ff
    argv = [ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", os.fspath(p),
            "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    try:
        cp = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    except OSError as e:
        raise ShowtimeError("could not run ffmpeg to decode %s: %s" % (p, e))
    if cp.returncode != 0:
        tail = cp.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        raise ShowtimeError("could not decode %s: %s" % (p, " / ".join(tail) or "ffmpeg failed"))
    return np.frombuffer(cp.stdout, dtype="<f4").copy()


def write(path: PathLike, x: np.ndarray, sr: int, bits: int = 16) -> Path:
    """Write mono WAV (PCM 16/24 bit or float) atomically."""
    import soundfile as sf
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    subtype = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}[bits]
    tmp = part_path(p)
    y = np.clip(np.asarray(x, dtype=np.float32), -1.0, 1.0) if bits != 32 else np.asarray(x, dtype=np.float32)
    sf.write(str(tmp), y, int(sr), subtype=subtype, format="WAV")
    os.replace(str(tmp), str(p))
    return p


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    """Polyphase resampling (scipy), exact for integer-ratio rates."""
    if sr_in == sr_out or len(x) == 0:
        return np.asarray(x, dtype=np.float32)
    from scipy.signal import resample_poly
    g = gcd(int(sr_in), int(sr_out))
    return resample_poly(np.asarray(x, dtype=np.float64), sr_out // g, sr_in // g).astype(np.float32)


def silence(seconds: float, sr: int) -> np.ndarray:
    return np.zeros(max(0, int(round(seconds * sr))), dtype=np.float32)


def duration(path: PathLike) -> float:
    try:
        import soundfile as sf
        info = sf.info(os.fspath(path))
        return float(info.frames) / float(info.samplerate)
    except Exception:  # noqa: BLE001
        x, sr = read(path)
        return len(x) / float(sr)


def frame_db(x: np.ndarray, sr: int, hop: float = 0.01) -> np.ndarray:
    """RMS level per `hop` frame in dB relative to the loudest frame."""
    n = max(1, int(round(sr * hop)))
    m = len(x) // n
    if m == 0:
        return np.zeros(0, dtype=np.float32)
    fr = x[: m * n].reshape(m, n).astype(np.float64)
    db = 20.0 * np.log10(np.sqrt((fr ** 2).mean(axis=1)) + 1e-9)
    return (db - db.max()).astype(np.float32)


def speech_bounds(x: np.ndarray, sr: int, thr_db: float = -45.0) -> Tuple[float, float]:
    """(first, last) voiced time in seconds; (0, len) if nothing is voiced."""
    db = frame_db(x, sr)
    idx = np.flatnonzero(db > thr_db)
    if idx.size == 0:
        return 0.0, len(x) / float(sr)
    return idx[0] * 0.01, (idx[-1] + 1) * 0.01


def fade(x: np.ndarray, sr: int, fade_in: float = 0.003, fade_out: float = 0.008) -> np.ndarray:
    """Tiny linear fades to avoid clicks at cut points."""
    y = np.array(x, dtype=np.float32, copy=True)
    a = min(len(y), int(sr * fade_in))
    b = min(len(y), int(sr * fade_out))
    if a > 0:
        y[:a] *= np.linspace(0.0, 1.0, a, dtype=np.float32)
    if b > 0:
        y[len(y) - b:] *= np.linspace(1.0, 0.0, b, dtype=np.float32)
    return y

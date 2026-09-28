"""Audio file I/O at 48 kHz stereo float32.

- WAV/FLAC/AIFF at 48 kHz are read with soundfile (fast, no subprocess).
- Anything else (MP3, Ogg/Opus, M4A, video files, other rates) is decoded
  by the resolved ffmpeg to raw float32 through a pipe.
- Writing: WAV (PCM 16/24/float) and FLAC via soundfile; Opus/MP3/AAC via
  ffmpeg from a temporary WAV.

Paths are passed to ffmpeg as plain arguments (no filtergraph escaping is
needed), so Windows drive letters and odd characters are safe.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple, Union

import numpy as np

from .. import ff
from ..common import ShowtimeError, part_path
from . import SR

PathLike = Union[str, "os.PathLike[str]"]

_SF_EXT = {".wav", ".flac", ".aif", ".aiff", ".w64", ".rf64"}


def load(path: PathLike, sr: int = SR, mono: bool = False, offset: float = 0.0,
         duration: Optional[float] = None) -> np.ndarray:
    """Decode any audio (or the first audio stream of a video) to float32.

    Returns (n, 2) stereo (or (n,) if mono=True) at `sr` Hz.
    """
    p = Path(path)
    if not p.is_file():
        raise ShowtimeError("audio file not found: %s" % p)
    x = None
    if p.suffix.lower() in _SF_EXT:
        try:
            import soundfile as sf
            info = sf.info(str(p))
            if info.samplerate == sr:
                start = int(round(offset * sr))
                frames = int(round(duration * sr)) if duration is not None else -1
                x, _ = sf.read(str(p), dtype="float32", always_2d=True, start=start,
                               frames=frames)
        except Exception:  # noqa: BLE001 - fall back to ffmpeg
            x = None
    if x is None:
        x = _ffmpeg_decode(p, sr, offset, duration)
    if x.ndim == 1:
        x = x[:, None]
    if x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    elif x.shape[1] > 2:
        x = x[:, :2]
    x = np.ascontiguousarray(x, dtype=np.float32)
    if mono:
        return x.mean(axis=1)
    return x


def _ffmpeg_decode(p: Path, sr: int, offset: float, duration: Optional[float]) -> np.ndarray:
    args = [ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error"]
    if offset > 0:
        args += ["-ss", "%.6f" % offset]
    args += ["-i", str(p)]
    if duration is not None:
        args += ["-t", "%.6f" % duration]
    args += ["-vn", "-map", "0:a:0?", "-ac", "2", "-ar", str(sr), "-f", "f32le", "-acodec", "pcm_f32le", "-"]
    try:
        cp = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
    except OSError as e:
        raise ShowtimeError("could not run ffmpeg to decode %s: %s" % (p, e),
                            hint="run `showtime doctor`")
    if cp.returncode != 0:
        tail = cp.stderr.decode("utf-8", "replace").strip().splitlines()[-3:]
        raise ShowtimeError("ffmpeg could not decode %s: %s" % (p, " | ".join(tail)))
    x = np.frombuffer(cp.stdout, dtype="<f4")
    if x.size == 0:
        raise ShowtimeError("no audio stream in %s" % p)
    return x.reshape(-1, 2).copy()


def info(path: PathLike) -> dict:
    """Duration / sample rate / channels / codec (soundfile, else ffprobe)."""
    p = Path(path)
    if p.suffix.lower() in _SF_EXT:
        try:
            import soundfile as sf
            i = sf.info(str(p))
            return {"duration": i.frames / float(i.samplerate), "sample_rate": i.samplerate,
                    "channels": i.channels, "codec": i.subtype.lower()}
        except Exception:  # noqa: BLE001
            pass
    pr = ff.probe(p)
    a = (pr.get("audio_streams") or [{}])[0]
    return {"duration": pr.get("duration") or a.get("duration") or 0.0,
            "sample_rate": a.get("sample_rate"), "channels": a.get("channels"), "codec": a.get("codec")}


def save(path: PathLike, x: np.ndarray, sr: int = SR, bits: int = 24, bitrate: str = "128k") -> Path:
    """Write audio; the format follows the extension (.wav .flac .opus .ogg .mp3 .m4a)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    x = np.asarray(x, dtype=np.float32)
    if not np.all(np.isfinite(x)):
        x = np.nan_to_num(x)
    ext = p.suffix.lower()
    import soundfile as sf
    if ext in (".wav", ".flac"):
        sub = {16: "PCM_16", 24: "PCM_24", 32: "FLOAT"}.get(bits, "PCM_24")
        if ext == ".flac" and sub == "FLOAT":
            sub = "PCM_24"
        tmp = part_path(p)
        try:
            sf.write(str(tmp), x, sr, subtype=sub)
            os.replace(str(tmp), str(p))
        finally:
            if tmp.exists():
                tmp.unlink()
        return p
    codec = {".opus": ["-c:a", "libopus", "-b:a", bitrate, "-vbr", "on"],
             ".ogg": ["-c:a", "libvorbis", "-q:a", "5"],
             ".mp3": ["-c:a", "libmp3lame", "-b:a", bitrate],
             ".m4a": ["-c:a", "aac", "-aac_coder", "fast", "-b:a", bitrate]}.get(ext)
    if codec is None:
        raise ShowtimeError("unsupported audio format %r (use .wav, .flac, .opus, .ogg, .mp3 or .m4a)" % ext)
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        sf.write(tmp, x, sr, subtype="FLOAT")
        out_tmp = part_path(p)
        ff.run_ffmpeg(["-i", tmp] + codec + [str(out_tmp)])
        os.replace(str(out_tmp), str(p))
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return p


def transcode(src: PathLike, dst: PathLike, bitrate: str = "128k") -> Path:
    """Transcode any file to the format of dst's extension with ffmpeg (48 kHz stereo)."""
    d = Path(dst)
    d.parent.mkdir(parents=True, exist_ok=True)
    ext = d.suffix.lower()
    codec = {".opus": ["-c:a", "libopus", "-b:a", bitrate, "-vbr", "on"],
             ".ogg": ["-c:a", "libvorbis", "-q:a", "5"],
             ".mp3": ["-c:a", "libmp3lame", "-b:a", bitrate],
             ".flac": ["-c:a", "flac", "-sample_fmt", "s16"],
             ".wav": ["-c:a", "pcm_s24le"],
             ".m4a": ["-c:a", "aac", "-aac_coder", "fast", "-b:a", bitrate]}.get(ext)
    if codec is None:
        raise ShowtimeError("unsupported target format %r" % ext)
    tmp = part_path(d)
    ff.run_ffmpeg(["-i", str(src), "-vn", "-map_metadata", "-1", "-ac", "2", "-ar", str(SR)] + codec + [str(tmp)])
    os.replace(str(tmp), str(d))
    return d


def duration_of(path: PathLike) -> float:
    return float(info(path).get("duration") or 0.0)


def peak_rms_db(x: np.ndarray) -> Tuple[float, float]:
    a = np.abs(x)
    pk = float(a.max()) if a.size else 0.0
    rms = float(np.sqrt((np.asarray(x, dtype=np.float64) ** 2).mean())) if a.size else 0.0
    return 20 * np.log10(pk + 1e-12), 20 * np.log10(rms + 1e-12)

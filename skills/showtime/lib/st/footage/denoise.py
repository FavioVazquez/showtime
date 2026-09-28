"""Speech denoising with graceful fallbacks.

Methods, best first (`auto` picks the first available):
  deepfilter  DeepFilterNet 3 (`deep-filter` binary in ~/.showtime/bin,
              `showtime setup --with deepfilter`): strongest, natural voice.
  rnnoise     ffmpeg `arnndn` with an RNNoise model (~/.showtime/models/arnndn):
              good on steady noise (fans, hum, hiss).
  afftdn      ffmpeg FFT denoiser with noise tracking: always available.

A gentle 70 Hz high-pass runs first in every method (rumble, handling noise).
`strength` 0..1 blends toward the original (1 = full reduction). The output keeps the
source's channel count and its exact length in samples (a model's frame delay is padded
back), so a cleaned track lines up with the picture.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from .. import ff
from ..common import ShowtimeError, ensure_dir, info, paths, which
from . import util as U

METHODS = ("auto", "deepfilter", "rnnoise", "afftdn")
RNN_MODELS = {"cb": "general recordings (default)", "sh": "noisy recordings, stronger", "std": "original RNNoise"}


def deepfilter_bin() -> Optional[str]:
    env = os.environ.get("SHOWTIME_DEEPFILTER")
    if env and Path(env).is_file():
        return env
    return which("deep-filter")


def available() -> Dict[str, bool]:
    rnn = any((paths()["arnndn"] / ("%s.rnnn" % m)).is_file() for m in RNN_MODELS)
    return {"deepfilter": bool(deepfilter_bin()), "rnnoise": rnn and ff.has_filter("arnndn"),
            "afftdn": ff.has_filter("afftdn")}


def pick(method: str) -> str:
    av = available()
    if method not in METHODS:
        raise ShowtimeError("unknown denoise method %r (%s)" % (method, ", ".join(METHODS)))
    if method != "auto":
        if av.get(method):
            return method
        fallback = next((m for m in ("deepfilter", "rnnoise", "afftdn") if av.get(m)), None)
        if not fallback:
            raise ShowtimeError("no denoiser available in this ffmpeg build")
        return fallback
    for m in ("deepfilter", "rnnoise", "afftdn"):
        if av.get(m):
            return m
    raise ShowtimeError("no denoiser available (no deep-filter, arnndn or afftdn)",
                        hint="run `showtime setup --with deepfilter`")


def _filter(method: str, strength: float, model: str) -> str:
    s = max(0.0, min(1.0, strength))
    if method == "rnnoise":
        mp = paths()["arnndn"] / ("%s.rnnn" % model)
        if not mp.is_file():
            mp = next(p for p in (paths()["arnndn"] / ("%s.rnnn" % m) for m in RNN_MODELS) if p.is_file())
        return "highpass=f=70,arnndn=m=%s:mix=%.2f" % (ff.filter_path(mp), s)
    return "highpass=f=70,afftdn=nr=%.1f:nf=-42:tn=1" % (6 + 18 * s)


def denoise(src, out, *, method: str = "auto", strength: float = 1.0, model: str = "cb",
            audio_only: bool = False, track: int = 0) -> Dict[str, Any]:
    """Denoise the audio of `src`. Writes a WAV (audio_only or .wav/.flac output)
    or remuxes the video with cleaned AAC audio. Returns a report."""
    src, out = Path(src), Path(out)
    pr = U.probe(src)
    if not pr.get("has_audio"):
        raise ShowtimeError("%s has no audio to denoise" % src.name)
    m = pick(method)
    ensure_dir(out.parent)
    to_wav = audio_only or out.suffix.lower() in (".wav", ".flac")
    streams = pr.get("audio_streams") or []
    chans = int((streams[track] if track < len(streams) else streams[0] if streams else {}).get("channels") or 1)
    chans = max(1, min(chans, 8))
    with tempfile.TemporaryDirectory(prefix="st-dn-") as td:
        tdp = Path(td)
        raw = tdp / "in.wav"
        ff.run_ffmpeg(["-i", str(src), "-map", "0:a:%d" % track, "-vn", "-ac", str(chans), "-ar", "48000",
                       "-af", "highpass=f=70", "-c:a", "pcm_s16le", str(raw)])
        n_in = _samples(raw)
        clean = tdp / "clean.wav"
        if m == "deepfilter":
            exe = deepfilter_bin()
            od = ensure_dir(tdp / "out")
            atten = 100 if strength >= 0.99 else int(round(6 + 30 * max(0.0, strength)))
            cp = subprocess.run([exe, "-D", "-a", str(atten), "-o", str(od), str(raw)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                encoding="utf-8", errors="replace")
            res = od / raw.name
            if cp.returncode != 0 or not res.is_file():
                info("deep-filter failed (%s); falling back to ffmpeg denoise" % (cp.stderr or "").strip()[-200:])
                m = "rnnoise" if available().get("rnnoise") else "afftdn"
            else:
                shutil.move(str(res), str(clean))
        if m != "deepfilter":
            ff.run_ffmpeg(["-i", str(raw), "-af", _filter(m, strength, model), "-ar", "48000", "-c:a", "pcm_s16le",
                           str(clean)])
        n_out = _samples(clean)
        if n_in and n_out != n_in:
            # a model's frame/lookahead delay shortens the track (deep-filter: ~30 ms): pad or trim the end back
            # to the source's exact sample count so the audio keeps its length against the picture
            fixed = tdp / "clean-len.wav"
            ff.run_ffmpeg(["-i", str(clean), "-af", "apad=whole_len=%d,atrim=end_sample=%d" % (n_in, n_in),
                           "-c:a", "pcm_s16le", str(fixed)])
            clean = fixed
        if to_wav:
            if out.suffix.lower() == ".flac":
                ff.run_ffmpeg(["-i", str(clean), "-c:a", "flac", str(out)])
            else:
                shutil.copyfile(str(clean), str(out))
        else:
            ff.run_ffmpeg(["-i", str(src), "-i", str(clean), "-map", "0:v?", "-map", "1:a", "-c:v", "copy",
                           "-c:a", "aac", "-aac_coder", "fast", "-b:a", "256k", "-ar", "48000", "-ac", str(chans),
                           "-movflags", "+faststart", str(out)])
        before = U.audio_levels(*U.load_audio(raw, sr=16000))
        after = U.audio_levels(*U.load_audio(clean, sr=16000))
        removed = _removed_db(raw, clean)
    s = max(0.0, min(1.0, strength))
    return {"output": str(out), "method": m, "strength": strength, "channels": chans,
            "noise_floor_before_db": before["floor_db"], "noise_floor_after_db": after["floor_db"],
            "reduction_limit": strength_limit(m, s), "removed_db": removed,
            "samples": n_in, "samples_out": n_in or _samples(clean)}


def strength_limit(method: str, s: float) -> str:
    """What --strength means for this method, in words (the report line)."""
    if method == "deepfilter":
        return "no limit" if s >= 0.99 else "at most %d dB of reduction" % int(round(6 + 30 * s))
    if method == "rnnoise":
        return "%d%% of the RNNoise output mixed in" % int(round(100 * s))
    return "noise reduction %.0f dB" % (6 + 18 * s)


def _samples(path: Path) -> int:
    try:
        import soundfile as sf
        return int(sf.info(str(path)).frames)
    except Exception:  # noqa: BLE001 - length repair is best effort
        return 0


def _removed_db(raw: Path, clean: Path) -> Optional[float]:
    """Level of what the denoiser took out (source minus result, dBFS RMS): unlike the noise floor it
    changes with --strength, so two strengths can be compared."""
    try:
        import numpy as np
        a, _ = U.load_audio(raw, mono=True)
        b, _ = U.load_audio(clean, mono=True)
        n = min(len(a), len(b))
        if n == 0:
            return None
        d = a[:n].astype(np.float64) - b[:n].astype(np.float64)
        return round(10 * float(np.log10(np.mean(d ** 2) + 1e-12)), 1)
    except Exception:  # noqa: BLE001
        return None

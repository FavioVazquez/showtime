"""Speech under music: estimate how loud the bed is, and pull the voice out only when it helps.

Separation is double-edged: on clean speech it adds artefacts and raises the error rate, so it runs
only when the music is loud (estimated speech-to-background ratio under ~8 dB) or when a first pass
recognises suspiciously few words for the amount of speech. The separated vocal stem keeps the
original timeline sample for sample, so word times need no mapping beyond the resampling.

Model: UVR-MDX-NET-Voc_FT (ONNX, MIT; credit the Ultimate Vocal Remover project), fetched on first
use (67 MB, asr_models.ensure("mdx-voc-ft")). Inference is plain numpy + onnxruntime (no PyTorch),
so it runs wherever the rest of showtime does, Intel Macs included.
"""
from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..common import ShowtimeError, debug, info, ort_telemetry_off
from .. import platform as plat
from . import util as U

SNR_GATE_DB = 8.0
# MDX-Net settings of UVR-MDX-NET-Voc_FT (UVR's model_data for this checkpoint)
MDX = {"n_fft": 7680, "hop": 1024, "dim_f": 3072, "dim_t": 256, "compensate": 1.021, "sr": 44100}


# --------------------------------------------------------------------------
# how loud is the background?
# --------------------------------------------------------------------------

def speech_to_background_db(audio, sr: int, spans: Optional[Sequence[Tuple[float, float]]]) -> Optional[float]:
    """Median level of speech frames minus median level of the non-speech frames (dB).

    Music keeps playing between phrases (a ducked bed even rises there), so a small difference means a
    loud bed; room noise sits far under speech. None without speech spans or pauses to measure."""
    import numpy as np
    if not spans:
        return None
    db = U.frame_db(audio, sr, 0.05)
    m = np.zeros(len(db), dtype=bool)
    for s, e in spans:
        m[int(s / 0.05): int(math.ceil(e / 0.05))] = True
    # pauses: at least 0.1 s away from speech
    k = 2
    pad = np.convolve(m.astype(float), np.ones(2 * k + 1), "same") > 0
    sp, bg = db[m], db[~pad]
    if len(sp) < 10 or len(bg) < 6:
        return None
    # digital silence between phrases would read as a 150 dB ratio: anything past 60 dB is "no background"
    return round(min(60.0, float(np.median(sp) - max(-90.0, float(np.median(bg))))), 1)


def level_spread_db(audio, sr: int) -> Optional[float]:
    """Loud frames (90th percentile) minus quiet frames (20th), 50 ms RMS: a fallback when the VAD
    finds no pauses (it may hear the music itself as speech)."""
    import numpy as np
    db = U.frame_db(audio, sr, 0.05)
    db = db[db > -100]
    if len(db) < 20:
        return None
    return round(float(np.percentile(db, 90) - np.percentile(db, 20)), 1)


def music_likely(audio, sr: int, spans) -> Dict[str, Any]:
    """{"snr_db": x|None, "separate": bool, "why": str, "method": "pauses"|"spread"}."""
    snr = speech_to_background_db(audio, sr, spans)
    method = "pauses"
    if snr is None:
        spread = level_spread_db(audio, sr)
        if spread is None:
            return {"snr_db": None, "separate": False, "why": "too short to measure the background"}
        snr, method = round(spread - 6.0, 1), "spread"   # the spread overstates the ratio by ~6 dB
    if snr < SNR_GATE_DB:
        return {"snr_db": snr, "separate": True, "method": method,
                "why": "the background is only %.1f dB under the speech" % snr}
    return {"snr_db": snr, "separate": False, "method": method,
            "why": "speech is %.1f dB over the background" % snr}



def speech_time_snr_db(mix, vocals, sr: int) -> Optional[float]:
    """Voice-to-music ratio while the voice is active, measured on a separation (music = mix - vocals).

    The pause-based estimate cannot see a bed that is ducked under the speech (loud between phrases,
    quiet under them); the separated stems can. None when the voice is never clearly active."""
    import numpy as np
    n = min(len(mix), len(vocals))
    v = np.asarray(vocals[:n], dtype=np.float64)
    m = np.asarray(mix[:n], dtype=np.float64) - v
    vd = U.frame_db(v.astype(np.float32), sr, 0.05)
    if not len(vd):
        return None
    act = vd > max(float(vd.max()) - 25.0, -55.0)
    if act.sum() < 10:
        return None
    hop = int(0.05 * sr)
    idx = np.repeat(act, hop)[:n]
    idx = np.concatenate([idx, np.zeros(n - len(idx), dtype=bool)]) if len(idx) < n else idx
    pv, pm = float((v[idx] ** 2).mean()), float((m[idx] ** 2).mean())
    return round(10 * math.log10((pv + 1e-12) / (pm + 1e-12)), 1)


# --------------------------------------------------------------------------
# MDX-Net inference (numpy STFT + onnxruntime)
# --------------------------------------------------------------------------

def _stft(x, n_fft: int, hop: int, window):
    """x: [C, N] -> complex [C, n_fft//2+1, frames], centred (reflect padding) like torch.stft."""
    import numpy as np
    pad = n_fft // 2
    xp = np.pad(x, ((0, 0), (pad, pad)), mode="reflect")
    frames = 1 + (xp.shape[1] - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(frames)[:, None]
    fr = xp[:, idx] * window[None, None, :]
    return np.fft.rfft(fr, axis=-1).transpose(0, 2, 1)


def _istft(spec, n_fft: int, hop: int, window, length: int):
    """complex [C, F, T] -> [C, length] (overlap-add, window-square normalised, centred)."""
    import numpy as np
    fr = np.fft.irfft(spec.transpose(0, 2, 1), n=n_fft, axis=-1) * window[None, None, :]
    c, t, _ = fr.shape
    total = n_fft + hop * (t - 1)
    y = np.zeros((c, total))
    wsum = np.zeros(total)
    w2 = window ** 2
    for i in range(t):
        y[:, i * hop: i * hop + n_fft] += fr[:, i]
        wsum[i * hop: i * hop + n_fft] += w2
    y /= np.maximum(wsum, 1e-8)[None, :]
    pad = n_fft // 2
    return y[:, pad: pad + length]


def _session(model: Path, threads: int):
    import onnxruntime as ort
    ort_telemetry_off(ort)
    so = ort.SessionOptions()
    so.intra_op_num_threads = max(1, threads)
    so.inter_op_num_threads = 1
    return ort.InferenceSession(str(model), sess_options=so, providers=["CPUExecutionProvider"])


def vocals(x, sr: int, model: Path, threads: Optional[int] = None, progress: bool = True):
    """Separated vocals of `x` (mono or [N, C] float32 at `sr`) -> mono float32 at `sr`, same length."""
    import numpy as np
    from scipy.signal import resample_poly
    n_fft, hop, dim_f, dim_t = MDX["n_fft"], MDX["hop"], MDX["dim_f"], MDX["dim_t"]
    msr = MDX["sr"]
    a = np.asarray(x, dtype=np.float64)
    if a.ndim == 1:
        a = np.stack([a, a], axis=1)
    g = math.gcd(msr, sr)
    a = resample_poly(a, msr // g, sr // g, axis=0).T            # [2, N] at 44.1 kHz
    n = a.shape[1]
    chunk = hop * (dim_t - 1)
    trim = n_fft // 2
    gen = chunk - 2 * trim
    pad = gen + trim - (n % gen)
    mix = np.concatenate([np.zeros((2, trim)), a, np.zeros((2, pad))], axis=1)
    window = np.hanning(n_fft + 1)[:-1]                           # periodic Hann, like torch.hann_window
    sess = _session(model, threads or plat.cpu_count())
    name = sess.get_inputs()[0].name
    out = []
    steps = list(range(0, mix.shape[1] - chunk + 1, gen))
    t0 = time.time()
    for k, i in enumerate(steps):
        part = mix[:, i:i + chunk]
        spec = _stft(part, n_fft, hop, window)[:, :dim_f, :dim_t]         # [2, dim_f, dim_t]
        inp = np.stack([spec[0].real, spec[0].imag, spec[1].real, spec[1].imag])[None].astype(np.float32)
        pred = sess.run(None, {name: inp})[0][0]                          # [4, dim_f, dim_t]
        full = np.zeros((2, n_fft // 2 + 1, dim_t), dtype=np.complex128)
        full[0, :dim_f] = pred[0] + 1j * pred[1]
        full[1, :dim_f] = pred[2] + 1j * pred[3]
        y = _istft(full, n_fft, hop, window, chunk)
        out.append(y[:, trim:-trim])
        if progress and k == 0 and len(steps) > 4:
            eta = (time.time() - t0) * (len(steps) - 1)
            if eta > 10:
                info("separating the voice from the music: ~%ds" % int(eta))
    v = np.concatenate(out, axis=1)[:, :n] * MDX["compensate"]
    v = v.mean(axis=0)
    v = resample_poly(v, sr // g, msr // g)[: len(x) if np.ndim(x) == 1 else np.shape(x)[0]]
    return v.astype(np.float32)


def separate_wav(src_wav: Path, dst_wav: Path, threads: Optional[int] = None) -> Path:
    """Vocals of a (16 kHz mono) WAV into dst_wav (cached by the caller)."""
    import soundfile as sf
    from .asr_models import ensure
    model = ensure("mdx-voc-ft", "separating speech from music")
    x, sr = U.load_audio(src_wav, sr=16000)
    t0 = time.time()
    v = vocals(x, sr, model, threads=threads)
    tmp = dst_wav.with_name(dst_wav.stem + ".part.wav")
    sf.write(str(tmp), v, sr, subtype="PCM_16")
    tmp.replace(dst_wav)
    debug("separated %s in %.1fs" % (src_wav.name, time.time() - t0))
    return dst_wav

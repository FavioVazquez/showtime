"""Narration mastering: clean, even, and at a known loudness.

Chain (ffmpeg, all built-in filters present in every supported build):
    highpass 70 Hz  ->  de-esser  ->  gentle 3:1 compressor  ->  loudnorm
Loudness uses two passes (measure, then linear gain) to -16 LUFS integrated,
-1.5 dBTP, which suits voice-over for web/social; the final video mix is
normalized again by `audio mix` / render. If the linear pass lands more than
0.5 LU off (loudnorm falls back to dynamic mode when the peak limit would
be hit), a corrective gain is applied and the result re-measured.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .. import ff
from ..common import ShowtimeError, warn

PathLike = Union[str, "os.PathLike[str]"]

PRESETS: Dict[str, Dict[str, Any]] = {
    # target LUFS, true peak, LRA, highpass Hz, de-ess intensity, compressor (threshold dB, ratio)
    "voice": {"lufs": -16.0, "tp": -1.5, "lra": 7.0, "highpass": 70, "deess": 0.4, "comp": (-20, 3.0)},
    "podcast": {"lufs": -16.0, "tp": -1.0, "lra": 6.0, "highpass": 80, "deess": 0.5, "comp": (-22, 3.5)},
    "broadcast": {"lufs": -23.0, "tp": -1.0, "lra": 7.0, "highpass": 70, "deess": 0.4, "comp": (-24, 2.5)},
    "youtube": {"lufs": -14.0, "tp": -1.0, "lra": 7.0, "highpass": 70, "deess": 0.4, "comp": (-20, 3.0)},
    "gentle": {"lufs": -16.0, "tp": -1.5, "lra": 9.0, "highpass": 60, "deess": 0.0, "comp": None},
}


def chain(highpass: Optional[float] = 70, deess: float = 0.4, comp: Optional[tuple] = (-20, 3.0)) -> List[str]:
    f: List[str] = []
    if highpass:
        f.append("highpass=f=%g:poles=2" % highpass)
    if deess and deess > 0:
        if ff.has_filter("deesser"):
            f.append("deesser=i=%g:m=0.5:f=0.5:s=o" % min(1.0, deess))
        else:
            warn("this ffmpeg has no deesser filter: skipping de-essing")
    if comp:
        thr, ratio = comp
        if ff.has_filter("acompressor"):
            f.append("acompressor=threshold=%gdB:ratio=%g:attack=5:release=80:makeup=1:knee=4" % (thr, ratio))
    return f


def _loudnorm_json(stderr: str) -> Dict[str, float]:
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", stderr or "", re.S)
    if not m:
        raise ShowtimeError("loudness measurement failed (no audio?)")
    d = json.loads(m.group(0))
    return {k: float(v) for k, v in d.items() if re.match(r"^-?[\d.]+$|^-?inf$", str(v))}


def measure(path: PathLike, pre: Optional[List[str]] = None, lufs: float = -16.0, tp: float = -1.5,
            lra: float = 7.0) -> Dict[str, float]:
    """Integrated loudness, true peak and LRA (loudnorm analysis)."""
    af = ",".join((pre or []) + ["loudnorm=I=%g:TP=%g:LRA=%g:print_format=json" % (lufs, tp, lra)])
    cp = ff.run_ffmpeg(["-i", os.fspath(path), "-vn", "-af", af, "-f", "null", "-"], loglevel="info",
                       overwrite=False)
    return _loudnorm_json(cp.stderr)


def master(src: PathLike, dst: PathLike, lufs: Optional[float] = None, tp: Optional[float] = None,
           preset: str = "voice", sr: int = 48000, bits: int = 24, stereo: bool = False) -> Dict[str, Any]:
    """Master a voice file. Returns a report with before/after loudness."""
    if preset not in PRESETS:
        raise ShowtimeError("unknown mastering preset %r" % preset, hint="presets: " + ", ".join(PRESETS))
    p = dict(PRESETS[preset])
    lufs = p["lufs"] if lufs is None else float(lufs)
    tp = p["tp"] if tp is None else float(tp)
    lra = p["lra"]
    src_p, dst_p = Path(src), Path(dst)
    if not src_p.is_file():
        raise ShowtimeError("input not found: %s" % src_p)
    if src_p.resolve() == dst_p.resolve():
        raise ShowtimeError("output must differ from the input", hint="pass -o <new file>")
    dst_p.parent.mkdir(parents=True, exist_ok=True)
    pre = chain(p["highpass"], p["deess"], p["comp"])
    before = measure(src_p, None, lufs, tp, lra)
    m1 = measure(src_p, pre, lufs, tp, lra)
    if m1.get("input_i", -99) < -70:
        raise ShowtimeError("the input is (nearly) silent: nothing to master")
    ln = ("loudnorm=I=%g:TP=%g:LRA=%g:measured_I=%.2f:measured_TP=%.2f:measured_LRA=%.2f:"
          "measured_thresh=%.2f:offset=%.2f:linear=true" % (lufs, tp, lra, m1["input_i"], m1["input_tp"],
                                                            m1["input_lra"], m1["input_thresh"], m1["target_offset"]))
    codec = {16: "pcm_s16le", 24: "pcm_s24le", 32: "pcm_f32le"}[bits]
    tmp = dst_p.with_name(".%s.part%s" % (dst_p.stem, dst_p.suffix or ".wav"))
    af = ",".join(pre + [ln, "aresample=%d" % sr])
    ff.run_ffmpeg(["-i", os.fspath(src_p), "-vn", "-af", af, "-ar", str(sr), "-ac", "2" if stereo else "1",
                   "-c:a", codec, os.fspath(tmp)])
    after = measure(tmp, None, lufs, tp, lra)
    fixed = False
    for _ in range(2):
        diff = lufs - after["input_i"]
        if abs(diff) <= 0.4:
            break
        # loudnorm could not apply the full linear gain (peaky or very short clip):
        # add the missing gain and catch the peaks with a limiter set under the ceiling.
        tmp2 = dst_p.with_name(".%s.fix%s" % (dst_p.stem, dst_p.suffix or ".wav"))
        af2 = "volume=%.2fdB" % diff
        if diff > 0 and after["input_tp"] + diff > tp - 0.1 and ff.has_filter("alimiter"):
            af2 += ",alimiter=limit=%.4f:attack=2:release=60:level=disabled" % (10 ** ((tp - 0.7) / 20.0))
        ff.run_ffmpeg(["-i", os.fspath(tmp), "-af", af2, "-ar", str(sr), "-c:a", codec, os.fspath(tmp2)])
        os.replace(os.fspath(tmp2), os.fspath(tmp))
        after = measure(tmp, None, lufs, tp, lra)
        fixed = True
    os.replace(os.fspath(tmp), os.fspath(dst_p))
    return {"input": str(src_p), "output": str(dst_p), "preset": preset, "target_lufs": lufs, "target_tp": tp,
            "before": {"lufs": round(before["input_i"], 2), "tp": round(before["input_tp"], 2),
                       "lra": round(before["input_lra"], 2)},
            "after": {"lufs": round(after["input_i"], 2), "tp": round(after["input_tp"], 2),
                      "lra": round(after["input_lra"], 2)},
            "gain_corrected": fixed, "chain": pre, "sample_rate": sr}


def master_array(x, sr: int, lufs: float = -16.0, tp: float = -1.5, preset: str = "voice", out_sr: int = 48000):
    """Master an in-memory mono float array; returns (array, sr, report)."""
    from . import audio_io as aio
    with tempfile.TemporaryDirectory(prefix="st-vo-") as d:
        a, b = Path(d) / "in.wav", Path(d) / "out.wav"
        aio.write(a, x, sr, bits=32)
        rep = master(a, b, lufs=lufs, tp=tp, preset=preset, sr=out_sr, bits=32)
        y, rate = aio.read(b)
    rep.pop("input", None)
    rep.pop("output", None)
    return y, rate, rep

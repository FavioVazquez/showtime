"""Stabilise shaky footage: vid.stab two-pass (detect -> transform) when the
ffmpeg build has it, otherwise the single-pass `deshake` filter.

strength 0..1 controls how much motion is smoothed (0.5 = handheld walk,
1.0 = very shaky). optzoom crops just enough to hide moving borders.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict

from .. import ff
from ..common import ShowtimeError, ensure_dir, info
from . import util as U


def stabilize(src, out, *, strength: float = 0.5, preview: bool = False) -> Dict[str, Any]:
    src, out = Path(src), Path(out)
    pr = U.probe(src)
    if not pr.get("has_video"):
        raise ShowtimeError("%s has no video stream" % src.name)
    s = max(0.0, min(1.0, strength))
    ensure_dir(out.parent)
    preset = ff.preset("preview" if preview else "final")
    audio = ["-map", "0:a?", "-c:a", "aac", "-aac_coder", "fast", "-b:a", "256k", "-ar", "48000"] if pr.get("has_audio") else []
    if ff.has_filter("vidstabdetect") and ff.has_filter("vidstabtransform"):
        with tempfile.TemporaryDirectory(prefix="st-stab-") as td:
            trf = Path(td) / "motion.trf"
            info("stabilising %s: analysing motion" % src.name)
            ff.run_ffmpeg(["-i", str(src), "-an", "-vf", "vidstabdetect=shakiness=%d:accuracy=15:result=%s"
                           % (int(round(3 + 7 * s)), ff.filter_path(trf)), "-f", "null", "-"])
            vf = ("vidstabtransform=input=%s:smoothing=%d:zoom=0:optzoom=1:interpol=bicubic,"
                  "unsharp=5:5:0.5:3:3:0.0,%s" % (ff.filter_path(trf), int(round(10 + 40 * s)), preset.vf_tail))
            ff.run_ffmpeg(["-i", str(src), "-map", "0:v:0", "-vf", vf] + preset.video + audio +
                          ["-movflags", "+faststart", str(out)])
        method = "vidstab"
    else:
        r = int(round(16 + 32 * s))
        vf = "deshake=rx=%d:ry=%d,%s" % (r, r, preset.vf_tail)
        ff.run_ffmpeg(["-i", str(src), "-map", "0:v:0", "-vf", vf] + preset.video + audio +
                      ["-movflags", "+faststart", str(out)])
        method = "deshake"
    return {"output": str(out), "method": method, "strength": s}

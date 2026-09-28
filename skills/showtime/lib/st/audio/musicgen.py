"""Optional MusicGen draft tier (installed with `showtime setup --with musicgen`).

MusicGen weights are CC-BY-NC 4.0: output is for personal, demo or temp-track
use only, never for commercial videos. Every run prints that warning and the
result's sidecar records license CC-BY-NC-4.0, so `audio mix` reports it.

Generation runs in ~/.showtime/venv-musicgen (a separate venv with torch);
post-processing (loudness, bar-aligned loop/fit to the exact length, beat
analysis) runs here. CPU speed is roughly 5-20x slower than real time.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

from ..common import ShowtimeError, home, log, read_json, warn, write_json
from .. import platform as plat

LICENSE = "CC-BY-NC-4.0"
WARNING = ("MusicGen weights are CC-BY-NC-4.0: this output is for personal/demo/temp-track use only, "
           "not for commercial videos. Swap in library or composed music before publishing.")


def venv_python() -> Path:
    return plat.venv_python(home() / "venv-musicgen")


def available() -> bool:
    return venv_python().is_file()


def generate(prompt: str, seconds: float, out: Path, seed: int = 0, fit_to: Optional[float] = None,
             lufs: float = -16.0, threads: int = 0, timeout: float = 3600) -> Dict:
    if not available():
        raise ShowtimeError("MusicGen is not installed (optional tier, ~3.5 GB)",
                            hint="run `showtime setup --with musicgen`, or use `showtime audio compose` / the library")
    warn(WARNING)
    st = read_json(home() / "state.json", {}) or {}
    mg = st.get("musicgen") or {}
    model = mg.get("repo", "facebook/musicgen-small")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = out.with_name(".%s.raw.wav" % out.stem)
    gen_s = min(30.0, max(2.0, seconds))
    est = gen_s * 12
    log("MusicGen: %.0fs of audio, roughly %d-%d min on a laptop CPU ..." % (gen_s, max(1, est // 120), max(2, est // 30)))
    worker = Path(__file__).with_name("musicgen_worker.py")
    cmd = [str(venv_python()), str(worker), "--prompt", prompt, "--seconds", str(gen_s), "--out", str(raw),
           "--model", model, "--seed", str(seed), "--threads", str(threads)]
    if mg.get("revision"):
        cmd += ["--revision", mg["revision"]]
    env = dict(os.environ)
    env.setdefault("HF_HOME", str(home() / "models" / "hf"))
    env.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    t0 = time.time()
    try:
        cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=None, env=env, timeout=timeout,
                            encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise ShowtimeError("MusicGen timed out after %ds" % timeout)
    if cp.returncode != 0 or not raw.is_file():
        raise ShowtimeError("MusicGen failed (exit %d)" % cp.returncode, hint="run `showtime doctor`; see the log above")
    info = json.loads((cp.stdout or "{}").strip().splitlines()[-1])
    from . import beats as beats_mod
    from . import fit as fit_mod
    from . import master, wav
    x = wav.load(raw)
    target = fit_to or seconds
    b = None
    try:
        b = beats_mod.analyze(raw)
    except ShowtimeError:
        pass
    if abs(len(x) / 48000 - target) > 0.01:
        x, finfo = fit_mod.fit(x, target, b)
    else:
        finfo = {"mode": "none"}
    y, minfo = master.normalize(x, lufs, -1.0)
    wav.save(out, y)
    try:
        raw.unlink()
    except OSError:
        pass
    meta = {"schema": "showtime.musicgen/1", "prompt": prompt, "seed": seed, "model": model, "license": LICENSE,
            "warning": WARNING, "generated_seconds": info.get("seconds"), "fit": finfo, "master": minfo,
            "seconds": round(time.time() - t0, 1), "output": str(out), "attribution_required": False,
            "commercial_use": False}
    write_json(out.with_name(out.stem + ".musicgen.json"), meta)
    try:
        write_json(out.with_name(out.stem + ".beats.json"), beats_mod.analyze(out))
    except ShowtimeError:
        pass
    return meta

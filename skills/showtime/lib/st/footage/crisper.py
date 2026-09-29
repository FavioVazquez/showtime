"""CrisperWhisper 2.0: opt-in "max accuracy" verbatim transcription.

Its weights are under the Nyra Health Non-Commercial Research License (free for research and other
non-commercial use; commercial use needs a licence from Nyra), so it is never a default: the first
use asks for an explicit acceptance (`showtime transcribe --model crisper --accept-license`), which
is remembered in <home>/licenses.json. It runs on PyTorch (>= 2.4), which has no builds for Intel
Macs; there it stops with a clear message. Everything else installs on first use into its own
environment (<home>/venv-crisper: the crisperwhisper package + CPU PyTorch, ~1 GB), so the main
environment never carries PyTorch. Model weights (small ~1 GB .. large ~3 GB) come from Hugging
Face into <home>/models/hf on first use.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..common import ShowtimeError, home, info, paths, read_json, write_json
from .. import platform as plat

PACKAGE = "crisperwhisper[transformers]==2.0.3"
LICENSE_ID = "crisperwhisper-2.0-nc"
LICENSE_TEXT = ("CrisperWhisper 2.0 model weights (nyralabs/CrisperWhisper2.0_*) are licensed under the Nyra "
                "Health Non-Commercial Research License: free for research and other non-commercial use; any "
                "commercial use requires a commercial licence from Nyra (https://nyra-labs.com/license). "
                "Videos you transcribe with it are covered by those terms.")
SIZES = {"small": "nyralabs/CrisperWhisper2.0_small", "medium": "nyralabs/CrisperWhisper2.0_medium",
         "turbo": "nyralabs/CrisperWhisper2.0_turbo", "large": "nyralabs/CrisperWhisper2.0_large"}

RUNNER = r'''
import json, sys, time
import torch
wav, size, lang, out, threads = sys.argv[1], sys.argv[2], (sys.argv[3] or None), sys.argv[4], int(sys.argv[5])
torch.set_num_threads(threads)
from crisperwhisper import CrisperWhisperModel
m = CrisperWhisperModel(size)
r = m.transcribe(wav, language=lang, word_timestamps=True)
words = [{"word": w.word, "start": float(w.start), "end": float(w.end),
          "probability": float(getattr(w, "probability", 1.0) or 1.0)} for w in (r.words or [])]
json.dump({"text": r.text, "words": words, "language": getattr(r, "language", lang)}, open(out, "w"))
'''


def unsupported_reason() -> Optional[str]:
    if plat.platform_key() == "mac-x64":
        return ("CrisperWhisper needs PyTorch 2.4 or newer, and PyTorch stopped publishing builds for Intel Macs "
                "after 2.2.2, so it cannot run on this Mac")
    return None


def _licenses_path() -> Path:
    return home() / "licenses.json"


def license_accepted() -> bool:
    try:
        return LICENSE_ID in (read_json(_licenses_path()) or {})
    except ShowtimeError:
        return False


def accept_license() -> None:
    p = _licenses_path()
    try:
        d = read_json(p) if p.is_file() else {}
    except ShowtimeError:
        d = {}
    d[LICENSE_ID] = {"accepted": time.strftime("%Y-%m-%dT%H:%M:%S"), "text": LICENSE_TEXT}
    write_json(p, d)


def check(accept: bool = False) -> None:
    """Raise a clear ShowtimeError unless CrisperWhisper may run here (platform + licence)."""
    why = unsupported_reason()
    if why:
        raise ShowtimeError(why, hint="use the default model (Parakeet, verbatim, keeps um/uh): drop --model crisper")
    if license_accepted():
        return
    if accept:
        accept_license()
        info("licence accepted and remembered in %s: %s" % (_licenses_path(), LICENSE_TEXT))
        return
    if sys.stdin is not None and sys.stdin.isatty() and sys.stderr.isatty():
        sys.stderr.write(LICENSE_TEXT + "\nAccept these terms? [y/N] ")
        sys.stderr.flush()
        if sys.stdin.readline().strip().lower() in ("y", "yes"):
            accept_license()
            return
    raise ShowtimeError("CrisperWhisper is licensed for non-commercial use only; it needs your explicit acceptance",
                        why=LICENSE_TEXT,
                        hint="if your use is non-commercial, re-run with --accept-license (asked once); otherwise "
                             "use the default model (Parakeet, CC-BY-4.0)", code=3)


def venv_dir() -> Path:
    return home() / "venv-crisper"


def ensure_env() -> Path:
    """Python of the CrisperWhisper environment, creating it on first use (announced)."""
    vpy = plat.venv_python(venv_dir())
    marker = venv_dir() / ".showtime-crisper"
    if vpy.exists() and marker.is_file():
        return vpy
    if os.environ.get("SHOWTIME_OFFLINE", "") not in ("", "0", "false", "no"):
        raise ShowtimeError("the CrisperWhisper environment is not installed and this run is offline",
                            hint="run once online: showtime transcribe <file> --model crisper")
    uv = os.environ.get("SHOWTIME_UV") or plat.find_tool("uv")
    if not uv:
        raise ShowtimeError("installing CrisperWhisper needs uv (it builds a separate PyTorch environment)",
                            hint="run `showtime setup` (it installs uv), then try again")
    info("installing CrisperWhisper 2.0 + CPU PyTorch into %s (about 1 GB, one time)" % venv_dir())
    if not vpy.exists():
        cp = subprocess.run([uv, "venv", "--python", "3.12", str(venv_dir())], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
        if cp.returncode != 0:
            raise ShowtimeError("could not create %s" % venv_dir(), why=(cp.stdout or "")[-600:])
    cmd = [uv, "pip", "install", "--python", str(vpy)]
    if plat.os_name() in ("linux", "windows"):
        # the CPU wheels (the default Linux wheel pulls ~2.5 GB of CUDA libraries)
        cmd += ["--index-url", "https://download.pytorch.org/whl/cpu", "--extra-index-url", "https://pypi.org/simple",
                "--index-strategy", "unsafe-best-match"]
    cmd += ["torch>=2.4", PACKAGE]
    cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    if cp.returncode != 0:
        raise ShowtimeError("installing CrisperWhisper failed", why=(cp.stdout or "")[-800:],
                            hint="check the connection and try again; the default model needs none of this")
    marker.write_text(PACKAGE + "\n", encoding="utf-8")
    return vpy


def _unbracket(t: str) -> str:
    """CrisperWhisper writes fillers as [UH] / [UM]: plain words here, so they are cut like any filler
    (a bracketed token would otherwise read as an audio event such as "(laughter)")."""
    import re
    m = re.match(r"^\[([A-Za-z]{1,6})\]([.,!?]*)$", t)
    if m:
        from .util import is_filler
        if is_filler(m.group(1)):
            return m.group(1).lower() + m.group(2)
    return t


def run(wav: Path, size: str, lang: Optional[str], threads: int,
        accept_license: bool = False) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Tokens in transcribe.py's engine format: [{"raw", "start", "end", "conf", "seg"}]."""
    check(accept_license)
    if size not in SIZES:
        raise ShowtimeError("unknown CrisperWhisper size %r" % size, hint="small, medium, turbo or large")
    vpy = ensure_env()
    out = Path(str(wav) + ".crisper-%s.json" % size)
    runner = paths()["cache"] / "crisper_runner.py"
    runner.parent.mkdir(parents=True, exist_ok=True)
    runner.write_text(RUNNER, encoding="utf-8")
    # PyTorch oversubscribes badly on big machines: at most 8 threads unless asked for more
    n = max(1, min(threads, int(os.environ.get("SHOWTIME_CRISPER_THREADS") or 8)))
    env = dict(os.environ, OMP_NUM_THREADS=str(n), MKL_NUM_THREADS=str(n), HF_HOME=str(paths()["hf"]),
               TOKENIZERS_PARALLELISM="false")
    info("transcribing with CrisperWhisper 2.0 %s (non-commercial licence; the first run downloads %s)"
         % (size, SIZES[size]))
    cp = subprocess.run([str(vpy), str(runner), str(wav), size, lang or "", str(out), str(n)], env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    if cp.returncode != 0 or not out.is_file():
        raise ShowtimeError("CrisperWhisper failed", why=(cp.stdout or "")[-800:],
                            hint="try again, or use the default model")
    d = json.loads(out.read_text(encoding="utf-8"))
    toks = [{"raw": " " + _unbracket(str(w["word"]).strip()), "start": w["start"], "end": w["end"],
             "conf": round(float(w.get("probability", 1.0)), 3), "seg": 0} for w in d.get("words", [])]
    return toks, {"language": d.get("language") or lang}

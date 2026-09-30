"""Model files the voice module needs, and lazy downloads of the optional ones.

Kokoro comes from `showtime setup`; Whisper is fetched before the first
transcription (st/lazy.py). Two more optional pieces are fetched on first
use (with a one-line notice), verified by size + sha256:

- the English CTC aligner (wav2vec2-base-960h, ONNX uint8-quantized, 95 MB, Apache-2.0)
- Piper voices for sherpa-onnx (60-115 MB each; commercially usable ones only)

Downloads reuse the installer's resumable, checksum-verified fetcher, which falls back to the
model mirror (st/mirror.py) when Hugging Face is blocked.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Dict, List, Optional

from ..common import ShowtimeError, home, human_size, info, paths

W2V_REV = "729c1a6730fb549c20a1c73a3d3f96f11020225e"
W2V_BASE = "https://huggingface.co/onnx-community/wav2vec2-base-960h-ONNX/resolve/%s/" % W2V_REV
W2V_VARIANTS = {
    # uint8 dynamic quantization: 95 MB, runs on every onnxruntime CPU build
    # (the "int8" export uses ConvInteger, which CPU onnxruntime lacks).
    "q8": ("onnx/model_quantized.onnx", "model_quantized.onnx", 95212816,
           "1d9a366c27b2966625cd5035ac3db8847c53bba617169912bb251b42975a3a22"),
    "fp32": ("onnx/model.onnx", "model.onnx", 377911891,
             "00b7cc69516c1ab63c429e63a2b543e4d42bb77441ec5b98ee935de175b00de1"),
}
W2V_VOCAB = ("vocab.json", "vocab.json", 358, "4178db26b3c7570f6a47f14ac6a1c7b32950b8c2800fb097287e53776934f1c5")


def _offline() -> bool:
    return os.environ.get("SHOWTIME_OFFLINE", "") not in ("", "0", "false", "no")


def aligner_variant() -> str:
    v = (os.environ.get("SHOWTIME_ALIGNER") or "q8").lower()
    return v if v in W2V_VARIANTS else "q8"


def aligner_model_name() -> str:
    return W2V_VARIANTS[aligner_variant()][1]


W2V_LICENSE = "Apache-2.0 (facebook/wav2vec2-base-960h; ONNX export by onnx-community)"


def kokoro_files() -> Dict[str, Optional[Path]]:
    """The Kokoro model to load: the timestamped fp16 export (current installs), else the fp32
    timestamped or stock exports an older install still has, or $SHOWTIME_KOKORO_MODEL."""
    d = paths()["kokoro"]
    candidates = [d / "kokoro-v1.0-timestamped-fp16.onnx", d / "kokoro-v1.0-timestamped.onnx"]
    stock = d / "kokoro-v1.0.onnx"
    voices = d / "voices-v1.0.bin"
    ts = next((c for c in candidates if c.is_file()), None)
    env_model = os.environ.get("SHOWTIME_KOKORO_MODEL")
    model = Path(env_model) if env_model else (ts or (stock if stock.is_file() else None))
    return {"model": model if model and model.is_file() else None,
            "voices": voices if voices.is_file() else None,
            "timestamped": ts}


def aligner_dir() -> Path:
    return paths()["models"] / "align" / "wav2vec2-base-960h"


def whisper_dir(name: str) -> Optional[Path]:
    d = paths()["whisper"] / name
    return d if (d / "model.bin").is_file() else None


def piper_dir(name: str) -> Path:
    return paths()["models"] / "piper" / ("vits-piper-" + name)


def _setup_module():
    p = paths()["setup"] / "setup.py"
    spec = importlib.util.spec_from_file_location("showtime_setup_voice", str(p))
    if spec is None or spec.loader is None:
        raise ShowtimeError("installer not found at %s" % p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def _fetch(url: str, dest: Path, sha: Optional[str], size: Optional[int], label: str) -> None:
    try:
        st = _setup_module()
        seeds = st.Seeds([os.environ.get("SHOWTIME_SEED_DIRS", "")] if os.environ.get("SHOWTIME_SEED_DIRS") else [])
        st.fetch(url, dest, sha, size, seeds, label)
    except ShowtimeError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ShowtimeError("download failed for %s: %s" % (label, e),
                            hint="check your connection and retry; files resume where they stopped. Behind a "
                                 "proxy that blocks the model hosts, set SHOWTIME_MODEL_MIRROR to a mirror URL "
                                 "or a folder holding the files")


def ensure_aligner(allow_download: bool = True) -> Optional[Path]:
    """Directory holding the aligner model + vocab.json, downloading if needed."""
    d = aligner_dir()
    files = [W2V_VARIANTS[aligner_variant()], W2V_VOCAB]
    missing = [f for f in files if not (d / f[1]).is_file() or (f[2] and (d / f[1]).stat().st_size != f[2])]
    if not missing:
        return d
    if not allow_download or _offline():
        return None
    total = sum(f[2] or 0 for f in missing)
    info("downloading the English word aligner (wav2vec2, %s, one time) to %s" % (human_size(total), d))
    for remote, local, size, sha in missing:
        _fetch(W2V_BASE + remote, d / local, sha, size, "aligner " + local)
    (d / "LICENSE.txt").write_text(W2V_LICENSE + "\nSource: " + W2V_BASE + "\n", encoding="utf-8")
    return d


def ensure_piper(name: str, allow_download: bool = True) -> Path:
    from .voices import PIPER_URL, PIPER_VOICES
    meta = PIPER_VOICES[name]
    d = piper_dir(name)
    if (d / (name + ".onnx")).is_file() and (d / "tokens.txt").is_file():
        return d
    if not allow_download or _offline():
        raise ShowtimeError("Piper voice %s is not installed" % name,
                            hint="run the command again online; it downloads once (%s)" % human_size(meta["size"]))
    st = _setup_module()
    arch = paths()["downloads"] / ("vits-piper-%s.tar.bz2" % name)
    info("downloading Piper voice %s (%s, %s, one time)" % (name, human_size(meta["size"]), meta["license"]))
    _fetch(PIPER_URL % name, arch, str(meta["sha256"]), int(meta["size"]), "piper " + name)
    d.parent.mkdir(parents=True, exist_ok=True)
    tmp = d.with_name(d.name + ".part")
    import shutil
    shutil.rmtree(str(tmp), ignore_errors=True)
    st.extract(arch, "tar.bz2", tmp, strip=1)
    shutil.rmtree(str(d), ignore_errors=True)
    os.replace(str(tmp), str(d))
    try:
        arch.unlink()
    except OSError:
        pass
    if not (d / (name + ".onnx")).is_file():
        cands: List[Path] = sorted(d.glob("*.onnx"))
        if not cands:
            raise ShowtimeError("Piper archive for %s had no .onnx model" % name)
    return d


def status() -> Dict[str, object]:
    k = kokoro_files()
    return {
        "kokoro_model": str(k["model"]) if k["model"] else None,
        "kokoro_timestamped": bool(k["timestamped"]),
        "kokoro_voices": str(k["voices"]) if k["voices"] else None,
        "aligner": str(aligner_dir()) if (aligner_dir() / aligner_model_name()).is_file() else None,
        "whisper": [n for n in ("small.en", "large-v3-turbo", "small", "base", "tiny.en") if whisper_dir(n)],
        "supertonic": (paths()["supertonic"] / "onnx" / "vocoder.onnx").is_file(),
        "piper": sorted(p.name.replace("vits-piper-", "") for p in (paths()["models"] / "piper").glob("vits-piper-*")
                        if not p.name.endswith(".part")) if (paths()["models"] / "piper").is_dir() else [],
        "home": str(home()),
    }

"""Model files for transcription, speech separation and the speaker cutout, fetched on first use.

Every entry lives in setup/manifest.json (id, url, size, sha256, licence; "tier": "lazy"),
so `showtime setup --full` installs the same files up front and a seed folder
(`setup --seed`) can supply them offline. `ensure(name)` is the first-use hook
(st/lazy.py does the fetching: "fetching parakeet-tdt-0.6b-v3-int8 (487 MB) for
transcription (one time; resumable, sha256-verified)").

    ITEMS        short model name -> manifest item id + facts the ASR code needs
    ensure(id)   the model folder/file, downloading it when needed
    present(id)  True when the files are already there (no network)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..common import ShowtimeError, home, skill_dir

# Parakeet-TDT 0.6B v3: the 25 European languages it was trained on (model card).
PARAKEET_V3_LANGS = {"bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu", "it", "lv", "lt",
                     "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv", "ru", "uk"}

# name -> facts. "item" is the manifest id; "path" is relative to the runtime home.
ITEMS: Dict[str, Dict[str, Any]] = {
    "parakeet-v2": {"item": "parakeet-tdt-0.6b-v2-int8", "engine": "parakeet",
                    "path": "models/sherpa/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
                    "check": "encoder.int8.onnx", "label": "Parakeet-TDT 0.6B v2 (English)",
                    "languages": {"en"}},
    "parakeet-v3": {"item": "parakeet-tdt-0.6b-v3-int8", "engine": "parakeet",
                    "path": "models/sherpa/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
                    "check": "encoder.int8.onnx", "label": "Parakeet-TDT 0.6B v3 (25 languages)",
                    "languages": PARAKEET_V3_LANGS},
    "silero-vad": {"item": "silero-vad-v5", "path": "models/sherpa/silero_vad_v5.onnx",
                   "label": "Silero VAD v5"},
    "mdx-voc-ft": {"item": "uvr-mdx-net-voc-ft", "path": "models/separate/UVR-MDX-NET-Voc_FT.onnx",
                   "label": "UVR MDX-Net vocal separator"},
    "modnet": {"item": "modnet", "path": "models/matte/modnet.onnx", "label": "MODNet portrait matting"},
}


def _offline() -> bool:
    return os.environ.get("SHOWTIME_OFFLINE", "") not in ("", "0", "false", "no")


def manifest_item(item_id: str) -> Dict[str, Any]:
    man = json.loads((skill_dir() / "setup" / "manifest.json").read_text(encoding="utf-8"))
    for it in man.get("items", []):
        if it.get("id") == item_id:
            return it
    raise ShowtimeError("model %s is not in the setup manifest" % item_id)


def item_bytes(item_id: str) -> int:
    try:
        return sum(int(f.get("size") or 0) for f in manifest_item(item_id).get("files", []))
    except (ShowtimeError, OSError, ValueError):
        return 0


def location(name: str) -> Path:
    return home() / ITEMS[name]["path"]


def present(name: str) -> bool:
    p = location(name)
    chk = ITEMS[name].get("check")
    return (p / chk).is_file() if chk else p.is_file()


def ensure(name: str, feature: str = "transcription", allow_download: bool = True) -> Path:
    """Path of model `name` (see ITEMS), fetching it on first use through the shared first-use fetcher
    (st/lazy.py: announced with its size, resumable, sha256-verified, seed folders, a lock against two
    processes fetching at once). Offline or on a failed download it raises a ShowtimeError whose fix names
    `showtime setup --full` / `--seed DIR --fetch <id>`."""
    meta = ITEMS[name]
    if present(name):
        return location(name)
    from .. import lazy
    lazy.ensure_item(meta["item"], feature, allow_download=allow_download and not _offline())
    if not present(name):
        raise ShowtimeError("%s was fetched but %s is missing" % (meta["label"], location(name)),
                            hint="run `showtime setup --fetch %s --force`" % meta["item"])
    return location(name)


def status() -> List[Dict[str, Any]]:
    """[{name, label, present, bytes}] for doctor/--json output."""
    return [{"name": n, "label": m["label"], "present": present(n), "bytes": item_bytes(m["item"])}
            for n, m in ITEMS.items()]

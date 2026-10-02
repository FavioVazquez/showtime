"""The model mirror: where a pinned model file can come from when its own host is blocked (stdlib only).

Agent sandboxes often sit behind an egress proxy that allows GitHub but answers 403 for Hugging Face or
GitHub LFS. setup/setup.py `fetch` (the one downloader behind setup, first-use fetches and the voice
models) asks this module for the other places a file lives and tries them in order:

  1. SHOWTIME_MODEL_MIRROR as a local folder: checked before any network, like a seed folder
  2. the primary URL, unless it already failed as blocked in this process
  3. SHOWTIME_MODEL_MIRROR as a base URL, then each base in mirror.json `mirrors`

Every copy, from any source, is verified by size and sha256 before it is installed. mirror.json lists
the mirrored files (primary URL, file name on the mirror, size, sha256, license); a URL that is not in
it has no mirror. SHOWTIME_MODEL_MIRROR=off turns the mirrors off. Several values are separated by commas.

The audio mirror (music_catalog.json, sfx_packs.json, library_manifest.json) works the same way but the
pinned files are not listed one by one here -- each caller (st/audio/music.py `fetch`, st/audio/library.py
`download`, used by st/audio/packs.py too) already knows its own id, kind ("music", "sfx" or "lib") and
file extension, and asks `audio_sources()` for the candidates to try, in the same order as above, keyed
by SHOWTIME_AUDIO_MIRROR and mirror.json's `audio` block. scripts/stage_audio_mirror.py builds its
release assets, named `<kind>--<id>.<ext>` (mirror.json `audio.naming`).
"""
from __future__ import annotations

import json
import os
import re
import socket
import ssl
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MANIFEST = Path(__file__).resolve().parent / "mirror.json"
ENV = "SHOWTIME_MODEL_MIRROR"
AUDIO_ENV = "SHOWTIME_AUDIO_MIRROR"

_data: Optional[Dict[str, Any]] = None
_by_url: Dict[str, Dict[str, Any]] = {}
_blocked: Dict[str, str] = {}          # host -> why, for this process: later files skip straight to a mirror


class Blocked(IOError):
    """The source refused or cannot be reached (proxy block, 403/404, no route): try the next one, do not retry."""


def load(data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """mirror.json, cached. Passing `data` replaces it (tests)."""
    global _data, _by_url
    if data is not None or _data is None:
        if data is None:
            try:
                data = json.loads(MANIFEST.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {"mirrors": [], "files": []}
        _data = data
        _by_url = {f["url"]: f for f in data.get("files") or []}
    return _data


def entry(url: str) -> Optional[Dict[str, Any]]:
    load()
    return _by_url.get(url)


def _env_values(name: str = ENV) -> List[str]:
    raw = (os.environ.get(name) or "").strip()
    return [v.strip() for v in raw.split(",") if v.strip()]


def disabled(name: str = ENV) -> bool:
    return any(v.lower() in ("off", "0", "no", "false", "none") for v in _env_values(name))


def _is_url(v: str) -> bool:
    return bool(re.match(r"^(https?|file)://", v, re.I))


def bases() -> List[str]:
    """Mirror base URLs in the order they are tried (SHOWTIME_MODEL_MIRROR first)."""
    if disabled():
        return []
    out: List[str] = []
    for b in [v for v in _env_values() if _is_url(v)] + list(load().get("mirrors") or []):
        b = b if b.endswith("/") else b + "/"
        if b not in out:
            out.append(b)
    return out


def local_dirs() -> List[Path]:
    if disabled():
        return []
    return [Path(os.path.expanduser(v)) for v in _env_values() if not _is_url(v)]


# --------------------------------------------------------------------------------------- audio mirror
def _audio() -> Dict[str, Any]:
    return load().get("audio") or {}


def audio_disabled() -> bool:
    return disabled(AUDIO_ENV)


def audio_bases() -> List[str]:
    """Audio mirror base URLs, in the order they are tried (SHOWTIME_AUDIO_MIRROR first)."""
    if audio_disabled():
        return []
    out: List[str] = []
    for b in [v for v in _env_values(AUDIO_ENV) if _is_url(v)] + list(_audio().get("mirrors") or []):
        b = b if b.endswith("/") else b + "/"
        if b not in out:
            out.append(b)
    return out


def audio_local_dirs() -> List[Path]:
    if audio_disabled():
        return []
    return [Path(os.path.expanduser(v)) for v in _env_values(AUDIO_ENV) if not _is_url(v)]


def audio_name(kind: str, item_id: str, ext: str) -> str:
    """The mirror file name for one audio item (mirror.json `audio.naming`, default `<kind>--<id>.<ext>`)."""
    tmpl = _audio().get("naming") or "<kind>--<id>.<ext>"
    return tmpl.replace("<kind>", kind).replace("<id>", item_id).replace("<ext>", ext.lstrip("."))


def audio_local_copy(kind: str, item_id: str, ext: str) -> Optional[Path]:
    """The mirror file for this item in a SHOWTIME_AUDIO_MIRROR folder, or None: the caller verifies it."""
    name = audio_name(kind, item_id, ext)
    for d in audio_local_dirs():
        p = d / name
        if p.is_file():
            return p
    return None


def audio_sources(kind: str, item_id: str, ext: str, primary_url: str) -> List[Any]:
    """Sources to try for one audio file, in order: a SHOWTIME_AUDIO_MIRROR folder copy (a Path, already
    on disk -- the caller still verifies it), the primary URL (a str, unless its host already failed as
    blocked in this process), then each base in `audio_bases()` (also a str) named by `audio_name()`."""
    out: List[Any] = []
    local = audio_local_copy(kind, item_id, ext)
    if local is not None:
        out.append(local)
    name = audio_name(kind, item_id, ext)
    mirrors = [b + name for b in audio_bases()]
    if not (mirrors and host(primary_url) in _blocked):
        out.append(primary_url)
    out.extend(mirrors)
    return out


def local_copy(url: str) -> Optional[Path]:
    """The mirror file for `url` in a SHOWTIME_MODEL_MIRROR folder (by its mirror name or its own name);
    the caller verifies it."""
    e = entry(url)
    names = ([e["file"]] if e else []) + [url.rsplit("/", 1)[-1]]
    for d in local_dirs():
        for n in names:
            p = d / n
            if p.is_file():
                return p
    return None


def host(url: str) -> str:
    m = re.match(r"^[a-z]+://([^/:]+)", url, re.I)
    return m.group(1).lower() if m else url


def sources(url: str) -> List[str]:
    """URLs to try for `url`, in order: the primary (unless its host is known blocked), then the mirrors."""
    e = entry(url)
    mirrors = [b + e["file"] for b in bases()] if e else []
    if mirrors and host(url) in _blocked:
        return mirrors
    return [url] + mirrors


def mark_blocked(url: str, why: str) -> None:
    _blocked[host(url)] = why


def reset() -> None:
    _blocked.clear()


def blocked_reason(exc: BaseException) -> Optional[str]:
    """A short reason when `exc` means this source will not serve the file (so: next source, no retry);
    None for errors worth retrying (timeouts, resets, a truncated body)."""
    if isinstance(exc, Blocked):
        return str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403, 404, 407, 410, 451):
            return "HTTP %d" % exc.code
        return None
    status = getattr(exc, "status", None)  # e.g. st/assets/net.py HTTPStatusError, raised after its own retries
    if isinstance(status, int):
        return "HTTP %d" % status if status in (401, 403, 404, 407, 410, 451) else None
    reason: Any = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    text = str(reason)
    if "Tunnel connection failed" in text or re.search(r"\b(403|407)\b", text):
        return "blocked by a proxy (%s)" % text.strip()[:80]
    if isinstance(reason, socket.gaierror):
        return "host name not resolved"
    if isinstance(reason, (ConnectionRefusedError, PermissionError)):
        return "connection refused"
    if isinstance(reason, ssl.SSLError) or isinstance(exc, (socket.timeout, TimeoutError)):
        return None
    return None


def describe_failure(label: str, url: str, tried: List[Tuple[str, str]], mirror_file: Optional[str] = None,
                     env: str = ENV) -> str:
    """The one error when every source failed: what is blocked, and the override.

    `mirror_file` names the mirror asset directly (the audio mirror: no per-url mirror.json entry to look
    up) and `env` names the override variable (SHOWTIME_AUDIO_MIRROR for audio); both default to the
    model mirror's own `entry(url)` lookup and SHOWTIME_MODEL_MIRROR."""
    parts = ["%s (%s)" % (host(u), why) for u, why in tried]
    msg = "could not download %s: %s" % (label, "; ".join(parts) or "no source")
    mf = mirror_file or ((entry(url) or {}).get("file") if env == ENV else None)
    if mf:
        msg += (". Allow one of these hosts in the sandbox's network settings, or set %s to a mirror URL or "
                "a folder holding %s" % (env, mf))
    elif any(why.startswith(("HTTP 403", "HTTP 407", "blocked")) for _u, why in tried):
        msg += ". %s is blocked here and this file has no mirror: allow it in the sandbox's network settings" % host(url)
    return msg

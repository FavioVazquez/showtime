"""Extra sound-effect packs (sfx_packs.json): fetched into the audio library on first use.

Each pack is a CC0 (or CC BY, with its exact credit) zip or file on its creator's site, pinned by URL,
size and sha256. A pack is installed the first time it is needed: a mix that names one of its
items (`"lib": "oga-keyboard-typing/..."`), a mix library search in its category that finds nothing
installed, `showtime audio packs fetch <id|category>`, or `showtime setup --full`. Installed items
join ~/.showtime/library/catalog.json like every other library source (analysed: hit point,
loudness, category, tags), so `audio lib search` finds them and credits work as usual.

sfx_packs.json (schema showtime.audio.packs/1):
  hosts  {host: {delay_s, rule}}   the only hosts packs may come from, and how politely
  packs  [{id, title, author, source, source_url (the pack page), url (the file), type (zip|file), bytes,
           sha256, license (CC0-1.0 | CC-BY-4.0 | CC-BY-3.0 | CC-PDDC), evidence (where the page says so),
           attribution (exact credit, required for CC BY), credit_optional, kind (sfx|ambience),
           category (ui|transition|impact|foley|fx|ambience|musical), tags[], files, formats[], include?,
           notes?}]
"""
from __future__ import annotations

import concurrent.futures as cf
import fnmatch
import json
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..common import ShowtimeError, human_size, log, read_json, warn, write_json

SCHEMA = "showtime.audio.packs/1"
PACKS = Path(__file__).with_name("sfx_packs.json")
ALLOWED_LICENSES = ("CC0-1.0", "CC-BY-4.0", "CC-BY-3.0", "CC-PDDC")
CATEGORIES = ("ui", "transition", "impact", "foley", "fx", "ambience", "musical")


def load(path: Optional[Path] = None) -> Dict[str, Any]:
    import os
    p = Path(path or os.environ.get("SHOWTIME_SFX_PACKS") or PACKS)
    d = json.loads(p.read_text(encoding="utf-8"))
    if d.get("schema") != SCHEMA:
        raise ShowtimeError("%s is not a %s file" % (p, SCHEMA))
    return d


def validate(doc: Optional[Dict[str, Any]] = None) -> List[str]:
    doc = doc if doc is not None else load()
    errs: List[str] = []
    ids = set()
    hosts = doc.get("hosts") or {}
    for pk in doc.get("packs") or []:
        pre = "pack %s: " % pk.get("id")
        for k in ("id", "title", "author", "source_url", "url", "type", "bytes", "sha256", "license", "evidence",
                  "kind", "category", "tags"):
            if pk.get(k) in (None, "", []):
                errs.append(pre + "missing " + k)
        if pk.get("id") in ids:
            errs.append(pre + "duplicate id")
        ids.add(pk.get("id"))
        if pk.get("license") not in ALLOWED_LICENSES:
            errs.append(pre + "license %r not allowed" % pk.get("license"))
        if str(pk.get("license", "")).startswith("CC-BY") and not (pk.get("attribution") or "").strip():
            errs.append(pre + "a CC BY pack needs its attribution text")
        if pk.get("category") not in CATEGORIES:
            errs.append(pre + "category must be one of %s" % ", ".join(CATEGORIES))
        if pk.get("type") not in ("zip", "file"):
            errs.append(pre + "type must be zip or file")
        if pk.get("kind") not in ("sfx", "ambience"):
            errs.append(pre + "kind must be sfx or ambience")
        host = (urllib.parse.urlparse(str(pk.get("url") or "")).hostname or "")
        if not str(pk.get("url", "")).startswith("https://") or not any(host == h or host.endswith("." + h) for h in hosts):
            errs.append(pre + "url must be https on a listed host (%s)" % ", ".join(hosts))
        if not (isinstance(pk.get("sha256"), str) and len(pk["sha256"]) == 64):
            errs.append(pre + "sha256 must be 64 hex characters")
        if not (isinstance(pk.get("bytes"), int) and pk["bytes"] > 0):
            errs.append(pre + "bytes must be a positive integer")
    return errs


def _state() -> Dict[str, Any]:
    from . import library
    return read_json(library.library_dir() / "state.json", {"sources": {}})


def installed_ids() -> List[str]:
    from . import library
    lib = library.library_dir()
    st = _state().get("sources") or {}
    return [sid for sid, s in st.items() if all((lib / f).is_file() for f in s.get("files", []))]


def matching(query: Any = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
    """Packs by id glob, category or words in title/tags."""
    doc = load()
    out = []
    words = [w.lower() for w in (query if isinstance(query, list) else str(query or "").replace(",", " ").split()) if w]
    for pk in doc["packs"]:
        if category and pk["category"] != category:
            continue
        if words:
            hay = " ".join([pk["id"], pk["title"].lower(), pk["category"], " ".join(pk["tags"])])
            if not all(fnmatch.fnmatch(pk["id"], w) or w in hay for w in words):
                continue
        out.append(pk)
    return out


def install(pks: Iterable[Dict[str, Any]], reason: Optional[str] = None, force: bool = False,
            workers: int = 3) -> Dict[str, Any]:
    """Download, verify, unpack and analyse packs into the library catalog (announced, idempotent)."""
    from ..assets import net
    from . import library
    pks = list(pks)
    have = set(installed_ids())
    todo = [p for p in pks if force or p["id"] not in have]
    rep: Dict[str, Any] = {"installed": [], "skipped": [p["id"] for p in pks if p not in todo], "failed": []}
    if not todo:
        return rep
    if net.offline():
        raise ShowtimeError("sound pack(s) %s are not installed and SHOWTIME_OFFLINE=1 is set" % ", ".join(p["id"] for p in todo),
                            hint="run `showtime audio packs fetch %s` while online" % " ".join(p["id"] for p in todo))
    doc = load()
    man = {"user_agent": net.USER_AGENT, "host_delays": {h: v.get("delay_s", 1.0) for h, v in (doc.get("hosts") or {}).items()}}
    lib = library.library_dir()
    lib.mkdir(parents=True, exist_ok=True)
    state = _state()
    cat = library.load_catalog(required=False)
    items = {it["id"]: it for it in cat.get("items", [])}
    for pk in todo:
        log("fetching sound pack %s (%s, %s, %s) for %s" % (pk["id"], pk["category"], human_size(pk["bytes"]),
                                                            pk["license"], reason or "the library"))
        src = dict(pk, tier="packs", evidence_url=pk.get("source_url"))
        try:
            files = library.install_source(src, man)
            for k in [k for k, v in items.items() if v.get("source_id") == pk["id"]]:
                items.pop(k)
            with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
                infos = list(ex.map(lambda f: library.analyze_file(f, src["kind"], src), files))
            for f, info in zip(files, infos):
                it = library._item_for(src, f, info)
                if it.get("category") in (None, "fx") and pk["category"] != "fx":
                    it["category"] = pk["category"]
                items[it["id"]] = it
            state.setdefault("sources", {})[pk["id"]] = {
                "url": pk["url"], "sha256": pk["sha256"], "tier": "packs",
                "files": [f.relative_to(lib).as_posix() for f in files], "installed": time.strftime("%Y-%m-%dT%H:%M:%S")}
            write_json(lib / "state.json", state)
            cat["items"] = sorted(items.values(), key=lambda it: it["id"])
            library.save_catalog(cat)
            rep["installed"].append(pk["id"])
        except ShowtimeError as e:
            warn("%s: %s" % (pk["id"], e))
            rep["failed"].append({"id": pk["id"], "error": str(e)})
    try:
        full = library.load_manifest()
        full = dict(full, sources=list(full.get("sources", [])) + [dict(p, tier="packs") for p in doc["packs"]])
        library.write_credits_sources(full, library.load_catalog(required=False))
    except Exception as e:  # noqa: BLE001 - the sources summary is a convenience
        warn("could not update CREDITS-SOURCES.md: %s" % e)
    return rep


def install_for_ref(ref: Any) -> bool:
    """Install the uninstalled pack(s) a mix library reference points at. True when something was installed."""
    have = set(installed_ids())
    cands: List[Dict[str, Any]] = []
    doc = load()
    if isinstance(ref, str) or (isinstance(ref, dict) and ref.get("id")):
        rid = ref if isinstance(ref, str) else ref["id"]
        cands = [p for p in doc["packs"] if rid == p["id"] or rid.startswith(p["id"] + "/")]
    elif isinstance(ref, dict):
        q = ref.get("search") or ref
        cats = q.get("category")
        cands = matching(q.get("query") or q.get("words"), cats if isinstance(cats, str) else None)
    cands = [p for p in cands if p["id"] not in have]
    if not cands:
        return False
    rep = install(cands, reason="the mix")
    return bool(rep["installed"])


def hint_for(category: Optional[str], words: Optional[str]) -> Optional[str]:
    """A one-line hint about uninstalled packs that match a library search."""
    try:
        have = set(installed_ids())
        pks = [p for p in matching(words, category) if p["id"] not in have]
    except Exception:  # noqa: BLE001
        return None
    if not pks:
        return None
    size = sum(p["bytes"] for p in pks)
    return "%d more sound pack(s) match (%s, %s): showtime audio packs fetch %s" % (
        len(pks), ", ".join(p["id"] for p in pks[:3]) + (" ..." if len(pks) > 3 else ""), human_size(size),
        " ".join(p["id"] for p in pks[:3]) if len(pks) <= 3 else "--category %s" % (category or pks[0]["category"]))

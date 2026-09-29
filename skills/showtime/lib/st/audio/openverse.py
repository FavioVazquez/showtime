"""Live Openverse audio search: "find five more like this" beyond the curated catalog.

Openverse indexes CC-licensed audio from Freesound, Wikimedia Commons and Jamendo. Anonymous use is
limited to about 20 requests a minute and 200 a day, and its terms forbid scraping, so this is an
interactive search for one project, never a crawler: responses are cached for a day in
~/.showtime/cache/http, and only CC BY and CC0 / public-domain results are shown (never NC or ND).

Only Freesound and Wikimedia Commons are searched by default. Jamendo results are left out: Jamendo's
own terms put conditions on top of the artists' CC licence (a paid licence for commercial use through
Jamendo Licensing, and download rules for its file storage), and tracks enrolled in its licensing
program can be claimed on video platforms, so a CC BY tag on Openverse is not enough to know that a
published video is in the clear. `source="jamendo"` still searches it on request (with a warning), for
someone who has checked the artist's terms. Openverse only sets `category` (music, sound_effect ...)
on Jamendo results, so it is ignored for the default sources.

`fetch()` downloads one result into a project folder and writes `<file>.license.json` (title,
creator, license, landing page and the TASL credit), so `audio mix` credits it automatically.
Unlike catalog tracks nobody has listened to these: preview before using one.
"""
from __future__ import annotations

import re
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..common import ShowtimeError, log

API = "https://api.openverse.org/v1/audio/"
DEFAULT_SOURCES = ("freesound", "wikimedia_audio")
SOURCES = ("freesound", "wikimedia_audio", "jamendo")
SOURCE_ALIASES = {"wikimedia": "wikimedia_audio", "commons": "wikimedia_audio", "wikimedia-commons": "wikimedia_audio"}
JAMENDO_NOTE = ("Jamendo results are included on request: Jamendo's own terms add conditions to commercial use and "
                "its licensing program can claim videos, so check the artist's terms before publishing")


def sources(source: Optional[str]) -> List[str]:
    """The Openverse sources to search: Freesound and Wikimedia Commons unless asked (comma list)."""
    if not source:
        return list(DEFAULT_SOURCES)
    out = []
    for w in re.split(r"[,\s]+", source.strip().lower()):
        if not w:
            continue
        w = SOURCE_ALIASES.get(w, w)
        if w not in SOURCES:
            raise ShowtimeError("unknown Openverse source %r" % w, hint="one of: freesound, wikimedia, jamendo")
        if w not in out:
            out.append(w)
    return out or list(DEFAULT_SOURCES)
LICENSE_SPDX = {("by", "4.0"): "CC-BY-4.0", ("by", "3.0"): "CC-BY-3.0", ("by", "2.5"): "CC-BY-2.5",
                ("by", "2.0"): "CC-BY-2.0", ("cc0", "1.0"): "CC0-1.0", ("pdm", "1.0"): "CC-PDM-1.0"}


def _spdx(r: Dict[str, Any]) -> Optional[str]:
    return LICENSE_SPDX.get((str(r.get("license") or "").lower(), str(r.get("license_version") or "")))


def credit(r: Dict[str, Any]) -> str:
    """TASL credit: '"Title" by Creator (landing page), licensed under CC BY 3.0: <deed>'."""
    lic = _spdx(r) or r.get("license")
    label = {"CC-BY-4.0": "CC BY 4.0", "CC-BY-3.0": "CC BY 3.0", "CC-BY-2.5": "CC BY 2.5", "CC-BY-2.0": "CC BY 2.0",
             "CC0-1.0": "CC0 1.0", "CC-PDM-1.0": "Public Domain Mark 1.0"}.get(lic, str(lic))
    return "“%s” by %s (%s), licensed under %s: %s" % (
        (r.get("title") or "untitled").strip(), (r.get("creator") or "unknown").strip(), r.get("foreign_landing_url") or "",
        label, r.get("license_url") or "")


def search(words: str, category: str = "", licenses: str = "by,cc0", limit: int = 10,
           min_dur: Optional[float] = None, max_dur: Optional[float] = None, source: Optional[str] = None) -> List[Dict[str, Any]]:
    from ..assets import net
    if not words.strip():
        raise ShowtimeError("give some words to search for, e.g. `audio music openverse calm piano`")
    bad = [l for l in licenses.split(",") if l.strip() not in ("by", "cc0", "pdm")]
    if bad:
        raise ShowtimeError("only CC BY and CC0 / public-domain results are allowed (got %s)" % ",".join(bad),
                            hint="non-commercial (nc) and no-derivatives (nd) music cannot be used in videos you publish")
    params = {"q": words, "license": licenses, "page_size": min(20, max(1, int(limit))), "filter_dead": "true",
              "mature": "false"}
    srcs = sources(source)
    params["source"] = ",".join(srcs)
    if category and "jamendo" in srcs:      # Openverse only categorises Jamendo results
        params["category"] = category
    if "jamendo" in srcs:
        from ..common import warn
        warn(JAMENDO_NOTE)
    data = net.get_json(API + "?" + urllib.parse.urlencode(params), ttl=86400)
    out = []
    for r in data.get("results") or []:
        if r.get("source") not in srcs:
            continue
        spdx = _spdx(r)
        if not spdx:
            continue
        d = (r.get("duration") or 0) / 1000.0
        if min_dur and d < min_dur or max_dur and d > max_dur:
            continue
        tags = [t.get("name") for t in r.get("tags") or [] if t.get("name")]
        out.append({"id": "openverse:" + r["id"], "title": r.get("title"), "creator": r.get("creator"),
                    "license": spdx, "duration": round(d, 1), "source": r.get("source"),
                    "landing_url": r.get("foreign_landing_url"), "file_url": r.get("url"),
                    "vocals": bool(set(tags) & {"male", "female", "vocal", "vocals", "singer", "voice"}),
                    "tags": tags[:10], "genres": r.get("genres") or [], "credit": credit(r), "_raw": r})
    return out[:limit]


def fetch(result_id: str, dest_dir: Path) -> Dict[str, Any]:
    """Download one search result into dest_dir with its license sidecar."""
    from ..assets import licenses, net
    oid = result_id.split(":", 1)[1] if result_id.startswith("openverse:") else result_id
    if not re.fullmatch(r"[0-9a-f-]{36}", oid):
        raise ShowtimeError("not an Openverse audio id: %r" % result_id, hint="ids look like openverse:<uuid>")
    r = net.get_json(API + oid + "/", ttl=86400)
    spdx = _spdx(r)
    if not spdx:
        raise ShowtimeError("%s is licensed %s %s, which showtime does not use" % (result_id, r.get("license"),
                                                                                r.get("license_version")))
    if r.get("source") == "jamendo":
        from ..common import warn
        warn(JAMENDO_NOTE)
    dest_dir = Path(dest_dir)
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", "%s-%s" % (r.get("creator") or "artist", r.get("title") or oid)).strip("-")[:80]
    ext = (r.get("filetype") or "mp3").lower()
    ext = "mp3" if ext.startswith("mp3") else ext
    out = dest_dir / ("%s.%s" % (name, ext))
    log("fetching %s by %s from %s" % (r.get("title"), r.get("creator"), r.get("source")))
    info = net.download(r["url"], out, max_bytes=80 << 20, timeout=120)
    side = licenses.write_sidecar(out, {"source": "openverse/%s" % r.get("source"), "id": "openverse:" + oid,
                                        "title": r.get("title"), "author": r.get("creator"),
                                        "author_url": r.get("creator_url"), "license": spdx,
                                        "license_url": r.get("license_url"), "landing_url": r.get("foreign_landing_url"),
                                        "file_url": r.get("url"), "sha256": info["sha256"], "credit": credit(r)})
    return {"path": str(out), "license_file": str(side), "license": spdx, "credit": credit(r), "bytes": info["bytes"]}

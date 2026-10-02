#!/usr/bin/env python3
"""Stage the audio mirror's release assets (stdlib only, any OS, Python 3.8+).

The real music, sound-effect packs and audio-library files showtime fetches on first use are pinned
(URL, size, sha256, license) in three files next to skills/showtime/lib/st/audio: music_catalog.json
`tracks`, sfx_packs.json `packs` and library_manifest.json `sources`. Their hosts (opengameart.org,
scottbuckley.com.au, incompetech.com, archive.org, upload.wikimedia.org, bigsoundbank.com, kenney.nl)
are exactly the kind of site an agent sandbox's egress proxy blocks, so this script downloads every one
of them from its primary (honouring each host's own politeness rule: OpenGameArt's 10 s, Scott Buckley's
one-at-a-time -- SHOWTIME_AUDIO_MIRROR is forced off here, like stage_model_mirror.py does for models),
verifies size and sha256, writes LICENSES.txt (title, artist/author, license, license_url, source page
and attribution, then the license texts) and SHA256SUMS, and prints the `gh release create` / `gh
release upload` commands. It uploads nothing: a person runs those commands.

The owner has Scott Buckley's permission to mirror his tracks in bulk (his library's own terms ask
agents and automated tools never to bulk-download it from his site; the showtime runtime itself still
fetches his tracks one at a time, on first use, same as before -- this script's bulk staging is a
one-time, permissioned exception, printed below).

    python scripts/stage_audio_mirror.py                                # every pinned audio file, into ./audio-mirror
    python scripts/stage_audio_mirror.py --out /tmp/am --only 'music--buckley-*'
    python scripts/stage_audio_mirror.py --kind sfx                     # only the sound-effect packs
    python scripts/stage_audio_mirror.py --seed ~/.showtime             # reuse verified copies from an install
    python scripts/stage_audio_mirror.py --pin                          # first pin library sources lacking size/sha256

--pin runs the library's own maintainer pin (download each unpinned source, write its bytes and sha256
into library_manifest.json) before staging, so those sources can be mirrored too; commit the updated
library_manifest.json with the release.

Exit code 0 = every file staged and verified, 1 = a file failed, 2 = bad usage.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "showtime"
AUDIO_DIR = SKILL / "lib" / "st" / "audio"
MIRROR_JSON = SKILL / "lib" / "st" / "mirror.json"
GH_REPO = "FavioVazquez/showtime"
SPDX_TEXT = "https://raw.githubusercontent.com/spdx/license-list-data/main/text/%s.txt"
GITHUB_RELEASE_ASSET_LIMIT = 1000  # https://docs.github.com/en/repositories/releasing-projects-on-github/ ...
                                   # ... linking-to-releases says a release supports up to 1,000 assets (checked
                                   # 2026; if this changed, treat this constant, not the behaviour below, as stale)

LICENSE_URLS = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-3.0": "https://creativecommons.org/licenses/by/3.0/",
    "CC-PDDC": "https://creativecommons.org/licenses/publicdomain/",
    "CC-PDM-1.0": "https://creativecommons.org/publicdomain/mark/1.0/",
}


def _naming() -> str:
    data = json.loads(MIRROR_JSON.read_text(encoding="utf-8"))
    return (data.get("audio") or {}).get("naming") or "<kind>--<id>.<ext>"


def mirror_name(kind: str, item_id: str, ext: str) -> str:
    return _naming().replace("<kind>", kind).replace("<id>", item_id).replace("<ext>", ext.lstrip("."))


def _ext_of(url: str) -> str:
    name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name
    return (Path(name).suffix.lstrip(".") or "bin").lower()


# --------------------------------------------------------------------------------------------- items
def music_items() -> List[Dict[str, Any]]:
    cat = json.loads((AUDIO_DIR / "music_catalog.json").read_text(encoding="utf-8"))
    sources = cat.get("sources") or {}
    out = []
    for t in cat.get("tracks") or []:
        if t.get("status") == "vetoed":
            continue
        src = sources.get(t["source"], {})
        fetch = src.get("fetch") or {}
        ext = t.get("format") or _ext_of(t["file_url"])
        out.append({
            "kind": "music", "id": t["id"], "title": t["title"], "author": t["artist"], "url": t["file_url"],
            "bytes": t["bytes"], "sha256": t["sha256"], "ext": ext, "license": t["license"],
            "license_url": t.get("license_url") or LICENSE_URLS.get(t["license"], ""),
            "source_page": t.get("landing_url") or src.get("homepage") or "",
            "attribution": t.get("attribution") or t.get("credit_optional") or "",
            "delay_s": float(fetch.get("delay_s", 1.0)), "bulk": fetch.get("bulk", True) is not False,
            "bulk_note": "Scott Buckley's library (one track per request, never bulk; mirroring it in bulk here is "
                        "with his explicit permission -- see CHANGELOG.md)" if fetch.get("bulk") is False else None,
        })
    return out


def sfx_items() -> List[Dict[str, Any]]:
    doc = json.loads((AUDIO_DIR / "sfx_packs.json").read_text(encoding="utf-8"))
    hosts = doc.get("hosts") or {}
    out = []
    for pk in doc.get("packs") or []:
        host = urllib.parse.urlparse(pk["url"]).hostname or ""
        delay = next((v.get("delay_s", 1.0) for h, v in hosts.items() if host == h or host.endswith("." + h)), 1.0)
        out.append({
            "kind": "sfx", "id": pk["id"], "title": pk["title"], "author": pk["author"], "url": pk["url"],
            "bytes": pk["bytes"], "sha256": pk["sha256"], "ext": _ext_of(pk["url"]), "license": pk["license"],
            "license_url": LICENSE_URLS.get(pk["license"], ""), "source_page": pk.get("source_url") or "",
            "attribution": pk.get("attribution") or pk.get("credit_optional") or "",
            "delay_s": float(delay), "bulk": True, "bulk_note": None,
        })
    return out


def lib_items() -> List[Dict[str, Any]]:
    man = json.loads((AUDIO_DIR / "library_manifest.json").read_text(encoding="utf-8"))
    delays = man.get("host_delays") or {}
    out = []
    skipped = 0
    for s in man.get("sources") or []:
        if not s.get("bytes") or not s.get("sha256"):
            skipped += 1  # not pinned yet (library.py `pin()` fills these in as sources are added)
            continue
        host = urllib.parse.urlparse(s["url"]).hostname or ""
        delay = next((v for h, v in delays.items() if host == h or host.endswith("." + h)), 0.5)
        out.append({
            "kind": "lib", "id": s["id"], "title": s["id"], "author": s.get("credit_optional") or s["id"],
            "url": s["url"], "bytes": s["bytes"], "sha256": s["sha256"], "ext": _ext_of(s["url"]),
            "license": s["license"], "license_url": LICENSE_URLS.get(s["license"], ""),
            "source_page": s.get("source_url") or s.get("evidence_url") or "",
            "attribution": s.get("attribution") or s.get("credit_optional") or "",
            "delay_s": float(delay), "bulk": True, "bulk_note": None,
        })
    if skipped:
        print("note: %d library source(s) are not pinned yet (no bytes/sha256) and are skipped here; "
             "`showtime audio lib pin` fills those in" % skipped, file=sys.stderr)
    return out


def all_items() -> List[Dict[str, Any]]:
    items = music_items() + sfx_items() + lib_items()
    for it in items:
        it["file"] = mirror_name(it["kind"], it["id"], it["ext"])
    return items


# --------------------------------------------------------------------------------------------- download
class Seeds:
    """A local file with a pinned item's exact size and sha256 (an existing install, ~/.showtime, a
    folder of previously staged files), matched without re-hashing every candidate twice."""

    SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv"}

    def __init__(self, dirs: List[str]) -> None:
        self.dirs = [Path(os.path.expanduser(d)) for d in dirs if d]
        self._index: Optional[Dict[int, List[Path]]] = None

    def _build(self) -> Dict[int, List[Path]]:
        idx: Dict[int, List[Path]] = {}
        for root in self.dirs:
            if not root.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(str(root)):
                dirnames[:] = [d for d in dirnames if d not in self.SKIP]
                for fn in filenames:
                    p = Path(dirpath) / fn
                    try:
                        n = p.stat().st_size
                    except OSError:
                        continue
                    if n > 0:
                        idx.setdefault(n, []).append(p)
        return idx

    def find(self, size: int, sha: str) -> Optional[Path]:
        if not self.dirs:
            return None
        if self._index is None:
            self._index = self._build()
        for cand in self._index.get(size, []):
            try:
                if _sha256(cand) == sha:
                    return cand
            except OSError:
                continue
        return None


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_SSL = ssl.create_default_context()
_last_hit: Dict[str, float] = {}


UA = "showtime-stage-audio-mirror/0.2 (https://github.com/FavioVazquez/showtime) python-urllib"
# Hosts with no delay of their own in the catalogs that still throttle bursts of large files.
MIN_DELAY = {"upload.wikimedia.org": 5.0}


def _polite(url: str, delay: float) -> None:
    host = urllib.parse.urlparse(url).hostname or ""
    delay = max(delay, MIN_DELAY.get(host, 0.0))
    wait = _last_hit.get(host, 0.0) + delay - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()


def fetch_primary(it: Dict[str, Any], dest: Path, seeds: Seeds, retries: int = 4) -> str:
    """Ensure `dest` holds `it`'s pinned bytes, from a seed or `it["url"]` (never a mirror: this script
    builds the mirror). Returns 'present' | 'seeded' | 'downloaded'."""
    if dest.is_file() and dest.stat().st_size == it["bytes"] and _sha256(dest) == it["sha256"]:
        return "present"
    seed = seeds.find(it["bytes"], it["sha256"])
    if seed is not None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        tmp.write_bytes(seed.read_bytes())
        os.replace(str(tmp), str(dest))
        return "seeded"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    last_err: Optional[BaseException] = None
    for attempt in range(1, retries + 1):
        try:
            _polite(it["url"], it["delay_s"])
            # Wikimedia's user-agent policy asks for a contact; without one its rate limit is much stricter.
            req = urllib.request.Request(it["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120, context=_SSL) as r, open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
            got_size = tmp.stat().st_size
            if got_size != it["bytes"]:
                raise IOError("size mismatch: got %d, expected %d" % (got_size, it["bytes"]))
            got_sha = _sha256(tmp)
            if got_sha != it["sha256"]:
                raise IOError("sha256 mismatch: got %s, expected %s" % (got_sha, it["sha256"]))
            os.replace(str(tmp), str(dest))
            return "downloaded"
        except Exception as e:  # noqa: BLE001 - retried, then reported by the caller
            last_err = e
            try:
                tmp.unlink()
            except OSError:
                pass
            if attempt < retries:
                # 429/503: wait what the host asks (Retry-After) or back off for minutes, not seconds --
                # upload.wikimedia.org throttles a burst of full-size files for a while.
                code = getattr(e, "code", None)
                if code in (429, 503):
                    ra = (getattr(e, "headers", None) or {}).get("Retry-After") or ""
                    time.sleep(float(ra) if ra.strip().isdigit() else 60 * attempt)
                else:
                    time.sleep(2 * attempt)
    raise IOError(str(last_err))


# --------------------------------------------------------------------------------------------- output
def _spdx_ids(items: List[Dict[str, Any]]) -> List[str]:
    return sorted({it["license"] for it in items if it["license"]})


def _license_text(spdx: str) -> str:
    try:
        req = urllib.request.Request(SPDX_TEXT % spdx, headers={"User-Agent": "showtime-stage-audio-mirror"})
        with urllib.request.urlopen(req, timeout=30, context=_SSL) as r:
            return r.read().decode("utf-8", "replace").strip()
    except Exception as e:  # noqa: BLE001
        return "(text not fetched: %s; see https://spdx.org/licenses/%s.html)" % (e, spdx)


def licenses_txt(items: List[Dict[str, Any]], tag: str) -> str:
    out = ["showtime audio mirror (%s)" % tag, "",
           "These files are unmodified copies of real music tracks, sound-effect packs and audio-library files,",
           "mirrored so showtime can fetch them where their own creators' hosts are blocked. Each keeps its own",
           "license, listed below with its source page and attribution. The full license texts follow.", ""]
    for it in sorted(items, key=lambda i: i["file"]):
        out += ["%s" % it["file"],
                "  item:        %s (%s)" % (it["title"], it["kind"]),
                "  by:          %s" % it["author"],
                "  license:     %s (%s)" % (it["license"], it["license_url"]),
                "  attribution: %s" % (it["attribution"] or "none required"),
                "  source:      %s" % it["source_page"],
                "  original:    %s" % it["url"],
                "  size:        %d bytes" % it["bytes"],
                "  sha256:      %s" % it["sha256"], ""]
    for i in _spdx_ids(items):
        out += ["=" * 78, i, "=" * 78, ""]
        out += [_license_text(i) if not i.startswith("LicenseRef-") else
                "Released into the public domain; no license terms apply. See the source links above.", ""]
    return "\n".join(out) + "\n"


def commands(out_dir: Path, names: List[str], tag: str) -> List[str]:
    q = (lambda s: '"%s"' % s) if os.name == "nt" else (lambda s: "'%s'" % s)
    notes = ("Unmodified copies of real music, sound effects and audio-library files (see LICENSES.txt) that "
            "showtime downloads when their creators' own hosts are blocked. Not a showtime release.")
    create = ("gh release create %s --repo %s --title %s --notes %s --latest=false"
              % (tag, GH_REPO, q("showtime audio mirror (%s)" % tag), q(notes)))
    # gh release upload takes a file list on the command line: split across calls if a shell's argv limit is a
    # concern, but a few hundred short names is well inside getconf ARG_MAX on every platform showtime supports.
    upload = "gh release upload %s --repo %s --clobber %s" % (tag, GH_REPO, " ".join(q(n) for n in names))
    return ["cd %s" % q(str(out_dir)), create, upload]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="audio-mirror", help="staging folder (default ./audio-mirror)")
    ap.add_argument("--only", action="append", default=[], metavar="GLOB", help="only mirror files matching")
    ap.add_argument("--kind", choices=("music", "sfx", "lib"), help="only this kind")
    ap.add_argument("--seed", action="append", default=[], metavar="DIR",
                    help="reuse sha256-verified copies from DIR (e.g. an existing ~/.showtime)")
    ap.add_argument("--tag", default=None, help="release tag (default: mirror.json audio.tag, or audio-v1)")
    ap.add_argument("--pin", action="store_true",
                    help="first pin library sources that lack bytes/sha256 (writes library_manifest.json)")
    a = ap.parse_args(argv)
    os.environ["SHOWTIME_AUDIO_MIRROR"] = "off"   # stage from the primaries only
    if a.pin:
        sys.path.insert(0, str(SKILL / "lib"))
        from st.audio import library   # noqa: E402 - the library's own maintainer pin, not a second copy
        res = library.pin(tier=library.TIERS[-1])
        print("pinned %d library source(s); commit skills/showtime/lib/st/audio/library_manifest.json"
              % len(res.get("pinned") or res.get("done") or []))
    mdata = json.loads(MIRROR_JSON.read_text(encoding="utf-8"))
    tag = a.tag or (mdata.get("audio") or {}).get("tag") or "audio-v1"
    items = all_items()
    if a.kind:
        items = [it for it in items if it["kind"] == a.kind]
    if a.only:
        items = [it for it in items if any(fnmatch.fnmatch(it["file"], g) for g in a.only)]
    if not items:
        print("no audio item matches --kind/--only", file=sys.stderr)
        return 2
    seen_bulk_note = set()
    for it in items:
        if it.get("bulk_note") and it["source_page"] not in seen_bulk_note:
            print("note: %s" % it["bulk_note"])
            seen_bulk_note.add(it["source_page"])
    out_dir = Path(a.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    seeds = Seeds([os.path.expanduser(s) for s in a.seed])
    failed: List[str] = []
    for it in items:
        dest = out_dir / it["file"]
        try:
            how = fetch_primary(it, dest, seeds)
        except Exception as e:  # noqa: BLE001
            print("FAIL %s: %s" % (it["file"], e), file=sys.stderr)
            failed.append(it["file"])
            continue
        print("ok   %-72s %11d  %s" % (it["file"], it["bytes"], how))
    if failed:
        print("\n%d file(s) failed: %s" % (len(failed), ", ".join(failed)), file=sys.stderr)
        return 1
    staged = [it for it in items if (out_dir / it["file"]).is_file()]
    (out_dir / "LICENSES.txt").write_text(licenses_txt(staged, tag), encoding="utf-8")
    (out_dir / "SHA256SUMS").write_text("".join("%s  %s\n" % (it["sha256"], it["file"]) for it in
                                                sorted(staged, key=lambda i: i["file"])), encoding="utf-8")
    total = sum(it["bytes"] for it in staged)
    names = [it["file"] for it in staged] + ["LICENSES.txt", "SHA256SUMS"]
    print("\nstaged %d files, %.1f MB, in %s" % (len(staged), total / 1e6, out_dir))
    if len(names) > GITHUB_RELEASE_ASSET_LIMIT:
        print("\nwarning: %d assets exceeds GitHub's per-release limit (%d; see GitHub's release docs -- this "
             "script assumes that figure, confirm it is still current): split the upload across more than one "
             "release tag." % (len(names), GITHUB_RELEASE_ASSET_LIMIT), file=sys.stderr)
    if a.only or a.kind:
        print("(a subset: stage every file before uploading)")
    print("\nTo publish (a person runs these; nothing was uploaded):\n")
    for c in commands(out_dir, names, tag):
        print(c + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

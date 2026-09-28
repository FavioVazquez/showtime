"""License policy, sidecars and credits.

Policy (default):
  allowed without credit   CC0, Public Domain (PDM / PD / US-gov NASA media), OFL-1.1,
                           MIT, ISC, Apache-2.0, BSD, Unlicense, Zlib, UFL
  needs --allow-attribution  CC-BY 2.0-4.0  -> a line in CREDITS.txt is required
  needs --allow-share-alike  CC-BY-SA (implies attribution; derivative must be shared alike)
  never                    anything NC (non-commercial) or ND (no derivatives), unknown licenses

Every fetched file gets `<file>.license.json` next to it:
  {source, id, title, author, author_url, license, license_url, landing_url,
   file_url, attribution_required, credit, fetched, sha256}
`write_credits(folder)` compiles every sidecar under a folder into CREDITS.txt.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..common import ShowtimeError, write_json

FREE = "free"            # no attribution needed
ATTRIBUTION = "attribution"
SHARE_ALIKE = "share-alike"
EXCLUDED = "excluded"

_FREE_IDS = {
    "cc0", "cc0-1.0", "pdm", "pd", "public-domain", "publicdomain", "pd-usgov", "pd-nasa",
    "ofl", "ofl-1.1", "mit", "isc", "apache-2.0", "apache", "bsd", "bsd-2-clause", "bsd-3-clause",
    "unlicense", "zlib", "ufl-1.0", "0bsd", "mit-0",
    "generated",         # made on this machine by showtime (a composed bed, a synthesized hit): the user's own work
}


def normalize(lic: Optional[str]) -> str:
    """'CC BY-SA 4.0' -> 'cc-by-sa-4.0', 'Public domain' -> 'public-domain'."""
    s = (lic or "").strip().lower()
    s = s.replace("creative commons", "cc").replace("attribution", "by")
    s = re.sub(r"[\s_/]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if s in ("pdm-1.0", "pdm1.0", "public-domain-mark", "public-domain-mark-1.0"):
        return "pdm"
    if s.startswith("public-domain") or s in ("pd", "no-restrictions", "no-known-copyright-restrictions"):
        return "public-domain"
    if s.startswith("cc-zero") or s.startswith("cc0"):
        return "cc0"
    return s


def classify(lic: Optional[str]) -> str:
    """Return FREE, ATTRIBUTION, SHARE_ALIKE or EXCLUDED for a license string."""
    n = normalize(lic)
    if not n:
        return EXCLUDED
    if n in _FREE_IDS or n.startswith("pd-") or n.startswith("ofl") or n.startswith("apache-2"):
        return FREE
    if n.startswith("cc-by") or n.startswith("by"):
        if "nc" in n.split("-") or "nd" in n.split("-"):
            return EXCLUDED
        if "sa" in n.split("-"):
            return SHARE_ALIKE
        return ATTRIBUTION
    return EXCLUDED


def check(lic: Optional[str], *, allow_attribution: bool = False, allow_share_alike: bool = False,
          what: str = "this asset") -> str:
    """Raise ShowtimeError unless the policy allows `lic`. Returns its class."""
    cls = classify(lic)
    if cls == FREE:
        return cls
    if cls == ATTRIBUTION:
        if allow_attribution:
            return cls
        raise ShowtimeError("%s is licensed %s, which requires a credit line" % (what, lic),
                            hint="re-run with --allow-attribution (a CREDITS.txt line is written for you), "
                                 "or pick a CC0 / public-domain result")
    if cls == SHARE_ALIKE:
        if allow_share_alike:
            return cls
        raise ShowtimeError("%s is licensed %s (share-alike: the video would inherit the license)" % (what, lic),
                            hint="re-run with --allow-share-alike if that is acceptable, or pick another result")
    raise ShowtimeError("%s has license %r, which showtime does not use" % (what, lic or "unknown"),
                        hint="non-commercial, no-derivatives and unknown licenses are excluded; pick another result")


def credit_line(info: Dict[str, Any]) -> str:
    """Human credit: '"Title" by Author (CC BY 4.0) - https://landing'."""
    title = (info.get("title") or "").strip()
    author = (info.get("author") or "").strip()
    lic = (info.get("license_label") or info.get("license") or "").strip()
    parts = []
    if title:
        parts.append('"%s"' % title[:120])
    if author:
        parts.append("by %s" % author[:80])
    if info.get("source_label"):
        parts.append("via %s" % info["source_label"])
    s = " ".join(parts) or (info.get("id") or "asset")
    if lic:
        s += " (%s)" % lic
    link = info.get("landing_url") or info.get("file_url")
    if link:
        s += " - " + link
    return s


def sidecar_path(asset: Path) -> Path:
    asset = Path(asset)
    return asset.with_name(asset.name + ".license.json")


def write_sidecar(asset: Path, info: Dict[str, Any]) -> Path:
    data = dict(info)
    data.setdefault("fetched", time.strftime("%Y-%m-%dT%H:%M:%S"))
    data["license_class"] = classify(data.get("license"))
    data["attribution_required"] = data["license_class"] in (ATTRIBUTION, SHARE_ALIKE)
    data.setdefault("credit", credit_line(data))
    data["file"] = Path(asset).name
    out = write_json(sidecar_path(asset), data)
    try:
        out.chmod(0o644)
    except OSError:
        pass
    return out


def read_sidecar(asset: Path) -> Optional[Dict[str, Any]]:
    p = sidecar_path(asset)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def iter_sidecars(folder: Path) -> Iterable[Path]:
    folder = Path(folder)
    if folder.is_file():
        folder = folder.parent
    for p in sorted(folder.rglob("*.license.json")):
        if "node_modules" in p.parts:
            continue
        yield p


def collect(folder: Path, *, only_required: bool = True) -> List[Dict[str, Any]]:
    out = []
    seen = set()
    for p in iter_sidecars(folder):
        try:
            info = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if only_required and not info.get("attribution_required"):
            continue
        line = info.get("credit") or credit_line(info)
        if line in seen:
            continue
        seen.add(line)
        info["credit"] = line
        info["sidecar"] = str(p)
        out.append(info)
    return out


def write_credits(folder: Path, *, out: Optional[Path] = None, include_free: bool = False) -> Optional[Path]:
    """Write CREDITS.txt for every attribution-required asset under `folder`.

    Returns the path, or None when nothing needs credit (no file is written then).
    """
    folder = Path(folder)
    items = collect(folder, only_required=not include_free)
    if not items:
        return None
    dest = Path(out) if out else (folder if folder.is_dir() else folder.parent) / "CREDITS.txt"
    lines = ["Credits", "", "This video uses the following third-party material:", ""]
    for it in items:
        lines.append("- " + it["credit"])
    lines += ["", "Generated by showtime from the .license.json sidecars next to each file."]
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def append_credit(project: Path, info: Dict[str, Any]) -> Path:
    """Add one credit line to <project>/CREDITS.txt (deduplicated)."""
    project = Path(project)
    project.mkdir(parents=True, exist_ok=True)
    dest = project / "CREDITS.txt"
    line = "- " + (info.get("credit") or credit_line(info))
    existing = dest.read_text(encoding="utf-8").splitlines() if dest.is_file() else [
        "Credits", "", "This video uses the following third-party material:", ""]
    if line not in existing:
        existing.append(line)
    dest.write_text("\n".join(existing) + "\n", encoding="utf-8")
    return dest

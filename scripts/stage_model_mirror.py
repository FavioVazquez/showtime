#!/usr/bin/env python3
"""Stage the model mirror's release assets (stdlib only, any OS, Python 3.8+).

skills/showtime/lib/st/mirror.json lists the model files the default install and first-use features
download, each with its primary URL, its file name on the mirror, size, sha256 and license. This script
downloads every one of them from its primary into a folder under its mirror name, verifies size and
sha256 (the installer's own fetcher: resumable, retried; mirrors are off here), writes LICENSES.txt
(each model's license, source and attribution, then the license texts) and SHA256SUMS, and prints the
`gh release create` / `gh release upload` commands. It uploads nothing: a person runs those commands.

    python scripts/stage_model_mirror.py                          # into ./model-mirror
    python scripts/stage_model_mirror.py --out /tmp/mm --only 'yunet--*'
    python scripts/stage_model_mirror.py --seed ~/.showtime       # reuse verified copies from an install
    python scripts/stage_model_mirror.py --fill                   # write missing size/sha256 into mirror.json

Exit code 0 = every file staged and verified, 1 = a file failed, 2 = bad usage.
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib.util
import json
import os
import ssl
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "showtime"
MIRROR_JSON = SKILL / "lib" / "st" / "mirror.json"
GH_REPO = "FavioVazquez/showtime"
SPDX_TEXT = "https://raw.githubusercontent.com/spdx/license-list-data/main/text/%s.txt"


def _setup_module():
    os.environ["SHOWTIME_MODEL_MIRROR"] = "off"       # stage from the primaries only
    spec = importlib.util.spec_from_file_location("showtime_setup_stage", str(SKILL / "setup" / "setup.py"))
    mod = importlib.util.module_from_spec(spec)      # type: ignore[arg-type]
    spec.loader.exec_module(mod)                     # type: ignore[union-attr]
    return mod


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _spdx_ids(expr: str) -> List[str]:
    return [t for t in expr.replace("(", " ").replace(")", " ").split() if t not in ("AND", "OR", "WITH")]


def _license_text(spdx: str) -> str:
    try:
        ctx = ssl.create_default_context()
        req = urllib.request.Request(SPDX_TEXT % spdx, headers={"User-Agent": "showtime-stage-mirror"})
        with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
            return r.read().decode("utf-8", "replace").strip()
    except Exception as e:  # noqa: BLE001
        return "(text not fetched: %s; see https://spdx.org/licenses/%s.html)" % (e, spdx)


def licenses_txt(files: List[Dict[str, Any]], data: Dict[str, Any]) -> str:
    out = ["showtime model mirror (%s)" % data.get("tag", "models-v1"), "",
           "These files are unmodified copies of third-party model files, mirrored so showtime can install",
           "them where their own hosts are blocked. Each keeps its own license, listed below with its source",
           "and attribution. The full license texts follow; files whose upstream ships its own license",
           "notice also carry it as a separate asset (the *--LICENSE* and *_License.md files).", ""]
    for f in files:
        out += ["%s" % f["file"],
                "  model:       %s" % f["item"],
                "  license:     %s (%s)" % (f["license"], f["license_url"]),
                "  attribution: %s" % f["attribution"],
                "  source:      %s" % f["source"],
                "  original:    %s" % f["url"],
                "  size:        %d bytes" % f["size"],
                "  sha256:      %s" % f["sha256"], ""]
    ids = sorted({i for f in files for i in _spdx_ids(f["license"])})
    for i in ids:
        out += ["=" * 78, i, "=" * 78, ""]
        if i.startswith("LicenseRef-"):
            out += ["Released into the public domain by its author; no license terms apply. See the source",
                    "links above.", ""]
        else:
            out += [_license_text(i), ""]
    return "\n".join(out) + "\n"


def commands(out_dir: Path, names: List[str], tag: str) -> List[str]:
    q = (lambda s: '"%s"' % s) if os.name == "nt" else (lambda s: "'%s'" % s)
    notes = ("Unmodified third-party model files (see LICENSES.txt) that showtime downloads when Hugging Face or "
             "GitHub LFS is blocked. Not a showtime release.")
    create = ("gh release create %s --repo %s --title %s --notes %s --latest=false"
              % (tag, GH_REPO, q("showtime model mirror (%s)" % tag), q(notes)))
    upload = "gh release upload %s --repo %s --clobber %s" % (tag, GH_REPO, " ".join(q(n) for n in names))
    return ["cd %s" % q(str(out_dir)), create, upload]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="model-mirror", help="staging folder (default ./model-mirror)")
    ap.add_argument("--only", action="append", default=[], metavar="GLOB", help="only mirror files matching")
    ap.add_argument("--seed", action="append", default=[], metavar="DIR",
                    help="reuse sha256-verified copies from DIR (e.g. an existing ~/.showtime)")
    ap.add_argument("--fill", action="store_true", help="write missing size/sha256 values into mirror.json")
    a = ap.parse_args(argv)
    data = json.loads(MIRROR_JSON.read_text(encoding="utf-8"))
    files = [f for f in data["files"] if not a.only or any(fnmatch.fnmatch(f["file"], g) for g in a.only)]
    if not files:
        print("no mirror file matches %s" % a.only, file=sys.stderr)
        return 2
    out_dir = Path(a.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    su = _setup_module()
    seeds = su.Seeds([os.path.expanduser(s) for s in a.seed])
    failed, filled = [], False
    for f in files:
        dest = out_dir / f["file"]
        try:
            how = su.fetch(f["url"], dest, f.get("sha256") or None, f.get("size") or None, seeds, f["file"], verify=True)
        except Exception as e:  # noqa: BLE001
            print("FAIL %s: %s" % (f["file"], e), file=sys.stderr)
            failed.append(f["file"])
            continue
        size, sha = dest.stat().st_size, _sha256(dest)
        if f.get("size") and f.get("sha256") and (size, sha) != (f["size"], f["sha256"]):
            print("FAIL %s: staged copy differs from mirror.json" % f["file"], file=sys.stderr)
            failed.append(f["file"])
            continue
        if not f.get("size") or not f.get("sha256"):
            f["size"], f["sha256"], filled = size, sha, True
        print("ok   %-72s %11d  %s" % (f["file"], size, how))
    if filled and a.fill:
        MIRROR_JSON.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("wrote sizes and checksums into %s" % MIRROR_JSON)
    if failed:
        print("\n%d file(s) failed: %s" % (len(failed), ", ".join(failed)), file=sys.stderr)
        return 1
    staged = [f for f in files if (out_dir / f["file"]).is_file()]
    (out_dir / "LICENSES.txt").write_text(licenses_txt(staged, data), encoding="utf-8")
    (out_dir / "SHA256SUMS").write_text("".join("%s  %s\n" % (f["sha256"], f["file"]) for f in staged),
                                        encoding="utf-8")
    total = sum(f["size"] for f in staged)
    big = [f["file"] for f in staged if f["size"] > 1_000_000_000]
    print("\nstaged %d files, %.1f MB, in %s%s" % (len(staged), total / 1e6, out_dir,
                                                   ("; over 1 GB: " + ", ".join(big)) if big else ""))
    if a.only:
        print("(a subset: stage every file before uploading)")
    print("\nTo publish (a person runs these; nothing was uploaded):\n")
    for c in commands(out_dir, [f["file"] for f in staged] + ["LICENSES.txt", "SHA256SUMS"], data.get("tag", "models-v1")):
        print(c + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

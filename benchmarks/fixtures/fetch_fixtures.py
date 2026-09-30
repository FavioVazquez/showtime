#!/usr/bin/env python3
"""Download and prepare the media fixtures that are not stored in git.

    python benchmarks/fixtures/fetch_fixtures.py            # fetch + trim, verify hashes
    python benchmarks/fixtures/fetch_fixtures.py --check    # only report what is present

Each media/<id>.source.json pins a public-domain file by URL and SHA-256 and says how to trim it.
The download is cached in <bench home>/cache/ so re-running is instant.
media/style-reference.mp4 (T10) is not downloaded: make_reference.py draws it with ffmpeg.
"""
import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "harness"))
sys.path.insert(0, str(HERE))
import common  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(spec: dict, cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    dst = cache / (spec["id"] + ".source" + Path(spec["file_url"]).suffix)
    if dst.exists() and sha256(dst) == spec["source_sha256"]:
        return dst
    print("downloading %s (%.1f MB) from %s" % (spec["id"], spec.get("source_bytes", 0) / 1e6, spec["file_url"]))
    tmp = dst.with_suffix(".part")
    with urllib.request.urlopen(spec["file_url"], timeout=120) as r, open(tmp, "wb") as fh:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    got = sha256(tmp)
    if got != spec["source_sha256"]:
        tmp.unlink()
        raise SystemExit("%s: SHA-256 mismatch (got %s). The upstream file changed; re-pin it on purpose." % (spec["id"], got))
    tmp.replace(dst)
    return dst


def prepare(spec: dict, src: Path, out: Path) -> None:
    ff = common.ffmpeg()
    t = spec["trim"]
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(t["start"]), "-i", str(src),
           "-t", str(t["duration"])] + spec["encode"] + [str(out)]
    subprocess.run(cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report only")
    a = ap.parse_args()
    cache = common.bench_home() / "cache"
    ok = True
    for sj in sorted((HERE / "media").glob("*.source.json")):
        spec = json.loads(sj.read_text(encoding="utf-8"))
        out = HERE / "media" / (spec["id"] + ".mp4")
        if a.check:
            print("%-10s %s" % (spec["id"], "present" if out.exists() else "MISSING (run fetch_fixtures.py)"))
            ok = ok and out.exists()
            continue
        if out.exists():
            print("%-10s present: %s" % (spec["id"], out.name))
            continue
        prepare(spec, fetch(spec, cache), out)
        print("%-10s ready: %s (%.1f MB)" % (spec["id"], out.name, out.stat().st_size / 1e6))
    import make_reference
    ref = make_reference.OUT
    if a.check:
        print("%-10s %s" % ("style-reference", "present" if ref.exists() else "MISSING (run fetch_fixtures.py)"))
        ok = ok and ref.exists()
    elif ref.exists():
        print("%-10s present: %s" % ("style-reference", ref.name))
    else:
        make_reference.build(ref)
        print("%-10s ready: %s (%.1f MB, drawn by make_reference.py)" % ("style-reference", ref.name, ref.stat().st_size / 1e6))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

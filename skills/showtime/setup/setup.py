#!/usr/bin/env python3
"""showtime installer: idempotent, resumable, cross-platform, stdlib only.

Installs everything into ~/.showtime (or $SHOWTIME_HOME):

  bin/        static ffmpeg + ffprobe (or reuses a capable system ffmpeg)
  venv/       Python 3.12 virtualenv created with uv, pinned deps (requirements.txt)
  node/       pinned Node packages (package.json / package-lock.json), incl. Playwright
  browsers/   Playwright Chromium, only when no Chrome/Edge/Chromium is installed
  models/     Kokoro, Whisper, sherpa-onnx models, YuNet, arnndn (sha256-verified)
  soundfonts/ General MIDI banks + their licenses

Tiers:   minimal (CI) < core (default) < full.   Extras: --with a,b (see --list).

Examples:
  python setup.py                      # core tier
  python setup.py --tier minimal       # smallest working install
  python setup.py --with asr-turbo,diarize
  python setup.py --list               # tiers, extras and download sizes
  python setup.py --verify             # re-hash every installed file
  python setup.py --link               # dev only: link ~/.claude/skills/showtime to this checkout

Runs with any Python 3.8+. Needs `uv` (Python deps) and Node.js 20+ (render).
"""
from __future__ import annotations

import argparse
import errno
import fnmatch
import hashlib
import json
import os
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

SETUP_DIR = Path(__file__).resolve().parent
SKILL_DIR = SETUP_DIR.parent
LIB_DIR = SKILL_DIR / "lib"
sys.path.insert(0, str(LIB_DIR))
from st import __version__  # noqa: E402
from st import platform as plat  # noqa: E402

UA = "showtime-setup/%s (+python urllib)" % __version__
MANIFEST_PATH = SETUP_DIR / "manifest.json"
TIER_ORDER = ["minimal", "core", "full"]
PY_VERSION = "3.12"
MIN_NODE = 20
KEY_PACKAGES = ["numpy", "scipy", "onnxruntime", "ctranslate2", "faster-whisper", "kokoro-onnx",
                "sherpa-onnx", "opencv-python", "av", "librosa", "numba", "llvmlite", "scenedetect",
                "soundfile", "pillow", "tinysoundfont", "supertonic", "imageio-ffmpeg", "pypdfium2"]
IMPORT_CHECK = ["numpy", "scipy", "soundfile", "PIL", "cv2", "av", "scenedetect", "faster_whisper",
                "ctranslate2", "onnxruntime", "kokoro_onnx", "sherpa_onnx", "librosa", "mido",
                "pretty_midi", "pyloudnorm", "requests", "pypdfium2"]


# ==========================================================================
# Output helpers
# ==========================================================================

class Report:
    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    def add(self, component: str, status: str, detail: str = "", seconds: float = 0.0, **extra: Any) -> None:
        row = {"component": component, "status": status, "detail": detail, "seconds": round(seconds, 1)}
        row.update(extra)
        self.rows.append(row)
        say("%-5s %s%s" % (status.upper(), component, (": " + detail) if detail else ""))

    @property
    def failed(self) -> bool:
        return any(r["status"] == "fail" for r in self.rows)


def _tty() -> bool:
    return hasattr(sys.stderr, "isatty") and sys.stderr.isatty() and not os.environ.get("NO_COLOR")


def say(msg: str) -> None:
    try:
        print(msg, file=sys.stderr, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode(), file=sys.stderr, flush=True)


def human(n: Optional[float]) -> str:
    if n is None:
        return "?"
    for u in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or u == "GB":
            return ("%d %s" % (n, u)) if u == "B" else ("%.1f %s" % (n, u))
        n /= 1024.0
    return "%.1f GB" % n


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: Sequence[str], env: Optional[Dict[str, str]] = None, cwd: Optional[Path] = None,
        capture: bool = True, timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run([str(c) for c in cmd], env=full_env, cwd=str(cwd) if cwd else None,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.STDOUT if capture else None,
                          encoding="utf-8", errors="replace", timeout=timeout)


def tail(text: Optional[str], n: int = 12) -> str:
    # drop Python's caret-only traceback markers ("   ^^^^^"): they carry no information in a summary
    lines = [x for x in (text or "").strip().splitlines() if x.strip(" ^~")]
    return "\n".join("      " + x for x in lines[-n:])


def replace_file(src: Path, dst: Path) -> None:
    """os.replace with retries: on Windows, antivirus scanners briefly lock new files."""
    for i in range(10):
        try:
            os.replace(str(src), str(dst))
            return
        except PermissionError:
            if os.name != "nt" or i == 9:
                raise
            time.sleep(0.5)


def rmtree(path: Path) -> None:
    """shutil.rmtree that also removes read-only files (Windows)."""
    def onerror(func, p, exc_info):  # noqa: ANN001
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            raise exc_info[1]
    shutil.rmtree(str(path), onerror=onerror)


# ==========================================================================
# Manifest / selection
# ==========================================================================

def load_manifest() -> Dict[str, Any]:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def item_files(item: Dict[str, Any], key: str) -> Optional[List[Dict[str, Any]]]:
    """Files for this platform, or None if the item does not support it."""
    if "platform_files" in item:
        return item["platform_files"].get(key)
    return item.get("files", [])


def select_items(man: Dict[str, Any], tier: str, extras: Iterable[str]) -> List[Dict[str, Any]]:
    tiers = TIER_ORDER[:TIER_ORDER.index(tier) + 1]
    ex = set(extras)
    return [it for it in man["items"]
            if (it.get("tier") in tiers) or (it.get("extra") and it["extra"] in ex)]


def resolve_extras(man: Dict[str, Any], tier: str, with_: Sequence[str]) -> List[str]:
    extras = [e for e in with_ if e]
    if tier == "full":
        extras = list(man.get("full_extras", [])) + extras
    unknown = [e for e in extras if e not in man["extras"]]
    if unknown:
        raise SystemExit("setup: unknown extra(s): %s\n  available: %s" % (
            ", ".join(unknown), ", ".join(sorted(man["extras"]))))
    seen: List[str] = []
    for e in extras:
        if e not in seen:
            seen.append(e)
    return seen


# ==========================================================================
# Downloads (resumable, sha256-verified, seedable)
# ==========================================================================

class Seeds:
    """Index of local files that may already hold a download (matched by size, then sha256)."""

    SKIP = {".venv", "venv", "node_modules", "__pycache__", "site-packages", ".git", "lib", "include"}

    def __init__(self, dirs: Sequence[str]) -> None:
        self.dirs = [Path(os.path.expanduser(d)) for d in dirs if d]
        self._index: Optional[Dict[int, List[Path]]] = None

    def _build(self) -> Dict[int, List[Path]]:
        idx: Dict[int, List[Path]] = {}
        for root in self.dirs:
            if not root.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(str(root), followlinks=True):
                dirnames[:] = [d for d in dirnames if d not in self.SKIP]
                for fn in filenames:
                    p = Path(dirpath) / fn
                    try:
                        n = p.stat().st_size
                    except OSError:
                        continue
                    if n >= 1024:
                        idx.setdefault(n, []).append(p)
        return idx

    def find(self, size: Optional[int], sha: Optional[str]) -> Optional[Path]:
        if not self.dirs or not size or not sha:
            return None
        if self._index is None:
            self._index = self._build()
        for cand in self._index.get(size, []):
            try:
                if sha256_file(cand) == sha:
                    return cand
            except OSError:
                continue
        return None


def _ssl_context() -> Optional[ssl.SSLContext]:
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return None


class Progress:
    def __init__(self, label: str, total: Optional[int]) -> None:
        self.label, self.total = label, total
        self.last = 0.0
        self.start = time.time()

    def update(self, done: int, final: bool = False) -> None:
        now = time.time()
        if not final and now - self.last < (0.5 if _tty() else 15):
            return
        self.last = now
        rate = done / max(now - self.start, 1e-3)
        pct = (" %5.1f%%" % (100.0 * done / self.total)) if self.total else ""
        msg = "  %s%s  %s / %s  %s/s" % (self.label, pct, human(done), human(self.total), human(rate))
        if _tty():
            sys.stderr.write("\r" + msg.ljust(78)[:118] + ("\n" if final else ""))
            sys.stderr.flush()
        else:
            say(msg)


def _download_urllib(url: str, part: Path, total: Optional[int], label: str) -> None:
    ctx = _ssl_context()
    have = part.stat().st_size if part.exists() else 0
    if total and have > total:
        part.unlink()
        have = 0
    headers = {"User-Agent": UA}
    if have:
        headers["Range"] = "bytes=%d-" % have
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
        code = getattr(resp, "status", 200)
        mode = "ab"
        if have and code != 206:
            mode, have = "wb", 0  # server ignored the range: restart
        prog = Progress(label, total)
        done = have
        with open(part, mode) as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                prog.update(done)
        prog.update(done, final=True)


def _download_curl(url: str, part: Path) -> None:
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("curl not available")
    cp = subprocess.run([curl, "-fL", "--retry", "3", "--connect-timeout", "30", "-A", UA,
                         "-C", "-", "-o", str(part), url])
    if cp.returncode not in (0, 33):  # 33: range not satisfiable (already complete)
        raise RuntimeError("curl exited with %d" % cp.returncode)


def fetch(url: str, dest: Path, sha: Optional[str], size: Optional[int], seeds: Seeds,
          label: str, verify: bool = False) -> str:
    """Ensure `dest` holds the file. Returns 'present' | 'seeded' | 'downloaded'."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and (size is None or dest.stat().st_size == size):
        if not verify or not sha or sha256_file(dest) == sha:
            return "present"
        say("  %s: checksum mismatch, re-downloading" % dest.name)
        dest.unlink()
    seeded = seeds.find(size, sha)
    if seeded is not None:
        tmp = dest.with_name(dest.name + ".part")
        shutil.copyfile(str(seeded), str(tmp))
        replace_file(tmp, dest)
        return "seeded"
    part = dest.with_name(dest.name + ".part")
    last_err: Optional[BaseException] = None
    for attempt in range(1, 5):
        try:
            try:
                _download_urllib(url, part, size, label)
            except (ssl.SSLError, urllib.error.URLError) as e:
                if isinstance(e, urllib.error.HTTPError) and e.code in (403, 404, 410):
                    raise
                if "CERTIFICATE" in str(e).upper() or isinstance(e, ssl.SSLError):
                    say("  TLS verification failed in Python (%s); retrying with curl" % e)
                    _download_curl(url, part)
                else:
                    raise
            got = part.stat().st_size
            if size is not None and got != size:
                if got > size:
                    part.unlink()
                raise IOError("size mismatch for %s: got %d, expected %d" % (label, got, size))
            if sha:
                actual = sha256_file(part)
                if actual != sha:
                    part.unlink()
                    raise IOError("sha256 mismatch for %s: got %s, expected %s" % (label, actual, sha))
            replace_file(part, dest)
            return "downloaded"
        except urllib.error.HTTPError as e:
            if e.code in (403, 404, 410):
                raise IOError("%s: HTTP %d for %s" % (label, e.code, url))
            last_err = e
        except (IOError, OSError, RuntimeError, urllib.error.URLError, ssl.SSLError) as e:
            last_err = e
        if attempt < 4:
            wait = 3 * attempt
            say("  %s: attempt %d failed (%s); retrying in %ds" % (label, attempt, last_err, wait))
            time.sleep(wait)
    raise IOError("could not download %s: %s" % (label, last_err))


# ==========================================================================
# Archive extraction
# ==========================================================================

def _safe_rel(name: str, strip: int) -> Optional[str]:
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts) or name.startswith("/"):
        return None
    parts = parts[strip:]
    return "/".join(parts) if parts else None


def extract(archive: Path, kind: str, dest: Path, strip: int = 0,
            include: Optional[List[str]] = None, pick: Optional[List[str]] = None,
            executables: Optional[List[str]] = None) -> List[Path]:
    """Extract (a subset of) an archive. `pick` extracts only files whose basename
    matches (flattened into dest). Returns the written file paths."""
    dest.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    picks = {plat.exe(p) for p in (pick or [])} | set(pick or [])
    exe_names = set(executables or [])

    def wanted(rel: str) -> bool:
        if pick is not None:
            return rel.rsplit("/", 1)[-1] in picks
        if not include:
            return True
        return any(fnmatch.fnmatch(rel, pat) for pat in include)

    def target_for(rel: str) -> Path:
        return dest / (rel.rsplit("/", 1)[-1] if pick is not None else rel)

    def finish(t: Path, mode_bits: int) -> None:
        if os.name != "nt" and (mode_bits & 0o111 or t.name in exe_names or t.name in picks):
            t.chmod(t.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        written.append(t)

    if kind == "zip":
        with zipfile.ZipFile(str(archive)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                rel = _safe_rel(info.filename, strip)
                if not rel or not wanted(rel):
                    continue
                t = target_for(rel)
                t.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(t, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                finish(t, (info.external_attr >> 16) & 0o777)
    elif kind.startswith("tar"):
        mode = {"tar": "r:", "tar.gz": "r:gz", "tgz": "r:gz", "tar.bz2": "r:bz2", "tar.xz": "r:xz"}[kind]
        with tarfile.open(str(archive), mode) as tf:
            for m in tf:
                if not m.isfile():
                    continue
                rel = _safe_rel(m.name, strip)
                if not rel or not wanted(rel):
                    continue
                t = target_for(rel)
                t.parent.mkdir(parents=True, exist_ok=True)
                src = tf.extractfile(m)
                if src is None:
                    continue
                with src, open(t, "wb") as out:
                    shutil.copyfileobj(src, out, 1 << 20)
                finish(t, m.mode)
    else:
        raise ValueError("unsupported archive type: %s" % kind)
    return written


def unquarantine(paths: Iterable[Path]) -> None:
    """macOS: drop the quarantine flag so Gatekeeper does not block CLI tools."""
    if not plat.IS_MAC or not shutil.which("xattr"):
        return
    for p in paths:
        subprocess.run(["xattr", "-d", "com.apple.quarantine", str(p)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ==========================================================================
# State
# ==========================================================================

class State:
    def __init__(self, home: Path) -> None:
        self.path = home / "state.json"
        try:
            self.data: Dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.data.setdefault("items", {})

    def save(self) -> None:
        self.data["showtime_version"] = __version__
        self.data["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(self.path))


def item_status(item: Dict[str, Any], home: Path, key: str, state: Optional[Dict[str, Any]] = None,
                verify: bool = False) -> Tuple[str, str]:
    """('ok'|'missing'|'unsupported'|'corrupt', detail) for an installed item.

    Shared with `showtime doctor` (imported from this file)."""
    files = item_files(item, key)
    if files is None:
        return "unsupported", "not available for %s" % key
    missing = []
    for f in files:
        if f.get("archive"):
            creates = home / f.get("creates", f["dest"])
            rec = (state or {}).get("items", {}).get(item["id"], {})
            if not creates.exists():
                missing.append(f.get("creates", f["dest"]))
            elif state is not None and rec.get("archive_sha256") not in (None, f.get("sha256")):
                return "corrupt", "installed from a different archive; re-run setup"
            continue
        p = home / f["dest"]
        if not p.is_file():
            missing.append(f["dest"])
        elif f.get("size") and p.stat().st_size != f["size"]:
            return "corrupt", "%s has the wrong size" % f["dest"]
        elif verify and f.get("sha256") and sha256_file(p) != f["sha256"]:
            return "corrupt", "%s fails its sha256 check" % f["dest"]
    if missing:
        return "missing", ", ".join(missing[:3]) + (" ..." if len(missing) > 3 else "")
    return "ok", ""


def item_size(item: Dict[str, Any], key: str) -> int:
    return sum(int(f.get("size") or 0) for f in (item_files(item, key) or []))


# Rough sizes of what uv/npm install (not in the manifest): measured on macOS/Linux.
PACKAGES_BYTES = {"python": int(1.5 * 1024 ** 3), "node": 250 * 1024 ** 2}


def install_estimate(tier: str = "core", extras: Sequence[str] = (), home: Optional[Path] = None,
                     man: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What a setup run will download and roughly how long it takes.

    Returns download_bytes (models, binaries), packages_bytes (Python + Node
    packages, when not installed yet), total_bytes and minutes_low/high
    (50 MB/s .. 8 MB/s plus a fixed install overhead). Used by the launcher's
    first-run message and setup's own preflight line.
    """
    man = man or load_manifest()
    key = plat.platform_key()
    home = home or Path(os.path.expanduser(os.environ.get("SHOWTIME_HOME") or "~/.showtime"))
    items = select_items(man, tier, list(extras))
    todo = [it for it in items if item_status(it, home, key)[0] != "ok"]
    dl = sum(item_size(it, key) for it in todo)
    ff_have = (home / "bin" / plat.exe("ffmpeg")).is_file()
    if not ff_have:
        cands = man.get("ffmpeg", {}).get(key) or []
        if cands:
            dl += sum(int(f.get("size") or 0) for f in cands[0].get("files", []))
    pk = 0
    if not plat.venv_python(home / "venv").exists():
        pk += PACKAGES_BYTES["python"]
    if not (home / "node" / "node_modules" / "playwright").is_dir():
        pk += PACKAGES_BYTES["node"]
    total = dl + pk
    mb = total / 1024.0 ** 2
    low = mb / 50.0 / 60.0 + (2 if pk else 0.2)
    high = mb / 8.0 / 60.0 + (5 if pk else 0.5)
    return {"tier": tier, "extras": list(extras), "download_bytes": dl, "packages_bytes": pk, "total_bytes": total,
            "items": [it["id"] for it in todo], "minutes_low": max(1, int(round(low))),
            "minutes_high": max(2, int(round(high)))}


def describe_estimate(est: Dict[str, Any]) -> str:
    """'about 2.3 GB (1.1 GB downloads + 1.2 GB packages), usually 4-12 min'."""
    if est["total_bytes"] <= 0:
        return "nothing to download (already installed)"
    parts = []
    if est["download_bytes"]:
        parts.append("%s downloads" % human(est["download_bytes"]))
    if est["packages_bytes"]:
        parts.append("%s Python/Node packages" % human(est["packages_bytes"]))
    return "about %s (%s), usually %d-%d min" % (human(est["total_bytes"]), " + ".join(parts),
                                                est["minutes_low"], est["minutes_high"])


# ==========================================================================
# Installer
# ==========================================================================

class Installer:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.home = Path(os.path.expanduser(args.home or os.environ.get("SHOWTIME_HOME") or "~/.showtime"))
        self.key = plat.platform_key()
        self.man = load_manifest()
        self.state = State(self.home)
        prev = self.state.data.get("installed") or {}
        # Re-running setup (e.g. `--with X` later) keeps what is already installed:
        # the previous tier is the default and previous extras stay in the plan.
        self.tier = args.tier or (prev.get("tier") if prev.get("tier") in TIER_ORDER else "core")
        keep = [e for e in prev.get("extras", []) if e in self.man["extras"]]
        self.extras = resolve_extras(self.man, self.tier, keep + list(args.with_))
        self.carried = set(keep) - set(args.with_)
        self.report = Report()
        seed_dirs = list(args.seed or []) + [d for d in os.environ.get("SHOWTIME_SEED_DIRS", "").split(os.pathsep) if d]
        self.seeds = Seeds(seed_dirs)
        self.skip = set(args.skip or [])
        self.vpy = plat.venv_python(self.home / "venv")
        self.env_common = {
            "SHOWTIME_HOME": str(self.home),
            "HF_HOME": str(self.home / "models" / "hf"),
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "PLAYWRIGHT_BROWSERS_PATH": str(self.home / "browsers"),
            "SUPERTONIC_CACHE_DIR": str(self.home / "models" / "supertonic3"),
        }

    # ---------------------------------------------------------------- utils
    def timed(self, component: str, fn: Callable[[], Tuple[str, str]], **extra: Any) -> None:
        t0 = time.time()
        try:
            status, detail = fn()
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001
            status, detail = "fail", "%s: %s" % (type(e).__name__, e)
        self.report.add(component, status, detail, time.time() - t0, **extra)

    def find_uv(self) -> Optional[str]:
        env = os.environ.get("SHOWTIME_UV")
        if env and Path(env).is_file():
            return env
        return plat.find_tool("uv")

    def find_node(self) -> Tuple[Optional[str], Optional[Tuple[int, ...]]]:
        node = os.environ.get("SHOWTIME_NODE") or plat.find_tool("node")
        if not node:
            return None, None
        try:
            out = subprocess.run([node, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 encoding="utf-8", timeout=30).stdout.strip()
            ver = tuple(int(x) for x in re.findall(r"\d+", out)[:3])
            return node, ver
        except (OSError, ValueError, subprocess.SubprocessError):
            return node, None

    def npm_cmd(self, node: str) -> List[str]:
        nd = Path(node).resolve().parent
        for cli in (nd / "node_modules" / "npm" / "bin" / "npm-cli.js",
                    nd.parent / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"):
            if cli.is_file():
                return [node, str(cli)]
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("npm not found next to node (%s)" % node)
        return [npm]

    # ------------------------------------------------------------ preflight
    def preflight(self) -> None:
        o = plat.os_name()
        head = None
        try:
            from st.delight import header
            head = header("showtime setup %s" % __version__, "  \u00b7  ".join(
                [self.key, "home %s" % self.home, "tier %s" % self.tier]
                + (["extras " + ",".join(self.extras)] if self.extras else [])), sys.stderr)
        except Exception:  # noqa: BLE001 - decoration never breaks setup
            head = None
        say(head or "showtime setup %s  |  %s  |  home %s  |  tier %s%s" % (
            __version__, self.key, self.home, self.tier,
            ("  |  extras " + ",".join(self.extras)) if self.extras else ""))
        if sys.version_info < (3, 8):
            raise SystemExit("setup: Python 3.8+ is required to run the installer")
        if o == "mac":
            try:
                ver = subprocess.run(["sw_vers", "-productVersion"], stdout=subprocess.PIPE,
                                     encoding="utf-8").stdout.strip()
                major = int(ver.split(".")[0])
                if major < 14:
                    self.report.add("os", "warn", "macOS %s: macOS 14 (Sonoma) or newer is needed for the "
                                                  "pinned wheels (opencv, av)" % ver)
            except (OSError, ValueError):
                pass
        elif o == "linux":
            try:
                libc = os.confstr("CS_GNU_LIBC_VERSION") or ""
                m = re.search(r"(\d+)\.(\d+)", libc)
                if m and (int(m.group(1)), int(m.group(2))) < (2, 28):
                    self.report.add("os", "warn", "%s: glibc 2.28+ is needed (Ubuntu 20.04+ / Debian 10+)" % libc)
            except (ValueError, OSError, AttributeError):
                pass
        if self.key not in self.man["ffmpeg"]:
            self.report.add("os", "warn", "platform %s has no prebuilt downloads; using system tools" % self.key)
        self.home.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(str(self.home)).free
        need = sum(item_size(it, self.key) for it in select_items(self.man, self.tier, self.extras)
                   if item_status(it, self.home, self.key)[0] != "ok") + 2 * 1024 ** 3
        if free < need:
            self.report.add("disk", "warn", "%s free at %s; about %s needed" % (human(free), self.home, human(need)))
        try:
            est = install_estimate(self.tier, self.extras, self.home, self.man)
            if est["total_bytes"] > 0:
                say("  plan: %s" % describe_estimate(est))
        except Exception:  # noqa: BLE001 - an estimate must never block setup
            pass

    # --------------------------------------------------------------- ffmpeg
    def _ff_check(self, ffmpeg: str) -> Tuple[bool, List[str], List[str], str]:
        from st.ff import (REQUIRED_ENCODERS, REQUIRED_FILTERS, RECOMMENDED_FILTERS,
                           RECOMMENDED_ENCODERS, _list_names, _version_of)
        v = _version_of(ffmpeg)
        if not v:
            return False, ["(does not run)"], [], ""
        filters, encoders = set(_list_names(ffmpeg, "filters")), set(_list_names(ffmpeg, "encoders"))
        miss_req = [f for f in REQUIRED_FILTERS if f not in filters] + [e for e in REQUIRED_ENCODERS if e not in encoders]
        miss_rec = [f for f in RECOMMENDED_FILTERS if f not in filters] + [e for e in RECOMMENDED_ENCODERS if e not in encoders]
        return not miss_req, miss_req, miss_rec, v

    def step_ffmpeg(self) -> Tuple[str, str]:
        mode = self.args.ffmpeg
        bindir = self.home / "bin"
        ours = bindir / plat.exe("ffmpeg")
        if mode != "system" and ours.is_file() and not self.args.force:
            ok, req, rec, v = self._ff_check(str(ours))
            if ok and (bindir / plat.exe("ffprobe")).is_file():
                self.state.data.setdefault("ffmpeg", {}).update({"path": str(ours), "version": v})
                return ("ok" if not rec else "warn"), "ffmpeg %s in %s%s" % (
                    v, bindir, ("; missing optional: " + ", ".join(rec)) if rec else "")
        if mode in ("auto", "system"):
            from st.ff import _system_candidates
            for cand in _system_candidates("ffmpeg"):
                ok, req, rec, v = self._ff_check(cand)
                probe = Path(cand).with_name(plat.exe("ffprobe"))
                good_enough = ok and not [r for r in rec if r in ("zscale", "arnndn")] and probe.is_file()
                if good_enough:
                    if mode == "system":
                        # The resolver prefers ~/.showtime/bin; remove ours so the system build is used.
                        for n in ("ffmpeg", "ffprobe"):
                            p = bindir / plat.exe(n)
                            if p.is_file():
                                p.unlink()
                    self.state.data["ffmpeg"] = {"source": "system", "path": cand, "version": v, "missing_optional": rec}
                    return ("ok" if not rec else "warn"), "using system ffmpeg %s at %s%s" % (
                        v, cand, ("; missing optional: " + ", ".join(rec)) if rec else "")
                say("  system ffmpeg %s not used (%s)" % (cand, "does not run" if not v else
                    "missing: " + ", ".join((req + rec)[:6])))
            if mode == "system":
                return "fail", "no capable system ffmpeg found (use --ffmpeg static)"
        cands = self.man["ffmpeg"].get(self.key, [])
        if not cands:
            return "warn", "no static ffmpeg for %s; install ffmpeg with libass/libx264 yourself" % self.key
        errors = []
        for cand in cands:
            try:
                bindir.mkdir(parents=True, exist_ok=True)
                dl = self.home / "cache" / "downloads"
                written: List[Path] = []
                for f in cand["files"]:
                    name = f["url"].rsplit("/", 1)[-1]
                    arc = dl / ("%s-%s" % (cand["id"], name))
                    how = fetch(f["url"], arc, f.get("sha256"), f.get("size"), self.seeds,
                                "%s %s" % (cand["id"], name), verify=True)
                    say("  %s: %s" % (name, how))
                    staged = self.home / "cache" / ("ffstage-" + cand["id"])
                    written += extract(arc, f["archive"], staged, pick=f["pick"])
                for w in written:
                    target = bindir / w.name
                    if target.exists():
                        target.unlink()
                    shutil.move(str(w), str(target))
                    if os.name != "nt":
                        target.chmod(0o755)
                shutil.rmtree(str(self.home / "cache" / ("ffstage-" + cand["id"])), ignore_errors=True)
                unquarantine([bindir / plat.exe("ffmpeg"), bindir / plat.exe("ffprobe")])
                ok, req, rec, v = self._ff_check(str(ours))
                if not ok:
                    errors.append("%s: missing %s" % (cand["id"], ", ".join(req)))
                    continue
                for f in cand["files"]:
                    (dl / ("%s-%s" % (cand["id"], f["url"].rsplit("/", 1)[-1]))).unlink()
                self.state.data["ffmpeg"] = {"source": cand["id"], "path": str(ours), "version": v,
                                             "license": cand.get("license"), "missing_optional": rec}
                try:
                    from st import ff as _ff
                    _ff._cached = None
                except Exception:  # noqa: BLE001
                    pass
                return ("ok" if not rec else "warn"), "%s -> %s%s" % (
                    cand["id"], bindir, ("; missing optional: " + ", ".join(rec)) if rec else "")
            except Exception as e:  # noqa: BLE001
                errors.append("%s: %s" % (cand["id"], e))
                say("  ffmpeg candidate %s failed: %s" % (cand["id"], e))
        return "fail", "; ".join(errors) + " (imageio-ffmpeg from the venv will be used as a last resort)"

    # --------------------------------------------------------------- python
    def _req_hash(self, extra: Sequence[str]) -> str:
        h = hashlib.sha256((SETUP_DIR / "requirements.txt").read_bytes())
        h.update(("|".join(sorted(extra)) + "|" + PY_VERSION).encode())
        return h.hexdigest()[:16]

    def step_python(self) -> Tuple[str, str]:
        uv = self.find_uv()
        if not uv:
            return "fail", "uv not found. Install it, then re-run setup:\n" + uv_hint()
        venv = self.home / "venv"
        env = dict(self.env_common)
        env.setdefault("UV_PYTHON_DOWNLOADS", "automatic")
        pyv = None
        if self.vpy.exists():
            cp = run([str(self.vpy), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"])
            pyv = cp.stdout.strip() if cp.returncode == 0 else None
        if self.args.force or pyv != PY_VERSION:
            if venv.exists():
                say("  recreating venv (%s)" % ("--force" if self.args.force else "python %s" % pyv))
                rmtree(venv)
            cp = run([uv, "venv", "--python", PY_VERSION, str(venv)], env=env, timeout=1800)
            if cp.returncode != 0:
                return "fail", "uv venv failed:\n" + tail(cp.stdout)
        pip_extras = []
        for e in self.extras:
            pip_extras += self.man["extras"][e].get("pip", [])
        stamp = venv / ".showtime-reqs"
        want = self._req_hash(pip_extras)
        if not self.args.force and stamp.is_file() and stamp.read_text().strip() == want:
            detail = "venv up to date (%s)" % venv
        else:
            say("  installing Python packages (uv pip, wheels only)...")
            cp = run([uv, "pip", "install", "--python", str(self.vpy), "--only-binary", ":all:",
                      "-r", str(SETUP_DIR / "requirements.txt")], env=env, timeout=3600)
            if cp.returncode != 0:
                return "fail", "uv pip install failed:\n" + tail(cp.stdout, 20)
            if pip_extras:
                cp = run([uv, "pip", "install", "--python", str(self.vpy), "--only-binary", ":all:"] + pip_extras,
                         env=env, timeout=1800)
                if cp.returncode != 0:
                    return "fail", "extra packages failed (%s):\n%s" % (" ".join(pip_extras), tail(cp.stdout))
            # tinysoundfont declares pyaudio (live playback only): install without deps.
            cp = run([uv, "pip", "install", "--python", str(self.vpy), "--no-deps", "tinysoundfont==0.3.7"],
                     env=env, timeout=900)
            if cp.returncode != 0:
                self.report.add("tinysoundfont", "warn",
                                "not installed (no wheel for %s and the source build failed; needs a C "
                                "compiler). SoundFont music falls back to other renderers." % self.key)
            stamp.write_text(want)
            detail = "installed into %s" % venv
        check = run([str(self.vpy), "-c",
                     "import importlib,json,sys\nbad={}\nfor m in %r:\n  try: importlib.import_module(m)\n"
                     "  except Exception as e: bad[m]=str(e)[:200]\nprint(json.dumps(bad))" % IMPORT_CHECK],
                    env=env, timeout=600)
        try:
            bad = json.loads(check.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            bad = {"(import check)": tail(check.stdout)}
        versions = self.pkg_versions(uv)
        self.state.data["python"] = {"venv": str(venv), "python": self.venv_version(), "packages": versions}
        if bad:
            return "fail", "imports failing: " + "; ".join("%s (%s)" % kv for kv in bad.items())
        return "ok", detail + "; python %s" % self.venv_version()

    def venv_version(self) -> str:
        cp = run([str(self.vpy), "-c", "import platform; print(platform.python_version())"])
        return cp.stdout.strip()

    def pkg_versions(self, uv: str) -> Dict[str, str]:
        cp = subprocess.run([uv, "pip", "list", "--python", str(self.vpy), "--format", "json"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace")
        text = cp.stdout or ""
        try:
            data = json.loads(text[text.find("["):]) if "[" in text else []
        except ValueError:
            return {}
        allv = {d["name"].lower(): d["version"] for d in data}
        return {k: allv[k] for k in KEY_PACKAGES if k in allv}

    # ----------------------------------------------------------------- node
    def step_node(self) -> Tuple[str, str]:
        node, ver = self.find_node()
        if not node:
            return "fail", "Node.js not found. " + node_hint()
        if not ver or ver[0] < MIN_NODE:
            return "fail", "Node.js %s is too old (need %d+). %s" % (".".join(map(str, ver or ())), MIN_NODE, node_hint())
        nd = self.home / "node"
        nd.mkdir(parents=True, exist_ok=True)
        pkg, lock = SETUP_DIR / "package.json", SETUP_DIR / "package-lock.json"
        h = hashlib.sha256(pkg.read_bytes() + (lock.read_bytes() if lock.is_file() else b"")).hexdigest()[:16]
        stamp = nd / ".showtime-stamp"
        if (not self.args.force and stamp.is_file() and stamp.read_text().strip() == h
                and (nd / "node_modules" / "playwright" / "package.json").is_file()):
            return "ok", "node %s; packages up to date (%s)" % (".".join(map(str, ver)), nd)
        shutil.copyfile(str(pkg), str(nd / "package.json"))
        if lock.is_file():
            shutil.copyfile(str(lock), str(nd / "package-lock.json"))
            sub = ["ci"]
        else:
            sub = ["install"]
        say("  installing Node packages (npm %s)..." % sub[0])
        cmd = self.npm_cmd(node) + sub + ["--no-audit", "--no-fund", "--loglevel=error"]
        cp = run(cmd, cwd=nd, env={"PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1"}, timeout=3600)
        if cp.returncode != 0:
            return "fail", "npm %s failed:\n%s" % (sub[0], tail(cp.stdout, 20))
        stamp.write_text(h)
        pw = json.loads((nd / "node_modules" / "playwright" / "package.json").read_text(encoding="utf-8"))["version"]
        self.state.data["node"] = {"node": ".".join(map(str, ver)), "dir": str(nd), "playwright": pw}
        return "ok", "node %s; playwright %s + %d packages in %s" % (
            ".".join(map(str, ver)), pw, len(json.loads(pkg.read_text(encoding="utf-8"))["dependencies"]), nd)

    # -------------------------------------------------------------- browser
    def step_browser(self) -> Tuple[str, str]:
        browsers = plat.find_browsers(self.home / "browsers")
        system = [b for b in browsers if b["source"] in ("system", "env")]
        want_pw = "chromium" in self.extras or not system
        if not want_pw:
            self.state.data["browser"] = system[0]
            return "ok", "%s: %s" % (system[0]["kind"], system[0]["path"])
        node, _ = self.find_node()
        cli = self.home / "node" / "node_modules" / "playwright" / "cli.js"
        if not node or not cli.is_file():
            return "fail", "Playwright is not installed (Node step failed), and no Chrome/Edge was found"
        say("  installing Playwright Chromium into %s ..." % (self.home / "browsers"))
        # --no-shell: showtime always drives the full browser in new-headless mode
        # (channel "chromium"), the same headless path system Chrome uses.
        cp = run([node, str(cli), "install", "--no-shell", "chromium"], env=self.env_common, timeout=3600)
        if cp.returncode != 0:
            return "fail", "playwright install chromium failed:\n" + tail(cp.stdout)
        pw = plat.playwright_chromium(self.home / "browsers")
        self.state.data["browser"] = {"kind": "playwright", "path": str(pw) if pw else None}
        detail = "Playwright Chromium at %s" % pw
        if plat.os_name() == "linux":
            detail += " (if it fails to start: sudo \"%s\" \"%s\" install-deps chromium)" % (node, cli)
        if system:
            detail += "; system browser also available: %s" % system[0]["path"]
        return "ok", detail

    # --------------------------------------------------------------- models
    def install_item(self, item: Dict[str, Any]) -> Tuple[str, str]:
        files = item_files(item, self.key)
        if files is None:
            return "skip", "not available on %s" % self.key
        status, _ = item_status(item, self.home, self.key, self.state.data, verify=self.args.verify)
        if status == "ok" and not self.args.force:
            return "ok", "present"
        hows = []
        for f in files:
            name = f["url"].rsplit("/", 1)[-1]
            if f.get("archive"):
                arc = self.home / "cache" / "downloads" / ("%s-%s" % (item["id"], name))
                how = fetch(f["url"], arc, f.get("sha256"), f.get("size"), self.seeds, name, verify=True)
                dest = self.home / f["dest"]
                extract(arc, f["archive"], dest, strip=int(f.get("strip", 0)), include=f.get("include"),
                        executables=f.get("executables"))
                if f.get("executables"):
                    unquarantine(dest / e for e in f["executables"])
                arc.unlink()
                self.state.data["items"][item["id"]] = {"archive_sha256": f.get("sha256"),
                                                         "installed": time.strftime("%Y-%m-%d")}
                hows.append(how)
            else:
                dest = self.home / f["dest"]
                how = fetch(f["url"], dest, f.get("sha256"), f.get("size"), self.seeds, name, verify=self.args.verify)
                if f.get("executable") and os.name != "nt":
                    dest.chmod(0o755)
                    unquarantine([dest])
                hows.append(how)
                self.state.data["items"].setdefault(item["id"], {"installed": time.strftime("%Y-%m-%d")})
        summary = ", ".join("%d %s" % (hows.count(h), h) for h in ("downloaded", "seeded", "present") if hows.count(h))
        return "ok", "%s (%s)" % (summary, human(item_size(item, self.key)))

    # ------------------------------------------------------------ extras
    def step_musicgen(self) -> Tuple[str, str]:
        uv = self.find_uv()
        if not uv:
            return "fail", "uv not found:\n" + uv_hint()
        warning = self.man["extras"]["musicgen"]["license_warning"]
        say("  NOTE: " + warning)
        venv = self.home / "venv-musicgen"
        vpy = plat.venv_python(venv)
        env = dict(self.env_common)
        if not vpy.exists():
            cp = run([uv, "venv", "--python", PY_VERSION, str(venv)], env=env, timeout=1800)
            if cp.returncode != 0:
                return "fail", "uv venv failed:\n" + tail(cp.stdout)
        if plat.os_name() == "linux":
            # PyPI's Linux torch wheels bundle CUDA (~3 GB); the CPU index is much smaller.
            cp = run([uv, "pip", "install", "--python", str(vpy), "--index-url",
                      "https://download.pytorch.org/whl/cpu", "torch>=2.5,<3"], env=env, timeout=3600)
            if cp.returncode != 0:
                return "fail", "torch (CPU) install failed:\n" + tail(cp.stdout)
        cp = run([uv, "pip", "install", "--python", str(vpy), "-r", str(SETUP_DIR / "requirements-musicgen.in")],
                 env=env, timeout=3600)
        if cp.returncode != 0:
            return "fail", "musicgen packages failed:\n" + tail(cp.stdout)
        mg = self.man["musicgen"]
        code = ("from huggingface_hub import snapshot_download as s; print(s(%r, revision=%r, allow_patterns=%r))"
                % (mg["repo"], mg["revision"], mg["allow_patterns"]))
        cp = run([str(vpy), "-c", code], env=env, timeout=7200, capture=False)
        if cp.returncode != 0:
            return "fail", "weights download failed"
        self.state.data["musicgen"] = {"venv": str(venv), "repo": mg["repo"], "revision": mg["revision"],
                                       "license": mg["license"]}
        return "warn", "installed in %s. %s" % (venv, warning)

    def step_manim(self) -> Tuple[str, str]:
        uv = self.find_uv()
        if not uv or not self.vpy.exists():
            return "fail", "needs the main venv (run setup without --skip python first)"
        cp = run([uv, "pip", "install", "--python", str(self.vpy), "-r", str(SETUP_DIR / "requirements-manim.in")],
                 env=self.env_common, timeout=3600)
        if cp.returncode != 0:
            return "warn", "manim failed to install (pycairo/manimpango need build dependencies: %s)\n%s" % (
                manim_build_fix(), tail(cp.stdout, 8))
        # smoke test: import the engine and the kit's native parts
        code = "import manim, manimpango, cairo; print(manim.__version__)"
        cp = run([str(self.vpy), "-c", code], env=self.env_common, timeout=600)
        if cp.returncode != 0:
            return "warn", "manim installed but does not import: %s\nfix: %s" % (tail(cp.stdout, 4), manim_build_fix())
        ver = (cp.stdout or "").strip().splitlines()[-1] if cp.stdout else "?"
        tex = "LaTeX found (equations work)" if (shutil.which("latex") or Path("/Library/TeX/texbin/latex").exists()) \
            else "no LaTeX: Text, shapes and graphs work; equations need it (showtime doctor prints the install line)"
        return "ok", "manim %s in the main venv; %s" % (ver, tex)

    def step_manimgl(self) -> Tuple[str, str]:
        uv = self.find_uv()
        if not uv:
            return "fail", "uv not found:\n" + uv_hint()
        venv = self.home / "venv-manimgl"
        vpy = plat.venv_python(venv)
        if not vpy.exists():
            cp = run([uv, "venv", "--python", PY_VERSION, str(venv)], env=self.env_common, timeout=1800)
            if cp.returncode != 0:
                return "fail", "uv venv failed:\n" + tail(cp.stdout)
        cp = run([uv, "pip", "install", "--python", str(vpy), "-r", str(SETUP_DIR / "requirements-manimgl.in")],
                 env=self.env_common, timeout=3600)
        if cp.returncode != 0:
            return "fail", "manimgl failed to install:\n" + tail(cp.stdout, 8)
        # importing manimlib opens a display (pyglet): a Linux server without one runs it under xvfb-run
        prefix, no_display = plat.gl_display_prefix()
        if no_display:
            self.state.data["manimgl"] = {"venv": str(venv), "version": "1.7.2"}
            return "warn", "ManimGL 1.7.2 installed in %s, but it cannot run yet: %s" % (venv, no_display)
        cp = run(prefix + [str(vpy), "-c", "import manimlib, moderngl; print('ok')"], env=self.env_common, timeout=600)
        if cp.returncode != 0:
            return "warn", "manimgl installed but does not import (it needs OpenGL 3.3): " + tail(cp.stdout, 4)
        self.state.data["manimgl"] = {"venv": str(venv), "version": "1.7.2"}
        return "ok", "ManimGL 1.7.2 in %s (renders need OpenGL 3.3%s)" % (
            venv, "; runs under xvfb-run on this display-less machine" if prefix else "")

    # ----------------------------------------------------------------- link
    def step_link(self) -> Tuple[str, str]:
        return link_skill(force=self.args.force)

    # ------------------------------------------------------------------ run
    def run(self) -> int:
        lock = acquire_lock(self.home)
        try:
            self.preflight()
            if "ffmpeg" not in self.skip:
                self.timed("ffmpeg", self.step_ffmpeg)
            if "python" not in self.skip:
                self.timed("python", self.step_python)
            if "node" not in self.skip:
                self.timed("node", self.step_node)
            if "browser" not in self.skip:
                self.timed("browser", self.step_browser)
            if "models" not in self.skip:
                for it in select_items(self.man, self.tier, self.extras):
                    self.timed(it["id"], lambda it=it: self.install_item(it),
                               group=it.get("group"), license=it.get("license"))
            for e in self.extras:
                if self.man["extras"][e].get("lazy"):
                    self.report.add(e, "skip", "fetched automatically the first time a feature needs it")
                    continue
                if e in self.carried and not self.args.force:
                    continue   # installed by an earlier run; its files were re-checked above
                if e == "musicgen":
                    self.timed("musicgen", self.step_musicgen)
                elif e == "manim":
                    self.timed("manim", self.step_manim)
                elif e == "manimgl":
                    self.timed("manimgl", self.step_manimgl)
                elif e == "imagegen":
                    self.report.add("imagegen", "skip", "not implemented yet (planned optional extra)")
            if self.args.link:
                self.timed("skill link", self.step_link)
            prev = self.state.data.get("installed", {})
            tiers = [prev.get("tier"), self.tier]
            best = max((t for t in tiers if t in TIER_ORDER), key=TIER_ORDER.index)
            self.state.data["installed"] = {
                "tier": best,
                "extras": sorted((set(prev.get("extras", [])) | set(self.extras))
                                 - {e for e in self.extras if self.man["extras"][e].get("lazy")}),
                "platform": self.key,
            }
            self.state.save()
        finally:
            release_lock(lock)
        return self.finish()

    def finish(self) -> int:
        rows = self.report.rows
        if self.args.json:
            print(json.dumps({"ok": not self.report.failed, "home": str(self.home), "platform": self.key,
                              "tier": self.tier, "extras": self.extras, "results": rows,
                              "state": self.state.data}, indent=2))
        else:
            say("")
            say("showtime setup summary (%s, tier %s)" % (self.key, self.tier))
            w = max([len(r["component"]) for r in rows] + [10])
            for r in rows:
                first = (r["detail"] or "").splitlines()[0] if r["detail"] else ""
                say("  %-5s %s  %s" % (r["status"].upper(), r["component"].ljust(w), first[:110]))
            py = self.state.data.get("python", {}).get("packages", {})
            if py:
                say("  versions: " + ", ".join("%s %s" % kv for kv in sorted(py.items())))
            if self.report.failed:
                say("\nSome steps failed. Fix the issues above and re-run setup (it resumes where it stopped).")
            else:
                say("\nDone. Check everything with: showtime doctor")
                say("Next: ask Claude for a video, or try `showtime new dom my-video` then `showtime preview my-video`.")
                in_plugin = "/plugins/" in str(SKILL_DIR).replace("\\", "/") or os.environ.get("CLAUDE_PLUGIN_ROOT")
                if not self.args.link and not skill_linked() and not in_plugin:
                    say("Claude Code: install the showtime plugin (see README). Developers can link this checkout "
                        "instead: showtime setup --link")
        return 1 if self.report.failed else 0


def manim_build_fix() -> str:
    """Per-OS build dependencies for Manim Community's pycairo / manimpango."""
    return {"mac": "brew install cairo pango pkg-config",
            "linux": "Debian/Ubuntu: sudo apt install libcairo2-dev libpango1.0-dev pkg-config python3-dev; "
                     "Fedora: sudo dnf install cairo-devel pango-devel pkgconf-pkg-config python3-devel; "
                     "Arch: sudo pacman -S cairo pango pkgconf",
            "windows": "pycairo and manimpango ship Windows wheels; if pip builds them, install the Microsoft "
                       "C++ Build Tools"}[plat.os_name()]


# ==========================================================================
# Skill link (~/.claude/skills/showtime)
# ==========================================================================

def claude_skills_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else plat.user_home() / ".claude") / "skills"


def skill_linked() -> bool:
    link = claude_skills_dir() / "showtime"
    try:
        return link.exists() and os.path.samefile(str(link), str(SKILL_DIR))
    except OSError:
        return False


def link_skill(force: bool = False) -> Tuple[str, str]:
    link = claude_skills_dir() / "showtime"
    link.parent.mkdir(parents=True, exist_ok=True)
    marker = ".showtime-copy"
    if os.path.lexists(str(link)):
        if skill_linked() and not (link / marker).exists():
            return "ok", "%s -> %s (already linked)" % (link, SKILL_DIR)
        is_link = link.is_symlink() or _is_junction(link)
        if is_link or (link / marker).exists():
            _remove_link(link)
        elif force:
            backup = link.with_name("showtime.backup-%s" % time.strftime("%Y%m%d-%H%M%S"))
            os.replace(str(link), str(backup))
            say("  moved existing %s to %s" % (link, backup))
        else:
            return "warn", "%s exists and is a real folder; not touching it (use --force to back it up and relink)" % link
    try:
        os.symlink(str(SKILL_DIR), str(link), target_is_directory=True)
        return "ok", "symlink %s -> %s" % (link, SKILL_DIR)
    except (OSError, NotImplementedError) as e:
        if os.name != "nt":
            return "fail", "could not create symlink: %s" % e
    cp = run(["cmd", "/c", "mklink", "/J", str(link), str(SKILL_DIR)])
    if cp.returncode == 0:
        return "ok", "junction %s -> %s" % (link, SKILL_DIR)
    shutil.copytree(str(SKILL_DIR), str(link), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (link / marker).write_text("copied by showtime setup; re-run `setup.py --link` after updating\n")
    return "warn", "symlinks/junctions unavailable: copied the skill to %s (re-run --link after updates)" % link


def _is_junction(p: Path) -> bool:
    fn = getattr(os.path, "isjunction", None)
    if fn:
        return bool(fn(str(p)))
    if os.name != "nt":
        return False
    try:
        return bool(os.lstat(str(p)).st_file_attributes & 0x400) and not p.is_symlink()  # type: ignore[attr-defined]
    except (OSError, AttributeError):
        return False


def _remove_link(p: Path) -> None:
    if p.is_symlink():
        p.unlink()
    elif _is_junction(p):
        os.rmdir(str(p))
    elif p.is_dir():
        shutil.rmtree(str(p))


# ==========================================================================
# Lock
# ==========================================================================

def acquire_lock(home: Path) -> Optional[Path]:
    home.mkdir(parents=True, exist_ok=True)
    lock = home / ".setup.lock"
    for _ in range(2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return lock
        except OSError as e:
            if e.errno != errno.EEXIST:
                return None
            try:
                pid = int(lock.read_text().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            age = time.time() - lock.stat().st_mtime
            if pid and age < 6 * 3600 and _pid_alive(pid):
                raise SystemExit("setup: another setup is running (pid %d). Remove %s if that is wrong." % (pid, lock))
            lock.unlink()
    return None


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        cp = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, encoding="utf-8", errors="replace")
        return str(pid) in (cp.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def release_lock(lock: Optional[Path]) -> None:
    if lock is not None:
        try:
            lock.unlink()
        except OSError:
            pass


# ==========================================================================
# Hints
# ==========================================================================

RESTART_HINT = ("If you just installed it, restart Claude Code (or open a new terminal) so it sees the new PATH; "
                "showtime also looks in the installers' default folders.")


def uv_hint() -> str:
    if plat.os_name() == "windows":
        how = ('    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"\n'
               "    (or: winget install --id=astral-sh.uv -e)")
    else:
        how = ("    curl -LsSf https://astral.sh/uv/install.sh | sh\n"
               "    (or: pipx install uv, brew install uv, or see https://docs.astral.sh/uv/)")
    return how + "\n    " + RESTART_HINT


def node_hint() -> str:
    how = {"mac": "Install Node.js 24 or 22 LTS (20 or newer) from https://nodejs.org (or `brew install node`).",
           "windows": "Install Node.js 24 or 22 LTS (20 or newer) from https://nodejs.org (or `winget install OpenJS.NodeJS.LTS --source winget`).",
           "linux": ("Install Node.js 24 or 22 LTS (20 or newer) with fnm (`curl -fsSL https://fnm.vercel.app/install | bash`, "
                     "then `fnm install --lts`) or NodeSource (https://github.com/nodesource/distributions); "
                     "distribution packages are often older than 20.")}[plat.os_name()]
    return how + " " + RESTART_HINT


# ==========================================================================
# CLI
# ==========================================================================

def list_plan(man: Dict[str, Any], home: Path, as_json: bool) -> int:
    key = plat.platform_key()
    state = State(home).data
    out: Dict[str, Any] = {"platform": key, "home": str(home), "tiers": {}, "extras": {}}
    for t in TIER_ORDER:
        its = select_items(man, t, man.get("full_extras", []) if t == "full" else [])
        out["tiers"][t] = {"description": man["tiers"][t], "download_bytes": sum(item_size(i, key) for i in its),
                           "items": [i["id"] for i in its]}
    for name, ex in man["extras"].items():
        its = [i for i in man["items"] if i.get("extra") == name]
        st = [item_status(i, home, key, state)[0] for i in its]
        out["extras"][name] = {"description": ex["description"], "download_bytes": sum(item_size(i, key) for i in its),
                               "installed": bool(st) and all(s == "ok" for s in st), "lazy": bool(ex.get("lazy"))}
    if as_json:
        print(json.dumps(out, indent=2))
        return 0
    print("showtime setup: platform %s, home %s\n" % (key, home))
    print("tiers (--tier):")
    for t, d in out["tiers"].items():
        print("  %-8s %-9s %s" % (t, human(d["download_bytes"]), d["description"]))
    print("\nextras (--with a,b):")
    for n, d in out["extras"].items():
        size = human(d["download_bytes"]) if d["download_bytes"] else ("auto" if d.get("lazy") else "")
        print("  %-15s %-9s %s%s" % (n, size, d["description"], "  [installed]" if d["installed"] else ""))
    print("\n(sizes are downloads; the Python venv adds about 1.5 GB and Node packages about 250 MB)")
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="showtime setup",
        description="Install or update showtime's tools, Python/Node dependencies and models (idempotent).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n  showtime setup                        # core tier (the default)\n"
               "  showtime setup --list                 # tiers, extras, sizes\n"
               "  showtime setup --with asr-turbo,diarize\n"
               "  showtime setup --tier minimal         # smallest working install (CI)\n"
               "  showtime setup --estimate             # size and time, installs nothing\n"
               "  showtime setup --link                 # dev only: personal skill link to this checkout")
    ap.add_argument("--tier", choices=TIER_ORDER, default=None,
                    help="what to install (default: core, or the tier already installed)")
    ap.add_argument("--with", dest="with_", default="", metavar="EXTRAS",
                    help="comma-separated extras, e.g. asr-turbo,parakeet,diarize,events,supertonic (see --list)")
    ap.add_argument("--list", action="store_true", help="show tiers, extras and sizes, then exit")
    ap.add_argument("--estimate", action="store_true", help="print download size and time for this plan, then exit")
    ap.add_argument("--link", action="store_true",
                    help="development only: link ~/.claude/skills/showtime to this checkout (junction or copy on "
                         "Windows); the supported install is the Claude Code plugin")
    ap.add_argument("--ffmpeg", choices=["auto", "static", "system"], default="auto",
                    help="auto: keep ours or reuse a capable system ffmpeg, else download (default)")
    ap.add_argument("--skip", action="append", choices=["ffmpeg", "python", "node", "browser", "models"],
                    help="skip a step (repeatable)")
    ap.add_argument("--force", action="store_true", help="reinstall even if up to date")
    ap.add_argument("--verify", action="store_true", help="re-hash installed files against the manifest")
    ap.add_argument("--seed", action="append", metavar="DIR",
                    help="folder with already-downloaded files to reuse (matched by size + sha256; repeatable)")
    ap.add_argument("--home", help="install location (default: $SHOWTIME_HOME or ~/.showtime)")
    ap.add_argument("--json", action="store_true", help="print the final summary as JSON on stdout")
    a = ap.parse_args(argv)
    a.with_ = [x.strip() for x in a.with_.split(",") if x.strip()]
    return a


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    man = load_manifest()
    home = Path(os.path.expanduser(args.home or os.environ.get("SHOWTIME_HOME") or "~/.showtime"))
    if args.list:
        return list_plan(man, home, args.json)
    if args.estimate:
        try:
            prev = (State(home).data.get("installed") or {})
            tier = args.tier or prev.get("tier") or "core"
            est = install_estimate(tier, resolve_extras(man, tier, list(prev.get("extras", [])) + args.with_), home, man)
        except SystemExit as e:
            say(str(e))
            return 2
        if args.json:
            print(json.dumps(est, indent=2))
        else:
            print("showtime setup --tier %s%s: %s" % (tier, (" --with " + ",".join(args.with_)) if args.with_ else "",
                                                     describe_estimate(est)))
        return 0
    if args.home:
        os.environ["SHOWTIME_HOME"] = str(home)
    t0 = time.time()
    try:
        rc = Installer(args).run()
        try:  # opt-in sound logo when a long install finishes (SHOWTIME_SOUND=1, terminals only)
            from st.delight import maybe_chime
            maybe_chime(time.time() - t0, ok=rc == 0)
        except Exception:  # noqa: BLE001
            pass
        return rc
    except KeyboardInterrupt:
        say("\nsetup interrupted; re-run to resume (downloads continue where they stopped)")
        return 130


if __name__ == "__main__":
    sys.exit(main())

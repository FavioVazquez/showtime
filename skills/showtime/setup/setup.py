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
from st import mirror  # noqa: E402

UA = "showtime-setup/%s (+python urllib)" % __version__
MANIFEST_PATH = SETUP_DIR / "manifest.json"
TIER_ORDER = ["minimal", "core", "full"]
PY_VERSION = "3.12"
# Windows on Arm: showtime's venvs use x64 CPython, which Windows 11 runs through its built-in
# emulation, because ctranslate2, opencv-python, av and numba publish no Windows arm64 wheels.
VENV_PLATFORM = {"win-arm64": "win-amd64"}
MIN_NODE = 20
KEY_PACKAGES = ["numpy", "scipy", "onnxruntime", "ctranslate2", "faster-whisper", "kokoro-onnx",
                "sherpa-onnx", "opencv-python", "av", "librosa", "numba", "llvmlite", "scenedetect",
                "soundfile", "pillow", "tinysoundfont", "supertonic", "imageio-ffmpeg", "pypdfium2"]
# faster-whisper/ctranslate2 and imageio-ffmpeg are first-use components (manifest "lazy_pip"), not checked here
IMPORT_CHECK = ["numpy", "scipy", "soundfile", "PIL", "cv2", "av", "scenedetect", "onnxruntime", "kokoro_onnx",
                "sherpa_onnx", "librosa", "mido", "pretty_midi", "pyloudnorm", "requests", "pypdfium2"]


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


def rmtree_aside(path: Path, trash: Path) -> List[str]:
    """Remove a folder even when files in it are in use. On Windows a running python.exe or a loaded DLL
    cannot be deleted (WinError 5) but can be renamed: such files move into `trash` (on the same drive)
    and a later run deletes them. Returns the files moved aside; raises OSError when one cannot move."""
    moved: List[str] = []

    def onerror(func, p, exc_info):  # noqa: ANN001
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
            return
        except OSError:
            pass
        if os.path.isdir(p) and not os.path.islink(p):
            raise exc_info[1]
        trash.mkdir(parents=True, exist_ok=True)
        os.replace(p, str(trash / ("%d-%d-%s" % (os.getpid(), len(moved), os.path.basename(p)))))
        moved.append(p)
    shutil.rmtree(str(path), onerror=onerror)
    return moved


def empty_trash(trash: Path) -> None:
    """Delete what rmtree_aside moved aside earlier (files still in use stay for the next run)."""
    if trash.is_dir():
        for p in trash.iterdir():
            try:
                rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
            except OSError:
                pass


# ==========================================================================
# Manifest / selection
# ==========================================================================

def load_manifest() -> Dict[str, Any]:
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def ffmpeg_candidates(man: Dict[str, Any], key: Optional[str] = None) -> List[Dict[str, Any]]:
    """ffmpeg builds to try in order: this platform's own, then (Windows on Arm) the x64 builds,
    which Windows runs through its emulation when the native one does not start."""
    key = key or plat.platform_key()
    table = man.get("ffmpeg", {})
    out = list(table.get(key) or [])
    fallback = plat.binary_key(key)
    if fallback != key:
        out += [c for c in table.get(fallback) or [] if c not in out]
    return out


def python_request(key: Optional[str] = None) -> str:
    """The interpreter `uv venv --python` asks for on this platform (see VENV_PLATFORM)."""
    if (key or plat.platform_key()) == "win-arm64":
        return "cpython-%s-windows-x86_64-none" % PY_VERSION
    return PY_VERSION


def item_files(item: Dict[str, Any], key: str) -> Optional[List[Dict[str, Any]]]:
    """Files for this platform, or None if the item does not support it."""
    if "platform_files" in item:
        return plat.pick_for_platform(item["platform_files"], key)
    return item.get("files", [])


def select_items(man: Dict[str, Any], tier: str, extras: Iterable[str]) -> List[Dict[str, Any]]:
    """Manifest items a tier (+ extras) installs. The full tier also takes every first-use
    ("lazy") item; the browser item is the browser step's business, not the models loop's."""
    tiers = TIER_ORDER[:TIER_ORDER.index(tier) + 1] + (["lazy"] if tier == "full" else [])
    ex = set(extras)
    return [it for it in man["items"] if it.get("group") != "browser"
            and ((it.get("tier") in tiers) or (it.get("extra") and it["extra"] in ex))]


def browser_item(man: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The pinned Chrome Headless Shell (installed only when no system browser is found)."""
    return next((it for it in man["items"] if it.get("group") == "browser"), None)


def system_browsers() -> List[Dict[str, str]]:
    """Installed Chrome / Edge / Chromium (or $SHOWTIME_CHROME), best first.

    SHOWTIME_SYSTEM_BROWSER=0 ignores them (tests, or a system Chrome that misbehaves)."""
    return [b for b in plat.find_browsers(None) if b["source"] in ("system", "env")]


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
                    if n > 0:     # small files too: model configs and tokenizers are a few hundred bytes
                        idx.setdefault(n, []).append(p)
        return idx

    def find(self, size: Optional[int], sha: Optional[str], url: Optional[str] = None) -> Optional[Path]:
        if not size or not sha:
            return None
        if url:
            hit = hf_cache_find(url, sha, size)
            if hit is not None:
                return hit
        if not self.dirs:
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


# --------------------------------------------------------------------------
# Shared Hugging Face cache (read-only reuse, sha256-verified)
# --------------------------------------------------------------------------

_HF_URL = re.compile(r"^https://huggingface\.co/(?P<repo>[^/]+/[^/]+)/resolve/(?P<rev>[^/]+)/(?P<path>.+)$")


def hf_cache_dirs() -> List[Path]:
    """Hugging Face hub caches other tools filled (~/.cache/huggingface/hub, $HF_HUB_CACHE ...).

    showtime keeps its own HF_HOME under ~/.showtime, but a model file another tool already
    downloaded is reused instead of fetched again (verified by size and sha256, then hard-linked
    when possible, else copied). Opt out with SHOWTIME_SHARED_HF_CACHE=0."""
    if os.environ.get("SHOWTIME_SHARED_HF_CACHE", "1").strip().lower() in ("0", "false", "no", "off"):
        return []
    own = Path(os.path.expanduser(os.environ.get("SHOWTIME_HOME") or "~/.showtime")).resolve()
    cands: List[Path] = []
    for var in ("SHOWTIME_USER_HF_HUB_CACHE", "HF_HUB_CACHE"):
        if os.environ.get(var):
            cands.append(Path(os.path.expanduser(os.environ[var])))
    for var in ("SHOWTIME_USER_HF_HOME", "HF_HOME"):
        if os.environ.get(var):
            cands.append(Path(os.path.expanduser(os.environ[var])) / "hub")
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        cands.append(Path(xdg) / "huggingface" / "hub")
    cands.append(plat.user_home() / ".cache" / "huggingface" / "hub")
    out: List[Path] = []
    for c in cands:
        try:
            r = c.resolve()
        except OSError:
            continue
        if r.is_dir() and r not in out and own not in r.parents and r != own:
            out.append(r)
    return out


def hf_cache_find(url: str, sha: str, size: int) -> Optional[Path]:
    """A verified copy of this pinned Hugging Face file in a shared hub cache, or None.

    LFS files live in blobs/<sha256>, so a hit needs no scan; small non-LFS files are looked up
    in snapshots/<revision>/<path>. Any repository's blob with the same sha256 counts (the same
    weights are often mirrored under several repos)."""
    m = _HF_URL.match(url)
    dirs = hf_cache_dirs()
    if not dirs:
        return None
    for hub in dirs:
        cands: List[Path] = []
        if m:
            repo_dir = hub / ("models--" + m.group("repo").replace("/", "--"))
            cands += [repo_dir / "blobs" / sha, repo_dir / "snapshots" / m.group("rev") / m.group("path")]
        try:
            cands += [d / "blobs" / sha for d in hub.iterdir() if d.name.startswith("models--")]
        except OSError:
            pass
        for c in cands:
            try:
                if c.is_file() and c.stat().st_size == size and sha256_file(c) == sha:
                    return c
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


def _download_urllib(url: str, part: Path, total: Optional[int], label: str,
                     progress: Optional[Callable[[int, Optional[int]], None]] = None) -> None:
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
        if _looks_like_block_page(resp, url):
            raise mirror.Blocked("answered with a web page instead of the file (a proxy block page?)")
        code = getattr(resp, "status", 200)
        mode = "ab"
        if have and code != 206:
            mode, have = "wb", 0  # server ignored the range: restart
        prog = Progress(label, total) if progress is None else None
        done = have
        with open(part, mode) as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if prog is not None:
                    prog.update(done)
                else:
                    progress(done, total)
        if prog is not None:
            prog.update(done, final=True)


def _download_curl(url: str, part: Path) -> None:
    curl = shutil.which("curl")
    if not curl:
        raise RuntimeError("curl not available")
    cp = subprocess.run([curl, "-fL", "--retry", "3", "--connect-timeout", "30", "-A", UA,
                         "-C", "-", "-o", str(part), url])
    if cp.returncode in (5, 6, 7, 22, 56):  # no proxy/host, no connection, HTTP error, proxy refused
        raise mirror.Blocked("curl exited with %d" % cp.returncode)
    if cp.returncode not in (0, 33):  # 33: range not satisfiable (already complete)
        raise RuntimeError("curl exited with %d" % cp.returncode)


def _install_copy(src: Path, dest: Path) -> None:
    tmp = dest.with_name(dest.name + ".part")
    if tmp.exists():
        tmp.unlink()
    try:
        os.link(str(src), str(tmp))      # same filesystem: no second copy on disk
    except OSError:
        shutil.copyfile(str(src), str(tmp))
    replace_file(tmp, dest)


def _looks_like_block_page(resp: Any, url: str) -> bool:
    """A proxy that answers 200 with its own HTML page instead of the file."""
    ctype = str(resp.headers.get("Content-Type") or "").lower()
    return ctype.startswith("text/html") and not url.lower().split("?")[0].endswith((".html", ".htm"))


def _fetch_from(url: str, part: Path, sha: Optional[str], size: Optional[int], label: str,
                progress: Optional[Callable[[int, Optional[int]], None]]) -> None:
    """Download `url` into `part` and verify it. Raises mirror.Blocked when this source will not serve the
    file (no retry), IOError after the retries for anything else. A checksum mismatch deletes the part."""
    last_err: Optional[BaseException] = None
    for attempt in range(1, 5):
        try:
            try:
                _download_urllib(url, part, size, label, progress)
            except (ssl.SSLError, urllib.error.URLError) as e:
                if mirror.blocked_reason(e) is not None:
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
                    raise mirror.Blocked("sha256 mismatch: got %s, expected %s" % (actual, sha))
            return
        except (IOError, OSError, RuntimeError, urllib.error.URLError, ssl.SSLError) as e:
            why = mirror.blocked_reason(e)
            if why is not None:
                raise mirror.Blocked(why)
            last_err = e
        if attempt < 4:
            wait = 3 * attempt
            say("  %s: attempt %d failed (%s); retrying in %ds" % (label, attempt, last_err, wait))
            time.sleep(wait)
    raise IOError("%s" % last_err)


def fetch(url: str, dest: Path, sha: Optional[str], size: Optional[int], seeds: Seeds,
          label: str, verify: bool = False,
          progress: Optional[Callable[[int, Optional[int]], None]] = None) -> str:
    """Ensure `dest` holds the file. Returns 'present' | 'seeded' | 'downloaded'.

    Seeds come first (a --seed folder, a verified copy in a shared Hugging Face cache, or a
    SHOWTIME_MODEL_MIRROR folder); downloads resume from `<dest>.part`. When the primary host is
    blocked (403, a proxy refusing the connection, no route) the file comes from the model mirror
    (st/mirror.py, mirror.json); every source is sha256-verified. `progress(done, total)` replaces
    the built-in progress line (the runtime's lazy fetches report through showtime's own Progress)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and (size is None or dest.stat().st_size == size):
        if not verify or not sha or sha256_file(dest) == sha:
            return "present"
        say("  %s: checksum mismatch, re-downloading" % dest.name)
        dest.unlink()
    seeded = seeds.find(size, sha, url)
    if seeded is not None:
        _install_copy(seeded, dest)
        return "seeded"
    local = mirror.local_copy(url)
    if local is not None:
        if (size is None or local.stat().st_size == size) and (not sha or sha256_file(local) == sha):
            _install_copy(local, dest)
            return "seeded"
        say("  %s: %s in %s does not match the pinned checksum; ignored" % (label, local.name, local.parent))
    if os.environ.get("SHOWTIME_OFFLINE", "") not in ("", "0", "false", "no"):
        raise IOError("%s is not downloaded and SHOWTIME_OFFLINE is set (seed it with --seed DIR, "
                      "or run `showtime setup --full` on a connected machine)" % label)
    part = dest.with_name(dest.name + ".part")
    tried: List[Tuple[str, str]] = []
    for src in mirror.sources(url):
        if tried:
            say("  %s: %s; trying the model mirror at %s" % (label, tried[-1][1], mirror.host(src)))
        try:
            _fetch_from(src, part, sha, size, label, progress)
        except mirror.Blocked as e:
            tried.append((src, str(e)))
            if src == url and not str(e).startswith("sha256"):
                mirror.mark_blocked(url, str(e))
            continue
        except IOError as e:
            tried.append((src, str(e)))
            continue
        replace_file(part, dest)
        return "downloaded"
    raise IOError(mirror.describe_failure(label, url, tried))


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
    picks = {plat.exe(p) for p in (pick or []) if "*" not in p} | set(pick or [])
    exe_names = set(executables or [])

    def wanted(rel: str) -> bool:
        if pick is not None:
            base = rel.rsplit("/", 1)[-1]
            return base in picks or any("*" in p and fnmatch.fnmatch(base.lower(), p.lower()) for p in picks)
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
    """('ok'|'missing'|'legacy'|'unsupported'|'corrupt', detail) for an installed item.

    'legacy': the current files are missing but an older release's equivalent (manifest "legacy",
    e.g. the fp32 Kokoro of showtime 0.1) is here and still works. Setup treats it as missing (it
    upgrades); doctor reports it as a note, never a failure. Shared with `showtime doctor`."""
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
        old = item.get("legacy") or []
        if old and all((home / o["dest"]).is_file() and (not o.get("size") or (home / o["dest"]).stat().st_size == o["size"])
                       for o in old):
            return "legacy", "using %s from an earlier release" % ", ".join(o["dest"] for o in old)
        return "missing", ", ".join(missing[:3]) + (" ..." if len(missing) > 3 else "")
    return "ok", ""


def item_size(item: Dict[str, Any], key: str) -> int:
    return sum(int(f.get("size") or 0) for f in (item_files(item, key) or []))


def install_files(item: Dict[str, Any], home: Path, key: str, seeds: "Seeds", state: Dict[str, Any],
                  force: bool = False, verify: bool = False,
                  progress: Optional[Callable[[int, Optional[int]], None]] = None) -> Tuple[str, str]:
    """Download (or seed), verify and unpack one manifest item into `home`.

    Shared by setup and the runtime's first-use fetches (st/lazy.py). `state` is the
    state.json dict; the item's record is updated in place (the caller saves it).
    `progress(done, total)` gets cumulative bytes over all of the item's files."""
    files = item_files(item, key)
    if files is None:
        return "skip", "not available on %s" % key
    status, _ = item_status(item, home, key, state, verify=verify)
    if status == "ok" and not force:
        return "ok", "present"
    hows = []
    base = [0]

    def cb(done: int, total: Optional[int]) -> None:
        if progress is not None:
            progress(base[0] + done, None)

    for f in files:
        name = f["url"].rsplit("/", 1)[-1]
        if f.get("archive"):
            arc = home / "cache" / "downloads" / ("%s-%s" % (item["id"], name))
            how = fetch(f["url"], arc, f.get("sha256"), f.get("size"), seeds, name, verify=True,
                        progress=cb if progress else None)
            dest = home / f["dest"]
            extract(arc, f["archive"], dest, strip=int(f.get("strip", 0)), include=f.get("include"),
                    executables=f.get("executables"))
            if f.get("executables"):
                unquarantine(dest / e for e in f["executables"])
            for marker in f.get("markers", []):
                (home / marker).parent.mkdir(parents=True, exist_ok=True)
                (home / marker).write_text("", encoding="utf-8")
            arc.unlink()
            state.setdefault("items", {})[item["id"]] = {"archive_sha256": f.get("sha256"),
                                                          "installed": time.strftime("%Y-%m-%d")}
            hows.append(how)
        else:
            dest = home / f["dest"]
            how = fetch(f["url"], dest, f.get("sha256"), f.get("size"), seeds, name, verify=verify,
                        progress=cb if progress else None)
            if f.get("executable") and os.name != "nt":
                dest.chmod(0o755)
                unquarantine([dest])
            hows.append(how)
            state.setdefault("items", {}).setdefault(item["id"], {"installed": time.strftime("%Y-%m-%d")})
        base[0] += int(f.get("size") or 0)
        if progress is not None:
            progress(base[0], None)
    summary = ", ".join("%d %s" % (hows.count(h), h) for h in ("downloaded", "seeded", "present") if hows.count(h))
    return "ok", "%s (%s)" % (summary, human(item_size(item, key)))


def packages_bytes(man: Dict[str, Any], kind: str, key: str, what: str = "download") -> int:
    """Measured size of the Python or Node packages for a platform (manifest `packages`)."""
    rec = (man.get("packages") or {}).get(kind) or {}
    per = rec.get(key) or rec.get("linux-x64") or {}
    return int(per.get(what) or 0)


def install_estimate(tier: str = "core", extras: Sequence[str] = (), home: Optional[Path] = None,
                     man: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What a setup run will download and roughly how long it takes.

    Returns download_bytes (models, binaries), packages_bytes (Python + Node
    packages, when not installed yet), total_bytes and minutes_low/high
    (50 MB/s .. 8 MB/s plus a fixed install overhead), and what it takes on disk once
    installed: disk_bytes and disk (by component: python, node, ffmpeg, browser, models;
    from the measured sizes in the manifest's "disk" table and packages.*.disk). Used by
    the launcher's first-run message and setup's own preflight line.
    """
    man = man or load_manifest()
    key = plat.platform_key()
    home = home or Path(os.path.expanduser(os.environ.get("SHOWTIME_HOME") or "~/.showtime"))
    sizes = man.get("disk") or {}
    disk: Dict[str, int] = {}
    items = select_items(man, tier, list(extras))
    todo = [it for it in items if item_status(it, home, key)[0] != "ok"]
    dl = sum(item_size(it, key) for it in todo)
    disk["models"] = dl
    ff_have = (home / "bin" / plat.exe("ffmpeg")).is_file()
    if not ff_have:
        cands = plat.pick_for_platform(man.get("ffmpeg", {}), key) or []
        if cands:
            ff_dl = sum(int(f.get("size") or 0) for f in cands[0].get("files", []))
            dl += ff_dl
            disk["ffmpeg"] = int((sizes.get("ffmpeg") or {}).get(cands[0].get("id"), 0) or ff_dl)
    browser = browser_item(man)
    if browser is not None and not system_browsers() and item_status(browser, home, key)[0] != "ok":
        dl += item_size(browser, key)
        disk["browser"] = int(plat.pick_for_platform(sizes.get("browser") or {}, key) or item_size(browser, key))
    if tier == "full":   # --full also takes the first-use parts that are not manifest items
        ids = {it["id"] for it in man["items"]}
        later = sum(r["size"] for r in plan_rows(man, key, home) if r["tier"] == "first-use"
                    and r["component"] not in ids and not r["component"].startswith("Chrome Headless Shell"))
        dl += later
        disk["models"] += later
    pk = 0
    if not plat.venv_python(home / "venv").exists():
        pk += packages_bytes(man, "python", key)
        disk["python"] = packages_bytes(man, "python", key, "disk") or 3 * packages_bytes(man, "python", key)
    if not (home / "node" / "node_modules" / "playwright").is_dir():
        pk += packages_bytes(man, "node", key)
        disk["node"] = packages_bytes(man, "node", key, "disk") or 8 * packages_bytes(man, "node", key)
    total = dl + pk
    mb = total / 1024.0 ** 2
    low = mb / 50.0 / 60.0 + (2 if pk else 0.2)
    high = mb / 8.0 / 60.0 + (5 if pk else 0.5)
    disk = {k: v for k, v in disk.items() if v}
    return {"tier": tier, "extras": list(extras), "download_bytes": dl, "packages_bytes": pk, "total_bytes": total,
            "items": [it["id"] for it in todo], "minutes_low": max(1, int(round(low))),
            "minutes_high": max(2, int(round(high))), "disk_bytes": sum(disk.values()), "disk": disk}


# what grows after setup (setup --estimate says so): the parts features fetch the first time they are used
GROWS_LATER = ("Later: features fetch their parts the first time they are used (the first transcription adds "
               "about 490 MB, its speech model), `showtime setup --full` takes them all now (about 5 GB), and "
               "renders and the test suite keep caches in %s (about 0.7 GB after a test run). uv keeps its own "
               "copy of the Python packages in its cache (`uv cache clean` frees it), and fetches Python 3.12 "
               "(about 60 MB) when none is installed.")


def describe_disk(est: Dict[str, Any]) -> str:
    """'about 1.4 GB on disk once installed (Python packages 699 MB, Node packages 341 MB, ...)'."""
    if not est.get("disk_bytes"):
        return ""
    names = {"python": "Python packages", "node": "Node packages", "ffmpeg": "ffmpeg", "browser": "browser",
             "models": "models"}
    parts = ["%s %s" % (names.get(k, k), human(v)) for k, v in sorted(est["disk"].items(), key=lambda kv: -kv[1])]
    return "about %s on disk once installed (%s)" % (human(est["disk_bytes"]), ", ".join(parts))


def find_uv() -> Optional[str]:
    env = os.environ.get("SHOWTIME_UV")
    if env and Path(env).is_file():
        return env
    return plat.find_tool("uv")


def find_node() -> Tuple[Optional[str], Optional[Tuple[int, ...]]]:
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


def missing_prereqs(skip: Iterable[str] = ()) -> List[Dict[str, str]]:
    """The tools setup cannot download itself, checked before anything is fetched: uv (builds the
    Python environment) and Node.js 20+ (renders). -> [{tool, problem, fix}], empty when both are here."""
    skip = set(skip)
    out: List[Dict[str, str]] = []
    if "python" not in skip and not find_uv():
        out.append({"tool": "uv", "problem": "uv was not found (setup uses it to build the Python environment)",
                    "fix": uv_hint()})
    if "node" not in skip:
        node, ver = find_node()
        if not node:
            out.append({"tool": "node", "problem": "Node.js was not found (it renders the videos)", "fix": "    " + node_hint()})
        elif ver and ver[0] < MIN_NODE:
            out.append({"tool": "node", "problem": "Node.js %s is too old (showtime needs %d or newer)"
                        % (".".join(map(str, ver)), MIN_NODE), "fix": "    " + node_hint()})
    return out


def describe_prereqs(missing: Sequence[Dict[str, str]]) -> str:
    lines = []
    for m in missing:
        lines.append("  %s. Install it:\n%s" % (m["problem"], m["fix"]))
    lines.append("Nothing was downloaded. Install %s, then run `showtime setup` again."
                 % " and ".join("Node.js" if m["tool"] == "node" else m["tool"] for m in missing))
    return "\n".join(lines)


def describe_estimate(est: Dict[str, Any]) -> str:
    """'about 522 MB to download (258 MB models and tools + 264 MB Python/Node packages), about 1.3 GB on disk,
    usually 2-6 min'."""
    if est["total_bytes"] <= 0:
        return "nothing to download (already installed)"
    parts = []
    if est["download_bytes"]:
        parts.append("%s models and tools" % human(est["download_bytes"]))
    if est["packages_bytes"]:
        parts.append("%s Python/Node packages" % human(est["packages_bytes"]))
    disk = (", about %s on disk" % human(est["disk_bytes"])) if est.get("disk_bytes") else ""
    return "about %s to download (%s)%s, usually %d-%d min" % (human(est["total_bytes"]), " + ".join(parts), disk,
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
        self.tier = "full" if getattr(args, "full", False) else (
            args.tier or (prev.get("tier") if prev.get("tier") in TIER_ORDER else "core"))
        keep = [e for e in prev.get("extras", []) if e in self.man["extras"]]
        auto = [e for e, ex in self.man["extras"].items() if ex.get("auto")] if getattr(args, "full", False) else []
        self.extras = resolve_extras(self.man, self.tier, keep + list(args.with_) + auto)
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
        return find_uv()

    def find_node(self) -> Tuple[Optional[str], Optional[Tuple[int, ...]]]:
        return find_node()

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
        elif o == "windows" and not VENV_PLATFORM.get(self.key):
            # this Python has the venv's architecture: its probe tells whether onnxruntime will load
            vc = plat.missing_vc_runtime()
            if vc:
                self.report.add("vc++ runtime", "warn", "Microsoft Visual C++ 2015-2022 x64 runtime not found; voices "
                                "and transcription will not load until it is installed: " + plat.vc_runtime_fix(vc))
                say("  " + plat.vc_runtime_fix(vc))
        if plat.pick_for_platform(self.man["ffmpeg"], self.key) is None:
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
    def _ff_check(self, ffmpeg: str, timeout: float = 30) -> Tuple[bool, List[str], List[str], str]:
        from st.ff import (REQUIRED_ENCODERS, REQUIRED_FILTERS, RECOMMENDED_FILTERS,
                           RECOMMENDED_ENCODERS, _list_names, _run_version, probe_features, too_old)
        v, why = _run_version(ffmpeg, timeout)
        if not v:
            return False, ["(does not run: %s)" % why], [], ""
        filters, encoders = set(_list_names(ffmpeg, "filters")), set(_list_names(ffmpeg, "encoders"))
        miss_req = [f for f in REQUIRED_FILTERS if f not in filters] + [e for e in REQUIRED_ENCODERS if e not in encoders]
        # an old build (Ubuntu 22.04's 4.4.2) has the filters but not the options showtime uses
        old = too_old(v, probe_features(ffmpeg))
        if old:
            miss_req.insert(0, "too old: " + ", ".join(old))
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
                return "fail", "no capable system ffmpeg found (an older build lacks what showtime uses): " \
                               "use showtime's own build: `showtime setup --ffmpeg static`"
        cands = ffmpeg_candidates(self.man, self.key)
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
                # the first start of a freshly unpacked binary can wait on a virus scan
                ok, req, rec, v = self._ff_check(str(ours), timeout=180)
                if not ok:
                    errors.append("%s: missing %s" % (cand["id"], ", ".join(req)))
                    if len(cands) > 1:
                        say("  ffmpeg candidate %s not usable (%s); trying the next one" % (cand["id"], ", ".join(req)))
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
        h.update(("|".join(sorted(extra)) + "|" + python_request(self.key)).encode())
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
        why = "--force" if self.args.force else ("python %s" % pyv if pyv != PY_VERSION else "")
        want_plat = VENV_PLATFORM.get(self.key)
        if not why and want_plat:
            cp = run([str(self.vpy), "-c", "import sysconfig; print(sysconfig.get_platform())"])
            have = cp.stdout.strip()
            if have != want_plat:
                why = "%s Python, %s needed" % (have or "unknown", want_plat)
        trash = self.home / "cache" / "trash"
        empty_trash(trash)
        if why:
            if venv.exists():
                say("  recreating venv (%s)" % why)
                try:
                    aside = rmtree_aside(venv, trash)
                except OSError as e:
                    return "fail", ("cannot remove the old venv %s (%s): a running showtime process uses it, often "
                                    "your coding agent's showtime MCP server or a preview. Close it (or quit the "
                                    "agent), then run `showtime setup --force` again." % (venv, e))
                if aside:
                    say("  %d file(s) of the old venv are still in use (%s): moved to %s, the next setup deletes them"
                        % (len(aside), Path(aside[0]).name, trash))
            if want_plat:
                say("  %s: using x64 Python %s, run by Windows' emulation (some packages have no arm64 wheels)"
                    % (self.key, PY_VERSION))
            cp = run([uv, "venv", "--python", python_request(self.key), str(venv)], env=env, timeout=1800)
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
            vc = plat.missing_vc_runtime(self.vpy) if plat.IS_WINDOWS else []
            if vc or (plat.IS_WINDOWS and any("DLL load failed" in v for v in bad.values())):
                return "fail", "%s; imports failing: %s" % (plat.vc_runtime_fix(vc), "; ".join("%s (%s)" % kv for kv in bad.items()))
            return "fail", "imports failing: " + "; ".join("%s (%s)" % kv for kv in bad.items())
        return "ok", detail + "; python %s" % self.venv_version()

    def step_espeak(self) -> Tuple[str, str]:
        """The espeak-ng self-test doctor runs (st.voice.espeak.check): Kokoro cannot speak without it."""
        code = "import json\nfrom st.voice.espeak import check\nprint(json.dumps(check(refresh=True)))\n"
        cp = run([str(self.vpy), "-c", code], env=dict(self.env_common, PYTHONPATH=str(LIB_DIR)), timeout=300)
        try:
            res = json.loads(cp.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return "fail", "the self-test did not run:\n" + tail(cp.stdout)
        if not res.get("ok"):
            return "fail", "%s\nfix: %s" % (res.get("error"), res.get("hint"))
        return "ok", "%s (%s), self-test passed" % (res.get("source"), res.get("lib"))

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
        """An installed Chrome / Edge / Chromium costs nothing; otherwise the pinned Chrome Headless
        Shell (~100-120 MB). Full Chromium only for --with chromium, or --full without a system browser
        (headed captures); otherwise a --headed run fetches it on first use."""
        system = system_browsers()
        want_full = "chromium" in self.extras or (self.tier == "full" and not system)
        notes = []
        if system and not want_full:
            self.state.data["browser"] = system[0]
            return "ok", "%s: %s (0 MB; if it cannot render, the headless shell is fetched on first use)" % (
                system[0]["kind"], system[0]["path"])
        shell = browser_item(self.man)
        if not system and shell is not None:
            st, detail = install_files(shell, self.home, self.key, self.seeds, self.state.data,
                                       force=self.args.force, verify=self.args.verify)
            if st == "skip":
                notes.append("no pinned headless shell for %s" % self.key)
                want_full = True
            else:
                exe = self.home / (item_files(shell, self.key) or [{}])[0].get("creates", "")
                self.state.data["browser"] = {"kind": "headless-shell", "path": str(exe), "source": "showtime"}
                notes.append("Chrome Headless Shell %s at %s (%s)" % (shell.get("version", ""), exe.parent, detail))
        if want_full:
            node, _ = self.find_node()
            cli = self.home / "node" / "node_modules" / "playwright" / "cli.js"
            if not node or not cli.is_file():
                return "fail", "Playwright is not installed (Node step failed), and no Chrome/Edge was found"
            say("  installing Playwright Chromium (full browser, for headed captures) into %s ..." % (self.home / "browsers"))
            cp = run([node, str(cli), "install", "--no-shell", "chromium"], env=self.env_common, timeout=3600)
            if cp.returncode != 0:
                return "fail", "playwright install chromium failed:\n" + tail(cp.stdout)
            pw = plat.playwright_chromium(self.home / "browsers")
            if not notes:
                self.state.data["browser"] = {"kind": "playwright", "path": str(pw) if pw else None}
            notes.append("Playwright Chromium at %s" % pw)
        if system:
            notes.append("system browser also available: %s" % system[0]["path"])
        detail = "; ".join(notes)
        if plat.os_name() == "linux" and not system:
            node, _ = self.find_node()
            detail += " (if it fails to start: sudo \"%s\" \"%s\" install-deps chromium)" % (
                node or "node", self.home / "node" / "node_modules" / "playwright" / "cli.js")
        return "ok", detail

    # --------------------------------------------------------------- models
    def install_item(self, item: Dict[str, Any]) -> Tuple[str, str]:
        return install_files(item, self.home, self.key, self.seeds, self.state.data,
                             force=self.args.force, verify=self.args.verify)

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
            cp = run([uv, "venv", "--python", python_request(self.key), str(venv)], env=env, timeout=1800)
            if cp.returncode != 0:
                return "fail", "uv venv failed:\n" + tail(cp.stdout)
        if plat.os_name() == "linux":
            # PyPI's Linux torch wheels bundle CUDA (~3 GB); the CPU index is much smaller.
            cp = run([uv, "pip", "install", "--python", str(vpy), "--index-url",
                      "https://download.pytorch.org/whl/cpu", "torch>=2.13,<3"], env=env, timeout=3600)
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

    def step_audio_extra(self, name: str) -> Tuple[str, str]:
        """Pre-fetch what is otherwise downloaded on first use: every produced-music catalog track
        (music-catalog) or every extra sound-effect pack (sfx-packs), for offline machines."""
        if not self.vpy.exists():
            return "fail", "needs the main venv (run setup without --skip python first)"
        if name == "music-catalog":
            cmd = ["audio", "music", "fetch", "--all", "--json"] + sum((["--seed", d] for d in (self.args.seed or [])), [])
        else:
            cmd = ["audio", "packs", "fetch", "--all", "--json"]
        env = dict(self.env_common, SHOWTIME_HOME=str(self.home))
        cp = run([str(self.vpy), str(LIB_DIR / "st" / "launcher.py")] + cmd, env=env, timeout=6 * 3600)
        try:
            rep = json.loads((cp.stdout or "")[(cp.stdout or "").index("{"):])
        except ValueError:
            return "fail", "exit %d\n%s" % (cp.returncode, tail(cp.stdout, 8))
        done = len(rep.get("fetched", rep.get("installed", [])))
        # music: "skipped" = tracks whose creator asks for no bulk downloads (they come on first use); packs: already there
        have = len(rep["cached"]) if "cached" in rep else len(rep.get("skipped", []))
        later = len(rep.get("skipped", [])) if "cached" in rep else 0
        failed = rep.get("failed") or []
        msg = "%d downloaded, %d already present%s%s" % (
            done, have, ", %d left for first use (their creator asks for no bulk downloads)" % later if later else "",
            ", %d failed (first: %s)" % (len(failed), failed[0].get("error", "")[:120]) if failed else "")
        return ("warn" if failed else "ok"), msg

    def step_manimgl(self) -> Tuple[str, str]:
        uv = self.find_uv()
        if not uv:
            return "fail", "uv not found:\n" + uv_hint()
        venv = self.home / "venv-manimgl"
        vpy = plat.venv_python(venv)
        if not vpy.exists():
            cp = run([uv, "venv", "--python", python_request(self.key), str(venv)], env=self.env_common, timeout=1800)
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
    # ----------------------------------------------------- first-use parts
    def venv_lazy(self, names: Sequence[str]) -> Tuple[str, str]:
        """Fetch runtime components that need the venv (Python packages, icons, audio packs)."""
        if not self.vpy.exists():
            return "fail", "needs the Python environment first: run `showtime setup`"
        env = dict(self.env_common, PYTHONPATH=str(LIB_DIR), SHOWTIME_SKILL=str(SKILL_DIR))
        if self.seeds.dirs:
            env["SHOWTIME_SEED_DIRS"] = os.pathsep.join(str(d) for d in self.seeds.dirs)
        cp = run([str(self.vpy), "-m", "st.lazy", "fetch"] + list(names), env=env, capture=False, timeout=6 * 3600)
        return ("ok", "fetched %s" % ", ".join(names)) if cp.returncode == 0 else (
            "fail", "fetching %s failed (exit %d); re-run to resume" % (", ".join(names), cp.returncode))

    def step_imageio_fallback(self) -> Tuple[str, str]:
        """Last-resort ffmpeg when neither the static build nor a system ffmpeg works."""
        return self.venv_lazy(["imageio-ffmpeg"])

    def install_full_chromium(self) -> Tuple[str, str]:
        node, _ = self.find_node()
        cli = self.home / "node" / "node_modules" / "playwright" / "cli.js"
        if not node or not cli.is_file():
            return "fail", "Playwright is not installed (run `showtime setup` first)"
        size = ((self.man["extras"].get("chromium") or {}).get("download_bytes") or {}).get(self.key)
        say("  installing Playwright Chromium (full browser%s) into %s ..." % (
            ", %s" % human(size) if size else "", self.home / "browsers"))
        cp = run([node, str(cli), "install", "--no-shell", "chromium"], env=self.env_common, timeout=3600)
        if cp.returncode != 0:
            return "fail", "playwright install chromium failed:\n" + tail(cp.stdout)
        return "ok", "Playwright Chromium at %s" % plat.playwright_chromium(self.home / "browsers")

    def fetch_one(self, name: str) -> Tuple[str, str]:
        man = self.man
        item = next((it for it in man["items"] if it["id"] == name), None)
        if name in ("browser", "chromium-headless-shell"):
            item = browser_item(man)
        if item is not None:
            return install_files(item, self.home, self.key, self.seeds, self.state.data,
                                 force=self.args.force, verify=self.args.verify)
        if name == "chromium":
            return self.install_full_chromium()
        if name in man["extras"]:
            steps = {"musicgen": self.step_musicgen, "manim": self.step_manim, "manimgl": self.step_manimgl,
                     "music-catalog": lambda: self.step_audio_extra("music-catalog"),
                     "sfx-packs": lambda: self.step_audio_extra("sfx-packs")}
            if name in steps:
                st, detail = steps[name]()
            else:
                its = [it for it in man["items"] if it.get("extra") == name]
                if not its:
                    return "skip", "nothing to fetch for %s" % name
                res = [install_files(it, self.home, self.key, self.seeds, self.state.data,
                                     force=self.args.force, verify=self.args.verify) for it in its]
                st = "fail" if any(r[0] == "fail" for r in res) else "ok"
                detail = "; ".join(r[1] for r in res)
            if st in ("ok", "warn"):
                inst = self.state.data.setdefault("installed", {"tier": "core", "extras": [], "platform": self.key})
                inst["extras"] = sorted(set(inst.get("extras", [])) | {name})
            return st, detail
        if name in (man.get("lazy_pip") or {}) or name in ("icons", "audio-library", "library") or name.startswith("library:"):
            return self.venv_lazy([name])
        raise SystemExit("setup: unknown component %r (see `showtime setup --plan`)" % name)

    def run_fetch(self, names: Sequence[str]) -> None:
        say("showtime setup --fetch %s  |  %s  |  home %s" % (",".join(names), self.key, self.home))
        for n in names:
            self.timed(n, lambda n=n: self.fetch_one(n))

    def fetch_first_use(self) -> None:
        """--full: everything the default install leaves for first use."""
        self.timed("first-use components", lambda: self.venv_lazy(
            [n for n, spec in (self.man.get("lazy_pip") or {}).items() if not spec.get("fallback_only")]
            + ["icons", "audio-library"]))

    def prune(self) -> Tuple[str, str]:
        """Remove files a newer manifest replaced (listed in manifest "superseded"), once their replacement is here."""
        gone, freed = [], 0
        for sup in self.man.get("superseded", []):
            p = self.home / sup["dest"]
            by = next((it for it in self.man["items"] if it["id"] == sup.get("by")), None)
            if not p.is_file() or by is None or item_status(by, self.home, self.key)[0] != "ok":
                continue
            env_model = os.environ.get("SHOWTIME_KOKORO_MODEL")
            if env_model and os.path.abspath(env_model) == os.path.abspath(str(p)):
                continue
            freed += p.stat().st_size
            p.unlink()
            gone.append(sup["dest"])
        return "ok", ("removed %s (%s freed)" % (", ".join(gone), human(freed))) if gone else "nothing to remove"

    def superseded_note(self) -> None:
        old = [self.home / s["dest"] for s in self.man.get("superseded", []) if (self.home / s["dest"]).is_file()]
        if old:
            say("  note: %d file(s) from an older version are no longer used (%s): `showtime setup --prune` removes them"
                % (len(old), human(sum(p.stat().st_size for p in old))))

    def run(self) -> int:
        lock = acquire_lock(self.home)
        try:
            if self.args.fetch or self.args.prune:
                if self.args.fetch:
                    self.run_fetch(self.args.fetch)
                if self.args.prune:
                    self.timed("prune", self.prune)
                self.state.save()
                return self.finish()
            self.preflight()
            # uv and Node.js are installed by the user: say so before the first download, not after 200 MB
            missing = missing_prereqs(self.skip)
            if missing:
                for m in missing:
                    self.report.add(m["tool"], "fail", "%s; install it:\n%s" % (m["problem"], m["fix"]))
                say(describe_prereqs(missing))
                return self.finish()
            ffmpeg_ok = True
            if "ffmpeg" not in self.skip:
                self.timed("ffmpeg", self.step_ffmpeg)
                ffmpeg_ok = self.report.rows[-1]["status"] != "fail"
            if "python" not in self.skip:
                self.timed("python", self.step_python)
                if self.report.rows[-1]["status"] != "fail":
                    self.timed("espeak-ng", self.step_espeak)
                if not ffmpeg_ok:
                    self.timed("imageio-ffmpeg", self.step_imageio_fallback)
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
                elif e in ("music-catalog", "sfx-packs"):
                    self.timed(e, lambda e=e: self.step_audio_extra(e))
                elif e == "imagegen":
                    self.report.add("imagegen", "skip", "not implemented yet (planned optional extra)")
            if self.tier == "full" and "models" not in self.skip:
                self.fetch_first_use()
            if self.args.link:
                self.timed("skill link", self.step_link)
            self.superseded_note()
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
            self.timed("showtime command", self.step_shim)
        finally:
            release_lock(lock)
        return self.finish()

    def step_shim(self) -> Tuple[str, str]:
        """The stable <home>/bin/showtime (+ .cmd/.ps1 on Windows) that runs this skill (st/shim.py)."""
        from st import shim
        code, detail = shim.install(self.home, SKILL_DIR)
        return ("ok" if code == "ok" else "warn"), detail

    def finish(self) -> int:
        rows = self.report.rows
        if self.args.json:
            print(json.dumps({"ok": not self.report.failed, "home": str(self.home), "platform": self.key,
                              "tier": self.tier, "extras": self.extras, "results": rows,
                              "state": self.state.data}, indent=2))
        elif self.args.fetch or self.args.prune:
            # a first-use fetch (often inside another command): the step lines above say it all
            if self.report.failed:
                say("fetch failed: fix the issue above and run it again (downloads resume where they stopped)")
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
                try:
                    from st import shim
                    for line in shim.path_hint(self.home):
                        say(line)
                except Exception:  # noqa: BLE001 - advice only
                    pass
                say("Next: ask your coding agent for a video, or try `showtime new dom my-video` then `showtime preview my-video`.")
                in_plugin = "/plugins/" in str(SKILL_DIR).replace("\\", "/") or os.environ.get("CLAUDE_PLUGIN_ROOT")
                if not self.args.link and not skill_linked() and not in_plugin:
                    say("To use showtime in your coding agent, install it there: the steps for Claude Code, Codex, Cursor, "
                        "Devin, OpenCode and more are at "
                        "https://github.com/FavioVazquez/showtime/blob/main/docs/agents.md . Developers can link this "
                        "checkout for Claude Code instead: showtime setup --link")
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

RESTART_HINT = ("If you just installed it, restart your coding agent (or open a new terminal) so it sees the new PATH; "
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
                               "installed": bool(st) and all(s == "ok" for s in st), "lazy": bool(ex.get("lazy")),
                               "auto": bool(ex.get("auto"))}
    if as_json:
        print(json.dumps(out, indent=2))
        return 0
    print("showtime setup: platform %s, home %s\n" % (key, home))
    print("tiers (--tier):")
    for t, d in out["tiers"].items():
        print("  %-8s %-9s %s" % (t, human(d["download_bytes"]), d["description"]))
    print("\nextras (--with a,b):")
    for n, d in out["extras"].items():
        size = human(d["download_bytes"]) if d["download_bytes"] else ("auto" if d.get("lazy") or d.get("auto") else "")
        print("  %-15s %-9s %s%s" % (n, size, d["description"], "  [installed]" if d["installed"] else ""))
    print("\n(sizes are downloads; `showtime setup --plan` shows every component, its URL, sha256 and when it is fetched)")
    return 0


# ==========================================================================
# Plan: every component, its tier, URL, size, sha256 and when it is fetched
# ==========================================================================

PLATFORMS = ["mac-arm64", "mac-x64", "win-x64", "linux-x64", "linux-arm64"]


def _mb(n: Optional[int]) -> str:
    return "-" if not n else ("%.1f MB" % (n / 1e6))


def plan_rows(man: Dict[str, Any], key: str, home: Optional[Path] = None,
              system_browser: Optional[bool] = None) -> List[Dict[str, Any]]:
    """One row per component for platform `key`: {component, tier, url, size, sha256, when, files}.

    tier: default (the first `showtime setup`), first-use (fetched when a feature needs it, or
    by --full), extra (`--with NAME`), full (only with --full / --tier full). `files` lists every
    pinned file ({url, sha256, size}) for pre-seeding offline machines."""
    rows: List[Dict[str, Any]] = []
    here = key == plat.platform_key()
    if system_browser is None:
        system_browser = bool(system_browsers()) if here else False

    def add(component: str, tier: str, when: str, files: List[Dict[str, Any]], url: str = "", size: int = 0,
            sha: str = "", note: str = "") -> None:
        if files and not url:
            url = files[0]["url"] + ((" (+%d more)" % (len(files) - 1)) if len(files) > 1 else "")
        if files and not size:
            size = sum(int(f.get("size") or 0) for f in files)
        if files and not sha:
            sha = files[0].get("sha256") or ""
        row = {"component": component, "tier": tier, "url": url, "size": int(size or 0), "sha256": sha, "when": when,
               "files": [{"url": f["url"], "sha256": f.get("sha256"), "size": f.get("size")} for f in files]}
        if note:
            row["note"] = note
        rows.append(row)

    ff = (man.get("ffmpeg") or {}).get(key) or []
    if ff:
        add("ffmpeg + ffprobe (%s)" % ff[0]["id"], "default", "setup (skipped when a capable system ffmpeg is found)",
            ff[0]["files"], note=ff[0].get("notes", ""))
    pk = man.get("packages") or {}
    py = (pk.get("python") or {}).get(key) or {}
    add("Python packages", "default", "setup", [], url="PyPI via uv (setup/requirements.txt, exact versions)",
        size=int(py.get("download") or 0), sha="versions pinned in requirements.txt",
        note="%s on disk" % _mb(py.get("disk")) if py.get("disk") else "")
    if py.get("python_download"):
        add("Python 3.12 (uv-managed)", "default", "setup, only if no Python 3.12 is installed", [],
            url="https://github.com/astral-sh/python-build-standalone (via uv)", size=int(py["python_download"]),
            sha="checked by uv")
    nd = (pk.get("node") or {}).get(key) or {}
    add("Node packages", "default", "setup", [], url="registry.npmjs.org (setup/package-lock.json)",
        size=int(nd.get("download") or 0), sha="sha512 per package in package-lock.json",
        note="%s on disk" % _mb(nd.get("disk")) if nd.get("disk") else "")
    shell = browser_item(man)
    if shell is not None and item_files(shell, key):
        add("Chrome Headless Shell %s" % shell.get("version", ""), "default" if not system_browser else "first-use",
            "setup when no Chrome/Edge/Chromium is installed%s" % (
                " (this machine has one: fetched only if it cannot render)" if system_browser else ""),
            item_files(shell, key) or [])
    for it in man["items"]:
        if it.get("group") == "browser":
            continue
        files = item_files(it, key)
        if files is None:
            continue
        if it.get("tier") in ("minimal", "core"):
            tier, when = "default", "setup"
        elif it.get("tier") == "lazy":
            tier, when = "first-use", it.get("when", "first use")
        elif it.get("extra") in man.get("full_extras", []):
            tier, when = "full", "--full, or `showtime setup --with %s`" % it["extra"]
        else:
            tier, when = "extra", "`showtime setup --with %s`" % it.get("extra")
        add(it["id"], tier, when, files)
    for cid, spec in (man.get("lazy_pip") or {}).items():
        b = spec.get("download_bytes") or {}
        add(cid, "fallback" if spec.get("fallback_only") else "first-use", spec.get("when", "first use"), [],
            url="PyPI via uv (setup/%s)" % spec["requirements"], size=int(b.get(key) or b.get("linux-x64") or 0),
            sha="versions pinned in setup/%s" % spec["requirements"])
    for name, ex in man["extras"].items():
        if ex.get("auto"):
            add(name, "first-use", ex.get("when", "first use"), [], url="PyPI via uv (setup/requirements-%s.in)" % name,
                size=int(ex.get("approx_bytes") or 0), sha="resolved by uv", note="size approximate")
    ch = man["extras"].get("chromium") or {}
    if ch.get("download_bytes"):
        add("chromium (full)", "first-use" if not system_browser else "extra", ch.get("when", ""), [],
            url=str(ch.get("url", "")).replace("{platform}", {"linux-x64": "linux64", "win-x64": "win64"}.get(key, key)),
            size=int((ch["download_bytes"] or {}).get(key) or 0), sha="checked by Playwright")
    packs_file = SKILL_DIR / "lib" / "st" / "audio" / "library_manifest.json"
    try:
        lib = json.loads(packs_file.read_text(encoding="utf-8"))
        from st.audio import libparts as _parts  # stdlib only
        for name, desc in _parts.PARTS.items():
            srcs = [x for x in lib["sources"] if _parts.part_of(x) == name]
            files = [{"url": x["url"], "sha256": x.get("sha256"), "size": x.get("bytes")} for x in srcs]
            when = ("first use of the audio library" if name == "starter" else
                    "`showtime audio lib fetch --tier extended`" if name == "extended" else
                    "a search that needs it (or `showtime audio lib fetch --part %s`)" % name)
            add("library part %s" % name, "first-use" if name != "extended" else "extra", when, files,
                url="%d pinned files (lib/st/audio/library_manifest.json)" % len(files),
                sha="sha256 per file" if name != "extended" else "sha256 recorded on first download")
    except Exception as e:  # noqa: BLE001 - the plan never fails on the library
        say("  (audio library parts not listed: %s)" % e)
    from st import lazy as _lazy
    for name, ex in man["extras"].items():
        if ex.get("first_use"):
            files = _lazy.audio_extra_files(name)
            add(name, "first-use", "%s; all now: `showtime setup --fetch %s` (or --full)" % (ex.get("when", "first use"), name),
                files, url="%d pinned files (%s)" % (len(files), {"music-catalog": "lib/st/audio/music_catalog.json",
                                                                 "sfx-packs": "lib/st/audio/sfx_packs.json"}.get(name, name)),
                sha="sha256 per file")
    icons = man.get("icon_packs") or []
    if icons:
        add("icons", "first-use", "per icon on first use (a few KB each, pinned versions on jsDelivr); "
            "`--fetch icons` unpacks all sets for offline use", icons,
            url="cdn.jsdelivr.net/npm/<set>@<version>/<icon>.svg, or %d npm tarballs" % len(icons))
    return rows


def plan_totals(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """Bytes per tier; "full" = what `setup --full` downloads (default + first-use + full-tier extras)."""
    t: Dict[str, int] = {}
    for r in rows:
        t[r["tier"]] = t.get(r["tier"], 0) + r["size"]
    t["full"] = sum(r["size"] for r in rows if r["tier"] in ("default", "first-use", "full")
                    and not r["component"].startswith("Chrome Headless Shell")) + sum(
        r["size"] for r in rows if r["component"].startswith("Chrome Headless Shell") and r["tier"] == "default")
    return t


def print_plan(man: Dict[str, Any], key: str, as_json: bool, urls: bool) -> int:
    rows = plan_rows(man, key)
    if urls:
        seen = set()
        for r in rows:
            for f in r["files"]:
                if f["url"] in seen:
                    continue
                seen.add(f["url"])
                print("%s  %12s  %s" % (f.get("sha256") or "-" * 64, f.get("size") or "?", f["url"]))
        return 0
    tot = plan_totals(rows)
    if as_json:
        print(json.dumps({"platform": key, "rows": rows, "totals": tot}, indent=2))
        return 0
    print("showtime setup --plan  (platform %s; sizes are downloads, MB = 1,000,000 bytes)\n" % key)
    w = max(len(r["component"]) for r in rows)
    print("%-*s  %-9s  %9s  %-16s  %s" % (w, "component", "tier", "size", "sha256", "when / from"))
    for r in rows:
        print("%-*s  %-9s  %9s  %-16s  %s" % (w, r["component"], r["tier"], _mb(r["size"]),
                                            (r["sha256"][:16] if re.match(r"^[0-9a-f]{64}$", r["sha256"] or "") else
                                             (r["sha256"] or "")[:16]), r["when"]))
        print("%-*s  %s" % (w, "", r["url"]))
    shell = next((r for r in rows if r["component"].startswith("Chrome Headless Shell")), None)
    sb = shell["size"] if shell else 0
    with_browser = tot.get("default", 0) - (sb if shell and shell["tier"] == "default" else 0)
    print("\ndefault install: %s with a Chrome/Edge/Chromium on the machine, %s without one (headless shell)"
          % (_mb(with_browser), _mb(with_browser + sb)))
    print("fetched on first use, only when a feature needs it: up to %s   everything now (--full): %s"
          % (_mb(tot.get("first-use")), _mb(tot.get("full"))))
    print("offline machines: `showtime setup --plan --urls` lists every pinned file (sha256, bytes, URL); download "
          "them anywhere into one folder, then `showtime setup --full --seed FOLDER`")
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
               "  showtime setup --plan                 # every download: tier, URL, size, sha256, when\n"
               "  showtime setup --full                 # everything now, nothing fetched later (offline use)\n"
               "  showtime setup --fetch whisper-small.en,whisper-engine   # one first-use component now\n"
               "  showtime setup --estimate             # size and time, installs nothing\n"
               "  showtime setup --link                 # dev only: personal skill link to this checkout")
    ap.add_argument("--tier", choices=TIER_ORDER, default=None,
                    help="what to install (default: core, or the tier already installed)")
    ap.add_argument("--with", dest="with_", default="", metavar="EXTRAS",
                    help="comma-separated extras, e.g. asr-turbo,parakeet,diarize,events,supertonic (see --list)")
    ap.add_argument("--list", action="store_true", help="show tiers, extras and sizes, then exit")
    ap.add_argument("--plan", action="store_true",
                    help="print every component: tier, URL, size, sha256 and when it is fetched, then exit")
    ap.add_argument("--platform", choices=PLATFORMS, help="with --plan: show another platform's downloads")
    ap.add_argument("--urls", action="store_true", help="with --plan: only the pinned files (sha256, bytes, URL)")
    ap.add_argument("--full", action="store_true",
                    help="install everything now, including what is otherwise fetched on first use "
                         "(for offline machines; add --seed DIR to reuse downloaded files)")
    ap.add_argument("--fetch", default="", metavar="NAMES",
                    help="fetch only these first-use components now, e.g. whisper-small.en,whisper-engine,icons "
                         "(names from --plan)")
    ap.add_argument("--prune", action="store_true", help="remove files from older versions that nothing uses any more")
    ap.add_argument("--estimate", action="store_true", help="print download size and time for this plan, then exit")
    ap.add_argument("--link", action="store_true",
                    help="development only: link ~/.claude/skills/showtime to this checkout (junction or copy on "
                         "Windows); to use showtime in an agent, install it there (https://github.com/FavioVazquez/showtime/blob/main/docs/agents.md)")
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
    a.fetch = [x.strip() for x in a.fetch.split(",") if x.strip()]
    if a.full and a.tier and a.tier != "full":
        ap.error("--full and --tier %s disagree" % a.tier)
    return a


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    man = load_manifest()
    home = Path(os.path.expanduser(args.home or os.environ.get("SHOWTIME_HOME") or "~/.showtime"))
    if args.list:
        return list_plan(man, home, args.json)
    if args.plan:
        return print_plan(man, args.platform or plat.platform_key(), args.json, args.urls)
    if args.estimate:
        try:
            prev = (State(home).data.get("installed") or {})
            tier = "full" if args.full else (args.tier or prev.get("tier") or "core")
            est = install_estimate(tier, resolve_extras(man, tier, list(prev.get("extras", [])) + args.with_), home, man)
        except SystemExit as e:
            say(str(e))
            return 2
        missing = missing_prereqs(args.skip or [])
        est["missing"] = [m["tool"] for m in missing]
        if args.json:
            print(json.dumps(est, indent=2))
        else:
            print("showtime setup --tier %s%s: %s" % (tier, (" --with " + ",".join(args.with_)) if args.with_ else "",
                                                     describe_estimate(est)))
            if est.get("disk_bytes"):
                print("  " + describe_disk(est))
                print("  " + GROWS_LATER % home)
            if missing:
                print("Install first (setup stops before downloading anything without it):")
                for m in missing:
                    print("  %s. Install it:\n%s" % (m["problem"], m["fix"]))
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

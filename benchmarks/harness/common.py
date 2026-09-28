"""Shared helpers for the benchmark harness (Python stdlib only).

Locations
  BENCH      this folder's parent (benchmarks/)
  REPO       the showtime repository (the plugin under test)
  home       SHOWTIME_BENCH_HOME, else ~/.vbench (a neutral name: agents can see paths): arms, runs, caches, judge packets.
             Never inside the repository.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

BENCH = Path(__file__).resolve().parent.parent
REPO = BENCH.parent
SHOWTIME = REPO / "skills" / "showtime" / "bin" / ("showtime.cmd" if os.name == "nt" else "showtime")

# The reply sent when an agent stops to ask the user something. Same text for every arm.
NEUTRAL_REPLY = ("I'm not available to answer questions right now. Use your best judgment, state your "
                 "assumptions, and finish the video.")

VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".gif"}
HTML_EXT = {".html", ".htm"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", ".cache"}


# ---------------------------------------------------------------- locations

def bench_home() -> Path:
    env = os.environ.get("SHOWTIME_BENCH_HOME")
    p = Path(env).expanduser() if env else Path.home() / ".vbench"
    p = p.resolve()
    if p == REPO or REPO in p.parents:
        raise SystemExit("SHOWTIME_BENCH_HOME must be outside the repository (got %s)" % p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def ws_root() -> Path:
    """Where agent workspaces and judge packets live: BENCH_WS_ROOT, else a shared folder OUTSIDE the
    operator's home. Claude Code discovers skills (.claude/skills) and CLAUDE.md files in every parent of
    the working directory, so a workspace under the home folder would load the operator's own skills."""
    env = os.environ.get("BENCH_WS_ROOT")
    if env:
        p = Path(env).expanduser()
    elif sys.platform == "darwin":
        p = Path("/", "Users", "Shared", "vbench-w")  # the macOS shared folder, outside every home
    elif os.name == "nt":
        p = Path(os.environ.get("PUBLIC", "C:\\Users\\Public")) / "vbench-w"
    else:
        p = Path("/var/tmp/vbench-w")
    p.mkdir(parents=True, exist_ok=True)
    p = p.resolve()
    bad = ancestor_config(p)
    if bad:
        raise SystemExit("workspace root %s has Claude Code config above it (%s): agents would load it. "
                         "FIX: set BENCH_WS_ROOT to a folder with no .claude/ or CLAUDE.md in any parent" % (p, bad))
    return p


def ancestor_config(p: Path) -> Optional[str]:
    """First .claude/ dir or CLAUDE.md found in p or any parent (None when clean)."""
    for d in [p] + list(p.parents):
        for name in (".claude", "CLAUDE.md", "CLAUDE.local.md", ".mcp.json"):
            if (d / name).exists():
                return str(d / name)
    return None


def local_arms_file() -> Path:
    env = os.environ.get("SHOWTIME_BENCH_LOCAL")
    return Path(env).expanduser() if env else bench_home() / "arms.local.json"


def claude_bin() -> str:
    env = os.environ.get("BENCH_CLAUDE")
    if env:
        return env
    for c in (Path.home() / ".local" / "bin" / "claude",):
        if c.exists():
            return str(c)
    found = shutil.which("claude")
    if not found:
        raise SystemExit("claude CLI not found. FIX: install Claude Code or set BENCH_CLAUDE=/path/to/claude")
    return found


def showtime_home() -> Path:
    env = os.environ.get("SHOWTIME_HOME")
    return Path(env).expanduser() if env else Path.home() / ".showtime"


def ffmpeg(name: str = "ffmpeg") -> str:
    """The benchmark's ffmpeg/ffprobe: BENCH_FFMPEG_DIR, else showtime's resolver dir, else PATH."""
    exe = name + (".exe" if os.name == "nt" else "")
    for d in (os.environ.get("BENCH_FFMPEG_DIR"), str(showtime_home() / "bin")):
        if d and (Path(d) / exe).exists():
            return str(Path(d) / exe)
    found = shutil.which(name)
    if not found:
        raise SystemExit("%s not found. FIX: run `showtime setup` or set BENCH_FFMPEG_DIR" % name)
    return found


def node_bin() -> str:
    env = os.environ.get("BENCH_NODE")
    if env:
        return env
    found = shutil.which("node")
    if not found:
        raise SystemExit("node not found. FIX: install Node 22+ or set BENCH_NODE")
    return found


# ---------------------------------------------------------------- specs

def load_tasks(only: Optional[List[str]] = None) -> List[Dict]:
    tasks = []
    for md in sorted((BENCH / "tasks").glob("t*.md")):
        text = md.read_text(encoding="utf-8")
        m = re.search(r"```json\s*\n(.*?)\n```", text, re.S)
        if not m:
            raise SystemExit("%s: no ```json spec block" % md.name)
        spec = json.loads(m.group(1))
        spec["_file"] = md.name
        if only and spec["id"] not in only and spec["id"].split("-")[0] not in only:
            continue
        tasks.append(spec)
    if only and not tasks:
        raise SystemExit("no task matches %s" % only)
    return tasks


def load_arms(only: Optional[List[str]] = None) -> Dict:
    cfg = json.loads((BENCH / "arms" / "arms.json").read_text(encoding="utf-8"))
    local = {}
    lf = local_arms_file()
    if lf.exists():
        local = json.loads(lf.read_text(encoding="utf-8"))
    arms = []
    for a in cfg["arms"]:
        if only and a["id"] not in only:
            continue
        a = dict(a)
        key = a.get("source", "")
        if key.startswith("local:"):
            a["local"] = local.get(key.split(":", 1)[1])
        arms.append(a)
    if only and not arms:
        raise SystemExit("no arm matches %s" % only)
    return {"common": cfg["common"], "arms": arms}


# ---------------------------------------------------------------- misc

def opaque(name: str, n: int = 8) -> str:
    return "a" + hashlib.sha1(name.encode()).hexdigest()[:n]


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def tree_digest(root: Path) -> str:
    """Stable digest of a directory's file names + contents (for arm manifests)."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and not (set(p.relative_to(root).parts) & SKIP_DIRS):
            h.update(str(p.relative_to(root)).replace(os.sep, "/").encode())
            h.update(sha256_file(p).encode())
    return h.hexdigest()


def run(cmd: List[str], **kw) -> subprocess.CompletedProcess:
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run([str(c) for c in cmd], **kw)


def probe(path: Path) -> Dict:
    """ffprobe summary: duration, size, fps, codecs, audio."""
    r = run([ffmpeg("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    if r.returncode != 0:
        return {"ok": False, "error": r.stderr.strip()[-400:]}
    d = json.loads(r.stdout or "{}")
    out = {"ok": True, "duration": float(d.get("format", {}).get("duration") or 0), "bytes": path.stat().st_size,
           "video": None, "audio": None}
    for s in d.get("streams", []):
        if s.get("codec_type") == "video" and not out["video"] and s.get("disposition", {}).get("attached_pic") != 1:
            num, _, den = (s.get("avg_frame_rate") or "0/1").partition("/")
            fps = float(num) / float(den or 1) if float(den or 1) else 0.0
            out["video"] = {"codec": s.get("codec_name"), "width": s.get("width"), "height": s.get("height"),
                            "fps": round(fps, 3), "pix_fmt": s.get("pix_fmt")}
        elif s.get("codec_type") == "audio" and not out["audio"]:
            out["audio"] = {"codec": s.get("codec_name"), "channels": s.get("channels"),
                            "sample_rate": s.get("sample_rate")}
    return out


def aspect_label(w: int, h: int) -> str:
    if not w or not h:
        return "?"
    r = w / h
    for name, val in (("16:9", 16 / 9), ("9:16", 9 / 16), ("1:1", 1.0), ("4:5", 0.8), ("4:3", 4 / 3), ("21:9", 21 / 9)):
        if abs(r - val) / val < 0.02:
            return name
    return "%d:%d" % (w, h)


def log(msg: str) -> None:
    sys.stderr.write("[bench %s] %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stderr.flush()

def wait_for_round(run: str, poll_s: float = 30.0) -> None:
    """Block while any run_matrix process is still working on `run` (several processes may share a round)."""
    import shutil as _sh
    import subprocess as _sp
    import time as _t
    if not _sh.which("pgrep"):
        return
    said = False
    while _sp.run(["pgrep", "-f", "run_matrix.py --run %s " % run], capture_output=True).returncode == 0:
        if not said:
            log("waiting for run_matrix on %s to finish before scoring" % run)
            said = True
        _t.sleep(poll_s)

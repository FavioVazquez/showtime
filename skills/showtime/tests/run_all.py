#!/usr/bin/env python3
"""Run every showtime smoke test (tests/test_*.py) and summarise.

Each test file is a standalone script (exit code 0 = pass) that accepts --fast. Files run with the
showtime environment (PYTHONPATH, SHOWTIME_*, HF_HOME, PLAYWRIGHT_BROWSERS_PATH ...) and the venv
Python when present.

-j N runs N test files (or parts of files, see below) at once, each in its own process (default auto, see
below; -j 1 runs whole files one after another with their output streamed live). Every file gets its own working
folder and its own TMPDIR/TEMP/TMP, so browser profiles, servers' scratch files and temp renders never
meet; the read-only runtime (~/.showtime models, library, node, venv) is shared, and the shared caches
under ~/.showtime/cache are written atomically (common.part_path + os.replace, common.cache_lock).
Servers bind free ports (port 0, or the next free port after a preferred one). Heavy files start first
(longest processing time first, from the timings of the previous run kept in ~/.showtime/cache).
Files in SERIAL run alone after the parallel batch. In parallel mode a file's output is captured and a
failing file's output is printed in full at the end.

--shard I/N runs only the I-th of N parts of the (filtered) file list, for CI jobs that split the suite
across machines. The split depends only on the file names and SHARD_WEIGHTS below (fast-suite seconds
from a CI run, never this machine's timing cache), so every machine computes the same parts: each file
lands in exactly one part, and the parts are balanced by weight (longest first, into the lightest part).

-j auto sizes itself to the machine: min(files, cores / 2, 8) up to 16 cores (as before), and on bigger
machines up to cores / 2 (at most BIG_MAX_AUTO_JOBS), fewer when free memory is short (MEM_PER_JOB_GB each).
There, each test's CPU threads (SHOWTIME_THREADS, when not set) are sized to its share of the machine.

Long files split into parts on machines with many cores (tests/_split.py: which files, which tests must share
a process): a part is its own process with its own TMPDIR and scratch folder, running a subset of the file's
tests through tests/_part.py (tests the plan does not know run in the first part, so a split never drops a
test). Only from SPLIT_MIN_JOBS (9) processes at once up, and a file splits only when it would otherwise be
the longest job (its time over the suite's time / -j); files in SERIAL never split and still run alone.
--no-split turns it off.

--changed [REF] runs only the test files the changes since REF can affect (default: the merge-base with the
v0.2.0 branch, else main; plus uncommitted and untracked files). tests/_impact.py decides from what each test
really used in earlier runs (recorded while tests run: tests/_trace/, ~/.showtime/cache/test-impact.json),
a static scan of imports, paths and CLI commands, and a small override table; a file it cannot place runs
everything and says which file. --explain prints why each file was picked (and the split plan). In CI, fetch
the base first (actions/checkout with fetch-depth: 0, or git fetch origin main) and run
`run_all.py --fast --changed origin/main`; CI keeps no recorded runs, so it uses the static scan (broader).
Recording is on by default except in CI (the CI environment variable); --no-trace / --trace override it.

usage: python tests/run_all.py [--fast] [-j N|auto] [-k NAME [-k NAME ...]] [--shard I/N] [--list] [--json]
                               [--timeout S] [--changed [REF]] [--explain] [--no-split] [--no-trace|--trace]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = TESTS_DIR.parent
PLUGIN_ROOT = SKILL_DIR.parent.parent
sys.path.insert(0, str(SKILL_DIR / "lib"))
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

from st import platform as plat  # noqa: E402
from st.common import cache_lock  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

import _impact  # noqa: E402
import _split  # noqa: E402

PART_RUNNER = TESTS_DIR / "_part.py"

# Test files that must not run while another test file runs, with the reason. They run one after
# another once the parallel batch is done. Every file isolates its temp/scratch folders, binds free
# ports and writes the shared caches atomically, so only timing-sensitive files belong here. Add a file
# here (with its reason) rather than letting it flake under -j.
SERIAL: dict = {
    "test_export.py": "its HTML player checks watch playback in real time (frames drawn, picture against the "
                      "sound clock); on a 4-core CI runner another file's Chrome starves them",
    "test_delight.py": "its real `showtime --help` runs on a pseudo-terminal, and a sandbox with few pty devices "
                       "ran out of them (\"out of pty devices\") while other files held theirs; about a second alone",
}

MAX_AUTO_JOBS = 8
# machines with more cores than this may run more than MAX_AUTO_JOBS at once (up to cores / 2, at most
# BIG_MAX_AUTO_JOBS, and MEM_PER_JOB_GB of free memory each: a test runs Chrome, ffmpeg or a speech model)
BIG_MACHINE_CPUS = 16
# long files split into parts only when this many processes run at once (a bigger machine than a laptop or
# a CI runner, which keep running whole files as before)
SPLIT_MIN_JOBS = MAX_AUTO_JOBS + 1
BIG_MAX_AUTO_JOBS = 48
MEM_PER_JOB_GB = 2.5

# Seconds per file in the fast suite (the slowest of Ubuntu, Windows and macOS arm64 on 2-core GitHub
# runners, September 2026). Used only to balance --shard parts, so they need to be roughly right, not
# current; a file missing here weighs SHARD_DEFAULT_WEIGHT, and a file in SERIAL counts double (it runs
# alone, while the others share the machine).
SHARD_WEIGHTS = {
    "test_render.py": 363, "test_motion.py": 308, "test_export.py": 294, "test_capture.py": 198,
    "test_audio.py": 185, "test_footage.py": 133, "test_qa.py": 131, "test_voice.py": 102,
    "test_foundation.py": 35, "test_job.py": 34, "test_mcp.py": 26, "test_studio.py": 26,
    "test_manim.py": 4, "test_skill_structure.py": 3, "test_doc.py": 3, "test_delight.py": 1,
    "test_film.py": 1, "test_caption_cards.py": 1, "test_runtime.py": 1, "test_chart_labels.py": 1,
    "test_run_all.py": 5, "test_preview_server.py": 3, "test_packages.py": 8, "test_hosts.py": 4,
}
SHARD_DEFAULT_WEIGHT = 60


def discover(pattern="") -> list:
    tests = sorted(TESTS_DIR.glob("test_*.py"))
    # foundation first: every other module depends on it
    tests.sort(key=lambda p: (p.stem != "test_foundation", p.stem))
    pats = [pattern] if isinstance(pattern, str) else list(pattern or [""])
    pats = [p.lower() for p in pats] or [""]
    return [t for t in tests if any(p in t.stem.lower() for p in pats)]


def tree_top(dirs) -> set:
    """Top-level entries of the plugin root and the skill folder: a test must never add any."""
    out = set()
    for d in dirs:
        try:
            out.update(str(p) for p in d.iterdir())
        except OSError:
            pass
    return out


# Top-level folders and files that belong to the repository (they are in git's file list). One that
# appears while a test runs (another checkout step, a contributor creating benchmarks/) is not a stray.
LEGIT_TOP = {
    PLUGIN_ROOT: {".claude-plugin", ".git", ".gitattributes", ".github", ".gitignore", ".out-of-scope",
                  "CHANGELOG.md", "CONTEXT.md", "CONTRIBUTING.md", "LICENSE", "README.md", "agents", "assets",
                  "benchmarks", "examples", "hooks", "monitors", "scripts", "skills", "plugin.json", "mcp.json",
                  "mcp_config.json", "gemini-extension.json", "com.github.copilot"},
    SKILL_DIR: {"SKILL.md", "bin", "lib", "mcp", "references", "runtime", "scripts", "setup", "templates", "tests"},
}
# caches that tools (not tests) create and .gitignore already covers
CACHE_NAMES = {"__pycache__", ".ruff_cache", ".pytest_cache", ".mypy_cache", ".DS_Store", "Thumbs.db"}


def git_top_level(root: Path) -> set:
    """Top-level names in git's file list (tracked + untracked, not ignored); empty without git."""
    exe = shutil.which("git")
    if not exe or not (root / ".git").exists():
        return set()
    try:
        cp = subprocess.run([exe, "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard"],
                            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return set()
    if cp.returncode != 0:
        return set()
    return {line.split("/", 1)[0] for line in cp.stdout.splitlines() if line.strip()}


def legit_entries() -> set:
    """Absolute paths of top-level entries a test run may see appear without it being a stray."""
    names = {PLUGIN_ROOT: set(LEGIT_TOP[PLUGIN_ROOT]) | git_top_level(PLUGIN_ROOT),
             SKILL_DIR: set(LEGIT_TOP[SKILL_DIR])}
    out = set()
    for d, ns in names.items():
        out.update(str(d / n) for n in ns | CACHE_NAMES)
    return out


def strays(before: set, after: set, legit: set) -> list:
    """Entries that appeared during a test and are not part of the repository."""
    return sorted(p for p in after - before if p not in legit)


# ------------------------------------------------------------------ parallel scheduling

def available_memory_gb():
    """Free (available) memory in GB, or None when it cannot be read. Stdlib only: /proc/meminfo on Linux,
    vm_stat on macOS, GlobalMemoryStatusEx on Windows."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", encoding="ascii") as fh:
                info = dict(line.split(":", 1) for line in fh if ":" in line)
            kb = info.get("MemAvailable") or info.get("MemFree")
            return int(kb.split()[0]) / 1048576.0 if kb else None
        if sys.platform == "darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            page = 4096
            first = out.splitlines()[0] if out else ""
            if "page size of" in first:
                page = int(first.split("page size of")[1].split()[0])
            pages = 0
            for line in out.splitlines():
                key = line.split(":")[0].strip()
                if key in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"):
                    pages += int(line.split(":")[1].strip().rstrip("."))
            return pages * page / 1073741824.0 if pages else None
        if os.name == "nt":
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MemStatus()
            st.dwLength = ctypes.sizeof(MemStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):  # type: ignore[attr-defined]
                return st.ullAvailPhys / 1073741824.0
            return None
        pages = os.sysconf("SC_AVPHYS_PAGES")
        return pages * os.sysconf("SC_PAGE_SIZE") / 1073741824.0
    except (OSError, ValueError, IndexError, AttributeError, subprocess.SubprocessError):
        return None


def machine_jobs(cpus: int = None, mem_gb="auto") -> int:
    """Processes at once for -j auto. Up to BIG_MACHINE_CPUS cores: half the cores, at most MAX_AUTO_JOBS
    (unchanged: laptops, CI runners). Bigger machines: half the cores, at most BIG_MAX_AUTO_JOBS and
    MEM_PER_JOB_GB of free memory per process (never fewer than the small-machine rule gives)."""
    cpus = cpus or plat.cpu_count()
    small = max(1, min(cpus // 2, MAX_AUTO_JOBS))
    if cpus <= BIG_MACHINE_CPUS:
        return small
    n = min(cpus // 2, BIG_MAX_AUTO_JOBS)
    mem = available_memory_gb() if mem_gb == "auto" else mem_gb
    if mem:
        n = min(n, int(mem // MEM_PER_JOB_GB))
    return max(small, n)


def auto_jobs(n_files: int) -> int:
    """Files at once by default: machine_jobs() (half the cores: a test file often runs several processes:
    ffmpeg, Chrome, ASR threads), never more than there are files."""
    return max(1, min(n_files, machine_jobs()))


def thread_share(jobs: int, cpus: int = None):
    """SHOWTIME_THREADS for each test on a big machine running many at once (speech and ASR models use every
    core by default), or None where the default is fine."""
    cpus = cpus or plat.cpu_count()
    if cpus <= BIG_MACHINE_CPUS or jobs <= MAX_AUTO_JOBS:
        return None
    return max(4, (2 * cpus) // jobs)


def parse_jobs(v: str) -> int:
    """0 = auto; else a positive int."""
    if str(v).strip().lower() in ("auto", "0", ""):
        return 0
    try:
        n = int(v)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a number or 'auto', got %r" % v)
    if n < 1:
        raise argparse.ArgumentTypeError("-j must be at least 1")
    return n


def parse_shard(v: str) -> tuple:
    """'I/N' (1 <= I <= N) -> (I, N)."""
    try:
        i, n = (int(x) for x in str(v).split("/"))
    except ValueError:
        raise argparse.ArgumentTypeError("expected I/N, for example 1/3; got %r" % v)
    if n < 1 or not 1 <= i <= n:
        raise argparse.ArgumentTypeError("--shard %s: I must be between 1 and N" % v)
    return i, n


def shard_parts(names: list, n: int, weights: dict = None) -> list:
    """Split file names into n parts: heaviest first, each into the currently lightest part (ties: the
    lower-numbered part). Deterministic: depends only on the names and the weights."""
    if weights is None:
        weights = {k: v * (2 if k in SERIAL else 1) for k, v in SHARD_WEIGHTS.items()}
        weights.update({k: 2 * SHARD_DEFAULT_WEIGHT for k in SERIAL if k not in SHARD_WEIGHTS})
    w = lambda name: float(weights.get(name, SHARD_DEFAULT_WEIGHT))  # noqa: E731
    parts, loads = [[] for _ in range(n)], [0.0] * n
    for name in sorted(set(names), key=lambda x: (-w(x), x)):
        k = min(range(n), key=lambda j: (loads[j], j))
        parts[k].append(name)
        loads[k] += w(name)
    return parts


def select_shard(tests: list, shard: tuple) -> list:
    """The tests (Paths) of shard (i, n), in their original order."""
    i, n = shard
    mine = set(shard_parts([t.name for t in tests], n)[i - 1])
    return [t for t in tests if t.name in mine]


def times_file() -> Path:
    return showtime_home() / "cache" / "test-times.json"


def load_times() -> dict:
    try:
        d = json.loads(times_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_times(mode: str, results: list) -> None:
    """Remember each file's seconds (and each test's, when recorded) for the next run's ordering and split
    plan (atomic: a concurrent run may read it; locked: runs from several checkouts share the file). A file
    run in parts counts the sum of its parts."""
    p = times_file()
    with cache_lock(p, timeout=30, stale=120):
        _save_times(p, mode, results)


def _save_times(p: Path, mode: str, results: list) -> None:
    d = load_times()
    by_file: dict = {}
    for r in results:
        by_file.setdefault(r.get("file", r["test"]), []).append(r)
        for tid, sec in (r.get("test_times") or {}).items():
            d["%s:%s::%s" % (mode, r.get("file", r["test"]), tid)] = sec
    for name, rs in by_file.items():
        if all(r["returncode"] != 124 and r["returncode"] != 130 for r in rs):  # a timeout says nothing about the length
            d["%s:%s" % (mode, name)] = round(sum(r["seconds"] for r in rs), 1)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(".%s.%d.part" % (p.name, os.getpid()))
        tmp.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(p))
    except OSError:
        pass


def lpt_order(tests: list, mode: str, times: dict) -> list:
    """Longest processing time first. A file with no timing yet counts as the longest (starts early)."""
    def est(t):
        v = times.get("%s:%s" % (mode, t.name))
        return float(v) if isinstance(v, (int, float)) else float("inf")
    return sorted(tests, key=lambda t: (-est(t), t.name))


# ------------------------------------------------------------------ work items (whole files and parts)

def trace_file() -> Path:
    return showtime_home() / "cache" / "test-impact.json"


def scan_cache_file() -> Path:
    return showtime_home() / "cache" / "test-impact-scan.json"


def file_seconds(name: str, mode: str, times: dict) -> float:
    """Expected seconds of a whole file: the last run here, else the CI weights, else the default."""
    v = times.get("%s:%s" % (mode, name))
    if isinstance(v, (int, float)):
        return float(v)
    return float(SHARD_WEIGHTS.get(name, SHARD_DEFAULT_WEIGHT))


def whole(t: Path, est=None, wrap=False) -> dict:
    return {"path": t, "file": t.name, "label": t.name, "part": None, "ids": None, "known": None,
            "catch_all": False, "wrap": wrap, "est": est}


def plan_items(tests: list, jobs: int, mode: str, times: dict, split: bool = True, record: bool = False,
               explain: list = None) -> list:
    """Work items for the parallel phase: whole files, and parts of the long files in _split.SPLIT.

    Only with SPLIT_MIN_JOBS or more jobs. A file splits when its expected time is over the target part
    length: max(the suite's time / jobs,
    the longest job that cannot split, MIN_PART_SECONDS); it gets enough parts to come under it (at most
    its MAX_PARTS, at most one per group of tests that must share a process). Files in SERIAL never split.
    record: run the SPLIT files through tests/_part.py even whole, to record each test's time."""
    items = []
    est = {t.name: file_seconds(t.name, mode, times) for t in tests}
    known = {t.name: isinstance(times.get("%s:%s" % (mode, t.name)), (int, float)) for t in tests}
    cands = {}
    if split and jobs >= SPLIT_MIN_JOBS:
        for t in tests:
            if t.name in _split.SPLIT and t.name not in SERIAL:
                try:
                    ft = _split.file_tests(t)
                except (OSError, SyntaxError, ValueError):
                    continue
                units = ft.units()
                if len(units) >= 2:
                    cands[t.name] = (ft, units, _split.test_weights(ft, est[t.name], times, mode))
    target = 0.0
    if cands:
        par = [t for t in tests if t.name not in SERIAL]
        total = sum(est[t.name] for t in par)
        # a whole file bounds the part length only when its time is known (a new file's default guess does not)
        fixed = [est[t.name] for t in par if t.name not in cands
                 and (known[t.name] or t.name in SHARD_WEIGHTS)]
        unit_max = [sum(w[i] for i in u) for ft, units, w in cands.values() for u in units]
        target = max([_split.MIN_PART_SECONDS, total / max(1, jobs)] + fixed + unit_max)
    for t in tests:
        n = 1
        if t.name in cands:
            ft, units, w = cands[t.name]
            n = _split.part_count(est[t.name], target, len(units), _split.MAX_PARTS.get(t.name, _split.DEFAULT_MAX_PARTS))
        if n < 2:
            items.append(whole(t, est[t.name] if known[t.name] else None,
                               wrap=record and t.name in _split.SPLIT and t.name not in SERIAL))
            continue
        parts = _split.assign(units, w, n)
        n = len(parts)
        for k, ids in enumerate(parts):
            items.append({"path": t, "file": t.name, "label": "%s[%d/%d]" % (t.name, k + 1, n), "part": (k + 1, n),
                          "ids": ids, "known": ft.ids, "catch_all": k == 0, "wrap": True,
                          "est": round(sum(w[i] for i in ids), 1)})
        if explain is not None:
            explain.append("%s: about %.0fs -> %d parts of about %s s (target %.0fs per job)" % (
                t.name, est[t.name], n, "/".join("%.0f" % sum(w[i] for i in ids) for ids in parts), target))
    return items


def verify_split(items: list, results: list) -> list:
    """[(label, note)] for split files whose parts did not run each planned test exactly once (checked from
    the tests each part recorded; only when every part of the file passed)."""
    out = []
    by_file: dict = {}
    for it in items:
        if it["part"]:
            by_file.setdefault(it["file"], []).append(it)
    res = {r["test"]: r for r in results}
    for name, its in by_file.items():
        rs = [res.get(it["label"]) for it in its]
        if not all(r and r["ok"] for r in rs):
            continue
        seen: dict = {}
        for r in rs:
            for tid in r.get("test_times") or {}:
                seen[tid] = seen.get(tid, 0) + 1
        if not seen:
            continue                       # nothing recorded (a module-level skip): nothing to compare
        planned = set(its[0]["known"] or [])
        missing = sorted(planned - set(seen))
        twice = sorted(t for t, c in seen.items() if c > 1)
        if missing or twice:
            out.append((its[0]["label"], "split plan broke: %s%s" % (
                ("not run: " + ", ".join(missing[:5])) if missing else "",
                ("; run twice: " + ", ".join(twice[:5])) if twice else "")))
    return out


def lpt_items(items: list) -> list:
    """Longest first; an item with no estimate yet counts as the longest (starts early)."""
    return sorted(items, key=lambda it: (-(it["est"] if it["est"] is not None else float("inf")), it["label"]))


def popen_group_kwargs() -> dict:
    """Start a test in its own process group so a timeout or Ctrl-C can stop everything it started."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)}
    return {"start_new_session": True}


def kill_tree(p: subprocess.Popen) -> None:
    if p.poll() is not None and os.name == "nt":
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
        else:
            os.killpg(p.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        p.kill()
    except OSError:
        pass


class Runner:
    def __init__(self, py: str, env: dict, args, legit: set, n_total: int, capture: bool, trace: bool = False,
                 trace_node: bool = True):
        self.py, self.env, self.args, self.legit = py, env, args, legit
        self.n_total, self.capture, self.trace, self.trace_node = n_total, capture, trace, trace_node
        self.lock = threading.Lock()
        self.running: dict = {}      # label -> Popen
        self.done = 0
        self.stopping = False
        self.seen = tree_top((PLUGIN_ROOT, SKILL_DIR))

    def run(self, item) -> dict:
        if isinstance(item, Path):
            item = whole(item)
        t, label = item["path"], item["label"]
        base = {"test": label, "file": item["file"], "part": ("%d/%d" % item["part"]) if item["part"] else None}
        if self.stopping:
            return dict(base, ok=False, returncode=130, seconds=0.0, note="not run (interrupted)", output="")
        fast = ["--fast"] if self.args.fast else []
        cmd = ([self.py, str(PART_RUNNER), str(t)] if item["wrap"] else [self.py, str(t)]) + fast
        if not self.capture:
            print("=== %s%s" % (label, " (--fast)" if self.args.fast else ""), file=sys.stderr, flush=True)
        # each file (or part) runs in a fresh folder: outputs that default to ./showtime-out never land in the
        # repository, and its own temp folder (short name: macOS unix-socket paths are limited to 104 bytes)
        run_dir = Path(tempfile.mkdtemp(prefix="st-%s-" % t.stem[5:][:12]))
        scratch, tmp = run_dir / "cwd", run_dir / "t"
        scratch.mkdir()
        tmp.mkdir()
        env = dict(self.env, TMPDIR=str(tmp), TEMP=str(tmp), TMP=str(tmp))
        times_out = run_dir / "times.json"
        if item["wrap"]:
            env["ST_TEST_TIMES"] = str(times_out)
        if item["ids"] is not None:
            plan = run_dir / "plan.json"
            plan.write_text(json.dumps({"ids": item["ids"], "known": item["known"], "catch_all": item["catch_all"]}),
                            encoding="utf-8")
            env["ST_TEST_PLAN"] = str(plan)
        trace_dir = run_dir / "trace"
        if self.trace:
            env = _impact.trace_env(env, trace_dir, node=self.trace_node)
        log = run_dir / "output.log"
        t0 = time.time()
        rc, note, output, test_times, used = 0, "", "", {}, None
        try:
            with open(log, "wb") as fh:
                out = {"stdout": fh, "stderr": subprocess.STDOUT} if self.capture else {}
                if self.capture:
                    out["stdin"] = subprocess.DEVNULL
                p = subprocess.Popen(cmd, env=env, cwd=scratch, **out, **popen_group_kwargs())
                with self.lock:
                    self.running[label] = p
                try:
                    rc = p.wait(timeout=self.args.timeout)
                except subprocess.TimeoutExpired:
                    kill_tree(p)
                    p.wait()
                    rc, note = 124, "timed out after %.0fs" % self.args.timeout
                finally:
                    with self.lock:
                        self.running.pop(label, None)
            if self.capture:
                output = log.read_text(encoding="utf-8", errors="replace")
            try:
                test_times = json.loads(times_out.read_text(encoding="utf-8")) if item["wrap"] else {}
            except (OSError, ValueError):
                test_times = {}
            if self.trace and rc == 0:
                used = sorted(_impact.read_trace(trace_dir))
        finally:
            shutil.rmtree(str(run_dir), ignore_errors=True)
        if self.stopping and rc != 0:
            note = note or "interrupted"
        dt = time.time() - t0
        with self.lock:
            now = tree_top((PLUGIN_ROOT, SKILL_DIR))
            stray = strays(self.seen, now, self.legit)
            self.seen = now
            others = sorted(self.running)
            self.done += 1
            n = self.done
        if stray:
            rc = rc or 1
            note = (note + "; " if note else "") + "wrote into the repository: " + ", ".join(stray[:5])
            if others:
                note += " (files running at the same time: %s)" % ", ".join(others)
        res = dict(base, ok=rc == 0, returncode=rc, seconds=round(dt, 1), note=note, output=output,
                   test_times=test_times, used=used if rc == 0 else None)
        if self.capture:
            print("[%*d/%d] %s %-28s %7.1fs %s" % (len(str(self.n_total)), n, self.n_total,
                                                   "PASS" if rc == 0 else "FAIL", label, dt,
                                                   ("rc=%d %s" % (rc, note)).strip() if rc else note),
                  file=sys.stderr, flush=True)
        else:
            print("=== %s %s in %.1fs %s" % (label, "PASS" if rc == 0 else "FAIL (rc=%d)" % rc, dt, note),
                  file=sys.stderr, flush=True)
        return res

    def stop_all(self) -> None:
        self.stopping = True
        with self.lock:
            procs = list(self.running.values())
        for p in procs:
            kill_tree(p)


def trace_default() -> bool:
    """Record what each test uses (for --changed) unless this is a CI job (nothing is kept there)."""
    v = os.environ.get("ST_TEST_TRACE")
    if v is not None:
        return v.strip().lower() not in ("0", "no", "false", "off", "")
    return os.environ.get("CI", "").strip().lower() in ("", "0", "false", "no")


def save_used(mode: str, results: list) -> None:
    """Add what each file used to the trace store, for files whose every part passed."""
    by_file: dict = {}
    for r in results:
        by_file.setdefault(r["file"], []).append(r)
    new = {}
    for name, rs in by_file.items():
        if rs and all(r["ok"] and r.get("used") is not None for r in rs):
            new["%s:%s" % (mode, name)] = {f for r in rs for f in r["used"]}
    if new:
        with cache_lock(trace_file(), timeout=30, stale=120):
            _impact.save_traces(trace_file(), new)


def changed_selection(args, tests: list, mode: str):
    """-> (tests to run, summary dict) for --changed; exits via SystemExit(2) on a git problem."""
    t0 = time.time()
    try:
        changed, deleted, desc = _impact.changed_files(args.changed or None)
    except RuntimeError as e:
        print("error: --changed: %s" % e, file=sys.stderr)
        raise SystemExit(2)
    imap = _impact.ImpactMap(_impact.repo_files(), cache=scan_cache_file())
    sel = _impact.select([t.name for t in tests], changed, deleted, imap, _impact.load_traces(trace_file()), mode)
    took = time.time() - t0
    n_all = len(tests)
    if sel["all"]:
        picked = tests
    else:
        picked = [t for t in tests if t.name in sel["tests"]]
    print("changed since %s: %d file(s)%s -> %s (impact map %.1fs)" % (
        desc, len(changed) + len(deleted), (", %d deleted" % len(deleted)) if deleted else "",
        ("every test file (%d)" % n_all) if sel["all"] else "%d of %d test files: %s" % (
            len(picked), n_all, ", ".join(t.name for t in picked) or "none"), took), file=sys.stderr, flush=True)
    for f, why in sel["unplaced"][:10]:
        print("  runs everything: %s (%s)" % (f, why), file=sys.stderr)
    if args.explain:
        for f in changed + deleted:
            print("  changed: %s%s" % (f, " (deleted)" if f in deleted else ""), file=sys.stderr)
        for line in _impact.explain_lines(sel):
            print("  " + line, file=sys.stderr)
        for note in sel["notes"]:
            print("  note: " + note, file=sys.stderr)
    summary = {"base": desc, "changed": changed, "deleted": deleted, "all": sel["all"],
               "unplaced": [f for f, _ in sel["unplaced"]], "tests": sorted(t.name for t in picked),
               "seconds": round(took, 2)}
    return picked, summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run showtime smoke tests (tests/test_*.py).")
    ap.add_argument("--fast", action="store_true", help="pass --fast to every test (CI mode)")
    ap.add_argument("-j", "--jobs", type=parse_jobs, default=0, metavar="N",
                    help="processes at once (default auto: min(files, cores/2, %d) up to %d cores, up to cores/2 "
                         "on bigger machines; 1 = whole files one after another, output streamed live)"
                         % (MAX_AUTO_JOBS, BIG_MACHINE_CPUS))
    ap.add_argument("-k", dest="pattern", action="append", default=[],
                    help="only tests whose name contains this (repeatable: any of them)")
    ap.add_argument("--changed", nargs="?", const="", default=None, metavar="REF",
                    help="only the test files the changes since REF can affect (default: merge-base with %s; "
                         "uncommitted and untracked files count)" % " / ".join(_impact.BASE_REFS[::2]))
    ap.add_argument("--explain", action="store_true",
                    help="say why each file was picked (--changed) and how long files are split")
    ap.add_argument("--no-split", action="store_true", help="run every file whole (no parts)")
    ap.add_argument("--no-trace", dest="trace", action="store_false", default=None,
                    help="do not record which repository files each test uses (default: record, except in CI)")
    ap.add_argument("--trace", dest="trace", action="store_true", help="record them even in CI")
    ap.add_argument("--shard", type=parse_shard, metavar="I/N",
                    help="run only part I of N (a stable, weight-balanced split of the files; CI runs 1/3, 2/3, 3/3)")
    ap.add_argument("--list", action="store_true", help="list tests and exit")
    ap.add_argument("--json", action="store_true", help="print a JSON summary on stdout")
    ap.add_argument("--timeout", type=float, default=900, help="seconds per test file or part (default 900)")
    ap.add_argument("--python", help="interpreter for the tests (default: showtime venv, else this one)")
    args = ap.parse_args(argv)

    mode = "fast" if args.fast else "full"
    tests = discover(args.pattern)
    changed_info = None
    if args.changed is not None and tests:
        tests, changed_info = changed_selection(args, tests, mode)
        if not tests:
            print("nothing to run", file=sys.stderr)
            if args.json:
                print(json.dumps({"ok": True, "passed": 0, "failed": 0, "results": [], "changed": changed_info},
                                 indent=2))
            return 0
    if args.shard and tests:
        tests = select_shard(tests, args.shard)
        print("shard %d/%d: %s" % (args.shard[0], args.shard[1], ", ".join(t.name for t in tests) or "(no files)"),
              file=sys.stderr, flush=True)
        if not tests:   # more parts than files: an empty part passes
            return 0
    if not tests and not args.list:
        print("no tests matched", file=sys.stderr)
        return 1
    trace = trace_default() if args.trace is None else args.trace
    times = load_times()
    cap = args.jobs or machine_jobs()
    plan_notes: list = []
    parallel_files = [t for t in tests if t.name not in SERIAL]
    serial = [t for t in tests if t.name in SERIAL]
    items = plan_items(parallel_files, cap, mode, times, split=not args.no_split, record=trace,
                       explain=plan_notes) if cap > 1 else [whole(t) for t in tests]
    if args.list:
        for t in tests:
            print(t.name + ("   (serial: %s)" % SERIAL[t.name] if t.name in SERIAL else ""))
        if args.explain and cap > 1:
            print("\nat -j %d: %d processes%s" % (cap, len(items) + len(serial),
                                                  "" if plan_notes else " (no file splits)"))
            for line in plan_notes:
                print("  " + line)
        return 0
    home = showtime_home()
    env = build_env(home)
    vpy = plat.venv_python(home / "venv")
    py = args.python or (str(vpy) if vpy.exists() else sys.executable)
    jobs = min(cap, max(1, len(items)))
    threads = thread_share(jobs)
    if threads and not os.environ.get("SHOWTIME_THREADS"):
        env["SHOWTIME_THREADS"] = str(threads)
    if jobs > 1:
        items = lpt_items(items)
        n_parts = sum(1 for it in items if it["part"])
        print("running %d test files%s, %d at a time%s%s" % (
            len(tests), (" as %d processes (%d parts of split files)" % (len(items) + len(serial), n_parts))
            if n_parts else "", jobs, " (--fast)" if args.fast else "",
            ("; then alone: " + ", ".join(t.name for t in serial)) if serial else ""), file=sys.stderr, flush=True)
        if args.explain:
            for line in plan_notes:
                print("  split: " + line, file=sys.stderr)
    else:
        items, serial = [whole(t) for t in tests], []
    trace_node = trace and _impact.node_can_trace(env.get("SHOWTIME_NODE") or plat.find_tool("node", env.get("PATH")))
    runner = Runner(py, env, args, legit_entries(), len(items) + len(serial), capture=jobs > 1, trace=trace,
                    trace_node=trace_node)
    results = []
    t_all = time.time()
    try:
        if jobs > 1:
            with ThreadPoolExecutor(max_workers=jobs) as ex:
                futs = [ex.submit(runner.run, it) for it in items]   # submission order = start order (LPT)
                try:
                    while not all(f.done() for f in futs):
                        time.sleep(0.2)
                except KeyboardInterrupt:
                    runner.stop_all()
                    raise
                results += [f.result() for f in futs]
            for t in serial:
                results.append(runner.run(whole(t)))
        else:
            for it in items:
                results.append(runner.run(it))
    except KeyboardInterrupt:
        runner.stop_all()
        print("\ninterrupted", file=sys.stderr)
        return 130
    wall = time.time() - t_all
    for label, note in verify_split(items, results):
        for r in results:
            if r["test"] == label:
                r.update(ok=False, returncode=r["returncode"] or 1, note=(r["note"] + "; " if r["note"] else "") + note)
    save_times(mode, results)
    if trace:
        save_used(mode, results)
    order = {t.name: i for i, t in enumerate(tests)}
    results.sort(key=lambda r: (order[r["file"]], r["test"]))
    failed = [r for r in results if not r["ok"]]
    failed_files = sorted({r["file"] for r in failed}, key=lambda n: order[n])
    busy = sum(r["seconds"] for r in results)
    summary = {"ok": not failed, "passed": len(tests) - len(failed_files), "failed": len(failed_files),
               "seconds": round(wall, 1), "sum_seconds": round(busy, 1), "jobs": jobs, "python": py,
               "platform": plat.platform_key(), "shard": ("%d/%d" % args.shard) if args.shard else None,
               "processes": len(results), "serial": {t.name: SERIAL[t.name] for t in serial},
               "results": [{k: v for k, v in r.items() if k not in ("output", "test_times", "used")} for r in results]}
    if changed_info is not None:
        summary["changed"] = changed_info
    if jobs > 1:
        for r in failed:
            print("\n" + "=" * 30 + " %s FAIL (rc=%d) %s " % (r["test"], r["returncode"], r["note"]) + "=" * 30,
                  file=sys.stderr)
            print(r["output"].rstrip() or "(no output)", file=sys.stderr)
        print("\n%-30s %6s %9s" % ("test file", "result", "seconds"), file=sys.stderr)
        for r in results:
            print("%-30s %6s %9.1f%s" % (r["test"], "PASS" if r["ok"] else "FAIL", r["seconds"],
                                          ("  " + r["note"]) if r["note"] else ""), file=sys.stderr)
    if args.json:
        print(json.dumps(summary, indent=2))
    print("\n%d/%d test files passed in %.1fs wall%s%s" % (
        summary["passed"], len(tests), wall,
        (" (%d at a time%s; %.1fs summed over processes, %.1fx)" % (
            jobs, (", %d processes" % len(results)) if len(results) != len(tests) else "", busy,
            busy / wall if wall else 0)) if jobs > 1 else "",
        ("; failed: " + ", ".join(failed_files)) if failed else ""), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

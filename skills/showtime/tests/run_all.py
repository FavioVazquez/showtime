#!/usr/bin/env python3
"""Run every showtime smoke test (tests/test_*.py) and summarise.

Each test file is a standalone script (exit code 0 = pass) that accepts --fast. Files run with the
showtime environment (PYTHONPATH, SHOWTIME_*, HF_HOME, PLAYWRIGHT_BROWSERS_PATH ...) and the venv
Python when present.

-j N runs N whole test files at once, each in its own process (default auto = min(files, cores / 2, 8);
-j 1 runs them one after another with their output streamed live). Every file gets its own working
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

usage: python tests/run_all.py [--fast] [-j N|auto] [-k NAME [-k NAME ...]] [--shard I/N] [--list] [--json]
                               [--timeout S]
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

from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

# Test files that must not run while another test file runs, with the reason. They run one after
# another once the parallel batch is done. Empty today: every file isolates its temp/scratch folders,
# binds free ports and writes the shared caches atomically. Add a file here (with its reason) rather
# than letting it flake under -j.
SERIAL: dict = {}

MAX_AUTO_JOBS = 8

# Seconds per file in the fast suite (the slowest of Ubuntu, Windows and macOS arm64 on 2-core GitHub
# runners, September 2026). Used only to balance --shard parts, so they need to be roughly right, not
# current; a file missing here weighs SHARD_DEFAULT_WEIGHT.
SHARD_WEIGHTS = {
    "test_render.py": 363, "test_motion.py": 308, "test_export.py": 294, "test_capture.py": 198,
    "test_audio.py": 185, "test_footage.py": 133, "test_qa.py": 131, "test_voice.py": 102,
    "test_foundation.py": 35, "test_job.py": 34, "test_mcp.py": 26, "test_studio.py": 26,
    "test_manim.py": 4, "test_skill_structure.py": 3, "test_doc.py": 3, "test_delight.py": 1,
    "test_film.py": 1, "test_caption_cards.py": 1, "test_runtime.py": 1, "test_chart_labels.py": 1,
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
                  "benchmarks", "examples", "monitors", "scripts", "skills"},
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

def auto_jobs(n_files: int) -> int:
    """Files at once by default: half the cores (a test file often runs several processes: ffmpeg,
    Chrome, ASR threads), at most MAX_AUTO_JOBS, never more than there are files."""
    return max(1, min(n_files, plat.cpu_count() // 2, MAX_AUTO_JOBS))


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
    weights = SHARD_WEIGHTS if weights is None else weights
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
    """Remember each file's seconds for the next run's ordering (atomic: a concurrent run may read it)."""
    p = times_file()
    d = load_times()
    for r in results:
        if r["returncode"] != 124:  # a timeout says nothing about the real length
            d["%s:%s" % (mode, r["test"])] = r["seconds"]
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
    def __init__(self, py: str, env: dict, args, legit: set, n_total: int, capture: bool):
        self.py, self.env, self.args, self.legit = py, env, args, legit
        self.n_total, self.capture = n_total, capture
        self.lock = threading.Lock()
        self.running: dict = {}      # name -> Popen
        self.done = 0
        self.stopping = False
        self.seen = tree_top((PLUGIN_ROOT, SKILL_DIR))

    def run(self, t: Path) -> dict:
        if self.stopping:
            return {"test": t.name, "ok": False, "returncode": 130, "seconds": 0.0, "note": "not run (interrupted)",
                    "output": ""}
        cmd = [self.py, str(t)] + (["--fast"] if self.args.fast else [])
        if not self.capture:
            print("=== %s%s" % (t.name, " (--fast)" if self.args.fast else ""), file=sys.stderr, flush=True)
        # each file runs in a fresh folder: outputs that default to ./showtime-out never land in the repo,
        # and its own temp folder (short name: macOS unix-socket paths are limited to 104 bytes)
        run_dir = Path(tempfile.mkdtemp(prefix="st-%s-" % t.stem[5:][:12]))
        scratch, tmp = run_dir / "cwd", run_dir / "t"
        scratch.mkdir()
        tmp.mkdir()
        env = dict(self.env, TMPDIR=str(tmp), TEMP=str(tmp), TMP=str(tmp))
        log = run_dir / "output.log"
        t0 = time.time()
        rc, note, output = 0, "", ""
        try:
            with open(log, "wb") as fh:
                out = {"stdout": fh, "stderr": subprocess.STDOUT} if self.capture else {}
                if self.capture:
                    out["stdin"] = subprocess.DEVNULL
                p = subprocess.Popen(cmd, env=env, cwd=scratch, **out, **popen_group_kwargs())
                with self.lock:
                    self.running[t.name] = p
                try:
                    rc = p.wait(timeout=self.args.timeout)
                except subprocess.TimeoutExpired:
                    kill_tree(p)
                    p.wait()
                    rc, note = 124, "timed out after %.0fs" % self.args.timeout
                finally:
                    with self.lock:
                        self.running.pop(t.name, None)
            if self.capture:
                output = log.read_text(encoding="utf-8", errors="replace")
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
        res = {"test": t.name, "ok": rc == 0, "returncode": rc, "seconds": round(dt, 1), "note": note,
               "output": output}
        if self.capture:
            print("[%*d/%d] %s %-24s %7.1fs %s" % (len(str(self.n_total)), n, self.n_total,
                                                   "PASS" if rc == 0 else "FAIL", t.name, dt,
                                                   ("rc=%d %s" % (rc, note)).strip() if rc else note),
                  file=sys.stderr, flush=True)
        else:
            print("=== %s %s in %.1fs %s" % (t.name, "PASS" if rc == 0 else "FAIL (rc=%d)" % rc, dt, note),
                  file=sys.stderr, flush=True)
        return res

    def stop_all(self) -> None:
        self.stopping = True
        with self.lock:
            procs = list(self.running.values())
        for p in procs:
            kill_tree(p)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run showtime smoke tests (tests/test_*.py).")
    ap.add_argument("--fast", action="store_true", help="pass --fast to every test (CI mode)")
    ap.add_argument("-j", "--jobs", type=parse_jobs, default=0, metavar="N",
                    help="test files at once (default auto = min(files, cores/2, %d); 1 = one after another, "
                         "output streamed live)" % MAX_AUTO_JOBS)
    ap.add_argument("-k", dest="pattern", action="append", default=[],
                    help="only tests whose name contains this (repeatable: any of them)")
    ap.add_argument("--shard", type=parse_shard, metavar="I/N",
                    help="run only part I of N (a stable, weight-balanced split of the files; CI runs 1/3, 2/3, 3/3)")
    ap.add_argument("--list", action="store_true", help="list tests and exit")
    ap.add_argument("--json", action="store_true", help="print a JSON summary on stdout")
    ap.add_argument("--timeout", type=float, default=900, help="seconds per test file (default 900)")
    ap.add_argument("--python", help="interpreter for the tests (default: showtime venv, else this one)")
    args = ap.parse_args(argv)

    tests = discover(args.pattern)
    if args.shard and tests:
        tests = select_shard(tests, args.shard)
        print("shard %d/%d: %s" % (args.shard[0], args.shard[1], ", ".join(t.name for t in tests) or "(no files)"),
              file=sys.stderr, flush=True)
        if not tests:   # more parts than files: an empty part passes
            return 0
    if args.list:
        for t in tests:
            print(t.name + ("   (serial: %s)" % SERIAL[t.name] if t.name in SERIAL else ""))
        return 0
    if not tests:
        print("no tests matched", file=sys.stderr)
        return 1
    home = showtime_home()
    env = build_env(home)
    vpy = plat.venv_python(home / "venv")
    py = args.python or (str(vpy) if vpy.exists() else sys.executable)
    jobs = min(args.jobs or auto_jobs(len(tests)), len(tests))
    mode = "fast" if args.fast else "full"
    parallel = [t for t in tests if t.name not in SERIAL]
    serial = [t for t in tests if t.name in SERIAL]
    if jobs > 1:
        parallel = lpt_order(parallel, mode, load_times())
        print("running %d test files, %d at a time%s%s" % (
            len(tests), jobs, " (--fast)" if args.fast else "",
            ("; then alone: " + ", ".join(t.name for t in serial)) if serial else ""), file=sys.stderr, flush=True)
    else:
        parallel, serial = tests, []
    runner = Runner(py, env, args, legit_entries(), len(tests), capture=jobs > 1)
    results = []
    t_all = time.time()
    try:
        if jobs > 1:
            with ThreadPoolExecutor(max_workers=jobs) as ex:
                futs = [ex.submit(runner.run, t) for t in parallel]   # submission order = start order (LPT)
                try:
                    while not all(f.done() for f in futs):
                        time.sleep(0.2)
                except KeyboardInterrupt:
                    runner.stop_all()
                    raise
                results += [f.result() for f in futs]
        for t in (serial if jobs > 1 else parallel):
            results.append(runner.run(t))
    except KeyboardInterrupt:
        runner.stop_all()
        print("\ninterrupted", file=sys.stderr)
        return 130
    wall = time.time() - t_all
    save_times(mode, results)
    order = {t.name: i for i, t in enumerate(tests)}
    results.sort(key=lambda r: order[r["test"]])
    failed = [r for r in results if not r["ok"]]
    busy = sum(r["seconds"] for r in results)
    summary = {"ok": not failed, "passed": len(results) - len(failed), "failed": len(failed),
               "seconds": round(wall, 1), "sum_seconds": round(busy, 1), "jobs": jobs, "python": py,
               "platform": plat.platform_key(), "shard": ("%d/%d" % args.shard) if args.shard else None,
               "serial": {t.name: SERIAL[t.name] for t in serial},
               "results": [{k: v for k, v in r.items() if k != "output"} for r in results]}
    if jobs > 1:
        for r in failed:
            print("\n" + "=" * 30 + " %s FAIL (rc=%d) %s " % (r["test"], r["returncode"], r["note"]) + "=" * 30,
                  file=sys.stderr)
            print(r["output"].rstrip() or "(no output)", file=sys.stderr)
        print("\n%-26s %6s %9s" % ("test file", "result", "seconds"), file=sys.stderr)
        for r in results:
            print("%-26s %6s %9.1f%s" % (r["test"], "PASS" if r["ok"] else "FAIL", r["seconds"],
                                          ("  " + r["note"]) if r["note"] else ""), file=sys.stderr)
    if args.json:
        print(json.dumps(summary, indent=2))
    print("\n%d/%d test files passed in %.1fs wall%s%s" % (
        summary["passed"], len(results), wall,
        (" (%d at a time; %.1fs summed over files, %.1fx)" % (jobs, busy, busy / wall if wall else 0))
        if jobs > 1 else "",
        ("; failed: " + ", ".join(r["test"] for r in failed)) if failed else ""), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

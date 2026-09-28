#!/usr/bin/env python3
"""Smoke run: one task (T7 logo sting), two arms (baseline, showtime), end to end, short cap.

    python benchmarks/harness/smoke.py                 # real run (needs a headless credential)
    python benchmarks/harness/smoke.py --fake          # harness self-test: stand-in CLI, no model, no cost

Steps: credential check -> arm setup -> isolation audit (what each session loads) -> 2 runs, 2 at once
-> automatic metrics -> fact-check judge -> 3 blind pairwise judges -> 2 ranking judges -> human board
-> report.
Nothing runs in the background after it returns.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def step(title, cmd, env, check=True):
    print("\n== %s\n$ %s" % (title, " ".join(str(c) for c in cmd[1:])), flush=True)
    r = subprocess.run([str(c) for c in cmd], env=env)
    if check and r.returncode != 0:
        raise SystemExit("smoke: step failed: %s (exit %d)" % (title, r.returncode))
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fake", action="store_true", help="use the stand-in CLI (harness self-test)")
    ap.add_argument("--run", default=None)
    ap.add_argument("--cap-min", type=float, default=10.0)
    ap.add_argument("--budget", type=float, default=6.0)
    ap.add_argument("--skip-judges", action="store_true")
    a = ap.parse_args()
    env = dict(os.environ)
    run = a.run or ("selftest" if a.fake else "smoke")
    marker = None
    if a.fake:
        env["BENCH_CLAUDE"] = str(HERE / "selftest" / "fake_claude.py")
        sys.path.insert(0, str(HERE))
        import common
        marker = common.ws_root() / "FAKE_ASK"
        marker.write_text("1\n")  # the stand-in asks once, then delivers
    try:
        return steps(a, env, run)
    finally:
        if marker is not None and marker.exists():
            marker.unlink()  # never leave the stand-in's switch in a workspace root a real round may use


def steps(a, env, run) -> int:
    py = sys.executable
    bench = HERE.parent
    if not a.fake:
        step("headless credential", [py, HERE / "arms.py", "auth"], env)
    step("arm setup", [py, HERE / "arms.py", "setup", "--arms", "baseline,showtime"], env)
    if not a.fake:
        step("isolation audit", [py, HERE / "arms.py", "audit", "--arms", "baseline,showtime"], env)
    step("runs (2 at once)", [py, HERE / "run_matrix.py", "--run", run, "--arms", "baseline,showtime", "--tasks", "t7",
                              "-j", "2", "--cap-min", str(a.cap_min), "--budget", str(a.budget)], env, check=False)
    step("automatic metrics", [py, bench / "scoring" / "auto_metrics.py", "--run", run], env)
    if not a.skip_judges:
        step("fact-check judge", [py, bench / "scoring" / "factcheck.py", "--run", run], env)
        step("pairwise judges", [py, bench / "scoring" / "pairwise.py", "--run", run, "--judges", "3"], env)
        step("ranking judge", [py, bench / "scoring" / "rank.py", "--run", run, "--judges", "2"], env)
    step("human board", [py, bench / "scoring" / "human_board.py", "build", "--run", run, "--task", "t7"], env, check=False)
    step("report", [py, bench / "scoring" / "aggregate.py", "--run", run], env)
    return 0


if __name__ == "__main__":
    sys.exit(main())

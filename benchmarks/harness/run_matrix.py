#!/usr/bin/env python3
"""Run a benchmark round: every (arm, task) cell, at most N at once, in the foreground.

    python benchmarks/harness/run_matrix.py --run r1 [--arms a,b] [--tasks t1,t7] [-j 2] [--reps 1]
    python benchmarks/harness/run_matrix.py --run r1 --dry-run      # print the schedule only
    python benchmarks/harness/run_matrix.py --run r1 --task-arms "t1=baseline+showtime+skill-b;t2=baseline+showtime+skill-h"

Per-task arms
  --task-arms gives each task its own arm list ("task=arm+arm;task=arm+arm", or a JSON file mapping task id
  or prefix -> [arm, ...]). Only the listed tasks run (unless --tasks narrows them further); --arms, if also
  given, filters every list. Scoring needs nothing extra: it scores whatever cells exist.

Scheduling
  - Cells are grouped by task; inside a task the arm order is shuffled with a fixed seed, and the runs are
    started in that order, N at a time. So two concurrent runs are usually two arms of the SAME task,
    which keeps machine load comparable between the arms being compared.
  - --reps R repeats the whole matrix as <run>-rep1..R (fresh workspaces each time).
  - Finished cells are skipped (meta.json exists), so an interrupted round resumes where it stopped.
  - Each cell is its own `run_one.py` process; this script waits for all of them before it exits.
"""
import argparse
import json
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402


def parse_task_arms(spec: str) -> dict:
    """ "t1=a+b;t2=a+c" or a JSON file {"t1": ["a", "b"], ...} -> {task prefix: [arm, ...]}."""
    p = Path(spec).expanduser()
    if p.suffix == ".json" and p.is_file():
        raw = json.loads(p.read_text(encoding="utf-8"))
        return {str(k): [str(x) for x in v] for k, v in raw.items() if not str(k).startswith("_")}
    out = {}
    for part in spec.replace(",", ";").split(";"):
        if not part.strip():
            continue
        if "=" not in part:
            raise SystemExit("--task-arms: expected task=arm+arm, got %r" % part)
        k, v = part.split("=", 1)
        out[k.strip()] = [x.strip() for x in v.split("+") if x.strip()]
    if not out:
        raise SystemExit("--task-arms: empty")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--arms")
    ap.add_argument("--tasks")
    ap.add_argument("--task-arms", help='per-task arm lists: "t1=baseline+showtime+skill-b;t2=..." or a JSON file')
    ap.add_argument("--reverse", action="store_true", help="take tasks in reverse order (for a second process on the same round; cells are locked)")
    ap.add_argument("-j", "--jobs", type=int, default=2, help="concurrent runs (default 2; keep <= 2 on 6 cores)")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--cap-min", type=float)
    ap.add_argument("--budget", type=float, default=15.0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    arms = [x["id"] for x in common.load_arms(a.arms.split(",") if a.arms else None)["arms"]]
    tasks = [t["id"] for t in common.load_tasks(a.tasks.split(",") if a.tasks else None)]
    per_task = {t: arms for t in tasks}
    if a.task_arms:
        known = {x["id"] for x in common.load_arms()["arms"]}
        per_task = {}
        for key, lst in parse_task_arms(a.task_arms).items():
            bad = [x for x in lst if x not in known]
            if bad:
                raise SystemExit("--task-arms: unknown arm(s) %s (known: %s)" % (bad, ", ".join(sorted(known))))
            for t in tasks:
                if t == key or t.split("-")[0] == key:
                    per_task[t] = [x for x in arms if x in lst]  # arms.json order, then shuffled below
        tasks = [t for t in tasks if per_task.get(t)]
        if not tasks:
            raise SystemExit("--task-arms: no task left to run")
    if a.reverse:
        tasks = tasks[::-1]  # a second process can start from the other end of the same round
    rng = random.Random(a.seed)
    cells = []
    for rep in range(1, a.reps + 1):
        name = a.run if a.reps == 1 else "%s-rep%d" % (a.run, rep)
        for t in tasks:
            order = per_task[t][:]
            rng.shuffle(order)
            cells += [(name, t, arm) for arm in order]
    for c in cells:
        print("%-12s %-18s %s" % c)
    if a.dry_run:
        return 0
    here = Path(__file__).resolve().parent

    def go(cell):
        name, t, arm = cell
        cmd = [sys.executable, str(here / "run_one.py"), "--run", name, "--task", t, "--arm", arm,
               "--budget", str(a.budget)]
        if a.cap_min:
            cmd += ["--cap-min", str(a.cap_min)]
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True)
        return cell, r.returncode, time.time() - t0, (r.stdout + r.stderr)[-600:]

    failures = 0
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        futs = [ex.submit(go, c) for c in cells]
        for f in as_completed(futs):
            cell, rc, dt, tail = f.result()
            failures += rc != 0
            common.log("%s %s %s: exit %d in %.0fs%s" % (cell + (rc, dt, "" if rc == 0 else "\n" + tail)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

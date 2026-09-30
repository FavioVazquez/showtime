#!/usr/bin/env python3
"""Run a benchmark round from its manifest (benchmarks/rounds/<run>.json): new cells, reused cells, scoring, gates.

    python benchmarks/harness/round.py plan   benchmarks/rounds/r4.json     # what runs, what is reused, checks
    python benchmarks/harness/round.py reuse  benchmarks/rounds/r4.json     # copy the reused cells into the round
    python benchmarks/harness/round.py run    benchmarks/rounds/r4.json [-j 3] [--tasks t9]  # the new cells
    python benchmarks/harness/round.py score  benchmarks/rounds/r4.json     # auto, fact check, rank, boards, report
    python benchmarks/harness/round.py report benchmarks/rounds/r4.json     # stream metrics + release gates only
    python benchmarks/harness/round.py all    benchmarks/rounds/r4.json     # reuse, run, score
    ... --fake                                                              # stand-in CLI: no model, no cost

A manifest names cells, not only arms: a cell is one folder of the round (runs/<run>/<task>/<cell>) made
either by a new run of an arm (`new`) or by copying a finished cell from an earlier round (`reuse`). Two
cells may run the same arm (a second run to see the spread: `showtime-rep2`). A reused cell keeps its
stream, meta and fact check; everything else is scored again with this checkout's scoring, so every cell of
the round is measured by the same `showtime qa`, frames and judges. A reused cell must have been made for
the same prompt as the task file today (checked), and its deliverable must still exist in its workspace.

Isolation (round 3 lesson): each new cell runs in its own workspace and CLAUDE_CONFIG_DIR, and the plugin
arm gets its own runtime-home overlay whose `showtime` command runs the arm's frozen snapshot (arms.py
`overlay_home`). `plan` refuses to go on when an arm is not set up that way; the report flags any command a
run made against another showtime folder (round_report.py `foreign_paths`).
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common  # noqa: E402

SCHEMA = "showtime.bench.round/1"
KEEP_FROM_REUSED = ("meta.json", "stream.jsonl", "stderr.log")


# ---------------------------------------------------------------- manifest

def load_manifest(path: Path) -> Dict:
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    if m.get("schema") != SCHEMA:
        raise SystemExit("%s: not a round manifest (schema %s expected)" % (path, SCHEMA))
    m["_path"] = str(path)
    return m


def cells(m: Dict) -> List[Dict]:
    """Every cell of the round: {task, cell, arm, kind: new|reuse, board, judge, source?}."""
    known_arms = {a["id"] for a in common.load_arms()["arms"]}
    defs = m.get("cells") or {}
    out = []
    for key, spec in m["tasks"].items():
        task = common.load_tasks([key])[0]
        for kind in ("new", "reuse"):
            for name in spec.get(kind, []):
                d = defs.get(name) or {}
                arm = d.get("arm", name)
                if arm not in known_arms:
                    raise SystemExit("manifest: cell %s uses unknown arm %s" % (name, arm))
                c = {"task": task["id"], "cell": name, "arm": arm, "kind": kind, "board": d.get("board", True),
                     "judge": d.get("judge", True), "note": d.get("note", "")}
                if kind == "reuse":
                    c["source"] = str(reuse_root(m) / task["id"] / d.get("reuse_cell", name))
                out.append(c)
    names = [(c["task"], c["cell"]) for c in out]
    dup = {x for x in names if names.count(x) > 1}
    if dup:
        raise SystemExit("manifest: cells listed twice: %s" % sorted(dup))
    return out


def reuse_root(m: Dict) -> Path:
    home = os.environ.get("BENCH_REUSE_HOME") or m.get("reuse", {}).get("home") or ""
    return Path(home).expanduser() / "runs" / m.get("reuse", {}).get("run", "")


def run_root(m: Dict) -> Path:
    return common.bench_home() / "runs" / m["run"]


# ---------------------------------------------------------------- checks

def check_reuse(c: Dict) -> Optional[str]:
    """None when a reused cell can be copied, else why not."""
    src = Path(c["source"])
    meta = common.read_json(src / "meta.json")
    if not meta:
        return "no meta.json in %s" % src
    task = common.load_tasks([c["task"]])[0]
    if meta.get("prompt") != task["prompt"]:
        return "made for another prompt (%r), the task now says %r" % (meta.get("prompt"), task["prompt"])
    prim = (meta.get("deliverable") or {}).get("primary")
    if not prim:
        return "the source cell delivered nothing (it would be reused as a failure; say so in the manifest)"
    if not (Path(meta["workspace"]) / prim).exists():
        return "its deliverable is gone: %s" % (Path(meta["workspace"]) / prim)
    return None


def check_arm(arm_id: str) -> Optional[str]:
    """The plugin arm must be set up with its own runtime-home overlay (round 3 ran two tasks on another
    branch's code through a shared home). None when fine."""
    import arms as armlib
    d = armlib.arm_dir(arm_id)
    man = common.read_json(d / "manifest.json")
    if not man:
        return "not set up. FIX: python benchmarks/harness/arms.py setup --arms %s --force" % arm_id
    if man.get("kind") != "plugin":
        return None
    home = d / "home" / ".showtime"
    rec = home / "skill-path"
    if home.is_symlink() or not rec.is_file():
        return ("its runtime home is not an overlay with its own skill-path (set up by an older harness). "
                "FIX: python benchmarks/harness/arms.py setup --arms %s --force" % arm_id)
    target = Path(rec.read_text(encoding="utf-8").strip())
    snap = Path(man.get("plugin_dir") or "")
    if not str(target).startswith(str(snap)):
        return "its showtime command runs %s, not the arm's snapshot %s" % (target, snap)
    return None


def snapshot_age(arm_id: str) -> Optional[str]:
    """A warning when the plugin snapshot differs from this checkout (set up before the last change)."""
    import arms as armlib
    man = common.read_json(armlib.arm_dir(arm_id) / "manifest.json") or {}
    if man.get("kind") != "plugin" or not man.get("plugin_dir_digest"):
        return None
    now = common.tree_digest(common.REPO / "skills")
    if now != man["plugin_dir_digest"]:
        return ("the %s snapshot (%s) differs from this checkout's skills/: re-run "
                "`arms.py setup --arms %s --force` if the checkout is the code to measure" % (arm_id, man.get("created"), arm_id))
    return None


# ---------------------------------------------------------------- estimate

EST_NEW = {  # USD (API-equivalent) and minutes per new cell when no earlier cell of that arm and task exists
    "showtime": (3.0, 14.0), "baseline": (1.3, 8.0)}
JUDGE_USD_PER_CANDIDATE = 0.125   # round 3: 18 ranking judgments of 4 candidates cost $8.97
FACTCHECK_USD = 0.2               # round 3: $0.13-0.26 per deliverable


def estimate(m: Dict, cs: List[Dict]) -> Dict:
    """Cost and time of the round from the reuse source's own numbers (same arm + task), else EST_NEW."""
    prev = {}
    root = reuse_root(m)
    for mj in sorted(root.glob("*/*/meta.json")) if root.exists() else []:
        meta = common.read_json(mj) or {}
        prev[(mj.parent.parent.name, mj.parent.name)] = (meta.get("cost_usd") or 0.0, (meta.get("wall_s") or 0) / 60.0)
    rows, runs_usd, runs_min = [], 0.0, 0.0
    ref_cell = {c: (m.get("cells", {}).get(c, {}) or {}).get("reuse_cell", c) for c in m.get("cells", {})}
    for c in cs:
        if c["kind"] != "new":
            continue
        # the closest earlier cell: the focal arm's previous version on the same task, else the same arm there
        if c["arm"] == m.get("focal") and m.get("previous"):
            key = (c["task"], ref_cell.get(m["previous"], m["previous"]))
        else:
            key = (c["task"], c["arm"])
        got = prev.get(key)
        usd, mins = got if got else EST_NEW.get(c["arm"], (3.0, 14.0))
        src = "same task, earlier round" if got else "default estimate"
        rows.append({"task": c["task"], "cell": c["cell"], "usd": round(usd, 2), "min": round(mins, 1), "from": src})
        runs_usd += usd
        runs_min += mins
    by_task: Dict[str, int] = {}
    for c in cs:
        if c["judge"]:
            by_task[c["task"]] = by_task.get(c["task"], 0) + 1
    judges = (m.get("judging") or {}).get("rank_judges", 3)
    rank_usd = sum(n * JUDGE_USD_PER_CANDIDATE * judges for n in by_task.values() if n >= 2)
    fc_usd = FACTCHECK_USD * sum(1 for c in cs if c["kind"] == "new" and "footage" not in
                                 (common.load_tasks([c["task"]])[0].get("expect") or {}))
    jobs = (m.get("run_settings") or {}).get("jobs", 2)
    return {"cells": rows, "runs_usd": round(runs_usd, 2), "runs_serial_min": round(runs_min),
            "runs_wall_min_at_jobs": round(runs_min / max(1, jobs) * 1.15), "jobs": jobs,
            "rank_usd": round(rank_usd, 2), "factcheck_usd": round(fc_usd, 2),
            "total_usd": round(runs_usd + rank_usd + fc_usd, 2)}


# ---------------------------------------------------------------- steps

def cmd_plan(m: Dict, a) -> int:
    cs = cells(m)
    problems = []
    print("round %s: %d cells (%d new, %d reused)" % (m["run"], len(cs), sum(c["kind"] == "new" for c in cs),
                                                        sum(c["kind"] == "reuse" for c in cs)))
    for c in cs:
        why = check_reuse(c) if c["kind"] == "reuse" else None
        flags = ("" if c["board"] else " no-board") + ("" if c["judge"] else " no-judge")
        print("  %-20s %-15s %-6s %-9s%s%s" % (c["task"], c["cell"], c["kind"], c["arm"], flags,
                                              ("  <- " + Path(c["source"]).relative_to(reuse_root(m)).as_posix()) if c["kind"] == "reuse" else ""))
        if why:
            problems.append("%s/%s: %s" % (c["task"], c["cell"], why))
    if not a.fake:
        for arm in sorted({c["arm"] for c in cs if c["kind"] == "new"}):
            why = check_arm(arm)
            if why:
                problems.append("arm %s: %s" % (arm, why))
            old = snapshot_age(arm)
            if old:
                print("  note: " + old)
    for t in {c["task"] for c in cs}:
        ref = common.load_tasks([t])[0]
        for item in ref.get("inputs", []):
            if "fetch" in item and not (common.BENCH / "fixtures" / "media" / (item["fetch"] + ".mp4")).exists():
                problems.append("%s: fixture %s missing. FIX: python benchmarks/fixtures/fetch_fixtures.py" % (t, item["fetch"]))
    est = estimate(m, cs)
    print("estimate: runs $%.2f (%d min one at a time, ~%d min at -j %d), ranking judges $%.2f, fact checks $%.2f; "
          "total about $%.2f (API-equivalent)" % (est["runs_usd"], est["runs_serial_min"], est["runs_wall_min_at_jobs"],
                                                   est["jobs"], est["rank_usd"], est["factcheck_usd"], est["total_usd"]))
    common.write_json(run_root(m) / "round.json", {"manifest": m["_path"], "planned": common.now_iso(), "cells": cs,
                                                   "estimate": est, "problems": problems})
    for p in problems:
        print("PROBLEM: " + p)
    return 1 if problems else 0


def cmd_reuse(m: Dict, a) -> int:
    bad = 0
    for c in cells(m):
        if c["kind"] != "reuse":
            continue
        dst = run_root(m) / c["task"] / c["cell"]
        if (dst / "meta.json").exists() and not a.force:
            print("  %-20s %-15s already here" % (c["task"], c["cell"]))
            continue
        why = check_reuse(c)
        if why:
            print("  %-20s %-15s CANNOT REUSE: %s" % (c["task"], c["cell"], why))
            bad += 1
            continue
        copy_cell(Path(c["source"]), dst, c)
        print("  %-20s %-15s copied from %s" % (c["task"], c["cell"], c["source"]))
    return 1 if bad else 0


def copy_cell(src: Path, dst: Path, c: Dict) -> None:
    """meta, stream and stderr, plus a fact check that verifiably looked at the frames; the rest is re-scored."""
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for name in KEEP_FROM_REUSED:
        if (src / name).exists():
            shutil.copy2(src / name, dst / name)
    fc = common.read_json(src / "score" / "factcheck.json") or {}
    if fc.get("ok") and fc.get("claims") is not None:
        (dst / "score").mkdir()
        common.write_json(dst / "score" / "factcheck.json", dict(fc, reused_from=str(src)))
    meta = common.read_json(dst / "meta.json")
    meta["reused"] = {"from": str(src), "original_run": meta.get("run"), "original_arm": meta.get("arm"),
                      "copied": common.now_iso(), "cell": c["cell"]}
    meta["cell"] = c["cell"]
    common.write_json(dst / "meta.json", meta)


def cmd_run(m: Dict, a) -> int:
    cs = [c for c in cells(m) if c["kind"] == "new" and (not a.tasks or c["task"].split("-")[0] in a.tasks.split(",")
                                                            or c["task"] in a.tasks.split(","))]
    if a.cells:
        cs = [c for c in cs if c["cell"] in a.cells.split(",")]
    settings = m.get("run_settings") or {}
    rng = random.Random(settings.get("seed", 4))
    order = []
    for t in sorted({c["task"] for c in cs}, key=lambda x: int(x.split("-")[0][1:])):
        group = [c for c in cs if c["task"] == t]
        rng.shuffle(group)
        order += group
    for c in order:
        print("%-8s %-20s %-15s %s" % (m["run"], c["task"], c["cell"], c["arm"]))
    if a.dry_run:
        return 0
    env = child_env(a)
    budget = a.budget or settings.get("budget_usd", 15.0)

    def go(c):
        cmd = [sys.executable, str(HERE / "run_one.py"), "--run", m["run"], "--task", c["task"], "--arm", c["arm"],
               "--cell", c["cell"], "--budget", str(budget)]
        cap = a.cap_min or settings.get("cap_min")
        if cap:
            cmd += ["--cap-min", str(cap)]
        t0 = time.time()
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)
        return c, r.returncode, time.time() - t0, (r.stdout + r.stderr)[-600:]

    failures = 0
    with ThreadPoolExecutor(max_workers=max(1, a.jobs or settings.get("jobs", 2))) as ex:
        for f in as_completed([ex.submit(go, c) for c in order]):
            c, rc, dt, tail = f.result()
            failures += rc != 0
            common.log("%s %s: exit %d in %.0fs%s" % (c["task"], c["cell"], rc, dt, "" if rc == 0 else "\n" + tail))
    return 1 if failures else 0


def child_env(a) -> Dict[str, str]:
    env = dict(os.environ)
    if a.fake:
        env["BENCH_CLAUDE"] = str(HERE / "selftest" / "fake_claude.py")
    return env


def step(title: str, cmd: List, env: Dict, check: bool = False) -> int:
    print("\n== %s\n$ %s" % (title, " ".join(str(x) for x in cmd[1:])), flush=True)
    r = subprocess.run([str(x) for x in cmd], env=env)
    if check and r.returncode != 0:
        raise SystemExit("round: step failed: %s (exit %d)" % (title, r.returncode))
    return r.returncode


def cmd_score(m: Dict, a) -> int:
    py, sc = sys.executable, common.BENCH / "scoring"
    env = child_env(a)
    judging = m.get("judging") or {}
    rc = 0
    rc |= step("automatic metrics (every cell, this checkout's qa)", [py, sc / "auto_metrics.py", "--run", m["run"]], env)
    if judging.get("factcheck", True):
        rc |= step("fact check (cells without a verified one)", [py, sc / "factcheck.py", "--run", m["run"], "--skip-done"], env)
    nojudge = sorted({c["cell"] for c in cells(m) if not c["judge"]})
    rank = [py, sc / "rank.py", "--run", m["run"], "--judges", str(judging.get("rank_judges", 3)), "-j", str(judging.get("rank_jobs", 3))]
    rc |= step("ranking judges", rank + (["--skip-cells", ",".join(nojudge)] if nojudge else []), env)
    if judging.get("boards", True):
        noboard = sorted({c["cell"] for c in cells(m) if not c["board"]})
        rc |= step("blind boards", [py, sc / "human_board.py", "build", "--run", m["run"], "--focal", m.get("focal", "showtime")]
                   + (["--skip-cells", ",".join(noboard)] if noboard else []), env)
    rc |= cmd_report(m, a)
    return rc


def cmd_report(m: Dict, a) -> int:
    py, sc = sys.executable, common.BENCH / "scoring"
    env = child_env(a)
    step("tally the blind votes (if any were imported)", [py, sc / "human_board.py", "tally", "--run", m["run"]], env)
    rc = step("aggregate", [py, sc / "aggregate.py", "--run", m["run"]], env)
    return rc | step("stream metrics and release gates", [py, sc / "round_report.py", "--manifest", m["_path"]], env)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["plan", "reuse", "run", "score", "report", "all"])
    ap.add_argument("manifest")
    ap.add_argument("--fake", action="store_true", help="stand-in CLI for runs and judges (harness self-test, no cost)")
    ap.add_argument("-j", "--jobs", type=int)
    ap.add_argument("--tasks", help="run: only these tasks (t9,t10)")
    ap.add_argument("--cells", help="run: only these cells (showtime,showtime-rep2)")
    ap.add_argument("--budget", type=float, help="run: --max-budget-usd per session (default: the manifest's)")
    ap.add_argument("--cap-min", type=float, help="run: time cap per cell in minutes (default: each task's)")
    ap.add_argument("--dry-run", action="store_true", help="run: print the schedule only")
    ap.add_argument("--force", action="store_true", help="reuse: copy again over cells already in the round")
    a = ap.parse_args()
    m = load_manifest(Path(a.manifest))
    if a.command == "plan":
        return cmd_plan(m, a)
    if a.command == "reuse":
        return cmd_reuse(m, a)
    if a.command == "run":
        return cmd_run(m, a)
    if a.command == "score":
        return cmd_score(m, a)
    if a.command == "report":
        return cmd_report(m, a)
    rc = cmd_plan(m, a)
    if rc:
        return rc
    return cmd_reuse(m, a) | cmd_run(m, a) | cmd_score(m, a)


if __name__ == "__main__":
    sys.exit(main())

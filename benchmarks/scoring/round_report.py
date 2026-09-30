#!/usr/bin/env python3
"""Per-cell stream metrics and the release gates for a round described by a manifest (benchmarks/rounds/*.json).

    python benchmarks/scoring/round_report.py --manifest benchmarks/rounds/r4.json [--json]

Reads what the other steps wrote (meta.json, stream.jsonl, score/auto.json, rank_summary.json,
human_summary.json) and writes, next to the round's report.md:
  stream_metrics.json   per cell: cost, tokens, model calls, images read into the main context (and by
                        sub-agents), largest main context, tool text, full renders, receipt, foreign paths
  gates.json / gates.md every gate of the manifest as PASS / FAIL / PENDING with the numbers behind it
and appends both tables to report.md (between markers, so running it again replaces them).

Full renders per job come from the job's receipt.json when showtime wrote one (renders.full), else from
job.json, else they are estimated from the stream (render commands without --from/--to), and the table
says which. "Foreign paths" lists showtime folders a run touched outside its own arm (a contaminated run,
as two round-3 cells were): a plugin cell may use only its snapshot and its own runtime home; a cell of any
other arm may use none.
"""
import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))
import common  # noqa: E402
import stream_cost  # noqa: E402

BEGIN, END = "<!-- round_report: begin -->", "<!-- round_report: end -->"
RENDER_RE = re.compile(r"""(?:^|[\s;&|(`])(?:"?\$\{?\w+\}?"?|\S*showtime(?:\.cmd)?)\s+(?:edit\s+)?render\b([^;&|\n]*)""")
PARTIAL_RE = re.compile(r"--(?:from|to|span)\b")
SHOWTIME_PATH_RE = re.compile(r"(/[^\s'\"`;|&]*?(?:/skills/showtime|/\.showtime))(?=[/\s'\"`;|&]|$)([^\s'\"`;|&]*)")


# ---------------------------------------------------------------- per cell

def tool_calls(stream: Path) -> List[Dict]:
    """Main-agent tool calls (name, input) in order."""
    out = []
    for line in stream.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("type") != "assistant" or m.get("parent_tool_use_id"):
            continue
        for b in (m.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                out.append({"name": b.get("name", ""), "input": b.get("input") or {}})
    return out


def renders_from_stream(calls: List[Dict]) -> Dict:
    """Render commands the agent ran: full vs partial (--from/--to/--span). An estimate: renders started by a
    script the agent wrote are not seen."""
    full = partial = 0
    for c in calls:
        if c["name"] == "Bash":
            for m in RENDER_RE.finditer(str(c["input"].get("command") or "")):
                if PARTIAL_RE.search(m.group(1)):
                    partial += 1
                else:
                    full += 1
        elif c["name"].endswith("__render"):
            if any(k in c["input"] for k in ("from", "to", "span")):
                partial += 1
            else:
                full += 1
    return {"full": full, "partial": partial, "source": "stream (estimate)"}


def job_dirs(ws: Path) -> List[Path]:
    root = ws / "showtime-out"
    return sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime) if root.is_dir() else []


def receipt_for(ws: Path, primary: Optional[str]) -> Optional[Dict]:
    """The receipt of the job that made the deliverable (else the newest job with one)."""
    jobs = job_dirs(ws)
    if primary:
        owner = [j for j in jobs if (ws / primary).resolve().as_posix().startswith(j.resolve().as_posix() + "/")]
        jobs = owner + [j for j in jobs if j not in owner][::-1]
    else:
        jobs = jobs[::-1]
    for j in jobs:
        rec = common.read_json(j / "receipt.json")
        if rec:
            return rec
    return None


def renders_from_job(ws: Path, primary: Optional[str]) -> Optional[Dict]:
    rec = receipt_for(ws, primary)
    if rec and isinstance(rec.get("renders"), dict):
        r = rec["renders"]
        return {"full": r.get("full"), "partial": r.get("partial"), "preview": r.get("preview"), "source": "receipt.json"}
    for j in job_dirs(ws)[::-1]:
        data = common.read_json(j / "job.json") or {}
        rl = [x for x in data.get("renders") or [] if isinstance(x, dict)]
        if rl:
            return {"full": sum(1 for x in rl if x.get("kind") == "full"),
                    "partial": sum(1 for x in rl if x.get("kind") == "partial"),
                    "preview": sum(1 for x in rl if x.get("kind") == "preview"), "source": "job.json"}
    return None


def _strings(v) -> List[str]:
    """Every string in a tool input, decoded (a JSON dump would glue an escaped newline onto the next path)."""
    if isinstance(v, str):
        return [v]
    if isinstance(v, dict):
        return [s for x in v.values() for s in _strings(x)]
    if isinstance(v, list):
        return [s for x in v for s in _strings(x)]
    return []


def foreign_paths(calls: List[Dict], allowed: List[str]) -> List[str]:
    """showtime folders named in the run's commands and file reads that are not the arm's own. A path is the
    arm's own when it lies under an allowed root (or is a parent of one, e.g. `ls` of the arm's folder)."""
    roots = [a.rstrip("/") for a in allowed]
    seen = []
    for c in calls:
        for text in _strings(c["input"]):
            for m in SHOWTIME_PATH_RE.finditer(text):
                p, full = m.group(1), (m.group(1) + m.group(2)).rstrip("/")
                if any(full == a or full.startswith(a + "/") or a.startswith(full + "/") for a in roots):
                    continue
                if p not in seen:
                    seen.append(p)
    return seen


def arm_roots(arm_id: str) -> List[str]:
    """Where a plugin cell may legitimately touch showtime: its snapshot and its runtime-home overlay."""
    import arms as armlib
    d = armlib.arm_dir(arm_id)
    man = common.read_json(d / "manifest.json") or {}
    if man.get("kind") != "plugin":
        return []
    out = [str(d / "home" / ".showtime")]
    if man.get("plugin_dir"):
        out.append(str(Path(man["plugin_dir"])))
    # the overlay links the operator's tools, models and caches in by design; only bin/ and the skill path are the
    # arm's own, so reaching those in the shared home is still foreign (the round 3 contamination)
    shared = common.showtime_home()
    if shared.is_dir():
        out += [str(e) for e in sorted(shared.iterdir()) if e.name not in armlib.OWN_ENTRIES]
    return out


def cell_metrics(rdir: Path) -> Dict:
    meta = common.read_json(rdir / "meta.json") or {}
    stream = rdir / "stream.jsonl"
    row = {"task": rdir.parent.name, "cell": rdir.name, "arm": meta.get("arm"),
           "reused": bool(meta.get("reused")), "cost_usd": meta.get("cost_usd"), "wall_s": meta.get("wall_s"),
           "turns": meta.get("num_turns"), "tokens": meta.get("tokens") or {}}
    if not stream.exists():
        return dict(row, error="no stream.jsonl")
    sc = stream_cost.analyse(stream, top=3)
    tok = row["tokens"]
    row.update({"calls_main": sc["calls_main"], "images_main": sc["images_main"], "images_sub": sc["images_sub"],
                "ctx_max": sc["ctx_max"], "ctx_median": sc["ctx_median"], "tool_text_chars": sc["tool_output_chars"],
                "tokens_in": (tok.get("input_tokens") or 0) + (tok.get("cache_read_input_tokens") or 0)
                + (tok.get("cache_creation_input_tokens") or 0),
                "tokens_out": tok.get("output_tokens") or 0,
                "image_sources": sc["image_sources"]})
    if row["cost_usd"] is None:
        row["cost_usd"] = sc["cost_usd"]
    calls = tool_calls(stream)
    ws = Path(meta.get("workspace") or "/nonexistent")
    prim = (meta.get("deliverable") or {}).get("primary")
    rj = renders_from_job(ws, prim) if ws.exists() else None
    row["renders"] = rj or renders_from_stream(calls)
    rec = receipt_for(ws, prim) if ws.exists() else None
    row["receipt"] = bool(rec)
    row["receipt_cost"] = None
    if rec:
        cost = (rec.get("usage") or {}).get("cost_usd")   # receipt.json schema 1 (references/receipt.md)
        row["receipt_cost"] = cost if isinstance(cost, (int, float)) else None
    allowed = arm_roots(meta.get("arm") or "") if not meta.get("reused") else []
    row["foreign_paths"] = foreign_paths(calls, allowed) if not meta.get("reused") else []
    return row


# ---------------------------------------------------------------- gates

def med(xs: List) -> Optional[float]:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.median(xs), 2) if xs else None


def gate(gid: str, name: str, status: str, detail: str, **numbers) -> Dict:
    return dict({"id": gid, "name": name, "status": status, "detail": detail}, **numbers)


def vote_between(human: Dict, task: str, a: str, b: str) -> Optional[str]:
    """The blind vote between two cells on a task: "a", "b", "tie" or None (no answer, no ratings)."""
    for p in human.get("pairs") or []:
        if p.get("task") == task and {p.get("a"), p.get("b")} == {a, b}:
            w = p.get("winner")
            return "tie" if w == "tie" else ("a" if w == a else "b" if w == b else None)
    ra = (human.get("ratings_by_task") or {}).get(task, {}).get(a)
    rb = (human.get("ratings_by_task") or {}).get(task, {}).get(b)
    if isinstance(ra, (int, float)) and isinstance(rb, (int, float)):
        return "a" if ra > rb else "b" if rb > ra else "tie"
    return None


def ratings_by_task(root: Path) -> Dict[str, Dict[str, float]]:
    """{task: {cell: rating}} from the imported vote digests (tally keeps ratings pooled per arm only)."""
    import human_board
    keys = common.read_json(common.bench_home() / "human" / root.name / "key.json", {}) or {}
    out = {}
    for task, k in keys.items():
        dg = common.bench_home() / "human" / root.name / "votes" / (task + ".txt")
        if not dg.exists():
            continue
        d = human_board.parse_digest(dg.read_text(encoding="utf-8"))
        out[task] = {k["letters"][L]: n for L, n in d["ratings"].items() if L in k["letters"]}
    return out


def gates(m: Dict, rows: List[Dict], root: Path) -> List[Dict]:
    g = m.get("gates") or {}
    focal, prev, base = m.get("focal", "showtime"), m.get("previous", ""), m.get("baseline", "baseline")
    rank = (common.read_json(root / "rank_summary.json", {}) or {}).get("per_task") or {}
    human = common.read_json(root / "human_summary.json", {}) or {}
    human["ratings_by_task"] = ratings_by_task(root)
    auto = {(r["task"], r["cell"]): (common.read_json(root / r["task"] / r["cell"] / "score" / "auto.json") or {}) for r in rows}
    focal_rows = [r for r in rows if r["cell"] == focal]
    focal_runs = [r for r in rows if r["arm"] == focal and not r["reused"]]   # every new run of the arm (reps too)
    out = []

    # 1. cost per video vs the baseline on the same tasks
    tasks = sorted({r["task"] for r in focal_rows} & {r["task"] for r in rows if r["cell"] == base})
    fc = med([r["cost_usd"] for r in focal_rows if r["task"] in tasks])
    bc = med([r["cost_usd"] for r in rows if r["cell"] == base and r["task"] in tasks])
    out.append(gate("cost", "Median cost per video <= plain Opus on the same tasks",
                    "PENDING" if fc is None or bc is None else ("PASS" if fc <= bc else "FAIL"),
                    "%s $%s vs %s $%s on %d tasks (API-equivalent, from the stream)" % (focal, fc, base, bc, len(tasks)),
                    focal_median=fc, baseline_median=bc))
    # 2. images read into the main context
    im = med([r.get("images_main") for r in focal_rows])
    cap = g.get("images_main_median_max", 12)
    out.append(gate("images", "Images read into the main context: median <= %d per job" % cap,
                    "PENDING" if im is None else ("PASS" if im <= cap else "FAIL"),
                    "median %s (per task: %s)" % (im, ", ".join("%s %s" % (r["task"].split("-")[0], r.get("images_main")) for r in focal_rows)),
                    median=im))
    # 3. full renders per job
    rn = med([(r.get("renders") or {}).get("full") for r in focal_rows])
    rcap = g.get("full_renders_median_max", 1)
    srcs = sorted({(r.get("renders") or {}).get("source") for r in focal_rows if r.get("renders")})
    out.append(gate("renders", "Full renders per job: median %s" % rcap,
                    "PENDING" if rn is None else ("PASS" if rn <= rcap else "FAIL"),
                    "median %s (per task: %s; from %s)" % (rn, ", ".join("%s %s" % (r["task"].split("-")[0], (r.get("renders") or {}).get("full"))
                                                                        for r in focal_rows), " / ".join(srcs) or "-"),
                    median=rn))
    # 4. quality not worse than the previous version: judge AND vote, per task
    qt = g.get("quality_tasks") or []
    need = g.get("quality_min_tasks", max(0, len(qt) - 1))
    per, passed, pending = [], 0, 0
    for t in qt:
        tid = common.load_tasks([t])[0]["id"]
        jr = rank.get(tid) or {}
        jf, jp = (jr.get(focal) or {}).get("mean_rank"), (jr.get(prev) or {}).get("mean_rank")
        judge_ok = None if jf is None or jp is None else jf <= jp
        if jf is None and jp is not None and any(r["task"] == tid and r["cell"] == focal for r in rows):
            judge_ok = False   # the new run delivered nothing the judges could rank
        v = vote_between(human, tid, focal, prev)
        vote_ok = None if v is None else v in ("a", "tie")
        ok = False if (judge_ok is False or vote_ok is False) else (None if judge_ok is None or vote_ok is None else True)
        passed += ok is True
        pending += ok is None
        per.append("%s judge %s vs %s%s, vote %s" % (t, jf, jp, "" if judge_ok is None else (" ok" if judge_ok else " worse"),
                                                    {"a": "won", "b": "lost", "tie": "tie", None: "pending"}[v]))
    status = "PASS" if passed >= need else ("PENDING" if passed + pending >= need else "FAIL")
    out.append(gate("quality", "Quality: judge and blind vote >= %s on at least %d of %d tasks" % (prev, need, len(qt)), status,
                    "%d of %d pass, %d pending: %s" % (passed, len(qt), pending, "; ".join(per)), passed=passed, pending=pending))
    # 4b. qa failures on every new run of the focal arm
    fails = [(r["task"], r["cell"], ((auto[(r["task"], r["cell"])].get("qa") or {}).get("summary") or {}).get("fail"))
             for r in focal_runs]
    known = [f for f in fails if isinstance(f[2], int)]
    bad = [f for f in known if f[2] > g.get("qa_fail_max", 0)]
    out.append(gate("qa", "qa failures: %d" % g.get("qa_fail_max", 0),
                    "PENDING" if not known else ("FAIL" if bad else "PASS"),
                    ("failures in " + ", ".join("%s/%s %d" % f for f in bad)) if bad else
                    "%d runs checked, none failed%s" % (len(known), "" if len(known) == len(fails) else " (%d without a qa result)" % (len(fails) - len(known)))))
    # 4c. the launch task is not last (judge and vote), among every cell but the focal arm's other new runs
    lt = g.get("launch_task")
    if lt:
        tid = common.load_tasks([lt])[0]["id"]
        field_cells = {r["cell"] for r in rows if r["task"] == tid and not (r["arm"] == focal and not r["reused"] and r["cell"] != focal)}
        field = {c: v.get("mean_rank") for c, v in (rank.get(tid) or {}).items() if c in field_cells}
        judge_last = None
        if focal in field and len(field) >= 2:
            others = [v for c, v in field.items() if c != focal]
            judge_last = field[focal] > max(others)
        rt = {c: n for c, n in (human["ratings_by_task"].get(tid) or {}).items() if c in field_cells}
        vote_last, vote_note = None, "vote rating %s (field %s)" % (rt.get(focal), json.dumps(rt, sort_keys=True))
        if focal in rt and len(rt) >= 2:
            vote_last = rt[focal] < min(n for c, n in rt.items() if c != focal)
        else:   # a board voted as pairs only (no ratings): last = lost every pair it was in
            mine = [pr for pr in human.get("pairs") or [] if pr.get("task") == tid and focal in (pr.get("a"), pr.get("b"))
                    and {pr.get("a"), pr.get("b")} <= field_cells and pr.get("winner") in (pr.get("a"), pr.get("b"))]
            if mine:
                won = sum(1 for pr in mine if pr["winner"] == focal)
                vote_last = won == 0
                vote_note = "blind pairs won %d of %d" % (won, len(mine))
        st = "FAIL" if (judge_last or vote_last) else ("PENDING" if judge_last is None or vote_last is None else "PASS")
        out.append(gate("launch", "Launch task (%s) not last" % lt, st,
                        "judge mean rank %s (field %s); %s" % (field.get(focal), json.dumps(field, sort_keys=True), vote_note)))
    # 5. receipts
    have = [r for r in focal_runs if r.get("receipt")]
    costed = [r for r in have if r.get("receipt_cost") is not None]
    out.append(gate("receipts", "Every job writes a receipt (cost filled where the host reports it)",
                    "PENDING" if not focal_runs else ("PASS" if len(have) == len(focal_runs) else "FAIL"),
                    "%d of %d runs have receipt.json; %d with a cost" % (len(have), len(focal_runs), len(costed))))
    # isolation
    dirty = [r for r in rows if r.get("foreign_paths")]
    out.append(gate("isolation", "No run touched another showtime folder (round 3 contamination check)",
                    "FAIL" if dirty else "PASS",
                    "; ".join("%s/%s: %s" % (r["task"], r["cell"], ", ".join(r["foreign_paths"][:3])) for r in dirty) or
                    "%d new runs checked" % sum(1 for r in rows if not r["reused"])))
    return out


# ---------------------------------------------------------------- output

def fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return "%.2f" % v
    return str(v)


def metrics_table(rows: List[Dict]) -> str:
    head = ["task", "cell", "reused", "$", "wall min", "turns", "calls", "tokens in (k)", "tokens out (k)", "images main",
            "images sub", "max ctx (k)", "tool text (k chars)", "full renders", "receipt"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        rn = r.get("renders") or {}
        lines.append("| " + " | ".join(fmt(x) for x in [
            r["task"], r["cell"], "yes" if r["reused"] else "", r.get("cost_usd"),
            round((r.get("wall_s") or 0) / 60.0, 1), r.get("turns"), r.get("calls_main"),
            (r.get("tokens_in") or 0) // 1000, (r.get("tokens_out") or 0) // 1000, r.get("images_main"), r.get("images_sub"),
            (r.get("ctx_max") or 0) // 1000, (r.get("tool_text_chars") or 0) // 1000,
            "%s%s" % (fmt(rn.get("full")), "" if rn.get("source") in ("receipt.json", "job.json") else "*"),
            "yes" if r.get("receipt") else ""]) + " |")
    return "\n".join(lines)


def spread_table(rows: List[Dict], focal: str) -> str:
    """The focal arm's repeated runs side by side (cost, images, renders, context)."""
    reps = [r for r in rows if r["arm"] == focal and not r["reused"]]
    tasks = sorted({r["task"] for r in reps if r["cell"] != focal})
    if not tasks:
        return ""
    lines = ["| task | cell | $ | images main | full renders | max ctx (k) | wall min |", "|---|---|---|---|---|---|---|"]
    for t in tasks:
        for r in sorted((x for x in reps if x["task"] == t), key=lambda x: x["cell"]):
            lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (t, r["cell"], fmt(r.get("cost_usd")), fmt(r.get("images_main")),
                                                                 fmt((r.get("renders") or {}).get("full")), (r.get("ctx_max") or 0) // 1000,
                                                                 round((r.get("wall_s") or 0) / 60.0, 1)))
    return "\n".join(lines)


def gates_md(gs: List[Dict]) -> str:
    return "\n".join("- **%s** %s: %s" % (x["status"], x["name"], x["detail"]) for x in gs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    m = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    root = common.bench_home() / "runs" / m["run"]
    rows = [cell_metrics(mj.parent) for mj in sorted(root.glob("*/*/meta.json"))]
    common.write_json(root / "stream_metrics.json", rows)
    gs = gates(m, rows, root)
    common.write_json(root / "gates.json", gs)
    md = ("## Release gates\n\n" + gates_md(gs) + "\n\n## Process metrics from the stream (every cell)\n\n" + metrics_table(rows)
          + "\n\n`*` = full renders estimated from the stream's commands (no receipt.json or job.json record). "
          "Images main / sub: images that entered the main agent's context / a sub-agent's. Max ctx: the largest "
          "input (fresh + cached) of one main-agent model call. Tool text: characters of non-image tool output the "
          "main agent read. Reused cells keep the numbers of the round they were made in.\n")
    sp = spread_table(rows, m.get("focal", "showtime"))
    if sp:
        md += "\n## Spread: repeated runs of %s\n\n%s\n" % (m.get("focal", "showtime"), sp)
    (root / "gates.md").write_text(md, encoding="utf-8")
    rep = root / "report.md"
    if rep.exists():
        text = rep.read_text(encoding="utf-8")
        text = re.sub(re.escape(BEGIN) + ".*?" + re.escape(END) + "\n?", "", text, flags=re.S)
        rep.write_text(text.rstrip() + "\n\n" + BEGIN + "\n" + md + END + "\n", encoding="utf-8")
    if a.json:
        print(json.dumps({"gates": gs, "cells": rows}, indent=1))
    else:
        print(gates_md(gs))
        print("\nwrote %s" % (root / "gates.md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

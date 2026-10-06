#!/usr/bin/env python3
"""The behaviour scoreboard: one `claude plugin eval` run of benchmarks/plugin-eval, in plain numbers.

Reads the eval's output folder (aggregate-result.json, the `--output-dir` of the run) and writes
SCOREBOARD.md: per case the pass rate with showtime and without it (the eval's no-plugin arm, same model),
how often the skill fired, tokens and cost per run, the run date, the model, the runs per case, and a
"what failed" list in plain words. Optionally the latest full-benchmark round (its results.json) is
summarised under it.

    python3 benchmarks/scoring/scoreboard.py <eval output dir> -o benchmarks/plugin-eval/SCOREBOARD.md
    python3 benchmarks/scoring/scoreboard.py <eval output dir> --round latest      # + the newest benchmark round
    python3 benchmarks/scoring/scoreboard.py <eval output dir> --readme            # the README's short table
    python3 benchmarks/scoring/scoreboard.py <eval output dir> --readme --update README.md

Where the numbers come from:
  pass / score / errors   aggregate-result.json, as the eval graded them (a run passes when every scored
                          grader passes; `tool_used: Skill` is the plugin-fired indicator, never scored)
  tokens                  each run's trace (`tracePath`, kept only with `--keep-temp`): the result line's
                          per-model usage (input, output, cache reads, cache writes), else the summed usage
                          records (lib/st/job/usage.py); peak context and turns from stream_cost.py
  cost                    the eval's per-run cost minus its judge cost (the agent's own spend, at list price),
                          and the judges' cost apart; cross-checked against usage.py's dated price table
Traces are copied into <output dir>/traces/ (unless --no-collect), so the token numbers survive the
temporary folders being cleaned. A run with no trace says "not recorded", never a guess.

Stdlib only, Python 3.8+.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
REPO = BENCH.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "skills" / "showtime" / "lib"))
import eval_graders  # noqa: E402
import stream_cost  # noqa: E402
from st.job import usage  # noqa: E402

START = "<!-- scoreboard:start -->"
END = "<!-- scoreboard:end -->"
SCOREBOARD_LINK = "benchmarks/plugin-eval/SCOREBOARD.md"
SKILL_INDICATOR = "skill-fired"
ARMS = (("with", "with showtime"), ("without", "without showtime"))
# README rows: (label, tag, what is counted)
KINDS = (
    ("Stays out of unrelated requests", "non-trigger"),
    ("Honest about inputs and limits", "honesty"),
    ("Keeps the contract (questions, card, plan shape)", "contract"),
)


# ------------------------------------------------------------------ loading

def load_result(path: Path) -> Tuple[Dict[str, Any], Path]:
    """(aggregate result, output dir) from an output folder or the JSON file itself."""
    path = Path(path).expanduser()
    f = path / "aggregate-result.json" if path.is_dir() else path
    if not f.is_file():
        raise SystemExit("no aggregate-result.json in %s: pass the eval's --output-dir" % path)
    return json.loads(f.read_text(encoding="utf-8")), f.parent


def case_info(case: Dict[str, Any], suite_root: str) -> Dict[str, Any]:
    """Tags of a case from its prompt.md (where the run read it, else this checkout's copy)."""
    for d in (Path(suite_root or ".") / str(case.get("dir") or ""), BENCH / "plugin-eval" / str(case.get("name"))):
        if (d / "prompt.md").is_file():
            try:
                return eval_graders.load_case(d)
            except (OSError, ValueError):
                continue
    return {"tags": [], "graders": []}


def trace_file(out_dir: Path, case: str, arm: str, i: int) -> Path:
    return out_dir / "traces" / case / ("%s-%d.jsonl" % (arm, i + 1))


def collect_traces(res: Dict[str, Any], out_dir: Path) -> int:
    """Copy each run's kept trace into <out_dir>/traces/<case>/<arm>-<n>.jsonl; returns how many were copied."""
    n = 0
    for c in res.get("cases") or []:
        for arm, _ in ARMS:
            for i, run in enumerate((c.get("arms") or {}).get(arm) or []):
                dst = trace_file(out_dir, c["name"], arm, i)
                src = Path(str(run.get("tracePath") or ""))
                if dst.is_file() or not run.get("tracePath") or not src.is_file():
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(str(src), str(dst))
                n += 1
    return n


# ------------------------------------------------------------------ tokens and cost of one run

def _result_line(path: Path) -> Optional[Dict[str, Any]]:
    last = None
    for e in eval_graders.read_trace(path):
        if e.get("type") == "result":
            last = e
    return last


def run_usage(trace: Optional[Path]) -> Dict[str, Any]:
    """Tokens of one run from its trace: {recorded, tokens, models, cost_list, turns, ctx_max}."""
    if trace is None or not trace.is_file():
        return {"recorded": False}
    out: Dict[str, Any] = {"recorded": True}
    try:
        sc = stream_cost.analyse(trace)
        out["turns"], out["ctx_max"] = sc.get("turns"), sc.get("ctx_max")
    except (OSError, ValueError):
        pass
    res = _result_line(trace)
    mu = (res or {}).get("modelUsage") if isinstance((res or {}).get("modelUsage"), dict) else None
    models: Dict[str, Dict[str, int]] = {}
    if mu:
        cc = ((res.get("usage") or {}).get("cache_creation") or {})
        w1, w5 = int(cc.get("ephemeral_1h_input_tokens") or 0), int(cc.get("ephemeral_5m_input_tokens") or 0)
        share_1h = w1 / float(w1 + w5) if (w1 + w5) else 0.0
        for m, u in mu.items():
            writes = int(u.get("cacheCreationInputTokens") or 0)
            models[usage.canonical_model(m)] = {
                "input": int(u.get("inputTokens") or 0), "output": int(u.get("outputTokens") or 0),
                "cache_read": int(u.get("cacheReadInputTokens") or 0),
                "write_1h": int(round(writes * share_1h)), "write_5m": writes - int(round(writes * share_1h)),
                "searches": int(u.get("webSearchRequests") or 0)}
    else:                                    # no result line (a killed run): the usage records themselves
        rd = usage.read_claude(trace)
        for m, b in (rd.get("models") or {}).items():
            models[m] = {k: int(b.get(k, 0)) for k in usage.FIELDS}
            models[m]["searches"] = int(b.get("searches", 0))
    if not models:
        return dict(out, recorded=False)
    tot = {k: sum(b[k] for b in models.values()) for k in usage.FIELDS}
    out["models"] = sorted(models)
    out["tokens"] = dict(tot, total=sum(tot.values()))
    costs = [usage.cost_usd(b, m) for m, b in models.items()]
    out["cost_list"] = round(sum(costs), 4) if all(c is not None for c in costs) else None
    return out


# ------------------------------------------------------------------ the numbers

def _mean(xs: List[Optional[float]]) -> Optional[float]:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else None


def _median(xs: List[Optional[float]]) -> Optional[float]:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return statistics.median(xs) if xs else None


def summarize(res: Dict[str, Any], out_dir: Path) -> Dict[str, Any]:
    suite = res.get("suite") or {}
    cases = []
    models_seen = set()
    for c in res.get("cases") or []:
        info = case_info(c, suite.get("root", ""))
        tags = list(info.get("tags") or [])
        defs = {g["name"]: g for g in c.get("graders") or []}
        row: Dict[str, Any] = {"name": c["name"], "tags": tags, "arms": {}, "graders": defs,
                               "prompt": c.get("promptMarkdown", "")}
        for arm, _ in ARMS:
            runs = (c.get("arms") or {}).get(arm)
            if runs is None:
                continue
            recs = []
            for i, r in enumerate(runs):
                tf = trace_file(out_dir, c["name"], arm, i)
                if not tf.is_file() and r.get("tracePath") and Path(str(r["tracePath"])).is_file():
                    tf = Path(str(r["tracePath"]))
                u = run_usage(tf if tf.is_file() else None)
                models_seen.update(u.get("models") or [])
                cost = r.get("costUsd")
                judge = r.get("judgeCostUsd") or 0.0
                recs.append({"i": i + 1, "passed": bool(r.get("passed")), "score": r.get("score"),
                             "error": r.get("error"), "turns": r.get("turns"), "started": r.get("startedAt"),
                             "agent_cost": (cost - judge) if isinstance(cost, (int, float)) else None,
                             "judge_cost": judge, "usage": u, "graders": r.get("graders") or [],
                             "skipped_judges": bool(r.get("skippedPaidGraders"))})
            fired = [g["passed"] for rr in recs for g in rr["graders"] if g.get("name") == SKILL_INDICATOR]
            row["arms"][arm] = {
                "runs": len(recs), "passed": sum(1 for x in recs if x["passed"]),
                "score": _mean([x["score"] for x in recs]), "errors": sum(1 for x in recs if x["error"]),
                "fired": (sum(1 for f in fired if f), len(fired)) if fired else None,
                "tokens": _mean([(x["usage"].get("tokens") or {}).get("total") for x in recs]),
                "tokens_recorded": sum(1 for x in recs if x["usage"].get("recorded")),
                "agent_cost": _mean([x["agent_cost"] for x in recs]),
                "judge_cost": sum(x["judge_cost"] or 0 for x in recs), "records": recs}
        agg = c.get("aggregates") or {}
        row["delta"] = agg.get("delta")
        cases.append(row)
    runs_per_case = sorted({a["runs"] for c in cases for a in c["arms"].values()})
    model = suite.get("modelOverride") or (", ".join(sorted(models_seen)) if models_seen else None)
    plugins = suite.get("plugins") or []
    return {"date": str(res.get("startedAt") or "")[:10], "claude_version": res.get("claudeVersion"),
            "duration_s": res.get("durationSeconds"), "cost": res.get("costUsd"), "partial": res.get("partial"),
            "partial_reason": res.get("partialReason"), "judge": suite.get("judgeModel") or "haiku (the eval's default)",
            "model": model or "the Claude Code default (not recorded)", "ablation": suite.get("ablation"),
            "plugin": ("%s %s" % (plugins[0].get("name"), plugins[0].get("version") or "")).strip() if plugins else None,
            "runs_per_case": runs_per_case, "cases": cases}


# ------------------------------------------------------------------ formatting

def _pct(k: int, n: int) -> str:
    return "%d/%d (%d%%)" % (k, n, round(100.0 * k / n)) if n else "-"


def _tok(v: Optional[float]) -> str:
    if v is None:
        return "not recorded"
    return "%.1fk" % (v / 1000.0) if v >= 1000 else "%d" % v


def _usd(v: Optional[float]) -> str:
    return "-" if v is None else "$%.2f" % v


def _n(n: int, word: str) -> str:
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _kind(tags: List[str]) -> str:
    return ", ".join(tags) if tags else "-"


def _fail_rule(defn: Dict[str, Any]) -> str:
    """The FAIL sentence of a model grader's criteria (its own plain-words definition of a failure)."""
    text = " ".join(str(defn.get("graderMarkdown") or (defn.get("config") or {}).get("criteria") or "").split())
    m = re.search(r"FAIL if (.+?)(?:$|(?<=\.)\s)", text)
    return m.group(1).rstrip(".") if m else ""


def _what(defn: Dict[str, Any]) -> str:
    t = defn.get("type")
    cfg = defn.get("config") or {}
    if t == "regex":
        where = {"last_message": "the final reply", "trace": "the session"}.get(str(cfg.get("target") or "last_message"),
                                                                                str(cfg.get("target")))
        return "regex on %s, %s" % (where, cfg.get("match", "contains"))
    if t == "tool_used":
        return "%s calls, allowed %s..%s" % (cfg.get("tool"), cfg.get("min", 1), cfg.get("max", "any"))
    if t == "llm":
        return "model grader on the %s" % str(cfg.get("focus") or "last_message").replace("_", " ")
    return str(t)


def what_failed(s: Dict[str, Any]) -> List[str]:
    lines = []
    for arm, label in ARMS:
        for c in s["cases"]:
            a = c["arms"].get(arm)
            if not a:
                continue
            n = a["runs"]
            for r in a["records"]:
                if r["error"]:
                    lines.append("- `%s`, %s, run %d ended with an error: %s." % (c["name"], label, r["i"], r["error"]))
                if r["skipped_judges"]:
                    lines.append("- `%s`, %s, run %d: model graders were skipped (cost ceiling)." % (c["name"], label, r["i"]))
            names = []
            for r in a["records"]:
                for g in r["graders"]:
                    if g["name"] not in names:
                        names.append(g["name"])
            for gname in names:
                fails = [(r, g) for r in a["records"] for g in r["graders"] if g["name"] == gname and not g["passed"]]
                if not fails:
                    continue
                defn = c["graders"].get(gname, {})
                indicator = gname == SKILL_INDICATOR
                if indicator and "trigger" not in c["tags"]:
                    continue
                k = len(fails)
                head = "- `%s`, %s, %d of %d run%s: " % (c["name"], label, k, n, "" if n == 1 else "s")
                if indicator:
                    lines.append(head + "the showtime skill did not fire (an indicator, not part of the score).")
                    continue
                why = fails[0][1].get("explanation") or ""
                why = why if len(why) <= 160 else why[:157] + "..."
                rule = _fail_rule(defn) if defn.get("type") == "llm" else ""
                lines.append(head + "`%s` failed (%s%s). %s%s" % (
                    gname, _what(defn), "" if fails[0][1].get("scored", True) else ", not scored",
                    ("Failure means: %s. " % rule) if rule else "", ("Grader said: %s" % why) if why else ""))
    return lines


def scoreboard_md(s: Dict[str, Any], round_md: str = "") -> str:
    rpc = "/".join(str(x) for x in s["runs_per_case"]) or "-"
    total_runs = sum(a["runs"] for c in s["cases"] for a in c["arms"].values())
    head = [
        "# showtime behaviour scoreboard",
        "",
        "Run %s with `claude plugin eval` (Claude Code %s) on %s: agent model %s, judge %s, %s run%s per case per arm, "
        "%s, %s in all, %s at list price (agents and judges), %s." % (
            s["date"] or "(date not recorded)", s["claude_version"] or "?", s["plugin"] or "the plugin",
            s["model"], s["judge"], rpc, "" if rpc == "1" else "s", _n(len(s["cases"]), "case"),
            _n(total_runs, "run"), _usd(s["cost"]),
            ("%d min" % round((s["duration_s"] or 0) / 60.0)) if s["duration_s"] else "time not recorded"),
        "",
    ]
    if s["partial"]:
        head += ["**Partial run** (%s): cases or runs are missing; read the numbers as incomplete." % s["partial_reason"], ""]
    head += [
        "What this measures: how Claude Code behaves on one-sentence requests with showtime installed and with no "
        "plugin at all (the eval's baseline arm: same model, same prompt, same read-only tools). It does not measure "
        "video quality; nothing is rendered (see the full benchmark for that). A run passes when every scored grader "
        "passes; regex and tool-call graders run first, a model grader (3 votes, 2 to pass) only where a pattern cannot "
        "decide. \"Skill fired\" is reported, not scored.",
        "",
        "## Per case",
        "",
        "| Case | Checks | With showtime | Without | Δ score | Skill fired | Tokens / run (with, without) "
        "| Agent cost / run (with, without) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in s["cases"]:
        w, wo = c["arms"].get("with") or {}, c["arms"].get("without") or {}
        fired = w.get("fired")
        head.append("| `%s` | %s | %s | %s | %s | %s | %s, %s | %s, %s |" % (
            c["name"], _kind(c["tags"]), _pct(w.get("passed", 0), w.get("runs", 0)),
            _pct(wo.get("passed", 0), wo.get("runs", 0)) if wo else "-",
            "-" if c["delta"] is None else "%+.2f" % c["delta"],
            _pct(*fired) if fired else "-",
            _tok(w.get("tokens")), _tok(wo.get("tokens")) if wo else "-",
            _usd(w.get("agent_cost")), _usd(wo.get("agent_cost")) if wo else "-"))
    head += ["", "## By kind", "", "| Kind | Cases | With showtime | Without |", "|---|---|---|---|"]
    for label, k, n, kw, nw, cases in kind_rows(s):
        head.append("| %s | %d | %s | %s |" % (label, cases, _pct(k, n), _pct(kw, nw)))
    fails = what_failed(s)
    head += ["", "## What failed", ""] + (fails or ["Nothing: every scored grader passed in every run."])
    head += ["", "## Runs", "",
             "| Case | Arm | Run | Pass | Score | Turns | Tokens | Peak context | Agent $ | List $ (usage.py) | Judge $ | Error |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in s["cases"]:
        for arm, _ in ARMS:
            a = c["arms"].get(arm)
            for r in (a or {}).get("records", []):
                u = r["usage"]
                head.append("| `%s` | %s | %d | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                    c["name"], arm, r["i"], "yes" if r["passed"] else "no",
                    "-" if r["score"] is None else "%.2f" % r["score"], r["turns"] if r["turns"] is not None else "-",
                    _tok((u.get("tokens") or {}).get("total")), _tok(u.get("ctx_max")) if u.get("recorded") else "-",
                    _usd(r["agent_cost"]), _usd(u.get("cost_list")), _usd(r["judge_cost"]),
                    (r["error"] or "").replace("|", "/")))
    head += ["", "Tokens are input + output + cache reads + cache writes, from each run's trace; \"not recorded\" means "
             "the trace was not kept (run the eval with `--keep-temp`). Agent cost is the eval's per-run cost minus "
             "its judge cost; the list-price column recomputes it from the tokens with the dated price table in "
             "`skills/showtime/lib/st/job/usage.py` (prices as of %s). A plan does not pay per run; the figures say "
             "what the work weighs." % usage.PRICES_AS_OF]
    if round_md:
        head += ["", round_md]
    head += ["", "## Rerun it", "", "See `benchmarks/plugin-eval/README.md` (one command: the eval, then this scoreboard)."]
    return "\n".join(head) + "\n"


def kind_rows(s: Dict[str, Any]) -> List[Tuple[str, int, int, int, int, int]]:
    """(label, passed with, runs with, passed without, runs without, cases) per README row."""
    rows = []
    trig = [c for c in s["cases"] if "trigger" in c["tags"]]
    fired = [c["arms"]["with"]["fired"] for c in trig if c["arms"].get("with", {}).get("fired")]
    rows.append(("Skill fires on a video request", sum(f[0] for f in fired), sum(f[1] for f in fired), 0, 0, len(trig)))
    for label, tag in KINDS:
        cs = [c for c in s["cases"] if tag in c["tags"]]
        w = [c["arms"].get("with") or {} for c in cs]
        wo = [c["arms"].get("without") or {} for c in cs]
        rows.append((label, sum(a.get("passed", 0) for a in w), sum(a.get("runs", 0) for a in w),
                     sum(a.get("passed", 0) for a in wo), sum(a.get("runs", 0) for a in wo), len(cs)))
    w = [c["arms"].get("with") or {} for c in s["cases"]]
    wo = [c["arms"].get("without") or {} for c in s["cases"]]
    rows.append(("All cases", sum(a.get("passed", 0) for a in w), sum(a.get("runs", 0) for a in w),
                 sum(a.get("passed", 0) for a in wo), sum(a.get("runs", 0) for a in wo), len(s["cases"])))
    return rows


def readme_block(s: Dict[str, Any], link: str = SCOREBOARD_LINK) -> str:
    lines = [START, "", "| Behaviour | Cases | With showtime | Without (same model, no plugin) |", "|---|---|---|---|"]
    for label, k, n, kw, nw, cases in kind_rows(s):
        lines.append("| %s | %d | %s | %s |" % (label, cases, _pct(k, n), "-" if label.startswith("Skill fires") else _pct(kw, nw)))
    tok_w = _median([x["usage"].get("tokens", {}).get("total") for c in s["cases"] for x in (c["arms"].get("with") or {}).get("records", [])])
    tok_wo = _median([x["usage"].get("tokens", {}).get("total") for c in s["cases"] for x in (c["arms"].get("without") or {}).get("records", [])])
    rpc = "/".join(str(x) for x in s["runs_per_case"]) or "-"
    lines += ["", "`claude plugin eval`, %s, %s, agent %s, judge %s, %s run%s per case per arm; median tokens per run %s with "
              "showtime, %s without; the whole run cost %s at list price. Every case, every failure and how to rerun it: "
              "[SCOREBOARD.md](%s)." % (s["date"], s["plugin"] or "showtime", s["model"], s["judge"], rpc,
                                        "" if rpc == "1" else "s", _tok(tok_w), _tok(tok_wo), _usd(s["cost"]), link),
              "", END]
    return "\n".join(lines)


def update_readme(readme: Path, block: str) -> None:
    text = readme.read_text(encoding="utf-8")
    i, j = text.find(START), text.find(END)
    if i < 0 or j < i or text.count(START) != 1 or text.count(END) != 1:
        raise SystemExit("%s needs exactly one %s ... %s block" % (readme, START, END))
    readme.write_text(text[:i] + block + text[j + len(END):], encoding="utf-8")


# ------------------------------------------------------------------ the full benchmark's latest round

def find_round(spec: str) -> Optional[Path]:
    """A round's results.json: a path, a run name in the bench home, or 'latest' (the newest one there)."""
    p = Path(spec).expanduser()
    if p.is_file():
        return p
    if p.is_dir() and (p / "results.json").is_file():
        return p / "results.json"
    sys.path.insert(0, str(BENCH / "harness"))
    try:
        import common  # noqa: E402
        runs = common.bench_home() / "runs"
    except (ImportError, SystemExit):
        return None
    if spec == "latest":
        found = sorted(runs.glob("*/results.json"), key=lambda f: f.stat().st_mtime)
        return found[-1] if found else None
    f = runs / spec / "results.json"
    return f if f.is_file() else None


def round_section(results: Path) -> str:
    d = json.loads(results.read_text(encoding="utf-8"))
    rows = ["## Full benchmark, round %s" % d.get("run", results.parent.name), "",
            "The video-quality benchmark (`benchmarks/README.md`): automatic checks, invented-claim checks and blind "
            "judges on rendered videos. Aggregated %s." % str(d.get("created") or "")[:10], "",
            "| Arm | Delivered | Spec | Invented claims | Judge rank | Judge win | Human win | Median cost |",
            "|---|---|---|---|---|---|---|---|"]
    fmt = lambda v: "-" if v is None else ("%.2f" % v if isinstance(v, float) else str(v))
    for arm, v in sorted((d.get("per_arm") or {}).items()):
        rows.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            arm, fmt(v.get("delivered")), fmt(v.get("spec")), fmt(v.get("invented")), fmt(v.get("judge_rank")),
            fmt(v.get("judge_win")), fmt(v.get("human_win")), _usd(v.get("cost_med_usd"))))
    return "\n".join(rows)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("output_dir", help="the eval's --output-dir (or its aggregate-result.json)")
    ap.add_argument("-o", "--out", help="SCOREBOARD.md path (default <output dir>/SCOREBOARD.md)")
    ap.add_argument("--round", help="add the full benchmark's round: latest, a run name, or a results.json path")
    ap.add_argument("--readme", action="store_true", help="print the README's short table (with its markers)")
    ap.add_argument("--update", metavar="README", help="with --readme: replace the block between the markers in this file")
    ap.add_argument("--link", default=SCOREBOARD_LINK, help="where the README's short table links (default %(default)s)")
    ap.add_argument("--no-collect", action="store_true", help="do not copy kept traces into <output dir>/traces/")
    a = ap.parse_args(argv)
    res, out_dir = load_result(Path(a.output_dir))
    if not a.no_collect:
        collect_traces(res, out_dir)
    s = summarize(res, out_dir)
    if a.readme:
        block = readme_block(s, a.link)
        if a.update:
            update_readme(Path(a.update), block)
            print("updated %s" % a.update)
        else:
            print(block)
        return 0
    round_md = ""
    if a.round:
        f = find_round(a.round)
        round_md = round_section(f) if f else "## Full benchmark\n\nNo round results found for %r." % a.round
    out = Path(a.out) if a.out else out_dir / "SCOREBOARD.md"
    out.write_text(scoreboard_md(s, round_md), encoding="utf-8")
    for label, k, n, kw, nw, cases in kind_rows(s):
        print("%-50s with %-12s without %s" % (label, _pct(k, n), _pct(kw, nw) if nw else "-"))
    print("wrote %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

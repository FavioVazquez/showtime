#!/usr/bin/env python3
"""Aggregate one benchmark round into results.json and a Markdown report (from report/TEMPLATE.md).

    python benchmarks/scoring/aggregate.py --run r1 [--out report.md]

Headline numbers, per arm (all tasks pooled, then per task):
  delivered        share of tasks with a playable deliverable of the right kind
  spec             mean share of the task's format checks met (duration, aspect, audio, voice, captions...)
  qa_fail / warn   mean `showtime qa` FAIL / WARN findings per deliverable
  invented         mean invented claims (unsupported + contradicted) per deliverable
  judge_win        blind pairwise win rate (ties = 0.5) and Bradley-Terry log strength
  judge_rank       blind ranking judge (rank.py): mean rank score, 1 = ranked first, 0 = ranked last
  human_win        blind human A/B win rate (if votes were imported)
  ttfo / wall      median time to first output / wall time, seconds
  cost / turns     median USD and turns; questions asked in total
Nothing is dropped: failed and capped runs count as "not delivered" and appear in the per-run table.
"""
import argparse
import json
import statistics
import string
import sys
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))
import auto_metrics  # noqa: E402
import common  # noqa: E402


def med(xs: List) -> object:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.median(xs), 1) if xs else None


def mean(xs: List) -> object:
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(sum(xs) / len(xs), 3) if xs else None


def collect(run: str) -> Dict:
    rows = []
    for rd in auto_metrics.run_dirs(run, None, None):
        meta = common.read_json(rd / "meta.json") or {}
        auto = common.read_json(rd / "score" / "auto.json") or {}
        fc = common.read_json(rd / "score" / "factcheck.json") or {}
        qa = auto.get("qa") or {}
        rows.append({
            "task": rd.parent.name, "arm": rd.name, "delivered": bool(auto.get("produced")),
            "spec": auto.get("spec_score"), "spec_detail": auto.get("spec"),
            "qa_verdict": qa.get("verdict"), "qa_fail": (qa.get("summary") or {}).get("fail"),
            "qa_warn": (qa.get("summary") or {}).get("warn"), "lufs": (qa.get("loudness") or {}).get("integrated_lufs"),
            "invented": fc.get("invented"), "footage": auto.get("footage"), "html": (auto.get("html") or {}).get("offline"),
            "ttfo_s": meta.get("ttfo_s"), "wall_s": meta.get("wall_s"), "cost_usd": meta.get("cost_usd"),
            "turns": meta.get("num_turns"), "questions": meta.get("questions"), "capped": meta.get("capped"),
            "is_error": meta.get("is_error"), "tokens_out": (meta.get("tokens") or {}).get("output_tokens"),
            "skills_invoked": meta.get("skills_invoked"), "integrity_ok": (meta.get("integrity") or {}).get("operator_state_unchanged"),
        })
    return {"rows": rows}


def per_arm(rows: List[Dict], pw: Dict, human: Dict, rk: Dict = None) -> Dict:
    arms = sorted({r["arm"] for r in rows})
    hp = {}
    for p in (human or {}).get("pairs", []):
        if not p.get("a") or not p.get("b"):
            continue
        s = 0.5 if p["winner"] == "tie" else (1.0 if p["winner"] == p["a"] else 0.0)
        for arm, pts in ((p["a"], s), (p["b"], 1 - s)):
            hp.setdefault(arm, []).append(pts)
    out = {}
    for a in arms:
        rs = [r for r in rows if r["arm"] == a]
        dl = [r for r in rs if r["delivered"]]
        out[a] = {
            "runs": len(rs), "delivered": round(len(dl) / len(rs), 3) if rs else 0,
            "spec": mean([r["spec"] for r in rs]), "qa_fail": mean([r["qa_fail"] for r in dl]),
            "qa_warn": mean([r["qa_warn"] for r in dl]), "invented": mean([r["invented"] for r in dl]),
            "judge_win": (pw.get("win_rate") or {}).get(a), "judge_rank": ((rk or {}).get("rank_score") or {}).get(a),
            "judge_bt": (pw.get("bradley_terry_log_strength") or {}).get(a),
            "human_win": mean(hp.get(a, [])), "human_rating": mean((human or {}).get("ratings", {}).get(a, [])),
            "ttfo_med_s": med([r["ttfo_s"] for r in rs]), "wall_med_s": med([r["wall_s"] for r in rs]),
            "cost_med_usd": med([r["cost_usd"] for r in rs]), "cost_total_usd": round(sum(r["cost_usd"] or 0 for r in rs), 2),
            "turns_med": med([r["turns"] for r in rs]), "questions_total": sum(r["questions"] or 0 for r in rs),
            "capped": sum(1 for r in rs if r["capped"]), "integrity_ok": all(r["integrity_ok"] is not False for r in rs),
        }
    return out


def table(headers: List[str], rows: List[List]) -> str:
    fmt = lambda v: "-" if v is None else ("%.2f" % v if isinstance(v, float) else str(v))
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(fmt(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--out", help="report path (default <bench home>/runs/<run>/report.md)")
    a = ap.parse_args()
    root = common.bench_home() / "runs" / a.run
    data = collect(a.run)
    pw = common.read_json(root / "pairwise_summary.json", {}) or {}
    human = common.read_json(root / "human_summary.json", {}) or {}
    rk = common.read_json(root / "rank_summary.json", {}) or {}
    arms = per_arm(data["rows"], pw, human, rk)
    arm_labels = {x["id"]: x["label"] for x in common.load_arms()["arms"]}
    res = {"run": a.run, "created": common.now_iso(), "per_arm": arms, "pairwise": pw, "ranking": rk, "human": human,
           "rows": data["rows"]}
    common.write_json(root / "results.json", res)
    headline = table(["arm", "delivered", "spec", "qa FAIL", "qa WARN", "invented", "judge win", "BT", "judge rank", "human win",
                      "TTFO s", "wall s", "cost $ (med)", "turns", "questions", "capped"],
                     [[arm_labels.get(k, k), v["delivered"], v["spec"], v["qa_fail"], v["qa_warn"], v["invented"],
                       v["judge_win"], v["judge_bt"], v["judge_rank"], v["human_win"], v["ttfo_med_s"], v["wall_med_s"], v["cost_med_usd"],
                       v["turns_med"], v["questions_total"], v["capped"]] for k, v in arms.items()])
    runs = table(["task", "arm", "delivered", "spec", "qa", "LUFS", "invented", "TTFO s", "wall s", "$", "turns", "questions", "capped"],
                 [[r["task"], r["arm"], r["delivered"], r["spec"], r["qa_verdict"], r["lufs"], r["invented"], r["ttfo_s"],
                   r["wall_s"], r["cost_usd"], r["turns"], r["questions"], r["capped"]] for r in data["rows"]])
    pt = pw.get("per_task") or {}
    per_task = table(["task"] + sorted(arms), [[t] + [d.get(x) for x in sorted(arms)] for t, d in sorted(pt.items())])
    rt = rk.get("per_task") or {}
    ranking = table(["task"] + sorted(arms), [[t] + [(d.get(x) or {}).get("mean_rank") for x in sorted(arms)]
                                              for t, d in sorted(rt.items())]) if rt else "(no ranking judge in this round)"
    tmpl = string.Template((common.BENCH / "report" / "TEMPLATE.md").read_text(encoding="utf-8"))
    md = tmpl.safe_substitute(run=a.run, created=res["created"], headline=headline, per_task=per_task, runs=runs,
                              judgments=pw.get("judgments", 0), first_pos=pw.get("first_position_win_rate"),
                              ranking=ranking, rank_judgments=rk.get("judgments", 0),
                              rank_first=rk.get("first_position_top_rate"), rank_expected=rk.get("first_position_expected"),
                              integrity="all runs left the operator's Claude Code settings and skills untouched"
                              if all(v["integrity_ok"] for v in arms.values()) else "INTEGRITY PROBLEM: see results.json")
    out = Path(a.out) if a.out else root / "report.md"
    out.write_text(md, encoding="utf-8")
    print(headline)
    print("\nreport: %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

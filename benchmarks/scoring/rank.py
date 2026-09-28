#!/usr/bin/env python3
"""Blind ranking judge: per task, one judge sees every delivered output at once and ranks them.

    python benchmarks/scoring/rank.py --run r1 [--task t2] [--judges 1] [--seed 5] [-j 3]

A cheaper alternative to pairwise.py when each task has only a few arms (every pair x 3 judges grows fast).
Blinding and position
  - One packet per judgment with neutral folders video-1 .. video-N (the same contents as a pairwise side:
    frames, metrics.json with output properties only, transcript.txt). No arm names, paths or process data.
  - The order is shuffled per task (seeded), and judge k sees it rotated by k, so with N judges every arm
    is shown in every position once. The key is stored only in the results file.
  - Every judge is a fresh headless session with only the Read tool.
Output: <bench home>/runs/<run>/rank.jsonl (one line per judgment) and rank_summary.json:
  per_task   {task: {arm: {"mean_rank", "rank_score", "scores"}}}   rank_score = (N - rank) / (N - 1), 1 = best
  rank_score {arm: mean rank_score over its tasks}
  first_position_top_rate   how often video-1 was ranked first (bias check; 1/N is ideal)
"""
import argparse
import json
import random
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))
import auto_metrics  # noqa: E402
import common  # noqa: E402
import judge  # noqa: E402
from pairwise import CRITERIA, build_side, html_recording, is_html  # noqa: E402

PROMPT = """You are a senior video editor judging {n} finished deliverables made for the same request.
You do not know who or what made them; judge only what is in front of you.

The request was:
  "{request}"

Read everything in {folders}: frames/ (a contact sheet and key stills in time order), metrics.json
(duration, size, aspect, audio loudness, automatic QA findings) and transcript.txt (what is spoken, from
automatic speech recognition). You cannot play the videos; infer motion and pacing from the frame sequence
and timing, and sound from the transcript and loudness numbers. Look at every frame image listed below;
set saw_frames to false if any of them would not open (then the judgment is not used).

Score each 1-10 on: brief_fit (did it do what was asked: length, format, content), visual_craft
(composition, typography, colour, hierarchy), legibility (text readable at phone size, contrast),
motion_and_pacing, audio (voice, music, levels; 1 if the request needed sound and there is none),
accuracy (no wrong or invented facts; correct maths or data), polish (no glitches, black/frozen frames,
cut-off text, placeholder content). Then rank all {n} from the one you would ship first to the one you
would ship last (no ties). Ignore file size and render speed. Do not favour any position. Answer only
with the JSON."""


def schema(n: int) -> Dict:
    labels = [str(i + 1) for i in range(n)]
    crit = {"type": "object", "properties": {c: {"type": "integer", "minimum": 1, "maximum": 10} for c in CRITERIA},
            "required": CRITERIA}
    return {
        "type": "object",
        "properties": {
            "ranking": {"type": "array", "items": {"type": "string", "enum": labels}, "minItems": n, "maxItems": n},
            "confidence": {"type": "integer", "minimum": 1, "maximum": 5},
            "scores": {"type": "object", "properties": {l: crit for l in labels}, "required": labels},
            "reason": {"type": "string"},
            "saw_frames": {"type": "boolean"},
        },
        "required": ["ranking", "confidence", "scores", "reason", "saw_frames"],
    }


def orders(arms: List[str], judges: int, rng: random.Random) -> List[List[str]]:
    base = sorted(arms)
    rng.shuffle(base)
    return [base[k % len(base):] + base[:k % len(base)] for k in range(judges)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--task")
    ap.add_argument("--judges", type=int, default=1, help="judgments per task (default 1)")
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("-j", "--jobs", type=int, default=3, help="judgments in parallel (default 3)")
    a = ap.parse_args()
    root = common.bench_home() / "runs" / a.run
    out_path = root / "rank.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                j = json.loads(line)
                if j.get("ok"):
                    done.add((j["task"], j["judge"]))
    rng = random.Random(a.seed)
    by_task: Dict[str, Dict[str, Dict]] = {}
    for rd in auto_metrics.run_dirs(a.run, a.task, None):
        auto = common.read_json(rd / "score" / "auto.json") or {}
        if auto.get("produced"):
            by_task.setdefault(rd.parent.name, {})[rd.name] = auto
    jobs = []
    for task_id, arms in sorted(by_task.items()):
        if len(arms) < 2:
            common.log("%s: only %d delivered output(s), nothing to rank" % (task_id, len(arms)))
            continue
        task = common.load_tasks([task_id])[0]
        for k, order in enumerate(orders(list(arms), a.judges, rng)):
            if (task_id, k) not in done:
                jobs.append((task, arms, k, order))
    lock = threading.Lock()

    def judge_one(job):
        task, arms, k, order = job
        task_id = task["id"]
        pk = common.ws_root() / "judge-packets" / ("rk-" + common.opaque("%s/%s/%d" % (a.run, task_id, k), 10))
        if pk.exists():
            shutil.rmtree(pk)
        for i, arm in enumerate(order):
            build_side(pk / ("video-%d" % (i + 1)), arms[arm], html_recording(a.run, task_id, arm) if is_html(arms[arm]) else None)
        n = len(order)
        folders = ", ".join("video-%d/" % (i + 1) for i in range(n))
        res = judge.ask(pk, PROMPT.format(n=n, request=task["prompt"], folders=folders) + "\n\n" + judge.frames_prompt(pk),
                        schema(n))
        # a ranking made without looking at the pictures does not count (seen in r1/r2: the judge guessed
        # file names, found none and ranked from numbers and transcripts)
        blind = judge.check_seen(res, pk, ["video-%d" % (i + 1) for i in range(n)]) if res.get("ok") else None
        if blind:
            res.update(ok=False, error=blind)
        rec = {"task": task_id, "judge": k, "order": order, "ok": res.get("ok"), "cost_usd": res.get("cost_usd"),
               "error": res.get("error"), "images_read": len(res.get("read") or [])}
        if res.get("ok"):
            d = res["data"]
            rk = [str(x) for x in d.get("ranking") or []]
            if sorted(rk) != [str(i + 1) for i in range(n)]:
                rec.update(ok=False, error="ranking is not a permutation: %s" % rk)
            else:
                rec["ranking"] = [order[int(x) - 1] for x in rk]
                rec["first_ranked_position"] = int(rk[0])
                rec["confidence"] = d.get("confidence")
                rec["scores"] = {order[int(l) - 1]: v for l, v in (d.get("scores") or {}).items() if l.isdigit()
                                 and 1 <= int(l) <= n}
                rec["reason"] = (d.get("reason") or "")[:1500]
        with lock, open(out_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        common.log("%s judge %d -> %s" % (task_id, k, rec.get("ranking", rec.get("error"))))

    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        list(ex.map(judge_one, jobs))
    failed = []
    if out_path.exists():
        print(json.dumps(summarize(root), indent=2))
        latest = {}
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                j = json.loads(line)
                latest[(j["task"], j["judge"])] = j
        failed = [j for j in latest.values() if not j.get("ok")]
    for j in failed:
        common.log("FAILED %s judge %s: %s" % (j["task"], j["judge"], j.get("error")))
    return 1 if failed else 0


def summarize(root: Path) -> Dict:
    recs = [json.loads(l) for l in (root / "rank.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    recs = [r for r in recs if r.get("ok") and r.get("ranking")]
    per_task: Dict[str, Dict[str, Dict]] = {}
    top_first, n_sum = 0, 0.0
    for r in recs:
        n = len(r["ranking"])
        top_first += r.get("first_ranked_position") == 1
        n_sum += 1.0 / n
        for pos, arm in enumerate(r["ranking"]):
            e = per_task.setdefault(r["task"], {}).setdefault(arm, {"ranks": [], "scores": []})
            e["ranks"].append(pos + 1)
            e["scores"].append((n - 1 - pos) / (n - 1))
            s = (r.get("scores") or {}).get(arm)
            if s:
                e.setdefault("criteria", []).append(s)
    out_task, pooled = {}, {}
    for t, d in per_task.items():
        out_task[t] = {}
        for arm, e in d.items():
            crit = {}
            for c in CRITERIA:
                xs = [x.get(c) for x in e.get("criteria", []) if isinstance(x.get(c), (int, float))]
                if xs:
                    crit[c] = round(sum(xs) / len(xs), 2)
            rs = round(sum(e["scores"]) / len(e["scores"]), 3)
            out_task[t][arm] = {"mean_rank": round(sum(e["ranks"]) / len(e["ranks"]), 2), "rank_score": rs,
                                "judgments": len(e["ranks"]), "scores": crit}
            pooled.setdefault(arm, []).append(rs)
    summary = {"judgments": len(recs), "per_task": out_task,
               "rank_score": {a: round(sum(v) / len(v), 3) for a, v in sorted(pooled.items())},
               "first_position_top_rate": round(top_first / len(recs), 3) if recs else None,
               "first_position_expected": round(n_sum / len(recs), 3) if recs else None}
    common.write_json(root / "rank_summary.json", summary)
    return summary


if __name__ == "__main__":
    sys.exit(main())

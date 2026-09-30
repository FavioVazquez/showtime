#!/usr/bin/env python3
"""Blind pairwise judging: for every task, every pair of arms that delivered, 3 independent judges.

    python benchmarks/scoring/pairwise.py --run r1 [--task t2] [--judges 3] [--seed 7]

Blinding
  - Each judgment gets its own packet folder with neutral names: video-1/ and video-2/ (frames, contact
    sheet, a metrics.json with only output properties, and the automatic transcript). No arm names, no
    paths, no process data (time, cost, questions are reported separately and never judged).
  - Which arm is "1" is decided per judgment: judges alternate the order (AB, BA, AB for one pair and
    BA, AB, BA for the next) so each arm is shown first equally often overall; the key is stored only in
    the results file.
  - Every judge is a fresh headless session with only the Read tool.
  - A judgment counts only with proof that the judge looked at every image (see rank.py and judge.py).
Output: <bench home>/runs/<run>/pairwise.jsonl (one line per judgment) and pairwise_summary.json
(win rate per arm with ties = 0.5, Bradley-Terry strengths, first-position win rate as a bias check, and
"both_orders": per task and pair, the arm that won when shown first AND when shown second, else "split" or
"tie"; a pair judged in one order only says so, as with --judges 1).
"""
import argparse
import itertools
import json
import math
import random
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))
import auto_metrics  # noqa: E402
import common  # noqa: E402
import judge  # noqa: E402

CRITERIA = ["brief_fit", "visual_craft", "legibility", "motion_and_pacing", "audio", "accuracy", "polish"]
SCHEMA = {
    "type": "object",
    "properties": {
        "winner": {"type": "string", "enum": ["1", "2", "tie"]},
        "confidence": {"type": "integer", "minimum": 1, "maximum": 5},
        "scores": {"type": "object", "properties": {
            "1": {"type": "object", "properties": {c: {"type": "integer", "minimum": 1, "maximum": 10} for c in CRITERIA},
                  "required": CRITERIA},
            "2": {"type": "object", "properties": {c: {"type": "integer", "minimum": 1, "maximum": 10} for c in CRITERIA},
                  "required": CRITERIA}}, "required": ["1", "2"]},
        "reason": {"type": "string"},
        "saw_frames": {"type": "boolean"},
    },
    "required": ["winner", "confidence", "scores", "reason", "saw_frames"],
}

PROMPT = """You are a senior video editor judging two finished deliverables made for the same request.
You do not know who or what made them; judge only what is in front of you.

The request was:
  "{request}"

Read everything in video-1/ and video-2/: frames/ (a contact sheet and key stills in time order),
metrics.json (duration, size, aspect, audio loudness, automatic QA findings) and transcript.txt (what is
spoken, from automatic speech recognition). You cannot play the videos; infer motion and pacing from the
frame sequence and timing, and sound from the transcript and loudness numbers. Look at every frame image
listed below; set saw_frames to false if any of them would not open (then the judgment is not used).

Score each 1-10 on: brief_fit (did it do what was asked: length, format, content), visual_craft
(composition, typography, colour, hierarchy), legibility (text readable at phone size, contrast),
motion_and_pacing, audio (voice, music, levels; 1 if the request needed sound and there is none),
accuracy (no wrong or invented facts; correct maths or data), polish (no glitches, black/frozen frames,
cut-off text, placeholder content). Then pick the one you would ship, or "tie" only if you truly cannot
choose. Ignore file size and render speed. Do not favour either position. Answer only with the JSON."""


def metrics_view(auto: Dict) -> Dict:
    pr = auto.get("probe") or {}
    v = pr.get("video") or {}
    qa = auto.get("qa") or {}
    return {"duration_s": round(pr.get("duration") or 0, 2), "width": v.get("width"), "height": v.get("height"),
            "fps": v.get("fps"), "has_audio": bool(pr.get("audio")),
            "loudness": qa.get("loudness"), "qa_findings": [f"{f['severity']}: {f['message']}" for f in qa.get("findings", [])],
            "captions_file": bool(auto.get("captions_sidecar")), "html": auto.get("html") and {
                k: auto["html"].get(k) for k in ("bytes", "offline", "single_file", "animates", "phone_overflow", "media")}}


def is_html(auto: Dict) -> bool:
    return bool(auto.get("html")) and not (auto.get("probe") or {}).get("video")


_REC_GUARD = threading.Lock()
_REC_LOCKS: Dict[str, threading.Lock] = {}


def html_recording(run: str, task_id: str, arm: str) -> Optional[Path]:
    """The screen recording human_board.py makes of an HTML deliverable (played like a viewer would), made
    now when the boards were not built yet. None when the page could not be recorded.
    One recording per file at a time: parallel judges of one task used to record the same page into the same
    file at once (round 4 dry run: a corrupt recording)."""
    rec = common.bench_home() / "human" / run / "recordings" / task_id / (arm + ".mp4")
    with _REC_GUARD:
        lock = _REC_LOCKS.setdefault(str(rec), threading.Lock())
    with lock:
        return _html_recording(run, task_id, arm, rec)


def _html_recording(run: str, task_id: str, arm: str, rec: Path) -> Optional[Path]:
    import human_board
    rep = common.read_json(rec.with_suffix(".json")) or {}
    if rec.exists() and (rep.get("report") or {}).get("ok"):
        return rec
    rd = common.bench_home() / "runs" / run / task_id / arm
    meta = common.read_json(rd / "meta.json") or {}
    try:
        src = Path(meta["workspace"]) / meta["deliverable"]["primary"]
    except (KeyError, TypeError):
        return None
    if not src.is_file():
        return None
    out = human_board.record_html(src, rec, False)
    return rec if out.get("ok") and rec.exists() else None


def stills_from(video: Path, dst: Path, n: int = 8) -> List[tuple]:
    """A contact sheet and n evenly spaced stills of a video -> [(file name, label)]."""
    dur = float((common.probe(video) or {}).get("duration") or 0)
    if dur <= 0:
        return []
    out = []
    sheet = dst / "00.jpg"
    step = dur / n
    common.run([common.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-vf",
                "fps=%.6f,scale=480:-2,tile=4x%d" % (1.0 / step, (n + 3) // 4), "-frames:v", "1", "-q:v", "4", str(sheet)])
    if sheet.exists():
        out.append((sheet.name, "contact sheet, %d stills every %.1f s" % (n, step)))
    for i in range(n):
        t = (i + 0.5) * step
        f = dst / ("%02d.jpg" % (i + 1))
        common.run([common.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", "%.3f" % t, "-i", str(video),
                    "-frames:v", "1", "-vf", "scale=1280:-2", "-q:v", "3", str(f)])
        if f.exists():
            out.append((f.name, "still at %.1f s" % t))
    return out


def build_side(dst: Path, auto: Dict, recording: Optional[Path] = None) -> None:
    """One neutral side of a judge packet. An HTML deliverable is judged from its screen recording (stills
    of the page playing), not from screenshots taken before playback, which all show the start screen."""
    (dst / "frames").mkdir(parents=True)
    index = []
    if recording is not None and Path(recording).exists():
        index = stills_from(Path(recording), dst / "frames")
    if not index:
        fr = auto.get("frames") or {}
        imgs = ([fr["sheet"]] if fr.get("sheet") else []) + list(fr.get("key") or [])
        for i, p in enumerate(imgs):
            if p and Path(p).exists():
                name = "%02d%s" % (i, Path(p).suffix)
                shutil.copy2(p, dst / "frames" / name)
                index.append((name, "contact sheet" if (i == 0 and fr.get("sheet")) else "key still"))
    (dst / "frames" / "INDEX.txt").write_text("".join("%s %s\n" % x for x in index), encoding="utf-8")
    common.write_json(dst / "metrics.json", metrics_view(auto))
    (dst / "transcript.txt").write_text(((auto.get("asr") or {}).get("text") or "(no speech detected or not transcribed)") + "\n",
                                        encoding="utf-8")


def bradley_terry(arms: List[str], games: List[tuple], iters: int = 200) -> Dict[str, float]:
    """games: (a, b, score_a) with score_a in {1, 0.5, 0}. MM algorithm, strengths normalised to mean 1."""
    p = {a: 1.0 for a in arms}
    wins = {a: 0.0 for a in arms}
    for a, b, s in games:
        wins[a] += s
        wins[b] += 1 - s
    for _ in range(iters):
        new = {}
        for i in arms:
            den = sum((1.0 / (p[i] + p[j])) for a, b, _ in games for (x, j) in ((a, b), (b, a)) if x == i)
            new[i] = (wins[i] + 0.1) / den if den else p[i]
        m = sum(new.values()) / len(new)
        p = {k: v / m for k, v in new.items()}
    return {k: round(math.log(v), 3) for k, v in p.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--task")
    ap.add_argument("--judges", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("-j", "--jobs", type=int, default=3, help="judgments in parallel (default 3)")
    ap.add_argument("--attempts", type=int, default=3,
                    help="a judgment that cannot prove it looked at every frame is asked again, up to N sessions (default 3)")
    a = ap.parse_args()
    root = common.bench_home() / "runs" / a.run
    out_path = root / "pairwise.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            j = json.loads(line)
            done.add((j["task"], j["a"], j["b"], j["judge"]))
    rng = random.Random(a.seed)
    by_task: Dict[str, Dict[str, Dict]] = {}
    for rd in auto_metrics.run_dirs(a.run, a.task, None):
        auto = common.read_json(rd / "score" / "auto.json") or {}
        if auto.get("produced"):
            by_task.setdefault(rd.parent.name, {})[rd.name] = auto
    jobs = []
    for task_id, arms in sorted(by_task.items()):
        task = common.load_tasks([task_id])[0]
        pairs = list(itertools.combinations(sorted(arms), 2))
        rng.shuffle(pairs)
        for pi, (x, y) in enumerate(pairs):
            for k in range(a.judges):
                if (task_id, x, y, k) not in done:
                    first_is_x = (k + pi) % 2 == 0
                    jobs.append((task, arms, x, y, k, (x, y) if first_is_x else (y, x)))
    lock = threading.Lock()

    def judge_one(job):
        task, arms, x, y, k, (one, two) = job
        task_id = task["id"]
        tag = "pw-" + common.opaque("%s/%s/%s/%s/%d" % (a.run, task_id, x, y, k), 10)

        def build() -> Path:
            pk = common.ws_root() / "judge-packets" / tag
            if pk.exists():
                shutil.rmtree(pk)
            for side, arm in (("video-1", one), ("video-2", two)):
                build_side(pk / side, arms[arm], html_recording(a.run, task_id, arm) if is_html(arms[arm]) else None)
            return pk

        # same proof as rank.py: every image opened (tool calls) and its reading-check number reported
        res, attempts = judge.ask_verified(build, lambda pk: PROMPT.format(request=task["prompt"]) + "\n\n" + judge.frames_prompt(pk),
                                           SCHEMA, ["video-1", "video-2"], attempts=a.attempts,
                                           seed="%s/%s/%s/%s/%d/%d" % (a.run, task_id, x, y, k, a.seed))
        rec = {"task": task_id, "a": x, "b": y, "judge": k, "first": one, "ok": res.get("ok"),
               "cost_usd": round(sum(z.get("cost_usd") or 0 for z in attempts), 4), "error": res.get("error"),
               "attempts": attempts}
        if res.get("ok"):
            d = res["data"]
            w = d.get("winner")
            rec["winner"] = "tie" if w == "tie" else (one if w == "1" else two)
            rec["confidence"] = d.get("confidence")
            rec["scores"] = {one: d["scores"]["1"], two: d["scores"]["2"]}
            rec["reason"] = d.get("reason", "")[:1200]
        with lock, open(out_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
        common.log("%s %s vs %s judge %d -> %s" % (task_id, x, y, k, rec.get("winner", rec.get("error"))))

    # judges are API-bound (no local CPU work), so several can run at once
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        list(ex.map(judge_one, jobs))
    summarize(root)
    return 0


def both_orders(recs: List[Dict]) -> Dict[str, Dict[str, str]]:
    """Per task and pair: the arm that won (by majority) in each order it was shown in. It counts as the
    winner only when it won both orders; otherwise "split" (the preference followed the position) or "tie"."""
    seen: Dict[tuple, Dict[str, List[str]]] = {}
    for r in recs:
        seen.setdefault((r["task"], r["a"], r["b"]), {}).setdefault("a_first" if r["first"] == r["a"] else "b_first",
                                                                   []).append(r["winner"])
    out: Dict[str, Dict[str, str]] = {}
    for (task, a, b), d in sorted(seen.items()):
        def major(ws: List[str]) -> str:
            pts = sum(1.0 if w == a else 0.0 if w == b else 0.5 for w in ws) / len(ws)
            return a if pts > 0.5 else b if pts < 0.5 else "tie"
        if len(d) < 2:
            res = "one order only"
        else:
            wa, wb = major(d["a_first"]), major(d["b_first"])
            res = wa if wa == wb and wa != "tie" else ("tie" if wa == wb else "split")
        out.setdefault(task, {})["%s vs %s" % (a, b)] = res
    return out


def summarize(root: Path) -> Dict:
    recs = [json.loads(l) for l in (root / "pairwise.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    recs = [r for r in recs if r.get("ok")]
    arms = sorted({r["a"] for r in recs} | {r["b"] for r in recs})
    games, first_wins, decided = [], 0, 0
    per = {a: {"games": 0, "points": 0.0} for a in arms}
    per_task: Dict[str, Dict[str, Dict]] = {}
    for r in recs:
        s = 0.5 if r["winner"] == "tie" else (1.0 if r["winner"] == r["a"] else 0.0)
        games.append((r["a"], r["b"], s))
        for arm, pts in ((r["a"], s), (r["b"], 1 - s)):
            per[arm]["games"] += 1
            per[arm]["points"] += pts
            t = per_task.setdefault(r["task"], {}).setdefault(arm, {"games": 0, "points": 0.0})
            t["games"] += 1
            t["points"] += pts
        if r["winner"] != "tie":
            decided += 1
            first_wins += r["winner"] == r["first"]
    summary = {"judgments": len(recs),
               "both_orders": both_orders(recs),
               "win_rate": {a: round(v["points"] / v["games"], 3) for a, v in per.items() if v["games"]},
               "per_task": {t: {a: round(v["points"] / v["games"], 3) for a, v in d.items()} for t, d in per_task.items()},
               "bradley_terry_log_strength": bradley_terry(arms, games) if games else {},
               "first_position_win_rate": round(first_wins / decided, 3) if decided else None}
    common.write_json(root / "pairwise_summary.json", summary)
    return summary


if __name__ == "__main__":
    sys.exit(main())

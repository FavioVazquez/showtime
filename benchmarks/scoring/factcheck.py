#!/usr/bin/env python3
"""Invented-claims check: a blind judge lists every factual claim a deliverable makes (spoken or on screen)
and labels each against the task's source files.

    python benchmarks/scoring/factcheck.py --run smoke-01 [--task t7] [--arm showtime]

Run auto_metrics.py first (it makes the frames and the transcript). Writes score/factcheck.json:
  claims[]      {text, where: spoken|screen, verdict: supported|unsupported|contradicted|not_a_claim, why}
  counts        per verdict; "invented" = unsupported + contradicted
The packet holds only: the request, the source files' text, the transcript, and the frames, under neutral
names. The judge never sees the arm, the workspace or any file path from the run.
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))
import auto_metrics  # noqa: E402
import common  # noqa: E402
import judge  # noqa: E402

SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "where": {"type": "string", "enum": ["spoken", "screen", "both"]},
            "verdict": {"type": "string", "enum": ["supported", "unsupported", "contradicted", "not_a_claim"]},
            "why": {"type": "string"}}, "required": ["text", "where", "verdict", "why"]}},
        "legibility_problems": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["claims", "legibility_problems"],
}

PROMPT = """You are checking a short video for invented claims. You do not know who or what made it.

The person asked for exactly this:
  "{request}"

Everything the video may state as fact must come from the SOURCES folder (or, if there are no sources,
be correct general knowledge; for mathematics, be mathematically correct). Read every file in this folder:
  - SOURCES/*          the only facts the maker was given
  - transcript.txt     what is spoken (automatic transcript; may be empty if there is no voice)
  - frames/*.jpg       stills and a contact sheet of what is on screen, in time order

List every factual claim the video makes, spoken or on screen (numbers, dates, feature names, commands,
comparisons, causes, "first/only/fastest" statements, testimonials, prices, install commands).
Label each:
  supported     stated in or directly computable from SOURCES (or correct maths / common knowledge if no sources)
  unsupported   not in SOURCES and not common knowledge (e.g. an invented speed-up, user count, quote)
  contradicted  conflicts with SOURCES or is wrong
  not_a_claim   slogans, calls to action, opinions ("clean and simple")
Also list on-screen text you could not read at this size (legibility_problems), quoting what you can.
Be strict and literal. Do not reward style. Answer only with the JSON object."""


def packet_for(rdir: Path, task: dict, auto: dict) -> Path:
    pk = common.ws_root() / "judge-packets" / ("fc-" + common.opaque(str(rdir), 10))
    if pk.exists():
        shutil.rmtree(pk)
    (pk / "SOURCES").mkdir(parents=True)
    (pk / "frames").mkdir()
    for f in task.get("facts", []):
        src = common.BENCH / f
        if src.exists():
            shutil.copy2(src, pk / "SOURCES" / src.name)
    (pk / "transcript.txt").write_text(((auto.get("asr") or {}).get("text") or "(no transcript)") + "\n",
                                       encoding="utf-8")
    fr = auto.get("frames") or {}
    imgs = ([fr["sheet"]] if fr.get("sheet") else []) + list(fr.get("key") or [])
    for i, p in enumerate(imgs):
        if p and Path(p).exists():
            shutil.copy2(p, pk / "frames" / ("%02d%s" % (i, Path(p).suffix)))
    return pk


def check(rdir: Path) -> dict:
    auto = common.read_json(rdir / "score" / "auto.json") or {}
    if not auto.get("produced"):
        return {"skipped": "no deliverable"}
    task = common.load_tasks([auto["task"]])[0]
    if task.get("expect", {}).get("footage"):
        return {"skipped": "footage edit: claims are the speaker's own"}
    if (auto.get("asr") or {}).get("text") is None and task.get("expect", {}).get("audio"):
        # make sure spoken claims are visible to the judge even when the task did not need ASR scoring
        v = Path(common.read_json(rdir / "meta.json")["workspace"]) / common.read_json(rdir / "meta.json")["deliverable"]["primary"]
        if v.suffix.lower() in common.VIDEO_EXT and (auto.get("probe") or {}).get("audio"):
            asr = auto_metrics.transcribe(rdir / "score" / "qa-input" / ("deliverable" + v.suffix.lower()), rdir / "score" / "asr")
            auto["asr"] = {"text": (asr or {}).get("text", "")}
    pk = packet_for(rdir, task, auto)
    res = judge.ask(pk, PROMPT.format(request=task["prompt"]), SCHEMA)
    out = {"ok": res.get("ok"), "error": res.get("error"), "cost_usd": res.get("cost_usd")}
    if res.get("ok"):
        claims = res["data"].get("claims", [])
        counts = {}
        for c in claims:
            counts[c.get("verdict")] = counts.get(c.get("verdict"), 0) + 1
        out.update({"claims": claims, "counts": counts,
                    "invented": counts.get("unsupported", 0) + counts.get("contradicted", 0),
                    "legibility_problems": res["data"].get("legibility_problems", [])})
    common.write_json(rdir / "score" / "factcheck.json", out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--task")
    ap.add_argument("--arm")
    a = ap.parse_args()
    for rd in auto_metrics.run_dirs(a.run, a.task, a.arm):
        r = check(rd)
        print("%-18s %-9s invented=%s %s" % (rd.parent.name, rd.name, r.get("invented"), r.get("skipped") or r.get("error") or ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

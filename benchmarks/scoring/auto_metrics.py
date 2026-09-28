#!/usr/bin/env python3
"""Automatic metrics for every run of a benchmark round (same tools, same settings, for every arm).

    python benchmarks/scoring/auto_metrics.py --run smoke-01 [--task t7] [--arm showtime] [--no-asr]

Per run folder (runs/<run>/<task>/<arm>/) it writes score/auto.json with:
  produced         a deliverable of the right kind exists and decodes (full decode, errors counted)
  spec             duration / aspect / audio / captions / voice as the task asked (each true/false/None)
  qa               `showtime qa` on a COPY of the video in a neutral folder, with the task's expect block
                   (loudness, true peak, clipping, silence, black and frozen stretches, frame 0, captions);
                   the same command and thresholds for every arm, so no arm gets its own project context
  asr              local word-level transcript of the deliverable (voice tasks and the footage task)
  footage          (t4) fillers left, content words kept in order, long silences left
  captions_sync    (sidecar captions) median |cue start - spoken word start|
  html             (t6) headless-Chrome probe: network requests, single file, plays, phone overflow
  frames           contact sheet + 6 key frames for the judges (from `showtime snap`)
  process          wall time, time to first output, tokens, cost, turns, questions (copied from meta.json)
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))
import common  # noqa: E402

FILLERS = {"um", "uh", "er", "ah", "erm", "hmm", "mm", "umm", "uhh", "uhm"}


def norm_words(words: List[Dict]) -> List[str]:
    out = []
    for w in words:
        t = re.sub(r"[^a-z0-9']", "", (w.get("word") or w.get("text") or "").lower())
        if t:
            out.append(t)
    return out


def lcs_len(a: List[str], b: List[str]) -> int:
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b):
            cur.append(prev[j] + 1 if x == y else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def transcribe(video: Path, out_dir: Path) -> Optional[Dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    r = common.run([common.SHOWTIME, "transcribe", str(video), "--edit-dir", str(out_dir), "--json"], cwd=str(out_dir))
    js = sorted((out_dir / "transcripts").glob("*.json"))
    if r.returncode != 0 or not js:
        return {"error": (r.stderr or r.stdout)[-600:]}
    d = json.loads(js[0].read_text(encoding="utf-8"))
    return {"text": d.get("text", ""), "words": d.get("words", []), "duration": d.get("duration")}


def parse_srt(path: Path) -> List[Dict]:
    cues = []
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r", "")
    for block in re.split(r"\n\s*\n", text):
        m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)", block)
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0
        body = block[m.end():].strip()
        cues.append({"start": start, "end": end, "text": re.sub(r"<[^>]+>", "", body)})
    return cues


def caption_sync(cues: List[Dict], words: List[Dict]) -> Dict:
    """Median offset between each cue's first word and the same word spoken (searched nearby)."""
    offs = []
    for c in cues:
        first = norm_words([{"word": c["text"].split()[0]}]) if c["text"].split() else []
        if not first:
            continue
        near = [w for w in words if abs(float(w.get("start", 0)) - c["start"]) < 3.0
                and norm_words([w]) == first]
        if near:
            offs.append(min(abs(float(w["start"]) - c["start"]) for w in near))
    offs.sort()
    return {"cues": len(cues), "matched": len(offs),
            "median_offset_s": round(offs[len(offs) // 2], 3) if offs else None,
            "p90_offset_s": round(offs[int(len(offs) * 0.9)], 3) if offs else None}


def decode_errors(video: Path) -> int:
    r = common.run([common.ffmpeg(), "-v", "error", "-i", str(video), "-f", "null", "-"])
    return len([ln for ln in r.stderr.splitlines() if ln.strip()])


def expect_block(task: Dict, pr: Dict) -> Dict:
    ex = task.get("expect", {})
    e = {}
    if ex.get("duration"):
        lo, hi = ex["duration"]
        e["duration"], e["tolerance"] = (lo + hi) / 2.0, (hi - lo) / 2.0
    if ex.get("audio") == "required":
        e["audio"] = True
    if ex.get("lufs") is not None:
        e["lufs"] = ex["lufs"]
    if ex.get("platform"):
        e["platform"] = ex["platform"]
    return e


def score_video(task: Dict, meta: Dict, rdir: Path, video: Path, asr_on: bool) -> Dict:
    ex = task.get("expect", {})
    sd = rdir / "score"
    pr = common.probe(video)
    out: Dict = {"probe": pr, "decode_errors": decode_errors(video)}
    out["produced"] = bool(pr.get("ok") and pr.get("video") and pr.get("duration", 0) > 0.5)
    v = pr.get("video") or {}
    aspect = common.aspect_label(v.get("width") or 0, v.get("height") or 0)
    dur = pr.get("duration") or 0
    has_audio = bool(pr.get("audio"))
    spec = {"aspect": aspect in ex.get("aspect", [aspect]), "aspect_is": aspect}
    if ex.get("duration"):
        spec["duration"] = ex["duration"][0] <= dur <= ex["duration"][1]
    if ex.get("audio") in ("required", "preferred"):
        spec["audio"] = has_audio
    out["spec"] = spec

    # qa on a neutral copy so no arm's project/job metadata changes what is checked
    qin = sd / "qa-input"
    if qin.exists():
        shutil.rmtree(qin)
    qin.mkdir(parents=True)
    copy = qin / ("deliverable" + video.suffix.lower())
    shutil.copy2(video, copy)
    sidecars = []
    for sc in sorted(video.parent.glob("*")):
        if sc.suffix.lower() in (".srt", ".vtt") and sc.stem.split(".")[0] == video.stem.split(".")[0]:
            dst = qin / ("deliverable" + sc.suffix.lower())
            shutil.copy2(sc, dst)
            sidecars.append(dst)
    if not sidecars:  # any caption file the agent wrote in the workspace
        ws = Path(meta["workspace"])
        found = [p for p in ws.rglob("*") if p.suffix.lower() in (".srt", ".vtt") and "node_modules" not in p.parts]
        for sc in found[:1]:
            dst = qin / ("deliverable" + sc.suffix.lower())
            shutil.copy2(sc, dst)
            sidecars.append(dst)
    common.write_json(qin / "expect.json", {"expect": expect_block(task, pr)})
    cmd = [common.SHOWTIME, "qa", str(copy), "--expect", str(qin / "expect.json"), "--json", "-o", str(sd / "qa")]
    if ex.get("platform"):
        cmd += ["--platform", ex["platform"]]
    for sc in sidecars:
        cmd += ["--captions", str(sc)]
    r = common.run(cmd, cwd=str(qin))
    try:
        qa = json.loads(r.stdout)
        out["qa"] = {"verdict": qa.get("verdict"), "summary": qa.get("summary"),
                     "findings": [{"rule": f.get("rule"), "severity": f.get("severity"), "message": f.get("message")}
                                  for f in qa.get("findings", [])],
                     "loudness": {k: (qa.get("loudness") or {}).get(k) for k in
                                  ("integrated_lufs", "true_peak_dbtp", "lra", "silent_gaps")},
                     "clipping": ((qa.get("loudness") or {}).get("clipping") or {}).get("runs"),
                     "detect": qa.get("detect"), "sheet": qa.get("sheet")}
    except ValueError:
        out["qa"] = {"error": (r.stderr or r.stdout)[-800:]}
    out["captions_sidecar"] = [p.name for p in sidecars]

    # frames for the judges
    snap = sd / "frames"
    r = common.run([common.SHOWTIME, "snap", str(copy), "--count", "12", "-o", str(snap), "--json"], cwd=str(qin))
    ts = [round(dur * f, 2) for f in (0.02, 0.2, 0.4, 0.6, 0.8, 0.98)]
    r2 = common.run([common.SHOWTIME, "snap", str(copy), "--at", ",".join(str(t) for t in ts), "--width", "960",
                     "--format", "jpg", "-o", str(snap / "key"), "--json"], cwd=str(qin))
    out["frames"] = {"sheet": next((str(p) for p in snap.glob("*.jpg") if "sheet" in p.name), None),
                     "key": sorted(str(p) for p in (snap / "key").glob("*.jpg")),
                     "error": None if r.returncode == 0 and r2.returncode == 0 else (r.stderr + r2.stderr)[-400:]}

    # speech
    if asr_on and has_audio and (ex.get("voice") or ex.get("footage") or ex.get("captions")):
        asr = transcribe(copy, sd / "asr")
        out["asr"] = {"words": len((asr or {}).get("words") or []), "text": ((asr or {}).get("text") or "")[:3000],
                      "error": (asr or {}).get("error")}
        if ex.get("voice"):
            spec["voice"] = out["asr"]["words"] >= 20
        words = (asr or {}).get("words") or []
        if ex.get("footage"):
            out["footage"] = footage_metrics(task, words, sd)
        if sidecars and sidecars[0].suffix == ".srt":
            out["captions_sync"] = caption_sync(parse_srt(sidecars[0]), words)
    if ex.get("captions") == "required":
        spec["captions"] = bool(sidecars) or None  # None = burned-in or absent: the judges decide from frames
    return out


def lcs_align(a: List[str], b: List[str]) -> Dict[int, int]:
    """Longest-common-subsequence alignment: {index in a: index in b}."""
    n, m = len(a), len(b)
    t = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            t[i][j] = t[i + 1][j + 1] + 1 if a[i] == b[j] else max(t[i + 1][j], t[i][j + 1])
    out, i, j = {}, 0, 0
    while i < n and j < m:
        if a[i] == b[j]:
            out[i] = j
            i, j = i + 1, j + 1
        elif t[i + 1][j] >= t[i][j + 1]:
            i += 1
        else:
            j += 1
    return out


def content(words: List[Dict]) -> List[Dict]:
    """Words with a normalised key, fillers dropped."""
    out = []
    for w in words:
        k = norm_words([w])
        if k and k[0] not in FILLERS:
            out.append({"k": k[0], "start": float(w.get("start", 0)), "end": float(w.get("end", 0))})
    return out


def footage_metrics(task: Dict, words: List[Dict], sd: Path) -> Dict:
    """Footage edit (t4): known fillers removed, content kept in order, long pauses left.

    Transcribed fillers are not trusted (ASR often folds an 'uh' into the next word), so each known filler
    is checked by timing: the span of content words around it must shrink by >= 60% of the filler length.
    Source and output are transcribed by the same local model, so any folding happens the same way."""
    spec = common.read_json(common.BENCH / "fixtures" / "media" / "interview.source.json") or {}
    gt = spec.get("ground_truth", {})
    src = common.BENCH / "fixtures" / "media" / "interview.mp4"
    cache = common.bench_home() / "cache" / "asr-source"
    js = sorted((cache / "transcripts").glob("*.json")) if (cache / "transcripts").exists() else []
    ref = json.loads(js[0].read_text(encoding="utf-8")) if js else transcribe(src, cache)
    rw, ow = content((ref or {}).get("words") or []), content(words)
    rk, ok = [w["k"] for w in rw], [w["k"] for w in ow]
    align = lcs_align(rk, ok)
    spans = []
    for fs in gt.get("filler_spans", []):
        pat = fs["words"]
        idx = next((i for i in range(len(rk) - len(pat) + 1) if rk[i:i + len(pat)] == pat), None)
        if idx is None:
            spans.append({"words": pat, "result": "not found in source transcript"})
            continue
        src_span = rw[idx + len(pat) - 1]["end"] - rw[idx]["start"]
        mapped = [align.get(idx + k) for k in range(len(pat))]
        if any(m is None for m in mapped):
            spans.append({"words": pat, "result": "words cut"})
            continue
        out_span = ow[mapped[-1]]["end"] - ow[mapped[0]]["start"]
        removed = (src_span - out_span) >= 0.6 * fs["filler_s"]
        spans.append({"words": pat, "src_span": round(src_span, 2), "out_span": round(out_span, 2),
                      "result": "removed" if removed else "kept"})
    kept = len(align)
    gaps = [b["start"] - a["end"] for a, b in zip(ow, ow[1:])]
    n_fill = sum(2 if "two" in fs.get("note", "") else 1
                 for fs, r in zip(gt.get("filler_spans", []), spans) if r["result"] == "removed")
    return {"fillers_known": gt.get("fillers"), "fillers_removed": n_fill, "filler_spans": spans,
            "fillers_transcribed_in_output": sum(1 for w in norm_words(words) if w in FILLERS),
            "content_words_source": len(rk), "content_words_kept_in_order": kept,
            "content_kept_ratio": round(kept / len(rk), 3) if rk else None,
            "extra_words": max(0, len(ok) - kept),
            "pauses_over_1s": sum(1 for g in gaps if g > 1.0),
            "longest_pause_s": round(max(gaps), 2) if gaps else None}


def score_html(meta: Dict, rdir: Path, page: Path) -> Dict:
    sd = rdir / "score" / "html"
    r = common.run([common.node_bin(), str(common.BENCH / "scoring" / "html_probe.mjs"), str(page), str(sd)])
    try:
        rep = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"produced": False, "error": (r.stderr or r.stdout)[-800:]}
    mb = page.stat().st_size / 1e6
    spec = {"single_file": rep.get("single_file"), "offline": rep.get("offline"), "plays": rep.get("animates"),
            "size_ok": mb <= 16, "phone_ok": rep.get("phone_overflow") is False}
    return {"produced": True, "html": rep, "spec": spec,
            "frames": {"key": [str(sd / s) for s in rep.get("shots", [])], "sheet": None}}


def score_run(rdir: Path, asr_on: bool = True) -> Dict:
    meta = common.read_json(rdir / "meta.json")
    task = common.load_tasks([meta["task"]])[0]
    prim = (meta.get("deliverable") or {}).get("primary")
    res: Dict = {"task": meta["task"], "arm": meta["arm"], "produced": False}
    if prim:
        p = Path(meta["workspace"]) / prim
        if task.get("deliverable") == "html":
            res.update(score_html(meta, rdir, p))
        else:
            res.update(score_video(task, meta, rdir, p, asr_on))
    res["process"] = {k: meta.get(k) for k in ("wall_s", "ttfo_s", "first_tool_s", "cost_usd", "num_turns", "questions",
                                               "auto_replies", "capped", "is_error", "tokens", "subagents",
                                               "skills_invoked")}
    spec = res.get("spec") or {}
    checks = [v for k, v in spec.items() if isinstance(v, bool)]
    res["spec_score"] = round(sum(checks) / len(checks), 3) if checks else 0.0
    common.write_json(rdir / "score" / "auto.json", res)
    return res


def run_dirs(run: str, task: Optional[str], arm: Optional[str]) -> List[Path]:
    root = common.bench_home() / "runs" / run
    out = []
    for m in sorted(root.glob("*/*/meta.json")):
        t, a = m.parent.parent.name, m.parent.name
        if (task and not t.startswith(task)) or (arm and a != arm):
            continue
        out.append(m.parent)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", required=True)
    ap.add_argument("--task")
    ap.add_argument("--arm")
    ap.add_argument("--no-asr", action="store_true", help="skip local transcription (faster)")
    a = ap.parse_args()
    common.wait_for_round(a.run)
    for rd in run_dirs(a.run, a.task, a.arm):
        r = score_run(rd, not a.no_asr)
        qa = r.get("qa") or {}
        print("%-18s %-9s produced=%-5s spec=%.2f qa=%s %s" % (r["task"], r["arm"], r["produced"], r["spec_score"],
                                                              qa.get("verdict"), qa.get("summary")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

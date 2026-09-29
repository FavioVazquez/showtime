#!/usr/bin/env python3
"""Human blind A/B boards (one per task) built with showtime studio, for voting from a phone.

    python benchmarks/scoring/human_board.py build  --run r1 [--task t2] [--focal showtime] [--seed 11] [--rerecord]
    python benchmarks/scoring/human_board.py import --run r1 --task t2 --file feedback.json
    python benchmarks/scoring/human_board.py tally  --run r1

build   Every arm that delivered becomes an unlabeled candidate (letters shuffled per task). Nobody is
        dropped: when the candidates do not fit one page, ALL of them are re-encoded with the same settings
        (same bounding box, bitrate, H.264 + AAC, faststart, no metadata) until the page is <= 15 MB.
        HTML deliverables are screen-recorded to MP4 first, by the same procedure for every page
        (html_record.mjs: Chrome at 1920x1080, play pressed like a viewer would, the video's own length
        if the page exposes it, else 60 s; page audio captured in the page). A candidate that cannot be
        recorded gets a "could not be recorded" card instead of media, and the reason is logged.
        Each candidate carries its video, a poster frame and its length. Up to 5 A/B questions
        ("A or C: which would you ship?"): every pair with the focal arm plus one other pair, so the
        voter cannot tell which letter is the focal one from the questions alone. Voters can also rate
        every candidate 0-5. The board is marked "blind": nothing is recommended.
        Writes <bench home>/human/<run>/<task>.html (studio export --target artifact: a single file to
        publish as a private artifact) and key.json (letter -> arm; never put it on the board), then
        checks that no arm id, arm label or output path appears in the board's text or media metadata.
        One task failing does not stop the others (exit 1 at the end if any failed).
import  Feeds a returned feedback file into the task's studio job (`showtime studio feedback --import`).
tally   Maps answers and ratings back to arms through key.json -> human_summary.json.
"""
import argparse
import base64
import html as htmlmod
import itertools
import json
import os
import random
import re
import shutil
import string
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "harness"))
import auto_metrics  # noqa: E402
import common  # noqa: E402

PAGE_MAX_BYTES = 15.0e6      # published as an artifact (16 MB hard limit): keep the whole page under this
SHELL_BYTES = 450e3          # page code + board JSON + posters, measured ~0.3 MB; the loop below corrects it
REC_W, REC_H, REC_CAP_S = 1920, 1080, 60
POSTER_BOX = 640


def st(args: List[str], cwd: Path, out_root: Path) -> common.subprocess.CompletedProcess:
    env = dict(os.environ, SHOWTIME_OUT=str(out_root))
    return common.run([common.SHOWTIME] + args, cwd=str(cwd), env=env)


def log(msg: str) -> None:
    common.log("board: " + msg)


# ---------------------------------------------------------------- media

def settings_for(total_s: float, media_bytes: float) -> Dict:
    """One set of encoding settings for every candidate of a board, from the bits each second may use."""
    kbps = media_bytes * 8 / 1000.0 / max(total_s, 1.0)
    audio = (96, 2) if kbps >= 600 else (64, 1)
    video = int(max(120, min(2500, (kbps - audio[0]) * 0.92)))
    box = 1280 if video >= 1600 else 960 if video >= 800 else 854 if video >= 450 else 640
    return {"box": box, "video_kbps": video, "audio_kbps": audio[0], "audio_ch": audio[1]}


def encode(src: Path, dst: Path, s: Dict, audio: bool, tmp: Path) -> None:
    """Same filter, codec, bitrate and container settings for every candidate; never upscales."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = ("scale='min(%d,iw)':'min(%d,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,format=yuv420p"
          % (s["box"], s["box"]))
    base = [common.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-map", "0:v:0", "-vf", vf,
            "-fpsmax", "30", "-c:v", "libx264", "-preset", "slow", "-b:v", "%dk" % s["video_kbps"],
            "-maxrate", "%dk" % int(s["video_kbps"] * 1.5), "-bufsize", "%dk" % (s["video_kbps"] * 2),
            "-passlogfile", str(tmp / "x264")]
    common.run(base + ["-pass", "1", "-an", "-f", "mp4", os.devnull], check=True)
    tail = (["-map", "0:a:0", "-c:a", "aac", "-b:a", "%dk" % s["audio_kbps"], "-ac", str(s["audio_ch"]), "-ar", "48000"]
            if audio else ["-an"])
    common.run(base + ["-pass", "2"] + tail + ["-map_metadata", "-1", "-map_chapters", "-1", "-sn", "-dn",
                                               "-movflags", "+faststart", str(dst)], check=True)


def poster(src: Path, t: float, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    vf = "scale='min(%d,iw)':'min(%d,ih)':force_original_aspect_ratio=decrease" % (POSTER_BOX, POSTER_BOX)
    common.run([common.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-ss", "%.2f" % t, "-i", str(src),
                "-frames:v", "1", "-vf", vf, "-q:v", "5", "-map_metadata", "-1", str(dst)], check=True)


def record_html(src: Path, dst: Path, rerecord: bool) -> Dict:
    """Screen-record one HTML deliverable (html_record.mjs); cached next to the key, off the board."""
    meta = dst.with_suffix(".json")
    sig = {"src": str(src), "bytes": src.stat().st_size, "mtime": src.stat().st_mtime, "w": REC_W, "h": REC_H, "cap": REC_CAP_S}
    old = common.read_json(meta) or {}
    if not rerecord and old.get("sig") == sig and old.get("report", {}).get("ok") and dst.exists():
        return old["report"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = common.run([common.node_bin(), str(common.BENCH / "scoring" / "html_record.mjs"), str(src), str(dst),
                    "--width", str(REC_W), "--height", str(REC_H), "--cap", str(REC_CAP_S)], timeout=900)
    try:
        rep = json.loads((r.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        rep = {"ok": False, "why": "recorder printed no report (exit %s): %s" % (r.returncode, (r.stderr or "")[-400:])}
    common.write_json(meta, {"sig": sig, "report": rep})
    return rep


# ---------------------------------------------------------------- leak check

def leak_terms() -> List[str]:
    """Arm ids, arm labels, local names of the arms' sources, output-folder names, plus BENCH_LEAK_TERMS."""
    terms = {"showtime-out", "Claude Code", "key.json"}
    try:
        cfg = common.load_arms()
        for a in cfg["arms"]:
            terms.update([a["id"], a.get("label") or ""])
            loc = a.get("local") or {}
            if isinstance(loc, dict) and loc.get("name"):
                terms.add(str(loc["name"]))
    except SystemExit:
        pass
    terms.update(t.strip() for t in os.environ.get("BENCH_LEAK_TERMS", "").split(",") if t.strip())
    return sorted(t for t in terms if len(t) >= 4)


def leak_check(page: Path, terms: List[str]) -> Dict:
    """Search the board's own content (embedded board JSON, <title>, meta tags, and the bytes of every
    embedded media file) for the terms. The page code is the same for every board and candidate; its own
    mentions (the chrome's branding) are counted separately in `chrome`."""
    text = page.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'<script type="application/json" id="board-data">(.*?)</script>', text, re.S)
    data = m.group(1) if m else ""
    media = re.findall(r"data:([a-z]+/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=]+)", data)
    content = re.sub(r"data:[a-z]+/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+", "data:", data)
    content = content.replace('"schema":"showtime.studio.board/1"', "")  # the format's fixed id, same on every board
    heads = " ".join(re.findall(r"<title>.*?</title>|<meta name=\"st-job\"[^>]*>", text, re.S))
    board_text = htmlmod.unescape(content + " " + heads)
    rest = text.replace(data, "") if data else text
    rest = re.sub(r"data:[a-z]+/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+", "data:", rest)
    hits, chrome = [], {}
    for t in terms:
        rx = re.compile(re.escape(t), re.I)
        for mm in rx.finditer(board_text):
            hits.append({"term": t, "where": "board", "context": board_text[max(0, mm.start() - 40):mm.end() + 40]})
        for mime, b64 in media:
            raw = base64.b64decode(b64)
            if re.search(re.escape(t.encode("utf-8")), raw, re.I):
                hits.append({"term": t, "where": "media " + mime})
        n = len(rx.findall(rest))
        if n:
            chrome[t] = n
    return {"ok": not hits, "hits": hits[:20], "chrome": chrome, "media_files": len(media), "board_json": bool(m)}


# ---------------------------------------------------------------- board

def build(run: str, task_id: str, focal: str, seed: int, rerecord: bool = False) -> Dict:
    home = common.bench_home()
    task = common.load_tasks([task_id])[0]
    root = home / "human" / run
    root.mkdir(parents=True, exist_ok=True)
    cands = {}
    for rd in auto_metrics.run_dirs(run, task["id"], None):
        auto = common.read_json(rd / "score" / "auto.json") or {}
        meta = common.read_json(rd / "meta.json") or {}
        if auto.get("produced"):
            cands[rd.name] = {"auto": auto, "path": Path(meta["workspace"]) / meta["deliverable"]["primary"]}
    if len(cands) < 2:
        return {"task": task["id"], "skipped": "fewer than 2 deliverables"}
    rng = random.Random("%s/%s/%d" % (run, task["id"], seed))
    arms = sorted(cands)
    letters = list(string.ascii_uppercase[:len(arms)])
    rng.shuffle(letters)
    key = dict(zip(letters, arms))
    notes = {}  # letter -> why a candidate has no media (logged; kept off the board)

    # 1. a playable source per candidate: the MP4 itself, or a screen recording of the HTML page
    recorded = False
    rec_dir = root / "recordings" / task["id"]
    for letter in sorted(key):
        c = cands[key[letter]]
        c["src"] = c["path"]
        if c["path"].suffix.lower() in common.HTML_EXT:
            recorded = True
            rep = record_html(c["path"], rec_dir / (key[letter] + ".mp4"), rerecord)
            c["rec"] = rep
            if rep.get("ok"):
                c["src"] = rec_dir / (key[letter] + ".mp4")
                log("%s %s: recorded %.1f s (%s, length from %s, played via %s, audio %s)" % (
                    task["id"], letter, rep.get("duration", 0), rep.get("backend"), rep.get("duration_source"),
                    rep.get("played_via"), "captured" if (rep.get("audio") or {}).get("captured") else "none"))
            else:
                c["src"] = None
                notes[letter] = "could not be recorded: " + str(rep.get("why") or "unknown")[:300]
                log("%s %s: %s" % (task["id"], letter, notes[letter]))
        if c["src"] is not None:
            pr = common.probe(c["src"])
            if not pr.get("ok") or not pr.get("video") or not (pr.get("duration") or 0) > 0:
                notes[letter] = "not playable: " + str(pr.get("error") or "no video stream")[:300]
                log("%s %s: %s" % (task["id"], letter, notes[letter]))
                c["src"] = None
            c["probe"] = pr
    # page audio: kept only if it could be captured for every recorded page that had some; else none for all
    strip_audio = any((c.get("rec") or {}).get("ok") and (c["rec"].get("audio") or {}).get("sources")
                      and not c["rec"]["audio"].get("captured") for c in cands.values())
    if strip_audio:
        log("%s: page audio could not be captured for every page: all recordings are shown without sound" % task["id"])

    job = "vote-" + task["id"].split("-")[0]
    r = st(["studio", "init", job, "--title", "Blind vote", "--brief", task["prompt"], "--json"], root, root)
    if r.returncode != 0:
        raise RuntimeError("studio init failed: %s" % r.stderr[-600:])
    info = json.loads(r.stdout)
    jdir = Path(info.get("job_dir") or Path(info["studio_dir"]).parent)
    if not jdir.is_absolute() or root not in jdir.parents:
        raise RuntimeError("studio job landed outside %s: %s" % (root, jdir))
    sdir = jdir / "studio"
    for sub in ("animatic", "thumbs", "frames"):
        shutil.rmtree(sdir / "media" / sub, ignore_errors=True)

    playable = [l for l in sorted(key) if cands[key[l]]["src"] is not None]
    total = sum(cands[key[l]]["probe"]["duration"] for l in playable)
    out_html = root / ("%s.html" % task["id"])
    media_budget = (PAGE_MAX_BYTES - SHELL_BYTES) * 3 / 4  # base64 grows 4/3
    tmp = Path(tempfile.mkdtemp(prefix="board-"))
    try:
        alloc, grown = media_budget, False  # alloc: what the settings plan for; media_budget: the hard limit
        for attempt in range(6):
            s = settings_for(total, alloc)
            sizes = {}
            for letter in playable:
                c = cands[key[letter]]
                has_audio = bool(c["probe"].get("audio")) and not (strip_audio and c.get("rec"))
                c["has_audio"] = has_audio
                dst = sdir / "media" / "animatic" / (letter + ".mp4")
                encode(c["src"], dst, s, has_audio, tmp)
                sizes[letter] = dst.stat().st_size
                poster(c["src"], max(0.0, c["probe"]["duration"] * 0.6), sdir / "media" / "thumbs" / (letter + ".jpg"))
            enc_total = sum(sizes.values())
            if enc_total > media_budget and attempt < 5:
                log("%s: media %.1f MB over the %.1f MB budget at %s; re-encoding all candidates smaller" % (
                    task["id"], enc_total / 1e6, media_budget / 1e6, s))
                alloc *= media_budget / enc_total * 0.96
                continue
            if not grown and enc_total < 0.85 * media_budget and s["video_kbps"] < 2500 and attempt < 5:
                # simple or silent sources left budget unused: give every candidate the same higher settings
                grown = True
                alloc *= min(1.6, media_budget / max(enc_total, 1) * 0.95)
                continue
            board = board_json(task, jdir, key, cands, playable, notes, s, recorded, strip_audio, focal, arms, rng_seed=(run, seed))
            common.write_json(sdir / "board.json", board)
            r = st(["studio", "board", str(jdir)], root, root)
            if r.returncode != 0:
                raise RuntimeError("studio board rejected the board:\n%s%s" % (r.stdout[-1500:], r.stderr[-800:]))
            warns = [ln for ln in (r.stdout + r.stderr).splitlines() if "warning" in ln]
            r = st(["studio", "export", str(jdir), "--target", "artifact", "-o", str(out_html), "--json"], root, root)
            if r.returncode != 0:
                raise RuntimeError("studio export failed: %s" % r.stderr[-800:])
            exp = json.loads(r.stdout or "{}")
            size = out_html.stat().st_size
            if (exp.get("skipped") or size > PAGE_MAX_BYTES) and attempt < 5:
                log("%s: page %.2f MB, skipped %s; re-encoding all candidates smaller" % (task["id"], size / 1e6, exp.get("skipped")))
                shrink = min(0.93, PAGE_MAX_BYTES / max(size, 1) * 0.97)
                media_budget *= shrink
                alloc *= shrink
                grown = True
                continue
            if exp.get("skipped") or size > PAGE_MAX_BYTES:
                raise RuntimeError("board still over budget after 6 tries (%.2f MB, skipped %s)" % (size / 1e6, exp.get("skipped")))
            break
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    questions = board["questions"]
    keys = common.read_json(root / "key.json", {}) or {}
    keys[task["id"]] = {"letters": key, "questions": [q["id"] for q in questions], "job": str(jdir),  # absolute path
                        "notes": notes, "encode": s, "audio_stripped": strip_audio}
    common.write_json(root / "key.json", keys)
    leak = leak_check(out_html, leak_terms())
    if not leak["ok"]:
        raise RuntimeError("the board names a tool or an output path: %s" % json.dumps(leak["hits"])[:1500])
    return {"task": task["id"], "html": str(out_html), "bytes": size, "candidates": len(board["concepts"]),
            "playable": len(playable), "no_media": sorted(notes), "encode": s, "audio_stripped": strip_audio,
            "export_skipped": exp.get("skipped"), "warnings": warns, "leak_check": {"ok": leak["ok"], "chrome": leak["chrome"]}}


def board_json(task: Dict, jdir: Path, key: Dict, cands: Dict, playable: List[str], notes: Dict, s: Dict,
               recorded: bool, strip_audio: bool, focal: str, arms: List[str], rng_seed) -> Dict:
    concepts = []
    for letter in sorted(key):
        c = cands[key[letter]]
        entry = {"id": "cand-" + letter, "tag": letter, "title": "Version " + letter}
        if letter not in playable:
            entry.update({"logline": "Could not be recorded or played: this version is shown without media.",
                          "frames": [{"id": "cand-%s-f1" % letter, "src": "media/thumbs/none.svg", "placeholder": True,
                                      "caption": "Could not be recorded"}]})
            concepts.append(entry)
            continue
        pr = c["probe"]
        v = pr.get("video") or {}
        dur = round(pr.get("duration") or 0, 1)
        bits = ["%.1f s" % dur, common.aspect_label(v.get("width") or 0, v.get("height") or 0)]
        if c.get("rec"):
            bits.append("screen-recorded HTML page")
        if not c.get("has_audio"):
            bits.append("no sound" if not (strip_audio and c.get("rec")) else "sound not captured")
        entry.update({"duration": dur, "logline": " · ".join(bits),
                      "frames": [{"id": "cand-%s-f1" % letter, "src": "media/thumbs/%s.jpg" % letter,
                                  "thumb": "media/thumbs/%s.jpg" % letter, "caption": "Frame at 60%"}],
                      "animatic": {"src": "media/animatic/%s.mp4" % letter, "poster": "media/thumbs/%s.jpg" % letter,
                                   "duration": dur}})
        concepts.append(entry)
    if len(playable) < len(key):
        none_svg = jdir / "studio" / "media" / "thumbs" / "none.svg"
        none_svg.parent.mkdir(parents=True, exist_ok=True)
        none_svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">'
                            '<rect width="640" height="360" fill="#2a2a2a"/><text x="320" y="186" font-family="sans-serif" '
                            'font-size="28" fill="#dddddd" text-anchor="middle">Could not be recorded</text></svg>', encoding="utf-8")
    rng = random.Random("%s/%s/%d/q" % (rng_seed[0], task["id"], rng_seed[1]))
    inv = {a: l for l, a in key.items()}
    pairs = []
    if focal in inv:
        pairs = [tuple(sorted((inv[focal], inv[o]))) for o in arms if o != focal]
    others = [p for p in itertools.combinations(sorted(key), 2) if p not in pairs]
    rng.shuffle(others)
    pairs = (pairs + others)[:5]
    rng.shuffle(pairs)
    questions = [{"id": "q-%s%s" % p, "text": "%s or %s: which would you ship?" % p,
                  "options": [{"id": "q-%s%s-%s" % (p[0], p[1], x), "label": x} for x in (p[0], p[1])] +
                             [{"id": "q-%s%s-tie" % p, "label": "Can't choose"}], "allowText": True} for p in pairs]
    small = ["Small print: every version is re-encoded with the same settings so all fit on one page "
             "(H.264 within %dx%d px, %d kbps video, AAC %d kbps; nothing upscaled)." % (s["box"], s["box"], s["video_kbps"], s["audio_kbps"])]
    if recorded:
        small.append("HTML deliverables were screen-recorded the same way for every version: Chrome at %dx%d, "
                     "play pressed as a viewer would, for the video's own length when the page exposes it (else %d s), "
                     "page sound captured in the page%s." % (REC_W, REC_H, REC_CAP_S,
                                                           "; sound could not be captured for every page, so none is shown" if strip_audio else ""))
    return {"schema": "showtime.studio.board/1", "job": jdir.name, "title": "Blind vote: " + task["title"],
            "brief": task["prompt"], "rev": 1, "phase": "review", "blind": True,
            "round": {"n": 1, "label": "Blind A/B",
                      "prompt": "Play each version, rate each 0-5, then answer the A/B questions. Nothing says which tool made which.",
                      "note": " ".join(small)},
            "history": [{"rev": 1, "note": "%d blind candidates" % len(concepts)}],
            "concepts": concepts, "questions": questions}


DIGEST_PAIR = re.compile(r"^\s*-\s*([A-Z]) or ([A-Z]):.*?->\s*([A-Z]|tie)\s*$", re.I)
DIGEST_RATING = re.compile(r'^\s*-\s*([A-Z])\s+"[^"]*":\s*(\d)/5\s*$')
DIGEST_PICK = re.compile(r'^\s*-\s*concept:\s*([A-Z])\b')


def parse_digest(text: str) -> Dict:
    """Votes from the board's "Copy for your agent" text ("Copy for Claude" before 0.2.0; the digest is the same):
    the only way back from a board opened as a claude.ai artifact, where downloads are blocked.
    Returns {answers: [(x, y, winner)], ratings: {letter: n}, pick}."""
    out = {"answers": [], "ratings": {}, "pick": None}
    section = ""
    for line in text.splitlines():
        head = line.strip().rstrip(":").lower()
        if head in ("picks", "answers", "reactions", "comments") or head.startswith("comments ("):
            section = head.split(" ")[0]
            continue
        m = DIGEST_PAIR.match(line)
        if m and section == "answers":
            out["answers"].append((m.group(1).upper(), m.group(2).upper(), m.group(3)))
            continue
        m = DIGEST_RATING.match(line)
        if m and section == "reactions":
            out["ratings"][m.group(1)] = int(m.group(2))
            continue
        m = DIGEST_PICK.match(line)
        if m and section == "picks":
            out["pick"] = m.group(1)
    return out


def tally(run: str) -> Dict:
    root = common.bench_home() / "human" / run
    keys = common.read_json(root / "key.json", {}) or {}
    out = {"tasks": {}, "pairs": [], "ratings": {}, "picks": {}}
    for task_id, k in keys.items():
        dg = root / "votes" / (task_id + ".txt")
        if dg.exists():  # "Copy for your agent" digest (artifact-hosted boards; older boards said "Copy for Claude")
            d = parse_digest(dg.read_text(encoding="utf-8"))
            letters = k["letters"]
            for x, y, w in d["answers"]:
                winner = "tie" if w.lower() == "tie" else letters.get(w.upper())
                out["pairs"].append({"task": task_id, "a": letters.get(x), "b": letters.get(y), "winner": winner})
            for L, n in d["ratings"].items():
                if letters.get(L):
                    out["ratings"].setdefault(letters[L], []).append(n)
            if d["pick"] and letters.get(d["pick"]):
                out["picks"][task_id] = letters[d["pick"]]
            out["tasks"][task_id] = {"answers": len(d["answers"]), "ratings": len(d["ratings"]), "source": "digest"}
            continue
        r = st(["studio", "feedback", k["job"], "--json"], root, root)
        try:
            state = json.loads(r.stdout).get("state", {})
        except ValueError:
            continue
        letters = k["letters"]
        for qid, ans in (state.get("answers") or {}).items():
            val = (ans or {}).get("value") if isinstance(ans, dict) else ans
            pair = qid[2:]
            a, b = letters.get(pair[0]), letters.get(pair[1])
            pick = str(val or "").rsplit("-", 1)[-1]
            winner = "tie" if pick == "tie" else letters.get(pick)
            out["pairs"].append({"task": task_id, "a": a, "b": b, "winner": winner})
        for target, n in (state.get("ratings") or {}).items():
            arm = letters.get(target.replace("cand-", ""))
            if arm:
                out["ratings"].setdefault(arm, []).append(n)
        out["tasks"][task_id] = {"answers": len(state.get("answers") or {}), "ratings": len(state.get("ratings") or {})}
    common.write_json(common.bench_home() / "runs" / run / "human_summary.json", out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["build", "import", "tally"])
    ap.add_argument("--run", required=True)
    ap.add_argument("--task")
    ap.add_argument("--focal", default="showtime")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--file")
    ap.add_argument("--rerecord", action="store_true", help="screen-record HTML deliverables again (default: reuse)")
    a = ap.parse_args()
    if a.command == "build":
        failed = 0
        for t in common.load_tasks([a.task] if a.task else None):
            try:
                print(json.dumps(build(a.run, t["id"], a.focal, a.seed, a.rerecord)), flush=True)
            except Exception as e:  # one task's failure never stops the others
                failed += 1
                log("%s: FAILED: %s" % (t["id"], e))
                traceback.print_exc(file=sys.stderr)
                print(json.dumps({"task": t["id"], "error": str(e)[:1500]}), flush=True)
        return 1 if failed else 0
    elif a.command == "import":
        keys = common.read_json(common.bench_home() / "human" / a.run / "key.json", {}) or {}
        k = keys[common.load_tasks([a.task])[0]["id"]]
        root = common.bench_home() / "human" / a.run
        text = Path(a.file).read_text(encoding="utf-8", errors="replace")
        if text.lstrip().startswith("STUDIO FEEDBACK"):  # the board's "Copy for your agent" text (or "Copy for Claude" from older boards)
            d = parse_digest(text)
            if not d["answers"] and not d["ratings"] and not d["pick"]:
                print("no votes found in %s (expected the 'Copy for your agent' text of a blind board)" % a.file)
                return 1
            (root / "votes").mkdir(parents=True, exist_ok=True)
            (root / "votes" / (k_task := common.load_tasks([a.task])[0]["id"])).with_suffix(".txt").write_text(text, encoding="utf-8")
            print("imported %s: %d answers, %d ratings, pick %s" % (k_task, len(d["answers"]), len(d["ratings"]), d["pick"]))
            return 0
        r = st(["studio", "feedback", k["job"], "--import", str(Path(a.file).resolve())], root, root)
        print(r.stdout or r.stderr)
    else:
        print(json.dumps(tally(a.run), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Blind pairwise review: `showtime review-pack <job> --against <old>` and `showtime review-verdict`.

A reviewer's absolute score (1-10) is noisy; a preference between two versions is steadier, and it
only counts when it survives swapping the order. So a pairwise round shows the critic the new render
and an older one as "X" and "Y" (assigned at random), with the same evidence for both at the same
times: a contact sheet each, side-by-side sheets, frames at matched times, the frames around each
cut, text crops, loudness plots, the qa verdict and a transcript of the narration (the critic cannot
hear). Two briefs judge the pair in the two orders (order-1: X first, order-2: Y first), each by a
fresh critic; the key (which label is which file) sits outside the round folder, in
<review root>/.pairwise-keys/, which no critic is given.

`review-verdict` applies the rule: the new version is an improvement only when it is preferred in both
orders; a tie or a split keeps the older one. It tracks the best version so far (best.json) and, once
the round cap is reached, says to ship the best with its open findings listed.
"""
from __future__ import annotations

import os
import random
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import ff
from ..common import ShowtimeError, log, read_json, write_json
from . import images, media, review
from . import video as qa_video

KEYS = ".pairwise-keys"
LABELS = ("X", "Y")
# what the video was asked to be; files that tell the story of the fixes (feedback, decisions, the job
# ledger, check and mix reports of the current project) would tell the critic which version is newer
CONTEXT_NAMES = ("brief.md", "storyboard.md", "script.md", "plan.md", "brand.md", "credits.txt", "CREDITS.txt",
                 "share.txt", "share-copy.txt")
PLAN_FILES = ("showtime.json", "index.html", "cues.js", "scenes.js", "voice/timeline.json")
MAX_MATCHED = 20


# ------------------------------------------------------------------ which video is "old"

def _read(path: Path) -> Any:
    """JSON from a file, or None when it is missing."""
    return read_json(path, {}) if Path(path).is_file() else None


def round_video(root: Path, n: int, role: str = "new") -> Path:
    """The video a round judged: a single round's manifest video, a pairwise round's new (or old) one."""
    d = root / ("round-%d" % n)
    key = _read(root / KEYS / ("round-%d.json" % n))
    if isinstance(key, dict) and key.get(role):
        return Path(key[role]["video"])
    m = _read(d / "manifest.json")
    if isinstance(m, dict) and m.get("video"):
        return Path(m["video"])
    raise ShowtimeError("round-%d in %s has no video on record" % (n, root), hint="pass the older video file instead")


def resolve_against(against: str, root: Path, new: Path) -> Tuple[Path, str]:
    """(older video, how it was found) for --against: a video file, round-N / N, or "best"."""
    a = str(against).strip()
    m = re.fullmatch(r"(?:round-?)?(\d+)", a)
    if m and not Path(a).is_file():
        v, how = round_video(root, int(m.group(1))), "the video of round-%s" % m.group(1)
    elif a.lower() == "best":
        best = _read(root / "best.json")
        if isinstance(best, dict) and best.get("video"):
            v, how = Path(best["video"]), "the best version so far (best.json, round %s)" % best.get("round")
        else:
            rounds = review.critic_rounds(root)
            if not rounds:
                raise ShowtimeError("--against best: %s has no answered review round yet" % root,
                                    hint="review the first version with plain showtime review-pack, or pass the older "
                                         "video file")
            v, how = round_video(root, rounds[-1]), "the video of round-%d (no pairwise verdict yet)" % rounds[-1]
    else:
        v, how = Path(a).expanduser(), "given"
    if not v.is_file():
        raise ShowtimeError("--against %s: no such video (%s)" % (against, v),
                            hint="pass the older render, round-N, or best")
    v = v.resolve()
    if v == new.resolve():
        raise ShowtimeError("--against %s is the same file as the version under review (%s)" % (against, new.name),
                            hint="render the new version first (it becomes the job's latest final), then pair it")
    return v, how


# ------------------------------------------------------------------ one side of the pair

def _plan_fresh(proj: Optional[Path], video: Path) -> bool:
    """The project's scene plan is as old as the video (so its scene times describe this render)."""
    if proj is None:
        return False
    try:
        vt = video.stat().st_mtime
        return all((proj / f).stat().st_mtime <= vt + 1 for f in PLAN_FILES if (proj / f).is_file())
    except OSError:
        return False


def side_cuts(video: Path, proj: Optional[Path], dur: float) -> Tuple[List[float], List[Tuple[float, str]], str]:
    """(cuts, scene starts with names, source) for one video; planned scenes only when the plan is not
    newer than the render (the older version was often made from an earlier plan)."""
    detected = media.scene_cuts(video, threshold=0.25)
    planned = review.planned_scenes(video, proj, dur) if _plan_fresh(proj, video) else None
    if planned is None:
        planned = review.planned_scenes(video, None, dur)          # an edit's EDL report is per render
    if planned is None:
        return [c for c in detected if 0.1 < c < dur - 0.1], [(0.0, "")] + [(c, "") for c in detected], "cut detection"
    cuts = [a for a, _ in planned["scenes"] if 0.1 < a < dur - 0.1]
    cuts += [t for t in detected if 0.1 < t < dur - 0.1 and all(abs(t - c) >= 0.6 for c in cuts)]
    return sorted(cuts), list(planned["scenes"]), planned["source"]


def _placeholder(path: Path, size: Tuple[int, int], text: str) -> Path:
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, (24, 24, 28))
    d = ImageDraw.Draw(im)
    f = images.font(max(12, size[1] // 12))
    w = d.textlength(text, font=f)
    d.text(((size[0] - w) / 2, size[1] / 2 - size[1] // 24), text, fill=(200, 200, 205), font=f)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(os.fspath(path), "PNG" if path.suffix.lower() == ".png" else "JPEG", quality=90)
    return path


def frames_at(video: Path, times: Sequence[float], out: Path, dur: float, fps: float, W: int, H: int,
              width: Optional[int], ext: str = "jpg") -> List[Path]:
    """One image per requested time, named by that time (so X and Y files match); past the end of this
    video a card says where it ended instead of repeating its last frame."""
    last = media.clamp_time(dur, dur, fps)
    w = width or W or 640
    h = int(round(w * (H / float(W or 1)) / 2) * 2) if W else 360
    res = []
    for t in times:
        name = media.frame_name(t, ext)
        if t > last + 0.5 / fps:
            res.append(_placeholder(out / name, (w, h), "ended at %.2fs" % dur))
        else:
            got = media.extract_frames(video, [min(t, last)], out, width=width, duration=dur, fps=fps, names=[name])
            res.append(got[0] if got else _placeholder(out / name, (w, h), "no frame at %.2fs" % t))
    return res


def transcript(video: Path, proj: Optional[Path]) -> Tuple[str, str]:
    """(text, source): the narration of this render (st.qa.review.narration), one timed line per cue."""
    cues, source = review.narration(video, proj)
    return review.cue_lines(cues), source


def asr_cues(video: Path, scratch: Path) -> Tuple[List[Tuple[float, float, str]], str]:
    """Speech recognition of one render with a model that is already installed (never a download), so a
    version without caption files still gets a transcript when the other version has one: otherwise the
    critic could tell the two apart by which one has a transcript. ([], "") when that is not possible."""
    old = os.environ.get("SHOWTIME_OFFLINE")
    os.environ["SHOWTIME_OFFLINE"] = "1"
    try:
        from ..footage import transcribe as T
        from ..footage import util as U
        doc, _ = T.transcribe(video, edit_dir=scratch, out_path=scratch / "asr.json", events="off", separate="off")
        words = [w for w in U.words_of(doc) if w.get("start") is not None]
    except Exception as e:  # noqa: BLE001 - no model, no audio, no speech: the brief says so
        log("review-pack: no speech transcript for one version (%s)" % str(e).splitlines()[0][:120])
        return [], ""
    finally:
        if old is None:
            os.environ.pop("SHOWTIME_OFFLINE", None)
        else:
            os.environ["SHOWTIME_OFFLINE"] = old
    cues: List[List[Any]] = []
    for w in words:
        if cues and w["start"] - cues[-1][1] < 0.6 and len(cues[-1][2]) < 14:
            cues[-1][1] = w["end"]
            cues[-1][2].append(str(w["text"]).strip())
        else:
            cues.append([w["start"], w["end"], [str(w["text"]).strip()]])
    out = [(float(a), float(b), " ".join(t)) for a, b, t in cues]
    return out, "speech recognition" if out else ""


def asr_transcript(video: Path, scratch: Path) -> Tuple[str, str]:
    """(text, source) of asr_cues."""
    cues, source = asr_cues(video, scratch)
    return review.cue_lines(cues), source


def _scrub(text: str, video: Path, label: str) -> str:
    """qa messages can name the file (final-2.mp4 says which render is newer): name the label instead."""
    for a in sorted({str(video.resolve()), str(video), video.name, video.stem}, key=len, reverse=True):
        text = text.replace(a, "video %s" % label)
    for a in sorted({str(video.resolve().parent), str(video.parent)}, key=len, reverse=True):
        text = text.replace(a, "<folder>")
    return text


def qa_text(q: Dict[str, Any], video: Path, label: str) -> str:
    loud = q.get("loudness") or {}
    out = ["Automated QA of video %s: %s (%d fail, %d warn)" % (label, q["verdict"], q["summary"]["fail"],
                                                               q["summary"]["warn"])]
    if loud.get("integrated_lufs") is not None:
        out.append("Loudness: %s LUFS integrated, true peak %s dBTP (target %s LUFS)" % (
            loud.get("integrated_lufs"), loud.get("true_peak_dbtp"), loud.get("target_lufs")))
    rh = (q.get("rhythm") or {}).get("summary")
    if rh:
        out.append("Rhythm: %s" % rh)
    for f in [f for f in q.get("findings", []) if f["severity"] in ("FAIL", "WARN")][:20]:
        out.append("- %s %s%s: %s" % (f["severity"], f["rule"], " t=%.2fs" % f["t"] if f.get("t") is not None else "",
                                      f["message"]))
    return _scrub("\n".join(out) + "\n", video, label)


def build_side(pre: Dict[str, Any], video: Path, proj: Optional[Path], pack: Path, keys: Path,
               matched: List[Tuple[float, str]], sheet_times: List[float], *, record: bool, platform: Optional[str],
               lufs: Optional[float], expect_file: Optional[str], say: Any) -> Dict[str, Any]:
    label = pre["label"]
    d = pack / label
    (d / "frames").mkdir(parents=True)
    dur, fps, (W, H) = pre["duration"], pre["fps"], pre["size"]
    thumb = 400 if W >= H else 240
    say("review-pack: %s: qa" % label)
    qdir = keys / ("qa-%s" % label)
    shutil.rmtree(qdir, ignore_errors=True)
    q = qa_video.run(video, project=proj, expect_file=expect_file, out_dir=qdir, platform=platform, lufs=lufs,
                     quiet=True, record=record)
    (d / "qa.txt").write_text(qa_text(q, video, label), encoding="utf-8", newline="\n")
    say("review-pack: %s: frames at the matched times" % label)
    sp = frames_at(video, sheet_times, d / "sheet-frames", dur, fps, W, H, thumb)
    sheet = images.contact_sheet([{"path": str(p), "label": "%.2fs" % t} for p, t in zip(sp, sheet_times)],
                                 d / "sheet.jpg", thumb=thumb,
                                 title="video %s  %dx%d  %.2fs" % (label, W, H, dur))
    mp = frames_at(video, [t for t, _ in matched], d / "frames", dur, fps, W, H, min(W, 1280) or None)
    cuts = pre["cuts"]
    strips: List[Dict[str, Any]] = []
    for c in cuts[:16]:
        k0 = int(round(c * fps))
        for k, p in media.extract_run(video, max(0, k0 - 2), 7, fps, d / "cut-frames", width=thumb, duration=dur):
            strips.append({"path": str(p), "label": "cut %.2f %+df" % (c, k - k0), "sub": "%.3fs" % (k / fps)})
    cut_sheet = str(images.contact_sheet(strips, d / "cuts.jpg", thumb=thumb, cols=7,
                                         title="video %s  every frame from 2 before to 4 after each cut" % label)) \
        if strips else None
    text_crops: List[Dict[str, Any]] = []
    try:
        from . import textcrops
        live = [(t, lab) for t, lab in matched if t <= dur]
        tp = frames_at(video, [t for t, _ in live], keys / ("text-%s" % label), dur, fps, W, H, None, ext="png")
        text_crops = textcrops.crops([(t, lab, p) for (t, lab), p in zip(live, tp)], d / "frames", limit=12)
        shutil.rmtree(keys / ("text-%s" % label), ignore_errors=True)
    except Exception as e:  # noqa: BLE001 - the crops help the critic; they must not stop the pack
        say("review-pack: %s: text crops skipped (%s)" % (label, e))
    loud = review.loudness_png(qdir, q, d / "loudness.png", dur, "video %s" % label)
    hear = None
    try:
        from . import hearing
        b = sorted(set([0.0] + [c for c in cuts if 0.2 < c < dur - 0.2] + [dur]))
        hear = hearing.for_pack(video, proj, q, qdir, cuts=[c for c in cuts if 0.1 < c < dur - 0.1],
                                scenes=[(b[i], b[i + 1], "part %d" % (i + 1)) for i in range(len(b) - 1) if b[i + 1] - b[i] > 0.15],
                                out_dir=d, name="video %s" % label, title="video %s" % label)
        if hear:
            tp = Path(hear["text"])
            tp.write_text(_scrub(tp.read_text(encoding="utf-8"), video, label), encoding="utf-8", newline="\n")
    except Exception as e:  # noqa: BLE001 - the hearing material helps the critic; it must not stop the pack
        say("review-pack: %s: hearing measurements skipped (%s)" % (label, e))
    poster = next((p for p, (t, lab) in zip(mp, matched) if lab == "poster %s" % label), mp[0] if mp else None)
    thumb_small = str(images.thumbnail_preview(poster, d / ("thumb-168x94.png" if W >= H else "thumb-94x168.png"),
                                               (168, 94) if W >= H else (94, 168))) if poster else None
    return {"label": label, "duration": dur, "size": [W, H], "fps": fps, "sheet": str(sheet), "cut_strips": cut_sheet,
            "cuts": [round(c, 3) for c in cuts],
            "frames": [{"t": round(t, 3), "label": lab, "path": str(p)} for p, (t, lab) in zip(mp, matched)],
            "text_crops": text_crops, "loudness_graph": loud, "thumbnail_preview": thumb_small,
            "hearing": {"text": hear["text"], "graph": hear["graph"]} if hear else None,
            "qa": {"verdict": q["verdict"], "summary": q["summary"], "text": str(d / "qa.txt")},
            "transcript": str(d / "transcript.txt"), "story": str(d / "story.txt"),
            "launch_rhythm": (q.get("rhythm") or {}).get("summary") if (q.get("rhythm") or {}).get("launch") else None,
            "_q": q}


def story_of(side: Dict[str, Any], pre: Dict[str, Any], cues: List[Tuple[float, float, str]], source: str,
             pack: Path) -> str:
    """One version's parts in order (cuts as the boundaries), each with the matched frame nearest its middle
    and its narration, for the first-viewer pass. Paths are relative to a brief's order-N folder."""
    dur = side["duration"]
    b = sorted(set([0.0] + [c for c in pre["cuts"] if 0.2 < c < dur - 0.2] + [dur]))
    parts = []
    od = pack / "order-1"
    for a, e in [(b[i], b[i + 1]) for i in range(len(b) - 1) if b[i + 1] - b[i] > 0.15]:
        inside = [f for f in side["frames"] if a <= f["t"] < e]
        best = min(inside, key=lambda f: abs(f["t"] - (a + e) / 2)) if inside else None
        parts.append((a, e, "", _rel(best["path"], od) if best else None))
    return review.story_text(parts, cues, source, where="your brief's folder")


# ------------------------------------------------------------------ the pack

def _matched_times(sides: List[Dict[str, Any]]) -> List[Tuple[float, str]]:
    """Frame 0, the hook, each video's poster and last frame, and every scene middle of both, deduplicated."""
    key: List[Tuple[float, str]] = [(0.0, "frame 0"), (0.5, "hook 0.5s"), (1.5, "hook 1.5s")]
    mids: List[Tuple[float, str]] = []
    for s in sides:
        dur, fps = s["duration"], s["fps"]
        if s.get("poster") is not None:
            key.append((float(s["poster"]), "poster %s" % s["label"]))
        key.append((media.clamp_time(dur, dur, fps), "end of %s" % s["label"]))
        b = sorted(set([0.0] + [c for c in s["cuts"] if 0.2 < c < dur - 0.2] + [dur]))
        mids += [(round((b[i] + b[i + 1]) / 2, 3), "scene middle") for i in range(len(b) - 1) if b[i + 1] - b[i] > 0.15]
    out: List[Tuple[float, str]] = []
    for t, lab in sorted(key):                     # the key moments, once per time
        if all(abs(t - u) >= 0.02 for u, _ in out):
            out.append((round(t, 3), lab))
    for t, lab in sorted(mids):                    # scene middles not within 0.3 s of a frame already taken
        if len(out) < MAX_MATCHED and all(abs(t - u) >= 0.3 for u, _ in out):
            out.append((t, lab))
    return sorted(out)


def _pre_probe(label: str, video: Path, proj: Optional[Path]) -> Dict[str, Any]:
    pr = ff.probe(video)
    dur, fps = float(pr.get("duration") or 0), float(pr.get("fps") or 30.0)
    cuts, _, source = side_cuts(video, proj, dur)
    rj = review.render_report(video)
    poster = ((rj or {}).get("poster") or {}).get("time") if isinstance(rj, dict) else None
    return {"label": label, "duration": dur, "fps": fps, "cuts": cuts, "scenes_source": source,
            "size": [int(pr.get("width") or 0), int(pr.get("height") or 0)],
            "poster": float(poster) if poster is not None and float(poster) <= dur else None}


def build(target: Optional[str], against: str, *, out: Optional[str] = None, project: Optional[str] = None,
          expect_file: Optional[str] = None, platform: Optional[str] = None, force_round: bool = False,
          every: Optional[float] = None, quiet: bool = False, lufs: Optional[float] = None,
          seed: Optional[int] = None) -> Dict[str, Any]:
    t0 = time.time()
    say = (lambda m: None) if quiet else log
    new, job = review.resolve_video(target, say=log)
    new = new.resolve()
    root = Path(out).expanduser().resolve() if out else ((job / "review") if job else new.parent / (new.stem + ".review"))
    old, how = resolve_against(against, root, new)
    log("review-pack: pairwise, %s against %s (%s)" % (new.name, old.name, how))
    n, pack = review.open_round(root, force_round, new, say)
    keys = root / KEYS / ("round-%d" % n)
    shutil.rmtree(keys, ignore_errors=True)
    keys.mkdir(parents=True)
    rng = random.Random(seed) if seed is not None else random.SystemRandom()
    x_is_new = rng.random() < 0.5
    by_label = {"X": new if x_is_new else old, "Y": old if x_is_new else new}
    role = {"X": "new" if x_is_new else "old", "Y": "old" if x_is_new else "new"}
    if lufs is None or platform is None:
        prev = review._last_qa_args(new, job)      # both sides are judged like the last qa of the new render
        lufs = float(prev["lufs"]) if lufs is None and prev.get("lufs") is not None else lufs
        platform = str(prev["platform"]) if platform is None and prev.get("platform") else platform
    proj_new = qa_video.find_project(new, project)
    projs = {"X": proj_new if x_is_new else qa_video.find_project(old, project),
             "Y": qa_video.find_project(old, project) if x_is_new else proj_new}
    say("review-pack: finding scenes and cuts in both versions")
    pre = [_pre_probe(lab, by_label[lab], projs[lab]) for lab in LABELS]
    matched = _matched_times(pre)
    longest = max(p["duration"] for p in pre)
    step = every or (1.0 if longest <= 48 else longest / 48.0)
    sheet_times = sorted(set(round(i * step, 3) for i in range(int(longest / step) + 1)))
    sides = {}
    for pr in pre:
        lab = pr["label"]
        sides[lab] = build_side(pr, by_label[lab], projs[lab], pack, keys, matched, sheet_times,
                                record=role[lab] == "new", platform=platform, lufs=lufs, expect_file=expect_file, say=say)
    say("review-pack: narration transcripts and the parts in order")
    narr = {lab: review.narration(by_label[lab], projs[lab]) for lab in LABELS}
    for lab in LABELS:
        other = "Y" if lab == "X" else "X"
        if not narr[lab][0] and narr[other][0]:
            narr[lab] = asr_cues(by_label[lab], keys / ("asr-%s" % lab))
    texts = {lab: (review.cue_lines(narr[lab][0]), narr[lab][1]) for lab in LABELS}
    for i, lab in enumerate(LABELS):
        Path(sides[lab]["transcript"]).write_text(
            (texts[lab][0] or "(no narration transcript for this version: no caption file, voice timeline or recognised "
                               "speech belongs to it)") + "\n", encoding="utf-8", newline="\n")
        Path(sides[lab]["story"]).write_text(story_of(sides[lab], pre[i], narr[lab][0], narr[lab][1], pack),
                                             encoding="utf-8", newline="\n")
    say("review-pack: side-by-side sheets")
    W, H = sides["X"]["size"]
    thumb = 360 if W >= H else 220
    compare = {}
    for a, b in (("X", "Y"), ("Y", "X")):
        items = []
        for fa, fb in zip(sides[a]["frames"], sides[b]["frames"]):
            items += [{"path": fa["path"], "label": "%s  %.2fs" % (a, fa["t"]), "sub": fa["label"]},
                      {"path": fb["path"], "label": "%s  %.2fs" % (b, fb["t"]), "sub": fb["label"]}]
        compare[a + b] = str(images.contact_sheet(items, pack / ("compare-%s%s.jpg" % (a, b)), thumb=thumb, cols=4,
                                                  title="the same moments: %s left, %s right (pairs)" % (a, b)))
    say("review-pack: copying context")
    ctx = pack / "context"
    ctx.mkdir()
    copied: List[str] = []
    search = [d for d in (job, proj_new, job / "studio" if job else None, proj_new / "studio" if proj_new else None)
              if d and d.is_dir()]
    for d in search:
        for name in CONTEXT_NAMES:
            src = d / name
            if src.is_file() and src.stat().st_size < 2_000_000 and not (ctx / name).exists():
                shutil.copy2(src, ctx / name)
                copied.append(str(ctx / name))
    manifest: Dict[str, Any] = {
        "round": n, "max_rounds": review.MAX_ROUNDS, "pairwise": True, "labels": list(LABELS),
        "sides": {lab: {k: v for k, v in s.items() if not k.startswith("_")} for lab, s in sides.items()},
        "matched_times": [[t, lab] for t, lab in matched], "compare": compare, "context": copied,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "platform": platform, "lufs": lufs,
    }
    briefs = []
    for k, (first, second) in enumerate((("X", "Y"), ("Y", "X")), start=1):
        od = pack / ("order-%d" % k)
        od.mkdir()
        (od / "CRITIC.md").write_text(pair_brief(manifest, pack, od, first, second, k), encoding="utf-8", newline="\n")
        briefs.append(str(od / "CRITIC.md"))
    manifest["critic"] = briefs
    write_json(pack / "manifest.json", manifest)                # blind: no file names, no roles
    write_json(root / KEYS / ("round-%d.json" % n), {
        "round": n, "X": {"video": str(by_label["X"]), "role": role["X"]},
        "Y": {"video": str(by_label["Y"]), "role": role["Y"]},
        "sources": {lab: {"scenes": pre[i]["scenes_source"], "transcript": texts[lab][1] or None}
                    for i, lab in enumerate(LABELS)},
        "new": {"video": str(new), "label": "X" if x_is_new else "Y"},
        "old": {"video": str(old), "label": "Y" if x_is_new else "X", "found": how}})
    (pack / "INCOMPLETE").unlink()
    if job and (job / "job.json").is_file():
        try:
            from ..job import ledger
            ledger.note(job, pointers=["review=%s" % briefs[0]],
                        event="pairwise review pack round %d built (%s against %s)" % (n, new.name, old.name))
        except Exception:  # noqa: BLE001
            pass
    manifest.update({"dir": str(pack), "key": str(root / KEYS / ("round-%d.json" % n)), "seconds": round(time.time() - t0, 1),
                     "qa": {lab: sides[lab]["qa"] for lab in LABELS}})
    return manifest


def _rel(p: Optional[str], base: Path) -> str:
    """A pack file relative to the brief's folder (../X/frames/...), so the critic never sees the job's path."""
    if not p:
        return "(none)"
    try:
        return Path(os.path.relpath(Path(p).resolve(), base.resolve())).as_posix()
    except ValueError:                         # another drive on Windows
        return str(p)


def _side_block(s: Dict[str, Any], base: Path) -> str:
    r = _rel
    lab = s["label"]
    frames = "\n".join("  - %s at %.2fs: `%s`" % (f["label"], f["t"], r(f["path"], base)) for f in s["frames"])
    crops = "\n".join("  - %.2fs (%s), text about %d px tall: `%s`" % (c["t"], c["label"], c["line_px"], r(c["path"], base))
                      for c in s["text_crops"]) or "  - (no text lines found; open the full-size frames instead)"
    return """## Video {lab} ({w}x{h}, {fps:.3g} fps, {dur:.2f}s)
- Automated QA: {verdict}, details in `{qa}`
- Contact sheet at the shared times: `{sheet}`
- Every frame around each cut ({ncuts} cuts): `{cuts}`
- Loudness over time: `{loud}`
- {hear}
- Narration transcript (you cannot hear it): `{tr}`
- The parts in order, each with its middle frame and its narration: `{story}`
- Thumbnail at feed size: `{thumb}`
- Frames at the matched times (the same times as the other video; past its end a card says so):
{frames}
- Text lines at full size (type detail pass):
{crops}
""".format(lab=lab, w=s["size"][0], h=s["size"][1], fps=s["fps"], dur=s["duration"], verdict=s["qa"]["verdict"],
           qa=r(s["qa"]["text"], base), sheet=r(s["sheet"], base), ncuts=len(s["cuts"]),
           cuts=r(s["cut_strips"], base), loud=r(s["loudness_graph"], base), tr=r(s["transcript"], base),
           story=r(s.get("story"), base),
           hear=("Sound, measured for the hearing pass (you cannot listen): `%s`, plotted in `%s`" % (
               r(s["hearing"]["text"], base), r(s["hearing"]["graph"], base)) if s.get("hearing") else
               "Sound, measured for the hearing pass: (none: no measured audio track)"),
           thumb=r(s["thumbnail_preview"], base), frames=frames, crops=crops)


def pair_brief(m: Dict[str, Any], pack: Path, od: Path, first: str, second: str, k: int) -> str:
    sides = m["sides"]
    ctx = "\n".join("- `%s`" % _rel(c, od) for c in m["context"]) or \
        "- (no brief or storyboard found: judge as a reasonable viewer would)"
    launch = ""
    rh = {lab: sides[lab].get("launch_rhythm") for lab in LABELS}
    if any(rh.values()):
        launch = review.LAUNCH_CHECKS.format(rhythm="; ".join("%s: %s" % (lab, rh[lab] or "(not measured)") for lab in LABELS))
    return """# Critic brief: pairwise round {n} of at most {maxr}, order {k} of 2 (video {a} first)

You are a helper for one task: compare two versions of one video, **{a}** and **{b}**, from the evidence
in this folder, and say which one you would ship. Do not run the showtime workflow, do not edit the
project, do not re-render, and do not dispatch other agents. The labels were assigned at random; which
version is newer is kept from you on purpose, and it does not matter: judge what you see. Another critic
judges the same pair in the other order; read only the files this brief lists (never another order-*
folder), and write only `FINDINGS.md` next to this brief.

Skill: {skill}
Paths below are relative to this brief's folder.

{side_a}
{side_b}
## Side by side
- `{cmp}`: the same moments, pairs of {a} (left) and {b} (right).

Context (what the video was asked to be):
{ctx}
{launch}
{first_viewer}

{hearing}

## How to judge
Look at every image of {a}, then every image of {b}, before writing. Measure geometry in pixels on the
full-size frames, not by eye on the sheets. You cannot hear either video: judge sound from each video's
`audio.txt`, `hearing.png`, loudness plot and transcript (the hearing pass above), and list what they cannot
show under DECLINED TO JUDGE. When the brief is silent, judge by what a reasonable viewer on the target
platform expects.

{questions}
Weigh them for both videos. Then prefer one: the one you would ship. Answer "tie" only when you truly
cannot choose. **No scores**: do not rate either video on a number scale; the preference and the findings
carry the judgment.

Then judge each video on its own, {absolute}

{severity}

Rule: **every finding names its video ([{a}] or [{b}]), cites a timestamp and a frame path** from this
folder. A finding without a video, a time or a frame is dropped. Quote numbers (sizes, seconds, colours)
in fixes.

## Answer in exactly this format (write it to FINDINGS.md next to this brief)
```
PREFERENCE: {a} | {b} | tie  -- one line: the one you would ship, and why
VERDICT {a}: ship | ship after fixes | not ready
VERDICT {b}: ship | ship after fixes | not ready
WOULD I POST {a}: yes | no  -- one reason, judged on {a} alone (not against {b})
WOULD I POST {b}: yes | no  -- one reason, judged on {b} alone (not against {a})
FIRST VIEWER (one line per part of each video's story.txt; every "no" is also listed below):
- [{a}] part 1 (0.00-8.20s) ../{a}/frames/...jpg: yes | no  -- why
HEARING (one line per check of the hearing pass, per video; every problem is also listed below):
- [{a}] voice over music: ok | problem  -- the numbers from its audio.txt
WHAT WORKS (max 3 per video, so it is kept):
- [{a}] ...
BLOCKERS:
- [{b}] t=12.40s ../{b}/frames/t0012.400s.jpg  problem -> concrete fix
SHOULD-FIX:
- ...
POLISH:
- ...
DECLINED TO JUDGE (what you could not or chose not to assess, e.g. how the voice sounds):
- ...
BEST POSTER FRAME: [{a} or {b}] t=..s because ...
```
""".format(n=m["round"], maxr=m["max_rounds"], k=k, a=first, b=second, skill=review._skill_dir(),
           side_a=_side_block(sides[first], od), side_b=_side_block(sides[second], od),
           cmp=_rel(m["compare"][first + second], od), ctx=ctx, launch=launch,
           questions=review.QUESTIONS.replace("open every text crop above", "open every text crop listed")
           .replace("Answer these eight questions for yourself first", "Answer these eight questions for each video first"),
           severity=review.SEVERITY, absolute=review.ABSOLUTE,
           hearing=review.hearing_brief("each video's `audio.txt` and `hearing.png`")
           .replace("You cannot hear this video.", "You cannot hear either video.")
           .replace("Write one line per check under HEARING (`- voice", "Write one line per check and video under HEARING (`- [%s] voice" % first)
           .replace("finding under the usual severities, with its time\nand `hearing.png`",
                    "finding under the usual severities, with its video, its time\nand that video's `hearing.png`"),
           first_viewer=review.FIRST_VIEWER.format(story="each video's `story.txt` (first %s, then %s)" % (first, second))
           .replace("Write one line per part under FIRST VIEWER: `- part 2",
                    "Write one line per part under FIRST VIEWER, tagged with its video: `- [%s] part 2" % first))


# ------------------------------------------------------------------ findings and the verdict

HEAD = re.compile(r"^\s*(BLOCKERS?|SHOULD[- ]FIX|POLISH|WHAT WORKS|DECLINED TO JUDGE|BEST POSTER FRAME|VERDICT|PREFERENCE|"
                  r"WOULD I POST|PREVIOUS|FIRST[- ]VIEWER|HEARING)\b", re.I)
SEV_OF = {"BLOCKER": "blocker", "BLOCKERS": "blocker", "SHOULD-FIX": "should-fix", "SHOULD FIX": "should-fix",
          "POLISH": "polish"}
T_RE = re.compile(r"\bt\s*=\s*(\d+(?:\.\d+)?)\s*s\b", re.I)
FRAME_RE = re.compile(r"[\w./\\-]+\.(?:jpe?g|png)\b", re.I)
LABEL_RE = re.compile(r"\[\s*([XY])\s*\]")


def parse_findings(text: str) -> Dict[str, Any]:
    """PREFERENCE, per-video verdicts and located findings from one order's FINDINGS.md."""
    pref = None
    verdicts: Dict[str, str] = {}
    items: List[Dict[str, Any]] = []
    dropped: List[str] = []
    sev = None
    for raw in text.splitlines():
        line = raw.strip().strip("`")
        h = HEAD.match(line)
        if h:
            word = h.group(1).upper()
            rest = line[h.end():]
            sev = SEV_OF.get(word.replace("  ", " "))
            if word == "PREFERENCE":
                val = re.split(r"\s--\s|\s-\s|\s—\s", rest.lstrip(" :"), maxsplit=1)[0].strip().strip("*").strip()
                toks = re.findall(r"\b(X|Y|tie|neither|none)\b", val, re.I)
                if len(toks) == 1 or (toks and "|" not in val):
                    tok = toks[0]
                    pref = tok.upper() if tok.upper() in LABELS else "tie"
            elif word == "VERDICT":
                m = re.match(r"\s*([XY])\s*:\s*(.+)", rest)
                if m:
                    verdicts[m.group(1)] = m.group(2).strip()
            continue
        bullet = re.match(r"(?:[-*]|\d+[.)])\s*", line)
        if sev and bullet:
            body = line[bullet.end():].strip()
            if not body or body.strip(".() ").lower() in ("none", "n/a", "", "..."):
                continue
            lab = LABEL_RE.search(body)
            fr = FRAME_RE.search(body)
            label = lab.group(1) if lab else None
            if label is None and fr:
                m = re.search(r"(?:^|[/\\])([XY])[/\\]frames", fr.group(0))
                label = m.group(1) if m else None
            t = T_RE.search(body)
            if not (label and t and fr):
                dropped.append(body)
                continue
            items.append({"severity": sev, "video": label, "t": float(t.group(1)), "frame": fr.group(0), "text": body})
    from ..job import review_state
    posts = review_state.parse_would_post(text)
    return {"preference": pref, "verdicts": verdicts, "findings": items, "dropped": dropped,
            "would_post": {k: v for k, v in posts.items() if k in LABELS},
            "self_review": text.lstrip().upper().startswith("SELF-REVIEW")}


def would_post(parsed: Sequence[Dict[str, Any]], label: str) -> Dict[str, Any]:
    """The absolute verdict on one version across both orders: "no" when either critic would not post it,
    "yes" when both would, None when a line is missing."""
    ans = [p.get("would_post", {}).get(label) for p in parsed]
    nos = [a for a in ans if a and a[0] == "no"]
    if nos:
        return {"answer": "no", "reason": "; ".join(a[1] for a in nos if a[1]) or None}
    if ans and all(ans):
        return {"answer": "yes", "reason": "; ".join(a[1] for a in ans if a[1]) or None}
    return {"answer": None, "reason": None}


def decide(pref1: Optional[str], pref2: Optional[str], new_label: str) -> Tuple[bool, str]:
    """The rule: the new version wins only when both orders prefer it; a tie or a split is no improvement."""
    if pref1 == new_label and pref2 == new_label:
        return True, "new preferred in both orders"
    if pref1 == pref2 and pref1 in LABELS:
        return False, "old preferred in both orders"
    if pref1 == "tie" and pref2 == "tie":
        return False, "tie in both orders"
    return False, "split or tie (order 1: %s, order 2: %s): not preferred in both orders" % (pref1 or "?", pref2 or "?")


def _round_dir(target: Optional[str], rnd: Optional[int]) -> Tuple[Path, int]:
    """(review root, round) from a round folder, a review root, or a job (latest pairwise round)."""
    t = Path(str(target)).expanduser() if target else None
    root: Optional[Path] = None
    if t is not None and t.is_dir() and re.fullmatch(r"round-\d+", t.name):
        return t.parent.resolve(), rnd or int(t.name.split("-")[1])
    if t is not None and t.is_dir() and (t / KEYS).is_dir():
        root = t.resolve()
    elif t is not None and t.is_dir() and (t / "review" / KEYS).is_dir():
        root = (t / "review").resolve()
    else:
        _, job = review.resolve_video(target, say=None)
        if job is None:
            raise ShowtimeError("no job or review folder found for %s" % (target or "the current job"),
                                hint="pass the round folder (…/review/round-N)")
        root = job / "review"
    if rnd:
        return root, rnd
    rounds = [n for n in review._rounds(root) if (root / KEYS / ("round-%d.json" % n)).is_file()]
    if not rounds:
        raise ShowtimeError("%s has no pairwise round" % root,
                            hint="build one with showtime review-pack <job> --against best (or an older render)")
    return root, rounds[-1]


def verdict(target: Optional[str] = None, rnd: Optional[int] = None) -> Dict[str, Any]:
    root, n = _round_dir(target, rnd)
    pack = root / ("round-%d" % n)
    key = _read(root / KEYS / ("round-%d.json" % n))
    if not isinstance(key, dict):
        raise ShowtimeError("round-%d is not a pairwise round (no key in %s)" % (n, root / KEYS),
                            hint="review-verdict judges rounds built with review-pack --against")
    from ..job import findings as gate
    parsed = []
    for k in (1, 2):
        f = pack / ("order-%d" % k) / "FINDINGS.md"
        if not (f.is_file() and f.stat().st_size > 0):
            raise ShowtimeError("round-%d has no answer for order %d yet (%s)" % (n, k, f),
                                hint="dispatch a fresh critic with only %s and ask for FINDINGS.md next to it"
                                     % (f.parent / "CRITIC.md"))
        text = f.read_text(encoding="utf-8", errors="replace")
        p = parse_findings(text)
        ids = {g["text"]: g["id"] for g in gate.parse(text, "r%do%d" % (n, k))}     # the ids review-respond takes
        for it in p["findings"]:
            fid = ids.get(" ".join(it["text"].strip("`").split()))
            if fid:
                it["id"] = fid
        if p["preference"] is None:
            raise ShowtimeError("%s has no readable PREFERENCE line (X, Y or tie)" % f,
                                hint="ask the critic to fix that one line; do not guess it")
        parsed.append(p)
    new_l, old_l = key["new"]["label"], key["old"]["label"]
    improved, why = decide(parsed[0]["preference"], parsed[1]["preference"], new_l)
    winner = "new" if improved else "old"
    best_label = new_l if improved else old_l
    role = {new_l: "new", old_l: "old"}
    findings = []
    for k, p in enumerate(parsed, start=1):
        for it in p["findings"]:
            findings.append(dict(it, order=k, role=role[it["video"]]))
    order_sev = {"blocker": 0, "should-fix": 1, "polish": 2}
    open_best = sorted([f for f in findings if f["video"] == best_label], key=lambda f: (order_sev[f["severity"]], f["t"]))
    answered = review.critic_rounds(root)
    cap = len(answered) >= review.MAX_ROUNDS
    best_video = key[winner]["video"]
    res = {"round": n, "improved": improved, "reason": why, "winner": winner, "best": best_video,
           "new": key["new"]["video"], "old": key["old"]["video"], "labels": {new_l: "new", old_l: "old"},
           "preferences": [p["preference"] for p in parsed],
           "blind": not any(p["self_review"] for p in parsed), "open_findings": open_best,
           "findings": findings, "dropped": [d for p in parsed for d in p["dropped"]],
           "rounds_used": len(answered), "max_rounds": review.MAX_ROUNDS, "cap_reached": cap,
           "blockers_open": sum(1 for f in open_best if f["severity"] == "blocker"),
           "would_post": would_post(parsed, best_label),
           "would_post_new": would_post(parsed, new_l)["answer"]}
    if cap:
        res["next"] = "round cap reached: ship %s with its open findings listed%s" % (
            Path(best_video).name, "; blockers are open, so show them to the user, who decides" if res["blockers_open"] else "")
    elif res["would_post"]["answer"] != "yes":
        res["next"] = ("%s is the best version, but %s: fix what the critics named and pair again (--against best)"
                       % (Path(best_video).name, "a critic would not post it (%s)" % (res["would_post"]["reason"] or "no reason")
                          if res["would_post"]["answer"] == "no" else
                          "a critic left out the WOULD I POST line; ask for it, then rerun review-verdict"))
    elif improved:
        res["next"] = ("keep %s; fix its open findings and pair the next render with showtime review-pack <job> "
                       "--against best, or ship it" % Path(best_video).name)
    else:
        res["next"] = ("not an improvement: %s stays the best version. Fix and pair again (--against best), or ship %s "
                       "with its open findings listed" % (Path(best_video).name, Path(best_video).name))
    write_json(pack / "verdict.json", res)
    (pack / "VERDICT.md").write_text(verdict_md(res), encoding="utf-8", newline="\n")
    prev = _read(root / "best.json")
    hist = (prev.get("history") if isinstance(prev, dict) else None) or []
    hist = [h for h in hist if h.get("round") != n] + [{"round": n, "improved": improved, "best": best_video}]
    write_json(root / "best.json", {"video": best_video, "round": n, "open_findings": open_best, "history": hist})
    job = root.parent if (root.parent / "job.json").is_file() else None
    if job:
        try:
            from ..job import ledger
            ledger.note(job, pointers=["review_verdict=%s" % (pack / "VERDICT.md")],
                        event="review verdict round %d: %s (%s)" % (n, "new version wins" if improved else "no improvement", why))
        except Exception:  # noqa: BLE001
            pass
    res["dir"] = str(pack)
    return res


def verdict_md(v: Dict[str, Any]) -> str:
    out = ["# Pairwise verdict, round %d" % v["round"], "",
           "- New: `%s`; old: `%s`" % (v["new"], v["old"]),
           "- Preferences: order 1 %s, order 2 %s (%s)" % (v["preferences"][0], v["preferences"][1],
                                                          ", ".join("%s = %s" % kv for kv in sorted(v["labels"].items()))),
           "- Result: **%s** (%s)" % ("improvement" if v["improved"] else "not an improvement", v["reason"]),
           "- Best so far: `%s`" % v["best"], "- Rounds: %d of %d" % (v["rounds_used"], v["max_rounds"])]
    wp = v.get("would_post") or {}
    out.append("- Would the critics post the best version: **%s**%s (absolute, independent of the comparison)" % (
        wp.get("answer") or "not answered", (" (%s)" % wp["reason"]) if wp.get("reason") else ""))
    if not v["blind"]:
        out.append("- Not blind: at least one order is a self-review by the maker, who knows which is new; say so to the user")
    out += ["- Next: %s" % v["next"], "", "## Open findings of the best version"]
    out += ["- %s%s [%s, order %d] %s" % (f["severity"].upper(), " %s" % f["id"] if f.get("id") else "", f["role"], f["order"],
                                          f["text"]) for f in v["open_findings"]] or ["- (none)"]
    if any(f.get("id") for f in v["open_findings"]):
        out += ["", "Before delivery each blocker and should-fix above is fixed or waived: "
                "`showtime review-respond <job> --fixed <id> \"what changed\"` or `--waive <id> \"why\"`."]
    if v["dropped"]:
        out += ["", "## Dropped (no video, time or frame)"] + ["- %s" % d for d in v["dropped"]]
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------ CLI printing

def print_pack(m: Dict[str, Any]) -> None:
    print("pairwise review pack round %d  (X qa %s, Y qa %s)" % (m["round"], m["qa"]["X"]["verdict"], m["qa"]["Y"]["verdict"]))
    for lab in LABELS:
        s = m["sides"][lab]
        print("  %s  %.2fs  sheet %s, %d frames, %d cuts" % (lab, s["duration"], s["sheet"], len(s["frames"]),
                                                            len(s["cuts"])))
    print("  compare   %s" % "  ".join(m["compare"].values()))
    print("  briefs    %s" % "\n            ".join(m["critic"]))
    print("  key       %s  (which label is which; never give it to a critic)" % m["key"])
    print("  next: dispatch two fresh critics at once, each with only one brief's path, each writing FINDINGS.md next "
          "to its brief; then run showtime review-verdict %s" % m["dir"])
    print(m["dir"])


def print_verdict(v: Dict[str, Any]) -> None:
    print("round %d: %s (%s)" % (v["round"], "IMPROVEMENT: the new version wins" if v["improved"] else "NOT AN IMPROVEMENT",
                                 v["reason"]))
    print("  best      %s" % v["best"])
    wp = v.get("would_post") or {}
    print("  post it?  %s%s" % (wp.get("answer") or "not answered (a WOULD I POST line is missing)",
                                ("  (%s)" % wp["reason"]) if wp.get("reason") else ""))
    if not v["blind"]:
        print("  note      a self-review is not blind (the maker knows which is new): tell the user")
    nb = {s: sum(1 for f in v["open_findings"] if f["severity"] == s) for s in ("blocker", "should-fix", "polish")}
    print("  open      %d blocker, %d should-fix, %d polish (in %s)" % (nb["blocker"], nb["should-fix"], nb["polish"],
                                                                        Path(v["dir"]) / "VERDICT.md"))
    if v["dropped"]:
        print("  dropped   %d finding(s) without a video, time or frame" % len(v["dropped"]))
    print("  next: %s" % v["next"])

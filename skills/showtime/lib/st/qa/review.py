"""`showtime review-pack <job|video>`: everything a critic needs, as files.

The critic (a fresh sub-agent, or a person) gets a folder, never the session:
contact sheets (1 per second, every scene, every transition midpoint), key
frames, full-size crops of the largest text lines (the type detail pass), a loudness graph, the sound measured
for the hearing pass (audio.txt and hearing.png, st.qa.hearing), the qa verdict, copies of the brief/storyboard/ledger
and a CRITIC.md brief with the severity scale and the answer format. Each pack
is one round: review/round-1/, review/round-2/. The protocol allows three critic
rounds; a round counts once a critic's FINDINGS.md is in it, so a round without
one (the critic has not answered yet, a newer final, an interrupted pack) is
rebuilt in place instead of using up a round. `--against` builds a blind pairwise
round instead (st.qa.pairwise: old vs new, judged in both orders).
"""
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .. import ff
from ..common import ShowtimeError, log, read_json, write_json
from . import images, media
from . import video as qa_video

PathLike = Union[str, "os.PathLike[str]"]

MAX_ROUNDS = 3
CONTEXT_NAMES = ("brief.md", "storyboard.md", "script.md", "plan.md", "SHOWTIME.md", "share.txt", "share-copy.txt",
                 "credits.txt", "CREDITS.txt", "decisions.md", "feedback.md", "vo.srt", "captions.srt", "final.srt",
                 "mix.report.json", "brand.md")


def resolve_video(target: Optional[PathLike], say: Any = None) -> Tuple[Path, Optional[Path]]:
    """(video, job folder or None) for a video file, a job folder or slug, or None (the current job).

    A job resolves to its latest final (else preview) from job.json "outputs", falling back to the
    newest final*/preview* file, so a re-render (final-2.mp4) is what gets reviewed.
    """
    from ..job import ledger
    t = Path(str(target)).expanduser() if target not in (None, "") else None
    if t is not None and t.is_dir() and not ledger.is_job(t.resolve()) and ledger.enclosing_job(t) is None:
        rj = read_json(t / "render.json", None) if (t / "render.json").is_file() else None
        if isinstance(rj, dict) and rj.get("output") and Path(rj["output"]).is_file() and not ledger.is_span_report(rj):
            return Path(rj["output"]), None
    try:
        video, job, _ = ledger.media_arg(target, "video", say=say)
    except ShowtimeError as e:
        raise ShowtimeError("no video found for %s: %s" % (target or "the current job", e),
                            hint="pass a video file, or a job folder with a render (render first)")
    return video, job


def render_report(video: Path) -> Optional[Dict[str, Any]]:
    """render.json for a video: <video>.work/render.json (render -o) or render.json beside it."""
    for rj in (video.with_suffix(".work") / "render.json", video.parent / "render.json"):
        data = read_json(rj, None) if rj.is_file() else None
        if isinstance(data, dict) and (not data.get("output") or Path(str(data["output"])).name == video.name):
            return data
    return None


# ------------------------------------------------------------------ planned scene boundaries

def _offset(video: Path) -> float:
    """Start of the rendered range (render --from) so project times map onto the file."""
    rj = render_report(video)
    rng = (rj or {}).get("range") if isinstance(rj, dict) else None
    try:
        return float(rng[0]) if rng else 0.0
    except (TypeError, ValueError, IndexError):
        return 0.0


def scene_clips(clips: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The top-level clips that are scenes, not overlay layers (a kicker, a name card, a persistent map
    inset, a caption strip): <section> / class "scene" clips when the page has two or more; otherwise
    every top-level clip minus those that run open-ended over later clips or sit inside another clip's
    window (an overlay is shown during a scene; scenes follow each other)."""
    top = [c for c in clips if c.get("parent") is None and c.get("t0") == c.get("t0") and c["t0"] != float("inf")]

    def is_scene(c: Dict[str, Any]) -> bool:
        cls = c["attrs"].get("class", "").split()
        return c["tag"] == "section" or "scene" in cls or "data-scene" in c["attrs"]
    marked = [c for c in top if is_scene(c)]
    if len(marked) >= 2:
        return marked
    inf = float("inf")

    def end(c: Dict[str, Any]) -> float:
        t1 = c.get("t1", inf)
        return inf if t1 != t1 else t1
    starts = [c["t0"] for c in top]
    # open-ended with later clips starting under it: a persistent layer; data-overlay: said so
    cands = [c for c in top if "data-overlay" not in c["attrs"]
             and not (end(c) == inf and any(t > c["t0"] + 1e-6 for t in starts))]
    out = []
    for c in cands:
        t0, t1 = c["t0"], end(c)
        inside = any(o is not c and o["t0"] <= t0 + 1e-6 and end(o) >= t1 - 1e-6
                     and (o["t0"] < t0 - 1e-6 or end(o) > t1 + 1e-6) for o in cands)
        if not inside:   # shown during another clip: an overlay
            out.append(c)
    return out


def _clip_scenes(proj: Path) -> List[Tuple[float, str]]:
    """Scene clips of the project's index.html (resolved like the stage runtime; overlays left out)."""
    page = proj / "index.html"
    if not page.is_file():
        return []
    try:
        from ..cli_core import _Tags  # stdlib-only clip resolver shared with `showtime retime`
        clips = _Tags(page.read_text(encoding="utf-8", errors="replace")).resolve()
    except Exception:  # noqa: BLE001 - an unparsable page falls back to detection
        return []
    return [(float(c["t0"]), c.get("id") or c["attrs"].get("data-name") or c["tag"]) for c in scene_clips(clips)]


CUE_PAIR = re.compile(r"(?<![\w$.'\"])([A-Za-z_$][\w$]*)\s*:\s*(-?\d*\.?\d+(?:[eE][-+]?\d+)?)(?![\w.])")


def _cue_scenes(proj: Path) -> List[Tuple[float, str]]:
    """A canvas film's `CUE.acts = [[CUE.x, 'Label'], ...]` (cues.js or index.html). Every `key: number`
    pair in the CUE object counts, also several on one line (`burnAt: 8.171, arrive: 8.571,`)."""
    for f in [proj / "cues.js", proj / "index.html", proj / "scenes.js"]:
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"\bCUE\s*=\s*\{(.*?)\n?\};", text, re.S)
        cue: Dict[str, float] = {}
        if m:
            for k, v in CUE_PAIR.findall(m.group(1)):
                cue.setdefault(k, float(v))
        a = re.search(r"CUE\.acts\s*=\s*\[(.*?)\]\s*;", text, re.S)
        if not a:
            continue
        out = []
        for ref, lab in re.findall(r"\[\s*(CUE\.[A-Za-z_]\w*|-?\d*\.?\d+)\s*,\s*['\"]([^'\"]*)['\"]", a.group(1)):
            t = cue.get(ref[4:]) if ref.startswith("CUE.") else float(ref)
            if t is not None:
                out.append((float(t), lab))
        if out:
            return out
    return []


def _chapter_list(v: Any) -> List[Tuple[float, str]]:
    """showtime.json "scenes"/"chapters": numbers, [t, label] pairs or {t|s|start, label|name|id}."""
    out: List[Tuple[float, str]] = []
    for i, x in enumerate(v if isinstance(v, list) else []):
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            out.append((float(x), "scene %d" % (i + 1)))
        elif isinstance(x, (list, tuple)) and x and isinstance(x[0], (int, float)):
            out.append((float(x[0]), str(x[1]) if len(x) > 1 else ""))
        elif isinstance(x, dict):
            t = next((x[k] for k in ("start", "t", "s") if isinstance(x.get(k), (int, float))), None)
            if t is not None:
                out.append((float(t), str(x.get("label") or x.get("id") or x.get("name") or "")))
    return out


def _voice_scenes(proj: Path) -> List[Tuple[float, str]]:
    tl = read_json(proj / "voice" / "timeline.json", None) if (proj / "voice" / "timeline.json").is_file() else None
    out = []
    lines = tl.get("lines") if isinstance(tl, dict) else None
    for ln in lines if isinstance(lines, list) else []:
        if not isinstance(ln, dict):
            continue
        slot = ln.get("slot") or {}
        st = slot.get("start", ln.get("start"))
        if st is not None:
            out.append((float(st), str(ln.get("id") or "")))
    return out


def planned_scenes(video: Path, proj: Optional[Path], dur: float) -> Optional[Dict[str, Any]]:
    """Scene starts the maker planned, in video time: [(start, name)] + where they came from.

    Order: showtime.json "scenes", then "chapters" -> a film's CUE.acts -> scene clips (data-start
    <section>/.scene clips, else top-level clips that are not overlays) -> voice/timeline.json
    slots -> an edit's EDL report (segment output starts). None when there is nothing to go on
    (review-pack then detects cuts in the pixels)."""
    found: List[Tuple[float, str]] = []
    source = ""
    if proj is not None:
        cfg = read_json(proj / "showtime.json", {}) if (proj / "showtime.json").is_file() else {}
        for key in ("scenes", "chapters"):
            found = _chapter_list(cfg.get(key) if isinstance(cfg, dict) else None)
            if found:
                source = "showtime.json %s" % key
                break
        for fn, label in ((_cue_scenes, "the film's CUE.acts"), (_clip_scenes, "the project's clips (data-start)"),
                          (_voice_scenes, "voice/timeline.json")):
            if found:
                break
            found = fn(proj)
            source = label if found else ""
        if found:
            off = _offset(video)
            found = [(t - off, n) for t, n in found]
    if not found:
        rep = qa_video.edit_report(video)
        if rep and rep.get("segments"):
            found = [(float(s.get("out_start") or 0.0), "%s %.2fs" % (s.get("source"), float(s.get("src_start") or 0)))
                     for s in rep["segments"]]
            source = "the edit's EDL report"
    found = sorted({round(t, 3): n for t, n in found if -1e-6 <= t < dur - 0.05}.items())
    if len(found) < 2:
        return None  # one scene tells the critic nothing a cut detector would not
    return {"scenes": found, "source": source}


# ------------------------------------------------------------------ narration and the story in order

Cue = Tuple[float, float, str]


def narration(video: Path, proj: Optional[Path]) -> Tuple[List[Cue], str]:
    """(cues in video time, source): the narration of this render, from its own caption sidecar, else the
    project's voice timeline or caption files when they are not newer than the render (a re-voice after it
    would lie). ([], "") when there is none."""
    from . import captions as qa_captions
    for ext in (".srt", ".vtt", ".ass"):
        side = video.with_suffix(ext)
        if side.is_file():
            try:
                cues = qa_captions.parse(side)["cues"]
            except Exception:  # noqa: BLE001 - an unreadable sidecar is no narration
                continue
            return [(float(c["start"]), float(c["end"]), str(c["text"])) for c in cues], "its caption file %s" % side.suffix
    if proj is None:
        return [], ""
    try:
        vt = video.stat().st_mtime
    except OSError:
        return [], ""
    off = _offset(video)
    tl = proj / "voice" / "timeline.json"
    if tl.is_file() and tl.stat().st_mtime <= vt + 1:
        data = read_json(tl, {}) or {}
        from .hearing import line_offsets
        moved = line_offsets(proj, data) if isinstance(data, dict) else {}   # where the mix plays each line
        out: List[Cue] = []
        for ln in (data.get("lines") if isinstance(data, dict) else None) or []:
            if isinstance(ln, dict) and ln.get("text") and ln.get("start") is not None:
                o = off - moved.get(str(ln.get("id")), 0.0)
                a = float(ln.get("speech_start", ln["start"])) - o
                b = float(ln.get("speech_end", ln.get("end", a))) - o
                out.append((a, b, str(ln["text"])))
        if out:
            return out, "the voice timeline"
    for f in (proj / "voice" / "vo.srt", proj / "vo.srt", proj / "captions.srt", proj / "final.srt"):
        if f.is_file() and f.stat().st_mtime <= vt + 1:
            try:
                cues = qa_captions.parse(f)["cues"]
            except Exception:  # noqa: BLE001
                continue
            return [(float(c["start"]) - off, float(c["end"]) - off, str(c["text"])) for c in cues], "the project's captions"
    return [], ""


def cue_lines(cues: Sequence[Cue]) -> str:
    return "\n".join("[%7.2fs - %7.2fs] %s" % (a, b, " ".join(t.split())) for a, b, t in cues if t.strip())


NO_NARRATION = ("(no narration transcript: no caption file or voice timeline belongs to this render. If it has a voice, "
                "judge from the on-screen text and say so under DECLINED TO JUDGE)")


def story_text(parts: Sequence[Tuple[float, float, str, Optional[str]]], cues: Sequence[Cue], source: str,
               where: str = "this folder") -> str:
    """The video in order, as a first-time viewer meets it: each part (start, end, name, frame path) with the
    narration said during it (a line belongs to the part it starts in). For the critic's first-viewer pass."""
    out = ["# The video in order, as a first-time viewer meets it",
           "",
           "Each part, the frame at its middle and the narration said during it (you cannot hear the video; this is "
           "the voice). Frame paths are relative to %s. For the first-viewer pass: judge from this, the contact "
           "sheet and the frames, before you read the brief." % where, ""]
    spoken = [c for c in cues if c[2].strip()]
    for i, (a, b, name, frame) in enumerate(parts):
        last = i == len(parts) - 1
        out.append("part %d  %.2f-%.2fs%s  frame: %s" % (i + 1, a, b, "  (%s)" % name if name else "",
                                                         "`%s`" % frame if frame else "(see the contact sheet)"))
        mine = [c for c in spoken if (a - 0.05 <= c[0] < b - 0.05) or (last and c[0] >= b - 0.05) or (i == 0 and c[0] < a)]
        out += ["  " + ln for ln in cue_lines(mine).splitlines()] or ["  (no narration in this part)"]
        out.append("")
    out.append(("Narration from %s." % source) if spoken else NO_NARRATION)
    return "\n".join(out).rstrip() + "\n"


def _rounds(root: Path) -> List[int]:
    out = []
    for d in root.glob("round-*") if root.is_dir() else []:
        m = re.fullmatch(r"round-(\d+)", d.name)
        if m and d.is_dir():
            out.append(int(m.group(1)))
    return sorted(out)


def _has_findings(d: Path) -> bool:
    """A critic answered in this round (a pairwise round: in either order's folder)."""
    for f in [d / "FINDINGS.md"] + sorted(d.glob("order-*/FINDINGS.md")):
        if f.is_file() and f.stat().st_size > 0:
            return True
    return False


def _next_round(root: Path, force: bool = False) -> Tuple[int, bool]:
    """(round number, rebuild?) : the latest round is rebuilt while it has no FINDINGS.md."""
    rounds = _rounds(root)
    if not rounds:
        return 1, False
    last = rounds[-1]
    if not force and not _has_findings(root / ("round-%d" % last)):
        return last, True
    return last + 1, False


def open_round(root: Path, force_round: bool, video: Path, say: Any) -> Tuple[int, Path]:
    """Pick the round folder (the round cap, a rebuild of an unanswered round) and mark it INCOMPLETE."""
    n, rebuild = _next_round(root, force=force_round)
    answered = critic_rounds(root)
    if not rebuild and len(answered) >= MAX_ROUNDS and not force_round:
        raise ShowtimeError("%s already has %d critic rounds (FINDINGS.md in %s); the critic protocol stops at %d" % (
            root, len(answered), ", ".join("round-%d" % r for r in answered), MAX_ROUNDS),
            hint="ship the best version with its open findings listed (showtime review-verdict names it after a "
                 "pairwise round) and show them to the user instead of looping. Polish after a \"ship\" verdict needs "
                 "no new pack: snap before/after (showtime snap <video> --at T --compare <old video>), run qa, log it in "
                 "work/feedback.md. --force-round makes round %d anyway" % n)
    pack = root / ("round-%d" % n)
    if rebuild:
        say("review-pack: round-%d has no FINDINGS.md yet, so it is rebuilt for %s (a critic that answered in chat: save "
            "its answer as round-%d/FINDINGS.md first)" % (n, video.name, n))
        shutil.rmtree(pack, ignore_errors=True)
    pack.mkdir(parents=True)
    # an interrupted pack stays marked, so nobody hands it to a critic; the next run rebuilds it
    (pack / "INCOMPLETE").write_text("this pack is being built or was interrupted; run showtime review-pack again\n",
                                     encoding="utf-8")
    return n, pack


def critic_rounds(root: Path) -> List[int]:
    """Rounds a critic answered (FINDINGS.md present)."""
    return [n for n in _rounds(root) if _has_findings(root / ("round-%d" % n))]


VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".m4v")


def other_deliverables(video: Path, job: Optional[Path]) -> List[str]:
    """Videos in the job that this pack does not cover and that are not just older renders of it
    (variants such as final-16x9.mp4, final.square.mp4, exports/): the critic is told about them."""
    if not job:
        return []
    older = re.compile(r"^(final|preview)(-\d+)?(\.poster)?$")
    out = []
    for d in (job, job / "exports"):
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix.lower() not in VIDEO_EXTS or not f.is_file() or f.resolve() == video.resolve():
                continue
            if d == job and older.match(f.stem):
                continue
            out.append(str(f))
    return out[:12]


def _last_qa_args(video: Path, job: Optional[Path]) -> Dict[str, Any]:
    """{lufs, platform} given explicitly to the last `showtime qa` of this file (job ledger), else {}."""
    if job is None:
        return {}
    try:
        from ..job import ledger
        rec = ledger.qa_of(ledger.load(job), video)
    except Exception:  # noqa: BLE001 - the ledger is a convenience
        return {}
    try:
        same = rec.get("video") and Path(str(rec["video"])).resolve() == video.resolve()
    except OSError:
        same = False
    return {k: rec.get(k) for k in ("lufs", "platform")} if same else {}


def build(target: Optional[PathLike] = None, *, out: Optional[PathLike] = None, project: Optional[PathLike] = None,
          expect_file: Optional[PathLike] = None, platform: Optional[str] = None, force_round: bool = False,
          every: Optional[float] = None, quiet: bool = False, lufs: Optional[float] = None) -> Dict[str, Any]:
    t0 = time.time()
    say = (lambda m: None) if quiet else log
    video, job = resolve_video(target, say=log)  # always say which file (stderr), even with --json
    root = Path(out).expanduser().resolve() if out else ((job / "review") if job else video.parent / (video.stem + ".review"))
    n, pack = open_round(root, force_round, video, say)
    (pack / "frames").mkdir(parents=True)
    pr = ff.probe(video)
    dur = float(pr.get("duration") or 0)
    fps = float(pr.get("fps") or 30.0)
    W, H = int(pr.get("width") or 0), int(pr.get("height") or 0)
    thumb = 400 if W >= H else 240

    if lufs is None or platform is None:
        # the fresh qa run judges like the last qa of this file: its --lufs / --platform carry over
        prev = _last_qa_args(video, job)
        if lufs is None and prev.get("lufs") is not None:
            lufs = float(prev["lufs"])
            say("review-pack: loudness target %g LUFS (from the last showtime qa --lufs of %s)" % (lufs, video.name))
        if platform is None and prev.get("platform"):
            platform = str(prev["platform"])
            say("review-pack: platform %s (from the last showtime qa --platform of %s)" % (platform, video.name))
    say("review-pack: running qa")
    q = qa_video.run(video, project=project, expect_file=expect_file, out_dir=pack / "qa", platform=platform,
                     lufs=lufs, quiet=True, record=True)
    proj = Path(q["project"]) if q.get("project") else None

    say("review-pack: finding scenes and transitions")
    planned = planned_scenes(video, proj, dur)
    names: Dict[float, str] = {}
    detected = media.scene_cuts(video, threshold=0.25)
    if planned is not None:
        scenes_source = planned["source"]
        starts = [a for a, _ in planned["scenes"]]
        names = {round(a, 3): n for a, n in planned["scenes"]}
        cuts = [c for c in starts if 0.1 < c < dur - 0.1]
        say("review-pack: %d scenes from %s" % (len(starts), scenes_source))
        # chapters (or CUE acts) are navigation: several scenes and hard cuts can sit inside one. Add
        # the project's clip starts and the cuts seen in the picture, so every real cut gets a strip.
        extra: List[Tuple[float, str, float]] = []
        if proj is not None and planned["source"] != "the project's clips (data-start)":
            off = _offset(video)
            extra += [(t - off, n, 0.15) for t, n in _clip_scenes(proj)]
        extra += [(t, "", 0.6) for t in detected]        # a transition's detected cut lands near its planned start
        added = 0
        for t, lab, win in sorted(extra, key=lambda x: (x[2], x[0])):     # named clip starts before picture cuts
            if not (0.1 < t < dur - 0.1) or any(abs(t - c) < win for c in cuts):
                continue
            cuts.append(round(t, 3))
            added += 1
            if lab:
                names.setdefault(round(t, 3), lab)
        cuts.sort()
        if added:
            scenes_source += " + %d cut%s inside them (clips, picture)" % (added, "" if added == 1 else "s")
            say("review-pack: +%d cuts between the planned scenes (project clips and the picture)" % added)
    else:
        scenes_source = "cut detection"
        cuts = detected
    bounds = sorted(set([0.0] + [c for c in cuts if 0.2 < c < dur - 0.2] + [dur]))
    scenes = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1) if bounds[i + 1] - bounds[i] > 0.15]

    # 1 fps sheet (capped), scenes sheet (scene middles + transition midpoints), key frames
    step = every or (1.0 if dur <= 48 else dur / 48.0)
    t_sheet = [media.clamp_time(i * step, dur, fps) for i in range(int(dur / step) + 1)]
    t_sheet = sorted(set(round(t, 3) for t in t_sheet))
    sheet_paths = media.extract_frames(video, t_sheet, pack / "sheet-frames", width=thumb, duration=dur, fps=fps)
    sheet = images.contact_sheet([{"path": str(p), "label": "%.2fs" % t, "sub": "f%d" % round(t * fps)}
                                  for p, t in zip(sheet_paths, t_sheet)], pack / "sheet.jpg", thumb=thumb,
                                 title="%s  %dx%d  every %.2gs" % (video.name, W, H, step))
    scene_items: List[Dict[str, Any]] = []
    scene_times: List[Tuple[float, str]] = []
    for i, (a, b) in enumerate(scenes):
        nm = names.get(round(a, 3))
        scene_times.append((media.clamp_time((a + b) / 2, dur, fps), "scene %d%s mid" % (i + 1, " (%s)" % nm if nm else "")))
    for c in cuts:
        if 0.1 < c < dur - 0.1:
            scene_times += [(media.clamp_time(c - 0.1, dur, fps), "cut %.2f -0.1" % c),
                            (media.clamp_time(c + 0.04, dur, fps), "cut %.2f mid" % c),
                            (media.clamp_time(c + 0.2, dur, fps), "cut %.2f +0.2" % c)]
    scene_times.sort()
    sp = media.extract_frames(video, [t for t, _ in scene_times], pack / "frames", width=min(W, 1280) or None,
                              duration=dur, fps=fps)
    for p, (t, lab) in zip(sp, scene_times):
        scene_items.append({"path": str(p), "label": lab, "sub": "%.2fs" % t})
    say("review-pack: narration and the parts in order")
    cues, narr_source = narration(video, proj)
    (pack / "transcript.txt").write_text((cue_lines(cues) or NO_NARRATION) + "\n", encoding="utf-8", newline="\n")
    mids = {lab: p for p, (t, lab) in zip(sp, scene_times) if lab.startswith("scene ") and lab.endswith(" mid")}
    parts = []
    for i, (a, b) in enumerate(scenes):
        nm = names.get(round(a, 3))
        fr = mids.get("scene %d%s mid" % (i + 1, " (%s)" % nm if nm else ""))
        parts.append((a, b, nm or "", _rel(str(fr), pack) if fr else None))
    (pack / "story.txt").write_text(story_text(parts, cues, narr_source), encoding="utf-8", newline="\n")
    scenes_sheet = images.contact_sheet(scene_items, pack / "scenes.jpg", thumb=thumb,
                                        title="%s  scenes and transitions (%d cuts, from %s)" % (
                                            video.name, len(cuts), scenes_source)) \
        if scene_items else None

    # frame-by-frame strips around each cut: double exposures and flashes live in 2-5 frames
    cut_sheet = None
    strip_items: List[Dict[str, Any]] = []
    for c in [c for c in cuts if 0.1 < c < dur - 0.1][:16]:
        k0 = int(round(c * fps))
        for k, p in media.extract_run(video, max(0, k0 - 2), 7, fps, pack / "cut-frames", width=thumb, duration=dur):
            strip_items.append({"path": str(p), "label": "cut %.2f %+df" % (c, k - k0), "sub": "%.3fs" % (k / fps)})
    if strip_items:
        cut_sheet = str(images.contact_sheet(strip_items, pack / "cuts.jpg", thumb=thumb, cols=7,
                                             title="%s  every frame from 2 before to 4 after each cut" % video.name))

    key: List[Tuple[float, str]] = [(0.0, "frame 0 (thumbnail in feeds)"), (0.5, "hook 0.5s"), (1.5, "hook 1.5s"),
                                    (media.clamp_time(dur, dur, fps), "last frame")]
    rj = render_report(video)
    poster_t = ((rj or {}).get("poster") or {}).get("time") if isinstance(rj, dict) else None
    if poster_t is not None:
        key.append((float(poster_t), "poster"))
    key = [(media.clamp_time(t, dur, fps), lab) for t, lab in key if t <= dur]
    kp = media.extract_frames(video, [t for t, _ in key], pack / "frames", width=min(W, 1280) or None, duration=dur, fps=fps)
    key_frames = [{"t": round(t, 3), "label": lab, "path": str(p)} for p, (t, lab) in zip(kp, key)]
    thumb_small = None
    if kp:
        src = next((Path(k["path"]) for k in key_frames if k["label"] == "poster"), Path(key_frames[0]["path"]))
        thumb_small = str(images.thumbnail_preview(src, pack / ("thumb-168x94.png" if W >= H else "thumb-94x168.png"),
                                                   (168, 94) if W >= H else (94, 168)))

    # type detail pass: the largest text lines at full resolution (sheets shrink away baselines and weights)
    say("review-pack: cropping text lines at full size")
    text_crops: List[Dict[str, Any]] = []
    try:
        from . import textcrops
        tsrc: List[Tuple[float, str]] = [(k["t"], k["label"]) for k in key_frames]
        tsrc += [(t, lab) for t, lab in scene_times if " mid" in lab and not lab.startswith("cut ")]
        tsrc = sorted({round(t, 3): lab for t, lab in tsrc}.items())
        tdir = pack / "text-frames"
        tp = media.extract_frames(video, [t for t, _ in tsrc], tdir, duration=dur, fps=fps, ext="png")
        text_crops = textcrops.crops([(t, lab, p) for (t, lab), p in zip(tsrc, tp)], pack / "frames")
        shutil.rmtree(tdir, ignore_errors=True)
    except Exception as e:  # noqa: BLE001 - the crops help the critic; they must not stop the pack
        say("review-pack: text crops skipped (%s)" % e)

    loud_png = loudness_png(pack / "qa", q, pack / "loudness.png", dur, video.name)
    hear = None
    try:
        from . import hearing
        say("review-pack: measuring the sound for the hearing pass")
        hear = hearing.for_pack(video, proj, q, pack / "qa", cuts=[c for c in cuts if 0.1 < c < dur - 0.1],
                                scenes=[(a, b, names.get(round(a, 3)) or "scene %d" % (i + 1)) for i, (a, b) in enumerate(scenes)],
                                out_dir=pack, name="this video", title=video.name)
    except Exception as e:  # noqa: BLE001 - the hearing material helps the critic; it must not stop the pack
        say("review-pack: hearing measurements skipped (%s)" % e)

    say("review-pack: copying context")
    ctx = pack / "context"
    ctx.mkdir()
    copied: List[str] = []
    # the packed video's own mix report (render writes <video>.work/audio/mix.report.json) comes first:
    # a job's work/ folder can hold another mix's report (a side mix, an earlier cut), and the critic
    # must judge the audio of the video it is watching
    from .hearing import own_mix_report
    own_mix = own_mix_report(video) or (video.with_suffix(".work") / "audio" / "mix.report.json")
    if own_mix.is_file() and own_mix.stat().st_size < 2_000_000:
        shutil.copy2(own_mix, ctx / "mix.report.json")
        copied.append(str(ctx / "mix.report.json"))
    search = [d for d in (job, proj, job / "studio" if job else None, proj / "studio" if proj else None,
                          job / "work" if job else None, proj / "audio" if proj else None) if d and d.is_dir()]
    for d in search:
        for name in CONTEXT_NAMES:
            if name == "mix.report.json" and own_mix.is_file():
                continue
            src = d / name
            if src.is_file() and src.stat().st_size < 2_000_000:
                dest = ctx / name
                if dest.exists():
                    dest = ctx / ("%s-%s" % (d.name, name))
                shutil.copy2(src, dest)
                copied.append(str(dest))
    for ext in (".srt", ".vtt"):
        side = video.with_suffix(ext)
        if side.is_file() and side.stat().st_size < 2_000_000 and not (ctx / side.name).exists():
            shutil.copy2(side, ctx / side.name)
            copied.append(str(ctx / side.name))
    if proj and (proj / "showtime.json").is_file():
        shutil.copy2(proj / "showtime.json", ctx / "showtime.json")
        copied.append(str(ctx / "showtime.json"))
    ck = proj / "work" / "check" / "report.json" if proj else None
    if ck and ck.is_file():
        shutil.copy2(ck, ctx / "check.json")
        copied.append(str(ctx / "check.json"))
        if (ck.parent / "sheet.jpg").is_file():
            shutil.copy2(ck.parent / "sheet.jpg", ctx / "check-sheet.jpg")
            copied.append(str(ctx / "check-sheet.jpg"))
    prev = [str(p) for p in sorted(root.glob("round-*/FINDINGS.md")) if p.parent != pack]

    manifest = {
        "round": n, "max_rounds": MAX_ROUNDS, "video": str(video), "job": str(job) if job else None,
        "project": str(proj) if proj else None, "duration": dur, "size": [W, H], "fps": fps,
        "qa": {"verdict": q["verdict"], "report": q["report"], "summary": q["summary"]},
        "sheet": str(sheet), "scenes_sheet": str(scenes_sheet) if scenes_sheet else None,
        "cuts": [round(c, 3) for c in cuts], "scenes": [[round(a, 3), round(b, 3)] for a, b in scenes],
        "scenes_source": scenes_source,
        "key_frames": key_frames, "scene_frames": [{"label": it["label"], "path": it["path"]} for it in scene_items],
        "text_crops": text_crops,
        "loudness_graph": loud_png, "thumbnail_preview": thumb_small, "context": copied,
        "hearing": {k: hear[k] for k in ("text", "graph", "summary")} if hear else None,
        "previous_findings": prev, "previous_ids": _previous_ids(root, pack),
        "transcript": str(pack / "transcript.txt"), "story": str(pack / "story.txt"),
        "narration_source": narr_source or None, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cut_strips": cut_sheet, "not_in_pack": other_deliverables(video, job),
        "missing_context": [] if (job or proj) else ["job", "project"],
    }
    write_json(pack / "manifest.json", manifest)
    (pack / "CRITIC.md").write_text(critic_brief(manifest, q, pack), encoding="utf-8", newline="\n")
    manifest["critic"] = str(pack / "CRITIC.md")
    manifest["dir"] = str(pack)
    manifest["seconds"] = round(time.time() - t0, 1)
    write_json(pack / "manifest.json", manifest)
    (pack / "INCOMPLETE").unlink()
    if job and (job / "job.json").is_file():
        try:
            from ..job import ledger
            ledger.note(job, pointers=["review=%s" % (pack / "CRITIC.md")],
                        event="review pack round %d built (qa %s)" % (n, q["verdict"]))
        except Exception:  # noqa: BLE001
            pass
    return manifest


def loudness_png(qa_dir: Path, q: Dict[str, Any], out: Path, dur: float, title: str) -> Optional[str]:
    """The loudness graph from a qa run's loudness.json (None when qa measured no audio)."""
    lj = read_json(qa_dir / "loudness.json", {})           # a silent video has no loudness.json
    loud = q.get("loudness") or {}
    if not (isinstance(lj, dict) and lj.get("short_term")):
        return None
    hop = float(lj.get("hop", 0.1))
    m, s = lj.get("momentary") or [], lj.get("short_term") or []
    tm = [i * hop + 0.4 for i in range(len(m))]
    ts = [i * hop + 3.0 for i in range(len(s))]
    # plot both on the momentary grid: short-term value at the same end time
    smap = {round(t, 2): v for t, v in zip(ts, s)}
    s_on_m = [smap.get(round(t, 2)) for t in tm]
    return str(images.loudness_graph(tm, m, s_on_m, out, target=loud.get("target_lufs"),
                                     integrated=loud.get("integrated_lufs"), true_peak=loud.get("true_peak_dbtp"),
                                     gaps=loud.get("silent_gaps") or [], duration=dur, title=title))


def _rel(p: Optional[str], base: Path) -> str:
    if not p:
        return "(none)"
    try:
        return Path(p).resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return str(p)


def _skill_dir() -> str:
    """The showtime skill folder, for the critic's `references/crew/...` briefs (any host, no variables)."""
    try:
        from ..common import skill_dir
        return str(skill_dir())
    except Exception:  # noqa: BLE001
        return str(Path(__file__).resolve().parents[3])


# Added to CRITIC.md for launch, promo, release and trailer films (qa's rhythm says launch): the premium
# grammar of references/workflows/launch-video.md, as checks a stranger can make from the pack.
LAUNCH_CHECKS = """
## Launch film checklist (judge these too; each miss is a Should-fix unless marked)
Measured by qa: {rhythm}
- Scenes: 4-6 in 20-45 s, one message each. A new layout per feature, or more than 6, reads as a slide deck.
- Scene changes: a shared element carried across (match) or a soft dissolve; at most one fly-through and one
  deliberate hard cut. A push, pan, wipe or whip on every beat is choppy.
- Holds: each scene's result is on screen, settled, for at least 1.5 s; nothing is frozen for more than ~3.5 s mid-film (the end card holds 3-4 s).
- Opening: frame 0 is the hook, complete and readable at phone size (a Blocker when it is blank or a logo).
- Type: one display face and one mono, headline >= 6 % of the frame height, commands and UI text >= 3.5 %;
  one accent colour on one ground for the whole film.
- Motion: every camera move must have a reason; if you can't say it, it is a finding (at most one fly-through,
  from the hook into the product; proof scenes and the end card hold a still camera). No punch-ins, shake,
  bounce, overshoot or pops; entrances ease out.
- Music: a produced track with dynamics (qa's music dynamics >= 3 dB); scene changes sit on its phrases; the
  name lands on its swell; it ends on a fade or a cadence. Effects on every cut are a finding.
- End card: name, one-line value, install command or CTA exactly as the sources give it, URL; held >= 3 s.
- Honesty: every command and output line matches the evidence in context/; any claim without a source is a Blocker.
"""


# Added to CRITIC.md instead of the launch checklist when the showreel tone is on (st.showreel: a showreel, a hype
# reel or a "go all out" brief). The round-1 blind vote (2026-10-02) went to the denser, louder reel: restraint loses
# this brief, so tame is a finding here.
SHOWREEL_CHECKS = """
## Showreel rubric (the showreel tone is on: judge these instead of restraint; each miss is a Should-fix unless marked)
Measured by qa: {rhythm}
The round-5 blind vote (2026-10-05) went to the reel that kept cutting to the last second (13-14 shots, no trick
twice, the name landing late and moving); the takes that repeated fewer, longer ideas and held their name 2.5-3.5 s
lost. Count these against the reel, each one a Should-fix:
- Long holds: any shot over ~2 s, and an end card that holds still over ~1 s of a 15 s reel (qa's showreel_long_end).
  The name lands on the last beats with about its reading time (~1.25 s) and keeps moving (a build, a sweep, a drift).
- Repeats: two shots with the same technique, ground or layout (qa's showreel_repeats lists look-alike pairs; check
  the sheet for the ones it misses, e.g. two particle shots in different colours). Two shots that show the same
  trick are one shot.
- Energy dips: any stretch over ~1 s before the end card where the reel sags (qa lists the dips; also a slow
  ease-in, a settled chart, a quiet beat in the music).
- Energy: from frame 0 the reel moves with intent; the cuts and the hits land on the music's beats (cuts.jpg and
  the hearing numbers). A reel a stranger would call calm, tasteful or corporate is a Should-fix: it loses this
  brief to a louder one, however clean it is.
- Density and variety: 12-14 shots per 15 s (under 12 is qa's showreel_sparse) and at least 8 distinct kinds from
  the menu: live data or a counter, words over a liquid shader, a 3D object, particles, kinetic type, a pattern
  system, glitch or RGB split, a camera move or tunnel, a morph or match cut. Name the kinds you count.
- Craft: every technique is executed well at full size: no banding in gradients and shaders, no aliased 3D edges,
  no particles popping in or out, no stuttering camera, no broken or half-drawn frames (the cut strips). One cheap
  shot spoils the reel (a Blocker when it is the opening or the last shot).
- Surprise: at least two moments a viewer would not predict (a transition that turns one shot into the next, a
  scale or a perspective jump, a type trick); if every shot is a stock effect, say which.
- Ending: it lands: a hit on the music, the name or the one message readable (the hero line), then out. An ending
  that just stops is a Should-fix.
- Flash words (texture: one to three words that leave before they can be read) are allowed and are not readability
  findings. The hero line is not texture: it must be readable at phone size for its full reading time.
- Safety: no more than 3 bright flashes in any second (qa's flash_risk); a strobe over that is a Blocker.
"""

QUESTIONS = """Answer these eight questions for yourself first; they are what the findings weigh:
1. Hook: at 1.5 s, does a stranger know what this is about and want to keep watching?
2. Clarity: after the whole video, could they say what it is, who it is for and how to get it?
3. Readability: is any text too small, too short-lived, low-contrast or in a platform UI zone?
4. Craft: alignment, spacing, consistent type and colour, clean transitions (check the mid-cut frames),
   no muddy double exposures, no effects the tone does not justify. Include the **type detail pass**:
   open every text crop above and every title or text frame in `frames/` at full size (never judge type
   from the sheets) and check, line by line: words, math and numbers on one line share one baseline
   (a formula, a superscript or a number must not sit lower or higher than the words beside it); they
   look one size (x-heights match) and one weight (thin math beside bold words reads broken); kerning
   and word spacing are even (no collisions, no gaps); no widow (one word alone on a last line) or
   orphaned punctuation. Any of these in a title, the hook or the poster is a Should-fix.
5. Distinctness: could these frames belong to a different product unchanged?
6. Poster: which single frame would you post as the thumbnail? Is frame 0 that frame?
7. Honesty: does anything look like an invented claim, number, testimonial or fake UI presented as real?
8. Story logic: go shot by shot through the scene list: what would a stranger think each shot is, and what
   job does it do (show the product, prove a claim, set up the next beat)? A shot that is only there because
   it looks good, or that only makes sense to the author, is a finding."""

# The showreel tone swaps the clarity and story questions (a reel is judged as a reel, not as an explainer).
SHOWREEL_QUESTIONS = QUESTIONS.replace(
    "2. Clarity: after the whole video, could they say what it is, who it is for and how to get it?",
    "2. Energy and density: would a stranger call it impressive, or tame? Count the shots, the distinct techniques,\n"
    "   the long holds, the repeats and the dips.").replace(
    "3. Readability: is any text too small, too short-lived, low-contrast or in a platform UI zone?",
    "3. Readability: is the hero line (the name, the one message) big, high-contrast and held long enough to read?\n"
    "   Flash words (one to three words of texture, gone in under a second) are allowed in a showreel.").replace(
    "8. Story logic: go shot by shot through the scene list: what would a stranger think each shot is, and what\n"
    "   job does it do (show the product, prove a claim, set up the next beat)? A shot that is only there because\n"
    "   it looks good, or that only makes sense to the author, is a finding.",
    "8. Surprise and ending: which moments would a viewer not predict, and does the ending land on the beat with the\n"
    "   hero line held? In a showreel a shot may be there because it looks good: that is its job.")

ABSOLUTE = """**would you post this under your own name?** Picture it on the target platform, watched once
at full size by someone who does not know the maker. The bar is "a stranger would not call it cheap, broken or
wrong", not "flawless": a video with should-fix and polish findings is usually still a yes (list them above).
Answer no only when a blocker stands, or when the video as a whole reads as cheap or unfinished at a glance:
captions in stepped boxes (one box per line, each a different width), a player's controls or a cursor left in
the footage, a small or soft recording inside big empty borders, a hook that shows nothing for seconds. One
flawed shot in an otherwise finished video is a should-fix, not a no. Judge this video alone, never "better
than before". In quality mode a "no" holds delivery like a blocker, so name what a stranger notices first."""

SEVERITY = """Severity:
- **Blocker**: an invented or wrong claim, a misspelled product or person name; black, frozen or garbage
  frames; wrong aspect or duration for the platform; clipped or missing voice; text cut off or outside the safe
  zone; a missing license credit.
- **Should-fix**: a part a first-time viewer cannot place (why it is here, how it connects to the opening; a
  Blocker when the opening never says what the video is about); a shot with no clear job or one a stranger would
  misread (a Blocker at the hook or payoff); text not readable at phone size or for as long as it is on screen; a title or text line whose parts sit on different baselines or differ in size or weight; music masking the voice;
  a dead stretch over ~2s; a level jump at a cut the story does not call for; music cut off on the last frame;
  off-brand colours; captions more than ~150 ms out of sync.
- **Polish**: easing taste, 1-2 frame timing, colour nuance."""


def _previous_ids(root: Path, pack: Path) -> List[Dict[str, Any]]:
    """The blockers and should-fixes of the earlier rounds, with the ids the PREVIOUS lines name (st.job.findings)."""
    job = root.parent
    if root.name != "review" or not (job / "job.json").is_file():
        return []
    try:
        from ..job import findings
        g = findings.collect(job)
    except Exception:  # noqa: BLE001 - the brief still lists the files
        return []
    return [{"id": f["id"], "severity": f["severity"], "text": f["text"], "status": f["status"]}
            for f in g["findings"] if pack.resolve() not in Path(f["file"]).resolve().parents]


FIRST_VIEWER = """## First-viewer pass (do it first, before you open the brief or `context/`)
You have never seen the brief. Go through {story} in order: each part's middle frame and the narration said
during it (you cannot hear the video, so that transcript is the voice), with the contact sheet for what happens
between them. For each part answer one question: **do I know why this part is here, and how it connects to what
the opening said the video is about?** Write one line per part under FIRST VIEWER: `- part 2 (8.00-21.50s)
<frame path>: yes | no -- why`. Every "no" is also a Should-fix with a concrete fix (a one-line spoken bridge from
the part before, the steps shown as a persistent roadmap with the current one lit, a cut). It is a Blocker when the
opening (about the first 10 s) never says what the video is about or why it matters; a video that asks the viewer
questions must say why before the first one. Only then read the context files."""


HEARING = """## Hearing pass (after the picture; you cannot listen)
You cannot hear this video. {files} measure what an ear would catch: each voice line's level over the music and
its words per minute, pauses and near silence, the level on both sides of every cut, each effect's timing and
level, how the music ends, the peaks. `transcript.txt` has the words with their times. Judge **only what those
numbers and the transcript support**, quote the numbers in the finding, and never guess at what they cannot
show (how the voice sounds, a mispronounced word, harsh s sounds, whether the music fits the mood): list those
under DECLINED TO JUDGE. Write one line per check under HEARING (`- voice over music: ok -- every line 12-17 dB
over the bed`, or `problem -- ...`); every problem is also a finding under the usual severities, with its time
and `hearing.png`:
1. Voice over the music: a line under {masked:g} dB over the bed is music masking the voice (Should-fix; a Blocker when
   the music is louder than the words, or at the hook or the payoff). "estimate" values overstate the music a
   little; say so when you rely on one.
2. Pace: a line over ~{fast:g} words a minute is rushed (Should-fix when it carries the main message, else Polish);
   a line that overlaps the next one, starts before the video or runs to its last frame is clipped (Blocker).
3. Silence: a pause in the voice or near silence over ~{quiet:g} s mid-video that nothing on screen carries is a dead
   stretch (Should-fix).
4. Level at cuts: a jump over {jump:g} LU that the story does not call for (no impact, no drop, no section change
   noted) is a Should-fix; 3-6 LU is Polish.
5. Effects: one more than ~0.1 s off the cut or CUE it belongs to is late or early (Should-fix on a hit the
   picture lands on, else Polish); one under the rest of the mix is not heard (Polish unless it carries a beat);
   one far over the programme (loud) startles (Should-fix).
6. Ending: sound still playing on the last frame is music cut off (Should-fix); music that stops more than
   1 s before the picture without a reason is Polish.
7. Peaks: clipping is a Blocker; a true peak over the ceiling is qa's finding to confirm."""

def hearing_brief(files: str) -> str:
    """The hearing pass section of a critic brief, with the thresholds qa uses (runtime/thresholds.json)."""
    from .hearing import thresholds
    th = thresholds()
    return HEARING.format(files=files, masked=th["voice_over_bed_min_db"], fast=th["fast_wpm"],
                          quiet=th["quiet_stretch_s"], jump=th["level_jump_lu"])


NO_HEARING = """## Hearing pass
The video has no measured audio track (qa says so): write `HEARING: no audio` and judge whether a silent video
suits the platform and the brief."""


def critic_brief(m: Dict[str, Any], q: Dict[str, Any], pack: Path) -> str:
    fails = [f for f in q.get("findings", []) if f["severity"] in ("FAIL", "WARN")]
    ctx_list = "\n".join("- `%s`" % _rel(c, pack) for c in m["context"]) or "- (no brief or storyboard found: judge as a reasonable viewer would)"
    key_list = "\n".join("- %s at %.2fs: `%s`" % (k["label"], k["t"], _rel(k["path"], pack)) for k in m["key_frames"])
    crops = m.get("text_crops") or []
    text_list = "\n".join("- %.2fs (%s), text about %d px tall: `%s`" % (c["t"], c["label"], c["line_px"],
                                                                        _rel(c["path"], pack)) for c in crops) \
        or "- (no text lines were found in the key and scene frames; if the video has on-screen text, open the " \
           "full-size frames in `frames/` instead)"
    qa_list = "\n".join("- %s %s%s: %s" % (f["severity"], f["rule"], " t=%.2fs" % f["t"] if f.get("t") is not None else "",
                                           f["message"]) for f in fails[:20]) or "- (no automated findings)"
    others = ""
    if m.get("not_in_pack"):
        others += ("\n## Not in this pack\nThe job also has these videos; judge only `%s`, and do not assume the others share "
                   "its problems or fixes:\n%s\n" % (Path(m["video"]).name, "\n".join("- `%s`" % x for x in m["not_in_pack"])))
    if m.get("missing_context"):
        others += ("\n## Missing context\nNo job or project was found for this video, so there is no brief, storyboard, "
                   "check report or plan here. Judge as a reasonable viewer would, and say so under DECLINED TO JUDGE.\n")
    rh = q.get("rhythm") or {}
    reel = bool((q.get("showreel") or {}).get("on") or rh.get("showreel"))
    if reel:
        others += SHOWREEL_CHECKS.format(rhythm=rh.get("summary") or "(not measured)")
    elif rh.get("launch"):
        others += LAUNCH_CHECKS.format(rhythm=rh.get("summary") or "(not measured)")
    prev = ""
    if m.get("previous_findings"):
        ids = m.get("previous_ids") or []
        idl = ("\nThe earlier blockers and should-fixes, by id (answer each one):\n" + "\n".join(
            "- %s (%s; the maker says: %s): %s" % (f["id"], f["severity"], f["status"] if f["status"] != "open" else
                                                  "nothing yet", f["text"][:160]) for f in ids) + "\n") if ids else ""
        prev = ("\n## This is round %d\nRead the previous findings first and judge only whether they were fixed, plus anything "
                "the fixes broke, and answer each under PREVIOUS (`fixed <id>: ...` or `not fixed <id>: ...`, naming what "
                "it was about, e.g. the captions). Do not reopen settled taste questions.\n%s\n%s" % (
                    m["round"], "\n".join("- `%s`" % p for p in m["previous_findings"]), idl))
    return """# Critic brief (round {round} of at most {maxr})

You are a helper for one task: review a finished video from the evidence in this folder. Do not run the
showtime workflow, do not edit the project, do not re-render, and do not dispatch other agents. You did not
make this video and owe it nothing. Everything you need is a file path below; the session that made it is
not available to you on purpose.

Skill: {skill}

## The video
- File: `{video}` ({w}x{h}, {fps:.3g} fps, {dur:.2f}s)
- Automated QA: **{verdict}** ({nf} fail, {nw} warn). Report: `{qa}`
- Contact sheet, one frame every ~1s: `{sheet}`
- Scenes and transitions (scene middles, each cut at -0.1s / midpoint / +0.2s): `{scenes}`
- Every frame around each cut (2 before to 4 after; double exposures and flashes hide here): `{cuts}`
- Loudness over time: `{loud}`
- {hearing_files}
- Thumbnail at feed size: `{thumb}`
- Narration, timed (you cannot hear it): `transcript.txt`
- The parts in order, each with its middle frame and its narration: `story.txt`

Key frames:
{keys}

Text lines cut from full-size frames (100 %, not scaled; for the type detail pass below):
{text_list}

Context (the brief, plan, ledger and reports the video was made against):
{ctx}

Automated findings to confirm or dismiss by looking at the frames:
{qa_list}
{others}{prev}
{first_viewer}

{hearing}

## How to judge
Look at every image above before writing. When the brief is silent, judge by what a reasonable viewer on the
target platform would expect (a vertical social cut is mostly watched muted, so missing captions matter).
Measure geometry (sizes, offsets, margins) in pixels on the full-size frames in `frames/`, not by eye on the
sheets. If the brief withholds something until a reveal (a name, a price), check every frame before the reveal.

{judging}
Rule: **every finding cites a timestamp and a frame path** from this folder (audio findings: a timestamp and
`hearing.png`). A finding without a location is dropped. Quote numbers (sizes, seconds, colours) in fixes. No scores: do not rate the
video on a number scale; the verdict and the findings carry the judgment.

Then the absolute verdict, {absolute}

## Answer in exactly this format (write it to FINDINGS.md in this folder)
```
VERDICT: ship | ship after fixes | not ready  -- one line of reasoning
WOULD I POST THIS: yes | no  -- one reason, judged on this video alone
FIRST VIEWER (one line per part of story.txt; every "no" is also listed below):
- part 1 (0.00-8.20s) frames/...jpg: yes | no  -- why
HEARING (one line per check of the hearing pass; every problem is also listed below):
- voice over music: ok | problem  -- the numbers from audio.txt
WHAT WORKS (max 3, so it is kept):
- ...
BLOCKERS:
- t=12.40s frames/t0012.400s.jpg  problem -> concrete fix
SHOULD-FIX:
- ...
POLISH:
- ...
DECLINED TO JUDGE (what you could not or chose not to assess, e.g. how the voice sounds, brand fit without a brand kit):
- ...
BEST POSTER FRAME: t=..s because ...
PREVIOUS (round 2+ only: one line per earlier blocker or should-fix, by its id):
- fixed r1-S2: <the finding>   |   not fixed r1-S2: <the finding> -> what is still wrong
```

Limits: at most {maxr} critic rounds per video. A later round checks only the fixes. If blockers remain
after the last one, stop: the maker shows your findings to the user instead of looping.
""".format(skill=_skill_dir(), round=m["round"], maxr=m["max_rounds"], video=m["video"], w=m["size"][0], h=m["size"][1], fps=m["fps"],
           dur=m["duration"], verdict=q["verdict"], nf=q["summary"]["fail"], nw=q["summary"]["warn"],
           qa=_rel(q["report"], pack), sheet=_rel(m["sheet"], pack), scenes=_rel(m["scenes_sheet"], pack),
           loud=_rel(m["loudness_graph"], pack), thumb=_rel(m["thumbnail_preview"], pack), keys=key_list, ctx=ctx_list,
           qa_list=qa_list, prev=prev, cuts=_rel(m.get("cut_strips"), pack), others=others, text_list=text_list,
           judging=(SHOWREEL_QUESTIONS if reel else QUESTIONS) + "\n\n" + SEVERITY + "\n", absolute=ABSOLUTE,
           first_viewer=FIRST_VIEWER.format(story="`story.txt`"),
           hearing_files=("Sound, measured for the hearing pass (you cannot listen): `%s`, plotted in `%s`" % (
               _rel(m["hearing"]["text"], pack), _rel(m["hearing"]["graph"], pack)) if m.get("hearing") else
               "Sound, measured for the hearing pass: (none: the video has no measured audio track)"),
           hearing=hearing_brief("`audio.txt` and `hearing.png`") if m.get("hearing") else NO_HEARING)

"""`showtime qa <video>`: evidence that a finished file is fit to hand over.

Checks the file itself (not the project or a preview): container and stream
settings, duration against the project, loudness and true peak against the
platform target, clipping, silent gaps, black and frozen runs, the first frame,
caption sidecars, required credits and the optional `expect` block in
showtime.json. Every finding carries a rule id, a severity (FAIL/WARN/INFO),
a timestamp when it has one, the path of the frame at that time, and a fix.

Verdict: FAIL when any FAIL finding exists, WARN when any WARN exists, else PASS.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .. import ff
from ..common import ShowtimeError, log, read_json, write_json
from . import captions as capmod
from . import phone as phonemod
from . import media
from . import floor
from . import hearing


_THRESHOLD_DEFAULTS = {"still_hold_s": 2.5, "launch_hold_s": 3.5, "final_hold_max_s": 4.0, "frozen_fail_s": 6.0, "freeze_noise_db": -50.0}
THRESHOLDS_FILE = Path(__file__).resolve().parents[3] / "runtime" / "thresholds.json"


def thresholds() -> Dict[str, float]:
    """Timing thresholds shared with `showtime check` and `showtime retime`
    (runtime/thresholds.json); the literals above are the fallback."""
    out = dict(_THRESHOLD_DEFAULTS)
    try:
        doc = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
        for k in out:
            if isinstance(doc.get(k), (int, float)) and doc[k] > 0:
                out[k] = float(doc[k])
        if isinstance(doc.get("freeze_noise_db"), (int, float)) and doc["freeze_noise_db"] < 0:
            out["freeze_noise_db"] = float(doc["freeze_noise_db"])
    except (OSError, ValueError):
        pass
    return out

PathLike = Union[str, "os.PathLike[str]"]

SEV_RANK = {"FAIL": 0, "WARN": 1, "INFO": 2}

# Extra platform presets beyond the export targets (lengths, loudness, size caps).
EXTRA_TARGETS: Dict[str, Dict[str, Any]] = {
    "web": {"width": None, "height": None, "max_duration": 30.0, "min_duration": 1.0, "lufs": None,
            "true_peak": None, "audio": False, "max_mb": 15, "note": "website hero loop: no audio track, small file"},
    "github": {"width": None, "height": None, "max_duration": None, "min_duration": 0.5, "lufs": -14.0,
               "true_peak": -1.0, "audio": None, "max_mb": 10, "note": "README/PR embed: 10 MB on free plans"},
    "chat": {"width": None, "height": None, "max_duration": None, "min_duration": 0.5, "lufs": -14.0,
             "true_peak": -1.0, "audio": None, "max_mb": 10, "note": "Slack/Discord/email: keep under 10 MB"},
    "broadcast": {"width": 1920, "height": 1080, "max_duration": None, "min_duration": 1.0, "lufs": -23.0,
                  "true_peak": -1.0, "audio": True, "max_mb": None, "note": "EBU R128"},
}

# Rule ids -> one-line description (also the documentation table in references/qa.md).
RULES = {
    "unreadable": "the file cannot be probed or decoded",
    "no_video": "there is no video stream",
    "odd_dimensions": "width or height is odd (breaks 4:2:0 players)",
    "codec": "video codec is not H.264 in an MP4",
    "pix_fmt": "pixel format is not yuv420p",
    "variable_fps": "frame rate is variable or unusual",
    "duration": "duration differs from the project/expect by more than the tolerance",
    "faststart": "the MP4 index is at the end (slow start on the web)",
    "color_tags": "BT.709 colour tags are missing",
    "no_audio": "there is no audio stream",
    "audio_codec": "audio is not AAC 48 kHz",
    "av_length": "audio and video lengths differ",
    "silent_audio": "the audio stream is silent",
    "loudness": "integrated loudness is off the platform target",
    "true_peak": "true peak is above the ceiling",
    "clipping": "the waveform is squared off at full scale",
    "leading_silence": "audio starts late",
    "silent_gap": "a silent stretch inside the video",
    "trailing_silence": "a long silent tail",
    "first_frame_black": "frame 0 is black (players and feeds show it as the thumbnail)",
    "first_frame_flat": "frame 0 is a flat colour",
    "poster_flash": "frame 0 differs sharply from frame 1 (a baked poster that flashes on autoplay and loops)",
    "poster_mismatch": "the delivered poster still is lighter or darker than its video frame (or its PNG carries colour chunks)",
    "black_segment": "a black stretch inside the video",
    "ends_black": "the video ends on black",
    "frozen": "the picture does not change for a long stretch",
    "final_hold": "the last seconds are a still hold",
    "dead_stop": "a fast move halts in one frame with no ease-out (reads as a glitch)",
    "flash_risk": "more than 3 general flashes in one second (photosensitivity: large, fast swings in brightness)",
    "showreel_sparse": "a showreel (showreel tone) with fewer shots than its density floor (12 per 15 s)",
    "showreel_long_end": "a showreel whose end card holds still over 10% of the reel (or whose last shot runs over 20%)",
    "showreel_repeats": "a showreel with two shots that look alike (the same technique or layout twice)",
    "held_shot": "a long held camera shot with sound (live footage, e.g. a speaker holding still; not frozen)",
    "phone_size": "text smaller than the phone minimum (points at 390 pt wide, per aspect; from showtime check)",
    "phone_reading": "text on screen for less than it takes to read (from showtime check)",
    "phone_zone": "text under platform UI, a player control strip or at the frame edge (from showtime check)",
    "phone_unverified": "the phone check could not verify type size, reading time or UI zones (no showtime check report)",
    "captions_past_end": "captions run past the end of the video",
    "captions_timing": "a caption ends before it starts",
    "captions_overlap": "two captions are on screen at once",
    "caption_lines": "a caption has more than two lines",
    "caption_line_long": "a caption line is too long to read",
    "caption_fast": "a caption needs more than 20 characters/s",
    "caption_flash": "captions on screen for less than 0.5 s",
    "caption_bounds": "a caption sits outside the safe box",
    "captions_empty": "a caption file has no cues",
    "captions_missing": "expect.captions is true but no captions were found",
    "captions_unverified": "captions may be burned in but cannot be verified",
    "missing_credits": "attribution is required but no credits file ships with the video",
    "credits_incomplete": "the credits file lacks a required line",
    "content_id_credit": "music protected by Content ID lacks its credit in share.txt (the description)",
    "too_long": "longer than the platform allows",
    "too_short": "shorter than the platform allows",
    "aspect": "aspect ratio differs from the platform's",
    "resolution": "the frame is smaller than the platform's recommended size",
    "upscale": "the source footage was enlarged more than 1.5x (looks soft)",
    "file_size": "file is larger than the size cap",
    "must_show": "a must-show text was not found on screen",
    "must_show_unverified": "a must-show text exists in the project but was not verified on screen",
    "expect_invalid": "the expect block has an unknown key or a bad value",
    "reference_copy": "the render copies its style reference (near-copy guard: sampled frames + cut rhythm)",
    "reference_close": "some frames look like frames of the style reference",
    "reference_credit": "the \"Style reference:\" credit is missing from credits.txt or share.txt",
}
RULES.update(floor.RULES)   # the quality floor (st.qa.floor): looks-cheap patterns, WARN only
RULES.update(hearing.RULES)  # the hearing pass (st.qa.hearing): what an ear catches, WARN only


class Findings:
    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []
        self.passed: List[str] = []

    def add(self, rule: str, severity: str, message: str, *, t: Optional[float] = None, end: Optional[float] = None,
            fix: str = "", **extra: Any) -> None:
        f: Dict[str, Any] = {"rule": rule, "severity": severity, "message": message}
        if t is not None:
            f["t"] = round(float(t), 3)
        if end is not None:
            f["end"] = round(float(end), 3)
        if fix:
            f["fix"] = fix
        f.update(extra)
        self.items.append(f)

    def ok(self, line: str) -> None:
        self.passed.append(line)

    def has(self, *rules: str) -> bool:
        return any(f["rule"] in rules for f in self.items)


# ------------------------------------------------------------------ context

def find_project(video: Path, explicit: Optional[PathLike] = None) -> Optional[Path]:
    """The project folder that produced `video`, if it can be found."""
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if p.is_file():
            p = p.parent
        if not (p / "showtime.json").is_file() and not (p / "index.html").is_file():
            raise ShowtimeError("%s is not a showtime project (no showtime.json or index.html)" % p,
                                hint="pass the project folder that holds showtime.json, or leave --project out")
        return p
    edit = edit_report(video) is not None       # a footage edit: its own report, not a project, made it
    for rj in (video.parent / "render.json", video.with_suffix(".work") / "render.json",
               video.parent / "job.json"):
        data = read_json(rj, None) if rj.is_file() else None
        if isinstance(data, dict) and data.get("project"):
            if rj.name == "render.json" and data.get("output") and Path(str(data["output"])).name != video.name:
                continue                         # another video's render (e.g. a cards/ sub-project's)
            if rj.name == "job.json" and edit:
                continue                         # the job's sub-project (cards, titles) did not make this video
            p = Path(data["project"])
            if (p / "showtime.json").is_file() or (p / "index.html").is_file():
                return p
    if (video.parent / "showtime.json").is_file():
        return video.parent
    return None


def job_of(video: Path) -> Optional[Path]:
    """The job folder the video sits in (directly, or in a subfolder such as exports/)."""
    from ..job import ledger
    return ledger.enclosing_job(video)


def default_out(video: Path) -> Path:
    job = job_of(video)
    if job is not None:
        return job / "work" / "qa" / video.stem
    if (video.parent / "work").is_dir():
        return video.parent / "work" / "qa" / video.stem
    return video.parent / (video.stem + ".qa")


def platform_for(video: Path, cfg: Dict[str, Any], expect: Dict[str, Any], explicit: Optional[str] = None
                 ) -> Tuple[Optional[str], Optional[str]]:
    """(platform, where it came from): --platform, then expect.platform, then showtime.json "platform",
    then the job's platform (job.json, set by `showtime job init/note --platform`)."""
    if explicit:
        return explicit, "--platform"
    if expect.get("platform"):
        return str(expect["platform"]), "showtime.json expect"
    pv = cfg.get("platform") if isinstance(cfg, dict) else None
    if isinstance(pv, list) and pv:
        pv = pv[0]
    if isinstance(pv, str) and pv.strip():
        return pv.strip(), "showtime.json"
    job = job_of(video)
    if job is not None and (job / "job.json").is_file():
        data = read_json(job / "job.json", {}) or {}
        jp = data.get("platform")
        if isinstance(jp, list) and jp:
            jp = jp[0]
        if isinstance(jp, str) and jp.strip():
            return jp.strip(), "job.json"
    return None, None


def load_expect(project: Optional[Path], expect_file: Optional[PathLike]) -> Tuple[Dict[str, Any], Optional[str]]:
    if expect_file:
        p = Path(expect_file)
        data = read_json(p, None)
        if not isinstance(data, dict):
            raise ShowtimeError("%s must contain a JSON object" % p, hint='e.g. {"duration": 15, "platform": "reels"}')
        return (data.get("expect") if isinstance(data.get("expect"), dict) else data), str(p)
    if project and (project / "showtime.json").is_file():
        cfg = read_json(project / "showtime.json", {}) or {}
        ex = cfg.get("expect")
        if isinstance(ex, dict):
            return ex, str(project / "showtime.json")
    return {}, None


EXPECT_KEYS = {"duration", "tolerance", "duration_tolerance", "platform", "lufs", "true_peak", "audio", "captions",
               "must_show", "max_size_mb", "fps", "width", "height", "aspect", "credits", "notes", "style"}


def target_for(name: Optional[str]) -> Optional[Dict[str, Any]]:
    if not name:
        return None
    n = str(name).lower().strip()
    if n in EXTRA_TARGETS:
        return dict(EXTRA_TARGETS[n], name=n)
    try:
        from ..deliver.exports import TARGETS
    except Exception:  # noqa: BLE001 - deliver is optional for qa
        TARGETS = {}
    t = TARGETS.get(n)
    if t is None:
        raise ShowtimeError("unknown platform %r" % name, hint="choose from: %s" % ", ".join(
            list(TARGETS) + list(EXTRA_TARGETS)))
    return {"name": n, "width": t.width or None, "height": t.height or None, "max_duration": t.max_duration,
            "min_duration": t.min_duration, "lufs": t.lufs, "true_peak": t.true_peak, "audio": None,
            "max_mb": None, "note": t.note, "native": t.native}


def raw_probe(video: Path) -> Dict[str, Any]:
    exe = ff.ffprobe_path()
    if not exe:
        return {}
    from ..common import run
    cp = run([exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(video)], check=False)
    if cp.returncode != 0:
        return {}
    try:
        return json.loads(cp.stdout or "{}")
    except ValueError:
        return {}


# ------------------------------------------------------------------ main

def run(video: PathLike, *, project: Optional[PathLike] = None, expect_file: Optional[PathLike] = None,
        out_dir: Optional[PathLike] = None, platform: Optional[str] = None, lufs: Optional[float] = None,
        captions: Sequence[str] = (), sheet: bool = True, sheet_count: Optional[int] = None,
        quiet: bool = False, record: bool = True, steps: bool = True) -> Dict[str, Any]:
    t0 = time.time()
    vpath = Path(video).expanduser().resolve()
    if not vpath.is_file():
        raise ShowtimeError("video not found: %s" % vpath, hint="pass the rendered file, e.g. showtime-out/<job>/final.mp4")
    # steps=False (brief output): drop the progress lines, keep the notes (which captions, which picture area)
    progress = ("qa: probing", "qa: measuring loudness", "qa: scanning for black", "qa: contact sheet",
                "qa: measuring the edit rhythm", "qa: measuring what an ear would catch")
    say = (lambda m: None) if quiet else (lambda m: None if not steps and m.startswith(progress) else log(m))
    proj = find_project(vpath, project)
    expect, expect_src = load_expect(proj, expect_file)
    cfg = read_json(proj / "showtime.json", {}) if proj and (proj / "showtime.json").is_file() else {}
    out = Path(out_dir).expanduser().resolve() if out_dir else default_out(vpath)
    frames_dir = out / "frames"
    out.mkdir(parents=True, exist_ok=True)
    F = Findings()
    rep: Dict[str, Any] = {"video": str(vpath), "project": str(proj) if proj else None, "expect": expect or None,
                           "expect_source": expect_src, "out_dir": str(out), "findings": F.items, "passed": F.passed}
    if lufs is not None:
        rep["lufs_arg"] = float(lufs)

    for k in expect:
        if k not in EXPECT_KEYS:
            F.add("expect_invalid", "WARN", "unknown key %r in the expect block (known: %s)" % (k, ", ".join(sorted(EXPECT_KEYS))),
                  fix="fix the key name in showtime.json \"expect\"")
    plat_name, plat_src = platform_for(vpath, cfg, expect, platform)
    try:
        tgt = target_for(plat_name)
    except ShowtimeError:
        if plat_src == "--platform":
            raise
        F.add("expect_invalid", "WARN", "unknown platform %r in %s; checked without a platform target" % (plat_name, plat_src),
              fix="use one of: youtube, x, linkedin, reels, tiktok, shorts, square, web, github, chat, broadcast")
        tgt = None
    if tgt is not None:
        tgt["source"] = plat_src
    rep["target"] = tgt

    # ---------------------------------------------------------- probe
    say("qa: probing %s" % vpath.name)
    try:
        pr = ff.probe(vpath)
    except ShowtimeError as e:
        F.add("unreadable", "FAIL", "ffprobe could not read the file: %s" % e, fix="re-render or re-export the video")
        return _finish(rep, F, out, t0, vpath, record)
    raw = raw_probe(vpath)
    vs = next((s for s in raw.get("streams", []) if s.get("codec_type") == "video"
               and not (s.get("disposition") or {}).get("attached_pic")), {})
    aus = [s for s in raw.get("streams", []) if s.get("codec_type") == "audio"]
    dur = float(pr.get("duration") or 0.0)
    W, H = int(pr.get("width") or 0), int(pr.get("height") or 0)
    fps = float(pr.get("fps") or 0.0) or 30.0
    size = int(pr.get("size_bytes") or vpath.stat().st_size)
    fs = media.faststart(vpath)
    rep["probe"] = {"duration": round(dur, 4), "width": W, "height": H, "fps": round(fps, 4), "vcodec": pr.get("vcodec"),
                    "pix_fmt": pr.get("pix_fmt"), "profile": vs.get("profile"), "color": {
                        "space": pr.get("color_space"), "primaries": pr.get("color_primaries"),
                        "transfer": pr.get("color_transfer"), "range": pr.get("color_range")},
                    "faststart": fs, "size_bytes": size, "bit_rate": pr.get("bit_rate"),
                    "audio": [{"codec": a.get("codec_name"), "sample_rate": int(a.get("sample_rate") or 0),
                               "channels": a.get("channels"), "duration": _f(a.get("duration"))} for a in aus]}
    if not pr.get("has_video"):
        F.add("no_video", "FAIL", "the file has no video stream", fix="render again; check that the encode step finished")
        return _finish(rep, F, out, t0, vpath, record)

    alpha_kind = vpath.suffix.lower() in (".mov", ".webm") and pr.get("has_alpha")
    _check_stream(F, pr, vs, W, H, fps, fs, vpath, alpha_kind)
    expected, tol, why = _expected_duration(vpath, cfg, expect, fps)
    if expected is not None:
        if abs(dur - expected) > tol:
            F.add("duration", "FAIL", "duration is %.3fs; %s is %.3fs (tolerance ±%.3fs)" % (dur, why, expected, tol),
                  fix="re-render the full range, or update the duration in showtime.json")
        else:
            F.ok("duration %.2fs matches %s (%.2fs ±%.2fs)" % (dur, why, expected, tol))
    _check_platform(F, tgt, expect, dur, W, H, size, vpath)

    # ---------------------------------------------------------- audio
    want_audio = expect.get("audio")
    if want_audio is None and tgt is not None:
        want_audio = tgt.get("audio")
    loud: Dict[str, Any] = {}
    if not aus:
        if want_audio is False:
            F.ok("no audio track (as expected for this target)")
        else:
            F.add("no_audio", "FAIL" if want_audio else "WARN",
                  "the video has no audio track" + (" but the expect block asks for audio" if want_audio else ""),
                  fix="add music or voice (showtime.json \"audio\", or ST.score), or set \"audio\": false in expect for a silent loop")
    else:
        say("qa: measuring loudness")
        loud = _check_audio(F, vpath, aus, dur, fps, tgt, expect, lufs, cfg)
    rep["loudness"] = {k: v for k, v in loud.items() if not k.startswith("_")}

    # ---------------------------------------------------------- picture
    say("qa: scanning for black and frozen frames")
    pic = None
    try:
        side = read_json(Path(str(vpath) + ".export.json"), None) if Path(str(vpath) + ".export.json").is_file() else None
        pic = side.get("picture") if isinstance(side, dict) else None
        if pic:
            say("qa: judging the picture inside the %s bars (%dx%d at %d,%d)" % (side.get("fit"), pic[2], pic[3], pic[0], pic[1]))
        det = media.detect(vpath, dur, freeze_noise_db=thresholds()["freeze_noise_db"], crop=pic)
    except ShowtimeError as e:
        F.add("unreadable", "FAIL", str(e), fix="the file is damaged; render or export it again")
        det = {"black": [], "freeze": []}
    rep["detect"] = {"black": det["black"], "freeze": det["freeze"]}
    if pic:
        rep["detect"]["picture"] = pic
    first = media.extract_frames(vpath, [0.0], frames_dir, width=min(W, 960) or None, duration=dur, fps=fps)
    _check_picture(F, det, first[0] if first else None, dur, fps, vpath=vpath, crop=pic, rms=loud.get("_rms"),
                   footage=_may_hold_footage(proj, cfg), rep=rep,
                   launch_kind=str(cfg.get("kind") or "").lower() in ("launch", "promo", "trailer", "teaser", "release"))
    _check_opening_flash(F, vpath, fps)
    _check_poster_match(F, vpath)

    _check_upscale(F, vpath)
    rep["floor"] = _check_floor(F, vpath, dur, W, H, pic, _may_hold_footage(proj, cfg))
    _check_rhythm(F, vpath, dur, fps, proj, cfg, expect, rep, say)
    if loud.get("_x") is not None:
        _check_hearing(F, vpath, loud, dur, proj, rep, say)
    loud.pop("_x", None)

    # ---------------------------------------------------------- captions, credits, texts
    caps = caption_files(vpath, proj, captions, W, H, say)
    rep["captions"] = [str(c) for c in caps]
    n_before = len(F.items)
    _check_captions(F, vpath, caps, expect, dur, W, H, proj)
    cap_items = F.items[n_before:]
    _check_credits(F, vpath, proj, expect)
    _check_must_show(F, proj, expect)
    rep["phone"] = _check_phone(F, vpath, proj, W, H, caps, cap_items)
    _check_reference(F, vpath, say)

    # ---------------------------------------------------------- frames + sheet
    times = sorted({f["t"] for f in F.items if f.get("t") is not None})
    if times:
        paths = media.extract_frames(vpath, times, frames_dir, width=min(W, 960) or None, duration=dur, fps=fps)
        by_t = {}
        for p in paths:
            m = re.match(r"t(\d+\.\d+)s", p.name)
            if m:
                by_t[round(float(m.group(1)), 3)] = str(p)
        for f in F.items:
            if f.get("t") is not None:
                tt = round(media.clamp_time(f["t"], dur, fps), 3)
                if tt in by_t:
                    f["frame"] = by_t[tt]
    if sheet and dur > 0:
        say("qa: contact sheet")
        rep["sheet"] = _sheet(vpath, out, dur, fps, W, H, F, sheet_count)
    return _finish(rep, F, out, t0, vpath, record, loud)


def _f(x: Any) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _check_stream(F: Findings, pr: Dict[str, Any], vs: Dict[str, Any], W: int, H: int, fps: float,
                  fs: Optional[bool], vpath: Path, alpha_kind: bool) -> None:
    bits = []
    if W % 2 or H % 2:
        F.add("odd_dimensions", "FAIL", "size %dx%d has an odd side; 4:2:0 video needs even width and height" % (W, H),
              fix="use even numbers in showtime.json (e.g. 1920x1080, 1080x1920)")
    vc = pr.get("vcodec")
    if alpha_kind:
        F.add("codec", "INFO", "%s with alpha (%s): an overlay master, not a delivery file" % (vpath.suffix, vc))
    elif vc != "h264":
        F.add("codec", "WARN", "video codec is %s; H.264 plays everywhere" % vc,
              fix="showtime deliver exports <video> --targets youtube (re-encodes to H.264)")
    else:
        bits.append("h264" + (" " + str(vs.get("profile")) if vs.get("profile") else ""))
    pix = pr.get("pix_fmt") or ""
    if not alpha_kind:
        if pix != "yuv420p":
            F.add("pix_fmt", "WARN", "pixel format is %s; players and platforms expect yuv420p" % (pix or "unknown"),
                  fix="re-encode with -pix_fmt yuv420p (showtime deliver exports does this)")
        else:
            bits.append("yuv420p")
    rf = _frac(vs.get("r_frame_rate"))
    af = _frac(vs.get("avg_frame_rate"))
    common = (23.976, 24, 25, 29.97, 30, 50, 59.94, 60)
    if rf and af and abs(rf - af) > 0.02 * rf:
        F.add("variable_fps", "WARN", "variable frame rate (nominal %.3g, average %.3g fps)" % (rf, af),
              fix="conform to a constant rate (the project fps); VFR drifts out of sync in editors")
    elif not any(abs(fps - c) < 0.01 for c in common):
        F.add("variable_fps", "WARN", "unusual frame rate %.3f fps" % fps, fix="use 24, 25, 30 or 60 fps")
    else:
        bits.append("%dx%d %sfps" % (W, H, ("%.3f" % fps).rstrip("0").rstrip(".")))
    if fs is False:
        F.add("faststart", "WARN", "the MP4 index (moov) is at the end: web players must download the whole file before playing",
              fix="re-mux with -movflags +faststart (showtime deliver exports does this)")
    elif fs:
        bits.append("faststart")
    if not alpha_kind:
        tags = [pr.get("color_primaries"), pr.get("color_transfer"), pr.get("color_space")]
        if not all(t == "bt709" for t in tags):
            F.add("color_tags", "WARN", "colour tags are %s (primaries/transfer/matrix); untagged or non-BT.709 video shifts colour between players" % "/".join(str(t) for t in tags),
                  fix="re-encode with BT.709 tags (showtime render and deliver exports tag them)")
        else:
            bits.append("BT.709")
    if bits:
        F.ok("file: " + ", ".join(bits))


def _frac(s: Any) -> Optional[float]:
    try:
        if not s or s in ("0/0",):
            return None
        a, _, b = str(s).partition("/")
        return float(a) / float(b or 1)
    except (ValueError, ZeroDivisionError):
        return None


def _expected_duration(vpath: Path, cfg: Dict[str, Any], expect: Dict[str, Any],
                       fps: float) -> Tuple[Optional[float], float, str]:
    frame = 1.0 / (fps or 30.0)
    if expect.get("duration") is not None:
        try:
            d = float(expect["duration"])
        except (TypeError, ValueError):
            return None, 0, ""
        tol = expect.get("tolerance", expect.get("duration_tolerance"))
        tol = float(tol) if tol is not None else max(0.5, frame)
        return d, max(tol, frame * 1.01), "expect.duration"
    rj = read_json(vpath.parent / "render.json", None) if (vpath.parent / "render.json").is_file() else None
    if isinstance(rj, dict) and rj.get("output") and Path(rj["output"]).name == vpath.name and rj.get("duration"):
        return float(rj["duration"]), frame * 1.5, "the render report"
    er = edit_report(vpath)
    if er is not None:
        # a footage edit: the EDL's own length (a poster-baked copy of it runs as long)
        return (float(er["duration"]), frame * 1.5, "the edit render report") if er.get("duration") else (None, 0, "")
    if cfg.get("duration"):
        return float(cfg["duration"]), frame * 1.5, "showtime.json"
    return None, 0, ""


def capped_exports(vpath: Path, platform: Optional[str], max_mb: float) -> List[Path]:
    """Size-capped copies of `vpath` that `deliver exports` wrote into exports/ beside it (or beside the
    job's final) for this platform: <stem>.<platform>[-Nmb].mp4 or <stem>.<N>mb.mp4, under `max_mb`."""
    dirs = [vpath.parent / "exports"]
    job = job_of(vpath)
    if job is not None and (job / "exports") not in dirs:
        dirs.append(job / "exports")
    pat = re.compile(r"^%s\.(?:%s(?:-[\d.]+mb)?|[\d.]+mb)$" % (re.escape(vpath.stem), re.escape(platform or "-")))
    out = []
    for d in dirs:
        for f in sorted(d.glob("%s.*.mp4" % vpath.stem)) if d.is_dir() else []:
            if pat.match(f.stem) and f.is_file() and f.stat().st_size / 1e6 <= float(max_mb):
                out.append(f)
    return sorted(out, key=lambda f: f.stat().st_mtime, reverse=True)


def _check_platform(F: Findings, tgt: Optional[Dict[str, Any]], expect: Dict[str, Any], dur: float,
                    W: int, H: int, size: int, vpath: Optional[Path] = None) -> None:
    max_mb = expect.get("max_size_mb") or (tgt or {}).get("max_mb")
    if max_mb:
        mb = size / 1e6   # decimal MB, as platform limits are
        name = (tgt or {}).get("name")
        if mb > float(max_mb):
            ex = capped_exports(vpath, name, float(max_mb)) if vpath is not None else []
            if ex:
                # the master stays full quality; the capped deliverable is the export (checked on its own)
                F.add("file_size", "INFO", "the master is %.1f MB (the %s cap is %s MB); its capped export %s is %.1f MB" % (
                    mb, name or "size", max_mb, ex[0].name, ex[0].stat().st_size / 1e6),
                    fix="check the export itself: showtime qa %s%s" % (ex[0], " --platform %s" % name if name else ""))
            else:
                F.add("file_size", "FAIL", "file is %.1f MB; the cap is %s MB" % (mb, max_mb),
                      fix="keep this master and export a capped copy: showtime deliver exports %s --targets %s, then "
                          "showtime qa <that export>%s" % (
                              vpath if vpath is not None else "<video>",
                              name if name in ("github", "chat", "web") else "original --max-mb %g" % float(max_mb),
                              " --platform %s" % name if name else ""))
        else:
            F.ok("size %.1f MB (cap %s MB)" % (mb, max_mb))
    for key in ("width", "height", "fps"):
        if expect.get(key) is not None:
            got = {"width": W, "height": H}.get(key)
            if got is not None and int(expect[key]) != got:
                F.add("aspect", "FAIL", "%s is %s; expect says %s" % (key, got, expect[key]), fix="render at the expected size")
    if expect.get("aspect"):
        m = re.match(r"^\s*(\d+)\s*[:x/]\s*(\d+)\s*$", str(expect["aspect"]))
        if m and W and H and abs(W / H - int(m.group(1)) / int(m.group(2))) > 0.01:
            F.add("aspect", "FAIL", "aspect is %dx%d; expect says %s" % (W, H, expect["aspect"]), fix="render at the expected aspect")
    if not tgt:
        return
    name = tgt["name"]
    if tgt.get("max_duration") and dur > tgt["max_duration"] + 0.01:
        F.add("too_long", "FAIL", "%.1fs is longer than %s allows (%.0fs)" % (dur, name, tgt["max_duration"]),
              fix="cut it down, or export with --trim (as of 2026; limits change)")
    if tgt.get("min_duration") and dur < tgt["min_duration"] - 0.01:
        F.add("too_short", "FAIL", "%.1fs is shorter than %s accepts (%.1fs)" % (dur, name, tgt["min_duration"]))
    if tgt.get("width") and tgt.get("height") and W and H:
        want = tgt["width"] / float(tgt["height"])
        nat = tgt.get("native")
        if abs(W / float(H) - want) > 0.02 and nat and nat[0] - 0.01 <= W / float(H) <= nat[1] + 0.01:
            # x and linkedin play a 1:1 or 4:5 master as it is (deliver exports keeps its aspect)
            F.ok("aspect %dx%d plays as is on %s (the feed keeps %.2f to %.2f)" % (W, H, name, nat[0], nat[1]))
        elif abs(W / float(H) - want) > 0.02:
            F.add("aspect", "WARN", "%dx%d does not match %s (%dx%d); the export will crop or pad" % (
                W, H, name, tgt["width"], tgt["height"]),
                fix="build an aspect-specific layout, then: showtime deliver exports <video> --targets %s" % name)
        else:
            F.ok("aspect fits %s" % name)
            tw, th = int(tgt["width"]), int(tgt["height"])
            if W * H < 0.97 * tw * th:
                F.add("resolution", "WARN", "%dx%d is below %s's recommended %dx%d (%.0f%% of the pixels): "
                      "the platform scales it up and it looks soft" % (W, H, name, tw, th, 100.0 * W * H / (tw * th)),
                      fix="render the final at %dx%d (a --preview or --scale render is for checking only)" % (tw, th))


def _check_audio(F: Findings, vpath: Path, aus: List[Dict[str, Any]], dur: float, fps: float,
                 tgt: Optional[Dict[str, Any]], expect: Dict[str, Any], lufs_arg: Optional[float],
                 cfg: Dict[str, Any]) -> Dict[str, Any]:
    import numpy as np
    from ..audio import meter
    kept_source = False
    a0 = aus[0]
    codec, sr = a0.get("codec_name"), int(a0.get("sample_rate") or 0)
    if vpath.suffix.lower() in (".mp4", ".m4v", ".mov") and codec != "aac":
        F.add("audio_codec", "WARN", "audio codec is %s; MP4 delivery expects AAC" % codec, fix="re-export (deliver exports encodes AAC)")
    elif sr and sr != 48000:
        F.add("audio_codec", "INFO", "audio sample rate is %d Hz (48 kHz is the video standard)" % sr)
    ad = _f(a0.get("duration"))
    if ad and dur and abs(ad - dur) > max(1.5 / fps, 0.06):
        F.add("av_length", "WARN", "audio lasts %.3fs, video %.3fs" % (ad, dur), fix="pad or trim audio to the video length before muxing")
    try:
        x = media.decode_audio(vpath)
    except Exception as e:  # noqa: BLE001
        F.add("unreadable", "FAIL", "could not decode the audio: %s" % e)
        return {}
    m = meter.measure(x)
    I, TP = m.get("integrated_lufs"), m.get("true_peak_dbtp")
    target = lufs_arg if lufs_arg is not None else expect.get("lufs")
    if target is None and tgt is not None and "lufs" in tgt:
        target = tgt.get("lufs")
    elif target is None:
        target = -14.0
        # nothing named a target: an edit render's own report says what it was mastered to, so the check
        # judges it against that (the default is showtime's delivery -14 LUFS; an EDL may ask for another
        # level or to keep the source level)
        lt = (edit_report(vpath) or {}).get("loudness_target")
        if isinstance(lt, dict):
            if lt.get("mode") == "source":
                kept_source = True
            elif isinstance(lt.get("lufs"), (int, float)):
                target = float(lt["lufs"])
    mix_master = None
    if isinstance(cfg.get("audio"), str):
        mix_master = cfg.get("audio")
    ceiling = expect.get("true_peak", (tgt or {}).get("true_peak", -1.0))
    if ceiling is None:
        ceiling = -1.0
    out: Dict[str, Any] = {"integrated_lufs": I, "true_peak_dbtp": TP, "lra": m.get("lra"),
                           "sample_peak_dbfs": m.get("sample_peak_dbfs"), "target_lufs": target,
                           "ceiling_dbtp": ceiling, "mix": mix_master}
    if I is None:
        F.add("silent_audio", "FAIL", "the audio track is silent", t=0.0,
              fix="check the mix (showtime audio mix ... ) and that the render found showtime.json \"audio\"")
        return out
    if target is not None:
        off = I - float(target)
        if kept_source:
            # asked for (edit render --keep-loudness / "loudness": false): say so, do not fail it
            F.add("loudness", "INFO", "loudness %.1f LUFS: this edit keeps the source level as asked; showtime delivers "
                  "at %g LUFS" % (I, target) + ("" if abs(off) <= 1 else " (%.1f LU %s)" % (abs(off), "louder" if off > 0 else "quieter")),
                  fix="render without --keep-loudness to master it to %g LUFS / -1 dBTP" % target)
        elif abs(off) > 3:
            F.add("loudness", "FAIL", "integrated loudness %.1f LUFS is %.1f LU off the %.0f LUFS target" % (I, off, target),
                  fix="master to the target: showtime audio master <in> -o <out> --lufs %g, then re-mux" % target)
        elif abs(off) > 1:
            F.add("loudness", "WARN", "integrated loudness %.1f LUFS is %.1f LU off the %.0f LUFS target" % (I, off, target),
                  fix="re-master to %g LUFS" % target)
        else:
            F.ok("loudness %.1f LUFS (target %g), true peak %.1f dBTP" % (I, target, TP if TP is not None else float("nan")))
    if TP is not None:
        if TP > 0.0:
            F.add("true_peak", "FAIL", "true peak %.2f dBTP is above 0: it will distort on playback" % TP,
                  fix="limit to %g dBTP (showtime audio master --tp %g)" % (ceiling, ceiling))
        elif TP > float(ceiling) + 0.3:
            F.add("true_peak", "WARN", "true peak %.2f dBTP is above the %g dBTP ceiling" % (TP, ceiling),
                  fix="limit to %g dBTP (AAC adds ~0.3 dB: master 0.5 dB under the ceiling)" % ceiling)
    cl = media.clipped_runs(x)
    out["clipping"] = cl
    if cl["runs"]:
        F.add("clipping", "FAIL", "the waveform is clipped (%d squared-off runs, first at %.2fs)" % (cl["runs"], cl["times"][0]),
              t=cl["times"][0], fix="lower the gain before the limiter; replace the clipped source file if it arrived clipped")
    hop = 0.05
    rms = media.rms_curve(x, hop=hop)
    thr = -50.0
    first_sound = next((i * hop for i, v in enumerate(rms) if v >= thr), None)
    last_sound = next(((len(rms) - i) * hop for i, v in enumerate(reversed(rms)) if v >= thr), None)
    out["first_sound"] = first_sound
    out["_rms"] = {"hop": hop, "db": rms}
    out["_x"] = x                       # the decoded audio, for the hearing pass (dropped before the report)
    out["last_sound"] = last_sound
    if first_sound is not None and first_sound > 0.5:
        F.add("leading_silence", "WARN", "audio starts at %.2fs; the first seconds are silent" % first_sound, t=0.0,
              end=first_sound, fix="start music on frame 1 (trim the silent head of the bed or move its start)")
    gaps = [g for g in media.runs_below(rms, hop, thr, 1.0)
            if first_sound is not None and g[0] > first_sound + 1e-6 and last_sound is not None and g[1] < last_sound - 1e-6]
    out["silent_gaps"] = gaps
    for s, e in gaps[:5]:
        sev = "FAIL" if e - s >= 3.0 else "WARN"
        F.add("silent_gap", sev, "silence from %.2fs to %.2fs (%.1fs) inside the video" % (s, e, e - s), t=s, end=e,
              fix="extend the music bed under this stretch, or close the gap in the voice timeline")
    if last_sound is not None and dur - last_sound >= 2.0:
        F.add("trailing_silence", "WARN", "the last %.1fs are silent (sound ends at %.2fs)" % (dur - last_sound, last_sound),
              t=last_sound, fix="end the music on a button at the logo hold, or shorten the tail")
    if not gaps and not F.has("leading_silence", "trailing_silence", "silent_audio"):
        F.ok("no silent gaps (audio from %.2fs to %.2fs)" % (first_sound or 0, last_sound or dur))
    try:
        c = meter.curves(x, hop=0.1)
        out["_curves"] = {"hop": 0.1, "momentary": [None if not np.isfinite(v) else round(float(v), 2) for v in c["momentary"]],
                          "short_term": [None if not np.isfinite(v) else round(float(v), 2) for v in c["short_term"]]}
    except Exception:  # noqa: BLE001
        pass
    return out


def _may_hold_footage(proj: Optional[Path], cfg: Dict[str, Any]) -> bool:
    """False only when the video is known to be pure motion graphics: a project whose page plays no
    <video> (then a long hold is always a design problem, never a speaker holding still)."""
    if proj is None:
        return True
    try:
        page = (proj / (cfg.get("entry") or "index.html")).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    return bool(re.search(r"<video\b|data-st=[\"']?(?:video|footage|clip-video)", page, re.I))


def _sound_share(rms: Optional[Dict[str, Any]], s: float, e: float, floor_db: float = -40.0) -> float:
    """Share of [s, e) with sound above floor_db (voice or other programme audio)."""
    if not rms or not rms.get("db"):
        return 0.0
    hop = float(rms["hop"])
    vals = rms["db"][int(s / hop): max(int(s / hop) + 1, int(e / hop))]
    return (sum(1 for v in vals if v >= floor_db) / float(len(vals))) if vals else 0.0


def _check_picture(F: Findings, det: Dict[str, List[Tuple[float, float]]], first: Optional[Path],
                   dur: float, fps: float, *, vpath: Optional[Path] = None, crop: Optional[Sequence[int]] = None,
                   rms: Optional[Dict[str, Any]] = None, footage: bool = False,
                   rep: Optional[Dict[str, Any]] = None, launch_kind: bool = False) -> None:
    frame = 1.0 / fps
    black0 = next((b for b in det["black"] if b[0] <= frame * 0.5), None)
    st = media.image_stats(first) if first else None
    if st is not None:
        # black = nothing visible: a dark design with a title or an equation on it is not black
        is_black = st["mean"] < 14 and st["p99"] < 40 and st.get("p999", 0.0) < 60
        if is_black:
            ln = (black0[1] - black0[0]) if black0 else frame
            F.add("first_frame_black", "FAIL", "frame 0 is black%s: feeds, chat apps and players show it as the thumbnail" % (
                " (black for the first %.2fs)" % ln if ln > frame * 1.5 else ""), t=0.0,
                fix="open on something visible: compose the hook so t=0 already shows it (then showtime.json \"poster\": 0). "
                    "Baking a later poster into frame 0 only works when it looks like the opening (else it flashes)")
        elif st["std"] < 2.0:
            F.add("first_frame_flat", "WARN", "frame 0 is a flat colour (mean luma %.0f)" % st["mean"], t=0.0,
                  fix="start on the hook's picture (compose it at t=0), or bake a poster that looks like the opening "
                      "(showtime deliver poster <video> --bake)")
        else:
            F.ok("frame 0 has picture (poster or hook)")
    for s, e in det["black"]:
        ln = e - s
        if s <= frame * 0.5:
            continue
        if e >= dur - frame * 1.5:
            if ln >= 1.0:
                F.add("ends_black", "WARN", "the last %.1fs are black" % ln, t=s, end=e,
                      fix="end on a designed hold (logo, CTA) instead of fading to black")
            continue
        if ln >= 1.0:
            F.add("black_segment", "FAIL", "black from %.2fs to %.2fs (%.2fs)" % (s, e, ln), t=s, end=e,
                  fix="check clip timing around this time (data-start/data-dur), or a missing video/image")
        elif ln >= 0.25:
            F.add("black_segment", "WARN", "black from %.2fs to %.2fs (%.2fs)" % (s, e, ln), t=s, end=e,
                  fix="if this is not a planned dip-to-black, check clip timing around this time")
    if not F.has("black_segment", "ends_black"):
        F.ok("no black stretches")

    def mostly_black(s: float, e: float) -> bool:
        cov = sum(max(0.0, min(e, b1) - max(s, b0)) for b0, b1 in det["black"])
        return cov >= 0.8 * (e - s)

    th = thresholds()
    hold, end_max, fail_s = th["still_hold_s"], th["final_hold_max_s"], th["frozen_fail_s"]
    if launch_kind:
        hold = th.get("launch_hold_s", 3.5)     # a settled result may breathe a little longer in a launch film
    any_frozen = False
    for s, e in det["freeze"]:
        ln = e - s
        if ln < hold or mostly_black(s, e):
            continue
        # camera footage of someone holding still reads as a hold to freezedetect; judge it as footage
        lv = media.liveness(vpath, s, e, crop=crop) if (footage and vpath is not None) else None
        if lv is not None and rep is not None:
            rep.setdefault("detect", {}).setdefault("live", []).append(dict(lv, start=s, end=e))
        live = bool(lv and lv["live"])
        if live and _sound_share(rms, s, e) >= 0.5:
            F.add("held_shot", "INFO", "a held camera shot from %.2fs to %.2fs (%.1fs): live footage (camera noise and small "
                  "movements in %d%% of sampled frames) with sound, such as a speaker holding still; not a frozen picture"
                  % (s, e, ln, round(100 * lv["live_share"])), t=s, end=e,
                  fix="fine for a talking head; cut in a B-roll or a punch-in only if the shot feels long")
            continue
        if e >= dur - frame * 1.5:
            F.add("final_hold", "INFO" if ln <= end_max else "WARN", "the last %.1fs are a still hold (from %.2fs)" % (ln, s),
                  t=s, end=e, fix="" if ln <= end_max else "shorten the end hold or add subtle motion")
            continue
        if live:
            any_frozen = True
            F.add("frozen", "WARN", "the picture barely changes from %.2fs to %.2fs (%.1fs): live footage (camera noise and small "
                  "movements) but no sound, so it plays as a long static shot" % (s, e, ln), t=s, end=e,
                  fix="shorten the shot, cut to another angle or B-roll, or add a slow push")
            continue
        any_frozen = True
        sev = "FAIL" if ln >= fail_s or (dur >= 4 and ln >= 0.5 * dur) else "WARN"
        F.add("frozen", sev, "the picture does not change from %.2fs to %.2fs (%.1fs; small changes such as typing a few "
              "characters or a thin moving line still count as a hold)" % (s, e, ln), t=s, end=e,
              fix="add motion (a slow push, drift, progress element) or shorten the hold; "
                  "find it in the project with: showtime check <project> --find-first frozen")
    if not any_frozen:
        F.ok("no frozen stretches over %gs" % hold)


POSTER_FLASH_DIFF = 12.0   # same threshold as render's --poster-bake auto


def _check_rhythm(F: Findings, vpath: Path, dur: float, fps: float, proj: Optional[Path], cfg: Dict[str, Any],
                  expect: Dict[str, Any], rep: Dict[str, Any], say: Any) -> None:
    """Edit rhythm (st.qa.rhythm): measured for every short video; judged for launch, promo, release and
    trailer films, where hard cuts, too many scenes and a flat music bed read as choppy and cheap, and for
    showreels (st.showreel), where too few shots read as tame. Flashes are judged on every video."""
    from . import rhythm
    from .. import showreel
    goal = None
    jdata: Dict[str, Any] = {}
    job = job_of(vpath)
    if job is not None:
        jdata = (read_json(job / "job.json", {}) or {}) if (job / "job.json").is_file() else {}
        goal = jdata.get("goal")
    reel = showreel.resolve(cfg, jdata)
    rep["showreel"] = reel
    # a showreel is judged on density and energy: the launch grammar (few scenes, few hard cuts) does not apply
    launch = rhythm.launch_like(cfg, expect, goal) and not reel["on"]
    if dur <= 0 or (dur > 180 and not launch):
        return
    say("qa: measuring the edit rhythm")
    scenes = None
    try:
        from .review import planned_scenes
        pl = planned_scenes(vpath, proj, dur) if proj is not None else None
        scenes = [t for t, _ in pl["scenes"]] if pl else None
    except Exception:  # noqa: BLE001 - the scene list is optional
        scenes = None
    try:
        r = rhythm.measure(vpath, dur, fps, scenes=scenes, max_seconds=180, showreel=bool(reel["on"]))
    except Exception as e:  # noqa: BLE001 - a measurement aid, never a reason to fail qa
        rep["rhythm"] = {"error": str(e)}
        return
    r["launch"] = launch
    r["showreel"] = bool(reel["on"])
    r["summary"] = rhythm.summary(r)
    rep["rhythm"] = r
    # motion defects on every video (st.qa.motion): a fast move that halts in one frame
    from . import motion
    for d in r.get("dead_stops") or []:
        txt = motion.describe(d, fps)
        F.add("dead_stop", "WARN", txt["message"], t=d["t"], fix=txt["fix"])
    fl = (r.get("picture") or {}).get("flashes") or {}
    if fl.get("max_per_s", 0) > rhythm.FLASH_MAX_PER_S:
        F.add("flash_risk", "WARN", "%d general flashes within one second from %.2fs (large swings in brightness over a "
              "quarter of the frame or more): more than %d a second can trigger seizures in photosensitive viewers" % (
                  fl["max_per_s"], fl.get("at") or 0.0, rhythm.FLASH_MAX_PER_S), t=fl.get("at"),
              fix="at most 3 flashes a second: space strobes and glitch bursts at least 0.33 s apart, shrink them under a "
                  "quarter of the frame, or lower their contrast (references/pacing.md section 5)")
    if reel["on"]:
        _check_showreel(F, r, dur)
        return
    if not launch:
        return
    L = rhythm.LIMITS
    pic = r["picture"]
    short = dur <= 60
    if short and pic["n_hard_cuts"] > L["max_hard_cuts"]:
        F.add("edit_choppy", "WARN", "%d hard cuts in %.0fs (%s): premium launch films change scene with a camera move, a "
              "match or a soft dissolve, and cut hard at most %d times" % (pic["n_hard_cuts"], dur,
                                                                           ", ".join("%.2f" % c for c in pic["hard_cuts"][:8]),
                                                                           L["max_hard_cuts"]),
              t=pic["hard_cuts"][0], fix="use the launch template's handoffs (through, match, pan, blur-dissolve) instead of cuts "
                                         "(references/workflows/launch-video.md)")
    n_sc = max(r["scenes"]["count"] if r.get("scenes") else 0, pic.get("n_layouts", 0))
    if short and n_sc > L["max_scenes"]:
        F.add("too_many_scenes", "WARN", "%d scenes or layouts in %.0fs: the eye re-learns the screen every %.1fs; tell it "
              "in 4-6 scenes" % (n_sc, dur, dur / n_sc),
              fix="merge beats into one scene with a camera move, or cut the weakest (launch-video.md, scene grammar)")
    if pic.get("longest_still_s", 0) > L["max_still_s"]:
        F.add("dead_hold", "WARN", "nothing moves for %.1fs from %.2fs" % (pic["longest_still_s"], pic["longest_still_at"]),
              t=pic["longest_still_at"], fix="a slow camera drift (camera component data-drift) or the next beat")
    m = r.get("music")
    voiced = False
    if proj is not None:
        mix = cfg.get("audio")
        if isinstance(mix, str) and (proj / mix).is_file() and mix.lower().endswith(".json"):
            spec = read_json(proj / mix, {}) or {}
            voiced = any((tr.get("kind") == "voice") for tr in spec.get("tracks", []) if isinstance(tr, dict))
    if m and not voiced and m.get("range_db", 99) < L["min_music_range_db"]:
        F.add("flat_music", "WARN", "the soundtrack moves only %.1f dB (10th-90th percentile): no breath, no swell for the "
              "edit to ride" % m["range_db"],
              fix="a produced track excerpt with a build (`showtime audio cuts --apply <project>`), or gain_points that "
                  "dip the middle and lift into the end card")


def _check_showreel(F: Findings, r: Dict[str, Any], dur: float) -> None:
    """The showreel tone (st.showreel, st.qa.reel): density (12-14 shots per 15 s), an end card that lands instead of
    holding (still for at most 10% of the reel), no shot that repeats another. The round-5 blind vote (2026-10-05)
    went to the reel that kept cutting to the last second; the takes that held their name 2.5-3.5 s lost."""
    from .. import showreel
    th = showreel.thresholds()
    pic = r.get("picture") or {}
    rl = r.get("reel") or {}
    shots = max(r["scenes"]["count"] if r.get("scenes") else 0, pic.get("n_layouts", 0), pic.get("n_hard_cuts", 0) + 1,
                rl.get("n_shots", 0))
    need = int(round(th["shots_per_15s_min"] * dur / 15.0))
    if dur >= 5 and shots < need:
        F.add("showreel_sparse", "WARN", "%d shots in %.1fs: a showreel cuts %d-%d times per 15 s (%d here), or it reads as a calm "
              "launch film" % (shots, dur, th["shots_per_15s_min"], th["shots_per_15s_max"], need),
              fix="cut on every 1-2 beats: split long shots, add flash cuts and a new technique per shot (references/tones.md, "
                  "showreel; motion-craft.md section 11)")
    else:
        F.ok("showreel density: %d shots in %.1fs (at least %d)" % (shots, dur, need))
    end = rl.get("end")
    if end and dur >= 5:
        still_max, shot_max = th["end_hold_max_frac"] * dur, th["end_shot_max_frac"] * dur
        if end["still_s"] > still_max or end["shot_s"] > shot_max:
            F.add("showreel_long_end", "WARN", "the last shot runs %.1fs from %.2fs and holds still for its last %.1fs: a showreel "
                  "lands its name on the last beat and keeps it moving (still at most %.1fs, the last shot at most %.1fs here)" % (
                      end["shot_s"], end["t"], end["still_s"], still_max, shot_max), t=end["t"], end=dur,
                  fix="spend the end card's seconds on one or two more shots; land the name about 1.25 s before the end "
                      "(its reading time) and keep it alive (a build, a sweep, a drift) to the last frame (references/tones.md, showreel)")
        else:
            F.ok("showreel ending: the last shot %.1fs, still for %.1fs" % (end["shot_s"], end["still_s"]))
    reps = rl.get("repeats") or []
    if reps:
        F.add("showreel_repeats", "WARN", "%d pair(s) of shots look alike (same ground, palette and composition): %s" % (
                  len(reps), ", ".join("%.2fs and %.2fs" % (x["a"], x["b"]) for x in reps[:6])), t=reps[0]["b"],
              fix="give each shot its own technique and ground: no technique twice (references/tones.md, showreel, the menu)")
    elif rl:
        F.ok("showreel variety: no two shots look alike")


def _check_hearing(F: Findings, vpath: Path, loud: Dict[str, Any], dur: float, proj: Optional[Path],
                   rep: Dict[str, Any], say: Any) -> None:
    """The hearing pass (st.qa.hearing): voice over the music line by line, quiet stretches, level jumps at
    cuts, a cut-off ending. Measured on the decoded audio; the block levels go into loudness.json (review-pack
    builds audio.txt and hearing.png from them), the cheap checks become WARNs."""
    say("qa: measuring what an ear would catch")
    try:
        from .review import _offset, planned_scenes
        blk = hearing.blocks(loud["_x"], 48000, vpath)
        lines, src = hearing.speech_lines(vpath, proj)
        pl = planned_scenes(vpath, proj, dur)
        starts = [(float(t), n) for t, n in pl["scenes"]] if pl else [(0.0, "")]
        cuts = [t for t, _ in starts if 0.1 < t < dur - 0.1]
        hard = ((rep.get("rhythm") or {}).get("picture") or {}).get("hard_cuts") or []
        cuts = sorted(cuts + [float(t) for t in hard if 0.1 < t < dur - 0.1 and all(abs(t - c) >= 0.5 for c in cuts)])
        b = sorted(set([0.0] + [t for t, _ in starts if 0.1 < t < dur - 0.1] + [dur]))
        names = {round(t, 3): n for t, n in starts}
        scenes = [(b[i], b[i + 1], names.get(round(b[i], 3)) or "scene %d" % (i + 1)) for i in range(len(b) - 1)
                  if b[i + 1] - b[i] > 0.15]
        off = _offset(vpath)
        mp = hearing.own_mix_report(vpath)
        mix = hearing.mix_facts(read_json(mp, None) if mp else None, off, dur)
        cues = {k: v - off for k, v in hearing.cue_values(proj).items()}
        h = hearing.measure(blk, dur, lines=lines, lines_source=src, cuts=cuts, scenes=scenes, mix=mix, cues=cues,
                            loud=loud)
    except Exception as e:  # noqa: BLE001 - a measurement aid, never a reason to fail qa
        rep["hearing"] = {"error": str(e).splitlines()[0][:200] if str(e) else type(e).__name__}
        return
    hearing.check(F, h)
    h["summary"] = hearing.summary(h)
    h["mix_report"] = str(mp) if mp else None
    rep["hearing"] = h
    loud.setdefault("_curves", {})["blocks"] = blk


def _check_opening_flash(F: Findings, vpath: Path, fps: float) -> None:
    """A frame 0 unlike frames 1-2 (a poster baked over an opening that builds from empty) shows as
    a one-frame flash on autoplay and on every loop. A real cut at frame 1 is rare; it is flagged too."""
    d = media.opening_diffs(vpath, 3)
    if not d:
        return
    if d[0] > POSTER_FLASH_DIFF and (len(d) < 2 or d[1] < d[0] / 3.0):
        F.add("poster_flash", "WARN", "frame 0 differs sharply from frame 1 (mean diff %.0f/255): a one-frame flash on "
              "autoplay and on every loop" % d[0], t=0.0, end=1.0 / (fps or 30.0),
              fix="start the video in the poster's state (compose the hook at t=0, showtime.json \"poster\": 0), "
                  "or render without the bake (--poster-bake off) and upload poster.jpg as the cover")
    else:
        F.ok("frame 0 flows into frame 1 (no poster flash)")


POSTER_LUMA_DIFF = 4.0     # mean luma levels (0-255) a poster still may differ from its video frame


def poster_of(vpath: Path) -> Optional[Tuple[Path, float]]:
    """(poster image, time) recorded by the render of this video (render.json "poster"), when it exists."""
    for rj in (vpath.parent / "render.json", vpath.with_suffix(".work") / "render.json"):
        r = read_json(rj, None) if rj.is_file() else None
        if not isinstance(r, dict) or not isinstance(r.get("poster"), dict):
            continue
        if r.get("output") and Path(str(r["output"])).name != vpath.name:
            continue
        f, t = r["poster"].get("file"), r["poster"].get("time")
        if not f or t is None:
            continue
        p = Path(str(f))
        p = p if p.is_absolute() else vpath.parent / p
        if p.is_file():
            try:
                return p, float(t)
            except (TypeError, ValueError):
                return None
    return None


def _check_poster_match(F: Findings, vpath: Path) -> None:
    """A delivered poster still should look like its video frame: compare mean luma (tiny grey copies), and
    flag PNG colour chunks (gAMA, cHRM, cICP, iCCP), which make browsers draw the still darker than the video."""
    found = poster_of(vpath)
    if not found:
        return
    img, t = found
    chunks = media.png_colour_chunks(img)
    a, b = media.mean_luma(img), media.mean_luma(vpath, at=t)
    if a is None or b is None:
        return
    d = a - b
    if abs(d) > POSTER_LUMA_DIFF:
        F.add("poster_mismatch", "WARN", "the poster %s is %.0f levels %s than the video at %.2fs" % (
            img.name, abs(d), "lighter" if d > 0 else "darker", t), t=t,
            fix="make the poster from the final video: showtime deliver poster %s --at %.2f" % (vpath.name, t))
    elif chunks:
        F.add("poster_mismatch", "WARN", "the poster %s carries PNG colour chunks (%s): browsers draw it darker than the "
              "video frame" % (img.name, ", ".join(chunks)), t=t,
              fix="make the poster again with this showtime (it writes PNGs without them), or use a .jpg")
    else:
        F.ok("the poster matches its video frame (mean luma within %.0f levels)" % POSTER_LUMA_DIFF)


UPSCALE_LIMIT = 1.5


def edit_report(vpath: Path) -> Optional[Dict[str, Any]]:
    """The `edit render` report of a video (<stem>.report.json), also for a poster-baked copy
    (final.poster.mp4 -> final.report.json)."""
    stems = [vpath.stem]
    if vpath.stem.endswith(".poster"):
        stems.append(vpath.stem[: -len(".poster")])
    for st in stems:
        rp = vpath.with_name(st + ".report.json")
        r = read_json(rp, None) if rp.is_file() else None
        if isinstance(r, dict) and r.get("edl"):
            return r
    return None


def _check_upscale(F: Findings, vpath: Path) -> None:
    """WARN when an edit enlarged its source more than 1.5x (from the edit render report)."""
    rep = edit_report(vpath)
    if not rep:
        return
    worst: Dict[str, Dict[str, Any]] = {}
    accepted = False
    for seg, meta in zip(rep.get("segments") or [], rep.get("segment_meta") or []):
        up = (meta or {}).get("upscale") if isinstance(meta, dict) else None
        if not isinstance(up, dict) or float(up.get("factor") or 0) <= UPSCALE_LIMIT:
            continue
        if up.get("accepted"):
            accepted = True
            continue
        key = str(seg.get("source"))
        if key not in worst or up["factor"] > worst[key]["factor"]:
            worst[key] = dict(up, t=seg.get("out_start"), source=key)
    for w in worst.values():
        F.add("upscale", "WARN", "source %s is enlarged %.2fx (%s)" % (w["source"], w["factor"], w.get("detail", "")),
              t=w.get("t"), fix=w.get("fix") or "use a smaller output size, a wider crop or a sharper source")
    if accepted:
        F.add("upscale", "INFO", "sources are enlarged more than %.1fx; the EDL accepts it (output.allow_upscale)" % UPSCALE_LIMIT)
    if not worst and not accepted and (rep.get("segment_meta") or []):
        F.ok("no source enlarged more than %.1fx" % UPSCALE_LIMIT)


def _check_floor(F: Findings, vpath: Path, dur: float, W: int, H: int, crop: Optional[Sequence[int]],
                 footage: bool) -> Dict[str, Any]:
    """The quality floor (st.qa.floor): player chrome, soft footage, stepped caption boxes, empty borders."""
    try:
        return floor.check(F, vpath, dur, W, H, crop=crop, footage=footage)
    except Exception as e:  # noqa: BLE001 - a warning-only look never breaks qa
        from ..common import debug
        debug("quality floor skipped: %s" % e)
        return {"error": str(e)}


def is_job_latest(vpath: Path) -> bool:
    """True when `vpath` is its job's latest final or preview."""
    job = job_of(vpath)
    if job is None:
        return False
    try:
        from ..job import ledger
        data = ledger.load(job)
        cur = [ledger.latest_output(job, k, data) for k in ("final", "preview")]
        return any(c is not None and c.resolve() == vpath.resolve() for c in cur)
    except Exception:  # noqa: BLE001 - the ledger is a convenience
        return False


def job_captions(vpath: Path) -> Optional[Path]:
    """The job's latest captions file when `vpath` is that job's latest final or preview (so a
    poster-baked final.poster.mp4 is still checked against final.srt). None otherwise."""
    if not is_job_latest(vpath):
        return None
    try:
        from ..job import ledger
        job = job_of(vpath)
        c = ledger.latest_output(job, "captions", ledger.load(job))
        return c.resolve() if c is not None else None
    except Exception:  # noqa: BLE001 - the ledger is a convenience
        return None


def own_sidecars(vpath: Path) -> List[Path]:
    """<stem>.srt/.vtt/.ass beside the video (for a poster-baked final.poster.mp4 also final.*)."""
    stems = [vpath.stem] + ([vpath.stem[: -len(".poster")]] if vpath.stem.endswith(".poster") else [])
    return [vpath.with_name(st + ext) for st in stems for ext in (".srt", ".vtt", ".ass")
            if vpath.with_name(st + ext).is_file()]


def _aspect_of_captions(cap: Path) -> Optional[float]:
    """Frame aspect a caption file was made for: an .ass file's PlayRes, else the video it is named
    after (final.srt -> final.mp4 beside it). None when unknown."""
    if cap.suffix.lower() in (".ass", ".ssa"):
        try:
            pr = capmod.parse(cap).get("play_res")
        except OSError:
            pr = None
        if pr and pr[1]:
            return float(pr[0]) / float(pr[1])
    for ext in (".mp4", ".mov", ".m4v", ".webm"):
        v = cap.with_suffix(ext)
        if v.is_file():
            try:
                p = ff.probe(v)
            except ShowtimeError:
                return None
            if p.get("width") and p.get("height"):
                return float(p["width"]) / float(p["height"])
            return None
    return None


def caption_files(vpath: Path, proj: Optional[Path], explicit: Sequence[str], W: int, H: int,
                  say: Any = None) -> List[Path]:
    """The caption sidecars qa checks for `vpath`.

    --captions given: exactly those files (auto-discovery is off, so a variant is judged on its own
    sidecar only). In a job folder: the video's own <stem>.srt/.vtt/.ass, plus the job's latest
    captions (its pointer) only when the video is the job's latest final/preview, has no sidecar of
    its own and the pointer was made for the same aspect (with no pointer: the project's caption files
    of the same aspect). Outside a job: <stem>.*, captions.*,
    subs.*, captions/ beside the video and the project's captions."""
    say = say or (lambda m: None)
    if explicit:
        out: List[Path] = []
        for x in explicit:
            p = Path(x).expanduser()
            if not p.is_file():
                raise ShowtimeError("caption file not found: %s" % p.resolve(),
                                    hint="pass an .srt/.vtt/.ass file with --captions, or leave --captions out to "
                                         "check the video's own sidecars")
            if p.resolve() not in out:
                out.append(p.resolve())
        return out
    if job_of(vpath) is None:
        return capmod.find_sidecars(vpath, proj)
    own = [p.resolve() for p in own_sidecars(vpath)]
    jc = job_captions(vpath)
    if jc is not None and jc not in own:
        if own:
            # a variant with its own sidecar (final-16x9.mp4 + final-16x9.srt) is judged on that, not on
            # the job's captions pointer, which may belong to another cut
            say("qa: using %s (the video's own captions), not the job's %s" % (own[0].name, jc.name))
        else:
            asp = _aspect_of_captions(jc)
            if asp is not None and W and H and abs(asp - W / float(H)) > 0.02:
                say("qa: not checking the job's captions %s: they were made for another aspect than this %dx%d "
                    "video (pass --captions <file> to check a sidecar)" % (jc.name, W, H))
            else:
                say("qa: checking the job's latest captions %s" % jc)
                own.append(jc)
    elif jc is None and not own and proj is not None and is_job_latest(vpath):
        # the job's latest render with no captions recorded: its project's sidecars (captions/ or beside
        # index.html), when they were made for this aspect
        for d in (proj / "captions", proj):
            for c in sorted(d.iterdir()) if d.is_dir() else []:
                if c.suffix.lower() in (".srt", ".vtt", ".ass") and c.is_file():
                    asp = _aspect_of_captions(c)
                    if asp is None or not (W and H) or abs(asp - W / float(H)) <= 0.02:
                        own.append(c.resolve())
        own = own[:6]
    return own


def _check_captions(F: Findings, vpath: Path, files: Sequence[Path], expect: Dict[str, Any],
                    dur: float, W: int, H: int, proj: Optional[Path] = None) -> None:
    for p in files:
        try:
            cap = capmod.parse(p)
        except OSError as e:
            F.add("captions_empty", "WARN", "could not read %s: %s" % (p.name, e))
            continue
        before = len(F.items)
        for f in capmod.check(cap, dur, W, H, source=p.name):
            F.add(f["rule"], f["severity"], f["message"], t=f.get("t"), fix=f.get("fix", ""), file=str(p))
        if len(F.items) == before:
            sm = capmod.summary(cap)
            F.ok("captions %s: %d cues inside the video, readable line lengths and placement (shortest cue %.2fs)" % (
                p.name, len(cap["cues"]), sm["shortest_s"] or 0))
    if expect.get("captions") and not files:
        burned = False
        texts = _check_texts(proj) if proj else None
        if texts:
            burned = any(t.get("caption") for t in texts.get("texts", []))
        if burned:
            F.ok("captions: the project draws caption text (data-caption); no sidecar to check timing")
        else:
            F.add("captions_missing", "FAIL" if texts is not None else "WARN",
                  "expect.captions is true but no caption sidecar (.srt/.vtt/.ass) was found" +
                  ("" if texts is not None else " and burned-in captions could not be verified"),
                  fix="make captions: showtime captions <transcript> -o captions.srt, or mark caption text with data-caption and re-run showtime check")


def _check_phone(F: Findings, vpath: Path, proj: Optional[Path], W: int, H: int, caps: Sequence[Path],
                 cap_items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The phone check (st.qa.phone): type size, reading time and UI zones from the project's last
    `showtime check`, caption line length and speed from the sidecars; one summary line."""
    stats = []
    for p in caps:
        try:
            stats.append(capmod.stats(capmod.parse(p)))
        except OSError:
            pass
    return phonemod.evaluate(F, vpath, proj, W, H, list(caps), cap_items, stats)
def _check_reference(F: Findings, vpath: Path, say: Any) -> None:
    """Style references of the job (`showtime reference`): near-copy guard and credit line."""
    try:
        from ..variety import guard
        guard.qa_check(F, vpath, say)
    except ShowtimeError as e:
        F.add("reference_copy", "INFO", "near-copy guard skipped: %s" % e.message)
    except Exception as e:  # noqa: BLE001 - a guard failure must not hide the other findings
        from ..common import debug
        debug("reference guard failed: %s" % e)


def _record_look(vpath: Path, rep: Dict[str, Any]) -> None:
    """A passing qa on the job's latest final records the job's look in the local history (st.variety)."""
    if rep.get("verdict") not in ("PASS", "WARN"):
        return
    try:
        from ..job import ledger
        job = ledger.enclosing_job(vpath)
        if job is None:
            return
        cur, kind = ledger.latest_video(job)
        if kind != "final" or cur is None or cur.resolve() != vpath.resolve():
            return
        from ..variety import history
        history.record_job(job)
    except Exception as e:  # noqa: BLE001 - the history is a convenience
        from ..common import debug
        debug("could not record the look history: %s" % e)


def _check_credits(F: Findings, vpath: Path, proj: Optional[Path], expect: Dict[str, Any]) -> None:
    need: List[str] = []
    sources: List[str] = []
    claimable: List[Dict[str, Any]] = []
    roots = [p for p in (proj, vpath.parent / "work", vpath.with_suffix(".work")) if p and p.is_dir()]
    for root in roots:
        for rp in _limited_rglob(root, "mix.report.json"):
            data = read_json(rp, None)
            if isinstance(data, dict):
                for c in data.get("credits") or []:
                    if c and c not in need:
                        need.append(str(c))
                        sources.append(str(rp))
                for it in data.get("credit_items") or []:
                    if isinstance(it, dict) and it.get("content_id") == "smart-cid-releasable" and it not in claimable:
                        claimable.append(it)
    if claimable and expect.get("credits") is not False:
        share = vpath.parent / "share.txt"
        body = share.read_text(encoding="utf-8", errors="replace").lower() if share.is_file() else ""
        lacking = [it for it in claimable if (it.get("artist") or "").lower() not in body
                   or (it.get("title") or "").lower() not in body]
        if lacking:
            F.add("content_id_credit", "WARN", "%s: YouTube's Content ID claims videos whose description lacks this credit, and "
                  "%s" % ("; ".join("\u201c%s\u201d by %s" % (it.get("title"), it.get("artist")) for it in lacking[:3]),
                          "share.txt does not have it" if share.is_file() else "there is no share.txt next to the video"),
                  fix="re-render (render writes the credits block into share.txt) or run: showtime audio credits --report "
                      "<mix.report.json> --out-dir %s" % vpath.parent)
    if proj:
        try:
            from ..assets import licenses
            for info in licenses.collect(proj, only_required=True):
                line = info.get("credit")
                if line and line not in need:
                    need.append(line)
                    sources.append(info.get("sidecar", ""))
        except Exception:  # noqa: BLE001 - assets module optional
            pass
    rj = read_json(vpath.parent / "render.json", None) if (vpath.parent / "render.json").is_file() else None
    if isinstance(rj, dict) and rj.get("credits") and Path(str(rj["credits"])).is_file():
        pass
    have = find_credits(vpath)
    if expect.get("credits") is False:
        return
    if not need:
        if have:
            F.ok("credits file present (%s)" % have.name)
        else:
            F.ok("no attribution required (no CC-BY items in the mix report or asset sidecars)")
        return
    if not have:
        F.add("missing_credits", "FAIL", "%d item(s) need attribution but no credits.txt ships with the video: %s" % (
            len(need), "; ".join(_snip(n, 60) for n in need[:3])),
            fix="write it next to the video: showtime assets credits <project> -o %s (and paste it into the post description)"
                % (vpath.parent / "credits.txt"), sources=sources[:5])
        return
    body = " ".join(have.read_text(encoding="utf-8", errors="replace").lower().split())
    missing = [n for n in need if " ".join(n.lower().split())[:40] not in body]
    if missing:
        F.add("credits_incomplete", "WARN", "%s lacks %d required credit line(s): %s" % (
            have.name, len(missing), "; ".join(_snip(n, 60) for n in missing[:3])),
            fix="regenerate it: showtime assets credits <project> -o %s" % have)
    else:
        F.ok("credits: %s lists all %d required attribution(s)" % (have.name, len(need)))


def find_credits(vpath: Path) -> Optional[Path]:
    """The credits file that ships with `vpath`: <stem>.credits.txt, then credits.txt (any case, so
    CREDITS.txt from older tools counts), then CREDITS.md, then the job's latest credits pointer."""
    try:
        names = {c.name.lower(): c for c in vpath.parent.iterdir() if c.is_file()}
    except OSError:
        names = {}
    for n in (vpath.stem.lower() + ".credits.txt", "credits.txt", "credits.md"):
        if n in names:
            return names[n]
    job = job_of(vpath)
    if job is not None:
        try:
            from ..job import ledger
            c = ledger.latest_output(job, "credits")
            if c is not None:
                return c
        except Exception:  # noqa: BLE001 - the ledger is a convenience
            pass
    return None


def _limited_rglob(root: Path, name: str, limit: int = 2000) -> List[Path]:
    out: List[Path] = []
    n = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", "frames", ".git", "__pycache__")]
        n += 1
        if n > limit:
            break
        if name in filenames:
            out.append(Path(dirpath) / name)
    return out


def _check_texts(proj: Optional[Path]) -> Optional[Dict[str, Any]]:
    """The on-screen text list from the project's last `showtime check` (None when unavailable)."""
    if not proj:
        return None
    rp = proj / "work" / "check" / "report.json"
    data = read_json(rp, None) if rp.is_file() else None
    if not isinstance(data, dict) or not isinstance(data.get("texts"), list):
        return None
    newest = 0.0
    for p in proj.iterdir():
        if p.is_file() and p.suffix.lower() in (".html", ".js", ".css", ".json", ".mjs") and p.name != "showtime.json":
            newest = max(newest, p.stat().st_mtime)
    return {"texts": data["texts"], "stale": rp.stat().st_mtime < newest, "path": str(rp)}


def _norm(s: str) -> str:
    return " ".join(str(s).lower().split())


def _check_must_show(F: Findings, proj: Optional[Path], expect: Dict[str, Any]) -> None:
    items = expect.get("must_show") or []
    if isinstance(items, (str, dict)):
        items = [items]
    if not items:
        return
    texts = _check_texts(proj)
    src_blob = None
    for it in items:
        if isinstance(it, dict):
            want, at, tol = str(it.get("text", "")), it.get("at"), float(it.get("tol", 1.0))
        else:
            want, at, tol = str(it), None, 1.0
        if not want.strip():
            continue
        nw = _norm(want)
        if texts is not None:
            hits = [t for t in texts["texts"] if nw in _norm(t.get("text", ""))]
            if at is not None:
                hits = [t for t in hits if (t.get("first", 0) - tol) <= float(at) <= (t.get("last", 0) + tol)]
            if hits:
                h = hits[0]
                F.ok("must_show \"%s\" is on screen %.2f-%.2fs%s" % (_snip(want, 30), h.get("first", 0), h.get("last", 0),
                                                                    " (check report may be stale)" if texts["stale"] else ""))
                continue
            F.add("must_show", "FAIL", "\"%s\" was not found on screen%s (last showtime check: %s%s)" % (
                _snip(want, 40), " near %.1fs" % float(at) if at is not None else "", texts["path"],
                ", older than the project files" if texts["stale"] else ""), t=float(at) if at is not None else None,
                fix="add the text, or re-run showtime check <project> if the project changed since")
            continue
        if src_blob is None:
            src_blob = _project_source(proj)
        if src_blob and nw in src_blob:
            F.add("must_show_unverified", "WARN", "\"%s\" appears in the project source but was not verified on screen" % _snip(want, 40),
                  fix="run showtime check <project> (it records every on-screen text), then showtime qa again")
        else:
            F.add("must_show", "FAIL", "\"%s\" is not in the project at all" % _snip(want, 40),
                  fix="add it to the scene that should show it")


def _project_source(proj: Optional[Path]) -> str:
    if not proj:
        return ""
    parts: List[str] = []
    total = 0
    for dirpath, dirnames, filenames in os.walk(proj):
        dirnames[:] = [d for d in dirnames if d not in ("node_modules", "work", ".git", "showtime-out")]
        for fn in filenames:
            if fn.lower().endswith((".html", ".js", ".mjs", ".json", ".md", ".txt", ".srt", ".vtt")) and fn != "showtime.json":
                p = Path(dirpath) / fn
                try:
                    if p.stat().st_size > 2_000_000:
                        continue
                    s = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                parts.append(re.sub(r"<[^>]+>", " ", s))
                total += len(s)
                if total > 20_000_000:
                    break
    return _norm(" ".join(parts))


def _snip(s: str, n: int = 40) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _sheet(vpath: Path, out: Path, dur: float, fps: float, W: int, H: int, F: Findings,
           count: Optional[int]) -> Optional[str]:
    from . import images
    n = count or int(max(6, min(36, round(dur))))
    times = [media.clamp_time((i + 0.5) * dur / n, dur, fps) for i in range(n)]
    width = 400 if W >= H else 240
    paths = media.extract_frames(vpath, times, out / "sheet-frames", width=width, duration=dur, fps=fps)
    marks: Dict[int, str] = {}
    for f in F.items:
        if f.get("t") is None or f["severity"] == "INFO":
            continue
        for i, tt in enumerate(times):
            end = f.get("end", f["t"] + 1.0 / fps)
            if f["t"] - 0.5 * dur / n <= tt <= end + 0.5 * dur / n:
                if marks.get(i) != "FAIL":
                    marks[i] = f["severity"]
    items = [{"path": str(p), "label": "%.2fs" % t, "sub": "f%d" % round(t * fps), "mark": marks.get(i)}
             for i, (p, t) in enumerate(zip(paths, times))]
    try:
        return str(images.contact_sheet(items, out / "sheet.jpg", thumb=width,
                                        title="%s  %dx%d %.3gfps %.2fs" % (vpath.name, W, H, fps, dur)))
    except (ValueError, OSError):
        return None


def _finish(rep: Dict[str, Any], F: Findings, out: Path, t0: float, vpath: Path, record: bool,
            loud: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    F.items.sort(key=lambda f: (SEV_RANK.get(f["severity"], 3), f.get("t", -1) if f.get("t") is not None else -1))
    n_fail = sum(1 for f in F.items if f["severity"] == "FAIL")
    n_warn = sum(1 for f in F.items if f["severity"] == "WARN")
    rep["verdict"] = "FAIL" if n_fail else "WARN" if n_warn else "PASS"
    rep["summary"] = {"fail": n_fail, "warn": n_warn, "info": len(F.items) - n_fail - n_warn, "passed": len(F.passed)}
    rep["seconds"] = round(time.time() - t0, 2)
    rep["created"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    path = out / "qa.json"
    write_json(path, rep)
    if loud and loud.get("_curves"):
        write_json(out / "loudness.json", loud["_curves"])
        rep["loudness_curve"] = str(out / "loudness.json")
    rep["report"] = str(path)
    if record:
        try:
            from ..job import ledger
            ledger.record_qa(vpath, rep)
        except Exception as e:  # noqa: BLE001 - the ledger is a convenience
            from ..common import debug
            debug("could not record qa in job ledger: %s" % e)
        _record_look(vpath, rep)
    return rep


def _format_brief(rep: Dict[str, Any]) -> str:
    pr = rep.get("probe") or {}
    head = Path(rep["video"]).name
    if pr:
        head += "  %sx%s @ %sfps, %.2fs, %.1f MB" % (pr.get("width"), pr.get("height"), ("%.3f" % (pr.get("fps") or 0)).rstrip("0").rstrip("."),
                                                   pr.get("duration") or 0, (pr.get("size_bytes") or 0) / 1e6)
    lines = [head]
    tg = rep.get("target") or {}
    if tg.get("name"):
        lines.append("  platform  %s%s" % (tg["name"], " (from %s)" % tg["source"] if tg.get("source") else ""))
    else:
        lines.append("  platform  none (generic checks; pass --platform reels|youtube|... to check length, aspect and loudness)")
    passed = list(rep.get("passed", []))
    loud = [p for p in passed if p.startswith("loudness")]
    rest = [re.split(r"[:(]", p)[0].strip() for p in passed if not p.startswith("loudness")]
    if loud or rest:
        lines.append("  PASS  %s" % "; ".join(loud + (["also " + ", ".join(rest)] if rest else [])))
    if (rep.get("phone") or {}).get("line"):
        lines.append("  %s" % rep["phone"]["line"])
    notes = 0
    for f in rep.get("findings", []):
        if f["severity"] == "INFO":
            notes += 1
            continue
        t = ("  t=%.2fs" % f["t"]) if f.get("t") is not None else ""
        lines.append("  %-4s  %s%s  %s" % (f["severity"], f["rule"], t, f["message"]))
        if f.get("frame"):
            lines.append("        frame: %s" % f["frame"])
        if f.get("fix"):
            lines.append("        fix: %s" % f["fix"])
    rh = rep.get("rhythm") or {}
    if rh.get("summary"):
        lines.append("  rhythm  %s" % rh["summary"])
    if rep.get("sheet"):
        lines.append("  sheet   %s (for reviewers)" % rep["sheet"])
    lines.append("  look    showtime look %s   (one small image; references/looking.md)" % rep["video"])
    lines.append("  report  %s%s" % (rep.get("report"), " (%d note(s) there; --verbose prints them)" % notes if notes else ""))
    s = rep.get("summary", {})
    lines.append("verdict: %s (%d fail, %d warn, %d note) for %s in %.1fs" % (
        rep.get("verdict"), s.get("fail", 0), s.get("warn", 0), s.get("info", 0), Path(rep["video"]).name, rep.get("seconds", 0)))
    return "\n".join(lines)


def format_text(rep: Dict[str, Any], verbose: bool = False, brief: bool = False) -> str:
    """Human summary for the terminal. brief (lean mode, agents): the loudness line, FAIL/WARN findings with
    frame and fix, notes as a count, paths and the verdict."""
    if brief:
        return _format_brief(rep)
    lines = []
    pr = rep.get("probe") or {}
    head = Path(rep["video"]).name
    if pr:
        head += "  %sx%s @ %sfps, %.2fs, %.1f MB" % (pr.get("width"), pr.get("height"), ("%.3f" % (pr.get("fps") or 0)).rstrip("0").rstrip("."),
                                                   pr.get("duration") or 0, (pr.get("size_bytes") or 0) / 1e6)
    lines.append(head)
    tg = rep.get("target") or {}
    if tg.get("name"):
        lines.append("  platform  %s%s" % (tg["name"], " (from %s)" % tg["source"] if tg.get("source") else ""))
    else:
        lines.append("  platform  none (generic checks; pass --platform reels|youtube|... to check length, aspect and loudness)")
    for p in rep.get("passed", []):
        lines.append("  PASS  %s" % p)
    if (rep.get("phone") or {}).get("line"):
        lines.append("  %s" % rep["phone"]["line"])
    for f in rep.get("findings", []):
        if f["severity"] == "INFO" and not verbose and len(rep["findings"]) > 20:
            continue
        t = ("  t=%.2fs" % f["t"]) if f.get("t") is not None else ""
        lines.append("  %-4s  %s%s  %s" % (f["severity"], f["rule"], t, f["message"]))
        if f.get("frame"):
            lines.append("        frame: %s" % f["frame"])
        if f.get("fix") and f["severity"] != "INFO":
            lines.append("        fix: %s" % f["fix"])
    rh = rep.get("rhythm") or {}
    if rh.get("summary"):
        lines.append("  rhythm  %s" % rh["summary"])
    if (rep.get("hearing") or {}).get("summary"):
        lines.append("  hearing  %s" % rep["hearing"]["summary"])
    if rep.get("sheet"):
        lines.append("  sheet   %s" % rep["sheet"])
    lines.append("  report  %s" % rep.get("report"))
    s = rep.get("summary", {})
    lines.append("verdict: %s (%d fail, %d warn, %d note) for %s in %.1fs" % (
        rep.get("verdict"), s.get("fail", 0), s.get("warn", 0), s.get("info", 0), Path(rep["video"]).name, rep.get("seconds", 0)))
    return "\n".join(lines)

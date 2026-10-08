"""Platform exports: one master video -> files tuned for each destination.

Each target fixes the frame size, a bitrate ceiling, the loudness target and
the platform's duration limit. When the aspect ratio differs from the
master, the picture is converted with:

  blur  - fit the whole frame over a blurred, zoomed copy of itself (default
          when orientation changes; nothing is cut off)
  crop  - fill the frame and crop the overflow (use --focus to choose where)
  pad   - fit the frame and pad with a solid colour
  auto  - blur when orientation flips (landscape <-> portrait), crop for
          small aspect differences (<= 12%), otherwise blur

Size-capped copies: `max_mb` (the github/chat/web targets, --max-mb N for the
size targets, --max-mb shorts:19 for one platform) switches the video to a
two-pass average bitrate computed from the duration, so the file lands just
under the cap (decimal MB, as upload limits are). A master already under the
budget gets a quality (CRF) encode capped at that rate instead, so an export is
never inflated toward the cap. The `original` target keeps the master's size
and frame rate. x and linkedin keep a 1:1 or 4:5 master's aspect (fit auto).

Loudness: each platform's target (-14 LUFS), unless --lufs or the job names
one (qa --lufs, showtime.json expect.lufs / loudness / master.lufs).

Audio is normalised with two-pass loudnorm (measure, then a linear pass) to
the target's LUFS and to a peak ceiling ff.TP_MARGIN_DB under the target's
true peak, encoded as AAC 256k 48 kHz, and the encoded peak is re-checked
(ff.ensure_true_peak re-encodes the audio when AAC overshoot crosses the
ceiling).
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .. import ff
from ..common import ShowtimeError, log, warn

PathLike = Union[str, "os.PathLike[str]"]


@dataclass(frozen=True)
class Target:
    name: str
    width: int
    height: int
    max_duration: Optional[float]      # seconds; None = effectively unlimited
    min_duration: float
    maxrate_kbps: int                  # video bitrate ceiling (CRF with VBV cap)
    crf: int
    max_fps: float
    audio_kbps: int
    lufs: float
    true_peak: float
    note: str
    max_mb: Optional[float] = None     # size cap in decimal MB (two-pass bitrate); None = CRF only
    audio: bool = True                 # False: no audio track (website hero loops)
    kind: str = "mp4"                  # "gif" / "webp": a silent image loop (deliver/loops.py)
    loop_width: int = 0                # image loops: default width in px (never enlarged)
    loop_fps: float = 0.0              # image loops: default frame rate
    native: Optional[tuple] = None     # (min, max) width/height the feed plays as is: a master in it keeps its aspect

    @property
    def is_loop(self) -> bool:
        return self.kind in ("gif", "webp")

    @property
    def keeps_size(self) -> bool:
        return not self.width or not self.height


TARGETS: Dict[str, Target] = {
    "youtube": Target("youtube", 1920, 1080, None, 1.0, 16000, 18, 60, 256, -14.0, -1.0,
                      "16:9 1080p; YouTube normalises playback to about -14 LUFS"),
    "x": Target("x", 1920, 1080, 140.0, 0.5, 12000, 20, 60, 256, -14.0, -1.0,
                "16:9 1080p (a 1:1 or 4:5 master keeps its aspect); 2:20 limit for standard accounts",
                native=(0.8, 1.78)),
    "linkedin": Target("linkedin", 1920, 1080, 600.0, 3.0, 10000, 20, 60, 256, -14.0, -1.0,
                       "16:9 1080p (a 1:1 or 4:5 master keeps its aspect); 3 s to 10 min", native=(0.8, 1.78)),
    "reels": Target("reels", 1080, 1920, 180.0, 3.0, 10000, 20, 60, 256, -14.0, -1.0,
                    "9:16 1080x1920; keep captions inside the centre 4:5 safe zone"),
    "tiktok": Target("tiktok", 1080, 1920, 600.0, 3.0, 10000, 20, 60, 256, -14.0, -1.0,
                     "9:16 1080x1920; up to 10 min when uploaded"),
    "shorts": Target("shorts", 1080, 1920, 180.0, 1.0, 12000, 19, 60, 256, -14.0, -1.0,
                     "9:16 1080x1920; YouTube Shorts up to 3 min"),
    "square": Target("square", 1080, 1080, None, 1.0, 8000, 20, 60, 256, -14.0, -1.0,
                     "1:1 1080x1080 feed post"),
    # same size as the master: for repos, chat and websites, usually with a size cap
    "original": Target("original", 0, 0, None, 0.5, 20000, 18, 60, 192, -14.0, -1.0,
                       "the master's size and frame rate; add --max-mb N for a size-capped copy"),
    "github": Target("github", 0, 0, None, 0.5, 20000, 20, 60, 160, -14.0, -1.0,
                     "README/PR embed: master size, under 10 MB (free plans)", max_mb=10.0),
    "chat": Target("chat", 0, 0, None, 0.5, 20000, 20, 60, 160, -14.0, -1.0,
                   "Slack/Discord/email: master size, under 10 MB", max_mb=10.0),
    "web": Target("web", 0, 0, 30.0, 1.0, 20000, 20, 60, 0, -14.0, -1.0,
                  "website hero loop: master size, no audio, under 15 MB", max_mb=15.0, audio=False),
    # silent image loops for READMEs, docs and chat (two-pass palette GIF; lossy animated WebP)
    "webp": Target("webp", 0, 0, None, 0.2, 0, 0, 15, 0, 0.0, 0.0,
                   "README hero loop: animated WebP, 960 px wide, 15 fps, under 5 MB",
                   max_mb=5.0, audio=False, kind="webp", loop_width=960, loop_fps=15),
    "gif": Target("gif", 0, 0, None, 0.2, 0, 0, 15, 0, 0.0, 0.0,
                  "README hero loop fallback: palette GIF, 960 px wide, 15 fps, under 5 MB",
                  max_mb=5.0, audio=False, kind="gif", loop_width=960, loop_fps=15),
    "webp-small": Target("webp-small", 0, 0, None, 0.2, 0, 0, 12, 0, 0.0, 0.0,
                         "showcase/docs loop: animated WebP, 480 px wide, 12 fps, under 1.5 MB",
                         max_mb=1.5, audio=False, kind="webp", loop_width=480, loop_fps=12),
    "gif-small": Target("gif-small", 0, 0, None, 0.2, 0, 0, 12, 0, 0.0, 0.0,
                        "showcase/docs loop fallback: palette GIF, 480 px wide, 12 fps, under 1.5 MB",
                        max_mb=1.5, audio=False, kind="gif", loop_width=480, loop_fps=12),
}
LOOP_TARGETS = tuple(n for n, t in TARGETS.items() if t.is_loop)

# `all` means the social platforms; the size/keep-size targets are asked for by name
PLATFORM_TARGETS = ("youtube", "x", "linkedin", "reels", "tiktok", "shorts", "square")
# targets a bare --max-mb N caps (the master-size copies and the image loops); an upload platform is capped
# only by name (--max-mb shorts:19), or when the list has none of these
SIZE_TARGETS = ("original", "github", "chat", "web") + tuple(n for n, t in TARGETS.items() if t.is_loop)
# platforms that turn loud files down to about -14 LUFS and leave quieter ones as they are
NORMALIZING = ("youtube", "x", "linkedin", "reels", "tiktok", "shorts", "square")


def parse_max_mb(spec: Any) -> Tuple[Optional[float], Dict[str, float]]:
    """--max-mb: "20" (the size targets, see SIZE_TARGETS) or "original:20,shorts:19" (per target), or both."""
    if spec is None or spec == "":
        return None, {}
    if isinstance(spec, (int, float)):
        return float(spec), {}
    bare: Optional[float] = None
    per: Dict[str, float] = {}
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        name, _, val = part.rpartition(":")
        try:
            v = float(val)
        except ValueError:
            raise ShowtimeError("--max-mb %r: use a number of MB, or target:MB pairs (e.g. original:20,shorts:19)"
                                % spec)
        if v <= 0:
            raise ShowtimeError("--max-mb must be above 0 (got %g)" % v)
        if name:
            n = name.strip().lower()
            if n not in TARGETS:
                raise ShowtimeError("--max-mb: unknown target %r" % n, hint="choose from: " + ", ".join(TARGETS))
            per[n] = v
        else:
            bare = v
    return bare, per


def cap_for(t: "Target", bare: Optional[float], per: Dict[str, float], names: Sequence[str]) -> Tuple[Optional[float], bool]:
    """(size cap in MB, True when the user asked for it) for target `t` in a run exporting `names`."""
    if t.name in per:
        return per[t.name], True
    if bare is not None and (t.name in SIZE_TARGETS or not any(n in SIZE_TARGETS for n in names)):
        return bare, True
    return t.max_mb, False


def native_size(sw: int, sh: int, target: "Target") -> Optional[Tuple[int, int]]:
    """The export size that keeps the master's aspect when `target` plays it natively (x/linkedin take
    1:1 and 4:5 as they are), else None. Never enlarged; the short side at most the target's."""
    if not target.native or not sw or not sh:
        return None
    ar = sw / float(sh)
    if not (target.native[0] - 0.01 <= ar <= target.native[1] + 0.01):
        return None
    k = min(1.0, min(target.width, target.height) / float(min(sw, sh)), max(target.width, target.height) / float(max(sw, sh)))
    return int(round(sw * k / 2)) * 2, int(round(sh * k / 2)) * 2


def job_loudness(video: PathLike, job: Optional[PathLike] = None) -> Tuple[Optional[float], Optional[str]]:
    """The loudness a job asked for (qa --lufs on this video or the job, showtime.json expect.lufs /
    "loudness" / master.lufs of its project), with where it came from; (None, None) when it names none."""
    import json as _json
    vp = Path(video).resolve()
    jdir = Path(job) if job else None
    if jdir is None:
        for d in [vp.parent] + list(vp.parents)[:3]:
            if (d / "job.json").is_file():
                jdir = d
                break
    data: Dict[str, Any] = {}
    if jdir is not None and (jdir / "job.json").is_file():
        try:
            data = _json.loads((jdir / "job.json").read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            data = {}
    files = data.get("qa_files") if isinstance(data.get("qa_files"), dict) else {}
    rec = files.get(str(vp)) if isinstance(files.get(str(vp)), dict) else None
    if rec and isinstance(rec.get("lufs"), (int, float)):
        return float(rec["lufs"]), "qa --lufs on %s" % vp.name
    for r in reversed(list(files.values())):
        if isinstance(r, dict) and isinstance(r.get("lufs"), (int, float)):
            return float(r["lufs"]), "the job's qa --lufs"
    proj = data.get("project") or (data.get("pointers") or {}).get("project")
    cands = [Path(proj)] if proj else []
    if jdir is not None:
        cands += [jdir / "project", jdir]
    for d in cands:
        cfgp = Path(d) / "showtime.json"
        if not cfgp.is_file():
            continue
        try:
            cfg = _json.loads(cfgp.read_text(encoding="utf-8-sig")) or {}
        except (OSError, ValueError):
            continue
        ex = cfg.get("expect") if isinstance(cfg.get("expect"), dict) else {}
        for val, where in ((ex.get("lufs"), "expect.lufs"), (cfg.get("loudness"), "loudness"),
                           ((cfg.get("master") or {}).get("lufs") if isinstance(cfg.get("master"), dict) else None,
                            "master.lufs")):
            if isinstance(val, (int, float)):
                return float(val), "showtime.json %s" % where
    return None, None


def list_targets() -> List[Dict[str, Any]]:
    return [asdict(t) for t in TARGETS.values()]


def parse_targets(spec: Union[str, Sequence[str]]) -> List[Target]:
    names: List[str] = []
    for part in ([spec] if isinstance(spec, str) else list(spec)):
        names += [x.strip().lower() for x in str(part).split(",") if x.strip()]
    if not names:
        raise ShowtimeError("no targets given", hint="choose from: " + ", ".join(TARGETS))
    if "all" in names:
        return [TARGETS[n] for n in PLATFORM_TARGETS]
    bad = [n for n in names if n not in TARGETS]
    if bad:
        raise ShowtimeError("unknown target(s): %s" % ", ".join(bad), hint="choose from: " + ", ".join(TARGETS))
    seen: List[Target] = []
    for n in names:
        if TARGETS[n] not in seen:
            seen.append(TARGETS[n])
    return seen


def choose_fit(src_w: int, src_h: int, dst_w: int, dst_h: int, fit: str) -> str:
    if fit != "auto":
        return fit
    src_ar, dst_ar = src_w / float(src_h), dst_w / float(dst_h)
    if abs(src_ar - dst_ar) / dst_ar < 0.01:
        return "scale"
    if (src_ar > 1) != (dst_ar > 1) and abs(src_ar - 1) > 0.05 and abs(dst_ar - 1) > 0.05:
        return "blur"
    return "crop" if abs(src_ar - dst_ar) / dst_ar <= 0.12 else "blur"


def video_filter(src_w: int, src_h: int, W: int, H: int, fit: str, focus_x: float = 0.5,
                 focus_y: float = 0.5, pad_color: str = "black") -> str:
    """Filtergraph (single input [0:v] -> output [v]) converting to WxH."""
    fx = min(max(focus_x, 0.0), 1.0)
    fy = min(max(focus_y, 0.0), 1.0)
    tail = ff.BT709_VF + ",format=yuv420p,setsar=1"
    if fit == "scale":
        return "[0:v]scale=%d:%d:flags=lanczos,%s[v]" % (W, H, tail)
    if fit == "crop":
        return ("[0:v]scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,"
                "crop=%d:%d:(iw-%d)*%.4f:(ih-%d)*%.4f,%s[v]" % (W, H, W, H, W, fx, H, fy, tail))
    if fit == "pad":
        return ("[0:v]scale=%d:%d:force_original_aspect_ratio=decrease:flags=lanczos,"
                "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=%s,%s[v]" % (W, H, W, H, ff.filter_value(pad_color), tail))
    if fit == "blur":
        # Blur at quarter resolution (fast), darken slightly so the sharp copy reads as foreground.
        bw, bh = max(2, W // 4 // 2 * 2), max(2, H // 4 // 2 * 2)
        return ("[0:v]split=2[bgsrc][fgsrc];"
                "[bgsrc]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,gblur=sigma=12,"
                "eq=brightness=-0.06:saturation=1.15,scale=%d:%d:flags=bicubic[bg];"
                "[fgsrc]scale=%d:%d:force_original_aspect_ratio=decrease:flags=lanczos[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2,%s[v]" % (bw, bh, bw, bh, W, H, W, H, tail))
    raise ShowtimeError("unknown fit %r (use auto, blur, crop, pad or scale)" % fit)


def picture_rect(src_w: int, src_h: int, W: int, H: int, fit: str) -> Optional[List[int]]:
    """[x, y, w, h] of the master's picture inside a pad/blur export (None when it fills the frame)."""
    if fit not in ("pad", "blur"):
        return None
    k = min(W / float(src_w), H / float(src_h))
    w, h = int(round(src_w * k / 2) * 2), int(round(src_h * k / 2) * 2)
    if w >= W - 2 and h >= H - 2:
        return None
    return [(W - w) // 2, (H - h) // 2, w, h]


def cap_bitrate_kbps(max_mb: float, duration: float, audio_kbps: int) -> int:
    """Average video bitrate that keeps a file of `duration` under `max_mb` decimal MB
    (3% kept for the container, 2% for the encoder's rate-control error)."""
    budget_bits = float(max_mb) * 1e6 * 8 * 0.95
    video_bits = budget_bits - audio_kbps * 1000.0 * duration
    return int(video_bits / max(duration, 0.1) / 1000.0)


def export_one(src: PathLike, target: Target, out: PathLike, fit: str = "auto", focus_x: float = 0.5,
               focus_y: float = 0.5, loudnorm: bool = True, trim: bool = False, preview: bool = False,
               pad_color: str = "black", info: Optional[Dict[str, Any]] = None,
               measured: Optional[Dict[str, float]] = None, max_mb: Optional[float] = None,
               lufs: Optional[float] = None, lufs_source: Optional[str] = None) -> Dict[str, Any]:
    """Export `src` for one target. Returns a report dict.

    max_mb: the size cap for this target (None: the target's own). lufs: the loudness to deliver (None:
    the target's), lufs_source says where it came from (reported)."""
    from dataclasses import replace
    info = info or ff.probe(src)
    if not info.get("has_video"):
        raise ShowtimeError("%s has no video stream" % src, hint="pass the rendered video (for example final.mp4), not an audio file or image")
    sw, sh = int(info["display_width"]), int(info["display_height"])
    notes: List[str] = []
    if target.keeps_size:
        target = replace(target, width=sw // 2 * 2, height=sh // 2 * 2)
    elif fit == "auto":
        keep = native_size(sw, sh, target)
        if keep and abs(sw / float(sh) - target.width / float(target.height)) > 0.02:
            notes.append("kept the master's %dx%d aspect: %s plays it as is (--fit blur|crop|pad converts to %dx%d)"
                         % (sw, sh, target.name, target.width, target.height))
            target = replace(target, width=keep[0], height=keep[1])
    cap = max_mb if max_mb is not None else target.max_mb
    dur = float(info.get("duration") or 0.0)
    warnings: List[str] = []
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    t_limit: Optional[float] = None
    if target.max_duration and dur > target.max_duration + 0.01:
        if trim:
            t_limit = target.max_duration
            warnings.append("trimmed from %.1fs to the %s limit of %.0fs" % (dur, target.name, target.max_duration))
        else:
            warnings.append("%.1fs is longer than %s's %.0fs limit (use --trim to cut)" % (
                dur, target.name, target.max_duration))
    if dur < target.min_duration:
        warnings.append("%.1fs is shorter than %s's %.1fs minimum" % (dur, target.name, target.min_duration))
    mode = choose_fit(sw, sh, target.width, target.height, fit)
    graph = video_filter(sw, sh, target.width, target.height, mode, focus_x, focus_y, pad_color)
    fps = info.get("fps") or 30.0
    out_fps = min(fps, target.max_fps)
    base: List[str] = ["-i", os.fspath(src), "-filter_complex", graph, "-map", "[v]"]
    crf = target.crf + (5 if preview else 0)
    has_audio = bool(info.get("has_audio")) and target.audio
    out_dur = min(dur, t_limit) if t_limit else dur
    vkbps: Optional[int] = None
    quality_cap: Optional[int] = None
    if cap:
        vkbps = min(cap_bitrate_kbps(cap, out_dur, target.audio_kbps if has_audio else 0), target.maxrate_kbps)
        if vkbps < 250:
            raise ShowtimeError("%.1f s of video cannot fit in %s MB at %dx%d (it would get %d kbps)" % (
                out_dur, cap, target.width, target.height, max(vkbps, 0)),
                hint="raise --max-mb, shorten the video (--trim), or export a smaller size (e.g. --targets reels for 1080x1920)")
        # a master already under the budget: a quality (CRF) encode capped at the budget's rate, so a 2.5 MB
        # master never comes out as a 12 MB export padded to the cap
        src_kbps = (float(info.get("size_bytes") or 0) * 8 / 1000.0 / dur) if dur > 0 else 0.0
        px = (target.width * target.height) / float(max(1, sw * sh))
        if src_kbps and src_kbps * max(1.0, px) * 1.15 < vkbps:
            quality_cap, vkbps = vkbps, None
            notes.append("the master is already small (%.0f kbps): a quality encode (CRF %d) capped at the %g MB "
                         "budget's rate, not a file padded to the cap" % (src_kbps, crf, cap))

    def video_args(kbps: Optional[int]) -> List[str]:
        ceiling = min(target.maxrate_kbps, quality_cap) if quality_cap else target.maxrate_kbps
        rate = (["-b:v", "%dk" % kbps, "-maxrate", "%dk" % int(kbps * 1.6), "-bufsize", "%dk" % int(kbps * 2)] if kbps else
                ["-crf", str(crf), "-maxrate", "%dk" % ceiling, "-bufsize", "%dk" % (ceiling * 2)])
        va = ["-c:v", "libx264", "-preset", "veryfast" if preview else ("slow" if kbps else "medium")] + rate + [
              "-profile:v", "high", "-pix_fmt", "yuv420p"] + ff.BT709_TAGS
        if out_fps < fps - 0.01:
            va += ["-r", ff._fps_str(out_fps)]
        gop = int(round(out_fps * 2))
        return va + ["-g", str(gop), "-keyint_min", str(min(gop, int(round(out_fps))))]

    if out_fps < fps - 0.01:
        warnings.append("frame rate capped from %.3g to %.3g fps" % (fps, out_fps))
    loud: Dict[str, Any] = {}
    af = "aresample=48000"
    audio_args: List[str] = ["-an"]
    if has_audio and lufs is not None and abs(lufs - target.lufs) > 0.05:
        target = replace(target, lufs=float(lufs))
        if loudnorm:
            notes.append("loudness %.1f LUFS (%s) instead of %s's %.0f%s" % (
                lufs, lufs_source or "--lufs", target.name, TARGETS[target.name].lufs,
                ": the platform turns louder files down and leaves quieter ones as they are"
                if target.name in NORMALIZING and lufs < TARGETS[target.name].lufs else ""))
    if has_audio:
        if loudnorm:
            tp_goal = target.true_peak - ff.TP_MARGIN_DB
            m = measured if measured is not None else ff.measure_loudness(src, target.lufs, tp_goal)
            loud["input_lufs"] = m.get("input_i")
            loud["input_true_peak"] = m.get("input_tp")
            if m.get("input_i") is not None and m["input_i"] > -70:
                af = ff.loudnorm_filter(m, target.lufs, tp_goal) + ",aresample=48000"
            else:
                warnings.append("audio is silent; loudness not changed")
        audio_args = ["-map", "0:a:0", "-af", af] + ff.aac_args("%dk" % target.audio_kbps)
    # the output never runs past the picture: without a cap, loudness filters and AAC framing can
    # leave the audio a few frames longer than the video, and players (and qa) then see a longer file
    vdur = float(info.get("video_duration") or 0.0)
    if t_limit:
        limit = ["-t", "%.3f" % t_limit]
    elif has_audio and vdur > 0:
        limit = ["-t", "%.3f" % vdur]
    else:
        limit = []
    tail = ["-movflags", "+faststart", "-map_metadata", "0", os.fspath(out)]
    if vkbps:
        # two-pass average bitrate: the way to land just under a size cap
        import tempfile
        with tempfile.TemporaryDirectory(prefix="st-2pass-") as td:
            lb = os.path.join(td, "x264")
            ff.run_ffmpeg(base + video_args(vkbps) + ["-pass", "1", "-passlogfile", lb, "-an"] + limit + ["-f", "null", "-"])
            ff.run_ffmpeg(base + video_args(vkbps) + ["-pass", "2", "-passlogfile", lb] + audio_args + limit + tail)
            size = Path(out).stat().st_size
            if size > cap * 1e6:
                # rate control overshot: pass 2 again at the measured ratio
                vkbps = int(vkbps * cap * 1e6 / size * 0.97)
                ff.run_ffmpeg(base + video_args(vkbps) + ["-pass", "2", "-passlogfile", lb] + audio_args + limit + tail)
    else:
        ff.run_ffmpeg(base + video_args(None) + audio_args + limit + tail)
        if quality_cap and cap and Path(out).stat().st_size > cap * 1e6:
            # the quality encode came out over the cap after all: two-pass at the budget's rate
            import tempfile
            vkbps = quality_cap
            with tempfile.TemporaryDirectory(prefix="st-2pass-") as td:
                lb = os.path.join(td, "x264")
                ff.run_ffmpeg(base + video_args(vkbps) + ["-pass", "1", "-passlogfile", lb, "-an"] + limit + ["-f", "null", "-"])
                ff.run_ffmpeg(base + video_args(vkbps) + ["-pass", "2", "-passlogfile", lb] + audio_args + limit + tail)
    if has_audio:
        tp = ff.ensure_true_peak(out, target.true_peak, audio_source=src, af=af,
                                 bitrate="%dk" % target.audio_kbps)
        loud["encoded_true_peak"] = tp["after"]
        if tp["attempts"]:
            loud["peak_repair"] = tp["attempts"]
            if not tp["fixed"]:
                warnings.append("true peak %.1f dBTP is above the %.1f dBTP ceiling" % (tp["after"], target.true_peak)
                                if tp["after"] is not None else "the true peak could not be measured after the repair "
                                "(it was %.1f dBTP, ceiling %.1f)" % (tp["before"], target.true_peak))
    res = ff.probe(out)
    rect = picture_rect(sw, sh, target.width, target.height, mode)
    side = Path(str(out) + ".export.json")
    if rect:
        # qa judges black and frozen stretches inside the picture, not on the bars around it
        import json as _json
        side.write_text(_json.dumps({"source": os.fspath(Path(src).name), "fit": mode, "picture": rect,
                                     "size": [target.width, target.height]}), encoding="utf-8")
    elif side.exists():
        side.unlink()
    a_durs = [a.get("duration") for a in res.get("audio_streams") or [] if a.get("duration")]
    v_out = res.get("video_duration")
    if a_durs and v_out and max(a_durs) > v_out + 1.0 / max(out_fps, 1.0):
        warnings.append("audio runs %.2fs past the video" % (max(a_durs) - v_out))
    if cap and (res.get("size_bytes") or 0) > cap * 1e6:
        warnings.append("%.1f MB is over the %s MB cap" % ((res.get("size_bytes") or 0) / 1e6, cap))
    if has_audio and loudnorm:
        try:
            after = ff.measure_loudness(out, target.lufs, target.true_peak)
            loud["output_lufs"] = after.get("input_i")
            loud["output_true_peak"] = after.get("input_tp")
            if abs(after["input_i"] - target.lufs) > 1.5:
                warnings.append("output loudness %.1f LUFS (target %.1f)" % (after["input_i"], target.lufs))
        except ShowtimeError:
            pass
    return {
        "target": target.name, "output": str(out), "fit": mode,
        "width": res.get("width"), "height": res.get("height"), "fps": res.get("fps"),
        "duration": res.get("duration"), "size_bytes": res.get("size_bytes"),
        "bitrate_kbps": round((res.get("bit_rate") or 0) / 1000.0),
        "loudness": dict(loud, target=target.lufs if has_audio and loudnorm else None,
                         target_source=(lufs_source or "--lufs") if (has_audio and lufs is not None) else
                         (target.name if has_audio and loudnorm else None)),
        "warnings": warnings, "notes": notes, "max_mb": cap, "video_kbps": vkbps, "picture": rect,
    }


def carry_report(src: Path, out: Path, out_height: int) -> Optional[Path]:
    """Copy an `edit render` report (<stem>.report.json) to the export, with the upscale factors
    scaled to the export's height, so qa of the export still sees how far the sources were enlarged."""
    import json
    from ..qa.video import edit_report
    rep = edit_report(src)
    if not rep:
        return None
    src_h = float(((rep.get("output") or {}) if isinstance(rep.get("output"), dict) else {}).get("height") or 0) or None
    try:
        src_h = src_h or float(ff.probe(src).get("display_height") or 0)
    except ShowtimeError:
        src_h = None
    k = (out_height / src_h) if src_h else 1.0
    rep = json.loads(json.dumps(rep))
    for meta in rep.get("segment_meta") or []:
        up = (meta or {}).get("upscale") if isinstance(meta, dict) else None
        if isinstance(up, dict) and up.get("factor"):
            up["factor"] = round(float(up["factor"]) * k, 3)
    rep["exported_from"] = str(src)
    dest = out.with_name(out.stem + ".report.json")
    dest.write_text(json.dumps(rep, indent=1), encoding="utf-8")
    return dest


def export(src: PathLike, targets: Union[str, Sequence[str]], out_dir: Optional[PathLike] = None,
           fit: str = "auto", focus_x: float = 0.5, focus_y: float = 0.5, loudnorm: bool = True,
           trim: bool = False, preview: bool = False, pad_color: str = "black",
           max_mb: Any = None, start: Optional[float] = None, end: Optional[float] = None,
           width: Optional[int] = None, fps: Optional[float] = None, lufs: Optional[float] = None,
           lufs_source: Optional[str] = None) -> Dict[str, Any]:
    """Export `src` for every target; files are named <stem>.<target>.mp4 (.gif/.webp for image loops).

    max_mb: N (caps the size targets: original/github/chat/web and the loops, or every target when none of
    those is listed), "target:N,..." per target, or both (see parse_max_mb). lufs: deliver this loudness
    instead of each platform's (lufs_source: where it came from, reported).
    start/end (seconds), width and fps shape the image loops (gif, webp, gif-small, webp-small) only."""
    src_p = Path(src)
    if not src_p.is_file():
        raise ShowtimeError("file not found: %s" % src_p,
                            hint="pass the video file or its job folder (showtime status lists recent jobs)")
    tl = parse_targets(targets)
    bare, per = parse_max_mb(max_mb)
    unlisted = [n for n in per if n not in [t.name for t in tl]]
    if unlisted:
        raise ShowtimeError("--max-mb names %s, which is not in --targets" % ", ".join(unlisted),
                            hint="add it to --targets, or drop it from --max-mb")
    names = [t.name for t in tl]
    loop_opts = [n for n, v in (("--from", start), ("--to", end), ("--width", width), ("--fps", fps)) if v is not None]
    if loop_opts and any(not t.is_loop for t in tl):
        raise ShowtimeError("%s shape the image loops (%s) only" % ("/".join(loop_opts), ", ".join(LOOP_TARGETS)),
                            hint="export the MP4 targets in a separate run without %s" % "/".join(loop_opts))
    if width is not None and width < 64:
        raise ShowtimeError("--width %d is too small (64 px or more)" % width)
    if fps is not None and not (1 <= fps <= 60):
        raise ShowtimeError("--fps %g is out of range (1 to 60)" % fps)
    od = Path(out_dir) if out_dir else src_p.parent / "exports"
    od.mkdir(parents=True, exist_ok=True)
    info = ff.probe(src_p)
    cache: Dict[Any, Dict[str, float]] = {}
    results = []
    for t in tl:
        cap, asked = cap_for(t, bare, per, names)
        name = t.name
        if t.name == "original" and cap:
            name = "%smb" % ("%g" % cap)
        elif asked:
            name = "%s-%smb" % (t.name, "%g" % cap)
        if t.is_loop:
            # <stem>.loop.webp / .gif, <stem>.loop-small.gif, <stem>.loop-2mb.gif (--max-mb)
            name = "loop" + t.name[len(t.kind):] + ("-%smb" % ("%g" % cap) if asked else "")
        out = od / ("%s.%s.%s" % (src_p.stem, name, t.kind))
        if out.resolve() == src_p.resolve():
            raise ShowtimeError("export would overwrite the input: %s" % out,
                                hint="choose another --out-dir (the default is an exports/ folder beside the video)")
        if t.is_loop:
            from . import loops
            r = loops.export_loop(src_p, t.kind, out, width=int(width or t.loop_width), fps=float(fps or t.loop_fps),
                                  max_mb=cap, start=start, end=end, info=info, name=t.name)
            for w in r["warnings"]:
                warn("%s: %s" % (t.name, w))
            results.append(r)
            continue
        log("exporting %s -> %s (%s%s)" % (src_p.name, out.name, "%dx%d" % (t.width, t.height) if t.width else "master size",
                                          ", under %g MB" % cap if cap else ""))
        measured = None
        want = t.lufs if lufs is None else float(lufs)
        if info.get("has_audio") and loudnorm and t.audio:
            key = (want, t.true_peak)
            if key not in cache:
                cache[key] = ff.measure_loudness(src_p, want, t.true_peak - ff.TP_MARGIN_DB)
            measured = cache[key]
        r = export_one(src_p, t, out, fit, focus_x, focus_y, loudnorm, trim, preview, pad_color, info, measured,
                       max_mb=cap if asked else None, lufs=lufs, lufs_source=lufs_source)
        try:
            carried = carry_report(src_p, out, int(r.get("height") or 0))
            if carried:
                r["report"] = str(carried)
        except Exception as e:  # noqa: BLE001 - lineage is a convenience
            warn("could not carry the edit report to %s: %s" % (out.name, e))
        for w in r["warnings"]:
            warn("%s: %s" % (t.name, w))
        for n in r.get("notes") or []:
            log("%s: %s" % (t.name, n))
        results.append(r)
    return {"input": str(src_p), "out_dir": str(od), "exports": results}

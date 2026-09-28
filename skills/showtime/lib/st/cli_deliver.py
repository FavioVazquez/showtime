"""`showtime deliver ...`: posters, platform exports and thumbnails."""
from __future__ import annotations

import argparse
from pathlib import Path

from typing import Any, List, Optional, Tuple

from .common import ShowtimeError, log, print_json

COMMANDS = {
    "deliver": "Finish a video: poster frame, platform exports (YouTube, X, Reels...), thumbnails",
}


def register(sub: argparse._SubParsersAction) -> None:
    d = sub.add_parser("deliver", help=COMMANDS["deliver"], description=(
        "Delivery tools for a finished video.\n\n"
        "  poster   pick a poster frame; --bake puts it on frame 0 (audio untouched)\n"
        "  exports  platform versions with the right size, bitrate and loudness\n"
        "  thumb    1280x720 thumbnail from a frame or an image\n"
        "  targets  list export targets"), formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("Examples:\n"
                "  showtime deliver exports launch --targets youtube,reels   # a job: its latest final\n"
                "  showtime deliver exports final.mp4 --targets youtube,reels,square\n"
                "  showtime deliver exports final.mp4 --targets all --trim\n"
                "  showtime deliver poster final.mp4 --bake          # poster on frame 0 for feeds\n"
                "  showtime deliver thumb final.mp4 --at 7.4\n"
                "  showtime deliver targets"))
    ds = d.add_subparsers(dest="deliver_cmd", metavar="<subcommand>")

    p = ds.add_parser("poster", help="pick a poster frame; optionally bake it into frame 0 or attach as cover",
                      formatter_class=argparse.RawDescriptionHelpFormatter,
                      epilog="Examples:\n  showtime deliver poster final.mp4\n  showtime deliver poster final.mp4 --at 7.4 --bake\n"
                             "  showtime deliver poster launch --bake     # a job: its latest final; records final=<baked>\n"
                             "  showtime deliver poster final.mp4 --project my-video --cover",
                      description="Pick the poster frame (auto-scored, --at, or the project's showtime.json "
                                  "'poster' time), write it as PNG, and optionally bake it into frame 0 "
                                  "(re-encodes video once; audio is copied so duration and sync are unchanged).\n\n"
                                  "<video> may be a job folder or name (or left out inside a job): the job's latest final. "
                                  "Inside a job the poster image and a baked/cover video are recorded in job.json "
                                  "(poster=, final=), so qa, review-pack and exports follow the baked file. "
                                  "A poster is baked once: when frame 0 already holds it (a render with showtime.json "
                                  "\"poster\", or an earlier --bake) and --at is not a different time, nothing is re-encoded. "
                                  "Default outputs never overwrite (<video>.poster-2.png ...).")
    p.add_argument("video", nargs="?", help="input video, or a job folder/name (its latest final); default: the "
                                            "current or newest job")
    p.add_argument("--at", type=float, help="poster time in seconds (default: auto-pick)")
    p.add_argument("--project", help="project folder whose showtime.json has a 'poster' time")
    p.add_argument("--image", help="use this image as the poster instead of a frame")
    p.add_argument("--out", help="poster image path (default: <video>.poster.png)")
    p.add_argument("--bake", action="store_true", help="replace frame 0 with the poster")
    p.add_argument("--cover", action="store_true", help="attach the poster as MP4 cover art (no re-encode)")
    p.add_argument("-o", "--output", help="output video for --bake/--cover (default: <video>.poster.mp4)")
    p.add_argument("--samples", type=int, default=12, help="frames to score when auto-picking (default 12)")
    p.add_argument("--json", action="store_true", help="print a JSON report")
    p.set_defaults(func=cmd_poster)

    p = ds.add_parser("exports", help="make platform versions (youtube, x, linkedin, reels, tiktok, shorts, square; "
                                      "original/github/chat/web for size-capped copies; webp/gif loops for READMEs)",
                      formatter_class=argparse.RawDescriptionHelpFormatter,
                      epilog="Examples:\n  showtime deliver exports final.mp4 --targets youtube,x\n"
                             "  showtime deliver exports final.mp4 --targets reels,shorts --fit crop --focus 0.4\n"
                             "  showtime deliver exports final.mp4 --targets all --preview   # check framing fast\n"
                             "  showtime deliver exports final.mp4 --targets original --max-mb 20   # same size, under 20 MB\n"
                             "  showtime deliver exports final.mp4 --targets youtube,original --max-mb 20   # YouTube uncapped\n"
                             "  showtime deliver exports final.mp4 --targets shorts,original --max-mb shorts:19,original:20\n"
                             "  showtime deliver exports final.mp4 --targets github,chat            # under 10 MB each\n"
                             "  showtime deliver exports final.mp4 --targets webp,gif --from 2 --to 8   # README hero loop\n"
                             "  showtime deliver exports final.mp4 --targets webp-small,gif-small --from 0:04 --to 0:09\n"
                             "  showtime deliver exports final.mp4 --targets gif --width 640 --fps 12 --max-mb 2",
                      description="Export a master video for one or more platforms. Files are written as "
                                  "<stem>.<target>.mp4 in --out-dir (default: <video dir>/exports). A job folder or "
                                  "name exports that job's latest final (e.g. the baked final.poster.mp4). "
                                  "'all' means the seven social platforms. original/github/chat/web keep the master's "
                                  "size; github and chat stay under 10 MB, web under 15 MB without audio, and --max-mb N "
                                  "caps those (and the loops; every target when none of them is listed), --max-mb "
                                  "shorts:19 caps one platform (two-pass bitrate from the duration; decimal MB like upload "
                                  "limits; a master already under the budget gets a quality encode, never a bigger file). "
                                  "A capped file is named <stem>.<N>mb.mp4 (original) or <stem>.<target>-<N>mb.mp4. x and "
                                  "linkedin keep a 1:1 or 4:5 master's aspect (--fit converts). Loudness: the job's target "
                                  "(qa --lufs, showtime.json expect.lufs) or --lufs, else each platform's -14 LUFS.\n\n"
                                  "Image loops (silent, loop forever): webp and gif are a README hero loop (960 px wide, "
                                  "15 fps, under 5 MB); webp-small and gif-small a showcase/docs loop (480 px, 12 fps, "
                                  "under 1.5 MB). GIFs use a two-pass palette; ship the WebP with the GIF as fallback. "
                                  "--from/--to pick the window, --width/--fps override the size and rate, and a loop "
                                  "over its cap is re-encoded smaller (quality, then fps, then width) until it fits.")
    p.add_argument("video", nargs="?", help="master video, or a job folder/name (its latest final); default: the "
                                            "current or newest job")
    p.add_argument("--targets", required=True, help="comma list, e.g. youtube,x,reels (or 'all')")
    p.add_argument("--fit", default="auto", choices=["auto", "blur", "crop", "pad", "scale"],
                   help="aspect conversion. auto: crop when the aspect differs by 12%% or less, else blur (a blurred "
                        "copy fills the bars; bright designs smear into them). pad: bars in --pad-color, best for "
                        "text-heavy designs on a flat background")
    p.add_argument("--focus", type=float, default=0.5, help="crop focus, 0=left .. 1=right (default 0.5)")
    p.add_argument("--focus-y", type=float, default=0.5, help="crop focus, 0=top .. 1=bottom (default 0.5)")
    p.add_argument("--pad-color", default=None,
                   help="colour for --fit pad (default: the project's showtime.json background, else black)")
    p.add_argument("--max-mb", metavar="MB|T:MB", help="size cap in MB. A bare number caps original/github/chat/web and the "
                   "image loops (every target when the list has none of those); target:MB caps one target, e.g. "
                   "--max-mb original:20,shorts:19. Two-pass bitrate; a master already under the budget is not "
                   "inflated to it; loops shrink to fit")
    p.add_argument("--lufs", type=float, help="loudness for every export (default: the job's target from qa --lufs or "
                   "showtime.json expect.lufs/loudness, else each platform's -14)")
    p.add_argument("--from", dest="start", type=_time_arg, metavar="T",
                   help="image loops: start of the window (seconds or mm:ss; default 0)")
    p.add_argument("--to", dest="end", type=_time_arg, metavar="T",
                   help="image loops: end of the window (seconds or mm:ss; default the end)")
    p.add_argument("--width", type=int, help="image loops: width in px (default 960, or 480 for -small; never enlarged)")
    p.add_argument("--fps", type=float, help="image loops: frame rate (default 15, or 12 for -small)")
    p.add_argument("--out-dir", help="output folder")
    p.add_argument("--trim", action="store_true", help="cut videos longer than the platform limit")
    p.add_argument("--no-loudnorm", action="store_true", help="keep the audio level as is")
    p.add_argument("--preview", action="store_true", help="fast, lower-quality encodes for checking framing")
    p.add_argument("--json", action="store_true", help="print a JSON report")
    p.set_defaults(func=cmd_exports)

    p = ds.add_parser("thumb", help="thumbnail (default 1280x720 JPEG under 2 MB)",
                      formatter_class=argparse.RawDescriptionHelpFormatter,
                      epilog="Examples:\n  showtime deliver thumb final.mp4\n  showtime deliver thumb final.mp4 --at 3.2 -o thumb.jpg\n"
                             "  showtime deliver thumb poster.png --size 1080x1080 --fit crop",
                      description="Make a thumbnail from a video frame (auto-picked or --at) or an image.")
    p.add_argument("source", nargs="?", help="video or image, or a job folder/name (its latest final); default: the "
                                             "current or newest job")
    p.add_argument("--at", type=float, help="frame time in seconds (default: auto-pick)")
    p.add_argument("-o", "--output", help="output .jpg/.png/.webp (default: <source>.thumb.jpg)")
    p.add_argument("--size", default="1280x720", help="WIDTHxHEIGHT (default 1280x720)")
    p.add_argument("--fit", default="auto", choices=["auto", "blur", "crop", "pad", "scale"])
    p.add_argument("--focus", type=float, default=0.5, help="crop focus 0..1 (default 0.5)")
    p.add_argument("--json", action="store_true", help="print a JSON report")
    p.set_defaults(func=cmd_thumb)

    p = ds.add_parser("targets", help="list export targets and their rules",
                      formatter_class=argparse.RawDescriptionHelpFormatter,
                      epilog="Examples:\n  showtime deliver targets\n  showtime deliver targets --json")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_targets)


def _time_arg(v: str) -> float:
    from .common import parse_time
    try:
        t = parse_time(v)
    except ShowtimeError as e:
        raise argparse.ArgumentTypeError(str(e))
    if t < 0:
        raise argparse.ArgumentTypeError("time must be 0 or more: %r" % v)
    return t


def _video_arg(arg: Optional[str]) -> Tuple[Path, Optional[Path]]:
    """A file as given, or a job folder/name/None -> that job's latest final (else preview)."""
    from .job import ledger
    video, job, _ = ledger.media_arg(arg, "video", say=log)
    return video, job


def _fresh(p: Path) -> Path:
    """`p`, or p-2, p-3 ... when it exists (default outputs never overwrite)."""
    if not p.exists():
        return p
    k = 2
    while True:
        c = p.with_name("%s-%d%s" % (p.stem, k, p.suffix))
        if not c.exists():
            return c
        k += 1


def _record(target: Path, outputs: List[str], **kw: Any) -> Optional[Path]:
    try:
        from .job import ledger
        return ledger.record_outputs(target, outputs, **kw)
    except Exception as e:  # noqa: BLE001 - the ledger is a convenience
        from .common import debug
        debug("could not update the job ledger: %s" % e)
        return None


def cmd_poster(args: argparse.Namespace) -> int:
    from .deliver import poster
    from .job import ledger
    video, _job = _video_arg(args.video)
    video = video.resolve()
    report: dict = {}
    if args.bake and not args.image:
        done = poster.baked_time(video)
        want = args.at
        if want is None and args.project:
            want = poster.project_poster_time(args.project)
        if done is not None and (want is None or done.get("time") is None or abs(float(want) - float(done["time"])) < 0.02):
            tt = "t=%.2fs" % done["time"] if done.get("time") is not None else "the poster"
            log("the poster frame (%s) is already frame 0 of %s (baked by %s); nothing to do" % (tt, video.name, done["by"]))
            report = {"video": str(video), "time": done.get("time"), "method": "already-baked",
                      "bake": {"output": str(video), "skipped": True, "by": done["by"]}}
            if args.json:
                print_json(report)
            else:
                print(str(video))
            return 0
    if args.image:
        img = Path(args.image)
        if not img.is_file():
            raise ShowtimeError("file not found: %s" % img, hint="check the image path (relative paths start from the current folder)")
        report = {"video": str(video), "poster": str(img.resolve()), "time": None, "method": "image"}
    else:
        out_img = Path(args.out) if args.out else _fresh(video.with_name(video.stem + ".poster.png"))
        report = poster.make_poster(video, out_img, args.at, args.project, samples=args.samples)
        log("poster at %.3fs (%s) -> %s" % (report["time"], report["method"], report["poster"]))
    stem = video.stem if video.stem.endswith(".poster") else video.stem + ".poster"
    out = Path(args.output) if args.output else _fresh(video.with_name(stem + ".mp4"))
    kind = "preview" if ledger.infer_kind(video) == "preview" else "final"
    outs = ["poster=%s" % Path(report["poster"]).resolve()] if not args.image else []
    baked = None
    if args.bake:
        report["bake"] = poster.bake(video, out, image=report["poster"], poster_time=report.get("time"))
        log("baked poster into frame 0 -> %s" % out)
        outs.append("%s=%s" % (kind, out.resolve()))
        if report.get("time") is not None:
            baked = {str(out.resolve()): float(report["time"])}
    elif args.cover:
        report["cover"] = poster.attach_cover(video, report["poster"], out)
        log("attached cover art -> %s" % out)
        outs.append("%s=%s" % (kind, out.resolve()))
    if outs:
        ev = "poster at %.2fs" % report["time"] if report.get("time") is not None else "poster from an image"
        if args.bake:
            ev += " baked into %s" % out.name
        job = _record(video, outs, stage="deliver" if (args.bake or args.cover) else None, event=ev, baked=baked)
        if job is not None:
            report["job"] = str(job)
            if args.bake or args.cover:
                log("job %s: latest %s -> %s" % (job.name, kind, out.name))
    if args.json:
        print_json(report)
    else:
        print(report.get("bake", report.get("cover", {})).get("output", report.get("poster")))
    return 0


def _project_background(video: Path, job: Optional[Path]) -> Optional[str]:
    """showtime.json "background" of the project that made `video` (render.json, else the job's project)."""
    import json
    cands = []
    for rj in (video.with_suffix(".work") / "render.json", video.parent / "render.json"):
        try:
            r = json.loads(rj.read_text(encoding="utf-8"))
            if r.get("project"):
                cands.append(Path(r["project"]))
        except (OSError, ValueError):
            pass
    if job is not None:
        try:
            from .job import ledger
            pj = ledger.project_of(job, ledger.load(job))
            if pj:
                cands.append(Path(pj))
        except Exception:  # noqa: BLE001
            pass
    for c in cands:
        try:
            bg = json.loads((c / "showtime.json").read_text(encoding="utf-8-sig")).get("background")
        except (OSError, ValueError):
            continue
        if isinstance(bg, str) and bg.strip() and "gradient" not in bg and "url(" not in bg:
            return bg.strip()
    return None


def cmd_exports(args: argparse.Namespace) -> int:
    from .deliver import exports
    video, job = _video_arg(args.video)
    pad = args.pad_color or _project_background(video, job) or "black"
    lufs, lsrc = (args.lufs, "--lufs") if args.lufs is not None else exports.job_loudness(video, job)
    rep = exports.export(video, args.targets, args.out_dir, args.fit, args.focus, args.focus_y,
                         loudnorm=not args.no_loudnorm, trim=args.trim, preview=args.preview,
                         pad_color=pad, max_mb=args.max_mb, start=args.start, end=args.end,
                         width=args.width, fps=args.fps, lufs=lufs, lufs_source=lsrc)
    if job is not None and (job / "job.json").is_file():
        try:
            from .job import ledger
            ledger.note(job, stage="deliver", event="exports of %s: %s" % (
                video.name, ", ".join(r["target"] for r in rep["exports"])))
        except Exception:  # noqa: BLE001
            pass
    if args.json:
        print_json(rep)
    else:
        for r in rep["exports"]:
            if r.get("format") in ("gif", "webp"):
                print("%-10s %s  %sx%s  %.2fs  %.3g fps  %.2f MB%s  [loop %.2f-%.2fs]" % (
                    r["target"], r["output"], r["width"], r["height"], r["duration"] or 0, r["fps"],
                    (r["size_bytes"] or 0) / 1e6, (" (cap %g MB)" % r["max_mb"]) if r.get("max_mb") else "",
                    r["from"], r["to"]))
                continue
            lo = r["loudness"].get("output_lufs")
            tp = r["loudness"].get("encoded_true_peak")
            print("%-9s %s  %sx%s  %.2fs  %.1f MB%s%s%s  [%s]" % (
                r["target"], r["output"], r["width"], r["height"], r["duration"] or 0,
                (r["size_bytes"] or 0) / 1e6, (" (cap %g MB)" % r["max_mb"]) if r.get("max_mb") else "",
                ("  %.1f LUFS" % lo) if lo is not None else "",
                ("  %.1f dBTP" % tp) if tp is not None else "", r["fit"]))
            for n in r.get("notes") or []:
                print("          note: %s" % n)
        _exports_card(rep)
    return 0


def _exports_card(rep: dict) -> None:
    """Terminals only: what was exported, where, and how to open it."""
    from . import delight
    from .common import human_size
    outs = [r for r in rep.get("exports") or [] if r.get("output")]
    if not outs:
        return
    if len(outs) == 1:
        r = outs[0]
        where = Path(r["output"])
        title, facts = "%s is ready" % where.name, [delight.fmt_len(r.get("duration")),
                                                    "%sx%s" % (r.get("width"), r.get("height")),
                                                    human_size(r.get("size_bytes"))]
    else:
        where = Path(rep.get("out_dir") or Path(outs[0]["output"]).parent)
        title = "%d exports are ready" % len(outs)
        facts = [", ".join(str(r.get("target")) for r in outs[:4]) + (", ..." if len(outs) > 4 else ""),
                 human_size(sum(r.get("size_bytes") or 0 for r in outs)) + " in all"]
    delight.show_card(title, where, facts, delight.open_hint(where))


def cmd_thumb(args: argparse.Namespace) -> int:
    from .deliver import thumbs
    src = Path(args.source).expanduser() if args.source else None
    if src is None or not src.is_file():
        src, _job = _video_arg(args.source)
    rep = thumbs.thumbnail(src, args.output, args.at, args.size, args.fit, args.focus)
    if args.json:
        print_json(rep)
    else:
        print(rep["output"])
    return 0


def cmd_targets(args: argparse.Namespace) -> int:
    from .deliver import exports
    ts = exports.list_targets()
    if args.json:
        print_json(ts)
        return 0
    for t in ts:
        if t.get("kind") in ("gif", "webp"):
            print("%-10s %9s  %-10s %-19s %s" % (t["name"], "%d px" % t["loop_width"], "%g fps" % t["loop_fps"],
                                               "loop, max %g MB" % t["max_mb"], t["note"]))
            continue
        lim = ("max %ds" % t["max_duration"]) if t["max_duration"] else "no limit"
        size = "%4dx%-4d" % (t["width"], t["height"]) if t["width"] else "  master "
        print("%-10s %s  %-10s %5d kbps  %.0f LUFS  %s" % (
            t["name"], size, lim, t["maxrate_kbps"], t["lufs"], t["note"]))
    return 0

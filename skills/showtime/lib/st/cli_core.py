"""Core commands: doctor, setup, paths, new.

Stdlib only (these commands also run before the venv exists).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .common import ShowtimeError, log, paths, portable_path, print_json, read_json, warn, write_json

COMMANDS = {
    "doctor": "Check the installation (runs ffmpeg, Python, Node and a browser for real)",
    "setup": "Install or update dependencies and models into ~/.showtime",
    "paths": "Show where showtime keeps its tools, models and caches",
    "new": "Create a project from a template: showtime new <template> <dir>",
    "retime": "Change a project's length; scenes, poster, music and captions move with it",
}


def register(sub: argparse._SubParsersAction) -> None:
    # doctor parses its own options (st/doctor.py) so both entry points agree.
    p = sub.add_parser("doctor", help=COMMANDS["doctor"], add_help=False,
                       description="Runs st.doctor; see `showtime doctor --help`.")
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("setup", help=COMMANDS["setup"], add_help=False,
                       description="Runs setup/setup.py; see `showtime setup --help`.")
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_setup)

    p = sub.add_parser("paths", help=COMMANDS["paths"], description=COMMANDS["paths"],
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="Examples:\n  showtime paths\n  showtime paths models\n  showtime paths --json")
    p.add_argument("--json", action="store_true", help="print a JSON object")
    p.add_argument("name", nargs="?", help="print just one path (e.g. models, bin, venv_python)")
    p.set_defaults(func=cmd_paths)

    register_new(sub)


# ------------------------------------------------------------------ doctor

def cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import main as doctor_main
    return doctor_main(list(args.rest))


def cmd_setup(args: argparse.Namespace) -> int:
    setup_py = paths()["setup"] / "setup.py"
    base = getattr(sys, "_base_executable", None) or sys.executable
    return subprocess.call([base, str(setup_py)] + list(args.rest))


# ------------------------------------------------------------------- paths

def cmd_paths(args: argparse.Namespace) -> int:
    p = {k: str(v) for k, v in paths().items()}
    if args.name:
        if args.name not in p:
            raise ShowtimeError("unknown path %r; choose from: %s" % (args.name, ", ".join(sorted(p))))
        print(p[args.name])
        return 0
    if args.json:
        print_json(p)
        return 0
    w = max(len(k) for k in p)
    for k in sorted(p):
        exists = os.path.exists(p[k])
        print("%s  %s%s" % (k.ljust(w), p[k], "" if exists else "  (missing)"))
    return 0


# --------------------------------------------------------------------- new

def _first_line(readme: Path) -> str:
    if readme.is_file():
        for line in readme.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip().lstrip("#").strip()
            if s:
                return s
    return ""


def list_templates() -> List[Dict[str, Any]]:
    """Project templates: the folders under SKILL/templates that hold a showtime.json.

    Other folders there (e.g. `studio`, the board files `showtime studio init` copies) are not
    video projects and are left out.
    """
    root = paths()["templates"]
    out = []
    if root.is_dir():
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name.startswith((".", "_")) or not (d / "showtime.json").is_file():
                continue
            try:
                cfg = read_json(d / "showtime.json", {}) or {}
            except ShowtimeError:
                cfg = {}
            out.append({"name": d.name, "path": str(d), "description": _first_line(d / "README.md"),
                        "size": "%sx%s" % (cfg.get("width", 1920), cfg.get("height", 1080)),
                        "fps": cfg.get("fps"), "duration": cfg.get("duration")})
    return out


ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350)}


def _parse_size(text: str) -> Any:
    m = re.match(r"^\s*(\d+)\s*[xX*:,]\s*(\d+)\s*$", text or "")
    if not m:
        raise argparse.ArgumentTypeError("use WIDTHxHEIGHT, e.g. 1280x720")
    return int(m.group(1)), int(m.group(2))


def register_new(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("new", help=COMMANDS["new"], description=(
        "Copy SKILL/templates/<template> into <dir> and fill in showtime.json.\n"
        "Run without arguments to list templates.\n\n"
        "--duration rescales the whole timeline, not just showtime.json: every scene's\n"
        "data-start/data-dur, the poster time, the audio mix (music sections, sfx and voice\n"
        "positions), caption word times and canvas cue tables move together, so the scenes\n"
        "fill the new length (see `showtime retime --help`)."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("Examples:\n"
                "  showtime new --list\n"
                "  showtime new dom my-launch                      # 16:9 product launch\n"
                "  showtime new dom my-launch --duration 20        # every scene, the poster and the music scale to 20 s\n"
                "  showtime new short my-reel --duration 15\n"
                "  showtime new dom teaser --size 1280x720 --duration 8\n"
                "  showtime new film explainer --title \"How it works\"\n"
                "  showtime new data ~/charts/signups --job signups-data   # a project outside the job folder"))
    p.add_argument("template", nargs="?", help="template name (see `showtime new --list`)")
    p.add_argument("dir", nargs="?", help="destination folder (created; must be empty unless --force)")
    p.add_argument("--list", action="store_true", help="list templates and exit")
    p.add_argument("--title", help="video title (default: folder name)")
    p.add_argument("--size", type=_parse_size, metavar="WxH", help="frame size, e.g. 1280x720")
    p.add_argument("--width", type=int)
    p.add_argument("--height", type=int)
    p.add_argument("--fps", type=float)
    p.add_argument("--duration", "-d", type=float, metavar="S",
                   help="length in seconds; scenes, poster, music and cues are rescaled to fit")
    p.add_argument("--background", help="CSS colour, e.g. '#000'")
    p.add_argument("--aspect", choices=list(ASPECTS),
                   help="shortcut for width/height at 1080p (16:9=1920x1080, 9:16=1080x1920 ...)")
    p.add_argument("--force", action="store_true", help="allow a non-empty destination (files are overwritten)")
    p.add_argument("--job", "-j", metavar="JOB",
                   help="record the project in this job (folder or name); a <dir> inside a job folder is "
                        "recorded in that job without it")
    p.add_argument("--no-brand", action="store_true",
                   help="launch/promo templates: do not apply the brand kit found for the project (brand.json)")
    p.add_argument("--mode", choices=["quality", "lean"],
                   help="review mode for this video (showtime.json \"review_mode\", and its job's): quality (the "
                        "default: full review, a critic round before delivery) or lean (a draft pass: no critic round "
                        "unless publish-bound or asked, one look per stage)")
    p.add_argument("--no-reference-style", action="store_true",
                   help="do not link the job's style reference (references/*/style.css) into the page")
    p.add_argument("--json", action="store_true", help="print the created project as JSON")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("retime", help=COMMANDS["retime"], description=(
        "Change a project's length and move its whole timeline with it.\n\n"
        "Scenes are the top-level clips in the page (elements with data-start/data-dur that are\n"
        "not inside another clip). Longer: each scene's length is multiplied by new/old, and\n"
        "everything inside a scene (component data-at times, sound effects, voice lines,\n"
        "caption words, the poster) keeps its offset from the start of its scene, so animations\n"
        "run at the same speed and each scene holds longer. Shorter: everything is scaled by\n"
        "new/old, including the times inside scenes. Music sections move with the scene\n"
        "starts. Canvas projects: every number in the `var CUE = {...}` table of the\n"
        "project's *.js files is scaled (except cps), and bpm is adjusted so the cues stay on\n"
        "bar lines. A scene stretched more than %gx gets a warning: it now holds still after\n"
        "its last animation, so give it more content or motion.\n\n"
        "--from-voice <timeline.json> (from `showtime voice script`) sets the scene lengths from\n"
        "the narration instead: lines are matched to scenes by id (a line \"bars\" narrates the\n"
        "scene id=\"bars\"), else in order, else by --map. Each narrated scene becomes --pad +\n"
        "the slots of its lines (a slot runs from a line's start to the next line's start, so it\n"
        "includes the pause; the last one includes the tail); scenes without a line after the\n"
        "narration (an end card) keep their length. Every line becomes a voice track at scene\n"
        "start + pad in audio/mix.json (music ducks under it), music sections, sound effects\n"
        "and the poster move with their scenes, and the caption layer reads\n"
        "voice/captions.words.json (word times in the video). Files are edited in place;\n"
        "--dry-run shows the changes first.\n\n"
        "A scene start or end that falls within 1 ms after a frame is written at that frame (at or\n"
        "just below the frame time), so the stage and the transitions agree on every cut. Overlays are not scenes: a top-level\n"
        "clip marked data-overlay, one without a length (a persistent credit, a logo bug), or on a\n"
        "page of <section class=\"scene\"> scenes any other top-level clip; they follow the scenes\n"
        "they sit over. Not rescaled: CSS animation-delay / transition-delay values and times inside\n"
        "scripts (other than a canvas film's CUE table); adjust those by hand after a retime." % STRETCH_WARN),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("Examples:\n"
                "  showtime retime my-launch --duration 20\n"
                "  showtime retime my-launch --duration 12 --dry-run\n"
                "  showtime retime my-film -d 30 --json\n"
                "  showtime retime my-reel --from-voice my-reel/voice/timeline.json\n"
                "  showtime retime my-reel --from-voice voice/timeline.json --map hook=open,demo=demo,cta=close\n"
                "  showtime retime my-reel --from-voice voice/timeline.json --map lines-to-scenes.json --pad 0.4\n"
                "  showtime retime my-launch --cuts 5.33,12.44,19.56,24.89 -d 30   (scene changes on the music's phrases)"))
    p.add_argument("project", help="project folder (with showtime.json)")
    p.add_argument("--duration", "-d", type=float, metavar="S", help="new length in seconds")
    p.add_argument("--from-voice", metavar="TIMELINE",
                   help="set scene lengths from a `voice script` timeline.json (or its folder)")
    p.add_argument("--map", "-m", metavar="MAP",
                   help="--from-voice: line=scene pairs (hook=open,demo=bars) or a JSON file {\"line\": \"scene\"}; "
                        "scenes by id or number; lines left out join the scene of the line before them")
    p.add_argument("--pad", type=float, default=0.3, metavar="S",
                   help="--from-voice: picture before each scene's first line (default 0.3 s)")
    p.add_argument("--keep-captions", action="store_true",
                   help="--from-voice: leave the caption layer's data-src alone")
    p.add_argument("--total", type=float, metavar="S",
                   help="--from-voice: keep the video S seconds long (the end card after the narration grows or "
                        "shrinks; it warns under 2.5 s; when every scene is narrated, the hold after the last line does)")
    p.add_argument("--cuts", metavar="T,T,...",
                   help="put the scene changes at these times (seconds, one per scene change, e.g. from `showtime "
                        "audio cuts`: the music's phrase starts); with --duration the video also gets that length")
    p.add_argument("--dry-run", "-n", action="store_true", help="print what would change, write nothing")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    p.set_defaults(func=cmd_retime)


def cmd_new(args: argparse.Namespace) -> int:
    templates = list_templates()
    if args.list or not args.template:
        if not templates:
            raise ShowtimeError("no templates found in %s" % paths()["templates"],
                                hint="templates are installed with the skill; is SHOWTIME_SKILL correct?")
        if getattr(args, "json", False):
            print_json(templates)
            return 0
        print("templates (showtime new <template> <dir>):")
        for t in templates:
            dur = t.get("duration")
            print("  %-10s %-10s %-6s %s" % (t["name"], t["size"], ("%gs" % float(dur)) if dur else "", t["description"]))
        print("  %-10s %-10s %-6s %s" % ("manim", "1920x1080", "", "math and diagram animation "
                                         "(use: showtime manim new <dir>)"))
        return 0
    names = {t["name"]: t for t in templates}
    if args.template == "manim" and "manim" not in names:
        raise ShowtimeError("Manim projects have their own command",
                            why="a Manim project is Python scenes + manim.json, not an HTML page",
                            hint="showtime manim new %s   (see `showtime manim new --help` for --template)"
                                 % (args.dir or "my-math"))
    if args.template not in names:
        folder = paths()["templates"] / args.template
        if args.template == "studio" or folder.is_dir():
            raise ShowtimeError("'%s' is not a project template" % args.template,
                                why="that folder holds studio board files, not a video project",
                                hint="for a studio session run `showtime studio init <job>`; project templates: %s"
                                     % ", ".join(names))
        from . import __version__
        raise ShowtimeError("unknown template %r" % args.template,
                            why="this is showtime %s at %s" % (__version__, paths()["skill"]),
                            hint="available: %s (a template the docs name but this list lacks means an older "
                                 "showtime is running: `showtime doctor` says which)" % (", ".join(names) or "(none installed)"))
    if not args.dir:
        raise ShowtimeError("missing destination folder", hint="showtime new %s my-video" % args.template)
    if args.duration is not None and not (0 < args.duration <= 3600):
        raise ShowtimeError("--duration must be between 0 and 3600 seconds (got %g)" % args.duration)
    job_dir: Optional[Path] = None
    if getattr(args, "job", None):
        from .job import ledger
        job_dir = ledger.resolve(args.job)   # an unknown job is an error before anything is copied
    src = Path(names[args.template]["path"])
    dst = Path(args.dir).expanduser().resolve()
    if dst.exists() and any(dst.iterdir()) and not args.force:
        raise ShowtimeError("%s is not empty" % dst, why="showtime never overwrites earlier work by default",
                            hint="choose a new folder (e.g. %s-2) or pass --force" % dst.name)
    # the template's README.md describes the template (placeholder names, what to edit): it would go
    # stale in the project and ship with it, so it stays in the skill and the path is printed instead
    shutil.copytree(str(src), str(dst), dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", ".DS_Store", "showtime-out", "work", "README.md"))
    cfg_path = dst / "showtime.json"
    cfg: Dict[str, Any] = read_json(cfg_path, {}) if cfg_path.is_file() else {}
    if args.aspect:
        cfg["width"], cfg["height"] = ASPECTS[args.aspect]
    if args.size:
        cfg["width"], cfg["height"] = args.size
    for k in ("width", "height", "fps", "background"):
        v = getattr(args, k)
        if v is not None:
            cfg[k] = int(v) if k == "fps" and float(v).is_integer() else v
    cfg["title"] = args.title if args.title else _title_from(dst.name, cfg.get("title"))
    cfg.setdefault("template", args.template)   # read by the look history (st.variety)
    cfg.setdefault("width", 1920)
    cfg.setdefault("height", 1080)
    cfg.setdefault("fps", 30)
    cfg.setdefault("duration", 10.0)
    cfg.setdefault("background", "#000")
    if getattr(args, "mode", None):
        cfg["review_mode"] = args.mode      # read by qa's review rule when the job has no mode of its own
    for dim in ("width", "height"):
        if int(cfg[dim]) % 2:
            raise ShowtimeError("%s must be even for H.264 (got %s)" % (dim, cfg[dim]))
    write_json(cfg_path, cfg)
    film_score = _vary_film_score(dst, cfg, job_dir) if cfg.get("score") else None
    retimed: Optional[Dict[str, Any]] = None
    if args.duration is not None:
        old = float(cfg.get("duration") or 0)
        if old > 0 and abs(old - args.duration) > 1e-6:
            retimed = retime_project(dst, float(args.duration))
            cfg = read_json(cfg_path, {})
        else:
            cfg["duration"] = args.duration
            write_json(cfg_path, cfg)
    notes = _aspect_notes(dst, cfg)
    for n in notes:
        warn(n)
    job_rec = _attach_to_job(dst, job_dir)
    if job_rec and getattr(args, "mode", None):
        try:
            from .job import ledger
            ledger.note(job_rec, review_mode=args.mode)
        except Exception as e:  # noqa: BLE001 - never fail `new` over the ledger
            warn("could not record the review mode in job %s: %s" % (job_rec, e))
    branded = _brand_new_project(dst, cfg, job_rec or job_dir, getattr(args, "no_brand", False))
    ref_style = None
    if not getattr(args, "no_reference_style", False):
        from .variety import restyle
        ref_style = restyle.apply_to_project(dst, job_rec or job_dir, brand_applied=bool(branded and branded.get("applied")))
        if ref_style and ref_style.get("linked"):
            cfg = read_json(cfg_path, cfg)
    result = {"project": str(dst), "template": args.template, "config": cfg, "retime": retimed, "notes": notes,
              "review_mode": getattr(args, "mode", None),
              "film_score": film_score,
              "job": str(job_rec) if job_rec else None, "brand": branded, "reference_style": ref_style,
              "template_notes": str(src / "README.md") if (src / "README.md").is_file() else None}
    if args.json:
        print_json(result)
    else:
        log("created %s from template '%s' (%sx%s @ %sfps, %ss)" % (
            dst, args.template, cfg["width"], cfg["height"], cfg["fps"], cfg["duration"]))
        if retimed:
            for line in retimed["changes"]:
                log("  retimed " + line)
            for n in retimed["notes"]:
                warn(n)
        if film_score:
            log("score: %s %s, %g bpm, %s mood (a new one: showtime audio film-score %s --mood <mood>)" % (
                film_score["key"], film_score["mode"], film_score["bpm"], film_score["mood"], dst))
        if job_rec:
            log("job %s: project -> %s" % (job_rec.name, dst))
        if branded and branded.get("applied"):
            from .brand.commands import report as _brand_report
            _brand_report(branded["applied"])
        elif branded and branded.get("hint"):
            log(branded["hint"])
        for line in (ref_style or {}).get("log") or []:
            log(line)
        if (src / "README.md").is_file():
            log("template notes (not copied into the project): %s" % (src / "README.md"))
        print(str(dst))
    return 0


LAUNCH_KINDS = ("launch", "promo", "trailer", "teaser", "release")


def _brand_new_project(dst: Path, cfg: Dict[str, Any], job: Optional[Path], skip: bool) -> Optional[Dict[str, Any]]:
    """Brand first: a launch/promo project starts in the product's look when a brand kit is found
    (the job's brand/ folder, the project or its parents); otherwise say how to get one or record why not."""
    if str(cfg.get("kind") or "").lower() not in LAUNCH_KINDS or skip:
        return None
    try:
        from . import brand as brandmod
        from .brand.apply import apply_project
        kit = brandmod.load(dst)
        if kit is not None:
            return {"applied": apply_project(dst, kit)}
        from .brand.capture import job_brand
        rec = job_brand(job)
        if rec and rec.get("none"):
            return {"none": rec["none"]}
        where = " --job %s" % job.name if job else ""
        return {"hint": "no brand kit found: capture the product first (`showtime brand capture <repo|url>%s`), then "
                        "`showtime brand apply %s`; or record why not: `showtime brand skip%s --why \"...\"`" % (
                            where, dst, (" " + job.name) if job else "")}
    except Exception as e:  # noqa: BLE001 - never fail `new` over the brand kit
        warn("brand kit not applied: %s" % e)
        return None


def _vary_film_score(project: Path, cfg: Dict[str, Any], job: Optional[Path]) -> Optional[Dict[str, Any]]:
    """A film project's own score (st.audio.filmscore): key, tempo, chords, motif and sound picked from the
    brief's mood and away from recent jobs' scores. Never fails `new`: the template's score stays."""
    try:
        from .audio import filmscore
        from .job import ledger
        job = job or ledger.enclosing_job(project)
        goal = str((ledger.load(job) if job is not None and (job / "job.json").is_file() else {}).get("goal") or "")
        return filmscore.apply(project, brief=" ".join(x for x in (goal, str(cfg.get("title") or "")) if x))
    except Exception as e:  # noqa: BLE001
        warn("kept the template's score (%s)" % e)
        return None


def _attach_to_job(project: Path, job: Optional[Path]) -> Optional[Path]:
    """Record the new project in its job (pointers.project): the --job given, else the job folder
    that contains it. Never fails `new` over the ledger."""
    try:
        from .job import ledger
        return ledger.attach_project(project, job)
    except Exception as e:  # noqa: BLE001
        if job is not None:
            warn("could not record the project in job %s: %s" % (job, e))
        return None


def cmd_retime(args: argparse.Namespace) -> int:
    proj = Path(args.project).expanduser().resolve()
    if proj.is_file() and proj.name == "showtime.json":
        proj = proj.parent
    if not (proj / "showtime.json").is_file():
        raise ShowtimeError("no showtime.json in %s" % proj, hint="pass the project folder: showtime retime <project> -d 20")
    if getattr(args, "cuts", None):
        if args.from_voice:
            raise ShowtimeError("--cuts and --from-voice both set the scene lengths; give one of them")
        cuts = _parse_cuts(args.cuts)
        new, plan = cuts_plan(proj, cuts, args.duration)
        rep = retime_project(proj, new, dry_run=args.dry_run, plan=plan)
        return _retime_report(rep, proj, args)
    if (args.duration is None) == (args.from_voice is None):
        raise ShowtimeError("give either --duration S or --from-voice <timeline.json>",
                            hint="showtime retime %s -d 20   or   showtime retime %s --from-voice %s/voice/timeline.json"
                                 % (args.project, args.project, args.project))
    if (args.map or getattr(args, "total", None) is not None) and not args.from_voice:
        raise ShowtimeError("--map and --total only apply with --from-voice",
                            hint="for a plain length change use --duration")
    if args.from_voice:
        if not (0 <= args.pad <= 5):
            raise ShowtimeError("--pad must be between 0 and 5 seconds (got %g)" % args.pad)
        tl = Path(args.from_voice).expanduser()
        if not tl.is_absolute() and not tl.exists() and (proj / tl).exists():
            tl = proj / tl
        plan, new, voice = voice_plan(proj, tl, args.map, args.pad, args.keep_captions,
                                      total=getattr(args, "total", None))
        rep = retime_project(proj, new, dry_run=args.dry_run, plan=plan, voice=voice)
        rep["voice"] = {"timeline": voice["timeline"], "mapping": voice["mapping"], "how": voice["how"],
                        "pad": voice["pad"], "captions": voice["words_rel"]}
        rep["notes"] = voice["notes"] + rep["notes"]
    else:
        rep = retime_project(proj, float(args.duration), dry_run=args.dry_run)
    return _retime_report(rep, proj, args)


def _parse_cuts(spec: str) -> List[float]:
    try:
        return [float(x) for x in re.split(r"[,\s]+", str(spec).strip()) if x]
    except ValueError:
        raise ShowtimeError("--cuts takes seconds separated by commas (got %r)" % spec,
                            hint="showtime retime <project> --cuts 5.3,12.4,19.6,24.9")


def cuts_plan(proj: Path, cuts: List[float], total: Optional[float] = None) -> Any:
    """(new length, plan) that puts the scene changes of a project at `cuts`: one time per scene change
    (N-1 for N scenes), or N scene starts beginning with 0. Every scene keeps at least 0.5 s."""
    cfg_path, cfg, old = _project_cfg(proj)
    new = float(total) if total else old
    page = proj / str(cfg.get("page") or "index.html")
    if not page.is_file():
        raise ShowtimeError("--cuts needs an HTML page with scenes (%s is missing)" % page.name)
    scenes, _ = _split_tops(_Tags(page.read_text(encoding="utf-8")).resolve())
    n = len(scenes)
    starts = list(cuts)
    if len(starts) == n - 1:
        starts = [0.0] + starts
    if len(starts) != n or n == 0:
        raise ShowtimeError("%s has %d scene(s), so --cuts needs %d time(s) (got %d)" % (page.name, n, max(0, n - 1), len(cuts)),
                            why="each time is where one scene hands over to the next",
                            hint="scenes: %s" % ", ".join(_scene_names(scenes)))
    if abs(starts[0]) > 1e-6:
        raise ShowtimeError("the first scene must start at 0 (got %g)" % starts[0])
    ends = starts[1:] + [new]
    fps = float(cfg.get("fps") or 30)
    plan = []
    for i, (a, b) in enumerate(zip(starts, ends)):
        if b - a < 0.5:
            raise ShowtimeError("scene %d (%s) would last %.2fs; every scene needs at least 0.5 s" % (
                i + 1, _scene_names(scenes)[i] or "#%d" % (i + 1), b - a), hint="check the order of --cuts and the length")
        plan.append((_on_frame(a, fps), b if i == n - 1 else _on_frame(b, fps)))
    return new, plan


def _retime_report(rep: Dict[str, Any], proj: Path, args: argparse.Namespace) -> int:
    if args.json:
        print_json(rep)
        return 0
    head = "would retime" if args.dry_run else "retimed"
    log("%s %s: %gs -> %gs%s" % (head, proj, rep["from"], rep["to"],
                                 (" (from the voice, lines mapped %s)" % rep["voice"]["how"]) if rep.get("voice") else ""))
    for line in rep["changes"]:
        print("  " + line)
    for n in rep["notes"]:
        warn(n)
    if not args.dry_run:
        print("next: showtime check %s" % proj)
    return 0


def _aspect_notes(proj: Path, cfg: Dict[str, Any]) -> List[str]:
    """Canvas films are drawn in fixed design units: warn when the frame has another shape."""
    page = proj / "index.html"
    if not page.is_file():
        return []
    m = re.search(r"design\s*:\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]", page.read_text(encoding="utf-8", errors="replace"))
    if not m:
        return []
    dw, dh = int(m.group(1)), int(m.group(2))
    w, h = int(cfg.get("width") or dw), int(cfg.get("height") or dh)
    if abs((w / float(h)) - (dw / float(dh))) / (dw / float(dh)) <= 0.01:
        return []
    return ["this canvas template is drawn in %dx%d design units; a %dx%d frame shows it letterboxed. "
            "Change `design` in index.html and re-lay the scenes, or use the `short` template for vertical video"
            % (dw, dh, w, h)]


def _title_from(folder: str, template_title: Optional[str]) -> str:
    if template_title and not re.search(r"(?i)template|untitled", str(template_title)):
        return str(template_title)
    words = re.split(r"[-_\s]+", folder.strip())
    return " ".join(w.capitalize() for w in words if w) or "Untitled"


# ------------------------------------------------------------------ retime
#
# Moves a whole project to a new length: the page's scenes, the poster, the audio mix, caption word
# files and canvas cue tables. Stdlib only (`new` runs before the venv exists).

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
         "track", "wbr"}
_CLIP_TIME = re.compile(r"^\s*(?:(#[A-Za-z_][\w:.-]*)\s*(?:([+-])\s*(\d*\.?\d+))?|([+])?\s*(-?\d*\.?\d+)\s*s?)\s*$")
# component options that are times or durations (scaled only when the video gets shorter)
_INNER_TIMES = ("data-at", "data-dur", "data-exit-at", "data-exit-dur", "data-hold", "data-typing", "data-every",
                "data-first", "data-stagger", "data-reveal-dur", "data-diff-at", "data-diff-dur", "data-grow",
                "data-draw", "data-hide-after", "data-hide-caret-after", "data-hold-last",
                # typewriter / code-block: finish typing within this many seconds (ken-burns' data-fit
                # is a word, "cover"/"contain", and never matches the number test)
                "data-fit")
_NUM = r"-?\d+(?:\.\d+)?|-?\.\d+"


def _fmt(x: float) -> str:
    s = ("%.3f" % x).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _r(x: float) -> float:
    return float(_fmt(x))


def _on_frame(t: float, fps: float) -> float:
    """A time within 1 ms of a frame boundary is written at or just below that frame (3 decimals, rounded
    down): 53.434 for frame 53.4333 is a hair after the boundary, where older runtimes flashed the incoming
    scene for one frame. Other times are kept as they are (the stage puts them on the next frame)."""
    if t != t or t in (_INF,) or fps <= 0:
        return t
    n = round(t * fps)
    if abs(t - n / fps) > 0.001:
        return t
    return math.floor(n / fps * 1000.0 + 1e-6) / 1000.0


def _is_overlay(c: Dict[str, Any], sectioned: bool) -> bool:
    """A top-level clip that is not a scene: marked data-overlay, open-ended (no length: a persistent credit,
    a logo bug), or, on a page whose scenes are <section class="scene">, any other top-level clip."""
    a = c["attrs"]
    if "data-overlay" in a:
        return True
    if a.get("data-dur") in (None, "") and a.get("data-end") in (None, ""):
        return True
    if sectioned:
        return not (c["tag"] == "section" and "scene" in (a.get("class") or "").split())
    return False


def _split_tops(clips: List[Dict[str, Any]]) -> Any:
    """(scenes, overlays) among the top-level clips, in document order."""
    tops = [c for c in clips if c["parent"] is None]
    sectioned = any(c["tag"] == "section" and "scene" in (c["attrs"].get("class") or "").split() for c in tops)
    scenes = [c for c in tops if not _is_overlay(c, sectioned)]
    return scenes, [c for c in tops if _is_overlay(c, sectioned)]


class _Tags:
    """Start tags of an HTML document with their source offsets and clip nesting."""

    def __init__(self, text: str) -> None:
        from html.parser import HTMLParser
        starts = [0] + [m.end() for m in re.finditer("\n", text)]
        tags: List[Dict[str, Any]] = []
        stack: List[Any] = []   # (tag, clip record or None)

        outer = self

        class P(HTMLParser):
            def handle_starttag(self, tag: str, attrs: Any) -> None:  # noqa: D401
                outer._add(self, tag, attrs, tag in _VOID)

            def handle_startendtag(self, tag: str, attrs: Any) -> None:
                outer._add(self, tag, attrs, True)

            def handle_endtag(self, tag: str) -> None:
                for i in range(len(stack) - 1, -1, -1):
                    if stack[i][0] == tag:
                        del stack[i:]
                        break

        self.text, self.tags, self._stack, self._starts = text, tags, stack, starts
        p = P(convert_charrefs=True)
        p.feed(text)
        p.close()

    def _add(self, parser: Any, tag: str, attrs: Any, void: bool) -> None:
        raw = parser.get_starttag_text() or ""
        line, col = parser.getpos()
        start = self._starts[line - 1] + col
        a = {k: ("" if v is None else v) for k, v in attrs}
        parent = next((rec for _, rec in reversed(self._stack) if rec is not None), None)
        rec = {"tag": tag, "start": start, "end": start + len(raw), "raw": raw, "attrs": a,
               "clip": "data-start" in a, "parent": parent, "id": a.get("id", "")}
        self.tags.append(rec)
        if not void:
            self._stack.append((tag, rec if rec["clip"] else None))

    def resolve(self) -> List[Dict[str, Any]]:
        """Resolve every clip's start/end like the stage runtime does."""
        clips = [t for t in self.tags if t["clip"]]
        by_id = {c["id"]: c for c in clips if c["id"]}
        state: Dict[int, int] = {}

        def spec(c: Dict[str, Any], s: str, rel: float) -> float:
            m = _CLIP_TIME.match(s or "")
            if not m:
                return float("nan")
            if m.group(1):
                ref = by_id.get(m.group(1)[1:])
                if ref is None:
                    return float("nan")
                e = res(ref)["t1"]
                d = float(m.group(3)) if m.group(3) else 0.0
                return e - d if m.group(2) == "-" else e + d
            v = float(m.group(5))
            return rel + v if m.group(4) == "+" else v

        def res(c: Dict[str, Any]) -> Dict[str, Any]:
            k = id(c)
            if state.get(k) == 2:
                return c
            if state.get(k) == 1:
                c["t0"], c["t1"] = float("nan"), float("nan")
                return c
            state[k] = 1
            base = res(c["parent"])["t0"] if c["parent"] is not None else 0.0
            if base != base:
                base = 0.0
            c["t0"] = spec(c, c["attrs"].get("data-start", ""), base)
            dur, end = c["attrs"].get("data-dur"), c["attrs"].get("data-end")
            c["t1"] = float("inf")
            if dur not in (None, ""):
                try:
                    c["t1"] = c["t0"] + max(0.0, float(dur))
                except ValueError:
                    pass
            elif end not in (None, ""):
                c["t1"] = spec(c, end, c["t0"])
            state[k] = 2
            return c

        for c in clips:
            res(c)
        return clips


_INF = float("inf")


class _SceneMap:
    """Old -> new time, scene by scene.

    `pairs` = [((old_start, old_end), (new_start, new_end)), ...] for the top-level scenes. A time
    inside a scene keeps its offset from the scene start when the scene gets longer (animations run
    at the same speed, the scene holds longer) and is scaled with the scene when it gets shorter.
    Times outside every scene are interpolated between the scene boundaries.
    """

    def __init__(self, pairs: List[Any], old: float, new: float) -> None:
        self.pairs = [p for p in pairs if p[0][0] == p[0][0] and p[1][0] == p[1][0]]
        self.old, self.new = old, new
        pts: Dict[float, float] = {0.0: 0.0}
        for (os_, oe), (ns, ne) in self.pairs:
            pts.setdefault(os_, ns)
            if oe != _INF and ne != _INF:
                pts.setdefault(oe, ne)
        pts[old] = new
        self.pts = sorted(pts.items())

    def factor(self, i: int) -> float:
        (os_, oe), (ns, ne) = self.pairs[i]
        if oe == _INF or ne == _INF or oe - os_ <= 1e-9:
            return 1.0
        return min(1.0, (ne - ns) / (oe - os_))

    def scene_of(self, t: float) -> Optional[int]:
        best = None
        for i, ((os_, oe), _) in enumerate(self.pairs):
            if os_ <= t + 1e-9 and t < oe - 1e-9:
                best = i
        return best

    def _lerp(self, t: float) -> float:
        pts = self.pts
        if t <= pts[0][0]:
            return t
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if t <= x1 + 1e-12:
                return y0 if x1 - x0 <= 1e-12 else y0 + (t - x0) * (y1 - y0) / (x1 - x0)
        x0, y0 = pts[-1]
        return y0 + (t - x0) * (self.new / self.old if self.old > 0 else 1.0)

    def __call__(self, t: float) -> float:
        if abs(t - self.old) < 1e-6:
            return self.new
        i = self.scene_of(t)
        if i is None:
            return self._lerp(t)
        (os_, oe), (ns, ne) = self.pairs[i]
        v = ns + (t - os_) * self.factor(i)
        return min(v, ne) if ne != _INF else v


def _set_attr(raw: str, name: str, value: str) -> str:
    pat = re.compile(r"(\s%s\s*=\s*)(\"[^\"]*\"|'[^']*'|[^\s>]+)" % re.escape(name), re.I)
    m = pat.search(raw)
    if not m:
        return raw
    q = m.group(2)[0] if m.group(2)[:1] in "\"'" else '"'
    return raw[:m.start(2)] + q + value + q + raw[m.end(2):]


def _scale_spec(v: str, fn: Any) -> str:
    """Apply fn to the number in a clip time spec ("3.2", "+1", "#id+0.5")."""
    m = _CLIP_TIME.match(v or "")
    if not m:
        return v
    if m.group(1):
        if not m.group(3):
            return v
        return "%s%s%s" % (m.group(1), m.group(2), _fmt(fn(float(m.group(3)), True)))
    x = float(m.group(5))
    return ("+" if m.group(4) else "") + _fmt(fn(x, bool(m.group(4))))


def _scale_json_times(v: str, k: float, name: str = "") -> str:
    """Scale "at"/"t" values inside a JSON-ish attribute (every number in data-cues)."""
    if name == "data-cues" and re.match(r"^\s*\[\s*(?:%s)(?:\s*,\s*(?:%s))*\s*\]\s*$" % (_NUM, _NUM), v):
        return re.sub(_NUM, lambda m: _fmt(float(m.group(0)) * k), v)
    return re.sub(r"(\"(?:at|t)\"\s*:\s*)(%s)" % _NUM, lambda m: m.group(1) + _fmt(float(m.group(2)) * k), v)


def _add_attr(raw: str, name: str, value: str) -> str:
    """Set an attribute on a start tag, adding it when missing."""
    if re.search(r"\s%s\s*=" % re.escape(name), raw, re.I):
        return _set_attr(raw, name, value)
    m = re.search(r"\s*/?>\s*$", raw)
    at = m.start() if m else len(raw)
    return raw[:at] + ' %s="%s"' % (name, value) + raw[at:]


def _top_of(t: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The top-level scene a tag belongs to (itself for a scene), or None."""
    r = t if t["clip"] else t["parent"]
    while r is not None and r["parent"] is not None:
        r = r["parent"]
    return r


def _retime_html(text: str, old: float, new: float, plan: Optional[List[Any]] = None, fps: float = 30.0) -> Any:
    """Retime a page. Without `plan`, every scene scales by new/old. `plan` is a list of new
    (start, end) windows, one per top-level scene in document order (from `--from-voice`). Scene
    edges within 1 ms after a frame are written at that frame. Overlays (top-level clips that are not scenes: data-overlay,
    open-ended, or not a section.scene on a sectioned page) follow the scenes they sit over."""
    k = new / old
    doc = _Tags(text)
    clips = doc.resolve()
    scenes, overlays = _split_tops(clips)
    over_ids = {id(c) for c in overlays}
    if plan is None:
        targets = []
        for c in scenes:
            t0, t1 = c["t0"], c["t1"]
            ns = _on_frame(t0 * k, fps) if t0 == t0 else t0
            ne = t1 if t1 in (_INF,) or t1 != t1 else (new if abs(t1 - old) < 1e-3 else _on_frame(t1 * k, fps))
            targets.append((ns, ne))
    else:
        targets = list(plan)
    smap = _SceneMap([((c["t0"], c["t1"]), tg) for c, tg in zip(scenes, targets)], old, new)
    index = {id(c): i for i, c in enumerate(scenes)}
    edits: List[Any] = []
    for t in doc.tags:
        a, raw = t["attrs"], t["raw"]
        top = t["clip"] and t["parent"] is None
        inside = t["parent"] is not None
        sc = _top_of(t)
        kin = smap.factor(index[id(sc)]) if sc is not None and id(sc) in index else k
        if t["clip"] and top and id(t) in over_ids:
            # an overlay: its start and end follow the scenes they fall in (a credit across two scenes)
            sp = _CLIP_TIME.match(a.get("data-start") or "")
            if sp and not sp.group(1) and not sp.group(4) and t["t0"] == t["t0"]:
                n0 = _on_frame(smap(t["t0"]), fps)
                raw = _set_attr(raw, "data-start", _fmt(n0))
                if a.get("data-dur") not in (None, "") and t["t1"] not in (_INF,) and t["t1"] == t["t1"]:
                    try:
                        float(a["data-dur"])
                        raw = _set_attr(raw, "data-dur", _fmt(max(0.0, _on_frame(smap(t["t1"]), fps) - n0)))
                    except ValueError:
                        pass
                em = _CLIP_TIME.match(a.get("data-end") or "")
                if em and not em.group(1) and not em.group(4):
                    raw = _set_attr(raw, "data-end", _fmt(_on_frame(smap(float(em.group(5))), fps)))
        elif t["clip"]:
            if top:
                ns, ne = targets[index[id(t)]]
                sp = _CLIP_TIME.match(a["data-start"] or "")
                if sp and sp.group(1):
                    # "#previous+0.5": keep the chain; the gap scales with a uniform retime
                    if plan is None:
                        raw = _set_attr(raw, "data-start", _scale_spec(a["data-start"], lambda x, rel: x * k))
                elif sp and ns == ns:
                    raw = _set_attr(raw, "data-start", ("+" if sp.group(4) else "") + _fmt(ns))
                if a.get("data-end"):
                    em = _CLIP_TIME.match(a["data-end"])
                    if em and not em.group(1) and not em.group(4) and ne not in (_INF,) and ne == ne:
                        raw = _set_attr(raw, "data-end", _fmt(ne))
                    elif plan is None:
                        raw = _set_attr(raw, "data-end", _scale_spec(a["data-end"], lambda x, rel: x * k))
                if a.get("data-dur") not in (None, "") and ne != _INF and ne == ne and ns == ns:
                    try:
                        float(a["data-dur"])
                        raw = _set_attr(raw, "data-dur", _fmt(ne - ns))
                    except ValueError:
                        pass
            elif kin < 1:
                # nested clip in a shorter scene: relative times shrink with it, absolute ones follow it
                fn = (lambda x, rel, _k=kin: x * _k if rel else smap(x))
                raw = _set_attr(raw, "data-start", _scale_spec(a["data-start"], fn))
                if a.get("data-end"):
                    raw = _set_attr(raw, "data-end", _scale_spec(a["data-end"], fn))
                if a.get("data-dur") not in (None, ""):
                    try:
                        raw = _set_attr(raw, "data-dur", _fmt(float(a["data-dur"]) * kin))
                    except ValueError:
                        pass
            else:
                # nested clip in a longer scene: absolute times follow their scene, relative ones stay
                sp = _CLIP_TIME.match(a["data-start"] or "")
                if sp and not sp.group(1) and not sp.group(4):
                    raw = _set_attr(raw, "data-start", _fmt(smap(float(sp.group(5)))))
        if kin < 1 and (inside or t["clip"]):
            for name in _INNER_TIMES:
                if name == "data-dur" and t["clip"]:
                    continue
                if a.get(name) not in (None, "") and re.match(r"^\s*(%s)\s*$" % _NUM, a[name]):
                    raw = _set_attr(raw, name, _fmt(float(a[name]) * kin))
            for name, v in a.items():
                if name.startswith("data-") and v and v.lstrip()[:1] in "[{" and name != "data-st":
                    nv = _scale_json_times(v, kin, name)
                    if nv != v:
                        raw = _set_attr(raw, name, nv.replace('"', "&quot;") if _quote_of(t["raw"], name) == '"' else nv)
            tr = a.get("data-transition")
            if tr:
                m = re.search(r"(\s)(%s)\s*$" % _NUM, tr)
                if m:
                    x = float(m.group(2))     # a shorter handoff, but not a jump cut
                    raw = _set_attr(raw, "data-transition", tr[:m.start(2)] + _fmt(max(x * kin, min(x, 0.35))))
        elif not inside and not t["clip"] and a.get("data-at") not in (None, ""):
            # a component outside every clip: its start is absolute
            try:
                raw = _set_attr(raw, "data-at", _fmt(smap(float(a["data-at"]))))
            except ValueError:
                pass
        if raw != t["raw"]:
            edits.append((t["start"], t["end"], raw))
    out = text
    for s, e, raw in sorted(edits, reverse=True):
        out = out[:s] + raw + out[e:]
    # chained scenes ("#previous") resolve from rounded ends: make every scene end exactly on its target
    for _ in range(len(scenes) + 1):
        fscenes = _split_tops(_Tags(out).resolve())[0]
        if len(fscenes) != len(scenes):
            break
        edits = []
        for c, (ns, ne) in zip(fscenes, targets):
            if c["attrs"].get("data-dur") in (None, "") or c["t0"] != c["t0"] or ne in (_INF,) or ne != ne:
                continue
            want = _fmt(ne - c["t0"])
            if want != c["attrs"]["data-dur"]:
                edits.append((c["start"], c["end"], _set_attr(c["raw"], "data-dur", want)))
        if not edits:
            break
        for s, e, raw in sorted(edits, reverse=True):
            out = out[:s] + raw + out[e:]
    final = _split_tops(_Tags(out).resolve())[0]
    info = {"scenes": [{"name": c["id"] or c["attrs"].get("data-name") or c["tag"],
                        "from": [_r(o["t0"]), _r(o["t1"]) if o["t1"] != _INF else None],
                        "to": [_r(c["t0"]), _r(c["t1"]) if c["t1"] != _INF else None]}
                       for o, c in zip(scenes, final)] if len(final) == len(scenes) else []}
    words = [t["attrs"].get("data-src") for t in doc.tags
             if t["attrs"].get("data-st") in ("caption-karaoke", "captions") and t["attrs"].get("data-src")]
    return out, smap, info, words


def _quote_of(raw: str, name: str) -> str:
    m = re.search(r"\s%s\s*=\s*([\"'])" % re.escape(name), raw)
    return m.group(1) if m else '"'


def _fit_bpm(bpm: float, k: float) -> float:
    """A tempo that keeps cue times on the same bar lines after scaling by k, near the old tempo."""
    best = bpm
    score = None
    for n in (0.25, 0.5, 1, 2, 3, 4):
        b = bpm * n / k
        if 40 <= b <= 220:
            d = abs(math.log(b / bpm))
            if score is None or d < score - 1e-9:
                best, score = b, d
    return _r(best)


def _retime_cues(text: str, old: float, new: float) -> Any:
    """Scale the numbers in a `var CUE = { ... };` table. Returns (text, changes) or (None, [])."""
    m = re.search(r"\b(?:var|let|const)\s+CUE\s*=\s*\{", text)
    if not m:
        return None, []
    end = text.find("\n};", m.end())
    if end < 0:
        end = text.find("};", m.end())
    if end < 0:
        return None, []
    k = new / old
    body = text[m.end():end]
    changes: List[str] = []

    def sub(mm: Any) -> str:
        key, num = mm.group(2), float(mm.group(3))
        if key == "cps":
            return mm.group(0)
        if key == "duration":
            nv = new
        elif key == "bpm":
            nv = _fit_bpm(num, k)
        else:
            nv = num * k
        if abs(nv - num) > 1e-9:
            changes.append("%s %s -> %s" % (key, mm.group(3), _fmt(nv)))
        return mm.group(1) + _fmt(nv)

    body2 = re.sub(r"(^\s*([A-Za-z_]\w*)\s*:\s*)(%s)(?=\s*,|\s*$|\s*//)" % _NUM, sub, body, flags=re.M)
    if body2 == body:
        return None, []
    return text[:m.end()] + body2 + text[end:], changes


def _map_sections(v: Any, tmap: Any) -> Any:
    if isinstance(v, str):
        def one(tok: str) -> str:
            mm = re.match(r"^\s*(%s)\s*:\s*(.+?)\s*$" % _NUM, tok)
            if mm:
                return "%s:%s" % (_fmt(tmap(float(mm.group(1)))), mm.group(2))
            mm = re.match(r"^\s*(.+?)\s*[:@]\s*(%s)\s*$" % _NUM, tok)
            if mm:
                return "%s:%s" % (mm.group(1), _fmt(tmap(float(mm.group(2)))))
            return tok
        return ",".join(one(t) for t in v.split(","))
    if isinstance(v, list):
        out = []
        for it in v:
            if isinstance(it, dict):
                it = dict(it)
                for key in ("start", "end", "at", "t"):
                    if isinstance(it.get(key), (int, float)):
                        it[key] = _r(tmap(float(it[key])))
            out.append(it)
        return out
    if isinstance(v, dict):
        return {kk: (_r(tmap(float(vv))) if isinstance(vv, (int, float)) else vv) for kk, vv in v.items()}
    return v


def _retime_mix(spec: Dict[str, Any], tmap: Any, old: float, new: float) -> int:
    n = 0

    def length_to_end(d: Dict[str, Any], start: float) -> None:
        for key in ("dur", "duration"):
            if isinstance(d.get(key), (int, float)) and abs(start + float(d[key]) - old) < 0.05:
                d[key] = _r(new - tmap(start))

    if isinstance(spec.get("duration"), (int, float)):
        spec["duration"] = _r(new) if abs(float(spec["duration"]) - old) < 0.05 else _r(tmap(float(spec["duration"])))
        n += 1
    if spec.get("sections") is not None:
        spec["sections"] = _map_sections(spec["sections"], tmap)
        n += 1
    for tr in spec.get("tracks") or []:
        if not isinstance(tr, dict):
            continue
        start = float(tr.get("at", tr.get("start", 0)) or 0)
        for key in ("at", "start", "end"):
            if isinstance(tr.get(key), (int, float)):
                tr[key] = _r(tmap(float(tr[key])))
                n += 1
        length_to_end(tr, start)
        comp = tr.get("compose")
        if isinstance(comp, dict):
            if comp.get("sections") not in (None, "", "auto"):
                comp["sections"] = _map_sections(comp["sections"], tmap)
                n += 1
            length_to_end(comp, start)
    return n


def _fixed_music(spec: Dict[str, Any]) -> List[str]:
    """Music tracks read from a file that neither loops nor is fitted: they keep their own length."""
    out = []
    for tr in spec.get("tracks") or []:
        if isinstance(tr, str):
            out.append(tr)
        elif isinstance(tr, dict) and tr.get("kind", "music") == "music" and (tr.get("file") or tr.get("lib")) \
                and not (tr.get("loop") or tr.get("fit") or tr.get("compose")):
            out.append(str(tr.get("file") or tr.get("lib")))
    return out


def _dump_mix(spec: Dict[str, Any]) -> str:
    """JSON with one line per track (the layout the templates use)."""
    lines = []
    for key, v in spec.items():
        if key == "tracks" and isinstance(v, list):
            inner = ",\n".join("    " + json.dumps(t, ensure_ascii=False) for t in v)
            lines.append('  "tracks": [\n%s\n  ]' % inner)
        else:
            lines.append("  %s: %s" % (json.dumps(key), json.dumps(v, ensure_ascii=False)))
    return "{\n" + ",\n".join(lines) + "\n}\n"


# A scene held more than this many times its written length gets a warning: the extra time is a
# still hold after its last animation (check and qa flag holds of STILL_HOLD_S or more).
def _threshold(name: str, default: float) -> float:
    """A timing threshold shared with `check` and `qa` (runtime/thresholds.json)."""
    try:
        v = json.loads((Path(__file__).resolve().parents[2] / "runtime" / "thresholds.json").read_text(encoding="utf-8"))[name]
        return float(v)
    except (OSError, ValueError, KeyError, TypeError):
        return default


STRETCH_WARN = _threshold("stretch_warn", 1.5)
STILL_HOLD_S = _threshold("still_hold_s", 2.5)


def _project_cfg(proj: Path) -> Any:
    cfg_path = proj / "showtime.json"
    cfg = read_json(cfg_path, {}) or {}
    try:
        old = float(cfg.get("duration") or 0)
    except (TypeError, ValueError):
        old = 0.0
    if old <= 0:
        raise ShowtimeError("%s has no duration to scale from" % cfg_path,
                            hint='set "duration" to the length the scenes were written for, then retime')
    return cfg_path, cfg, old


def _stretch_notes(scenes: List[Dict[str, Any]]) -> List[str]:
    """Scenes that now hold much longer than they were written for (S11)."""
    long = []
    for sc in scenes:
        (a0, a1), (b0, b1) = sc["from"], sc["to"]
        if a1 is None or b1 is None or a1 - a0 <= 1e-6:
            continue
        ratio = (b1 - b0) / (a1 - a0)
        extra = (b1 - b0) - (a1 - a0)
        if ratio > STRETCH_WARN and extra >= 1.0:
            long.append("%s x%.1f (+%.1fs)" % (sc["name"], ratio, extra))
    if not long:
        return []
    return ["scenes stretched more than %gx hold still after their last animation: %s. Add beats to them "
            "(another chart state, a callout, a second line of text, the next command) or more scenes: a slow "
            "push-in alone still plays slow. `showtime check` flags still holds of %gs or more (dead_air) and "
            "scenes that hold on past their last change and reading time (slow_scene)" % (STRETCH_WARN, ", ".join(long), STILL_HOLD_S)]


def _rel(path: Path, proj: Path) -> str:
    try:
        return os.path.relpath(str(path), str(proj)).replace(os.sep, "/")
    except ValueError:          # another drive on Windows
        return path.resolve().as_posix()


def retime_project(proj: Path, new: float, dry_run: bool = False, plan: Optional[List[Any]] = None,
                   voice: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Move a project's whole timeline to `new` seconds. Returns a report.

    `plan` (new (start, end) per top-level scene) and `voice` come from `retime --from-voice`."""
    if not (0 < new <= 3600):
        raise ShowtimeError("duration must be between 0 and 3600 seconds (got %g)" % new)
    cfg_path, cfg, old = _project_cfg(proj)
    k = new / old
    rep: Dict[str, Any] = {"project": str(proj), "from": old, "to": new, "factor": round(k, 4),
                           "changes": [], "files": [], "notes": [], "dry_run": dry_run}
    writes: Dict[Path, str] = {}
    tmap: Any = _SceneMap([], old, new)
    page = proj / str(cfg.get("page") or "index.html")
    words_files: List[str] = []
    if page.is_file():
        html = page.read_text(encoding="utf-8")
        out, tmap, info, words_files = _retime_html(html, old, new, plan, fps=float(cfg.get("fps") or 30))
        if voice is not None:
            out = _voice_captions(out, voice, rep)
        if out != html:
            writes[page] = out
            sc = info["scenes"]
            rep["scenes"] = sc
            rep["changes"].append("%s: %d scene(s): %s" % (page.name, len(sc), ", ".join(
                "%s %s-%s" % (s["name"], _fmt(s["to"][0]), _fmt(s["to"][1]) if s["to"][1] is not None else "end")
                for s in sc)))
            rep["notes"] += _stretch_notes(sc)
    if plan is None:
        for js in sorted(proj.glob("*.js")):
            txt = js.read_text(encoding="utf-8")
            out, ch = _retime_cues(txt, old, new)
            if out is not None:
                writes[js] = out
                rep["changes"].append("%s: %s" % (js.name, "; ".join(ch)))
                if k > STRETCH_WARN and not rep.get("scenes"):
                    rep["notes"].append("the cue table in %s was stretched x%.1f: every move now runs that much slower. "
                                        "Add beats in the scenes (or shorten the target) if it drags; `showtime check` "
                                        "flags still holds of %gs or more" % (js.name, k, STILL_HOLD_S))
    if isinstance(cfg.get("poster"), (int, float)):
        p0 = float(cfg["poster"])
        p1 = min(_r(tmap(p0)), _r(new - 1.0 / float(cfg.get("fps") or 30)))
        cfg["poster"] = p1
        if abs(p1 - p0) > 1e-9:
            rep["changes"].append("poster %s -> %s" % (_fmt(p0), _fmt(p1)))
    cfg["duration"] = int(new) if float(new).is_integer() and isinstance(cfg.get("duration"), int) else new
    audio = cfg.get("audio")
    fixed: List[str] = []
    if voice is not None and not audio:
        audio = cfg["audio"] = "audio/mix.json"
        spec0 = {"_comment": "Created by `showtime retime --from-voice`: the voice lines on their scenes.",
                 "duration": old, "sample_rate": 48000, "tracks": [], "master": {"lufs": -14, "true_peak": -1}}
        writes[proj / audio] = _dump_mix(spec0)
        rep["changes"].append("showtime.json: audio -> %s (new mix with the voice)" % audio)
    if isinstance(audio, str) and audio.lower().endswith(".json") and ((proj / audio).is_file() or (proj / audio) in writes):
        mp = proj / audio
        try:
            spec = json.loads(writes[mp] if mp in writes else mp.read_text(encoding="utf-8-sig"))
        except ValueError as e:
            raise ShowtimeError("%s is not valid JSON: %s" % (mp, e))
        before = json.loads(json.dumps(spec))
        n = _retime_mix(spec, tmap, old, new)
        added = _voice_tracks(spec, voice, rep) if voice is not None else 0
        fixed = _fixed_music(spec)
        changed = _count_changes(before, spec)
        if changed:
            writes[mp] = _dump_mix(spec)
            rep["changes"].append("%s: %d value(s) changed%s" % (
                audio, changed, (" (%d voice track(s) placed)" % added) if added else " (music sections follow the scenes)"))
    elif isinstance(audio, (list, dict)):
        spec = {"tracks": audio} if isinstance(audio, list) else audio
        fixed = _fixed_music(spec)
        before = json.loads(json.dumps(spec))
        n = _retime_mix(spec, tmap, old, new)
        if voice is not None:
            n += _voice_tracks(spec, voice, rep)
        changed = _count_changes(before, spec)
        if changed:
            cfg["audio"] = spec["tracks"] if isinstance(audio, list) else spec
            rep["changes"].append("showtime.json audio: %d value(s) changed" % changed)
    elif voice is not None and isinstance(audio, str):
        rep["notes"].append("the soundtrack %s is a fixed file, so the voice lines were not added: use a mix.json "
                            "(`references/audio.md`) and run this again" % audio)
    if k > 1 and fixed:
        rep["notes"].append("music from a file keeps its own length (%s): add \"fit\": true (or \"loop\": true) "
                            "to the track so it reaches %gs" % (", ".join(fixed[:3]), new))
    if voice is not None:
        wp = proj / voice["words_rel"]
        writes[wp] = json.dumps(voice["words_doc"], indent=1, ensure_ascii=False) + "\n"
        rep["changes"].append("%s: %d caption word(s) at their video times" % (voice["words_rel"], len(voice["words_doc"]["words"])))
    for w in words_files:
        wp = (proj / w.lstrip("/")) if not w.startswith(("http:", "https:")) else None
        if not wp or not wp.is_file():
            continue
        if voice is not None and (not voice["keep_captions"] or _inside(wp, voice["timeline_dir"])):
            continue    # the caption layer now reads the voice words (or this is the voice module's own file)
        try:
            data = json.loads(wp.read_text(encoding="utf-8"))
        except ValueError:
            continue
        items = data.get("words") if isinstance(data, dict) else data
        if not isinstance(items, list):
            continue
        n = 0
        for it in items:
            if isinstance(it, dict):
                for key in ("start", "end"):
                    if isinstance(it.get(key), (int, float)):
                        it[key] = _r(tmap(float(it[key])))
                        n += 1
        if n:
            writes[wp] = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
            rep["changes"].append("%s: %d word time(s)" % (w, n))
    if isinstance(audio, str) and not audio.lower().endswith(".json") and voice is None:
        rep["notes"].append("the soundtrack %s is a fixed file: re-cut or re-fit it to %gs "
                            "(showtime audio fit, or a mix.json with \"fit\": true)" % (audio, new))
    rep["changes"].append("showtime.json: duration %s -> %s" % (_fmt(old), _fmt(new)))
    if k < 0.6 and plan is None:
        rep["notes"].append("the video is much shorter than the scenes were written for (x%.2f): "
                            "run `showtime check` and cut a scene if text no longer has time to be read" % k)
    rep["files"] = sorted(str(p) for p in list(writes) + [cfg_path])
    if not dry_run:
        for p, txt in writes.items():
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(str(p), "w", encoding="utf-8", newline="") as fh:   # keep LF line ends on Windows too
                fh.write(txt)
        write_json(cfg_path, cfg)
    return rep


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


# ------------------------------------------------------- retime --from-voice
#
# `voice script` writes timeline.json: one entry per line with its clip (lines/NN-id.wav) and its slot
# (from the line's start to the next line's start, so it includes the pause after it; the last slot
# includes the tail). Each narrated scene becomes pad + the slots of its lines; the lines are placed
# as separate voice tracks at scene start + pad, the music sections, sound effects and the poster move
# with their scenes, and the caption words are rewritten at their video times.

def _scene_names(scenes: List[Dict[str, Any]]) -> List[str]:
    return [c["id"] or c["attrs"].get("data-name") or "" for c in scenes]


def _parse_map(spec: str) -> Dict[str, str]:
    pth = Path(spec).expanduser()
    if pth.is_file():
        try:
            data = json.loads(pth.read_text(encoding="utf-8-sig"))
        except ValueError as e:
            raise ShowtimeError("%s is not valid JSON: %s" % (pth, e),
                                hint='write {"<line id>": "<scene id>", ...}')
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
        if isinstance(data, list):
            return {str(x[0]): str(x[1]) for x in data if isinstance(x, (list, tuple)) and len(x) == 2}
        raise ShowtimeError("%s must hold an object {\"<line id>\": \"<scene id>\"}" % pth)
    out: Dict[str, str] = {}
    for part in re.split(r"[,;]\s*", spec.strip()):
        if not part:
            continue
        m = re.match(r"^\s*([^=:]+?)\s*[=:]\s*(.+?)\s*$", part)
        if not m:
            raise ShowtimeError("cannot read --map entry %r" % part, hint="use line=scene pairs: --map hook=open,demo=bars")
        out[m.group(1)] = m.group(2)
    return out


def _map_lines(lines: List[Dict[str, Any]], names: List[str], spec: Optional[str]) -> Any:
    """Scene index for every line, and how it was decided."""
    ids = [str(ln.get("id", "")) for ln in lines]
    known = {n: i for i, n in enumerate(names) if n}

    def scene_ref(v: str) -> int:
        v = v.strip().lstrip("#")
        if v in known:
            return known[v]
        if v.isdigit() and 1 <= int(v) <= len(names):
            return int(v) - 1
        raise ShowtimeError("--map names scene %r, which the page does not have" % v,
                            hint="scenes (by id or number): %s" % ", ".join(
                                "%d=%s" % (i + 1, n or "?") for i, n in enumerate(names)))

    if spec:
        mp = _parse_map(spec)
        bad = [x for x in mp if x not in ids]
        if bad:
            raise ShowtimeError("--map names line(s) %s that the voice timeline does not have" % ", ".join(bad),
                                hint="lines: %s" % ", ".join(ids))
        if ids[0] not in mp:
            raise ShowtimeError("--map must place the first line (%s)" % ids[0],
                                hint="lines left out join the scene of the line before them")
        out, cur = [], 0
        for i in ids:
            if i in mp:
                cur = scene_ref(mp[i])
            out.append(cur)
        return out, "from --map (lines left out join the scene of the line before them)"
    if all(i in known for i in ids):
        return [known[i] for i in ids], "by id"
    if ids and ids[0] in known and any(i in known for i in ids[1:]):
        out, cur = [], known[ids[0]]
        joined = []
        for i in ids:
            if i in known:
                cur = known[i]
            else:
                joined.append(i)
            out.append(cur)
        return out, "by id (%s join the scene of the line before them)" % ", ".join(joined)
    if len(ids) <= len(names):
        return list(range(len(ids))), "by order"
    raise ShowtimeError("the voice has %d lines but the page has %d scenes, and the line ids (%s) match no scene id"
                        % (len(ids), len(names), ", ".join(ids[:6])),
                        hint="map them: --map %s (line=scene; several lines may share a scene), or a JSON file"
                             % ",".join("%s=%s" % (i, names[min(n, len(names) - 1)] or n + 1)
                                        for n, i in enumerate(ids[:3])))


def voice_plan(proj: Path, timeline: Path, mapping: Optional[str] = None, pad: float = 0.3,
               keep_captions: bool = False, total: Optional[float] = None) -> Any:
    """(plan, new length, voice context) for `retime --from-voice`. `total` keeps the video that long by
    growing or shrinking the last scene after the narration (the end card)."""
    cfg_path, cfg, old = _project_cfg(proj)
    page = proj / str(cfg.get("page") or "index.html")
    if not page.is_file():
        raise ShowtimeError("no %s in %s" % (page.name, proj))
    tl_path = timeline.expanduser().resolve()
    if tl_path.is_dir():
        tl_path = tl_path / "timeline.json"
    if not tl_path.is_file():
        raise ShowtimeError("voice timeline not found: %s" % tl_path,
                            hint="write it with `showtime voice script <script.md> -o <project>/voice` "
                                 "(it prints the timeline.json path)")
    try:
        tl = json.loads(tl_path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ShowtimeError("%s is not valid JSON: %s" % (tl_path, e))
    lines = tl.get("lines") if isinstance(tl, dict) else None
    if not lines or not all(isinstance(ln, dict) and isinstance(ln.get("slot"), dict) and ln.get("file")
                            for ln in lines):
        raise ShowtimeError("%s is not a voice timeline (no lines with slots)" % tl_path,
                            why="--from-voice reads the timeline.json that `showtime voice script` writes",
                            hint="showtime voice script <script.md> -o <project>/voice")
    doc = _Tags(page.read_text(encoding="utf-8"))
    scenes, overlays = _split_tops(doc.resolve())
    fps = float(cfg.get("fps") or 30)
    if not scenes:
        raise ShowtimeError("%s has no scenes (elements with data-start/data-dur)" % page.name,
                            why="canvas films keep their times in a cue table, not in scene clips",
                            hint="copy the line slots from %s into the cue table, or run "
                                 "`showtime retime <project> -d <voice length + 1>`" % tl_path.name)
    for c in scenes:
        if c["t0"] != c["t0"] or c["t1"] in (_INF,) or c["t1"] != c["t1"]:
            raise ShowtimeError("scene %s has no fixed start and length" % (c["id"] or c["tag"]),
                                hint="give every scene data-start and data-dur (an overlay over several scenes: "
                                     "mark it data-overlay)")
    names = _scene_names(scenes)
    assign, how = _map_lines(lines, names, mapping)
    if any(b < a for a, b in zip(assign, assign[1:])):
        raise ShowtimeError("the lines would run backwards through the scenes (%s)" % ", ".join(
            "%s->%s" % (ln["id"], names[s] or s + 1) for ln, s in zip(lines, assign)),
                            hint="keep the script in scene order, or fix --map")
    first, last = assign[0], assign[-1]
    mute = [names[i] or str(i + 1) for i in range(first, last + 1) if i not in set(assign)]
    if mute:
        raise ShowtimeError("scene(s) %s sit between narrated scenes but get no line" % ", ".join(mute),
                            hint="give them a line with --map (line=scene), or move them after the narration")
    order = sorted(range(len(scenes)), key=lambda i: (scenes[i]["t0"], i))
    if order != list(range(len(scenes))):
        raise ShowtimeError("the scenes are not in time order in the page",
                            hint="list the <section> scenes in the order they play")
    by_scene: Dict[int, List[Dict[str, Any]]] = {}
    for ln, sidx in zip(lines, assign):
        by_scene.setdefault(sidx, []).append(ln)
    plan: List[Any] = []
    placed: List[Any] = []
    notes: List[str] = []
    cursor = 0.0
    for i, c in enumerate(scenes):
        if i in by_scene:
            ns = cursor
            lc = ns + pad
            for ln in by_scene[i]:
                placed.append((ln, _r(lc)))
                lc += float(ln["slot"].get("duration") or (float(ln["slot"]["end"]) - float(ln["slot"]["start"])))
            ne = _r(lc)
        else:
            ns, ne = cursor, _r(cursor + (c["t1"] - c["t0"]))
        ns, ne = _on_frame(ns, fps), _on_frame(ne, fps)
        plan.append((ns, ne))
        if ne - ns < 1.0:
            notes.append("scene %s is only %.2fs long" % (names[i] or i + 1, ne - ns))
        cursor = ne
    new = _r(cursor)
    if total is not None:
        last_i = len(plan) - 1
        ns, ne = plan[last_i]
        ne2 = _on_frame(ne + (float(total) - new), fps)
        if last_i in by_scene:
            # every scene is narrated (a narrated close): the last scene holds after its last line,
            # longer or shorter, but never cuts into the speech
            ln, at = [(x, a) for x, a in placed if x is by_scene[last_i][-1]][0]
            speech_end = _on_frame(at + float(ln.get("duration") or ln["slot"].get("duration") or 0), fps)
            if ne2 < speech_end - 1e-6:
                raise ShowtimeError("--total %g would cut the last line: the narration ends at %.2fs" % (total, speech_end),
                                    why="every scene is narrated, so only the pause after the last line can change",
                                    hint="use --total %g or more, shorten the script (voice script --fit), or add an "
                                         "end card after the narration" % (math.ceil(speech_end * 10) / 10.0))
            if ne2 > ne + 1e-6:
                notes.append("every scene is narrated: the last scene (%s) holds %.2fs after its last line to fit --total %g"
                             % (names[last_i] or last_i + 1, ne2 - speech_end, total))
        else:
            if ne2 - ns < 1.0:
                raise ShowtimeError("--total %g leaves the end card %.2fs long (the narration takes %.2fs)" % (
                    total, ne2 - ns, ns), hint="shorten the script (voice script --fit), or raise --total")
            if ne2 - ns < 2.5:
                notes.append("the end card is only %.2fs long to fit --total %g (2.5 s or more reads as a hold)" % (ne2 - ns, total))
        plan[last_i] = (ns, ne2)
        new = _r(float(total))
    tl_dir = tl_path.parent
    tracks = []
    for ln, at in placed:
        tracks.append({"id": "vo-%s" % ln["id"], "kind": "voice", "file": _rel(tl_dir / ln["file"], proj), "start": at})
    words = []
    for ln, at in placed:
        base = float(ln.get("start", ln["slot"]["start"]))
        for w in ln.get("words") or []:
            try:
                words.append({"text": w["text"], "start": _r(float(w["start"]) - base + at),
                              "end": _r(float(w["end"]) - base + at), "type": "word", "line": ln["id"]})
            except (KeyError, TypeError, ValueError):
                continue
    words_rel = "voice/captions.words.json"
    if _rel(tl_dir, proj).startswith("../") or os.path.isabs(_rel(tl_dir, proj)):
        notes.append("the voice clips live outside the project (%s): copy that folder into the project to keep "
                     "it self-contained" % tl_dir)
    ctx = {"timeline": str(tl_path), "timeline_dir": tl_dir, "tracks": tracks, "vo_file": _rel(tl_dir / str(tl.get("file") or "vo.wav"), proj),
           "lines_dir": _rel(tl_dir / "lines", proj), "words_rel": words_rel, "keep_captions": keep_captions,
           "words_doc": {"source": portable_path(tl_path, proj / "voice"),
                         "note": "written by `showtime retime --from-voice`: word times in the video",
                         "words": words},
           "mapping": [{"line": ln["id"], "scene": names[s] or s + 1, "at": at} for (ln, at), s in zip(placed, assign)],
           "how": how, "pad": pad, "notes": notes}
    return plan, new, ctx


def _count_changes(a: Any, b: Any) -> int:
    """How many leaf values differ between two JSON trees (added/removed entries count once)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return sum(_count_changes(a.get(k), b.get(k)) if (k in a and k in b) else 1 for k in set(a) | set(b))
    if isinstance(a, list) and isinstance(b, list):
        n = sum(_count_changes(x, y) for x, y in zip(a, b))
        return n + abs(len(a) - len(b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return 0 if abs(float(a) - float(b)) < 1e-9 else 1
    return 0 if a == b else 1


def _voice_tracks(spec: Dict[str, Any], voice: Dict[str, Any], rep: Dict[str, Any]) -> int:
    """Replace the voice's tracks in a mix spec with one track per line at its new time."""
    tracks = spec.setdefault("tracks", [])
    lines_dir = voice["lines_dir"].rstrip("/") + "/"

    def ours(tr: Any) -> bool:
        if not isinstance(tr, dict) or tr.get("kind", "") != "voice":
            return False
        f = str(tr.get("file") or "").replace("\\", "/")
        return f == voice["vo_file"] or f.startswith(lines_dir) or str(tr.get("id", "")).startswith("vo-")
    old = [t for t in tracks if ours(t)]
    gain = next((t.get("gain_db") for t in old if isinstance(t.get("gain_db"), (int, float))), None)
    new_tracks = [dict(t, **({"gain_db": gain} if gain is not None else {})) for t in voice["tracks"]]
    pos = next((i for i, t in enumerate(tracks) if ours(t)), len(tracks))
    kept = [t for t in tracks if not ours(t)]
    pos = min(pos, len(kept))
    spec["tracks"] = kept[:pos] + new_tracks + kept[pos:]
    others = [t for t in kept if isinstance(t, dict) and t.get("kind") == "voice"]
    if others:
        rep["notes"].append("the mix has other voice tracks (%s); they were moved with the scenes, not replaced"
                            % ", ".join(str(t.get("file") or t.get("id")) for t in others[:3]))
    ducked = 0
    for t in kept:
        # every music source of a mix (audio/mix.py); synth, keystrokes and typewriter are effects
        if isinstance(t, dict) and t.get("kind", "music") == "music" and "duck" not in t and \
                any(t.get(k) for k in ("file", "lib", "catalog", "compose")):
            t["duck"] = {"under": "voice"}
            ducked += 1
    rep["changes"].append("voice: %d line(s) placed on their scenes (%s)%s" % (
        len(new_tracks), ", ".join("%s@%s" % (m["line"], _fmt(m["at"])) for m in voice["mapping"]),
        "; music ducks under the voice" if ducked else ""))
    return len(new_tracks) + ducked


def _voice_captions(html: str, voice: Dict[str, Any], rep: Dict[str, Any]) -> str:
    """Point top-level caption layers at the rewritten caption words (unless --keep-captions)."""
    doc = _Tags(html)
    caps = [t for t in doc.tags if t["attrs"].get("data-st") in ("caption-karaoke", "captions")]
    if not caps:
        rep["notes"].append("no caption layer: for burned captions add "
                            '<div data-st="caption-karaoke" data-src="%s"></div> after the scenes' % voice["words_rel"])
        return html
    if voice["keep_captions"]:
        return html
    edits = []
    for t in caps:
        if t["parent"] is not None:
            rep["notes"].append("the caption layer inside scene %s was left alone; point it at %s with "
                                "data-at set to minus the scene start, or move it after the scenes"
                                % (_top_of(t)["id"] or "?", voice["words_rel"]))
            continue
        raw = _add_attr(_add_attr(t["raw"], "data-src", voice["words_rel"]), "data-at", "0")
        if raw != t["raw"]:
            edits.append((t["start"], t["end"], raw))
            rep["changes"].append("captions read %s (was %s)" % (voice["words_rel"], t["attrs"].get("data-src") or "inline words"))
    for s, e, raw in sorted(edits, reverse=True):
        html = html[:s] + raw + html[e:]
    return html

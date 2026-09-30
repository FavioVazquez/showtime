"""`showtime manim ...`: math and diagram animation with Manim Community (ManimGL optional).

Nothing here imports manim: renders and checks run the scene kit (`st_manim`) in the showtime venv
as a subprocess, so `--help`, `new`, `cues` and the static checks work without the extra.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .common import ShowtimeError, log, paths, print_json, warn

COMMANDS = {
    "manim": "Math and diagram animation with Manim: showtime manim new|render|check|cues",
}

_F = argparse.RawDescriptionHelpFormatter
TEMPLATES = ("example", "equation", "graph", "plane", "refine", "blank")


def _say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def register(sub: argparse._SubParsersAction) -> None:
    m = sub.add_parser("manim", help=COMMANDS["manim"], formatter_class=_F, description=(
        "Exact math and diagram animation (equations, proofs, graphs, grid transforms) with Manim Community\n"
        "and showtime's scene kit `st_manim` (brand theme, colour-coded equations, narration beats).\n\n"
        "  new     a project folder from a template (manim.json, scenes.py, narration.md)\n"
        "  render  scenes -> one video: draft (480p15 + contact sheet) or final (1080p30), 16:9/9:16/1:1,\n"
        "          --alpha for overlays, voice on the same clock, cached per scene\n"
        "  check   static checks + a dry run + qa's black/frozen detectors on a draft: cue words, still holds,\n"
        "          word budgets, colours, LaTeX, words and math on one line (baseline, x-height, mixed_line)\n"
        "  cues    the narration's lines and numbered words (what beat()/at()/fit() accept)\n\n"
        "Guide: references/manim.md. ManimGL scene files (`from manimlib import *`) render with the optional\n"
        "engine: showtime setup --with manimgl."),
        epilog="Examples:\n"
               "  showtime manim new my-math\n"
               "  showtime voice script my-math/narration.md -o my-math/voice/\n"
               "  showtime manim check my-math\n"
               "  showtime manim render my-math                     # draft + contact sheet\n"
               "  showtime manim render my-math --quality final -o final.mp4\n"
               "  showtime manim render my-math --aspect 9:16 --quality final\n"
               "  showtime manim render overlay.py --scene Formula --alpha -o formula.webm")
    s = m.add_subparsers(dest="manim_cmd", metavar="<subcommand>")

    p = s.add_parser("new", help="create a Manim project from a template", formatter_class=_F,
                     description="Copy a template into <dir>: manim.json, scenes.py and narration.md (the example's\n"
                                 "narration, or a one-line stub to replace). The title defaults to the folder name (the\n"
                                 "job's name for <job>/manim).\n"
                                 "Templates: example (a narrated 25 s explainer), equation, graph, plane, refine, blank.",
                     epilog="Examples:\n  showtime manim new my-math\n  showtime manim new proof --template equation "
                            "--aspect 9:16 --title \"Why it balances\"")
    p.add_argument("dir")
    p.add_argument("--template", "-t", default="example", choices=TEMPLATES)
    p.add_argument("--aspect", choices=("16:9", "9:16", "1:1", "4:5"))
    p.add_argument("--title")
    p.add_argument("--force", action="store_true", help="copy into a folder that is not empty")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_new)

    p = s.add_parser("render", help="render scenes to one video (draft or final, any aspect, alpha)", formatter_class=_F,
                     description="Render a scene file or a project folder. Scenes are cached per scene (their code, the\n"
                                 "cues they use, theme, size): only changed scenes render again. Draft = 480p15 plus a\n"
                                 "contact sheet of each scene's last frame; final = 1080p30 (manim.json fps) plus\n"
                                 "poster.jpg. The voice (voice/timeline.json) is muxed on the same clock; a mix spec\n"
                                 "adds music and effects through `showtime audio mix`.",
                     epilog="Examples:\n  showtime manim render my-math\n"
                            "  showtime manim render my-math --quality final --aspect 9:16 -o short.mp4\n"
                            "  showtime manim render scenes.py --scene Proof --alpha -o proof.webm   (VP9 alpha)\n"
                            "  showtime manim render my-math --alpha prores -o proof.mov             (for editors)\n"
                            "  showtime manim render my-math --cues voice/timeline.json --mix audio/mix.json")
    p.add_argument("target", help="scene .py file or project folder")
    p.add_argument("--scene", action="append", help="render only this scene (repeatable; default: all, in order)")
    p.add_argument("--quality", "-q", choices=("draft", "final"), default="draft")
    p.add_argument("--aspect", choices=("16:9", "9:16", "1:1", "4:5"), help="override manim.json (frame units follow)")
    p.add_argument("--alpha", nargs="?", const="webm", choices=("webm", "prores"),
                   help="transparent background: webm (VP9 alpha, default) or prores (ProRes 4444 .mov)")
    p.add_argument("--fps", type=float, help="frame rate (default: 15 draft, manim.json fps or 30 final)")
    p.add_argument("--size", type=_size, metavar="WxH",
                   help="exact pixel size, e.g. 1280x720 for a page layer (the frame's short side stays 8 units)")
    p.add_argument("--cues", help="voice timeline.json (or narration.md for estimated timing)")
    p.add_argument("--mix", help="audio mix spec (music, effects) mixed under the voice")
    p.add_argument("--brand", help="brand.json to theme from (default: found from the project folder)")
    p.add_argument("--engine", choices=("ce", "gl"), help="force the engine (default: from the file's imports)")
    p.add_argument("--no-audio", action="store_true")
    p.add_argument("--fresh", action="store_true", help="ignore every cache")
    p.add_argument("--sheet", action="store_true", help="also write the contact sheet for a final render")
    p.add_argument("-o", "--output")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_render)

    p = s.add_parser("check", help="static checks + a dry run of every scene", formatter_class=_F,
                     description="Finds what makes a math explainer read badly before you render: cue words the\n"
                                 "narration never says (and line ids that are also spoken words), reveals that land\n"
                                 "late, still holds on qa's thresholds (WARN from 2.5 s, ERROR from 6 s mid-video; a\n"
                                 "thin line or a small label moving does not count as change, as in qa),\n"
                                 "too many words on screen, one concept in two colours, words and math (or a number)\n"
                                 "side by side on different baselines or at different x-heights, LaTeX missing (with\n"
                                 "the FIX line for this OS). It then renders the draft (the one `render` reuses) and runs\n"
                                 "qa's black and frozen-frame detectors on it: a near-black ground with sparse content and\n"
                                 "a small Indicate on an equation are flagged here as qa flags them, with a fix\n"
                                 "(--no-draft skips it). Exit code 1 on errors (--strict: on warnings too).",
                     epilog="Examples:\n  showtime manim check my-math\n  showtime manim check my-math --aspect 9:16"
                            "   (the portrait layout: safe area, holds)\n  showtime manim check scenes.py --json")
    p.add_argument("target")
    p.add_argument("--scene", action="append")
    p.add_argument("--aspect", choices=("16:9", "9:16", "1:1", "4:5"),
                   help="check the layout at this aspect (default: manim.json), as render --aspect draws it")
    p.add_argument("--cues")
    p.add_argument("--brand")
    p.add_argument("--static", action="store_true", help="skip the dry run (no manim needed)")
    p.add_argument("--no-draft", action="store_true",
                   help="skip the draft render that runs qa's black and frozen-frame detectors")
    p.add_argument("--strict", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_check)

    p = s.add_parser("cues", help="list the narration lines and numbered words", formatter_class=_F,
                     description="Print each narration line (the ids beat() takes) with its slot and its words\n"
                                 "numbered by occurrence (what at()/fit(until=) take). Reads voice/timeline.json,\n"
                                 "else estimates from narration.md.",
                     epilog="Examples:\n  showtime manim cues my-math\n  showtime manim cues my-math --json")
    p.add_argument("target", help="project folder, timeline.json or narration.md")
    p.add_argument("--fps", type=float, default=30)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_cues)


def _size(text: str) -> Any:
    import re
    m = re.match(r"^\s*(\d+)\s*[xX*,]\s*(\d+)\s*$", text or "")
    if not m:
        raise argparse.ArgumentTypeError("use WIDTHxHEIGHT, e.g. 1280x720")
    return int(m.group(1)), int(m.group(2))


# ------------------------------------------------------------------ new

NARRATION_STUB = """<!-- One `## id` heading per narration line: the id is the beat name the scenes use
     (self.beat("intro")), the words are what at()/fit(until=) cue on. Until the voice exists,
     check and draft renders estimate the timing from this file.
     Voice it with: showtime voice script narration.md -o voice/ -->

## intro
Replace this line with the first sentence of the narration.
"""

GENERIC_DIRS = {"manim", "project", "scenes", "src", "math"}


def _default_title(dst: Path) -> str:
    """The project's name: its folder, or the job's slug for <job>/manim (a folder named "manim" says nothing)."""
    if dst.name.lower() not in GENERIC_DIRS:
        return dst.name
    import re
    m = re.match(r"^(?P<slug>.+?)-\d{8}-\d{6}(?:-\d+)?$", dst.parent.name)
    return (m.group("slug") if m else dst.parent.name) or dst.name

def cmd_new(args: argparse.Namespace) -> int:
    root = paths()["templates"] / "manim"
    if not root.is_dir():
        raise ShowtimeError("the manim templates are missing (%s)" % root, hint="reinstall showtime")
    dst = Path(args.dir).expanduser().resolve()
    if dst.exists() and any(dst.iterdir()) and not args.force:
        raise ShowtimeError("%s is not empty" % dst, why="showtime never overwrites earlier work by default",
                            hint="choose a new folder or pass --force")
    dst.mkdir(parents=True, exist_ok=True)
    if args.template == "example":
        shutil.copytree(str(root / "example"), str(dst), dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", ".DS_Store", "build", "out", "voice"))
    else:
        shutil.copyfile(str(root / "patterns" / (args.template + ".py")), str(dst / "scenes.py"))
        cfg = json.loads((root / "example" / "manim.json").read_text(encoding="utf-8"))
        for k in ("colors", "mix", "scenes"):
            cfg.pop(k, None)
        (dst / "manim.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        if not (dst / "narration.md").exists():
            (dst / "narration.md").write_text(NARRATION_STUB, encoding="utf-8")
    cfgp = dst / "manim.json"
    cfg = json.loads(cfgp.read_text(encoding="utf-8"))
    if args.title:
        cfg["title"] = args.title
    elif args.template != "example":
        cfg["title"] = _default_title(dst)
    if args.aspect:
        cfg["aspect"] = args.aspect
    cfgp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    from .manim_run.render import manim_installed
    files = sorted(str(p.relative_to(dst)) for p in dst.rglob("*") if p.is_file())
    info = {"ok": True, "dir": str(dst), "template": args.template, "files": files,
            "manim_installed": manim_installed(), "guide": str(paths()["skill"] / "references" / "manim.md")}
    if args.json:
        print_json(info)
        return 0
    print("created %s (%s): %s" % (dst, args.template, ", ".join(files)))
    if (dst / "narration.md").is_file():
        print("next: showtime voice script %s -o %s" % (dst / "narration.md", dst / "voice"))
    print("then: showtime manim check %s   and   showtime manim render %s" % (dst, dst))
    if not info["manim_installed"]:
        print("note: Manim installs itself before the first render (about 60 MB, 1-3 min; "
              "now: showtime setup --fetch manim)")
    return 0


# ------------------------------------------------------------------ render

def cmd_render(args: argparse.Namespace) -> int:
    from .manim_run.render import render
    res = render(Path(args.target), scenes=args.scene, quality=args.quality, aspect=args.aspect, alpha=args.alpha,
                 fps=args.fps, cues_arg=args.cues, out=args.output, brand=args.brand, fresh=args.fresh,
                 no_audio=args.no_audio, mix=args.mix, engine=args.engine, sheet=True if args.sheet else None,
                 size=args.size)
    if args.json:
        print_json(res)
        return 0
    cached = sum(1 for s in res["scenes"] if s.get("cached"))
    print("%s  %dx%d %gfps %s, %.1f s, %d scene(s)%s, %.1f s to render" % (
        res["output"], res["size"][0], res["size"][1], res["fps"], res.get("aspect", ""), res.get("duration", 0),
        len(res["scenes"]), (" (%d cached)" % cached) if cached else "", res["seconds"]))
    if res.get("sheet"):
        print("contact sheet: %s" % res["sheet"])
    if res.get("poster"):
        print("poster: %s" % res["poster"])
    if res.get("audio_note"):
        print("audio: %s" % res["audio_note"])
    for lc in res.get("late_cues") or []:
        warn("%s: %s lands %.2f s late" % (lc["scene"], lc.get("why"), lc.get("by", 0)))
    if res.get("alpha") == "webm":
        print("VP9 alpha plays in Chrome, Edge and Firefox, not Safari: bake it into the final MP4 "
              "(showtime render of the page) before sharing an HTML export")
    _card(res, args)
    return 0


def _card(res: Dict[str, Any], args: argparse.Namespace) -> None:
    """Terminals only: what was made and the next step (a draft: the final; a final: qa)."""
    from . import delight
    from .common import human_size
    out = Path(res["output"])
    try:
        size = human_size(out.stat().st_size)
    except OSError:
        size = None
    if args.quality == "draft":
        nxt = "showtime manim render %s --quality final" % delight.shell_path(args.target)
    else:
        nxt = "showtime qa %s" % delight.shell_path(out)
    delight.show_card("%s is ready" % out.name, out, [delight.fmt_len(res.get("duration")),
                      "%dx%d" % tuple(res["size"][:2]), size], nxt, delight.qa_verdict(out))


# ------------------------------------------------------------------ check

def cmd_check(args: argparse.Namespace) -> int:
    from .manim_run.check import check
    res = check(Path(args.target), scenes=args.scene, cues_arg=args.cues, brand=args.brand, dry_run=not args.static,
                aspect=args.aspect, draft=not args.no_draft)
    if args.json:
        print_json(res)
    else:
        for it in res["findings"]:
            where = (" [%s]" % it["scene"]) if it.get("scene") else ""
            print("%-5s %-16s%s %s" % (it["level"], it["code"], where, it["message"]))
            if it.get("fix") and it["level"] != "INFO":
                print("      fix: %s" % it["fix"])
        for s in res["scenes"]:
            print("scene %-20s %6.2f s" % (s["name"], s["seconds"]))
        print("manim check: %d error(s), %d warning(s)" % (res["errors"], res["warnings"]))
    if res["errors"] or (args.strict and res["warnings"]):
        return 1
    return 0


# ------------------------------------------------------------------ cues

def cmd_cues(args: argparse.Namespace) -> int:
    from .manim_run import cues as cm
    t = Path(args.target).expanduser()
    if t.is_dir():
        from .manim_run.project import Project
        pr = Project(t)
        c = cm.load(None, pr.dir, pr.cfg.get("voice", "voice/timeline.json"), pr.cfg.get("narration", "narration.md"),
                    args.fps)
        if c is None:
            raise ShowtimeError("no narration in %s: no voice timeline, and no narration.md with lines" % t,
                                why="a film without narration has no cues: its scenes run on their own timing",
                                hint="for a narrated film, write narration.md with one `## <beat>` heading per line")
    else:
        c = cm.load(str(t), t.parent, None, None, args.fps)
    assert c is not None
    if args.json:
        print_json(c)
    else:
        print("\n".join(cm.describe(c)))
    return 0

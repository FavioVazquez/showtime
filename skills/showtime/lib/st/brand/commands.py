"""Handlers for `showtime brand capture | apply | skip` (registered in st/cli_job.py with the other brand commands)."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from ..common import ShowtimeError, log, output_dir, print_json, slugify, warn, write_json

RAW = argparse.RawDescriptionHelpFormatter


def register(bs) -> None:
    """Add capture / apply / skip to the `brand` sub-parsers."""
    q = bs.add_parser("capture", help="brand first: capture the brand + real UI of a repo or URL into <job>/brand/",
                      formatter_class=RAW, description=(
                          "One command before a launch (or any product) storyboard: the palette with roles, fonts, logo, the\n"
                          "wordmark as the site sets it, the product's code-block look, its own copy (tagline, headline, CTAs,\n"
                          "install line, README commands, features, the latest CHANGELOG release) and its real UI: the site\n"
                          "folder in the repo (site/, docs/, public/, dist/ ... with an index.html) served and captured, a\n"
                          "running dev server (--url), or, for a command-line tool, the README commands to run as evidence.\n"
                          "Writes brand.json + brand.md (+ capture/) and records the kit in the job; `showtime new launch`\n"
                          "then applies it. Nothing in the repo is executed."),
                      epilog=("examples:\n"
                              "  showtime brand capture . --job my-launch              # repo + its site folder -> <job>/brand/\n"
                              "  showtime brand capture https://acme.dev --job my-launch\n"
                              "  showtime brand capture . --url http://localhost:5173 --job my-launch   # the running app\n"
                              "  showtime brand capture ~/code/tool -o ./brand --no-site"))
    q.add_argument("source", nargs="?", default=".", help="repository folder or http(s) URL (default: this folder)")
    q.add_argument("--job", "-j", help="the job (folder or name): writes <job>/brand/ and records it in job.json")
    q.add_argument("-o", "--out", help="output folder (default <job>/brand, else showtime-out/brand-<name>-<time>/)")
    q.add_argument("--url", help="with a repo: capture this running app (dev server) as the real UI")
    q.add_argument("--serve", help="with a repo: serve and capture this folder instead of the detected site folder")
    q.add_argument("--aspect", default="16:9,1:1,9:16", help="screens to capture (default 16:9,1:1,9:16)")
    q.add_argument("--no-site", action="store_true", help="with a repo: do not capture a site folder")
    q.add_argument("--no-font-lookup", action="store_true", help="do not look fonts up in the Fontsource catalog")
    q.add_argument("--force", action="store_true", help="replace an existing brand.json in the output folder")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_capture)

    q = bs.add_parser("apply", help="apply the brand kit to a project (tokens, fonts, SLOT copy on the end card)",
                      formatter_class=RAW,
                      epilog=("examples:\n  showtime brand apply my-job/project           # finds my-job/brand/brand.json\n"
                              "  showtime brand apply my-video --brand ../brand/brand.json --no-fill"))
    q.add_argument("project", help="project folder (index.html)")
    q.add_argument("--brand", help="brand.json or its folder (default: searched from the project up)")
    q.add_argument("--no-fill", action="store_true", help="only the look: leave SLOT text alone")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_apply)

    q = bs.add_parser("skip", help="record why a job has no brand kit (check and the ledger show it)",
                      formatter_class=RAW,
                      epilog=("examples:\n  showtime brand skip my-launch --why \"the user asked for our house style, not the product's\"\n"
                              "  showtime brand skip my-launch --why \"no repo or site given; plain theme\""))
    q.add_argument("job", nargs="?", help="job folder or name (default: the newest job)")
    q.add_argument("--why", required=True, help="the reason, one line")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_skip)


def _job(arg: Optional[str]) -> Path:
    from ..job import ledger
    return ledger.resolve(arg)


def cmd_capture(args: argparse.Namespace) -> int:
    from . import capture as cap
    from . import draft, warnings_for
    from ..job import ledger
    job: Optional[Path] = _job(args.job) if args.job else None
    if job is None and not args.out:
        job = ledger.enclosing_job(Path.cwd())
    src = str(args.source)
    if args.out:
        out = Path(args.out).expanduser().resolve()
    elif job is not None:
        out = job / "brand"
    else:
        name = slugify(Path(src).expanduser().resolve().name if "://" not in src else src.split("://", 1)[1].split("/")[0])
        out = output_dir("brand-%s" % name, create=False)
    bj = out / "brand.json"
    if bj.exists() and not args.force:
        raise ShowtimeError("%s already exists" % bj, hint="pass --force to capture again, or -o another folder")
    out.mkdir(parents=True, exist_ok=True)
    say = (lambda m: None) if args.json else log
    kit = cap.capture(src, out, serve=args.serve, url=args.url, aspects=args.aspect, site=not args.no_site,
                      lookup_fonts=not args.no_font_lookup, say=say)
    stored = draft.relativize(kit, out)
    write_json(bj, stored)
    kit["_file"] = str(bj)
    md = out / "brand.md"
    md.write_text(cap.storyboard_md(kit, draft.brand_md(kit, bj.name)), encoding="utf-8", newline="\n")
    summary = cap.summary_line(kit)
    if job is None:
        job = ledger.enclosing_job(out)
    if job is not None:
        cap.record_in_job(job, {"kit": str(bj), "source": src, "summary": summary})
    warns = warnings_for(kit)
    if args.json:
        print_json({"brand": str(bj), "notes_md": str(md), "job": str(job) if job else None, "summary": summary,
                    "real_ui": kit.get("real_ui"), "capture": kit.get("capture"), "notes": kit.get("notes"),
                    "warnings": warns, "kit": stored})
        return 0
    log("brand kit for %s: %s" % (kit.get("name"), summary))
    copy = kit.get("copy") or {}
    if copy.get("install"):
        log("  install line (verbatim): %s" % copy["install"]["command"])
    if (kit.get("capture") or {}).get("contact_sheet"):
        log("  screens: %s" % kit["capture"]["contact_sheet"])
    for n in kit.get("notes") or []:
        warn(n)
    for w in warns:
        if "no logo" in w and kit.get("wordmark"):
            continue
        warn(w)
    if job is not None:
        log("recorded in %s; `showtime new launch %s/project` applies it" % (job / "job.json", job))
    print(str(bj))
    print(str(md))
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    import os
    from . import load
    from .apply import apply_project
    proj = Path(args.project).expanduser().resolve()
    if not (proj / "index.html").is_file():
        raise ShowtimeError("%s has no index.html" % proj, hint="brand apply works on page projects (showtime new ...)")
    if args.brand:
        os.environ["SHOWTIME_BRAND"] = str(Path(args.brand).expanduser().resolve())
    kit = load(proj)
    if kit is None:
        raise ShowtimeError("no brand kit found for %s" % proj,
                            hint="capture one: showtime brand capture <repo|url> --job <job> (or pass --brand)")
    res = apply_project(proj, kit, fill=not args.no_fill)
    if args.json:
        print_json(res)
        return 0
    report(res)
    return 0


def report(res) -> None:
    t = res["tokens"]
    log("brand %s applied to %s: ground %s, ink %s, accent %s, window %s on %s" % (
        res.get("name"), res["project"], t.get("--bg"), t.get("--fg"), t.get("--accent"), t.get("--win-fg"), t.get("--win-bg")))
    for f in res.get("filled") or []:
        log("  filled " + f)
    for n in res.get("notes") or []:
        warn(n)


def cmd_skip(args: argparse.Namespace) -> int:
    from .capture import record_in_job
    job = _job(args.job)
    why = " ".join(str(args.why).split())
    if len(why) < 4:
        raise ShowtimeError("say why in a few words", hint='--why "the user asked for a plain look"')
    record_in_job(job, {"none": why})
    if args.json:
        print_json({"job": str(job), "brand": {"none": why}})
    else:
        log("recorded in %s: no brand kit (%s)" % (job / "job.json", why))
    return 0

"""Evidence and bookkeeping commands: qa, review-pack, job, status, clean, brand, report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

from .common import ShowtimeError, human_size, is_terminal, log, print_json, warn

COMMANDS = {
    "qa": "Check a finished video: file, loudness, black/frozen/silent, captions, credits -> PASS/WARN/FAIL",
    "review-pack": "Build a critic packet for a render: contact sheets, key frames, loudness graph, CRITIC.md",
    "review-verdict": "Decide a pairwise review round: the new render wins only if preferred in both orders",
    "job": "Job ledger: showtime job init|note|discard|list|show (job.json + SHOWTIME.md)",
    "status": "Where the latest (or given) job stands, in three lines",
    "clean": "Remove intermediates showtime created in a job or project (frames, scratch); asks first",
    "brand": "Brand kit: showtime brand capture|init|apply|show|css|skip (brand.json + brand.md)",
    "report": "Write a local, redacted bug-report.md (never uploads anything)",
}

RAW = argparse.RawDescriptionHelpFormatter
LEAN_SKIPS_SHORT = "lean skips the critic round unless publish-bound or asked, one look per stage"
MODE_HELP = (
    "Create a job folder (showtime-out/<slug>-<timestamp>/) with job.json and SHOWTIME.md, and check setup.\n\n"
    "Modes (--mode, two independent choices):\n"
    "  quick (default) | studio   how much to ask before building (studio: concept, look and storyboard boards)\n"
    "  quality (default) | lean   how much reviewing the finished video gets:\n"
    "      quality  the full review on every finished video: looks, qa and a look after the final render, and a\n"
    "               critic round (showtime review-pack + a critic sub-agent) before delivery; qa and deliver say\n"
    "               \"review pending\" until that round has a verdict\n"
    "      lean     a cheaper draft pass: one look per stage and no critic round unless the video is publish-bound\n"
    "               or the user asks. check, qa and the looks still run.\n"
    "The review mode is recorded in job.json and SHOWTIME.md. Default for new jobs: SHOWTIME_MODE, else\n"
    "`showtime config mode lean|quality`, else quality. Switch a job later: showtime job note <job> --mode lean")


def _mode_arg(value: str) -> List[str]:
    """--mode values: quick/studio and/or lean/quality, comma-joined or repeated."""
    out = []
    for v in str(value).split(","):
        v = v.strip().lower()
        if not v:
            continue
        if v not in ("quick", "studio", "lean", "quality"):
            raise argparse.ArgumentTypeError("unknown mode %r (use quick or studio, and lean or quality)" % v)
        out.append(v)
    return out


def _split_modes(values) -> "tuple":
    """(quick|studio or None, lean|quality or None) from the --mode values; the last of each kind wins."""
    flow = review = None
    for group in values or []:
        for v in group:
            if v in ("quick", "studio"):
                flow = v
            else:
                review = v
    return flow, review


def register(sub: argparse._SubParsersAction) -> None:
    # ------------------------------------------------------------------ qa
    p = sub.add_parser("qa", help=COMMANDS["qa"], formatter_class=RAW, description=(
        "Check the finished file (not the project, not a preview) and print PASS/WARN/FAIL findings,\n"
        "each with a timestamp, the frame at that time and a fix. Exit code 1 on FAIL.\n\n"
        "Checks: codec/pix_fmt/fps/even size, faststart, BT.709 tags, duration vs the project,\n"
        "audio present, integrated loudness and true peak vs the platform target, clipping,\n"
        "leading/inner/trailing silence, black and frozen stretches, frame 0 not black,\n"
        "the phone check (one line: type size in points at phone width, reading time and platform UI zones\n"
        "from the project's last `showtime check`, caption line length and speed from the sidecars),\n"
        "caption sidecars (timing, line length, safe placement: the video's own <stem>.srt/.vtt/.ass, and\n"
        "for a job's latest render also the job's latest captions of the same aspect, e.g. final.srt for a\n"
        "baked final.poster.mp4; --captions FILE checks exactly that file instead), resolution below the\n"
        "platform's size (540x960 for reels WARNs), footage enlarged more than 1.5x by an edit (from its\n"
        "render report), credits when CC-BY material was used, and the optional \"expect\" block in\n"
        "showtime.json:\n"
        '  "expect": {"duration": 15, "tolerance": 0.5, "platform": "reels", "lufs": -14,\n'
        '             "captions": true, "audio": true, "must_show": ["Acme", {"text": "v2", "at": 3}],\n'
        '             "max_size_mb": 50}\n'
        "Writes qa.json, frames/ and sheet.jpg to <job>/work/qa/<video>/ (or <video>.qa/).\n\n"
        "Which file: pass the video, or a job folder or job name to check that job's LATEST render\n"
        "(job.json \"outputs\": the newest final, else the newest preview; a re-render writes final-2.mp4\n"
        "and qa follows it). With no argument: the job the current folder is in, else the newest job.\n"
        "It prints \"using <path> (latest final)\" so you can see which file was checked.\n\n"
        "Platform: name the destination whenever there is one. It sets the length cap, aspect and\n"
        "loudness target (reels/tiktok/shorts: 9:16, <= 180/600/180 s, -14 LUFS; youtube: 16:9;\n"
        "broadcast: -23 LUFS; web: no audio, small file). Without --platform, qa uses the expect block's\n"
        "\"platform\", then showtime.json \"platform\", then the job's (showtime job init|note --platform);\n"
        "with none of them it runs generic checks only (no length/aspect limits, -14 LUFS)."),
        epilog=("examples:\n"
                "  showtime qa                                   # latest render of the current/newest job\n"
                "  showtime qa launch-teaser --platform reels    # a job by name: its latest final\n"
                "  showtime qa showtime-out/launch-20260926-101500/final-2.mp4\n"
                "  showtime qa final.mp4 --project my-video --platform reels\n"
                "  showtime qa final.mp4 --expect expect.json --json"))
    p.add_argument("video", nargs="?", help="video file, or a job folder/name (its latest final, else preview); "
                                            "default: the current or newest job")
    p.add_argument("--project", help="project folder (default: found from render.json or next to the video)")
    p.add_argument("--expect", help="JSON file with an expect block (default: showtime.json \"expect\")")
    p.add_argument("--platform", help="where it will be posted: youtube, x, linkedin, reels, tiktok, shorts, square, web, "
                                      "github, chat, broadcast (default: expect/showtime.json/job.json platform, else none)")
    p.add_argument("--lufs", type=float, help="loudness target (default: the platform's, else -14)")
    p.add_argument("--captions", action="append", default=[], metavar="FILE",
                   help="caption sidecar to check (repeatable); replaces the ones qa would find itself")
    p.add_argument("-o", "--out", help="folder for qa.json, frames and the sheet")
    p.add_argument("--no-sheet", action="store_true", help="skip the contact sheet")
    p.add_argument("--sheet-count", type=int, help="frames on the contact sheet (default: one per second, 6-36)")
    p.add_argument("--strict", action="store_true", help="exit 1 on WARN too")
    p.add_argument("--json", action="store_true", help="print the full report as JSON")
    p.add_argument("-v", "--verbose", action="store_true", help="show every note")
    p.set_defaults(func=cmd_qa)

    # ------------------------------------------------------------ review-pack
    p = sub.add_parser("review-pack", help=COMMANDS["review-pack"], formatter_class=RAW, description=(
        "Make a folder a critic (a fresh sub-agent or a person) can judge without the session:\n"
        "sheet.jpg (1 frame/s), scenes.jpg (every scene middle and each cut at -0.1s/mid/+0.2s),\n"
        "frames/ (frame 0, hook, poster, last frame, scene frames), loudness.png, qa/ (a fresh qa run),\n"
        "thumb-168x94.png, context/ (brief, storyboard, SHOWTIME.md, showtime.json, check.json, mix report)\n"
        "and CRITIC.md (the brief: the eight judging questions, severity scale, citation rule, answer\n"
        "format, 3-round limit).\n"
        "Scene boundaries come from the project (showtime.json scenes/chapters, a film's CUE.acts, the\n"
        "scene clips: data-start <section>/.scene elements, else top-level clips that are not overlays,\n"
        "voice/timeline.json) or the edit's EDL report; only without either are cuts detected in pixels.\n"
        "Rounds: <job>/review/round-N/. A round counts once the critic's FINDINGS.md is saved in it; until\n"
        "then the next run rebuilds the same round (a newer final, an interrupted pack). Three critic rounds.\n"
        "Also: cuts.jpg (every frame from 2 before to 4 after each cut), frames/text-*.png (the largest text\n"
        "lines cut from full-size frames, for the critic's type detail pass), and the video's .srt/.vtt sidecars.\n"
        "A job folder or name packs that job's LATEST render (job.json \"outputs\"; final, else preview).\n\n"
        "--against OLD makes a blind pairwise round instead: the latest render and OLD (a video file, round-N,\n"
        "or best) as X and Y at random, the same moments of both, both cut strips, loudness plots, qa and a\n"
        "narration transcript each, and two briefs (order-1/CRITIC.md: X first, order-2/CRITIC.md: Y first)\n"
        "for two fresh critics. The key (which is which) stays in <review>/.pairwise-keys/; then run\n"
        "showtime review-verdict."),
        epilog=("examples:\n"
                "  showtime review-pack                                   # latest render of the current/newest job\n"
                "  showtime review-pack showtime-out/launch-20260926-101500\n"
                "  showtime review-pack final-2.mp4 --project my-video --platform reels\n"
                "  showtime review-pack my-job --against best             # pairwise: latest final vs the best so far"))
    p.add_argument("target", nargs="?", help="video file, or a job folder/name (default: the current or newest job)")
    p.add_argument("--project", help="project folder (default: found from render.json)")
    p.add_argument("--expect", help="JSON file with an expect block")
    p.add_argument("--platform", help="target preset for the qa run (default: the last showtime qa --platform of "
                                      "this file, else as for showtime qa)")
    p.add_argument("--lufs", type=float, help="loudness target for the qa run (default: the last showtime qa --lufs of "
                                             "this file, else the platform's)")
    p.add_argument("-o", "--out", help="review root (default <job>/review)")
    p.add_argument("--every", type=float, help="contact sheet spacing in seconds (default 1)")
    p.add_argument("--force-round", action="store_true",
                   help="always start a new round, also past the 3-round limit or when the last round has no FINDINGS.md")
    p.add_argument("--against", metavar="OLD",
                   help="pairwise round: judge the render against OLD (a video file, round-N, or best) in both orders")
    p.add_argument("--json", action="store_true", help="print the manifest as JSON")
    p.set_defaults(func=cmd_review_pack)

    p = sub.add_parser("review-verdict", help=COMMANDS["review-verdict"], formatter_class=RAW, description=(
        "Read both orders' FINDINGS.md of a pairwise round (review-pack --against) and apply the rule: the new\n"
        "render is an improvement only when the critic preferred it in both orders; a tie or a split keeps the\n"
        "older one. Writes VERDICT.md and verdict.json in the round, <review>/best.json (the best version so far\n"
        "and its open findings), and says what to do next; after the last round (3): ship the best version with\n"
        "its open findings listed."),
        epilog=("examples:\n"
                "  showtime review-verdict                        # latest pairwise round of the current/newest job\n"
                "  showtime review-verdict showtime-out/my-job/review/round-2"))
    p.add_argument("target", nargs="?", help="round folder, review folder, or a job folder/name (default: current job)")
    p.add_argument("--round", type=int, help="round number (default: the latest pairwise round)")
    p.add_argument("--json", action="store_true", help="print the verdict as JSON")
    p.set_defaults(func=cmd_review_verdict)

    # ------------------------------------------------------------------ job
    j = sub.add_parser("job", help=COMMANDS["job"], formatter_class=RAW, description=(
        "One folder per job: showtime-out/<slug>-<timestamp>/ with job.json (machine ledger) and\n"
        "SHOWTIME.md (Goal / Where we are / Verified vs Assumed / Open questions / Next command / Pointers).\n"
        "Update it at every stage boundary; a resumed session reads SHOWTIME.md first."),
        epilog=("examples:\n"
                "  showtime job init launch-teaser --goal \"15s teaser for v2, 9:16 + 16:9\"\n"
                "  showtime job note --stage storyboard --verified \"user approved storyboard v2\"\n"
                "  showtime job note --assumed \"music bed CC0 from the catalog\" --question \"Logo on dark or light?\"\n"
                "  showtime job note --answer 1:dark --next \"showtime render my-video --preview\"\n"
                "  showtime job list"))
    js = j.add_subparsers(dest="job_cmd", metavar="<subcommand>")
    q = js.add_parser("init", help="create a job folder with job.json and SHOWTIME.md", formatter_class=RAW,
                      description=MODE_HELP,
                      epilog="examples:\n  showtime job init launch-teaser --goal \"15 s teaser for v2, 9:16 and 16:9\"\n"
                             "  showtime job init pricing-explainer --mode studio --project videos/pricing\n"
                             "  showtime job init quick-draft --mode lean      # a cheaper draft pass (no critic round)\n"
                             "  showtime job init teaser --mode studio,lean")
    q.add_argument("slug", help="short name, e.g. launch-teaser")
    q.add_argument("--mode", action="append", default=[], type=_mode_arg, metavar="MODE",
                   help="quick (default) or studio; quality (default: the full review on every finished video) or "
                        "lean (%s). Repeat or comma-join to set both, e.g. studio,lean. Without it the review mode "
                        "comes from SHOWTIME_MODE, then `showtime config mode`" % LEAN_SKIPS_SHORT)
    q.add_argument("--goal", help="the one-sentence request (formats, length)")
    q.add_argument("--request", help="the user's request exactly as typed (the receipt quotes it); without --goal it also becomes the goal")
    q.add_argument("--project", help="project folder this job renders")
    q.add_argument("--platform", help="main destination (reels, youtube, ...): showtime qa checks against it by default")
    q.add_argument("--base", help="where showtime-out/ lives (default: $SHOWTIME_OUT or the current folder)")
    q.add_argument("--assumed", action="append", default=[], help="an assumption made for the user (repeatable)")
    q.add_argument("--question", action="append", default=[], help="an open question for the user (repeatable)")
    q.add_argument("--next", dest="next_cmd", help="the next command to run")
    q.add_argument("--no-check", action="store_true",
                   help="skip the quick setup check (by default job init runs `showtime doctor --quick`, reused for an hour)")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_job_init)
    q = js.add_parser("note", help="record a stage boundary: verified/assumed/questions/next/pointers", formatter_class=RAW,
                      epilog="examples:\n  showtime job note --stage render --status started\n"
                             "  showtime job note --stage render --verified \"final.mp4 1080p, qa PASS\" --next \"showtime deliver exports ...\"\n"
                             "  showtime job note launch-teaser --answer 1:both --pointer brief=studio/brief.md\n"
                             "  showtime job note launch-teaser --output animatic=studio/media/animatic/a1.mp4")
    q.add_argument("job", nargs="?", help="job folder or slug (default: latest)")
    q.add_argument("--stage", help="stage name: brief, look, storyboard, animatic, build, render, qa, deliver, ...")
    q.add_argument("--status", choices=["started", "done", "failed", "skipped"], help="stage status (default done)")
    q.add_argument("--seconds", type=float, help="stage duration (default: since --status started)")
    q.add_argument("--verified", action="append", default=[], help="something actually checked (repeatable)")
    q.add_argument("--assumed", action="append", default=[], help="something assumed, not checked (repeatable)")
    q.add_argument("--question", action="append", default=[], help="an open question (repeatable)")
    q.add_argument("--answer", action="append", default=[], metavar="N:TEXT", help="answer open question N (repeatable)")
    q.add_argument("--next", dest="next_cmd", help="the next command ('' clears it)")
    q.add_argument("--pointer", action="append", default=[], metavar="NAME=PATH", help="file pointer (repeatable)")
    q.add_argument("--warning", action="append", default=[], help="a warning to keep (repeatable)")
    q.add_argument("--output", action="append", default=[], metavar="[KIND=]PATH",
                   help="a produced file (repeatable); KIND (final, preview, edl, poster, share, credits, captions, "
                        "animatic, report) makes it that kind's latest file, and is inferred from the name when left "
                        "out; a video under <job>/studio/ is always the animatic, never the final/preview; report "
                        "(.html/.htm/.pdf) is a document deliverable and never becomes the final/preview video")
    q.add_argument("--platform", help="main destination (reels, youtube, ...); '' clears it")
    q.add_argument("--project", help="the project folder this job renders (pointers.project); also set by "
                                     "render --job and found automatically in <job>/<folder>/showtime.json")
    q.add_argument("--goal", help="set or replace the goal")
    q.add_argument("--request", help="set or replace the user's request exactly as typed (the receipt quotes it)")
    q.add_argument("--render", metavar="KIND=FILE", help="record a render for the receipt: full=final.mp4, "
                   "preview=preview.mp4 or partial=final.mp4 (a span re-rendered); render and edit render do it themselves")
    q.add_argument("--render-span", metavar="FROM-TO", help="with --render partial=...: the seconds re-rendered, e.g. 2.5-8")
    q.add_argument("--render-base", metavar="FILE", help="with --render partial=... --render-span: the full render the span "
                                                         "was spliced into (the partial render is then a full final)")
    q.add_argument("--mode", action="append", default=[], type=_mode_arg, metavar="MODE",
                   help="switch mode: quick or studio, and/or the review mode quality or lean (%s)" % LEAN_SKIPS_SHORT)
    q.add_argument("--cache-hit", type=int, default=0, help="cache hits to add")
    q.add_argument("--cache-miss", type=int, default=0, help="cache misses to add")
    q.add_argument("--event", help="free-form history line")
    q.add_argument("--auto", action="store_true",
                   help="the --output files come from a tool (render, edit, captions): a variant video (an alpha "
                        ".webm/.mov, or an .mp4 not named final*/preview*) is logged but does not become the latest")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_job_note)
    q = js.add_parser("discard", help="take an unused render out of the job (moved to work/discarded/, never deleted)",
                      formatter_class=RAW, description=(
                          "Moves the file, its .work/ folder, poster and credits to <job>/work/discarded/ and points\n"
                          "the job's latest final/preview/poster back at the newest remaining file, so qa, review-pack\n"
                          "and deliver never pick the discarded render. Caption files (final.srt, .vtt, .ass) stay in\n"
                          "the job (they belong to the cut, not to one render); name one to discard it too."),
                      epilog="examples:\n  showtime job discard launch-teaser final-4.mp4\n"
                             "  showtime job discard showtime-out/launch-20260926-101500 final-4.mp4 --json")
    q.add_argument("job", help="job folder or slug")
    q.add_argument("file", help="the render to discard (a path inside the job, or its name)")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_job_discard)
    q = js.add_parser("list", help="jobs under showtime-out/, newest first", formatter_class=RAW,
                      epilog="examples:\n  showtime job list\n  showtime job list --base ~/videos --json")
    q.add_argument("--base", help="folder containing showtime-out/")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_job_list)
    q = js.add_parser("show", help="print SHOWTIME.md of a job", formatter_class=RAW,
                      epilog="examples:\n  showtime job show\n  showtime job show launch-teaser --json")
    q.add_argument("job", nargs="?", help="job folder or slug (default: latest)")
    q.add_argument("--json", action="store_true", help="print job.json instead")
    q.set_defaults(func=cmd_job_show)
    j.set_defaults(func=lambda a: _group_help(j))

    # ------------------------------------------------------------------ status
    p = sub.add_parser("status", help=COMMANDS["status"], formatter_class=RAW, description=(
        "Three lines: which job and stage, what is verified/assumed/open, and the next command.\n"
        "Without an argument: the newest job under ./showtime-out (or $SHOWTIME_OUT).\n\n"
        "Background runs: any command takes --background (it starts detached and prints a run id at once);\n"
        "`showtime status <run-id>` then says whether it still runs, its latest progress line, and at the\n"
        "end its exit code and last lines of output. --wait S watches it for up to S seconds (a line every\n"
        "30 s) and exits with the command's own code, or 75 if it is still running."),
        epilog="examples:\n  showtime status\n  showtime status launch-teaser\n  showtime status --json\n"
               "  showtime render my-video --background\n  showtime status render-20260928-141500-a1b2 --wait 240\n"
               "  showtime status --runs")
    p.add_argument("job", nargs="?", help="job folder, a file in it, a slug, or a background run id")
    p.add_argument("--json", action="store_true")
    p.add_argument("--runs", action="store_true", help="list the background runs")
    p.add_argument("--wait", type=float, metavar="S", help="background run: watch it for up to S seconds")
    p.add_argument("--cancel", action="store_true", help="background run: stop it")
    p.set_defaults(func=cmd_status)

    # ------------------------------------------------------------------ clean
    p = sub.add_parser("clean", help=COMMANDS["clean"], formatter_class=RAW, description=(
        "Remove intermediates that showtime wrote, and nothing else. Shows the size first and asks you to\n"
        "type the folder name (or pass --yes).\n"
        "  --frames   only frame dumps (work/frames)\n"
        "  (default)  frames + check/snap/qa scratch, audio intermediates, diagnostics, and in a Manim\n"
        "             project (manim.json, e.g. <job>/manim/) its build/ scene cache and out/*-draft* renders\n"
        "  --all      also review packs and logs\n"
        "Never touched: final/preview videos, poster, exports/, credits, share text, job.json, render.json,\n"
        "SHOWTIME.md, studio/, and any file showtime did not create."),
        epilog="examples:\n  showtime clean --dry-run\n  showtime clean showtime-out/launch-20260926-101500 --frames\n  showtime clean my-video --yes")
    p.add_argument("target", nargs="?", help="job folder, slug, project or Manim project folder (default: latest job)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--frames", action="store_true", help="only frame dumps")
    g.add_argument("--all", action="store_true", help="also review packs and logs")
    p.add_argument("-y", "--yes", action="store_true", help="do not ask")
    p.add_argument("-n", "--dry-run", action="store_true", help="only show what would be removed")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_clean)

    # ------------------------------------------------------------------ brand
    b = sub.add_parser("brand", help=COMMANDS["brand"], formatter_class=RAW, description=(
        "An optional brand kit (brand.json + brand.md): logo, colours with roles, fonts, voice,\n"
        "pronunciations, formats, tone words. Workflows use it as defaults when it exists."),
        epilog=("examples:\n"
                "  showtime brand capture . --job my-launch     # brand first: repo + its site/app screens + copy -> <job>/brand/\n"
                "  showtime brand init --from .                 # from this repo (CSS vars, tailwind, package.json, README)\n"
                "  showtime brand init --url https://example.com  # from a site (reuses a site capture if present)\n"
                "  showtime brand show\n"
                "  showtime brand css > brand.css"))
    bs = b.add_subparsers(dest="brand_cmd", metavar="<subcommand>")
    q = bs.add_parser("init", help="draft brand.json + brand.md from a repo or a website", formatter_class=RAW,
                      epilog="examples:\n  showtime brand init --from .\n  showtime brand init --url https://example.com -o brand/brand.json\n"
                             "  showtime brand init --site-json showtime-out/example-com-site-20260926-101500/site.json")
    src = q.add_mutually_exclusive_group()
    src.add_argument("--from", dest="from_dir", help="repository folder (default: current folder)")
    src.add_argument("--url", help="website URL (uses an existing site capture, or runs one)")
    src.add_argument("--site-json", help="a site.json from `showtime site capture`")
    q.add_argument("-o", "--output", default="brand.json", help="output file (default ./brand.json)")
    q.add_argument("--capture-dir", help="where to put a new site capture (default showtime-out/brand-capture-<ts>)")
    q.add_argument("--no-capture", action="store_true", help="with --url: never run a capture, only reuse one")
    q.add_argument("--no-font-lookup", action="store_true", help="do not look fonts up in the Fontsource catalog")
    q.add_argument("--force", action="store_true", help="overwrite an existing brand.json")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_brand_init)
    q = bs.add_parser("show", help="print the brand kit that applies here", formatter_class=RAW,
                      epilog="examples:\n  showtime brand show\n  showtime brand show brand/brand.json --json")
    q.add_argument("path", nargs="?", help="brand.json or a folder (default: search from the current folder)")
    q.add_argument("--json", action="store_true")
    q.set_defaults(func=cmd_brand_show)
    q = bs.add_parser("css", help="print the palette and fonts as CSS variables", formatter_class=RAW,
                      epilog="examples:\n  showtime brand css\n  showtime brand css -o my-video/brand.css")
    q.add_argument("path", nargs="?", help="brand.json or a folder")
    q.add_argument("-o", "--output", help="write to a file instead of stdout")
    q.set_defaults(func=cmd_brand_css)
    from .brand import commands as brand_first   # brand capture | apply | skip (brand first for launches)
    brand_first.register(bs)
    b.set_defaults(func=lambda a: _group_help(b))

    # ------------------------------------------------------------------ report
    p = sub.add_parser("report", help=COMMANDS["report"], formatter_class=RAW, description=(
        "Assemble bug-report.md: environment, a quick doctor run, the job ledger, check/qa verdicts and\n"
        "the tail of logs with errors. Home paths, user names, e-mails and anything that looks like a\n"
        "secret are redacted (and re-scanned until clean). Nothing is uploaded: read it, then share it\n"
        "yourself if you want to."),
        epilog="examples:\n  showtime report\n  showtime report showtime-out/launch-20260926-101500 --problem \"audio drifts after 10s\"")
    p.add_argument("job", nargs="?", help="job folder or slug (default: latest job, if any)")
    p.add_argument("-o", "--output", help="output file (default <job>/bug-report.md)")
    p.add_argument("--problem", default="", help="what you expected and what happened")
    p.add_argument("--no-doctor", action="store_true", help="skip the quick doctor run")
    p.add_argument("--doctor-json", metavar="FILE", help="use this `showtime doctor --json` result instead of running it")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_report)


def _group_help(parser: argparse.ArgumentParser) -> int:
    parser.print_help()
    return 2


# ====================================================================== handlers

def cmd_qa(args: argparse.Namespace) -> int:
    from .qa import video as qa
    from .job import ledger
    from .common import brief_output
    brief = brief_output(args.verbose)
    video, _job, _ = ledger.media_arg(args.video, "video", say=log)
    rep = qa.run(video, project=args.project, expect_file=args.expect, out_dir=args.out, platform=args.platform,
                 lufs=args.lufs, captions=args.captions, sheet=not args.no_sheet, sheet_count=args.sheet_count,
                 quiet=args.json, steps=not brief)
    review = _review_of(_job, video)   # the job's critic round (quality mode); never changes the video's verdict
    if review is not None:
        rep["review"] = review
    if args.json:
        print_json(rep)
    else:
        print(qa.format_text(rep, verbose=args.verbose, brief=brief))
        _print_review(review)
    if rep["verdict"] == "FAIL" or (args.strict and rep["verdict"] == "WARN"):
        return 1
    return 0


def _review_of(job, video=None):
    """The review state of a job's final (st.job.review_state), or None: no job, not a final, or unreadable."""
    if job is None:
        return None
    try:
        from .job import ledger, review_state
        data = ledger.load(job)
        if video is not None:
            latest, kind = ledger.latest_video(job, data)
            if kind != "final" or latest is None or latest.resolve() != Path(video).resolve():
                return None      # a preview, an export or an older render: the review is about the latest final
        return review_state.state(job, data, Path(video) if video is not None else None)
    except Exception:  # noqa: BLE001 - the review line never breaks qa or deliver
        return None


def _print_review(review, stream=None) -> None:
    """The review line after a verdict: a WARN while a quality-mode critic round is pending."""
    if not review:
        return
    from .job import review_state
    out = stream or sys.stdout
    line = review_state.pending_line(review)
    if line:
        out.write(line + "\n")
    elif review.get("status") in ("done", "cap"):
        out.write("review: %s%s\n" % (review["message"], ("; next: " + review["next"]) if review.get("next") else ""))


def cmd_review_pack(args: argparse.Namespace) -> int:
    from .qa import review
    if args.against:
        from .qa import pairwise
        m = pairwise.build(args.target, args.against, out=args.out, project=args.project, expect_file=args.expect,
                           platform=args.platform, force_round=args.force_round, every=args.every, quiet=args.json,
                           lufs=args.lufs)
        print_json(m) if args.json else pairwise.print_pack(m)
        return 0
    m = review.build(args.target, out=args.out, project=args.project, expect_file=args.expect, platform=args.platform,
                     force_round=args.force_round, every=args.every, quiet=args.json, lufs=args.lufs)
    if args.json:
        print_json(m)
        return 0
    print("review pack round %d  (qa %s: %d fail, %d warn)" % (m["round"], m["qa"]["verdict"], m["qa"]["summary"]["fail"],
                                                               m["qa"]["summary"]["warn"]))
    print("  sheet     %s" % m["sheet"])
    if m.get("scenes_sheet"):
        print("  scenes    %s  (%d scenes, %d cuts, from %s)" % (m["scenes_sheet"], len(m["scenes"]), len(m["cuts"]),
                                                             m.get("scenes_source") or "cut detection"))
    if m.get("loudness_graph"):
        print("  loudness  %s" % m["loudness_graph"])
    if m.get("cut_strips"):
        print("  cuts      %s  (frame by frame around each cut)" % m["cut_strips"])
    print("  frames    %d key + %d scene frames in %s" % (len(m["key_frames"]), len(m["scene_frames"]), Path(m["dir"]) / "frames"))
    print("  context   %d file(s)%s" % (len(m["context"]), "  (no job or project found: no brief, plan or check report; "
                                                            "pass --project)" if m.get("missing_context") else ""))
    for other in m.get("not_in_pack") or []:
        print("  not in this pack: %s  (review it with: showtime review-pack %s)" % (other, other))
    print("  brief     %s" % m["critic"])
    print("  next: give a fresh sub-agent only the brief's path and ask for FINDINGS.md in that folder. "
          "No sub-agent tool? Answer CRITIC.md yourself into FINDINGS.md, say it was a self-review, and ask the "
          "user for a second look before calling it shipped.")
    print(m["dir"])
    return 0


def cmd_review_verdict(args: argparse.Namespace) -> int:
    from .qa import pairwise
    v = pairwise.verdict(args.target, args.round)
    print_json(v) if args.json else pairwise.print_verdict(v)
    return 0


def cmd_job_init(args: argparse.Namespace) -> int:
    from .job import ledger
    if args.platform:
        from .qa.video import target_for
        target_for(args.platform)  # unknown names fail here, not at qa time
    flow, review = _split_modes(args.mode)
    d, data = ledger.init(args.slug, mode=flow or "quick", goal=args.goal, base=args.base, project=args.project,
                          assumed=args.assumed, questions=args.question, next_cmd=args.next_cmd, platform=args.platform,
                          request=args.request, review_mode=review)
    if data.get("gitignore_written"):
        log("showtime-out/ is inside a git repo: wrote showtime-out/.gitignore so renders are never committed")
    setup = None if args.no_check else _setup_check()
    from . import review_mode as rmode
    rv, rv_src = data["review_mode"], data["review_mode_source"]
    if args.json:
        out = {"job": str(d), "ledger": str(d / "job.json"), "notes": str(d / "SHOWTIME.md"), "mode": data["mode"],
               "review_mode": {"mode": rv, "source": rmode.SOURCES.get(rv_src, rv_src), "summary": rmode.SUMMARY[rv]}}
        if setup is not None:
            out["setup"] = {"ok": setup.get("ok"), "counts": setup.get("counts"),
                            "problems": [r for r in setup.get("checks") or [] if r.get("status") in ("warn", "fail")]}
        print_json(out)
    else:
        log("job %s (%s mode)" % (d.name, data["mode"]))
        log("review: " + rmode.describe(rv, rv_src))
        if setup is not None:
            from .doctor import quick_lines
            sys.stderr.write("\n".join(quick_lines(setup)) + "\n")   # stdout stays the job folder alone
        print(str(d))
    return 0


def _setup_check():
    """The quick setup check (doctor --quick, reused for an hour), so a job starts in one command."""
    try:
        from .doctor import quick_check
        return quick_check()
    except Exception as e:  # noqa: BLE001 - never fail job init over the check itself
        log("setup check skipped (%s: %s); run `showtime doctor --quick`" % (type(e).__name__, e))
        return None


def cmd_job_note(args: argparse.Namespace) -> int:
    from .job import ledger
    job = ledger.resolve(args.job)
    data = ledger.note(job, stage=args.stage, status=args.status, seconds=args.seconds, verified=args.verified,
                       assumed=args.assumed, questions=args.question, answers=args.answer, next_cmd=args.next_cmd,
                       pointers=args.pointer, warnings=args.warning, goal=args.goal, outputs=args.output,
                       cache_hits=args.cache_hit, cache_misses=args.cache_miss, event=args.event, mode=_split_modes(args.mode)[0],
                       review_mode=_split_modes(args.mode)[1],
                       platform=args.platform, project=args.project, auto=args.auto, request=args.request,
                       render=_parse_render(args.render, args.render_span, args.seconds, args.render_base))
    if args.stage == "deliver" and (args.status or "done") == "done":
        from .job import receipt
        receipt.refresh(job)                # the natural end of a job: receipt.md, receipt.json, the share.txt line
        rv = _review_of(job)
        if rv and rv.get("pending"):
            from .job import review_state
            sys.stderr.write(review_state.pending_line(rv) + "  (delivered without the quality-mode critic round)\n")
    if args.json:
        print_json(data)
    else:
        for o in data.get("_recorded") or []:
            if o.get("variant"):
                log("%s logged as a variant, not the latest %s (%s). To make it the latest: showtime job note %s "
                    "--output %s=%s" % (Path(o["path"]).name, o["variant"], o["why"], job.name, o["variant"], o["path"]))
        for line in ledger.status_lines(job, data):
            print(line)
        print(str(job / "SHOWTIME.md"))
    return 0


def _parse_render(spec, span, seconds, base=None):
    """`--render KIND=FILE [--render-span A-B] [--render-base FILE]` -> the dict ledger.note(render=...) takes."""
    if not spec:
        if span or base:
            raise ShowtimeError("--render-span and --render-base need --render")
        return None
    kind, sep, name = spec.partition("=")
    if not sep or not kind.strip() or not name.strip():
        raise ShowtimeError("--render must look like KIND=FILE (KIND: full, preview or partial)")
    out = {"kind": kind.strip(), "file": name.strip(), "seconds": seconds}
    if span:
        import re
        m = re.match(r"^\s*([0-9.]+)\s*-\s*([0-9.]+)\s*$", span)
        if not m:
            raise ShowtimeError("--render-span must look like FROM-TO in seconds, e.g. 2.5-8")
        out["span"] = [float(m.group(1)), float(m.group(2))]
    if base:
        out["base"] = base
    return out


def cmd_job_discard(args: argparse.Namespace) -> int:
    from .job import ledger
    job = ledger.resolve(args.job)
    res = ledger.discard(job, args.file)
    if args.json:
        print_json(res)
        return 0
    log("discarded %s -> %s" % (Path(res["discarded"]).name, Path(res["moved"][0]).parent if res["moved"] else "?"))
    for m in res["moved"]:
        print("  moved   %s" % Path(m).name)
    for k in res.get("kept") or []:
        print("  kept    %s  (captions stay with the job; discard them by name if they were only for this render)"
              % Path(k).name)
    for k in ("final", "preview", "poster"):
        if res["outputs"].get(k):
            print("  latest %-8s %s" % (k, res["outputs"][k]))
    return 0


def cmd_job_list(args: argparse.Namespace) -> int:
    from .job import ledger
    jobs = ledger.list_jobs(args.base)
    if args.json:
        out = []
        for j in jobs:
            try:
                d = ledger.load(j)
            except ShowtimeError:
                d = {}
            out.append({"job": str(j), "mode": d.get("mode"), "stage": d.get("stage"), "updated": d.get("updated"),
                        "qa": (d.get("qa") or {}).get("verdict"), "goal": d.get("goal")})
        print_json(out)
        return 0
    if not jobs:
        print("no jobs under %s" % (", ".join(str(r) for r in ledger.out_roots(args.base)) or Path.cwd() / "showtime-out"))
        return 0
    for j in jobs[:40]:
        try:
            print(ledger.status_lines(j)[0])
        except ShowtimeError as e:
            print("%s  (%s)" % (j.name, e))
    return 0


def cmd_job_show(args: argparse.Namespace) -> int:
    from .job import ledger
    job = ledger.resolve(args.job)
    data = ledger.load(job)
    if args.json:
        print_json(data)
        return 0
    if not (job / "SHOWTIME.md").is_file():
        ledger.save(job, data)
    sys.stdout.write((job / "SHOWTIME.md").read_text(encoding="utf-8"))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from . import runs
    if args.runs or args.wait is not None or args.cancel or (args.job and runs.find(args.job)):
        # the launcher normally answers these itself (it works before setup); same code either way
        argv = ([args.job] if args.job else []) + (["--runs"] if args.runs else []) + \
            (["--wait", str(args.wait)] if args.wait is not None else []) + (["--cancel"] if args.cancel else []) + \
            (["--json"] if args.json else [])
        return runs.status_main(argv)
    from .job import ledger
    if args.job is None and ledger.enclosing_job(Path.cwd()) is None and ledger.latest() is None:
        msg = "no showtime jobs under %s" % (Path.cwd() / "showtime-out")
        if args.json:
            print_json({"job": None, "message": msg})
        else:
            print(msg)
            print("start one: showtime job init <slug>   (renders also create job folders)")
            from . import review_mode as rmode
            print("review mode for new jobs: " + rmode.describe(*rmode.default_mode()))
        return 0
    job = ledger.resolve(args.job)
    data = ledger.load(job)
    lines = ledger.status_lines(job, data)
    if args.json:
        open_q = [q["text"] for q in data.get("questions", []) if not q.get("answer")]
        print_json({"job": str(job), "lines": lines, "stage": data.get("stage"), "qa": data.get("qa"),
                    "open_questions": open_q, "next": ledger.suggest_next(job, data),
                    "outputs": ledger.outputs_view(job, data), "platform": data.get("platform"),
                    "mode": data.get("mode", "quick"), "review": _review_of(job),
                    "notes": str(job / "SHOWTIME.md") if (job / "SHOWTIME.md").is_file() else None})
    else:
        for line in lines:
            print(line)
    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    from .job import clean, ledger
    level = "frames" if args.frames else "all" if args.all else "default"
    if args.target and Path(args.target).expanduser().is_dir() and \
            clean.kind_of(Path(args.target).expanduser().resolve()) in ("project", "manim"):
        target = Path(args.target).expanduser().resolve()
    else:
        target = ledger.resolve(args.target)
    plan = clean.plan(target, level)
    if args.json and (args.dry_run or not plan["items"]):
        print_json(plan)
        return 0
    if not args.json:
        for line in clean.describe(plan):
            print(line)
    if not plan["items"] or args.dry_run:
        return 0
    if not args.yes:
        if not is_terminal(sys.stdin):
            raise ShowtimeError("refusing to delete without confirmation (not a terminal)",
                                hint="re-run with --yes after checking the list above (or --dry-run to only look)")
        name = Path(plan["target"]).name
        try:
            typed = input("type the folder name (%s) to delete %s: " % (name, human_size(plan["bytes"])))
        except EOFError:
            typed = ""
        if typed.strip() != name:
            print("cancelled: nothing deleted")
            return 1
    freed = clean.execute(plan)
    if plan["kind"] == "job" and (target / "job.json").is_file():
        try:
            ledger.note(target, event="clean (%s): freed %s" % (level, human_size(freed)))
        except ShowtimeError:
            pass
    if args.json:
        print_json(dict(plan, freed=freed))
    else:
        print("freed %s" % human_size(freed))
    return 0


def cmd_brand_init(args: argparse.Namespace) -> int:
    from . import brand as brandmod
    from .brand import draft
    from .common import output_dir, write_json
    out = Path(args.output).expanduser().resolve()
    if out.is_dir():
        out = out / "brand.json"
    if out.exists() and not args.force:
        raise ShowtimeError("%s already exists" % out, hint="pass --force to replace it, or -o another path")
    lookup = not args.no_font_lookup
    if args.site_json:
        sj = Path(args.site_json).expanduser().resolve()
        if not sj.is_file():
            raise ShowtimeError("site capture not found: %s" % sj,
                                hint="capture the site first: showtime site capture <url>, then pass its site.json")
        kit = draft.from_site(sj, lookup)
    elif args.url:
        roots = [Path.cwd(), Path.cwd() / "showtime-out"] + ([Path(args.capture_dir).expanduser().resolve()] if args.capture_dir else [])
        sj = draft.find_capture(args.url, roots)
        if sj:
            log("reusing the site capture in %s" % sj.parent)
        elif args.no_capture:
            raise ShowtimeError("no site capture found for %s" % args.url, hint="run: showtime site capture %s" % args.url)
        else:
            cap_dir = Path(args.capture_dir).expanduser().resolve() if args.capture_dir else output_dir("brand-capture", create=False)
            log("capturing %s (about 30-60 s) into %s" % (args.url, cap_dir))
            sj = draft.capture(args.url, cap_dir)
        kit = draft.from_site(sj, lookup)
    else:
        src = Path(args.from_dir or ".").expanduser().resolve()
        kit = draft.from_repo(src, lookup)
    out.parent.mkdir(parents=True, exist_ok=True)
    stored = draft.relativize(kit, out.parent)
    write_json(out, stored)
    md = out.with_suffix(".md")
    if md.exists() and not args.force:
        md = out.with_name(out.stem + ".draft.md")
    md.write_text(draft.brand_md(kit, out.name), encoding="utf-8", newline="\n")
    warns = brandmod.warnings_for(kit)
    if args.json:
        print_json({"brand": str(out), "notes": str(md), "kit": stored, "warnings": warns})
        return 0
    pal = brandmod.palette(kit)
    if kit.get("adopted_from"):
        log("the repo already has a brand kit: copied %s (status %s) instead of scanning; edit that file to change "
            "the brand" % (kit["adopted_from"], kit.get("status") or "not set"))
    else:
        log("drafted brand kit for %s: %d colour(s), %d font slot(s), logo %s" % (
            kit.get("name"), len(kit.get("colors") or []), len(kit.get("fonts") or {}),
            "found" if (kit.get("logo") or {}).get("path") else "not found"))
    for role in ("bg", "ink", "accent"):
        if pal.get(role):
            print("  %-7s %s" % (role, pal[role]))
    for w in warns:
        warn(w)
    print("  state these as assumptions (quick mode) or show them on the look board (studio); "
          "edit %s to correct them" % out.name)
    print(str(out))
    print(str(md))
    return 0


def _load_brand(path_arg):
    from . import brand as brandmod
    import os
    if path_arg:
        p = Path(path_arg).expanduser().resolve()
        os.environ["SHOWTIME_BRAND"] = str(p)
    kit = brandmod.load(Path.cwd())
    if kit is None:
        raise ShowtimeError("no brand.json found here or in the parent folders",
                            hint="draft one: showtime brand init --from <repo> (or --url <site>)")
    return kit


def cmd_brand_show(args: argparse.Namespace) -> int:
    from . import brand as brandmod
    kit = _load_brand(args.path)
    if args.json:
        print_json(kit)
        return 0
    print("%s  (%s%s)" % (kit.get("name"), kit["_file"], ", draft" if kit.get("status") == "draft" else ""))
    if kit.get("tagline"):
        print("  tagline  %s" % kit["tagline"])
    for role, hx in brandmod.palette(kit).items():
        print("  %-8s %s" % (role, hx))
    for slot, f in (kit.get("fonts") or {}).items():
        fam = f.get("family") if isinstance(f, dict) else f
        ok, where = brandmod.font_status(str(fam or ""))
        print("  font %-7s %s  (%s)" % (slot, fam, where))
    lg = kit.get("logo") or {}
    print("  logo     %s" % (lg.get("path") or "(none)"))
    v = kit.get("voice") or {}
    if v.get("id"):
        print("  voice    %s x%s" % (v["id"], v.get("speed", 1.0)))
    if kit.get("pronunciations"):
        print("  say      " + ", ".join("%s=%s" % kv for kv in kit["pronunciations"].items()))
    if kit.get("formats"):
        print("  formats  " + ", ".join(kit["formats"]))
    if kit.get("tone"):
        print("  tone     " + ", ".join(kit["tone"]))
    for w in brandmod.warnings_for(kit):
        warn(w)
    return 0


def cmd_brand_css(args: argparse.Namespace) -> int:
    from . import brand as brandmod
    css = brandmod.css_vars(_load_brand(args.path))
    if args.output:
        Path(args.output).write_text(css, encoding="utf-8")
        print(args.output)
    else:
        sys.stdout.write(css)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from .job import ledger, report
    job = None
    if args.job:
        job = ledger.resolve(args.job)
    else:
        job = ledger.latest()
    res = report.build(job, Path(args.output) if args.output else None, doctor=not args.no_doctor, problem=args.problem,
                       doctor_json=Path(args.doctor_json) if args.doctor_json else None)
    if args.json:
        print_json(res)
        return 0
    if res["redactions_left"]:
        warn("could not redact: %s. Read the file carefully before sharing it." % ", ".join(sorted(set(res["redactions_left"]))))
    log("wrote a local report (nothing was uploaded). Read it before sharing.")
    print(res["path"])
    return 0

"""`showtime release-video`: release notes or a PR description -> a video project, no agent needed."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .common import ShowtimeError, print_json

COMMANDS = {
    "release-video": "Release notes, a CHANGELOG section or a PR description -> a ready-to-render video project",
}

_F = argparse.RawDescriptionHelpFormatter


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("release-video", help=COMMANDS["release-video"], formatter_class=_F, description=(
        "Write a video project from release notes, with no agent in the loop (CI, the GitHub Action).\n\n"
        "Reads Markdown release notes (a GitHub release body, a CHANGELOG section with --changelog-version,\n"
        "or a PR description with --kind pr) and writes <out>/index.html, showtime.json and audio/mix.json:\n"
        "a hook card (name, version, date), one scene per group of changes (the notes' own headings and lines,\n"
        "verbatim; long lines are cut at a word with an ellipsis), and an end card (install command, URL and\n"
        "the @people the notes credit). Internal sections (dependencies, CI, docs, chores) are counted, not\n"
        "shown. Every word on screen comes from the notes or from a flag, so nothing is invented. The music\n"
        "is composed on this machine. Then: `showtime check <out>`, `showtime render <out>`, `showtime qa`.\n\n"
        "For a film with an angle (a demo of the new feature, a real diff) follow the changelog workflow\n"
        "with an agent instead; this command is the unattended fallback."),
        epilog=("Examples:\n"
                "  showtime release-video notes.md -o release-project --name acme --version 2.3.0\n"
                "  showtime release-video CHANGELOG.md --changelog-version 2.3.0 --name acme -o rv\n"
                "  gh release view v2.3.0 --json body -q .body | showtime release-video - --name acme -o rv\n"
                "  showtime release-video pr.md --kind pr --name acme --version '#482' -o pr-video\n"
                "  showtime release-video notes.md -o rv --install 'pip install -U acme' --url https://acme.dev"))
    p.add_argument("notes", help="Markdown file with the notes, or - for stdin")
    p.add_argument("-o", "--out", required=True, help="project folder to write (created; must be empty unless --force)")
    p.add_argument("--name", help="product or repository name (default: the notes' title, else the folder name)")
    p.add_argument("--version", dest="rel_version", metavar="VERSION",
                   help="version shown (default: found in the notes' title)")
    p.add_argument("--changelog-version", metavar="VERSION",
                   help="the notes file is a whole CHANGELOG: use the section of this version")
    p.add_argument("--kind", choices=["release", "pr"], default="release", help="labels for a release or a PR")
    p.add_argument("--date", help="date shown on the hook (default: found in the notes)")
    p.add_argument("--install", help="install or upgrade command for the end card, e.g. 'pip install -U acme'")
    p.add_argument("--url", help="URL for the end card (the release page)")
    p.add_argument("--aspect", default="16:9", choices=["16:9", "9:16", "1:1", "4:5"])
    p.add_argument("--max-items", type=int, default=7, help="lines shown in all (default 7; the rest are counted)")
    p.add_argument("--force", action="store_true", help="write into a non-empty folder")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.set_defaults(func=cmd_release_video)


def cmd_release_video(args: argparse.Namespace) -> int:
    from . import release_video as rv
    if args.notes == "-":
        md = sys.stdin.read()
    else:
        src = Path(args.notes)
        if not src.is_file():
            raise ShowtimeError("notes file not found: %s" % src, hint="pass a Markdown file, or - to read stdin")
        md = src.read_text(encoding="utf-8", errors="replace")
    if args.changelog_version:
        sec = rv.changelog_section(md, args.changelog_version)
        if not sec:
            raise ShowtimeError("no section for version %s in %s" % (args.changelog_version, args.notes),
                                why="looked for a heading such as '## %s' or '## [v%s] - <date>'"
                                    % (args.changelog_version, args.changelog_version.lstrip("v")),
                                hint="check the version spelling, or pass the section itself as the notes file")
        md = sec
    notes = rv.parse_notes(md)
    if not any(s["items"] for s in notes["sections"]):
        raise ShowtimeError("no user-facing changes found in the notes",
                            why="the video shows the notes' bullet lines; there were none outside internal sections "
                                "(dependencies, CI, docs, chores)",
                            hint="pass notes with a bulleted list of changes, or make the video with an agent "
                                 "(references/workflows/changelog-video.md)")
    name = args.name or _name_from_title(notes["title"]) or Path(os.getcwd()).name
    version = args.rel_version or notes["version"]
    if args.kind == "pr" and version and version.isdigit():
        version = "#" + version
    p = rv.plan(notes, name=name, version=version, kind=args.kind, max_items=max(1, args.max_items))
    try:
        res = rv.write_project(Path(args.out), notes, p, install=args.install or "", url=args.url or notes["compare"] or "",
                               date=args.date or notes["date"], aspect=args.aspect, force=args.force)
    except FileExistsError:
        raise ShowtimeError("%s is not empty" % args.out, hint="pick a new folder, or pass --force to write into it")
    if args.json:
        print_json(res)
        return 0
    print("wrote %s: %d scenes, %.1f s, %d of %d changes shown%s" % (
        res["project"], res["scenes"], res["duration"], res["shown"], res["total"],
        " (%d more counted on screen)" % res["more"] if res["more"] else ""))
    print("next: showtime check %s && showtime render %s" % (_q(res["project"]), _q(res["project"])))
    return 0


def _name_from_title(title: str) -> str:
    import re
    t = re.sub(r"\bv?\d+\.\d+(?:\.\d+)?\S*", "", title or "")
    t = re.sub(r"\b(release|released|version)\b", "", t, flags=re.I)
    t = re.sub(r"\d{4}-\d{2}-\d{2}", "", t)
    return t.strip(" -–—:·|[]()")


def _q(s: str) -> str:
    return '"%s"' % s if " " in s else s

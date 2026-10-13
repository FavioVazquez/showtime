"""`showtime recap`: a Claude Code session -> a short narrated film of what the agent did."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .common import ShowtimeError, print_json

COMMANDS = {
    "recap": "A Claude Code session -> a short narrated film of what the agent did (allow-listed facts only)",
}

_F = argparse.RawDescriptionHelpFormatter


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("recap", help=COMMANDS["recap"], formatter_class=_F, description=(
        "Turn a Claude Code session into a 30-60 s narrated film of what the agent did: a title from the\n"
        "facts, the numbers (time, turns, tool calls, files), a timeline of the files it read and edited and the\n"
        "commands and tests it ran, where the edits landed, the tests red to green, and the diff from git.\n\n"
        "Privacy is an allow-list of facts: a title made from them, tool names and counts, repository-relative\n"
        "paths of files inside the repository, program names from a fixed list with their own subcommand\n"
        "(`git commit`, `npm test`; anything else is \"other\"), test counts, git diff stats and timestamps.\n"
        "Free text (the request, a sub-agent's description) is only offered in script.md as a # suggestion;\n"
        "editing script.md is the only way to change what is on screen. Assistant text, tool output, memory,\n"
        "paths, URLs and the environment are not on the list.\n"
        "A hard filter then drops any line that looks like a key or token, an absolute path, a URL, a host or\n"
        "an e-mail address, and nothing is rendered before you have read script.md: filters can miss things.\n\n"
        "<out> is showtime-out/recap-<session> unless --out is given. First run: writes <out>/script.md (every line that will be shown or spoken) and <out>/facts.json,\n"
        "and stops. Read and edit script.md, then run the same command with --yes: it builds <out>/project,\n"
        "narrates it (showtime voice, captions burned in), checks, renders <out>/recap.mp4 and runs qa.\n"
        "Everything runs on this machine and nothing is uploaded; the music may be a catalog track downloaded once\n"
        "from its creator's site (nothing is sent; --music <style> or SHOWTIME_OFFLINE=1 keeps it fully local)."),
        epilog=("Examples:\n"
                "  showtime recap --latest                       # this folder's newest session: script.md first\n"
                "  showtime recap --latest --yes                 # after reading script.md: render it\n"
                "  showtime recap ~/.claude/projects/<project>/<session>.jsonl --repo . --out ~/recaps/parser\n"
                "  showtime recap <session-id> --since main --yes --no-voice --preview   # script.md read already\n"
                "  showtime recap --latest --yes --aspect 9:16 --out ~/recaps/parser-vertical\n\n"
                "A recap covers one transcript: a session's sub-agents have their own (recap them separately). Run\n"
                "inside Claude Code, --latest picks the session in progress."))
    p.add_argument("session", nargs="?", help="a session transcript (.jsonl), or a session id")
    p.add_argument("--latest", action="store_true", help="the newest session of the current folder")
    p.add_argument("--repo", metavar="DIR", help="the repository the session worked in (default: its working folder)")
    p.add_argument("--since", metavar="REF", help="diff stats from git diff REF (default: the session's own commits)")
    p.add_argument("--out", help="output folder (default: showtime-out/recap-<session> under $SHOWTIME_OUT or the "
                   "current folder; refused inside a git repository where git would track it)")
    p.add_argument("--yes", action="store_true",
                   help="build and render from an existing script.md (a call that writes script.md never renders)")
    p.add_argument("--fresh", action="store_true", help="rewrite script.md from the session (drops your edits; "
                   "nothing is rendered in that call)")
    p.add_argument("--no-voice", action="store_true", help="no narration (and no captions); scenes hold for reading")
    p.add_argument("--voice", default="af_heart", help="narration voice (default af_heart)")
    p.add_argument("--aspect", default="16:9", choices=["16:9", "9:16"])
    p.add_argument("--cut-sounds", action="store_true",
                   help="a soft swoosh on each scene cut (off by default: a film has no sound on its cuts)")
    p.add_argument("--music", metavar="STYLE|ID|none",
                   help="pin the music: a composed style (showtime audio styles), a catalog track id, or none "
                        "(default: chosen from the session, off what the last films used)")
    p.add_argument("--no-render", action="store_true", help="with --yes: write the project only")
    p.add_argument("--preview", action="store_true", help="fast draft render (<=720p)")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.set_defaults(func=cmd_recap)


def _launcher() -> Path:
    return Path(__file__).resolve().parent / "launcher.py"


def _st(args: list, *, quiet: bool, capture: bool = False) -> subprocess.CompletedProcess:
    sys.stdout.flush()
    return subprocess.run([sys.executable, str(_launcher())] + [str(a) for a in args],
                          stdout=subprocess.PIPE if capture else (subprocess.DEVNULL if quiet else sys.stderr),
                          stderr=subprocess.DEVNULL if quiet and not capture else None,
                          encoding="utf-8", errors="replace")


def cmd_recap(args: argparse.Namespace) -> int:
    from . import recap as rc
    say = (lambda *a: None) if args.json else (lambda *a: print(*a, file=sys.stderr))
    if args.session:
        path = rc.find_session(args.session)
    elif args.latest:
        path = rc.latest_session(Path.cwd())
    else:
        raise ShowtimeError("no session given", hint="showtime recap --latest, or showtime recap <session.jsonl>")
    ses = rc.parse_session(path)
    top, roots = rc.repo_roots(ses, args.repo)
    facts = rc.collect(ses, top, roots, since=args.since)
    suggestions = rc.suggestions_for(ses)     # free text: written to script.md as comments, nowhere else
    del ses                                   # nothing of the raw session goes further than this line
    out = Path(args.out) if args.out else _default_out(facts["ref"])
    out.mkdir(parents=True, exist_ok=True)
    script = out / "script.md"
    fresh_lines = rc.script_lines(facts)
    kept_edits = False
    if script.is_file() and not args.fresh:
        ref, lines = rc.read_script(script.read_text(encoding="utf-8", errors="replace"))
        if ref != facts["ref"]:
            raise ShowtimeError("%s was written for another session" % script,
                                hint="pass another --out, or --fresh to rewrite it for this session")
        kept_edits = True
    else:
        lines = fresh_lines
    # every line the person wrote (any key whose text recap did not write, or a key recap never writes): the
    # strict request rule as well as the hard filter; a refused line falls back to recap's own, else goes
    refused = []
    for key in list(lines):
        ln = lines[key]
        mine = rc.own_line(key, ln["text"], fresh_lines, facts)
        if mine == "own":
            continue
        if mine == "stale":                   # recap's line with an old 6+ digit count: today's, silently
            lines[key] = dict(fresh_lines[key])
            continue
        if rc.free_text_refused(ln["text"]):
            refused.append(key)
            if key in fresh_lines:
                lines[key] = dict(fresh_lines[key])
            else:
                del lines[key]
    lines, dropped = rc.hard_filter(lines)
    for key in refused:
        say("refused %s from script.md: it names a path, host, address, key, a value-like word or a long number "
            "(the request rule); %s" % (key, "recap's own line is used instead" if key in lines else "left out"))
    if "hook.title" not in lines:             # a title is needed: the facts' own
        lines["hook.title"] = {"scene": "hook", "kind": "show", "text": rc.facts_title(facts)}
        lines.move_to_end("hook.title", last=False)
    if not kept_edits:
        script.write_text(rc.write_script(lines, facts["ref"], suggestions), encoding="utf-8")
    (out / "facts.json").write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
    res = {"script": str(script), "facts": str(out / "facts.json"), "summary": rc.summary(facts),
           "dropped": dict(dropped), "refused": refused, "lines": len(lines),
           "kept_script": kept_edits}         # True: an existing script.md was read as it is (edited or not)
    say("recap of %s: %s" % (Path(path).name, res["summary"]))
    if dropped:
        say("hard filter: dropped %s" % ", ".join("%d line%s (%s)" % (n, "" if n == 1 else "s", why)
                                                   for why, n in dropped.items()))
    if not args.yes or not kept_edits:
        # a script written in this call is never rendered in it: the person reads it first (also with --yes)
        res["next"] = "read %s, edit it if you like, then run the same command with --yes" % script
        res["rendered"] = False
        if args.json:
            print_json(res)
        else:
            print(script)
            say("%s %s: every line the film will show or speak. Read it, then rerun with --yes (edit or delete "
                "lines first if you like).%s" % ("kept your" if kept_edits else "wrote", script,
                                                 " Nothing was rendered: this call wrote the script." if args.yes
                                                 else ""))
        return 0
    say("using %s as you left it" % script)

    scenes = [s for s in rc.scenes_for(facts) if s == "end" or any(ln["scene"] == s for ln in lines.values())]
    project = out / "project"
    if project.exists() and any(project.iterdir()) and not (project / "recap.json").is_file():
        raise ShowtimeError("%s exists and was not written by recap" % project, hint="pass another --out")
    project.mkdir(parents=True, exist_ok=True)
    voice = not args.no_voice and any(ln["kind"] == "say" for ln in lines.values())
    slots = None
    if voice:
        slots = _narrate(rc, facts, lines, scenes, project, args, say)
    durs = rc.durations(facts, lines, scenes, slots)
    files = rc.project_files(facts, lines, scenes, durs, aspect=args.aspect, captions=bool(voice), music=args.music,
                             fetch=True, project=project, cut_sounds=args.cut_sounds)
    rc.write_project(project, files)
    if voice:
        cp = _st(["retime", project, "--from-voice", project / "voice" / "timeline.json", "--pad", rc.PAD],
                 quiet=args.json)
        if cp.returncode != 0:
            raise ShowtimeError("showtime retime --from-voice failed on %s" % project,
                                hint="run it yourself to see why, or rerun recap with --no-voice")
    job = _job(out, project)
    cfg = json.loads((project / "showtime.json").read_text(encoding="utf-8"))
    res.update({"project": str(project), "duration": cfg.get("duration"), "scenes": scenes, "voice": bool(voice),
                "music": files["bed"]["label"],
                "job": str(job)})
    say("wrote %s: %d scenes, %.1f s%s" % (project, len(scenes), float(cfg.get("duration") or 0),
                                          ", narrated" if voice else ""))
    if args.no_render:
        if files["bed"]["how"] == "catalog":
            res["music_note"] = ("the music is fetched when you render (showtime audio music fetch %s now to have it "
                                 "cached)" % files["bed"]["id"])
        if args.json:
            print_json(res)
        else:
            if res.get("music_note"):
                say("music: %s" % res["music_note"])
            print(project)
        return 0
    from .cli_release import _render_pr
    from . import bed
    bed.ensure(project / "audio" / "mix.json", files["bed"])
    res["music"] = files["bed"]["label"]
    say("music: %s" % files["bed"]["label"])
    stem = "recap-9x16" if args.aspect == "9:16" else "recap"
    video = _render_pr(project, out / (stem + ".mp4"), preview=args.preview, quiet=args.json)
    from .job import ledger
    kind = "preview" if args.preview else "final"
    ledger.note(job, outputs=["%s=%s" % (kind, video)], event="recap: %s is the latest %s" % (video.name, kind))
    cp = _st(["qa", video, "--project", project, "--json"], quiet=True, capture=True)
    try:
        q = json.loads(cp.stdout[cp.stdout.index("{"):])
        verdict = q.get("verdict") or ("FAIL" if cp.returncode else "PASS")
        res["qa"] = {"verdict": verdict, "findings": [
            {"severity": f.get("severity"), "rule": f.get("rule"), "t": f.get("t"), "message": f.get("message")}
            for f in (q.get("findings") or []) if f.get("severity") in ("WARN", "FAIL")][:12]}
    except (ValueError, AttributeError):
        res["qa"] = {"verdict": "FAIL" if cp.returncode else "?"}
    res["video"] = str(video)
    owed = bed.credit_report(video, files["bed"])
    if owed["credits"]:
        res.update({"credits": owed["credits"], "share": owed["share"], "credit_notes": owed["notes"]})
    from .pr_video import remove_work
    remove_work(video)                        # the render's work folder (stems, absolute local paths), once qa ran
    if args.json:
        print_json(res)
        return 0 if cp.returncode == 0 else 1
    print(video)
    if owed["credits"]:
        say("credits %s   (the music needs its credit where you post the video)" % owed["credits"])
    for n in owed["notes"]:
        say("note: " + n)
    say("qa %s%s" % (res["qa"]["verdict"], ": " + "; ".join("%s %s" % (f["severity"], f["rule"]) for f in
                                                            res["qa"].get("findings") or []) if res["qa"].get("findings") else ""))
    return 0 if cp.returncode == 0 else 1


def _narrate(rc, facts, lines, scenes, project: Path, args, say) -> dict:
    """voice/narration.md -> showtime voice script; then, when a scene needs longer than its line, the same
    script again with a pause after that line (only the timeline changes: the lines come from the cache).
    Returns {scene: slot seconds}."""
    vdir = project / "voice"
    vdir.mkdir(parents=True, exist_ok=True)
    md = vdir / "narration.md"
    pauses: dict = {}
    for attempt in range(2):
        md.write_text(rc.narration_md(lines, scenes, voice=args.voice, pauses=pauses), encoding="utf-8")
        cp = _st(["voice", "script", md, "-o", vdir], quiet=True, capture=True)
        tl_path = vdir / "timeline.json"
        if cp.returncode != 0 or not tl_path.is_file():
            raise ShowtimeError("the narration could not be made (showtime voice script failed)",
                                hint="run `showtime doctor` (the voice needs `showtime setup`), or rerun with --no-voice")
        tl = json.loads(tl_path.read_text(encoding="utf-8"))
        speech = {ln["id"]: float(ln.get("duration") or (ln["end"] - ln["start"])) for ln in tl.get("lines", [])}
        slots = {ln["id"]: float(ln["slot"].get("duration") or 0) for ln in tl.get("lines", [])}
        more = rc.extra_pauses(facts, lines, scenes, speech)
        if attempt == 0 and any(abs(more.get(s, 0) - pauses.get(s, 0)) > 0.05 for s in set(more) | set(pauses)):
            pauses = more
            continue
        break
    say("narration: %d lines, %.1f s (%s)" % (len(slots), float(tl.get("duration") or 0), args.voice))
    return slots


def _default_out(ref: str) -> Path:
    """showtime-out/recap-<ref> (stable per session, so the --yes call finds the script the first call wrote),
    under $SHOWTIME_OUT or the current folder. Refused when git would track it: recap's files hold the session's
    facts and should never be committed by accident."""
    base = Path(os.environ.get("SHOWTIME_OUT") or Path.cwd())
    root = base if base.name == "showtime-out" else base / "showtime-out"
    out = root / ("recap-" + ref)
    probe = (out / "script.md").absolute()
    near = out.absolute()                     # git runs from the nearest folder that exists (SHOWTIME_OUT may not yet)
    while not near.is_dir() and near.parent != near:
        near = near.parent
    try:
        cp = subprocess.run(["git", "-C", str(near), "rev-parse", "--is-inside-work-tree"], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, encoding="utf-8", timeout=30)
        in_repo = cp.returncode == 0 and cp.stdout.strip() == "true"
        ignored = in_repo and subprocess.run(["git", "-C", str(near), "check-ignore", "-q", "--no-index",
                                              str(probe)],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        in_repo, ignored = False, False
    if in_repo and not ignored:
        raise ShowtimeError("the default output folder %s is inside a git repository that would track it" % out,
                            why="recap's files hold the session's facts; they should never be committed by accident",
                            hint="pass --out <a folder outside the repository>, set SHOWTIME_OUT, or add "
                                 "showtime-out/ to the repository's .gitignore")
    return out


def _job(out: Path, project: Path) -> Path:
    """The output folder is recap's own job (so `showtime qa <out>` and the receipt find the video, and the
    render never logs into a job above it)."""
    from .job import ledger
    o = out.resolve()
    if ledger.enclosing_job(o) == o:
        return o
    data = ledger.new_data(o.name or "recap", "quick", "showtime recap: a short film of what an agent did in a "
                           "session", o, project.resolve())
    data["pointers"]["project"] = str(project.resolve())
    data["history"][-1]["event"] = "job created by showtime recap"
    ledger.save(o, data)
    return o

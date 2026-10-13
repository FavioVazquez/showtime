"""`showtime repro`: a failing browser test (a Playwright trace, or the command that runs it) -> a short narrated
video for a bug report or a pull request, with steps.json, captions and a repro.md to paste. The first call writes
the film's script (script.md) and stops; the person reads it, then `--yes` renders it."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

from .common import ShowtimeError, print_json

COMMANDS = {
    "repro": "A failing browser test (a Playwright trace or the test command) -> a short narrated video for a bug report",
}

_F = argparse.RawDescriptionHelpFormatter
SCREENSHOTS = "screenshots are shown as captured; --redact does not touch pixels"


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("repro", help=COMMANDS["repro"], formatter_class=_F, description=(
        "A bug report you can watch: turn a failing Playwright test into a short narrated video (10-40 s) of\n"
        "what it did, step by step on the real page, and exactly where and how it failed.\n\n"
        "Input: a Playwright trace (the trace.zip `npx playwright test --trace on` or `pytest --tracing on`\n"
        "writes), or the test command after `--`: showtime turns tracing on for failing tests (--trace\n"
        "retain-on-failure / --tracing retain-on-failure, with --output in a temporary folder, unless you gave\n"
        "them), runs it (stopped after --timeout seconds) and films the first failing test's trace.\n\n"
        "Two calls. The first writes <job>/script.md (every caption, spoken line and on-screen text, and the\n"
        "masked steps) and stops: nothing is rendered. Read it, edit or delete lines, then run the same command\n"
        "again with --yes (or `showtime repro --yes <job>`): every line goes through the filters again, then\n"
        "the film is narrated, rendered and checked (check, render, qa).\n\n"
        "The film: a title card (test name, file:line, FAILED); each action on its screenshot from the trace\n"
        "with a cursor and click ripple at the target box, a step counter and a one-line caption; the failing\n"
        "step slowed down (its source line, expected and received side by side, the error, console errors);\n"
        "an end card with the command that re-runs it. Long tests keep the first step and the steps before\n"
        "the failure; the passing steps between them become one \"+ N passing steps\" scene. Narrated by\n"
        "showtime's local voice (--no-voice: captions only). The music may be a catalog track downloaded once from\n"
        "its creator's site (nothing is sent; its credit goes into repro.md; --music <style> or SHOWTIME_OFFLINE=1\n"
        "keeps it fully local).\n\n"
        "Writes into a job folder (showtime-out/repro-<timestamp>/, or --out): script.md and report.json\n"
        "(first call); repro.mp4 (16:9, 1080p), repro.srt, repro.poster.jpg, steps.json, repro.md and project/\n"
        "(--yes). The raw trace is not kept (--keep-trace keeps the run's traces in <job>/work, unfiltered).\n\n"
        "Privacy: what was typed is never shown or spoken, in any field (\"Type 12 characters into the 'Email'\n"
        "field\"), and the field is covered in the screenshots from then on; --show-typed shows what was typed\n"
        "into fields that are not secret (filtered). URLs lose their query string and fragment; paths on the\n"
        "machine show as their last part; auth headers, NAME=value secrets, e-mail addresses (--show-emails\n"
        "keeps them) and key-shaped strings are masked; --redact REGEX (repeatable) masks more. Network data\n"
        "is never shown. Screenshots are shown as captured (--redact does not touch pixels): run the test\n"
        "with a test account, and watch the film before you post it."),
        epilog=("Examples:\n"
                "  showtime repro test-results/login-signs-in-chromium/trace.zip     # writes script.md, stops\n"
                "  showtime repro test-results/login-signs-in-chromium/trace.zip --yes   # after reading it\n"
                "  showtime repro -- npx playwright test tests/login.spec.ts\n"
                "  showtime repro -- pytest tests/test_login.py\n"
                "  showtime repro --yes showtime-out/repro-20261012-101500 --no-voice --preview\n"
                "  showtime repro trace.zip --redact 'acct-[0-9]+' --redact 'staging\\.acme\\.test'\n"
                "  showtime repro --yes --out bug-1234 --no-render     # the project, steps.json, repro.md"))
    p.add_argument("input", nargs="*", metavar="TRACE | JOB | -- COMMAND",
                   help="a trace.zip, the test command after -- (run with tracing on), or with --yes a job folder")
    p.add_argument("--yes", action="store_true",
                   help="render from the job's script.md as you left it (a call that writes script.md never renders)")
    p.add_argument("--out", help="job folder (default: showtime-out/repro-<timestamp>/)")
    p.add_argument("--redact", action="append", default=[], metavar="REGEX",
                   help="mask text matching this regular expression everywhere it would show (repeatable; also "
                        "applied again with --yes)")
    p.add_argument("--show-typed", action="store_true",
                   help="show what was typed into fields that are not secret (filtered; never spoken)")
    p.add_argument("--show-emails", action="store_true", help="do not mask e-mail addresses")
    p.add_argument("--keep-trace", action="store_true",
                   help="keep the run's raw traces in <job>/work/test-results (unfiltered: they hold what was typed)")
    p.add_argument("--timeout", type=float, default=1800.0, metavar="SECONDS",
                   help="stop the test command after this long (default 1800)")
    p.add_argument("--no-voice", action="store_true", help="no narration: captions (repro.srt) only")
    p.add_argument("--voice", metavar="NAME", help="narration voice (default af_heart; showtime voice list)")
    p.add_argument("--cut-sounds", action="store_true",
                   help="a soft swoosh on each scene cut (off by default: a film has no sound on its cuts)")
    p.add_argument("--music", metavar="STYLE|ID|none",
                   help="pin the music: a composed style (showtime audio styles), a catalog track id, or none "
                        "(default: chosen from the test, off what the last films used)")
    p.add_argument("--size", choices=["1080p", "720p"], default="1080p", help="frame size, 16:9 (default 1080p)")
    p.add_argument("--preview", action="store_true", help="fast draft render (<=720p)")
    p.add_argument("--no-render", action="store_true", help="with --yes: write the project, steps.json, repro.srt "
                                                            "and repro.md only")
    p.add_argument("--keep-work", action="store_true", help="keep the render's work folders (audio stems, check report)")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p.set_defaults(func=cmd_repro)


def _is_command(args: list, argv: Optional[list] = None) -> bool:
    """A command when `--` was given (argparse drops it) or there is more than one word; else a trace or a job."""
    argv = sys.argv[1:] if argv is None else argv
    return "--" in argv or len(args) > 1


def _command_line(redact) -> str:
    """The command line for job.json, with --redact patterns hidden (a pattern can be the secret itself) and
    the rest redacted."""
    argv, out, hide = sys.argv[1:], [], False
    for a in argv:
        if hide:
            out.append("<pattern>")
            hide = False
        elif a == "--redact":
            out.append(a)
            hide = True
        elif a.startswith("--redact="):
            out.append("--redact=<pattern>")
        else:
            out.append(redact(a))
    return " ".join(out)[:300]


def _job(out_arg, goal: str, redact) -> "tuple[Path, bool]":
    """The job folder, made once there is something to put in it: --out (a new or empty folder, or a job
    folder without a repro yet), else a fresh showtime-out/repro-<timestamp>/ (beside the job the current
    folder is inside, never in it). Returns (the folder, whether this call made it)."""
    from .job import ledger
    made = True
    if out_arg:
        out = Path(out_arg)
        if out.exists() and ledger.enclosing_job(out) == out.resolve():
            if (out / "report.json").exists() or (out / "project").exists():
                raise ShowtimeError("%s already holds a repro" % out, hint="pick a new --out folder, or add --yes "
                                                                          "to render its script.md")
            return out, False
        if out.exists() and any(out.iterdir()):
            raise ShowtimeError("%s is not empty" % out, hint="pick a new --out folder (renders never overwrite)")
        out.mkdir(parents=True, exist_ok=True)
        d, data = out, ledger.new_data("repro", "quick", goal, out.resolve(), None)
        data["history"][-1]["event"] = "job created by showtime repro"
    else:
        here = ledger.enclosing_job(Path.cwd())
        d, data = ledger.init("repro", goal=goal, base=here.parent if here is not None else None)
    data["command"] = _command_line(redact)
    ledger.save(d, data)
    return d, made


def _input_key(inputs: list, is_cmd: bool) -> str:
    """What the --yes call matches a job by: the trace's content, or the command and the folder it ran in
    (only the hash is stored)."""
    h = hashlib.sha1()
    if is_cmd:
        h.update(("cmd\0%s\0%s" % (os.getcwd(), "\0".join(inputs))).encode("utf-8", "replace"))
    else:
        with open(inputs[0], "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def _review_job(args, is_cmd: bool) -> Optional[Path]:
    """With --yes: the job whose script.md to render (--out, a job folder given, or the newest repro job made
    from the same trace or command); None when there is none yet (this call writes the script)."""
    from .job import ledger
    if args.out:
        o = Path(args.out)
        return o if (o / "report.json").is_file() else None
    if not is_cmd and len(args.input) == 1 and Path(args.input[0]).is_dir():
        o = Path(args.input[0])
        if not (o / "report.json").is_file():
            raise ShowtimeError("%s is not a job showtime repro wrote (no report.json)" % o,
                                hint="pass the trace.zip or the test command first: that call writes script.md")
        return o
    if not is_cmd:
        from . import repro as rp
        rp.open_trace(Path(args.input[0])).close()
    key = _input_key(args.input, is_cmd)
    for j in ledger.list_jobs():
        try:
            if json.loads((j / "report.json").read_text(encoding="utf-8")).get("key") == key:
                return j
        except (OSError, ValueError):
            continue
    return None


def _shown_path(p: Path) -> str:
    """A trace's path as the end card shows it: relative to the current folder when inside it, else its name."""
    try:
        rel = os.path.relpath(str(p.resolve()), os.getcwd())
    except ValueError:                                      # another drive on Windows
        rel = p.name
    if rel.startswith(".."):
        rel = p.name
    return '"%s"' % rel if " " in rel else rel


def _default_voice(name) -> str:
    if name:
        return name
    env = os.environ.get("SHOWTIME_VOICE") or ""
    return env if env[:1] in ("a", "b") else "af_heart"      # the narration is English


def _voice(proj: Path, lines: dict, voice: str, quiet: bool) -> dict:
    """`showtime voice script` on one line per scene -> {scene id: {"dur", "file", "speech": (a, b)}}."""
    vdir = proj / "voice"
    vdir.mkdir(parents=True, exist_ok=True)
    md = "---\nvoice: %s\ngap: 0.3\ntail: 0.3\n---\n" % voice + "".join(
        "## %s\n%s\n\n" % (sid, text.replace("\n", " ")) for sid, text in lines.items())
    (vdir / "narration.md").write_text(md, encoding="utf-8")
    launcher = Path(__file__).resolve().parent / "launcher.py"
    sys.stdout.flush()
    cp = subprocess.run([sys.executable, str(launcher), "voice", "script", str(vdir / "narration.md"), "-o", str(vdir),
                         "--no-readback"], stdout=subprocess.DEVNULL if quiet else sys.stderr, stderr=subprocess.PIPE,
                        encoding="utf-8", errors="replace")
    if cp.returncode != 0 or not (vdir / "timeline.json").is_file():
        last = [x for x in (cp.stderr or "").splitlines() if x.strip()]
        raise ShowtimeError("the narration could not be made%s" % (": " + last[-1].strip()[:200] if last else ""),
                            why="showtime voice script failed on the narration (project/voice/narration.md)",
                            hint="showtime doctor checks the voice (showtime setup installs it), or pass --no-voice "
                                 "for captions only")
    tl = json.loads((vdir / "timeline.json").read_text(encoding="utf-8"))
    out = {}
    for ln in tl.get("lines") or []:
        a, b = float(ln.get("start", 0)), float(ln.get("end", 0))
        out[ln["id"]] = {"dur": float(ln.get("duration", b - a)), "file": "voice/" + ln["file"],
                         "speech": (float(ln.get("speech_start", a)) - a, float(ln.get("speech_end", b)) - a)}
    return out


def cmd_repro(args: argparse.Namespace) -> int:
    from . import repro as rp
    if not args.input and not (args.yes and args.out):
        raise ShowtimeError("no trace or test command given",
                            hint="showtime repro test-results/<test>/trace.zip, or showtime repro -- npx playwright test")
    say = (lambda *a: None) if args.json else (lambda *a: print(*a, file=sys.stderr))
    redact = rp.Redactor(args.redact, show_emails=args.show_emails)
    is_cmd = bool(args.input) and _is_command(args.input)
    if args.yes:
        job = _review_job(args, is_cmd)
        if job is not None:
            return _render(job, args, redact, say)
    return _write_script(args, is_cmd, redact, say)


def _write_script(args, is_cmd: bool, redact, say) -> int:
    """The first call: parse the trace (running the command first), make the job, keep the screenshots the film
    can use, write report.json and script.md, and stop. Nothing is left behind when it fails, and the raw
    traces of a run are deleted (unless --keep-trace)."""
    from . import repro as rp
    tmp = None
    run = None
    cmd = list(args.input) if is_cmd else None
    try:
        if cmd is not None:
            tmp = Path(tempfile.mkdtemp(prefix="showtime-repro-"))
            say("running %s (tracing on for failing tests)" % redact(" ".join(cmd)))
            run = rp.run_and_find(cmd, tmp / "test-results", timeout=args.timeout)
            if not run["trace"]:
                if run["traces"]:
                    raise ShowtimeError("no test failed (%d trace%s written, exit code %d), so there is nothing to "
                                        "report" % (len(run["traces"]), "" if len(run["traces"]) == 1 else "s",
                                                    run["rc"]),
                                        hint="run the test that fails, or pass its trace: showtime repro <trace.zip>")
                if run["runner"] and run["rc"] == 0:
                    raise ShowtimeError("no test failed (exit code 0): tracing was on for failing tests, and no trace "
                                        "was written", hint="run the test that fails, or pass its trace.zip")
                raise ShowtimeError("the command wrote no trace.zip (exit code %d)" % run["rc"],
                                    why="showtime adds --trace retain-on-failure (playwright test) or --tracing "
                                        "retain-on-failure (pytest) when it recognizes the runner%s, and looks only "
                                        "where it told the runner to write" % ("" if run["runner"] else
                                                                              "; it did not recognize this one"),
                                    hint="run it as `npx playwright test ...` or `pytest ...`, or turn tracing on "
                                         "yourself and pass the trace.zip")
            trace = Path(run["trace"])
            if len(run["failing"]) > 1:
                say("note: %d tests failed; filming the first" % len(run["failing"]))
        else:
            trace = Path(args.input[0])
            if trace.is_dir():
                raise ShowtimeError("%s is a folder" % trace.name,
                                    hint="pass a trace.zip, a test command after --, or with --yes a repro job folder")
            rp.open_trace(trace).close()                     # a clear error before anything is made
        rep = rp.parse(trace, redact, label=trace.parent.name, show_typed=args.show_typed)
        if rep["failure"] is None:
            raise ShowtimeError("the trace records no failure: every step passed",
                                hint="showtime repro films a failing test; pass the trace of one that failed")
        rerun = rp.rerun_command(rep, cmd, redact)
        key = _input_key(args.input, is_cmd)
        goal = "showtime repro: %s" % (" ".join(cmd) if cmd else args.input[0])[:200]
        job, made = _job(args.out, redact(goal), redact)
        try:
            rp.keep_shots(trace, rep, job / "shots")
            in_tmp = tmp is not None and _inside(trace, tmp)
            viewer = ""
            if args.keep_trace and tmp is not None:
                kept = job / "work" / "test-results"
                shutil.copytree(str(tmp / "test-results"), str(kept))
                if in_tmp:
                    viewer = _shown_path(kept / trace.relative_to(tmp / "test-results"))
            elif not in_tmp:
                viewer = _shown_path(trace)
            viewer = redact(rp.viewer_command(rep, viewer)) if viewer else ""
            data = {"generator": "showtime repro", "schema": 1, "key": key, "report": rep, "rerun": rerun,
                    "viewer": viewer}
            (job / "report.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
            script = job / "script.md"
            script.write_text(rp.write_script(rep, rerun, viewer), encoding="utf-8")
        except BaseException:
            if made:
                shutil.rmtree(str(job), ignore_errors=True)
            else:
                for name in ("shots", "work/test-results", "report.json", "script.md"):
                    q = job / name
                    shutil.rmtree(str(q), ignore_errors=True) if q.is_dir() else q.unlink() if q.exists() else None
            raise
    finally:
        if tmp is not None:
            shutil.rmtree(str(tmp), ignore_errors=True)
    again = "showtime repro --yes %s" % shlex.quote(str(job))
    res = {"job": str(job), "script": str(script), "rendered": False, "steps": len(rep["steps"]),
           "failed_step": rep["failure"].get("step"), "test": rep["test"], "masked_values": rep["privacy"]["masked_values"],
           "next": "read %s, then rerun with --yes (%s)" % (script, again),
           "privacy": dict(rep["privacy"], screenshots="as captured", raw_trace="kept" if args.keep_trace and tmp
                           else "deleted" if tmp else "not copied"),
           "run": {"rc": run["rc"], "runner": run["runner"], "failing": len(run["failing"])} if run else None}
    if args.json:
        print_json(res)
        return 0
    say("%d steps, fails at step %s; %d typed value%s hidden; %s" % (
        len(rep["steps"]), rep["failure"].get("step") or "?", rep["privacy"]["masked_values"],
        "" if rep["privacy"]["masked_values"] == 1 else "s", SCREENSHOTS))
    if args.keep_trace and tmp is not None:
        say("kept the run's raw traces in %s: they are not filtered (they hold what was typed)" % (job / "work"))
    say("wrote %s: every line the film will show or speak. Nothing was rendered." % script)
    print("read %s, then rerun with --yes: %s" % (script, again))
    return 0


def _inside(p: Path, folder: Path) -> bool:
    try:
        p.resolve().relative_to(folder.resolve())
        return True
    except ValueError:
        return False


def _render(job: Path, args, redact, say) -> int:
    """The --yes call: the report as script.md leaves it (every line filtered again), then narration, the
    project, steps.json, repro.srt and repro.md, then check, render and qa."""
    from . import repro as rp
    from .cli_release import _render_pr
    from .job import ledger
    t_start = time.time()
    script = job / "script.md"
    if not script.is_file():
        raise ShowtimeError("%s has no script.md" % job, hint="run showtime repro without --yes first: it writes it")
    data = json.loads((job / "report.json").read_text(encoding="utf-8"))
    rep, rerun, viewer = rp.apply_script(data["report"], data.get("rerun") or "", data.get("viewer") or "",
                                         rp.read_script(script.read_text(encoding="utf-8", errors="replace")), redact)
    say("using %s as you left it; %s" % (script, SCREENSHOTS))
    proj = job / "project"

    def make_plan(speech=None):
        p = rp.plan(rep, rerun=rerun, speech=speech)
        p["viewer"] = viewer
        return p
    p = make_plan()
    lines = rp.narration(rep, p)
    voice, spans, tracks = {}, None, []
    if not args.no_voice and lines:
        name = _default_voice(args.voice)
        say("narrating %d lines with %s" % (len(lines), name))
        for _ in range(3):                                   # the voice can change the plan (a longer line, a skip)
            voice = _voice(proj, lines, name, args.json)
            p = make_plan({k: v["dur"] for k, v in voice.items()})
            again = rp.narration(rep, p)
            if again == lines:
                break
            lines = again
        spans, tracks = {}, []
        for sc in p["scenes"]:
            v = voice.get(sc["id"])
            if v:
                at = round(sc["start"] + rp.VOICE_PAD, 3)
                tracks.append({"id": "vo-%s" % sc["id"], "kind": "voice", "file": v["file"], "start": at})
                spans[sc["id"]] = (at + v["speech"][0], at + v["speech"][1])
    res = rp.write_project(proj, rep, p, job, size=args.size, voice_tracks=tracks, force=True,
                           music=args.music, fetch=True, cut_sounds=args.cut_sounds)
    steps = rp.steps_json(rep, p)
    (job / "steps.json").write_text(json.dumps(steps, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    srt = rp.build_srt(p, lines, spans)
    out = {"job": str(job), "project": res["project"], "duration": p["duration"], "scenes": len(p["scenes"]),
           "steps": len(rep["steps"]), "shown_steps": p["shown_steps"], "skipped_steps": len(p["skipped_steps"]),
           "failed_step": (rep["failure"] or {}).get("step"), "test": rep["test"], "steps_json": str(job / "steps.json"),
           "voice": None if args.no_voice else _default_voice(args.voice),
           "masked_values": rep["privacy"]["masked_values"], "rendered": not args.no_render,
           "privacy": dict(rep["privacy"], screenshots="as captured")}
    say("wrote %s: %d scenes, %.1f s; %d of %d steps shown%s, fails at step %s" % (
        proj, len(p["scenes"]), p["duration"], p["shown_steps"], len(rep["steps"]),
        " (%d passing summed up)" % len(p["skipped_steps"]) if p["skipped_steps"] else "",
        (rep["failure"] or {}).get("step") or "?"))
    from . import bed

    def credit_line() -> str:
        item = res["bed"].get("credit") or {}
        return (item.get("attribution") or "") if item.get("attribution_required") else ""
    out["music"] = res["bed"]["label"]
    md_path = job / "repro.md"
    if args.no_render:
        (job / "repro.srt").write_text(srt, encoding="utf-8")
        md_path.write_text(rp.markdown(rep, p, "repro.mp4", credit_line()), encoding="utf-8")
        out.update({"srt": str(job / "repro.srt"), "markdown": str(md_path)})
        if res["bed"]["how"] == "catalog":
            out["music_note"] = ("the music is fetched when you render (showtime audio music fetch %s now to have it "
                                 "cached); %s" % (res["bed"]["id"], "its credit is in repro.md" if credit_line() else
                                                  "no credit is required"))
        if args.json:
            print_json(out)
        else:
            if out.get("music_note"):
                say("music: %s" % out["music_note"])
            print("next: showtime check %s && showtime render %s -o %s" % (proj, proj, job / "repro.mp4"))
        return 0
    bed.ensure(proj / "audio" / "mix.json", res["bed"])
    out["music"] = res["bed"]["label"]
    video = _render_pr(proj, job / "repro.mp4", preview=args.preview, quiet=args.json)
    kind = "preview" if args.preview else "final"
    ledger.note(job, outputs=["%s=%s" % (kind, video)], event="repro: %s is the latest %s" % (video.name, kind))
    srt_path = video.with_suffix(".srt")
    srt_path.write_text(srt, encoding="utf-8")
    md_path.write_text(rp.markdown(rep, p, video.name, credit_line()), encoding="utf-8")
    owed = bed.credit_report(video, res["bed"])
    if owed["credits"]:
        out.update({"credits": owed["credits"], "share": owed["share"], "credit_notes": owed["notes"]})
    poster = video.with_name(video.stem + ".poster.jpg")
    if not poster.is_file():
        from .deliver.poster import extract_frame
        extract_frame(video, float(res["poster_at"]), poster)
    from .qa import video as qa
    verdict = qa.run(video, project=str(proj), quiet=True, sheet=False)
    if not args.keep_work:
        from .pr_video import remove_work
        remove_work(video)
        shutil.rmtree(str(proj / "work"), ignore_errors=True)     # check's report (paths on this machine)
    elapsed = round(time.time() - t_start, 1)
    out.update({"video": str(video), "srt": str(srt_path), "poster": str(poster), "markdown": str(md_path),
                "qa": {"verdict": verdict["verdict"], "summary": verdict.get("summary"),
                       "findings": [{"rule": f.get("rule"), "level": f.get("severity"), "message": f.get("message")}
                                    for f in verdict.get("findings", []) if f.get("severity") in ("FAIL", "WARN")]},
                "seconds": elapsed})
    if args.json:
        print_json(out)
    else:
        print("video   %s (%.1f s)" % (video, p["duration"]))
        print("steps   %s" % (job / "steps.json"))
        print("report  %s   (paste into the issue, then drag %s onto its comment line)" % (md_path, video.name))
        if owed["credits"]:
            print("credits %s   (the music needs its credit in the post: it is in repro.md)" % owed["credits"])
        for n in owed["notes"]:
            say("note: " + n)
        print("qa      %s%s" % (verdict["verdict"], "".join("\n  %s %s" % (f["level"], f["message"]) for f in out["qa"]["findings"][:6])))
        say("watch %s before you post it: %s" % (video.name, SCREENSHOTS))
    return 1 if verdict["verdict"] == "FAIL" else 0

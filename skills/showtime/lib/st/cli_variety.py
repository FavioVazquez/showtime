"""`showtime history` (the local look history) and `showtime reference` (a reference's grammar)."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, Optional

from .common import ShowtimeError, print_json, slugify

COMMANDS = {
    "history": "The looks of your recent videos (local only): list, check a project for repeats, clear, off/on",
    "reference": "Break a reference video into its grammar (pace, shots, palette, motion, sound) for the plan",
    "signature": "The look signatures new page projects start in: list them, or swap a project's",
}

_F = argparse.RawDescriptionHelpFormatter


def register(sub: argparse._SubParsersAction) -> None:
    h = sub.add_parser("history", help=COMMANDS["history"], formatter_class=_F, description=(
        "What your recent videos looked like, so the next one does not look the same.\n\n"
        "Each finished job's look (template, theme, palette, type pair, transitions, camera moves, music,\n"
        "structure, tone; read from its project files, brand.json and audio mix) is recorded when `showtime qa`\n"
        "passes on its latest final. `showtime check` and `showtime history check` compare a project with the\n"
        "last five jobs and name two concrete alternatives for every repeat.\n\n"
        "The history is a file on this machine (<SHOWTIME_HOME>/history/looks.json); showtime never uploads\n"
        "it. Opt out with `showtime history off` or SHOWTIME_HISTORY=off; `showtime history clear` deletes it.\n\n"
        "  list    the recent looks (default)\n"
        "  check   compare a project or job with the recent looks\n"
        "  add     record a job's look now (qa does it on a passing final)\n"
        "  clear   delete the history (or one job's entry with --job)\n"
        "  off/on  stop or resume recording (the file stays until cleared)"),
        epilog="Examples:\n"
               "  showtime history\n"
               "  showtime history check my-video            # a project folder\n"
               "  showtime history check launch --json       # a job: its project, brand kit and plan\n"
               "  showtime history add launch\n"
               "  showtime history clear --job launch-20260929-101500\n"
               "  showtime history off")
    hs = h.add_subparsers(dest="history_cmd", metavar="<subcommand>")
    h.add_argument("-n", type=int, default=10, help="how many recent looks to list (default 10)")
    h.add_argument("--json", action="store_true", help="print JSON")
    h.set_defaults(func=cmd_history_list)
    p = hs.add_parser("list", help="the recent looks", formatter_class=_F)
    p.add_argument("-n", type=int, default=10, help="how many (default 10)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_history_list)
    p = hs.add_parser("check", help="compare a project or job with the last five looks", formatter_class=_F,
                      description="Compare a look with the last five recorded jobs (itself excluded). Every repeat "
                                  "comes with two alternatives from what showtime has. Exit code 0 (the repeats are "
                                  "advice); --strict exits 1 when something strong repeats.",
                      epilog="Examples:\n  showtime history check my-video\n  showtime history check launch --json")
    p.add_argument("target", nargs="?", help="a project folder (showtime.json) or a job (default: the current job)")
    p.add_argument("-n", type=int, default=5, help="how many recent jobs to compare with (default 5)")
    p.add_argument("--strict", action="store_true", help="exit 1 when a strong aspect repeats")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_history_check)
    p = hs.add_parser("add", help="record a job's look now", formatter_class=_F)
    p.add_argument("job", nargs="?", help="job folder or name (default: the current job)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_history_add)
    p = hs.add_parser("clear", help="delete the history (or one job's entry)", formatter_class=_F)
    p.add_argument("--job", help="remove only this job's entry (name or folder)")
    p.set_defaults(func=cmd_history_clear)
    p = hs.add_parser("off", help="stop recording looks")
    p.set_defaults(func=lambda a: _onoff(False))
    p = hs.add_parser("on", help="resume recording looks")
    p.set_defaults(func=lambda a: _onoff(True))

    r = sub.add_parser("reference", help=COMMANDS["reference"], formatter_class=_F, description=(
        "Study a reference video's grammar, never its content.\n\n"
        "Measures, locally: scene changes (hard cuts by ffmpeg scene detection, composition changes, the\n"
        "motion bursts of pushes and whips), shot lengths, pace (changes per 10 s), how scenes change (cut,\n"
        "fast handoff, continuous move), palette, brightness, motion energy and the\n"
        "camera verb per shot, a text-on-screen estimate with a rough type scale, the loudness curve,\n"
        "silence and tempo. Writes into <job>/references/<name>/: reference.md (with the brief the\n"
        "storyboard uses: borrow pace, type scale, transitions; never its words, logos or shots),\n"
        "reference.json, sheet.jpg (1 frame per second), shots.jpg and fingerprint.npz. It also puts\n"
        "\"Style reference: <title>\" in the job's credits.txt and share.txt, and from then on `showtime qa`\n"
        "fails a render that copies the reference's pictures (near-copy guard).\n\n"
        "Local files are the normal input. A URL works only as a direct link to a video file (fetched with\n"
        "the downloader showtime uses for media); pages and streaming sites are not fetched. Use references\n"
        "you may watch and keep; the site's terms apply to downloading.\n\n"
        "  reference <video|url>      analyse (into the current job, --job, or -o)\n"
        "  reference check [video]    near-copy guard now: a video (default: the job's latest final) against\n"
        "                             the job's references, or --against <reference folder or video>\n"
        "  reference diff [job|video] measure a render like the reference and report every KEEP item of\n"
        "                             its spec (cuts, shot lengths, moves and easing, palette, layout, beat\n"
        "                             and sound hits) as ok or OFF, with frame numbers\n"
        "  reference credit [job]     put the credit line(s) back into credits.txt and share.txt\n"
        "  reference list [job]       the job's references"),
        epilog="Examples:\n"
               "  showtime reference ~/Movies/favourite-launch.mp4 --job launch --for 30\n"
               "  showtime reference https://example.org/media/clip.mp4 --title \"Example clip\" --job launch\n"
               "  showtime reference check launch\n"
               "  showtime reference check final.mp4 --against showtime-out/launch-.../references/clip\n"
               "  showtime reference diff launch\n"
               "  showtime reference credit launch")
    r.add_argument("items", nargs="+", metavar="<video|url|check|diff|credit|list>", help="what to analyse, or a subcommand")
    r.add_argument("--job", help="job to attach it to (default: the job the current folder is in)")
    r.add_argument("-o", "--out", help="output folder (default: <job>/references/<name>/)")
    r.add_argument("--title", help="title for the credit line (default: the file name)")
    r.add_argument("--for", dest="target", type=float, metavar="SECONDS",
                   help="length of the video you are making: the brief turns pace into a scene count")
    r.add_argument("--max-seconds", type=float, default=600.0, help="analyse at most this much (default 600)")
    r.add_argument("--against", help="check: a reference folder, reference.json or video")
    r.add_argument("--no-credit", action="store_true", help="do not write the credit line (you credit it yourself)")
    r.add_argument("--strict", action="store_true", help="diff: exit 1 when a KEEP item is off")
    r.add_argument("--json", action="store_true", help="print JSON")
    r.set_defaults(func=cmd_reference)

    g = sub.add_parser("signature", help=COMMANDS["signature"], formatter_class=_F, description=(
        "Look signatures: whole looks a new page project starts in, like a film's score. Each is a palette\n"
        "(ground, ink, muted, surfaces, two accents, every text colour at accessible contrast), a type pair,\n"
        "a motion feel and a ground treatment (how much key light, grid and vignette).\n\n"
        "`showtime new` on dom, launch, short or data picks one away from the looks of the last projects\n"
        "created here and the last videos finished here (the look history), seeded by the folder name\n"
        "(--look-seed), and says which. A brand kit or a job's style reference wins over it; `--look\n"
        "template` keeps the template's own look. The page gets a <style id=\"st-look\"> block of theme\n"
        "tokens; edit it, or swap it here.\n\n"
        "  list                 the signatures (default)\n"
        "  apply <project> <id> swap the project's look: an id, next (the next pick in rotation) or\n"
        "                       template (take the signature out)"),
        epilog="Examples:\n"
               "  showtime signature\n"
               "  showtime signature apply my-video tidewater\n"
               "  showtime signature apply my-video next\n"
               "  showtime signature apply my-video template")
    gs = g.add_subparsers(dest="signature_cmd", metavar="<subcommand>")
    g.add_argument("--json", action="store_true", help="print JSON")
    g.set_defaults(func=cmd_signature_list)
    p = gs.add_parser("list", help="the look signatures", formatter_class=_F)
    p.add_argument("--template", help="only the ones this template can wear (dom, launch, short, data)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_signature_list)
    p = gs.add_parser("apply", help="swap a project's look signature", formatter_class=_F,
                      epilog="Examples:\n  showtime signature apply my-video cobalt\n  showtime signature apply my-video next")
    p.add_argument("project", help="project folder (showtime.json + index.html)")
    p.add_argument("id", help="a signature id, next, or template")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_signature_apply)


# ------------------------------------------------------------------ look signatures

def cmd_signature_list(args: argparse.Namespace) -> int:
    from .variety import signatures as sigs
    tpl = getattr(args, "template", None)
    rows = sigs.compatible(tpl) if tpl else sigs.catalog()
    if tpl and not rows:
        raise ShowtimeError("the %s template keeps its own look" % tpl, hint="look signatures dress: %s" % ", ".join(sigs.TEMPLATES))
    recent = [x["id"] for x in sigs.recent_picks()]
    if getattr(args, "json", False):
        print_json({"signatures": rows, "recent_picks": recent, "templates": {k: list(v) for k, v in sigs.TEMPLATES.items()}})
        return 0
    print("look signatures (showtime new <template> <dir> --look <id>; showtime signature apply <project> <id>):")
    for r in rows:
        print("  %-10s %-5s %s%s" % (r["id"], r["polarity"], sigs.describe(r), "  [recent]" if r["id"] in recent else ""))
    print("templates: %s (data: light grounds only); film, tutorial and series keep their own looks" % ", ".join(sigs.TEMPLATES))
    return 0


def cmd_signature_apply(args: argparse.Namespace) -> int:
    from .variety import signatures as sigs
    res = sigs.set_project(Path(args.project), args.id)
    if getattr(args, "json", False):
        print_json(res)
        return 0
    prev = " (was %s)" % res["previous"] if res.get("previous") else ""
    print("look: %s%s" % (res["describe"], prev))
    return 0


# ------------------------------------------------------------------ history

def _onoff(on: bool) -> int:
    from .variety import history
    history.set_enabled(on)
    ok, why = history.enabled()
    if on and not ok:
        print("look history: still off (%s)" % why)
    else:
        print("look history: %s (%s)" % ("on" if on else "off", history.folder()))
    return 0


def cmd_history_list(args: argparse.Namespace) -> int:
    from .variety import history, look
    looks = history.recent(max(1, int(getattr(args, "n", 10) or 10)))
    ok, why = history.enabled()
    if getattr(args, "json", False):
        print_json({"enabled": ok, "file": str(history.file()), "looks": looks})
        return 0
    state = "on" if ok else "off (%s)" % why
    print("look history: %s, %d recorded, %s (local only)" % (state, len(history.load()), history.file()))
    if not looks:
        print("  (nothing yet: a job is recorded when `showtime qa` passes on its final)")
        return 0
    for x in looks:
        print("  %-34s %s" % ((x.get("job") or "?")[:34], (x.get("at") or "")[:16]))
        print("      %s" % look.summary(x))
    used: Dict[str, Dict[str, int]] = {}
    for x in looks[:history.RECENT]:
        for k in ("theme", "template", "tone"):
            if x.get(k):
                used.setdefault(k, {})[x[k]] = used.setdefault(k, {}).get(x[k], 0) + 1
        if x.get("type"):
            used.setdefault("type", {})[x["type"][0]] = used.setdefault("type", {}).get(x["type"][0], 0) + 1
        tr = x.get("transitions") or {}
        if tr:
            p = sorted(tr.items(), key=lambda kv: -kv[1])[0][0]
            used.setdefault("transitions", {})[p] = used.setdefault("transitions", {}).get(p, 0) + 1
        for m in x.get("music") or []:
            used.setdefault("music", {})[m.get("ref")] = used.setdefault("music", {}).get(m.get("ref"), 0) + 1
    if used:
        print("  recently used (pick something else for the next job):")
        for k, v in used.items():
            print("    %-12s %s" % (k, ", ".join("%s x%d" % kv for kv in sorted(v.items(), key=lambda kv: -kv[1]))))
    return 0


def look_for(target: Optional[str]) -> Dict[str, Any]:
    """The look of a project folder (plus its job's brand and tone) or of a job."""
    from .job import ledger
    from .variety import look
    if target:
        p = Path(target).expanduser()
        if p.is_file() and p.name == "showtime.json":
            p = p.parent
        if p.is_dir() and (p / "showtime.json").is_file():
            lk = look.project_look(p)
            job = ledger.enclosing_job(p)
            if job is not None:
                jl = look.job_look(job)
                for k in ("brand", "tone"):
                    if jl.get(k) and not lk.get(k):
                        lk[k] = jl[k]
                lk["job"], lk["job_path"] = jl["job"], jl["job_path"]
            else:
                lk["job"] = p.name
            return lk
    job = ledger.resolve(target)
    return look.job_look(job)


def cmd_history_check(args: argparse.Namespace) -> int:
    from .variety import history
    lk = look_for(args.target)
    res = history.check(lk, n=max(1, args.n))
    if args.json:
        print(history.to_json(res))
    else:
        print(history.format_text(res))
    return 1 if (args.strict and res.get("level") == "warning") else 0


def cmd_history_add(args: argparse.Namespace) -> int:
    from .job import ledger
    from .variety import history, look
    job = ledger.resolve(args.job)
    ok, why = history.enabled()
    if not ok:
        raise ShowtimeError("the look history is off (%s)" % why, hint="showtime history on")
    rec = history.record(look.job_look(job))
    if args.json:
        print_json(rec)
    else:
        print("recorded %s: %s" % (job.name, look.summary(rec or {})))
    return 0


def cmd_history_clear(args: argparse.Namespace) -> int:
    from .variety import history
    n = history.clear(args.job)
    print("removed %d look(s) from %s" % (n, history.file()))
    return 0


# ------------------------------------------------------------------ reference

def _out_dir(args: argparse.Namespace, name: str) -> Any:
    from .common import output_dir
    from .job import ledger
    if args.out:
        return Path(args.out).expanduser(), (ledger.resolve(args.job) if args.job else ledger.enclosing_job(Path(args.out)))
    job = ledger.resolve(args.job) if args.job else ledger.enclosing_job(Path.cwd())
    if job is None:
        return output_dir("%s-reference" % name), None
    base = job / "references" / slugify(name, default="reference")
    d, k = base, 2
    while d.exists():
        d = base.with_name("%s-%d" % (base.name, k))
        k += 1
    return d, job


def cmd_reference(args: argparse.Namespace) -> int:
    items = list(args.items)
    head = items[0]
    if head in ("check", "diff", "credit", "list") and not Path(head).exists():
        return {"check": _ref_check, "diff": _ref_diff, "credit": _ref_credit, "list": _ref_list}[head](args, items[1:])
    if len(items) > 1:
        raise ShowtimeError("one reference at a time (got %d)" % len(items),
                            hint="run `showtime reference <video>` once per reference")
    from .variety import guard, reference
    src = head
    name = args.title or (reference._title_of(src, Path(src)) if reference.is_url(src) else Path(src).stem)
    out, job = _out_dir(args, name)
    rep = reference.analyze(src, out, title=args.title, target=args.target, max_seconds=args.max_seconds)
    credit = None
    if job is not None:
        from .job import ledger
        try:
            ledger.note(job, pointers=["reference=%s" % out], event="style reference %s: %s" % (rep["title"], out))
        except Exception:  # noqa: BLE001 - the ledger is a convenience
            pass
        if not args.no_credit:
            credit = guard.ensure_credit(job, rep["credit"])
    if args.json:
        print_json({"out_dir": str(out), "job": str(job) if job else None, "reference_md": rep["reference_md"],
                    "sheet": rep.get("sheet"), "shots_sheet": rep.get("shots_sheet"), "credit": rep["credit"],
                    "credit_written": credit, "pace": rep["pace"], "shot_lengths": rep["shot_lengths"],
                    "palette": rep["palette"], "palette_roles": rep.get("palette_roles"), "layout": rep.get("layout"),
                    "style_css": rep.get("style_css"), "camera": rep["camera"], "motion": rep["motion"],
                    "text": rep["text"], "sound": {k: v for k, v in (rep.get("sound") or {}).items()
                                                   if k != "level_db_per_half_s"}, "brief": rep["brief"]})
        return 0
    sl = rep.get("shot_lengths") or {}
    snd = rep.get("sound") or {}
    print("reference: %s (%s, %s)" % (rep["title"], reference._fmt(rep["analysed_seconds"]), rep["aspect"]))
    nc = rep["pace"]["changes"]
    print("  shots %d (%d scene change%s, %d hard cut%s), %.1f changes per 10 s, median shot %.1f s (min %.1f, max %.1f)" % (
        len(rep["shots"]), nc, "" if nc == 1 else "s", rep["pace"]["hard_cuts"], "" if rep["pace"]["hard_cuts"] == 1 else "s",
        rep["pace"]["per_10s"],
        sl.get("median") or 0, sl.get("min") or 0, sl.get("max") or 0))
    print("  camera %s; motion %s" % (", ".join("%s %s" % (k, reference._pct(v)) for k, v in list(rep["camera"].items())[:3]),
                                      ", ".join("%s %s" % (k, reference._pct(v)) for k, v in list(rep["motion"].items())[:3])))
    roles = rep.get("palette_roles") or {}
    print("  palette %s%s" % (" ".join(c["hex"] for c in rep["palette"][:6]),
                              " (%s)" % ", ".join("%s %s" % (k, roles[k]) for k in ("ground", "ink", "accent") if roles.get(k))
                              if roles else ""))
    lay = rep.get("layout") or {}
    if lay:
        print("  layout %s, margin %d px at 1920, type sizes %s px at 1080 (estimate)" % (
            lay["align"], lay["margin_px_1920"], " / ".join(str(x["px_1080"]) for x in lay.get("sizes") or []) or "?"))
    if snd.get("present"):
        print("  sound %s LUFS, silence %s%s" % (snd.get("lufs", "?"), reference._pct(snd.get("silence_share")),
                                               ", ~%g BPM" % round(float(snd["bpm"])) if snd.get("bpm") else ""))
    print("  brief   %s (section \"Brief for the storyboard\")" % rep["reference_md"])
    if rep.get("sheet"):
        print("  sheet   %s" % rep["sheet"])
    if rep.get("shots_sheet"):
        print("  shots   %s" % rep["shots_sheet"])
    if rep.get("style_css"):
        print("  style   %s (link after the theme; `showtime new ... --job` does it)" % rep["style_css"])
    if job is None:
        print("  note: not attached to a job; pass --job <job> so qa guards against copies and credits it")
    elif credit is not None:
        print("  credit  \"%s\" in credits.txt and share.txt" % rep["credit"])
    print("  same style: carry over its pace, palette, type, layout, transitions and sound shape; never its words, "
          "footage, shots or music (reference.md)")
    return 0


def _ref_list(args: argparse.Namespace, rest: list) -> int:
    from .job import ledger
    from .variety import guard
    job = ledger.resolve(rest[0] if rest else args.job)
    refs = guard.job_references(job)
    if args.json:
        print_json(refs)
        return 0
    if not refs:
        print("no references in %s (add one: showtime reference <video> --job %s)" % (job.name, job.name))
    for r in refs:
        print("  %s  %s" % (r.get("title"), r.get("dir")))
    return 0


def _ref_credit(args: argparse.Namespace, rest: list) -> int:
    from .job import ledger
    from .variety import guard
    job = ledger.resolve(rest[0] if rest else args.job)
    refs = guard.job_references(job)
    if not refs:
        raise ShowtimeError("no references in %s" % job.name, hint="showtime reference <video> --job %s" % job.name)
    for r in refs:
        if r.get("credit"):
            res = guard.ensure_credit(job, r["credit"])
            print("%s: %s" % (r["credit"], "added to " + ", ".join(Path(c).name for c in res["changed"])
                              if res["changed"] else "already there"))
    return 0


def _ref_diff(args: argparse.Namespace, rest: list) -> int:
    import json as _json
    from .job import ledger
    from .variety import guard, reference, spec
    target = rest[0] if rest else args.job
    job = None
    if target and Path(target).expanduser().is_file():
        video = Path(target).expanduser().resolve()
        job = ledger.resolve(args.job) if args.job else ledger.enclosing_job(video)
    else:
        job = ledger.resolve(target)
        video, _kind = ledger.latest_video(job)
        if video is None:
            raise ShowtimeError("%s has no rendered video yet" % job.name, hint="render first, or pass a video file")
    if args.against:
        d = Path(args.against).expanduser()
        d = d.parent if d.is_file() else d
    else:
        refs = guard.job_references(job) if job else []
        if not refs:
            raise ShowtimeError("no reference to diff against", hint="pass --against <reference folder>, or analyse "
                                                                    "one: showtime reference <video> --job <job>")
        d = Path(refs[-1]["dir"])
    meta = _json.loads((d / "reference.json").read_text(encoding="utf-8")) if (d / "reference.json").is_file() else {}
    if not meta.get("spec"):
        raise ShowtimeError("%s has no spec (analysed by an older showtime)" % d,
                            hint="analyse it again: showtime reference <video> --job <job>")
    rep = reference.measure(video, max_seconds=args.max_seconds, sheet_dir=None, title=video.stem)
    rep.pop("_sheet", None)
    res = spec.diff(meta["spec"], spec.build(rep))
    if args.json:
        print_json({"video": str(video), "reference": meta.get("title"), "reference_dir": str(d), **res})
    else:
        print(spec.diff_text(res, video.name, meta.get("title") or d.name))
    return 1 if (args.strict and not res["ok"]) else 0


def _ref_check(args: argparse.Namespace, rest: list) -> int:
    from .job import ledger
    from .variety import guard
    video: Optional[Path] = None
    job = None
    target = rest[0] if rest else args.job
    if target and Path(target).expanduser().is_file():
        video = Path(target).expanduser().resolve()
        job = ledger.resolve(args.job) if args.job else ledger.enclosing_job(video)
    else:
        job = ledger.resolve(target)
        video, _kind = ledger.latest_video(job)
        if video is None:
            raise ShowtimeError("%s has no rendered video yet" % job.name, hint="render first, or pass a video file")
    if args.against:
        a = Path(args.against).expanduser()
        if a.is_file() and a.name == "reference.json":
            a = a.parent
        if a.is_dir():
            if not (a / "fingerprint.npz").is_file():
                raise ShowtimeError("%s has no fingerprint.npz" % a, hint="analyse it again: showtime reference <video>")
            import json as _json
            meta = _json.loads((a / "reference.json").read_text(encoding="utf-8")) if (a / "reference.json").is_file() else {}
            rv = next((v for v in (meta.get("kept_copy"), meta.get("file")) if v and Path(v).is_file()), None)
            refs = [{"title": meta.get("title") or a.name, "dir": str(a), "fingerprint": str(a / "fingerprint.npz"),
                     "video": rv}]
            results = guard.check_video(video, refs)
        elif a.is_file():
            res = guard.compare(guard.fingerprint_video(video), guard.fingerprint_video(a, fps=guard.REF_FPS),
                                render_video=video, ref_video=a)
            res["reference"] = a.name
            results = [res]
        else:
            raise ShowtimeError("not found: %s" % a)
    else:
        refs = guard.job_references(job) if job else []
        if not refs:
            raise ShowtimeError("no references to compare with", hint="pass --against <reference folder or video>, "
                                                                        "or analyse one: showtime reference <video> --job <job>")
        results = guard.check_video(video, refs)
    worst = 0
    if args.json:
        print_json({"video": str(video), "results": results})
    for res in results:
        sev, rule, text = guard.message(res)
        worst = max(worst, 1 if sev == "FAIL" else 0)
        if not args.json:
            print("%s  %s" % (sev, text))
            if sev in ("FAIL", "WARN"):
                print("      fix: %s" % guard.FIX)
    return worst

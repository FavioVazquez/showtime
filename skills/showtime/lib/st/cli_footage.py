"""Footage commands: transcribe, pack, edit (cut/check/render/view), captions,
footage (scenes/reframe/denoise/stabilize/view/grade/luts/probe/autozoom).

Heavy imports happen inside the handlers so `showtime --help` stays fast.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .common import ShowtimeError, info, parse_time, print_json, write_json

COMMANDS = {
    "transcribe": "Word-level local transcription of video/audio (fillers kept, cached)",
    "pack": "Pack transcripts into takes_packed.md (phrase-level, for reading a shoot)",
    "edit": "Edit footage by transcript: cut (EDL from a transcript), check, render, view",
    "captions": "Captions from a transcript: ASS styles (bold-pop, clean, ...) + SRT/VTT",
    "footage": "Footage tools: scenes, reframe, denoise, stabilize, view, grade, luts, probe",
}

_F = argparse.RawDescriptionHelpFormatter


def _add_json(p: argparse.ArgumentParser) -> None:
    p.add_argument("--json", action="store_true", help="print a JSON result on stdout")


def register(sub: argparse._SubParsersAction) -> None:
    _register_transcribe(sub)
    _register_pack(sub)
    _register_edit(sub)
    _register_captions(sub)
    _register_footage(sub)


# --------------------------------------------------------------------------
# transcribe
# --------------------------------------------------------------------------

def _register_transcribe(sub) -> None:
    p = sub.add_parser("transcribe", help=COMMANDS["transcribe"], formatter_class=_F,
                       description="Transcribe speech to a word-level, verbatim transcript (fillers like um/uh are "
                                   "kept: they are edit points). Everything runs locally. Results are cached per "
                                   "source content, so re-running is instant.\n\n"
                                   "Output: <job>/edit/transcripts/<name>.json: the job the media or the current "
                                   "folder is in, else the newest job under ./showtime-out, else a new job "
                                   "<name>-edit. Nothing is written next to your footage unless you pass --edit-dir.",
                       epilog="Models:\n"
                              "  auto       turbo when installed, else small.en (English) / small (other languages)\n"
                              "  turbo      Whisper large-v3-turbo: best accuracy, 99 languages (setup --with asr-turbo)\n"
                              "  small      multilingual, fast; small.en: English only (installed by default)\n"
                              "  parakeet   English, ~3x faster than turbo, keeps fillers (setup --with parakeet)\n"
                              "\nExamples:\n"
                              "  showtime transcribe raw/take1.mp4\n"
                              "  showtime transcribe raw/ --model turbo              # every media file in a folder\n"
                              "  showtime transcribe interview.mov --speakers 2      # label speakers S0, S1\n"
                              "  showtime transcribe vlog.mp4 --language es\n"
                              "  showtime transcribe obs.mkv --audio-track 1         # mic on the second track\n"
                              "  showtime transcribe demo.mp4 --prompt \"showtime, Kokoro, ffmpeg\"  # names/jargon\n"
                              "  showtime transcribe talk.mp4 --from 12:30 --to 18:00  # only that part (times stay on the file's clock)")
    p.add_argument("media", nargs="+", help="video/audio files or folders")
    p.add_argument("--model", "-m", default="auto", help="auto (default), turbo, small, small.en, base.en, medium, "
                                                        "parakeet, parakeet-v3, or a model folder")
    p.add_argument("--language", "-l", help="language code (en, es, fr...); default: detect (or English for .en models)")
    p.add_argument("--speakers", "-s", help="diarize: number of speakers, or 'auto' (default: off, all S0)")
    ev = p.add_mutually_exclusive_group()
    ev.add_argument("--events", dest="events", action="store_const", const="on",
                    help="tag audio events (laughter, applause, music); default: on when the tagger is installed")
    ev.add_argument("--no-events", dest="events", action="store_const", const="off", help="skip audio events")
    p.set_defaults(events="auto")
    p.add_argument("--audio-track", "-a", type=int, default=0, help="audio track index (default 0)")
    p.add_argument("--no-vad", action="store_true", help="disable voice-activity filtering (whisper)")
    p.add_argument("--no-refine", action="store_true", help="keep raw ASR word times (no energy snapping)")
    p.add_argument("--prompt", help="names/jargon to bias recognition (whisper), e.g. \"showtime, Kokoro\"")
    p.add_argument("--edit-dir", help="where to write transcripts/ (default: <job>/edit, see above)")
    p.add_argument("-o", "--output", help="transcript path (single input only)")
    p.add_argument("--force", "-f", action="store_true", help="ignore the cache and transcribe again")
    p.add_argument("--threads", type=int, help="CPU threads (default: all cores)")
    p.add_argument("--from", dest="start", metavar="T", help="transcribe from this time (seconds or mm:ss); word "
                                                             "times stay on the source's clock")
    p.add_argument("--to", dest="end", metavar="T", help="transcribe up to this time (seconds or mm:ss)")
    _add_json(p)
    p.set_defaults(func=cmd_transcribe)


def cmd_transcribe(args) -> int:
    from .footage import transcribe as T
    from .footage import util as U
    items = U.collect_media(args.media)
    if args.output and len(items) != 1:
        raise ShowtimeError("-o/--output needs exactly one input file")
    results = []
    for f in items:
        doc, path = T.transcribe(f, model=args.model, language=args.language, speakers=args.speakers,
                                 events=args.events, audio_track=args.audio_track, vad=not args.no_vad,
                                 refine=not args.no_refine, prompt=args.prompt, edit_dir=args.edit_dir,
                                 force=args.force, threads=args.threads, out_path=args.output,
                                 start=parse_time(args.start) if args.start is not None else None,
                                 end=parse_time(args.end) if args.end is not None else None)
        st = doc.get("stats") or {}
        results.append({"source": str(f), "transcript": str(path), "duration": doc.get("duration"),
                        "range": doc.get("range"),
                        "language": doc.get("language"), "model": doc.get("model"), "words": st.get("words"),
                        "fillers": st.get("fillers"), "events": st.get("events"),
                        "speakers": (st.get("diarize") or {}).get("speakers", 1),
                        "dropped": len((doc.get("guards") or {}).get("dropped") or []),
                        "warnings": (doc.get("guards") or {}).get("warnings") or []})
    if args.json:
        print_json(results if len(results) != 1 else results[0])
    else:
        for r in results:
            print(r["transcript"])
        if results:
            ed = Path(results[0]["transcript"]).parent.parent
            print("next: showtime pack %s" % ed, file=sys.stderr)
    return 0


# --------------------------------------------------------------------------
# pack
# --------------------------------------------------------------------------

def _register_pack(sub) -> None:
    p = sub.add_parser("pack", help=COMMANDS["pack"], formatter_class=_F,
                       description="Write <edit_dir>/takes_packed.md: every transcript as phrase lines "
                                   "`[start-end wA-wB] S0 text`, breaking on pauses and speaker changes. "
                                   "Read it to choose what to keep.",
                       epilog="Examples:\n  showtime pack raw/edit\n  showtime pack raw/edit --gap 0.8 --no-ids\n"
                              "  showtime pack --files raw/edit/transcripts/take2.json -o take2.md")
    p.add_argument("edit_dir", nargs="?", default=None,
                   help="edit folder (with transcripts/) or a job; default: ./edit when it exists, else the current/newest job's edit/")
    p.add_argument("--gap", type=float, default=0.5, help="phrase break at pauses >= this many seconds (default 0.5)")
    p.add_argument("--no-ids", action="store_true", help="omit word ids")
    p.add_argument("--files", nargs="+", help="pack only these transcript files")
    p.add_argument("-o", "--output", help="output .md (default <edit_dir>/takes_packed.md)")
    _add_json(p)
    p.set_defaults(func=cmd_pack)


def _pack_dir(arg: Optional[str]) -> Path:
    """The edit folder for `pack`: as given (a folder, or a job whose edit/ it is), else ./edit,
    else the current or newest job's edit/."""
    from .job import ledger
    if arg:
        p = Path(arg).expanduser()
        if p.is_dir() and (p / "edit").is_dir() and not (p / "transcripts").is_dir():
            return p / "edit"
        if not p.exists() and "/" not in arg and "\\" not in arg:
            job = ledger.resolve_name(arg)
            if job is not None:
                return job / "edit"
        return p
    if Path("edit").is_dir():
        return Path("edit")
    job = ledger.enclosing_job(Path.cwd()) or ledger.latest()
    if job is not None and (job / "edit").is_dir():
        return job / "edit"
    return Path("edit")


def cmd_pack(args) -> int:
    from .footage import pack as P
    ed = _pack_dir(args.edit_dir)
    if ed.name == "transcripts":
        ed = ed.parent
    out = args.output or (ed / "takes_packed.md")
    rep = P.pack(ed, out, gap=args.gap, ids=not args.no_ids, files=args.files)
    if args.json:
        print_json(rep)
    else:
        info("%d take(s), %d phrases, %.0f s of speech material (%d chars)" % (
            rep["takes"], rep["phrases"], rep["seconds"], rep["chars"]))
        print(rep["output"])
    return 0


# --------------------------------------------------------------------------
# edit
# --------------------------------------------------------------------------

def _register_edit(sub) -> None:
    e = sub.add_parser("edit", help=COMMANDS["edit"], formatter_class=_F,
                       description="Edit real footage from its transcript.\n\n"
                                   "  cut     build an EDL from transcript(s): drop fillers, long pauses, word ranges\n"
                                   "  check   validate an EDL and print the frame-exact plan (no rendering)\n"
                                   "  render  render an EDL to video (segments, overlays, music, captions, loudness)\n"
                                   "  view    PNG timeline views around every cut of a rendered edit\n\n"
                                   "EDL format: references/editing.md",
                       epilog="Typical flow:\n"
                              "  showtime transcribe raw/take1.mp4\n"
                              "  showtime pack raw/edit\n"
                              "  showtime edit cut raw/edit/transcripts/take1.json --max-pause 0.6 --captions bold-pop \\\n"
                              "      --aspect 9:16 -o raw/edit/edl.json\n"
                              "  showtime edit render raw/edit/edl.json --preview\n"
                              "  showtime edit view raw/edit/edl.json\n"
                              "  showtime edit render raw/edit/edl.json")
    s = e.add_subparsers(dest="edit_cmd", metavar="<subcommand>")

    p = s.add_parser("cut", help="build an EDL from transcript(s)", formatter_class=_F,
                     description="Turn transcript(s) into an EDL that keeps the speech and removes fillers "
                                 "(default), long pauses (--max-pause), word ranges (--remove) or time ranges. "
                                 "Cuts never fall inside a kept word; edges are padded. Review the printed summary "
                                 "(or `edit check`) before rendering.",
                     epilog="Examples:\n"
                            "  showtime edit cut edit/transcripts/take1.json -o edit/edl.json\n"
                            "  showtime edit cut edit/transcripts/take1.json --max-pause 0.5 --remove w40-w52 \\\n"
                            "      --aspect 9:16 --captions bold-pop --grade auto -o edit/edl.json\n"
                            "  showtime edit cut t1.json t2.json --keep-fillers -o edl.json   # takes in order")
    p.add_argument("transcripts", nargs="+", help="transcript JSON file(s) (their sources play in this order)")
    p.add_argument("--keep-fillers", action="store_true", help="do not remove um/uh/erm")
    p.add_argument("--filler", action="append", default=[], help="extra filler word to remove (repeatable)")
    p.add_argument("--max-pause", type=float, help="shorten pauses longer than this (seconds), e.g. 0.5")
    p.add_argument("--keep-pause", type=float, default=0.3, help="pause length left where something was cut (0.3)")
    p.add_argument("--remove", action="append", default=[], help="word ids to remove, e.g. w12-w18 (repeatable)")
    p.add_argument("--remove-time", action="append", default=[], help="time range to remove, e.g. 12.5-14 (repeatable)")
    p.add_argument("--keep-time", action="append", default=[], help="keep only these time ranges (repeatable)")
    p.add_argument("--pad-before", type=float, default=0.05, help="kept before each word, 0.03-0.2 s (0.05)")
    p.add_argument("--pad-after", type=float, default=0.08, help="kept after each word, 0.03-0.2 s (0.08)")
    p.add_argument("--aspect", help="output aspect/size: 16:9, 9:16, 1:1, 4:5, 4k ... (default: source)")
    p.add_argument("--fit", choices=["auto", "cover", "contain", "blur", "reframe"], help="how sources fill the frame")
    p.add_argument("--fps", help="output fps (default: first source, normalised)")
    p.add_argument("--captions", help="caption style (bold-pop, clean, boxed, minimal, cinematic)")
    p.add_argument("--grade", help="none, auto, a preset or a look (see `footage luts`)")
    p.add_argument("--music", help="music file to lay under the speech (ducked)")
    p.add_argument("--denoise", choices=["auto", "deepfilter", "rnnoise", "afftdn"], help="clean the speech audio")
    p.add_argument("-o", "--output", help="EDL path (default <edit dir>/edl.json; when it exists, edl-2.json ... is "
                                          "written and printed, unless --overwrite)")
    p.add_argument("--overwrite", action="store_true", help="replace an existing EDL at -o instead of writing edl-N.json")
    _add_json(p)
    p.set_defaults(func=cmd_edit_cut)

    p = s.add_parser("check", help="validate an EDL, print the plan", formatter_class=_F,
                     description="Validate an EDL (sources, ranges inside the media, overlays, audio) and print "
                                 "the frame-exact plan: output time of every segment and the total duration.",
                     epilog="Examples:\n  showtime edit check edit/edl.json --json\n"
                            "  showtime edit check talk-edit          # a job: its latest EDL (edit cut records it)")
    p.add_argument("edl", nargs="?", help="EDL file, or a job folder/name (its latest EDL); default: the current or "
                                          "newest job")
    _add_json(p)
    p.set_defaults(func=cmd_edit_check)

    p = s.add_parser("render", help="render an EDL to video", formatter_class=_F,
                     description="Render an EDL: frame-accurate segments (tonemap, fit/reframe, grade, 30 ms audio "
                                 "fades), lossless concat, overlays, music bed, captions LAST, two-pass loudness. "
                                 "Segments are cached: re-rendering after a small change only redoes what changed. "
                                 "Writes the video, <out>.report.json and <out>.srt (when captions are on). "
                                 "Never overwrites: when the output exists it writes final-2.mp4 (preview-2.mp4 ...) "
                                 "and prints that path; --overwrite replaces the file instead (segments stay cached, "
                                 "so re-renders are cheap). <edl> may be a job folder or name: its latest EDL. "
                                 "Rendering into a job folder (-o <job>/final.mp4) updates job.json \"outputs\".",
                     epilog="Examples:\n"
                            "  showtime edit render edit/edl.json --preview        # fast 720p draft\n"
                            "  showtime edit render edit/edl.json --preview --overwrite   # re-render the same preview.mp4\n"
                            "  showtime edit render edit/edl.json                  # final -> edit/final.mp4\n"
                            "  showtime edit render edit/edl.json --aspect 9:16 --captions bold-pop -o edit/vertical.mp4\n"
                            "  showtime edit render edit/edl.json --aspect 1:1 --fit blur -o edit/square.mp4")
    p.add_argument("edl", help="EDL file, or a job folder/name (its latest EDL)")
    p.add_argument("-o", "--output", help="output video (default <edl folder>/final.mp4 or preview.mp4)")
    p.add_argument("--preview", "-p", action="store_true", help="fast draft (<= 1280 px, quick encode)")
    p.add_argument("--aspect", help="override output aspect/size (16:9, 9:16, 1:1, 4:5, 4k ...)")
    p.add_argument("--fit", choices=["auto", "cover", "contain", "blur", "reframe"], help="override fit")
    p.add_argument("--captions", help="override caption style ('none' to disable); another style starts from its own "
                                      "defaults (the EDL's position/size options belong to its style)")
    p.add_argument("--caption-position", choices=["bottom", "middle", "top"], help="override where captions sit")
    p.add_argument("--no-captions", action="store_true", help="render without captions/subtitles")
    p.add_argument("--grade", help="override the grade")
    p.add_argument("--jobs", "-j", type=int, help="parallel segment encodes (default 1-3 by CPU count)")
    p.add_argument("--overwrite", action="store_true", help="replace the output file if it exists (default: write name-2.mp4)")
    _add_json(p)
    p.set_defaults(func=cmd_edit_render)

    p = s.add_parser("view", help="timeline PNGs around every cut", formatter_class=_F,
                     description="For a rendered edit: filmstrip + waveform + words for +-1.5 s around each cut, "
                                 "plus the first/last seconds, 4 windows per PNG. Look at them after every render.\n\n"
                                 "Which video: --video when given; else the NEWEST render of this EDL (the newest "
                                 "<video>.report.json that names it, beside the EDL or in its job folder), so after a "
                                 "re-render (preview-2.mp4) the views follow it. With no EDL: the newest edit render "
                                 "here (./, ./edit, or the current/newest job). It prints \"using <video> (latest "
                                 "render of <edl>)\".",
                     epilog="Examples:\n  showtime edit view                         # newest edit render\n"
                            "  showtime edit view edit/edl.json           # newest render of this EDL\n"
                            "  showtime edit view edit/edl.json --video edit/final.mp4")
    p.add_argument("edl", nargs="?", help="EDL file, or a job folder/name (default: the newest edit render)")
    p.add_argument("--video", help="rendered video (default: the newest render of the EDL)")
    p.add_argument("-o", "--out-dir", help="folder for the PNGs (default <edl folder>/views)")
    p.add_argument("--window", type=float, default=1.5, help="seconds each side of a cut (1.5)")
    _add_json(p)
    p.set_defaults(func=cmd_edit_view)


def _rel(p: Path, base: Path) -> str:
    try:
        return os.path.relpath(str(p), str(base)).replace(os.sep, "/")
    except ValueError:  # different drive on Windows
        return str(p)


def cmd_edit_cut(args) -> int:
    from .footage import cuts as C
    from .footage import util as U
    from .footage import edl as E
    trs = [(Path(t).resolve(), U.load_transcript(t)) for t in args.transcripts]
    first = trs[0][0]
    ed = first.parent.parent if first.parent.name == "transcripts" else first.parent
    out = Path(args.output).resolve() if args.output else ed / "edl.json"
    wanted = out
    if out.exists() and not args.overwrite:
        out = U.unique_path(out)
        info("%s exists; writing %s (renders and edits never overwrite; pass --overwrite to replace it)"
             % (wanted.name, out.name))
    base = out.parent
    sources: Dict[str, str] = {}
    tmap: Dict[str, str] = {}
    ranges: List[Dict[str, Any]] = []
    removed_all: List[Dict[str, Any]] = []
    before = after = 0.0
    for tp, tr in trs:
        src = Path(tr.get("source") or "")
        if not src.is_file():
            cand = tp.parent.parent.parent / (tp.stem + ".mp4")
            raise ShowtimeError("the transcript's source is missing: %s" % (src or "(none)"),
                                hint="re-run `showtime transcribe` on the media, or fix \"source\" in %s" % tp.name
                                if not cand.is_file() else "expected %s" % cand)
        key = U.bare(src.stem).replace(" ", "-") or "src"
        k, n = key, 2
        while k in sources:
            k, n = "%s%d" % (key, n), n + 1
        sources[k] = _rel(src, base) if not tr.get("audio_track") else {
            "file": _rel(src, base), "audio_track": int(tr["audio_track"])}
        tmap[k] = _rel(tp, base)
        plan = C.plan_keep(tr, fillers=not args.keep_fillers, extra_fillers=args.filler,
                           remove_ids=args.remove if len(trs) == 1 else [],
                           remove_times=U.parse_ranges(",".join(args.remove_time)) if args.remove_time and len(trs) == 1 else [],
                           keep_times=U.parse_ranges(",".join(args.keep_time)) if args.keep_time and len(trs) == 1 else None,
                           max_pause=args.max_pause, keep_pause=args.keep_pause,
                           pad_before=args.pad_before, pad_after=args.pad_after)
        words = U.words_of(tr)
        for a, b in plan["keep"]:
            said = [w["text"] for w in words if a <= (w["start"] + w["end"]) / 2 <= b]
            note = " ".join(said[:8]) + (" ..." if len(said) > 8 else "")
            ranges.append({"source": k, "start": a, "end": b, "note": note})
        removed_all += [dict(r, source=k) for r in plan["removed"]]
        before += plan["before"]
        after += plan["after"]
    if (args.remove or args.remove_time or args.keep_time) and len(trs) > 1:
        info("note: --remove/--remove-time/--keep-time apply only with a single transcript; ignored")
    doc: Dict[str, Any] = {"version": 1, "sources": sources, "transcripts": tmap, "ranges": ranges}
    o: Dict[str, Any] = {}
    if args.aspect:
        o["aspect"] = args.aspect
    if args.fit:
        o["fit"] = args.fit
    if args.fps:
        o["fps"] = args.fps
    if o:
        doc["output"] = o
    if args.grade:
        doc["grade"] = args.grade
    if args.captions and args.captions != "none":
        doc["captions"] = {"style": args.captions}
    if args.music:
        doc["audio"] = {"music": _rel(Path(args.music).resolve(), base)}
    if args.denoise:
        doc.setdefault("audio", {})["denoise"] = args.denoise
    doc["cut_summary"] = {"before_s": round(before, 3), "after_s": round(after, 3), "segments": len(ranges),
                          "removed": [{"id": r.get("id"), "text": r["text"], "at": r["start"], "why": r["why"],
                                       "source": r["source"]} for r in removed_all]}
    E.normalize(json.loads(json.dumps(doc)), base, str(out))  # validate before writing
    write_json(out, doc)
    job = _record(out, ["edl=%s" % out], stage="cut", event="edit cut -> %s" % out.name)
    if args.json:
        print_json({"edl": str(out), "requested": str(wanted), "before": round(before, 3), "after": round(after, 3),
                    "segments": len(ranges), "removed": len(removed_all), "job": str(job) if job else None})
    else:
        why: Dict[str, int] = {}
        for r in removed_all:
            why[r["why"]] = why.get(r["why"], 0) + 1
        info("%.1f s -> %.1f s, %d segment(s); removed %s" % (
            before, after, len(ranges), ", ".join("%d %s" % (v, k) for k, v in why.items()) or "nothing but pauses"))
        info("wrote %s" % out)
        print(out)
        print("next: showtime edit render %s --preview" % out, file=sys.stderr)
    return 0


# ----------------------------------------------------------- which file is current

def _record(target: Path, outputs: List[str], **kw: Any) -> Optional[Path]:
    """Update job.json "outputs" when `target` sits in a job folder (a convenience: never fails the command)."""
    try:
        from .job import ledger
        return ledger.record_outputs(target, outputs, **kw)
    except Exception as e:  # noqa: BLE001
        from .common import debug
        debug("could not update the job ledger: %s" % e)
        return None


def _edl_arg(arg: Optional[str]) -> Path:
    """An EDL path, or a job folder/name (None: the current or newest job) -> that job's latest EDL."""
    p = Path(arg).expanduser() if arg else None
    if p is not None and p.is_file():
        return p.resolve()
    from .job import ledger
    edl, _job, _ = ledger.media_arg(arg, "edl", say=info)
    return edl


def _render_reports(dirs: List[Path]) -> List[Dict[str, Any]]:
    """Edit render reports (<video>.report.json) in `dirs` whose video and EDL still exist, newest first."""
    from .common import read_json
    seen, out = set(), []
    for d in dirs:
        if not d.is_dir():
            continue
        for rp in d.glob("*.report.json"):
            if rp in seen:
                continue
            seen.add(rp)
            r = read_json(rp, None)
            if not isinstance(r, dict) or not r.get("edl") or not r.get("output"):
                continue
            if Path(r["output"]).is_file() and Path(r["edl"]).is_file():
                out.append({"report": rp, "video": Path(r["output"]), "edl": Path(r["edl"]).resolve(),
                            "mtime": rp.stat().st_mtime})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out


def latest_edit_render(edl: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """The newest render of `edl` (or of any EDL when None) near it, in its job, or under the current folder."""
    from .job import ledger
    dirs: List[Path] = []
    if edl is not None:
        dirs += [edl.parent, edl.parent / "edit"]
        job = ledger.enclosing_job(edl)
    else:
        cwd = Path.cwd()
        dirs += [cwd, cwd / "edit"]
        job = ledger.enclosing_job(cwd)
        if job is None:
            try:
                job = ledger.latest()
            except Exception:  # noqa: BLE001
                job = None
    if job is not None:
        dirs += [job, job / "edit", job / "exports"]
        for k in ("final", "preview"):
            v = ledger.latest_output(job, k)
            if v is not None:
                dirs.append(v.parent)
    reps = _render_reports(dirs)
    if edl is not None:
        reps = [r for r in reps if r["edl"] == edl.resolve()]
    return reps[0] if reps else None


def _view_target(edl_arg: Optional[str], video: Optional[str]):
    """(edl, video) for `edit view` / `footage view --edl`."""
    if edl_arg:
        edl = _edl_arg(edl_arg)
    else:
        if video:
            raise ShowtimeError("--video needs the EDL too", hint="showtime edit view <edl.json> --video <file>")
        r = latest_edit_render(None)
        if r is None:
            raise ShowtimeError("no edit render found here (no *.report.json in ./, ./edit or the current job)",
                                hint="pass the EDL: showtime edit view <edl.json>, or render it first: showtime edit render <edl.json> --preview")
        info("using %s (latest render of %s)" % (r["video"], r["edl"].name))
        return r["edl"], r["video"]
    if video:
        return edl, Path(video)
    r = latest_edit_render(edl)
    if r is not None:
        info("using %s (latest render of %s)" % (r["video"], edl.name))
        return edl, r["video"]
    return edl, None


def cmd_edit_check(args) -> int:
    from .footage import edl as E
    from .footage import util as U
    ed = E.load(_edl_arg(args.edl))
    segs = E.plan(ed)
    summ = E.summary(ed, segs)
    trs = E.load_transcripts(ed)
    summ["transcripts"] = sorted(trs)
    if ed["captions"] and len(trs) < len({s["source"] for s in segs}):
        summ["problems"] = ["captions are on but some sources have no transcript"]
    joins = E.join_problems(segs, ed["output"]["fps"]) + E.punch_bounce(segs, ed["output"]["fps"])
    if joins:
        summ["problems"] = summ.get("problems", []) + joins
    if args.json:
        print_json(summ)
        return 0
    o = summ["output"]
    print("EDL ok: %d segment(s), %s, %dx%d @ %s fps, fit %s" % (len(segs), U.fmt_time(summ["duration"]),
                                                                o["width"], o["height"], o["fps"], o["fit"]))
    for s in summ["segments"]:
        print("  #%-3d %-10s src %8.3f-%8.3f -> out %8.3f-%8.3f  %s" % (
            s["i"], s["source"][:10], s["src_start"], s["src_end"], s["out_start"], s["out_end"], s.get("note", "")[:60]))
    extras = []
    if summ["overlays"]:
        extras.append("%d overlay(s)" % summ["overlays"])
    if summ["captions"]:
        extras.append("captions: %s" % summ["captions"])
    if summ["music_tracks"]:
        extras.append("%d audio track(s)" % summ["music_tracks"])
    if extras:
        print("  " + ", ".join(extras))
    for p in summ.get("problems", []):
        print("  problem: " + p)
    return 0


def cmd_edit_render(args) -> int:
    from .footage import render_edl as R
    ov: Dict[str, Any] = {}
    if args.aspect or args.fit:
        ov["output"] = {k: v for k, v in (("aspect", args.aspect), ("fit", args.fit)) if v}
        if args.aspect:
            ov["output"].update(width=None, height=None)
    if args.captions:
        ov["captions"] = False if args.captions == "none" else {"style": args.captions}
    if getattr(args, "caption_position", None):
        if ov.get("captions") is False:
            raise ShowtimeError("--caption-position with --captions none makes no sense")
        ov["captions"] = dict(ov.get("captions") or {}, position=args.caption_position)
    if args.grade:
        ov["grade"] = args.grade
    edl = _edl_arg(args.edl)
    rep = R.render(edl, args.output, preview=args.preview, overwrite=args.overwrite, jobs=args.jobs,
                   captions=not args.no_captions, overrides=ov or None)
    outp = Path(rep["output"])
    outs = ["%s=%s" % ("preview" if args.preview else "final", outp), "edl=%s" % edl]
    srt = outp.with_suffix(".srt")
    if srt.is_file() and srt.stat().st_mtime >= outp.stat().st_mtime - 600:
        outs.append("captions=%s" % srt)
    job = _record(outp, outs, stage="preview" if args.preview else "render", seconds=rep.get("seconds"),
                  event="edit render %s -> %s" % (Path(edl).name, outp.name))
    rep["job"] = str(job) if job else None
    if args.json:
        print_json(rep)
    else:
        lo = rep.get("loudness") or {}
        info("duration %.2f s (planned %.2f), %s frames, loudness %s LUFS / %s dBTP" % (
            rep.get("video_duration") or rep["duration"], rep["duration"], rep.get("frames"),
            lo.get("integrated_lufs"), lo.get("true_peak_dbtp")))
        info("report %s" % rep["report"])
        for w in (rep.get("warnings") or [])[:6]:
            info("warning: %s" % w)
        print(rep["output"])
        nxt = _edit_render_next(edl, outp, job, args.preview)
        from . import delight
        shown = delight.show_card("%s is ready" % outp.name, outp, [
            delight.fmt_len(rep.get("video_duration") or rep.get("duration")),
            "%sx%s" % (rep["width"], rep["height"]) if rep.get("width") else None,
            _size_text(outp)], nxt, delight.qa_verdict(outp, job))
        if not shown:
            print("next: %s" % nxt, file=sys.stderr)
    return 0


def _size_text(p: Path) -> Optional[str]:
    from .common import human_size
    try:
        return human_size(p.stat().st_size)
    except OSError:
        return None


def _edit_render_next(edl: Path, out: Path, job: Optional[Path], preview: bool) -> str:
    """After a preview: look at the cuts. After a final: poster, then qa (then exports)."""
    if preview:
        return "showtime edit view %s --video %s   (look at every cut), then the final: showtime edit render %s%s" % (
            edl, out, job.name if job else edl, (" -o %s" % (job / "final.mp4")) if job else "")
    tgt = job.name if job else str(out)
    return ("showtime deliver poster %s --bake   (poster in frame 0; it becomes the latest final)   then   "
            "showtime qa %s" % (tgt, tgt))


def cmd_edit_view(args) -> int:
    from .footage import timeline_view as V
    edl, video = _view_target(args.edl, args.video)
    pages = V.view_edl(edl, video, args.out_dir, window=args.window)
    if args.json:
        print_json({"pages": [str(p) for p in pages]})
    else:
        for p in pages:
            print(p)
    return 0


# --------------------------------------------------------------------------
# captions
# --------------------------------------------------------------------------

def _register_captions(sub) -> None:
    from_styles = "bold-pop, clean, boxed, minimal, cinematic"
    p = sub.add_parser("captions", help=COMMANDS["captions"], formatter_class=_F,
                       description="Generate styled captions (ASS, burned with libass) from a word-level transcript, "
                                   "plus SRT/VTT for platforms. With --edl the words are mapped to the edited "
                                   "timeline (cut words disappear, times shift exactly). With --burn the captions "
                                   "are rendered onto a video.\n\nStyles: " + from_styles,
                       epilog="Examples:\n"
                              "  showtime captions edit/transcripts/take1.json --style clean --aspect 16:9 -o subs.ass\n"
                              "  showtime captions t.json --edl edit/edl.json --style bold-pop -o edit/caps.ass --srt edit/caps.srt\n"
                              "  showtime captions clip.srt --style boxed --size 1080x1920 -o boxed.ass\n"
                              "  showtime captions t.json --style bold-pop --burn clip.mp4 -o clip.captioned.mp4\n"
                              "An --srt/--vtt written into a job folder becomes the job's latest captions, which\n"
                              "`showtime qa <job>` checks with the latest final. A --burn output written into a\n"
                              "job as an .mp4 named final* (the default <final>.captioned.mp4 of a final) becomes\n"
                              "the job's latest final, so qa, review-pack and deliver use the captioned file.\n"
                              "When the video already burns\n"
                              "captions (a project page with caption-karaoke/captions/F.caption, or an EDL with\n"
                              "captions), the files written are optional; the command says so.\n"
                              "Grouping, sizes and safe zones: references/captions.md")
    p.add_argument("transcript", help="transcript JSON (or .srt/.vtt to restyle)")
    p.add_argument("--style", "-s", default="bold-pop", help="caption style (default bold-pop)")
    p.add_argument("--edl", help="map words through this EDL (output timeline)")
    p.add_argument("--aspect", help="frame aspect/size preset (16:9, 9:16, 1:1, 4:5, 4k)")
    p.add_argument("--size", help="frame size WxH, e.g. 1080x1920 (default: EDL output or the source video)")
    p.add_argument("--font", help="font family (anton, inter, instrument-serif, ...) or a .ttf/.otf path")
    p.add_argument("--highlight", help="active-word colour, e.g. #FFE500")
    p.add_argument("--color", help="text colour, e.g. #FFFFFF")
    p.add_argument("--position", choices=["bottom", "middle", "top"], default="bottom")
    p.add_argument("--text-scale", "--size-scale", dest="text_scale", type=float, metavar="K",
                   help="text size as a multiple of the style's (e.g. 1.5 for bigger burned Shorts captions; "
                        "lines wrap sooner)")
    p.add_argument("--max-words", type=int, help="words per caption (style default); also for the --srt/--vtt sidecars")
    p.add_argument("--regroup", action="store_true",
                   help="with an .srt/.vtt input: regroup the words instead of keeping its cues and line breaks")
    p.add_argument("--uppercase", action="store_true", default=None, help="force uppercase")
    p.add_argument("--fillers", action="store_true", help="show um/uh (hidden by default)")
    p.add_argument("--keep-emoji", action="store_true",
                   help="keep emoji in burned captions (removed by default: libass draws them from each OS's own font)")
    p.add_argument("-o", "--output", help="output .ass, or the video path with --burn")
    p.add_argument("--srt", help="also write an SRT here")
    p.add_argument("--vtt", help="also write a WebVTT here")
    p.add_argument("--burn", metavar="VIDEO", help="burn the captions onto this video")
    _add_json(p)
    p.set_defaults(func=cmd_captions)


def _parse_size(size: Optional[str], aspect: Optional[str]):
    from .footage.edl import ASPECTS
    if size:
        try:
            w, h = (int(x) for x in size.lower().split("x"))
            return w, h
        except ValueError:
            raise ShowtimeError("invalid --size %r (use WxH, e.g. 1080x1920)" % size)
    if aspect:
        if aspect.lower() not in ASPECTS:
            raise ShowtimeError("unknown aspect %r (%s)" % (aspect, ", ".join(ASPECTS)))
        return ASPECTS[aspect.lower()]
    return None


def cmd_captions(args) -> int:
    from .footage import captions as C
    from .footage import util as U
    from .footage import edl as E
    tr = U.load_transcript(args.transcript)
    size = _parse_size(args.size, args.aspect)
    words = tr["words"]
    cuts = None
    if args.edl:
        ed = E.load(args.edl)
        segs = E.plan(ed)
        trs = E.load_transcripts(ed)
        # the given transcript wins for its own source
        src = str(Path(tr.get("source") or "").resolve()) if tr.get("source") else None
        for k, v in ed["sources"].items():
            if src and str(v["path"]) == src:
                trs[k] = tr
        words = E.map_words(segs, trs, include_events=False)
        cuts = E.cut_times(segs, ed["output"].get("fps") or 30)
        if not size:
            size = (ed["output"]["width"], ed["output"]["height"])
    if not size and args.burn:
        pr = U.probe(args.burn)
        size = (pr.get("display_width") or 1920, pr.get("display_height") or 1080)
    if not size and tr.get("source") and Path(tr["source"]).is_file():
        pr = U.probe(tr["source"])
        if pr.get("has_video"):
            size = (pr.get("display_width"), pr.get("display_height"))
    size = size or (1920, 1080)
    opts: Dict[str, Any] = {"position": args.position, "fillers": args.fillers,
                            "emoji": bool(getattr(args, "keep_emoji", False))}
    if args.font:
        opts["font"] = args.font
    if args.highlight:
        opts["highlight"] = args.highlight
    if args.color:
        opts["color"] = args.color
    if args.max_words:
        opts["max_words"] = args.max_words
    if args.uppercase:
        opts["upper"] = True
    if args.text_scale is not None:
        if not 0.5 <= args.text_scale <= 2.5:
            raise ShowtimeError("--text-scale must be between 0.5 and 2.5 (got %g)" % args.text_scale,
                                hint="1.2 makes the text 20% larger than the style's own size")
        base = C.get_style(args.style)["size"]
        k = float(args.text_scale)
        opts["size"] = {o: v * k for o, v in base.items()} if isinstance(base, dict) else float(base) * k
    burn_out = None
    if args.burn:
        burn_out = Path(args.output) if args.output else Path(args.burn).with_name(Path(args.burn).stem + ".captioned.mp4")
        if burn_out.suffix.lower() == ".ass":
            raise ShowtimeError("with --burn, -o is the output video (e.g. clip.captioned.mp4)")
        ass_out = burn_out.with_suffix(".ass")
    else:
        ass_out = Path(args.output) if args.output else Path(args.transcript).with_name(
            Path(args.transcript).stem + ".%s.ass" % args.style)
    rep = C.build(words, ass_out, style=args.style, width=int(size[0]), height=int(size[1]),
                  lang=tr.get("language") or "en", options=opts,
                  srt=Path(args.srt) if args.srt else None, vtt=Path(args.vtt) if args.vtt else None,
                  context=[args.transcript, args.edl, args.burn], cuts=cuts,
                  keep_cues=False if args.regroup else None)
    sidecar = rep.get("srt") or rep.get("vtt")
    if sidecar:
        # the job's latest captions (qa checks them with the job's latest final): only a sidecar written
        # into the job folder itself; an experiment elsewhere never re-points the job
        from .job import ledger
        sp = Path(sidecar).resolve()
        job = ledger.enclosing_job(sp)
        if job is not None and sp.parent == job.resolve():
            job = _record(sp, ["captions=%s" % sp], event="captions -> %s" % sp.name)
            rep["job"] = str(job) if job else None
            if job is not None:
                info("job %s: captions -> %s" % (job.name, sp.name))
        elif job is not None:
            info("note: %s is in a subfolder of job %s (%s/), so the job's captions pointer (what qa checks with the "
                 "latest final) is unchanged; write the sidecar to %s/ to re-point it, or check this file with "
                 "showtime qa <video> --captions %s" % (sp.name, job.name, sp.parent.relative_to(job.resolve()).as_posix(),
                                                         job, sp))
    if burn_out is not None:
        from . import ff
        burn_out = U.unique_path(burn_out)
        pr = U.probe(args.burn)
        vf = "ass=filename=%s:fontsdir=%s,%s" % (ff.filter_path(rep["ass"]), ff.filter_path(rep["fontsdir"]),
                                                 ff.BT709_VF + ",format=yuv420p")
        preset = ff.preset("final")
        ff.run_ffmpeg(["-i", str(args.burn), "-map", "0:v:0", "-map", "0:a?", "-vf", vf] + preset.video +
                      (["-c:a", "copy"] if pr.get("has_audio") else []) + ["-movflags", "+faststart", str(burn_out)])
        rep["video"] = str(burn_out)
        # the captioned video is the job's new latest final when it is one (like `deliver poster --bake`);
        # a burn onto another clip, or into a subfolder, is logged as a variant
        from .job import ledger
        bjob = ledger.enclosing_job(burn_out.resolve())
        if bjob is not None:
            data = ledger.note(bjob, outputs=["final=%s" % burn_out.resolve()], auto=True,
                               event="captions --burn %s -> %s" % (Path(args.burn).name, burn_out.name))
            rec = ledger.recorded_as(data, burn_out)
            rep["job"] = str(bjob)
            if rec is not None and rec.get("kind") == "final":
                rep["job_latest_final"] = True
                info("job %s: latest final -> %s (qa, review-pack and deliver now use the captioned file)" % (
                    bjob.name, burn_out.name))
            else:
                rep["job_latest_final"] = False
                info("job %s: %s logged as a variant (%s); the latest final is unchanged. To make it the final: "
                     "showtime job note %s --output final=%s" % (bjob.name, burn_out.name,
                                                                (rec or {}).get("why") or "not a final", bjob.name,
                                                                burn_out.resolve()))
    if args.json:
        print_json(rep)
    else:
        t = rep["timing"]
        info("%s: %d caption group(s), %d words, font %s%s" % (
            rep["style"], rep["groups"], rep["words"], rep["font"],
            "" if not any((t["words_outside_group"], t["overlaps"])) else " (timing problems: %s)" % t))
        if rep.get("burned_elsewhere"):
            info("note: sidecars optional (the video already burns captions: %s)" % rep["burned_elsewhere"])
        print(rep.get("video") or rep["ass"])
        for k in ("srt", "vtt"):
            if rep.get(k):
                print(rep[k])
    return 0


# --------------------------------------------------------------------------
# footage
# --------------------------------------------------------------------------

def _register_footage(sub) -> None:
    f = sub.add_parser("footage", help=COMMANDS["footage"], formatter_class=_F,
                       description="Tools for real footage.\n\n"
                                   "  trim       cut a range out of a clip; seek-friendly proxies for <video> layers\n"
                                   "  scenes     shot detection + contact sheet (or --every N s)\n"
                                   "  reframe    face-tracked crop to 9:16 / 1:1 / 4:5 (or blur-pad)\n"
                                   "  denoise    clean speech audio (DeepFilterNet / RNNoise / FFT)\n"
                                   "  stabilize  two-pass stabilisation\n"
                                   "  view       filmstrip + waveform + words PNG for a time range\n"
                                   "  grade      auto-correct and/or apply a look to a clip\n"
                                   "  luts       list looks, or preview every look on a frame\n"
                                   "  probe      media facts as JSON (size, fps, rotation, HDR, audio tracks)\n"
                                   "  autozoom   click-driven zoom for screen recordings (capture module)\n\n"
                                   "Default outputs never go beside your media: they go to <job>/work/scenes or\n"
                                   "<job>/work/footage/ (the job the file or the current folder is in, else the newest\n"
                                   "job), or a fresh showtime-out/<tool>-<time>/ when there is no job. -o picks a path.",
                       epilog="Examples:\n"
                              "  showtime footage scenes raw/broll.mp4\n"
                              "  showtime footage reframe talk.mp4 --aspect 9:16 -o talk.vertical.mp4\n"
                              "  showtime footage denoise interview.mov -o interview.clean.mov\n"
                              "  showtime footage view take1.mp4 --from 12 --to 20\n"
                              "  showtime footage luts --preview take1.mp4 --at 5\n"
                              "  showtime footage grade take1.mp4 --auto --look teal-orange -o take1.graded.mp4")
    s = f.add_subparsers(dest="footage_cmd", metavar="<subcommand>")

    p = s.add_parser("trim", help="cut a range out of a clip, or make a seek-friendly proxy for a <video> layer",
                     formatter_class=_F,
                     description="Cut --from/--to out of a video (frame-accurate re-encode, H.264 + AAC, +faststart), "
                                 "optionally smaller (--width) and with short keyframe intervals (--gop, default 0.5 s) "
                                 "so a <video> layer in a page seeks fast during renders. --webm writes VP9 (Chromium "
                                 "builds without H.264). --copy cuts without re-encoding (instant, but it starts on "
                                 "the keyframe before --from). Output never goes beside your media: <job>/work/footage/ "
                                 "by default (see above); -o picks a path.",
                     epilog="Examples:\n  showtime footage trim interview.mp4 --from 61 --to 142 -o excerpt.mp4\n"
                            "  showtime footage trim demo.mp4 --width 1280 -o project/media/demo.mp4   # proxy for a page\n"
                            "  showtime footage trim demo.mp4 --webm --width 1280 -o project/media/demo.webm")
    p.add_argument("video")
    p.add_argument("--from", dest="t_from", type=float, default=0.0, help="start time in seconds (default 0)")
    p.add_argument("--to", dest="t_to", type=float, help="end time in seconds (default: the end)")
    p.add_argument("--width", type=int, help="scale to this width (even; height follows)")
    p.add_argument("--gop", type=float, default=0.5, help="seconds between keyframes (default 0.5: fast seeking)")
    p.add_argument("--crf", type=int, help="quality (default 18 for H.264, 32 for VP9)")
    p.add_argument("--webm", action="store_true", help="VP9 in WebM instead of H.264 in MP4")
    p.add_argument("--no-audio", action="store_true", help="drop the audio (a silent <video> layer)")
    p.add_argument("--copy", action="store_true", help="stream copy (no re-encode; starts on a keyframe)")
    p.add_argument("-o", "--output", help="output file (default <job>/work/footage/<name>.trim.mp4)")
    _add_json(p)
    p.set_defaults(func=cmd_trim)

    p = s.add_parser("scenes", help="shot detection + contact sheet", formatter_class=_F,
                     description="Detect shots (PySceneDetect adaptive detector; ffmpeg scdet fallback) and write "
                                 "<name>.scenes.json + a labelled contact sheet PNG. --every N makes a sheet with "
                                 "one frame every N seconds instead (quick inventory of any clip).",
                     epilog="Examples:\n  showtime footage scenes broll.mp4                 # -> <job>/work/scenes/\n"
                            "  showtime footage scenes talk.mp4 --every 5 --job talk-edit\n"
                            "  showtime footage scenes talk.mp4 -o shots/")
    p.add_argument("video")
    p.add_argument("--every", type=float, help="periodic sheet: one frame every N seconds (at most 60 frames: "
                                               "narrow the range with --from/--to for a denser look)")
    p.add_argument("--from", dest="t_from", type=float, help="periodic sheet: start time (s)")
    p.add_argument("--to", dest="t_to", type=float, help="periodic sheet: end time (s)")
    p.add_argument("--threshold", type=float, help="detector threshold (adaptive default 3.0)")
    p.add_argument("--min-len", type=float, default=0.6, help="minimum shot length in seconds (0.6)")
    p.add_argument("--method", choices=["adaptive", "content", "scdet"], default="adaptive")
    p.add_argument("-o", "--out-dir", help="output folder, or a .png/.jpg file for the --every sheet (default "
                                          "<job>/work/scenes: the --job, the job the video or the current folder is "
                                          "in, else the newest job; never next to the source)")
    p.add_argument("--job", help="job folder or name whose work/scenes/ gets the sheet")
    _add_json(p)
    p.set_defaults(func=cmd_scenes)

    p = s.add_parser("reframe", help="face-tracked crop to another aspect", formatter_class=_F,
                     description="Reframe a clip to another aspect ratio. Faces are tracked with YuNet and the crop "
                                 "glides (dead zone + smoothing, hard cuts respected). With --fit blur the whole "
                                 "frame is kept on a blurred background instead.",
                     epilog="Examples:\n  showtime footage reframe talk.mp4 --aspect 9:16\n"
                            "  showtime footage reframe talk.mp4 --aspect 1:1 --zoom 1.15 -o square.mp4\n"
                            "  showtime footage reframe screen.mp4 --aspect 9:16 --fit blur")
    p.add_argument("video")
    p.add_argument("--aspect", default="9:16", help="target aspect/size (default 9:16)")
    p.add_argument("--fit", choices=["reframe", "cover", "blur", "contain"], default="reframe")
    p.add_argument("--zoom", type=float, help="extra punch-in, 1.0-3.0")
    p.add_argument("--focus", help="fixed crop centre 'x,y' in 0..1 (disables tracking), e.g. 0.3,0.5")
    p.add_argument("--preview", action="store_true", help="fast draft")
    p.add_argument("-o", "--output")
    _add_json(p)
    p.set_defaults(func=cmd_reframe)

    p = s.add_parser("denoise", help="clean speech audio", formatter_class=_F,
                     description="Reduce background noise in speech. auto = DeepFilterNet when installed, else "
                                 "RNNoise (arnndn), else ffmpeg afftdn. Video is copied untouched.",
                     epilog="Examples:\n  showtime footage denoise take1.mp4 -o take1.clean.mp4\n"
                            "  showtime footage denoise vo.wav -o vo.clean.wav --strength 0.7")
    p.add_argument("input")
    p.add_argument("-o", "--output")
    p.add_argument("--method", choices=["auto", "deepfilter", "rnnoise", "afftdn"], default="auto")
    p.add_argument("--strength", type=float, default=1.0, help="0..1 (default 1 = full)")
    p.add_argument("--model", choices=["cb", "sh", "std"], default="cb", help="RNNoise model (default cb)")
    p.add_argument("--audio-track", type=int, default=0)
    _add_json(p)
    p.set_defaults(func=cmd_denoise)

    p = s.add_parser("stabilize", help="stabilise shaky footage", formatter_class=_F,
                     description="Two-pass vid.stab stabilisation (deshake fallback when the ffmpeg build lacks it).",
                     epilog="Example:\n  showtime footage stabilize walk.mp4 --strength 0.7 -o walk.stable.mp4")
    p.add_argument("video")
    p.add_argument("-o", "--output")
    p.add_argument("--strength", type=float, default=0.5, help="0..1 (default 0.5)")
    p.add_argument("--preview", action="store_true")
    _add_json(p)
    p.set_defaults(func=cmd_stabilize)

    p = s.add_parser("view", help="timeline PNG for a range (or --edl)", formatter_class=_F,
                     description="Filmstrip + waveform + words (+ pauses) for a time range of a media file. "
                                 "With --edl: views around every cut of the rendered edit.",
                     epilog="Examples:\n  showtime footage view take1.mp4 --from 12 --to 20\n"
                            "  showtime footage view --edl edit/edl.json")
    p.add_argument("media", nargs="?")
    p.add_argument("--from", dest="start", help="start time (s or mm:ss)")
    p.add_argument("--to", dest="end", help="end time")
    p.add_argument("--transcript", help="transcript JSON (default: found in edit/transcripts)")
    p.add_argument("--frames", type=int, default=8, help="thumbnails in the strip (8)")
    p.add_argument("--mark", action="append", default=[], help="draw a marker at this time (repeatable)")
    p.add_argument("--edl", help="view every cut of this EDL's rendered video")
    p.add_argument("--video", help="with --edl: the rendered video")
    p.add_argument("-o", "--output", help="PNG path (or folder with --edl)")
    _add_json(p)
    p.set_defaults(func=cmd_view)

    p = s.add_parser("grade", help="auto-correct / apply a look", formatter_class=_F,
                     description="Colour-correct a clip (--auto: exposure, contrast, saturation from measured "
                                 "frame statistics) and/or apply a preset or look (strength 0..1). --analyze only "
                                 "prints the measurements; --compare writes a before/after still.",
                     epilog="Presets: none subtle punch warm cool film mono webcam lowlight\n"
                            "Looks:   see `showtime footage luts`\n"
                            "Examples:\n  showtime footage grade take1.mp4 --analyze\n"
                            "  showtime footage grade take1.mp4 --auto --look teal-orange --strength 0.5\n"
                            "  showtime footage grade take1.mp4 --preset punch --compare --at 4")
    p.add_argument("video")
    p.add_argument("--auto", action="store_true", help="measured exposure/contrast/saturation correction")
    p.add_argument("--preset", help="eq/curves preset")
    p.add_argument("--look", help="procedural look name, or a .cube file")
    p.add_argument("--strength", type=float, default=0.6, help="look strength 0..1 (default 0.6)")
    p.add_argument("--analyze", action="store_true", help="print measurements + the auto correction and exit")
    p.add_argument("--compare", action="store_true", help="write a before/after PNG instead of a video")
    p.add_argument("--at", type=float, help="time for --compare (default: middle)")
    p.add_argument("--preview", action="store_true")
    p.add_argument("-o", "--output")
    _add_json(p)
    p.set_defaults(func=cmd_grade)

    p = s.add_parser("luts", help="list looks / preview them on a frame", formatter_class=_F,
                     description="List the built-in looks (original, generated .cube LUTs), write them to "
                                 "~/.showtime/models/luts, or preview all of them on one frame of a video.",
                     epilog="Examples:\n  showtime footage luts\n  showtime footage luts --preview take1.mp4 --at 5 "
                            "--strength 0.7")
    p.add_argument("--preview", metavar="VIDEO", help="make a sheet of every look on a frame of VIDEO")
    p.add_argument("--at", type=float, help="frame time for --preview (default: middle)")
    p.add_argument("--strength", type=float, default=0.7)
    p.add_argument("--write", action="store_true", help="(re)write all .cube files at --strength")
    p.add_argument("-o", "--output", help="sheet PNG path")
    _add_json(p)
    p.set_defaults(func=cmd_luts)

    p = s.add_parser("probe", help="media facts as JSON", description="Probe a media file (size, display size, "
                     "rotation, fps, VFR, HDR transfer, colour tags, audio tracks, duration).")
    p.add_argument("media")
    p.set_defaults(func=cmd_probe)

    # prefix_chars="+": every argument (including --help) is passed through untouched
    p = s.add_parser("autozoom", help="screen-recording auto zoom (capture module)", add_help=False,
                     prefix_chars="+", description="Provided by the capture module (st.footage.autozoom).")
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_autozoom)


def _adhoc_render(video: str, out: Optional[str], suffix: str, extra: Dict[str, Any], preview: bool) -> Dict[str, Any]:
    """Render one whole clip through the EDL renderer (reuses fit/grade/audio code)."""
    import hashlib
    from .footage import render_edl as R
    from .footage import util as U
    from .common import home
    src = Path(video).resolve()
    pr = U.probe(src)
    if not pr.get("has_video"):
        raise ShowtimeError("%s has no video stream" % src.name)
    doc = {"sources": {"clip": str(src)}, "ranges": [{"source": "clip", "start": 0,
                                                     "end": round(float(pr["duration"]), 3)}],
           "loudness": False}
    doc.update(extra)
    h = hashlib.sha1(json.dumps(doc, sort_keys=True).encode()).hexdigest()[:12]
    d = home() / "cache" / "footage" / "adhoc" / h
    edl_p = write_json(d / "edl.json", doc)
    out_p = Path(out) if out else footage_out(src, src.stem + suffix + ".mp4")
    out_p.parent.mkdir(parents=True, exist_ok=True)
    return R.render(edl_p, out_p.resolve(), preview=preview, captions=False)


def footage_out(src: Path, name: str) -> Path:
    """Default output of a footage tool, never beside the user's own media:
    a source inside a job (showtime's own output) -> beside it; else <job>/work/footage/<name> for the
    job the current folder is in, else the newest job; with no job at all showtime-out/footage-<ts>/<name>."""
    from .job import ledger
    from .common import output_dir
    src = Path(src).resolve()
    if ledger.enclosing_job(src) is not None:
        return src.with_name(name)
    job = ledger.enclosing_job(Path.cwd()) or ledger.latest()
    if job is not None:
        info("writing into job %s (work/footage)" % job.name)
        return job / "work" / "footage" / name
    return output_dir("footage", create=False) / name


def scenes_dir(video: Path, job_arg: Optional[str] = None) -> Path:
    """Where `footage scenes` writes by default: <job>/work/scenes for --job, the job the video or the
    current folder is in, else the newest job; with no job at all a fresh showtime-out/scenes-<ts>/.
    Never the source's own folder (the user's footage stays untouched)."""
    from .job import ledger
    from .common import output_dir
    if job_arg:
        job = ledger.resolve(job_arg)
    else:
        job = ledger.enclosing_job(video) or ledger.enclosing_job(Path.cwd()) or ledger.latest()
    if job is not None:
        info("writing into job %s (work/scenes)" % job.name)
        return job / "work" / "scenes"
    return output_dir("scenes", create=False)


def cmd_trim(args) -> int:
    from . import ff
    from .footage import util as U
    src = Path(args.video).resolve()
    if not src.is_file():
        raise ShowtimeError("video not found: %s" % src)
    pr = U.probe(src)
    dur = float(pr.get("duration") or 0.0)
    a = max(0.0, float(args.t_from or 0.0))
    b = min(dur, float(args.t_to)) if args.t_to is not None else dur
    if not b > a:
        raise ShowtimeError("nothing to cut: --from %.3f is not before --to %.3f (the clip is %.2fs)" % (a, b, dur))
    ext = ".webm" if args.webm else (src.suffix if args.copy else ".mp4")
    out = Path(args.output).expanduser() if args.output else footage_out(src, "%s.trim%s" % (src.stem, ext))
    out = U.unique_path(out) if out.exists() else out
    out.parent.mkdir(parents=True, exist_ok=True)
    fps = float(pr.get("fps") or 30.0)
    gop = max(1, int(round(float(args.gop) * fps)))
    vf = []
    if args.width:
        vf.append("scale=%d:-2:flags=lanczos" % (int(args.width) // 2 * 2))
    if args.copy:
        cmd = ["-ss", "%.3f" % a, "-i", str(src), "-t", "%.3f" % (b - a), "-map", "0:v:0", "-map", "0:a?",
               "-c", "copy", "-avoid_negative_ts", "make_zero"] + (["-an"] if args.no_audio else [])
    elif args.webm:
        cmd = ["-ss", "%.3f" % a, "-i", str(src), "-t", "%.3f" % (b - a), "-map", "0:v:0"] + \
              ([] if args.no_audio else ["-map", "0:a?"]) + (["-vf", ",".join(vf)] if vf else []) + \
              ["-c:v", "libvpx-vp9", "-b:v", "0", "-crf", str(args.crf or 32), "-row-mt", "1", "-deadline", "good",
               "-cpu-used", "2", "-g", str(gop), "-pix_fmt", "yuv420p"] + \
              (["-an"] if args.no_audio else ["-c:a", "libopus", "-b:a", "128k"])
    else:
        cmd = ["-ss", "%.3f" % a, "-i", str(src), "-t", "%.3f" % (b - a), "-map", "0:v:0"] + \
              ([] if args.no_audio else ["-map", "0:a?"]) + ["-vf", ",".join(vf + [ff.BT709_VF, "format=yuv420p"])] + \
              ["-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf or 18), "-g", str(gop),
               "-keyint_min", str(max(1, gop // 2)), "-bf", "0"] + ff.BT709_TAGS + \
              (["-an"] if args.no_audio else ff.aac_args("192k")) + ["-movflags", "+faststart"]
    ff.run_ffmpeg(cmd + [str(out)])
    res = U.probe(out)
    rep = {"input": str(src), "output": str(out), "from": round(a, 3), "to": round(b, 3),
           "duration": res.get("duration"), "width": res.get("display_width"), "height": res.get("display_height"),
           "size_bytes": out.stat().st_size, "gop_frames": None if args.copy else gop,
           "codec": "copy" if args.copy else ("vp9" if args.webm else "h264")}
    if args.json:
        print_json(rep)
    else:
        info("trimmed %.2f-%.2fs of %s (%s%s) -> %s" % (a, b, src.name, rep["codec"],
                                                     "" if args.copy else ", keyframe every %d frames" % gop, out))
        print(out)
    return 0


def cmd_scenes(args) -> int:
    from .footage import scenes as S
    from .footage import util as U
    p = Path(args.video).resolve()
    if not p.is_file():
        raise ShowtimeError("video not found: %s" % p)
    out_arg = Path(args.out_dir).expanduser() if args.out_dir else None
    as_file = out_arg is not None and out_arg.suffix.lower() in (".png", ".jpg", ".jpeg")
    od = (out_arg.parent if as_file else out_arg) if out_arg else scenes_dir(p, args.job)
    if (args.t_from is not None or args.t_to is not None) and not args.every:
        raise ShowtimeError("--from/--to need --every (a periodic sheet of that range)",
                            hint="showtime footage scenes %s --every 0.25 --from %s --to %s" % (
                                p.name, args.t_from or 0, args.t_to or "<end>"))
    if args.every:
        dur = float(U.probe(p).get("duration") or 0.0)
        plan = S.periodic_plan(dur, args.every, args.t_from or 0.0, args.t_to)
        rng = "" if args.t_from is None and args.t_to is None else ".%g-%gs" % (plan["start"], plan["end"])
        target = out_arg if as_file else od / ("%s%s.every%gs.png" % (p.stem, rng, args.every))
        sheet = S.periodic_sheet(p, target, every=args.every, start=plan["start"], end=plan["end"])
        rep = {"sheet": str(sheet), "frames": len(plan["times"]), "step": round(plan["step"], 3)}
        if plan["capped"]:
            info("note: one frame every %gs would be %d frames; the sheet shows %d (one every %.2fs). Narrow it with "
                 "--from/--to for the density you asked for" % (args.every, plan["wanted"], len(plan["times"]), plan["step"]))
    else:
        rep = S.scenes_with_sheet(p, od, threshold=args.threshold, min_len=args.min_len, method=args.method)
    if args.json:
        print_json(rep)
    else:
        if "scenes" in rep:
            info("%d shot(s): %s" % (len(rep["scenes"]), ", ".join(U.fmt_time(s["start"]) for s in rep["scenes"][:20])))
            print(rep["json"])
        print(rep["sheet"])
    return 0


def cmd_reframe(args) -> int:
    o: Dict[str, Any] = {"aspect": args.aspect, "fit": args.fit}
    rng: Dict[str, Any] = {}
    if args.zoom:
        rng["zoom"] = args.zoom
    if args.focus:
        try:
            x, y = (float(v) for v in args.focus.split(","))
        except ValueError:
            raise ShowtimeError("--focus must be 'x,y' with values 0..1")
        rng["focus"] = {"x": x, "y": y}
    extra: Dict[str, Any] = {"output": o}
    rep = _adhoc_render(args.video, args.output, "." + args.aspect.replace(":", "x"), extra, args.preview) \
        if not rng else _adhoc_render_range(args, extra, rng)
    meta = (rep.get("segment_meta") or [{}])[0] or {}
    if args.json:
        print_json({"output": rep["output"], "fit": meta.get("fit"), "faces": meta.get("faces"),
                    "moving": meta.get("moving"), "size": [rep["width"], rep["height"]]})
    else:
        info("fit %s, faces found in %s detection frames" % (meta.get("fit"), meta.get("faces")))
        print(rep["output"])
    return 0


def _adhoc_render_range(args, extra: Dict[str, Any], rng: Dict[str, Any]) -> Dict[str, Any]:
    from .footage import util as U
    src = Path(args.video).resolve()
    pr = U.probe(src)
    r = {"source": "clip", "start": 0, "end": round(float(pr["duration"]), 3)}
    r.update(rng)
    extra = dict(extra, ranges=[r])
    return _adhoc_render(args.video, args.output, "." + args.aspect.replace(":", "x"), extra, args.preview)


def cmd_denoise(args) -> int:
    from .footage import denoise as D
    from .footage import util as U
    src = Path(args.input).resolve()
    out = Path(args.output) if args.output else footage_out(src, src.stem + ".clean" + src.suffix)
    out = U.unique_path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rep = D.denoise(src, out, method=args.method, strength=args.strength, model=args.model, track=args.audio_track)
    if args.json:
        print_json(rep)
    else:
        info("%s, strength %g (%s): noise floor %.1f -> %.1f dBFS%s; %d channel(s), same length as the source" % (
            rep["method"], rep["strength"], rep["reduction_limit"], rep["noise_floor_before_db"], rep["noise_floor_after_db"],
            ", removed signal %.1f dBFS" % rep["removed_db"] if rep.get("removed_db") is not None else "", rep["channels"]))
        if rep["noise_floor_before_db"] - rep["noise_floor_after_db"] < 1.0:
            info("note: the floor barely moved: there was little steady noise to remove (try --method afftdn for hiss, "
                 "or skip denoise on clean audio)")
        print(rep["output"])
    return 0


def cmd_stabilize(args) -> int:
    from .footage import stabilize as S
    from .footage import util as U
    src = Path(args.video).resolve()
    out = U.unique_path(Path(args.output) if args.output else footage_out(src, src.stem + ".stable.mp4"))
    out.parent.mkdir(parents=True, exist_ok=True)
    rep = S.stabilize(src, out, strength=args.strength, preview=args.preview)
    if args.json:
        print_json(rep)
    else:
        info("stabilised with %s" % rep["method"])
        print(rep["output"])
    return 0


def cmd_view(args) -> int:
    from .common import parse_time
    from .footage import timeline_view as V
    if args.edl:
        edl, video = _view_target(args.edl, args.video)
        pages = V.view_edl(edl, video, args.output)
        if args.json:
            print_json({"pages": [str(p) for p in pages]})
        else:
            for p in pages:
                print(p)
        return 0
    if not args.media:
        raise ShowtimeError("give a media file (or --edl)")
    out_png = args.output
    if not out_png:
        from .footage import util as U
        from .job import ledger
        mp = Path(args.media).resolve()
        if mp.is_file() and ledger.enclosing_job(mp) is None:
            dur = float(U.probe(mp).get("duration") or 0.0)
            s0 = max(0.0, parse_time(args.start) if args.start else 0.0)
            e0 = min(dur, parse_time(args.end)) if args.end else dur
            out_png = str(footage_out(mp, "views/%s_%.1f-%.1f.png" % (mp.stem, s0, e0)))
    out = V.view(args.media, parse_time(args.start) if args.start else None, parse_time(args.end) if args.end else None,
                 out_png, transcript=args.transcript, frames=args.frames,
                 marks=[parse_time(m) for m in args.mark])
    if args.json:
        print_json({"png": str(out)})
    else:
        print(out)
    return 0


def cmd_grade(args) -> int:
    from .footage import grade as G
    from .footage import util as U
    src = Path(args.video).resolve()
    if args.analyze:
        stats = G.analyze(src)
        stats["auto_filter"] = G.auto_filter(stats)
        if args.json:
            print_json(stats)
        else:
            print("mean luma %.2f, shadows %.2f, highlights %.2f, saturation %.1f -> %s" % (
                stats["mean"], stats["low"], stats["high"], stats["sat"], stats["auto_filter"] or "(no correction)"))
        return 0
    spec: Dict[str, Any] = {}
    if args.auto:
        spec["auto"] = True
    if args.preset:
        spec["preset"] = args.preset
    if args.look:
        spec["lut"] = args.look
        spec["strength"] = args.strength
    if not spec:
        spec = {"auto": True}
    if args.compare:
        from . import ff
        if args.output and Path(args.output).suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            raise ShowtimeError("--compare writes a before/after still image, but -o %s is not an image name"
                                % args.output,
                                hint="use -o %s (or drop --compare to write the graded video)"
                                     % Path(args.output).with_suffix(".png").name)
        pr = U.probe(src)
        t = args.at if args.at is not None else float(pr.get("duration") or 0) / 2
        chain = G.build_filter(spec, src, max(0.0, t - 1), 2.0, base_dir=Path.cwd())
        out = Path(args.output) if args.output else U.unique_path(footage_out(src, src.stem + ".grade-compare.png"))
        out.parent.mkdir(parents=True, exist_ok=True)
        vf = ("split=2[a][b];[b]%s[g];[a]scale=960:-2,drawbox=w=iw:h=ih:c=black@0:t=0[a2];[g]scale=960:-2[g2];"
              "[a2][g2]hstack" % (chain or "null"))
        ff.run_ffmpeg(["-ss", "%.3f" % t, "-i", str(src), "-frames:v", "1", "-filter_complex", vf, str(out)])
        if args.json:
            print_json({"png": str(out), "filter": chain})
        else:
            info("left: original, right: graded (%s)" % (chain or "none"))
            print(out)
        return 0
    rep = _adhoc_render(str(src), args.output, ".graded", {"grade": spec, "output": {"fit": "cover"}}, args.preview)
    if args.json:
        print_json({"output": rep["output"]})
    else:
        print(rep["output"])
    return 0


def cmd_luts(args) -> int:
    from .footage import luts as L
    if args.preview:
        from . import ff
        from .footage import util as U
        from .footage.scenes import contact_sheet  # noqa: F401 - PIL present
        from PIL import Image, ImageDraw
        from .footage.fontfiles import pil_font
        import tempfile
        src = Path(args.preview).resolve()
        pr = U.probe(src)
        t = args.at if args.at is not None else float(pr.get("duration") or 0) / 2
        tiles = [("original", None)] + [(n, L.ensure(n, args.strength)) for n in L.LOOKS]
        imgs = []
        with tempfile.TemporaryDirectory(prefix="st-luts-") as td:
            base = Path(td) / "frame.png"
            ff.run_ffmpeg(["-ss", "%.3f" % t, "-i", str(src), "-frames:v", "1", "-vf", "scale=480:-2", str(base)])
            for name, cube in tiles:
                if cube is None:
                    imgs.append((name, Image.open(base).convert("RGB")))
                    continue
                o = Path(td) / (name + ".png")
                ff.run_ffmpeg(["-i", str(base), "-vf", L.cube_filter(cube), str(o)])
                imgs.append((name, Image.open(o).convert("RGB")))
        w, h = imgs[0][1].size
        cols = 4
        rows = (len(imgs) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * w + (cols + 1) * 8, rows * (h + 30) + 8), (18, 18, 20))
        d = ImageDraw.Draw(sheet)
        for k, (name, im) in enumerate(imgs):
            r, c = divmod(k, cols)
            x, y = 8 + c * (w + 8), 8 + r * (h + 30)
            sheet.paste(im, (x, y))
            d.text((x + 2, y + h + 5), name, fill=(230, 230, 230), font=pil_font(18))
        out = Path(args.output) if args.output else U.unique_path(footage_out(src, src.stem + ".looks.png"))
        out.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out)
        if args.json:
            print_json({"png": str(out), "strength": args.strength, "looks": list(L.LOOKS)})
        else:
            print(out)
        return 0
    if args.write:
        paths = [str(L.ensure(n, args.strength)) for n in L.LOOKS]
        if args.json:
            print_json({"luts": paths})
        else:
            for p in paths:
                print(p)
        return 0
    rows = L.listing()
    if args.json:
        print_json(rows)
    else:
        for r in rows:
            print("%-14s %s" % (r["name"], r["description"]))
        print("\nUse: EDL \"grade\": {\"lut\": \"teal-orange\", \"strength\": 0.6}  or  "
              "`showtime footage grade clip.mp4 --look teal-orange`", file=sys.stderr)
    return 0


def cmd_probe(args) -> int:
    from .footage import util as U
    pr = dict(U.probe(args.media))
    pr["hdr"] = str(pr.get("color_transfer") or "") in ("smpte2084", "arib-std-b67")
    if pr.get("vp_alpha") and str(pr.get("pix_fmt") or "").startswith("yuv4"):
        # VP8/VP9 keep alpha in a side channel (ALPHA_MODE=1): ffprobe's native decoder reports the colour
        # planes only; the file really is yuva (libvpx decodes the alpha)
        pr["pix_fmt_stream"] = pr["pix_fmt"]
        pr["pix_fmt"] = "yuva" + str(pr["pix_fmt"])[3:]
        pr["alpha"] = "side channel (VP9/VP8 ALPHA_MODE=1)"
    print_json(pr)
    return 0


def cmd_autozoom(args) -> int:
    try:
        from .footage import autozoom  # provided by the capture module
    except ImportError:
        raise ShowtimeError("autozoom is not installed yet (it ships with the capture module)")
    main = getattr(autozoom, "main", None)
    if not callable(main):
        raise ShowtimeError("st.footage.autozoom has no main(argv) entry point")
    rest = list(args.rest or [])
    return int(main(rest) or 0)

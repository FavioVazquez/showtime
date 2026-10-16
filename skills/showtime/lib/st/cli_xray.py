"""`showtime xray`: measure a filmed clip (sound onsets, camera tracking), or bring events from a data stream, and
check a finished film against it."""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Optional

from .common import ShowtimeError, log, print_json

COMMANDS = {
    "xray": "Measure what happens in a filmed clip (each hit's exact frame, the object's motion) and verify the finished film",
}

_F = argparse.RawDescriptionHelpFormatter


def register(sub: argparse._SubParsersAction) -> None:
    x = sub.add_parser("xray", help=COMMANDS["xray"], formatter_class=_F, description=(
        "X-ray a real thing you filmed (a typewriter, a music box, a guitar): measure every hit from the clip's\n"
        "own sound and picture so the drawing inside it lands on the exact frame, then check the finished film.\n\n"
        "  analyze   clip -> <job>/xray/xray.json (events with their frame) + check.jpg (look at it before building);\n"
        "            a recording with no picture (a WAV) works too: the page draws the picture side\n"
        "  import    events.csv|json -> <job>/xray/xray.json: event times measured in a data stream, mapped to film time\n"
        "  notes     clip -> <job>/xray/notes.json (the notes played, tempo, key, chords, voices) + notes.mid, notes.musicxml,\n"
        "            check-notes.jpg (a piano roll over the waveform)\n"
        "  verify    job -> reads the film back: the sync marker on every frame, the audio against the clip,\n"
        "            optionally the smoothness of a scrolling band; writes the xray section of the job receipt"),
        epilog=("Examples:\n"
                "  showtime xray analyze typewriter.mp4 --job typewriter\n"
                "  showtime xray analyze clip.mp4 --from 2 --to 11 --min-gap 0.15 --sensitivity 0.6\n"
                "  showtime xray analyze clip.mp4 --track --region '420,300 1500,310 1480,880 440,870' --ref-time 1.0\n"
                "  showtime xray import peaks.csv --job chirp --time-map 100,-0.14 --source chirp.wav\n"
                "  showtime xray notes guitar.mp4 --job guitar --instrument guitar\n"
                "  showtime xray verify typewriter --video final.mp4\n"))
    s = x.add_subparsers(dest="xray_cmd", metavar="<subcommand>")

    a = s.add_parser("analyze", help="clip -> xray.json (events: time, frame, strength, band) + check.jpg", formatter_class=_F,
                     description=(
                         "Detect the hits in a clip's sound: a high-passed RMS envelope on a 1 ms grid, bursts above an\n"
                         "adaptive floor, each onset = the first millisecond within 6 dB of the burst's peak. Hits closer\n"
                         "than --min-gap are merged (the first stays; the rest are listed under `dropped` with the reason).\n"
                         "event frame = floor(t * fps) of the clip. Look at check.jpg before you build on it.\n\n"
                         "--track also follows the object through the clip (KLT points inside --region, minus the --mask\n"
                         "polygons of moving parts, frame-to-frame homographies composed outwards from the frame at\n"
                         "--ref-time) and writes one 3x3 per frame under xray.json \"track\" (the whole clip, not only\n"
                         "--from/--to). Points are x,y in the clip's pixels, read off the frame at --ref-time."),
                     epilog="Writes <job>/xray/xray.json and check.jpg (a new job when --job is not given).")
    a.add_argument("clip", help="the video you filmed (with its sound), or a recording with no picture (a WAV)")
    a.add_argument("--job", help="job folder or name (default: a new showtime-out/xray-<timestamp>/)")
    a.add_argument("--from", dest="t_from", type=float, default=0.0, metavar="S", help="start of the part to analyze, seconds (default 0)")
    a.add_argument("--to", dest="t_to", type=float, default=None, metavar="S", help="end of the part to analyze, seconds")
    a.add_argument("--min-gap", type=float, default=None, metavar="S",
                   help="closest two hits may be (default 0.12 s; 0.06 s with the flux engine)")
    a.add_argument("--engine", choices=["auto", "envelope", "flux"], default="auto",
                   help="envelope: separate hits (clicks, strikes); flux: spectral flux for dense or sustained sound (music, "
                        "plucks over a bed); auto (default): envelope, flux when it finds under 0.3 events per second of "
                        "sustained sound. xray.json detector.engine and .note say which ran and why")
    a.add_argument("--sensitivity", type=float, default=0.5, metavar="0-1",
                   help="0..1, higher finds quieter hits (default 0.5)")
    a.add_argument("--track", action="store_true", help="also track the object (needs --region and --ref-time)")
    a.add_argument("--region", metavar='"x,y x,y ..."', help="the object's outline on the reference frame (3+ points)")
    a.add_argument("--ref-time", type=float, default=None, metavar="T", help="the time of the reference frame the region is drawn on")
    a.add_argument("--mask", action="append", default=[], metavar='"x,y ..."',
                   help="a polygon of a moving part to leave out of the tracking (repeatable)")
    a.add_argument("--fps", type=float, default=None, metavar="N",
                   help="a recording with no picture: the film's frame rate the events land on (default 30)")
    a.add_argument("-o", "--out", metavar="DIR", help="write the files here (default <job>/xray)")
    a.add_argument("--json", action="store_true", help="print xray.json")
    a.set_defaults(func=cmd_analyze)

    im = s.add_parser("import", help="events from a data stream (CSV or JSON of times) -> xray.json", formatter_class=_F,
                      description=(
                          "Write xray.json from event times measured in a data stream (peaks of a signal, a sensor log,\n"
                          "a list of times) instead of from the clip's sound. Film time t = (t_data - T0) x SLOW\n"
                          "(--time-map SLOW,T0: SLOW film seconds per data second, data time T0 at film time 0); the\n"
                          "event's frame = floor(t * fps). xray.json says detector.engine \"data\" and how (detector.note).\n\n"
                          "Input: a CSV with a header (the time column is t, time, t_data or --column; no header: the first\n"
                          "column) or a JSON list of times, of objects, or {\"events\": [...]}. Other columns travel with each\n"
                          "event. Events before film time 0 or after the source's end are listed under `dropped`.\n"
                          "--source is the clip or recording the film plays (a sonified data stream: the same time map):\n"
                          "its fps, length and sha256, and verify finds it."),
                      epilog=("Writes <job>/xray/xray.json and check.jpg (the source's waveform with the imported ticks).\n"
                              "Example:\n  showtime xray import peaks.csv --job chirp --time-map slow=100,t0=-0.14 --source chirp.wav"))
    im.add_argument("events", help="the events: a CSV with a time column, or a JSON list (up to 50 MB and 100,000 events)")
    im.add_argument("--job", help="job folder or name (default: a new showtime-out/xray-<timestamp>/)")
    im.add_argument("--time-map", metavar="SLOW,T0", help="film t = (t_data - T0) x SLOW (default 1,0: data time is film time); "
                                                          "also slow=100,t0=-0.14; leave a part empty for its default (,5 is t0 5)")
    im.add_argument("--column", metavar="NAME", help="the time column (default t, time or t_data)")
    im.add_argument("--strength", metavar="NAME", help="a column whose size sets each event's strength (scaled to the largest)")
    im.add_argument("--source", metavar="CLIP", help="the clip or recording the film plays (its fps, length, sha256)")
    im.add_argument("--fps", type=float, default=None, metavar="N",
                    help="the frame rate the events land on, without a video --source (default 30)")
    im.add_argument("--duration", type=float, default=None, metavar="S", help="the film-time length, without --source")
    im.add_argument("--note", help="how the events were measured, in a sentence (default: the file, column and time map)")
    im.add_argument("-o", "--out", metavar="DIR", help="write the files here (default <job>/xray)")
    im.add_argument("--json", action="store_true", help="print xray.json")
    im.set_defaults(func=cmd_import)

    n = s.add_parser("notes", help="clip -> notes.json (pitch, onset, tempo map, key, chords) + MIDI, MusicXML, check-notes.jpg",
                     formatter_class=_F, description=(
                         "Read the notes an instrument plays (guitar, piano, music box) from the clip's sound, or from a WAV\n"
                         "recording with no picture, with Basic Pitch (ONNX, no TensorFlow). Every note keeps frame = floor(t * fps): the\n"
                         "clip's frame rate, or the 30 fps grid for a recording with no picture. Adds a smooth\n"
                         "tempo map (scroll with it, never snap to the last note), eighth-note quantization, the key, a chord per\n"
                         "beat, the melody (loudest note from E4 up) and bass voices, and with --instrument guitar the string,\n"
                         "fret and finger of every note (standard tuning, open position first).\n"
                         "Look at check-notes.jpg before you build on it."),
                     epilog="Writes <job>/xray/notes.json, notes.mid, notes.musicxml, check-notes.jpg.")
    n.add_argument("clip", help="the video you filmed (with its sound), or a WAV or other recording with no picture")
    n.add_argument("--job", help="job folder or name (default: a new showtime-out/xray-<timestamp>/)")
    n.add_argument("--from", dest="t_from", type=float, default=0.0, metavar="S", help="start of the part to read, seconds (default 0)")
    n.add_argument("--to", dest="t_to", type=float, default=None, metavar="S", help="end of the part to read, seconds")
    n.add_argument("--instrument", choices=["auto", "guitar", "piano", "musicbox", "drums"], default="auto",
                   help="auto tells a music box (high register) from a piano; guitar adds strings and frets and must be asked for; drums sorts the hits by sound (kick, snare, hats, tom, crash)")
    n.add_argument("-o", "--out", metavar="DIR", help="write the files here (default <job>/xray)")
    n.add_argument("--json", action="store_true", help="print notes.json")
    n.set_defaults(func=cmd_notes)

    v = s.add_parser("verify", help="read a finished film back against xray.json (marker, audio, smoothness)", formatter_class=_F,
                     description=(
                         "1. Marker: the 6x6 px square at (width-10, height-10) of the film is read on every frame; it is\n"
                         "   white on the film frames of the events (event frame + offset) and black otherwise.\n"
                         "2. Audio: the film's sound against the clip's (first 12 s), cross-correlated: the lag in ms.\n"
                         "3. With --band x,y,w,h: the frame-to-frame horizontal shift of that band; stalls (0 px while the\n"
                         "   median speed is over 1 px) and jumps (the shift changes by over 3 px).\n\n"
                         "Writes the xray section of the job receipt (receipt.json) and <job>/xray/verify.json, prints the\n"
                         "end-card line. Exit 1 when a FAIL condition holds: a marker is present and an event is missing or\n"
                         "extra, or the audio is more than 20 ms from the clip. No marker at all is a WARN (unverified)."),
                     epilog="Example:\n  showtime xray verify my-job --video my-job/final.mp4 --band 0,820,1920,200")
    v.add_argument("job", nargs="?", help="job folder or name (default: the current or newest job)")
    v.add_argument("--video", metavar="MP4", help="the film (default: the job's latest final or preview)")
    v.add_argument("--source", metavar="CLIP", help="the clip it was measured from (default: remembered by analyze)")
    v.add_argument("--offset-frames", type=int, default=None, metavar="N",
                   help="the film frame of the clip's frame 0 (default: the project's showtime.json \"xray\".offset_frames, else 0)")
    v.add_argument("--skip", metavar="i,i", help="event indexes (i in xray.json) that are not the object's and carry no marker "
                   "(default: the project's showtime.json \"xray\".skip)")
    v.add_argument("--band", metavar="x,y,w,h", help="a scrolling band of the film to check for stalls and jumps "
                                                     "(default: the project's showtime.json \"xray\".band rows, full width)")
    v.add_argument("--json", action="store_true", help="print the result as JSON")
    v.set_defaults(func=cmd_verify)
    x.set_defaults(func=lambda args: (x.print_help() or 2))


def _job_for(arg: Optional[str]) -> Path:
    from .job import ledger
    if arg:
        p = Path(arg).expanduser()
        if os.name != "nt" and re.match(r"^[A-Za-z]:[\\/]", arg):
            raise ShowtimeError("--job %s looks like a Windows path, which does not exist on this system" % arg,
                                hint="pass a job folder or id on this machine")
        bare = not any(sep in arg for sep in ("/", "\\")) and not arg.startswith((".", "~"))
        if p.exists() or bare:
            try:
                return ledger.resolve(arg)
            except ShowtimeError:
                if p.exists():
                    raise
        p.mkdir(parents=True, exist_ok=True)
        data = ledger.new_data("xray", "quick", "x-ray a clip", p.resolve(), None)
        data["history"][-1]["event"] = "job created by showtime xray"
        ledger.save(p, data)
        return p.resolve()
    here = ledger.enclosing_job(Path.cwd())
    d, _ = ledger.init("xray", goal="x-ray a clip", base=here.parent if here is not None else None)
    return d


def cmd_analyze(args: argparse.Namespace) -> int:
    from . import xray
    track = None
    if args.track:
        if not args.region or args.ref_time is None:
            raise ShowtimeError("--track needs --region and --ref-time",
                                hint='--region "x,y x,y x,y x,y" (the outline on the frame at --ref-time), e.g. --ref-time 1.0')
        track = {"region": xray.parse_points(args.region), "ref_time": args.ref_time,
                 "masks": [xray.parse_points(m) for m in args.mask]}
    elif args.region or args.mask or args.ref_time is not None:
        raise ShowtimeError("--region, --mask and --ref-time only work with --track", hint="add --track")
    if not 0.0 <= args.sensitivity <= 1.0:
        raise ShowtimeError("--sensitivity is 0..1 (got %g)" % args.sensitivity)
    if args.min_gap is not None and args.min_gap <= 0:
        raise ShowtimeError("--min-gap must be above 0 seconds")
    xray.validate_clip(args.clip)
    xray.check_source(args.clip, args.fps, track=bool(track))   # refused before a job exists
    job = _job_for(args.job)
    out = Path(args.out) if args.out else job / "xray"
    doc = xray.analyze(args.clip, out, t_from=args.t_from, t_to=args.t_to, min_gap=args.min_gap, engine=args.engine,
                       sensitivity=args.sensitivity, track=track, fps=args.fps)
    try:
        from .job import ledger
        ledger.note(job, stage="xray", outputs=[], event="xray analyze: %d events from %s" % (len(doc["events"]), doc["source"]["file"]))
    except Exception:  # noqa: BLE001 - the ledger is a convenience
        pass
    if args.json:
        print_json(doc)
        return 0
    ev = doc["events"]
    log("xray: %d events%s from %s (%d dropped)" % (len(ev), " (%.3f s to %.3f s)" % (ev[0]["t"], ev[-1]["t"]) if ev else "",
                                                    doc["source"]["file"], len(doc["dropped"])))
    if doc["track"]:
        log("xray: tracked %d frames from reference frame %d" % (len(doc["track"]["H"]), doc["track"]["ref_frame"]))
    print(out / "xray.json")
    print(out / "check.jpg")
    log("look at check.jpg before building: every tick should sit on a hit you can hear")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    from . import xray
    events = Path(args.events)
    kw = dict(time_map=xray.parse_time_map(args.time_map), source=args.source, fps=args.fps, duration=args.duration,
              column=args.column, strength=args.strength, note=args.note)
    doc, x = xray.build_import(events, **kw)        # every refusal comes before a job exists; the source is read once
    job = _job_for(args.job)
    out = Path(args.out) if args.out else job / "xray"
    xray.write_import(doc, x, events, out, args.source)
    try:
        from .job import ledger
        ledger.note(job, stage="xray", outputs=[], event="xray import: %d events from %s" % (len(doc["events"]), events.name))
    except Exception:  # noqa: BLE001 - the ledger is a convenience
        pass
    if args.json:
        print_json(doc)
        return 0
    ev = doc["events"]
    log("xray: %d events (%.3f s to %.3f s, frames %d to %d) from %s; %d dropped" % (
        len(ev), ev[0]["t"], ev[-1]["t"], ev[0]["frame"], ev[-1]["frame"], events.name, len(doc["dropped"])))
    print(out / "xray.json")
    print(out / "check.jpg")
    log("look at check.jpg before building: every tick should sit where the data says an event is")
    return 0


def cmd_notes(args: argparse.Namespace) -> int:
    from . import xray, xray_music
    xray.validate_clip(args.clip)
    job = _job_for(args.job)
    out = Path(args.out) if args.out else job / "xray"
    doc = xray_music.analyze(args.clip, out, t_from=args.t_from, t_to=args.t_to, instrument=args.instrument)
    try:
        from .job import ledger
        ledger.note(job, stage="xray", outputs=[], event="xray notes: %d notes from %s" % (len(doc["notes"]), doc["source"]["file"]))
    except Exception:  # noqa: BLE001 - the ledger is a convenience
        pass
    if args.json:
        print_json(doc)
        return 0
    if doc["instrument"] == "drums":
        from collections import Counter
        c = Counter(d["piece"] for d in doc["drums"])
        log("xray: %d drum hits (%s), %.0f bpm; a classifier of sound types, not a transcription" % (
            len(doc["drums"]), ", ".join("%d %s" % (v, k) for k, v in sorted(c.items())), doc["tempo"]["bpm"]))
    else:
        log("xray: %d notes (%s), %d melody, %d bass, %.0f bpm, key %s, %d chords" % (
            len(doc["notes"]), doc["instrument"], len(doc["voices"]["melody"]), len(doc["voices"]["bass"]),
            doc["tempo"]["bpm"], doc["key"] or "-", len(doc["chords"])))
    for name in ("notes.json", "notes.mid", "notes.musicxml", "check-notes.jpg"):
        print(out / name)
    log("look at check-notes.jpg before building: every bar should sit on a note you can hear")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from . import xray
    from .job import ledger
    job = ledger.resolve(args.job)
    band = None
    if args.band:
        try:
            band = [int(float(v)) for v in args.band.split(",")]
        except ValueError:
            band = []
        if len(band) != 4:
            raise ShowtimeError("--band is x,y,w,h in film pixels (got %r)" % args.band)
    skip = None
    if args.skip is not None:
        try:
            skip = [int(v) for v in args.skip.replace(" ", "").split(",") if v != ""]
        except ValueError:
            raise ShowtimeError("--skip is event indexes like 0,3 (got %r)" % args.skip)
    res = xray.verify(job, args.video, args.source, args.offset_frames, band, skip)
    xray.add_to_receipt(job)
    if args.json:
        print_json(res)
    else:
        print(res["line"])
        for n in res["notes"]:
            log("xray: " + n)
        for f in res["findings"]:
            log("%s %s: %s" % (f["severity"], f["rule"], f["message"]))
        sm = res.get("smoothness")
        if sm:
            log("smoothness: %d frames, median %.1f px/frame, %d stalls, %d jumps" % (sm["frames"], sm["median_px"], sm["stalls"], sm["jumps"]))
    return 1 if res["status"] == "FAIL" else 0

"""`showtime voice ...`: local narration (TTS with word timings), alignment, mastering.

Heavy imports (numpy, onnxruntime, kokoro) happen inside the handlers, so
`showtime --help` stays fast and a missing dependency only affects these
commands.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .common import ShowtimeError, print_json, slugify

COMMANDS = {
    "voice": "Narration: text-to-speech with word timings, script -> timed VO, alignment, mastering",
}

_F = argparse.RawDescriptionHelpFormatter


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    k = 2
    while True:
        c = path.with_name("%s-%d%s" % (path.stem, k, path.suffix))
        if not c.exists():
            return c
        k += 1


def _read_text(args: argparse.Namespace, what: str = "text") -> str:
    parts: List[str] = []
    if getattr(args, "file", None):
        p = Path(args.file)
        if not p.is_file():
            raise ShowtimeError("text file not found: %s" % p)
        parts.append(p.read_text(encoding="utf-8-sig"))
    t = getattr(args, "text", None)
    if t:
        if t == "-":
            parts.append(sys.stdin.read())
        elif len(t) < 260 and Path(t).suffix.lower() in (".txt", ".md") and Path(t).is_file():
            parts.append(Path(t).read_text(encoding="utf-8-sig"))
        else:
            parts.append(t)
    text = " ".join(" ".join(parts).split())
    if not text:
        raise ShowtimeError("no %s given" % what, hint="pass it as an argument, with -f FILE, or '-' for stdin")
    return text


def _say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def register(sub: argparse._SubParsersAction) -> None:
    v = sub.add_parser("voice", help=COMMANDS["voice"], formatter_class=_F, description=(
        "Local narration with exact word timings (Kokoro by default; nothing leaves this machine).\n\n"
        "  list     voices by language, with quality grades and recommendations\n"
        "  say      speak a text -> WAV + .words.json (word start/end times)\n"
        "  script   a script (JSON/Markdown) -> per-line clips, vo.wav, timeline.json, vo.srt\n"
        "  align    word timings for any recording + its script\n"
        "  master   voice chain: high-pass, de-ess, gentle compression, -16 LUFS\n"
        "  ipa      show the phonemes espeak-ng produces (to write pronunciation fixes)\n"
        "  bench    measure speed (RTF) and speaking rate (words/sec) on this machine\n"
        "  cache    size of the speech cache (capped at SHOWTIME_TTS_CACHE_MB, default 1024); --clear empties it\n"
        "  cues     timeline.json -> a JS table (lines, words) a canvas film's cues read, so a re-voice re-times it"),
        epilog="Examples:\n"
               "  showtime voice say \"Meet Showtime.\" -o vo.wav\n"
               "  showtime voice say \"Hola, bienvenidos.\" -v ef_dora -o hola.wav\n"
               "  showtime voice script narration.md -o voice/\n"
               "  showtime voice align take.wav \"the exact words spoken\" -o take.words.json\n"
               "  showtime voice master raw.wav -o vo.wav\n"
               "Markup inside any text: [pause 0.4]  [Showtime](/ʃˈoʊtaɪm/)  [SQL](sequel)  <!-- ignored -->")
    s = v.add_subparsers(dest="voice_cmd", metavar="<subcommand>")

    # list -----------------------------------------------------------------
    p = s.add_parser("list", help="list voices (Kokoro, Supertonic, Piper)", formatter_class=_F,
                     description="List voices with language, gender, upstream quality grade and notes.\n"
                                 "Kokoro grades are the model author's (A best ... F); Spanish and Portuguese "
                                 "voices were never graded.",
                     epilog="Examples:\n  showtime voice list\n  showtime voice list --lang es\n"
                            "  showtime voice list --engine piper --json")
    p.add_argument("--lang", "-l", help="filter by language (en, en-gb, es, fr, it, pt, hi, ja, zh)")
    p.add_argument("--engine", "-e", choices=["kokoro", "supertonic", "piper"], help="only this engine")
    p.add_argument("--all", action="store_true", help="include low-grade Kokoro voices (D/F)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_list)

    # say ------------------------------------------------------------------
    p = s.add_parser("say", help="speak text -> WAV + word timings", formatter_class=_F,
                     description="Synthesize speech. Writes OUT.wav (mastered to -16 LUFS, 48 kHz, unless --raw) and "
                                 "OUT.words.json (transcript format: every word with start/end seconds).\n"
                                 "Unchanged text is served from the cache instantly.",
                     epilog="Examples:\n"
                            "  showtime voice say \"Meet Showtime, the studio in your terminal.\" -o vo.wav\n"
                            "  showtime voice say -f intro.txt -v am_michael --style upbeat -o intro.wav\n"
                            "  showtime voice say \"Te presentamos Showtime.\" -v ef_dora -o es.wav\n"
                            "  showtime voice say \"Fits the scene.\" --fit 2.5 -o line.wav   # tune speed to ~2.5 s\n"
                            "  showtime voice say \"Blend.\" -v af_heart:60+am_michael:40 -o blend.wav\n"
                            "  showtime voice say \"Hola\" -v supertonic:F1 --lang es -o st.wav  # needs setup --with supertonic")
    p.add_argument("text", nargs="?", help="text to speak ('-' reads stdin; a .txt/.md path reads the file)")
    p.add_argument("-f", "--file", help="read the text from a file")
    p.add_argument("-v", "--voice", help="voice id (default: af_heart, or the language's default)")
    p.add_argument("-s", "--speed", type=float, default=1.0, help="speaking rate, 0.5-2.0 (default 1.0)")
    p.add_argument("-l", "--lang", help="language override (default: from the voice)")
    p.add_argument("-e", "--engine", choices=["auto", "kokoro", "supertonic", "piper"], default="auto",
                   help="TTS engine (default: from the voice id)")
    p.add_argument("--style", default="neutral", help="delivery: neutral, calm, warm, upbeat, energetic, "
                                                     "tutorial, documentary, trailer (default neutral)")
    p.add_argument("--fit", type=float, metavar="SECONDS", help="adjust the speed so the speech lasts about this long")
    p.add_argument("--lexicon", action="append", default=[], metavar="FILE", help="extra pronunciation lexicon JSON")
    p.add_argument("--raw", action="store_true", help="skip mastering (engine's native rate, raw level)")
    p.add_argument("--lufs", type=float, default=-16.0, help="mastering loudness target (default -16)")
    p.add_argument("--no-cache", action="store_true", help="always re-synthesize")
    p.add_argument("-o", "--output", help="output .wav (default ./voice-<text>.wav, never overwritten)")
    p.add_argument("--json", action="store_true", help="print the full result as JSON")
    p.set_defaults(func=cmd_say)

    # script ---------------------------------------------------------------
    p = s.add_parser("script", help="script -> per-line clips + vo.wav + timeline.json", formatter_class=_F,
                     description="Synthesize a narration script. Output folder:\n"
                                 "  vo.wav            all lines placed with their pauses, mastered (48 kHz)\n"
                                 "  timeline.json     every line's start/end/slot and every word's times\n"
                                 "  vo.words.json     transcript format (for `showtime captions`)\n"
                                 "  vo.srt            ready-made captions\n"
                                 "  lines/NN-id.wav   each line on its own (+ .words.json, line-relative)\n"
                                 "Set scene durations from timeline.json lines[].slot.duration.\n"
                                 "Only changed lines are re-synthesized (content-hash cache).",
                     epilog="Script formats (see references/voice.md):\n"
                            "  JSON: {\"voice\": \"af_heart\", \"gap\": 0.4, \"lines\": [{\"id\": \"hook\", \"text\": \"...\"}]}\n"
                            "  Markdown: front matter (voice:, gap:), then '## id {voice=.. speed=.. pause_after=..}'\n"
                            "            headings each followed by the line's text.\n"
                            "Examples:\n"
                            "  showtime voice script narration.md\n"
                            "  showtime voice script vo.json -o project/voice --voice am_michael --gap 0.5\n"
                            "  showtime voice script narration.md -o project/voice --fit 15   # land on 15 s\n"
                            "--fit S: all lines speed up/slow down together within 0.85-1.15x, then pauses shrink\n"
                            "(>= 0.2 s), then it prints how many words to cut; a short script gets tail silence.")
    p.add_argument("script", help="script file (.json, .md or .txt)")
    p.add_argument("-o", "--output", help="output folder (default: voice/ next to the script)")
    p.add_argument("-v", "--voice", help="default voice for lines without one")
    p.add_argument("-s", "--speed", type=float, help="default speed")
    p.add_argument("--style", help="default delivery style")
    p.add_argument("-l", "--lang", help="default language")
    p.add_argument("--gap", type=float, help="default pause between lines in seconds (default 0.35)")
    p.add_argument("--lead-in", type=float, help="silence before the first line (default 0)")
    p.add_argument("--tail", type=float, help="silence after the last line (default 0.6)")
    p.add_argument("--lufs", type=float, help="loudness of vo.wav (default -16)")
    p.add_argument("--no-master", action="store_true", help="leave vo.wav unmastered")
    p.add_argument("--fit", type=float, metavar="SECONDS",
                   help="fit the whole narration to this length (speed 0.85-1.15x, then shorter pauses, "
                        "then says how many words to cut)")
    p.add_argument("--lexicon", action="append", default=[], metavar="FILE", help="extra pronunciation lexicon")
    p.add_argument("--json", action="store_true", help="print timeline.json")
    p.set_defaults(func=cmd_script)

    # align ----------------------------------------------------------------
    p = s.add_parser("align", help="word timings for a recording + its script", formatter_class=_F,
                     description="Force-align known text to audio (any WAV/MP3/M4A/video). The script's own words "
                                 "and punctuation are kept.\n"
                                 "Methods: ctc (English, ~20-40 ms), tts (Kokoro reference + DTW, any Kokoro "
                                 "language, ~20-40 ms on TTS), whisper (~100+ ms), even (spread).",
                     epilog="Examples:\n"
                            "  showtime voice align take.wav \"Welcome to the demo.\" -o take.words.json\n"
                            "  showtime voice align vo.mp3 -f script.txt --lang es\n"
                            "  showtime voice align clip.mp4 -f lines.txt --method whisper --json")
    p.add_argument("audio", help="audio or video file")
    p.add_argument("text", nargs="?", help="the spoken text (or -f FILE)")
    p.add_argument("-f", "--file", help="read the text from a file")
    p.add_argument("-l", "--lang", default="en", help="language (default en)")
    p.add_argument("-m", "--method", default="auto", choices=["auto", "ctc", "tts", "whisper", "even"],
                   help="alignment method (default auto: ctc for English, then tts, whisper, even)")
    p.add_argument("--voice", help="Kokoro reference voice for --method tts (default: the language's default)")
    p.add_argument("--no-snap", action="store_true", help="do not snap word edges to the audio energy")
    p.add_argument("-o", "--output", help="output words JSON (default AUDIO.words.json, never overwritten)")
    p.add_argument("--json", action="store_true", help="print the words JSON")
    p.set_defaults(func=cmd_align)

    # master ---------------------------------------------------------------
    p = s.add_parser("master", help="voice mastering chain to a loudness target", formatter_class=_F,
                     description="High-pass, de-ess, gentle compression, then two-pass loudness normalization "
                                 "(default -16 LUFS, -1.5 dBTP, 48 kHz, 24-bit mono WAV).",
                     epilog="Presets: voice (-16), podcast (-16), youtube (-14), broadcast (-23), gentle (no compression)\n"
                            "Examples:\n  showtime voice master raw.wav -o vo.wav\n"
                            "  showtime voice master take.m4a -o take.wav --preset podcast\n"
                            "  showtime voice master vo.wav -o vo-yt.wav --lufs -14 --json")
    p.add_argument("input", help="input audio (any format ffmpeg reads)")
    p.add_argument("-o", "--output", help="output .wav (default INPUT.master.wav, never overwritten)")
    p.add_argument("--preset", default="voice", help="voice, podcast, youtube, broadcast, gentle (default voice)")
    p.add_argument("--lufs", type=float, help="integrated loudness target (overrides the preset)")
    p.add_argument("--tp", type=float, help="true-peak ceiling in dBTP (overrides the preset)")
    p.add_argument("--stereo", action="store_true", help="write stereo instead of mono")
    p.add_argument("--json", action="store_true", help="print the report as JSON")
    p.set_defaults(func=cmd_master)

    # ipa ------------------------------------------------------------------
    p = s.add_parser("ipa", help="show phonemes for text (for pronunciation fixes)", formatter_class=_F,
                     description="Print the IPA espeak-ng produces per word, and what the lexicon overrides; the\n"
                                 "phrase line is what the voice reads, overrides included. Copy a line into\n"
                                 "lexicon.json and edit it to fix a pronunciation. The lexicon.json read is the one in\n"
                                 "the current folder (or its one sub-folder that has one), or in --project; `voice\n"
                                 "script` reads the one next to its script or one folder up.",
                     epilog="Examples:\n  showtime voice ipa \"Showtime runs on Kubernetes\"\n"
                            "  showtime voice ipa \"Te presentamos Showtime\" --lang es")
    p.add_argument("text", help="words to phonemize (inline [word](/ipa/) and [word](respelling) work too)")
    p.add_argument("-l", "--lang", help="language (default en, or the voice's)")
    p.add_argument("-v", "--voice", help="take the language from this voice")
    p.add_argument("--project", metavar="DIR", help="use this project's lexicon.json / brand.json (a folder or the "
                   "script file; default: the current folder, or its one sub-folder with a lexicon.json)")
    p.add_argument("--lexicon", action="append", default=[], metavar="FILE")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ipa)

    # bench ----------------------------------------------------------------
    p = s.add_parser("bench", help="measure RTF and words/sec per voice on this machine", formatter_class=_F,
                     description="Synthesize a fixed paragraph per voice (uncached) and report the real-time factor "
                                 "(synthesis seconds / audio seconds; below 1 is faster than real time) and the "
                                 "speaking rate at speed 1.0, useful for word budgets.",
                     epilog="Examples:\n  showtime voice bench\n  showtime voice bench -v af_heart,am_michael,ef_dora --json")
    p.add_argument("-v", "--voices", default="af_heart,am_michael,bf_emma,ef_dora",
                   help="comma-separated voice ids; VOICE@LANG sets the language (supertonic:F1@es)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_bench)

    # cache ----------------------------------------------------------------
    p = s.add_parser("cache", help="show or clear the speech cache", formatter_class=_F,
                     description="Synthesized lines are cached by content hash so unchanged lines are free to "
                                 "re-run. The cache is capped (SHOWTIME_TTS_CACHE_MB, default 1024 MB): the least "
                                 "recently used lines are dropped first.",
                     epilog="Examples:\n  showtime voice cache\n  showtime voice cache --clear\n"
                            "  showtime voice cache --prune --max-mb 200")
    p.add_argument("--clear", action="store_true", help="delete every cached line")
    p.add_argument("--prune", action="store_true", help="trim to the cap now (least recently used first)")
    p.add_argument("--max-mb", type=float, help="cap for --prune (default SHOWTIME_TTS_CACHE_MB or 1024)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_cache)

    p = s.add_parser("cues", help="timeline.json -> a JS table of line and word times for canvas cue tables",
                     formatter_class=_F,
                     description="Writes a small script that defines `var VO = {duration, lines: {<id>: {start, end, "
                                 "speech_start, speech_end, slot_end}}, words: {<id>: [[text, start, end], ...]}}` "
                                 "(seconds; --offset added to every time). Load it before cues.js and write cue times "
                                 "as VO.lines.hook.start + 0.2 instead of numbers: after a re-voice (a changed line, a "
                                 "translation) run `voice cues` again and every cue follows. Also works for DOM pages.",
                     epilog="Examples:\n  showtime voice cues project/voice/timeline.json -o project/voice/cues.js\n"
                            "  showtime voice cues voice/ -o voice/cues.js --offset 0.6 --var NARR")
    p.add_argument("timeline", help="timeline.json from `voice script` (or its folder)")
    p.add_argument("-o", "--output", help="output .js (default: cues.js next to the timeline)")
    p.add_argument("--offset", type=float, default=0.0, help="seconds added to every time (the voice's start in the video)")
    p.add_argument("--var", default="VO", help="variable name (default VO)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_cues)


# ------------------------------------------------------------------------
# Handlers
# ------------------------------------------------------------------------

def cmd_cues(args: argparse.Namespace) -> int:
    import json as _json
    import re as _re
    from .common import read_json
    tp = Path(args.timeline).expanduser()
    if tp.is_dir():
        tp = tp / "timeline.json"
    if not tp.is_file():
        raise ShowtimeError("timeline not found: %s" % tp, hint="write it with `showtime voice script <script> -o voice/`")
    if not _re.fullmatch(r"[A-Za-z_$][\w$]*", args.var):
        raise ShowtimeError("--var must be a JavaScript identifier (got %r)" % args.var)
    tl = read_json(tp)
    off = float(args.offset or 0.0)
    r = lambda x: round(float(x) + off, 3)  # noqa: E731
    lines, words = {}, {}
    for ln in tl.get("lines") or []:
        lid = str(ln.get("id"))
        slot = ln.get("slot") or {}
        lines[lid] = {"start": r(ln.get("start", 0)), "end": r(ln.get("end", 0)),
                      "speech_start": r(ln.get("speech_start", ln.get("start", 0))),
                      "speech_end": r(ln.get("speech_end", ln.get("end", 0))),
                      "slot_end": r(slot.get("end", ln.get("end", 0)))}
        words[lid] = [[w.get("text"), r(w.get("start", 0)), r(w.get("end", 0))] for w in ln.get("words") or []]
    doc = {"duration": round(float(tl.get("duration", 0)), 3),
           "offset": off, "lines": lines, "words": words}
    out = Path(args.output) if args.output else tp.with_name("cues.js")
    out.parent.mkdir(parents=True, exist_ok=True)
    body = ("// written by `showtime voice cues` from %s: run it again after every `voice script`\n"
            "var %s = %s;\nif (typeof window !== 'undefined') window.%s = %s;\n" % (
                tp.name, args.var, _json.dumps(doc, ensure_ascii=False, separators=(",", ":")), args.var, args.var))
    out.write_text(body, encoding="utf-8")
    if args.json:
        print_json({"output": str(out), "lines": len(lines), "words": sum(len(v) for v in words.values()), "var": args.var})
    else:
        _say("%d line(s), %d word(s) -> %s (var %s)" % (len(lines), sum(len(v) for v in words.values()), out, args.var))
        print(out)
    return 0


_LIST_COLS = ("id", "lang", "gender", "grade")


def cmd_list(args: argparse.Namespace) -> int:
    from .voice import models, voices
    rows: List[Dict[str, Any]] = []
    st = models.status()
    if args.engine in (None, "kokoro"):
        for vi in voices.kokoro_catalog():
            if not args.all and vi.grade[:1] in ("D", "F") and not args.lang and not args.json:
                continue
            vi.installed = bool(st["kokoro_model"])
            rows.append(vi.as_dict())
    if args.engine in (None, "supertonic"):
        for name in voices.SUPERTONIC_VOICES:
            rows.append(voices.VoiceInfo(id="supertonic:" + name, engine="supertonic", lang="multi",
                                         gender=name[0].lower(), notes="31 languages (use --lang)",
                                         license="OpenRAIL-M (weights)", installed=bool(st["supertonic"]),
                                         langs=voices.SUPERTONIC_LANGS).as_dict())
    if args.engine in (None, "piper"):
        for name, meta in sorted(voices.PIPER_VOICES.items()):
            rows.append(voices.VoiceInfo(id="piper:" + name, engine="piper", lang=str(meta["lang"]),
                                         gender=str(meta["gender"]), notes="fast fallback, robotic",
                                         license=str(meta["license"]), installed=name in st["piper"],
                                         attribution=str(meta.get("attribution", ""))).as_dict())
    if args.lang:
        want = args.lang.lower()
        rows = [r for r in rows if r["lang"] == "multi" and want.split("-")[0] in r.get("langs", [])
                or r["lang"] == want or r["lang"].split("-")[0] == want]
    if args.json:
        print_json({"voices": rows, "defaults": voices.DEFAULTS, "status": st})
        return 0
    if not rows:
        raise ShowtimeError("no voices match", hint="try `showtime voice list --all`")
    print("%-28s %-6s %-3s %-5s %-4s %s" % ("VOICE", "LANG", "SEX", "GRADE", "READY", "NOTES"))
    for r in rows:
        notes = r["notes"] + ("" if r["engine"] == "kokoro" else "  [%s]" % r["license"])
        print("%-28s %-6s %-3s %-5s %-4s  %s" % (*(r[c] for c in _LIST_COLS), "yes" if r["installed"] else "no", notes))
    sys.stdout.flush()
    print("\nDefaults: en af_heart (female) / am_michael (male), en-gb bf_emma, es ef_dora, fr ff_siwis."
          "\nNot installed = downloads on first use (Piper) or `showtime setup --with supertonic`.", file=sys.stderr)
    return 0


def _speech_summary(sp, out: Optional[Path], report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from .voice import tts
    rate = tts.measure_rate(sp)
    d = {"output": str(out) if out else None, "words_file": str(tts.words_path(out)) if out else None,
         "duration": round(sp.duration, 3), "voice": sp.voice, "engine": sp.engine, "lang": sp.lang,
         "speed": sp.speed, "timing": sp.timing, "words": len(sp.words), "wps": rate["wps"], "wpm": rate["wpm"],
         "cached": sp.cached, "synth_seconds": round(sp.synth_seconds, 2), "rtf": round(sp.rtf, 3)}
    if report:
        d["loudness"] = report.get("after")
    return d


def cmd_say(args: argparse.Namespace) -> int:
    import os
    from .voice import lexicon as lexmod
    from .voice import master as mastermod
    from .voice import tts
    text = _read_text(args)
    if args.no_cache:
        os.environ["SHOWTIME_NO_CACHE"] = "1"
    lex = lexmod.load(args.lexicon, project_dir=Path.cwd())
    kw = dict(voice=args.voice, lang=args.lang, engine=None if args.engine == "auto" else args.engine,
              lexicon=lex, style=args.style)
    t0 = time.time()
    if args.fit:
        sp = tts.fit_to(text, args.fit, speed=args.speed, **kw)
    else:
        sp = tts.synthesize(text, speed=args.speed, **kw)
    default_name = "voice-%s.wav" % slugify(text, 32, "line")
    if not args.output:
        out = _unique(Path.cwd() / default_name)
    elif Path(args.output).is_dir() or args.output.endswith(("/", "\\")):
        Path(args.output).mkdir(parents=True, exist_ok=True)
        out = _unique(Path(args.output) / default_name)
    else:
        out = Path(args.output)
        if out.suffix.lower() != ".wav":
            out = out.with_suffix(".wav")
        out.parent.mkdir(parents=True, exist_ok=True)
    report = None
    if args.raw:
        sp.save(out)
    else:
        y, rate, report = mastermod.master_array(sp.audio, sp.sample_rate, lufs=args.lufs)
        from .voice import audio_io as aio
        from .common import write_json
        aio.write(out, y, rate, bits=24)
        from .common import portable_path
        write_json(tts.words_path(out), sp.transcript(portable_path(out, out.parent)))
    d = _speech_summary(sp, out, report)
    d["wall_seconds"] = round(time.time() - t0, 2)
    if args.json:
        d["word_timings"] = sp.words
        print_json(d)
    else:
        _say("%s  %.2fs  %d words (%.2f words/s)  voice %s  timing %s%s" % (
            out, sp.duration, d["words"], d["wps"], sp.voice, sp.timing, "  [cached]" if sp.cached else
            "  RTF %.2f" % sp.rtf))
        print(out)
        print(tts.words_path(out))
    return 0


def cmd_script(args: argparse.Namespace) -> int:
    from .voice import script
    ov = {"voice": args.voice, "speed": args.speed, "style": args.style, "lang": args.lang, "gap": args.gap,
          "lead_in": args.lead_in, "tail": args.tail, "lufs": args.lufs}
    if args.no_master:
        ov["master"] = False
    tl = script.build(args.script, args.output, ov, tuple(args.lexicon), fit=args.fit)
    out = Path(args.output) if args.output else Path(args.script).parent / "voice"
    if args.json:
        if tl.get("fit"):
            _say(script.fit_message(tl["fit"]))
        print_json(tl)
        return 0
    _say("\n%-4s %-16s %-11s %7s %7s %7s  %s" % ("#", "LINE", "VOICE", "START", "END", "SLOT", "TEXT"))
    for ln in tl["lines"]:
        txt = ln["text"] if len(ln["text"]) <= 48 else ln["text"][:45] + "..."
        _say("%-4d %-16s %-11s %7.2f %7.2f %7.2f  %s" % (ln["index"], ln["id"][:16], ln["voice"][:11], ln["start"],
                                                        ln["end"], ln["slot"]["duration"], txt))
    _say("total %.2fs, %d lines, %d words, loudness %s LUFS, built in %.1fs" % (
        tl["duration"], len(tl["lines"]), len(tl["words"]),
        "%.1f" % tl["loudness"] if tl["loudness"] is not None else "raw", tl["build_seconds"]))
    if tl.get("fit"):
        _say(script.fit_message(tl["fit"]))
    for name in ("vo.wav", "timeline.json", "vo.words.json", "vo.srt", "lines/"):
        print(out / name)
    return 0


def cmd_align(args: argparse.Namespace) -> int:
    from .common import write_json
    from .voice import align
    text = _read_text(args, "script text")
    src = Path(args.audio)
    t0 = time.time()
    words, used, dur = align.align(src, text, lang=args.lang, method=args.method, voice=args.voice,
                                   snap_edges=not args.no_snap)
    out = Path(args.output) if args.output else _unique(src.with_name(src.stem + ".words.json"))
    from .common import portable_path
    data = {"source": portable_path(src, out.parent), "duration": round(dur, 3), "language": args.lang.split("-")[0],
            "model": "align-" + used, "method": used,
            "words": [dict(w, type="word") for w in words]}
    write_json(out, data)
    if args.json:
        print_json(data)
    else:
        _say("%d words aligned with %s in %.1fs (%.2fs of audio)" % (len(words), used, time.time() - t0, dur))
        print(out)
    return 0


def cmd_master(args: argparse.Namespace) -> int:
    from .voice import master
    src = Path(args.input)
    out = Path(args.output) if args.output else _unique(src.with_name(src.stem + ".master.wav"))
    rep = master.master(src, out, lufs=args.lufs, tp=args.tp, preset=args.preset, stereo=args.stereo)
    if args.json:
        print_json(rep)
    else:
        b, a = rep["before"], rep["after"]
        _say("%s: %.1f LUFS / %.1f dBTP  ->  %.1f LUFS / %.1f dBTP (LRA %.1f)" % (
            src.name, b["lufs"], b["tp"], a["lufs"], a["tp"], a["lra"]))
        print(out)
    return 0


def _ipa_project_dir(project: Optional[str]) -> Path:
    """Where `voice ipa` looks for lexicon.json / brand.json: --project (a folder or a script file), else the
    current folder, else the one sub-folder of it that holds a lexicon.json (<job>/project, <job>/voice...)."""
    if project:
        p = Path(project).expanduser()
        return p if p.is_dir() else p.parent
    cwd = Path.cwd()
    if (cwd / "lexicon.json").is_file() or (cwd / "brand.json").is_file():
        return cwd
    try:
        subs = [d for d in cwd.iterdir() if d.is_dir() and (d / "lexicon.json").is_file()]
    except OSError:
        subs = []
    return subs[0] if len(subs) == 1 else cwd


def cmd_ipa(args: argparse.Namespace) -> int:
    from .voice import espeak, voices
    from .voice import lexicon as lexmod
    from .voice.textnorm import normalize_tokens, split_pauses, tokenize
    lang = args.lang or (voices.resolve(args.voice).lang if args.voice else "en-us")
    pdir = _ipa_project_dir(args.project)
    lex = lexmod.load(args.lexicon, project_dir=pdir)
    # keeps inline [word](/ipa/) and [word](respelling) overrides; drops [pause] marks and comments
    toks = tokenize(" ".join(seg.text for seg in split_pauses(args.text)))
    normalize_tokens(toks, lang)
    rows = []
    for t in toks:                      # a lexicon respelling is what every engine reads
        if not t.say and not t.ipa:
            say = lex.say(t.core, lang)
            if say:
                t.spoken = say
    phon = espeak.phonemize([t.spoken or t.core for t in toks], lang)
    pieces: List[str] = []
    run: List[str] = []
    for t, ph in zip(toks, phon):
        ipa = t.ipa or (lex.ipa(t.core, lang) if not t.say else None)
        rows.append({"word": t.core, "spoken": t.spoken, "espeak": ph, "lexicon": ipa})
        if ipa:                         # as Kokoro reads it: the override spliced in between espeak runs
            if run:
                pieces.append(espeak.phonemize(" ".join(run), lang))
                run = []
            pieces.append(ipa)
        else:
            run.append(t.lead + (t.spoken or t.core) + t.trail)
    if run:
        pieces.append(espeak.phonemize(" ".join(run), lang))
    whole = " ".join(p for p in pieces if p)
    used = [src for src in lex.sources if Path(src).resolve() != lexmod.BUILTIN.resolve()]
    if args.json:
        print_json({"lang": lang, "words": rows, "phrase": whole, "lexicons": used})
        return 0
    for r in rows:
        extra = ("  (reads as %r)" % r["spoken"]) if r["spoken"] and r["spoken"] != r["word"] else ""
        fix = ("   lexicon -> %s" % r["lexicon"]) if r["lexicon"] else ""
        print("%-18s %-28s%s%s" % (r["word"], r["espeak"], fix, extra))
    print("\nphrase: %s%s" % (whole, "   (with the lexicon)" if any(r["lexicon"] for r in rows) else ""))
    print("lexicon: %s" % (", ".join(used) if used else "built-in only (no lexicon.json in %s; `voice ipa --project DIR` "
                           "reads DIR's, --lexicon FILE adds one; `voice script` reads the lexicon.json next to its "
                           "script or one folder up)" % pdir), file=sys.stderr)
    print("lexicon entry format: {\"%s\": \"%s\"}" % (rows[0]["word"], rows[0]["lexicon"] or rows[0]["espeak"]),
          file=sys.stderr)
    return 0


BENCH_TEXT = {
    "en": ("Meet Showtime, the video studio that lives in your terminal. Point it at any project and get a "
           "polished launch film in minutes, rendered entirely on your own machine. It writes the script, records "
           "the voice, and cuts every scene to the beat."),
    "es": ("Te presentamos Showtime, el estudio de video que vive en tu terminal. Apúntalo a cualquier proyecto y "
           "obtén un video de lanzamiento impecable en minutos, generado por completo en tu propia máquina."),
}


def cmd_bench(args: argparse.Namespace) -> int:
    import os
    from .voice import tts, voices
    os.environ["SHOWTIME_NO_CACHE"] = "1"
    rows = []
    for item in [x.strip() for x in args.voices.split(",") if x.strip()]:
        v, _, lang = item.partition("@")
        spec = voices.resolve(v, lang or None)
        text = BENCH_TEXT.get(spec.lang.split("-")[0], BENCH_TEXT["en"])
        tts.synthesize("Warm up.", voice=v, lang=lang or None, use_cache=False)
        sp = tts.synthesize(text, voice=v, lang=lang or None, use_cache=False)
        rate = tts.measure_rate(sp)
        rows.append({"voice": sp.voice, "engine": sp.engine, "lang": sp.lang, "audio_seconds": round(sp.duration, 2),
                     "synth_seconds": round(sp.synth_seconds, 2), "rtf": round(sp.rtf, 3),
                     "engine_rtf": round(sp.meta.get("engine_seconds", sp.synth_seconds) / max(sp.duration, 1e-6), 3),
                     "words": rate["words"],
                     "wps": rate["wps"], "wpm": rate["wpm"], "timing": sp.timing})
        if not args.json:
            _say("%-24s %-6s RTF %.2f (engine %.2f)  %.1fs for %.1fs  %.2f words/s  %.0f wpm  timing %s" % (
                sp.voice, sp.lang, sp.rtf, rows[-1]["engine_rtf"], sp.synth_seconds, sp.duration, rate["wps"],
                rate["wpm"], sp.timing))
    if args.json:
        import platform
        print_json({"machine": platform.platform(), "cpu_count": os.cpu_count(), "results": rows})
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    from .common import human_size
    from .voice import tts
    res: Dict[str, Any] = {}
    if args.clear or args.prune:
        limit = int(args.max_mb * 1024 * 1024) if args.max_mb is not None else None
        res = tts.prune_cache(limit=limit, clear=bool(args.clear))
    st = tts.cache_stats()
    st.update(res)
    if args.json:
        print(json.dumps(st, indent=2))
        return 0
    if res:
        _say("removed %d cached line(s), freed %s" % (res["removed"], human_size(res["freed_bytes"])))
    print("%s  %d line(s), %s of %s" % (st["dir"], st["entries"], human_size(st["bytes"]),
                                        human_size(st["limit_bytes"]) if st["limit_bytes"] else "no cap"))
    return 0

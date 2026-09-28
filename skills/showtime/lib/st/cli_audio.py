"""`showtime audio ...`: music, sound effects, library, analysis, mixing, mastering.

Heavy imports (numpy/scipy) happen inside the handlers, so `showtime --help`
stays fast and a missing dependency only affects these commands.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import ShowtimeError, print_json, warn

COMMANDS = {
    "audio": "Music (compose/library), sound effects, beats, mixing, loudness and mastering",
}

_F = argparse.RawDescriptionHelpFormatter


def _unique(path: Path) -> Path:
    """Default output names never overwrite an earlier result."""
    if not path.exists():
        return path
    k = 2
    while True:
        c = path.with_name("%s-%d%s" % (path.stem, k, path.suffix))
        if not c.exists():
            return c
        k += 1


def register(sub: argparse._SubParsersAction) -> None:
    a = sub.add_parser("audio", help=COMMANDS["audio"], formatter_class=_F, description=(
        "Local audio toolkit.\n\n"
        "  compose    procedural music in 18 styles, exact length, stems + MIDI + beats.json\n"
        "  styles     list music styles (bpm, key, moods, what they suit)\n"
        "  sfx        render a procedural sound effect (prints its hit time)\n"
        "  sfx-types  list the 56 procedural effect types\n"
        "  lib        audio library: fetch, search, info, index, credits, stats, sources, generate\n"
        "  beats      beat grid, downbeats, onsets, energy, sections, key -> beats.json\n"
        "  fit        loop or trim music to an exact length on bar lines\n"
        "  mix        render an audio/mix.json (ducking, hit alignment, loudness) + report\n"
        "  meter      loudness (LUFS), true peak, LRA, RMS, clipping\n"
        "  master     normalise a file to a loudness target (default -14 LUFS / -1 dBTP)\n"
        "  musicgen   optional MusicGen draft music (non-commercial weights)"),
        epilog="Examples:\n"
               "  showtime audio compose --style upbeat-tech --dur 30 --sections 0:intro,8:build,16:drop,26:outro -o bed.wav\n"
               "  showtime audio sfx whoosh --dur 1.2 -o whoosh.wav\n"
               "  showtime audio lib search whoosh --kind sfx --limit 5\n"
               "  showtime audio mix audio/mix.json -o audio/mix.wav\n")
    s = a.add_subparsers(dest="audio_cmd", metavar="<subcommand>")

    p = s.add_parser("compose", help="compose music in a style to an exact length", formatter_class=_F,
                     description="Compose and render music. Section markers land exactly on downbeats (the tempo is "
                                 "nudged slightly per section), the piece ends on a final hit, and the file is exactly "
                                 "--dur seconds long. Writes OUT.wav, OUT.mid, OUT.beats.json and OUT.stems/.",
                     epilog="Examples:\n"
                            "  showtime audio compose --style underscore --dur 45 -o bed.wav      # calm bed for explainers, data, reports\n"
                            "  showtime audio compose --style upbeat-tech --dur 20 -o launch.wav  # a driving launch bed\n"
                            "  showtime audio compose --style epic-trailer --bpm 84 --key Cm --dur 30 \\\n"
                            "      --sections 0:intro,10:build,18:drop,27:outro -o trailer.wav\n"
                            "  showtime audio compose --style synthwave --dur 20 --backend synth --seed 3 -o sw.wav\n"
                            "Section names: intro, verse, build, drop, chorus, break, bridge, outro.")
    p.add_argument("--style", "-s", default="underscore", help="style name (see `audio styles`; default underscore, a calm "
                   "documentary bed)")
    p.add_argument("--dur", "--duration", "-d", type=float, default=30.0, dest="dur", help="length in seconds (default 30)")
    p.add_argument("--bpm", type=float, help="tempo (default: the style's)")
    p.add_argument("--key", "-k", help="key, e.g. C, Am, F#, Ebm (default: the style's)")
    p.add_argument("--sections", help="markers 'time:name,...' e.g. 0:intro,8:build,16:drop (default: automatic)")
    p.add_argument("--seed", type=int, default=0, help="variation seed (default 0)")
    p.add_argument("--backend", default="auto", choices=["auto", "sf", "synth", "hybrid"],
                   help="renderer: SoundFont, numpy synth, or hybrid (default: the style's)")
    p.add_argument("--soundfont", help="SoundFont name or path (default GeneralUser GS)")
    p.add_argument("--lufs", type=float, default=-14.0, help="master loudness (default -14)")
    p.add_argument("--tp", type=float, default=-1.0, help="true-peak ceiling dBTP (default -1)")
    p.add_argument("--no-stems", action="store_true", help="skip OUT.stems/")
    p.add_argument("--no-sfx", action="store_true", help="no risers/impacts at section changes")
    p.add_argument("-o", "--output", help="output .wav (default ./<style>-<dur>s.wav)")
    p.add_argument("--json", action="store_true", help="print the full JSON summary")
    p.set_defaults(func=cmd_compose)

    p = s.add_parser("styles", help="list music styles", formatter_class=_F,
                     description="List the composer's styles: bpm range, key, moods and what each suits.",
                     epilog="Examples:\n  showtime audio styles\n  showtime audio styles --json\n"
                            "  showtime audio compose --style lofi-chill --dur 30 -o bed.wav   # then use one")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_styles)

    p = s.add_parser("sfx", help="render a procedural sound effect", formatter_class=_F,
                     description="Render one procedural effect (loudness-matched to its category) and print its "
                                 "hit time: the moment to align with a video frame.",
                     epilog="Examples:\n"
                            "  showtime audio sfx whoosh -o whoosh.wav\n"
                            "  showtime audio sfx riser --dur 4 --key Am -o riser.wav      # hit = 4.0 (the landing)\n"
                            "  showtime audio sfx impact --intensity 0.9 --seed 3 -o hit.wav\n"
                            "  showtime audio sfx click --variants 4 -o clicks/click.wav   # click-1.wav ... click-4.wav")
    p.add_argument("type", help="effect type (see `audio sfx-types`)")
    p.add_argument("--dur", "-d", type=float, help="duration in seconds (default: the type's)")
    p.add_argument("--key", "-k", default="C", help="musical key for tonal effects (default C)")
    p.add_argument("--intensity", "-i", type=float, default=0.7, help="0..1 (default 0.7)")
    p.add_argument("--seed", type=int, default=0, help="variation seed (default 0)")
    p.add_argument("--variants", type=int, default=1, help="render N seeds (seed, seed+1, ...)")
    p.add_argument("--raw", action="store_true", help="skip category loudness matching")
    p.add_argument("-o", "--output", help="output .wav/.flac (default ./<type>.wav)")
    p.set_defaults(func=cmd_sfx)

    p = s.add_parser("sfx-types", help="list procedural sound effect types", formatter_class=_F,
                     description="List the procedural effect types `audio sfx` renders, by category.",
                     epilog="Examples:\n  showtime audio sfx-types\n  showtime audio sfx-types --category transition\n"
                            "  showtime audio sfx-types --json")
    p.add_argument("--category", help="only this category (transition, impact, ui, foley, fx, ambience, musical)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_sfx_types)

    _register_lib(s)

    p = s.add_parser("beats", help="analyse music: beats, downbeats, onsets, energy, sections, key", formatter_class=_F,
                     description="Analyse a music file and write beats.json. `rhythmic`/`pacing` say whether hard "
                                 "cuts may sit on beats (beat_cut) or should follow phrases and energy (phrase_flow).",
                     epilog="Examples:\n  showtime audio beats song.mp3            # writes song.beats.json\n"
                            "  showtime audio beats song.mp3 --json -o -")
    p.add_argument("file")
    p.add_argument("-o", "--output", help="beats.json path ('-' = stdout only; default <file>.beats.json)")
    p.add_argument("--engine", default="native", choices=["native", "librosa"], help="default native (fast)")
    p.add_argument("--bpm", type=float, help="known tempo hint")
    p.add_argument("--json", action="store_true", help="print the JSON instead of a summary")
    p.set_defaults(func=cmd_beats)

    p = s.add_parser("fit", help="loop or trim music to an exact length (bar-aligned)", formatter_class=_F,
                     description="Fit music to a duration: loops a bar-aligned region or ends on a downbeat with a "
                                 "short decay (it says which bar, and when that is mid-phrase). --ending song keeps "
                                 "the track's own ending: its last bars are spliced in at a downbeat. Uses "
                                 "<file>.beats.json when present, else analyses the file.",
                     epilog="Examples:\n  showtime audio fit track.mp3 --dur 42.5 -o bed.wav\n"
                            "  showtime audio fit track.opus --dur 45 --ending song -o bed.wav   (ends on the song's cadence)")
    p.add_argument("file")
    p.add_argument("--dur", "-d", type=float, required=True, help="target seconds")
    p.add_argument("--beats", help="beats.json to use")
    p.add_argument("--fade-out", type=float, help="fade length when trimming")
    p.add_argument("--from", dest="start", type=float, metavar="S",
                   help="start at S seconds into the track (snapped to the nearest downbeat), e.g. the chorus")
    p.add_argument("--ending", choices=("auto", "song", "fade"), default="auto",
                   help="when trimming: auto (a downbeat and a short decay), song (splice in the track's own last "
                        "bars so it ends as written), fade (a plain fade)")
    p.add_argument("-o", "--output", help="output (default <file>.fit.wav)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_fit)

    p = s.add_parser("mix", help="render an audio mix.json to one mastered file", formatter_class=_F,
                     description="Render a mix spec (music/voice/sfx/ambience tracks, hit alignment, loops, fades, "
                                 "ducking and spectral carving under the voice, two-stage loudness to -14 LUFS / "
                                 "-1 dBTP). Also writes mix.report.json (levels per section, credits) and credits.txt "
                                 "when CC-BY items are used (a copied library file is matched by content, a file with "
                                 "a <file>.license.json uses it). Masking warnings skip designed layers (one family, "
                                 "\"layer\": \"<id>\", \"texture\": true). Key clicks for a page typewriter: a track "
                                 "{\"typewriter\": {\"text\": ..., \"cps\": 18}, \"start\": t}. See references/audio.md "
                                 "for the format.",
                     epilog="Examples:\n  showtime audio mix audio/mix.json -o audio/mix.wav\n"
                            "  showtime audio mix audio/mix.json -o preview.m4a --check")
    p.add_argument("spec", help="mix.json")
    p.add_argument("-o", "--output", help="output audio (default <spec dir>/mix.wav)")
    p.add_argument("--report", help="report path (default mix.report.json beside the output)")
    p.add_argument("--root", help="base folder for relative paths (default: spec folder, project root, cwd)")
    p.add_argument("--check", action="store_true", help="also measure with ffmpeg ebur128")
    p.add_argument("--json", action="store_true", help="print the full report")
    p.set_defaults(func=cmd_mix)

    p = s.add_parser("meter", help="measure loudness, true peak, LRA, RMS, clipping", formatter_class=_F,
                     description="EBU R128 / BS.1770-4 metering of any audio or video file.",
                     epilog="Examples:\n  showtime audio meter final.mp4\n  showtime audio meter mix.wav --windows 1 --json")
    p.add_argument("files", nargs="+")
    p.add_argument("--windows", type=float, help="also list RMS per N-second window")
    p.add_argument("--ffmpeg", action="store_true", help="cross-check with ffmpeg ebur128")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_meter)

    p = s.add_parser("master", help="normalise loudness with a true-peak limiter", formatter_class=_F,
                     description="Master to an exact loudness target. Engine 'st' iterates gain + look-ahead "
                                 "true-peak limiting until within 0.05 LU; 'loudnorm' uses ffmpeg two-pass loudnorm.",
                     epilog="Examples:\n  showtime audio master mix.wav -o mix.master.wav\n"
                            "  showtime audio master vo.wav -o vo.m.wav --target podcast --preset voice")
    p.add_argument("input")
    p.add_argument("-o", "--output", help="output (default <input>.master.wav)")
    p.add_argument("--lufs", type=float, help="integrated loudness target (default -14)")
    p.add_argument("--tp", type=float, help="true-peak ceiling dBTP (default -1)")
    p.add_argument("--target", help="named target: web, youtube, social, podcast, broadcast, music-bed ...")
    p.add_argument("--preset", default="mix", choices=["mix", "music", "voice", "none"], help="tone chain (default mix)")
    p.add_argument("--engine", default="st", choices=["st", "loudnorm"])
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_master)

    p = s.add_parser("musicgen", help="optional MusicGen draft music (NON-COMMERCIAL weights)", formatter_class=_F,
                     description="Generate draft music with MusicGen-small on CPU (slow). Requires "
                                 "`showtime setup --with musicgen`. The weights are CC-BY-NC-4.0: never use the "
                                 "output in commercial videos.",
                     epilog='Example:\n  showtime audio musicgen "warm corporate background, soft piano, no vocals" --dur 20 -o draft.wav')
    p.add_argument("prompt")
    p.add_argument("--dur", "-d", type=float, default=20.0, help="final length (generation capped at 30 s, then looped)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--lufs", type=float, default=-16.0)
    p.add_argument("-o", "--output", help="output (default ./musicgen.wav)")
    p.set_defaults(func=cmd_musicgen)

    a.set_defaults(func=lambda args: _group_help(a))


def _register_lib(s) -> None:
    lib = s.add_parser("lib", help="audio library: fetch, search, info, index, credits, stats", formatter_class=_F,
                       description="The local audio library in ~/.showtime/library (CC0 / CC-BY / generated).",
                       epilog="Examples:\n  showtime audio lib fetch                    # core tier, ~249 MB, ~10-15 min\n"
                              "  showtime audio lib search --kind music --mood uplifting --bpm 100-130 --min-dur 60\n"
                              "  showtime audio lib search riser --kind sfx\n"
                              "  showtime audio lib info incompetech-voxel-revolution")
    ls = lib.add_subparsers(dest="lib_cmd", metavar="<subcommand>")

    p = ls.add_parser("fetch", help="download + analyse library tiers", formatter_class=_F,
                      description="Download the manifest's sources (core: pinned sha256; extended: sha256 recorded on "
                                  "first download and verified after), transcode music to Opus, analyse every "
                                  "file, render the generated tier, and write catalog.json + CREDITS-SOURCES.md. "
                                  "Re-running skips what is installed.",
                      epilog="Tiers: core (~249 MB), extended (core + ~1 GB more music).")
    p.add_argument("--tier", default="core", choices=["core", "extended"])
    p.add_argument("--only", help="comma list of source ids (globs ok)")
    p.add_argument("--no-generated", action="store_true", help="skip rendering procedural SFX + composed beds")
    p.add_argument("--force", action="store_true", help="re-install even if present")
    p.add_argument("--keep-downloads", action="store_true", help="keep the downloaded archives")
    p.add_argument("--workers", type=int, default=3, help="parallel analysis workers (default 3)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_lib_fetch)

    p = ls.add_parser("search", help="search the catalog", formatter_class=_F,
                      description="Filter and rank library items. Words match ids, titles, tags and moods.",
                      epilog="Examples:\n  showtime audio lib search whoosh --kind sfx --distinct\n"
                             "  showtime audio lib search --kind music --mood calm --dur 45 --license cc0\n"
                             "  showtime audio lib search --kind music --bpm 118-126 --key Am")
    p.add_argument("words", nargs="*", help="free-text words")
    p.add_argument("--kind", help="music, sfx, stinger, ambience, voice (comma list); ambience also lists sfx loops "
                                  "that work as a bed, ranked lower")
    p.add_argument("--mood", help="e.g. uplifting, calm, dark, epic (comma list)")
    p.add_argument("--tags", help="comma list")
    p.add_argument("--bpm", help="range, e.g. 100-130 (half/double time also match)")
    p.add_argument("--key", help="compatible key, e.g. Am")
    p.add_argument("--min-dur", type=float)
    p.add_argument("--max-dur", type=float)
    p.add_argument("--dur", type=float, help="desired length (ranks items that fit)")
    p.add_argument("--energy", help="0..1 or range, e.g. 0.6-1")
    p.add_argument("--license", help="cc0, cc-by, CC-BY-4.0 ... (comma list)")
    p.add_argument("--source", help="source id prefix, e.g. kenney, incompetech, generated")
    p.add_argument("--category", help="sfx category: ui, transition, impact, foley, fx, musical, ambience")
    p.add_argument("--loopable", action="store_true", default=None)
    p.add_argument("--rhythmic", action="store_true", default=None)
    p.add_argument("--tier", help="core, extended, generated, byo")
    p.add_argument("--distinct", action="store_true", help="one result per variant group")
    p.add_argument("--limit", "-n", type=int, default=15)
    p.add_argument("--paths", action="store_true", help="print absolute file paths")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_lib_search)

    p = ls.add_parser("info", help="show one catalog item (and its credit line)", formatter_class=_F,
                      epilog="Examples:\n  showtime audio lib info generated-sfx/whoosh-01-0.6s\n"
                             "  showtime audio lib info generated-sfx/whoosh-01-0.6s --path")
    p.add_argument("id")
    p.add_argument("--path", action="store_true", help="print only the absolute path")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_lib_info)

    p = ls.add_parser("index", help="catalog your own folder in place (BYO, not copied)", formatter_class=_F,
                      description="Add a local folder (e.g. a sound pack you downloaded) to the catalog without "
                                  "copying it. Mark the license honestly; non-redistributable packs stay local.",
                      epilog='Example:\n  showtime audio lib index ~/Downloads/MyPack --name mypack --license "vendor-royalty-free"')
    p.add_argument("folder")
    p.add_argument("--name", required=True, help="short name (becomes source id byo-<name>)")
    p.add_argument("--license", required=True, help="license identifier, e.g. CC0-1.0, CC-BY-4.0, vendor license name")
    p.add_argument("--kind", default="sfx", choices=["sfx", "music", "ambience", "voice", "stinger"])
    p.add_argument("--attribution", help="credit line if the license requires one")
    p.add_argument("--redistributable", action="store_true", help="files may be shared (default: no)")
    p.set_defaults(func=cmd_lib_index)

    p = ls.add_parser("credits", help="credit lines for library items", formatter_class=_F,
                      description="Print the credit lines the licenses of these items require (CC-BY and similar). "
                                  "`audio mix` writes them to credits.txt next to the mix on its own.",
                      epilog="Examples:\n  showtime audio lib credits generated-sfx/whoosh-01-0.6s\n"
                             "  showtime audio lib credits ID1 ID2 -o credits.txt")
    p.add_argument("ids", nargs="+")
    p.add_argument("-o", "--output", help="also write the lines to this file (e.g. credits.txt)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_lib_credits)

    p = ls.add_parser("stats", help="catalog statistics", formatter_class=_F,
                      epilog="Examples:\n  showtime audio lib stats\n  showtime audio lib stats --json")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_lib_stats)

    p = ls.add_parser("sources", help="list manifest sources (tier, size, license)", formatter_class=_F,
                      epilog="Examples:\n  showtime audio lib sources\n  showtime audio lib sources --tier extended")
    p.add_argument("--tier", choices=["core", "extended"])
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_lib_sources)

    p = ls.add_parser("generate", help="render only the generated tier (procedural SFX + composed beds)",
                      formatter_class=_F, epilog="Examples:\n  showtime audio lib generate\n"
                                                 "  showtime audio lib generate --force   # re-render everything")
    p.add_argument("--force", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_lib_generate)

    p = ls.add_parser("pin", help="(maintainers) fill in missing sha256/bytes in the manifest")
    p.add_argument("--tier", default="core", choices=["core", "extended"])
    p.add_argument("--only", help="comma list of source ids")
    p.add_argument("--manifest", help="manifest path (default: the skill's)")
    p.set_defaults(func=cmd_lib_pin)

    lib.set_defaults(func=lambda args: _group_help(lib))


def _group_help(p: argparse.ArgumentParser) -> int:
    p.print_help()
    return 2


# ------------------------------------------------------------------------------------------ handlers
def cmd_compose(args) -> int:
    from .audio import compose
    style = compose.resolve_style(args.style)
    out = Path(args.output) if args.output else _unique(Path("%s-%gs.wav" % (style, args.dur)))
    if out.suffix.lower() != ".wav":
        raise ShowtimeError("compose writes WAV (got %s); convert afterwards with `audio master`" % out.suffix)
    r = compose.build(style, args.dur, out, bpm=args.bpm, key=args.key, sections=args.sections, seed=args.seed,
                      backend=args.backend, soundfont=args.soundfont, lufs=args.lufs, tp=args.tp,
                      stems=not args.no_stems, with_sfx=not args.no_sfx)
    if args.json:
        print_json(r)
    else:
        secs = ", ".join("%s@%.2f (%.1f bpm)" % (s["name"], s["start"], s["bpm"]) for s in r["sections"])
        print("%s  %s in %s, %.1f bpm, %s, %.2fs, final hit at %.2fs" % (
            r["outputs"]["audio"], r["style"], r["key"], r["bpm"], r["backend"], r["duration"], r["end_hit"]))
        print("  sections: " + secs)
        print("  master: %.2f LUFS, %.2f dBTP   (%.1fs)" % (r["master"]["output_lufs"], r["master"]["output_tp"], r["seconds"]))
        for k in ("beats", "license", "midi", "stems"):
            if r["outputs"].get(k):
                print("  %-6s %s" % (k, r["outputs"][k]))
    for n in r.get("plan_notes") or []:
        warn(n)
    return 0


def cmd_styles(args) -> int:
    from .audio import compose
    rows = compose.style_list()
    if args.json:
        print_json(rows)
        return 0
    for r in rows:
        print("%-18s %3d bpm  %-3s  %-7s %s" % (r["style"], r["bpm"], r["key"], r["backend"], r["description"]))
        print("%-18s use for: %s   moods: %s" % ("", r["use_for"], ", ".join(r["moods"])))
    return 0


def cmd_sfx(args) -> int:
    from .audio import sfx, wav
    from .common import write_json
    t = sfx.resolve_type(args.type)
    base = Path(args.output) if args.output else _unique(Path("%s.wav" % t))
    outs = []
    for i in range(max(1, args.variants)):
        x, m = sfx.render(t, dur=args.dur, intensity=args.intensity, seed=args.seed + i, key=args.key, level=not args.raw)
        p = base if args.variants <= 1 else base.with_name("%s-%d%s" % (base.stem, i + 1, base.suffix))
        wav.save(p, x, bits=24)
        m["file"] = str(p)
        write_json(p.with_name(p.stem + ".sfx.json"), m)   # `audio mix` reads the hit from here
        outs.append(m)
    print_json(outs[0] if len(outs) == 1 else outs)
    return 0


def cmd_sfx_types(args) -> int:
    from .audio import sfx
    rows = sfx.list_types()
    if args.category:
        rows = [r for r in rows if r["category"] == args.category]
    if args.json:
        print_json(rows)
        return 0
    cur = None
    for r in rows:
        if r["category"] != cur:
            cur = r["category"]
            print("\n[%s]  level %.0f LUFS" % (cur, sfx.CATEGORY_LEVEL[cur]))
        print("  %-15s hit=%-5s %5.2fs %s%s" % (r["type"], r["kind"], r["default_dur"], r["description"],
                                                "  (tonal: --key)" if r["tonal"] else ""))
    print("\n%d types. Render: showtime audio sfx <type> [--dur --key --intensity --seed] -o file.wav" % len(rows))
    return 0


def cmd_beats(args) -> int:
    from .audio import beats
    from .common import write_json
    d = beats.analyze(args.file, engine=args.engine, known_bpm=args.bpm)
    if args.output != "-":
        out = Path(args.output) if args.output else Path(args.file).with_name(Path(args.file).stem + ".beats.json")
        from .common import portable_path
        write_json(out, dict(d, file=portable_path(d["file"], out.parent)))   # beats files get published with projects
        d["written"] = str(out)
    if args.json:
        print_json(d)
    else:
        print(beats.summary_text(d))
        if d.get("written"):
            print(d["written"])
    return 0


def cmd_fit(args) -> int:
    from .audio import beats, fit, wav
    from .common import read_json
    src = Path(args.file)
    bdoc = None
    if args.beats:
        bdoc = read_json(args.beats)
    else:
        side = src.with_name(src.stem + ".beats.json")
        bdoc = read_json(side) if side.is_file() else beats.analyze(src)
    x = wav.load(src)
    start = 0.0
    if args.start:
        # start inside the track (the chorus, the loud part), on the nearest downbeat
        start = fit.snap_to_downbeat(bdoc, float(args.start))
        x = x[int(round(start * 48000)):]
        bdoc = fit.shift_beats(bdoc, start)
    y, info = fit.fit(x, args.dur, bdoc, fade_out=args.fade_out, ending=args.ending)
    if start:
        info["from"] = round(start, 3)
    out = Path(args.output) if args.output else _unique(src.with_name(src.stem + ".fit.wav"))
    wav.save(out, y)
    info["output"] = str(out)
    if args.json:
        print_json(info)
    else:
        print("%s  (%s, %.2fs -> %.2fs)" % (out, info.get("mode"), info["source_duration"], info["target"]))
        if info.get("ending") == "song":
            print("  ends with the track's own last %d bar(s) (from %.2fs), spliced in at the downbeat %.2fs%s"
                  % (info["ending_bars"], info["ending_from"], info["splice_at"],
                     "; final hit at %.2fs" % info["end_hit"] if info.get("end_hit") is not None else ""))
        elif info.get("ending") == "downbeat":
            print("  ends on the downbeat at %.2fs after %d bar(s)%s" % (
                info["ends_at"], info.get("bars", 0), ": " + info["phrase_note"] if info.get("phrase_note") else
                " (a whole 4-bar phrase)"))
        elif info.get("ending") == "fade":
            print("  no beat grid: faded out over %.2fs" % info.get("fade_out", 0))
        if info.get("note"):
            warn(info["note"])
    return 0


def cmd_mix(args) -> int:
    from .audio import mix
    spec = Path(args.spec)
    if not spec.is_file():
        raise ShowtimeError("mix spec not found: %s" % spec)
    out = Path(args.output) if args.output else spec.with_name("mix.wav")
    rep = mix.render(spec, out, root=Path(args.root) if args.root else None,
                     report_path=Path(args.report) if args.report else None, ffmpeg_check=args.check)
    if args.json:
        print_json(rep)
        return 0
    print("%s  %.2fs  %s LUFS  %s dBTP  LRA %s" % (rep["output"], rep["duration"], rep["integrated_lufs"],
                                                   rep["true_peak_dbtp"], rep["lra"]))
    if rep.get("voice_to_music_db") is not None:
        print("  voice sits %.1f dB above music/ambience while speaking" % rep["voice_to_music_db"])
    for sct in rep["sections"]:
        print("  %-12s %6.2f-%6.2f  %s LUFS  rms %.1f dBFS" % (sct["name"][:12], sct["start"], sct["end"], sct["lufs"], sct["rms_dbfs"]))
    if rep.get("ffmpeg_ebur128"):
        print("  ffmpeg check: %s" % json.dumps(rep["ffmpeg_ebur128"]))
    if rep.get("credits_file"):
        print("  credits: %s" % rep["credits_file"])
    print("  report: %s" % rep["report_file"])
    return 0


def cmd_meter(args) -> int:
    from .audio import meter
    res = [meter.measure_file(f, windows=args.windows, ffmpeg_check=args.ffmpeg) for f in args.files]
    if args.json:
        print_json(res[0] if len(res) == 1 else res)
        return 0
    for m in res:
        print("%s" % m["file"])
        print("  integrated %s LUFS   LRA %s LU   true peak %s dBTP   sample peak %s dBFS" % (
            m["integrated_lufs"], m["lra"], m["true_peak_dbtp"], m["sample_peak_dbfs"]))
        print("  short-term max %s   momentary max %s   RMS %s dBFS   duration %.2fs" % (
            m["short_term_max_lufs"], m["momentary_max_lufs"], m["rms_dbfs"], m["duration"]))
        if m["clip_runs"] or m["full_scale_samples"]:
            print("  CLIPPING: %d full-scale samples, %d runs" % (m["full_scale_samples"], m["clip_runs"]))
        if m.get("ffmpeg"):
            print("  ffmpeg ebur128: %s" % json.dumps(m["ffmpeg"]))
        if m.get("window_rms_dbfs"):
            print("  RMS per %gs: %s" % (m["window_s"], " ".join("%.1f" % v for v in m["window_rms_dbfs"])))
    return 0


def cmd_master(args) -> int:
    from .audio import master
    lufs, tp = master.target_for(args.target)
    if args.lufs is not None:
        lufs = args.lufs
    if args.tp is not None:
        tp = args.tp
    src = Path(args.input)
    out = Path(args.output) if args.output else _unique(src.with_name(src.stem + ".master.wav"))
    rep = master.master_file(src, out, lufs, tp, args.preset, args.engine)
    if args.json:
        print_json(rep)
    else:
        b, a_ = rep["before"], rep["after"]
        print("%s  %s -> %s LUFS, true peak %s -> %s dBTP (%s)" % (out, b["integrated_lufs"], a_["integrated_lufs"],
                                                                  b["true_peak_dbtp"], a_["true_peak_dbtp"], args.engine))
    return 0


def cmd_musicgen(args) -> int:
    from .audio import musicgen
    out = Path(args.output) if args.output else _unique(Path("musicgen.wav"))
    meta = musicgen.generate(args.prompt, args.dur, out, seed=args.seed, lufs=args.lufs)
    print_json(meta)
    return 0


def cmd_lib_fetch(args) -> int:
    from .audio import library
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    rep = library.fetch(args.tier, only=only, generated=not args.no_generated, force=args.force,
                        keep_downloads=args.keep_downloads, workers=args.workers)
    if args.json:
        print_json(rep)
    else:
        print("installed %d sources, skipped %d, failed %d; catalog has %d items (%s) in %.0fs" % (
            len(rep["installed"]), len(rep["skipped"]), len(rep["failed"]), rep["items"], rep["size"], rep["seconds"]))
        for f in rep["failed"]:
            print("  FAILED %s: %s" % (f["id"], f["error"]))
        print(rep["catalog"])
    return 1 if rep["failed"] and not rep["installed"] and not rep["skipped"] else 0


def cmd_lib_search(args) -> int:
    from .audio import library, search
    res = search.search(query=" ".join(args.words) or None, kind=args.kind, mood=args.mood, tags=args.tags,
                        bpm=args.bpm, key=args.key, min_dur=args.min_dur, max_dur=args.max_dur, duration=args.dur,
                        energy=args.energy, license=args.license, source=args.source, category=args.category,
                        loopable=args.loopable, rhythmic=args.rhythmic, tier=args.tier, distinct=args.distinct,
                        limit=args.limit)
    if args.json:
        print_json([{"id": r["id"], "score": r["score"], "path": str(library.item_path(r["item"])), **r["item"]} for r in res])
        return 0
    if not res:
        print("no matches (loosen the filters, or run `showtime audio lib stats`)", file=sys.stderr)
        return 1
    for r in res:
        print(str(library.item_path(r["item"])) if args.paths else search.row(r))
    return 0


def cmd_lib_info(args) -> int:
    from .audio import library
    it = library.get_item(args.id)
    p = library.item_path(it)
    if args.path:
        print(p)
        return 0
    if args.json:
        print_json({**it, "abs_path": str(p), "exists": p.is_file()})
        return 0
    for k in ("id", "title", "artist", "kind", "category", "duration", "bpm", "key", "rhythmic", "loopable", "lufs",
              "true_peak", "peak_db", "hit", "energy", "mood", "tags", "license", "source_url", "tier"):
        if it.get(k) not in (None, [], ""):
            print("%-12s %s" % (k, ", ".join(it[k]) if isinstance(it[k], list) else it[k]))
    print("%-12s %s%s" % ("path", p, "" if p.is_file() else "  (MISSING)"))
    if it.get("attribution_required"):
        print("CREDIT REQUIRED:\n  " + (it.get("attribution") or "").replace("\n", "\n  "))
    elif it.get("credit_optional"):
        print("credit (optional): %s" % it["credit_optional"])
    return 0


def cmd_lib_index(args) -> int:
    from .audio import library
    rep = library.index_folder(Path(args.folder), args.name, args.license, args.kind, args.attribution, args.redistributable)
    print_json(rep)
    return 0


def cmd_lib_credits(args) -> int:
    from .audio import library
    c = library.credits_for(args.ids)
    if args.output:
        Path(args.output).write_text(c["text"] or "No credits required (CC0 / generated).\n", encoding="utf-8", newline="\n")
    if args.json:
        print_json(c)
    else:
        print(c["text"] or "No credits required (CC0 / generated).")
        if c["optional"]:
            print("Optional courtesy credits: " + "; ".join(c["optional"]))
    return 0


def cmd_lib_stats(args) -> int:
    from .audio import library
    st = library.stats()
    if args.json:
        print_json(st)
        return 0
    print("%d items, %.1f hours, %s  (%s)" % (st["items"], st["hours"], st["size"], st["catalog"]))
    for k in ("kind", "category", "license", "tier"):
        print("  %-9s %s" % (k, ", ".join("%s %d" % (a, b) for a, b in sorted(st[k].items(), key=lambda z: -z[1]))))
    if st["missing_files"]:
        print("  WARNING: %d catalog files are missing (re-run `showtime audio lib fetch --force`)" % st["missing_files"])
    return 0


def cmd_lib_sources(args) -> int:
    from .audio import library
    from .common import human_size
    man = library.load_manifest()
    rows = [s for s in man["sources"] if not args.tier or s.get("tier", "core") == args.tier]
    if args.json:
        print_json([{k: v for k, v in s.items() if not k.startswith("_")} for s in rows])
        return 0
    for s_ in rows:
        print("%-44s %-8s %-9s %9s  %s" % (s_["id"], s_.get("tier", "core"), s_["kind"], human_size(s_.get("bytes")), s_["license"]))
    print("%d sources" % len(rows))
    return 0


def cmd_lib_generate(args) -> int:
    from .audio import library
    rep = library.generate(library.load_manifest().get("generated", {}), force=args.force)
    library.write_credits_sources(library.load_manifest(), library.load_catalog())
    print_json(rep) if args.json else print("generated %d sfx, %d music beds (%d already present) in %.0fs" % (
        rep["sfx"], rep["music"], rep["skipped"], rep["seconds"]))
    return 0


def cmd_lib_pin(args) -> int:
    from .audio import library
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    print_json(library.pin(Path(args.manifest) if args.manifest else None, args.tier, only))
    return 0

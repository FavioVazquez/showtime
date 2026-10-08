"""`showtime audio ...`: music, sound effects, library, analysis, mixing, mastering.

Heavy imports (numpy/scipy) happen inside the handlers, so `showtime --help`
stays fast and a missing dependency only affects these commands.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

from .common import ShowtimeError, human_size, print_json, warn

COMMANDS = {
    "audio": "Music (produced catalog/compose/library), sound effects, beats, mixing, credits, loudness, mastering",
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
        "  music      produced music catalog (Scott Buckley, Kevin MacLeod, OpenGameArt ...): search, pick, fetch,\n"
        "             credits; fetched on first use; also live Openverse search\n"
        "  compose    procedural music in 18 styles, exact length, stems + MIDI + beats.json\n"
        "  styles     list music styles (bpm, key, moods, what they suit)\n"
        "  sfx        render a procedural sound effect (prints its hit time)\n"
        "  sfx-types  list the 56 procedural effect types\n"
        "  lib        audio library: fetch, search, info, index, credits, stats, sources, generate\n"
        "  packs      extra sound-effect packs (CC0 foley, UI, impacts, ambience), fetched on first use\n"
        "  credits    credits.txt + description block + end-card line for a mix report or ids\n"
        "  cuts       music-led cut plan: the excerpt of a track and scene changes on its phrases\n"
        "  beats      beat grid, downbeats, onsets, energy, sections, key -> beats.json\n"
        "  fit        loop or trim music to an exact length on bar lines\n"
        "  mix        render an audio/mix.json (ducking, hit alignment, loudness) + report\n"
        "  meter      loudness (LUFS), true peak, LRA, RMS, clipping\n"
        "  master     normalise a file to a loudness target (default -14 LUFS / -1 dBTP)\n"
        "  musicgen   optional MusicGen draft music (non-commercial weights)"),
        epilog="Examples:\n"
               "  showtime audio music pick --for launch --dur 45             # a produced track for a launch film\n"
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

    p = s.add_parser("film-score", help="write a new score.js for a film project (key, tempo, chords, motif, sound)",
                     formatter_class=_F,
                     description="Write the film template's score.js from a new signature: key and mode, a tempo "
                                 "and meter that keep the cues on bar lines, a progression, a motif, the "
                                 "instruments and the drums, picked for the mood and away from the scores of "
                                 "recent jobs (the look history). `showtime new film` does this once; run it again "
                                 "for another score. A score.js you wrote by hand is kept unless --force.",
                     epilog="Examples:\n  showtime audio film-score my-film\n"
                            "  showtime audio film-score my-film --mood tension\n"
                            "  showtime audio film-score my-film --seed 7 --json")
    p.add_argument("project")
    p.add_argument("--mood", choices=["calm", "upbeat", "tension", "playful", "cinematic"],
                   help="default: from the job's goal and the title, else a seeded choice")
    p.add_argument("--seed", type=int, help="a fixed seed (default: the project and the history)")
    p.add_argument("--force", action="store_true", help="replace a hand-written score.js")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_film_score)

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

    _register_music(s)
    _register_lib(s)
    _register_packs(s)
    _register_credits(s)

    p = s.add_parser("cuts", help="music-led cut plan: excerpt + scene changes on phrase starts, swell on the end card",
                     formatter_class=_F, description=(
        "Pick the excerpt of a produced track that fits a short film and put the scene changes on its\n"
        "phrase starts (4-bar boundaries), with the track's biggest swell where the end card starts.\n"
        "The excerpt is scored for a calm-to-loud shape, no silence under the hook, no dropouts and an\n"
        "end on a phrase. TRACK is a catalog id (`showtime audio music search`), a file, or nothing:\n"
        "then the best catalog track --for the use (default launch) is picked and fetched.\n\n"
        "--apply <project> moves the project's scenes to the cuts (like `showtime retime --cuts`) and\n"
        "writes the excerpt as the music track of its audio/mix.json (effects and voice stay); an\n"
        "element with data-credit on the page gets the music's short credit line."),
        epilog="Examples:\n"
               "  showtime audio cuts --for launch --dur 30 --scenes 5            # plan only\n"
               "  showtime audio cuts buckley-with-these-hands --apply <job>/project\n"
               "  showtime audio cuts music/theme.mp3 --dur 24 --scenes 4 --end-card 5 --json\n"
               "  showtime audio cuts --apply <job>/project --offset 142.2        # keep a chosen excerpt")
    p.add_argument("track", nargs="?", help="catalog id or audio file (default: pick --for USE)")
    p.add_argument("--for", dest="use", default="launch", help="catalog use when no TRACK is given (default launch)")
    p.add_argument("--dur", "-d", type=float, help="film length in seconds (default: the project's)")
    p.add_argument("--scenes", "-n", type=int, help="number of scenes (default: the project's, else 5)")
    p.add_argument("--end-card", type=float, metavar="S", help="length of the end card (default 20%% of the film, 4-7 s)")
    p.add_argument("--hook", type=float, metavar="S", help="length of the opening scene (default 16%% of the film, 3.5-6 s)")
    p.add_argument("--offset", type=float, metavar="S", help="use the excerpt starting here instead of searching")
    p.add_argument("--apply", metavar="PROJECT", help="retime this project's scenes to the cuts and set its music track")
    p.add_argument("--dry-run", action="store_true", help="with --apply: show the changes, write nothing")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_cuts)

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
    p.add_argument("--no-speaker-safe", action="store_true",
                   help="leave the lows as mixed: no high-pass under 40 Hz and no low shelf on a bass-heavy bed (for a "
                        "video meant for headphones; the same as \"master\": {\"speaker_safe\": false})")
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


def _music_filters(p) -> None:
    p.add_argument("--for", dest="use", help="what the music is for: launch, trailer, explainer, tutorial, data, "
                   "documentary, story, promo, social, product-demo, tech, background (see `music presets`)")
    p.add_argument("--shelf", help="cinematic, inspiring, ambient, corporate-tech, upbeat, documentary, tension, "
                   "playful, lofi, piano, orchestral (comma list)")
    p.add_argument("--mood", help="e.g. hopeful, calm, epic, dark (comma list)")
    p.add_argument("--energy", help="0..1 or a range, e.g. 0.2-0.5")
    p.add_argument("--dur", type=float, help="the video's length in seconds (ranks tracks that cover it)")
    p.add_argument("--min-dur", type=float)
    p.add_argument("--max-dur", type=float)
    p.add_argument("--vocals", help="none, some, lead (comma list; explainer presets allow none only)")
    p.add_argument("--source", help="buckley, incompetech, opengameart, wikimedia, archive (comma list)")
    p.add_argument("--license", help="cc-by, cc0, pd, CC-BY-4.0 ... (comma list)")
    p.add_argument("--ending", help="clean (a final hit and ring-out), soft (fade or quiet outro), cut, unknown")
    p.add_argument("--all", action="store_true", help="include tracks you vetoed")


def _register_music(s) -> None:
    m = s.add_parser("music", help="produced music catalog: search, pick, fetch, credits, veto", formatter_class=_F,
                     description="A curated catalog of produced recordings (Scott Buckley, Kevin MacLeod, composers on OpenGameArt, CC0 and "
                                 "public-domain recordings), tagged by shelf, mood, energy and use. "
                                 "Nothing is bundled: a track is fetched from its creator's site the first time it is "
                                 "used (\"fetching X (N MB) for Y\"), checked against its pinned sha256 and kept in "
                                 "~/.showtime/music, so it works offline afterwards. Every mix that uses one writes the "
                                 "exact credit into credits.txt and the description block of share.txt.",
                     epilog="Examples:\n"
                            "  showtime audio music pick --for launch --dur 45\n"
                            "  showtime audio music search --for explainer --mood calm --limit 5\n"
                            "  showtime audio music search hopeful piano\n"
                            "  showtime audio music fetch buckley-with-these-hands\n"
                            "  showtime audio music info buckley-with-these-hands\n"
                            "  showtime audio music openverse calm cinematic piano    # live search beyond the catalog\n"
                            "In a mix: {\"kind\": \"music\", \"catalog\": \"buckley-with-these-hands\", \"fit\": true}")
    ms = m.add_subparsers(dest="music_cmd", metavar="<subcommand>")

    p = ms.add_parser("search", help="search the catalog", formatter_class=_F,
                      epilog="Examples:\n  showtime audio music search --for launch\n"
                             "  showtime audio music search --shelf ambient,piano --energy 0-0.3 --dur 60\n"
                             "  showtime audio music search epic --source buckley --json")
    p.add_argument("words", nargs="*", help="words matched against title, artist, moods, uses, instruments")
    _music_filters(p)
    p.add_argument("--limit", "-n", type=int, default=12, help="maximum results (default 12)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_music_search)

    p = ms.add_parser("pick", help="the best track for a use and length (optionally fetch it)", formatter_class=_F,
                      epilog="Examples:\n  showtime audio music pick --for launch --dur 45\n"
                             "  showtime audio music pick --for explainer --dur 90 --n 1    # the second-best\n"
                             "  showtime audio music pick --for trailer --fetch --json")
    p.add_argument("words", nargs="*")
    _music_filters(p)
    p.add_argument("--n", type=int, default=0, help="0 = best, 1 = second best ... (variety between videos)")
    p.add_argument("--fetch", action="store_true", help="download it now (otherwise the mix fetches it on first use)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_music_pick)

    p = ms.add_parser("fetch", help="download tracks now (verified, cached)", formatter_class=_F,
                      description="Download catalog tracks into ~/.showtime/music (sha256-verified). Mixes fetch on "
                                  "first use anyway; this is for working offline later.",
                      epilog="Examples:\n  showtime audio music fetch buckley-with-these-hands\n"
                             "  showtime audio music fetch --for launch --limit 5\n"
                             "  showtime audio music fetch --all                 # the whole catalog (see `music stats`)\n"
                             "  showtime audio music fetch --all --seed /media/usb/showtime-seed")
    p.add_argument("ids", nargs="*")
    p.add_argument("--for", dest="use")
    p.add_argument("--shelf")
    p.add_argument("--limit", type=int, default=5, help="with --for/--shelf: how many (default 5)")
    p.add_argument("--all", action="store_true", help="every active track in the catalog")
    p.add_argument("--seed", action="append", metavar="DIR", help="folder with already-downloaded copies (offline)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_music_fetch)

    p = ms.add_parser("info", help="one track: tags, length, license, exact credit, cache state", formatter_class=_F,
                      epilog="Examples:\n  showtime audio music info buckley-with-these-hands\n"
                             "  showtime audio music info with-these-hands --path")
    p.add_argument("id")
    p.add_argument("--path", action="store_true", help="print only the cached file path (fetches it first)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_music_info)

    p = ms.add_parser("veto", help="never pick a track again (or --undo)", formatter_class=_F,
                      epilog="Examples:\n  showtime audio music veto incompetech-cipher --reason \"too busy\"\n"
                             "  showtime audio music veto --import vetoes.json     # the list the curation board exports\n"
                             "  showtime audio music veto incompetech-cipher --undo")
    p.add_argument("ids", nargs="*")
    p.add_argument("--reason", default="")
    p.add_argument("--undo", action="store_true")
    p.add_argument("--import", dest="import_file", help="a JSON list of ids (or {\"vetoed\": [...]})")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_music_veto)

    p = ms.add_parser("stats", help="catalog counts by shelf, source and license; cache size", formatter_class=_F)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_music_stats)

    p = ms.add_parser("presets", help="what each --for use means (shelves, energy, vocals)", formatter_class=_F)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_music_presets)

    p = ms.add_parser("check", help="(maintainers) validate the catalog; --online also checks every URL",
                      formatter_class=_F)
    p.add_argument("--online", action="store_true", help="HEAD every file URL (slow, polite; a few minutes)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_music_check)

    p = ms.add_parser("openverse", help="live search of CC BY / CC0 music on Openverse (beyond the catalog)",
                      formatter_class=_F,
                      description="Search Openverse (Freesound and Wikimedia Commons) for CC BY and CC0 audio. "
                                  "Anonymous use is limited (about 20 searches a minute, 200 a day) and responses are "
                                  "cached for a day. Nobody has listened to these: preview before using one. "
                                  "--fetch downloads one result with a .license.json, so the mix credits it. "
                                  "Jamendo is left out unless you ask (--source jamendo): its own terms add "
                                  "conditions to commercial use and its licensing program can claim videos.",
                      epilog="Examples:\n  showtime audio music openverse calm piano --limit 5\n"
                             "  showtime audio music openverse whoosh --license cc0\n"
                             "  showtime audio music openverse --fetch openverse:b8d9b313-... -o my-video/audio")
    p.add_argument("words", nargs="*")
    p.add_argument("--source", help="freesound, wikimedia (default: both); jamendo only on request (check the "
                   "artist's terms before publishing)")
    p.add_argument("--category", default="", help="music, sound_effect ... (Openverse only sets it on Jamendo results)")
    p.add_argument("--license", default="by,cc0", help="by, cc0, pdm (comma list; default by,cc0)")
    p.add_argument("--min-dur", type=float)
    p.add_argument("--max-dur", type=float)
    p.add_argument("--limit", "-n", type=int, default=10)
    p.add_argument("--fetch", metavar="ID", help="download this result (openverse:<uuid>)")
    p.add_argument("-o", "--output", default=".", help="folder for --fetch (default: here)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_music_openverse)

    m.set_defaults(func=lambda args: _group_help(m))


def _register_packs(s) -> None:
    k = s.add_parser("packs", help="extra sound-effect packs, fetched on first use", formatter_class=_F,
                     description="CC0 (and credited CC BY) sound-effect packs beyond the library's core tier: foley "
                                 "(paper, keyboards, typewriter, cloth, coins), UI, impacts, sci-fi, whooshes and "
                                 "ambiences. A mix that names a pack item, or searches a category with nothing "
                                 "installed, fetches the pack itself; this command does it ahead of time.",
                     epilog="Examples:\n  showtime audio packs list\n  showtime audio packs list --category foley\n"
                            "  showtime audio packs fetch oga-keyboard-typing\n"
                            "  showtime audio packs fetch --category ui\n  showtime audio packs fetch --all")
    ks = k.add_subparsers(dest="packs_cmd", metavar="<subcommand>")
    p = ks.add_parser("list", help="packs, size, license, installed or not")
    p.add_argument("words", nargs="*")
    p.add_argument("--category")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_packs_list)
    p = ks.add_parser("fetch", help="download + analyse packs into the library")
    p.add_argument("ids", nargs="*", help="pack ids (globs ok) or words")
    p.add_argument("--category")
    p.add_argument("--all", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_packs_fetch)
    k.set_defaults(func=lambda args: _group_help(k))


def _register_credits(s) -> None:
    p = s.add_parser("credits", help="credits.txt, description block and end card for a mix", formatter_class=_F,
                     description="Write the credits a video's sounds require: credits.txt (exact attribution lines, "
                                 "courtesy credits, an optional end-card line, Content ID notes) and a block in "
                                 "share.txt between '--- Credits (keep in the video description) ---' and "
                                 "'--- end credits ---' (replaced on every run; the rest of share.txt is kept). "
                                 "`showtime render` runs this for you; a CC BY sound without credit text is an error.",
                     epilog="Examples:\n  showtime audio credits --report my-video/audio/mix.report.json --out-dir my-video\n"
                            "  showtime audio credits buckley-with-these-hands incompetech-inspired\n"
                            "  showtime audio credits --report mix.report.json --end-card")
    p.add_argument("ids", nargs="*", help="catalog track ids or library item ids (instead of --report)")
    p.add_argument("--report", help="a mix.report.json")
    p.add_argument("--out-dir", help="write credits.txt (and the share.txt block) into this folder")
    p.add_argument("--name", default="credits.txt", help="credits file name (default credits.txt)")
    p.add_argument("--merge", help="an existing credits file whose other lines are kept (render passes its own)")
    p.add_argument("--no-share", action="store_true", help="do not touch share.txt")
    p.add_argument("--end-card", action="store_true", help="print only the end-card line(s)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_credits)


def _register_lib(s) -> None:
    lib = s.add_parser("lib", help="audio library: fetch, search, info, index, credits, stats", formatter_class=_F,
                       description="The local audio library in ~/.showtime/library (CC0 / CC-BY / generated).",
                       epilog="Examples:\n  showtime audio lib fetch                    # core tier, ~249 MB, ~10-15 min\n"
                              "  showtime audio lib fetch --part music-epic  # one part of the library (see --list-parts)\n"
                              "  showtime audio lib search --kind music --mood uplifting --bpm 100-130 --min-dur 60\n"
                              "  showtime audio lib search riser --kind sfx\n"
                              "  showtime audio lib info incompetech-voxel-revolution")
    ls = lib.add_subparsers(dest="lib_cmd", metavar="<subcommand>")

    p = ls.add_parser("fetch", help="download + analyse library tiers", formatter_class=_F,
                      description="Download the manifest's sources (core: pinned sha256; extended: sha256 recorded on "
                                  "first download and verified after), transcode music to Opus, analyse every "
                                  "file, render the generated tier, and write catalog.json + CREDITS-SOURCES.md. "
                                  "Re-running skips what is installed.",
                      epilog="Tiers: core (~249 MB), extended (core + ~200 MB more music and effects).\n"
                             "Parts: the starter part (~41 MB) arrives on first use of the library; category parts\n"
                             "(sfx, ambience, music-upbeat, music-calm, music-epic) arrive when a search needs them,\n"
                             "or now with --part NAME. (Extra sound-effect packs: `showtime audio packs`.)")
    p.add_argument("--tier", default="core", choices=["core", "extended"])
    p.add_argument("--part", help="fetch only this part (starter, sfx, ambience, music-upbeat, music-calm, music-epic, "
                                  "extended; comma list ok)")
    p.add_argument("--list-parts", action="store_true", help="list the parts, their sizes and what is installed")
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
    p.add_argument("--limit", "-n", type=int, default=15, help="maximum results (default 15)")
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


def cmd_film_score(args) -> int:
    from .audio import filmscore
    from .common import read_json
    proj = Path(args.project).expanduser().resolve()
    if not (proj / "score.js").is_file() or not (proj / "cues.js").is_file():
        raise ShowtimeError("%s has no score.js and cues.js" % proj, hint="this works on a film project (showtime new film)")
    title = str((read_json(proj / "showtime.json", {}) or {}).get("title") or "")
    sig = filmscore.apply(proj, brief=title, mood=args.mood, seed=args.seed, force=args.force)
    if sig is None:
        raise ShowtimeError("score.js in %s was written by hand: kept" % proj, hint="--force replaces it")
    if args.json:
        print_json(sig)
    else:
        print("score.js: %s %s, %g bpm in %d/4, %s chords, %s motif, %s, %s drums (%s mood)" % (
            sig["key"], sig["mode"], sig["bpm"], sig["meter"], sig["progression"], sig["motif"], sig["palette"],
            sig["drums"], sig["mood"]))
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


def cmd_cuts(args) -> int:
    from .audio import cutplan
    from .common import read_json
    proj = Path(args.apply).expanduser().resolve() if args.apply else None
    dur, scenes = args.dur, args.scenes
    if proj is not None:
        if proj.is_file() and proj.name == "showtime.json":
            proj = proj.parent
        cfg = read_json(proj / "showtime.json", {})
        if not cfg:
            raise ShowtimeError("no showtime.json in %s" % proj, hint="--apply takes the project folder")
        dur = dur or float(cfg.get("duration") or 0) or None
        if scenes is None:
            from .cli_core import _Tags, _split_tops
            page = proj / str(cfg.get("page") or "index.html")
            if page.is_file():
                scenes = len(_split_tops(_Tags(page.read_text(encoding="utf-8")).resolve())[0]) or None
    if not dur:
        raise ShowtimeError("how long is the film?", hint="pass --dur 30, or --apply <project> to read it")
    scenes = scenes or 5
    source: Dict[str, Any]
    credit = None
    label = ""
    if args.track and Path(args.track).expanduser().is_file():
        path = Path(args.track).expanduser().resolve()
        rel = path
        if proj is not None:
            try:
                rel = Path(os.path.relpath(str(path), str(proj)))
            except ValueError:
                rel = path
        source = {"file": rel.as_posix()}
        label = path.name
    else:
        from .audio import music
        t = music.get(args.track) if args.track else music.pick(use=args.use, dur=dur)
        path = music.fetch(t, purpose="the cut plan")
        source = {"catalog": t["id"]}
        credit = music.end_card_line(t)
        label = "%s (%s)" % (t["id"], t["artist"])
    an = cutplan.analysis_for(path)
    p = cutplan.plan(an, float(dur), int(scenes), end_card=args.end_card, offset=args.offset, hook=args.hook)
    p["track"] = label
    p["source"] = source
    if credit:
        p["credit_line"] = credit
    if proj is not None:
        p["applied"] = cutplan.apply(p, proj, source, credit_line=credit, dry_run=args.dry_run)
    if args.json:
        print_json(p)
        return 0
    print(cutplan.summary(p, label))
    print("mix track: " + json.dumps(cutplan.music_track(p, source)))
    if proj is not None:
        for line in p["applied"]["changes"]:
            print(("  would " if args.dry_run else "  ") + line)
        if not args.dry_run:
            print("next: showtime check %s" % proj)
    else:
        print("apply: showtime retime <project> --cuts %s -d %g   (or rerun with --apply <project>)"
              % (",".join("%g" % c for c in p["cuts"]), p["dur"]))
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
                     report_path=Path(args.report) if args.report else None, ffmpeg_check=args.check,
                     speaker_safe_on=False if args.no_speaker_safe else None)
    if args.json:
        print_json(rep)
        return 0
    print("%s  %.2fs  %s LUFS  %s dBTP  LRA %s" % (rep["output"], rep["duration"], rep["integrated_lufs"],
                                                   rep["true_peak_dbtp"], rep["lra"]))
    if rep.get("voice_to_music_db") is not None:
        print("  voice sits %.1f dB above music/ambience while speaking" % rep["voice_to_music_db"])
    sp = rep.get("speaker") or {}
    if sp.get("above_300_lufs") is not None:
        print("  on a phone speaker (above 300 Hz): %.1f LUFS, %.1f LU under the mix%s" % (
            sp["above_300_lufs"], sp["gap_300_lu"],
            "; speaker-safe: low shelf %g dB on %s" % (sp["shelf_db"], ", ".join(sp.get("shelved") or []))
            if sp.get("shelf_db") else "" if sp.get("on") else "; speaker-safe off"))
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
    from .audio import library, libparts
    if args.list_parts:
        rows = libparts.status()
        if args.json:
            print_json(rows)
        else:
            for r in rows:
                print("%-13s %9s  %-9s %s" % (r["id"], human_size(r["bytes"]), "installed" if r["ready"] else
                                              "missing %s" % human_size(r["missing_bytes"]), r["description"]))
        return 0
    if args.part:
        rc = 0
        for name in [x.strip() for x in args.part.split(",") if x.strip()]:
            rep = libparts.ensure(name, "`audio lib fetch --part %s`" % name)
            print("%s: fetched %d sources%s" % (name, rep.get("fetched", 0),
                                                ("; %d failed" % len(rep["failed"])) if rep.get("failed") else ""))
            rc = rc or (1 if rep.get("failed") else 0)
        return rc
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
    hint = None
    if (args.category or (args.kind or "") in ("sfx", "ambience")) and len(res) < args.limit:
        from .audio import packs
        hint = packs.hint_for(args.category, " ".join(args.words) or None)
    if not res:
        print("no matches (loosen the filters, or run `showtime audio lib stats`)", file=sys.stderr)
        if hint:
            print(hint, file=sys.stderr)
        return 1
    for r in res:
        print(str(library.item_path(r["item"])) if args.paths else search.row(r))
    if hint:
        print(hint, file=sys.stderr)
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


# ------------------------------------------------------------------------------------------ produced music
def _music_kw(args) -> dict:
    return dict(use=args.use, shelf=args.shelf, mood=args.mood, energy=args.energy, dur=args.dur, min_dur=args.min_dur,
                max_dur=args.max_dur, vocals=args.vocals, source_id=args.source, license=args.license,
                ending=args.ending, include_vetoed=args.all)


def _fmt_dur(sec: float) -> str:
    return "%d:%02d" % (int(sec) // 60, int(round(sec)) % 60)


def _music_row(t: dict, score=None, width: int = 40) -> str:
    """One search result. The id is never cut (it is what `music info` and mix.json take): the column is as
    wide as the longest id shown, and only the moods are shortened."""
    from .audio import music
    cached = "cached" if music.is_cached(t) else "%.0f MB" % (t["bytes"] / 1e6)
    lic = music.LICENSES[t["license"]][1]
    return "%-*s %5s  %-14s e%.2f %-6s %-9s %-30s %s" % (
        width, t["id"], _fmt_dur(t["duration"]), t["shelf"], t["energy"], t["tempo"], lic,
        ", ".join(t["moods"][:3])[:30], cached)


def cmd_music_search(args) -> int:
    from .audio import music
    res = music.search(" ".join(args.words) or None, limit=args.limit, **_music_kw(args))
    if args.json:
        print_json([{"id": r["track"]["id"], "score": r["score"], "why": r["why"], "cached": music.is_cached(r["track"]),
                     **r["track"]} for r in res])
        return 0 if res else 1
    if not res:
        print("no matches (loosen the filters; `showtime audio music presets` lists the uses)", file=sys.stderr)
        return 1
    width = max([40] + [len(r["track"]["id"]) for r in res])
    for r in res:
        print(_music_row(r["track"], width=width))
    print("%d shown. Details and the exact credit: showtime audio music info <id>" % len(res))
    return 0


def cmd_music_pick(args) -> int:
    from .audio import music
    t = music.pick(n=args.n, words=" ".join(args.words) or None, **_music_kw(args))
    path = music.fetch(t, purpose="music pick") if args.fetch else None
    item = music.credit_item(t)
    if args.json:
        print_json({**t, "path": str(path) if path else None, "cached": music.is_cached(t), "credit": item})
        return 0
    print("%s  \u201c%s\u201d by %s, %s, %s, energy %.2f" % (t["id"], t["title"], t["artist"], _fmt_dur(t["duration"]),
                                                             t["shelf"], t["energy"]))
    print("  moods: %s   ending: %s   vocals: %s" % (", ".join(t["moods"]), t["ending"], t["vocals"]))
    print("  preview: %s" % t["landing_url"])
    if path:
        print("  file: %s" % path)
    else:
        print("  mix track: {\"kind\": \"music\", \"catalog\": \"%s\", \"fit\": true}   (fetched on first use, %s)"
              % (t["id"], "cached" if music.is_cached(t) else "%.0f MB" % (t["bytes"] / 1e6)))
    print("  credit: " + (item["attribution"] or item["credit_optional"] or "").replace("\n", " / "))
    if item.get("content_id") == "smart-cid-releasable":
        print("  note: Smart Content ID: keep the credit in the video description (render puts it in share.txt)")
    return 0


def cmd_music_fetch(args) -> int:
    from .audio import music
    if args.all:
        ts = music.tracks(include_vetoed=False)
    elif args.ids:
        ts = [music.get(i) for i in args.ids]
    elif args.use or args.shelf:
        ts = [r["track"] for r in music.search(use=args.use, shelf=args.shelf, limit=args.limit)]
    else:
        raise ShowtimeError("name tracks to fetch, or use --for/--shelf/--all",
                            hint="showtime audio music fetch buckley-with-these-hands")
    rep = music.fetch_many(ts, seeds=args.seed, purpose="offline use", bulk=not args.ids)
    if args.json:
        print_json(rep)
    else:
        print("fetched %d, already cached %d, failed %d, left for first use %d  (%s)" % (
            len(rep["fetched"]), len(rep["cached"]), len(rep["failed"]), len(rep["skipped"]), music.cache_root()))
        for f in rep["failed"]:
            print("  FAILED %s: %s" % (f["id"], f["error"]))
    return 1 if rep["failed"] and not (rep["fetched"] or rep["cached"]) else 0


def cmd_music_info(args) -> int:
    from .audio import music
    t = music.get(args.id)
    if args.path:
        print(music.fetch(t, purpose="music info --path"))
        return 0
    item = music.credit_item(t)
    if args.json:
        print_json({**t, "cached": music.is_cached(t), "cache_path": str(music.cached_path(t)), "credit": item})
        return 0
    for k in ("id", "title", "artist", "composer", "source", "duration", "shelf", "moods", "energy", "tempo", "uses",
              "vocals", "instruments", "ending", "quiet_intro_s", "highlight_s", "loops", "bpm", "license",
              "content_id", "landing_url", "notes"):
        v = t.get(k)
        if k == "source":
            v = music.source(t).get("name") or v
        if k == "duration":
            v = "%s (%.1f s)" % (_fmt_dur(v), v)
        if k == "quiet_intro_s":
            k, v = "quiet intro", ("%.0f s before it is clearly audible" % v) if v and v >= 3 else None
        if k == "highlight_s":
            k, v = "highlight", ("%s: its loudest stretch; start a short cut there with \"offset\": \"highlight\""
                                 % _fmt_dur(v)) if v and v >= 10 else None
        if v not in (None, [], ""):
            print("%-12s %s" % (k, ", ".join(map(str, v)) if isinstance(v, list) else v))
    print("%-12s %s" % ("file", music.cached_path(t) if music.is_cached(t) else "not fetched yet (%.1f MB, on first use)"
                        % (t["bytes"] / 1e6)))
    if item["attribution"]:
        print("CREDIT REQUIRED (%s):\n  %s" % (", ".join(t["placements"]), item["attribution"].replace("\n", "\n  ")))
    else:
        print("credit (optional): %s" % item["credit_optional"])
    print("end card:    %s" % item["end_card"])
    if item.get("content_id_note"):
        print("content id:  %s" % item["content_id_note"])
    if t["id"] in music.vetoed_ids():
        print("VETOED: this track is never picked automatically (`audio music veto %s --undo`)" % t["id"])
    return 0


def cmd_music_veto(args) -> int:
    from .audio import music
    from .common import read_json
    ids = list(args.ids)
    reasons = {}
    if args.import_file:
        d = read_json(args.import_file)
        ids += list(d.get("vetoed") if isinstance(d, dict) else d)
        reasons = dict(d.get("reasons") or {}) if isinstance(d, dict) else {}
    if reasons and not args.undo:
        for i in ids:
            rep = music.veto([i], reason=reasons.get(i) or args.reason)
        print_json(rep) if args.json else print("vetoed %d track(s); %d vetoed in total (%s)" % (
            len(ids), len(rep["vetoed"]), rep["file"]))
        return 0
    if not ids:
        v = music.vetoed_ids()
        print_json(v) if args.json else print("\n".join("%s  %s" % (k, x.get("reason", "")) for k, x in sorted(v.items()))
                                              or "no vetoed tracks")
        return 0
    rep = music.veto(ids, reason=args.reason, undo=args.undo)
    print_json(rep) if args.json else print("%s %d track(s); %d vetoed in total (%s)" % (
        "restored" if args.undo else "vetoed", len(rep["changed"]), len(rep["vetoed"]), rep["file"]))
    return 0


def cmd_music_stats(args) -> int:
    from .audio import music
    st = music.stats()
    if args.json:
        print_json(st)
        return 0
    print("%d tracks, %.1f hours, %s if all fetched; %d cached in %s" % (st["tracks"], st["hours"], st["download_size"],
                                                                         st["cached"], st["cache"]))
    for k in ("shelf", "source", "license"):
        print("  %-8s %s" % (k, ", ".join("%s %d" % kv for kv in sorted(st[k].items(), key=lambda z: -z[1]))))
    if st["vetoed"]:
        print("  vetoed   %s" % ", ".join(st["vetoed"]))
    return 0


def cmd_music_presets(args) -> int:
    from .audio import music
    ps = music.load_catalog().get("presets") or {}
    if args.json:
        print_json(ps)
        return 0
    for k, v in sorted(ps.items()):
        print("%-13s shelves %-48s energy %.2f-%.2f  vocals %s" % (k, ",".join(v["shelves"]), v["energy"][0], v["energy"][1],
                                                                   ",".join(v.get("vocals") or ["any"])))
    return 0


def cmd_music_check(args) -> int:
    from .audio import music
    errs = music.validate()
    bad = []
    if args.online:
        import time as _t
        import urllib.request
        from .assets import net
        for t in music.tracks():
            try:
                req = urllib.request.Request(t["file_url"], method="HEAD", headers={"User-Agent": net.USER_AGENT})
                with urllib.request.urlopen(req, timeout=30, context=net._ssl_context()) as r:
                    size = int(r.headers.get("Content-Length") or -1)
                if size not in (-1, t["bytes"]):
                    bad.append("%s: size %d, catalog %d" % (t["id"], size, t["bytes"]))
            except Exception as e:  # noqa: BLE001
                bad.append("%s: %s" % (t["id"], e))
            _t.sleep(float((music.source(t).get("fetch") or {}).get("delay_s", 1.0)))
    if args.json:
        print_json({"errors": errs, "unreachable": bad})
    else:
        for e in errs + bad:
            print(e)
        print("catalog: %d problem(s)%s" % (len(errs), "; %d URL problem(s)" % len(bad) if args.online else ""))
    return 1 if errs or bad else 0


def cmd_music_openverse(args) -> int:
    from .audio import openverse
    if args.fetch:
        r = openverse.fetch(args.fetch, Path(args.output))
        print_json(r) if args.json else print("%s\n  license: %s\n  credit (written to %s): %s" % (
            r["path"], r["license"], Path(r["license_file"]).name, r["credit"]))
        return 0
    res = openverse.search(" ".join(args.words), category=args.category, licenses=args.license, limit=args.limit,
                           min_dur=args.min_dur, max_dur=args.max_dur, source=args.source)
    if args.json:
        print_json([{k: v for k, v in r.items() if k != "_raw"} for r in res])
        return 0 if res else 1
    if not res:
        print("no CC BY / CC0 results", file=sys.stderr)
        return 1
    for r in res:
        print("%s  %s  %-10s %s%s\n    \u201c%s\u201d by %s  (%s)" % (
            r["id"], _fmt_dur(r["duration"]), r["license"], r["source"], "  VOCALS" if r["vocals"] else "",
            r["title"], r["creator"], r["landing_url"]))
    print("Not curated: preview first. Download one with: showtime audio music openverse --fetch <id> -o <project>/audio")
    return 0


def cmd_packs_list(args) -> int:
    from .audio import packs
    have = set(packs.installed_ids())
    rows = packs.matching(args.words or None, args.category)
    if args.json:
        print_json([dict(p, installed=p["id"] in have) for p in rows])
        return 0
    from .common import human_size
    for p in rows:
        print("%-40s %-10s %4d files %9s  %-10s %s" % (p["id"], p["category"], p.get("files") or 0, human_size(p["bytes"]),
                                                      p["license"], "installed" if p["id"] in have else ""))
    print("%d pack(s). Fetch: showtime audio packs fetch <id> (or --category X / --all)" % len(rows))
    return 0


def cmd_packs_fetch(args) -> int:
    from .audio import packs
    if args.all:
        pks = packs.load()["packs"]
    else:
        pks = []
        for w in args.ids:
            for p in packs.matching([w]):
                if p not in pks:
                    pks.append(p)
        if args.category:
            pks += [p for p in packs.matching(None, args.category) if p not in pks]
    if not pks:
        raise ShowtimeError("no pack matches", hint="list them: showtime audio packs list")
    rep = packs.install(pks, reason="audio packs fetch", force=args.force)
    if args.json:
        print_json(rep)
    else:
        print("installed %d, already present %d, failed %d" % (len(rep["installed"]), len(rep["skipped"]), len(rep["failed"])))
        for f in rep["failed"]:
            print("  FAILED %s: %s" % (f["id"], f["error"]))
    return 1 if rep["failed"] and not rep["installed"] else 0


def cmd_credits(args) -> int:
    from .audio import credits as cr
    from .audio import library, music
    items = []
    if args.report:
        items += cr.items_from_report(args.report)
    for i in args.ids:
        try:
            items.append(music.credit_item(music.get(i)))
        except ShowtimeError:
            it = library.get_item(i)
            items.append({"id": it["id"], "title": it.get("title"), "artist": it.get("artist"), "license": it.get("license"),
                          "attribution": it.get("attribution"), "attribution_required": it.get("attribution_required"),
                          "credit_optional": it.get("credit_optional")})
    extra = cr.lines_from_file(Path(args.merge)) if args.merge else []
    r = cr.render(items, extra)
    if args.end_card:
        print("\n".join(r["end_card"]) or "(no music needs an end-card line)")
        return 0
    res = {"required": r["required"], "end_card": r["end_card"], "notes": r["notes"], "description": r["description"]}
    if args.out_dir:
        res.update(cr.write(Path(args.out_dir), items, credits_name=args.name, share=not args.no_share, extra_lines=extra))
    if args.json:
        print_json(res)
        return 0
    if args.out_dir:
        if res.get("credits_file"):
            print("credits: %s" % res["credits_file"])
        if res.get("share_file"):
            print("share:   %s (credits block updated)" % res["share_file"])
    else:
        print(r["credits_txt"].rstrip())
    for n in r["notes"]:
        warn(n)
    return 0

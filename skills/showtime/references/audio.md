# Audio tools: compose, effects, library, beats, mix, master

Read this when a video needs music, sound effects, a voice-over mix or a loudness check, and you
need the exact `showtime audio` commands and the `audio/mix.json` format. For choosing music by
tone, read `music.md`. For how loud, how many and where sounds go, read `sound-design.md`. For
music written in code inside a canvas film, read `synth-score.md`.

Everything runs locally. Every command has `--help` with examples, and most accept `--json`.

## 1. The five-minute path

```bash
showtime audio lib fetch                                    # once: ~249 MB library (~10-15 min), safe to re-run
showtime audio compose --style underscore --dur 45 \
    --sections 0:intro,6:verse,24:break,40:outro -o audio/bed.wav     # which style: music.md
showtime audio sfx whoosh -o audio/whoosh.wav               # prints JSON with "hit"
showtime audio mix audio/mix.json -o audio/mix.wav          # mastered to -14 LUFS / -1 dBTP + report
showtime audio meter audio/mix.wav                          # verify, never guess
```

When a project's `showtime.json` has `"audio": "audio/mix.json"`, `showtime render` runs the mix
itself. Run `audio mix` on its own while iterating: it takes seconds, and the report shows what
changed.

## 2. Music

| Need | Command |
|---|---|
| Music cut exactly to the edit, with section changes on picture changes | `audio compose --style S --dur D --sections "t:name,..."` |
| A real recording from the library | `audio lib search --kind music --mood calm --min-dur 60` |
| A library track at exactly the video's length | `audio fit track.opus --dur 42.5 -o bed.wav` (bar-aligned loop or musical ending; `--ending song` keeps the track's own ending) |
| The beat grid of any track | `audio beats track.mp3` (writes `track.beats.json`) |
| Temp music from a text prompt (non-commercial) | `audio musicgen "prompt" --dur 20 -o draft.wav` (optional tier) |

`audio compose` details:
- `--style` is one of 18 styles (`audio styles`; default `underscore`). `--bpm` and `--key` default to the style's own.
- `--sections "0:intro,8:build,16:drop,26:outro"`. Names: intro, verse, build, drop, chorus, break,
  bridge, outro. Every marker lands exactly on a downbeat. The tempo is nudged per section (usually
  under 2 %, up to about 6-7 % for very short sections) and a section may get a 2-beat bar to make
  that happen. Above a 3 % bend, or with a 2-beat bar, compose warns and prints a `--bpm` that puts
  every marker on whole bars (when one exists near the asked tempo), or the same markers moved to
  whole bars at the asked tempo. A marker inside the final hit's ring-out (for example `27:outro` in a
  30 s bed whose hit lands at 27.14 s) merges into the ending, with a one-line note.
- The piece ends with a final tonic hit, snapped to the grid inside a short ring-out. The file is
  exactly `--dur` seconds (sample-exact). `end_hit` in the output is the time of that hit: put the
  logo there.
- Transitions come with it: a riser that lands on each drop, reverse cymbals into energetic
  sections, an impact on drops for cinematic styles, and a downlifter into outros (`--no-sfx` removes them).
- Outputs: `bed.wav` (mastered, -14 LUFS), `bed.mid`, `bed.beats.json` (beats, downbeats, bars,
  sections, events, `end_hit`, the `backend` and `soundfont` file actually used, the plan `notes`), `bed.stems/{drums,bass,pad,arp,lead,keys,sfx}.wav`.
- `--backend auto|sf|synth|hybrid`: SoundFont instruments (GeneralUser GS), the numpy synth, or synth
  drums/bass with SoundFont keys and strings. If `tinysoundfont` or the SoundFont is missing, it
  falls back to the synth automatically. It still works, it just sounds more electronic.
- `--seed N` gives a different melody and variation with the same structure. Try 2 or 3 seeds.

## 3. Sound effects

- `audio sfx-types` lists 56 procedural types in 7 categories, with their hit kind:
  - `onset`: the sound hits at its start (impacts, clicks, bells).
  - `peak`: the loudest moment (whooshes, sparkles).
  - `end`: the build-up lands on the last sample (risers, reverse cymbals, swells, sparkle-up).
- `audio sfx <type> [--dur --key --intensity 0..1 --seed N] -o file.wav` writes `file.wav` and
  `file.sfx.json`, and prints the JSON: `hit` (seconds), `hit_frame_30fps`, `category`, and the level.
  `audio mix` reads the sidecar, so `"align": "hit"` uses the true hit automatically.
- Tonal types (riser, swell, notification, success, bell, logo-sting, drone, and others) take
  `--key`. Give them the music's key so effects sit in the harmony.
- Output is loudness-matched per category (`sound-design.md` §2), so `gain_db: 0` in a mix is a
  sensible level.
- `--variants 4` renders four seeds (`x-1.wav` ... `x-4.wav`). Use a different variant for each
  repeat, so repeated clicks don't sound identical.
- Library effects (Kenney, OpenGameArt and generated variants) carry `hit`, `category` and
  `harshness` in the catalog.

## 4. Library

```bash
showtime audio lib fetch [--tier core|extended] [--no-generated]   # idempotent; resumes
showtime audio lib search whoosh --kind sfx --distinct              # words match ids, titles, tags, moods
showtime audio lib search --kind music --mood uplifting --bpm 100-130 --min-dur 60 --license cc0
showtime audio lib search --kind music --key Am --dur 45            # compatible keys rank higher
showtime audio lib info incompetech-voxel-revolution                # details + the exact credit line
showtime audio lib credits <id> <id> -o CREDITS.txt
showtime audio lib stats | sources | generate
showtime audio lib index ~/Sounds/MyPack --name mypack --license "vendor-license"   # your own pack, in place
```

- **Tiers:**
  - `core` (~249 MB) has every Kenney CC0 audio pack, OpenGameArt CC0 packs and ambiences, about 45
    Kevin MacLeod tracks and stings (CC-BY 4.0, stored as Opus), and CC0 music from Komiku, Loyalty
    Freak Music and Musopen (Chopin).
  - `generated` is rendered locally and needs no download: about 160 effect variants and 28 composed beds.
  - `extended` adds about 1 GB more music. Core sources are pinned (URL, size, sha256); most extended
    sources are not pinned yet, so their sha256 is recorded in `state.json` on the first download and
    every re-download must match it (trust on first use). Maintainers pin them with
    `showtime audio lib pin --tier extended`.
- **Licenses:** CC0 and generated items need no credit. **CC-BY items must be credited**. `audio mix`
  writes `CREDITS.txt` next to its output and lists the credits in the report; `showtime render`
  copies them into `credits.txt` beside the final, which is the file that ships. Paste them into the
  video description. `--license cc0` avoids the question entirely.
  - A library file copied into a project and used as `"file"` keeps its license: the mix matches it
    to the catalog by content (size, then sha256). A file with a `<file>.license.json` sidecar uses
    that. A music `file` with neither gets a warning (use `"lib": "<id>"`, or add the sidecar).
- **Kinds and categories:**
  - Kinds are `music`, `stinger` (short musical hits and jingles), `sfx`, `ambience` and `voice`
    (announcer words).
  - SFX categories are `ui`, `transition`, `impact`, `foley`, `fx`, `musical` and `ambience`.
  - `--kind ambience` also lists sfx items that can serve as a bed (at least 3 s, loopable or named
    or tagged as a loop, such as a 7 s water loop in a foley pack), ranked below real ambience items
    and marked "an sfx loop (catalogued as sfx)".
- **Moving the library:** set `SHOWTIME_LIBRARY=/path` to keep it elsewhere, for example on an external disk.

## 5. The mix spec (`audio/mix.json`)

```json
{ "duration": 20.0,
  "tracks": [
    {"id": "bed", "kind": "music", "file": "audio/bed.wav", "gain_db": -2,
     "fade_out": 1.2, "duck": {"under": "voice", "depth_db": 12, "carve": 0.4}},
    {"kind": "voice", "file": "voice/vo.wav", "start": 0.6},
    {"kind": "sfx", "file": "audio/whoosh.wav", "at": 3.0, "align": "hit"},
    {"kind": "sfx", "synth": {"type": "impact", "key": "D", "intensity": 0.8, "seed": 3}, "at": 17.5},
    {"kind": "sfx", "lib": "kenney-interface-sounds/click-001", "at": 5.2, "gain_db": -4, "pan": 0.3},
    {"kind": "ambience", "lib": {"search": {"query": "rain", "kind": "ambience"}}, "loop": true, "gain_db": -3}
  ],
  "sections": {"intro": 0, "demo": 4, "cta": 16},
  "master": {"lufs": -14, "true_peak": -1}
}
```

- **Sources:** each track has exactly one.
  - `file`: a path.
  - `lib`: a catalog id, or `{"search": {...}, "pick": 0}`.
  - `synth`: an `audio sfx` spec.
  - `compose`: an `audio compose` spec. The duration defaults to the rest of the mix, and the result
    is cached by content hash.
- **Levels:** `level: "auto"` is the default. Each track is first brought to its kind's reference:
  voice -16 LUFS, music -20 LUFS, ambience -32 LUFS, sfx by category. `gain_db` is then relative to
  that. Use `"level": "raw"` to keep a file's own level.
- **Placement:**
  - `start` (timeline seconds), `offset` (skip into the source), `end` or `dur`.
  - `at` + `align` (`hit|start|end|peak`) puts that point of the sound exactly on `at`. `hit` in the
    track overrides the measured hit (seconds from the file start).
- **Length:** `loop: true` or `fit: true` fills the window. Music loops on bar lines when a beat grid
  is known (a `.beats.json` sidecar, a composed track, or a library item), and ends musically.
- **Shape:** `fade_in` and `fade_out`, plus `pan` from -1 to 1. Every clip edge gets at least 3–5 ms
  of fade, so there are no clicks.
- **Ducking:** `duck: {"under": "voice" | ["voice", "sfx"] | [track ids], "depth_db": 12, "attack": 0.08,
  "release": 0.5, "hold": 0.3, "lookahead": 0.12, "carve": 0..1}`.
  - The duck follows the activity of the key tracks: speech for voice, and any other track too (a
    list of sfx ids ducks the bed under the key clicks). It starts 120 ms early, holds across short
    pauses and releases slowly.
  - `carve` also cuts the bed only in the voice's own bands, biased to 1–4 kHz, and only while the
    voice speaks. 0.3–0.5 is transparent; above 0.7 it starts to sound hollow.
- **Typing in a recorded demo:** `{"kind": "sfx", "keystrokes": "media/events.json", "start": 10.8,
  "rec_offset": 7.85, "rate": 1.75}` clicks once per typed character and key combo of a `demo record`,
  in sync with the recording placed at `start` (`rec_offset` = the recording time shown there, `rate`
  = its `data-rate`), so no click times are converted by hand.
- **Typing on a page `typewriter`:** `{"kind": "sfx", "typewriter": {"text": "npm create showtime", "cps": 18},
  "start": 2.5}` clicks once per typed character (and backspace) on the component's own timeline: give it
  the same `text` or `script`, `cadence`, `cps`, `fit` and `seed` as the page, and `start` = the video
  time the typing starts (its clip's start plus `data-at`).
- **Designed layers and masking:** the report warns when an effect is under the rest of the mix. Tracks
  of one family (same file stem or explicit id prefix such as `key-01`..`key-38`, the same synth type)
  never count as "the rest" for each other; a riser whose hit is its end is judged before its end;
  `"layer": "<id>"` marks a track stacked on another (a braam on an impact); `"texture": true` skips
  the check for a track meant to sit under (soft UI clicks under a voice). Masked tracks of one
  family are reported as one line.
- **Gain automation:** `gain_points: [[t, db], ...]` on any track (timeline seconds, linear in dB
  between points, end values hold), e.g. `[[0, 4], [2.6, 4], [3.2, 0]]` lifts a quiet hook by 4 dB.
  `section_gain` on a music bed sets a level per section with 0.25 s ramps: `{"intro": 3}` (the
  composed bed's section names) or `{"0": 2.5, "5": 0}` (seconds). This is the fix for "the intro is
  too quiet": a short sfx cannot lift a whole section, and renaming a section changes the arrangement.
- **`sections`:** optional names for the report. They default to the composed track's sections, or
  5 s windows.
- **`master`:**
  - `lufs` (default -14) and `true_peak` (default -1).
  - `engine` is `st` (exact, the default), `loudnorm` (ffmpeg two-pass) or `none`.
  - Output formats are `.wav` (24-bit), `.flac`, `.m4a`, `.mp3` and `.opus`.
- **Paths** resolve against the mix.json folder, then the project root (the folder with
  `showtime.json`), then the current directory. `--root` overrides.

`mix.report.json` contains:
- integrated LUFS, true peak and LRA, plus the pre-master levels
- per section: LUFS, RMS and the RMS of each bus
- `voice_to_music_db`: how far the voice sits above the music and ambience while speaking (aim for 10–20)
- per track: gain, level reference and alignment, plus duck and carve statistics; for a music bed
  its landmarks on the output timeline (`end_hit`, `music_sections`, `downbeats`) and, for a composed
  bed, the `backend_used` and `soundfont_file` (the credit line for the SoundFont): line up the logo
  with `end_hit` from here, not from the cache; for each sfx `above_bed_db`, its loudest 25 ms over
  everything else (under 0 dB it is probably masked, and the report warns)
- the library items used and their credits
- warnings (voice too close to the music, a first section more than 6 LU under the loudest, masked
  effects, clipping, heavy limiting, non-commercial sources)
- paths relative to the report's folder, so a report can be copied or published

Read the report before you listen. Then listen.

## 6. Analysis and delivery

- **`audio beats file`** writes `bpm`, `bpm_confidence`, `beats`, `downbeats`, `onsets` (each tagged
  kick/snare/hat), an `energy` curve (0.5 s), `sections` (energy phases VOID/LOW/MEDIUM/HIGH),
  `moments` (SURGE/DROP) and `key`.
  - **Trust `rhythmic`/`pacing`:** with `beat_cut`, hard cuts may sit on beats. With `phrase_flow`
    (ambient or rubato music), the grid is fictional: cut on phrases and energy changes instead.
  - For composed music the grid is exact by construction (`source: "composed"`).
  - The tempo usually matches metadata within 1–3 %. On-beat vs off-beat phase can still be wrong
    on dense dance music with offbeat bass, so check the first downbeats on a waveform view when a
    hard sync matters.
- **`audio meter file [--windows 1] [--ffmpeg]`** gives integrated, short-term max, momentary max,
  LRA, true peak (8x oversampled), sample peak, RMS, clipped runs and DC. `--ffmpeg` cross-checks
  with ffmpeg's ebur128.
- **`audio master in -o out [--target youtube|podcast|broadcast|...] [--preset mix|music|voice|none]`**
  normalises to within 0.05 LU with true peak at or below the ceiling. Master to WAV and encode once
  at the end: AAC and MP3 add up to about 0.5 dB of overshoot.

## 7. Platform notes

- **Everything portable:** all DSP is numpy/scipy. ffmpeg comes from the resolver, for decoding,
  Opus encoding and the loudnorm engine, and paths go to it as plain arguments, so Windows drive
  letters are fine.
- **SoundFonts:** rendering uses `tinysoundfont`. It has ready-made wheels for macOS arm64,
  Windows and Linux x64. On Intel macOS and Linux arm64 it is compiled at setup; if that fails,
  compose uses the numpy synth for every part (styles still work).
- **MusicGen** lives in its own venv (`showtime setup --with musicgen`). On CPU it runs roughly
  10x slower than real time. Its weights are **CC-BY-NC**, so never use its output in a commercial
  video. The mix report warns when it is used.

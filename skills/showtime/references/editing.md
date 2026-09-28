# Editing real footage by transcript

Read this when the user hands you real video (a talking head, an interview, a screen recording
with narration, a pile of takes) and wants it cut, tightened, captioned, reframed for vertical,
or turned into a short. It covers the workflow, the EDL format, the render and the rules that keep
an edit correct. Caption styles and numbers live in `captions.md`; the individual tools (scenes,
reframe, denoise, stabilize, grade, looks, timeline views) are in `footage-tools.md`.

Everything runs locally: speech recognition, speaker labels, audio events, face tracking, grading.
You cannot watch or listen to the result, so every step below ends with something you can read
(JSON, a packed transcript, a PNG) instead.

## 1. The workflow

| Step | Command | Done when |
|---|---|---|
| 1. Inventory | `showtime footage probe <file>` per file, `showtime footage scenes <file> --every 5` for a look (written to the job's `work/scenes/`, never beside the footage) | you know durations, orientation, fps, HDR, audio tracks, what is on screen |
| 2. Transcribe | `showtime transcribe raw/ --edit-dir <job>/edit` (folder or files) | every take has `<job>/edit/transcripts/<name>.json` |
| 3. Pack | `showtime pack <job>` | you have read `<job>/edit/takes_packed.md` end to end |
| 4. Converse | ask at most 1-2 questions (length, platform, what must stay), only when the request leaves them open | goal, target length and aspect are clear |
| 5. Strategy | state the plan in 3-6 lines: keep/cut logic, order, aspect, captions, music, look | stated as an assumption; confirmed by the user only when it drops content (takes, sentences, order) |
| 6. EDL | `showtime edit cut ...` then edit the JSON by hand as needed; `showtime edit check edl.json` (or `edit check <job>`: its latest EDL) | `edit check` passes and the plan reads right |
| 7. Preview | `showtime edit render edl.json --preview` (a second run writes `preview-2.mp4` and prints it; `--overwrite` reuses the name) | the render report has `frames_ok: true` and no warnings |
| 8. Self-eval | `showtime edit view edl.json` (the newest render of that EDL; it prints which) + read the PNGs; loudness numbers from the report | every cut looks and reads clean (see section 6) |
| 9. Iterate | edit the EDL, render the preview again (unchanged segments are reused) | at most 3 passes, then ask |
| 10. Final | `showtime edit render edl.json` (default beside the EDL; a workflow's `-o <job>/final.mp4` wins) | final.mp4 + final.report.json + final.srt, then `showtime deliver exports` if needed |

Tell the user the time cost up front for anything long: transcription runs at roughly 0.1 x the
audio length with Parakeet and 0.3-0.5 x with Whisper turbo on a 6-core laptop (more on older
machines, much less on Apple Silicon).

## 2. Transcripts

`showtime transcribe` writes one word-level, verbatim transcript per file (and per audio track):

```json
{"source": "/abs/take1.mp4", "duration": 42.1, "language": "en", "model": "large-v3-turbo",
 "words": [{"id": "w0", "text": "So,", "start": 0.52, "end": 0.81, "type": "word", "speaker": "S0", "conf": 0.93},
           {"text": " ", "start": 0.81, "end": 1.2, "type": "spacing"},
           {"id": "w1", "text": "um,", "start": 1.2, "end": 1.5, "type": "word", "speaker": "S0", "conf": 0.8},
           {"id": "w9", "text": "(laughter)", "start": 5.1, "end": 6.0, "type": "audio_event"}],
 "guards": {"dropped": [], "warnings": []}}
```

- **Model choice.** `auto` uses Whisper large-v3-turbo when installed (best, 99 languages), else
  `small.en`. `--model parakeet` is the fast English engine (about 3x less CPU than turbo, keeps
  fillers). Pass `--language xx` for non-English speech if turbo is not installed.
- **Fillers are kept on purpose.** A disfluency prompt keeps "um"/"uh"; they are edit points.
- **Word edges are snapped** to the audio energy (typically 200-300 ms raw error -> ~10-80 ms).
- **Guards against invented text:** silent tracks are refused (`--audio-track N` for OBS-style
  multi-track files), words with no speech energy nearby, words after the audible end and
  repetition loops are dropped and listed in `guards.dropped`. Read `guards.warnings`.
- **Speakers:** `--speakers 2` (or `auto`) labels words S0, S1... Pass the real count when known. It
  can miss short interjections ("Yeah.") or label a long window as one voice; when a published
  transcript exists, align it (`showtime voice align <audio> -f transcript.txt`) and take each turn's
  speaker from its labels instead (captions.md, section 6).
- **Names and jargon:** `--prompt "showtime, Kokoro, ffmpeg"` biases Whisper toward them.
- Results are cached by content: re-running is instant unless the media changed (`--force` to redo).
- **Part of a long file:** `--from 12:30 --to 18:00` (seconds or mm:ss) transcribes only that stretch.
  Word times stay on the file's own clock (offset by `--from`), the transcript gets `"range": [750, 1080]`,
  `duration` is the range's end, and it is written as `<name>.750-1080.json` beside any full transcript
  (cached per range). Cuts planned from it drop everything outside the range. Use it to find a moment in a
  long recording fast; transcribe the whole file when the edit spans it.
- Correcting a transcript is allowed (fix spelling in `text`), never move `start`/`end` by hand.

## 3. Reading the material

`takes_packed.md` shows every phrase as `[start-end wFirst-wLast] SPEAKER text`, breaking at pauses
of 0.5 s or more. Read all of it before proposing an edit. Look for: the strongest opening line
(hook), false starts and retakes (keep the last clean take of a sentence), the payoff line, dead
air, laughter/applause events worth keeping.

## 4. The EDL

```json
{"sources": {"a": "../raw/take1.mp4", "b": {"file": "../raw/obs.mkv", "audio_track": 1}},
 "ranges": [{"source": "a", "start": 2.40, "end": 7.95, "note": "hook"},
            {"source": "b", "start": 31.10, "end": 38.42, "zoom": 1.12},
            {"source": "a", "start": 9.10, "end": 15.30, "grade": "punch"}],
 "output": {"aspect": "9:16", "fps": 30, "fit": "auto"},
 "grade": {"auto": true, "lut": "teal-orange", "strength": 0.5},
 "captions": {"style": "bold-pop"},
 "overlays": [{"file": "../assets/logo.png", "start": 0.5, "duration": 3, "position": "top-right", "width": "18%", "fade": 0.3},
              {"file": "../broll/city.mp4", "start": 12.0, "duration": 2.5, "position": "full", "offset": 4.0}],
 "audio": {"music": {"file": "../music/bed.wav", "gain_db": -4}, "denoise": "auto"},
 "loudness": {"lufs": -14, "tp": -1}}
```

Paths are relative to the EDL file. Times are seconds (`"1:02.5"` also works).

| Field | Meaning | Default |
|---|---|---|
| `sources` | name -> file (or `{file, audio_track}`) | required |
| `ranges[]` | `source`, `start`, `end` in source seconds, played in order | required |
| `ranges[].fit / zoom / focus` | per-range framing: fit mode, punch-in 1.0-3.0, fixed centre `{"x","y"}` 0..1 | output fit, 1.0, face track |
| `ranges[].grade / stabilize / volume_db / mute / note` | per-range overrides | global / off / 0 / false |
| `output.aspect` | `16:9 9:16 1:1 4:5 4:3 21:9 720p 1080p 4k 4k-vertical` or `width`/`height` | first source's size (max 4K) |
| `output.fps` | output rate; every source is normalised to it | first source, snapped to a standard rate |
| `output.fit` | `cover`, `contain`, `blur` (whole frame on a blurred copy), `reframe` (face-tracked crop), `auto` | `auto` |
| `grade` | `none`, `auto`, preset, look, or `{auto, preset, lut, strength, filter}` | `none` |
| `captions` | style name or `{style, font, highlight, color, position, max_words, fillers, srt}` | none |
| `subtitles` | a ready `.ass/.srt/.vtt` to burn instead of generated captions | none |
| `overlays[]` | `file` (png/jpg/mov/webm/mp4), `start` (output time), `duration`, `offset` (in the overlay), `position` (`full`, `center`, `top-left` ... `bottom-right`), `x`/`y`/`width`/`height` (px or `"10%"`), `scale`, `opacity`, `fade`, `fit`, `audio`, `volume_db`, `duck_db` | centred, 40 % wide, silent |
| `audio.music` | a file (or `{file, gain_db, fade_in, fade_out, loop}`): looped, faded, ducked under speech | none |
| `audio.tracks[]` | any `audio/mix.json` track (music, sfx, synth, library id), times on the output timeline | none |
| `audio.denoise` | `auto`, `deepfilter`, `rnnoise`, `afftdn` | off |
| `loudness` | `{lufs, tp}`, a number, or `false` | -14 LUFS / -1 dBTP |

A formula or diagram over footage: render it with `showtime manim render <scene.py> --alpha -o <job>/edit/eq.webm` (VP9 with alpha) and add it as an `overlays[]` entry with `"position": "full"`; the alpha channel is kept (`references/manim.md`, integration).

`auto` fit: same aspect -> `cover`; a taller source into a wider frame (phone clip in 16:9) ->
`blur`; a wider source into a taller frame -> `reframe` (face tracking, centre when no face).

`showtime edit cut` writes a correct EDL from transcripts: `--max-pause 0.5` shortens long pauses,
fillers go by default (`--keep-fillers`), `--remove w40-w52` drops a retake, `--remove-time`,
`--keep-time`, `--aspect`, `--captions`, `--grade`, `--music`, `--denoise`. It also stores a
`cut_summary` (what was removed and why) for you to review. Several transcripts play in order.

## 5. Hard rules (correctness)

1. **Never cut inside a word.** Range edges come from word boundaries plus padding: keep 30-200 ms
   (defaults: 50 ms before a word, 80 ms after; plosive endings need 60-80 ms).
2. **Pad removals generously.** Fillers have soft onsets; the cut reaches 40 ms past them.
3. **Leave breath.** Where material was removed keep ~0.3 s of pause; long pauses shrink to that.
4. **Keep the last clean take** of a repeated sentence, never splice half of two takes.
5. **Frame-exact offsets.** Each range becomes `round(duration x fps)` frames; the output time of
   every segment is the running sum of frames actually written. Captions, overlays and music use
   those offsets, so there is no drift however many cuts there are. Do not compute offsets yourself;
   read them from `edit check` or the render report.
6. **30 ms audio fades** at every join (automatic). Segments keep PCM audio until the final encode,
   so no codec gap appears at cuts. A range that starts exactly where the previous one ended in the
   same source (a reframe-only split: same take, new `zoom`/`focus`) joins with no fade, so the
   sound stays continuous; set such splits to frame-aligned times (`start + frames / fps`): `edit
   check` reports two ranges of one source that overlap or miss by less than a frame and prints the
   exact start to use. With face tracking on (`fit` auto resolves to `reframe`), a range's `focus` is
   only the fallback; for a fixed crop use `"fit": "cover"` plus `focus` on the range. The tracker
   starts where the face settles (the median of the first second) and its dead zone shrinks with
   `zoom`, so a punch-in stays centred.
7. **Captions and subtitles are burned last**, over overlays.
8. **Loudness is mastered once**, on the final program: -14 LUFS / -1 dBTP by default
   (`loudness: -16` for tutorials and podcasts). The renderer masters 0.5 dB under the ceiling to
   leave room for AAC.
9. **One output frame rate**; mixed sources are converted. HDR (PQ/HLG) is tone-mapped to SDR,
   phone rotation is honoured, sources without audio get silence.
10. **Outputs are never overwritten** unless `--overwrite`; the next free `name-2.mp4` (or `edl-2.json`
    for `edit cut`) is used and printed. Use the printed path, or a job argument, from then on.
11. **Everything the session makes lives in an `edit/` folder** inside a job: `<job>/edit/`
    (`transcribe` makes a `<name>-edit` job when there is none). Never next to the user's footage
    unless they say so (`--edit-dir`), never in the skill.

## 6. Self-evaluation (you cannot watch it)

After every render:

1. Read `<out>.report.json`: `frames_ok` must be true, `warnings` empty, `loudness` within 1 LU of
   the target, `true_peak_dbtp` at or under the ceiling.
2. `showtime edit view edl.json` and read every PNG. Each cut shows the filmstrip, the waveform,
   the words and the pauses around it. Look for: a word clipped at a cut (waveform cut mid-shape,
   word label missing), a double word across a join, dead air over 0.6 s. Jump cuts in a tightened
   talking head are left as they are by default: they read as a clean edit, while a punch-in that
   goes back out at the next cut reads as a bouncing zoom (`edit check` and `edit render` flag
   alternating scales). Use `zoom` only when asked or for a reason in the content: one scale held for
   a whole sentence or section (1.06-1.12, e.g. a tighter frame for the key answer), a single push
   for emphasis, or a vertical reframe; never a different scale on every other range.
3. For captions, check the render report's `captions.timing` (all zeros is correct) and a frame or
   two (`showtime footage view final.mp4 --from 3 --to 6`).
4. For anything published, transcribe the output (`showtime transcribe final.mp4 --edit-dir edit/qa`)
   and confirm no fillers or clipped words remain.
5. Say what you checked and what you could not (you did not listen to it).

Stop after 3 fix-and-render passes and ask the user.

## 7. Recipes

- **Tighten a talking head:** `edit cut t.json --max-pause 0.5` -> preview -> view.
- **Vertical short from a landscape interview:** `edit cut t.json --aspect 9:16 --captions bold-pop
  --remove w0-w25` (drop the warm-up); the face-tracked reframe already frames it, so no alternating
  punch-ins.
- **Best-of from several takes:** transcribe all, pack, write `ranges` by hand from the packed lines
  (one source key per take), `edit check`, preview.
- **Podcast clip with speakers:** `transcribe --speakers 2`, choose ranges by speaker lines, captions
  `clean`, `loudness: -16`. For a long episode, transcribe only a window around the part you want
  (`transcribe ep.mp3 --from 21:30 --to 24:00`; times stay on the episode's clock).
- **Same edit, many formats:** render once per aspect with `--aspect` / `-o`, or render the 16:9
  master and use `showtime deliver exports`.

## 8. Red flags

| Tempting shortcut | Do this instead |
|---|---|
| Writing ranges from memory of the transcript | Copy times from `takes_packed.md` or use `edit cut` |
| Cutting exactly at a word's start/end time | Keep the padding; let `edit cut` compute edges |
| Declaring the edit done after the render exits 0 | Read the report and the cut views first |
| Re-transcribing to "check" a cached transcript | The cache is keyed by content; it is already current |
| Using `.en` Whisper models on non-English audio | `--language xx` (switches to a multilingual model) |
| Hard-coding caption offsets or overlay times from range sums | Use output times from `edit check` |

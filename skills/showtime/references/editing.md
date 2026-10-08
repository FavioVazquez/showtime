# Editing real footage by transcript

Read this when the user hands you real video (a talking head, an interview, a screen recording
with narration, a pile of takes) and wants it cut, tightened, captioned, reframed for vertical,
or turned into a short. It covers the workflow, the EDL format, the render and the rules that keep
an edit correct. Caption styles and numbers live in `captions.md`; the individual tools (scenes,
reframe, denoise, stabilize, grade, looks, timeline views) are in `footage-tools.md`.

Everything runs locally: speech recognition, speaker labels, audio events, face tracking, grading.
You cannot watch or listen to the result, so every step below ends with something you can read
(JSON, a packed transcript, a PNG) instead.

## Essentials

- Order: `showtime footage probe <file>`, `showtime transcribe raw/ --edit-dir <job>/edit`, `showtime pack <job>`
  (read all of `takes_packed.md`), a 3-6 line plan, `showtime edit cut ...`, `showtime edit check edl.json` (§1)
- Then `showtime edit render edl.json --preview` and `showtime edit view edl.json`; final `showtime edit render
  edl.json` (a workflow's `-o <job>/final.mp4` wins), `showtime deliver exports` if needed (§1)
- Ask at most 1-2 questions; the user confirms the plan only when it drops content (takes, sentences, order);
  tell them the transcription time up front for anything long (§1)
- Transcripts: Parakeet (`auto`) covers 25 European languages, others need `--language xx`; never pick
  `--model crisper` for the user; `--speakers N`, `--from`/`--to` for a window (§2)
- Fix spelling in `text` only; never move `start`/`end` by hand (§2)
- Never cut inside a word: keep 30-200 ms of padding (defaults 50 ms before, 80 ms after); keep ~0.3 s of breath
  where material was removed (0.2 s at a filler) (§5)
- Keep the last clean take of a repeated sentence; never splice half of two takes (§5)
- Never compute output offsets yourself; read them from `edit check` or the render report (§5)
- Loudness is mastered once: -14 LUFS / -1 dBTP by default; another level only when asked (`--lufs N`,
  `--keep-loudness`, `"loudness": false`) (§5)
- Outputs are never overwritten without `--overwrite`: use the printed path (`name-2.mp4`); everything lives in
  `<job>/edit/`, never beside the user's footage (§5)
- `edit cut`: fillers go by default (`--keep-fillers`); "mm-hmm" is a word; "you know", "este" go only with
  `--filler-set en-discourse`/`es-discourse`; `--remove w40-w52` drops a retake (§4)
- `output.fit` `auto`: same aspect `cover`, a taller source into a wider frame `blur`, wider into taller
  `reframe` (face-tracked crop) (§4)
- Leave jump cuts in a talking head; no punch-in on every other range (one scale 1.06-1.12 per section, with a
  reason) (§6)
- After every render: report `frames_ok: true`, `warnings` empty, loudness within 1 LU, `captions.timing` all
  zeros; read every `edit view` PNG; say what you could not check (you did not listen) (§6)
- Published work: `showtime transcribe final.mp4 --edit-dir edit/qa` to confirm no fillers or clipped words;
  stop after 3 fix-and-render passes and ask (§6)
- Copy range times from `takes_packed.md` or `edit cut`, never from memory (§8)
- Cards (title, lower third, pull-quote, data callout, chapter, list, side panel, a big word behind the speaker)
  go in the EDL's `cards`, anchored to a phrase (`say`) or a word id, never to seconds; `showtime edit cards
  suggest <edl>` lists moments (§9)
- `behind` cuts the speaker out over the word (MODNet on the CPU); `showtime footage cutout <clip>` writes the
  speaker alone with alpha for another editor (§9)
- Cards and captions stay off the face (9:16 cards with no room become splits); `edit check` lists each card's times and every problem; caption
  `emphasis` takes the 3-5 terms that carry the message (§9)
- A long recording into short clips: `showtime edit moments` ranks whole-sentence moments (suggestions: read and pick
  in `moments.json`), `showtime edit clips` makes one EDL, render and qa per pick, in parallel, and a sheet (§10)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. The workflow | 67-84 |
| 2. Transcripts | 86-136 |
| 3. Reading the material | 138-143 |
| 4. The EDL | 145-199 |
| 5. Hard rules (correctness) | 201-236 |
| 6. Self-evaluation (you cannot watch it) | 238-258 |
| 7. Recipes | 260-272 |
| 8. Red flags | 274-283 |
| 9. Cards: graphics anchored to the words | 285-379 |
| 10. Highlights: a long recording's best moments as clips | 381-432 |

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

Tell the user the time cost up front for anything long: transcription with the default Parakeet
model runs at roughly 0.1-0.2 x the audio length on a 6-core laptop (0.3-0.5 x with Whisper turbo;
much less on Apple Silicon). The first transcription fetches the model once (~490 MB, announced).

## 2. Transcripts

`showtime transcribe` writes one word-level, verbatim transcript per file (and per audio track):

```json
{"source": "/abs/take1.mp4", "duration": 42.1, "language": "en", "language_source": "guessed",
 "model": "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
 "words": [{"id": "w0", "text": "So,", "start": 0.52, "end": 0.81, "type": "word", "speaker": "S0", "conf": 0.93},
           {"text": " ", "start": 0.81, "end": 1.2, "type": "spacing"},
           {"id": "w1", "text": "um,", "start": 1.2, "end": 1.5, "type": "word", "speaker": "S0", "conf": 0.8},
           {"id": "w9", "text": "(laughter)", "start": 5.1, "end": 6.0, "type": "audio_event"}],
 "guards": {"dropped": [], "warnings": []}}
```

- **Model choice.** `auto` uses Parakeet-TDT 0.6B v3: verbatim (it writes "um"/"uh" as words),
  25 European languages including English and Spanish, fetched on first use. For other languages
  pass `--language xx`: auto then uses Whisper (turbo when installed, else small). `--model
  parakeet-v2` is the English-only Parakeet; `--model turbo` / `small` pick Whisper for anyone who
  wants it. `--model crisper` is the opt-in CrisperWhisper 2.0 "max accuracy" model: its weights are
  for non-commercial use only (it asks for `--accept-license` once), it needs PyTorch and is not
  available on Intel Macs. Never pick it for the user.
- **Language.** `language_source` says where `language` came from: `given` (`--language`), `model`
  (an English-only model), `detected` (Whisper heard it; `language_probability` is its confidence),
  `guessed` (Parakeet v3, from common words) or `default` (nothing to go on, so `en`). On `guessed` or
  `default` with speech that is not English, transcribe again with `--language xx`.
- **Fillers are kept on purpose;** they are edit points. After ASR a gap scan looks at voiced
  stretches no word covers (150-800 ms) and at words far longer than their spelling (an "uh" folded
  into them), decodes each again on its own, and adds the fillers found as words with
  `"filler": true, "detected": "gap-scan"`. A real word found that way is never marked (the transcript
  lists it under `filler_scan`). `--no-gap-scan` turns it off.
- **Speech under music.** For a video showtime rendered itself (a voiced motion render, or an edit
  with a music bed), transcribe reads the dry narration stem the render kept, not the mix, and says
  so (`audio_from`; `--no-stem` for the mix). For other footage it measures the background: when music
  sits within ~8 dB of the speech it first separates the voice (UVR MDX-Net, 67 MB on first use;
  credit UVR) and transcribes that (`stats.separation`); `--separate on|off` forces it.
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
| `ranges[].hold` | freeze the range's last frame this many seconds (0-10), the sound fading out: an ending with air | 0 |
| `ranges[].fade_out` | fade the range's sound out over its last seconds (0-5, a quadratic curve): a clip that ends on applause | 30 ms edge fade |
| `output.aspect` | `16:9 9:16 1:1 4:5 4:3 21:9 720p 1080p 4k 4k-vertical` or `width`/`height` | first source's size (max 4K) |
| `output.fps` | output rate; every source is normalised to it | first source, snapped to a standard rate |
| `output.fit` | `cover`, `contain`, `blur` (whole frame on a blurred copy), `reframe` (face-tracked crop), `auto` | `auto` |
| `grade` | `none`, `auto`, preset, look, or `{auto, preset, lut, strength, filter}` | `none` |
| `captions` | style name or `{style, font, highlight, color, position, max_words, fillers, srt, emphasis}` (`emphasis`: words or phrases coloured in the look's accent, §9) | none |
| `subtitles` | a ready `.ass/.srt/.vtt` to burn instead of generated captions | none |
| `overlays[]` | `file` (png/jpg/mov/webm/mp4), `start` (output time), `duration`, `offset` (in the overlay), `position` (`full`, `center`, `top-left` ... `bottom-right`), `x`/`y`/`width`/`height` (px or `"10%"`), `scale`, `opacity`, `fade`, `fit`, `audio`, `volume_db`, `duck_db` | centred, 40 % wide, silent |
| `audio.music` | a file (or `{file, gain_db, fade_in, fade_out, loop}`): looped, faded, ducked under speech | none |
| `audio.tracks[]` | any `audio/mix.json` track (music, sfx, synth, library id), times on the output timeline | none |
| `audio.denoise` | `auto`, `deepfilter`, `rnnoise`, `afftdn` | off |
| `loudness` | `{lufs, tp}`, a number, or `false` / `"source"` (keep the source level) | -14 LUFS / -1 dBTP |
| `cards[]` | designed cards anchored to the words: `type`, `say` or `word`, timing and content (§9) | none |
| `look` | a look signature id (`showtime signature`) for the cards and the caption emphasis | the brand kit, else one picked once for the EDL |

A formula or diagram over footage: render it with `showtime manim render <scene.py> --alpha -o <job>/edit/eq.webm` (VP9 with alpha) and add it as an `overlays[]` entry with `"position": "full"`; the alpha channel is kept (`references/manim.md`, integration).

`auto` fit: same aspect -> `cover`; a taller source into a wider frame (phone clip in 16:9) ->
`blur`; a wider source into a taller frame -> `reframe` (face tracking, centre when no face).

`showtime edit cut` writes a correct EDL from transcripts: `--max-pause 0.5` shortens long pauses,
fillers go by default (`--keep-fillers`; words the gap scan flagged go too; the pause left where a
filler was is capped at `--filler-pause`, 0.2 s; every cut edge moves to the quietest point within
40 ms, `--no-snap` to keep them; `--strict-fillers` cuts only fillers a second, isolated decode heard
again: fewer false cuts, some fillers stay). A listener's "mm-hmm" / "uh-huh" is a word (it means yes),
never a filler. Spanish "este", "o sea" and English "you know", "like" are real words
elsewhere, so they go only when asked: `--filler-set es-discourse` / `en-discourse`, or `--filler "o
sea"`. `--remove w40-w52` drops a retake, `--remove-time`,
`--keep-time`, `--aspect`, `--captions`, `--grade`, `--music`, `--denoise`. It also stores a
`cut_summary` (what was removed and why) for you to review. Several transcripts play in order.

## 5. Hard rules (correctness)

1. **Never cut inside a word.** Range edges come from word boundaries plus padding: keep 30-200 ms
   (defaults: 50 ms before a word, 80 ms after; plosive endings need 60-80 ms).
2. **Pad removals generously.** Fillers have soft onsets; the cut reaches 40 ms past them.
3. **Leave breath.** Where material was removed keep ~0.3 s of pause (0.2 s where a filler was);
   long pauses shrink to that.
4. **Keep the last clean take** of a repeated sentence, never splice half of two takes.
5. **Frame-exact offsets.** Each range becomes `round(duration x fps)` frames; the output time of
   every segment is the running sum of frames actually written. Captions, overlays and music use
   those offsets, so there is no drift however many cuts there are. Do not compute offsets yourself;
   read them from `edit check` or the render report.
6. **20 ms equal-power audio crossfades** at every cut (automatic; `audio.crossfade` in the EDL,
   0-0.05 s, 0 = the older 30 ms fade-out/fade-in); the first and last edges fade 30 ms. Segments keep PCM audio until the final encode,
   so no codec gap appears at cuts. A range that starts exactly where the previous one ended in the
   same source (a reframe-only split: same take, new `zoom`/`focus`) joins with no fade, so the
   sound stays continuous; set such splits to frame-aligned times (`start + frames / fps`): `edit
   check` reports two ranges of one source that overlap or miss by less than a frame and prints the
   exact start to use. With face tracking on (`fit` auto resolves to `reframe`), a range's `focus` is
   only the fallback; for a fixed crop use `"fit": "cover"` plus `focus` on the range. The tracker
   starts where the face settles (the median of the first second) and its dead zone shrinks with
   `zoom`, so a punch-in stays centred.
7. **Captions and subtitles are burned last**, over overlays.
8. **Loudness is mastered once**, on the final program: -14 LUFS / -1 dBTP by default, the same
   target as every other showtime delivery, whatever the source level was (a -16 LUFS recording
   comes out at -14). Another level only when asked: `edit render --lufs N` or `"loudness": N`;
   to leave the source level alone, `edit cut --keep-loudness` / `edit render --keep-loudness` or
   `"loudness": false` (the report says `loudness_target: source` and qa notes it instead of
   failing it). The renderer masters 0.5 dB under the ceiling to leave room for AAC.
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
  `clean` (loudness stays -14 unless asked). For a long episode, transcribe only a window around the part you want
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

## 9. Cards: graphics anchored to the words

A talking head, a podcast clip, a lecture or an interview looks produced when designed cards appear as the
words are said. They live in the EDL, so a re-cut moves them with the words:

```json
"look": "tidewater",
"captions": {"style": "clean", "emphasis": ["space weather", "twenty two thousand miles"]},
"cards": [
  {"type": "lower-third", "say": "directly affected by the sun", "name": "Sarah Jones", "role": "Mission Scientist"},
  {"type": "list", "say": "it directly affects", "title": "Space weather affects",
   "items": [{"text": "Satellites", "say": "safety of our satellites"}, {"text": "GPS navigation", "say": "GPS navigation"}]},
  {"type": "stat", "say": "twenty two thousand miles", "value": 22000, "suffix": " miles", "label": "above Earth"},
  {"type": "panel", "say": "a whole half of the Earth", "title": "Half of Earth in one view", "until": "play out below"},
  {"type": "quote", "say": "the most comprehensive view we've ever had"}
]
```

| Type | Shows | Needs |
|---|---|---|
| `title` | kicker + headline on a plate | `title` (`kicker`, `text`) |
| `lower-third` | name and role (the lower-third component) | `name` (`role`, `variant`) |
| `quote` | the line as said, word by word on its spoken times; a cut into a sentence gets an ellipsis | (`text` replaces the words) |
| `stat` | a number counting up, its label, a source line | `value` (or a number in `say`), `prefix`, `suffix`, `label`, `source_note` |
| `chapter` | a full-frame interstitial on a scrim | `title` (`kicker`) |
| `list` | items that appear as each is said | `items` [{`text`, `say`}] (`title`) |
| `panel` | the speaker moves to one half (face-tracked), the panel fills the other: title, `body`, items, a `value` | `title` |
| `behind` | a big word behind the speaker: the plate, the word, then the speaker cut out on top | (`text`, else the words said; `kicker`, `background`, `color`) |

- **When.** `say` is a phrase as spoken (case, punctuation, `%` and number words do not matter: "twenty two
  thousand" matches "22,000", "two point five" 2.5, "nineteen ninety five" 1995); it takes the first match after
  the previous card's anchor and may span a cut; a card on the same words as the one before shares its anchor
  only when those words are not said again later (else anchor it with `word`). A stat's figure comes from its
  words only when they hold exactly one number; otherwise the card gives `value`. `word` (`"w57"`, with `source` for several
  takes) anchors to a transcript word. A card appears `lead` (0.12 s) before its first word and stays `hold`
  seconds after its last (per type, 1.8-4 s), until a later phrase (`until`), or `dur` seconds. Times snap to
  frames. A phrase that is not in the edit is an error that says why: never said, cut out (with its source
  time), or said only before the previous card.
- **Where.** 16:9: title top, lower third bottom-left above the captions, quote/stat/list in the half away from
  the face (YuNet; `side` overrides), chapter centred. 9:16: cards sit in the tallest stretch the face and the
  captions leave free inside the platform's safe box (under the chin); a card that does not fit there becomes a
  split (the speaker moves to the lower 45 %, the card fills the top, as for a panel); `"layout": "overlay"` keeps
  it on the full frame (then `edit check` reports the missing room), `"split"` asks for one. A card is never up
  while a split moves the speaker (check). A `box` (`{x, y, w, h}` frame fractions) places one by hand. A list on a
  plate grows as each item is said. A chapter in 9:16 is a split too (no scrim over the face). Splits or panels
  under 1.5 s apart keep the split between them, and a card's hold ends on the next cut once it has had its time.
  A card that would leave in the last second stays to the last frame (with a range `hold`, it rests there).
- **Captions never cover the face.** With cards (or `"captions": {"avoid_face": true}`), the face is tracked in
  windows of about 3 s and where the caption band would cover it (eyes to chin) the captions move just below the
  chin, else just above the eyes; with no room either way, `edit check` and qa (`caption_face`) say so.
  `"avoid_face": false` turns it off. A caption that runs across a split's edge (or a move) is cut there, each
  piece in its own place (qa reads the pieces as one caption).
- **Panel.** The render splits the ranges at the panel's first and last frame (reframe-only joins: continuous
  sound, no new cuts) and frames the speaker into their part of the frame. Captions under a panel centre on the
  speaker's half (16:9) or sit in the panel just above the seam (9:16), never over the speaker.
- **Behind.** `{"type": "behind", "say": "faster than ever before", "text": "Faster"}`: the word in the look's
  display face, as big as the frame allows, behind the speaker. 16:9: a speaker off-centre gets it on the free
  side with its last letter half behind the head (`"side"` picks a side, or `center`), its foot on the chin line
  so the shoulders never cover it; 9:16 and square: across the top with the head over its lower part, and when a
  close-up leaves no room above the head the speaker moves down for the card (a reframe-only split, like a panel;
  captions follow under the chin; `"layout": "overlay"` keeps the full frame). `background`: `footage` (the shot,
  default), `dim`, `blur` (a background blur), `ground` (the look's ground: a background swap), a colour
  (`"#0b1d3a"`) or an image file; a moved speaker gets the ground (there is no shot above them). `color`: `auto`
  (the look's accent when it reads), `accent`, `accent-2`, `fg`, `white` or `#rrggbb`. One word or two: a newline
  in `text` makes two lines. How it renders: the render cuts the speaker out of its own frames (a person matte
  per frame: MODNet, Apache-2.0, 26 MB, fetched on first use; CPU only, about 25 fps at 1080p on 64 cores, 6.7 on
  6 cores; smoothed over time and reset at every cut, refined at full size, cached) and composites the plate,
  the word, then the speaker, under every other card and the captions. The report's `cards.behind` has, per
  card, how much of the word the speaker hides (`hidden`, the widest hidden stretch `hidden_run`) and the
  matte's `flicker`; `edit check` estimates the share from the face before a render and prints the last render's
  numbers; qa warns (`behind_hidden` over 45 % hidden or a hidden stretch over 40 % of the word, `matte_flicker`
  over 2 % of the speaker's area jumping on a still picture). `edit cards suggest` offers the most stressed
  single word as a behind card.
- **Cut-out alone.** `showtime footage cutout talk.mp4 [--from 12 --to 18]` writes `<name>.cutout.webm` (VP9 with
  alpha: browsers, EDL overlays, `<video>` layers; `--format prores` a ProRes 4444 `.mov` for an editor, `png` a
  numbered PNG folder), `<name>.matte.mp4` (the matte alone, white = person: a luma matte anywhere) and
  `<name>.cutout-sheet.jpg` to look at (most players show a VP9 cut-out without its alpha). It cuts out people,
  not objects; the report gives the speed and the flicker. `--size 384` is about twice as fast and softer.
- **Look.** The EDL's `look`, else the job's brand kit, else a look signature picked once (kept in
  `work/<edl>/cards/look.json`). The caption emphasis uses its accent when it reads on footage.
- **How it renders.** Every card goes into one page (cards back to back) rendered once with alpha (QuickTime
  Animation) at the render's size, cached by its content, then composited as overlays under the captions (a
  behind card's layers first, so the other cards sit on the speaker). The render report has a `cards` block
  (times, boxes, problems) and qa repeats its problems (`card_problem`).
- **Checks.** `edit check` prints each card's output times and lists: reading time (0.5 s + characters / 13;
  a quote read along as said: characters / 20 + 0.5 s), cards sharing the screen and the place, a card on the
  caption band or out of the 9:16 safe box, a card taller than its room, a card up during a 9:16 split, captions
  with no room off the face, a list item said after its card leaves, a stat whose counted figure is up under
  1.5 s, over 12 s (a panel 30 s), and caption
  emphasis said more than once per 6 s or with more than 5 terms. `edit view` writes `<video>-cards-N.png`, one
  band per card with its in and out marked.
- **Suggestions.** `showtime edit cards suggest <edl | transcript>` lists numbers with units, names after
  "my name is"/"I'm", list markers and "X, Y and Z" enumerations, quotable lines, topic shifts and stressed
  words (louder and longer than their sentence), each with paste-ready card JSON. Pick the few that carry the
  story; every on-screen fact comes from the speaker's words or the source.

## 10. Highlights: a long recording's best moments as clips

A talk, panel, podcast, interview or stream becomes 3-10 short clips in two commands. showtime finds candidates
and makes the clips; you judge which moments stand alone (`workflows/footage-edit.md`, Highlights).

**`showtime edit moments <transcript(s) | job> [--count 8 --min 20 --max 60]`** prints a table and writes
`<edit dir>/moments.json` (`moments-2.json` when it exists). A candidate is a run of whole sentences of one
source whose clip would last `--min`..`--max` s once fillers and pauses over 0.5 s are trimmed; it starts where the
sentence before ended cleanly (end punctuation, or a pause or a new speaker without a trailing comma or "and"),
not on a reply ("Yeah.", "Thank you.") or a word in lower case after a pause; it never holds a 3 s pause or ends
on a lone "So". Speaker changes count only after a 0.3 s pause, and a label held for under 4 words is taken as
diarization noise. Each candidate gets these signals (0-1; the score is their weighted mean, leaving out what
could not be measured, which the table names):

| Signal | What counts | Weight |
|---|---|---|
| `hook` | the first 3 s (the rest of the first sentence at half): a question, a number, a strong claim, a contrast, a story opener ("I remember"), emotion, direct address | 0.20 |
| `complete` | a clean start (not "And", "Because", "That's why", "It's also") and end (a full stop, not a question, a pause or a new speaker after); a moment that switches speaker must end with the answer | 0.18 |
| `events` | laughter, applause or cheering from the transcript's audio events inside or right after the last word (before anyone speaks again); music under it counts against | 0.16 |
| `energy` | against the speaker's own median: level, level spread, pitch spread (autocorrelation pitch, 70-400 Hz) and pace, as percentiles over all candidates | 0.14 |
| `lines` | the best quotable line (claims, contrast, emotion, a number), short punchy sentences, a 3-word phrase said twice | 0.10 |
| `topic` | inside one topic segment (TextTiling over content words, no model), focused on a few of them | 0.10 |
| `flow` | no pause over 1.2 s, few fillers | 0.08 |
| `length` | near the middle of `--min`..`--max` | 0.04 |

Introductions, thanks, logistics and sponsor reads ("please join me in welcoming", "QR code", "use code") score
x0.7 and say so. The best non-overlapping candidates win (at least 3 s apart). Each moment has `id`, `rank`,
`score`, `source`, `transcript`, `start`/`end` (the first word's start and the last word's end, source seconds),
`span`, `duration` (the clip's estimated length), `words` (first and last id), `title` (the most quotable phrase,
the speaker's own words), `opening`, `closing`, `keywords`, `signals`, `why`, `speakers` (share of words),
`events`, `topic` (its segment; the file lists every segment with keywords under `sources`), `fillers`,
`housekeeping` and the full `text`. You edit the file: `"pick": true`, `title`, `start`/`end` (any time: the
edges snap to whole words) and `"remove": ["w12-w18"]` for a stretch to cut inside.

**`showtime edit clips [job] [--moments FILE] [--pick m1,m4 | --count 3] [--aspect 9:16] [--preview]`** makes the
picks (`--pick`, else `"pick": true`, else the best `--count`). Per moment it writes
`<job>/edit/clips/<NN>-<title>.json`: `edit cut`'s cut (fillers out, pauses over `--max-pause` 0.5 s down to 0.3 s,
edges at the quietest 10 ms), a start on the first real word (a filler or a "Yeah," / "Well," lead-in goes),
0.15 s of breath before and 0.35 s after that never reach within 40 ms of a word outside the moment; a laugh or
applause that follows the last word stays in for up to 2.5 s (a trailing "So" said into it is cut) and fades out
(`fade_out`). The output is the aspect's size, smaller when the source would be enlarged more than 1.78x (a 9:16
crop of 1080p footage is 1.78x: accepted with `allow_upscale`, qa notes it; 720p renders 720x1280). Captions:
bold-pop at 0.09 of the width in tall frames, kept off the face (`avoid_face`; 0.08 when only that keeps the line
under the chin throughout, instead of a jump above the eyes), clean in wide ones (`--captions`).
`--cards` adds a title card on the first words with the moment's title, and a data callout when the speaker says a
number with a unit (`edit cards suggest` on the clip). The clips render with the EDL renderer, several at once
(cores / 4, at most the clips), each through qa (`--platform`, else the job's); they go to `<job>/clips/` (drafts:
`clips/preview/`) with `clips.json` (moment, source range, EDL, video, length, qa verdict, LUFS, true peak and
findings per clip) and `sheet.jpg` (five frames per clip, qa's colour on the border). Re-running updates an EDL in
place when nobody edited it since it was written (its render cache stays valid); one edited by hand is kept and
the new EDL goes beside it. Videos never overwrite (`--overwrite` to replace them). In the job ledger a clip is
never the job's final: the batch is one history line and one verified line per clip with its qa verdict.

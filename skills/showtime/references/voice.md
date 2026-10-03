# Voice: narration, word timings, pronunciation

Read this when a video needs a voice-over. That covers picking a voice or language (Spanish included), writing narration, sizing a script to a length, fixing how a word is said, timing scenes or captions to the voice, and aligning a recorded take to its script.

Everything runs locally. Kokoro is the default engine. It gives exact word timings and 54 voices across 9 languages. The text never leaves the machine.

## Essentials

- Defaults: `af_heart` (English), `ef_dora` (Spanish), `bf_emma` (British English), `ff_siwis` (French). Never
  swap a voice the user named; otherwise use the default and say which voice you used (§ Choosing a voice)
- Narration: `showtime voice script narration.md -o voice/`, one `## <scene id>` per scene; `--fit 15` lands
  it on 15 s; on "cut about N words", cut them and rerun (§ Script → timeline → scenes)
- Outputs: `vo.wav` (−16 LUFS, the `voice` track in `audio/mix.json`), `timeline.json` (slots, word times),
  `vo.words.json` (for `showtime captions`), `vo.srt`, `lines/NN-id.wav` (§ Script → timeline → scenes)
- The voice sets scene lengths: DOM projects run `showtime retime <project> --from-voice voice/timeline.json`;
  canvas films load `showtime voice cues voice/timeline.json -o voice/cues.js`. Never hand-edit durations;
  trigger a reveal at the `start` of the word that names it (§ Script → timeline → scenes)
- To change a line, edit it and rerun: only that line re-synthesizes; later `start` values move, so reread
  `timeline.json` (§ Script → timeline → scenes)
- Budget about 2.8–3.3 words/s in English at speed 1.0, 2.9 in Spanish, 2.4 for a calm read; leave 10–20 % of
  the video without speech (§ Word budgets)
- One idea per sentence, 8–16 words; end on the payoff word with 0.5–1 s of tail. Directions go in
  `<!-- comments -->` or `> quote` lines, never in the spoken text (§ Writing for the ear)
- Speed: 0.9–0.95 for explainers, 1.0 natural, 1.05–1.15 for hooks; above 1.2 sounds rushed. When a fit leaves
  a line faster than x1.1, cut words rather than accept it (§ Choosing a voice, § Script → timeline → scenes)
- Wrong word: `showtime voice ipa "Word" [--lang es]`, then a `lexicon.json` entry (`ipa` Kokoro only, `say`
  every engine) or inline `[SQL](sequel)` (§ Pronunciation fixes)
- Spanish voices read English names with Spanish rules: add the product name to the lexicon in every Spanish
  video. `--lang es` is Castilian, `--lang es-419` Latin American (§ Pronunciation fixes, § Choosing a voice)
- Supertonic is not reproducible: keep its WAVs and `timeline.json`. You cannot listen: compare candidates
  with `showtime transcribe` round-trips and `voice ipa` (§ Choosing a voice)
- Narration masters to −16 LUFS / −1.5 dBTP; keep it there and let `audio mix` duck the music (§ Mastering)
- Never imitate a real person; say the voice is synthetic where the platform expects it; CC-BY Piper voices
  need their credit line (§ Engines and licensing)
- Synthesize the voice before a long browser render; "Kokoro is not ready": `showtime setup`
  (§ Performance, § Platform notes and troubleshooting)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Commands | 54-66 |
| Choosing a voice | 68-107 |
| Writing for the ear | 109-120 |
| Word budgets | 122-133 |
| Script → timeline → scenes (timing-driven editing) | 135-188 |
| Captions from TTS timings | 190-196 |
| Pronunciation fixes | 198-220 |
| Aligning a recorded voice (or another engine's output) | 222-237 |
| Mastering | 239-255 |
| Engines and licensing | 257-267 |
| Performance (measured on a 6-core Intel i5-8500, CPU only, load ~3) | 269-284 |
| Platform notes and troubleshooting | 286-299 |

## Commands

| Command | What it does |
|---|---|
| `showtime voice list [--lang es] [--json]` | Lists voices with language, gender, quality grade, notes and whether each is installed. |
| `showtime voice say "text" -v af_heart -o vo.wav` | Writes `vo.wav` (48 kHz, −16 LUFS) and `vo.words.json` (start and end time of every word). |
| `showtime voice script narration.md -o voice/` | Writes per-line clips, `vo.wav`, `timeline.json`, `vo.words.json` and `vo.srt`. `--fit 15` lands the whole narration on 15 s. |
| `showtime voice align take.wav -f script.txt -o take.words.json` | Gives word timings for a recording and its known text. |
| `showtime voice master raw.wav -o vo.wav [--preset podcast]` | Runs high-pass, de-ess and gentle compression, then two-pass loudness normalization. |
| `showtime voice ipa "Kubernetes" [--lang es]` | Shows the phonemes espeak-ng produces, so you can write a pronunciation fix. |
| `showtime voice bench [-v a,b]` | Measures speed and speaking rate on this machine. |

Every command has `--help` with examples, and `--json` for machine output. A `say` or script line whose text, voice, speed and lexicon are unchanged comes back from the cache instantly. Editing one line re-synthesizes only that line.

## Choosing a voice

The defaults are `af_heart` for English, `ef_dora` for Spanish, `bf_emma` for British English and `ff_siwis` for French. Grades are the model author's published ratings (A is best). Words per second (w/s) was measured here at speed 1.0 on one paragraph and includes normal sentence pauses.

| Tone / use | Voice | Grade | w/s | Notes |
|---|---|---|---|---|
| Warm, natural, all-round (default) | `af_heart` | A | 3.06 | Safest choice for launches and explainers |
| Bright, energetic (promo, social) | `af_bella` | A- | 2.96 | |
| Calm, intimate, slow | `af_nicole` | B- | 1.96 | Soft and close to the mic; for calm pieces, not fast cuts. Plan about 1.8 w/s of script for a nicole explainer (a 70 s fit took 124 words) |
| Clear and neutral (docs, UI walkthroughs) | `af_sarah` | C+ | 3.15 | |
| Steady male, trustworthy (default male) | `am_michael` | C+ | 2.80 | |
| Deep, confident (trailers, big reveals) | `am_fenrir` | C+ | 3.07 | Pair with `--style trailer` |
| Lively male (upbeat promos) | `am_puck` | C+ | 3.10 | |
| British, polished (tutorials, docs) | `bf_emma` | B- | 3.34 | Fast: consider speed 0.92 |
| British, authoritative (documentary) | `bm_george` | C | 2.84 | |
| British storyteller | `bm_fable` | C | 3.43 | |
| **Spanish**, female (default) | `ef_dora` | – | 2.90 | Exact timings; use the lexicon for English brand names |
| **Spanish**, male | `em_alex` | – | 2.87 | |
| **Spanish**, most natural (optional) | `supertonic:F1` / `supertonic:M1` + `--lang es` | – | 2.54 / 2.51 | Needs `showtime setup --with supertonic`; timings are aligned (about 20–30 ms) |

**Which Spanish voice:** `ef_dora` is the default (installed, exact word timings, the localize workflow
uses it); Supertonic sounds more natural when it is installed. **Accent:** `--lang es` gives Castilian
pronunciation for Kokoro and Piper voices ("cero" with θ); `--lang es-419` gives Latin American seseo
(also in `voice ipa`, front matter `lang: es-419`, or a line's `lang`). Supertonic uses its own model and
ignores the region code. Supertonic is not reproducible: synthesizing the same line again moves its
timing by 30-260 ms (Kokoro stays within ~50 ms), so a project whose cues come from its timeline must
keep its WAVs and `timeline.json` (or re-run `voice cues`/`retime --from-voice` after a rebuild). You cannot listen: compare
candidates with `showtime transcribe` round-trips and `voice ipa`, and state the choice to the user.

| Use | Voice | Grade | Words/s | Notes |
|---|---|---|---|---|
| Spanish or English quick drafts | `piper:es_MX-claude-high`, `piper:en_US-ljspeech-high` | – | 2.66 / 3.21 | Fast but robotic; downloads 65–115 MB on first use |
| French / Italian / Portuguese (BR) / Hindi | `ff_siwis` / `if_sara`, `im_nicola` / `pf_dora`, `pm_alex` / `hf_alpha`, `hm_omega` | B- to C | | |
| Japanese / Mandarin | `jf_alpha` / `zf_xiaobei` | C+ / D | | Phonemes come from espeak-ng, so the accent is approximate. Avoid these for published work. |

- **Blends:** `-v af_heart:60+am_michael:40` mixes voice styles (the weights are normalized). Use a blend to make a brand's own voice.
- **Styles:** `--style` sets speed and pause lengths together. The styles are `neutral`, `calm` (0.92x, long pauses), `warm`, `upbeat` (1.08x), `energetic` (1.15x), `tutorial`, `documentary` and `trailer` (0.9x, 0.6 s sentence pauses).
- **Speed:** 0.9–0.95 suits explainers and anything the viewer must follow on screen. 1.0 is natural. 1.05–1.15 suits hooks and promos. Above 1.2 sounds rushed. Kokoro accepts 0.5–2.0.
- **Explicit choices:** a voice the user names is never swapped silently. An unknown voice is an error that lists close matches.
- **Asking the user:** ask about gender or tone only when it changes the video. Otherwise use the default and say which voice you used.

## Writing for the ear

- **One idea per sentence, 8–16 words.** Long sentences lose the listener and make captions wrap badly.
- **Write numbers the way they should be said** when it matters: "twenty twenty-six", "three and a half". Common forms are handled already. "3.5" becomes "3 point 5". "in 2026" becomes "twenty twenty-six". "Dr." becomes "doctor". "e.g." becomes "for example". "showtime.dev" becomes "showtime dot dev". "v2.0" becomes "version 2 point 0". A bare year after "the" is not covered ("the 1973 Nobel" is read "nineteen hundred seventy three"): write it inline, `the [1973](nineteen seventy-three) Nobel`.
- **Spanish (and French, Portuguese, Italian, German) numbers** are read as written in those languages: "60 000" and "60.000" are one number ("sesenta mil", not digit by digit), "13,7" is "trece coma siete". The Hawaiian ʻokina (U+02BB, or ‘ between letters) is silent instead of spelled out ("Hawaiʻi").
- **Math and sequences by ear.** A listener hears no punctuation: "One. One plus three is four." is heard as "one one plus three". Never end a sentence and start the next on the same word; say a running sum as steps ("Start with one. Add three, and you have four. Add five: nine.") and symbols as words ("n squared", "two n minus one"). `voice script` warns when a line repeats a word across a sentence break.
- **Front-load the subject:** "Showtime renders on your machine", not "On your machine, rendering is done by Showtime".
- **Name what is on screen at the moment it appears.** The voice sets the timing, so a reveal happens when its word is spoken, and not before.
- **Use contractions and plain words.** "It's", "you'll", "use". Avoid "utilize". Read the script aloud once in your head.
- **Punctuation is timing.** A period gives about a 0.3 s pause (0.45 s with `calm`). A comma gives about 0.12 s. `[pause 0.6]` gives an exact silence. Use a dash for a quick turn.
- **Never put directions in the spoken text.** Directions go in `<!-- comments -->` or `> quote` lines in a Markdown script, and are never spoken.
- **End on the payoff word:** "...rendered entirely on your own **machine**." Leave 0.5–1 s of tail before the end card.

## Word budgets

At speed 1.0 the Kokoro English voices speak about **2.8–3.3 words per second** (170–200 wpm) including sentence pauses. Spanish runs about **2.9 w/s**. A calm read (speed 0.92 with longer pauses) drops to about **2.4 w/s**. Plan with these numbers, then trust the real durations in `timeline.json`.

| Spoken length | Brisk (1.0, ~3.0 w/s) | Calm (~2.4 w/s) |
|---|---|---|
| 6 s hook | 15–18 words | 12–14 words |
| 15 s | 40–45 words | 32–36 words |
| 30 s | 80–90 words | 65–72 words |
| 60 s | 160–180 words | 130–145 words |

Leave 10–20 % of a video's length without speech: the open, pauses before reveals, and the end card. Run `showtime voice bench -v <voice>` to measure a specific voice on this machine.

## Script → timeline → scenes (timing-driven editing)

The voice decides how long each scene lasts. Write the script as one line per scene, build it, then set each scene's duration from its slot.

```markdown
---
voice: af_heart
gap: 0.4            # default silence after each line (s)
tail: 0.8           # silence after the last line
---
## hook
Meet Showtime. [pause 0.3] The video studio that lives in your terminal.

> Director's note: warm, not salesy (quotes and <!-- comments --> are never spoken)

## demo {voice=am_michael speed=1.05 pause_after=0.7}
Point it at any project, and get a polished launch film in minutes.

## outro {style=calm fit=3.2}
Rendered entirely on your own machine.
```

Front matter (and the top level of a JSON script) takes `voice`, `speed`, `style`, `lang`, `engine`,
`gap`, `lead_in`, `tail`, `lufs`, `lexicon` and `fit`; each line can override `voice`, `speed`, `style`,
`lang`, `engine`, `pause_after`, `fit` and `at`.

JSON works the same way: `{"voice": ..., "gap": ..., "lines": [{"id", "text", "voice", "speed", "style", "lang", "engine", "pause_after", "fit", "at"}]}`. A bare list of strings also works. Without headings, each paragraph of a Markdown or text file is one line.

- `fit: 3.2` adjusts that line's speed (within 0.8–1.25x of its own speed) so it lasts about 3.2 s. Use it when a scene has a fixed length, such as a beat-locked cut.
- `at: 12.0` pins a line to start at 12 s, for example on a music drop. Later lines follow on from it. If the pinned line would overlap the one before, you get a warning.

**Fitting the whole script to a length:** `showtime voice script narration.md -o voice --fit 15` (or a top-level `"fit": 15` in the JSON, `fit: 15` in the front matter). It works in three steps and stops as soon as the narration is on target (within 1 %, at least 0.1 s; then a small overshoot trims the pauses and a short result is padded, so `vo.wav` lasts the target):

1. Every line without its own `fit` changes speed together, within 0.85–1.15x. A new speed means every line re-synthesizes (up to four tries; it says so first), so a 13-line script can take a few minutes. Each try's lines are cached.
2. Still long: the pauses between lines shrink (never below 0.2 s) and so does the tail (never below 0.3 s).
3. Still long: it prints `still Xs over ... cut about N words (of M; the voice speaks W words/s)`. Cut them from the script and run it again; nothing is dropped for you.

When the fit leaves any line faster than x1.1 (its own speed times the fit factor), it warns that the voice sounds rushed and says how many words to cut to fit at x1.0: explainers and documentaries read best at x0.9-1.0, so cut words rather than accept x1.15. A script that ends short is slowed (down to 0.85x), then padded with silence at the end so `vo.wav` lasts exactly the target; the output estimates how many words would fill the gap. It prints `fit T: before -> result (speed xF, pauses -Xs, tail +Ys of silence)`, and `timeline.json` gets a `fit` block (`target`, `before`, `result`, `speed_factor`, `pauses_trimmed`, `tail_padded`, `cut_words`, `add_words`, `wps`, `tolerance`); line `pause_after` values and `tail` show the trimmed times.

`showtime voice script narration.md` writes `voice/` next to the script:

| File | Contents |
|---|---|
| `vo.wav` | All lines placed with their pauses, mastered to −16 LUFS, 48 kHz. Use it as the `voice` track in `audio/mix.json`. |
| `timeline.json` | `duration`, `loudness` and `lines[]`. Each line has `id`, `text`, `voice`, `start`, `end`, `speech_start`, `speech_end`, `slot {start, end, duration}`, `pause_after`, `file`, `timing`, `wps` and `words[]` (absolute seconds). A flat `words[]` has a `line` id on each word. |
| `vo.words.json` | Every word in the shared transcript format (`text`, `start`, `end`, `type: "word"`), ready for `showtime captions`. |
| `vo.srt` | Captions of at most 32 characters per line (fits vertical video too), balanced, no one-word orphans, readable at 20 characters/s or slower. |
| `lines/NN-id.wav` | Each line alone, plus `.words.json` with line-relative times. Use these when scenes are rendered separately. |

**Scene durations:** make each scene `lines[i].slot.duration` long. A slot runs from the line's start to the next line's start, so it includes the pause. The last slot includes the tail. In a DOM project, `showtime retime <project> --from-voice voice/timeline.json` does it all at once: name each line after its scene (`## demo` narrates `<section id="demo">`), and it sets the scene lengths (0.3 s of picture, `--pad`, plus the slots), places each line as its own voice track, ducks the music and moves sections, effects, the poster and the caption words (`render.md`). Canvas films load `showtime voice cues voice/timeline.json -o voice/cues.js` (a `VO` table of line and word times) and read their cue times from it, so re-running `voice script` + `voice cues` re-times the film.

**Reveal cues:** trigger an element at the `start` of the word that names it. Take it from `timeline.json` words (add the line's scene offset when scenes are rendered separately).

**Changing one line:** edit it and run the script again. Only that line is synthesized again. Later `start` values move, so reread `timeline.json` and never hand-edit durations.

## Captions from TTS timings

Kokoro's word times come straight from the model's phoneme durations. The waveform runs about 50 ms behind that duration grid, so the times are shifted earlier by that amount (measured over 6 voices and 3 speeds). Each word start then snaps to a clear onset in the audio when there is one within 80 ms, and silence is trimmed from word ends. Measured on test sentences, starts land within about 10 ms of clear acoustic onsets, and within 15–40 ms of an independent CTC aligner.

- For styled or karaoke captions, feed `vo.words.json` to `showtime captions` (footage module). You can also load `timeline.json` in the page and highlight `words[i]` while `t` is between `start` and `end`.
- `vo.srt` is a quick fallback for players and platforms.
- The caption text is the script's own spelling ("2026", "Showtime,"), even where the speech says "twenty twenty-six".

## Pronunciation fixes

1. Run `showtime voice ipa "Kubernetes kubectl" [--lang es]` to see what espeak-ng says for each word. It reads the `lexicon.json` in the current folder, or its one sub-folder with a `lexicon.json`, or `--project <dir>` (`voice script` has no `--project`: it reads the `lexicon.json` next to its script or one folder up, plus any `--lexicon FILE`), shows which lexicon it used, and its `phrase:` line is what the voice reads with the lexicon and inline fixes applied.
2. Add an entry to `lexicon.json` next to the script or project, or under `"pronunciations"` in `brand.json`:

   ```json
   {
     "Showtime": "ʃˈoʊtaɪm",
     "kubectl": {"ipa": "kjˈuːb kəntɹˈoʊl"},
     "SQL": {"say": "sequel"},
     "GIF": {"ipa": {"en": "ɡˈɪf", "es": "ɡˈif"}},
     "CLI": {"ipa": {"en": "sˌiːˌɛlˈaɪ"}, "case": true}
   }
   ```

   - `ipa` uses the symbols espeak-ng prints: `ˈ` primary stress before the stressed syllable, `ː` long vowel. It works with Kokoro only.
   - `say` is a respelling that works with every engine (Supertonic and Piper read text, not phonemes).
   - Values can be per language (`"en"`, `"es"`, `"*"` for any). Matching ignores case unless `"case": true`. Possessives ("Showtime's") reuse the entry.
3. For a one-off, fix the word inline: `[Showtime](/ʃˈoʊtaɪm/)` for IPA or `[SQL](sequel)` for a respelling.

The lexicons merge in this order, and later ones win: the built-in list (`lib/st/voice/lexicon.json`, tech words espeak gets wrong such as CLI, JSON, kubectl, Redis, and English brand names for Spanish voices such as GitHub, YouTube, Claude), then `$SHOWTIME_LEXICON`, then the project's `lexicon.json` or `brand.json`, then `--lexicon FILE`.

For Spanish voices, English brand names need a lexicon entry; otherwise espeak reads them with Spanish rules ("Showtime" comes out as "show-TEE-meh"). The built-in list covers common ones. Add the product name for every Spanish video.

## Aligning a recorded voice (or another engine's output)

`showtime voice align take.wav -f script.txt [--lang es] [--method auto|ctc|tts|whisper|even]`

The output keeps the script's exact words and punctuation. The table below compares each method's word starts with Kokoro's exact times on Kokoro speech.

| Method | Languages | Start error (mean) | Cost |
|---|---|---|---|
| `ctc`: a wav2vec2 letter model (95 MB, downloaded on first use) plus forced alignment | English | 5–40 ms (typical ~20) | ~1–3 s per minute of audio |
| `tts`: the text is spoken with Kokoro, which has exact times, then warped onto the audio (MFCC + DTW) | every Kokoro language | 20–35 ms with a different voice as reference | one Kokoro synthesis |
| `whisper`: faster-whisper word times mapped onto the script | 99 | 100–125 ms | slow (large model for non-English) |
| `even`: words spread over the voiced parts | any | ~110–140 ms | instant |

`auto` tries ctc, then tts, then whisper, then even for English. For other languages it tries tts, then whisper, then even. Every method finishes by snapping word edges to the audio energy. `--no-snap` turns that off.

For real human takes the numbers are larger, because the speaker's pace and pauses differ from the reference. Check the result against the energy on your own footage.

## Mastering

`voice say` and `voice script` master by default (−16 LUFS, −1.5 dBTP, mono 48 kHz, 24-bit). `--raw` or `--no-master` skips it.

The chain is: high-pass at 70 Hz, de-esser, 3:1 compressor, then two-pass linear loudnorm. If a peaky or very short clip cannot reach the target, gain is added under a limiter. The chain adds no delay, so word times stay valid.

Presets for `voice master`:

| Preset | Target |
|---|---|
| `voice` | −16 |
| `podcast` | −16, stronger compression |
| `youtube` | −14 |
| `broadcast` | −23 |
| `gentle` | no compression |

The final video mix is normalized again (−14 by default), so keep narration at −16 and let `audio mix` duck the music under it.

## Engines and licensing

| Engine | Weights license | Notes |
|---|---|---|
| Kokoro-82M v1.0 (default) | Apache-2.0 | kokoro-onnx (MIT). Needs espeak-ng (GPL-3.0), which is loaded at run time from the installed wheel or the system, never copied into this repo. |
| Supertonic 3 (optional) | OpenRAIL-M: commercial use is allowed with use-based restrictions (no impersonation, deception or harm) | 31 languages. Code MIT. Upstream development has stopped, so the version is pinned. |
| Piper voices (optional, sherpa-onnx, Apache-2.0) | per voice | Only commercially usable voices are listed. Public domain: `en_US-ljspeech-high`, `en_US-john/kristin/norman-medium`, `en_GB-cori-high`. Apache-2.0: `es_MX-claude-high`. CC0: `es_ES-davefx-medium`. Unlicense: `es_MX-ald-medium`. **CC-BY, credit required:** `en_US-libritts_r-medium`, `en_GB-alba-medium`, `es_ES-sharvard-medium`. The credit line is in `voice list --json` → `attribution`; put it in the video's credits. |
| English aligner | Apache-2.0 | wav2vec2-base-960h, ONNX export |

- **No cloning:** no engine here clones a real person's voice. Do not imitate a real person.
- **Disclosure:** say that the voice is synthetic where the platform or audience expects it. Platforms increasingly ask for an "AI voice" label.

## Performance (measured on a 6-core Intel i5-8500, CPU only, load ~3)

| Step | Speed | Notes |
|---|---|---|
| Kokoro | RTF 0.34–0.42 | A 60 s narration takes about 25 s. |
| Supertonic | engine RTF 0.19–0.20 | Plus alignment. |
| Piper `es_MX-claude-high` | engine RTF 0.06 | |
| Model load | Kokoro about 1 s, aligner 0.2 s | |
| First espeak self-test | a few seconds, once | Cached in `~/.showtime/cache/voice/espeak.json`. |

RTF means synthesis time divided by audio length; below 1 is faster than real time. Apple Silicon and recent x86 CPUs are faster.

Tips:

- Synthesize the voice before starting a long browser render: both use every core.
- `SHOWTIME_THREADS=N` limits ONNX threads.

## Platform notes and troubleshooting

- **espeak-ng.** showtime uses a system espeak-ng when one is found (Homebrew or MacPorts on macOS, `apt install espeak-ng` on Linux, the `.msi` on Windows). Otherwise it uses the copy inside the `espeakng-loader` wheel, which exists for macOS arm64/x64, Linux x64/arm64 and Windows x64/arm64. Each candidate is tested once in a child process, because a broken espeak kills its process.
  - A data path over ~140 bytes, or a non-ASCII path on Windows, is copied once to a short folder: `<home>/cache`, `%ProgramData%` on Windows, `$TMPDIR`, then `/tmp/showtime-espeak-<uid>` (your own 0700 folder) on macOS and Linux. This avoids a known espeak-ng path-buffer bug. `showtime setup` runs the same self-test as `showtime doctor`, so it fails when no candidate works.
  - To force a choice, set `SHOWTIME_ESPEAK=bundled|system`, or give exact paths with `SHOWTIME_ESPEAK_LIB` and `SHOWTIME_ESPEAK_DATA`.

| Symptom | Fix |
|---|---|
| "Kokoro is not ready" | Run `showtime setup` (the minimal tier includes Kokoro). |
| A word is read wrong | Run `voice ipa`, then add a lexicon entry. |
| Spanish reads an English name oddly | Add a lexicon entry with an `"es"` or `"*"` value. |
| Timings are "estimated" on a few words | The word had no pronounceable letters (a symbol, an emoji) and was interpolated. Rewrite it as words. |
| Offline machine | Set `SHOWTIME_OFFLINE=1`. Alignment then skips `ctc` and uses `tts`; Piper voices must already be downloaded. |
| Cache | Stored in `~/.showtime/cache/voice/tts/` and capped at 1 GB (`SHOWTIME_TTS_CACHE_MB`); the least recently used lines go first. `showtime voice cache` shows its size, `--clear` empties it. `SHOWTIME_NO_CACHE=1` or `--no-cache` bypasses it. |

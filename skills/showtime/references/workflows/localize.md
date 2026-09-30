# Workflow: localize a video (re-voice and re-caption in another language)

Read this when the user wants the same video in another language: Spanish narration for an English
explainer, subtitles in three languages, a dubbed version of a talking-head clip ("make a Spanish
version", "add Portuguese subtitles"). How much can change depends on what the video was made from:

| Source | What you can deliver |
|---|---|
| a showtime project (HTML or canvas) with a voice script | a full version: translated on-screen text, a new voice, captions, re-timed scenes, re-rendered |
| a finished file with narration you recorded or generated separately | a new voice track mixed over the picture, translated captions |
| real footage of a person speaking | translated subtitles (always), or a voice-over dub over the ducked original (no lip sync, no voice cloning) |

## Essentials

- Translate meaning, lines within about 10 % of the original; numbers, units, claims, product names, commands
  and code stay as they are; say the translation is machine-made by you and offer a review
  (§ Translation rules)
- Every English brand name a non-English voice says needs a lexicon entry: check with
  `showtime voice ipa "<line>" --lang es` before synthesizing (§ Translation rules)
- `showtime voice script <job>/project/narration.<lang>.md -o <job>/project/voice --voice ef_dora`, then
  `showtime retime <job>/project --from-voice <job>/project/voice/timeline.json` (§ Steps (showtime project))
- Allow 20-30 % longer on-screen text; fonts must cover the language's characters. A dub is a voice-over, not
  lip-synced, never a cloned voice: say so (§ Translation rules, § Steps (finished file or footage))

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inputs | 36-41 |
| Defaults | 43-50 |
| Translation rules | 52-62 |
| Steps (showtime project) | 64-82 |
| Steps (finished file or footage) | 84-97 |
| Pitfalls | 99-105 |
| Read next | 107-110 |

## Inputs

- The source (project, file or footage) and its script or transcript.
- The target language(s) and region (Spain or Latin American Spanish, Brazilian Portuguese).
- Helpful: a glossary of terms that must stay in English (product names, commands), a brand kit with
  pronunciations.

## Defaults

Translate meaning, not words, keeping line lengths within about 10 % of the original so timing
survives; product names, commands and code stay as they are; Spanish voice `ef_dora` (female) or
`em_alex` (male), other languages via `showtime voice list --lang <code>` (Supertonic covers 31
languages when installed); captions in the target language as a sidecar and, for social, burned in.
State the region/variant and the pronunciation of names as assumptions; ask only when the request
leaves the variant genuinely open (Brazilian vs European Portuguese for a named market, say).

## Translation rules

- You translate; the user or a native speaker approves. Say that the translation is machine-made by you
  and offer a review round before the final render for anything published.
- Keep numbers, units and claims identical to the source; never add or soften claims.
- Every English brand name a non-English voice says needs a lexicon entry (`voice.md` "Pronunciation
  fixes"); otherwise it is read with the target language's rules. Check with
  `showtime voice ipa "<line>" --lang es` before synthesizing.
- On-screen text: allow for 20-30 % longer strings (Spanish, German, French); check for overflow.
- Fonts must cover the language's characters (accents, ñ, ç). A missing glyph falls back to a system
  font, which `showtime check` flags; `showtime captions` reports characters its font lacks. Add subsets with `showtime assets font "<family>" --subsets latin,latin-ext`.

## Steps (showtime project)

1. **Job.** `showtime job init <name>-<lang> --goal "..."`; copy the project to `<job>/project` so the
   original stays untouched.
2. **Translate** the voice script (`narration.<lang>.md`, same line ids) and every on-screen string
   (HTML text, chart titles, `scenes.js` strings). List the glossary terms you kept in English.
3. **Voice.** `showtime voice script <job>/project/narration.<lang>.md -o <job>/project/voice --voice ef_dora`
   (the line's own `lang` comes from the voice). Re-time the scenes from the new slots: a DOM project
   with `showtime retime <job>/project --from-voice <job>/project/voice/timeline.json` (scenes, voice
   tracks, music, effects and caption words move together; `render.md`); a canvas film whose cues read
   `VO` (`explainer.md` step 5) by running `showtime voice cues <job>/project/voice/timeline.json -o
   <job>/project/voice/cues.js` again (search the cue table for times typed as numbers and move them
   to `VO` first). Add `--fit <original length>` to
   `voice script` when the translation must keep the original's length.
4. **Captions.** Point the caption layer at the new `voice/vo.words.json`, or make a sidecar with
   `showtime captions <job>/project/voice/vo.words.json --style clean --size <WxH> -o <job>/caps.ass --srt <job>/final.srt`.
5. **Check, first look, final, verify** as in the pipeline: `showtime render <job>/project --job <job>`,
   then `showtime qa <job>` (the latest final and the job's captions).
   Compare the contact sheet with the original's: same beats, no overflow, no missing glyphs.

## Steps (finished file or footage)

1. **Transcript.** `showtime transcribe <video>` (or use the original script and `showtime voice align
   <video> -f script.txt` to get word times for a known text).
2. **Subtitles.** Translate cue by cue, keeping each cue's start and end (write an `.srt` from the
   transcript's phrases, `showtime pack` shows them grouped), then restyle and check it:
   `showtime captions <job>/subs.<lang>.srt --style clean --size <WxH> -o <job>/subs.<lang>.ass`.
   Burn for social: `showtime captions <job>/subs.<lang>.srt --style bold-pop --burn <video> -o <job>/final.<lang>.mp4`.
3. **Dub (optional).** Write one translated line per original phrase with `at` = the phrase start and
   `fit` = its length; `showtime voice script` it; mix it over the video as in `voiceover-only.md`
   step 5, with the original at `"volume_db": -14` (or muted where only speech is heard). Tell the user
   plainly: this is a voice-over, not a lip-synced dub, and the original speaker's voice is not cloned.
4. **Verify.** `showtime qa <job>/final.<lang>.mp4 --captions <job>/subs.<lang>.srt`; look at a few
   frames with long lines (`showtime footage view <job>/final.<lang>.mp4 --from <a> --to <b>`).

## Pitfalls

- Re-using the original scene timings with a longer translation: the voice runs over the cuts.
- English names read with Spanish rules ("show-TEE-meh"): add lexicon entries before synthesizing.
- Captions over 42 characters per line (32 on vertical) because translations grow: qa warns; re-split.
- Translating code, commands or UI labels that the viewer will see in English in the product.
- Presenting a machine translation as reviewed: say who has checked it (nobody yet, until the user does).

## Read next

`references/voice.md`, `references/captions.md`, `references/typography.md`,
`references/workflows/voiceover-only.md`, `references/workflows/explainer.md`, `references/qa.md`.

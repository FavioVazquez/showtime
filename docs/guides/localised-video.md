# Make a video in another language

You have a video and want it in Spanish, French or another language: a new voice, every on-screen word
translated, captions in that language, and scenes that still land on their lines. How much can change depends on
what the video was made from.

| You have | You get |
|---|---|
| a showtime project with a voice script | a full version: on-screen text translated, a new voice, captions, scenes re-timed, rendered again |
| a finished file with a separate narration | a new voice track over the picture, translated captions |
| footage of a person speaking | translated subtitles, or a voice-over over the ducked original (no lip sync, no voice cloning) |

## Say this

> "Make the Spanish version of the heat pump explainer, Spain Spanish."

Say the region when it matters (Spain or Latin American Spanish, Brazilian or European Portuguese), and list
terms that must stay in English, such as your product name.

## What happens

For a showtime project:

1. `showtime job init heat-pump-es` and a copy of the project into `<job>/project`, so the original stays as is.
2. Your agent translates the voice script into `narration.es.md` (same line ids) and every on-screen string. It
   keeps numbers, units, claims, product names, commands and code as they are, and lines within about 10 % of
   the original length.
3. `showtime voice ipa "<line>" --lang es` checks how the voice will say each English name; names that would be
   read with Spanish rules get a lexicon entry first.
4. `showtime voice script <job>/project/narration.es.md -o <job>/project/voice --voice ef_dora` makes the new
   voice with word timings (`showtime voice list --lang <code>` lists voices for other languages).
5. `showtime retime <job>/project --from-voice <job>/project/voice/timeline.json` moves the scenes, music,
   effects and caption words to the new lines.
6. `showtime check`, a look at the frames with the longest strings, then `showtime render <job>/project --job <job>`
   and `showtime qa <job>`.

For footage, `showtime transcribe`, translated subtitles cue by cue, then `showtime captions` to style or burn
them (`--burn`).

## What you get

- `final.mp4` in the new language, with captions (`.srt`) beside it.
- `narration.es.md` and the translated strings in the project, so a native speaker can review them.
- A list of the terms kept in English.

## How long it takes

Measured for [example 03](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/03-explainer-heat-pump-es) (a 50 s Spanish explainer) on a 6-core
Intel Mac shared with three other example jobs:

| Step | Time |
|---|---|
| Audition: 4 voices, one passage each | 7-19 s each |
| `voice script`, 8 lines | 56 s |
| `check` | 20-23 s |
| One final render (lossless capture, slow encode) | 2 min 55 s to 4 min 25 s |
| `qa` | 13-16 s |

About 20 minutes from the request to the first version, with the audition and two renders. In
[example 13](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/13-wikipedia-waggle-dance), the French `voice script` (6 lines) took 63 s and the
French final render 2 min 15 s, on a 6-core Intel Mac.

## Phrases that change it

- "Keep the original length" adds `--fit <seconds>` to `voice script`.
- "A male voice" picks another voice (`em_alex` for Spanish).
- "Subtitles only" skips the new voice.
- "Burned-in captions for Reels" burns them in the bold style.
- "And in French" adds a second language the same way.

## Limits

- Your agent translates. Say who has checked it: nobody, until you or a native speaker does. For anything
  published, ask for a review round before the final render.
- Translations run 20-30 % longer on screen in Spanish, German or French; `showtime check` flags text that no
  longer fits.
- A dub of a person speaking is a voice-over, not lip-synced, and never a copy of their voice.
- Fonts must cover the language's characters; `showtime check` flags a missing glyph.

## The example

[Example 03](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/03-explainer-heat-pump-es) (the heat pump explainer in Spanish) and
[example 13](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/13-wikipedia-waggle-dance) (English and French).
[Example 26](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/26-nobel-chemistry-en-es) is a 2:30 explainer and its Spanish version: every string,
a Spanish voice and captions, the same numbers. The full workflow is [localize.md](../../skills/showtime/references/workflows/localize.md).

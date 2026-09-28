# Crew brief: voice director

Read this when you were dispatched as the voice director of a showtime job (after
`references/crew/rules.md`).

**Your job: the narration as heard**: casting, pronunciation, pacing, the rendered voice-over and,
for localized versions, the translated read. Reference: `references/voice.md` (all of it) and, for
other languages, `references/workflows/localize.md`.

## Task shapes

### A. Casting (studio sound phase)

`showtime voice list` for the language, then three candidates that suit the tone. Each reads the
picked hook: `showtime voice say "<hook>" -v <id> -o <own dir>/casting/<id>.wav`. Write `casting.md`:
per voice the id, why it fits, what it risks (too bright, too slow), and a recommendation. The
director masters the samples onto the board.

### B. Voice-over (build)

You own the project's `voice/` folder for this phase.
1. Pronunciation first: resolve the brand kit's `pronunciation_candidates` and any product, people or
   code names in the script. `showtime voice ipa "<word>"` shows what the engine will say; write fixes
   as inline hints or lexicon entries (`voice.md`, Pronunciation fixes) and keep them in
   `lexicon.json` in your folder.
2. Render: `showtime voice script <script> -o <project>/voice/`, with `--fit <seconds>` when the
   length is fixed. Speed and `pause_after` per section, as the script format allows.
3. Listen by numbers: read `timeline.json` (line lengths against the storyboard slots) and
   `vo.words.json` (no swallowed words, no long gaps). `showtime voice master` only for recorded
   voices; TTS output is already at level.

Done when: every line exists, every name is pronounced as the brand says (checked with `voice ipa`),
the total length matches the target within half a second (or the gap is reported), and
`timeline.json` is in `voice/`.

### C. Localization

Per language: translate the script (keep claim ids, keep on-screen numbers exact), pick a voice for
that language, render with `--fit` to the same slots. Translations run 15 to 30 % longer: shorten the
wording before speeding the voice past about 1.1. Write each language to `<own dir>/<lang>/` (script,
`voice/`, captions from the voice timings). Mark every machine translation `needs native review` in
your result; never present it as reviewed.

## Never

- Changing the script's meaning or facts: send wording problems back as notes.
- Editing `audio/`, `index.html` or `showtime.json`. The director retimes the scenes from your
  `timeline.json`.

# Crew brief: scriptwriter

Read this when you were dispatched as the scriptwriter of a showtime job (after
`references/crew/rules.md`).

**Your job: the words, and the proof behind them.** Everything the viewer reads or hears, every line
traceable to a source. References: `references/story.md` (sections 1, 3, 5, 6), `references/pacing.md`
(sections 1 and 6), `references/voice.md` (Writing for the ear, Word budgets, the script format).

## Task shapes

### A. Facts and hooks (pitch round, before a concept is picked)

1. Read the sources `TASK.md` lists: README, docs, changelog, site capture text, footage transcripts.
2. `facts.md`: what the source actually says, one fact per line, each with `file:line` or a URL. Split
   into "can state" (explicit in the source) and "cannot state" (implied, marketing guesses, numbers
   without a table behind them).
3. `claims.json`: every fact a video might use, as
   `{"id": "K1", "text": "...", "source": "README.md:14", "status": "sourced"}`. Status is `sourced`,
   `needs-check` (source is old or ambiguous) or `illustrative` (sample data, to be labelled).
4. `hooks.md`: 5 to 8 openings of different types (`story.md` section 3), each at most 12 words, each
   tagged with the claim ids it relies on.

Write each `file:line` relative to the source folder `TASK.md` names (say which at the top of
`facts.md`), so the researcher can open it. Hooks are raw material: the director may swap one into a
concept card or offer a few as an opening-line question, so each must stand alone without a concept.
Concept-agnostic: never pick the concept; the creative director and the user do that. Skim large
source files with a search (`grep` for the UI strings you need), never read them whole.

### B. Script (after the concept is picked)

1. Inputs: the picked concept, the storyboard rows if they exist, the brand tone and pronunciations,
   `claims.json`.
2. `script.md` in the `voice.md` script format, one section per scene named with the scene id. Word
   budgets from `voice.md` (a brisk 15 s holds 40 to 45 words); leave 10 to 20 % of the runtime
   without speech (the open, pauses before reveals, the end card). Spell out what a voice must say
   ("v2.3" is "version two point three"); the screen can show the exact figure.
3. `onscreen.json`: per scene the on-screen lines with character counts and the minimum hold from
   `pacing.md` section 1. A line that cannot be read in its scene's time gets shorter, never smaller.
4. The call to action and a draft of the share text (`references/platforms.md`), in `script.md`.
5. Update `claims.json`: every factual line in the script or on screen points to a claim id with a
   scene id. No source, no line.
6. Optional, only when `TASK.md` lists it: a fit check,
   `showtime voice script <own dir>/script.md --fit <seconds> -o <own dir>/fit/`, and report the real
   line lengths from `fit/timeline.json` (this is TTS, medium CPU).

Done when: every line fits its budget, every factual line has a claim with a source, and the script
reads aloud cleanly (read it once, out loud in your head, and fix the stumbles).

## Voice

Plain, concrete, specific to this product. No hype words (`story.md` section 5 lists them), no
superlatives the source does not state, no rhetorical questions as filler. Narration as discrete cues,
because each cue becomes a reveal.

## Never

- A number, user count, benchmark, quote or customer the source does not state.
- Copy that needs more reading time than its scene has.
- Editing the project's `voice/` folder: the director copies your script in.

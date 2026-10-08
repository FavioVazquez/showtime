# Crew brief: sound designer

Read this when you were dispatched as the sound designer of a showtime job (after
`references/crew/rules.md`).

**Your job: everything the viewer hears except the voice**: the music bed, the effects, the sound
logo, the balance against the voice, and a mix at the target loudness. References:
`references/audio.md`, `references/music.md`, `references/sound-design.md`.

## Task shapes

### A. Sound board (studio)

Three beds, M1 to M3, of equal length (8 to 12 s), each a different style or tempo band, each paired
with the look it suits. Pick produced tracks with `showtime audio music search --for <use> --dur <d>`
(launch, trailer, story: the default), compose with `showtime audio compose --style <s> --dur <d> ...`
(list styles with `showtime audio styles`) or search the library with `showtime audio lib search ...` using the
license filter from `TASK.md`. Write them as WAV into `<own dir>/beds/` and describe each in
`sound.md` (style, BPM, key, the look it pairs with, license and credit line if any). Recommend one.
The director masters them onto the board.

### B. Build (after lock)

You own the project's `audio/` folder for this phase; nobody else writes there.
1. Read the frozen cue table from `TASK.md` (scene starts, hit times, VO line times from
   `voice/timeline.json`).
2. Bed: a catalog track (`"catalog": "<id>", "fit": true`; credited automatically), a composed bed to the
   exact length with sections on the scene boundaries, or a library track fitted with `showtime audio fit ...`.
   Library tracks: CC0 preferred; CC-BY only with its credit line.
3. Effects: one per cue that earns it, not one per cut. `showtime audio sfx <type> ...` prints the hit
   offset; place each with `"align": "hit"` so the transient lands on the frame.
4. Sound logo for the end card when the storyboard asks: 1 to 2 s, in the bed's key.
5. `audio/mix.json` (`references/audio.md` section 5): the voice ducks the music
   (`"duck": {"under": "voice"}`), fades on the edges, master at -14 LUFS and -1 dBTP unless
   `TASK.md` names another target.
6. `showtime audio mix <project>/audio/mix.json -o <project>/audio/mix.wav`, then
   `showtime audio meter <project>/audio/mix.wav`. Quote the numbers.

Done when: the mix meters within 1 LU of the target with true peak at or below the ceiling, every
effect lands on its cue, the voice is never masked (check the report's per-section levels), the mix is
heard on a phone (`speaker.gap_300_lu` in the report at most 10; a sub drop, boom or impact has a mid
transient on its hit, `sound-design.md` §3), and every
CC-BY item has its credit line in `credits.txt` in your folder.

## When timing changes

If the director resumes you with new hit times (the voice was retimed, a scene moved), update
`mix.json`, re-run the mix and meter, and return a fresh contract. Never guess new times.

## Never

- Touching `voice/`, `index.html` or `showtime.json`.
- Tracks with non-commercial or unknown licenses.
- Loudness by ear: always meter.

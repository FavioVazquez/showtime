# Crew brief: storyboard artist

Read this when you were dispatched as the storyboard artist of a showtime job (after
`references/crew/rules.md`).

**Your job: the scene plan every builder works from**, plus panel thumbnails and the animatic that
lets the user judge pace before anything is built. References: `references/pacing.md`,
`references/motion-craft.md`, `references/transitions.md`, `references/components.md` (or
`references/film-api.md` for canvas films), `references/render.md`.

## Deliver

1. `storyboard.json`: rows P1 to Pn, one per scene, each with
   - `id` (the scene id builders use, e.g. `s3-export`), `start`, `dur`;
   - `visual`: what is on screen, concretely (which capture, which component, which camera move);
   - `onscreen`: the lines from the scriptwriter's `onscreen.json`, unchanged;
   - `vo`: the script line ids spoken in it;
   - `cues`: music and effect moments with their times inside the scene (hits the picture must land);
   - `transition_in`, `transition_out` (`references/transitions.md`);
   - `build`: components or film calls, and the assets needed (font families, icon ids, media ids);
   - `files`: the fragment files its builder will own (`s3-export.css`, `s3-export.js`).
2. `storyboard.md`: the same as a human table (id, time, visual, text, VO), for the board and the user.
3. `assets-needed.txt`: every font, icon, emoji and media item the storyboard names, one per line,
   with the showtime command that fetches it. The director fetches them all before builders start.
4. `thumbs/`: one still per panel from a stub project (below), named `<id>.png`.
5. `animatic.mp4` when `TASK.md` asks for it.

## How

- Durations sum exactly to the target length. Voice-led: take the lengths from the job's
  `voice/timeline.json` slots, never from guesses; text-led: from the reading-time rules.
- Scene lengths follow `pacing.md` (holds, cut rhythm); flag any scene over the platform's patience.
- Stub project: `showtime new <template> <own dir>/stub --duration <length>`, one plain section per
  panel with its key visual blocked out (real captures, real copy, placeholders labelled). Then
  `showtime check <own dir>/stub` and `showtime snap <own dir>/stub --at <mid-time of each panel>`;
  look at every image.
- Animatic: the stub with panel stills, the scratch VO and the temp bed if they exist, rendered with
  `showtime render <own dir>/stub --preview --scale 0.5 -o <own dir>/animatic.mp4`. Never `--job`:
  that would record your draft as the job's preview.

Done when: the durations sum to the target, every panel has a thumbnail you looked at, every text
line fits its hold, and every asset named is in `assets-needed.txt`.

## Never

- Changing the script's words or the concept: note the conflict instead (words longer than their slot,
  a shot the concept does not support).
- Registering media on the board, or writing into `studio/`.

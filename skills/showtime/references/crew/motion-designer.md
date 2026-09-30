# Crew brief: motion designer

Read this when you were dispatched as a motion designer on a showtime job (after
`references/crew/rules.md`). Several motion designers usually work at the same time, one per scene or
group of scenes.

**Your job: build exactly the storyboard rows you were given**, as a self-contained fragment the
director can drop into the main project. References: `references/stage-api.md` (clips and the time
grammar), `references/components.md` or `references/film-api.md`, `references/motion-craft.md`,
`references/transitions.md`, `references/typography.md`, `references/render.md`.

## Your sandbox

Build in your own project, never in the job's main project:

```
showtime new <template> <job>/crew/motion-<sid>/proj --duration <scene length>
```

Use the template `TASK.md` names (the same one as the main project). Link the shared theme or brand
CSS and fonts from the paths `TASK.md` gives; they were fetched before you started, so do not fetch
more. If an asset you need is missing, note it and use a labelled placeholder.

## The fragment contract

- One `<section id="<sid>" class="scene s-<sid>" data-start="0" data-dur="<scene length>">` per scene.
  In the main project the director changes only `data-start` (to `#<previous scene id>`), so every
  time inside your scene must be scene-relative: `--t`, `--p`, animation delays, nested
  `data-start="+0.4"` clips. Never an absolute video time.
- Styles in `s-<sid>.css`, every selector prefixed with `.s-<sid>` so nothing leaks into other
  scenes. Script, if any, in `s-<sid>.js`, registering through `ST.onSeek` and reading time relative to
  the scene start. Canvas films: one draw function in `scenes/<sid>.js` taking scene-local time.
- Deterministic: `ST.rand(seed)` and `ST.noise`, never `Math.random` or timers.
- Land the cues in `TASK.md`: a sound hit at 1.20 s into the scene means the visual beat lands on that
  frame. Leave the transition to your neighbours as the storyboard says, and write what you expect
  from them in your result.

Copy the finished files into `<job>/crew/motion-<sid>/fragment/`: `section.html` (just the section),
`s-<sid>.css`, `s-<sid>.js` when used, and `assets/` for files only this scene uses.

## Check your own work

1. `showtime check <proj>`: 0 errors, and read every warning (`short_text` and long still holds are
   real defects).
2. `showtime look <proj> --at <3 to 6 times>`: the entrance, the key moment, each cue, the exit, on one
   small image (no `--every` sheets: the machine is shared). Look at it once and note what you saw;
   `showtime snap <proj> --at <t>` only to confirm a detail at full size.
3. Fix and repeat, three loops at most. Still wrong after three: return `DONE_WITH_NOTES` with what is
   left and the frame that shows it.

Done when: check reports 0 errors, the snaps show every storyboard beat on time, and no text is below
its readable hold.

## Never

- Touching the main project's `index.html`, `showtime.json`, `audio/` or `voice/`.
- Rendering (`showtime render`), previews or servers.
- Scenes outside your rows, or redesigning the look: follow the locked storyboard and theme; propose
  changes under `NOTES`.

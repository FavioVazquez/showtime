# Launch film (16:9, 9:16, 1:1): five scenes, a still camera, match cuts, cut to a produced track

The default for launch, promo and release videos (`references/workflows/launch-video.md`). It follows
the premium grammar: 5 scenes, no hard cuts, one ground, one accent, one type system, one message at a
time, the scene changes on the music's phrases and the name on its swell.

Files:
- `showtime.json`: size, fps, duration, `"kind": "launch"` (qa then judges the edit rhythm: hard cuts,
  scene count, still stretches, flat music), the poster (the hook, baked into frame 0).
- `audio/mix.json`: one produced catalog track (`"catalog": "<id>"` with `offset`, `dur`, fades), no
  effects. `showtime audio cuts --apply <project>` picks the excerpt and moves the scenes onto its
  phrases; the track is fetched on first use and credited in `credits.txt`, `share.txt` and the end
  card's `data-credit` line.
- `index.html`: the film.
  1. **hook**: one line, big, complete at frame 0; the key word (`<em>`) holds a letter marked
     `data-portal="counter"`. It rests about 2 s, then the camera leans toward that letter (the start of the
     fly-through), so the hook never sits frozen for 4-5 s.
  2. **verb**: the camera flies **through** the letter's counter into the product window: a command
     types and its output lands, then the result line is marked.
  3. **proof** and 4. **proof**: **match** handoffs: the window (`data-match="win"`) stays in place while
     the next command runs in it (`.hist` shows the previous command, dimmed, with its whole output or none, never a partial one: one terminal session) and the
     headline beside it changes.
  5. **end**: a slow **blur-dissolve** onto the name, the value line, the install command, the URL and
     the music credit.
  Under all scenes sits one world layer (a drifting key light, a rim light, a vignette) and grain; the
  scenes are see-through, so the ground never cuts.

Slots (search for `SLOT:`): the label and hook, the window title, each command and its output lines
(copied from `<job>/work/evidence/*.txt`; `data-st="fit"` on `.term` shrinks the type so the longest command fits at every size), each headline, the end card's name, value, install command
and URL. For a web product replace the terminal with
`<div class="win" data-match="win" data-st="browser-frame" data-src="shots/app.png"></div>`; for real
clips put a `<video>` (VP9 proxy) in the window.

Timing: scene lengths are the `data-dur` of each `<section>`; inside a scene, `data-at` (typing),
`data-start="+N"` (output lines) and the `mark` delay are seconds from the scene start.
`showtime retime <project> -d <s>` scales them; `showtime audio cuts --apply` or
`showtime retime <project> --cuts ...` sets the scene changes directly.

Brand: `showtime new launch` applies the brand kit it finds (`showtime brand capture <repo|url> --job <job>`
writes one to `<job>/brand/`): a `<style id="st-brand">` block sets the colour tokens, the product window
(`--win-*`, the product's code-block colours), the world light and the fonts, and the end card's wordmark,
version, value line and install command replace their SLOTs. By hand: the colour and font tokens at the top of the style. Sizes are container units,
so `showtime render <project> --size 9:16` (and `1:1`) re-lays the same page: the window on top, the
words below, inside the feed safe zone.

Commands:
- `showtime preview .`   player with scrubber and audio
- `showtime check .` and `showtime check . --size 9:16`
- `showtime snap . --every 1`
- `showtime render . --job <job>` and `showtime render . --job <job> --size 9:16`

Components and transitions: `references/components.md` (camera, typewriter, browser-frame),
`references/transitions.md` (through, match, pan).

# Tutorial series: one kit, many episodes (a product walkthrough drawn on canvas)

A series of short how-to videos for one product that look, sound and move the same from episode to episode.

- `kit.js` (the series root): **the one place to edit** what every episode shares.
  - The look: palette, fonts, the window layout.
  - The chrome: intro card, the step band with progress, captions under the window, keycaps, recap and outro.
  - The sound: a four-note signature motif (intro, and its answer in the outro), click, key, Enter, success, whoosh, step tick, and a music bed whose chords resume mid-chord on any seek.
  - The product, drawn procedurally: `KIT.state()` and `KIT.drawApp(T, st)`, with named hit-rects (`KIT.rects(st)`: `add:0`, `card:c3`, `save`, `col:1` ...) so cursors, cameras, spotlights and callouts target the UI by name.
- `cues.js` + `opener.js`: the series opener (this folder is itself a project: `showtime render .` renders it).
- `episode-01/`: an episode. It is a normal project with a synced copy of the kit. Its `episode.js` is one timeline table that drives both the picture and the sound through `KIT.episode(spec)`: steps, state events, cursor, camera, captions, keys, typing, spotlights and callouts.
- `series.json`: the series name and its episodes.

Workflow:

```
showtime series add <series> --title "Move cards between columns"   # episode-02 from a short skeleton
showtime preview <series>/episode-02                                 # edit episode.js, watch it live
showtime series sync <series>                                        # after editing kit.js
showtime series check <series>                                       # stale kit copies? (exit 1)
showtime render <series>/episode-01                                  # MP4, as any project
showtime series export <series> -o site/                             # every episode as HTML + index.html
```

Replace the sample product (a planning board) with yours in `kit.js`: its state, `drawApp` and `rects`. The episode files then only change their timeline tables. The pattern, the kit API and the episode spec are in `references/series.md`.

Length: `showtime retime <series>/episode-01 -d <s>` scales the `CUE` table in `episode.js` (steps, clicks, keys, typing, captions, recap and outro move together). `showtime new series <dir> --duration <s>` sets the opener's length.

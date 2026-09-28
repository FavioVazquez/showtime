# Canvas tutorial: app walkthrough with cursor, clicks, typing, keycaps, zoom and step titles

A three-step product walkthrough drawn procedurally on one canvas (no screen recording needed), with a soft music bed and UI sounds.

- `cues.js`: every click, keystroke and step time. The picture and the score both read it.
- `app.js`: the fake app UI as a pure function of T (`appState(T)` + `drawApp`). Swap in your own screens and labels.
- `scenes.js`: camera moves, cursor, step titles, step bar and the keycap overlay.
- `score.js`: music bed + click, typing, key-combo and success sounds on the cue times.

To walk through a real web app instead, record it with `showtime demo record` and follow `references/tutorial-recording.md`.
The API is documented in `references/film-api.md` and `references/synth-score.md`.

Aspect: laid out for 16:9 (`design: [1920, 1080]`). Other aspects show the 16:9 design fitted inside the
frame; for a vertical walkthrough, record the app with `showtime demo record` and use
`showtime autozoom --fit cover --size 1080x1920` (see `references/tutorial-recording.md`).

Length: `showtime new tutorial <dir> --duration <s>` (or `showtime retime <dir> -d <s>` later) moves the whole timeline together: every time in `cues.js` (clicks, typing start, steps, outro), the poster and the score (typing speed `cps` is kept). Longer cuts keep every animation's speed and hold each scene longer; shorter cuts scale everything. Then run `showtime check`: it fails with `dead_air` when the scenes end before the video does.

The length as shipped and after `--duration`/`retime` is `duration` in `showtime.json` (this README states no times, so it never goes stale).

Sharing it as a web page: `showtime export html <dir>` gives one small file (the score plays live). Its start card shows the `title`; add `"subtitle"` (and `"kicker"`, a small line above the title) to `showtime.json` for a line under it. Chapters come from the `acts` in `index.html`.

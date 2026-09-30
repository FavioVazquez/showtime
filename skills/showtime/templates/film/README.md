# Canvas film: title, metaphor, data reveal, end card, with a procedural score

A short explainer drawn on one canvas with the `Film` toolkit, scored with `Synth`.

- `cues.js`: the ONE table of cut and hit times. Picture and music both read it, so a cut and its sound can never drift apart.
- `scenes.js`: the picture. `scenes(T, g, F)` draws the whole frame for time T.
- `score.js`: the music and sound design, rendered offline to WAV by `showtime render`. `showtime new film` rewrites it for each project (key, tempo and meter, chords, motif, instruments, drums from the brief's mood, away from recent jobs' scores); `showtime audio film-score <dir> [--mood M]` writes another. For a mood piece "with music", a produced catalog track in a mix (`"audio"`) is usually the better bed (`references/music.md`).
- `index.html`: loads fonts, the runtime and the three files above.

Edit the words in `scenes.js`, then move cue times in `cues.js` if a section needs more room (scores read section lengths from the cue gaps).
Render a quick look with `showtime render <dir> --preview`. The API is documented in `references/film-api.md` and `references/synth-score.md`.

Aspect: this film is laid out for 16:9 (`design: [1920, 1080]` in `index.html`). Any 16:9 size renders
identically; `--aspect 9:16` or `1:1` shows the same 16:9 design fitted inside the frame. For a real
vertical or square cut, set `design` to `[1080, 1920]` / `[1080, 1080]` and re-place the elements in
`scenes.js` (positions are in design units).

Length: `showtime new film <dir> --duration <s>` (or `showtime retime <dir> -d <s>` later) moves the whole timeline together: every time in `cues.js` (cuts, hits, the end), the poster and the score, whose tempo is adjusted so cuts stay on bar lines. Longer cuts keep every animation's speed and hold each scene longer; shorter cuts scale everything. Then run `showtime check`: it fails with `dead_air` when the scenes end before the video does.

The length as shipped and after `--duration`/`retime` is `duration` in `showtime.json` (this README states no times, so it never goes stale).

Sharing it as a web page: `showtime export html <dir>` gives one small file (the score plays live). Its start card shows the `title`; add `"subtitle"` (and `"kicker"`, a small line above the title) to `showtime.json` for a line under it. Chapters come from the `acts` in `index.html`.

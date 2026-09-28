# Data story (16:9): title, bar chart, line chart and a closing number, driven by JSON data

Files:
- `showtime.json`: 1920x1080 at 30 fps, editorial light look, `"audio": "audio/mix.json"`.
- `audio/mix.json`: a restrained generated `underscore` bed (strings and a soft piano pulse, no drums,
  no build or drop) and one soft chime on the closing number, mastered to -14 LUFS. Serious data
  wants calm music or none (`references/music.md` section 1).
- Transitions: a soft dissolve out of the title, dips between charts (one calm family; no pushes or
  warps over a chart the viewer is reading, `references/transitions.md` section 3).
- `index.html`: four scenes. Charts are `data-st="chart"` elements that read `data/*.json`.
- `data/build-time.json`, `data/deploys.json`: title (the takeaway), subtitle, units, the highlighted
  label, an optional callout, and the numbers. All values are sample data (labelled "sample data" on screen): never publish
  invented figures; replace them and cite the source in the last scene.

Chart options (JSON file or data-* attributes): `type` bar | hbar | line, `data` (bars:
`[{label, value}]`; lines: `{labels, series:[{name, values}]}`), `states` (the same chart
re-targeted at later times: `[{at, data, title}]`, the axis rescales first, then the marks move),
`highlight`, `annotate {label|index, text, at}`, `prefix`, `suffix`, `decimals`, `compact`, `yMax`.

From a spreadsheet: `showtime data import table.csv . --x month --y signups --scene bars --title "<the takeaway>"`
writes `data/table.json` and points the scene's chart at it (`--chart line|hbar|race`, `--highlight max`,
`--annotate "text"`; `showtime data inspect table.csv` lists the columns).

Craft: one insight per chart state, highlight one series and mute the rest, direct labels instead
of legends, hold the settled chart 2-3 s (longer when narrated). For a longer cut (about 30 s) give
the bar scene 2-3 `states` instead of one long hold: `retime` warns when a scene is stretched past 1.5x.

Aspects: 16:9 as shipped; `--aspect 9:16` and `--aspect 1:1` also pass `showtime check` (charts
reserve room for their end labels; tall frames keep clear of short-form app UI).

Commands: `showtime preview .`, `showtime check .`, `showtime render . --preview`, `showtime render .`

Length: `showtime new data <dir> --duration <s>` (or `showtime retime <dir> -d <s>` later) moves the whole timeline together: the four scenes' `data-dur`, the poster, the music sections and the sound effects. Longer cuts keep every animation's speed and hold each scene longer; shorter cuts scale everything. Then run `showtime check`: it fails with `dead_air` when the scenes end before the video does.

The length as shipped and after `--duration`/`retime` is `duration` in `showtime.json` (this README states no times, so it never goes stale).

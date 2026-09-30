# Workflow: data story (animated charts and numbers)

Read this when the video is about numbers: a metric that changed, a benchmark, survey results, a
report's key figures, an animated chart ("turn these results into a 20 s video", "animate this CSV").
The default build is the `data` template: charts read JSON files, so the numbers never live in HTML.

## Essentials

- Defaults: 15-30 s, 16:9 at 1920x1080, `editorial` look, a restrained `underscore` bed or none, at most 2-3
  soft effects, one insight per chart state, the takeaway as the chart title, the source on screen in the last
  scene (§ Defaults)
- Every number on screen matches its source exactly (round only in narration); never extrapolate, smooth or
  fill gaps; if the data does not support the takeaway, say so before building (§ Honesty first)
- `showtime job init <topic>-data --goal "..."`; `showtime data inspect <table>`; write the takeaway as a
  sentence with a number plus the source line in SHOWTIME.md (`showtime job note --verified`) (§ Steps)
- `showtime new data <job>/project --title "..." --duration <len>`; charts read JSON in `<job>/project/data/`,
  numbers never live in HTML (§ Steps)
- `showtime data import <table.csv> <job>/project --x <col> --y <col> --scene bars --title "<takeaway>"`
  (`--chart bar|hbar|line|race`, `--series`, `--where`, `--top N`, `--names`); anything derived is a small
  script kept in the job (§ Steps)
- `"count": false` in the chart JSON for a number a paused frame must never misstate; replace every
  placeholder and the source line; 30 s or more gets 2-3 `states`, not a stretched `--duration` (§ Steps)
- Voice: one line per chart state, numbers spelled out in the script and exact on screen, each revealed on
  its word. Sound: never a drop, claps or a bright melody under numbers (§ Steps)
- `showtime check <job>/project`, `showtime look <job>/project`, show the sheet with the numbers listed; final
  with `"poster"`, `"expect": {"must_show": ["74%"]}` and `showtime render <job>/project --job <job>`, then
  `showtime check` and `showtime qa <job>`, then the critic round it names (quality mode, the default) (§ Steps)
- Hold a settled chart 2-3 s; direct labels, not legends; custom labels 29 px or more (§ Pitfalls)
- Pacing: a visible change about every 2 s (a state, a callout or reference line arriving, a count-up); hold
  only as long as the text needs to be read. Fix `slow_scene`, `dead_air` and qa `frozen` warnings (a
  beat, or a shorter scene), never accept them; a slow push-in alone still plays slow (§ Pacing)
- Items that arrive in a later state: leave them out of the earlier states (or `null`), never `0`; never hide
  chart labels while a chart moves (`chart_labels_hidden`); a callout names its year or value (§ Pacing)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inputs | 46-50 |
| Defaults | 52-58 |
| Honesty first | 60-64 |
| Steps | 66-136 |
| Pacing | 138-159 |
| Pitfalls | 161-168 |
| Read next | 170-173 |

## Inputs

- The data itself: a CSV, JSON, spreadsheet export, a table in a README or report, with its source.
- The takeaway the user wants (or you propose one from the data and state it as an assumption).
- Helpful: brand kit, platform, whether there is a voice-over.

## Defaults

15-30 s, 16:9 at 1920x1080 (`--aspect 9:16` and `1:1` also pass check); `editorial` look from the
template; a restrained `underscore` bed (sections `intro`/`verse`/`outro`, no build or drop) or no music,
and at most 2-3 soft effects (`music.md` section 1); one insight per chart state; the takeaway as the chart title; the
source cited on screen in the last scene. State the takeaway you found in the opening line; ask which
matters most only when the data supports two different stories.

## Honesty first

Every number on screen must match its source exactly (round only in narration). Never extrapolate,
smooth, or fill gaps; never start a bar axis above zero without saying so; label sample or illustrative
data as such. If the data does not support the takeaway the user wants, say so before building.

## Steps

1. **Job.** `showtime job init <topic>-data --goal "..."`.
2. **Read the data.** Load it, check units, time ranges, missing values and outliers. A CSV, TSV or
   JSON table: `showtime data inspect <table>` lists its columns, which are numbers, and the first
   values. Write the takeaway as a sentence with a number ("Build time fell 74 % in six months") and
   the source line.
   *Done when:* the takeaway and its source are in SHOWTIME.md (`showtime job note --verified`).
3. **Story.** Headline takeaway, context state, the change, one annotation, the implication
   (`story.md` section 4, data story). Pick the chart per idea: bars to compare, ranked bars to re-order,
   lines for change over time. Plan chart `states` for before/after moments.
4. **Project.** `showtime new data <job>/project --title "..." --duration <len>` (scenes `open`,
   `bars`, `lines`, `stat`). Charts read one JSON file each in `<job>/project/data/`. From a table:

   ```
   showtime data import <table.csv> <job>/project --x month --y signups --scene bars        --title "Signups doubled after launch" --highlight max --annotate "launch week"
   ```

   It writes `data/<table>.json` and points that scene's chart at it (`data-src`, `data-type`).
   `--chart bar|hbar|line|race` (default: bar for one value column and up to 12 rows, else line),
   `--y a,b` for several lines, `--series <col>` for long tables (one row per label and series),
   `--top N` (keeps the N largest; a bar chart keeps the table's order, e.g. chronological, an hbar
   ranks by value; `--sort value|source` overrides), `--ref next` (a dashed line at the first row
   `--top` left out: "next warmest"), `--step S` (race, seconds per row), `--prefix/--suffix/--decimals`
   (detected from values like $3.5k or 45 %), `-o <file>`, `--dry-run`. Negative values (anomalies,
   deltas) chart below a zero line. `--names col="Label"` sets a series' display name (the default
   only makes the column readable: `wind_solar` becomes "Wind solar"; custom components keyed by
   name see the display name). A scene without a chart element still gets its data file; the import
   prints the element to add.

   **A long table** (a statistics download: one row per series and month, with annual rows mixed
   in, like EIA's `MSN, YYYYMM, Value`): reduce it in the import, no derive script. `--where` keeps
   the matching rows (repeatable, all must match): `COL=VALUE`, `COL!=VALUE`, `COL~REGEX`,
   `COL>N`. Then `--series` turns one row per (label, series) into lines or racers:

   ```
   showtime data import eia.csv <job>/project --where "YYYYMM~13$" --where "MSN~^(CLETPUS|NGETPUS|WSETPUS)$" \
       --x YYYYMM --y Value --series MSN --chart line --names CLETPUS=Coal,NGETPUS="Natural gas",WSETPUS="Wind + solar"
   ```

   (EIA marks annual totals as month 13.) `showtime data inspect <table>` first shows the columns
   and sample values. Anything more (a ratio of two series, a rolling mean) is a small script that
   writes a clean CSV; keep it in the job so the numbers can be checked.

   For a number a paused frame must never misstate, set
   `"count": false` in the chart JSON (labels appear at their final value). The subtitle names the source file until you
   write the real source. Other charts: write the JSON by hand (`title` = the takeaway, `subtitle`,
   `prefix`/`suffix`, `highlight`, `annotate`, `data`, `states`; `components.md` section 4). Replace
   every placeholder value; update the closing number and the source line. For 30 s or more give the
   bar scene 2-3 `states` (a before/after): `--duration` far past the template's length stretches
   scenes into still holds, and it warns past 1.5x.
5. **Voice (optional).** One line per chart state, `## <scene id>` per scene in
   `<job>/project/narration.md`; `showtime voice script ... --fit <seconds>` and
   `showtime retime <job>/project --from-voice <job>/project/voice/timeline.json` as in
   `social-short.md` step 4; reveal each number on the word that says it. Numbers are spelled out in
   the script ("seventy-four percent"), exact on screen.
6. **Sound.** Keep the calm bed (never a drop, claps or a bright melody under numbers; a team report
   can also go without music); one soft effect on the closing number
   (`count-up.sync.land` gives the exact landing time), at most two more on real state changes.
   Transitions: one calm family for the whole piece, `dip` between scenes full of text (`transitions.md`
   section 3, data and reports).
7. **First look.** `showtime check <job>/project`, `showtime look <job>/project` (`looking.md`), judge
   every settled chart state: labels readable, the highlight obvious, end labels not clipped.
   Show the sheet with the numbers listed beside it so the user can verify them, and carry on.
8. **Final.** `"poster"` on the most telling chart state; `"expect": {"must_show": ["74%"]}` for the
   key figures; `showtime render <job>/project --job <job>`.
9. **Verify.** `showtime check <job>/project` (records on-screen text for `must_show`), then
   `showtime qa <job>` (the latest final), `showtime look <job>`, then the critic round qa names (quality
   mode, the default: `review.md`). *Done when:* PASS/WARN with every must-show figure found and no
   "review pending".
10. **Deliver.** Share copy that states the same number and the source; exports; the delivery card.

## Pacing

- **A beat about every 2 s.** After the marks land, the next thing arrives: a reference line, the
  callout (`annotate.at` about 1-1.5 s after it), a highlight (`highlightAt: "settled"`), the next
  `state`, a count-up. A chart scene longer than about 6 s needs a second state or a split into two
  scenes. `showtime check` reports `slow_scene` when a scene holds past its last change and its reading
  time by more than 2.5 s (4 s for the last scene): add the beat or shorten the scene (`data-dur`, or
  `showtime retime` for the whole video). The template's slow push-in keeps a hold from freezing; it
  does not make it lively.
- **Reading time sets the hold, not more.** Every text stays up for its reading time (the phone check's
  `short_text`); a longer hold than that and the next beat's 2 s is dead time. A 30-45 s story is 5-7
  scenes or 2-3 states per chart, not the four template scenes stretched.
- **Constancy.** Items that join in a later state are absent before it: leave the label out of the
  earlier state's data (or give it `null`); a `0` is a real zero with a "0.00" label on the baseline.
  Existing labels stay lit and ride their bars while items arrive; `count: false` labels show only
  real values, also across a morph. Never add CSS that hides `.st-chart-val` or `.st-chart-endlabel`
  while `[data-st-moving]` (check warns `chart_labels_hidden`): every number blinks off and on.
- **Callouts name their datum.** "2015: first year above 400 ppm", not "first year above 400 ppm". On a
  line chart the chart prefixes the point's label when the text does not name it; `{label}` and
  `{value}` in `annotate.text` are filled from the data ("{value} in {label}").
- **Transitions between text-heavy scenes: `dip`.** A blur dissolve smears both scenes' text in the
  middle of the window (a muddy frame on a paused player); the template uses dips throughout.

## Pitfalls

- Several insights in one chart state: split them into states or scenes.
- Legends instead of direct labels; rainbow palettes. Highlight one series, mute the rest (`color.md`).
- Holding the settled chart for less than 2 s: nobody reads it (2-3 s, longer when narrated).
- Axis labels too small at 1080p: the chart keeps them at 29 px or more; custom labels you add need the
  same (check groups its `small_text` notes into one line).
- A count-up that lands on a rounded value different from the source.

## Read next

`references/story.md`, `references/components.md`, `references/color.md`, `references/typography.md`,
`references/pacing.md`, `references/qa.md`.

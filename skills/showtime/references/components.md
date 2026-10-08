# Motion components: API, options and examples (runtime/components)

Read this when you are building an HTML/DOM video page (`showtime new dom|short|data`) and want
titles, captions, lower thirds, stats, charts, code, browser or device frames, a cursor, chat or
notification UI, a checklist, a Ken Burns still, a map, an end card or a WebGL look (fluted glass,
tilt-shift, liquid metal, mesh gradient, god rays, marble, metaballs). For scene-to-scene handoffs read `references/transitions.md`; for timing
and taste read `references/motion-craft.md`.
Run `showtime motion` for the live list.

## Essentials

- Setup: `/_st/stage.js`, a theme CSS, then `/_st/components/index.js` as a module. Any element with
  `data-st="<component>"` mounts itself; options are kebab-case `data-*` (`data-exit-at` = `exitAt`) or JSON (§1)
- `at` is seconds local to the clip the component sits in (the nearest ancestor with `data-start`); every other
  time option (`cues`, `exitAt`, `path[].at`, `states[].at` ...) counts from the component's `at` (§1)
- A title already on screen at t=0: `data-style="none"` (kinetic-type), never a negative `at` (it shifts every
  exit too) (§1)
- Seek-safe: components are pure functions of time, with no timers, CSS transitions or accumulated state; your
  own components follow the same rules (compute from `lt`, measure in `setup` only) (§1, §8)
- Size in container units (`cqw`, `cqh`, `cqmin`) so one page works at 16:9, 9:16 and 1:1; a padded `.scene`
  shrinks them, so set `.scene { padding: 0 }` or pad an inner wrapper (§1)
- Frame-exact cuts: `data-start`/`data-dur` within 1 ms of a frame boundary land on it (`7.0667` is frame 212 at
  30 fps), so write beat-synced cuts with 4 decimals (§1)
- Put SFX and narration on `sync` beats (`count-up.sync.land`, `cursor.sync.click1`) after `await c.ready`; videos
  inside components are muted `<video data-st>` (§1)
- Where options live: `kinetic-type`, `typewriter`, `caption-karaoke` §2; `lower-third`, `count-up`, `steps`,
  `question-beat` (a stop-and-ask question's pause and think beat) §3;
  `chart`, `world-map` §4; `browser-frame`, `device-frame`, `cursor`, `keystrokes`, `code-block`, `chat-thread`,
  `notifications`, `feature-grid` §5; `camera`, `fit`, `portal`, `ken-burns`, `logo-reveal`, `end-card`, `grain`
  §6; the WebGL looks `fluted-glass`, `tilt-shift`, `liquid-metal`, `mesh-gradient`, `god-rays`, `marble`,
  `metaballs` §7; themes and tokens §8; writing your own
  §9. Live list: `showtime motion`
- `caption-karaoke`: `clean-pop` is the default and the style for 9:16 shorts; 3-5 `emphasis` words, not more;
  place the layer outside the scenes so it runs across cuts (§2)
- `count-up` and `chart` take real numbers only; the chart title is the takeaway computed from the data; keep
  numbers in a `src` JSON file; a chart needs a sized box (§3, §4)
- Keep chart `valueLabels` on its auto-thinning default (`"all"` triggers `labels_crowded`); past ~12 labelled
  bars (~6 at 9:16) label only the highlight and extremes, aggregate, or use a `line` chart (§4)
- Chart from a table: `showtime data import <table> <project> --x <col> --y <col> --scene <id>` (§4)
- Capture pages at the device's real viewport; code panels from `showtime code file.ts -o code.json` with a shiki
  theme whose comments clear 4.5:1 (`showtime check` judges every token) (§5)
- Chat and notification UI stays generic (never a real app's branding); no emoji icons (§5)
- `end-card` holds >= 2.5 s; a 5-6 % `camera` push onto a result is the premium move (§6)
- Motion blur on a snap beat: `data-st-blur` on the moving element (a word, a card, a component), smeared only
  on its fast frames, sharp when it lands; 1-3 a video, never on text being read (§1)
- Looks need no GPU (WebGL on SwiftShader) and fall back to a CSS or 2D version without WebGL; `tilt-shift` and
  `mesh-gradient` are the quiet ones for explainers, `fluted-glass`, `liquid-metal`, `god-rays` and `marble` are
  for launches, titles and reels, `metaballs` for playful beats and a gooey wipe; `check` warns (`look_budget`)
  when one costs more than 50 ms a frame without a GPU (§7)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. Setup (two lines) and the time model | 64-114 |
| 2. Text: kinetic-type, typewriter, caption-karaoke | 116-175 |
| 3. Identification and numbers: lower-third, count-up, steps, question-beat | 177-218 |
| 4. Data: chart, world-map | 220-271 |
| 5. Product and UI: browser-frame / device-frame, cursor and keystrokes, code-block, ... | 273-335 |
| 6. Camera, stills, closers, texture | 337-378 |
| 7. Looks (WebGL): fluted-glass, tilt-shift, liquid-metal, mesh-gradient, god-rays, marble, metaballs | 380-545 |
| 8. Themes (runtime/themes) | 547-560 |
| 9. Writing your own component | 562-581 |

## 1. Setup (two lines) and the time model

```html
<script src="/_st/stage.js"></script>                                  <!-- the time contract -->
<link rel="stylesheet" href="/_st/themes/neutral.css">                  <!-- colours, fonts, motion feel -->
<script type="module" src="/_st/components/index.js"></script>         <!-- every component, auto-mounted -->

<section class="scene" data-start="0" data-dur="4">
  <h1 class="t-display" data-st="kinetic-type" data-style="blur" data-at="0.2">Hello</h1>
</section>
```

- **Mounting.** Any element with `data-st="<component>"` mounts itself. Options are `data-*`
  attributes in kebab-case (`data-exit-at` = `exitAt`); arrays and objects are JSON. Or mount from
  JS: `import { KineticType } from '/_st/components/index.js'; KineticType('#title', { style: 'blur' })`.
  A JSON blob works too: `data-options='{"style":"blur","at":0.2}'`.
- **Time.** `at` is when the component starts, in seconds **local to the clip** it sits in (the
  nearest ancestor with `data-start`; composition time outside any clip). Every other time option
  (`cues`, `exitAt`, `path[].at`, `highlight[].at`, `states[].at` ...) counts **from the component's
  `at`**: with the default `at: 0` that is clip time, but `data-at="0.6" data-exit-at="5"` exits at
  5.6 s into the clip. To have a title already on screen at t=0, use `data-style="none"` (kinetic-type)
  rather than a negative `at` (which shifts every exit time too).
- **Seek-safe.** Components are pure functions of time: they set inline styles on every seek and
  never use timers, CSS transitions or accumulated state, so any frame renders alone, in any order.
  They measure once, after their fonts load and with their clip forced visible.
- **Sync points.** Each controller exposes `sync` (composition seconds of named beats, e.g.
  `count-up.sync.land`, `cursor.sync.click1`) to line up SFX or narration:
  `const c = CountUp('#n', {...}); await c.ready; c.sync.land`.
- **Sizing.** Everything is in container units (`cqw`, `cqh`, `cqmin`). `.stage` and `.scene` are
  size containers, so the same page works at 16:9, 9:16 and 1:1. Tall frames can switch layout with
  `@container (max-aspect-ratio: 5/6) { ... }`. Container units measure the content box: a `.scene`
  with padding makes `90cqh` 90 % of the padded box, not of the frame (set `.scene { padding: 0 }`
  or pad an inner wrapper when you place things by frame percentages).
- **Frame-exact cuts.** `data-start`/`data-dur` values within 1 ms of a frame boundary land on that
  frame (`7.0667` is frame 212 at 30 fps), so beat-synced cuts can be written with 4 decimals.
- **Styling.** Components read theme tokens (`--accent`, `--font-display`, `--radius` ...) with
  fallbacks; component CSS loads first, so your page CSS wins. Class names are `st-<component>-*`.
- **Media.** Images and videos inside components are awaited before the first frame. Videos must be
  muted `<video data-st>` (the stage seeks them).
- **Motion blur on a snap.** `data-st-blur` on the element that moves (any element: a word, a card, a
  component's root) smears it only while it moves faster than 6 px a frame, as a 180° camera shutter would,
  and it lands sharp: `<span class="word" data-st-blur>SNAP</span>`, or `data-st-blur="shutter 270; max 120"`.
  The stage poses it between frames from its CSS animations, its component's update, `ST.anime` timelines or
  a `pose(t)` given to `ST.blur(el, {pose})`. One to three snap beats a video, never on text being read or
  slow moves (`check` warns): stage-api.md § Shutter blur, motion-craft.md §5.

Helpers exported by `/_st/components/index.js` (from `core.js`): `ease(name)` (`'power3.out'`,
`'expo.inOut'`, `'spring(0.5,0.8)'`, `'glide'`, `'steps(6)'`, `'cubic-bezier(...)'`, named
`premium|standard|emphasized|exit|camera`), `spring(response, damping)`, `seg(t, start, dur, ease)`,
`envelope(t, {start, in, end, out})`, `stagger(i, n, each, {cap, from})`, `hash(i, seed)`, `rng(seed)`,
`noise1(x, seed)`, `splitText(el)`, `define({name, defaults, setup})` to write your own component.

## 2. Text

### kinetic-type
Split a headline into words, characters or lines and reveal with a stagger (total stagger capped).
| option | default | meaning |
|---|---|---|
| `style` | `rise` | `rise` `mask` (slides up from behind a clip) `blur` `pop` (spring) `slide` `drop` `swing` (3D flip up) `track` (letters converge) `scramble` (glyphs cycle then lock) `fade` `none` (on screen from the start; exits still apply) |
| `by` | `words` | `words` `chars` `lines` (per-letter only for 1-3 word heroes) |
| `dur`, `stagger`, `cap` | theme | per-unit entrance time, gap between units, max total stagger (0.6 s) |
| `from` | `start` | `start` `end` `center` `edges` `random` |
| `ease` | per style | any ease name |
| `distance`, `blur` | 0.55, 0.18 | travel and blur in em |
| `accent` | | comma list of words to colour with `--accent` (`<em>` works too) |
| `cues` | | array of start times per unit (lock words to narration word times) |
| `exit`, `exitAt`, `exitDur`, `hold` | `none` | `fade` `rise` `drop` `blur` `mask`; exit at `exitAt` (counted from `at`), or `hold` s after landing, or at the clip end |
```html
<h1 class="t-hero" data-st="kinetic-type" data-style="mask" data-accent="faster">Ship faster</h1>
```

### typewriter
Typed text with a human or uniform cadence; caret solid while typing, blinking when idle.
Options: `text` (default: the element's text), `script` (`[{type:'...'},{pause:0.3},{back:4}]` for
typos and corrections), `cadence` `human|uniform`, `cps` 18, `fit` (seconds to finish by),
`caret` `bar|block|underline|none`, `blink` 1.06, `hideCaretAfter`, `linePause` 0.35, `seed`.
```html
<p class="t-mono" data-st="typewriter" data-fit="2.5">npx showtime render launch</p>
```

### caption-karaoke
Word-timed captions grouped into readable cards, spoken word highlighted, placed in the safe zone.
Input: `src` (JSON URL) or `words`: a showtime transcript, the voice module's `*.words.json`, or
any `[{text, start, end}]` (`type` other than `word` is skipped; `emph: true` marks emphasis).
| option | default | meaning |
|---|---|---|
| `style` | `clean-pop` | `clean-pop` (sentence-case heavy sans, thin edge and soft shadow, spoken word turns the accent: the default, and the right one for 9:16 shorts), `bold-pop` (outlined heavy caps, spoken word pops slightly in the accent: loud, hype pieces), `highlight-box` (accent box glides behind the word), `underline-sweep` (bar sweeps under the word as it is said), `minimal` (subtitle, upcoming words dimmed), `boxed-pill` (card on a rounded plate), `fill` (each word fills left to right) |
| `position` | `auto` | `auto` (9:16: `lower`; 16:9: 10 % above the bottom), `top` `center` `lower` (the block hangs from 62 % height, so a two-line card grows down, never up into the content; lifted only if it would pass the safe bottom) `bottom` |
| `maxWords`, `maxChars` | per style / fit | card limits (clean-pop 5, bold-pop 4 words; cards aim for about one word fewer); `maxChars` = two lines of what fits the width, at most 32 characters a line on 9:16 (42 otherwise) |
| `gap` | 0.3 | a pause longer than this starts a new card |
| `emphasis` | | comma list of the 3-5 words that carry the message, coloured in the accent (no scale). At most one shows per card (the first); more than 5 shown (or one per 6 s in longer videos) is a `check` warning, because an accent on every term means nothing. Terms match letters and digits (`2.0`, `--unique`) |
| `size` | 1 | font scale; `upper` forces uppercase on/off; `holdLast` 0.8 s; `plate` colour |
| `keep` | | comma list of phrases never split across cards or lines (`"Command K,Command E"`); each word keeps its own highlight time |
| `skipLines` | | comma list of voice line ids whose words are not captioned (the title already says it); survives `retime --from-voice`. A word with `"hidden": true` in the words file is skipped too |
| `group` | `words` | `phrase`: cards break only at punctuation and pauses (up to 8 words on 2 lines, at least 1 s each), for fast speech (Spanish at ~3.5 words/s gave 0.4 s cards) |
| `minShow` | 0.4 | a card shorter than this joins a neighbour (fast speech would otherwise flash "HIT N" for 0.27 s); a card that still cannot merge is a `check` warning |
Grouping: a sentence end or a pause longer than `gap` always ends a card; inside a sentence the
split is chosen as a whole: cards near the target size, on screen at least `minShow`, breaking at
commas and breaths, and never ending on a weak word (articles, prepositions, conjunctions,
auxiliaries: "empty lines before" / "sorting." becomes "clears empty lines" / "before sorting.";
English plus common Spanish, French, Portuguese and German ones). One-word cards are avoided; cards
never overlap; each card shows from its first word − 0.05 s to its last word + 0.35 s. Lines use
`text-wrap: balance`; a weak word stays on the line of the word after it, and a short token ("K")
can still strand away from its modifier: list such pairs in `keep`. Theme tokens:
`--cap-font --cap-weight --cap-ink --cap-accent --cap-outline --cap-plate --cap-active-ink`. The
edge, glow and drop shadow are all made from `--cap-outline`, so on a light ground set a dark ink and a
light outline (as `paper` does) and the words stay crisp; the accent must pass 4.5:1 on the ground.
For a light 9:16 short, `boxed-pill` (a plate behind the card) reads best.
Put the layer outside the scenes so it runs across cuts; it is marked `data-caption` for QA.
```html
<div data-st="caption-karaoke" data-src="voice/vo.words.json" data-style="highlight-box" data-at="0.6"></div>
```

## 3. Identification and numbers

### lower-third
`variant` `bar|card|kicker|pill`, `name`, `role`, `kicker` (label for `kicker`), `avatar` (image for
`pill`), `side` `left|right`, `hold` (seconds on screen after landing; default: until near the clip
end), `exit` true, `in` (entrance seconds; default 0.85, kicker 1.0), `position` `auto|top|none`
(`top`: under the safe top, for 9:16 videos whose captions sit in the lower half; none = place it
yourself). In 9:16 the type is larger (name 6.4cqmin, role 4cqmin) so it reads on a phone.
```html
<div data-st="lower-third" data-variant="card" data-name="Ada Park" data-role="Staff engineer" data-at="1"></div>
```

### count-up
`value`, `from` 0, `decimals`, `prefix`, `suffix`, `label`, `dur` 1.6, `ease` `power3.out`,
`compact` (12.8k), `group`, `variant` `plain|ring|bar`, `of` (ring/bar total; default 100 for %),
`pulse`, `align`, `locale` (number format; default the page's `<html lang>`, so a Spanish page shows
13,7 and 60.000; chart takes it too), `suffixAlign` (`auto`: a suffix starting with ° sits at the top of the figure, so
"°C" never reads as "◦C"; `top`, `baseline`). The number's box reserves the widest value the count
shows in the real font, so proportional display figures never run into the suffix. Size with
`--cu-size` (figure) and `--cu-ring`. Sync: `land`. Use real numbers only.
Prefix and suffix sit tight against the number ("+160%", not "+ 160 %").
```html
<div data-st="count-up" data-value="71" data-suffix="%" data-variant="ring" data-label="of Earth's surface is ocean"></div>
```

### steps
`steps` (array or comma list), `variant` `dots|bar|list`, `cues` (times each step activates; list
items tick on their own cue), or `first` 0.4 + `every` 1.2.

### question-beat
The "pause and think" beat of a stop-and-ask question (showtime.json `"questions"`, `html-export.md`
§ Questions), which is what the MP4 shows where the HTML export stops and asks: the prompt and its
choices while the narrator asks, a countdown ring for the question's `think` seconds from its `at`,
then the right choice marked and its reply in the countdown's place. Times come from the question
(a voice cue follows the narration): it appears where the asking line starts (2.5 s before the pause
for a time in seconds; `at` on the element sets it), so put it in the scene that asks. `id` (default:
the first question), `label` (`Pause and think`; write it in the video's language, `""` for none),
`reveal` true, `reply` true, `keys` true (A B C), `hold` (seconds after the reveal before it fades;
default: its clip ends it). Sync: `ask`, `pause`, `reveal` (put a soft tick or a chime on them).
```html
<div data-st="question-beat" data-id="q1" data-label="Pausa y piensa"></div>
```

## 4. Data

### chart
Bar, horizontal-bar and line charts with a story: grow/draw on, highlight one datum, callout.
| option | meaning |
|---|---|
| `type` | `bar` `hbar` (ranked rows that re-order smoothly) `line` |
| `src` | JSON file with any of the options below (recommended: keep numbers out of HTML) |
| `data` | bars: `[{label, value}]`; lines: `{labels: [...], series: [{name, values, color?}]}` |
| `states` | `[{at, data, title?}]`: morph to new data (axis rescales first, then marks move); a title that changes only after " · " (a race's year) swaps without fading |
| `title`, `subtitle` | write the takeaway as the title, computed from the data, never invented (illustration with made-up sample values 42 → 11 min: (42 − 11) / 42 = 74%, so "Median build time fell 74%") |
| `highlight` | label (bar) or series name (line) in the accent; the rest muted |
| `annotate` | `{label | index, text, at?}` callout after the marks settle |
| `prefix`, `suffix`, `decimals`, `compact`, `yMax`, `yMin`, `ticks` 4, `locale`, `grow` 0.9, `draw` 1.6, `curve` `monotone|linear` |
| `valueLabels` | `true` (auto): bar labels that would come closer than 0.3em shrink a little (never below 0.8x or the chart's minimum font), then the least important hide (the highlighted, annotated, max, min, last and first stay; the rest by size of value; a label that would sit on a neighbouring bar hides too), planned per state so they fade with a morph instead of flickering; `"all"` shows every label however crowded (`showtime check` then reports `labels_crowded`); `false` hides them (hbar races included) |
| `count` | `true`; `false` shows each value label at its real value, fading in as the bar lands (no "+0.69" mid-count on a paused frame) |
| `highlightAt` | `start`; `settled` colours the highlighted bar only once the bars have landed |
| `ref` | `{value, label, sub?, at?}`: a dashed reference line (a target, "next warmest: 2014, +0.75") drawn on after the marks settle |
| `dots` | `auto` (line points up to 40), `true`, `false` |
Negative values work in every type: the axis reaches below zero, a zero line appears and bars grow
down (anomalies, deltas, profit/loss); the axis leaves room under the lowest bar for its value label,
so it never sits on the category labels (unless `yMin` is set). A `prefix` of `+` signs values (`+1.29`, `−0.49`). Options in
the `src` file apply unless the element sets them (`data-*` or `data-options`), so `decimals` from
`data import` is honoured; tick labels carry the decimals their step needs (0, 0.5, 1.0). hbar rows
rank by value (ties keep the data order) and glide only while a state change runs. A single line
series' end label shows the value only (the title names it). `--chart-muted` can be a theme token
on `:root`.
Needs a sized box (e.g. `position:absolute; inset:...`). Sync: `settled`, `callout`, `ref`, `state2`...
Axis, value and subtitle labels never go below 2.7vmin (29 px at 1080p, readable on a phone); set
`--chart-min-font` lower only for a small inset chart. An `annotate` callout sits above its bar's
value label and any neighbour label under it, and the y axis leaves headroom for it. An hbar value
label that a `ref` line would strike through slides past the line as it draws on.
Many bars: category labels wider than their slot show every n-th (plus the last, highlighted and
annotated ones). Past ~12 labelled bars (or ~6 in 9:16) a value on every bar is noise: keep the
default auto-thinning, label only the highlight and the extremes, aggregate (decades instead of
years), or use a `line` chart whose end label carries the latest value.
From a CSV or JSON table: `showtime data import <table> <project> --x <col> --y <col> --scene <id>`
writes the chart file and points that scene's chart at it (`workflows/data-story.md`).

### world-map
World map or globe (Natural Earth 110m via `world-atlas`, d3-geo). `projection`
`naturalEarth|equalEarth|mercator|orthographic`, `spin` (deg/s, globe), `camera`
`[{at, center:[lon,lat], zoom, dur}]`, `highlight` `[{at, names:[...]|ids:[...], color?}]`,
`markers` `[{at, lon, lat, label}]`, `routes` `[{at, from:[lon,lat], to:[lon,lat], dur}]`,
`graticule`, `labels`, `src`/`object` for other TopoJSON/GeoJSON. Country names are the Natural
Earth names ("United States of America", "France").
One country (a regional map): `projection` `mercator` (conformal: the right shape at high latitude),
`src` the 50m file, and the zoom that fills a fraction `f` of the frame width with the country's
longitude span `L`: `zoom = f * W / ((L / 360) * min(W, H))` (Mercator's fit makes the world
`min(W, H)` wide). Routes are single great-circle legs: split a multi-stop route into legs with their
own `at`. A marker's "current/visited" state is a class you toggle on `.st-map-marker` from
`ST.onSeek`; to put a label left of its dot, set `text-anchor: end` in page CSS.

## 5. Product and UI

### browser-frame / device-frame
Brand-free chrome around a screenshot, a video or live HTML children. The URL bar uses the theme's
`--font-body`; on a page without a theme (a canvas film with DOM layers) set `--font-body` and link
a font file (`/_st/themes/fonts/inter.css`), or the bar falls back to the OS UI font.
Shared: `src` (image or video), `scroll` `[{at, to, dur}]` (`to` 0..1 fraction, pixels, or `#id`),
`zoom` `[{at, scale, x, y, dur}]` (camera push to x/y %), `camera` `page|frame` (`page`: the push
happens inside fixed chrome; `frame`: the whole window scales, chrome included, and its edges leave
the picture, which reads better than a page sliding under a pinned URL bar), `tilt` `[rx, ry]`
degrees, `enter` `rise|none`, `float`. Children given together with `src` stay as an overlay above
the screenshot (a highlight ring, a cursor target) and move with its scroll and zoom. Scroll
targets are measured once the image has decoded; a step that cannot move (the page is not taller
than the view) is a `check` warning. A full-page capture scrolls a flat image, so a sticky nav slides
away with it: cut the nav strip from the capture and pin it as a child if the real page keeps it.
browser-frame: `url`, `typeUrl` (types the URL), `title`, `theme` `auto|light|dark`.
device-frame: `model` `phone|tablet|laptop`, `color` `graphite|silver`, `notch`.
`drift` `auto|none|<scale per second>`: a still screenshot (`src` image) with no `scroll` or `zoom`
steps gets a slow push-in by default (+1.2 %/s, capped at +8 %), so the shot is never a frozen frame;
`none` turns it off (check then flags the hold). A cursor path or a scroll still reads better.
Capture pages at the device's real viewport (a desktop page squeezed into a phone looks wrong).
```html
<div data-st="browser-frame" data-url="acme.dev/pricing" data-src="shots/pricing.png"
     data-scroll='[{"at":1.5,"to":0.6,"dur":2}]' style="position:absolute;inset:10% 12%"></div>
```

### cursor and keystrokes
cursor: `path` `[{at, x, y} | {at, target:"#sel", dx, dy, click, hover}]` (x/y in % of the
cursor layer; targets are tracked live, so it follows tilted or moving UI), `style`
`arrow|hand|dot`, `size` 3.4 (cqmin), `arc` 0.12, `hideAfter`. It arrives exactly at each `at`;
clicks press the target (CSS `scale`) and ripple; `hover` sets `[data-st-hover]` on the target.
keystrokes: `items` `[{at, keys:"⌘ K"} | {at, text:"deploy"}]`, `hold` 1.5. `⌘ ⇧ ⌥ ⌃ ↵ ⌫ ⇥ ← → ↑ ↓`
are drawn as SVG so they look the same on every OS.
```html
<div data-st="cursor" data-path='[{"at":0,"x":85,"y":90},{"at":1.2,"target":"#buy","click":true}]'></div>
```

### code-block
Editor panel from `showtime code file.ts -o code.json` tokens (offline shiki; 65 themes).
`src`/`tokens`/`code` (plain text fallback), `title`, `chrome` `window|none`, `lineNumbers`,
`reveal` `lines|type|none`, `cps` 45 / `fit` (typing), `highlight` `[{lines:"4-6", at, color?}]`,
`diffAt` + `diffDur` 0.7 (with `showtime code old.ts --to new.ts`: removed lines flash red and
collapse, added lines open green), `focus` `[{line, at, dur}]` (scroll), `size` (cqmin), `dim` 0.35,
`firstLine` (an excerpt keeps its file's numbers: `data-first-line="258"` shows 258, 259, ... and
`highlight`/`focus` take those numbers).
Line numbers are 1-based and, for diffs, count the new file. Line numbers and diff gutters clear
4.5:1 on the default panel (`--code-ln-opacity` 0.62, `--code-add`, `--code-del`); pick a shiki theme
whose comments and punctuation also clear it (`houston` does; `vitesse-dark` draws comments at
#666666), since `showtime check` judges every token.

### chat-thread / notifications
chat-thread: `messages` `[{from:'me'|'them'|name, text, at?, stream?}]`, `typing` 0.9 s indicator
before replies, `gap`, `speed`, `names`. Auto-timed by reading time; scrolls as it fills.
notifications: `items` `[{app, title, text, icon?, time?, at?}]`, `every` 0.9, `max` 4 visible,
`top` (a CSS length or % of the frame; a `top` in the page CSS also wins over the safe-area default).
Generic UI only: do not imitate a real app's branding.

### feature-grid
`items` `[{icon, title, text}]` or existing children, `columns` (auto by aspect), `focus`
`[{at, index}]` spotlight, `stagger`, `cap` 0.55 (the whole stagger's ceiling in seconds; raise it
to land each card on its own beat), `dim`. Icons: `.svg` path (inlined, takes the accent; e.g.
`/_lib/lucide-static/icons/zap.svg`), raw `<svg>`, image, or text. Avoid emoji (they render
with each OS's own font).

## 6. Camera, stills, closers, texture

- **camera**: a scene camera over the content it wraps (put it at `position:absolute; inset:0` around
  the scene's content). `path` `[{at, dur, zoom, focus, to, ease}]`: `at` seconds from the scene start,
  `dur` the move (0 = a cut to that framing), `zoom` (1 = as laid out), `focus` a selector inside the
  camera or `[x%, y%]` (the point looked at), `to` `[x%, y%]` where it lands on screen (default the
  centre), `ease` (default `camera`). Zoom is interpolated in log space and the focus with the same
  curve, so a push reads even. `contain` (default true): at zoom >= 1 the content always covers the
  frame. `drift` (zoom per second after the last move, capped at +6 %): holds keep breathing;
  `data-drift="hold"` is the documented hold push, 0.012 (1.2 %/s), which `check` and qa's `frozen`
  detector both count as change on light and dark text frames (0.8 %/s is borderline, 0.4 %/s fails check). Children
  with `data-depth="k"` that fill the camera move k times as much (0.3 = a far layer: parallax).
  `keepText` (default true): while the camera moves, the union of the visible text stays inside the
  frame (the feed-safe box at 9:16), so a push never crops a headline; between moves (with `drift` 0,
  the default) the transform sits on whole pixels so type does not shimmer. `to: "stay"` zooms about
  the focus where it is laid out. A 5-6 % push onto a result is the premium move; `through`/`match`/`pan`
  (`transitions.md`) carry the camera from one scene to the next.
- **fit**: `data-st="fit"` on a terminal, a code line or a command pill: the type shrinks until the
  longest line fits the box (and the lines fit its height) at the frame size of the run, down to `min`
  (0.55); below that, lines wrap with a hanging indent. Measured once, after the components inside it.
  ```html
  <div class="cam" data-st="camera" data-drift="0.004"
       data-path='[{"at":0,"zoom":1},{"at":3,"dur":1.6,"focus":".out","zoom":1.08}]'>...</div>
  ```
- **portal** (for the `through` transition): `data-portal` on any element makes its box the opening;
  `data-portal="counter"` on a single letter (`<span data-portal="counter">o</span>`) makes the glyph's
  enclosed hole the opening (measured from the real font).
- **ken-burns**: `src` or child media, `from`/`to` `{scale, x, y}` (x/y %), or `focus` `[x%, y%]` +
  `zoom` 1.1, `dur` (default clip length), `ease` `sine.inOut`, `fit` (`cover`; `contain` shows the
  whole image; page CSS on `.st-kb-media` works too), `fade` (default: none when the shot starts with
  its scene, so beat cuts stay hard cuts; 0.4 s when it appears mid-scene with `at` > 0), `mask` (a CSS
  mask image applied to the moving picture, so it scales with the zoom; a mask on the wrapper stays
  fixed while the picture grows under it).
- **logo-reveal**: `text` (wordmark) or a child `<img>`/`<svg>`, `style`
  `assemble|mask|blur|draw` (draw needs inline SVG paths), `dot` (accent full stop), `bloom` (false:
  no accent glow as it lands; end-card takes it too).
- **end-card**: logo reveal + `tagline` + `cta` pill + `url`; hold >= 2.5 s. `logo` (image URL) or a
  child img/svg plus `text` shows the mark next to the name (stacked in tall frames): the mark
  resolves first, the name follows. A mark alone resolves with `blur` (`style` `mask|blur|draw`).
  Sizes: `--logo-mark-size` (default 16cqmin alone, 1.1x `--logo-size` next to the name).
- **grain**: seeded film grain over the frame; `opacity` (default `--grain`), `fps` 24, `size`,
  `blend`. Keeps dark gradients from banding after compression.

## 7. Looks (WebGL): fluted-glass, tilt-shift, liquid-metal, mesh-gradient, god-rays, marble, metaballs

Seven looks drawn by showtime's own WebGL layer (`runtime/effects/gl.js`, GLSL ES 1.00). They need no GPU:
without one Chrome draws WebGL on the CPU (SwiftShader), the same frame gives the same pixels with 1 or 3
render workers, and every motion is a function of the clip's time. Each one fills its box (by default the
scene: `position:absolute; inset:0`); text or other elements inside it sit on top. All seven in one 18 s page,
with its render: the `_looks` demo in the showtime repository's examples folder.

- **Shared options.** `at`; `keys` `[{at, dur, ease, ...values}]` moves numeric options over time (each key
  eases from where the values are to its own over `[at, at+dur]`; `dur` 0 is a cut), for example
  `data-keys='[{"at":0.5,"dur":1.6,"y":0.4,"ease":"sine.inOut"}]'`; `scale` renders the look smaller and lets
  the browser scale it up (cheaper, softer; `fluted-glass` and `liquid-metal` take 0.75 by themselves where WebGL
  runs on the CPU, unless `scale` is given, which looks the same at the frame size); `seed`.
- **Pictures.** `data-src` (an image file) or an `<img>` or `<canvas>` inside the element; the picture covers
  the box like `object-fit: cover`, `focus` `[x%, y%]` picks the centre. A `<canvas>` is read again on every
  frame, after the page's other `onSeek` handlers. `<video>` is not a source yet: use a still of it.
- **Without WebGL** each look draws a fallback so the frame still reads as designed: a CSS pane (fluted-glass), a
  CSS blur behind a mask (tilt-shift), a 2D chrome sphere (liquid-metal), a still CSS field (mesh-gradient), a
  still CSS glow behind the sharp shape (god-rays), its first frame worked out once in JS (marble), and flat
  blobs traced on a 2D canvas, which still move (metaballs); `showtime check` says so (`look_fallback`).
- **Cost without a GPU**: the extra ms a 1080p frame takes on the build box (a 64-core machine, SwiftShader;
  each frame a seek and a JPEG screenshot, as render takes it, against the same scene without the look), with
  one browser and per browser with 8 rendering at once (render's choice there):

  | Look, at its default | 1 browser | 8 browsers | at `scale` 1 (1 / 8) |
  |---|---|---|---|
  | fluted-glass (0.75 without a GPU) | 26 | 27 | 40 / 44 |
  | tilt-shift (blur passes at 0.35) | 38-42 | 49-52 | (the compose is full size already) |
  | liquid-metal sphere / ring / blob (0.75) | 18 / 20 / 30 | 22 / 42 / 37 | sphere 23 / 41, ring 61 / 77, blob 55 / 69 |
  | mesh-gradient (0.5) | 9-10 | 10-11 | 22 / 29 |
  | god-rays dawn, glow / spotlight (0.5) | 15-16 / 23 | 21-22 / 37 | dawn, glow 38 / 70, spotlight 94 / 133 |
  | marble (0.75) | 23-28 | 30-35 | 35-51 / 60 |
  | metaballs merge / lava / wipe (0.75) | 11 / 17 / 12 | 18 / 21 / 24 | 28 / 33 |

  A full-size canvas costs a CPU renderer more than its share of pixels (its copy to the screen and the caches),
  so most looks draw smaller and are scaled up; the four newer ones are soft enough not to show it, and fluted
  glass and liquid metal take 0.75 by themselves without a GPU. `showtime check` adds the costs up per look from
  its real size (`runtime/effects/gl.js` COST_1080P, the costs above with how each grows with size) and warns
  (`look_budget`) above 50 ms (`runtime/thresholds.json` "look_budget_ms"). A small machine without a GPU is
  several times slower than the box: keep one look per scene, and lower `scale` before adding a second one.
- **Many looks.** A look holds a WebGL context only while its clip is on screen and builds it again, the same,
  when a seek comes back, so a long reel can have a look in every scene. Chrome keeps about 16 contexts per
  page: `check` warns (`look_contexts`) above 8 looks on screen at once and fails above 14; past 12 at once
  the oldest give theirs back and show a still copy of their frame. A context the browser takes back anyway
  is `look_lost`.

**fluted-glass**: a pane of reeded glass over an image, or over slow glows in the theme's colours when there is
no image. Each flute shows a squeezed copy of a wider strip of the picture, with a chromatic split, a highlight
down each flute and a fine seam. Use it for hero frames, launch title cards and trailer plates. `preset`
`reeded` (fine, quiet), `fluted` (default), `prism` (wide, angled, strong split); `width` (px at the frame
size), `depth` (0-1.5), `angle` (degrees), `split` (0-0.6), `frost` (0-3, a softer picture inside the flutes),
`light` (0-1), `flow` (the flutes slide, px/s), `drift` (the picture pushes in, zoom per second, default
0.008), `focus`, `keys`, `scale` (default 1, and 0.75 where WebGL runs on the CPU). Fallback: the picture (or
the glows) under CSS flute shading.

```html
<div data-st="fluted-glass" data-src="media/plate.jpg"
     data-keys='[{"at":0,"depth":0},{"at":0.1,"dur":1.1,"depth":0.62,"ease":"premium"}]'></div>
```

**tilt-shift**: a sharp band across a screenshot or photo, with a blur that grows away from it. The quiet look:
it points at one region (a form, a chart row, a street) without boxes or arrows; move the band with `keys` as
the narration moves. `preset` `miniature` (narrow band, strong blur, richer colour), `focus` (wide band, soft
blur, the rest dimmed; for explainers), `progressive` (sharp below the band, blur toward the top edge, for
type over a photo); `y` (band centre, 0 top to 1 bottom), `angle`, `width` (half-height of the sharp band,
fraction of the frame height), `feather`, `blur` (px), `side` (`both|top|bottom`), `dim`, `saturate`,
`contrast`, `drift`, `focus`, `keys`, `scale` (the largest size the blur passes run at, default 0.35; strong
blurs run smaller on their own, a blur hides it). Fallback: a CSS-blurred copy behind a gradient mask.

```html
<div data-st="tilt-shift" data-src="shots/dashboard.png" data-preset="focus" data-y="0.7"
     data-keys='[{"at":2.4,"dur":1.2,"y":0.35,"ease":"sine.inOut"}]'></div>
```

**liquid-metal**: a chrome object whose surface flows slowly, reflecting a studio built from the theme
palette (a bright horizon, a graded sky and floor and soft boxes, faintly tinted by `--accent` and
`--accent-2`; a dark studio with white boxes on a dark ground, a white studio with dark cards on a light one),
with fresnel edges, a key highlight and a filmic roll-off, on a transparent canvas over the scene's own
ground, with a soft contact shadow. A word (`text`, in `--font-display`) or an image (`logo`) is printed on
the soft box behind the viewer, so it shows in the middle of the metal. Use it for launch end
cards and reels, not explainers. `preset` `auto` (chrome on dark, pearl on light), `chrome`, `pearl`, `neon`;
`shape` `sphere` (cheapest) `|blob|ring`; `size` (radius, fraction of half the shorter side, default 0.62);
`x`, `y` (centre); `liquid` (0-1; keep 0.3-0.45 when the reflected word must read); `speed`; `turn` (the
studio turns, degrees per second); `shadow`; `in` (seconds to grow in); `keys` (x, y, size, liquid), `scale`
(default 1, and 0.75 where WebGL runs on the CPU, which looks the same at the frame size for half the cost).
Fallback: a still chrome sphere drawn on a 2D canvas.

```html
<div data-st="liquid-metal" data-shape="blob" data-text="Tidepool" data-x="0.67" data-in="0.7"></div>
```

**mesh-gradient**: a soft colour field that drifts slowly: 4-6 colour points from the theme palette on long
closed paths, blended in Oklab (two colours meet without a grey or muddy middle), the field between them bent
by a smooth warp, with a fine grain so the gradient never steps into bands after compression. The quiet ground
for an explainer, a chapter card or a quote: text sits on top. `preset` `calm` (default: close to `--bg`, low
contrast, for words over it; on a dark ground it stays in the accent nearest the ground's hue, since a warm accent
darkened into a cool ground turns brown), `aurora` (accent glows in the dark), `vivid` (the accents at full
strength: a title or a reel, check the contrast of anything on it); `points` (4-6), `intensity` (how far the
colours leave `--bg`, 0-1), `warp` (0-1.5), `move` (how far each point travels, fraction of the frame height),
`speed` (1 = a loop of about half a minute), `grain` (0-0.08), `colors` (a comma list or JSON array of CSS
colours, used in turn), `keys` (intensity, warp, move, grain), `scale` (default 0.5: the field is smooth).
Fallback: the same points at the first frame as still CSS radial gradients.

```html
<div data-st="mesh-gradient"><h2 class="t-title">How the cache fills</h2></div>
<div data-st="mesh-gradient" data-preset="aurora" data-keys='[{"at":0,"intensity":0.3},{"at":0.2,"dur":1.5,"intensity":0.85}]'></div>
```

**god-rays**: shafts of light through a word or a logo. The light is gathered along rays from a light point
(three nested passes at a quarter of the frame size), so it leaks out around and between the letters in beams
and the shape's shadow streaks away from it; the shape itself is drawn sharp on top. Use it for a title or a
logo reveal: let the light come up (`in`, or `strength` in `keys`) and hold while the word reads. `preset`
`dawn` (default: a warm light right behind the shape, beams bursting out of the letters, the shape a dark
silhouette with a lit rim), `spotlight` (a cool light above the frame, beams falling through the air and the
letters' shadows down them), `glow` (the shape itself shines in the accent and streams out); `text` (in
`--font-display`) or `logo` (an image URL, or an `<img>` inside the element); `size` (the word's height,
fraction of the frame height, default 0.22); `cx`, `cy` (the shape's centre); `x`, `y` (the light; outside 0-1
for a light off the frame); `length` (0-1), `strength` (0-2), `decay` (0.5-1), `shafts` (how broken the light
is into beams, 0-1), `disc` (the light's size), `color`, `drift` (the light sways a little; 0 holds it), `in`,
`keys` (x, y, length, strength, decay, shafts), `scale` (default 0.5). The look draws its own dark air (light
needs darkness to show), from `--bg`, or from `--fg` on a light theme. Fallback: a still CSS glow and beams
behind the sharp shape.

```html
<div data-st="god-rays" data-text="Northlight" data-in="1.2"></div>
<div data-st="god-rays" data-logo="media/mark.png" data-preset="spotlight"
     data-keys='[{"at":0,"x":0.2},{"at":0.3,"dur":2.5,"x":0.55,"ease":"sine.inOut"}]'></div>
```

**marble**: veined stone or marbled paper that flows slowly, tinted by the theme. Smooth gradient noise (a small
tileable texture made once in JS, so a CPU renderer pays one lookup per octave) bends the plane twice over, and
the bent plane is drawn as stone (a cloudy tone, a network of veins, some bold and some a thread, hairlines and a
soft halo) or as paper (stripes of the theme's colours combed into each other). Use it under a title, a quote or
an end card for an editorial or premium feel; `ink` is loud: put text on it on a plate. `preset` `auto`
(default: `carrara` on a light ground, `nero` on a dark one), `carrara` (white stone, grey veins with a trace
of `--accent-2`), `nero` (dark stone, light veins with a trace of `--accent`), `ink` (stripes of `--accent` and
`--accent-2` with a fine line on the ground); `zoom` (larger is finer), `angle` (the main direction of the veins
or stripes), `turbulence` (0-2), `veins` (0-1.5), `speed` (1 = a slow flow; 0 a still stone), `sheen` (0-1),
`colors` (stone, vein, second vein; for `ink` up to four stripe colours), `keys` (zoom, turbulence, veins,
sheen), `scale` (default 0.75). Fallback: the look's first frame, worked out once in JS at a quarter of the size.

```html
<div data-st="marble"><blockquote class="t-display">Measure twice.</blockquote></div>
<div data-st="marble" data-preset="ink" data-speed="1.5"></div>
```

**metaballs**: gooey blobs in the accent that merge and split. Each ball adds to a field and the blobs are
drawn where it passes 1, with an edge a pixel soft at any size; they are shaded like soft candy (a dome, a key
light, a crisp highlight, a rim lit in `--accent-2`), on a transparent canvas over the scene's ground, with a
soft glow on a dark ground and a soft shadow on a light one. Use it for playful beats (three ideas merging into
one, a number that splits), a playful ground, or a gooey wipe over a cut. `preset` `merge` (default: satellites
that gather into a central blob and part again, together), `lava` (blobs rising and sinking across the frame),
`wipe` (a gooey band that crosses the frame and covers all of it in the middle of its run, at least from
`at + 0.46 * dur` to `at + 0.54 * dur`: put it in a layer above both scenes with the cut at `at + dur / 2`); `count` (3-12), `size` (the main blob's
radius, fraction of the frame height), `x`, `y`, `spread` (how far the satellites travel; key it to 0 to merge
on a beat), `speed`, `gloss` (0 flat - 1 candy), `glow` (0-1), `colors` (a comma list), `from` (wipe:
`left|right|top|bottom`), `dur` (wipe: seconds, default 1.2), `in` (seconds to grow in, with a small
overshoot), `keys` (x, y, size, spread, gloss, glow), `scale` (default 0.75). Fallback: the same blobs traced
on a 2D canvas on every frame (flat colour, crisp edge), so they still move.

```html
<div data-st="metaballs" data-x="0.68" data-in="0.6" data-keys='[{"at":2.2,"dur":0.8,"spread":0,"ease":"power3.inOut"}]'></div>
<div class="layer" data-start="4.4" data-dur="1.2" style="z-index:50">
  <div data-st="metaballs" data-preset="wipe" data-dur="1.2" data-from="left"></div>
</div>
```

## 8. Themes (runtime/themes)

`neutral` (light product), `bold` (loud launch), `editorial` (magazine, calm), `neon`
(night tech), `paper` (hand-made explainer), `terminal` (developer console). One `<link>` each.
Token contract: palette `--bg --fg --muted --surface --surface-2 --border --accent --accent-2
--accent-ink --good --bad --shadow`; type `--font-display --font-body --font-mono --font-hand
--weight-display --weight-body --tracking-display --leading-display --case-display`; shape/space
`--radius --radius-lg --stroke --space-1..4 --safe-x --safe-y`; motion `--motion-energy
--dur-in --dur-out --dur-beat --stagger --ease-in --ease-out --ease-move --ease-emph`; captions
`--cap-*`; texture `--grain --glow`. Override any token on `:root` or a scene for a brand.
Layout classes from `base.css`: `.stage .scene .layer .safe .center .stack .row`, type
`.t-hero .t-display .t-title .t-sub .t-body .t-label .t-mono .t-num`, `.accent .muted .surface
.glow .vignette`. Fonts are local files (Fontsource packages); each theme loads only its own
families, `themes/fonts.css` loads them all, `themes/fonts/noto-sans-jp.css` adds Japanese.

## 9. Writing your own component

```js
import { define, seg, ease } from '/_st/components/index.js';
export const Badge = define({
  name: 'badge', defaults: { at: 0, text: 'NEW' },
  setup(el, o) {                    // runs once, fonts loaded, clip visible
    el.textContent = o.text;
    const E = ease('spring(0.4,0.6)');
    return { duration: 0.5, update(lt) { el.style.transform = `scale(${E(seg(lt, 0, 0.5))})`; } };
  },
});
```
Rules: compute everything from `lt` (local seconds); no `setTimeout`, CSS transitions or
accumulators; animate `transform`, `opacity`, `filter`, `clip-path`; measure in `setup` only.
Mounting: `<div data-st="badge" data-text="v2">` elements are mounted as soon as `define()` runs, even
when the page module defines the component after `index.js` mounted the rest; or call
`Badge('#el', {...})` yourself. A component's DOM is built in `setup`, which runs after CSS and fonts
load, not when the factory returns: `const c = LowerThird(el, {...}); await c.ready;` before touching
its inner elements (`el.querySelector('.st-lt-role')` is null until then).

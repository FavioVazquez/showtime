# Film API: canvas films with `Film` (runtime/film.js)

Read this when you are building or editing a canvas film (`showtime new film`, `showtime new tutorial`, or any
project that loads `/_st/film.js`): explainers, metaphors, data stories, procedural product walkthroughs,
kinetic type. For HTML/CSS scenes, read the DOM component references instead. For music and sound, read
`synth-score.md`.

A canvas film is one `<canvas>` redrawn from scratch for every frame by `scenes(T, g, F)`, where `T` is the
time in seconds. The renderer seeks to each frame time in order, so the picture has to be a **pure
function of T**. The same `T` must always give the same pixels, whatever frame was drawn before.

---

## Essentials

- Draw the whole frame in `scenes(T, g, F)` as a pure function of `T`: no state between frames (`x += v`,
  pushing to arrays), no unseeded randomness or clocks; use `F.rng(seed)`, `F.hash`, `F.noise` (§11)
- Start with `Film.start({look, design, scenes, fonts, images, score, acts})`; `design: [1920, 1080]` for 16:9,
  `[1080, 1920]` for 9:16. `showtime.json` wins for size, fps and duration (§1, §2)
- Derive every progress from T: `F.seg(T, a, b, ease)` (0..1), `F.win(T, a, b)` (visibility; 0 at exactly `b`,
  so end it after the duration for the last frame), `F.tween`, `F.kf`, `F.stagger`, `F.springTo`, `F.timeline`,
  `F.beats` (§3, §11)
- Split scenes with `F.sequence(T, [{t0, t1, draw, in}])`. Transitions are centred on the cut: put the whoosh
  or downbeat exactly on `t0`; use one or two transition types, `dip` only for chapter breaks (§4)
- Keep every cut, click and hit time in one cue table (`cues.js`) shared by `scenes.js` and `score.js` (§11)
- Text: `F.text`, `F.reveal` (by word or line; per-character only for 1-2 word titles), `F.typewriter`,
  `F.counter`. Minimum 36 px body and 76 px or more for headlines in 1920x1080 design units (§5)
- Never put arrows, `⌘`, `✓` or other symbols in text: draw them with `F.glyph` (`F.keycap`/`F.keyCombo`
  do it for you) (§5)
- Mark UI-mockup detail with `F.decor(() => ...)` or `{decor: true}`, never anything the viewer must read (§5)
- Fonts are files, never system fonts: link the Fontsource CSS from `/_lib/` and list the weights in
  `Film.start({fonts})`. Declare images in `Film.start({images})` or `F.image()` at setup, not in
  `scenes()` (§9)
- Wrap your own `g.globalAlpha`, `g.filter`, transform or clip changes in `g.save()`/`g.restore()`;
  `g.filter = 'blur(...)'` is slow at 1080p, use it for a few elements only (§11)
- First motion by 0.1-0.3 s, hero on screen by 0.5 s, never open on a black frame, leave `fadeIn` at 0 (§2, §3)
- Entrances decelerate; exits accelerate and run 20-30 % faster; no overshooting springs on blocks of text (§3)
- Walkthroughs: name UI parts once with `F.rects`, then `F.cursorPath`, `F.clickZoom`, `F.camera` +
  `F.withCamera`, `F.fold` for UI state; draw step titles, keycaps and captions after `withCamera` (§8)
- Charts (`F.bars`, `F.lineChart`): one insight per state, the headline states the takeaway, hold 2-3 s (§7)
- Animated grain (`grainFps`) is incompressible: only when the film look is the point, and warn about size (§10)
- Vertical films: author with `design: [1080, 1920]`, text inside x 64-916, y 220-1440 (§11)
- Commands: `showtime render <dir>` (`--preview` for a 720p draft), `showtime preview <dir>`,
  `showtime snap <dir> --at 2,4.5`, `showtime check <dir>`, `showtime score <dir>` (§1, §12)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. Minimal film | 62-86 |
| 2. Film.start(options) | 88-113 |
| 3. Time: progress, windows, keyframes | 115-161 |
| 4. Scenes and transitions | 163-187 |
| 5. Text | 189-227 |
| 6. Shapes, UI pieces and diagrams | 229-257 |
| 7. Particles, charts, frames and images | 259-286 |
| 8. Camera and tutorials | 288-353 |
| 9. Fonts, images and cross-platform rules | 355-367 |
| 10. Looks and file size | 369-386 |
| 11. The pure-function-of-T rules (and the pitfalls they prevent) | 388-411 |
| 12. Recipes | 413-465 |

## 1. Minimal film

```html
<!doctype html>
<html><head>
  <meta charset="utf-8"><title>My film</title>
  <link rel="stylesheet" href="/_lib/@fontsource-variable/inter/index.css">
  <script src="/_st/stage.js"></script>
  <script src="/_st/film.js"></script>
  <script src="/_st/synth.js"></script>   <!-- only if there is a score -->
</head><body><script>
Film.start({
  look: 'dark',
  design: [1920, 1080],
  scenes(T, g, F) {
    F.reveal('Every frame is a function of time.', F.W / 2, 540, F.seg(T, 0.2, 1.2),
      { size: 96, weight: 800, align: 'center' });
  },
});
</script></body></html>
```

`showtime.json` sets the output size, fps and duration (`{"width": 1920, "height": 1080, "fps": 30,
"duration": 8}`). Render with `showtime render <dir>` (add `--preview` for a quick 720p draft). Use
`showtime preview <dir>` to scrub it in a browser, and `showtime score <dir>` to hear only the music.

## 2. `Film.start(options)`

| option | default | meaning |
|---|---|---|
| `scenes(T, g, F)` | required | Draws the whole frame. `g` is the 2D context in design units. `F` is `Film`. |
| `design` | output size | `[w, h]` or `{width, height, fit}`. Author in these units; `fit: 'contain'` (default) or `'cover'` scales them to the output. Use `[1920, 1080]` for 16:9 and `[1080, 1920]` for 9:16. |
| `look` | `'dark'` | `'dark' \| 'paper' \| 'blueprint' \| 'film' \| 'neon' \| 'clean'`, an override object `{base: 'paper', grain: 0.04, vignette: 0.3, dust: 0, leak: 0, grainFps: 0, grainSize: 1, weave: 0, labels: false, backdrop: fn, overlay: fn}`, or a function `(T, g, F) => {}` used as the backdrop. |
| `palette` | from the look | Overrides any of `bg bg2 ink muted faint accent accent2 accent3 good warn bad panel panel2 line shadow`. Read them back as `F.pal.accent` etc. |
| `fonts` | Inter 400/600/800 | Fonts to load before frame 0: CSS font strings (`'700 1em "Inter Variable"'`) or `{family, src, weight, style}` for a font file in the project. The page must also link the font's CSS (see §9). |
| `fontFamilies` | | Remap the families used by `family:` keys: `{sans: '"Geist Variable"', mono: ...}`. |
| `images` | | `{logo: 'assets/logo.png'}` preloads the images; use them as `F.img.logo`. |
| `acts` (or `chapters`) | | `[[0, 'Title'], [3, 'Data']]` (also `{t, label}` or `{s, label}`). Draws small act labels when `look.labels` is true. `showtime score` uses these as report sections, and an HTML export uses them as chapters: scrubber ticks, the chapter menu, keys 1-9 and `#chapter=` links. showtime.json `"chapters"` wins over them. |
| `subtitle`, `kicker` | | Lines for the HTML export's start card: a subtitle under the title, and a small line above it (a series and episode). showtime.json `"subtitle"`/`"kicker"` win. |
| `fadeIn`, `fadeOut`, `fadeColor` | 0, 0, `#000` | Global fades in seconds. A good hook starts moving on frame 1, so leave `fadeIn` at 0 unless you mean it. |
| `score` | | A `Synth.score(...)` function, stored as `ST.score` and rendered offline to WAV. |
| `width`, `height`, `fps`, `duration`, `background` | | Page-level fallbacks. `showtime.json` wins for any key it sets. |
| `pixelRatio` | device ratio | Canvas backing scale (the renderer handles `--scale`). |

After `start`, these are available: `F.W`/`F.H` (the design size), `F.u` (`min(W, H) / 1080`, a unit for
responsive sizes), `F.cx`/`F.cy`, `F.duration`, `F.fps`, `F.T` (the current frame time), `F.pal`, `F.g`
(the current context), `F.canvas`.

The frame is composed in this order: backdrop, then `scenes()` in design space (clean state, wrapped in
save/restore), then dust, light leak, vignette, `overlay`, grain, act labels, and finally fades. A throw in
`scenes()` paints a red error bar with the message. In render mode it also fails the render, reporting the
exact T.

## 3. Time: progress, windows, keyframes

Every animated helper takes a **progress** `p` in 0..1 (or an **age** in seconds for one-shot effects).
Derive it from T:

```js
F.seg(T, a, b, ease?)            // 0 before a, 1 after b, eased in between
F.win(T, a, b, fin=0.3, fout)    // visibility: fades in over fin after a, out over fout before b
F.tween(T, t0, dur, from, to, ease='outCubic')     // numbers, arrays, colors, flat objects
F.kf(T, [[0, 0], [1.2, 300, 'outExpo'], [3, 280]]) // keyframes; the ease on a key shapes the move INTO it
F.stagger(T, i, n, t0, {each: 0.06, dur: 0.5, total: 0.5, order: 'start'|'end'|'center'|'edges'})
F.split(p, i, n, overlap?)       // stagger inside one progress value
F.springTo(T, t0, from, to, {response: 0.5, damping: 0.8})   // physical spring released at t0 (may overshoot)
```

Named sections:

```js
var TL = F.timeline({ title: [0, 3], metaphor: [3, 6], data: [6, 9], end: [9, 12] });
TL.p('data', T, 'outCubic'); TL.local('data', T); TL.on('data', T); TL.at(T);  // -> 'data'
```

Musical grid for picture (the same numbers as `m.grid` in the score):

```js
var B = F.beats({ bpm: 96, offset: 0 });
B.t(2, 1);          // time of bar 2, beat 1 (both 0-based)
B.pulse(T, 0.15);   // 1 on every beat, decaying: drive a subtle scale or glow
B.snap(4.93);       // nearest beat time
```

**Easing** (`F.E.*`, or pass a name string anywhere an ease is accepted): `linear`, `in/out/inOut` +
`Sine Quad Cubic Quart Expo Circ Back`, plus house curves `enter` (decelerate), `exit` (accelerate), `move`
(standard), `reveal` (premium expo-like), `camera` (gentle in-out), and springs `smooth` (no overshoot),
`snappy` (slight overshoot) and `bouncy` (playful). Build custom curves with `F.bezier(x1, y1, x2, y2)` or
`F.spring(response, damping)`. A spring ease has `.duration`, its natural settle time. Size its window with
that value; don't squeeze the spring into a shorter one.

Motion rules that make a film look premium:
- Entrances decelerate (`reveal`, `outExpo`, `enter`); exits accelerate (`exit`) and run 20-30 % faster.
  Camera moves use `camera`/`inOutSine`. Keep springs with overshoot for small, playful elements, never
  for blocks of text.
- Durations: micro 0.1-0.2 s, element entrance 0.3-0.6 s, big moves 0.5-0.8 s, camera pushes 1-4 s.
  Stagger groups by 30-60 ms and keep the whole group under 0.5 s.
- Something should change every 2-4 s. After a settle, hold at least 0.5 s, and 1.5-2.5 s for anything the
  viewer must read.
- Put the first motion by 0.1-0.3 s and get the hero on screen by 0.5 s. Never open on a black frame.

## 4. Scenes and transitions

```js
F.sequence(T, [
  { t0: 0, t1: 3, draw: title },
  { t0: 3, t1: 6, draw: metaphor, in: { type: 'wipe', dur: 0.5, dir: 'left' } },
  { t0: 6, t1: 9, draw: data, in: 'cut' },
  { t0: 9, t1: 12, draw: endCard, in: { type: 'fade', dur: 0.6 } },
]);
function title(local, p, T) { /* local = T - t0, p = progress through the scene */ }
```

Transitions are **centred on the cut**: a 0.6 s fade into a scene that starts at 3.0 s runs from 2.7 to
3.3 s, with both scenes drawn in the overlap. Put the whoosh peak or the downbeat exactly on `t0`. The
types are `cut`, `fade`, `dip` (through `color`: the outgoing scene is drawn until the cut and the
incoming one after it, never both), `wipe` and `push` (`dir`: left, right, up, down), `zoom`,
`blur` and `iris`. Hard cuts on the beat carry most premium work. Use one or two transition types per film,
and keep `dip` for chapter breaks. Any transition takes `blur` (px at 1080p): `in: { type: 'zoom', dur: 0.36,
blur: 14 }` pulls focus on the incoming scene and softens the outgoing one, so a bright flat shape in the
new scene never reads as a hard-edged box over the old one. To avoid a double exposure in a dissolve,
fade the outgoing scene's text before the window starts.

A label that must move across a line or another label (above the pipe to below it) should not be dragged
through it: `var r = F.relocate(T, 12.0, 0.5, [x0, y0], [x1, y1])` gives `{x, y, alpha}` that dips out
mid-move and comes back.

## 5. Text

Font families are keys of `F.FONTS`: `sans` (Inter), `display` (Space Grotesk), `serif` (Instrument
Serif), `mono` (JetBrains Mono). You can also pass any CSS family string.

```js
F.text(str, x, y, {size, weight, family, italic, color, alpha, align: 'left'|'center'|'right',
  baseline: 'alphabetic'|'middle'|'top', tracking: -0.02 /* em */, maxWidth /* shrink to fit */,
  stroke, strokeWidth, shadow: {blur, x, y, color} | true, decor /* UI-mockup detail */})   // -> width
F.decor(() => { /* draw a mock app window: its small labels are detail, not copy */ })
F.measure(str, opts) ; F.fit(str, maxWidth, opts) /* -> size */ ; F.wrap(str, maxWidth, opts) /* -> lines */
F.paragraph(str, x, y, {width, lineHeight: 1.35, ...text opts})     // -> {lines, height}
F.reveal(str, x, y, p, {by: 'line'|'word'|'char', effect: 'rise'|'fade'|'blur'|'scale'|'slide',
  width /* wrap */, lineHeight: 1.12, overlap, ease: 'reveal', exit: 0..1, ...text opts})
F.typewriter(str, x, y, p, {caret: true, caretColor, blink: 1.0, lineHeight, ...text opts})
F.counter(value, x, y, p, {from: 0, decimals: 0, prefix, suffix, suffixSize, suffixColor, separator: ',',
  format(v), ...text opts})     // fixed-width digits: the number never jitters while it counts
```

`'rise'` (the default for words and lines) slides each unit up from behind an invisible mask, which is
the clean editorial reveal. `'blur'` is the modern soft-focus entrance. Animate readable text by word or
line; per-character reveals suit only 1-2 word hero titles. Minimum sizes at 1080p are 36 px for body and
76 px or more for headlines (in 1920x1080 design units).

**Decor:** small text inside a UI mockup (menu items in a mock app window, a thumbnail's caption) is detail,
not copy. Draw it inside `F.decor(() => ...)` or pass `{decor: true}` to one `F.text` call, and
`showtime check` reports its size, contrast and overlaps as notes instead of warnings (the canvas twin of the
DOM's `data-st-decor`). Headlines, captions, numbers and anything the viewer must read are never decor.

**Symbols:** the bundled fonts contain no arrows, `⌘`, `⇧`, `⌥`, `⌃`, `↵`, `⌫`, `⇥` or `✓`. Anything that
falls back to a system font looks different on macOS, Windows and Linux, so `F.text` warns when it sees
them. Draw them as vectors instead:

```js
F.glyph('cmd' | 'shift' | 'option' | 'ctrl' | 'return' | 'left' | 'right' | 'up' | 'down' | 'backspace' |
        'tab' | 'check' | 'close' | 'plus' | '⌘' | '→' ..., x, y, size, {color, width, alpha})
```

`F.keycap` and `F.keyCombo` do this automatically for symbol labels.

## 6. Shapes, UI pieces and diagrams

```js
F.rr(x, y, w, h, r | [tl, tr, br, bl])              // path only
F.box(x, y, w, h, r, {fill, stroke, lineWidth, dash, alpha, shadow, dims /* a scrim or modal backdrop: check does not judge text under it */})
F.circle(x, y, r, {fill, stroke, lineWidth, alpha, shadow})
F.line(x1, y1, x2, y2, {color, width, dash, cap, alpha})
F.glow(x, y, radius, color, alpha=0.35)             // soft radial light
F.grid({step: 60, alpha: 0.08, dots, rect})
F.pill(label, x, y, {size, fill, color, stroke, icon /* dot color */, alpha})     // centred; -> {w, h}
F.card(x, y, w, h, {title, body, fill, stroke, radius: 18, accent /* left bar */, shadow, alpha})
F.keycap(label, x, y, {size: 64, press: 0..1, dark, color, alpha})                // -> width
F.keyCombo(['⌘', 'K'], x, y, {size, p /* staggered pop-in */, press /* 0..1 or per key [] */, plus: true})
F.cursor(x, y, {kind: 'arrow'|'dot'|'ibeam', scale: 1.6, press: 0..1, color})     // (x, y) is the tip
F.ripple(x, y, age, {radius: 44, dur: 0.55, color, width})
F.arrow(x1, y1, x2, y2, {p, curve: -1..1, color, width, head, dash})
F.callout(anchorX, anchorY, boxX, boxY, 'Label', {p, sub, size, color, fill, align})
F.spotlight({x, y, w, h, r} | {cx, cy, radius}, {p, dim: 0.6, pad, ring: color | false})
F.path(points, p, {smooth, color, width, dash, fill /* area */, baseY, head /* pen dot */, glow})  // -> pen [x, y]
```

Callouts, captions, the step band and spotlights are recorded for `showtime check`: a callout card over
text drawn before it is a `text_overlap` ("hidden under the callout"), a card that points off the frame
or runs off it is `callout_off_target`, and text a spotlight (or an `F.box` with `dims`) darkens on
purpose is not judged for contrast. Put a card in empty space, or light its target with a spotlight so
the card can rest on the dimmed rest of the picture.

`F.path` draws by **length**, so progress looks even along curves. Use it for signatures, route lines,
underlines, rings, connectors and the "tangle becomes a straight line" style of metaphor.

## 7. Particles, charts, frames and images

```js
F.burst(age, {x, y, count: 28, seed, speed: [300, 800], angle, spread, gravity: 1200, life: 1.2,
  size, colors, shape: 'circle'|'rect'|'spark'})       // closed-form; fire it on a cause (click, settle)
F.field(T, {count: 60, seed, rect, speed: [vx, vy], size, color, alpha, twinkle})  // ambient drift

F.bars(data, {x, y, w, h}, p, {labels, highlight: i | [i], colors, color, max, gap, radius, values,
  decimals, prefix, suffix, labelSize, valueSize, horizontal, baseline})
F.lineChart([series...], rect, p, {min, max, highlight, colors, width, fill, dots, grid: 3, labels,
  endLabel: true | fn, smooth})                          // -> pen positions
F.ring(x, y, radius, frac, {width, color, track, label})
F.counter(...)   // see §5

F.browser({x, y, w, h}, {url, theme: 'light'|'dark', page, radius, bar, border}, (g, w, h) => {...})
F.phone(rect, {color, screen}, (g, w, h) => {...})
F.laptop(rect, {color, screen, base}, (g, w, h) => {...})
// the content callback draws in LOCAL coordinates (0, 0 = top-left of the screen), clipped

F.image(src)                                  // -> handle {img, ready, w, h}; call at setup, not in scenes
F.drawImage(handle | 'name' | src, x, y, w, h, {fit: 'cover'|'contain'|'fill', align: [0.5, 0.5],
  zoom, pan: [dx, dy], radius, alpha, shadow})
F.kenBurns(img, rect, p, {from: {zoom: 1, pan: [0, 0]}, to: {zoom: 1.12, pan: [-0.02, -0.015]}, ease})
```

Chart rules: one insight per chart state. The headline states the takeaway ("Build time fell 74%"), not
the metric name. Highlight one series in the accent color and mute the rest. Hold the final state for
2-3 s. Label illustrative numbers as illustrative on screen.

## 8. Camera and tutorials

```js
var cam = F.camera(T, [[0, 960, 540, 1], [2, 1400, 300, 1.8, 'camera'], [4, 960, 540, 1]]); // [t, x, y, zoom, ease?, rot?]
F.withCamera(cam, function () { /* world drawing */ }, { shake: F.shake(T, 6, { freq: 1.3, seed: 2 }) });
F.focus({x, y, w, h}, {pad: 0.15, maxZoom: 2.8})      // camera that frames a rect (clamped to the frame)
F.camPoint(cam, x, y)                                 // world point -> screen point (for overlays)
// named targets and clamping: keys may name a UI rect; the view never leaves the bounds
F.camera(T, [[0, 960, 540, 1], [2, 'saveBtn', 1.8], [4, 'sidebar']], { ui: ui, clamp: WIN })   // clamp: true = the frame
F.clampCam(cam, WIN)                                  // keep any camera inside a rect (a wider view is centred on it)
```

Zoom interpolates geometrically, so a 1x to 2x move feels even. Draw overlays that must stay put, such as
step titles, keycaps, captions and the step bar, **after** `withCamera` returns, in screen space.

Tutorial helpers (see `templates/tutorial`, and `templates/series` for a whole series built on them):

```js
var cur = F.cursorPath(T, [[0, 900, 600], [2.2, 1400, 180, {click: true}], [5, 1100, 500]]);
// -> {x, y, press, clickAge, click: {x, y, t}}; the pointer arrives 0.12 s early and clicks exactly at t
F.ripple(cur.click.x, cur.click.y, cur.clickAge); F.cursor(cur.x, cur.y, {press: cur.press, tag: 'Right-click'});
F.pulse({x, y, w, h, r: 12}, T, t0, {t1, period: 0.9})   // attention rings around a target (hover, "look here")
F.clickZoom(T, [{t: 2.2, x: 1400, y: 180}], {zoom: 1.8, lead: 0.45, hold: 1.4})  // auto camera per click
F.stepTitle(1, 'Create a project', F.win(T, 0.3, 4.5), {x, y, size, sub})
F.stepBar(['Create', 'Name', 'Render'], currentFloat, {x, y, w, size})
F.caption('Lower-third caption', F.win(T, 3, 6), {y, size, maxWidth})
F.actLabel('Chapter two', p)
F.captions(T, [[3, 6, 'Click New project'], [6.2, 9, 'Name it']], {y, size, maxWidth, fill})   // caption track
F.stepBand(T, [[4, 'Find the board'], [8.6, 'Add a card']], {end: 29, h: 72})  // top band (opaque): badge, title, STEP n OF N, segments
```

**Named UI rects.** Draw the product once, describe where its parts are once, and point everything at
names instead of copying coordinates between the cursor, the camera, spotlights and callouts:

```js
var ui = F.rects({
  newBtn: [1240, 34, 220, 58],                                    // x, y, w, h in page coordinates
  row: function (i) { return [320, 400 + i * 86, 1140, 66]; },    // a family: ui.rect('row', 2) or 'row:2'
}, { origin: [WIN.x, WIN.y + BAR] });                             // page -> world (the window's content area)
ui.rect('newBtn') / ui.local('newBtn') / ui.center('row:2') / ui.point('newBtn', 'right' | 'tl' | [0.2, 0.5])
var cur = F.cursorPath(T, [[0, 900, 600], [2.2, 'newBtn', { click: true }], [4, 'row:2', { at: 'left', dx: 20 }]], { ui: ui });
var r = ui.rect('newBtn'); F.spotlight(r, { p: F.win(T, 3, 5) }); F.callout.apply(null, ui.point('newBtn', 'right').concat([1500, 300, 'New project']));
```

An unknown name throws with the list of known ones. When the layout depends on state (a list that grows),
build the rects from the state each frame (`kitRects(st)`), as the series kit does.

**UI state from events** (`F.fold`, alias `F.stateAt`): the state of the product at time T, folded from an
event list, so every frame is still a pure function of T:

```js
var st = F.fold(T, { stop: 3, open: false, draft: '' }, [
  [CUE.click1, { open: true }],                                      // merge a patch
  [CUE.next,   function (s) { s.stop += 1; }],                       // or change the copy
  [CUE.type,   function (s, dt) { s.draft = 'Launch'.slice(0, Math.floor(dt * 12)); }],   // dt = T - event time
]);
```

The initial object is never changed (each call works on a copy); events may be listed in any order.

Walkthrough craft:
- Move the camera before the action: arrive 0.15-0.4 s before a click or typing.
- Zoom 1.5-2x for clicks and typing, and hold 1.2 s or more.
- Leave at least 1.8 s between separate zooms, and zoom out after about 2.5 s idle.
- Put keycaps bottom-centre, 44-56 px or more tall at 1080p.
- Keep typing fast (10-14 characters per second).

## 9. Fonts, images and cross-platform rules

- **Fonts are files, never system fonts.** Link the Fontsource CSS served from `/_lib/` (installed by
  setup), for example `/_lib/@fontsource-variable/inter/index.css`,
  `/_lib/@fontsource-variable/jetbrains-mono/index.css`, `/_lib/@fontsource/instrument-serif/index.css`
  (italic: `400-italic.css`), `/_lib/@fontsource-variable/space-grotesk/index.css`. List the weights you
  use in `Film.start({fonts})`: canvas text does not trigger font loading by itself, and the renderer waits
  for these. Font files in the project also work: `fonts: [{family: 'Brand', src: 'fonts/brand.woff2'}]`.
- Symbols are vectors (§5). Emoji differ per OS as well: render them as images (`showtime assets emoji`).
- Images: list them in `Film.start({images})` or call `F.image()` at setup so the renderer waits for them.
  An image first requested inside `scenes()` is missing from early frames, and a warning says so.
- Nothing in film.js depends on the OS. The same page renders the same frame on macOS, Windows and Linux,
  apart from tiny anti-aliasing differences between GPU drivers.

## 10. Looks and file size

| look | feel | grain (static unless noted) | extras |
|---|---|---|---|
| `dark` | product, dev tools | 0.04 | accent glow from the top |
| `paper` | editorial explainer | 0.07 | warm radial paper, light dust |
| `blueprint` | technical, architecture | 0.05 | grid + registration marks |
| `film` | cinematic, nostalgic | 0.07 **animated 12 fps** | flicker, dust, light leaks, gate weave |
| `neon` | launch hype, gaming | 0.05 | magenta/cyan glows |
| `clean` | UI-first, corporate | 0 | flat background |

Static grain is a texture: it breaks up gradient banding and costs almost no bitrate. **Animated grain is
incompressible noise.** Measured on the 12 s film template at 1280x720, the file was 1.4 MB with no grain,
3.3 MB with static grain, 17 MB at 12 fps and 43 MB at 24 fps. Turn it on (`grainFps: 12`) only when the
film look is the point, and warn the user about file size. Even static grain and dust cost a lot at the
default CRF 16 with jpeg capture on long films (a 45 s film look was 82 MB): for a size budget, lower grain
and dust (0.03 / 0.10), set `"render": {"crf": 22, "format": "png"}` in showtime.json, or make a capped
copy (`showtime deliver exports <file> --targets original --max-mb 20`).

## 11. The pure-function-of-T rules (and the pitfalls they prevent)

1. **No state between frames.** Never do `x += v` or push to arrays in `scenes()`. Compute positions in
   closed form from T (`F.burst`, `F.field` and `F.springTo` do exactly that). Frames are rendered by
   several browsers in parallel, each starting mid-film.
2. **No unseeded randomness or clocks.** Use `F.rng(seed)` (create it inside the function, so every frame
   replays the same sequence), `F.hash(i)`, `F.noise(x, seed)`, `F.noise2`, `F.fbm`. For jitter, hash a
   quantised time: `F.hash(Math.floor(T * 12))`.
3. **One cue table.** Keep every cut, click and hit time in one object (`cues.js` in the templates) shared
   by `scenes.js` and `score.js`. Then a cut and its sound can never drift apart.
4. **Build the end state first**, then animate into it. Layout constants come from the design size, not
   from measuring the canvas mid-animation.
5. **Canvas state leaks inside a frame.** Helpers save and restore for you. When you change `g.globalAlpha`,
   `g.filter`, transforms or clips yourself, wrap the change in `g.save()` / `g.restore()`. `F.*` helpers
   multiply into the current alpha, so fading a group works: `g.save(); g.globalAlpha *= a; ...; g.restore()`.
6. **`g.filter = 'blur(...)'` is slow** at 1080p. Use it for a few elements or short transitions, not
   full-frame on every frame.
7. **Fonts and images must be declared** (§9). Otherwise the first frames render with fallbacks.
8. **Half-open windows**: `F.win(T, a, b)` is 0 at exactly `b`. For something that must remain on the last
   frame, end its window after the film's duration.
9. **Symbols in text** fall back to OS fonts: use `F.glyph` (§5).
10. **Design size vs aspect.** `design: [1920, 1080]` rendered at 9:16 letterboxes the content inside the
    look's backdrop. For vertical films, author with `design: [1080, 1920]` and keep text inside the vertical
    safe box (x 64-916, y 220-1440).

## 12. Recipes

A tutorial **series** (several episodes that share their look, chrome, sound motif and product UI) is a
pattern of its own: `showtime new series <dir>`, then read `series.md`.

Typewriter with matching key sounds (picture and score share `CUE`):

```js
// scenes.js
F.typewriter(CUE.text, 400, 500, F.seg(T, CUE.typeStart, CUE.typeStart + CUE.text.length / CUE.cps), {family: 'mono', size: 40});
// score.js
m.typing(CUE.typeStart, CUE.text.length, { cps: CUE.cps });   // key i sounds when character i appears
```

Number that lands on a beat:

```js
var B = F.beats({ bpm: 100 });
F.counter(74, 1600, 640, F.seg(T, B.t(3), B.t(4), 'outCubic'), { suffix: '%', size: 200, weight: 800, align: 'center' });
```

Zoom-through to the next scene (fast push, cut hidden in the blur):

```js
var z = F.seg(T, 5.6, 6.0, 'inExpo');
F.withCamera({ x: 1400, y: 300, zoom: F.lerp(1, 6, z) }, function () { drawScene1(T); });
```

Spotlight + callout on a UI element:

```js
F.spotlight({ x: 1200, y: 160, w: 260, h: 70, r: 12 }, { p: F.win(T, 4, 7), pad: 10 });
F.callout(1330, 230, 1500, 420, 'Click here', { p: F.seg(T, 4.2, 5), sub: 'creates a project' });
```

DOM layers over a film (a credit line, a map inset, a browser-frame): give them `data-start` /
`data-dur` like any clip. To time them from the voice, set those attributes from `CUE` / `VO` in a
classic script that runs while the page loads, after the cue table (the stage resolves clips when
the page is ready): `el.dataset.start = CUE.source; el.dataset.dur = CUE.card - CUE.source;`.

A WebGL shader transition (`ridged-burn`, `domain-warp` ...) inside a film: the film draws one canvas,
the shader needs two. Add a second `<canvas>` sized like the film's, register
`transition({from: secondCanvas, to: filmCanvas, type: 'ridged-burn', at, dur})`, and in an
`ST.onSeek` handler inside the window draw the outgoing scene into the second canvas (render the film
once with a flag that holds the outgoing scene, copy it with `drawImage`), then let the film draw the
normal frame. Both canvases are pure functions of T, so preview, snap, check and render agree.

Debugging: open the project with `showtime preview <dir>` and scrub. `showtime snap <dir> --at 2,4.5`
saves stills, and `showtime check <dir>` runs the pre-render QA. `Film.render(t)` redraws a frame from the
browser console. `Film.frameInfo()` returns what the last frame drew: every `F.text` call with its box in
output pixels, on-screen size, font, color and effective alpha. QA tools use it to check canvas text.
Text under a zoomed camera can sit partly off-canvas on purpose, so only boxes that intersect the frame
matter.

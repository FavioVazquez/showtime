# Stage API: the time contract for showtime pages

Read this when you write or debug a showtime page (`index.html` + `showtime.json`), add a
library (anime.js, Lottie, three.js, canvas, video) to a scene, or `showtime check` reports
a determinism, timing or seek problem.

## Essentials

- Every frame is a pure function of `t`: the renderer calls `ST.seek(t)` per frame and screenshots; the same
  `t` must give the same pixels in any order, on any machine (§ The one rule)
- `<script src="/_st/stage.js"></script>` is the first script in `<head>`; fonts and packages from `/_lib/`,
  fetched assets from `/_assets/`, the rest relative; nothing from the internet (§ Minimal page)
- `showtime.json`: `width`/`height` (even), `fps` (30), `duration`, `background`, `title`, `poster`, `audio`,
  `loudness` (-14 LUFS, -1 dBTP). It wins over `ST.config`; CLI flags win over both (§ Configuration)
- Clips: an element with `data-start` shows only inside `[start, end)`; `data-dur` or `data-end`; values
  `2.5`, `+0.5`, `#intro`, `#intro+0.3`. Visible clips get `data-active`, `--t` and `--p` (§ Clips)
- CSS and Web Animations in a clip run on the clip's clock (`animation-delay` from the clip start);
  `showtime retime` does not rescale `animation-delay`, check delays by hand after it (§ Clips)
- Time reveals to words from the `VO` table (`showtime voice cues voice/timeline.json -o voice/cues.js`),
  not typed numbers; run `voice cues` again after every re-voice (§ Clips)
- Draw anything else in `ST.onSeek((t, frame) => ...)`, returning nothing or a real `Promise`, never a library
  timeline. `ST.waitFor` for loading, `ST.rand(seed)`, `ST.noise`, `ST.progress`, `ST.ease.*` (§ API)
- Never call `ST.seek` or `ST.ready` from scene code (§ API, § Readiness)
- Libraries: create them paused and hand them over: `ST.anime(tl, {offset})`, `ST.lottie(anim, ...)`,
  `ST.three(renderer, scene, camera, fn)` with `preserveDrawingBuffer: true`, `ST.gsap` (§ API)
- Never: `setTimeout`/`setInterval` animation, class-toggled CSS `transition`, state between frames
  (`x += v`), `Math.random()` for layout, remote files, system fonts, symbols as text, animated GIFs,
  animating `left/top/width/height` instead of `transform` (§ Determinism)
- Motion blur on a snap beat: `data-st-blur` on the one element that moves (`"shutter 180; samples 8; threshold 6;
  max 50%"`, all optional) or `ST.blur(el, {pose})`; copies only on the fast frames, it lands sharp (§ Shutter blur)
- Footage: VP9/WebM made with `showtime footage trim in.mp4 --webm --no-audio -o media/clip.webm` (never bare
  ffmpeg), a proxy at the shown size; the page is always muted, sound goes in the `audio` mix (§ API)
- Emoji in text become images: install each once with `showtime assets emoji` (§ Determinism)
- Overlay pages for `render --alpha`: `"overlay": true` or `<body data-overlay>` (§ Configuration)
- `showtime check` recaptures frames after a delay and in another order to prove determinism; scrub in
  `showtime preview` (§ Determinism, § Preview mode)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| The one rule | 52-57 |
| Minimal page | 59-94 |
| Configuration | 96-112 |
| Clips: data-start / data-dur | 114-154 |
| API: Library helpers (built-in adapters), <video> in a page | 156-241 |
| Shutter blur: data-st-blur and ST.blur | 243-296 |
| Determinism: what the render mode does and what to avoid | 298-329 |
| Readiness | 331-339 |
| Preview mode | 341-353 |
| Scene transitions with shaders (layer protocol) | 355-361 |

## The one rule

**Every frame is a pure function of time `t` (seconds).** Nothing plays during a render: the
renderer calls `ST.seek(t)` for frame 0, 1, 2 ... and takes a screenshot after each seek. The
same page must produce the same pixels for the same `t`, whatever frame came before, on any
machine. Everything below is how to get there without thinking about it.

## Minimal page

```html
<!doctype html>
<html><head>
<script src="/_st/stage.js"></script>                       <!-- first script in <head> -->
<link rel="stylesheet" href="/_lib/@fontsource-variable/inter/index.css">
<style>
  body { font-family: 'Inter Variable'; color: #fff; }
  .scene { position: absolute; inset: 0; display: grid; place-items: center; }
  h1 { font-size: 9vmin; animation: rise .8s cubic-bezier(.2,.8,.2,1) .2s both; }
  @keyframes rise { from { opacity: 0; transform: translateY(4vmin); } }
</style></head>
<body>
  <section class="scene" id="intro" data-start="0" data-dur="3"><h1>Hello</h1></section>
  <section class="scene" id="next" data-start="#intro" data-dur="2"><h1>World</h1></section>
  <script>
    ST.onSeek((t) => { document.body.style.setProperty('--hue', String(200 + t * 20)); });
  </script>
</body></html>
```

`showtime.json` next to it:

```json
{ "width": 1920, "height": 1080, "fps": 30, "duration": 5, "background": "#0b0d12",
  "title": "Hello", "poster": 1.5, "audio": "audio/mix.json" }
```

- `/_st/...` is the showtime runtime, `/_lib/<package>/...` any installed npm package (animejs,
  three, lottie-web, d3, katex, roughjs, @fontsource...), `/_assets/...` files fetched by
  `showtime assets`. Everything else is relative to the project folder. Nothing is fetched from
  the internet during a render (requests are blocked and reported by `showtime check`).
- `vw`/`vh`/`vmin` are the stage size, so a page written with them works at 16:9, 9:16 and 1:1.
- If a page forgets the stage script, the server adds it, but put it first so the virtual clock
  is installed before any library reads the clock.

## Configuration

| Field | Meaning | Default |
|---|---|---|
| `width`, `height` | stage size in CSS px (even numbers) | 1920 x 1080 |
| `fps` | frames per second | 30 |
| `duration` | length in seconds; if missing: the latest clip end, else the longest finite CSS animation | required somewhere |
| `background` | colour behind everything (transparent with `--alpha`) | `#000` |
| `title` | used for the output folder name | folder name |
| `poster` | time (s) of the frame baked into frame 0 and saved as poster.jpg | none (auto-picked poster.jpg, not baked) |
| `audio` | a sound file, a mix spec (`audio/mix.json`), an inline `{"tracks": [...]}` or a list of files/tracks | none |
| `loudness` / `master` | loudness target (`-14`) or `{"lufs": -14, "true_peak": -1}` | -14 LUFS, -1 dBTP |
| `seed` | base seed for `Math.random` in render mode | 1 |
| `overlay` | the page is an overlay for `render --alpha` (lower thirds, step chips): gaps between its elements are intended, so `check` notes them instead of reporting `dead_air`; `<body data-overlay>` does the same. With `--alpha` the themes' scene and stage fills are transparent; a background a scene sets itself still paints | false |

`ST.config({...})` in the page sets the same fields. **showtime.json wins** when both set a
value (`showtime check` warns about the conflict); CLI flags (`--fps`, `--from/--to`) win over both.

## Clips: `data-start` / `data-dur`

Any element with `data-start` is a clip. It is shown (`display` restored) only inside its window
`[start, end)` and hidden otherwise; a clip that reaches the end of the video also owns the last
frame. The stage sets on each visible clip:

- attribute `data-active` (style entrances with `[data-active]` if you like)
- CSS variables `--t` (seconds since the clip started) and `--p` (0..1 through the clip), and on
  `:root`: `--st-t` (video time) and `--st-p` (0..1 through the video)

Outside its window a clip's `--t`/`--p` still depend only on the time: 0 before it starts, its last
frame's values after it ends. A transition that keeps the outgoing scene on screen therefore shows
the same frame however the video is seeked.

Time grammar for `data-start` and `data-end`:

| Value | Means |
|---|---|
| `2.5` | 2.5 s into the video |
| `+0.5` | 0.5 s after the parent clip starts (nesting) |
| `#intro` | when the clip with `id="intro"` ends |
| `#intro+0.3`, `#intro-0.2` | relative to that end (overlaps are fine) |

`data-dur` is a length in seconds; `data-end` is an alternative absolute end. No end means "until
the video ends". Add `data-keep` to hide with `visibility` instead of `display` (keeps layout, for
elements you measure). Bad values or circular references are reported by `showtime check`.

**CSS animations and Web Animations inside a clip run on the clip's clock**: `animation-delay:
.2s` means 0.2 s after the clip starts. The stage pauses every animation and sets its
`currentTime` on each seek, so `@keyframes` just work, including `infinite` loops. Put
`data-st-free` on an element to leave its animations alone (rarely needed). `showtime retime`
rescales `data-start`/`data-dur`/`data-at`, not `animation-delay`: after a retime, check delays by
hand.

**Reveals on a spoken word.** `showtime voice cues voice/timeline.json -o voice/cues.js` writes a
`VO` table (line and word times). Load it with a classic `<script>` and set times from it before the
page is ready, instead of typing numbers: `el.dataset.at = (VO.words.demo[3][1] - sceneStart).toFixed(3)`.
This holds for a voice that plays as one track (`--offset` = its start in the video); run `voice cues`
again after every re-voice. After `retime --from-voice`, which places each line in its scene, count
from the scene start: a word's time in its line (`VO.words.<line>[i][1] - VO.lines.<line>.start`)
plus the line's delay in the scene.

## API

| Call | What it does |
|---|---|
| `ST.onSeek(fn)` | `fn(t, frame)` runs on every seek, in registration order. Return nothing, or a real `Promise` for async work (e.g. a texture). Returns an `off()` function. |
| `ST.adapter(name, fn)` | same as `onSeek`, named (shown in errors and `ST.info().handlers`) |
| `ST.waitFor(promise, label?)` | before the first frame: delays readiness (data, images, models). Inside a seek handler: delays that frame's screenshot. |
| `ST.rand(seed)` | deterministic generator: `r()` in [0,1), `r.range(a,b)`, `r.int(a,b)`, `r.pick(arr)`, `r.sign()`. Seeds can be numbers or strings. |
| `ST.noise(x, seed)`, `ST.noise2(x, y, seed)` | smooth deterministic noise in [-1, 1] (drift, wobble, handheld camera) |
| `ST.progress(t, a, b, ease?)` | 0..1 position of `t` between `a` and `b`, optionally eased |
| `ST.ease.*` | `linear`, `in`/`out`/`inOut` + `Sine Quad Cubic Quart Expo Circ Back` (the same names as Film's `F.E`), `outElastic` |
| `ST.clamp(x, a, b)`, `ST.lerp(a, b, p)` | helpers |
| `ST.score = async (ctx, dest, info) => {...}` | optional score written in Web Audio: schedule everything from time 0 on `ctx` into `dest`. Rendered offline to a WAV by the renderer and played in sync by the preview player. `info = {duration, sampleRate, offline}` |
| `ST.config(obj)` | set/merge config (see above); returns the effective config |
| `ST.mode` | `'render'` (renderer, check, snap), `'preview'` (inside the player or a plain browser), `'player'` |
| `ST.t`, `ST.frame`, `ST.cfg` | current time, frame, config |
| `ST.questions` | showtime.json `"questions"` with times resolved (voice cues included): `[{id, t, think, resume, from, prompt, choices, answer, reply}]`, for a page that draws its own pause and think beat (`html-export.md` § Questions); `await ST.configReady()` first in a preview |
| `ST.info()` | size, fps, duration (and where it came from), frame count, clip count, handler names |
| `ST.clips()` | resolved clip windows `[{name, id, start, end}]`, frame-exact: a clip is on screen exactly while `t >= start && t < end` (a time written within 1 ms of a frame, like 1.9667 at 60 fps, is reported as that frame's time, as the stage shows it); `end` is `null` for a clip that runs to the end of the video. Gate canvas drawing on these, not on times typed again in the script |
| `ST.diag()` | what the runtime noticed: timer callbacks during playback, CSS transitions, video problems, handler errors |
| `ST.pace()` | how much the waits are scaled for this page: `{factor, frame_ms, seek_ms, seeks, ceiling, on}` (see Readiness) |
| `ST.seek(t)`, `ST.ready()` | used by the renderer and the player. **Never call them from scene code.** |

### Library helpers (built-in adapters)

```js
// anime.js v4: create paused, the stage seeks it. offset = when it starts in the video.
import { createTimeline, stagger } from '/_lib/animejs/dist/bundles/anime.esm.min.js';
const tl = createTimeline({ autoplay: false }).add('.card', { opacity: [0, 1], translateY: [40, 0], delay: stagger(120) });
ST.anime(tl, { offset: 3.5 });

// Lottie (lottie-web): autoplay false; readiness waits for the file.
const anim = lottie.loadAnimation({ container: el, renderer: 'svg', autoplay: false, loop: false, path: 'logo.json' });
ST.lottie(anim, { offset: 1.0, loop: false, speed: 1 });

// three.js: the stage renders after your update.
ST.three(renderer, scene, camera, (t) => { mesh.rotation.y = t * 0.8; });   // WebGLRenderer({preserveDrawingBuffer: true})

// GSAP (only if you installed it yourself; it is not part of showtime)
ST.gsap(timeline, { offset: 0 });

// Canvas / SVG / anything else: draw from t
ST.onSeek((t) => { ctx.clearRect(0, 0, W, H); drawScene(ctx, t); });
```

The helpers never `await` the library object: several animation libraries return objects with a
`then` method that only settles when playback ends. If you write your own adapter, return
`undefined` or a real `Promise`, never the timeline.

### `<video>` in a page

Every `<video>` is paused, muted and seeked to the middle of the right source frame on each seek
(seeking to the exact frame boundary shows the previous frame in Chromium). Attributes:
`data-offset` (in-point in the source, s), `data-rate`, `loop` / `data-loop`, `data-fps` (source
fps if it differs from the video's), `data-st="off"` (leave it alone). Its clock is its own
`data-start`, else the nearest clip's.

Renders (and `check`, `snap`, studio frames) draw every `<video>` on a canvas: on a busy or slow
machine Chrome can put a paused video's seeked frame on screen after the capture (the frame before,
or nothing for the first one), while a canvas is captured with the rest of the page. The canvas goes
right after the video and gets the video's computed style every frame (size, position, flex/grid
place, `object-fit`, transforms, opacity, filters, border-radius, masks, z-index, visibility), so it
lays out and paints where the video did; the video steps out of the flow, hidden, and its boxes
(`getBoundingClientRect`, `offsetWidth`...) report the canvas's. Transparent (alpha) clips stay
transparent; a clip up to Chrome's largest canvas (268 M pixels) is drawn at full size, a bigger one
stays a plain video. Nothing to write for it; the preview plays the plain `<video>`. Two things
differ: an extra element after each video shifts `:nth-child` / `:last-child` / `video + x`
selectors (use classes or `:nth-of-type`), and the video's own CSS transitions are off in renders
(they finish at once there anyway). `data-st-video="native"` on a `<video>` keeps it a plain video
in renders too (an edge case the canvas gets wrong).

A `<canvas data-st-video="ID">` of your own, styled like `<video id="ID">`, takes the frame of
`<video id="ID">` instead (the video is hidden; in the preview the canvas stays empty).
`showtime adopt` writes its pages this way.

- Use **VP9/WebM** (or AV1) for footage inside pages: Chromium builds without proprietary codecs
  (Playwright's Chromium, some Linux packages) cannot decode H.264. Convert with
  `showtime footage trim in.mp4 --webm --no-audio -o media/clip.webm` (never bare ffmpeg).
- Every seek decodes from the previous keyframe, so a large H.264 source with long keyframe
  intervals costs 100-300 ms per frame per render worker. Make a proxy the size the page shows it,
  with a keyframe every 0.5 s: `showtime footage trim demo.mp4 --width 1280 -o media/demo.mp4`
  (add `--from/--to` to keep only the part you use). `showtime check` raises its render estimate
  for pages with `<video>` layers.
- Keep sound out of the page: put it in the `audio` mix instead (the page is always muted).
- For long footage, prefer editing it with the footage tools and compositing graphics rendered
  with `--alpha` on top.

## Shutter blur: `data-st-blur` and `ST.blur`

Motion blur for a snap beat (a whip, a slam, a scale punch) on the one element that moves. While it moves
faster than `threshold` px a frame on screen, the stage draws `samples` copies of it posed at sub-frame times
from `t` back to `t - shutter`, averaged in its place (a 180° shutter is half a frame, as on a film camera).
At rest, moving slowly, and on the frame it comes to rest, the element draws itself, sharp. Nothing is
captured twice: the poses are computed from the element's own motion, so a blurred frame costs a few
milliseconds more (render.md § Speed), never `samples` captures. Four snap beats, and the same whip without and
with the blur: the `_blur` demo in the showtime repository's examples folder.

```html
<h1 class="word" data-st-blur>SNAP</h1>                      <!-- shutter 180, samples 8, threshold 6, max 50% -->
<div class="card" data-st-blur="shutter 270; max 120">...</div>
```

| Option | Default | Meaning |
|---|---|---|
| `shutter` | `180` | shutter angle in degrees: 180 is half a frame, 360 a whole frame (a longer smear) |
| `samples` | `8` | copies averaged on a blurred frame; each one is a copy of the element to draw |
| `threshold` | `6` | px a frame (on screen) under which the element is drawn sharp |
| `max` | `50%` | the longest smear: px, or % of the element's shorter side on screen; a faster frame gets a shorter shutter |

Where its motion may come from, because the stage can set each one to any time and read the element back:
CSS `@keyframes` and Web Animations on the element and its descendants, the showtime component around it,
timelines handed to `ST.anime` / `ST.gsap`, and a `pose(t)` function. A pose replaces the element's
`ST.onSeek` code: it runs on every seek and between frames.

```js
const logo = document.querySelector('#logo');
ST.blur(logo, { pose: (t) => {               // ST.blur(el | selector, {shutter, samples, threshold, max, pose}) -> off()
  const p = ST.progress(t, 2.0, 2.25, ST.ease.outExpo);
  logo.style.transform = `translateX(${((1 - p) * -900).toFixed(1)}px) rotate(${((1 - p) * -30).toFixed(2)}deg)`;
} });
```

Motion from a plain `ST.onSeek` handler or from a moving ancestor is not seen: `check` says so
(`blur_unsampled`). Canvas films: `F.motionBlur` (film-api.md §12).

How it is drawn: each copy is a clone of the element posed at its sample time; where the page's rules no
longer reach it in its new place (`.line > span`, `.scene > .card b`), the element's computed values are pinned
on it and on its descendants, so it looks the same. All copies are averaged with `mix-blend-mode:
plus-lighter` in an isolated group (in pairs of halves, so 8-bit rounding adds a level or two, not one per
copy) and smoothed along the motion by a gaussian half a step wide. An opaque element stays opaque where
every copy covers it. The copies live in an `<st-blur>` made once, right after the element, so selectors
such as `:last-child`, `+` and `:nth-child` see one more sibling on every frame (as after a `<video>`); an
`overflow: hidden` parent clips them as it clips the element (a mask reveal). Page code never meets them
(they are removed before each seek's handlers run), the same frame gives the same pixels in any worker, and
check's text audits read the element itself, as blurred, on those frames.

Taste (motion-craft.md §5): 1-3 snap beats a video, on the element that snaps; never on text being read, a
slow drift or a whole scene (scenes move with a transition: `push` with `blur: true`, `whip-pan`). `check`
warns `blur_slow`, `blur_text`, `blur_container`, `blur_unsampled` and `blur_inline` (render.md). Limits: a
non-replaced inline box is never transformed (use `inline-block`); a blend mode or backdrop filter inside the
element blends within its copies; a `<video>` inside it shows only in renders (canvases are copied).

## Determinism: what the render mode does and what to avoid

In render mode (render, check, snap) a small runtime is installed before any page script:

- `Date`, `Date.now()` and `performance.now()` return the frame time (`Date.now()` is
  2026-01-01T00:00:00Z plus `t`).
- `requestAnimationFrame` callbacks are queued and run once per seek with the frame time, so
  libraries with their own loop are driven by the seeks.
- `Math.random` and `crypto.getRandomValues` are seeded again on every frame from the frame
  number, so they give the same values for the same frame in any order or worker.
- `setTimeout` / `setInterval` stay real (loading needs them); callbacks that run during playback
  are counted and reported with their source line.
- Requests to anything other than the local server are blocked.

| Don't | Do instead |
|---|---|
| animate with `setTimeout`, `setInterval`, a counter incremented per frame | compute the value from `t` in `ST.onSeek`, or use `@keyframes` / a paused timeline |
| CSS `transition` triggered by toggling a class | `@keyframes`, or set the value from `t` (transitions are jumped to their end) |
| keep state between frames (`x += v`), physics stepping | closed-form `x = f(t)`, or pre-simulate once at load and look up by frame |
| `Math.random()` for layout that must stay put across frames | `const r = ST.rand('stars')` created once, at load |
| read the DOM in a seek handler and build on the previous frame's layout | measure once at load (after `ST.waitFor(document.fonts.ready)`) |
| remote fonts, images, scripts or map tiles | `/_lib/@fontsource...`, files in the project, `/_assets/...` |
| system fonts (`Helvetica`, `Arial`, `system-ui`, emoji fonts) | `@font-face` files; they render the same on macOS, Windows and Linux |
| emoji typed as text drawn by the OS emoji font | nothing to do: stage.js swaps text emoji (🚀, ❤️, 👍🏽, flags) for Noto SVGs from `/_st/emoji/<codepoints>.svg`; install each once with `showtime assets emoji 🚀` (check reports a 404 with that command when one is missing). `data-st-emoji="off"` on an element keeps its emoji as text |
| ⌘ ⇧ ⌥ ↵ and arrows as text in keycaps | the `keystrokes` component and `Film.keyCombo` draw them as vector icons |
| animated GIFs | a VP9 `<video>` or an image sequence driven by `t` |
| animating `left/top/width/height/margin` for motion | `transform` (layout properties snap to whole pixels and judder) |
| `canvas.getImageData` every frame on a GPU canvas | `getContext('2d', {willReadFrequently: true})` or avoid readback |
| `backface-visibility` tricks in 3D CSS | real geometry, or render both faces explicitly |

`showtime check` probes all of this for real: it captures frames, captures them again after a
real delay and in another order, and compares the pixels.

## Readiness

`ST.ready()` (called by the renderer and the player, never by scenes) waits for: the page
`load` event, every `@font-face` in the document (all are loaded up front), `<img>` decode,
`<video>` data, and every `ST.waitFor` promise; then it resolves the duration and seeks to 0.
A page that never becomes ready fails with the list of pending `waitFor` labels.
Each of these waits (60 s for fonts and for the `waitFor` gates, 15 s per image or video, 30 s for
the load event) is multiplied by the page's pace factor, 1 to 5, measured from the gaps between its
frames while it gets ready and from its first seeks; `ST.pace()` returns it (render.md explains the factor).

## Preview mode

Opening a page through `showtime preview` (or the server's `/_st/preview?page=/index.html`) shows
the **player**: the page runs in a frame at its real size scaled to fit, driven by `ST.seek` with a
real-time clock, with the same virtual clock installed as in render mode, so what you scrub is
what renders. Player keys: Space play/pause, Left/Right one frame (Shift: 1 s), Home/End, L loop,
M mute, S safe-zone guides, F fit/100%. Clip names (`data-name`, else `id`) are marked on the
scrubber. Audio: `ST.score` is rendered offline once and played in sync from any position,
together with `work/mix.wav` (built from the `audio` field by `showtime preview`). Saving a project
file reloads the page at the same time position.

Opening the page itself (`/index.html`) redirects to the player; `/index.html?st=raw` plays the page
alone in a loop (Space pauses).

## Scene transitions with shaders (layer protocol)

Pages can expose `window.__stLayers = { pending(), solo(id), put(id, dataUrl), compose(), unsolo() }`
(the transitions module does). After each seek the renderer asks `pending()`; for each layer id it
calls `solo(id)`, screenshots the page, hands the image back with `put()`, and finally `compose()`s
before the real screenshot. The page sees `window.__ST_RENDER__.layers === true` when this is active.
Frames without pending layers cost nothing extra.

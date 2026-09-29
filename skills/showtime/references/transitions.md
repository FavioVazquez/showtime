# Transitions: scene handoffs for HTML videos (runtime/transitions)

Read this when a DOM video has more than one scene and you are choosing how scenes hand off, or
when adding a shader (WebGL) transition. For real-footage edits (MP4 clips) the footage tools use
ffmpeg crossfades instead. `showtime motion transitions` prints the catalog; the machine-readable
version with moods and energy is `runtime/transitions/catalog.json`.

## 1. Using them

Declarative (recommended): put `data-transition` on the **incoming** scene. The outgoing scene is
the previous sibling with `data-start`.
```html
<section class="scene" id="a" data-start="0" data-dur="4">...</section>
<section class="scene" id="b" data-start="#a" data-dur="4" data-transition="push left 0.5">...</section>
<section class="scene" id="c" data-start="#b" data-dur="3" data-transition="domain-warp">...</section>
```
Spec: `<type> [left|right|up|down] [seconds] [start|center|end|peak]`; more options as JSON in
`data-transition-options='{"blur":true}'`. `cut` or `none` = hard cut. `index.js` wires these
automatically; pages that do not load it call `autoTransitions()`.

From JS: `import { transition } from '/_st/transitions/transitions.js';`
`transition({ from: '#a', to: '#b', type: 'iris', center: [70, 40], dur: 0.6 })`.
Options: `at` (composition seconds; default the incoming scene's start), `dur`, `ease`, `align`,
`dir`, `blur`, `color`, `shape`, `count`, `center`, `inverse`, `items`, `a`, `b`, `seed`.

**Timing model.** The window is `[at, at + dur]`, `at` = the incoming scene's `data-start`; its
edges snap to frames like clip edges do (a time within 1 ms of a frame is on it). The
outgoing scene stays on screen through the window holding its last frame (its clip is kept active),
so no start time moves and voice, captions and SFX stay aligned. `align: center` straddles the cut;
`align: end` finishes on it; `align: peak` puts a hard-cut transition's swap on the scene start
(`flash` swaps at 35 % of its window, glitch-type ones at 50 %), so the white of a flash lands on the
beat the scene was placed on: `data-transition="flash 0.3 peak"`. Keep the outgoing scene's content fully visible when the window
starts: the transition is its exit (no separate exit animations on non-final scenes).

## 2. Catalog

Tier: **premium** = safe default look; **accent** = once or twice per video; **cheap** = only when
the style asks for it (retro, glitch aesthetics, irony).

| name | kind | dur | energy | tier | what it does / when |
|---|---|---|---|---|---|
| crossfade | css | 0.5 | calm | premium | incoming fades over outgoing; same background, same thought |
| dip | css | 0.7 | calm | premium | through a colour (`color`, default theme bg); chapter breaks, before the logo |
| blur-dissolve | css | 0.6 | calm | premium | outgoing blurs and grows, incoming resolves; the default soft cut, hides clashing backgrounds |
| push | css | 0.55 | medium | premium | both scenes move one frame-width (`dir`; `blur: true` adds motion blur); sequences |
| slide | css | 0.6 | medium | premium | incoming covers, outgoing parallaxes and dims; depth, cards |
| zoom-through | css | 0.55 | high | premium | accelerate into the old scene, decelerate out of the new (`inverse` = pull back / arrival) |
| whip-pan | css | 0.45 | high | accent | fast push under heavy directional blur |
| iris | css | 0.6 | medium | accent | circle opens from `center` [x%, y%] |
| wipe | css | 0.6 | medium | accent | `shape` linear (a direction alone, `wipe left`, means linear), diagonal (default), bars (`count`), diamond; bars/diamond read cheap |
| glitch | css | 0.35 | high | cheap | stepped RGB split + slice displacement, cut at the middle |
| flash | css | 0.4 | high | accent | to white (`color`) and cut at the peak; max 1-2 per video |
| stagger | css | 0.9 | medium | premium | items leave in reading order, new items arrive (`items` selector, default `[data-stagger-item]`) |
| through | css | 1.5 | calm | premium | one camera move: fly into a portal element of this scene (`data-portal`: a window, a screen, a card; `data-portal="counter"` on one letter: its enclosed hole) and the next scene is what was inside it; `inverse` pulls back out of a portal of the next scene; the launch hook's handoff |
| match | css | 0.9 | calm | premium | shared elements (`data-match="name"` in both scenes) fly from their old place to their new one while the rest dissolves; the product window carrying across feature beats |
| pan | css | 1.2 | medium | premium | the camera travels to the next scene laid beside this one (`dir`, a 6 % pull-back `arc`, a `gap`); one direction per video |
| domain-warp | webgl | 0.9 | calm | premium | the new scene seeps in along a warped fractal front with an accent glow |
| ridged-burn | webgl | 0.8 | high | accent | film-burn front with a hot rim, charring and sparks (`a` = sideways bias) |
| sdf-iris | webgl | 0.65 | medium | premium | anti-aliased iris with a lit rim and echoes (`a`,`b` = centre 0..1) |
| ripple | webgl | 0.8 | calm | accent | circular waves bend both frames; memory, water, calm |
| chromatic-split | webgl | 0.4 | high | accent | RGB copies fly apart and re-converge on the new scene |
| cross-zoom | webgl | 0.5 | high | premium | radial zoom blur peaking mid-way with lens fringing |
| light-leak | webgl | 0.8 | calm | premium | warm over-exposed flare sweeps across, filmic roll-off (`a` = strength, default 1) |
| pixel-dissolve | webgl | 0.6 | medium | cheap | blocks coarsen and flip in random order (`a` = block size) |
| morph-warp | webgl | 0.8 | calm | premium | a noise flow field drags one frame into the other |
| whip-blur | webgl | 0.45 | high | accent | shader whip pan with a heavy smear (`a` = 1 left, -1 right) |
| signal-glitch | webgl | 0.35 | high | cheap | stepped row tears, block jumps, RGB shift, cut inside the noise |

## 3. Choosing

- **One primary + one or two accents.** 60-70 % of cuts use the same transition (hard cuts count;
  on the beat, a hard cut is the most premium transition there is). Repetition reads as intent.
- **Energy.** Calm pieces: blur-dissolve / crossfade, 0.6-0.9 s, shaders domain-warp, morph-warp,
  light-leak. Medium (product, explainer): push / stagger / slide, 0.4-0.6 s, shader sdf-iris or
  cross-zoom for the reveal. High (music video, hype reel): zoom-through / whip-pan / hard cuts,
  0.3-0.5 s, shader cross-zoom, ridged-burn, chromatic-split.
- **Launch, promo, release, trailer: match cuts and dissolves, one motivated camera move at most.**
  `match` while the product window carries across the feature beats, a `blur-dissolve` or `dip`
  (0.8-1 s) onto the end card, and at most one `through` (hook into the product, when the product
  appears inside the hook's big key word). Every camera move needs a reason you can say; premium launch
  films change scene 4-5 times and keep the camera still (`workflows/launch-video.md`). No push, pan,
  flash, glitch or shader in a launch film.
- **Position in the story.** Opening: the most distinctive. Related points: the primary, short.
  Topic change: something different. Climax / reveal: the boldest (a shader). Outro: the simplest
  and slowest (dip or crossfade, 0.6-1 s).
- **Data stories, reports, explainers.** A transition must say what changed: same topic, next chart =
  `dip` (0.5-0.7 s) or a hard cut when the axes stay; new chapter = a slower `dip`; title into the
  first chart = `blur-dissolve`. Never push, warp or wipe a chart the viewer is still reading, and
  never mix three unrelated families in a four-scene piece (push + blur + shader reads as chopped).
  Let each chart finish settling (bars landed, callout shown) before its scene ends.
- **Voice-led pieces: never transition mid-sentence.** A handoff sits in the pause between two
  voice lines (`retime --from-voice` puts scene starts there); a cut inside a sentence, or a
  transition window that covers spoken words, reads as a mistake.
- **Direction.** One direction for every push/slide in a video (leftward = forward).
- **Premium signals.** Motion continuity across the cut (exit accelerates, entry decelerates,
  they meet at peak speed); motion blur only on fast moves; nothing longer than 1 s between UI shots.
- **Cheap signals.** A different transition on every cut, star/diamond/checker wipes, glitch on
  everything, dissolves over 1 s between UI shots, a whoosh on every cut.
- **Photosensitivity.** Flashes and glitches: never more than 3 bright flashes per second.
- **Dense scenes on both sides.** `crossfade` lays the incoming scene over the outgoing one, so two
  busy charts on the same background read as a double exposure mid-window: use `dip`, or delay the
  incoming scene's first element past the window's midpoint.
- **Text inside shader windows.** A WebGL transition rasterises the whole scene, labels included, so
  text smears for the length of the window: fade labels out before the window starts and in after it
  ends (or use a CSS transition for text-heavy cuts). `domain-warp` also smears a wordmark into its
  accent glow: on an end card with a logo, use `dip`.
- **Strength.** `ripple` takes `a` (wave strength, default 1): `data-transition-options='{"a":0.6}'`
  is 40 % calmer; a shorter window alone still swirls.

**Camera moves in detail.**
- `through`: the portal is measured on screen every frame (the scene's own camera can move it). The
  zoom runs in log space (as even from 1x to 40x as from 1x to 2x), the portal drifts to the frame
  centre over the first 75 %, and the opening grows to the full frame over the last 45 %. The incoming
  scene plays from the window's start, so what shows through the portal is already alive. A letter
  counter needs a closed glyph (o a e d g p q b 0 6 8 9) in a font with a real hole; the counter is
  found by drawing the glyph once. `inverse`: the outgoing scene shrinks into the incoming scene's
  `[data-portal]` and dissolves into it over the last 20 % (`keep` skips that), so the portal should
  show what the outgoing scene ends on (the same clip, the same screen).
- `match`: pairs every `[data-match]` of the incoming scene with the same name in the outgoing scene,
  measured each frame; the incoming copy fades in over the outgoing one along the same path, the rest of
  the outgoing scene fades out in the first half, the rest of the incoming scene fades in from 35 %, and
  the incoming ground fades in on its own layer. Do not give a matched element an entrance animation in
  the incoming scene. Same ground on both sides.
- `pan`: both scenes are placed in one world, the next one `dir`-wards (default: to the right), and the
  camera travels with a small pull-back; the page background shows in the gap, so keep one ground.

## 4. How the WebGL transitions work (and on which machines)

The compositor draws both scenes into a WebGL 1 canvas placed right above them and blends them with
the shader. Layers placed after the incoming scene in the same parent (a map inset, labels, captions)
stay above every transition, CSS or WebGL, for the whole window: the runtime lifts positioned siblings
without a z-index of their own; give an overlay an explicit `z-index` only to order overlays among
themselves.
- **Text in shader windows.** Displacement shaders (domain-warp, ripple, morph-warp) smear small text.
  Fade the outgoing scene's text out just before the window and the incoming text in just after it,
  or keep text on an overlay layer, which the shader never touches.
- **Alpha renders.** The shader canvas is opaque: over transparent scenes in a `render --alpha` it
  paints the whole frame. Put the window between two full-frame plates, or use a CSS transition
  (`crossfade`, `wipe`, `iris`, `slide` keep the transparency).
- **Scene pixels.** By default each scene is rasterised in the page: it is cloned with its ancestor
  chain, the page CSS is embedded (only the font faces its text needs, as data URLs), images,
  canvases and video frames are frozen to images, CSS animations are frozen at their current value,
  and the result is drawn through an SVG `<foreignObject>`. This works in render, snap, check and the
  preview player, on every OS. Cost here: ~50-250 ms per transition frame at 1080p (only frames
  inside the window).
- **Limits of in-page rasterising.** Cross-origin iframes are dropped; elements styled only through
  selectors that depend on siblings outside the scene may differ; `<video>` without a loaded frame
  shows empty. If a scene looks different in the transition, give it self-contained styles, or use
  a CSS transition.
- **Exact path (renderer layer capture).** When the renderer sets `window.__ST_RENDER__.layers = true`,
  the page does not rasterise; after each `ST.seek(t)` the renderer calls
  `window.__stLayers.pending()` (-> `[{id}]`), then for each id `solo(id)`, a screenshot, and
  `put(id, dataUrl)`, then `compose()`, then its normal screenshot. `solo` hides everything except
  the layer's scene; `compose` restores and draws the shader.
- **GPU.** Hardware WebGL through ANGLE (Metal on macOS, D3D11 on Windows, GL on Linux) or
  SwiftShader (`--gpu off`, slower, most reproducible across machines). Shaders are GLSL ES 1.00
  with no extensions, no derivatives, constant loop bounds of at most 16 iterations, and no reversed
  `smoothstep` edges, so they compile on every ANGLE backend.
- **No WebGL.** If a context cannot be created, the transition falls back to its CSS relative
  (`fallback` in the catalog) and logs a warning.

## 5. Writing a new shader

Add an entry to `runtime/transitions/shaders.js` (`SHADERS[name]`) that defines
`vec4 blend(vec2 uv)` using `srcA(uv)`, `srcB(uv)`, `uP` (eased progress), `uR` (linear),
`uAspect`, `uRes`, `uAccent`, `uAccent2`, `uSeed`, `uA`, `uB` and the helpers `rnd`, `noise`,
`fbm`, `filmic`; then add its name to `GL_TYPES`, `DEFAULTS` and `GL_FALLBACK` in
`transitions.js` and to `catalog.json`. At `uP = 0` it must return scene A exactly and at
`uP = 1` scene B. Anything random must come from `rnd()` of stepped progress so frames are
deterministic.

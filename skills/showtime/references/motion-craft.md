# Motion craft: easing, timing, stagger, holds, camera moves and what reads as cheap

Read this when you are choosing how things move in a video (DOM components, canvas films, or
custom code), reviewing a draft that "feels off", or setting motion defaults for a new theme.
Component options: `references/components.md`. Scene handoffs: `references/transitions.md`.

## Essentials

- Default to a strong ease-out (`power3.out`, `premium`); overshoot (`back`, springs damping < 0.8) only in a
  playful register and never on blocks of text; ease every spatial move (§1, §2)
- Reveal as the narration says it, spread into the back half of the scene; never front-load and freeze (§1)
- Hold after a move lands: ≥0.5 s short-form, ≥1 s explainer, 1.5-2.5 s for anything to read or understand;
  nothing freezes: holds over ~2 s keep the hold push (`data-drift="hold"`, 1.2 %/s) (§1)
- Stagger in importance order: letters 15-25 ms, words 30-60 ms, items 60-100 ms, ≤0.4-0.5 s per group; over
  ~9 items use one wipe (§1, §4)
- Something changes every 2-4 s in short-form; a text-only scene over ~2.5 s needs motion (a 5-7 % push, 7-8 %
  on dark frames) or `check`/`qa` flag a still hold (§1, §6)
- Entrance 0.3-0.6 s, exit 60-80 % of it, scene move 0.5-0.8 s, count-up 1.2-2.5 s; first motion 0.1-0.3 s after
  the cut, hero visible by 0.5 s (§3)
- Animate transforms only (`translate`, `scale`, `rotate`, `opacity`, `filter`, `clip-path`); scale in from
  0.94-0.98, travel 16-40 px; only the final scene exits on its own (§5)
- Motion blur (`data-st-blur`) only on 1-3 snap beats a video (a whip, a slam, a scale punch: the move in 6-9
  frames, most of it in the first 2-3), on the element that snaps; never on text being read, a slow drift or a
  whole scene (§5)
- Camera: push 1.00 -> 1.04-1.08 over a shot; punch-ins never in launch, promo or explainer films nor on every
  jump cut; UI zoom 1.5-2x (max ~2.8x); drift on the background layer only (§6)
- Headlines ≥7 % of the frame height; body ≥36 px at 1080p landscape, 48 px at 1080x1920; text-only hold
  `max(1.0, 0.5 + characters / 13)` s (§7)
- Visual hits 1-2 frames before the beat; put SFX on the components' `sync` beats (§8)
- Determinism: no `Date.now`, timer animation, unseeded `Math.random`, CSS `transition`s, accumulators or
  `will-change`; register library timelines paused (`ST.anime(tl)`) (§10)
- Showreel tone: 12-14 shots per 15 s on a BPM grid, no technique twice, at least 8 kinds (live counter, words
  over a liquid shader, 3D, particles, kinetic and glitch type, a pattern system, a tunnel, a morph), a match or
  zoom-through for surprise, the name landing on the last beats (~1.25 s); `showtime new showreel` (§11)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. The five rules that matter most | 51-71 |
| 2. Easing by character | 73-89 |
| 3. Durations | 91-106 |
| 4. Stagger | 108-119 |
| 5. Entrances and exits | 121-150 |
| 6. Camera moves | 152-190 |
| 7. Type in motion | 192-200 |
| 8. Rhythm and sound sync | 202-208 |
| 9. Anti-patterns (and the fix) | 210-227 |
| 10. Determinism rules (why frames match every time) | 229-238 |
| 11. Showreel: go all out | 240-291 |

## 1. The five rules that matter most

1. **Smooth beats bouncy.** Default to a strong ease-out (`power3.out`, or `premium` =
   cubic-bezier(0.16, 1, 0.3, 1)). Overshoot (`back`, springs with damping < 0.8) only in an
   explicitly playful register, and never on blocks of text.
2. **Reveal as it is said.** Nothing appears before the narration mentions it; spread reveals across
   the scene (especially the back half) instead of dumping everything in the first second and then
   freezing (the "slideshow" failure).
3. **Hold after it lands.** At least 0.5 s (short-form) or 1 s (explainer) of stillness after a move
   before the next change; 1.5-2.5 s for anything that must be read or understood. The stillness is the
   content's, never the frame's: **nothing freezes.** A hold longer than about 2 s keeps a slow push
   under it so it reads as intended, not stuck: the scene camera's `data-drift="hold"` (1.2 % of scale
   per second, 0.04 % a frame at 30 fps, capped at +6 %; the rate that passes both `check` and qa's
   `frozen` detector on light and dark text frames with margin, measured; 0.8 %/s is borderline). Much faster (0.25 % a frame is 7.5 %/s)
   reads as a zoom, not a hold. Launch films keep a still camera on their proof scenes and get the
   motion from the next beat instead (`workflows/launch-video.md`); a hold longer than reading needs
   is cut, not pushed (`slow_scene`).
4. **One thing leads.** What moves first is what matters most. Stagger in importance order, keep
   every group's total stagger under ~0.5 s, and don't start everything at the same instant.
5. **Something changes every 2-4 s** in short-form (a cut, a reveal, a camera move). A static frame
   longer than ~4 s loses viewers, but a designed hold on the key message is not dead air.

## 2. Easing by character

| use | curve (name in `ease()`) | notes |
|---|---|---|
| entrances, reveals (workhorse) | `power3.out`, `premium`, `expo.out` | fast start, long settle |
| exits | `power2.in`, `exit` (0.3, 0, 0.8, 0.15) | accelerate away; 20-30 % shorter than the entrance |
| moves between two rest positions | `power3.inOut`, `camera` (0.65, 0, 0.35, 1) | cameras, pans, pushes |
| organic, ambient, crossfades, Ken Burns | `sine.inOut` | never for a hero arrival |
| UI micro-motion | `standard` (0.2, 0, 0, 1), `emphasized` (0.05, 0.7, 0.1, 1) | 100-300 ms |
| premium "never quite lands" arrival | `glide` | 87 % of the way at 20 % of the time, then eases in |
| physical settle | `spring(response, damping)` | response 0.3-0.6 s; damping 1 = no overshoot, 0.8-0.85 ~1-2 %, 0.6-0.7 playful |
| typing, blinking, counters that tick | `steps(n)` | mechanical registers (terminal theme) |
| linear | `linear` | only opacity under 150 ms, rotation loops, tickers |

Springs are closed-form (a pure function of progress), so they are seek-safe; `spring(...).duration`
is the natural settle time. Put overshooting curves on transforms only; fade opacity with its own
non-overshooting ease.

## 3. Durations

| what | duration |
|---|---|
| micro UI (press, toggle, chip) | 0.10-0.25 s |
| element entrance | 0.3-0.6 s (0.15-0.3 urgent, 0.5-0.8 luxury, 0.8-2 cinematic) |
| exit | 60-80 % of its entrance |
| scene / layout move | 0.5-0.8 s |
| count-up | 1.2-2.5 s (under 0.8 s reads as a flash) |
| camera push / drift | 1-4 s for a push, a whole shot for a drift |
| chart state change | ~1 s per stage (axis, then marks, then labels) |
| first motion in a scene | 0.1-0.3 s after the cut; hero visible by 0.5 s |
| hold before a cut | >= 0.5 s short-form, >= 1 s explainer, 2-3 s for a settled chart |

Slowest scene about 3x slower than the fastest; monotone rhythm reads as a template (try
short-short-long, with the longest hold on the key message).

## 4. Stagger

- Letters 15-25 ms, words 30-60 ms, list items or cards 60-100 ms; total per group <= 0.4-0.5 s
  (`stagger(i, n, each, {cap})` enforces the cap). Over ~9 items, switch to a wipe or sweep: for
  dense marks (more than ~50 bars, stripes, dots) reveal the group with one `clip-path: inset()` wipe;
  per-mark staggers with their own easing read as a staircase.
- Emotion: 40 ms urgent, 80 ms conversational, 150 ms deliberate, 250 ms+ ceremonial.
- Vary the entrance direction between groups (rise, slide, scale, mask) instead of everything
  coming up from y+30 with a fade.
- Per-letter animation only for 1-3 word hero titles; animate readable text by word or line.
- Decaying cascades feel like a settling camera: each next item travels a little less
  (e.g. 80 -> 60 -> 45 -> 30 px) or starts a little sooner (gap x 0.85 per item).

## 5. Entrances and exits

- Build the resting (end) state in HTML/CSS first; animate *from* it.
- Transform-only motion (`translate`, `scale`, `rotate`, `opacity`, `filter`, `clip-path`).
  Animating `left/top/width/height/font-size/letter-spacing` snaps to whole pixels and stutters
  on slow eases.
- Scale entrances from 0.94-0.98, not 0; translate 16-40 px (or 0.3-0.6 em), not 200.
- Mask reveals (content slides out from behind a clip) and blur-in (8-12 px -> 0) read premium; a
  plain fade reads flat.
- Exits: only the final scene exits on its own; elsewhere the transition is the exit. Outgoing
  content must be complete and visible when the transition starts.
- Scene phases: build (0-30 %: staggered entrances) -> breathe (30-70 %: one small ambient motion,
  or stillness) -> resolve (70-100 %: the decisive last element, then a still hold).

**Snap beats and motion blur.** A snap is the exception to the small moves above: a word whipped in from the
side, a title slammed down, a logo punched in from 2-3x, the whole distance in 6-9 frames on a hard ease-out
(`expo.out`, `cubic-bezier(0.16, 1, 0.3, 1)`): most of it in the first 2-3 frames, the rest a settle (shorter,
and qa calls the landing a `dead_stop`). At that speed a sharp element strobes (it jumps its own size
between frames) and reads cheap; `data-st-blur` on it (stage-api.md § Shutter blur) smears it only on its
fast frames, like a camera shutter, and it lands sharp. Taste:

- One to three snaps a video, on the beat, where the energy peaks: the showreel's flash words, a launch title's
  arrival. A blur on every move reads as a filter, not as speed.
- Never on text the viewer is reading: it snaps in blurred, lands, then holds sharp for its reading time. A
  ticker or a line that drifts while it is read gets no blur (`check`: `blur_text`).
- Never on slow motion: entrances of 16-40 px, drifts, pushes and gentle slides already read smooth; blurring
  them only softens them (`check` warns `blur_slow` under about a quarter of the element's size a frame).
- Never on a scene, a container or a full-frame layer: a whole-frame smear reads as a broken frame and costs
  copies of the whole page (`blur_container`). Scene-to-scene moves are transitions: `push` with `blur: true`,
  `whip-pan`, `whip-blur` (transitions.md).

## 6. Camera moves

| move | numbers |
|---|---|
| push-in (focus) | scale 1.00 -> 1.04-1.08 over the whole shot, `sine.inOut` or `camera` |
| punch-in (emphasis) | 1.0 -> 1.15-1.3 in 0.25-0.4 s, `power3.out`, hold >= 1 s; never in launch, promo or explainer films, and never on every jump cut (viewers read it as cheap); fine in a showreel (§11) |
| zoom to a UI target | 1.5-2x for clicks and typing, 1.3-1.5x for scroll, hard max ~2.8x; transition 0.6 s + 0.55 s x ln(zoom); start 0.15-0.4 s before the action; hold >= 1.2 s |
| pull-back reveal | author the wide shot at 1x and open scaled in, never shrink a 1x close-up |
| drift | 2-8 px x, 1-4 px y, 1-3 slow cycles per shot, on the background layer only |
| parallax | 2-4 depth layers; far layers move 20-40 % of near layers |
| shake | only on impacts, <= 0.3 s, amplitude decaying; decorrelated x/y noise |

The `camera` component (`components.md`) does all of these from a path of keys (zoom, focus, eased in
log-zoom space, drift on holds, parallax depth layers); scene-to-scene camera moves are the
`through`, `match` and `pan` transitions (`transitions.md`).

Scale perception: < 5 % reads as static, 10-15 % comfortable, > 30 % dramatic. Never run the same
ambient zoom on every scene; stillness after motion is powerful.

Text-only scenes longer than ~2.5 s need some motion or `check`/`qa` flag a still hold: the hold push
(`data-drift="hold"`, §1 rule 3) or a 5-7 % push over the scene (`.cam` wrapper, `sine.inOut`) is enough. Thin moving parts (a 2 px ruler fill, a small
pulse, a grey label) do not count as change, and a small restyle (a 3 cqh bold label made 2.4 cqh grey)
can drop a scene back under the threshold; re-run `check` after type changes. On dark frames a slow
push changes few pixels, so give it 7-8 % or pair it with another beat.

**Looks** (`fluted-glass`, `tilt-shift`, `liquid-metal`, `mesh-gradient`, `god-rays`, `marble`, `metaballs`;
`components.md` §7) are seasoning: one per scene, and only where it says something. In an explainer or tutorial
two fit. `tilt-shift` with the `focus` preset points at the region the narration is about, then moves with it
(a 1-1.5 s `sine.inOut` key), and the rest stays legible enough to keep the viewer oriented. `mesh-gradient`
`calm` is the ground under words (a chapter card, a definition, a quote): it should be felt more than seen, so
keep its intensity low and its drift slow, never key it to the narration, and keep `vivid` for a title. Glass,
metal, rays and marble are hero looks: a launch title over `fluted-glass`, a metal object on the end card with
the product name in its reflection, the name revealed by `god-rays` (the light comes up over about 1 s, then
holds), a quote or an end card on `marble` (`nero` or `carrara`; `ink` is loud and wants a plate under the
text), a reel shot. Let them form on screen (depth, `in` or strength easing up over about 1 s) and then hold
quietly while the text reads; never put moving glass behind body text, and never run the same look in two
scenes of one film. `metaballs` are for play: a merge on the beat where two ideas become one (`spread` keyed
to 0), a count that splits, a gooey `wipe` on a cut in a reel; not in a serious or sad film, and never as
filler behind words.

## 7. Type in motion

- One idea per card, 1-6 words. Headlines >= 7 % of the frame height; minimum body 36 px at
  1080p landscape, 48 px at 1080x1920.
- Display tracking tight (-0.02 to -0.04 em); body normal. Two families at most, contrasting
  (serif + sans or sans + mono), extreme weight contrast (300 vs 800).
- Reading budget when text is the only carrier: hold = max(1.0, 0.5 + characters / 13) s,
  about 3 words per second.
- Numbers: tabular figures (`.t-num`), land on a beat, never invent them.

## 8. Rhythm and sound sync

- Place visual hits 1-2 frames (33-66 ms at 30 fps) before the beat or SFX transient; audio
  slightly late is tolerated, early is not.
- 60-70 % of motion on the beat grid feels musical; 100 % feels mechanical.
- Components expose `sync` beats (e.g. `count-up.sync.land`, `cursor.sync.click1`,
  `kinetic-type.sync.landed`): put the SFX at that time instead of guessing.

## 9. Anti-patterns (and the fix)

| looks cheap | do instead |
|---|---|
| `back`/elastic overshoot on everything | ease-out; overshoot once, on one hero element |
| every element enters at t = 0 | lead with the hero, stagger the rest in importance order |
| everything from y+30 with a fade | vary axis and technique per group; mask or blur reveals |
| front-loaded then frozen for 5 s | reveal with the narration, spread into the back half |
| endless breathing / floating loops | one subtle ambient motion per scene, or none |
| a different transition every cut | one primary transition + 1-2 accents |
| linear moves | ease every spatial move |
| full-screen dark linear gradients | radial glows + grain (`data-st="grain"`); gradients band after compression |
| pure #000 / #fff, rainbow accents | theme tokens; one accent colour |
| centred-everything web layout | anchor to edges, asymmetric splits, 3 depth layers |
| text shake / wiggle / rainbow | emphasis by weight, colour or scale, one at a time |
| a fast snap that strobes (a sharp word jumping 200 px a frame) | `data-st-blur` on that element: smeared only while fast, sharp when it lands (§5) |
| motion blur on every move | only the 1-3 snap beats; entrances, drifts and pushes stay sharp (§5) |
| more than 3 flashes per second | at most one flash per ~0.33 s, small area when faster (photosensitivity) |

## 10. Determinism rules (why frames match every time)

Every visual is a function of time: no `Date.now`, `setTimeout`/`setInterval` animation, unseeded
`Math.random` (use `hash()`/`rng()` or `ST.rand`), CSS `transition`s on animated elements,
accumulating `x += v`, or state flipped in callbacks. CSS `@keyframes` inside a clip are seeked
by the stage relative to the clip start; library timelines must be created paused and registered
(`ST.anime(tl)`). Avoid `will-change` on animated elements: the extra compositor layers make
anti-aliasing depend on which frame was drawn before (measured here: up to 84/255 on text edges
when frames are sought out of order). `showtime check` re-shoots frames after a delay and in shuffled order to catch
anything tied to wall-clock time.

## 11. Showreel: go all out

The showreel tone (`tones.md`) inverts the restraint above: density, energy and surprise win, and the quality bar
moves into craft (no banding, no specks, no stutter, no broken frame). `showtime new showreel <dir>` is a working
15 s reel built from the recipes below (`templates/showreel/reel.js` holds the helpers); swap shots for the
maker's own work whenever there is any.

**Structure.** Pick a tempo first, then cut on its grid: at 120 BPM a beat is 0.5 s, 15 s is 30 beats. 12-14 shots,
each 1.5-2.5 beats (one data or 3D shot may take 3-4) and each a different technique; a run of flash words on
2/3-beat steps; the name takes the last 2-2.5 beats (its reading time, ~1.25 s), tracking or building in on the
beat and moving to the last frame. The 2026-10-05 rematch: the winner cut 13-14 shots and landed its name in the
last 1.75 s; the takes that held their name 2.5-3.5 s lost. Nothing sags for more than ~1 s: a settled chart or
object keeps a push or a turn going. One hit per cut in the mix, a riser into the drop and into the name. Hook
landed at frame 0 (no blur-in on the poster frame). At least one match or zoom-through where a shot turns into the
next (the critic's "surprise"): a tunnel whose centre opens into the next shot's ground, a fly-through the counter
of a letter into the end card. Variety: no technique twice, at least 8 kinds (`tones.md`, showreel, the menu); two
shots on the same ground with the same layout read as one trick (qa's `showreel_repeats`).

The template's fourteen shots (`showtime new showreel`), seconds: hook, words over a liquid chrome shader (0-1);
flash words (1-2); particle burst on the drop (2-3); 3D knot, camera dolly (3-4.25); glitch type on red
(4.25-5); kinetic bands (5-5.75); live data, bars, a line and an odometer counter (5.75-7.5); shape morph
(7.5-8.25); tile system (8.25-9.25); tunnel that opens into the next ground (9.25-10.25); line drawing
(10.25-11.5); halftone sphere (11.5-12.5); type as a mask over a shader, flying through the O (12.5-13.75);
the name (13.75-15).

| technique | recipe (all offline, a pure function of the shot's local time) |
|---|---|
| shader ground | a full-frame WebGL fragment shader (`shaderLayer(canvas, frag, {scale: 0.75})`): domain-warped value noise (`fbm(p + 2.6 * fbm2(p + t))`), read as a height field, its normal reflecting a two-colour sky gives liquid chrome; feed `u_t` from the clip's local time, darken a pool under the type (contrast), 4 octaves at 0.75 scale renders fast; `preserveDrawingBuffer: true` |
| particle burst on a beat | seeded once (`ST.rand('drop')`), positions closed-form: distance `v (1 - e^(-k τ)) / k` with drag k 2-3, an angle that swirls by `s (1 - e^(-1.2 τ))`; draw each as a streak from its position 0.07 s earlier, additive (`lighter`), fading over 1.7-3.3 s so the shot never ends in dust; the hit's core glow stays under a quarter of the frame (flash limit) |
| kinetic type | flash words on the beat (one per 2/3 beat, `data-st-flash`, on screen from their first frame), each a snap (a whip, a slam, a scale punch in 6 frames) under a shutter blur (`data-st-blur` on the word, not its full-frame wrapper); bands of 1-3 word repeats in opposite directions with `x = (1 - e^(-2.2 u)) × 46 cqw` (fast in, easing out), a full-bleed colour band behind one row (`box-shadow: 0 0 0 100cqw; clip-path: inset(0 -100cqw)`); an outline stack in a static face (a variable font's outlines show their overlapping contours); glitch as `::before`/`::after` slices of `attr(data-text)` plus an RGB-split `text-shadow`, both from CSS variables set per frame, bursting in the first 0.16 s of each beat (the word is audited once) |
| 3D object turn | three.js from `/_lib/three` through an import map, lit by `RoomEnvironment` through a PMREM (sigma 0.12: nothing fetched, soft reflections), `MeshPhysicalMaterial` metal 1, roughness about 0.22, iridescence 1, 96+ radial segments (lower roughness and segments read as specks), two coloured point lights; `ST.three(renderer, scene, camera, fn)` turns it and dollies the camera in from local time |
| live data / counter | `chart(canvas, {value, label})`: hairlines draw out, bars rise on a damped spring (`1 - e^(-6p) cos 9p`) staggered 45 ms, a line draws on with a pulsing head, a ring gauge closes, and an odometer rolls to the number (each wheel turns only while the one below passes 9 -> 0); land it by ~1.25 s and keep a slow push so the settled chart never sits still. Drawn on the canvas, the number is texture; a figure the viewer must read goes in the DOM, held its reading time |
| words over a liquid shader | the hook: the chrome shader under one display word landed at frame 0; or type as a mask: the shader canvas under a full-frame `var(--ink)` layer with `mix-blend-mode: multiply` and the word in white, so the liquid shows only inside the letters; fly through a letter's counter (`scale` to 60 about the counter's centre, measured with a DOM `Range`, `inExpo` over the last 0.45 s) into the next ground |
| morph | `morph(canvas, {steps})`: one filled shape whose outline r(θ) blends between circle, star, square and flower on the half beats (eased), turning, with three outline echoes trailing 50 ms apart |
| pattern system | a grid of 32 tiles (quarter circles, dots, squares, wedges in the palette) each turning a quarter on every half beat, staggered a frame or so |
| line drawing | `spiro(canvas)`: a hypotrochoid drawing itself on over ~1.1 s with a white core under the ink and a glowing head, over a faint rosette of finished copies turning the other way |
| halftone | `halftone(canvas)`: a dot grid sized by the shade of a lit sphere whose light swings round, ripples of small dots outside it |

**Canvas shots draw from the stage's clip windows.** A canvas or WebGL shot drawn in `ST.onSeek` only while its
scene is on screen asks `ST.clips()` (the template's `active(id, t)` and `localTime(id, t)`): those windows are
frame-exact. A copy of the scene times in the script (`if (t >= 1.9667)`) draws the shot a frame after the cut,
and the render's first frame after it comes out blank while `snap` looks right; `check` reports it
(`late_first_frame`). `"render": {"settle": "raf2"}` does not change it.

**Flash words and the hero line.** Texture words carry the energy and may leave before they can be read, only when
marked and short (`pacing.md` §1); the name or the one message is held its full reading time (`no_hero_line`).
Shot tags ("01 Shader") are one system: the same corner, every technique shot, or none.

**What the critic flags in reels** (round-1 findings): a placeholder name on the end card; specks on 3D metal; every
cut a hard cut with no shot turning into the next; a tag system that starts and stops; a blurred poster frame; two
empty frames before a flash word; a band colour that stops short of the frame; moire in thin far rings; a quiet hook
under a frame-0 hit; a particle shot that ends as sparse dust.

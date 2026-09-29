# Motion craft: easing, timing, stagger, holds, camera moves and what reads as cheap

Read this when you are choosing how things move in a video (DOM components, canvas films, or
custom code), reviewing a draft that "feels off", or setting motion defaults for a new theme.
Component options: `references/components.md`. Scene handoffs: `references/transitions.md`.

## 1. The five rules that matter most

1. **Smooth beats bouncy.** Default to a strong ease-out (`power3.out`, or `premium` =
   cubic-bezier(0.16, 1, 0.3, 1)). Overshoot (`back`, springs with damping < 0.8) only in an
   explicitly playful register, and never on blocks of text.
2. **Reveal as it is said.** Nothing appears before the narration mentions it; spread reveals across
   the scene (especially the back half) instead of dumping everything in the first second and then
   freezing (the "slideshow" failure).
3. **Hold after it lands.** At least 0.5 s (short-form) or 1 s (explainer) of stillness after a move
   before the next change; 1.5-2.5 s for anything that must be read or understood.
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

## 6. Camera moves

| move | numbers |
|---|---|
| push-in (focus) | scale 1.00 -> 1.04-1.08 over the whole shot, `sine.inOut` or `camera` |
| punch-in (emphasis) | 1.0 -> 1.15-1.3 in 0.25-0.4 s, `power3.out`, hold >= 1 s; never in launch, promo or explainer films, and never on every jump cut (viewers read it as cheap) |
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

Text-only scenes longer than ~2.5 s need some motion or `check`/`qa` flag a still hold: a 5-7 % push
over the scene (`.cam` wrapper, `sine.inOut`) is enough. Thin moving parts (a 2 px ruler fill, a small
pulse, a grey label) do not count as change, and a small restyle (a 3 cqh bold label made 2.4 cqh grey)
can drop a scene back under the threshold; re-run `check` after type changes. On dark frames a slow
push changes few pixels, so give it 7-8 % or pair it with another beat.

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

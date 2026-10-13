# Workflow: living diagram (a system explained over time)

Read this when the user wants how something works shown as a figure that builds and moves: a machine, a
process, a pipeline, an architecture, a market, an organ, any system of parts and flows ("show how a heat pump
works", "explain what happens when you press Enter", "animate this mechanism"). The build is the `diagram`
template: one isometric scene spec drawn by `/_st/diagram.js` as a pure function of time, in a light (paper)
or dark (night schematic) theme. For numbers that change use `data-story.md`; for math use `manim.md`.

## Essentials

- Defaults: 15-25 s, 16:9 at 1920x1080, light theme (`--theme dark` for the night schematic, `--theme white` for
  white with colour only where it means something), a voice
  that names each part as it matters, a quiet bed ducked under it; every invented number marked
  "Illustrative sample" on screen (§ Defaults)
- One line to a spec: list the parts, how they connect, what flows and in which order things happen;
  parts arrive in the order that explains them (§ Steps, § Scene spec)
- `showtime new diagram <job>/project --duration <s> [--theme light|dark] [--example enter|market]`; edit `scene.js` (CUE beat times,
  `window.SCENE`), the page words in `index.html` or the scene's `page` block (§ Steps)
- Pieces: `part:` from the library (machine parts, `node` icons, `stack`, `store`, `queue`), pipes and links
  joined by port name, flows, packets (`tokens`), states and pulses, labels, tags, camera, focus (§ Scene spec)
- Narrated: write `narration.md`, `showtime voice script ... --fit <s> --estimate`, then without it;
  `showtime voice cues ... --offset <voice start>`; load `voice/cues.js` before `scene.js` and land beats on
  words (§ Steps)
- `showtime check`: 0 errors and every WARN read; a `diagram:` warning names a label that collides (move
  the part, give the label an `elbow`, or shorten it) (§ Labels and layout)
- Poster: a separate still at the "all built, camera at rest" time (`"poster"`), never baked into frame 0:
  keep `"render": {"poster_bake": "off"}` (§ Pitfalls)
- Render, `showtime qa <job>`, `showtime review-pack <job>` and the critic round (§ Steps)
- A figure people poke: `showtime export html <project> --interactive [--target artifact]` writes
  `<slug>-figure.html`, one offline file: the board is live from the first frame (hover a part, pick a step, turn a
  knob). The scene says what is interactive in `interactive` (steps, knobs, readouts, a tour); `--example
  econ-lab` and `--example enter` show both kinds (§ Interactive)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inputs | 47-51 |
| Defaults | 53-59 |
| Steps | 61-88 |
| Scene spec | 90-132 |
| Labels and layout | 134-151 |
| Themes | 153-158 |
| Interactive | 160-204 |
| Pitfalls | 206-223 |
| Read next | 225-228 |

## Inputs

- The subject and its source: docs, a paper, a datasheet, the user's own words. Every on-screen claim traces to it.
- What the viewer must understand at the end, in one sentence (the dek line).
- Helpful: the theme (light or dark), length, whether there is a voice, a brand kit.

## Defaults

15-25 s, 16:9 at 1920x1080, 30 fps, the light theme (paper, near-white solids, one hairline weight, two
accents); the dark theme when the user asks for dark or night. A voice (`af_heart` or `am_michael`) naming
each part as it lights up, 2.5-3 words per second; a quiet `minimal-pulse` or `underscore` bed ducked under
it. Labels name a part and say what it does in under 40 characters; numbers are sourced or marked
"Illustrative sample". State the theme and the voice as assumptions.

## Steps

1. **Job.** `showtime job init <topic>-diagram --request "..."`; note `<job>`.
2. **Understand the system.** From the source, write down the parts, the connections, what flows between
   them and the order of events. Pick 4-8 parts; more crowds a 1920x1080 frame. Write the one sentence the
   viewer keeps; it becomes the dek.
3. **Project.** `showtime new diagram <job>/project --duration <s>` (`--theme dark` for the night look). It
   starts with a working heat-pump scene; `--example market` (a matching market of nodes and envelopes) or
   `--example enter` (a coding agent's loop across your machine and the cloud) starts from another scene at
   that scene's own length, so `--duration` and a later `showtime retime` scale from the right base. Each
   example carries its own title block in `page`. Copying a file from `examples/` over `scene.js` by hand
   keeps the template's length: set `"duration"` in `showtime.json` to the copy's `CUE.duration` first.
4. **Spec.** Edit `scene.js` (§ Scene spec): the CUE table first (one beat time per line, so `showtime retime`
   moves them), then the items, flows, tokens, states, labels, tags, camera.
5. **Voice (narrated films).** One `## <id>` line per beat in `narration.md`;
   `showtime voice script <job>/project/narration.md -o <job>/project/voice --fit <s> --estimate`, cut words
   until it fits, then the same command without `--estimate`. Then
   `showtime voice cues <job>/project/voice/timeline.json -o <job>/project/voice/cues.js --offset 0.4`,
   add `<script src="voice/cues.js"></script>` before `scene.js` in `index.html`, and set beats from
   `VO.words.<line>[i][1]` (see `templates/diagram/examples/enter.js`). Put the voice in `audio/mix.json` at `"start": 0.4` with
   the bed ducked under it, and `"audio": "audio/mix.json"` in `showtime.json`.
6. **First look.** `showtime check <job>/project` (0 errors, read every WARN), then
   `showtime snap <job>/project --at <t>` at each beat and `showtime look <job>/project`. Fix what you see:
   crowded tags, a leader across the figure, a part hidden behind another.
   *Done when:* check reports 0 errors and no `diagram:` warning.
7. **Render and verify.** `"poster"` at the all-built moment, `"render": {"poster_bake": "off"}`;
   `showtime render <job>/project --job <job>`, `showtime qa <job>` (quote LUFS and true peak),
   `showtime review-pack <job>` and the critic round (`references/review.md`).

## Scene spec

`window.SCENE` in `scene.js`. World units are isometric: x runs to the lower right, y to the lower left,
z up; times are seconds; `world: {scale, origin}` maps them to the 1920x1080 page.

- **items**: everything in the world.
  - Parts: `{id, part, at, size, build, lift, ports}`. Machine parts `plate` (the ground; any z for a raised
    platform, `faces: 'coolFaces'`, `glass: true` for another material), `floor`, `wall` (cut, hatched), `box`, `slab`, `unit`, `compressor`,
    `tank`, `valve`, `cassette`. System pieces: `node` (`icon`: person, school, building, house, bank, firm,
    server, terminal, hub, core, gate, files, lamp, tool; `seats: n`, `seatSide`, `scale`, `glass: true` for a glass
    shell around a lit core), `stack` (cells that grow on
    `count: [[t, n], ...]`), `store` (a tray whose `fill` is keyed in t), `queue` (slots).
  - `build` is when a part arrives (it drops `lift` units and fades in over 0.6 s); the build order is the
    explanation order.
  - Ports: every part has named attach points (`top`, `bottom`, `x+`, `x-`, `y+`, `y-`, a node's `center`,
    `seat1`...); add your own with `ports: {name: {at: [dx, dy, dz], face}}` relative to `at`.
  - Pipes `{kind: 'pipe', from: 'part.port', to: 'part.port', route: 'xy', tone, build: [t, dur]}` route
    along the axes in `route` order with rounded bends and collars; links `{kind: 'link', ...}` are thin
    straight lines (`dash`, `w`, `arc`); floor links sit under the parts.
  - `{kind: 'air', ...}` wavy streams; `{kind: 'floortext', at, text, at0, dir}` mono caps in the floor plane.
  - Shapes for anything else: `shapes: [{kind: 'box' | 'cyl' | 'ball' | 'face' | 'line' | 'fins' | 'fan' |
    'hatch' | 'ghost' | 'bloom' | 'ring' ...}]` (`glass: true` on a box).
  - Depth: parts, pipes and links are sorted once at mount from their boxes plus the port rule. Settle a wrong
    order with `behind: [ids]` / `front: [ids]` on an item, or `order` (a number, lower first among equals);
    `depth: 'list'` on the scene draws in list order. A cycle is reported. `explode` and `lift` offsets do not
    re-sort, so keep exploded parts from passing each other.
- **flows**: `[{at, speed, spacing, path: [{pipe}, {gap: px}, ...]}]` dashes (light) or glowing beads (dark)
  over pipes and hidden gaps; they take the pipe's tone.
- **tokens**: discrete packets, `{id, tone, r, shape: 'chip' | 'envelope', size: [w, d, h], moves: [{at, dur,
  along: 'link', reverse, off: [dx, dy, dz]} | {at, dur, to: 'part.port' | [x, y, z], from, hop, off}], tones:
  [{at, tone}], until}` (a puck without `shape`); the last move that started wins, so any t is closed form.
- **states**: `{target, at, tone}` changes a part's or pipe's tone; `{..., pulse: true, dur}` lights it up and
  lets it fall back. Tones: `cold`, `hot`, `warm`, `ok`, `mute`.
- **labels**: `{for: part, at, title, sub}` placed by the layout pass; `elbow: [dx, dy]` and `side` override;
  `until` (it leaves) and `back` (it returns, e.g. for the end).
- **tags**: pills on a part, pipe (`f`), point or packet: `{for | pipe | anchor | token, text, at, until, off,
  align, size}` or `keys: [[t, text, tone], ...]` for a value that changes (each value is its own persistent
  text). Typed: `type: [t0, t1]` reveals it left to right with a caret, `typeFrom: n` characters already there,
  `caretUntil`; `press: t` (with `pressTone`) presses it like a key.
- **focus**: `[{part, with: [...], at, until}]` veils the rest; **camera**: keys `{at, dur, zoom, focus: part |
  [x, y, z] | [sx, sy], to}` run in order; **explode**: `{at, dur, back, offsets: {id: [dx, dy, dz]}}`.
- **steps** (`.ld-steps` beat lines), **reveal** (`{sel, at}` page elements), **page** (kicker, title with
  `*accent*`, dek, footers).

## Labels and layout

Each label tries candidate elbows around its anchor and scores them at every camera pose it is shown in:
parts it would cover (veiled parts count less), pipes, floor text, tags, the page's title block and footers,
other labels, leaders crossing parts or other leaders, the safe zone, and a preference for pointing outward.
A label still colliding at the pose where it lands is reported as `[showtime] diagram: label "X" collides:
...`, which `showtime check` lists as a warning: move the part, give the label an `elbow`, or shorten its text.
A leader drawn across a part is reported the same way, as `leader across part X`, with two exemptions: the
label's own part, and a part whose outline already holds the anchor (a unit hung on a wall), both count only past
the leader's halfway point, because any leader leaving them crosses their first stretch.
At later camera poses it is placed to avoid collisions but not reported: there it fades out instead (below).
Any label, tag or floor text that never shows fully inside the text safe zone (cut by the frame, or in the
bottom 8 % under phone controls) is reported too: `"X" never shows fully inside the text safe zone`.
`Diagram.report` in the page holds the depth order and each label's placement.

Text stays check-friendly by construction: labels, tags, floor text and steps are persistent nodes, text fades
take at most 0.2 s, floor text is raised to 25 px on screen, and any text fades out before the camera carries
it off the frame.

## Themes

`<html data-theme="light|dark">` (set by `--theme`) picks the tokens in `Diagram.themes` and the page styles
in `/_st/diagram.css`. Light: warm paper, near-white solids, ink hairlines, dashed flows, solid pills,
Instrument Serif title. Dark: night ground, steel line work, glowing beads, outlined pills, Space Grotesk.
The same spec renders in both; check and render each theme you ship.

## Interactive

The same scene is also a live figure: `figure.html` in the project (`<html data-st-live>`, preview it with
`showtime preview <project> --page figure.html`) and `showtime export html <project> --interactive` for one offline
file, `<slug>-figure.html` (`--target artifact` for an HTML artifact, `-o` to name it). No play button and no
timeline: the board is built and moving from the first frame; the viewer hovers or tabs to a part (the focus veil
lights it and its own pipes and links; a card says what it is and its value), picks a step (an experiment that runs
on the board), turns a knob (the step runs again: levels, stacks and tags answer at once). Untouched, a tour of the
same live actions plays; any input stops it, and it comes back after 20 s. Keys (arrows, 1-9, R, Esc, L), deep links
(`#step=cost&rule=3&part=infl`), reduced motion (still; input works), a pause when hidden or off screen, and a phone
layout (the words leave the drawing for the panel) come with it. The file makes no network request (a
Content-Security-Policy blocks it); it embeds the runtime, the scene and every word and number in it, so sharing or
publishing the file shares all of that.

`SCENE.interactive` says what is live; everything else comes from the scene:

- `title`, `sub`, `source` (a line under the readouts), `parts: [{id, name, sub}]` (the hover cards and the parts
  list, in tab order; default: the labelled parts), `crop: {desk, phone}` (the stage area shown), `camera` (the live
  page's own framing), `start` (the live clock starts at this film time: a film-first scene starts after its build).
- `steps: [{id, kicker, text, knob, narr, run(fx, again)}]` and `reset(fx)` (the resting board, before every step).
  `text` and `narr` may be functions of the knobs' values. `run` writes through `fx`, at the step's moment plus each
  call's `{delay}`: `level(store, 0..1)`, `count(stack, n)`, `say(tag, text, tone)` and `hide(tag)` (a tag by its
  `id`), `pulse(part, tone)`, `tone(part, tone | null)`, `show(part, on)`, `send(token, moves, {stay})` (moves as in
  `tokens`, times relative to the call), `park(token)`, `focus(part)`, `every(ms, fn, name)`. `again` is true when
  only a knob moved: retarget without a new shock. Give each call for one target in time order.
- `knobs: {name: {label, hint, options: [[value, words]] | min, max, step, format(v), default}}`; a step names its
  knob. `readouts(state, stepId) -> {rows: [{part, k, v, u, tone}], note}`: the numbers under the figure (the hovered
  part's row is marked; `tone` colours it). Every number shown comes from the scene's data, never typed into words.
- `keys: {a: {label, step, when(state), run(fx, state, stepId)}}` for answers the scene asks for (the Enter example:
  Allow (A), Deny (D)); with a `label` it is also a button on that step while `when` holds (phones have no keys), and
  `agree(state, stepId, {board, step, readouts}) -> [contradictions]`: what the board's tags, the step's words and the
  readouts must agree on (the walk reports each one). Keep a knob for a setting and the state for an answer.
- `tour: [[action, ms]]`: `{step}`, `{knob: [name, value]}`, `{hover: part | null}` or `fn(fx, state)`.
- `film: 'tour'` makes `index.html` film the tour on the film's clock (a live-first scene, like econ-lab): set
  `CUE.duration` to the tour's length. Without it the film is the scene's own timeline (like enter).

The engine underneath is `Diagram.live(spec, {live: {now}})`: `set`, `fire`, `focus`, `tone`, `show`, `hit` write
keys at a moment, so any time is still drawn as a pure function of the clock. `--theme white` is the live figure's
look; `--theme` sets both pages. `showtime check` walks the live figure too, at rest: every step x each knob value
(every option; every value of a range of up to 25, else 9 across it) x each hovered part, and each of the scene's
keys pressed from each step and value. It reports text cut by the figure's frame (`figure_text_cut`), texts that
overlap (`figure_text_overlap`, naming the state), a readout showing NaN or Infinity, a link that, followed, opens
another state or two steps sharing an id (`figure_link`), what `agree` says (`figure_story`), a step that throws,
sideways scroll or text under 12 px on a phone. Not walked: the moments while a step plays (a tag that shows for 2 s
on its way), the tour's own function actions.

## Pitfalls

- A poster baked into frame 0 flashes the finished diagram before the build: keep `poster_bake` off.
- Anything on the floor layer (plates, floors, floor links, rings, ghosts) fades out under a footer line while that
  footer is on screen (an SVG mask on the floor layer); a part, packet or tag the camera carries under a footer draws
  behind its text. Keep camera moves from parking parts under the footers. The holes are measured once, when the
  diagram mounts: set the footer text in `page`, not from a script later.
- Times typed into the spec instead of CUE: `showtime retime` cannot move them.
- Tags placed by hand can sit on floor text or each other; check reports `text_overlap`: move one by its
  `off`.
- Too many parts: past about 8 the labels have nowhere to go. Split into two figures or drop a part.
- Text on a beat shorter than its reading time (a tag value that changes too fast): `short_text`. Hold each
  value at least 1 s.
- A link ending inside a part draws over it: end it on a front face port (`x+`, `y+`, `top`) or let the
  port rule put it behind (`x-`, `y-`, `bottom`).
- Invented numbers without "Illustrative sample" on screen (`story.md` §6).
- A live tag and a part share an id (a tag naming the part): `say` sets the tag, `level`/`count` the part. A string
  is always a tag's text, a number always a level or a count.

## Read next

`references/voice.md` (fit, cues), `references/audio.md` (mix, ducking), `references/stage-api.md` (the time
contract), `references/review.md` (the critic round), `references/html-export.md` (sharing; `--interactive`).

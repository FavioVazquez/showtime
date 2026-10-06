# Showreel (16:9, 15 s): fourteen shots on a 120 BPM grid, no technique twice, the name landing on the last beats

The go-all-out recipe for a showreel, a hype reel or a "show what you can do" brief (`references/tones.md`,
"showreel"; `references/motion-craft.md` section 11). `showtime.json` sets `"tone": "showreel"`, so `check`
lets flash words go before their reading time, `qa` judges density, the ending and repeats instead of the launch
grammar, and the critic gets the showreel rubric (energy, density, variety, craft, surprise, ending).

Built to the bar of the 2026-10-05 blind rematch: the reel that won kept cutting to the last second (13-14 shots,
a new kind of shot every time, the name landing late and short); the takes that held their name for 3-4 s lost.

Files:
- `showtime.json`: 1920x1080 at 30 fps, `"tone": "showreel"`, `"audio": "audio/mix.json"`, poster at frame 0
  (the hook is landed there).
- `audio/mix.json`: a generated `upbeat-tech` bed at 120 BPM (a build, the drop on the particle burst at 2 s, an
  outro under the name) and one hit per shot on its cut, ticks under the counter, mastered to -14 LUFS. No downloads.
- `reel.js`: small deterministic techniques, original code with no dependencies: `shaderLayer` (a full-frame WebGL
  fragment shader), `burst` (a closed-form particle burst on a beat), `tunnel` (a fly-through of rings), `chart`
  (bars on a spring, a line drawing on, a ring gauge and an odometer counter), `morph` (one shape blending through
  outlines), `spiro` (a line drawing drawing itself on), `halftone` (a lit sphere in dots) and `localTime`
  (seconds into a scene). Every draw is a function of time only.
- `index.html`: the reel. Fourteen shots (seconds), each a different technique:
  1. **hook** (0-1): words over a liquid chrome shader, landed at frame 0 and settling.
  2. **flash** (1-2): three flash words, a third of a second each (`data-st-flash`).
  3. **burst** (2-3): a particle burst on the drop.
  4. **object** (3-4.25): an iridescent three.js torus knot lit by a generated room (`RoomEnvironment`, nothing
     fetched), the camera dollying in.
  5. **glitch** (4.25-5): RGB split and sliced copies on red (pseudo-elements, so the word is audited once).
  6. **bands** (5-5.75): kinetic type bands sliding in opposite directions (texture: flash words).
  7. **data** (5.75-7.5): live data: bars spring up, a line draws on, a ring closes, a counter rolls to its number,
     then a slow push (drawn on the canvas: texture, not a figure to read).
  8. **morph** (7.5-8.25): one shape turning circle, star, square, flower on the half beats.
  9. **grid** (8.25-9.25): a shape system, 32 tiles turning a quarter on every half beat.
  10. **tunnel** (9.25-10.25): a fly-through of rings whose centre opens into the next shot's pink ground (a match).
  11. **spiro** (10.25-11.5): a line drawing drawing itself on with a glowing head.
  12. **halftone** (11.5-12.5): a sphere in halftone dots, its light swinging round.
  13. **mask** (12.5-13.75): type as a mask, a hot shader inside the letters, then a fly-through the O into the
      end card's dark ground (a match).
  14. **end** (13.75-15): the name tracks in on the beat, a light sweeps it, the frame keeps pushing; it holds its
      reading time (1.25 s) and no more.

Shot tags (`01 Shader` ... `12 Mask`) are one system: the same corner on every technique shot (flash words).

Slots (search for `SLOT:`): the hook word, the three flash words, the glitch word (and its `data-text`), the
band words, the counter's number and label, the mask word (keep an O: the camera flies through it), the name and
the role. Swap a shot for the maker's own work (a clip in a `<video>`, a still with a push) when there is any:
real work beats a stock technique. Swap a technique for another kind, never for a second copy of one already in
the reel (qa warns `showreel_repeats`).

Flash words: `data-st-flash` marks texture (at most 3 words and 24 characters, on screen 0.2 s or more); in the
showreel tone they may leave before they can be read. The name on the end card is not texture: it is on screen
1.25 s (its reading time), and `check` warns `no_hero_line` when nothing is held its reading time. A longer name
needs a longer end card: take the time from a shot, and keep the card moving (qa warns `showreel_long_end` when it
holds still over 10% of the reel).

Rendering: the shaders and three.js need WebGL (`--gpu auto`, the default; on Linux without a GPU the software
path works, more slowly). Keep `preserveDrawingBuffer: true` on every WebGL canvas. The shader canvases draw at
0.75 of the frame size and are scaled up (they are soft by design); raise `scale` for sharper detail at the cost
of render time.

Commands: `showtime preview .`, `showtime check .`, `showtime render . --preview`, `showtime render .`

Length: the shots sit on a 120 BPM grid (a beat every 0.5 s, cuts on beats and half beats). `showtime retime <dir>
-d <s>` scales the scenes and the mix together; pick a length that keeps the cuts on beats (30 beats is 15 s, 40
beats 20 s) or change the `bpm` in `audio/mix.json` to match.

Other aspects: the reel is laid out for 16:9 and recomposes itself for tall and square frames, so `showtime render .
--size 9:16` (or 1:1, 4:5) needs no edits and `showtime check . --size 9:16` passes. Type scales by the frame's
shorter side; on a tall frame the shot tags and the centred words sit inside the vertical safe box (clear of the
platform UI), the name wraps to two lines, the tile grid turns 4x8, two more type bands fill the height, the chart
stacks the counter over the bars, and the 3D camera pulls back. Keep those rules when you swap a shot.

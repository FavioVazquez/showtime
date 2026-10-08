# Go all out: a showreel

Sometimes restraint is the wrong brief: a showreel, a hype reel, "show what you can do". showtime has a tone and a
template for that, a shutter blur for fast snaps, and seven looks drawn in its own WebGL that need no GPU. This
guide shows what to say and what your agent does.

## Say this

> "Go all out: a 15-second showreel for Northlight, 16:9 and 9:16."

The words "showreel", "demo reel", "hype reel", "go all out" or "show off" set the tone by themselves. Give the
name, the one line it should land on, and any real work to show (clips or stills): real work beats a stock
technique.

## What happens

1. `showtime new showreel <job>/project` copies a working reel: fourteen shots on a 120 BPM grid, each a
   different technique (a liquid chrome shader, flash words, a particle burst, a 3D object, glitch, kinetic type
   bands, live data, a morph, a tile system, a tunnel, a line drawing, halftone, type as a mask), and the name
   landing on the last beats. `showtime.json` sets `"tone": "showreel"`.
2. Your agent fills the `SLOT:` words (the hook, the flash words, the name and role) and swaps shots for your
   own work, never for a second copy of a technique already in the reel.
3. Flash words snap in under a shutter blur (`data-st-blur`): smeared only on the 4-7 frames they move fast,
   sharp when they land.
4. Looks on request: `fluted-glass`, `tilt-shift`, `liquid-metal`, `mesh-gradient`, `god-rays`, `marble` and
   `metaballs` (`showtime motion` lists them).
5. `showtime check <job>/project`, then `--size 9:16`: the reel re-lays itself for tall and square frames with
   no edits.
6. `showtime render <job>/project --job <job>` (and `--size 9:16`), then `showtime qa <job>`. In this tone qa
   wants at least 12 shots per 15 s, an end card still for at most 10 % of the reel and no two shots alike.
7. A critic reviews it against the showreel rubric: energy, density, variety, craft, surprise, ending.

## What you get

- `final.mp4` (1920x1080, 30 fps) and `1080x1920.mp4` for the tall cut, with a generated 120 BPM bed mastered to
  -14 LUFS, one hit per cut.
- The project, with every technique in `reel.js` as plain code you can read and change.

## How long it takes

Measured without a GPU on a 64-core Linux machine: a 15 s WebGL showreel test page (450 frames) rendered in
21.5 s with 4 workers; [the looks demo](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/_looks) (552 frames at 720p) in 7 s with 8 workers.
On a busy 6-core Intel Mac with its GPU, the same 15 s showreel page took 56.1 s.

A small machine without a GPU is much slower on WebGL: on the same 6-core Mac with its GPU turned off, a
shader-heavy 1080p scene took about 0.5 s a frame, so a 90 s WebGL piece takes about 22 minutes there. 60 fps
doubles the render time. Each blurred word adds about 8 ms to the frames it blurs, at 1080p without a GPU.

## Phrases that change it

- "60 fps" sets `--fps 60` (smoother fast motion, twice the frames).
- "20 seconds" retimes the reel; keep the cuts on beats (40 beats at 120 BPM is 20 s).
- "Square" or "4:5" renders those sizes too.
- "Put it on marble" or "god rays behind the name" asks for a look.
- "Calmer" leaves this tone; say which tone you want instead.

## Limits

- Restraint loses this brief, but legibility still wins: the name is held for its reading time, and flashes
  stay within the safety limit of 3 a second.
- Without WebGL each look draws a still or simpler fallback, and `showtime check` says so.
- `showtime check` warns when a look costs more than 50 ms a frame without a GPU. Keep one look per scene on a
  small machine.

## The example

<!-- example: 30 -->
[The looks demo](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/_looks) shows all seven looks in one 18 s page;
[the blur demo](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/_blur) shows four snaps with and without the shutter blur. The tone's rules are
in [tones.md](../../skills/showtime/references/tones.md); the looks in
[components.md, section 7](../../skills/showtime/references/components.md).

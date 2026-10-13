# Make a living diagram, and a live figure

Some things are easier to see than to read: a heat pump, a market, a coding agent's loop. A living diagram draws
the system as an isometric figure and explains it over time: parts arrive in the order that explains them, pipes
and links join them, flows and packets move through them, labels land when their part matters, and the camera
chooses what to look at. The same scene also exports as a live figure: one offline page people hover, step
through and tune.

## Say this

> "Make a 25-second diagram of how a heat pump moves heat, light theme, with a voice."

> "Now make it a live figure I can put on our docs page."

## What happens

1. `showtime new diagram <job>/project` starts from a working heat-pump scene. `--example enter` (a coding agent's
   loop), `--example market` (a matching market) or `--example econ-lab` (households, firms and a central bank)
   start from the other finished scenes; `--theme dark` or `--theme white` changes the look.
2. Your agent writes the system into `scene.js`: the parts and their ports, the pipes and links, what flows, the
   labels, the camera, and a table of beat times, so `showtime retime` can move them later.
3. `showtime check` reports a label that collides with another or never shows whole, and text too small for a phone.
4. For a narrated film, the beats land on the voice's words; `showtime render` makes the video.
5. For the live figure, the scene declares what is live (steps, knobs, readouts, the parts to hover) and
   `showtime export html <project> --interactive` writes `<slug>-figure.html`. `showtime check` walks every step,
   each knob value and each hovered part of it first.
6. To let people touch it, the scene can also take typing (`interactive.type`), a click on a part (`parts[].press`) or a
   drag on a part that turns a knob (`parts[].drag`). `--example typewriter` (type on it) and `--example computer`
   (what happens when you press a key) start from finished ones; the heat pump drags its outdoor unit to set the weather.

## What you get

- A film: a 16:9 video at 1920x1080, 15-25 s by default.
- A live figure: one HTML file that opens offline and makes no network requests. No play button: the board is
  live from the first frame. Hover a part to light it and read what it is, pick a step to run it on the board,
  turn a knob and the numbers answer; untouched, a short tour plays. Keys, links to a state
  (`#step=cost&rule=3`), reduced motion and a phone layout come with it. `--target artifact` makes a version for an
  HTML artifact.

## How long it takes

Tried for this guide on `--example enter` as it ships (27 s, a composed bed, no voice), on a 6-core Intel Mac:
`showtime check` took 28 s and the 720p render 47 s of capture (3 workers). The live figure is a separate,
short export of the same project; its time was not measured.

## Phrases that change it

- "Dark" or "a night schematic" sets `--theme dark`; "plain white" sets `--theme white`.
- "Longer" or "30 seconds" sets `--duration`; the beats scale with it.
- "Let people change X" adds a knob to the live figure; "show the numbers" adds readouts under it.

## Limits

- Pick 4-8 parts; more crowds a 1920x1080 frame.
- Every on-screen claim needs a source, or the figure says "Illustrative sample".
- The live figure carries every word and number of the scene, so sharing the file shares all of that.

## The example

[The living diagram demo](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/_diagram) is the Enter loop as a film and two live figures; one of them
is live on [its page on the site](https://faviovazquez.github.io/showtime/examples/_diagram.html). Your agent's
guide: [diagram.md](../../skills/showtime/references/workflows/diagram.md).

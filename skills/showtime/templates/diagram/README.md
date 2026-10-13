# Living diagram: a system that builds, flows and explains itself, as a film and as a live figure

An isometric figure drawn by `/_st/diagram.js` as a pure function of time: parts arrive in the order that
explains them, pipes and links join them by port name, flows and packets move through them, labels land
when their part matters and the camera chooses what to look at.

- `scene.js`: the spec (`window.SCENE`) and the `CUE` table of beat times (one per line, so
  `showtime new diagram --duration` and `showtime retime` move them). It starts as a heat pump.
- `examples/market.js` (a matching market: nodes, links, envelopes, steps) and `examples/enter.js` (a coding
  agent's loop across your machine and the cloud, narrated): `showtime new diagram <dir> --example market` (or
  `enter`) starts from one at its own length.
- `examples/econ-lab.js`: a three-equation economy (households, firms, a central bank) as a live-first figure:
  steps are experiments, the rule strength and a promise's horizon are knobs; its film is its tour.
- `examples/computer.js`: what happens when you press a key, as a live figure you type on: the key goes down,
  the matrix finds it, its USB HID code waits for the poll (a knob), the CPU takes an interrupt, the editor puts the
  character in RAM, the GPU draws it and the screen shows it at its next refresh; its film is its tour.
- `index.html`: the film's page (title block, corner notes, footers) and the fonts of the themes. The theme is
  `<html data-theme>`: `showtime new diagram <dir> --theme dark` (or `white`) sets it, with `"theme"` and
  `"background"` in `showtime.json`.
- `figure.html`: the same scene as a live figure (hover a part, pick a step, turn a knob), from the scene's
  `interactive` block: `showtime export html <dir> --interactive` makes it one offline file.
- `audio/mix.json`: a quiet bed; add the voice track for a narrated film.

The guide: `references/workflows/diagram.md` (`showtime guide diagram`). The poster is a still at the end
(`"poster"`), never baked into frame 0 (`"render": {"poster_bake": "off"}`): the film opens on the empty plate.

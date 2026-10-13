# The X-ray mechanism library

One folder per kind of object, each a drawing of its inside that the `xray` template moves on the events measured
from a clip (`showtime new xray <dir> --mechanism <object>`):

- `mechanism.js`: `XRAY.mechanism({name, noun, one, box, anchors, outline, headline, measured, drawn, draw})`.
  `box` and every point are in the mechanism's own design space; `anchors` are four named points a clip places
  on its object (`showtime.json` `"xray".place`); `draw(k)` draws one frame with the kit `xray.js` hands it:
  `k.seg/ell/poly/path/dot/label`, `k.env(i)` (0..1, peaking on event i's frame), `k.cur`, `k.s`, `k.hot`,
  `k.ch` (the character the clip shows for it), `k.n` (events so far), `k.since(i)` (frames), `k.view`
  (`panel` or `inplace`).
- `diagram.js` (optional): the same object as an isometric living diagram for `--layout diagram`.
- `README.md`: the parts, what each event moves, what is measured and what is drawn, the clips it was made on.

Every entry was made on a real clip and verified (`showtime xray verify`: every event on its frame). A new one
starts as a copy of the closest entry; add it with the clip it was verified on and its receipt line.

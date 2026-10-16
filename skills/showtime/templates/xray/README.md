# X-ray: a real clip, with its inside drawn in sync and a receipt that proves it

The page shows a clip someone filmed (a typewriter, a music box) and draws the inside of the object moving on the
exact frames the clip's own sound says it did. It starts as a 9.4 s sample: an Underwood 315 typing "Sounds of
changes." (Erik Pålsson / Sounds of Changes, CC BY 3.0: keep the credit if you keep the clip).

- `xray.json`: the measured events, from `showtime xray analyze <clip> --job <job> [--track ...]` (copy
  `<job>/xray/xray.json` here). With a `track`, the inside is drawn on the object itself as the camera moves.
- `media/clip.webm`: the clip (its sound plays from `audio/mix.json`; the page itself is muted). It starts at
  film frame 0: trim the clip, never shift it.
- `mechanism.js`: the inside, from the mechanism library (`library/xray/<object>/`, `--mechanism <object>`): its
  parts, how an event moves them, the four anchor points that place it on the object.
- `showtime.json` `"xray"`: `layout` (through, split, diagram), `skip` (events that are not the object's, by
  index), `kinds` (`{"18": "return"}`), `text` (what the clip shows the events produced, one character each),
  `place` (the anchors on the reference frame of the track, in the clip's pixels), `credit`, `receipt` (the
  line `showtime xray verify` prints, for the end card).
- `cue.js`: the beats (the scan, the labels, the end card); set `endcard` to the clip's length.
- `xray.js`: the runtime (layout, drawing kit, the sync marker in the bottom-right corner: never cover it).

9:16 puts the clip on top, the inside below it (in place as well when tracked) and the sound strip over the
counters, all inside the reels safe box (the drawing too: the platform's buttons sit right of x 916) and at
the phone floor (43 px at 1920), the part labels in a column left of the drawing (two, left and right, when one
can't hold them) and never over it, the mechanism's captions in a row above; 16:9 with a track draws
in place over the whole frame (`"panel": true` keeps the schematic beside it);
16:9 without one puts the inside beside the clip. Library: typewriter, musicbox, switch (and the music entries).
The guide: `references/workflows/xray.md` (`showtime guide xray`).

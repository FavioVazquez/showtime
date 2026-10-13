# Disc music box (Polyphon, Symphonion, Regina style)

Parts: the perforated disc (drive holes on the rim), the play line from the spindle, one star wheel per track, the
comb with one tooth per pitch (bass long and at the top, treble short).

- An event = a pluck: its slot reaches the play line, its star wheel turns one tooth and the comb tooth rings,
  peaking on the event's frame; the slot then turns away with the disc, so the disc fills with what was played.
- Which tooth: from `notes.json` (`showtime xray notes <clip> --job <job> --instrument musicbox`, copied next to
  `index.html`): one track and one tooth per pitch heard. Without it, three registers by the sound's band (low,
  mid, high), said on screen.
- The disc's speed: `"xray": {"spin": <degrees per second>}`, measured from the clip (follow a mark on the disc
  over a few seconds); default 6.
- Anchors to place on the reference frame (see-through on a disc filmed face on): `rim_e` (where the play line
  meets the rim), then `rim_s`, `rim_w`, `rim_n` going clockwise from it (four rim points, no three in a line).
  Measure the spin by tracking the disc itself (`analyze --track --region` around the disc): the homographies turn
  with it; then track the cabinet with the disc masked to place the drawing.
- Analyze dense music with the flux engine (`--engine flux`, `auto` picks it when the sound never goes quiet).
- Measured: pluck times and count (the clip's sound), pitches (notes.json). Drawn: a generic disc music box; the
  slots are rebuilt from the sound, not read off the disc in the clip.

Verified on: "Music Box Plays \"Angels ever bright and fair\"", a disc music box at the Canada Science and Technology Museum
(Wikimedia Commons, CC BY 3.0, author: the museum): https://commons.wikimedia.org/wiki/File:Music_Box_Plays_%22Angels_ever_bright_and_fair%22.webm

# Drum kit (drum part and kit from above)

Parts: a percussion staff (percussion clef, the usual drum key), a fixed playhead, and a kit seen from above,
the drummer's seat at the bottom: kick (shell, batter head, pedal and beater), snare (with its wires), hi-hat,
two mounted toms, floor tom, crash and ride.

- An event = a hit: its pieces are written at the playhead, red on the event's frame: kick in the bottom space
  (stem down), floor tom, snare in the third space, mid and high tom above it (stems up), hi-hat x above the
  staff (with an o when open), ride x on the top line, crash x on the ledger line above; a beat's hits share a
  beam (a second beam for sixteenths). On the kit, each piece hit flashes and its skin ripples out from the
  centre, bigger for a louder hit; a cymbal sways and rings down; the kick's beater swings into the head.
  Every hit also flashes the playhead.
- The staff scrolls on the smooth tempo map (`k.beat`), hits on their quantized sixteenth.
- Which piece: `notes.json` `drums[]` (`showtime xray notes <clip> --job <job> --instrument drums`): a classifier
  of sound types (kick, snare, tom, hi-hat closed or open, crash), not a transcription; it does not see the kit.
  Toms are split floor, mid and high by their pitch against the clip's other toms. The ride is drawn but the
  sorter never names it.
- Analyze with `--engine flux` and skip (`"skip"`) the events with no sorted hit within 3 frames, so every red
  piece is a hit the sorter placed. `"px_per_beat"` widens the staff for fast playing.
- Split layout only: a drummer fills the frame, never see-through on a person.
- Measured: hit times and count (the clip's sound), the piece of each hit (sorted by its sound), loudness.
  Drawn: a generic kit and the drum part, not this drummer's kit.

Verified on: Lukáš Perný drum solo, KC Dunaj Bratislava 2012 (Wikimedia Commons, CC BY-SA 4.0: https://commons.wikimedia.org/wiki/File:Luk%C3%A1%C5%A1_Pern%C3%BD%2C_drum_solo_%C5%A1ou_sample%2C_KC_Dunaj%2C_Bratislava%2C_2012.webm; a film made from it is CC BY-SA too), 20-34 s, 9:16
dark: 30 of 30 events on their frame · audio 0.0 ms from the original; scroll 8.9 px/frame, 0 stalls and 0
jumps between the scan and the end card.

# Piano (grand staff and keyboard)

Parts: a grand staff (brace, treble and bass clefs and key signature drawn as paths, no music font needed), a
fixed playhead, and an 88-key keyboard (A0 to C8, middle C marked).

- An event = a strike (one or more keys at once): its notes are written at the playhead, red on the event's
  frame (stems, flags, a beam once the second eighth of a pair is heard, dots, ledger lines, accidentals outside
  the key), and their keys go down and light while they sound. Every strike also flashes the playhead, so a
  strike with no pitch heard still shows.
- The staff scrolls on the smooth tempo map (`k.beat` of the frame's time), never by jumping to the last note;
  notes sit on their quantized beat (eighths of that map).
- Which notes: from `notes.json` (`showtime xray notes <clip> --job <job> --instrument piano`). Hands: the bass
  voice on the bass staff, the melody on the treble staff, other notes with the nearer of the two. Spelling
  follows the key heard (G major: F sharp in the signature).
- `showtime.json` `"xray"`: `meter` (beats per bar; bar lines, the time signature and the bar counter appear
  only when it is set, it is not measured), `downbeat` (beat of bar 1, default 0), `key` (override or `false`),
  `min_confidence`, `px_per_beat`. Without `notes.json`, a strike is a rhythm slash, never a guessed pitch.
- Skip events before the first note (room noise) and clicks after the last one (`"skip"`).
- Measured: strike times and count (the clip's sound), pitches, key, tempo map, eighth-note rhythm (the
  notes model). Drawn: the notation itself (no rests, one stem per hand per beat, ties shown as the longer
  value), not the printed score.

Verified on: Minuet in G, BWV Anh. 114 (Notebook for Anna Magdalena Bach, attributed to Christian Petzold), recording KasraR (Wikimedia Commons, public domain), 22.2 s, 9:16 dark:
91 of 91 events on their frame · audio 0.0 ms from the original; scroll 6.0 px/frame, 0 stalls and 0 jumps
between the scan and the end card.

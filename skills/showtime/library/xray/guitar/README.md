# Guitar (tab and fretboard)

Parts: chord names, a six-line tab (string 1, high e, on top; string names on the left), the right-hand
fingers under it (p thumb, i index, m middle, a ring), a fixed playhead, and a fretboard diagram in the same
orientation (nut on the left, frets 0-12 at their real spacing, inlays at 3 5 7 9 12).

- An event = a pluck: its notes are written as fret numbers on their strings at the playhead, red on the
  event's frame, with the plucking fingers under them; on the fretboard the fretted dots (or an o at the nut for
  an open string) light while they sound and the plucked string vibrates from the fret to the bridge, ringing
  down over about a second. Every pluck also flashes the playhead.
- The tab scrolls on the smooth tempo map (`k.beat`), notes on their quantized beat.
- Which string, fret and finger: `notes.json` `guitar[]` (`showtime xray notes <clip> --job <job> --instrument
  guitar`): assigned by rule (standard tuning, open position first; p for strings 6-4, i m a for 3 2 1), not
  read from the hands. Say so on the end card (`"drawn"`).
- `showtime.json` `"xray"`: `min_confidence` (drop ghost notes: harmonics and buzz come out at 0.1-0.2),
  `chords` (`false` hides them; a name shows only when it holds for `chord_beats` beats, default 2, which drops
  passing one-beat guesses), `px_per_beat`. Skip the events with no pitch heard (finger and string noise).
- Trim the clip to the playing (`footage trim --from`): talk or tuning before it turns into ghost notes.
- Measured: pluck times and count, pitches, chords (guessed from the notes), tempo map. Drawn: the tab and
  fretboard, fingering by rule.

Verified on: fingerpicking C, Am, D, G, Em (Elenaf, Wikimedia Commons, CC BY-SA 3.0: https://commons.wikimedia.org/wiki/File:Fingerpicking_Pattern_4_p-ima_chitarra.webm; a film made from it is CC BY-SA too), trimmed from 6.0 s,
18.7 s, 9:16 dark, `min_confidence` 0.3: 33 of 33 events on their frame · audio 0.1 ms from the original;
scroll 6.0 px/frame, 0 stalls and 0 jumps between the scan and the end card.

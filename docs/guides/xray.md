# Make an X-ray of a real thing

Film something doing its thing: a typewriter typing, a music box playing, a guitar, a drum kit. An X-ray is a film of
that clip where the inside of the object is drawn moving on the exact frames the clip's own sound says it did: on the
object itself as the camera moves (see-through), or beside it. Instruments can also get their music written out from
the sound, as a score, a guitar tab or a drum sheet. Every X-ray ends with a receipt that `showtime xray verify`
prints after reading the finished film back: "19 of 19 events on their frame · audio 0.0 ms from the original".

## Say this

> "X-ray this clip of my typewriter: draw its inside on the machine as it types."

> "Here's my music box playing. Show the disc and the comb, for a phone." · "Turn this drum clip into a drum sheet."

## What happens

1. **Film it.** Keep the sound: the events are found in it. A phone and a little shake are fine; close and well lit
   beats wide and dark. A clip you did not film needs a license that allows it (CC0, CC BY, CC BY-SA) and its credit.
2. **Measure it.** `showtime xray analyze <clip> --job <job>` writes every event (a keystroke, a pluck, a hit) with its
   time and frame into `xray.json`, and `check.jpg`: the waveform with a tick per event. Your agent plays the clip at
   a few ticks and counts events against what it sees. For see-through, `--track --region "x,y ..." --ref-time <t>`
   follows the object; `--mask` leaves out hands or parts that move by themselves.
3. **Pick a mechanism.** `showtime new xray <job>/project --mechanism <object>` copies one from the
   [mechanism library](../../skills/showtime/library/xray/README.md) (a manual typewriter, a disc music box and more),
   which grows with every verified X-ray; an object it lacks starts as a copy of the closest entry. Your agent first
   names the object from three frames and writes down what moves on each event.
4. **Choose a layout and a look.** `--layout through` (on the object), `split` (beside the clip; on a phone, the clip on
   top) or `diagram` (an isometric living diagram, in the manner of the [living diagram demo](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/_diagram));
   `--theme dark` (a radiograph) or `light` (a blueprint on paper); 16:9 or 9:16.
5. **Music and drums.** `showtime xray notes <clip> --job <job> --instrument piano|guitar|musicbox|drums` reads the
   music with local models: pitches, key, chords and a smooth tempo map for a score; a string and fret per note for a
   guitar tab; every hit sorted into kick, snare, hi-hat, toms and cymbals for a drum sheet. Look at
   `check-notes.jpg` first. A score scrolls on the tempo map, never jumping to the latest note.
6. **Render and verify.** After `showtime render`, `showtime xray verify <job>` reads the final file: a small sync
   marker in a corner is white only on event frames, and the film's sound is matched against the clip's. Missing or
   extra events, or audio more than 20 ms off, fail `showtime qa`; `--band x,y,w,h` also checks a scrolling score for
   stalls and jumps. The line goes in the receipt and on the end card.
7. **Share it.** Post the receipt line and the clip's credit with the film. Add it to the
   [X-ray gallery](https://faviovazquez.github.io/showtime/xray/) with the gallery issue form, or add your mechanism
   with a pull request ([Add an X-ray mechanism](../../CONTRIBUTING.md#add-an-x-ray-mechanism)); anyone can then
   start from it with `showtime new xray <dir> --mechanism <object>`.

## What you get

- `final.mp4` at 1920x1080 or 1080x1920 with the clip's own sound, and an end card with the receipt and the credit.
- `xray.json` (every event with its frame) and `check.jpg`; for music, `notes.json`, `notes.mid` and `notes.musicxml`.
- The receipt line in the job's `receipt.md`, plus the usual poster, captions and exports.

## The live page

`showtime export html <project> --interactive --prompt "X-ray this clip of my typewriter."` writes `<name>-live.html`,
one offline file: the clip with its own sound and the inside drawn on every frame. The pads under the picture play
the next hit of their kind (on a typewriter, type the letter); drag the picture to scrub, click it for the next hit.
Space plays, the arrows step event to event, Shift+S is quarter speed, Shift+T light or dark, Shift+L the layout.
`#hit4` opens the 4th event, `#t2.5` a time; `_light`, `_split` and the rest join with `_`. The page shows your prompt
and the commands (placeholders, never your paths). To put it on a page:
`<showtime-xray src="you-live.html" ratio="16/9">` with the X-ray page's `embed.js` (a poster that loads on click), or `<iframe src="you-live.html#embed">`.

## How long it takes

Most of it is the render of a film about three seconds longer than the clip.

## Phrases that change it

- "Drawn on it", "see-through": `--layout through`; "beside it": `--layout split`; "as a diagram": `--layout diagram`.
- "Blueprint", "light": `--theme light`; "x-ray", "dark": `--theme dark`; "for Reels", "vertical": 9:16.
- "Write the music out", "as a score", "as a tab", "as a drum sheet": adds `showtime xray notes`.

## Limits

- **The inside is a generic mechanism.** Event times and counts are measured from the sound, and anything the clip
  shows (the typed text) is read from the picture; the inside is a simplified mechanism of that kind of object, not
  this exact unit, and the film says so on screen.
- **Which key, note or drum needs evidence**: the paper, a display, the notes read from the sound. Without it the film
  says "a keystroke", never a guessed key.
- **Tracking needs a steady object.** When the overlay slides (fast moves, a camera still settling, the object leaving
  the frame), trim the clip or use the split layout.
- **The drum sheet comes from a sound-type classifier.** Each hit is sorted by what it sounds like; it does not see
  which drum was struck, and two drums that sound alike can swap.
- **Dense music** that never goes quiet uses `analyze --engine flux` (picked by `auto`); very fast passages can merge.
- **Nothing leaves your machine**, but the job folder remembers: `xray/source.path` holds your clip's absolute path
  and `xray.json` its file name and sha256. Check them before you share a job folder.
- **Objects only.** An inside is never drawn over a person: a clip where someone fills the frame gets the split layout.

## The example

The [X-ray gallery](https://faviovazquez.github.io/showtime/xray/) plays every verified film with its receipt and the
commands that made it. The `xray` template starts as a 9.4 s sample: an Underwood 315 typing "Sounds of changes."
(Erik Pålsson / Sounds of Changes, CC BY 3.0). Your agent's guide:
[xray.md](../../skills/showtime/references/workflows/xray.md).

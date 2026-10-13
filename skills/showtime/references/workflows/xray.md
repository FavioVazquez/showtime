# Workflow: an X-ray of a real clip (xray)

Read this when the user has a clip of something real doing its thing (a typewriter typing, a clock ticking, a
music box playing, a bike shifting, a lock turning, a sewing machine, a stapler) and wants to see what happens
inside it: "x-ray this clip", "show the mechanism while I type", "what's going on inside when it clicks". One
clip in; out comes a film where the inside moves on the exact frames the clip's own sound says it did, with a
receipt that proves it.

## Essentials

- `showtime xray analyze <clip> --job <job>` measures the clip: every event in its sound (time, frame,
  strength, band) into `<job>/xray/xray.json`, and `<job>/xray/check.jpg` to look at (§ Steps)
- `showtime new xray <job>/project --mechanism <object> [--layout through|split|diagram]`: the inside from the
  mechanism library (`library/xray/`: typewriter, musicbox, switch, piano, guitar, drums), drawn on the tracked object (through), beside the
  clip (split) or as an isometric living diagram (diagram); counters, sound strip, sync marker, end card; copy
  the clip and `xray.json` in (§ Steps, § Mechanism library)
- Before drawing: snap 3 frames, name the object and which parts move on each event; every event moves
  something on its own frame, a strike peaks ON its frame (§ Drawing the inside)
- After the render, `showtime xray verify <job>` checks the film itself: events on their frame (from the
  sync marker) and the audio against the original clip, in ms; qa runs it too; the end card quotes it (§ Verify)
- `showtime export html <project> --interactive` writes the live page, `<slug>-live.html`: the clip with its sound,
  every event a tick to jump to, the inside drawn by the same page at that frame; one offline file (§ Live page)
- On screen, say what is measured (event times and counts) and what is drawn (a generic mechanism of
  that kind of object) (§ Honesty)
- See-through in place (`--track`, the inside drawn on the object as the camera moves): objects only,
  never people; when the overlay drifts, use the split layout (§ See-through)
- A clip the user did not film: license and credit line before you start (§ Credits)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inputs | 44-55 |
| Steps | 57-84 |
| Drawing the inside | 86-103 |
| Verify | 105-114 |
| Live page | 116-150 |
| Honesty | 152-161 |
| See-through | 163-177 |
| Mechanism library | 179-188 |
| Credits | 190-194 |
| Pitfalls | 196-204 |
| Read next | 206-210 |

## Inputs

- The clip, with its sound (events are found in the sound). A phone video is fine; shaky is fine. Close and
  well lit beats wide and dark: the inside is drawn to match what the camera shows.
- Music (a guitar, a piano, a music box): `showtime xray notes <clip> --job <job> [--instrument ...]` adds the
  pitches (notes.json, MIDI, MusicXML; key, chords, tempo map, guitar strings and frets), so the page can say which
  note, string or tooth; `--instrument drums` sorts each hit into kick, snare, hi-hat, toms, cymbals or ride
  (notes.json `drums`, a sound-type classifier, not a transcription). Dense music: `analyze --engine flux` (auto picks it when the sound never goes quiet).
- What the object is ("an Underwood portable typewriter", "a Polyphon disc music box"). If the user does not
  say, look at 3 frames and name it, then say what you assumed.
- Helpful: the part of the clip that matters (`--from/--to`), and anything the clip itself shows that fixes
  the events (the text typed on the paper, the gear being shifted to): it turns "a key" into "the key S".

## Steps

1. `showtime job init xray-<object> --request "<verbatim>"`.
2. `showtime xray analyze <clip> --job <job>`. Open `xray/check.jpg`: the waveform with every event tick,
   dropped events in grey. Play the clip at 3 or 4 of the ticks and confirm a real event sits there (a key, a
   click, a tick); count them against what you can see. Too many (releases counted as strikes): raise
   `--min-gap`; too few (soft events missed): raise `--sensitivity`. Read `dropped` in `xray.json`: it says why
   each one went.
3. Snap 3 frames of the clip (`showtime snap <clip> --at <t>`): the moment before the first event, one in the
   middle, the last. Write down: the object, the parts that move on each event, and anything that happens once
   (a carriage return, a bell, a gear change). Each kind of event gets its own motion.
4. `showtime new xray <job>/project --mechanism <object> --duration <clip length + about 3 s>`, then set
   `cue.js` `endcard` to the clip's length. Put the clip, with its sound, in `media/clip.webm`
   (`showtime footage trim <clip> --webm -o <job>/project/media/clip.webm`; the audio mix plays its sound, the
   page is muted) and `<job>/xray/xray.json` (and `notes.json`) next to `index.html`. Analyze the file you put in
   `media/`, so its frames are the film's; a 29.97 fps clip in a 30 fps film is converted by time (floor(t * 30)).
   In `showtime.json` `"xray"`: `skip` (event indexes that are not the object's: a hand bump, a cough), `kinds`
   (`{"18": "return"}`), `text` (what the clip itself shows the events produced, one character each), `place`
   (the mechanism's four anchors on the reference frame, for see-through; no three in a line), `window` (the
   see-through outline, reference-frame pixels; default the tracked region), `panel: true` (16:9 see-through
   with the schematic beside the clip), `theme` (`dark` radiograph or `light` blueprint: `new xray --theme`),
   `credit` (the clip's credit line; `own: true` for the user's own clip), `receipt`.
5. A library mechanism: place it and check (`showtime check`, `showtime look`, `showtime snap --at` an event's
   time: the struck part must sit on the real one). An object the library lacks: copy the closest
   `mechanism.js` and redraw `draw(k)` (§ Drawing the inside).
6. `showtime render <project> --job <job>`, then `showtime xray verify <job>` and put its line in `showtime.json`
   `"xray".receipt`; re-render only the end (`--from <end card start> --to <length>`).
7. `showtime qa <job>` (it runs verify again), the critic round, deliver with the credit line.

## Drawing the inside

- Draw the real kind of mechanism, simplified, not a symbol. A typewriter has a key lever, a typebar that swings
  up to the platen, a ribbon that lifts, an escapement that lets the carriage step one letter, a mainspring; a
  disc music box has a perforated disc, star wheels and a comb with one tooth per pitch; a derailleur has a
  cable, a parallelogram and a cage. Six to ten parts, each one labelled.
- Use the template's helpers: `seg`, `circ`, `ell`, `path` (lines and shapes in the panel's coordinates),
  `label` (a leader line and a tag, kept on screen), `env(i)` (0..1, the motion of event i, 1 on its frame),
  `typed(frame)` (events so far). Glow, cyan lines on the dark ground, red for what is acting right now.
- Motion rules: a strike PEAKS on its event's frame and starts 2-3 frames before (the sound is the impact);
  it settles over 5-8 frames. A part that advances (a wheel, a carriage, a counter) steps on the event's frame.
  Something that happens once (a return, a bell) gets its own, longer motion across its frames.
- Compare frames, never seconds: `xray.json` gives each event a `frame`; the template adds the film's offset.
- Counters and readouts come from the same events (keystrokes so far, rate, returns). Never a number the clip
  did not give.
- Phone sizes: labels 28 px and up, counters 80 px and up, on 1080x1920.
- Scrolling bands (a score, a tab, a timeline) follow a smoothed time-to-position curve, never a jump to the
  latest event: verify reports stalls and jumps.

## Verify

- The template draws the sync marker: a 6x6 square in the bottom-right corner, black, white only on event
  frames. Do not cover it or move it.
- `showtime xray verify <job>` reads that corner on every frame of the final film and compares the white
  frames with the events, then cross-correlates the film's audio with the clip's. It prints a line like
  "18 of 18 events on their frame · audio 0.0 ms from the original" and writes it into the job receipt.
- Missing or extra events, or audio more than 20 ms off: qa FAILs. Fix the page (an event drawn on the wrong
  frame, a trimmed clip without its offset), not the receipt.
- No marker (a page you wrote yourself): qa WARNs "unverified". Say so on delivery.

## Live page

- `showtime export html <project> --interactive` (`--target artifact` for an HTML artifact, `-o` to name it) writes
  `<slug>-live.html`: one file, no network request (a Content-Security-Policy blocks it), the clip packed once.
- The viewer plays the clip with its own sound, scrubs a timeline where every event is a tick (red kept, grey
  skipped), clicks a tick or presses ← / → to land on the next event's exact frame (shift + arrow: one
  frame; `,` `.` too, unless the pads claim them, as a typewriter's do), and Shift+S (0.25×) plays the event slowly and stops on its frame. Light or dark (Shift+T); see-through or
  split (Shift+L) when the clip is tracked. Space plays and pauses. Hovering or tapping a part label (or picking it
  under the timeline) lights it up.
- Touch: pads under the picture, one per kind of event (typewriter: a letter; instruments: a note; drums: kick,
  snare, hat; a switch: one). A pad plays the next event of its kind from the current frame and rests on it, so the
  viewer plays the clip's own sound back. Typing does the same: the typewriter's letter is its key, the other
  mechanisms take `a s d f g h j k l ;` in pad order. Dragging the picture sideways scrubs the clip; a click on it
  plays the next hit when paused, and pauses when playing.
- The picture is the film's own page at that frame: xray.js and mechanism.js (or the diagram scene) draw it, driven by
  the scrub time instead of the renderer. Nothing is drawn twice, so a page that verifies also reads right live.
- Under the picture: the receipt line (`"xray".receipt`, from `showtime xray verify`) and the credit line. No receipt
  yet: the page says so. The timeline stops at the clip's end; the sync marker is not shown (it is for verify).
- Links open a moment, as plain anchors (a host that drops `key=value` keeps them): `<file>#hit4` (the 4th event, as
  the page counts it), `#t2.5` (seconds), and the tokens `_light` / `_dark`, `_through` / `_split`, joined with `_`:
  `#hit4_light`, `#t2.5_dark_split`. The page's Link button copies one.
- Make your own with one line: under the picture, a one-line request (`/showtime x-ray ...`) with Copy, and the
  commands with Copy. The commands are written with placeholders (`clip.mp4`, `xray-<mechanism>`), never the project's own paths.
  The prompt is only what you give: `--prompt "<the request>"` on the export, else `"xray": {"made": {"prompt": ...}}`
  in showtime.json, else none (the job's request is never read). `showtime new xray` records `"xray": {"made":
  {"mechanism", "layout", "theme"}}` and nothing else. The export report (and `--json` `made`) states what was embedded.
- Embed: `<script src=".../xray/embed.js"></script>` and
  `<showtime-xray src="...-live.html" ratio="16/9" title="..." poster="..."></showtime-xray>` show a poster
  with a Play-live button and load the page on click (`autoload`: at once; `hit="4"`: opens on that event). Or a plain frame: `<iframe src="...-live.html#embed">`: `#embed` makes the
  page fit its width and report its height to the host. The page can be framed by any site (its policy has no
  frame-ancestors).
- Size: the clip is the file (the typewriter's 6.4 MB clip makes an 8.9 MB page). Over `--max-mb` (16, the artifact
  limit) the clip is re-encoded for this export only; trim it to the part that matters first.
- Big pictures on a phone: a 16:9 film at 390 px is a picture to look at; the parts list under the timeline is the
  way to the labels there.

## Honesty

- Nothing leaves the machine. The job folder holds `xray/source.path` (the absolute path of the clip, so `verify`
  finds it) and `xray.json` (the clip's file name and sha256): check them before sharing a job folder.
- Say on screen, in plain words: what was measured (the event times from the clip's sound, counts, anything
  read from the picture) and what was drawn (the inside: a generic mechanism of that kind of object, not this
  exact unit).
- Never invent which key, which note, which gear, unless the clip shows it (the paper, a display) or the user
  told you. "A keystroke" is fine; "the key S" needs evidence.
- Never put a command that does not exist on the end card.

## See-through

- `showtime xray analyze <clip> --job <job> --track --region "x,y x,y ..." --ref-time <t>` follows the object
  through the clip (points on the object, a perspective transform per frame) and writes it into `xray.json`.
  Mask parts that move by themselves (a carriage, hands over keys) with `--mask`.
- Look at the 6 frames in `check.jpg`: the outline must sit on the object in all of them. If it slides, use
  the split layout.
- Objects only, never people. A clip where a person fills the frame gets the split layout; never draw an
  "inside" over a body.
- Track the object, not its moving parts: on a turning disc, track the cabinet with the disc masked (tracking the
  disc itself measures its spin instead: the homographies turn with it). A camera that settles in the first second
  tracks badly there: trim it off.
- A mechanism that is visible in the clip (a bare switch, an open movement): mark the real parts and their
  forces instead of redrawing them over the footage; draw the schematic in the panel.
- Draw inside the object's outline (clip-path from the tracked polygon), the rest of the frame stays as filmed.

## Mechanism library

- `library/xray/<object>/`: `mechanism.js` (the drawing: design box, four anchors, `draw(k)`), `diagram.js`
  (the living-diagram scene, for `--layout diagram`), `README.md` (parts, what an event moves, what is measured and
  what is drawn, the clip it was verified on). `showtime new xray --mechanism <object>` copies one in.
- The kit `draw(k)` gets: `k.seg/ell/poly/path/dot/label` in design units, `k.env(i)` (0..1, 1 on event i's
  frame), `k.cur`/`k.s`/`k.hot` (the event acting now), `k.ch` (its character from `text`), `k.ev[i].notes`
  (its pitches from notes.json), `k.n` (events so far), `k.since(i)` (frames), `k.view` (panel or inplace).
- A new object: start from the closest entry, verify it on a real clip, then add it with its README and the
  receipt line: the library grows with every verified X-ray.

## Credits

- The user's own clip: nothing to add. Any other clip: its license and credit line before you start, in the
  job's credits so qa sees them, and on the end card. CC BY needs the credit; CC BY-SA makes the film BY-SA too;
  no license found means do not use it.

## Pitfalls

- Counting releases as strikes: a key makes two sounds (down and back); `--min-gap` merges them. Check against
  what you can see.
- A strike that starts on the event's frame looks late: the sound is the impact, so the motion peaks there.
- Seconds instead of frames: an event at 2.183 s is frame 65 at 30 fps; comparing `t >= 2.183` with the
  frame's start time (2.1667) fires one frame late.
- A filter is not an X-ray: tinting the clip blue shows nothing inside. Draw the mechanism.
- A trimmed clip without its offset puts every event early or late: set `"xray".offset_frames` in showtime.json (the page starts the clip at that film frame) and the clip's `start` in audio/mix.json to offset_frames / fps seconds.

## Read next

- `references/workflows/diagram.md` for drawn figures and their craft
- `references/editing.md` for trimming and preparing footage
- `references/qa.md` for the checks qa runs

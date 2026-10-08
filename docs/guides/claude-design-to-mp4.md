# Turn a Claude Design animation into an MP4

Claude Design builds animations as live HTML pages and has no video export. showtime takes the exported page as
it is and renders it frame by frame into a video, at 1080p with sharp text. Then you can add music, a voice-over,
captions and platform versions like any other showtime video.

## Say this

First export the design as HTML: you get a zip with `Main.dc.html`, `support.js` and a `vendor/` folder. Then:

> "Make 'Launch (12s)-html.zip' an MP4, with a music bed."

You can also give the folder you unpacked the zip into.

## What happens

1. `showtime adopt "Launch (12s)-html.zip"` unpacks the zip into a new job's `project/src/` (the zip is not
   changed), sees that it is a Claude Design export, and works out three things:
   - **Size.** The artboard keeps its aspect at 1080 on the short side: 1280x720 becomes 1920x1080, 540x960
     becomes 1080x1920. The page is laid out again at that size, so text stays sharp.
   - **Fonts.** Google Fonts links are replaced by the same font files, copied into `project/fonts/` with their
     licences, so the render needs no network and looks the same on every system.
   - **Length.** It reads the animation's own clock. A design that loops renders exactly one loop, and adopt
     checks that the last frame leads back into the first.
   It finishes with `showtime check` and prints what it found.
2. `showtime render <project> --job <job> --preview`, a quick 720p draft to look at.
3. For music, your agent picks a track (`showtime audio music pick`) or composes one, and writes the project's
   mix. For a voice-over, `showtime voice script`; for captions, `showtime captions`.
4. `showtime render <project> --job <job>` for the final, then `showtime qa <job>`.
5. Platform versions on request: `showtime deliver exports <job> --targets x,reels`.

If you change the design later, export it again and run `showtime adopt <project> --refresh`.

## What you get

- `final.mp4` in the job folder (1920x1080 or 1080x1920, 30 fps), with `poster.jpg` and `render.json`.
- `project/adopt.json`: what adopt found (size, length, fonts, whether the loop is seamless).
- `project/fonts/` with each font's licence file.

## How long it takes

Tried for this guide on a tiny hand-written page in the same format (a 640x360 artboard, 4 s), on a 6-core
Intel Mac with a load average around 50:

| Step | Time |
|---|---|
| `showtime adopt` (unpack, size, length, determinism check, `showtime check`) | 42 s |
| `showtime render --preview` (120 frames at 1280x720) | 30 s |

[Example 28](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/28-claude-design-to-mp4)'s two real designs, on a 64-core Linux machine without a
GPU: adopt took 21 s (a 12 s design) and 51 s (a 20 s loop), the final renders 10.5 s and 20.5 s. As a rule a final
render takes about 1-2 times the video's length at 1080p on a mid-range laptop (`render.md`, Speed).

## Phrases that change it

- "Make it 9:16" or "1080x1080" sets `--size`; a different aspect is centred.
- "Make it 10 seconds" sets `--duration`. On a looping design that can cut the loop short and jump at the end.
- "Add a voice-over" or "add captions" adds the narration steps.
- "As a web page too" adds `showtime export html <project>`.

## Limits

- Adopt drives the design's own runtime on a virtual clock. A page that waits for real time in ways the clock
  cannot reach (a network request, a timer it never clears) can fail the determinism check, and adopt says so.
- Offline at adopt time, the fonts cannot be copied. The summary says to run `showtime adopt <project> --refresh`
  once you are online.
- The exported `support.js` and `vendor/` are Claude Design's runtime. They stay in your project; do not
  publish them as your own code.

## The example

[Example 28](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/28-claude-design-to-mp4) adopts two exported designs, a 12 s 16:9 test and a 9:16 loop,
with a music bed each (CC BY 4.0 for the 16:9, CC0 for the loop) and before-and-after stills of the text at 100 %. The details are in [adopt.md, From Claude Design](../../skills/showtime/references/adopt.md).

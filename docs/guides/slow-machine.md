# Work on a slow machine, or one without a GPU

showtime renders on the CPU when there is no GPU: Chrome draws WebGL in software (SwiftShader). Nothing needs a
graphics card. What changes is the time, so this guide says what to expect and how to keep a small machine fast
enough.

## Say this

> "Render it, but I'm on a 4-core laptop with no GPU: draft first, and keep it light."

Your agent picks the cheaper paths below by itself once it knows.

## What happens

- **Workers.** `showtime render` picks the number of browsers by itself: 3 with a GPU; without one, one per 8 CPU
  threads, at least 3 (fewer under 5 threads) and at most 8. The log and `render.json` say why. Keep the
  automatic count unless a machine crashes with several (`--workers 1`).
- **Drafts first.** `showtime render <project> --preview` is at most 720p with a fast encode.
  `--preview --fps 12` captures 40 % of the frames: the fastest look at layout, story and the timing of cuts.
  For stills, `showtime snap` takes seconds.
- **Estimates.** `showtime check <project>` prints an estimate of the render time for this project.
- **Fix a part, not the whole.** `showtime render <project> --job <job> --from 12 --to 18` renders only those
  seconds and splices them into the job's last full render, as the next `final-N.mp4`. An unchanged soundtrack
  is reused.
- **Long runs in the background.** Any command takes `--background`: `showtime render <project> --background`
  prints a run id, and `showtime status <run-id> --wait 240` watches it.
- **Heavy looks.** WebGL looks render smaller and are scaled up (`scale`); `showtime check` warns when a look
  costs more than 50 ms a frame without a GPU. Keep one look per scene on a small machine.
- **Waits scale.** On a slow page showtime waits longer for it to get ready (up to 5 times the usual waits,
  never less), so a busy machine does not fail heavy pages.

## What you get

- The same files as any render: `final.mp4` (or `preview.mp4` for a draft) and `poster.jpg`.
- `render.json` beside each render: the worker count and why, the time per stage, and how much the waits were
  scaled for a slow page.
- A fix as the next `final-N.mp4`; renders never overwrite.

## How long it takes

Measured on a 64-core Linux machine with no GPU (Chrome drawing in software):

| 90 s video at 1080p30 | 3 workers | best count measured |
|---|---|---|
| Launch film (measured at 2,700 frames) | 2.0 min | 0.8 min (16 workers) |
| WebGL showreel (scaled up from 15 s) | about 2.2 min | about 2.0 min (4) |
| DOM page (scaled up from 15 s) | about 3.3 min | about 1.9 min (16) |

On a 6-core Intel Mac with its GPU, the same three ran at about 2.3-3.3 min for 90 s. With the GPU turned off,
the WebGL showreel there took about 22 minutes for 90 s (about 0.5 s a frame): **a 4-8 core machine without a
GPU looks like that, not like the 64-core numbers.** DOM pages without WebGL suffer much less (about 5-8 min
for 90 s on the Mac with the GPU off).

Other steps, measured:

| Step | Machine | Time |
|---|---|---|
| Cut out a speaker, 1 min of 1080p (`footage cutout`) | 6 cores of the 64-core machine | about 5.7 min (3.7 min with `--size 384`) |
| A 1 s fix spliced into a 15-30 s video | busy 6-core Mac | 12.6-20.5 s |
| Transcribe an hour, no speaker labels | 64 cores, shared | 5:40 |

Transcribing an hour on a laptop was not measured.

## Phrases that change it

- "Draft only" or "just a preview" stops at `--preview`.
- "Half size" sets `--scale 0.5`.
- "Run it in the background" adds `--background`.
- "Use at most 2 browsers" sets `--workers 2` (or `SHOWTIME_MAX_WORKERS=2` for every render).

## Limits

- No flag makes software WebGL faster with the same pixels; on a small machine the lever is fewer WebGL scenes,
  a lower look `scale`, or a lower resolution.
- 4K draws four times the pixels of 1080p and 60 fps doubles the frames: 5 minutes of 4K at 60 fps takes
  roughly 40-80 minutes or more on a laptop.
- Very long videos (over about 10 minutes) render best in sections with `--from/--to`.

## The example

No single example covers this; the numbers come from the render speed section of
[render.md](../../skills/showtime/references/render.md) and the build-box timings in
[example 24](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/24-highlights-apollo17-panel).

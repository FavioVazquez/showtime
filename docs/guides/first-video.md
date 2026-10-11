# Make your first video

Start here if you have never used showtime. Ask for a 5-second test video: your agent installs what is missing, makes
the video on your computer and checks it. You learn that the install works, and you see every step a bigger video
goes through.

## Say this

Install [uv](https://docs.astral.sh/uv/) and [Node.js](https://nodejs.org) 24 or 22 LTS (20 or newer works), check
them with `uv --version` and `node --version`, and restart your coding agent. Add showtime to it (Claude Code:
`/plugin marketplace add FavioVazquez/showtime`, then `/plugin install showtime@showtime`; other agents:
[agents.md](../agents.md)). Then open an empty folder and type:

> "Make a 5-second test video that says hello."

## What happens

1. **One line of assumptions,** before anything runs: "Quick mode: 5 s, 16:9, no voice-over; full review, say 'lean'
   for a draft pass." It asks a question only when a request could mean two different videos.
2. **Setup, the first time only.** `showtime job init` stops with "setup has not been run yet". Your agent tells you
   the download (about 0.5 to 0.75 GB, usually 2 to 6 minutes; `showtime setup --estimate` prints yours) and runs
   `showtime setup` once you say yes. A sandbox blocks it? See
   [Troubleshooting](../troubleshooting.md#setup-never-ran-or-the-sandbox-blocked-it).
3. **A job folder.** `showtime job init hello` makes `showtime-out/hello-<date>-<time>/` for everything this request
   makes ([what is in it](../glossary.md#the-job-folder)).
4. **A first look.** `showtime new dom <job>/project --duration 5` copies a starter page, fits it to 5 s and dresses
   it in a [look signature](../glossary.md#look-signature). Your agent writes "hello" into it, runs `showtime check`
   and `showtime look`, and shows you a still or a fast draft.
5. **The render.** `showtime render <job>/project --job <job>` draws every frame in a headless browser on your
   computer. Nothing is uploaded.
6. **The checks.** `showtime qa <job>` checks the file, the loudness, black or frozen stretches and the poster, and
   prints PASS, WARN or FAIL. In quality mode (the default) a [critic](../glossary.md#critic) then reviews the video;
   until it has, qa says "review pending".
7. **The delivery card:** the files, the length, the loudness, the qa verdict, the review, what was assumed, and
   three things you could ask for next.

## What you get

- `final.mp4` (1920x1080, 30 fps) and `poster.jpg`. Open `final.mp4`: that is your first video.
- `receipt.md`: the request as you typed it, the renders, the time, and the tokens and cost when your agent reports
  them. `share.txt` holds the receipt's one line.
- `project/`: the page your agent wrote. Edit it and ask for a new render; renders never overwrite.

## How long it takes

Measured for this guide on a 6-core Intel Mac with its GPU, while other jobs kept it busy (load average about 4):

| Step | Command | Time |
|---|---|---|
| Make the job and check setup | `showtime job init hello --request "..."` | 0.8 to 15 s (two runs) |
| Copy and fit the starter page | `showtime new dom <job>/project --duration 5` | 3 s |
| Render 5 s at 1080p (3 browsers) | `showtime render <job>/project --job <job>` | 78 s |
| Check the file | `showtime qa <job>` | 10 s |

Setup comes first, the first time (usually 2 to 6 minutes). Your agent's writing and the critic's review come on
top and were not timed. More numbers: [render § Speed](../../skills/showtime/references/render.md#speed).

## Phrases that change it

- "Show me options first" (or "studio") opens a local board where you pick a concept, a look and a storyboard first.
- "Lean" skips the critic, for a cheaper draft pass; `showtime config mode lean` makes it the default.
- "With a voice-over" adds narration from a voice on your machine; "in Spanish" changes its language.
- "Vertical" makes a 9:16 video for Reels, Shorts or TikTok.

## Limits

- The test video is a starter page with your word in it. A real video needs something to work from: a repo, a site,
  a brief, footage.
- Setup needs the network once. Bigger pieces (the transcription model, Manim, music tracks) download the first time
  a video needs them, with their size shown first. The test video downloads nothing more.
- Something failed? Ask your agent to run `showtime doctor`, then see [Troubleshooting](../troubleshooting.md).

## The example

For what a bigger request makes, see [example 01](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/01-launch-tidepool): a 20-second launch video for
Tidepool, a fictional notes app, made in quick mode from its landing page and app screens, with composed music and
no voice-over (1920x1080, 17.0 MB, after a critic review). Then try it on your own repo with
[launch video from your repo](launch-video-from-repo.md), or pick another task from the [guides](README.md).

Next: [choose your path](../README.md#choose-your-path), the workflow that matches what you want to make.

# Make a launch video from your repo

You have a product in a repository, maybe with a site or a running app. You want a 20-45 s launch or promo video
in the product's own colours, type and words, showing real screens and real commands. This guide shows what to
say and what your agent does.

## Say this

> "Make a 30-second launch video for this repo, for X and LinkedIn."

Run it from the repository, or give its path or URL. If the app runs locally, say where
("it runs on localhost:3000"): the agent can capture the real UI.

## What happens

1. `showtime job init acme-launch --platform x` makes the job folder.
2. `showtime brand capture . --job <job> --aspect 16:9,1:1` reads the repo (CSS variables, Tailwind, fonts, logo,
   README, CHANGELOG), serves and captures its site folder or your running app (`--url`), and writes
   `<job>/brand/brand.json` and `brand.md`: the palette with roles, the fonts, the wordmark, the copy word for word
   with where it came from, and screens per aspect. Nothing in the repo is executed.
3. Evidence: for a command-line tool, your agent runs each command it will show on a small sample and saves the
   output in `<job>/work/evidence/`. Every line on screen traces to a file.
4. A plan in one sentence ("This video tells ___ that ___") and 4-6 scenes, one message each.
5. `showtime new launch <job>/project --duration 30` starts the project in the brand kit's look and fills the
   end card from it. With no brand to capture, your agent records why (`showtime brand skip`) and the project
   starts in a look signature instead: a curated palette, type pair and motion feel, picked away from your recent
   videos (`showtime signature` lists the 12).
6. `showtime audio cuts --for launch --apply <job>/project` picks a produced track and cuts the scenes to its
   phrases, with the swell on the end card.
7. `showtime check <job>/project` and `showtime look <job>/project`, at every aspect it delivers.
8. `showtime render <job>/project --job <job>`, then `showtime qa <job>`, then `showtime review-pack <job>` and a
   critic's review. Fixes, re-render, qa again.
9. Exports on request (`showtime deliver exports <final> --targets x,linkedin`), share copy, and the delivery
   card: files, length, loudness, qa, the review's verdict, what was looked at, and the cost.

## What you get

- `final.mp4` (1920x1080, 30 fps), `poster.jpg`, `share.txt` (post copy), `credits.txt` when the music asks for
  credit, and `exports/` with the platform versions.
- `<job>/brand/`: the brand kit, reusable for the next video.
- The delivery card in the chat. `showtime receipt <job> --card` prints it again.

## How long it takes

Measured for [example 01](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/01-launch-tidepool) (20 s, 16:9) on a 6-core Intel Mac shared with
about three other render jobs:

| Step | Time |
|---|---|
| `site capture`, landing page / app | 14.5 s / 9.8 s |
| `check` with the timeline pass | 52 s |
| One final render | 1 min 58 s to 2 min 53 s |
| `qa` | 11-13 s |
| `review-pack` | 17 s |

[Example 10](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/10-launch-showtime) (30 s with a voice-over) rendered its shipped final in 1 min
40 s on the same kind of machine. The time your agent spends planning and fixing is on top and depends on the
agent; `showtime receipt` reports it per job.

## Phrases that change it

- "A 9:16 cut for Reels too" renders the same page re-laid at 9:16 (`--size 9:16`).
- "Use the cobalt look" picks a look signature; "keep the template's look" sets `--look template`.
- "Same style as this video" with a file: `showtime reference <video> --job <job>` first.
- "With a voice-over" adds a script, a voice and captions.
- "Lean" asks for a cheaper draft pass with fewer looks; a video you will publish still gets one critic round.

## Limits

- Claims come only from your repo, site or what you say. A number the README does not give is left out or
  marked for you to fill.
- A brand colour too weak for text is deepened for text only, and the agent says so.
- A private app is captured where it runs on your machine (`--url http://localhost:<port>`), not from the web.

## The example

[Example 01](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/01-launch-tidepool) (a 20 s launch from a landing page and the real app UI) and
[example 10](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/10-launch-showtime) (showtime's own launch, 16:9 and 1:1). The full workflow is
[launch-video.md](../../skills/showtime/references/workflows/launch-video.md).

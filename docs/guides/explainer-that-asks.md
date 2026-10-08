# Make an explainer that stops and asks

An explainer teaches more when it asks before it tells. showtime can put three or four questions in a video: the
web version stops at each one, shows the choices and waits for an answer, then says why; the MP4 shows a short
"pause and think" countdown in the same place. You can share the web version as one file or as a site with a
link preview.

## Say this

> "Make a 90-second explainer on how a heat pump moves heat, with three questions that stop and ask, as an
> HTML video I can share."

Give the source (a page, a paper, your notes). Say who it is for, so the questions are the right size.

## What happens

1. Your agent plans the explainer: a cold open that poses the puzzle, 3-5 steps, and a question at the step
   the viewer can almost take alone. Each question has three short choices (the right one, the near miss most
   people pick, and one other) and a reply for each that says why.
2. The project: `showtime new film <job>/project` or `showtime new dom <job>/project`. From a storyboard table,
   `showtime new dom <job>/project --from-storyboard storyboard.md` writes one scene per shot and the narration.
3. The voice: `showtime voice script` on the narration, then `showtime retime <job>/project --from-voice
   <job>/project/voice/timeline.json`.
4. The questions go in `showtime.json` under `"questions"`. Each one's `at` is the id of the narrator's line
   that asks it, so a re-voice moves the question with its line. The video draws a pause-and-think beat at each
   one (the `question-beat` component). `showtime check` names any problem (a duplicate id, an answer out of
   range, a line that does not exist, two beats that overlap).
5. `showtime render <job>/project --job <job>` and `showtime qa <job>` for the MP4.
6. `showtime export html <job>/project` for the web version. For a site:
   `showtime export html <job>/project --folder -o site/ --share-url https://you.github.io/heat-pump/`.

## What you get

- `final.mp4` with a pause-and-think beat at each question.
- `<title>.html`: one file that plays offline in any browser, with chapters, keys (`?` lists them) and the
  questions. The scrubber marks each question green or red once answered.
- With `--folder`: `index.html` and `assets/`, plus an empty `.nojekyll` so GitHub Pages serves every file. Serve
  it from a host that answers byte-range requests (GitHub Pages and most web hosts do), so a seek plays at once.
- `socratic.json` beside the export, for a page that drives the player itself.

## Links to a moment or a stretch

- `video.html#t=1:05` opens at 1:05; `#chapter=3` at the third chapter.
- `video.html#t=1:05-1:20` plays that stretch on a loop.
- In the player, Shift + drag on the scrubber picks a stretch, and `c` copies a link to it.

## How long it takes

[Example 25](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/25-nobel-physics-ice-telescope) (2:38, three questions) rendered in about 3 min 15 s on
a 6-core Intel Mac, and its `--folder` export with a link preview took 82 s on a 64-core Linux machine. On the Mac,
[example 13](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/13-wikipedia-waggle-dance) (60 s) exported to one HTML file in about 25 s.

## Phrases that change it

- "Go on by itself after an answer" adds `--auto-continue 6` (seconds).
- "No questions in the web version" adds `--no-questions`.
- "With a link preview" adds `--share-url` (and `--share-image` for your own card image; the poster frame is the
  default).
- "Under 10 MB" sets `--max-mb 10`.

## Limits

- Questions stop only in the HTML export. The MP4 cannot wait; it shows the countdown and then the answer.
- A single file has no image in link previews unless you give a share URL; upload the `.share.jpg` beside it.
- Hosting is your step: showtime writes the files and uploads nothing.

## The example

[Example 25](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/25-nobel-physics-ice-telescope) explains the 2026 Nobel Prize in Physics with three
questions; its [HTML video](https://github.com/FavioVazquez/showtime-examples/blob/main/examples/25-nobel-physics-ice-telescope/interactive/index.html) is a folder export
with a link preview. How to write good questions: [story.md, section 9](../../skills/showtime/references/story.md). The export's
options: [html-export.md](../../skills/showtime/references/html-export.md).

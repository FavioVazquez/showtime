# Turn a long recording into short clips

You have a talk, a panel, a podcast or a stream, from 20 minutes to a few hours. You want 3-10 short clips of
30-60 s, usually vertical with captions. showtime ranks the candidate moments and makes the clips; you (or your
agent) judge which moments stand on their own.

## Say this

> "Find the best 30-60 s moments of panel.mp4 and make three vertical clips with captions."

Say how many clips, and for which platform (Shorts, Reels, TikTok) if you know.

## What happens

1. `showtime job init panel-clips --platform shorts` makes the job. qa checks every clip against that platform.
2. `showtime transcribe panel.mp4 --edit-dir <job>/edit` writes a word-level transcript, with laughter and
   applause tagged when the audio tagger is installed. Add `--speakers auto` (or `--speakers 2`) for speaker
   labels; they are optional here.
3. `showtime edit moments <job> --count 10` ranks the candidates and writes `<job>/edit/moments.json`. Each one
   is whole sentences, with its opening line, why it ranks, a suggested title in the speaker's own words and the
   full text. It looks for a hook in the first 3 s, a complete thought, speaker energy, laughter or applause,
   quotable lines, one topic and no long pauses. Introductions, thanks and logistics rank lower.
4. Your agent reads each candidate's text, not only its score, and marks the picks in `moments.json`
   (`"pick": true`). It can rewrite a title, move a start or an end (edges snap to whole words) or cut a stretch
   inside (`"remove": ["w12-w18"]`). It tells you what it picked and why.
5. `showtime edit clips <job> --preview` renders drafts of the picks in parallel, each through qa, plus a
   contact sheet (`sheet.jpg`, a row of frames per clip). Your agent looks at the sheet for clips that open on a
   wide shot, graphics cut by the crop, or captions jumping off the face, and fixes the edges.
6. `showtime edit clips <job>` renders the finals at 1080x1920 from 1080p footage.
7. `showtime snap <clip> --at <t>` on the start, middle and end of each clip, then share copy per clip.

## What you get

- `<job>/clips/01-<title>.mp4` and so on, one per pick (drafts in `<job>/clips/preview/`).
- `clips.json`: per clip the moment, the source range, the length, qa's verdict, loudness and findings.
- `sheet.jpg`, five frames per clip with qa's colour on the border.
- One EDL per clip in `<job>/edit/clips/`. Edit one and render it alone with `showtime edit render`.

## How long it takes

Measured for [example 24](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/24-highlights-apollo17-panel), a 57:48 panel at 1080p, on a 64-core
Linux machine with no GPU, shared with other jobs (load average 40-170):

| Step | Time |
|---|---|
| Transcribe the hour, no speaker labels | 5:40 |
| Transcribe the hour with `--speakers auto` | 13:07 |
| `edit moments` (2,255 candidates) | 4-8 s |
| `edit clips --preview` (3 drafts) | 40 s |
| `edit clips` (3 finals, qa each) | 49-69 s |

End to end: about 7 minutes without speaker labels, about 14 with them, plus the time spent reading. For this
guide, `edit moments` on the same transcript with `--no-audio` (no energy measure) took 12 s on a busy 6-core
Mac. A long transcription on a laptop was not measured.

## Phrases that change it

- "Square clips" or "landscape clips" sets `--aspect 1:1` or `16:9`.
- "Add a title card" adds `--cards`: the moment's title, and a data callout when the speaker says a number with
  a unit.
- "Clean captions" sets `--captions clean`; "no captions" sets `--captions none`.
- "Keep the ums" sets `--keep-fillers`.
- "Clips of 20-40 s" sets `--min 20 --max 40` on `edit moments`.

## Limits

- The ranking is a shortlist, not a verdict. A moment that needs the sentence before it is a bad clip whatever
  its score.
- On a wide shot the vertical crop follows the biggest face, which may not be the speaker.
- Burned-in name graphics in the source can be cut by the vertical crop.
- Laughter only counts when the transcript's audio tagger hears it.
- Misheard names are fixed in the transcript's text only; word times stay as they are.

## The example

[Example 24](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/24-highlights-apollo17-panel): a 58-minute NASA panel into three vertical clips,
with what the ranking found, what was picked and why. The full rules are in
[editing.md, section 10](../../skills/showtime/references/editing.md).

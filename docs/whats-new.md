# What's new

What each release changes for you, newest first, one sentence a feature. The
[changelog](../CHANGELOG.md) has every change and the reason for it.

## 0.4.1

### Seven looks, no GPU needed

<!-- media: looks: a 4-6 s loop from examples/_looks (god rays, marble, metaballs) -->

Fluted glass, tilt-shift, liquid metal, mesh gradient, god rays, marble and metaballs are drawn in showtime's own
WebGL, each adds less than 50 ms to a 1080p frame at its default size (one browser on a 64-core machine without a
GPU), and each has a designed fallback where WebGL is missing ([components § 7](../skills/showtime/references/components.md#7-looks-webgl-fluted-glass-tilt-shift-liquid-metal-mesh-gradient-god-rays-marble-metaballs),
[the demo](https://github.com/FavioVazquez/showtime-examples/blob/main/examples/_looks/README.md)).

### Shutter blur on fast moves

<!-- media: blur: a 4-6 s loop from examples/_blur (the whip without and with the blur) -->

Mark the element that moves with `data-st-blur` and it smears the way a camera shutter would, only on the frames it
moves fast, and lands sharp ([stage-api § Shutter blur](../skills/showtime/references/stage-api.md#shutter-blur-data-st-blur-and-stblur),
[the demo](https://github.com/FavioVazquez/showtime-examples/blob/main/examples/_blur/README.md)).

### Cards over a talking head, and a word behind the speaker

<!-- media: cards: a 4-6 s loop from examples/23 (the side panel, then "Faster" behind the speaker at 40.4-43.6 s) -->

Name tags, a list that builds as it is said, a data callout, a pull-quote or a side panel appear as the words are
said, and a big word can stand behind the speaker, cut out on your CPU
([editing § 9](../skills/showtime/references/editing.md#9-cards-graphics-anchored-to-the-words),
[example 23](https://github.com/FavioVazquez/showtime-examples/blob/main/examples/23-talking-head-cards-nasa/README.md)).

### A long recording's best moments, as short clips

<!-- media: highlights: a 4-6 s loop from examples/24 (one of the three vertical clips) -->

`showtime edit moments` ranks the best 20-60 s moments of a podcast, talk or panel on your machine, and
`showtime edit clips` turns the ones you pick into vertical clips with captions, each checked by qa: a 58-minute
panel took about 7 minutes end to end on a 64-core machine
([editing § 10](../skills/showtime/references/editing.md#10-highlights-a-long-recordings-best-moments-as-clips),
[example 24](https://github.com/FavioVazquez/showtime-examples/blob/main/examples/24-highlights-apollo17-panel/README.md)).

### Claude Design to MP4

<!-- media: claude-design: a 4-6 s loop of an adopted Claude Design export -->

`showtime adopt <export.zip>` turns a Claude Design animation's HTML export into a 1080p video with sharp text, its
Google Fonts copied in with their licences and exactly one loop of a looping design, ready for music, a voice and
captions ([adopt § From Claude Design](../skills/showtime/references/adopt.md#from-claude-design)).

### Faster renders, and no GPU needed

<!-- media: speed: a still of a render's progress lines -->

The encoder runs while the frames are captured, an unchanged soundtrack is reused, waits stretch on a slow machine
instead of failing, and without a GPU the number of browsers follows your cores: a 1 s fix took 13-21 s instead of
31-54 s on a busy 6-core Intel Mac ([render § Speed](../skills/showtime/references/render.md#speed),
[FAQ](faq.md#do-i-need-a-gpu)).

### Link previews for HTML videos

<!-- media: share: a still of a pasted link showing the poster frame -->

`showtime export html --folder --share-url <address>` (or `"share"` in showtime.json) adds the tags that make a
pasted link show a title, a description and the poster frame, and the folder is ready for GitHub Pages
([html-export § Sharing and hosting](../skills/showtime/references/html-export.md#sharing-and-hosting)).

### Notes on a stretch of time, naming what they point at

<!-- media: notes: a still of the notes page with a stretch band on the scrubber -->

On the notes page (`showtime review open <job>`), Shift + drag on the scrubber marks a stretch, and
`showtime review notes` names the scene and the elements under each spot or box and the scenes a stretch covers,
so your agent fixes the right thing ([review § 6](../skills/showtime/references/review.md#6-notes-on-the-finished-video)).

### Since you last looked

<!-- media: catchup: a still of the "since you last looked" lines of showtime status -->

Edit a job's files by hand, leave notes or pick on a board, and `showtime status <job>` tells your agent what
changed since it last looked, so it keeps your edits instead of writing over them
([FAQ](faq.md#can-i-edit-the-files-myself)).

### The voice-over is heard back

<!-- media: readback: a still of the "heard back" lines of voice script -->

After the voice-over is made, showtime transcribes it on your machine and flags a name, an acronym or a number the
voice said wrong (a name spelled "Open A I" was heard as "OpenI"), with the fix to try
([voice § Pronunciation fixes](../skills/showtime/references/voice.md#pronunciation-fixes)).

### check catches more before the render

<!-- media: check: a still of check's findings -->

`showtime check` judges a fading text at its clearest frame, warns when something sits where the captions go
(`caption_zone`), tries a WebGPU page again without WebGPU, estimates each look's cost (`look_budget`) and flags
blur on text being read ([render](../skills/showtime/references/render.md)).

### Site fixes

<!-- media: site: a still of a search result opening its section -->

On [the site](https://faviovazquez.github.io/showtime/), search finds names such as `pr-video` and every part of a
long page, a placeholder such as `<title>` in a guide shows as text instead of hiding the rest of the page, and
every page has a link preview.

## 0.4.0 (5 October 2026)

- **Videos that stop and ask.** List questions in showtime.json and the HTML export pauses on that frame, asks,
  marks the answer and plays on; the MP4 gets a "pause and think" beat.
- **Notes on the finished video.** `showtime review open <job>` plays the latest render on a local page where you
  click a spot or drag a box and type a note; your agent reads the notes, fixes and replies.
- **Range links.** `video.html#t=10-20` plays that part of an HTML video on a loop.
- **A pull request becomes a video.** `showtime pr-video <N | URL>` makes a short video for the PR's description,
  with a copy under GitHub's 10 MB attachment limit.
- **A storyboard table becomes a project.** `showtime new <template> <dir> --from-storyboard <file>` reads a
  Markdown table of shots.
- **Go all out.** A "showreel" brief turns on a dense tone, and the `showreel` template renders at 16:9, 9:16, 1:1
  and 4:5 with no edits.
- **The critic watches as a first-time viewer**, and its Blockers and Should-fixes must be fixed or waived before a
  job is marked delivered.
- **A hearing pass** reports music over the voice, cut-off lines, long silences and jumps in level.
- **Twelve look signatures.** New projects start in a curated palette, type pair and motion feel, picked away from
  your recent videos.
- **A behaviour scoreboard anyone can rerun**: an agent scored 35/42 with showtime and 25/42 without.

The README has the longer [0.4.0 summary](https://github.com/FavioVazquez/showtime#new-in-040).

## Earlier releases

The README summarises [0.3.0](https://github.com/FavioVazquez/showtime#new-in-030) (quieter runs, full review by
default, style references, the phone check) and [0.2.0](https://github.com/FavioVazquez/showtime#new-in-020)
(every coding agent, a lighter first run, a real music catalog). Everything else is in the
[changelog](../CHANGELOG.md).

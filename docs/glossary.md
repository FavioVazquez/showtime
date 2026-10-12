# Glossary

The words you meet in showtime's output, its delivery card and its docs, in alphabetical order. Each entry says
what the word means here and where it lives on disk or which command makes it.

This page is for people using showtime. [CONTEXT.md](../CONTEXT.md) is the house vocabulary for whoever writes
showtime itself: one word per idea, the near-synonyms to avoid, and the ambiguities it settles.
The release check warns when the skill uses an avoided word. The two agree. This page adds the words a new
user meets first (EDL, ledger, critic, look signature) and leaves the finer distinctions to CONTEXT.md: scene, shot,
clip, beat and slot; mix, master, score and bed; board, storyboard and animatic.

## The job folder

Every request gets one folder, and nothing in it is overwritten: a second render is `final-2.mp4`. Each stage of a
job writes its own files. The [5-second test video](guides/first-video.md) makes the ones without a note; the others
appear when a job needs them.

```text
showtime-out/hello-20261009-205903/
│
│  0 Start ─────── SHOWTIME.md         the ledger: goal, stage, verified vs assumed, open questions, next command
│                  job.json            the same for machines: versions, stage times, the latest file of each kind
│                  AGENTS.md           tells an agent that opens the folder later to read SHOWTIME.md first
│                  CLAUDE.md           (the same text)
│
│  2 Plan ──────── project/voice/timeline.json        with a voice-over: line and word times
│
│  3 First look ── project/index.html, showtime.json  the page and its settings
│                  edit/edl.json                      instead of project/, for a footage edit
│
│  4 Build ─────── final.mp4           the video; a new render is final-2.mp4
│                  poster.jpg          the still shown before it plays
│                  final.work/         render.json: browsers, GPU, time per stage
│
│  5 Verify ────── work/qa/final/      qa.json and sheet.jpg, the last qa verdict
│                  review/round-1/     CRITIC.md and FINDINGS.md, the critic's round
│
│  6 Deliver ───── receipt.md          what the job took: rounds, renders, time, tokens
│                  share.txt           the receipt's one line; post copy above it when there is somewhere to post
│                  exports/            platform copies, when you ask for them
```

Stage 1 (understand the request) reads your files and writes nothing new. The receipt and `share.txt` are written
when your agent records the delivery (`showtime job note --stage deliver`).

## critic

A fresh sub-agent that reviews a finished video. It gets one file, `CRITIC.md`, from `showtime review-pack` (contact
sheets, key frames, a loudness graph and the brief) and writes `FINDINGS.md` with a verdict. It never sees the
conversation, so it judges the video, not the intentions. In quality mode every finished video gets a critic round
before delivery. See [finding](#finding) and [review](../skills/showtime/references/review.md).

## crew

Ten optional specialist sub-agents that ship with showtime: brand designer, creative director, critic, editor,
motion designer, researcher, scriptwriter, sound designer, storyboard artist and voice director. They get file
pointers, never the chat, and hand back files. Your agent stays the director: the only one who talks to you, keeps
the [ledger](#ledger) and renders. Say "no crew" to keep the whole job in one session, or "full crew" to use every
member the job can. See [crew](../skills/showtime/references/crew.md).

## delivery card

The fixed summary at the end of every job: Done, Files, Length, Loudness, QA, Review, Findings, Look (what was
actually opened and seen), Cost, Assumed, what is cheap or costly to change, and three options for what to do next.
`showtime receipt <job> --card` fills in what showtime knows. See [modes § 5](../skills/showtime/references/modes.md).

## draft

A fast render for review: `showtime render <project> --preview` (at most 720p, fast encode). Timing and content are
real; picture quality is not. Not to be confused with a [preview](#preview).

## EDL

An edit decision list: a JSON file that lists which stretches of your recordings to keep, in order, with captions,
cards and the output size. A footage edit keeps it at `<job>/edit/edl.json`. `showtime edit cut` writes it from a
transcript, `showtime edit check` checks it, and `showtime edit render` renders from it, so your original footage
is never changed. See [editing](../skills/showtime/references/editing.md).

## export

A platform version made from the [final](#final): `showtime deliver exports <job> --targets youtube,reels,square`
writes them into `<job>/exports/`, each to its platform's size, length and file limits.

## final

The full-quality render that qa checks: `final.mp4`. Renders never overwrite, so a re-render is `final-2.mp4` and a
poster bake `final.poster.mp4`. Commands given a job use its latest final, and `showtime qa` prints which file that
is.

## finding

One problem the critic reports, with a timestamp and an id: a Blocker (`r1-B1`), a Should-fix (`r1-S1`) or a Polish
item (`r1-P1`). A video is not marked delivered while a Blocker or Should-fix is neither fixed nor
[waived](#waive). Polish items never hold up delivery. `showtime review-respond <job>` lists them with their state.

## first look

The first thing you see, within minutes: a still, a contact sheet or a fast [draft](#draft). It is there to catch a
wrong direction early, before the full render. In quick mode your agent shows it and keeps going.

## HTML video

A single file that plays in any browser, offline: the same frames as the MP4, a player with chapters, keyboard
shortcuts, links to a moment, and questions that pause the video until the viewer answers. `showtime export html`
makes one from any project. See [html-export](../skills/showtime/references/html-export.md).

## job

One request carried out end to end, in its own folder: `showtime-out/<name>-<date>-<time>/`. `showtime job init`
makes it. `<job>` in commands is that folder or just its name (`launch` means the newest `launch-*` job). A job
holds the [ledger](#ledger), the [project](#project) or the [EDL](#edl), the renders, the qa reports and the
[receipt](#receipt).

## lean

See [quality and lean](#quality-and-lean).

## ledger

The job's own record of where it stands: `SHOWTIME.md` for people and `job.json` for programs. It holds the goal,
the stage, what was verified and what was only assumed, the open questions and the next command. `showtime job note`
writes it at every stage; `showtime status`, qa and a resumed session read it. An agent that opens the folder later
starts there.

## look

`showtime look <project|video|job>` makes one small composite image (1280 px) of a video's key frames, and a brief
for a reviewer who answers in text. It lets your agent check the picture without filling its context with images.
The delivery card's Look line says what was opened and what was seen. See
[looking](../skills/showtime/references/looking.md).

## look signature

A named set of palette, type pair, motion feel and ground (glow, grid, vignette) that a new page project starts in,
when there is no brand kit or style reference. There are twelve: seven dark and five light. showtime picks one that
differs from the last six projects on this machine and the last five finished videos, so videos do not all look
alike. `showtime new ... --look <id>` chooses one, `showtime signature list` lists them, and
`showtime signature apply <project> next` swaps it. A brand kit always wins. See
[color § 9](../skills/showtime/references/color.md#9-look-signatures).

## poster

The still a player shows before the video plays, and the frame a feed shows. `"poster": <seconds>` in
`showtime.json` picks it, and `showtime render` writes `poster.jpg`. A poster at 0 s means the video opens on a
complete frame. `showtime deliver poster <job> --at <seconds> --bake` puts a later frame at the start.

## preview

Watching a project live in the browser player: `showtime preview <project>`, with a scrubber and frame stepping. No
file is written. A quick file is a [draft](#draft).

## project

A folder with `index.html` and `showtime.json` (plus its assets) that `showtime render` turns into a video. It is
the source your agent writes, never an output. `showtime new <template> <dir>` makes one from a
[template](#template).

## quality and lean

The review setting: how much your agent checks a video after making it. **Quality** (the default) gives every
finished video the full review: looks, qa and a [critic](#critic) round before delivery. **Lean** is a cheaper draft
pass: no critic unless the video is going to be published. Say "lean", or run `showtime config mode lean` to make it
the default. It is a separate setting from [quick and studio](#quick-and-studio).

## quick and studio

The asking setting: how much your agent asks before building. **Quick** (the default) states its assumptions in one
line and starts; it asks only when a request could mean two different videos. **Studio** shows you options on a
local board first (concepts, looks, music, a storyboard and an animatic) and waits for your picks. Say "show me
options first" or "studio". It is a separate setting from [quality and lean](#quality-and-lean). See
[modes](../skills/showtime/references/modes.md).

## readback

After a voice-over is made, showtime transcribes each line on your machine and compares it with the script. When a
name, an acronym or a number is heard differently, it warns. qa runs the same check. A word someone listened to
and found right is cleared in `showtime.json`: `"readback": {"ok": ["JSON"]}`. See
[troubleshooting](troubleshooting.md#a-name-is-said-wrong-a-readback-warn).

## receipt

`receipt.md` and `receipt.json` in the job folder: the request as typed, the assumptions, the review rounds, every
render, the wall time, and the tokens and cost when your agent's session log can be read (anything unknown says
"not reported by this agent"). `showtime receipt <job>` writes it. See
[receipt](../skills/showtime/references/receipt.md).

## signature

Short for [look signature](#look-signature), as in `showtime signature`.

## splice

Re-rendering only part of a finished video: `showtime render <project> --job <job> --from 12 --to 18` renders those
seconds and puts them into the job's last full render, saved as the next `final-N.mp4`. An unchanged soundtrack is
reused. It is how a small fix stays fast.

## studio

See [quick and studio](#quick-and-studio).

## template

A starter project that `showtime new` copies, such as `dom` (a launch page), `short` (a vertical video), `data` (a
chart story) or `film` (a canvas film with its own score). `showtime new` with no arguments lists them all with their
size and length.

## timeline.json

The voice-over's timing, written by `showtime voice script` next to `vo.wav`: each line's start and its share of the
time, and every word's start and end. Scenes take their lengths from it (`showtime retime <project> --from-voice
<project>/voice/timeline.json`), and captions and reveals land on its word times.

## waive

Closing a [finding](#finding) on purpose, with a one-line reason, instead of fixing it:
`showtime review-respond <job> --waive r1-S2 "the pause is on purpose"`. Your agent asks you before it waives a
Blocker. Every waiver and its reason is listed in the receipt.

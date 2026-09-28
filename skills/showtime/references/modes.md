# Modes: quick and studio

Read this when you start a job and need to decide how much to ask, when the user wants to steer more
(or less) than the current mode allows, or when you write the closing delivery card. The studio
protocol itself (phases, boards, questions) is in `studio.md`; the board format in `boards.md`.

## 1. Quick mode (the default)

One request in, one video out. The user sees three things: an opening line, a first look, and the
final with a delivery card.

**The opening line** states the mode, the format and the assumptions in one sentence, so a wrong
assumption costs the user one reply:

> Quick mode: a 20 s 16:9 launch video for acme-cli, upbeat tone, generated music, no voice-over.
> First look in about 3 minutes.

**Questions.** Most requests need none: when the request names the kind of video and there is
something to work from (a repo, a URL, footage, a brief), state the assumptions and start. Ask only
when the request is genuinely ambiguous (nothing to work from, or two readings that make different
videos), at most two questions, and only when the answer changes the video. Each carries its
recommended answer, written as the answer itself, so "yes" is always a valid reply:

> Two quick ones: (1) Length: 20 s for social (recommended) or 60 s for the site? (2) Where does it
> start from: this repo (recommended) or the public site?

Questions worth asking: platform and aspect when nothing hints at it; a hard length; what must be
shown. Voice-over is a stated assumption ("no voice-over"), not a question, unless the request
hints at narration. Never ask what the source already answers (product name, colours, features,
audience hints): look it up and say what you found. Everything else becomes a stated assumption,
logged with `showtime job init ... --assumed "..."` or `showtime job note --assumed`.

**When to wait.** Quick mode does not stop for approval. The opening line, the first look and any
drafted brand kit are shown and work continues in the same turn; the user can interrupt. Wait for
a reply only when:
- a step is destructive: it drops content the user recorded (picks takes, removes sentences,
  reorders), or overwrites or deletes their files;
- a step is expensive: a large install (`showtime setup`), a download, a render or transcription
  expected to take more than about 10 minutes;
- the request is genuinely ambiguous (above).

**Budget.** First look within minutes (a contact sheet from `showtime snap`, or a draft render).
Tell the user the time for anything that takes more than about 30 s.

**Recording the mode.** `showtime job init <slug> --mode quick` (the default). SHOWTIME.md carries
the goal, what is verified, what is assumed, and the open questions.

## 2. Studio mode (opt-in)

Studio trades speed for control: the user picks a concept, a look, a sound and a storyboard on a
local board before anything is built. Start it when the user asks ("studio", "brainstorm this with
me", "show me options first", "storyboard it first", "I want control").

Offer it yourself only when all three hold: high stakes (a launch, a trailer, a brand film), an open
direction (no concept or tone given), and the user is present. Offer once, in one line, defaulting to
quick:

> I can go straight to a draft (about 5 min) or open a studio board where you pick a concept, look
> and storyboard first (15-25 min). Straight to the draft?

The offer rides on the opening line and counts as one of the two questions. It does not block:
carry on in quick mode, and switch (section 3) if the user takes it.

Never offer it for small edits, captions, cut-downs, re-exports, or when the user already described
the video in detail.

Starting: `showtime job init <slug> --mode studio --goal "..."`, then `showtime studio init <job>`
(the folder `job init` printed, or its name: studio attaches to that job; with no job yet it creates
one) and follow `studio.md` from its first phase.

## 3. Switching

| From → to | Trigger | Do |
|---|---|---|
| quick → studio | "show me alternatives for the music", "can I pick the look?", a yes to the studio offer | `showtime studio init <job>` (switches the same job to studio mode), write the current plan into `studio/brief.md` with every choice marked assumed; open only the phase asked for |
| studio → quick | "just make it", "you decide the rest", "skip ahead" | Lock what is picked, fill every open decision with its recommendation (logged as assumed), say so in two lines, build (`showtime job note --mode quick`) |
| studio, back a phase | "back to concepts" | Mark later picks stale in brief.md (never delete them), re-confirm them after the new pick |

A switch never loses work: drafts, voice lines and transcripts are cached and reused.

## 4. Sub-agents (the crew)

Quick mode stays inline. Two exceptions: parallel scene building for longer videos (6+ scenes: one
`showtime:motion-designer` per scene or group of scenes, capped by CPU), and, when publish-bound, the
`showtime:researcher` before the final and the `showtime:critic` on it. Studio can use the whole crew
(creative director, brand designer, scriptwriter, storyboard artist, motion, sound, voice, editor,
researcher, critic). Who to dispatch when, the `TASK.md` each gets, merging scene fragments and the
CPU budget: `crew.md`.

Give each one pointers, not the conversation: its brief (`crew/<role>.md`) and a `TASK.md` naming the
inputs, the folder it owns, what to deliver and the command that proves it done. Crew members never
start studio, never open boards or servers, never ask the user questions, and never render the
final. You merge, check and render.

The critic is different: it receives only `CRITIC.md` from `showtime review-pack` and is read-only
(`review.md`).

## 5. The delivery card

The last message of every job, quick or studio. Short, scannable, paths first:

```
Done: 20 s launch video for acme-cli (16:9, 1920x1080, 30 fps)
  final     showtime-out/acme-launch-20260926-101500/final.mp4   (qa PASS: -14.0 LUFS, -1.4 dBTP)
  poster    .../poster.jpg (baked into frame 0 by render)
  share     .../share.txt   credits .../credits.txt (2 CC-BY music credits: paste into the post)
  exports   .../exports/final.reels.mp4, final.youtube.mp4

Assumed: no voice-over; the "4x faster" line comes from the README benchmark table.
Cheap to change (minutes): any text, colours, music style, a scene's length, sound effects, exports.
Costly (a new pass): the story order, adding a voice-over, a different aspect layout, new footage.

Next, pick one:
  1. A 9:16 cut for Reels with captions (about 4 min)
  2. Add a narrated version (voice af_heart, about 6 min)
  3. A 6 s bumper from the hook and the end card
```

Rules for the card:
- `final` is the file qa checked (the job's latest final: `final-2.mp4` after a re-render, the baked
  `final.poster.mp4` after `deliver poster --bake`), never an older one.
- Quote the qa verdict with its loudness and true peak; never "should be fine".
- List every assumption that reached the video, especially anything the user did not confirm.
- Cheap vs costly is about this job's actual structure (a voice-led video makes timing changes costly).
- Exactly three next options, each concrete and with a time estimate.
- Record it: `showtime job note --stage deliver --verified "qa PASS ..." --next "<option 1 command>"`.

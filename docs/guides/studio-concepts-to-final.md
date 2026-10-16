# Studio: from concepts to the final film

<!-- tutorial: numbered steps, each with a screenshot from one real run -->

Studio mode opens a local board where you choose a concept, compare it with the others, leave notes, approve a
storyboard, and only then does the film get built. This guide walks through one real run, step by step, with a
screenshot of each step. The video is a 20-second trailer for Tidepool, a fictional notes app that ships with showtime
as sample material.

![The whole run in 22 seconds: the board with four concepts, a wipe between two of them, a pick and a comment, the storyboard, the approval and the finished trailer.](../../assets/readme/tutorials/studio/clip.webp)

## Say this

> "Show me options first for a 20-second trailer that tells note-takers everything they write stays on their own
> machine."

"Options first" (or "studio") is the trigger. Without it, your agent goes straight to a draft.

## 1. Your agent starts the session and builds the board

It makes a job, attaches a studio session to it, writes the concepts into `studio/board.json`, and renders one to
three style frames for each concept. Then it checks the board and opens it.

![A terminal: showtime studio init, two showtime studio frame runs that render three frames each in under 3 seconds, showtime studio board printing "board OK: rev 1, 4 concepts", and showtime studio open printing a local link.](../../assets/readme/tutorials/studio/01-terminal-board.webp)

The terminal output is trimmed to the lines that matter; `showtime studio frame` runs once per concept. The link is
local (`127.0.0.1`) and carries a key. It opens nowhere else.

## 2. Open the board

Round 1 is the question "which direction feels like a Tidepool trailer?". There are three concepts and one wildcard.
Each card has its frames, a one-line pitch, the hook of the first three seconds, a palette, type, music and the risk.
One concept is marked **Recommended**, with the reason.

![The studio board at round 1: the heading "Which direction feels like a Tidepool trailer?", and cards for C1 Low tide, C2 Macro (recommended) and C3 Keystrokes, each with a style frame.](../../assets/readme/tutorials/studio/02-board.webp)

## 3. Compare two concepts

The **Compare** tab puts any two concepts on one frame. Drag across it to wipe from one to the other.

![The Compare tab: a frame split down the middle, C1 Low tide on the left with its wave line and C2 Macro on the right with the words "Sync: local only".](../../assets/readme/tutorials/studio/03-compare.webp)

## 4. Pick, like and comment

**Pick** chooses a concept. The heart likes one, and you can like a concept you did not pick, to say "keep this part".
The speech-bubble button opens a comment. Here the reviewer picks C2, likes C1 and writes that the film should land on
C1's sunrise.

![A comment box on C2 Macro with the text: Frame 1 reads instantly. Land the name on the sunrise from C1.](../../assets/readme/tutorials/studio/04-comment.webp)

Every click is saved on your computer in `studio/feedback.json`. Press **Feedback** to read what you left:

![The Feedback panel listing the pick, the like and the comment, with a box to add a note and a Copy for your agent button.](../../assets/readme/tutorials/studio/05-feedback.webp)

## 5. Your agent reads it and answers

You tell your agent you are done. It runs `showtime studio feedback`, repeats what you said in a few lines, logs the
decision in `decisions.md` (append-only) and brings out the next round. What you typed on the board is quoted as
your opinion about the video; it is never run as an instruction.

![A terminal: showtime studio feedback printing the pick C2 Macro, the like on C1 and the comment, then showtime studio decide appending D-002.](../../assets/readme/tutorials/studio/06-terminal-digest.webp)

## 6. Check the storyboard

Round 2 is the storyboard of the concept you picked: every shot with its time range, what is on screen, and a note on
how it moves. The thumbnails are rendered from the draft project at those moments. Open the **Storyboard** tab, and
use **Note** under a shot to say what to change.

![The Storyboard tab: shot cards C2.1 to C2.5, with a sixth cut off at the right edge, each with a thumbnail, a time range such as 0:00.0 to 0:02.5, what is on screen and a Note button.](../../assets/readme/tutorials/studio/07-storyboard.webp)

![A comment box on shot C2.1: Hold the first shot a beat longer.](../../assets/readme/tutorials/studio/08-shot-note.webp)

The **Animatic** below the storyboard is a rough cut with the music, to judge pace before anything is rendered;
`n` adds a note at the moment you are watching.

## 7. Approve

The **Decide** tab has the questions your agent still needs answered, two dials (energy and pace) and an **Approve**
button for the concept you want built, with a box for final notes.

![The Decide tab: Energy and Pace sliders, "C2 · Macro, ending on the sunrise" chosen in the Ready box, the note "Lock it. Cuts on the beat." and an Approve button.](../../assets/readme/tutorials/studio/09-approve.webp)

Your agent reads the approval, logs it and builds the film. This is the last point to change your mind cheaply.

![A terminal for steps 6 and 7: the storyboard thumbnails rendered, the board checked at rev 2, and showtime studio feedback printing APPROVED: C2 Macro, ending on the sunrise with the final note.](../../assets/readme/tutorials/studio/10-terminal-storyboard.webp)

## 8. See the final

`showtime render` draws every frame on your computer, and `showtime qa` checks the file. For this film the render took
45 seconds for 20 seconds of 1080p.

![Four frames of the finished trailer: the words "Sync: local only" in macro focus, a task being ticked, a note on local-first software, and the end card: Tidepool, Your notes, kept on your own machine.](../../assets/readme/tutorials/studio/11-final.webp)

In quality mode (the default), a critic reviews the finished film and you can leave notes on it too:
[Leave notes on a video and get them fixed](notes-and-fixes.md). The finished trailer from an earlier run of this
same session is [example 09](https://github.com/FavioVazquez/showtime-examples/blob/main/examples/09-studio-trailer/README.md).

## How long it takes

Measured for this guide on a 6-core Intel Mac (i5-8500), while nothing else was rendering:

| Step | What ran | Time |
|---|---|---|
| Style frames, one concept | `showtime studio frame ... --html` (3 frames) | 2.8 to 3.2 s (39 s the first time, while the browser started) |
| Storyboard thumbnails | `showtime studio frame ... --project --at` (8 frames) | 9.6 s |
| The final render | `showtime render <project> --job <job>` (20 s, 1080p) | 45 s |

Your agent's writing of the concepts and your own time on the board come on top and were not timed.

## Phrases that change it

- "Show me options first", "studio", "I want control": opens the board.
- "Only stop me for concepts": your agent fills the other stops with its recommended answer and logs them as assumed.
- "Resume the studio": it reads `brief.md` and `decisions.md` and carries on; it never asks a settled question again.
- "Export the board": `showtime studio export <job> --inline` makes one HTML file you can send.

## Limits

- The board is local. Anyone you send the link to cannot open it; export it if someone else must look.
- The style frames show a direction, not the film. A concept can look right in frames and still be hard to animate.
- Music beds and voice samples also go on the board; this run skipped them to stay short.
- To keep the run short, the project that was rendered in step 8 is the finished project of example 09, copied to a plain
  folder; the storyboard thumbnails and the final film come from it. The clicks on the board were made with a headless
  browser, the way a reviewer would make them.
- The commands behind each step: [Studio mode](../../skills/showtime/references/studio.md); the board file:
  [Board format](../../skills/showtime/references/boards.md).

# Questions people ask

Short answers, each with a link to the long one. Something missing? Open an
[issue](https://github.com/FavioVazquez/showtime/issues).

## Do I need a GPU?

No. Every frame is drawn by a browser, and without a GPU the browser draws on the CPU, WebGL included. On a
64-core Linux machine with no GPU, a 30-second 1080p launch film rendered in 17.6 s with 0.4.1's automatic settings
(8 browsers), against 42.0 s with 0.4.0's (3 browsers), and in 13.1 s with 16 browsers (measured on 7 October 2026). On fewer cores, WebGL scenes are the slow part: on a 6-core Intel Mac
with its GPU turned off, a shader-heavy 1080p frame took about 0.5 s. Without a GPU, showtime picks the number of
browsers from your cores, and each of the seven WebGL looks adds less than 50 ms to a 1080p frame at its default
size (measured on the same 64-core machine, one browser). More numbers:
[render § Speed](../skills/showtime/references/render.md#speed).

## What does it cost?

showtime is free and open source ([MIT](../LICENSE)). It has no account, no subscription and no API key. The cost
is your coding agent's tokens. Every job ends with a receipt: run `showtime receipt <job>` and open `receipt.md`.
It shows the request as you typed it, the review rounds, every render, the wall time, and the tokens and cost when
your agent's session log can be read (Claude Code, Codex and Devin; other agents say "not reported by this
agent"). Costs are at API list prices, so on a plan they are a measure, not a bill
([receipt format](../skills/showtime/references/receipt.md)).

## Which coding agents work?

Claude Code, Codex, Cursor, Devin and OpenCode were tested: each installed showtime and made a real video with it.
Copilot, Gemini CLI, Antigravity, Cline, Kilo Code, Kiro, Zed, Goose, Amp, Factory Droid and Qwen Code should work
but have not made a video yet. The exact install for each is in [agents.md](agents.md). The
[behaviour scoreboard](https://github.com/FavioVazquez/showtime#behaviour-scoreboard) shows how often the skill does the right thing, and
anyone can rerun it.

## Does anything leave my machine?

No. showtime has no server and no telemetry, and it uploads nothing you make. It goes online to download its tools
and models (once), and when you ask it to fetch something: a media search, a website capture, a pull request for
`showtime pr-video`, and the Google Fonts (and their licence texts) of a page you adopt with `showtime adopt`. Your prompts go to your coding agent, under that agent's own policy. The details are in
[PRIVACY.md](../PRIVACY.md).

## Who owns the videos I make?

You do. When a video uses music, a sound or a picture that needs a credit, showtime writes `credits.txt` next to
it, and the credit line goes into the post copy. A few optional models are for non-commercial use only and are off
by default: the CrisperWhisper transcription model, which asks for your acceptance first, and the MusicGen music
model, whose drafts are labelled. The speaker cutout model (MODNet) is Apache-2.0. Every model's licence is listed in the
[README](https://github.com/FavioVazquez/showtime#license-and-credits).

## How much disk does it need?

Setup downloads about 0.53 to 0.59 GB on macOS and Windows and 0.73 GB on Linux x64, and once unpacked the
install takes about 1.4 GB on macOS and Windows and 1.7 to 1.8 GB on Linux, with a browser already installed (the
headless browser setup fetches otherwise adds 0.2 to 0.3 GB). Bigger pieces come the first time a video needs them,
each with its size shown first: the transcription model (about 490 MB), Manim (60 MB), music tracks and sound packs (a few
MB each). Running the test suite keeps about 0.7 GB of caches. `showtime setup --estimate` prints your sizes,
`showtime setup --plan` lists every download, and `showtime setup --full` fetches everything now (about 5.1 to 5.7
GB to download) for a machine that will be offline.

## How long does a video take?

The render is usually the short part. On a 6-core Intel Mac with a GPU, a 15-second 1080p page rendered in 28 s, and in 0.4.1
a 1-second fix spliced into a finished video took 13 to 21 s while other jobs were running. Writing, checking and
the critic's review take longer, and depend on your agent and the video. The receipt records the wall time of
every job. Your agent says the time before anything that takes over 30 s.

## Does it run on Windows, Linux and macOS?

Yes. It is tested on Intel Macs, Apple Silicon, Linux x64, Linux arm64, Windows x64 and Windows 11 on Arm. Still to
run: Windows 10/11 desktop. If you have one, `scripts/e2e-windows.ps1` runs everything and zips the result for an
issue. What ran where is in the [README](https://github.com/FavioVazquez/showtime#requirements).

## Which languages?

Voices speak English, Spanish and 30 other languages, all on your machine: the default voices cover eight of them, and
the Supertonic voices, an extra (`showtime setup --with supertonic`), add the rest. Transcripts cover 25 languages
with the default model, and more with Whisper. Ask for "the same video in French" and your agent re-voices it,
re-times the scenes and translates the on-screen text
([localize](../skills/showtime/references/workflows/localize.md)).

## Can I edit the files myself?

Yes. Every job is a folder of plain files: the page, the script, the edit list, the mix. Change anything, then tell
your agent to carry on. `showtime status <job>` lists what changed since the agent last looked (your edits, your
notes on the video, open findings), and the agent keeps your edits. Each job folder also has an `AGENTS.md` and a
`CLAUDE.md`, so an agent that opens the folder later knows where things stand.

## I disagree with the critic. What now?

Say so. A finding is fixed or waived before the video is marked delivered, and a waiver is one line with a reason:
`showtime review-respond <job> --waive r1-S2 "the pause is on purpose"`. Your agent asks you before it waives a
blocker. Every waiver and its reason is listed in the receipt
([review](../skills/showtime/references/review.md)).

## Can viewers answer questions in the video?

Yes, in the HTML export. List questions in `showtime.json` and the player stops on that frame, asks, marks the
answer and plays on. The MP4 gets a short "pause and think" beat instead
([html-export § Questions](../skills/showtime/references/html-export.md#questions)).

## Can I leave notes on the finished video?

Yes. `showtime review open <job>` plays the latest render on a local page. Click a spot, drag a box, or Shift +
drag on the scrubber to mark a stretch of time, and type a note. Your agent reads the notes with
`showtime review notes`, which names what each one points at (the scene, and the elements under a spot or box),
fixes them and replies on the page
([review § 6](../skills/showtime/references/review.md)).

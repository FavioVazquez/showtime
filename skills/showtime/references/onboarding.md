# Onboarding: the first-run conversation

Read this when `showtime doctor --quick` reports failures, when a command says setup has not been run,
or when the user is new to showtime ("how do I set this up?", "what do I need?"). The goal is one
short exchange: what is there, what is missing, one decision, then the install, then back to the video.

## Essentials

- Look first: `showtime doctor --json --quick` (read `checks[]`) and `showtime setup --estimate`; one table by
  area, then one question: install the default now (recommended), with the printed numbers (§1, §2)
- Setup is the user's call, not yours: a quick test is no reason to skip it. Say the size and time and run it; if the
  user declines, say what cannot be made without it and stop. Never make the video another way instead (bare ffmpeg,
  your own script): that is not showtime, and nothing checks it.
- Install with `showtime setup` (idempotent, resumes), or `--background` and
  `showtime status <id> --wait 240`; done when `showtime doctor` shows 0 fail (§3)
- Missing uv or Node.js 20+: show the printed command and let the user run it (or run it after a yes); in a
  sandbox the user runs `showtime setup` in their own terminal, or use
  `SHOWTIME_HOME=.showtime showtime setup` (§3)
- Exit code 3: relay the `showtime setup --with <name>` line and size, ask, install, continue;
  `SHOWTIME_AUTO_INSTALL=1` only if the user says so (§4)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. Look before you talk | 32-43 |
| 2. Tell the user in one table, then ask one thing | 45-62 |
| 3. Install | 64-90 |
| 4. What works now, what arrives later | 92-113 |
| 5. Where things live | 115-119 |
| 6. If setup fails | 121-126 |

## 1. Look before you talk

```
showtime doctor --json --quick
```

Read `checks[]`: each row has `check`, `status` (`pass`, `warn`, `fail`, `skip`), `detail` and `hint`
(the one-line fix). `--quick` skips the test encode and the browser launch (about 1 s); run the full
`showtime doctor` after installing.

Also run `showtime setup --estimate` (installs nothing) for the size and time of the default install,
and `showtime setup --list` when the user asks about extras.

## 2. Tell the user in one table, then ask one thing

Group the rows into what they mean for videos, not into package names:

| Area | Status | Means |
|---|---|---|
| ffmpeg, browser, Node | ok | rendering works |
| Python venv, models | missing | voice, transcription and captions need setup |
| audio library | not fetched | generated music and effects still work; library tracks need a fetch |

Then one decision, with the default recommended:

> showtime needs a one-time install into `~/.showtime`: about 0.6-0.9 GB of downloads, usually 2-6
> minutes. Nothing outside that folder changes. Install the default now? (recommended)

Use the numbers `setup --estimate` printed, not the ones in this file. Do not ask about tiers or extras
up front: the default tier covers every workflow in SKILL.md, and extras are fetched when a feature
needs one.

## 3. Install

```
showtime setup                 # the core tier; prints progress, resumes after interruptions
showtime doctor                # full check, including a real browser launch and test encode
```

- setup is idempotent: running it again skips what is present and resumes partial downloads.
- It needs **uv** and **Node.js 20+**. If either is missing, setup stops and prints the exact
  install command for this OS. Installing system software is the user's call: show them the command
  and let them run it (or run it only after they say yes), then run setup again.
- A long setup should run in the background with progress checks, not block your turn:
  `showtime setup --background`, then `showtime status <id> --wait 240` until it ends.
- Inside an agent's sandbox (doctor fails `home writable` or `network` and names the host setting to
  change): ask the user to run `showtime setup` once in their own terminal, or to change that setting;
  or install into the project with `SHOWTIME_HOME=.showtime showtime setup` (showtime then finds
  `./.showtime` by itself in that project).
- The first doctor (or render) after a restart can take a few minutes while the OS checks native
  libraries, macOS especially; doctor says so and shows what it is checking. Tell the user it is
  not stuck; later runs take seconds.
- Behind a proxy or offline: `showtime setup --seed DIR` reuses files downloaded elsewhere
  (matched by size and sha256).
- A proxy that blocks Hugging Face or GitHub LFS (the Claude app's sandbox answers 403): setup and first-use
  fetches take those model files from showtime's model mirror on GitHub by themselves, sha256-verified;
  `SHOWTIME_MODEL_MIRROR=<URL or folder>` points at another copy.

Done when `showtime doctor` shows 0 fail. Warnings each come with a `fix:` line; most are optional.

## 4. What works now, what arrives later

Say this in two or three lines so nothing surprises the user later:

| Works right after the core install | Fetched automatically on first use (a one-line notice with the size) |
|---|---|
| HTML and canvas videos, all templates, preview, render, check, snap | the audio library's starter part (~41 MB) on first library use; category parts, produced-music tracks and extra SFX packs when a mix or search needs them; all of it: `showtime audio lib fetch` (~249 MB) |
| generated music, all 56 effect types, mixing, mastering | the transcription model, Parakeet v3 (~465 MB), before the first transcription; the Whisper engine + a Whisper model only for languages outside Parakeet's 25; the vocal separator (67 MB) for speech under loud music |
| Kokoro voices (English, Spanish, more) with word timings | Manim (~60 MB) before the first Manim scene; icons one at a time (a few KB each) |
| footage edits, captions (transcripts after the first-use fetch) | Piper voices, the English aligner, background removal outside macOS (rembg; its model is about 170 MB) |
| site capture, demo recording, auto zoom, fonts, exports | a headed browser (`--headed` without Chrome/Edge: full Chromium, ~200 MB) |

Still explicit (`showtime setup --with <name>`): Whisper turbo (`asr-turbo`), speaker labels (`diarize`),
audio event tags (`events`), Supertonic voices (`supertonic`), DeepFilterNet (`deepfilter`).
`showtime setup --plan` lists every component with its size, URL, sha256 and when it is fetched. On a
machine that will be offline later, run `showtime setup --full` while online (everything now, nothing
fetched later), or copy the files from `showtime setup --plan --urls` and use `--seed DIR`. A
first-use fetch while offline fails with exit code 3 and says exactly that.

When a feature needs a missing extra, the command fails with exit code 3 and prints the exact
`showtime setup --with <name>` line and its size. Relay it, ask, install, continue. Setting
`SHOWTIME_AUTO_INSTALL=1` lets it install without asking; only set it if the user says so.

## 5. Where things live

`showtime paths` prints them. Everything is under `~/.showtime` (move it with `SHOWTIME_HOME`): the
ffmpeg build, the Python venv, Node packages, models, SoundFonts, the audio library, fonts and caches.
Videos go to `./showtime-out/` in the folder the user works in (`SHOWTIME_OUT` moves it).

## 6. If setup fails

1. Re-run `showtime setup`: most failures are interrupted downloads, and it resumes.
2. `showtime setup --verify` re-hashes installed files; `--force` reinstalls.
3. Still failing: `showtime doctor --report` writes a redacted `bug-report.md` (nothing is uploaded).
   Read `diagnosing.md` for the triage order.

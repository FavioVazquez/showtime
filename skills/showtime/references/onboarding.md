# Onboarding: the first-run conversation

Read this when `showtime doctor --quick` reports failures, when a command says setup has not been run,
or when the user is new to showtime ("how do I set this up?", "what do I need?"). The goal is one
short exchange: what is there, what is missing, one decision, then the install, then back to the video.

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

> showtime needs a one-time install into `~/.showtime`: about 2.9 GB, usually 3-11 minutes. Nothing
> outside that folder changes. Install the default now? (recommended)

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
- A long setup should run in the background with progress checks, not block your turn.
- The first doctor (or render) after a restart can take a few minutes while the OS checks native
  libraries, macOS especially; doctor says so and shows what it is checking. Tell the user it is
  not stuck; later runs take seconds.
- Behind a proxy or offline: `showtime setup --seed DIR` reuses files downloaded elsewhere
  (matched by size and sha256).

Done when `showtime doctor` shows 0 fail. Warnings each come with a `fix:` line; most are optional.

## 4. What works now, what arrives later

Say this in two or three lines so nothing surprises the user later:

| Works right after the core install | Fetched or installed on first use (with a one-line notice) |
|---|---|
| HTML and canvas videos, all templates, preview, render, check, snap | the local audio library (`showtime audio lib fetch`, about 249 MB, about 10–15 min) |
| generated music, all 56 effect types, mixing, mastering | Whisper turbo for the best multilingual transcripts (`showtime setup --with asr-turbo`) |
| Kokoro voices (English, Spanish, more) with word timings | speaker labels (`--with diarize`), audio event tags (`--with events`) |
| transcription with small models, footage edits, captions | Supertonic voices (`--with supertonic`), Piper voices, the English aligner (automatic) |
| site capture, demo recording, auto zoom, fonts, icons, exports | background removal outside macOS (rembg, automatic; its default model is about 170 MB), DeepFilterNet (`--with deepfilter`) |

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

# Diagnosing a problem the user reports

Read this when the user says the video "came out wrong", "it's slow", "setup failed", "it worked yesterday",
or wants to report a bug in showtime. It covers intake, where the evidence lives, how to read it without
flooding the context, and the local bug report. The fix itself follows `debugging-renders.md`.

## Essentials

- Ask one question with a default: what did you expect, what did you see, at what time (offer a contact
  sheet); never ask what `SHOWTIME.md` or the conversation already answers (§1)
- Start with `showtime status` and `showtime job show`; fresh evidence from `showtime qa <job> --json` and
  `showtime check <project> --json`; compare the path qa prints with the file the user watched (§2, §3)
- Read logs with bounds (the last 40 lines, or `error|fail|exception` matches); never paste a whole log (§3)
- Every finding cites its source (`work/logs/render.log:212`); numbers come from output, not memory (§4)
- `showtime report [job] --problem "..."` writes a local `bug-report.md`: the user reads it before sharing;
  show the exact issue text and wait for approval before any `gh` command (§6)
- State the cause in one sentence with its evidence, fix it, record `showtime job note --verified "..."` (§7)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. Intake: one question | 30-37 |
| 2. Evidence on disk | 39-54 |
| 3. Read with bounds | 56-66 |
| 4. Findings cite their source | 68-72 |
| 5. Where to look first | 74-84 |
| 6. The bug report (local only) | 86-94 |
| 7. Hand off | 96-100 |

## 1. Intake: one question

A complaint is not yet a problem statement. Ask one question that gets all three parts, with a default:

> What did you expect, what did you see instead, and at what time in the video? (If you are not sure of the
> time, I'll make a contact sheet and you can point at a frame.)

Do not ask anything already answered in `SHOWTIME.md` (its "Answered" list) or in the conversation.

## 2. Evidence on disk

Every job folder (`showtime-out/<slug>-<timestamp>/`) keeps its own flight record:

| File | What it tells you |
|---|---|
| `SHOWTIME.md` | goal, stage, what was verified vs only assumed, open questions, next command |
| `job.json` | versions (showtime, python, node, ffmpeg, browser), OS/arch, stage timings, cache hits, warnings, qa verdict, `pointers.project` (recorded by `new` inside the job or `new --job`, `render --job`, `job note --project`), `outputs` (the latest final, draft, EDL, poster, share, credits, captions and studio animatic; `showtime job note <job> --output KIND=PATH` sets one; `output_log` keeps the history) |
| `render.json` | frames, workers, browser, capture and encode settings, audio loudness, warnings, timings, the log path (with `--job` or `-o`: `<video>.work/render.json`) |
| `<video>.work/logs/render.log` | every ffmpeg command with its stderr, browser page and console errors, blocked requests, the failure stack |
| `work/logs/`, `work/diagnostics/` | full tool output and the screenshot/DOM/log saved next to a failure |
| `work/qa/<video>/qa.json` | the last qa verdict with timestamps and frame paths |
| `<project>/work/check/report.json` | the last `showtime check` findings and the on-screen text list |
| `<project>/audio/mix.report.json` | loudness, per-track levels, library items and credits |

Start with `showtime status` (three lines) and `showtime job show` (the whole `SHOWTIME.md`).

## 3. Read with bounds

Logs can be megabytes. Measure before reading, and read only what answers the question:

- `showtime status`, `showtime job show --json` for the ledger;
- the last 40 lines of a log, or the lines that match `error|fail|exception`;
- `showtime qa <job> --json` (the latest final; it prints which file) and `showtime check <project> --json`
  for fresh, structured evidence. "It came out wrong" after a re-render often means an older file was
  opened: compare the path qa prints with the one the user watched.

Never paste a whole log into the conversation or into a command.

## 4. Findings cite their source

Each finding names where it came from: `work/logs/render.log:212`, `render.json timings.capture`, or
`t=8.20s frames/t0008.200s.jpg`. Numbers are copied from command output, never from memory. A finding without
a source is a guess: either find the source or drop it.

## 5. Where to look first

| Complaint | Look first |
|---|---|
| "too slow" | `render.json` timings and workers, `job.json` cache hits/misses, `check`'s estimate |
| "audio is off" | `mix.report.json`, `qa` loudness/`av_length`/`silent_gap`, the hit offsets in the mix |
| "looks different from the preview" | `check --determinism`, `font_not_embedded`, GPU flags in `render.json` |
| "text is cut off / unreadable" | `check` layout and contrast findings at the cited time, `snap --at t` |
| "black / stuck frames" | `qa` `black_segment`/`frozen` timestamps, then `check --find-first black|frozen` |
| "setup failed" | `showtime doctor`, `~/.showtime/logs/` |
| "it worked before" | compare `job.json` env blocks of the good and the bad job (versions, browser, tier) |

## 6. The bug report (local only)

`showtime report [job] --problem "<what happened>"` writes `bug-report.md` into the job folder (or the current
folder): an environment table, a quick doctor run, the ledger excerpt, qa and check verdicts, and the tail of
logs that contain errors. Home paths become `~`, the user name `<user>`, e-mail addresses `<email>`, and
anything that looks like a token or password `<REDACTED>`; the result is re-scanned until nothing matches.

Nothing is uploaded. Tell the user where the file is and that they should read it before sharing. If they
want a GitHub issue, show the exact text and wait for their approval before running any `gh` command.

## 7. Hand off

State the cause in one sentence with its evidence, then fix it following `debugging-renders.md`. Record what
was learned with `showtime job note --verified "..."` or `--warning "..."` so a later session does not repeat
the investigation.

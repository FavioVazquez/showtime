# Debugging renders: find the cause before changing anything

Read this when a render fails, flickers, shows black or frozen frames, looks different from the preview,
drops fonts or media, drifts out of sync, or when a fix you already tried did not work. For "the video came
out wrong" reports from the user, start with `diagnosing.md` (intake and evidence), then come back here.

## Essentials

- Name the cause, with the output that shows it (start with the render's `log <path>`), before editing; no
  sleeps or timeouts as fixes, gate on the thing itself (`ST.waitFor(promise)`) (§ Rules)
- Rule out the machine: `showtime new dom st-probe --duration 3`, `showtime render st-probe --preview`; if that
  fails too, `showtime doctor` (§ Rules)
- One change per re-render (`showtime render <project> --from 4 --to 7 --preview`), compare `showtime snap` stills
  at the same times; after three failed fixes, change the approach and tell the user (§ Rules)
- Bisect in time: `showtime check <project> --find-first black|frozen|nondeterministic|error` (§ Bisect in time)
- After the fix, re-run the command that showed it, quote its output, then `showtime qa` the new file (§ Symptom)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Rules | 27-51 |
| The pipeline and what reveals each hand-off | 53-68 |
| Bisect in time, not in code | 70-82 |
| Determinism | 84-94 |
| Symptom → first move | 96-111 |

## Rules

1. **Evidence first.** Name the cause, with the command output that shows it, before editing the project.
   A change made on a guess costs a re-render and hides the real fault. Start with the log the render
   printed (`log <path>`: `<video>.work/logs/render.log`, with every ffmpeg command, browser page and
   console errors, blocked requests and the failure stack).
2. **Rule out the machine.** Render the matching template with the same flags:
   `showtime new dom st-probe --duration 3`, then `showtime render st-probe --preview`
   (use `film` for canvas projects). If the template also fails, the environment is at fault:
   run `showtime doctor`, not a scene edit.
3. **No sleeps.** Never "fix" flicker, missing images or blank fonts with a delay or a timeout. Gate
   readiness on the thing itself: `ST.waitFor(promise)` for fonts, images and data; an awaited `seeked`
   for video. Tools follow the same rule: wait for a file or a port, never for N seconds.
4. **One change per re-render.** Change one thing, re-render only the affected range
   (`showtime render <project> --from 4 --to 7 --preview`), and compare stills at the same timestamps
   (`showtime snap <project> --at 5.2,6.0`) with the ones from before.
5. **Three strikes.** After three failed fixes for the same symptom, stop patching. Change the approach
   (another adapter, move the effect from DOM to canvas, pre-render the element to a video clip, drop the
   effect) and tell the user what you tried, what each attempt showed, and what you will do instead.
6. **Guard every layer the bug crossed.** When you find a cause, add the check that would have caught it
   earlier (a `check` or `qa` rule plus a fixture in `tests/fixtures/defects/`) so it cannot come back quietly.

Signals from the user that you are guessing: "that's not what I see", "it still flickers", "you changed the
wrong thing", "it was fine before". The answer is a snap or a contact sheet at the timestamp in question,
not another blind edit.

## The pipeline and what reveals each hand-off

A render passes through these boundaries. Find the first one where the output is already wrong.

| Hand-off | What goes wrong there | Command that shows it |
|---|---|---|
| project → server | 404s, wrong paths, remote URLs (renders are offline) | `showtime check <project>`: `missing_file`, `network`, `request_failed` |
| server → page ready | a promise never resolves, a script throws on load | `check`: `ready_failed` names what it is still waiting for; `showtime preview <project>` shows the console |
| page → seek | a scene handler throws for some `t` | `check`: `seek_error`; `showtime check <project> --find-first error` |
| seek → pixels | real-time timers, CSS transitions, unseeded randomness, unawaited video | `check`: `timers`, `css_transitions`, `unseeded_random`, `nondeterministic`, `unstable_frame`; `--determinism`; `--find-first nondeterministic` |
| pixels at one time | wrong layout, blank text, missing font glyphs | `showtime snap <project> --at t` compared with `preview` at the same `t`; `check`: `font_*`, `text_*`, `safe_zone`, `low_contrast` (canvas films included) |
| timeline | black gaps between clips, stalls | `--find-first black`, `--find-first frozen --min 1` |
| capture → encode | missing or retried frames, wrong frame count | `render.json` (`frames`, `warnings`, `timings`), `work/diagnostics/` |
| encode → file | codec, pixel format, colour tags, faststart, duration | `showtime qa <final.mp4>` |
| audio: score / mix → master → mux | silence, clipping, wrong loudness, drift | `showtime score <project>` (music only), `audio/mix.report.json`, `showtime audio meter <file>`, `qa`: `loudness`, `true_peak`, `clipping`, `silent_gap`, `av_length` |
| master → platform files | wrong size, too long, too big | `showtime qa <export> --platform reels` (and the other targets) |

## Bisect in time, not in code

Video faults live at a moment. `showtime check <project> --find-first <probe>` scans the timeline coarsely,
then halves the interval until it has the exact frame, and saves that frame and the last good one:

| Probe | Finds | Typical cause |
|---|---|---|
| `black` | first near-black frame | a clip window gap (`data-start`/`data-dur`), a video that failed to load |
| `frozen` | first frame of a still stretch of at least `--min` seconds | a paused timeline, a missing adapter, a gap after re-timing scenes |
| `nondeterministic` | first frame that differs when reached by a jump vs by stepping, or after 150 ms | a timer, `Date.now()` at load, `Math.random()`, a video not awaited |
| `error` | first time where the seek handler throws | an index out of range, data that runs out |

Narrow it with `--from`/`--to` and `--step`. Exit code 1 means a bad frame was found.

## Determinism

A frame must be a pure function of `t`. `showtime check` probes 4 frames by default; `--determinism` probes 12
and also loads the page a second time (like a second render worker) and compares hashes. Differences of 1-2
levels on edges are GPU rasterisation noise and are reported as notes, not errors. Real differences come from:

- `setTimeout`/`setInterval` driving visuals (they run on real time),
- CSS transitions (use keyframes or a timeline),
- `Math.random()` inside a draw or seek function (create `ST.rand(seed)` once; Film: `F.rng`/`F.hash`),
- media not awaited (`ST.waitFor`, `<video data-st>`),
- anything read from the wall clock at load.

## Symptom → first move

| Symptom | First move |
|---|---|
| Flicker or jitter | `showtime check <project>`; look for `timers`, `unseeded_random`, `css_transitions` |
| Looks different from the preview | `--determinism`; `snap` vs `preview` at the same `t`; `font_not_embedded` |
| Text in the wrong font | `check` fonts section; load files with `@font-face` or `/_lib/@fontsource...`, await them |
| Black or empty stretch | `--find-first black`, then the clip windows around that time |
| Nothing moves for seconds | `--find-first frozen`, or `qa` `frozen` with its timestamp |
| Audio out of sync | the mix report's hit offsets; `qa` `av_length`; re-render the range, never retime to hide it |
| Audio too quiet, loud or distorted | `qa` `loudness`/`true_peak`/`clipping`; `showtime audio meter` on each stem |
| Render crashes or times out | `showtime doctor`; retry with `--workers 1` or `--gpu off`; `work/diagnostics/` |
| Slow | `render.json` timings, `check`'s estimate and `heavy_effects` note (large blurs, backdrop filters) |

When the cause is found and fixed, re-run the command that showed it and quote its new output. Then run
`showtime qa` on the new file before calling the video ready.

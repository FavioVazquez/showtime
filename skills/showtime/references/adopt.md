# Adopting a video written as a function of time

Read this when the user already has a video written as code: an HTML page with `seek(t)`, `render(t)`,
`draw(t)` or `setTime(t)`, a canvas page, a page animated with CSS, or a Python script that draws frames
and pipes them to ffmpeg. It also applies when you wrote one yourself without showtime's templates. Adopt
it; do not rewrite it into a template.

```
showtime adopt launch-video/                    # finds the page, its time function, size and length
showtime check <project>                        # adopt runs it once for you
showtime render <project> --job <job>           # --from/--to for a range, as for any project
showtime qa <job>
showtime export html <project>                  # the same page as a shareable web video
```

`adopt` copies the folder into `<project>/src/`, so the original files are never changed. It skips
`node_modules`, virtualenvs, `.git`, frame dumps and videos the page does not load. Around the copy it writes
`index.html`, `showtime.json` and `adopt.json`, the last one recording what it found and where each value
came from. After that the project behaves like any showtime project: `check`, `snap`, `render` (including
`--from/--to`), `preview`, `qa`, `captions`, the `audio/mix.json` audio track, `export html` and
`review-pack`. With no `-o`, a new job is created (`showtime-out/<name>-<ts>/project`); `--job <job>`
adds the project to an existing one.

## Essentials

- Adopt, do not rewrite into a template: `showtime adopt <folder>` copies it to `<project>/src/` and runs
  `showtime check`; then `showtime render <project> --job <job>` and `showtime qa <job>` (§ What adopt checks)
- Override wrong guesses: `--seek`, `--fn`, `--unit s|ms|frame`, `--ready`, `--duration`, `--fps`, `--size`,
  `--mode page|clock|python|capture` (§ Contracts it recognises)
- Exit 1 means fix first; `nondeterministic`: compute every value from `t` (timers and a library on its own
  ticker do not follow the virtual clock) (§ What adopt checks, § Limits)
- After editing an adopted Python script: `showtime adopt <project> --refresh` (§ Python scripts)
- The render masters the mix to -14 LUFS (§ Sound)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Contracts it recognises | 44-58 |
| What adopt checks | 60-79 |
| Python scripts | 81-95 |
| Sound | 97-103 |
| Limits | 105-111 |

## Contracts it recognises

| Contract | What the source looks like | How showtime drives it |
|---|---|---|
| `page` | `window.seek = t => ...`, `function render(t)`, `window.draw = function (t)`, `setTime(t)`, `app.seekTo(t)`; a `DURATION` global | `index.html` loads the stage runtime, then the page; `/_st/adopt.js` calls the time function on every seek |
| `clock` | only CSS `@keyframes`, Web Animations or a `requestAnimationFrame` loop that reads `performance.now()` | the stage's virtual clock: animations are paused and set to the frame time, rAF runs once per frame |
| `python` | a script whose frame function (`render(t)`, `make_frame(t)`, `render_frame(i)`, ...) returns a Pillow image, a numpy array or RGB bytes, with an `if __name__ == "__main__":` guard | the script is imported in a separate process and asked for every frame; the frames become `media/frames.webm`, which `index.html` plays frame-exactly |
| `capture` | a Python script with no such function (it builds each frame inside `main()`) | its own `main()` runs once on the copy; the video it writes is ingested, and its sound goes into the mix |

Detection uses the page, its local scripts and the render driver found next to it (puppeteer,
playwright or raw DevTools code). Adopt reads the driver and never runs it. The driver tells it which
function is called per frame, in which unit (`${t}`, `${t*1000}`, a frame number), the viewport size,
the fps, the length, a `ready` promise it awaits, and any setup call such as `window.setData(rows)`.
Flags override every guess: `--seek`, `--fn`, `--unit s|ms|frame`, `--ready`, `--duration`, `--fps`,
`--size`, `--mode page|clock|python|capture`, `--page`, `--script`.

## What adopt checks

- **Determinism.** Each sampled frame is captured twice: first in order, then in reverse after other
  frames. For pages, frame 0 is captured once more after 150 ms of real time. Differences in solid areas are
  an error (`nondeterministic`); differences only on antialiased edges are reported as `raster noise`. A
  capture-mode script cannot be checked this way, and the report says so ("not measured").
- **`showtime check`** runs at the end, unless you pass `--no-check`. Its report and contact sheet are
  written to `work/check/`.
- The exit code is 1 when something must be fixed first. Every problem is printed with what happened, why
  and how to fix it.

| Code | Means | Fix |
|---|---|---|
| `needs_setup` | the driver called something like `setData(rows)` before the frames, with data the page does not load | write that call in a JS file (it runs in the page and may `await fetch(...)`), then `--setup setup.js` |
| `no_time_function` | the named function is not a global (a module script, a closure) | `--seek <name>` for another name; otherwise expose it as `window.seek = ...` in a copy |
| `no_duration` | no `DURATION`-like global, nothing in the driver, and no finite CSS animation | `--duration <seconds>` |
| `outside_ref` | the page loads `../data.csv` from outside the folder | adopt the parent folder, with `--page sub/video.html` |
| `nondeterministic` | the frames depend on order or real time | compute every value from `t`; `check` lists timers |
| `no_contract` | no time function and no animations | a static page is a still, not a video |
| `remote` (warning) | fonts or scripts are loaded from the internet, which renders block | copy them into the folder, or use `/_lib/@fontsource/...` |

## Python scripts

- **Interpreter.** Adopt uses the folder's `.venv`/`venv` first, then showtime's, then `python3`, so the
  script finds its own packages. Pass `--python <path>` to choose another.
- **Where it runs.** The script runs in its own process, from its folder inside the copy. Showtime's
  ffmpeg is first on `PATH`, so bare `ffmpeg`/`ffprobe` calls work. A wall-clock limit applies
  (`--timeout` minutes, default 30).
- **Network.** Sockets to other machines are refused inside the Python process (`--allow-network` lifts
  this). This is a guard rail, not an operating-system jail: the script can still write files anywhere it
  could before, so adopt only code you would run yourself.
- **Frames.** Frame functions run in up to 8 processes (`--workers`). The frames are encoded once as
  near-lossless VP9 with a keyframe every half second.
- **After editing.** Once you edit the original script, run `showtime adopt <project> --refresh`. It copies
  the source again and redraws all frames; `render --from/--to --job <job>` then re-renders only the range you changed, spliced into the job's final.
  Your `audio/mix.json`, captions and poster settings are kept.

## Sound

Audio files that the driver or script muxes and that exist in the folder go into `audio/mix.json` at
their own level (`"level": "raw"`). In capture mode, the audio track of the video the script wrote goes
there instead. Numbered clips a script placed itself (`vo/final_1.wav` ...) are listed in `adopt.json` but
not placed, because their times live in the script. From here, add music, sound effects or a voice-over
to the mix as for any project (`references/audio.md`). The render masters the mix to -14 LUFS.

## Limits

- Top-level `const`/`let`/`function` in classic scripts are visible to the adapter; names inside ES
  modules are visible only when the page assigns them to `window`.
- Animations driven by `setTimeout`/`setInterval`, and GSAP on its own ticker, do not follow the virtual
  clock. Adopt warns about them, and `check` reports the frames they break.
- A page that sets its own `<base>` cannot be adopted as it is.

# Adopting a video written as a function of time

Read this when the user already has a video written as code: an HTML page with `seek(t)`, `render(t)`,
`draw(t)` or `setTime(t)`, a canvas page, a page animated with CSS, a Claude Design animation exported as
HTML, or a Python script that draws frames and pipes them to ffmpeg. It also applies when you wrote one
yourself without showtime's templates. Adopt it; do not rewrite it into a template.

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
- A Claude Design animation: export the HTML zip, `showtime adopt <file>.zip`; the artboard fills the frame,
  fonts are copied in, a loop renders one period (§ From Claude Design)
- The render masters the mix to -14 LUFS (§ Sound)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Contracts it recognises | 47-61 |
| What adopt checks | 63-86 |
| Python scripts | 88-102 |
| Sound | 104-110 |
| From Claude Design | 112-139 |
| Limits | 141-147 |

## Contracts it recognises

| Contract | What the source looks like | How showtime drives it |
|---|---|---|
| `page` | `window.seek = t => ...`, `function render(t)`, `window.draw = function (t)`, `setTime(t)`, `app.seekTo(t)`; a `DURATION` global | `index.html` loads the stage runtime, then the page; `/_st/adopt.js` calls the time function on every seek |
| `clock` | only CSS `@keyframes`, Web Animations or a `requestAnimationFrame` loop that reads `performance.now()` | the stage's virtual clock: animations are paused and set to the frame time, rAF runs once per frame. The length comes from the clock (`% 13` loops, `Math.min(t, 12)` ends at 12 s) or from the animations (finite ones end; ones that repeat forever give one loop) |
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
| `remote` (warning) | fonts or scripts are loaded from the internet, which renders block | copy them into the folder, or use `/_lib/@fontsource/...`; Google Fonts links are copied for you |
| `fonts_offline` (warning) | the Google Fonts the page links could not be downloaded (no network) | when online, `showtime adopt <project> --refresh` |
| `fonts_license` (warning) | a family the page links is not OFL, Apache, MIT or UFL (or not in the Fontsource catalog), so it was not copied | use another font; if you may use it, `showtime adopt <project> --refresh --allow-license` |
| `fonts_failed` (warning) | the fonts could not be copied for another reason (the message says which) | copy them into the folder yourself, or use `showtime assets font <name>` |
| `loop_seam` (warning) | a looping page: the frame after the last is not frame 0 again, so the loop jumps | `--duration` with the length after which every animation is back at its start |

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

## From Claude Design

Claude Design builds animations as live HTML and has no video export. Export the design as HTML (a zip
with `Main.dc.html`, `support.js` and `vendor/`) and adopt the zip, or the folder you unpacked it into:

```
showtime adopt "Launch (12s, 16 9)-html.zip"    # unpacked into <project>/src/; the zip is not changed
showtime render <project> --preview             # then the final render and qa, as for any project
```

- **Detection.** The page has an `<x-dc>` template and a `<script data-dc-script>` logic class. `adopt.json`
  says "Claude Design export". It is a clock page: the design's own runtime runs on the virtual clock.
- **Size.** The artboard size comes from the export (`$preview`). The video keeps its aspect at 1080 on the
  short side: a 1280x720 artboard renders at 1920x1080, a 540x960 one at 1080x1920. The page is laid out
  again at that size with CSS zoom, so text stays sharp. `--size` picks another size; a different aspect is
  centred.
- **Fonts.** Google Fonts links are replaced by the same files, downloaded at adopt time into
  `<project>/fonts/` with their licenses (OFL or Apache), so renders are offline and the same on every
  system. This is the one time adopt goes online by itself: it asks fonts.googleapis.com and
  fonts.gstatic.com for the files, and api.fontsource.org and raw.githubusercontent.com for the licenses.
  Only files from fonts.gstatic.com are copied. Offline (or with `SHOWTIME_OFFLINE=1`), the summary says
  what to run later: `showtime adopt <project> --refresh`. A refresh reuses fonts already in the project
  (checked by their sha256) and needs no network.
- **Length.** A clock in the logic class gives it: `((now - start) / 1000) % 13` with `Math.min(t, 12)`
  ends at 12 s, where the animation ends. CSS animations that repeat forever give one loop: the time after
  which all of them are back at the start (an `alternate` one takes two durations). Adopt checks that the
  frame after the last is frame 0 again and says `seamless`. `--duration` still wins.
- **Then.** Add a voice-over, music, captions and platform exports as for any project.

## Limits

- Top-level `const`/`let`/`function` in classic scripts are visible to the adapter; names inside ES
  modules are visible only when the page assigns them to `window`.
- Animations driven by `setTimeout`/`setInterval`, and GSAP on its own ticker, do not follow the virtual
  clock. Adopt warns about them, and `check` reports the frames they break.
- A page that sets its own `<base>` cannot be adopted as it is.

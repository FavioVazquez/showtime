# Rendering, checking and previewing a project

Read this when you are about to look at, check or render a showtime project; when a render is
slow, fails, or looks different from the preview; or when you need the exact flags and outputs of
`showtime render`, `check`, `snap`, `preview`, `server` and `retime`.

## The loop

```
showtime new dom my-video -d 20     # or film / short / data / tutorial; the whole timeline fits 20 s
showtime preview my-video            # player with scrubber and audio; reloads on save
showtime check my-video              # QA gate: fix every error, read every warning
showtime snap my-video               # contact sheet (look at it) or --at 2.5,7 for stills
showtime render my-video --preview   # quick 720p draft
showtime render my-video             # final: showtime-out/<title>-<timestamp>/final.mp4
showtime render my-video --job <job> # final into a job: <job>/final.mp4 (final-2.mp4 on a re-render)
showtime retime my-video -d 30       # change the length later: scenes, poster, mix and cues move together
showtime retime my-video --from-voice my-video/voice/timeline.json   # scene lengths from the narration
```

Every command has `--help` with examples, prints the paths it wrote, and takes `--json` for a
machine-readable result. Errors end with a `fix:` line; add `--debug` for a stack trace.

## `showtime render <project>`

A project is a folder with `showtime.json` and `index.html` (or pass an `.html` file / `--page`).

| Option | Default | Notes |
|---|---|---|
| `-o FILE` | new job folder | never overwrites: an existing name gets `-2`, `-3`...; inside a job folder the file is recorded as the job's latest final (or draft) |
| `--job JOB`, `-j` | none | a job folder or name: writes `<job>/final.mp4` (`final-2.mp4`... on a re-render, `preview.mp4` with `--preview`) and records it in job.json `outputs`, so `showtime qa <job>` checks it. Not with `-o` |
| `--out-dir DIR` | `$SHOWTIME_OUT` or the current folder | job folder is `DIR/showtime-out/<title>-<timestamp>/` |
| `--preview`, `-p` | off | a draft: at most 720p, x264 veryfast CRF 23, AAC 128k, no poster bake; the file is named `preview.mp4` |
| `--from S --to S` | whole video | re-render one section (audio is cut to match; no poster bake) |
| `--fps N` | showtime.json | |
| `--workers N`, `-w` | auto: up to 3 | separate browsers, each renders a contiguous range in order |
| `--scale X` | 1 | `0.5` = half size, `2` = supersampled (sharper text, 4x the pixels) |
| `--alpha prores\|animation\|webm` | off | transparent background (the themes' scene and stage fills turn transparent; a background a scene sets itself still paints; mark an overlay page `<body data-overlay>` so `check` does not call its gaps dead air): ProRes 4444 `.mov` (editors; large: a 1 s full-frame 1080p stinger is about 30 MB), QuickTime Animation `.mov` (editors; lossless RGBA, a fraction of that for flat graphics such as lower thirds and stingers, larger than ProRes for photos and gradients) or VP9 `.webm` (web) |
| `--format jpeg\|png` | jpeg (q92) | png is lossless and ~1.5x slower to capture |
| `--crf N`, `--x264-preset P` | 16 / medium (preview 23 / veryfast) | lower CRF = better and bigger. For masters kept in a repo or an example folder, `"render": {"crf": 18}` in showtime.json: about 20-25 % smaller with no visible loss on flat graphics (a 35 s code video: 22.6 MB at 16, 17.9 MB at 18). Keep 16 (or 14-16 with grain) for anything a platform re-encodes |
| `--poster S` / `--poster none` | showtime.json `poster` | the frame at S becomes poster.jpg (and frame 0, see `--poster-bake`) |
| `--poster-bake auto\|force\|off` | auto | auto bakes the poster into frame 0 only when it looks like the opening frame (else frame 0 would flash on autoplay and loops) |
| `--lufs N`, `--no-loudnorm`, `--no-audio` | -14 LUFS, -1 dBTP | |
| `--allow-silent` | off | a project with audio (ST.score or an `audio` mix) fails when its audio fails twice; this ships it silent instead |
| `--gpu off` | auto | software rendering: slower, most reproducible across machines |
| `--settle raf1\|raf2\|none` | raf1 | paint wait after each seek (raf2 is extra safe; none can miss paints) |
| `--keep-frames` | off | keep `work/frames/` |
| `--size WxH\|9:16` | showtime.json, else the page's `ST.config` | one page, another size for this run (a 9:16 cut of a 16:9 page: the page reads the frame aspect, components size by container units). With `--job` the file is `<job>/1080x1920.mp4`, recorded as a variant; `check` and `snap` take `--size` too |

Encode settings you ship with belong in showtime.json, so every re-render keeps them (flags still win;
a draft `--preview` ignores the block):

```json
"render": {"crf": 22, "x264_preset": "slow", "format": "png", "poster": "none"}
```

Keys: `crf`, `x264_preset`, `format`, `quality`, `poster`, `poster_bake`, `settle`, `workers`, `lufs`.
A final more than twice the size of the previous final in the same folder gets a warning naming the
settings that one used. A re-render next to an existing `final.mp4` writes `final-2.mp4` (an info
line, not a warning). Over 20 MB, the summary prints the command for a size-capped copy
(`showtime deliver exports <file> --targets original --max-mb 20`); grain, dust and noisy photo textures
cost the most bitrate. A final above about 25 Mb/s (at 1080p) gets a hint too: that is almost always
animated film grain (`grainFps` above 0 in a film look: 240 MB for 30 s), which static grain
(`grainFps: 0`) or `crf 18` shrinks.

What happens:

1. The project is served on `127.0.0.1` (random port). One headless Chrome/Edge/Chromium per
   worker opens the page with the render-mode runtime (virtual clock, seeded randomness, network
   blocked) and waits for `ST.ready()`.
2. Frames are split into contiguous ranges. Each worker first replays (without capturing) the
   second before its range, then seeks every frame in order and captures it with the Chrome
   DevTools screenshot call. Missing or empty frames are captured again; a crashed browser is
   restarted up to twice, with a screenshot, the DOM and the console saved to `work/diagnostics/`.
3. One encode: H.264 High, yuv420p, BT.709 matrix with accurate rounding, BT.709/tv tags, no
   B-frames (first frame never freezes in picky players), keyframe every 2 s, `+faststart`.
4. Audio, prepared while frames are captured: `ST.score` rendered offline in its own page, plus
   the showtime.json `audio` (a mix spec goes to `showtime audio mix`; if that module is missing,
   a built-in mixer handles file tracks with start/offset/gain/fades/loop). Everything is cut to
   the rendered range, padded/trimmed to the exact video length, brought to the loudness target
   (plain gain when the peaks allow it, else gain into an oversampled limiter with at most 6 dB of
   limiting and a warning if the target is out of reach), encoded as AAC 192k in `.m4a` (keeps the
   encoder delay, so sync is exact), checked for true peak, and muxed without re-encoding video.
5. Poster: with a `poster` time, that frame is saved as `poster.jpg` and copied over frame 0
   before the single encode (feeds and chat apps show frame 0), but only when it looks like the
   opening frame (`--poster-bake auto`). A poster over an opening that builds from empty would show
   as a one-frame flash on autoplay and on every loop, so it is not baked and the summary says why.
   The best default is a hook that is complete at t=0 with `"poster": 0`; for YouTube and other
   platforms that take a custom thumbnail, upload `poster.jpg` instead. Without a poster time,
   `showtime deliver poster` picks a sharp, representative frame for `poster.jpg` (not baked).
   qa WARNs `poster_flash` when frame 0 differs sharply from frame 1.
6. The result is probed (frame count, duration) and a report is written.

Output folder:

```
showtime-out/my-video-20260926-101500/
  final.mp4          (the draft is preview.mp4; .mov/.webm for --alpha; final-2.mp4 on a re-render)
  poster.jpg         (<stem>.poster.jpg for any other name)
  credits.txt        only when the mix or the project's CREDITS.txt/credits.txt lists CC-BY items
                     (<stem>.credits.txt for any other name; also written with -o)
  final.work/        the render's work folder: <stem>.work/ with --job or -o, work/ in a new job folder
    render.json      settings, browser, timings, capture fps, loudness, warnings, ffprobe summary, "log"
    logs/render.log  every ffmpeg command with its stderr, browser page errors, console errors and
                     warnings, blocked requests, HTTP errors >= 400, warnings, the failure stack
    video.mp4 (no audio), audio/{score,mix,combined,master}.wav + master.m4a,
    frames/ (with --keep-frames), diagnostics/ (after failures)
```

The summary ends with the `output`, `poster`, `report` (render.json) and `log` paths; after a
failed or odd render, read `render.log` first (`debugging-renders.md`). A render whose output is
under `<job>/studio/` (an animatic: `-o <job>/studio/media/animatic/<id>.mp4 --preview`) is logged
as a job event and recorded as the job's `animatic`, never as its latest preview or final; its work
folder goes to `<job>/work/renders/<name>.work/`, so `studio/` holds only media.

## `showtime check <project>`

Run it before every final render; a video is not ready while it reports errors. It loads the page
exactly like the renderer and reports findings with the time they happen and a fix.

| Code | Severity | Means |
|---|---|---|
| `ready_failed`, `page_error`, `seek_error` | error | the page throws, or never becomes ready |
| `network`, `missing_file` | error | remote request (blocked in renders) or 404 |
| `unstable_frame` | error | pixels keep changing after a seek finished: something runs on real time |
| `nondeterministic` | error | a frame differs when reached in another order (state kept between frames) |
| `clip_timing`, `video` | error | bad `data-start`/`data-dur`, or a video that cannot be decoded/seeked |
| `font_load_failed` | error | an `@font-face` file failed |
| `low_contrast` | warning (error below 2:1) | WCAG contrast of text against the real pixels behind it: 4.5:1, or 3:1 for text >= 24px (>= 18.7px bold). Measured where each text is fully faded in, not blurred and outside scene transitions; a text seen only mid-transition gets an info note naming the transition. |
| `font_not_embedded` | warning | text is painted with a system font (differs between Mac, Windows and Linux) |
| `text_off_canvas`, `text_clipped`, `text_overlap` | warning | layout problems at the sample times; overlaps are measured on the painted glyphs (not line boxes, so big display type with tall leading is not a false alarm) and say how deep they are; `text_overlap` also covers text hidden under a badge, callout or pill ("X is hidden under Y"), in canvas films too (an `F.callout` card over readable text drawn before it). Found only mid-transition, they are info notes naming the transition ("mid-transition: push into #demo; the settled frame at 0:04.43 is judged on its own"): check samples the settled frame 2 frames after every transition too |
| `labels_crowded` | warning | SVG labels (chart values and axes, map names) whose painted glyphs touch or sit closer than 0.15em side by side or stacked (`label_gap_em` in `runtime/thresholds.json`); one finding per graphic naming the worst pair. While a chart is still growing or morphing it is an info note. Fix: fewer bars, the default `valueLabels` (auto-thinning), a larger plot, or a line chart |
| `callout_off_target` | warning | canvas film: an `F.callout` card is on screen but its anchor is off the frame (the camera moved away from what it points at), or the card itself runs off the frame |
| `safe_zone` | warning | vertical video: text outside the box that feed UIs leave free (x 64-916, y 220-1440 at 1080x1920); the message names the edge ("top at y 185 < 220") |
| `edge_margin` | warning | landscape: text fully in frame but within 3% of an edge (player controls, overscan); keep 5% (96 px at 1920) |
| `control_strip` | warning | landscape: text under 32 px (at 1080p) in the bottom 8%, where a player's progress bar and controls sit |
| `short_text` | warning | text on screen for less than it takes to read (17 characters/s + 0.3 s, min 1 s); mark text read along with the voice `data-caption` |
| `poster_not_baked` | info | showtime.json `poster` is set, but the frame differs from the opening, so `render` (`--poster-bake auto`) will not bake it into frame 0 (it would flash on autoplay and loops); poster.jpg is still written. Start the video in the poster's state, or `"render": {"poster_bake": "force"}` |
| `dead_air` | error / warning | error: for 1.5 s or more no clip is showing (a gap between scenes, or scenes that end before the video does; canvas: only the flat backdrop is drawn), listed in report.json `timeline_holes` (`from`, `to`, `at_end`, `detail`). Warning: a still hold of `--dead-air` seconds or more (default 2.5 s, the same rule as qa `frozen`, so check catches it before the render), or an end hold over 4 s. Fix: add motion (a slow push-in, drift, a progress element) or another beat, or shorten the scene with `showtime retime`. An overlay page for `--alpha` (`<body data-overlay>` or showtime.json `"overlay": true`) gets `overlay_gap` notes instead |
| `final_hold` | info | a still hold that runs to the end, up to 4 s: fine for an end card (qa has the same rule) |
| `timeline_gap` | warning | only with `--no-timeline`: a gap in the clip table (the dense pass that measures holes was skipped) |
| `blank_frames`, `first_frame_blank` | warning | black/white screens; a blank frame 0 is a bad thumbnail |
| `timers`, `css_transitions`, `animated_gif`, `config_conflict`, `clip_after_end` | warning | see [stage-api.md](stage-api.md) |
| `raster_noise`, `title_safe`, `small_text`, `heavy_effects`, `contrast_unmeasured`, `duration_inferred` | info | worth knowing, usually fine. Many `small_text` notes become one ("31 small labels, 19-23px (e.g. ...)"; report.json keeps `count` and `items`) |

Outputs `work/check/report.json` and `work/check/sheet.jpg` (the sample frames with timestamps;
look at it), and an estimate of the full render time (raised for `<video>` layers, which decode on
every seek, and when the machine is busy). A still hold uses qa's rule (`freeze_noise_db` in
`runtime/thresholds.json`): a few typed characters or a thin moving line do not count as motion.
After layout-only fixes, re-check with `--no-timeline` (about half the time); run the full check
again after timing changes. report.json also lists `scenes`
(`name`, `id`, `start`, `end` of the top-level clips) and `transitions` (`type`, `start`, `dur`,
`from`, `to`); review-pack uses them for per-scene frames. The hold thresholds live in
`runtime/thresholds.json`, shared by check, retime and qa. Exit code 1 on errors (`--strict`: also on
warnings). Useful flags: `--samples N` (default 9 + the last frame), `--at 3.2,7.9`,
`--no-timeline` (skip the dense pass: faster), `--no-determinism`, `--dead-air S` (default 2.5).

How the determinism probe works: four frames are captured, re-captured after 150 ms of real time,
and captured again after being reached in another order through the two previous frames (the way
a render worker reaches them). Differences that only touch antialiased edges are reported as
`raster_noise` (info); differences with solid changed areas are errors.

## `showtime snap <project | video>`

`--at 1,2.5` writes `work/snap/t0001.000s.png` ... (full size; `--width 960` to shrink,
`--format jpg`). Each time snaps to the nearest frame; files keep the time you asked for, and the
frame shown is printed when it differs (two times on one frame are both written and noted). Without
`--at` it makes `work/snap/sheet.jpg` from 12 evenly spaced frames plus the last one (`--count N`,
`--every 1s`, `--cols`, `--thumb`). Project stills are pixel-identical to the render. Another page
(`--page square.html`) or size (`--size 9:16`) writes to `work/snap-<page>[-<WxH>]/` (check likewise
to `work/check-...`), so runs never overwrite each other. One still as a named file (a frame from a
clip for the page): `showtime snap clip.mp4 --at 7.5 --width 1920 -o media/map.jpg` (`--width` also
upscales, with a note).

A rendered video works too (a footage edit, the shipped final, an export), decoded with showtime's
own ffmpeg: `showtime snap <job>/final-3.mp4 --at 12.9,13.0` (output `<job>/work/snap/<name>/`).
Before/after proof for a fix: `showtime snap final-3.mp4 --at 4.2,9.5 --compare final-2.mp4` writes
`compare.jpg` with the old frame left and the new one right (`--compare` also takes a project).

## `showtime preview <project>`

Serves the project on `http://127.0.0.1:4800` (next free port) and opens the player in a Chrome
or Edge app window (`--browser default` for the system browser, `--no-open` to only print the URL).
From a terminal it runs until Ctrl+C; when started by an agent (output not a terminal) it goes to
the background and the command returns: `--status`, `--stop`. Keys and audio: see
[stage-api.md](stage-api.md#preview-mode). The `audio` mix is built into `work/mix.wav` first and
rebuilt when showtime.json or audio files change.

`showtime server <project> [--port N] [--watch] [--json]` serves a project without the player
(same mounts: `/_st/`, `/_lib/<package>/`, `/_assets/`; byte ranges; local connections only). Its
page URL redirects to the preview player, so it is not a way to capture a static site: use
`showtime site capture --serve <dir>` (`capture.md`); on a folder without `showtime.json` it says so
and prints that command.

## `showtime retime <project> -d <seconds>`

Changes a project's length and moves the whole timeline with it; `showtime new ... --duration N`
runs the same step. Scenes are the top-level clips (`data-start`/`data-dur` not inside another
clip). Longer: each scene is stretched by new/old and everything inside a scene (component
`data-at`, sound effects, voice lines, caption words, the poster) keeps its offset from the scene
start, so animations keep their speed and scenes hold longer. Shorter: everything scales, including
times inside scenes. `audio/mix.json` music sections follow the scene starts (a bed that ran to the
end still does); canvas projects scale every number in the `var CUE = {...}` table (except `cps`)
and adjust `bpm` so cues stay on bar lines. Files are edited in place: `--dry-run` (`-n`) prints the
changes first, `--json` the report. A library or user music file that is too short gets a note:
add `"fit": true` to its track. Never retime one scene by hand and leave the rest.

A scene stretched more than 1.5x gets a warning: it now holds still after its last animation (check
flags holds of 2.5 s or more), so give it another beat or motion; canvas cue tables warn too, since
everything runs slower. Retimed transitions never shrink below 0.35 s.

`--from-voice <timeline.json>` (from `showtime voice script`; the `voice/` folder works too) sets
the scene lengths from the narration instead of one length for all:

- Lines are matched to scenes by id (the line `## demo` narrates `<section id="demo">`), else in
  order, else by `--map hook=open,demo=bars` (or a JSON file `{"line": "scene"}`); lines left out
  of the map join the scene of the line before them.
- Each narrated scene lasts `--pad` (default 0.3 s of picture before its first line) plus the slots
  of its lines (a slot runs to the next line's start, so it includes the pause). Scenes after the
  narration (an end card) keep their length; a scene with no line between narrated scenes is an error.
  `--total 30` keeps the video 30 s long: the end card after the narration grows or shrinks to
  absorb the difference (a warning under 2.5 s, an error under 1 s), so you never hand-edit its
  `data-dur`. The report counts only values that really changed.
- Every line becomes its own voice track in `audio/mix.json` (`vo-<id>`, file
  `voice/lines/NN-id.wav`) at scene start + pad; music without ducking gets `"duck": {"under":
  "voice"}`; music sections, sound effects and the poster move with their scenes. A project without
  a mix gets `audio/mix.json`.
- It writes `voice/captions.words.json` (word times in the video) and points top-level caption
  layers at it with `data-at="0"` (`--keep-captions` leaves them alone).
- DOM projects only: canvas films keep their times in the cue table (copy the slot starts there).
- Re-running with the same timeline changes nothing; `--dry-run` shows the plan.

## Speed

Measured on a 6-core Intel i5-8500 (2018) with Chrome 154 and a Radeon Pro 570X, while other jobs
were running:

| Workload | Result |
|---|---|
| 15 s, 1920x1080, 30 fps DOM/CSS launch template, 3 workers, final | capture 28.6 fps, encode 9.7 s, 28 s total |
| same, `--preview` (1280x720 output) | capture 28.9 fps, encode 2.3 s, 20.5 s total |
| same, 1 worker | 19 fps (jpeg), 12 fps (png) |
| 4 s 1280x720 template / canvas + offline score, 2 workers | 30-40 fps / 26-35 fps capture; A/V offset 0.02 ms |

Rules of thumb:

- A final render takes about 1-2x the video length at 1080p on a mid-range laptop. `showtime check`
  prints an estimate for the current project.
- Keep JPEG capture (default). PNG is only needed for `--alpha` (automatic) or pixel diffs.
- 2-3 workers is the sweet spot on 4-8 cores; more workers fight over the CPU and the GPU.
- `--preview` saves encode time and file size, not capture time: Chrome still draws each frame at
  full size. For a fast first look use `showtime snap` (seconds) and `showtime preview` (real time).
- What is slow to draw: `backdrop-filter`, large `filter: blur()` (above ~20px), many large
  `box-shadow`s or masks, full-screen gradients with blur on top, thousands of DOM nodes, heavy
  WebGL shaders. `check` flags pages with many heavy effects. Blur a small layer and scale it up
  instead of blurring a full-screen one.
- Animate `transform` and `opacity`; they are cheap and smooth. Animating layout properties
  (`width`, `top`, `font-size`...) forces layout every frame and moves in whole pixels.
- Fonts: load them from `/_lib/@fontsource/<family>/...` or `/_lib/@fontsource-variable/<family>/...`
  (installed by setup), or from `@font-face` files in the project. Never rely on system fonts or
  web font URLs; `check` shows which fonts actually painted the text.
- Long videos: renders keep one browser per worker for the whole range; for videos longer than
  ~10 minutes, render in sections with `--from/--to` and join them with the editing tools.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `no Chrome, Edge or Chromium found` | install Google Chrome, or `showtime setup --with chromium` |
| `no working ffmpeg found` | `showtime setup` (installs a static ffmpeg into `~/.showtime/bin`) |
| `the page never became ready (still waiting for: ...)` | a `ST.waitFor` promise never settles, or a script failed first: `showtime check` |
| `seek to ...s timed out` | an async `onSeek` never resolves, or a `<video>` cannot seek (use VP9) |
| frames differ from the preview | `showtime check`: look for `timers`, `css_transitions`, `nondeterministic` |
| video element is black in renders but plays in your browser | the render browser cannot decode H.264: convert the clip to VP9/WebM |
| text looks different on another OS | `font_not_embedded` in `check`: load the font as a file |
| a render with several workers is not bit-identical to a single-worker render | Chrome keeps some antialiasing state from earlier frames (e.g. after a blur); differences are invisible (>40 dB PSNR). Use `--workers 1` when you need bit-exact frames |
| browser crashes with several workers on a small machine | `--workers 1`, or `--gpu off` |
| audio is quieter than -14 LUFS with a warning | the mix has very sharp peaks; compress/limit it in the mix, or accept the level |
| Linux: Chrome fails to start in a container | install Chrome's system libraries (`sudo npx playwright install-deps chromium`) |

## Platforms

Works the same on macOS (Apple Silicon and Intel), Windows 10/11 and Linux: the scripts are Node,
all processes are started with argument lists, paths go through `path`/`pathlib`, and ffmpeg is
always the one resolved by showtime (`$SHOWTIME_FFMPEG`, then `~/.showtime/bin/ffmpeg(.exe)`,
then a working one on PATH). The browser is the system Chrome, then Edge, then Chromium, then the
Chromium installed by `showtime setup --with chromium`; override with `SHOWTIME_CHROME=/path`.
GPU drawing uses Metal on macOS, Direct3D 11 on Windows and the default GL (SwiftShader
fallback) on Linux; if the GPU path fails to start, rendering retries in software. Pixels can
differ slightly between machines and GPUs (antialiasing), never in timing or layout.

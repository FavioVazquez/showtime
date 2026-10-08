# Rendering, checking and previewing a project

Read this when you are about to look at, check or render a showtime project; when a render is
slow, fails, or looks different from the preview; or when you need the exact flags and outputs of
`showtime render`, `check`, `snap`, `preview`, `server` and `retime`.

## Essentials

- Order: `showtime preview`, `showtime check`, `showtime look`, `showtime render <p> --preview`, then the
  final `showtime render <p>`; every command takes `--help` and `--json` (§ The loop)
- Run `showtime check <project>` before every final render: fix every error, read every warning. After
  layout-only fixes re-check with `--no-timeline`; after timing changes run the full check (§ showtime check)
- A full render is the expensive step: fix a job's video with `render <p> --from S --to S --job <job>`: the
  seconds are re-rendered and spliced into a copy of its last full render, a full-length `final-N.mp4`. Without
  that render (or after a size, fps or length change) it writes `<job>/work/span-S-S.mp4`, a clip, never the
  video (§ The loop, § showtime render)
- `showtime render <p>` writes a new job folder and never overwrites; `--job <job>` writes `<job>/final.mp4`
  (`final-2.mp4` on a re-render) so `showtime qa <job>` checks it; not with `-o` (§ showtime render)
- Defaults: CRF 16 / `veryfast`, JPEG capture, workers by machine (3 with a GPU; without one, one per 8 CPU
  threads, 3-8), -14 LUFS / -1 dBTP; `--preview` is a 720p draft, `--preview --fps 12` the fastest first look.
  Keep CRF 16 for anything a platform re-encodes; encode settings you ship go in showtime.json
  `"render": {...}` (flags still win); `"x264_preset": "medium"` is the encode before 0.4.1 (§ showtime render)
- Poster: best default is a hook complete at t=0 with `"poster": 0`; a poster unlike the opening is not baked
  into frame 0 (`poster_not_baked`) unless `"render": {"poster_bake": "force"}` (§ showtime render)
- `dead_air`: 1.5 s with no clip showing is an error; a still hold of 2.5 s or more, or an end hold over 4 s,
  is a warning: add motion or another beat, or shorten with `showtime retime` (§ showtime check)
- Check enforces text rules: contrast 4.5:1 (3:1 for text >= 24px); vertical safe box x 64-916, y 220-1440
  at 1080x1920; landscape: 5% from the edges, no text under 32 px in the bottom 8% (§ showtime check)
- Change the length only with `showtime retime <p> -d N` (`--dry-run` first); never retime one scene by hand.
  `--from-voice voice/timeline.json` sets scene lengths from the narration; `--total N` keeps the video length
  (§ showtime retime)
- `showtime preview` started by an agent goes to the background (`--status`, `--stop`); give the user the
  printed link as is, ending in `k=...` (§ showtime preview)
- Speed: a final takes about 1-2x the video length at 1080p; keep JPEG and the automatic workers; animate `transform`
  and `opacity`; avoid `backdrop-filter` and full-screen `filter: blur()` above ~20px. Fonts only as files
  (`/_lib/@fontsource/...` or `@font-face`), never system fonts or web font URLs (§ Speed)
- A length, size or deadline that cannot be met (a long 4K film "in a few minutes") gets a plain no in
  the first line, the arithmetic and an honest estimate, then what can be done: a preview first, 1080p or
  30 fps, a shorter cut, the full render in the background. Never lower the spec quietly (§ Speed)
- After a failed or odd render read `render.log` first; no browser or ffmpeg: `showtime setup`; a `<video>`
  black in renders: convert the clip to VP9/WebM (§ showtime render, § Troubleshooting)
- Over 20 MB: `showtime deliver exports <file> --targets original --max-mb 20`; animated film grain
  (`grainFps` above 0) is the usual cause of a huge final (§ showtime render)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| The loop | 58-94 |
| showtime render <project> | 96-227 |
| showtime check <project> | 229-288 |
| showtime snap <project / video> | 290-311 |
| showtime preview <project> | 313-330 |
| showtime retime <project> -d <seconds> | 332-381 |
| Speed | 383-452 |
| Troubleshooting | 454-468 |
| Platforms | 470-485 |

## The loop

```
showtime new dom my-video -d 20     # or launch / film / short / data / tutorial; the whole timeline fits 20 s
showtime preview my-video            # player with scrubber and audio; reloads on save
showtime check my-video              # QA gate: fix every error, read every warning
showtime look my-video               # one small composite of the key frames (references/looking.md)
showtime snap my-video               # contact sheet or --at 2.5,7 for stills (full size: for reviewers)
showtime render my-video --preview   # quick 720p draft
showtime render my-video --preview --fps 12   # fastest first look: layout and story, not motion
showtime render my-video             # final: showtime-out/<title>-<timestamp>/final.mp4
showtime render my-video --job <job> # final into a job: <job>/final.mp4 (final-2.mp4 on a re-render)
showtime retime my-video -d 30       # change the length later: scenes, poster, mix and cues move together
showtime retime my-video --from-voice my-video/voice/timeline.json   # scene lengths from the narration
```

Every command has `--help` with examples, prints the paths it wrote, and takes `--json` for a
machine-readable result. Errors end with a `fix:` line; add `--debug` for a stack trace. Without a
terminal (agents, the MCP server) output is brief: verdict, findings to act on with fixes, paths; the
full report goes to a file (`check`: `work/check/report.txt`) and `--verbose` prints it.

A full render is the expensive step: `render` warns when the project changed after the last
`showtime check` (or was never checked), and after a second full render in the same place it suggests
proving the next fix with `--from S --to S` first.

A fix after the first full render: `showtime render <p> --from 12 --to 18 --job <job>`. When the job's latest
final comes from `showtime render` of this project at the same size, frame rate and length, only those seconds,
widened to the keyframes around them (at most 2 s each side), are captured and encoded with the same settings
(the old render's x264 preset and CRF unless you pass others); they replace exactly those frames in a copy of
that render, whose other frames stay byte for byte. The result is the job's next full final (`final-2.mp4`, same
length, the mix of the whole video: reused when its inputs did not change, else mixed and mastered again;
poster as in a full render), recorded as `spliced: 12-18 from final.mp4` and counted by the receipt as a partial
render. When the old render was encoded with other settings or another ffmpeg, the whole video is encoded once
instead (old frames decoded, new ones from the capture). With no such render, after a size, fps or length
change, with `--preview`, `--alpha` or `--size`, or without `--job`, the result is a span clip:
`<job>/work/span-12-18.mp4` (without a job, `span-12-18.mp4` in a new folder). It is only those seconds: look at
it (`showtime look <file>`), never deliver it; `qa <job>`, `look <job>` and the ledger skip span clips.

## `showtime render <project>`

A project is a folder with `showtime.json` and `index.html` (or pass an `.html` file / `--page`).

| Option | Default | Notes |
|---|---|---|
| `-o FILE` | new job folder | never overwrites: an existing name gets `-2`, `-3`...; inside a job folder the file is recorded as the job's latest final (or draft) |
| `--job JOB`, `-j` | none | a job folder or name: writes `<job>/final.mp4` (`final-2.mp4`... on a re-render, `preview.mp4` with `--preview`) and records it in job.json `outputs`, so `showtime qa <job>` checks it. Not with `-o` |
| `--out-dir DIR` | `$SHOWTIME_OUT` or the current folder | job folder is `DIR/showtime-out/<title>-<timestamp>/` |
| `--preview`, `-p` | off | a draft: at most 720p, x264 veryfast CRF 23, AAC 128k, no poster bake; the file is named `preview.mp4` |
| `--from S --to S` | whole video | re-render one section: with `--job` and a full render there, spliced into a copy of it (a full `final-N.mp4`); otherwise a span clip `span-S-S.mp4` (audio cut to match, no poster), never a final (§ The loop) |
| `--fps N` | showtime.json | `--preview --fps 12` is the fastest first look (40 % of the frames): judge layout and story with it, not motion |
| `--workers N`, `-w` | auto | separate browsers. Auto: 3 with a GPU; without one (SwiftShader, llvmpipe, WARP), one per 8 CPU threads, at least 3 and at most 8; never more than CPU threads - 2, one per 45 frames, one per 3 GB of memory (in a container, of its memory limit), or `SHOWTIME_MAX_WORKERS`. The render log and render.json `workers_why` say what was picked and why |
| `--scale X` | 1 | `0.5` = half size, `2` = supersampled (sharper text, 4x the pixels) |
| `--alpha prores\|animation\|webm` | off | transparent background (the themes' scene and stage fills turn transparent; a background a scene sets itself still paints; mark an overlay page `<body data-overlay>` so `check` does not call its gaps dead air): ProRes 4444 `.mov` (editors; large: a 1 s full-frame 1080p stinger is about 30 MB), QuickTime Animation `.mov` (editors; lossless RGBA, a fraction of that for flat graphics such as lower thirds and stingers, larger than ProRes for photos and gradients) or VP9 `.webm` (web) |
| `--format jpeg\|png` | jpeg (q92) | png is lossless and ~1.5x slower to capture |
| `--crf N`, `--x264-preset P` | 16 / veryfast (preview 23 / veryfast) | `medium` (the default before 0.4.1) takes 2-3x longer to encode for the same size and look (SSIM within 0.0004 on the templates); `"render": {"x264_preset": "medium"}` keeps it. Lower CRF = better and bigger. For masters kept in a repo or an example folder, `"render": {"crf": 18}` in showtime.json: about 20-25 % smaller with no visible loss on flat graphics (a 35 s code video: 22.6 MB at 16, 17.9 MB at 18). Keep 16 (or 14-16 with grain) for anything a platform re-encodes |
| `--poster S` / `--poster none` | showtime.json `poster` | the frame at S becomes poster.jpg (and frame 0, see `--poster-bake`) |
| `--poster-bake auto\|force\|off` | auto | auto bakes the poster into frame 0 only when it looks like the opening frame (else frame 0 would flash on autoplay and loops) |
| `--lufs N`, `--no-loudnorm`, `--no-audio` | -14 LUFS, -1 dBTP | |
| `--allow-silent` | off | a project with audio (ST.score or an `audio` mix) fails when its audio fails twice; this ships it silent instead |
| `--gpu off` | auto | software rendering: slower, most reproducible across machines |
| `--settle raf1\|raf2\|none` | raf1 | paint wait after each seek (raf2 is extra safe; none can miss paints). A canvas or WebGL scene blank on the first frame after a cut is not a paint wait: raf2 does not change it; see `late_first_frame` in `check` |
| `--keep-frames` | off | keep the captured frames (`frames/` in the work folder), also after a failed or interrupted render |
| `--keep-work` | off | keep the whole work folder: the silent `video.mp4` (about the size of the final) and the WAV stems too |
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
   blocked) and waits for `ST.ready()`. The workers' browsers start while the first one loads the page.
2. Frames are split into contiguous ranges, one per worker. Each worker first replays (without
   capturing) the second before its range, then seeks every frame in order and captures it with the
   Chrome DevTools screenshot call. A worker that is
   done takes the back half of the largest range left (after its own one-second replay), so no
   worker runs alone at the end; a worker whose page does not open in 5 minutes (scaled, see below) gets a new browser,
   and its frames go to the others meanwhile. Missing or empty frames are captured again; a crashed
   browser is restarted up to twice, with a screenshot, the DOM and the console saved to
   `work/diagnostics/`.
3. One encode, running during the capture: the frames go to disk as before and one ffmpeg reads
   them in order as soon as each one and all before it are there, so the file is the same, byte
   for byte, as an encode started after the capture (`SHOWTIME_PIPE_ENCODE=0` does that). With a GPU,
  a frame where one worker handed frames to another can differ from a single-worker render by
  antialiasing noise (a few levels on a few hundred pixels); two renders of a project can therefore
  differ at those joins, which fall where the timing puts them. H.264 High,
   yuv420p, BT.709 matrix with accurate rounding, BT.709/tv tags, no B-frames (first frame never
   freezes in picky players), keyframe every 2 s, `+faststart`. A splice encodes its segments after
   the capture.
4. Audio, prepared while frames are captured: `ST.score` rendered offline in its own page, plus
   the showtime.json `audio` (a mix spec goes to `showtime audio mix`; if that module is missing,
   a built-in mixer handles file tracks with start/offset/gain/fades/loop). The mix is made to be heard
   on a phone speaker: a 40 Hz high-pass on everything but the voice and, on a bass-heavy bed, a low
   shelf before the loudness normalisation (`audio.md` § Heard on a phone). `"master": {"speaker_safe":
   false}` in showtime.json or the mix turns it off, for a video meant for headphones. Everything is cut to
   the rendered range, padded/trimmed to the exact video length, brought to the loudness target
   (plain gain when the peaks allow it, else gain into an oversampled limiter with at most 6 dB of
   limiting and a warning if the target is out of reach), encoded as AAC 256k in `.m4a` (keeps the
   encoder delay, so sync is exact), checked for true peak, and muxed without re-encoding video.
   The result is kept in `~/.showtime/cache/render-audio/` (the newest 12, at most 1 GB) by a hash of
   everything it is made from: the mix spec and every file it names with the sidecars beside it
   (`.license.json`, beats, words, hit point), the project's non-picture files (showtime.json, voice
   takes and their timings, music, sounds, question cues; not the page's HTML, JS, CSS, images, fonts or
   videos the mix does not name), the music vetoes and look history when a track is a catalog query,
   the score's samples, the range, the loudness settings, the ffmpeg binary, the library and catalog
   settings, and the audio code. A render whose mix inputs did not change (a picture fix, a
   `--from/--to` splice) reuses it and says so; `SHOWTIME_AUDIO_CACHE=0` mixes it again every time.
5. Poster: with a `poster` time, that frame is saved as `poster.jpg` and copied over frame 0
   before the single encode (feeds and chat apps show frame 0), but only when it looks like the
   opening frame (`--poster-bake auto`). A poster over an opening that builds from empty would show
   as a one-frame flash on autoplay and on every loop, so it is not baked and the summary says why.
   The best default is a hook that is complete at t=0 with `"poster": 0`; for YouTube and other
   platforms that take a custom thumbnail, upload `poster.jpg` instead. Without a poster time,
   `showtime deliver poster` picks a sharp, representative frame for `poster.jpg` (not baked).
   qa WARNs `poster_flash` when frame 0 differs sharply from frame 1.
6. The result is probed (frame count, duration) and a report is written.

Waits are scaled to the page. Each wait (the page load, fonts, images, videos, `ST.waitFor` gates, every
seek, the page becoming ready, a worker's page opening) has a fixed value that suits a normal machine (60 s
for fonts and gates, 60 s per seek). The page measures its own cost while it gets ready: the gaps between its
frames and the time its first seeks take. A slow machine without a GPU, a busy runner or a heavy page then
gets each wait times a factor of up to 5; a fast machine keeps the fixed values, never less. render.json
`pace` records the factor and what was measured (`frame_ms`, `seek_ms`), render.log says so when it is above
1, and `showtime check` reports the same in its report (`pace`). `SHOWTIME_PACE=0` keeps the fixed waits.

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
    audio/           master.m4a (the soundtrack as muxed), mix.json and mix.report.json (review-pack
                     and qa read the report), mix.voice.wav (the narration alone, 16 kHz: what
                     `showtime transcribe` reads for this video)
    diagnostics/     screenshot, DOM and console of a frame that failed (only after a retry or a failure)
    with --keep-work also: video.mp4 (no audio), audio/{score,mix,combined,master}.wav
    with --keep-frames also: frames/
```

A finished render removes its frames, the silent video copy and the WAV stems (together several
times the size of the final); a failed or interrupted one (Ctrl-C, a host's SIGTERM) removes its
frames and keeps its log and diagnostics. `showtime clean <job>` removes what renders from before
0.4.0 left behind (`<stem>.work/video.mp4`, the WAV stems); `showtime clean <job> --frames` removes only
the frame dumps, `--all` also the review packs and logs (the person's notes in `review/notes/` stay).

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
| `request_failed` | warning | a local request failed (not a 404). A load cancelled while it ran (an image whose `src` changed again before it arrived, as when check's seeks swap pictures) is not a failure: report.json `cancelled_loads` counts those |
| `unstable_frame` | error | pixels keep changing after a seek finished: something runs on real time |
| `nondeterministic` | error | a frame differs when reached in another order (state kept between frames) |
| `late_first_frame` | error | the first frame after a hard cut is drawn a frame late: the page draws a scene (a canvas, WebGL) from its own copy of the scene times, so the render shows that frame blank or stale while `snap` looks right. Check walks every cut on a fresh page in order, as a render does. Gate drawing on `ST.clips()` (frame-exact windows) |
| `clip_timing`, `video` | error | bad `data-start`/`data-dur`, or a video that cannot be decoded/seeked |
| `font_load_failed` | error | an `@font-face` file failed |
| `low_contrast` | error (warning under 1 % of the height) | WCAG contrast of text against the real pixels behind it: 4.5:1 for every size. Judged at the settled frame: a text a sample caught mid-fade, blurred or mid-entrance is measured again at the frame of its visible window where it is most opaque, and only fails when it is low there (the message gives that time and where it was first sampled). A text seen only mid-transition gets an info note naming the transition. Large text (>= 4 % of the height) in the colours of the job's style reference (`reference-style.css`) at 3:1 or more is a note: the user asked for that look. |
| `caption_zone` | warning | with caption-karaoke captions: a visible element (text, image, SVG shape, a box with a fill) drawn where the caption cards sit while a caption shows. Names the element, the time and the overlap in px. Ignores full-frame backgrounds, full-width bands without text and anything under 10 % opacity; mark an intended overlap `data-st-caption-ok` |
| `webgpu` | error / warning | the page asks for WebGPU (`navigator.gpu`, a `webgpu` canvas); the message names the file and line. Check loads the page again with WebGPU gone, as on a machine without a GPU (showtime never needs one): error when no WebGL or 2D canvas of the page draws in its place (the render would be a flat ground), warning when one does (frames differ with and without a GPU). Fix: WebGL or 2D, e.g. showtime's shader layer (`shaderLayer`, motion-craft.md) |
| `font_not_embedded` | warning | text is painted with a system font (differs between Mac, Windows and Linux) |
| `text_off_canvas`, `text_clipped` | error | readable text runs off the frame or is cut by a container at a sample time (decor: info) |
| `text_overlap` | warning | layout problems at the sample times; overlaps are measured on the painted glyphs (not line boxes, so big display type with tall leading is not a false alarm) and say how deep they are; `text_overlap` also covers text hidden under a badge, callout or pill ("X is hidden under Y"), in canvas films too (an `F.callout` card over readable text drawn before it). Found only mid-transition, they are info notes naming the transition ("mid-transition: push into #demo; the settled frame at 0:04.43 is judged on its own"): check samples the settled frame 2 frames after every transition too |
| `labels_crowded` | warning | SVG labels (chart values and axes, map names) whose painted glyphs touch or sit closer than 0.15em side by side or stacked (`label_gap_em` in `runtime/thresholds.json`); one finding per graphic naming the worst pair. While a chart is still growing or morphing it is an info note. Fix: fewer bars, the default `valueLabels` (auto-thinning), a larger plot, or a line chart |
| `chart_labels_hidden` | warning | the project's CSS hides chart labels while the chart moves (`[data-st-moving] .st-chart-val { opacity: 0 }`): every number blinks off when an item is added and back when it settles. Fix: delete the rule; labels ride their marks through a morph, an added item fades its label in, `count: false` shows real values only |
| `slow_scene` | warning | a scene holds on past its last change (a component or CSS animation ending) and past the reading time of its text by more than 2.5 s (4 s for the last scene, an end card): a slow push keeps it from counting as a still hold, but it plays slow. Fix: a beat about every 2 s (a chart state, a callout or reference line arriving, a highlight, a count-up, the next line), or shorten the scene. `report.pacing` lists them |
| `blur_text`, `blur_slow`, `blur_container`, `blur_unsampled`, `blur_inline` | warning | shutter blur (`data-st-blur`, `F.motionBlur`; stage-api.md § Shutter blur), measured on every frame the element is on screen from its own motion: text the viewer reads is blurred (over 0.4 s in one run, on every frame it shows, or with a threshold under 6 px a frame, so it blurs while it moves slowly); the motion is too slow to need it (at its fastest frame under a quarter of its shorter side a frame, or never fast enough to blur); a scene, a container (more than 60 elements, a canvas or video inside, or a film draw that returns a point instead of a box) or a layer over half the frame; it moves from an `ST.onSeek` handler or a moving ancestor, which the blur cannot pose between frames (its copies never show); an inline box, which CSS never transforms. Numbers in `runtime/thresholds.json` "blur"; report.json `blur` lists each element's peak motion, size and blurred frames |
| `same_frame_entrance` | warning | 3 or more sibling items whose CSS entrance (from opacity 0) starts on the same frame: nothing leads, they land as one block. The message names the frame; fix: stagger them 2-4 frames apart in reading order (`animation-delay: calc(var(--i) * 0.1s)`) |
| `callout_off_target` | warning | canvas film: an `F.callout` card is on screen but its anchor is off the frame (the camera moved away from what it points at), or the card itself runs off the frame |
| `safe_zone` | warning | vertical video: text outside the box that feed UIs leave free (x 64-916, y 220-1440 at 1080x1920); the message names the edge ("top at y 185 < 220") |
| `edge_margin` | warning | landscape: text fully in frame but within 3% of an edge (player controls, overscan); keep 5% (96 px at 1920) |
| `control_strip` | warning | landscape: text under 32 px (at 1080p) in the bottom 8%, where a player's progress bar and controls sit |
| `short_text` | warning | text on screen for less than it takes to read (0.3 s + the longer of characters/17 and words/3, per language, min 1 s; part of the phone check, see qa.md); mark text read along with the voice `data-caption` |
| `beat_words` | note | three or more 1-2 word texts shown one after another, each 0.35-1.2 s (a word per beat): read as one line at no more than words/3 per second, so not `short_text` |
| `flash_text` | note | showreel tone only: flash words (`data-st-flash`, 1-3 words, 24 characters at most, on screen 0.2 s or more) that leave before their reading time on purpose, so not `short_text` (`tones.md`, showreel) |
| `no_hero_line` | warning | showreel tone: every text is a flash word, so no line (the name, the one message) is held its reading time; part of the phone check |
| `tiny_text` | warning | readable text under the phone minimum: points at 390 pt wide (16:9 5 pt, 1:1 10, 4:5 11, 9:16 15) and at least 2.2 % of the frame height; part of the phone check, `report.phone` has the sizes. UI-mockup detail marked `data-st-decor` is exempt; many small texts become one warning that lists them |
| `poster_not_baked` | info | showtime.json `poster` is set, but the frame differs from the opening, so `render` (`--poster-bake auto`) will not bake it into frame 0 (it would flash on autoplay and loops); poster.jpg is still written. Start the video in the poster's state, or `"render": {"poster_bake": "force"}` |
| `dead_air` | error / warning | error: for 1.5 s or more no clip is showing (a gap between scenes, or scenes that end before the video does; canvas: only the flat backdrop is drawn), listed in report.json `timeline_holes` (`from`, `to`, `at_end`, `detail`). Warning: a still hold of `--dead-air` seconds or more (default 2.5 s, the same rule as qa `frozen`, so check catches it before the render), or an end hold over 4 s. Fix: add motion (a slow push-in, drift, a progress element) or another beat, or shorten the scene with `showtime retime`. An overlay page for `--alpha` (`<body data-overlay>` or showtime.json `"overlay": true`) gets `overlay_gap` notes instead |
| `final_hold` | info | a still hold that runs to the end, up to 4 s: fine for an end card (qa has the same rule) |
| `look_repeat` | warning / info | the look repeats one of your last five videos (theme, palette, type pair, transitions, camera, music, structure; template or tone alone: info), with two alternatives per repeat; a repeat that follows the job's style reference is info (intended); `--no-history` skips it ([reference.md](reference.md)) |
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

`showtime look <project | video | job>` is the lean way to see a video: one composite (1280 px,
`--width`) of the opening frame, each scene's settled frame from a current check report (else evenly
spaced frames, `--count`), and the last frame; `--at` picks times (16 at most). It numbers looks per job
(`<job>/work/look/look-N.jpg`), writes `look-N.md` (a brief a reviewer sub-agent follows) and
`verdicts.md`, and warns past 12 looks; `--stills` adds full-size frames. Protocol: `references/looking.md`.

A rendered video works too (a footage edit, the shipped final, an export), decoded with showtime's
own ffmpeg: `showtime snap <job>/final-3.mp4 --at 12.9,13.0` (output `<job>/work/snap/<name>/`).
Before/after proof for a fix: `showtime snap final-3.mp4 --at 4.2,9.5 --compare final-2.mp4` writes
`compare.jpg` with the old frame left and the new one right (`--compare` also takes a project).

## `showtime preview <project>`

Serves the project on `http://127.0.0.1:4800` (next free port) and opens the player in a Chrome
or Edge app window (`--browser default` for the system browser, `--no-open` to only print the URL).
From a terminal it runs until Ctrl+C; when started by an agent (output not a terminal) it goes to
the background and the command returns: `--status`, `--stop`. The server answers only on
127.0.0.1 and only with its per-session key: give the user the printed link as is (it ends in
`k=...`); a request without the key gets a 403 that says so, and `--status` prints the link again.
Keyboard and audio: see
[stage-api.md](stage-api.md#preview-mode). The `audio` mix is built into `work/mix.wav` first and
rebuilt when showtime.json or audio files change.

`showtime server <project> [--port N] [--watch] [--json]` serves a project without the player
(same mounts: `/_st/`, `/_lib/<package>/`, `/_assets/`; byte ranges; local connections only; the
printed links carry the session key, `--json` gives `key` for the `X-Showtime-Key` header). Its
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
  of its lines (a slot runs to the next line's start, so it includes the pause). The first line keeps
  its lead-in: pinned 2.4 s into the voice (`at: 2.4` or `lead_in: 2.4`, a music-only opening), it starts
  at 2.4 s in the video and its scene grows by that much picture before it (never less than `--pad`).
  Scenes after the narration (an end card) keep their length; a scene with no line between narrated
  scenes is an error unless it is marked `data-silent` (no line on purpose: a pause, a question beat).
  `--total 30` keeps the video 30 s long: the end card after the narration grows or shrinks to
  absorb the difference (a warning under 2.5 s, an error under 1 s), so you never hand-edit its
  `data-dur`. When every scene is narrated (a narrated close), the last scene's hold after its last
  line absorbs it instead; a `--total` that would cut into that line is an error that names the
  shortest length that works. The report counts only values that really changed.
- Pins win over `data-silent` scenes. A silent scene keeps its length and moves the lines after it
  later by that much, unless the next line is pinned (`{at=...}`) and the voice starts it on its
  pin: then the voice already holds the silence, so the silent scene fills the gap from the end of
  the line before it (plus its pause) to the pin, and the narrated scene before it keeps whatever is
  left. A gap a little shorter than the silent scene wants shrinks it, with a note that says how
  much later to pin the line. The silent scene keeps its length (with a note saying why) when the
  voice ran past the pin (the line before it is too long), when it would drop under 1 s, and when the
  pin comes from a 0.4.0 narration.md that left the silent shots out (regenerate it).
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

0.4.0 against 0.4.1 on the same machine (2026-10-07, 1080p30, automatic settings, best of 2 interleaved runs).
Other jobs kept it very busy (load average 50-280 on 6 cores), so every number spreads widely; the encode and
fix rows moved the most:

| Workload (showreel 15 s / DOM page 15 s / launch film 30 s) | 0.4.0 | 0.4.1 |
|---|---|---|
| encode left after the capture | 21.8 / 25.1 / 56.6 s | 5.1 / 9.3 / 13.7 s |
| whole render | 56.6 / 53.7 / 115.0 s | 56.1 / 58.9 / 80.5 s |
| a 1 s fix spliced into the job's video | 54.4 / 30.9 / 31.9 s | 12.6 / 18.2 / 20.5 s |
| file size; SSIM against the 0.4.0 file | 15.5 / 15.2 / 31.8 MB | 15.7 / 14.9 / 31.1 MB; 0.9976 / 0.9963 / 0.9978 |

A 5 s span of a finished 150 s explainer took 56.6 s the first time and 22.4 s the next (mix reused).
The showreel and launch frames were byte for byte the same as 0.4.0's; the DOM page differed by GPU
antialiasing noise in 12 of 450 frames (at most 7 levels on a few hundred pixels), as two 0.4.0 runs of it do.

Rules of thumb:

- A final render takes about 1-2x the video length at 1080p on a mid-range laptop. `showtime check`
  prints an estimate for the current project.
- Scale it before promising a time: 4K draws four times the pixels of 1080p and 60 fps doubles the
  frames: about 8x the work, so 5 minutes of 4K at 60 fps (18,000 frames) takes roughly 40-80 minutes or
  more on a laptop, not minutes,
  and building the scenes comes first. Say so plainly and offer the faster paths (preview, 1080p/30 fps,
  a shorter cut, the full render in the background).
- Keep JPEG capture (default). PNG is only needed for `--alpha` (automatic) or pixel diffs.
- Keep the automatic worker count. With a GPU, 3 browsers were fastest on a 6-core machine (4 and 6
  were slower). Without one, every browser already spreads its drawing over the cores: on a 6-core
  machine 1 browser beat 3 for a WebGL showreel (by about 10 %) but a DOM page was about 50 % slower
  with 1 than with 3, and on a 64-core machine 4-16 were best, so the default is one per 8 CPU
  threads, at least 3 and at most 8. On a 4-8 core machine without a GPU, WebGL scenes stay slow (about 0.5 s per frame
  for a shader-heavy 1080p scene, measured): render them at half resolution.
- What 0.4.1 made faster, with the same frames (except GPU antialiasing noise at hand-over joins):
  x264 `veryfast` (2-3x faster encodes than `medium`
  at the same size and look; `"render": {"x264_preset": "medium"}` keeps the old one), the encode
  running during the capture, no worker left alone at the end, and the mix reused when its
  inputs did not change. A 1 s `--from/--to` fix no longer waits for the whole mix to be built
  again: it costs the start, the page load and the frames of the widened span.
- `--preview` saves encode time and file size, not capture time: Chrome still draws each frame at
  full size. `--preview --fps 12` captures 40 % of the frames: the fastest whole-video first look
  (layout, story, timing of cuts; not motion). For stills use `showtime snap` (seconds) and
  `showtime preview` (real time).
- The shutter blur (`data-st-blur`) costs only on the frames it draws (a snap: 4-7 frames). Measured on the
  build box (64 cores, no GPU: Chrome 154 rasterizing with SwiftShader, 1 worker, 1920x1080, 8 copies, median
  of 3 renders while other jobs ran, load 7-40): a frame took 7.9 ms more with one blurred 150 px word, 13.9
  ms with three and 26.7 ms with six (33-37 ms without); a card with a gradient and a shadow 10.7, 28.1 and
  48.7 ms more. About 3 ms of each element is script (posing, copying, comparing styles), the rest is drawing
  the copies. `samples` scales it; a whole-frame layer would cost a whole frame per copy (`blur_container`).
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
| `no Chrome, Edge or Chromium found` | `showtime setup` (installs the Chrome Headless Shell, ~100-120 MB), or install Google Chrome |
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
then a working one on PATH). The browser is the system Chrome, then Edge, then Chromium (version 120
or newer), then the Chrome Headless Shell that `showtime setup` installs when none is found (headless
runs), then a full Chromium (`showtime setup --with chromium`, fetched automatically for `--headed`
captures). Override with `SHOWTIME_CHROME=/path`; `SHOWTIME_SYSTEM_BROWSER=0` ignores installed
browsers. The headless shell draws the same frames as Chrome except the antialiasing of small text
edges (bit-identical on the dom, data and short templates; 37-45 dB PSNR, under 1% of pixels, on the
text-heavy film and tutorial templates, measured 2026-09-28); `SHOWTIME_HEADLESS_SHELL=0` renders with
full Chromium instead.
GPU drawing uses Metal on macOS, Direct3D 11 on Windows and the default GL (SwiftShader
fallback) on Linux; if the GPU path fails to start, rendering retries in software. Pixels can
differ slightly between machines and GPUs (antialiasing), never in timing or layout.

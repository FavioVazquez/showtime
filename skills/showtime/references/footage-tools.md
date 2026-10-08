# Footage tools

Read this when you need one specific tool for real footage outside (or inside) an EDL edit:
shot detection and contact sheets, face-tracked reframing, speech denoise, stabilisation, colour
correction and looks, timeline views, media facts. The editing workflow itself is in `editing.md`;
captions are in `captions.md`.

Every command has `--help` with examples and `--json` for machine-readable results, prints the
paths it wrote, and never overwrites an earlier output (a `-2` suffix is added). Default outputs never
go beside the user's media: `footage scenes` writes to `<job>/work/scenes/`, and `reframe`, `grade`
(and its `--compare` still), `denoise`, `stabilize`, `luts --preview` and `view <media>` to
`<job>/work/footage/`. The job is `--job` where offered, else the job the file or the current folder
is in, else the newest job; with no job at all, a fresh `showtime-out/<tool>-<time>/`. A source
already inside a job keeps its outputs beside it; `-o` picks any path. `transcribe` writes to
`<job>/edit/transcripts/` the same way (with no job it makes a `<name>-edit` job rather than writing
beside the footage); older `<media folder>/edit/transcripts/` files are still found by `edit cut`
and `footage view`. `--edit-dir` picks any folder, e.g. next to the footage when the user asks.

## Essentials

- Look first: `showtime footage probe <file>` and `showtime footage scenes <file>` (`--every 5` for a quick
  look); read the contact sheet before planning B-roll or cutaways (§ Inventory: probe and scenes)
- Excerpts and proxies: `showtime footage trim <file> --from 61 --to 142 -o ...`, `--width 1280` for a page
  proxy, `--webm --no-audio` for VP9; use it instead of a one-range EDL or bare ffmpeg (§ Trim and proxies)
- Raw interview recordings and live shots have fillers to cut; resource reels and press soundbites are already
  edited (§ Trim and proxies)
- Self-review: `showtime footage view <file> --from 12 --to 20`, and `showtime edit view edit/edl.json` around
  every cut (§ Timeline views)
- Reframe: `showtime footage reframe <file> --aspect 9:16` (face-tracked); screen recordings and slides use
  `--fit blur` (cropping cuts off UI); enlarging over 1.5x looks soft (§ Reframe)
- Cut out the speaker: `showtime footage cutout <file> --from 12 --to 18`: VP9 with alpha (or `--format prores`,
  `png`), a matte file, a sheet to look at; people only; on the CPU (§ Cut out the speaker)
- Denoise: `showtime footage denoise <file> -o ...` (`--strength` below 1 keeps room tone); never on clean
  studio audio; before loudness mastering; in an EDL `"audio": {"denoise": "auto"}` (§ Denoise speech)
- Stabilise: `showtime footage stabilize <file> --strength 0.7 -o ...`; no `--compare`: judge by watching, or
  compare framing with `showtime snap ... --compare` (§ Stabilise)
- Colour: correct first (`--auto`), then a look at 40-70 % (`--look teal-orange --strength 0.5`); `--analyze`
  for stats, `--compare --at 4` for before/after. Grade real footage only, never UI captures or motion
  graphics (§ Colour: correction and looks)
- Heavy steps (transcription, renders) use all cores: run them one after another, not in parallel with browser
  captures; `showtime doctor` lists what your ffmpeg has (§ Platform notes)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inventory: probe and scenes | 57-74 |
| Trim and proxies | 76-88 |
| Timeline views (self-review) | 90-99 |
| Reframe (16:9 -> 9:16, 1:1, 4:5) | 101-118 |
| Cut out the speaker | 120-146 |
| Denoise speech | 148-166 |
| Stabilise | 168-180 |
| Colour: correction and looks | 182-200 |
| Screen recordings: auto zoom | 202-205 |
| Platform notes | 207-216 |

## Inventory: probe and scenes

```bash
showtime footage probe raw/take1.mp4           # size, display size, rotation, fps, VFR, HDR, audio tracks
showtime footage scenes raw/broll.mp4          # shots -> <job>/work/scenes/broll.scenes.json + labelled sheet PNG
showtime footage scenes raw/take1.mp4 --every 5 --job talk-edit   # one frame every 5 s (quick look at any clip)
```

For a VP9/VP8 webm with alpha (an overlay rendered with `--alpha`), `probe` reports `pix_fmt: yuva420p` with
`pix_fmt_stream: yuv420p` and `alpha: side channel`: the alpha plane lives beside the colour planes, so
ffmpeg's native decoder (and a plain `snap`) sees only the colour; libvpx decodes the alpha. ProRes 4444
reports its real format (`yuva444p12le`).

Shot detection uses PySceneDetect's adaptive detector (hard cuts, and fades reported at their end)
and falls back to ffmpeg's `scdet`. `--min-len` (0.6 s) merges flicker; `--threshold` tunes it.
Read the contact sheet PNG to see what is in the footage before planning B-roll or cutaways.
A periodic sheet holds at most 60 frames: `--every 0.25 --from 12 --to 16` looks closely at a range
(the command says when it had to spread frames out); `-o sheet.png` names the file.

## Trim and proxies

```bash
showtime footage trim interview.mp4 --from 61 --to 142 -o <job>/work/excerpt.mp4   # frame-accurate excerpt
showtime footage trim demo.mp4 --width 1280 -o project/media/demo.mp4             # seek-friendly proxy for a page
showtime footage trim demo.mp4 --webm --no-audio -o project/media/demo.webm       # VP9 for Chromium without H.264
```

Re-encodes (H.264 + AAC, +faststart, a keyframe every `--gop` 0.5 s) unless `--copy` (instant, starts on
a keyframe). Use it instead of a one-range EDL or bare ffmpeg.

Talking-head footage for a "cut the ums" demo: resource reels and press soundbites are already edited
(no fillers left to cut); raw interview recordings and live shots are where fillers are.

## Timeline views (self-review)

```bash
showtime footage view take1.mp4 --from 12 --to 20            # filmstrip + waveform + words + pauses
showtime footage view take1.mp4 --from 12 --to 20 --mark 15.4
showtime edit view edit/edl.json                              # +-1.5 s around every cut of the render
```

Pauses of 0.4 s or more are shaded (with their length when 0.6 s or more), fillers are drawn in
red, audio events in amber, cut points as red lines. The transcript is found automatically.

## Reframe (16:9 -> 9:16, 1:1, 4:5)

```bash
showtime footage reframe talk.mp4 --aspect 9:16               # face-tracked crop
showtime footage reframe talk.mp4 --aspect 1:1 --zoom 1.15    # plus a punch-in
showtime footage reframe talk.mp4 --aspect 9:16 --focus 0.3,0.5   # fixed crop centre, no tracking
showtime footage reframe screen.mp4 --aspect 9:16 --fit blur  # keep the whole frame on a blurred copy
```

Tracking: YuNet face detection at 8 fps, the largest confident face (preferring the one nearest the
previous pick), gaps filled, a dead zone of 3.5 % of the width so small moves do not pan, a 1 s
centred average, and hard shot changes respected (no pan across a cut). The face sits slightly
above centre. No face found -> centre crop (or `focus`). Inside an EDL the same happens per range
with `"fit": "reframe"` (or `auto`), and `zoom` > 1 punches in around the face.

Use `blur` (or `contain`) for screen recordings and slides: cropping cuts off UI. A crop that enlarges
the source more than 1.5x (a 1280x720 clip cropped to 9:16 and scaled to 1080x1920 is 2.67x) looks
soft: the command warns and suggests a smaller standard size (720x1280, else 540x960) or `--fit blur`.

## Cut out the speaker

```bash
showtime footage cutout talk.mp4                               # -> talk.cutout.webm + talk.matte.mp4 + talk.cutout-sheet.jpg
showtime footage cutout talk.mp4 --from 12 --to 18 --format prores -o talk-cut.mov   # ProRes 4444 for an editor
showtime footage cutout talk.mp4 --format png --no-audio      # a numbered RGBA PNG folder
showtime footage cutout talk.mp4 --matte-only --size 384       # the matte alone, about twice as fast
```

A person matte per frame from MODNet (portrait matting, Apache-2.0, code and weights; 26 MB, fetched on first
use and sha256-checked, `showtime setup --fetch modnet` up front) on onnxruntime's CPU provider: no GPU, no
account. The frame is scaled to a 512 px short side for the network (`--size`), the matte is smoothed over time
where the picture is still (hair and edges stop shimmering; motion lets the new estimate through at once; every
cut starts afresh) and refined at full size with a guided filter against the frame itself. Measured on a 1080p
interview (x64 Linux), the whole command with the VP9 cut-out: 17-23 fps on 64 cores (80-105 s per minute of
footage), 5.2 fps on 6 cores (about 6 minutes per minute; `--size 384` 8.1 fps, under 4 minutes); the matte
alone (as a behind card makes it) 25 fps on 64 cores, 6.7 on 6. The report gives the speed and `flicker` (the
share of the person's area whose matte jumps on a still picture; a warning over 2 %: a busy or dark background).

- `<name>.cutout.webm`: VP9 with alpha and Opus sound; browsers play it with its alpha, EDL `overlays[]` and
  `<video>` layers composite it. ffmpeg's own VP9 decoder and most players show it without the alpha: look at
  `<name>.cutout-sheet.jpg` (three frames over a checkerboard, their mattes under them).
- `--format prores`: ProRes 4444 with 16-bit alpha and PCM sound, for an editor. `png`: RGBA frames.
- `<name>.matte.mp4`: the matte alone (white = person), H.264: a luma or track matte in any editor.
- The colour of the frames is kept as recorded (BT.709 in, BT.709 out). It cuts out people, not objects;
  frames with no person come out empty (the report counts them).
- In an edit, a `behind` card does all of this itself on the render's own frames (`editing.md` section 9).

## Denoise speech

```bash
showtime footage denoise interview.mov -o interview.clean.mov        # auto: best available
showtime footage denoise vo.wav -o vo.clean.wav --strength 0.7
```

`auto` picks DeepFilterNet (installed with `showtime setup --with deepfilter`) if present, else
RNNoise (`arnndn`, models `cb` general / `sh` stronger / `std`), else ffmpeg `afftdn`. A 70 Hz
high-pass runs first. `strength` below 1 keeps some room tone (sounds more natural): for DeepFilterNet
it caps the reduction (0.5 = at most 21 dB), for RNNoise it is the wet mix, for `afftdn` the reduction
amount. The report line names that, the noise floor before/after and the level of what was removed (the
floor alone barely moves on audio with little steady noise, so two strengths can look alike there; the
removed level differs). The output keeps the source's channel count (stereo stays stereo) and its exact
length in samples (DeepFilterNet's ~30 ms frame delay is padded back), so a cleaned track still lines up
with the picture. In an EDL use `"audio": {"denoise": "auto"}`: each source is cleaned once and cached.

Do not denoise clean studio audio; it can only lose detail. Denoise before loudness mastering
(the renderer does this order for you).

## Stabilise

```bash
showtime footage stabilize walk.mp4 --strength 0.7 -o walk.stable.mp4
```

Two-pass vid.stab (motion analysis, then smoothing with automatic border-hiding zoom and a light
sharpen). Builds without vid.stab (some ffmpeg builds, for example on Apple Silicon) fall back to
`deshake`; the output says which was used. In an EDL: `"stabilize": true` on a range.

There is no `--compare` here on purpose: a before/after still cannot show shake. Judge motion by
watching both, or compare the framing (the stabiliser zooms in to hide moving borders) with
`showtime snap walk.stable.mp4 --at 2,5 --compare walk.mp4` (writes a before|after `compare.jpg`).

## Colour: correction and looks

```bash
showtime footage grade take1.mp4 --analyze                     # measured stats + the auto correction
showtime footage grade take1.mp4 --auto --look teal-orange --strength 0.5 -o take1.graded.mp4
showtime footage grade take1.mp4 --preset punch --compare --at 4     # before/after PNG (-o must be .png/.jpg)
showtime footage luts                                          # list looks
showtime footage luts --preview take1.mp4 --at 5               # every look on one frame (PNG)
```

- **Order:** correct first (auto: exposure via gamma, contrast when flat or foggy, saturation when
  dull; each change bounded), then a look at 40-70 %, then the BT.709 output conversion.
- **Presets** (eq/curves): `subtle punch warm cool film mono webcam lowlight`.
- **Looks** are original 33-point `.cube` LUTs generated by showtime (no third-party files):
  `teal-orange warm-film clean-punch cool-tech mono-contrast bleach golden-hour matte night`. The
  strength is baked into the LUT. Your own `.cube` works too (`--look my.cube --strength 0.6`).
- Grade real footage only. UI captures and motion graphics keep their design colours.
- In an EDL: `"grade": "auto"`, `"grade": "warm-film"`, or
  `{"auto": true, "preset": "subtle", "lut": "teal-orange", "strength": 0.5}`; per range too.

## Screen recordings: auto zoom

`showtime footage autozoom ...` forwards to the capture module's click-driven zoom (see
`tutorial-recording.md`).

## Platform notes

- All tools run on macOS (Apple Silicon and Intel), Windows and Linux. ffmpeg features differ by
  build; every optional filter has a fallback (vid.stab -> deshake, arnndn -> afftdn,
  zscale missing -> HDR shown without tone mapping plus a warning, lut3d missing -> look skipped
  with a warning). `showtime doctor` lists what your ffmpeg has.
- Speech recognition, diarization, events, face tracking and the speaker cutout run on the CPU through
  CTranslate2 / ONNX Runtime; no GPU or account is needed.
- Heavy steps (transcription, renders) use all cores: run them one after another, not in parallel
  with browser captures.

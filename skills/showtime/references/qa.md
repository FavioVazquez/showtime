# QA: acceptance checklists and the critic pass

Read this when a video is about to be rendered or delivered: the pre-render and post-render checklists
and the `showtime qa` rules and `expect` block. The critic protocol is in `review.md`.

Nothing ships on "it rendered". Ship on evidence. Run the pre-render list before the final render,
the post-render list on the MP4, then the critic pass. Fix, re-render the affected range, and re-check.
Report failures honestly. Don't retime audio or cut duration to hide a sync problem.

Tools: `showtime check <project>` (runtime errors, overflow, contrast from real pixels, determinism
warnings), `showtime snap <project> --at t1,t2,...` and `--sheet --every 1s` (stills and contact sheets),
`showtime render <project> --preview` (fast draft), `showtime audio meter <file>` (loudness and peaks).
For stream inspection, use the bundled ffprobe (`showtime paths` shows where it is). Never call a bare system `ffmpeg`/`ffprobe`.

Batch visual checks: look at one contact sheet per phase, not dozens of single frames.

## 1. Pre-render (on the project)

**Story**
- [ ] The "This video tells ___ that ___" sentence exists and every scene traces back to it.
- [ ] The hook is readable by 0.3 s, and the first change happens by 2 s. Frame 0 is not black and not a logo sting.
- [ ] Every claim, number, quote and logo is from the source (story.md §6). Illustrative data is labeled when it could be mistaken for real.
- [ ] No secrets, internal hostnames or real customer or personal data appear anywhere, including in share copy.
- [ ] The distinctness check (story.md §8) passed.

**Text and layout** (sheet at each scene start and midpoint)
- [ ] `showtime check` reports 0 errors. Warnings are read and either fixed or explained.
- [ ] Every text hold meets pacing.md §1 (settled time, not entrance time).
- [ ] Sizes are at or above the floor in typography.md §3. Text sits inside the safe box for every target aspect.
- [ ] Contrast is ≥4.5:1 (≥3:1 for large display) on real pixels, including frames **mid-transition**.
- [ ] No overflow, clipping, collisions or orphaned single-word lines. Nothing sits in the caption band when captions exist.
- [ ] No `labels_crowded` (warning): SVG labels in one graphic (chart values and axes, map names) that touch or sit
      closer than 0.15em side by side or stacked (`label_gap_em` in `runtime/thresholds.json`). Fix: fewer bars
      (aggregate, or label only the highlight and extremes), the chart's default `valueLabels` (auto-thinning, not
      `"all"`), or a larger plot. Seen only while a chart grows or morphs it is a note; the settled frame is judged.
- [ ] There are no off-palette colors and at most 2 font families. All fonts load from local files (no fallback in the check report).

**Motion**
- [ ] Cuts: snapshot at `cut − 0.1 s` and `cut + 0.2 s` for every cut. Elements that continue across a cut match
      in position, scale and color. A crossfade between two busy layouts must not look like a muddy double exposure.
      Stagger it (old out, then new in) or dip through the ground.
- [ ] No dead zones of 1 s or more without motion, unless it's the planned held beat or the final hold.
- [ ] No bounce on text blocks, no looping "breathing" on readable text, and no lingering slow push in the back half of a scene.
- [ ] Flash limit: ≤3 flashes in any 1 s window, and ≤2 flash frames in the whole video.
- [ ] The final frame is a designed hold (logo, CTA), not the tail end of an exit animation.

**Audio plan**
- [ ] Music starts on frame 1 (no silent intro) and ends on a button that lands on the logo (no fade-out mid-phrase).
- [ ] The voice script fits the word budget, and scene durations were synced from the measured voice clips.
- [ ] SFX density matches the tone, with one sound family. The reveal gets an impact, and there is no whoosh on every cut.

**Determinism**
- [ ] No `Date.now`, unseeded `Math.random`, CSS transitions, infinite animations or timers driving visuals
      (`showtime check` warns). Randomness goes through `ST.rand(seed)`/`ST.noise`.
- [ ] Snap the same time twice (e.g. `--at 3.2,3.2`). The two images must be identical.
- [ ] Snap a late time first and then an early one. Seeking backward must give the same image as seeking forward.

## 2. Post-render (on the MP4)

**File**
- [ ] H.264 High, `yuv420p`, BT.709 tags present, faststart, AAC 48 kHz stereo, and the expected width, height and fps.
- [ ] Duration = `showtime.json` duration ±1 frame. Frame count = `round(duration × fps)`. Audio duration within 1 frame of video.
- [ ] Within every target's length and size cap (platforms.md §2).

**Visual** (contact sheet at 1 s intervals + stills at the hook, reveal, each cut, the final second)
- [ ] Frame 0 is the intended poster or hook frame. There are no black or frozen runs over 0.5 s that weren't planned.
  Camera footage of a speaker holding still is not frozen: `qa` samples a long hold and, when every part of the frame keeps
  camera noise and a few places move (lips, blinks, hands) while there is sound, reports it as `held_shot` (INFO) instead;
  the same live picture without sound is a `frozen` WARN. A hold in a project whose page plays no `<video>` is always judged as frozen.
- [ ] No banding in dark gradients when viewed at 200% (color.md §4). No encoding blockiness on grain or fast motion.
- [ ] Brand colors sampled from a flat area are within about 2 levels of the source hex.
- [ ] Text is legible when the sheet is viewed at phone size (about 360 px wide for 16:9, 270 px for 9:16).

**Audio metering** (`showtime audio meter`)
| Measure | Target |
|---|---|
| Integrated loudness | −14 LUFS ±1 (or the requested target) |
| True peak | ≤ −1.0 dBTP |
| Loudness range | ≤8 LU (≤11 for music-first pieces) |
| Voice vs music under it | Music 18–25 dB below the voice. Voice is always intelligible |
| Start | Audio present within the first 0.1 s when music is planned from frame 1 |
| End | Clean button or tail, with no cut-off decay in the last 0.3 s |
- [ ] Listen once on small speakers or earbuds, at least the hook, the reveal and the end. No clicks at edits,
      no harsh sibilance, and no SFX louder than the voice.

**Deliverables**
- [ ] Frame 0 is the thumbnail and flows into frame 1: a hook complete at t=0 (`"poster": 0`), or a poster that
      `showtime render` baked because it looks like the opening (`--poster-bake auto`). `poster.jpg` is the cover to
      upload where a platform takes one. EDL and external videos: `showtime deliver poster <video> --at <t> --bake`
      (then `<video>.poster.mp4` ships). qa WARNs `poster_flash` when frame 0 jumps to a different frame 1.
- [ ] `share.txt` exists, is 1–3 sentences in the video's tone, and contains no claim that isn't in the video.
- [ ] Captions are burned in for social targets, and a sidecar `.srt`/`.vtt` exists where the platform supports one.
- [ ] A credits file ships whenever any CC-BY asset was used (`credits.txt` beside `final.mp4`, or
      `<stem>.credits.txt`; render writes it), and the user has been told to paste it into the description.
- [ ] Platform exports each pass their own caps and safe zones.
- [ ] The report to the user lists paths, actual duration, the angle in one sentence, the contact sheet, and scene ids for targeted changes.

## 3. The critic pass

Publish-bound or studio work: `showtime review-pack <job>`, then follow `review.md`. The critic's
brief is the `CRITIC.md` the pack writes (severity scale, citation rule, answer format, two rounds at
most); do not write a brief of your own. Quick work gets the self-review in `review.md` section 1.

## Tools

The checklists above are judged by eye; these commands produce the evidence. **Do not call a video ready
without a `showtime qa` verdict from the current turn**, quoted with its numbers, and without having looked
at the contact sheet it wrote.

**`showtime qa [video|job] [--project dir] [--expect file] [--platform name] [--captions file] [--json]`**
checks the delivered file itself. Given a job (folder or name), or nothing inside a job, it checks the
job's latest final (else its latest draft) and prints `using <path> (latest final)`; an explicit older
file is still checked, with a note naming the newer one. Name the platform whenever there is one:
`--platform`, else showtime.json `expect.platform`, else showtime.json `"platform"`, else the job's
(`showtime job init|note --platform reels`); the output says which (`platform  reels (from job.json)`),
and with none it runs generic checks only (no length or aspect limits).

Which caption files it checks (it prints them; `qa.json` `captions`):
- `--captions FILE` (repeatable): exactly those files, nothing found automatically. Use it to judge a
  variant on its own sidecar (`qa shorts-9x16.mp4 --captions shorts-9x16.ass`).
- In a job folder: the video's own sidecars, `<stem>.srt/.vtt/.ass` beside it (`final.srt` also counts
  for a baked `final.poster.mp4`), plus the job's latest captions (recorded by `edit render`, by
  `showtime captions --srt` into the job folder, or `job note --output captions=<file>`) only when the
  file is the job's latest final or draft, has no sidecar of its own and the captions were made for the
  same aspect (an `.ass` PlayRes, or the video the `.srt` is named after); with no captions recorded, the
  project's own caption files of that aspect. A 9:16 variant or an export never inherits the 16:9 captions.
- Outside a job: `<stem>.*`, `captions.*` / `subs.*` and `captions/` beside the video, and the project's.

Output: PASS / WARN / FAIL lines, each with a rule id, a timestamp, the frame at that time
(`work/qa/<video>/frames/`) and a fix; `qa.json` and `sheet.jpg` (FAIL/WARN frames outlined). Every long
caption line and every too-fast cue is listed (up to 12 each, the rest counted), so one run shows them all.
Exit code 1 on FAIL (`--strict`: also on WARN). When the video sits in a job folder, the verdict is logged
per file in `job.json` (`qa_files`); the job's verdict (`qa`, what `status` and `SHOWTIME.md` show) follows
the job's latest final (else draft) only, so checking an export or a variant never makes the final look
unchecked. After a WARN, "Next command" names the rules to fix first (e.g.
`showtime check <project> --find-first frozen`), then the re-render and `showtime qa <job>`.

Size-capped platforms (`github`, `chat`, `web`, or `expect.max_size_mb`): keep a full-quality master and
deliver a capped copy. When `deliver exports` already wrote one beside the master (`exports/<stem>.github.mp4`,
`<stem>.<N>mb.mp4`) under the cap, the master's `file_size` is INFO and names the command that checks the
export itself (`showtime qa <export> --platform github`); without one it FAILs with the exact
`deliver exports` command.

| Rule | Severity | Fires when |
|---|---|---|
| `unreadable`, `no_video` | FAIL | ffprobe cannot read the file (or its audio cannot be decoded) / the file has no video stream |
| `odd_dimensions` | FAIL | width or height is odd |
| `codec`, `pix_fmt`, `variable_fps`, `faststart`, `color_tags` | WARN | not H.264 / yuv420p / constant standard fps / moov first / BT.709 tagged |
| `duration` | FAIL | off the expect block (± tolerance) or the project/render length (± 1.5 frames) |
| `no_audio` | WARN (FAIL if `expect.audio`) | no audio stream |
| `audio_codec` | WARN (INFO for a sample rate other than 48 kHz) | the audio codec is not AAC |
| `av_length` | WARN | audio and video lengths differ by more than 1.5 frames (and 0.06 s) |
| `silent_audio` | FAIL | the audio stream is digital silence |
| `loudness` | WARN > 1 LU off target, FAIL > 3 LU | integrated LUFS vs the platform target (default -14) |
| `true_peak` | WARN above ceiling + 0.3, FAIL above 0 dBTP | 8x oversampled true peak |
| `clipping` | FAIL | runs of full-scale samples (a squared-off waveform) |
| `leading_silence` / `trailing_silence` | WARN | sound starts after 0.5 s / the last 2 s are silent |
| `silent_gap` | WARN ≥ 1 s, FAIL ≥ 3 s | silence inside the video |
| `first_frame_black` | FAIL | frame 0 is black (no poster baked) |
| `first_frame_flat` | WARN | frame 0 is one flat colour |
| `poster_flash` | WARN | frame 0 differs sharply from frames 1-2 (a baked poster over an opening that builds from empty): a one-frame flash on autoplay and every loop |
| `black_segment` | WARN ≥ 0.25 s, FAIL ≥ 1 s | black inside the video (`ends_black`: WARN for a black ending ≥ 1 s) |
| `frozen` | WARN ≥ 2.5 s (launch films, showtime.json `"kind": "launch"`: ≥ 5 s, `launch_hold_s`), FAIL ≥ 6 s or half the video | no visible change (a few typed characters or a thin moving line still count as a hold); the thresholds, `freeze_noise_db` included, live in `runtime/thresholds.json`, shared with `showtime check`, so check finds the same holds before the render. A padded or blurred export is judged inside its picture (`<export>.export.json`), not on its bars. See "Dark themes and slow pushes" below |
| `held_shot` | INFO | a long hold that is live camera footage with sound (a speaker holding still), not a frozen picture; see the Visual checklist above |
| `final_hold` | INFO ≤ 4 s, WARN above | the ending is a still hold (fine for an end card) |
| `captions_past_end`, `captions_timing` | FAIL | sidecar cues outside the video or reversed |
| `caption_flash` | WARN | cues on screen for under 0.4 s (fast speech split into one-word blinks); the summary prints the shortest cue |
| `captions_overlap`, `caption_lines`, `caption_line_long`, `caption_fast`, `caption_bounds` | WARN | two cues at once, > 2 lines, > 42 characters (32 vertical, 4:5 included), > 20 characters/s (cues of 3+ words), outside the safe box. `showtime captions` and `voice script` write within these same limits |
| `captions_missing` | FAIL/WARN | `expect.captions` but no sidecar and no caption text in the check report |
| `captions_empty` | WARN | a caption file has no cues or cannot be read |
| `missing_credits` | FAIL | a mix report or `.license.json` sidecar requires attribution and no credits file (`credits.txt` in any case, `<stem>.credits.txt`, or the job's credits) ships with the video |
| `credits_incomplete` | WARN | the credits file lacks a required line |
| `too_long`, `too_short`, `file_size` | FAIL | outside the platform or expect limits |
| `aspect` | WARN (FAIL for `expect.width/height/aspect`) | aspect differs from the platform |
| `resolution` | WARN | the aspect fits but the frame has under 97 % of the platform's pixels (540x960 for Reels): render the final at full size |
| `upscale` | WARN (INFO when the EDL sets `"output": {"allow_upscale": true}`) | an EDL render enlarged a source more than 1.5x (from `<video>.report.json`, also for a baked `final.poster.mp4` and for exports, which carry the report with factors scaled to their size); the fix names a smaller output size or `--fit blur`, or says when it is unavoidable (1080p to 1080x1920) |
| `must_show` | FAIL | a must-show text is missing from the on-screen text list of the last `showtime check` |
| `must_show_unverified` | WARN | found only in the project source (run `showtime check`, then `qa` again) |
| `expect_invalid` | WARN | an unknown key in the `expect` block, or an unknown platform name (checked without a platform target) |
| `edit_choppy` | WARN (launch films) | more than 5 hard cuts in a film of up to 60 s |
| `too_many_scenes` | WARN (launch films) | more than 6 scenes or layouts in up to 60 s |
| `dead_hold` | WARN (launch films) | nothing moves for more than 5.5 s |
| `flat_music` | WARN (launch films without a voice) | the mix's loudness moves less than 3 dB (10th-90th percentile of 0.5 s windows) |

The optional `expect` block in `showtime.json` (or a file passed with `--expect`) states the brief's
measurable targets up front:

```json
"expect": {"duration": 15, "tolerance": 0.5, "platform": "reels", "lufs": -14, "true_peak": -1,
           "audio": true, "captions": true, "max_size_mb": 50,
           "must_show": ["Northwind", {"text": "v2 is here", "at": 3.0, "tol": 1.0}]}
```

Platforms: `youtube x linkedin reels tiktok shorts square` (as in `deliver exports`) plus `web` (silent loop,
15 MB), `github` and `chat` (10 MB), `broadcast` (-23 LUFS).

**Edit rhythm** (`rhythm` in qa.json, one line in the output) is measured for every video up to 3 minutes:
layouts (stretches with one composition) and how each layout change happens (`cut`, `fast`: a push,
wipe or whip under 0.6 s that replaces the frame, `move`: 0.6 s or more of continuous motion: a camera
move, a match, a dissolve), hard cuts, shot lengths, the share of frames where nothing moves and the
longest such stretch, the mix's dynamics, and per planned scene change whether it was a hard cut
and whether the music moves there (an onset or a +1.5 dB rise). It is judged (the four rules above) for
launch, promo, release and trailer films: showtime.json `"kind": "launch"` (the launch template sets it),
`expect.style`, or a job goal that says launch, promo, trailer, teaser or release video. The numbers
come from the premium grammar in `workflows/launch-video.md`.

**Dark themes and slow pushes.** Black and frozen stretches are measured on absolute pixel change, so two
honest designs can trip them:
- `black_segment` on a dark theme: a near-black ground (#0b0b0f and similar) counts as black. A 0.25-1 s
  WARN where a crossfade lands on the empty ground is usually real dead air; start the incoming content
  earlier (or on the cut) rather than lightening the ground.
- `frozen` on a slow push or drift over dark frames: an 8 % push over 7 s, eased at both ends, changes
  dark pixels too little in its slow ends. Look at the two frames the finding names (or
  `showtime snap <video> --at <start>,<end>`): if the framing visibly moved, the hold is a slow camera
  move, not a still; either speed the move (or drop the ease on the long side), add a moving element, or
  accept the WARN knowingly (`showtime job note <job> --verified "frozen at 12.4 s is a slow push"`).
  A typing beat on a still terminal is a real hold; give it a cursor or a camera move.

**`showtime check <project>`** also audits canvas films through `Film.frameInfo()` (text off frame, safe
zone, overlap, contrast against the surrounding pixels, fonts, reading time), flags `Math.random()` during
playback (`unseeded_random`), and records every on-screen text with its first/last time in
`report.json` (`texts`), which `qa` uses for `must_show`. Extra modes:
- `--determinism`: 12 probe frames plus a second page load; frame hashes land in `report.json`.
- `--find-first black|frozen|nondeterministic|error [--from s --to s --min s]`: bisects to the first bad
  frame and saves it with the last good one (see `debugging-renders.md`).

**`showtime review-pack [job|video]`** (a job means its latest final) builds the critic's folder (`review/round-N/`: sheets, key and scene
frames, loudness graph, qa run, context copies, `CRITIC.md` with the eight judging questions). Scene
frames follow the planned scenes: showtime.json `"scenes"`, then `"chapters"`, then a film's `CUE.acts`
(every `key: number` pair in `CUE` counts), then the page's scene clips (`<section>` / `.scene` clips when
there are two or more, else top-level clips minus overlays: a clip shown inside another clip's window, an
open-ended layer under later clips, or `data-overlay`), `voice/timeline.json` slots or the EDL report; only
without any of these does it detect cuts in the pixels. It prints `(N scenes, M cuts, from <source>)`; the
manifest has `scenes_source`. Its fresh qa run uses `--platform`/`--lufs` when given, else the ones the last
`showtime qa` of the same file was given (a -16 LUFS tutorial stays judged at -16). For an edit render, qa judges loudness against what the render report says it was mastered to (-14 by default; a kept source level is noted, not failed). The protocol is in
`review.md`.

**Which render is the job's latest final.** `showtime qa <job>`, `review-pack <job>` and `deliver` use the
job's latest final. A render, `edit render`, `captions --burn` or `deliver poster --bake` inside a job
becomes it when the file is an `.mp4` named `final*` (or a derived copy of the current final, e.g.
`launch.poster.mp4` of `launch.mp4`); `render --job` always writes such names. Anything else (an alpha
`.webm`/`.mov` overlay, `bumper.mp4`, a second aspect named `shorts-9x16.mp4`) is logged as a variant and
the output says how to promote it: `showtime job note <job> --output final=<file>`. Check a variant with
`showtime qa <file>` (plus `--captions` for its own sidecar).

Planted-defect fixtures in `tests/fixtures/defects/` prove each rule fires; add one before adding a rule.

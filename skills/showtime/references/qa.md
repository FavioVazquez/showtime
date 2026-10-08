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

Batch visual checks: one `showtime look` per phase, not dozens of single frames (`looking.md`).

## Essentials

- Never call a video ready without a `showtime qa` verdict from the current turn, quoted with its numbers, and
  a look at the file (`showtime look <job>`). Ship on evidence, not on "it rendered" (§ Tools)
- Pre-render list, final render, post-render list on the MP4, critic pass; never retime audio or cut duration
  to hide a sync problem (§1, §2, §3)
- The "This video tells ___ that ___" sentence exists and every scene traces to it; hook readable by 0.3 s, first
  change by 2 s, frame 0 neither black nor a logo sting (§1)
- Every claim, number, quote and logo is from the source; label illustrative data; no secrets, internal hostnames
  or real customer or personal data anywhere, share copy included (§1)
- `showtime check <project>`: 0 errors, ends with `phone check: PASS`; contrast ≥4.5:1 (≥3:1 large display) on
  real pixels, mid-transition frames included; no `labels_crowded` (§1)
- Snap `cut − 0.1 s` and `cut + 0.2 s` at every cut; no unplanned 1 s dead zone; ≤3 flashes in any 1 s and
  ≤2 flash frames per video; the final frame is a designed hold (§1)
- No `Date.now`, unseeded `Math.random`, CSS transitions or timers; `--at 3.2,3.2` gives identical images (§1)
- File: H.264 High, `yuv420p`, BT.709 tags, faststart, AAC 48 kHz stereo, duration = `showtime.json` ±1 frame (§2)
- Audio: −14 LUFS ±1 (or the requested target), true peak ≤ −1.0 dBTP, LRA ≤8 LU (≤11 music-first), music
  18–25 dB under the voice; `loudness` WARNs past 1 LU off target, FAILs past 3 LU (§2, § Tools)
- Hearing (WARN, with times): a voice line under 8 dB over the music (`voice_masked`, from the narration stem),
  near silence over 2 s mid-video (`quiet_stretch`), a jump over 6 LU at a cut (`level_jump`), sound still playing
  on the last frame (`abrupt_end`), a name or number of the voice-over heard differently from the script
  (`readback`, FAIL for a title, brand or lexicon name), a mix that plays far quieter on a phone speaker than its
  loudness says (`speaker_loudness`: over 10 LU under above 300 Hz, FAIL over 18); `review-pack` hands the
  critic the full measurements (§2, § Tools)
- Frame 0 is the thumbnail: a hook complete at t=0 (`"poster": 0`) or a baked poster (`--poster-bake auto`);
  EDL and external videos: `showtime deliver poster <video> --at <t> --bake`. Ship `share.txt` (1–3 sentences,
  no claim not in the video), burned captions for social plus a sidecar, and credits for any CC-BY asset (§2)
- `showtime qa [video|job] [--platform name] [--captions file] [--expect file]`: always name the platform;
  exit 1 on FAIL (`--strict`: also WARN); after a WARN run the "Next command" it prints (§ Tools)
- Size caps (`github`, `chat`, `web`): keep the master, qa the capped export with `--platform github` (§ Tools)
- Captions: ≤2 lines, ≤42 characters a line (32 vertical, 4:5 included), ≤20 characters/s for 3+ word cues, no
  cue under 0.4 s; judge a variant on its own sidecar with `--captions FILE` (§ Tools)
- Phone check floors: 5 pt (16:9), 10 pt (1:1), 11 pt (4:5), 15 pt (9:16); reading time `0.3 s + max(characters
  / cps, words / wps)`, ≥1 s. qa quotes the last `showtime check`, so run check first or it says PARTIAL (§ Tools)
- `frozen` WARNs from 2.5 s without visible change (launch films 3.5 s), FAILs from 6 s. Launch films also WARN
  past 5 hard cuts or 6 scenes in 60 s, a 5.5 s still, and a voiceless mix moving under 3 dB (§ Tools)
- Quality mode (the default), publish-bound or studio work: `showtime review-pack <job>` (qa's "review pending"
  line names it), then `review.md` with the pack's `CRITIC.md`; lean: publish-bound only (§3)
- Quality floor (WARN): player controls in the footage, soft or upscaled footage, stepped caption boxes, a
  small picture in big flat borders; the critic's `WOULD I POST THIS: no` holds delivery in quality mode, and
  each blocker and should-fix it raises is fixed or waived before delivery (§3, § Tools)
- Only a `final*.mp4` is the latest final; promote a variant: `job note <job> --output final=<file>` (§ Tools)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. Pre-render (on the project) | 68-114 |
| 2. Post-render (on the MP4) | 116-157 |
| 3. The critic pass | 159-169 |
| Tools | 171-386 |

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
- [ ] `showtime check` ends with `phone check: PASS` (type size in points at phone width, every text held long enough to read,
      nothing under platform UI; the numbers and their sources are under "Phone check" below).
- [ ] Contrast is ≥4.5:1 (≥3:1 for large display) on real pixels, including frames **mid-transition**.
- [ ] No `low_contrast`: check judges a fading text at the frame where it is most opaque, so a long fade-in needs no shortening.
- [ ] No overflow, clipping, collisions or orphaned single-word lines. Nothing sits in the caption band when captions exist.
- [ ] No `caption_zone`: nothing visible is drawn where the caption cards sit while a caption shows (`data-st-caption-ok` if intended).
- [ ] No `webgpu`: scenes draw with WebGL or 2D; a WebGPU page renders a flat ground on a machine without a GPU.
- [ ] No `blur_*` warning: a shutter blur (`data-st-blur`) sits only on 1-3 snap beats, on the element that snaps, never on
      text being read, slow moves or a whole scene; snap a blurred frame and the frame it lands on (sharp) to look at both.
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
| End | Clean button or tail, with no cut-off decay in the last 0.3 s (`abrupt_end`) |
| Across cuts | No jump over 6 LU in the bed or the voice that the story does not call for (`level_jump`) |
| Heard on a phone | The mix above 300 Hz at most 10 LU under the full mix (`speaker_loudness`; posted films 1-8 LU) |
- [ ] Listen once on small speakers or earbuds, at least the hook, the reveal and the end. No clicks at edits,
      no harsh sibilance, and no SFX louder than the voice. The critic cannot listen: its hearing pass judges
      only the numbers in the pack's `audio.txt` (review.md §1), so these stay yours.

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

Every finished video in quality mode (the default; qa prints "review pending" with the command until a round
has a verdict), and publish-bound or studio work in lean mode: `showtime review-pack <job>`, then follow
`review.md`. The critic's
brief is the `CRITIC.md` the pack writes (severity scale, citation rule, answer format, three rounds
at most, pairwise from round 2, the absolute `WOULD I POST THIS` line, the first-viewer pass); do not write a brief
of your own. Lean work that is not publish-bound gets the self-review in `review.md` section 1. Once a critic has
answered, `showtime job note <job> --stage deliver` waits until each of its blockers and should-fixes is fixed or
waived (`showtime review-respond`, `review.md` section 4). It also refuses while the final's latest qa verdict is
FAIL (WARN passes): fix, re-render and run `showtime qa <job>` again.

## Tools

The checklists above are judged by eye; these commands produce the evidence. **Do not call a video ready
without a `showtime qa` verdict from the current turn**, quoted with its numbers, and without a look at
the file (`showtime look <job>`, `looking.md`).

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
The hearing measurements (voice over the music per line, words per minute, quiet stretches, the level across
each cut, effects, the ending, the read-back) are in `qa.json` `hearing`, summed up in the `hearing` line; their 100 ms block
levels are in `loudness.json` `blocks`, from which `review-pack` writes the critic's `audio.txt` and `hearing.png`.
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
| `voice_masked` | WARN | a voice line sits under 8 dB (`hearing.voice_over_bed_min_db`) over the music under its words. Measured only when the render's narration stem lines up with the file's audio (render keeps `work/audio/mix.voice.wav`; an edit render its speech stem; a voice-only mix over an `ST.score` bed): the stem is aligned (±50 ms) and scaled to the delivered audio, the rest is the bed. Without a stem `review-pack` still estimates it for the critic, never a WARN |
| `quiet_stretch` | WARN | near silence for 2 s or more mid-video: 100 ms blocks more than 20 LU under the integrated loudness (`quiet_stretch_s`, `quiet_under_lu`), not already a `silent_gap` |
| `level_jump` | WARN | the level changes more than 6 LU (`level_jump_lu`) across a cut (planned scene starts and hard cuts), 1 s each side, like with like: the bed with the bed (stem), else both sides speech or both not; a cut where speech starts or stops, an effect within 1 s or a music section change at the cut does not count |
| `readback` | WARN, FAIL for a name in the title, brand or project lexicon | the project's `voice/vo.wav` transcribed again locally and lined up with the script sound by sound: a name, acronym or number heard differently ("Open A I" heard as "OpenI"). Reuses `voice/readback.json` when `voice script` wrote it for that `vo.wav`; else transcribes the line clips (cached), or `vo.wav` itself. INFO when the recognizer is not installed. Fix: [voice.md](voice.md) § Pronunciation fixes |
| `speaker_loudness` | WARN over 10 LU, FAIL over 18 (`speaker_gap_lu`, `speaker_gap_fail_lu`); INFO when the mix turned `speaker_safe` off | heard on a phone: the integrated loudness of the mix above 300 Hz (and above 1 kHz), measured like `ffmpeg -af "highpass=f=300,highpass=f=300,ebur128"`, against the full mix. Phone and laptop speakers play little under 300 Hz, so a mix of kick, bass and sub at -14 LUFS plays quiet there. Calibrated on 7 Oct 2026: every posted film 0.7-8.2 LU, a bass-led showreel preview 13.6 LU (-27.6 LUFS above 300 Hz, about 9 dB quieter on a phone than the voice-led films). The fix: `showtime audio mix` (its speaker-safe step, on by default, cuts the bed's lows; `audio.md` § Heard on a phone), a bed with more in the mids, a mid transient on sub hits. The numbers are in every qa run (`qa.json` `hearing.speaker`, the PASS line, the `hearing` line) |
| `abrupt_end` | WARN | the last 0.2 s (of the bed, with a stem) are within 10 dB (`abrupt_end_db`) of the 3 s before and audible: music, or a word, cut off on the last frame. A seamless loop may ignore it |
| `first_frame_black` | FAIL | frame 0 is black (no poster baked) |
| `first_frame_flat` | WARN | frame 0 is one flat colour |
| `poster_flash` | WARN | frame 0 differs sharply from frames 1-2 (a baked poster over an opening that builds from empty): a one-frame flash on autoplay and every loop |
| `poster_mismatch` | WARN | the render's poster still (render.json `poster`) differs from its video frame by more than 4 mean luma levels, or its PNG carries colour chunks (gAMA, cHRM, cICP, iCCP) that make browsers draw it darker than the video |
| `black_segment` | WARN ≥ 0.25 s, FAIL ≥ 1 s | black inside the video (`ends_black`: WARN for a black ending ≥ 1 s) |
| `frozen` | WARN ≥ 2.5 s (launch films, showtime.json `"kind": "launch"`: ≥ 3.5 s, `launch_hold_s`), FAIL ≥ 6 s or half the video | no visible change (a few typed characters or a thin moving line still count as a hold); the thresholds, `freeze_noise_db` included, live in `runtime/thresholds.json`, shared with `showtime check`, so check finds the same holds before the render. A padded or blurred export is judged inside its picture (`<export>.export.json`), not on its bars. See "Dark themes and slow pushes" below |
| `dead_stop` | WARN | a fast move (6+ frames of real change) whose last frames still move at half its peak or more, then nothing for 4+ frames: it lands with no settle. The message names the frame; fix: ease the last 6-10 frames out (`power3.out`, `premium`) or land earlier and hold (st.qa.motion, on the rhythm's frame differences) |
| `held_shot` | INFO | a long hold that is live camera footage with sound (a speaker holding still), not a frozen picture; see the Visual checklist above |
| `final_hold` | INFO ≤ 4 s, WARN above | the ending is a still hold (fine for an end card) |
| `captions_past_end`, `captions_timing` | FAIL | sidecar cues outside the video or reversed |
| `caption_flash` | WARN | cues on screen for under 0.4 s (fast speech split into one-word blinks); the summary prints the shortest cue |
| `captions_overlap`, `caption_lines`, `caption_line_long`, `caption_fast`, `caption_bounds` | WARN | two cues at once, > 2 lines, > 42 characters (32 vertical, 4:5 included), > 20 characters/s (cues of 3+ words), outside the safe box. `showtime captions` and `voice script` write within these same limits |
| `phone_size`, `phone_reading`, `phone_zone` | WARN | the phone check's findings, copied from the project's last `showtime check` with their timestamps (and frames): text under the minimum in points at phone width / on screen for less than it takes to read / under platform UI, a player control strip or at the frame edge. A phone-check failure is a WARN, never a FAIL |
| `phone_unverified` | INFO | qa could not verify type size, reading time or UI zones: no `showtime check` report with a phone block for this project, or it ran at another size. Captions are still judged (below) |
| `captions_missing` | FAIL/WARN | `expect.captions` but no sidecar and no caption text in the check report |
| `captions_empty` | WARN | a caption file has no cues or cannot be read |
| `missing_credits` | FAIL | a mix report or `.license.json` sidecar requires attribution and no credits file (`credits.txt` in any case, `<stem>.credits.txt`, or the job's credits) ships with the video |
| `credits_incomplete` | WARN | the credits file lacks a required line |
| `too_long`, `too_short`, `file_size` | FAIL | outside the platform or expect limits |
| `aspect` | WARN (FAIL for `expect.width/height/aspect`) | aspect differs from the platform |
| `resolution` | WARN | the aspect fits but the frame has under 97 % of the platform's pixels (540x960 for Reels): render the final at full size |
| `upscale` | WARN (INFO when the EDL sets `"output": {"allow_upscale": true}`) | an EDL render enlarged a source more than 1.5x (from `<video>.report.json`, also for a baked `final.poster.mp4` and for exports, which carry the report with factors scaled to their size); the fix names a smaller output size or `--fit blur`, or says when it is unavoidable (1080p to 1080x1920) |
| `caption_face` | WARN | an edit with cards (or `captions.avoid_face`) has captions over the tracked face (eyes to chin) with no room above or below it (from `<video>.report.json`) |
| `card_problem` | WARN | an edit's cards (EDL `cards`) overlap, sit on the captions or out of the safe box, lack room beside the face, or are too short to read (from `<video>.report.json`; `edit check` lists the same) |
| `behind_hidden` | WARN | a behind card's word is over 45 % behind the speaker, or a stretch over 40 % of its width is hidden (measured by the render from the word's ink and the speaker's matte; `edit check` estimates it from the face) |
| `matte_flicker` | WARN | the speaker's cut-out under a behind card flickers: over 2 % of the speaker's area jumps on a still picture (the render's matte measure) |
| `player_chrome` | WARN (footage) | a thin bar across over half the width, low in the frame or in a recorded player, with small glyphs at both ends (play, time, fullscreen), in the same place on 2+ sampled frames: a web player's controls recorded with the page |
| `soft_footage` | WARN (footage) | edge sharpness (sum \|Laplacian\| / sum \|gradient\| per detailed 64 px cell, at delivery size) under 0.75 on 60 % of the detailed cells, on half the sampled frames: crisp screen text is ~1.5, a 2x upscale ~1.0, 3x ~0.7. Fix: re-record at 2x device scale |
| `caption_boxes` | WARN | two caption boxes stacked around one centre with widths differing by over 10 % (one box per line: the stepped look), on 2+ sampled frames. Fix: one plate (`captions --style boxed`) |
| `empty_borders` | WARN (footage) | a solid picture filling under 70 % of the frame (width x height) inside flat borders, on over 30 % (and 2+) of the sampled frames |
| `must_show` | FAIL | a must-show text is missing from the on-screen text list of the last `showtime check` |
| `must_show_unverified` | WARN | found only in the project source (run `showtime check`, then `qa` again) |
| `expect_invalid` | WARN | an unknown key in the `expect` block, or an unknown platform name (checked without a platform target) |
| `reference_copy` | FAIL | the render copies a style reference of its job: 25 % of sampled frames match reference frames, or 10 % with the same cut rhythm (`reference.md` section 3) |
| `reference_close` | WARN | 5 % or more of the sampled frames look like reference frames |
| `reference_credit` | WARN | "Style reference: ..." is missing from credits.txt or share.txt (`showtime reference credit <job>`) |
| `edit_choppy` | WARN (launch films) | more than 5 hard cuts in a film of up to 60 s |
| `too_many_scenes` | WARN (launch films) | more than 6 scenes or layouts in up to 60 s |
| `dead_hold` | WARN (launch films) | nothing moves for more than 5.5 s |
| `flat_music` | WARN (launch films without a voice) | the mix's loudness moves less than 3 dB (10th-90th percentile of 0.5 s windows) |
| `showreel_sparse` | WARN (showreel tone) | fewer than 12 shots per 15 s (scenes, layouts, hard cuts or the showreel shot count, whichever counts most; scaled to the length): a reel that cuts like a launch film loses its brief. The launch rules above do not apply in the showreel tone |
| `showreel_long_end` | WARN (showreel tone) | the end card holds still (0.25 s windows moving under 1 level) for more than 10% of the reel, or the last shot runs over 20%: the losing reels of the 2026-10-05 rematch held their name 2.5-3.5 s of 15. Land the name on the last beats with its reading time and keep it moving |
| `showreel_repeats` | WARN (showreel tone) | two shots of 0.4 s or more, not neighbours and not the end card, look alike: colour histogram distance under 0.3 and coarse layout correlation over 0.7 (the same ground, palette and composition: one technique twice) |
| `flash_risk` | WARN (every video) | more than 3 general flashes in any second: a frame-to-frame change of 0.1 or more in linear luminance over a quarter of the frame or more, the darker side under 0.8, a pair of opposing changes counted as one flash (the WCAG general flash threshold, measured on 256x144 frames). Fix: space strobes and glitch bursts 0.33 s apart, shrink them, or lower their contrast (`pacing.md` §5) |

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
come from the premium grammar in `workflows/launch-video.md`. In the showreel tone (showtime.json `"tone":
"showreel"`, the job's tone, or a brief that says showreel, demo reel, hype reel, go all out or show off;
`tones.md`) the launch rules are replaced by the showreel checks (`showreel_sparse`, `showreel_long_end`,
`showreel_repeats`; `lib/st/qa/reel.py` measures the shots, the end card's still hold, look-alike pairs and
energy dips into qa.json's `rhythm.reel`), and qa.json has a `showreel` block saying where the tone came from. Flashes (`flash_risk`) are judged on every video.

**Phone check** (the audience complaint: text moves too fast to read and is too small on a phone). One named
check, printed as one line by both tools:

```
phone check: PASS (smallest text 8.1 pt (minimum 5 pt for 16:9); every text held to its reading time at 17 characters/s or 3 words/s (en); nothing under platform UI; captions: 12 cues, longest line 34 characters, fastest 15 characters/s)
phone check: FAIL - type 4.1 pt "Terms apply" at 0:12.4; reading "Sign up today" 0.8s of 2.1s at 0:05.0; under platform UI "Link in bio" at 0:09.0
phone check: PARTIAL (captions: 12 cues, longest line 34 characters; type size, reading time and UI zones need `showtime check <project>` ...)
```

**Showreel flash words.** In the showreel tone only, a text marked `data-st-flash` (canvas: `{flash: true}`)
of at most 3 words and 24 characters, on screen at least 0.2 s, may leave before its reading time: `check` notes
it as `flash_text` instead of `short_text`, and the PASS line says "except N flash word(s) (showreel tone)". The
exemption is that narrow on purpose: an unmarked text, a longer marked line or a 1-frame blip is still
`short_text`; with no other text held its reading time (the hero line) `check` warns `no_hero_line`, a reading
part of the phone check; size, contrast, overlaps and platform UI zones are judged as always. Outside the tone the
mark changes nothing.

`showtime check` measures it before the render and writes the per-frame findings plus a `phone` block in
`report.json` (aspect, minimum, smallest texts, items with timestamps). `showtime qa` cannot read pixels back
into text, so it quotes that block (`work/check/report.json`) and says PARTIAL when there is none, when it ran at
another size, or when it is older than the project sources; captions are always judged on the sidecar files.
Parts:

| Part | Rule (finding codes) | Limit | Where the number comes from |
|---|---|---|---|
| Reading time | `short_text` | every text (not numbers alone, not `data-caption` text read along with the voice) is on screen for `0.3 s + max(characters / cps, words / wps)`, at least 1 s; per language in `runtime/thresholds.json` `reading`: default 17 characters/s and 3 words/s, `ja` 4 chars/s, `zh` 9, `ko` 12 (no words/s for languages written without spaces). The language is showtime.json `lang`, else `<html lang>`, else `en` | Checked against the published sources on 2026-09-29, no number changed. Netflix timed-text style guides, reading speed for adult programs: English 20 characters/s (17 for children's programs; [en-US](https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide)), Japanese 4 ([ja](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215767517-Japanese-Timed-Text-Style-Guide); 7 for SDH, no separate children's figure), Simplified Chinese 9 (7 for children's; [zh](https://partnerhelp.netflixstudios.com/hc/en-us/articles/215986007-Chinese-Simplified-Timed-Text-Style-Guide)), Korean 12 (9 for children's; [ko](https://partnerhelp.netflixstudios.com/hc/en-us/articles/216001127-Korean-Timed-Text-Style-Guide)). So `ja` 4, `zh` 9 and `ko` 12 are exactly the adult limits. The default 17 characters/s is the English children's limit, i.e. deliberately under the adult 20 (on-screen text is read while the picture also moves). 3 words/s = 180 words/min, the top of the BBC's 160-180 wpm recommendation (0.33-0.375 s per word, at least about 0.3 s per word on screen), quoted from the [BBC Subtitle Guidelines](https://www.bbc.co.uk/accessibility/forproducts/guides/subtitles/) as reproduced on [clevercast.com](https://www.clevercast.com/bbc-subtitling-guidelines/) (the BBC page itself could not be fetched when this was checked); it is about 76 % of the 238 wpm adults read silently (English non-fiction; 260 fiction, 183 aloud): [Brysbaert 2019, Journal of Memory and Language 109, 104047](https://doi.org/10.1016/j.jml.2019.104047) (open PDF: [gwern.net](https://gwern.net/doc/psychology/linguistics/2019-brysbaert.pdf)). Tune the file, not the code |
| Type size | `tiny_text` | on-screen size in points at phone width: `px x 390 / frame width` (an iPhone 14/15-class screen, the video filling its width in a feed). Minimum by aspect (`phone_min_pt`): 16:9 5 pt, 1:1 10 pt, 4:5 11 pt, 9:16 15 pt; `tiny_text_frac` (2.2 % of the frame height) stays as a second floor, so 1920x1080 needs 25 px, 1080x1920 42 px, 1080x1080 28 px, 1080x1350 31 px. Decor (`data-st-decor`, `{decor: true}`) is exempt. Judged on the median size over the text's life, so an entrance that starts small is not a small text; text under the minimum is one warning per text, grouped when there are many | calibrated on the shipped examples: their smallest 16:9 labels are 5.1-6.5 pt (26-33 px at 1080p), their vertical ones 15.6-15.9 pt, the square one 11.2 pt, so the minimums are the smallest sizes that let the examples pass. That is a floor, not a target: aim for typography.md's floors (36 px at 1080p = 7.3 pt, 48 px at 1080x1920 = 17.3 pt), and `small_text` notes still mark text under ~3.3 % |
| UI zones | `safe_zone`, `edge_margin`, `control_strip` | frames taller than wide (9:16, 4:5): text inside x 64-916, y 220-1440 at 1080x1920 (platforms.md §3, scaled); landscape and square: not within 3 % of an edge, and no small text in the bottom 8 % (player controls) | platforms.md §3, typography.md §6 |
| Captions | `caption_line_long`, `caption_fast`, `caption_flash`, `caption_lines`, `caption_bounds` (qa, on the sidecar) | at most 2 lines, 42 characters per line (32 vertical), 20 characters/s for cues of 3+ words, no cue under 0.4 s, inside the safe box (`st/captions_rules.py`, shared with the writers) | subtitle practice as above; the summary line quotes the cue count, the longest line and the fastest cue |

`--no-timeline` skips reading time (the line says so); type size and zones come from the sample frames then.
Burned-in captions that are drawn as page text (`data-caption`) get the type-size and zone checks like any text,
but not the reading-time rule (they follow the voice).

**Quality floor** (`st/qa/floor.py`). Four looks-cheap patterns that pass every technical check: the four
rows above from `player_chrome` on, measured on 3-10 frames sampled across the video (grey, at delivery size up to
1920 px wide). They are WARNs only, tuned to stay quiet on designed frames (a title on a flat ground, a divider
line, one caption plate); the thresholds are constants at the top of the file. `player_chrome`, `soft_footage`
and `empty_borders` run only when the video may hold footage (not for a project whose page plays no `<video>`),
and a padded export is judged inside its picture. `qa.json` `floor` has the counts.

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

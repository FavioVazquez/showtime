# Variety: the look history and style references

Read this when the user says "make it like this video", gives a reference clip, asks for something that
does not look like the last one, or `showtime check` reports `look_repeat`.

Audiences notice when every video from one tool looks the same. Two tools keep a job from repeating
itself or copying someone else: the look history (what your recent videos looked like) and style
references (another video's style, never its content).

## Essentials

- "Same style as this video": right after `job init`, `showtime reference <video> --job <job>`; read its
  `reference.md` brief, `sheet.jpg` and `shots.jpg`, not the video. The brief is the plan's look (§2)
- Carry over the style: its sampled colours, type sizes and margin (`style.css`), pace and beat runs, cut and
  wipe verbs, motion energy and sound shape. It overrides template, theme and workflow defaults (§2)
- Never the content: its words, logos, footage, shots rebuilt frame by frame, characters, music track. Subject,
  words and facts come from the user (§2)
- `showtime new <template> <dir> --job <job>` links `style.css` last; remove template decoration the reference
  lacks (gradients, glows, grids). Every text line at one of its type sizes, no smaller (§2)
- Sound: a new bed built like its shape (a kick on every beat: `ST.score` or `audio compose --bpm`), not
  another genre (§2)
- After the render: `showtime reference diff <job>` measures it like the reference and lists every KEEP item
  of the spec (cuts, shot lengths, moves and easing, palette, layout, beat, sound hits) as ok or OFF with
  frame numbers; fix the OFF lines or say why the change is deliberate (§2)
- No reference: before the storyboard run `showtime history` and pick a theme, type pair, primary transition,
  music shelf and structure the last five jobs did not use, unless the user or brand asks for continuity (§1)
- On `look_repeat` take an alternative or say which repeat you kept and why; a series keeps palette and type
  and varies the rest; a repeat that follows the job's style reference is intended (a note) (§1)
- Local files only (a URL only as a direct video link); ask for the file when given a page; never bypass a
  login or bot wall. Keep the "Style reference" credit (`showtime reference credit <job>`) (§2)
- A qa FAIL `reference_copy`: rebuild the listed shots from the user's own material (§3)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. The look history | 40-67 |
| 2. Style references ("make it like this") | 69-135 |
| 3. The near-copy guard | 137-160 |

## 1. The look history

Every job whose latest final passes `showtime qa` is recorded in `<SHOWTIME_HOME>/history/looks.json`:
template, theme, palette, type pair, transitions (by type, counted), camera moves, music (catalog id and
shelf, composed style, file), structure (scene count, lengths, shape), tone and brand kit. They are read
from the project files, `brand.json` and the audio mix; nothing is rendered or uploaded.

| Command | What it does |
|---|---|
| `showtime history` | the recent looks and what was used most in the last five |
| `showtime history check <project or job>` | repeats against the last five jobs, two alternatives each |
| `showtime history add <job>` | record a job now (qa does it on a passing final) |
| `showtime history clear [--job J]` | delete the file, or one job's entry |
| `showtime history off` / `on` | stop or resume recording (`SHOWTIME_HISTORY=off` does the same) |

**In the plan.** Without a style reference (§2 sets the look when there is one), before writing the
storyboard, run `showtime history` and pick a theme, type pair, primary
transition, music shelf and structure the last five jobs did not use, unless the user or the brand asks
for continuity. `showtime check` warns (`look_repeat`) when a project still repeats one, with two
alternatives per repeat drawn from what showtime has: runtime themes and their type pairs and palettes,
catalog transitions (launch films: only the launch-safe ones), camera verbs, catalog tracks from other
shelves within the use's energy, other structures and hooks (`story.md`), other tones (`tones.md`).

Rules of thumb:
- A series for one brand shares its palette and type on purpose: jobs with the same brand kit name are
  not flagged for those; vary the camera, transitions, structure and music instead.
- Template and tone repeats alone are notes, not warnings.
- The user's instructions win: a requested look is not a defect. Say which repeat you kept and why.

## 2. Style references ("make it like this")

`showtime reference <video> --job <job> [--for <seconds>]` measures the reference and writes
`<job>/references/<name>/`:
- `reference.md`: the brief for the storyboard, the grammar at a glance and a table of shots;
- `sheet.jpg` (1 frame per second) and `shots.jpg` (one frame per shot): read these instead of the video;
- `style.css`: the sampled palette (ground, ink, accent), side margin and type sizes as CSS tokens, with the
  theme tokens (`--bg`, `--fg`, `--accent`, `--safe-x`, `--grain`, `--glow`) set from them;
- `reference.json` (all numbers, with the `spec`) and `fingerprint.npz` (small grey frames for the near-copy
  guard).

**The spec.** The "Spec" section of `reference.md` (and `spec` in `reference.json`) is the reference in
frames: every scene change with its frame and kind (a wipe with its panel colour and direction), the shot
lengths in frames, the element moves inside shots (start frame, length, easing: the share of the move done by
its middle, from the frame-difference curve), the palette roles, alignment, margin and type sizes, the tempo
and every sound hit's frame. **KEEP** lists what a same-style video keeps; **CHANGE** what it never keeps
(words, subject and facts, logos, pictures and footage, the music track). `showtime reference diff <job>`
(or `<video> --against <reference folder>`) measures a render the same way and prints one line per KEEP item,
ok or OFF with frame numbers (`--json`; `--strict` exits 1 on an OFF line); a render of another length is
compared with the reference's times scaled to it.

What it measures: scene changes (hard cuts by ffmpeg scene detection, composition changes, and the
motion bursts of pushes and whips; cuts a beat apart stay separate, so a word-per-beat run shows as one),
shot lengths and their spread, pace (changes per 10 s), how scenes change (hard cut, colour panel wipe with
its colour and direction, fast handoff, continuous move), the palette sampled from the frames with its roles
and whether it is flat, brightness per shot, motion energy and the camera verb per shot (hold, push-in,
pull-back, pan, tilt, moving content), text lines with their alignment, margin and sizes (type found by its edges, each line's ink height:
cap height for capitals; no OCR), the loudness curve, silence share, tempo, cuts on the beat, and the sound's
build (a kick on the beats, an off-beat tick, low-end share, a last hit, silence at the end).

**The route for "same style as this".** 1. `job init`, then `showtime reference <video> --job <job>`.
2. Read the brief and `shots.jpg`; the plan's look is the brief (skip the look-history picks of §1).
3. `showtime new <template> <job>/project --duration <len> --job <job>`: it copies `style.css` into the project
as `reference-style.css`, links it last in `<head>` and sets the background to the reference's ground, so its
tokens win over the theme and the template (`--no-reference-style` skips it; an applied brand kit wins for
colours). 4. Rebuild the page in the reference's grammar: its structure and shot lengths scaled to your length,
its beat runs, its cut and wipe verbs, its alignment and margin, every text line at one of its type sizes (no
smaller body copy), and none of the template's decoration the reference lacks. Match the face by eye in
`shots.jpg` with an installed font (`showtime assets font <family>`). 5. Sound built like the reference's
(a kick on every beat at its tempo: a synth score, `references/synth-score.md`, or
`showtime audio compose --bpm <bpm>`), never another genre's bed and never its track. 6. check, render, qa.
7. `showtime reference diff <job>`: fix the OFF lines, or say which change is deliberate and why.

**Carry over the style:** pace and shot-length pattern, beat runs, how scenes hand off (mapped to showtime
transition names or a panel element), camera verbs, alignment, margin and type sizes, the palette (its
sampled colours: a same-style video keeps them), the shape of the sound. Use the brand's or the user's
colours instead only when there is a brand kit, the user asks, or the reference is another company's ad whose
colours are its brand. **Never the content:** its words, logos, footage, shots or compositions recreated
frame by frame, characters, its music track. The near-copy guard (§3) checks the render.

A word-per-beat run (one or two words per beat, one after another) is read as one line: `showtime check`
notes it (`beat_words`) instead of flagging each word as `short_text` when its words arrive no faster
than 3 per second.

Input: local files first. A URL works only as a direct link to a video file (the same downloader as asset
fetches); pages and streaming sites are not fetched, and showtime never bypasses a login or bot wall. Ask
the user for the file when they give a page link. The rights note in `reference.md` says this.

**Credit.** The command writes "Style reference: <title>" into the job's `credits.txt` and `share.txt`;
render keeps it (it moves into the description block when there is one). `--title` sets the name; `--no-credit`
skips it when the user credits it another way. `showtime reference credit <job>` restores it; qa warns
(`reference_credit`) when it is missing.

**The look history.** A job with a style reference follows it on purpose: `showtime check` and
`showtime history check` mark a repeat in template, theme, type, transitions, camera, structure or tone as
intended (a note, no alternatives), and a palette repeat too when the look uses the reference's colours.
Music repeats still count (a reference sets the sound's shape, not the track).

## 3. The near-copy guard

`showtime qa` compares the render with every reference of its job (`showtime reference check <job>` runs it
alone; `--against <folder or video>` for any pair):

- Frames: up to 48 frames of the render (2 per second, spread evenly), each 64x36 grey, against every
  reference frame at 4 per second. A frame is a near copy when its block SSIM (at 48x27, brightness and
  contrast normalised) is at least 0.80 and its
  64-bit difference hash differs in at most 12 bits, or its SSIM alone is at least 0.93. Flat frames
  (a plain ground) are not counted.
- Detail: when both videos are on disk, each frame the test above calls a near copy is confirmed at 256x144
  on the textured blocks only (flat ground says nothing), at the best of small zooms and shifts; it stays a
  copy at 0.65 or more. The same layout with other words scores about 0.3-0.45 (a same-style video passes);
  a re-encode, grade or small crop of the reference about 0.8-0.95.
- Rhythm: the render's scene-change positions against the reference's, as shares of each length; a cut counts
  when it lines up within 2 % (F1 score, 0 when the shot counts differ by more than a quarter).

| Result | When |
|---|---|
| FAIL `reference_copy` | 25 % or more of the counted frames are near copies, or 10 % or more while the rhythm similarity is 0.8 or more |
| WARN `reference_close` | 5 % or more of the counted frames are near copies |
| PASS | otherwise; the line notes a rhythm that follows the reference closely (0.9 or more): fine, rhythm is grammar |

Fix a FAIL by rebuilding the matching shots (qa lists their times) from the user's own material.

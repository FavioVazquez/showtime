# Workflow: social short (Reels, TikTok, Shorts, vertical clips)

Read this when the user wants a vertical or short-form video: a reel, a TikTok, a YouTube Short, a
9:16 clip, a vertical explainer, a cut-down of a longer video ("make a 15 s reel announcing v2", "a
vertical explainer with voice-over", "cut this into a TikTok").
Two starting points: **made from scratch** (the `short` template) or **cut from existing material**
(a longer render or real footage). Real talking-head footage, even for a reel: follow
`footage-edit.md` with the vertical settings below. An audiogram (podcast or interview audio with
animated captions) is the from-scratch path with the recording as the voice track (section below).

## Inputs

- The message (or the long video / footage to cut down), the platform, a length.
- Helpful: a voice-over script or a recording, brand kit, a hook idea.

## Defaults

9:16 at 1080x1920, 30 fps; 12-20 s; hook readable by 0.3 s and a first change by 2 s; 3-5 beats of one
idea each; karaoke captions (`clean-pop`; `bold-pop` for loud hype pieces) whenever there is speech; a loopable ending (the last frame
flows into the first); -14 LUFS; safe zones respected: nothing important in the bottom 25 % or the
right-hand 15 % (platform UI), captions hanging from 62 % height (they grow down, never past 75 %). Ask at most: the platform, only
when nothing hints at it and it changes length or safe zones. Voice-over: none unless the request
implies one; say so in the opening line.

## Steps (from scratch)

1. **Job.** `showtime job init <name>-short --goal "..." --platform reels` (or tiktok, shorts: qa then
   checks the aspect, length cap and loudness for it). The printed folder is `<job>`.
2. **Hook and beats.** Pick the hook (`story.md` section 3) and write 3-5 beats; the social-short
   structure is in `story.md` section 4. *Done when:* the first 2 s carry the whole promise.
3. **Project.** `showtime new short <job>/project --duration <len>` (the whole timeline, music and
   caption words scale to it; later changes: `showtime retime <job>/project -d <len>`). Replace the
   chat demo with the real content (captured 9:16 shots:
   `showtime site capture <url> <job>/work/capture --aspect 9:16`).
4. **Voice (if any).** Write `<job>/project/narration.md` with one `## <scene id>` heading per scene
   (the template's scenes are `hook`, `demo`, `close`; `voice.md` has the format), then:
   - `showtime voice script <job>/project/narration.md -o <job>/project/voice --fit <seconds>`:
     the length minus 0.3 s per narrated scene (the next step puts that much picture before each
     scene's first line) and minus any unnarrated end card; about `<len> - 1` for three scenes. The
     lines change speed together (0.85-1.15x), then pauses shrink; if it prints "cut about N words",
     cut them and rerun.
   - `showtime retime <job>/project --from-voice <job>/project/voice/timeline.json`: each scene
     becomes 0.3 s plus its lines' slots, each line is placed as its own voice track on its scene,
     the bed ducks under it, music sections, effects and the poster move with their scenes, and the
     caption layer reads `voice/captions.words.json`. Line ids that are not scene ids: match in order,
     or `--map hook=open,demo=demo`. `--dry-run` first shows the plan.
   Never edit `data-dur`, sections or effect times by hand from the slots. Without a voice, delete
   the caption layer or feed it on-screen words.
5. **First look.** `showtime check <job>/project` (reports safe-zone, short-text and still-hold problems at 9:16),
   `showtime snap <job>/project --every 1`, look, show it and carry on (quick mode does not wait).
   *Done when:* 0 errors, no safe-zone warnings.
6. **Final and verify.** Set `"poster"` to the strongest frame (Reels shows it as the cover), add
   `"expect": {"platform": "reels", "duration": <len>, "captions": true}`, then
   `showtime render <job>/project --job <job>` and `showtime qa <job>` (the latest final, checked
   against the job's platform; `--platform` overrides).
7. **Deliver.** `showtime deliver exports <the final qa checked> --targets reels,tiktok,shorts` when
   more than one platform is wanted; one-line share copy with one CTA; the delivery card.

## Audiogram (audio clip with captions)

1. `showtime transcribe <audio> --edit-dir <job>/edit` (`--speakers 2` for two voices), then
   `showtime pack <job>/edit` and pick the range `a`-`b` (15-60 s) from `takes_packed.md`.
2. Trim it (the footage editor needs a video stream, so use the mixer): write `<job>/work/clip.json`
   as `{"duration": <b-a>, "tracks": [{"kind": "voice", "file": "<audio>", "start": 0, "offset": <a>}]}`,
   run `showtime audio mix <job>/work/clip.json -o <job>/work/clip.wav`, then
   `showtime transcribe <job>/work/clip.wav --edit-dir <job>/work` so word times start at 0.
3. `showtime new short <job>/project --duration <b-a>`. Copy `clip.wav` and its transcript
   (`<job>/work/transcripts/clip.json`) into the project; point `caption-karaoke` at the transcript,
   add `clip.wav` as the `voice` track in `audio/mix.json` with `"duck": {"under": "voice"}` on the bed
   (or drop the bed), and show the speaker's name in a `lower-third` over their photo or the show's art.
4. First look, final and verify as in steps 5-7 above.

## Steps (cut-down of a longer video)

1. Decide what survives: the hook, the single strongest beat, the close (`platforms.md` section 6:
   60 s to 30 s to 15 s to 6 s, shortening from the middle).
2. From a showtime project: build a 9:16 variant (`--aspect 9:16` layouts re-flow; the dom and data
   templates pass check at 9:16), then `showtime retime <project> -d <len>` (scenes, poster and the
   bed's sections move together), render. Re-lay out, never just crop a 16:9 layout. Same length and
   edit, only another shape: no copy needed, `showtime check <project> --size 9:16`, then
   `showtime render <project> --job <job> --size 9:16` (writes `<job>/1080x1920.mp4`, a variant; qa it
   with `--platform reels`).
3. From a rendered 16:9 file with no project: `showtime deliver exports <video> --targets reels --fit blur`
   (whole frame on a blurred fill) or `--fit crop --focus 0.4`; check framing fast with `--preview`.
4. From footage: `showtime edit cut <transcript> --aspect 9:16 --captions bold-pop --keep-time <a-b>`
   (face-tracked reframe by default), preview, view, final (`footage-edit.md`).
5. `showtime qa <job>` (the job's platform, or `--platform reels|tiktok|shorts`), look at the sheet.

## Pitfalls

- A 16:9 layout cropped to 9:16: tiny type and cut-off UI. Re-lay out.
- Captions under the platform's buttons or description: keep them in the safe band; qa checks sidecars,
  check audits burned `data-caption` text.
- Emphasis on every term (`data-emphasis` with 9 words): the accent stops meaning anything. Pick the 3-5
  words that carry the message; one shows per card and `check` warns past that.
- A slow start: no logo sting, no fade from black, no "Introducing".
- Music that fades mid-phrase at the end: compose to the exact length; the composer ends on a hit.
- Emoji in captions: libass draws them with each OS's own font, so burned captions drop them by default.

## Read next

`references/story.md`, `references/platforms.md`, `references/components.md` (caption-karaoke),
`references/captions.md`, `references/typography.md`, `references/workflows/footage-edit.md`.

# Workflow: narrate an existing video

Read this when the picture already exists and only needs a voice: a silent screen recording, a
product clip, a finished animation, a video whose narration should be replaced ("add a voice-over to
this demo.mp4", "narrate this clip in a calm voice"). The picture is not re-edited; the voice is written
to fit it, then mixed over the original sound.

## Essentials

- Defaults: `af_heart` or `am_michael` at 1.0, original audio 12 dB lower (muted when it is clashing speech),
  narration from about 0.5 s to before the last second, captions as a sidecar, -14 LUFS final (§ Defaults)
- Look before writing: `showtime footage probe <video>`, `showtime footage scenes <video> --job <job>`; one line
  per shot at 2.5-3 words per second, never naming a thing before it appears (§ Steps)
- `showtime voice script <job>/narration.md -o <job>/voice`: every line inside its shot; shorten overruns, never
  speed a voice past 1.25x (§ Steps)
- EDL with one range (`volume_db` -12 or `"mute": true`) plus the voice track, `showtime edit check`, then
  `showtime edit render <job> --preview` and `showtime edit view <job>` to check sync (§ Steps)
- `showtime edit render <job> -o <job>/final.mp4`, `showtime qa <job>`, `showtime look <job>`; name the voice and
  its license in the delivery card (§ Steps)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inputs | 30-34 |
| Defaults | 36-42 |
| Steps | 44-77 |
| Pitfalls | 79-86 |
| Read next | 88-91 |

## Inputs

- The video file. Optionally a script, or notes on what to say.
- Helpful: the voice (gender, accent, tone), the language, whether the original sound stays (music,
  UI sounds) and how loud.

## Defaults

A local Kokoro voice (`af_heart` or `am_michael`; `voice list` for others) at speed 1.0, -16 LUFS voice
level before the mix; original audio kept 12 dB lower (or muted when it is speech that would clash);
narration starts about 0.5 s in and ends before the last second; captions as a sidecar; the final is
mastered to -14 LUFS. State the voice you picked and what happens to the original sound as
assumptions; ask only when the original is speech the user may want to keep.

## Steps

1. **Job.** `showtime job init <name>-vo --goal "..."`.
2. **Watch through images.** `showtime footage probe <video>` (length, audio tracks), then
   `showtime footage scenes <video> --job <job>` (a labelled sheet of every shot with its times) and look at it.
   If the video has speech, `showtime transcribe <video>` shows where it talks. *Done when:* you have a
   shot list with start/end times and what each shot shows.
3. **Write to the picture.** One line per shot or group of shots; each line must fit its window at about
   2.5-3 words per second (`pacing.md` section 6). Name things as they appear, never before. Save as
   `<job>/narration.md` with per-line `at` (when the line must start) and `fit` (its window in seconds)
   where timing matters (`voice.md` "Script → timeline → scenes").
4. **Voice.** `showtime voice script <job>/narration.md -o <job>/voice`. Read `voice/timeline.json`:
   every line's `start` and `end` must fall inside its shot. Fix overruns by shortening the line (best)
   or `fit`; never speed a voice past 1.25x. *Done when:* no line crosses into the next shot's topic.
5. **Mix onto the video** with an EDL (the picture is copied as one range):

   ```json
   {"sources": {"v": "../input.mp4"},
    "ranges": [{"source": "v", "start": 0, "end": 42.0, "volume_db": -12}],
    "audio": {"tracks": [{"kind": "voice", "id": "vo", "file": "../voice/vo.wav", "start": 0}]}}
   ```

   Save it as `<job>/edit/edl.json` (paths are relative to the EDL file, or absolute; use `"mute": true` instead of
   `volume_db` to drop the original sound, and `"audio": {"music": ...}` to add a bed).
   `showtime edit check <job>/edit/edl.json`, then `showtime edit render <job> --preview`.
6. **Check the sync.** `showtime edit view <job>` (the newest render; it prints which) shows frames, waveform and words
   together; or `showtime footage view <draft file> --transcript <job>/voice/vo.words.json
   --from <a> --to <b>` around the key lines. *Done when:* each named thing is on screen while it is said.
7. **Captions (optional).** `showtime captions <job>/voice/vo.words.json --style clean --size <WxH>
   -o <job>/edit/caps.ass --srt <job>/final.srt`; burn them with `"subtitles": "caps.ass"` in the EDL.
8. **Final and verify.** `showtime edit render <job> -o <job>/final.mp4`,
   `showtime qa <job>` (the latest final and the job's captions), `showtime look <job>`.
9. **Deliver.** The delivery card, including the voice used and its license (Kokoro voices are
   Apache-2.0; some Piper voices need a credit line, listed by `showtime voice list --json`).

## Pitfalls

- Writing the script before looking at the shots: the voice then describes things that are not there.
- Narration over on-screen speech: mute or strongly duck the original only where the new voice speaks,
  or split the range and set `volume_db` per range.
- Cramming: a line that needs 1.4x speed is a line that is too long.
- Re-encoding colour: a stream-copied source keeps its colour tags; qa warns when the source was not
  BT.709-tagged, which is the source's property, not an error you introduced.

## Read next

`references/voice.md`, `references/editing.md` (EDL fields), `references/footage-tools.md`,
`references/captions.md`, `references/sound-design.md`.

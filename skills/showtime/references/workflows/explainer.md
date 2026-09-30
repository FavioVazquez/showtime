# Workflow: explainer (canvas film, voice-over, procedural score)

Read this when the user wants something explained: how a product, idea, algorithm or process works
("explain how our sync engine works in 60 seconds", "a short video about why X matters"). The default
build is a canvas film drawn with `Film`, narrated with a local voice and scored with `Synth`, all
generated on this machine. For a feature tour of a real app use `tutorial.md`; for numbers use
`data-story.md`. When the subject is math itself (an equation, a proof, a function graph, a grid
transform, geometry), build it with Manim instead: `references/manim.md`.

## Essentials

- Defaults: 45-60 s, 16:9 at 1920x1080, 30 fps, `film` template, voice `af_heart` (state it as an
  assumption), 2.5-3 words per second. A 9:16 explainer: `showtime new short` and `social-short.md` (§ Defaults)
- Script first: one line per scene, 6-20 words, numbers and acronyms spelled out; on screen show the payload,
  never the narration word for word (§ Steps, § Pitfalls)
- `showtime new film <job>/project --title "..." --duration <target>`; `showtime voice script ... --fit
  <target>`; `showtime voice cues` into `voice/cues.js`; time reveals from `VO`, never type a time (§ Steps)
- Voice into `audio/mix.json` + `"audio"` in `showtime.json`, 10-20 dB above the music (§ Steps, § Pitfalls)
- `showtime check`, `showtime look`, show the user the script; `showtime render <job>/project --job <job>`,
  `showtime qa <job>` (§ Steps)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inputs | 31-34 |
| Defaults | 36-46 |
| Steps | 48-92 |
| Pitfalls | 94-104 |
| Read next | 106-109 |

## Inputs

- The subject: a repo, docs, an article, a diagram, or the user's own words.
- Helpful: audience (beginners or experts), length, where it plays, a brand kit, a preferred voice.

## Defaults

45-60 s, 16:9 at 1920x1080, 30 fps; `film` template with the `documentary` or `default` tone; voice
`af_heart` (or `am_michael`), 2.5-3 words per second; a quiet score that follows the story sections;
burned-in or sidecar captions from the narration's word timings. Ask at most: length/audience, only
when the request leaves it open. State the voice you picked as an assumption.

**Vertical (Reels, Shorts, TikTok, any 9:16 explainer):** the `film` template is drawn for 16:9 and
shows letterboxed at 9:16, so build it with `showtime new short` (DOM scenes, karaoke captions) and
follow `social-short.md`, whose voice step fits the script and sets the scenes from it. Keep this
file's steps 2-3 (subject and script); `film` works vertically only if you re-lay its drawing.

## Steps

1. **Job.** `showtime job init <topic>-explainer --goal "..."`; note `<job>`.
2. **Understand the subject.** Read the source until you can state the one mechanism that makes it
   work. Pick one explainer shape (concept, process, list, story; `story.md` section 4) and a visual
   spine from the subject's own world (the transplant test). *Done when:* the contract is in SHOWTIME.md.
3. **Script first.** Write narration as discrete cues, one line per scene, 6-20 words each, written for
   the ear (`story.md` section 5, `voice.md` "Writing for the ear"). Use the word budgets in `pacing.md`
   section 6 to size it to the length. Spell out numbers and acronyms for the voice.
4. **Project.** `showtime new film <job>/project --title "..." --duration <target>` (the cue table and
   score scale to the target).
5. **Voice.** Save the script as `<job>/project/narration.md` (one `## id` heading per scene), then
   `showtime voice script <job>/project/narration.md -o <job>/project/voice --fit <target>`. `--fit`
   lands the narration on the target: all lines change speed together (0.85-1.15x), then pauses
   shrink; if it is still long it prints "cut about N words": cut them from the script and rerun
   (a short script is padded with silence at the end). Check product names with
   `showtime voice ipa "<line>"` and add lexicon entries where the phonemes are wrong (`voice.md`
   "Pronunciation fixes"); rerun, and only changed lines re-synthesize. Read `voice/timeline.json`:
   each line's `slot.start` is its scene's cue. Run `showtime voice cues <job>/project/voice/timeline.json
   -o <job>/project/voice/cues.js`, load it before `cues.js`, and write cue times as
   `VO.lines.intro.start` or a word's time (`VO.words.intro[3][1]`) instead of numbers, so a re-voice or a
   translation re-times the film by running `voice cues` again. Draw each scene in `scenes.js`
   (`film-api.md`) and trigger each reveal at the `start` of the word that names it; never type a time
   the voice decides. If the narration's `duration` differs from the project's, run
   `showtime retime <job>/project -d <duration>` first, then write the cues.
   *Done when:* every storyboard row has a scene function timed from `timeline.json`.
6. **Sound.** Keep `score.js` sections on the same cues. Add the voice to the project's sound: create
   `audio/mix.json` with `{"kind": "voice", "file": "voice/vo.wav", "start": 0}` and set
   `"audio": "audio/mix.json"` in `showtime.json` (the score still plays; render combines both).
   Hold the score 10-20 dB under speech (the mix report's `voice_to_music_db`) with `m.level('music', ...)` at line starts
   (`synth-score.md` section 6). Check the music alone in seconds: `showtime score <job>/project`.
   *Done when:* section levels rise and fall with the story and none sits near silence by mistake.
7. **First look.** `showtime check <job>/project` (canvas text is audited through `Film.frameInfo()`),
   `showtime look <job>/project` (`looking.md`), and show it to the user together
   with the script, then carry on (quick mode does not wait; the script is the cheapest thing to
   change if they reply). *Done when:* 0 check errors, and the user has seen the script.
8. **Captions.** Burned-in on the canvas: `F.caption` driven by the same word times; then skip
   sidecars (for Reels and TikTok burned is enough; `showtime captions` says the files are optional
   when the video already burns captions). Sidecar only, or an extra `.srt` for YouTube, LinkedIn
   or X: `showtime captions <job>/project/voice/vo.words.json --style clean --aspect 16:9
   -o <job>/captions.ass --srt <job>/final.srt` (recorded as the job's captions).
9. **Final.** `"poster"` in `showtime.json`, then `showtime render <job>/project --job <job>`.
10. **Verify.** `showtime qa <job>` (the latest final, plus the job's captions); `showtime look <job>`.
    Quality mode (the default; lean: publish-bound only): review-pack and critic (`review.md`).
11. **Deliver.** Share copy (YouTube chapters if over 2 minutes), exports, the delivery card.

## Pitfalls

- On-screen text repeating the narration word for word. Show the payload (a number, a name, a diagram
  label); the voice carries the sentence.
- Scene lengths set by hand and then a voice that does not fit. Fit the voice to the target
  (`--fit`), take the scene times from `timeline.json`, and re-read it after any script change.
- A 9:16 request built on `film`: letterboxed. Use the `short` template (Defaults).
- A score competing with the voice: the voice should sit 10-20 dB above the music while speaking.
- Diagram labels too small at 1080p: check's small-text notes matter here (`typography.md`).
- Drawing symbols (⌘, arrows, ✓) inside normal text: the toolkit draws them as shapes; emoji must be
  images.

## Read next

`references/story.md`, `references/voice.md`, `references/film-api.md`, `references/synth-score.md`,
`references/pacing.md`, `references/captions.md`, `references/qa.md`.

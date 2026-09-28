# Vertical short (9:16): hook, chat demo, end card, karaoke captions from word timings

Files:
- `showtime.json`: 1080x1920 at 30 fps, `"audio": "audio/mix.json"`.
- `audio/mix.json`: a generated `synthwave` bed plus whoosh, bubble pops and checklist ticks on the
  cue times, mastered to -14 LUFS. Add your voice as a `voice` track and `"duck": {"under": "voice"}`
  on the music (`references/audio.md`).
- `index.html`: three scenes plus one caption layer (`data-st="caption-karaoke"`) that runs over
  everything. Layout keeps clear of short-form app UI: content in the top ~58 %, captions hanging
  from 62 % (two-line cards grow down, never past 75 %), nothing in the bottom 25 % or the right-hand 15 %.
- `words.json`: placeholder word timings for the script. Replace them with real ones:
  `showtime voice say "your script" -o voice/vo.wav` writes `voice/vo.words.json`; point the
  caption layer at it (`data-src="voice/vo.words.json"`), or run `showtime transcribe` on a
  recording. Any list of `{text, start, end}` works.

Caption styles (`data-style`): clean-pop (default for shorts: sentence case, heavy sans, spoken word
in the accent), bold-pop (all caps, outlined: loud, hype pieces), highlight-box, underline-sweep,
minimal, boxed-pill, fill. `data-emphasis="word,word"` colours the 3-5 key words of the video (one
shows per card); `data-position` = auto | top | center | lower | bottom.

Checklist cues (`data-cues`) are the times, local to the scene, of the words that name each item,
so the ticks land on the narration.

Aspect: made for 9:16 (passes `showtime check` with no warnings there). For a 16:9 or 1:1 cut, start from
`showtime new dom <dir> --aspect ...` instead; this layout's caption band and chat column assume a tall frame.

Commands: `showtime preview .`, `showtime check .`, `showtime render . --preview`, `showtime render .`

Length: `showtime new short <dir> --duration <s>` (or `showtime retime <dir> -d <s>` later) moves the whole timeline together: the three scenes' `data-dur`, the poster, the music sections, the sound effects and the caption word times in `words.json`. Longer cuts keep every animation's speed and hold each scene longer; shorter cuts scale everything. Then run `showtime check`: it fails with `dead_air` when the scenes end before the video does.

The length as shipped and after `--duration`/`retime` is `duration` in `showtime.json` (this README states no times, so it never goes stale).

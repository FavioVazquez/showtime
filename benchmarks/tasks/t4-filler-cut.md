# T4 · Cut fillers from a real talking clip

```json
{
  "id": "t4-filler-cut",
  "title": "Cut fillers from a talking clip",
  "prompt": "Cut the filler words and long pauses out of interview.mp4 and give me the tightened video.",
  "inputs": [{"fetch": "interview", "to": "interview.mp4"}],
  "deliverable": "video",
  "expect": {"duration": [40, 58], "aspect": ["16:9"], "audio": "required", "captions": null, "platform": null,
             "source_duration": 63.7, "footage": true},
  "facts": ["fixtures/media/interview.source.json"],
  "cap_minutes": 25
}
```

**Source:** a 63.7 s excerpt of a NASA Kennedy Space Center interview with STS-1 pilot Robert Crippen
(NASA media, public domain; exact URL, hash and trim in `fixtures/media/interview.source.json`; fetched by
`fixtures/fetch_fixtures.py`, not stored in git). Ground truth (in the same file): 5 "uh" fillers,
located by a word-level ASR pass over the whole source file, and two silent stretches of about 5.2 s (between
soundbites from 24.8 s, and at the end from 58.5 s), found with `silencedetect` (-35 dB, 0.5 s).

**Automatic checks specific to this task:** the output is transcribed with the same local model as the
excerpt and its content words are aligned to the excerpt's. A filler counts as removed when the span of words
around it got shorter by at least 60% of the filler's length (ASR alone is not trusted to transcribe "uh": on
the excerpt it folds them into neighbouring words). Also: content words kept in order (target 100%), extra
words, pauses over 1 s left, longest pause, clicks and silences from `showtime qa`. A reference cut that
removes exactly the known intervals scores 5/5 removed, 99.4% of words kept, 51.5 s.

**Expected failure, recorded honestly:** no arm is given a cloud API key. An arm whose shipped
transcription needs one either finds another way (allowed) or stops; stopping is scored as "no output".

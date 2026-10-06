# Rounds 5 and 6: go all out (a blind rematch on the round-1 showreel prompt)

**Status: run twice on 2026-10-05.** Round 5 lost (plain Opus first). After a density fix, round 6 won: the two
showtime takes ranked first and second and the plain winner third. Results at the end. The prompt is in
`r5-allout.prompt.txt`.

## Why

In round 1 (2026-10-02) the owner ranked five takes of one prompt blind. Plain Opus 5.5 (max) came first. Opus 5.5
(max) with showtime 0.3.x came second, very close behind. The winner was denser, with about 10 scenes in 15 s, a
liquid chrome shader, particles and glitch type. showtime's quality defaults pushed restraint and long reading
holds.

0.4.0 adds the showreel tone (`skills/showtime/references/tones.md`, "showreel"). The brief's own words turn it
on: "showreel" and "go all out" are both in this prompt. With the tone on:

- the agent aims for a dense reel: many short shots, a shader, particles, 3D, flash words and a hero line;
- `check` allows flash words;
- `qa` judges density, the ending and repeats instead of the launch grammar;
- the critic uses the showreel rubric.

The question: does Opus 5.5 with showtime 0.4.0 now beat the round-1 winner?

One measurement from round 1, stated here so the new vote can correct it: the round-1 finals were not
loudness-matched. The winner measures -12.9 LUFS integrated, the showtime takes -14.0 LUFS. That is 1.1 LU louder,
and in a blind A/B the louder take tends to sound better. All round-1 finals are 1920x1080 at 60 fps.

## What is compared

| Cell | What | Made how |
|---|---|---|
| `plain` | plain Opus 5.5 (max) with no video skill: round 1's take 2, the owner's #1 | reused, not re-run |
| `allout-1`, `allout-2` | Opus 5.5 (max) + showtime 0.4.0 | 2 new takes of the same prompt |

## Equal settings

- **Prompt:** exactly `r5-allout.prompt.txt`, byte for byte: the round-1 prompt, 153 bytes, no trailing newline.
  Nothing goes before or after it and there is no hint about the tone or the template: the point of the round is
  that the prompt's own words turn the mode on.
- **Agent and model:** the agent CLI round 1 used (Devin CLI) with the model round 1 used for "Opus 5.5 (max)"
  (`claude-opus-5-5-max`), permission mode `dangerous`, as in round 1.
- **Plugin:** showtime 0.4.0 at one recorded commit, installed for the agent from that checkout
  ([docs/agents.md](../../docs/agents.md), Devin). The agent's plugin info must print 0.4.0, and no other showtime
  (an older plugin or command on the PATH) may win.
- **Workspace:** one fresh, empty folder per take with no `CLAUDE.md`/`AGENTS.md` above it, trusted once with an
  interactive start (Devin refuses `-p` in untrusted folders); the same machine and tools for every take.
- **Running:** a new session per take (a resumed session carries context). Any question gets "your call", as in
  round 1. Caps: 60 min and $40 per take; a take that hits one is reported as capped.
- **Deliverable:** the take's final 15 s MP4, the last final the agent names; the 16:9 one if it made several.

What is recorded per take: cost and wall time; whether the tone came on (`qa.json` `"showreel": {"on": true,
"source": ...}`, "brief" or "project" when the agent used `showtime new showreel`; if it was off, the mode failed
the test whatever the vote); the `qa` verdict and loudness; whether a critic round ran.

## Normalize, then blind

Every candidate gets the same length, loudness and container; only the picture and the mix differ. Two-pass
loudnorm to -14 LUFS integrated:

```bash
for f in plain.mp4 allout-1.mp4 allout-2.mp4; do
  # pass 1: measure
  ffmpeg -hide_banner -i "$f" -t 15 -af loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json -f null - 2> "${f%.mp4}.ln.txt"
  # pass 2: apply with the measured_* values from pass 1; exactly 15.000 s; no metadata
  ffmpeg -hide_banner -y -i "$f" -t 15 -map_metadata -1 \
      -af "loudnorm=I=-14:TP=-1.5:LRA=11:measured_I=..:measured_TP=..:measured_LRA=..:measured_thresh=..:offset=..:linear=true" \
      -c:v libx264 -crf 16 -preset slow -pix_fmt yuv420p -c:a aac -b:a 192k -ar 48000 -movflags +faststart "norm/${f}"
done
```

- **Frame rate:** each take keeps its own fps (frame rate is part of the work). All takes in both rounds were 60 fps.
- **Check:** after normalizing, every file measures the same duration (±1 frame) and -14.0 ±0.3 LUFS.
- **Letters:** a seeded shuffle maps cells to `Video-A.mp4`, `Video-B.mp4`, `Video-C.mp4`; the key is kept away from
  the voter. File names, metadata and page names name no maker, model or tool.
- **Identity in the picture:** every take says "Devin, Motion Designer", because the prompt says "you". That is the
  same for every cell and is not edited out.

## The vote

The three videos go to the owner with letters only and one line: rank A, B, C from best to worst. No commentary
before the vote; the key is opened after the ranking is recorded.

- **Rule:** a showtime take is published only if it is ranked #1.
- **Tie:** if a showtime take ties for #1, ask once for a forced choice.

## Results

Both rounds ran these settings as written. The plain cell is round 1's #1, reused. Costs are list-price
equivalents of the token metrics in the agent's own session store (`showtime receipt` reads them), not the agent
vendor's bill.

### Round 5: lost

showtime 0.4.0 as first merged.

| Rank | Cell | Notes |
|---|---|---|
| 1 | `plain` | round 1's #1 |
| 2 | `allout-2` | tone on; qa PASS; capped at 61 min after delivering |
| 3 | `allout-1` | tone on (it started from `showtime new showreel`); qa PASS; about 49 min |

The owner: "all solid, C the worst". Measured on the frames: the winner cut 13-14 shots in 15 s and kept its name
moving through the last 1.8 s; the showtime takes cut 9-11 shots and held "DEVIN." still for 2.5-3.5 s, and the
template take repeated a look. Fixes before round 6: the showreel tone asks for 12-14 shots per 15 s, no technique
twice and an end card of about the name's reading time; `qa` warns `showreel_sparse`, `showreel_long_end` and
`showreel_repeats`; the critic counts holds, repeats and dips; the template was rebuilt to 14 shots. Separately, a
blank first frame after cuts was fixed (`ST.clips()` frame-exact times, `check` `late_first_frame`).

### Round 6: won

showtime 0.4.0 after the density fix, the same settings, two new takes.

| Rank | Cell | Wall time | Cost | Notes |
|---|---|---|---|---|
| 1 | `allout-1` | 60 min (delivered just inside the cap) | $26.23 | tone on (from `showtime new showreel`); qa PASS, 0 warnings; -14.0 LUFS; 60 fps; 3 finals, the last one used |
| 2 | `allout-2` | 49 min | $18.13 | tone on (project); qa PASS, 0 warnings; -14.0 LUFS; 60 fps; its own review round fixed an odometer glitch and a loudness jump |
| 3 | `plain` | (reused) | (round 1: $19.96) | round 1's #1 |

The rule is met: a showtime take ranked #1, and both showtime takes beat the round-1 winner.

**Limits:** one voter, the owner (showtime's author), who had seen the plain take in rounds 1 and 5, so the vote is
only partly blind; two showtime takes against one plain take; the plain take was made on 2026-10-02 and not re-run.
Both showtime takes picked the tone through the project (`showtime new showreel`, `"source": "project"`), not from
the brief alone. Treat it as an anecdote, not a result.

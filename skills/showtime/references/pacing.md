# Pacing: time budgets, rhythm and beat sync

Read this when you set how long text holds, how often to cut, how to sync to beats, how many words
narration can fit, or how long a format should run.

The pace comes from cuts and motion. It never comes from pulling text off the screen before it
can be read. The rule is **fast in, then hold**. Never fast in, then gone.

## 1. Readability timing (text on screen)

Hold time is counted from the moment the **whole line has settled**, not from when it starts to enter.
| Text | Minimum settled hold |
|---|---|
| Single word / short label (≤3 words) | 0.8 s |
| Headline (4–8 words) | `max(1.2, 0.3 × words)` s |
| Text with no voice carrying it | `max(1.0, 0.5 + chars / 13)` s |
| Number with a unit ("74% faster") | 1.2 s after the count-up lands |
| Anything the viewer must understand (a diagram, code, chart state) | 1.5–2.5 s |
| Logo / end card with URL | ≥2.5 s |

- The reading speed ceiling is about **3 words/s**, or ≤17 characters/s for captions.
- If text echoes the narration word for word, it can move at speech speed. If text adds information
  while the voice says something else, the viewer can follow neither. Don't do it.
- Words should never be animated faster than the text can be read. Per-letter effects only work on 1–2 word titles.
- Test: freeze on the frame where the text is fully settled. If you can't read it twice before it leaves, lengthen the hold.

## 2. Motion durations

| Motion | Duration |
|---|---|
| Micro UI (hover, tick, toggle) | 100–200 ms |
| Element entrance | 300–600 ms (house default 0.5 s, `expo-out`) |
| Exit | 20–30% shorter than the matching entrance |
| Scene-scale move or layout change | 500–800 ms |
| Camera push / drift | 1–4 s |
| Count-up | 0.8–1.5 s (short-form), up to 2.5 s for a hero number |
| Stagger between words or list items | 30–60 ms; letters 15–25 ms; the **whole group ≤ 0.5 s** (`stagger = min(0.06, 0.5 / count)`) |

- The first visible motion starts within 0.1–0.3 s of a scene's start, and the hero is visible by 0.5 s.
- After an element settles, hold ≥0.5 s (short-form) or ≥1.0 s (explainer) before the next change.
- The slowest scene should be about 3× slower than the fastest. Contrast is what makes speed feel fast.

## 3. Cut rhythm

Average shot length by genre:
| Genre | Shot length |
|---|---|
| Hype / teaser / chaotic | 0.5–1.5 s |
| Launch film | 1.5–3 s (feature shots 3–6 s) |
| Explainer | 3–6 s |
| Data story | 4–8 s per chart state |
| Tutorial | as long as the action needs, with a camera move every 5–8 s |
| Talking head | cut pauses over 0.35–0.5 s, keeping 0.1–0.15 s of breath |

- In short-form, **something changes every 2–4 s**: a cut, a camera move, new text or a state change.
  A static frame for over 4 s loses people unless it is a deliberate held beat.
- Vary shot lengths in patterns like short-short-long. Put the longest hold on the key message.
  Equal-length cards read as a template.
- Plan one deliberate **held beat** per video, where nothing moves for 1–2 s. Stillness after motion is powerful.
- Reveal content as the narration names it, weighted toward the second half of each scene.
  Showing everything in the first quarter and then freezing is the slideshow failure.
- Break the pattern about every 30 s in longer pieces (a new layout, a color flip, a silent beat).

## 4. Beat sync

Grid math: `beat = 60 / BPM` s, `bar = 4 beats`. At 120 BPM, a beat is 0.5 s and a bar is 2 s. At 30 fps, one frame is 33.3 ms.
- **Cut 1–2 frames before the beat** (33–66 ms at 30 fps). A picture change that slightly leads its
  sound reads as tight. One that lags reads as late.
- **Hard hits are instant.** Cuts, color flips and content swaps land on the frame, with no easing into a hit.
- **Moves that must land on a beat** (a wipe covering the frame, a count-up locking, a collision)
  start 40–190 ms early so they *arrive* on it. **Reactive moves** (a pop answering a snare) fire 0–45 ms after.
- Structure goes on downbeats (beat 1 of the bar) and energy on snares. Calm sections cut every 2 bars,
  builds every bar, drops every beat or half beat.
- Land the reveal and the logo on the strongest downbeat. Try 0.25–0.5 s of near-silence right before the drop.
- About 60–70% of events on the grid feels musical. 100% feels mechanical.
- **Readable text vs fast beats:** a readable message stays ≥1 beat, and a sentence ≥2 beats. Above
  ~110 BPM, snap text reveals to every other beat, or reveal and hold. Anything on screen shorter than
  a beat is texture, not a message.
- **Grid trust:** on calm, drumless music a beat tracker invents a metronome. If the detected onsets are
  sparse (more grid beats than real hits), pace by phrases and energy with long holds and dissolves, and
  never hard-cut on the invented grid. When the music is composed by `showtime audio compose`, the grid
  is exact by construction, so use it.
- Tension builders (count-ups, morphs, risers) resolve on a downbeat, never mid-bar.
- At most one camera move per phrase (4 bars), never one per beat.

## 5. Flash and strobe limits (safety, not taste)

- **No more than 3 flashes in any 1 s window.** A flash is a large, fast luminance swing, especially
  to or from white, or any saturated red flash.
- A flash frame is 1–2 frames, used at most 1–2 times per video.
- When flashing faster than 3/s is required by the concept, the flashing area must stay under 25% of the frame.
- Strobes, glitch bursts and rapid palette flips count as flashes. A strobe system runs ≤2–3 s at a time.

## 6. Narration word budgets

| Pace | Words/s | Use |
|---|---|---|
| Relaxed | 2.0 | Cinematic, documentary, accessibility |
| Natural (default) | 2.5 | Launch, explainer |
| Technical | 2.2 | Code, PRs, tutorials with dense visuals |
| Brisk | 3.0 | Social shorts, only when visuals are simple |

- Word budget = `duration × wps × 0.85`. The 15% slack is for silence, which is a feature.
  15 s ≈ 32 words, 30 s ≈ 64, 60 s ≈ 128, 90 s ≈ 190.
- Per scene: ≤19 words (≈9 s). Allow up to 26 words for at most two scenes, and split anything longer.
- The voice starts 0.3–0.6 s in (the hook visual goes first) and ends ≥1.0 s before the logo lands.
- **Real audio length wins.** After generating the voice, set scene durations from the measured clips,
  not from your estimate. Never stretch or squeeze the voice to fit a plan.
- Leave 0.2–0.4 s between spoken lines, and 0.6–1.0 s at section changes.

## 7. Durations by format

| Format | Length | Notes |
|---|---|---|
| Bumper / teaser | 6–15 s | One image, one line, logo |
| Social launch clip | 20–45 s | The sweet spot is 20–30 s |
| Vertical short | 15–45 s | Loopable ending; see `platforms.md` for caps |
| Hero launch film | 60–90 s | Hard cap 120 s |
| Feature walkthrough | 45–120 s | |
| Tutorial | 2–8 min | Chapters when over 2 min (≥3 chapters, each ≥10 s) |
| Explainer | 60–180 s | |
| PR / changelog | 30–90 s | About 150 words or fewer |
| Website hero loop | 6–20 s | Seamless loop, no audio |
| Logo sting | 2–5 s | |

Cut-downs keep the hook and the close and drop from the middle: 60 s → 30 s (hook + 2 features +
close) → 15 s (hook + 1 feature + close) → 6 s (one image, one line, logo).

## 8. Frame math

- Author times in seconds and quantize to frames: `t = round(t × fps) / fps`.
- Duration in frames = `round(duration × fps)`. Scene boundaries should land on whole frames.
- At 30 fps: 0.1 s = 3 frames, 0.5 s = 15, 1 s = 30. At 24 fps: 1 frame = 41.7 ms. At 60 fps: 16.7 ms.
- Visibility windows are half-open `[start, end)`. An animation that must be fully visible needs to finish at least one frame before its clip ends.

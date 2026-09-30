# Tones: presets and freeform direction

Read this when you pick the tone of a video or turn the user's words ("premium", "punchier",
"funny") into concrete choices.

A tone is a bundle of decisions: tempo, how much is on screen, how type behaves, how scenes
change, what it sounds like, and how color is treated. Pick one preset, then adjust it with the
user's words (section 3). Scene counts assume a ~20 s piece; scale them linearly for other lengths.
Easing names are CSS-style: `expo-out` = cubic-bezier(0.16,1,0.3,1), `std-out` = (0.2,0,0,1),
`in-out` = (0.65,0,0.35,1), `sine` = (0.37,0,0.63,1).

## Essentials

- Pick one preset, then adjust it with the user's words and say which changes you made. Scene counts assume a
  ~20 s piece; scale them linearly (§1, §3)
- Nothing specified: `default` (4–5 scenes of 3–5 s, `expo-out` entrances 0.4–0.6 s, hard cuts on beats with a
  blur-dissolve at section changes; launches `upbeat-tech`, explainers and data a calm underscore) (§1)
- No tone given: dev tool -> technical or default; consumer app -> playful; luxury, hardware -> polished or
  minimal; people's stories -> documentary; big launch, trailer, event -> cinematic (§2)
- Avoid the tone and look your last five videos used unless asked (`showtime history`) (§2)
- `playful` sound only when the user or the product asks for it: under anything serious it reads as a kids'
  game (§1)
- `polished`: no whooshes, claps, bells or plucked leads, no overshoot; `chaotic`: flash frames ≤2 per video,
  and legibility still wins (§1)
- Blends take pacing and sound from the first word and the look from the second; on conflicts the readability
  rules in `pacing.md` win (§3)
- Every tone: one primary transition for 60–70% of cuts plus at most 1–2 accent types; one sound family in the
  music's key; a "cheap" effect only in a parody, once or twice (§4)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. Presets | 38-139 |
| 2. Choosing a preset (when the user gave no tone) | 141-154 |
| 3. Freeform direction → knobs | 156-175 |
| 4. Invariants across every tone | 177-182 |

## 1. Presets

**default**: clear, confident, modern. Use it when nothing else is specified.
- Pacing: 4–5 scenes, 3–5 s each. One motion change every 2–3 s.
- Type: one grotesk sans, 700–800 display, tight tracking, one accent word per card.
- Motion: `expo-out` entrances 0.4–0.6 s, word stagger 40 ms.
- Transitions: hard cuts on beats, with a blur-dissolve (0.35 s) at section changes.
- Sound: mid-tempo bed at 105–120 BPM for launches (`upbeat-tech`); explainers and data use a calm
  underscore instead (`music.md` section 1). 2–4 soft UI cues, one impact on the reveal.
- Color: the brand palette as is, dark or light following the brand, 1.5% grain on gradients.

**polished**: premium, calm, expensive.
- Pacing: 3–4 scenes, 4–6 s each. Long holds and plenty of negative space (45–60% of the frame empty).
- Type: large, light-to-regular display (300–500) against one heavy word, or an editorial serif.
- Motion: slow push-ins (scale 1.00→1.05 over a shot), `in-out`/`sine`, 0.6–0.9 s entrances, no overshoot.
- Transitions: soft blur-dissolve 0.6–0.8 s, match cuts, shared-element moves.
- Sound: sparse piano, pads or soft pulse at 70–95 BPM (`underscore`, `minimal-pulse`, `ambient-pad`), or
  no music. 2–3 subtle cues. No whooshes, claps, bells or plucked leads.
- Color: restrained, with near-black or warm off-white grounds, one desaturated accent and a subtle vignette.

**playful**: warm, bouncy, human.
- Pacing: 5–6 scenes, 2–4 s each.
- Type: rounded or quirky display (a wide grotesk, or a handwritten annotation font for asides) at 800–900.
- Motion: springs with 10–20% bounce on shapes and stickers, never on paragraphs. Squash on landings, ±4–8° tilts.
- Transitions: pushes, iris wipes, shape morphs, pop-cuts.
- Sound: bright plucks, marimba or ukulele-style synth at 110–125 BPM, pops on 30–40% of entrances.
  Only when the user or the product asks for playful: under anything serious this reads as a kids'
  game or a cat video.
- Color: saturated brand color plus one complementary pop on light grounds, with a paper texture allowed.

**deadpan**: dry, understated, funny because it's serious.
- Pacing: 3–4 scenes, 4–7 s each. Uncomfortable pauses are part of the joke: a 0.8–1.5 s beat of stillness before the punchline.
- Type: plain, neutral sans or typewriter mono at modest sizes, placed with lots of empty frame. Never exclamation marks.
- Motion: almost none. Cuts and simple fades, with things appearing rather than animating.
- Transitions: very slow dissolves (0.8–1.0 s) or dry hard cuts.
- Sound: near silence, room tone, a single lonely tone, 1–2 cues total. The absence of music is funny.
- Color: flat, muted and slightly institutional (beige, office gray, fluorescent-light tint).

**chaotic**: loud, fast, meme-literate.
- Pacing: 6–8 scenes, many under 2 s, none over 4 s. Cuts on every beat during drops.
- Type: ALL CAPS condensed impact font, huge (60–80% of frame width), rotated stickers, stacked layers.
- Motion: zoom-cuts (scale 1.2→1.0 in 0.15 s), shakes 6–10 px decaying over 0.3 s, fast whips with blur.
- Transitions: hard cuts, flash frames (≤2 per video), zoom-throughs, glitch bursts under 0.2 s.
- Sound: 130–160 BPM, dense sfx on beats, bass hits, record scratches. Respect the flash limits in `pacing.md`.
- Color: clashing high-saturation pairs, inverted frames, halftone and grain. Legibility still wins.

**cinematic**: epic, emotional, big scale.
- Pacing: 4–5 scenes, 3–6 s. Build tension slowly, then land hard on the reveal.
- Type: huge display, either a wide-tracked serif or an extended sans, 1–3 words per card. Letterboxing (2.39:1 bars) is optional.
- Motion: slow camera drift, parallax depth layers, rack-focus blur, a scale 0.95→1.0 settle.
- Transitions: dip to black between acts, scale-dissolves, light-leak wipes used at most once.
- Sound: low drones, risers into impacts, orchestral hits or sub booms, 60–90 BPM or free time. 2–3 big cues.
- Color: graded look (teal/amber or cold steel), crushed-but-not-black shadows (lift to about 16 in 0–255), grain 2–3%, vignette.

**app-store**: feature-forward, clean, device-centric.
- Pacing: 4–6 feature cards, 3–4 s each, with the same layout rhythm repeated.
- Type: headline plus a one-line sub per card, bold sans, sentence case.
- Motion: device mockup with the real UI, taps with ripples, scroll moves, `std-out` 0.35–0.45 s.
- Transitions: consistent slide or push 0.35–0.45 s in one direction throughout.
- Sound: bright upbeat bed at 115–125 BPM, soft taps on interactions only.
- Color: brand-colored card grounds that rotate through 2–3 tints, pure device frames, soft shadows.

**documentary**: sincere, observational, human.
- Pacing: 4–6 scenes, 4–8 s. Let footage breathe, and put voice over real imagery.
- Type: small, precise lower-thirds and captions, a quiet serif or humanist sans, and a date/place slug in mono.
- Motion: slow Ken Burns on stills (scale 1.00→1.06 over 5–6 s), handheld-feel drift of 1–2 px.
- Transitions: straight cuts and J/L audio cuts, with dissolves only for time passing.
- Sound: room tone, soft piano or guitar, real ambience. No sfx stingers.
- Color: natural grade, gentle contrast, true skin tones, light grain.

**retro**: a nostalgic era (pick one explicitly: 70s film, 80s synth, 90s web, early-2000s gadget).
- Pacing: 4–6 scenes, 3–4 s.
- Type: an era-appropriate display (a chunky serif, chrome italic sans, a pixel font or a condensed grotesk).
- Motion: period moves, like stepped animation (12 fps holds), scanline wipes and wobbly film gate.
- Transitions: film burns, VHS tracking glitches, wipes that were in fashion then. Commit fully.
- Sound: the era's instruments (analog synth arpeggios, drum machine, lo-fi tape). Pitch wobble is allowed.
- Color: period palettes (faded warm film, magenta/cyan neon, web-safe primaries), heavy grain or scanlines.

**corporate-parody**: an earnest corporate video done straight, as satire.
- Pacing: 4–5 scenes, 3–5 s, overly tidy.
- Type: clean corporate sans, centered, with Title Case Taglines and a trademark symbol where it's funny.
- Motion: stock-style smooth slides, spinning 3D logo energy, lens flare exactly once.
- Transitions: the cheesy ones (star wipe, cube spin) used knowingly, once or twice. The joke lives in the contrast.
- Sound: uplifting stock-style bed with claps and a triumphant resolve on the logo.
- Color: corporate blue and swoosh gradients, sincerely overdone.

**minimal / keynote**: product as hero object.
- Pacing: 3–5 scenes, 3–5 s. One element per frame.
- Type: 1–3 words that fill 60–80% of the frame width. Nothing else on screen.
- Motion: slow, weighty (0.8–1.2 s `in-out`), with the product lit and rotating slightly.
- Transitions: cuts to black and match cuts.
- Sound: music-first, a single build and a button ending on the logo.
- Color: pure ground (near-black or near-white) with the product carrying all the color.

**technical**: for developers and engineers.
- Pacing: 4–6 scenes, 3–5 s. Real commands, real output.
- Type: monospace for code and output, a crisp sans for claims, grid-aligned layouts.
- Motion: typed commands (fast-forward long typing 2–4×), terminal output streaming, diff highlights.
- Transitions: hard cuts on beats, with a wipe along the grid.
- Sound: minimal electronic (`minimal-pulse`, 90–110 BPM; `upbeat-tech` for a launch), soft key clicks
  on typing (a few, not every key).
- Color: dark ground with visible 6% grid lines and one terminal-bright accent.

## 2. Choosing a preset (when the user gave no tone)

| Source signals | Tone |
|---|---|
| Dev tool, CLI, library, infra | technical, or default |
| Consumer app, game, kid or family product | playful |
| Absurd or joke product, side project with a funny name | deadpan or chaotic |
| Luxury, design, hardware, portfolio | polished or minimal |
| Mobile app store listing, feature tour | app-store |
| Nonprofit, research, story of people | documentary |
| Big launch, trailer, event | cinematic |
| A reference video to match | the tone `showtime reference` suggests from its pace and sound |

Avoid the tone and look your last five videos used unless asked (`showtime history`, `reference.md`).

## 3. Freeform direction → knobs

Translate the user's words into concrete changes and say which ones you made.
| They say | Change |
|---|---|
| "punchier", "faster", "tighter" | Shots −25%, cut on beats, drop the weakest scene, `expo-out` 0.3 s, more hard cuts |
| "calmer", "slower", "more breathing room" | Shots +30–50%, hold settled frames ≥1.5 s, dissolves, remove half the sfx |
| "more premium", "classier" | Fewer elements, more empty space, slower eases, no bounce, no whooshes, desaturate the accent 10–20% |
| "funnier" | Find the absurd true detail, play it straight, add a beat of stillness before the punchline |
| "more energy", "hype" | +15–25 BPM, shorter shots, a riser into the reveal, bigger type, one flash frame |
| "cleaner", "simpler" | One idea per frame, remove decorations, one font, one accent |
| "bolder" | Type +30% size and a heavier weight, higher contrast, a full-bleed accent-color scene |
| "warmer", "more human" | Warm neutrals, softer corners, acoustic instruments, a real face or hands if footage exists |
| "techier" | Mono accents, grid, terminal visuals, synth bed, precise hard cuts |
| "like a movie trailer" | cinematic preset, letterbox, dip-to-black act breaks, name lands last |
| "less corporate" | Kill stock-style gradients and centered layouts; use the product's own quirky copy |

Blends: "deadpan but cinematic" means take **pacing and sound** from the first word and **look** from
the second. If two instructions conflict (e.g. "chaotic but readable"), readability rules in
`pacing.md` still win. Keep the chaos in motion and sound, not in how long text is held.

## 4. Invariants across every tone

- Hook and readability rules from `story.md` and `pacing.md` apply to all tones.
- One primary transition covers 60–70% of cuts, plus at most 1–2 accent types.
- One sound family per video: the same whoosh, the same click, all in the music's key.
- A parody tone may use a "cheap" effect on purpose, once or twice, never by default.

# Typography for video

Read this when you choose fonts, sizes, spacing or text placement for a video.

Video type is read once, at a distance, on a phone, while it moves. Go bigger, use fewer words,
push the weight contrast harder and hold longer than you would on a web page.

## Essentials

- Fonts are local files loaded with `@font-face` (`showtime assets font <family>` for others); never
  `Helvetica`, `Arial`, `SF Pro`, `Segoe UI`, `Menlo` or `system-ui`; declare every weight and style (§1)
- Wait for fonts before frame 0 (`ST.waitFor(document.fonts.ready)` or `ST.ready()`); non-Latin text needs a
  family that covers the script (a Noto family) (§1)
- At most 2 families and 2-3 weights; extreme weight contrast (300 vs 800, 400 vs 900); give the display role
  to a face with character, not Inter (§2)
- Instrument Serif figures misread ("11" as "ll"): set numbers in the body sans with `tabular-nums` (§2)
- Floor (smallest readable size): 36 px at 1920x1080, 48 at 1080x1920, 40 at 1:1, 42 at 4:5; decorative
  metadata down to 60 % of it; body and labels x1.3 for landscape video watched in a feed (§3)
- The hero fills 60-80 % of the frame width; trust `showtime check`'s measured boxes, not the estimate (§3)
- At most 42 characters per line landscape, 18-20 vertical; captions 2 lines; 6 words per card (§3)
- Display tracking -2 % to -4 %; `tabular-nums` for counting numbers; sentence case; no italic emphasis (§4)
- Kinetic: by word or line (per-letter only for 1-2 word titles); entrances 0.4-0.6 s moving 16-40 px, scale
  from 0.96-0.98, never from 0; never shake or pulse readable text (§5)
- Animate only `transform`, `opacity`, `clip-path` and `filter`; no CSS centering transform on an element whose
  transform you animate (§5)
- Safe areas: 16:9 text inside the 90 % box (96 px sides, 54 px top and bottom), the bottom 16.7 % kept for
  captions; 9:16 box x 64-916, y 220-1440; square and 4:5 6 % margins (§6)
- Contrast at least 4.5:1 against the real composited pixels (3:1 for display text 48 px or more at 1080p);
  over footage one treatment per video (scrim, stroke plus shadow, or plate); move the text first (§7)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. Fonts: always files, never system names | 42-52 |
| 2. Pairings | 54-81 |
| 3. Sizes by format (px, at the render size) | 83-105 |
| 4. Spacing and settings | 107-117 |
| 5. Kinetic type rules | 119-133 |
| 6. Safe areas | 135-145 |
| 7. Contrast | 147-159 |

## 1. Fonts: always files, never system names

- Every font is a local file loaded with `@font-face` from the fonts folder that setup installs
  (`showtime paths` prints where it is). Fetch any other OFL family with `showtime assets font <family>`.
- Never write `Helvetica`, `Arial`, `SF Pro`, `Segoe UI`, `Menlo` or `system-ui` in a render. They differ
  per OS (a Windows or Linux machine renders a different video) and silently fall back.
- Wait for fonts before the first frame (`ST.waitFor(document.fonts.ready)`, or let `ST.ready()` do it). Declare
  every weight and style you use. A missing bold gets faux-bolded and looks cheap.
- Non-Latin text (CJK, Arabic, Devanagari, Cyrillic) needs a family that covers the script. Check
  before building, and fetch a Noto family for that script if needed.
- Brand fonts: use the brand's font if it is OFL/free and fetchable. Otherwise pick the closest OFL match and tell the user.

## 2. Pairings

The core set that setup installs covers these roles: Inter, Geist, Geist Mono, JetBrains Mono,
Instrument Serif, Anton, Bricolage Grotesque, Caveat. Families marked (fetch) come from `assets font`.
| Use | Display | Text / support |
|---|---|---|
| Product / SaaS default | Geist 700–800 | Geist Mono for labels, data, code |
| Dev tool launch | Bricolage Grotesque 800 | JetBrains Mono |
| Cinematic / editorial | Instrument Serif (italic for the accent word) | Inter 400–500 |
| Social short / captions | Anton or Bebas Neue (fetch), caps | Inter 600–800 |
| Data story | Fraunces (fetch) or Instrument Serif | IBM Plex Sans / Mono (fetch) |
| Playful | Bricolage Grotesque 800 (wide axis) | Caveat for handwritten asides |
| Technical / terminal | JetBrains Mono 700 | Geist 500 |
| Retro | Era-matched display (fetch, e.g. a chunky serif, pixel or chrome italic) | A neutral sans |

**Figures in display serifs.** Instrument Serif's "1" has no flag, so at display size "11" reads as
"ll" and "2015" as "20l5". Numbers in an editorial or data story (years, counts, the stat) go in a face
whose "1" is unmistakable: set the figures in the body sans (`font-family: var(--font-body)` on the
number's span, with `font-variant-numeric: tabular-nums` for anything that counts), or write the
number out in the headline. Check the stills at display size before the render.

Rules:
- Use at most 2 families and 2–3 weights per video. A third "annotation" face (handwriting) is allowed for asides only.
- Contrast should mean something: serif against sans, or sans against mono. Two similar grotesks side by side look like a mistake.
- Make weight contrast extreme (300 vs 800, or 400 vs 900). 400 vs 700 reads flat on video.
- Inter is a fine workhorse for body text, captions and UI, but it has no personality as the display face.
  Give the display role to a face with character unless the brand dictates otherwise.
- Match the register: statements in the display face, data and metadata in mono, quotes and attributions in the serif.

## 3. Sizes by format (px, at the render size)

| Format | Hero (1–3 words) | Headline | Body / sub | Label / data | Caption | Floor |
|---|---|---|---|---|---|---|
| 1920×1080 (16:9) | 140–240 | 80–120 | 40–56 | 28–36 | 44–56 | 36 |
| 1080×1920 (9:16) | 150–260 | 96–140 | 52–68 | 40–48 | 80–110 | 48 |
| 1080×1080 (1:1) | 120–200 | 80–110 | 44–56 | 32–40 | 64–84 | 40 |
| 1080×1350 (4:5) | 130–210 | 84–120 | 46–60 | 34–42 | 70–90 | 42 |
| 3840×2160 | ×2 the 1080p row | | | | | 72 |
| 1280×720 | ×0.67 the 1080p row | | | | | 24 |

- **Floor** = the smallest size for anything the viewer must read. Decorative metadata (coordinates,
  ghost words, tick labels) may go down to 60% of the floor.
- If a landscape video will be watched in a feed (X, LinkedIn, embedded in a post), multiply body and label sizes by 1.3.
- **On a phone the video is about 390 pt wide**, so points = px × 390 / frame width: the floor row is 7.3 pt for 1920×1080, 17.3 pt
  for 1080×1920, 14.4 pt for 1080×1080 and 15.2 pt for 1080×1350. `showtime check` fails the *phone check* below 5 pt (16:9), 10 pt
  (1:1), 11 pt (4:5) and 15 pt (9:16), the smallest sizes the shipped examples pass; treat the floor column as the size to aim for
  (qa.md, "Phone check").
- The hero should fill 60–80% of the frame width. The display element should be 3–6× the size of its nearest neighbor.
- Fit to width: `max_px = usable_width / (chars × ratio)`, where ratio ≈ 0.55 (regular sans), 0.62
  (bold caps sans), 0.42–0.45 (condensed caps like Anton/Bebas), 0.60 (mono), 0.50 (serif). Then
  measure the real box in the browser (`showtime check` reports overflow). Never trust the estimate alone.
- Line length: ≤42 characters per line landscape, ≤18–20 vertical, ≤2 lines for captions, ≤6 words per card.

## 4. Spacing and settings

- Display tracking −2% to −4% (`letter-spacing: -0.03em`). Body 0. All-caps labels +4% to +8%.
- Line height: display 0.92–1.05, body 1.3–1.45, captions 1.05–1.15.
- On dark grounds, drop body weight one step (500 → 400) and add +0.05 line height. Light text blooms on dark.
- Numbers: `font-variant-numeric: tabular-nums` for anything that counts or stacks, so digits don't jitter.
- Use sentence case by default. ALL CAPS only for condensed display faces, short labels and loud tones.
- No italics for emphasis. Emphasize with weight, color or scale, one at a time. Italic is for a single
  accent word in a serif, for quotes, or for foreign words.
- Code: turn ligatures off unless the brand uses them, show real syntax colors from the project's theme
  and highlight at build time, and show at most 12 lines at once at ≥32 px.

## 5. Kinetic type rules

1. One idea per card. Animate by word or line when the text must be read; per-letter effects only on 1–2 word titles.
2. Entrances: mask reveal (text rising from behind a clip edge) or blur-in (8→0 px + opacity) over
   0.4–0.6 s. Move 16–40 px, not 200. Scale from 0.96–0.98, never from 0.
3. Stick to one reading direction per video: enter from below or left, exit up or left.
4. Emphasis goes to one word per card (color or weight), and at most one emphasized word per 2–3 cards across the video.
5. Never shake, wobble, rainbow-cycle or continuously pulse readable text. Movement ends and then the text holds.
6. Animate `transform`, `opacity`, `clip-path` and `filter` only. Animating `font-size`, `letter-spacing` or
   width reflows the text and stutters. For a size change, use `scale`.
7. Don't put a CSS centering transform on an element whose transform you also animate. Center with
   flex or inset instead.
8. Count-ups ease out, land on a beat, and the label appears after the number lands.
9. Keep text crisp at rest. Motion blur is for the approach only; land sharp. `data-st-blur` does exactly that on a
   word that snaps in (smeared only on its fast frames), never on text that moves while it is read (stage-api.md).

## 6. Safe areas

**Landscape 16:9 (1920×1080):** keep all text inside the 90% title-safe box (96 px sides, 54 px
top and bottom). Keep essential brand content inside 80% for anything that may be cropped to other aspects.
When captions are present, nothing else goes in the bottom 16.7% (180 px + 20 px gap). YouTube end
screens cover the last 5–20 s, so keep the final end-card layout clear of the lower-right and center-bottom quadrant.
**Vertical 9:16 (1080×1920), universal organic box:** x 64 → 916, y 220 → 1440 (top 220, bottom 480,
left 64, right 164, where the action buttons sit). Hook text goes at y 300–700. Captions center on y 1150–1300.
Logo and CTA go at y 700–1200. For paid ads, use a stricter box: 14% top, 35% bottom, 6% sides.
**Square and 4:5:** 6% margin on all sides. A 9:16 video's profile-grid cover is cropped to the center
3:4 (1080×1440, y 240–1680), so keep cover text inside it.

## 7. Contrast

- Text against its actual background ≥ **4.5:1** (WCAG AA). Large display text (≥48 px at 1080p) may go to 3:1.
  Small text over moving footage should aim for ≥7:1.
- Measure against the real composited pixels behind the glyphs, not the CSS background color. `showtime check` does this.
- Over footage or busy UI, pick **one** treatment per video:
  - a scrim: a local gradient or plate under the text at 30–60% black, not a full-frame darkening
  - a stroke plus shadow: 6–8 px dark stroke and a 2–4 px soft shadow at caption sizes (vertical)
  - a plate: a rounded box behind the text (radius 12–16 px, padding 8/16 px, 55–70% opacity)
- Choose by the background's brightness under the text (0–255 luma): below 60, light text works as is;
  60–180 needs a scrim or stroke; above 180, use dark text or an opaque plate.
- Never place text over the busiest part of the frame. Move the text before you add a plate.
- Never rely on color alone to separate meaning (red/green): add weight, an icon or position.

# Color: palettes, contrast, banding, grading

Read this when you build a palette for a video, check text contrast, worry about banding in gradients,
or grade real footage.

Treat color like typography. Fewer choices, each doing one job, applied the same way everywhere.

## Essentials

- Declare the palette as CSS tokens before any scene: `--ground`, `--ink` (≥7:1 on the ground), `--muted`,
  `--accent` (one hue, ≤15 % of the frame), optional `--accent-2`, `--surface`; each hex written once (§1)
- Never pure `#000`/`#FFF` on large areas: near-black `#0B0B0D`–`#141416` or an off-white (§1)
- Brand: quote exact values, map by role, not frequency; an accent that fails contrast keeps hue and chroma,
  changes only OKLCH lightness, and you tell the user (§2)
- No brand: polarity by subject, OKLCH from one hue; avoid purple-to-blue gradients, neon cyan on black, gradient
  text, rainbow accents, glowing glassmorphism (§2)
- Contrast: body ≥4.5:1, large display ≥3:1, ink on ground ≥7:1, accent text ≥4.5:1, accent shape ≥3:1; never
  red vs green alone (§3)
- Saturated strokes ≥3 px at 1080p, small text on a neutral ground; chroma down 5–10 % on large red or magenta
  fields (§4)
- No full-screen linear gradient on a dark ground: solid ground + 1–2 radial glows (peak opacity ≤0.45) + seeded
  grain at 1.5–3 % (`ST.noise`/`ST.rand`) (§4)
- Never grade UI, logos, screenshots or brand colors; grade real footage only: correct, match, look at 40–70 %,
  protect skin, clean up (§5, §6)
- LUTs: only the generated ones (`showtime footage luts`), via `showtime footage grade` at 40–70 %; one look per
  video; never read a `.cube` file into context (§7)
- Checks: every hex in the token block, contrast on real pixels mid-transition too, no banding at 200 %, brand
  colors within about 2 levels in the MP4 (§8)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. Palette roles | 42-57 |
| 2. Palettes from the brand | 59-80 |
| 3. Contrast and color vision | 82-89 |
| 4. What video compression does to color | 91-104 |
| 5. UI and motion graphics: don't grade | 106-111 |
| 6. Grading real footage | 113-131 |
| 7. LUTs | 133-143 |
| 8. Checks | 145-151 |

## 1. Palette roles

Every video declares these as CSS custom properties before any scene is built:
| Role | Job | Rule |
|---|---|---|
| `--ground` | The main background of the video | Same ground across scenes, or two grounds that alternate deliberately |
| `--ink` | Primary text and marks | ≥7:1 against the ground |
| `--muted` | Secondary text, gridlines, inactive data | Ink at 45–65% (text), or 8–15% (lines) |
| `--accent` | The one color that means "look here" | One hue, used on ≤15% of the frame area |
| `--accent-2` | Optional second accent for a second meaning (e.g. "after" vs "before") | Only if the story needs two states |
| `--surface` | Cards and panels on the ground | Ground shifted 4–8% in lightness toward the ink |

- Never use pure `#000` or `#FFF` for large areas. Use near-black (`#0B0B0D`–`#141416`) and warm or cool
  off-white (`#F4F2EE`, `#F2F4F7`). Pure black crushes on phones, and pure white glares.
- Tint neutrals toward the accent: a blue accent gets slightly blue grays. It makes the palette feel designed.
- Write every hex once in the token block. A hex that appears anywhere else in a page is a bug.

## 2. Palettes from the brand

1. Collect the source's real colors: CSS custom properties, `theme-color`, button and link colors,
   logo pixels, hero image. Quote exact values and never round them.
2. Map them to roles by what they do on the site, not by frequency:
   - ground: the largest background area
   - ink: the darkest (or lightest, on a dark site) text color
   - accent: the main interactive color. It is never the browser-default link blue, and never a pure
     status red or green (those mean error and success).
3. If the brand accent fails contrast on the ground, keep its hue and chroma and change only its
   lightness (in OKLCH) until it passes. Tell the user you adjusted it.
4. Light brand on dark video, or the reverse, is allowed if the brand site does both. Otherwise keep the brand's polarity.

**No brand given:** choose polarity by subject. Dev tools, cinema, finance, music and night themes go dark.
Food, wellness, kids, education and editorial go light. Build the palette in OKLCH from one hue:
ground L 0.14–0.18 (dark) or 0.96–0.98 (light) with chroma ≤0.02; ink at the opposite end; accent
L 0.65–0.78 with chroma 0.14–0.22. Check that the accent survives both the ground and a white caption.
**Light is not boring.** Light grounds need bolder structure (2–4 px rules, full-saturation accent hits,
subtle paper grain) to feel cinematic. Don't flip to dark just to look premium.

Clichés to avoid unless the brand really uses them: a purple-to-blue gradient, neon cyan on black,
gradient text everywhere, rainbow accents and glowing glassmorphism. They read as generic AI output.

## 3. Contrast and color vision

- WCAG contrast ratio = `(L1 + 0.05) / (L2 + 0.05)` using relative luminance. Targets: body text ≥4.5:1,
  large display ≥3:1, ink on ground ≥7:1, accent as text ≥4.5:1, accent as a shape ≥3:1.
- About 1 in 12 men has red-green color vision deficiency. Never encode meaning in red vs green alone.
  Pair color with a label, a shape, an icon or position. Blue/orange is a safe contrast pair.
- In charts, the focus series gets the accent and everything else is gray at 30–40%. Label series
  directly instead of using a legend. Use ≤7 bars or ≤3 lines per frame in short-form.

## 4. What video compression does to color

- The renderer encodes BT.709 with correct tags and limited range. Don't fight it by pre-correcting colors in CSS.
- 4:2:0 chroma subsampling halves the color resolution. Thin (1–2 px) saturated lines and small
  red-on-blue text fringe and smear. Make saturated strokes ≥3 px at 1080p, and put small text on a neutral ground.
- Very saturated reds and magentas bloom after platform re-encode. Pull chroma down 5–10% for large fields.

**Banding** is the most common "cheap" tell:
- Large, smooth, dark gradients band after H.264 encoding, and worse after the platform re-encodes them.
- Never use a full-screen linear gradient on a dark ground. Use a solid ground plus 1–2 localized
  radial glows (peak opacity ≤0.45, radius larger than the frame's short side).
- Add animated monochrome grain at 1.5–3% opacity over any gradient or glow. Generate it per frame from
  a seeded noise function (`ST.noise`/`ST.rand`) so renders stay deterministic.
- For upload masters of flat motion graphics, use CRF 14–16 (see `platforms.md`). Grain plus a low CRF keeps gradients clean.

## 5. UI and motion graphics: don't grade

Design colors are the truth. Real UI, logos, screenshots and brand colors are shown as-is. No LUTs,
no tint, no filter on the product. Mood comes from the ground, light (glows, vignette) and motion,
not from shifting the brand's hues. The exceptions are tones that explicitly recolor (retro, chaotic)
applied to decorative layers, and a whole-frame grade only when the user asks for one.

## 6. Grading real footage

Grade camera, webcam, screen-recorded video with a face, and stock only. Work in this order:
1. **Correct.** Set exposure (skin highlights at about 65–75% brightness), white balance (neutral
   grays neutral) and contrast. Keep blacks at 16–20 in video range, because fully crushed black looks cheap on phones.
2. **Match.** Make shots in one sequence share white balance, brightness and saturation. A mismatched
   cut is worse than a plain grade.
3. **Look.** Apply a LUT or creative grade at 40–70% strength by blending the graded image over the corrected one.
4. **Protect skin.** Skin hue must stay natural: cooler shadows and warmer highlights are fine, a shifted midtone isn't.
   Saturation +5–10% maximum overall.
5. **Clean up.** Mild denoise for low light, mild sharpening for webcams, and nothing that creates halos.

Bounded adjustments for a natural result: exposure −0.06 to +0.14, contrast −0.05 to +0.08,
highlights −0.18 to −0.04, shadows +0.04 to +0.18, temperature −0.05 to +0.10, vibrance 0 to +0.06,
vignette 0 to 0.05, no grain. Exceed these only for a named stylized look, and then commit to it.

Feedback mapping: "too dark" or "flat" means lift the shadows and protect the highlights. Never add a retro
texture to fix it. "More premium" means cleaner whites, gentle contrast and restrained saturation, not a
cinematic LUT on the product. "Keep the brand colors exact" means change framing and motion only.

## 7. LUTs

- Use the LUTs that setup generates (`showtime footage luts` lists them). They are procedural and
  license-clean. Don't download "free LUT packs", because most have unclear provenance.
- Apply them with `showtime footage grade` at 40–70% strength and tetrahedral interpolation. Always compare an
  early, a middle and a late frame before and after.
- Never read a `.cube` file into context. It is tens of thousands of numbers. Check its name and size only.
- Only one look per video. Two LUTs stacked is a mistake.
- Looks by tone: cinematic gets teal/amber or cold steel; documentary gets clean and natural; retro gets
  warm faded film (lifted blacks, rolled-off whites); technical gets a cool, clean punch; polished gets a
  soft contrast punch with slightly warm whites.

## 8. Checks

- Every hex in the pages appears in the token block. Grep the project's HTML, CSS and JS for `#[0-9a-fA-F]{3,8}` and compare.
- There is one accent, and it is visible in every scene.
- Contrast passes on real pixels at every text moment, including mid-transition frames.
- No visible banding in the darkest gradient at the final encode. Look at a still frame zoomed to 200%.
- Brand colors in the final MP4 are within about 2 levels of the source values (sample a flat brand-color area).

# showtime brand

The identity is **Curtain Call**: a velvet curtain tied back to reveal a lit stage, the second before the
show starts. It says what showtime does (you describe it, the curtain opens, the video plays) without
film-reel or clapperboard clichés. Everything here is project-owned; see [LICENSE.md](LICENSE.md).

Machine-readable kit: [`brand.json`](brand.json) (the `showtime brand` format; point a project at it with
`SHOWTIME_BRAND=assets/brand/brand.json`).

## Contents

| Folder | What | Use it for |
|---|---|---|
| `logo/` | `mark-hero.svg`, `mark.svg`, `mark-small.svg`, mono marks, `wordmark*.svg`, lockups, `mono-black/white.svg`, `wordmark-terminal*.svg` | everything with a logo |
| `icon/` | `app-icon-{16…1024}.png`, `app-icon.svg`, `favicon.ico` (16/32/48), `favicon.svg`, `apple-touch-icon.png` (180), `maskable-icon-{192,512}.png` | app, site and plugin icons |
| `social/` | `github-social-preview.png` (1280x640), `og-image.png` (1200x630), `readme-header-dark.png` / `readme-header-light.png` (1600x400) | repo settings, link previews, README |
| `motion/` | `sting-poster.jpg`, `sound-logo.mp3`, `source/` (the showtime projects); the sting videos are release assets: [`sting.mp4`](https://github.com/FavioVazquez/showtime-examples/releases/download/examples-media-v1/_brand--sting.mp4) (1920x1080, 6 s), [`sting-square.mp4`](https://github.com/FavioVazquez/showtime-examples/releases/download/examples-media-v1/_brand--sting-square.mp4) (1080x1080) | video intros and outros, launch posts |

The CLI carries its own 1.8 s cut of the sound logo (the hit and its tail, -20 LUFS, mono WAV) at
`skills/showtime/lib/st/sounds/sound-logo-short.wav`, so a skill installed on its own still has it; it plays
only when `SHOWTIME_SOUND=1` (or the plugin's `sound` option) is on.

## The mark in three sizes

The silhouette is the same at every size: rounded tile, stage opening, spotlight pool. Detail is added or
removed around it.

| Variant | File | Use at | What it has |
|---|---|---|---|
| Hero | `logo/mark-hero.svg`, `icon/app-icon.svg` | 96 px and up | velvet folds with sheen, gathered drapes, pleated valance with a gold hem, volumetric beam with haze and dust, lit pool, gold tie-backs |
| Flat | `logo/mark.svg`, `icon/app-icon-flat.svg` | 40 to 96 px, print, embroidery, anything that needs flat colour | three flat colours plus the beam gradient; folds as simple strokes |
| Small | `logo/mark-small.svg`, `icon/favicon.svg` | below 40 px | tile, opening and pool only |

The shipped icon PNGs already follow this: 128 px and up use the hero, 48 to 96 px the flat mark, 16 and
32 px the small mark. One-colour versions: `mark-mono-black/white.svg`, `mark-small-mono-black/white.svg`.

## Wordmark

`showtime`, always lowercase, set in **Fraunces Black (900)** with -1% tracking and the font's own kerning.
The SVGs have the type converted to outlines, so no font is needed to use them. Its playbill warmth is
what separates showtime from terminal-styled developer tools; do not reset it in another typeface.

- Lockups: `lockup-horizontal.svg` (light grounds), `lockup-horizontal-on-dark.svg`, `lockup-stacked*.svg`.
  The `-flat` lockups use the flat mark; use them when the mark would render under 96 px.
- Terminal contexts (CLI banners, docs about the command line): `wordmark-terminal.svg` (cream, for dark
  terminals), `wordmark-terminal-light.svg`, `wordmark-terminal-mono.svg`, set in JetBrains Mono ExtraBold
  with the small mark. In a real terminal, print `showtime` in bold with the gold `#E9B949` (or the terminal's
  default foreground); never print velvet red text on a dark terminal (2.7:1).

## Colour

A theatre at night: velvet, one warm light, a dark house, a cream programme.

| Name | Hex | Role |
|---|---|---|
| Velvet | `#B3121F` | the brand colour: the flat tile, large fills, buttons with cream or white text, accent on light grounds |
| Velvet deep | `#6E0B16` | folds in the flat mark, pressed states, badge fills |
| Velvet shadow | `#3A0A0F` | shadows inside the hero mark only |
| Velvet sheen | `#D0413A` | highlights inside the hero mark only, never a fill on its own |
| Spotlight gold | `#E9B949` | the light: beam, pool, tie-backs, text accents and highlights on dark grounds |
| Stage | `#15100E` | dark ground (warm near-black) |
| Wings | `#231916` | raised surfaces on Stage |
| House cream | `#F5EBDC` | type on dark; the light ground |
| Programme | `#B6A795` | secondary text on dark |

Contrast (WCAG 2.x). Text needs 4.5:1 (3:1 at 24 px+ or 19 px bold), graphics 3:1.

| Pair | Ratio | Allowed |
|---|---|---|
| House cream on Stage | 16.0 | all text |
| Spotlight gold on Stage | 10.3 | all text |
| Programme on Stage | 8.1 | all text |
| House cream on Wings | 14.6 | all text |
| Velvet on House cream | 5.9 | all text |
| House cream on Velvet (and white on Velvet 7.0) | 5.9 | all text, button labels |
| Velvet deep on House cream | 10.3 | all text |
| Stage on Spotlight gold | 10.3 | all text (gold badges) |
| Spotlight gold on Velvet | 3.8 | large text and graphics only |
| Velvet on Stage | 2.7 | shapes only, never text or thin lines |
| Spotlight gold on House cream | 1.6 | never (no gold on cream) |

On dark grounds the mark keeps its edge through the gold pool and the dark opening inside the red tile, and
it stays recognisable at 16 px on white, cream, GitHub dark (`#0D1117`) and dark browser tabs. Where a red
edge is not enough (for example a red tile on a dark red photo), put the mark on a Stage or cream plate.

## Clear space and minimum size

- Clear space around the mark and lockups: at least **25% of the mark's height** on every side (the width of
  one tie-back plus its gap). Nothing else (text, edges, other logos) enters it.
- Minimum sizes: hero 96 px, flat mark 40 px, small mark 16 px; horizontal lockup 120 px wide (use the
  `-flat` lockup under 300 px wide); stacked lockup 80 px wide; wordmark alone 64 px wide.
- Print: flat mark 10 mm, lockup 30 mm wide.

## Don'ts

- Don't recolour the tile pink, orange or purple, and don't swap velvet and gold.
- Don't use the hero mark below 96 px or the small mark above 64 px.
- Don't stretch, rotate, outline, add drop shadows to, or put effects on the mark or wordmark.
- Don't set the wordmark in capitals, in another typeface, or with the mark on its right.
- Don't place the full-colour mark on busy photos or mid-tone reds; use a plate or the mono mark.
- Don't use gold for body text on light grounds, or velvet for text on dark grounds.
- Don't add a film reel, clapperboard or play triangle to the mark.

## Type

| Slot | Family | Weight | License | Install |
|---|---|---|---|---|
| Display / wordmark | Fraunces | 900 (Black) | SIL Open Font License 1.1 | `showtime assets font fraunces --weights 900` |
| Body / UI | Inter | 400, 600, 700 | SIL Open Font License 1.1 | `showtime assets font inter --weights 400,600,700` |
| Mono / terminal | JetBrains Mono | 500, 800 | SIL Open Font License 1.1 | `showtime assets font "JetBrains Mono" --weights 500,800` |

The fonts are not bundled here: every SVG has its text outlined. The OFL allows using the fonts in logos
and images; the font files themselves stay under the OFL.

## Motion and sound

**Sting** ([`sting.mp4`](https://github.com/FavioVazquez/showtime-examples/releases/download/examples-media-v1/_brand--sting.mp4), 6.0 s, 1920x1080 30 fps; [`sting-square.mp4`](https://github.com/FavioVazquez/showtime-examples/releases/download/examples-media-v1/_brand--sting-square.mp4),
1080x1080; both are assets of the showtime-examples media release, not in git). The frame
opens on a closed velvet curtain that fills the screen; letterbox bars close to 2.39:1 (1.85:1 in the square
cut). The house lights dim and the footlights rise (the anticipation), the curtain gives a small tug, then
parts to the tie-backs while the camera pulls back. The spotlight ignites with a flicker at 3.15 s; dust
turns in the beam and haze drifts through it. The camera pulls out of the stage until it is the logo tile,
the letterbox opens, and the wordmark rises into a wide overhead light with a gold glint passing across it.
Subtle film grain throughout. Made with showtime (`motion/source/`: HTML/SVG/canvas projects, rendered with
`showtime render`; mix in `audio/mix.json`).

**Sound logo** (`motion/sound-logo.mp3`, 4.0 s, in D, mastered to -14 LUFS / -1 dBTP): a low
tonal swell with a reversed cymbal rises into an orchestral hit (cinematic impact, brass-like braam and a
chord stab) at 1.25 s, then a three-note motif resolves to D with a shimmer tail. The sting uses the same
elements, with the hit on the spotlight (3.15 s) and the motif on the wordmark (4.66 s). Every sound is
synthesised by showtime's own effects engine (`showtime audio sfx`), so there are no third-party samples.

Use the sting as an intro or outro, full length or from 4.3 s (logo only). Keep it at its mastered level.

## Rebuilding

The sting projects render with `showtime render motion/source/sting-wide -o <somewhere>/sting.mp4` (render
outside the repo so no `work/` folder lands here). The static assets were generated from the Curtain Call
geometry by a build script kept with the design files, not in the repository.

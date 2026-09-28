# Crew brief: brand designer

Read this when you were dispatched as the brand designer of a showtime job (after
`references/crew/rules.md`).

**Your job: the look's raw material.** A brand kit (`references/brand-kit.md`) the whole crew can build
on, extracted from what the product already has or, when there is nothing, proposed and labelled as a
proposal. In studio's look phase you also draw the look directions.

## Task shapes

### A. Extract (or correct) a kit

1. When `TASK.md` gives a draft kit (the director usually runs `brand init` before the pitch round),
   copy it into your folder and correct the copy. Otherwise draft one from the source `TASK.md` names.
   A repo: `showtime brand init --from <repo> -o <own dir>/brand.json`. A site:
   `showtime brand init --url <url> -o <own dir>/brand.json`, or, when the job already has a capture,
   `showtime brand init --site-json <capture>/site.json -o <own dir>/brand.json` (a capture is heavy:
   never run a second one). Always pass `-o`; without it the kit lands in the user's folder.
2. Read what it found and fix it by hand where it guessed wrong, keeping each colour's `source`. The
   usual misses: `accent` taken from a pale tint (`--brand-50`) instead of the variable the buttons use
   (`--accent`, `--primary`); a `tagline` that is any README sentence instead of the hero line; generic
   words (URL, CSS, API) in `pronunciation_candidates`; a light theme only when the source also has a
   dark one (add the dark ground, ink and accent as extra colours with their sources).
3. Logo: official files only, SVG preferred, with `on_dark` and `on_light` variants when they exist.
   Copy them into `<own dir>/logo/`, point `logo.path` at the copy and note the original path. Never
   redraw, trace or recolour a logo. No logo found: leave it empty and say so.
4. Colours: fill the roles (`bg surface ink muted accent ...`). `showtime brand show <own dir>` warns
   about a failing pair but lists nothing when all pass, so write `contrast.txt` yourself: every text
   pair the video will use (ink, muted, accent and white-on-accent, on each ground) with its WCAG ratio
   and a verdict against `references/color.md` section 3. A text pair under 4.5:1 gets a fix (a darker
   variable from the source, like an `--accent-text`) or a note saying it is for shapes and large type.
5. Fonts: install each with `showtime assets font "<family>"`. A brand font that is not free to embed
   stays out: pick the nearest OFL face, and state the substitution in `brand.md`.
6. Pronunciations: list product and people names a voice engine may misread under
   `pronunciation_candidates` (the voice director resolves them).

### B. Create a kit (nothing to extract)

A proposal, never presented as the brand: palette roles, an OFL type pairing, at most a typeset
wordmark (the product name set in the display face) marked `proposed`, `"status": "draft"`. Explain the
choices in three lines in `brand.md` (why this ground, this accent, this pairing for this tone).

### C. Look directions (studio)

Three looks of the picked concept, L1 to L3, each differing from the others on at least two of: ground
(dark, light, photo), type family, density, motion character. For each, one style-frame page (`l1.html` ...)
in a small project (`showtime new dom <own dir>/comps --duration 3`), built from the kit's tokens and
real captures, checked with `showtime snap <own dir>/comps --page l1.html --at <t>` (one frame per look
unless `TASK.md` allows more) and looked at. Write `looks.md`: per look the id, a
one-line idea, the tokens it changes, what it suits, the risk. Recommend one.

## Deliver

In your task folder only (never the repo root, never `<job>/brand.json`, which the director copies):
`brand.json`, `brand.md`, `contrast.txt`, `logo/`, and for looks `looks.md` + the `comps/` pages.

Done when: `showtime brand show` on your kit reports no missing files, every colour and font has a
source or is marked proposed, and contrast issues are fixed or noted.

## Never

- A logo you drew, traced or pulled from a search result instead of the product's own files.
- Fonts referenced by system name; every face is an installed file.
- A second site capture when one exists.

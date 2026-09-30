# Workflow: slideshow (photos or screenshots with music)

Read this when the user has a set of still images and wants a video: an event recap, a portfolio, a
"year in photos", a product screenshot reel, a memorial or celebration ("make a video from these 30
photos with music"). The build is a `dom` project: one scene per image with a slow move (`ken-burns`),
transitions, optional captions, and a music bed whose downbeats time the changes.

## Essentials

- Defaults: 2.5-4 s per image, `ken-burns` zoom 1.08-1.12 toward the subject (≤ 1.12 on small images), one
  transition style, a bed composed to the exact length; state mood and order (§ Defaults)
- `showtime assets sheet <folder> --sort date -o <job>/work/sheet.jpg` first; drop near-duplicates, order into
  an arc (§ Steps)
- `showtime new dom <job>/project --duration <total>`, one scene per image;
  `showtime audio compose --style acoustic-folk --dur <total>`; scene starts on downbeats (§ Steps)
- `showtime snap <job>/project --every 2` for bad crops; render with `--job <job>`, then `showtime qa <job>`
  (§ Steps)
- Never add names or captions you were not given (§ Pitfalls)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inputs | 29-32 |
| Defaults | 34-41 |
| Steps | 43-68 |
| Pitfalls | 70-77 |
| Read next | 79-82 |

## Inputs

- The images (a folder), in the order the user wants or with a rule (date, filename).
- Helpful: a title and closing line, captions per photo, the mood, the platform, a song the user owns.

## Defaults

2.5-4 s per image (longer for images with text, shorter for energetic edits; total = images × hold);
16:9 (9:16 for social, which crops wide photos: use `focus` per image); gentle `ken-burns` zoom 1.08-1.12
towards the subject; crossfade or `push` transitions, one style throughout; `acoustic-folk`,
`piano-emotional` or `lofi-chill` bed composed to the exact length; title card and end card of 2.5 s.
State the mood you read from the photos and the order you chose (date taken, else file name) as
assumptions; ask only when the order is genuinely unclear and matters (a story, a memorial).

## Steps

1. **Job.** `showtime job init <name>-slideshow --goal "..."`. The printed folder is `<job>`.
2. **Look at the images.** `showtime assets sheet <folder> --sort date -o <job>/work/sheet.jpg` puts
   every image on one numbered grid (EXIF rotation applied, sizes as displayed; clips show a frame and
   their length) with badges for `low-res` (long side under 1280 px) and `~N` (looks like item N: a
   burst or duplicate); `sheet.json` beside it lists size, orientation and date taken. Read the sheet,
   then open single images only where you need detail: faces (the `focus` point), text inside
   screenshots, blur. Drop near-duplicates, keep low-res images small or short. Order them into a
   small arc (start strong, build, end on the best image).
   *Done when:* an ordered list with a hold time and focus point per image is in SHOWTIME.md.
3. **Project.** `showtime new dom <job>/project --title "..." --duration <total>` (later length
   changes: `showtime retime <job>/project -d <total>`). Copy the images into
   `<job>/project/media/`. Replace the scenes with one
   `<section class="scene" data-start data-dur>` per image containing
   `<div data-st="ken-burns" data-src="media/01.jpg" data-focus="[40,35]" data-zoom="1.1">`, plus
   `data-transition` on each incoming scene (`showtime motion transitions --energy calm`).
4. **Music.** Compose to the total length with section markers on your act changes:
   `showtime audio compose --style acoustic-folk --dur <total> -o <job>/project/audio/bed.wav`,
   then move each scene start to the nearest downbeat in `bed.beats.json` (bars for calm edits, beats
   for fast ones). With the user's own song: `showtime audio beats <song>` and `showtime audio fit
   <song> --dur <total>`. Point `audio/mix.json` at the bed.
5. **First look.** `showtime check <job>/project`, `showtime snap <job>/project --every 2`, look for bad
   crops (faces cut off at 9:16) and images that are too dark or low resolution for the frame.
6. **Final, verify, deliver.** Poster on the best image; `showtime render <job>/project --job <job>`;
   `showtime qa <job>` (the latest final); share copy; the delivery card.

## Pitfalls

- Every image the same move: vary direction and focus, keep the speed constant.
- Zooming into a low-resolution photo past its pixels: keep zoom ≤ 1.12 on small images.
- Text-heavy screenshots flashing by: hold them 1 s longer per line of text, or zoom to the part that matters.
- Photos of people: use them as the user provided; do not add names or captions you were not given.
- Stock or web images the user did not supply: only CC0/public domain via `showtime assets media search`,
  with credits when required.

## Read next

`references/components.md` (ken-burns, end-card), `references/transitions.md`, `references/music.md`,
`references/pacing.md`, `references/assets.md`.

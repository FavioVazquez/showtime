# Assets: fonts, icons, emoji, stock photos and video, cutouts, credits

Read this when a video needs a typeface, an icon, an emoji, a background photo or clip, a subject
cut out of its background, or a credits file. Every asset is fetched without API keys, cached under
`~/.showtime/assets`, and written with a `<file>.license.json` sidecar so credits are automatic.
For material from the product itself (screens, logos, copy) read `references/capture.md`.

## 1. License policy (applies to every command)

| Class | Licenses | Used by default? |
|---|---|---|
| free | CC0, Public Domain / PDM, NASA media, OFL-1.1, MIT, ISC, Apache-2.0, BSD, Unlicense, UFL | yes, no credit needed |
| attribution | CC BY 2.0-4.0 | only with `--allow-attribution`; a credit line is written |
| share-alike | CC BY-SA | only with `--allow-share-alike` (the video inherits the license) |
| excluded | anything NC (non-commercial) or ND (no derivatives), unknown | never |

Never fetched at all: sources whose terms forbid automated downloads (for example some
illustration libraries), proprietary emoji sets, key-only stock sites, scraped Lottie marketplaces.
If the user supplies such files themselves, they are responsible for the license; keep a note.

Credits: `showtime assets credits <project>` compiles every attribution-required sidecar under the
project into `CREDITS.txt` (nothing is written when nothing needs credit). `media fetch --project`
and `emoji --project` append their credit line immediately. `showtime render` merges the project's
credits with the mix's into `credits.txt` beside the final (`<stem>.credits.txt` for other names);
that is the file that ships and that qa looks for. Put the credits in the video description, and in
an end card when the license asks for it.

`credits --all` also lists the free items, but only files that have a sidecar: fonts, the voice and a
composed score have none. For a full credits page (a README, a description) add those lines by hand:
the voice (engine and voice id, e.g. Kokoro `af_heart`), the font families and their license (from
`~/.showtime/assets/fonts/<id>/font.json`), and the SoundFont a composed bed used (`soundfont_file` in
`mix.report.json`), with the license its own file states.

## 2. Fonts

```
showtime assets font "Space Grotesk"                        # 400 + 700, latin: TTF + WOFF2 + variable WOFF2
showtime assets font inter --weights all --subsets latin,latin-ext
showtime assets font anton --copy-to ./my-video/fonts       # portable copy inside the project; prints the <link> and CSS lines
showtime assets font inter --path --weight 700              # print a TTF path (installs if missing)
showtime assets fonts                                       # installed families
showtime assets fonts --search grotesk                      # search ~2,000 families
```

Files land in `~/.showtime/assets/fonts/<id>/` with `font.css` (relative `@font-face` rules),
`font.json` (manifest), `LICENSE.txt` and a sidecar. Versions are pinned to the catalog version,
so re-installs are byte-identical. Static TTFs get consistent internal names on install (family +
Regular/Bold, or "<Family> SemiBold" style names for other weights), so libass, Pillow and ffmpeg pick
the weight you ask for; `--path --weight N` also installs the 400 and 700 cuts beside N.

Where each format goes:

- **HTML pages**: link the copied `font.css` (`<link rel="stylesheet" href="fonts/inter/font.css">`)
  or, while rendering through the showtime server, `/_assets/fonts/<id>/font.css`. The variable
  WOFF2 covers every weight. Wait for `document.fonts.ready` (the stage does).
- **Captions (libass)**: TTF files through `fontsdir=` + `Fontname=`; libass ignores WOFF2 and
  silently falls back to a system font. The captions tools look in `~/.showtime/assets/fonts`.
- **ffmpeg drawtext / PIL**: pass the TTF path from `--path`.
- Never rely on system font names; a render must look the same on every machine.

Starting pairings: Inter + Geist Mono (product), Instrument Serif + Inter (cinematic), Anton or
Bebas Neue + Inter (short-form captions), Bricolage Grotesque + JetBrains Mono (developer launch),
Fraunces + IBM Plex Sans (data story). Several of these are also preinstalled for the runtime
themes (see `references/typography.md`).

## 3. Icons

```
showtime assets icon lucide rocket --color "#a78bfa" --size 128
showtime assets icon phosphor chart-line-up --variant duotone -o scene/chart.svg
showtime assets icon tabler brand-github --variant filled --png --size 512
showtime assets icon simple-icons github --color brand          # the brand's own colour
showtime assets icons deploy                                     # search names and tags
```

| Set | License | Variants | Look |
|---|---|---|---|
| lucide (default choice) | ISC | - | 24 px stroke icons; animate well as draw-on strokes |
| phosphor | MIT | regular, thin, light, bold, fill, duotone | friendly, many weights |
| tabler | MIT | outline, filled | 5,000+ stroke icons |
| heroicons | MIT | outline, solid, mini, micro | Tailwind look (fetched from jsDelivr) |
| simple-icons | CC0 (trademarks apply) | - | 3,400+ brand logos; only to depict that brand |

Icons come from the pinned npm packages installed by setup (offline), with the same versions on
jsDelivr as a fallback. `--png` renders with headless Chrome (transparent background). Stroke icons
can be drawn on over time: set `stroke-dasharray` to the path length and animate
`stroke-dashoffset` from the length to 0 as a function of `t`.

## 4. Emoji

```
showtime assets emoji 🚀                                  # Noto 2D SVG (default)
showtime assets emoji rocket --set fluent-3d --size 256   # glossy 3D PNG
showtime assets emoji "thumbs up" --set fluent --skin medium --format png
showtime assets emojis party                              # search names/keywords
```

Sets without attribution: `noto` (SVG/PNG), `noto-3d` (PNG), `fluent` (colour SVG), `fluent-flat`
(SVG), `fluent-3d` (PNG 256). `twemoji` (CC BY) needs `--allow-attribution`; `openmoji`
(CC BY-SA) needs `--allow-share-alike`. Input can be the emoji, its CLDR name ("red heart"), a
keyword, or code points (`1f680`, `U+1F680`). Fluent has no flags; use Noto for those.
Use images, not emoji fonts, in renders: fonts differ per OS. In HTML pages this is automatic: the
stage swaps text emoji for `/_st/emoji/<codepoints>.svg`, served from the sets installed here (install
each emoji once; `showtime check` names any that are missing).

## 5. Stock photos and video (CC0 / public domain)

```
showtime assets media search "mountain sunrise" --preview sheet.jpg     # look at the sheet, pick by number
showtime assets media search "ocean waves" --type video --limit 6
showtime assets media search "great wave" --source met,cma --orientation landscape
showtime assets media fetch openverse:<id> --project ./my-video         # -> my-video/assets/media/
showtime assets media fetch nasa:<id> --quality medium -o plates/earth.mp4
showtime assets media fetch commons:<pageid> --max-size 1920 --project ./my-video   # Commons' 1920 px rendition
showtime assets media fetch https://pubs.usgs.gov/.../fig3.jpg --license public-domain \
    --source-page https://pubs.usgs.gov/... --author "USGS" --project ./my-video   # any URL, license vouched
showtime assets media search "iss interview" --type video --source nasa --max-duration 300 --max-mb 800
showtime assets media search "saturn" --source nasa --min-size 1920 --details
```

| Source | Media | License handling |
|---|---|---|
| openverse | images | `cc0,pdm` filter (anonymous limit ~20 requests/min) |
| commons | images, video | structured CC0 / public-domain statements; license re-read per file |
| nasa | images, video | public domain; no endorsement; never use NASA logos or insignia. Third-party work inside an item (citizen-processed JunoCam images, ESA/Hubble frames, a credited photographer) is read from the author and description: a CC BY credit becomes an attribution item, NC or an unclear notice leaves it out (the search says how many), and the notice is printed and kept in the sidecar |
| cma | images (artworks) | Cleveland Museum of Art open access, CC0 |
| met | images (artworks) | only objects marked public domain |
| aic (opt-in) | images (artworks) | CC0, but its image server may answer scripts with a bot check, which showtime does not bypass |

Search results are numbered and remembered, so `fetch <id>` works later without searching again.
Each result prints its full id on its own line (copy it into `fetch`), then licence, size, length and
file size. NASA results get size, length and file size from their metadata (automatic for video and
with `--min-size`/`--max-duration`/`--max-mb`; `--details` for images); these describe the original,
and NASA's `large` rendition is at most 1920 px wide, so use `--quality orig` for more headroom
(ken-burns at 1080p wants 1.3x). Each quality is cached separately.
Downloads are cached in `~/.showtime/assets/media/<source>/`; `--project` copies the file (plus its
sidecar) into the project.

Commons images always come as a standard thumbnail step, never a random one: 3840 px by default
(`--max-size 1920` for less, `--max-size 0` or `--quality orig` for the original), and only when the
original is wider. The fetch says which rendition it used and the sidecar records it (`rendition`,
`original_url`). Thumbnails are also the polite path: the originals server rate-limits scripts (HTTP 429
for minutes after a few originals). Every fetch waits for a server's `Retry-After` up to 60 s and
otherwise fails with the time to wait. Commons' "Author" field is copied as written there; the fetch
reminds you to check it against the primary source (for a figure from a paper it can name an editor).

A file no search source covers (a public-domain government PDF, a USGS photo) can be fetched by URL
with the license you read on its page: `fetch <url> --license public-domain --source-page <page>`
(plus `--title`, `--author`). The sidecar records the license as given by you, so credits, render and
qa treat it like any other asset. A host that refuses unknown agents gets one retry with a
browser-like agent that still names showtime. Always look at the preview sheet or the file before using it: public
domain does not mean on-brand. Recommended order for b-roll and backgrounds: Openverse, then
Commons, then NASA, then museum collections. Keep people who are recognisable out of ads unless the
source says releases exist.

Procedural alternatives need no license at all: gradients, grain, noise fields and shader
backgrounds from the runtime (see `references/components.md`, `references/film-api.md`).

## 6. Contact sheets of a folder

```
showtime assets sheet ./photos --sort date -o work/photos-sheet.jpg   # one numbered grid of every image or clip
showtime assets sheet "shots/*.png" --labels name                     # globs work on every OS (quote them)
showtime assets sheet ./trip -r --per-page 48 --json                  # sub-folders, bigger pages, JSON report
```

One image per page (`--per-page`, default 36; more pages are `sheet-p2.jpg` ...) with every item
numbered. EXIF rotation is applied, so sizes and orientation are as displayed; HEIC and clips are
read with ffmpeg (a clip shows one frame and its length). Badges: `low-res` (long side under
1280 px), `~N` (looks like item N: a burst or duplicate), `clip m:ss`. `<sheet>.json` beside it lists
size, orientation, date taken and flags per item. Never overwrites without `--overwrite` (a repeat
writes `sheet-2.jpg`); the default is `showtime-out/<folder>-sheet-<time>/sheet.jpg`. Use it before a
slideshow or whenever the user hands over a folder of images.

## 7. Cutouts (background removal)

```
showtime assets cutout product.jpg                      # -> product.cutout.png (RGBA)
showtime assets cutout photo.jpg --crop --pad 24 --mask photo.mask.png
showtime assets cutout art.jpg --engine rembg --model birefnet-general-lite
```

Engines: `vision` (macOS 14+, built in, about 0.2 s, no download) and `rembg` (Windows, Linux,
older macOS, or when Vision finds no subject). rembg is installed into the showtime venv on first
use (a one-line notice; constrained to the pinned lock file) and its model is downloaded once to
`~/.showtime/models/rembg`: `isnet-general-use` (default, 170 MB), `u2netp` (5 MB, rough),
`birefnet-general-lite` (220 MB, most robust, slow). Stills only. A picture without a clear
subject (a landscape) reports "no subject found" instead of producing an empty cutout. The PNG's
long side is capped at 2048 px by default (a 3655 px cut-out was 4.5-5 MB; a 1080p page never shows
more): `--max-size 1800` for smaller, `--max-size 0` for the full resolution. The mask matches the
PNG's size.

## 8. Where things live

```
~/.showtime/assets/fonts/<id>/        font files, font.css, font.json, LICENSE.txt
~/.showtime/assets/icons/<set>/       styled SVG/PNG icons
~/.showtime/assets/emoji/<set>/       emoji images
~/.showtime/assets/media/<source>/     fetched photos and clips
~/.showtime/cache/http/               cached API responses (catalogs, searches; used offline)
```

Every file has `<file>.license.json`: source, id, title, author, license, license_url,
landing_url, file_url, sha256, attribution_required, credit. `SHOWTIME_OFFLINE=1` stops all
network access (cached assets keep working). Set `SHOWTIME_CONTACT` (an email or URL) to add a
contact to the User-Agent, which some public APIs appreciate.

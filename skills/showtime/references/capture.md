# Capturing real material: code repos, websites, documents, bot walls

Read this when a video is about a real product or document: a code repository on disk, a running app,
a public website, or a PDF (paper, report, deck). It covers what to inspect in a repo, how to show the real UI, `showtime site`
(capture / component / record), what the outputs contain, and the bot-wall policy. For scripted
click-through recordings read `references/tutorial-recording.md`; for fonts, icons and stock
media read `references/assets.md`.

## 1. The rule: real material first

A video about a product should show that product. Prefer, in this order:

1. **The running app**, driven by a demo script (`showtime demo record`) or captured page by page
   (`showtime site capture http://localhost:3000`; a static folder: `showtime site capture --serve <dir>`).
2. **The real components**, served from the repo and screenshotted or embedded (section 3).
3. **The public website**, captured with `showtime site capture <url>`.
4. Only then a recreation in HTML, built from the extracted tokens (colours, fonts, radii) so it
   still looks like the product.

Never invent numbers, quotes, customer names or features. Copy that appears in the video comes
from the README, the site, or the user.

## 2. Inspecting a code repository

Read in this order and stop when you know enough to plan the video:

| Look at | To learn |
|---|---|
| `README*`, docs landing page | what it is, the one-line pitch, the headline claim, install command |
| `package.json` / `pyproject.toml` / `Cargo.toml` | name, description, scripts (`dev`, `start`, `build`), framework |
| `index.html`, `app/layout.*`, `pages/_app.*`, `src/main.*` | the shell, `<title>`, fonts loaded, global CSS |
| global CSS, `tailwind.config.*`, `theme.*`, `tokens.*`, CSS custom properties | brand colours, radii, shadows, type scale |
| font imports (`@fontsource/*`, `next/font`, Google Fonts links, `@font-face`) | exact families and weights |
| routes (`app/`, `pages/`, `src/routes/`, router config) | which screens exist; pick the 2-4 that tell the story |
| key components (hero, dashboard, editor, pricing, empty states) | what to show and zoom into |
| `public/`, `assets/`, `static/` | logo (SVG preferred), favicons, product images, OG image |
| CHANGELOG / release notes | what is new (launch and update videos) |
| examples, tests, fixtures, seed data | realistic demo data for recordings |

Answer before planning: what is it, who is it for, the most impressive true claim, the visual hook,
which real UI to show, the user flow worth showing (entry, key action, result), shortest satisfying
length, tone.

**Nothing secret leaves this step.** Skip `.env*`, key files, `secrets/`, credentials and anything
gitignored. Do not put internal hostnames, tokens, real customer names or emails into a plan,
frame or caption; use fictional stand-ins and say so.

Fonts: when the repo loads an open font (Inter, Geist, anything on Google Fonts / Fontsource),
install the same family as files: `showtime assets font "<family>" --copy-to <project>/fonts`. It
prints the `<link rel="stylesheet" href="fonts/<id>/font.css">` line for the page and the
`--font-display` / `--font-body` values for `:root`. Commercial fonts cannot be fetched; pick the
closest open family and mention the substitution. A system stack (`system-ui`, `-apple-system`,
`ui-sans-serif`) looks different on every OS: use Inter (or Geist) and say so; `inventory.md` notes
it when the page uses only a system stack.

## 3. Reusing real components by serving the app

The most faithful footage is the app itself:

- **Start its dev server** the way the README says (`npm run dev`, `pnpm dev`, `python -m ...`).
  Run it in the background, wait for the port, then capture `http://localhost:<port>`.
- **Static builds and site folders** (`dist/`, `build/`, `out/`, a folder with an `index.html`)
  need no server of their own: `showtime site capture --serve ./dist` (also `site record` and
  `site component`; `--page /pricing.html` opens another page) and
  `showtime demo record script.mjs --serve ./dist` serve the folder on 127.0.0.1 with a plain static
  server and stop it when done. A folder path given as the `<url>` is served the same way. Avoid
  `file://` URLs: links starting with `/` break there (capture warns and suggests `--serve`).
- **Never capture through `showtime server` or `showtime preview`**: they wrap pages in the preview
  player. Landing on it (any `/_st/` page) or on a directory listing makes the command exit 1 with
  "wrong page" (`--force` overrides). Check that the title capture prints is the product's.
- **Isolate one component**: if the repo has Storybook / Ladle / a playground, capture that URL;
  otherwise capture the page and crop with `showtime site component <url> "<selector>"`.
- **Seed the state**: log in with test fixtures, load example data, set the dark theme; a demo
  script can do all of that before its first `demo.wait()`.
- **Embed live UI** in an HTML composition only when it is static (no network, no timers), or
  record it and use the frames: pages driven by real time are not frame-exact.

## 4. `showtime site capture <url> [outdir]`

One command turns a URL (or `--serve <dir>`) into a data folder. In a job, pass
`<job>/work/capture`; the default is `./showtime-out/<name>-site-<time>/`, where `<name>` is the host
without `www.`, `localhost-<port>` for a local server, or the served folder's name (`dist`, `build`,
`public`, `out` become `<parent>-dist` and so on). The folder and the page title are printed at the end.

| Output | What it is |
|---|---|
| `inventory.md` | start here: files, brand summary, copy, CTAs, testimonials, numbers, warnings |
| `contact-sheet.jpg` | every screenshot on one image; look at it before opening single files |
| `assets-sheet.jpg` | downloaded logos and images on one image |
| `site.json` | everything extracted (below) |
| `shots/<aspect>/scroll-NNN.png` | viewport screenshots top to bottom, 30% overlap; `scroll-000` is the hero |
| `sections/NN-<heading>.png` | one element screenshot per page section (hero, features, pricing...) |
| `full/tile-NN.jpg`, `full/plate.jpg` | full-page tiles at capture DPR; the plate is the whole page at 1x |
| `dark/` | dark-theme shots (only when the site has a dark theme, or `--dark on`) |
| `assets/{logos,images,videos}/`, `assets/og-image.*` | downloaded media, size-capped |
| `visible-text.txt` | the page text (for narration and fact checks) |

`site.json` holds: `meta` (title, description, og/twitter tags, theme colour, icons), `headings`,
`copy` (paragraphs with their section heading), `ctas` (text, href, colours, radius, `primary`),
`testimonials` (text, author, avatar), `stats` ("40s", "12k+", "99.9%" with labels), `nav`,
`tokens` (CSS custom properties, colour variables, radii, shadows), `colors.roles`
(background, text, primary, onPrimary, accent, surface, themeColor) and `colors.palette` (by
visual weight, with roles), `fonts` (loaded faces, per-role family/weight/size), `sections`,
`images`/`videos` found, `assets` downloaded, `layout.libraries` (three, gsap, lottie, framer...).

Useful options: `--aspect 16:9,9:16,1:1` (portrait uses a phone layout: 390 CSS px, touch, DPR 3),
`--dark auto|on|off`, `--max-shots N`, `--no-assets`, `--budget MB`, `--no-full`, `--format jpg`,
`--timeout S`, `--json` (summary for scripts). Exit code 3 means blocked (section 6).

What happens, in order: load (DOMContentLoaded, then load, then network idle, with a retry without
GPU/WebGL if the page hangs); cookie banners are handled by DuckDuckGo's autoconsent rules
(always the privacy-preserving opt-out) plus a fallback that clicks "reject/close" inside consent
containers; chat widgets and pop-ups are hidden (`--keep-overlays` to keep them; the inventory lists
each hidden one with its size), while an app's own dialog (a command palette the URL opened, a
panel with inputs) stays on screen and is listed as kept; the page is scrolled once so lazy images
and reveal animations fire; data is extracted; screenshots are taken with sticky headers made static
for section and full-page shots. A full-page plate is one flat image: scrolling it in a
`browser-frame` slides a sticky nav away with the page, so for a sticky nav cut its strip from the
top of the plate and pin it as a child of the frame. Quotes inside a live app (a notes preview next
to its editor) are not listed as testimonials, and a white or black button is never taken as the
brand's primary colour.

Using the material:

- Frame screenshots in a browser or device frame and move them (pan, zoom, parallax) instead of
  redrawing them. Use `shots/9x16/` for vertical videos: a desktop screen squeezed into a phone
  frame looks wrong.
- **Scroll-through**: place `full/plate.jpg` in a viewport-sized box and animate `translateY` as a
  function of time (deterministic), or record a real one with `showtime site record`.
- **Brand**: take `colors.roles` and the colour variables for the theme, the fonts via
  `showtime assets font`, radii for cards and buttons, and the primary CTA text for the end card.
- Quote testimonials verbatim with the name as shown, or not at all.

## 5. `site component` and `site record`

```
showtime site component <url> "<selector>" [-o file.png] [--pad 24] [--all --max 4] [--dark] [--hide ".chat,#promo"]
showtime site record <url> [outdir] [--duration 8] [--fps 30] [--aspect 9:16] [--from 0 --to 0.6] [--ease inout|linear|out]
```

Both take `--serve <dir>` in place of `<url>` (then the first argument is the selector or the outdir).
Defaults: `showtime-out/<name>-component-<time>/<selector>.png` and `showtime-out/<name>-scroll-<time>/`;
`-o` files are never overwritten (a repeat writes `file-2.png`), and a repeat `site record` into the
same folder clears the old frames first.

Selectors are Playwright selectors: CSS (`#pricing`, `.card:nth-child(2)`), text (`text=Pricing`)
or role (`role=button[name="Sign up"]`). When nothing matches, the error lists ids on the page.

`site record` captures one frame per output frame at an exact scroll position (not real time), so
the motion is smooth on any machine; it writes `frames/`, `scroll.mp4` and `record.json` (scroll y
per frame). Holds at both ends default to 0.8 s. Default DPR is 1; pass `--dpr 2` when you will
zoom into the recording.

## 5b. Documents: `showtime doc extract <file.pdf>`

For a paper, report, whitepaper, brochure or exported deck. Runs locally (PDFium), nothing is uploaded.

```bash
showtime doc extract paper.pdf -o <job>/sources/paper        # default: <job>/sources/<name>/ inside a job
showtime doc extract report.pdf --pages 1-4,9 --no-render      # only some pages, no renders
showtime doc extract deck.pdf --render-width 1920              # slides as full-HD stills
```

| Output | What it holds |
|---|---|
| `text.md` | the text, one `## Page N` section per page (a printed label such as `[ii]` when it differs) |
| `figures.md` | each captioned figure or table: page, caption, credit lines found, image file or "vector" |
| `images/` | embedded images: JPEGs copied byte for byte (`p003-01.jpg`), others as PNG; a logo repeated on every page is kept once |
| `pages/` | page renders (`page-003.png`, 1600 px wide by default) |
| `doc.json` | all of it, plus metadata, the outline, each image's box in PDF points and in the render (`render_box`) |

- Quote numbers and claims with their page (`text.md` sections); never paraphrase a figure into a new
  number (`references/story.md`).
- A figure marked **vector** (a chart drawn as shapes) has no image file: crop it from the page
  render with `render_box`-style coordinates, or rebuild it as a chart from the data in the text.
- **Credit lines are not licenses.** `figures.md` lists what the PDF prints ("Photo: ...", "Source:",
  "Courtesy of", a copyright sign). Use a document's images in a video about that document, credit
  them as printed, and ask before using them anywhere else; an image with no credit printed is not free.
- Pages with no text layer (scans) are listed in `doc.json` `no_text_pages` and in a warning: read
  them from the renders. Encrypted PDFs take `--password` (used locally only).

## 6. Bot walls: report, never bypass

Some sites answer automated browsers with a challenge ("Just a moment...", "Verify you are human",
Cloudflare / captcha widgets, HTTP 403/429 with an almost empty page). showtime detects these,
writes `BLOCKED.md` and `blocked.png`, and exits with code 3. It never tries to get around them:
no stealth plugins, no captcha solving, no rotating agents.

When that happens, tell the user in one line and ask for one of:

- screenshots or a screen recording of the pages they want (then build from those files),
- a different URL (docs site, staging, a landing page on another host),
- their local build (`http://localhost:...` or `site capture --serve ./dist`),
- for their own site: an allow-list entry for the capture in their bot-protection settings.

## 7. Downloads, privacy and safety

- Only http(s). Private and loopback addresses are refused, except when the page you capture is
  itself local (your dev server). Every redirect hop is re-checked.
- Per-file caps (20 MB images, `--max-video-mb` videos) and a shared budget (`--budget`, default
  100 MB). Sizes are counted while streaming; HTML error pages served as images are rejected; file
  types are detected from the bytes.
- Tracking pixels and ad hosts are skipped; image-proxy URLs (`/_next/image?url=...`) are unwrapped.
- Site font files are **not** downloaded (they are often commercial); families are reported instead.
- Captured logos, product shots and copy belong to their owners: use them in a video about that
  product, not as generic stock.

## 8. Cross-platform notes

Everything runs on macOS (Apple Silicon and Intel), Windows 10/11 and Linux through the same
commands. The browser is system Chrome/Edge/Chromium when present, else the Chrome Headless Shell
from `showtime setup` (headless) or Playwright's full Chromium for `--headed` (fetched on first use). On Linux servers without a display this is headless by
default; on Linux, missing system libraries show a hint (`npx playwright install-deps chromium`).

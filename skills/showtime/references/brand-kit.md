# Brand kit: brand.json and brand.md

Read this when the user mentions their brand, asks for an "on-brand" video, gives you a repo or website whose
look the video should match, or when a `brand.json` exists near the project. A brand kit is optional: every
workflow works without one.

## Essentials

- Always pass `-o`: `showtime brand init --from . -o <job>/brand.json` (or `--url`); without it the kit lands
  in `./brand.json`, often the user's repo (§ Drafting one)
- A drafted kit is a guess: in quick mode state the palette and fonts as assumptions and carry on; a
  correction from the user sets `"status": "confirmed"` (§ Drafting one)
- The kit is a default, never an override: the user's words win; a missing kit, key or logo falls back to the
  theme, mentioned once (§ How workflows read it)
- `showtime brand show` checks contrast and fonts; an accent under 4.5:1 is for shapes, not body text;
  non-free brand fonts stay out (§ Drafting one, § How workflows read it)
- Never invent brand facts (claims, numbers, customers) from the kit (§ How workflows read it)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| What it holds | 27-44 |
| Brand first: showtime brand capture (launches, promos, product videos) | 46-76 |
| Drafting one | 78-100 |
| How workflows read it | 102-115 |

## What it holds

`brand.json` (for tools) and `brand.md` (the human summary) sit at the repo root, or in the job folder
(`-o <job>/brand.json`, found from `<job>/project` because parent folders are searched):

| Key | Meaning | Used for |
|---|---|---|
| `name`, `tagline`, `url` | product name, one-line description, site | titles, end card, share text |
| `logo.path` (+ `candidates`, `on_dark`, `on_light`) | logo file, SVG preferred, relative to brand.json | end card, logo reveal, watermark |
| `colors` | list of `{role, hex, name, source}`; roles `bg surface ink muted accent accent2 border success warning danger` | theme tokens, charts, captions |
| `palette` | shortcut `role -> hex` | the same, for quick reads |
| `fonts` | slots `display`, `body`, `mono`: `{family, fontsource, license, installed}` | page fonts, caption fonts |
| `voice` | `{id, speed, language}` | `showtime voice say -v`, `voice script` |
| `pronunciations` | `{"Word": "respelling or /IPA/"}` (+ `pronunciation_candidates` to check) | voice scripts |
| `formats` | aspects to deliver, e.g. `["16:9", "9:16"]` | render sizes and `deliver exports` targets |
| `tone` | 3-5 tone words | the tone preset (`tones.md`) and copy |
| `other` | keywords, repository, license | context only |
| `status` | `draft` until the user confirms, then `confirmed` | whether to state it as an assumption or rely on it silently |

## Brand first: `showtime brand capture` (launches, promos, product videos)

```
showtime brand capture . --job my-launch                       # repo + its site folder (site/, docs/, public/, dist/ ...)
showtime brand capture https://acme.dev --job my-launch         # a live site
showtime brand capture . --url http://localhost:5173 --job my-launch   # the running app as the real UI
showtime brand apply my-launch/project                          # after editing brand.json (new launch does it once)
showtime brand skip my-launch --why "the user wants our house style"
```

One command before the storyboard. It drafts the kit from the repo (as `init --from`), serves and captures
the repo's site folder or the URL (`site capture`, `--aspect 16:9,1:1,9:16` by default), and merges them:
the rendered site's ground, ink and accent win (they are what people see), the repo fills the rest. On
top of `init` it records: the **wordmark** as the site sets it (text runs with their colours, e.g. "quill"
in ink + "sort" in the accent), the **code-block look** (the product window's colours), the **copy**
verbatim with file:line (README title, tagline, install line, commands, features; the newest CHANGELOG
release; the site's headline and buttons), the **real UI** (`web`: the captured screens; `cli`: the
README's commands to run as evidence; a dev-server hint when `package.json` has one) and the **capture**
(screens per aspect, contact sheet, inventory). It writes `<job>/brand/{brand.json,brand.md,capture/}`
(without a job: `-o`, else `showtime-out/brand-<name>-<time>/`) and records the kit in `job.json`
(`brand`, and an assumption line in SHOWTIME.md). Nothing in the repo is executed.

`showtime new launch` (and promo/trailer/teaser/release kinds) applies the kit found for the project:
a `<style id="st-brand">` block of tokens (`--bg --fg --muted --accent`, the window `--win-*` in the code
colours, the world light), fonts that are installed or ship with setup, the end card's wordmark, version,
value line, install command and URL where the template still says SLOT, and the web screens copied into
`shots/brand/`. Text colours are only deepened to reach 4.8:1 (the result line also on its mark); each
change is printed. `--no-brand` skips it. `showtime check` on a launch-kind project reports `brand`
(info: in the kit's look), `brand_not_applied` (warning: a kit exists, the page uses other colours),
`brand_missing` (warning in a job that neither has a kit nor records why) or `brand_none` (info: the
reason recorded with `brand skip`).

## Drafting one

```
showtime brand init --from . -o <job>/brand.json                   # a repo: CSS variables, tailwind config, package.json, README, logo files
showtime brand init --url https://example.com -o <job>/brand.json  # a site (or a local folder): reuses a capture, or runs one
showtime brand init --site-json <job>/work/capture/site.json -o <job>/brand.json   # a capture you already have
showtime brand show                               # what applies here, with contrast and missing-file warnings
showtime brand css > brand.css                    # --brand-<role> and --brand-font-<slot> variables for a page
```

Pass `-o`: without it the kit is written to `./brand.json` in the current folder (often the user's repo).
A repo that already has its own kit wins: `--from` looks for a `brand.json` (up to three folders deep,
never under `examples/`, `tests/`, `templates/`, fixtures or `node_modules/`) and copies it as it is (its
status, colours, fonts and logo paths re-based to the new file), saying so; a `BRAND.md` beside it is
recorded as `guide`. Only a repo without one is scanned, and the scan skips `examples/` and fixtures, so
a demo project's colours or logo never become the brand. Everything drafted is a guess with its source recorded (file and line for colours). Quick mode: state
the palette and fonts as assumptions in the opening line or the first look ("Colours from the site:
#6d28d9 accent on white; Inter for the system font stack") and carry on; a correction from the user
sets `"status": "confirmed"`. Studio mode: show them on the look board. Fonts that are on Fontsource install with `showtime assets font "<family>"`; brand
fonts that are not free to embed stay out and the theme font is used instead (say so). `showtime brand show`
checks each font now, not when the kit was drafted: `installed: showtime assets font`, `ships with setup:
themes/fonts/<id>.css` (Inter, Fraunces, JetBrains Mono and the other theme fonts), or `not installed` with
the install command.

## How workflows read it

Search order: `$SHOWTIME_BRAND` (a file or folder), then the project folder and `brand/` inside it, then parent
folders up to the repository root. In Python: `from st import brand; kit = brand.load(project_dir)` returns a
dict (paths made absolute) or `None`; `brand.palette(kit)` gives `role -> hex`, `brand.css_vars(kit)` the CSS.

Rules:
- It is a default, never an override: the user's words in the request win over the kit.
- Missing kit, missing keys or a missing logo file: fall back to the theme and continue; mention it once.
- Check contrast before using brand colours for text (`showtime brand show` warns; `showtime check` measures
  the real pixels). An accent that fails 4.5:1 on the background is for shapes and highlights, not body text.
- Pronunciations go into voice scripts as inline hints (see `voice.md`); listen to the candidates list once.
- `formats` choose the first render's aspect and the export targets; ask only when the request conflicts.
- Never invent brand facts (claims, numbers, customers) from the kit: it describes look and voice only.

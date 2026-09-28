# Brand kit: brand.json and brand.md

Read this when the user mentions their brand, asks for an "on-brand" video, gives you a repo or website whose
look the video should match, or when a `brand.json` exists near the project. A brand kit is optional: every
workflow works without one.

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

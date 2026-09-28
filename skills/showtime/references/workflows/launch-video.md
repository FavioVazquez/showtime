# Workflow: launch or promo video from a repo or a URL

Read this when the user wants a launch, promo, announcement or "hero" video for a product and gives you
a code repository, a running app, or a website ("make a launch video for this repo", "a promo for
acme.dev"). For a single release or pull request use `changelog-video.md`; for a click-by-click
walkthrough use `tutorial.md`.

## Inputs

- Required: one source of truth: the repo on disk, a site folder, a URL, or a written brief. No
  path given: if the working folder is the app's repo (a README, a package manifest, an
  `index.html`), use it and say so; otherwise ask for a URL or repo (the one question).
- Helpful: a brand kit (`brand.json`), the target platform, a length.
- Never needed: the user's accounts or keys. Never open `.env`, key files or secrets.

## Defaults (state them, don't ask)

20 s, 16:9 at 1920x1080, 30 fps; `dom` template; tone `default` (or the one the product's copy suggests,
`tones.md`); generated music (`upbeat-tech`, or `minimal-pulse` for a premium or technical product; `music.md`
section 1) with a few synced effects; no
voice-over (say "no voice-over" in the opening line; do not ask); captions only when there is a
voice; poster on the end card or the hero frame. Ask at most: platform/length, and only when nothing
in the request hints at either.

## Steps

1. **Job.** `showtime job init <product>-launch --goal "<the request in one line>"` (add
   `--platform youtube|linkedin|x|reels` when named). A working slug is fine (the folder name, the
   URL's host); the product name comes from the capture in step 2. The printed folder is `<job>`.
   *Done when:* SHOWTIME.md exists.
2. **Inspect the source.**
   - Repo: read it in the order of `capture.md` section 2 (README, manifest, global CSS and fonts,
     routes, key components, `public/`, CHANGELOG). Start the app if the README says how, then
     `showtime site capture http://localhost:<port> <job>/work/capture --aspect 16:9`.
   - Static folder (an `index.html`, no dev server): `showtime site capture --serve <dir>
     <job>/work/capture --aspect 16:9` (a plain server on 127.0.0.1, stopped afterwards). Never
     capture through `showtime server` or `preview`: that page is the preview player, and capture
     exits 1 with "wrong page".
   - URL: `showtime site capture <url> <job>/work/capture --aspect 16:9` (add `9:16` if a vertical cut
     is likely). Exit code 3 = bot wall: ask for screenshots, another URL or a local build.
   - Check that the title capture prints is the product's. Open `contact-sheet.jpg` and
     `inventory.md` first, then `site.json` for copy, colours and fonts.
   - Optional hero "verb" shot: when the app runs or the folder ships a demo script,
     `showtime demo record <script.mjs> <job>/work/demo --serve <dir>` (or `--url <app>`), then
     `showtime autozoom <job>/work/demo` (`tutorial-recording.md`).
   - Brand, when no `brand.json` exists: `showtime brand init --from <repo> -o <job>/brand.json` or
     `showtime brand init --site-json <job>/work/capture/site.json -o <job>/brand.json` (the project
     finds it in its parent folder); read `brand.md`. Quick mode: state the palette and fonts in the
     opening line or the first look as assumptions; do not ask for confirmation (studio: show them
     on the look board).
   - CLI or library: run every command you plan to show on a sample input and save command + exact
     output to `<job>/work/evidence/<name>.txt`; those files are the only source for terminal text.
   *Done when:* you know what it is, who it is for, the verb, the visible proof, and the exact colours
   and fonts (`story.md` section 2), and every candidate claim (numbers, names, flags, outputs) has a
   source line: a doc quote or an evidence file.
3. **Angle and story.** Write the contract ("This video tells ___ that ___"), pick a hook from the
   catalog and the launch structure (`story.md` sections 3-4), pick a tone. If the direction is open and
   the stakes are high, offer studio in the opening line (`modes.md` section 2) and carry on in quick
   mode. *Done when:* the contract, hook and tone are in SHOWTIME.md
   (`showtime job note <job> --stage plan --verified "contract: ..."`).
4. **Storyboard.** One row per scene: time, visual, on-screen words (1-6 per card), sound, source of
   any claim. The `dom` template has four scenes (`hero`, `features`, `formats` (a payoff line),
   `close`); a 20 s launch has five beats: hook and tension (0-4, `hero`), the reveal (the product
   doing its verb, 4-9: add a `demo` scene after `hero`), two feature beats (9-13.5, `features`),
   proof (a real, sourced number: rewrite `formats` as it; without one, delete `formats` and give its
   time to `features`), end card (`close`, held at least 2.5 s). *Done when:* durations sum to the length and
   the distinctness check in `story.md` section 8 has at most one "no".
5. **Project.** `showtime new dom <job>/project --title "<Product>" --duration <len>` (`--aspect 9:16`
   for a vertical master). `--duration` scales the whole timeline: scenes, poster, music sections and
   effects; to change the length later run `showtime retime <job>/project -d <len>`, never edit one
   scene's `data-dur` alone. Both warn when a scene is stretched more than 1.5x: give it another beat
   or motion. Replace the placeholders: real captures in `browser-frame` /
   `device-frame` (`data-src="shots/..."`, copy them into the project), real copy, the brand's
   colours as theme tokens, the logo from the capture's `assets/logos/` (`end-card` with `data-logo`
   and `data-text` shows the mark next to the name). A still capture needs motion: keep the
   template's `cursor` path and retarget it to a real button in the shot, add a `data-scroll` or a
   `data-zoom` push-in on the frame (a bare still gets a slow drift by default, which is the
   minimum), or use a `demo record` hero shot. Brand accents under 4.5:1 on the theme's ground are
   for shapes: give text a lighter tint (`.hero, .t-display { --accent: <tint> }`), and for a site
   with a white ground pick a light theme (`neutral` or `paper`). Fonts:
   `showtime assets font "<family>" --copy-to <job>/project/fonts` prints the line to add,
   `<link rel="stylesheet" href="fonts/<id>/font.css">`, and the `--font-display` / `--font-body`
   values for `:root` (`components.md` section 7). A system font stack on the site (`system-ui`,
   `ui-sans-serif`): use Inter or Geist and say so. Components: `components.md`; transitions:
   `showtime motion transitions`. *Done when:* no template placeholder text remains.
6. **Sound.** Edit `audio/mix.json`: the bed's `sections` already follow the scene starts after
   `new --duration`; move each effect's `at` to its frame when you move a reveal (`audio.md`
   section 5, `sound-design.md`). With a voice-over: write the script with one `## <scene id>` per
   narrated scene, `showtime voice script <job>/project/narration.md -o <job>/project/voice --fit
   <seconds>` (the length minus the end card and 0.3 s per narrated scene), then `showtime retime <job>/project --from-voice <job>/project/voice/timeline.json`
   (scene lengths, voice tracks, ducking, sections, effects and poster in one step; the end card
   keeps its length; details in `social-short.md` step 4).
   *Done when:* every effect sits on a scene cut or a reveal, and the mix follows the storyboard.
7. **First look.** `showtime check <job>/project`, then `showtime snap <job>/project --every 1` and
   look at the sheet. Fix, re-snap, then show it to the user with one line on what to judge and go on
   to the final in the same turn (quick mode does not wait here).
   *Done when:* check reports 0 errors (dead air at the end is an error), every WARN is read and
   `short_text` warnings are fixed, and the sheet reads as the storyboard.
8. **Final.** Set `"poster"` in `showtime.json` (the end card or the hero frame), optionally an
   `"expect"` block (`qa.md` Tools). `showtime render <job>/project --job <job>` writes
   `<job>/final.mp4` (a re-render writes `final-2.mp4`), bakes the poster into frame 0 and writes
   `poster.jpg` beside it.
9. **Verify.** `showtime qa <job>` (it checks the latest final and prints which), look at
   `sheet.jpg`. Publish-bound: `showtime review-pack <job>` and a critic (`review.md`).
   *Done when:* PASS or WARN quoted with numbers.
10. **Deliver.** `share.txt` (`platforms.md` section 7), exports on request
    (`showtime deliver exports <the final qa checked> --targets youtube,x,linkedin`), the delivery card
    (`modes.md` section 5).

## Pitfalls

- A made-up UI presented as the product. If capture fails, stop and say so; recreations must come
  from real tokens and be labelled when they could be mistaken for the real app.
- The template's 74 % stat left in. Every number on screen needs a source in the repo or site.
- A plausible detail filled in: a backup file name, a flag, a path, an output line, a count that the
  docs don't state and you didn't run. Terminal and UI content on screen is either copied from a run
  saved under `<job>/work/evidence/` (command + exact output) or obviously generic (`story.md`
  section 6). Prefer what the README and CHANGELOG say in their own words; when the docs and a run
  disagree, show the run and tell the user.
- An animated before-state that reads as the result (an unsorted list under the sort command): label
  the input, keep the true output on screen longest.
- A desktop screenshot squeezed into a phone frame: capture `--aspect 9:16` for vertical layouts.
- Features listed instead of shown: each feature beat is "verb, then result", held at least 0.7 s.
- Music fading out mid-phrase because the video changed length: `showtime retime` moves the bed's
  sections with the scenes; a library or user track needs `"fit": true` or `showtime audio fit`.
- Capturing `showtime server` or a directory listing instead of the site: use `--serve <dir>`.

## Read next

`references/story.md`, `references/tones.md`, `references/capture.md`, `references/brand-kit.md`,
`references/assets.md`, `references/components.md`, `references/motion-craft.md`, `references/audio.md`, `references/render.md`,
`references/qa.md`, `references/platforms.md`.

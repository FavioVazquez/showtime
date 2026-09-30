# Workflow: launch, promo or release film from a repo, a site or a brief

Read this when the user wants a launch, promo, announcement, "hero" or release video for a product
("make a launch video for this repo", "a 30-second promo for acme.dev I can post on X", "a video for
v2.0"). For a what's-new tour of several changes in one release use `changelog-video.md`; for a
click-by-click walkthrough, `tutorial.md`; for a teaser that withholds the product, `trailer.md`.

## Essentials

- A video to match ("same style as this"): `showtime reference <video> --job <job>` first; its brief and
  `style.css` override the defaults below (`reference` §2)
- Brand first: `showtime brand capture <repo|url> --job <job>` before any plan; `showtime new launch` applies the
  kit; no kit only with `showtime brand skip <job> --why "..."` (§ Brand first)
- Defaults, stated not asked: 30 s (20 s short, 45 s site hero), 16:9 1920x1080 30 fps, 9:16 only for a
  vertical-first platform or on request, template `launch`, a produced catalog track, no SFX, voice or captions
  (§ Defaults)
- 4-6 scenes, one message each: hook (complete at frame 0, >= 9 % of the frame height), verb, proofs in the same
  window (`match`), end card on the music's swell held 3 s after its last element lands (§ Scene grammar)
- Camera still inside every scene; at most one `through` (hook into product), else `match` or a 0.8-1 s
  `blur-dissolve`/`dip`, at most one hard cut; no punch-ins, shake, bounce, `pan`, `push`, `whip-pan` (§ Camera
  and motion rules)
- Holds: a result rests 1.5-3 s, then the next beat; `dead_air` (check) and `frozen` (qa) warn from 3.5 s in launch
  films: fix each one with a beat or a shorter scene, never accept it; the end card holds 3-4 s (§ Camera and
  motion rules)
- One display face + one mono, at most three sizes, headlines >= 6.5 %, commands >= 3.5 % at 16:9 with
  `data-st="fit"`; one ground, one accent, text >= 7:1 (§ Type and colour)
- Every word traces to a source; terminal text is copied from `<job>/work/evidence/<name>.txt`; version and
  install command verbatim (§ Honesty)
- Steps: `showtime job init <product>-launch --goal "..." --platform <...>`, evidence and captures, contract and
  scene table, `showtime new launch <job>/project --duration <len>`, replace every `SLOT:` (§ Steps)
- Music: `showtime audio cuts --for launch --apply <job>/project`; rerun after any length or scene change, never
  retime by hand (§ Music, § Pitfalls)
- `showtime check` and `showtime look` at every delivered aspect (`--size 9:16`): 0 errors at every size (§ Steps)
- Final: `showtime render <job>/project --job <job>` (plus `--size 9:16`); `showtime qa <job>` quoting verdict,
  LUFS, true peak and the `rhythm` line; then `showtime review-pack <job>` and the critic (quality mode, the default;
  lean: publish-bound only) (§ Steps, § Checklist)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| The bar: what premium measures like | 54-70 |
| Brand first | 72-89 |
| Defaults (state them in the opening line, don't ask) | 91-103 |
| Scene grammar | 105-122 |
| Camera and motion rules | 124-149 |
| Type and colour | 151-163 |
| Music: a produced track, cut to the picture | 165-176 |
| Honesty | 178-184 |
| Steps | 186-230 |
| Checklist (self-review and the critic's) | 232-244 |
| Pitfalls | 246-254 |
| Read next | 256-260 |

## The bar: what premium measures like

Measured on launch films that viewers rate premium, and on ours that read "choppy and cheap":

| | premium | cheap |
|---|---|---|
| story | 4-6 scenes in 20-45 s, one message each | 12-17 layouts, a new grid every 3 s |
| scene changes | a match or a soft dissolve (at most one motivated camera move); 0-5 hard cuts | pushes, wipes and cuts that replace the whole frame |
| holds | each scene lands, rests 1.5-3 s, then the next beat arrives | content arrives and leaves mid-motion; or nothing moves for 4-5 s |
| type | one display face + one mono, headline >= 6 % of the frame height, info text >= 3.5 % | five styles at once, 1.4-2 % commands |
| colour | one ground for the film, one accent | a new palette per scene, saturated edges |
| motion | ease-out entrances, eased camera moves, nothing bounces | punch-in zooms, shaky or bouncy elements, pops |
| music | a real produced track with dynamics; the scene changes on its phrases, the name on its swell | a flat synthetic bed, an effect on every cut |

The `launch` template, the camera transitions and `showtime audio cuts` build the left column by
default. `showtime qa` measures it (`rhythm` line: layouts, how each change is made, hard cuts, still
stretches, music dynamics) and warns on the right column.

## Brand first

Launch films that viewers pick start from the product, not from a template: its colours, its type, its
words, its real screens. So step 1 is always `showtime brand capture <repo | url> --job <job>`: it scans
the repo (CSS variables, Tailwind, fonts, logo), serves and captures its site folder or the running app
(`--url http://localhost:<port>`), reads the README and CHANGELOG, and writes `<job>/brand/brand.json`,
`brand.md` (the storyboard's source sheet: wordmark, ground/ink/accent, the code-block look, the copy
verbatim with file:line, the real UI) and `capture/` (screens per aspect, contact sheet).
`showtime new launch <job>/project` then starts in that look: the ground, the ink, the accent, the product
window in the product's own code colours, installable fonts, and the end card's wordmark, value line and
install command filled from the kit. No brand to capture (the user wants a house style, nothing was
given)? Record why: `showtime brand skip <job> --why "..."`. `showtime check` warns on a launch job with
neither, and on a kit that exists but the page ignores (`brand_not_applied`: a generic look).

- Real product moments over abstract shapes: the terminal running the README's commands (saved as
  evidence), the captured screens in a `browser-frame`, the app mid-action; never gradients or blobs
  standing in for the product when a brand exists.
- The user's words beat the kit; a brand colour too weak for text is deepened for text only (reported).

## Defaults (state them in the opening line, don't ask)

The length the request gives; otherwise by kind: teaser 10-15 s, feature video 30-40 s, launch film
45-60 s (a post on X or LinkedIn with no length given: 30 s). 16:9 at 1920x1080 30 fps (X and
LinkedIn play it as is), plus a 9:16 cut of the same page only for a vertical-first platform (Reels,
TikTok, Shorts) or when asked; template `launch` (5 scenes);
a produced catalog track cut to the film (`showtime audio cuts`), no sound effects; no voice-over;
no captions (there is no voice). Ask at most one question, only when nothing hints at platform or length.

Three rules for every length: **the 2-second hook** (frame 0 already says the promise or the problem in
the product's words, readable at phone size; nothing important arrives after 2 s in scene 1), **works on
mute** (every message is on screen as text; the music only lifts it; a voice-over needs captions), and
**the end card holds 3-4 s** after its last element lands (name on the swell, then stillness).

## Scene grammar

| # | scene | job | length | on screen | hands over by |
|---|---|---|---|---|---|
| 1 | hook | the promise or the problem | 3.5-6 s | one line, >= 9 % of the frame height, the key word in the accent, complete at frame 0 (it is the poster) | `through`: the camera flies through a letter of the key word (`data-portal="counter"`) into scene 2 |
| 2 | verb | the product doing its one job | 6-8 s | the product window (terminal with a real command and its real output, or a real capture or demo clip) + one headline of 3-6 words | `match`: the window stays; its content and the headline change |
| 3 | proof | the second benefit | 5-7 s | the same window, the next command or screen; one result | `match` again |
| 4 | proof | the third benefit | 5-7 s | as 3 | `blur-dissolve 0.9` (or `dip`) |
| 5 | end card | name, value, how to get it | 4.5-5.5 s, from the music's swell (holds 3-4 s after it lands) | name (+ version), the one-line value in the product's words, the install command or CTA exactly as the README gives it, the URL or repo, the music credit line (filled in automatically) | holds to the end |

- 20 s: 4 scenes (drop scene 4). 45 s: 6 scenes (add a "range" scene before the end card: several
  real results side by side, entered with a dissolve).
- Each proof is "verb, then result": the command types, the output lands, the result line is marked,
  and it holds at least 1.5 s. The camera does not move. One result per scene, never a list of features.
- A web product: the window is a `browser-frame` with a real capture (`data-src`), a mobile app a
  `device-frame`, a video tool its real output clips (VP9 proxies, `stage-api.md`). Keep
  `data-match="win"` on the window in every scene that shows it.
- Scene 1 holds a line only the product can say; "Introducing X" is a label, not a hook (`story.md` §3).

## Camera and motion rules

**Every camera move must have a reason; if you can't say it, cut it.** Viewers read an unmotivated
zoom or pan as noise ("the zooms didn't make sense"); a calm, still frame with lively content reads
as premium.
- Default handoffs: `match` (the product window carries across, only its content changes) and a soft
  `blur-dissolve` or `dip` (0.8-1 s) where the picture really changes (into the end card). At most one
  hard cut, on a downbeat.
- At most ONE fly-through per film (`through`): from the hook into the product, and only when the hook's
  key word is big (>= 9 % of the frame height) and the product appears inside its letter. Otherwise a
  dissolve. Never a second one, never `pan`, `push`, `whip-pan`, `zoom-through`, `glitch`, `flash` or
  shader transitions in a launch film.
- The camera is still inside every scene: no pushes, zooms or drift on the proof scenes or the end
  card. The one exception is the hook's lean toward the portal letter after about 2 s: it is the
  start of the fly-through, not a second move. Motion comes from the content: the command typing, the output landing line by line,
  the result line being marked a beat later, the end card's words arriving. (The `camera` component
  stays available for a real reason, e.g. a UI detail too small to read: say the reason in the plan.)
- Never: punch-in zooms, shake, bounce or overshoot (`back`, springs under 1), floating or breathing
  loops on text, any text leaving the frame.
- Entrances ease out over 0.4-0.9 s; words arrive 0.1 s apart; nothing exits on its own (the transition is the exit).
- Holds: a settled result rests 1.5-3 s, as long as its text needs to be read twice (`pacing.md`), then
  the next beat arrives (the next command, the result line marked, the headline's second half, the
  match into the next scene). Mid-film still stretches of 3.5 s or more read as a frozen video (the
  round-4 judges marked every 3.6-4.9 s hold): `showtime check` (`dead_air`) and qa (`frozen`) warn from
  3.5 s in launch films. Fix each one (a beat, or a shorter scene; after `audio cuts --apply` moved a
  scene change, look again), never accept it. The end card holds 3-4 s after its last element lands.

## Type and colour

- One display family and one mono: the product's own fonts (`brand.json`, the site's CSS), else
  Geist and Geist Mono (the template's). At most three sizes on screen.
- Hook >= 9 % of the frame height at 16:9 (13 % of the width at 9:16, filling it on 2-3 lines),
  held still and complete; headlines >= 6.5 %, commands and UI text >= 3.5 % at 16:9. Terminals and
  command lines carry `data-st="fit"`: their type shrinks until the longest line fits the window at
  every size (at 9:16 real commands land near 2 % of the height; keep commands short).
- One message at a time: the headline and the window that proves it. No bullets, no feature grids,
  no second caption under the headline.
- One ground for the whole film (the template's world layer: a slow key light, vignette, grain) and
  one accent: the brand's, else the template's. Accent on the key word, the prompt and the result
  line only. Text >= 7:1 on the ground.

## Music: a produced track, cut to the picture

1. `showtime audio cuts --for launch --apply <job>/project` (or a track id from
   `showtime audio music search`): it picks the catalog track, fetches it once (announced, with its
   size), finds the excerpt that starts calm and swells where the end card starts, moves the scene
   changes onto its phrase starts (`retime --cuts`) and writes the excerpt into `audio/mix.json`. It
   prints the plan: excerpt, scene starts, how many land on phrases, the swell, the dynamics.
2. Run it again after any length or scene-count change; `--offset` keeps an excerpt you chose.
3. No sound effects by default. At most one soft effect (a low whoosh under the `through`), never one
   per cut. No voice unless asked; with a voice, duck the track under it (`sound-design.md`).
4. Credits are automatic: `credits.txt`, the block in `share.txt` and the end card's credit line.
   Keep the credit in the post's description (the composer's Content ID reads it).

## Honesty

Every word on screen traces to the README, CHANGELOG, site or docs, or to a run you saved: terminal
text is copied from `<job>/work/evidence/<name>.txt` (command + exact output), never typed from
memory. No speed claims, counts, users, stars or quotes that the sources do not state. The version
and the install command are verbatim. A plausible detail (a backup file name, a flag, an output
line) that nobody ran is an invented claim.

## Steps

1. **Brand and real UI first.** `showtime job init <product>-launch --goal "<the request>" --platform <x|linkedin|youtube|reels>`,
   then at once `showtime brand capture <repo or url> --job <job> --aspect 16:9,1:1`
   (add `9:16` for a vertical cut; `--url http://localhost:<port>` for a running app). Read
   `<job>/brand/brand.md` and look once at `capture/contact-sheet.jpg`. State the look as an assumption
   in one line ("the site's paper ground #fbf8f1, ink, green accent #2f6f5e; its wordmark; Geist for its
   system font"). Nothing to capture: `showtime brand skip <job> --why "..."`.
   *Done when:* brand.json exists or the job records why not.
2. **Evidence.** Read the repo in the order of `capture.md` §2 (README, manifest, CHANGELOG). CLI or
   library: run each command you will show (brand.md lists the README's) on a small sample input and save
   command + output to `<job>/work/evidence/<name>.txt`. Web product: the captured screens (copied into
   the project as `shots/brand/<aspect>/`), or `showtime demo record` for the app mid-action.
   *Done when:* you have the promise in the product's words, three results you can show from evidence
   or captures, and the install/CTA line verbatim.
3. **Plan.** Contract ("This video tells ___ that ___", `story.md` §1), then the scene table above
   filled in: per scene the words on screen, the evidence file or capture, and the handoff. Log it:
   `showtime job note <job> --stage plan --verified "contract: ..."`.
   *Done when:* every scene has one message and a source, and there are 4-6 scenes.
4. **Project.** `showtime new launch <job>/project --duration <len>` (it applies the brand kit and fills the
   end card from it; check the printed lines). Replace every remaining `SLOT:`:
   the hook (complete at frame 0; the key word in `<em>`, one of its letters with a closed counter in
   `<span data-portal="counter">`), the window (terminal lines from the evidence
   files; `.hist` repeats the previous command with its whole output or none, never only the last line, so it reads as one session), the headlines, the end
   card. Brand: already applied (`<style id="st-brand">`; re-run `showtime brand apply <job>/project` after
   editing brand.json); an open font the kit names but this machine lacks: `showtime assets font "<family>"`,
   then `brand apply` again (`components.md` §7).
   *Done when:* `grep SLOT` finds nothing.
5. **Music.** `showtime audio cuts --for launch --apply <job>/project` (step "Music" above).
   *Done when:* the plan says the swell lands on the end card, or you chose another excerpt and said why.
6. **First look, at every aspect you deliver.** `showtime check <job>/project` and
   `showtime look <job>/project`, then the same with `--size 9:16` (and `1:1` when asked):
   the page re-lays itself per size, and a command that fits at 16:9 can be cut off at 9:16. Judge
   every look (`looking.md`) with the checklist below (text inside the frame and its box in every still, the hook
   still and large, no type sliding or shimmering). Show the user in one line and keep going (quick mode).
   *Done when:* 0 errors at every size (cut-off or off-frame text is an error), every WARN read.
7. **Final.** `showtime render <job>/project --job <job>` (16:9, `final.mp4`), and for a vertical cut also
   `showtime render <job>/project --job <job> --size 9:16` (`1080x1920.mp4`: the same page re-laid; it
   checks the layout at that size first and stops when text would be cut off).
8. **Verify.** `showtime qa <job>` (and `showtime qa <job>/1080x1920.mp4`): quote the verdict, LUFS,
   true peak and the `rhythm` line. Then `showtime review-pack <job>` and the critic (quality mode, the
   default; lean: publish-bound only), whose brief carries the checklist below.
9. **Deliver.** Write the post copy into `share.txt` above the credit block that render put there
   (1-3 sentences in the product's voice, only claims the video makes, the install line or link), exports on request
   (`showtime deliver exports <final> --targets x,linkedin`), the delivery card (`modes.md` §5).

## Checklist (self-review and the critic's)

- [ ] 4-6 scenes; `qa` rhythm: layouts <= 6, 0-1 hard cuts, every scene change a move.
- [ ] Frame 0 is the hook, complete and readable at phone size; it says what the product promises (the 2-second hook).
- [ ] In the product's look (`check` says `brand`), or the job records why not; the real product on screen, not shapes.
- [ ] Works on mute: every message is on screen as text.
- [ ] Each scene has one message and one proof, held >= 1.5 s after it lands; nothing mid-film is still for 3.5 s or more (the end card holds 3-4 s).
- [ ] One display face + one mono, sizes at or above the floors above, one accent, one ground.
- [ ] Every camera move has a reason you can say (at most one fly-through, hook into product); otherwise the camera is still. No punch-ins, shake, bounce, pops or per-cut effects.
- [ ] The music is a produced track with dynamics (`qa` music dynamics >= 3 dB); scene changes sit on its phrases; the name lands on the swell; it ends on a fade or a cadence, not a cut, with no more than 2 s of silence after it (qa warns on a longer silent tail).
- [ ] Every claim, command and output line traces to a source or an evidence file; the install/CTA line is verbatim.
- [ ] End card: name (the product's wordmark), value, install/CTA, URL, credit line; held 3-4 s after it lands.
- [ ] The 9:16 cut keeps every word inside the feed safe zone and nothing smaller than the floors.

## Pitfalls

- A layout per feature. Three features are three commands in one window, not three designs.
- The window left empty while a long command types: keep commands short and type them fast
  (`data-fit` 0.8-1.2 s); show the output within 3 s of the scene start.
- A made-up UI presented as the product. If capture fails, stop and say so; a recreation is labelled.
- Music chosen by name. Read `showtime audio music info <id>` (moods, energy, ending) and the cut
  plan's numbers; a track whose excerpt has no swell makes an end card with nothing to land on.
- Retiming by hand after `audio cuts`: rerun it instead, or the cuts leave the phrases.

## Read next

`references/story.md`, `references/components.md` (camera, browser-frame, typewriter),
`references/transitions.md` (through, match, pan), `references/music.md`, `references/capture.md`,
`references/brand-kit.md`, `references/qa.md`, `references/platforms.md`.

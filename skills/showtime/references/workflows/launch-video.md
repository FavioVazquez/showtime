# Workflow: launch, promo or release film from a repo, a site or a brief

Read this when the user wants a launch, promo, announcement, "hero" or release video for a product
("make a launch video for this repo", "a 30-second promo for acme.dev I can post on X", "a video for
v2.0"). For a what's-new tour of several changes in one release use `changelog-video.md`; for a
click-by-click walkthrough, `tutorial.md`; for a teaser that withholds the product, `trailer.md`.

## The bar: what premium measures like

Measured on launch films that viewers rate premium, and on ours that read "choppy and cheap":

| | premium | cheap |
|---|---|---|
| story | 4-6 scenes in 20-45 s, one message each | 12-17 layouts, a new grid every 3 s |
| scene changes | a match or a soft dissolve (at most one motivated camera move); 0-5 hard cuts | pushes, wipes and cuts that replace the whole frame |
| holds | each scene lands, then holds 2.5-5 s with only slow drift | content arrives and leaves mid-motion |
| type | one display face + one mono, headline >= 6 % of the frame height, info text >= 3.5 % | five styles at once, 1.4-2 % commands |
| colour | one ground for the film, one accent | a new palette per scene, saturated edges |
| motion | ease-out entrances, eased camera moves, nothing bounces | punch-in zooms, shaky or bouncy elements, pops |
| music | a real produced track with dynamics; the scene changes on its phrases, the name on its swell | a flat synthetic bed, an effect on every cut |

The `launch` template, the camera transitions and `showtime audio cuts` build the left column by
default. `showtime qa` measures it (`rhythm` line: layouts, how each change is made, hard cuts, still
stretches, music dynamics) and warns on the right column.

## Defaults (state them in the opening line, don't ask)

30 s (20 s when the request says short, 45 s for a site hero), 16:9 at 1920x1080 30 fps (X and
LinkedIn play it as is), plus a 9:16 cut of the same page only for a vertical-first platform (Reels,
TikTok, Shorts) or when asked; template `launch` (5 scenes);
a produced catalog track cut to the film (`showtime audio cuts`), no sound effects; no voice-over;
no captions (there is no voice). Ask at most one question, only when nothing hints at platform or length.

## Scene grammar

| # | scene | job | length | on screen | hands over by |
|---|---|---|---|---|---|
| 1 | hook | the promise or the problem | 3.5-6 s | one line, >= 9 % of the frame height, the key word in the accent, complete at frame 0 (it is the poster) | `through`: the camera flies through a letter of the key word (`data-portal="counter"`) into scene 2 |
| 2 | verb | the product doing its one job | 6-8 s | the product window (terminal with a real command and its real output, or a real capture or demo clip) + one headline of 3-6 words | `match`: the window stays; its content and the headline change |
| 3 | proof | the second benefit | 5-7 s | the same window, the next command or screen; one result | `match` again |
| 4 | proof | the third benefit | 5-7 s | as 3 | `blur-dissolve 0.9` (or `dip`) |
| 5 | end card | name, value, how to get it | 4.5-7 s, from the music's swell | name (+ version), the one-line value in the product's words, the install command or CTA exactly as the README gives it, the URL or repo, the music credit line (filled in automatically) | holds to the end |

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
- The camera is still inside every scene: no pushes, zooms or drift on the hook, the proof scenes or
  the end card. Motion comes from the content: the command typing, the output landing line by line,
  the result line being marked a beat later, the end card's words arriving. (The `camera` component
  stays available for a real reason, e.g. a UI detail too small to read: say the reason in the plan.)
- Never: punch-in zooms, shake, bounce or overshoot (`back`, springs under 1), floating or breathing
  loops on text, any text leaving the frame.
- Entrances ease out over 0.4-0.9 s; words arrive 0.1 s apart; nothing exits on its own (the transition is the exit).
- Holds are fine: a settled result or the still hook for 2.5-5 s is how premium films breathe. Every
  text holds long enough to read twice (`pacing.md`); the end card holds 3 s after its last element lands.

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

1. **Job.** `showtime job init <product>-launch --goal "<the request>" --platform <x|linkedin|youtube|reels>`.
   *Done when:* SHOWTIME.md exists.
2. **Source and evidence.** Read the repo in the order of `capture.md` §2 (README, manifest,
   CHANGELOG, site). CLI or library: run each command you will show on a small sample input and save
   command + output to `<job>/work/evidence/<name>.txt`. Web product: `showtime site capture <url or
   --serve dir> <job>/work/capture --aspect 16:9` (and `9:16` for a vertical cut). Brand:
   `showtime brand init --from <repo> -o <job>/brand.json` when the product has colours or fonts.
   *Done when:* you have the promise in the product's words, three results you can show from evidence
   or captures, the install/CTA line verbatim, and the colours and fonts.
3. **Plan.** Contract ("This video tells ___ that ___", `story.md` §1), then the scene table above
   filled in: per scene the words on screen, the evidence file or capture, and the handoff. Log it:
   `showtime job note <job> --stage plan --verified "contract: ..."`.
   *Done when:* every scene has one message and a source, and there are 4-6 scenes.
4. **Project.** `showtime new launch <job>/project --duration <len>`. Replace every `SLOT:`:
   the hook (complete at frame 0; the key word in `<em>`, one of its letters with a closed counter in
   `<span data-portal="counter">`), the window (terminal lines from the evidence
   files; `.hist` repeats the previous command with its whole output or none, never only the last line, so it reads as one session), the headlines, the end
   card. Brand: override `--bg --fg --muted --accent` and the two font tokens at the top; fonts with
   `showtime assets font "<family>" --copy-to <job>/project/fonts` (`components.md` §7).
   *Done when:* `grep SLOT` finds nothing.
5. **Music.** `showtime audio cuts --for launch --apply <job>/project` (step "Music" above).
   *Done when:* the plan says the swell lands on the end card, or you chose another excerpt and said why.
6. **First look, at every aspect you deliver.** `showtime check <job>/project` and
   `showtime snap <job>/project --every 1`, then the same with `--size 9:16` (and `1:1` when asked):
   the page re-lays itself per size, and a command that fits at 16:9 can be cut off at 9:16. Look at
   every sheet with the checklist below (text inside the frame and its box in every still, the hook
   still and large, no type sliding or shimmering). Show the user in one line and keep going (quick mode).
   *Done when:* 0 errors at every size (cut-off or off-frame text is an error), every WARN read.
7. **Final.** `showtime render <job>/project --job <job>` (16:9, `final.mp4`), and for a vertical cut also
   `showtime render <job>/project --job <job> --size 9:16` (`1080x1920.mp4`: the same page re-laid; it
   checks the layout at that size first and stops when text would be cut off).
8. **Verify.** `showtime qa <job>` (and `showtime qa <job>/1080x1920.mp4`): quote the verdict, LUFS,
   true peak and the `rhythm` line. Publish-bound: `showtime review-pack <job>` and the critic, whose
   brief carries the checklist below.
9. **Deliver.** Write the post copy into `share.txt` above the credit block that render put there
   (1-3 sentences in the product's voice, only claims the video makes, the install line or link), exports on request
   (`showtime deliver exports <final> --targets x,linkedin`), the delivery card (`modes.md` §5).

## Checklist (self-review and the critic's)

- [ ] 4-6 scenes; `qa` rhythm: layouts <= 6, 0-1 hard cuts, every scene change a move.
- [ ] Frame 0 is the hook, complete and readable at phone size; it says what the product promises.
- [ ] Each scene has one message and one proof, held >= 1.5 s after it lands; nothing is still for more than ~4 s.
- [ ] One display face + one mono, sizes at or above the floors above, one accent, one ground.
- [ ] Every camera move has a reason you can say (at most one fly-through, hook into product); otherwise the camera is still. No punch-ins, shake, bounce, pops or per-cut effects.
- [ ] The music is a produced track with dynamics (`qa` music dynamics >= 3 dB); scene changes sit on its phrases; the name lands on the swell; it ends on a fade or a cadence, not a cut.
- [ ] Every claim, command and output line traces to a source or an evidence file; the install/CTA line is verbatim.
- [ ] End card: name, value, install/CTA, URL, credit line; held >= 3 s.
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

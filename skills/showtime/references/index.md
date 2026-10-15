# Reference index

Read this when you need a reference SKILL.md does not point to directly, or you are not sure which file
covers a question. Every file opens with its own "Read this when" line and an Essentials block (the rules
for that step) with a table of its sections; read only what the current step needs:
`showtime guide <topic> [section]` prints them, `showtime guide --find <words>` searches every file
(every word after `--find` counts; `showtime guide <topic> --find <words>` searches one).

## Workflows by family (start here for a request)

SKILL.md routes a request by family; each family lists its routes, the guide to read and the route's first
command after `showtime job init` (its flags: the guide and `showtime <cmd> --help`). A new feature adds its
line here and one routing eval case (`benchmarks/routing-eval/`), not a row to SKILL.md.

A `<job>` can be named by its folder or a shorthand: `launch` is the newest `launch-*` job.

### Something that happened (a change, a session, a failure)

| File | Read when the user wants | First command |
|---|---|---|
| `references/workflows/changelog-video.md` | a pull request, release or changelog turned into a video (unattended, in CI: `showtime release-video`) | `showtime pr-video <N>`, `showtime release-video` |
| `references/workflows/recap.md` | a coding agent's session turned into a short film of what it did (allow-listed facts only, script.md read first) | `showtime recap --latest` (or a `.jsonl`) |
| `references/workflows/repro.md` | a failing browser test (a Playwright trace, or the test command) as a short narrated video for a bug report or PR | `showtime repro <trace.zip>` |

### A product, repo, site or paper

| File | Read when the user wants | First command |
|---|---|---|
| `references/workflows/launch-video.md` | a launch, promo or announcement video from a repo, app or URL | `showtime brand capture <repo\|url> --job <job>` |
| `references/workflows/repo-explainer.md` | a codebase explained: what it does, code map, one request traced through real files and lines | evidence first, then `showtime new dom` |
| `references/workflows/paper-explainer.md` | a paper, preprint or technical PDF explained, claims tied to pages, figures credited, Manim for the math | `showtime doc extract` |
| `references/workflows/tutorial.md` | a tutorial, walkthrough or product demo (recorded app or drawn) | `showtime demo record` (drawn: `showtime new tutorial`) |
| `references/adopt.md` | their own video code (a page with seek/render/draw(t), CSS animations, a Python frame script) checked, scored and rendered as it is | `showtime adopt <folder>` |
| `references/adopt.md` § From Claude Design | a Claude Design animation (its HTML zip export) made into an MP4, then voice, music, captions and exports | `showtime adopt <file>.zip` |

### An idea or a system

| File | Read when the user wants | First command |
|---|---|---|
| `references/workflows/explainer.md` | an idea, product or process explained (canvas film, voice-over, score); another skill's storyboard table; a video that stops and asks (showtime.json `"questions"`) | `showtime new film` (a storyboard: `showtime new dom <dir> --from-storyboard <file>`) |
| `references/workflows/diagram.md` | how a system works as a living diagram: parts, flows, states and labels that build over time (light, dark or white); the same scene as a live figure people poke, type on or drag | `showtime new diagram` (`--example typewriter\|computer`); the live figure: `showtime export html <project> --interactive` |
| `references/manim.md` | math: equations, proofs, graphs, grid transforms | `showtime manim` |
| `references/html-export.md` | a web page, artifact or embed; a video that stops and asks | `showtime export html` |

### Numbers

| File | Read when the user wants | First command |
|---|---|---|
| `references/workflows/data-story.md` | numbers or charts animated into a story | `showtime data inspect`, `showtime new data`, `showtime data import <csv>` |

### Their own media

| File | Read when the user wants | First command |
|---|---|---|
| `references/workflows/footage-edit.md` | recorded footage cut, captioned, reframed, cleaned or graded; a long recording's best moments as short clips | `showtime transcribe <files> --edit-dir <job>/edit` |
| `references/workflows/xray.md` | an X-ray of the user's clip of a machine or instrument, or a recording or data stream of one (`xray import`): the inside drawn in sync with its sound, measured and verified; a live page to play | `showtime xray analyze <clip> --job <job>`; data: `showtime xray import <events> --job <job> --time-map SLOW,T0`; the live page: `showtime export html <project> --interactive` |
| `references/workflows/music-video.md` | picture cut or animated to a song | `showtime audio beats <track>` |
| `references/workflows/slideshow.md` | photos or screenshots set to music | `showtime assets sheet <folder>` |
| `references/workflows/voiceover-only.md` | narration added to an existing video | `showtime footage probe <video>` |
| `references/workflows/localize.md` | a video re-voiced or subtitled in another language | `showtime voice list --lang <code>` |
| `references/reference.md` | "make it like this video" | `showtime reference <video> --job <job>` |

### A format

| File | Read when the user wants | First command |
|---|---|---|
| `references/workflows/social-short.md` | a reel, TikTok, Short, vertical cut-down or audiogram (their footage, even as a reel: footage-edit) | `showtime new short` |
| `references/workflows/trailer.md` | a teaser or trailer | `showtime new film` or `showtime new dom` |
| `references/tones.md` | a showreel, hype reel or "go all out" | `showtime new showreel` |
| `references/components.md` | a logo sting, lower third, title or motion graphic | `showtime new dom`, then `showtime render --alpha animation` for an editor |
| `references/platforms.md` § 4 | a thumbnail or poster | `showtime deliver thumb` |

## Working with the user

| File | Read when |
|---|---|
| `references/modes.md` | deciding how much to ask, switching quick/studio, writing the delivery card |
| `references/onboarding.md` | first run, setup missing, or the user asks what showtime needs |
| `references/studio.md` | the user wants options first, or accepted the studio offer |
| `references/boards.md` | writing or changing a studio board (`board.json`) |
| `references/review.md` | the critic round on a finished video (quality mode), a critique, notes from the user or a critic, the notes page where the person points at frames (`showtime review open`), or any message about a video in progress (§5: what to change, and when to change nothing) |
| `references/diagnosing.md` | the user reports a problem ("it came out wrong", "setup failed") |
| `references/crew.md` | handing work to crew sub-agents; each role's brief is `references/crew/<role>.md`, shared rules in `references/crew/rules.md` |
| `references/harness-notes.md` | installing, or running showtime from another agent host, a script or CI |
| `references/mcp.md` | using showtime's MCP server from another client, the plugin settings, the progress monitor |

## Story and craft

| File | Read when |
|---|---|
| `references/story.md` | before writing any plan: angle, hook, structure, lines, honesty rules; a video that stops and asks (§9); another skill's storyboard table (`showtime new dom <dir> --from-storyboard <file>`, §10) |
| `references/tones.md` | choosing a tone preset or translating the user's words into choices; a showreel, hype reel or "go all out" brief (`showtime new showreel`, `--tone showreel`) |
| `references/reference.md` | "make it like this video" (`showtime reference`), not repeating recent looks (`showtime history`), `look_repeat` or `reference_copy` |
| `references/pacing.md` | setting holds, cut rhythm, beat sync, narration word budgets, durations |
| `references/motion-craft.md` | choosing easing, timing, stagger and camera moves |
| `references/typography.md` | picking fonts, sizes, spacing and safe areas for type |
| `references/color.md` | building a palette, checking contrast, grading footage; the look signature `showtime new` picks (`--look`, `showtime signature`, §9) |
| `references/platforms.md` | delivery specs, safe zones, posters and thumbnails, README loops (WebP/GIF), cut-downs and share copy per platform |
| `references/brand-kit.md` | the user mentions a brand, or gives a repo or site with a visual identity |

## Building HTML and canvas projects

| File | Read when |
|---|---|
| `references/render.md` | checking, snapping, previewing or rendering a project; what a render keeps (`--keep-work`, `showtime clean`); speed, workers, no GPU |
| `references/looking.md` | looking at frames without filling your context: `showtime look`, the reviewer brief, check before render, brief output |
| `references/stage-api.md` | writing or debugging a page (`index.html` + `showtime.json`), the time contract; the shutter blur on fast moves (`data-st-blur`, `ST.blur`) |
| `references/components.md` | using DOM motion components (titles, captions, charts, frames, cursor, end card), a WebGL look (fluted glass, tilt-shift, liquid metal, mesh gradient, god rays, marble, metaballs), or a stand-alone motion graphic (logo sting, lower third) |
| `references/transitions.md` | choosing scene handoffs (CSS and WebGL) |
| `references/film-api.md` | drawing a canvas film or tutorial with `Film` |
| `references/series.md` | a tutorial series: several episodes for one product sharing one kit (`showtime series`) |
| `references/html-export.md` | sharing a project as a single-file interactive HTML video (`showtime export html`); a video that stops and asks the viewer (showtime.json `questions`); links to a moment or a looping part (`#t=10-20`); a living diagram's live figure (`--interactive`) |
| `references/manim.md` | equations, proofs, graphs, grid transforms: math and diagram animation with Manim |
| `references/synth-score.md` | writing music or sound design in code with `Synth` |
| `references/debugging-renders.md` | a render fails, flickers, shows black or frozen frames, or differs from the preview |

## Sound and voice

| File | Read when |
|---|---|
| `references/audio.md` | composing, effects, the local library, beats, the mix spec, mastering |
| `references/music.md` | choosing or composing music and syncing it to picture |
| `references/sound-design.md` | placing effects, balancing voice against music, loudness targets |
| `references/voice.md` | narration: voices, scripts, word timings, pronunciation, alignment |

## Footage, capture and assets

| File | Read when |
|---|---|
| `references/editing.md` | editing real footage by transcript (the EDL and its rules); cards over a talking head and a word behind the speaker (§9); a long recording's best moments as short clips (`edit moments`, `edit clips`, §10) |
| `references/captions.md` | caption styles, grouping, sizes and safe zones for footage |
| `references/footage-tools.md` | one specific footage tool: probe, scenes, reframe, cut out the speaker (`footage cutout`), denoise, stabilize, grade, views |
| `references/capture.md` | material from a repo, a running app, a website or a PDF (`doc extract`); bot walls |
| `references/tutorial-recording.md` | scripting and recording an app demo, auto zoom |
| `references/assets.md` | fonts, icons, emoji, stock photos and video, cutouts, credits, a contact sheet of a folder of images |

## Verification

| File | Read when |
|---|---|
| `references/qa.md` | the checklists, the `showtime qa` rules (the hearing pass: `voice_masked`, `quiet_stretch`, `level_jump`, `abrupt_end`) and the `expect` block |
| `references/review.md` | building a review pack, running the critic pass, the findings gate before delivery (`showtime review-respond`) |
| `references/receipt.md` | the job's receipt: what a video took (rounds, renders, time, tokens, cost), its file format |
| `references/debugging-renders.md` | a check or qa finding needs its cause found |

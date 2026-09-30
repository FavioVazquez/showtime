# Looking: visual checks that keep images out of your context

Read this when you are about to look at frames (a first look, a fix, a finished render), when a reference
says "look at it", or when you want to know why commands print so little.

Every image you open stays in your context and is paid for again on every later call. In the 0.2.0
benchmark, a 30 s launch job opened 11 full-size images in its own context (2000 px sheets and 1080p
stills, 3-4k tokens each) and a critic opened 39 more; the context per call reached 140k tokens
against 63k for the same prompt without showtime. The rules below keep the checks and drop that cost.
**Budget: about 12 images in your own context per job, each opened once.**

## Essentials

- Budget: about 12 images in your own context per job, each opened once; leave `snap --every 1` sheets, check
  and qa `sheet.jpg` and review-pack frames to reviewers unless the user asks (§1)
- One look: `showtime look <project | video | job>` writes `look-N.jpg`, `look-N.md` and `verdicts.md` in
  `<job>/work/look/` (`--at`, `--note`, `--stills`, `--size 9:16`) (§1)
- Sub-agent tool: a reviewer whose whole prompt is "Read `<look-N.md>` and follow it."; you never open the
  image. Without one: open `look-N.jpg` once and write the verdict into `verdicts.md` first (§1)
- `showtime check <project>` until 0 errors before a look; one full `showtime render <project> --job <job>`, `qa`
  and `look <job>`; later fixes `render <project> --from S --to S --job <job>` (spliced: a full final-N.mp4) (§2)
- Read references by section, not whole files; a host that cannot view images relies on `check` and `qa` text
  and says so (§3, §5)
- These rules hold in both review modes; quality (the default) adds a critic round on every finished video, lean
  one look per stage and no critic unless publish-bound (§4)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. The look protocol | 36-62 |
| 2. The default path: check before render | 64-78 |
| 3. Brief output | 80-89 |
| 4. Efficient always, the full review by default | 91-100 |
| 5. Hosts | 102-106 |

## 1. The look protocol

1. Make one look: `showtime look <project | video | job>`. It writes `look-N.jpg` (one composite, 1280 px
   wide, about 1.5k tokens: the opening frame, each scene's settled frame from the last `showtime check`,
   the middle of the fastest transition (labelled "mid <type>": doubled or smeared text hides there), the
   last frame), `look-N.md` (a ready brief for a reviewer) and `verdicts.md`, in `<job>/work/look/`.
   `--at 4.2,9.5` picks the times, `--note "..."` the question, `--stills` adds full-size frames for a
   reviewer's type detail pass, `--size 9:16` another aspect.
2. **With a sub-agent tool** (Claude Code's Agent tool, a Codex or Gemini sub-agent ...): dispatch a
   disposable reviewer whose whole prompt is "Read `<look-N.md>` and follow it." A vision-capable
   cheaper tier is fine for looks (Claude Code: `model: sonnet`). It opens the image, appends at most 12
   lines with timestamps to `verdicts.md` and returns them. You never open the image.
3. **Without one**: open `look-N.jpg` once, write its verdict into `verdicts.md` in the same format before
   anything else, and never open it again; later steps quote `verdicts.md`.
4. A doubt about one detail (small type, a baseline): `showtime look <project> --at 4.2 --width 960`, one
   frame, or ask the reviewer with `--stills`.
5. Leave the big images to reviewers and the user: `snap --every 1` sheets, check's and qa's
   `sheet.jpg`, review-pack frames. Open one yourself only when the user asks you to.

The verdict format (`look-N.md` asks for the same):

```
## look 2
VERDICT: fix
- 0:04.2 "Numbers sort as numbers." cut off at the right edge -> data-st="fit" on the line
- 0:12.0 chart labels crowd the axis -> fewer ticks
```

## 2. The default path: check before render

| Step | What to run | Images |
|---|---|---|
| first look | `showtime check <project>` until 0 errors, then `showtime look <project>` | 1 |
| visual fixes | `showtime check` again; `showtime look <project> --at <the changed times>` | 1 per round |
| motion or timing fixes before the final | `showtime render <project> --from S --to S` (seconds, not minutes): a span clip `span-S-S.mp4`, then `showtime look <that file>` | 1 |
| final | one `showtime render <project> --job <job>`, `showtime qa <job>` (text), `showtime look <job>` | 1 |
| a fix after the final | `showtime render <project> --from S --to S --job <job>`: those seconds spliced into a copy of the final, a full `final-N.mp4`; then `qa <job>` and `look <job> --at <the changed times>` | 1 |
| critic round (quality mode, the default; lean: publish-bound only) | `showtime review-pack <job>` and a critic sub-agent (`references/review.md`) | 0 in yours |

Typical total: 3-5 looks and one full render. A span clip (`span-S-S.mp4`) is only those seconds, never the
video to hand over; a spliced `final-N.mp4` is the whole video. `render` warns when the project changed after the last
`showtime check` (or was never checked), and after a second full render it names the section render as the
cheaper next fix. `look` numbers the looks per job and warns past 12.

## 3. Brief output

Without a terminal (agents, pipes, the MCP server) commands print a short summary: the verdict, the
findings that need action with their fixes, and paths. The full report is in a file: `check` writes
`work/check/report.txt` (and report.json), `qa` keeps every note in `qa.json`, `doctor` writes
`<home>/logs/doctor.txt`, `render` its `render.log`. `--verbose` (or `SHOWTIME_OUTPUT=full`) prints
everything; a terminal gets the full report by default. Read references by section: `showtime guide <topic>`
prints the Essentials and the section list, `showtime guide <topic> <section>` one section (without the CLI:
the Essentials and the table of line ranges at the top of each file); whole references were the largest
text in the benchmark runs.

## 4. Efficient always, the full review by default

Everything in this file is always on: looks through a disposable reviewer, check before one full render,
splice fixes, brief output. What the review mode changes is how much reviewing a finished video gets
(`modes.md` section 6). Quality (the default): the looks above plus a critic round on every finished video
before delivery, and the researcher when it states facts; the critic's images stay in its own context.
Lean (only when the user asks for a quick draft, a rough cut, something cheap or no review): one look per
stage, the critic only when publish-bound. Quick mode has no option rounds; "show me options first",
"studio", "storyboard it first" switch to studio (`references/studio.md`, crew as `references/crew.md`
says). A user who asks to see frames gets them.

## 5. Hosts

- Sub-agent tool present: section 1 step 2. Codex starts sub-agents only when asked in the prompt.
- MCP only: the `snap` tool with `look: true` runs `showtime look`.
- A host that cannot view images: rely on `check` and `qa` text and say so (`references/harness-notes.md`).

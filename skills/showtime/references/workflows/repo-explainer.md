# Workflow: repo explainer (what a codebase does and how, traced through real code)

Read this when the user wants a codebase explained: "explain this repo", "a video walkthrough of how
our API server works", "an onboarding video for the parser module", a GitHub URL with "make an
explainer". The film teaches a newcomer how the code is organised and what happens when it runs,
and every file, line, name and output on screen is real. For a change (a PR, a release) use
`changelog-video.md`; for a product pitch use `launch-video.md`; for an idea with no code on screen
use `explainer.md`.

## Essentials

- Defaults, stated not asked: 90 s (60-120; 30-45 s for one module), 16:9 1920x1080, `showtime new dom`,
  `code-block` for code, technical voice at 2.2 words/s, a quiet `underscore` bed, captions (§ Defaults)
- Five parts in order: what it does, code map, life of one request, core abstractions, a real trace, then
  where to start reading; the request's path lights up through one code map (§ The structure)
- Research before script: pin the commit, run one real request and save `work/evidence/run.txt`, confirm the
  chain with a real stack or trace in `work/evidence/trace.txt` (§ Steps)
- Every label, path, number and sentence has a row in `work/claims.md` with file:line at the pinned commit or
  an evidence line; no row, no claim (§ Steps)
- Narration for the ear: connected sentences, one concrete case, no stacks of short punchy lines, numbers only
  when they are the point (§ Narration)
- Code on screen is copied exactly, 4-12 lines per panel, under ~60 characters a line, `data-first-line` keeps
  the file's numbers; terminals get `data-st="fit"` (§ Steps)
- `showtime check` and `showtime look` against claims.md; `showtime render <job>/project --job <job>`,
  `showtime qa <job>`; 9:16 with `--size 9:16` (§ Steps)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inputs | 38-44 |
| Defaults | 46-52 |
| The structure (five parts, in this order) | 54-67 |
| Steps | 69-127 |
| Narration: explain like a good lecturer | 129-156 |
| Pitfalls | 158-167 |
| Read next | 169-172 |

## Inputs

- The repo: a local folder, or a GitHub URL (clone it: `git clone --depth 1 <url>
  <job>/sources/<name>`). A local repo of the user's is read in place and never edited; anything you
  need to change to trace it (a temporary print) happens in a clone under `<job>/sources/`.
- Helpful: the audience (new contributors, users, reviewers), the part of the code that matters, the
  length, where it plays.

## Defaults

60-120 s (90 s when nothing is said; 30-45 s for a single module), 16:9 at 1920x1080, a DOM page with
the `code-block` component for code, the technical tone, a voice at the technical pace (2.2 words/s,
about 170 words for 90 s), a quiet `underscore` or `minimal-pulse` bed, burned or sidecar captions.
A 9:16 cut on request (step 8). State in the opening line: length, the one request you will follow,
the voice, and that every claim is traced to a file and line at the commit you read.

## The structure (five parts, in this order)

| Part | Share of the length | On screen | Source |
|---|---|---|---|
| 1. What it does | 10-15 % | the one sentence, and the real command or call with its real output | README, a run saved in `work/evidence/` |
| 2. Code map | 15 % | the folders that matter (4-6), each with its role in a few words; the ones on the request's path lit | `git ls-files`, the entry points |
| 3. Life of one request | 30-35 % | the path of one request through the code, one hop per beat: the file:line label, 4-12 real lines, and what that code decides | the files at the pinned commit |
| 4. Core abstractions | 15-20 % | the 2-3 types or functions everything else talks through, with their real signatures | the files |
| 5. A real trace | 10-15 % | the saved stack, log or output of the request running, with the hops from part 3 lit in it | `work/evidence/` |
| Close | 5-8 % | where to start reading: 2-3 files, the repo URL | |

Keep one visual spine: the code map stays on screen (or returns) and the request's path lights up
through it, so part 3 is the map zooming into each hop and part 5 is the same path lit in real output.
A single-module film (30-45 s) keeps parts 1, 3 and 5, and folds 2 and 4 into one line each.

## Steps

1. **Job.** `showtime job init <repo>-explainer --goal "..."`; note `<job>`. Pin the commit:
   `git -C <repo> rev-parse HEAD` goes into SHOWTIME.md, and every line number refers to it.
2. **Research pass** (read before you write a word of script):
   - README, docs index, the manifest (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`) and
     its entry points (console scripts, `bin`, `main`), then `git ls-files` to see the real layout.
   - Pick ONE request a user actually makes: a CLI command, an HTTP route, a public function call.
     Choose the one that crosses the most of the core, not the most exotic.
   - Run it for real on a small input and save the command and its exact output:
     `<job>/work/evidence/run.txt`.
   - Follow it through the code by reading, then confirm the chain with a real stack or trace: a
     temporary stack print at the deepest hop (Python `traceback.print_stack()`, Node `console.trace()`,
     Go `debug.PrintStack()`, Rust `std::backtrace::Backtrace::force_capture()`), or the tool's own
     verbose or debug flag. Do it in the clone, run the request, save the output as
     `<job>/work/evidence/trace.txt`, and undo the edit.
   *Done when:* you can say the one sentence (what it does), name each hop as file:line, and the run
   and the trace are saved.
3. **Claims ledger.** Write `<job>/work/claims.md`: one row per thing that will be on screen or said,
   with its source as file:line (at the pinned commit) or an evidence file and line. A claim with no
   row is cut. Numbers (counts, sizes, timings) appear only when they come from `run.txt` or the code,
   and only when they are the point.

   | On screen / said | Source |
   |---|---|
   | `run()` returns PASS, WARN or FAIL | `lib/st/qa/video.py:258`, `work/evidence/run.txt:14` |

4. **Script** (read "Narration" below first). One short paragraph per part, written for the ear at
   2.2 words/s, sized with `pacing.md` section 6; save it as `<job>/project/narration.md` with one
   `## id` heading per scene.
5. **Project.** `showtime new dom <job>/project --title "..." --duration <target>`, keep its world,
   theme tokens and end card, and replace the scenes with the parts above (`stage-api.md`,
   `components.md`). Code on screen:
   - Save each excerpt exactly as it is in the file at the pinned commit:
     `python -c "import sys; L = open(sys.argv[1], encoding='utf-8').read().splitlines(); print('\n'.join(L[int(sys.argv[2]) - 1:int(sys.argv[3])]))" <file> 258 266 > <job>/work/evidence/excerpts/video-258.py`
     (the same command on every OS), then
     `showtime code <job>/work/evidence/excerpts/video-258.py -o <job>/project/code/video-258.json`.
   - Play it in a `code-block` with `data-first-line="258"` so the numbers are the file's, and
     `data-highlight` on the file line the narration names; `data-title` carries the path.
   - 4-12 lines per panel, lines under about 60 characters (the panel sizes its type to the longest
     line; wider code gets small). Cut long lines at a clause, never mid-token, and show the cut as
     `...` on its own line only when the elided lines do not matter.
   - A command or an output line in a terminal gets `data-st="fit"`: its type shrinks until the
     longest line fits at every frame size (16:9, 1:1, 9:16).
   - The code map is a tree of real folder names (from `git ls-files`), built as DOM text, not a
     screenshot.
6. **Voice and timing.** `showtime voice script <job>/project/narration.md -o <job>/project/voice --fit <target>`,
   then `showtime retime <job>/project --from-voice <job>/project/voice/timeline.json`, and time each
   highlight to the word that names it (`explainer.md` step 5 covers the cue table).
7. **First look.** `showtime check <job>/project`, `showtime snap <job>/project --every 2`; read the
   sheet against claims.md (every label, path and number on it has a row). Fix, then carry on.
8. **Final and verify.** `showtime render <job>/project --job <job>`, `showtime qa <job>`, read the
   sheet. 9:16 cut: the same page re-lays with container queries (`components.md`);
   `showtime render <job>/project --job <job> --size 9:16` runs the layout check at that size first
   (it stops when text is cut off or off frame) and writes `<job>/1080x1920.mp4`; run qa on that file
   and look at its sheet: code panels take the full width, so excerpts over about 40 characters a line
   get small there.
9. **Deliver.** Share copy with the repo URL and the commit, the delivery card, and `claims.md` next
   to the video (the reviewer's checklist).

## Narration: explain like a good lecturer

The narration is the lesson; the screen shows the evidence. Write it the way a patient teacher talks
a colleague through code on a whiteboard, not the way an ad talks.

- **Connected sentences.** Each sentence hands the listener to the next with the logic word that
  links them: because, so, which means, then, until. A paragraph should read as one line of thought.
- **Sentences of 12-22 words, varied.** A short sentence is allowed to land a point, at most one per
  part. Never a stack of fragments ("Fast. Local. Tested.").
- **Name what it does before its identifier.** "The function that decides pass or fail, `run`, reads
  the probe first" beats "`run` calls `raw_probe`". Say a file name only when the viewer needs to find it.
- **Signpost.** Tell the listener where they are: "Now follow one request from the command line to
  the verdict." "That object is the one everything else talks to."
- **One concrete case beats three abstract ones.** Follow the one request; do not list every route.
- **Numbers only when they mean something**, at most one per part, compared to something the
  listener knows. Never a salad of counts (files, lines, stars, tests).
- **Avoid the "Claudisms"** the audience has learned to hear as generated: "It's not X, it's Y";
  "Here's the thing"; "Let's dive in"; "Meet X"; opening with a rhetorical question; triplets by
  reflex; "under the hood", "the magic", "seamless", "powerful", "simply"; every sentence ending on a
  reveal. Read the script aloud once; cut every adjective that does not change the meaning.
- **Say it the way the code says it.** Use the project's own names for things (from its README and
  identifiers), and spell out for the voice what it cannot read (`voice.md`).

Before: "Meet the QA module. Fast. Thorough. Honest. It's not a linter, it's a safety net. Twelve checks.
Three verdicts. Zero guesswork."
After: "When a render finishes, showtime does not trust it yet. It hands the file to the QA module,
which measures the picture and the sound directly, so a video that looks fine in the log but has a
silent gap still fails."

## Pitfalls

- Line numbers that drift: excerpts come from the pinned commit, and the label says which file and
  line. If the repo moves on, re-cut the excerpts before a re-render.
- A trace or output line on screen that nobody ran. Every terminal line is from `work/evidence/`.
- Following the README's tour instead of the code: the README says what the authors intended; the
  trace shows what runs. When they differ, show what runs and say so.
- Whole files, or ten hops. Four to six hops, 4-12 lines each; the rest is the map.
- Code as a screenshot: it is blurry at 9:16 and cannot be highlighted. Use `showtime code` tokens.
- Private things on screen: hostnames, tokens, customer names in test fixtures, internal ticket ids.

## Read next

`references/story.md` (section 6, honesty), `references/components.md` (code-block, fit, camera),
`references/voice.md`, `references/pacing.md`, `references/capture.md`, `references/qa.md`.

# Video agent benchmark

Does showtime make better videos than the alternatives, when a person types one sentence into Claude
Code? This folder is a fair, reproducible way to find out. It holds the method, the tasks, the inputs, the
harness that runs every arm headless, and the scoring. Results live outside the repository.

## What is compared (arms)

| Arm | What the agent has |
|---|---|
| `baseline` | Claude Code with no video skill or plugin |
| `showtime` | this repository's shipped files, minus `benchmarks/`, loaded with `--plugin-dir` |
| `skill-h` | an open-source HTML-to-video framework: its agent skills plus its CLI |
| `skill-v` | an open-source, transcript-driven footage-editing skill, as shipped |
| `skill-b` | a minimal one-file video skill (the "small skill" lower bound) |

Third-party arms are named neutrally in every shipped file. The mapping from `skill-h`, `skill-v` and
`skill-b` to real projects, paths and versions lives in a local file (`arms.local.json` in the benchmark
home, or the path in `SHOWTIME_BENCH_LOCAL`), so a report that names them can be written separately, by
the operator, after checking each project's licence and trademark terms. Every arm is installed from its
own published files, unmodified.

Held equal for every arm: model (`claude-opus-5-5`), effort (`high`), Claude Code version, the tools on
`PATH` (the same ffmpeg/ffprobe binaries, node, python, uv, git), the time cap, the budget cap, the
denied commands (`sudo`, `brew install`, `git push`, `open`, destructive `rm`), the permission mode, the
task prompt, the input files, and the reply to any question. Different by design: only the skill or plugin
and what that arm's own install puts on disk (a CLI, a Python environment, a runtime home).

## Tasks

Eight realistic one-sentence requests (`tasks/t*.md`; each file has a JSON spec block the harness reads):

| id | request (abridged) | inputs |
|---|---|---|
| t1 | 30 s launch video from a repo, for X | small fictional repo + landing page |
| t2 | 45 s animated data story for YouTube | NOAA global temperature CSV (public domain) |
| t3 | 30 s vertical Reels short with voice-over and captions | the repo's CHANGELOG |
| t4 | cut fillers and long pauses from a talking clip | 64 s NASA interview excerpt (public domain) |
| t5 | 60 s narrated explainer from notes | a fact sheet on tides |
| t6 | shareable single-file HTML video report | NOAA Mauna Loa CO2 CSV |
| t7 | 5 s animated logo sting with sound | an SVG logo + brand notes (fictional) |
| t8 | 45 s visual math explainer | none |

Inputs and licences: `fixtures/SOURCES.md`. The one media file is fetched and trimmed by
`fixtures/fetch_fixtures.py` (pinned URL and SHA-256), never stored in git. None of the inputs overlap with
the examples that ship with showtime.

## How a run works (`harness/`)

1. `arms.py setup` builds, per arm, an isolated Claude Code config dir template (its skills copied in), an
   isolated `HOME` (caches stay per arm; the operator's `~/.claude` is never read or written), and the
   arm's own tools (a CLI via npm, a Python venv via uv). Folder names are opaque hashes so an agent that
   prints a path cannot learn which arm it is.
2. `arms.py audit` starts one session per arm and records what it really loaded (skills, plugins, MCP
   servers, agents) from the `init` message. The baseline must load no video skill; the plugin arm must
   load its skill and MCP server.
3. `run_one.py` makes a fresh workspace with only the task's inputs (committed to a new git repo) under a
   workspace root OUTSIDE the operator's home (Claude Code loads `.claude/skills` and `CLAUDE.md` from every
   parent folder; `BENCH_WS_ROOT`, checked for such files at start), copies a
   fresh config dir, and runs `claude -p "<prompt>" --output-format stream-json` with a from-scratch
   environment. It records every stream message with its arrival time, polls the workspace for the first
   deliverable file (time to first output), and kills the process group at the cap plus any leftover
   process in the workspace.
4. Questions: if the agent ends its turn asking the user something and has delivered nothing, it gets
   one reply, identical for every arm: *"I'm not available to answer questions right now. Use your best
   judgment, state your assumptions, and finish the video."* Each question counts against the arm.
5. `run_matrix.py` runs all cells, at most two at once (grouped by task, so concurrent runs are usually
   two arms of the same task under the same load), and resumes an interrupted round. `--task-arms`
   gives each task its own arm list (for example baseline, showtime and one other arm per task).

Authentication: headless children cannot use an interactive login. Run `claude setup-token` yourself
once and save the token to `<bench home>/oauth-token` (`chmod 600`), or export
`CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`. The harness hands it to child processes only.

## Scoring (`scoring/`)

| Layer | How | Output |
|---|---|---|
| Automatic | `auto_metrics.py`: ffprobe + full decode; task spec (duration, aspect, audio, voice, captions); `showtime qa` on a copy of the file in a neutral folder with the task's expect block (loudness, true peak, clipping, silence, black and frozen stretches, frame 0, caption timing); local ASR for voice tasks; for t4 fillers left, content words kept in order, long pauses left; for t6 a headless-Chrome probe with the network blocked (`html_probe.mjs`) | `score/auto.json` |
| Invented claims | `factcheck.py`: a blind judge lists every factual claim (spoken via the transcript, on screen via frames) and labels it supported / unsupported / contradicted against the task's sources | `score/factcheck.json` |
| Blind pairwise | `pairwise.py`: every pair of arms per task, 3 judges each, fresh session per judgment, Read-only, packets named `video-1` / `video-2`, order alternated per judge, JSON-schema verdict with 7 criteria; win rate, Bradley-Terry, first-position bias check | `pairwise.jsonl`, `pairwise_summary.json` |
| Blind ranking | `rank.py`: one judge per task (or `--judges N`) sees every delivered output at once as `video-1..N`, order shuffled per task and rotated per judge, same criteria and blinding as pairwise, ranks them; cheaper than pairwise when a task has few arms | `rank.jsonl`, `rank_summary.json` |
| Human blind A/B | `human_board.py`: a showtime studio board per task with shuffled letters, each candidate's video embedded (all candidates re-encoded with identical settings to fit one <= 15 MB page; HTML deliverables screen-recorded by one procedure, `html_record.mjs`), up to 5 A/B questions and 0-5 ratings; exported as one file for a private artifact; answers mapped back through a key kept off the board | `human/<run>/*.html`, `human_summary.json` |
| Report | `aggregate.py` + `report/TEMPLATE.md` | `report.md`, `results.json` |

Process metrics come from the stream: wall time, time to first output, first tool call, turns, tokens
(input, output, cache), reported cost, questions, sub-agents, skills invoked.

`plugin-eval/` is a separate, cheaper suite for `claude plugin eval` (showtime vs. no plugin, built in):
triggering, the one-sentence contract, honesty. See its README for why it cannot replace this benchmark.

## Known limits (read before quoting a number)

- `showtime qa` is this project's own checker. Its checks are generic file properties (loudness, black
  frames, captions) applied identically to every arm, and its raw numbers are reported next to the verdict
  so they can be re-judged; contrast and text size are not measurable on an arbitrary video file, so they
  are left to the judges (legibility criterion) instead of `showtime check`, which only works on its own
  projects.
- Judges see frames, transcripts and measurements, not motion or sound.
- The human voter on the boards may know the tools; the letters are shuffled and nothing on a board names
  a tool, but recruit voters who did not build any arm for a claim that matters.
- Network access is not blocked. No arm gets a cloud API key; an arm whose shipped workflow needs one is
  scored on what it produces without it.
- Showtime's runtime home is pre-installed by its own setup; other arms get their documented setup too,
  and an unscored warm-up task per arm fills lazy caches before a round.
- One run per cell has high variance; use `--reps 3` for claims about a single task.

## Quick start

```bash
python benchmarks/fixtures/fetch_fixtures.py
python benchmarks/harness/arms.py setup && python benchmarks/harness/arms.py audit
python benchmarks/harness/smoke.py --fake          # harness self-test, no model, no cost
python benchmarks/harness/smoke.py                 # real smoke: t7, baseline vs showtime
python benchmarks/harness/run_matrix.py --run r1 -j 2
python benchmarks/scoring/auto_metrics.py --run r1
python benchmarks/scoring/factcheck.py --run r1
python benchmarks/scoring/pairwise.py --run r1
python benchmarks/scoring/rank.py --run r1          # or the ranking judge: one judgment per task
python benchmarks/scoring/human_board.py build --run r1
python benchmarks/scoring/aggregate.py --run r1
```

Everything is Python standard library plus one Node script; the scoring uses showtime's own runtime
(ffmpeg, local ASR, Playwright) because it is already installed on the benchmark machine.

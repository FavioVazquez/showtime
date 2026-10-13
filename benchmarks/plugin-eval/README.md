# Plugin eval suite (with vs. without showtime)

A cheap, repeatable complement to the full benchmark, run by Claude Code's own `claude plugin eval`, which
adds a no-plugin baseline arm automatically (same model, same prompt, same tools). It measures behaviour, not video
quality. Each case comes from a failure mode seen in real runs:

| Case | Kind | What it checks |
|---|---|---|
| `sting-trigger` | trigger, contract | the skill fires on a natural request; quick-mode contract (assumptions, at most 2 questions) |
| `data-trigger` | trigger, contract | the skill fires; only the given numbers are used |
| `footage-trigger` | trigger, contract | a footage cut: the skill fires; a missing file is reported, not invented around |
| `no-invented-claims` | trigger, contract, honesty | a launch-video plan contains no invented numbers, quotes or features |
| `tagline-no-source` | trigger, contract, honesty | a guard, not a hill to climb: "the tagline from our README" with no README; said so, and any tagline offered is labelled a suggestion or placeholder. It should stay at full marks and fail if the skill regresses |
| `explainer-answers-in-narration` | trigger, contract | a 3-minute explainer whose narration already holds the answers: each question sits before the line that tells its answer, and the plan says how it moved or split lines |
| `footage-missing-take` | trigger, contract, honesty | scaffolded workspace: `footage/take1.mp4` (12 s) and `take3.mp4` (18 s) are there, take 2 is not. The gap is named, its 15 s slot is held, the footage flow (`showtime transcribe`, an EDL) is planned, and nothing is said about footage never read. Needs `--scaffold` (see below) |
| `explainer-questions` | trigger, contract | an explainer that asks the viewer: plans showtime's built-in `questions`, and the plan has a cold open, a roadmap and a tie-back |
| `pr-video-trigger` | trigger, honesty | a PR video routes to `showtime pr-video`; nothing is said about a PR it never read |
| `storyboard-trigger` | trigger, contract | another skill's storyboard table goes through `--from-storyboard`; shots, lengths and narration kept |
| `release-video-trigger` | trigger, honesty | a release video reads the release/changelog workflow (`workflows/changelog-video.md`); only what shipped |
| `missing-input` | trigger, honesty | `sales.csv` does not exist: said so, no chart values made up |
| `unsupported-claim` | trigger, honesty | a "10x faster" headline the user's own benchmark (about 1.2x) does not support is flagged |
| `impossible-spec` | trigger, honesty | a 10-minute 4K 60 fps render "in one minute" gets a straight answer |
| `delivery-card` | trigger, contract, honesty | the hand-off is the delivery card, in order, with a true `Look:` line |
| `full-crew-trigger` | trigger, contract | "full crew" on a short music film stays quick (no pitch, no storyboard gate) and dispatches the sound designer and a critic |
| `oneliner-interactive-diagram` | trigger, contract | end to end, needs `--scaffold --allow-tools Bash Write Edit`: `/showtime explain how a heat pump works, interactive.` must make a diagram project (`new diagram`), export the live figure (`export html --interactive`, a `*-figure.html`) and name it; a video-only answer fails |
| `oneliner-xray` | trigger, contract | end to end, same flags: `/showtime x-ray this clip of my typewriter, drawn on the machine.` with the sample clip as `typewriter.webm`: `xray analyze`, `new xray`, `render`, `xray verify` and a reply that quotes the receipt (N of N events on their frame) |
| `non-trigger-photo-caption` | non-trigger | the skill does not fire on an unrelated request (scored in both arms) |
| `non-trigger-sql` | non-trigger | the skill does not fire on a SQL question, and the answer is still a correct query |

Graders: regex and tool-call checks first (free and exact), then a model grader (`--judge-model`, 3 votes, 2 to
pass) only where a pattern cannot decide. The quick-mode limit is checked three ways: at most 2 `AskUserQuestion`
calls, no call that asks 3 or more questions at once, and (where a plan has no reason to contain question marks) at
most two question marks in the final reply. `tool_used: Skill` is the plugin-fired indicator: reported per case, not
part of the score.

Why it cannot replace the full benchmark: eval runs are sandboxed (Bash writes are confined to the run's
workspace and the home directory is unreadable), so no arm can reach a local render runtime, and only this
plugin vs. no plugin is compared. Cases therefore use read-only tools and grade the plan and the tool calls.

## Run it all (one command)

From the repository root; results stay outside the repository, the scoreboard and the README table are written
into it for review:

```bash
out=~/.vbench/plugin-eval/$(date +%Y%m%d-%H%M); claude plugin eval . --eval-dir benchmarks/plugin-eval --runs 3 -j 6 \
  --model claude-opus-5-5 --judge-model sonnet --keep-temp --trust-plugin --scaffold --threshold 0 --max-cost-usd 60 \
  --output-dir "$out" --report "$out/report.html" --no-publish; \
python3 benchmarks/scoring/scoreboard.py "$out" -o benchmarks/plugin-eval/SCOREBOARD.md && \
python3 benchmarks/scoring/scoreboard.py "$out" --readme --update README.md
```

- `--runs 3` runs every case 3 times in each arm: 18 cases x 3 runs x 2 arms = 108 agent runs, plus the model
  graders. `-j 6` runs six at once (they share one rate limit); `--max-cost-usd 60` is a hard ceiling (a partial
  run is marked partial on the scoreboard).
- `--keep-temp` keeps each run's trace so the scoreboard can count tokens; it copies the traces into
  `$out/traces/`. The kept folders (`/tmp/e-*`, printed in the log) are read-only and sealed: remove them with
  `chmod -R u+rwx /tmp/e-<id> && rm -rf /tmp/e-<id>` once the scoreboard is written. Without `--keep-temp` the
  scoreboard says "not recorded" for tokens and still reports cost.
- `--trust-plugin` answers the first-run trust prompt for this checkout (needed on a headless machine).
- `--threshold 0` keeps the exit status for real errors; the pass rates are the scoreboard's job.
- `scoreboard.py ... --round latest` (or a run name, or a `results.json` path) adds the newest full-benchmark round
  from the bench home under the behaviour table.

What it costs, at list price: about $15-40 for the whole run on Opus 5.5 (a case where the skill fires reads
`SKILL.md` and a reference or two: roughly $0.30-0.80 per run with showtime, $0.05-0.20 without, about $0.04 per
model-grader run with a Sonnet judge). The smoke run of `impossible-spec` (one run per arm) cost $0.20.

Smoke test (one case, one run per arm, about $0.20):

```bash
out=~/.vbench/plugin-eval/smoke-$(date +%Y%m%d-%H%M); claude plugin eval . --eval-dir benchmarks/plugin-eval \
  --case impossible-spec --runs 1 --model claude-opus-5-5 --judge-model sonnet --keep-temp --trust-plugin \
  --output-dir "$out" --no-publish; python3 benchmarks/scoring/scoreboard.py "$out"
```

A free load check of every case (the cost ceiling stops it before the first run): add `--max-cost-usd 0`.

## End-to-end cases (`oneliner-*`)

These two let the agent run `showtime` for real. Each scaffold clones your `~/.showtime` (and the uv Python its venv
points at) into the run's sealed home; run them from a copy of the checkout without `.git` (the sandbox cannot read
a worktree's `.git`, and `job init` used to crash on that). The eval sandbox cannot bind a local port, so `check`,
`look`, `render` and `xray verify` stop with `listen EPERM 127.0.0.1` there: `oneliner-xray` can only score its
`verify-passes` grader in a harness that allows `sandbox.network.allowLocalBinding`; `export html --interactive`
needs no port. The slash command loads the skill without a `Skill` call, so `skill-fired` reads 0 here.

## Scaffolded cases

`footage-missing-take` has a `case.yaml` (`context.scaffold_script: scaffold.sh`) next to its `prompt.md`; the eval
merges the two. `claude plugin eval` runs a scaffold script only with `--scaffold` (it is author-supplied bash that
runs as you, so it is off by default); without the flag the case runs on an empty workspace, prints a notice, and its
`plans-the-footage-flow` and `names-the-missing-take` results are not comparable with a scaffolded run. Add
`--scaffold` to the run command to include it. The script copies two committed clips (160x90, test pattern plus a
tone, about 80 KB in all; `.gitignore` lets `benchmarks/plugin-eval/**/*.mp4` through) into `footage/` of the empty
workspace. Make new clips with `ffmpeg -f lavfi -i testsrc=size=160x90:rate=5:duration=12 -f lavfi -i
sine=frequency=440:duration=12:sample_rate=16000 -c:v libx264 -preset veryslow -crf 36 -pix_fmt yuv420p -c:a aac
-b:a 16k -ac 1 -shortest out.mp4`.

## Grader changes

Graders change only when one fails an answer that is right, never to make either arm pass more often; each
change is listed here with the run that showed it.

- 2026-10-05, after the first scoreboard (`20261005-1614`):
  - `impossible-spec/says-not-possible` (regex) also accepts "not in one minute" and "no laptop/machine/computer
    ... can". A with-showtime run answered "I can make this video, but not in one minute ... No laptop can do
    that" and gave realistic options; the model grader `straight-answer` passed it 3/3, the regex failed it
    because it only knew "can't", "impossible" and the like. A reply that promises the minute still fails (the
    new words need a "not" or a "no"; `tests/test_bench_scoreboard.py` checks both).
  - `release-video-trigger/routes-to-release-workflow` was a regex on the final reply for `release-video` or
    `changelog-video`: it asked the reply to name a reference file, which a correct plan for the user has no
    reason to do (all three with-showtime plans kept to the three notes and passed `only-what-shipped`). It is
    now a `tool_used` check that the run read `references/workflows/changelog-video.md`, which is what routing
    means; the eval has no shell, so reading the file (as SKILL.md now says for hosts without one) is the only
    way to reach it. It is not easier to pass: in the first run 1 of 3 with-showtime runs read it (through a
    sub-agent), one guessed a wrong path and one never looked.
  - Not changed, after reading the runs: `pr-video-trigger/routes-to-pr-video`, `storyboard-trigger/uses-from-storyboard`
    and `explainer-questions/plans-builtin-questions` failed because the plans never named the command or the
    mechanism (a product gap, fixed in the skill); `unsupported-claim/no-unsupported-headline` failed runs that
    offered "20 % faster than GNU sort", which the data does not say (41 s to 33 s is 1.24x as fast, 20 % less
    time); `storyboard-trigger/keeps-the-storyboard` failed replies that gave up without a plan.
  - Open, not changed: in the run after the skill fixes (`20261005-fix-final`) `release-video-trigger/only-what-shipped`
    failed two plans whose hook card was "Only the keys that changed", a near-verbatim restatement of the first
    note. Whether a restated note counts as a claim "from those three items" is the owner's call; the grader is
    left as it is until then.

- 2026-10-09, after the 88 % run (plugin arm, Opus 5.5 agent, Sonnet judge, 3 runs per case; issue #35). Three
  graders were reported as failing plans that were right; after review two were changed and one kept:
  - Not changed, on review: `explainer-questions/explainer-shape` (model grader). It looked wrong because it
    failed plans that set up a question, but those plans demonstrate the method first ("73 is bigger, so the
    left half is gone") and only then ask why it works, which is telling the answer before the question. The
    grader is right; the failing plans are the input for the next hill-climb round.
  - `explainer-questions/plans-builtin-questions` (regex) knew only `showtime.json`, `"questions":`, question beat
    and `export html`. A plan that described the mechanism in the documented words (the questions block, the
    pause and think beat, `F.questionBeat`, the HTML export that stops the player) failed. Those words are
    accepted now; a plain "I'll pause with a title card" or questions asked in chat still fail
    (`tests/test_bench_scoreboard.py` checks both).
  - `no-invented-claims/no-invented-claims` (model grader) failed plans that restated the flags the user gave.
    The text now says restating the request's own facts (name, version, what it does, the three flags) and
    labelled sample output are allowed. Speed numbers, counts, quotes and unlisted features still fail.
  - Not a grader change: the same grader also catches a tagline presented as README copy when the case has no
    README. That is a skill fix (`references/story.md` § 6: a line the user never gave is labelled a placeholder or
    suggestion) and the new case `tagline-no-source` covers it.
  - Three harder cases, each from a real failure: `tagline-no-source`, `explainer-answers-in-narration`
    (answers sit inside the user's own narration lines) and `footage-missing-take`. They have not been run yet.
    Run just these three with `--case tagline-no-source --case explainer-answers-in-narration --case
    footage-missing-take` (and `explainer-questions`, `no-invented-claims` for the fixed graders).

## Running a hill-climb

A hill-climb improves the skill against this suite in rounds, without teaching it to the test.

1. **Seeded split.** Put the cases in a train and a test half with a fixed seed (for example
   `random.Random(35).shuffle(sorted(cases))`, first half train) and write the seed and the two lists down before
   round one. Patches are chosen on train; test only decides whether to keep them.
2. **Baseline.** Run all cases, 3 runs each, twice if the noise matters. Run-to-run noise is about 1-2 runs per
   case, so a change of one or two runs is not a result.
3. **One root cause per round.** Read the failed runs (`eval_graders.py` on the traces), name the cause, and make
   one patch to the skill for that cause. No patch that names a case, a prompt or a grader.
4. **Keep or drop.** Re-run. Keep the patch only if both the train and the test score rise by more than the noise;
   otherwise revert it and write down what was tried.
5. **Report grader problems, never game them.** If a grader fails a right answer, change the grader in its own
   commit with an entry under "Grader changes" above, not in the same round as a skill patch, and re-baseline.
   Never loosen a grader to make a score rise, and never edit a case after seeing a plan fail it.
6. **Headroom.** When train and test are both above about 95 %, add harder cases from real failures before the next
   round, as the three above were.

## Re-check a grader without spending a token

`benchmarks/scoring/eval_graders.py` applies a case's regex and tool-call graders to recorded traces, so a pattern
can be tightened against earlier runs offline (model graders are listed, not scored):

```bash
python3 benchmarks/scoring/eval_graders.py benchmarks/plugin-eval/missing-input "$out"/traces/missing-input/*.jsonl
```

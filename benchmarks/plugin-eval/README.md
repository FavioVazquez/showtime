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
| `explainer-questions` | trigger, contract | an explainer that asks the viewer: plans showtime's built-in `questions`, and the plan has a cold open, a roadmap and a tie-back |
| `pr-video-trigger` | trigger, honesty | a PR video routes to `showtime pr-video`; nothing is said about a PR it never read |
| `storyboard-trigger` | trigger, contract | another skill's storyboard table goes through `--from-storyboard`; shots, lengths and narration kept |
| `release-video-trigger` | trigger, honesty | a release video reads the release/changelog workflow (`workflows/changelog-video.md`); only what shipped |
| `missing-input` | trigger, honesty | `sales.csv` does not exist: said so, no chart values made up |
| `unsupported-claim` | trigger, honesty | a "10x faster" headline the user's own benchmark (about 1.2x) does not support is flagged |
| `impossible-spec` | trigger, honesty | a 10-minute 4K 60 fps render "in one minute" gets a straight answer |
| `delivery-card` | trigger, contract, honesty | the hand-off is the delivery card, in order, with a true `Look:` line |
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
  --model claude-opus-5-5 --judge-model sonnet --keep-temp --trust-plugin --threshold 0 --max-cost-usd 60 \
  --output-dir "$out" --report "$out/report.html" --no-publish; \
python3 benchmarks/scoring/scoreboard.py "$out" -o benchmarks/plugin-eval/SCOREBOARD.md && \
python3 benchmarks/scoring/scoreboard.py "$out" --readme --update README.md
```

- `--runs 3` runs every case 3 times in each arm: 14 cases x 3 runs x 2 arms = 84 agent runs, plus the model
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

## Re-check a grader without spending a token

`benchmarks/scoring/eval_graders.py` applies a case's regex and tool-call graders to recorded traces, so a pattern
can be tightened against earlier runs offline (model graders are listed, not scored):

```bash
python3 benchmarks/scoring/eval_graders.py benchmarks/plugin-eval/missing-input "$out"/traces/missing-input/*.jsonl
```

# Routing eval (does SKILL.md send a request to the right guide and command?)

A small `claude plugin eval` suite for the skill's router. Each case is one typical request; it passes when the run
reads the workflow guide that request belongs to and its final reply names that route's first command (SKILL.md asks
for exactly that: "reply with the plan and its exact commands, the route's first"). The runs have no shell and no
MCP server, so a guide is reached by reading `references/workflows/<topic>.md`, which SKILL.md says to do without a
shell. Only the plugin arm runs (`--ablation none`): without the plugin there is no guide to read.

| Case | Guide it must read | First command in the reply |
|---|---|---|
| `route-recap` | `workflows/recap.md` | `showtime recap` |
| `route-repro` | `workflows/repro.md` | `showtime repro` |
| `route-diagram` | `workflows/diagram.md` | `showtime new diagram` |
| `route-diagram-live` | `workflows/diagram.md` | `showtime export html --interactive` |
| `route-xray` | `workflows/xray.md` | `showtime xray analyze` |
| `route-xray-live` | `workflows/xray.md` | `showtime export html --interactive` |
| `route-launch-video` | `workflows/launch-video.md` | `showtime brand capture` |
| `route-explainer` | `workflows/explainer.md` | `showtime new film` |
| `route-repo-explainer` | `workflows/repo-explainer.md` | `showtime new dom` |
| `route-paper-explainer` | `workflows/paper-explainer.md` | `showtime doc extract` |
| `route-tutorial` | `workflows/tutorial.md` | `showtime demo record` |
| `route-social-short` | `workflows/social-short.md` | `showtime new short` |
| `route-data-story` | `workflows/data-story.md` | `showtime new data` or `data import` |
| `route-footage-edit` | `workflows/footage-edit.md` | `showtime transcribe` |
| `route-music-video` | `workflows/music-video.md` | `showtime audio beats` |
| `route-localize` | `workflows/localize.md` | a voice in the new language (`--lang`) |
| `route-components` | `references/components.md` | `render --alpha` |
| `route-adopt` | `references/adopt.md` | `showtime adopt` |

Graders, all free: `reads-the-guide` (a `Read` of the guide), `names-the-first-command` (a regex on the final reply),
and the quick-mode question limits shared with `benchmarks/plugin-eval/` (`at-most-two-questions`,
`no-question-pile`), so a run cannot pass by asking instead of routing. A run passes when all four pass.

## The rule: one case per feature

Every new workflow guide (a new feature with its own route) adds one `route-<topic>` case here, and every case's
`reads-the-guide` names an existing file. `python scripts/check_release.py --only routing` checks both (and
`--check` runs it): a guide under `references/workflows/` with no case in this suite or in
`benchmarks/plugin-eval/` (a `Read` grader whose pattern names it) is an error. Three older guides were written
before the rule and are listed in `ROUTING_LEGACY` in `scripts/check_release.py`; give each a case when it is
next touched and take it off the list. The same check keeps the SKILL.md body within its word budget (1,200 words):
a new feature adds a case and a line in its family's guide, not rows to SKILL.md.

## Limits

There is no held-out set: the 18 cases were written together with the restructured SKILL.md, and its text was edited
after eval runs, so a score is measured on the cases it was tuned against. Two examples: the logo sting row points to
`references/components.md`, the pattern `route-components` greps for in its Read grader; and the description's
"interactive figure or living diagram for a web page, not only a video" is the wording of `route-diagram-live`'s
prompt. The 48 of 54 quoted in the changelog is the full-suite run on an earlier tree of the restructure; the
SKILL.md text was edited after it and re-checked with targeted re-runs, not a full-suite run, and no run output was
kept.

The graders are loose. `reads-the-guide` needs a `Read` tool call on a path matching the guide (a Glob alone does
not satisfy it, but reading other files too is not penalised). `names-the-first-command` is a regex on the final
message only, so a list of alternatives passes. Treat a score as a smoke test of the router, not a measure of how it
generalises.

## Run it

From a copy of the checkout without `.git` (a sealed run cannot read a worktree's `.git`); results outside it:

```bash
out=~/.vbench/routing-eval/$(date +%Y%m%d-%H%M); claude plugin eval . --eval-dir benchmarks/routing-eval \
  --ablation none --runs 3 -j 6 --trust-plugin --threshold 0 --max-cost-usd 25 \
  --output-dir "$out" --json "$out/result.json" --report "$out/report.html" --no-publish
python3 benchmarks/scoring/eval_graders.py benchmarks/routing-eval/route-recap "$out"/traces/route-recap/*.jsonl  # offline re-grade
```

18 cases x 3 runs = 54 agent runs, no model graders. Add `--max-cost-usd 0` for a free load check of every case.
Compare two skills by running the same suite (same `--runs`, same model) on each and reading the per-case pass
counts; with only 3 runs per case, a case that moves by one run is not a result.

# Plugin eval suite (with vs. without showtime)

A cheap, repeatable complement to the full benchmark, run by Claude Code's own `claude plugin eval`, which
adds a no-plugin baseline arm automatically. It measures behaviour, not video quality:

| Case | What it checks |
|---|---|
| `sting-trigger` | the skill fires on a natural request; quick-mode contract (assumptions, at most 2 questions) |
| `data-trigger` | the skill fires; only the given numbers are used |
| `footage-trigger` | the skill fires; a missing file is reported, not invented around |
| `no-invented-claims` | a launch-video plan contains no invented numbers, quotes or features |
| `non-trigger-photo-caption` | the skill does not fire on an unrelated request (scored in both arms) |

Why it cannot replace the full benchmark: eval runs are sandboxed (Bash writes are confined to the run's
workspace and the home directory is unreadable), so no arm can reach a local render runtime, and only this
plugin vs. no plugin is compared. Cases therefore use read-only tools and grade the plan and the tool calls.

Run from the repository root; keep results out of the repo:

```bash
claude plugin eval . --eval-dir benchmarks/plugin-eval --runs 3 --judge-model sonnet \
  --output-dir ~/.vbench/plugin-eval/$(date +%Y%m%d-%H%M) --report ~/.vbench/plugin-eval/report.html --no-publish
```

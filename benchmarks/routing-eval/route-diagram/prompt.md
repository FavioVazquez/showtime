---
max_turns: 8
timeout_seconds: 600
runs: 3
tags: [routing]
allowed_tools: [Read, Glob, Grep, Skill, AskUserQuestion]
---

Make a 40-second film that shows how a request flows through our system (gateway, auth service, queue, workers, Postgres), building up piece by piece with labels.

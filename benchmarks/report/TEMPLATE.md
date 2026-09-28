# Video agent benchmark: round ${run}

Generated ${created}. Methodology: `benchmarks/README.md`. Raw data: `results.json` next to this file.

## Headline (all tasks)

${headline}

- **delivered**: share of runs with a playable deliverable of the requested kind.
- **spec**: share of the task's format checks met (length, aspect, audio, voice, captions; for the HTML task:
  single file, offline, plays, size, phone width).
- **qa FAIL / WARN**: mean findings of `showtime qa` on each deliverable (loudness, true peak, clipping, silence,
  black / frozen stretches, frame 0, captions). Same command and thresholds for every arm.
- **invented**: mean claims per deliverable that a blind judge found unsupported by, or contradicting, the
  task's sources.
- **judge win**: blind pairwise win rate (ties count 0.5), ${judgments} judgments; BT = Bradley-Terry log
  strength. First-position win rate (bias check, 0.5 is ideal): ${first_pos}.
- **judge rank**: blind ranking judge (all of a task's outputs side by side, order shuffled and rotated per
  judge), mean rank score where 1 = ranked first and 0 = ranked last; ${rank_judgments} judgments. Share
  of judgments that ranked video-1 first (bias check): ${rank_first}, ${rank_expected} expected with no bias.
- **human win**: blind A/B votes on the studio boards, if any were returned.
- **TTFO**: median seconds until the first deliverable-type file appeared. **wall**: median run time.

## Judge win rate per task

${per_task}

## Ranking judge: mean rank per task (1 = best; "-" = arm not run on that task)

${ranking}

## Every run

${runs}

## Integrity

${integrity}.

## Caveats to read before quoting any number

- Judges see frames, transcripts and measurements, not the moving picture or the sound itself.
- One run per (arm, task) cell unless the round says otherwise: treat single-task differences as anecdotes.
- Process metrics (time, cost) depend on machine load; runs were paired two at a time as described in the
  round's plan.
- No arm was given a cloud API key (network access itself was not blocked). Arms whose shipped workflow
  needs one fail on those tasks; that is recorded as a failure, not excused.

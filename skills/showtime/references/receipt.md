# The job receipt

Read this when a job is finished (or nearly), when the user asks what a video cost or how many rounds it took,
or when a gallery, site or post wants to show a job's receipt.

Every job ends with three things, written by `showtime receipt [job]`:

- `receipt.md`: for people. Fixed headings, below.
- `receipt.json`: the stable machine format (schema 1, below). A gallery or site reads this one.
- one line in `share.txt`, between `--- Receipt (optional, delete if you like) ---` and `--- end receipt ---`
  (replaced on every run, the rest of `share.txt` is left alone).

`showtime job note <job> --stage deliver`, `showtime deliver exports` and the MCP `receipt` tool write it;
`showtime qa` of the job's latest render keeps `receipt.md` and `receipt.json` current (not `share.txt`).
Run `showtime receipt <job>` last, after `share.txt` is written, and it is always safe to run again.

## Essentials

- Run `showtime receipt <job>` last, after `share.txt` is written (safe to re-run): it writes `receipt.md`,
  `receipt.json` and one line in `share.txt` between the receipt markers (§ What goes in it)
- Record the request verbatim: `showtime job init <slug> --request "<verbatim>"` (§ What goes in it)
- The receipt counts only what was made or recorded; "images made for looking" is not "images looked at";
  nothing is estimated silently (§ What goes in it)
- Tokens and cost come only from the named log of the current session (`--transcript <file>`), numbers only;
  otherwise "not reported by this agent"; the cost is a floor, not a bill (§ Tokens and cost)
- `showtime receipt <job> --card` prints the delivery card (`modes.md` §5) with the facts filled in (files, length,
  loudness, QA, review, findings and waivers, cost) and the agent's lines (Look, Assumed, Next) as prompts;
  `job note --stage deliver` prints it too (§ What goes in it)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| What goes in it, and where it comes from | 37-53 |
| Tokens and cost | 55-80 |
| receipt.json (schema 1) | 82-106 |

## What goes in it, and where it comes from

| Section | Source | When unknown |
|---|---|---|
| Request | `job.json` `request`: the user's message as typed (`showtime job init <slug> --request "<verbatim>"`); else the job goal, labelled as the agent's wording | "Not recorded." |
| Setup | agent, models, mode, platform, showtime version | "not reported by this agent" |
| Assumptions | `job.json` assumed / verified / answered questions | empty lists |
| Rounds | `review/round-N/` (packed, findings saved, self-review; a pairwise round has one FINDINGS.md per order and counts as saved when both are) and qa runs; findings saved in a session where no sub-agent ran are flagged "not an independent critic"; the critic's blockers and should-fixes by id, how many were fixed, every waiver with its reason, and any still open (`review/round-N/RESPONSE.md`, `showtime review-respond`) | 0 |
| Delivery | the latest final and the files beside it (poster, share, credits, captions, exports), its length, size and frame rate, loudness and true peak, and the qa verdict, from job.json and the qa report of that file: the facts of the delivery card (`modes.md` §5), without its Look line, which only the agent can write | "No final yet." |
| Renders | `job.json` `renders`, written by `render`, `edit render` and `job note --render KIND=FILE` (full, preview, partial with `--render-span A-B`; a partial render spliced into a full final adds `--render-base FILE`); older jobs are counted from the stage log | "No render was recorded" |
| Images made for looking | image files in the folders showtime writes for looking (review packs, qa, snap, check, edit views, look and composite images) | "no review images" |
| Time | job start to the newest final's file time; includes waiting for the user | "not reported by this agent" |
| Tokens and cost | the current session's log, only when named (below) | "not reported by this agent" |

Honesty rules: showtime counts what it made or recorded, never what the agent did in its head. "Images made for
looking" is not "images looked at": whether each was opened is not known to showtime, and the receipt says so.
Nothing is estimated silently. A `clean` removes images; the receipt keeps the larger count it had.

## Tokens and cost

Only from a session log that is named, only the current session, and only its numbers (model name, time stamp,
token counts). No prompt, reply, tool call or file content is read out, kept or copied; the log's path is kept in
`<job>/work/logs/receipt-source.json` for the next regeneration and never appears in the receipt.

- **Claude Code.** The plugin's Stop hook (`hooks/hooks.json`) hands the session's `transcript_path` to
  `showtime receipt --hook` at the end of a turn; without the plugin: `showtime receipt <job> --transcript <file>`
  (or `SHOWTIME_TRANSCRIPT`). Usage per model message (input, output, cache read, cache write; sub-agent logs beside
  the session are added; a message logged twice counts once). Window: the job's start to its last update plus 30
  minutes; `--whole-session` counts everything. Cost is API-equivalent: the same tokens at public list prices
  (`lib/st/job/usage.py` `PRICES`, each read on its provider's pricing page, dated and sourced in the table: Opus 5.5,
  Sonnet 5.5, Sonnet 5, Fable 5.1, Haiku 4.5, GPT-6.1 Sol, GPT-6 Sol, GPT-6 Astra, Grok 4.7). A plan does
  not pay per video. A model with no price is listed with its tokens and no cost, and the total says it is a
  lower bound. Work the host keeps outside the session log is not counted, so treat it as a floor, not a bill.
- **Codex.** `--transcript <rollout.jsonl>`: tokens (input, cached, output, reasoning) from the cumulative
  `token_count` events in the window. Codex reports tokens, not dollars: cost says "not reported by this agent".
- **Devin.** Under Devin (or `--transcript <sessions.db> --host devin`) the CLI's session database
  (`~/.local/share/devin/cli/sessions.db`) is opened read-only; only each request's model id, time and token
  metrics are selected, from the sessions whose working folder holds the job. Devin reports tokens, not dollars:
  the cost is an estimate at the same API list prices (`PRICES`; Devin's ids drop their effort suffix, and a request
  past a model's long-context threshold is priced at that price) and is labelled "est.". SWE-2 has no list price
  there, so its tokens are listed unpriced and the total is a lower bound. A Fusion session lists the lead and the
  sidekick model with their share of the tokens.
- **Everything else, and the MCP path** (Claude Desktop, Cursor, ...): the server cannot see a session log, so
  tokens and cost say "not reported by this agent". The receipt still names the client through MCP.

## receipt.json (schema 1)

Keys never change meaning within a schema; new keys may be added.

```
schema, job, showtime, generated
request      {text, source}            text is masked (home paths, keys, e-mail addresses)
mode, platform, agent
assumptions  {not_checked[], checked[], decisions[{question, answer}], open_questions[]}
review       {packed, with_findings, pairwise, findings_files, self_reviewed, lead_review,
              rounds[{round, kind, findings, findings_files, self_review}],
              findings: null (no critic answered) | {raised, blockers, should_fix,
                        fixed[{id, severity, text, by, note}], waived[{id, severity, text, by, reason}],
                        open[{id, severity, text}]}}
delivery     {final, kind, poster?, share?, credits?, captions?, exports[], duration, size, fps, lufs, true_peak,
              target_lufs, qa, qa_fail, qa_warn}       file names only
qa           {runs, verdict, fail, warn, file}
renders      {full, preview, partial, spliced, seconds, source, list[{kind, file, seconds, span, spliced_from}]}
images       {total, by_kind{review, qa, snap, check, views, looks}, note}
time         {start, end, ends_at, wall_seconds, render_seconds, note}
usage        {status: "reported" | "not_reported", host, note?,
              tokens{input, output, cache_read, write_5m, write_1h, total}   (Codex: input, cached_input, output, reasoning)
              cost_usd (number | null), cost_note, prices_as_of, window,
              subagents?, models{<model>: {input, output, cache_read, write_5m, write_1h, messages, cost_usd, token_share?}}}
```

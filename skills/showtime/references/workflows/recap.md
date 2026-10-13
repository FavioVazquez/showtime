# Workflow: session recap (what an agent did, as a short film)

Read this when the user wants a video of what a coding agent did in a session: a recap for a pull
request description, a standup, a "what my agent did overnight" post ("make a video of this Claude
Code session", "recap my last session"). The command `showtime recap` reads a Claude Code transcript through an
allow-list and turns the facts into a 30-60 s narrated film; everything runs on this machine and nothing is uploaded (the bed may be a catalog
track downloaded once from its creator's site: nothing is sent; `--music <style>` or `SHOWTIME_OFFLINE=1` keeps it fully local).

## Essentials

- Route: `showtime recap --latest` (this folder's newest session) or `showtime recap <session.jsonl>`;
  it writes `<out>/script.md` and stops (also with `--yes`). Show the user script.md; only after they
  have read it run the same command with `--yes` (§ Steps)
- Never hand-write a recap from a transcript: transcripts hold keys, memory, private paths and other
  projects. The command keeps only allow-listed facts (§ What reaches the film)
- Edits go in script.md (change or delete lines), never in the generated page; the hard filter drops
  keys, absolute paths, URLs, hosts and e-mail addresses again on `--yes` (§ What reaches the film)
- Diff stats: the session's own commits by default; `--since <ref>` for a branch's whole change;
  `--repo <dir>` when the session ran in a worktree that is gone (§ Inputs)
- `--no-voice` for a silent cut, `--aspect 9:16` for a vertical one, `--preview` for a fast draft;
  the command checks, renders and runs `showtime qa` itself (§ Steps)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inputs | 33-41 |
| What reaches the film | 43-79 |
| The film | 81-91 |
| Steps | 93-107 |
| Pitfalls | 109-140 |
| Read next | 142-145 |

## Inputs

- One Claude Code transcript: `~/.claude/projects/<project>/<session>.jsonl` (sub-agents under
  `<session>/subagents/agent-<id>.jsonl`, their short description beside them), a session id, or
  `--latest` (run inside Claude Code, that is the session in progress). `CLAUDE_CONFIG_DIR` moves the
  folder. A session's recap covers its own transcript, not its sub-agents': recap those separately.
- The repository the session worked in: its working folder by default, `--repo <dir>` otherwise (a
  worktree under `.claude/worktrees/` that has been removed still maps to the repository's paths).
- Diff stats: `--since <ref>` (`git diff <ref>`, working tree included), else the commits the session made.

## What reaches the film

Only this allow-list (every line of the film is in script.md; tool names and counts are kept in
facts.json only):

- the title and the hook from the facts alone ("42 min · 6 files edited · red to green", the date, the
  counts); no free text from the session is film text by default;
- tool names (Claude Code's own; any MCP tool is "MCP tool", anything else "other") and counts; file
  paths relative to the repository, for files inside it (secret files such
  as `.env` and the `.git` folder count as outside);
- commands as a program name from a fixed list (git, npm, python, pytest, grep, curl ... ; anything
  else, a client's CLI or a script of the user's own, counts as "other"), with the program's own
  subcommand (`git commit`, never an alias, plugin or extension), a make or rake target only when
  generic, and `python -m` only for a runner (`pytest`, `unittest`, `pip`); never a script or module path;
- test runs (a runner in the program position: not an install, a lint or a `--version`) as counts read
  from the end of their output (pytest, unittest, jest, cargo, go, node, run_all); git diff stats;
  commits whose hash, as `git commit` printed it, is in this repository's history; active time (pauses
  of 10 min or more left out).

The request (the first user message, never a compaction summary) and a sub-agent's description are
offered in script.md only as `# show ...` suggestions, cleaned strictly (a sentence naming a path, host,
address, key, value-like word or digit groups ends the suggestion). They reach the film only if the
user uncomments one; any line of script.md that recap did not write (a title, a caption, a narration
line, a label) goes through the same strict rule and the hard filter, and the command names each line
it refused (recap's own line is used instead, or the line is left out when recap writes none). Which
lines are recap's own is decided by comparing shapes with what recap writes from the current facts,
never by trusting a file on disk: the line recap writes now, the same line with older counts (a count
standing alone, up to 5 digits in all, 12,345 included; never inside a file name), a file row or callout
that is exactly a file the session edited, a files line that names one exactly, or a "Most used" line
made only of allow-listed programs with a count. So rerunning while the session grows keeps your
script.md as you left it, on every call; anything else you wrote is checked as written. The suggestions
are never kept in facts.json or the project.

Assistant text, thinking, tool output, memory, attachments, absolute paths, URLs and the environment
are not on the list, and tool output is read only to count tests and commits. A hard filter then drops
any line that looks like a key, a path, a URL, a host or an e-mail address. Filters can miss things:
that is why nothing renders until the user has read script.md.

## The film

30-60 s, 16:9 (or `--aspect 9:16`), a light paper look (warm paper, ink, one rust accent): hook (a
title from the facts, the date, the counts), the numbers, a living timeline (read, edit, run and test lanes filling as a playhead
sweeps the session, edited files called out where they were first edited, the top commands), where the
edits landed (+/- per file from git), the tests red to green (one dot per run), the diff, an end card.
Narration with `showtime voice` (default `af_heart`) and burned captions; scenes are as long as their
line, and a scene with more to read gets a pause after it. The bed comes from the session (no sound on the cuts; `--cut-sounds` adds a soft swoosh)
(a catalog track, fetched once and cached, else a composed style; the same session sounds the same, another
one does not); `--music <style|catalog-id|none>` pins the bed. A CC BY track writes `recap.credits.txt` next to
the video (the command prints it and any Content ID note): keep that credit where you post it.

## Steps

1. **Script.** `showtime recap --latest` (or a transcript path) prints a one-line summary and writes
   `<out>/script.md` and `<out>/facts.json`; `<out>` is `showtime-out/recap-<session>` unless `--out`
   is given (refused where git would track it). Nothing is rendered yet.
2. **Read it with the user.** Every `show` line is on screen, every `say` line is spoken. Change a line
   or delete it; keep the keys (`show hook.title:`). To use the request as the title or under it,
   uncomment its `# show` line. Editing script.md is the only way to change what is on screen.
   *Done when:* the user has read script.md.
3. **Render.** The same command with `--yes`: it narrates (`voice/narration.md`), writes
   `<out>/project`, runs `showtime retime --from-voice`, `showtime check`, renders `<out>/recap.mp4`
   and runs `showtime qa` (PASS or WARN). `--preview` for a draft first, `--no-render` to stop at the
   project. `--fresh` rewrites script.md from the session (dropping edits).
4. **Look.** `showtime look <out>` (one composite of the scenes) before sharing; for a pull request,
   `showtime deliver exports <out>/recap.mp4 --targets github` makes a copy under 10 MB.

## Pitfalls

- Rendering before the user read script.md: a call that writes script.md never renders, `--yes` or not.
- A session in a removed worktree with no `--repo`: the command says so; pass the repository.
- Parallel agents committing to one repository: without `--since`, only the commits whose hashes the
  session's `git commit` printed count. `git commit -q` prints none, so such a commit is not counted;
  `--since <ref>` gives the change instead.
- Tests run in the background or with their output cut: they show as grey dots, uncounted.
- What the text guard is for: it keeps private text that slips in by accident, in the forms people write it,
  out of the film. That covers pasted keys and tokens, card, phone and ID numbers, paths, e-mail addresses, IPs and
  copy-paste artefacts. It does not stop you from disguising your own text on purpose: you wrote script.md, and you
  read it before anything renders.
- What it refuses in a line you write:
  - keys and tokens (vendor prefixes, a key name with its value, long hex or key-like runs), absolute paths,
    URLs, hosts, IPs and e-mail addresses;
  - a long number: 6+ digits in a row; three or more digit groups, whatever separates them; a chain of groups
    across punctuation or words of 1-4 letters holding 9+ digits in all (`SSN 123 and 45 and 6789`,
    `4 1 1 1 ...`); and two groups side by side when one has 4+ digits (`4111 1111`);
  - a line holding an invisible format or bidi character (a zero-width space, a soft hyphen). Every line is
    judged NFKC-folded, without combining marks or invisible fillers. A zero-width joiner inside an emoji is fine.
- Over-refusal on purpose: `Closes #12 #34 #56` (three groups) and a line over 2000 characters. These pass:
  `between 2024 and 2026`, `From 2024-2026`, `1920×1080`, `Node 18, 20 and 22`, `Python 3.11, 3.12 and 3.13`.
- A suggestion is only as clean as its rules: a nested block inside the request's own text, or an unknown
  tag in the middle of a line, can leave some of that text in the `# show` comment. Read it before you
  uncomment it.
- Known residual, and why you read script.md first:
  - Deliberate disguise passes: a number split by 5+ letter words (`4111 digit 1111 ...`), or digits written
    out as words.
  - An edited file whose own name is private (`data/4111111111111111.csv`) is shown and spoken in recap's own
    rows, callouts and files line, and it is kept in facts.json, because the session did edit it.
  - Counts carry digits by design: up to 5 per count, so up to 15 in a line with three counts. A "Most used"
    line holds at most 4 programs, each named once, with counts of 1-99999.

## Read next

`references/workflows/changelog-video.md` (a PR video from the diff), `references/voice.md`,
`references/captions.md`.

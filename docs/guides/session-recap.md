# Make a short film of what your agent did

Your coding agent worked for an hour: it read files, edited some, ran the tests until they passed, and committed.
A 30-60 s film of that is quicker to share than the log, in a pull request description, a standup or a post about
what your agent did overnight. `showtime recap` makes one from the session log on your machine, without reading
the conversation's text into the film.

## Say this

> "Make a recap video of this session."

Or run it yourself, in the folder the session worked in:

```bash
showtime recap --latest           # writes script.md and stops
showtime recap --latest --yes     # after you read script.md: renders it
```

`--latest` is this folder's newest Claude Code session; inside Claude Code that is the session you are in. A
`.jsonl` path or a session id works too.

## What happens

1. It reads one transcript (`~/.claude/projects/<project>/<session>.jsonl`) through an allow-list: times, turn and
   tool counts, paths of files inside the repository, program names from a fixed list (`git`, `npm`, `pytest` and
   the like; anything else counts as "other"), test counts read from the end of each test run, and the commits the
   session made, with their diff stats from git.
2. It writes `script.md` (every line that will be shown or spoken) and `facts.json`, prints a one-line summary
   such as `17 min, 14 turns, 12 tool calls, 1 repo file, 1 edited, 3 test runs (red to green)`, and stops. Even
   with `--yes`, a call that writes `script.md` never renders.
3. You read `script.md`. Change a line or delete it; the request you typed is there only as a commented `# show`
   suggestion, and reaches the film only if you uncomment it.
4. The same command with `--yes` checks every line again, narrates with a local voice, renders `recap.mp4`, and
   runs `showtime qa`.

Assistant text, tool output, memory, absolute paths, URLs and the environment are never on the list. A hard filter
also drops any line that still looks like a key, a path, a URL, a host or an e-mail address, in the lines you
write too. It is there to keep private text that slips in by accident out of the film; it does not stop you from
disguising your own text on purpose, which is why nothing renders until you have read `script.md`.

## What you get

- `recap.mp4`: 16:9 at 1920x1080 (or `--aspect 9:16`), narrated and captioned, in a light paper look: the title
  from the facts ("42 min · 6 files edited · red to green"), the numbers, a minute-by-minute timeline, where the
  edits landed, the tests red to green, the diff and an end card.
- `script.md` and `facts.json`: what the film was made from.
- `recap.credits.txt` when the music needs a credit, and a `project/` you can edit and render again.

Files go to `showtime-out/recap-<session>` unless you pass `--out`, which is refused where git would track it.

## How long it takes

Tried for this guide on the test session in `skills/showtime/tests/fixtures/recap/` (17 minutes of work, pointed
at a small temporary repository), on a 6-core Intel Mac: the `--yes` call took 1 min 36 s for a 37 s film, 1 min
06 s of it the render.

## Phrases that change it

- "Vertical" sets `--aspect 9:16`.
- "No voice" sets `--no-voice` (no narration and no captions; each scene holds long enough to read).
- "A quick draft" sets `--preview`.
- "The whole branch, not just this session's commits" sets `--since <ref>` for the diff.
- "Quiet ambient music" or "no music" sets `--music ambient-pad` or `--music none`. By default the bed is picked per session from
  showtime's music catalog (downloaded once from its creator's site; nothing is sent), so two recaps do not sound
  the same, and a rerun keeps its bed. `SHOWTIME_OFFLINE=1` keeps it fully local.

## Limits

- One transcript per film: a session's recap does not include its sub-agents' transcripts; recap those separately.
- Commits made with `git commit -q` print no hash, so they are not counted; `--since <ref>` gives the change instead.
- Tests run in the background or with their output cut show as grey dots, uncounted.
- Filters can miss things. Read `script.md`, and watch the film before you post it.

## The example

[The recap demo](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/_recap) is the test session as a 37 s film, with its `script.md`, its
`facts.json` and a list of what reached the film and what did not. Your agent's guide:
[recap.md](../../skills/showtime/references/workflows/recap.md).

# Workflow: pull request, release or changelog video

Read this when the video is about a change: a pull request, a release, a version's changelog, a diff,
a "what's new this week" ("turn PR 482 into a 30 s video", "a release video for v2.3"). The story
comes from the change itself; the code is shown as real hunks, never whole files.

## Essentials

- A PR turned into a video for its description: `showtime pr-video <N | URL>` is the route (it reads the PR
  itself with gh or GitHub's API, renders and exports under 10 MB). Plan it and name it, even when the PR
  cannot be read from here: never describe a PR you have not read (§ PR video in one command)
- Release notes or a CHANGELOG section given: this workflow, only their items, in their words: a hook or
  tagline restates one item and adds nothing; an install line, URL, output or numbers only from a source (the
  README, the release page, a run you saved), else left out or marked for the user to fill (§ Pitfalls).
  `showtime release-video
  <notes.md> -o <project> --name <product> --version <v>` writes a plain honest draft from them (§ Unattended)
- Defaults: 20-40 s, 16:9, at most 6 scenes, no push or cut per item. For users: the `launch` grammar
  (`launch-video.md`, `showtime audio cuts`); for contributors: `dom` template, `technical` tone, 2-4 real
  hunks of 4-12 lines (§ Defaults)
- Read the change (`git log --oneline <from>..<to>`, `git diff --stat`); per change, what a user can now do,
  with its commit or PR as the source (§ Steps)
- `showtime new launch <job>/project` or `showtime new dom <job>/project --title "<Product> <version>"`; end
  on the version and, when a source says it, where to get it. Code via
  `showtime code <before-file> --to <after-file>` (§ Steps)
- Only what shipped; numbers only from the PR, CI or release notes; no internal names; credit the authors
  (§ Pitfalls)
- `showtime check`, `showtime snap`, `showtime render <job>/project --job <job>`, `showtime qa <job>` (§ Steps)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inputs | 40-44 |
| Defaults | 46-55 |
| Steps | 57-82 |
| Unattended (CI, no agent) | 84-90 |
| PR video in one command | 92-120 |
| Pitfalls | 122-133 |
| Read next | 135-138 |

## Inputs

- The change: a PR (its description, commits and diff), a tag range (`git log v2.2..v2.3`), a
  CHANGELOG section, or release notes.
- Helpful: who it is for (users or contributors), the platform, the authors to credit.

## Defaults

20-40 s, 16:9; a release announced to users ("v2.0 is out", "a video for the 2.0 launch") follows the
launch grammar in `launch-video.md`: the `launch` template, 4-6 scenes, one window that carries the
changes one per scene, continuous camera handoffs, a produced track cut with `showtime audio cuts`.
A code-level what's-new for contributors: `dom` template (code panels) with the `technical` tone, a
restrained produced track (`showtime audio cuts --for tech`) or a composed `minimal-pulse` bed; 2-4
real hunks of 4-12 lines each. Either way: at most 6 scenes, no push or cut per item, credit the
authors by the names they use in the repo. State the audience (users, unless the change is internal)
as an assumption; ask only when the request leaves it open and the two cuts would differ.

## Steps

1. **Job.** `showtime job init <repo>-<version> --goal "..."`.
2. **Read the change.** With git: `git log --oneline <from>..<to>`, `git diff --stat <from>..<to>`,
   and the diffs of the files that matter. With a PR: its description, linked issue, and the diff.
   Separate user-visible changes from internal ones. *Done when:* you can say, per change, what a user
   can now do (or no longer suffers), with its commit or PR as the source.
3. **Pick the shape** (`story.md` section 4, PR / changelog): a changelog (hook, 2-4 equal items,
   wrap), a feature reveal (outcome, impact, the change, the diff, the mechanism, callback), a fix
   explainer (problem, cause, before/after, working), or a refactor (the smell, before/after structure,
   same outputs). The hook speaks outcome language, not file names.
4. **Project.** Announcement: `showtime new launch <job>/project --duration <len>` (one proof scene per
   change, up to three; the rest go in the end card's value line or the post copy). Code walkthrough:
   `showtime new dom <job>/project --title "<Product> <version>" --duration <len>`, one scene per change,
   code and mechanism in the same panel. Both end on the version and, from a source, where to get it.
5. **Material.**
   - Code: save the before and after versions of each hunk you will show, then
     `showtime code <before-file> --to <after-file> -o <job>/project/code/<name>.json` for a diff
     panel, or `showtime code <file> -o <job>/project/code/<name>.json` for a single file
     (`--theme`, `--lang` as needed). The `code-block` component plays it (`diffAt`, `highlight`, `focus`).
   - UI changes: capture before and after (`showtime site capture` on each build, or
     `showtime demo record` for the new flow; `capture.md`, `tutorial-recording.md`).
   - Numbers (speed-ups, sizes): only from benchmarks in the PR, CI output, or release notes.
6. **Sound, first look, final, verify, deliver** as in the pipeline: `showtime check`, `showtime snap`,
   `showtime render <job>/project --job <job>`, `showtime qa <job>`, share copy that
   links the release, the delivery card.

## Unattended (CI, no agent)

`showtime release-video <notes.md> -o <project> --name <product> --version <v>` writes a plain,
honest project from the notes alone (their headings and lines verbatim, reading-time holds, a
composed bed); `--changelog-version <v>` reads one section of a CHANGELOG, `--kind pr` a PR
description. The GitHub Action (`docs/github-action.md`) runs it on every release. It has no angle
and no demo: when an agent is available, this workflow makes the better film.

## PR video in one command

`showtime pr-video <N | URL>` turns a pull request into a short video to drag into its description, with
no agent: it reads the PR with `gh pr view` and `gh pr diff` (a paginated `gh api` call when the file list is
capped at about 100), writes `<out>/project` in the release-video look, checks and renders it, and exports
`<out>/pr-<N>.mp4` plus `pr-<N>.github.mp4` under GitHub's 10 MB attachment limit (`deliver exports --targets
github`). It prints two Markdown lines to paste into the PR; you drag the file onto them (nothing is uploaded).
The length follows the PR: about 16-20 s of budget for a small one, up to 45 s for a big one; the holds follow
the phone check's reading speed (17 characters or 3 words a second). Scenes: the hook (repo, number, title,
author), the description one phrase per frame (long sentences cut at a clause; template chrome such as test
plans, checklists and reviewer notes is left out), the files changed as a tree with +/- counts and the tests
touched, one or two real hunks (lockfiles, generated files and secret files are never picked), and a closing
card (the description's user-facing section when it has one, then the PR URL). No film grain, so the files stay
small. Values that look like secrets (keys, tokens, `.env` values, private keys) are masked in the diff, the
title and the description before anything is written, and the output says how many.

- No gh, or not signed in: a public PR on github.com is read from GitHub's REST API without signing in (no
  token is sent; 60 requests an hour, two per video; a private repository or a used-up limit says so). Or pass
  it yourself: `--diff pr.diff --body pr.md --title '...'` (plus `--repo`, `--author`), a saved `--pr-json`
  (gh's JSON or a REST `pulls/N` object), or `--base main` in the repo (`git diff main...HEAD`; a single commit
  gives the title and body).
- `--out DIR` is the output folder, its own job (default `pr-<N>-video`, beside the job folder when run inside
  one; `--force` writes into a non-empty project folder); `--url` sets the PR URL on the closing card.
- `--no-render` writes only the project; `--aspect 9:16|1:1|4:5`, `--max-items N` (description lines, default 4),
  `--preview` for a quick draft, `--keep-work` keeps the render's `pr-<N>.work/` folder (removed after the
  export otherwise), `--background` for hosts with short command timeouts.
- A PR too big to show in full (more files than GitHub lists, or a diff GitHub will not send) still gets a
  video: the true file count on screen, the tree and hunks from what was listed, and a note in the output.
- Like `release-video` it has no angle: for a feature reveal or a before/after demo, follow § Steps.

## Pitfalls

- Inventory hooks ("23 files changed"): a number goes in the hook only when it carries stakes.
- Whole files or tiny code: 4-12 lines per hunk, sized to read at 1080p (`typography.md`).
- Internal names on screen (branch names, ticket ids, private hostnames): translate to what users see.
- Features that are not in this release, or claims from the roadmap: only what shipped.
- Example commands and output that nobody ran: run them on a sample input, keep the exact output
  in `<job>/work/evidence/`, or keep the example obviously generic (`story.md` section 6).
- Taglines and end cards that add a claim: "See exactly what changed", "Loads cleanly now" or an install
  command the notes never gave. Restate an item, or mark the line as draft copy for the user to confirm;
  end on the version alone when nothing says where to get it.
- Forgetting the people: credit the authors (from the commits or PR) on the end card or in share copy.

## Read next

`references/story.md`, `references/components.md` (code-block), `references/capture.md`,
`references/typography.md`, `references/platforms.md`.

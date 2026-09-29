# Workflow: pull request, release or changelog video

Read this when the video is about a change: a pull request, a release, a version's changelog, a diff,
a "what's new this week" ("turn PR 482 into a 30 s video", "a release video for v2.3"). The story
comes from the change itself; the code is shown as real hunks, never whole files.

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
   code and mechanism in the same panel. Both end on the version and where to get it.
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

## Pitfalls

- Inventory hooks ("23 files changed"): a number goes in the hook only when it carries stakes.
- Whole files or tiny code: 4-12 lines per hunk, sized to read at 1080p (`typography.md`).
- Internal names on screen (branch names, ticket ids, private hostnames): translate to what users see.
- Features that are not in this release, or claims from the roadmap: only what shipped.
- Example commands and output that nobody ran: run them on a sample input, keep the exact output
  in `<job>/work/evidence/`, or keep the example obviously generic (`story.md` section 6).
- Forgetting the people: credit the authors (from the commits or PR) on the end card or in share copy.

## Read next

`references/story.md`, `references/components.md` (code-block), `references/capture.md`,
`references/typography.md`, `references/platforms.md`.

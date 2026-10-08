# Make a video of a pull request

A short video in a pull request's description shows reviewers and users what changed faster than a list of
files. `showtime pr-video` makes one in a single command, with no agent in the loop: about 20-45 s, under
GitHub's 10 MB attachment limit, ready to drag into the PR.

## Say this

> "Make a video of PR 482 for its description."

Or run it yourself in a clone of the repository:

```bash
showtime pr-video 482
showtime pr-video https://github.com/acme/tool/pull/482 --out pr-482
```

## What happens

1. It reads the PR with `gh pr view` and `gh pr diff`. Without `gh`, or not signed in, a public PR on github.com
   is read from GitHub's API without signing in. You can also pass it by hand: `--diff pr.diff --body pr.md
   --title '...'`, a saved `--pr-json`, or `--base main` to diff your local branch.
2. Lines that look like secrets (keys, tokens, `.env` values, private keys) are masked in the diff, the title and
   the description before anything is written, and the output says how many.
3. It writes `<out>/project`: a hook (repo, number, title, author), the description's own lines, the files changed
   with their +/- counts and the tests touched, one or two real hunks, and a closing card with the PR's URL.
   Every word on screen comes from the PR or a flag. A description with a list shows each item by its bold lead
   (or its first sentence), and "+ N more" counts the items left out.
4. It checks and renders the project, then makes the copy under 10 MB (`deliver exports --targets github`).
5. It prints two Markdown lines to paste into the PR description. You drag `pr-482.github.mp4` onto the comment
   line and GitHub uploads it. showtime uploads nothing.

## What you get

- `pr-482/pr-482.mp4` and `pr-482/pr-482.github.mp4` (under 10 MB).
- `pr-482/pr-482.md`: the lines to paste.
- `pr-482/project/`: an ordinary showtime project you can edit and render again.

## How long it takes

Tried for this guide on the test PR in `skills/showtime/tests/fixtures/pr/` (a saved PR and its diff), with
`--preview`, on a 6-core Intel Mac with a load average around 50:

```bash
showtime pr-video 482 --pr-json acme-482.json --diff acme-482.diff --repo acme/tool --preview --out pr-482
```

It made a 22 s video (668 frames at 1280x720) and a 2.9 MB GitHub copy in 2 min 18 s, of which 28 s was the
capture and 14 s the encode. A full-size render of a real PR was not timed here.

## Phrases that change it

- "Vertical" or "square" sets `--aspect 9:16` or `1:1`.
- "Show more of the description" raises `--max-items` (4 by default; the rest are counted on screen).
- "Just the project, I'll render it" sets `--no-render`.
- "A quick draft" sets `--preview`.

## In CI: the GitHub Action

The [showtime GitHub Action](../github-action.md) renders a video on the runner with no key and no agent. On a
pull request event it uses the PR's title and description (`showtime release-video --kind pr`), checks and
renders the film, runs qa, exports an HTML video and a copy under 10 MB, and uploads them as a workflow artifact.
It does not show the diff; `showtime pr-video` does.

## Limits

- It has no angle. For a feature reveal or a before-and-after demo, ask your agent for a changelog video
  instead ([changelog-video.md](../../skills/showtime/references/workflows/changelog-video.md)).
- A private repository needs `gh` signed in. Without signing in, GitHub allows 60 API requests an hour (two per
  video).
- A very large PR still gets a video, with the true file count on screen and hunks from what GitHub listed.
- Masking catches values that look like secrets. Read the diff before you post a video of it.

## The example

[Example 29](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/29-pr-video-showtime) is `showtime pr-video` on showtime's own PR #7: 40 s in 41 s on a
64-core machine, a 9.4 MB copy and the Markdown to paste. [Example 15](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/15-oss-release-black) is a release video an agent made from real diffs, the longer
way round.

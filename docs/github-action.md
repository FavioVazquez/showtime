# The showtime GitHub Action

A composite action that makes a video in CI: a short film of a release, from the release notes, with no API key
and no agent. It installs showtime on the runner, turns the notes into a project, checks it, renders it, runs
`showtime qa` on the finished file, exports a single-file HTML video, and uploads the result.

```yaml
- uses: FavioVazquez/showtime/.github/actions/showtime-video@v0.3.0
```

The complete workflow to copy is [`examples/showtime-release-video.yml`](examples/showtime-release-video.yml).

## What it is, and what it is not

- It runs showtime's own command line: `showtime release-video` (release notes or a pull request description to a
  ready-to-render project), then `check`, `render`, `qa`, `export html` and a copy under 10 MB (`deliver exports --targets github`). Every word on screen comes from your
  notes or from an input; nothing is invented, and the music is composed on the runner.
- The film is the **unattended fallback**: a hook card, one scene per group of changes, an end card. A film with
  an angle (a demo of the new feature, a real diff) is made with a coding agent
  ([changelog workflow](../skills/showtime/references/workflows/changelog-video.md)); the Action does not run an agent
  unless you configure one (mode `agent`, below).
- It reads no key and sends nothing anywhere. Files leave the runner only through the upload you choose: a workflow
  artifact or your own release page.

## Three modes

| `mode` | Needs | What runs |
|---|---|---|
| `release` (default) | nothing: no key, no agent | the notes come from the `notes` input, a `notes-file`, a `changelog` + `version`, or the event that started the run: a published release (its tag, name, date, page and description) or a pull request (its title and description, `--kind pr`, version `#<number>`). Then `job init`, `release-video`, `check`, `render`, `qa`, `export html`, and with `vertical: true` a 9:16 render and its qa |
| `project` | a showtime project folder committed in the repository (made earlier by a person or an agent) | `job init`, `check`, `render`, `qa`, `export html` on it |
| `agent` (optional, bring your own) | a coding-agent command you write, and your own API key as a secret | your `agent-command` runs with `SHOWTIME_PROMPT` (the `prompt` input), `SHOWTIME_BIN` (the showtime launcher), `SHOWTIME_JOB` and `SHOWTIME_OUT` (the job folder), and `SHOWTIME_NOTES` when notes were found. Afterwards the Action runs `qa` and `export html` itself, and fails when no final video exists |

In agent mode the Action never needs or reads a key: give it to your agent's step with `env:` in your workflow, as
in the last variant of the example. The agent CLI must be installed by an earlier step of yours and must have
showtime's skill ([how](agents.md)); this is not tested here beyond the plumbing.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `mode` | `release` | `release`, `project` or `agent` |
| `notes` | | release mode: the notes as Markdown text (first choice when set) |
| `notes-file` | | release mode: a Markdown file in the repository (needs `actions/checkout` first) |
| `changelog` | | release mode: a CHANGELOG file; the section of `version` is used. With `version` set and no other notes, `CHANGELOG.md` is used when it exists |
| `version` | the release tag, or `#<number>` for a pull request | the version shown; for a CHANGELOG, the section to use |
| `name` | the repository name | the product name on the hook card |
| `install` | none is shown | install or upgrade command for the end card |
| `url` | the release or pull request page, else the repository | URL on the end card |
| `max-items` | 7 | lines of the notes shown in all; the rest are counted on screen |
| `project` | | project mode: the project folder (with `showtime.json`) in the repository |
| `agent-command` | | agent mode: the shell command that runs your agent |
| `prompt` | | agent mode: what to make, passed as `SHOWTIME_PROMPT` |
| `vertical` | `false` | also render 9:16 (its layout is checked first) and run qa on it for reels |
| `platform` | generic checks | destination for qa: `reels`, `tiktok`, `shorts`, `youtube`, `web`, `github`, `broadcast`. It sets length, aspect, loudness and size limits, so pick it only when the video is really for that place: the default render is 37 to 54 MB for 23 to 33 s, which the 10 MB `github` limit would flag |
| `upload` | `artifact` | `artifact`, `release` or `none` |
| `artifact-name` | `showtime-video` | name of the uploaded artifact |
| `release-tag` | the tag of the release event | upload `release`: the tag to attach the files to |
| `github-token` | `${{ github.token }}` | upload `release`: the token for `gh release upload`; used for nothing else |
| `cache` | `true` | cache the installed showtime runtime between runs |
| `tier` | `minimal` | `showtime setup` tier: `minimal` is enough for this action; `core` or `full` add more |
| `browser-deps` | `true` | Linux: when the browser does not start, install its system libraries with `sudo` (as `scripts/e2e.py` does) |
| `showtime-path` | the checkout the action came from | run a different showtime checkout (a repository root or its `skills/showtime` folder) |

## Outputs

| Output | Meaning |
|---|---|
| `video` | path of the final MP4 |
| `html` | path of the single-file HTML video (plays offline in any browser; about 1 MB) |
| `poster` | path of the poster frame (JPEG) |
| `vertical` | path of the 9:16 MP4 when `vertical` is true |
| `qa` | the qa verdict of the final video: `PASS`, `WARN` or `FAIL` |
| `job` | the job folder: final video, exports, the qa report, contact sheets and frames |

A run also writes a short summary (qa verdict with loudness and true peak, file sizes, time) to the workflow run page.
A qa `FAIL` fails the step (exit code 1), but the outputs and the files are still reported, and the artifact upload
still runs, so you can open the failing video and its report.

## Uploads and permissions

- `artifact` (default): the MP4, its copy under 10 MB (`-github.mp4`, for release pages, PR comments and READMEs), the 9:16 MP4, the HTML video, the poster, `qa.json`, and `share.txt` / `credits.txt`
  when they exist, as one artifact kept 14 days (`actions/upload-artifact`). Needs `contents: read`.
- `release`: `gh release upload <tag> <files> --clobber` on the release the run belongs to (or `release-tag`), with
  `github-token`. Needs `permissions: contents: write` in your workflow. The files are named after the release
  (`release-<name>-<version>.mp4`, `.html`, `-poster.jpg`, ...) so `final.mp4` never collides on a release page.
- `none`: nothing is uploaded; read the outputs in a later step.

The action uploads nowhere else. A pull request from a fork gets a read-only token, so use `artifact` there.
Text from a release or a pull request reaches the action through the event file and environment variables, never
by expanding it inside a shell script, so a title such as `$(rm -rf ~)` is only a title.

## The cache

The showtime home (default `~/.showtime`: ffmpeg, the Python environment, the Node packages, the models of the
tier) is restored from `actions/cache` with the key
`showtime-action-<OS>-<arch>-py<version>-<tier>-<hash of the setup files>`, the hash computed by `run.py prepare`
from `skills/showtime/setup/` (`manifest.json`, `requirements.txt`, `package.json`, `package-lock.json`, `setup.py`)
because `hashFiles` only sees the workspace. There is no restore-key fallback: a hit is an exact match. `logs`,
`cache` and `runs` are left out. The cache is saved right after setup, so a render that fails still leaves the
next run a warm home. On a hit the setup step runs `showtime doctor --quick` and skips the install when it passes.
With `cache: false` every run installs from nothing.

Measured on a 64-core Linux box with fast disks and shared package caches (not a GitHub runner): the minimal tier
installs in 25 s and the home is 1.6 GB on disk (Python environment 0.9 GB, ffmpeg 0.3 GB, models 0.2 GB, Node
packages 0.15 GB); a warm run's setup step takes 5 s. Times on a hosted runner (2 to 4 cores, a fresh network)
will be longer; they have not been measured.

## Runners

Ubuntu is the tested path, tested here on a Linux x64 machine outside GitHub (showtime found the installed Chrome
there; hosted images ship Chrome, but this action has not run on one, and the sudo step for system libraries runs
only when the browser does not start). macOS and Windows runners use the same steps as
`.github/workflows/e2e.yml`, and on Windows `run.py` calls showtime through its Python launcher rather than
`showtime.cmd`, so titles with `&` or `%` are not re-read by `cmd.exe`. macOS and Windows have not been run with
this action.

## Try it without GitHub

```bash
python3 .github/actions/showtime-video/run.py --dry-run    # the commands and the resolved notes, title, version
.github/actions/showtime-video/local-run.sh /tmp/st-action  # the real steps against a made-up GitHub environment
```

`--dry-run` needs the GitHub environment of your event (`GITHUB_EVENT_NAME`, `GITHUB_EVENT_PATH`, `GITHUB_REPOSITORY`)
or a notes input, for example `INPUT_NOTES=$'- One\n- Two' python3 .../run.py --dry-run`. `local-run.sh` builds a
sample repository and a release (or, with `--event pull_request`, a pull request) payload, runs `prepare`, `setup`
and `run` as the action does, and prints the timings and the step outputs. Upload is a separate step of the action
and is not run there.

## Limits

- Release notes with no bullet lines outside the internal sections (dependencies, CI, docs, chores) have nothing to
  show: the command says so and the step fails; write the notes on the release or pass `notes`.
- The final MP4 is showtime's default quality (CRF 16), about 1.6 MB per second of film at 1080p (measured), so the
  action also writes a copy under GitHub's 10 MB limit (`showtime deliver exports <job> --targets github`; a failure
  there does not fail the step). The HTML video is under 1 MB and is the light way to share.
- `check` errors (text clipped, contrast, layout) fail the step before any render; `qa` findings of level FAIL fail
  it after.

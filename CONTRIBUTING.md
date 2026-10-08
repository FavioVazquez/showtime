# Contributing to showtime

Thanks for helping. showtime is a Claude Code skill that makes videos entirely on the user's machine, on
macOS (Apple Silicon and Intel), Windows 10/11 and Linux. Read [CONTEXT.md](CONTEXT.md) for the words we
use and [.out-of-scope/](.out-of-scope/README.md) for what we have decided not to do. Everyone here follows
the [code of conduct](CODE_OF_CONDUCT.md). Bugs, feature ideas, example requests and docs problems each
have an issue form; questions and videos you made go to
[Discussions](https://github.com/FavioVazquez/showtime/discussions).

## Set up a development checkout

```bash
git clone https://github.com/FavioVazquez/showtime
cd showtime
skills/showtime/bin/showtime setup            # Windows: skills\showtime\bin\showtime.cmd setup
skills/showtime/bin/showtime doctor
```

To try your working copy inside Claude Code without installing the plugin, link it as a personal skill
(development only; the published install is the plugin):

```bash
skills/showtime/bin/showtime setup --link     # ~/.claude/skills/showtime -> this checkout
```

## Ground rules

1. **Everything runs locally.** No cloud AI services, API keys, accounts, uploads or telemetry. The network
   is for downloads (pinned by URL, size and SHA-256 wherever the source allows) and for public web sources
   the user asks for (archive media search, site capture), which fetch and never send the user's files.
2. **Cross-platform is not optional.** Python (stdlib-only for the launcher and installer) and Node only;
   no shell-only logic. Use `pathlib`, pass subprocess arguments as lists (never a shell string), handle
   `.exe`, and put file paths into ffmpeg filter arguments with `st.ff.filter_path()`. Never call a bare
   `ffmpeg`: go through `st.ff` (or `scripts/lib/ff.mjs` in Node). Fonts are files fetched by setup, never
   system font names.
3. **Original work, clean licenses.** Write your own code and docs. Libraries are installed by setup and
   pinned; assets and models must allow commercial use (CC0, public domain, OFL, MIT, Apache; CC-BY only
   with automatic credits).
4. **Friendly by default.** Every command has `--help` with examples and sensible defaults. Errors say
   what went wrong, why, and the exact fix (`ShowtimeError(message, why=..., hint=...)`); tracebacks
   appear only with `--debug`. Anything slower than 30 s announces an estimate and shows progress
   (`st.common.estimate()` and `st.common.Progress`). Optional extras are never installed silently: call
   `st.common.require_extra(name, feature)`.
5. **Never overwrite earlier work.** Outputs go to a fresh `showtime-out/<slug>-<timestamp>/` folder unless
   the user names a file.

## Adding a command

- Python: add `skills/showtime/lib/st/cli_<module>.py` with a literal `COMMANDS = {"name": "one line"}` and
  `register(subparsers)`; the CLI discovers it. Node: add `skills/showtime/scripts/<name>.mjs`; the
  launcher routes `showtime <name>` to it.
- Put the command in a group in `skills/showtime/lib/st/launcher.py` (`GROUPS`) so `showtime --help`
  shows it with an example.
- Mention it in SKILL.md or a reference only as it really exists: `scripts/check_release.py` fails when the
  docs name a command or sub-command the CLI does not have.

## Tests

```bash
python skills/showtime/tests/run_all.py --fast        # what CI runs on every pull request (11 min on a clean Ubuntu machine, 18 on Windows and a macOS VM)
python skills/showtime/tests/run_all.py               # everything (longer; renders, voice, ASR)
python skills/showtime/tests/run_all.py -k audio      # one module
python skills/showtime/tests/run_all.py --fast --changed --explain   # only what your changes can affect
python scripts/check_release.py --check               # versions, SKILL.md, links, commands, paths, names
```

Each module has `tests/test_<module>.py`: stdlib + subprocess, real runs, short and small renders. Every
validator needs a known-bad sample that must fail next to a known-good one that passes, so a green run
proves the check still bites.

`run_all.py` runs several test files at once: `-j N` files in parallel, each in its own process with its
own working folder and TMPDIR (default `auto` = min(files, cores / 2, 8), and up to cores / 2 on machines
with more than 16 cores, fewer when memory is short); `-j 1` runs them one after another with live output.
From 9 processes at once up, long files run in parts (`tests/_split.py` says which files and which tests
must share a process; `tests/_part.py` runs a part, and any test the plan does not know runs in the first
part). A test that leaves something for a later test (a result on the class, a file in the class's
folder) is kept with it when the scan can see it; otherwise add the pair to `KEEP_TOGETHER` there.
`--changed [REF]` runs only the test files that the changes since REF (default: the merge-base with the
integration branch, plus uncommitted and untracked files) can affect: what each test used in earlier runs
(recorded while tests run, in `~/.showtime/cache/test-impact.json`), a static scan of imports, paths and
commands, and `OVERRIDES` in `tests/_impact.py`; a file it cannot place runs everything and says which.
Longest files start first (timings of the previous run, kept in `~/.showtime/cache/test-times.json`); a
failing file's output is printed in full at the end. A new test
must use temp folders, free ports (port 0) and atomic writes into `~/.showtime/cache`
(`common.part_path` + `os.replace`, `common.cache_lock`); a file that truly cannot share the machine goes
in `SERIAL` in `run_all.py`, with the reason. A test that serves something (its own HTTP server, or
showtime's: render, check, snap, export, preview) uses `tests/_listen.py`, so it skips in a sandbox that
refuses `listen()` (`SHOWTIME_TEST_NO_LISTEN=1` simulates one). `--shard I/N` runs one of N weight-balanced parts of the
files (CI splits the fast suite into three jobs per OS this way); the split uses only the file names and
`SHARD_WEIGHTS` in `run_all.py`, so give a new heavy test file a weight there.

## Example media

The examples live in their own repository,
[showtime-examples](https://github.com/FavioVazquez/showtime-examples): the 22 example folders, the
launch film, `examples/MEDIA.json` and `scripts/publish_media.py`. Example renders stay small in git
there: posters, `share.txt`, project sources and videos up to 10 MB. Any single file over 10 MB and every
`.mov` (ProRes masters) is published as a release asset of that repository instead; `MEDIA.json` lists
them (path, bytes, sha256, asset name) and a managed block at the end of its `.gitignore` keeps them out
of commits. This repository keeps only the README art (`assets/readme/`). Run these in a clone of
showtime-examples:

```bash
python scripts/publish_media.py                        # verify (check_release runs this too)
python scripts/publish_media.py --refresh              # after adding or re-rendering example media
python scripts/publish_media.py --links --example 20   # markdown links for that example's README
python scripts/publish_media.py --upload --dry-run     # the gh release upload command
python scripts/publish_media.py --upload               # upload (needs gh and the release tag)
```

A README links an asset as `https://github.com/<owner>/<repo>/releases/download/<tag>/<asset>`, where
`<asset>` is the path under `examples/` with `--` for `/` (`20-curtain-call-pack--pack--lower-thirds--lt-bar.mov`);
`--links` prints them from the manifest.

## Releases

1. Update CHANGELOG.md (what changed and why).
2. `python scripts/check_release.py --set-version X.Y.Z` (updates `st.__version__`, both plugin manifests,
   `setup/package.json`, `server.json` and `packages/npm/package.json`, and in the docs the site footer version,
   the README status line, the `.mcpb` download links and the Action pins). A new minor version also needs a
   person: the README's "What's new in X.Y.Z" summary and the status badge are reported, not rewritten.
3. `python scripts/check_release.py --check --mirror` and the full test run must be clean; work through the
   "Before publishing" list in CHANGELOG.md. `--mirror` goes online: it checks that every model and audio file
   the mirrors must hold is on its release (a new entry in `mirror.json` needs `scripts/stage_model_mirror.py`
   and its upload first).
4. When examples changed: in showtime-examples, `python scripts/publish_media.py --refresh`, then
   `--upload` to the release tag named in `examples/MEDIA.json` (see "Example media").
5. MCP packages (optional): `python scripts/build_packages.py all --out <folder outside the repo> --pack`
   builds the npm package (`packages/npm/`, named in `server.json` for the MCP Registry) and the `.mcpb`
   bundle (local stdio server for desktop clients and Smithery). It publishes nothing.

# Harness notes: installing showtime and using it from other agent hosts

Read this when you install showtime, when you run it from an agent host other than Claude Code (or from
a script or CI), or when something about the host gets in the way: background processes are killed,
long commands time out, images cannot be viewed, there is no terminal.

## 1. Claude Code

The supported install is the plugin:

```text
/plugin marketplace add FavioVazquez/showtime
/plugin install showtime@showtime
```

The plugin ships the skill folder (`skills/showtime/`: SKILL.md, references, runtime, scripts, templates,
`bin/`); SKILL.md names its folder with `${CLAUDE_SKILL_DIR}`, which Claude Code fills in, and runs
the CLI as `<folder>/bin/showtime`. The plugin also registers showtime's MCP server and a progress monitor, and offers a
few settings in `/config` (default voice and language, a CPU limit, the install folder); all of it
works with the defaults and needs no setup of its own (see `mcp.md`). Tools, models and caches are not
in the plugin; the first use runs `showtime setup`, which puts them in `~/.showtime` (see
`onboarding.md`). Updating the plugin never touches `~/.showtime`; run
`showtime setup` after an update if `showtime doctor` asks for it.

For development on a clone, `showtime setup --link` links `~/.claude/skills/showtime` to the checkout
(a junction or a copy on Windows). Do not use both the link and the plugin at once.

## 2. Any other agent host

The skill is plain files plus a command-line tool, so any host that can read files and run shell
commands can use it:

1. Put the skill folder where the host looks for skills. Hosts that understand skill folders with a
   `SKILL.md` (YAML frontmatter `name` and `description`, Markdown body) load it as is. Otherwise add
   one line to the host's instructions: "For any video request, read `<path>/skills/showtime/SKILL.md`
   first and follow it."
2. Make `showtime` callable: call the skill's launcher by its full path (`<path>/skills/showtime/bin/showtime`
   on macOS/Linux, `bin\showtime.cmd` on Windows, from cmd or PowerShell). If a checkout lost the exec
   bit, `sh <path>/skills/showtime/bin/showtime <args>` or `python3 <path>/skills/showtime/lib/st/launcher.py
   <args>` does the same (`py -3` on Windows). Paths in SKILL.md and its references are relative to the
   skill folder; a host that does not fill in `${CLAUDE_SKILL_DIR}` should use that folder.
3. Run `showtime setup` once (in a normal terminal if the host sandboxes commands, see section 3), then
   `showtime doctor`. Setup also writes the stable command `~/.showtime/bin/showtime` (`showtime.cmd`
   and `showtime.ps1` on Windows): it runs whichever showtime skill is installed, keeps working when a
   plugin update moves the skill folder (every run records the newest skill in `~/.showtime/skill-path`;
   `showtime doctor` repairs it), and is the path to put in scripts, hand-written agent configs and PATH.
   Setup and doctor print how to put it on PATH; showtime never edits shell profiles itself.
4. Optional: hosts that speak MCP can use showtime's MCP server instead of (or next to) the shell;
   `mcp.md` has the config for Claude Desktop, Cursor and Codex.

Everything showtime needs lives under `~/.showtime` (`SHOWTIME_HOME` moves it); several hosts or
checkouts can share one install.

## 3. Host behaviour that matters

| Host trait | What to do |
|---|---|
| Commands time out, or are stopped after minutes without output | Add `--background` to long work (setup, final renders, long transcriptions, audio, library fetch): it starts detached and prints a run id at once; `showtime status <id>` shows the latest progress and, at the end, the exit code and last output; `showtime status <id> --wait 240` watches it (a line every 30 s) and exits with the command's own code (75 while it still runs); `--cancel` stops it; `showtime status --runs` lists runs. Without `--background`, a long command prints a `still running` line every 45 s when its output is not a terminal, so hosts that stop silent commands keep it. Draft first: `showtime render <p> --preview` is quick |
| Background processes are killed at the end of a turn | Preview and studio servers: `showtime preview <p> --foreground` or `showtime studio serve <job>` under the host's own background mechanism |
| No terminal (piped output) | Colour and redrawn progress lines switch off by themselves; `SHOWTIME_PROGRESS=json` gives one JSON object per progress update, `off` silences it |
| Needs machine-readable output | Most commands take `--json`; errors go to stderr as `error:` / `why:` / `fix:` lines with a non-zero exit code |
| Cannot view images | The "look at it" gates in SKILL.md still apply: rely on `showtime qa` and `showtime check` text findings, and tell the user you could not inspect the frames yourself |
| No sub-agents | Skip parallel scene authoring; for publish-bound work give the user the `review-pack` folder instead of a critic sub-agent |
| Sandboxed commands (no network, writes only inside the folder the agent works in) | Run `showtime doctor`: it tests writing the showtime folder and reaching the download hosts, and names the setting to change in the host that runs it (Codex: the `network_access` and `writable_roots` sandbox settings in `~/.codex/config.toml`, doctor prints the lines; Antigravity: `read_url` / `write_file` rules; Cursor: the domains for `sandbox.json`; the Copilot cloud agent: `copilot-setup-steps.yml`). Two ways out work in every host: run `showtime setup` once in a normal terminal, or keep showtime inside that folder with `SHOWTIME_HOME=.showtime showtime setup`; from then on every command run in that project finds `./.showtime` by itself (its `.gitignore` keeps it out of git) |
| Sandboxed network | Setup needs HTTPS to its download hosts, and so does the first use of anything outside the default install (Whisper before the first transcription, Manim, the audio library's packs, icons, the aligner, Piper voices, rembg; `showtime setup --plan` lists them all). A machine that will be offline later runs `showtime setup --full` first. Media search queries public archives and site capture fetches the pages you point it at; nothing is uploaded. `SHOWTIME_OFFLINE=1` turns off every download (fonts, voices, media search); a feature that would need one says so instead |
| Windows | Use the `.cmd` shim from cmd and from PowerShell (in PowerShell, call a quoted path with `&`: `& "<path>\bin\showtime.cmd" doctor`); it needs no execution-policy change. `showtime.ps1` runs only where the policy allows local scripts (for example `RemoteSigned`); if PowerShell answers "running scripts is disabled", type `showtime.cmd` instead of `showtime`. Paths with spaces and parentheses work |

Exit codes worth handling: `0` ok; `1` a failure the command explains (qa FAIL, check errors); `3` a
missing extra (prints the `showtime setup --with` line) or, for `showtime site capture`, a bot wall
(see `capture.md`).

## 4. Environment variables

| Variable | Effect |
|---|---|
| `SHOWTIME_HOME` | install location (default: a `.showtime` folder in the project that setup has used, else `~/.showtime`); a relative value is resolved against the current folder |
| `SHOWTIME_HEARTBEAT` | seconds between `still running` lines of a long command whose output is not a terminal (default 45; `0` turns them off) |
| `SHOWTIME_MCP_WAIT` | MCP server: seconds a long tool call waits before it answers with a task id (default 20; Claude Code: until done; `none` = always wait) |
| `SHOWTIME_HOST` | name the agent host for `showtime doctor`'s advice when it guesses wrong: `codex`, `antigravity`, `cursor`, `copilot-cloud`, `gemini`, `devin`, `claude`, `generic` |
| `SHOWTIME_OUT` | where `showtime-out/` job folders are created (default: the current folder) |
| `SHOWTIME_OFFLINE=1` | never download |
| `SHOWTIME_AUTO_INSTALL=1` | install a missing extra instead of stopping with exit code 3 |
| `SHOWTIME_PROGRESS=json\|off` | progress format when not on a terminal |
| `NO_COLOR=1` | plain text output |
| `SHOWTIME_FFMPEG`, `SHOWTIME_CHROME`, `SHOWTIME_NODE`, `SHOWTIME_PYTHON` | use your own binaries |
| `SHOWTIME_STUDIO_IDLE_MIN` | studio server idle timeout (default 240 minutes) |
| `SHOWTIME_TTS_CACHE_MB` | voice cache cap (default 1024 MB) |
| `SHOWTIME_VOICE`, `SHOWTIME_LANG` | default narration voice and language (the plugin settings set them too) |
| `SHOWTIME_MAX_WORKERS` | cap on parallel render browsers (and, unless `SHOWTIME_THREADS` is set, CPU threads) |
| `SHOWTIME_OPEN_BROWSER=1` | `showtime studio open` opens the board in the browser |
| `SHOWTIME_SOUND=1` | play a short sound logo when a command that ran over 20 s finishes (your own terminal only) |
| `SHOWTIME_SETTINGS` | location of the saved plugin settings (default `~/.showtime/plugin-settings.json`) |
| `SHOWTIME_PROGRESS_LOG=0` | do not append milestones to `~/.showtime/logs/progress.jsonl` (used by the progress monitor) |

At a terminal of your own, showtime adds three small touches: the brand mark above `showtime --help`,
`setup` and `doctor`; a completion card after `render`, `export html`, `manim render`, `edit render` and
`deliver exports` (what was made, its length, size and qa verdict when one is recorded, and the next
command); and, only with `SHOWTIME_SOUND=1` or the plugin's `sound` option, a short sound after a job longer
than 20 s (played with `afplay`, PowerShell, `paplay`/`pw-play`/`aplay` or `ffplay`; a missing player is
silently skipped). None of it appears when the output is not a terminal (an agent's tool calls, pipes, logs),
with `--json`, `NO_COLOR`, `TERM=dumb`, `CI` or `SHOWTIME_COLOR=never`, so scripts and parsers see the same
plain output as before.

## 5. Scripts and CI

The CLI is the whole interface; nothing needs an agent. A minimal non-interactive render:

```bash
showtime setup --tier minimal
showtime new dom demo --duration 2 --width 640 --height 360
showtime render demo -o out/final.mp4
showtime qa out/final.mp4 --json
```

`showtime clean` asks you to type the folder name before removing anything; in scripts pass `--yes`
(and `--dry-run` first to see what goes).

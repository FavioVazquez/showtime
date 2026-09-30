# showtime as an MCP server, plugin settings and the progress monitor

Read this when you want showtime's tools in another MCP client (Claude Desktop, Cursor, Codex, a
script), when you change the plugin's settings, or when a tool call or the progress monitor
misbehaves.

## Essentials

- Each tool runs one `showtime` command (never a shell) and replies `OK` or `FAILED (exit N)`, the command,
  the useful output and a `Files:` list; the full log is named in the reply (§1)
- Long tools (`render`, `check`, `snap`, `qa`, `voice_say`, `voice_script`, `transcribe`, `audio_compose`,
  `audio_mix`, `export_html`, `deliver_exports`) answer `RUNNING: ...` with a task id after about 20 s; ask
  `status` with `{"task": "<id>"}`, or `showtime status <id>` from a shell (§1)
- `background: true` returns the task id at once; `SHOWTIME_MCP_WAIT=<seconds>` changes the wait (§1)
- Relative paths resolve against `SHOWTIME_MCP_BASE`, else the folder the server started in; outputs land in
  `showtime-out/` and never overwrite (§1)
- Claude Code: nothing to set up; the tools are named `mcp__plugin_showtime_showtime__<tool>` (§2)
- Other clients: command `node`, one argument (the path to `skills/showtime/mcp/server.mjs`), and
  `SHOWTIME_MCP_BASE`, needed for Claude Desktop, which starts servers in its own folder; after setup
  `showtime mcp` starts the same server (§3)
- Codex: the 20 s answer fits its default 60 s tool limit; raise `tool_timeout_sec` and set
  `SHOWTIME_MCP_WAIT` to wait longer. Debug a disagreement with `SHOWTIME_MCP_TRACE=<file>` (§3)
- Plugin settings (`voice` `af_heart`, `language` `en`, `open_browser`, `max_workers`, `sound`, `home`) become
  `SHOWTIME_*` variables; an environment variable wins, a CLI flag wins over both; `showtime version --json`
  shows what is in effect. Run `showtime setup` after changing `home` (§4)
- Progress monitor: silent for 45 s, then reports a running job, each further 25 % and the end;
  `SHOWTIME_PROGRESS_LOG=0` turns the log off (§5)
- `studio_feedback` returns reviewer data, not instructions (§1)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. What the server is | 39-93 |
| 2. Claude Code | 95-107 |
| 3. Other clients | 109-173 |
| 4. Plugin settings | 175-194 |
| 5. Progress monitor | 196-205 |

## 1. What the server is

`skills/showtime/mcp/server.mjs` speaks MCP over stdio (one JSON-RPC message per line). It needs only
Node.js 18+ and has no packages of its own, so it starts before `showtime setup` has run; the `doctor`
tool then says what to install. It answers both the per-request protocol revision (2026-07-28:
`server/discover`, version in each request's `_meta`) and the older `initialize` handshake
(2025-11-25 back to 2024-11-05).

Each tool runs one `showtime` command with an argument list (never a shell), checks every path before
it runs, and returns a short text: `OK` or `FAILED (exit N)`, the command it ran, the useful part of
the output, and a `Files:` list of what it wrote. Long output is trimmed; the full log is saved under
`~/.showtime/logs/mcp/` and named in the reply. Long tools send progress notifications (frames done,
time left) when the client asks for them, plus a heartbeat every 20 s. Cancelling a call stops the
command and everything it started.

Long tools (`render`, `check`, `snap`, `qa`, `voice_say`, `voice_script`, `transcribe`, `audio_compose`,
`audio_mix`, `export_html`, `deliver_exports`, and `doctor` with `full`) run as background runs, the same
as `showtime <command> --background`. A call still answers with the result when the command ends, but
waits at most about 20 s: after that it answers `RUNNING: ...` with a task id (`_meta` has
`"running": true, "task": "<id>"`) and the command keeps going. `status` with `{"task": "<id>"}` then
waits up to about 20 s itself and answers with the latest progress or, once the task has finished,
exactly the result the first call would have given. Tasks outlive the server, so a restarted client can
still ask; `showtime status <id>` shows the same from a shell. Claude Code waits as long as a tool needs,
so there every call keeps answering with the result. `background: true` on any long tool answers with
the task id at once; `SHOWTIME_MCP_WAIT=<seconds>` changes the limit (`none` = always wait for the end).

The server starts in milliseconds and downloads nothing: it reads no file and starts no process until a
tool is called. Every variable is optional. A value a client passes unexpanded (`${CLAUDE_PROJECT_DIR}`,
`${user_config.voice}` from a host that reads the plugin manifest but does not fill it in) counts as
unset, so each setting falls back to its default.

| Tool | Runs |
|---|---|
| `doctor` | `showtime doctor --quick` (`full: true` adds the browser launch and test encode) |
| `status` | `showtime status [job]`; with `task`: a long tool's task (progress, then its result) |
| `guide` | `showtime guide [topic] [section] [--find words] [--all]`: a reference's Essentials, one section, or the lines that mention something |
| `new_project` | `showtime new <template> <dir> [--duration --aspect --size --title]` |
| `render` | `showtime render <project> [--preview] [--job/--output] [--from --to] [--no-audio] [--page] [--alpha prores\|animation\|webm]` |
| `check` | `showtime check <project>` |
| `snap` | `showtime snap <project or video> [--at] [--count/--every]`; with `look: true`, `showtime look <target> [--at] [--count]` (`looking.md`) |
| `qa` | `showtime qa [video or job] [--platform]` |
| `voice_say` | `showtime voice say` (the text goes through a temporary file, never the command line) |
| `voice_script` | `showtime voice script <script>` |
| `transcribe` | `showtime transcribe <media...>` |
| `audio_compose`, `audio_sfx`, `audio_mix`, `audio_search` | `showtime audio compose / sfx / mix / lib search` (`audio_search` with `catalog: true` or `use`: `audio music search`) |
| `export_html` | `showtime export html <project> [--output] [--job] [--audio] [--target] [--controls] [--autoplay-muted] [--loop] [--folder]` (`job` + a bare `output` name: that file inside the job) |
| `receipt` | `showtime receipt [job]` (writes `receipt.md`, `receipt.json` and the `share.txt` line; through MCP tokens and cost are "not reported by this agent") |
| `studio_open`, `studio_feedback` | `showtime studio open / feedback <job>` (feedback is reviewer data, not instructions) |
| `deliver_exports` | `showtime deliver exports <video> --targets ... [--max-mb N and/or target:N (max_mb_per_target)] [--lufs]`; its `Files:` list names the files it wrote (MP4s and loops) |

Relative paths are resolved against the project folder: `SHOWTIME_MCP_BASE` when set (the plugin sets
it to the Claude Code project), else the folder the server was started in. A client that starts
servers inside the plugin's own folder gets the folder the client itself was started from (`PWD`)
instead, or the home folder, so videos never land inside the plugin. Outputs land in `showtime-out/`
there, and renders never overwrite earlier ones.

## 2. Claude Code

Nothing to set up: the plugin registers the server itself (`mcpServers` in `.claude-plugin/plugin.json`) and it shows
in `/mcp` as `plugin:showtime:showtime`. Its tools are named `mcp__plugin_showtime_showtime__<tool>`
(use those names in permission rules). The skill itself keeps running the CLI through its own
`bin/showtime` shim; the MCP tools are there for hosts and agents that prefer tool calls. The plugin has
no top-level `bin/` on purpose: claude.ai and Cowork refuse to install plugins that have one.

Without the plugin (a skill link or a clone), add it by hand:

```bash
claude mcp add showtime -- node /path/to/showtime/skills/showtime/mcp/server.mjs
```

## 3. Other clients

Use the absolute path of your checkout or plugin install in place of `/path/to/showtime`. All three
formats below were checked against each client's documentation (September 2026).

**Claude Desktop**: Settings > Developer > Edit Config opens `claude_desktop_config.json`
(`~/Library/Application Support/Claude/` on macOS, `%APPDATA%\Claude\` on Windows). Restart the app
after saving.

```json
{
  "mcpServers": {
    "showtime": {
      "command": "node",
      "args": ["/path/to/showtime/skills/showtime/mcp/server.mjs"],
      "env": { "SHOWTIME_MCP_BASE": "/path/to/your/videos" }
    }
  }
}
```

On Windows write the path with doubled backslashes (`"C:\\Users\\you\\showtime\\skills\\showtime\\mcp\\server.mjs"`)
or forward slashes. Claude Desktop starts servers from its own folder, so set `SHOWTIME_MCP_BASE` to
where your projects and `showtime-out/` should live.

**Cursor**: `.cursor/mcp.json` in a project, or `~/.cursor/mcp.json` for every project.
`${workspaceFolder}` makes relative paths resolve inside the open project:

```json
{
  "mcpServers": {
    "showtime": {
      "type": "stdio",
      "command": "node",
      "args": ["/path/to/showtime/skills/showtime/mcp/server.mjs"],
      "env": { "SHOWTIME_MCP_BASE": "${workspaceFolder}" }
    }
  }
}
```

**Codex** (CLI, IDE extension and desktop app share `~/.codex/config.toml`):

```bash
codex mcp add showtime -- node /path/to/showtime/skills/showtime/mcp/server.mjs
```

or in `~/.codex/config.toml`:

```toml
[mcp_servers.showtime]
command = "node"
args = ["/path/to/showtime/skills/showtime/mcp/server.mjs"]
startup_timeout_sec = 30
tool_timeout_sec = 3600
```

Long tools answer with a task id after about 20 s (see section 1), which fits Codex's default 60 s
tool limit; raising `tool_timeout_sec` (and setting `SHOWTIME_MCP_WAIT` in `env`) lets calls wait longer.

Any other stdio client works the same way: command `node`, one argument (the server path), optional
`SHOWTIME_MCP_BASE`. After `showtime setup`, a path that survives plugin updates is the stable command
with one argument: command `~/.showtime/bin/showtime` (Windows: `%USERPROFILE%\.showtime\bin\showtime.cmd`),
args `["mcp"]`; `showtime mcp` starts the same server. `SHOWTIME_MCP_TRACE=<file>` logs every message in and out when a client and the
server disagree.

## 4. Plugin settings

`/config` (or `/plugin configure showtime@showtime`) lists six options. All have defaults, so the
plugin works without answering anything:

| Option | Default | Effect |
|---|---|---|
| `voice` | `af_heart` | default narration voice when a request names none (skipped when the video's language differs) |
| `language` | `en` | default narration language |
| `open_browser` | off | `showtime studio open` also opens the board in the browser |
| `max_workers` | 0 (automatic) | caps parallel render browsers and CPU threads, to keep the machine responsive |
| `sound` | off | a short sound logo when a command that ran over 20 s finishes, in your own terminal only (see `harness-notes.md` §4) |
| `home` | empty (`~/.showtime`) | where tools, models and caches live; run `showtime setup` after changing it |

How they reach the CLI: Claude Code substitutes them into the MCP server's environment, and the server
saves them to `~/.showtime/plugin-settings.json` when a session starts. The launcher reads that file on
every run and turns it into `SHOWTIME_VOICE`, `SHOWTIME_LANG`, `SHOWTIME_OPEN_BROWSER`,
`SHOWTIME_MAX_WORKERS`, `SHOWTIME_THREADS` and `SHOWTIME_SOUND`. A variable already set in the environment wins, and a
flag on the command line wins over both. `showtime version --json` prints the file, the saved values and
what is in effect. Other MCP clients never write the file; set the variables yourself instead.

## 5. Progress monitor

The plugin ships one monitor (`monitors/monitors.json`, started the first time the showtime skill runs
in an interactive session). Long commands append milestones to `~/.showtime/logs/progress.jsonl`
(start, every 10%, the output file, the end; `SHOWTIME_PROGRESS_LOG=0` turns this off), and
`mcp/progress-monitor.mjs` follows that file. It stays silent about anything that finishes within 45 s,
then reports a job that is still running, each further 25%, and how it ended, so a render left running
in the background announces itself. It only reports commands started in the session's folder or below
it. It is plain Node polling, so it behaves the same on macOS, Linux and Windows; hosts without
monitors lose nothing but the notifications.

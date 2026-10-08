# showtime in your coding agent

showtime is a skill, a command line and an MCP server. Any agent that reads [Agent Skills](https://agentskills.io)
and can run shell commands can use it; MCP adds typed tools on top, and the ten crew agents are an
optional speed-up for hosts with custom sub-agents. This page gives the exact install for each agent; the
[README](../README.md#works-with) has the short version.

**Tested** means the agent installed showtime and made a real video with it: the request "make a
5-second test video that says hello" in an empty folder, ending in a `final.mp4` whose `showtime qa`
verdict had no FAIL. **Should work** means the files it reads are there and were checked with the
agent's own tools where possible, but no real video was made in it yet.

| Agent | Install route | Crew agents | Status |
|---|---|---|---|
| [Claude Code](#claude-code) | plugin | yes | tested (primary host) |
| [OpenAI Codex](#openai-codex) | plugin (root `plugin.json` + `mcp.json`) | via `showtime install` | tested: CLI 0.158.0, plugin route |
| [Cursor](#cursor) | plugin (reads `.claude-plugin/`) | yes | tested: CLI 2026.09.28, `--plugin-dir` |
| [Devin](#devin) | plugin (reads `.claude-plugin/`) | yes (local only) | tested: CLI 3000.11.3, local plugin |
| [OpenCode](#opencode) | `showtime install` | yes | tested: 1.18.33, `showtime install` route, a free model |
| [GitHub Copilot](#github-copilot) (CLI and VS Code) | plugin | yes (`com.github.copilot/agents/`) | should work |
| [Gemini CLI](#gemini-cli) | `showtime install` (or the extension) | yes | should work |
| [Antigravity](#antigravity) | plugin from a clone, or `showtime install` | yes | should work |
| [Cline](#cline) | `showtime install` + MCP settings | no (its sub-agents cannot use MCP) | should work |
| [Kilo Code](#kilo-code) | skill + MCP settings | no | should work |
| [Kiro](#kiro) | `showtime install` | yes | should work |
| [Zed](#zed) | `showtime install` | no (no custom agents) | should work |
| [Goose](#goose) | skill + extension | no | should work |
| [Amp](#amp) | `showtime install` | no | should work |
| [Factory Droid](#factory-droid) | plugin (reads `.claude-plugin/`) | yes | should work |
| [Any other skills agent](#any-agent-skills-client) | `npx skills add` | no | should work |
| [Any MCP client](#mcp-only) | MCP server | no | should work |

Tested on Linux x64 (Ubuntu 24.04) on 2026-09-28.

## Before any of them: setup, once, in a normal terminal

showtime renders on your machine, so it needs its tools and models in `~/.showtime`: about 770 MB on Linux
x64, 560 to 610 MB on macOS and Windows (`showtime setup --plan` prints your exact list; bigger pieces such as
Whisper for transcripts arrive the first time a video needs them, with their size announced, and
`showtime setup --full` fetches them all now). Agent sandboxes often block that download, so run setup
yourself once:

```bash
git clone --depth 1 https://github.com/FavioVazquez/showtime ~/showtime
~/showtime/skills/showtime/bin/showtime setup      # Windows: ~\showtime\skills\showtime\bin\showtime.cmd setup
~/showtime/skills/showtime/bin/showtime doctor     # every line PASS (SKIP is fine)
```

Setup also writes the stable command `~/.showtime/bin/showtime` (Windows: `showtime.cmd`), which keeps
working when a plugin update moves the skill folder. `showtime` below means that command, or the
skill's own `bin/showtime`.

Review mode, the same in every agent: quality (the default) reviews every finished video with a critic round
before delivery; ask your agent for "lean" or run `showtime config mode lean` (or set `SHOWTIME_MODE=lean`;
MCP clients: the `new_project` tool's `mode`) for a cheaper draft pass.

## showtime install

For agents that do not install plugins from this repository, one command puts each piece where that
agent looks for it:

```bash
showtime install --agent <name>              # for your user
showtime install --agent <name> --project    # into the current project only
showtime install --agent <name> --print      # show what it would write, change nothing
showtime install --agent <name> --uninstall  # remove what it added, nothing else
showtime install --list                      # agents it knows
```

It links the skill folder where the agent reads skills (only where it does not see one already),
writes the ten crew agents in the agent's own format, and adds a `showtime` MCP server entry
launched as `~/.showtime/bin/showtime mcp`. Config files are merged, never replaced: the original is
kept once as `<file>.before-showtime`, and a file it cannot parse (JSON with comments, YAML) is left
alone with the entry printed for you to paste. Run it again after updating showtime.

## Claude Code

```text
/plugin marketplace add FavioVazquez/showtime
/plugin install showtime@showtime
```

Everything is included: the skill, the ten crew agents, the MCP server and the plugin settings
(`/config`).

## Claude app

In the Claude desktop app: **Customize → Plugins → Add marketplace**, enter `FavioVazquez/showtime`,
then install showtime from it. Commands run in the app's sandbox, behind a proxy that can answer 403
for Hugging Face and GitHub LFS. `showtime setup` works there anyway: when a model's
own host is blocked, the file comes from showtime's model mirror (release assets under the `models-v1`
tag of this repository) and is checked against the same sha256. The mirror holds the default install's
and first-use models (Kokoro, YuNet, Whisper small.en, Parakeet v3, the word aligner, Silero VAD, the
denoise models, the default SoundFont); opt-in extras such as `--with asr-turbo` and Piper voices are
not mirrored. `SHOWTIME_MODEL_MIRROR` points at another mirror: a base URL, or a folder holding the
files under their mirror names (`skills/showtime/lib/st/mirror.json` lists them); `off` turns the
mirror off.

The same proxy also blocks the hosts real music and sound effects come from (opengameart.org,
scottbuckley.com.au, incompetech.com, archive.org, upload.wikimedia.org, bigsoundbank.com, kenney.nl),
so a video's soundtrack and sound effects would otherwise be silently missing. The audio mirror (release
assets under the `audio-v1` tag) covers the music catalog, the sound-effect packs and the core/extended
library tiers the same way: `SHOWTIME_AUDIO_MIRROR` picks another mirror or folder, `off` disables it.

## OpenAI Codex

```bash
codex plugin marketplace add FavioVazquez/showtime
codex plugin add showtime@showtime
showtime install --agent codex --no-skill --no-mcp   # optional: the ten crew agents (~/.codex/agents)
```

Codex reads the root `plugin.json` and `mcp.json` (Agent Plugins 1.0): the skill appears as
`showtime:showtime` and the MCP server starts from the plugin folder. Codex plugins cannot carry
sub-agents, hence the optional second command; Codex only starts them when you ask ("spawn the
scriptwriter agent").

Sandbox: renders write to `~/.showtime` and setup needs the network. In the default `workspace-write`
sandbox, add to `~/.codex/config.toml`:

```toml
[sandbox_workspace_write]
network_access = true
writable_roots = ["/home/<you>/.showtime"]
```

On Ubuntu 24.04 Codex's own sandbox may not start at all ("bwrap: setting up uid map: Permission
denied"); that is the distribution restricting unprivileged user namespaces, not showtime. The test
above ran with `--sandbox danger-full-access` on a throwaway machine for that reason.

Headless: `codex exec --skip-git-repo-check "make a 5-second test video that says hello"`.

## Cursor

Editor: put a clone where Cursor loads local plugins, then restart Cursor.

```bash
git clone --depth 1 https://github.com/FavioVazquez/showtime ~/.cursor/plugins/local/showtime
```

CLI (`agent`): load the same folder with `--plugin-dir`:

```bash
agent --plugin-dir ~/.cursor/plugins/local/showtime
agent -p --force --trust --approve-mcps --plugin-dir ~/.cursor/plugins/local/showtime "make a 5-second test video that says hello"
```

Cursor reads `.claude-plugin/plugin.json`: skill, crew agents and MCP server all load. Without the
plugin: `showtime install --agent cursor` (skill in `~/.agents/skills`, agents in `~/.cursor/agents`,
MCP in `~/.cursor/mcp.json`). Cursor's sandbox limits network to `sandbox.json`, so run setup in a
normal terminal first.

## Devin

```bash
devin plugins install FavioVazquez/showtime        # add --local to keep it off your Devin Cloud plugins
devin plugins info showtime                         # skill, 10 agents, MCP server "showtime"
```

Devin reads `.claude-plugin/`. Crew agents work in the CLI and Devin Desktop, not in Devin Cloud.
Devin asks before each MCP tool by default (allow `mcp__showtime__*` in its permissions to skip that).
Headless: `devin -p "…" --permission-mode dangerous --respect-workspace-trust false < /dev/null`.

## OpenCode

```bash
showtime install --agent opencode
```

The skill goes to `~/.agents/skills/showtime`, the crew to `~/.config/opencode/agents` (`mode: subagent`)
and the MCP server to `~/.config/opencode/opencode.json`. Check with `opencode agent list` and
`opencode mcp list` (showtime: connected). Headless: `opencode run --auto "…"`; the test used one of
OpenCode's free models and the showtime MCP tools (doctor, new_project, check, render, qa).

## GitHub Copilot

CLI:

```bash
copilot plugin marketplace add FavioVazquez/showtime
copilot plugin install showtime@showtime
```

VS Code: run **Chat: Install Plugin From Source** with `https://github.com/FavioVazquez/showtime`
(plugins the CLI installed also appear in VS Code). Copilot reads the root Agent Plugins manifest; the
crew agents come from `com.github.copilot/agents/`. Without the plugin: `showtime install --agent copilot`.

## Gemini CLI

Gemini CLI now serves paid API keys and Gemini Code Assist Standard/Enterprise.

```bash
showtime install --agent gemini
```

This adds the skill (`~/.agents/skills`), the crew in Gemini's format (Gemini tool names,
`timeout_mins: 60`) in `~/.gemini/agents`, and the MCP server in `~/.gemini/settings.json`. The
repository is also a Gemini extension (`gemini extensions install https://github.com/FavioVazquez/showtime`):
it brings the skill and the MCP server, but Gemini then prints an "Error loading agent" line for each of
the ten Claude-format crew files it cannot read; the install command above avoids that. Gemini stops a
shell command after 300 s without output: showtime prints a progress line every 45 s.

## Antigravity

```bash
git clone --depth 1 https://github.com/FavioVazquez/showtime ~/showtime
agy plugin install ~/showtime                     # skill, crew and MCP server (mcp_config.json)
```

or, without the plugin: `showtime install --agent antigravity` (skill in
`~/.gemini/antigravity-cli/skills`, crew in `~/.gemini/config/agents`, MCP in
`~/.gemini/config/mcp_config.json`; `agy agents` and `agy mcp list` show them). Antigravity's terminal
sandbox has no network by default: run setup in a normal terminal.

## Cline

```bash
showtime install --agent cline
```

The skill goes to `~/.cline/skills/showtime` and the MCP server to the Cline CLI's `~/.cline/mcp.json`.
In the VS Code extension, add the same entry under **MCP Servers > Configure MCP Servers** (the
command prints it), or let Cline follow [`llms-install.md`](../llms-install.md). Cline's sub-agents
cannot use MCP, so no crew is installed.

## Kilo Code

```bash
showtime install --agent kilo
```

The skill goes to `~/.agents/skills`. Add the MCP server in Kilo's MCP settings with the command it
prints (`~/.showtime/bin/showtime` with the argument `mcp`).

## Kiro

```bash
showtime install --agent kiro
```

Kiro reads skills only from `~/.kiro/skills`, so the skill is linked there; the crew goes to
`~/.kiro/agents/*.json` (each loads the skill as a resource) and the MCP server to
`~/.kiro/settings/mcp.json`.

## Zed

```bash
showtime install --agent zed
```

The skill goes to `~/.agents/skills/showtime` (Zed does not read nested skill folders; this link is
flat). Zed's `settings.json` usually has comments, so the command prints the `context_servers` entry
to paste instead of editing it. Zed has no custom agent files.

## Goose

```bash
showtime install --agent goose
```

The skill goes to `~/.agents/skills`; paste the printed block into `~/.config/goose/config.yaml`, or
run `goose configure` > Add Extension > Command-line Extension with the command `~/.showtime/bin/showtime mcp`.

## Amp

```bash
showtime install --agent amp        # or: amp mcp add showtime -- ~/.showtime/bin/showtime mcp
```

## Factory Droid

```bash
droid plugin marketplace add FavioVazquez/showtime
droid plugin install showtime@showtime
```

Factory translates the `.claude-plugin/` layout. Without the plugin: `showtime install --agent factory`.

## Qwen Code

```bash
showtime install --agent qwen       # Qwen reads skills only from ~/.qwen/skills
```

## Any Agent Skills client

```bash
npx skills add FavioVazquez/showtime
```

This installs the skill for the agents you pick. Then run setup once from the installed skill folder
(`<skills folder>/showtime/bin/showtime setup`), and add the MCP server if you want it (below).

## MCP only

Any client that starts local (stdio) servers can use showtime's MCP server on its own. After setup:

```json
{
  "mcpServers": {
    "showtime": { "command": "/home/<you>/.showtime/bin/showtime", "args": ["mcp"] }
  }
}
```

(Windows: `C:\\Users\\you\\.showtime\\bin\\showtime.cmd`.) Two routes need no clone: from npm
([@faviovazquez/showtime-mcp](https://www.npmjs.com/package/@faviovazquez/showtime-mcp), also in the MCP Registry as
`io.github.FavioVazquez/showtime`),
`{"command": "npx", "args": ["-y", "@faviovazquez/showtime-mcp"]}` (see
[`packages/npm/README.md`](../packages/npm/README.md)), and [`showtime-0.4.0.mcpb`](https://github.com/FavioVazquez/showtime/releases/download/v0.4.0/showtime-0.4.0.mcpb) from the v0.4.0 release, which
Claude Desktop opens with a double click. Setup still runs once on your machine, because the models and tools
never travel inside a package. Long tools answer with a task id after about
20 s when a client stops calls early; the `status` tool reports progress and the result.

The MCP server has a `guide` tool that reads a reference by the piece (its rules, one section, or the lines that
mention something), so a client without the skill does not have to load whole files, and a `receipt` tool that writes a
job's receipt. Tokens and cost are "not reported by this agent" through MCP.

Ten core tools are listed by default (`doctor`, `status`, `guide`, `new_project`, `render`, `check`, `qa`,
`export_html`, `deliver_exports`, `receipt`). Add `"env": { "SHOWTIME_MCP_TOOLS": "all" }` to the server entry to list
the voice, music, sound-effect, transcription, stills and studio-board tools too; the `.mcpb` sets it for you.

Some features have no MCP tool yet: `adopt` (a Claude Design export too), `footage cutout`, `edit cards`,
`edit moments`, `edit clips`, `pr-video`, `review open` and `review notes`, and `export html`'s `--share-url` and
`--share-image` (showtime.json `"share"` works through `export_html`). An agent with a shell runs them as
`showtime <command>`; a client with MCP only cannot reach them yet.

## In CI: the GitHub Action

To make a release or pull-request video on a runner, with no agent and no API key, use the
[showtime GitHub Action](github-action.md). Its `agent` mode runs a coding-agent command you configure, with your own
key as a secret; only the plumbing of that mode is tested here, not a particular agent.

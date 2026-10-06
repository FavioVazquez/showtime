# Installing showtime's MCP server (instructions for an AI agent)

showtime is a local video studio: its MCP server gives you tools that render HTML/canvas scenes to MP4,
speak narration, compose music, transcribe footage, check a finished video and export it for platforms,
all on the user's machine. There are no API keys. Follow these steps in order and tell the user what you
are doing at each one.

## 1. Check the prerequisites

- **Node.js 20 or newer**: run `node --version`. If it is missing or older, ask the user to install Node.js
  (24 or 22 LTS) from https://nodejs.org and to restart this editor afterwards.
- **uv** (preferred) or **Python 3.8+**: run `uv --version`, else `python3 --version` (`py -3 --version` on
  Windows). If neither works, ask the user to install uv (https://docs.astral.sh/uv/getting-started/installation/)
  and to restart this editor afterwards.
- **git**, to clone the repository.

## 2. Get the code

Clone the repository into a stable folder the user agrees to (not a temporary folder: the MCP settings
will point into it). For example:

```bash
git clone --depth 1 https://github.com/FavioVazquez/showtime.git ~/showtime
```

Below, `<showtime>` means the absolute path of that folder (for example `/Users/alice/showtime` or
`C:\Users\alice\showtime`). Do not use `~` inside the MCP settings; write the full path.

## 3. Run setup once

Setup downloads showtime's tools and models (ffmpeg, a browser for rendering, local voice and speech
models, Node and Python packages) into `~/.showtime`. It changes nothing outside that folder. First show
the user the size and time, and ask before downloading:

```bash
<showtime>/skills/showtime/bin/showtime setup --estimate
```

On Windows use `<showtime>\skills\showtime\bin\showtime.cmd` in place of `<showtime>/skills/showtime/bin/showtime`.

When the user agrees, run it (it takes several minutes; let it finish):

```bash
<showtime>/skills/showtime/bin/showtime setup
```

If the download is refused or the folder is not writable (a sandbox), ask the user to run the same command
in their own terminal. Then check the result:

```bash
<showtime>/skills/showtime/bin/showtime doctor
```

Lines should say PASS (SKIP is fine; the `agent skill` line only says how the skill was installed). A WARN or FAIL line
says what is wrong and the command that fixes it.

## 4. Add the server to the MCP settings

Add this entry under `mcpServers` in the MCP settings file (in Cline: MCP Servers > Configure > Configure
MCP Servers; in the Cline CLI: `~/.cline/mcp.json`). Keep any servers that are already there.

```json
{
  "mcpServers": {
    "showtime": {
      "command": "node",
      "args": ["<showtime>/skills/showtime/mcp/server.mjs"],
      "env": { "SHOWTIME_MCP_BASE": "<folder where the user wants their videos>", "SHOWTIME_MCP_TOOLS": "all" },
      "timeout": 3600,
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

- Replace both placeholders with absolute paths. On Windows, write backslashes doubled
  (`C:\\Users\\alice\\showtime\\skills\\showtime\\mcp\\server.mjs`) or use forward slashes.
- `SHOWTIME_MCP_BASE` is where new projects and `showtime-out/` (the finished videos) go; use the open
  project folder if the user has no preference.
- `SHOWTIME_MCP_TOOLS` set to `all` lists every tool, voice, music, sound effects and transcription included.
  Leave it out for the ten core tools only (make, render, check, export, deliver), which keeps the tool list short.
- `timeout` is in seconds: renders and transcriptions often take longer than the default 60. A long
  tool that runs past about 20 s answers `RUNNING` with a task id instead of timing out; call `status`
  with `{"task": "<id>"}` until it returns the result.
- Leave `autoApprove` empty unless the user asks otherwise; `doctor`, `status`, `check`, `qa`,
  `audio_search` and `studio_feedback` only read.

## 5. Verify

Call the `doctor` tool. It should report the installation as ready. Then offer a first video, for example:
"Make a 10-second title card that says Hello, with a short music sting", using `new_project`, then
`render` with `preview: true`, then `qa`.

## If something goes wrong

- `node` or `uv` not found right after installing: the editor needs a restart to see the new PATH.
- A tool times out: raise `timeout` (up to 3600), or pass `"background": true` and poll `status`.
- `doctor` fails `home writable` or `network`: the editor runs commands in a sandbox; doctor names the
  setting to change, or run step 3 in a normal terminal.
- Files look corrupt: `<showtime>/skills/showtime/bin/showtime setup --verify`.
- More: https://github.com/FavioVazquez/showtime#readme and `skills/showtime/references/mcp.md`.

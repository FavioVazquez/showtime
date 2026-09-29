# showtime MCP server

A local video studio for your coding agent. Describe a video. Your agent directs. Your machine renders.

This package runs showtime's MCP server (`showtime-mcp`) and its command line (`showtime`) on your own
machine. Scenes are HTML and canvas pages rendered frame by frame; voice-over, music, sound effects,
transcripts, captions, QA and platform exports all run locally. There are no API keys and nothing is uploaded.

## Use it from an MCP client

Any client that starts local (stdio) servers:

```json
{
  "mcpServers": {
    "showtime": {
      "command": "npx",
      "args": ["-y", "@faviovazquez/showtime-mcp"]
    }
  }
}
```

The server has no dependencies and starts in well under a second. Its `doctor` tool says what is
missing on your machine.

## One-time setup

showtime keeps its tools, models and caches in `~/.showtime` (set `SHOWTIME_HOME` to move it). Run
setup once in a normal terminal, because agent sandboxes often block the downloads it needs:

```bash
npx -y -p @faviovazquez/showtime-mcp showtime setup
```

It needs Python 3.8+ or [uv](https://docs.astral.sh/uv/). `showtime doctor` checks the result.

## Settings

| Variable | What it does |
|---|---|
| `SHOWTIME_MCP_BASE` | Folder that relative paths (and new projects) resolve against. Default: the client's working folder. |
| `SHOWTIME_HOME` | Where showtime keeps its tools, models and caches. Default: `~/.showtime`. |

## More

The full skill, the agent integrations, examples and documentation live at
<https://github.com/FavioVazquez/showtime>. MIT licensed.

<!-- mcp-name: io.github.FavioVazquez/showtime -->

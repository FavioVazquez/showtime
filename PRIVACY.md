# Privacy

showtime is open-source software that runs on your own computer. It has no account, no telemetry and no
server of its own, and it does not collect, store or send your data anywhere.

Your prompts are handled by the coding agent you use (Claude Code, Codex, Cursor, Devin or another), under that
agent's own privacy policy.

showtime connects to the internet only to:

1. download its tools and models, during setup or the first time a feature needs one, from the sources listed
   with their checksums in `skills/showtime/setup/manifest.json` (music tracks and sound packs come from their
   creators' own sites, listed in the music catalog and sound-pack files next to it);
2. fetch media or pages when you ask it to, for example an Openverse, Wikimedia Commons or NASA search, or
   capturing a website you name.

Everything it makes stays in folders on your machine. That includes the look history (`showtime history`): a
file in `~/.showtime/history/` listing your recent jobs' names, folders and visual choices (theme, colours, fonts,
transitions, music), kept only so the next video does not repeat them. It is never uploaded; turn it off with
`showtime history off` (or `SHOWTIME_HISTORY=off`) and delete it with `showtime history clear`. Its local preview and studio servers listen only on
127.0.0.1 and require a per-session key.

Terms: showtime is provided under the [MIT License](LICENSE), "as is", without warranty. You are responsible for
the content you make with it and for having the rights to any media you give it. Tools and models that setup
downloads keep their own licenses, listed in `skills/showtime/setup/manifest.json`.

Questions: https://github.com/FavioVazquez/showtime/issues

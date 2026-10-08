# Privacy

showtime is open-source software that runs on your own computer. It has no account, no telemetry and no
server of its own, and it does not collect, store or send your data anywhere.

Some libraries showtime uses have telemetry of their own, and showtime turns it off for every process it
starts: onnxruntime (the voice, alignment, background-removal and speaker-cutout models; `ORT_DISABLE_TELEMETRY=1`, plus
`onnxruntime.disable_telemetry_events()` before each model loads) and the Hugging Face hub client
(`HF_HUB_DISABLE_TELEMETRY=1`). It sets these only when they are unset.

Your prompts are handled by the coding agent you use (Claude Code, Codex, Cursor, Devin or another), under that
agent's own privacy policy.

showtime connects to the internet only to:

1. download its tools and models, during setup or the first time a feature needs one, from the sources listed
   with their checksums in `skills/showtime/setup/manifest.json` (music tracks and sound packs come from their
   creators' own sites, listed in the music catalog and sound-pack files next to it). When a creator's site or a
   model's own host is blocked (an agent sandbox's egress proxy), the file instead comes from showtime's own
   mirror: unmodified release assets on `github.com/FavioVazquez/showtime`, checked against the same checksum
   (`skills/showtime/lib/st/mirror.json`; `SHOWTIME_MODEL_MIRROR` and `SHOWTIME_AUDIO_MIRROR` point at another
   mirror or turn it off);
2. fetch media or pages when you ask it to, for example an Openverse, Wikimedia Commons or NASA search, or
   capturing a website you name, and, when you adopt a page that links Google Fonts (`showtime adopt`), those
   font files and their license texts: the stylesheet and files from `fonts.googleapis.com` and
   `fonts.gstatic.com`, the license from `api.fontsource.org` and `raw.githubusercontent.com`. Only the family
   names the page asks for are sent. `SHOWTIME_OFFLINE=1` skips these fetches (adopt says what to run later);
3. read the pull request you name with `showtime pr-video`: through the GitHub CLI (`gh`) when it is installed
   and signed in, otherwise a public pull request from GitHub's REST API without signing in (no token is sent).
   With `--diff`, `--base` or `--pr-json` it reads your own files and git branch instead, with no network.

Footage never leaves your machine either: transcription, the speaker cutout (`footage cutout`, whose MODNet model is
fetched once on first use, as in point 1) and `edit moments` / `edit clips`, which rank a recording by local signals
(no language model, no service) and render its clips here.

Everything it makes stays in folders on your machine. That includes the look history (`showtime history`): a
file in `~/.showtime/history/` listing your recent jobs' names, folders and visual choices (theme, colours, fonts,
transitions, music), kept only so the next video does not repeat them, and next to it `picks.json`, the look
signatures `showtime new` (and `edit render`, for an edit's cards) picked for your recent projects (the
signature, the project or EDL path and the time). Neither is
ever uploaded; turn both off with `showtime history off` (or `SHOWTIME_HISTORY=off`), delete both with
`showtime history clear`. Its local preview, studio and notes
(`showtime review open`) servers listen only on 127.0.0.1 and require a per-session key.

Terms: showtime is provided under the [MIT License](LICENSE), "as is", without warranty. You are responsible for
the content you make with it and for having the rights to any media you give it. Tools and models that setup
downloads keep their own licenses, listed in `skills/showtime/setup/manifest.json`.

Questions: https://github.com/FavioVazquez/showtime/issues

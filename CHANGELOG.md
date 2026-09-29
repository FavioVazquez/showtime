# Changelog

All notable changes to showtime. Each entry says what changed and why, so this file also answers
"where did X go?". Versions follow [semantic versioning](https://semver.org); the version lives in
`skills/showtime/lib/st/__init__.py` and `python3 scripts/check_release.py` keeps the plugin manifests, the registry files and
`setup/package.json` in sync with it.

## 0.2.0: every coding agent, a lighter first run, a real music catalog

showtime is now a local video studio for your coding agent, not only for Claude Code: describe a video, your
agent directs, your machine renders. The same repository installs in Claude Code, Codex, Cursor, Devin and OpenCode
(each made a real test video) and is packaged for Copilot, Gemini CLI, Antigravity, Cline, Kilo Code, Kiro, Zed, Goose,
Amp, Factory Droid and Qwen Code. The first run fell from about 3 GB (0.1's own `setup --estimate`: 1.3 GB of downloads plus 1.7 GB of
packages) to about 770 MB on Linux x64 (`setup --plan`; about 560 to 610 MB on macOS and Windows); nothing was
removed, the rest is fetched the first time a video needs it. Music now comes from a catalog of 249 produced tracks with the credit written for
you, and Apple Silicon, Linux arm64 and Windows on Arm run end to end in CI.

Highlights (details in the entries below):

- **Any agent.** `showtime install --agent <name>`, Agent Plugins manifests next to `.claude-plugin/`, a stable
  `~/.showtime/bin/showtime` command, background runs for hosts that kill long commands, MCP task ids, and a
  doctor that knows each agent's sandbox. Install steps per agent: `docs/agents.md`.
- **Smaller first run.** `showtime setup --plan` (per platform), `--full` (everything now, for offline use),
  `--fetch`, `--prune`; one fp16 Kokoro voice, Whisper, Manim, the audio library beyond a 41 MB starter part, icons
  and the browser fetched on first use, each announced with its size. Homes made by 0.1 keep working.
- **Music and sound.** A catalog of 249 measured tracks (Scott Buckley, Kevin MacLeod, CC0 and public-domain
  recordings), fetched from the creators on first use, credited automatically in `credits.txt` and the post copy;
  35 more sound packs; Openverse live search.
- **Platforms.** `scripts/e2e.py` and a manual workflow run the whole path on Apple Silicon, Linux arm64, Windows
  11 on Arm and Windows Server 2025; Windows on Arm runs an x64 Python under emulation.
- **Security.** The preview and server commands answer only requests that carry a per-session key.
- **Transcription.** Parakeet-TDT 0.6B v3 is the default (fetched on first use, 465 MB): it keeps "um" and "uh",
  finds 81% of the fillers on a public human-labelled podcast set at 83% precision against its labels (0.1.0's
  Whisper small.en: 11% at 78%), and hears speech under music better (7.3% word errors at equal loudness, was
  19.7%). Local evaluations on small sets; details in the entry below.
- **Faster tests.** `run_all.py --changed` runs only the tests a change can affect.
- **Launch videos.** The default launch/promo film has four to six scenes, a big still hook, a still camera and
  at most one motivated fly-through (from the hook into the product, one continuous dolly), match cuts and a
  dissolve into the end card; motion comes from the content (typing, results landing). A produced catalog track is
  cut so its swell lands on the end card (`showtime audio cuts --for launch`), terminals fit every size
  (`data-st="fit"`), and text cut off by its container, or cropped during a transition, is now a check ERROR;
  `render --size` checks the layout at that size first.
- **Captions, boards and edits.** Caption shadows follow the outline colour (clean on light themes); standalone
  studio boards show a clear "copy for your agent, then paste it" step; footage edits are mastered to -14 LUFS
  unless you ask to keep the source level.

### Before publishing 0.2.0 (release checklist)

- [x] **Windows end-to-end rerun**: `windows-11-arm` and `windows-2025` pass end to end with the fast suite, as do
      `macos-14` and `ubuntu-24.04-arm`.
- [x] **README and CHANGELOG** launch-video entries written.
- [ ] **Publish the MCP packages, in order** (the maintainer's publish notes): npm
      `@faviovazquez/showtime-mcp`, the `.mcpb` as a release asset of `v0.2.0`, the MCP Registry, Smithery. The
      README's "MCP only" section and `docs/agents.md` say those routes exist "once 0.2.0 is published".
- [ ] **Directory listing text** for Cursor, Codex and Cline.
- [ ] Carried over from 0.1.0: mirror the GeneralUser GS SoundFont (its author asks projects to host their own copy;
      sha256 `9575028c…688cfe`) and the MuseScore_General SoundFont on a release and point `setup/manifest.json` at
      them; pin size and sha256 for the extended audio-library tier (about 150 entries record theirs on first download).

### Changed: verbatim transcription by default, fillers found, speech under music heard

- **Parakeet-TDT 0.6B v3 is the default transcription model** (sherpa-onnx, int8, CC-BY-4.0): it writes
  "um"/"uh" as words and covers 25 European languages including English and Spanish. It is fetched on
  first use (465 MB, announced with its size). Whisper stays for other languages (`--language xx`
  picks it) and for anyone who asks (`--model turbo|small`). Why: Whisper small.en, the old default,
  found 11% of the fillers on PodcastFillers test excerpts (Whisper turbo 40%); the new pipeline finds
  81% at 83% precision against the dataset's labels (event match within 200 ms; local evaluation).
- **A filler scan after ASR** decodes voiced pauses no word covers, and words far longer than their
  spelling, again on their own, and adds the hesitations it hears (`"filler": true`). Backchannels
  ("mm-hmm", "uh-huh") are words and never cut. Spanish "este" / "o sea" are cut only on request
  (`edit cut --filler-set es-discourse`). `edit cut --strict-fillers` cuts only fillers a second decode
  confirmed.
- **Cleaner filler cuts:** the pause left where a filler was is capped at 0.2 s, each cut edge moves to
  the quietest 10 ms within 40 ms, and cuts get a 20 ms equal-power crossfade (was a 30 ms fade out and
  in). On the benchmark interview the default commands now find and cut all five known "uh" (the
  benchmark's own scorer credits 4 of 5; the same commands in 0.1.0 removed none).
- **Speech under music:** transcribing a video showtime rendered reads the dry narration stem the render
  kept (the mixer now writes `<mix>.voice.wav`; edit renders record the speech before the music bed).
  Other footage: when the music is within ~8 dB of the voice, the voice is separated first with UVR's
  MDX-Net model (ONNX, no PyTorch, 67 MB on first use), unless the bed is ducked under the speech.
  On a speech-over-music test set this took word errors from 6.6% (small.en) to 4.4%, and at equal
  loudness from 19.7% to 7.3%.
- **CrisperWhisper 2.0** is available as an opt-in "max accuracy" model (`--model crisper`): its weights
  are for non-commercial use, so it asks for `--accept-license` once; it needs PyTorch, which no longer
  ships for Intel Macs, so it says so there instead of trying.

### Added: faster test runs (`--changed`, long files in parts, big machines)

- **`run_all.py --changed [REF]`** runs only the test files a change can affect, `--explain` says why
  each was picked. It combines what each test really used in earlier runs (recorded while the suite runs:
  every repository file its Python and Node processes import or open), a static scan (imports, named
  paths, `showtime <cmd>` routing, template names) and a short override table for docs and manifests; a
  file it cannot place runs everything. On the 64-core build machine an edit to the transcriber picks
  the footage, packaging and portability tests plus the hygiene check; one such run took 27 s.
- **Long files run in parts** on machines with many cores (from 9 processes at once): tests that share
  state stay together, tests the plan does not know run in the first part, and each part is checked to
  have run its tests exactly once. Laptops and CI runners keep running whole files.
- **`-j auto` uses big machines**: up to half the cores (was at most 8), fewer when free memory is short;
  there each test's model threads are sized to its share of the machine. The fast suite on 64 cores went
  from 219 s to 131 s at `-j 32` (159 s while other jobs loaded the machine); the HTML export file, which
  runs alone, is 78 s of that.

### Added: one repository for every coding agent, and `showtime install --agent`

- **Manifests next to `.claude-plugin/`** (which is unchanged): an Agent Plugins 1.0 `plugin.json` +
  `mcp.json` at the root (Codex, Copilot, Kiro; the MCP server starts from `./skills/showtime/mcp/server.mjs`
  in the plugin folder), `gemini-extension.json` (Gemini CLI, `${extensionPath}`), `mcp_config.json`
  (Antigravity, which installs the root plugin from a clone) and the Copilot crew in
  `com.github.copilot/agents/`, because Copilot takes agents only from there once a root `plugin.json`
  exists. Cursor and Devin read `.claude-plugin/` and need nothing new. `scripts/build_agents.py`
  regenerates the crew copies from `agents/*.md`.
- **`showtime install --agent <name>`** for Codex, Copilot, Cursor, Devin, Gemini CLI, Antigravity,
  OpenCode, Cline, Kilo, Kiro, Zed, Goose, Amp, Factory, Qwen and Claude Code: links the skill where
  the agent looks (Kiro, Cline, Qwen and Antigravity have their own folders), writes the ten crew agents
  in the agent's format (Codex TOML, OpenCode `mode: subagent`, Gemini tool names and `timeout_mins: 60`,
  Kiro JSON; Claude-only fields and model aliases dropped) and adds the MCP server as
  `<SHOWTIME_HOME>/bin/showtime mcp`. It merges config files (one `.before-showtime` backup) and leaves a
  file it cannot parse alone with the entry printed; `--print`, `--project`, `--uninstall`, `--list`.
  The skill carries a copy of the crew (`setup/agents/`) so a skill installed on its own has it too.
- **Real agent tests** ("make a 5-second test video that says hello", qa with no FAIL): Codex CLI
  0.158.0 (plugin), Cursor CLI (plugin folder), Devin CLI 3000.11.3 (local plugin), OpenCode 1.18.33
  (`showtime install`). Per-agent install steps: `docs/agents.md`.

### Added: a portable core (the stable command, background runs, MCP task ids, a sandbox-aware doctor)

- **`~/.showtime/bin/showtime`** (`.cmd`/`.ps1` on Windows) is written by setup and repaired by `doctor`. It runs
  the skill recorded in `<home>/skill-path`, finds a skill that moved, follows the newest version and keeps a copy
  of a skill that runs from npm's cache, so it keeps working when a plugin update changes the skill folder. Setup
  prints how to put it on `PATH` and never edits a shell file.
- **SKILL.md and the crew agents no longer depend on Claude Code's variables.** Paths are relative to the skill
  folder, SKILL.md has a `compatibility:` line, no command is built from `${CLAUDE_SKILL_DIR}` or
  `${CLAUDE_PLUGIN_ROOT}` (other hosts leave them empty, so `${CLAUDE_SKILL_DIR}/bin/showtime` became
  `/bin/showtime`), and the crew agents call `showtime` from `PATH`. `check_release.py` enforces it.
- **`showtime <cmd> --background`** and `showtime status <run> [--wait S] [--cancel] [--runs]` for hosts that kill a
  command after a few minutes; a "still running" line every 45 s when stderr is not a terminal.
- **The MCP server answers `initialize` in milliseconds and runs long tools as background runs**: after about
  20 s a call returns a task id and `status {task}` reports progress and the result (Claude Code keeps waiting and
  gets the result in one call). `showtime mcp` starts it; a `${...}` placeholder a host did not fill counts as
  unset, and the projects folder is never inside the plugin.
- **`doctor` knows agent sandboxes**: whether `~/.showtime` and the work folder are writable and whether the
  network is reachable, and it names the setting to change for Codex, Antigravity, Cursor, Copilot's cloud agent,
  Gemini CLI or Devin. `SHOWTIME_HOME` is the escape hatch (relative values, a project's `.showtime` found without
  any variable, uv and npm caches moved in when their folders are read-only).
- **Windows.** The home lookup searches every home folder Windows can name (`USERPROFILE`, `HOME`,
  `HOMEDRIVE`+`HOMEPATH`, the account's real profile); `showtime version --json` says how the home was chosen.
- Tests: `tests/test_portable.py`, `tests/test_mcp.py`.

### Changed: a smaller first download, and everything else on first use

- **The default install is about 770 MB on Linux x64 (about 3 GB before)**, 560 to 610 MB on macOS and Windows,
  with a Chrome, Edge or Chromium already installed (about 100 MB more without one). `showtime setup --plan` lists
  every component per platform (`--platform`) with its size, source, sha256 and when it is fetched; `--urls` lists
  the pinned files for pre-seeding; `--full` installs everything now (6.6 to 7.2 GB, for machines that will be
  offline; `--seed DIR` reuses files); `--fetch NAMES` fetches chosen first-use components; `--prune` removes what
  older versions left behind. `doctor` lists the first-use components.
- **Kokoro** is one fp16 timestamped model (163 MB) instead of two fp32 files (651 MB), loaded with an in-memory
  guard for half-precision 0/0 phase bins.
- **Whisper** (small.en and its engine, about 500 MB) is fetched on the first transcription, **Manim** and
  **ManimGL** before the first scene, **icons** one at a time (a few KB each, pinned versions), the **audio library**
  in parts (a 41 MB starter part, category parts when a search finds fewer than three results), and the
  **browser** is an installed Chrome/Edge/Chromium first, else the pinned Chrome Headless Shell (about 100 MB,
  sha256, resumable); the full Chromium is fetched only for `--headed` runs or when the shell cannot start.
- Every first-use fetch prints "fetching X (N MB) for Y" first, is pinned by size and sha256, resumes, and fails with
  exit code 3 and the exact command when the machine is offline. A shared Hugging Face cache is reused
  (sha256-verified, hard-linked; `SHOWTIME_SHARED_HF_CACHE=0` opts out). imageio's ffmpeg is a last-resort
  fallback only. The Windows ffmpeg is BtbN's GPL shared build (86 MB) before Gyan's essentials (115 MB).
- **Upgrading from 0.1 needs no action.** A home with the old fp32 Kokoro keeps working (`doctor` warns and offers
  `showtime setup`, then `setup --prune`); nothing that worked stops working.
- Docs: `references/onboarding.md` has the first-use table; the README and `docs/agents.md` state the new sizes.

### Added: a produced-music catalog, credits that write themselves, more sound

- **`lib/st/audio/music_catalog.json`**: 249 produced tracks (Scott Buckley 128, Kevin MacLeod 82, Wikimedia
  Commons 20, Internet Archive 19), each pinned by URL, bytes and sha256, tagged by shelf, mood, energy, tempo, use
  and vocals, with a measured ending, quiet intro and highlight offset. Nothing is bundled or re-hosted: a mix (or
  `audio music fetch <id>`, or `setup --full`) downloads a track from its creator's site the first time, announces
  its size and caches it in `~/.showtime/music`.
- **A quality gate**: every track was downloaded, decoded and measured (format, bandwidth, stereo, clipping, hiss,
  crackle, loudness range, silences, length, rhythm, ending); 16 failed and were removed. Jamendo artists were
  removed too (its own terms add conditions to commercial use); Jamendo is only reachable with
  `--source jamendo` and a warning.
- **Commands**: `audio music search|pick|fetch|info|veto|stats|presets|check|openverse`, `audio packs list|fetch`,
  `audio credits`. `pick` ranks by energy, length fit and a featured track; a catalog track skips its near-silent
  lead-in, or starts at its loudest stretch with `"offset": "highlight"`. `audio music openverse` searches
  Freesound and Wikimedia Commons live (CC BY and CC0).
- **Credits.** Every render that uses a catalog track writes the creator's credit into `credits.txt`, a description
  block in `share.txt` and the end-card line, and prints a note (Scott Buckley's Content ID only claims uncredited
  uses). A CC BY sound without credit text fails the mix, and `qa` warns when Content ID-protected music lacks its
  credit in `share.txt`.
- **Sound packs**: 35 extra packs (34 CC0, 1 CC BY: applause, cheering, rain and thunder, camera shutter, pencil
  and marker writing, clicks, and more) installed the first time a mix or search needs them.
- Docs: `references/music.md` (a produced track, a composed bed or none), `references/audio.md`, the workflows.
  Tests: `tests/test_music.py`.

### Added: end-to-end platform tests, Windows on Arm

- **`scripts/e2e.py`** runs everything through the user's entry point on any OS: setup, doctor, a voiced render
  with qa, HTML export, transcription, captions (SRT/VTT and burned in), an MCP handshake and the fast suite, with
  per-step logs and a summary; a step whose output has a Python traceback fails even with exit code 0.
  **`scripts/e2e-windows.ps1`** wraps it for a standard user on Windows 10/11 (entry points, execution policy, a
  BOM script, a path with a space, a results zip). **`.github/workflows/e2e.yml`** (manual) runs it on `macos-14`,
  `ubuntu-24.04-arm`, `windows-11-arm` and `windows-2025`. What ran where is listed under Requirements in the README.
- **Windows on Arm**: `arch()` reports arm64 even from an emulated x64 Python; setup builds the venvs with x64
  CPython 3.12 (ctranslate2, opencv-python, av and numba have no Windows arm64 wheels) and recreates a venv of the
  wrong architecture; downloads without a win-arm64 build fall back to win-x64. The native arm64 ffmpeg is tried
  first, then the x64 builds; a failing ffmpeg now says why (exit code with its Windows status name, stderr tail or a
  time-out), and `doctor` says why it passed one over. phonemizer's espeak-ng exit hook no longer prints a
  `PermissionError` there (the folder is removed on the next run).

### Added: MCP packages and housekeeping

- **`server.json`** (MCP Registry) and **`packages/npm`** (`@faviovazquez/showtime-mcp`: the skill folder plus
  two bins, `showtime-mcp` for the stdio server and `showtime` for setup), **`scripts/build_packages.py`** (npm
  package and a reproducible `.mcpb` bundle), **`llms-install.md`** (step-by-step install for agents such as
  Cline). Nothing is published yet.
- **The preview and server commands need a per-session key.** They answer only requests that carry the server's
  random 256-bit key (the printed link has `k=<key>`, traded for an HttpOnly SameSite=Strict cookie); anything else
  gets a plain 403 that says where the link is. Before, any web page open in the browser could read project files
  over `http://127.0.0.1` (the server sent `Access-Control-Allow-Origin: *`). `site capture` names showtime's own
  server instead of calling its 403 a bot check.
- **CI runs the Intel Mac only nightly and by hand**; pushes and pull requests run Linux, Windows and Apple
  Silicon. `check_release` refuses links to the old Codex documentation address.

### Changed: wording, README, docs and site for every agent

- The tagline is "A local video studio for your coding agent. Describe a video. Your agent directs. Your machine
  renders." Claude Code is named in its own install section and where it is factually the host. README, its art
  (hero, pipeline, what runs where, crew hand-offs), plugin and extension descriptions, `brand.json`, the site and
  the docs say so; the CLI's help, `setup` and `doctor` say "your coding agent" instead of Claude.
- **README**: a "Works with" section (tested agents, the ones that should work, the install for each, the MCP-only
  route), new sizes and first-use downloads, the music catalog, the platform list with what actually ran where, and
  a "New in 0.2.0" list. **Docs**: `docs/agents.md` is part of the docs map and the site.
- **`doctor`** labels a plugin install by the agent that owns the folder ("installed as a plugin for Codex") and the
  row is `agent skill` (it was `claude skill`). **SKILL.md** says the launcher is `<skill folder>/bin/showtime`
  and that a plugin root has no `bin/` (an agent looked for it there in testing).

## 0.1.0: final pass (changes after the first complete build)

### Changed: pre-publish pass (brand media, requirements, platform status)

- **The 4-second sound logo ships as MP3 only** (`assets/brand/motion/sound-logo.mp3`); the 1.1 MB WAV
  master is no longer in the repository. The CLI keeps its own 79 KB WAV cut
  (`skills/showtime/lib/st/sounds/sound-logo-short.wav`), because the players it falls back to on Windows
  (`System.Media.SoundPlayer`) and Linux (`aplay`) play WAV only.
- **The brand stings are release assets.** `sting.mp4` and `sting-square.mp4` moved to `examples/_brand/`
  and are published with the examples' media release (`publish_media.py` sends every video in
  `examples/_brand/` there, whatever its size); `BRAND.md` and `brand.json` link to the release URLs.
- **yt-dlp is no longer installed.** Nothing in showtime used it; it and the five packages only it
  needed (brotli, brotlicffi, mutagen, pycryptodomex, websockets) left `requirements.in`, the lock, setup's
  import check and `doctor`.
- Docs: the core audio library is about 249 MB and takes about 10 to 15 minutes to fetch; the rembg entry
  in `setup/manifest.json` names its default model (isnet-general-use, about 170 MB); the Windows Node.js
  command is `winget install OpenJS.NodeJS.LTS --source winget` (without `--source`, winget can also query
  the Microsoft Store source and stop to ask the user to accept its terms).
- **CI.** `checks.yml` runs the quick release checks (check_release, the skill structure test) on every
  push and pull request. `ci.yml` sets up the core tier and runs the fast suite with `-j auto` on Ubuntu,
  Windows and Apple Silicon (macos-14), plus the Intel Mac once the repository is public; changes that only
  touch Markdown, `docs/`, `assets/readme/`, `site/` or `.out-of-scope/` skip it. The showtime runtime
  (ffmpeg, models, SoundFont, Node packages, Python venv) is cached per OS, keyed on the setup manifest,
  the requirements and Node locks, `setup.py` and the Python version. One run per branch at a time (a newer
  push cancels the older run); the nightly tier runs only on a public repository or by hand; a manual run
  can pick runner images and test files.
- **The HTML export test holds up on small CI runners.** On a 2-core runner with a software GPU, its
  real-time playback checks failed for reasons of speed (the driver's 1.5 s window took 10 s on Windows
  while the video played on to its end). It now records how long that window took and the player's
  transport events; on a machine too slow to play in real time those checks skip with the reason, after
  everything that does not depend on speed has run. On 2 cores or fewer, "the picture never runs ahead of
  the sound" allows the player's own extrapolation of a coarse audio clock (at most 0.25 s).
- **README diagrams show their wide art on github.com.** Each `<picture>` had a `(max-width: 700px)`
  source for a tall phone layout, but GitHub's sanitizer keeps only `prefers-color-scheme` in
  `<source media>`, so the narrow art won on desktops too. The README and `docs/README.md` now pick only
  between the light and dark wide art, which scales down on phones, and the 16 `-narrow-` SVGs are gone
  from `assets/readme/` (the site uses the wide art as well).
- **Platform status.** Windows x64 has been tested end to end (Windows Server 2025, as a standard user)
  and Apple Silicon in CI (GitHub's macOS 14 arm64 runners: core setup and the fast suite, which includes
  real renders); the README's Requirements, status table and badges say so ("tested: Intel Mac · Apple
  Silicon · Linux x64 · Windows x64"), and that Windows 10/11 desktop editions and Linux arm64 have not
  been run yet. A run on a physical Apple Silicon Mac is still welcome.
- **Site link previews use absolute URLs.** `og:image` was a relative path, which link previews (Slack,
  X, iMessage) cannot load. Every page now has an absolute `og:image`, `twitter:image` and `og:url` built from
  `site_url` in `site/config.json` (or the repository's GitHub Pages address).
- **CI runs the fast suite in three shards per OS.** `run_all.py --shard I/N` runs one of N parts of the
  test files, split by fixed per-file weights (`SHARD_WEIGHTS`, fast-suite seconds from a CI run; longest
  first into the lightest part), so every machine computes the same split and each file runs exactly
  once; inside a shard two files run at a time (`-j 2`, also on the 3-core Apple Silicon runner, where
  `auto` would pick 1). `ci.yml` runs shards 1/3, 2/3 and 3/3 as
  separate jobs on Ubuntu, Windows, Apple Silicon and, on the public repository, the Intel Mac
  (`macos-15-intel`: the `macos-13` image is retired); shard 1 also runs the render smoke and the
  path-with-spaces shims. On one 2-core runner the suite took 23 to 31 minutes per OS.
- **The HTML export test runs alone** (`SERIAL` in `run_all.py`). Its player checks watch playback in real
  time; on the public 4-core runners, sharing the machine with another file's Chrome left the player
  drawing 1 to 4 frames in the 1.5 s window on Windows and the Intel Mac. A file in `SERIAL` counts double
  when the shards are balanced. Running alone was not enough on the Windows image (1 frame drawn while the
  clock ran on), so on a CI runner (`CI` set) those real-time checks skip with the reason when the browser
  draws fewer than 5 frames in the window or the sound is still loading, as they already did on 2 cores;
  everything before them (requests, errors, duration, soundtrack) still runs, and on a desktop they
  always run.

### Changed: the examples have their own repository

- The 22 examples, the launch film, `examples/MEDIA.json` and `scripts/publish_media.py` moved to
  [showtime-examples](https://github.com/FavioVazquez/showtime-examples), and the media release (every
  example file over 10 MB and every `.mov`) is that repository's. This repository is the plugin people
  install, well inside the plugin directory's size and file limits. Links to an example point at
  showtime-examples; the README art (`assets/readme/`) stays here.
- `site/build.py` reads the examples from `--examples DIR`, else from a clone next to this one
  (`examples_dir` in `site/config.json`); the Pages workflow checks showtime-examples out and downloads
  its release.
- `scripts/check_release.py` has a `directory` check: the plugin directory's limits (files, sizes,
  symlinks, Windows-safe names, `.gitattributes`, README, LICENSE, plugin.json fields, a default for
  every userConfig option). It runs by default where there is no `examples/` folder.
- The README says what showtime runs and downloads, and what goes over the network.

### Fixed: final release pass (parallel renders, talking heads, seeks, exports, boards)

- **Parallel renders no longer collide in the shared audio cache.** Temp files are unique per process
  (`common.part_path`) and every cache fill (synth hits, typewriter clicks, composed beds) holds a
  per-entry lock (`common.cache_lock`), so three renders of one project mix at once and get identical
  audio. Font, voice and decode caches use the same temp names.
- **A failed mix is loud.** When `showtime audio mix` fails for a mix with synth/compose tracks or
  ducking, render stops with the error instead of shipping the simple built-in mixer's version (which
  drops those sounds); a files-only fallback warns with `AUDIO FALLBACK`. The mix is retried once and
  has a 20-minute timeout; timed-out child processes are killed (SIGKILL after 5 s).
- **The simple mixer cannot hang.** One ffmpeg graph with every file as an input (the same file twice,
  tracks 50 s apart) deadlocked intermittently in ffmpeg 9 (4 of 45 parallel runs); each track is now
  rendered to an aligned stem and the stems are summed (0 of 45). It also honours a track's `dur`.
- **qa: a speaker holding still is not a frozen picture.** A long hold in camera footage (noise in every
  part of the frame plus local motion) with sound is `held_shot` (INFO); without sound it is a `frozen`
  WARN. Motion-graphics holds (also under grain or typing) and any hold in a project that plays no
  `<video>` are judged as before.
- **Synth scores resume at their level on a realtime seek.** Envelopes written after their start time
  (building a voice can outlast the 60 ms lead) faded the note in over half a second; compressors start
  released.
- **review-pack finds the cuts inside a chapter** (project clip starts and cuts seen in the picture).
- **export html fits footage under the limit.** A single file over `--max-mb` because of video clips
  gets those clips re-encoded (2-pass, for the export only) at the bitrate that fits; `--fit off` stops
  with the breakdown instead.
- **Stills of a `<video>` land on the right frame** when the clip loads late (added by a handler, a
  new src): the seek waits for its data and computes the loop point then; a `seeked` from an earlier seek
  no longer ends the wait; `snap` warns when a video missed its frame.
- **Studio board sticky bars stay opaque in WebKit** (opaque fallback before `color-mix()`, 96 %
  over the blur, own layer above videos).
- **Composed beds carry their license.** `audio compose` writes `<file>.license.json` (`generated`,
  no attribution); older beds are recognised by their beats file.
- **Benchmark judges look at the pictures.** Judges get the exact frame paths (they only have Read and
  cannot list folders), the harness records which images each judge opened, and a judgment that did not
  open every video's frames (or says it could not) fails. HTML deliverables are judged from stills of
  their screen recording, not from screenshots of the start screen.
- Dependencies: BtbN ffmpeg builds re-pinned to `autobuild-2026-09-27-13-04` (n9.0.2; the old tag is
  rotated out), simple-icons 16.33.0. Node advice: 24 or 22 LTS (the fast suite passes on Node 24.21.0).

### Added: a companion site, a visual crew, and diagrams that explain

- `site/`: a static companion site built by `python3 site/build.py` (landing page with the hero film,
  a gallery that plays every example with filters by use case, one page per example with its HTML
  video embedded, the crew, and every guide in `references/` as a page with a sidebar and search).
  No framework, no trackers, fonts served from the site. The gallery previews each example on hover
  with a silent 4-second clip cut at build time (`site/content/previews.json`). `.github/workflows/pages.yml` builds it and
  downloads the example videos from the media release at deploy time, since they are not in git.
- README: the crew as an illustrated cast of ten (all optional, said so on the card) and a diagram of
  who hands what to whom; diagrams for the pipeline, what runs where, studio mode, the anatomy of an
  HTML video and the output formats, each in light and dark and in a narrow layout for phones; the
  launch film as the hero (its poster links to the release asset until the MP4 is attached in GitHub's
  editor), and a hidden benchmark section.
- The launch film (`examples/_launch/`): 40 s in 16:9, 1:1 and 9:16 plus an HTML video, published as release
  assets with the example media; a silent 6-second teaser loops in the site's hero, and "Watch the film"
  plays it with sound. Music: "With These Hands" by Scott Buckley, CC BY 4.0; per the composer's terms the
  audio ships only inside the film, never as a separate file. `assets/readme/social/launch-1280x640.jpg` is
  the social preview and the site's `og:image`.
- `examples/README.md`: a wall of all 22 previews, then one card per example with its loop, the
  sentence that made it, what it shows and its links. `docs/README.md`: the programme as a map, and
  "choose your path" as cards with a preview of an example made with each workflow.

### Changed: the README is a show, with a gallery and a docs map

The README now opens with an animated curtain (SVG, CSS only, light and dark versions, still for
reduced motion), a three-step quick start, an animated Claude Code session that ends on showtime's real
completion card, and a gallery of all 22 examples grouped by use case with looping previews (animated
WebP made with `showtime deliver exports --targets webp-small`, in `assets/readme/`). Every example's
request is there as a copy-ready prompt. Deep dives (every command, the crew, studio mode, the audio
toolkit, Manim, the HTML player's keys), install details and troubleshooting fold away. New
[`docs/README.md`](docs/README.md) maps every guide in `skills/showtime/references/` by what you are
making. `examples/README.md` has the same grouping, with lengths, formats, watch links (release assets
via `{{RELEASE_URL}}`) and HTML videos. Platform status is stated as tested (Intel Mac, Linux x86_64)
versus supported and in testing (Apple Silicon, Windows, Linux arm64).

### Changed: calmer, more premium defaults where the blind benchmark found weak spots

A blind benchmark against other video workflows (six tasks, a human judge) put showtime first on four;
the viewer's comments on its own outputs drove these fixes. Each names what the session actually did.

- **Music taste.** A data report and a math explainer got beds the viewer called "like the Sims" and
  "a DIY YouTube video". Root causes: the `data` template shipped `corporate-minimal` at 110 bpm with a
  `build`→`drop` section map (snare roll, crash, tom fills, reverse cymbals, a glockenspiel motif, then a
  whoosh, a paper swipe, a thock and a ding on top); the docs routed explainers and "premium" to that
  style; and `ambient-pad`, which the math session tried first before switching to the corporate bed,
  went silent every other bar. Now:
  - two new restrained styles, `underscore` (strings, contrabass, a soft felt-piano pulse, no drums, no
    melody; the new `audio compose` default and the bed for explainers, data, reports and math) and
    `minimal-pulse` (warm pad, sub bass, a muted pluck ostinato, a soft kick; tech and data);
  - restrained styles (`underscore`, `minimal-pulse`, `ambient-pad`, `piano-emotional`,
    `corporate-minimal`) never add section crashes, drum fills, snare rolls, risers or reverse cymbals;
    `corporate-minimal` lost its glockenspiel (a sparse piano motif instead) and slowed to 104 bpm;
  - fix: a chord held for two bars (`ambient-pad`, `underscore`, `cinematic-build`, `dark-tension`,
    `deep-house`) was cut at the end of its first bar, leaving the pad and bass silent for the second;
    the 45 s ambient bed's 10th-percentile level goes from -58.9 to -22.6 dBFS. Library beds composed
    by the old composer are re-rendered by `showtime audio lib generate` (`COMPOSER_REV`), and the
    generated tier gains four `underscore`/`minimal-pulse` beds (28 in all);
  - the `data` template: an `underscore` bed (`intro`/`verse`/`chorus`/`outro`, no drop) and one soft
    chime on the closing number; the `film` template's score lost its claps and whoosh;
  - `references/music.md` section 1: a taste rule (restraint reads as premium; no music is an option),
    a content → style table and a "what not to pick unless asked" list (mallet and plucked leads,
    claps and shaker under data, build/drop maps under charts, game-UI effects); routing in
    `data-story.md`, `launch-video.md`, `tutorial.md`, `footage-edit.md`, `manim.md`, `tones.md`,
    `sound-design.md` follows it; SKILL.md has a red flag for it;
  - ducking under a voice defaults to 12 dB (was 10): the bed sits about 16 dB under speech.
- **Crowded chart numbers.** A data story's 18-bar decade chart put the negative bars' value labels on
  top of the category labels ("−0.27" over "1900") and ran neighbours 4 px apart; `showtime check` said
  nothing because text overlap only fired past 15 % glyph overlap and nothing measured "too close".
  Bar charts now leave room under the lowest negative bar, plan value labels per state from the
  settled values (shrink slightly, then hide the least important; highlighted, annotated, max, min,
  first and last always show; labels fade across morphs; `valueLabels: "all"` keeps every one, `false`
  hides them), thin category labels that don't fit their slot, and slide an hbar value label past a
  `ref` line. `check` has a new `labels_crowded` warning for SVG labels that touch or sit closer than
  0.15em (`label_gap_em` in `runtime/thresholds.json`; notes while a chart is still animating).
  Same chart, before/after: 18 → 14 labels, tightest gap 4 px → 94 px, 3 → 0 labels on the axis.
- **Captions for vertical shorts.** The reel's viewer said the subtitles "were not the best". The
  session used the short template's `bold-pop` karaoke: ALL CAPS with a heavy outline, 2-3 word cards
  that broke mid-phrase and ended on weak words ("EMPTY LINES BEFORE" / "SORTING"), an active-word
  scale that made neighbours collide ("NATURALSORT"), nine emphasis terms, and two-line cards centred
  on 64 % that grew up into the content. Now: a new `clean-pop` style (sentence-case heavy sans, thin
  edge and soft shadow, the spoken word turns the accent) is the component default and the short
  template's; cards are phrase-aware (never end a card or line on an article, preposition, conjunction
  or auxiliary, in en/es/fr/pt/de; no one-word cards; `minShow` respected); the lower block hangs from
  62 % and grows down inside the safe box; the pop is 1.04 and emphasised words no longer stay scaled;
  at most one emphasised word per card (check warns past five terms). Burned ASS captions
  (`edit render`, `showtime captions`) use the same no-weak-ending rule. `bold-pop` stays for loud,
  hype pieces.
- **Punch-ins on jump cuts.** The filler-cut session followed `footage-edit.md` ("`zoom: 1.12` on
  alternate ranges hides jump cuts") and the viewer disliked the zoom in and back out at every cut. The
  recipe now leaves jump cuts alone by default; `editing.md`, `story.md` and the vertical recipe explain
  when a punch-in is right (one scale held per sentence or section, on request). `edit check` and
  `edit render` flag a scale that keeps bouncing at cuts (`punch_bounce`).
- **HTML report transitions.** The `data` template shipped three unrelated handoffs (`push left`,
  `blur-dissolve`, `morph-warp`) that the report session kept; the viewer found them nonsensical and
  chopped. The template now uses one calm family (a dissolve out of the title, dips between charts);
  `transitions.md` gains rules for data stories and reports and "never transition mid-sentence".
- **Fact discipline in launch videos.** A reviewer could not verify four small specifics in the launch
  video (a backup file name, a line count, a code excerpt, and a mid-animation frame that looked like an
  unsorted result). The first three came from running the tool, but nothing on disk said so.
  `story.md` section 6 now treats specifics as claims (a doc quote or an evidence file under
  `<job>/work/evidence/`, else obviously generic), warns off incidental specifics, and requires every
  held frame to be true on its own; `launch-video.md`, `changelog-video.md` and the researcher follow it.

### Added: small touches at the terminal (brand mark, completion card, opt-in sound)

A person running showtime in their own terminal now sees the Curtain Call mark (a two-line curtain in
velvet and gold) above `showtime --help`, `setup` and `doctor`, and a three-line completion card after
`render`, `export html`, `manim render`, `edit render` and `deliver exports`: what was made (length, size),
where it is, the qa verdict when one is recorded for that exact file, and the one next command. With
`SHOWTIME_SOUND=1` or the new plugin option `sound` (default off), a 1.8 s cut of the sound logo
(`skills/showtime/lib/st/sounds/sound-logo-short.wav`, 79 KB) plays when a command that ran over 20 s
finishes; it uses a player the system already has and never delays or fails the command. All three stay
off when the output is not a terminal (so Claude's tool calls, pipes and logs are unchanged), with `--json`,
`NO_COLOR`, `TERM=dumb`, `CI` or `SHOWTIME_COLOR=never`; the logic lives in `lib/st/delight.py` and its Node
twin `scripts/lib/delight.mjs`. Why: the plan's delight pass, without adding a step or changing any
machine-readable output.

Also: the most common deliver and qa errors (`file not found`, `has no video stream`, `could not decode`,
poster time outside the video, wrong cover/thumbnail format, an export that would overwrite its input,
not a showtime project) now carry a `fix:` line with the exact next step, and a bad option in a Node
command (`render`, `export`, ...) says `fix: run ... --help for every option, with examples` like the
Python commands. `edit render` shows its "next:" line inside the card at a terminal.

### Changed: fixes from the batch-2 examples (friction log, examples 12-22)

Each item was hit while making examples 12-22; the fix is in code with a test unless marked docs.
- **Transitions.** A transition window snaps to frames like clip edges: a scene start written as
  `6.6667` or `53.434` (within 1 ms after a frame) no longer shows the incoming scene alone for one frame
  before the transition (examples 12, 14, 17; check and qa both missed it). Layers placed after the
  incoming scene (a map inset, labels) stay above every transition window instead of dropping under the
  scenes (example 19). `wipe left` is the straight wipe (a direction used to be ignored for the default
  diagonal). Film `dip` draws the outgoing scene until the cut and the incoming one after it (a title
  card without a ground showed the last shot through the dip). `ridged-burn` embers are round points,
  not square blocks. Docs: text in displacement shaders, WebGL windows over `--alpha` scenes, a shader
  transition inside a canvas film.
- **check.** The text audit sees text under `pointer-events: none` (lower thirds, overlays: it was
  reported "covered" and must_show FAILed), measures SVG text through its transforms and viewBox (a
  label in `scale(2)` was reported at half size), and keeps the full text of each line (must_show
  missed words after character 80). A low-contrast finding names the failing span ("1" in "1import
  json ...", a line number). Numbers alone (axis ticks, years) skip the reading-time rule. An overlay
  page (`<body data-overlay>` or showtime.json `"overlay": true`) reports gaps as notes, not
  `dead_air`. The seek-order error hints at handlers that keep state between seeks; the timers warning
  says when the call came from a library. `check --page other.html` and `--size` write to
  `work/check-<page>[-<WxH>]/`.
- **One page, several sizes.** snap, check and studio frames follow a page's own (render already did)
  `ST.config({width, height})` when showtime.json sets none (a square page was captured stretched to
  1920x1080). `render|check|snap --size 1080x1920|9:16` renders one page at another size for a run;
  `render --job J --size 9:16` writes `<job>/1080x1920.mp4`, a variant. `snap --page` gets its own
  folder, `snap -o still.jpg` with one `--at` writes that file, and `--width` can upscale.
- **Alpha renders.** Themes' scene and stage fills are transparent under `--alpha` (a steps overlay came
  out as a dark plate unless the page reset `--scene-bg`); a background a scene sets itself still paints.
- **Components.** chart: `valueLabels: false` also hides hbar race values; a race title that only
  changes after " · " swaps without fading (it pulsed at 0.25 s steps); `locale`. count-up follows
  `<html lang>` (`13,7` on a Spanish page) or `locale`. A component a page module `define()`s after
  `index.js` mounted the page is mounted (it warned "unknown component"); docs: await `ctrl.ready`
  before touching a component's DOM. caption-karaoke `group: "phrase"` for fast speech, and
  highlight-box blends the ink with the gliding box (the next word vanished for 3 frames on dark
  grounds). lower-third: `in` (entrance seconds), `position: top`, larger type in 9:16, accent above a
  themed plate. feature-grid `cap`; notifications `top` (and page CSS `top` wins); logo-reveal and
  end-card `bloom: false`. code-block line numbers and diff gutters clear 4.5:1 by default. The
  `mediaReady` fallback timer is cleared (every page with a `<video>` warned about a timer). Bare
  `code, kbd, pre` use the theme's mono face; the paper theme falls back to Space Grotesk for glyphs its
  display face lacks (the ʻokina).
- **Studio.** Board shortcuts work after using the Compare wipe (a range input kept focus and swallowed
  the keys). An artifact export (`studio export --target artifact`) names a file left out of the page
  and where it is in the job folder instead of a dead placeholder, and says when the viewer does not
  keep reactions across reloads; a plain export prints the `--target artifact` line to use for an
  artifact. The feedback digest after the build asks for a ship decision, not "lock and build".
- **Capture.** `demo record` logs navigated URLs with query values, fragments and credentials redacted
  (a studio board link carried its key into events.json) and logs typing into a password field as dots.
- **Docs.** Word-timed reveals on DOM pages from `voice cues`, `retime` does not rescale
  `animation-delay`, demo actions glide before they press, still-hold rules on text scenes and dark
  frames, the dom template's four scenes in the launch workflow, a one-country map recipe, multi-part
  packs and the decisions note on a studio board, browser-frame fonts on pages without a theme.
- **qa and the job ledger.** qa checks only a video's own caption sidecars inside a job; the job's
  captions count only for its latest final with the same aspect, and `--captions` replaces auto-found
  files (a 9:16 cut was judged by the 16:9 captions). Every too-fast cue and over-long line is listed in
  one run. qa keeps a verdict per file, so checking an export no longer makes the final look unchecked.
  For size-capped platforms (github, chat, web) the master's size is a note when a capped export exists,
  with the command that checks the export. A render, edit render, `captions --burn` or poster bake in a
  job becomes the latest final only when it is an `.mp4` named `final*` (or a copy derived from the
  current final); alpha overlays, bumpers and second aspects are recorded as variants, with the command
  that promotes one (`job note --auto`). `captions --burn` into a job updates the latest final and says
  so. `job discard` keeps caption files and lists what moved.
- **review-pack.** `--lufs` (and it reuses the last qa `--lufs`/`--platform` of the file); overlay clips
  are no longer scenes (film acts and showtime.json chapters come first); every `CUE` key is read, even
  several on one line.
- **Captions and footage.** The per-line character limit applies to each line (45-character French
  lines); the boxed style draws one continuous plate per caption (darker bars between karaoke runs);
  `captions --size-scale`. `footage denoise` keeps channels and exact length and reports what the
  strength did; `footage grade --compare` refuses a video file name; `footage probe` reports `yuva420p`
  for VP9 alpha. `brand init --from <repo>` adopts the repo's own brand.json and skips examples and
  fixtures; `brand show` checks fonts live. `showtime clean` frees Manim build caches and drafts.
- **Docs.** Dark themes and slow pushes in qa, comparing a stabilised clip, podcast speakers from a
  published transcript, `transcribe --from/--to` for long episodes.
- **From the re-render of examples 01-07 on Linux.** `demo record --platform mac|windows|linux` (or
  the script's `options.platform`) sets the user agent, `navigator.platform` and `userAgentData`, so an
  app that picks "⌘K" or "Ctrl K" from the OS records the same on any machine. autozoom: an explicit
  focus (`demo.focus`, a `--hints` focus) sets its shot; clicks and typing inside its span no longer
  shrink it to the editor's fit zoom; a take written as `autozoom-2.mp4` says so again at the end.
  `export html --audio-file <wav|mp4>` embeds exactly that sound (a shipped video's soundtrack when the
  voice WAVs are gone) instead of the score and the mix. `check` notes `poster_not_baked` when the
  showtime.json poster will not be baked into frame 0. Docs: Supertonic re-synthesis moves line
  timings, the app's own clock during slow takes, `review-pack <file> --project`.
- **HTML export speaks the page's language.** `export html --lang` (default: showtime.json `lang`, the
  page's `<html lang>`, the narration's `lang:`, else en) sets `<html lang>` and the player's own words
  (Play, Replay, chapters, Sound on, Starts at, the key help, messages) in English, Spanish, French,
  Portuguese and German, from one table in the player; other languages get English controls. A Spanish
  export showed "Play" and "9 chapters · Sound on".
- **review-pack text crops hold whole lines.** Bold or tightly set words merged into one blob and were
  thrown away, so crops showed fragments ("l is a f"); word-shaped blobs now count, and each line is
  grown sideways over the rest of its ink (specks such as snow or dust do not extend it).
- **Manim.** The scene cache covers helper classes (a changed layout class shipped the old layout from
  cache); `key_map` matches declared keys with spaces; inside a line that says the word, `at("half")`
  is the word, not a line named "half", and `manim check` warns `cue_ambiguous`; check's still-hold
  rule is qa's (2.5 s warn, 6 s error, subtle plays do not count, holds join across scenes) and takes
  `--aspect`; `refine(start=, tag=)`; `-o <job>/final.mp4` writes `poster.jpg`; ManimGL renders report
  their length; pattern templates get a narration.md and the job's title. Docs: VGroup re-parenting,
  `remove(VGroup)`, a wide diagram turned for 9:16.
- **Audio.** `audio compose` warns when the tempo bends over 3 % or a section gets a 2-beat bar and
  suggests a bpm (or snapped markers) that fits, and notes a marker merged into the ending hit.
  Masking warnings skip designed layers (same file stem, id prefix or synth type; a riser whose hit is
  its end) and group per family; tracks take `layer` / `texture`. A `typewriter` mix track clicks on
  the page typewriter's own timeline. The mix report records the SoundFont used; a copied library file
  keeps its license (matched by size and sha256, or a sidecar) and a music file with none warns;
  ambience search includes sfx loops; `audio fit` says which bar it ends on and `--ending song` splices
  in the track's own ending.
- **Voice.** `voice ipa` applies the lexicon to the phrase line and finds the project's lexicon;
  grouped numbers and decimal commas read correctly in es/fr/pt/it/de ("60 000", "13,7"); the ʻokina is
  silent; `--fit` says every line re-synthesizes. Docs: a bare year after "the", af_nicole's pace.
- **Deliver.** A master already under a size cap is encoded for quality within the cap's bitrate
  instead of being inflated toward it (2.5 MB became 11.9 MB); a bare `--max-mb N` caps only
  original/github/chat/web and loops (every target when none is listed) and `target:N` caps one;
  exports follow the job's loudness target (`--lufs`); x and linkedin keep a 1:1 or 4:5 master's
  aspect.
- **Render.** `--alpha animation`: QuickTime Animation `.mov` (lossless RGBA, several times smaller
  than ProRes for flat graphics; ProRes stingers were 27-32 MB). A final above 25 Mb/s at 1080p gets
  a hint (animated grain). Docs: crf 18 for masters kept in a repository.
- **Assets.** `assets cutout --max-size` (default 2048); Commons fetches use a standard thumbnail width
  (3840 default, `--max-size`, `--quality orig`) recorded in the sidecar, with a Retry-After-aware
  backoff on HTTP 429; `assets media fetch <url> --license ... --source-page ...` for any file; an
  author-check note on Commons fetches; `credits --all` says which lines to add by hand.
- **Data, retime, export, MCP.** `data import --where` and `--names COL=Label`, and it writes the data
  when the scene has no chart yet; `retime` leaves overlays alone (not a `section.scene`,
  `data-overlay` or open-ended), writes a scene edge that falls within 1 ms after a frame at that
  frame, and says it does not rescale
  `animation-delay`; `export html --job J -o name.html`; MCP `render` takes `page` and `alpha`,
  `export_html` the embed options, `deliver_exports` caps and `lufs` with an accurate file list.


### Added: large example media ship as release assets

Example renders made the repository heavy (about 490 MB of the 680 MB under `examples/`). Any file over
10 MB and every `.mov` (ProRes masters) under `examples/` is now a GitHub release asset: listed in
`examples/MEDIA.json` (path, bytes, sha256, a unique flat asset name, the reason) and excluded from git by
a managed block at the end of `.gitignore`. `scripts/publish_media.py` verifies the manifest against the
files (also run by `check_release.py`: an unlisted or un-ignored large file is an error, a re-render that
changed a size is a warning), `--refresh` rewrites the manifest and the block, `--links` prints markdown
links for a README (`https://github.com/<repo>/releases/download/<tag>/<asset>`), and `--upload` stages
the files under their asset names and runs `gh release upload <tag> ... --clobber` (`--dry-run` prints
it). Nothing under `examples/` was moved or deleted. At the time of writing: 30 files (497.5 MB) are
release assets, 960 files (192.8 MB) stay in git. `tests/run_all.py` no longer reports the repository's
own top-level folders (`benchmarks/`, `examples/` ...) as files a test wrote into the repository.

### Fixed: ManimGL on a Linux server without a display

Importing ManimGL opens a display (pyglet), so on a server with no `DISPLAY` setup reported "does not
import" and renders failed. showtime now runs ManimGL under `xvfb-run` by itself when there is no
display (setup's check, `showtime manim render`); when Xvfb is missing, setup, doctor and the render say
so with the install line per distribution. Setup summaries also drop Python's `^^^^` traceback markers,
which were all a failed import showed. Found on the first Linux run.

### Fixed: two tests that assumed the author's machine

`test_export` packed an emoji that only a machine that had fetched it before has: it now installs it
the way the export's own warning tells a user to (skipped when offline). Its player-vs-snap frame check
asks the stage for a video frame before the screenshot, because headless Chrome on Linux can keep
compositing a paused video's previous frame after a seek.

### Fixed: alpha renders keep their colours in an editor

`render --alpha prores` and `--alpha webm` converted the captured RGB frames with FFmpeg's default BT.601
matrix but tagged the ProRes file BT.709, so Premiere or Resolve, decoding as tagged, shifted every colour
(a brand red `#B3121F` came back as `#C1221D`, gold `#E9B949` as `#EEB744`). Every render output (H.264,
ProRes 4444, VP9) is now converted with the BT.709 matrix and carries full BT.709 tags, the WebM included;
the `alpha_prores`/`alpha_webm` encode presets and Manim's ProRes path do the same. Found by the critic on
example 20's lower thirds; `test_render.py` checks the decoded colour of a ProRes render.

### Fixed: words and math on one line share a baseline, size and weight (Manim), and critics look at type full size

Example 22's opening title "Why πr²?" set the math 34 % of the cap height below the words, a size
smaller and much lighter; a boxes-based `arrange(aligned_edge=DOWN)` did it (the "y" descender), and
the critic and every check missed it because contact sheets shrink it away.
- `st_manim`: `mixed_line("Why", tex(r"\pi r^2"), "?")` puts words and math on one baseline measured
  on the glyphs, scales the math to the text's x-height and sets it in `\boldsymbol` (plus a thin
  outline beside 800-900 weights); `align_baseline(a, b)`, `baseline()`, `x_height()`; `counter()`
  keeps its baseline while it counts; `eq(bold=True)`.
- `showtime manim check` measures words-plus-math and words-plus-number lines on screen:
  `baseline_mismatch` (> 4 % of the cap height), `xheight_mismatch` (> 12 %), `mixed_type` (placed
  by hand).
- `showtime review-pack` cuts the largest text lines out of full-size frames (`frames/text-*.png`);
  CRITIC.md, `references/review.md` and the critic brief add a type detail pass.
- Example 22 and the `example` Manim template rebuilt with the helpers.

### Fixed: HTML exports keep their styles and fonts under a host's strict CSP

Published as a claude.ai artifact, a DOM export (the data template, `examples/12-energy-report`) showed
its charts but every piece of text tiny and in a fallback serif. The viewer's Content-Security-Policy
allows inline styles but not `blob:` stylesheets, and the stage document linked every stylesheet (the
theme, `components.css`) and every font as a `blob:` URL: the theme's tokens, `container-type` and
sizes were gone, so text fell back to 16 px serif in a 1920x1080 frame. Canvas films lost their fonts
the same way (sizes held, the typeface did not). Now the stage writes every packed stylesheet as
inline `<style>` text (imports inlined, also for links created by script) and turns every packed
`@font-face` (and `new FontFace(url)`) into a FontFace built from the font's bytes, which no
`font-src` rule applies to. Fonts or stylesheets that still fail are reported in the console and in
`showtimePlayer.warnings`, and on screen with `#st-debug`. `test_export` opens a data-template export
in a sandboxed frame on another origin under an inline-styles-only, no-fonts CSP at phone size. The
example HTML files (`_html/`, `11-tutorial-series-tidepool/episode-0*/final.html`,
`12-energy-report/us-power-mix.html`) were re-exported.

### Added: README loops, PDF import, partial transcription; MCP server moved into the manifest

- **Image loops for READMEs and docs.** `showtime deliver exports <video> --targets webp,gif` makes a
  silent, forever-looping animated WebP and a GIF fallback (960 px, 15 fps, under 5 MB);
  `webp-small`/`gif-small` make showcase loops (480 px, 12 fps, under 1.5 MB). `--from/--to` pick the
  window, `--width/--fps` override the defaults, and a loop over its cap (`--max-mb` or the target's) is
  encoded again smaller (WebP quality, then frame rate, then width) until it fits. GIFs are two-pass
  (palettegen `stats_mode=diff`, Bayer dithering, `diff_mode=rectangle`) at rates GIF delays can keep
  exactly. Files: `exports/<stem>.loop.webp`, `.loop.gif`, `.loop-small.*`. Why: the README hero and
  showcase loops were being made by hand with bare ffmpeg (`references/platforms.md`).
- **PDF import.** `showtime doc extract <file.pdf> [-o dir]` writes `text.md` (one section per page),
  `images/` (embedded images; JPEGs copied byte for byte, repeats kept once), `figures.md` (captions tied
  to their image or marked vector, plus the credit lines the PDF prints, with a note that a credit line is
  not a license), `pages/` renders and `doc.json`. Default folder: `<job>/sources/<name>/`. New core
  dependency `pypdfium2==5.13.0` (PDFium; Apache-2.0/BSD-3-Clause; wheels for macOS arm64/x86_64 13+,
  Windows x64/arm64, Linux x86_64/aarch64 glibc and musl). Run `showtime setup` once to add it to an
  existing install; `showtime doctor` checks it.
- **Transcribe part of a long file.** `showtime transcribe <media> --from 12:30 --to 18:00` (seconds or
  mm:ss) runs ASR on that stretch only. Word times stay on the file's clock, the transcript records
  `"range"` and `duration` = the range's end (so cut plans drop everything outside it), it is written as
  `<name>.<from>-<to>.json`, and the cache is keyed by the range. `pack` marks it "(part)".
- **MCP server declared in `.claude-plugin/plugin.json`** (`mcpServers`, same command, `${CLAUDE_PLUGIN_ROOT}`
  and `${user_config.*}` substitution). The repo-root `.mcp.json` is gone: Claude Code also read it as a
  *project* server for anyone who opened the repository itself, where `${CLAUDE_PLUGIN_ROOT}` does not
  resolve, so contributors were offered a server that timed out. Plugin users see no change.
- **Studio board chrome** (top bar, favicon, the "preparing the first round" state) uses the Curtain
  Call mark, wordmark and colours (Stage bar with gold accents in dark mode, House cream in light).
  The content area keeps its neutral palette, so concepts in a user's brand are judged on neutral ground.

### Changed: canvas-film QA sees callouts, dims and captions (tutorial review)

A frame-by-frame review of the tutorial series (example 11) found callout cards covering note titles, a card
off the frame, the step band letting the zoomed app show through, and backdrop slivers in zoomed shots, and
`showtime check` had reported none of it: its canvas findings were ~450 contrast warnings per episode,
mostly text under deliberate dims.
- `Film.frameInfo()` now records `covers` (callout cards with their anchor, captions, the step band,
  spotlight dims, `F.box({dims: true})` scrims) and each text's draw order.
- `showtime check`: a callout card over text drawn before it is `text_overlap` ("hidden under the callout");
  a card pointing off the frame or cut by its edge is the new `callout_off_target`; text under a dim is not
  judged for contrast (one `dimmed_text` note); text on a caption plate counts as spoken captions (no
  `short_text`); text hidden under the band or a caption is skipped. Checked in the dense pass too.
- `F.stepBand` is opaque by default and picks white or the ground for its badge number, whichever reads
  better on the accent (white on a light accent failed contrast).
- Player start screen: the poster's brightness under the title block is sampled, so a light poster under a
  dark scrim gets the deep scrim, now sized to the title block (the kicker was unreadable).
- `showtime snap`: long `--every` sheets from 1080p masters shrink each frame before laying out the sheet (a
  93-frame sheet crashed the lab page); any CLI command now exits after reporting an error instead of
  hanging on a crashed browser.
- Example 11 re-rendered: callouts moved into empty or dimmed space, spotlit tour stops, a camera clamp that
  keeps zoomed shots on the app, the recap cleared before the outro, a readable intro subtitle, longer
  keycap holds, poster frames that show the result.

### Added: Manim module for math and diagram explainers

Exact math animation (equations, proofs, graphs, grid transforms) was the one kind of explainer the
HTML and canvas projects could not do well, so Manim is now a first-class project type.

- `showtime manim new|render|check|cues` (`lib/st/cli_manim.py`, orchestration in `lib/st/manim_run/`).
  Renders use Manim Community (the `manim` extra, pinned `>=0.21,<0.22`) with PyAV encoding; drafts are
  480p15 with a contact sheet of each scene's last frame, finals 1080p30 with `poster.jpg`. The frame is
  set explicitly for 9:16, 1:1 and 4:5 (the short side is always 8 units; Manim's default squeezes
  vertical renders to about 40 %). Each scene is cached by a hash of its own code, the cues it uses,
  the theme and the size. `--alpha` gives VP9-alpha WebM or ProRes 4444.
- `st_manim`, an original helper library for scene files: brand theme from `brand.json` (colours,
  a semantic hue set that stays text-safe and distinct from the emphasis colour, fonts registered
  from files), `eq()` that splits equations into parts and colours each concept the same everywhere,
  `morph()` (terms crossing the equals sign travel on an arc), narration beats (`beat`, `at`, `fit`,
  frame-snapped `hold`, `mark("poster")`), layout regions for every aspect, glow, highlight box,
  background-coloured backstroke, a LaTeX-free count-up, and four patterns (equation walkthrough,
  plane transform, graph build with a faint preview, approximation refinement).
- Narration sync: cues come from `voice/timeline.json` (or are estimated from `narration.md` until the
  voice exists); every play and wait is snapped to whole frames so cues land exactly and scenes sit
  on the voice's clock. The voice is muxed as is, or placed line by line through `showtime audio mix`
  when scenes drift or a music/effects mix is given.
- `showtime manim check`: cue words the narration never says, late reveals, holds over 4 s with nothing
  moving, on-screen word budgets, one concept in two colours, safe area, and LaTeX availability with
  the exact install line per OS.
- `templates/manim/`: a narrated two-scene example ("odd numbers build squares", check-clean) and five
  pattern starters. Guide: `references/manim.md`.
- Optional `manimgl` extra: ManimGL 1.7.2 (the released OpenGL build) in its own venv, used for scene
  files that import `manimlib`. The kit and checks are Manim Community only.
- `showtime doctor` rows for manim, LaTeX (packages and per-OS FIX lines) and manimgl; setup smoke-tests
  the manim install and prints the cairo/pango build line per OS when it fails.

### Added: plugin executables, settings, MCP server and progress monitor
- **Running the CLI from the skill.** SKILL.md now runs `"${CLAUDE_SKILL_DIR}/bin/showtime" <cmd>`
  (Claude Code substitutes the skill's folder), so the command works from any working directory with
  no PATH setup. The plugin deliberately has no top-level `bin/`: claude.ai and Cowork (including
  organization sync) refuse to install plugins that have one.
- **Plugin settings** (`userConfig`, all optional with defaults): default narration voice and language,
  open studio boards in the browser, a CPU limit (`max_workers`) and the install folder. Claude Code
  passes them to the MCP server, which saves them to `~/.showtime/plugin-settings.json`; the launcher
  turns that file into `SHOWTIME_VOICE`, `SHOWTIME_LANG`, `SHOWTIME_OPEN_BROWSER`,
  `SHOWTIME_MAX_WORKERS`/`SHOWTIME_THREADS` defaults (environment and flags still win). The voice
  resolver, render worker choice and `studio open` honour them; `showtime version --json` shows what is
  in effect.
- **MCP server** (`skills/showtime/mcp/server.mjs`, registered in `.claude-plugin/plugin.json`): 18 tools that wrap the
  CLI with validated paths, no shell, progress notifications, cancellation, trimmed output and a saved
  full log. It speaks both the 2026-07-28 per-request protocol and the older `initialize` handshake,
  and returns the summary as text (Claude Code shows `structuredContent` to the model in place of the
  text, so machine facts go in `_meta`). Config for Claude Desktop, Cursor and Codex in
  `references/mcp.md`.
- **Progress monitor** (`monitors/monitors.json`): long commands append milestones to
  `~/.showtime/logs/progress.jsonl` (`SHOWTIME_PROGRESS_LOG=0` turns it off); the monitor reports
  jobs still running after 45 s, each further 25% and the end, and stays quiet about short ones.
- Tests: `tests/test_mcp.py` (both protocol eras, validation, doctor -> new -> render preview -> qa over
  stdio, settings reaching the CLI, manifest wiring, monitor).

### Changed: fixes from the eleven example videos (friction log)
Each item was hit while making `examples/`; the fix is in code (with a test) unless marked docs.
- **Render.** A poster is baked into frame 0 only when it looks like the opening (`--poster-bake
  auto|force|off`): a mid-video poster over an opening that builds from empty used to flash for one
  frame on autoplay and every loop; qa now WARNs `poster_flash`. Encode defaults can live in
  showtime.json `"render"` (crf, preset, format, poster ...), and a final more than twice the size of the
  previous one warns. "final.mp4 exists; writing final-2.mp4" is an info line, not a warning. The
  offline score page is no longer closed while it renders (it shipped silent finals on busy machines);
  a failed soundtrack is retried and then fails the render unless `--allow-silent`. The voice-over-score
  gap is measured (`audio.voice_over_score_db`). Studio renders keep their scratch in `<job>/work/renders/`.
  ETAs are measured from the first unit of work.
- **Sizes are decimal MB everywhere** (render, qa, exports, html export), like upload limits.
- **Exports.** `deliver exports --max-mb N` (two-pass, lands under the cap) and targets `original`,
  `github`, `chat`, `web` at the master's size; padded exports record their picture so qa judges black
  and frozen stretches inside it; exports carry the edit report (upscale lineage). `--pad-color` defaults
  to the project's background.
- **snap** takes a rendered video (`showtime snap final.mp4 --at 4.2`), snaps to the nearest frame, keeps
  the requested time in file names and says when two times share a frame; `--compare other.mp4` writes a
  before|after sheet.
- **review-pack.** Rounds count critic answers (FINDINGS.md), so a newer final or an interrupted pack
  rebuilds the same round; `cuts.jpg` shows every frame around each cut; other deliverables in the job
  and missing context are named in CRITIC.md; the video's own .srt ships in the pack; labels draw accented
  letters. review.md: what to do with no sub-agent tool, and how to verify polish after a "ship" verdict.
- **check** uses qa's still-hold rule (`freeze_noise_db` in thresholds.json), measures overlaps on glyph
  ink, names the edge in `safe_zone`, adds `edge_margin` and `control_strip` for landscape, reads SVG
  `fill`, treats contrast measured mid-entrance as a note, names fallback glyphs, surfaces component
  warnings, and raises its render estimate for `<video>` layers and busy machines.
- **Captions.** An .srt/.vtt input keeps its cues and line breaks (ASS and sidecars agree; `--regroup`);
  cues shorter than 0.7 s (0.4 s karaoke) merge instead of flashing; short sentence tails join the cue
  before; cues snap to EDL cuts; line breaks avoid function words and split names; `--max-words` reaches
  the sidecars; a bigger `size` lowers `chars`; qa WARNs `caption_flash` and prints the shortest cue; only
  a sidecar in the job folder re-points the job's captions; a variant's own .srt wins in qa.
  `edit render --captions <style>` starts from that style's defaults; `--caption-position`.
- **caption-karaoke**: `keep` phrases, `skipLines`, short cards merge (`minShow`).
- **Voice.** Sidecars store portable paths (relative, `showtime:` / `showtime-home:` prefixes); `--fit`
  lands exactly on the target and warns above x1.1; `voice cues` writes a `VO` table for canvas cue tables.
- **Audio.** `gain_points` and `section_gain` automation; a `keystrokes` track clicks in sync with a demo
  recording; `audio fit --from`; a fitted track with `offset` uses a shifted beat grid (it was off by the
  offset); the mix report lists `end_hit`/sections/downbeats, per-sfx `above_bed_db`, warns on a quiet
  first section and masked effects, and uses relative paths. `m.fade` ramps from the automated level;
  `m.ramp`, `m.duckUnder`. `showtime score` writes into the job, never a `showtime-out/` inside the
  project, and reports the voice-over-bed gap for narrated projects.
- **Components.** chart: negative values and a zero line, file options honoured (decimals ...), tick
  decimals, `+`/`−` signs, hard ranks for ties, `count`, `highlightAt`, `ref`, `dots`, `--chart-muted` on
  `:root`; count-up reserves the widest counting value and lifts "°C"; ken-burns fades only mid-scene,
  CSS object-fit, `mask`; browser-frame scrolls measured after decode, keeps children over a screenshot,
  `camera: frame`; kinetic-type `style: none`; ripple strength `a`; `peak` alignment for flash/glitch;
  film transitions take `blur`; `F.relocate`. Clip edges within 1 ms of a frame land on it.
- **Capture and demo.** `demo.type(text, opts)` types into the focused field (and logs its box); frames
  are really captured at `--dpr`; `demo.wide()`; autozoom: no bridging across chapters, `--hints`,
  `--cursor-offset`, `--keys-pos`, `--key-glyphs`, `<name>.keys.json`, corner room, shot list in the
  output. site capture keeps an app's own dialogs, lists hidden overlays with sizes, skips in-app quotes
  as testimonials and white/black buttons as the primary colour. NASA media: third-party notices in the
  description change the licence (JunoCam processing, ESA/Hubble), results show full ids, size, length
  and file size (`--min-size`, `--max-duration`, `--max-mb`), and each quality is cached separately.
- **Footage.** Transcripts default to the job (a new `<name>-edit` job when there is none), never next to
  the user's footage; `footage trim` (excerpts and seek-friendly proxies, `--webm`); `footage scenes
  --every` takes `--from/--to` and a file `-o`; `edit check` reports near-contiguous ranges; upscale
  messages say when 1080x1920 from 1080p is unavoidable, and `output.allow_upscale` accepts it; the face
  tracker seeds on the median of the first second with a zoom-scaled dead zone.
- **Jobs.** `showtime job discard` moves an unused render out of the job; a hand-set `next` is dropped by
  the next stage or render; a delivered job says "nothing required"; job names resolve from inside a job;
  studio approvals are read from feedback.json (they stayed "not approved" after later board revisions).
- **Templates.** `showtime new` no longer copies the template's README.md into the project; JSON files are
  written with normal permissions (not 0600).
- **Studio.** `studio decide` appends the next D-nnn; `studio frame --storyboard` fills storyboard thumbs;
  the board opens on the picked concept (or one with an animatic); `feedback --new` lists only what is new,
  and removed questions keep their names from earlier board revisions; `preview` no longer reports a slow
  start (building the mix) as a failure.
- **Release.** `check_release.py` fails on committed videos over 20 MB and on published `*.work/` folders;
  `.gitignore` ignores every `work/` folder.

### Added: the crew (specialist sub-agents)
- Ten plugin sub-agents in `agents/` (`showtime:creative-director`, `brand-designer`, `scriptwriter`,
  `storyboard-artist`, `motion-designer`, `sound-designer`, `voice-director`, `editor`, `researcher`,
  `critic`). Each is thin: frontmatter with an explicit tool list (never the Agent tool, so members
  cannot dispatch others), model and effort per role (judgment roles inherit the session model,
  production roles use sonnet), the non-negotiable rules inline, a pointer to its brief, and a return
  contract (`DONE`, `DONE_WITH_NOTES`, `NEEDS_INPUT`, `BLOCKED`). Why: studio and publish-bound jobs
  have independent pieces (concepts, brand, script, scenes, sound, voice, fact check, critique) that
  run better in parallel with fresh contexts, while the main session stays the only voice to the user.
- Host-neutral role briefs in `skills/showtime/references/crew/` plus `crew/rules.md` (shared hard rules,
  reading order, return contract), so the linked dev install and other agent hosts use the same text
  through a generic sub-agent, or the director follows the brief inline.
- `references/crew.md`: the director's playbook (when to dispatch whom per mode, the `TASK.md`
  skeleton, parallel patterns for the pitch round, build and fix loop, merging scene fragments with
  `data-start="#prev-scene"`, a CPU budget for heavy commands, token cost). Quick mode stays inline
  except long-video scene builders and, when publish-bound, the researcher and critic.
- SKILL.md: a short Crew section with the phase table (studio bullet and two studio red flags tightened
  to stay within the word budget); `modes.md` section 4, `review.md` section 3 and `studio.md` link the
  roles.
- `scripts/check_release.py` gains an `agents` check (frontmatter, name = file name, description at most
  300 characters starting "showtime crew.", no Agent tool, known model/effort/color values, no fields
  plugin agents ignore, every `${CLAUDE_PLUGIN_ROOT}` path exists, brief and rules pointers, return
  contract, one agent per brief) and scans agent bodies for unknown `showtime` commands;
  `tests/test_skill_structure.py` runs it and proves each rule fails on a bad sample.

### Added (from end-to-end trial runs of the skill)
- `showtime export html <project>`: a project as one self-contained interactive HTML video (player with poster,
  chapters, keyboard, fullscreen; live `ST.score` or an embedded AAC/Opus soundtrack; `--folder` for hosting;
  `--max-mb` budget, 16 MB by default). Frames match the render. Why: videos are shared as web pages and
  artifacts too, not only as MP4 (`references/html-export.md`, demos in `examples/_html/`).
- `showtime voice script --fit SECONDS`: lands a whole narration on a length (shared speed change within
  0.85-1.15x, then shorter pauses, then "cut about N words"); a short script is padded with silence.
  Why: a 15 s vertical explainer came out at 16.55 s and only hand-cutting words fixed it.
- `showtime retime <project> --from-voice voice/timeline.json` (`--map`, `--pad`, `--keep-captions`):
  scene lengths from the narration, one voice track per line, ducking, and music sections, effects,
  poster and caption words moved with their scenes. Why: those values were being copied from the
  slots by hand, scene by scene.
- `showtime data inspect|import`: a CSV/TSV/JSON table becomes chart data (`--chart bar|hbar|line|race`,
  `--scene` wires it into the page). Why: every data story needed a hand-written conversion.
- `showtime new --job JOB`: records the project in the job (a project folder inside a job is recorded
  without it). `job note --project`, and an `animatic` output kind for renders under `<job>/studio/`.
- `showtime render` writes `<work>/logs/render.log` and prints its path.

### Changed
- `edit render`: a range that continues the same source where the previous range ended (a reframe-only
  split) joins without the 30 ms edge fades, which dipped continuous room tone by 14-18 dB for ~20 ms.
- `showtime check --dead-air` defaults to 2.5 s, the same rule as qa's `frozen`, and both read
  `runtime/thresholds.json`; an end hold up to 4 s is a `final_hold` note. Why: check passed a 4.2 s
  still that qa then flagged, a full render later.
- `check` reports text hidden under a badge, notes layout and contrast seen only mid-transition (and
  judges the settled frame), groups repeated `small_text` notes, and lists `scenes` and `transitions` in
  report.json.
- `new --duration` and `retime` warn when a scene is stretched more than 1.5x; retimed transitions stay
  at 0.35 s or more.
- `showtime captions` and `voice script`'s `vo.srt` group within qa's limits (42/32 characters, 20
  characters/s; one shared module), karaoke styles write one event per group, a sidecar written inside
  a job becomes the job's captions, and the command says when the video already burns captions.
- `deliver poster|exports|thumb` accept a job (its latest final); `poster --bake` records the baked file
  as the latest final, bakes once and never overwrites. `edit check` accepts a job.
- Footage tools (`footage scenes`, `reframe`, `grade`, `denoise`, `stabilize`, `luts --preview`, `view`)
  write into the job's `work/`, never beside the user's footage; reframes and EDL renders warn when a
  source is enlarged more than 1.5x.
- qa: new `resolution` and `upscale` warnings; it checks the job's latest captions; after a WARN the
  job's next command is a fix, not an export. review-pack takes scene frames from the planned scenes
  instead of detecting cuts in the pixels, and CRITIC.md carries the seven judging questions.
- Components: `end-card` shows a logo next to the name, `browser-frame`/`device-frame` drift slowly on
  a still screenshot (`data-drift`), chart labels keep a readable minimum size and callouts clear the
  value labels, count-up prints "+160%". `studio frame --title` creates a missing concept.

## 0.1.0 — first complete build

The first version that makes whole videos end to end on one machine: HTML/canvas motion graphics
rendered frame by frame, narration, music and sound design, footage editing from transcripts,
captions, and platform exports. Everything runs locally; no accounts or API keys.

### Install and health
- `showtime setup` (stdlib-only installer, idempotent and resumable): static ffmpeg/ffprobe per
  platform, a Python 3.12 virtualenv built with uv from pinned requirements (PEP 508 markers for Intel
  macOS pins), pinned Node packages including Playwright, and sha256-checked models. Tiers `minimal`
  (CI), `core` (default) and `full`; optional extras with `--with`; `--list` and `--estimate` show sizes
  and time before anything is downloaded. Re-running with `--with X` keeps the tier and extras already
  installed.
- `showtime doctor`: real checks (a test encode, venv imports, Node packages, a headless browser with
  WebGL, every model file, the espeak-ng self-test) as PASS/WARN/FAIL, each problem with a one-line fix;
  `--json` for scripts; `--report [JOB]` writes a redacted `bug-report.md` locally (never uploaded).
- Entry points `bin/showtime` (POSIX sh), `bin/showtime.cmd` and `bin/showtime.ps1` only find a Python
  and run the stdlib launcher, which resolves the skill from its own location (a copied or
  plugin-installed tree works the same as a checkout).
- Grouped `showtime --help` with examples per group; every command has `--help` with examples.
  Errors print what went wrong, why and the exact fix; tracebacks only with `--debug`. Colour turns
  off automatically when output is not a terminal (or with `NO_COLOR`). Running a command before setup
  prints exactly what to install, with size and time.
- `showtime version [--json]`, `showtime paths`, `showtime new <template> <dir>`.

### Make (HTML/canvas projects)
- Stage runtime with a strict time contract (every frame is a pure function of time) and a virtual-time
  shim, so renders are frame-exact and repeatable.
- `showtime render` (parallel headless Chrome capture, H.264 BT.709 encode, offline audio, loudness to
  -14 LUFS, poster bake), `preview` (browser player with scrubber, frame step and synced audio),
  `check` (pre-render QA: timers, failed requests, contrast, system fonts, overlap, safe zones),
  `snap` (stills and contact sheets), `score` (render only the Web Audio score), `server`.
- Canvas film toolkit and a Web Audio synth/score API; 20 DOM motion components, 12 CSS and 11 WebGL
  scene transitions, 6 themes; `showtime motion` lists them and `showtime code` prepares highlighted
  code. Templates: `dom`, `film`, `short`, `tutorial`, `data`.

### Audio and voice
- `showtime audio`: procedural composer (16 styles, sections on downbeats, stems, MIDI, beat grid),
  56 synthesized sound-effect types, a local library of permissively licensed music/effects/ambience
  with search and automatic credits, beat analysis, fit-to-length, `mix.json` rendering with ducking
  and hit alignment, metering and mastering. The default SoundFont bank is FluidR3Mono (MIT).
- `showtime voice`: Kokoro, Supertonic and Piper voices with word timings (forced alignment),
  script-to-timeline narration with pauses, pronunciations and per-line caching, mastering to -16 LUFS.

### Footage, capture and assets
- `showtime transcribe` (word-level, local Whisper/Parakeet, speakers, audio events), `pack`,
  `edit cut|check|render|view` (edit by transcript, frame-exact), `captions` (five styles, SRT/VTT,
  burn-in), `footage scenes|reframe|denoise|stabilize|view|grade|luts|probe|autozoom`.
- `showtime site capture|component|record` (screenshots, copy, brand colours and fonts, assets,
  consent banners declined), `showtime demo record|init` (scripted app walkthroughs on a virtual
  clock), `showtime autozoom`, `showtime assets font|icon|emoji|media|cutout|credits`.

### Deliver
- `showtime deliver exports` for YouTube, X, LinkedIn, Reels, TikTok, Shorts and square, with blur-pad
  or crop for aspect changes, duration limits and loudness; `deliver poster` (auto-picked, baked into
  frame 0 or attached as cover) and `deliver thumb`.
- Final audio is AAC 256 kb/s, mastered 0.5 dB under the true-peak ceiling, and the encoded peak is
  re-checked (`ff.ensure_true_peak`) and repaired by re-encoding only the audio. Why: ffmpeg's AAC
  encoder at 192 kb/s produced a +3.9 dBTP burst on limited speech whose WAV was clean.

### Project hygiene
- `CONTEXT.md` glossary, `.out-of-scope/` decisions, `CONTRIBUTING.md`, a pull-request template,
  `.gitattributes` fixing line endings per file type, `scripts/check_release.py` and
  `tests/test_skill_structure.py`, CI on macOS arm64/x86_64, Ubuntu and Windows (every pull request:
  structure, unit, a short render and the defect suite; nightly: everything).

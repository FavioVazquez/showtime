# Changelog

All notable changes to showtime. Each entry says what changed and why, so this file also answers
"where did X go?". Versions follow [semantic versioning](https://semver.org); the version lives in
`skills/showtime/lib/st/__init__.py` and `python3 scripts/check_release.py` keeps the plugin manifests, the registry files and
`setup/package.json` in sync with it.

## 0.4.5 (2026-10-14)

- **New: X-ray events from a data stream.** `showtime xray import <events.csv|json> --job <job> --time-map SLOW,T0`
  writes `xray.json` from event times measured in data (peaks of a signal, a sensor log) instead of from the clip's
  sound: film time = (t_data - T0) x SLOW, each event's frame = floor(t * fps), `detector.engine: "data"` with a note
  that says how. A CSV with a time column or a JSON list; `--strength <column>` sizes the events, other columns
  travel with them, events outside the film are listed under `dropped`, and `--source` (the sound the film plays)
  gives the frame rate and length and lets `xray verify` check the film. The live page's commands then start with
  `xray import`. A film made this way used to need a hand-written `xray.json`. Limits: an events file up to 50 MB and
  100,000 events, film times up to 24 h; a file it cannot hold (NaN or infinity, a huge number, deep nesting, an
  over-long CSV cell, a file with a NUL byte (one saved as UTF-16, say)) is refused with the reason, before a job exists. `--strength` with a cell that is not a number
  is refused (a blank cell is strength 0, counted in one warning); `--time-map ",5"` sets T0 alone, and a part given
  twice is refused. The note it writes names the events file, never a folder. A data column named `kind`, `ch`,
  `notes` or `pitches` can no longer break the live page.
- **New: X-ray of a recording with no picture.** `xray analyze` takes a WAV or any recording without
  a video stream instead of refusing it: the events land on a frame grid of `--fps` (default 30), and `xray notes` takes one too, always at 30 fps; xray.json marks the
  source `audio_only`, and the page draws the picture side. `--track` on such a recording is refused with the reason.
  `xray notes --help` says so too (it still called the clip "the video you filmed").
- **Fixed: the X-ray live page states how the events were measured.** It said "from the clip's own sound" for every
  film; it now uses `"xray".measured` from showtime.json, else xray.json's detector (the sound, or a data stream and
  its note).
- **New: `"xray".made.commands` lists the steps that made a film** on its live page, in place of the four standard
  commands, and the export warns when the commands name a mechanism the library does not have (a command that would
  not run) or carry a local path.
- **Fixed: an X-ray project without notes passes `showtime check`.** The page asks for `notes.json` only in case
  `xray notes` wrote one; its absence was a "missing file" error in check and a warning in render.
- **Fixed: `footage trim -o <file>` writes that file.** An existing `-o` file was kept and the trim went to
  `<name>-2` next to it, with only the printed path to say so; now trim refuses with the reason, `--overwrite` (or
  `--force`) replaces the file, and `-o` naming the input clip is refused, whatever its spelling (a different case on
  a case-insensitive disk, a hard link). Without `-o` nothing changes.
- **Fixed: the embed element takes only safe addresses.** `<showtime-xray src="...">` now loads a page only when `src`
  is a relative path, an http(s) address or a `file:` address (a post you open from your disk still loads its film);
  anything else (`javascript:`, `data:`, `vbscript:`) leaves the poster with no frame. The frame is sandboxed so the
  live page can run its own scripts and nothing more (no storage, forms, popups or navigating the page around it).
- **Fixed: the Type field on living diagrams you touch.** A paste or an input method's burst types at most 200
  characters at a time; a focused summary (the Narration line), slider, button or link keeps all of its own keys
  (letters, Space, Enter, Backspace) instead of having them typed on the board, and the Type field itself takes them
  as before; an emoji is one key press, and Backspace on an empty field works on Android keyboards too; the field's
  text is 16 px, so iOS does not zoom the page when you tap it; and an input method (Chinese, Japanese, Korean and
  others) keeps its pending text until you commit it instead of the field being cleared under it.
- **Fixed: the heat pump's discharge tag.** The starting scene said 70 °C on the discharge pipe while its default
  weather (2 °C outside) works out to 63 °C; both tags now show what the scene computes for its default.
- **Changed: the X-ray live page and the gallery say what sharing shares.** A live page carries the prompt it was made
  with and the commands that made it, showtime.json's whole `xray` block (so `xray.made.prompt` too, even when
  `--prompt` shows another), the source recording's file name and sha256 (never a path) and, for a film made from
  data, the events file's name and sha256 with its column names, labels and values; the page, the gallery, the X-ray
  guide and the workflow say so. The export warns if your own commands hold a local path; it does not remove it.
- **Changed: SKILL.md routes by family, at 1,200 words or fewer.** The router was one row per feature (26 rows, the
  body at its 1,500-word cap). It now sends a request to one of six families (something that happened; a product, repo,
  site or paper; an idea or a system; numbers; their own media; a format) and each family names its guides;
  `references/index.md` lists every route by family with its first command, and flags live in the guides and
  `showtime <cmd> --help`. The pipeline, the "Done when" lines, the red flags and the rules are kept.
  A routing eval for contributors (`benchmarks/routing-eval/`, 18 typical requests, each graded on the guide it reads
  and the first command it names) scored the restructured skill 48 of 54 runs, against 46 for the old router; the
  cases were written with the restructure and the skill text was edited after those runs, so the score is measured on
  the cases it was tuned against. The release check caps the body at 1,200 words and wants an eval case for every
  workflow guide except three older ones (slideshow, trailer, voice-over only), so a new feature
  adds a case and a line in its family's guide, not rows to SKILL.md.
- **Fixed: the skill description** covers an interactive figure or living diagram for a web page, not only a video
  (a request for one used to leave the skill unloaded), and gets back its triggers for an animated logo intro, outro
  or sting, removing silences, re-voicing or subtitling a video in another language, and the "not for still-image
  edits or photo-post captions" line; every earlier trigger is kept, reworded to fit 1,024 characters. A logo sting,
  lower third or title routes to `references/components.md` by its path, which now opens with the transparent render
  for an editor (`render --alpha`). A command the host kills at its timeout keeps its one-line pointer in SKILL.md
  (`--background`, then `status <id> --wait 240`).
- **Fixed: recap on Windows with short folder names.** A session recorded in a folder under its 8.3 short name
  (`RUNNER~1`, common on build machines) lost its files from the recap because git reports the long name; recap now
  matches both spellings.
- **Fixed: a screenshot stopped at its time limit says when the browser was stuck.** When a frame never came, the
  check that found the browser silent (or its drawing processes idle) could also be the one that reached the
  screenshot's time limit, and the error then gave only the limit ("still not there after N s, the longest a
  screenshot may take"). It now names the stuck browser ("the browser did not say what it was doing for N s"); the
  wait ends at the same moment. It happened on a slow or busy machine, with a low `SHOWTIME_SHOT_TIMEOUT`, or when
  reading the page's size had used most of a screenshot's time.
- **Fixed: tests and checks.** The detector test now fails when no event is found, the two figure test files are
  balanced across the shards, the embed element is tested in a browser, the X-ray page tests skip where node is missing,
  every test server accepts many parallel connects (Windows refused past 5), `scripts/check_release.py` fails on a
  merge-conflict marker left in a file, and `test_pace` derives the stuck-frame guard's waits from its constants with
  room for a loaded Windows runner's late answers and timers; the cut-frame tests say why `check` skipped the cut
  walk.

## 0.4.4 (2026-10-13)

- **New: X-ray, a film of a real thing with its inside drawn on the frames its own sound says.** Film something doing
  its thing (a typewriter typing, a music box playing, a guitar, a drum kit) and showtime draws the mechanism moving
  on the object as the camera moves (`--layout through`), beside the clip (`split`; on a phone the clip on top) or as
  an isometric living diagram next to it (`diagram`), as a dark radiograph or a light blueprint (`--theme`), 16:9 or
  9:16. `showtime xray analyze <clip> --job <job>` finds every event (a keystroke, a pluck, a hit) in the clip's sound
  with its time and frame, writes `xray.json` and a `check.jpg` (the waveform with a tick per event), and with
  `--track --region ... --ref-time` follows the object (`--mask` leaves out hands). `--engine envelope|flux|auto`
  picks the detector; dense or sustained sound uses the spectral-flux one. `showtime new xray <dir> --mechanism
  <object>` starts from the mechanism library: six drawings of an inside, each made on a real clip and verified, a
  manual typewriter, a disc music box, a snap-action switch, a piano, a guitar and a drum kit (an object the library
  lacks starts as a copy of the closest entry, and anyone can add one). `showtime xray notes <clip> --instrument
  piano|guitar|musicbox|drums` reads the music with local models and writes `notes.json`, `notes.mid` and
  `notes.musicxml`: pitches, key, chords and a smooth tempo map for a scrolling score, a string and fret per note for
  a guitar tab, and every drum hit sorted by sound into kick, snare, hi-hat, toms and cymbals for a drum sheet
  (General MIDI channel 10 and percussion MusicXML). `showtime xray verify <job>` reads the finished film back: a
  small marker in a corner is white only on event frames and the film's sound is matched against the clip's, so the
  receipt says "19 of 19 events on their frame · audio 0.0 ms from the original"; missing or extra events, or audio
  more than 20 ms off, fail `showtime qa`, and `--band` also checks a scrolling score for stalls and jumps. `qa` also
  asks for the clip's credit (`xray.credit` in showtime.json, or `xray.own`), and the receipt and the end card carry
  it. A film made at another frame rate than its clip is converted by `floor(t * film fps) + offset`. The inside is
  a generic mechanism of that kind of object, which the film says on screen, and which key or note a hit was needs
  evidence (the paper, a display, the notes), otherwise the film says "a keystroke". Guide: [X-ray](docs/guides/xray.md)
  and [xray.md](skills/showtime/references/workflows/xray.md). Checked by tests that detect events in generated sound,
  read notes and drum hits, and start a project from the template.
- **New: the X-ray live page, a film you play.** `showtime export html <xray project> --interactive` writes
  `<name>-live.html`, one offline file: the clip with its own sound and the inside drawn on every frame, slow motion,
  light or dark, see-through or beside, labels on hover, the receipt and the credit. It then went further. Pads under
  the picture play the next event of their kind from the real clip with its sound (a typewriter's keys laid out as a
  keyboard, an instrument's notes in pitch order, a kit's drums named as people say them); the keys of your keyboard
  press them, so you type on the typewriter; dragging the picture scrubs and a click plays the next event.
  Links are plain anchors: `#hit4`, `#t2.5`, `_light`, `_split` (`#hit4_light`), and the Link button copies one. The page
  shows the request that made the film in quotes with Copy, then the commands: pass `--prompt "<request>"` to the
  export (or `xray.made.prompt` in showtime.json); the commands use placeholders and never your paths, `showtime new
  xray` records only `xray.made` (mechanism, layout, theme), and the export report says what it embedded. The page embeds
  with `<showtime-xray src="you-live.html" ratio="16/9">` (a poster and a Play button; the one script is `embed.js`) or
  an iframe with `#embed`, and its policy allows framing. The letter shortcuts moved to Shift (Shift+S quarter speed,
  Shift+T theme, Shift+L layout). The live export takes the mechanism for its commands from `xray.made`, else from the
  project's own `mechanism.js`, and warns when it can only guess. Checked by tests that open the exported page in a browser and read what the export embeds.
- **New: living diagrams you touch.** A figure's scene can answer the viewer, not only the knobs: `interactive.type`
  receives every character typed on the figure (from anywhere on the page, or from a Type field on a phone's soft
  keyboard; Enter and Backspace arrive too), `parts[].press` runs when a part is clicked or tapped (or Enter on its
  button) and `parts[].drag` turns a knob while the viewer drags the part (`axis`, and `span` in pixels for the whole
  range). With `type` set, plain letters belong to the scene and the figure's own shortcuts take Shift (Shift+R run
  again, Shift+L copy link, Shift+1-9 steps). Two new examples start from it: `showtime new diagram <dir> --example
  typewriter` (type on it: the key goes down, the typebar swings to the print point, the letter lands on the paper,
  the carriage steps, the bell rings near the margin, Enter returns the carriage) and `--example computer` (what
  happens when you press a key: the keyboard, a USB poll, an interrupt, RAM, the GPU and the screen's refresh, in slow
  motion with typical, labelled numbers; click a part to pulse it). The heat pump template's outdoor unit now drags to
  set the weather. Each still films from its tour, and a figure framed with `#embed` reports its height to the host
  like an X-ray page. `showtime check` walks a typed line and every pressable part. Checked by tests that type on the exported figures in a browser.
- **Fixed: code scanning.** The exported figure's title is cleaned of markup in one linear pass instead of a repeated
  search.
- **The site's X-ray page.** A gallery of ten films (the typewriter four ways, the music box in a phone and a wide cut,
  the switch, the piano, the guitar and the drums), each with its receipt, the clip's credit with a link to the
  clip's file page (a share-alike clip says the film has the same license), and the commands that made it, with a
  copy button. "Play it live" on a card plays the live page in place (one at a time, on a stage beside the card's
  words), "Try it live" on the hero, an Embed snippet per card, and a shelf of three figures you touch (type on the
  typewriter, type on the computer, drag the heat pump's weather). Filters by kind and theme.

## 0.4.3 (2026-10-13)

- **Recap and repro pick their music per video, and generated videos are quieter on the cuts.** Both used to get
  the same bed and the same swoosh, click and error sounds every time. Now the bed is a catalog track picked from the
  session or test, off the music of the last films (downloaded once from its creator's site and cached; nothing is
  sent), or, offline with no cache, a composed style; the click and error sounds come from the subtle synth families.
  A rerun of the same job keeps its bed, and `--music <style|catalog-id|none>` pins it. A catalog track's credit,
  share text and Content ID note are printed and returned in `--json`, and repro puts the credit into `repro.md`; if
  the download fails, a composed bed takes its place unless the track was pinned. Recap, repro, `release-video` and
  `pr-video` no longer put a sound on every cut (`--cut-sounds` adds a soft swoosh, 18 dB under the bed); repro
  keeps its click on a click and its failure tone. The bed under narration ducks 10 dB (was 12). The transition
  sounds are softer everywhere: whoosh, swoosh-in and swoosh-out rise over 100-200 ms or more and are low-passed near
  3 kHz (swoosh-in 0.6 s, swoosh-out 0.7 s by default), and synth hits are cached under a synth version, so a
  machine that rendered before gets the new sounds. Test: `test_bed.py`.
- **Every render worker captures from a page set up like the first one.** Under load, a worker whose page opened
  while one of its modules got no reply could render bare frames: in one nightly render, two of three workers drew
  none of the looks. A page's setup (each component ready or not, each look on WebGL or its fallback, its failed
  requests) is now compared with the first page's once it is ready; a page that differs is opened again, and when
  the first page was the broken one the render stops with an error instead of shipping its frames. The soundtrack
  page fails the same way when it misses the score, so a dropped module no longer ships a silent video. Failed
  requests are listed in the render log. Test: `test_looks.py` (`test_07b_a_page_that_opened_short_is_opened_again`).
- **New: `showtime recap` turns a Claude Code session into a 30-60 s narrated film of what the agent did.** It reads
  one transcript (`--latest`, a `.jsonl` path or a session id; a sub-agent's own transcript works too, and a session's
  recap covers that transcript only, not its sub-agents) and shows a title made from the facts ("42 min · 6 files
  edited · red to green"), the numbers (active time, turns, tool calls, files), a living timeline of the files read
  and edited and the commands and tests run, where the edits landed, the tests red to green, the diff and the outcome.
  For pull request descriptions, standups and "what my agent did overnight" posts. Transcripts hold everything
  (memory, keys printed by mistake, private paths, other projects), so the film is built from an allow-list of facts:
  repository-relative paths of files inside the repository, program names from a fixed list with the program's own
  subcommand (anything else counts as "other"; never a script or module path), test counts, commits whose printed hash
  is in the repository's history and their git diff stats, and timestamps. Free text (the request, a sub-agent's
  description) is only offered in `script.md` as a commented suggestion, never kept in `facts.json` or the project;
  editing `script.md` is the only way to change what is on screen, and any line the user writes there goes through the
  same strict rule. A hard filter then drops any line that still looks like a key, an absolute path, a URL, a host or
  an e-mail address, or that holds an invisible format character (every line is judged NFKC-folded). Filters can miss
  things, so a call that writes `script.md` (every line that will be shown or spoken) stops there, `--yes` included,
  and the film is rendered only by a later call, from `script.md` as the user left it: narrated with `showtime voice`
  and captioned, in a light paper look (`--no-voice`, `--aspect 9:16`, `--preview`). Its files go to
  `showtime-out/recap-<session>` unless `--out` is given; that default is refused where git would track it. Guide:
  `references/workflows/recap.md`.
- **Living diagrams: `showtime new diagram` and the `/_st/diagram.js` runtime.** A system explained over time as an
  isometric figure: parts arrive in the order that explains them, pipes and links join them by port name, flows,
  packets, state changes and pulses move through them, labels land when their part matters, and the camera and a
  focus veil choose what to look at. One engine, two themes: light (paper, the default) and dark (night schematic),
  picked with `--theme` (the page's `data-theme`, `"theme"` and `"background"` in showtime.json). A parts library
  covers machines (plate, wall cutaway, unit, compressor, tank, valve, cassette) and abstract systems (`node` with
  person, school, bank, firm, server, terminal, hub, core, gate, files, lamp and tool icons; `stack`, `store`,
  `queue`). Depth comes from a sort on the parts' boxes plus a port rule (a pipe on a back face is behind its
  part), labels from a layout pass that scores candidate places at every camera pose and reports a collision where
  the label lands, and any text that never shows fully inside the text safe zone, as `diagram:` warnings in
  `showtime check`. Text is check-friendly by construction: persistent nodes, fades of at most 0.2 s, floor text
  raised to the readable minimum, and text that fades out before the camera carries it off the frame. Beat times
  live in a `CUE` table, so `--duration` and `showtime retime` move them; narrated films land beats on `VO` words.
  The template starts as a heat pump; `--example market` (a matching market) and `--example enter` (a coding
  agent's loop) start from the other scenes at their own length. The poster is a still at the end, never baked into
  frame 0 (`"render": {"poster_bake": "off"}`). Guide: `references/workflows/diagram.md` (`showtime guide
  diagram`). Test: `test_diagram.py`.
- **New: a living diagram is also a live figure people poke: `showtime export html <project> --interactive`.** The
  same scene, as one offline file (`<slug>-figure.html`, `--target artifact` for an HTML artifact): no play button
  and no timeline. The board is built and moving from the first frame; hovering or tabbing to a part lights it and
  its own pipes and links (the film's focus veil) and a card says what it is and its value; each step is an
  experiment that runs on the board; knobs (a rule's strength, a promise's horizon) run the step again and the
  levels, stacks and tags answer at once, with the numbers under the figure. Untouched, an idle tour of the same
  live actions plays and stops at any touch. Keys, deep links to a state (`#step=cost&rule=3&part=infl`), reduced
  motion (still; input works), a pause when hidden or off screen, a phone layout (words leave the drawing for the
  panel), the scene's title in the page and its link preview. A scene declares what is live in `SCENE.interactive`
  (steps, knobs, readouts, parts, a tour); the engine underneath is `Diagram.live` (`set`, `fire`, `focus`, `tone`,
  `show`, `hit`), keys written at the moment the viewer acts, so every frame is still a pure function of the clock,
  and films draw as before (apart from the two fixes below). A live-first scene films its own tour
  (`interactive.film = 'tour'`). New theme `--theme white` (white ground, neutral greys, colour only where it means
  something). `showtime check` walks `figure.html` at rest: every step x each knob value (every option; a range in
  full up to 25 values, else 9 across it) x each hovered part, and the scene's keys, and reports cut or overlapping
  text, broken readouts, links that open another state, and what the scene's `agree` finds (`figure_*`). The export
  runs none of the project's code (it reads the scene's title as text) and writes the packed fonts' licences into
  the file. Examples: `--example econ-lab` (households, firms and a central bank; every number from the
  set-the-rate toy's results) and `--example enter` (the coding agent's loop: you answer the permission check). The
  file carries every word and number of the scene, so publishing it shares all of that. Two engine fixes that show
  in films too: a stack now shrinks when its count goes down, and flow dashes over a link of their own colour now
  show. Guide: `references/workflows/diagram.md` § Interactive, `references/html-export.md` § Live figure. Test:
  `test_interactive.py`.
- **Diagram footers fade only the floor under them.** The fade under the footer lines (`page.footL`/`footR`) is now
  a feathered SVG mask on the floor layer alone, so a tag, a part or floor text that sits next to a footer keeps its
  full colour, and each hole follows its footer's `reveal`: a footer revealed later does not cut the floor before it
  shows. An empty footer paints nothing. Test: `test_diagram.py` (in both themes).
- **The site and the repository share one link-preview image.**
- **Site: "How showtime is built" at `harness/`.** The crew's operating manual, public edition: who does what, on
  which model and machine, and how a task becomes a merged PR or a film, in its own design inside the site's header
  and footer (every page's footer links it). Its loops, posters and the 0.4.3 film are small files in
  `examples/_harness/`; the page's body is `site/content/harness.html`, whose first line sets the address of the
  article it links to.
- **New: `showtime repro` turns a failing Playwright test into a short narrated video for a bug report.** From a
  `trace.zip`, or the test command after `--` (run with tracing on failure), it shows each step on the trace's own
  screenshots with a cursor and the target boxed, then the failing step slowed down with expected and received, the
  error and the console errors, and writes `repro.md` to paste into the issue. It writes `script.md` and stops;
  `--yes` renders it. Typed values are never shown or spoken (their fields are covered); paths are shortened to
  the file name, URLs lose their query strings, and secrets are masked. Guide: `references/workflows/repro.md`. Test: `test_repro.py`.
- **Docs and site for 0.4.3: the new features, with three demos and a live figure on the site.** The README has a
  "New in 0.4.3" section (living diagrams and live figures, recap, repro, the render fix, music per video and quiet
  cuts, the harness page), the new commands in its quick list and `diagram`, `recap` and `repro` in the command
  table; What's new has a 0.4.3 section; three task guides for people (`docs/guides/session-recap.md`,
  `bug-report-video.md`, `living-diagram.md`; the README now says fourteen); the glossary has "live figure" and
  "living diagram"; the docs map and its pictures count seventeen workflows. Three demos join the gallery
  (35 videos): `examples/_diagram` (the Enter loop film from `--example enter`, its live figure and the econ-lab
  live figure), `examples/_recap` (the test session in `tests/fixtures/recap`, with its `script.md` and
  `facts.json`) and `examples/_repro` (the fixture trace in `tests/fixtures/repro`, with `repro.md`), each with a
  README loop and still, on the Explainers and Code and data shelves and in "New in 0.4". `site/build.py`: a card's
  `Live figures:` links are its HTML, linked as "Live figure" and left out of the HTML videos list; the example page
  embeds the first one in a room as wide as the page, so it keeps its desktop layout (the figure stacks under
  820 px), and 1120 px tall on a phone, where the board, the step and the steps fit without scrolling inside it;
  inline code in prose wraps (a long fixture path widened phone pages to 456-480 px); the footer credits "With
  These Hands" for the recap demo. The harness page says "new in 0.4.3" for living diagrams. Tests:
  `test_site_build.py` (`test_live_figures_are_the_cards_html_not_its_videos`; 13 cards badged "New in 0.4"),
  `test_site_search.py` (13 badges, five demos).

## 0.4.2 (2026-10-10)

- **On Windows, `audio mix` runs writing into one folder at once no longer fail with "permission denied".**
  Several `showtime audio mix` runs of one `mix.json` whose outputs go into one folder share its `mix.report.json`.
  On Windows, replacing a file that another process is replacing or has open at that moment fails for a few
  milliseconds with "Access is denied", so one mix could exit with `permission denied:
  ...\.mix.report.json.<random>` (the end-to-end test of the 0.4.2 release PR on windows-2025). Every JSON file
  showtime writes atomically (`write_json`) now retries that replace for up to 2 s, as run records already did, and
  a "permission denied" on a rename names both paths and the Windows error code. `showtime render` was not affected:
  each render mixes into its own folder. Test: `test_foundation.py`
  (`test_write_json_retries_a_replace_another_process_holds`,
  `test_permission_denied_names_both_sides_of_a_rename`); `test_audio.py` (`test_08_parallel_mixes_share_the_cache`)
  is the end-to-end case.
- **Docs, second pass: stale `--workers` and splice help, the voice Essentials, "Whisper for transcripts", and a doctor pointer.**
  Left over from the 0.4.2 audit: `render --help` still described the old one-browser-per-8-threads rule and a splice
  "mixed again" audio it now reuses; the README repeated the old worker rule; `voice.md` listed the fit command without
  its `--estimate` dry run first and said "9 languages" for 9 Kokoro variants (8 languages); the site said Whisper is
  fetched for transcripts (it is Parakeet). `showtime doctor` now ends with a link to the troubleshooting page when a
  check fails. Test: `test_skill_structure.py` (`test_fit_is_estimated_before_synthesis` now scans `voice.md`; the
  stale-phrase guard now scans `site/build.py` and `harness-notes.md`), `test_lean.py`
  (`test_doctor_brief_and_verbose` asserts the link).
- **A capture lane's page keeps its size when its browser window is resized late (issue #49).** Under load, a
  whole capture lane of a normal render could come out wrong: with 3 workers on a 180-frame film, every frame from 60
  or 120 on. Playwright sizes a new page with two calls at once, the window (`Browser.setWindowBounds`) and the
  emulated viewport (`Emulation.setDeviceMetricsOverride`). A headless window on macOS is at least 500 px wide, so
  there the window always resizes, and when that resize landed after the emulated size, the view the screenshots
  copy took the window's content size, 500x57 for a 256x144 page, while the page itself still laid out at 256x144.
  Every screenshot of that lane was 500x57 (the page in the top-left corner, black beside it), and ffmpeg scaled them
  into the video; a clipped screenshot (`--scale` below 1, `--preview` above 720p) kept the right size with its bottom
  black. The saved captures of the failing renders show it; the frame writes, the encoder's reads (same bytes) and
  the frame order were right in every run. `stagehost.mjs` now sets the page's emulated size again from its own
  DevTools session once the page is ready, which fixes the race wherever it happens. Then it checks: `shot()` checks
  the size of every unclipped screenshot; a page whose screenshots are clipped gets one unclipped screenshot when it
  opens (the clipped ones have the clip's size whatever the view's); and every seek and every clipped screenshot
  read the page's layout size. A wrong size is set again and the screenshot or seek repeated (at most 3 times, then
  the capture fails and the worker retries on a new page), and render.log says so. Not covered: a clipped
  screenshot of a view that loses its size after the page opened while the page keeps its layout (not seen; the
  size set again at ready held through later window resizes in every probe), and `demo.mjs`, `capture.mjs`,
  `site.mjs` and `probe.mjs`, which take their own screenshots. Setting the size again also fixes `--scale 2`
  captures, which were 1x on a Mac every time (a 512x288 render came out 256x144). Measured on a 6-core Intel Mac
  with a GPU, a 256x144 page rendered with `--workers 3` against a 1-worker reference, every frame compared, under
  eight `yes` loops plus a looping 4 GB `dd` (load 17-78): 7 of 40 renders had a wrong lane before, 0 of 30 after
  (5 pages in those 30 runs opened with the 500x57 view and were set right when ready); at `--scale 0.5`, 5 of 20
  before, 0 of 20 after. The `dd` alone did it in 1 of 20 (load about 10), the `yes` loops alone in 0 of 20. Waiting
  for two equal screenshots before the first frame (tried first) does not catch it: two 500x57 screenshots are equal. Test: `test_render_speed.py`
  `TestCaptureSize` (a real window resize after the page opened, at scale 1, 0.5 and 2; each of the ready-time
  call, the screenshot size check, the seek's and the clipped screenshot's layout checks fails it when removed).
- **Site: "Start here" in four places, the gallery in six shelves, and "New in 0.4" kept low.** A newcomer's first
  action sat two diagrams and three tables down the docs map, "Get started" only jumped within the landing, the gallery
  was sorted by history (01 to 32) under a 0.2.0 film, a guide page's crumb was a repo path, and the new glossary
  (docs/glossary.md) and CONTEXT.md would have built to one page. The docs sidebar's first group is now **Start here**
  (Your first video, The map, When something goes wrong, Questions people ask, Glossary, Works with your agent, What's
  new with a version chip), which is also the start of Previous / Next; troubleshooting and the glossary are built,
  and CONTEXT.md moves to `docs/house-vocabulary.html` ("House vocabulary" in Backstage, linked from the glossary).
  The docs map opens with an **Overture · Start here** of three steps (install with Copy, your first video, if
  something goes wrong), and the first-video guide ends on "Next: choose your path". The landing's "Get started"
  opens the first-video guide, and its "New in 0.4" tile (all of 0.4.x) links each released 0.4 section and shows
  five of the new examples. The gallery opens on its intro ("Thirty examples and two demos"), then the tabs and a
  **Start here** shelf named by the kind of video (Launch video, Narrated explainer, Your footage, edited), then six shelves (Explainers, Your footage, Products and brands, Code and data, Social and
  trailers, Looks and motion), each with a line and the guides behind it. The groups and their order live in
  `site/content/gallery.json`, so the examples repository does not change, and the build stops when a card is on no
  shelf or two. The ten 0.4 examples carry a "New in 0.4" badge and a last tab, every card shows its number and one
  duration format (`25 · 2:38`, `02 · 0:45`) and a "Copy the request" button, example pages are titled "Example 25:
  ...", guide pages name their act in the crumb ("Docs / Act IV · Sound and voice / Voice") with a "See it done" line
  of examples, and the docs search opens install, error and first-video questions on the page written for them. The
  film above the gallery is gone (`"gallery_film": null` in `site/config.json`; an object brings one back), the
  footer credits its music only while one is set, and README.md's links to `gallery.html#launch-film` now go to the
  gallery and the film's MP4. The old tab addresses (`gallery.html#data-and-reports`, `#for-developers` ...) open
  All. The build stops when gallery.json's "New in" name is not the newest release's series, so the badges and the
  landing tile cannot name different releases. Test:
  `test_site_build.py` `StartHereAndShelves`, `PeoplePages` `test_glossary_and_house_vocabulary_have_their_own_pages`,
  `test_site_search.py` `RealBuild`.
- **A name cleared in `readback.ok` also clears it inside a longer phrase, and `readback.note` keeps a respelled
  name as a note.** `"readback": {"ok": ["Qwen"]}` cleared the word "Qwen", but the phrase "Qwen Image" failed again,
  because a cleared entry only matched the whole suspect text (issue #46). A suspect now clears through a run of whole
  words in it ("Qwen" for "Qwen Image" heard "QN image") when the rest of the phrase was heard as written, so
  "Hugging Face" does not clear a misheard "Hugging Face Hub", "AI" does not clear a swallowed "Open A I", and
  "Quenched" stays. A new `"readback": {"note": ["Qwen"]}` list, same shape and matching, is for a word a person
  listened to and found right (`voice ipa` shows the sound it is told) that the recogniser only spells another way
  ("QN"): it stays in the read-back as a NOTE (`NOTE ... [listed in readback.note by the project: ...]`), an INFO in
  qa, never a FAIL, tagged as the project's claim; the receipt and the qa hearing line count it as noted. `ok` wins
  when a word is in both. Test: `test_readback.py` `ClearedPhraseTests`, `RespelledNameTests`
  `test_a_noted_word_is_a_note_never_a_fail`.
- **Site: fixes from the 0.4.2 docs audit.** The live docs/skill.html showed SKILL.md's front matter as one huge heading
  (`render_md` parsed it as-is, so the closing `---` made it a setext heading); the footer said "0.4", the hero 0.4.1
  and the landing's "New in 0.4.1" was typed by hand; only sidebar pages had Previous/Next; "doctor" and "estimate"
  searches put the Changelog first and the landing and gallery were not searchable; and the gallery's film was
  hard-coded. The build now strips front matter before rendering, reads the footer and `llms.txt` version from
  `st.__version__` and the landing's "New in" from the newest release in `docs/whats-new.md`, gives the docs map,
  the Start pages and every example page Previous/Next, indexes the landing and gallery, weighs the changelog at 0.5
  in search, and reads the gallery film from `gallery_film` in `site/config.json` (`null` since the gallery
  redesign above: the old 0.2.0 launch film is no longer shown). Test: `test_site_build.py` `OneVersion`,
  `test_site_search.py` `RealBuild`.
- **Docs: a first-video guide, troubleshooting by symptom, a glossary, and clearer first explanations.** A docs audit
  found that newcomers were sent to the 1,382-line README, that troubleshooting answers were written for agents only,
  and that EDL, ledger and look signature were used before any page defined them. New pages:
  `docs/guides/first-video.md` (a 5-second test video step by step, timed on a 6-core Intel Mac, in the task-guide
  shape), `docs/troubleshooting.md` (twelve symptoms, each with what showtime does today, what to say and the
  command) and `docs/glossary.md` (the reader's glossary with a diagram of the job folder; CONTEXT.md stays the house
  vocabulary and is linked from it).
  The README, the docs map, the guides index and the FAQ link them. The two mode settings are now explained as two:
  quick or studio (how much the agent asks) and quality or lean (how much it checks), in the README, SKILL.md, the
  docs map and modes.md; the docs map no longer says "quick is lean". EDL, ledger and look signature are defined at
  first use (SKILL.md, editing.md, color.md). The FAQ's GPU answer leads with the answer, its language count names the
  eight Kokoro languages and the 32 in all (Kokoro's nine counts American and British English apart), the README's
  scoreboard sentence says what was measured, and "How it works" opens with today's order instead of the 0.2.0
  history. agents.md now says your agent runs setup, with terminal setup only for a sandbox that blocks the download,
  and names the transcription model instead of Whisper. SKILL.md goes from about 1,500 to about 1,490 words with every
  red flag kept: the new definitions are short there (the glossary has the long ones), and the opening line and a few phrases
  are tighter. `check_release` now checks the links and commands of the two new
  docs/ pages. Test: `test_skill_structure.py` `TestCheckersBite` `test_newcomer_pages_are_linked_and_checked`.
- **Chapter mode: render a film in named pieces and join them with one soundtrack (issue #22).** Rendering
  sections with `--from/--to` and joining them with `edit render` gave loudness steps of 2.6 and 0.7 dB at the
  joins (each span mastered its own audio) and cut fades. `render --chapters` prints the plan from showtime.json
  `"chapters"` (else the film's acts) and says first that on one machine a whole render is faster (measured: see
  render.md § Speed); `render --chapter N --job J` splices chapter N into the job's full render, or without one
  writes a video-only piece in `<job>/work/chapters/<W>x<H>/`; `render --join --job J` byte-joins the pieces at
  their keyframes (or encodes once when their settings differ), builds the soundtrack once for the whole video,
  muxes it and checks every seam against the master (frames, keyframes, the seam frames captured again against a frame inside the
  same piece, so grain or a high CRF passes, loudness step <= 0.1 dB, lag 0 +-1 sample) before naming it `final.mp4`, `kind: "joined"`; `qa` adds a seam section.
  Every whole render now has a keyframe at each chapter start, so after a whole render or a join a later
  `--chapter N` fix re-renders exactly its frames. A piece cut short is refused with its `--chapter N` command, a
  one-chapter film is refused, and the receipt counts each piece's time once. Pieces carry `sources_hash` (the project's sources, the same on a copy at another path): other
  files warn at the join, another length or size is refused. Tests: `test_chapters.py`.
- **The join's seam check compares each frame on Windows too.** On the Windows CI runner `render --join` stopped
  at a random frame of the seam check with "could not compare frame 119 of mux.mp4: frame= 1 ... time=00:00:00.00". The PSNR
  comparison gave ffmpeg's `psnr` the captured image at time 0 and the video's frame half a frame later (the seek
  lands between frames), so the one frame `-frames:v 1` keeps went out uncompared, and the real comparison only ran
  when the image's end of stream arrived, after the output had finished. Whether ffmpeg ran it before shutting down
  was thread timing: it did on macOS and Linux and now and then did not on Windows (no PSNR line, exit 0). Both
  inputs now start at time 0, so the first frame is the compared one on any OS, and the error quotes ffmpeg's own
  message instead of its progress line and stream list (`settb=AVTB` also drops psnr's "not matching timebases" warning;
  same values). Test: `test_chapters.py` (`test_frame_psnr_compares_the_frame_it_outputs` holds the image's end of
  stream back 1.5 s, which fails the old graph on any OS, and checks the value; `test_ff_messages_drop_progress`).
- **`test_signatures.py` checks reading time once per motion feel and template, not twelve times.** On the Windows
  nightly the file ran 868 s on its first night (6 Oct), then out of its 900 s on 7 and 8 Oct (680 s on 9 Oct); the
  Intel Mac reached 900 s on 9 Oct. It ran a full `showtime check` per look signature, twelve of them, on 4-thread
  runners without a GPU and next to another test file. The fonts wait raised to 60 s on 5 Oct was not the cause:
  it landed with the test itself, and it ends as soon as the faces are in. A look changes the palette, the type and
  the motion feel; the dense timeline (reading time, sizes and zones over the whole video) depends mostly on the
  motion feel and the template, and the determinism probe on the template only. `check_plan()` now runs the
  timeline for the first signature of each motion feel and of each template (6 of 12) and `--no-timeline` for the
  others (contrast, layout, phone size and zones from the samples, as before), and the determinism probe on the
  first check of each template (the only probe of the data template in the suite). The twelve checks without a GPU
  on a 6-core Intel Mac, one after another, with no probe at all: 994 CPU seconds and 762 s before (load 16-53,
  shared), 658 and 513 s after (load 21-44). Test: `test_signatures.py` `CheckPlan` (issue #13).
- **Without a GPU a slow WebGL frame no longer ends `check` at 60 s, and `check --no-cuts` skips the cut walk (issue
  #14).** On the macOS Intel nightly, `test_showreel.py`'s check of the showreel template at 16:9 ran out of its
  300 s (7, 8 and 9 Oct; the file passed at 879 s on 6 Oct). Without a GPU the template's WebGL shots (the chrome
  and heat shaders, the three.js knot) are drawn on the CPU, and every 12th WebGL frame cost the GPU process 8-18
  CPU seconds here, whatever the shader, the
  canvas size or the compositing flags; the cut walk (a second page that seeks every cut four times) paid for those
  frames again, at every aspect, although the first frame after a cut does not change with the aspect and
  `test_cut_frames.py` already walks the template's cuts. `--no-cuts` (next to `--no-timeline`) leaves out the walk,
  report.json's `cuts` and `late_first_frame`; the aspect test passes it. One 16:9 check without a GPU on a 6-core
  Intel Mac: 361 and 364 CPU seconds before, 242 and 244 after (160-183 s against 133-149 s wall at load 15-19).
  That was not enough. On 10 Oct the full tier still failed on the 4-core ubuntu-24.04 runner (the aspect test at
  9:16) and on macos-15-intel (that test, and `test_cut_frames.py`'s template check) with `timed out after 60s:
  reading the page's size`. A clipped screenshot (check's timeline, thumbnails and cut walk; render's `--scale` below
  1, and `--preview` of a page above 720p) first reads the page's layout size (#49). That read is the first call on
  the page's main thread after a seek, and without a GPU the main thread waits there while SwiftShader draws the
  seek's WebGL frame in the GPU process. The seek itself returns in milliseconds, so the page's pace stayed 1 and the
  read kept a flat 60 s. Reproduced on a 6-core Intel Mac with `--gpu off` and 8 busy loops: both runs ended this way,
  after 128 s and 127 s (the read after the seek to 0.9 s took 39 s, the one after 3.0 s passed 60 s), the GPU process
  working at about 0.45 of a core all the while and the renderers idle. The read is now guarded like the screenshot it
  belongs to (the stuck-frame guard, #24, below): waited for while the GPU process and renderers work, failed once
  they have done no work for 30 s (x the page's pace), sooner than before. The longer bound is the same as for
  screenshots: where the browser cannot report its work, or any of its pages keeps working (the work is summed over
  all of them), a check or a clipped render frame can now wait up to 10 minutes at that step (render: up to 3
  attempts, each in a new browser) where it waited 60 s x pace; the read and the screenshot of one capture share those
  10 minutes. The page load (to DOMContentLoaded) also had a flat 60 s, and on the same Mac under heavier load (23,
  another session's renders) it ended check's cut walk once after the read was fixed (`Timeout 60000ms exceeded`, no
  cuts probed; seen once there, not on CI). It now gets 3/5 of the page-open deadline, 180 s: a load that never
  finishes still fails as the page (check's `ready_failed` with a report; on check's second pages, the cut walk, the
  determinism load and the no-GPU probe, the soft finding it was), not as a stuck browser killed and tried again after
  the page-open deadline. With the read fix the two checks pass on that Mac with the busy loops and another session's
  renders (595 s for the 9:16 check, 886 s for the one with the cut walk, 13 cuts and none late, at load 20-35; single
  size reads of up to 290 s, the GPU process at work throughout), and with the load deadline the 9:16 check again
  (435 s at load 11-16). Tests: `test_pace.py` `TestSizeReadWaitsForTheFrame` (a main thread held past the old
  deadline is waited for, a stopped renderer still fails the read), `TestSlowPages`
  `test_load_that_never_finishes_is_the_page` and `test_second_page_load_is_a_finding`, `test_cut_frames.py`
  `test_no_cuts_skips_the_walk`.
- **`review-findings` accepts `t=a-b s` ranges as a timestamp, and Polish items get ids.** A finding carrying a range
  such as `t=38.73-41.50s` was warned as citing no timestamp (the check only knew `t=3.00s`), and Polish bullets were
  left out of the id scheme, so `showtime review-respond <job> --fixed r1-P1` only printed the list of valid ids
  (issue #48). Ranges (`t=38.73-41.50s`, `t=38.73s-41.50s`, `t=38.73 - 41.50 s`) now count in every finding, and
  Polish bullets are registered as `r1-P1 ...` beside `r1-B1` and `r1-S1`: they are listed by `review-respond`, can be
  marked fixed or waived, and are counted by `review-findings`, but are never open, so they still never gate the
  delivery (and stay out of the receipt's counts and lists and the next round's PREVIOUS list). The pairwise parser
  `review-verdict` reads uses the same timestamp pattern, so a range-timestamped finding is no longer dropped there.
  A Polish bullet without a timestamp now gets the "cites no timestamp" warning too, as CRITIC.md asks of each. Test: `test_review_mode.py`
  `TestReviewFindings` `test_time_ranges_count_as_timestamps`, `TestFindingsGate`
  `test_polish_ids_register_and_never_gate`.
- **Voice-led workflows run `voice script --fit S --estimate` before the first synthesis.** `--estimate` already
  prints "cut about N words" and synthesizes nothing, but only `voice.md` mentioned it: the social-short, explainer
  and other voice-led routes went straight to `--fit <seconds>`, so an agent with a slow voice (about 2.6 words/s)
  ran a 1-4 minute fit three times, cutting words between runs, and ended at x1.12 (issue #45). The social-short,
  explainer, repo-explainer, paper-explainer, data-story, localize and manim guides, the scriptwriter and voice
  director briefs now say to estimate first and cut words until it fits, and SKILL.md pipeline step 2 names the estimate and then the real run. Test:
  `test_skill_structure.py` `TestSkillMd` `test_fit_is_estimated_before_synthesis`.
- **"This look repeats recent videos" names the property that matched, its distance and its threshold.** The warning
  said which aspect repeated (palette, type pair ...) and listed the look's own values, but not what matched against
  the earlier job or how close it was, so after changing colours by hand the warning stayed with no way to tell what
  to change next (issue #47). Each repeat now carries a `why` (in `showtime check`, `history check` and `--json`): the
  palette colours that matched with their distance and the threshold (`3 of 4 colours match (#a ~ #b 12 apart; threshold
  60, needs 3)`), `fonts identical (Inter)`, the share of camera moves or transition kinds against its limit, the
  scene-length spread against 6 %. A page wearing a look
  signature matches on the signature id in its look comment, not on colours, and says so (changing colours does not
  clear it; `showtime signature` picks another). The `why` names the job it was measured against. Test: `test_variety.py` `TestHistory`
  `test_message_names_the_matched_property_distance_and_threshold`.
- **`render --size` checks the page it renders, and a timing error is not "the layout breaks".** The layout check that
  runs before a `--size` render started `check` without `--page`, so it ran on `index.html`: a page whose text runs
  off the frame at 9:16 rendered anyway while `index.html` was fine, a broken `index.html` stopped the render of a
  clean page, and the report landed in `index.html`'s `work/check-<WxH>/`. The stop rule also matched any error code
  containing "clip", so a `clip_timing` error (not a layout problem) stopped the render with "the layout breaks".
  Render now passes `--page`, the thinner report goes to its own `work/render-check-<page>-<WxH>/` (it never replaces
  a full `showtime check` report), the hint names the page however it was given, `clip_timing` no longer stops it, and
  the check runs with `--no-timeline --no-history` (nothing those phases find can stop a render; 69 s to 24 s in the
  issue's measurement of a 30 s 9:16 check). Not done: skipping the check for a splice whose page is byte-identical to
  the base render's. Test: `test_render_fixes.py` `RenderSizeChecksItsPage` (issue #43).
- **A chart with `states` and none at 0 now opens on its own `data` and `title`.** The top-level `data` and `title`
  were dropped as soon as `states` was given, so a chart whose first state was at 5.86 s opened on that state and its
  title, and its own 6-row view never appeared (and `check` and `qa` passed; only a contact sheet showed it, issue #44).
  The top-level `data` and `title` are now the implicit state at 0 whenever no state starts at 0, and the first state
  morphs from them; `components.md` §4 says so. Charts with a state at 0, or with no `data`, are unchanged. Test:
  `test_chart_labels.py` `ChartLabels` `test_top_level_data_and_title_show_before_a_first_state_later_than_zero`.
- **Without a GPU, `--workers auto` uses more browsers from 8 CPU threads up.** It picked one browser per 8 CPU
  threads, at least 3, so an 8-thread machine with software GL got 3, while a 180 s 1080p30 DOM page rendered in
  231 s with 8 against 345 s with 3, and a WebGL showreel in 529 s with 8 against 752 s with 4 (issue #41). Auto is
  now CPU threads - 2 from 8 threads up (at most 8, and still within the frame, memory and `SHOWTIME_MAX_WORKERS`
  limits); below 8 threads and with a GPU nothing changes. Test: `test_render_speed.py`
  `test_auto_workers_and_software_gl`.
- **`edit render` keeps the sound in sync with the picture on showtime's own renders (issue #38).** A range cut from a
  render made by showtime (`-bf 0`: its video edit list starts at 0, its audio's after the 1024-sample AAC priming) could
  come out with its sound up to 1024 samples (21 ms) early: the input seek that cut each range is not sample-accurate
  on this audio, and its error depends on where it lands (1024 samples at `"start": 0`, the usual case for span or
  chapter files, which also left 21 ms of silence before every cut; 256, 512 or 1024 at some later starts, e.g. 2, 4
  and 8 s). Each range's sound is now decoded from the file's start, with no input seek, and trimmed to the exact
  sample; the video keeps its fast seek. Decoding the AAC of a 10-minute source takes about 1 s, so a range near its
  end renders about 1 s slower. Cached segments are rebuilt once. Test: `test_footage.py` `EdlAudioSyncTest`.
- **Extra local voice engines load by name, and doctor stops failing on Kokoro when you chose another engine.**
  The engine list was closed in three places (`engines.get()`, the `--engine` choices and `$SHOWTIME_VOICE`), and
  doctor failed on Kokoro's model files even after `setup --skip models` with another engine selected. An engine of
  your own is a Python module `<name>.py` exposing `ENGINE` (Piper-shaped: `has_timings = False` gets the usual
  alignment), found on `$SHOWTIME_ENGINE_PATH`, then in `~/.showtime/engines/` (it survives an update), then next to
  the built-in engines; a built-in name always means the built-in engine. Names must match `^[a-z][a-z0-9_]{0,31}$`
  and are checked before any import; an unknown name lists the engines found. `$SHOWTIME_VOICE=<engine>:<voice>`
  selects one; doctor skips Kokoro's files when the voice names another engine (an unset voice still expects
  Kokoro) and lists each extra engine and whether it imports. `references/voice.md` has a "Bring your own voice
  engine" section: your engine, your network; showtime ships no network engine. Proposed and designed by @heavygee
  in issue #8, who also wrote a matching PR (#36). Test: `test_voice_engines.py`.
- **The scriptwriter and the storyboard artist get more turns, and the director is told how to stay inside them.** A heavy
  storyboard brief ran out of turns before it finished (issue #42). `scriptwriter` now has `maxTurns: 50` (was 30) and
  `storyboard-artist` `maxTurns: 80` (was 50). `references/crew.md` §3 tells the director to split a heavy brief (the
  board first, the animatic as a second task) and, when a member stops at its cap, to resume it with a follow-up
  `SendMessage` instead of dispatching it again. Test: `test_skill_structure.py` checks that every crew agent
  declares `maxTurns` between 20 and 100.
- **A fix to a `--size` variant is spliced too.** `render --from/--to --job` spliced a fix into the job's last
  full render, but with `--size` it always wrote a span clip, so an audio-only fix to the 9:16 cut
  (`<job>/1080x1920.mp4`) took a full re-render (about 2.5 min instead of 43 s for the 16:9 final). With `--size` the
  span is now spliced into the job's newest render of that size (`<W>x<H>*.mp4`, the same project, frame rate and
  length checks), written as the next `<W>x<H>-N.mp4` (a variant: the job's final is unchanged), with the soundtrack
  reused when its inputs did not change; with no earlier render of that size it stays a span clip and says why.
  Test: `test_splice.py` `TestSpliceSize` (issue #29).
- **`check` and `render` reject a malformed audio mix spec before any frame is captured.** A `showtime.json`
  `"audio"` pointing to a mix spec with no `tracks` list passed `check`, and the render then only warned
  (`AUDIO FALLBACK`) and shipped the simple mixer's soundtrack (issue #27), which cost a whole re-render. `check` now
  validates the audio (a missing file or spec, no or empty `tracks`, an unknown track `kind`, a track without exactly
  one source, a missing track file, a non-numeric `start`/`at`/`gain_db`...) and reports an `audio_mix` error; `render`
  runs the same validation at its start and stops with that message and a non-zero exit (not with `--no-audio`).
  The same rules run alone, without rendering, as `showtime audio mix <spec> --validate`. Catalog and library
  sources are not resolved. A mix that passes validation but fails while mixing still falls back as before.
- **`voice script --fit` says up front when the narration cannot fit.** It used to synthesize every line, then
  re-synthesize them all at up to four speeds, and only then report how many words to cut (issue #28). Now the
  characters are counted at the voice's own rate before the first line, a script that is too long gets "cut about N
  words" (and the rushed-speech warning) at once, and `--fit S --estimate` prints that estimate alone without making any audio.
- **`voice_to_music_db` is no longer empty when the music is `ST.score`.** The score is rendered offline and
  combined after the mix, so a voice-over mix plus `ST.score` had no music bus and `mix.report.json` said
  `"voice_to_music_db": null` (qa's hearing facts read the same field), although the guides tell the reader to
  check it (issue #30). `render` already measured the voice-over-score gap into `render.json`
  (`audio.voice_over_score_db`); it now also writes it into the mix report as `voice_to_music_db`, with
  `voice_to_music_source: "score"`, unless the mix measured one itself. Test: `test_render.py` `test_19`.

- **A frame that never comes no longer stalls a render or a check (issue #24).** A screenshot used to be waited
  for up to 10 minutes in a render and for ever in a check. Now once the browser's GPU process and renderers have done
  no work for 30 s (x the page's pace) the screenshot fails: render draws the frame again in a new browser
  (`capture.retries` in `render.json`) and check ends with an error naming its step. A browser that cannot report its
  processes' work keeps the old cap (10 minutes, `SHOWTIME_SHOT_TIMEOUT`), and so does a frame whose renderer keeps
  working (a page with its own timer loop). `SHOWTIME_TIMEOUT=<seconds>` gives a render or check its caller's limit:
  past it the command ends with an error naming where each of its parts is. Tests: `test_pace.py`
  `TestFrameNeverComes`, `TestSlowPages`.
- **`--disable-frame-rate-limit` stays on Linux only.** 0.4.1 shipped it in render's browsers on every OS. With it,
  a renderer keeps spending CPU after the GPU process stops, so on macOS the guard above never saw a stopped GPU
  process (measured on an Intel Mac with a GPU: the stall test fails with the flag and passes without), and it bought
  about 2 % there, inside run-to-run spread, for about 22 % more CPU while rendering; it is the likely cause of the
  stalls on the macOS CI runners, where this has not been re-run. On an 8-thread Linux machine without a GPU it is
  about 10 % faster than without it (5 % faster than 0.4.1, which has the flag but not the guard) and the guard still ends a frame that never comes. `"render"` in
  `scripts/lib/chrome-flags.json` is now per OS like `"gpu"` (`renderFlags()` still takes a plain list): on Linux only;
  off on macOS and Windows, which is untested with the guard and goes back to its state before 0.4.1. Tests:
  `test_pace.py` `test_no_frame_rate_limit_flag`, `test_render_speed.py` `test_auto_workers_and_software_gl`.

- **A WebGL canvas that loses its context no longer ships white.** On the Intel Mac CI runner some renders lost
  every WebGL context on the GPU, and each of those canvases was captured white with no word from `render`
  (nightly `test_cut_frames`, issue #12). In a render the page's WebGL canvases are now watched after every seek:
  one lost while on screen stops a render on the GPU, which runs once more without it (`--gpu off`, into the same
  folder, with a warning that says so); without a GPU, where the page itself is the cause (more contexts at once
  than the browser keeps), the warnings name each canvas and its white frames. Showtime's looks are left out: they
  give contexts back on purpose and draw their fallback (`check`'s `look_lost`).
- **`setup` installs a failed extra again on a plain re-run (issue #39).** When `setup --full` failed on manim (pycairo
  and manimpango could not build without the cairo headers), the extra was recorded anyway: the next `setup` exited 0
  in a second and skipped it, doctor said "the manim extra is recorded but not importable", and only `--force`
  fixed it. A re-run now checks every recorded extra with doctor's own check (the manim package in the main venv,
  manimlib in the manimgl venv) and installs a broken one again, with one line saying why; a working one is still
  skipped. Doctor's manimgl row checked only that the venv existed, so a failed package install passed; it now
  says "the manimgl extra is recorded but not importable". setup also drops doctor's cached `--quick` result
  (`cache/doctor-quick.json`, reused up to 1 h), so the next `showtime doctor --quick` checks again instead of
  showing the WARN from before.
- **`setup` names the missing build dependencies of manim/manimgl before it downloads anything (issue #40).** They only
  showed up when pycairo failed to build, after about 55 min of `setup --full` downloads. When the plan installs
  manim or manimgl on macOS or Linux, setup first checks for a C compiler, pkg-config, and cairo + pangocairo
  (`pkg-config --exists`), and a missing one is a WARN with the install line for this OS (the one the manim
  failure already printed) at the start; setup goes on. Test: `test_os_install.py` `TestExtras`.

- **`retime --from-voice` counts a silent scene once before a later pin (issue #21).** When a pinned line (`at`) came
  after a silent scene but not directly after it, the line right after the silence lost the pin and the silence was
  counted twice: once by the voice holding the gap up to the pin and once as the silent scene's own length. The first
  pinned line after the silent scene now counts, even with unpinned lines between them, so the silent scene fills the
  gap before the pin and keeps its length when the gap allows; render.md says so. Test: `test_storyboard.py` `TestSilentShots`
  `test_a_later_pin_holds_the_silent_shot_once`, `test_two_lines_after_a_silent_shot_one_pinned`.
- **The stable `showtime` command keeps the installed skill when two copies have the same version (issue #23).**
  On a tie the command used to follow whichever folder ran last, so running a second checkout or a scratch copy of the
  installed version re-pointed it for every agent and script sharing the home. Now an installed skill (a plugin, or a
  skill in an agent's skills folder) wins a tie over a checkout or a copy run by path, and otherwise the recorded one
  stays; a newer version still wins, and `showtime setup --link` points the command at its checkout on purpose.
  `showtime doctor` no longer reports such a kept tie as drift. agents.md, harness-notes.md and CONTRIBUTING.md say so.
  Test: `test_portable.py` `test_same_version_keeps_the_installed_skill`.
- **The `mix.json` examples use the `tracks` list the mixer requires, and the review guide says to wait for the critic's
  reply (issues #26 and #32).** The explainer and music-video workflows and music.md showed a track object at the top
  level of `audio/mix.json`, which the mixer rejects; they now show `{"tracks": [...]}`. The review and crew guides
  told the agent to wait for `FINDINGS.md` to appear, which never happens when the critic's Write is denied (it returns
  the findings as its reply); they now say to wait for the critic to return and save its reply when the file is
  missing, and the critic's brief says to reply with the whole block when it cannot write files.
- **A caption-karaoke overlay on a canvas film is documented (issue #31).** `F.caption` draws plain text with no
  per-word highlight, and nothing said that the DOM `caption-karaoke` component can sit over a canvas film. film-api.md
  now has "Karaoke captions over a canvas film" (the two lines to add, `data-src` pointing at the voice module's
  `vo.words.json`, how `check` audits the layer and what it cannot see on the canvas); components.md and the explainer
  workflow link it.
- **"Full crew" is a trigger, and the guides carry one table of the words that set each mode (issue #33).** Saying
  "full crew" or "use the whole crew" keeps quick mode (no pitch, no storyboard gate) and dispatches every member the
  job can use (the sound designer for any film with music, the voice director for any voice-over, motion designers,
  the researcher, the critic twice); CPU limits still apply. The README, modes.md and crew.md show the same table of
  what you say, the mode and the crew. A new plugin-eval case, `full-crew-trigger`, checks it.
- **Publish-bound quick jobs with music or effects dispatch the sound designer (issue #34).** Quick mode named the
  critic, the researcher and scene builders, so a publish-bound film with a music bed or effects was mixed inline
  without the sound designer. modes.md, crew.md and the README now add the sound designer, in parallel with the build,
  when the video is publish-bound and has music or effects (not voice only, not lean).

## 0.4.1 (2026-10-08)

- **Renders are faster, most of all without a GPU.** Measured on a 64-core Linux machine with no GPU, default
  settings, best of 2 interleaved runs against 0.4.0: a 30 s launch film (900 frames) went from 42.0 s to 17.6 s
  (2.4x), a 15 s DOM page from 31.8 s to 16.4 s (1.9x), a 15 s WebGL showreel from 25.3 s to 21.9 s. With the same
  worker count the DOM page and the launch film are still 12-28 % faster (launch on 8 workers 22.8 -> 17.5 s, on 16
  workers 18.2 -> 13.1 s); the picture matches 0.4.0 at SSIM 0.997-0.998 and files are about the same size. On a
  busy 6-core Intel Mac a 1 s fix spliced into a 15-30 s video went from 31-54 s to 13-21 s. `references/render.md`
  Speed.
  - The encoder runs during the capture: one ffmpeg reads the frames in order as they land (the same file byte for
    byte as encoding afterwards; `SHOWTIME_PIPE_ENCODE=0` goes back), so on the launch film 0.5 s of encoding was
    left after the capture instead of 4.5 s. x264 `veryfast` is the default (`--x264-preset medium` or
    `"render": {"x264_preset": "medium"}` for the old one); a splice reuses its base render's preset.
  - Without a GPU the automatic worker count follows the cores: one browser per 8 CPU threads, at least 3 from 6
    threads up, at most 8 (8 on the 64-core machine, where 0.4.0 used 3); a container's memory limit caps it.
    `render.json` and the log say how many and why. With a GPU it stays 3.
  - A finished worker takes over the back half of the largest part left, and the other browsers start while the
    first loads the page. Render's browsers draw a frame when asked instead of on the next 60 Hz tick.
  - An unchanged soundtrack is reused from `~/.showtime/cache/render-audio` (12 newest, 1 GB); the key covers the
    mix, every file it names and their licence and beat sidecars, the music vetoes and look history for catalog
    queries, and the audio code. `SHOWTIME_AUDIO_CACHE=0` turns it off.
  - A stuck browser or encoder no longer hangs a render: a page that does not open gets a new browser, a frozen
    browser is dropped and its frames retried on a fresh one, an encoder that exits or a frame write that fails no
    longer leaves the render waiting, and every ffmpeg call around the poster and the mux has a time limit. Waits
    (load, fonts, images, videos, `ST.waitFor` gates, seeks) scale with the page's measured pace, up to 5x and never
    below the fixed values, so heavy pages on a busy runner or a machine without a GPU no longer time out (`pace` in
    `render.json` and check's report; `ST.pace()`; `SHOWTIME_PACE=0` keeps fixed waits).
- **Designed cards over a talking head, timed to the words.** An EDL's `cards` put a title, lower third, pull-quote,
  data callout, chapter, a list that builds as each item is said, or a side panel over real footage, anchored to a
  phrase (`say`) or a word, so a re-cut moves them. They take the job's brand kit or look signature and render once
  as an alpha clip under the captions. `references/editing.md` section 9.
  - Captions never cover the speaker's face (tracked eyes to chin: moved below the chin, else above the eyes;
    `captions.avoid_face` for edits without cards; qa `caption_face`). `captions.emphasis` colours key terms.
  - A panel frames the speaker into one half; a 9:16 card with no room beside the face becomes a split, and a
    caption crossing a split's edge is cut there. A range `hold` freezes its last frame with the sound faded, for an
    ending with air. Spoken numbers fold as said (2.5, years), and a stat takes its figure only from one clean
    number.
  - `showtime edit cards suggest` lists card moments in a transcript, locally; `edit check`, `edit view` and qa
    (`card_problem`) know cards, and `edit check` flags list items said after their card leaves.
- **A word behind the speaker, cut out on the CPU.** `showtime footage cutout <clip> [--from A --to B] [-o out]`
  cuts a person out with MODNet portrait matting (Apache-2.0, 26 MB, fetched on first use), smoothed over time and
  reset at every cut, as VP9 with alpha (`--format prores` or `png`), a matte file and a contact sheet. About
  1.3-1.8 min per minute of 1080p on a 64-core Linux machine with no GPU, about 5.7 min when held to 6 of its cores
  (3.7 with `--size 384`). The EDL card `"type": "behind"` puts a big word between the background (`dim`, `blur`, `ground`, a colour
  or an image) and the speaker; qa warns `behind_hidden` and `matte_flicker`.
- **A long recording to its best short clips.** `showtime edit moments <transcripts | folder | job>` ranks
  whole-sentence moments of `--min`..`--max` seconds by local signals (a hook in the first 3 s, a complete thought,
  speaker energy, laughter and applause, one topic; introductions and logistics rank lower) into `moments.json` with
  a reason and a suggested title. `showtime edit clips [job] --pick m1,m4 | --count 3` makes them finished clips:
  tight whole-word starts and clean ends, fillers and pauses trimmed, face-tracked 9:16, captions off the face,
  optional `--cards`, rendered in parallel, each through qa, with a contact sheet. A 58-minute panel took about 7
  minutes end to end on a 64-core Linux machine with no GPU (example 24).
  - Edit renders no longer let the sound drift ahead of the picture at cuts (62 ms by the end of a 9-segment clip);
    EDL ranges take `fade_out`.
- **Claude Design to MP4: `showtime adopt <export.zip>`.** A Claude Design HTML export (the zip or its folder) is
  unpacked into the project's `src/`; the artboard fills a frame of 1080 on its short side (1280x720 -> 1920x1080,
  540x960 -> 1080x1920) with sharp text, its Google Fonts are copied in with their licences, the length comes from
  the animation's own clock or its CSS loops, and a looping design renders exactly one seamless loop (`loop_seam`
  otherwise). `references/adopt.md` From Claude Design, example 28.
  - New `showtime assets font --css <Google Fonts link> --copy-to <dir>`: the files a browser gets, with each
    family's licence; non-OFL/Apache/MIT/UFL families need `--allow-license`. https only, files only from
    fonts.gstatic.com; an offline `--refresh` keeps the fonts already copied (checked by sha256).
  - An artboard larger than the frame is no longer cropped, a cursor blink is not taken as the loop, and
    `adopt.json` keeps paths relative to the project.
- **Seven looks in showtime's own WebGL, no GPU needed**: `fluted-glass`, `tilt-shift`, `liquid-metal`,
  `mesh-gradient`, `god-rays`, `marble` and `metaballs`, each with presets built from the theme tokens, the same
  frames with any worker count, and a designed fallback where WebGL is missing. At its default size each adds less
  than 50 ms to a 1080p frame without a GPU (one browser on the 64-core machine; `references/components.md` section
  7 has the table). A look holds a WebGL context only while its clip is on screen, so twenty looks on one page no
  longer go blank, and on a GPU each look reads its frame back before the screenshot (no stale frames).
  `showtime check` prints each look's estimated cost and warns `look_budget` (over 50 ms), `look_fallback`, `look_contexts`
  (over 8 on screen at once, an error over 14) and `look_lost`. `examples/_looks`.
- **Shutter blur on chosen elements.** `data-st-blur` (or `ST.blur(el, {pose})`) smears an element as a 180° shutter
  would, only on the frames it moves fast, and lands it sharp; options `shutter`, `samples`, `threshold`, `max`;
  `F.motionBlur` for canvas films. About 8 ms more per blurred word per frame at 1080p without a GPU (one browser on the 64-core Linux machine). check warns
  `blur_text`, `blur_slow`, `blur_container`, `blur_unsampled` and `blur_inline`. The showreel template's flash
  words are now snaps under the blur. `examples/_blur`.
- **qa hears the mix as a phone speaker does, and the mixer is speaker-safe by default.** The first mix of the 0.4.1
  showreel was almost inaudible on a phone: above 300 Hz it sat 13.6 LU under the full mix. `speaker_loudness`
  measures the mix above 300 Hz and 1 kHz against the full mix: WARN over 10 LU, FAIL over 18 (posted films measure
  0.7-8.2 LU; a soundtrack showtime did not mix, such as your own song or a footage edit's sound, stays a WARN). `showtime audio mix` (so also `render` of a showtime.json `"audio"` mix; not an `ST.score` bed or the
  built-in fallback mixer) puts a 40 Hz high-pass on everything but the voice and, on a bass-heavy mix, a low shelf on
  the bed; voice-led films change by 0.01 LU. `"master": {"speaker_safe": false}` or
  `--no-speaker-safe` turns it off. The mix report gives each effect its speaker gap and notes a sub hit with
  nothing in the mids (`sub_alone`).
- **The voice-over is heard back.** `voice script` and `voice say` transcribe what they wrote with the local
  recognizer and compare it with the script sound by sound, so a name, acronym or number said wrong ("Open A I"
  heard as "OpenI") is a WARN with its fix; cached by each line's audio and recognizer. It runs when the local
  recognizer is installed: it arrives with the first transcription, or `showtime setup --fetch
  parakeet-tdt-0.6b-v3-int8`. A flagged line is heard again by a second recognizer when one is installed (Whisper
  small.en for English), and a word someone listened to is cleared with `"readback": {"ok": ["JSON"]}` in
  showtime.json. `--no-readback` or `SHOWTIME_READBACK=0`. qa adds a `readback` hearing item (FAIL only for a title,
  brand or lexicon name the second recognizer also hears differently), review-pack's `audio.txt` lists every
  line as scripted and as heard, the critic checks it and the receipt names the words. A lone "A" spelled inside a
  name is flagged; the lexicon gains LaTeX, TeX, arXiv, Nvidia, sudo, and Python and PyTorch for Spanish.
- **Notes name what they point at, and cover a stretch of time.** `showtime review notes` resolves each spot or box
  to the scene and the elements under it (`--no-elements`; `--json` `on_screen`); a note can span `t` to `to`
  (Shift + drag on the bar, `[` and `]`, Mark stretch on a phone, `--add ... --at T --to T2`), shown as a band with Play
  stretch and counted at delivery.
- **Since you last looked.** `showtime status <job>` lists what the person changed while the agent was away (project
  files edited by hand, unread notes, new board picks and comments, open findings), then marks it seen; job commands
  end with one line pointing to it (`--json`: `since_last_looked`). `SHOWTIME_AWAY_MIN`, `SHOWTIME_CATCHUP=0`.
  `job init` writes `AGENTS.md` and `CLAUDE.md` into the job folder for a resumed agent.
- **HTML exports that are whole, small and shareable.**
  - Every file the page needs is packed or the export stops with the list (a large minify outlasted the local
    server's keep-alive, and a Physics explainer lost every scene after shot 7). Sound files only a data file names
    stay out: that export went from 25.3 MB to 4.1 MB.
  - Link previews: `--share-url` / `--share-image` or `"share"` in showtime.json add the tags that show a title, a
    description and the poster frame when the link is pasted. `--folder` writes `.nojekyll`, so GitHub Pages serves
    it as is (#19). `showtime export html <job>` takes a job.
  - The player no longer stalls after a seek on a server without Range requests (`python -m http.server`; when
    reading the soundtrack whole fails, the next seek tries again), and
    `--max-mb` re-encodes a footage clip that needs a second pass from the original, once, on at most 8 threads
    (x264's rate control overshot on 64).
- **`showtime check` catches more.** Text is judged for contrast at its most opaque frame (long fades no longer fail
  `low_contrast`); `caption_zone` warns about an element where the captions sit while one shows
  (`data-st-caption-ok` to opt out); `webgpu` checks a page again without WebGPU (an error when nothing draws in its
  place); `same_frame_entrance` starts an entrance where its keyframes leave opacity 0; image loads cancelled by
  check's own seeks are counted apart (`cancelled_loads`).
- **Clean installs on macOS, Windows and Ubuntu, fixed from what fresh machines found.** `setup` checks uv and
  Node.js before any download and prints each system's install line (also in `--estimate`, which now gives the disk
  each part takes); on Windows a missing Visual C++ 2015-2022 runtime is named with its download link in setup,
  doctor and any DLL load error, `setup --force` no longer fails replacing its own venv, and `job init` warns when a
  job folder is deep enough to pass the 260-character path limit. An ffmpeg without the options showtime uses
  (Ubuntu 22.04's 4.4.2) is refused by setup and warned by doctor, and a loudness reading that failed is never
  recorded as 0 LUFS. The preview window opens Chrome with its device discovery (Cast) turned off. The test suite skips
  the site tests without the examples checkout. `check_release.py --mirror` checks every model and audio mirror
  asset, and a failed model download names the missing mirror file.
- **Docs for people.** An FAQ (GPU, cost, agents, privacy, licences, disk, time, platforms, languages, hand edits,
  the critic, questions, notes) and What's new, first in the site's Start group; ten task guides in `docs/guides/`
  (a talking head with cards, Claude Design to MP4, a long recording to clips, a launch video from a repo, another
  language, a PR video, an explainer that asks, going all out, notes and fixes, a slow machine), each with what to
  say, what you get, measured times naming the machine and the limits, in their own sidebar group after Start. The README, the docs
  maps, SKILL.md, SECURITY and PRIVACY catch up with 0.4.0 and 0.4.1. Site search finds hyphenated names
  (`pr-video`) and opens the matching section; pages get share tags and a canonical link, and the site has
  `sitemap.xml`, `robots.txt` and `llms.txt`.
- **Examples for 0.4.0 and 0.4.1 (#18).** 23, a NASA interview dressed with cards and a word behind the speaker, at
  16:9 and 9:16; 24, a 58-minute panel into three vertical clips; 25, a Nobel Physics explainer whose HTML video
  stops at three questions; 26, a Nobel Chemistry explainer in English and Spanish; 28, two Claude Design exports
  adopted as they are; 29, `showtime pr-video` on showtime's own PR; 30, the showreel template in four shapes with
  no edits; 32, one project in all twelve look signatures. The gallery gets a Looks and motion group with the looks
  and shutter blur demos. Examples made before look signatures say `--look template` in their rebuild steps.
- **GitHub as the public tracker.** Issue forms (bug, feature idea, example request, docs problem), a Show and tell
  discussion form, a code of conduct (Contributor Covenant 2.1) and release notes categories. The nightly reports
  its own failures: a failed run comments its failed jobs and tests on the open nightly issue or opens one, and a
  green run on every system closes it (#15).
- **Fixes.**
  - `new --from-storyboard` keeps a "(pause)" narration cell (or another direction, or a dash) as a silent shot
    instead of voicing it (#17); `retime --from-voice` lets a pinned line win over a silent scene before it, which
    fills the gap instead of adding its length on top, and never shrinks under 1 s.
  - `audio music search` never cuts a track id, and an unknown id names the closest one (#16).
  - New `showtime review-findings <job> < reply`: a critic that cannot write files returns its answer as text, and
    this saves it as the round's FINDINGS.md after checking its shape (#20).
  - Posters, thumbnails, qa frames and snaps pulled into a JPEG convert the video's colours properly (a saturated
    poster was about 6 levels darker than its frame), and qa compares the poster with its exact frame.
  - A file that reads above the -1 dBTP ceiling at all after the AAC encode is re-encoded (a GitHub copy read -0.9).
  - `pr-video` shows a description's list item by item ("+ N more" for the rest) instead of the opening paragraph
    cut into frames; the showreel template's data shot fits 1:1 and 4:5; a mix track's `"ending": "song"` keeps the
    song's own ending; a span render with `-o <own name>.mp4` and no `--job` writes that file and never splices into the job's final
    (with `--job` the fix is spliced as before and `-o` is ignored); two renders
    started in the same second no longer share a folder; a scene marked `data-stretch="spread"` spreads its beats
    when it gets longer (the dom template's hero no longer holds still at `--duration 24`).
  - Transcripts say where their language came from (`language_source`), Parakeet v3's language guess works again (it
    always said English), a soft first word is kept and a music intro is not transcribed.
  - `guide --find` takes several words unquoted; the templates' sample URL is a reserved `.example` name; the site
    shows a stray placeholder tag as text instead of hiding the page; the critic is described as reviewing every
    video in quality mode; `history clear` also removes the signature picks.
  - A browser that stops answering no longer hangs a command: every page showtime opens has a deadline (5 minutes,
    longer for slow pages) and one retry in a new browser, and check exits with an error naming the step; a 3D look
    whose WebGL context is lost stays in check's report with its fallback.

## 0.4.0 (2026-10-05)

- **Videos that stop and ask.** showtime.json `"questions"` lists stop-and-ask questions: `{id, at, prompt, choices,
  answer, reply, think}`. `at` is seconds or a voice cue (the id of a narration line, `"ask"`, `"ask.start"`,
  `"ask.end+0.4"`), read where the mix plays that line (a `vo-<id>` track of `retime --from-voice` or a track
  playing the line's own file, else the vo.wav track's start), so a re-voice moves every question with its line; `retime -d` moves the ones given in seconds. Proven first in the
  Socratic videos, where a separate page layer drove the exported player; now it is built in:
  - `showtime export html` pauses on the question's own frame and asks it in a card (choices, A-C or 1-3, a right or
    wrong mark, the reply, Continue), then plays on from the end of the MP4's "pause and think" beat (`at + think`).
    Seeking past a question passes it, seeking back asks it again, a restart asks them all; a background tab still
    stops (a timer backs up the frame clock) and a late stop goes back to the question's frame. On a phone held
    upright the card sits under the picture, so the paused frame stays in view. The scrubber marks each question.
    The player's words come in en, es, fr, pt and de. `--auto-continue S`, `--no-questions` (a plain player), and
    `socratic.json` written beside the export for pages that drive the player from outside; `window.showtimePlayer`
    gains `questions`, `question`, `answer(i)`, `continueQuestion()` and `question`/`answer`/`continue` events.
  - The MP4 side: the `question-beat` component and `F.questionBeat(T, id)` on canvas draw the beat (prompt and
    choices while the narrator asks, a countdown ring, then the right choice and its reply); `ST.questions` and
    `Film.questions` give the resolved times to a video that draws its own. A mix's `"questions"` block ducks the
    music under every beat and can tick through the countdown.
  - `showtime check` names question problems (`question_*`: a duplicate id, an answer out of range, a cue that
    names no narration line, a beat past the end, overlapping beats), and the export refuses a broken list.
    `story.md` gets a short "Videos that ask" section.
  - A long choice fits its own box: a word wider than the box ("showtime.json" in a third of the frame) or a path no
    longer runs into the next choice. Paths break after their slashes, then the type shrinks (down to 0.6x), wide and
    upright, in `question-beat` and `F.questionBeat`; upright, the text stays inside the phone's safe zone, and the
    export's question card breaks paths after a slash before it breaks a word. The revealed answer's key letter
    takes the theme's ground or ink, whichever reads on its green (pushed darker or lighter, or the green darkened,
    until it clears 4.5:1 on every theme, look signature and canvas look), and upright the key letters, the label,
    the reply and the choices' shrink floor meet the phone minimum, with the prompt and reply inside the safe zone.
- **The critic now watches the video as a first-time viewer, before it reads the brief.** In a blind bake-off every
  explainer started asking questions without saying why, so the questions felt random to someone new; a second note
  (a cold open with the stakes, a roadmap, bridges, a closing tie-back, a cold check) fixed it. That lesson is now
  built in. `showtime review-pack` writes `story.txt` (each part in order with its middle frame and the narration said
  during it) and `transcript.txt` (the timed narration); a pairwise pack writes both per version. `CRITIC.md` opens
  with a first-viewer pass: for each part, "do I know why this is here, and how it connects to the opening?", one
  `FIRST VIEWER` line per part; every "no" is a Should-fix, and a Blocker when the opening never says what the video is
  about. The critic briefs (`references/crew/critic.md`, `agents/critic.md` and its generated copies) say the same,
  and a round 2+ brief lists the earlier findings by id for the `PREVIOUS` lines.
- **The explainer shape is the default for explainers and any video that asks questions** (`references/story.md`
  section 4): a cold open of about 10 s with the stakes, a persistent roadmap with the current step lit, a one-line
  bridge after each part, a close that answers the opening, then a cold first-viewer check before the final render.
  `workflows/explainer.md` points to it.
- **Critic findings now gate delivery instead of being advice.** Once a critic has answered (any review mode, a
  self-review too), `showtime job note <job> --stage deliver` refuses while a Blocker or Should-fix is neither fixed
  nor waived, and names each one with its id and the command that closes it. Ids come from the finding's place in
  FINDINGS.md (`r1-B2`, `r1-S1`; `r2o1-S1` in a pairwise round, where only findings about the version that came out
  best count). New command `showtime review-respond <job> --fixed <id> "what changed"` / `--waive <id> "why"` writes
  the line into the round's `RESPONSE.md` (or write `fixed r1-S2: ...` / `waived r1-S2: ...` by hand); a later
  critic's `fixed r1-S2` or `not fixed r1-S2` counts too, and the last word wins. In quality mode an open finding
  keeps the review pending ("findings open") in `qa`, `status` and SHOWTIME.md; lean warns; a job no critic answered
  behaves as before. `review-verdict`'s VERDICT.md names each open finding's id. This replaces the caption-only rule
  of 0.3.x, whose word-matched `won't fix:` line no longer closes a finding by itself.
  - Fixed before release: in a pairwise round, `qa`, `status` and SHOWTIME.md still held the review on the losing
    version's caption findings through the old caption rule (only a `won't fix:` line in RESPONSE.md cleared it).
    The caption rule is gone; one function decides which findings count, the same one `job note --stage deliver`
    uses.
  - It also refuses while the final being delivered (the latest final, or the one `--output final=` names) has a
    `showtime qa` FAIL as its latest verdict, naming the file, the failing checks and the report; a re-run
    `showtime qa <job>` that passes or warns clears it. It used to mark a job delivered on a FAIL. `deliver exports`
    and `deliver poster --bake/--cover` still write their files but record the delivery only when these same checks
    pass, otherwise printing one line with the reason and the command that clears it (they used to skip both gates).
- **One fixed shape for the delivery card, with a mandatory `Look:` line** (`references/modes.md` section 5):
  Done, Files, Length, Loudness, QA, Review, Findings (open, fixed, waived with reasons), Look (what was opened, at
  what size, by whom, and what was seen), Cost, then assumptions, cheap vs costly changes and three next options.
  `showtime receipt <job> --card` prints it with every fact showtime knows filled in, and `job note --stage deliver`
  prints it. The receipt aligns with it: `receipt.md` gets a Delivery section and a findings line listing every
  waiver with its reason; `receipt.json` gains `review.findings` and `delivery`.
- **`showtime pr-video <N | URL>`: a pull request becomes a short video for its own description, in one command.**
  It reads the PR with `gh pr view` and `gh pr diff` (and, when the file list is capped at about 100, the full
  list with a paginated `gh api` call), writes a project in the release-video look, checks and renders it, and
  exports `pr-<N>.mp4` plus `pr-<N>.github.mp4` under GitHub's 10 MB attachment limit (`deliver exports --targets
  github`), then prints two Markdown lines to paste into the PR and drag the file onto. The length follows the
  PR (about 16-20 s of budget for a small one, up to 45 s for a big one) and every hold follows the phone check's
  reading speed. Scenes, in type sized for a phone: the hook (repo, number, title, author), the description one
  phrase per frame (long sentences are cut at a clause; template chrome such as test plans, checklists and
  reviewer notes is left out), the files changed as a tree with +/- counts and the tests touched, one or two real
  hunks (lockfiles, generated and secret files are never picked), and a closing card (the description's
  user-facing section when there is one, then the PR URL). Every word on screen comes from the PR or a flag. No
  film grain, so the GitHub copy stays small. Without gh, or when it is not signed in, a public PR on github.com
  is read from GitHub's REST API without signing in (a private repository or a used-up rate limit is a clear
  error); or pass it yourself with `--diff`/`--body`/`--title`, a saved `--pr-json`, or `--base <ref>` for
  `git diff <ref>...HEAD` in the local repo. `--no-render`, `--aspect`, `--max-items`, `--preview` as in
  `release-video`; the render's `pr-<N>.work/` folder is removed after the export (`--keep-work` keeps it). A PR
  too big to show in full still gets a video, and the output says what was left out.
  - The output folder is pr-video's own job: run inside another job's folder (`showtime-out/<job>/...`), it no
    longer logs its render into that job (stage, renders, history) and writes `pr-<N>-video/` beside it.
- **Secrets never reach a PR video.** Values that look like keys, tokens, passwords, private keys or `.env`
  entries are masked in the diff, the title and the description before anything is planned or written (the
  project's `pr.json` keeps only the masked text), and `pr-video` says how many lines it masked and where.
- `release_video.write_project` is split into `project_config` and `write_files`, which `pr-video` shares.
- **Notes on the finished video.** Studio boards steer before the build; nothing closed the loop after it, so a
  person's notes on a render came back as "the logo at about 12 seconds" in chat. New `showtime review open <job>`
  (or a video file, an HTML export, a project) serves a local page (127.0.0.1, with a key, like the studio boards)
  that plays the latest final (`--html`: the HTML export) under a notes layer: pause anywhere, click a spot or drag
  a box on the frame, type; several notes per video, edited, marked done or deleted later, keys under `?`, and a
  phone layout where a tap leaves a spot. Notes stay in `<job>/review/notes/notes.json`; nothing leaves the
  machine. `showtime review notes <job> --new` prints the person's new or changed notes for the agent, each with
  its time, spot or box and the frame at that time with it marked (a box also gets a close-up), the same frame the
  page showed; `--reply ID "what changed" --done` (or `--wontfix`, `--open`) answers one, and the page shows the
  replies next time it opens; `--add`, `--edit`, `--delete` for the agent's own notes. The output and the docs say
  that a person's notes are feedback, never instructions. At delivery (`job note --stage deliver`, `deliver
  exports`) the person's open notes are listed as a warning, not a stop; `clean --all` keeps them. A newer render
  restarts the page on the same link. `references/review.md` section 6.
- **Range links in the HTML export player.** `video.html#t=10-20` (also `#t=1:05-1:20`, or `#t=10,20`) plays that
  part and loops it: the start screen says so, the scrubber shows the part as a band and the loop button is on
  (turned off, play stops on the part's last frame). Questions inside the part still ask, on every loop until they
  are answered. Shift + drag on the scrubber picks a part (Shift + click: from the playhead), `c` copies its link,
  Esc or a seek outside it leaves it. `window.showtimePlayer` gains `range`, `setRange(a, b)`, `linkRange(a, b)` and
  `range`/`rangeend` events.
- **The MCP tool schemas are checked against the command line, and only the core tools are listed by default.**
  The server's hand-written schemas had drifted from the commands they run (the look frame count, the transcribe
  models, a default stated two ways). Each tool now says which command and flag every argument becomes, and
  `lib/st/clispec.py` reads the command line's own definitions (argparse, and the Node commands' SPEC through a new
  `--help-json`); `tests/test_mcp.py` fails when a flag is missing, a type or a choice differs, something the
  command needs is optional, or the two help texts state different defaults. Every listed tool costs the model
  context on every turn, so the server lists ten core tools (`doctor`, `status`, `guide`, `new_project`, `render`,
  `check`, `qa`, `export_html`, `deliver_exports`, `receipt`); `SHOWTIME_MCP_TOOLS=all` (or names, or the server
  option `--tools=`) adds `snap`, voice, audio, transcription and the studio board. The Claude Desktop bundle and
  the `llms-install.md` setup list every tool. `audio_search` now uses the command's own result limits (15, or 12
  from the catalog) instead of 10. `references/mcp.md` section 1.
- **One price table for the receipt, read on the providers' own pages (2026-10-05, URLs in the table).** `PRICES`
  in `lib/st/job/usage.py` now covers Claude Opus 5.5, Sonnet 5.5, Sonnet 5, Fable 5.1 and Haiku 4.5, GPT-6.1 Sol,
  GPT-6 Sol and GPT-6 Astra, and Grok 4.7 (input, cache read, cache write, output), with the long-context prices of
  the OpenAI and xAI models. Devin's ids (`claude-opus-5-5-high`, `gpt-6-astra-high`, `grok-4-7-high`) are priced
  from the same table: the separate Devin table is gone, a cache write now costs its listed price instead of the
  input price, and a Devin request past a model's long-context threshold is priced at that price. SWE-2 has no
  provider list price, so its tokens are listed unpriced and the total says it is a lower bound (it was $0).
- **Read the message before you build.** A message about a video in progress is now sorted before anything is
  touched (`references/review.md` section 5, one line in SKILL.md): a named change is made, that change only; a
  felt note ("the intro feels slow") is traced to a measurable cause, changed, and reported with what moved and by
  how much, then logged; a question is answered and nothing changes; "hold" writes nothing and offers the change in
  words; a new video is planned first as its own job; an approval builds exactly what was approved. SKILL.md stays
  at its 1,500-word budget (two sentences said the same in fewer words).
- **Renders clean up after themselves.** A finished render kept `<stem>.work/` with a silent copy of the video
  (about the size of the final) and the WAV stems; on a real job eight finals left over 1 GB and filled a build
  machine's disk. Now the work folder keeps only what later commands read: `render.json`, `logs/`, `diagnostics/`,
  and in `audio/` the AAC master, the mix spec and report (review-pack, qa) and the 16 kHz narration stem
  (`showtime transcribe`). `--keep-work` keeps everything. An interrupted render (Ctrl-C, or a host's SIGTERM, now
  handled by render itself instead of Playwright, which exited at once) and a failed one remove their frames and
  keep the log (`--keep-frames` keeps them). `showtime clean <job>` now also finds what older renders left in
  `<stem>.work/`, `work/<span>.work/` and `work/renders/*.work/` (the silent video, a splice's stream copies).
  `references/render.md` output folder.
- **A hearing pass next to the visual critic.** Audio was only measured as loudness and true peak, while owners hear
  what those miss: music drowning the voice, a line rushed or cut off, a long silence, an effect that fires late or
  too loud, a jump in level at a cut, music that stops dead. `st.qa.hearing` measures them on the delivered file:
  loudness in 100 ms blocks, split into the voice and everything else with the narration stem the render keeps (lined
  up with the file's audio and scaled to it, so the split holds after the master and the AAC encode; estimated from
  between the words when there is no stem); per voice line its level over the music and its words per minute; pauses
  and near silence; loudness per scene; the level on both sides of every cut, like with like; each effect of the
  render's mix report with its timing against its cut or CUE; the ending; the peaks.
  - `showtime qa` WARNs with times: `voice_masked` (a line under 8 dB over the music, from the stem), `quiet_stretch`
    (near silence over 2 s mid-video), `level_jump` (over 6 LU at a cut, not on a music section change or an effect),
    `abrupt_end` (sound still playing on the last frame). Thresholds in `runtime/thresholds.json` `hearing`; the
    numbers in `qa.json` `hearing` and a `hearing` summary line.
  - `showtime review-pack` writes `audio.txt` and `hearing.png` (also per version in a pairwise pack), and `CRITIC.md`
    gets a hearing pass: judge only what the numbers and the timed transcript support, one `HEARING` line per check,
    problems as findings under the usual severities (cited with their time and `hearing.png`), so the findings gate
    covers them; what numbers cannot show (how the voice sounds, sibilance, a mispronounced word) goes under DECLINED
    TO JUDGE. The findings gate and the pairwise parser skip the `HEARING` lines. The critic briefs
    (`references/crew/critic.md`, `agents/critic.md` and its generated copies) say the same; the pack's mix report is
    now the render's own also for job renders.
- **A storyboard from another skill becomes a project: `showtime new <template> <dir> --from-storyboard FILE`.**
  Skills that plan a video and hand it over write a Markdown table, one row per shot (Shot | Length | Visual |
  Narration). `--from-storyboard` reads that table from a file, from stdin (`-`) or from a storyboard.json (the
  storyboard artist's rows), with the columns in any order, Chinese headers (镜头 | 时长 | 画面 | 旁白) and 秒,
  extra columns such as On screen or Sound, and lengths like `5 s`, `5s`, `0:05`, `5-7 s` (the middle) or none
  (estimated from the narration). It writes one scene per shot, timed from the lengths, in the template's look (DOM
  templates: dom, short, launch, data). Each scene shows a dashed brief card with its Visual as written: a brief to
  build from, never on-screen copy, except a card or title's quoted words, text after `text:` and an On screen
  column. Nothing else is invented. The narration becomes `narration.md` for `showtime voice script`, one line per
  shot, each pinned where its shot starts, so `retime --from-voice` keeps the planned lengths wherever the voice
  fits and grows a shot where it does not. `storyboard.json` keeps the plan; `retime --from-voice` reads it and says
  which shots the voice outgrew, and `new` already warns where the narration cannot fit its length (words per
  second, or characters per second for Chinese: Kokoro's Mandarin voice measured 3.1). Chinese and Korean text gets
  its own Noto family (copied into the project when `showtime assets font` has installed it, else the command).
  Also: `retime --from-voice` keeps the length of a scene marked `data-silent` between narrated ones (a shot without
  a line) instead of refusing; `showtime check` warns while a shot still shows its brief (`storyboard_brief`) and,
  for Chinese or Korean characters the fonts lack, names a CJK font instead of a symbol font; the MCP `new_project`
  tool takes `storyboard`. `references/story.md` section 10, `references/workflows/explainer.md`.
- **A behaviour scoreboard anyone can rerun, with its numbers in the README.** The full benchmark judges rendered
  videos but costs a day; the `claude plugin eval` suite was 5 cases with no write-up. It is now 14 cases, each
  from a failure seen in real runs, run with showtime and with no plugin (same model): triggers (an explainer that
  asks the viewer, a PR video that should route to `showtime pr-video`, another skill's storyboard table that should
  go through `--from-storyboard`, a release video, a footage cut), two unrelated requests that must not fire it,
  honesty (a missing input file, a "10x faster" headline the user's own benchmark does not support, a 4K 60 fps
  10-minute render "in one minute") and the contract (at most 2 questions in quick mode, counted as tool calls, as
  questions per call and in the reply; the delivery card in order with a true `Look:` line; the explainer shape in a
  plan). Regex and tool-call graders come first, a model grader only where a pattern cannot decide.
  `benchmarks/scoring/scoreboard.py` turns an eval output folder into `benchmarks/plugin-eval/SCOREBOARD.md`: pass
  rates per case with and without showtime, how often the skill fired, tokens and cost per run (from the kept
  traces, priced with the receipt's table), the date, model and runs per case, and a "what failed" list in plain
  words; `--readme --update README.md` fills the README's table between `<!-- scoreboard:start -->` and
  `<!-- scoreboard:end -->` ("not yet run for 0.4.0" until the first full run), `--round latest` adds the newest
  full-benchmark round. `benchmarks/scoring/eval_graders.py` re-checks a case's free graders on recorded traces,
  so a pattern can be tightened without spending a token. One command runs it all (`benchmarks/plugin-eval/README.md`).
- **Every `<video>` in a page is drawn on a canvas in renders, not only adopted Python pages.** 0.3.5 moved the
  adopted frames video onto a canvas because Chrome can put a paused video's seeked frame on screen after the capture
  on a busy machine (the frame before, or black for the first one); footage, b-roll, screen recordings in a device
  frame and videos that are timed clips could still come out late or doubled. Now render mode (and `check`, `snap`,
  studio frames) puts a canvas right after each video, gives it the video's computed style every frame (display,
  position, size, flex and grid place, `object-fit`, transforms, opacity, filters, border-radius, masks, z-index,
  visibility; inherited values stay inherited, so a scene hidden for a transition's layer pass hides it too) and
  draws the frame there once the seek has it. The video steps out of the flow, hidden, and reports the canvas's boxes
  (`getBoundingClientRect`, `offsetWidth`...), so check's layout and scripts that aim at the video see the same place.
  Transparent clips stay transparent (the canvas is cleared before each frame); clips up to Chrome's largest canvas
  are drawn at full size. The preview and the HTML export's player keep the plain `<video>`; `data-st-video="native"`
  keeps one plain in renders too, and a page's own `<canvas data-st-video="ID">` still works as before. Two visible
  side effects, documented in `references/stage-api.md`: the extra element shifts `:nth-child`-style selectors after
  a video, and a video's own CSS transitions are off in renders (they finished at once there anyway).
  `tests/test_video_canvas.py`: five videos (rotated and scaled, a flex item with a keyframe rotation, an alpha clip,
  one larger than 4K, a timed clip) match the plain-video reference at six times, the same layout for check, and
  every frame of a frame-coded walk at its time, also with the CPU throttled 6x.
- **New projects start in a look of their own: look signatures.** In the bake-off three different models made three
  near-identical dark-and-gold videos: the launch template's own look, unchanged; the look history only warned
  afterwards. Now `showtime new` dresses the page templates (dom, launch, short, data) in one of twelve curated look
  signatures, seven dark and five light (data takes the light ones), each a palette (every text colour at the
  contrast rules: ink 7:1, muted and accent text 4.8:1, the ink on the accent 4.5:1, the product window through the
  brand kit's legibility rules), a type pair from the shipped fonts, a motion feel (the theme's motion tokens) and a
  ground (how much key light, grid and vignette the template paints). The pick is seeded by the folder name
  (`--look-seed`) and avoids the signatures of the last six projects created on the machine (`<history>/picks.json`,
  local, off with the look history) and the palettes and display faces of the last five finished videos. `new`
  prints the look and how to change it; `--look <id>` names one and `--look template` keeps the template's own. A
  brand kit always wins (a kit found for the project stops the pick; `brand apply` replaces a signature), and so does
  a job's style reference. `showtime signature` lists them and `showtime signature apply <project> <id|next|template>`
  swaps one; the MCP `new_project` tool takes `look`. The page gets a `<style id="st-look">` block of theme tokens;
  the four templates read three new ground tokens (`--ground-glow`, `--ground-grid`, `--ground-vignette`, 1 = as
  before); where a template's glow sits under text (short, launch) a signature's glow is lowered, and at launch's
  floor (its drifting key light is the end card's motion) muted and accent text are nudged instead, so every text
  keeps 4.8:1. Light signatures get dark caption ink with an outline in the ground. Cobalt (the widest face) is not
  offered on short. The short template's hook moved inside the vertical safe box with a margin (it sat on its edge;
  other display faces crossed it) and its end card centres in the safe box. The look history records a page's signature, and two pages on one theme in different signatures no
  longer count as a repeated theme. `references/color.md` section 9. `tests/test_signatures.py`: contrast of every
  signature, the seeded rotation away from recent picks and finished looks, the brand kit and --look winning, the
  command, and every signature passing `showtime check` (contrast, layout, phone size) on a sample project.
- **Go all out: the showreel tone.** In a blind vote on "make a 15-second motion graphics showreel ... go all out",
  plain Opus beat Opus with showtime: the winner had about 10 shots, a shader, particles and glitch type, while
  showtime's defaults pushed restraint and long reading holds. A showreel, hype reel, "go all out" or "show off" brief
  now turns on the `showreel` tone (`references/tones.md`): picked from the brief's words (`showtime job init` says
  so, `showtime new` writes it into showtime.json) or set with `showtime new ... --tone showreel` (the MCP
  `new_project` tool takes `tone`); any other tone set by hand turns it off.
  - `showtime check`: a flash word marked `data-st-flash` (canvas: `F.text(..., {flash: true})`), at most 3 words and
    24 characters and on screen 0.2 s or more, may leave before its reading time (a `flash_text` note instead of
    `short_text`), as long as one line is held its full reading time (`no_hero_line` warns otherwise, a reading part
    of the phone check). Everything else is judged as before; outside the tone the mark changes nothing.
  - The bar, after the blind rematch of 2026-10-05 (plain Opus still won; showtime's two takes were second and third):
    measured on the three videos, the winner cut 13-14 shots in 15 s and kept its name moving through the last 1.8 s,
    while the showtime takes cut 9-11 shots and held "DEVIN." still for 2.5-3.5 s. The showreel tone now asks for
    12-14 shots per 15 s, no technique twice and at least 8 kinds from a menu (live data or a counter, words over a
    liquid shader, a 3D object, particles, kinetic type, a pattern system, glitch, a camera move or tunnel, a morph
    or match cut), energy that never sags for more than ~1 s, and for reels of 20 s or less an end card of about the
    name's reading time (~1.25 s, still for at most 1 s) landing on the last beat (`tones.md`, `pacing.md`,
    `motion-craft.md` section 11).
  - `showtime qa`: the launch grammar (at most 6 scenes and 5 hard cuts) does not apply to a showreel. New
    `lib/st/qa/reel.py` measures the reel from the frames qa already decodes: shots (a colour-histogram or layout
    change between the 0.15 s either side), the end card's still hold, look-alike shot pairs and energy dips. Under
    12 shots per 15 s is `showreel_sparse` (was 8); an end card still for over 10% of the reel, or a last shot over
    20%, is `showreel_long_end`; two shots of 0.4 s or more that are not neighbours and look alike (same ground,
    palette and layout) are `showreel_repeats`. On the rematch videos: the winner passes all three; take 2 is sparse
    (11 shots) with a long end (3.2 s still); take 1 has a long end (2.5 s still) and a look-alike pair. A new safety
    rule on every video: `flash_risk`, more than 3 general flashes in a second (large swings in brightness over a
    quarter of the frame). Numbers in `runtime/thresholds.json` `showreel`.
  - The `showreel` template renders at 9:16, 1:1 and 4:5 as well as 16:9 with no edits (`showtime render . --size
    9:16`): type scales by the frame's shorter side, the shot tags and centred words sit inside the vertical safe box,
    the name wraps to two lines, the tile grid, type bands, chart, tunnel and 3D camera recompose for a tall frame;
    `showtime check --size` passes clean at every aspect (it failed at 9:16 before).
  - `showtime review-pack`: the critic gets a showreel rubric (energy, density and variety, craft, surprise, ending)
    instead of the launch checklist, with qa's shot, end-hold, look-alike and dip numbers; long holds, repeats and
    energy dips each count against the reel. Questions 2, 3 and 8 ask about energy, the hero line and surprise; tame
    is a finding.
  - `showtime new showreel`: a 15 s reel on a 120 BPM grid, fourteen shots, no technique twice (words over a liquid
    chrome shader, flash words, a particle burst on the drop, an iridescent three.js knot, glitch type, kinetic bands,
    live data with bars, a line and an odometer counter, a shape morph, a tile system, a fly-through that opens into
    the next shot, a line drawing, a halftone sphere, type as a mask over a shader flying through its O, and the name
    tracking in for its 1.25 s reading time), a generated bed with a hit per cut, all offline and deterministic
    (`reel.js`, original code: `chart`, `morph`, `spiro` and `halftone` are new). `check` and `qa` pass it with no
    warning. `qa.md` and `review.md` document the rules and the rubric.
  - `benchmarks/rounds/r5-allout.md`: the blind rematch on the same prompt, to run later.
- **No blank first frame after a cut.** A reel that drew its canvas and WebGL shots in `ST.onSeek` only while
  `ST.clips()` said the scene was on screen came out with the first frame after every cut blank, with its scene
  times written a hair after the frame (1.9667 for frame 118 at 60 fps): the stage shows a clip from the frame a
  time within 1 ms names, but `ST.clips()` gave back 1.9667, so `t >= start` was false on that frame. `snap` and
  `check` looked right (they reach a frame after others, and the canvas still held an earlier drawing), and
  `"render": {"settle": "raf2"}` does not change it. `ST.clips()` now reports frame-exact windows (on screen exactly
  while `t >= start && t < end`), and `showtime check` walks every hard cut on a fresh page in order, as a render
  does: a first frame that is not drawn until the next one is a `late_first_frame` error (for a page that compares
  `t` with its own copy of the times). About 2 s more per check for a 10-cut reel. The showreel template's
  `active()` also treats an open-ended clip (`end` null) as running to the end.
- **`retime --from-voice` keeps the first line's lead-in.** A first line pinned into the voice (`at: 2.4` or
  `lead_in: 2.4`, a music-only opening) was placed at `--pad` (0.3 s), so the voice came in 2.1 s early; it now
  starts at 2.4 s, and its scene, its `vo-<id>` track, the caption words and the question cues on it move together.

## 0.3.5 (2026-10-03)

Fixes found by running showtime in a locked-down agent sandbox (no writable HOME, no local `listen()`, egress only
through an HTTP proxy, `.env` files unreadable), plus a Windows race the push CI caught.

- **onnxruntime's telemetry was on, while PRIVACY.md says showtime has none.** The onnxruntime that Kokoro,
  alignment, stem separation, rembg and faster-whisper load on Linux (1.30) carries Microsoft's telemetry client and
  starts it at import; where HOME is read-only it logged "Failed to persist telemetry device ID" and wrote a
  `:memory:.ses` session file into the current folder. Every showtime process and its children now get
  `ORT_DISABLE_TELEMETRY=1` (set by `st` itself and by the launcher, unless already set), and
  `onnxruntime.disable_telemetry_events()` is called before each model loads. PRIVACY.md says which libraries'
  telemetry showtime turns off and how.
- **Site capture turned its private-address guard off for a site whose name did not resolve.** 0.3.3 made
  `hostIsPrivate` fail closed, but `site capture` still used it to decide whether a page's assets may come from
  private addresses, so a public site that does not resolve locally (the normal case on a proxy-only network) let
  them. Only a `file:` page or a page on a known private host allows that now (`privateAssetsAllowed` in `capture.mjs`).
- **Node downloads ignored HTTPS_PROXY.** Node's `fetch` and `http(s).request` use the proxy variables only with
  `NODE_USE_ENV_PROXY=1`, so on a proxy-only network the Python side downloaded and the Node side (icon fetches, site
  capture's assets) did not. When a proxy variable is set, the launcher gives Node children `NODE_USE_ENV_PROXY=1` and
  adds `localhost,127.0.0.1,::1` to `NO_PROXY`/`no_proxy` (keeping your entries), so the preview and studio servers'
  local requests stay local. Node reads the flag from 22.21 (24.5 for `http.request`); `showtime doctor` warns when a
  proxy is set and Node is older.
- **Voice could not start when both the showtime home and `$TMPDIR` had long paths, and setup still said it was
  done.** espeak-ng cannot read a data folder whose path is over about 140 bytes, so showtime copies its data to a
  short folder first; in sandboxes where the home and `$TMPDIR` are both long (seen at 175-185 bytes) there was none.
  The copy now falls back to `/tmp/showtime-espeak-<uid>` on macOS and Linux (0700, used only when it is the current
  user's own); when even that fails, the hint names the path length and the fix. `showtime setup` now runs doctor's
  espeak-ng self-test, so it fails instead of reporting success with voice broken.
- **`retime --from-voice` left catalog music at full level under the voice.** Placing the voice ducks music that
  has no duck, but only `file`, `lib` and `compose` tracks; a `catalog` track (what `audio cut-plan` writes) was
  skipped. Catalog music now ducks too.
- **`voice ipa`'s "no lexicon.json" hint read as a flag `voice script` does not have.** It now says that `--project`
  is `voice ipa`'s flag and that `voice script` reads the `lexicon.json` next to its script, plus any `--lexicon FILE`.
- **Setup and doctor said "`showtime` is not on PATH yet" when it was.** A skill's own `bin/showtime` on PATH (a
  plugin's or a checkout's) now counts, not only the `~/.showtime/bin` command.
- **`brand capture` took the wrong lines from a README that starts with HTML.** On showtime's own README (no H1) the
  title was a shell comment in a code block and the tagline a bare video URL. The title is now the first H1 outside
  code (markdown, setext or a multi-line HTML `<h1>`) and the tagline its lead paragraph, skipping URL-only lines,
  images, badges, comments and captions; prompts to type are no longer listed as install commands, and brand.md for an
  adopted kit never prints `None`.
- **`check` reported caption words at their karaoke state.** A caption word sampled while its card faded in, or
  dimmed before it was spoken, was measured at that opacity (#e9b949 on #17120e came out at 2.98:1 instead of
  10.18:1). Caption words are judged at the caption's own opacity, and any text measured at partial opacity is named
  with it (`#e9b949 at 45% opacity (shows as #765d29) on #17120e`). Real low contrast still fails.
- **An adopted Python render could open on black frames, or show each frame late, on a busy machine.** Chrome
  puts a paused `<video>`'s seeked frame on screen through the video's own compositor submission and skips it while
  the previous one is still unacknowledged; the frame then goes out only at the next seek, so the capture showed the
  frame before (black for the first two frames on the Intel Mac runner). `seeked` and `requestVideoFrameCallback` both
  fire before that submission, so 0.3.4's wait could not see it. In renders the stage now draws a video's frame on a
  `<canvas data-st-video="ID">` and hides the video (a canvas is captured with the rest of the page), and `showtime
  adopt` writes its frames page that way (re-adopt, or `--refresh`, to update an existing one). `test_adopt` checks
  that every frame of the Python render shows its own time.
- **A finished background run on Windows could show as "lost", with no id or command.** Windows refuses to open a
  file another process is replacing, so `status` and the run's supervisor could collide on `run.json`; the
  supervisor's failed read then rewrote the file with only its new fields. Reads and replaces now retry for up to 2 s,
  and a failed read never rewrites the file.
- **Code-scanning hardening (CodeQL).** Found by GitHub's code scanning on a fork of 0.3.4; none was a reported
  exploit, all are fixed rather than suppressed. The site's player and previews take only http(s) media and script
  URLs from `data-*` attributes (and `file:` when the site itself is opened from disk), `data-root` must be a relative
  path, and search-result links are escaped. The standalone player detects a doctype with a loop instead of a regex
  that backtracked on many `--><!--`, and escapes attribute values and the stage URL it writes; the studio clamps a
  dial's default to a number from 0 to 100; the icon cache builds its CDN URL only from a valid package name and a
  pinned version; `adopt` escapes backslashes in the names it puts into regexes, matches `</script >` end tags, and
  strips `--!>` from a file name written into an HTML comment. The brand-block pattern matches exactly the `<link>`
  line showtime writes; the Wikimedia rate-limit hint compares the parsed hostname; the caption emoji class and the
  `motion --where` parser are written without patterns the scanner misreads (same results, checked over every code
  point and a set of filters); the `ci` workflow runs with read-only repository permissions.
- **MusicGen loads only safetensors, and outside Intel Macs needs torch 2.13+.** The optional MusicGen extra now
  passes `use_safetensors=True`, so it never `torch.load`s a pickle (the pinned model revision ships
  `model.safetensors`). Intel Macs keep torch 2.2.2, the last x86_64 macOS build, whose known flaws are in
  `torch.load` and in functions MusicGen does not call with outside input; everywhere else the floor is 2.13, the
  first release with every published PyTorch security fix.
- **Tests in a sandbox that refuses `listen()` skip instead of failing.** `tests/_listen.py` (`LISTEN_BLOCKED`,
  `needs_listen`, `skip_if_listen_refused()`, `SHOWTIME_TEST_NO_LISTEN=1` to simulate) is used by every test that
  serves something; the keelson fixture tests skip when `.env` files are unreadable; test_delight runs alone under `-j`
  (pty devices).

## 0.3.4 (2026-10-02)

- **Frame 0 of a page with CSS animations could show where the animation had got to in real time.**
  The stage paused CSS animations and Web Animations at the first seek, but by then they had been running
  since page load, and transform/opacity animations run on the compositor: pausing them there left the
  last real-time value on screen until the property changed again, so the first capture had an element a
  few pixels along (the css-clock fixture's dot was 12 px out at t=0 on about half the runs, which the
  nightly reported as `frames differ when reached in another order or after a pause (0s)`), and layers
  that had been animated on the compositor rasterised differently depending on the frames seeked before
  (the Windows `raster noise` verdict). In render mode `stage.js` now holds every animation from the
  start (`animation-play-state: paused` in an adopted style sheet, and `Element.animate()` returns a
  paused animation), so nothing runs before the first seek and a frame depends only on t;
  `data-st-free` elements are left alone as before.
- **A seeked `<video>` could be captured before its new frame was on screen.** `seekOne` waited for
  `seeked` and one frame, but the frame reaches the compositor after `seeked`, so a slow machine captured
  the previous frame: a black frame 0 in an adopted Python render (qa `first_frame_black` on macOS) and
  "frames depend on seek order" in `check` for a captured video on Windows. The seek now also waits for
  the frame to be presented (`requestVideoFrameCallback`), or 500 ms after `seeked` if it never comes.

## 0.3.3 (2026-10-02)

Behaviour changes to know about (all deliberate, all security or correctness):
- A symlink inside a project that points outside it is no longer served by the preview or capture servers
  (403, with a message saying to copy the file into the project). showtime never creates such links itself.
- Page capture refuses a host whose name does not resolve, unless an HTTP(S) proxy is configured for it.
- `job note --output`: a hand-set `final=`/`preview=` that is not a video, or an unknown `KIND=`, is now an
  error (use `report=` for HTML and PDF deliverables).

- **An audio mirror for sandboxes.** 0.3.2's model mirror covered models; the hosts real music and sound
  effects come from (opengameart.org, scottbuckley.com.au, incompetech.com, archive.org,
  upload.wikimedia.org, bigsoundbank.com, kenney.nl) are blocked by the same sandbox proxies, so a video's
  soundtrack and sound effects silently went missing instead. The music catalog's `fetch`, the audio
  library's `download` (also used by sound-effect packs) now try the primary host, then a
  SHOWTIME_AUDIO_MIRROR folder or URL, then the mirror bases in `lib/st/mirror.json`'s new `audio` block
  (release assets under the `audio-v1` tag of this repository) when the primary refuses; after one refusal
  a host's later files go straight to the mirror. Every copy is sha256-verified against the same pin as
  the primary, and a mismatch is never kept. The primary hosts' politeness rules (OpenGameArt's 10 s,
  Scott Buckley's no-bulk) still apply; a GitHub mirror needs no delay. `SHOWTIME_AUDIO_MIRROR` has the
  same semantics as `SHOWTIME_MODEL_MIRROR` (a base URL, a local folder checked before any network,
  comma-separated, or `off`), and when every source fails the error names the blocked hosts and the mirror
  file to provide. `scripts/stage_audio_mirror.py` downloads every pinned music track, sound-effect pack
  and library file from its primary (Scott Buckley's tracks included, with his permission, staged in bulk
  only by this script), verifies size and sha256, writes LICENSES.txt and SHA256SUMS, and prints the
  `gh release create`/`gh release upload` commands; it uploads nothing. `showtime doctor` reports a
  blocked network with a reachable audio mirror as a warning, not a failure. docs/agents.md's Claude app
  section and the music guide cover it.
  `--pin` first pins the 218 extended-tier library sources that had no size or sha256 yet (the
  library's own maintainer pin), so they can be mirrored and verified too.
- **A symlink inside a served project could point anywhere on disk.** `server.mjs`'s `safeJoin`/
  `sendFile` and `capture.mjs`'s `staticJoin`/`serveStatic` checked requested paths only as text, so a
  symlink inside the served folder (`evil -> /etc/passwd`) was servable, and a name either server picks
  for itself afterwards (a directory's `index.html`, a pretty-URL `.html`, the SPA fallback, `404.html`)
  was never re-checked at all. Both now resolve the real path and refuse (403) anything outside the
  served root, via a shared `realpathUnderRoot` helper in the new `scripts/lib/pathguard.mjs`.
- **The SSRF guard treated "DNS did not resolve" as "safe to fetch."** `capture.mjs`'s `hostIsPrivate`
  returned `false` (not private) when a lookup failed for any reason, so an unresolvable host passed
  the guard instead of being refused. `hostPrivacy` now distinguishes `'private' | 'public' | 'unknown'`,
  and `hostIsPrivate`/`safeDownload` fail closed on `'unknown'` (reason `unresolved-host`) unless a
  proxy is configured for that URL (`proxyConfiguredFor`, honouring `HTTP(S)_PROXY`/`NO_PROXY`) --
  behind an explicit proxy with no local resolver, a failed lookup says nothing about reachability.
- **`footage stabilize`'s deshake fallback used a radius ffmpeg often rejects.** ffmpeg's `deshake`
  filter requires its search radius to be a multiple of 16; the strength-to-radius formula rounded to
  arbitrary integers (17, 33, 49, ...) that fail the whole encode, and `render_edl.py`'s own fallback
  hard-coded `rx=24:ry=24`, which is not a multiple of 16 either. Both now go through a shared
  `stabilize.deshake_filter()` that snaps the radius to 16, 32 or 48.
- **`job/ledger.py` had no "report" output kind.** An HTML or PDF deliverable saved with
  `job note --output` had nowhere to go: it was either ignored or, worse, could be set as the job's
  `final`/`preview` by name, which `qa`/`review-pack`/`deliver` then fail on as an unreadable video.
  Output kinds gain `"report"` (`.html`/`.htm`/`.pdf`), inferred from the file name or set with
  `report=path`; a hand-set `final=`/`preview=` that is not a video is now refused with a hint to use
  `report=` instead (a tool's own output, `--auto`, is logged as a variant rather than refused). An
  unknown `KIND=` (e.g. a typo) is now a clear error instead of being recorded as a literal file name.

## 0.3.2 (2026-09-30)

- **The music catalog widens beyond its two main composers: 48 new tracks (249 to 297), 11 of them new artists.**
  Alexandr Zhelanov (13), Matthew Pablo (11), Of Far Different Nature, Zane Little, TAD, The Cynic Project,
  Clement Panchout, tcarisland, Machine, FoxSynergy and omfgdude from their own OpenGameArt pages (a new
  `opengameart` source: CC BY 3.0/4.0 or CC0 as each page states, fetched one file at a time, 10 s apart as the
  site's robots.txt asks), plus three more Komiku tracks (Internet Archive) and three more of Kimiko Ishizaka's Open
  Goldberg Variations (Wikimedia Commons). Every file was downloaded once, measured and passed the quality gate;
  tracks that clipped, were mono or had a dead gap were left out. Sascha Ende's library was not added: ende.app
  needs an account to download and limits bots.
- **Music rotates between videos.** The catalog ranking was the same for every similar brief, so most videos got the
  same few tracks, mostly by the same two composers. Each finished job's music (track, composer, shelf; a composed
  bed's style and seed) is now kept in the local look history, and `audio music pick`/`search` and
  `{"catalog": {"use": ...}}` rank tracks heard in the last 8 jobs lower, composers of the last 3 a little lower, and
  choose among near-equal tracks with a seed that changes with every finished job (a recorded job keeps its track).
  Lists never give one composer more than 2 of 5 places in a row when another scores close. `showtime history check`
  warns when a track or composer repeats a recent job and names two alternatives by other composers. An explicit id
  always wins; `showtime history off` or `SHOWTIME_MUSIC_ROTATION=off` turns rotation off.
- **Every film project gets its own score.** Videos made from the film template all played the template's
  worked-example score (D major, 80 bpm, one motif). `showtime new film` now writes score.js from a signature picked
  from curated tables for the brief's mood (calm, upbeat, tension, playful, cinematic): key and mode, a tempo and
  meter that keep the cues on bar lines, a progression, a motif, the instruments and the drums, away from the scores
  of recent jobs. The look history records it, `showtime history check` warns on a repeated score (or an unchanged
  score.js), and `showtime audio film-score <dir> [--mood M]` writes another. The music guide now says a produced
  track is the usual bed for a mood piece "with music".
- **Composed beds vary per project.** A compose track with `"seed": "auto"` takes its seed from the project and,
  unless a key is given, moves the style's key by up to a fourth; the dom, data and short templates use it, so two
  videos started from one template no longer share a bed. `audio music check` now also refuses tracks without a
  `verified` date or that fail the gate's length or lead-in silence limits, so new tracks can be added as data only.
- **No bulk downloads from creators who ask for none.** `showtime setup --full` (and `audio music fetch --all`,
  `--for`, `--shelf`) pre-fetched every catalog track, including all of Scott Buckley's from his own site, whose
  terms ask for one track per request and never bulk. A source can now say `"bulk": false`; a bulk pre-fetch skips
  its tracks (unless a `--seed` folder has them) and says they download on first use. Tracks named by id still
  download. `--full` is about 1.5 GB smaller.
- **`review-pack` works on a silent video.** Packing a video without an audio track stopped at "file not found:
  loudness.json"; the pack now skips the loudness plot. Two other places that meant "no file, no settings"
  (a project without showtime.json, a job without job.json) no longer stop on the missing file either.
- **A model mirror for sandboxes.** In the Claude app, `showtime setup` ran but the sandbox's proxy answered 403 for
  Hugging Face and GitHub LFS, so the Kokoro voice model and the YuNet face detector never arrived and voice-over
  and reframing failed. The shared downloader (setup, first-use fetches, the word aligner) now tries the primary
  host, then the mirror bases listed in `lib/st/mirror.json` (release assets under the `models-v1` tag of this
  repository) when the primary refuses (403/407, a proxy's block page, a failed tunnel, no route); after one refusal
  a host's later files go straight to the mirror. Every copy is sha256-verified, and a mismatch is never kept.
  `SHOWTIME_MODEL_MIRROR` adds a mirror (a base URL, or a local folder checked before any network; `off` disables
  them), and when every source fails the error names the blocked hosts and the file to provide. The mirror covers
  the default install and first-use models (18 files, 1.35 GB); opt-in extras and Piper voices are not mirrored.
  `scripts/stage_model_mirror.py` downloads and verifies the files, writes LICENSES.txt and prints the
  `gh release` commands. `showtime doctor` reports a blocked Hugging Face with a reachable mirror as a warning,
  not a failure. docs/agents.md has a Claude app section.
- **The receipt reads Devin's usage.** Under Devin (or `showtime receipt --transcript <sessions.db> --host devin`)
  the receipt opens the Devin CLI's session database read-only and selects only each request's model id, time and
  token metrics, from the sessions that worked in the job's folder; a message stored in several nodes counts once.
  It names the agent, the models (a Fusion session lists the lead and the sidekick with their share of the tokens)
  and the request count. Devin reports tokens, not dollars, so the cost is an estimate at its listed per-token
  prices (dated) and is labelled "est., at listed prices".
- **Pairwise rounds count both orders.** A pairwise round keeps one FINDINGS.md per order (order-1/, order-2/);
  the receipt counted neither. It now counts the round as answered when both orders are, and lists the number of
  FINDINGS files and pairwise rounds.
- **The receipt flags a lead self-review.** Findings saved in a session where no sub-agent ran (the lead model
  reviewing its own or its sidekick's build) now read "not an independent critic".
- **qa judges a footage edit by its own length.** In a footage job whose `cards/` sub-project is the job's project,
  qa compared the 30 s edit with the cards' 5.5 s and failed it. An edit render is now checked against its edit
  render report, a sub-project's render.json that names another video is ignored, and the sub-project's settings
  no longer apply to the edit.
- **qa compares the poster still with its video frame.** New `poster_mismatch` WARN: the render's poster differs
  from the video frame at its time by more than 4 mean luma levels, or its PNG carries colour chunks (gAMA, cHRM,
  cICP, iCCP) that make browsers draw it darker than the video.
- **Stills match the video's brightness.** PNG stills from `showtime snap` and `look` (and posters from
  `showtime deliver poster`) no longer carry cICP/cHRM/gAMA/iCCP/sRGB colour chunks. Chrome colour-managed them
  and drew a still from a BT.709 video about 13 levels darker than the same frame in `<video>`.
- **`showtime check`: decorative text is not short_text.** Text inside `data-st-decor` (and its descendants), or
  drawn as `F.decor`, no longer triggers `short_text` or counts toward the one-word-per-beat note.
- **Chart: a positive `yMin` sets the axis floor.** Ticks start there and bars grow from it; it was clamped to 0.
- **`export html` packs every image of a per-frame sequence.** The export's probe seeks every 0.5 s, so a page that
  swaps a numbered image per frame (`f_0030.png`, `f_0031.png`, ...) shipped only the few it landed on. Around the
  times a numbered image sequence was requested, the probe now visits every frame.
- **The quality floor.** A 30 s clip made from a screen recording passed `showtime qa` and won a blind pairwise
  round against the previous pass, yet looked cheap at full size: two-line captions in stepped boxes, a web
  player's controls in the footage, a small recording inside big empty borders. The critic had marked the
  captions should-fix, and the video shipped anyway because the pairwise only asks "better than the last version?".
  - **An absolute verdict.** Every critic answer (CRITIC.md, the pairwise briefs, the crew brief) now carries
    `WOULD I POST THIS: yes | no -- one reason`, judged on the video alone (pairwise: one line per video). In
    quality mode a "no" (for a pairwise round: either critic's "no" for the winning render) keeps the review
    pending like "not ready", even when the pairwise preferred the render; a missing line keeps the round
    pending too. `review-verdict` records it (`would_post` in verdict.json, VERDICT.md, its printout), and the
    review state (`status`, `qa`, the receipt) carries it per round. The bar is "a stranger would not call it
    cheap, broken or wrong", not "flawless": worded first as a plain "would you post it", the critic said no to
    all 8 videos the author had rated, 4 of them approved; with the bar spelled out it agreed with the author on
    5 of those 8 and on 5 of 6 held-out videos it was never tuned on. The misses were mostly audio,
    which a critic reading images cannot hear.
  - **A caption should-fix cannot ship silently.** A should-fix or blocker that names captions or subtitles
    stays open until a later round's critic writes a line naming the captions with `fixed`, or the maker writes
    `won't fix: <reason>` about them in `review/round-N/RESPONSE.md` (plain word matching). Quality mode: the
    review stays pending; lean mode: `showtime qa` prints a WARN. Later-round critics answer each earlier
    finding under `PREVIOUS` (`fixed:` / `not fixed:`).
  - **Four new qa warnings** (`st/qa/floor.py`, up to 20 sampled frames at delivery size, WARN only):
    `player_chrome` (a progress bar with control glyphs at both ends on a dark control overlay, in the same place on 2+ frames),
    `soft_footage` (edge sharpness under 0.75 on most detailed parts of half the frames: re-record at 2x device
    scale), `caption_boxes` (stacked caption boxes of different widths), `empty_borders` (a solid picture filling
    under 70 % of the frame inside flat borders for over 30 % of the video). The footage-only ones skip projects
    whose page plays no `<video>`. On the clip above, qa now warns on three of the four; the owner-approved
    re-cut and every shipped example stay clean.

## 0.3.1 (2026-09-30)

- **The plugin's end-of-turn hook no longer fails before setup.** Installing the plugin and working a few turns before
  `showtime setup` made the Stop hook (`showtime receipt --hook`, which keeps a job's token and cost receipt current)
  print "needs the showtime environment" and fail at the end of every turn. Before setup there is no job to refresh, so
  the hook now exits quietly: from the launcher when the environment is missing, and from `bin/showtime` when there
  is no Python yet. A real command run before setup still says what to install.
- **Setup is the user's call.** In a test in the Claude app, the agent judged the one-time setup too big for a
  five-second clip and made the video with bare ffmpeg instead. SKILL.md and `references/onboarding.md` now say it
  plainly: give the size and time and run setup; if the user declines, say what cannot be made without it; never make
  the video another way.
- **SKILL.md's description is one line** (it was a folded YAML block, which one directory's importer read as ">").

## 0.3.0 (2026-09-30)

- **Quality first: every finished video gets the full review by default; lean is an opt-in.** Benchmark round 4
  showed the lean default (fewer looks, the critic only for publish-bound work, which the agent often did not
  trigger: a 45 s data story for YouTube shipped with no critic) ranked below 0.2.0 on several tasks (4-5 s still
  holds, a muddy crossfade, a label missing its year). The review mode is now a separate, visible choice. **quality**
  (the default): looks through the disposable reviewer, qa and a look after the final render, and a critic round
  (review-pack + a critic sub-agent, pairwise against the previous final when there is one) before delivery, plus
  the researcher when the video states facts. **lean**: one look per stage, the critic only when publish-bound or
  asked. The efficiency work (brief output, guide sections, `job init` checking setup, splice renders, looks outside
  the main context) stays on in both. Switch: `showtime job init <slug> --mode lean` (or `studio,lean`; recorded in
  job.json, SHOWTIME.md and the history; `job note --mode quality` switches back), `showtime config mode lean|quality`
  for every job (the new `showtime config` command; stdlib, runs before setup), `SHOWTIME_MODE`, the Claude Code
  plugin option "Review mode", and `showtime new --mode` / the MCP `new_project` tool's `mode` (showtime.json
  `review_mode`). `showtime status`, `doctor`, `job init`, the receipt (`review_mode`, the critic round's state) and
  every `--help` name the mode and what lean skips. The critic round cannot be skipped by accident: in quality mode
  `showtime qa <job>` on the latest final prints `WARN review pending ... -> <command>` until a round has a verdict (a
  VERDICT line in FINDINGS.md, or `review-verdict` for a pairwise round; "not ready" stays pending until a later round
  or the three-round cap), and `status`, SHOWTIME.md's next command, `deliver exports` and `job note --stage deliver`
  say the same. The line never changes the video's own qa verdict or exit code; lean prints none of it. SKILL.md's
  opening line states the mode ("Quality mode (default): full review; say 'lean' for a cheaper draft pass."), and
  `modes.md` section 6 lists the phrases that mean lean.
- **"Same style as this video" lands on the reference's style.** Benchmark round 4, t10: the owner's blind vote picked
  plain Opus over showtime ("much closer to the reference ... maintained colors and idea"). showtime had run
  `showtime reference`, but its brief said to use your own colours (the run switched to greens), merged the reference's
  0.5 s word-per-beat cuts into one 3.7 s shot and called its colour-panel wipes `push`/`whip-pan`, gave no layout or
  sound build (the run chose small body text and an acoustic-folk bed), and `short_text` pushed the beat words to 1 s.
  Now `showtime reference` keeps beat cuts separate, names colour-panel wipes (colour, direction, length), samples
  the palette (ground, ink, accent, flat or not), measures alignment, margin and type sizes, and the sound's build
  (kick on the beats, off-beat tick, last hit, silence at the end); the brief says to carry the style over (its
  colours included, unless a brand kit or the user says otherwise) and never the content, and writes `style.css`.
  `showtime new <template> --job <job>` links that file last and sets the background, so template and theme defaults
  yield (`--no-reference-style` skips it). The variety guard treats repeats that follow the job's style reference as
  intended (a note, no alternatives). `showtime check` reads a word-per-beat run as one line (`beat_words` note)
  when its words arrive no faster than 3 per second, and large text in the reference's own colour pair at 3:1 or more (WCAG large text) is a `low_contrast` note instead of an error when `reference-style.css` is linked. Type sizes are now measured from the ink of each line (cap heights; the t10 reference reads 385 / 200 / 85 / 65 / 50 px, the drawn sizes). Route: a router row in SKILL.md, the `reference` Essentials,
  and a line in the launch and social-short workflows.
- **The reference as a spec, and `showtime reference diff`.** reference.md/reference.json now carry a spec in frames
  (every scene change and its kind, shot lengths, element moves with length and easing from the frame-difference
  curve, palette roles, layout and type sizes, tempo and every sound hit) with KEEP and CHANGE lists.
  `showtime reference diff <job>` measures a render the same way and prints each KEEP item as ok or OFF with frame
  numbers (`--json`, `--strict`; another length is compared with scaled times). On t10 the round-4 plain Opus video
  lines up on every item; round 4's showtime video is OFF on cuts, shots, palette, moves and sound.
- **The near-copy guard checks detail before it fails.** A frame the coarse 64x36 test calls a near copy is confirmed
  at 256x144 on its textured blocks, over small zooms and shifts, when both videos are on disk. The round-4 plain Opus
  video (same layout, other words) failed the old guard at 12 % of frames; it passes now (detail about 0.3-0.45),
  while a re-encode, grade or small crop of the reference still fails (about 0.8-0.95).
- **Charts keep their numbers while the data changes, and data videos keep moving.** In the round-4 blind vote the
  owner saw numbers "disappear and then reappear when a new item is added" in two data stories: the agents had hidden
  every chart label while a chart moved (`[data-st-moving] .st-chart-val { opacity: 0 }`), because an added bar showed
  "0.00" before it arrived, `count: false` labels counted through a morph and a line's end label read a point behind
  the drawn tip. Now an item missing from a state (or `null`) is absent, not zero: added items grow in and light their
  own labels, labels already on screen stay lit and ride their marks (the per-state label plan keeps them first),
  `count: false` shows only real values across a morph, a state that only changes the title no longer counts as
  moving, a line's end label reads the point under its tip, absent line points are gaps, and hbar rows are sized for
  the largest state (a row that joins takes the place of one that leaves). `showtime check` warns
  `chart_labels_hidden` on CSS that hides chart labels while charts move. Callouts name their datum: `{label}` and
  `{value}` in `annotate.text`, and a line chart prefixes the point's label ("2015: first year above 400 ppm", the
  judges' missing year); a line callout slides clear of the end label; with a reference line the callout arrives a
  second later. Pacing: `check` warns `slow_scene` when a scene holds on past its last change and its reading time by
  more than 2.5 s (4 s for an end card), the case the slow push hid ("readable, but not dynamic"); the data template
  and release films use `dip` between text scenes (the judges' "heavy blur mid-transition" was a blur dissolve), the
  data template's source line arrives as a beat, and `workflows/data-story.md` has a Pacing section (a beat about every
  2 s, holds as long as reading needs, fix `slow_scene`/`dead_air`/`frozen` instead of accepting them). Holds: launch
  films warn on still holds from 3.5 s (was 5 s; the judges marked every 3.6-4.9 s launch hold as frozen), the launch
  hook leans toward its portal letter after 2 s instead of sitting still for 4.5 s, and a headline that arrives later
  in a launch scene rises in. Motion defects: qa `dead_stop` (a fast move that halts in one frame, with the frame
  number and an ease-out fix), check `same_frame_entrance` (3+ siblings entering on one frame, with a stagger fix),
  camera `data-drift="hold"` (1.2 %/s: the measured hold push that check and qa both count as change; motion-craft:
  nothing freezes), and `showtime look` adds the middle of the fastest transition to its key frames. Re-rendered
  round-4 projects (t2 x2, t6, t1) pass check and qa with 0 errors and 0 fails; tests `test_chart_constancy.py`,
  `test_pacing.py`.

- **A section re-render makes the whole video, or says it is only a clip.** `showtime render <p> --from A --to B
  --job <job>` used to write the job's next `final-N.mp4` with only the A-B seconds in it (found in a benchmark smoke
  run: an 18 s fragment beside the 82 s video, and the agent could not tell which one to hand over). Now, when the
  job's latest final comes from `showtime render` of the same project at the same size, frame rate and length, only
  A-B (widened to the keyframes around it) is captured and encoded with the full-render settings, and those frames
  replace exactly that run in a copy of the old final: a full-length `final-N.mp4`, every other frame the old
  render's bytes, no visible seam (checked frame by frame against a full render of the fixed project), audio mixed
  and mastered again for the whole video, poster as in a full render. A 1.2 s fix in a 20 s 1080p video took 18 s
  instead of 43 s for the full render. job.json records it as the latest final with `spliced: A-B from final-(N-1)`
  and the receipt counts a partial render. Another ffmpeg or other encode settings fall back to one whole encode.
  Without such a render (or after a size, fps or length change, with `--preview`, `--alpha`, `--size`, or without a
  job) the result is a span clip, `<job>/work/span-A-B.mp4` (no job: `span-A-B.mp4` in a new folder), never
  `final*`/`preview*`; render prints that it is a span and how to get the full video. `latest_video`, `qa <job>`,
  `look <job>`, review and ledger adoption never pick a span clip (nor a pre-0.3.0 span saved as `final-N.mp4`).

- **Blind vote boards say how to vote.** A board marked `"blind": true` opens with three steps (watch, rate and answer,
  copy and paste) and a **Copy my votes** button; the phone bar and the feedback drawer use the same label, and the
  production phases are not shown. Long concept titles no longer widen the page on a phone. Round 3's voter found the
  old "Copy for your agent" step hard to see. Non-blind boards are unchanged.
- **Benchmark round 4 is ready to launch** (`benchmarks/rounds/r4.md`): two new tasks (t9 explain a repo, t10 make a
  video in the style of a reference, with an original ffmpeg-drawn reference), a manifest-driven `round.py` that reuses
  earlier rounds' cells and runs second runs as their own cells, and `round_report.py`, which adds per-run stream
  metrics (cost, tokens, calls, images in context, largest context, tool text, full renders, receipt), an isolation
  check for runs that touch another showtime folder, and the 0.3.0 release gates as PASS / FAIL / PENDING.
- **Manim templates pass `manim check` and `qa`.** A fresh `manim new --template example` opened on 0.33 s of black and had
  an 8 s still stretch (check: 2 errors, 4 warnings); it now passes check with 0 errors and 0 warnings in 16:9, 9:16, 1:1
  and 4:5, and its voiced final passes qa with 0 fails and 0 warnings. The cause of the black opening was the kit:
  `beat()` waited out the voice's lead-in before the scene had added anything, so `beat("hook"); add(hook)` still opened
  on an empty frame; on an empty scene `beat()` now holds that lead-in on whatever is add()ed next. The example keeps its
  story and colours with bigger motion on every word (each spoken number drops into the sum over a large running total,
  copies of each term fly down and become its band of tiles, the four terms are boxed as braces read 4 by 4), and its
  line ids are no longer spoken words (`tiling`, `closing`). The pattern templates open on their title at t=0;
  `equation` uses a larger walkthrough (`equation_walkthrough(font_size=)`) and a slow camera push, `graph` fills the area
  under the curve as it is traced (`graph_build(area=True)`), `refine` sits under its title. check's black-frame fix states
  qa's rule (a frame is black only when nothing visible is on it). `tests/test_manim_templates.py`.

- **`manim check` agrees with `qa`.** After its dry run, check renders the draft (the same 480p15 scenes `manim render` caches) and
  runs qa's black and frozen-frame detectors on it with qa's thresholds. Manim's near-black ground with sparse content
  (`black_segment`) and a small `Indicate` on an equation (`frozen`) are now reported before the full render, each with a fix
  (`"light": true`, a bigger visible change); a hold the dry run already named is not repeated. `--no-draft` skips the pass.
  `references/manim.md` points to section 11 for integration (it said 9).
- **Receipts.** Every job ends with `receipt.md`, `receipt.json` (stable, schema 1) and one line in `share.txt`:
  the request as typed, the assumptions, review rounds, full vs partial renders, the images showtime made for looking,
  wall time from job start to final, and tokens and cost when the host's session log is named. Anything unknown says
  "not reported by this agent"; nothing is estimated. `showtime receipt [job]` regenerates it; `qa` keeps it current,
  `job note --stage deliver`, `deliver exports` and the MCP `receipt` tool finish it. Claude Code: the plugin's Stop hook
  (or `--transcript FILE`) sums the current session's token counts (numbers only, never text) and prices them at
  dated API list prices, labelled API-equivalent; Codex gives tokens only. `job init --request` keeps the user's words
  verbatim, and partial renders (`render --from/--to`) are now recorded in the ledger. Format: `references/receipt.md`.
- **Phone check.** The audience complaint about agent-made video (text moves too fast to read and is too small on a phone) is now one
  named check. `showtime check` ends with `phone check: PASS` or `FAIL - <items with timestamps>` and writes a `phone` block to
  `report.json`; `showtime qa` prints the same line, quoting that report (PARTIAL when there is none) and adding the caption
  sidecar's line length and reading speed. It joins what already existed: reading time (`short_text`, now per language: 17
  characters/s and 3 words/s, Japanese 4, Chinese 9, Korean 12 characters/s, in `runtime/thresholds.json`), type size (`tiny_text`, now
  in points at a 390 pt wide phone, with a minimum per aspect: 16:9 5 pt, 1:1 10, 4:5 11, 9:16 15; canvas text and captions are judged
  too, and small text is judged over its whole life, not only the sample frames) and the platform UI zones (`safe_zone`, `edge_margin`,
  `control_strip`). New qa rules `phone_size`, `phone_reading`, `phone_zone` (WARN) and `phone_unverified` (INFO). Numbers, sources and
  the calibration on the shipped examples: `references/qa.md`, "Phone check".
- **Pairwise review.** A model reviewer's absolute score is noisy; its preference between two versions is
  steadier, and only when it survives swapping the order. `showtime review-pack <job> --against best` (or
  `round-N`, or an older file) pairs the latest render with the best so far as a blind X/Y (random; the key
  stays in `review/.pairwise-keys/`): frames at the same times, both cut strips, loudness plots, qa and a
  narration transcript each, side-by-side sheets, and two briefs, one per order, for two fresh critics.
  `showtime review-verdict` applies the rule in code: the new render wins only when preferred in both orders;
  a tie or a split keeps the older one (`best.json`). The protocol now allows three critic rounds (was two),
  then ships the best version with its open findings listed. The briefs say "no scores". The benchmark's
  `pairwise_summary.json` adds `both_orders`: the arm that won a pair with either arm shown first.
### Lean mode: looks out of the main context, check before render, brief output

Measured in the 0.2.0 benchmark streams: showtime jobs cost 1.4-4.4x plain Opus on five of six tasks, largely because every
image opened (2000 px sheets, 1080p stills) and every long tool output stays in the agent's context and is paid for
on each later call, and runs took more calls (51 vs 13 on the launch task). Nothing was removed; the full output and
the full studio are one flag or one sentence away.

- **`showtime look <project | video | job>`**: one composite of the key frames (the opening frame, each scene's
  settled frame from the last `check`, the last frame), 1280 px wide, numbered per job with a budget of 12, plus
  `look-N.md`, a brief a disposable reviewer sub-agent follows (it opens the image and answers in text with
  timestamps), and `verdicts.md`. MCP: the `snap` tool takes `look: true`. `references/looking.md` is the protocol;
  SKILL.md, the workflows, `review.md`, `qa.md` and `crew.md` point their "look at it" steps there.
- **Check before render.** `render` warns when the project changed after the last `showtime check` (or was never
  checked) before a full render, and after a second full render names `--from S --to S` as the cheaper next fix.
- **Brief output.** Without a terminal (agents, pipes, MCP) `check`, `qa`, `doctor` and `render` print the verdict,
  the findings to act on with their fixes, and paths; the full report goes to a file (`work/check/report.txt`,
  `qa.json`, `<home>/logs/doctor.txt`, `render.log`). `--verbose` or `SHOWTIME_OUTPUT=full` prints everything; a
  terminal keeps the full report. MCP tool results are capped at 40 lines.
- **Lean by default**: quick mode is lean on strong models; "show me options first" or "studio" opens the studio,
  and publish-bound work keeps the researcher and the critic.
- **Crew model tiers**: the editor runs on Sonnet (the voice director already did); creative roles and the critic
  keep the session model.
- `benchmarks/scoring/stream_cost.py`: cost, turns, images in the main context (and which command produced each),
  context per call and the largest tool outputs of a stream-json run.
- **References by the piece.** The other large cost in the 0.2.0 streams was reference text: runs `cat` whole
  references and workflows (34-57k characters of tool text per job, two outputs over 30k spilled to files and read
  again). Every reference and workflow now opens with an `## Essentials` block (the rules for that step, 7-30 lines,
  each pointing at the section with the detail) and a table of its sections with line ranges; nothing else in them
  changed. `showtime guide <topic>` prints the Essentials and the section list (about a fifth of the file),
  `showtime guide <topic> <section>` one section (a number, a name, or a sub-heading such as `count-up`),
  `showtime guide --find <words>` the matching lines of every reference with their section. It is stdlib only (works
  before setup) and an MCP tool (`guide`). `scripts/check_release.py` checks every Essentials block (present, first,
  at most 40 lines, pointers that name real sections) and keeps the tables' line numbers current (`--check` fails on
  a stale table; without it the tables are rewritten). The crew briefs and `index.md` are read whole and have none.
  SKILL.md's routing tables name topics under a `showtime guide` header (`launch-video`, `components` ...): with
  paths there, a first proof run still `cat` the workflow and `html-export.md` (29k characters) before anything else.
  Proof on the 0.2.0 task t6 (single-file HTML report), one run each, same prompt and runtime: v0.3.0 base $1.11,
  30 model calls, 6 images, max context 74k; this change $0.81, 24 calls, 2 images, max context 58k; the report
  passes the same automatic checks (single file, offline, plays, no phone overflow).
- **Font messages that say what is wrong.** A text node drawn only with a system font while the page has loaded
  the family it asks for (a lone "₂" in a `<sub>` the font lacks) is now reported as a glyph fallback naming the
  characters (`U+2082`), not "load a font file" (that advice sent an agent searching the disk for font files).
- **One command to start.** `showtime job init` runs the quick setup check itself and prints `setup: ready` (or the
  failures with their fixes) on stderr; stdout stays the job folder. A healthy `doctor --quick` result is reused for an
  hour by both (same version, skill, home, agent and folder); `doctor --quick --fresh` checks again, a failing setup
  is always checked again. SKILL.md's step 0 is now `job init`.
- **Variety guard.** Each finished job's look (template, theme, palette, type pair, transitions, camera moves,
  music, structure, tone; read from the project files, `brand.json` and the mix) is kept in a local history
  (`~/.showtime/history/looks.json`, never uploaded; `showtime history off` or `SHOWTIME_HISTORY=off` opts
  out). `showtime check` warns `look_repeat` when a project repeats one of the last five jobs, with two
  concrete alternatives per repeat (themes, type pairs, palettes, catalog transitions, camera verbs, catalog
  tracks from other shelves, structures, tones); `showtime history` lists, checks, adds and clears.
  `showtime new` records the template name in showtime.json. Why: "every agent video looks the same" was the
  loudest audience complaint.
- **Style references.** `showtime reference <video>` breaks a reference into its grammar: cut times, shot
  lengths and pace (ffmpeg scene detection), how scenes change, palette, motion and camera verb per shot, a
  text-on-screen estimate with a rough type scale, loudness curve, silence and tempo, a 1 fps contact sheet
  and a brief for the storyboard (borrow the grammar; never its words, logos or shots). Local files first; a
  URL only as a direct link to a video file. The credit "Style reference: <title>" goes into credits.txt and
  share.txt (render keeps it), and `showtime qa` fails a render that copies the reference (`reference_copy`:
  sampled-frame SSIM and difference hashes plus cut-rhythm similarity; thresholds in
  `references/reference.md`).
- **`showtime adopt <folder | page | script>`**: a video someone already wrote as a function of time gets showtime's checks, sound, captions, qa, HTML export and review without a rewrite. It detects the contract (an HTML page with `seek`/`__seek`/`render`/`draw(t)`/`setTime(t)`, a page animated only by CSS, Web Animations or requestAnimationFrame on the virtual clock, a Python frame function returning Pillow/numpy/bytes, or a Python script whose own main writes the video) from the page, its local scripts and the render driver next to it, copies the folder (the originals are never changed), and writes a normal project around it. It then checks determinism (each sampled frame captured twice, in two orders) and runs `showtime check`. Every problem is printed as what/why/fix (`needs_setup`, `no_duration`, `outside_ref`, ...). Python runs in a separate process on the copy, with sockets to other machines refused and a time limit. `--refresh` re-adopts after the original changes. `references/adopt.md`.
- **Brand first for launches.** `showtime brand capture <repo|url> --job <job>` captures the product before the
  storyboard in one step: the palette with roles (the rendered site's ground, ink and accent win over the repo's
  CSS), fonts, logo, the wordmark as the site sets it, the code-block look, the product's copy verbatim with
  file:line (README tagline, install line, commands, features, the newest CHANGELOG release, the site's headline
  and buttons) and its real UI (the site folder or a running app captured per aspect, or the README commands of a
  CLI to run as evidence). It writes `<job>/brand/{brand.json,brand.md,capture/}` and records the kit in the job.
  `showtime new launch` applies the kit (theme tokens, the product window in the product's code colours, fonts,
  the end card's wordmark, version, value line and install command; text colours only deepened for contrast)
  and `showtime brand apply` re-applies it. A launch job without a kit records why (`showtime brand skip <job>
  --why ...`); `showtime check` warns when a launch job has neither (`brand_missing`) or when a kit exists but the
  page ignores it (`brand_not_applied`). The launch workflow starts from this step and states the length defaults
  (teaser 10-15 s, feature 30-40 s, launch 45-60 s), the 2-second hook, works-on-mute and the 3-4 s end-card hold.
  Why: in the 0.2.0 benchmark the launch video lost three votes running to a launch tool that starts from the brand.
- **qa fixes found while proving it.** `showtime qa` re-extracts its contact-sheet frames when the video is newer
  than them (a re-render to the same `final.mp4` used to show the old render's frames), and a 1:1 or 4:5 master
  is no longer an aspect warning for x or linkedin (both play it as is, as `deliver exports` already knew).
- **Fixes where the contract tripped agents** (found in the 0.2.0 benchmark runs):
  - Stage: a clip that is not active but still on screen (the outgoing scene through a transition, the incoming one
    in an early-aligned window) had the `--t`/`--p` of whichever seek last activated it, so its frames depended on
    seek order (`check`'s `nondeterministic`, chunk joins). Now they are a function of t: 0 before the clip starts,
    its last frame's values after it ends (what an in-order render always showed). Active clips are unchanged.
  - `retime --from-voice --total` works when every scene is narrated (a narrated close): the pause after the last
    line absorbs the difference; a total that would cut the line is an error naming the shortest one that works.
  - Manim: a `narration.md` with no lines (only a comment) is a silent film, not an error; `--mix` is read from the
    current folder first, then the project, and a mix track's file is also found in the Manim folder. A silent-film
    recipe is in `references/manim.md`.
  - `doctor` warns, with the fix, when `<SHOWTIME_HOME>/bin/showtime` runs another showtime than the agent's (a newer
    one recorded by another host, or a newer one installed that has not run yet); `showtime new` with an unknown
    template names the running version.
  - `check` names exactly the characters the page's fonts lack (from the loaded faces' unicode-ranges, not every
    non-Latin character of the line) and gives the fix for each: `<sub>`/`<sup>` markup for sub/superscript digits
    (no bundled font has them), an inline SVG for arrows, an `@font-face` with that `unicode-range` for the rest.
  - `SECURITY.md`: how to report a vulnerability privately, what is in scope, supported versions.
### Explainers from repos, papers and releases

- **Repo explainer workflow** (`references/workflows/repo-explainer.md`): a codebase explained in five parts (what it
  does, code map, life of one request, core abstractions, a real trace), from a research pass with a saved run and a
  real stack in `work/evidence/`; every claim is a row in `claims.md` pointing at file:line at a pinned commit; a
  narration guide for teaching like a lecturer instead of stacking short punchy lines and numbers.
- **Paper explainer workflow** (`references/workflows/paper-explainer.md`): a PDF or arXiv paper through
  `doc extract`, claims tied to pages, equations and figures, licenses checked before any figure is shown (credit
  sidecars feed `credits.txt`, which qa requires), Manim for the math.
- **`code-block` keeps a file's line numbers**: `data-first-line="258"` numbers an excerpt 258, 259, ... and
  `highlight`/`focus` take those numbers.
- **`showtime release-video`**: release notes, a CHANGELOG section (`--changelog-version`) or a PR description
  (`--kind pr`) become a ready-to-render project with no agent: the notes' own headings and lines, reading-time
  holds, the people credited, a composed bed; internal sections (dependencies, CI, docs) are counted, not shown.
- **GitHub Action** (`.github/actions/showtime-video`, guide in `docs/github-action.md`, example workflow in
  `docs/examples/`): installs showtime on the runner (minimal tier, cached), renders a release or PR video with
  `release-video`, or a committed project, or runs an agent command you configure with your own key; runs
  `check` and `qa`, exports the HTML video and a copy under 10 MB, and uploads them as an artifact or release assets.

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
- [x] **MCP packages published** (2026-09-29): npm `@faviovazquez/showtime-mcp` 0.2.0, the `.mcpb` as a release
      asset of `v0.2.0`, the MCP Registry (`io.github.FavioVazquez/showtime`) and Smithery
      (`favio-vazquezp/showtime`). The README's "MCP only" section and `docs/agents.md` link them.
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

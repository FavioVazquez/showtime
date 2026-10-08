# HTML export: share a video as one interactive web page

Read this when the user wants to share, send, embed or publish a video as a web page instead of
(or as well as) an MP4: "send me something I can open in the browser", "put it on the site",
"make it shareable as an artifact", "an HTML version", or when the MP4 is not the point (a
canvas film with a procedural score, an interactive demo someone scrubs through).

```
showtime export html <project>                     # -> showtime-out/<title>-<ts>/<title>.html
showtime export html <project> -o launch.html      # one file, opens offline in any browser
showtime export html <project> --folder -o site/   # index.html + assets/ for web hosting
showtime export html <project> --target artifact -o launch.html   # to publish as an HTML artifact
showtime export html <job>                         # a job: its project/ folder, written into the job folder
showtime export html <job> --folder out            # a job as a folder: ./out/index.html + assets/
```

## Essentials

- `showtime export html <project>` writes one offline `.html`; `-o launch.html` names it, `--folder -o site/`
  writes `index.html` + `assets/` for hosting, `--target artifact` for an artifact or docs page (§ Options). A job
  (`<job>`, as qa takes it) exports its `project/` folder into the job folder; `<job> --folder out` writes `./out/`
- After a render, offer the HTML version in one line when the destination is a browser; share an MP4 for
  social platforms, video hosts, editors, long footage or pages that are heavy to draw (§ MP4 or HTML?)
- Publishing is the user's call: offer it, never do it unasked (§ Sharing and hosting)
- Leave `--audio` at `auto` (`score` only when `ST.score` is the only sound, else `embed`); `--audio score` on a
  narrated film drops the voice (§ Audio modes)
- `embed` is AAC at `--bitrate` (default 96k, about 12 KB per second) at -14 LUFS; `--codec opus` is about a
  third smaller and plays in Chromium builds without proprietary codecs (§ Audio modes)
- A hand-written `ST.score` that honours `run.from` sets `ST.score.seekable = true`, else it renders whole
  before playing (§ Audio modes)
- The file must stay under `--max-mb` (default 16 MB); a bigger export writes nothing and lists sizes by kind.
  Ways down: `--bitrate 64k`, `--codec opus --bitrate 48k`, recompressed footage, `--folder` (§ Size budget)
- One chapter per step for tutorials and demos: showtime.json `"chapters": [[0, "Intro"], [4.5, "Demo"]]`, else
  `Film.start` `acts`, else the top-level clips (§ Options)
- Start screen: `--subtitle`/`--kicker` (or showtime.json); `--poster T` (default 40 %) should have space in a
  corner for the title; `"startTitle": false` when the poster frame is a hook (§ What you get, § Options)
- Embeds: `--controls none --autoplay-muted --loop` in an `<iframe>`, driven by `window.showtimePlayer`
  (§ Sharing and hosting)
- Link previews: showtime.json `"share": {"url", "image", "description"}` (or `--share-url`, `--share-image`);
  give a real `"title"` and `"chapters"`, the export warns about "Project" and "Shot 1" (§ Sharing and hosting)
- `-o` never overwrites (`-2`, `-3`); `--lang CODE` sets the player's words (en, es, fr, pt, de) (§ Options)
- Point someone at a passage with a range link, `video.html#t=1:05-1:20`: it plays that part on a loop
  (Shift + drag on the scrubber picks one, `c` copies its link) (§ What you get)
- Videos that ask: showtime.json `"questions"` (`at` = seconds or a narration line id) stop the player at each
  one; it goes on from the end of the MP4's pause and think beat; `socratic.json` is written beside it (§ Questions)
- A video report (charts, numbers) is a data story first: build and pace it with `workflows/data-story.md` (a
  change about every 2 s, holds as long as reading needs, callouts that name their year), then export it
- Use the MP4 for footage-led videos and slow-to-draw pages: playing is drawing. Sound always needs a click;
  a `--folder` export opened from `file://` cannot `fetch()` footage, serve it over http (§ Limitations)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| What you get | 63-129 |
| MP4 or HTML? | 131-141 |
| Audio modes (--audio): How the live score streams (and why seeking is exact) | 143-174 |
| Size budget | 176-199 |
| Sharing and hosting | 201-250 |
| Questions | 252-295 |
| Options | 297-327 |
| Limitations | 329-363 |

## What you get

One `.html` file (default) that holds the whole project: the stage runtime, the page, its
scripts and styles, the libraries it loads, fonts, images, emoji, JSON data, footage and the
mixed audio. Opened from disk, a chat attachment or a web server, it makes **no network request**
(a Content-Security-Policy in the file blocks any that a page might try).

It plays in a small player:

- a **start screen** until the viewer clicks, taps or presses a key (browsers only allow sound
  after one): the poster frame drawn live under a soft scrim in the film's ground colour, and in one
  corner the title, the subtitle and a small line above it (showtime.json `"subtitle"`, `"kicker"`,
  or `--subtitle`/`--kicker`, or `Film.start({subtitle, kicker})`), a **Play** button with the length
  and "N chapters · Sound on". The title uses the film's own title font (the stage hands the player
  its font files) and the button the film's accent colour; every colour is checked for contrast
  against the ground and replaced when it would not read. The corner is the one where the poster
  frame has the least text (the stage reports where its text sits), so the block never covers the
  headline. The page's `<title>` is the project title; nothing else is written over the picture.
  `--start poster` also packs the frame as an image, shown while the page loads.
- **fills the screen**: the page around the picture is the film's background colour (never a black
  frame around it). On a phone held upright with a landscape film the picture runs full width at
  the top; the title, the Play button and a tappable chapter list sit under it, the controls are
  docked at the bottom within thumb reach and a line suggests turning the phone for full screen. A
  vertical film fills a phone's width; safe-area insets (notches, home bar) are respected.
- play/pause, a scrubber with chapter ticks, a time tooltip and the rendered part of a live score,
  time, the current chapter (click it for the **chapter menu**), volume and mute, loop, fullscreen,
  "copy a link to this moment", and `?` for the key map; the controls hide while playing and come
  back on mouse move or tap (touch: 48 px targets, the time in 15 px type, chapter names in the
  scrubber tooltip)
- **deep links**: `film.html#t=72.5`, `#t=1:12.5`, `#t=1m12s` or `#chapter=3` / `#chapter=data` (the
  chapter's label) open the video there: the start screen says where, and playback starts there after
  the click. Changing the hash while it plays jumps there.
- **range links**: `#t=10-20` (also `#t=1:05-1:20`, or `#t=10,20` as in media fragments) plays that part
  and **loops** it: the start screen says "Plays 0:10 - 0:20 on a loop", the scrubber shows the part as a
  band, and the loop button is on; turned off, play stops on the part's last frame (Play starts the part
  again). Questions inside the part still ask (again on every loop until answered; one after it never
  does). Seeking outside the part, Esc, or a plain `#t=` leaves it. To make one, **Shift + drag** on the
  scrubber (Shift + click: from the playhead to the click); `c` (or the link button) then copies the
  range's link instead of the moment's. Point a reviewer at a passage with a range link.
- fits any window size or aspect, works with touch, respects reduced motion (no muted autoplay),
  labelled for screen readers; the controls use the system font

Keyboard (shown in the player with `?`):

| Keys | Action |
|---|---|
| any key (before starting) | begin (a digit begins at that chapter) |
| Space, K | play / pause |
| ← / → | back / forward 1 s |
| Shift + ← / →, `,` / `.` | one frame back / forward |
| J / L | back / forward 5 s |
| 1-9 | jump to chapter 1-9 (a video without chapters: 10-90 %) |
| `[` / `]`, Page Up / Page Down | previous / next chapter (`[` goes to the start of the current chapter first when more than 1.5 s into it) |
| 0, Home / End | start / last frame |
| R | restart from the beginning and play |
| M, ↑ / ↓ | mute, volume |
| F | fullscreen |
| C | copy a link to this moment (`#t=`), or to the picked range (`#t=a-b`) |
| Shift + drag on the scrubber | pick a range to loop and link (Shift + click: from the playhead); Esc clears it |
| ? , Esc | show / hide the key map |
| A-C or 1-3, Enter | while a question is asked: answer it, then continue (§ Questions) |

**Frames are exactly the render's.** The page runs in the same stage runtime `showtime render`
uses (virtual clock, seeded randomness, the same config), and the player seeks it to the
audio's time on every screen refresh, so a paused frame at `t` is the frame of the MP4 at
`t` (the test suite compares them with `showtime snap`). Picture follows the audio: there is
no drift, and a slow machine drops frames instead of falling behind the sound.

## MP4 or HTML?

| Share an MP4 when | Share HTML when |
|---|---|
| it goes to a social platform, a video host or an editor | it is opened by a person in a browser: a link, a chat, a docs page, an artifact |
| the page is heavy to draw (large blurs, many shaders, 4K) | it is a canvas film or motion graphics with a procedural score: a few hundred KB instead of MBs |
| it has long real footage (the HTML carries the clips as data) | people should scrub, pause on a frame, jump by chapter, or you want text to stay sharp at any size |
| it must play on anything, including smart TVs and mail clients | you want it embeddable (`--controls none`) or hosted as a page |

Both come from the same project, so offering both costs one command. After a render, offer the
HTML version in one line when the destination is a browser.

## Audio modes (`--audio`)

| Mode | What is in the file | Use |
|---|---|---|
| `auto` (default) | `score` when the only sound is `ST.score`, else `embed` | almost always |
| `score` | nothing: the browser plays the procedural score itself, **streamed**: it renders the score in short pieces ahead of the playhead (the first one while the start screen shows, usually well under a second) and the rest in the background, at the render's loudness (same gain and limiter the exporter measured) | canvas films and tutorials scored with `Synth`: the smallest file |
| `embed` | the audio exactly as the render builds it (score + `audio` mix, loudness to -14 LUFS) as AAC in `.m4a` at `--bitrate` (default 96k; about 12 KB per second) | voice, music files, anything mixed; **every narrated film** (a voice is a mix: `score` would drop it, and footage layers make the file large anyway). `auto` already picks it |
| `none` | no sound | silent loops, embeds |

`--codec opus` makes the embedded track about a third smaller at the same quality; AAC is the
default because Chrome, Edge, Safari and Firefox decode it. Chromium builds without proprietary
codecs (and some Linux Firefox installs) cannot: the picture then plays silently and the player
says so on screen; `--codec opus` plays there. `--lufs` and `--no-loudnorm` work as in `render`.
With `--audio score` a project that also has an `audio` mix loses the mix (a warning says so): a
narrated film exported with `--audio score` has no voice. Leave `--audio` at `auto` (or say `embed`).

### How the live score streams (and why seeking is exact)

A `Synth` score sounds the same rendered from any time as the same stretch of a render from 0
(`synth-score.md` §5b): sustained sounds resume at their level and phase, short ones are not replayed,
noise is keyed to film time, and every event sits half-way between two samples so all renders round
it the same way. The player renders pieces of 1.5-12 s (sized to the machine's speed), each started
2.5 s early on a 128-sample boundary so reverb tails and compressors have settled, applies the
export's gain and limiter, and plays them through Web Audio back to back; the sound is the clock and
the picture follows it. A seek into a rendered stretch plays at once, elsewhere as soon as that piece
is ready (the picture holds with a spinner meanwhile). The test suite checks that the streamed sound
equals a whole render of the score to about -80 dB. A hand-written `ST.score` that does not honour
`run.from` is rendered whole before playing (mark it `ST.score.seekable = true` if it does).

`window.showtimePlayer.audio` is then `{kind: 'score', currentTime, paused, duration, rendered(),
level(t0, t1), verify(t0, t1), tap()}`: `verify` compares the stream with a whole render, `tap()`
returns an AnalyserNode on the output.

## Size budget

The single file must stay under `--max-mb` (default **16 MB**, the artifact size limit; `0` turns
it off). Base64 adds a third to binary files. When the export would be bigger, nothing is
written and the error lists the size by kind (video, audio, fonts, images, scripts) and the
largest files, with what to do. Typical sizes: a 12 s canvas film with a live score about 220 KB, a two-minute canvas tutorial about
170 KB, a 15 s DOM launch video with an embedded mix 0.7 MB. What keeps procedural films small:

- the runtime is trimmed to what the video uses: `film.js` and `synth.js` drop sections the project
  never calls (charts, device frames, drum kit ...; the report lists them), the stage runtime drops its
  preview player; scripts and styles lose comments and spaces (`--minify off` keeps them as written);
- every text file (scripts, styles, data, the page) and the player itself travel gzip-compressed and are
  unpacked by the browser (DecompressionStream; every 2023+ browser has it);
- fonts: only WOFF2 (the older formats a stylesheet lists are left out), no faces for alphabets the video
  never shows, and for canvas films no families no frame draws with (`--all-fonts` keeps everything);
- no poster image with the default start screen (the frame is drawn live);
- no sound files the page never plays: the export carries its own mixed audio, so a WAV that only a data file
  names (`voice/timeline.json` names `vo.wav`) stays out; a sound the page itself requests is packed.

Fonts are then usually the largest part: a variable font's Latin file is 30-65 KB.

Ways down: `--bitrate 64k` or `--codec opus --bitrate 48k`; `--audio score` for score-only
projects; footage recompressed (`-c:v libvpx-vp9 -crf 36`, the size it is shown at) or `--folder`;
images at the size they appear; fewer font families and weights.

## Sharing and hosting

- **A file**: send the `.html`; it opens with a double-click. Nothing is uploaded by showtime.
- **An artifact or a docs page**: export with `--target artifact` (one file, held under 16 MB) and
  publish that. It plays when a host shows it in a sandboxed frame (even one without
  `allow-same-origin`; fullscreen then depends on the host). In such a frame the player hides what
  needs a file address or a download ("copy a link to this moment", the deep-link hint in the key
  map); `--target artifact` bakes that in, and the player also detects a sandboxed or claude.ai
  frame by itself. A host may also add its own Content-Security-Policy (inline styles only, no
  font URLs): the stage writes every stylesheet inline and builds fonts from their bytes
  (FontFace), so the theme, its fonts and its sizes survive that. A font that still fails is
  reported in the console; add `#st-debug` to the address to see the reports on screen.
  Publishing is the user's call; offer it, do not do it unasked.
- **A web site**: `--folder -o site/` writes `index.html`, `assets/vfs.js` (scripts, styles,
  fonts, small images) and `assets/media/` (footage, the mixed audio and large images as real files,
  no base64, no size limit). Upload the folder anywhere static. It also opens from disk. The
  folder carries no Content-Security-Policy (it loads its own files), so the no-network guarantee
  is the single file's; set a CSP on the server if you need one.
  GitHub Pages: push the folder to a repository (or its `docs/`) and turn Pages on for it. The export
  writes an empty `.nojekyll` beside `index.html`: without it Pages' Jekyll step drops folders whose
  names start with `_` (`assets/media/_export/`, the mixed audio) and the page plays silent.
  Serve it from a server that answers byte-range requests, as GitHub Pages and most web hosts do: a seek
  then plays at once. A plain test server without them (`python3 -m http.server`) cannot seek the
  mixed audio, so after a seek the player reads the audio file whole and the picture plays on silent
  until it is in. That read starts as soon as the player knows the file's length, before any seek, so a
  seek a few seconds in waits for what is left of it (the whole read is about 3.3 s for 2 MB at 0.6 MB/s).
  If the read fails, the next seek tries it again. To look at it on your own machine, open
  `index.html` from disk instead.
- **Link previews**: the page carries `og:title`, `og:description`, `og:url`, `og:image` and
  `twitter:card`, so a link to it shows a card in chats and social posts. Set them in showtime.json,
  `"share": {"url": "https://me.github.io/launch/", "image": "card.jpg", "description": "One sentence."}`,
  or with `--share-url` and `--share-image`. The title is the export's title; the description defaults
  to the length and chapter count. The image is an https URL, or a file (`--folder` copies it to
  `assets/`); without one, a `--folder` export uses the poster frame (`assets/poster.jpg`), and a single
  file with a share URL gets it beside the file (`<name>.share.jpg`, upload both). A single file without
  a share URL has no image: link previews cannot read images inside the file. Most platforms ignore a
  relative image path; with the share URL the export makes it absolute (relative to the page's folder),
  without it the path stays relative and the export says so. The export warns when the title is a
  default ("Project", from a folder named `project`) or when the chapters are scene ids ("Shot 1",
  "Shot 2"): both show in previews and in the player; set `"title"` and `"chapters"` in showtime.json.
- **Embedding**: `--controls none --autoplay-muted --loop` gives a bare looping picture (a click
  toggles pause); put the file in an `<iframe>`. Pages can drive it through
  `window.showtimePlayer` inside that frame: `ready` (promise), `play()`, `pause()`, `restart()`,
  `seek(t)` (resolves when the frame is drawn), `currentTime`, `duration`, `paused`, `started`,
  `muted`, `volume`, `loop`, `chapters`, `chapter` (current), `goToChapter(i)`, `startTime` (from a
  deep link), `link(t)` / `copyLink()` (`{url, hash, full}`; `link()` with a range set links the range),
  `range` (`{a, b}` or null), `setRange(a, b)` / `setRange(null)`, `linkRange(a, b)`, `audio`,
  `questions`, `question` (the id being asked), `answer(i)`, `continueQuestion()`,
  `on('play'|'pause'|'seek'|'ended'|'loop'|'frame'|'ready'|'restart'|'link'|'question'|'answer'|'continue'|'range'|'rangeend', fn)`;
  the player element also dispatches `showtime:<event>` DOM events.

## Questions

A video can stop and ask the viewer before it tells them (`story.md` § 9). List the questions in
showtime.json:

```json
"questions": [
  { "id": "q1", "at": "ask-sum", "prompt": "What is it equal to?", "choices": ["2", "3", "It grows forever"],
    "answer": 1, "reply": {"0": "Close, but it lands on 3.", "1": "Yes: the whole tower equals 3.", "2": "It levels off at 3."},
    "think": 3 }
]
```

- `at`: where the video pauses. Seconds, or a voice cue: the id of a narration line (`## ask-sum` in
  `narration.md`, the ids in `voice/timeline.json`). `"ask-sum"` is the end of that line's speech,
  `"ask-sum.start"` its start, `"ask-sum.end+0.4"` adds an offset. Cues are read where the mix plays that
  line (a `vo-<id>` track `retime --from-voice` writes or a track playing the line's own file, else the
  `vo.wav` track's start), so a
  re-voice or a retime moves every question with its line; `retime -d` moves questions given in seconds.
- `choices` (2-9, three read best) and `answer`, the index of the right one (0 is the first).
- `reply`: one line shown after any answer, or one per choice (`{"0": "...", "1": "..."}`) that says
  why. The reply of the right choice is what the MP4 shows at its reveal.
- `think` (default 3 s): the length of the MP4's "pause and think" beat, from `at`.
- `"questions": false` turns them off; `showtime check` names every problem (`question_*` errors: a
  duplicate id, an answer out of range, a cue that names no line, a beat past the end, two beats that
  overlap), and the export refuses a broken list.

In the HTML export the player pauses on the frame at `at` and a card asks the question: the prompt,
the choices (A-C or 1-3 on the keyboard), then a right or wrong mark, the reply and Continue (Enter),
which plays on from `at + think`, the end of the beat the MP4 shows instead. The scrubber marks each
question (green or red once answered) and the card keeps the score. Seeking past a question passes it;
seeking back before it asks it again unless it was answered; a restart or a replay asks them all. Play
while a question waits plays on through the video's own beat. A page that is late (a background tab)
still stops, back on the question's frame. Over the picture the card sits at the bottom, above the
controls; on a phone held upright it sits under the picture, so the paused frame stays in view.

- `--auto-continue 6` goes on by itself 6 s after an answer; `--no-questions` exports a plain player
  (the video still draws its beats); with `--controls none` the embedding page asks them.
- `socratic.json` is written beside the export (`{title, questions: [{id, pause, resume, prompt, choices,
  answer, feedback}]}`) for a page that drives the player from outside (`window.showtimePlayer`).
- The MP4 shows what the video draws itself: the `question-beat` component (`components.md` § 3) or
  `F.questionBeat` on canvas (`film-api.md` § 12), and in the mix a `"questions"` block ducks the music
  under every beat and can tick through it (`audio.md` § 5). A video may draw its own beat and use only
  the times (`ST.questions`, `Film.questions`).

## Options

| Option | Default | Notes |
|---|---|---|
| `-o FILE` / `--job JOB` | new job folder | never overwrites (`-2`, `-3` ...); `-o` an existing folder (or `dir/`) writes `<dir>/<title>.html`; `--job J -o embed.html` writes that name inside the job folder |
| `--folder` | off | `-o` is then a folder |
| `--controls full\|minimal\|none` | full | minimal: play, scrubber, mute, fullscreen |
| `--autoplay-muted` | off | starts muted as soon as it loads, with a "Tap for sound" button |
| `--loop` | off | the viewer can toggle it |
| `--target file\|artifact` | file | artifact: for a sandboxed host (one file, max 16 MB, no link/download features) |
| `--start card\|poster` | card | what shows before playing (see above) |
| `--poster T` / `none` | showtime.json `poster`, else 40 % | the frame behind the start screen (pick one with space in a corner for the title); with `--start poster` (or an explicit `--poster`) it is also packed as an image shown until the page is ready |
| `--lang CODE` | showtime.json `lang`, else the page's `<html lang>`, else the narration's `lang:`, else en | sets `<html lang>` and the player's own words (Play, Chapters, Sound on, the key help) in en, es, fr, pt or de; other languages get English controls |
| `--audio-file FILE` | | embed exactly this sound (a WAV, or the shipped MP4's audio) instead of rebuilding the score and the mix |
| `--title`, `--subtitle`, `--kicker` | showtime.json `title`, `subtitle`, `kicker` | page title and start screen |
| `--share-url URL` | showtime.json `share.url` | the page's address once hosted: `og:url`, and relative share images made absolute (§ Sharing and hosting) |
| `--share-image URL\|FILE` | showtime.json `share.image`, else the poster frame | the link-preview image; showtime.json `share.description` sets `og:description` |
| `--no-questions` | questions asked | a plain player that does not stop at showtime.json `questions` (§ Questions) |
| `--auto-continue S` | wait for Continue | go on S seconds after a question is answered |
| showtime.json `"startTitle": false` | title shown | the poster frame already says what the video is (a hook frame): only the Play row sits over the picture, on a light corner scrim; the title still heads the phone layout |
| `--minify auto\|off` | auto | trim and compress the runtime, scripts and styles (off: as written, uncompressed; for debugging) |
| `--json` | | report: output, bytes, audio, chapters, sizes by kind, largest files, warnings |
| `--all-fonts`, `--no-csp`, `--page`, `--keep-work` | | see `showtime export --help` |

Chapters come from showtime.json `"chapters": [[0, "Intro"], [4.5, "Demo"]]`, else the film's
`acts` (or `chapters`) in `Film.start`, else the top-level clips (named by `data-name` or `id`). They
drive the scrubber ticks, the chapter menu, keys 1-9 and `[`/`]`, and `#chapter=` links: give a video
with steps (a tutorial, a demo) one chapter per step.

A tutorial series (`showtime new series`) exports all at once: `showtime series export <series> -o
site/` writes every episode and the opener as single files plus an `index.html` listing them.

## Limitations

- **Sound needs a click** in every browser; `--autoplay-muted` starts the picture muted instead (a
  live score then starts when the viewer taps for sound).
- **Deep links and copied links** need the file to have an address: from disk, a web server or a
  link to the file. Inside a host that shows it in a sandboxed frame (an artifact page) the hash of
  the frame cannot be set from outside, so the player hides "copy link" there (the `c` key still
  copies `#t=...` with a note).
  iPhone: the volume slider is hidden (iOS only allows mute) and there is no fullscreen button
  (Safari has no element fullscreen on iPhone): the player suggests turning the phone instead.
- **Playing is drawing.** The browser draws each frame live, so pages that take long to draw a
  frame (big blur filters, several shader layers, footage seeked every frame) drop frames on
  slower machines where the MP4 would not. Footage in pages is seeked per frame for exactness,
  which is smooth for short clips and heavy for long ones: use the MP4 for footage-led videos.
- **Shader transitions** are drawn live from a snapshot of the two scenes (the render captures
  them as screenshots); they look the same but are not bit-exact during the transition.
- **Old browsers**: needs a current Chrome, Edge, Firefox or Safari (2023+): import maps, blob
  URLs, `srcdoc`, DecompressionStream (older browsers get a one-line message instead of the video). A page's own import map (`"three": "/_lib/three/build/three.module.js"`, prefix
  entries like `"three/addons/"`) is folded into the player's single map, so bare imports work.
- **Codecs**: footage plays only where the browser decodes it. H.264 `.mp4` clips and the AAC
  audio do not play in Chromium builds without proprietary codecs; VP9/WebM footage and
  `--codec opus` play in every current browser engine.
- **--folder from disk** (`file://`): browsers refuse `fetch()` of files there, so pages that
  read footage or large images as data (WebGL textures from those, `fetch` of a video) need the
  folder served over http; everything else works from disk.
- **Size**: the embedded audio costs about 12 KB/s at 96k; embedded footage costs its size plus a third.
  A score rendered live (`score`) is rendered by the viewer's browser before playback can start:
  for a 12 s score that took from about 1 s to 10 s in testing, depending on how busy the machine
  was, and it grows with the score's length (a click in the meantime starts playback once ready).
- Page code that builds URLs in unusual ways (reading `document.currentScript.src`, string
  surgery on `location.href`, CSS `@import` added at run time) may miss the packed files
  (`new URL(path, location.href)` does work: it resolves against the page's own address). A project
  file the page asks for that cannot be packed (not there, or the server did not answer) stops the
  export with the list, so a page never ships with scenes missing; a missing emoji or runtime file is a
  warning. The browser console names anything else that is missing.

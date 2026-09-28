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
```

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
| C | copy a link to this moment (`#t=`) |
| ? , Esc | show / hide the key map |

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
- no poster image with the default start screen (the frame is drawn live).

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
- **Embedding**: `--controls none --autoplay-muted --loop` gives a bare looping picture (a click
  toggles pause); put the file in an `<iframe>`. Pages can drive it through
  `window.showtimePlayer` inside that frame: `ready` (promise), `play()`, `pause()`, `restart()`,
  `seek(t)` (resolves when the frame is drawn), `currentTime`, `duration`, `paused`, `started`,
  `muted`, `volume`, `loop`, `chapters`, `chapter` (current), `goToChapter(i)`, `startTime` (from a
  deep link), `link(t)` / `copyLink()` (`{url, hash, full}`), `audio`,
  `on('play'|'pause'|'seek'|'ended'|'loop'|'frame'|'ready'|'restart'|'link', fn)`;
  the player element also dispatches `showtime:<event>` DOM events.

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
  (`new URL(path, location.href)` does work: it resolves against the page's own address); `showtime export` warns about any file
  the page asked for that it could not pack, and the browser console names what is missing.

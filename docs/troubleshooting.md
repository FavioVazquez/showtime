# Troubleshooting

Find what you see, then tell your agent the line under **Say**. Each answer says what showtime does today and the
command your agent runs. You can run the commands yourself in a terminal too: `showtime` is
`~/.showtime/bin/showtime` after setup (Windows: `showtime.cmd`).

Start with `showtime doctor` when you are not sure. It runs ffmpeg, Python, Node.js and a browser for real and
prints PASS, WARN, FAIL or SKIP per check, each problem with a `fix:` line. `showtime doctor --quick` skips the
browser launch and the test encode.

| What you see | Jump to |
|---|---|
| "Node.js not found", or "too old" | [Node.js](#nodejs-not-found-or-too-old) |
| "setup has not been run yet", "setup has not completed yet", or the download was blocked | [Setup](#setup-never-ran-or-the-sandbox-blocked-it) |
| "no Chrome, Edge or Chromium found", or the browser will not start | [Browser](#no-browser-or-the-browser-will-not-start) |
| The agent's command stops before the render ends | [Long renders](#the-agents-command-times-out-on-a-long-render) |
| Rendering is slow, or there is no GPU | [Slow renders](#rendering-is-slow-or-there-is-no-gpu) |
| The video differs from the preview, or flickers | [Preview and flicker](#the-video-differs-from-the-preview-or-flickers) |
| A black or frozen stretch | [Black or frozen](#a-black-or-frozen-stretch) |
| A name is said wrong (a readback WARN) | [Pronunciation](#a-name-is-said-wrong-a-readback-warn) |
| "cut about N words" | [Narration too long](#cut-about-n-words-the-narration-is-too-long) |
| Music drowns the voice, or a loudness FAIL | [Sound](#music-drowns-the-voice-or-a-loudness-fail) |
| A command ends with exit code 3 | [Exit code 3](#a-command-ends-with-exit-code-3) |
| "It still looks wrong" after a fix | [Wrong file](#it-still-looks-wrong-after-a-fix) |

## Node.js not found, or too old

showtime needs Node.js 20 or newer; 24 or 22 LTS is recommended. doctor fails `node` with "Node.js not found" or
"Node.js 18.x ... is too old". A Node.js you just installed is not seen until the agent restarts.

- **Do:** install Node.js from [nodejs.org](https://nodejs.org) (on Linux, fnm or NodeSource: distribution packages
  are often older than 20). Restart your coding agent, or open a new terminal.
- **Check:** `node --version`, then `showtime doctor --quick`.
- **Say:** "Node.js is installed now; run showtime doctor again."

## Setup never ran, or the sandbox blocked it

Before setup, every showtime command that needs it, `showtime job init` included, stops with "`job` needs the
showtime environment, and setup has not been run yet", and prints the command to run. A setup that did not finish
shows in doctor as "setup has not completed yet". Your agent should give
the download size and time (`showtime setup --estimate`), wait for your yes and run `showtime setup`. Some agent
sandboxes block that download or the write to `~/.showtime`: doctor then fails `home writable` or `network` and
names the host setting to change.

- **Do:** run setup once in your own terminal, then go back to your agent:

  ```bash
  git clone --depth 1 https://github.com/FavioVazquez/showtime ~/showtime
  ~/showtime/skills/showtime/bin/showtime setup      # Windows: ~\showtime\skills\showtime\bin\showtime.cmd setup
  ~/showtime/skills/showtime/bin/showtime doctor     # every line PASS (SKIP is fine)
  ```

- **Or:** ask your agent to install into the project folder, which the sandbox can write:
  `SHOWTIME_HOME=.showtime showtime setup` (PowerShell: `$env:SHOWTIME_HOME=".showtime"; showtime setup`). showtime
  then finds `./.showtime` by itself in that project.
- **Interrupted?** Run `showtime setup` again: it skips what is there and resumes downloads. `showtime setup --verify`
  re-checks the files.
- **Say:** "Setup is done; carry on with the video."

More: [onboarding § Install](../skills/showtime/references/onboarding.md) and [agents.md](agents.md).

## No browser, or the browser will not start

Every frame is drawn by a headless browser. doctor fails `browser` when it finds no Chrome, Edge or Chromium, and
`browser launch` when one is found but will not start (common on a bare Linux server, which lacks the libraries).

- **No browser:** `showtime setup` installs Chrome's headless shell (about 100 to 120 MB to download), or install
  Google Chrome.
- **It will not start, on Linux:** `npx playwright install-deps chromium` installs the missing system libraries.
- **WebGL unavailable** (a WARN): 3D and shader scenes will fail. Try `showtime doctor --gpu off`, which tests
  drawing on the CPU; when that passes, render with `--gpu off` too.
- **Say:** "Run showtime doctor and fix the browser line."

## The agent's command times out on a long render

Many agents stop a command that runs longer than their time limit. A render, a setup or a long transcription
can take longer than that.

- **Do:** run it in the background and watch it: `showtime render <project> --job <job> --background` prints a run
  id at once, and `showtime status <run-id> --wait 240` reports its progress for up to 240 s at a time. Any
  command takes `--background`.
- **Say:** "Run the render in the background and check on it."

Your agent says how long anything over 30 s will take before it starts it.

## Rendering is slow, or there is no GPU

No GPU is needed. Without one the browser draws on the CPU, WebGL included, and showtime picks how many browsers
to run from your CPU threads: 3 with a GPU; without one, CPU threads - 2 (at most 8) from 8 threads up, and 3
below. `render.json` beside each render says how many and why. WebGL scenes are the slow part on a small machine:
on a 6-core Intel Mac with its GPU turned off, a shader-heavy 1080p frame took about 0.5 s.

- **Draft first:** `showtime render <project> --preview` (at most 720p, fast encode), or `--preview --fps 12` for
  the fastest look at timing.
- **Fix a part, not the whole:** `showtime render <project> --job <job> --from 12 --to 18` renders those seconds
  and [splices](glossary.md#splice) them into the last full render.
- **Know before:** `showtime check <project>` prints an estimate of the render time.
- **Say:** "I'm on a 4-core laptop with no GPU: draft first, and keep it light."

More: [slow machine guide](guides/slow-machine.md) and [render § Speed](../skills/showtime/references/render.md#speed).

## The video differs from the preview, or flickers

showtime draws each frame as a function of time, so the preview and the render should match. When they do not,
something on the page runs on the clock or at random: a timer, a CSS transition, `Math.random()`, a font or a
video that was not awaited.

- **Do:** `showtime check <project>` names it (`timers`, `unseeded_random`, `css_transitions`,
  `font_not_embedded`). `showtime check <project> --determinism` loads the page twice and compares 12 frames.
- **Say:** "At 0:08 the title flickers; it looks fine in the preview."

More: [debugging-renders](../skills/showtime/references/debugging-renders.md).

## A black or frozen stretch

`showtime qa` warns about black from 0.25 s (FAIL from 1 s) and a picture that does not change from 2.5 s (FAIL
from 6 s, or half the video), each with its time.

- **Do:** `showtime check <project> --find-first black` (or `frozen`) finds the first bad frame before you render
  again; `showtime snap <project> --at 8.2` shows that moment.
- **Say:** "The screen goes black at 0:12 for about a second."

## A name is said wrong (a readback WARN)

After making the voice-over, `voice script` listens to it with the local recognizer and warns when a name, an
acronym or a number is heard differently from the script. qa checks it again. The recognizer can be wrong too, so a
WARN means "listen to this line": the clip is `voice/lines/NN-<scene>.wav`.

- **It sounds wrong:** `showtime voice ipa "Word"` shows what the voice is told. Your agent adds a pronunciation to
  `lexicon.json` or writes `[SQL](sequel)` in the script, and runs `voice script` again.
- **It sounds right:** clear the word in the project's `showtime.json`: `"readback": {"ok": ["JSON"]}`.
- **Say:** "It says Kubernetes wrong; it should sound like koo-ber-NET-eez."

More: [voice § Pronunciation fixes](../skills/showtime/references/voice.md).

## "cut about N words": the narration is too long

With `--fit 15`, `voice script` makes the narration last 15 s: first it speeds every line up within 0.85-1.15x,
then it shortens the pauses. When that is not enough it prints `still Xs over ... cut about N words`. It never drops
words for you.

- **Do:** estimate before any speech is made: `showtime voice script narration.md --fit 15 --estimate` prints the cut
  and synthesizes nothing. Cut the words, estimate again, then run it without `--estimate`.
- **Say:** "Keep 20 seconds; cut the script, not the pace."

## Music drowns the voice, or a loudness FAIL

qa measures the loudness against the target (-14 LUFS unless the platform needs another): WARN more than 1 LU off,
FAIL more than 3 LU off, and FAIL for a true peak above 0 dBTP. It also warns (`voice_masked`) when a voice line
sits less than 8 dB above the music under it.

- **Do:** the music's level and its duck under the voice are in `audio/mix.json` (`gain_db`, and `"duck": {"under":
  "voice", "depth_db": 12}`). Your agent lowers the music or deepens the duck, mixes again and re-renders. `showtime
  audio meter <file>` measures any file.
- **Say:** "The music is too loud under the voice from 0:20."

More: [sound-design](../skills/showtime/references/sound-design.md) and [qa](../skills/showtime/references/qa.md).

## A command ends with exit code 3

Exit code 3 means showtime stopped on purpose and needs your decision. There are two cases.

- **A website blocked the capture.** Some sites answer automated browsers with a challenge ("Verify you are human").
  `showtime site capture` writes `BLOCKED.md` and `blocked.png` and stops. showtime never works around a block. Give
  your agent screenshots or a screen recording, another URL, or your local build (`http://localhost:...`).
- **A feature needs an optional part.** The command prints the exact `showtime setup --with <name>` line and its
  size. Say yes and your agent installs it and carries on. Offline, a first-use download fails the same way.
- **Say:** "Use these screenshots instead," or "Yes, install it."

More: [capture § Bot walls](../skills/showtime/references/capture.md).

## "It still looks wrong" after a fix

Renders never overwrite: a fix makes `final-2.mp4`, a poster bake `final.poster.mp4`. A video player that still has
the old file open shows the old video.

- **Do:** `showtime qa <job>` prints the file it checked (`using ... (latest final)`); open that one.
  `showtime status <job>` says where the job stands.
- **Say:** "Which file is the latest?"

## Still stuck

`showtime report <job> --problem "what you expected and what happened"` writes a redacted `bug-report.md` into the
job folder. Nothing is uploaded: read it, then attach it to an
[issue](https://github.com/FavioVazquez/showtime/issues) if you like. Your agent's triage order is in
[diagnosing](../skills/showtime/references/diagnosing.md). Short answers to other questions are in the
[FAQ](faq.md).

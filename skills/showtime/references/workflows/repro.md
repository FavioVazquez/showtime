# Workflow: a failing browser test as a video (repro)

Read this when a browser test fails and the user wants to show it: a bug report or a pull request that
should carry what the test did and where it broke ("make a video of this failing Playwright test", "turn
trace.zip into something I can attach to the issue"). A bug report you can watch: the test's own steps on
the screenshots the trace holds, then the failure slowed down.

## Essentials

- Two calls: `showtime repro <trace.zip>` (or `showtime repro -- npx playwright test <spec>`, also
  `-- pytest <file>`) writes `<job>/script.md` and stops; read it, then the same command with `--yes`
  renders it, every line filtered again (§ Steps)
- The `--yes` call writes `repro.mp4` (16:9, 1080p), `repro.srt`, `repro.poster.jpg`, `steps.json`,
  `repro.md` (to paste into the issue) and `project/`; check, render and qa run inside it (§ Steps)
- The film: title card (test, file:line, FAILED), one scene per step with a cursor, click ripple and box on
  the target, the failing step slowed down (source line, expected and received, error, console errors), an
  end card with the re-run command; planned for 10-40 s, long tests sum up their middle steps (§ The film)
- Narrated by `showtime voice` (`af_heart` unless `--voice`); `--no-voice` leaves captions only (§ The film)
- Privacy: typed values never shown or spoken (their fields covered on screen), paths, query strings, auth
  headers, `NAME=value` secrets and e-mails masked, `--redact <regex>` everywhere text shows; screenshots
  are shown as captured, so use a test account and watch the film before posting it (§ Privacy)
- Fast draft: `--yes --preview`; project and reports only: `--yes --no-render` (§ Options)
- Never describe a failure you have not read: quote `repro.md` or `steps.json`, not a guess (§ Pitfalls)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inputs | 36-45 |
| Steps | 47-76 |
| The film | 78-104 |
| Privacy | 106-149 |
| Options | 151-167 |
| Pitfalls | 169-181 |
| Read next | 183-186 |

## Inputs

- A Playwright trace: the `trace.zip` that `npx playwright test --trace on` (or `retain-on-failure`) and
  `pytest --tracing on` write under `test-results/<test>/`. Traces from the test runner carry step titles,
  locators and the test's file:line; traces from the library alone (pytest) still give every action, its
  target box, screenshots and the error.
- Or the command that runs the tests, after `--` (a single script too: `-- ./e2e.sh`). It runs without a
  shell, from the current folder.
- Helpful: patterns to hide beyond the defaults (account ids, customer names, internal hostnames) for
  `--redact`.

## Steps

1. **Write the script.** `showtime repro test-results/<test>/trace.zip`, or `showtime repro -- npx
   playwright test tests/login.spec.ts`. With a command, it adds `--trace retain-on-failure` (`playwright
   test`, also through `pnpm exec`, `yarn` or `node .../cli.js test`) or `--tracing retain-on-failure`
   (`pytest`, `python -m pytest`), and `--output` in a temporary folder, unless the command already sets
   them. It runs in your environment (your PATH, without what showtime sets for its own tools) with an
   empty stdin and `PLAYWRIGHT_HTML_OPEN=never` unless you set it (so the html reporter does not serve its
   report and wait for Ctrl+C), stops it after `--timeout` seconds (default 1800), and films the failing
   trace that started first (it says when several failed). Traces are looked for only where the runner
   was told to write (that folder, or your own `--output`), never across the working tree. A runner it
   does not recognize runs as it is: pass its trace instead.
2. **Read `<job>/script.md`.** The job folder is made only once a failing trace was parsed (a failed run
   leaves nothing behind): `showtime-out/repro-<timestamp>/` (beside the job the current folder is in,
   never inside it), or `--out <folder>`. It holds `script.md` (every caption, spoken line and on-screen
   text, keyed by scene, then the masked steps), `report.json` (the filtered timeline) and `shots/` (the
   trace's screenshots). The run's raw traces are deleted (`--keep-trace` keeps them in `<job>/work/`,
   unfiltered). Nothing is rendered in this call. Edit the text after a label, or delete a line to leave
   it out (a deleted spoken line leaves its scene silent).
3. **Render it.** The same command again with `--yes` (it finds the newest job made from the same trace
   or command), or `showtime repro --yes <job>`. Every line goes through the filters again (add
   `--redact` here too), then it narrates, writes `<job>/project` (a DOM project: `index.html`,
   `showtime.json`, `audio/mix.json`, the screenshots it uses, `repro.json`), runs `showtime check` (it
   stops on errors), `showtime render -o <job>/repro.mp4` and `showtime qa`, and prints the verdict (exit
   code 1 on a qa FAIL).
4. **Read the result, then watch it.** `repro.md` has the steps, the failure (expected, received, the last
   log line, the source line), the console errors and the re-run command, with a comment line to drag
   `repro.mp4` onto in an issue or PR. `steps.json` is the parsed timeline: each step's kind, caption,
   locator, file:line, duration, status, target box, and where it sits in the film. Quote these; do not
   paraphrase the error. Watch `repro.mp4` in full before you post it: screenshots are not filtered.

## The film

- **Title card:** FAILED, the test's name, its file:line, then the Playwright version, browser, step count
  and the failing step.
- **Steps:** each action on its screenshot from the trace, in a browser frame showing the page's address,
  with a step counter and, up to 24 steps, a row of dots (passed, current, failed). Clicks, checks and hovers
  show the frame before the action with a cursor travelling to the point and a ripple; fills and presses show
  the first frame taken after the step ended; the target's box is drawn when the trace records it, and the screenshot zooms in toward
  it (up to 1.6x). Beside it: the kind,
  a one-line caption ("Click the 'Sign in' button", "Type 16 characters into the 'Email' field"), the
  locator and file:line with the step's duration. A step after an error the test caught is no failure: the
  failing step is the one whose error ended the test.
- **The failure:** the screenshot at the moment it failed, framed in red, then about one beat a second: the
  caption, the failing source line (the trace carries the test file), expected and received side by side
  with the characters Playwright marks as different highlighted, the error's first line, and up to two
  console errors (`console.error` and uncaught page errors up to the failure).
- **End card:** the re-run command (the command you gave, else `npx playwright test <file>:<line>` for a test
  runner's trace; a library-only trace such as pytest's gets none) and the trace viewer command.
- **Length:** each step holds for its reading time (17 characters or 3 words a second; 2.2-4.2 s), the failure
  6.5-12 s, and the film is planned to stay within 40 s: a longer test keeps its first step and the steps just
  before the failure, and the passing steps between them become one "+ N passing steps" scene with up to six
  of their screenshots. Narration can lengthen a scene past these holds.
- **Sound:** narration from `showtime voice script` (one line per scene, read-back off), each line 0.3 s into
  its scene, a scene lengthened to fit its line; typed values are never spoken (fills, typed text,
  chosen options and unnamed keys are said without them). A quiet composed bed ducked
  under the voice, a click sound on clicks and checks, and a soft tone on the failure. `repro.srt` carries
  the same lines (two lines of at most 42 characters, at most 20 characters a second where the scene allows).

## Privacy

Traces can hold secrets. The filters run on every text the film, `repro.srt`, `steps.json`, `repro.md`,
`script.md`, `report.json` and the project show, in the first call and again on `--yes`:

- What was typed is never shown or spoken, in any field and through any API (`fill`, `type`,
  `pressSequentially`, `keyboard.type`, `insertText`, a key that is not a named key): the caption says
  "Type 12 characters into the 'Email' field". The values themselves are masked wherever else they appear
  (the source line, the call log, an expected value). `--show-typed` shows what was typed into fields that
  are not secret (filtered, never spoken); a field is secret when it is `type="password"`, its
  `autocomplete` is current-password, new-password or one-time-code, or its locator, name, id, label,
  placeholder or test id says password, secret, token, key or OTP. Text typed with `page.keyboard` goes
  into the focused field: right after a click, fill or focus on a field, that field; after a Tab or another
  key, a mouse click, a navigation or any step that may have moved the focus, a field showtime cannot name,
  which counts as secret (and cannot be covered: `script.md` says so).
- The field a value was typed into is covered on the screenshots, from that step on, while the trace's
  DOM snapshots show it on the page and holding text: the cover goes when the field is emptied, removed or
  replaced by another page, moves with the scroll of the page and of the boxes around the field, and moves
  to a later step's box when that step acts on the same field. When the page scrolled, a second cover also
  stays where the field was (unless it would hide the step's own target), since a fixed header does not
  scroll. A field the snapshots cannot follow (no id or name, a snapshot too large to read, none at all,
  as in a library-only trace) keeps its cover where it was until the page changes. Layout shifts and
  animations are not followed: watch the film.
- URLs lose their query string, fragment and `user:password@`; `file://` URLs show their last two path
  parts; paths on the machine (home, temp and system folders, drives) show only their last part, so no
  absolute or home path is written to the job's outputs or project.
- Console lines and error text: `Authorization: Bearer ...`/`Basic ...`, `token X`, `NAME=value` and
  `NAME: value` for token, secret, password, passwd, api key, auth, session and cookie names, and e-mail
  addresses (`••••••@corp.example`; `--show-emails` keeps them) are masked, as are the key and token
  shapes `showtime pr-video` masks. Each console line is cut to 300 characters, and at most 20 are kept.
  Expected and received values stay, filtered.
- `--redact <regex>` (repeatable) masks every match in captions, step text, the error, console lines, the
  source line, the re-run command, the narration and every file above. The patterns are not written to
  `job.json`.
- Network requests, headers, cookies and bodies are never shown (`trace.network` is never opened). DOM
  snapshots are read only to tell which fields are on the page and whether they are empty; nothing of
  them is kept or shown.
- Edits to `script.md` reach every output: what is not a line of its own is rebuilt from one (a step's
  target from its locator, the test's file from its location), and every text is filtered again.
- **Screenshots are shown as they were captured** (typed fields covered): whatever else the page displayed
  is in the video, and `--redact` does not touch pixels. Run the test with a test account, read
  `script.md`, and watch `repro.mp4` before you post it. Every call prints this.
- Not filtered: `job.json`, `SHOWTIME.md` and the render's own reports under `<job>/work/` record this
  machine's tool paths (local bookkeeping, never posted), and `--keep-trace` keeps raw traces.

## Options

- `--yes`: render the job's `script.md` as you left it (a call that writes the script never renders).
- `--out <folder>`: the job folder (new or empty; with `--yes`, the job to render).
- `--redact <regex>`, `--show-typed` (first call), `--show-emails`, `--keep-trace`: see § Privacy.
- `--timeout <seconds>`: stop the test command after this long (default 1800).
- `--no-voice`: captions only; `--voice <name>`: another voice (`showtime voice list`).
- `--cut-sounds`: a soft swoosh on each scene cut (off by default; the click on a click and the failure tone stay).
- `--music <style|catalog-id|none>`: pin the bed (default: chosen from the test, off the last films' music; a catalog
  track is downloaded once from its creator's site, nothing is sent, and its credit goes into `repro.md`; a style or
  `SHOWTIME_OFFLINE=1` keeps it fully local).
- `--size 720p`: a 1280x720 frame instead of 1920x1080; `--preview`: a fast draft render (720p at most).
- `--no-render` (with `--yes`): the project, `steps.json`, `repro.srt` and `repro.md` only; it prints the
  check and render commands.
- `--keep-work`: keep the render's `repro.work/` (audio stems) and `project/work/` (check's report), removed
  after qa otherwise.
- `--json`: the result as JSON on stdout (the test run's own output goes to stderr).

## Pitfalls

- A trace without screenshots (`screenshots: false` in the trace options) shows "no screenshot in the trace"
  in place of each page; turn screenshots on.
- An assertion has no target box in the trace, so the failing `expect` is shown by its source line and the
  expected and received values, not by a box on the page.
- The test passed: `showtime repro` stops with "the trace records no failure" (with a command: "no test
  failed"); it films failing tests.
- A command that wrote no trace.zip (another runner, tracing off in its config): turn tracing on yourself and
  pass the trace.
- Console lines are cut to 90 characters on screen; `steps.json` and `repro.md` keep up to 300.
- A huge trace (more than 20,000 files or 1 GB of events) is refused: run the one failing test alone.
- The film shows what the trace recorded; a claim about the cause belongs in the report text, from the code.

## Read next

`references/workflows/changelog-video.md` (a video for the PR that fixes it: `showtime pr-video`),
`references/qa.md`, `references/voice.md`, `references/captions.md`.

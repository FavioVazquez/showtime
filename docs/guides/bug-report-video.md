# Turn a failing test into a bug-report video

A browser test failed and you want the issue to show it: what the test did, step by step, and where it broke.
`showtime repro` turns the test's Playwright trace into a short narrated video, plus a Markdown summary to paste
into the issue. Typed values are never shown.

## Say this

> "Make a video of this failing Playwright test for the bug report."

Or run it yourself:

```bash
# from a trace: writes script.md and stops
showtime repro test-results/login-signs-in/trace.zip
# or run the test and film its failing trace
showtime repro -- npx playwright test tests/login.spec.ts
# after you read script.md: renders it
showtime repro --yes showtime-out/repro-<timestamp>
```

## What happens

1. With a trace, it reads it. With a command after `--`, it runs the test with `--trace retain-on-failure` added
   (or `--tracing retain-on-failure` for `pytest`), in a temporary output folder, and takes the failing trace.
2. It writes `script.md` (every caption, spoken line and on-screen text), `report.json` and the trace's
   screenshots into the job folder, and stops.
3. You read `script.md` and change or delete lines.
4. The same command with `--yes` (or `showtime repro --yes <job>`) filters every line again, narrates with a local
   voice, renders `repro.mp4`, runs `showtime qa`, and writes `repro.md`.

## What you get

- `repro.mp4` (16:9, 1080p): a title card (the test, its file and line, FAILED), one scene per step on the trace's
  screenshots with a cursor and the target boxed, then the failing step slowed down with the source line, expected
  and received, the error and the page's console errors, and an end card with the re-run command.
- `repro.md`: the steps, the failure, the console errors and the re-run commands, with a line to drag the video onto
  in a GitHub issue or pull request.
- `repro.srt`, `repro.poster.jpg`, `steps.json` (the parsed timeline) and `project/`.

## What it hides

- Values typed into fields are never shown or spoken: their fields are covered on the screenshots, and the
  captions say how many characters went in.
- Paths on your machine are shortened to the file name and URLs lose their query strings; auth headers,
  `NAME=value` secrets and e-mail addresses are masked in every line; `--redact <regex>` masks more (account ids, customer names, internal hostnames).
- Screenshots are otherwise shown as they were captured. Run the test with a test account, and watch the film
  before you post it.

## How long it takes

Tried for this guide on the test trace in `skills/showtime/tests/fixtures/repro/` (six steps, failing at the
last), on a 6-core Intel Mac: the `--yes` call took 2 min 30 s for a 34 s film.

## Phrases that change it

- "No voice" sets `--no-voice` (captions only); "another voice" sets `--voice <name>`.
- "Smaller" sets `--size 720p`; "a quick draft" sets `--yes --preview`.
- "A swoosh on the cuts" sets `--cut-sounds` (off by default; the click on a click and the failure tone stay).
- "No music" sets `--music none`. By default the bed is picked per test from showtime's music catalog (downloaded
  once from its creator's site; nothing is sent, and its credit goes into `repro.md`); a style or
  `SHOWTIME_OFFLINE=1` keeps it fully local.

## Limits

- It films a Playwright trace. A runner it does not recognize runs as it is: pass its trace instead.
- A trace from the library alone (pytest) has no step titles or file and line, but still every action, its target,
  screenshots and the error.
- It shows what the trace holds. It does not find the cause of the bug.

## The example

[The repro demo](https://github.com/FavioVazquez/showtime-examples/tree/main/examples/_repro) is the fixture test "signs in and greets the user" as a 34 s film, with its
`repro.md` and `script.md`. Your agent's guide: [repro.md](../../skills/showtime/references/workflows/repro.md).

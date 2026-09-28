## What and why

<!-- One paragraph: what changes for someone making a video, and why. Link the issue if there is one. -->

## How it was tested

Operating systems you ran it on (check all that apply; CI covers the rest):

- [ ] macOS, Apple Silicon
- [ ] macOS, Intel
- [ ] Windows 10/11
- [ ] Linux (distro: )

Paste the last lines of the test run (required):

```text
$ python skills/showtime/tests/run_all.py --fast
...
N/N test files passed in S s
```

- [ ] `python scripts/check_release.py --check` is clean
- [ ] New or changed commands have `--help` with examples, and CHANGELOG.md says what changed and why
- [ ] Anything that can fail prints what went wrong, why, and the exact fix (tracebacks only with `--debug`)
- [ ] Paths use pathlib, processes use argument lists, ffmpeg goes through `st.ff` (never a bare `ffmpeg`)
- [ ] Any new third-party asset or model is permissively licensed and its license is recorded
      (see `.out-of-scope/non-commercial-assets.md`)

## Output to look at (for visual or audio changes)

<!-- A contact sheet, a short clip, or loudness numbers from `showtime audio meter`. -->

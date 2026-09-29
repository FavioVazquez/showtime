# Workflow: edit real footage (talking head, interview, podcast, vlog)

Read this when the user hands you recorded video or audio and wants it edited: cut the ums and long
pauses, tighten a talking head, pull clips from an interview or podcast, pick the best takes, add
captions, reframe to vertical, clean the audio, fix the colour. Everything is driven by a word-level
transcript; you read text and images, never the raw video. The full reference is `editing.md`.

## Inputs

- One or more media files or a folder of takes. No path given: list the media files in the working
  folder (`*.mp4 *.mov *.mkv *.webm *.m4a *.wav`). Exactly one candidate: use it and say so. Ask only
  when there are none or several.
- The goal: length, platform/aspect, what must stay, what must go.
- Helpful: speaker count, names and jargon (for the transcription prompt), a music bed, a brand kit.

## Defaults

Keep the source aspect, frame rate and framing (no punch-ins on cuts unless asked), except for Reels/TikTok/Shorts: `--aspect 9:16 --captions
bold-pop` (face-tracked reframe). Remove fillers, shorten pauses over 0.5 s to 0.3 s; captions
`bold-pop` for vertical, `clean` for 16:9; `--grade auto` only when the footage looks off; denoise only
when noise is audible in the measurements; -14 LUFS / -1 dBTP for every edit (the same as everything else showtime delivers, podcasts and tutorials included; another level only when the user asks: `--lufs N`, or `--keep-loudness` to leave the source level). Ask at most:
target length/platform, and anything that must stay or go, and only when the request leaves it open.

## Steps

1. **Job.** `showtime job init <name>-edit --goal "..."` (add `--platform reels|tiktok|shorts|youtube`
   when named; qa then checks aspect, length cap and loudness for it). The printed folder is `<job>`;
   the edit files live in `<job>/edit/`, so `<job>` works as the argument of `edit render` and
   `edit view`.
2. **Inventory.** `showtime footage probe <file>` per file (rotation, fps, HDR, audio tracks), and
   `showtime footage scenes <file> --every 5 --job <job>` for a visual sheet in `<job>/work/scenes/`
   (never beside the user's footage); look at it.
   *Done when:* you know durations, orientation, audio tracks and what is on screen.
3. **Transcribe.** `showtime transcribe <folder or files> --edit-dir <job>/edit` (without `--edit-dir`
   the transcripts go to the job the media or the current folder is in, else a new `<name>-edit` job,
   never next to the user's footage; add `--speakers 2` for interviews,
   `--prompt "names, jargon"`, `--language es` for non-English, `--audio-track 1` for a mic on track
   2). Transcripts are cached by content, so a re-run is instant. The first run loads the model
   (it prints `loading model ...`; about 30 s on a mid-range laptop, a fixed cost per run), then
   progress over the audio. Tell the user the time first for long files. Read `guards.warnings` in
   each transcript.
4. **Read the material.** `showtime pack <job>/edit` and read `takes_packed.md` end to end:
   the hook line, retakes (keep the last clean one), the payoff, dead air, events worth keeping.
5. **Plan in 3-6 lines** (keep/cut logic, order, aspect, captions, music, look). Mechanical work
   (fillers, pauses, captions, reframing, loudness) is stated as an assumption and done. Wait for the
   user only when the plan drops content: picks between takes, removes sentences, reorders.
   *Done when:* the plan is in SHOWTIME.md, confirmed when it drops content.
6. **EDL.** `showtime edit cut <job>/edit/transcripts/*.json -o <job>/edit/edl.json` with the options
   that match the plan (`--max-pause 0.5`, `--remove w40-w52`, `--keep-time 12.5-40`,
   `--aspect 9:16`, `--captions bold-pop`, `--grade auto`, `--music bed.wav`, `--denoise auto`).
   Hand-edit ranges only with times copied from `takes_packed.md`. `showtime edit check <job>` (the
   job's latest EDL, or pass the EDL path): read the plan and the output time of every segment. Re-cutting never
   overwrites: the new EDL is `edl-2.json` (printed; from then on `<job>` in `edit render`/`edit view`
   means it); `--overwrite` replaces `edl.json` in place.
7. **Draft.** `showtime edit render <job> --preview`, then `showtime edit view <job>` and read every
   PNG (words, waveform and frames around each cut). Both print the file they used; `edit view`
   always shows the newest render (a re-render writes `preview-2.mp4`; `--overwrite` reuses
   `preview.mp4`). Read the render report (`edit render` prints `report <path>` and up to six
   warnings): `frames_ok` true, no warnings. A source enlarged more than 1.5x (a 720p clip reframed to
   1080x1920) is warned with a fix: a smaller EDL output size such as 720x1280, or `--fit blur`. Fix
   and re-render (unchanged segments are reused); at most three passes, then ask.
8. **Final.** `showtime edit render <job> -o <job>/final.mp4` (this `-o` wins over the EDL folder
   default in `editing.md`). Captions are burned last; a matching `.srt` with the video's name is
   written beside it.
9. **Poster.** `showtime deliver poster <job> --at <t> --bake` (the job's latest final) writes
   `final.poster.mp4` with the poster in frame 0 (and `final.poster.png`) and records both as the
   job's latest final and poster; a second bake of the same frame is skipped. The baked file is the
   deliverable: qa and exports follow it. Reels, TikTok and Shorts let the user pick a cover in the
   app, so the bake is optional there.
10. **Verify.** `showtime qa <job>` (the latest final; it prints which, uses the job's platform and
    checks the job's captions `final.srt`). Look at the sheet. For anything published, transcribe the output
    (`showtime transcribe <the checked file> --edit-dir <job>/work/qa-transcript`) and confirm no
    fillers or clipped words remain. Say what you could not check (you did not listen).
11. **Deliver.** Exports (`showtime deliver exports <job> --targets ...`: the latest final), share copy,
    the delivery card.

## Recipes

| Goal | Additions |
|---|---|
| Tighten a talking head | `edit cut --max-pause 0.5`, no punch-ins: jump cuts in a tightened talking head are expected and read as clean; a zoom in and back out at every cut reads as a gimmick (`edit check` flags it). Reframe only on request, one scale held per sentence or section (`editing.md` section 6) |
| Vertical from landscape | `--aspect 9:16` (face-tracked reframe), `--captions bold-pop`; or `showtime footage reframe <file> --aspect 9:16` for a whole clip |
| Podcast clip | `transcribe --speakers 2`, pick ranges by speaker lines, captions `clean` (loudness stays at the -14 default unless asked). Long episode: `transcribe <file> --from 21:30 --to 24:00` transcribes only that window (times stay on the episode's clock). Published transcript: align it (`showtime voice align`) and take speakers from its labels rather than diarization (captions.md, section 6) |
| Noisy room | `showtime footage denoise <file> --strength 0.7 -o clean.mp4` first, or `"audio": {"denoise": "auto"}` in the EDL |
| Colour | `showtime footage grade <file> --analyze`, then `--auto`, or a look (`showtime footage luts`); `--compare` writes a before/after still |
| Shaky phone clip | `showtime footage stabilize <file>` or `"stabilize": true` on a range |
| Music under speech | `"audio": {"music": "../music/bed.wav"}` (ducked automatically); compose one with `showtime audio compose --style underscore --dur <len>` (calm; `music.md`) |
| B-roll or logo | `overlays[]` in the EDL with output times from `edit check` |

## Pitfalls

- Declaring the edit done because the render exited 0: read the report and the cut views first.
- Writing ranges from memory: copy times from `takes_packed.md` or let `edit cut` compute edges.
- Cutting exactly at word boundaries: keep the padding (50 ms before, 80 ms after).
- Computing caption or overlay times from range sums: use the output times from `edit check`.
- Using an English-only model on other languages: pass `--language`.
- Moving word times by hand in a transcript: fix spelling only.

## Read next

`references/editing.md`, `references/captions.md`, `references/footage-tools.md`,
`references/platforms.md`, `references/qa.md`.

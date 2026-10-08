# Workflow: edit real footage (talking head, interview, podcast, vlog)

Read this when the user hands you recorded video or audio and wants it edited: cut the ums and long
pauses, tighten a talking head, pull clips from an interview or podcast, turn a long recording (talk,
panel, podcast, stream) into its best short clips, pick the best takes, add captions, reframe to
vertical, clean the audio, fix the colour. Everything is driven by a word-level transcript; you read
text and images, never the raw video. The full reference is `editing.md`.

## Essentials

- Defaults: keep the source aspect, fps and framing (no punch-ins); Reels/TikTok/Shorts get `--aspect 9:16
  --captions bold-pop`; fillers out, pauses over 0.5 s cut to 0.3 s; -14 LUFS / -1 dBTP unless asked
  (§ Defaults)
- Ask only for length/platform and what must stay or go, and only when the request leaves it open (§ Defaults)
- `showtime job init <name>-edit --goal "..."` (`--platform reels|tiktok|shorts|youtube` when named) (§ Steps)
- Inventory: `showtime footage probe <file>`, `showtime footage scenes <file> --every 5 --job <job>`; never
  write anything beside the user's footage (§ Steps)
- `showtime transcribe <files> --edit-dir <job>/edit` (`--speakers 2`, `--prompt "names, jargon"`,
  `--language`); tell the user the time first for long files; read `guards.warnings` (§ Steps)
- `showtime pack <job>/edit`, read `takes_packed.md` end to end; plan in 3-6 lines in SHOWTIME.md; wait for
  the user only when the plan drops content (takes, sentences, order) (§ Steps)
- `showtime edit cut <job>/edit/transcripts/*.json -o <job>/edit/edl.json` with the plan's options, then
  `showtime edit check <job>`; copy times from `takes_packed.md`, never from memory (§ Steps, § Pitfalls)
- Draft `showtime edit render <job> --preview`, then `showtime edit view <job>`: read every PNG and the report
  (`frames_ok` true, no warnings); at most three passes, then ask (§ Steps)
- Final `showtime edit render <job> -o <job>/final.mp4`; poster `showtime deliver poster <job> --at <t> --bake`
  (optional for Reels, TikTok, Shorts) (§ Steps)
- Verify: `showtime qa <job>`, `showtime look <job>`; for published work transcribe the output and confirm no
  fillers or clipped words; say what you could not check (§ Steps)
- Caption and overlay times come from `edit check` output times, not range sums (§ Pitfalls)
- Dress up a talking head: EDL `cards` anchored to phrases, `edit cards suggest` for moments, `edit check` until it
  lists no card problem, one EDL per aspect (§ Dress up a talking head)
- Text behind the speaker: a `behind` card (the speaker cut out over a big word, on the CPU); background blur or
  swap: its `background` (`blur`, `ground`, an image); the speaker alone with alpha: `showtime footage cutout`
  (§ Recipes)
- A long recording into its best clips: `showtime edit moments <job>` ranks candidates (suggestions only), you read
  their text and pick; `showtime edit clips <job> --preview`, the sheet, then the finals: one EDL, render and qa
  per clip, in parallel (§ Highlights from a long recording)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inputs | 52-58 |
| Defaults | 60-66 |
| Steps | 68-119 |
| Recipes | 121-136 |
| Dress up a talking head | 138-161 |
| Highlights from a long recording | 163-192 |
| Pitfalls | 194-204 |
| Read next | 206-209 |

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
    checks the job's captions `final.srt`), then `showtime look <job>` (`looking.md`). For anything
    published, transcribe the output (`showtime transcribe <the checked file> --edit-dir <job>/work/qa-transcript`) and confirm no
    fillers or clipped words remain. Say what you could not check (you did not listen).
11. **Deliver.** Exports (`showtime deliver exports <job> --targets ...`: the latest final), share copy,
    the delivery card.

## Recipes

| Goal | Additions |
|---|---|
| Tighten a talking head | `edit cut --max-pause 0.5`, no punch-ins: jump cuts in a tightened talking head are expected and read as clean; a zoom in and back out at every cut reads as a gimmick (`edit check` flags it). Reframe only on request, one scale held per sentence or section (`editing.md` section 6) |
| Vertical from landscape | `--aspect 9:16` (face-tracked reframe), `--captions bold-pop`; or `showtime footage reframe <file> --aspect 9:16` for a whole clip |
| Podcast clip | `transcribe --speakers 2`, pick ranges by speaker lines, captions `clean` (loudness stays at the -14 default unless asked). Long episode: `transcribe <file> --from 21:30 --to 24:00` transcribes only that window (times stay on the episode's clock); its best moments, several clips at once: § Highlights from a long recording. Published transcript: align it (`showtime voice align`) and take speakers from its labels rather than diarization (captions.md, section 6) |
| Noisy room | `showtime footage denoise <file> --strength 0.7 -o clean.mp4` first, or `"audio": {"denoise": "auto"}` in the EDL |
| Colour | `showtime footage grade <file> --analyze`, then `--auto`, or a look (`showtime footage luts`); `--compare` writes a before/after still |
| Shaky phone clip | `showtime footage stabilize <file>` or `"stabilize": true` on a range |
| Music under speech | `"audio": {"music": "../music/bed.wav"}` (ducked automatically); compose one with `showtime audio compose --style underscore --dur <len>` (calm; `music.md`) |
| B-roll or logo | `overlays[]` in the EDL with output times from `edit check` |
| Lower third, quote, data callout, list, side panel | EDL `cards` (§ Dress up a talking head) |
| Big text behind the speaker | a `behind` card: `{"type": "behind", "say": "<the phrase>", "text": "<one word>"}`; one per stretch, a word or two, on a calm shot (`editing.md` section 9) |
| Background blur or swap behind the speaker | the behind card's `"background": "blur"`, `"dim"`, `"ground"`, `"#rrggbb"` or an image file |
| The speaker cut out for another editor | `showtime footage cutout <clip> --from A --to B` (VP9 with alpha; `--format prores` or `png`) plus a matte file and a sheet to look at |

## Dress up a talking head

For a founder update, a podcast clip, a lecture or an interview that should look produced without touching the
footage: a title, a lower third, a pull-quote, a data callout, a chapter card, a list that builds as it is
said, a side panel, and the words that carry the message coloured in the captions (`editing.md` §9).

1. **Cut first.** Steps 1-6 above; the cards follow the words, so a later re-cut moves them.
2. **Find the moments.** `showtime edit cards suggest <job>` (the job's latest EDL): numbers with units, the
   speaker's name, list markers, quotable lines, topic shifts, stressed words. Pick 4-7 cards for a minute;
   one card on screen at a time, except a lower third under a title.
3. **Write the cards** into the EDL's `cards` with `say` phrases copied from the transcript, and
   `captions.emphasis` with 3-5 terms. Every name, role, number and label comes from the speaker's words or the
   source (a slate, the source page); a pull-quote is the speaker's exact line. A `look` id, or the job's brand
   kit.
4. **Check.** `showtime edit check <job>` prints each card's output times; fix every card problem it lists
   (reading time, overlap, captions, captions or cards over the face).
5. **One EDL per aspect.** 9:16 has less room: copy the EDL (`edl-916.json`, `"output": {"aspect": "9:16"}`,
   bold-pop captions), and drop or shorten what `edit check` flags. The captions move below the chin by
   themselves; a card with no room left there becomes a split (the speaker moves to the lower part).
6. **Preview and look.** `edit render <edl> --preview`, then `showtime snap <preview> --at <each card's middle>`
   and `edit view` (one band per card): no card on the face, nothing under the captions, numbers landed; for a
   behind card, frames at its start, middle and end at full size: the word readable, the speaker's edge clean.
7. **Final and qa** as in steps 8-10; qa repeats any card problem (`card_problem`; a behind card's
   `behind_hidden` and `matte_flicker` from the render's own measures).

## Highlights from a long recording

For a talk, panel, podcast, interview or stream of 20 minutes to a few hours that should become 3-10 short clips
(30-60 s, usually 9:16 with captions). showtime ranks the candidates and makes the clips; you judge them.

1. **Job.** `showtime job init <name>-clips --platform shorts` (or `reels`, `tiktok`; qa uses it for every clip).
2. **Transcribe the whole recording.** `showtime transcribe <file> --edit-dir <job>/edit`. Tell the user the time
   first: an hour of audio took under 6 minutes on a busy 64-core machine, 13 with `--speakers auto`. Speakers are
   optional here (the ranking found the same top four without them); pass `--speakers N` when you know N. Fix
   misheard names in `text` only (a published caption file is a good check); never move times.
3. **Rank.** `showtime edit moments <job> --count 10` (`--min 20 --max 60` by default: the clip's length once
   fillers and pauses are trimmed) prints a table and writes `<job>/edit/moments.json` (a few seconds for an hour).
   Each moment is whole sentences, with its opening line, why it ranks, a suggested title in the speaker's words and
   its full text (`editing.md` §10 lists the signals). Introductions, thanks and logistics rank lower.
4. **Read and pick.** Read each candidate's `text`, not only its score: keep the ones that stand alone, vary the
   voices and topics, and heed `why` ("starts on And", "the answer goes on after the end"). In `moments.json` set
   `"pick": true`, rewrite `title`, move `start`/`end` (edges snap to whole words; the clip says when an edge lands
   mid-sentence) and cut a stretch inside with `"remove": ["w12-w18"]`. Say what you picked and why.
5. **Drafts.** `showtime edit clips <job> --preview` renders the picks in parallel, each through qa, into
   `<job>/clips/preview/` with `sheet.jpg` (a row of frames per clip) and `clips.json`. Look at the sheet: a clip
   that opens on a wide shot with the speaker outside the crop, burned-in graphics cut by the crop, captions jumping
   off the face. Move the edges and run it again: an EDL you did not edit by hand is updated in place, so unchanged
   segments come from the cache.
6. **Finals.** `showtime edit clips <job>` (1080x1920 from 1080p footage: the 9:16 crop enlarges it 1.78x, which the
   EDL accepts and qa notes; a 720p source renders 720x1280). `--cards` adds a title card (the moment's title) and a
   data callout when the speaker says a number with a unit; `--aspect 1:1`, `--captions clean` change the look.
7. **Verify.** Read each clip's qa line in the table (`clips.json` keeps the findings), then `showtime snap <clip>
   --at <t>` on the opening, the middle and the end of every clip. A fix for one clip: edit its EDL in
   `<job>/edit/clips/`, then `showtime edit render <that EDL> -o <job>/clips/<its name>.mp4`.
8. **Deliver.** Share copy per clip (`platforms.md`), credits when the source asks for them.

## Pitfalls

- Declaring the edit done because the render exited 0: read the report and the cut views first.
- Writing ranges from memory: copy times from `takes_packed.md` or let `edit cut` compute edges.
- Cutting exactly at word boundaries: keep the padding (50 ms before, 80 ms after).
- Computing caption or overlay times from range sums: use the output times from `edit check`.
- Using an English-only model on other languages: pass `--language`.
- Moving word times by hand in a transcript: fix spelling only.
- Timing a card in seconds or as an `overlays[]` image: anchor it to the words (`cards`, `say`).
- Making clips from the top of the moments table unread: the ranking is a shortlist; a moment that needs the
  sentence before it, or ends before the answer does, is a bad clip whatever its score.

## Read next

`references/editing.md`, `references/captions.md`, `references/footage-tools.md`,
`references/platforms.md`, `references/qa.md`.

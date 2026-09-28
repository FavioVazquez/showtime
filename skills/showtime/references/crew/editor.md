# Crew brief: editor (footage)

Read this when you were dispatched as the editor of a showtime footage job (after
`references/crew/rules.md`).

**Your job: cut the user's footage by its transcript** into the video the contract describes, with
captions and other aspects when asked. References: `references/editing.md` (the workflow, the EDL,
the hard rules, self-evaluation), `references/captions.md`, `references/footage-tools.md`.

## How

You own the job's `edit/` folder. Follow `editing.md` section 1 step by step, with these limits:

1. Inventory each source with `showtime footage probe <file>`.
2. Transcribe one source at a time: `showtime transcribe <file> --edit-dir <job>/edit`. Transcripts are
   cached; never delete them. This is heavy: run it only when `TASK.md` allows it, and never while a
   browser capture runs.
3. `showtime pack <job>`, then read `edit/takes_packed.md` end to end before choosing anything.
4. Pick takes and write the EDL (`showtime edit cut ...`, then by hand). Keep breaths and pauses that
   carry meaning; cut fillers, false starts and dead air.
5. `showtime edit check <job>` until it passes.
6. A draft into your own folder: `showtime edit render <edl> --preview` (never `--job` or the
   final). Then `showtime edit view <edl>` and read every PNG: cut points, caption placement, framing.
7. Captions (`showtime captions ...`) in the style the platform needs; other aspects with
   `showtime footage reframe ...` when `TASK.md` asks.
8. Three iterations at most, then report what is left.

## The rule that matters most

Dropping content the user recorded is the user's decision. Write `edit/cuts.md`: every removed span
with source file, start and end time, the words, and why. List any dropped take, sentence or reorder in
your result under `NOTES`; the director confirms them with the user before the final.

## Deliver

`edit/edl.json`, `edit/cuts.md`, the draft and its views, caption files (`.ass`, `.srt`), and
reframed variants if asked.

Done when: `edit check` passes, the draft's report says `frames_ok: true`, you read every view
image, the length is within the contract, and `cuts.md` lists every removal.

## Never

- A final render or `showtime deliver`; the director renders the final.
- Touching the source footage files.
- Silently removing a whole take or a sentence the user might want.

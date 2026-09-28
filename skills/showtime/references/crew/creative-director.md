# Crew brief: creative director

Read this when you were dispatched as the creative director of a showtime job (after
`references/crew/rules.md`).

**Your job: the idea.** You pitch the concepts, set the tone, choose the device that carries the video,
and sign off the storyboard and animatic before the director locks them. You do not judge the finished
video (that is the critic) and you do not build scenes.

## Task shapes

`TASK.md` names one of these.

### A. Pitch round

1. Read the contract (`studio/brief.md` or SHOWTIME.md), the source summary it points to (capture
   folder, repo README, `brand.json`), the platform and the length. If the scriptwriter's `facts.md`
   is already in the job, use it; never wait for it.
2. Follow `references/story.md` sections 2, 3 and 7 and `references/tones.md`. Write **3 concepts from
   different paths plus 1 wildcard**. Different means another story shape, device or format, never
   only another palette.
3. Name the most typical idea for this category and reject it on purpose; it goes in the file so
   nobody pitches it later by accident.
4. Recommend one concept with a single reason. Mixing two is a valid recommendation.
5. Optional, when `TASK.md` asks for style frames: make `comps/` a small project
   (`showtime new dom <own dir>/comps --duration 3`) with one page per concept (`c1.html`, `c2.html`,
   `w1.html`) using the job's tokens (`showtime brand css <job>/brand.json`, a draft kit is fine; fonts
   from `references/typography.md`) and real captures. The director renders each page from its own
   folder, so everything a page loads lives inside `comps/`: copy captures and the logo file into
   `comps/assets/`, link fonts as `/_st/themes/fonts/<family>.css`, nothing from the network. Check each
   page once with `showtime snap <own dir>/comps --page c1.html --at <t>` (one frame per page) and look
   at the images; a page you change after its snap is re-snapped or named in `NOTES`.

Deliver:
- `concepts.md`: per concept an id (C1, C2 ... W1 for the wildcard), title, the idea in one line, what
  the viewer sees (naming one or two real capabilities in plain words), the hook for the first two
  seconds, a beat strip with rough timings, the spine (the device that holds it together), why it fits
  this audience and platform, the main risk, and what it needs (footage, VO, captures). End with
  "Rejected on purpose: ..." and "Recommended: C? because ...".
- `concepts.json`: a list of cards in the board's concept fields (`references/boards.md`, Concept), so
  the director pastes them into `board.json` unchanged: `id` (`c1` ... `w1`), `tag` (`C1` ... `W1`),
  `title`, `logline` (the idea in one line), `hook`, `duration`, `structure` (`[{label, dur}]`, the beat
  strip), `tone` (chips), `risk`, `unlocks` (what it needs), `wildcard: true` on the wildcard, and
  `recommended: true` with `why` on exactly one. No media paths: frames are added by the director.
- Tone: the `tones.md` preset and the knob changes, one line each, in `concepts.md`.

Done when: 3 + 1 concepts that pass `story.md` section 8 (distinctness) on your own honest reading,
exactly one recommended, every product fact traced to the source.

### B. Sign-off (before lock)

Inputs: the picked concept, `storyboard.json`/`storyboard.md`, panel thumbnails, the animatic file.
Look at every thumbnail and read the animatic's contact sheet if one is given. Check against the
contract and the picked concept:
- Does the hook land in the first 1.5 s? Is the spine visible in every scene?
- Does the order build (setup, turn, payoff) and end on the call to action?
- Does anything drift into the rejected typical idea?
- Is anything on a frame a claim without a source, or fake UI presented as real?

Deliver `signoff.md`: a verdict (`go`, `go with changes`, `no-go`) and numbered points, each tied to a
panel id or a timestamp, each with a concrete change. Keep taste notes separate from blockers.

## Never

- Concepts that differ only in colour, copy or music.
- Invented features, numbers or customers to make a concept work.
- Writing into `studio/`: the board belongs to the director.
- A logo redrawn, cropped, masked or recoloured on a frame: place the official file as it is.

## Tools and budget

Light CPU only: `showtime motion`, `showtime audio styles`, `showtime brand show`, `showtime new` for
your `comps/`, and one `snap --at` frame per style-frame page (5 at most). No renders, no captures.

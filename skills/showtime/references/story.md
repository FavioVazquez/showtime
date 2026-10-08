# Story: angle, hook, structure, lines

Read this before writing a plan. The story is where most of a video's quality gets decided, and it
costs nothing to redo. Motion, sound and render just carry it out.

## Essentials

- Before any scene, write "This video tells ___ (audience) that ___ (claim)." The claim is something someone
  could dispute or be surprised by, not a topic; cut every scene that does not trace back to it (§1)
- Mine the source in order: what it is (in its own words), the verb, visible proof, the oddest true fact,
  identity; plan at least one scene of real UI or output when the source has one (§2)
- Never open `.env`, keys, `secrets/` or credential files; keep internal hostnames, customer names and private
  data out of plan, video and share copy; use obvious fictional stand-ins and say so (§2)
- Build the visual device from the product's own world; a prop that fits another product's video unchanged
  fails the transplant test (§2)
- Hook: frame 1 already informative and moving (a launch hook is complete at frame 0); no black lead-in, fade
  from black, logo sting or "Introducing…"; readable by 0.3 s, first cut or big change by 2.0 s (§3, §4)
- Given a video to match, run `showtime reference <video> --job <job> --for <seconds>` first (§4)
- Explainers, and any video that asks the viewer questions: cold open with the stakes (~10 s), a persistent
  roadmap of the steps, a one-line bridge after each part, a close that answers the opening; then a cold
  first-viewer check of every part before the final render (§4)
- 1–6 words per card; on-screen text never repeats the narration; no banned filler ("unlock", "seamless" ...);
  narration as discrete cues, 1–2 sentences of 6–20 words per scene (§5)
- Sourced claims only: no invented numbers, benchmarks, users, quotes, logos or versions; a number on screen
  matches its source exactly; label sample data that could pass as real (§6)
- The user's own claim is checked too: a headline their data does not support ("5x faster" against their own
  52 s vs 40 s) is flagged before anything is built, with the figure the data does support, stated exactly:
  1.3x as fast, 30 % faster or 23 % less time, never "30 % less time" (§6)
- Specifics (file names, flags, output lines, paths, versions) need a source or a run saved to
  `<job>/work/evidence/<name>.txt` and logged with `job note --verified`; never fill a gap with a guess (§6)
- Every held frame must be true on its own; a failed capture is reported, never faked; no redrawn logos (§6)
- Open direction: 3–5 concepts from different paths, one unexpected; show all before recommending one (§7)
- Before building, run the distinctness check: two or more "no" answers mean revise the plan (§8)
- Videos that ask (showtime.json `"questions"`): ask before you tell (nothing earlier, the cold open included,
  gives an answer away), one idea per question, three choices, a reply that says why for each; the plan
  names the mechanism: `questions` in showtime.json, the HTML export (`showtime export html`) stops, the MP4
  shows a pause and think beat (§9)
- Given a storyboard table (Shot | Length | Visual | Narration) from another skill: `showtime new dom <dir>
  --from-storyboard <file>`, named in the plan; shots, lengths and narration kept as written; each Visual is
  a brief to build, not on-screen copy (§10)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. The one-sentence contract | 56-62 |
| 2. Finding the angle in the real product | 64-88 |
| 3. Hooks (the first 2 seconds) | 90-112 |
| 4. Structures | 114-162 |
| 5. Writing the lines | 164-177 |
| 6. Honesty rules (hard) | 179-207 |
| 7. Pitch round (when direction is open) | 209-226 |
| 8. Distinctness check (before building) | 228-241 |
| 9. Videos that ask | 243-265 |
| 10. A storyboard from another skill | 267-292 |

## 1. The one-sentence contract

Before any scene exists, write: **"This video tells ___ (audience) that ___ (claim)."**
- The claim is something someone could disagree with or be surprised by ("Your CI can finish before
  your coffee does"). A topic ("Our CI tool") is not a claim.
- Every scene must trace back to the claim. If you can't say why a scene serves it, cut the scene.
- After one viewing, a stranger should be able to say what the thing is, who it's for and how to get it.

## 2. Finding the angle in the real product

Mine the source (repo, site, PR, footage, brief) in this order and write down what you find:
1. **What it is**, in the product's own words: README first line, page `<title>`/`og:description`, hero copy.
2. **The verb**: the one thing a user *does* with it that makes a visible change (types a prompt,
   drags a file, runs a command, swipes). This verb becomes your hero shot.
3. **Visible proof**: real UI, real output, a real before/after, real numbers already published by the
   project (benchmarks in the README, changelog numbers, star counts shown on the page).
4. **The oddest true fact**: the detail a friend would repeat ("it runs on a toaster", "the whole thing is
   one file", "it's named after the founder's cat"). Oddness is where humor and memorability come from.
5. **Identity**: exact colors (CSS variables, theme-color), fonts, logo file, icon style, tone of the copy.

Security, always: never open `.env`, keys, `secrets/` or credential files. Keep internal hostnames,
customer names, emails and private data out of the plan, the video and the share copy. Swap in
obvious fictional stand-ins (`acme-demo`, "Sam Rivera") and say that you did.

**The metaphor comes from the product's own world.** A log analyzer lives among timestamps and
stack traces; a baking app lives among flour and ovens; a queue library lives in lines and tickets.
Build the visual device (the "spine") from that vocabulary and thread it through every beat.
**Transplant test:** if a prop could appear unchanged in another product's video (a glowing brain,
gears, a rocket, a generic dashboard), it didn't come from this product. Replace it.

What to show, best first: (1) the working product doing its job, (2) a recreated UI moment,
(3) an animated model of the core idea, (4) typography carrying the product's own copy.
Plan at least one scene of real UI or real output whenever the source has one.

## 3. Hooks (the first 2 seconds)

Rules that are never broken:
- Frame 1 is already informative and already moving. No black lead-in, no fade from black, no logo sting,
  no "Introducing…" opener.
- Text is readable by **0.3 s**. The first cut or big change happens by **2.0 s**.
- The hook speaks the viewer's outcome language, never internal vocabulary (file names, function names,
  feature lists). A number goes in the hook only when it carries stakes ("11 minutes → 40 seconds"),
  never when it's an inventory ("23 files changed").
- One hook per video. The claim lands by the second beat. Everything after that is evidence.

Hook catalog (pick based on what the source actually offers):
| Hook | Shape | Needs from the source |
|---|---|---|
| Result first | Show the finished outcome, then rewind ("This took 3 seconds") | A visible output |
| Before/after split | Pain on the left, relief on the right, one line | A real before state |
| Bold claim | 3–6 words, huge, on motion | A claim you can back up in the video |
| Stakes number | One number with its unit and consequence | A real published number |
| Pattern interrupt | Something that shouldn't be there, handled deadpan | Product absurdity or a strong visual |
| Pain validation | Name the exact annoyance the viewer has today | A clear audience |
| Question | A question the viewer already asks themselves | Only if the answer arrives by 4 s |
| Live action | The verb happening mid-stream (cursor already typing) | Real UI or demo |
| Contrast | "Everyone does X. This does Y." | A real point of difference |

## 4. Structures

Given a video to match ("like this"), run `showtime reference <video> --job <job> --for <seconds>` first and
build the storyboard from the brief in its `reference.md` (`references/reference.md`).

Times are for the default length. Scale proportionally, but keep the hook at ≤3 s.

**Launch (20–45 s social, 60–90 s hero).** 4–6 scenes, one message each, handed over by camera
cuts and dissolves, not layout changes, the camera still (`workflows/launch-video.md`, scene grammar): hook (the promise or the
problem, complete at frame 0, 3.5–6 s) → the verb (the product doing its one job, a real command or
capture, the result landing and marked) → 1–3 proof beats in the same window, each "verb then
result" with the result held ≥1.5 s → end card on the music's swell: name, one-line value,
install/CTA, URL, held ≥3 s. A real number or quote may replace one proof beat when it is sourced.
**Explainer.** Pick one: concept (name → mechanism, one layer at a time → implication); process
(3–6 steps on one consistent stage); list (hook → N parallel items, three is strongest → wrap);
story (setup → tension → turn → resolution → lesson). Never follow the source's paragraph order.
**The explainer shape (the default for explainers and for any video that asks the viewer questions).**
A first-time viewer must always know why the part on screen is there. Without these four pieces a run of
questions feels random, however good each answer looks:
1. *Cold open, about 10 s, before the first question or step:* the stakes in plain words, who claims what
   and what the video will do about it. "Last week a well-known researcher argued that X. His evidence is
   one Y from 2016. Let's test his argument, one question at a time." The hook rules still hold (§3):
   frame 1 is already informative.
2. *Roadmap:* the 3–5 steps as one persistent, readable element (a numbered rail, a checklist), the
   current step lit at each part, so the viewer always knows where they are.
3. *Bridges:* after each part, one short spoken line that leads into the next, so each step follows from
   the last ("So the move came from search. Does a language model search too?").
4. *Tie-back:* the close answers the opening claim in one line, then the end card.
Before the final render, check it cold: a reviewer who never read the brief goes through the parts in order
(frames and narration only) and answers for each "Do I know why this is here, and how it connects to the
opening?" Every "no" gets fixed (`review.md` §1, the first-viewer pass; the critic does it from `story.txt`).
**Tutorial / walkthrough.** Outcome preview (2–4 s) → steps, one action per spoken sentence, a
consistent stage, camera move before each action → recap card → next step. Over 2 min: chapters.
**Data story.** Headline as the takeaway ("Build time fell 74%") → context state → the change →
one annotation → implication. One insight per chart state.
**Social short (≤30 s, vertical).** Hook → 3–5 fast beats with one idea each → punchline or loop-back.
Design the last frame so it flows into the first frame on replay.
**Music video / beat piece.** The track is the spine: sections follow real musical changes, not a
template. Scenes = distinct visual treatments (usually 1–6), not beats. See `pacing.md` for grid trust.
**PR / changelog.** Pick one: changelog (hook → 2–4 equal change items → wrap), feature reveal
(outcome → impact → name the change → diff → mechanism → callback), fix explainer (problem →
how the bug happened → before/after → it working), refactor (the smell → before/after structure →
same inputs, same outputs → evidence). Alternate code and mechanism scenes. Show 2–4 real hunks,
4–12 lines each, never whole files. Credit the people who wrote the code.
**Talking-head recut.** The speaker is the spine. Cut dead air and fillers and let the jump cuts
stand (no zoom in and back out at every cut), add B-roll or cards only over abstract stretches, and
caption everything.
**Trailer / teaser (6–30 s).** Withhold something. Mood → escalating fragments → title → one
sting. Show the world, not the feature list. The name lands last.

## 5. Writing the lines

- One idea per card: 1–6 words on screen. A sentence on screen is a failed card.
- On-screen text never repeats the narration word for word. Captions already do that. On-screen text is
  the payload: the number, the name, the verb.
- Use the product's own words over your words. Specific beats clever.
- Banned filler: "streamline your workflow", "unlock", "supercharge", "elevate", "seamless",
  "the power of", "game-changer", "revolutionize", "next-level", "excited to share".
- Narration is written as **discrete cues** ("First the file lands, then the preview builds, then it ships"),
  because each cue becomes a reveal point. 1–2 sentences per scene, 6–20 words.
- Write for the ear: contractions, short words, varied sentence length. Read it aloud once.
- Spell out what a voice engine must say: "10x" → "ten times", "API" → "A P I", "v2.3" → "version two
  point three", "acme.dev" → "acme dot dev". The screen can show the exact figure.
- Humor comes from the product's own truth, delivered straight. Never punch down or mock users.

## 6. Honesty rules (hard)

- No invented claims, numbers, benchmarks, user counts, ratings, testimonials, press quotes, awards,
  customer logos or version numbers. If the source doesn't state it, the video doesn't either.
- Illustrative UI content is fine when it's obviously illustrative ("Exported ✓" toasts, placeholder
  names, sample data). When sample data could be mistaken for real results, label it ("sample data").
- A number on screen must match its source exactly (you may round only in narration).
- **The user's claims are claims too.** A headline the user asks for is checked against the data they
  gave before anything is built. "5x faster than X" next to their own "X 52 s, ours 40 s" is not
  supported: say so in the first lines, show the arithmetic, offer headlines the data supports, and keep
  "5x" only if they send a source for it. State a ratio the way it is true: 52 s → 40 s is 1.3x as fast,
  30 % faster or 23 % less time; "30 % less time" is wrong (speed and time are not the same percentage).
  When in doubt, show the two measured numbers.
- **Specifics are claims too.** File names, flag spellings, output lines, line counts, paths, error
  messages and version strings on screen each need a source: the docs (README, CHANGELOG, site) or
  output you produced by running the product in this job. Run it, save the transcript
  (`<job>/work/evidence/<name>.txt`, the command and its exact output) and log it
  (`job note --verified "config path: ~/.config/acmectl/config.toml (ran acmectl init, evidence/init.txt)"`).
  What you can't source, make obviously generic (`file.txt`, `…`) or leave out. Never fill a gap
  with a plausible guess (a file name, an extra flag, a count).
- **Incidental specifics cost more than they earn.** A line count, an internal function body or an
  exact file size proves nothing to the viewer and is one more thing that can be wrong: show them
  only when they are the point.
- **Every held frame must be true on its own.** A viewer (or a reviewer scrubbing stills) may see any
  frame: an animated "before" state that looks like a result (unsorted lines under a sort command)
  must read as the input (label it, dim it) or pass in under ~0.4 s; hold the real output longest.
- If a capture or fetch fails, stop and say so. Don't fake the product with a made-up UI and present it as real.
- Don't redraw third-party logos. Use the official files, or leave them out.
- Human-in-the-loop products keep the human as the protagonist. Don't imply automation that doesn't exist.

## 7. Pitch round (when direction is open)

Run it when the user hasn't said what the video should be. Skip it when they have.
1. Answer privately: what does this subject look like in its own world? What does the target feeling
   look like as a frame (urgency = compression, awe = one thing too big for the frame, calm = empty
   space)? Where will it play (feed = fight for the first second; lobby screen = ambient)? What does
   *every other video* in this category look like?
2. Write **3–5 concepts, each from a different path**: the product's world, the emotion, the audience
   (meet or deliberately break expectations), the category cliché inverted, an unusual format (a
   recipe card, a countdown, a letter, a weather report, a trading card, a museum label).
3. At least one must be **unexpected**. Your own estimate that another model would pitch it should be
   under 10%. If none clears that bar, generate again.
4. Give each concept three lines: the idea, what the viewer sees (naming 1–2 capabilities in plain words),
   the opening hook. Show all of them **before** recommending one, then recommend with a single reason.
   Mixing concepts is a valid answer. Quick mode: one round only. Studio mode: concepts go on a board
   with style frames, and "more like X" rounds are allowed (`studio.md`).
5. In autonomous runs, do this internally and report the chosen concept plus the most typical one you
   deliberately rejected.

## 8. Distinctness check (before building)

Answer honestly. Two or more "no" answers means revise the plan.
- Does the opening frame look like *this* product, recognizably, even with the logo covered?
- Is there one visual device (spine) that returns at least twice?
- Would the transplant test fail for every prop, meaning none could move into a competitor's video unchanged?
- Is there at least one frame worth posting as a still?
- Does the video contain one moment of surprise (a turn, a reveal, a joke, a scale change)?
- Is the pacing varied (short-short-long), not a metronome of equal cards?
- Did you avoid the category's default look (purple-blue gradient, floating glass cards, generic
  particles, stock bokeh, everything centered with equal weight)?
- Could you cut 20% and lose nothing? If yes, cut it.
- Does it look different from your last five videos (`showtime history`; `showtime check` warns with
  `look_repeat`)? With a reference clip, did you take its grammar and none of its content (`reference.md`)?

## 9. Videos that ask

An explainer can stop and ask before it tells (showtime.json `"questions"`: the HTML export pauses and
asks, the MP4 shows a "pause and think" countdown; `html-export.md` § Questions).
- **Ask before you tell.** Ask at the step the viewer can almost take alone, then show it. A question
  the next line answers anyway, or one nobody could guess, is a quiz, not a step.
- **One idea per question.** The question names exactly one thing to decide; three or four questions
  in a 60-90 s video, each its own chapter, with the answer shown between them.
- **Three choices**: the right one, the near miss most people pick, and one that shows a different
  misunderstanding. Short (1-4 words), parallel, none a joke.
- **The reply explains why**, for every choice: "1 + 2 × 5 = 11, one step too far" teaches more than
  "Wrong". Under 15 words, and true (§6).
- The narrator asks the question out loud (its line id is the question's `at`), the countdown is
  silent under ducked music, and the reveal is the next line.
- **Nothing gives an answer away early.** The cold open poses the puzzle; it does not show the result a
  later question asks about (an opening "the tower adds up to exactly 3" spoils "what does it add up
  to?"), and no step answers the next question before it is asked.
- **The plan says how it asks.** Lay it out in the explainer shape (§4), each piece visible in the plan: the
  cold open (its line), the roadmap as an on-screen element with its 3-5 step labels, a bridge line after each
  part, and the close's line that answers the opening in so many words; each question sits in its place,
  before its answer. Then name the mechanism: the questions go in showtime.json
  `"questions"` (`at` = the narrator's line), `showtime export html` makes the page that stops and waits
  for an answer, and the MP4 shows the pause and think beat. The user then knows what they will get.

## 10. A storyboard from another skill

Some skills plan a video and hand it over as a Markdown table, one row per shot: Shot | Length | Visual |
Narration (Chinese 镜头 | 时长 | 画面 | 旁白 too; columns in any order, extra ones such as On screen or Sound).
Start from it instead of a template's scenes:

- `showtime new dom <job>/project --from-storyboard storyboard.md` (`short` for 9:16; `-` reads the table from
  stdin; a storyboard.json from the storyboard artist works too). One scene per shot (`shot-1`, `shot-2` ...),
  timed from the lengths; a missing length is estimated from the narration.
- Each scene shows a dashed brief: the Visual as written. It says what to build; it is not on-screen copy. Only a
  card or title's quoted words, text after `text:` and an On screen column are shown as written. Build every
  shot's picture from its brief, and add nothing the storyboard and its sources do not support (§6).
- The narration is `narration.md`, one `## shot-N` line per narrated shot, pinned (`{at=...}`) where its shot
  starts. Run `showtime voice script <dir>/narration.md -o <dir>/voice`, then the `retime --from-voice` line `new`
  prints: shots keep their planned lengths where the voice fits and grow where it does not. `new` warns at
  planning rates (2.8 words/s, 3.2 Chinese characters/s) and retime names the shots the voice outgrew. Cut words
  rather than accept a rushed read.
- A Narration cell that is empty, a dash or only a direction in brackets (`(pause)`, `(silence)`, `[beat]`) is a
  silent shot: no line is voiced, the scene is marked `data-silent` and keeps the table's length, and the next
  line's pin counts it. `retime --from-voice` lets that pin win: the silent shot fills the gap up to it, so the
  shots after it do not drift late (`render.md`, retime).
- The table's lengths are the plan; the voice decides. `storyboard.json` keeps the plan, `storyboard.md` goes to
  the critic's review pack. `check` warns (`storyboard_brief`) while any brief is left.
- The plan you show lists the shots in order with their lengths and narration exactly as written, says what
  each Visual brief becomes on screen, and names the command (`--from-storyboard`). Change nothing silently: a
  length the voice will outgrow or a line you would cut is named, with the reason, for the user to decide.

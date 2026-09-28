# Story: angle, hook, structure, lines

Read this before writing a plan. The story is where most of a video's quality gets decided, and it
costs nothing to redo. Motion, sound and render just carry it out.

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

Times are for the default length. Scale proportionally, but keep the hook at ≤3 s.

**Launch (20–45 s social, 60–90 s hero).** Hook 0–3 → tension (the problem in one image) 3–8 →
reveal (name + hero UI, on the strongest downbeat) → 2–4 feature beats, each "verb then result", each
ending on a result frame held ≥0.7 s → optional proof beat (a real number, a real quote) → close:
logo, one-line value, URL/CTA held ≥2.5 s.
**Explainer.** Pick one: concept (name → mechanism, one layer at a time → implication); process
(3–6 steps on one consistent stage); list (hook → N parallel items, three is strongest → wrap);
story (setup → tension → turn → resolution → lesson). Never follow the source's paragraph order.
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

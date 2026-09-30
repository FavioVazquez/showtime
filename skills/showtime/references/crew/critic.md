# Crew brief: critic

Read this when you were dispatched as the critic of a showtime job (after
`references/crew/rules.md`).

**Your job: an honest second pair of eyes** on a draft or a final candidate, seen as a stranger sees
it. You receive one file: `CRITIC.md` in a review round folder built by `showtime review-pack`. It
replaces `TASK.md` for you: it names the video, the pack's images and what to answer. The protocol is
`references/review.md` sections 1 and 3.

## How

1. Read `CRITIC.md` fully. Then look at every image it lists: `sheet.jpg`, `scenes.jpg`, `cuts.jpg`
   (double exposures and flashes hide there), every file in `frames/`, `loudness.png`, the small
   thumbnail. Read the `qa/` verdict and the `context/` files (brief, storyboard, captions).
2. **Type detail pass.** Open every `frames/text-*.png` crop (the largest text lines, cut from full-size
   frames) and every title or text frame in `frames/` at full size; never judge type from the contact
   sheets, which shrink these flaws away. For each line check: words, math and numbers share one
   baseline (a formula, a superscript or a number must not sit lower or higher than the words beside
   it); they look one size (matching x-heights) and one weight (thin math beside bold words reads
   broken); kerning and word spacing are even; no widow (one word alone on a last line) or orphaned
   punctuation. Measure offsets in pixels on the crop and quote them in the finding.
3. Answer the eight questions in `CRITIC.md` (hook, clarity, readability, craft, distinctness, poster,
   honesty, story logic) from what you see, not from what the brief says was intended. A launch film's
   brief adds a checklist (scene count, continuous scene changes, holds, type system, motion, music on
   the phrases, end card): judge every line of it too. For story logic,
   go shot by shot: say what a stranger would think each shot is and what job it does; flag any shot
   that is there only because it looks good.
4. Write `FINDINGS.md` in the same round folder, in the format `CRITIC.md` gives:
   - findings sorted **Blocker**, **Should-fix**, **Polish**, each with a timestamp and a frame path
     from the pack, what is wrong, and a concrete fix. A finding without a location does not count;
   - what works (so it survives the fixes);
   - what you declined to judge and why (for example, you cannot hear the audio: judge the loudness
     plot and the captions instead);
   - a verdict: `ship`, `ship after fixes` or `not ready`;
   - the absolute verdict, `WOULD I POST THIS: yes | no -- one reason`: would you post this under your own
     name, watched once at full size by a stranger? The bar is "not cheap, broken or wrong", not "flawless":
     with only should-fix and polish findings it is usually a yes. Say no when a blocker stands or the whole
     video reads as cheap at a glance (captions in stepped boxes, a player's controls in the footage, a small
     or soft recording in big borders); one flawed shot is a should-fix. Judge the video alone, never "better
     than the last version". In quality mode a "no" holds delivery like a blocker;
   - from round 2, a `PREVIOUS` line per earlier blocker or should-fix: `fixed: ...` or `not fixed: ...`,
     naming what it was about (a caption should-fix stays open until a later line names the captions and
     says `fixed`, or the maker writes `won't fix: <reason>`);
   - the best poster frame.

Done when: `FINDINGS.md` exists in the round folder and every finding has a timestamp and a frame path.

## Pairwise rounds

A brief in `round-N/order-1/` or `order-2/` compares two versions, `X` and `Y`, shown in the order it
names; another critic judges the other order. Look at every image of both (`../X/`, `../Y/`, the
side-by-side `compare-*.jpg`, both `qa.txt` and `transcript.txt`), answer the questions for each, then
give `PREFERENCE: X | Y | tie` (the one you would ship), then `WOULD I POST X:` and `WOULD I POST Y:` (yes or
no, one reason each, each judged alone: preferring one does not make it postable). Every finding names its video (`[X]` or `[Y]`)
besides its time and frame. Which version is newer is hidden on purpose: never look for it (the
`.pairwise-keys/` folder, other `order-*` folders, file dates). Write `FINDINGS.md` next to your brief.
No scores in any round: do not rate a video on a number scale.

## Severity

As `CRITIC.md` defines it. Rate what you see; nobody may tell you what to ignore. A self-imposed
"minor at most" is how real problems ship.

## Never

- Editing the project, re-rendering, running the showtime workflow, or fixing anything yourself.
- Writing anywhere but `FINDINGS.md` next to the `CRITIC.md` you were given.
- Reading the conversation or asking the author what they meant: judge the pack.

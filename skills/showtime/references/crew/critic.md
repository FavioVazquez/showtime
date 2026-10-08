# Crew brief: critic

Read this when you were dispatched as the critic of a showtime job (after
`references/crew/rules.md`).

**Your job: an honest second pair of eyes** on a draft or a final candidate, seen as a stranger sees
it. You receive one file: `CRITIC.md` in a review round folder built by `showtime review-pack`. It
replaces `TASK.md` for you: it names the video, the pack's images and what to answer. The protocol is
`references/review.md` sections 1 and 3.

## How

1. Read `CRITIC.md` fully. Then look at every image it lists: `sheet.jpg`, `scenes.jpg`, `cuts.jpg`
   (double exposures and flashes hide there), every file in `frames/`, `loudness.png`, `hearing.png`, the
   small thumbnail. Read the `qa/` verdict. Leave the `context/` files (brief, storyboard, captions) for after
   step 2.
2. **First-viewer pass, cold.** Before you read the brief, go through `story.txt` (pairwise: each video's
   `story.txt`) in order: each part's middle frame and the narration said during it, with the contact sheet
   for what happens between. You are someone who never read the brief. For each part answer: "Do I know why
   this part is here, and how it connects to what the opening said the video is about?" Write one line per
   part under `FIRST VIEWER` (`- part 2 (8.00-21.50s) frames/...: no -- why`). Every "no" is also a
   Should-fix with a concrete fix (a one-line spoken bridge from the part before, the steps as a persistent
   roadmap with the current one lit, a cut); a Blocker when the opening never says what the video is about or
   why it matters. A video that asks the viewer questions must say why before the first one. Then read the
   `context/` files.
3. **Type detail pass.** Open every `frames/text-*.png` crop (the largest text lines, cut from full-size
   frames) and every title or text frame in `frames/` at full size; never judge type from the contact
   sheets, which shrink these flaws away. For each line check: words, math and numbers share one
   baseline (a formula, a superscript or a number must not sit lower or higher than the words beside
   it); they look one size (matching x-heights) and one weight (thin math beside bold words reads
   broken); kerning and word spacing are even; no widow (one word alone on a last line) or orphaned
   punctuation. Measure offsets in pixels on the crop and quote them in the finding.
4. **Hearing pass.** You cannot listen, so `audio.txt` measures what an ear would catch and `hearing.png`
   plots it: each voice line's level over the music and its words per minute, pauses and near silence, the
   level on both sides of every cut, each effect's timing and level, how the music ends, the peaks, how
   loud it is heard on a phone (the mix above 300 Hz: `on a phone speaker: -27.6 LUFS, 13.6 LU under the
   mix` is a video most viewers hear far too quiet), and the read-back (each name or number the voice-over
   was heard saying differently from the script). Go
   through the checks `CRITIC.md` lists and write one line per check under `HEARING` (`- voice over music:
   problem -- line 4 sits 5 dB over the bed`). Judge only what the numbers and `transcript.txt` support and
   quote them; every problem is also a finding with its time and `hearing.png`. What numbers cannot show (how
   the voice sounds, a mispronounced word the read-back does not list, harsh s sounds, whether the music fits)
   goes under `DECLINED TO
   JUDGE`, never a guess.
5. Answer the eight questions in `CRITIC.md` (hook, clarity, readability, craft, distinctness, poster,
   honesty, story logic) from what you see, not from what the brief says was intended. A launch film's
   brief adds a checklist (scene count, continuous scene changes, holds, type system, motion, music on
   the phrases, end card): judge every line of it too. A showreel's brief has the showreel rubric
   instead (energy, density, craft, surprise, ending): judge every line; there a tame reel is a finding,
   flash words are not, and a shot that is there because it looks good is doing its job. For story logic,
   go shot by shot: say what a stranger would think each shot is and what job it does; flag any shot
   that is there only because it looks good (not in a showreel).
6. Write `FINDINGS.md` in the same round folder, in the format `CRITIC.md` gives:
   - the `FIRST VIEWER` lines, one per part;
   - the `HEARING` lines, one per check of the hearing pass;
   - findings sorted **Blocker**, **Should-fix**, **Polish**, one bullet each, each with a timestamp and a
     frame path from the pack (a sound finding: a timestamp and `hearing.png`), what is wrong, and a concrete
     fix. A finding without a location does not count.
     The maker must fix or waive every blocker and should-fix before delivery, so rate honestly both ways;
   - what works (so it survives the fixes);
   - what you declined to judge and why (for example how the voice sounds: the hearing pass covers what the
     numbers show, nothing more);
   - a verdict: `ship`, `ship after fixes` or `not ready`;
   - the absolute verdict, `WOULD I POST THIS: yes | no -- one reason`: would you post this under your own
     name, watched once at full size by a stranger? The bar is "not cheap, broken or wrong", not "flawless":
     with only should-fix and polish findings it is usually a yes. Say no when a blocker stands or the whole
     video reads as cheap at a glance (captions in stepped boxes, a player's controls in the footage, a small
     or soft recording in big borders); one flawed shot is a should-fix. Judge the video alone, never "better
     than the last version". In quality mode a "no" holds delivery like a blocker;
   - from round 2, a `PREVIOUS` line per earlier blocker or should-fix, by the id `CRITIC.md` lists:
     `fixed r1-S2: ...` or `not fixed r1-S2: ...`, naming what it was about. Your "not fixed" reopens a
     finding the maker marked fixed;
   - the best poster frame.

Done when: `FINDINGS.md` exists in the round folder, it has a `FIRST VIEWER` line per part and a `HEARING` line
per check, and every finding has a timestamp and a frame path (or `hearing.png`).

If writing `FINDINGS.md` fails (some hosts deny Write to sub-agents), do not shorten anything: put the whole
answer, exactly as the file would hold it, in your last message inside one ``` block, after the return contract
(the 20-line limit does not apply to that block), with `STATUS: DONE_WITH_NOTES` and the note "FINDINGS.md not
written (Write denied): the answer is below". The director saves it with `showtime review-findings`.

## Pairwise rounds

A brief in `round-N/order-1/` or `order-2/` compares two versions, `X` and `Y`, shown in the order it
names; another critic judges the other order. Look at every image of both (`../X/`, `../Y/`, the
side-by-side `compare-*.jpg`, both `qa.txt`, `transcript.txt`, `story.txt`, `audio.txt` and `hearing.png`), do
the first-viewer pass and the hearing pass for each (lines tagged `[X]` or `[Y]`), answer the questions for each, then
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

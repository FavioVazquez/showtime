# Review: the critic pass and acting on feedback

Read this when a video is headed for publishing (the user says it will be posted, shown, or sent), when the
user asks for a critique, or when the user (or a critic) sends notes on a draft, storyboard or animatic.
The checklists live in `qa.md`; this file is the review protocol (self-review, critic, notes).

## 1. Pick the tier

- **Quick work** (drafts, internal, "just make it"): self-review. Run `showtime qa <job>` (the latest
  final), open the contact sheet it writes and look at it, check the brief's must-show list, and ask
  yourself the questions below. No sub-agent.
- **Publish-bound or studio work**: one critic pass by a fresh sub-agent on the final candidate (optionally
  also on the first look). Before the final render, the `showtime:researcher` checks every claim and
  asset license (`crew/researcher.md`). The critic sees files, never the conversation. This is the only critic
  protocol; `qa.md` defers to it.

Self-review questions (also what a critic weighs):
1. Hook: at 1.5 s, does a stranger know what this is about and want to keep watching?
2. Clarity: after the whole video, could they say what it is, who it's for and how to get it?
3. Readability: is any text too small, too short-lived, low-contrast or in a platform UI zone?
4. Craft: alignment, spacing, consistent type and colour, clean transitions (check mid-cut frames), no
   muddy double exposures, no effects the tone does not justify. Then the **type detail pass**: look at
   every title and text frame at full size (the pack's `frames/text-*.png` crops and the full frames in
   `frames/`, never only the contact sheets, which shrink these flaws away) and check each line: words,
   math and numbers on one line share one baseline (a formula, a superscript or a number sitting lower
   or higher than the words beside it reads broken); they look one size (matching x-heights) and one
   weight (thin math beside bold words); kerning and word spacing are even; no widow (one word alone on
   the last line) or orphaned punctuation. Any of these in a title, the hook or the poster is a
   Should-fix. Manim scenes: `showtime manim check` flags mixed lines (`baseline_mismatch`,
   `xheight_mismatch`, `mixed_type`); build them with `mixed_line()` (`references/manim.md`).
5. Distinctness: could these frames belong to a different product unchanged?
6. Poster: which single frame would you post as the thumbnail? Is frame 0 that frame?
7. Honesty: does anything look like an invented claim, number, testimonial or fake UI presented as real?
8. Story logic: for every shot, what does a stranger think it is, and why is it here? A shot that is
   pretty but unexplained (a random landscape after a reveal, footage unrelated to the claim beside
   it, a visual that only makes sense to the author) is a Should-fix; one at the hook or the payoff is
   a Blocker. Walk the scene list in order and name the job of each shot (show the product, prove a
   claim, set up the next beat); a shot with no job gets cut or replaced.

## 2. Build the pack

```
showtime review-pack <job>          # the job's latest final; or a video file; add --platform reels etc.
showtime review-pack <job> --lufs -16   # a loudness target other than the platform's (tutorials, podcasts)
```

The pack's fresh qa run judges like your last `showtime qa` of the same file: its `--platform` and `--lufs`
carry over unless you pass new ones, so CRITIC.md never reports a -16 LUFS mix as "2 LU off -14".

It prints the video it packed (`using ... (latest final)`) and writes `<job>/review/round-N/`: `sheet.jpg`
(a frame per second), `scenes.jpg` (every scene middle and each cut at -0.1 s, midpoint, +0.2 s), `cuts.jpg`
(every frame from 2 before to 4 after each cut, where double exposures and flashes hide), `frames/`
(frame 0, the hook at 0.5 s and 1.5 s, the poster, the last frame, scene frames; plus `text-<t>-<k>.png`,
the largest text lines of the key and scene frames cut out at full resolution for the type detail
pass), `loudness.png`,
`thumb-168x94.png`, a fresh `qa/` run, `context/` (brief, storyboard, SHOWTIME.md, showtime.json, check
report, mix report, the video's `.srt`/`.vtt`) and `CRITIC.md`, the brief to hand over (it carries the
eight questions of section 1). Other videos in the job (a 16:9 variant, exports) are listed in CRITIC.md
as "not in this pack": pack each deliverable you publish (`showtime review-pack <file>`; for a file
outside the job, such as a copied export, add `--project <dir>` so the pack gets its scenes and context).

Rounds count critic answers, not packs: a round is used once `FINDINGS.md` is saved in it. Until then
the next `review-pack` rebuilds the same round (for a newer final, or after an interrupted pack, which
carries an `INCOMPLETE` file). When a critic answers in chat, save its answer as `FINDINGS.md` in the
round folder before building the next round. Scenes are the planned ones (showtime.json `scenes` or
`chapters`, a film's `CUE.acts`, the page's scene clips, the voice timeline, the EDL report), named in the
frame labels; it says where they came from (`from <source>`) and falls back to detecting cuts in the pixels
only when there is no plan. Overlay clips (a kicker, a name card, a map inset shown during a scene) are not
scenes: `<section>`/`.scene` clips win when a page has them, otherwise a clip inside another clip's window
or an open-ended layer is left out; mark any other overlay with `data-overlay`. A film with DOM overlays
over its canvas is split by its `CUE.acts`.

## 3. Dispatch the critic

- Give the sub-agent only the path of `CRITIC.md` and ask it to write `FINDINGS.md` in the same folder.
  With the plugin installed, dispatch the `showtime:critic` agent (brief: `crew/critic.md`); otherwise
  a general sub-agent told to read that brief. `crew.md` pattern D says when a studio job spends
  round 1 on the first look.
- **No sub-agent tool in this session** (you may be a sub-agent yourself): answer `CRITIC.md` yourself,
  in its format, into `FINDINGS.md`, starting with `SELF-REVIEW (no critic available)`. Look at every
  sheet, including `cuts.jpg`. Tell the user the review was a self-review and ask for a second pair of
  eyes before calling the video shipped: self-reviews rate real should-fix problems as polish.
- Name a vision-capable model explicitly; the critic must look at the images.
- Do not tell it what to ignore or how severe things are. Coaching a reviewer toward "minor at most" is how
  real flaws ship.
- The critic is read-only: it does not edit, re-render, run the showtime workflow or dispatch other agents.

Severity, as CRITIC.md states it:
- **Blocker**: invented or wrong claims, misspelled names, black/frozen/garbage frames, wrong aspect or
  duration for the platform, clipped or missing voice, text cut off or outside the safe zone, missing credits.
- **Should-fix**: text too small or too brief to read, a line whose words and math (or numbers) sit on
  different baselines or differ in size or weight, music masking the voice, dead stretches over ~2 s,
  off-brand colours, captions more than ~150 ms out of sync.
- **Polish**: easing, 1-2 frame timing, colour nuance.

Every finding cites a timestamp and a frame path from the pack. Findings without a location are dropped.
The answer also lists what works, what the critic declined to judge, a verdict (ship / ship after fixes /
not ready) and the best poster frame.

## 4. Act on the findings

1. Treat each finding as a claim. Snap the cited time (`showtime snap <project> --at t`, or
   `showtime snap <video.mp4> --at t` for a footage edit or the shipped file) and confirm the problem is there
   before changing anything. Critics are wrong sometimes too. Read a suggested script rewording in its full
   sentence before re-voicing it.
2. Fix blockers first, then should-fix items; polish only when it is cheap.
3. If you disagree with a finding, keep it and say why in your summary to the user; never drop it silently.
4. Fix, re-render (the next `final-N.mp4`; the job points at it), re-run `showtime check` after timing
   fixes (a shorter scene can break a label elsewhere), run `showtime qa <job>` again, and build round 2
   (`showtime review-pack <job>` again; both follow the latest final). Round 2 judges only the fixes and
   anything they broke. Text-only notes (a README line, share text) need no re-render and no new pack.
5. **Two rounds at most.** If blockers remain after round 2, stop and show the user the open findings with
   frames; they decide. `review-pack` refuses a third critic round unless `--force-round` is given.
6. **Polish after a "ship" verdict** needs no new pack: fix, then prove each fix with a before/after pair
   (`showtime snap <new.mp4> --at t1,t2 --compare <old.mp4>`), run `showtime qa`, and log it in
   `work/feedback.md`. An unused render is dropped from the job with `showtime job discard <job> <file>` (its poster, credits and `.work/` move with it to `work/discarded/`; caption files stay, name one to discard it too).

## 5. Notes from the user

1. **Echo them back numbered**, each tied to a timestamp or scene: "1. (0:03, scene 2) title too small ...".
   If a note is ambiguous ("make it punchier"), ask about that note only, offering 2-3 concrete readings with
   a recommended default, before changing anything.
2. **Apply in this order**: blockers (a wrong claim, a broken frame) → cheap tweaks (text, colour, timing) →
   structural changes (reordering scenes, new music). One change per re-render, affected range only.
3. **Show proof**: before/after stills at the cited timestamps (`showtime snap <new> --at t --compare <old>`),
   and the new qa verdict.
   State what changed and where; skip the praise.
4. **Push back when a note collides with a locked decision or a check**, e.g. six more lines of text in a
   3-second shot fails the reading-time rule, or a note contradicts a style frame the user approved. Say so,
   give the consequence, offer an alternative; the user decides.
5. **Log every round** in `work/feedback.md` inside the job folder:

```
## Round 2 (2026-09-26 14:10)
1. "logo too late" (0:13.5) -> moved the logo reveal from 13.5 s to 12.8 s; re-rendered 12-15 s
2. "music too loud under the voice" -> ducking depth 10 -> 14 dB; qa: -14.0 LUFS, TP -1.2
Not changed: "add the pricing table" (conflicts with the 15 s length; offered a 30 s cut)
```

Then record the boundary: `showtime job note --stage feedback --verified "round 2 applied: qa PASS"`.

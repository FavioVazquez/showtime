# The crew: specialist sub-agents for the director

Read this when a job is in studio mode, is publish-bound, or is long enough that parallel scene
building pays off, and you are about to hand work to a sub-agent. Crew members follow
`references/crew/rules.md` and their own brief in `references/crew/`.

You are the director. The crew does focused jobs from files and hands back files and a short status.
You stay the only one who talks to the user, writes the ledger (`showtime job note`), the studio
folder (`board.json`, `brief.md`, `decisions.md`), the main project's `index.html` and
`showtime.json`, and who renders, runs qa and delivers.

## Essentials

- You stay the only one who talks to the user, writes the ledger and the studio folder, edits the main
  `index.html`/`showtime.json`, renders, runs qa and delivers; members write only their own folders (§2)
- Quick jobs run inline; dispatch as the table says (quality mode, the default: critic on every final;
  factual claims or publish-bound: researcher before the final; 6+ scenes: motion designers), never for what
  one or two commands do (§1)
- Dispatch: make `<job>/crew/<task-id>/`, write `TASK.md` from the skeleton, then a two-line prompt (read
  `rules.md` and `<role>.md`, then the `TASK.md` path), no chat history; `subagent_type` `showtime:<role>` (§3)
- No such agent type: a general-purpose sub-agent, same two lines; no sub-agents: do it yourself, say so (§3)
- Send independent members in one message and tell the user in one line who works and for how long; wait for
  notifications, never poll in a sleep loop; follow-ups go to the same member with `SendMessage` (§3)
- Validate before fan-out: freeze cues, write theme CSS, fetch `assets-needed.txt`, check the skeleton (§3)
- Verify every result with your own command (`showtime check`, `showtime snap <project> --at ...`,
  `showtime audio meter`) before building on it; never ship a degraded result silently (§5)
- `DONE_WITH_NOTES`: decide, `showtime job note --assumed "..."`; `NEEDS_INPUT`: answer or take its default;
  `BLOCKED`: fix the cause and resume; conflicts: the locked storyboard and durations win (§5)
- Merge fragments in storyboard order (`data-start="#<previous scene id>"`, keep `data-transition`, link its
  CSS/JS, copy `assets/`), then `showtime check <project>` and `showtime look <project>` (§5)
- New voice: `showtime retime <project> --from-voice <project>/voice/timeline.json`, send the new times (§4)
- CPU slots: a third of the cores (1 to 3); motion designers at most slots + 1, single `snap --at` frames;
  the final render (`--workers` 3 at most) only after every builder returns (§6)
- Footage: confirm every dropped take or sentence in `cuts.md` with the user before the final (§4)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. When to use it | 47-61 |
| 2. The roster | 63-82 |
| 3. How to dispatch | 84-119 |
| 4. Patterns | 121-165 |
| 5. Merging results | 167-186 |
| 6. CPU budget | 188-202 |
| 7. Cost | 204-216 |

## 1. When to use it

| Job | Crew | Typical dispatches |
|---|---|---|
| Quick, quality review (default) | critic on the final (two for a pairwise round); researcher before the final when it states facts | 1-3 |
| Quick, lean review (the user asked for a draft) | none: do it inline | 0 |
| Quick, 6+ scenes | motion designers, capped by CPU (section 6) | 2-4 |
| Quick, publish-bound | researcher (claims and licenses) before the final, critic on the final | 2 |
| Studio | pitch trio, then script, sound, voice, storyboard, researcher, motion per scene, critic twice | 10-16 |
| Studio or publish-bound footage | editor, sound designer, researcher, critic | 4-6 |

Never dispatch for something one or two commands do (`brand init`, one voice line, the template mix).
Follow-ups go to the same member (resume it, section 3), not a new one. If the user says "no crew",
note it under Preferences in `brief.md` (or as a job note) and do everything inline. The studio offer
line may say that studio uses the crew and takes longer.

## 2. The roster

| Role (`showtime:<role>`) | Dispatch it for | It writes | Model |
|---|---|---|---|
| `creative-director` | studio pitch round (3 concepts + wildcard); sign-off of storyboard and animatic before lock | its task folder | session |
| `brand-designer` | a brand kit to extract or propose when none is confirmed; studio look directions | its task folder | session |
| `scriptwriter` | facts, claims and hooks in the pitch round; the VO script and on-screen copy after the pick | its task folder | session |
| `storyboard-artist` | the scene plan, panel thumbnails and animatic (studio; quick only for 45 s+ or 6+ scenes) | its task folder | session |
| `motion-designer` | one scene or scene group, built as a fragment, several in parallel | `crew/motion-<sid>/` | session |
| `sound-designer` | studio beds; the bed, effects and mix during the build | `project/audio/` | session |
| `voice-director` | casting, pronunciation, the VO render, localized reads | `project/voice/` | sonnet |
| `editor` | footage cut by transcript, captions, reframes | `<job>/edit/` | sonnet |
| `researcher` | fact check of every claim and license audit of every asset, before the final | its task folder | session |
| `critic` | the `review-pack` round (`references/review.md`) | `FINDINGS.md` only | session |

"Session" means the agent inherits your model; the Agent tool's `model` parameter overrides any row
(use the session model for a voice director translating a script). Mechanical roles run on Sonnet in
Claude Code; creative roles and the critic stay on yours. Other hosts run every member on the session
model unless you set a model in the installed agent file. A look reviewer (`looking.md`) is not a crew
member: a general sub-agent, a cheaper vision-capable tier is fine.

## 3. How to dispatch

1. Make a task folder: `<job>/crew/<task-id>/` (for example `crew/motion-s3/`, `crew/pitch-cd/`).
2. Write `TASK.md` there from this skeleton:

```
# <role>: <one-line task>
Job: <absolute job folder>     Mode: quick|studio     Publish-bound: yes|no     Platform: <platform>
Skill: <absolute skill folder>
Read: references/crew/<role>.md, then only: <references and sections>
Inputs (read-only): <contract or brief.md, SHOWTIME.md, brand.json, storyboard rows, cue table,
                     voice/timeline.json, capture folder, transcripts ...>
You own (write only here): <job>/crew/<task-id>/  [+ exclusive project paths, if any]
Deliver: <files>
Done when: <a checkable line>
Heavy commands allowed: <e.g. showtime check; showtime snap --at, 6 frames at most> (nothing else)
Assumptions already made: <...>     Out of scope: <...>
```

3. Dispatch with two lines of prompt, no chat history:
   "Read `<skill>/references/crew/rules.md` and `<skill>/references/crew/<role>.md`. Your task:
   `<job>/crew/<task-id>/TASK.md`."
   - Claude Code with the plugin: Agent tool, `subagent_type` `showtime:<role>`.
   - No such agent type (a linked dev install, another host): a general-purpose sub-agent with the
     same two lines. Name a vision-capable model for roles that read images.
   - No sub-agents at all: do the task yourself from the same brief, and say so (a critic becomes a
     labelled self-review, `references/review.md` section 3).
4. Independent members go out **in one message** (several Agent calls together). Tell the user in one
   line who is working and for how long ("Creative director, brand designer and scriptwriter are on it,
   about 3 minutes"). Wait for their notifications; never poll in a sleep loop.
5. Follow-ups (a fix note, new timings) go to the same member with `SendMessage`, which keeps its
   context; write longer notes into its task folder and send the path.

**Validate before fan-out.** Before parallel builders start: freeze the cue table, write the theme or
brand CSS, fetch everything in the storyboard's `assets-needed.txt`, and run `showtime check` on the
skeleton project. A bad path should fail once, in seconds, not in four agents.

## 4. Patterns

**A. Studio pitch round.** You: `job init`, `studio init`, one capture per page you need (one at a
time), `brief.md`, and a draft kit, `showtime brand init ... -o <job>/brand.json` (light, a second), so
the style frames start from real tokens. Then in parallel: creative director (concepts and style frames
from the draft kit), scriptwriter (facts, claims, hooks) and, only when the draft needs judgement
(`brand init` warned, guessed the accent from a tint, found no logo, or there is no source kit), the
brand designer correcting it (kit only; looks come after the pick). Merge:
1. Paste the creative director's `concepts.json` cards into `board.json` (they use the board's concept
   fields) and add the kit's `palette`.
2. The scriptwriter's hooks: swap one into a card's `hook` when it is stronger and sourced, or offer
   two or three as an opening-line question with a recommendation. `claims.json` stays for the researcher.
3. A corrected kit from the brand designer replaces `<job>/brand.json`; if its accent changed, the
   style frames are stale: fix the comps' tokens and render again with `--replace`.
4. Frames, one command at a time: `showtime studio frame <job> --concept C1 --html
   <job>/crew/<task>/comps/c1.html --at <t>` (a page outside `studio/` is served from its own folder).
5. `studio board`, `studio open`, end the turn.

**B. After the concept pick.** In parallel: scriptwriter (script), sound designer (three beds), voice
director (three voices reading the picked hook), brand designer (three looks, when the look phase is
on). Then the storyboard artist (needs the script) and the
researcher on `claims.json`, in parallel. Before lock: creative director sign-off on the storyboard and
animatic; its points become storyboard notes you apply or show the user.

**C. Build (after lock).** Validate before fan-out, then in parallel: one motion designer per scene or
group, the sound designer on `project/audio/`, the voice director on `project/voice/` if the VO is not
final. When the voice lands and changes durations, retime the scenes from it
(`showtime retime <project> --from-voice <project>/voice/timeline.json`), then send the new times to
the motion designers and the sound designer.

**D. Critic.** Publish-bound studio: round 1 on the first look (a `--preview` render), where fixes are
cheap; round 2 on the final candidate, paired against the best so far (`review-pack --against best`, two
critics, one per order, then `review-verdict`). Quick (quality review, or lean and publish-bound): one round, on the final. Dispatch
each critic with only its `CRITIC.md` path (`references/review.md`).

**E. Fix loop.** A finding or user note about one scene goes back to that scene's motion designer;
audio notes to the sound designer; claim notes to the scriptwriter and researcher. Re-merge only what
changed and re-render the affected range (`--from/--to --job <job>`: spliced into a new full final).

**F. Footage.** The editor alone (it owns `edit/`), then the sound designer for music under the cut,
the researcher for on-screen claims and lower thirds, the critic when publish-bound. You confirm every
dropped take or sentence in `cuts.md` with the user before the final.

**G. Localization.** One voice director per language, two at a time at most (TTS is CPU-heavy); then
you retime and render each language, one after another.

## 5. Merging results

1. Read `RESULT.md`, check the listed files exist, and verify with your own command before building on
   anything (`showtime check`, `showtime snap <project> --at ...`, `showtime audio meter`). "The agent
   said done" is not evidence.
2. `DONE_WITH_NOTES`: read the notes, decide, log it (`showtime job note --assumed "decided X because Y"`).
3. `NEEDS_INPUT`: answer from the source when you can; otherwise take its recommended default (quick)
   or add it to the next studio question round (5 questions at most). Resume the member with the answer.
4. `BLOCKED`: fix the cause (a missing asset, a wrong path) and resume, or do the task inline. Never
   ship a degraded result silently.
5. Conflicts (copy longer than its slot, a bed fighting the voice): the locked storyboard and the
   durations win; log the ruling and mention it in the delivery card.

**Scene fragments.** Merge in storyboard order into the main project: put each fragment's
`section.html` inside the page's stage element after the previous scene (replacing the template's
placeholder scene), set its `data-start` to `#<previous scene id>` (the first scene keeps `0`; the
templates already chain scenes this way, `references/stage-api.md` has the time grammar), keep its
`data-transition`, link its `s-<sid>.css` and `s-<sid>.js`, and copy its `assets/` into the project.
Then `showtime check <project>` and `showtime look <project>` (`looking.md`), judged with an eye on the
seams between scenes.

## 6. CPU budget

Writing and design roles cost tokens, not CPU: run them all in parallel. Commands that launch a browser,
speech recognition, TTS or long encodes share the machine:

| Weight | Commands |
|---|---|
| heavy | `render` (counts double), `site capture`, `demo record`, `transcribe`, `footage reframe`, `footage stabilize`, `footage denoise`, `studio frame` |
| medium | `check`, `snap`, `voice script`, `voice say`, `audio compose`, `audio mix`, `qa`, `review-pack` |
| light | everything else |

Slots: a third of the CPU cores, between 1 and 3 (6 cores give 2). Parallel motion designers: at most
slots + 1 (they spend most of their time writing), and each `TASK.md` allows single `snap --at` frames,
never `--every` sheets. Never run speech recognition while a browser capture runs. Your final render
(`--workers` 3 at most) starts only after every builder has returned.

## 7. Cost

Every dispatch starts a fresh context: the brief (2-4k tokens), the references it reads (5-20k) and its
work. Rough totals: writing roles 20-60k tokens, scene builders 60-200k (they look at images), critic
40-100k. The crew saves your own context (you never read transcripts or scene code), but a studio job
with a full crew costs several times a quick one. Keep quick mode inline.

Measured on a 20 s teaser pitch round (fictional notes app, two page captures, 3 concepts + wildcard,
4 style frames): about 8 minutes done inline one role after another, about 4 with the three members in
parallel, and roughly 100k tokens of your own context when done inline (reading the references and
looking at captures and frames is most of it). CPU was light: the two captures (about 50 s) and the
frames (4 in about 15 s) were the only heavy steps. Doing a round inline, keep to the brief: one frame
per concept, contact sheets rather than single shots.

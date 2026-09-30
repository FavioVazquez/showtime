# Workflow: tutorial, walkthrough or product demo

Read this when the user wants to show how to use something: a feature tour, a how-to, a tutorial
episode, a product demo ("record a walkthrough of the new onboarding", "a 90 s tutorial on setting up
X"). Two builds: **record the real app** with a scripted demo plus auto zoom (default whenever the app
can run here), or **draw it** with the canvas `tutorial` template when there is no runnable app or the
UI is conceptual.

## Essentials

- Defaults: 60-120 s, 16:9 1920x1080 30 fps, `--look framed` auto zoom, one action per sentence, captions as a
  sidecar, -16 LUFS for voice-heavy tutorials when the platform allows (`qa --lufs -16`) (§ Defaults)
- Seed fictional data, never real credentials, names or tokens; hide notifications and dev overlays (§ Inputs)
- Voice first (`showtime voice script <job>/narration.md -o <job>/voice`), then `showtime demo record`; gate on
  `demo.waitFor`, never fixed sleeps; keep the default `--dpr 2` (§ Steps (recorded app), § Pitfalls)
- `showtime autozoom <job>/rec --preview` and look before the full run; then the EDL, `showtime edit check`,
  `showtime edit render <job> --preview`, and the final with `-o <job>/final.mp4` (§ Steps (recorded app))
- Verify with `showtime qa <job>` and `showtime look <job>`: each step on screen as it is said; chapters in
  `share.txt` from 0:00, at least three, each ≥10 s (§ Steps (recorded app))
- No runnable app: `showtime new tutorial <job>/project` (§ Steps (drawn tutorial, no runnable app))

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| Inputs | 32-37 |
| Defaults | 39-46 |
| Steps (recorded app) | 48-80 |
| Steps (drawn tutorial, no runnable app) | 82-87 |
| Pitfalls | 89-95 |
| Read next | 97-100 |

## Inputs

- The app: a repo that runs locally, a static build (`dist/`), a staging URL, or the user's own screen
  recording (with an optional cursor log).
- The task being taught, step by step, and the audience's starting point.
- Helpful: test accounts or seed data the project already ships (never real credentials).

## Defaults

60-120 s per episode (a 3-5 s outcome preview, 3-5 steps of 10-25 s, a 5 s recap); 16:9 at
1920x1080, 30 fps; `--look framed` auto zoom; narration `bf_emma` or `am_michael` at speed 1.0 with
one action per sentence; `minimal-pulse` or `underscore` bed at a low level (or none); captions as a sidecar;
loudness -16 LUFS for voice-heavy tutorials if the platform allows (`qa --lufs -16`).
Ask at most: which task to show, when the request does not say. Voice-over: follow the request; when
it is silent, state your choice as an assumption.

## Steps (recorded app)

1. **Job.** `showtime job init <app>-tutorial --goal "..."`.
2. **Run the app** the way its README says, in the background, and wait for the port; or serve a static
   build with `--serve ./dist` in step 4. Seed demo data, use fictional names, hide notifications and dev
   overlays (`tutorial-recording.md` section 3). *Done when:* the start screen shows clean, realistic data.
3. **Script the narration and the actions together.** One sentence per action. Build the voice first:
   `showtime voice script <job>/narration.md -o <job>/voice`; `voice/timeline.json` gives each step's
   length, which becomes the `demo.wait()` holds in the demo script.
4. **Demo script.** `showtime demo init <job>/walkthrough.mjs`, then write the steps with `goto`,
   `click`, `type` (12-16 cps), `press`, `waitFor` (real-time, not recorded), `wait` (recorded holds),
   `chapter`. Record: `showtime demo record <job>/walkthrough.mjs <job>/rec --url http://localhost:<port>`.
   *Done when:* `<job>/rec/demo.mp4` exists and `events.json` lists every click and keystroke.
5. **Auto zoom.** `showtime autozoom <job>/rec --preview` first (half size), look at a few frames
   (`showtime footage scenes <job>/rec/autozoom.mp4 --every 2`), then the full `showtime autozoom <job>/rec`.
   Vertical: `--look plain --size 1080x1920 --fit cover`. *Done when:* zooms land on each action and
   never cut a label in half at a key moment.
6. **Assemble.** Put the zoomed video, title cards and the voice together with an EDL:
   `{"sources": {"rec": "../rec/autozoom.mp4"}, "ranges": [{"source": "rec", "start": 0, "end": <len>}],
   "audio": {"tracks": [{"kind": "voice", "file": "../voice/vo.wav", "start": 0.5}]}}`, saved as
   `<job>/edit/edl.json` (paths are relative to the EDL file). Add title cards and a logo as `overlays[]`,
   a quiet bed as `audio.music`. `showtime edit check <job>/edit/edl.json`, then
   `showtime edit render <job> --preview` and look at `showtime edit view <job>` (the newest render).
   (Alternative for heavy graphics: an HTML project with the frames in a `browser-frame` and the
   runtime cursor and keystrokes driven by `events.json`; `tutorial-recording.md` section 5.)
7. **Captions.** `showtime captions <job>/voice/vo.words.json --style clean --size 1920x1080
   -o <job>/edit/caps.ass --srt <job>/final.srt`, or `"captions"` in the EDL to burn them.
8. **Final.** `showtime edit render <job> -o <job>/final.mp4`.
9. **Verify.** `showtime qa <job>` (the latest final and the job's captions), `showtime look <job>`; check that
   every step named in the narration is on screen when it is said.
10. **Deliver.** Chapters in `share.txt` (first at 0:00, at least three, each at least 10 s), exports,
    the delivery card. Series: keep the demo script, voice settings and look per episode in SHOWTIME.md
    notes so episode 2 matches episode 1.

## Steps (drawn tutorial, no runnable app)

1. `showtime new tutorial <job>/project --duration <len>`; replace the fake app in `app.js` with the real screens'
   layout and labels (from screenshots the user provides or `showtime site capture`).
2. Move the click, type and step times in `cues.js` to the narration (`voice/timeline.json`).
3. Check, snap, render, qa as in the pipeline. Canvas labels under an intentional camera zoom are fine.

## Pitfalls

- Showing loading spinners: gate on app state with `demo.waitFor`, never on fixed sleeps.
- Typing long text on screen: paste it or cut the typing short.
- Recording at DPR 1 and zooming 2x: text goes soft. Keep the default `--dpr 2`.
- Real names, emails or tokens in the recording: seed fictional data before recording.
- Narration ahead of the picture: an action should happen as its sentence says it, never before.

## Read next

`references/tutorial-recording.md`, `references/capture.md`, `references/voice.md`,
`references/editing.md`, `references/film-api.md`, `references/captions.md`, `references/qa.md`.

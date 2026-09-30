# Tutorial and product-demo recordings

Read this when the video walks through a real app: a feature tour, a tutorial episode, a launch
demo. It covers writing a demo script, pacing clicks and typing, `showtime demo record`, the
events file, auto zoom with a synthetic cursor and keycaps, and how to structure 60-120 s episodes.
For inspecting the repo and serving the app read `references/capture.md`; for an animated
walkthrough drawn entirely in code see `templates/tutorial`, and for a **series** of episodes that share
one look, sound motif and product UI (drawn in code, targeted by named rects) read
`references/series.md` (`showtime new series`).

## Essentials

- Pipeline: `showtime demo init walkthrough.mjs`,
  `showtime demo record walkthrough.mjs --url http://localhost:3000` (or `--serve ./dist`), then
  `showtime autozoom <demo-folder>` (§1)
- In a job pass `<job>/work/demo` as the outdir; never record through `showtime server` or `preview` (exit 1,
  "wrong page") (§1)
- Helpers advance a virtual clock; gate on app state with `waitFor` (not recorded, so loading never shows),
  never on fixed sleeps (§2)
- Pointer actions glide 0.35-0.9 s first: to hit a narration word at `w`, start the action about 0.4 s before
  the word (or pass a short `move`) (§2)
- Record with `--platform mac` when the narration names Mac shortcuts; keep time-of-day text out of shots (§2)
- Capture at `--dpr 2` with a 1280x800 to 1440x900 viewport; one action per sentence; hold 1.5-2.5 s
  on anything to read; type at 12-16 characters/s and never type a paragraph (§3)
- Park the pointer near what you talk about, never on a label the voice names; never show a real wait
  over 1 s; dead air over 0.7 s gets cut or covered by a camera move (§3)
- Clean stage: seeded demo data, no personal data, tokens or real customer names, no notification badges or
  dev overlays; use fictional names and say so (§3, §6)
- Episodes of 60-120 s: a 3-5 s hook showing the end result, 3-5 steps of 10-25 s, a 5 s recap/CTA; over 2
  minutes add chapters (`demo.chapter`) (§3)
- Autozoom: `--max-zoom` defaults to 2.0; vertical: `--look plain --size 1080x1920 --fit cover`; `--preview`
  for a fast half-size pass. Outputs never overwrite (`autozoom-2.mp4`): copy the file it names (§4)
- Change the camera without a new take: `--hints hints.json` (`focus`, `wide`, `drop`, `key`) and
  `--cursor-offset` (§4)
- Your own recording: `showtime autozoom screen.mp4 --cursor-log cursor.csv --cursor-scale 2`; without a log,
  zooms follow screen changes and no cursor is drawn (§4)
- In an HTML project: `showtime footage trim rec/demo.mp4 --width 1920 -o <job>/project/media/demo.mp4`, a
  `<video data-st>` layer with `data-offset`; voice lines at chapter time plus 0.3-0.6 s;
  `retime --from-voice` does not apply (§5)
- Before rendering: the script runs twice with the same frame count, every click lands on something visible,
  zoom never cuts off the subject (else `--max-zoom 1.6`), and the final passes `showtime qa` (§6)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. The pipeline | 53-68 |
| 2. Writing a demo script | 70-127 |
| 3. Pacing rules | 129-144 |
| 4. Auto zoom | 146-195 |
| 5. events.json (for compositions): Composing a recording into an HTML project | 197-236 |
| 6. Checklist before rendering the episode | 238-245 |

## 1. The pipeline

```
showtime demo init walkthrough.mjs                       # starter script with every helper
showtime demo record walkthrough.mjs --url http://localhost:3000     # or --serve ./dist
showtime autozoom showtime-out/walkthrough-demo-<time>/   # zoom + cursor + ripples + keycaps
```

The default output folder is `showtime-out/<script>-demo-<time>/` (printed at the end); in a job,
pass `<job>/work/demo` as the outdir. `--serve` uses a plain static server; never record through
`showtime server` or `preview` (the command exits 1 with "wrong page").

`demo record` writes `frames/` (clean frames, no cursor), `events.json` and `demo.mp4`.
`autozoom` (also `showtime footage autozoom`) writes `autozoom.mp4` plus `autozoom.camera.json`.
Use the MP4 directly, or place the frames/video in an HTML composition and drive the camera, the
runtime cursor and keystroke components from `events.json` (section 5).

## 2. Writing a demo script

A script is an ES module; every helper advances a virtual clock and records frames, so a script
produces the same video on a fast or a slow machine.

```js
export const options = { size: '1440x900', fps: 30 };      // CSS viewport; frames at --dpr (default 2)

export default async function (demo) {
  await demo.goto('/');                              // relative to --url / --serve
  await demo.wait(1.2);                              // establish the screen
  await demo.chapter('Create a project');
  await demo.click('text=New project');              // glide (0.35-0.9 s by distance), press, release
  await demo.type('#name', 'Launch video', { cps: 14 });
  await demo.press('Meta+Enter');                    // shown as keycaps by autozoom
  await demo.waitFor('.toast');                      // real-time wait, NOT recorded
  await demo.wait(1.5);                              // read the result
  await demo.scroll('#pricing', { duration: 1.2 });
  await demo.hover('.plan.pro');
  await demo.focus('.plan.pro', { zoom: 1.6, duration: 2 });   // explicit camera hint
  await demo.wait(1.0);
}
```

| Helper | Does |
|---|---|
| `goto(path)` | navigate (not recorded); dismisses cookie banners; stops on bot walls |
| `wait(s)` | record `s` seconds of the current screen |
| `waitFor(selector \| fn \| seconds)` | wait in real time without recording: loading never shows |
| `moveTo(target, {duration})` | move the cursor on an eased, slightly curved path |
| `click(target, {hold, move})`, `dblclick` | move, press (2 frames), release, hold 0.35 s |
| `type(target, text, {cps, clear, jitter})` | click the field, then type at `cps` characters/s with a deterministic human rhythm |
| `type(text, {cps})` or `type(null, text, {cps})` | type into the field that already has focus (no click, the caret stays put); the focused element's box is logged so autozoom still frames it |
| `press('Meta+K')` | key or combo (Playwright names: Meta, Control, Shift, Alt, Enter, ArrowDown...) |
| `hover`, `select(target, value)`, `drag(from, to)` | as named |
| `scroll(target \| 'top' \| 'bottom' \| {y} \| dy, {duration})` | smooth, eased scroll |
| `focus(target, {zoom, duration})` | tell autozoom to frame this element |
| `chapter(title)`, `note(text)` | markers for titles, chapters, narration |
| `page` | the Playwright page (escape hatch) |

Targets are Playwright selectors (`#id`, `.class`, `text=Save`, `role=button[name="Save"]`) or
points `{x, y}` in CSS pixels. Off-screen targets are scrolled into view first.

Every pointer action first glides the cursor to its target: 0.35-0.9 s depending on the distance
(`click(t, {move: 0.2})` sets it), and `drag(from, to)` glides to `from` before pressing. The press or
the drag start lands that much after the moment you call it, so to hit a narration word at time `w`,
start the action about `w - 0.4` s (or pass a short `move`).

The page sees the recording machine's OS unless told otherwise: an app that shows "Ctrl K" on Linux
and "⌘K" on a Mac changes its labels and modifier keys with it. Record with `--platform mac` (or
`export const options = { platform: 'mac' }` in the script) when the narration names Mac shortcuts,
so a take on Windows or Linux matches. The app's own clock (`Date.now()`, "Just now" labels) runs in
real time, and a take can last several times its video length: keep time-of-day text out of shots,
or freeze it in the app's test mode.

Timing: CSS transitions and Web Animations are stepped frame by frame (`--animations step`), so
hover effects and toasts animate at true speed in the recording. JavaScript timers still run in real
time: gate on app state with `waitFor`, never on fixed sleeps.

## 3. Pacing rules

- Capture at 2x (default `--dpr 2`) so zooms up to 2x stay sharp. Use a 1280x800 to 1440x900 CSS
  viewport; bump the app's own zoom (125-150%) if text would be small at 1080p.
- One action per sentence of narration. Hold 1.5-2.5 s on anything the viewer must read.
- Typing: 12-16 characters/s for short fields; paste or cut long text (never type a paragraph).
  After the first line of a field, omit the target so each line does not click (and move the caret).
- Park the pointer near what you type into or talk about, never on a label the voice names: the
  camera follows the pointer, and a parked pointer covers the thing on screen.
- Loading: skip it with `waitFor` (the result appears instantly); never show a real wait over 1 s.
- Dead air over 0.7 s gets cut or covered by a camera move.
- Clean the stage first: seeded demo data, no personal data, no notification badges, no dev
  overlays. Use fictional names and say so.
- Episodes of 60-120 s: a 3-5 s hook showing the end result, 3-5 steps of 10-25 s each, a 5 s
  recap/CTA. Over 2 minutes, add chapters (`demo.chapter`) with title cards of about 1.5 s or
  description timestamps (first at 0:00, at least three, each at least 10 s long).

## 4. Auto zoom

```
showtime autozoom <demo-folder>                                   # framed look, 1920x1080
showtime autozoom <demo-folder> --look plain --size 1080x1920 --fit cover   # vertical follow-cam
showtime autozoom <demo-folder> --keys all --max-zoom 2.2 --bg "#0b1020,#312e81"
showtime autozoom screen.mp4 --cursor-log cursor.csv --cursor-scale 2        # your own recording
showtime autozoom screen.mp4                                       # no telemetry: follows screen changes
showtime autozoom <demo-folder> --preview                          # half size, fast
```

Zoom rules built in:

- Clicks zoom to 1.8x, typing 1.6x, drags 1.4x, scrolls stay wide; an element's box limits the
  zoom so it fills about 70% of the view. Hard cap 2.8x (`--max-zoom`, default 2.0).
- The camera starts moving before the action: 0.15 s (click), 0.25 s (scroll/drag), 0.4 s (typing).
- Actions closer than 1.5 s and within 20% of the screen share one shot; shots less than 1.8 s
  apart are bridged (the camera pans instead of zooming out and back in), but never across a
  `demo.chapter()` marker, and `demo.wide()` ends any shot at that moment (a wide beat); each shot
  holds at least about 1.6 s after its last click (1.2 s after typing), then zooms out.
- A target in a window corner may use the framed look's padding, so it is not pinned to the
  picture's edge.
- The camera follows the cursor with a dead zone (central 75% of the view, 60% while typing).
- Motion is a damped spring (zoom in log space, response 0.55 s; pan 0.42 s).
- The synthetic cursor is 1.6x a normal pointer, dips on click with a ring ripple (0.35 s), and fades
  after 2 s idle. Keycaps sit bottom-centre at 88% height, fade in 0.15 s, stay 1.5 s after the last
  key, fade out 0.3 s. `--keys all` also shows typed text.
- `--look framed` (default) puts the window on a gradient with padding, rounded corners and a soft
  shadow; zooming in fills the frame.
- `--keys-pos bottom|top|bottom-left|bottom-right|top-left|top-right` moves the keycaps;
  `--key-glyphs` draws ⌘ ⌥ ⇧ ⌃ ↵ instead of words. Every run also writes `<name>.keys.json` (keycaps
  and typed text with times and glyph labels) so a composition can draw its own (`--keys off`).
- Output names never overwrite: a second run writes `autozoom-2.mp4` and `autozoom-2.camera.json`,
  and says so first. Copy the file it names.
- The text summary lists every shot (`start-end x zoom at x%,y%`); `--plan --json` has `shot_list`.

Changing the camera without a new take:
- `--hints hints.json`: a list of events merged at plan time: `{"type":"focus","t":12,"end":14,
  "x":640,"y":300,"zoom":1.4}` adds a shot (CSS px), `{"type":"wide","t":20}` goes wide,
  `{"type":"drop","t":8,"end":9.5}` removes the actions in that span. To name a key the way the voice
  does, drop it and re-add it with a label: `{"type":"key","t":45.47,"keys":".","label":". full stop"}`
  (a lone punctuation key is labelled with its name by default, e.g. `. Period`).
- `--cursor-offset 22.6-24:36,12` moves the recorded pointer 36,12 CSS px inside 22.6-24 s, eased in
  and out (a parked pointer that covers a label); repeatable.

Your own screen recordings: record with the system cursor hidden if you can, and log the pointer
alongside as JSON `[[t, x, y, down], ...]` or CSV `t,x,y,down` in video pixels (`--cursor-scale 2`
for macOS point coordinates on a Retina capture). Clicks come from `down` changes and dwells
(the pointer resting 0.45-2.6 s) become softer zoom targets. Without a log, zooms follow regions of
the screen that change, and no cursor is drawn.

## 5. events.json (for compositions)

```json
{ "fps": 30, "frames": 412, "duration": 13.73, "viewport": {"width": 1440, "height": 900}, "dpr": 2,
  "frame_size": {"width": 2880, "height": 1800}, "frame_pattern": "frames/%05d.jpg", "video": "demo.mp4",
  "cursor": [[0.0, 892.8, 648.0, 0], ...],
  "events": [{"t": 1.87, "type": "click", "x": 308, "y": 279, "bbox": [48, 252, 520, 53], "target": "#repo"},
             {"t": 2.04, "end": 2.54, "type": "type", "text": "acme/web", "bbox": [...]},
             {"t": 3.66, "type": "key", "keys": "Meta+K"},
             {"t": 0.5, "end": 1.29, "type": "scroll", "from": 0, "to": 2492},
             {"t": 0.5, "type": "chapter", "title": "Create a preview"}],
  "chapters": [...],
  "overlays": {"cursor_path": [{"at": 1.87, "x": 32.1, "y": 51.7, "click": true}],
               "keystrokes": [{"at": 2.04, "text": "acme/web"}, {"at": 3.66, "keys": "Meta K"}]} }
```

Coordinates are CSS pixels of the viewport (multiply by `dpr` for frame pixels); `cursor` has one
row per frame. `overlays.cursor_path` and `overlays.keystrokes` are already in the format of the
runtime `cursor` and `keystrokes` components (x/y in % of the frame), so a composition can show the
clean frames as a video layer and draw its own cursor and keycaps in the page style. The camera
from `autozoom --plan` (`*.camera.json`: per frame `[t, zoom, cx, cy]`, centre as a fraction of
the source frame) can drive a CSS transform on that layer:
`transform: scale(zoom) translate((0.5 - cx) * 100%, (0.5 - cy) * 100%)` with
`transform-origin: 50% 50%`.

### Composing a recording into an HTML project

When the tutorial needs step cards, a result-first hook or captions over the recording, use the
recording as a `<video data-st>` layer instead of an EDL:
1. `showtime footage trim rec/demo.mp4 --width 1920 -o <job>/project/media/demo.mp4` (a
   seek-friendly proxy), or use `autozoom.mp4` when its camera is what you want.
2. Place it: `<video data-st src="media/demo.mp4" data-offset="S">` inside a scene; `data-offset` is
   the recording time shown at the scene start. Chapter times from `events.json` minus the offset
   give each step card's `data-start`.
3. Voice lines go in `audio/mix.json` at chapter time plus a short lead (0.3-0.6 s); the recording sets
   the timing here, so `retime --from-voice` does not apply. Build the caption words at video time
   (voice word times plus each line's `start`) for `caption-karaoke`.
4. In a vertical short, frame the desktop recording as a card and push in per beat with a small
   `ST.onSeek` camera (scale/translate from waypoints in recording pixels), or with `browser-frame`
   `zoom` steps (x/y in % of the view).

## 6. Checklist before rendering the episode

- The script runs start to finish twice with the same frame count.
- No personal data, tokens or real customer names in any frame (check the contact sheet or
  `showtime footage view`).
- Every step has narration or a caption; every click lands on something visible.
- Zoom never cuts off the thing being explained; re-run with `--max-zoom 1.6` if it does.
- Final render passes `showtime qa`.

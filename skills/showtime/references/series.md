# Tutorial series: one kit, many episodes

Read this when the user wants **several** how-to videos for one product (a course, onboarding lessons,
"episode 1, 2, 3"), or asks to make a new episode in the style of an existing one. For a single walkthrough,
`showtime new tutorial` (canvas) or `tutorial-recording.md` (a recorded real app) is enough.

A series should feel like one show: the same intro, the same step band, the same caption style, the same
cursor, the same sounds for a click or a key, a signature motif at the start and its answer at the end,
and the product drawn the same way everywhere. Copying those between episode projects drifts after the
second episode. The series pattern keeps them in **one kit file** that every episode uses.

```
showtime new series planner-howto          # the series root and episode-01 (a working example)
showtime series add planner-howto --title "Move cards between columns"
showtime preview planner-howto/episode-02  # edit episode-02/episode.js, watch it live
showtime series sync planner-howto         # after editing planner-howto/kit.js
showtime series check planner-howto        # exit 1 when an episode has a stale kit copy
showtime render planner-howto/episode-01   # MP4, like any project
showtime series export planner-howto -o planner-site/   # every episode as one HTML file + index.html
```

## Layout

| Path | What it is |
|---|---|
| `series.json` | `{name, kit: "kit.js", episodes: ["episode-01", ...]}` |
| `kit.js` | **The kit: edit it here.** Look, chrome, sound, the product UI and its named rects, `KIT.episode(spec)`. |
| `showtime.json`, `index.html`, `cues.js`, `opener.js` | The series opener, a project of its own (series name, tagline, episode list, the motif). It is also where you try out kit changes. |
| `episode-NN/` | One project per episode: `showtime.json` (title, subtitle, kicker, duration), `index.html`, `episode.js` (the timeline table), `kit.js` (a synced copy: never edit it). |

Each episode is an ordinary project, so `preview`, `check`, `snap`, `render`, `retime` and `export` work on it
unchanged. The kit copy lives inside the episode because a project's files are served from its own
folder. `showtime export` warns when an episode's copy differs from the series kit, and `series check`
fails. Run `series sync` after every kit edit.

## The kit (`kit.js`, global `KIT`)

| Part | API | Notes |
|---|---|---|
| Look | `KIT.brand` (series, product, url, key, closing line), `KIT.palette`, `KIT.look`, `KIT.fonts` | One palette and one font family keep exports small. |
| Product | `KIT.state()` → the product's initial state; `KIT.drawApp(T, st)` draws the app window in world coordinates | Procedural: no screenshots, crisp at any zoom, and every state is a value. |
| Named rects | `KIT.rects(st)` → `Film.rects(...)`: `board`, `col:i`, `head:i`, `card:<id>`, `add:i`, `input`, `save`, `cancel`, `share`, `search`, `nav:i` | Built from the state, so a card's rect follows it when the list grows. Cursors, cameras, spotlights and callouts use these names. |
| Chrome | `KIT.intro`, `KIT.band` (the step band: number, title, `STEP n OF N`, progress), `KIT.captions` (under the window), `KIT.keycaps`, `KIT.recap`, `KIT.outro`, `KIT.opener` | The window sits between the band and the captions, so neither covers the UI. |
| Sound | `KIT.sound.signature(m, t, {resolve})`, `click`, `key`, `enter`, `success`, `snap`, `whoosh`, `step`, `bed(m, t0, t1, {bpm, numerals, db})` | The signature is four bell notes over a swelling chord in `KIT.brand.key`; the outro plays its falling answer. The bed is one chord a bar, so seeking lands mid-chord cleanly. |
| Episode | `KIT.episode(spec)` | Builds the scenes and the score from one timeline table and calls `Film.start`. |

To teach a different product, change `KIT.state`, `KIT.drawApp` and `KIT.rects` (and the brand block). The
episodes keep their structure; only their timeline tables mention product specifics.

## An episode: one timeline table

Every time in `episode.js` is used by both the picture and the sound. A click in `cursor` draws the
pointer's press and ripple and plays the click. A key in `keys` shows the keycap and plays the key. Each
step in `steps` moves the band and plays the step tick.

```js
var CUE = { intro: 3.6, s1: 4.0, s2: 8.6, addClick: 10.6, s3: 12.0, type1: 12.6, enter: 15.2, recap: 29, outro: 33.8, duration: 38 };

KIT.episode({
  number: 1, title: 'Add your first card', subtitle: 'Capture a task in a few seconds', duration: CUE.duration,
  intro: [0, CUE.intro],
  steps: [[CUE.s1, 'Find the board'], [CUE.s2, 'Add a card'], [CUE.s3, 'Name it and press Enter']],
  stepsEnd: CUE.recap,
  recap: { t0: CUE.recap, items: [[['N'], 'New card'], [['↵'], 'Save it']] },
  outro: { t0: CUE.outro, next: '02 · Move cards between columns' },
  state: [                                          // what the product does, as Film.fold events
    [CUE.addClick, { composing: 0, pressed: 'add:0', pressT: CUE.addClick }],
    [CUE.enter, function (s) { s.cards.c6 = { title: 'Draft launch email', label: 'copy' }; s.cols[0].push('c6'); s.born.c6 = CUE.enter; s.composing = -1; }],
  ],
  typing: [[CUE.type1, 'Draft launch email', 13]],   // typed into the composer, one key sound per character
  keys: [[CUE.enter, ['↵'], 'Enter']],
  cursor: [[0, 'board', { at: [0.8, 0.85] }], [CUE.addClick, 'add:0', { click: true }]],
  camera: [[CUE.intro, [960, 540], 1], [CUE.s2 + 1, 'col:0', 1.5, { whoosh: true }], [CUE.recap - 1, [960, 540], 1]],
  spots: [[CUE.s1 + 0.6, CUE.s2 - 1, 'col:0']],
  callouts: [[CUE.s1 + 1.2, CUE.s2 - 0.6, 'head:0', 'New cards start here', 'right']],
  captions: [[CUE.s2 + 0.2, CUE.s3 - 0.2, 'Click + Add card at the bottom of the column.']],
  success: [CUE.enter + 0.1],
});
```

| Field | Meaning |
|---|---|
| `intro: [t0, t1]` | the episode card (series, "Episode 01", title, subtitle) on the signature motif |
| `steps`, `stepsEnd` | `[[t, title], ...]`: the band and the chapters (keys 1-9 in the HTML player) |
| `state` | `[[t, patch \| fn(s, dt)], ...]` folded over `KIT.state()` (`Film.fold`): the UI at T is a pure function of T |
| `typing` | `[[t, text, cps], ...]`: the composer's draft grows one character at a time, with a key sound each |
| `cursor` | `[[t, 'rect' \| x, y, {click, at, dx, dy}], ...]`: a named target resolves with the UI as it is at that key's time |
| `camera` | `[[t, 'rect' \| [x, y], zoom?, {whoosh, ease}], ...]`: clamped so it never shows past the window |
| `keys` | `[[t, ['⌘', 'K'], 'label', 'enter'?], ...]`: keycap overlay + key sound (Enter gets the heavier one) |
| `spots`, `callouts` | `[[t0, t1, 'rect', pad]]`, `[[t0, t1, 'rect', 'text', 'left'\|'right'\|'above'\|'below', 'sub']]` |
| `pulses` | `[[t0, t1, 'rect'], ...]`: attention rings around a target (a hover, "look here") |
| cursor `{tag}` | `[t, 'card:c4', {click: true, tag: 'Right-click'}]` labels the pointer around that key |
| `captions` | `[[t0, t1, 'text'], ...]` under the window; one idea per caption, under two lines |
| `recap`, `outro` | the recap list (keys + what they do) and the next-episode card with the series closing line |
| `success`, `snaps`, `music`, `draw(T, st, ui)` | success chimes; a snap sound (something clicks into place); the bed's `{bpm, numerals, db}`; extra drawing in world space |

The chapters are `Intro`, each step, then `Recap`. The HTML export shows them as scrubber ticks and a
chapter menu, keys 1-9 jump to them, and `#chapter=3` links open there.

## Craft for a series

- **Same beats in every episode.** Use the same intro length (3-4 s), one step per action, a recap of the keys
  the viewer should remember, and a next-episode line. Viewers learn the format once.
- **One action per step.** Give the step 4-10 s: a caption that says what to do, the cursor or keys doing it,
  and 0.5 s of stillness after each click before the next move.
- **Name UI targets, never copy coordinates.** When the product's layout changes in the kit, every episode
  follows it.
- **Only show what the product does.** Keep states and labels true to the real product. Mark anything
  illustrative in the notes you hand over, and ask when a behaviour is unknown (where a new card lands,
  what a counter shows).
- **Sound identity.** Keep the signature motif and the click/key sounds in the kit. Episodes add only
  their own moments (`success`, a whoosh on a big camera move). Keep the bed under the UI sounds
  (`db: -13` or lower).
- **Length.** 30-120 s per episode. Longer lessons become two episodes.

## Checks

`showtime series check` (kit copies), then for each episode `showtime check`, `showtime snap <episode> --sheet`,
and a look at the contact sheet: band never over a callout, captions never over the pointer's target, the
camera inside the window. `showtime series export` gives every episode as a small HTML file (a live score
and no media: 150-250 KB each), plus an index page for sharing the series.

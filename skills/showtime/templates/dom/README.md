# Product launch (16:9, 9:16, 1:1): the claim, the product doing its verb, features, formats, end card

Files:
- `showtime.json`: size, fps, duration, background, poster time, and `"audio": "audio/mix.json"`. The poster is
  the hook frame (claim + product teaser); `"startTitle": false` tells `showtime export html` that this
  frame already carries the title, so the start screen only adds the Play row. `title`, `subtitle` and
  `kicker` (SLOT) head the exported page and its phone layout.
- `audio/mix.json`: the soundtrack, generated on this machine at render time (no downloads): an
  `upbeat-tech` bed composed to the scene cuts plus a whoosh (camera move), keystroke (typing), click
  (Generate), swoosh, knock and logo sting on the matching frames, mastered to -14 LUFS. When you move one
  scene or beat by hand, move its effect's `at` with it; swap the bed for a library track or add a voice
  (`references/audio.md`).
- `index.html`: the video. Four scenes (`<section class="scene" data-start data-dur>`):
  1. **hero**: the hook (a claim of about 4 words, one supporting line) with the product window teased at the side;
     the camera then pulls the window to the centre (a CSS keyframe move), pushes in on the prompt while
     it types (`browser-frame` `data-zoom`), the cursor clicks Generate and the cut builds (timeline clips,
     preview wipe, toast). A steps rail on the side says where we are in the flow.
  2. **features**: three benefit cards with live motifs, spotlit in turn.
  3. **formats**: the payoff in one image (16:9, 9:16 and 1:1 frames fan in).
  4. **close**: mark + name, tagline, call to action and URL over a lit horizon, entered through one
     WebGL shader transition (`sdf-iris`, a lit ring that echoes the horizon).
  Scene handoffs: `push left` twice (one direction for the whole video), one shader at the key moment.
- Every ground is lit (key light, rim light, faint grid, slow light sweep, vignette, grain): no flat
  backgrounds. Every colour comes from the theme (`/_st/themes/bold.css`) through a small token block at
  the top of the page, so another theme or a brand palette re-colours the whole video. Try `neutral`,
  `editorial`, `neon`, `paper` or `terminal`.

Slots to replace (search the page for `SLOT:`):
- Product mark and name (the inline SVG, or `<img class="mark" src="logo.svg">`), the hook, the supporting
  line, the three steps, the three features, the payoff line, and the end card's name, tagline, CTA and URL.
- The mock app inside the browser frame (marked `data-st-decor`: UI detail, so `showtime check` does not
  hold its small labels to the text-size floor). Swap it for a real capture
  (`<div class="frame" data-st="browser-frame" data-src="shots/app.png">` from `showtime site capture`) or a
  `showtime demo record` clip, and retarget the cursor (`#go`) and the `data-zoom` push to the real button.
- There are no numbers on screen on purpose: a stat needs a real, cited source. To add one, put a
  `data-st="count-up"` with the sourced figure in the features or formats scene and show the source line.

Sizes: hero type is 11% of the frame height (landscape), product window 70% of the frame width, body
copy >= 3% of the height, labels >= 2.8%; body and labels are >= 7:1 against the ground. Tall frames keep all
copy inside the short-form safe box (x 6-85 %, y 11.5-75 %); the `@container` blocks at the end of the style
re-lay every scene for square and tall frames.

Timing rules used here: first motion within 0.2 s of each scene start, the hook holds long enough to read,
one camera move per beat, holds of ~1 s before each cut, one accent colour, one shader transition.

Aspects: 16:9 as shipped; `showtime new dom <dir> --aspect 9:16` or `--aspect 1:1` pass `showtime check`
with no warnings. Length: 15 s as shipped; `--duration 10` still passes the phone check's reading times, because
the hook and the feature lines are short (about 4 words). Longer copy needs a longer video.

Commands:
- `showtime preview .`  player with scrubber and audio
- `showtime check .`    pre-render QA (layout, contrast, text size, determinism, fonts)
- `showtime render . --preview` then `showtime render .`

Component and transition reference: `references/components.md`, `references/transitions.md`.

Length: `showtime new dom <dir> --duration <s>` (or `showtime retime <dir> -d <s>` later) moves the whole timeline together: the four scenes' `data-dur`, the poster, the music sections and every sound effect. Longer cuts keep every animation's speed and hold each scene longer; shorter cuts scale everything. Then run `showtime check`: it fails with `dead_air` when the scenes end before the video does.

The length as shipped and after `--duration`/`retime` is `duration` in `showtime.json` (this README states no times, so it never goes stale).

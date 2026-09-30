# Math and diagram explainers with Manim

Read this when the user wants an equation, a proof, a function graph, geometry, a grid or matrix
transform, or any math or diagram explainer, or asks for Manim by name. It covers the engine choice,
the project, the `st_manim` scene kit, the craft rules (with numbers), narration sync, integration
with pages and footage, and LaTeX setup per OS.

## Essentials

- Order: `showtime job init <slug> --goal "..."`, beat sheet and narration, `showtime manim new <job>/manim`
  (`--template equation|graph|plane|refine|blank`, `--aspect 9:16`), then
  `showtime voice script <job>/manim/narration.md -o <job>/manim/voice/` (`--fit <s>`) (§2)
- `showtime manim cues <job>/manim` prints the line ids and numbered words that `beat()`, `at()` and
  `fit(until=)` take; never name a line after a word the narration says (`cue_ambiguous`) (§2, §9)
- `showtime manim check <job>/manim` until 0 errors and every WARN read; for a 9:16 cut also run it with
  `--aspect 9:16` (§2)
- Draft `showtime manim render <job>/manim` (480p15 + contact sheet): every scene's last frame must look
  finished. Final `--quality final -o <job>/final.mp4`, then `showtime qa <job>` (§2)
- Write scenes with `from st_manim import *` on `ShowScene` (`ShowCameraScene`, `Show3DScene`), never a plain
  `Scene`: its waits are frame-snapped (§9, §12)
- `self.beat("<line id>")` starts a beat; `self.at(cue)` starts 0.3 s before the word; `self.fit(anim,
  until=cue)` ends as the word starts; `self.hold(s)`; `self.mark("poster")` (§9)
- Scenes sit on the voice's clock: no animation before the first beat. Fix `cue_late` by shortening what comes
  before or cueing an earlier word, never by speeding the voice (§10)
- Frame 0 is the thumbnail: `self.add()` the hook (title, first equation or picture) right after the first
  `beat()`, never fade it in from the empty ground. On an empty scene `beat()` holds the voice's lead-in on
  whatever you add() next, so `self.beat("hook"); self.add(hook)` opens on the hook
- Place by region (`place(mob, "top")`), not absolute coordinates: the short side is always 8 units (§3, §9)
- Plan beats first: one beat = one narration line = 1-3 animation calls + a hold; 3-6 beats per scene (§4)
- Pacing: a visual change every 3-6 s, first motion within 0.5 s, no still over 2.5 s mid-video (WARN from
  2.5 s, FAIL from 6 s), final hold 2-3 s (§5)
- Equations: build with `eq(tex)`, write the headline once and then only `morph(a, b)`; one change per step;
  every frame is a true statement that matches the picture (§6)
- Colour: one emphasis colour `T.emph`, never on a variable; 3-5 hues bound to concepts in `manim.json`
  `"colors"`; scaffolding in greys (§7)
- On screen: titles 4 words, labels 3, callouts and notes 8, never the narration itself (§8)
- Words and math on one line: `mixed_line()` or `align_baseline()`, never `arrange(aligned_edge=DOWN)` (§8, §12)
- Seed randomness inside `construct`; no `add_sound`; `counter()` needs no LaTeX (`DecimalNumber` does) (§12)
- Remove a group's members (`self.remove(x, y)`), never a fresh `VGroup(x, y)` (§12)
- showtime never installs LaTeX; `showtime doctor` and `showtime manim check` print the install line (§13)
- Clip for a page: `--alpha --fps 30 -o <page>/media/proof.webm`; VP9 alpha does not play in Safari, so for
  `showtime export html` bake the page to MP4 or render without `--alpha` (§11)

<!-- section lines: kept current by scripts/check_release.py -->
| Section | Lines |
|---|---|
| 1. When Manim, and which engine | 61-79 |
| 2. Quick path | 81-99 |
| 3. The project | 101-125 |
| 4. Planning: the beat sheet first | 127-137 |
| 5. Pacing (numbers) | 139-154 |
| 6. Equations | 156-177 |
| 7. Colour | 179-191 |
| 8. Craft by topic | 193-253 |
| 9. The kit (from st_manim import *) | 255-288 |
| 10. Narration sync | 290-319 |
| 11. Integration | 321-335 |
| 12. Pitfalls | 337-363 |
| 13. Setup and LaTeX per OS | 365-389 |

## 1. When Manim, and which engine

| Build it with | When |
|---|---|
| Manim (this file) | exact math: LaTeX equations that morph, constructions, plots, grids, proofs |
| canvas film (`references/film-api.md`) | illustrated or stylised explainers, metaphors, characters of your own |
| DOM page (`references/components.md`) | UI, product, text-heavy motion graphics |

Mixing is normal: a Manim clip can be a layer in a page or an overlay on footage (section 11).

**Engines.** Manim Community (the `manim` extra, pinned 0.21.x) is the default: released, CPU-only
(cairo), headless on every OS, encoded by PyAV. The `st_manim` kit, cues, checks and caching all use
it. ManimGL is optional (`showtime setup --with manimgl`, its own venv): the pinned PyPI release is
1.7.2 from late 2024, an OpenGL renderer that needs an OpenGL 3.3 context (on a Linux server with no
display showtime runs it under `xvfb-run` by itself; install the `xvfb` package once). Its newer GPU
renderer is not released, so showtime does not ship it. Use ManimGL only
for scene files already written for it (`from manimlib import *`); `showtime manim render` detects that
import and renders them as they are, with no kit, cues or checks. For 3D-heavy scenes it is faster and
depth-correct; everything else belongs in Manim Community.

## 2. Quick path

1. `showtime job init <slug> --goal "..."`, then write the beat sheet (section 4) and the narration.
2. `showtime manim new <job>/manim` (`--template equation|graph|plane|refine|blank`, `--aspect 9:16`).
   *Done when:* the folder has `manim.json`, `scenes.py`, `narration.md`.
3. `showtime voice script <job>/manim/narration.md -o <job>/manim/voice/` (add `--fit <s>` for a target length).
4. `showtime manim cues <job>/manim` lists each line id and its numbered words: the names `beat()`,
   `at()` and `fit(until=)` take.
5. Write the scenes. `showtime manim check <job>/manim` until it reports 0 errors and you have read
   every WARN (its still-hold rule uses qa's thresholds, and after the dry run it renders the draft and runs qa's
   black and frozen-frame detectors on it, so the near-black default ground with sparse content and a small
   `Indicate` on an equation show up here, not after the final; `--no-draft` skips that). For a 9:16 cut, also
   `showtime manim check <job>/manim --aspect 9:16`: the portrait layout has its own holds and safe area.
6. `showtime manim render <job>/manim` (draft: 480p15 plus a contact sheet). Judge the sheet once (`looking.md`): every
   scene's last frame must look like a finished composition.
7. `showtime manim render <job>/manim --quality final -o <job>/final.mp4`, then `showtime qa <job>`.

Without a voice yet, check and draft renders estimate the timing from `narration.md` at a calm
2.6 words per second and say so; the real voice replaces the estimate on the next render.

## 3. The project

`manim.json` (every key optional): `title`, `file` (default `scenes.py`), `scenes` (play order;
default every scene class in file order), `aspect` (`16:9`, `9:16`, `1:1`, `4:5`), `fps` (final;
drafts use 15), `voice` (default `voice/timeline.json`), `narration` (default `narration.md`),
`colors` (one colour per concept, below), `brand` (a brand.json path; default: found from the
folder like every showtime command), `light` (the brand's light palette), `mix` (music and effects).

**Frame units.** The short side of the frame is always 8 units: 16:9 is 14.22 x 8, 9:16 is
8 x 14.22, 1:1 is 8 x 8. Manim's own default keeps 14.22 x 8 whatever the pixel size, which shrinks
vertical content to about 40 %; showtime sets the frame explicitly. Place things by region, not
absolute coordinates, and a 9:16 cut re-lays itself out: `showtime manim render <p> --aspect 9:16`.

**Outputs.** `<project>/out/<title>-draft.mp4` plus `-sheet.jpg`, or `<title>.mp4` plus `poster.jpg`
for finals (`-o` chooses the file; a video is never overwritten: `final.mp4` becomes `final-2.mp4`).
The poster is named like `showtime render` names it: `poster.jpg` beside `-o <job>/final.mp4` (also
when it is saved as `final-2.mp4`; the newest render's poster replaces it), `<stem>.poster.jpg` beside
any other name. `build/` holds caches and logs; delete it any time.

**Caching.** Each scene's key hashes its own class and its in-file bases, the module-level code
(helper functions, constants and non-scene classes such as a layout class), other files in the
folder, the cue lines it uses, the theme, the size and the kit version. Editing one scene or
re-voicing one line re-renders only the scenes involved. Inside a scene, Manim's per-animation cache
skips unchanged animations. Equations compile once into `~/.showtime/cache/manim/tex`. `--fresh`
ignores every cache.

## 4. Planning: the beat sheet first

- Write the video as short verb-led beats before any code: "Show the triangle", "Label the sides",
  "Slide the pieces", "Ask: why the same?", "Reveal the equation". One beat = one narration line =
  one to three animation calls plus a hold. Keep the sheet as the docstring of `scenes.py`.
- One idea per scene, 3-6 beats, 8-40 s of screen time. Many short scenes beat one long one: they
  render and cache independently and re-time cleanly.
- Scene k+1 opens on scene k's last frame (same objects, same places); cut hard only when the topic
  changes.
- Expose counts, colours and ranges as parameters so "the same at 8, 32 and 128 pieces" is a loop,
  not a copy.

## 5. Pacing (numbers)

| Thing | Value |
|---|---|
| a visual change | every 3-6 s, one per narrated clause |
| start the motion before its word | 0.2-0.5 s (`at()` default lead 0.3 s) |
| hold between small beats / after a result / after the payoff | 1 s / 2-3 s / 3-5 s |
| longest still frame | under 2.5 s mid-video (check and qa WARN from 2.5 s, FAIL from 6 s; end hold up to 4 s). A thin line, a small label, a slow sweep of a radius or an `Indicate` on one equation does not count as movement for either: check reports what qa's detector sees on the draft as `frozen`. qa calls a frame black only when almost nothing is visible (99.5 % of it dark): a title or an equation on Manim's near-black ground is fine, an empty ground between beats is not; for a light look, `"light": true` in manim.json |
| run times: fade, label, pulse / write, draw / meaningful transform / process / camera sweep | 0.5-1 / 1-2 / 2-4 / 5-10 / 10-20 s |
| stagger (`lag_ratio`): 2-4 items / 3-20 / hundreds | 0.3-0.5 / 0.1-0.25 / 0.01-0.05 (the whole wave 1-2 s) |
| first motion | within 0.5 s of the start |
| final hold | 2-3 s on the key image |

Alternate: after a 3 s structural transform, make the next beat short (a label, a pulse). Use linear
easing for time-driven processes and long drifts, the default smooth easing for "here is the shape",
there-and-back for pulses.

## 6. Equations

- Split before you animate. `eq(tex)` does it: each variable with its scripts, number, operator,
  command with its arguments and `\left...\right` group is its own part, and any concept declared
  in `colors` (`"2n-1"`, `"n^2"`) is merged into one part. Parts inside `\frac{..}{..}` or
  `\sqrt{..}` stay inside their command: restructure (`a^2 = (c-b)(c+b)` rather than a root) or morph
  the whole fraction.
- Write the headline once; afterwards it only morphs. `morph(a, b)` moves matching parts, fades the
  rest toward where they go, and swings parts that cross the relation sign on a 40 degree arc
  (never a straight line through other glyphs). `key_map={"+": "-"}` turns one part into another.
- Change one thing per step; unchanged parts stay pixel-still (place `b` over `a` first).
- **Every frame is a true statement that matches the picture.** A still is judged on its own: an
  equation ahead of its tiles ("1+3+5 = 2²" beside a 2x2 grid while the third layer flies in) reads as
  wrong maths. Add the new term, its picture and the new result in the same `play()` (or bring the term
  in only after the picture lands, and update the result in that step); never leave a stale result
  showing while the left side has already grown. Same for counters and totals next to a diagram.
- Focus without deleting: `dim_others(e, ["x"])` (to 35 %), a `highlight()` box, then `undim(e)`.
- Braces carry 1-3 word labels. Derivations stack with aligned relation signs (`stack()`), at most 3-4
  lines, older lines faded.
- `equation_walkthrough(self, steps)` does all of this with `cue`, `focus`, `note` and `key_map` per step;
  `font_size=100-120` when the equation is the whole picture (math is thin ink: at 72 a morph alone is a
  hold for qa), and a slow camera push (`ShowCameraScene`, 5 %) keeps long walkthroughs moving.

## 7. Colour

- One emphasis colour (the brand accent, `T.emph`) means "look here now": boxes, pulses, the payoff.
  Never give it to a variable.
- 3-5 semantic hues (`T.hue(1)`...), each bound to one concept for the whole video through
  `manim.json` "colors": the shape, the term, the label and the graph of "x" share one hue. The viewer
  learns the colour from the picture before the symbol appears.
- Scaffolding in greys: axes and grids at `T.grid`, ghosts at 30-50 % opacity.
- The kit derives the hues per theme: each reaches 4.5:1 on the background, stays clear of the
  emphasis colour and of the brand's second accent, and the set stays apart under common colour-vision
  deficiencies. A brand colour that fails 4.5:1 (a deep red on a dark stage) is used for fills only.
- The default look without a brand is warm near-black with an ember emphasis and a grotesk display
  face. Do not imitate any channel's signature look.

## 8. Craft by topic

**Picture before algebra.** Concrete instance, then picture, then pattern, then symbol. Show
1 + 3 + 5 as tiles before writing the sum; small numbers first (n = 4), then larger, then n. The
symbol arrives as a label for what is already on screen. Fly a copy of the shape into its symbol
(`TransformFromCopy`) so "this term IS that area". A rearrangement proof moves slowly (2-4 s per
group), keeps each piece's colour, and holds before/after side by side for 2 s. Refinement ladders
(`refine()`) step 4, 8, 16, 32 pieces, faster each time (2, 1.5, 1, 0.7 s); `refine(..., start=mob)`
continues from a picture already on screen (the first step transforms it) and `tag="N = %d"`, a
callable `n -> mobject` or `None` sets the step label. A ladder that crosses two narration lines is
two `refine()` calls: the second one with `start=` the first one's result. Show the tempting wrong
picture first when it is common.

**Graphs.** Axes first (1 s), tick labels only where needed. `graph_build()` shows a faint preview of
the whole curve, then traces it (linear when x is time) with a glowing tip; `area=True` fills the area under
it with the trace (a thin curve alone is too small a change for qa's frozen-frame detector). Compare curves on one set
of axes in two hues; rescale axes smoothly instead of cutting to new ones.

**Grids and matrices.** `plane_transform(self, [[1, 1], [0, 1]])`: a faint static grid stays as
"before", the moving grid is twice the frame so its edges never show, basis vectors ride on it in two
hues and the matrix columns use the same two hues. 3-4 s, then 2 s of hold; one transform per beat.
Nonlinear maps need a subdivided grid (`prepare_for_nonlinear_transform`).

**Live numbers and sweeps.** Values count up (`counter()` + `count_to()`, 1-2 s, no LaTeX needed,
fixed digit widths). Sweep a parameter extreme, other extreme, then the usual value, about 2 s each
with 1 s holds, and change formula, number and picture in the same animation.

**Camera.** 2D moves only for a reason (follow, make room, go to a detail), 1.5-3 s, and not during a
meaningful transform. Zoom across large scales exponentially.

**3D.** `Show3DScene`: start looking straight down so it reads as a 2D diagram, then tilt (3-5 s).
Orbit at 1-3 degrees per second; pin labels to the screen (`add_fixed_in_frame_mobjects`). Keep 3D
sections short (20-40 s) and 20 x 20 faces or fewer: Manim Community draws 3D on the CPU (on a 6-core laptop, about 20x
slower than real time at 1080p) and cannot depth-sort, so draw axes behind surfaces on purpose.

**Words on screen.** The narration carries sentences; the screen carries labels. Titles 4 words,
labels 3, callouts and notes 8, one line at a time, next to what they name, no legends, never the
narration itself. Tiers: `title()` (display font), `callout()`, `label()`, `note()`; each gets a
backstroke in the background colour so it reads over grids. Questions ("Why n squared?") are good
on-screen text; answer them visibly later.

**Words and math on one line.** "Why πr²?", "Area = πr²", "rings 8": build them with
`mixed_line("Why", tex(r"\pi r^2"), "?", size=88)` (tiers as `tier="callout"` etc.), or, for parts you
place yourself, `align_baseline(words, math_or_number)`. Text (Pango, the theme fonts) and `MathTex`
(LaTeX, Computer Modern) come from two engines: `arrange(RIGHT)` centres their boxes and
`aligned_edge=DOWN` lines up their lowest points, so a descender ("y", "g") or a superscript drags a
part off the baseline, and CM's small x-height makes math at the same font size read a size smaller.
`mixed_line` measures each part on its glyphs, puts every part on the text's baseline, scales the math
to the text's x-height (`match="cap"` for math that is mostly capitals and digits) and, beside
SEMIBOLD or heavier text, sets it in `\boldsymbol`. The trade-off: CM bold matches 600-700 text but is
still lighter than an 800-900 display weight, so beside ULTRABOLD/HEAVY text the math also gets an
outline in its own colour, 6 % of the x-height wide (`thicken=`; it fills small counters as it grows,
so keep it at 0.08 or less and look at a full-size frame). `line[1]` is the second part (animate it
like any mobject). `showtime manim check` measures every words-plus-math or words-plus-number pair on
screen and warns `baseline_mismatch` (more than 4 % of the cap height apart), `xheight_mismatch` (math
x-height more than 12 % off) and `mixed_type` (words and math placed by hand).

**Quality details.** Strokes at 1080p: data 4-5 px, construction 2 px, grids 1-1.5 px. Nothing touches
the frame edge (the safe area is 0.45 units, more at the top and bottom on 9:16 for platform UI).
Remove what is no longer needed (0.5 s fades); no more than about 5 groups on screen. End on the
image.

## 9. The kit (`from st_manim import *`)

```python
from st_manim import *              # all of manim, plus the kit

class Proof(ShowScene):             # ShowCameraScene (movable frame), Show3DScene
    def construct(self):
        self.beat("hook")           # the narration line "hook" starts here
        t = title("Same frame, same pieces")
        place(t, "top")             # regions: top middle bottom main center upper lower left right *_third
        self.add(t)                 # on screen at t=0: frame 0 is the thumbnail
        e = eq(r"a^2 + b^2 = c^2")  # parts coloured from manim.json "colors"
        self.at("squared")          # 0.3 s before the word
        self.play(Write(e))
        self.fit(Indicate(e["c^2"]), until="same#2")   # ends as the word starts
        self.hold(2)                # frame-snapped
        self.mark("poster")         # this frame becomes poster.jpg
```

- Theme `T`: `T.bg T.surface T.ink T.muted T.emph T.grid T.ghost`, `T.hue(i)`, `T.var("x")`,
  `T.color("hue2"|"emph"|"#hex")`, fonts `T.display`/`T.body` (installed as files and registered;
  `showtime assets font` installs a brand font on the first render).
- Layout: `place(mob, region, align=)`, `region()`, `region_center()`, `safe_box()`, `fit_width()`,
  `is_portrait()`, `frame_size()`.
- Lines: `mixed_line(*parts, tier=, size=, match="x"|"cap", bold=, thicken=, gap=)` with strings, `tex(r"...")`
  parts and mobjects; `align_baseline(a, *others)`; `baseline(mob)`, `x_height(mob)`, `line_metrics(mob)`
  (Text, MarkupText, MathTex/Tex/`eq()`, `counter()`, which keeps its baseline as it counts).
- Effects: `glow_dot(point)`, `glow(mob)` (layer count drops in drafts), `highlight(mob)`,
  `ghost(mob)`, `backstroke(mob)`, `counter()`/`count_to()`.
- Cues: a word (`"five"`), its n-th occurrence (`"four#2"`), a word of another line
  (`"rule:squared"`), a line id (its first word) or `"<id>.end"` (its last word), or seconds since the
  scene start. Do not name a line after a word the narration says (`## half` when a line says
  "half"): inside a line that says the word, `at("half")` means the word; everywhere else the line.
  `manim check` warns (`cue_ambiguous`). `self.cue_time(cue)` gives the time; `self.now` is the scene clock.

## 10. Narration sync

- Scenes sit on the voice's clock: the first scene starts at 0, every other scene at the slot start of
  its first beat, and each scene ends at the slot end of its last beat. Concatenated, they line up
  with `vo.wav` exactly, so the render muxes the voice as is.
- Every `play` and `wait` is snapped to whole frames (Manim rounds animations up and still holds down,
  which drifts up to a frame per call). Cue landings are exact to the frame.
- A reveal that cannot start before its word is logged; `check` reports `cue_late`. Fix it by
  shortening what comes before or cueing an earlier word, never by speeding the voice.
- A scene without beats, or animation before the first beat, moves the scenes off the voice's clock:
  the render then places every line at its measured start through `showtime audio mix` and says so.
- Music and effects: `--mix audio/mix.json` (format in `references/audio.md`); the voice tracks are
  added from the cues and the bed ducks under them. Math wants a restrained bed (`underscore` or
  `ambient-pad`, sections `intro`/`verse`/`outro`) or none; never a bright corporate or plucky
  style (`music.md` section 1). Effects on events: one or two (a soft click on a count-up, a chime
  on the payoff), not a pop on every step, at the times `showtime manim cues` prints.

**Silent film (music and on-screen words, no voice).**
1. Leave `narration.md` without lines (the stub's comment alone is fine) or delete it. `check` and
   `render` treat that as no narration: no cues, no estimate, no error.
2. Pace with `play(run_time=...)` and `self.hold(s)`, not `beat()`/`at()`; the on-screen words carry
   the story, so give each a read-time hold (section 5). `showtime manim check <p>` prints each
   scene's seconds; their sum is the length.
3. Music cut to that length: `showtime audio compose --style underscore --dur <total> --sections
   "0:intro,<t>:verse,<t>:outro" -o <p>/audio/bed.wav`, then `<p>/audio/mix.json` with
   `{"tracks": [{"id": "bed", "kind": "music", "file": "audio/bed.wav", "fade_out": 1.5}]}` plus one
   or two effects (`"at"` = the scene start + the event's time in it). A track's `file` is found
   beside the mix spec, then in the Manim folder, then in the current folder.
4. `showtime manim render <p> --quality final --mix audio/mix.json -o <job>/final.mp4` (or `"mix":
   "audio/mix.json"` in `manim.json`). `--mix` is read from the current folder first, then the project.

## 11. Integration

- **In a DOM or film page.** Render the clip with alpha at the page's fps:
  `showtime manim render <p> --scene Proof --alpha --fps 30 -o <page>/media/proof.webm` and add
  `<video src="media/proof.webm" data-start="12" muted playsinline style="position:absolute;inset:0;width:100%;height:100%">`
  (in a film page, after the canvas). Stage.js seeks it frame-exactly (`references/stage-api.md`);
  keep its sound in the page's audio mix. `showtime render` bakes it into the MP4.
- **Safari and alpha.** VP9 alpha plays in Chrome, Edge and Firefox, not Safari. For anything shared as
  HTML (`showtime export html`), render the page to MP4 first so the layer is baked in, or render the
  clip without `--alpha` on the page's background colour.
- **Over footage.** `--alpha -o <job>/edit/eq.webm` and an EDL `overlays[]` entry with
  `"position": "full"` (`references/editing.md`); the EDL render decodes VP9 alpha.
- **For editors.** `--alpha prores` writes ProRes 4444 with alpha (large, lossless-grade).
- **ManimGL files** (`from manimlib import *`) render in their own venv; the kit, cues and `check`'s
  dry run are Manim Community only. The render summary reports the file's probed duration.

## 12. Pitfalls

- A vertical render made with plain `manim -r 1080,1920` shrinks everything; use `showtime manim
  render --aspect 9:16` (or the kit, which sets the frame on import).
- Raw `self.wait()` in a plain `Scene` drifts; use `ShowScene` (its waits are snapped).
- `DecimalNumber`, `Integer`, `Matrix`, numbered axes and `MathTex` all need LaTeX; `counter()` does not.
- A number that changes inside a static group can leave stale digits in Manim; `counter()` is built to
  avoid it, other updater-driven text should be added to the scene on its own.
- `always_redraw` rebuilds every frame: keep it to small objects.
- Glow layers, 3D faces and hundreds of objects are what makes renders slow; drafts cap glow layers.
- Randomness: seed it (`random.seed(3)`, `np.random.seed(3)`) inside `construct`, or caches never hit.
- Don't use `add_sound`: sound goes through the voice and the mix.
- Fonts are files: the theme registers them; a family name alone falls back to Pango's default.
- Backstrokes use the background colour, not black.
- `self.play(VGroup(a, b).animate.shift(UP))` puts that new group into `self.mobjects` with `a` and `b`
  inside it, so a later cleanup such as "remove everything except a and b" removes the group and them
  with it. Clean up by listing what to remove, and remove a group's members, not a fresh
  `VGroup(x, y)`: `self.remove(VGroup(x, y))` removes nothing (Manim Community does not look inside a
  group it was not given): `self.remove(x, y)`.
- A wide diagram on a 9:16 frame: write its geometry in its own frame axes (an origin `O`, a unit `U`
  along the base, `V` up) and draw every part through them. `U = RIGHT, V = UP` gives the 16:9 layout;
  `U = DOWN, V = RIGHT` (a quarter turn) the portrait one, with the same code. Then check it with
  `showtime manim check <p> --aspect 9:16`.
- Words and math (or a number) on one line never go through `arrange(aligned_edge=DOWN)` or a nudge by
  eye: use `mixed_line()` or `align_baseline()` (section 8). Look at the title frames at full size
  (`showtime snap <video> --at 0`), not on a contact sheet: a baseline jump of a few pixels vanishes in
  a thumbnail and is obvious on a phone.

## 13. Setup and LaTeX per OS

Manim Community installs itself into the main venv before the first Manim render (about 60 MB,
announced; `showtime setup --fetch manim` or `--with manim` does it now) and is smoke-tested. Text,
shapes, graphs and planes need nothing else. Equations need LaTeX, which showtime never installs itself
(admin rights, size); `showtime doctor` and `showtime manim check` print the exact line:

| OS | Install |
|---|---|
| macOS (Apple Silicon and Intel) | `brew install --cask basictex` (BasicTeX 2026), open a new terminal, then `sudo tlmgr update --self && sudo tlmgr install standalone preview doublestroke relsize fundus-calligra wasysym physics dvisvgm rsfs wasy cm-super jknapltx mathastext microtype setspace xcolor everysel ragged2e babel-english` (there is no `ms` package in TeX Live 2026) |
| Windows 10/11 | `winget install MiKTeX.MiKTeX`, then `initexmf --set-config-value=[MPM]AutoInstall=1` so missing packages install on first use (the first equation render can take minutes) |
| Linux | TeX Live 2026 (scheme-basic) plus the same `tlmgr install` list, or the distro packages: `sudo apt install texlive texlive-latex-extra texlive-fonts-extra texlive-science cm-super dvisvgm` (Debian/Ubuntu), `texlive-scheme-basic` plus the listed `texlive-*` packages (Fedora), `texlive-basic texlive-latexextra texlive-fontsextra texlive-science` (Arch) |

TeX installed from a GUI session is often missing from PATH; showtime also looks in the usual folders
(`/Library/TeX/texbin`, `/usr/local/texlive/<year>/bin/...`, MiKTeX and TeX Live on Windows) and puts
the one it finds first for renders.

**Build errors when installing manim.** pycairo (and manimpango on Linux) compile against system
libraries on macOS and Linux: macOS `brew install cairo pango pkg-config`; Debian/Ubuntu
`sudo apt install libcairo2-dev libpango1.0-dev pkg-config python3-dev`; Fedora
`sudo dnf install cairo-devel pango-devel pkgconf-pkg-config python3-devel`; Arch
`sudo pacman -S cairo pango pkgconf`. Windows gets wheels. Then `showtime setup --with manim --force`.

**When a render fails.** The error names the scene, the line in `scenes.py` and the log
(`build/logs/render.log`). A cue word error lists the words the line really has.

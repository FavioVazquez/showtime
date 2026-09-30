# Manim: math and diagram explainers

Projects made with `showtime manim new <dir> [--template example|equation|graph|plane|refine|blank]`.

- `example/`: a narrated explainer in two scenes ("odd numbers build squares"): each spoken number drops
  into the sum while a running total ticks up, copies of each term fly down and become its band of
  tiles in the same colour, the square is boxed and braced, the sum morphs into 4^2 and then into the
  general rule. It passes `showtime manim check` with no warnings: the hook is on screen at t=0 and
  something visible changes every 1-2 s. Files: `manim.json` (settings, one colour per concept),
  `scenes.py` (the beat sheet is its docstring), `narration.md` (one `## id` heading per beat).
- `patterns/`: one-scene starters that run without narration: `equation.py` (walkthrough with morphs,
  focus and a note), `graph.py` (axes, faint preview, traced curve with a glowing tip), `plane.py`
  (shear with ghost grid and coloured basis; needs LaTeX for the matrix), `refine.py` (approximation
  ladder), `blank.py`.

Voice it with `showtime voice script <dir>/narration.md -o <dir>/voice/`, list the cue words with
`showtime manim cues <dir>`, then `showtime manim check <dir>` and `showtime manim render <dir>`. The
length comes from the voice (every reveal waits for its word), so this README states no times. Without
a voice, timing is estimated from `narration.md`.

Guide: `references/manim.md`.

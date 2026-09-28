# Manim: math and diagram explainers

Projects made with `showtime manim new <dir> [--template example|equation|graph|plane|refine|blank]`.

- `example/`: a narrated explainer in two scenes ("odd numbers build squares"): the sum is written term
  by term on each spoken number, tiles in the same colours build the square, the sum morphs into 4^2
  and then into the general rule. Files: `manim.json` (settings, one colour per concept),
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

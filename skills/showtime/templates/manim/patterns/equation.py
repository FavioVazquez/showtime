"""Equation walkthrough: write a line once, then only morph it, one change per step.

Beat sheet
  1. Write the starting equation
  2. Move b^2 across the equals sign (it travels on an arc, its colour stays)
  3. Factor the difference of squares; box a^2 while the narration names it

Colours come from manim.json "colors" when declared; here they are passed inline to stay self-contained.
With narration, add self.beat("<line id>") and give steps a "cue" word (showtime manim cues <dir>).
"""
from st_manim import *

COLORS = {"a": "hue1", "b": "hue2", "c": "emph"}


class Walkthrough(ShowScene):
    def construct(self):
        t = title("Rearrange the sides")
        place(t, "top")
        self.play(FadeIn(t, shift=0.2 * UP), run_time=0.7)
        final = equation_walkthrough(self, [
            {"tex": r"a^2 + b^2 = c^2", "hold": 1.0},
            {"tex": r"a^2 = c^2 - b^2", "key_map": {"+": "-"}, "hold": 1.0},
            {"tex": r"a^2 = (c - b)(c + b)", "focus": "a^2", "note": "the unknown square", "hold": 1.2},
        ], colors=COLORS)
        self.play(Circumscribe(final, color=T.emph), run_time=1.0)
        self.hold(2.0)

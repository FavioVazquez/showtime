"""Plane transform: a shear shown on the whole grid.

Beat sheet
  1. The grid, with the basis vectors in two hues
  2. The matrix appears (its columns in the same hues) and the grid shears; a faint grid stays behind as "before"
  3. Hold on the result

Needs LaTeX for the matrix (showtime manim check prints the install line for this OS).
"""
from st_manim import *


class Shear(ShowScene):
    def construct(self):
        plane_transform(self, [[1, 1], [0, 1]], run_time=3.0, hold=1.5)
        c = callout("Every line stays a line")
        place(c, "bottom")
        self.play(FadeIn(c, shift=0.2 * UP), run_time=0.7)
        self.hold(2.0)

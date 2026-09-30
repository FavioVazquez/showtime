"""Approximation refinement: the same picture at 4, 8, 16 and 32 pieces, faster each step.

Beat sheet
  1. The title and the circle's outline (on screen at t=0); its area by stacked rectangles, coarse
  2. Refine: each step replaces the last, quicker, until the steps vanish into the curve
  3. Hold on the fine version next to the exact outline
"""
from st_manim import *


R = 2.3             # the disc's radius: it fits the main region, under the title band


def slices(n: int) -> VGroup:
    """n horizontal strips filling a disc of radius R (a Riemann-style staircase)."""
    r = R
    g = VGroup()
    h = 2 * r / n
    for i in range(n):
        y = -r + (i + 0.5) * h
        w = 2 * np.sqrt(max(r * r - y * y, 0))
        rect = Rectangle(width=w, height=h * 0.94, stroke_width=0)
        rect.set_fill(T.hue(1), opacity=0.9 if i % 2 == 0 else 0.7)
        rect.move_to(np.array([0, y, 0]))
        g.add(rect)
    g.move_to(region_center("main"))
    return g


class Refine(ShowScene):
    def construct(self):
        t = title("Strips fill a circle")
        place(t, "top", align="left")  # the step label n = 4, 8, ... sits top right
        outline = Circle(radius=R, color=T.muted, stroke_width=2).move_to(region_center("main"))
        self.add(t, outline)          # frame 0 is the thumbnail: the title and the outline are there at t=0
        refine(self, slices, ns=(4, 8, 16, 32), run_times=(1.2, 1.0, 0.8, 0.6))
        self.play(outline.animate.set_stroke(T.emph, width=4), run_time=0.8)
        self.hold(2.0)

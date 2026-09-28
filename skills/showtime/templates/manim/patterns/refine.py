"""Approximation refinement: the same picture at 4, 8, 16 and 32 pieces, faster each step.

Beat sheet
  1. A circle's area by stacked rectangles, coarse
  2. Refine: each step replaces the last, quicker, until the steps vanish into the curve
  3. Hold on the fine version next to the exact outline
"""
from st_manim import *


def slices(n: int) -> VGroup:
    """n horizontal strips under a half disc of radius 2.4 (a Riemann-style staircase)."""
    r = 2.4
    g = VGroup()
    h = 2 * r / n
    for i in range(n):
        y = -r + (i + 0.5) * h
        w = 2 * np.sqrt(max(r * r - y * y, 0))
        rect = Rectangle(width=w, height=h * 0.94, stroke_width=0)
        rect.set_fill(T.hue(1), opacity=0.9 if i % 2 == 0 else 0.7)
        rect.move_to(np.array([0, y, 0]))
        g.add(rect)
    g.move_to(region_center("middle"))
    return g


class Refine(ShowScene):
    def construct(self):
        outline = Circle(radius=2.4, color=T.muted, stroke_width=2).move_to(region_center("middle"))
        self.play(Create(outline), run_time=0.8)
        refine(self, slices, ns=(4, 8, 16, 32), run_times=(1.2, 1.0, 0.8, 0.6))
        self.play(outline.animate.set_stroke(T.emph, width=4), run_time=0.8)
        self.hold(2.0)

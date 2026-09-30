"""Equation walkthrough: write a line once, then only morph it, one change per step.

Beat sheet
  1. Write the starting equation
  2. Move b^2 across the equals sign (it travels on an arc, its colour stays)
  3. Factor the difference of squares; box a^2 while the narration names it
  Throughout: the title is on screen at t=0, and the camera pushes in slowly (5 %): math is thin ink, so
  a written or morphing line alone is too small a change for qa's frozen-frame detector

Colours come from manim.json "colors" when declared; here they are passed inline to stay self-contained.
With narration, add self.beat("<line id>") and give steps a "cue" word (showtime manim cues <dir>).
"""
from st_manim import *

COLORS = {"a": "hue1", "b": "hue2", "c": "emph"}


class Walkthrough(ShowCameraScene):
    def construct(self):
        t = title("Rearrange the sides")
        place(t, "top")
        self.add(t)                   # frame 0 is the thumbnail: the title is there at t=0
        push = self.camera.frame
        push.add_updater(lambda m, dt: m.scale(1 - 0.004 * dt))   # a slow push, about 5 % over the scene
        self.add(push)
        # the equation is the whole picture: large (font_size 110), holds under 1 s
        final = equation_walkthrough(self, [
            {"tex": r"a^2 + b^2 = c^2", "hold": 0.8},
            {"tex": r"a^2 = c^2 - b^2", "key_map": {"+": "-"}, "hold": 0.8},
            {"tex": r"a^2 = (c - b)(c + b)", "focus": "a^2", "note": "the unknown square", "hold": 1.2},
        ], colors=COLORS, font_size=110)
        self.play(Circumscribe(final, color=T.emph), run_time=1.0)
        self.hold(2.0)

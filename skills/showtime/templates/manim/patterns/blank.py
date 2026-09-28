"""A blank ShowScene with the kit ready. Replace the beat sheet and the construct body.

Beat sheet (write it first: one verb-led line per beat)
  1. Show ...
  2. Highlight ...
  3. Transition ...
"""
from st_manim import *


class Main(ShowScene):
    def construct(self):
        # self.beat("hook")           # with narration.md / voice/timeline.json: one beat per line
        t = title("Your idea here")
        place(t, "center")
        self.play(FadeIn(t, shift=0.2 * UP), run_time=0.8)
        self.hold(2.0)

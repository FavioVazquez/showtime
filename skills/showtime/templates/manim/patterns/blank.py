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
        self.add(t)                   # frame 0 is the thumbnail: add() the hook, never fade it in from black
        self.play(t.animate.scale(1.06), run_time=2.0)   # a slow push: nothing stands still for long
        self.hold(1.0)

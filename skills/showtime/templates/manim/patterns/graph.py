"""Graph build: axes first, a faint preview of the whole curve, then the curve traced with a glowing tip.

Beat sheet
  1. Label the idea (on screen at t=0)
  2. Build the axes, preview the curve, trace it at constant speed (the x-axis is time); the area under
     it fills with the trace, so the change is big enough to read as motion (a thin line alone is not)
  3. Mark the peak and hold on the finished picture
"""
from st_manim import *


class Growth(ShowScene):
    def construct(self):
        t = title("A damped swing")
        place(t, "top")
        self.add(t)                   # frame 0 is the thumbnail: the title is there at t=0
        f = lambda x: 2.2 * np.exp(-0.35 * x) * np.cos(2.2 * x)
        axes, graph = graph_build(self, f, x_range=(0, 8), y_range=(-2.4, 2.4), where="main", run_time=3.5,
                                  area=True)
        peak = axes.c2p(0, f(0))
        tag = label("start", color="muted").next_to(peak, RIGHT, buff=0.25)
        self.play(FadeIn(tag, shift=0.1 * LEFT), run_time=0.6)
        self.play(graph.animate.set_stroke(width=6), run_time=0.8)
        self.hold(2.0)

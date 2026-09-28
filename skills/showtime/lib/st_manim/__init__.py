"""st_manim: showtime's helper kit for Manim Community scenes.

    from st_manim import *        # everything from manim, plus the kit

    class Squares(ShowScene):
        def construct(self):
            self.beat("hook")
            t = title("Odd numbers")
            place(t, "top")
            self.play(FadeIn(t, shift=0.2 * UP))
            e = eq(r"1 + 3 + 5 = 9", colors={"9": "emph"})
            self.at("five")
            self.play(Write(e))

Theme      T (brand colours, T.hue(i), T.var("x"), fonts registered from files), theme()
Type       title(), callout(), label(), note(), markup(), backstroke()
Lines      mixed_line("Why", tex(r"\\pi r^2"), "?"), align_baseline(a, b), baseline(), x_height()
Equations  eq(), morph(), dim_others(), undim(), stack(), Eq
Beats      ShowScene / ShowCameraScene / Show3DScene: beat(), at(), fit(), hold(), mark(), cue_time(), now
Layout     place(), region(), region_center(), safe_box(), fit_width(), fit_in(), is_portrait(), frame_size()
Effects    glow_dot(), glow(), highlight(), ghost(), counter(), count_to()
Patterns   equation_walkthrough(), plane_transform(), graph_build(), refine()

showtime renders set the frame size, background, fonts, cues and logs through $SHOWTIME_MANIM
(see references/manim.md). A plain `manim` call works too: the theme then comes from the folder's
brand.json and there are no cues.
"""
from manim import *  # noqa: F401,F403

from . import _settings  # noqa: F401  (puts SKILL/lib on sys.path for the stdlib helpers)
from ._layout import (apply_frame, fit_in, fit_width, frame_size, is_portrait, place, region,  # noqa: F401
                      region_center, regions, safe_box)
from ._theme import Theme, theme  # noqa: F401
from ._type import backstroke, callout, label, markup, note, tier_text, title, words_of  # noqa: F401
from ._line import MixedLine, TexPart, align_baseline, baseline, line_metrics, mixed_line, tex, x_height  # noqa: F401
from ._tex import Eq, Morph, dim_others, eq, morph, split, stack, tokens, undim  # noqa: F401
from ._beats import CueError, Show3DScene, ShowCameraScene, ShowScene  # noqa: F401
from ._fx import Counter, count_to, counter, ghost, glow, glow_dot, highlight  # noqa: F401
from ._patterns import equation_walkthrough, graph_build, plane_transform, refine  # noqa: F401

__version__ = "1.0.0"

T = theme()


def _configure() -> None:
    """Frame units from the pixel size (short side = 8) and the theme background."""
    apply_frame()
    if not config.transparent:
        config.background_color = T.bg


_configure()

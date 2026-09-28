"""Small effects with good defaults: glow, highlight box, ghost copy, a count-up number without LaTeX."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
from manim import (ORIGIN, Circle, Dot, MarkupText, SurroundingRectangle, ValueTracker, VGroup, VMobject, config,
                   smooth)

from ._theme import theme
from ._type import backstroke


def glow_dot(point: Any = ORIGIN, color: Optional[str] = None, radius: float = 0.32, layers: int = 12,
             core: float = 0.06) -> VGroup:
    """A small solid dot inside soft rings whose opacity falls off outward (layers cost render time)."""
    T = theme()
    col = T.color(color) if color else T.emph
    if config.pixel_height < 720:
        layers = min(layers, 6)
    rings = VGroup(*[
        Circle(radius=core + (radius - core) * (i / layers) ** 1.4, stroke_width=0)
        .set_fill(col, opacity=min(1.0, 1.8 / layers)).move_to(point)
        for i in range(layers, 0, -1)])
    dot = Dot(point, radius=core, color=col)
    g = VGroup(rings, dot)
    g._st_glow = True  # type: ignore[attr-defined]
    return g


def glow(mob: VMobject, color: Optional[str] = None, layers: int = 6, spread: float = 10.0,
         opacity: float = 0.45) -> VGroup:
    """A halo of widening, faint strokes behind `mob` (returns VGroup(halo, mob))."""
    T = theme()
    col = T.color(color) if color else (mob.get_stroke_color().to_hex() if mob.get_stroke_width() else T.emph)
    if config.pixel_height < 720:
        layers = min(layers, 3)
    base = max(float(mob.get_stroke_width() or 2.0), 1.0)
    halo = VGroup(*[mob.copy().set_fill(opacity=0).set_stroke(col, width=base + spread * i / layers,
                                                               opacity=opacity / layers)
                    for i in range(layers, 0, -1)])
    return VGroup(halo, mob)


def highlight(target: VMobject, color: Optional[str] = None, buff: float = 0.14, width: float = 4.0,
              radius: float = 0.08) -> SurroundingRectangle:
    """A box around the part being talked about, in the emphasis colour. Show it with Create (0.5 s),
    keep it for the sentence, then FadeOut. One box at a time."""
    T = theme()
    return SurroundingRectangle(target, color=T.color(color) if color else T.emph, buff=buff, stroke_width=width,
                                corner_radius=radius)


def ghost(mob: VMobject, opacity: float = 0.3) -> VMobject:
    """A faint copy that previews where something is going (or where it was)."""
    g = mob.copy()
    g.set_opacity(opacity)
    g._st_ghost = True  # type: ignore[attr-defined]
    return g


class Counter(VMobject):
    """A number that counts (no LaTeX needed): tabular digits in the theme font, fixed left edge.

        n = counter(0, suffix=" tiles")
        self.play(count_to(n, 16), run_time=1.5)

    It is ONE shape whose outline is rebuilt from the text each frame (a stable identity, so manim's
    per-animation static/moving split never leaves stale digits behind, even inside a VGroup).
    """

    def __init__(self, value: float = 0, decimals: int = 0, prefix: str = "", suffix: str = "",
                 color: Optional[str] = None, font_size: float = 56, thousands: bool = True, **kw: Any) -> None:
        super().__init__(**kw)
        T = theme()
        self.tracker = ValueTracker(value)
        self.decimals = decimals
        self.prefix, self.suffix = prefix, suffix
        self.color_hex = T.color(color) if color else T.ink
        self.font_size = font_size
        self.thousands = thousands
        self._shown: Optional[str] = None
        self._draw(value, keep_left=False)
        self.set_fill(self.color_hex, opacity=1.0)
        self.set_stroke(width=0)
        backstroke(self)
        self.add_updater(lambda m: m._draw(m.tracker.get_value()))

    def _fmt(self, v: float) -> str:
        spec = "{:,.%df}" % self.decimals if self.thousands else "{:.%df}" % self.decimals
        return self.prefix + spec.format(v) + self.suffix

    def _baseline(self) -> Optional[float]:
        fr = getattr(self, "_st_metrics", None)
        if not fr or not self.has_points():
            return None
        return float(self.get_bottom()[1]) + fr[0] * float(self.height)

    def _draw(self, v: float, keep_left: bool = True) -> None:
        text = self._fmt(v)
        if text == self._shown:
            return
        T = theme()
        # a probe "Hx" in front gives the baseline, x-height and cap height (for mixed_line/align_baseline);
        # its glyphs are dropped, the number's glyphs are kept
        t = MarkupText('<span font_features="tnum">Hx%s</span>' % text, font=T.body, weight=T.display_weight,
                       font_size=self.font_size)
        glyphs = t.family_members_with_points()
        probe, rest = glyphs[:2], glyphs[2:]
        pts = [m.points for m in rest]
        keep = keep_left and self.has_points()
        left = self.get_left() if keep else None
        base = self._baseline() if keep else None
        center_y = self.get_center()[1] if keep else None
        self.set_points(np.concatenate(pts) if pts else np.zeros((0, 3)))
        if len(probe) == 2 and pts:
            ys = np.concatenate(pts)[:, 1]
            y0, h = float(ys.min()), float(ys.max() - ys.min()) or 1e-9
            H, x = probe
            b = (float(H.get_bottom()[1]) + float(x.get_bottom()[1])) / 2
            self._st_metrics = ((b - y0) / h, float(x.height) / h, float(H.height) / h, None)
            self._st_metrics_live = True
        if left is not None:
            # keep the left edge and the baseline (a comma or a new digit must not make the number jump)
            new_base = self._baseline()
            dy = (base - new_base) if (base is not None and new_base is not None) else center_y - self.get_center()[1]
            self.shift(np.array([left[0] - self.get_left()[0], dy, 0.0]))
        self._shown = text
        self._st_text = text  # type: ignore[attr-defined]

    def set_value(self, v: float) -> "Counter":
        self.tracker.set_value(v)
        self._draw(v)
        return self

    def get_value(self) -> float:
        return self.tracker.get_value()


def counter(value: float = 0, decimals: int = 0, **kw: Any) -> Counter:
    """A live number (see Counter)."""
    return Counter(value, decimals=decimals, **kw)


def count_to(num: Counter, value: float, rate_func: Any = smooth) -> Any:
    """Animation that ticks `num` to `value` (pair with run_time=1-2 s)."""
    return num.tracker.animate(rate_func=rate_func).set_value(value)

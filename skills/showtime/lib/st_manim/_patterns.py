"""Four patterns with the craft built in. Each takes the scene and plays its beats.

    equation_walkthrough(self, steps)          write once, then only morph; focus = dim others + box
    plane_transform(self, [[1, 1], [0, 1]])    ghost grid, oversize moving grid, coloured basis + matrix
    graph_build(self, f, x_range=(0, 4))       axes first, faint preview of the whole curve, glowing tip
    refine(self, build, ns=(4, 8, 16, 32))     an approximation that sharpens, faster each step
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from manim import (DOWN, LEFT, RIGHT, UP, UR, ApplyMatrix, Axes, Create, FadeIn, FadeOut, Matrix, NumberPlane,
                   ReplacementTransform, Transform, ValueTracker, Vector, VGroup, Write, always_redraw, linear,
                   smooth)

from ._fx import glow_dot, highlight
from ._layout import frame_size, place, region
from ._tex import Eq, dim_others, eq, morph, undim
from ._theme import theme
from ._type import backstroke, label, note

Step = Union[str, Dict[str, Any]]


def equation_walkthrough(scene: Any, steps: Sequence[Step], where: str = "center", colors: Optional[Dict[str, str]] = None,
                         hold: float = 1.0, arc_degrees: float = 40, write_time: float = 1.6,
                         morph_time: float = 1.6, font_size: Optional[float] = None) -> Eq:
    """Walk an equation through its steps. A step is a TeX string or a dict:
        {"tex": ..., "cue": "word" (wait for it first), "key_map": {"+": "-"}, "focus": "c^2" (dim the rest
         and box it), "note": "3 words max" (a note under the line), "hold": seconds}
    The first line is written; every later line only morphs, so symbols keep their identity.
    font_size: the equation's size (eq()'s default 72 when None); each line still fits `where`. Math is
    thin ink: at 72 on its own, a written or morphing line is too small a change for qa's frozen-frame
    detector, so a walkthrough that is the whole picture wants 100-120."""
    cur: Optional[Eq] = None
    dimmed = False
    extras: List[Any] = []
    for i, st in enumerate(steps):
        spec = {"tex": st} if isinstance(st, str) else dict(st)
        if spec.get("cue") is not None:
            scene.at(spec["cue"])
        nxt = eq(spec["tex"], colors=colors, **({"font_size": font_size} if font_size else {}))
        place(nxt, where)
        if extras:
            scene.play(*[FadeOut(x) for x in extras], run_time=0.4)
            extras = []
        if cur is None:
            scene.play(Write(nxt), run_time=write_time)
        else:
            if dimmed:
                scene.play(undim(cur))
                dimmed = False
            scene.play(morph(cur, nxt, key_map=spec.get("key_map"), arc=arc_degrees * np.pi / 180),
                       run_time=morph_time)
        cur = nxt
        if spec.get("focus"):
            box = highlight(cur[spec["focus"]])
            scene.play(dim_others(cur, [spec["focus"]]), Create(box), run_time=0.6)
            extras.append(box)
            dimmed = True
        if spec.get("note"):
            n = note(spec["note"]).next_to(cur, DOWN, buff=0.45)
            scene.play(FadeIn(n, shift=0.15 * UP), run_time=0.6)
            extras.append(n)
        scene.hold(spec.get("hold", hold))
    assert cur is not None
    if extras:
        scene.play(*[FadeOut(x) for x in extras], run_time=0.4)
    if dimmed:
        scene.play(undim(cur))
    return cur


def plane_transform(scene: Any, matrix: Sequence[Sequence[float]], run_time: float = 3.0, ghost: bool = True,
                    basis: bool = True, show_matrix: bool = True, hold: float = 2.0,
                    colors: Tuple[str, str] = ("hue1", "hue2")) -> VGroup:
    """A linear map shown on the plane: a faint static grid for "before", a moving grid twice the frame
    (its edges never show), basis vectors in two hues and the matrix with columns in the same hues."""
    T = theme()
    fw, fh = frame_size()
    span = max(fw, fh)
    c1, c2 = T.color(colors[0]) or T.hue(1), T.color(colors[1]) or T.hue(2)
    parts = VGroup()
    if ghost:
        g = NumberPlane(x_range=[-span, span, 1], y_range=[-span, span, 1],
                        background_line_style={"stroke_color": T.ghost, "stroke_width": 1.5, "stroke_opacity": 0.5},
                        axis_config={"stroke_color": T.ghost, "stroke_width": 1.5, "stroke_opacity": 0.5},
                        faded_line_ratio=1)
        g._st_bleed = True  # type: ignore[attr-defined]
        scene.add(g)
        parts.add(g)
    plane = NumberPlane(x_range=[-span * 2, span * 2, 1], y_range=[-span * 2, span * 2, 1],
                        background_line_style={"stroke_color": T.grid, "stroke_width": 2, "stroke_opacity": 0.9},
                        axis_config={"stroke_color": T.muted, "stroke_width": 2.5}, faded_line_ratio=2)
    plane.prepare_for_nonlinear_transform()
    plane._st_bleed = True  # type: ignore[attr-defined]
    scene.play(Create(plane, lag_ratio=0.02), run_time=1.2)
    parts.add(plane)
    vecs = VGroup()
    if basis:
        i_hat = Vector(RIGHT, color=c1, stroke_width=6)
        j_hat = Vector(UP, color=c2, stroke_width=6)
        vecs.add(i_hat, j_hat)
        scene.play(FadeIn(vecs), run_time=0.6)
    card = None
    if show_matrix:
        m = [[_num(v) for v in row] for row in matrix]
        card = Matrix(m, h_buff=1.1).scale(0.8)
        for k in range(2):
            for row in range(2):
                card.get_entries()[row * 2 + k].set_color(c1 if k == 0 else c2)
        backstroke(card, width=8)
        x0, y0, x1, y1 = region("full")
        card.move_to(np.array([x0, y1, 0]) + np.array([card.width / 2 + 0.1, -card.height / 2 - 0.1, 0]))
        scene.play(FadeIn(card, shift=0.2 * DOWN), run_time=0.8)
    mat = np.array(matrix, dtype=float)
    scene.play(ApplyMatrix(mat, plane), *[ApplyMatrix(mat, v) for v in vecs], run_time=run_time)
    scene.hold(hold)
    out = VGroup(parts, vecs)
    if card is not None:
        out.add(card)
    return out


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else "%g" % v


def graph_build(scene: Any, f: Callable[[float], float], x_range: Tuple[float, float] = (-3, 3),
                y_range: Optional[Tuple[float, float]] = None, axes: Optional[Axes] = None, color: Optional[str] = None,
                run_time: float = 3.0, preview: bool = True, dot: bool = True, linear_time: bool = True,
                where: str = "center", area: Union[bool, float] = False) -> Tuple[Axes, Any]:
    """Axes first (1 s), a faint preview of the whole curve, then the curve traced with a glowing tip.
    Use linear_time for a time axis (constant speed), smooth for "here is the shape".
    area=True (or an opacity) fills the area under the curve as it is traced: a thin curve alone changes
    too little of the frame for qa's frozen-frame detector over a long trace. The area stays on screen
    as `graph.st_area`."""
    T = theme()
    col = T.color(color) if color else T.hue(1)
    if axes is None:
        xs = np.linspace(x_range[0], x_range[1], 200)
        ys = [f(x) for x in xs]
        if y_range is None:
            lo, hi = float(min(ys)), float(max(ys))
            pad = (hi - lo) * 0.15 or 1.0
            y_range = (lo - pad, hi + pad)
        x0, y0, x1, y1 = region(where)
        axes = Axes(x_range=[x_range[0], x_range[1], max(1, (x_range[1] - x_range[0]) / 6)],
                    y_range=[y_range[0], y_range[1], max(0.5, (y_range[1] - y_range[0]) / 5)],
                    x_length=(x1 - x0) * 0.9, y_length=(y1 - y0) * 0.9, tips=False,
                    axis_config={"stroke_color": T.muted, "stroke_width": T.stroke["construct"]})
        axes.move_to(np.array([(x0 + x1) / 2, (y0 + y1) / 2, 0]))
        scene.play(Create(axes), run_time=1.0)
    graph = axes.plot(f, x_range=[x_range[0], x_range[1]], color=col, stroke_width=T.stroke["data"])
    if preview:
        pv = graph.copy().set_stroke(opacity=0.28)
        scene.play(FadeIn(pv), run_time=0.6)
    fill = None
    if area:
        op = 0.3 if area is True else float(area)
        x_lo = float(x_range[0])

        def swept() -> Any:
            x_tip = float(axes.p2c(graph.get_end())[0]) if graph.has_points() else x_lo
            return axes.get_area(graph, x_range=[x_lo, max(x_tip, x_lo + 1e-3)], color=col, opacity=op,
                                 stroke_width=0)
        fill = always_redraw(swept)
        scene.add(fill)
    if dot:
        tip = always_redraw(lambda: glow_dot(graph.get_end(), color=col, radius=0.26, layers=8))
        scene.add(tip)
    scene.play(Create(graph, rate_func=linear if linear_time else smooth), run_time=run_time)
    if fill is not None:
        scene.remove(fill)
        still = axes.get_area(graph, x_range=[float(x_range[0]), float(x_range[1])], color=col, opacity=op,
                              stroke_width=0)
        scene.add(still)
        scene.bring_to_front(graph)
        graph.st_area = still  # type: ignore[attr-defined]
    if dot:
        scene.remove(tip)
        final = glow_dot(graph.get_end(), color=col, radius=0.26, layers=8)
        scene.add(final)
    return axes, graph


def refine(scene: Any, build: Callable[[int], Any], ns: Sequence[int] = (4, 8, 16, 32),
           run_times: Sequence[float] = (2.0, 1.5, 1.0, 0.7), show_n: bool = True, where: str = "center",
           hold: float = 0.6, start: Any = None, tag: Any = "n = %d") -> Any:
    """An approximation that sharpens: build(n) -> mobject for each n, each step replacing the last,
    faster each time so the limit feels inevitable.

    start: a mobject already on screen; the first step transforms it into build(ns[0]) instead of
    fading that in (continue a ladder from where the picture is, e.g. across two narration lines).
    tag: the step label: a %-format string ("N = %d", placed top right), a callable n -> mobject that
    you place yourself, or None for no label (show_n=False does the same)."""
    def make_tag(n: int) -> Any:
        return tag(n) if callable(tag) else label(str(tag) % n)

    use_tag = show_n and tag is not None and tag is not False
    cur = build(ns[0])
    tg = make_tag(ns[0]) if use_tag else None
    if tg is not None and not callable(tag):
        place(tg, "top", align="right")
    first_anims = [FadeIn(cur) if start is None else ReplacementTransform(start, cur)]
    if tg is not None:
        first_anims.append(FadeIn(tg))
    scene.play(*first_anims, run_time=run_times[0] if run_times else 1.5)
    scene.hold(hold)
    for i, n in enumerate(ns[1:], 1):
        nxt = build(n)
        rt = run_times[min(i, len(run_times) - 1)] if run_times else 1.0
        anims = [ReplacementTransform(cur, nxt)]
        if tg is not None:
            nt = make_tag(n)
            if not callable(tag):
                nt.move_to(tg, aligned_edge=RIGHT)
            anims.append(Transform(tg, nt))
        scene.play(*anims, run_time=rt)
        scene.hold(hold)
        cur = nxt
    return cur

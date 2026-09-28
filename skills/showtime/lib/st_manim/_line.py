"""One line of mixed type: words and math (or numbers) on one baseline, at one x-height.

    q = mixed_line("Why", tex(r"\\pi r^2"), "?", size=88)       # a title-tier question
    a = mixed_line("Area =", tex(r"\\pi r^2"), tier="callout")
    g = VGroup(label("rings"), n).arrange(RIGHT); align_baseline(g[0], n)   # n moves onto the label's baseline

Why a helper: Text (Pango, the theme fonts) and MathTex (LaTeX, Computer Modern) come from two
engines with different metrics, and each is centred on its own bounding box. `arrange(RIGHT)` centres
the boxes and `aligned_edge=DOWN` lines up their lowest points, so a descender ("y", "g"), a
superscript or a fraction drags a part off the baseline. And Computer Modern's x-height (0.43 em) is
smaller than most sans fonts' (0.5-0.55 em), so math at the "same" size reads a size smaller.

How it measures: each part is rebuilt once with a probe "Hx" in front (same font, weight and size; for
TeX, \\mathrm{Hx} in the same template), and the probe's glyphs give the baseline (the flat feet of H
and x), the cap height (H) and the x-height (x). Descenders and scripts never move the baseline.
The result is kept as fractions of the part's box, so it survives scaling and moving.

Weight: bold display type beside regular Computer Modern reads as two weights. mixed_line() sets the
math in \\boldsymbol (CM bold math italic) when the text is SEMIBOLD or heavier. That matches 600-700
text but is still lighter than an 800-900 display weight, so for ULTRABOLD/HEAVY text it also adds an
outline in the fill colour 6 % of the x-height wide (`thicken=`, a fraction of the x-height; 0 turns
it off). The outline closes small counters (the loop of a "2", the eye of an "e") as it grows: keep
it at 0.08 or less and look at a full-size frame.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from manim import MarkupText, MathTex, SingleStringMathTex, Tex, Text, VGroup, VMobject

from ._theme import theme
from ._type import SIZES, backstroke, tier_font, tier_text

HEAVY = {"SEMIBOLD", "BOLD", "ULTRABOLD", "HEAVY"}         # math in \\boldsymbol beside these
HEAVIEST = {"ULTRABOLD", "HEAVY"}                          # ... and thickened by THICKEN
THICKEN = 0.06            # outline width for math beside 800-900 text, in x-heights
OPENERS = "([{“‘¿¡$"
CLOSERS = ".,;:!?)]}%”’…"
WORD_GAP = 0.5            # word space, in x-heights of the reference text
TIGHT_GAP = 0.12          # before closing punctuation / after an opening one
MATH_TIGHT_GAP = 0.3      # the same next to math (italic overhang and scripts need more room)

Metrics = Dict[str, float]


# ------------------------------------------------------------------ measuring

def _box(m: VMobject) -> Tuple[float, float]:
    return float(m.get_bottom()[1]), float(m.height)


def _fractions(probe: VMobject, first: int, rest: Sequence[VMobject]) -> Optional[Tuple[float, float, float]]:
    """(baseline, x-height, cap height) as fractions of the height of `rest`, from the probe glyphs
    H (index first) and x (first + 1), measured from the bottom of `rest`."""
    if not rest:
        return None
    glyphs = [g for g in probe.family_members_with_points()]
    if len(glyphs) < first + 2:
        return None
    H, x = glyphs[first], glyphs[first + 1]
    pts = np.concatenate([g.points for r in rest for g in r.family_members_with_points()] or [np.zeros((0, 3))])
    if not len(pts):
        return None
    y0, y1 = float(pts[:, 1].min()), float(pts[:, 1].max())
    h = y1 - y0
    if h <= 1e-9:
        return None
    base = (float(H.get_bottom()[1]) + float(x.get_bottom()[1])) / 2
    return (base - y0) / h, float(x.height) / h, float(H.height) / h


def _probe_text(m: Any) -> Optional[Tuple[float, float, float]]:
    src = getattr(m, "original_text", None) or getattr(m, "text", None)
    if not src or "\n" in str(src):
        return None
    kw = dict(font=getattr(m, "font", "") or "", slant=getattr(m, "slant", "NORMAL"),
              weight=getattr(m, "weight", "NORMAL"), font_size=getattr(m, "_font_size", 48.0))
    try:
        if isinstance(m, MarkupText):
            p = MarkupText("Hx" + str(src), **kw)
        else:
            p = Text("Hx" + str(src), **kw)
    except Exception:  # noqa: BLE001 - an unusual text is simply not measured
        return None
    return _fractions(p, 0, p.submobjects[2:])


def _probe_tex(m: Any) -> Optional[Tuple[float, float, float]]:
    strings = list(getattr(m, "tex_strings", None) or [getattr(m, "tex_string", "")])
    if not any(s.strip() for s in strings):
        return None
    text_mode = isinstance(m, Tex)
    head = "Hx" if text_mode else r"\mathrm{Hx}"
    if getattr(m, "st_bold", False):
        head = r"\boldsymbol{%s}" % head
    kw: Dict[str, Any] = {}
    for a in ("tex_template", "tex_environment", "arg_separator"):
        if getattr(m, a, None) is not None:
            kw[a] = getattr(m, a)
    try:
        p = (Tex if text_mode else MathTex)(head, *strings, **kw)
    except Exception:  # noqa: BLE001
        return None
    return _fractions(p, 0, p.submobjects[1:])


def _signature(m: VMobject) -> Tuple[int, float]:
    n = sum(len(g.points) for g in m.family_members_with_points())
    return n, round(float(m.width) / max(float(m.height), 1e-9), 3)


def line_metrics(m: VMobject) -> Optional[Metrics]:
    """{"baseline", "x_height", "cap_height", "bottom", "top"} of one text, math or counter part, in scene
    units, measured from its glyphs (see the module doc). None for anything else."""
    if not isinstance(m, VMobject) or not m.has_points() and not m.family_members_with_points():
        return None
    sig = _signature(m)
    cached = getattr(m, "_st_metrics", None)
    fr: Optional[Tuple[float, float, float]] = None
    if cached and (cached[3] == sig or getattr(m, "_st_metrics_live", False)):
        fr = cached[:3]
    else:
        if isinstance(m, (Text, MarkupText)):
            fr = _probe_text(m)
        elif isinstance(m, SingleStringMathTex):      # MathTex, Tex, Eq and single strings
            fr = _probe_tex(m)
        if fr is None:
            return None
        m._st_metrics = (fr[0], fr[1], fr[2], sig)  # type: ignore[attr-defined]
    bottom, h = _box(m)
    return {"baseline": bottom + fr[0] * h, "x_height": fr[1] * h, "cap_height": fr[2] * h,
            "bottom": bottom, "top": bottom + h}


def baseline(m: VMobject) -> float:
    """y of the baseline of a text, math or counter part."""
    lm = line_metrics(m)
    if lm is None:
        raise TypeError("baseline(): %s is not Text, MarkupText, MathTex/Tex/eq() or counter()" % type(m).__name__)
    return lm["baseline"]


def x_height(m: VMobject) -> float:
    lm = line_metrics(m)
    if lm is None:
        raise TypeError("x_height(): %s is not Text, MarkupText, MathTex/Tex/eq() or counter()" % type(m).__name__)
    return lm["x_height"]


def align_baseline(a: VMobject, *others: VMobject) -> Any:
    """Move each of `others` up or down so it sits on `a`'s baseline (x is kept). Returns the one
    moved part, or a VGroup of them."""
    y = baseline(a)
    for b in others:
        b.shift(np.array([0.0, y - baseline(b), 0.0]))
        b._st_aligned = True  # type: ignore[attr-defined]
    a._st_aligned = True  # type: ignore[attr-defined]
    return others[0] if len(others) == 1 else VGroup(*others)


# ------------------------------------------------------------------ building a line

class TexPart:
    """A math part for mixed_line() (made by tex()); it becomes an eq() sized to the line."""

    def __init__(self, tex: str, colors: Optional[Dict[str, str]] = None, isolate: Sequence[str] = (),
                 bold: Optional[bool] = None, color: Optional[str] = None, **kw: Any) -> None:
        self.tex, self.colors, self.isolate, self.bold, self.color, self.kw = tex, colors, isolate, bold, color, kw

    def build(self, bold: bool) -> VMobject:
        from ._tex import eq
        b = self.bold if self.bold is not None else bold
        kw = dict(self.kw)
        if self.color is not None:
            kw["color"] = theme().color(self.color) or self.color
        return eq(self.tex, colors=self.colors, isolate=self.isolate, bold=b, **kw)

    def __repr__(self) -> str:  # pragma: no cover
        return "tex(%r)" % self.tex


def tex(tex: str, colors: Optional[Dict[str, str]] = None, isolate: Sequence[str] = (), bold: Optional[bool] = None,
        color: Optional[str] = None, **kw: Any) -> TexPart:
    """A math part for mixed_line(): mixed_line("Why", tex(r"\\pi r^2"), "?"). Concept colours come from
    manim.json as in eq(). For an equation on its own line use eq()."""
    return TexPart(tex, colors=colors, isolate=isolate, bold=bold, color=color, **kw)


class MixedLine(VGroup):
    """The parts of a mixed_line(), in order (line[1] is the second part), on one baseline."""

    def baseline(self) -> float:
        return baseline(self.st_ref)  # type: ignore[attr-defined]

    def scale(self, scale_factor: float, **kw: Any) -> "MixedLine":
        super().scale(scale_factor, **kw)
        if getattr(self, "st_thicken", 0):          # the math outline keeps its share of the x-height
            _thicken([m for m in self.submobjects if _is_math(m)], self.st_thicken, x_height(self.st_ref))
        return self


def _thicken(mobs: Sequence[VMobject], frac: float, xh: float) -> None:
    """Outline math glyphs in their own fill colour, `frac` x-heights wide (manim width 1 = 0.01 units)."""
    width = float(frac) * xh / 0.01
    for m in mobs:
        for g in m.family_members_with_points():
            g.set_stroke(g.get_fill_color(), width=width, opacity=g.get_fill_opacity())


def _is_math(m: Any) -> bool:
    return isinstance(m, SingleStringMathTex)


def mixed_line(*parts: Union[str, TexPart, VMobject], tier: str = "title", size: Optional[float] = None,
               color: Optional[str] = None, match: str = "x", bold: Optional[bool] = None,
               thicken: Optional[float] = None, gap: Optional[Union[float, Sequence[float]]] = None) -> MixedLine:
    """Words and math on one line: strings become text in `tier` (title | callout | label | note, at
    `size`), tex() parts become equations, other mobjects are used as they are.

    Every math part is scaled so its x-height equals the text's (match="cap": cap heights instead, for
    math that is mostly capitals and digits), and every part sits on the first text's baseline.
    bold=None sets math in \\boldsymbol when the tier's weight is SEMIBOLD or heavier; thicken (a fraction
    of the x-height, default 0.06 beside ULTRABOLD/HEAVY text, else 0) outlines math in its fill colour.
    gap: space between parts in scene units (one value or one per joint); the default is a word space,
    tight before closing and after opening punctuation. Size the line with `size`; line.scale() keeps
    the outline in proportion. line.baseline() is the shared baseline."""
    if not parts:
        raise ValueError("mixed_line(): give at least one part")
    if match not in ("x", "cap"):
        raise ValueError("mixed_line(match=%r): use 'x' or 'cap'" % match)
    T = theme()
    _, weight = tier_font(tier)
    bold_math = (str(weight).upper() in HEAVY) if bold is None else bool(bold)
    if thicken is None:
        thicken = THICKEN if (bold is None and str(weight).upper() in HEAVIEST) else 0.0
    mobs: List[VMobject] = []
    texts: List[Optional[str]] = []
    for p in parts:
        if isinstance(p, str):
            s = p.strip()
            if not s:
                continue
            mobs.append(tier_text(s, tier, color, size))
            texts.append(p)
        elif isinstance(p, TexPart):
            if p.color is None and color is not None and not p.colors:
                p.color = color
            m = p.build(bold_math)
            backstroke(m)
            mobs.append(m)
            texts.append(None)
        elif isinstance(p, VMobject):
            mobs.append(p)
            texts.append(None)
        else:
            raise TypeError("mixed_line(): parts are strings, tex(...) or mobjects, not %s" % type(p).__name__)
    ref = next((m for m in mobs if not _is_math(m) and line_metrics(m) is not None), None)
    if ref is None:
        ref = next((m for m in mobs if line_metrics(m) is not None), None)
    if ref is None:
        raise ValueError("mixed_line(): no part could be measured (use strings, tex(), Text, eq() or counter())")
    rm = line_metrics(ref)
    assert rm is not None
    key = "x_height" if match == "x" else "cap_height"
    for m in mobs:
        if m is ref or not _is_math(m):
            continue
        mm = line_metrics(m)
        if mm and mm[key] > 1e-9:
            m.scale(rm[key] / mm[key])
        if thicken > 0:
            _thicken([m], thicken, rm["x_height"])
            backstroke(m)
    xh = rm["x_height"]
    gaps: List[float] = []
    for i in range(1, len(mobs)):
        if gap is not None:
            gaps.append(float(gap[i - 1]) if isinstance(gap, (list, tuple)) else float(gap))
            continue
        prev, cur = texts[i - 1], texts[i]        # explicit spaces around a string always mean a word space
        tight = (cur is not None and cur[:1] in CLOSERS) or (prev is not None and prev[-1:] in OPENERS)
        near_math = _is_math(mobs[i - 1]) or _is_math(mobs[i])
        gaps.append(((MATH_TIGHT_GAP if near_math else TIGHT_GAP) if tight else WORD_GAP) * xh)
    y = rm["baseline"]
    x = float(mobs[0].get_right()[0])
    for i, m in enumerate(mobs[1:], start=1):
        m.shift(np.array([x + gaps[i - 1] - float(m.get_left()[0]), 0.0, 0.0]))
        x = float(m.get_right()[0])
    for m in mobs:
        m.shift(np.array([0.0, y - baseline(m), 0.0]))
        m._st_aligned = True  # type: ignore[attr-defined]
    line = MixedLine(*mobs)
    line.st_ref = ref  # type: ignore[attr-defined]
    line._st_line = True  # type: ignore[attr-defined]
    line.st_thicken = float(thicken)  # type: ignore[attr-defined]
    line.move_to(np.zeros(3))
    return line


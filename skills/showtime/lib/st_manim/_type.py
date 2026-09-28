"""On-screen words: three type tiers plus a callout, each with a word budget and a backstroke.

Narration carries the sentences; the screen carries labels. Budgets (checked by `showtime manim
check`): title 4 words, label 3, callout 8, note 8. Every tier gets a backstroke in the background
colour, so it stays legible over grids and curves without a box.

Words and math on ONE line ("Why pi r^2?", "Area = pi r^2", "rings 8") go through `mixed_line()` or
`align_baseline()` (see _line.py): Text and MathTex are drawn by two engines with different metrics.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple

from manim import MarkupText, Text, VMobject

from ._theme import theme

# font_size at the kit's 8-unit short side (manim's default Text size is 48)
SIZES = {"title": 64, "callout": 42, "label": 34, "note": 26}
BUDGETS = {"title": 4, "label": 3, "callout": 8, "note": 8, None: 8}


def words_of(text: str) -> int:
    return len([w for w in str(text).split() if any(ch.isalnum() for ch in w)])


def backstroke(mob: VMobject, width: Optional[float] = None, color: Optional[str] = None) -> VMobject:
    """A stroke drawn behind the fill in the background colour (not black), for legibility over graphics."""
    T = theme()
    mob.set_stroke(color or T.bg, width=T.stroke["back"] if width is None else width, background=True)
    return mob


def _text(text: str, tier: str, color: Optional[str], font: str, weight: str, size: Optional[float],
          **kw: Any) -> Text:
    T = theme()
    if color is not None:
        color = T.color(color) or color
    t = Text(str(text), font=font, weight=weight, font_size=size or SIZES[tier], color=color or T.ink, **kw)
    backstroke(t)
    t._st_tier = tier  # type: ignore[attr-defined]
    t._st_text = str(text)  # type: ignore[attr-defined]
    return t


def tier_font(tier: str) -> Tuple[str, str]:
    """(font family, Pango weight) of a type tier: title | callout | label | note."""
    T = theme()
    if tier == "title":
        return T.display, T.display_weight
    if tier == "callout":
        return T.body, "MEDIUM" if T.body_weight == "NORMAL" else T.body_weight
    if tier in SIZES:
        return T.body, T.body_weight
    raise KeyError("unknown type tier %r; use one of: %s" % (tier, ", ".join(SIZES)))


def tier_text(text: str, tier: str = "title", color: Optional[str] = None, size: Optional[float] = None,
              **kw: Any) -> Text:
    """Text in a tier's font, weight and size (title() etc. by name)."""
    font, weight = tier_font(tier)
    if tier == "note" and color is None:
        color = theme().muted
    return _text(text, tier, color, font, weight, size, **kw)


def title(text: str, color: Optional[str] = None, size: Optional[float] = None, **kw: Any) -> Text:
    """Headline in the display font. Budget: 4 words."""
    return tier_text(text, "title", color, size, **kw)


def callout(text: str, color: Optional[str] = None, size: Optional[float] = None, **kw: Any) -> Text:
    """One short line (a question, a takeaway). Budget: 8 words."""
    return tier_text(text, "callout", color, size, **kw)


def label(text: str, color: Optional[str] = None, size: Optional[float] = None, **kw: Any) -> Text:
    """A name next to the thing it names. Budget: 3 words."""
    return tier_text(text, "label", color, size, **kw)


def note(text: str, color: Optional[str] = None, size: Optional[float] = None, **kw: Any) -> Text:
    """Small annotation, muted by default. Budget: 8 words."""
    return tier_text(text, "note", color, size, **kw)


def markup(text: str, tier: str = "callout", color: Optional[str] = None, **kw: Any) -> MarkupText:
    """Pango markup (<b>, <span foreground=...>) in a tier's size and the body font."""
    T = theme()
    t = MarkupText(text, font=T.body, font_size=SIZES.get(tier, 42), color=T.color(color) if color else T.ink, **kw)
    backstroke(t)
    t._st_tier = tier  # type: ignore[attr-defined]
    return t

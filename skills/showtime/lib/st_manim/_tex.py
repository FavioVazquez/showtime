"""Colour-coded equations that split themselves into parts, and a matching-part morph.

Manim Community matches equation parts by their TeX string, so every term you want to move,
colour or point at must be its own part. `eq()` does that split for you: it tokenises the TeX at
the top level (a variable with its scripts, a number, an operator, a command with its brace
arguments, a whole \\left...\\right group) and merges the tokens that spell a declared concept
("2n-1", "n^2") into one part. Each concept gets its colour from manim.json "colors" (or
`colors=`), everywhere, so a symbol keeps one colour for the whole video.

    e = eq(r"1 + 3 + 5 = 3^2", colors={"3^2": "emph"})
    e["3^2"]            # that part (a VGroup); e.part("+", 2) is the second "+"
    self.play(morph(e, eq(r"3^2 = 9")))     # same parts glide, crossing "=" on an arc

Terms inside \\frac{..}{..} or \\sqrt{..} stay inside their command's part (split the equation
differently, or morph the whole fraction).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from manim import (DEGREES, AnimationGroup, FadeIn, FadeOut, MathTex, Transform, VGroup, VMobject)

from ._theme import theme

RELATIONS = {"=", "<", ">", r"\le", r"\ge", r"\leq", r"\geq", r"\neq", r"\approx", r"\equiv", r"\to", r"\sim",
             r"\propto", r"\Rightarrow", r"\iff"}
SPACING = {",", ";", "!", ":", " ", "quad", "qquad"}


# ------------------------------------------------------------------ tokenizer

def _brace_end(s: str, i: int, open_ch: str = "{", close_ch: str = "}") -> int:
    """Index just past the group that opens at s[i]."""
    depth = 0
    j = i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    raise ValueError("unbalanced %s%s in %r" % (open_ch, close_ch, s))


def _skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i].isspace():
        i += 1
    return i


def _script(s: str, i: int) -> int:
    """Consume any ^/_ scripts (and primes) that follow position i."""
    while True:
        j = _skip_ws(s, i)
        if j < len(s) and s[j] == "'":
            i = j + 1
            continue
        if j < len(s) and s[j] in "^_":
            k = _skip_ws(s, j + 1)
            if k < len(s) and s[k] == "{":
                i = _brace_end(s, k)
            elif k < len(s) and s[k] == "\\":
                m = re.match(r"\\([A-Za-z]+|.)", s[k:])
                i = k + (len(m.group(0)) if m else 1)
            else:
                i = k + 1
            continue
        return i


def tokens(tex: str) -> List[str]:
    """Top-level atoms of a TeX math string (see the module doc)."""
    s = tex
    out: List[str] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i].isspace():
            i += 1
            continue
        start = i
        c = s[i]
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+|.)", s[i:])
            name = m.group(1) if m else c
            i += len(m.group(0)) if m else 1
            if name == "left":
                depth = 1
                while i < n and depth:
                    m2 = re.search(r"\\(left|right)(?![A-Za-z])", s[i:])
                    if not m2:
                        i = n
                        break
                    depth += 1 if m2.group(1) == "left" else -1
                    i += m2.end()
                i = min(n, i + (2 if i < n and s[i] == "\\" else 1))   # the closing delimiter
                i = _script(s, i)
            elif name in SPACING:
                pass
            else:
                while True:
                    j = _skip_ws(s, i)
                    if j < n and s[j] == "{":
                        i = _brace_end(s, j)
                    elif j < n and s[j] == "[" and name in ("sqrt",):
                        i = _brace_end(s, j, "[", "]")
                    else:
                        break
                i = _script(s, i)
        elif c == "{":
            i = _script(s, _brace_end(s, i))
        elif c.isdigit() or (c == "." and i + 1 < n and s[i + 1].isdigit()):
            m = re.match(r"\d*\.?\d+", s[i:])
            i += len(m.group(0)) if m else 1
            i = _script(s, i)
        elif c.isalpha():
            i = _script(s, i + 1)
        elif c in "^_":
            i = _script(s, i)
        else:
            i += 1
            if c in ")]|!":
                i = _script(s, i)
        tok = re.sub(r"\s+", " ", s[start:i]).strip()
        if tok:
            out.append(tok)
    return out


def _norm(t: str) -> str:
    return re.sub(r"\s+", "", t)


def _base(tok: str) -> str:
    """'a^2' -> 'a', 'x_{n+1}' -> 'x', '\\alpha^2' -> '\\alpha'."""
    m = re.match(r"(\\[A-Za-z]+|[A-Za-z0-9.]+|\{.*\})", tok)
    return m.group(1) if m else tok


def split(tex: str, keys: Iterable[str] = ()) -> Tuple[List[str], List[Optional[str]]]:
    """(parts, key per part): top-level tokens with each key's token run merged into one part."""
    toks = tokens(tex)
    key_toks = []
    for k in keys:
        try:
            kt = [_norm(t) for t in tokens(k)]
        except ValueError:
            continue
        if kt:
            key_toks.append((k, kt))
    key_toks.sort(key=lambda kv: -len(kv[1]))
    parts: List[str] = []
    pkeys: List[Optional[str]] = []
    i = 0
    normed = [_norm(t) for t in toks]
    while i < len(toks):
        for k, kt in key_toks:
            if normed[i:i + len(kt)] == kt:
                parts.append(" ".join(toks[i:i + len(kt)]))
                pkeys.append(k)
                i += len(kt)
                break
        else:
            parts.append(toks[i])
            pkeys.append(None)
            i += 1
    return parts, pkeys


# ------------------------------------------------------------------ Eq

class Eq(MathTex):
    """A MathTex split into addressable parts: e["x^2"], e.part("+", 2), e.keys."""

    def __init__(self, tex: str, colors: Optional[Dict[str, str]] = None, isolate: Sequence[str] = (),
                 color: Optional[str] = None, bold: bool = False, **kw: Any) -> None:
        T = theme()
        cmap: Dict[str, str] = dict(T.colors)
        for k, v in (colors or {}).items():
            cmap[k] = T.color(v) or v
        keys = list(cmap) + list(isolate)
        parts, pkeys = split(tex, keys)
        if not parts:
            raise ValueError("eq(): empty TeX")
        self.st_tex = tex
        self.st_bold = bool(bold)
        kw.setdefault("font_size", 72)
        # bold: every part in \boldsymbol (Computer Modern bold math italic); keys stay the plain TeX
        tex_parts = [r"\boldsymbol{%s}" % p for p in parts] if bold else parts
        super().__init__(*tex_parts, color=color or T.ink, **kw)
        self.keys: List[str] = [pk or _norm(p) for p, pk in zip(parts, pkeys)]
        self.st_colors: Dict[str, str] = {}
        for sub, p, pk in zip(self.submobjects, parts, pkeys):
            col = cmap.get(pk) if pk else (cmap.get(_norm(p)) or cmap.get(_base(p)))
            if col:
                sub.set_color(col)
                self.st_colors[pk or _norm(p)] = col

    def part(self, key: str, occurrence: int = 1) -> VMobject:
        k = _norm(key)
        seen = 0
        for sub, sk in zip(self.submobjects, self.keys):
            if _norm(sk) == k:
                seen += 1
                if seen == occurrence:
                    return sub
        raise KeyError("eq %r has no part %r (#%d); parts: %s" % (self.st_tex, key, occurrence,
                                                                 ", ".join(self.keys)))

    def parts(self, key: str) -> VGroup:
        k = _norm(key)
        return VGroup(*[s for s, sk in zip(self.submobjects, self.keys) if _norm(sk) == k])

    def __getitem__(self, value: Any) -> Any:
        if isinstance(value, str):
            m = re.match(r"^(.*)#(\d+)$", value)
            if m:
                return self.part(m.group(1), int(m.group(2)))
            return self.part(value)
        return super().__getitem__(value)


def eq(tex: str, colors: Optional[Dict[str, str]] = None, isolate: Sequence[str] = (), bold: bool = False,
       **kw: Any) -> Eq:
    """Colour-coded equation split into parts (see the module doc). bold=True sets it in \\boldsymbol."""
    return Eq(tex, colors=colors, isolate=isolate, bold=bold, **kw)


def _keys_of(m: VMobject) -> List[str]:
    """Part keys with whitespace removed, so a declared key "\\pi r" matches a key_map entry "\\pi r"."""
    if isinstance(m, Eq):
        return [_norm(k) for k in m.keys]
    return [_norm(getattr(s, "tex_string", "") or str(i)) for i, s in enumerate(m.submobjects)]


def _relation_x(m: VMobject, keys: List[str]) -> Optional[float]:
    for sub, k in zip(m.submobjects, keys):
        if k in RELATIONS or k in {_norm(r) for r in RELATIONS}:
            return float(sub.get_center()[0])
    return None


class Morph(AnimationGroup):
    """Matching-part transform from equation `a` to equation `b` (see morph())."""

    def __init__(self, a: VMobject, b: VMobject, key_map: Optional[Dict[str, str]] = None,
                 arc: float = 40 * DEGREES, **kw: Any) -> None:
        ka, kb = _keys_of(a), _keys_of(b)
        kmap = {_norm(k): _norm(v) for k, v in (key_map or {}).items()}
        ra, rb = _relation_x(a, ka), _relation_x(b, kb)
        used: set = set()
        anims = []
        extra = []
        unmatched_a = []
        for sa, k in zip(a.submobjects, ka):
            want = kmap.get(k, k)
            j = next((j for j, kk in enumerate(kb) if kk == want and j not in used), None)
            if j is None:
                unmatched_a.append(sa)
                continue
            used.add(j)
            sb = b.submobjects[j]
            crosses = ra is not None and rb is not None and \
                (sa.get_center()[0] - ra) * (sb.get_center()[0] - rb) < 0 and k not in RELATIONS
            anims.append(Transform(sa, sb.copy(), path_arc=arc if crosses else 0))
        new_parts = [b.submobjects[j] for j in range(len(kb)) if j not in used]
        toward = VGroup(*new_parts).get_center() if new_parts else b.get_center()
        for sa in unmatched_a:
            d = toward - sa.get_center()
            anims.append(FadeOut(sa, shift=0.25 * d / (np.linalg.norm(d) or 1)))
        for sb in new_parts:
            c = sb.copy()
            extra.append(c)
            src = VGroup(*unmatched_a).get_center() if unmatched_a else a.get_center()
            d = sb.get_center() - src
            anims.append(FadeIn(c, shift=0.25 * d / (np.linalg.norm(d) or 1)))
        kw.setdefault("run_time", 1.6)
        super().__init__(*anims, **kw)
        self._st_remove = [a] + list(a.submobjects) + extra
        self._st_add = b

    def clean_up_from_scene(self, scene: Any) -> None:
        super().clean_up_from_scene(scene)
        for anim in self.animations:
            anim.interpolate(0)
        scene.remove(self.mobject)
        scene.remove(*self._st_remove)
        scene.add(self._st_add)


def morph(a: VMobject, b: VMobject, key_map: Optional[Dict[str, str]] = None, arc: float = 40 * DEGREES,
          **kw: Any) -> Morph:
    """Same parts move to their new places (terms crossing the relation travel on an `arc`), parts that
    leave fade toward the new ones, new parts fade in. key_map={"+": "-"} turns one part into another.
    Place `b` where it should end before calling (e.g. b.move_to(a))."""
    return Morph(a, b, key_map=key_map, arc=arc, **kw)


def dim_others(m: VMobject, keep: Sequence[Any], to: float = 0.35) -> AnimationGroup:
    """Fade every part of `m` except `keep` (parts or keys) to `to` opacity. Undo with undim(m)."""
    keep_mobs = []
    for k in keep:
        if isinstance(k, str) and isinstance(m, Eq):
            keep_mobs.extend(list(m.parts(k)))
        else:
            keep_mobs.append(k)
    anims = [s.animate.set_opacity(to) for s in m.submobjects if s not in keep_mobs]
    return AnimationGroup(*anims, run_time=0.6)


def undim(m: VMobject) -> AnimationGroup:
    return AnimationGroup(*[s.animate.set_opacity(1) for s in m.submobjects], run_time=0.6)


def stack(*eqs: VMobject, gap: float = 0.5) -> VGroup:
    """Derivation lines one under another, aligned on their first relation sign."""
    g = VGroup(*eqs).arrange(np.array([0.0, -1.0, 0.0]), buff=gap)
    xs = [_relation_x(e, _keys_of(e)) for e in eqs]
    if all(x is not None for x in xs):
        x0 = xs[0]
        for e, x in zip(eqs, xs):
            e.shift(np.array([x0 - x, 0.0, 0.0]))  # type: ignore[operator]
    return g

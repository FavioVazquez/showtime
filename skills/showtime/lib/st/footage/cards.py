"""Cards for a talking head: designed overlays that appear when the words are said.

An EDL's `cards` list (references/editing.md, "Cards") holds a title, a lower third, a pull-quote, a data
callout, a chapter card, a list that builds point by point, a side panel, or a big word behind the speaker
(`behind`: the speaker is cut out over it; st.footage.behind). Each card is anchored to the transcript, never
to seconds:

    {"type": "stat", "say": "twenty two thousand miles", "value": 22000, "suffix": " miles",
     "label": "above Earth"}

- `say` is a phrase: its first match after the previous card's anchor (case, punctuation, "%" and number
  words do not matter: "twenty two thousand" matches "22,000"); it may span a cut. `word` is a transcript
  word id instead (`"w57"` or 57; `source` picks the take when there are several).
- `lead` (s before the first word, default 0.12), then `hold` (s after the anchor's last word), `until` (a
  later phrase: the card ends after it) or `dur` (s). Times resolve through the EDL's frame-exact output
  mapping (edl.map_words), so a re-cut moves every card with its words.

`resolve` turns the specs into output-timeline cards with a layout box; `problems` lists what `edit check`
reports (overlaps, the caption band, the safe box, reading time); `page` writes the card reel (one DOM page,
cards back to back) that `render_reel` renders once with alpha (QuickTime Animation) and caches; the EDL
renderer composites each card as an overlay (`overlays_for`) under the captions. A `panel` also changes the
base framing: `panel_splits` cuts the ranges at the panel's frames so the speaker is framed into one half
(render_edl._video_graph, `layout`).
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..common import ShowtimeError, debug, ensure_dir, info, read_json, write_json

TYPES = ("title", "lower-third", "quote", "stat", "chapter", "list", "panel", "behind")
ALIASES = {"lower_third": "lower-third", "lowerthird": "lower-third", "name": "lower-third", "pull-quote": "quote",
           "pullquote": "quote", "data": "stat", "number": "stat", "callout": "stat", "steps": "list",
           "side-panel": "panel", "split": "panel", "text-behind": "behind", "behind-text": "behind",
           "word-behind": "behind"}
# what each type needs, and its default hold (s after the anchor's last word) and shortest life
NEEDS = {"title": ("title",), "lower-third": ("name",), "quote": (), "stat": (), "chapter": ("title",),
         "list": ("items",), "panel": ("title",), "behind": ()}
HOLD = {"title": 2.6, "lower-third": 4.0, "quote": 1.8, "stat": 2.6, "chapter": 2.2, "list": 2.2, "panel": 2.5,
        "behind": 1.6}
MIN_DUR = {"title": 2.0, "lower-third": 3.0, "quote": 2.0, "stat": 3.0, "chapter": 2.0, "list": 2.5, "panel": 3.0,
           "behind": 1.5}
MAX_DUR = {"panel": 30.0, "behind": 10.0}
MAX_DUR_DEFAULT = 12.0
LEAD = 0.12
KEYS = {"type", "say", "word", "source", "lead", "hold", "until", "dur", "side", "title", "kicker", "name", "role",
        "text", "by", "value", "from", "prefix", "suffix", "decimals", "label", "source_note", "items", "body",
        "note", "box", "variant", "points", "layout", "background", "color"}
REEL_REV = 1

# --------------------------------------------------------------------------------------------- spec


def norm_type(t: Any) -> str:
    k = str(t or "").strip().lower()
    return ALIASES.get(k, k)


def normalize_specs(items: Any, errs: List[str], base: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Validate the EDL's `cards` list (shape only; the phrases are matched by `resolve`). `base`: the EDL's
    folder (a behind card's background image is relative to it)."""
    if items in (None, False):
        return []
    if not isinstance(items, list):
        errs.append("cards must be a list of card objects (references/editing.md, Cards)")
        return []
    out: List[Dict[str, Any]] = []
    for i, c in enumerate(items):
        where = "cards[%d]" % i
        if not isinstance(c, dict):
            errs.append("%s must be an object" % where)
            continue
        t = norm_type(c.get("type"))
        if t not in TYPES:
            errs.append("%s.type %r is not a card type (%s)" % (where, c.get("type"), ", ".join(TYPES)))
            continue
        if c.get("say") in (None, "") and c.get("word") is None:
            errs.append("%s (%s) needs \"say\" (a phrase from the transcript) or \"word\" (a word id such as w12)"
                        % (where, t))
            continue
        for k in NEEDS[t]:
            if c.get(k) in (None, "", []):
                errs.append("%s (%s) needs %r" % (where, t, k))
        for k in ("lead", "hold", "dur"):
            if c.get(k) is not None:
                try:
                    v = float(c[k])
                    if v < 0 or v > 120:
                        raise ValueError
                except (TypeError, ValueError):
                    errs.append("%s.%s must be seconds (0-120)" % (where, k))
        if t == "list":
            its = c.get("items")
            if not isinstance(its, list) or not its:
                errs.append("%s.items must be a list of {\"text\", \"say\"} (or strings)" % where)
            else:
                for j, it in enumerate(its):
                    if not isinstance(it, (str, dict)) or (isinstance(it, dict) and not it.get("text")):
                        errs.append("%s.items[%d] needs \"text\"" % (where, j))
        if c.get("layout") not in (None, "auto", "overlay", "split"):
            errs.append("%s.layout must be auto, overlay or split" % where)
        if c.get("side") not in (None, "auto", "left", "right") and not (t == "behind" and c.get("side") == "center"):
            errs.append("%s.side must be auto, left or right%s" % (where, " (or center)" if t == "behind" else ""))
        if t == "behind":
            from . import behind as BH
            BH.check_spec(c, where, errs, base)
        elif c.get("background") is not None or c.get("color") is not None:
            errs.append("%s: \"background\" and \"color\" belong to a behind card" % where)
        unknown = sorted(set(c) - KEYS)
        if unknown:
            errs.append("%s: unknown key(s) %s (known: %s)" % (where, ", ".join(unknown), ", ".join(sorted(KEYS))))
        out.append(dict(c, type=t, index=i))
    return out


# --------------------------------------------------------------------------------------------- matching

NUM = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                  "fourteen fifteen sixteen seventeen eighteen nineteen".split())}
NUM.update({"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
            "eighty": 80, "ninety": 90})
SCALE = {"hundred": 100, "thousand": 1000, "million": 10 ** 6, "billion": 10 ** 9}


def _toks(text: str) -> List[str]:
    t = str(text or "").lower().replace("%", " percent ").replace("per cent", "percent")
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)            # 22,000 -> 22000
    out = []
    for p in re.split(r"[\s\-–—/]+", t):
        p = re.sub(r"^[^\w$]+|[^\w]+$", "", p).replace("'", "").replace("’", "")
        if p:
            out.append(p)
    return out


def _canon(toks: Sequence[str]) -> List[Tuple[str, int, int]]:
    """Tokens with runs of English number words folded into digits: [(token, first, last)] (indices into toks).
    "twenty two thousand" -> "22000"; "one hundred and five" -> "105"; digits pass through."""
    out: List[Tuple[str, int, int]] = []
    i, n = 0, len(toks)
    while i < n:
        w = toks[i]
        if re.fullmatch(r"\d+", w) and i + 1 < n and toks[i + 1] in SCALE:    # "22 thousand"
            out.append((str(int(w) * SCALE[toks[i + 1]]), i, i + 1))
            i += 2
            continue
        if w in NUM:
            r = _spoken_number(toks, i)
            if r is not None:
                out.append((r[0], i, r[1] - 1))
                i = r[1]
                continue
        if re.fullmatch(r"\d+(\.\d+)?", w):
            w = w.rstrip("0").rstrip(".") if "." in w else w
        out.append((w, i, i))
        i += 1
    return out


def _sub100(toks: Sequence[str], j: int) -> Optional[Tuple[int, int]]:
    """A number under 100 at toks[j]: a unit, a teen, a tens word with an optional unit ("twenty two")."""
    if j >= len(toks) or toks[j] not in NUM:
        return None
    v = NUM[toks[j]]
    if v >= 20 and j + 1 < len(toks) and toks[j + 1] in NUM and 0 < NUM[toks[j + 1]] < 10:
        return v + NUM[toks[j + 1]], j + 2
    return v, j + 1


def _spoken_number(toks: Sequence[str], j: int) -> Optional[Tuple[str, int]]:
    """One spoken number starting at toks[j]: (digits, index after it). Years ("nineteen ninety five" 1995,
    "twenty twenty four" 2024), cardinals with hundred/thousand/million ("and" only after those), decimals
    ("two point five" 2.5). Two numbers side by side ("five six", "one and two") stay two numbers."""
    n = len(toks)
    a = _sub100(toks, j)
    if a is None:
        return None
    b = _sub100(toks, a[1])
    if 10 <= a[0] <= 99 and b is not None and 10 <= b[0] <= 99 and (b[1] >= n or toks[b[1]] not in SCALE):
        return str(a[0] * 100 + b[0]), b[1]                 # a year said in two halves
    total, k = 0, j
    while True:
        r = _sub100(toks, k)
        if r is None:
            break
        v, k = r
        if k < n and toks[k] == "hundred":
            v, k = v * 100, k + 1
            if k + 1 < n and toks[k] == "and" and toks[k + 1] in NUM:
                k += 1
            r = _sub100(toks, k)
            if r is not None:
                v, k = v + r[0], r[1]
        if k < n and toks[k] in SCALE and toks[k] != "hundred":
            total, k = total + v * SCALE[toks[k]], k + 1
            if k + 1 < n and toks[k] == "and" and toks[k + 1] in NUM:
                k += 1
            if k < n and toks[k] in NUM:
                continue
            break
        total += v
        break
    text = str(total)
    if k + 1 < n and toks[k] == "point" and toks[k + 1] in NUM and NUM[toks[k + 1]] < 10:
        digits = []
        k += 1
        while k < n and toks[k] in NUM and NUM[toks[k]] < 10:
            digits.append(str(NUM[toks[k]]))
            k += 1
        text = "%s.%s" % (text, "".join(digits))
        text = text.rstrip("0").rstrip(".")
    return text, k


def _word_tokens(words: Sequence[Dict[str, Any]]) -> Tuple[List[str], List[int]]:
    toks: List[str] = []
    owner: List[int] = []
    for k, w in enumerate(words):
        for t in _toks(w.get("text", "")):
            toks.append(t)
            owner.append(k)
    return toks, owner


class Matcher:
    """Phrase search over the output-timeline words (edl.map_words)."""

    def __init__(self, words: Sequence[Dict[str, Any]]) -> None:
        self.words = [w for w in words if w.get("type", "word") == "word"]
        toks, owner = _word_tokens(self.words)
        self.canon = [(t, owner[a], owner[b]) for t, a, b in _canon(toks)]
        self.raw = [(t, owner[i], owner[i]) for i, t in enumerate(toks)]

    def find(self, phrase: str, after: int = -1) -> Optional[Tuple[int, int]]:
        """(first word, last word) of the first match whose first word is after `after`, else None. Number words
        fold first ("22,000" = "twenty two thousand"); a phrase that holds only part of a spoken number
        ("twenty two" of "twenty two thousand") matches word for word, but only when the folded form is not said
        anywhere after `after` (then the folded match wins, even when it comes later)."""
        for seq, want in ((self.canon, [t for t, _a, _b in _canon(_toks(phrase))]), (self.raw, _toks(phrase))):
            n = len(want)
            if not n:
                return None
            for k in range(len(seq) - n + 1):
                if seq[k][1] <= after:
                    continue
                if all(seq[k + j][0] == want[j] for j in range(n)):
                    return seq[k][1], seq[k + n - 1][2]
        return None

    def find_all(self, phrase: str) -> List[Tuple[int, int]]:
        out, after = [], -1
        while True:
            m = self.find(phrase, after)
            if m is None:
                return out
            out.append(m)
            after = m[0]


def _word_index(words: Sequence[Dict[str, Any]], wid: Any, source: Optional[str]) -> Optional[int]:
    s = str(wid).strip()
    if re.fullmatch(r"\d+", s):
        s = "w" + s
    for k, w in enumerate(words):
        if str(w.get("id")) == s and (source is None or w.get("src") == source):
            return k
    return None


def _why_missing(phrase: str, edl: Dict[str, Any], transcripts: Dict[str, Dict[str, Any]], m: Matcher,
                 after: int, what: str = "say") -> str:
    if m.find(phrase, -1) is not None:
        if what == "until":
            return "it is said only before this card's anchor: \"until\" names words said after it"
        if what == "item":
            return "it is said only before the card's anchor: an item is matched after the card's own words"
        return ("it is said only before the previous card's anchor (cards match in order, each after the one "
                "before): move the card up the list or anchor it with \"word\"")
    for key, tr in transcripts.items():
        src = [w for w in tr.get("words", []) if w.get("type", "word") == "word"]
        hit = Matcher(src).find(phrase)
        if hit is not None:
            w = Matcher(src).words[hit[0]]
            return ("it was cut out of this edit (source %s at %.2f s, word %s): keep that range or pick another phrase"
                    % (key, float(w["start"]), w.get("id")))
    return "the transcript never says it (check the spelling against takes_packed.md)"


# --------------------------------------------------------------------------------------------- layout

def aspect_kind(w: int, h: int) -> str:
    r = h / float(w)
    return "tall" if r > 1.3 else ("square" if r >= 0.77 else "wide")


def caption_band(captions: Optional[Dict[str, Any]], w: int, h: int) -> Optional[Tuple[float, float]]:
    """(top, bottom) of the caption band in frame fractions, mirroring captions.to_ass (None: no captions)."""
    if not captions:
        return None
    from . import captions as C
    from .. import captions_rules as R
    try:
        st = C.get_style(captions.get("style", "bold-pop"),
                         {k: v for k, v in captions.items() if k in C.STYLES["bold-pop"]})
    except ShowtimeError:
        return None
    orient = C.orientation(w, h)
    size = max(12, int(round(C._pick(st["size"], orient) * min(w, h))))
    lines = int(st.get("max_lines", 2))
    block = size * (lines * 1.18) * (float(st.get("pop", 1.0)) if st.get("karaoke") else 1.0)
    pos = captions.get("position", "bottom")
    sl, stp, sr, sb = R.safe_box(w, h)
    if pos == "middle":
        y0 = (h - block) / 2.0
    elif pos == "top":
        mv = max(int(round((0.14 if orient == "portrait" else 0.07) * h)), int(round(stp)) + 4)
        y0 = mv
    else:
        mv = max(int(round(C._pick(st["margin_v"], orient) * h)), int(round(h - sb)) + 4)
        y0 = h - mv - block
    pad = 0.15 * size
    return max(0.0, (y0 - pad) / h), min(1.0, (y0 + block + pad) / h)


def _safe(w: int, h: int) -> Tuple[float, float, float, float]:
    from .. import captions_rules as R
    l, t, r, b = R.safe_box(w, h)
    return l / w, t / h, r / w, b / h


# the least height (frame fraction) a card needs in a tall frame, at the tall type scale
NEED_H = {"lower-third": 0.085, "title": 0.13, "stat": 0.12, "quote": 0.15, "list": 0.2, "chapter": 0.11}


def _free_band(lo: float, hi: float, blocks: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    """The tallest stretch of [lo, hi] that no block covers."""
    cuts = sorted((max(lo, a), min(hi, b)) for a, b in blocks if b > lo and a < hi)
    free, y = [], lo
    for a, b in cuts:
        if a > y:
            free.append((y, a))
        y = max(y, b)
    if y < hi:
        free.append((y, hi))
    return max(free, key=lambda r: r[1] - r[0]) if free else (lo, lo)


def unit_px(w: int, h: int) -> float:
    """The cards' type unit (--u in the reel's CSS) in pixels."""
    return 0.0142 * w if h / float(w) > 1.2 else 0.01 * min(w, h)


def need_height(card: Dict[str, Any], w: int, h: int, box_w: float) -> float:
    """About how tall (frame fraction) the card's plate is at this frame size: lines wrapped at the box width
    with an average glyph of 0.55 em (the reel's CSS sizes, in --u)."""
    u = unit_px(w, h)
    S = SIZES["tall" if h / float(w) > 1.2 else "wide"]
    inner = max(40.0, box_w * w - 6.4 * u)

    def lines(text: str, size_u: float) -> int:
        per = max(4, int(inner / (0.55 * size_u * u)))
        n, cur = 1, 0
        for word in str(text or "").split():
            if cur and cur + 1 + len(word) > per:
                n, cur = n + 1, len(word)
            else:
                cur += (1 if cur else 0) + len(word)
        return n
    t = card["type"]
    px = 5.2 * u                                            # the plate's padding
    if card.get("kicker"):
        px += 2.6 * 1.2 * u + 1.2 * u
    if t == "title":
        px += lines(card.get("title"), S["title"]) * S["title"] * 1.02 * u
    elif t == "chapter":
        px += lines(card.get("title"), S["chapter"]) * S["chapter"] * 1.02 * u + 2.9 * u
    elif t == "quote":
        px += 5 * u + lines(card.get("text") or card.get("said") or card.get("say"), S["quote"]) * S["quote"] * 1.14 * u
    elif t == "stat":
        px += S["stat"] * 1.1 * u + (lines(card.get("label"), S["label"]) * S["label"] * 1.25 * u if card.get("label") else 0)
    elif t == "list":
        its = card.get("items_resolved") or [{"text": x if isinstance(x, str) else x.get("text", "")}
                                             for x in card.get("items") or []]
        if card.get("title"):
            px += lines(card["title"], S["listtitle"]) * S["listtitle"] * 1.02 * u + 1.6 * u
        px += sum(lines(it["text"], S["item"]) * S["item"] * 1.08 * u for it in its) + 1.5 * u * max(0, len(its) - 1)
    elif t == "lower-third":
        # the lower-third component's own sizes (cqmin; name 6.4, role 4 in tall frames), its card padding
        cq = min(w, h) / 100.0
        tall = h / float(w) > 1.2
        role_lines = 0 if not card.get("role") else (1 if len(str(card["role"])) <= (32 if tall else 48) else 2)
        px = ((6.4 if tall else 4.4) * 1.2 + (4.0 if tall else 2.8) * 1.35 * role_lines + 3.2) * cq
    return px / h


# a tall frame's split (a panel, or a card with no room beside the face): the card above, the speaker below,
# the captions just above the seam (their baseline at SEAM_CAPTION_Y), the card's content above them
SEAM = 0.55
BRIDGE_S = 1.5        # splits (panels) closer than this are joined by the ground: no flip to the full shot
SEAM_CAPTION_Y = 0.538
SPLIT_CONTENT_END = 0.43


def layout(card: Dict[str, Any], w: int, h: int, band: Optional[Tuple[float, float]], side: str,
           face: Optional[Dict[str, float]] = None,
           cap_blocks: Optional[List[Tuple[float, float]]] = None,
           look: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The card's box (frame fractions x, y, w, h) and, for a panel, the speaker region and the panel region.
    face: the speaker's face in output fractions ({"top", "bottom"}), when found: tall frames keep cards off it.
    cap_blocks: where the captions sit while the card is up (caption_plan moves them off the face); default the
    caption band. In a tall frame a card with no room between the face and the captions becomes a split (the
    speaker moves to the lower half, as for a panel) unless it says "layout": "overlay"."""
    kind = aspect_kind(w, h)
    sl, st_, sr, sb = _safe(w, h)
    t = card["type"]
    if t == "behind":
        from . import behind as BH
        return BH.layout(card, w, h, face, kind, look)
    if isinstance(card.get("box"), dict):
        b = card["box"]
        return {"box": {k: float(b.get(k, d)) for k, d in (("x", 0.06), ("y", 0.1), ("w", 0.4), ("h", 0.3))},
                "kind": kind}
    top_of_band = band[0] if band else sb
    if kind == "wide":
        floor = min(sb, top_of_band - 0.03)
        if t == "title":
            x = 0.06 if side == "left" else 0.42
            box = {"x": x, "y": 0.08, "w": 0.52, "h": 0.30}
        elif t == "lower-third":
            hh = 0.17
            box = {"x": 0.06, "y": floor - hh, "w": 0.44, "h": hh}
        elif t == "chapter":
            box = {"x": 0.1, "y": 0.26, "w": 0.8, "h": 0.36}
        elif t == "panel":
            px = 0.0 if side == "left" else 0.5
            reg = {"x": px, "y": 0.0, "w": 0.5, "h": 1.0}
            spk = {"x": 0.5 if side == "left" else 0.0, "y": 0.0, "w": 0.5, "h": 1.0}
            box = {"x": px + 0.06, "y": 0.1, "w": 0.38, "h": floor - 0.1 - 0.01}
            return {"box": box, "kind": kind, "region": reg, "speaker": spk}
        else:   # quote, stat, list: beside the speaker
            x = 0.06 if side == "left" else 0.56
            box = {"x": x, "y": 0.1, "w": 0.38, "h": floor - 0.1 - 0.01}
        return {"box": box, "kind": kind}
    # tall and square: inside the platform safe box, in the tallest stretch the face and the captions leave free
    x0, x1 = max(sl, 0.06), min(sr, 0.94) if kind == "square" else sr
    top = st_ + 0.005
    split = {"region": {"x": 0.0, "y": 0.0, "w": 1.0, "h": SEAM}, "speaker": {"x": 0.0, "y": SEAM, "w": 1.0, "h": 1.0 - SEAM},
             "box": {"x": x0, "y": top, "w": x1 - x0, "h": SPLIT_CONTENT_END - top}, "kind": kind}
    if t == "panel" or card.get("layout") == "split":
        return dict(split, split=t != "panel")
    if t == "chapter" and card.get("layout") != "overlay":
        # in a tall frame a full-frame scrim would sit on the face: the chapter takes the split's top part
        return dict(split, split=True)
    if t == "chapter":
        blocks = [(band[0] - 0.01, band[1] + 0.01)] if band else []
        a, b = _free_band(top, sb - 0.005, blocks)
        hh = min(b - a, 0.3)
        return {"box": {"x": x0, "y": a + 0.008, "w": x1 - x0, "h": hh - 0.016}, "kind": kind}
    blocks = [(y0 - 0.005, y1 + 0.005) for y0, y1 in (cap_blocks if cap_blocks is not None else ([band] if band else []))]
    if face:
        blocks.append((face["top"], face["bottom"]))
    a, b = _free_band(top, sb - 0.005, blocks)
    room = b - a
    need = max(NEED_H.get(t, 0.12), need_height(card, w, h, x1 - x0))
    out = {"box": {"x": x0, "y": a + 0.008, "w": x1 - x0, "h": max(0.0, room - 0.016)}, "kind": kind,
           "room": round(room, 3), "need": need}
    if room + 1e-6 < need:
        if card.get("layout") != "overlay" and t != "lower-third":
            return dict(split, split=True, room=round(room, 3), need=need)
        out["cramped"] = True
    return out


def _overlap(a: Dict[str, float], b: Dict[str, float]) -> bool:
    return a["x"] < b["x"] + b["w"] - 1e-6 and b["x"] < a["x"] + a["w"] - 1e-6 and \
        a["y"] < b["y"] + b["h"] - 1e-6 and b["y"] < a["y"] + a["h"] - 1e-6


# --------------------------------------------------------------------------------------------- resolve

def _snap(t: float, fps: Fraction, up: bool = False) -> float:
    import math
    f = float(fps)
    n = math.ceil(t * f - 1e-6) if up else math.floor(t * f + 1e-6)
    return float(Fraction(max(0, n)) / fps)


def card_text(c: Dict[str, Any]) -> str:
    """Every word the card puts on screen (for reading time)."""
    parts: List[str] = []
    for k in ("kicker", "title", "name", "role", "text", "label", "body", "by", "source_note"):
        if c.get(k):
            parts.append(str(c[k]))
    if c["type"] == "stat":
        parts.append("%s%s%s" % (c.get("prefix") or "", c.get("value_text") or c.get("value") or "", c.get("suffix") or ""))
    for it in c.get("items_resolved") or []:
        parts.append(it["text"])
    return " ".join(parts)


def reading_time(text: str, spoken: bool = False) -> float:
    """Shortest time a card's text needs on screen. Silent text: 0.5 s + characters / 13 (captions.md, reading
    speed). Text the speaker says while it shows (a pull-quote of the line) is read along, like a caption:
    characters / 20 (qa's caption limit) + 0.5 s to finish."""
    return (len(text) / 20.0 if spoken else len(text) / 13.0) + 0.5


def resolve(edl: Dict[str, Any], segs: List[Dict[str, Any]], words: List[Dict[str, Any]],
            transcripts: Dict[str, Dict[str, Any]], *, width: Optional[int] = None, height: Optional[int] = None,
            faces: bool = True, look: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Output-timeline cards: start/end (frame-snapped), anchor words, items, layout. Raises ShowtimeError
    listing every card whose phrase is not found. `look` (look_for / look_peek) sizes a behind card's word in
    the look's display face."""
    specs = edl.get("cards") or []
    if not specs:
        return []
    fps: Fraction = edl["output"]["fps"]
    W = width or edl["output"]["width"]
    H = height or edl["output"]["height"]
    total = segs[-1]["out_end"] if segs else 0.0
    m = Matcher(words)
    ws = m.words
    band = caption_band(edl.get("captions"), W, H)
    errs: List[str] = []
    out: List[Dict[str, Any]] = []
    cursor = -1
    for c in specs:
        where = "cards[%d] (%s)" % (c["index"], c["type"])
        if c.get("word") is not None:
            k = _word_index(ws, c["word"], c.get("source"))
            if k is None:
                errs.append("%s: word %r is not in this edit (cut out, or not a word id of %s)" % (
                    where, c["word"], c.get("source") or "the transcript"))
                continue
            span = (k, k)
            if c.get("say"):
                hit = m.find(c["say"], k - 1)
                if hit is not None and hit[0] == k:
                    span = hit
        else:
            span = m.find(c["say"], cursor)
            if span is None and cursor >= 0:
                # no later match: two cards on the same words (a stat and a panel at one moment) share the anchor
                same = m.find(c["say"], cursor - 1)
                span = same if same is not None and same[0] == cursor else None
            if span is None:
                errs.append("%s: \"%s\" not found: %s" % (where, c["say"], _why_missing(c["say"], edl, transcripts, m, cursor)))
                continue
        cursor = span[0]
        a, b = span
        lead = float(c.get("lead", LEAD))
        start = _snap(max(0.0, float(ws[a]["start"]) - lead), fps)
        last_end = float(ws[b]["end"])
        items = []
        if c["type"] in ("list", "panel") and isinstance(c.get("items") or c.get("points"), list):
            icur = a - 1
            for j, it in enumerate(c.get("items") or c.get("points")):
                it = {"text": it} if isinstance(it, str) else dict(it)
                phrase = it.get("say") or it["text"]
                hit = m.find(phrase, icur)
                if hit is None:
                    errs.append("%s item %d: \"%s\" not found after the card's anchor: %s" % (
                        where, j + 1, phrase, _why_missing(phrase, edl, transcripts, m, icur, "item")))
                    continue
                icur = hit[0]
                at = _snap(max(start, float(ws[hit[0]]["start"]) - 0.08), fps)
                items.append({"text": str(it["text"]), "at": at, "say_end": float(ws[hit[1]]["end"])})
                last_end = max(last_end, float(ws[hit[1]]["end"]))
        if c.get("until"):
            hit = m.find(c["until"], a - 1)
            if hit is None:
                errs.append("%s: until \"%s\" not found after its anchor: %s" % (
                    where, c["until"], _why_missing(c["until"], edl, transcripts, m, a - 1, "until")))
                continue
            end = float(ws[hit[1]]["end"]) + 0.3
            # the pad after the last word never runs over the next cut: the card leaves with its shot
            nxt = next((s["out_start"] for s in segs if float(ws[hit[1]]["end"]) - 1e-6 <= s["out_start"] < end), None)
            if nxt is not None:
                end = nxt
        elif c.get("dur") is not None:
            end = start + float(c["dur"])
        else:
            end = last_end + float(c.get("hold", HOLD[c["type"]]))
            end = max(end, start + MIN_DUR[c["type"]])
            # a card leaves with its shot: the hold never runs over the next cut when the card has had its time
            nxt = next((float(s["out_start"]) for s in segs if last_end - 1e-6 <= float(s["out_start"]) < end), None)
            if nxt is not None and nxt - start >= MIN_DUR[c["type"]] and "hold" not in c:
                end = nxt
        end = min(_snap(end, fps, up=True), total)
        to_end = total - end < 1.0
        if to_end:
            end = total            # a card that would leave in the last second stays to the last frame
        rc = dict(c, start=round(start, 4), end=round(end, 4), anchor=[a, b],
                  said=" ".join(str(ws[k]["text"]) for k in range(a, b + 1)),
                  anchor_start=float(ws[a]["start"]), anchor_end=float(ws[b]["end"]),
                  segment=ws[a].get("segment"), items_resolved=items, to_end=to_end)
        if c["type"] == "quote":
            qw = [str(ws[k]["text"]).strip() for k in range(a, b + 1)]
            if not c.get("text"):
                # a pull-quote keeps the speaker's words; a cut into a sentence is marked with an ellipsis
                if a > 0 and not re.search(r"[.!?…]['\")\]]*$", str(ws[a - 1]["text"]).strip()):
                    qw[0] = "…" + qw[0]
                if not re.search(r"[.!?…]['\")\]]*$", qw[-1]):
                    qw[-1] = qw[-1].rstrip(",;:") + "…"
                rc["text"] = " ".join(qw)
            rc["quote_words"] = [{"text": qw[k - a], "at": round(max(0.0, float(ws[k]["start"]) - start), 3)}
                                 for k in range(a, b + 1)]
        if c["type"] == "stat" and c.get("value") is None:
            # the figure comes from the words only when they hold exactly one number; anything else could put a
            # number on screen she did not say, so the card has to give it
            nums = [t for t, _x, _y in _canon(_toks(rc["said"])) if re.fullmatch(r"\d+(\.\d+)?", t)]
            if len(nums) == 1:
                rc["value"] = float(nums[0]) if "." in nums[0] else int(nums[0])
                if "." in nums[0] and c.get("decimals") is None:
                    rc["decimals"] = len(nums[0].split(".")[1])
            else:
                errs.append("%s: %s in \"%s\": give the figure as \"value\"" % (
                    where, "no number" if not nums else "%d numbers (%s)" % (len(nums), ", ".join(nums)), rc["said"]))
                continue
        out.append(rc)
    if errs:
        raise ShowtimeError("%s: %d card(s) cannot be placed:\n  - %s" % (edl.get("origin", "EDL"), len(errs),
                                                                          "\n  - ".join(errs)),
                            hint="fix each card's \"say\" (a phrase as spoken; takes_packed.md has the words) or "
                                 "anchor it with \"word\": <id>; `showtime edit cards suggest <edl>` lists good moments")
    kind = aspect_kind(W, H)
    plan = caption_plan(edl, segs, W, H, faces=faces)
    for rc in out:
        face = face_box(edl, segs, rc["start"], rc["end"], W, H) if faces else None
        cap_blocks = [bd for a, b, bd in plan["bands"] if a < rc["end"] and rc["start"] < b] if band else None
        side = rc.get("side") or "auto"
        if side == "auto" and rc["type"] != "behind":       # a behind card places its word from the face itself
            if face is None or kind != "wide":
                side = "left" if rc["type"] == "panel" else "right"
            else:
                side = "left" if face["x"] >= 0.5 else "right"
        rc["side"] = side
        rc["face"] = face
        rc.update(layout(rc, W, H, band, side, face, cap_blocks, look))
        if rc["type"] == "behind":
            from . import behind as BH
            rc["plate_spec"] = BH.plate_of(rc, edl.get("dir"))
            rc["color_css"] = BH.color_css(rc, look, rc["plate"])
            rc["text"] = rc.get("text") or " ".join(rc["lines"])
            fm = rc.get("face_moved")
            if rc.get("moved") and fm and band:
                bh = band[1] - band[0]
                below = fm["chin"] + 0.008
                if below + bh <= _safe(W, H)[3] + 1e-6:
                    rc["caption_zone"] = {"start": rc["start"], "end": rc["end"], "align": 8,
                                          "y": round(below + 0.15 * bh / 1.3, 4), "why": "behind", "cut": True}
                else:
                    rc["caption_room"] = round(_safe(W, H)[3] - below, 3)
        rc["text_all"] = card_text(rc)
    # where a panel or a split is up, its own caption zone applies (the face is in the lower half then)
    # two splits (or panels) close together keep the split between them: a ground-only bridge, so the frame
    # does not flip to the full shot and back for a moment
    regs = sorted([c for c in out if c.get("region")], key=lambda c: c["start"])
    for a, b in zip(regs, regs[1:]):
        if 0 < b["start"] - a["end"] <= BRIDGE_S and a["region"] == b["region"]:
            out.append({"type": "ground", "index": -1 - len(out), "start": a["end"], "end": b["start"],
                        "region": a["region"], "speaker": a["speaker"], "side": a.get("side"), "box": a["box"],
                        "kind": kind, "said": "", "text_all": "", "items_resolved": [], "to_end": False})
    out.sort(key=lambda c: (c["start"], c["index"]))
    covered = [(c["start"], c["end"]) for c in out if (c.get("region") or c.get("speaker")) and kind != "wide"]
    plan["problems"] = [p for p in plan["problems"] if not any(a < p["end"] and p["start"] < b for a, b in covered)]
    edl["caption_plan"] = plan
    return out


_FACE_CACHE: Dict[str, Optional[Tuple[float, float, float]]] = {}


def face_box(edl: Dict[str, Any], segs: List[Dict[str, Any]], t0: float, t1: float, W: int, H: int
             ) -> Optional[Dict[str, float]]:
    """The speaker's face over output time t0..t1 in output-frame fractions: {"x", "top", "bottom"} (top
    includes the hair, bottom the chin), from YuNet's median over the card's window; None without a face.
    A frame of the source's aspect shows it whole; a taller frame (a 9:16 reframe) keeps the full height and
    centres the face across, so y maps through and x is the middle (a punch-in scales y about the centre)."""
    seg = next((s for s in segs if s["out_start"] <= (t0 + t1) / 2 < s["out_end"]), None)
    if seg is None:
        return None
    src = edl["sources"][seg["source"]]
    a = seg["start"] + max(0.0, t0 - seg["out_start"])
    d = max(0.5, min(t1, seg["out_end"]) - max(t0, seg["out_start"]))
    key = "%s:%.2f:%.2f" % (src["path"], a, d)
    if key not in _FACE_CACHE:
        med = None
        try:
            from . import reframe as RF
            if RF.available()[0]:
                pr = src["probe"]
                tr = [t for t in RF.detect_track(src["path"], a, min(d, 6.0), pr.get("display_width") or pr.get("width"),
                                                 pr.get("display_height") or pr.get("height")) if t is not None]
                if tr:
                    med = tuple(sorted(t[i] for t in tr)[len(tr) // 2] for i in range(3))
        except Exception as e:  # noqa: BLE001 - placement falls back to the defaults
            debug("cards: face detection failed: %s" % e)
        _FACE_CACHE[key] = med
    med = _FACE_CACHE[key]
    if med is None:
        return None
    cx, cy, fh = med
    pr = src["probe"]
    sw, sh = pr.get("display_width") or pr.get("width") or W, pr.get("display_height") or pr.get("height") or H
    src_ar, out_ar = sw / float(sh), W / float(H)
    fit = seg.get("fit") or (edl.get("output") or {}).get("fit") or "auto"
    if fit == "auto":       # render_edl._decide_fit's rule
        fit = "cover" if abs(src_ar - out_ar) / out_ar < 0.04 else ("blur" if src_ar < out_ar else "reframe")
    z = float(seg.get("zoom") or 1.0)
    # source fractions (y from the face box; what a caption must never cover runs from the eyes to the chin)
    ys = {"top": cy - 0.8 * fh, "bottom": cy + 0.6 * fh, "eyes": cy - 0.3 * fh, "chin": cy + 0.55 * fh}
    if fit in ("contain", "blur"):
        # the whole picture sits in a band (letterbox) or a column (pillarbox) of the frame
        s = min(W / float(sw), H / float(sh))
        pw, ph = sw * s / W, sh * s / H
        x = (1 - pw) / 2 + cx * pw
        mapped = {k: (1 - ph) / 2 + v * ph for k, v in ys.items()}
    else:
        taller = out_ar < src_ar * 0.96
        x = 0.5 if taller else cx          # a taller frame's crop follows the face across
        mapped = dict(ys)
        if not taller and out_ar > src_ar * 1.04:
            # a wider frame cut from a taller source (cover) crops the height about the centre
            k = (W / float(sw)) / (H / float(sh))
            mapped = {key: 0.5 + (v - 0.5) * k for key, v in ys.items()}
    if z > 1.001:
        mapped = {k: 0.5 + (v - 0.5) * z for k, v in mapped.items()}
    return {"x": x, "top": round(max(0.0, mapped["top"]), 3), "bottom": round(min(1.0, mapped["bottom"]), 3),
            "eyes": round(max(0.0, mapped["eyes"]), 3), "chin": round(min(1.0, mapped["chin"]), 3)}


def _windows(segs: List[Dict[str, Any]], step: float = 3.0) -> List[Tuple[float, float]]:
    out = []
    for s in segs:
        a, b = float(s["out_start"]), float(s["out_end"])
        n = max(1, int(round((b - a) / step)))
        out += [(a + (b - a) * i / n, a + (b - a) * (i + 1) / n) for i in range(n)]
    return out


def caption_plan(edl: Dict[str, Any], segs: List[Dict[str, Any]], W: int, H: int,
                 faces: bool = True) -> Dict[str, Any]:
    """Keep the captions off the speaker's face (eyes to chin), window by window (about 3 s, never across a cut):
    where the caption band would cover the tracked face, the captions move just below the chin when they fit
    above the platform's bottom UI, else just above the eyes; where neither fits, the window is a problem.
    Returns {"zones": captions.build zones, "bands": [(start, end, (top, bottom))] where the captions sit,
    "problems": [...]}. Panels and splits add their own zones (caption_zones), which win."""
    band = caption_band(edl.get("captions"), W, H)
    out: Dict[str, Any] = {"zones": [], "bands": [], "problems": []}
    if not band or not segs:
        return out
    if (edl.get("captions") or {}).get("avoid_face") is False:
        out["bands"] = [(a, b, band) for a, b in _windows(segs)]
        return out
    bh = band[1] - band[0]
    sl, st_, sr, sb = _safe(W, H)
    for a, b in _windows(segs):
        face = face_box(edl, segs, a, b, W, H) if faces else None
        eff = band
        if face and band[0] < face["chin"] and face["eyes"] < band[1]:
            below, above = face["chin"] + 0.008, face["eyes"] - 0.008
            if below + bh <= sb + 1e-6:
                eff = (below, below + bh)
                out["zones"].append({"start": a, "end": b, "align": 8, "y": round(below + 0.15 * bh / 1.3, 4),
                                     "why": "face"})
            elif above - bh >= st_ - 1e-6:
                eff = (above - bh, above)
                out["zones"].append({"start": a, "end": b, "align": 2, "y": round(above - 0.15 * bh / 1.3, 4),
                                     "why": "face"})
            else:
                out["problems"].append({"start": a, "end": b,
                                        "message": "the captions cover the speaker's face at %.1f-%.1f s (eyes %.2f to "
                                                   "chin %.2f of the frame) and there is no room above or below it: a "
                                                   "smaller caption style or size, or a panel" % (a, b, face["eyes"],
                                                                                                  face["chin"])})
        out["bands"].append((a, b, eff))
    return out


# --------------------------------------------------------------------------------------------- check

def problems(cards: List[Dict[str, Any]], edl: Dict[str, Any], width: Optional[int] = None,
             height: Optional[int] = None, measured: Optional[Dict[int, Dict[str, Any]]] = None) -> List[str]:
    """What `edit check` reports about resolved cards (each line names the card and the fix). `measured`:
    a behind card's matte and hidden-text numbers by card index (the render's, else edit check estimates)."""
    W = width or edl["output"]["width"]
    H = height or edl["output"]["height"]
    out: List[str] = []
    band = caption_band(edl.get("captions"), W, H)
    sl, st_, sr, sb = _safe(W, H)
    kind = aspect_kind(W, H)
    panels = [c for c in cards if c.get("region")]
    plan = edl.get("caption_plan") or {}
    out += [p["message"] for p in plan.get("problems", [])]
    cards = [c for c in cards if c["type"] != "ground"]    # bridges carry no text and never overlap a card

    def name(c: Dict[str, Any]) -> str:
        return "cards[%d] %s at %.2f s" % (c["index"], c["type"], c["start"])

    for c in cards:
        d = c["end"] - c["start"]
        spoken = c["type"] in ("quote", "behind") and _same_words(c.get("text") or "", c["said"])
        need = reading_time(c["text_all"], spoken)
        if d + 1e-6 < need:
            out.append("%s is on screen %.1f s; its %d characters need %.1f s to read (%s): raise \"hold\", end it "
                       "with \"until\", or shorten the text%s" % (
                           name(c), d, len(c["text_all"]), need,
                           "read along as it is said: characters / 20 + 0.5 s" if spoken else "0.5 s + characters / 13",
                           " (a quote: anchor a shorter part of the line)" if c["type"] == "quote" else ""))
        cap = MAX_DUR.get(c["type"], MAX_DUR_DEFAULT)
        if d > cap:
            out.append("%s stays %.1f s (over %.0f s): a card that long stops reading as an accent; split it or end it "
                       "earlier with \"until\"" % (name(c), d, cap))
        if d < 1.0:
            out.append("%s flashes for %.2f s: give it at least 2 s" % (name(c), d))
        if c["type"] == "stat":
            # the card's text has its reading time above; the counted figure must also rest a moment before it goes
            settled = d - 0.1 - count_dur(c)
            if settled + 0.02 < STAT_SETTLED_S:
                out.append("%s shows its counted figure for %.1f s before it leaves (at least %.1f s): end it later "
                           "(\"until\"/\"hold\")" % (name(c), max(0.0, settled), STAT_SETTLED_S))
        for k, it in enumerate(c.get("items_resolved") or []):
            if it["at"] > c["end"] - 0.8:
                out.append("%s: item %d (\"%s\") is said at %.2f s, after the card leaves at %.2f s (or in its last "
                           "0.8 s): end the card later (\"until\") or drop the item" % (name(c), k + 1, it["text"],
                                                                                        it["at"], c["end"]))
        b = c["box"]
        if b["x"] < sl - 0.005 or b["x"] + b["w"] > sr + 0.005 or b["y"] < st_ - 0.005 or b["y"] + b["h"] > sb + 0.005:
            out.append("%s leaves the %s safe box (x %.2f-%.2f, y %.2f-%.2f of the frame): platform UI covers it; "
                       "drop the \"box\" override or move it inside" % (name(c), "9:16" if kind == "tall" else "title",
                                                                         sl, sr, st_, sb))
        nh = need_height(c, W, H, b["w"]) if c["type"] not in ("panel", "lower-third", "behind") else 0.0
        if not c.get("cramped") and nh > b["h"] + 0.01:
            out.append("%s needs about %.0f %% of the frame's height and its box has %.0f %%: shorten the text or "
                       "give it a bigger \"box\"" % (name(c), 100 * nh, 100 * b["h"]))
        if c.get("cramped"):
            mid = ((edl.get("captions") or {}).get("position") == "middle")
            out.append("%s has %.0f %% of the frame's height free between the face and the captions (it needs about "
                       "%.0f %%): %sshorten the card, or make it a panel (the speaker moves to the lower half)" % (
                           name(c), 100 * c.get("room", 0), 100 * c.get("need", 0),
                           "" if mid else "put the captions in the middle (\"position\": \"middle\"), "))
        if band:
            in_split = kind != "wide" and any(p["start"] < c["end"] and c["start"] < p["end"] for p in panels)
            if in_split:
                cbs = [(SEAM_CAPTION_Y - (band[1] - band[0]), SEAM_CAPTION_Y)]
            else:
                cbs = [bd for a, e, bd in plan.get("bands", []) if a < c["end"] and c["start"] < e] or [band]
            hit = next((cb for cb in cbs if b["y"] < cb[1] and cb[0] < b["y"] + b["h"]), None)
            if hit:
                out.append("%s sits on the caption band (y %.2f-%.2f of the frame): the captions would run over it; "
                           "drop the \"box\" override, or move the captions (\"position\": \"top\")" % (name(c), hit[0], hit[1]))
    if any(c["type"] == "behind" for c in cards):
        from . import behind as BH
        for c in cards:
            if c["type"] != "behind":
                continue
            out += BH.problems(c, (measured or {}).get(c["index"]))
            if c.get("plate_note"):
                out.append("%s: %s" % (name(c), c["plate_note"]))
            if c.get("caption_room") is not None:
                out.append("%s: the speaker moves down for the word and the captions have no room under the chin "
                           "(%.0f %% of the frame): a smaller caption size, or a shorter word" % (
                               name(c), 100 * max(0.0, c["caption_room"])))
    for i, a in enumerate(cards):
        for bb in cards[i + 1:]:
            together = a["start"] < bb["end"] - 1e-6 and bb["start"] < a["end"] - 1e-6
            if together and "behind" in (a["type"], bb["type"]) and (
                    a["type"] == bb["type"] or a.get("region") or bb.get("region")):
                bh, other = (a, bb) if a["type"] == "behind" else (bb, a)
                out.append("%s and %s are up together (%.2f-%.2f s): %s; end one before the other starts" % (
                    name(bh), name(other), max(a["start"], bb["start"]), min(a["end"], bb["end"]),
                    "one word behind the speaker at a time" if a["type"] == bb["type"] else
                    "a word behind the speaker needs the full frame, and the panel moves the speaker"))
                continue
            moves_a, moves_b = bool(a.get("region") or a.get("speaker")), bool(bb.get("region") or bb.get("speaker"))
            if together and kind != "wide" and moves_a != moves_b and "chapter" not in (a["type"], bb["type"]):
                sp, ov = (a, bb) if moves_a else (bb, a)
                out.append("%s is up while %s moves the speaker %s (%.2f-%.2f s): it was placed for the "
                           "full frame; end one before the other starts" % (
                               name(ov), name(sp), "down" if sp["type"] == "behind" else "to the lower half",
                               max(a["start"], bb["start"]), min(a["end"], bb["end"])))
                continue
            if a["start"] < bb["end"] - 1e-6 and bb["start"] < a["end"] - 1e-6:
                ra = a.get("region") or a["box"]
                rb = bb.get("region") or bb["box"]
                if _overlap(ra, rb):
                    out.append("%s and %s are on screen together (%.2f-%.2f s) in the same place: end the first "
                               "earlier (\"hold\"/\"until\") or anchor the second later" % (
                                   name(a), name(bb), max(a["start"], bb["start"]), min(a["end"], bb["end"])))
    return out


def _same_words(a: str, b: str) -> bool:
    return [t for t, _x, _y in _canon(_toks(a))] == [t for t, _x, _y in _canon(_toks(b))]


def emphasis_problems(n_terms: int, n_hits: int, total: float) -> List[str]:
    """n_hits: how many times an emphasis term is said (each occurrence is one accent on screen)."""
    out = []
    if n_terms > 5:
        out.append("captions.emphasis has %d terms: 3-5 that carry the message read as emphasis; more read as noise" % n_terms)
    if total > 0 and n_hits > max(5, total / 6.0):
        out.append("captions.emphasis is said %d times in %.0f s (more than once per 6 s): keep the few terms that carry "
                   "the message" % (n_hits, total))
    return out


def summary_rows(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"i": c["index"], "type": c["type"], "start": c["start"], "end": c["end"], "said": c["said"],
             "side": c.get("side"), "split": bool(c.get("split")), "box": {k: round(v, 3) for k, v in c["box"].items()},
             **({"region": c["region"]} if c.get("region") else {}),
             **({"text": c.get("text"), "plate": c.get("plate"), "moved": bool(c.get("moved")),
                 "speaker": c.get("speaker"), "align": c.get("align"), "est_hidden": c.get("est_hidden"),
                 "est_run": c.get("est_run")} if c["type"] == "behind" else {}),
             "items": [{"text": it["text"], "at": it["at"]} for it in c.get("items_resolved") or []]}
            for c in cards if c["type"] != "ground"]


# --------------------------------------------------------------------------------------------- framing

def panel_splits(ranges: List[Dict[str, Any]], segs: List[Dict[str, Any]], cards: List[Dict[str, Any]],
                 fps: Fraction) -> List[Dict[str, Any]]:
    """The EDL ranges split at every panel's first and last frame; the ranges inside a panel get its `layout`.
    Splits are frame-aligned (start + frames / fps), so they are reframe-only joins: same source, continuous
    audio, no fades, and the frame count (and every output time) stays the same."""
    panels = [c for c in cards if c.get("speaker")]          # panels, and 9:16 behind cards that move the speaker
    if not panels:
        return ranges
    f = float(fps)
    marks = []
    for p in panels:
        marks.append((int(round(p["start"] * f)), int(round(p["end"] * f)), p))
    out: List[Dict[str, Any]] = []
    f0 = 0
    for r, s in zip(ranges, segs):
        n = s["frames"] - int(s.get("hold_frames") or 0)     # a held range: only its moving part splits
        cuts = sorted({k for a, b, _p in marks for k in (a, b) if f0 < k < f0 + n})
        edges = [f0] + cuts + [f0 + n]
        for a, b in zip(edges, edges[1:]):
            sub = dict(r)
            if b != f0 + n:
                sub.pop("hold", None)
            sub["start"] = r["start"] + (a - f0) / f
            sub["end"] = r["start"] + (b - f0) / f
            mid = (a + b) / 2.0
            p = next((p for x, y, p in marks if x <= mid < y), None)
            if p is not None:
                sub["layout"] = {"panel": p["index"], "speaker": p["speaker"], "side": p.get("side"), "card": p["type"]}
            elif "layout" in sub:
                sub.pop("layout")
            out.append(sub)
        f0 += s["frames"]
    return out


# --------------------------------------------------------------------------------------------- look

def look_peek(edl: Dict[str, Any], work: Path) -> Optional[Dict[str, Any]]:
    """The cards' look as the render would use it, without picking one (edit check): the EDL's `look`, the
    brand kit, or the signature an earlier render kept; None when none is decided yet."""
    from ..variety import signatures as sigs
    if edl.get("look"):
        sig = sigs.get(edl["look"])
        return {"sig": sig, "brand": None, "tokens": sigs.tokens(sig, "dom")}
    try:
        from .. import brand as brandmod
        kit = brandmod.load(edl["dir"])
    except Exception:  # noqa: BLE001
        kit = None
    if kit is not None:
        from ..brand.apply import tokens as brand_tokens
        return {"sig": None, "brand": kit, "tokens": brand_tokens(kit)[0]}
    rec = read_json(work / "look.json", None) if (work / "look.json").is_file() else None
    if isinstance(rec, dict) and rec.get("id"):
        try:
            sig = sigs.get(rec["id"])
            return {"sig": sig, "brand": None, "tokens": sigs.tokens(sig, "dom")}
        except ShowtimeError:
            return None
    return None


def look_for(edl: Dict[str, Any], work: Path) -> Dict[str, Any]:
    """{"sig": signature dict or None, "brand": kit or None, "about": str, "tokens": {...}} for the cards.
    The EDL's `look` wins, then a brand kit near the EDL, then a signature picked once (seeded by the EDL's
    path, away from recent looks) and kept in work/cards/look.json so later renders keep it."""
    from ..variety import signatures as sigs
    want = edl.get("look")
    if want:
        sig = sigs.get(want)
        return {"sig": sig, "brand": None, "about": "look %s (the EDL's)" % sig["name"], "tokens": sigs.tokens(sig, "dom")}
    try:
        from .. import brand as brandmod
        kit = brandmod.load(edl["dir"])
    except Exception:  # noqa: BLE001 - an unreadable kit: brand check says why
        kit = None
    if kit is not None:
        from ..brand.apply import tokens as brand_tokens
        t, _n = brand_tokens(kit)
        return {"sig": None, "brand": kit, "about": "the brand kit's colours", "tokens": t}
    keep = work / "look.json"
    rec = read_json(keep, None) if keep.is_file() else None
    sig = None
    if isinstance(rec, dict) and rec.get("id"):
        try:
            sig = sigs.get(rec["id"])
        except ShowtimeError:
            sig = None
    picked = False
    if sig is None:
        sig = sigs.choose("dom", str(Path(edl.get("origin", "edl")).resolve()))
        picked = True
        ensure_dir(work)
        write_json(keep, {"id": sig["id"], "about": "look signature picked for this EDL's cards; set \"look\" in the "
                                                    "EDL to choose another"})
        try:
            sigs.record_pick(sig["id"], Path(edl["origin"]).resolve())
        except Exception:  # noqa: BLE001
            pass
    return {"sig": sig, "brand": None, "tokens": sigs.tokens(sig, "dom"),
            "about": "look %s%s (set \"look\" in the EDL to change it; `showtime signature` lists them)" % (
                sig["name"], ", picked away from your recent looks" if picked else "")}


def accent_for_captions(look: Dict[str, Any]) -> Optional[str]:
    """The look's accent for caption emphasis when it reads on footage with a dark outline, else accent-2,
    else None (the caption style's own highlight)."""
    from ..brand import contrast
    t = look.get("tokens") or {}
    for k in ("--accent", "--accent-2"):
        v = str(t.get(k) or "")
        if re.fullmatch(r"#[0-9a-fA-F]{6}", v) and contrast(v, "#000000") >= 7.0:
            return v
    return None


# --------------------------------------------------------------------------------------------- the reel page

# type sizes in --u (the reel's unit: 1cqmin, or 1.42cqw in tall frames, where a phone shows them small); one
# table for the CSS and for need_height
SIZES = {
    "wide": {"title": 6.4, "chapter": 9.0, "quote": 4.4, "stat": 12.0, "label": 3.2, "item": 4.2, "listtitle": 4.6,
             "ptitle": 7.6, "pitem": 4.2},
    "tall": {"title": 5.6, "chapter": 6.6, "quote": 3.6, "stat": 9.5, "label": 3.0, "item": 3.7, "listtitle": 4.0,
             "ptitle": 5.8, "pitem": 3.6},
}


def css(behind: bool = False) -> str:
    """The reel's styles; `behind` adds the behind card's (only then, so other reels keep their cache keys)."""
    def decl(k: str) -> str:
        return " ".join("--s-%s: %s;" % kv for kv in SIZES[k].items())
    out = CSS.replace("%(wide)s", decl("wide")).replace("%(tall)s", decl("tall"))
    if behind:
        from . import behind as BH
        out += BH.CSS
    return out


CSS = r"""
html, body { background: transparent; }
.stage { background: transparent; }
.scene { background: transparent; --u: 1cqmin; %(wide)s }
@container (max-aspect-ratio: 5/6) { .scene { --u: 1.42cqw; %(tall)s } }
.box { position: absolute; display: flex; flex-direction: column; }
.plate { position: relative; background: color-mix(in oklab, var(--surface) 94%, transparent); color: var(--fg);
  border-radius: calc(var(--u) * 1.4); padding: calc(var(--u) * 2.6) calc(var(--u) * 3.2);
  box-shadow: 0 calc(var(--u) * 1.2) calc(var(--u) * 4) rgb(0 0 0 / 0.35);
  border: 1px solid color-mix(in oklab, var(--fg) 10%, transparent);
  animation: plateIn 0.5s var(--ease-out) var(--in, 0s) both, plateOut 0.35s cubic-bezier(0.5, 0, 0.75, 0) var(--out) forwards; }
.plate::before { content: ''; position: absolute; left: 0; top: calc(var(--u) * 2.4); bottom: calc(var(--u) * 2.4);
  width: calc(var(--u) * 0.55); background: var(--accent); border-radius: 0 9px 9px 0; }
@keyframes plateIn { from { opacity: 0; transform: translateY(calc(var(--u) * 2)) scale(0.985); } to { opacity: 1; transform: none; } }
@keyframes plateOut { from { opacity: 1; } to { opacity: 0; transform: translateY(calc(var(--u) * -1)); } }
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes fadeOut { from { opacity: 1; } to { opacity: 0; } }
@keyframes ruleIn { from { transform: scaleX(0); } to { transform: scaleX(1); } }
.kicker { font: 600 calc(var(--u) * 2.6)/1.2 var(--font-mono); letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--accent); margin: 0 0 calc(var(--u) * 1.2); }
.title { font-family: var(--font-display); font-weight: var(--weight-display); letter-spacing: var(--tracking-display);
  text-transform: var(--case-display, none); line-height: 1.02; font-size: calc(var(--u) * var(--s-title)); margin: 0; }
.body { font: 500 calc(var(--u) * 3.1)/1.32 var(--font-body); color: var(--fg); margin: calc(var(--u) * 1.4) 0 0; }
.muted { color: var(--muted); }
.note { font: 500 calc(var(--u) * 2.15)/1.3 var(--font-body); color: var(--muted); margin: calc(var(--u) * 1.6) 0 0; }
/* quote */
.q-mark { font: 700 calc(var(--u) * 11)/0.7 var(--font-display); color: var(--accent); height: calc(var(--u) * 5); }
.q-text { font-family: var(--font-display); font-weight: var(--weight-display); font-size: calc(var(--u) * var(--s-quote));
  line-height: 1.14; letter-spacing: calc(var(--tracking-display) * 0.5); margin: 0; text-wrap: balance; }
.q-by { font: 600 calc(var(--u) * 2.3)/1.2 var(--font-mono); letter-spacing: 0.1em; text-transform: uppercase;
  color: var(--muted); margin-top: calc(var(--u) * 1.8); }
/* stat */
.stat [data-st="count-up"] { --cu-size: calc(var(--u) * var(--s-stat)); text-align: left; }
.stat .st-cu-figure { justify-content: flex-start; color: var(--accent); font-family: var(--font-display);
  font-weight: var(--weight-display); }
.stat .st-cu-label { font: 600 calc(var(--u) * var(--s-label))/1.25 var(--font-body); color: var(--fg); text-align: left; }
/* list */
.list-items { display: flex; flex-direction: column; gap: calc(var(--u) * 1.5); margin-top: calc(var(--u) * 1.6); }
.li { display: flex; align-items: baseline; gap: calc(var(--u) * 1.6); opacity: 0;
  animation: liIn 0.45s var(--ease-out) var(--at) both; }
.li-n { font: 700 calc(var(--u) * 2.6)/1 var(--font-mono); color: var(--accent-ink); background: var(--accent);
  border-radius: calc(var(--u) * 0.8); padding: calc(var(--u) * 0.6) calc(var(--u) * 0.9); min-width: 1.8em; text-align: center; }
.li-t { font-family: var(--font-display); font-weight: var(--weight-display); font-size: calc(var(--u) * var(--s-item)); line-height: 1.08; }
@keyframes liIn { from { opacity: 0; transform: translateX(calc(var(--u) * -2)); } to { opacity: 1; transform: none; } }
/* a list on a plate grows as each item is said: an item takes no room before its cue (no empty plate) */
.plate .list-items { gap: 0; }
.plate .li { overflow: hidden; max-height: 0; margin-top: 0;
  animation: liGrow 0.35s var(--ease-out) var(--at) both, liIn 0.45s var(--ease-out) calc(var(--at) + 0.08s) both; }
@keyframes liGrow { from { max-height: 0; margin-top: 0; } to { max-height: calc(var(--u) * 18); margin-top: calc(var(--u) * 1.5); } }
/* chapter */
.scrim { position: absolute; inset: 0; background: radial-gradient(90% 80% at 50% 50%, rgb(0 0 0 / 0.62), rgb(0 0 0 / 0.38));
  animation: fadeIn 0.35s linear 0s both, fadeOut 0.35s linear var(--out) forwards; }
.chapter { align-items: center; justify-content: center; text-align: center; color: #fff; }
.chapter .kicker { color: var(--accent); }
.chapter .title { font-size: calc(var(--u) * var(--s-chapter)); color: #fff; text-wrap: balance; }
.chapter .rule { width: calc(var(--u) * 16); height: calc(var(--u) * 0.5); background: var(--accent); margin-top: calc(var(--u) * 2.4);
  transform-origin: 50% 50%; animation: ruleIn 0.6s var(--ease-out) 0.35s both; }
.chapter > * { animation: fadeOut 0.3s linear var(--out) forwards; }
.chapter.onground, .chapter.onground .title { color: var(--fg); }
/* panel */
.panel-bg { position: absolute; background: var(--bg); overflow: hidden;
  animation: fadeOut 0.01s linear var(--end) forwards; }
.panel-bg::before { content: ''; position: absolute; inset: 0;
  background: radial-gradient(70% 60% at 30% 20%, color-mix(in oklab, var(--accent) calc(18% * var(--ground-glow, 1)), transparent), transparent 70%); }
.panel-bg::after { content: ''; position: absolute; inset: 0; opacity: min(1, var(--ground-grid, 1));
  background-image: linear-gradient(to right, color-mix(in oklab, var(--fg) 6%, transparent) 1px, transparent 1px),
                    linear-gradient(to bottom, color-mix(in oklab, var(--fg) 6%, transparent) 1px, transparent 1px);
  background-size: calc(var(--u) * 8) calc(var(--u) * 8); }
.panel-edge { position: absolute; background: var(--accent); }
.panel { justify-content: center; color: var(--fg); }
.panel .title { font-size: calc(var(--u) * var(--s-ptitle)); text-wrap: balance; }
.panel > * { animation: fadeOut 0.3s linear var(--out) forwards; }
.panel .list-items { gap: calc(var(--u) * 2); margin-top: calc(var(--u) * 3); }
.panel .list-items .li-t { font-size: calc(var(--u) * var(--s-pitem)); }
.panel .body { font-size: calc(var(--u) * 3.6); }
.lt [data-st="lower-third"] { position: absolute; left: 0; bottom: 0; }
"""


def _e(s: Any) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def _pct(v: float) -> str:
    return "%.3f%%" % (v * 100)


def _box_style(b: Dict[str, float]) -> str:
    return "left:%s;top:%s;width:%s;height:%s" % (_pct(b["x"]), _pct(b["y"]), _pct(b["w"]), _pct(b["h"]))


def _card_html(c: Dict[str, Any], dur: float, kind: str) -> str:
    """One card's scene: its body, and for a split (a tall card with no room beside the face) the panel ground
    over the top half, the card centred on it."""
    if c.get("to_end"):
        dur += 10.0      # the card holds on the last frame: its exit falls after the video ends
    var = "--out:%.3fs;--end:%.3fs" % (max(0.4, dur - 0.4), max(0.0, dur - 0.034))
    if c["type"] == "ground":
        body = ""
    else:
        body = _card_body(c, dur, kind)
        if c["type"] == "chapter" and c.get("split"):
            body = re.sub(r'<div class="scrim"[^>]*></div>', "", body).replace('class="box chapter"', 'class="box chapter onground"')
    if not c.get("split") and c["type"] != "ground":
        return body
    reg = c["region"]
    if kind == "wide":
        ex = reg["x"] + reg["w"] if c.get("side") == "left" else reg["x"]
        edge = '<div class="panel-edge" style="left:calc(%s - 0.25cqmin);top:0;width:0.5cqmin;height:100%%;%s"></div>' % (
            _pct(ex), var)
    else:
        edge = '<div class="panel-edge" style="left:0;top:calc(%s - 0.25cqmin);width:100%%;height:0.5cqmin;%s"></div>' % (
            _pct(reg["y"] + reg["h"]), var)
    ground = '<div class="panel-bg" style="%s;%s"></div>%s' % (_box_style(reg), var, edge)
    return ground + body.replace("justify-content:flex-start", "justify-content:center", 1)


STAT_SETTLED_S = 1.5   # a stat's figure stays settled (counted up) at least this long


def count_dur(c: Dict[str, Any]) -> float:
    """How long a stat counts up: while the number is said (0.5-1.2 s), short enough that the settled figure
    stays up STAT_SETTLED_S before the card leaves."""
    return max(0.5, min(1.2, c["anchor_end"] - c["anchor_start"], (c["end"] - c["start"]) - 0.1 - STAT_SETTLED_S))


def _card_body(c: Dict[str, Any], dur: float, kind: str) -> str:
    """One card's scene body; times are seconds from the card's start."""
    t = c["type"]
    out_at = max(0.4, dur - 0.4)
    var = "--out:%.3fs;--end:%.3fs" % (out_at, max(0.0, dur - 0.034))
    b = c["box"]
    if t == "behind":
        from . import behind as BH
        return BH.html(c, dur, _box_style(b), _e)
    kick = '<p class="kicker">%s</p>' % _e(c["kicker"]) if c.get("kicker") else ""
    if t == "lower-third":
        hold = max(1.0, dur - 0.85 - 0.45)
        return ('<div class="box lt" style="%s"><div data-st="lower-third" data-variant="%s" data-position="none" '
                'data-name="%s" data-role="%s" data-at="0" data-hold="%.3f"></div></div>') % (
            _box_style(b), _e(c.get("variant") or "card"), _e(c["name"]), _e(c.get("role") or ""), hold)
    if t == "title":
        return ('<div class="box" style="%s;justify-content:flex-start"><div class="plate" style="%s">%s'
                '<h1 class="title" data-st="kinetic-type" data-style="mask" data-at="0.15">%s</h1>%s</div></div>') % (
            _box_style(b), var, kick, _e(c["title"]),
            '<p class="body muted">%s</p>' % _e(c["text"]) if c.get("text") else "")
    if t == "chapter":
        return ('<div class="scrim" style="%s"></div><div class="box chapter" style="%s;%s">%s'
                '<h2 class="title" data-st="kinetic-type" data-style="rise" data-at="0.2">%s</h2><div class="rule"></div></div>') % (
            var, _box_style(b), var, kick or '<p class="kicker">&nbsp;</p>', _e(c["title"]))
    if t == "quote":
        cues = [w["at"] for w in c.get("quote_words") or []]
        text = c.get("text") or c["said"]
        n = len(text.split())
        use_cues = cues and len(cues) == n
        return ('<div class="box" style="%s;justify-content:flex-start"><div class="plate" style="%s">'
                '<div class="q-mark">“</div><p class="q-text" data-st="kinetic-type" data-style="rise" data-at="0"%s>%s</p>%s'
                '</div></div>') % (
            _box_style(b), var, (" data-cues='%s'" % json.dumps(cues)) if use_cues else ' data-at="0.1"', _e(text),
            '<div class="q-by">%s</div>' % _e(c["by"]) if c.get("by") else "")
    if t == "stat":
        dur_count = count_dur(c)
        return ('<div class="box stat" style="%s;justify-content:flex-start"><div class="plate" style="%s">%s'
                '<div data-st="count-up" data-value="%s" data-from="%s" data-decimals="%d" data-prefix="%s" data-suffix="%s" '
                'data-label="%s" data-dur="%.2f" data-at="0.1" data-align="left"></div>%s</div></div>') % (
            _box_style(b), var, kick, _e(c["value"]), _e(c.get("from", 0)), int(c.get("decimals") or 0),
            _e(c.get("prefix") or ""), _e(c.get("suffix") or ""), _e(c.get("label") or ""), dur_count,
            '<p class="note">%s</p>' % _e(c["source_note"]) if c.get("source_note") else "")
    if t == "list":
        rows = "".join('<div class="li" style="--at:%.3fs"><span class="li-n">%d</span><span class="li-t">%s</span></div>'
                       % (it["at"] - c["start"], k + 1, _e(it["text"])) for k, it in enumerate(c["items_resolved"]))
        return ('<div class="box" style="%s;justify-content:flex-start"><div class="plate" style="%s">%s%s'
                '<div class="list-items">%s</div></div></div>') % (
            _box_style(b), var, kick, '<h3 class="title" style="font-size:calc(var(--u)*var(--s-listtitle))">%s</h3>' % _e(c["title"])
            if c.get("title") else "", rows)
    if t == "panel":
        reg = c["region"]
        edge = ""
        if kind == "wide":
            ex = reg["x"] + reg["w"] if c["side"] == "left" else reg["x"]
            edge = '<div class="panel-edge" style="left:calc(%s - 0.25cqmin);top:0;width:0.5cqmin;height:100%%;%s"></div>' % (
                _pct(ex), var)
        else:
            edge = '<div class="panel-edge" style="left:0;top:calc(%s - 0.25cqmin);width:100%%;height:0.5cqmin;%s"></div>' % (
                _pct(reg["y"] + reg["h"]), var)
        rows = "".join('<div class="li" style="--at:%.3fs"><span class="li-n">%d</span><span class="li-t">%s</span></div>'
                       % (it["at"] - c["start"], k + 1, _e(it["text"])) for k, it in enumerate(c["items_resolved"]))
        body = '<p class="body">%s</p>' % _e(c["body"]) if c.get("body") else ""
        stat = ""
        if c.get("value") is not None:
            stat = ('<div class="stat" style="margin-top:calc(var(--u)*2)"><div data-st="count-up" data-value="%s" '
                    'data-decimals="%d" data-prefix="%s" data-suffix="%s" data-label="%s" data-dur="1.4" data-at="0.4" '
                    'data-align="left"></div></div>') % (_e(c["value"]), int(c.get("decimals") or 0), _e(c.get("prefix") or ""),
                                                        _e(c.get("suffix") or ""), _e(c.get("label") or ""))
        return ('<div class="panel-bg" style="%s;%s"></div>%s<div class="box panel" style="%s;%s">%s'
                '<h2 class="title" data-st="kinetic-type" data-style="mask" data-at="0.15">%s</h2>%s%s%s%s</div>') % (
            _box_style(reg), var, edge, _box_style(b), var, kick, _e(c["title"]), body, stat,
            '<div class="list-items">%s</div>' % rows if rows else "",
            '<p class="note">%s</p>' % _e(c["source_note"]) if c.get("source_note") else "")
    raise ShowtimeError("unknown card type %r" % t)


def reel_plan(cards: List[Dict[str, Any]], fps: Fraction) -> List[Dict[str, Any]]:
    """Each card's place in the reel: frame-exact offset and frame count (cards back to back)."""
    f = float(fps)
    out, at = [], 0
    for c in cards:
        n = max(1, int(round((c["end"] - c["start"]) * f)))
        out.append({"card": c, "offset_frames": at, "frames": n, "offset": float(Fraction(at) / fps),
                    "dur": float(Fraction(n) / fps)})
        at += n
    return out


def page(cards: List[Dict[str, Any]], width: int, height: int, fps: Fraction, look: Dict[str, Any],
         lang: str = "en") -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    """(index.html, showtime.json, reel plan) of the card reel."""
    plan = reel_plan(cards, fps)
    kind = aspect_kind(width, height)
    scenes = []
    for p in plan:
        c = p["card"]
        scenes.append('<section class="scene card card-%s" data-start="%.4f" data-dur="%.4f">%s</section>' % (
            c["type"], p["offset"], p["dur"], _card_html(c, p["dur"], kind)))
    head_look = ""
    sig = look.get("sig")
    if sig is not None:
        from ..variety import signatures as sigs
        head_look = sigs.block(sig, "dom")
    doc = """<!doctype html>
<html lang="%s">
<head>
<meta charset="utf-8">
<title>showtime: talking-head cards (generated by edit render; do not edit)</title>
<script src="/_st/stage.js"></script>
<link rel="stylesheet" href="/_st/themes/bold.css">
<script type="module" src="/_st/components/index.js"></script>
<style>%s</style>
%s</head>
<body data-overlay>
<div class="stage">
%s
</div>
</body>
</html>
""" % (_e(lang), css(any(c["type"] == "behind" for c in cards)), head_look, "\n".join(scenes))
    total = float(Fraction(sum(p["frames"] for p in plan)) / fps)
    cfg = {"title": "cards", "width": int(width), "height": int(height), "fps": float(fps),
           "duration": round(total, 6), "background": "#000000", "overlay": True, "poster": None}
    return doc, cfg, plan


def render_reel(cards: List[Dict[str, Any]], width: int, height: int, fps: Fraction, look: Dict[str, Any],
                work: Path, *, preview: bool = False, lang: str = "en", workers: int = 2) -> Tuple[Path, List[Dict[str, Any]]]:
    """Render the card reel once (QuickTime Animation, alpha) and cache it by its content. Returns
    (reel file, plan)."""
    doc, cfg, plan = page(cards, width, height, fps, look, lang)
    brand_kit = look.get("brand")
    key = hashlib.sha256(json.dumps([REEL_REV, doc, cfg, bool(brand_kit), str(sorted((brand_kit or {}).items()))
                                     if brand_kit else ""], sort_keys=True, default=str).encode()).hexdigest()[:16]
    proj = ensure_dir(work / ("reel-%s" % key))
    # three folders under the project, so the render never takes the EDL's job for its own (enclosingJob looks
    # four levels up) and never becomes the job's latest final
    out = proj / "out" / "reel.mov"
    if out.is_file() and (proj / "done.json").is_file():
        return out, plan
    (proj / "index.html").write_text(doc, encoding="utf-8", newline="\n")
    write_json(proj / "showtime.json", cfg)
    if brand_kit is not None:
        from ..brand.apply import apply_project
        apply_project(proj, brand_kit, fill=False)
    ensure_dir(out.parent)
    launcher = Path(__file__).resolve().parent.parent / "launcher.py"
    cmd = [sys.executable, str(launcher), "render", str(proj), "-o", str(out), "--alpha", "animation", "--json",
           "--quiet", "--workers", str(max(1, workers)), "--poster", "none"]
    info("cards: rendering %d card(s) with alpha (%.1f s of graphics%s)" % (len(cards), cfg["duration"],
                                                                              ", preview size" if preview else ""))
    cp = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
    if cp.returncode != 0 or not out.is_file():
        tail = "\n".join((cp.stderr or cp.stdout or "").strip().splitlines()[-8:])
        raise ShowtimeError("the cards could not be rendered:\n%s" % tail,
                            hint="the generated page is %s; `showtime check %s` shows what it needs" % (
                                proj / "index.html", proj))
    write_json(proj / "done.json", {"cards": len(cards), "duration": cfg["duration"], "file": str(out)})
    return out, plan


def overlays_for(reel: Path, plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Internal overlay entries (edl.normalize's shape) that place each card of the reel at its output time."""
    from . import util as U
    pr = U.probe(reel)
    out = []
    for p in plan:
        c = p["card"]
        out.append({"index": "card%d" % c["index"], "file": reel, "image": False, "probe": pr, "start": c["start"],
                    "duration": p["dur"], "offset": p["offset"], "position": "full", "x": None, "y": None,
                    "width": None, "height": None, "scale": None, "opacity": 1.0, "fade": 0.0, "margin": 0.0,
                    "fit": "cover", "audio": False, "volume_db": 0.0, "duck_db": None, "card": c["index"]})
    return out


def caption_zones(cards: List[Dict[str, Any]], width: int, height: int,
                  plan: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Where the captions move. While a panel (or a 9:16 split) is up: in 16:9 they stay in their band but centre
    under the speaker's half (kept inside the frame); in 9:16 (or square) they sit in the panel just above the
    seam, never over the speaker. Elsewhere the caption_plan's zones keep them off the face. Earlier zones win."""
    out = []
    for c in cards:
        if c.get("caption_zone"):
            out.append(dict(c["caption_zone"]))
        if not c.get("region"):
            continue
        if aspect_kind(width, height) == "wide":
            sp = c.get("speaker") or {"x": 0.5, "w": 0.5}
            out.append({"start": c["start"], "end": c["end"], "align": 2, "x": sp["x"] + sp["w"] / 2.0})
        else:
            out.append({"start": c["start"], "end": c["end"], "align": 2, "y": SEAM_CAPTION_Y})
    return out + list((plan or {}).get("zones") or [])

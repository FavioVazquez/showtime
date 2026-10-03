"""Burned-in captions (ASS for libass) and subtitle files (SRT / VTT).

Styles
  bold-pop    1-3 heavy uppercase words, active word pops in an accent colour
              (karaoke). Short-form / social default.
  clean       sentence-case lines (max 2), soft shadow, fades. Explainers,
              interviews, YouTube.
  boxed       words on a translucent plate, active word tinted. Busy or bright
              footage where outlines are not enough.
  minimal     small, quiet, no outline. Calm or premium pieces.
  cinematic   serif lower-third lines with slow fades. Documentary / story.

Grouping rules (all styles): break at sentence ends, at a comma followed by a
pause, at pauses >= the style's gap, on speaker change, and at the style's
word/character/duration caps; the word cap tightens when speech is fast
(> 3.5 words/s -> 2 words, > 2.5 -> 3). A group does not end on a weak word
(FUNCTION_WORDS: "the", "to", "before", "is"...): it moves to the next group, or
that group's first word moves back, when both fit and neither flashes. One-word
groups merge into a neighbour when they fit. A group shows from its first word (minus a short
lead) until its last word ends (plus a tail), never overlapping the next.
Word timings are never altered, only group in/out. Groups shorter than the
style's `min_show` (0.7 s for sentence styles, 0.4 s for karaoke) are merged
into a neighbour instead of flashing by; a sentence styles' tail of 3 words or
fewer joins the cue before it when both fit; a cue starting just after a cut
(`cuts`) starts on the cut. Captions made from an .srt/.vtt keep its cues
(restyled, never regrouped), in the ASS and the sidecars alike.

Readability limits come from st.captions_rules (the numbers `showtime qa`
checks): a line never exceeds 42 characters (32 on vertical video; a group
only takes a word when its lines still fit that cap), and a
group of 3+ words stays on screen long enough to read at <= 20 characters/s
(it borrows free time before/after itself, else it is split in two).
Karaoke styles write one ASS event per group (the active word is animated
inside it), so each event is exactly the text on screen.

Placement uses PlayResX/Y equal to the video size and aspect-aware safe
zones (vertical video keeps captions above the bottom ~25 % where platform UI
sits and away from the right-side action rail).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import captions_rules as R
from ..common import ShowtimeError, warn
from . import util as U

STYLES: Dict[str, Dict[str, Any]] = {
    "bold-pop": {
        "font": "anton", "bold": False, "upper": True, "size": {"portrait": 0.105, "square": 0.092, "landscape": 0.08},
        "max_words": 3, "max_lines": 1, "chars": {"portrait": 18, "square": 20, "landscape": 26},
        "max_dur": 2.2, "gap": 0.25, "lead": 0.04, "tail": 0.12, "min_dur": 0.3, "karaoke": True,
        "color": "#FFFFFF", "highlight": "#FFE500", "outline": 0.075, "shadow": 0.03, "back": "#000000",
        "back_alpha": 0.45, "border": 1, "pop": 1.1, "fade": (40, 60), "spacing": 0.02,
        "margin_v": {"portrait": 0.30, "square": 0.18, "landscape": 0.14},
        "strip_punct": ".,;:", "density": True,
    },
    "clean": {
        "font": "inter", "bold": True, "upper": False, "size": {"portrait": 0.052, "square": 0.05, "landscape": 0.046},
        "max_words": 12, "max_lines": 2, "chars": {"portrait": 26, "square": 30, "landscape": 42},
        "max_dur": 6.0, "gap": 0.6, "lead": 0.08, "tail": 0.45, "min_dur": 0.8, "karaoke": False,
        "color": "#FFFFFF", "highlight": None, "outline": 0.05, "shadow": 0.035, "back": "#000000",
        "back_alpha": 0.55, "border": 1, "fade": (120, 100), "spacing": 0.0,
        "margin_v": {"portrait": 0.27, "square": 0.10, "landscape": 0.075},
        "strip_punct": "", "density": False,
    },
    "boxed": {
        "font": "inter", "bold": True, "upper": False, "size": {"portrait": 0.058, "square": 0.054, "landscape": 0.05},
        "max_words": 6, "max_lines": 2, "chars": {"portrait": 22, "square": 26, "landscape": 34},
        "max_dur": 3.5, "gap": 0.4, "lead": 0.06, "tail": 0.25, "min_dur": 0.5, "karaoke": True,
        "color": "#FFFFFF", "highlight": "#7CF3FF", "outline": 0.28, "shadow": 0.0, "back": "#000000",
        "back_alpha": 0.35, "border": 3, "plate": True, "pop": 1.0, "fade": (60, 60), "spacing": 0.0,
        "margin_v": {"portrait": 0.28, "square": 0.12, "landscape": 0.08},
        "strip_punct": "", "density": True,
    },
    "minimal": {
        "font": "inter", "bold": False, "upper": False, "size": {"portrait": 0.04, "square": 0.038, "landscape": 0.034},
        "max_words": 10, "max_lines": 2, "chars": {"portrait": 30, "square": 34, "landscape": 48},
        "max_dur": 5.0, "gap": 0.6, "lead": 0.08, "tail": 0.4, "min_dur": 0.8, "karaoke": False,
        "color": "#F5F5F5", "highlight": None, "outline": 0.0, "shadow": 0.06, "back": "#000000",
        "back_alpha": 0.4, "border": 1, "fade": (150, 150), "spacing": 0.01, "blur": 2,
        "margin_v": {"portrait": 0.25, "square": 0.08, "landscape": 0.06},
        "strip_punct": "", "density": False,
    },
    "cinematic": {
        "font": "instrument-serif", "bold": False, "upper": False,
        "size": {"portrait": 0.062, "square": 0.06, "landscape": 0.056},
        "max_words": 10, "max_lines": 2, "chars": {"portrait": 26, "square": 32, "landscape": 44},
        "max_dur": 5.5, "gap": 0.7, "lead": 0.12, "tail": 0.5, "min_dur": 1.0, "karaoke": False,
        "color": "#F5EFE6", "highlight": None, "outline": 0.0, "shadow": 0.05, "back": "#000000",
        "back_alpha": 0.25, "border": 1, "fade": (250, 250), "spacing": 0.02, "blur": 3,
        "margin_v": {"portrait": 0.26, "square": 0.1, "landscape": 0.085},
        "strip_punct": "", "density": False,
    },
}
ALIASES = {"bold": "bold-pop", "pop": "bold-pop", "karaoke": "bold-pop", "clean-sentence": "clean",
           "sentence": "clean", "box": "boxed", "cinematic-lower": "cinematic", "lower-third": "cinematic",
           "subtle": "minimal"}
SENT_END = re.compile(r"[.!?…]['\")\]]*$")
# words a caption or a line should not end on (they lean on what follows: "empty lines before" /
# "sorting"): English plus the commonest Spanish, French, Portuguese and German function words. The
# runtime caption component (runtime/components/captions.js WEAK_WORDS) uses the same list.
FUNCTION_WORDS = set((
    "a an the to of in on at by for with from into onto over under about than as and or but nor if that "
    "because before after while until is are was were be been am will would can could should has have had "
    "do does did not no very my your our its their his her this these those each every some any "
    "de del la el los las un una y o en con por para que al lo su sus es "
    "le les des du et au aux une sur pour avec est "
    "os um uma e do da dos das no na com "
    "der die das den dem ein eine und zu im mit von für ist").split())
CLAUSE_END = re.compile(r"[,;:—–]['\")\]]*$")


def is_weak(text: str) -> bool:
    """True when a caption or line should not end on this word (a function word, no punctuation after it)."""
    t = str(text or "").strip()
    if SENT_END.search(t) or CLAUSE_END.search(t):
        return False
    return re.sub(r"^[\W_]+|[^\w']+$", "", t.lower()) in FUNCTION_WORDS


def style_names() -> List[str]:
    return list(STYLES)


def get_style(name: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    key = ALIASES.get((name or "bold-pop").lower(), (name or "bold-pop").lower())
    if key not in STYLES:
        raise ShowtimeError("unknown caption style %r" % name, hint="styles: " + ", ".join(STYLES))
    st = dict(STYLES[key])
    st["name"] = key
    for k, v in (overrides or {}).items():
        if v is None or k in ("style",):
            continue
        st[k] = v
    return st


def orientation(w: int, h: int) -> str:
    r = h / float(w)
    return "portrait" if r > 1.3 else ("square" if r >= 0.77 else "landscape")


def _pick(v: Any, orient: str) -> Any:
    return v[orient] if isinstance(v, dict) else v


# --------------------------------------------------------------------------
# Grouping
# --------------------------------------------------------------------------

def display_words(words: List[Dict[str, Any]], lang: str = "en", keep_fillers: bool = False) -> List[Dict[str, Any]]:
    out = []
    for w in words:
        if w.get("type", "word") != "word":
            continue
        t = str(w.get("text", "")).strip()
        if not t or re.fullmatch(r"[\W_]+", t):
            continue
        if not keep_fillers and U.is_filler(t, lang):
            continue
        out.append(w)
    return out


def fits_lines(texts: List[str], per_line: int, max_lines: int) -> bool:
    """True when the words wrap into at most `max_lines` lines of `per_line` characters (greedy
    wrapping gives the fewest lines, so a balanced split within the limit then exists too).
    A single word longer than a line counts as one line: it cannot be broken."""
    lines, cur = 1, -1
    for t in texts:
        n = len(t)
        if cur < 0:
            cur = n
        elif cur + 1 + n <= per_line:
            cur += 1 + n
        else:
            lines += 1
            cur = n
    return lines <= max(1, int(max_lines))


def _fits(words: List[Dict[str, Any]], st: Dict[str, Any], max_chars: int) -> bool:
    """A group's words fit the style's lines (max_chars = characters per line x lines)."""
    lines = max(1, int(st["max_lines"]))
    return fits_lines([str(w["text"]).strip() for w in words], max_chars // lines, lines)


def group_words(words: List[Dict[str, Any]], st: Dict[str, Any], orient: str,
                readable: bool = True) -> List[Dict[str, Any]]:
    """Words -> caption groups [{words, start, end}] (see the module docstring for the rules).
    readable=False skips the reading-speed pass (fit_reading_speed)."""
    max_chars = int(_pick(st["chars"], orient)) * int(st["max_lines"])
    groups: List[List[Dict[str, Any]]] = []
    cur: List[Dict[str, Any]] = []

    def cap_at(i: int) -> int:
        cap = int(st["max_words"])
        if not st.get("density"):
            return cap
        t0 = words[i]["start"]
        n = sum(1 for w in words if t0 - 1.0 <= w["start"] <= t0 + 1.0)
        rate = n / 2.0
        if rate > 3.5:
            return min(cap, 2)
        if rate > 2.5:
            return min(cap, 3)
        return cap

    for i, w in enumerate(words):
        if cur:
            prev = cur[-1]
            gap = w["start"] - prev["end"]
            # the line cap is per line (qa checks every line), not per group: 44+40 characters in two
            # lines can still need a 45-character line once the words are balanced
            brk = (gap >= st["gap"] or len(cur) >= cap_at(i) or not _fits(cur + [w], st, max_chars)
                   or w["end"] - cur[0]["start"] > st["max_dur"]
                   or (w.get("speaker") and prev.get("speaker") and w["speaker"] != prev["speaker"])
                   or bool(SENT_END.search(prev["text"]))
                   or (CLAUSE_END.search(prev["text"]) and (gap >= 0.15 or len(cur) >= 2)))
            if brk:
                groups.append(cur)
                cur = []
        cur.append(w)
    if cur:
        groups.append(cur)
    groups = _no_weak_ends(groups, st, max_chars)
    # merge orphans (single short word) into a neighbour when it fits
    merged: List[List[Dict[str, Any]]] = []
    for g in groups:
        if (merged and len(g) == 1 and len(merged[-1]) < int(st["max_words"]) + 1
                and g[0]["start"] - merged[-1][-1]["end"] < 0.25
                and not SENT_END.search(merged[-1][-1]["text"])
                and _fits(merged[-1] + g, st, max_chars)):
            merged[-1] = merged[-1] + g
        else:
            merged.append(g)
    out = []
    for g in merged:
        out.append({"words": g, "start": g[0]["start"], "end": g[-1]["end"]})
    _time_groups(out, st)
    if readable:
        out = fit_reading_speed(out, st)
    out = merge_short(out, st, max_chars)
    if int(st["max_lines"]) >= 2 and not st.get("karaoke"):
        out = merge_orphans(out, st, max_chars)
    return out


def _no_weak_ends(groups: List[List[Dict[str, Any]]], st: Dict[str, Any], max_chars: int) -> List[List[Dict[str, Any]]]:
    """A group should not end on a weak word ("empty lines before" / "sorting."): hand the word to the
    next group when that still fits, else take the next group's first word. Not across a real pause or
    a speaker change. Word timings never change."""
    cap = int(st["max_words"])

    def lasts(ws: List[Dict[str, Any]]) -> bool:   # what is left would not flash by
        return ws[-1]["end"] - ws[0]["start"] >= min_show(st)

    for i in range(len(groups) - 1):
        a, b = groups[i], groups[i + 1]
        for _ in range(2):
            if not a or not b or not is_weak(a[-1]["text"]) or b[0]["start"] - a[-1]["end"] >= st["gap"]:
                break
            if a[-1].get("speaker") and b[0].get("speaker") and a[-1]["speaker"] != b[0]["speaker"]:
                break
            if len(a) > 1 and len(b) <= cap and _fits([a[-1]] + b, st, max_chars) and lasts(a[:-1]):
                b.insert(0, a.pop())
            elif len(b) > 1 and len(a) < cap and _fits(a + [b[0]], st, max_chars) and lasts(b[1:]):
                a.append(b.pop(0))
            else:
                break
    return [g for g in groups if g]


def min_show(st: Dict[str, Any]) -> float:
    """Shortest time a caption may be on screen before it reads as a flash."""
    if st.get("min_show") is not None:
        return float(st["min_show"])
    return R.FLASH_S if st.get("karaoke") else 0.7


def _join(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    return {"words": a["words"] + b["words"], "start": a["start"], "end": max(a["end"], b["end"])}


def merge_short(groups: List[Dict[str, Any]], st: Dict[str, Any], max_chars: int) -> List[Dict[str, Any]]:
    """Merge groups on screen for less than min_show into a neighbour (preferring the same sentence),
    when the result fits the line budget. Word timings never change."""
    lim = min_show(st)
    word_cap = max(int(st["max_words"]), 2) + 2
    out = list(groups)
    for _ in range(len(out)):
        idx = next((i for i, g in enumerate(out) if g["end"] - g["start"] < lim - 1e-6
                    and not g.get("_stuck")), None)
        if idx is None:
            break
        g = out[idx]
        best, best_cost = None, None
        for j in (idx - 1, idx + 1):
            if not (0 <= j < len(out)):
                continue
            a, b = (out[j], g) if j < idx else (g, out[j])
            gap = b["words"][0]["start"] - a["words"][-1]["end"]
            if gap > 0.6:
                continue
            words = a["words"] + b["words"]
            if not _fits(words, st, max_chars) or len(words) > word_cap:
                continue
            if any(w.get("speaker") and words[0].get("speaker") and w["speaker"] != words[0]["speaker"] for w in words):
                continue
            cost = gap + (1.0 if SENT_END.search(a["words"][-1]["text"]) else 0.0) + 0.05 * len(words)
            if best_cost is None or cost < best_cost:
                best, best_cost = j, cost
        if best is None:
            g["_stuck"] = True
            continue
        lo = min(best, idx)
        out[lo:lo + 2] = [_join(out[lo], out[lo + 1])]
        _time_groups(out, st)
    for g in out:
        g.pop("_stuck", None)
    return out


def merge_orphans(groups: List[Dict[str, Any]], st: Dict[str, Any], max_chars: int) -> List[Dict[str, Any]]:
    """A sentence's tail of 3 words or fewer ("into a gas.") joins the cue before it when that cue is
    the same sentence, the pause is short and the joined cue fits and reads in time."""
    out: List[Dict[str, Any]] = []
    for g in groups:
        if out and len(g["words"]) <= 3 and len(out[-1]["words"]) >= 2:
            a = out[-1]
            gap = g["words"][0]["start"] - a["words"][-1]["end"]
            words = a["words"] + g["words"]
            text = group_text({"words": words}, st)
            if (gap < 0.35 and not SENT_END.search(a["words"][-1]["text"]) and _fits(words, st, max_chars)
                    and len(words) <= int(st["max_words"]) + 3
                    and R.readable(text, max(g["end"], a["end"]) - a["start"])):
                out[-1] = _join(a, g)
                continue
        out.append(g)
    if len(out) != len(groups):
        _time_groups(out, st)
    return out


def cue_groups(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One group per imported cue (words carry "cue"), at the cue's own times."""
    out: List[Dict[str, Any]] = []
    for w in words:
        if not out or out[-1]["cue"] != w.get("cue"):
            out.append({"cue": w.get("cue"), "words": [], "start": w["start"], "end": w["end"]})
        out[-1]["words"].append(w)
        out[-1]["end"] = max(out[-1]["end"], w["end"])
    return out


def snap_to_cuts(groups: List[Dict[str, Any]], cuts: List[float], after: float = 0.25, before: float = 0.1) -> int:
    """A cue that starts up to `after` s after a cut (or `before` s before it) starts on the cut, and the
    cue before it ends there, so no caption hangs over into the new shot. Returns how many moved."""
    moved = 0
    cs = sorted(float(c) for c in cuts or [] if c and c > 0)
    for i, g in enumerate(groups):
        for c in cs:
            if c - before <= g["start"] <= c + after and abs(g["start"] - c) > 1e-3:
                first = g["words"][0]["start"]
                if first < c - before:   # the cue's first word is spoken before the cut: leave it
                    continue
                g["start"] = c
                if i and groups[i - 1]["end"] > c:
                    groups[i - 1]["end"] = max(c, groups[i - 1]["words"][-1]["end"])
                moved += 1
                break
    return moved


def _time_groups(out: List[Dict[str, Any]], st: Dict[str, Any]) -> None:
    """In/out times: lead/tail, min duration, never overlap (in place)."""
    for i, g in enumerate(out):
        prev_end = out[i - 1]["end"] if i else 0.0
        nxt = out[i + 1]["words"][0]["start"] - st["lead"] if i + 1 < len(out) else None
        g["start"] = max(prev_end, g["words"][0]["start"] - st["lead"], 0.0)
        end = g["words"][-1]["end"] + st["tail"]
        if g["words"][-1]["end"] - g["start"] < st["min_dur"]:
            end = max(end, g["start"] + st["min_dur"])
        if nxt is not None:
            end = min(end, max(nxt, g["words"][-1]["end"]))
        g["end"] = max(end, g["words"][-1]["end"])


def group_text(g: Dict[str, Any], st: Dict[str, Any]) -> str:
    """The group's text as displayed (case/punctuation rules applied; lines joined by a space)."""
    return " ".join(_word_text(w, st) for w in g["words"])


def _stretch(out: List[Dict[str, Any]], st: Dict[str, Any], i: int) -> None:
    """Give group i the time it needs to be read, from free time after it, then before it."""
    g = out[i]
    need = R.min_seconds(group_text(g, st))
    if g["end"] - g["start"] >= need:
        return
    last = g["words"][-1]["end"]
    limit = out[i + 1]["start"] if i + 1 < len(out) else last + max(float(st["tail"]), 0.0) + 1.0
    g["end"] = max(g["end"], min(g["start"] + need, limit))
    if g["end"] - g["start"] < need:
        first = g["words"][0]["start"]
        floor = max(out[i - 1]["end"] if i else 0.0, first - 0.5, 0.0)
        g["start"] = min(g["start"], max(g["end"] - need, floor))


def _split_point(texts: List[str]) -> int:
    total = len(" ".join(texts))
    best, best_cost = 1, None
    for j in range(1, len(texts)):
        head = len(" ".join(texts[:j]))
        cost = (abs(head - (total - head - 1)) - (8 if CLAUSE_END.search(texts[j - 1]) else 0)
                + (8 if is_weak(texts[j - 1]) else 0))
        if best_cost is None or cost < best_cost:
            best, best_cost = j, cost
    return best


def fit_reading_speed(groups: List[Dict[str, Any]], st: Dict[str, Any], rounds: int = 6) -> List[Dict[str, Any]]:
    """Keep every group of 3+ words under the reading-speed limit (st.captions_rules.MAX_CPS).

    A group that is too fast first borrows free screen time after (then before)
    itself; when there is none it is split in two and both halves are timed
    again. Word timings never change and groups never overlap."""
    out = list(groups)
    for _ in range(rounds):
        for i in range(len(out)):
            _stretch(out, st, i)
        nxt: List[Dict[str, Any]] = []
        split = False
        for g in out:
            j = _split_point([_word_text(w, st) for w in g["words"]]) if len(g["words"]) >= 2 else 0
            # a split that leaves a half shorter than min_show would only trade a fast cue for a flash:
            # keep the group (qa then reports it honestly as caption_fast)
            halves_ok = j > 0 and (g["words"][j - 1]["end"] - g["words"][0]["start"] + float(st["tail"]) >= min_show(st)
                                   and g["words"][-1]["end"] - g["words"][j]["start"] + float(st["tail"]) >= min_show(st))
            if len(g["words"]) >= R.CPS_MIN_WORDS and halves_ok and not R.readable(group_text(g, st), g["end"] - g["start"]):
                nxt.append({"words": g["words"][:j], "start": g["words"][0]["start"], "end": g["words"][j - 1]["end"]})
                nxt.append({"words": g["words"][j:], "start": g["words"][j]["start"], "end": g["words"][-1]["end"]})
                split = True
            else:
                nxt.append(g)
        out = nxt
        if not split:
            break
        _time_groups(out, st)
    return out


def layout_lines(ws: List[Dict[str, Any]], texts: List[str], max_chars: int, max_lines: int) -> List[List[int]]:
    """Line layout for a group: the cue's own breaks (words marked "br", from an imported .srt/.vtt)
    when present, else balanced by split_lines."""
    brk = [i for i, w in enumerate(ws[:-1]) if w.get("br")]
    if brk and max_lines >= 2:
        rows, start = [], 0
        for i in brk[: max_lines - 1]:
            rows.append(list(range(start, i + 1)))
            start = i + 1
        rows.append(list(range(start, len(ws))))
        return rows
    return split_lines(texts, max_chars, max_lines)


def split_lines(texts: List[str], max_chars: int, max_lines: int) -> List[List[int]]:
    """Word indices per line, balanced by characters; no one-word orphan lines."""
    total = len(" ".join(texts))
    if max_lines <= 1 or total <= max_chars or len(texts) < 2:
        return [list(range(len(texts)))]
    best, best_cost = None, None
    for k in range(1, len(texts)):
        a = len(" ".join(texts[:k]))
        b = len(" ".join(texts[k:]))
        cost = abs(a - b) + (1000 if max(a, b) > max_chars else 0) + (30 if k == 1 or k == len(texts) - 1 else 0)
        last, nxt = texts[k - 1], texts[k]
        if is_weak(last):
            cost += 14          # "the / next line" reads badly; the balance can give a little
        if last[:1].isupper() and nxt[:1].isupper() and not SENT_END.search(last) and not CLAUSE_END.search(last):
            cost += 14          # keep names together ("Kennedy / Space Center")
        if CLAUSE_END.search(last):
            cost -= 6           # a comma is a natural break
        if best_cost is None or cost < best_cost:
            best, best_cost = k, cost
    return [list(range(best)), list(range(best, len(texts)))]


# --------------------------------------------------------------------------
# ASS
# --------------------------------------------------------------------------

def ass_color(hex_color: Optional[str], alpha: float = 0.0) -> str:
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except (ValueError, IndexError):
        raise ShowtimeError("invalid colour %r (use #RRGGBB)" % hex_color)
    a = int(round(max(0.0, min(1.0, alpha)) * 255))
    return "&H%02X%02X%02X%02X" % (a, b, g, r)


def _ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return "%d:%02d:%02d.%02d" % (h, m, s, cs)


def _esc(t: str) -> str:
    return t.replace("\\", "∖").replace("{", "(").replace("}", ")").replace("\n", " ")


def _word_text(w: Dict[str, Any], st: Dict[str, Any]) -> str:
    t = str(w["text"]).strip()
    if st.get("strip_punct"):
        t = t.rstrip(st["strip_punct"]) or t
    if st.get("upper"):
        t = t.upper()
    return _esc(t)


class _Measure:
    """Line widths as libass draws them: the font file scaled so ascender + descender = the ASS size."""

    def __init__(self, font_path: Optional[Path], size: int, spacing: float, fake_bold: bool) -> None:
        self.size, self.spacing, self.k = size, spacing, 1.04 if fake_bold else 1.0
        self.font = None
        try:
            from PIL import ImageFont
            probe = ImageFont.truetype(str(font_path), 100)
            asc, desc = probe.getmetrics()
            self.font = ImageFont.truetype(str(font_path), max(1, int(round(100.0 * size / max(1, asc + desc)))))
        except Exception:  # noqa: BLE001 - no font file or PIL: an average-width estimate
            self.font = None

    def width(self, text: str) -> float:
        if self.font is not None:
            w = float(self.font.getlength(text))
        else:
            w = 0.52 * self.size * len(text)
        return w * self.k + self.spacing * max(0, len(text) - 1)


def _plate(lines: List[str], meas: "_Measure", st: Dict[str, Any], width: int, height: int, align: int,
           ml: int, mr: int, mv: int) -> str:
    """One vector shape behind a whole caption (all its lines): a single outline, so a translucent plate
    has no darker bands where per-word or per-line boxes would overlap."""
    size = meas.size
    pad_x, pad_y = 0.3 * size, 0.14 * size
    n = len(lines)
    block = n * size
    if align in (7, 8, 9):
        top = mv
    elif align in (4, 5, 6):
        top = (height - block) / 2.0
    else:
        top = height - mv - block
    cx = (ml + (width - mr)) / 2.0
    rows = []
    for i, ln in enumerate(lines):
        half = meas.width(ln) / 2.0 + pad_x
        y0 = top + i * size - (pad_y if i == 0 else 0)
        y1 = top + (i + 1) * size + (pad_y if i == n - 1 else 0)
        rows.append((cx - half, cx + half, y0, y1))
    r = lambda v: int(round(v))  # noqa: E731
    pts = [(r(rows[0][0]), r(rows[0][2])), (r(rows[0][1]), r(rows[0][2]))]
    for i, (x0, x1, y0, y1) in enumerate(rows):   # right side, top to bottom
        if i:
            pts.append((r(x1), r(y0)))
        pts.append((r(x1), r(y1)))
    for i in range(n - 1, -1, -1):                 # left side, bottom to top
        x0, x1, y0, y1 = rows[i]
        pts.append((r(x0), r(y1)))
        pts.append((r(x0), r(y0)))
    uniq = [pts[0]] + [q for a, q in zip(pts, pts[1:]) if q != a]
    return "m %d %d l " % uniq[0] + " ".join("%d %d" % q for q in uniq[1:])


def to_ass(groups: List[Dict[str, Any]], st: Dict[str, Any], width: int, height: int, font_family: str,
           position: str = "bottom", font_path: Optional[Path] = None) -> str:
    orient = orientation(width, height)
    short = min(width, height)
    size = max(12, int(round(_pick(st["size"], orient) * short)))
    outline = round(st["outline"] * size, 1)
    shadow = round(st["shadow"] * size, 1)
    plate = bool(st.get("plate"))
    if plate:
        # the plate is drawn as one shape per caption (below); the text itself has no box
        outline, shadow = 0.0, 0.0
    if st.get("blur") and outline <= 0:
        # libass blurs the glyph fill itself when a style has no border, which leaves soft, grey text.
        # A thin dark border takes the blur instead: the letters stay sharp inside a soft halo.
        outline = max(1.0, round(0.025 * size, 1))
    mv = int(round(_pick(st["margin_v"], orient) * height))
    ml = int(round(0.06 * width))
    mr = int(round((0.15 if orient == "portrait" else 0.06) * width))
    align = {"bottom": 2, "middle": 5, "top": 8}.get(position, 2)
    if align == 8:
        mv = int(round((0.14 if orient == "portrait" else 0.07) * height))
    if align == 5:
        mv = 0
    # stay inside the safe box qa checks (4:5 counts as vertical there, with the platform UI rails)
    sl, stp, sr_, sb = R.safe_box(width, height)
    ml = max(ml, int(round(sl)) + 2)
    mr = max(mr, int(round(width - sr_)) + 2)
    if align == 2:
        mv = max(mv, int(round(height - sb)) + 4)
    elif align == 8:
        mv = max(mv, int(round(stp)) + 4)
    border = 1 if plate else int(st.get("border", 1))
    back = ass_color(st.get("back"), st.get("back_alpha", 0.5))
    outline_col = ass_color("#000000", 0.0) if border == 1 else back
    spacing = round(st.get("spacing", 0.0) * size, 1)
    header = [
        "[Script Info]", "; generated by showtime", "ScriptType: v4.00+", "PlayResX: %d" % width,
        "PlayResY: %d" % height, "WrapStyle: 2", "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        "Style: Cap,%s,%d,%s,%s,%s,%s,%d,0,0,0,100,100,%s,0,%d,%s,%s,%d,%d,%d,%d,1" % (
            font_family, size, ass_color(st["color"]), ass_color(st.get("highlight") or st["color"]), outline_col,
            back, -1 if st.get("bold") and st.get("_font_weight", 400) < 600 else 0, spacing, border, outline, shadow,
            align, ml, mr, mv),
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines: List[str] = []
    max_chars = int(_pick(st["chars"], orient))
    fade_in, fade_out = st.get("fade", (0, 0))
    blur = st.get("blur")
    hl = ass_color(st.get("highlight") or st["color"])
    pop = float(st.get("pop", 1.0))
    meas = _Measure(font_path, size, spacing, bool(st.get("bold")) and st.get("_font_weight", 400) < 600) if plate else None
    # plate colour (&HBBGGRR&) and its transparency, the same as the style's BackColour
    plate_fill = "\\1c&H%s&\\1a&H%02X&" % (ass_color(st.get("back"))[4:],
                                            int(round(max(0.0, min(1.0, st.get("back_alpha", 0.5))) * 255)))
    text_layer = 1 if plate else 0
    for gi, g in enumerate(groups):
        ws = g["words"]
        texts = [_word_text(w, st) for w in ws]
        # fade only where the screen is empty before/after (no flicker between back-to-back groups)
        gin = fade_in if gi == 0 or g["start"] - groups[gi - 1]["end"] >= 0.1 else 0
        gout = fade_out if gi == len(groups) - 1 or groups[gi + 1]["start"] - g["end"] >= 0.1 else 0
        layout = layout_lines(ws, texts, max_chars, int(st["max_lines"]))
        prefix = "{\\blur%s}" % blur if blur else ""
        if meas is not None:
            shape = _plate([" ".join(texts[j] for j in line) for line in layout], meas, st, width, height, align, ml, mr, mv)
            fad0 = "\\fad(%d,%d)" % (gin, gout) if (gin or gout) else ""
            lines.append("Dialogue: 0,%s,%s,Cap,,0,0,0,,{\\an7\\pos(0,0)\\bord0\\shad0%s%s\\p1}%s{\\p0}" % (
                _ass_time(g["start"]), _ass_time(g["end"]), plate_fill, fad0, shape))
        if st.get("karaoke") and len(ws) >= 1:
            # one event per group; each word turns to the highlight colour (and pops) while it is
            # spoken, via \\t transforms timed from the event start (ms)
            base_c = ass_color(st["color"])
            span = g["end"] - g["start"]

            def ms(t: float) -> int:
                return int(round(max(0.0, min(span, t - g["start"])) * 1000))

            tok: List[str] = []
            for i in range(len(ws)):
                a = 0 if i == 0 else ms(ws[i]["start"])
                b = None if i == len(ws) - 1 else ms(ws[i + 1]["start"])
                fx = "\\c%s" % base_c
                if a <= 0:
                    fx = "\\c%s" % hl
                else:
                    fx += "\\t(%d,%d,\\c%s)" % (a, a + 1, hl)
                if b is not None:
                    fx += "\\t(%d,%d,\\c%s)" % (b, b + 1, base_c)
                if pop > 1.001:
                    big, rest = int(round(pop * 100)) + 4, int(round(pop * 100))
                    if a <= 0:
                        fx += "\\fscx%d\\fscy%d\\t(0,70,\\fscx%d\\fscy%d)" % (big, big, rest, rest)
                    else:
                        fx += "\\fscx100\\fscy100\\t(%d,%d,\\fscx%d\\fscy%d)\\t(%d,%d,\\fscx%d\\fscy%d)" % (
                            a, a + 1, big, big, a + 1, a + 71, rest, rest)
                    if b is not None:
                        fx += "\\t(%d,%d,\\fscx100\\fscy100)" % (b, b + 1)
                tok.append("{%s}%s" % (fx, texts[i]))
            body = "\\N".join(" ".join(tok[j] for j in line) for line in layout)
            fad = "{\\fad(%d,%d)}" % (gin, gout) if (gin or gout) else ""
            lines.append("Dialogue: %d,%s,%s,Cap,,0,0,0,,%s%s%s" % (text_layer, _ass_time(g["start"]), _ass_time(g["end"]),
                                                                   prefix, fad, body))
        else:
            body = "\\N".join(" ".join(texts[j] for j in line) for line in layout)
            fad = "{\\fad(%d,%d)}" % (gin, gout) if (gin or gout) else ""
            lines.append("Dialogue: %d,%s,%s,Cap,,0,0,0,,%s%s%s" % (text_layer, _ass_time(g["start"]), _ass_time(g["end"]),
                                                                   prefix, fad, body))
    return "\n".join(header + lines) + "\n"


# --------------------------------------------------------------------------
# SRT / VTT
# --------------------------------------------------------------------------

def _srt_time(t: float, sep: str = ",") -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d%s%03d" % (h, m, s, sep, ms)


def subtitle_groups(words: List[Dict[str, Any]], width: int = 1920, height: int = 1080,
                    options: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Sidecar (SRT/VTT) grouping: sentence-case, 2 lines within qa's line and reading-speed limits.
    options: max_words / max_dur / gap / min_show from the caption command also apply here."""
    over = {k: v for k, v in (options or {}).items() if k in ("max_words", "max_dur", "gap", "min_show") and v}
    st = get_style("clean", dict({"tail": 0.3, "min_dur": 0.83, "max_dur": 7.0, "lead": 0.0}, **over))
    orient = orientation(width, height)
    st["chars"] = min(int(_pick(st["chars"], orient)), R.max_line_chars(width, height))
    return group_words(words, st, orient)


def to_srt(groups: List[Dict[str, Any]], max_chars: int = 42) -> str:
    out = []
    for i, g in enumerate(groups, 1):
        texts = [str(w["text"]).strip() for w in g["words"]]
        layout = layout_lines(g["words"], texts, max_chars, 2)
        body = "\n".join(" ".join(texts[j] for j in line) for line in layout)
        out.append("%d\n%s --> %s\n%s\n" % (i, _srt_time(g["start"]), _srt_time(g["end"]), body))
    return "\n".join(out)


def to_vtt(groups: List[Dict[str, Any]], max_chars: int = 42) -> str:
    out = ["WEBVTT", ""]
    for g in groups:
        texts = [str(w["text"]).strip() for w in g["words"]]
        layout = layout_lines(g["words"], texts, max_chars, 2)
        body = "\n".join(" ".join(texts[j] for j in line) for line in layout)
        out.append("%s --> %s\n%s\n" % (_srt_time(g["start"], "."), _srt_time(g["end"], "."), body))
    return "\n".join(out)


# --------------------------------------------------------------------------
# High level
# --------------------------------------------------------------------------

BURNED_RE = re.compile(r"""data-st\s*=\s*["'](?:caption-karaoke|captions)["']|\bF\.caption\s*\(""")


def _project_burns(d: Path) -> Optional[str]:
    """'<file> (<what>)' when the showtime project in `d` draws captions into the picture."""
    try:
        pages = sorted(d.glob("*.html"))[:12]
    except OSError:
        return None
    for f in pages:
        try:
            m = BURNED_RE.search(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if m:
            what = "F.caption" if m.group(0).startswith("F.") else re.sub(r".*[\"'](.+)[\"']", r"\1", m.group(0))
            return "%s (%s)" % (f, what)
    return None


def _edl_burns(path: Path) -> Optional[str]:
    import json
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cap = d.get("captions") if isinstance(d, dict) else None
    if cap and not (isinstance(cap, dict) and cap.get("style") in (None, "none")):
        return "%s (edit render burns %s captions)" % (path, cap.get("style") if isinstance(cap, dict) else cap)
    return None


def burned_captions(*paths: Any, levels: int = 5) -> Optional[str]:
    """Where the video these files belong to already burns captions into the picture, else None.

    Looks at each path's enclosing showtime project (a folder with showtime.json whose
    page uses caption-karaoke / data-st="captions" / F.caption), an EDL whose "captions"
    is set, and the enclosing job (job.json: its project folder(s) and latest EDL)."""
    import json
    seen = set()
    for raw in paths:
        if not raw:
            continue
        try:
            p = Path(raw).expanduser().resolve()
        except OSError:
            continue
        if p.suffix.lower() == ".json" and p.is_file() and p.name not in ("showtime.json", "job.json"):
            hit = _edl_burns(p) if '"ranges"' in p.read_text(encoding="utf-8", errors="replace")[:20000] else None
            if hit:
                return hit
        start = p if p.is_dir() else p.parent
        for d in [start] + list(start.parents)[:levels]:
            if d in seen or d.name == "showtime-out":
                break
            seen.add(d)
            if (d / "showtime.json").is_file():
                hit = _project_burns(d)
                if hit:
                    return hit
            if (d / "job.json").is_file():
                cands: List[Path] = []
                try:
                    job = json.loads((d / "job.json").read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    job = {}
                for k in ("project",):
                    v = (job.get("pointers") or {}).get(k)
                    if v:
                        cands.append(Path(v) if Path(v).is_absolute() else d / v)
                try:
                    cands += [x.parent for x in d.glob("*/showtime.json")]
                except OSError:
                    pass
                for c in cands:
                    if (c / "showtime.json").is_file():
                        hit = _project_burns(c)
                        if hit:
                            return hit
                edl = (job.get("outputs") or {}).get("edl") if isinstance(job.get("outputs"), dict) else None
                if edl and Path(edl).is_file():
                    hit = _edl_burns(Path(edl))
                    if hit:
                        return hit
                break
    return None


def build(words: List[Dict[str, Any]], out_path, *, style: str = "bold-pop", width: int = 1080, height: int = 1920,
          lang: str = "en", options: Optional[Dict[str, Any]] = None, srt: Optional[Path] = None,
          vtt: Optional[Path] = None, context: Optional[List[Any]] = None,
          burned_note: Optional[bool] = None, keep_cues: Optional[bool] = None,
          cuts: Optional[List[float]] = None) -> Dict[str, Any]:
    """Write captions for output-timeline `words`. Returns a report dict incl. the
    fonts folder libass needs (`fontsdir`).

    context: extra paths (the transcript, the EDL) used to notice a video that
    already burns captions; then a warning says the files written here are
    optional and the report gets `burned_elsewhere`. burned_note: None = auto
    (skipped for intermediates under a work/ folder), False = never, True = always check."""
    from .fontfiles import find_font, fonts_dir
    opts = dict(options or {})
    position = opts.pop("position", "bottom")
    keep_fillers = bool(opts.pop("fillers", False))
    font_name = opts.pop("font", None)
    st = get_style(style, {k: v for k, v in opts.items() if k in STYLES["bold-pop"] or k in ("blur", "min_show")})
    base_style = get_style(style)
    if "size" in opts and "chars" not in opts:
        # a bigger size fits fewer characters on a line (ASS lines do not wrap): scale the cap with it
        orient0 = orientation(width, height)
        k = float(_pick(base_style["size"], orient0)) / max(1e-6, float(_pick(st["size"], orient0)))
        st["chars"] = max(8, int(int(_pick(base_style["chars"], orient0)) * k))
    if font_name:
        st["font"] = font_name
    font = find_font(st["font"], bold=bool(st.get("bold")))
    dw = display_words(words, lang, keep_fillers)
    font, dw, glyph_notes = _fit_glyphs(font, dw, st, keep_emoji=bool(opts.get("emoji")))
    st["_font_weight"] = font.weight
    orient = orientation(width, height)
    line_cap = R.max_line_chars(width, height)
    st["chars"] = min(int(_pick(st["chars"], orient)), line_cap)
    if keep_cues is None:   # an imported .srt/.vtt keeps its cues (restyle only)
        keep_cues = bool(dw) and all(w.get("cue") is not None for w in dw)
    groups = cue_groups(dw) if keep_cues else group_words(dw, st, orient)
    snapped = snap_to_cuts(groups, cuts) if cuts else 0
    text = to_ass(groups, st, width, height, font.family, position, font_path=font.path)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    rep: Dict[str, Any] = {"ass": str(out), "style": st["name"], "groups": len(groups), "words": len(dw),
                           "font": font.family, "font_file": str(font.path), "fontsdir": str(fonts_dir([font])),
                           "size": [width, height]}
    if keep_cues:
        sub = cue_groups(display_words(words, lang, True))
    else:
        sub = subtitle_groups(display_words(words, lang, False), width, height,
                              {k: opts.get(k) for k in ("max_words", "max_dur", "gap", "min_show")})
    if cuts:
        snapped += snap_to_cuts(sub, cuts)
    if keep_cues:
        rep["kept_cues"] = True
    if snapped:
        rep["snapped_to_cuts"] = snapped
    if srt:
        Path(srt).write_text(to_srt(sub, line_cap), encoding="utf-8")
        rep["srt"] = str(srt)
    if vtt:
        Path(vtt).write_text(to_vtt(sub, line_cap), encoding="utf-8")
        rep["vtt"] = str(vtt)
    rep["timing"] = check_timing(groups, dw)
    rep.update(glyph_notes)
    out_res = out.resolve()
    if burned_note is None:
        burned_note = not any(d.name in ("work",) or d.name.endswith(".work") for d in out_res.parents)
    if burned_note:
        where = burned_captions(*(list(context or []) + [out_res, srt, vtt]))
        if where:
            rep["burned_elsewhere"] = where
            warn("captions: the video already burns captions: %s. The files written here are optional: "
                 "keep an .srt only for platforms that take a caption upload (YouTube, LinkedIn, X); "
                 "Reels, TikTok and Shorts need nothing more" % where)
    return rep


def _span(lo: int, hi: int) -> str:
    return "%s-%s" % (chr(lo), chr(hi))


EMOJI_RE = re.compile("[" + "".join(_span(a, b) for a, b in (
    (0x1F1E6, 0x1F1FF), (0x1F300, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0xFE0F, 0xFE0F), (0x200D, 0x200D),
    (0x1F3FB, 0x1F3FF))) + "]")


def _fit_glyphs(font, dw: List[Dict[str, Any]], st: Dict[str, Any], keep_emoji: bool = False):
    """Make sure libass can draw every caption character from the caption font's own files.

    A missing glyph makes libass fall back to a system font (different on every OS, or an empty
    box). Emoji are removed from burned captions unless options.emoji is set (libass draws them
    monochrome from whatever font the OS has); other missing characters switch to the setup's
    multi-subset copy of the family when that covers them, otherwise they are reported."""
    from .fontfiles import coverage, find_font, FONTSOURCE
    notes: Dict[str, Any] = {}
    removed = 0
    if not keep_emoji:
        kept = []
        for w in dw:
            t = str(w.get("text", ""))
            t2 = EMOJI_RE.sub("", t).strip()
            if t2 != t.strip():
                removed += 1
                if not t2 or re.fullmatch(r"[\W_]+", t2):
                    continue
                w = dict(w, text=t2)
            kept.append(w)
        dw = kept
    if removed:
        notes["emoji_removed"] = removed
        warn("captions: removed emoji from %d word(s) (burned-in emoji would come from each OS's own font; "
             "pass the emoji option to keep them)" % removed)
    text = "".join(str(w.get("text", "")) for w in dw)
    if st.get("upper"):
        text += text.upper()
    need = {ord(ch) for ch in text if not ch.isspace()}
    missing = need - coverage(font)
    if missing and font.key in FONTSOURCE:
        try:
            alt = find_font(font.key, bold=font.weight >= 600, package_only=True)
            if len(need - coverage(alt)) < len(missing):
                notes["font_switched"] = "%s -> setup copy (%d more characters)" % (font.path.name, len(missing) - len(need - coverage(alt)))
                font, missing = alt, need - coverage(alt)
        except ShowtimeError:
            pass
    if missing:
        chars = "".join(sorted(chr(c) for c in missing))[:40]
        notes["missing_glyphs"] = chars
        warn("captions: %s has no glyph for %r; libass would substitute a system font. Use a font that "
             "covers them (e.g. --font noto-sans-jp for Japanese) or edit the words" % (font.family, chars))
    return font, dw, notes


def check_timing(groups: List[Dict[str, Any]], words: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Every displayed word must be on screen while it is spoken; groups must
    not overlap. Returns counts (all zero = good)."""
    shown = {id(w) for g in groups for w in g["words"]}
    outside = 0
    for g in groups:
        for w in g["words"]:
            if w["start"] < g["start"] - 0.001 or w["end"] > g["end"] + 0.001:
                outside += 1
    overlaps = sum(1 for a, b in zip(groups, groups[1:]) if b["start"] < a["end"] - 0.001)
    return {"words_missing": sum(1 for w in words if id(w) not in shown), "words_outside_group": outside,
            "overlaps": overlaps, "min_group_s": round(min((g["end"] - g["start"] for g in groups), default=0), 3)}


def ass_from_subtitles(src, out_path, *, style: str = "clean", width: int = 1920, height: int = 1080,
                       options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Restyle an existing SRT/VTT as ASS (cue text kept as-is)."""
    tr = U.import_subtitles(src)
    return build(tr["words"], out_path, style=style, width=width, height=height,
                 options=dict(options or {}, fillers=True))

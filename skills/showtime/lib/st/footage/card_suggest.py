"""`showtime edit cards suggest`: candidate moments for talking-head cards, found in a transcript locally.

Suggestions only (the agent picks the few that carry the story); no model calls, numpy for the audio measure:

  stat         a number with a unit ("twenty two thousand miles", "40 %", "3 billion people")
  lower-third  "my name is ...", "I'm <Name> ...", "I am a <role>"
  list         list markers (first / second / finally, number one ...) and "X, Y and Z" enumerations
  quote        quotable sentences: 6-20 words, superlatives, contrast, conviction, said with stress
  chapter      topic shifts: a long pause in the recording, an opener (so, now, next, another ...), a new speaker
  title        the opening line
  emphasis     stressed words: louder and longer than the rest of their sentence (captions.emphasis)
  behind       the strongest of those stressed words, as a big word behind the speaker (a behind card)

With an EDL the words are the edit's (output times, cut words gone); with a transcript, the recording's.
Every suggestion carries a `say` phrase exactly as spoken, so it pastes into the EDL's `cards` unchanged.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import util as U
from .cards import NUM, SCALE, _canon, _toks

UNITS = {
    "percent", "miles", "mile", "kilometers", "kilometres", "km", "meters", "metres", "feet", "foot", "inches",
    "years", "year", "months", "days", "day", "hours", "hour", "minutes", "minute", "seconds", "second", "weeks",
    "times", "people", "users", "customers", "dollars", "euros", "pounds", "degrees", "tons", "tonnes", "kilograms",
    "kg", "pounds", "gigabytes", "megabytes", "terabytes", "gb", "mb", "tb", "x", "fold", "million", "billion",
    "trillion", "satellites", "countries", "languages", "missions", "planets", "stars", "species", "lives", "jobs",
    "mph", "kph", "watts", "kilowatts", "volts", "hertz", "pixels", "frames", "steps", "points", "cents",
}
MARKERS = {"first": 1, "firstly": 1, "second": 2, "secondly": 2, "third": 3, "thirdly": 3, "fourth": 4, "fifth": 5,
           "finally": 9, "lastly": 9, "next": 5}
OPENERS = ("so ", "now ", "next ", "let's ", "lets ", "moving on", "another ", "the next ", "the second ", "the other ",
           "but the ", "okay ", "ok ", "alright ", "all right ")
SUPER = {"most", "best", "first", "only", "never", "ever", "biggest", "greatest", "fastest", "largest", "every",
         "always", "whole", "entire", "comprehensive", "impossible", "everything", "nobody", "everyone", "nothing"}
CONVICTION = ("i think", "i believe", "we can", "we will", "the key", "what matters", "the point", "the truth",
              "i'm excited", "i am excited", "the reason", "that's why", "this means", "which means")
CONTRAST = {"not", "but", "instead", "rather", "although", "however"}
PLAIN = set("above below about there their which these those would could should being really going thing things "
            "something people every never always maybe where while other another little".split())
SENT_END = re.compile(r"[.!?…]['\")\]]*$")


def _clean(t: str) -> str:
    return re.sub(r"^[^\w$%]+|[^\w%]+$", "", str(t or ""))


def _sentences(words: List[Dict[str, Any]], gap: float = 0.7) -> List[List[int]]:
    out, cur = [], []
    for k, w in enumerate(words):
        if cur and float(w["start"]) - float(words[cur[-1]]["end"]) > gap:
            out.append(cur)
            cur = []
        cur.append(k)
        if SENT_END.search(str(w["text"]).strip()):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _phrase(words: List[Dict[str, Any]], a: int, b: int) -> str:
    return " ".join(_clean(words[k]["text"]) for k in range(a, b + 1)).strip()


def _from(words: List[Dict[str, Any]], k: int) -> float:
    return round(float(words[k]["start"]), 2)


# ------------------------------------------------------------------------------------------------ detectors

def stats(words: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    toks: List[str] = []
    owner: List[int] = []
    for k, w in enumerate(words):
        for t in _toks(w["text"]):
            toks.append(t)
            owner.append(k)
    canon = _canon(toks)
    out = []
    for j, (t, a, b) in enumerate(canon):
        if not re.fullmatch(r"\d+(\.\d+)?", t):
            continue
        val = float(t) if "." in t else int(t)
        unit, ub = None, b
        for nxt in canon[j + 1: j + 3]:
            if nxt[0] in UNITS:
                unit, ub = nxt[0], nxt[2]
                break
            if nxt[0] in ("of", "per", "a", "an", "the"):
                continue
            break
        is_year = isinstance(val, int) and 1800 <= val <= 2100 and unit is None
        if unit is None and (is_year or (isinstance(val, int) and val < 100)):
            continue
        wa, wb = owner[a], owner[ub]
        said = _phrase(words, wa, wb)
        # the label: the words after the figure up to the clause end (at most 6)
        lab = []
        for k in range(wb + 1, min(len(words), wb + 8)):
            txt = str(words[k]["text"]).strip()
            lab.append(_clean(txt))
            if re.search(r"[,.;:!?]$", txt):
                break
        suffix = "%" if unit == "percent" else (" " + unit if unit else "")
        card = {"type": "stat", "say": said, "value": val, "suffix": suffix,
                "label": " ".join(x for x in lab[:6] if x) or "?"}
        out.append({"at": _from(words, wa), "say": said, "why": "a number%s" % (" with a unit (%s)" % unit if unit else ""),
                    "card": card})
    return out[:limit]


def names(words: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    out = []
    n = len(words)
    low = [_clean(w["text"]).lower() for w in words]
    for k in range(n):
        name_at = None
        if low[k] == "name" and k >= 1 and low[k - 1] == "my" and k + 1 < n and low[k + 1] == "is":
            name_at = k + 2
            start = k - 1
        elif low[k] in ("i'm", "im") or (low[k] == "i" and k + 1 < n and low[k + 1] == "am"):
            j = k + (2 if low[k] == "i" else 1)
            if j < n and _clean(words[j]["text"])[:1].isupper() and low[j] not in ("i",):
                name_at, start = j, k
        if name_at is None or name_at >= n:
            continue
        parts = []
        j = name_at
        while j < n and len(parts) < 3 and _clean(words[j]["text"])[:1].isupper():
            parts.append(_clean(words[j]["text"]))
            if re.search(r"[,.;:!?]$", str(words[j]["text"]).strip()):
                break
            j += 1
        if not parts:
            continue
        role = []
        j2 = j + 1 if j < n else j
        if j2 < n and low[j2 - 1:j2 + 1] and j2 + 1 < n and low[j2] in ("a", "an", "the", "and", "i'm"):
            for k2 in range(j2, min(n, j2 + 9)):
                role.append(_clean(words[k2]["text"]))
                if re.search(r"[,.;:!?]$", str(words[k2]["text"]).strip()):
                    break
        said = _phrase(words, start, min(n - 1, name_at + len(parts) - 1))
        out.append({"at": _from(words, start), "say": said, "why": "the speaker says their name",
                    "card": {"type": "lower-third", "say": said, "name": " ".join(parts),
                             "role": " ".join(role) or "?"}})
    return out[:limit]


def lists(words: List[Dict[str, Any]], sents: List[List[int]], limit: int) -> List[Dict[str, Any]]:
    out = []
    # 1. markers at the start of a sentence or clause, two or more within 90 s
    hits = []
    for k, w in enumerate(words):
        t = _clean(w["text"]).lower()
        prev = str(words[k - 1]["text"]).strip() if k else "."
        starts = k == 0 or bool(re.search(r"[,.;:!?]$", prev)) or float(w["start"]) - float(words[k - 1]["end"]) > 0.4
        if t in MARKERS and starts and t != "next":
            hits.append(k)
        elif t == "number" and k + 1 < len(words) and _clean(words[k + 1]["text"]).lower() in ("one", "two", "three", "1", "2", "3"):
            hits.append(k)
    groups: List[List[int]] = []
    for k in hits:
        if groups and float(words[k]["start"]) - float(words[groups[-1][-1]]["start"]) < 90:
            groups[-1].append(k)
        else:
            groups.append([k])
    for g in groups:
        if len(g) < 2:
            continue
        items = []
        for k in g:
            end = min(len(words) - 1, k + 6)
            for j in range(k, end + 1):
                if re.search(r"[,.;:!?]$", str(words[j]["text"]).strip()) and j > k:
                    end = j
                    break
            say = _phrase(words, k, end)
            items.append({"text": say, "say": say})
        out.append({"at": _from(words, g[0]), "say": items[0]["say"], "why": "%d list markers" % len(g),
                    "card": {"type": "list", "say": items[0]["say"], "items": items}})
    # 2. enumerations inside one sentence: "X, Y, and Z"
    for s in sents:
        txt = [str(words[k]["text"]).strip() for k in s]
        commas = [i for i, t in enumerate(txt) if t.endswith(",")]
        ands = [i for i, t in enumerate(txt) if _clean(t).lower() in ("and", "or") and i > 0 and txt[i - 1].endswith(",")]
        if len(commas) < 2 or not ands:
            continue
        a = ands[-1]
        bounds = [i for i in commas if i < a]
        if len(bounds) < 2:
            continue
        # the parts: from after the comma before each one (the first starts after the clause opener)
        starts = [max(0, bounds[0] - 5)] + [b + 1 for b in bounds[:-1]] + [a + 1]
        ends = bounds + [len(s) - 1]
        items = []
        for st_, en in zip(starts[-len(bounds) - 1:], ends[-len(bounds) - 1:]):
            en = min(en, st_ + 6)
            say = _phrase(words, s[st_], s[en])
            if say:
                items.append({"text": say, "say": say})
        if len(items) >= 3:
            out.append({"at": _from(words, s[starts[-len(bounds) - 1]]), "say": items[0]["say"],
                        "why": "an enumeration of %d (X, Y and Z): shorten each item's text" % len(items),
                        "card": {"type": "list", "say": items[0]["say"], "items": items}})
    out.sort(key=lambda x: x["at"])
    return out[:limit]


def quotes(words: List[Dict[str, Any]], sents: List[List[int]], stress: Dict[int, float], limit: int) -> List[Dict[str, Any]]:
    scored = []
    for s0 in sents:
        s = list(s0)
        if len(s) > 14:
            # a pull-quote over ~14 words fails its own reading time: offer the sentence's last clause (its
            # payoff), at most 12 words, starting after a comma when one falls inside
            s = s[-12:]
            cut = [i for i, k in enumerate(s[:-1]) if str(words[k]["text"]).strip().endswith(",")]
            if cut and len(s) - cut[-1] - 1 >= 6:
                s = s[cut[-1] + 1:]
        n = len(s)
        if n < 6 or n > 14:
            continue
        text = " ".join(str(words[k]["text"]).strip() for k in s)
        low = text.lower()
        if any(U.is_filler(words[k]["text"]) for k in s):
            continue
        sc = 1.0 - abs(n - 12) / 12.0
        ws = {_clean(words[k]["text"]).lower() for k in s}
        sc += 1.0 * len(ws & SUPER) + 0.5 * len(ws & CONTRAST)
        sc += 0.6 * sum(1 for c in CONVICTION if c in low)
        sc += 0.4 * sum(1 for k in s if stress.get(k, 0) > 0)
        if text.endswith("!"):
            sc += 0.5
        scored.append((sc, s, text))
    scored.sort(key=lambda x: -x[0])
    out = []
    for sc, s, text in scored[:limit]:
        say = _phrase(words, s[0], s[-1])
        out.append({"at": _from(words, s[0]), "say": say, "why": "quotable line (score %.1f)" % sc,
                    "card": {"type": "quote", "say": say}})
    out.sort(key=lambda x: x["at"])
    return out


def chapters(words: List[Dict[str, Any]], sents: List[List[int]], limit: int) -> List[Dict[str, Any]]:
    out = []
    for i, s in enumerate(sents):
        if i == 0:
            continue
        k = s[0]
        prev = sents[i - 1][-1]
        gap = float(words[k].get("src_start", words[k]["start"])) - float(words[prev].get("src_start", words[prev]["start"])) \
            - (float(words[prev]["end"]) - float(words[prev]["start"]))
        if words[k].get("src") != words[prev].get("src"):
            gap = max(gap, 0.0)
        text = " ".join(_clean(words[j]["text"]) for j in s[:6]).lower() + " "
        why = []
        if gap >= 1.2:
            why.append("a %.1f s pause in the recording before it" % gap)
        if any(text.startswith(o) for o in OPENERS):
            why.append("an opener (%s)" % text.split()[0])
        if words[k].get("speaker") and words[prev].get("speaker") and words[k]["speaker"] != words[prev]["speaker"]:
            why.append("a new speaker")
        if not why:
            continue
        say = _phrase(words, s[0], s[min(len(s) - 1, 3)])
        out.append({"at": _from(words, k), "say": say, "why": ", ".join(why),
                    "card": {"type": "chapter", "say": say, "kicker": "Part %d" % (len(out) + 2), "title": "?"}})
    return out[:limit]


def title(words: List[Dict[str, Any]], sents: List[List[int]]) -> List[Dict[str, Any]]:
    if not sents:
        return []
    s = sents[0]
    say = _phrase(words, s[0], s[min(len(s) - 1, 4)])
    return [{"at": _from(words, s[0]), "say": say, "why": "the opening line",
             "card": {"type": "title", "say": say, "title": "?", "kicker": "?"}}]


# ------------------------------------------------------------------------------------------------ stress

def _audio_for(words: List[Dict[str, Any]], sources: Dict[str, Tuple[Path, int]]):
    """{source key: (samples, sr)} of each source's 16 kHz mono track (cached like edit cut's snapping audio)."""
    out = {}
    for key, (path, track) in sources.items():
        try:
            wav = U.cache_dir("transcripts") / ("%s.t%d.16k.wav" % (U.quick_hash(path), track))
            if not wav.is_file():
                U.extract_wav(path, wav, sr=16000, track=track)
            out[key] = U.load_audio(wav, sr=16000)
        except Exception:  # noqa: BLE001 - the stress measure is optional
            continue
    return out


def stress_scores(words: List[Dict[str, Any]], sents: List[List[int]], audio) -> Dict[int, float]:
    """Per word: dB above its sentence's median word level, plus how much longer it is than the sentence's
    usual length per letter (content words of 3+ letters only); > 0 means stressed."""
    import numpy as np
    from .captions import FUNCTION_WORDS
    out: Dict[int, float] = {}
    for s in sents:
        rows = []
        for k in s:
            w = words[k]
            key = w.get("src", "_")
            if key not in audio:
                continue
            x, sr = audio[key]
            a = float(w.get("src_start", w["start"]))
            d = float(w["end"]) - float(w["start"])
            seg = x[int(a * sr): int((a + d) * sr)]
            if len(seg) < sr * 0.04:
                continue
            db = 20 * np.log10(max(1e-6, float(np.sqrt(np.mean(seg.astype(np.float64) ** 2)))))
            letters = max(1, len(re.sub(r"\W", "", str(w["text"]))))
            rows.append((k, db, d / letters))
        if len(rows) < 4:
            continue
        med_db = float(np.median([r[1] for r in rows]))
        med_len = float(np.median([r[2] for r in rows]))
        for k, db, per in rows:
            t = _clean(words[k]["text"]).lower()
            # a sentence's first word starts loud by nature (the onset after a breath): not stress
            raw = str(words[k]["text"]).strip()
            acronym = len(t) >= 2 and _clean(raw).isupper()
            # only words that can carry a message: 5+ letters or an acronym, one word per token, not a common
            # verb or adverb ("call", "like", "above" stressed in passing are not the message)
            if k == s[0] or (len(t) < 5 and not acronym) or " " in raw or t in FUNCTION_WORDS or t in PLAIN \
                    or U.is_filler(t):
                continue
            out[k] = round((db - med_db) / 3.0 + (per / max(1e-3, med_len) - 1.0), 3)
    return out


def emphasis(words: List[Dict[str, Any]], stress: Dict[int, float], total: float, limit: int) -> List[Dict[str, Any]]:
    ranked = sorted(((v, k) for k, v in stress.items() if v > 0.6), reverse=True)
    picked: List[int] = []
    seen = set()
    for v, k in ranked:
        t = float(words[k]["start"])
        key = _clean(words[k]["text"]).lower()
        if key not in seen and all(abs(t - float(words[j]["start"])) > 6.0 for j in picked):
            picked.append(k)
            seen.add(key)
        if len(picked) >= max(1, min(limit, int(total / 8) + 1, 5)):
            break
    return [{"at": _from(words, k), "say": _clean(words[k]["text"]), "why": "stressed (score %.1f)" % stress[k],
             "card": None} for k in sorted(picked, key=lambda j: words[j]["start"])]


def _word(w: str) -> str:
    return w if w.isupper() else w.capitalize()


def behind(words: List[Dict[str, Any]], stress: Dict[int, float], limit: int) -> List[Dict[str, Any]]:
    """A stressed content word of 4-12 letters, at most three, 12 s apart: the word the speaker leans on, big
    behind them (a behind card; the render cuts the speaker out over it)."""
    ranked = sorted(((v, k) for k, v in stress.items() if v > 0.9), reverse=True)
    picked: List[int] = []
    for v, k in ranked:
        w = _clean(words[k]["text"])
        if not (4 <= len(w) <= 12 and w.isalpha()):
            continue
        if all(abs(float(words[k]["start"]) - float(words[j]["start"])) > 12.0 for j in picked):
            picked.append(k)
        if len(picked) >= min(3, limit):
            break
    return [{"at": _from(words, k), "say": _clean(words[k]["text"]), "why": "stressed (score %.1f), one word" % stress[k],
             "card": {"type": "behind", "say": _clean(words[k]["text"]), "text": _word(_clean(words[k]["text"]))}}
            for k in sorted(picked, key=lambda j: words[j]["start"])]


# ------------------------------------------------------------------------------------------------ entry points

def suggest(words: List[Dict[str, Any]], *, sources: Optional[Dict[str, Tuple[Path, int]]] = None,
            duration: Optional[float] = None,
            timeline: str = "source", origin: str = "", limit: int = 6) -> Dict[str, Any]:
    words = [w for w in words if w.get("type", "word") == "word" and str(w.get("text", "")).strip()]
    sents = _sentences(words)
    audio = _audio_for(words, sources) if sources else {}
    stress = stress_scores(words, sents, audio) if audio else {}
    total = float(duration) if duration else (float(words[-1]["end"]) if words else 0.0)
    out = {"source": origin, "timeline": timeline, "duration": round(total, 2), "words": len(words),
           "suggestions": {"title": title(words, sents), "lower-third": names(words, limit),
                           "stat": stats(words, limit), "list": lists(words, sents, limit),
                           "quote": quotes(words, sents, stress, limit), "chapter": chapters(words, sents, limit),
                           "emphasis": emphasis(words, stress, total, limit) if stress else [],
                           "behind": behind(words, stress, limit) if stress else []},
           "notes": []}
    if not audio:
        out["notes"].append("stressed words were not measured (no source audio)")
    return out


def from_transcript(path, *, audio: bool = True, limit: int = 6) -> Dict[str, Any]:
    p = Path(path).resolve()
    tr = U.load_transcript(p)
    words = [dict(w, src="_") for w in U.words_of(tr)]
    src = Path(tr.get("source") or "")
    sources = {"_": (src, int(tr.get("audio_track") or 0))} if audio and src.is_file() else None
    return suggest(words, sources=sources, timeline="source (the recording's own times)", origin=str(p), limit=limit,
                   duration=tr.get("duration"))


def from_edl(path, *, audio: bool = True, limit: int = 6) -> Dict[str, Any]:
    from . import edl as E
    ed = E.load(path)
    segs = E.plan(ed)
    trs = E.load_transcripts(ed, required=True)
    words = E.map_words(segs, trs, include_events=False)
    sources = {k: (v["path"], int(v.get("audio_track") or 0)) for k, v in ed["sources"].items()} if audio else None
    rep = suggest(words, sources=sources, timeline="output (this edit's times)", origin=str(path), limit=limit,
                  duration=E.total_duration(segs))
    if ed.get("cards"):
        rep["notes"].append("the EDL already has %d card(s)" % len(ed["cards"]))
    return rep


def format_text(rep: Dict[str, Any]) -> str:
    lines = ["card suggestions for %s (%s, %d words, %s s); pick the few that carry the story:" % (
        rep["source"], rep["timeline"], rep["words"], rep["duration"])]
    for kind, items in rep["suggestions"].items():
        if not items:
            continue
        lines.append("")
        lines.append("%s:" % kind)
        for it in items:
            lines.append("  %7.2fs  \"%s\"  (%s)" % (it["at"], it["say"], it["why"]))
            if it.get("card"):
                lines.append("            %s" % json.dumps(it["card"], ensure_ascii=False))
    emph = [it["say"] for it in rep["suggestions"].get("emphasis") or []]
    if emph:
        lines.append("")
        lines.append("caption emphasis (3-5 words that carry the message): \"captions\": {..., \"emphasis\": %s}"
                     % json.dumps(emph, ensure_ascii=False))
    for n in rep.get("notes") or []:
        lines.append("note: %s" % n)
    lines.append("")
    lines.append("a \"?\" is yours to fill (from the speaker's words or the source page); paste the cards into the EDL's "
                 "\"cards\", then `showtime edit check <edl>`")
    return "\n".join(lines)

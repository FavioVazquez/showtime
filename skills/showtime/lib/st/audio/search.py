"""Search the audio library catalog with filters and ranking.

Filters (all optional): text query, kind, mood, tags, bpm range, key
(compatible keys: same, relative major/minor, fifth up/down), duration range,
energy range, license list, source, category, loopable, rhythmic, tier.

Ranking = text match (id/title/tags/mood/group) + mood/tag overlap + bpm
closeness + duration fit + energy closeness + small quality priors
(analysed loudness, known bpm, low harshness for UI sounds). `distinct`
keeps one result per variant group so repeated cues don't sound identical.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..common import ShowtimeError
from . import dsp

LICENSE_ALIASES = {"cc0": {"CC0-1.0", "PDM-1.0"}, "pd": {"PDM-1.0", "CC0-1.0"}, "cc-by": {"CC-BY-4.0", "CC-BY-3.0"},
                   "ccby": {"CC-BY-4.0", "CC-BY-3.0"}, "by": {"CC-BY-4.0", "CC-BY-3.0"}}
MOOD_SYNONYMS = {
    "happy": ["bright", "uplifting", "bouncy", "positive", "cheerful"], "upbeat": ["bright", "driving", "bouncy", "uplifting"],
    "calm": ["calming", "relaxed", "calm", "soft", "peaceful"], "chill": ["relaxed", "calm", "cozy", "grooving"],
    "sad": ["somber", "emotional", "tender", "melancholic"], "epic": ["epic", "heroic", "intense", "driving"],
    "dark": ["dark", "eerie", "mysterious", "unnerving", "suspense", "tense"], "tense": ["suspenseful", "tense", "suspense", "intense"],
    "funny": ["humorous", "playful", "bouncy"], "playful": ["playful", "humorous", "bouncy", "light"],
    "corporate": ["bright", "calm", "positive", "clean", "uplifting"], "tech": ["modern", "driving", "bright", "grooving"],
    "inspiring": ["uplifting", "hopeful", "epic", "bright"], "mysterious": ["mysterious", "mystical", "eerie"],
    "action": ["action", "driving", "aggressive", "intense"], "groovy": ["grooving", "groovy", "funky"],
    "emotional": ["emotional", "somber", "tender", "hopeful", "reflective"], "retro": ["retro", "nostalgic", "8bit"],
}


def _set(v: Any) -> set:
    if v is None:
        return set()
    if isinstance(v, str):
        return {x.strip().lower() for x in re.split(r"[,\s]+", v) if x.strip()}
    return {str(x).strip().lower() for x in v if str(x).strip()}


def _range(v: Any) -> Tuple[Optional[float], Optional[float]]:
    """'100-130', '120', (100, 130), [None, 130] -> (lo, hi)."""
    if v is None or v == "":
        return None, None
    if isinstance(v, (int, float)):
        return float(v) * 0.94, float(v) * 1.06
    if isinstance(v, (list, tuple)):
        lo, hi = (list(v) + [None, None])[:2]
        return (float(lo) if lo is not None else None), (float(hi) if hi is not None else None)
    s = str(v).strip()
    m = re.match(r"^\s*(\d+(?:\.\d+)?)?\s*[-:]\s*(\d+(?:\.\d+)?)?\s*$", s)
    if m and (m.group(1) or m.group(2)):
        return (float(m.group(1)) if m.group(1) else None), (float(m.group(2)) if m.group(2) else None)
    try:
        f = float(s)
        return f * 0.94, f * 1.06
    except ValueError:
        raise ShowtimeError("bad range %r (use e.g. 100-130)" % v)


def compatible_keys(key: str) -> Dict[str, float]:
    """Key -> {compatible key: score} (same 1.0, relative 0.9, fifths 0.7)."""
    pc, mode = dsp.parse_key(key)
    out = {dsp.key_name(pc, mode): 1.0}
    rel = (pc + 9) % 12 if mode == "major" else (pc + 3) % 12
    out[dsp.key_name(rel, "minor" if mode == "major" else "major")] = 0.9
    for d in (7, 5):
        out.setdefault(dsp.key_name((pc + d) % 12, mode), 0.7)
    return out


def _norm_key(k: Optional[str]) -> Optional[str]:
    if not k:
        return None
    try:
        pc, mode = dsp.parse_key(k)
        return dsp.key_name(pc, mode)
    except ValueError:
        return None


_PARAMS = {"query", "kind", "mood", "tags", "bpm", "key", "min_dur", "max_dur", "duration", "energy", "license",
           "source", "category", "loopable", "rhythmic", "tier", "distinct", "exclude"}


def normalize_query(q: Dict[str, Any]) -> Dict[str, Any]:
    """Accept loose keys from JSON specs (min_dur, max-dur, dur, license: 'cc0,cc-by' ...)."""
    out: Dict[str, Any] = {}
    for k, v in (q or {}).items():
        kk = k.replace("-", "_").lower()
        if kk in ("q", "text", "query", "words"):
            kk = "query"
        elif kk in ("dur", "duration"):
            kk = "duration"
        if kk not in _PARAMS:
            raise ShowtimeError("unknown library search field %r (use: %s)" % (k, ", ".join(sorted(_PARAMS))))
        out[kk] = v
    return out


BED_TAGS = {"ambience", "ambient", "loop", "background", "room-tone", "roomtone", "bed", "drone", "atmosphere"}


def _bed_like(it: Dict[str, Any]) -> bool:
    """An sfx item that can serve as an ambience bed: at least 3 s and loopable or named/tagged as a loop."""
    if float(it.get("duration") or 0) < 3.0:
        return False
    hay = (it["id"] + " " + (it.get("title") or "")).lower()
    tags = {t.lower() for t in it.get("tags", [])}
    return bool(it.get("loopable")) or "loop" in hay or bool(tags & BED_TAGS)


def search(query: Optional[str] = None, kind: Any = None, mood: Any = None, tags: Any = None, bpm: Any = None,
           key: Optional[str] = None, min_dur: Optional[float] = None, max_dur: Optional[float] = None,
           duration: Optional[float] = None, energy: Any = None, license: Any = None, source: Any = None,
           category: Any = None, loopable: Optional[bool] = None, rhythmic: Optional[bool] = None,
           tier: Any = None, distinct: bool = False, limit: int = 20, catalog: Optional[dict] = None,
           exclude: Iterable[str] = ()) -> List[Dict[str, Any]]:
    from . import library
    cat = catalog or library.load_catalog()
    kinds = _set(kind)
    moods = _set(mood)
    mood_x = set(moods)
    for m in moods:
        mood_x |= set(MOOD_SYNONYMS.get(m, []))
    want_tags = _set(tags)
    lic: set = set()
    for l_ in _set(license):
        lic |= LICENSE_ALIASES.get(l_, {l_.upper()})
    sources = _set(source)
    cats = _set(category)
    tiers = _set(tier)
    blo, bhi = _range(bpm)
    elo, ehi = _range(energy) if energy is not None and not isinstance(energy, (int, float)) else \
        ((float(energy) - 0.2, float(energy) + 0.2) if energy is not None else (None, None))
    keys = compatible_keys(key) if key else {}
    words = [w for w in re.split(r"[^a-z0-9#]+", (query or "").lower()) if w]
    excl = set(exclude)
    results = []
    # an ambience search also finds beds catalogued as sfx (a 7 s water loop in a foley pack), ranked lower
    cross_bed = kinds == {"ambience"}
    for it in cat.get("items", []):
        if it["id"] in excl:
            continue
        k = it.get("kind")
        xkind = False
        if kinds and k not in kinds:
            if not (cross_bed and k == "sfx" and _bed_like(it)):
                continue
            xkind = True
        if lic and it.get("license", "").upper() not in {x.upper() for x in lic}:
            continue
        if sources and not any(it.get("source_id", "").startswith(s) for s in sources):
            continue
        if cats and (it.get("category") or "") not in cats:
            continue
        if tiers and (it.get("tier") or "") not in tiers:
            continue
        d = float(it.get("duration") or 0)
        if min_dur is not None and d < float(min_dur):
            continue
        if max_dur is not None and d > float(max_dur):
            continue
        if loopable is not None and bool(it.get("loopable")) != bool(loopable):
            continue
        if rhythmic is not None and bool(it.get("rhythmic")) != bool(rhythmic):
            continue
        ib = it.get("bpm")
        if (blo is not None or bhi is not None):
            if not ib:
                continue
            ok = any((blo is None or c >= blo) and (bhi is None or c <= bhi) for c in (ib, ib * 2, ib / 2))
            if not ok:
                continue
        ie = it.get("energy")
        if elo is not None and ie is not None and not (elo <= ie <= (ehi if ehi is not None else 1.0)):
            continue
        tagset = {t.lower() for t in it.get("tags", [])}
        moodset = {m.lower() for m in it.get("mood", [])}
        if want_tags and not (want_tags & tagset):
            # allow tag words to match inside ids/titles too
            hay = (it["id"] + " " + (it.get("title") or "")).lower()
            if not any(t in hay for t in want_tags):
                continue
        if moods and not (mood_x & (moodset | tagset)):
            continue
        score = 0.0
        why = []
        if words:
            hay_id = it["id"].lower()
            hay_title = (it.get("title") or "").lower()
            hits = 0
            for w in words:
                if w in tagset or w in moodset:
                    score += 3.0
                    hits += 1
                elif w in hay_title or w in hay_id or w in (it.get("group") or "").lower():
                    score += 2.0
                    hits += 1
                elif any(w in t for t in tagset):
                    score += 1.0
                    hits += 1
            if hits == 0:
                continue
            if hits == len(words):
                score += 2.0
            why.append("text %d/%d" % (hits, len(words)))
        if moods:
            ov = len(mood_x & (moodset | tagset))
            score += 1.5 * ov
            why.append("mood %d" % ov)
        if want_tags:
            score += 1.0 * len(want_tags & tagset)
        if ib and (blo is not None or bhi is not None):
            mid = ((blo or bhi) + (bhi or blo)) / 2
            best = min(abs(c - mid) for c in (ib, ib * 2, ib / 2))
            score += max(0.0, 2.0 - best / 10.0)
        if keys:
            nk = _norm_key(it.get("key"))
            if nk in keys:
                score += 2.0 * keys[nk]
                why.append("key %s" % nk)
            elif nk:
                score -= 0.5
        if duration is not None:
            target = float(duration)
            if k in ("music", "ambience"):
                score += 1.5 if d >= target else max(-2.0, -2.0 * (target - d) / max(target, 1)) + (1.0 if it.get("loopable") else 0.0)
            else:
                score += max(0.0, 1.5 - abs(d - target) / max(target, 0.3))
        if ie is not None and energy is not None:
            mid = ((elo or 0) + (ehi if ehi is not None else 1)) / 2
            score += max(0.0, 1.0 - abs(ie - mid) * 3)
        # priors
        if k in ("music",) and it.get("lufs") is not None:
            score += 0.2
        if it.get("harshness") == "high" and (it.get("category") in ("ui",) or "ui" in tagset):
            score -= 0.5
        if it.get("tier") == "generated" and not words and not moods:
            score -= 0.1
        if xkind:
            score -= 1.5
            why.append("an sfx loop (catalogued as sfx)")
        results.append({"id": it["id"], "score": round(score, 3), "why": why, "item": it})
    results.sort(key=lambda r: (-r["score"], r["id"]))
    if distinct:
        seen, out = set(), []
        for r in results:
            g = r["item"].get("group") or r["id"]
            if g in seen:
                continue
            seen.add(g)
            out.append(r)
        results = out
    return results[: max(1, int(limit))]


def row(r: Dict[str, Any]) -> str:
    it = r["item"]
    bits = [it.get("kind", "?"), "%.1fs" % float(it.get("duration") or 0)]
    if it.get("bpm"):
        bits.append("%.0f bpm" % float(it["bpm"]))
    if it.get("key"):
        bits.append(str(it["key"]))
    if it.get("hit") is not None and it.get("kind") in ("sfx", "voice"):
        bits.append("hit %.3fs" % float(it["hit"]))
    bits.append(it.get("license", "?"))
    mood = ",".join((it.get("mood") or [])[:3])
    return "%-52s %s%s" % (r["id"], "  ".join(bits), ("  [" + mood + "]") if mood else "")

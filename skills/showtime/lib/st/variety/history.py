"""Look history: what this machine's recent videos looked like, so the next one does not repeat them.

Stored in <SHOWTIME_HOME>/history/looks.json (the newest MAX_KEEP finished jobs). Nothing in it
leaves the machine: no command uploads it, and it holds only job names, paths and the look fields
of st.variety.look. A job is recorded when `showtime qa` passes (PASS or WARN) on its latest final,
or by hand with `showtime history add <job>`.

Opting out: `showtime history off` (a marker file in the history folder), or SHOWTIME_HISTORY=off in
the environment. `showtime history clear` deletes the file.

The repeat check compares a look with the last RECENT jobs, aspect by aspect (template, theme,
palette, type, transitions, camera, music, structure, tone), and for every repeat proposes two
concrete alternatives from what showtime has: runtime themes, their type pairs and palettes,
transitions from the catalog, camera verbs, catalog music from other shelves, other structures and
hooks, other tone presets.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..common import home, read_json, skill_dir, write_json
from . import look as L

SCHEMA = 1
MAX_KEEP = 50
RECENT = 5
PALETTE_NEAR = 60.0          # colour distance under which two colours count as the same
# aspects that make a video look the same; template and tone alone are notes
STRONG = ("theme", "palette", "type", "transitions", "camera", "music", "structure")
ASPECT_NAMES = {"template": "template", "theme": "theme (look)", "palette": "palette", "type": "type pair",
                "transitions": "transitions", "camera": "camera moves", "music": "music", "structure": "structure",
                "tone": "tone"}


# ------------------------------------------------------------------ storage

def folder() -> Path:
    """<SHOWTIME_HOME>/history (SHOWTIME_HISTORY_DIR overrides it; the tests use that)."""
    d = os.environ.get("SHOWTIME_HISTORY_DIR")
    return Path(os.path.expanduser(d)) if d else home() / "history"


def file() -> Path:
    return folder() / "looks.json"


def _off_marker() -> Path:
    return folder() / "OFF"


def enabled() -> Tuple[bool, str]:
    v = str(os.environ.get("SHOWTIME_HISTORY", "")).strip().lower()
    if v in ("0", "off", "false", "no"):
        return False, "SHOWTIME_HISTORY=%s" % v
    if _off_marker().is_file():
        return False, "turned off with `showtime history off`"
    return True, ""


def set_enabled(on: bool) -> Path:
    m = _off_marker()
    if on:
        if m.is_file():
            m.unlink()
    else:
        m.parent.mkdir(parents=True, exist_ok=True)
        m.write_text("look history is off; `showtime history on` turns it back on\n", encoding="utf-8")
    return m


def load() -> List[Dict[str, Any]]:
    d = read_json(file(), None) if file().is_file() else None
    if not isinstance(d, dict) or not isinstance(d.get("looks"), list):
        return []
    return [x for x in d["looks"] if isinstance(x, dict)]


def _save(looks: List[Dict[str, Any]]) -> Path:
    return write_json(file(), {"schema": SCHEMA, "about": "showtime look history (local only; `showtime history`)",
                               "looks": looks[-MAX_KEEP:]})


def _same_job(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    for k in ("job_path", "project"):
        if a.get(k) and b.get(k) and os.path.normcase(str(a[k])) == os.path.normcase(str(b[k])):
            return True
    return False


def record(look: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Add (or replace) one job's look. None when the history is off."""
    ok, _why = enabled()
    if not ok:
        return None
    import time
    look = dict(look, at=time.strftime("%Y-%m-%dT%H:%M:%S"))
    looks = [x for x in load() if not _same_job(x, look)]
    looks.append(look)
    _save(looks)
    return look


def record_job(job: Path) -> Optional[Dict[str, Any]]:
    ok, _why = enabled()
    if not ok:
        return None
    return record(L.job_look(Path(job)))


def clear(job: Optional[str] = None) -> int:
    """Remove every entry (job None) or the entries of one job (name or path). Returns how many."""
    looks = load()
    if job is None:
        n = len(looks)
        try:
            file().unlink()
        except OSError:
            pass
        return n
    key = str(job)
    keep = [x for x in looks if not (x.get("job") == key or os.path.normcase(str(x.get("job_path") or "")) ==
                                     os.path.normcase(str(Path(key).expanduser().resolve())))]
    _save(keep)
    return len(looks) - len(keep)


def recent(n: int = RECENT, exclude: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    looks = [x for x in load() if not (exclude and _same_job(x, exclude))]
    return looks[-n:][::-1]   # newest first


# ------------------------------------------------------------------ comparing

def _primary(tr: Dict[str, int]) -> Optional[str]:
    if not tr:
        return None
    return sorted(tr.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def _share(tr: Dict[str, int]) -> float:
    """How much of a video's handoffs its primary transition makes."""
    tot = float(sum(tr.values())) or 1.0
    return tr.get(_primary(tr) or "", 0) / tot


def _jacc(a: Sequence[str], b: Sequence[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / float(len(sa | sb)) if (sa or sb) else 0.0


def palette_match(a: Sequence[str], b: Sequence[str]) -> bool:
    a, b = [c for c in a if c][:4], [c for c in b if c][:4]
    if len(a) < 3 or len(b) < 3:
        return False
    hits = sum(1 for x in a if any(L.color_distance(x, y) < PALETTE_NEAR for y in b))
    return hits >= min(3, len(a))


def _structure_match(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    if not a.get("scenes") or a.get("scenes") != b.get("scenes"):
        return False
    da, db = a.get("durations") or [], b.get("durations") or []
    if da and db and len(da) == len(db):
        sa, sb = float(sum(da)) or 1.0, float(sum(db)) or 1.0
        return max(abs(x / sa - y / sb) for x, y in zip(da, db)) <= 0.06
    return bool(a.get("shape")) and a.get("shape") == b.get("shape")


def _music_match(a: List[Dict[str, Any]], b: List[Dict[str, Any]]) -> Optional[str]:
    ra = {m.get("ref") for m in a if m.get("ref") and m.get("ref") != "score:synth"}
    rb = {m.get("ref") for m in b if m.get("ref") and m.get("ref") != "score:synth"}
    same = sorted(ra & rb)
    if same:
        return "the same track (%s)" % ", ".join(same)
    sa = {m.get("shelf") for m in a if m.get("shelf")}
    sb = {m.get("shelf") for m in b if m.get("shelf")}
    if sa & sb:
        return "the same catalog shelf (%s)" % ", ".join(sorted(sa & sb))
    return None


def aspect_value(look: Dict[str, Any], aspect: str) -> str:
    v = look.get(aspect)
    if aspect == "palette":
        return " ".join((v or [])[:4])
    if aspect == "type":
        return " + ".join((v or [])[:2])
    if aspect == "transitions":
        tr = v or {}
        top = sorted(tr.items(), key=lambda kv: (-kv[1], kv[0]))
        return "%s-led (%s)" % (_primary(tr), ", ".join("%s x%d" % kv for kv in top[:3])) if tr else ""
    if aspect == "camera":
        return ", ".join(v or [])
    if aspect == "music":
        return ", ".join(m.get("ref", "") for m in (v or []))
    if aspect == "structure":
        st = v or {}
        if not st.get("scenes"):
            return ""
        d = st.get("durations")
        return "%s scenes%s%s" % (st["scenes"], " (%s)" % st["shape"] if st.get("shape") else "",
                                   ": " + " / ".join("%g" % x for x in d) + " s" if d else "")
    return str(v or "")


def repeats(look: Dict[str, Any], others: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """[{aspect, value, jobs, detail, strong}] for every aspect `look` shares with one of `others`."""
    out: List[Dict[str, Any]] = []

    def hit(aspect: str, o: Dict[str, Any], detail: str = "") -> None:
        for r in out:
            if r["aspect"] == aspect:
                if o.get("job") not in r["jobs"]:
                    r["jobs"].append(o.get("job") or "?")
                return
        out.append({"aspect": aspect, "value": aspect_value(look, aspect), "jobs": [o.get("job") or "?"],
                    "detail": detail, "strong": aspect in STRONG})

    for o in others:
        same_brand = bool(look.get("brand")) and look.get("brand") == o.get("brand")
        if look.get("template") and look.get("template") == o.get("template"):
            hit("template", o)
        if look.get("theme") and look.get("theme") == o.get("theme"):
            hit("theme", o)
        if not same_brand and palette_match(look.get("palette") or [], o.get("palette") or []):
            hit("palette", o)
        ta, tb = look.get("type") or [], o.get("type") or []
        if not same_brand and ta and tb and ta[0].lower() == tb[0].lower():
            hit("type", o)
        tra, trb = look.get("transitions") or {}, o.get("transitions") or {}
        if tra and trb and _primary(tra) == _primary(trb) and (
                _jacc(list(tra), list(trb)) >= 0.5 or min(_share(tra), _share(trb)) >= 0.5):
            hit("transitions", o)
        ca, cb = look.get("camera") or [], o.get("camera") or []
        if ca and cb and _jacc(ca, cb) >= 0.67:
            hit("camera", o)
        mm = _music_match(look.get("music") or [], o.get("music") or [])
        if mm:
            hit("music", o, mm)
        if _structure_match(look.get("structure") or {}, o.get("structure") or {}):
            hit("structure", o)
        if look.get("tone") and look.get("tone") == o.get("tone"):
            hit("tone", o)
    order = list(ASPECT_NAMES)
    out.sort(key=lambda r: order.index(r["aspect"]))
    return out


# ------------------------------------------------------------------ alternatives

def _seed(look: Dict[str, Any]) -> int:
    key = str(look.get("job") or look.get("project") or "")
    return int(hashlib.sha1(key.encode("utf-8")).hexdigest()[:8], 16)


def _rotate(items: List[Any], seed: int) -> List[Any]:
    if not items:
        return items
    k = seed % len(items)
    return items[k:] + items[:k]


def _used(look: Dict[str, Any], others: List[Dict[str, Any]], key: str) -> List[Any]:
    vals: List[Any] = []
    for x in [look] + others:
        v = x.get(key)
        if isinstance(v, dict):
            vals += list(v)
        elif isinstance(v, list):
            vals += v
        elif v:
            vals.append(v)
    return vals


def _lum(h: str) -> float:
    r, g, b = L.hex_rgb(h)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _transition_catalog() -> List[Dict[str, Any]]:
    d = read_json(skill_dir() / "runtime" / "transitions" / "catalog.json", {}) or {}
    return [t for t in d.get("transitions", []) if isinstance(t, dict)]


LAUNCH_TRANSITIONS = ("match", "through", "pan", "blur-dissolve", "dip", "crossfade")
CAMERA_VERBS = [
    ("push-in", "a camera push onto the detail that matters (`data-st=\"camera\"`, zoom 1 -> 1.3 on a focus)"),
    ("pan", "one wide world the camera travels across (transition `pan`, one direction for the video)"),
    ("through", "fly into a portal in the scene: a window, a screen, a letter's counter (transition `through`)"),
    ("match", "the product window or headline carries across the cut (`data-match`, transition `match`)"),
    ("parallax", "depth layers that move at different rates (`data-depth` inside a camera)"),
    ("ken-burns", "slow moves over stills and screenshots (component `ken-burns`)"),
    ("locked-off", "no camera at all: still frames, hard cuts on the music's phrases"),
]
STRUCTURES = [
    ("result first", "open on the finished outcome, then rewind to how (story.md, hooks)"),
    ("before/after split", "the pain and the relief side by side in one frame, then the proof"),
    ("contrast", "\"Everyone does X. This does Y.\" as the spine, two long scenes instead of five cards"),
    ("live action", "open mid-action (the cursor already typing), one continuous take with camera moves"),
    ("short-short-long", "two quick beats and one long held scene that carries the claim"),
    ("three acts", "3 long scenes (setup, turn, payoff) instead of a card per feature"),
]
TEMPLATE_ALTS = {
    "dom": ["film (one canvas drawn as f(t): illustrated, filmic)", "data (editorial charts that move)"],
    "launch": ["film (a canvas short film with a synth score)", "dom with the paper or editorial theme"],
    "film": ["dom with a runtime theme and camera moves", "launch (product window carried across scenes)"],
    "short": ["dom at 9:16 with kinetic type", "film at 9:16 (canvas, illustrated)"],
    "data": ["film (hand-drawn chart as f(t))", "dom with the terminal or neon theme"],
    "tutorial": ["dom with a camera over one screenshot", "footage edit of a real screen recording"],
    "series": ["dom with a new opener each episode", "film episodes"],
    "manim": ["dom with the chart component", "film (canvas)"],
}
MUSIC_USE = {"launch": "launch", "promo": "promo", "trailer": "trailer", "data": "data", "tutorial": "tutorial",
             "short": "social", "explainer": "explainer", "film": "story", "dom": "launch", "series": "tutorial"}


def alternatives(aspect: str, look: Dict[str, Any], others: List[Dict[str, Any]], n: int = 2) -> List[str]:
    """Up to n concrete alternatives for one repeated aspect, none used by `look` or `others`."""
    seed = _seed(look)
    kind = str(look.get("kind") or look.get("template") or "").lower()
    if aspect == "theme":
        used = set(_used(look, others, "theme"))
        cands = [L.theme_info(t) for t in L.theme_names() if t not in used]
        return ["theme %s: %s" % (c["name"], c.get("about") or "") for c in _rotate(cands, seed)[:n] if c]
    if aspect == "palette":
        pal = look.get("palette") or []
        dark = bool(pal) and _lum(pal[0]) < 90
        used = [c for x in [look] + others for c in (x.get("palette") or [])[:4]]
        cands = []
        for t in L.theme_names():
            info = L.theme_info(t)
            p = info.get("palette") or []
            if len(p) < 3 or any(L.color_distance(p[0], u) < PALETTE_NEAR for u in used[:1]):
                continue
            flip = (_lum(p[0]) < 90) != dark
            cands.append((0 if flip else 1, t, p))
        cands.sort(key=lambda c: c[0])
        out = ["%s ground %s with %s accent (theme %s's palette%s)" % ("a light" if _lum(p[0]) >= 90 else "a dark",
                                                                          p[0], p[2], t, ", the opposite of recent jobs" if f == 0 else "")
               for f, t, p in cands]
        if look.get("brand"):
            out.insert(0, "the brand kit's second accent as the ground of one key scene (the rest stays on brand)")
        return out[:n]
    if aspect == "type":
        used = {str(f).lower() for x in [look] + others for f in (x.get("type") or [])[:1]}
        pairs = []
        for t in L.theme_names():
            ty = L.theme_info(t).get("type") or []
            if ty and ty[0].lower() not in used and ty not in [p for p, _ in pairs]:
                pairs.append((ty, t))
        return ["%s (the %s theme's %s; `showtime assets font \"%s\"`)" % (
            " + ".join(dict.fromkeys(ty)), t, "pair" if len(set(ty)) > 1 else "one family for all text", ty[0])
            for ty, t in _rotate(pairs, seed)[:n]]
    if aspect == "transitions":
        used = set(_used(look, others, "transitions"))
        cat = _transition_catalog()
        if kind in ("launch", "promo", "trailer", "release"):
            cands = [t for t in cat if t["name"] in LAUNCH_TRANSITIONS and t["name"] not in used]
        else:
            energy = _energy_of(look.get("transitions") or {}, cat)
            cands = [t for t in cat if t.get("tier") == "premium" and t["name"] not in used]
            cands.sort(key=lambda t: (0 if t.get("energy") == energy else 1, t["name"]))
            cands = cands[:6]
        return ["%s as the primary handoff: %s" % (t["name"], t.get("use_when", "")) for t in _rotate(cands, seed)[:n]]
    if aspect == "camera":
        used = set(_used(look, others, "camera"))
        cands = [(v, d) for v, d in CAMERA_VERBS if v not in used and not (v == "locked-off" and not look.get("camera"))]
        return ["%s: %s" % (v, d) for v, d in _rotate(cands, seed)[:n]]
    if aspect == "music":
        return _music_alternatives(look, others, kind, seed, n)
    if aspect == "structure":
        st = look.get("structure") or {}
        cands = list(STRUCTURES)
        if st.get("shape") == "even":
            cands.sort(key=lambda c: 0 if c[0] in ("short-short-long", "three acts") else 1)
        return ["%s: %s" % c for c in cands[:1] + _rotate(cands[1:], seed)[:n - 1]]
    if aspect == "template":
        return ["template " + x for x in TEMPLATE_ALTS.get(str(look.get("template")), TEMPLATE_ALTS["dom"])[:n]]
    if aspect == "tone":
        used = set(_used(look, others, "tone"))
        cands = [t for t in ("polished", "deadpan", "documentary", "technical", "cinematic", "minimal", "playful",
                             "retro") if t not in used]
        return ["tone %s (references/tones.md)" % t for t in _rotate(cands, seed)[:n]]
    return []


def _energy_of(tr: Dict[str, int], cat: List[Dict[str, Any]]) -> str:
    by = {t["name"]: t.get("energy") for t in cat}
    p = _primary({k: v for k, v in tr.items() if k != "cut"} or tr)
    return by.get(p or "", "medium") or "medium"


def _music_alternatives(look: Dict[str, Any], others: List[Dict[str, Any]], kind: str, seed: int, n: int) -> List[str]:
    try:
        from ..audio import music as mus
        cat = mus.load_catalog()
        use = MUSIC_USE.get(kind, "launch")
        pre = mus.preset(use, cat) or {}
        shelves = list(pre.get("shelves") or [])
        lo, hi = (pre.get("energy") or [0.0, 1.0])[:2]
        tracks = [t for t in mus.tracks(cat, include_vetoed=False)
                  if t.get("energy") is None or lo - 0.05 <= float(t["energy"]) <= hi + 0.05]
    except Exception:  # noqa: BLE001 - no catalog: a generic hint
        return ["a different catalog shelf: `showtime audio music search --shelf <shelf>`",
                "a composed bed in another style (audio mix `compose`)"][:n]
    used_refs = {m.get("ref") for x in [look] + others for m in (x.get("music") or [])}
    used_shelves = {m.get("shelf") for x in [look] + others for m in (x.get("music") or []) if m.get("shelf")}
    free = [s for s in shelves if s not in used_shelves] or [s for s in shelves]
    out: List[str] = []
    for shelf in _rotate(free, seed):
        cands = [t for t in tracks if t.get("shelf") == shelf and "catalog:%s" % t["id"] not in used_refs]
        if not cands:
            continue
        t = _rotate(sorted(cands, key=lambda t: t["id"]), seed)[0]
        out.append("catalog:%s (\"%s\", %s shelf, %s; `showtime audio music info %s`)" % (
            t["id"], t.get("title"), shelf, ", ".join((t.get("moods") or [])[:2]) or "no mood tags", t["id"]))
        if len(out) >= n:
            break
    return out


# ------------------------------------------------------------------ the check

def check(look: Dict[str, Any], n: int = RECENT) -> Dict[str, Any]:
    """{enabled, compared: [job names], repeats: [{aspect, value, jobs, detail, strong, alternatives}], level}."""
    ok, why = enabled()
    res: Dict[str, Any] = {"enabled": ok, "compared": [], "repeats": [], "level": "ok", "look": look}
    if not ok:
        res["note"] = "look history is off (%s)" % why
        return res
    others = recent(n, exclude=look)
    res["compared"] = [o.get("job") for o in others]
    reps = repeats(look, others)
    refs = reference_looks(look)
    if refs:
        res["references"] = [r["title"] for r in refs]
    for r in reps:
        why = intended(r["aspect"], look, refs)
        if why:
            # the user asked for this look: a repeat that follows the style reference is kept on purpose
            r["intended"], r["strong"], r["alternatives"] = why, False, []
        else:
            r["alternatives"] = alternatives(r["aspect"], look, others)
    res["repeats"] = reps
    if any(r["strong"] for r in reps):
        res["level"] = "warning"
    elif reps:
        res["level"] = "info"
    res["message"] = message(res)
    res["fix"] = fix_text(res)
    return res


# aspects a style reference sets: a repeat in one of them follows the reference on purpose
REFERENCE_LED = ("template", "theme", "palette", "type", "transitions", "camera", "structure", "tone")


def reference_looks(look: Dict[str, Any]) -> List[Dict[str, Any]]:
    """[{title, palette, scenes}] for the style references of the look's job (`showtime reference --job`)."""
    jp = look.get("job_path")
    if not jp or not Path(jp).is_dir():
        return []
    from .guard import job_references
    out = []
    for r in job_references(Path(jp)):
        data = read_json(Path(r["dir"]) / "reference.json", {}) or {}
        out.append({"title": r.get("title") or Path(r["dir"]).name,
                    "palette": [c.get("hex") for c in data.get("palette") or [] if c.get("hex")],
                    "scenes": len(data.get("shots") or [])})
    return out


def follows_palette(pal: Sequence[str], ref: Sequence[str]) -> bool:
    """The look uses the reference's main colours (at least two of its first three, or all when fewer)."""
    ref = [c for c in ref if c][:3]
    pal = [c for c in pal if c][:6]
    if not ref or not pal:
        return False
    hits = sum(1 for x in ref if any(L.color_distance(x, y) < PALETTE_NEAR for y in pal))
    return hits >= min(2, len(ref))


def intended(aspect: str, look: Dict[str, Any], refs: List[Dict[str, Any]]) -> Optional[str]:
    """Why a repeat is intended ("follows the style reference ..."), or None when it is a real repeat.
    The palette counts only when the look really uses the reference's colours; music never does (a
    reference sets the sound's shape, not the track)."""
    if not refs or aspect not in REFERENCE_LED:
        return None
    for r in refs:
        if aspect == "palette" and not follows_palette(look.get("palette") or [], r["palette"]):
            continue
        return "follows the style reference \"%s\"" % r["title"]
    return None


def message(res: Dict[str, Any]) -> str:
    """One warning line: what repeats (and in which recent jobs)."""
    reps = [r for r in res.get("repeats") or [] if r["strong"]] or res.get("repeats") or []
    if not reps:
        return ""
    if all(r.get("intended") for r in reps):
        k = len(res.get("compared") or [])
        return "this look repeats recent videos on purpose: %s (kept: %s)" % (
            ", ".join("%s (%d of the last %d)" % (ASPECT_NAMES[r["aspect"]], len(r["jobs"]), k) for r in reps),
            reps[0]["intended"])
    k = len(res.get("compared") or [])
    parts = []
    for r in reps:
        what = ASPECT_NAMES[r["aspect"]]
        val = r.get("detail") or r.get("value")
        parts.append("%s %s (%d of the last %d: %s)" % (what, val, len(r["jobs"]), k, ", ".join(r["jobs"][:3])))
    return "this look repeats recent videos: " + "; ".join(parts)


def fix_text(res: Dict[str, Any]) -> str:
    rows = []
    for r in [r for r in res.get("repeats") or [] if r["strong"]] or res.get("repeats") or []:
        alts = r.get("alternatives") or []
        if alts:
            rows.append("%s: %s" % (ASPECT_NAMES[r["aspect"]], " | ".join(alts)))
    return "; ".join(rows)


def format_text(res: Dict[str, Any]) -> str:
    lines: List[str] = []
    if not res.get("enabled"):
        return res.get("note") or "look history is off"
    comp = res.get("compared") or []
    if not comp:
        return "no earlier jobs in the look history yet (%s): nothing to compare" % file()
    if not res.get("repeats"):
        return "look is fresh: no repeats against the last %d job(s) (%s)" % (len(comp), ", ".join(comp))
    lines.append(("WARN  " if res["level"] == "warning" else "info  ") + message(res))
    for r in res["repeats"]:
        lines.append("  %-13s %s  <- %s" % (ASPECT_NAMES[r["aspect"]], r.get("detail") or r.get("value"), ", ".join(r["jobs"])))
        if r.get("intended"):
            lines.append("      kept: %s" % r["intended"])
        for a in r.get("alternatives") or []:
            lines.append("      try: %s" % a)
    return "\n".join(lines)


def to_json(res: Dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in res.items()}, indent=2, ensure_ascii=False)

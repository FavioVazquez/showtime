"""The sound of a generated film (recap, repro): a bed and a few effects that differ from film to film.

Both commands used to write the same bed (minimal-pulse, seed 11) and the same swoosh, click and error
tone every time. Here each film derives its sound from a stable hash of what it is about (the session,
the test), so the same input sounds the same on every rerun and different inputs sound different:

- the bed is a produced catalog track (picked through music.search, so the rotation away from the last
  8 finished jobs applies) when one is cached, or can be fetched now; otherwise a composed bed in a
  style chosen from a short list for the kind, moved off the styles of the last few jobs. A job keeps its
  pick: a rerun reuses the bed already in the project's mix.json, else the one the look history recorded
  for the project, and the job itself never counts as "recent";
- the cut, click and error effects are chosen per film from the synth families that stay subtle.

`--music <style|catalog-id|none>` pins the bed. Stdlib plus st.audio (imported when a choice is made).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .common import ShowtimeError, log

# composed styles that fit each kind (references/music.md section 2): calm for a recap; calm or tense for a
# repro (a failing test), never a groove
STYLES = {
    "recap": ("minimal-pulse", "underscore", "lofi-chill", "ambient-pad", "piano-emotional"),
    "repro": ("minimal-pulse", "underscore", "dark-tension", "ambient-pad", "lofi-chill"),
}
# the catalog query per kind: a restrained, vocal-free track (music.py presets)
CATALOG = {
    "recap": {"use": "story", "energy": (0.1, 0.5)},
    "repro": {"use": "tech", "energy": (0.15, 0.45)},
}
STYLE_JOBS = 3          # a composed style used by one of this many latest jobs is skipped when others remain
CANDIDATES = 8

# effect families (all subtle: ui and transition categories only)
CUT = ("swoosh-in", "swoosh-out")      # soft transitions only (the hard whoosh stays out of generated films)
DUCK_DEPTH_DB = 10.0                 # the bed under narration dips 10 dB (the mixer's default is 12): voice stays ~17 dB over it
CUT_GAIN_DB = -18.0                  # about 18 dB under the bed: felt on the cut, never heard as an effect
CLICK = ("click", "tick", "pop", "toggle")
ERROR = ("error", "power-down")
KEYS = ("C", "D", "E", "F", "G", "A")


def stable(*parts: Any) -> int:
    """A 32-bit number from the parts: the same input gives the same number on every machine and run."""
    return int(hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:8], 16)


def synth(key: str, role: str, salt: Any = 0, intensity: float = 0.4, tone: Optional[str] = None) -> Dict[str, Any]:
    """The synth spec of one effect: the family is this film's choice for the role, the seed the event's, the key
    (used by the tonal ones) the bed's when it is composed."""
    fams = {"cut": CUT, "click": CLICK, "error": ERROR}[role]
    typ = fams[stable(key, role, "family") % len(fams)]
    return {"type": typ, "intensity": round(intensity, 2), "seed": stable(key, role, salt) % 100000,
            "key": tone or KEYS[stable(key, role, "key") % len(KEYS)]}


def _project_key(project: Optional[Path]) -> Optional[str]:
    return str(Path(project).resolve()) if project else None


def _recent_styles(project: Optional[Path]) -> List[str]:
    """Composed styles of the last jobs, leaving out this project's own job; none when rotation is off."""
    from .audio import music
    if music.rotation_off():
        return []
    try:
        rows = music.recent_music(_project_key(project), n=STYLE_JOBS)
    except (ShowtimeError, OSError, ValueError):
        return []
    return [s for r in rows for s in r["composed"]]


def pick_style(kind: str, key: str, project: Optional[Path] = None) -> str:
    """A composed style for the kind: the film's own choice, off the styles of the last few jobs."""
    from .audio import compose
    names = [compose.resolve_style(s) for s in STYLES[kind]]
    recent = _recent_styles(project)
    pool = [s for s in names if s not in recent] or names
    return pool[stable(key, kind, "style") % len(pool)]


def _previous(project: Optional[Path]) -> Optional[Dict[str, Any]]:
    """The bed this project already has: {"catalog": id} or {"compose": {style, seed, key}}. First the bed in the
    project's own audio/mix.json (a rerun of the same job), then the music the look history recorded for it
    (music._pinned does the same for a catalog query)."""
    if not project:
        return None
    from .audio import compose, music
    mix = Path(project) / "audio" / "mix.json"
    tracks: List[Dict[str, Any]] = []
    try:
        tracks = [t for t in json.loads(mix.read_text(encoding="utf-8")).get("tracks", []) if t.get("id") == "bed"]
    except (OSError, ValueError, AttributeError):
        pass
    cands: List[Dict[str, Any]] = []
    for t in tracks:
        if isinstance(t.get("catalog"), str):
            cands.append({"catalog": t["catalog"]})
        elif isinstance(t.get("compose"), dict):
            cands.append({"compose": t["compose"]})
    key = _project_key(project)
    try:
        from .variety import history
        if history.enabled()[0]:
            for lk in reversed(history.load()):
                if not (music._same(lk.get("project"), key) or music._same(lk.get("job_path"), key)):
                    continue
                for m in lk.get("music") or []:
                    ref = str(m.get("ref") or "")
                    if ref.startswith("catalog:"):
                        cands.append({"catalog": ref[len("catalog:"):]})
                    elif ref.startswith("compose:") and m.get("seed") is not None:
                        cands.append({"compose": {k: m[k] for k in ("style", "seed", "key") if m.get(k) is not None}})
                break
    except (ShowtimeError, OSError, ValueError):
        pass
    for c in cands:
        if "catalog" in c:
            try:
                t = music.get(c["catalog"])
            except ShowtimeError:
                continue
            if t.get("status", "active") == "active" and t["id"] not in music.vetoed_ids():
                return {"catalog": t["id"]}
        else:
            try:
                comp = c["compose"]
                compose.resolve_style(comp["style"])
                int(comp["seed"])
                return {"compose": {"style": compose.resolve_style(comp["style"]), "seed": int(comp["seed"]),
                                    "key": comp.get("key") or compose.auto_key(comp["style"], int(comp["seed"]))}}
            except (ShowtimeError, KeyError, ValueError, TypeError):
                continue
    return None


def _catalog_track(kind: str, key: str, dur: float, fetch: bool, project: Optional[Path]) -> Optional[Dict[str, Any]]:
    """A catalog track for the film: a cached one first, else (fetch) the film's own pick, to be downloaded
    before the render; None if neither."""
    from .assets import net
    from .audio import music
    q = CATALOG[kind]
    try:
        rows = music.search(use=q["use"], energy=q["energy"], vocals="none", dur=dur or None,
                            limit=CANDIDATES, key=_project_key(project) or key)
    except ShowtimeError:
        return None
    cands = [r["track"] for r in rows]
    if not cands:
        return None
    i = stable(key, kind, "track") % len(cands)
    order = cands[i:] + cands[:i]
    for t in order:
        if music.is_cached(t):
            return t
    return order[0] if fetch and not net.offline() else None


def _compose(style: str, key: str, kind: str, sections: str, seed: Optional[int] = None,
             tone: Optional[str] = None) -> Dict[str, Any]:
    from .audio import compose
    seed = stable(key, kind, "seed") % 9000 + 1 if seed is None else int(seed)
    return {"style": style, "sections": sections, "seed": seed, "key": tone or compose.auto_key(style, seed)}


def _composed(kind, key, sections, track, c, **extra) -> Dict[str, Any]:
    return dict({"how": "compose", "kind": kind, "label": "composed %s (seed %d, key %s)" % (c["style"], c["seed"], c["key"]),
                 "style": c["style"], "key": c["key"], "track": track({"compose": c}), "fallback": None}, **extra)


def choose(kind: str, key: str, dur: float, sections: str, *, pin: Optional[str] = None, gain_db: float = -3.0,
           duck: Optional[Dict[str, Any]] = None, fetch: bool = False,
           project: Optional[Path] = None) -> Dict[str, Any]:
    """The bed of a film: {"how": catalog|compose|none, "kind", "label", "track" (the mix.json track or None),
    "fallback" (a composed track to use if a catalog track cannot be fetched), "style" or "id"}.

    `key` is what the film is about (it only seeds the pick); `project` is its folder (the rotation key, and where
    a rerun finds the bed it already has); `pin` is --music; `fetch` lets a catalog track that is not cached
    count (it is downloaded before the render, see ensure())."""
    from .audio import compose, music

    def track(src: Dict[str, Any]) -> Dict[str, Any]:
        tr: Dict[str, Any] = {"id": "bed", "kind": "music"}
        tr.update(src)
        tr.update({"gain_db": gain_db, "fade_out": 1.2})
        if duck:
            tr["duck"] = dict(duck)
        return tr

    if pin is not None and str(pin).strip().lower() in ("none", "off", "no"):
        return {"how": "none", "kind": kind, "label": "no music", "track": None, "fallback": None}
    if pin:
        try:
            style = compose.resolve_style(pin)
        except ShowtimeError:
            style = None
        if style is None:
            try:
                t = music.get(str(pin).strip())
            except ShowtimeError:
                raise ShowtimeError("--music %r is not a style, a catalog track or none" % pin,
                                    hint="showtime audio styles, showtime audio music pick --for story, or none")
            return _catalog_choice(t, track, kind, key, sections, project, pinned=True)
        return _composed(kind, key, sections, track, _compose(style, key, kind, sections), pinned=True)
    prev = _previous(project)
    if prev and "catalog" in prev:
        return _catalog_choice(music.get(prev["catalog"]), track, kind, key, sections, project)
    if prev:
        c = prev["compose"]
        return _composed(kind, key, sections, track, _compose(c["style"], key, kind, sections, c["seed"], c["key"]))
    t = _catalog_track(kind, key, dur, fetch, project)
    if t is not None:
        return _catalog_choice(t, track, kind, key, sections, project)
    return _composed(kind, key, sections, track, _compose(pick_style(kind, key, project), key, kind, sections))


def _catalog_choice(t, track, kind, key, sections, project, pinned: bool = False) -> Dict[str, Any]:
    from .audio import music
    src: Dict[str, Any] = {"catalog": t["id"], "fit": True}
    if float(t.get("quiet_intro_s") or 0) >= 6:
        src["offset"] = "highlight"
    fb = track({"compose": _compose(pick_style(kind, key, project), key, kind, sections)})
    return {"how": "catalog", "kind": kind, "pinned": pinned,
            "label": "%s by %s (catalog %s)" % (t["title"], t["artist"], t["id"]),
            "id": t["id"], "track": track(src), "fallback": fb, "credit": music.credit_item(t)}


def comment(choice: Dict[str, Any], sounds: bool = True) -> str:
    """The mix.json _comment: what made the bed, and what stayed on this machine. `sounds`: the mix has effects."""
    kind = choice.get("kind") or "film"
    fx = " and soft sounds made on this machine" if sounds else ""
    if choice.get("how") == "catalog":
        return ("Generated by showtime %s: a produced catalog track (downloaded once from its creator's site and cached; "
                "nothing is sent)%s. `--music <style>` or SHOWTIME_OFFLINE=1 keeps it fully local." % (kind, fx))
    if choice.get("how") == "none":
        return "Generated by showtime %s: %s." % (kind, "soft sounds made on this machine, no music (--music none)"
                                                 if sounds else "no music (--music none), no sounds")
    return "Generated by showtime %s: a composed bed%s, all made on this machine." % (kind, fx)


def scene_sections(project: Path) -> str:
    """music sections ("0:intro,4:verse,9:outro") from the scenes of the project's page as it is now (after a
    retime), or "" when they cannot be read."""
    try:
        html = (Path(project) / "index.html").read_text(encoding="utf-8")
    except OSError:
        return ""
    durs = [float(m) for m in re.findall(r'<section[^>]*class="scene"[^>]*data-dur="([\d.]+)"', html)]
    if not durs:
        return ""
    starts, t = [], 0.0
    for d in durs:
        starts.append(round(t, 2))
        t += d
    names = ["intro"] + ["verse"] * max(0, len(starts) - 2) + ["outro"]
    return ",".join("%g:%s" % (a, b) for a, b in zip(starts, names))


PLACEMENT = ("duck", "start", "gain_db", "fade_out", "gain_points")


def ensure(mix_path: Path, choice: Dict[str, Any]) -> None:
    """Before a render: a catalog bed is downloaded now (announced, checksummed). If that fails (no network, a blocked
    host, a cache that cannot be written) the bed in mix.json becomes the composed fallback, keeping the current
    bed's placement (duck, start, gain, fade, gain points) and sections from the scenes as they are now, so the
    render never stops on it. A track the person pinned with --music is not swapped: it fails."""
    if choice.get("how") != "catalog":
        return
    from .audio import music
    try:
        music.fetch(choice["id"], purpose="the soundtrack")
        return
    except (ShowtimeError, OSError) as e:
        if choice.get("pinned"):
            raise ShowtimeError("--music %s could not be fetched: %s" % (choice["id"], e),
                                hint="try again online, or pin a style: --music minimal-pulse")
        log("music: %s is not available (%s); using a composed bed instead" % (choice["id"], e))
    mp = Path(mix_path)
    mix = json.loads(mp.read_text(encoding="utf-8"))
    cur = next((t for t in mix["tracks"] if t.get("id") == "bed"), {})
    fb = dict(choice["fallback"])
    fb.update({k: cur[k] for k in PLACEMENT if k in cur})
    secs = scene_sections(mp.parent.parent)
    if secs:
        fb["compose"] = dict(fb["compose"], sections=secs)
    mix["tracks"] = [fb if t.get("id") == "bed" else t for t in mix["tracks"]]
    c = fb["compose"]
    choice.update(how="compose", style=c["style"], key=c["key"], track=fb, credit=None,
                  label="composed %s (seed %d, key %s; the catalog track could not be fetched)" % (
                      c["style"], c["seed"], c["key"]))
    mix["_comment"] = comment(choice, any(t.get("kind") == "sfx" for t in mix["tracks"]))
    mp.write_text(json.dumps(mix, indent=2) + "\n", encoding="utf-8")


def credit_report(video: Path, choice: Dict[str, Any]) -> Dict[str, Any]:
    """What a catalog bed owes the person, after the render: {"credits": file, "share": file, "notes": [...],
    "attribution": line or None}. Empty for a composed bed."""
    out: Dict[str, Any] = {"credits": None, "share": None, "notes": [], "attribution": None}
    item = choice.get("credit")
    if choice.get("how") != "catalog" or not item:
        return out
    from .audio import credits as credmod
    video = Path(video)
    for name in (video.stem + ".credits.txt", "credits.txt"):
        if (video.parent / name).is_file():
            out["credits"] = str(video.parent / name)
            break
    if (video.parent / "share.txt").is_file():
        out["share"] = str(video.parent / "share.txt")
    out["notes"] = credmod.content_id_notes([item])
    if item.get("attribution_required") and item.get("attribution"):
        out["attribution"] = item["attribution"]
    return out

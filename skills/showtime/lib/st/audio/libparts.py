"""Audio library parts: a small starter part first, category parts when they are needed.

The whole core tier is ~249 MB, which is too much for a first run. So the library is
split into parts over the same pinned sources in library_manifest.json (nothing new is
downloaded, only in smaller pieces):

  starter        ~41 MB, fetched automatically the first time anything reads the library:
                 UI, impact, whoosh, digital and sci-fi effects, three ambiences, six stingers
                 and one music bed per broad mood (uplifting, bright, calm, epic, dark, tech, piano)
  sfx            the other effect packs (casino, RPG, foley, retro synth, water, voice-overs)
  ambience       the other ambience loops
  music-upbeat   bright / bouncy / grooving / driving beds
  music-calm     calm / relaxed / emotional / classical beds
  music-epic     epic / intense / dark / suspenseful beds and the other stingers
  extended       the extended tier (more music and effects; `lib fetch --tier extended`)

A search that finds little in what is installed (fewer than MIN_HITS results) and points
at a part that is not here yet (music with an epic mood -> `music-epic`, any sound effect ->
`sfx`) fetches that part once, announced with its size, and searches again; offline it
keeps what is installed and says which part would add more. `showtime audio lib fetch` still
installs the whole core tier, and `showtime setup --full` everything. (The extra sound-effect
packs of sfx_packs.json are a different thing: audio/packs.py.)

Stdlib only (status() runs before the venv exists: doctor, `setup --plan`).
"""
from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from ..common import ShowtimeError, home, human_size, info, warn

MANIFEST = Path(__file__).with_name("library_manifest.json")

STARTER = [
    # effects (13.7 MB; Kenney hosts them fast, OpenGameArt asks for 10 s between downloads, so few of those)
    "kenney-ui-audio", "kenney-interface-sounds", "kenney-impact-sounds", "kenney-digital-audio",
    "kenney-sci-fi-sounds", "kenney-music-jingles", "oga-swishes-sound-pack",
    # ambiences (4.1 MB)
    "oga-amb-rain-loop-1", "oga-forest-ambience", "oga-low-rumbling",
    # stingers (4.4 MB)
    "incompetech-discovery-hit", "incompetech-the-curtain-rises", "incompetech-light-sting", "incompetech-cool-intro",
    "incompetech-newssting", "incompetech-mystery-sting",
    # one bed per broad mood (23.5 MB)
    "incompetech-newer-wave", "incompetech-voxel-revolution", "incompetech-easy-lemon-60-second",
    "incompetech-our-story-begins", "incompetech-darkening-developments", "incompetech-stoic-morning",
    "ia-loyalty-freak-music-high-technologic-beat-explosion", "ia-musopen-chopin-prelude-op-28-no-6",
]

UPBEAT = {"bouncy", "bright", "grooving", "driving", "energetic", "uplifting", "humorous", "adventurous"}
CALM = {"calm", "calming", "relaxed", "emotional", "classy", "somber", "mystical", "cozy", "tender"}
EPIC = {"epic", "intense", "dark", "suspenseful", "action", "eerie", "unnerving", "mysterious", "heroic"}

PARTS = {
    "starter": "starter set: common effects, ambiences, stingers and one bed per mood",
    "sfx": "more sound effects (casino, RPG, foley, retro synth, water, voice-overs)",
    "ambience": "more ambience loops",
    "music-upbeat": "bright, bouncy, grooving and driving music beds",
    "music-calm": "calm, relaxed, emotional and classical music beds",
    "music-epic": "epic, intense, dark and suspenseful beds, plus the other stingers",
    "extended": "the extended tier: more music and effects",
}
MIN_HITS = 3     # a search with fewer results than this fetches the parts it points at

QUERY_PARTS = {  # search words / moods that point at a part
    "music-upbeat": UPBEAT | {"upbeat", "happy", "tech", "corporate", "groovy", "funny", "playful", "inspiring"},
    "music-calm": CALM | {"sad", "chill", "piano", "ambient", "soft", "peaceful"},
    "music-epic": EPIC | {"tense", "trailer", "cinematic", "launch", "dramatic", "suspense"},
}


def _manifest() -> Dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def library_dir() -> Path:
    env = os.environ.get("SHOWTIME_LIBRARY")
    return Path(os.path.expanduser(env)) if env else home() / "library"


def part_of(src: Dict[str, Any]) -> str:
    """The one part a manifest source belongs to."""
    sid = src["id"]
    if sid in STARTER:
        return "starter"
    if src.get("tier", "core") != "core":
        return "extended"
    kind = src.get("kind")
    if kind in ("sfx", "voice"):
        return "sfx"
    if kind == "ambience":
        return "ambience"
    moods = {m.lower() for m in (src.get("mood") or [])} | {t.lower() for t in (src.get("tags") or [])}
    if kind == "stinger":
        return "music-epic" if src.get("type") == "file" else "sfx"
    scores = {"music-epic": len(moods & EPIC), "music-calm": len(moods & CALM), "music-upbeat": len(moods & UPBEAT)}
    best = max(scores.values())
    if best == 0:
        return "music-calm"
    for name in ("music-epic", "music-calm", "music-upbeat"):  # ties: the rarer mood wins
        if scores[name] == best:
            return name
    return "music-calm"


def sources(part: str, man: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    man = man or _manifest()
    if part not in PARTS:
        raise ShowtimeError("unknown library part %r" % part, hint="parts: " + ", ".join(PARTS))
    return [s for s in man["sources"] if part_of(s) == part]


def installed_sources() -> Set[str]:
    try:
        st = json.loads((library_dir() / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    lib = library_dir()
    return {sid for sid, rec in (st.get("sources") or {}).items()
            if all((lib / p).is_file() for p in rec.get("files", []))}


def managed() -> bool:
    """True when this library was filled from the manifest (parts apply); a folder of your own
    sounds indexed with `lib index` is left alone."""
    ids = {s["id"] for s in _manifest()["sources"]}
    return bool(installed_sources() & ids)


def status() -> List[Dict[str, Any]]:
    man = _manifest()
    have = installed_sources()
    out = []
    for name, desc in PARTS.items():
        srcs = sources(name, man)
        missing = [s for s in srcs if s["id"] not in have]
        when = ("first use of the audio library" if name == "starter" else
                "`showtime audio lib fetch --tier extended`" if name == "extended" else
                "a search that needs it, or `showtime audio lib fetch --part %s`" % name)
        out.append({"id": name, "description": desc, "sources": len(srcs),
                    "bytes": sum(int(s.get("bytes") or 0) for s in srcs),
                    "missing_bytes": sum(int(s.get("bytes") or 0) for s in missing),
                    "ready": not missing, "when": when})
    return out


def _offline() -> bool:
    return os.environ.get("SHOWTIME_OFFLINE", "").strip().lower() not in ("", "0", "false", "no")


def ensure(part: str, feature: str, required: bool = True) -> Dict[str, Any]:
    """Fetch a part's missing sources (announced). part 'all' = every core part.

    required=False turns an offline miss into a warning (the caller carries on with what is here)."""
    names = [p for p in PARTS if p != "extended"] if part == "all" else [part]
    man = _manifest()
    have = installed_sources()
    todo = [s for n in names for s in sources(n, man) if s["id"] not in have]
    if not todo:
        return {"fetched": 0}
    size = sum(int(s.get("bytes") or 0) for s in todo)
    label = "audio library part %s" % part if part != "all" else "the audio library"
    if _offline() and not os.environ.get("SHOWTIME_SEED_DIRS"):
        msg = "%s needs %s (%s), which is not downloaded yet, and showtime is offline" % (feature, label, human_size(size))
        if required:
            raise ShowtimeError(msg, why="library parts are fetched the first time they are needed",
                                hint="on a connected machine run `showtime setup --full` (or `showtime audio lib "
                                     "fetch`), or seed the files with `showtime setup --seed DIR --fetch library:%s`" % part,
                                code=3)
        warn(msg + "; using what is installed")
        return {"fetched": 0, "offline": True}
    info("fetching %s (%s, %d sources) for %s (one time; `showtime audio lib fetch` gets the whole library)" % (
        label, human_size(size), len(todo), feature))
    from . import library
    rep = library.fetch("extended" if any(s.get("tier") == "extended" for s in todo) else "core",
                        only=[s["id"] for s in todo], generated=False)
    if rep.get("failed") and required and len(rep["failed"]) == len(todo):
        raise ShowtimeError("could not fetch %s: %s" % (label, rep["failed"][0].get("error")),
                            hint="run the command again (downloads resume), or `showtime audio lib fetch`")
    return {"fetched": len(rep.get("installed", [])), "failed": rep.get("failed", [])}


def ensure_starter(feature: str = "the audio library") -> None:
    ensure("starter", feature)


def parts_for_query(words: Iterable[str], kinds: Iterable[str], moods: Iterable[str]) -> List[str]:
    """Parts a search would draw on that are not complete yet."""
    kinds_s = {k.lower() for k in kinds}
    terms = {w.lower() for w in words} | {m.lower() for m in moods}
    want: List[str] = []
    if not kinds_s or kinds_s & {"music", "stinger"}:
        want += [p for p, keys in QUERY_PARTS.items() if terms & keys]
    if kinds_s & {"sfx", "voice"}:
        want.append("sfx")
    if kinds_s & {"ambience"}:
        want.append("ambience")
    if not want or not managed():
        return []
    st = {p["id"]: p for p in status()}
    return [p for p in want if not st[p]["ready"]]


def match(pattern: str) -> List[str]:
    return [p for p in PARTS if fnmatch.fnmatch(p, pattern)]

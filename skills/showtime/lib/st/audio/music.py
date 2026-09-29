"""Produced music: a curated catalog of real recordings, fetched on first use and credited automatically.

The catalog (`music_catalog.json`, schema `showtime.music.catalog/1`) lists produced tracks that are
legal to fetch from their creators' own hosts: CC BY 4.0 (Scott Buckley, Kevin MacLeod), CC0 and
public-domain recordings (Wikimedia Commons, the Internet Archive). Nothing is re-hosted:
each entry pins the file URL, its byte size and sha256, and the exact credit the license asks for.
A track is downloaded the first time a mix, `audio music fetch` or `setup --full` needs it
("fetching X (N MB) for Y"), verified, and kept in ~/.showtime/music/ (or $SHOWTIME_MUSIC_CACHE).
Cached tracks work offline (SHOWTIME_OFFLINE=1).

Catalog layout (every field is checked by `validate()` and by tests/test_music.py):

  schema, about, updated
  quality_gate {checked (date), method, fail_if {threshold: value}, notes {metric: definition}}
  sources  {source_id: {name, homepage, license, attribution_format, placements, content_id,
                        content_id_note, restrictions[], evidence[], fetch: {hosts[], delay_s, rule}}}
  presets  {use: {shelves[], energy: [lo, hi], vocals: [allowed], max_intro_s?}}   (what `pick --for` means)
  tracks   [{id, title, artist, source, landing_url, file_url, format, bytes, sha256,
             license (SPDX), license_url, attribution (exact credit text, null for CC0/PD),
             credit_optional, placements[], content_id, duration (s), shelf, moods[], energy (0..1),
             tempo (slow|medium|fast), uses[], vocals (none|some|lead), instruments[],
             ending (clean|soft|cut|unknown), loops (true|false|null), status (active|vetoed),
             composer?, bpm?, variant_of?, variant?, openverse_id?, quiet_intro_s, lead_silence_s,
             highlight_s, featured?, notes?, verified (date)}]

Measured fields (the whole decoded file, see quality_gate.notes): `ending` clean = a final hit or
cadence with its ring-out (the last loud moment 1-7 s before the end), soft = a fade or a quiet outro,
cut = still loud in the last second (a loop point, an abrupt end, a movement that runs into the next);
`quiet_intro_s` = seconds until the track is clearly audible (body level minus 18 dB);
`lead_silence_s` = near-silence (below -50 dBFS) before the first sound, skipped by default in a mix;
`highlight_s` = where the loudest sustained 30 s begins (a mix starts there with "offset": "highlight").

Quality gate. Every track was downloaded, decoded in full and measured before it was admitted; one
failed check keeps a track out (thresholds in the catalog's `quality_gate.fail_if`):
  format       sample rate below 44.1 kHz; MP3 below 96 kbps, Vorbis below 80, Opus below 64
  bandwidth    below 11 kHz (the loud passages' long-term spectrum within 50 dB of its 200 Hz-4 kHz
               level): old 78 rpm transfers, AM-radio style and over-filtered masters sound muffled
  stereo       side/mid energy below -30 dB (mono or dual mono)
  clipping     more than 25 runs/min of 3+ samples at full scale, or more than 100 ppm of decoded
               samples above full scale
  hiss         a steady 8-16 kHz noise floor (never dips more than 4 dB in 23 ms frames) above -50 dB
               relative to the loud passages
  crackle      more than 30 audible clicks/min away from musical onsets, in a recording that also has
               under 15 kHz of bandwidth or a steady noise floor above -60 dB (surface noise)
  dynamics     loudness range above 20 LU (quiet passages vanish under a voice, peaks jump out), or
               integrated loudness below -36 LUFS
  silences     more than 8 s of silence before the music, more than 20 s after it, or a gap of more
               than 4 s below -55 dBFS inside it (the music stops mid-video)
  length       under 45 s
Tags were checked against the same measurements (tempo, pulse clarity, onset rate, percussive
share, spectral centroid, activity) and corrected where the audio clearly disagreed. Per-track
measurements live with the authoring notes, not in the package.

Licence rules enforced here: only CC-BY-4.0, CC-BY-3.0, CC0-1.0, CC-PDDC and CC-PDM-1.0; a CC BY
track must carry its attribution text and list "description" and "credits_file" among its
placements; file hosts must belong to the track's source; custom "royalty-free" hosts are refused.

User vetoes live in ~/.showtime/music/vetoes.json (`audio music veto <id>`); vetoed tracks are never
picked unless asked for by id.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from ..common import ShowtimeError, cache_lock, home, human_size, log, read_json, sha256_file, warn, write_json

SCHEMA = "showtime.music.catalog/1"
CATALOG = Path(__file__).with_name("music_catalog.json")

SHELVES = ("cinematic", "inspiring", "ambient", "corporate-tech", "upbeat", "documentary", "tension",
           "playful", "lofi", "piano", "orchestral")
TEMPOS = ("slow", "medium", "fast")
VOCALS = ("none", "some", "lead")
ENDINGS = ("clean", "soft", "cut", "unknown")
CONTENT_ID = ("smart-cid-releasable", "none-known", "unknown")
PLACEMENTS = ("description", "credits_file", "end_card", "video_credits")
LICENSES = {  # SPDX id -> (needs attribution, short label, canonical deed)
    "CC-BY-4.0": (True, "CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"),
    "CC-BY-3.0": (True, "CC BY 3.0", "https://creativecommons.org/licenses/by/3.0/"),
    "CC0-1.0": (False, "CC0", "https://creativecommons.org/publicdomain/zero/1.0/"),
    "CC-PDDC": (False, "public domain", "https://creativecommons.org/licenses/publicdomain/"),
    "CC-PDM-1.0": (False, "public domain", "https://creativecommons.org/publicdomain/mark/1.0/"),
}
# hosts whose terms forbid library use or automated fetching (see references/music.md). Jamendo: its own
# terms add conditions on top of the artists' CC licences (paid licences for commercial use, file-storage
# download rules) and its licensing program claims videos, so it is kept out of the curated catalog.
REFUSED_HOSTS = ("pixabay.com", "mixkit.co", "uppbeat.io", "bensound.com", "youtube.com", "youtu.be",
                 "freemusicarchive.org", "tunetank.com", "chosic.com", "freepd.com", "zapsplat.com", "jamendo.com")
USER_AGENT_NOTE = "showtime music fetch (one file per user request; never bulk)"

_CAT: Dict[str, Any] = {}


# ------------------------------------------------------------------------------------------ catalog
def load_catalog(path: Optional[Path] = None) -> Dict[str, Any]:
    p = Path(path or os.environ.get("SHOWTIME_MUSIC_CATALOG") or CATALOG)
    key = str(p)
    if key not in _CAT:
        try:
            cat = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ShowtimeError("the music catalog could not be read: %s (%s)" % (p, e))
        if cat.get("schema") != SCHEMA:
            raise ShowtimeError("%s is not a %s file" % (p, SCHEMA))
        _CAT[key] = cat
    return _CAT[key]


def tracks(cat: Optional[Dict[str, Any]] = None, include_vetoed: bool = True) -> List[Dict[str, Any]]:
    cat = cat or load_catalog()
    out = list(cat.get("tracks", []))
    if not include_vetoed:
        v = vetoed_ids()
        out = [t for t in out if t.get("status", "active") == "active" and t["id"] not in v]
    return out


def get(track_id: str, cat: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A track by id; forgiving: case-insensitive, a unique suffix ("with-these-hands") or title."""
    ts = tracks(cat)
    for t in ts:
        if t["id"] == track_id:
            return t
    low = track_id.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", low).strip("-")
    hits = [t for t in ts if t["id"].lower() == low or t["id"].lower().endswith("-" + slug)
            or re.sub(r"[^a-z0-9]+", "-", t["title"].lower()).strip("-") == slug]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise ShowtimeError("%r matches %d tracks: %s" % (track_id, len(hits), ", ".join(h["id"] for h in hits[:6])),
                            hint="use the full id")
    raise ShowtimeError("no catalog track %r" % track_id, hint="find ids with `showtime audio music search <words>`")


def source(t: Dict[str, Any], cat: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cat = cat or load_catalog()
    return (cat.get("sources") or {}).get(t.get("source"), {})


def license_info(spdx: Optional[str]) -> Tuple[bool, str, str]:
    if spdx not in LICENSES:
        raise ShowtimeError("license %r is not allowed in the music catalog" % spdx)
    return LICENSES[spdx]


def needs_attribution(t: Dict[str, Any]) -> bool:
    return bool(LICENSES.get(t.get("license"), (True,))[0])


# ------------------------------------------------------------------------------------------ validation
def validate(cat: Optional[Dict[str, Any]] = None) -> List[str]:
    """Every problem with the catalog (empty list = valid). Used by tests and `audio music check`."""
    cat = cat if cat is not None else load_catalog()
    errs: List[str] = []
    if cat.get("schema") != SCHEMA:
        errs.append("schema must be %s" % SCHEMA)
    srcs = cat.get("sources") or {}
    for sid, s in srcs.items():
        for k in ("name", "homepage", "license", "placements", "content_id", "fetch", "evidence"):
            if not s.get(k):
                errs.append("source %s: missing %s" % (sid, k))
        f = s.get("fetch") or {}
        if not f.get("hosts") or not isinstance(f.get("delay_s"), (int, float)) or not f.get("rule"):
            errs.append("source %s: fetch needs hosts, delay_s and rule" % sid)
        if s.get("content_id") not in CONTENT_ID:
            errs.append("source %s: content_id must be one of %s" % (sid, ", ".join(CONTENT_ID)))
    for use, p in (cat.get("presets") or {}).items():
        if not set(p.get("shelves") or []) <= set(SHELVES):
            errs.append("preset %s: unknown shelf in %s" % (use, p.get("shelves")))
        e = p.get("energy") or [0, 1]
        if not (len(e) == 2 and 0 <= e[0] <= e[1] <= 1):
            errs.append("preset %s: energy must be [lo, hi] within 0..1" % use)
    qg = cat.get("quality_gate")
    if not isinstance(qg, dict) or not qg.get("checked") or not isinstance(qg.get("fail_if"), dict):
        errs.append("quality_gate must record when the tracks were checked and the thresholds (fail_if)")
    ids, urls = set(), set()
    for t in cat.get("tracks") or []:
        tid = t.get("id") or "?"
        pre = "track %s: " % tid
        for k in ("id", "title", "artist", "source", "landing_url", "file_url", "format", "license", "license_url",
                  "placements", "content_id", "shelf", "moods", "tempo", "uses", "vocals", "ending"):
            if t.get(k) in (None, "", []):
                errs.append(pre + "missing " + k)
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", tid):
            errs.append(pre + "id must be lowercase words joined by '-'")
        if tid in ids:
            errs.append(pre + "duplicate id")
        ids.add(tid)
        if t.get("file_url") in urls:
            errs.append(pre + "duplicate file_url")
        urls.add(t.get("file_url"))
        if not (isinstance(t.get("bytes"), int) and t["bytes"] > 0):
            errs.append(pre + "bytes must be a positive integer")
        if not (isinstance(t.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", t["sha256"])):
            errs.append(pre + "sha256 must be 64 lowercase hex characters")
        if not (isinstance(t.get("duration"), (int, float)) and t["duration"] > 0):
            errs.append(pre + "duration must be positive seconds")
        if not (isinstance(t.get("energy"), (int, float)) and 0 <= t["energy"] <= 1):
            errs.append(pre + "energy must be 0..1")
        for k, allowed in (("shelf", SHELVES), ("tempo", TEMPOS), ("vocals", VOCALS), ("ending", ENDINGS),
                           ("content_id", CONTENT_ID)):
            if t.get(k) not in allowed:
                errs.append(pre + "%s %r is not one of %s" % (k, t.get(k), ", ".join(allowed)))
        d = t.get("duration") if isinstance(t.get("duration"), (int, float)) else 0
        for k in ("quiet_intro_s", "lead_silence_s", "highlight_s"):
            v = t.get(k)
            if not (isinstance(v, (int, float)) and 0 <= v < max(d, 1)):
                errs.append(pre + "%s must be measured seconds within the track" % k)
        if t.get("loops") not in (True, False, None):
            errs.append(pre + "loops must be true, false or null")
        if t.get("status", "active") not in ("active", "vetoed"):
            errs.append(pre + "status must be active or vetoed")
        if not set(t.get("placements") or []) <= set(PLACEMENTS):
            errs.append(pre + "unknown placement in %s" % t.get("placements"))
        s = srcs.get(t.get("source"))
        if s is None:
            errs.append(pre + "unknown source %r" % t.get("source"))
        lic = t.get("license")
        if lic not in LICENSES:
            errs.append(pre + "license %r is not allowed (only %s)" % (lic, ", ".join(LICENSES)))
            continue
        for k in ("file_url", "landing_url", "license_url"):
            u = str(t.get(k) or "")
            if not u.startswith("https://") and not (k == "license_url" and u.startswith("http://creativecommons.org/")):
                errs.append(pre + "%s must be https" % k)
        host = (urllib.parse.urlparse(str(t.get("file_url") or "")).hostname or "").lower()
        if any(host == h or host.endswith("." + h) for h in REFUSED_HOSTS):
            errs.append(pre + "file host %s is not allowed (its terms forbid library use)" % host)
        if s is not None and not any(host == h or host.endswith("." + h) for h in (s.get("fetch") or {}).get("hosts", [])):
            errs.append(pre + "file host %s is not one of source %s's hosts" % (host, t.get("source")))
        if LICENSES[lic][0]:
            a = t.get("attribution") or ""
            if not a.strip():
                errs.append(pre + "%s needs an attribution text" % lic)
            else:
                if t.get("artist", "\0") not in a:
                    errs.append(pre + "attribution must name the artist")
                if t.get("title", "\0").lower() not in a.lower():
                    errs.append(pre + "attribution must name the title")
                if not re.search(r"CC[ -]?BY|By Attribution", a):
                    errs.append(pre + "attribution must name the license")
            for p in ("description", "credits_file"):
                if p not in (t.get("placements") or []):
                    errs.append(pre + "a CC BY track must list %r in placements" % p)
        if s is not None and s.get("attribution_format") and LICENSES[lic][0]:
            want = s["attribution_format"].format(**{k: t.get(k, "") for k in ("title", "artist", "landing_url",
                                                                                  "license_url")},
                                                  license_label=LICENSES[lic][1])
            if (t.get("attribution") or "").strip() != want.strip():
                errs.append(pre + "attribution differs from the source's required format: %r" % want)
        if s is not None and t.get("content_id") != s.get("content_id") and s.get("content_id") != "unknown":
            errs.append(pre + "content_id must match its source (%s)" % s.get("content_id"))
    return errs


# ------------------------------------------------------------------------------------------ vetoes
def cache_root() -> Path:
    env = os.environ.get("SHOWTIME_MUSIC_CACHE")
    return Path(os.path.expanduser(env)) if env else home() / "music"


def _veto_file() -> Path:
    return cache_root() / "vetoes.json"


def vetoed_ids() -> Dict[str, Any]:
    d = read_json(_veto_file(), {}) if _veto_file().is_file() else {}
    return dict(d.get("vetoed") or {}) if isinstance(d, dict) else {}


def veto(ids: Iterable[str], reason: str = "", undo: bool = False) -> Dict[str, Any]:
    v = vetoed_ids()
    changed = []
    for i in ids:
        t = get(i)
        if undo:
            if v.pop(t["id"], None) is not None:
                changed.append(t["id"])
        else:
            v[t["id"]] = {"reason": reason, "at": time.strftime("%Y-%m-%d")}
            changed.append(t["id"])
    write_json(_veto_file(), {"schema": "showtime.music.vetoes/1", "vetoed": v})
    return {"changed": changed, "vetoed": sorted(v), "file": str(_veto_file())}


# ------------------------------------------------------------------------------------------ search
def _rng(v: Any) -> Optional[Tuple[float, float]]:
    if v is None or v == "":
        return None
    if isinstance(v, (list, tuple)):
        return float(v[0]), float(v[1])
    s = str(v).strip()
    if "-" in s[1:]:
        a, b = s.split("-", 1) if not s.startswith("-") else (s, s)
        return float(a), float(b)
    x = float(s)
    return max(0.0, x - 0.15), min(1.0, x + 0.15)


def _words(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, str):
        v = re.split(r"[,\s]+", v)
    return [w.strip().lower() for w in v if w and w.strip()]


def preset(use: Optional[str], cat: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not use:
        return {}
    cat = cat or load_catalog()
    ps = cat.get("presets") or {}
    u = use.strip().lower()
    if u in ps:
        return dict(ps[u], name=u)
    raise ShowtimeError("unknown use %r" % use, hint="one of: %s" % ", ".join(sorted(ps)))


def search(words: Any = None, *, use: Optional[str] = None, shelf: Any = None, mood: Any = None, energy: Any = None,
           dur: Optional[float] = None, min_dur: Optional[float] = None, max_dur: Optional[float] = None,
           vocals: Any = None, source_id: Any = None, license: Any = None, ending: Any = None,
           include_vetoed: bool = False, limit: int = 10, cat: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Ranked tracks: [{"track", "score", "why"}]. `use` applies a preset (launch, explainer, ...)."""
    cat = cat or load_catalog()
    pre = preset(use, cat)
    shelves = _words(shelf) or list(pre.get("shelves") or [])
    moods = _words(mood)
    ws = _words(words)
    e_rng = _rng(energy) or (tuple(pre["energy"]) if pre.get("energy") else None)
    voc = _words(vocals) or list(pre.get("vocals") or [])
    srcs = _words(source_id)
    lics = [x.lower() for x in _words(license)]
    ends = _words(ending)
    out = []
    for t in tracks(cat, include_vetoed=include_vetoed):
        why: List[str] = []
        score = 0.0
        if srcs and not any(t["source"].startswith(s) for s in srcs):
            continue
        if lics and not any(t["license"].lower().startswith(l) or (l == "cc-by" and t["license"].startswith("CC-BY"))
                            or (l in ("pd", "public-domain") and t["license"] in ("CC-PDDC", "CC-PDM-1.0"))
                            for l in lics):
            continue
        if voc and t["vocals"] not in voc:
            continue
        if ends and t["ending"] not in ends:
            continue
        d = float(t["duration"])
        if min_dur and d < min_dur:
            continue
        if max_dur and d > max_dur:
            continue
        if e_rng:
            lo, hi = e_rng
            e = float(t["energy"])
            if e < lo - 0.1 or e > hi + 0.1:
                continue
            gap = max(0.0, lo - e, e - hi)
            score -= 4 * gap + 1.5 * abs(e - (lo + hi) / 2)     # nearer the middle of the asked range ranks higher
        if shelves:
            if t["shelf"] in shelves:
                score += 3 - 0.3 * shelves.index(t["shelf"])
                why.append(t["shelf"])
            elif not ws and not moods:
                continue
        if pre and pre.get("name") in t["uses"]:
            score += 2.5
            why.append("made for %s" % pre["name"])
        hay = " ".join([t["id"], t["title"].lower(), t["artist"].lower(), t["shelf"], " ".join(t["moods"]),
                        " ".join(t["uses"]), " ".join(t.get("instruments") or []), (t.get("notes") or "").lower()])
        for m in moods:
            if m in t["moods"]:
                score += 2
                why.append(m)
            elif m in hay:
                score += 0.8
        hits = [w for w in ws if w in hay]
        if ws and not hits:
            continue
        score += 1.5 * len(hits)
        if dur:
            if d < dur:
                score -= 3 * (dur - d) / dur          # would need a loop
            else:
                score -= 0.4 * min(2.0, (d - dur) / max(dur, 1.0))   # a small slice of a long piece
        if t.get("featured"):
            score += 1.0
            why.append("featured")
        if pre.get("max_intro_s") is not None and t.get("quiet_intro_s") and t["quiet_intro_s"] > pre["max_intro_s"]:
            score -= 1.0
        out.append({"track": t, "score": round(score, 3), "why": why})
    # equal scores: a stable order that differs per use, so ties are not settled alphabetically
    salt = (pre.get("name") or "") + "|" + " ".join(ws + moods + shelves)
    out.sort(key=lambda r: (-r["score"], hashlib.sha1((salt + r["track"]["id"]).encode("utf-8")).hexdigest()))
    return out[: max(1, int(limit))] if limit else out


def pick(use: Optional[str] = None, dur: Optional[float] = None, n: int = 0, **kw: Any) -> Dict[str, Any]:
    """The n-th best track for a use (0 = best). Raises when nothing matches."""
    res = search(use=use, dur=dur, limit=max(10, n + 1), **kw)
    if not res:
        raise ShowtimeError("no catalog track matches %s" % json.dumps({k: v for k, v in dict(kw, use=use, dur=dur).items()
                                                                          if v not in (None, "", [])}),
                            hint="loosen the filters, or compose one: showtime audio compose --style underscore")
    return res[min(n, len(res) - 1)]["track"]


def resolve(ref: Any, dur: Optional[float] = None) -> Dict[str, Any]:
    """A track from an id string or {"use"/"shelf"/"mood"/"energy"/"words", "pick": n} (a mix.json source)."""
    if isinstance(ref, str):
        return get(ref)
    if isinstance(ref, dict):
        if ref.get("id"):
            return get(ref["id"])
        q = {k: ref.get(k) for k in ("shelf", "mood", "energy", "vocals", "license", "ending") if ref.get(k) is not None}
        q["source_id"] = ref.get("source")
        return pick(use=ref.get("use") or ref.get("for"), dur=ref.get("dur") or dur, n=int(ref.get("pick", 0)),
                    words=ref.get("words") or ref.get("search"), **q)
    raise ShowtimeError("bad catalog reference %r" % (ref,), hint='use a track id or {"use": "launch"}')


# ------------------------------------------------------------------------------------------ fetch + cache
def cached_path(t: Dict[str, Any]) -> Path:
    return cache_root() / t["source"] / ("%s.%s" % (t["id"], t.get("format") or "mp3"))


def _ok_marker(p: Path) -> Path:
    return p.with_name(p.name + ".sha256")


def is_cached(t: Dict[str, Any]) -> bool:
    """True when the verified file is present (size + the sha256 recorded at verification)."""
    p = cached_path(t)
    try:
        if p.stat().st_size != int(t["bytes"]):
            return False
        return _ok_marker(p).read_text(encoding="ascii").strip() == t["sha256"]
    except (OSError, ValueError):
        return False


def _seed_dirs(extra: Optional[Sequence[str]] = None) -> List[Path]:
    dirs = list(extra or []) + [d for d in os.environ.get("SHOWTIME_SEED_DIRS", "").split(os.pathsep) if d]
    return [Path(os.path.expanduser(d)) for d in dirs if d and Path(os.path.expanduser(d)).is_dir()]


def _from_seed(t: Dict[str, Any], seeds: List[Path]) -> Optional[Path]:
    """A local copy with the same size and sha256 (a seed folder made on another machine)."""
    want = int(t["bytes"])
    names = {Path(urllib.parse.unquote(urllib.parse.urlparse(t["file_url"]).path)).name, cached_path(t).name}
    for d in seeds:
        cands = [d / n for n in names] + [d / t["source"] / cached_path(t).name]
        for c in cands:
            try:
                if c.is_file() and c.stat().st_size == want and sha256_file(c) == t["sha256"]:
                    return c
            except OSError:
                continue
    return None


_last_hit: Dict[str, float] = {}


def _polite(t: Dict[str, Any]) -> None:
    delay = float((source(t).get("fetch") or {}).get("delay_s", 1.0))
    host = urllib.parse.urlparse(t["file_url"]).hostname or ""
    wait = _last_hit.get(host, 0.0) + delay - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()


def fetch(ref: Any, purpose: Optional[str] = None, seeds: Optional[Sequence[str]] = None, force: bool = False,
          quiet: bool = False) -> Path:
    """The local file of a catalog track: cached, seeded, or downloaded now (announced) and verified."""
    from ..assets import net
    t = ref if isinstance(ref, dict) and ref.get("sha256") else resolve(ref)
    p = cached_path(t)
    if not force and is_cached(t):
        return p
    with cache_lock(p, timeout=900.0):
        if not force and is_cached(t):
            return p
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.is_file() and not force and p.stat().st_size == int(t["bytes"]) and sha256_file(p) == t["sha256"]:
            _ok_marker(p).write_text(t["sha256"], encoding="ascii")
            return p
        seeded = _from_seed(t, _seed_dirs(seeds))
        if seeded is not None:
            shutil.copyfile(str(seeded), str(p))
            _ok_marker(p).write_text(t["sha256"], encoding="ascii")
            if not quiet:
                log("music: %s by %s copied from the seed folder %s" % (t["title"], t["artist"], seeded.parent))
            return p
        if net.offline():
            raise ShowtimeError("%r by %s is not downloaded yet and SHOWTIME_OFFLINE=1 is set" % (t["title"], t["artist"]),
                                why="catalog music is fetched from its creator's site the first time it is used",
                                hint="run `showtime audio music fetch %s` while online (or `showtime setup --full`), "
                                     "or pick a composed bed: showtime audio compose --style underscore" % t["id"])
        if not quiet:
            log("fetching %s by %s (%s) for %s" % (t["title"], t["artist"], human_size(t["bytes"]),
                                                   purpose or "the soundtrack"))
        _polite(t)
        part = p.with_name(".%s.%d.part" % (p.name, os.getpid()))
        try:
            info = net.download(t["file_url"], part, max_bytes=int(t["bytes"]) + (1 << 20), timeout=120, retries=2)
            if info["bytes"] != int(t["bytes"]) or info["sha256"] != t["sha256"]:
                raise ShowtimeError("%s changed upstream (got %s, %s; the catalog pins %s, %s)" % (
                    t["file_url"], human_size(info["bytes"]), info["sha256"][:12], human_size(t["bytes"]), t["sha256"][:12]),
                    why="the file at the creator's site is not the one that was listened to and credited",
                    hint="pick another track (`showtime audio music pick ...`) and report the id %s so the catalog is "
                         "re-pinned" % t["id"])
            os.replace(str(part), str(p))
        finally:
            if part.exists():
                try:
                    part.unlink()
                except OSError:
                    pass
        _ok_marker(p).write_text(t["sha256"], encoding="ascii")
        (p.with_name(p.name + ".license.json")).write_text(json.dumps(credit_item(t), indent=2), encoding="utf-8")
    return p


def match_file(path: Path) -> Optional[Dict[str, Any]]:
    """The catalog track a local file is a byte-for-byte copy of (same size, then sha256), or None: a
    track copied into a project and mixed as a plain "file" keeps its credit."""
    try:
        size = Path(path).stat().st_size
        cands = [t for t in tracks() if int(t["bytes"]) == size]
    except (OSError, ShowtimeError):
        return None
    if not cands:
        return None
    digest = sha256_file(path)
    return next((t for t in cands if t["sha256"] == digest), None)


def fetch_many(ts: Iterable[Dict[str, Any]], seeds: Optional[Sequence[str]] = None, purpose: str = "offline use",
               progress: Any = None) -> Dict[str, Any]:
    rep: Dict[str, Any] = {"fetched": [], "cached": [], "failed": []}
    ts = list(ts)
    todo = [t for t in ts if not is_cached(t)]
    rep["cached"] = [t["id"] for t in ts if t not in todo]
    total = sum(int(t["bytes"]) for t in todo)
    if todo:
        (progress or log)("music catalog: %d track(s) to fetch (%s), %d already cached" % (len(todo), human_size(total),
                                                                                          len(rep["cached"])))
    for i, t in enumerate(todo, 1):
        try:
            fetch(t, purpose="%s [%d/%d]" % (purpose, i, len(todo)), seeds=seeds)
            rep["fetched"].append(t["id"])
        except ShowtimeError as e:
            warn("%s: %s" % (t["id"], e))
            rep["failed"].append({"id": t["id"], "error": str(e)})
    return rep


def beats_for(p: Path) -> Optional[Dict[str, Any]]:
    """The beats.json of a cached track (analysed once, stored next to it)."""
    side = p.with_name(p.name + ".beats.json")
    if side.is_file():
        try:
            return read_json(side)
        except ShowtimeError:
            pass
    try:
        from . import beats
        d = beats.analyze(p, max_seconds=None)
    except Exception as e:  # noqa: BLE001 - analysis is an aid; the track still plays
        warn("beat analysis of %s failed: %s" % (p.name, e))
        return None
    try:
        write_json(side, d, indent=None)
    except OSError:
        pass
    return d


# ------------------------------------------------------------------------------------------ credits
def end_card_line(t: Dict[str, Any]) -> str:
    lab = LICENSES.get(t["license"], (True, t["license"], ""))[1]
    title = t["title"]
    if t.get("source") == "incompetech":
        return "Music: %s by Kevin MacLeod (incompetech.com), %s" % (title, lab)
    return "Music: “%s” by %s (%s)" % (title, t["artist"], lab)


def credit_item(t: Dict[str, Any]) -> Dict[str, Any]:
    """What the credits pipeline needs about one catalog track (TASL + where the credit must go)."""
    s = source(t)
    need = needs_attribution(t)
    item = {
        "id": "music:" + t["id"], "kind": "music", "title": t["title"], "artist": t["artist"],
        "source": s.get("name") or t["source"], "source_url": t["landing_url"], "license": t["license"],
        "license_url": t["license_url"], "attribution_required": need,
        "attribution": t.get("attribution") if need else None,
        "credit_optional": None if need else (t.get("credit_optional") or "%s by %s (%s)" % (
            t["title"], t["artist"], LICENSES[t["license"]][1])),
        "placements": list(t.get("placements") or []), "content_id": t.get("content_id"),
        "content_id_note": s.get("content_id_note"), "end_card": end_card_line(t),
    }
    return item


def board_rows(cat: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Flat rows for the curation board (id, title, artist, shelf, preview URL, landing, credit ...)."""
    cat = cat or load_catalog()
    rows = []
    for t in tracks(cat):
        rows.append({k: t.get(k) for k in ("id", "title", "artist", "source", "shelf", "moods", "energy", "tempo",
                                           "uses", "vocals", "duration", "license", "landing_url", "file_url",
                                           "ending", "status", "notes")})
        rows[-1]["credit"] = t.get("attribution") or credit_item(t)["credit_optional"]
    return rows


def stats(cat: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cat = cat or load_catalog()
    by: Dict[str, Dict[str, int]] = {"shelf": {}, "source": {}, "license": {}}
    total_b = 0
    total_s = 0.0
    cached = 0
    for t in tracks(cat):
        for k in by:
            by[k][t[k]] = by[k].get(t[k], 0) + 1
        total_b += int(t["bytes"])
        total_s += float(t["duration"])
        cached += 1 if is_cached(t) else 0
    return {"tracks": len(tracks(cat)), "hours": round(total_s / 3600, 1), "download_size": human_size(total_b),
            "download_bytes": total_b, "cached": cached, "cache": str(cache_root()), "vetoed": sorted(vetoed_ids()), **by}

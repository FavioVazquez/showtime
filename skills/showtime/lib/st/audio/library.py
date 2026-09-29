"""The local audio library: fetch, generate, analyse, catalog, credit.

Sources are pinned in library_manifest.json (URL + size + sha256 + license,
curated when the skill is authored; nothing is crawled at install time).
Tiers:
  core       all Kenney CC0 audio packs, pinned OpenGameArt CC0 packs and
             ambiences, ~45 incompetech CC-BY beds/stings (Opus 128k),
             allow-listed Internet Archive CC0 music
  extended   core + more incompetech music, more Internet Archive CC0 items
  generated  ~160 procedural SFX variants + 24 composed beds rendered locally
             (included with every fetch unless --no-generated)
  byo        folders the user indexes in place (`lib index`), never copied

Layout (~/.showtime/library, or $SHOWTIME_LIBRARY):
  music/<source>/...   sfx/<source>/...   ambience/<source>/...
  catalog.json         one entry per file (schema showtime.audio.catalog/1)
  CREDITS-SOURCES.md   every source with its license and credit line
  state.json           installed sources (sha256, file list)

Every file is analysed: duration, loudness (integrated LUFS / true peak, or
peak/RMS and max momentary loudness for clips under 0.4 s), hit point for
effects, bpm/beats/key/rhythmic flag (beats sidecar) for music, loopability,
brightness, and tags derived from file names and source metadata.
"""
from __future__ import annotations

import concurrent.futures as cf
import fnmatch
import json
import math
import os
import re
import shutil
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Iterable, List, Optional

import numpy as np

from ..common import ShowtimeError, human_size, home, log, read_json, sha256_file, warn, write_json
from . import SR

MANIFEST = Path(__file__).with_name("library_manifest.json")
TIERS = ("core", "extended")
AUDIO_EXT = (".ogg", ".wav", ".mp3", ".flac", ".opus", ".m4a", ".aif", ".aiff")
KIND_DIR = {"music": "music", "stinger": "music", "sfx": "sfx", "voice": "sfx", "ambience": "ambience"}
GENERIC_DIRS = {"audio", "sounds", "sound", "sfx", "ogg", "wav", "mp3", "files", "sound effects"}

# file-name stem -> tags (Kenney/OGA names are descriptive: impactMetal_heavy_003, click_002 ...)
STEM_TAGS = [
    (r"click|tap|mouseclick|mouserelease|select", ["click", "ui"]),
    (r"tick", ["tick", "ui"]),
    (r"switch|toggle", ["switch", "toggle", "ui"]),
    (r"rollover|hover", ["hover", "ui"]),
    (r"confirm|success|correct|win|achiev|congrat|level_?up|power_?up|objective", ["success", "positive"]),
    (r"error|wrong|fail|denied|lose|loser|game_?over", ["error", "negative"]),
    (r"back|close|minimi[sz]e", ["close", "ui"]),
    (r"open|maximi[sz]e", ["open", "ui"]),
    (r"question", ["question", "ui"]),
    (r"drop", ["drop"]),
    (r"scroll", ["scroll", "ui"]),
    (r"glitch", ["glitch", "digital"]),
    (r"laser|zap|beam|phaser", ["laser", "sci-fi"]),
    (r"explosion|boom|blast", ["explosion", "impact"]),
    (r"impact|hit|punch|thud|knock|slam", ["impact"]),
    (r"footstep|step", ["footstep", "foley"]),
    (r"coin|chip|cash|money", ["coin", "reward"]),
    (r"card", ["card", "foley"]),
    (r"dice|die[-_]", ["dice", "foley"]),
    (r"digital|computer|beep|bleep|tone", ["digital", "tech"]),
    (r"engine|thruster|motor", ["engine", "drone"]),
    (r"whoosh|swish|swoosh|woosh|swing|whip", ["whoosh", "transition"]),
    (r"jingle|sting|fanfare", ["jingle", "stinger"]),
    (r"glass", ["glass"]),
    (r"metal|anvil|clang", ["metal"]),
    (r"wood|plank", ["wood"]),
    (r"plop|bubble|pop", ["pop"]),
    (r"scratch|scrape", ["scrape"]),
    (r"door", ["door", "foley"]),
    (r"book|page|paper", ["paper", "foley"]),
    (r"cloth|leather|belt", ["cloth", "foley"]),
    (r"bell|gong|chime|ding", ["bell", "tonal"]),
    (r"force_?field|shield", ["forcefield", "sci-fi"]),
    (r"rain|storm|thunder", ["rain", "weather"]),
    (r"wind|gust", ["wind", "weather"]),
    (r"wave|ocean|sea|beach|river|water|splash", ["water"]),
    (r"bird|chirp|forest|park|cricket|frog", ["nature"]),
    (r"fire|crackl", ["fire"]),
    (r"traffic|road|city|street|car", ["city", "urban"]),
    (r"crowd|people|chatter", ["crowd"]),
    (r"loop", ["loop"]),
    (r"8[-_ ]?bit|retro|chip", ["retro", "8bit"]),
    (r"sax", ["sax", "jazz"]),
    (r"pizzicato", ["pizzicato", "strings"]),
    (r"steel", ["steel-drums"]),
    (r"magic|spell|sparkle", ["magic"]),
    (r"alarm|siren", ["alarm"]),
    (r"type|typing|keyboard|key_", ["keyboard"]),
    (r"shutter|camera", ["camera"]),
]

CATEGORY_RULES = [  # first match wins (sfx only)
    ("transition", {"whoosh", "transition", "riser", "swish", "swoosh", "reverse"}),
    ("impact", {"impact", "explosion", "punch", "boom", "slam"}),
    ("musical", {"jingle", "stinger", "sting"}),
    ("ui", {"ui", "click", "tick", "switch", "toggle", "hover", "interface", "success", "error", "select"}),
    ("fx", {"laser", "sci-fi", "digital", "glitch", "retro", "8bit", "magic", "forcefield", "engine", "tech"}),
    ("foley", {"foley", "footstep", "door", "paper", "cloth", "glass", "wood", "metal", "coin", "card", "dice", "water"}),
]


# ---------------------------------------------------------------------------------------------
# paths / catalog
# ---------------------------------------------------------------------------------------------
def library_dir() -> Path:
    """~/.showtime/library, or $SHOWTIME_LIBRARY (e.g. a library on an external drive)."""
    env = os.environ.get("SHOWTIME_LIBRARY")
    return Path(os.path.expanduser(env)) if env else home() / "library"


def catalog_path() -> Path:
    return library_dir() / "catalog.json"


def load_manifest(path: Optional[Path] = None) -> dict:
    return read_json(path or MANIFEST)


def load_catalog(required: bool = True) -> dict:
    """The catalog. required=True and nothing installed yet: the starter part (~41 MB) is fetched
    first (announced; offline this raises with the `setup --full` / `--seed` fix)."""
    p = catalog_path()
    if not p.is_file() and required and not os.environ.get("SHOWTIME_LIBRARY"):
        from . import libparts
        libparts.ensure_starter("the audio library")
    if not p.is_file():
        if required:
            raise ShowtimeError("the audio library is not installed",
                                hint="run `showtime audio lib fetch` (the core tier, ~249 MB) or "
                                     "`showtime audio lib fetch --part starter` (~41 MB)")
        return {"schema": "showtime.audio.catalog/1", "items": []}
    return read_json(p)


def save_catalog(cat: dict) -> None:
    cat["schema"] = "showtime.audio.catalog/1"
    cat["generated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    cat["count"] = len(cat.get("items", []))
    write_json(catalog_path(), cat, indent=1)


def item_path(item: dict) -> Path:
    p = Path(item["path"])
    return p if p.is_absolute() else library_dir() / p


def get_item(item_id: str) -> dict:
    cat = load_catalog()
    for it in cat["items"]:
        if it["id"] == item_id:
            return it
    # forgiving lookups: case-insensitive, or unique suffix
    low = item_id.lower()
    hits = [it for it in cat["items"] if it["id"].lower() == low or it["id"].lower().endswith("/" + low)]
    if len(hits) == 1:
        return hits[0]
    raise ShowtimeError("no library item %r" % item_id, hint="find ids with `showtime audio lib search <words>`")


_SIZES: Dict[str, Dict[int, List[dict]]] = {}


def match_file(path: Path) -> Optional[dict]:
    """The library item a file is a byte-for-byte copy of (same size, then same sha256), or None. Keeps
    the license and credit of a library track that was copied into a project and used as a "file"."""
    try:
        size = Path(path).stat().st_size
    except OSError:
        return None
    key = str(catalog_path())
    if key not in _SIZES:
        try:
            cat = load_catalog(required=False)
        except ShowtimeError:
            return None
        by: Dict[int, List[dict]] = {}
        for it in cat.get("items", []):
            try:
                by.setdefault(item_path(it).stat().st_size, []).append(it)
            except OSError:
                continue
        _SIZES[key] = by
    digest = None
    for it in _SIZES[key].get(size, []):
        digest = digest or sha256_file(path)
        if sha256_file(item_path(it)) == digest:
            return it
    return None


def resolve(ref: Any) -> dict:
    """An item from an id string, {"id": ...} or {"search": {...}, "pick": n}."""
    if isinstance(ref, str):
        return get_item(ref)
    if isinstance(ref, dict):
        if ref.get("id"):
            return get_item(ref["id"])
        q = ref.get("search") or {k: v for k, v in ref.items() if k != "pick"}
        from . import search
        res = search.search(**search.normalize_query(q), limit=max(1, int(ref.get("pick", 0)) + 1))
        if not res:
            raise ShowtimeError("library search matched nothing: %s" % json.dumps(q))
        return res[min(len(res) - 1, int(ref.get("pick", 0)))]["item"]
    raise ShowtimeError("bad library reference %r" % (ref,))


# ---------------------------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------------------------
_last_hit: Dict[str, float] = {}


def _polite(url: str, delays: Dict[str, float]) -> None:
    host = urllib.parse.urlparse(url).hostname or ""
    d = next((v for k, v in delays.items() if host.endswith(k)), 0.5)
    wait = _last_hit.get(host, 0.0) + d - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()


_SSL = None


def _ssl_context():
    """Prefer certifi's CA bundle (installed with requests) so HTTPS works the same on every OS,
    including Python builds that do not see the system certificate store."""
    global _SSL
    if _SSL is None:
        import ssl
        try:
            import certifi
            _SSL = ssl.create_default_context(cafile=certifi.where())
        except Exception:  # noqa: BLE001
            _SSL = ssl.create_default_context()
    return _SSL


_SEED_INDEX: Optional[Dict[int, List[Path]]] = None


def _seeded(sha256: Optional[str], size: Optional[int]) -> Optional[Path]:
    """A copy of a pinned file in $SHOWTIME_SEED_DIRS (`showtime setup --seed DIR`), matched by size + sha256."""
    global _SEED_INDEX
    dirs = [Path(d) for d in os.environ.get("SHOWTIME_SEED_DIRS", "").split(os.pathsep) if d]
    if not dirs or not sha256 or not size:
        return None
    if _SEED_INDEX is None:
        _SEED_INDEX = {}
        for root in dirs:
            for dirpath, _, names in os.walk(str(root)):
                for n in names:
                    p = Path(dirpath) / n
                    try:
                        _SEED_INDEX.setdefault(p.stat().st_size, []).append(p)
                    except OSError:
                        continue
    for p in _SEED_INDEX.get(int(size), []):
        try:
            if sha256_file(p) == sha256:
                return p
        except OSError:
            continue
    return None


def download(url: str, dest: Path, ua: str, delays: Dict[str, float], sha256: Optional[str] = None,
             size: Optional[int] = None, retries: int = 3) -> Path:
    if dest.is_file() and (not sha256 or sha256_file(dest) == sha256) and (not size or dest.stat().st_size == size):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    seed = _seeded(sha256, size)
    if seed is not None:
        tmp = dest.with_name(dest.name + ".part")
        shutil.copyfile(str(seed), str(tmp))
        os.replace(str(tmp), str(dest))
        return dest
    if os.environ.get("SHOWTIME_OFFLINE", "").strip().lower() not in ("", "0", "false", "no"):
        raise ShowtimeError("%s is not downloaded and showtime is offline" % url,
                            hint="seed it: `showtime setup --seed DIR --fetch audio-library` with the files from "
                                 "`showtime setup --plan --urls`", code=3)
    tmp = dest.with_name(dest.name + ".part")
    last_err: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            _polite(url, delays)
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=120, context=_ssl_context()) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            if size and tmp.stat().st_size != size:
                raise ShowtimeError("size mismatch for %s: got %d, expected %d" % (url, tmp.stat().st_size, size))
            if sha256:
                got = sha256_file(tmp)
                if got != sha256:
                    raise ShowtimeError("sha256 mismatch for %s (upstream changed?)" % url,
                                        hint="the manifest pin is stale; report it or re-pin with `showtime audio lib pin`")
            os.replace(str(tmp), str(dest))
            return dest
        except ShowtimeError as e:
            last_err = e
            if "mismatch" in str(e):
                break
        except Exception as e:  # noqa: BLE001 - network errors: retry
            last_err = e
            time.sleep(2 * attempt)
    try:
        tmp.unlink()
    except OSError:
        pass
    raise ShowtimeError("download failed: %s (%s)" % (url, last_err))


# ---------------------------------------------------------------------------------------------
# tagging / analysis
# ---------------------------------------------------------------------------------------------
def slug(s: str) -> str:
    s = re.sub(r"([a-z])([A-Z])", r"\1-\2", s)
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def stem_tags(name: str) -> List[str]:
    tags: List[str] = []
    for pat, t in STEM_TAGS:
        if re.search(pat, name, re.I):
            tags += t
    return tags


def group_of(source_id: str, stem: str) -> str:
    base = re.sub(r"([_\-\s(]*\d+\)?)$", "", stem)
    return "%s/%s" % (source_id, slug(base) or slug(stem))


def category_of(tags: Iterable[str], kind: str) -> Optional[str]:
    if kind in ("music", "stinger"):
        return "musical" if kind == "stinger" else None
    if kind == "ambience":
        return "ambience"
    if kind == "voice":
        return "foley"
    ts = set(tags)
    for cat, keys in CATEGORY_RULES:
        if ts & keys:
            return cat
    return "fx"


def _loopability(x: np.ndarray) -> Dict[str, Any]:
    n = len(x)
    w = min(int(1.0 * SR), n // 4)
    if w < SR // 10:
        return {"loopable": False, "loop_confidence": 0.0}
    m = x.mean(axis=1)

    def lvl(seg):
        return 20 * math.log10(float(np.sqrt((seg.astype(np.float64) ** 2).mean())) + 1e-9)
    body = lvl(m)
    a, b = lvl(m[:w]), lvl(m[-w:])
    faded = b < body - 12 or a < body - 12
    sa = np.abs(np.fft.rfft(m[:w] * np.hanning(w)))
    sb = np.abs(np.fft.rfft(m[-w:] * np.hanning(w)))
    sim = float(np.dot(sa, sb) / (np.linalg.norm(sa) * np.linalg.norm(sb) + 1e-12))
    conf = max(0.0, min(1.0, (sim - 0.6) / 0.35)) * (0.0 if faded else 1.0) * max(0.0, 1 - abs(a - b) / 6)
    return {"loopable": bool(conf >= 0.5), "loop_confidence": round(conf, 2)}


def analyze_file(path: Path, kind: str, base: dict) -> Dict[str, Any]:
    """Measure one library file; `base` holds source-level metadata."""
    from . import beats as beats_mod
    from . import meter, sfx, wav
    x = wav.load(path)
    dur = len(x) / SR
    info: Dict[str, Any] = {"duration": round(dur, 3), "sample_rate": SR, "channels": 2}
    try:
        wi = wav.info(path)
        info.update(source_sample_rate=wi.get("sample_rate"), codec=wi.get("codec"))
    except Exception:  # noqa: BLE001
        pass
    pk = float(np.abs(x).max()) if x.size else 0.0
    rms = float(np.sqrt((x.astype(np.float64) ** 2).mean())) if x.size else 0.0
    info["peak_db"] = round(20 * math.log10(pk + 1e-12), 2)
    info["rms_db"] = round(20 * math.log10(rms + 1e-12), 2)
    if dur >= 0.4:
        info["lufs"] = meter._r(meter.integrated(x))
        info["true_peak"] = meter._r(meter.true_peak(x, oversample=4))
    else:
        info["lufs"] = None
        info["true_peak"] = None
    mm = sfx.max_momentary(x)
    info["momentary_max_lufs"] = round(mm, 2) if math.isfinite(mm) else None
    mono = x.mean(axis=1)
    if mono.size > 256:
        seg = mono[: min(len(mono), 20 * SR)]
        spec = np.abs(np.fft.rfft(seg))
        fr = np.fft.rfftfreq(len(seg), 1 / SR)
        tot = float(spec.sum()) + 1e-12
        info["centroid_hz"] = int(float((spec * fr).sum()) / tot)
        hf = float(spec[fr >= 5000].sum()) / tot
        info["hf_ratio"] = round(hf, 3)
        info["harshness"] = "high" if hf > 0.35 else ("medium" if hf > 0.18 else "low")
    tags = set(base.get("tags", []))
    if kind in ("sfx", "voice"):
        hk = "peak" if tags & {"whoosh", "swish"} else ("end" if tags & {"riser", "reverse"} else "onset")
        info["hit"] = round(float(sfx.hit_time(x, hk)), 4)
        info["hit_kind"] = hk
    if kind in ("music", "ambience") or (kind == "stinger" and dur >= 4):
        info.update(_loopability(x))
    if kind in ("music", "stinger") and dur >= 4:
        try:
            a = beats_mod.analyze(path, known_bpm=base.get("bpm") or None, max_seconds=None)
            side = path.with_name(path.name + ".beats.json")
            write_json(side, a, indent=None)
            info["sidecar"] = str(side.relative_to(library_dir())) if _under(side, library_dir()) else str(side)
            if not base.get("bpm"):
                trust = bool(a.get("rhythmic")) and (a.get("bpm_confidence") or 0) >= 0.4
                info["bpm"] = a["bpm"] if trust else None
                info["bpm_source"] = "estimated" if trust else None
            info["bpm_confidence"] = a.get("bpm_confidence")
            info["key"] = base.get("key") or a.get("key")
            info["key_confidence"] = None if base.get("key") else a.get("key_confidence")
            info["rhythmic"] = a.get("rhythmic")
            info["pacing"] = a.get("pacing")
            if base.get("energy") is None:
                en = np.array(a["energy"]["values"]) if a.get("energy") else np.array([0.5])
                loud = min(1.0, max(0.0, ((info.get("lufs") or -20) + 30) / 20))
                info["energy"] = round(float(0.45 * loud + 0.35 * min(1.0, a.get("onset_rate", 2) / 6) + 0.2 * en.mean()), 2)
        except ShowtimeError as e:
            warn("beat analysis failed for %s: %s" % (path.name, e))
    return info


def _under(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------------------------
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}


def _safe_filename(name: str) -> str:
    """A file name that is valid on Windows, macOS and Linux."""
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f!]+', "_", stem).strip(". ") or "audio"
    if stem.split(".")[0].upper() in _WIN_RESERVED:
        stem = "_" + stem
    return stem[:120] + ("." + ext.lower() if ext else "")


def _member_name(member: str, used: set) -> str:
    parts = [p for p in PurePosixPath(member).parts[:-1] if p.lower() not in GENERIC_DIRS]
    stem = PurePosixPath(member).stem
    ext = PurePosixPath(member).suffix.lower()
    name = stem if not parts else "%s_%s" % (slug(parts[-1]).replace("-", "_"), stem)
    name = re.sub(r"[^A-Za-z0-9_\-().]+", "_", name).strip("_. ") or "sound"
    if name.split(".")[0].upper() in _WIN_RESERVED:
        name = "_" + name
    cand, k = name + ext, 2
    while cand.lower() in used:
        cand = "%s_%d%s" % (name, k, ext)
        k += 1
    used.add(cand.lower())
    return cand


def _matches(name: str, globs: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(name, g) or fnmatch.fnmatch(name.lower(), g.lower()) for g in globs)


def install_source(src: dict, man: dict, keep_downloads: bool = False) -> List[Path]:
    """Download (verify) and unpack/transcode one source; returns the installed files."""
    from . import wav
    ua = man.get("user_agent", "showtime-audio/0.1")
    delays = man.get("host_delays", {})
    url = src["url"]
    name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name
    cache = home() / "cache" / "downloads" / "audio" / src["id"]
    blob = download(url, cache / name, ua, delays, src.get("sha256"), src.get("bytes"))
    src["_sha256"] = src.get("sha256") or sha256_file(blob)
    dest = library_dir() / KIND_DIR.get(src["kind"], "sfx") / src["id"]
    if dest.exists():
        shutil.rmtree(str(dest))
    dest.mkdir(parents=True, exist_ok=True)
    files: List[Path] = []
    include = src.get("include") or ["*"]
    exclude = list(src.get("exclude") or []) + ["*review*", "*Preview*", "__MACOSX/*", "*/._*"]
    transcode = src.get("transcode")
    if src["type"] == "zip":
        used: set = set()
        with zipfile.ZipFile(blob) as z:
            for m in sorted(z.namelist()):
                if m.endswith("/") or not m.lower().endswith(AUDIO_EXT):
                    continue
                if not _matches(m, include) or _matches(m, exclude) or "preview" in m.lower():
                    continue
                tgt = dest / _member_name(m, used)
                with z.open(m) as fsrc, open(tgt, "wb") as fdst:
                    shutil.copyfileobj(fsrc, fdst)
                files.append(tgt)
    else:
        files.append(dest / _safe_filename(name))
        shutil.copy2(str(blob), str(files[0]))
    if transcode:
        out = []
        for f in files:
            ext = {"opus128": ".opus", "opus96": ".opus", "flac": ".flac"}.get(transcode, ".opus")
            br = "96k" if transcode == "opus96" else "128k"
            if f.suffix.lower() == ext:
                out.append(f)
                continue
            t = f.with_suffix(ext)
            wav.transcode(f, t, bitrate=br)
            f.unlink()
            out.append(t)
        files = out
    if not keep_downloads:
        shutil.rmtree(str(cache), ignore_errors=True)
    if not files:
        raise ShowtimeError("source %s produced no audio files (include globs %s)" % (src["id"], include))
    return files


def _item_for(src: dict, f: Path, info: Dict[str, Any]) -> Dict[str, Any]:
    kind = src["kind"]
    single = src["type"] != "zip"
    stem = f.stem
    tags = set(src.get("tags", [])) | set(src.get("base_tags", [])) | set(stem_tags(stem))
    if kind in ("music", "stinger"):
        tags |= {"music"} if kind == "music" else {"stinger", "music"}
    tags = sorted(t for t in tags if t)
    rel = f.relative_to(library_dir()) if _under(f, library_dir()) else f
    it: Dict[str, Any] = {
        "id": src["id"] if single else "%s/%s" % (src["id"], slug(stem)),
        "path": PurePosixPath(*Path(rel).parts).as_posix() if not Path(rel).is_absolute() else str(rel),
        "kind": kind, "title": src.get("title") if single and src.get("title") else stem.replace("_", " "),
        "artist": src.get("artist"), "group": None if single else group_of(src["id"], stem),
        "tags": tags, "mood": src.get("mood", []), "energy": src.get("energy"),
        "bpm": src.get("bpm"), "bpm_source": "metadata" if src.get("bpm") else None, "key": src.get("key"),
        "category": src.get("category") or category_of(tags, kind),
        "license": src["license"], "attribution_required": src["license"] not in ("CC0-1.0", "PDM-1.0", "generated"),
        "attribution": src.get("attribution"), "credit_optional": src.get("credit_optional"),
        "isrc": src.get("isrc"), "redistributable": src.get("redistributable", True),
        "source_id": src["id"], "source_url": src.get("source_url"), "download_url": src.get("url"),
        "sha256": src.get("_sha256"), "tier": src.get("tier", "core"),
    }
    it.update({k: v for k, v in info.items() if v is not None or k not in it})
    if src.get("loopable") is True:
        it["loopable"] = True
    return it


def fetch(tier: str = "core", only: Optional[List[str]] = None, generated: bool = True, force: bool = False,
          keep_downloads: bool = False, workers: int = 3, progress: Optional[Callable[[str], None]] = None) -> Dict:
    """Install every manifest source up to `tier`, analyse, update the catalog."""
    if tier not in TIERS:
        raise ShowtimeError("unknown tier %r (core or extended)" % tier)
    man = load_manifest()
    allowed = TIERS[: TIERS.index(tier) + 1]
    sources = [s for s in man["sources"] if s.get("tier", "core") in allowed]
    if only:
        sources = [s for s in sources if s["id"] in only or any(fnmatch.fnmatch(s["id"], o) for o in only)]
        if not sources:
            raise ShowtimeError("no manifest source matches %s" % ", ".join(only))
    lib = library_dir()
    lib.mkdir(parents=True, exist_ok=True)
    state = read_json(lib / "state.json", {"sources": {}})
    cat = load_catalog(required=False)
    items = {it["id"]: it for it in cat.get("items", [])}
    t0 = time.time()
    report = {"installed": [], "skipped": [], "failed": [], "items_added": 0}
    total_bytes = sum(int(s.get("bytes") or 0) for s in sources)
    log("audio library: %d sources in tier %s (~%s download)" % (len(sources), tier, human_size(total_bytes)))
    unpinned = [s["id"] for s in sources if not s.get("sha256")]
    if unpinned:
        log("note: %d source(s) have no pinned sha256 yet (extended tier): each file's hash is recorded on its "
            "first download and verified on every re-download (trust on first use)" % len(unpinned))
    for n_, src in enumerate(sources, 1):
        sid = src["id"]
        st = state["sources"].get(sid)
        if st and not force and all((lib / p).is_file() for p in st.get("files", [])) and st.get("url") == src["url"]:
            report["skipped"].append(sid)
            continue
        if not src.get("sha256") and st and st.get("sha256") and st.get("url") == src["url"]:
            src = dict(src, sha256=st["sha256"])  # verify a re-download against the first-use hash
        try:
            msg = "[%d/%d] %s (%s)" % (n_, len(sources), sid, human_size(src.get("bytes")))
            (progress or log)(msg)
            files = install_source(src, man, keep_downloads)
            for k in [k for k, v in items.items() if v.get("source_id") == sid]:
                items.pop(k)
            with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
                infos = list(ex.map(lambda f: analyze_file(f, src["kind"], src), files))
            for f, info in zip(files, infos):
                it = _item_for(src, f, info)
                items[it["id"]] = it
            state["sources"][sid] = {"url": src["url"], "sha256": src.get("_sha256"), "tier": src.get("tier", "core"),
                                     "files": [f.relative_to(lib).as_posix() for f in files],
                                     "installed": time.strftime("%Y-%m-%dT%H:%M:%S")}
            write_json(lib / "state.json", state)
            report["installed"].append(sid)
            report["items_added"] += len(files)
            cat["items"] = sorted(items.values(), key=lambda it: it["id"])
            cat["tier"] = tier
            save_catalog(cat)
        except ShowtimeError as e:
            warn("%s: %s" % (sid, e))
            report["failed"].append({"id": sid, "error": str(e)})
    if generated:
        g = generate(man.get("generated", {}), force=force, progress=progress)
        report["generated"] = g
    cat = load_catalog(required=False)
    write_credits_sources(man, cat)
    report["seconds"] = round(time.time() - t0, 1)
    report["catalog"] = str(catalog_path())
    report["items"] = len(cat.get("items", []))
    report["size"] = human_size(library_size())
    return report


def library_size() -> int:
    tot = 0
    for root, _, files in os.walk(str(library_dir())):
        for f in files:
            try:
                tot += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return tot


# ---------------------------------------------------------------------------------------------
# generated tier
# ---------------------------------------------------------------------------------------------
def generate(spec: dict, force: bool = False, progress: Optional[Callable[[str], None]] = None) -> Dict:
    """Render procedural SFX variants and composed beds into library/{sfx,music}/generated-*."""
    from . import compose, meter, sfx, wav
    lib = library_dir()
    cat = load_catalog(required=False)
    items = {it["id"]: it for it in cat.get("items", [])}
    made = {"sfx": 0, "music": 0, "skipped": 0}
    t0 = time.time()
    sdir = lib / "sfx" / "generated-sfx"
    adir = lib / "ambience" / "generated-ambience"
    mdir = lib / "music" / "generated-music"
    variants = list(_sfx_variants(spec.get("sfx", {})))
    (progress or log)("generating %d procedural sound effects ..." % len(variants))
    for v in variants:
        spec_ = sfx.REGISTRY[v["type"]]
        amb = spec_.category == "ambience"
        vid = "%s-%s" % (v["type"], v["tag"])
        out = (adir if amb else sdir) / (vid + (".opus" if amb else ".flac"))
        iid = ("generated-ambience/" if amb else "generated-sfx/") + vid
        if out.is_file() and iid in items and not force:
            made["skipped"] += 1
            continue
        x, m = sfx.render(v["type"], dur=v.get("dur"), intensity=v["intensity"], seed=v["seed"], key=v["key"])
        if amb:
            wav.save(out, x, bitrate="128k")
        else:
            wav.save(out, x, bits=16)
        rel = out.relative_to(lib).as_posix()
        pk = float(np.abs(x).max())
        items[iid] = {
            "id": iid, "path": rel, "kind": "ambience" if amb else "sfx",
            "title": "%s (%s)" % (v["type"].replace("-", " "), v["tag"]), "artist": "showtime (procedural)",
            "group": ("generated-ambience/" if amb else "generated-sfx/") + v["type"],
            "tags": sorted(set(spec_.tags + [v["type"], "generated", spec_.category])),
            "mood": [], "energy": round(v["intensity"], 2), "bpm": None, "key": m.get("key"),
            "category": spec_.category, "duration": m["duration"], "sample_rate": SR, "channels": 2,
            "hit": m["hit"], "hit_kind": spec_.kind, "peak_db": round(20 * math.log10(pk + 1e-12), 2),
            "momentary_max_lufs": _r2(sfx.max_momentary(x)), "lufs": _r2(meter.integrated(x)) if m["duration"] >= 0.4 else None,
            "loopable": amb, "license": "CC0-1.0", "attribution_required": False,
            "attribution": None, "credit_optional": None, "redistributable": True,
            "source_id": "generated-sfx", "source_url": None, "download_url": None, "sha256": None,
            "tier": "generated", "generator": {"type": v["type"], "dur": v.get("dur"), "intensity": v["intensity"],
                                               "seed": v["seed"], "key": v["key"]},
        }
        made["sfx"] += 1
    beds = spec.get("music", [])
    if beds:
        (progress or log)("composing %d library beds (a few minutes) ..." % len(beds))
    for b in beds:
        vid = "%s-%ds-%s" % (b["style"], int(b["duration"]), slug(b.get("key") or compose.STYLES[compose.resolve_style(b["style"])]["key"]))
        out = mdir / (vid + ".opus")
        iid = "generated-music/" + vid
        # beds composed by an older composer revision are re-rendered (sound fixes reach the library)
        if out.is_file() and iid in items and not force and (items[iid].get("generator") or {}).get("rev") == compose.COMPOSER_REV:
            made["skipped"] += 1
            continue
        tmp = mdir / (vid + ".wav")
        r = compose.build(b["style"], float(b["duration"]), tmp, bpm=b.get("bpm"), key=b.get("key"),
                          sections=b.get("sections"), seed=int(b.get("seed", 0)), stems=False, midi=False)
        wav.transcode(tmp, out, bitrate="128k")
        tmp.unlink()
        bj_src = tmp.with_name(tmp.stem + ".beats.json")
        bj = out.with_name(out.name + ".beats.json")
        doc = read_json(bj_src)
        doc["file"] = out.relative_to(lib).as_posix()
        write_json(bj, doc, indent=None)
        bj_src.unlink()
        st = compose.STYLES[r["style"]]
        items[iid] = {
            "id": iid, "path": out.relative_to(lib).as_posix(), "kind": "music",
            "title": "%s bed %ds in %s" % (r["style"], int(b["duration"]), r["key"]), "artist": "showtime (composed)",
            "group": "generated-music/" + r["style"], "tags": sorted(set(["music", "generated", r["style"]] + st["moods"][:2])),
            "mood": st["moods"], "energy": 0.4 if st["drums"] == "none" else 0.7, "bpm": r["bpm"], "bpm_source": "composed",
            "key": r["key"], "duration": float(b["duration"]), "sample_rate": SR, "channels": 2,
            "lufs": r["master"].get("output_lufs"), "true_peak": r["master"].get("output_tp"),
            "rhythmic": st["drums"] != "none", "pacing": "beat_cut" if st["drums"] != "none" else "phrase_flow",
            "loopable": False, "sidecar": bj.relative_to(lib).as_posix(), "license": "CC0-1.0",
            "attribution_required": False, "attribution": None, "credit_optional": None, "redistributable": True,
            "source_id": "generated-music", "tier": "generated", "category": None,
            "generator": {"style": r["style"], "duration": b["duration"], "key": r["key"], "bpm": r["requested_bpm"],
                          "seed": int(b.get("seed", 0)), "backend": r["backend"], "rev": compose.COMPOSER_REV},
            "end_hit": r["end_hit"], "sections": [{"name": s["name"], "start": s["start"]} for s in r["sections"]],
        }
        made["music"] += 1
        cat["items"] = sorted(items.values(), key=lambda it: it["id"])
        save_catalog(cat)
    cat["items"] = sorted(items.values(), key=lambda it: it["id"])
    save_catalog(cat)
    made["seconds"] = round(time.time() - t0, 1)
    return made


def _r2(v) -> Optional[float]:
    return round(float(v), 2) if v is not None and math.isfinite(float(v)) else None


def _sfx_variants(spec: dict):
    """Expand {"type": {"n": 3, "durs": [...], "keys": [...]}} (or the default plan) into variants."""
    from . import sfx
    plan = spec or DEFAULT_SFX_PLAN
    keys_default = ["C", "Am", "F", "D", "Em", "G"]
    for t, p in plan.items():
        if t not in sfx.REGISTRY:
            continue
        s = sfx.REGISTRY[t]
        n = int(p.get("n", 2))
        durs = p.get("durs") or [None]
        ints = p.get("intensity") or [0.5, 0.85]
        keys = p.get("keys") or (keys_default if s.tonal else ["C"])
        for i in range(n):
            d = durs[i % len(durs)]
            it = ints[i % len(ints)]
            k = keys[i % len(keys)]
            tag = "%02d" % (i + 1)
            if d:
                tag += "-%gs" % d
            if s.tonal:
                tag += "-" + slug(k)
            yield {"type": t, "dur": d, "intensity": it, "seed": 101 + i, "key": k, "tag": tag}


DEFAULT_SFX_PLAN = {
    "whoosh": {"n": 5, "durs": [0.6, 1.0, 1.5, 0.8, 2.2]}, "whoosh-heavy": {"n": 3, "durs": [1.2, 1.8, 2.8]},
    "swoosh-in": {"n": 3, "durs": [0.3, 0.45, 0.7]}, "swoosh-out": {"n": 3, "durs": [0.4, 0.6, 0.9]},
    "riser": {"n": 5, "durs": [1.0, 2.0, 3.0, 4.0, 6.0]}, "noise-riser": {"n": 4, "durs": [1.0, 2.0, 4.0, 8.0]},
    "downlifter": {"n": 3, "durs": [1.5, 2.5, 4.0]}, "reverse-cymbal": {"n": 3, "durs": [1.0, 2.0, 3.0]},
    "swell": {"n": 3, "durs": [2.0, 3.0, 5.0]}, "reverse-hit": {"n": 3, "durs": [0.8, 1.5, 2.5]},
    "tape-rewind": {"n": 2, "durs": [0.8, 1.5]},
    "impact": {"n": 5, "durs": [1.5, 2.4, 3.5, 2.0, 5.0]}, "boom": {"n": 3, "durs": [2.0, 3.0, 5.0]},
    "braam": {"n": 3, "durs": [2.0, 3.0, 4.0]}, "sub-drop": {"n": 3, "durs": [1.0, 2.0, 3.0]},
    "thock": {"n": 3}, "punch": {"n": 3}, "metal-hit": {"n": 3, "durs": [1.0, 2.0, 3.0]},
    "click": {"n": 4}, "tick": {"n": 3}, "pop": {"n": 4}, "toggle": {"n": 3}, "keyclick": {"n": 3},
    "typing": {"n": 3, "durs": [1.0, 3.0, 6.0]}, "notification": {"n": 4}, "success": {"n": 4}, "error": {"n": 3},
    "ding": {"n": 4}, "bell": {"n": 3}, "chime": {"n": 3}, "shimmer": {"n": 3, "durs": [1.0, 1.6, 3.0]},
    "sparkle-up": {"n": 3, "durs": [0.6, 1.0, 1.8]}, "coin": {"n": 3}, "power-up": {"n": 3}, "power-down": {"n": 3},
    "countdown-beep": {"n": 3, "intensity": [0.5, 0.5, 0.9]},
    "camera-shutter": {"n": 3}, "cash-register": {"n": 2}, "heartbeat": {"n": 2, "durs": [4.0, 8.0]},
    "paper-swipe": {"n": 3}, "water-drop": {"n": 3}, "clock-ticking": {"n": 2, "durs": [4.0, 10.0]},
    "glitch": {"n": 4, "durs": [0.3, 0.6, 1.0, 1.5]}, "laser": {"n": 3}, "zap": {"n": 3}, "tape-stop": {"n": 2},
    "vinyl-scratch": {"n": 3}, "static-burst": {"n": 3, "durs": [0.3, 0.8, 1.5]},
    "sonar-ping": {"n": 2}, "room-tone": {"n": 1, "durs": [30.0]}, "wind": {"n": 2, "durs": [30.0]},
    "rain": {"n": 2, "durs": [30.0]}, "drone": {"n": 3, "durs": [30.0], "keys": ["Dm", "Am", "Em"]},
    "stinger": {"n": 4}, "logo-sting": {"n": 5}, "drum-fill": {"n": 3, "durs": [0.5, 1.0, 2.0]},
}


# ---------------------------------------------------------------------------------------------
# BYO, credits, pinning
# ---------------------------------------------------------------------------------------------
def index_folder(folder: Path, name: str, license_: str, kind: str = "sfx", attribution: Optional[str] = None,
                 redistributable: bool = False, workers: int = 3) -> Dict:
    """Catalog a local folder in place (tier byo). Files are not copied."""
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise ShowtimeError("not a folder: %s" % folder)
    if kind not in KIND_DIR:
        raise ShowtimeError("kind must be one of %s" % ", ".join(KIND_DIR))
    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in AUDIO_EXT and p.is_file() and not p.name.startswith("._"))
    if not files:
        raise ShowtimeError("no audio files under %s" % folder)
    sid = "byo-" + slug(name)
    src = {"id": sid, "type": "zip", "kind": kind, "license": license_, "attribution": attribution,
           "redistributable": redistributable, "tier": "byo", "url": None, "source_url": str(folder), "tags": ["byo"]}
    cat = load_catalog(required=False)
    items = {it["id"]: it for it in cat.get("items", []) if it.get("source_id") != sid}
    log("indexing %d files from %s ..." % (len(files), folder))

    def one(f: Path):
        rel = f.relative_to(folder)
        base = dict(src)
        base["tags"] = ["byo"] + [slug(p) for p in rel.parts[:-1]][-2:]
        return f, analyze_file(f, kind, base), base
    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        results = list(ex.map(one, files))
    used = set()
    for f, info, base in results:
        it = _item_for({**src, "tags": base["tags"]}, f, info)
        it["path"] = str(f)
        iid = it["id"]
        k = 2
        while iid in used:
            iid = "%s-%d" % (it["id"], k)
            k += 1
        used.add(iid)
        it["id"] = iid
        items[iid] = it
    cat["items"] = sorted(items.values(), key=lambda it: it["id"])
    save_catalog(cat)
    return {"source_id": sid, "files": len(files), "catalog": str(catalog_path())}


def credits_for(ids: Iterable[str]) -> Dict[str, Any]:
    """Credit lines for items (only attribution-required ones are mandatory)."""
    req, opt = [], []
    for i in ids:
        it = get_item(i)
        if it.get("attribution_required") and it.get("attribution"):
            if it["attribution"] not in req:
                req.append(it["attribution"])
        elif it.get("credit_optional") and it["credit_optional"] not in opt:
            opt.append(it["credit_optional"])
    text = ""
    if req:
        text = "Music and sound credits\n\n" + "\n\n".join(r.strip() for r in req) + "\n"
    return {"required": req, "optional": opt, "text": text}


def write_credits_sources(man: dict, cat: dict) -> Path:
    counts: Dict[str, int] = {}
    for it in cat.get("items", []):
        counts[it.get("source_id") or "?"] = counts.get(it.get("source_id") or "?", 0) + 1
    lines = ["# Audio library sources", "",
             "Every item in catalog.json records its own license. CC0 items need no credit.",
             "CC-BY items MUST be credited in any video that uses them: `showtime audio mix` writes",
             "credits.txt automatically, and `showtime audio lib credits <id>` prints the lines.", "",
             "| Source | Tier | Items | License | Credit |", "|---|---|---|---|---|"]
    for s in man.get("sources", []):
        if s["id"] not in counts:
            continue
        credit = (s.get("attribution") or s.get("credit_optional") or "").split("\n")[0]
        lines.append("| [%s](%s) | %s | %d | %s | %s |" % (s["id"], s.get("source_url") or s["url"], s.get("tier", "core"),
                                                        counts[s["id"]], s["license"], credit))
    for sid in sorted(k for k in counts if k.startswith(("generated", "byo"))):
        lines.append("| %s | %s | %d | %s | none required |" % (sid, "generated" if sid.startswith("generated") else "byo",
                                                                counts[sid], "generated by showtime" if sid.startswith("generated") else "see catalog"))
    p = library_dir() / "CREDITS-SOURCES.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return p


def pin(manifest_path: Optional[Path] = None, tier: str = "extended", only: Optional[List[str]] = None) -> Dict:
    """Maintainer tool: download sources lacking sha256/bytes and write the pins back."""
    mp = Path(manifest_path or MANIFEST)
    man = read_json(mp)
    allowed = TIERS[: TIERS.index(tier) + 1]
    done = []
    for s in man["sources"]:
        if s.get("tier", "core") not in allowed or (only and s["id"] not in only):
            continue
        if s.get("sha256") and s.get("bytes"):
            continue
        name = Path(urllib.parse.unquote(urllib.parse.urlparse(s["url"]).path)).name
        dest = home() / "cache" / "downloads" / "audio" / s["id"] / name
        log("pinning %s" % s["id"])
        download(s["url"], dest, man.get("user_agent", "showtime-audio/0.1"), man.get("host_delays", {}))
        s["sha256"] = sha256_file(dest)
        s["bytes"] = dest.stat().st_size
        done.append(s["id"])
        write_json(mp, man, indent=1)
    return {"pinned": done, "manifest": str(mp)}


def stats() -> Dict[str, Any]:
    cat = load_catalog()
    by: Dict[str, Dict[str, int]] = {"kind": {}, "license": {}, "tier": {}, "category": {}}
    missing = 0
    total_dur = 0.0
    for it in cat["items"]:
        for k in by:
            v = str(it.get(k) or "-")
            by[k][v] = by[k].get(v, 0) + 1
        total_dur += float(it.get("duration") or 0)
        if not item_path(it).is_file():
            missing += 1
    return {"items": len(cat["items"]), "hours": round(total_dur / 3600, 2), "size": human_size(library_size()),
            "missing_files": missing, **by, "catalog": str(catalog_path()), "generated": cat.get("generated")}

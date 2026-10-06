"""Render an audio/mix.json into one mastered file plus mix.report.json.

Spec (all times in seconds on the output timeline):

  { "duration": 20.0, "sample_rate": 48000,
    "tracks": [
      {"kind": "music", "file": "audio/bed.wav", "gain_db": -6, "start": 0, "offset": 0,
       "fade_in": 0.3, "fade_out": 1.2, "loop": false,
       "duck": {"under": "voice", "depth_db": 12, "attack": 0.08, "release": 0.5, "carve": 0.0}},
      {"kind": "voice", "file": "voice/vo.wav", "start": 0.6},
      {"kind": "sfx", "file": "sfx/whoosh.wav", "at": 3.0, "align": "hit", "hit": 0.21, "gain_db": -10, "pan": 0},
      {"kind": "sfx", "synth": {"type": "impact", "key": "D", "intensity": 0.8, "seed": 3}, "at": 17.5, "align": "hit"},
      {"kind": "sfx", "lib": "kenney-interface-sounds/click_001", "at": 2.0},
      {"kind": "music", "compose": {"style": "upbeat-tech", "bpm": 118, "key": "D", "sections": "0:intro,8:drop"}},
      {"kind": "music", "catalog": "buckley-with-these-hands", "fit": true, "duck": {"under": "voice"}},
      {"kind": "music", "catalog": {"use": "explainer", "pick": 0}, "fit": true}
    ],
    "sections": [{"name": "intro", "start": 0, "end": 4}, ...],      (optional; for the report)
    "questions": {"duck_db": 12, "tick": true},                       (optional; see below)
    ("duration" may be left out inside a project: the showtime.json duration is used)
    "master": {"lufs": -14, "true_peak": -1, "engine": "st"} }

Track fields
  kind       music | voice | sfx | ambience   (drives default level and ducking groups)
  source     one of: file, lib (library id), catalog (produced-music id, or {"use": "launch", "pick": 0}
             rotated against recent jobs; fetched on first use and credited, see music.py), synth (sfx
             spec), compose (compose spec; "seed": "auto" varies the seed and, unless given, the key per project)
  level      "auto" (default): normalise to the kind's reference (voice -16 LUFS,
             music -20, ambience -32, sfx by category) before gain_db; "raw": as is
  gain_db    dB relative to the reference (or to the file with level=raw)
  start/end  timeline window of the clip (end defaults to the source end / mix end)
  offset     seconds skipped at the start of the source; "highlight" starts a catalog track at its
             loudest sustained stretch (on a downbeat). Catalog tracks skip their near-silent lead-in by
             default (offset 0 plays it)
  dur        clip length (alternative to end)
  at, align  place the source's hit|start|end|peak at `at` (hit is measured or given as `hit`)
  loop       true: loop (bar-aligned when a beat grid is known) to fill the window
  fit        true: loop or trim musically to exactly fill the window (music)
  fade_in, fade_out, pan (-1..1)
  duck       {"under": kinds or track ids, "depth_db": 12, "attack": 0.08, "release": 0.5,
              "hold": 0.3, "lookahead": 0.12, "carve": 0..1}; the key can be any tracks (voice, a
              list of sfx ids ...), not only speech
  gain_points  gain automation on the timeline: [[t, db], ...], linear in dB between points
              (before the first point / after the last one the end values hold), e.g.
              [[0, 4], [2.6, 4], [3.2, 0]] lifts a quiet hook 4 dB and settles by 3.2 s
  section_gain  per-section gain for a music bed: {"intro": 3, "drop": -1} (a composed bed's
              section names) or {"0": 2.5, "5": 0} (timeline seconds); 0.25 s ramps between
  keystrokes a `demo record` events.json: one synthesized key click per typed character and key
             combo, placed at `start`; `rec_offset` is the recording time shown at `start` and `rate`
             the recording's playback speed in the video (data-rate), e.g.
             {"kind": "sfx", "keystrokes": "media/events.json", "start": 10.8, "rec_offset": 7.85, "rate": 1.75}
  typewriter one key click per character of a page `typewriter` (the component's own timeline: same
             text/script, cadence, cps, fit, seed), placed at `start` = the video time the typing starts,
             e.g. {"kind": "sfx", "typewriter": {"text": "npm create showtime", "cps": 18}, "start": 2.5}
  id         optional name (used by duck.under and in the report)
  texture    true: an effect meant to sit under the mix (soft UI clicks under a voice): no masking warning
  layer      "<id>" or ["<id>", ...]: stacked with those tracks (a braam on an impact): they are not "the rest
             of the mix" when judging if this one is masked. Tracks of one family (same file stem or id
             prefix, e.g. keyclick-01..38; the same synth type) never mask each other either

Stop-and-ask questions (showtime.json "questions", each with a "pause and think" beat of `think`
seconds from its `at`): a top-level "questions" block, `true` or {"duck_db": 12, "tick": false,
"tick_gain_db": -4}, lowers every music and ambience track by duck_db through each beat (0.25 s in,
0.4 s out) and, with "tick", adds a soft clock tick on each second of the countdown. The beat times
are read from the project's showtime.json (voice cues resolved), so they follow a re-voice.

Relative paths resolve against the mix.json folder, then the project root (the
nearest folder with showtime.json), then the current directory.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import signal

from ..common import ShowtimeError, cache_lock, home, log, portable_path, read_json, warn, write_json
from .. import questions as _questions
from . import SR, dsp, master, meter, sfx, wav

KIND_REF = {"voice": -16.0, "music": -20.0, "ambience": -32.0}
# default duck depth: the bed sits ~16 dB under speech (-16 voice vs -20 music, minus 12), inside the
# 10-20 dB window and far enough down that a busy bed never competes with the words
DUCK_DB = 12.0
KINDS = ("music", "voice", "sfx", "ambience")


# ---------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------

def credits_file(folder: Path) -> Path:
    """The folder's credits file, always spelled `credits.txt` (the name render and qa use).

    An older `CREDITS.txt` (or any other capitalisation) is renamed, so a case-sensitive
    file system (Linux) never ends up with two credits files."""
    folder = Path(folder)
    want = folder / "credits.txt"
    try:
        for f in folder.iterdir():
            if f.name.lower() == "credits.txt" and f.name != "credits.txt":
                if want.exists() and not want.samefile(f):
                    f.unlink()
                else:
                    tmp = f.with_name(".credits-rename.tmp")
                    os.replace(str(f), str(tmp))
                    os.replace(str(tmp), str(want))
    except OSError:
        pass
    return want

def _cache_dir() -> Path:
    d = home() / "cache" / "audio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _num(v, name: str, idx: int, default=None, lo=None, hi=None):
    if v is None:
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ShowtimeError("track %d: %s must be a number (got %r)" % (idx, name, v))
    if lo is not None and f < lo or hi is not None and f > hi:
        raise ShowtimeError("track %d: %s=%s is out of range [%s, %s]" % (idx, name, f, lo, hi))
    return f


def resolve_path(p: str, bases: List[Path]) -> Path:
    q = Path(os.path.expanduser(str(p)))
    if q.is_absolute():
        if q.is_file():
            return q
        raise ShowtimeError("file not found: %s" % q)
    for b in bases:
        c = b / q
        if c.is_file():
            return c
    raise ShowtimeError("file not found: %s (looked in %s)" % (p, ", ".join(str(b) for b in bases)))


def _project_duration(bases: List[Path]) -> Optional[float]:
    for b in bases:
        f = Path(b) / "showtime.json"
        if f.is_file():
            try:
                d = read_json(f).get("duration")
                return float(d) if d else None
            except (ShowtimeError, ValueError, TypeError, AttributeError):
                return None
    return None


def _bases(spec_path: Optional[Path], root: Optional[Path]) -> List[Path]:
    out: List[Path] = []
    if root:
        out.append(Path(root))
    if spec_path:
        d = spec_path.resolve().parent
        out.append(d)
        for anc in [d] + list(d.parents)[:4]:
            if (anc / "showtime.json").is_file():
                out.append(anc)
                break
    out.append(Path.cwd())
    seen, res = set(), []
    for b in out:
        k = str(b.resolve())
        if k not in seen:
            seen.add(k)
            res.append(b)
    return res


def _sidecar_beats(p: Path) -> Optional[dict]:
    for c in (p.with_name(p.stem + ".beats.json"), p.with_name(p.name + ".beats.json")):
        if c.is_file():
            try:
                return read_json(c)
            except ShowtimeError:
                return None
    return None


def _word_segments(p: Path, offset: float) -> List[Tuple[float, float]]:
    """Speech segments from a <stem>.words.json sidecar (voice module output), relative to the clip."""
    side = p.with_name(p.stem + ".words.json")
    if not side.is_file():
        return []
    try:
        doc = read_json(side)
    except ShowtimeError:
        return []
    words = doc.get("words", []) if isinstance(doc, dict) else doc
    out = []
    for w in words if isinstance(words, list) else []:
        if not isinstance(w, dict) or w.get("type") in ("spacing", "audio_event"):
            continue
        try:
            a, b = float(w["start"]) - offset, float(w["end"]) - offset
        except (KeyError, TypeError, ValueError):
            continue
        if b > 0:
            out.append((max(0.0, a), b))
    return out


# ---------------------------------------------------------------------------------------------
# sources
# ---------------------------------------------------------------------------------------------
class Source:
    def __init__(self, audio: np.ndarray, meta: Dict[str, Any]):
        self.audio = audio
        self.meta = meta


def keystroke_times(events_doc: dict, offset: float = 0.0, rate: float = 1.0) -> List[float]:
    """Key-press times (seconds from the track start) from a `demo record` events.json: one per typed
    character (spread over the typing span with a seeded rhythm) and one per key combo. `offset` is
    the recording time the track starts at; `rate` the playback speed of the recording in the video."""
    out: List[float] = []
    rnd = np.random.default_rng(7)
    for e in (events_doc or {}).get("events", []):
        t0 = float(e.get("t", 0))
        if e.get("type") == "key":
            out.append(t0)
        elif e.get("type") == "type":
            text = str(e.get("text") or "")
            n = len(text)
            if not n:
                continue
            t1 = float(e.get("end", t0 + n / 14.0))
            step = max(1e-3, (t1 - t0) / n)
            for i, ch in enumerate(text):
                if ch == " ":
                    continue
                out.append(t0 + step * i + float(rnd.uniform(-0.25, 0.25)) * step)
    rate = rate if rate and rate > 0 else 1.0
    return sorted((t - offset) / rate for t in out if (t - offset) >= 0)


def _mulberry32(seed: int):
    """The page runtime's rng(seed) (components/core.js), bit for bit, so key times match the page."""
    state = [seed & 0xFFFFFFFF]

    def imul(x: int, y: int) -> int:
        return (x * y) & 0xFFFFFFFF

    def r() -> float:
        a = state[0] = (state[0] + 0x6D2B79F5) & 0xFFFFFFFF
        t = imul(a ^ (a >> 15), 1 | a)
        t = ((t + imul(t ^ (t >> 7), 61 | t)) & 0xFFFFFFFF) ^ t
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0
    return r


def typing_timeline(ops: List[dict], cadence: str = "human", cps: float = 18, word_gap: float = 0.12,
                    line_pause: float = 0.35, back_cps: float = 28, seed: int = 7) -> Tuple[List[float], float]:
    """(key times, end) of the `typewriter` component's timeline (components/typewriter.js typingTimeline):
    one time per typed character and per backspace, in the component's local seconds."""
    r = _mulberry32(int(seed))
    t = 0.0
    times: List[float] = []
    per = 1.0 / max(1.0, float(cps))
    human = cadence == "human"
    for op in ops:
        if op.get("pause") is not None:
            t += float(op["pause"] or 0)
            continue
        if op.get("back") is not None:
            for _ in range(int(op["back"])):
                t += 1.0 / back_cps
                times.append(t)
            t += 0.12
            continue
        chars = list(str(op.get("type", op.get("text", "")) or ""))
        i = 0
        while i < len(chars):
            n = 1 + int(math.floor(r() * 3)) if human else 1
            for ch in chars[i:i + n]:
                t += per * (0.55 + r() * 0.9) if human else per
                if ch == " ":
                    t += word_gap * (0.6 + r() * 0.8 if human else 1)
                if ch == "\n":
                    t += line_pause
                times.append(t)
            i += n
            if human:
                t += per * r() * 0.8
    return times, t


def typewriter_times(spec: Any, idx: int) -> List[float]:
    """Key times (seconds from the typewriter's start) for a mix track {"typewriter": {...}} with the
    component's own options: text or script, cadence, cps, fit, seed, linePause."""
    if isinstance(spec, str):
        spec = {"text": spec}
    if not isinstance(spec, dict) or not (spec.get("text") or spec.get("script")):
        raise ShowtimeError("track %d: typewriter needs \"text\" (or \"script\"), as on the page's typewriter" % idx,
                            hint='{"kind": "sfx", "typewriter": {"text": "npm create showtime", "cps": 18}, "start": 2.5}')
    ops = spec.get("script") if isinstance(spec.get("script"), list) else [{"type": str(spec["text"])}]
    kw = dict(cadence=str(spec.get("cadence", "human")), cps=float(spec.get("cps", 18)),
              word_gap=float(spec.get("wordGap", spec.get("word_gap", 0.12))),
              line_pause=float(spec.get("linePause", spec.get("line_pause", 0.35))), seed=int(spec.get("seed", 7)))
    times, end = typing_timeline(ops, **kw)
    if spec.get("fit"):
        kw["cps"] = max(6.0, kw["cps"] * end / float(spec["fit"]))
        times, end = typing_timeline(ops, **kw)
    return times


def _click_track(times: List[float]) -> np.ndarray:
    """One synthesized key click per time (six seeded variants, slight level variation)."""
    variants = []
    for sd in range(1, 7):
        key = "sfx-" + _hash({"t": "keyclick", "dur": None, "intensity": 0.6, "seed": sd, "key": "C"})
        cp = _cache_dir() / (key + ".wav")
        if not cp.is_file():
            with cache_lock(cp):
                if not cp.is_file():
                    x, _m = sfx.render("keyclick", dur=None, intensity=0.6, seed=sd, key="C")
                    wav.save(cp, x, bits=24)
        variants.append(wav.load(cp))
    length = (times[-1] + 0.3) if times else 0.3
    buf = np.zeros((int(round(length * SR)) + 1, 2), np.float32)
    for i, t in enumerate(times):
        v = variants[i % len(variants)]
        a = int(round(t * SR))
        b = min(len(buf), a + len(v))
        if b > a:
            buf[a:b] += v[: b - a] * (0.8 + 0.2 * ((i * 37) % 5) / 4)
    return buf


def _file_license(p: Path, meta: Dict[str, Any]) -> None:
    """License facts for a plain file: its `<file>.license.json` sidecar (`assets` writes them), else the
    library item it is a copy of (same bytes), so a copied CC-BY track keeps its credit."""
    side = p.with_name(p.name + ".license.json")
    if side.is_file():
        try:
            sj = read_json(side)
        except ShowtimeError:
            sj = {}
        if sj.get("license"):
            meta.update(license=sj.get("license"), attribution=sj.get("credit") or sj.get("attribution"),
                        attribution_required=bool(sj.get("attribution_required")), license_file=str(side))
            return
    beats = p.with_name(p.stem + ".beats.json")          # an older composed bed without its license sidecar
    if beats.is_file():
        try:
            bj = read_json(beats)
        except ShowtimeError:
            bj = {}
        if isinstance(bj, dict) and bj.get("source") == "composed":
            meta.update(license="generated", attribution_required=False,
                        attribution="composed locally with showtime audio compose (%s)" % bj.get("style", "?"))
            return
    from . import library
    item = library.match_file(p)
    if item:
        meta.update(library_id=item["id"], license=item.get("license"), attribution=item.get("attribution"),
                    attribution_required=item.get("attribution_required", False), title=item.get("title"),
                    matched_library=True)
        if not meta.get("hit"):
            meta["hit"] = item.get("hit")
        return
    from . import music
    t = music.match_file(p)             # a catalog track copied into the project keeps its credit
    if t:
        meta.update(catalog_id=t["id"], title=t["title"], artist=t["artist"], license=t["license"],
                    attribution=t.get("attribution"), attribution_required=music.needs_attribution(t),
                    credit=music.credit_item(t), matched_catalog=True)


def load_source(tr: dict, idx: int, bases: List[Path], mix_dur: float) -> Source:
    if tr.get("typewriter"):
        # one click per key of a page `typewriter` (same timeline as the component), from `start`
        times = typewriter_times(tr["typewriter"], idx)
        return Source(_click_track(times), {"source": "typewriter", "keystrokes": len(times), "category": "ui",
                                            "license": "generated", "attribution_required": False})
    if tr.get("keystrokes"):
        # one click per key press of a recorded demo, in sync with the recording in the video
        ep = resolve_path(tr["keystrokes"], bases)
        times = keystroke_times(read_json(ep), float(tr.get("rec_offset", tr.get("offset_rec", 0)) or 0),
                                float(tr.get("rate", 1.0) or 1.0))
        return Source(_click_track(times), {"source": "keystrokes", "path": str(ep), "keystrokes": len(times),
                                            "category": "ui", "license": "generated", "attribution_required": False})
    kinds = [k for k in ("file", "lib", "catalog", "synth", "compose") if tr.get(k)]
    if len(kinds) != 1:
        raise ShowtimeError("track %d: give exactly one source: file, lib, catalog, synth, compose, keystrokes or typewriter "
                            "(got %s)"
                            % (idx, ", ".join(kinds) or "none"))
    src = kinds[0]
    meta: Dict[str, Any] = {"source": src}
    if src == "file":
        p = resolve_path(tr["file"], bases)
        meta.update(path=str(p), beats=_sidecar_beats(p))
        side = p.with_name(p.stem + ".sfx.json")          # written by `audio sfx`
        if side.is_file():
            try:
                sj = read_json(side)
                meta.update(hit=sj.get("hit"), category=sj.get("category"))
            except ShowtimeError:
                pass
        off = tr.get("offset")
        off = 0.0 if isinstance(off, str) and off.strip().lower() == "highlight" else _num(off, "offset", idx, 0.0, 0.0)
        speech = _word_segments(p, off)       # (a "highlight" offset on a plain file is refused when it is placed)
        if speech:
            meta["speech"] = speech
        mg = p.with_name(p.stem + ".musicgen.json")        # written by `audio musicgen`
        if mg.is_file():
            meta.update(license="CC-BY-NC-4.0", noncommercial=True)
        else:
            _file_license(p, meta)
        return Source(wav.load(p), meta)
    if src == "lib":
        from . import library
        ref = tr["lib"]
        try:
            item = library.resolve(ref if isinstance(ref, str) else dict(ref))
        except ShowtimeError:
            # an item of an extra sound pack that is not installed yet: fetch the pack (announced), retry
            from . import packs
            if not packs.install_for_ref(ref):
                raise
            library._SIZES.clear()
            item = library.resolve(ref if isinstance(ref, str) else dict(ref))
        p = library.item_path(item)
        meta.update(path=str(p), library_id=item["id"], license=item.get("license"),
                    attribution=item.get("attribution"), attribution_required=item.get("attribution_required", False),
                    hit=item.get("hit"), category=item.get("category"), title=item.get("title"),
                    artist=item.get("artist"), credit_optional=item.get("credit_optional"),
                    source_url=item.get("source_url"))
        side = item.get("sidecar")
        if side:
            sp = library.library_dir() / side
            if sp.is_file():
                meta["beats"] = read_json(sp)
        return Source(wav.load(p), meta)
    if src == "catalog":
        from . import music
        proj = next((b for b in bases if (b / "showtime.json").is_file()), None)
        t = music.resolve(tr["catalog"], dur=float(tr.get("dur") or 0) or None,
                          key=str(proj.resolve()) if proj is not None else None)   # a query rotates per project
        p = music.fetch(t, purpose="the mix (track %d)" % idx)
        meta.update(path=str(p), catalog_id=t["id"], title=t["title"], artist=t["artist"], license=t["license"],
                    attribution=t.get("attribution"), attribution_required=music.needs_attribution(t),
                    credit=music.credit_item(t), beats=music.beats_for(p), lead_silence_s=t.get("lead_silence_s"),
                    highlight_s=t.get("highlight_s"))
        return Source(wav.load(p), meta)
    if src == "synth":
        spec = dict(tr["synth"]) if isinstance(tr["synth"], dict) else {"type": str(tr["synth"])}
        if "type" not in spec:
            raise ShowtimeError("track %d: synth needs a 'type' (see `showtime audio sfx-types`)" % idx)
        params = {"dur": spec.get("dur"), "intensity": float(spec.get("intensity", 0.7)),
                  "seed": int(spec.get("seed", 0)), "key": str(spec.get("key", "C"))}
        key = "sfx-" + _hash({"t": spec["type"], **params})
        cp = _cache_dir() / (key + ".wav")
        cj = _cache_dir() / (key + ".json")
        if not (cp.is_file() and cj.is_file()):
            # several renders can reach the same synth hit at once (16:9, 1:1 and 9:16 of one project):
            # one fills the entry, the others wait for it; writes are atomic either way
            with cache_lock(cp):
                if not (cp.is_file() and cj.is_file()):
                    x, m = sfx.render(spec["type"], **params)
                    wav.save(cp, x, bits=24)
                    write_json(cj, m)
        x, m = wav.load(cp), read_json(cj)
        meta.update(synth=m, hit=m["hit"], category=m["category"], license="generated", attribution_required=False)
        return Source(x, meta)
    # compose
    from . import compose
    spec = dict(tr["compose"])
    if "style" not in spec:
        raise ShowtimeError("track %d: compose needs a 'style' (see `showtime audio styles`)" % idx)
    start = float(tr.get("start", 0) or 0)
    dur = float(spec.get("duration") or spec.get("dur") or tr.get("dur") or (mix_dur - start))
    if dur < 2:
        raise ShowtimeError("track %d: compose duration %.2fs is too short (min 2 s)" % (idx, dur))
    sections = spec.get("sections")
    if sections not in (None, "", "auto"):
        # a mix that follows the project length may be shorter than the sections were written for:
        # keep only the sections that start inside the track (at least 1 s before its end)
        parsed = compose.parse_sections(sections, max(dur, 1e6))
        kept = [(n, t) for n, t in parsed if t <= dur - 1.0 or t == 0]
        if len(kept) < len(parsed):
            warn("track %d: sections after %.1fs dropped (the mix is %.1fs long)" % (idx, dur - 1.0, dur))
        sections = ",".join("%s:%s" % (round(t, 4), n) for n, t in kept) if kept else None
    seed, key_ = spec.get("seed", 0), spec.get("key")
    if str(seed).strip().lower() == "auto":
        # one bed per project: the seed (motif, humanising) and, unless "key" is given, the key follow the
        # project, so two videos on the same style do not share a bed
        proj = next((b for b in bases if (b / "showtime.json").is_file()), bases[0] if bases else Path.cwd())
        seed = int(hashlib.sha1(("%s|%s" % (proj.resolve(), spec["style"])).encode("utf-8")).hexdigest()[:6], 16)
        key_ = key_ or compose.auto_key(spec["style"], seed)
    cspec = {"style": spec["style"], "duration": round(dur, 4), "bpm": spec.get("bpm"), "key": key_,
             "sections": sections, "seed": int(seed), "backend": spec.get("backend", "auto"),
             "soundfont": spec.get("soundfont")}
    key = "compose-" + _hash(dict(cspec, _v=2))     # v2: beats.json records the backend and SoundFont used
    cp = _cache_dir() / key / "music.wav"
    bj = cp.with_name("music.beats.json")
    if not (cp.is_file() and bj.is_file()):
        with cache_lock(cp.parent, timeout=1200.0):
            if not (cp.is_file() and bj.is_file()):
                log("composing %s (%.1fs) ..." % (cspec["style"], dur))
                compose.build(cspec["style"], dur, cp, bpm=cspec["bpm"], key=cspec["key"], sections=cspec["sections"],
                              seed=cspec["seed"], backend=cspec["backend"], soundfont=cspec["soundfont"], stems=False)
    meta.update(path=str(cp), beats=read_json(bj), compose=cspec, license="generated", attribution_required=False)
    return Source(wav.load(cp), meta)


# ---------------------------------------------------------------------------------------------
# levels
# ---------------------------------------------------------------------------------------------
def auto_level(x: np.ndarray, kind: str, meta: dict) -> Tuple[float, Dict]:
    """Gain (dB) that brings a source to its kind's reference level."""
    if kind == "sfx":
        if meta.get("source") == "synth":
            return 0.0, {"reference": "sfx category (already levelled)", "category": meta.get("category")}
        cat = meta.get("category") or "fx"
        target = sfx.CATEGORY_LEVEL.get(cat, -20.0)
        cur = sfx.max_momentary(x)
        pk = float(np.abs(x).max()) if x.size else 0.0
        g = (target - cur) if math.isfinite(cur) else 0.0
        cap = sfx.CATEGORY_PEAK.get(cat, -1.0)
        if pk > 0 and 20 * math.log10(pk) + g > cap:
            g = cap - 20 * math.log10(pk)
        return g, {"reference": "%s %.0f LUFS (momentary max)" % (cat, target), "measured": round(cur, 2) if math.isfinite(cur) else None}
    ref = KIND_REF.get(kind, -20.0)
    cur = meter.integrated(x)
    if not math.isfinite(cur):
        cur = sfx.max_momentary(x)
    if not math.isfinite(cur):
        return 0.0, {"reference": ref, "measured": None, "note": "silent source"}
    return ref - cur, {"reference": "%.0f LUFS integrated" % ref, "measured": round(cur, 2)}


# ---------------------------------------------------------------------------------------------
# ducking and carving
# ---------------------------------------------------------------------------------------------
def activity(key: np.ndarray, hop: float = 0.01, rel_db: float = 35.0, floor_db: float = -55.0,
             hold: float = 0.3, min_len: float = 0.08) -> np.ndarray:
    """Speech/activity mask per `hop` frame from a key signal."""
    m = dsp.to_mono(key)
    h = max(1, int(hop * SR))
    k = int(math.ceil(len(m) / h))
    m = np.pad(m, (0, k * h - len(m)))
    lv = 20 * np.log10(np.sqrt((m.reshape(k, h) ** 2).mean(axis=1)) + 1e-9)
    if lv.max() < floor_db:
        return np.zeros(k, bool)
    act = lv > max(lv.max() - rel_db, floor_db)
    # close short gaps (hold), drop tiny islands
    g = int(hold / hop)
    idx = np.nonzero(act)[0]
    if idx.size:
        gaps = np.diff(idx)
        for a, gp in zip(idx[:-1], gaps):
            if 1 < gp <= g:
                act[a:a + gp] = True
    d = np.diff(np.concatenate([[0], act.astype(np.int8), [0]]))
    for s, e in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):
        if (e - s) * hop < min_len:
            act[s:e] = False
    return act


def segments_mask(segments: List[Tuple[float, float]], n_samples: int, hop: float = 0.01,
                  hold: float = 0.3) -> np.ndarray:
    """Activity frames from known speech segments (e.g. TTS word timings)."""
    k = int(math.ceil(n_samples / (hop * SR)))
    act = np.zeros(k, bool)
    for a, b in sorted(segments):
        act[max(0, int(a / hop)): max(0, min(k, int(math.ceil(b / hop))))] = True
    g = int(hold / hop)
    idx = np.nonzero(act)[0]
    for a, gp in zip(idx[:-1], np.diff(idx)):
        if 1 < gp <= g:
            act[a:a + gp] = True
    return act


def duck_gain(key: np.ndarray, n_samples: int, depth_db: float = DUCK_DB, attack: float = 0.08,
              release: float = 0.5, hold: float = 0.3, lookahead: float = 0.12, hop: float = 0.01,
              extra: Optional[np.ndarray] = None) -> Tuple[np.ndarray, Dict]:
    """Sample-rate gain curve that dips `depth_db` while the key is active
    (`extra`: an activity mask from word timings, OR-ed in)."""
    act = activity(key, hop, hold=hold) if np.any(key) else np.zeros(int(math.ceil(n_samples / (hop * SR))), bool)
    if extra is not None:
        m = min(len(act), len(extra))
        act = act.copy()
        act[:m] |= extra[:m]
    if not act.any():
        return np.ones(n_samples, np.float32), {"active_seconds": 0.0, "max_reduction_db": 0.0}
    sh = int(round(lookahead / hop))
    if sh > 0:
        act = np.concatenate([act[sh:], np.zeros(sh, bool)]) | act
    target = np.where(act, -abs(depth_db), 0.0)
    a_att = math.exp(-hop / max(attack, 1e-3))
    a_rel = math.exp(-hop / max(release, 1e-3))
    g = np.empty_like(target)
    cur = 0.0
    for i, v in enumerate(target.tolist()):
        cur = a_att * cur + (1 - a_att) * v if v < cur else a_rel * cur + (1 - a_rel) * v
        g[i] = cur
    centers = (np.arange(len(g)) + 0.5) * hop * SR
    gs = np.interp(np.arange(n_samples), centers, g)
    return (10 ** (gs / 20)).astype(np.float32), {"active_seconds": round(float(act.sum() * hop), 2),
                                                  "max_reduction_db": round(float(-g.min()), 2)}


CARVE_CENTRES = [160, 250, 400, 630, 1000, 1600, 2500, 4000, 6000]


def carve(bed: np.ndarray, voice: np.ndarray, strength: float = 0.5) -> Tuple[np.ndarray, Dict]:
    """Spectral carve: cut the bed only in the bands the voice occupies, only while it speaks.

    Bands are picked from the voice's long-term spectrum with a bias toward the
    1-4 kHz intelligibility region; each band's cut follows that band's voice
    envelope (attack 50 ms, release 250 ms)."""
    s = float(np.clip(strength, 0.0, 1.0))
    if s <= 0:
        return bed, {"bands": []}
    max_cut = 2 + 16 * s
    nb = int(np.clip(round(1 + 6 * s), 1, 6))
    q = 1.1 + 1.2 * s
    bias = min(1.0, 0.6 + 0.4 * s)
    nfft, hopn = 2048, 512
    v = dsp.to_mono(voice)
    f, _, V = signal.stft(v, fs=SR, nperseg=nfft, noverlap=nfft - hopn)
    P = (np.abs(V) ** 2)
    spec = P.mean(axis=1)
    scores = []
    for c in CARVE_CENTRES:
        m = (f >= c * 2 ** (-1 / 6)) & (f <= c * 2 ** (1 / 6))
        pw = float(spec[m].mean()) if m.any() else 1e-20
        pen = bias * 30.0 * (1 - math.exp(-(math.log2(c / 2000.0)) ** 2 / 2))
        scores.append(10 * math.log10(pw + 1e-20) - pen)
    order = np.argsort(scores)[::-1][:nb]
    top = scores[order[0]]
    bands = []
    for i in sorted(order):
        depth = float(np.clip(max_cut * 10 ** ((scores[i] - top) / 10), max_cut / 2, max_cut))
        bands.append((CARVE_CENTRES[i], depth))
    # per-band voice envelopes
    hop_s = hopn / SR
    a_att, a_rel = math.exp(-hop_s / 0.05), math.exp(-hop_s / 0.25)
    envs = []
    for c, depth in bands:
        m = (f >= c / 2 ** (1 / (2 * q))) & (f <= c * 2 ** (1 / (2 * q)))
        lvl = 10 * np.log10(P[m].sum(axis=0) + 1e-12)
        on = lvl > (lvl.max() - 30)
        tgt = np.where(on, 1.0, 0.0)
        e = np.empty_like(tgt)
        cur = 0.0
        for j, t in enumerate(tgt.tolist()):
            cur = a_att * cur + (1 - a_att) * t if t > cur else a_rel * cur + (1 - a_rel) * t
            e[j] = cur
        envs.append(e)
    out = np.empty_like(bed)
    for ch in range(bed.shape[1]):
        fb, _, B = signal.stft(bed[:, ch], fs=SR, nperseg=nfft, noverlap=nfft - hopn)
        T = B.shape[1]
        gdb = np.zeros((len(fb), T))
        lf = np.log2(np.maximum(fb, 1.0))
        for (c, depth), e in zip(bands, envs):
            bell = np.exp(-0.5 * ((lf - math.log2(c)) * q * 1.2) ** 2)
            ee = np.interp(np.arange(T), np.arange(len(e)), e)
            gdb -= depth * bell[:, None] * ee[None, :]
        _, y = signal.istft(B * 10 ** (gdb / 20), fs=SR, nperseg=nfft, noverlap=nfft - hopn)
        out[:, ch] = dsp.pad_to(y.astype(np.float32), len(bed))
    return out, {"bands": [{"hz": c, "max_cut_db": round(d, 1)} for c, d in bands], "strength": s}


# ---------------------------------------------------------------------------------------------
# placement
# ---------------------------------------------------------------------------------------------
def source_offset(tr: dict, idx: int, meta: dict) -> Tuple[float, Optional[str]]:
    """Seconds skipped at the start of a source, and why: the number given; "highlight" (a catalog track's
    loudest sustained stretch, moved to the nearest downbeat); by default a catalog track's near-silent
    lead-in (so the music starts with the picture)."""
    v = tr.get("offset")
    if isinstance(v, str) and v.strip().lower() == "highlight":
        h = meta.get("highlight_s")
        if h is None:
            raise ShowtimeError('track %d: "offset": "highlight" works for catalog music only' % idx,
                                hint='give seconds instead, e.g. "offset": 42.5')
        from . import fit as fitmod
        return round(max(0.0, fitmod.snap_to_downbeat(meta.get("beats"), float(h))), 4), "highlight"
    if v is None and meta.get("catalog_id") and float(meta.get("lead_silence_s") or 0) >= 0.5:
        return round(float(meta["lead_silence_s"]) - 0.1, 4), "lead-in silence"
    return _num(v, "offset", idx, 0.0, 0.0), None


def place(tr: dict, idx: int, src: Source, kind: str, N: int, mix_dur: float) -> Tuple[np.ndarray, Dict]:
    x = src.audio
    meta = src.meta
    info: Dict[str, Any] = {}
    offset, why = source_offset(tr, idx, meta)
    if offset:
        x = x[int(round(offset * SR)):]
        info["offset"] = offset
        if why:
            info["offset_from"] = why
    src_dur = len(x) / SR
    start = _num(tr.get("start"), "start", idx, None)
    at = _num(tr.get("at"), "at", idx, None)
    align = (tr.get("align") or ("hit" if at is not None and kind == "sfx" else "start")).lower()
    if align not in ("hit", "start", "end", "peak"):
        raise ShowtimeError("track %d: align must be hit, start, end or peak" % idx)
    if at is not None:
        if align == "start":
            anchor = 0.0
        elif align == "end":
            anchor = src_dur
        elif tr.get("hit") is not None:
            anchor = float(tr["hit"]) - (offset or 0.0)          # `hit` is measured from the file start
        elif align == "hit" and meta.get("hit") is not None:
            anchor = float(meta["hit"]) - (offset or 0.0)
        else:
            anchor = sfx.hit_time(x, "peak" if align == "peak" else "onset")
        start = at - anchor
        info["aligned"] = {"at": at, "align": align, "anchor": round(anchor, 4)}
    if start is None:
        start = 0.0
    end = _num(tr.get("end"), "end", idx, None)
    dur = _num(tr.get("dur"), "dur", idx, None, 0.0)
    if dur is not None and end is None:
        end = start + dur
    want_fill = bool(tr.get("loop") or tr.get("fit"))
    if end is None:
        end = mix_dur if want_fill else min(mix_dur, start + src_dur)
    win = max(0.0, end - start)
    if win <= 0:
        return np.zeros((0, 2), np.float32), {"start": start, "end": end, "skipped": "empty window"}
    if want_fill:
        from . import fit as fitmod
        # the grid must match the audio after `offset` (it used to be the file's own, off by the offset)
        y, finfo = fitmod.fit(x, win, fitmod.shift_beats(meta.get("beats"), offset or 0.0), fade_out=tr.get("fade_out"))
        info["fit"] = finfo
    else:
        y = x[: int(round(win * SR))]
    fi = _num(tr.get("fade_in"), "fade_in", idx, 0.0, 0.0)
    fo = _num(tr.get("fade_out"), "fade_out", idx, 0.0, 0.0)
    y = dsp.fade(y, max(fi, 0.003), max(fo, 0.005))
    pan_v = _num(tr.get("pan"), "pan", idx, 0.0, -1.0, 1.0)
    if pan_v:
        y = dsp.pan(y, pan_v)
    out = np.zeros((N, 2), np.float32)
    dsp.mix_at(out, y, int(round(start * SR)))
    info.update(start=round(start, 4), end=round(min(end, start + len(y) / SR), 4))
    if start < 0:
        info["note"] = "starts before 0 s: the first %.3fs are cut" % -start
    return out, info


# ---------------------------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------------------------
def _gain_points(tr: dict, idx: int, meta: dict, start: float, dur: float) -> List[Tuple[float, float]]:
    """[(t, db)] from a track's gain_points / section_gain (timeline seconds)."""
    pts: List[Tuple[float, float]] = []
    gp = tr.get("gain_points")
    if gp is not None:
        if not isinstance(gp, list) or not all(isinstance(x, (list, tuple)) and len(x) == 2 for x in gp):
            raise ShowtimeError("track %d: gain_points must be [[t, db], ...]" % idx)
        pts += [(float(t), _num(db, "gain_points", idx, 0.0, -60.0, 24.0)) for t, db in gp]
    sg = tr.get("section_gain")
    if sg is not None:
        if not isinstance(sg, dict) or not sg:
            raise ShowtimeError("track %d: section_gain must be an object: {\"intro\": 3} or {\"0\": 2.5, \"5\": 0}" % idx)
        secs = ((meta.get("beats") or {}).get("sections") or []) if isinstance(meta.get("beats"), dict) else []
        starts: List[Tuple[float, float]] = []
        for k, db in sg.items():
            try:
                t = float(k)
            except (TypeError, ValueError):
                hit = [x for x in secs if str(x.get("name")) == str(k)]
                if not hit:
                    raise ShowtimeError("track %d: section_gain names %r, but this track's sections are: %s" % (
                        idx, k, ", ".join(str(x.get("name")) for x in secs) or "(none: use timeline seconds as keys)"))
                for x in hit:
                    starts.append((float(x["start"]) + start, _num(db, "section_gain", idx, 0.0, -60.0, 24.0)))
                    starts.append((float(x["end"]) + start, None))  # type: ignore[arg-type]
                continue
            starts.append((t, _num(db, "section_gain", idx, 0.0, -60.0, 24.0)))
        # steps with 0.25 s ramps; a named section's end returns to 0 dB unless another key follows
        starts.sort(key=lambda z: z[0])
        level = 0.0
        ramp = 0.25
        for t, db in starts:
            new = 0.0 if db is None else float(db)
            if db is None and any(abs(t2 - t) < 1e-6 and d2 is not None for t2, d2 in starts):
                continue
            pts.append((max(0.0, t - ramp / 2), level))
            pts.append((t + ramp / 2, new))
            level = new
    return sorted(pts, key=lambda z: z[0])


def _envelope(points: List[Tuple[float, float]], n: int) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / SR
    xs = np.array([p[0] for p in points], dtype=np.float64)
    ys = np.array([p[1] for p in points], dtype=np.float64)
    return (10 ** (np.interp(t, xs, ys) / 20)).astype(np.float32)


def _audibility(sfx_y: np.ndarray, rest: np.ndarray, at: float, win: float = 0.35,
                before: bool = False) -> Optional[float]:
    """dB of an effect over everything else, in its loudest 25 ms window near `at` (before=True: in the
    `win` seconds that end at `at`, for a riser whose hit is its end)."""
    if before:
        a, b = int(max(0.0, at - win) * SR), int((at + 0.02) * SR)
    else:
        a, b = int(max(0.0, at - 0.05) * SR), int((at + win) * SR)
    seg, bed = sfx_y[a:b].mean(axis=1), rest[a:b].mean(axis=1)
    h = int(0.025 * SR)
    if len(seg) < h:
        return None
    k = len(seg) // h
    e = (seg[: k * h].reshape(k, h) ** 2).mean(axis=1)
    i = int(np.argmax(e))
    if e[i] <= 1e-12:
        return None
    r = float((bed[i * h:(i + 1) * h] ** 2).mean())
    return round(10 * math.log10(float(e[i]) / max(r, 1e-12)), 1)


def _family(rec: dict, tr: dict) -> str:
    """Designed layers of one sound: keyclick-01..38, click_001/click_002, the same synth type, one file."""
    import re as _re
    if tr.get("keystrokes") or tr.get("typewriter"):
        return "keys"
    if tr.get("synth"):
        sy = tr["synth"]
        return "synth:" + str(sy.get("type") if isinstance(sy, dict) else sy)
    src = tr.get("lib") if isinstance(tr.get("lib"), str) else (tr.get("file") or "")
    stem = Path(str(src)).stem if src else ""
    if not stem:
        stem = str(rec.get("id") or "")
    return _re.sub(r"[\s_\-.]*\d+$", "", stem.lower()) or stem.lower()


def _masking(per_track: List[Dict], placed: Dict[int, np.ndarray], tracks: List[dict]) -> List[str]:
    """Warnings for effects the rest of the mix hides. Designed layers are not "the rest": other tracks of
    the same family (same file stem or id prefix, same synth type: 38 keyclicks at 18/s), tracks named in
    `"layer": "<id>"` (a braam stacked on an impact), and a riser whose hit is its end is judged before
    its end. `"texture": true` on a track skips the check (soft clicks under a voice on purpose).
    Consecutive masked tracks of one family are one warning."""
    sfx_recs = [r for r in per_track if r["kind"] == "sfx"]
    if not sfx_recs:
        return []
    total = sum(placed[r["index"]] for r in per_track)
    fam = {r["index"]: _family(r, tracks[r["index"]]) for r in sfx_recs}
    import re as _re
    idfam = {r["index"]: _re.sub(r"[\s_\-.]*\d+$", "", str(tracks[r["index"]]["id"]).lower())
             for r in sfx_recs if tracks[r["index"]].get("id")}         # explicit ids only (not "sfx3")
    ids = {r["id"]: r["index"] for r in per_track}
    masked: List[Tuple[str, dict, float, float]] = []
    for rec in sfx_recs:
        tr = tracks[rec["index"]]
        at = (rec.get("aligned") or {}).get("at", rec.get("start"))
        if at is None:
            continue
        y_s = placed[rec["index"]]
        layer = tr.get("layer")
        layer = [layer] if isinstance(layer, str) else list(layer or [])
        mine = idfam.get(rec["index"])
        mates = [r["index"] for r in sfx_recs if r["index"] != rec["index"] and (
            fam[r["index"]] == fam[rec["index"]] or (mine and idfam.get(r["index"]) == mine))]
        mates += [ids[x] for x in layer if x in ids and ids[x] != rec["index"]]
        mates += [r["index"] for r in sfx_recs if rec["id"] in ([tracks[r["index"]].get("layer")]
                                                               if isinstance(tracks[r["index"]].get("layer"), str)
                                                               else list(tracks[r["index"]].get("layer") or []))]
        own = y_s + sum((placed[i] for i in set(mates) if i != rec["index"]), np.zeros_like(y_s))
        before = rec.get("end") is not None and float(at) >= float(rec["end"]) - 0.06 and \
            float(rec["end"]) - float(rec.get("start", 0.0)) > 0.3
        above = _audibility(y_s, total - own, float(at), win=min(1.0, float(rec["end"]) - float(rec.get("start", 0.0)))
                            if before else 0.35, before=before)
        rec["above_bed_db"] = above
        if tr.get("texture"):
            rec["texture"] = True
            continue
        if above is not None and above < 0:
            masked.append((fam[rec["index"]], rec, float(at), -above))
    out: List[str] = []
    i = 0
    while i < len(masked):
        j = i + 1
        while j < len(masked) and masked[j][0] == masked[i][0]:
            j += 1
        grp = masked[i:j]
        if len(grp) == 1:
            _, rec, at, under = grp[0]
            out.append("sfx %s at %.2fs is %.1f dB under the rest of the mix there (likely masked): raise its gain_db, "
                       "duck the bed under it (\"duck\": {\"under\": [\"%s\"]}), or mark it \"texture\": true if it "
                       "is meant to sit under" % (rec["id"], at, under, rec["id"]))
        else:
            n_fam = sum(1 for r in sfx_recs if fam[r["index"]] == grp[0][0])
            unders = [g[3] for g in grp]
            out.append("sfx %s .. %s (%d of %d \"%s\" tracks, %.2f-%.2fs) are %.1f-%.1f dB under the rest of the mix "
                       "(likely masked): raise their gain_db, duck the bed under them, or mark them \"texture\": true "
                       "if they are meant to sit under" % (grp[0][1]["id"], grp[-1][1]["id"], len(grp), n_fam, grp[0][0],
                                                            grp[0][2], grp[-1][2], min(unders), max(unders)))
        i = j
    return out


def _sections(spec: dict, placed_meta: List[dict], dur: float) -> List[dict]:
    s = spec.get("sections")
    out: List[dict] = []
    if isinstance(s, dict):
        items = sorted(((str(k), float(v)) for k, v in s.items()), key=lambda z: z[1])
        for i, (nm, t) in enumerate(items):
            out.append({"name": nm, "start": t, "end": items[i + 1][1] if i + 1 < len(items) else dur})
    elif isinstance(s, list):
        for i, it in enumerate(s):
            if isinstance(it, dict):
                st_ = float(it.get("start", 0))
                en = float(it.get("end", s[i + 1].get("start") if i + 1 < len(s) and isinstance(s[i + 1], dict) else dur))
                out.append({"name": str(it.get("name", "s%d" % i)), "start": st_, "end": en})
    elif isinstance(s, str) and s.strip():
        from .compose import parse_sections
        items = parse_sections(s, dur)
        for i, (nm, t) in enumerate(items):
            out.append({"name": nm, "start": t, "end": items[i + 1][1] if i + 1 < len(items) else dur})
    if not out:
        for m in placed_meta:
            b = m.get("beats")
            if b and b.get("source") == "composed" and b.get("sections") and not m.get("fitted"):
                off = m.get("start", 0.0)
                for sec in b["sections"]:
                    out.append({"name": sec["name"], "start": round(sec["start"] + off, 3), "end": round(sec["end"] + off, 3)})
                if b.get("end_hit") is not None and b["end_hit"] + off < dur - 0.05:
                    out.append({"name": "ending", "start": round(b["end_hit"] + off, 3), "end": round(dur, 3)})
                break
    if not out:
        step = 5.0 if dur > 10 else max(1.0, dur / 2)
        t = 0.0
        while t < dur - 1e-6:
            out.append({"name": "%.0f-%.0fs" % (t, min(dur, t + step)), "start": t, "end": min(dur, t + step)})
            t += step
    return out


def _question_beats(spec: dict, bases: List[Path], spec_path: Optional[Path]) -> Tuple[List[dict], Dict[str, Any]]:
    """The project's question beats and the mix's "questions" options ({} when the block is absent)."""
    q = spec.get("questions")
    if not q:
        return [], {}
    opts = dict(q) if isinstance(q, dict) else {}
    proj = next((b for b in bases if (Path(b) / "showtime.json").is_file()), None)
    if proj is None:
        return [], opts
    mix_dir = spec_path.resolve().parent if spec_path else None
    return _questions.beats(Path(proj), [t for t in spec.get("tracks") or [] if isinstance(t, dict)], mix_dir), opts


def _qnum(opts: Dict[str, Any], name: str, default: float, lo: float, hi: float) -> float:
    v = opts.get(name)
    if v is None:
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ShowtimeError("mix \"questions\": %s must be a number (got %r)" % (name, v))
    if not lo <= f <= hi:
        raise ShowtimeError("mix \"questions\": %s=%s is out of range [%s, %s]" % (name, f, lo, hi))
    return f


def _beat_duck(beats: List[dict], depth_db: float, n: int) -> np.ndarray:
    """Gain (linear) that lowers a bed by depth_db through every beat: 0.25 s in, 0.4 s out."""
    pts: List[Tuple[float, float]] = [(0.0, 0.0)]
    for b in beats:
        a, e = float(b["t"]), float(b["resume"])
        pts += [(max(pts[-1][0], a - 0.25), 0.0), (max(pts[-1][0], a), -depth_db), (max(pts[-1][0], e), -depth_db),
                (max(pts[-1][0], e + 0.4), 0.0)]
    return _envelope(pts, n)


def render(spec: Any, out_path, spec_path: Optional[Path] = None, root: Optional[Path] = None,
           report_path: Optional[Path] = None, ffmpeg_check: bool = False) -> Dict:
    if isinstance(spec, (str, Path)):
        spec_path = Path(spec)
        spec = read_json(spec_path)
    if not isinstance(spec, dict) or not isinstance(spec.get("tracks"), list) or not spec["tracks"]:
        raise ShowtimeError("mix spec needs a non-empty 'tracks' list", hint="see references/audio.md for the mix.json format")
    out_path = Path(out_path)
    sr_out = int(spec.get("sample_rate") or SR)
    if sr_out not in (44100, 48000):
        raise ShowtimeError("sample_rate must be 48000 or 44100")
    bases = _bases(spec_path, root)
    # stop-and-ask questions: a soft tick on each second of every pause and think beat (opt-in)
    qbeats, qopts = _question_beats(spec, bases, spec_path)
    ticks = []
    if qbeats and qopts.get("tick"):
        for b in qbeats:
            for k in range(int(math.ceil(float(b["think"]) - 1e-6))):
                ticks.append({"id": "q-tick-%s-%d" % (b["id"], k + 1), "kind": "sfx", "texture": True, "align": "hit",
                              "synth": {"type": "tick", "intensity": 0.5, "seed": 17 + k}, "at": round(b["t"] + k, 4),
                              "gain_db": _qnum(qopts, "tick_gain_db", -4.0, -40.0, 12.0)})
    if ticks:
        spec = dict(spec, tracks=list(spec["tracks"]) + ticks)
    tracks = spec["tracks"]
    # load sources first (needed to infer the duration)
    loaded = []
    dur = spec.get("duration")
    for i, tr in enumerate(tracks):
        if not isinstance(tr, dict):
            raise ShowtimeError("track %d must be an object" % i)
        kind = (tr.get("kind") or "sfx").lower()
        if kind not in KINDS:
            raise ShowtimeError("track %d: kind must be one of %s" % (i, ", ".join(KINDS)))
        if tr.get("mute"):
            continue
        loaded.append((i, tr, kind))
    if dur is None or dur == "project":
        # a mix inside a showtime project follows the video's length (showtime.json "duration")
        dur = _project_duration(bases)
    if dur is None:
        # infer from the sources that are not compose/loop (those fill the mix)
        ends = []
        for i, tr, kind in loaded:
            if tr.get("compose") or tr.get("loop") or tr.get("fit"):
                continue
            s = load_source(tr, i, bases, 0.0)
            tr["_src"] = s
            st_ = float(tr.get("start") or 0.0) if tr.get("at") is None else float(tr["at"])
            ends.append(st_ + len(s.audio) / SR - source_offset(tr, i, s.meta)[0])
        if not ends:
            raise ShowtimeError("mix spec needs a 'duration' (no fixed-length track to infer it from)")
        dur = max(ends)
    dur = float(dur)
    if dur <= 0 or dur > 3600:
        raise ShowtimeError("duration must be between 0 and 3600 seconds")
    N = int(round(dur * SR))
    q_depth = _qnum(qopts, "duck_db", 12.0, 0.0, 40.0) if qbeats else 0.0
    q_env = _beat_duck(qbeats, q_depth, N) if qbeats and q_depth > 0 else None
    buses: Dict[str, np.ndarray] = {}
    per_track: List[Dict] = []
    placed: Dict[int, np.ndarray] = {}
    used_lib: Dict[str, dict] = {}
    warnings: List[str] = []
    for i, tr, kind in loaded:
        src = tr.pop("_src", None) or load_source(tr, i, bases, dur)
        level = (tr.get("level") or "auto").lower()
        g_auto, linfo = (0.0, {"reference": "raw"}) if level == "raw" else auto_level(src.audio, kind, src.meta)
        gain = g_auto + _num(tr.get("gain_db"), "gain_db", i, 0.0, -60.0, 24.0)
        src.audio = src.audio * 10 ** (gain / 20)
        y, pinfo = place(tr, i, src, kind, N, dur)
        if y.shape[0] == 0:
            y = np.zeros((N, 2), np.float32)
        gpts = _gain_points(tr, i, src.meta, float(pinfo.get("start", 0.0) or 0.0), dur)
        if gpts:
            y = y * _envelope(gpts, y.shape[0])[:, None]
            pinfo = dict(pinfo, gain_points=[[round(t, 3), round(d, 2)] for t, d in gpts])
        if q_env is not None and kind in ("music", "ambience") and y.shape[0] == N:
            y = y * q_env[:, None]
            pinfo = dict(pinfo, question_duck_db=q_depth)
        placed[i] = y
        tid = str(tr.get("id") or "%s%d" % (kind, i))
        rec = {"id": tid, "index": i, "kind": kind, "source": src.meta.get("source"),
               "path": src.meta.get("path"), "gain_db": round(gain, 2), "level": linfo, **pinfo}
        if src.meta.get("catalog_id"):
            rec["catalog_id"] = src.meta["catalog_id"]
            used_lib["music:" + src.meta["catalog_id"]] = dict(src.meta["credit"])
        if src.meta.get("library_id"):
            rec["library_id"] = src.meta["library_id"]
            used_lib[src.meta["library_id"]] = {"id": src.meta["library_id"], "title": src.meta.get("title"),
                                                "artist": src.meta.get("artist"), "kind": kind,
                                                "license": src.meta.get("license"),
                                                "attribution": src.meta.get("attribution"),
                                                "attribution_required": src.meta.get("attribution_required"),
                                                "credit_optional": src.meta.get("credit_optional"),
                                                "source_url": src.meta.get("source_url")}
        if src.meta.get("matched_library"):
            rec["matched_library"] = True
        if src.meta.get("matched_catalog"):
            rec["matched_catalog"] = True
        elif kind == "music" and src.meta.get("source") == "file" and not src.meta.get("license"):
            warnings.append("music track %s (%s) has no license information: use \"lib\": \"<id>\" for a library "
                            "track, or put a %s.license.json next to the file, so the credits are right"
                            % (tid, Path(src.meta.get("path") or "?").name, Path(src.meta.get("path") or "?").name))
        if src.meta.get("license") and not src.meta.get("library_id") and not src.meta.get("catalog_id"):
            rec["license"] = src.meta["license"]
            if src.meta.get("attribution_required") or src.meta["license"] not in ("generated", "CC0-1.0"):
                used_lib["file:" + tid] = {"id": "file:" + tid, "title": Path(src.meta.get("path") or "").name,
                                           "kind": kind, "license": src.meta["license"],
                                           "attribution": src.meta.get("attribution"),
                                           "attribution_required": bool(src.meta.get("attribution_required"))}
        if src.meta.get("noncommercial"):
            warnings.append("track %s is MusicGen output (CC-BY-NC-4.0): not for commercial videos" % tid)
        if src.meta.get("synth"):
            rec["synth"] = {k: src.meta["synth"].get(k) for k in ("type", "hit", "category", "duration")}
        if src.meta.get("compose"):
            bj = src.meta.get("beats") if isinstance(src.meta.get("beats"), dict) else {}
            # what was actually used (the request may say "auto" / a family name): the license line needs it
            rec["compose"] = dict(src.meta["compose"], backend_used=bj.get("backend"), soundfont_file=bj.get("soundfont"))
            for n in bj.get("notes") or []:
                warnings.append("track %s (compose): %s" % (tid, n))
            rec["beats_file"] = str(Path(src.meta["path"]).with_name("music.beats.json"))
        bts = src.meta.get("beats") if isinstance(src.meta.get("beats"), dict) else None
        if bts and kind == "music" and not pinfo.get("fit"):
            # musical landmarks on the output timeline: line the logo up with end_hit, cuts with downbeats
            off = float(pinfo.get("start", 0.0) or 0.0) - float(pinfo.get("offset") or 0.0)
            if bts.get("end_hit") is not None:
                rec["end_hit"] = round(float(bts["end_hit"]) + off, 3)
            if bts.get("sections"):
                rec["music_sections"] = [{"name": x.get("name"), "start": round(float(x["start"]) + off, 3),
                                          "end": round(float(x["end"]) + off, 3)} for x in bts["sections"]]
            if bts.get("downbeats"):
                rec["downbeats"] = [round(float(t) + off, 3) for t in bts["downbeats"] if 0 <= float(t) + off <= dur][:64]
        rec["_meta"] = {"beats": src.meta.get("beats"), "start": pinfo.get("start", 0.0),
                        "fitted": bool(pinfo.get("fit")) and pinfo["fit"].get("mode") == "loop"}
        if src.meta.get("speech"):
            rec["_speech"] = src.meta["speech"]
        per_track.append(rec)
    # ducking (after all tracks are placed, so keys include everything)
    for rec in per_track:
        tr = tracks[rec["index"]]
        d = tr.get("duck")
        c = tr.get("carve")
        if not d and not c:
            continue
        d = d if isinstance(d, dict) else ({"under": "voice"} if d else {})
        under = d.get("under", "voice") if d else (c.get("under", "voice") if isinstance(c, dict) else "voice")
        under = [under] if isinstance(under, str) else list(under)
        key = np.zeros((N, 2), np.float32)
        segs: List[Tuple[float, float]] = []
        for other in per_track:
            if other is rec:
                continue
            if other["kind"] in under or other["id"] in under:
                key += placed[other["index"]]
                for a_, b_ in other.get("_speech") or []:
                    segs.append((a_ + other.get("start", 0.0), b_ + other.get("start", 0.0)))
        if not np.any(key):
            warnings.append("track %s ducks under %s, but no such track is playing" % (rec["id"], "/".join(under)))
            continue
        y = placed[rec["index"]]
        carve_s = d.get("carve", c if isinstance(c, (int, float)) else (c or {}).get("strength", 0)) if d else \
            (c if isinstance(c, (int, float)) else (c or {}).get("strength", 0.5))
        if carve_s:
            y, cinfo = carve(y, key, float(carve_s))
            rec["carve"] = cinfo
        if d:
            extra = segments_mask(segs, N, hold=float(d.get("hold", 0.3))) if segs else None
            g, dinfo = duck_gain(key, N, float(d.get("depth_db", DUCK_DB)), float(d.get("attack", 0.08)),
                                 float(d.get("release", 0.5)), float(d.get("hold", 0.3)), float(d.get("lookahead", 0.12)),
                                 extra=extra)
            if segs:
                dinfo["word_timings"] = True
            y = y * g[:, None]
            rec["duck"] = {"under": under, "depth_db": float(d.get("depth_db", DUCK_DB)), **dinfo}
        placed[rec["index"]] = y
    for rec in per_track:
        buses.setdefault(rec["kind"], np.zeros((N, 2), np.float32))
        buses[rec["kind"]] += placed[rec["index"]]
    mix = sum(buses.values()) if buses else np.zeros((N, 2), np.float32)
    ms = spec.get("master") or {}
    lufs = float(ms.get("lufs", -14.0))
    tp = float(ms.get("true_peak", ms.get("tp", -1.0)))
    engine = (ms.get("engine") or "st").lower()
    pre = meter.measure(mix)
    if engine == "st":
        y, minfo = master.normalize(mix, lufs, tp)
        if out_path.suffix.lower() in master.LOSSY or sr_out != SR:
            y = master.save_to_target(out_path, _resample(y, sr_out), lufs, tp, sr=sr_out)
            if sr_out != SR or out_path.suffix.lower() in master.LOSSY:
                y = wav.load(out_path)
        else:
            wav.save(out_path, y, sr=sr_out, bits=24)
    elif engine == "loudnorm":
        tmp = out_path.with_name(".%s.premaster.wav" % out_path.stem)
        wav.save(tmp, mix, bits=32)
        try:
            minfo = master.loudnorm_file(tmp, out_path, lufs, tp)
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
        y = wav.load(out_path)
        chk = meter.integrated(y)
        if abs(chk - lufs) > 0.5:
            warnings.append("loudnorm engine landed at %.2f LUFS (target %.1f); the default 'st' engine is exact" % (chk, lufs))
    elif engine == "none":
        y, minfo = mix, {"note": "no mastering"}
        wav.save(out_path, _resample(y, sr_out), sr=sr_out, bits=24)
    else:
        raise ShowtimeError("master.engine must be st, loudnorm or none")
    gain_lin = 10 ** ((minfo.get("gain_db") or 0.0) / 20) if engine == "st" else 1.0
    post = meter.measure(wav.load(out_path) if out_path.suffix.lower() not in (".wav", ".flac") else y)
    # per-section levels
    secs = _sections(spec, [r["_meta"] for r in per_track], dur)
    sec_rows = []
    for s_ in secs:
        a, b = int(max(0, s_["start"]) * SR), int(min(dur, s_["end"]) * SR)
        if b <= a:
            continue
        seg = y[a:b]
        row = {"name": s_["name"], "start": round(s_["start"], 3), "end": round(s_["end"], 3),
               "rms_dbfs": round(20 * math.log10(float(np.sqrt((seg.astype(np.float64) ** 2).mean())) + 1e-12), 2),
               "peak_dbfs": round(20 * math.log10(float(np.abs(seg).max()) + 1e-12), 2),
               "lufs": meter._r(meter.integrated(seg)) if (b - a) >= 0.4 * SR else None, "buses_rms_dbfs": {}}
        for k, bus in buses.items():
            bs = bus[a:b] * gain_lin
            row["buses_rms_dbfs"][k] = round(20 * math.log10(float(np.sqrt((bs.astype(np.float64) ** 2).mean())) + 1e-12), 1)
        sec_rows.append(row)
    # voice vs music during speech
    vm = None
    if "voice" in buses and ("music" in buses or "ambience" in buses):
        act = activity(buses["voice"], 0.1)
        if act.any():
            h = int(0.1 * SR)
            vb = buses["voice"][: len(act) * h]
            mb = sum(buses[k] for k in ("music", "ambience") if k in buses)[: len(act) * h]
            idx = np.repeat(act, h)[: len(vb)]
            v_db = 20 * math.log10(float(np.sqrt((vb[idx] ** 2).mean())) + 1e-12)
            m_db = 20 * math.log10(float(np.sqrt((mb[idx] ** 2).mean())) + 1e-12)
            vm = round(v_db - m_db, 2)
            if vm < 8:
                warnings.append("music is only %.1f dB under the voice while speaking (aim for 10-20 dB): "
                                "lower the music gain_db or add duck/carve" % vm)
    # the dry narration stem (before any music): transcription and captions read this instead of the
    # mix, so speech under a ducked bed is never missed. 16 kHz mono, next to the output.
    voice_stem = None
    if "voice" in buses and any(k in buses for k in ("music", "ambience", "sfx")):
        try:
            v16 = signal.resample_poly(dsp.to_mono(buses["voice"] * gain_lin), 1, 3).astype(np.float32)
            voice_stem = out_path.with_name(out_path.stem + ".voice.wav")
            wav.save(voice_stem, v16, sr=16000, bits=16)
        except Exception as e:  # noqa: BLE001 - a convenience for transcription, never fails the mix
            warn("could not write the narration stem: %s" % e)
            voice_stem = None
    # a hook far under the body sounds broken in a feed (autoplay starts on the quiet part)
    lvl = [r for r in sec_rows if r.get("lufs") is not None]
    if len(lvl) >= 2:
        loudest = max(r["lufs"] for r in lvl)
        if lvl[0]["lufs"] < loudest - 6:
            warnings.append("the first section (%s, %.1f LUFS) is %.1f LU under the loudest (%.1f): the hook may sound "
                            "too quiet in feeds; lift it with section_gain / gain_points on the bed, or add a drone or "
                            "ambience under it" % (lvl[0]["name"], lvl[0]["lufs"], loudest - lvl[0]["lufs"], loudest))
    # can each effect be heard over everything else?
    warnings += _masking(per_track, placed, tracks)
    if post.get("clip_runs"):
        warnings.append("output has %d clipped runs" % post["clip_runs"])
    for w in minfo.get("warning", "").split("\n") if isinstance(minfo.get("warning"), str) else []:
        if w:
            warnings.append(w)
    from . import credits as credmod
    credit_items = credmod.normalize(u for u in used_lib.values() if u.get("license") != "generated")
    credmod.check(credit_items)        # a CC BY sound without its credit text stops the mix (never a silent omission)
    credits = [u for u in credit_items if u.get("attribution_required") and u.get("attribution")]
    credits_path = None
    if credits:
        credits_path = credits_file(out_path.parent)
        credits_path.write_text(credmod.render(credit_items)["credits_txt"], encoding="utf-8", newline="\n")
    for n in credmod.content_id_notes(credit_items):
        log("note: " + n)
    rp = Path(report_path) if report_path else out_path.with_name(out_path.stem + ".report.json")
    if report_path is None and spec_path is not None and spec_path.name == "mix.json":
        rp = out_path.with_name("mix.report.json")
    for r in per_track:
        r.pop("_meta", None)
        r.pop("_speech", None)
        # paths relative to the report (reports get copied into review packs and examples)
        for k in ("path", "beats_file"):
            if r.get(k):
                r[k] = portable_path(r[k], rp.parent)
    report = {
        "schema": "showtime.mix.report/1", "output": portable_path(out_path, rp.parent), "duration": round(dur, 4), "sample_rate": sr_out,
        "master": {"target_lufs": lufs, "target_true_peak": tp, "engine": engine, **minfo},
        "integrated_lufs": post["integrated_lufs"], "true_peak_dbtp": post["true_peak_dbtp"], "lra": post["lra"],
        "short_term_max_lufs": post["short_term_max_lufs"], "sample_peak_dbfs": post["sample_peak_dbfs"],
        "premaster": {"integrated_lufs": pre["integrated_lufs"], "true_peak_dbtp": pre["true_peak_dbtp"]},
        "voice_to_music_db": vm, "sections": sec_rows, "tracks": per_track,
        "library_items": sorted(k for k in used_lib if not k.startswith(("file:", "music:"))), "credits": [c["attribution"] for c in credits],
        "credit_items": credit_items,
        "catalog_items": sorted(k[len("music:"):] for k in used_lib if k.startswith("music:")),
        "credits_file": portable_path(credits_path, rp.parent) if credits_path else None, "warnings": warnings,
        "voice_stem": portable_path(voice_stem, rp.parent) if voice_stem else None,
    }
    if spec.get("questions"):
        report["questions"] = {"beats": [{k: b[k] for k in ("id", "t", "resume")} for b in qbeats],
                               "duck_db": q_depth, "ticks": len(ticks)}
        if not qbeats:
            warnings.append("the mix has a \"questions\" block, but the project has no questions with a time "
                            "(showtime.json \"questions\"; `showtime check` names any that do not resolve)")
    if ffmpeg_check:
        report["ffmpeg_ebur128"] = meter.ffmpeg_ebur128(out_path)
    write_json(rp, report)
    report["report_file"] = str(rp)
    for w in warnings:
        warn(w)
    return report


def _resample(y: np.ndarray, sr_out: int) -> np.ndarray:
    if sr_out == SR:
        return y
    return signal.resample_poly(y, 147, 160, axis=0).astype(np.float32)

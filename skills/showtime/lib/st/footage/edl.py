"""The edit decision list (EDL): schema, validation and the frame-exact plan.

Minimal EDL (paths are relative to the EDL file):

    {"sources": {"a": "../raw/take1.mp4"},
     "ranges": [{"source": "a", "start": 2.40, "end": 7.95},
                {"source": "a", "start": 9.10, "end": 15.30, "note": "the payoff"}]}

Full reference: references/editing.md. Every field except sources/ranges is
optional and has a sensible default:

    "output":   {"aspect": "9:16" | "16:9" | "1:1" | "4:5" | "4k" | ..., "width", "height",
                 "fps": 30, "fit": "auto|cover|contain|blur|reframe", "background": "#000"}
    "grade":    "none" | "auto" | preset | {"auto": true, "preset": "punch", "lut": "teal-orange", "strength": 0.6}
    "overlays": [{"file", "start", "duration", "offset", "position", "x", "y", "width", "scale",
                  "opacity", "fade", "audio", "volume_db", "fit"}]
    "audio":    {"music": "bed.wav" | {...}, "tracks": [mix.json tracks on the OUTPUT timeline],
                 "denoise": false | "auto" | "deepfilter" | "rnnoise" | "afftdn",
                 "crossfade": 0.02 (seconds of equal-power audio crossfade at each cut, 0-0.05;
                              0 = the older 30 ms fade-out/fade-in)}
    "captions": false | "bold-pop" | {"style": "clean", ...caption options}
    "subtitles": "subs.ass" | "subs.srt"          (a ready-made file instead of generated captions)
    "loudness": {"lufs": -14, "tp": -1} | -16 | false | "source"   (default -14 LUFS / -1 dBTP, like every delivery)
    "transcripts": {"a": "transcripts/take1.json"}   (default: found next to the EDL / source)

Per range (all optional): fit, zoom (1.0-3.0 punch-in), focus {"x": 0..1, "y": 0..1},
grade (overrides the global grade), stabilize (true), volume_db, mute.
"""
from __future__ import annotations

import os
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..common import ShowtimeError, parse_time, read_json
from . import util as U

ASPECTS: Dict[str, Tuple[int, int]] = {
    "16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350), "4:3": (1440, 1080),
    "3:4": (1080, 1440), "21:9": (2560, 1080), "2:1": (2160, 1080),
    "720p": (1280, 720), "1080p": (1920, 1080), "1440p": (2560, 1440), "4k": (3840, 2160), "2160p": (3840, 2160),
    "4k-vertical": (2160, 3840), "9:16-4k": (2160, 3840), "vertical": (1080, 1920), "square": (1080, 1080),
    "landscape": (1920, 1080), "portrait": (1080, 1350),
}
FITS = ("auto", "cover", "contain", "blur", "reframe")
AUDIO_SR = 48000


def _even(v: float) -> int:
    return max(2, int(round(v / 2.0)) * 2)


def _num(v: Any, what: str, errs: List[str], lo: Optional[float] = None, hi: Optional[float] = None) -> Optional[float]:
    if v is None:
        return None
    try:
        x = parse_time(v) if isinstance(v, str) else float(v)
    except (ShowtimeError, TypeError, ValueError):
        errs.append("%s: %r is not a number" % (what, v))
        return None
    if lo is not None and x < lo or hi is not None and x > hi:
        errs.append("%s: %s is out of range [%s, %s]" % (what, v, lo, hi))
    return x


def resolve_path(p: str, base: Path) -> Path:
    q = Path(os.path.expanduser(str(p)))
    if not q.is_absolute():
        q = (base / q)
    return q.resolve()


def load(path, *, overrides: Optional[Dict[str, Any]] = None, check_files: bool = True) -> Dict[str, Any]:
    """Read + validate an EDL. Raises ShowtimeError listing every problem.
    check_files=False accepts a "subtitles" file that does not exist yet (a script that loads the
    EDL to write that very file); `edit render` still requires it."""
    p = Path(path).expanduser().resolve()
    raw = read_json(p)
    if overrides:
        raw = dict(raw)
        for k, v in overrides.items():
            cur = raw.get(k)
            if k == "captions" and isinstance(v, dict) and isinstance(cur, dict) and v.get("style") \
                    and v.get("style") != cur.get("style"):
                # another style: start from that style's own defaults (position, size, chars ...),
                # keeping only which sidecars to write
                raw[k] = dict({x: cur[x] for x in ("srt", "vtt") if x in cur}, **v)
            elif isinstance(v, dict) and isinstance(cur, dict):
                raw[k] = dict(cur, **v)
            else:
                raw[k] = v
    return normalize(raw, p.parent, str(p), check_files=check_files)


def normalize(raw: Dict[str, Any], base: Path, origin: str = "EDL", check_files: bool = True) -> Dict[str, Any]:
    errs: List[str] = []
    if not isinstance(raw, dict):
        raise ShowtimeError("%s: the EDL must be a JSON object" % origin)
    src_in = raw.get("sources")
    if isinstance(src_in, (list, tuple)):
        src_in = {Path(str(s)).stem: s for s in src_in}
    if isinstance(src_in, str):
        src_in = {Path(src_in).stem: src_in}
    if not isinstance(src_in, dict) or not src_in:
        raise ShowtimeError("%s: 'sources' must map names to media files, e.g. {\"a\": \"take1.mp4\"}" % origin)
    sources: Dict[str, Dict[str, Any]] = {}
    for key, val in src_in.items():
        sp = resolve_path(val if isinstance(val, str) else (val or {}).get("file", ""), base)
        if not sp.is_file():
            errs.append("source %r: file not found: %s" % (key, sp))
            continue
        try:
            pr = U.probe(sp)
        except ShowtimeError as e:
            errs.append("source %r: %s" % (key, e))
            continue
        if not pr.get("has_video"):
            errs.append("source %r has no video stream (%s)" % (key, sp.name))
        track = int((val or {}).get("audio_track", 0)) if isinstance(val, dict) else 0
        if track and track >= len(pr.get("audio_streams") or []):
            errs.append("source %r: audio_track %d does not exist (%d track(s))" % (
                key, track, len(pr.get("audio_streams") or [])))
        sources[str(key)] = {"path": sp, "probe": pr, "audio_track": track}

    ranges_in = raw.get("ranges") or raw.get("segments") or []
    if not isinstance(ranges_in, list) or not ranges_in:
        errs.append("'ranges' must be a non-empty list of {source, start, end}")
        ranges_in = []
    only = next(iter(sources)) if len(sources) == 1 else None
    ranges: List[Dict[str, Any]] = []
    for i, r in enumerate(ranges_in):
        where = "ranges[%d]" % i
        if not isinstance(r, dict):
            errs.append("%s must be an object" % where)
            continue
        key = str(r.get("source", only or ""))
        if key not in sources:
            if key in src_in:
                continue  # already reported
            errs.append("%s: unknown source %r (known: %s)" % (where, key, ", ".join(sources) or "none"))
            continue
        s = _num(r.get("start"), where + ".start", errs, lo=0)
        e = _num(r.get("end"), where + ".end", errs, lo=0)
        if e is None and r.get("duration") is not None and s is not None:
            d = _num(r.get("duration"), where + ".duration", errs, lo=0)
            e = s + d if d is not None else None
        if s is None or e is None:
            if "start" not in r or ("end" not in r and "duration" not in r):
                errs.append("%s needs start and end (seconds)" % where)
            continue
        dur = sources[key]["probe"].get("duration") or 0.0
        if e <= s:
            errs.append("%s: end (%.3f) must be after start (%.3f)" % (where, e, s))
            continue
        if dur and s >= dur:
            errs.append("%s: start %.3f is past the end of %s (%.3f s)" % (where, s, key, dur))
            continue
        if dur and e > dur + 0.05:
            errs.append("%s: end %.3f is past the end of %s (%.3f s); clamp it or pick another range" % (where, e, key, dur))
            continue
        e = min(e, dur) if dur else e
        item = {"index": i, "source": key, "start": s, "end": e}
        fit = r.get("fit")
        if fit is not None and fit not in FITS:
            errs.append("%s.fit must be one of %s" % (where, ", ".join(FITS)))
        for k in ("fit", "grade", "stabilize", "note", "mute", "label", "focus"):
            if r.get(k) is not None:
                item[k] = r[k]
        z = _num(r.get("zoom"), where + ".zoom", errs, lo=1.0, hi=3.0)
        if z is not None:
            item["zoom"] = z
        v = _num(r.get("volume_db"), where + ".volume_db", errs, lo=-60, hi=24)
        if v is not None:
            item["volume_db"] = v
        ranges.append(item)

    output = _output(raw.get("output") or {}, sources, errs)
    overlays = _overlays(raw.get("overlays") or [], base, errs)
    audio = _audio(raw.get("audio") or {}, raw, base, errs)
    captions = _captions(raw.get("captions"), errs)
    subtitles = None
    if raw.get("subtitles"):
        subtitles = resolve_path(raw["subtitles"], base)
        if not subtitles.is_file() and check_files:
            errs.append("subtitles file not found: %s (remove 'subtitles' or create the file)" % subtitles)
    lo = raw.get("loudness", {"lufs": -14.0, "tp": -1.0})
    if lo is False or lo is None or (isinstance(lo, str) and lo.strip().lower() in ("source", "keep", "none", "off")):
        loud = None    # keep the source level (no mastering)
    elif isinstance(lo, (int, float)):
        loud = {"lufs": float(lo), "tp": -1.0}
    elif isinstance(lo, dict):
        loud = {"lufs": float(lo.get("lufs", -14.0)), "tp": float(lo.get("tp", lo.get("true_peak", -1.0)))}
    else:
        errs.append("loudness must be a LUFS number, {lufs, tp}, or false / \"source\" to keep the source level")
        loud = None
    trs = {}
    for k, v in (raw.get("transcripts") or {}).items():
        trs[str(k)] = resolve_path(v, base)
    if errs:
        raise ShowtimeError("%s has %d problem(s):\n  - %s" % (origin, len(errs), "\n  - ".join(errs)),
                            hint="fix the EDL and run again (`showtime edit check <edl>` validates without rendering)")
    return {"version": int(raw.get("version", 1)), "dir": base, "origin": origin, "sources": sources,
            "ranges": ranges, "output": output, "grade": raw.get("grade", "none"), "overlays": overlays,
            "audio": audio, "captions": captions, "subtitles": subtitles, "loudness": loud,
            "transcripts": trs, "title": raw.get("title")}


def _output(o: Dict[str, Any], sources: Dict[str, Dict[str, Any]], errs: List[str]) -> Dict[str, Any]:
    if isinstance(o, str):
        o = {"aspect": o}
    first = next(iter(sources.values()))["probe"] if sources else {}
    w, h = o.get("width"), o.get("height")
    aspect = o.get("aspect") or o.get("size")
    if aspect:
        key = str(aspect).lower()
        if key not in ASPECTS:
            errs.append("output.aspect %r unknown (use %s)" % (aspect, ", ".join(ASPECTS)))
            aw, ah = 1920, 1080
        else:
            aw, ah = ASPECTS[key]
        if w and not h:
            w, h = int(w), _even(int(w) * ah / aw)
        elif h and not w:
            w, h = _even(int(h) * aw / ah), int(h)
        elif not w and not h:
            w, h = aw, ah
    if not w or not h:
        sw = first.get("display_width") or 1920
        sh = first.get("display_height") or 1080
        scale = min(1.0, 3840.0 / max(sw, sh))
        w, h = _even(sw * scale), _even(sh * scale)
    w, h = int(w), int(h)
    if w % 2 or h % 2:
        w, h = _even(w), _even(h)
    if not (16 <= w <= 7680 and 16 <= h <= 7680):
        errs.append("output size %dx%d is out of range" % (w, h))
    fps = U.parse_fps(o.get("fps")) if o.get("fps") else U.normalize_fps(first.get("fps"))
    fit = o.get("fit", "auto")
    if fit not in FITS:
        errs.append("output.fit must be one of %s" % ", ".join(FITS))
    return {"width": w, "height": h, "fps": fps, "fit": fit, "background": o.get("background", "black"),
            "allow_upscale": bool(o.get("allow_upscale")),
            "aspect_label": aspect or "%dx%d" % (w, h)}


def _pos_val(v: Any, what: str, errs: List[str]) -> Any:
    if v is None or isinstance(v, (int, float)):
        return v
    s = str(v).strip()
    if s.endswith("%"):
        try:
            return {"pct": float(s[:-1]) / 100.0}
        except ValueError:
            pass
    errs.append("%s: %r must be pixels or a percentage like '10%%'" % (what, v))
    return None


def _overlays(items: List[Any], base: Path, errs: List[str]) -> List[Dict[str, Any]]:
    out = []
    if not isinstance(items, list):
        errs.append("overlays must be a list")
        return out
    for i, o in enumerate(items):
        where = "overlays[%d]" % i
        if not isinstance(o, dict) or not o.get("file"):
            errs.append("%s needs a 'file'" % where)
            continue
        f = resolve_path(o["file"], base)
        if not f.is_file():
            errs.append("%s: file not found: %s" % (where, f))
            continue
        is_img = f.suffix.lower() in U.IMAGE_EXTS
        pr = {} if is_img else U.probe(f)
        start = _num(o.get("start", o.get("start_in_output", o.get("at"))), where + ".start", errs, lo=0)
        if start is None:
            errs.append("%s needs 'start' (output-timeline seconds)" % where)
            continue
        offset = _num(o.get("offset", 0), where + ".offset", errs, lo=0) or 0.0
        dur = _num(o.get("duration"), where + ".duration", errs, lo=0.04)
        if dur is None:
            dur = 3.0 if is_img else max(0.04, (pr.get("duration") or 3.0) - offset)
        pos = o.get("position", "full" if o.get("fit") else "center")
        item = {"index": i, "file": f, "image": is_img, "probe": pr, "start": start, "duration": dur,
                "offset": offset, "position": str(pos), "x": _pos_val(o.get("x"), where + ".x", errs),
                "y": _pos_val(o.get("y"), where + ".y", errs),
                "width": _pos_val(o.get("width"), where + ".width", errs),
                "height": _pos_val(o.get("height"), where + ".height", errs),
                "scale": _num(o.get("scale"), where + ".scale", errs, lo=0.01, hi=10),
                "opacity": _num(o.get("opacity", 1.0), where + ".opacity", errs, lo=0, hi=1),
                "fade": _num(o.get("fade", 0.0), where + ".fade", errs, lo=0, hi=5) or 0.0,
                "margin": _num(o.get("margin", 0.04), where + ".margin", errs, lo=0, hi=0.4),
                "fit": o.get("fit", "cover"), "audio": bool(o.get("audio", False)) and bool(pr.get("has_audio")),
                "volume_db": _num(o.get("volume_db", 0.0), where + ".volume_db", errs, lo=-60, hi=24) or 0.0,
                "duck_db": _num(o.get("duck_db"), where + ".duck_db", errs, lo=-60, hi=0)}
        out.append(item)
    return out


def _audio(a: Any, raw: Dict[str, Any], base: Path, errs: List[str]) -> Dict[str, Any]:
    if not isinstance(a, dict):
        errs.append("audio must be an object")
        a = {}
    tracks: List[Dict[str, Any]] = []
    music = a.get("music", raw.get("music"))
    if music:
        m = {"file": music} if isinstance(music, str) else dict(music)
        m.setdefault("kind", "music")
        m.setdefault("gain_db", -2.0)
        m.setdefault("fade_in", 0.5)
        m.setdefault("fade_out", 1.5)
        if "loop" not in m and "fit" not in m:
            m["loop"] = True
        if m.pop("duck", True) is not False:
            m["duck"] = {"under": "voice", "depth_db": 12, "attack": 0.08, "release": 0.5}
        tracks.append(m)
    for t in a.get("tracks") or []:
        if not isinstance(t, dict):
            errs.append("audio.tracks entries must be objects")
            continue
        tracks.append(dict(t))
    for t in tracks:
        if t.get("file"):
            fp = resolve_path(t["file"], base)
            if not fp.is_file():
                errs.append("audio track file not found: %s" % fp)
            t["file"] = str(fp)
    den = a.get("denoise", raw.get("denoise", False))
    if den not in (False, None, True, "auto", "deepfilter", "rnnoise", "afftdn"):
        errs.append("audio.denoise must be false, auto, deepfilter, rnnoise or afftdn")
    xf = a.get("crossfade", 0.02)
    try:
        xf = float(xf or 0.0)
    except (TypeError, ValueError):
        errs.append("audio.crossfade must be seconds (0-0.05), e.g. 0.02")
        xf = 0.02
    if not 0.0 <= xf <= 0.05:
        errs.append("audio.crossfade must be between 0 and 0.05 s (got %s)" % xf)
        xf = min(0.05, max(0.0, xf))
    return {"tracks": tracks, "denoise": ("auto" if den is True else (den or None)),
            "master": a.get("master"), "crossfade": xf}


def _captions(c: Any, errs: List[str]) -> Optional[Dict[str, Any]]:
    if c in (None, False, "none", ""):
        return None
    if c is True:
        return {"style": "bold-pop"}
    if isinstance(c, str):
        return {"style": c}
    if isinstance(c, dict):
        return dict(c, style=c.get("style", "bold-pop"))
    errs.append("captions must be false, a style name, or an object")
    return None


# --------------------------------------------------------------------------
# Frame-exact plan
# --------------------------------------------------------------------------

def plan(edl: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Segments with frame counts and exact output offsets.

    Every range becomes round(duration * fps) output frames (>= 1). Output
    offsets are the running sum of those frame counts / fps (a Fraction), so
    captions, overlays and audio never drift, however many cuts there are.
    The effective source end is start + frames / fps.
    """
    fps: Fraction = edl["output"]["fps"]
    segs = []
    frames_total = 0
    for i, r in enumerate(edl["ranges"]):
        n = max(1, int(round((r["end"] - r["start"]) * fps)))
        out_start = Fraction(frames_total) / fps
        frames_total += n
        out_end = Fraction(frames_total) / fps
        a0 = int(round(out_start * AUDIO_SR))
        a1 = int(round(out_end * AUDIO_SR))
        segs.append(dict(r, i=i, frames=n, src_end=r["start"] + float(Fraction(n) / fps),
                         out_start=float(out_start), out_end=float(out_end), audio_samples=a1 - a0))
    return segs


def retime(segs: List[Dict[str, Any]], fps: Fraction, actual_frames: List[int]) -> List[Dict[str, Any]]:
    """Recompute offsets from the frame counts actually written."""
    total = 0
    for s, n in zip(segs, actual_frames):
        s["frames"] = n
        s["out_start"] = float(Fraction(total) / fps)
        total += n
        s["out_end"] = float(Fraction(total) / fps)
        s["src_end"] = s["start"] + float(Fraction(n) / fps)
    return segs


def join_problems(segs: List[Dict[str, Any]], fps: Any = 30) -> List[str]:
    """Neighbouring ranges of one source that almost touch: an overlap of under a frame repeats a sliver
    of audio (and maybe a frame), a gap of under a frame skips one. Ranges are planned in whole frames
    from their own start, so a split must use the previous range's planned end (src_end)."""
    fr = 1.0 / float(fps or 30)
    out: List[str] = []
    for a, b in zip(segs, segs[1:]):
        if a["source"] != b["source"]:
            continue
        gap = float(b["start"]) - float(a["src_end"])
        if -fr < gap < -1e-4:
            out.append("ranges #%d and #%d of %s overlap by %.0f ms (a repeated sliver of audio): start #%d at %.6f"
                       % (a["i"], b["i"], a["source"], -gap * 1000, b["i"], float(a["src_end"])))
        elif 1e-4 < gap < fr:
            out.append("ranges #%d and #%d of %s leave a %.0f ms gap (a skipped frame): start #%d at %.6f"
                       % (a["i"], b["i"], a["source"], gap * 1000, b["i"], float(a["src_end"])))
    return out


def punch_bounce(segs: List[Dict[str, Any]], fps: Any = 30) -> List[str]:
    """Punch-ins that bounce: the framing scale changes at most cuts of one source and keeps going back
    (1.00 -> 1.12 -> 1.00 ...). On a talking head that reads as a zoom in and straight back out at
    every jump cut, which viewers notice more than the cut it was meant to hide. Returns one problem
    line (or none). Reframe-only splits (same take, continuous time) are not cuts and don't count."""
    tol = 0.5 / float(fps or 30)
    cuts = changes = returns = 0
    last_z: Dict[str, List[float]] = {}
    for a, b in zip(segs, segs[1:]):
        if a["source"] != b["source"]:
            continue
        if abs(float(a["src_end"]) - float(b["start"])) <= tol:
            continue                                         # a reframe-only split, not a cut
        cuts += 1
        za, zb = float(a.get("zoom") or 1.0), float(b.get("zoom") or 1.0)
        if abs(za - zb) < 0.005:
            continue
        changes += 1
        hist = last_z.setdefault(a["source"], [])
        if hist and abs(hist[-1] - zb) < 0.005:
            returns += 1                                     # back to the scale before the last change
        hist.append(za)
    if cuts >= 3 and changes >= 3 and returns >= 2 and changes >= 0.5 * cuts:
        return ["the framing scale changes at %d of %d cuts and keeps going back (a punch-in, then out again): "
                "on a talking head this reads as a bouncing zoom. Leave jump cuts as they are (the default), "
                "or hold one scale for a whole sentence or section (editing.md section 6)" % (changes, cuts)]
    return []


def cut_times(segs: List[Dict[str, Any]], fps: Any = 30) -> List[float]:
    """Output times where the picture cuts: every segment start except the first and except joins
    that continue the same source (a range split only to change the framing)."""
    tol = 0.5 / float(fps or 30)
    out: List[float] = []
    for a, b in zip(segs, segs[1:]):
        if a["source"] == b["source"] and abs(float(a["src_end"]) - float(b["start"])) <= tol:
            continue
        out.append(round(float(b["out_start"]), 4))
    return out


def total_duration(segs: List[Dict[str, Any]]) -> float:
    return segs[-1]["out_end"] if segs else 0.0


def find_transcript(edl: Dict[str, Any], key: str) -> Optional[Path]:
    if key in edl["transcripts"]:
        return edl["transcripts"][key]
    src = edl["sources"][key]["path"]
    track = edl["sources"][key].get("audio_track", 0)
    name = src.stem + (".track%d" % track if track else "") + ".json"
    cands = [edl["dir"] / "transcripts" / name, edl["dir"] / "edit" / "transcripts" / name] + \
        U.transcript_candidates(src, track)
    for c in cands:
        if c.is_file():
            return c
    return None


def load_transcripts(edl: Dict[str, Any], required: bool = False) -> Dict[str, Dict[str, Any]]:
    out = {}
    for key in {r["source"] for r in edl["ranges"]}:
        p = find_transcript(edl, key)
        if p is None:
            if required:
                raise ShowtimeError("no transcript found for source %r (%s)" % (key, edl["sources"][key]["path"].name),
                                    hint="run `showtime transcribe %s` or set \"transcripts\" in the EDL"
                                         % edl["sources"][key]["path"])
            continue
        out[key] = U.load_transcript(p)
    return out


def map_words(segs: List[Dict[str, Any]], transcripts: Dict[str, Dict[str, Any]],
              include_events: bool = True) -> List[Dict[str, Any]]:
    """Transcript words that survive the edit, on the OUTPUT timeline.

    A word is kept when at least half of it lies inside a segment; its times
    are clipped to the segment and shifted by the segment's exact offset.
    """
    out: List[Dict[str, Any]] = []
    for s in segs:
        tr = transcripts.get(s["source"])
        if not tr or s.get("mute"):
            continue
        a, b = s["start"], s["src_end"]
        for w in tr.get("words", []):
            typ = w.get("type", "word")
            if typ == "spacing" or (typ == "audio_event" and not include_events):
                continue
            ws, we = float(w["start"]), float(w["end"])
            ov = min(we, b) - max(ws, a)
            if ov <= 0 or ov < 0.5 * max(we - ws, 1e-3):
                continue
            item = dict(w)
            item["start"] = round(max(ws, a) - a + s["out_start"], 3)
            item["end"] = round(min(we, b) - a + s["out_start"], 3)
            item["src"] = s["source"]
            item["src_start"] = ws
            item["segment"] = s["i"]
            out.append(item)
    out.sort(key=lambda w: w["start"])
    return out


def summary(edl: Dict[str, Any], segs: List[Dict[str, Any]]) -> Dict[str, Any]:
    o = edl["output"]
    return {"output": {"width": o["width"], "height": o["height"], "fps": U.fps_str(o["fps"]), "fit": o["fit"]},
            "sources": {k: str(v["path"]) for k, v in edl["sources"].items()},
            "segments": [{"i": s["i"], "source": s["source"], "src_start": round(s["start"], 3),
                          "src_end": round(s["src_end"], 3), "frames": s["frames"],
                          "out_start": round(s["out_start"], 3), "out_end": round(s["out_end"], 3),
                          **({"note": s["note"]} if s.get("note") else {})} for s in segs],
            "duration": round(total_duration(segs), 3), "cuts": max(0, len(segs) - 1),
            "overlays": len(edl["overlays"]), "captions": (edl["captions"] or {}).get("style"),
            "music_tracks": len(edl["audio"]["tracks"])}

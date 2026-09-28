"""Shared helpers for the footage tools: media discovery, hashing, audio
extraction, energy envelopes, transcript loading/normalisation and fillers.

numpy / soundfile are imported inside the functions that need them.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .. import ff
from ..common import ShowtimeError, ensure_dir, home, part_path

PathLike = Union[str, "os.PathLike[str]"]

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".m2ts", ".mxf", ".ts", ".3gp",
              ".flv", ".wmv", ".mpg", ".mpeg", ".dv"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".aif", ".aiff", ".wma", ".caf"}
MEDIA_EXTS = VIDEO_EXTS | AUDIO_EXTS
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}

STANDARD_FPS = [Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001), Fraction(30),
                Fraction(48), Fraction(50), Fraction(60000, 1001), Fraction(60)]


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------

def collect_media(items: Sequence[PathLike], recursive: bool = True) -> List[Path]:
    """Expand files and folders into a sorted list of media files."""
    out: List[Path] = []
    for it in items:
        p = Path(it).expanduser()
        if p.is_dir():
            it_ = p.rglob("*") if recursive else p.glob("*")
            for f in sorted(it_):
                if f.is_file() and f.suffix.lower() in MEDIA_EXTS and "edit" not in f.relative_to(p).parts[:1]:
                    out.append(f.resolve())
        elif p.is_file():
            out.append(p.resolve())
        else:
            raise ShowtimeError("not found: %s" % p)
    seen, uniq = set(), []
    for f in out:
        k = os.path.normcase(str(f))
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    return uniq


def unique_path(path: PathLike) -> Path:
    """`path`, or `name-2.ext`, `name-3.ext`... so earlier outputs are never overwritten."""
    p = Path(path)
    if not p.exists():
        return p
    k = 2
    while True:
        c = p.with_name("%s-%d%s" % (p.stem, k, p.suffix))
        if not c.exists():
            return c
        k += 1


def quick_hash(path: PathLike, chunk: int = 1 << 20) -> str:
    """Content fingerprint of a (possibly huge) media file: size + first,
    middle and last MiB. Stable across renames/copies, changes on edits."""
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha256(b"st-qh1:%d:" % size)
    with open(p, "rb") as f:
        for off in sorted({0, max(0, size // 2 - chunk // 2), max(0, size - chunk)}):
            f.seek(off)
            h.update(f.read(chunk))
    return h.hexdigest()[:20]


def cache_dir(kind: str) -> Path:
    return ensure_dir(home() / "cache" / kind)


def legacy_edit_dir(media: PathLike) -> Path:
    """<folder of the media>/edit: where older releases wrote transcripts (still read, never written)."""
    return Path(media).resolve().parent / "edit"


def default_edit_dir(media: PathLike, create_job: bool = False) -> Path:
    """Where a session's edit files go: never next to the user's footage without a yes.

    - media inside a job (showtime's own renders) -> <that job>/edit
    - the job the current folder is in, else the newest job under ./showtime-out when it already has
      an edit/ folder -> <job>/edit
    - no job at all: with create_job, a new job `<media name>-edit` is made (./showtime-out/...);
      without it, the would-be location of the newest job, or <media folder>/edit as a last resort
      for read-only lookups.
    Pass --edit-dir to choose any folder (e.g. next to the footage, when the user says so)."""
    from ..job import ledger
    src = Path(media).resolve()
    job = ledger.enclosing_job(src) or ledger.enclosing_job(Path.cwd())
    if job is None:
        # the newest job only when it is already an edit job (an unrelated launch video's job is not)
        newest = ledger.latest()
        if newest is not None and (newest / "edit").is_dir():
            job = newest
    if job is None and create_job:
        from ..common import info
        slug = (src.stem if src.is_file() or src.suffix else src.name) or "footage"
        job, _data = ledger.init("%s-edit" % slug, goal="edit %s" % src.name)
        (job / "edit").mkdir(exist_ok=True)
        info("created job %s for the edit (transcripts go to %s; --edit-dir picks another folder)" % (job.name, job / "edit"))
    if job is None:
        return legacy_edit_dir(src)
    return job / "edit"


def transcript_candidates(media: PathLike, track: int = 0) -> List[Path]:
    """Every place a transcript of `media` may already be: the job-first edit folder, then the
    legacy <media folder>/edit/transcripts/ (read only)."""
    out = [transcript_path(default_edit_dir(media), media, track), transcript_path(legacy_edit_dir(media), media, track)]
    return list(dict.fromkeys(out))


def transcript_path(edit_dir: PathLike, media: PathLike, track: int = 0) -> Path:
    stem = Path(media).stem
    name = stem + (".track%d" % track if track else "") + ".json"
    return Path(edit_dir) / "transcripts" / name


# --------------------------------------------------------------------------
# Probing helpers
# --------------------------------------------------------------------------

_PROBE_CACHE: Dict[str, Dict[str, Any]] = {}


def probe(path: PathLike) -> Dict[str, Any]:
    """ff.probe with a per-process cache and the extra fields footage needs."""
    p = Path(path).resolve()
    try:
        st = p.stat()
    except OSError:
        raise ShowtimeError("file not found: %s" % p)
    key = "%s|%d|%d" % (p, st.st_size, int(st.st_mtime))
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    info = ff.probe(p)
    info.update(_extra_stream_info(p))
    _PROBE_CACHE[key] = info
    return info


def _extra_stream_info(p: Path) -> Dict[str, Any]:
    """VP9/VP8 alpha flag and SAR, which ff.probe does not report."""
    exe = ff.ffprobe_path()
    if not exe:
        return {}
    try:
        cp = ff.run([exe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                     "stream=codec_name,sample_aspect_ratio,r_frame_rate,avg_frame_rate:stream_tags",
                     "-of", "json", str(p)], check=False)
        data = json.loads(cp.stdout or "{}")
    except (ValueError, ShowtimeError):
        return {}
    s = (data.get("streams") or [{}])[0] if data.get("streams") else {}
    tags = {k.lower(): v for k, v in (s.get("tags") or {}).items()}
    out: Dict[str, Any] = {}
    if str(tags.get("alpha_mode", "")) == "1":
        out["vp_alpha"] = True
        out["has_alpha"] = True
    sar = s.get("sample_aspect_ratio")
    if sar and sar not in ("0:1", "1:1", "N/A"):
        out["sar"] = sar
    r, a = _frac(s.get("r_frame_rate")), _frac(s.get("avg_frame_rate"))
    if r and a and abs(r - a) / max(r, a) > 0.05:
        out["vfr"] = True
    return out


def _frac(s: Optional[str]) -> Optional[float]:
    try:
        v = float(Fraction(s)) if s and s not in ("0/0", "N/A") else None
        return v if v and v > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def normalize_fps(fps: Optional[float], default: Fraction = Fraction(30)) -> Fraction:
    """Snap a measured rate to the nearest standard rate (within 2 %), else keep it
    (limited to 1..120 fps)."""
    if not fps or fps <= 0 or math.isnan(fps):
        return default
    best = min(STANDARD_FPS, key=lambda r: abs(float(r) - fps))
    if abs(float(best) - fps) / fps < 0.02:
        return best
    fps = max(1.0, min(120.0, fps))
    return Fraction(fps).limit_denominator(1001)


def parse_fps(value: Union[str, float, int, Fraction, None]) -> Optional[Fraction]:
    if value in (None, "", "auto"):
        return None
    if isinstance(value, Fraction):
        return value
    s = str(value).strip()
    aliases = {"23.976": Fraction(24000, 1001), "29.97": Fraction(30000, 1001), "59.94": Fraction(60000, 1001)}
    if s in aliases:
        return aliases[s]
    try:
        f = Fraction(s).limit_denominator(1001)
    except (ValueError, ZeroDivisionError):
        raise ShowtimeError("invalid fps %r (use e.g. 30, 29.97, 30000/1001)" % value)
    if f <= 0 or f > 240:
        raise ShowtimeError("fps out of range: %s" % value)
    return f


def fps_str(f: Fraction) -> str:
    return str(f.numerator) if f.denominator == 1 else "%d/%d" % (f.numerator, f.denominator)


# --------------------------------------------------------------------------
# Audio
# --------------------------------------------------------------------------

def extract_wav(src: PathLike, dst: PathLike, sr: int = 16000, track: int = 0, mono: bool = True,
                start: Optional[float] = None, duration: Optional[float] = None) -> Path:
    """Decode one audio track to PCM WAV (16-bit)."""
    dst = Path(dst)
    ensure_dir(dst.parent)
    tmp = part_path(dst)
    args: List[str] = []
    if start:
        args += ["-ss", "%.6f" % start]
    if duration:
        args += ["-t", "%.6f" % duration]
    args += ["-i", str(src), "-map", "0:a:%d" % track, "-vn", "-sn", "-dn"]
    if mono:
        args += ["-ac", "1"]
    args += ["-ar", str(sr), "-c:a", "pcm_s16le", "-f", "wav", str(tmp)]
    ff.run_ffmpeg(args)
    os.replace(str(tmp), str(dst))
    return dst


def load_audio(path: PathLike, sr: Optional[int] = None, mono: bool = True):
    """(float32 array, sample_rate). Resamples through ffmpeg when needed."""
    import numpy as np
    import soundfile as sf
    p = Path(path)
    try:
        x, rate = sf.read(str(p), dtype="float32", always_2d=True)
    except Exception:  # noqa: BLE001 - not a WAV soundfile can read: decode via ffmpeg
        tmp = cache_dir("footage") / ("dec-%s.wav" % quick_hash(p))
        if not tmp.is_file():
            extract_wav(p, tmp, sr=sr or 48000, mono=mono)
        x, rate = sf.read(str(tmp), dtype="float32", always_2d=True)
    if mono:
        x = x.mean(axis=1)
    if sr and rate != sr:
        from scipy.signal import resample_poly
        g = math.gcd(int(sr), int(rate))
        x = resample_poly(x, sr // g, rate // g, axis=0).astype(np.float32)
        rate = sr
    return x, int(rate)


def frame_db(x, sr: int, hop: float = 0.01):
    """RMS level in dBFS per `hop`-second frame."""
    import numpy as np
    n = max(1, int(round(sr * hop)))
    m = len(x) // n
    if m == 0:
        return np.full(1, -120.0, dtype=np.float32)
    fr = x[: m * n].reshape(m, n)
    rms = np.sqrt(np.mean(fr.astype(np.float64) ** 2, axis=1))
    return (20 * np.log10(rms + 1e-9)).astype(np.float32)


def voice_threshold(db) -> Tuple[float, float, float]:
    """(threshold_db, noise_floor_db, peak_db) for 'voiced' frames.

    Relative to both the loudest frame and the noise floor, so it works on
    clean synthetic speech (digital silence) and on noisy real recordings.
    """
    import numpy as np
    peak = float(np.max(db)) if len(db) else -120.0
    floor = float(np.percentile(db, 10)) if len(db) else -120.0
    thr = max(floor + 12.0, peak - 40.0, -65.0)
    return thr, floor, peak


def audio_levels(x, sr: int) -> Dict[str, float]:
    import numpy as np
    if len(x) == 0:
        return {"peak_db": -120.0, "mean_db": -120.0, "active_ratio": 0.0}
    peak = float(np.max(np.abs(x)))
    db = frame_db(x, sr, 0.05)
    thr, floor, pk = voice_threshold(db)
    return {"peak_db": round(20 * math.log10(peak + 1e-9), 1),
            "mean_db": round(10 * math.log10(float(np.mean(x.astype(np.float64) ** 2)) + 1e-12), 1),
            "floor_db": round(floor, 1), "active_ratio": round(float(np.mean(db > thr)), 3)}


# --------------------------------------------------------------------------
# Words / transcripts
# --------------------------------------------------------------------------

FILLERS = {
    "en": {"um", "umm", "ummm", "uh", "uhh", "uhm", "uhmm", "erm", "er", "err", "ah", "ahh", "hmm", "hm", "hmmm",
           "mm", "mmm", "mhm", "eh"},
    "es": {"eh", "ehh", "em", "emm", "este", "mmm", "mm", "ah", "eeh", "ehm"},
    "fr": {"euh", "euhh", "heu", "bah", "hum", "mmm", "ben"},
    "de": {"äh", "ähm", "öhm", "hm", "hmm", "mhm", "ähh"},
    "pt": {"é", "hã", "hum", "ahn", "eh", "éh", "tipo"},
    "it": {"ehm", "eh", "mmm", "uhm", "cioè"},
}
_FILLER_RE = re.compile(r"(?i)^(u+m+|u+h+m*|e+r+m*|a+h+|h+m+|m+h*m+|e+h+m*)$")


def bare(text: str) -> str:
    """Lower-case token with surrounding punctuation removed ("Um," -> "um")."""
    return re.sub(r"^[\W_]+|[\W_]+$", "", str(text).strip().lower())


def is_filler(text: str, lang: Optional[str] = None, extra: Iterable[str] = ()) -> bool:
    b = bare(text)
    if not b:
        return False
    if b in extra:
        return True
    lang = (lang or "en").split("-")[0].lower()
    if b in FILLERS.get(lang, set()) or (lang != "en" and b in FILLERS["en"] and b not in ("er",)):
        return True
    return bool(_FILLER_RE.match(b))


def words_of(transcript: Dict[str, Any], include_events: bool = False) -> List[Dict[str, Any]]:
    kinds = ("word", "audio_event") if include_events else ("word",)
    return [w for w in transcript.get("words", []) if w.get("type", "word") in kinds]


def load_transcript(path: PathLike) -> Dict[str, Any]:
    """Read a transcript in our format, or import a foreign one (a bare word
    list, OpenAI/whisper verbose JSON, JSON with speaker_id/logprob fields, SRT or VTT)."""
    p = Path(path)
    if not p.is_file():
        raise ShowtimeError("transcript not found: %s" % p, hint="run `showtime transcribe <media>` first")
    if p.suffix.lower() in (".srt", ".vtt"):
        return import_subtitles(p)
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        raise ShowtimeError("transcript is empty: %s" % p)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ShowtimeError("transcript is not valid JSON: %s (%s)" % (p, e))
    tr = normalize_transcript(data, str(p))
    # sidecars written by showtime store the media path relative to the transcript's folder
    src = tr.get("source")
    if isinstance(src, str) and src and not src.startswith(("http://", "https://")):
        from ..common import resolve_portable
        rp = resolve_portable(src, p.parent)
        if rp is not None:
            tr["source"] = str(rp)
    return tr


def normalize_transcript(data: Any, origin: str = "") -> Dict[str, Any]:
    if isinstance(data, list):
        data = {"words": data}
    if not isinstance(data, dict):
        raise ShowtimeError("unrecognised transcript format%s" % (" in " + origin if origin else ""))
    raw = data.get("words")
    if raw is None and isinstance(data.get("segments"), list):   # whisper verbose json
        raw = [w for s in data["segments"] for w in (s.get("words") or [])]
    if raw is None and isinstance(data.get("transcription"), list):  # whisper.cpp full json
        raw = []
        for s in data["transcription"]:
            off = s.get("offsets") or {}
            raw.append({"text": s.get("text", ""), "start": off.get("from", 0) / 1000.0,
                        "end": off.get("to", 0) / 1000.0})
    if not isinstance(raw, list):
        raise ShowtimeError("transcript has no 'words' list%s" % (" (" + origin + ")" if origin else ""))
    words: List[Dict[str, Any]] = []
    for i, w in enumerate(raw):
        if isinstance(w, (list, tuple)) and len(w) >= 3:
            w = {"text": w[0], "start": w[1], "end": w[2]}
        if not isinstance(w, dict):
            continue
        t = w.get("text", w.get("word", ""))
        try:
            s, e = float(w["start"]), float(w["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (math.isfinite(s) and math.isfinite(e)) or e > 360000:
            raise ShowtimeError("transcript times look wrong (not seconds?)%s" % (" in " + origin if origin else ""))
        typ = w.get("type") or "word"
        item: Dict[str, Any] = {"text": str(t) if typ == "spacing" else str(t).strip(), "start": round(s, 3),
                                "end": round(max(s, e), 3), "type": typ}
        spk = w.get("speaker", w.get("speaker_id"))
        if spk is not None:
            m = re.search(r"(\d+)$", str(spk))
            item["speaker"] = "S%s" % m.group(1) if m else str(spk)
        if "conf" in w:
            item["conf"] = w["conf"]
        elif "probability" in w:
            item["conf"] = round(float(w["probability"]), 3)
        elif "logprob" in w:
            try:
                item["conf"] = round(math.exp(float(w["logprob"])), 3)
            except (TypeError, ValueError, OverflowError):
                pass
        if w.get("id"):
            item["id"] = str(w["id"])
        for k in ("estimated", "filler", "line", "br"):
            if w.get(k):
                item[k] = w[k]
        if w.get("cue") is not None:   # imported SRT/VTT: the cue each word came from
            item["cue"] = w["cue"]
        if typ == "word" and not item["text"]:
            continue
        words.append(item)
    words.sort(key=lambda x: (x["start"], x["type"] == "spacing"))
    ensure_ids(words)
    out = {k: v for k, v in data.items() if k not in ("words", "segments", "transcription")}
    out["words"] = words
    if "language" not in out and data.get("language_code"):
        out["language"] = data["language_code"]
    if "duration" not in out:
        ends = [w["end"] for w in words]
        out["duration"] = max(ends) if ends else 0.0
    return out


def ensure_ids(words: List[Dict[str, Any]]) -> None:
    """Give every word/event a stable id (w0, w1, ...) unless it has one."""
    have = {w.get("id") for w in words if w.get("id")}
    if have and all(w.get("id") for w in words if w.get("type") != "spacing"):
        return
    n = 0
    for w in words:
        if w.get("type") == "spacing":
            w.pop("id", None)
            continue
        w["id"] = "w%d" % n
        n += 1


def add_spacing(words: List[Dict[str, Any]], min_gap: float = 0.02) -> List[Dict[str, Any]]:
    """Rebuild 'spacing' tokens between consecutive words/events."""
    toks = [w for w in words if w.get("type") != "spacing"]
    toks.sort(key=lambda w: w["start"])
    out: List[Dict[str, Any]] = []
    for w in toks:
        if out:
            prev_end = max(x["end"] for x in out[-3:] if x.get("type") != "spacing")
            if w["start"] - prev_end >= min_gap:
                out.append({"text": " ", "start": round(prev_end, 3), "end": round(w["start"], 3), "type": "spacing"})
        out.append(w)
    return out


def import_subtitles(path: PathLike) -> Dict[str, Any]:
    """SRT/VTT -> transcript with words spread evenly inside each cue
    (marked estimated: phrase-level timing only)."""
    p = Path(path)
    txt = p.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    cues = []
    for block in re.split(r"\n\s*\n", txt):
        m = re.search(r"((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})", block)
        if not m:
            continue
        body = block[m.end():].strip()
        body = re.sub(r"<[^>]+>|\{[^}]*\}", "", body)
        # keep the cue's own line breaks: the word ending each line but the last gets "br"
        brk = set()
        n = 0
        rows = [r.split() for r in body.split("\n") if r.split()]
        for r in rows[:-1]:
            n += len(r)
            brk.add(n - 1)
        cues.append((_ts(m.group(1)), _ts(m.group(2)), " ".join(body.split()), brk))
    words = []
    for ci, (s, e, text, brk) in enumerate(cues):
        toks = text.split()
        if not toks:
            continue
        weights = [max(1, len(t)) for t in toks]
        total = float(sum(weights))
        t = s
        for ti, (tok, wgt) in enumerate(zip(toks, weights)):
            d = (e - s) * wgt / total
            w = {"text": tok, "start": round(t, 3), "end": round(t + d, 3), "type": "word", "estimated": True, "cue": ci}
            if ti in brk:
                w["br"] = True
            words.append(w)
            t += d
    tr = normalize_transcript({"words": words}, str(p))
    tr["model"] = "imported:" + p.suffix.lower().lstrip(".")
    tr["timing"] = "estimated"
    return tr


def _ts(s: str) -> float:
    parts = s.replace(",", ".").split(":")
    v = 0.0
    for part in parts:
        v = v * 60 + float(part)
    return v


def fmt_time(t: float) -> str:
    t = max(0.0, t)
    m, s = divmod(t, 60)
    h, m = divmod(int(m), 60)
    return ("%d:%02d:%05.2f" % (h, m, s)) if h else ("%d:%05.2f" % (m, s))


def parse_ranges(spec: Union[str, Sequence], what: str = "range") -> List[Tuple[float, float]]:
    """'1.5-3.2,10-12' or [[1.5,3.2],...] -> [(1.5, 3.2), ...]."""
    from ..common import parse_time
    out = []
    items = spec.split(",") if isinstance(spec, str) else list(spec)
    for it in items:
        if isinstance(it, str):
            it = it.strip()
            if not it:
                continue
            m = re.match(r"^(.+?)\s*(?:-|\.\.|to)\s*(.+)$", it)
            if not m:
                raise ShowtimeError("invalid %s %r (use start-end, e.g. 3.2-4.5)" % (what, it))
            a, b = parse_time(m.group(1)), parse_time(m.group(2))
        else:
            a, b = float(it[0]), float(it[1])
        if b <= a:
            raise ShowtimeError("invalid %s %r: end must be after start" % (what, it))
        out.append((a, b))
    return out

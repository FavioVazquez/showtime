"""The hearing pass: what an ear catches in a finished video, as numbers a critic who cannot listen can judge.

Owners hear what loudness and true peak miss: music drowning the voice, a line rushed or cut off, a long
silence, an effect that fires late or too loud, a jump in level at a cut, music that stops dead at the end.
This module measures those on the delivered audio. `showtime qa` runs it on every video with sound (the
cheap checks below become WARNs with times); `showtime review-pack` writes the numbers into the pack as
`audio.txt` and `hearing.png` for the critic's hearing pass (CRITIC.md).

What is measured
  blocks     loudness of every 100 ms block (K-weighted like LUFS, without the momentary meter's 400 ms
             window) of the programme; with the render's narration stem (render keeps the voice before the
             music as work/audio/mix.voice.wav; an edit render its speech stem) also of the voice and of the
             bed (everything else). The stem is lined up with the file's own audio (a lag search of +-50 ms)
             and scaled to it (least squares), so the split survives the render's master and the AAC encode.
  lines      the narration line by line (voice/timeline.json when it belongs to this render, else the caption
             cues): words per minute, and the voice over the bed during its words. Without a stem the bed is
             estimated from the quietest tenth of the line's 20 ms frames (the gaps between words and the
             stops): an upper bound, as some speech leaks in, so the line is marked "estimate" and qa never
             warns on it.
  scenes     loudness per scene, the speech share, the bed level (with a stem)
  cuts       the level on both sides of every cut, compared like with like: bed with bed (stem), else
             programme with programme when both sides are speech or both are not; a cut where speech starts
             or stops is not a jump. A music section change, gain automation or an effect at the cut is noted.
  quiet      stretches of near silence mid-video (blocks quieter than the programme's integrated loudness
             minus quiet_under_lu), and pauses in the voice
  effects    every sfx of the render's mix report: its hit time, how far over the rest of the mix it is
             (the mix's above_bed_db), how far it rises over the programme, the nearest cut and CUE value
  ending     the level of the last 0.2 s against the 3 s before (music or a word cut off on the last frame),
             where each music track ends
  peaks      true peak, sample peak and clipped runs (from qa's loudness measurement)
  speaker    the integrated loudness above 300 Hz and above 1 kHz (st.audio.meter.speaker_loudness): what a phone
             or laptop speaker, which plays little under ~300 Hz, makes of the mix; the gap to the full mix

Thresholds live in runtime/thresholds.json "hearing" (the literals in DEFAULTS are the fallback).
numpy and scipy (already used by the meter); no other dependency.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HOP = 0.1                         # seconds per block
FINE = 0.02                       # seconds per frame of the fine programme curve (the bed between words, no stem)
FLOOR = -120.0                    # block level of digital silence
SILENT = -55.0                    # a side of a cut, a bed under a line: below this it is silence, not a level
DEFAULTS: Dict[str, float] = {
    "voice_over_bed_min_db": 8.0,  # voice_masked: a line whose words sit less than this over the bed (stem)
    "quiet_stretch_s": 2.0,        # quiet_stretch / voice pauses: longer than this, mid-video
    "quiet_under_lu": 20.0,        # quiet: blocks this far under the integrated loudness
    "level_jump_lu": 6.0,          # level_jump: a change this big at a cut, like compared with like
    "abrupt_end_db": 10.0,         # abrupt_end: the last 0.2 s within this of the 3 s before (and audible)
    "fast_wpm": 200.0,             # lines faster than this are listed as fast (critic only)
    "slow_wpm": 100.0,             # lines slower than this are listed as slow (critic only)
    "sfx_loud_lu": 10.0,           # an effect peaking this far over the integrated loudness is listed as loud
    "speaker_gap_lu": 10.0,        # speaker_loudness WARN: the mix above 300 Hz this far under the full mix
    "speaker_gap_fail_lu": 18.0,   # speaker_loudness FAIL: as good as silent on a phone speaker
}


def thresholds() -> Dict[str, float]:
    """The hearing thresholds (runtime/thresholds.json "hearing", over DEFAULTS)."""
    from .video import THRESHOLDS_FILE
    out = dict(DEFAULTS)
    try:
        doc = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8")).get("hearing") or {}
        for k in out:
            if isinstance(doc.get(k), (int, float)) and not isinstance(doc.get(k), bool) and doc[k] > 0:
                out[k] = float(doc[k])
    except (OSError, ValueError, AttributeError):
        pass
    return out


# ------------------------------------------------------------------ the render's own files

def own_mix_report(video: Path) -> Optional[Path]:
    """mix.report.json of the mix this render played (render keeps it in its work folder), else None."""
    from . import review
    cands = [video.with_suffix(".work") / "audio" / "mix.report.json"]
    rj = review.render_report(video)
    if isinstance(rj, dict) and rj.get("log") and (not rj.get("output") or Path(str(rj["output"])).name == video.name):
        cands.append(Path(str(rj["log"])).parent.parent / "audio" / "mix.report.json")
    for c in cands:
        try:
            if c.is_file() and c.stat().st_size < 4_000_000:
                return c
        except OSError:
            continue
    return None


def voice_stem(video: Path) -> Optional[Tuple[Path, float, str]]:
    """(narration stem, its offset in s, what it is) when showtime rendered this file with music under speech:
    the mix's narration stem (or an edit's speech stem), else a mix of only voice tracks played over an
    ST.score bed (render mixes the two itself, so the voice mix is the stem)."""
    try:
        from ..footage.transcribe import dry_stem
        st = dry_stem(video.resolve())
    except Exception:  # noqa: BLE001 - the stem is a better measurement, never a requirement
        st = None
    if st:
        return st
    from ..common import read_json
    from . import review
    mp = own_mix_report(video)
    if mp is None or not (mp.parent / "score.wav").is_file() or not (mp.parent / "mix.wav").is_file():
        return None
    rep = read_json(mp, {}) or {}
    kinds = {t.get("kind") for t in rep.get("tracks") or [] if isinstance(t, dict)}
    if kinds == {"voice"}:
        return mp.parent / "mix.wav", review._offset(video), "the voice mix before the ST.score bed was added"
    return None


# ------------------------------------------------------------------ blocks

def _block_power(x: Any, sr: int, hop: float = HOP) -> Any:
    """Mean-square K-weighted power per block (100 ms). A mono signal counts twice (as dual-mono stereo), so
    voice and bed blocks read on the same scale as the stereo programme."""
    import numpy as np
    from ..audio import meter
    z = meter.k_weight(np.asarray(x, dtype=np.float64), sr)
    sq = (z ** 2).sum(axis=1) if z.ndim == 2 else 2.0 * z ** 2
    h = int(round(hop * sr))
    k = len(sq) // h
    if k == 0:
        return np.zeros(0)
    return sq[: k * h].reshape(k, h).mean(axis=1)


def _lufs(p: float) -> float:
    return max(FLOOR, -0.691 + 10 * math.log10(p)) if p > 0 else FLOOR


def _levels(p: Any) -> List[float]:
    return [round(_lufs(float(v)), 2) for v in p]


def split_voice(x: Any, sr: int, stem: Path, offset: float = 0.0) -> Optional[Dict[str, Any]]:
    """The voice and the bed of the delivered audio x, from the narration stem: {voice, bed (16 kHz mono
    arrays), gain_db, lag_ms, corr}. None when the stem does not line up with x (another mix, a re-voice):
    a correlation under 0.2 over the voiced samples (the voice would be ~14 dB under everything else)."""
    import numpy as np
    from scipy import signal
    from ..audio import wav
    y = np.asarray(x, dtype=np.float64)
    y = y.mean(axis=1) if y.ndim == 2 else y
    if sr != 16000:
        g_ = math.gcd(16000, sr)
        y = signal.resample_poly(y, 16000 // g_, sr // g_)
    v = np.asarray(wav.load(stem, sr=16000, mono=True), dtype=np.float64)
    i0 = int(round(offset * 16000))
    v = v[i0:] if i0 >= 0 else np.concatenate([np.zeros(-i0), v])
    v = np.concatenate([v[: len(y)], np.zeros(max(0, len(y) - len(v)))])
    if not len(y) or not np.any(v):
        return None
    # line up: the 30 s with the most voice, cross-correlated over +-50 ms
    sec = 16000
    e = np.add.reduceat(v ** 2, np.arange(0, len(v), sec)) if len(v) >= sec else np.array([float((v ** 2).sum())])
    w = min(30, len(e))
    run = np.convolve(e, np.ones(w), "valid")
    s0 = int(np.argmax(run)) * sec
    a, b = y[s0:s0 + w * sec], v[s0:s0 + w * sec]
    L = 800
    n = 1 << int(math.ceil(math.log2(max(2, len(a) + len(b)))))
    c = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
    cand = np.concatenate([c[n - L:], c[: L + 1]])
    lag = int(np.argmax(cand)) - L                       # y[i + lag] ~ v[i]
    vs = np.zeros_like(v)
    if lag >= 0:
        vs[lag:] = v[: len(v) - lag]
    else:
        vs[:lag] = v[-lag:]
    act = np.abs(vs) > np.abs(vs).max() * 10 ** (-45 / 20)
    vv, yv = float((vs[act] ** 2).sum()), float((y[act] ** 2).sum())
    if vv <= 0 or yv <= 0:
        return None
    dot = float((y[act] * vs[act]).sum())
    corr = dot / math.sqrt(vv * yv)
    if corr < 0.2:
        return None
    g = dot / vv
    voice = g * vs
    return {"voice": voice, "bed": y - voice, "gain_db": round(20 * math.log10(g), 2), "lag_ms": round(lag / 16.0, 2),
            "corr": round(corr, 3)}


def blocks(x: Any, sr: int, video: Optional[Path] = None) -> Dict[str, Any]:
    """{hop, programme, voice?, bed?, voice_source?, fit?, fine?}: block levels (LUFS-like) of the delivered
    audio, split into voice and bed when the render's narration stem lines up with it; without a split also the
    programme every 20 ms (fine), where the bed shows between the words."""
    import numpy as np
    zx = np.asarray(x, dtype=np.float64)
    out: Dict[str, Any] = {"hop": HOP, "programme": _levels(_block_power(zx, sr))}
    st = voice_stem(video) if video is not None else None
    if st:
        try:
            sp = split_voice(x, sr, st[0], st[1])
        except Exception as e:  # noqa: BLE001 - fall back to the estimate
            sp = None
            out["voice_note"] = "the narration stem could not be read (%s)" % str(e).splitlines()[0][:100]
        if sp is None:
            out.setdefault("voice_note", "the narration stem did not line up with this file's audio (another mix?)")
        else:
            n = len(out["programme"])
            out["voice"] = _levels(_block_power(sp["voice"], 16000))[:n]
            out["bed"] = _levels(_block_power(sp["bed"], 16000))[:n]
            out["voice_source"] = st[2]
            out["fit"] = {k: sp[k] for k in ("gain_db", "lag_ms", "corr")}
    if "voice" not in out:
        out["fine_hop"] = FINE
        out["fine"] = [round(v, 1) for v in _levels(_block_power(zx, sr, FINE))]
    return out


# ------------------------------------------------------------------ lines, cues, mix report

def line_offsets(proj: Path, tl: Dict[str, Any]) -> Dict[str, float]:
    """{line id: seconds to add to its voice/timeline.json times} for where the project's mix plays it: a
    `vo-<id>` track (retime --from-voice) or a track playing the line's own file (voice/lines/NN-id.wav) at its
    `start`, else the start of the track playing the whole vo.wav, else 0. Project time, like the clips. The
    rule is st.questions.line_offsets, which the stop-and-ask questions resolve their cues with."""
    from ..common import read_json
    from .. import questions
    cfg = read_json(proj / "showtime.json", {}) if (proj / "showtime.json").is_file() else {}
    own = questions.project_mix(proj, cfg if isinstance(cfg, dict) else {})
    tracks, base = (own[0], own[1]) if own else ([], proj)

    def where(f: Any) -> Path:
        for b in (base, proj):
            if (Path(b) / str(f)).exists():
                return (Path(b) / str(f)).resolve()
        return (proj / str(f)).resolve()
    return questions.line_offsets(tl, (proj / "voice").resolve(), [t for t in tracks if isinstance(t, dict)], where)


def speech_lines(video: Path, proj: Optional[Path]) -> Tuple[List[Dict[str, Any]], str]:
    """The narration of this render line by line, in video time: [{id, start, end, text, words, spans}]
    (spans: the word times, or the line itself) and where it came from."""
    from ..common import read_json
    from . import review
    off = review._offset(video)
    tl = proj / "voice" / "timeline.json" if proj is not None else None
    try:
        fresh = tl is not None and tl.is_file() and tl.stat().st_mtime <= video.stat().st_mtime + 1
    except OSError:
        fresh = False
    if fresh:
        data = read_json(tl, {}) or {}
        moved = line_offsets(proj, data) if isinstance(data, dict) else {}
        out: List[Dict[str, Any]] = []
        for ln in (data.get("lines") if isinstance(data, dict) else None) or []:
            if not (isinstance(ln, dict) and ln.get("text") and ln.get("start") is not None):
                continue
            o = off - moved.get(str(ln.get("id")), 0.0)
            try:
                a = float(ln.get("speech_start", ln["start"])) - o
                b = float(ln.get("speech_end", ln.get("end", a))) - o
                words = [(float(w["start"]) - o, float(w["end"]) - o) for w in ln.get("words") or []
                         if isinstance(w, dict) and w.get("start") is not None and w.get("end") is not None]
            except (TypeError, ValueError, KeyError):
                continue
            text = " ".join(str(ln["text"]).split())
            out.append({"id": str(ln.get("id") or "line %d" % (len(out) + 1)), "start": round(a, 3), "end": round(b, 3),
                        "text": text, "words": len(words) or len(text.split()), "spans": words or [(a, b)]})
        if out:
            return sorted(out, key=lambda r: r["start"]), "the voice timeline"
    cues, source = review.narration(video, proj)
    out = []
    for i, (a, b, t) in enumerate(cues):
        text = " ".join(str(t).split())
        if text:
            out.append({"id": "cue %d" % (i + 1), "start": round(a, 3), "end": round(b, 3), "text": text,
                        "words": len(text.split()), "spans": [(a, b)]})
    return sorted(out, key=lambda r: r["start"]), source


def cue_values(proj: Optional[Path]) -> Dict[str, float]:
    """The film's named CUE times (cues.js / index.html `CUE = {name: seconds, ...}`), project time."""
    if proj is None:
        return {}
    from .review import CUE_PAIR
    for f in (proj / "cues.js", proj / "index.html", proj / "scenes.js"):
        if not f.is_file():
            continue
        m = re.search(r"\bCUE\s*=\s*\{(.*?)\n?\};", f.read_text(encoding="utf-8", errors="replace"), re.S)
        if m:
            out: Dict[str, float] = {}
            for k, v in CUE_PAIR.findall(m.group(1)):
                out.setdefault(k, float(v))
            return out
    return {}


def _family(name: str) -> str:
    return re.sub(r"[\s_\-.]*\d+$", "", name.lower()) or name.lower()


def mix_facts(report: Optional[Dict[str, Any]], offset: float, dur: float) -> Dict[str, Any]:
    """Effects, music tracks, section changes and gain automation of a mix report, in video time."""
    out: Dict[str, Any] = {"sfx": [], "music": [], "sections": [], "gain_points": [], "voice_to_music_db": None,
                           "speaker_safe": None}
    if not isinstance(report, dict):
        return out
    out["voice_to_music_db"] = report.get("voice_to_music_db")
    if isinstance(report.get("speaker"), dict):
        sp = report["speaker"]
        out["speaker_safe"] = {k: sp.get(k) for k in ("on", "set_by", "shelf_db", "shelf_hz", "capped", "shelved",
                                                       "gap_300_lu_before", "sub_alone") if sp.get(k) is not None}
    for r in report.get("tracks") or []:
        if not isinstance(r, dict):
            continue
        kind = r.get("kind")
        synth = r.get("synth") if isinstance(r.get("synth"), dict) else None
        name = (synth or {}).get("type") or r.get("library_id") or r.get("catalog_id") or \
            (Path(str(r.get("path"))).stem if r.get("path") else "") or str(r.get("id") or kind)
        if kind == "sfx":
            at = (r.get("aligned") or {}).get("at", r.get("start"))
            if at is None:
                continue
            t = float(at) - offset
            if -0.05 <= t <= dur + 0.05:
                out["sfx"].append({"id": str(r.get("id")), "name": str(name), "t": round(t, 3), "family": _family(str(r.get("id") or name)),
                                   "above_bed_db": r.get("above_bed_db"), "texture": bool(r.get("texture")),
                                   "speaker_gap_lu": r.get("speaker_gap_lu"), "speaker_alone": bool(r.get("speaker_alone"))})
        elif kind in ("music", "ambience"):
            st, en = r.get("start"), r.get("end")
            row = {"id": str(r.get("id")), "kind": kind, "name": str(name),
                   "start": round(float(st) - offset, 3) if st is not None else None,
                   "end": round(float(en) - offset, 3) if en is not None else None,
                   "end_hit": round(float(r["end_hit"]) - offset, 3) if r.get("end_hit") is not None else None,
                   "ducks": bool(r.get("duck")), "duck_db": (r.get("duck") or {}).get("depth_db") if isinstance(r.get("duck"), dict) else None,
                   "fit": bool(r.get("fit"))}
            out["music"].append(row)
            for s in r.get("music_sections") or []:
                try:
                    out["sections"].append((round(float(s["start"]) - offset, 3), str(s.get("name") or "")))
                except (TypeError, ValueError, KeyError):
                    continue
            for p in r.get("gain_points") or []:
                try:
                    out["gain_points"].append(round(float(p[0]) - offset, 3))
                except (TypeError, ValueError, IndexError):
                    continue
    out["sfx"].sort(key=lambda s: s["t"])
    return out


# ------------------------------------------------------------------ measuring

class _Curve:
    """Block levels with window means in power."""

    def __init__(self, levels: Optional[Sequence[float]], hop: float = HOP) -> None:
        import numpy as np
        self.hop = hop
        self.ok = bool(levels)
        lv = np.asarray(levels or [], dtype=np.float64)
        self.db = lv
        self.p = np.where(lv <= FLOOR + 0.01, 0.0, 10 ** ((lv + 0.691) / 10))

    def idx(self, a: float, b: float) -> Any:
        """Blocks whose centre lies in [a, b)."""
        import numpy as np
        c = (np.arange(len(self.p)) + 0.5) * self.hop
        return (c >= a) & (c < b)

    def mean(self, sel: Any) -> Optional[float]:
        if sel is None or not sel.any():
            return None
        return _lufs(float(self.p[sel].mean()))


def _mask(spans: Sequence[Tuple[float, float]], n: int, pad: float = 0.0, hop: float = HOP) -> Any:
    import numpy as np
    m = np.zeros(n, dtype=bool)
    c = (np.arange(n) + 0.5) * hop
    for a, b in spans:
        m |= (c >= a - pad) & (c < b + pad)
    return m


def _r(v: Optional[float], nd: int = 1) -> Optional[float]:
    return None if v is None else round(float(v), nd)


def measure(blk: Dict[str, Any], dur: float, *, lines: Sequence[Dict[str, Any]] = (), lines_source: str = "",
            cuts: Sequence[float] = (), scenes: Sequence[Tuple[float, float, str]] = (),
            mix: Optional[Dict[str, Any]] = None, cues: Optional[Dict[str, float]] = None,
            loud: Optional[Dict[str, Any]] = None, th: Optional[Dict[str, float]] = None,
            speaker: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Everything the hearing pass reports, from block levels (`blocks`) and the video's timings. Pure: qa
    and review-pack call it with their own cut lists. mix = mix_facts(...); cues in video time; speaker =
    st.audio.meter.speaker_loudness of the delivered audio (qa measures it on the decoded samples)."""
    import numpy as np
    th = th or thresholds()
    loud = loud or {}
    mix = mix or mix_facts(None, 0.0, dur)
    prog = _Curve(blk.get("programme"))
    stem = bool(blk.get("voice") and blk.get("bed"))
    voice, bed = (_Curve(blk.get("voice")), _Curve(blk.get("bed"))) if stem else (None, None)
    fine = _Curve(None if stem else blk.get("fine"), float(blk.get("fine_hop") or FINE))
    n = len(prog.p)
    I = loud.get("integrated_lufs")
    out: Dict[str, Any] = {
        "thresholds": th, "duration": round(dur, 3), "lines_source": lines_source or None,
        "voice_source": blk.get("voice_source") if stem else None, "voice_note": blk.get("voice_note"),
        "fit": blk.get("fit") if stem else None,
        "integrated_lufs": I, "true_peak_dbtp": loud.get("true_peak_dbtp"), "lra": loud.get("lra"),
        "sample_peak_dbfs": loud.get("sample_peak_dbfs"), "target_lufs": loud.get("target_lufs"),
        "ceiling_dbtp": loud.get("ceiling_dbtp"), "clipping": loud.get("clipping"),
        "voice_to_music_db": mix.get("voice_to_music_db"),
        "speaker": dict(speaker, mix=mix.get("speaker_safe")) if speaker and speaker.get("gap_300_lu") is not None else None,
    }
    lines = sorted(lines, key=lambda r: r["start"])
    line_spans = [(float(ln["start"]), float(ln["end"])) for ln in lines]
    speech = _mask(line_spans, n)
    near_speech = _mask(line_spans, n, pad=0.25)
    worded = _mask([sp for ln in lines for sp in (ln.get("spans") or [(ln["start"], ln["end"])])], n, pad=0.03)

    # ---- lines
    rows: List[Dict[str, Any]] = []
    for i, ln in enumerate(lines):
        a, b = float(ln["start"]), float(ln["end"])
        span = b - a
        wpm = ln["words"] / span * 60.0 if span >= 0.5 and ln["words"] else None
        words = _mask(ln.get("spans") or [(a, b)], n, pad=0.03) & prog.idx(a - 0.05, b + 0.05)
        ratio, method, note = None, None, ""
        if stem and words.any():
            lv, lb = voice.mean(words), bed.mean(words)
            method = "stem"
            if lb is None or lb < SILENT:
                note = "no music under it"
            elif lv is not None:
                ratio = lv - lb
        elif fine.ok:
            # the bed between the words: the quietest tenth of the 20 ms frames of the line (stops, gaps); an
            # upper bound of the bed (some speech leaks in), so the line reads a little worse than it is
            method = "estimate"
            fr = fine.idx(a, b)
            wf = _mask(ln.get("spans") or [(a, b)], len(fine.p), hop=FINE) & fr
            if int(fr.sum()) >= 20 and wf.any():
                quiet_frames = np.sort(fine.p[fr])[: max(2, int(fr.sum()) // 10)]
                ps, pb = float(fine.p[wf].mean()), float(quiet_frames.mean())
                if _lufs(pb) < SILENT:
                    note = "no music under it"
                else:
                    ratio = 10 * math.log10(max(ps - pb, ps * 1e-4) / pb)
            else:
                note = "too short to measure the bed"
        flags: List[str] = []
        if ratio is not None and ratio < th["voice_over_bed_min_db"]:
            flags.append("music louder than the words" if ratio < 0 else "masked")
        if wpm is not None and wpm > th["fast_wpm"] and span >= 1.5 and ln["words"] >= 5:
            flags.append("fast")
        elif wpm is not None and wpm < th["slow_wpm"] and ln["words"] >= 4:
            flags.append("slow")
        if i + 1 < len(lines) and b > float(lines[i + 1]["start"]) + 0.02:
            flags.append("overlaps the next line")
        if b >= dur - 0.05:
            flags.append("runs to the last frame")
        if a < -0.01:
            flags.append("starts before the video")
        clip = [t for t in ((loud.get("clipping") or {}).get("times") or []) if a - 0.05 <= t <= b + 0.05]
        if clip:
            flags.append("clipped at %s" % ", ".join("%.2fs" % t for t in clip[:3]))
        rows.append({"id": ln["id"], "start": round(a, 3), "end": round(b, 3), "text": ln["text"], "words": ln["words"],
                     "wpm": _r(wpm, 0), "voice_over_bed_db": _r(ratio), "method": method, "note": note, "flags": flags})
    out["lines"] = rows

    # ---- pauses in the voice (mid-video)
    gaps = []
    for (a0, b0), (a1, _) in zip(line_spans, line_spans[1:]):
        if a1 - b0 > th["quiet_stretch_s"]:
            gaps.append({"start": round(b0, 3), "end": round(a1, 3), "seconds": round(a1 - b0, 2),
                         "lufs": _r(prog.mean(prog.idx(b0, a1)))})
    out["voice_pauses"] = gaps

    # ---- quiet stretches (near silence mid-video)
    quiet: List[Dict[str, Any]] = []
    if I is not None and n:
        level = max(float(I) - th["quiet_under_lu"], -60.0)
        loudish = np.nonzero(prog.db >= max(level, -50.0))[0]
        if len(loudish):
            first, last = int(loudish[0]), int(loudish[-1])
            gaps_s = [tuple(g) for g in (loud.get("silent_gaps") or [])]
            k = first
            while k <= last:
                if prog.db[k] < level:
                    j = k
                    while j <= last and prog.db[j] < level:
                        j += 1
                    s, e = k * HOP, j * HOP
                    if e - s >= th["quiet_stretch_s"] - 1e-9:
                        silent = sum(max(0.0, min(e, g1) - max(s, g0)) for g0, g1 in gaps_s) >= 0.5 * (e - s)
                        quiet.append({"start": round(s, 2), "end": round(e, 2), "seconds": round(e - s, 2),
                                      "lufs": _r(prog.mean(prog.idx(s, e))), "under": round(level, 1), "silent": silent})
                    k = j
                else:
                    k += 1
    out["quiet"] = quiet

    # ---- scenes
    srows = []
    for a, b, name in scenes:
        sel = prog.idx(a, b)
        if not sel.any():
            continue
        loudsel = sel & (prog.db > -70)
        stv = None
        if int(sel.sum()) >= 30:
            seg = prog.p[sel]
            stv = _lufs(float(np.convolve(seg, np.ones(30) / 30, "valid").max()))
        row = {"name": name, "start": round(a, 3), "end": round(b, 3), "lufs": _r(prog.mean(loudsel)),
               "short_term_max": _r(stv), "speech_share": round(float(speech[sel].mean()), 2)}
        if stem:
            row["bed_lufs"] = _r(bed.mean(sel & ~near_speech) if (sel & ~near_speech).any() else bed.mean(sel))
            row["voice_lufs"] = _r(voice.mean(sel & speech)) if (sel & speech).any() else None
        srows.append(row)
    out["scenes"] = srows

    # ---- level at each cut
    jumps = []
    for c in sorted(set(round(float(c), 3) for c in cuts)):
        if c < 1.0 or c > dur - 1.0:
            continue
        before, after = prog.idx(c - 1.0, c - 0.1), prog.idx(c + 0.1, c + 1.0)
        if not before.any() or not after.any():
            continue
        sb, sa = float(speech[before].mean()), float(speech[after].mean())
        notes: List[str] = []
        kind, lb, la = None, None, None
        if stem:
            kind, lb, la = "bed", bed.mean(before & ~near_speech) or bed.mean(before), bed.mean(after & ~near_speech) or bed.mean(after)
            if sb > 0.6 and sa > 0.6:
                vb_, va_ = voice.mean(before & speech), voice.mean(after & speech)
                if vb_ is not None and va_ is not None and abs(va_ - vb_) > abs((la or 0) - (lb or 0)):
                    kind, lb, la = "voice", vb_, va_
        elif sb > 0.6 and sa > 0.6:
            # voice with voice: only the blocks with words in them (the music and effects show between them)
            kind, lb, la = "voice", prog.mean(before & worded), prog.mean(after & worded)
        elif sb < 0.2 and sa < 0.2:
            kind, lb, la = "programme", prog.mean(before), prog.mean(after)
        else:
            notes.append("speech %s at the cut" % ("starts" if sa > sb else "stops"))
        hits = [s for s in mix["sfx"] if c - 1.0 <= s["t"] <= c + 1.0]
        if hits:
            notes.append("effect%s %s at %s" % ("s" if len(hits) > 1 else "", ", ".join(h["id"] for h in hits[:3]),
                                                ", ".join("%.2fs" % h["t"] for h in hits[:3])))
        sec = [nm for t, nm in mix["sections"] if abs(t - c) <= 0.35]
        if sec:
            notes.append("the music changes section here (%s)" % sec[0])
        if any(abs(t - c) <= 1.0 for t in mix["gain_points"]):
            notes.append("gain automation on the bed here")
        row: Dict[str, Any] = {"t": c, "kind": kind, "before": _r(lb), "after": _r(la), "jump": None, "flagged": False,
                               "notes": notes}
        if kind and lb is not None and la is not None:
            if lb < SILENT and la < SILENT:
                continue
            if lb < SILENT or la < SILENT:
                row["notes"].append("silence on one side")
            else:
                row["jump"] = round(la - lb, 1)
                row["flagged"] = abs(la - lb) > th["level_jump_lu"] and not hits and not sec
        jumps.append(row)
    out["cuts"] = jumps

    # ---- effects
    cut_list = sorted(set([0.0] + [float(c) for c in cuts]))
    fx = []
    for s in mix["sfx"]:
        t = s["t"]
        rise = None
        pa, pb = prog.mean(prog.idx(t - 0.05, t + 0.3)), prog.mean(prog.idx(t - 0.5, t - 0.05))
        if pa is not None and pb is not None:
            rise = pa - pb
        peak_sel = prog.idx(t - 0.05, t + 0.4)
        peak = float(prog.db[peak_sel].max()) if peak_sel.any() else None
        over = (peak - float(I)) if (peak is not None and I is not None) else None
        nc = min(cut_list, key=lambda c: abs(c - t)) if cut_list else None
        cue = None
        if cues:
            nm, ct = min(cues.items(), key=lambda kv: abs(kv[1] - t))
            if abs(ct - t) <= 0.5:
                cue = {"name": nm, "t": round(ct, 3), "off": round(t - ct, 3)}
        flags = []
        if s["above_bed_db"] is not None and s["above_bed_db"] < 0 and not s["texture"]:
            flags.append("under the rest of the mix")
        if over is not None and over > th["sfx_loud_lu"]:
            flags.append("loud")
        if s.get("speaker_alone"):
            flags.append("sub only (%.0f LU under above 300 Hz): a phone hardly plays it" % float(s.get("speaker_gap_lu") or 0))
        if nc is not None and 0.08 < abs(t - nc) <= 0.5 and not (cue and abs(cue["off"]) <= 0.04):
            flags.append("%.2fs %s the cut at %.2fs" % (abs(t - nc), "after" if t > nc else "before", nc))
        fx.append(dict(s, rise_lu=_r(rise), over_programme_lu=_r(over),
                       nearest_cut=round(nc, 3) if nc is not None and abs(t - nc) <= 1.0 else None, cue=cue, flags=flags))
    out["sfx"] = fx

    # ---- the ending
    curve = bed if stem else prog
    end: Dict[str, Any] = {"music": mix["music"], "abrupt": False, "measured_on": "the bed" if stem else "the programme"}
    k = int(dur / HOP + 1e-6)
    if curve is not None and k >= 30 and k <= len(curve.p):
        tail = _lufs(float(curve.p[k - 2:k].mean()))
        body_sel = curve.idx(dur - 3.0, dur - 0.5) & (curve.db > -60)
        body = float(np.median(curve.db[body_sel])) if body_sel.any() else None
        end.update(tail_lufs=round(tail, 1), body_lufs=_r(body))
        end["abrupt"] = bool(body is not None and tail > -45.0 and tail >= body - th["abrupt_end_db"])
    ends = [m["end"] for m in mix["music"] if m.get("end") is not None]
    if ends:
        last = max(ends)
        end["music_end"] = round(last, 3)
        if last < dur - 1.0:
            end["music_stops_early_s"] = round(dur - last, 2)
    hits = [m["end_hit"] for m in mix["music"] if m.get("end_hit") is not None]
    if hits:
        end["end_hit"] = max(hits)
    out["ending"] = end
    return out


# ------------------------------------------------------------------ qa

RULES = {
    "voice_masked": "a voice line sits less than 8 dB over the music under it (measured with the narration stem)",
    "quiet_stretch": "near silence for 2 s or more mid-video (20 LU under the programme)",
    "level_jump": "the level jumps more than 6 LU at a cut (bed with bed, or voice with voice)",
    "abrupt_end": "the sound is still at full level on the last frame (music or a word cut off)",
    "speaker_loudness": "on a phone or laptop speaker (the mix above 300 Hz) the video is far quieter than its "
                        "loudness says: a mix of bass and sub (WARN over 10 LU under the full mix, FAIL over 18)",
    "readback": "a name, acronym or number of the voice-over is heard differently from the script (the narration "
                "transcribed again locally); FAIL for a name in the title, the brand or the project's lexicon",
}


def readback(video: Path, proj: Optional[Path]) -> Optional[Dict[str, Any]]:
    """The voice-over heard back (st.voice.readback) for the project's voice/vo.wav, suspect times moved onto
    the video's clock. None without a voice timeline that belongs to this render."""
    if proj is None:
        return None
    from ..common import read_json
    from ..voice import readback as rb
    from . import review
    if not rb.enabled():
        return None
    rep = rb.for_project(proj, video)
    if not rep or rep.get("skipped"):
        return rep
    tl = read_json(proj / "voice" / "timeline.json", {}) or {}
    off = review._offset(video)
    moved = line_offsets(proj, tl) if isinstance(tl, dict) else {}
    for s in rep.get("suspects") or []:
        if s.get("t") is not None:
            s["voice_t"] = s["t"]
            s["t"] = round(float(s["t"]) - off + moved.get(str(s.get("line")), 0.0), 3)
    for ln in rep.get("lines") or []:
        ln.pop("heard_words", None)          # voice/readback.json keeps them; qa.json needs the text only
        ln["video_start"] = round(float(ln.get("start") or 0.0) - off + moved.get(str(ln.get("id")), 0.0), 3)
    return rep


def check_readback(F: Any, rep: Optional[Dict[str, Any]]) -> None:
    """The read-back as qa items: a WARN per word heard differently (FAIL for a name in the title, brand or
    project lexicon), an INFO when it could not run."""
    if not rep:
        return
    from ..voice import readback as rb
    if rep.get("skipped"):
        F.add("readback", "INFO", "the voice-over was not heard back: %s" % rep["skipped"],
              fix="install the local recognizer to check names: %s" % rb.fetch_hint())
        return
    sus = rep.get("suspects") or []
    if not sus:
        F.ok(rep.get("summary") or rb.summary(rep))
        return
    for s in sus[:8]:
        F.add("readback", "FAIL" if s.get("critical") else "WARN",
              "voice line %s: the script says \"%s\", the voice is heard as \"%s\"%s" % (
                  s.get("line"), s["word"], s.get("heard") or "nothing",
                  " (a name in the title, brand or lexicon)" if s.get("critical") else ""),
              t=s.get("t"), fix=rb.fix_for(s, s.get("clip")), word=s["word"], heard=s.get("heard"))
    if len(sus) > 8:
        F.add("readback", "WARN", "%d more words heard differently (voice/readback.json, review-pack's audio.txt)"
              % (len(sus) - 8), t=sus[8].get("t"))


def speaker_line(sp: Optional[Dict[str, Any]]) -> Optional[str]:
    """"on a phone speaker: -27.6 LUFS, 13.6 LU under the mix" (None without the measurement)."""
    if not sp or sp.get("gap_300_lu") is None:
        return None
    return "on a phone speaker: %.1f LUFS, %.1f LU under the mix" % (sp["above_300_lufs"], sp["gap_300_lu"])


def check_speaker(F: Any, h: Dict[str, Any]) -> None:
    """speaker_loudness: the mix above 300 Hz far under the full mix (a phone plays it that much quieter)."""
    sp = h.get("speaker")
    if not sp or sp.get("gap_300_lu") is None:
        return
    th = h["thresholds"]
    g = float(sp["gap_300_lu"])
    if g <= th["speaker_gap_lu"]:
        return
    mx = sp.get("mix") or {}
    by_choice = mx.get("on") is False and mx.get("set_by") not in (None, "default")
    sev = "INFO" if by_choice else ("FAIL" if g > th["speaker_gap_fail_lu"] else "WARN")
    k1 = (" (above 1 kHz %.1f LUFS, %.1f LU under)" % (sp["above_1k_lufs"], sp["gap_1k_lu"])
          if sp.get("gap_1k_lu") is not None else "")
    msg = ("%s%s; the full mix is %.1f LUFS. Phones and laptops play little under 300 Hz and this mix's energy is "
           "bass and sub, so it plays about %.0f dB quieter there than a voice-led video at the same loudness" % (
               speaker_line(sp), k1, sp.get("integrated_lufs") or 0.0, max(1.0, g - 4.5)))
    if by_choice:
        msg += " (the speaker-safe step is off by choice: %s)" % mx.get("set_by")
        fix = "if the video is not only for headphones, remove \"speaker_safe\": false and render again"
    elif mx.get("on") and mx.get("capped"):
        fix = ("the mixer's speaker-safe step already cut the bed's lows by %g dB: pick a bed with more in the mids, "
               "raise its mid parts (lead, keys), or layer a mid transient on sub hits (metal-hit, glitch at -8 to "
               "-12 dB)" % abs(float(mx.get("shelf_db") or 12)))
    elif mx.get("on") is False:
        fix = "turn the mixer's speaker-safe step back on (\"master\": {\"speaker_safe\": true}) and render again"
    elif mx:
        fix = ("render again: `showtime audio mix` cuts the bed's lows (speaker-safe, on by default) until the mix is "
               "within 8 LU above 300 Hz; or pick a bed with more in the mids")
    else:
        fix = ("mix the soundtrack with `showtime audio mix` (its speaker-safe step cuts the bed's lows before the "
               "loudness normalisation), or cut the bed's lows by hand (a low shelf of -6 to -12 dB at 160 Hz) and "
               "master again; an ST.score bed is not mixed there: turn its bass and kick down. A bed with more in "
               "the mids also does it")
    F.add("speaker_loudness", sev, msg, fix=fix, gap_300_lu=g, above_300_lufs=sp.get("above_300_lufs"),
          gap_1k_lu=sp.get("gap_1k_lu"))


def check(F: Any, h: Dict[str, Any]) -> None:
    """The cheap hearing checks as qa WARNs with times (st.qa.video.Findings)."""
    th = h["thresholds"]
    check_speaker(F, h)
    masked = [r for r in h["lines"] if r["method"] == "stem" and r["voice_over_bed_db"] is not None
              and r["voice_over_bed_db"] < th["voice_over_bed_min_db"]]
    for r in masked[:6]:
        F.add("voice_masked", "WARN", "voice line %s (%.2f-%.2fs) is only %.1f dB over the music under it (aim 10-20 dB): "
              "\"%s\"" % (r["id"], r["start"], r["end"], r["voice_over_bed_db"], _snip(r["text"])), t=r["start"], end=r["end"],
              fix="lower the bed under this line (gain_points), duck it deeper (\"duck\": {\"under\": \"voice\", "
                  "\"depth_db\": 15}) or add \"carve\": 0.4; then check mix.report.json voice_to_music_db")
    if len(masked) > 6:
        F.add("voice_masked", "WARN", "%d more voice lines sit under %g dB over the music (audio.txt of review-pack lists "
              "them all)" % (len(masked) - 6, th["voice_over_bed_min_db"]), t=masked[6]["start"])
    for q in [q for q in h["quiet"] if not q["silent"]][:5]:
        F.add("quiet_stretch", "WARN", "near silence from %.2fs to %.2fs (%.1fs at %s LUFS, more than %g LU under the "
              "programme)" % (q["start"], q["end"], q["seconds"], "%.0f" % q["lufs"] if q["lufs"] is not None else "?",
                             th["quiet_under_lu"]), t=q["start"], end=q["end"],
              fix="carry the stretch with the bed (gain_points or section_gain), or close the pause in the voice timeline")
    for j in [j for j in h["cuts"] if j["flagged"]][:6]:
        F.add("level_jump", "WARN", "the %s level jumps %+.1f LU at the cut at %.2fs (%.1f -> %.1f LUFS)" % (
            j["kind"], j["jump"], j["t"], j["before"], j["after"]), t=j["t"],
            fix="even the level across the cut (section_gain / gain_points on the bed, gain_db on the voice line), "
                "or make it a designed drop on a music section change")
    e = h["ending"]
    if e.get("abrupt"):
        d = h["duration"]
        F.add("abrupt_end", "WARN", "the sound is still at %.0f LUFS on the last frame (%.0f LUFS over the 3 s before): "
              "the music, or a word, is cut off" % (e["tail_lufs"], e["body_lufs"]), t=max(0.0, d - 0.25),
              fix="fade the bed out over the last 0.5-1.5 s (\"fade_out\" on the music track) or end on its end_hit; "
                  "a seamless loop may ignore this")


def _snip(s: str, n: int = 60) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def summary(h: Dict[str, Any]) -> str:
    """One line for qa's report: what the hearing pass found."""
    th = h["thresholds"]
    parts = []
    ls = [r for r in h["lines"] if r["voice_over_bed_db"] is not None]
    if ls:
        lo = min(ls, key=lambda r: r["voice_over_bed_db"])
        parts.append("voice %.0f-%.0f dB over the bed%s" % (lo["voice_over_bed_db"], max(r["voice_over_bed_db"] for r in ls),
                                                            "" if any(r["method"] == "stem" for r in ls) else " (estimate)"))
    w = [r["wpm"] for r in h["lines"] if r["wpm"]]
    if w:
        parts.append("%d-%d wpm" % (min(w), max(w)))
    nq = len([q for q in h["quiet"] if not q["silent"]])
    nj = sum(1 for j in h["cuts"] if j["flagged"])
    parts.append("%d quiet stretch%s" % (nq, "" if nq == 1 else "es"))
    parts.append("%d level jump%s at cuts (> %g LU)" % (nj, "" if nj == 1 else "s", th["level_jump_lu"]))
    parts.append("ending %s" % ("cut off" if h["ending"].get("abrupt") else "fades or ends"))
    sl = speaker_line(h.get("speaker"))
    if sl:
        parts.append(sl)
    rb = h.get("readback") or {}
    if rb and not rb.get("skipped"):
        n = len(rb.get("suspects") or [])
        parts.append("read-back %s" % ("%d word%s heard differently" % (n, "" if n == 1 else "s") if n else
                                       "names and numbers as written"))
    return ", ".join(parts)


# ------------------------------------------------------------------ audio.txt

def text(h: Dict[str, Any], *, plot: Optional[str] = "hearing.png", name: str = "the video") -> str:
    """audio.txt: the hearing measurements, for a critic who cannot listen."""
    th = h["thresholds"]
    d = h["duration"]
    L: List[str] = ["# Hearing: what the sound does, measured",
                    "",
                    "You cannot listen to %s. These numbers measure what an ear would catch; judge only what they and "
                    "transcript.txt support, and quote them. Levels are K-weighted like LUFS (100 ms blocks)." % name, ""]

    def f(v: Any, fmt: str = "%.1f", none: str = "?") -> str:
        return none if v is None else fmt % v
    L.append("Length %.2fs. Integrated %s LUFS (target %s), true peak %s dBTP (ceiling %s), loudness range %s LU." % (
        d, f(h["integrated_lufs"]), f(h["target_lufs"], "%g"), f(h["true_peak_dbtp"]), f(h["ceiling_dbtp"], "%g"), f(h["lra"])))
    if h.get("voice_source"):
        fit = h.get("fit") or {}
        L.append("Voice and music measured apart: %s, lined up with this file's audio (lag %s ms, correlation %s)." % (
            h["voice_source"], fit.get("lag_ms"), fit.get("corr")))
    else:
        L.append("Voice and music measured together (no narration stem%s): the music under a line is estimated from the "
                 "quietest moments between its words, which overstates it a little (marked estimate)." % (
                     ": %s" % h["voice_note"] if h.get("voice_note") else ""))
    if h.get("voice_to_music_db") is not None:
        L.append("The mix report says the voice sits %.1f dB over the music overall." % h["voice_to_music_db"])
    L += speaker_text(h.get("speaker"), th)
    if h.get("lines_source"):
        L.append("Lines from %s." % h["lines_source"])
    if plot:
        L.append("Plot: %s (top: loudness, scene changes as lines, speech as a blue band, effects as ticks, problems in "
                 "red; bottom: each voice line's level over the music and its words per minute)." % plot)

    L += ["", "## Voice line by line (aim 10-20 dB over the music; under %g dB it competes with the words; comfortable "
              "narration is 130-170 words a minute)" % th["voice_over_bed_min_db"]]
    if not h["lines"]:
        L.append("(no narration: no voice timeline or caption file belongs to this render)")
    for r in h["lines"]:
        over = "      -  " if r["voice_over_bed_db"] is None else "%+6.1f dB" % r["voice_over_bed_db"]
        how = " estimate" if r["method"] == "estimate" and r["voice_over_bed_db"] is not None else ""
        extra = [r["note"]] if r["note"] else []
        extra += r["flags"]
        L.append("%7.2f-%7.2fs  %s wpm  %s%s  %s: \"%s\"%s" % (
            r["start"], r["end"], "%4d" % r["wpm"] if r["wpm"] else "   -", over, how, r["id"], _snip(r["text"], 90),
            ("  <- " + "; ".join(extra)) if extra else ""))

    L += readback_text(h.get("readback"))

    L += ["", "## Pauses in the voice longer than %g s" % th["quiet_stretch_s"]]
    L += ["%7.2f-%7.2fs  %.1fs, the programme at %s LUFS meanwhile" % (g["start"], g["end"], g["seconds"], f(g["lufs"], "%.0f"))
          for g in h["voice_pauses"]] or ["(none)"]

    L += ["", "## Near silence mid-video (%g s or more under %s LUFS)" % (
        th["quiet_stretch_s"], f(h["quiet"][0]["under"], "%.0f") if h["quiet"] else "integrated - %g" % th["quiet_under_lu"])]
    L += ["%7.2f-%7.2fs  %.1fs at %s LUFS%s" % (q["start"], q["end"], q["seconds"], f(q["lufs"], "%.0f"),
                                                "  (digital silence: qa's silent_gap)" if q["silent"] else "")
          for q in h["quiet"]] or ["(none)"]

    L += ["", "## Loudness per scene"]
    for s in h["scenes"]:
        extra = ""
        if "bed_lufs" in s:
            extra = ", music %s, voice %s" % (f(s["bed_lufs"], "%.0f"), f(s.get("voice_lufs"), "%.0f", "-"))
        L.append("%7.2f-%7.2fs  %s LUFS (loudest 3 s %s)%s, speech %d%%  %s" % (
            s["start"], s["end"], f(s["lufs"]), f(s["short_term_max"], none="-"), extra, round(100 * s["speech_share"]), s["name"]))
    if not h["scenes"]:
        L.append("(one scene)")

    L += ["", "## Level across each cut (1 s each side, like with like; over %g LU the ear notices a jump)" % th["level_jump_lu"]]
    for j in h["cuts"]:
        lvl = ("%s %s -> %s LUFS, %s" % (j["kind"], f(j["before"], "%.1f"), f(j["after"], "%.1f"),
                                         "%+.1f LU" % j["jump"] if j["jump"] is not None else "no jump measured")
               if j["kind"] else "not compared")
        L.append("%7.2fs  %s%s%s" % (j["t"], lvl, "  <- JUMP" if j["flagged"] else "",
                                     ("  (" + "; ".join(j["notes"]) + ")") if j["notes"] else ""))
    if not h["cuts"]:
        L.append("(no cuts more than 1 s from either end)")

    L += ["", "## Effects (from the render's mix report: hit time, over the rest of the mix there, rise over the 0.5 s "
              "before, peak over the integrated loudness, the nearest cut or CUE)"]
    fx = h["sfx"]
    if not fx:
        L.append("(no effects, or no mix report for this render)")
    i = 0
    while i < len(fx):
        j = i
        while j + 1 < len(fx) and fx[j + 1]["family"] == fx[i]["family"]:
            j += 1
        grp = fx[i:j + 1]
        if len(grp) >= 6:
            ab = [g["above_bed_db"] for g in grp if g["above_bed_db"] is not None]
            L.append("%7.2f-%7.2fs  %d x %s%s%s" % (grp[0]["t"], grp[-1]["t"], len(grp), grp[0]["name"],
                                                     ", %+.0f to %+.0f dB over the rest" % (min(ab), max(ab)) if ab else "",
                                                     ("  <- %d under the rest of the mix" % sum(1 for g in grp if "under the rest of the mix" in g["flags"]))
                                                     if any("under the rest of the mix" in g["flags"] for g in grp) else ""))
        else:
            for g in grp:
                where = []
                if g["nearest_cut"] is not None and not any(" the cut at " in x for x in g["flags"]):
                    dd = g["t"] - g["nearest_cut"]
                    where.append("on the cut at %.2fs" % g["nearest_cut"] if abs(dd) <= 0.04 else
                                 "%.2fs %s the cut at %.2fs" % (abs(dd), "after" if dd > 0 else "before", g["nearest_cut"]))
                if g["cue"]:
                    where.append("CUE.%s %.2fs (%+.2fs)" % (g["cue"]["name"], g["cue"]["t"], g["cue"]["off"]))
                L.append("%7.2fs  %s (%s): %s over the rest, rises %s LU, peaks %s LU over the integrated%s%s" % (
                    g["t"], g["id"], g["name"], f(g["above_bed_db"], "%+.1f dB"), f(g["rise_lu"], "%+.1f"),
                    f(g["over_programme_lu"], "%+.1f"), ("; " + ", ".join(where)) if where else "",
                    ("  <- " + "; ".join(g["flags"])) if g["flags"] else ""))
        i = j + 1

    L += ["", "## The ending"]
    e = h["ending"]
    for m in e.get("music") or []:
        L.append("%s %s (%s): %s-%ss%s%s%s" % (
            m["kind"], m["id"], m["name"], f(m["start"], "%.2f"), f(m["end"], "%.2f"),
            ", ends on its end hit at %.2fs" % m["end_hit"] if m.get("end_hit") is not None else "",
            ", ducks %s dB under the voice" % f(m.get("duck_db"), "%g", "12") if m.get("ducks") else "",
            ", fitted to the video" if m.get("fit") else ""))
    if e.get("music_stops_early_s"):
        L.append("The music stops %.1fs before the picture ends." % e["music_stops_early_s"])
    if e.get("tail_lufs") is not None:
        L.append("The last 0.2 s of %s: %.0f LUFS; the 3 s before: %s LUFS -> %s" % (
            e["measured_on"], e["tail_lufs"], f(e.get("body_lufs"), "%.0f"),
            "STILL PLAYING on the last frame (cut off)" if e["abrupt"] else "it has faded or ended"))
    late = [r for r in h["lines"] if "runs to the last frame" in r["flags"]]
    if late:
        L.append("The voice line %s runs to the last frame." % late[0]["id"])

    L += ["", "## Peaks"]
    cl = h.get("clipping") or {}
    L.append("True peak %s dBTP, sample peak %s dBFS, %s" % (
        f(h["true_peak_dbtp"]), f(h["sample_peak_dbfs"]),
        ("%d clipped runs, first at %s" % (cl["runs"], ", ".join("%.2fs" % t for t in cl.get("times", [])[:5])))
        if cl.get("runs") else "no clipped runs"))
    return "\n".join(L).rstrip() + "\n"


def speaker_text(sp: Optional[Dict[str, Any]], th: Dict[str, float]) -> List[str]:
    """audio.txt's lines on how the mix plays on a phone or laptop speaker."""
    if not sp or sp.get("gap_300_lu") is None:
        return []
    g = float(sp["gap_300_lu"])
    L = ["Heard on a phone: %s (above 1 kHz %s LUFS, %s LU under). Phone and laptop speakers play little under "
         "300 Hz; the posted films sit 1-8 LU under, over %g LU the video sounds quiet on a phone, over %g it is "
         "close to silent there -> %s." % (
             speaker_line(sp), "%.1f" % sp["above_1k_lufs"] if sp.get("above_1k_lufs") is not None else "?",
             "%.1f" % sp["gap_1k_lu"] if sp.get("gap_1k_lu") is not None else "?", th["speaker_gap_lu"],
             th["speaker_gap_fail_lu"], "fine" if g <= th["speaker_gap_lu"] else
             "TOO QUIET ON A PHONE" if g <= th["speaker_gap_fail_lu"] else "ALMOST SILENT ON A PHONE")]
    mx = sp.get("mix") or {}
    if mx.get("on") is False:
        L.append("The mixer's speaker-safe step was off (%s)." % (mx.get("set_by") or "?"))
    elif mx.get("shelf_db"):
        L.append("The mixer's speaker-safe step cut the bed's lows %g dB at %g Hz (%s; %.1f LU under before)%s." % (
            abs(float(mx["shelf_db"])), mx.get("shelf_hz") or 160, ", ".join(mx.get("shelved") or []) or "the bed",
            mx.get("gap_300_lu_before") or 0.0, ", the most it does" if mx.get("capped") else ""))
    if mx.get("sub_alone"):
        L.append("Sub-heavy effects with nothing in the mids on their hit (a phone hardly plays them): %s." %
                 ", ".join(mx["sub_alone"]))
    return L


def readback_text(rep: Optional[Dict[str, Any]]) -> List[str]:
    """audio.txt's read-back table: every voice line as the script has it and as it was heard back."""
    if not rep:
        return []
    L = ["", "## Read-back: the voice-over transcribed again and compared with the script (names, acronyms, numbers)"]
    if rep.get("skipped"):
        return L + ["(not run: %s)" % rep["skipped"]]
    sus = rep.get("suspects") or []
    L.append("%s. A word listed here was heard differently: judge it as a mispronunciation unless the heard "
             "spelling is only another way to write the same sound." % (rep.get("summary") or "read-back").rstrip("."))
    for s in sus:
        L.append("%7ss  %s  script: %s / heard: %s%s" % (
            "%.2f" % s["t"] if s.get("t") is not None else "?", s.get("line"), s["word"], s.get("heard") or "(nothing)",
            "  <- a name in the title, brand or lexicon" if s.get("critical") else ""))
    for ln in rep.get("lines") or []:
        t = ln.get("video_start", ln.get("start"))
        L.append("%7ss  %s%s" % ("%.2f" % float(t) if t is not None else "?", ln.get("id"),
                                  "  <- " + ", ".join(ln["suspects"]) if ln.get("suspects") else ""))
        L.append("           script: %s" % _snip(str(ln.get("script") or ""), 160))
        L.append("           heard:  %s" % (_snip(str(ln.get("heard") or "(nothing)"), 160) if not ln.get("skipped")
                                            else "(not heard back: %s)" % ln["skipped"]))
    return L


def graph(h: Dict[str, Any], blk: Dict[str, Any], out: Path, title: str = "") -> Optional[str]:
    """hearing.png (st.qa.images.hearing_graph); None without block levels."""
    if not blk.get("programme"):
        return None
    from . import images
    return str(images.hearing_graph(h, blk, out, title=title))


# ------------------------------------------------------------------ for review-pack

def for_pack(video: Path, proj: Optional[Path], q: Dict[str, Any], qa_dir: Path, *,
             cuts: Sequence[float], scenes: Sequence[Tuple[float, float, str]], out_dir: Path,
             name: str = "the video", title: str = "") -> Optional[Dict[str, Any]]:
    """audio.txt and hearing.png for a review pack, from a qa run's block levels (qa_dir/loudness.json) and
    the pack's own cuts and scenes. None when the video has no measured audio."""
    from ..common import read_json
    from . import review
    lj = read_json(qa_dir / "loudness.json", {}) if (qa_dir / "loudness.json").is_file() else {}
    blk = lj.get("blocks") if isinstance(lj, dict) else None
    if not isinstance(blk, dict) or not blk.get("programme"):
        return None
    dur = float(((q.get("probe") or {}).get("duration")) or 0.0)
    lines, src = speech_lines(video, proj)
    off = review._offset(video)
    mp = own_mix_report(video)
    mix = mix_facts(read_json(mp, None) if mp else None, off, dur)
    cues = {k: v - off for k, v in cue_values(proj).items()}
    sp = (q.get("hearing") or {}).get("speaker")
    h = measure(blk, dur, lines=lines, lines_source=src, cuts=cuts, scenes=scenes, mix=mix, cues=cues,
                loud=q.get("loudness") or {}, speaker={k: v for k, v in sp.items() if k != "mix"} if isinstance(sp, dict) else None)
    h["readback"] = (q.get("hearing") or {}).get("readback")
    png = graph(h, blk, out_dir / "hearing.png", title=title)
    (out_dir / "audio.txt").write_text(text(h, plot="hearing.png" if png else None, name=name), encoding="utf-8",
                                       newline="\n")
    return {"text": str(out_dir / "audio.txt"), "graph": png, "summary": summary(h),
            "mix_report": str(mp) if mp else None}

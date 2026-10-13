"""X-ray drums: `showtime xray notes --instrument drums`.

A classifier of sound types, not a transcription: the hits come from xray.detect_flux (spectral flux, so a kick
that has no high end is still a hit), and each hit is sorted by its spectrum in the first 5-35 ms (70 ms for the low tone) against the
sound just before it: kick (a low tone under 100 Hz), snare (1-5 kHz noise), tom (a tonal 100-300 Hz body without
noise), hi-hat (noise from 6 kHz up, closed when it dies within 120 ms, open up to 450 ms) and crash (longer).
It does not know the kit: a kick and a hat within the same onset are two pieces; a hat under a snare is not seen.
Writes the "drums" list of notes.json, MIDI on channel 10 (General MIDI drum map), a MusicXML percussion staff
(sixteenth grid) and check-notes.jpg.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

import numpy as np

from .common import ShowtimeError, write_json
from . import xray_music as xm

SCHEMA = xm.SCHEMA
ENGINE = "flux-onsets+band-classifier"
SR = 48000
GM = {"kick": 36, "snare": 38, "hihat_closed": 42, "hihat_open": 46, "crash": 49}
TOM_GM = ((110.0, 45), (160.0, 48), (1e9, 50))          # by the tone's frequency: low, mid, high tom
PIECES = ("kick", "snare", "tom", "hihat_closed", "hihat_open", "crash")
RISE_DB = 8.0
KICK_RISE_DB = 12.0
KICK_MAX_HZ = 100.0
TONAL = 4.0                                              # peak over mean of the 100-300 Hz spectrum: a tone, not noise
OPEN_S = 0.12
CRASH_S = 0.45
HAT_DROP_DB = 15.0
SEG_A, SEG_B = 0.005, 0.035                              # seconds after the onset: skips the click of a kick
BASE_A, BASE_B = -0.030, -0.003
NFFT = 8192
# MusicXML percussion staff (display position, notehead)
XML_POS = {"kick": ("F", 4, None), "snare": ("C", 5, None), "hihat_closed": ("G", 5, "x"), "hihat_open": ("G", 5, "circle-x"),
           "crash": ("A", 5, "x")}
XML_TOM = {45: ("A", 4), 48: ("D", 5), 50: ("E", 5)}
DRUM_NAMES = {"kick": "Bass Drum", "snare": "Snare", "hihat_closed": "Closed Hi-Hat", "hihat_open": "Open Hi-Hat", "crash": "Crash Cymbal"}


def _psd(seg: np.ndarray, sr: int) -> Tuple[np.ndarray, np.ndarray]:
    """(freqs, power per Hz up to a constant) of a Hann-windowed segment, zero padded."""
    if len(seg) < 8:
        return np.fft.rfftfreq(NFFT, 1.0 / sr), np.zeros(NFFT // 2 + 1)
    w = np.hanning(len(seg))
    X = np.fft.rfft(seg * w, NFFT)
    return np.fft.rfftfreq(NFFT, 1.0 / sr), (np.abs(X) ** 2) / float(np.sum(w * w))


def _band(f: np.ndarray, P: np.ndarray, lo: float, hi: float) -> float:
    m = (f >= lo) & (f < hi)
    return float(P[m].mean()) if m.any() else 0.0


def _db(a: float, b: float) -> float:
    return 10.0 * math.log10((a + 1e-12) / (b + 1e-12))


def _slice(x: np.ndarray, a: int, t0: float, t1: float, sr: int) -> np.ndarray:
    i0, i1 = max(0, a + int(round(t0 * sr))), max(0, a + int(round(t1 * sr)))
    return x[i0:i1]


def hat_length(x: np.ndarray, a: int, next_a: Optional[int], sr: int = SR) -> float:
    """Seconds the 6 kHz+ noise rings after the onset at sample `a`: until it falls 15 dB under its peak, or until the
    next hit (at most 0.7 s) while it is still ringing."""
    from scipy import signal
    n = int(0.7 * sr)
    if next_a is not None:
        n = min(n, max(1, next_a - a - int(0.004 * sr)))
    seg = x[max(0, a - int(0.005 * sr)):a + n]
    if len(seg) < int(0.02 * sr):
        return 0.0
    y = signal.sosfilt(signal.butter(4, 6000.0, "hp", fs=sr, output="sos"), seg)
    hop = int(0.002 * sr)
    k = len(y) // hop
    if k < 4:
        return 0.0
    env = np.sqrt((y[:k * hop].reshape(k, hop) ** 2).mean(axis=1)) + 1e-12
    ip = int(np.argmax(env[:max(2, int(0.03 / 0.002))]))
    lim = env[ip] * 10 ** (-HAT_DROP_DB / 20.0)
    below = np.where(env[ip:] < lim)[0]
    return float((ip + (below[0] if len(below) else len(env) - ip)) * 0.002 - 0.0)


def measure(x: np.ndarray, a: int, sr: int = SR) -> Dict[str, float]:
    """What rose at the onset at sample `a` over the sound just before it (dB per band), and the tone and noise shape."""
    on = _slice(x, a, SEG_A, SEG_B, sr)
    pre = _slice(x, a, BASE_A, BASE_B, sr)
    f, Pon = _psd(on, sr)
    _, Ppre = _psd(pre, sr)
    fk, Pk = _psd(_slice(x, a, 0.0, 0.07, sr), sr)
    _, Pkpre = _psd(pre, sr)
    m = (fk >= 40) & (fk <= 300)
    body = (f >= 100) & (f <= 300)
    return {
        "mid_rise": _db(_band(f, Pon, 1000, 5000), _band(f, Ppre, 1000, 5000)),
        "high_rise": _db(_band(f, Pon, 6000, 16000), _band(f, Ppre, 6000, 16000)),
        "body_rise": _db(_band(f, Pon, 100, 300), _band(f, Ppre, 100, 300)),
        "low_rise": _db(_band(fk, Pk, 30, 110), _band(fk, Pkpre, 30, 110)),
        "mid_psd": _band(f, Pon, 1000, 5000), "high_psd": _band(f, Pon, 6000, 16000),
        "peak_hz": float(fk[m][int(np.argmax(Pk[m]))]) if m.any() else 0.0,
        "tonal": float(Pon[body].max() / (Pon[body].mean() + 1e-12)) if body.any() else 0.0}


def is_hit(m: Dict[str, float]) -> bool:
    """Something rose by 8 dB (12 for the low tone) over the sound before it: a new hit, not the flux wobbling in a ring-out."""
    return max(m["mid_rise"], m["high_rise"], m["body_rise"] - 2.0) >= RISE_DB or m["low_rise"] >= KICK_RISE_DB


def classify(x: np.ndarray, a: int, next_a: Optional[int], sr: int = SR, m: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    """The pieces heard at the onset at sample `a`: [{"piece", "gm", ("hz")}]; empty when no band rose over the sound before it."""
    m = m or measure(x, a, sr)
    mid_psd, high_psd, peak_hz = m["mid_psd"], m["high_psd"], m["peak_hz"]
    out: List[Dict[str, Any]] = []
    kick = m["low_rise"] >= KICK_RISE_DB and peak_hz < KICK_MAX_HZ
    snare = m["mid_rise"] >= RISE_DB and mid_psd >= 0.25 * high_psd
    # a hat over a snare: the snare's noise is about as loud at 6-16 kHz as at 1-5 kHz, a hat adds a lot more up there
    hat = m["high_rise"] >= RISE_DB and high_psd > 1e-9 and (not snare or high_psd >= 3.0 * mid_psd)
    tom = m["body_rise"] >= 10.0 and m["tonal"] >= TONAL and peak_hz >= KICK_MAX_HZ and not kick and not snare
    if kick:
        out.append({"piece": "kick", "gm": GM["kick"]})
    if snare:
        out.append({"piece": "snare", "gm": GM["snare"]})
    if hat:
        dur = hat_length(x, a, next_a, sr)
        piece = "hihat_closed" if dur < OPEN_S else "hihat_open" if dur < CRASH_S else "crash"
        out.append({"piece": piece, "gm": GM[piece]})
    if tom:
        out.append({"piece": "tom", "gm": next(g for hz, g in TOM_GM if peak_hz < hz), "hz": round(peak_hz, 1)})
    return out


def detect_hits(x: np.ndarray, t_from: float = 0.0, t_to: Optional[float] = None, sr: int = SR) -> List[Dict[str, Any]]:
    """[{t, piece, gm, velocity}] sorted by time (t absolute, with t_from)."""
    from . import xray
    ev, _ = xray.detect_flux(x, sr, min_gap=0.04, sensitivity=0.6, t_from=t_from, t_to=t_to)
    if not ev:
        return []
    idx = [int(round((e["t"] - t_from) * sr)) for e in ev]
    env = xray.envelope_db(x, sr)
    peaks = []
    for a in idx:
        ms = int(a / (sr / 1000.0))
        peaks.append(float(env[ms:ms + 60].max()) if ms < len(env) else -120.0)
    top = max(peaks)
    meas = [measure(x, a, sr) for a in idx]
    real = [k for k in range(len(ev)) if is_hit(meas[k])]
    hits = []
    for r, k in enumerate(real):
        e = ev[k]
        nxt = idx[real[r + 1]] if r + 1 < len(real) else None
        vel = float(min(1.0, max(0.1, 1.0 + (peaks[k] - top) / 30.0)))
        for p in classify(x, idx[k], nxt, sr, meas[k]):
            h = {"t": e["t"], "piece": p["piece"], "gm": p["gm"], "velocity": round(vel, 3)}
            if "hz" in p:
                h["hz"] = p["hz"]
            hits.append(h)
    return hits


# ------------------------------------------------------------------ score and files

DIV = 4                                                  # divisions per quarter: a sixteenth is 1
MEASURE = 4 * DIV
_TYPES = {1: ("16th", False), 2: ("eighth", False), 3: ("eighth", True), 4: ("quarter", False), 6: ("quarter", True),
          8: ("half", False), 12: ("half", True), 16: ("whole", False)}


def _pieces(d: int) -> List[int]:
    out = []
    for p in (16, 12, 8, 6, 4, 3, 2, 1):
        while d >= p:
            out.append(p)
            d -= p
    return out


def _rest(dur: int) -> str:
    typ, dot = _TYPES[dur]
    return "<note><rest/><duration>%d</duration><voice>1</voice><type>%s</type>%s</note>" % (dur, typ, "<dot/>" if dot else "")


def _hit_xml(group: Sequence[Dict[str, Any]], dur: int, tie_stop: bool, tie_start: bool) -> str:
    typ, dot = _TYPES[dur]
    xs = []
    for k, h in enumerate(group):
        if h["piece"] == "tom":
            step, octv = XML_TOM[h["gm"]]
            head = None
        else:
            step, octv, head = XML_POS[h["piece"]]
        s = "<note>" + ("<chord/>" if k else "")
        s += "<unpitched><display-step>%s</display-step><display-octave>%d</display-octave></unpitched><duration>%d</duration>" % (step, octv, dur)
        s += ('<tie type="stop"/>' if tie_stop else "") + ('<tie type="start"/>' if tie_start else "")
        s += '<instrument id="P1-I%d"/><voice>1</voice><type>%s</type>%s' % (h["gm"], typ, "<dot/>" if dot else "")
        s += "<notehead>%s</notehead>" % head if head else ""
        if tie_stop or tie_start:
            s += "<notations>%s%s</notations>" % ('<tied type="stop"/>' if tie_stop else "", '<tied type="start"/>' if tie_start else "")
        xs.append(s + "</note>")
    return "".join(xs)


def musicxml(hits: Sequence[Dict[str, Any]], quant: Sequence[Dict[str, Any]], bpm: float, title: str = "x-ray drums") -> str:
    """A percussion-staff MusicXML 3.1 file: one voice, simultaneous pieces as chords, each hit an eighth or a sixteenth
    (as far as the next hit allows) followed by rests. Standard drum positions (kick F4, snare C5, hats G5 x, crash A5 x,
    toms E5/D5/A4)."""
    by: Dict[int, List[Dict[str, Any]]] = {}
    for h, q in zip(hits, quant):
        by.setdefault(int(round(q["beat"] * DIV)), []).append(h)
    starts = sorted(by)
    n_meas = max(1, int(math.ceil((starts[-1] + 1) / float(MEASURE)))) if starts else 1
    items: List[Tuple[int, int, Optional[List[Dict[str, Any]]], bool, bool]] = []
    pos = 0

    def add(st: int, d: int, group: Optional[List[Dict[str, Any]]]) -> None:
        cuts = []
        while d > 0:
            take = min(d, MEASURE - (st % MEASURE))
            for p in _pieces(take):
                cuts.append((st, p))
                st += p
            d -= take
        for k, (s, p) in enumerate(cuts):
            items.append((s, p, group, group is not None and k > 0, group is not None and k < len(cuts) - 1))

    for k, st in enumerate(starts):
        if st > pos:
            add(pos, st - pos, None)
        d = min(2, starts[k + 1] - st) if k + 1 < len(starts) else 1
        add(st, d, by[st])
        pos = st + d
    if pos < n_meas * MEASURE:
        add(pos, n_meas * MEASURE - pos, None)
    meas = ["" for _ in range(n_meas)]
    for st, d, g, ts, tt in items:
        meas[st // MEASURE] += _hit_xml(g, d, ts, tt) if g else _rest(d)
    used = sorted({(h["gm"], h["piece"]) for h in hits})
    si, mi = [], []
    for gm, piece in used:
        nm = DRUM_NAMES.get(piece, "Tom %d" % gm)
        si.append('<score-instrument id="P1-I%d"><instrument-name>%s</instrument-name></score-instrument>' % (gm, escape(nm)))
        mi.append('<midi-instrument id="P1-I%d"><midi-channel>10</midi-channel><midi-unpitched>%d</midi-unpitched></midi-instrument>' % (gm, gm + 1))
    x = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">',
         '<score-partwise version="3.1"><work><work-title>%s</work-title></work>' % escape(title),
         '<identification><encoding><software>showtime xray notes</software></encoding></identification>',
         '<part-list><score-part id="P1"><part-name>Drums</part-name>%s%s</score-part></part-list><part id="P1">' % ("".join(si), "".join(mi))]
    for m in range(n_meas):
        x.append('<measure number="%d">' % (m + 1))
        if m == 0:
            x.append('<attributes><divisions>%d</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time>'
                     '<clef><sign>percussion</sign><line>2</line></clef></attributes>'
                     '<direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>%d</per-minute>'
                     '</metronome></direction-type><sound tempo="%d"/></direction>' % (DIV, round(bpm), round(bpm)))
        x.append(meas[m])
        x.append("</measure>")
    x.append("</part></score-partwise>")
    return "".join(x)


LANES = ["crash", "hihat_open", "hihat_closed", "tom", "snare", "kick"]
COLORS = {"kick": (80, 160, 255), "snare": (255, 150, 40), "hihat_closed": (120, 220, 140), "hihat_open": (60, 190, 110),
          "tom": (220, 120, 220), "crash": (250, 220, 90)}


def check_sheet(doc: Dict[str, Any], audio: np.ndarray, t0: float, dest: Path, width: int = 1600) -> Path:
    """The waveform with a tick per hit and one lane per piece."""
    from PIL import Image, ImageDraw
    dur = len(audio) / float(SR)
    t1 = t0 + max(dur, 0.1)
    wave_h, lane_h, pad = 140, 34, 28
    H = pad + wave_h + 8 + lane_h * len(LANES) + 24
    img = Image.new("RGB", (width, H), (18, 20, 26))
    d = ImageDraw.Draw(img)

    def px(t: float) -> int:
        return int(round((t - t0) / (t1 - t0) * (width - 1)))

    mid = pad + wave_h // 2
    seg = max(1, len(audio) // width)
    top = max(1e-6, float(np.max(np.abs(audio))) if len(audio) else 1.0)
    for x in range(width):
        s = audio[x * seg:(x + 1) * seg]
        if len(s):
            a = int(float(np.max(np.abs(s))) * (wave_h / 2 - 2) / top)
            d.line([(x, mid - a), (x, mid + a)], fill=(84, 112, 150))
    y0 = pad + wave_h + 8
    for k, lane in enumerate(LANES):
        d.text((4, y0 + k * lane_h + 4), lane, fill=(120, 128, 150))
    for h in doc["drums"]:
        k = LANES.index(h["piece"])
        x = px(h["t"])
        d.line([(x, pad), (x, pad + wave_h)], fill=(255, 90, 90))
        d.rectangle([x, y0 + k * lane_h + 2, x + 4, y0 + (k + 1) * lane_h - 2], fill=COLORS[h["piece"]])
    d.text((8, 6), "%s: %d hits (classified by sound), %.0f bpm" % (doc["source"]["file"], len(doc["drums"]), doc["tempo"]["bpm"]), fill=(230, 232, 240))
    for s in range(int(math.ceil(t0)), int(t1) + 1):
        d.text((px(s) + 2, H - 16), "%ds" % s, fill=(130, 136, 154))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dest), quality=88)
    return dest


def analyze(clip: Any, out_dir: Any, *, t_from: float = 0.0, t_to: Optional[float] = None) -> Dict[str, Any]:
    """Write notes.json (with "drums"), notes.mid (channel 10), notes.musicxml and check-notes.jpg; returns the notes.json dict."""
    from . import xray
    from .audio import wav
    clip = Path(clip)
    if not clip.is_file():
        raise ShowtimeError("clip not found: %s" % clip, hint="pass the video file you filmed")
    if t_to is not None and t_to <= t_from:
        raise ShowtimeError("--to (%g) must be after --from (%g)" % (t_to, t_from))
    out = Path(out_dir)
    src = xray._source_info(clip)
    if not src.pop("has_audio"):
        raise ShowtimeError("%s has no sound to read hits from" % clip.name, hint="x-ray reads the hits from the clip's audio")
    out.mkdir(parents=True, exist_ok=True)
    t_from = max(0.0, t_from)
    x = np.asarray(wav.load(clip, sr=SR, mono=True, offset=t_from, duration=(t_to - t_from) if t_to is not None else None), dtype=np.float32)
    hits = detect_hits(x, t_from, t_to)
    fps = float(src["fps"])
    drums = []
    for i, h in enumerate(hits):
        d = {"i": i, "t": round(h["t"], 4), "frame": xray.frame_of(h["t"], fps), "piece": h["piece"], "gm": h["gm"], "velocity": h["velocity"]}
        if "hz" in h:
            d["hz"] = h["hz"]
        drums.append(d)
    onset_t = sorted({d["t"] for d in drums})
    tm = xm.tempo_map(onset_t, grid=0.25)
    quant = [{"i": d["i"], "beat": max(0.0, round(xm.beat_of(d["t"], tm["map"]) * 4.0) / 4.0), "dur_beats": 0.25} for d in drums]
    doc: Dict[str, Any] = {
        "schema": SCHEMA, "source": src, "engine": ENGINE, "instrument": "drums",
        "note": "a classifier of sound types (kick, snare, hats, tom, crash by spectrum), not a transcription of a known kit",
        "range": {"from": t_from, "to": t_to}, "notes": [], "drums": drums, "tempo": tm, "quantized": quant}
    write_json(out / "notes.json", doc)
    midi = [{"t": d["t"], "end": d["t"] + 0.1, "pitch": d["gm"], "velocity": d["velocity"]} for d in drums]
    (out / "notes.mid").write_bytes(xm.midi_bytes(midi, tm["bpm"], channel=9))
    (out / "notes.musicxml").write_text(musicxml(drums, quant, tm["bpm"], clip.stem), encoding="utf-8")
    check_sheet(doc, x, t_from, out / "check-notes.jpg")
    return doc

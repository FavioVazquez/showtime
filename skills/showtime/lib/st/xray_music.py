"""X-ray music: the notes a filmed instrument plays (`showtime xray notes`).

Pitch model: Spotify's basic-pitch (Apache-2.0) as a 230 KB ONNX graph (assets/xray/nmp.onnx; its constant-Q
transform is inside the graph), run with onnxruntime: no TensorFlow. The windowing of the audio and the note
creation (model output -> note events) are numpy ports of basic_pitch.inference.run_inference and
basic_pitch.note_creation (see assets/xray/NOTICE); pitch bends are not ported.

On top of the notes: a smooth tempo map from the inter-onset intervals, eighth-note quantization, key
(Krumhansl-Schmuckler), chords, melody and bass voices, a guitar string/fret mapping, MIDI and MusicXML writers
(plain Python) and a check picture (piano roll over the waveform). Writes <job>/xray/notes.json (schema
showtime.xray.notes/1), notes.mid, notes.musicxml and check-notes.jpg.
"""
from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape

import numpy as np

from .common import ShowtimeError, write_json

SCHEMA = "showtime.xray.notes/1"
ENGINE = "basic-pitch-onnx"
MODEL = Path(__file__).resolve().parent / "assets" / "xray" / "nmp.onnx"

# basic_pitch.constants
SR = 22050
FFT_HOP = 256
ANNOT_FPS = SR // FFT_HOP                                   # 86
ANNOT_N_FRAMES = ANNOT_FPS * 2                              # 172
AUDIO_N_SAMPLES = SR * 2 - FFT_HOP                          # 43844
N_OVERLAP_FRAMES = 30
MIDI_OFFSET = 21
N_PITCHES = 88
MAX_FREQ_IDX = 87
FRAME_S = FFT_HOP / float(SR)                               # 11.6 ms

ONSET_THRESH = 0.5
FRAME_THRESH = 0.3
MIN_NOTE_LEN = 11                                           # frames (127.70 ms)
ENERGY_TOL = 11

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
KEY_NAMES_MAJOR = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
KEY_NAMES_MINOR = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]
CHORD_NAMES = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
KS_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
KS_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]
CHORD_TEMPLATES = [("", (0, 4, 7)), ("m", (0, 3, 7)), ("7", (0, 4, 7, 10)), ("dim", (0, 3, 6))]

MELODY_MIN_PITCH = 64                                       # E4
MELODY_MIN_CONF = 0.4
BASS_MIN_CONF = 0.3
CLUSTER_S = 0.035                                           # notes starting this close are one onset
GUITAR_OPEN = [64, 59, 55, 50, 45, 40]                      # strings 1..6: E4 B3 G3 D3 A2 E2
GUITAR_FRETS = 19
INSTRUMENTS = ("auto", "guitar", "piano", "musicbox", "drums")


def note_name(p: int) -> str:
    return "%s%d" % (NAMES[p % 12], p // 12 - 1)


# ------------------------------------------------------------------ audio and model

def load_audio(clip: Any, t_from: float = 0.0, t_to: Optional[float] = None) -> np.ndarray:
    """Mono float32 at 22050 Hz of the clip (or of --from..--to), decoded with showtime's own ffmpeg."""
    from .audio import wav
    dur = (t_to - t_from) if t_to is not None else None
    return np.asarray(wav.load(clip, sr=SR, mono=True, offset=max(0.0, t_from), duration=dur), dtype=np.float32)


def _session() -> Any:
    try:
        import onnxruntime as ort
    except ImportError as e:
        raise ShowtimeError("onnxruntime is not installed, so the notes cannot be read (%s)" % e,
                            hint="install showtime's environment (`showtime doctor --fix`) or `pip install onnxruntime` into it")
    if not MODEL.is_file():
        raise ShowtimeError("the note model is missing: %s" % MODEL, hint="reinstall showtime (assets/xray/nmp.onnx ships with it)")
    so = ort.SessionOptions()
    so.log_severity_level = 3
    return ort.InferenceSession(str(MODEL), sess_options=so, providers=["CPUExecutionProvider"])


def infer(audio: np.ndarray) -> Dict[str, np.ndarray]:
    """basic_pitch.inference.run_inference on a 22050 Hz mono signal: 2 s windows with 30 frames of overlap, the
    overlap trimmed, the pieces joined. Returns {"note": (frames, 88), "onset": (frames, 88)}."""
    sess = _session()
    in_name = sess.get_inputs()[0].name
    names = [o.name for o in sess.get_outputs()]
    # the graph's outputs are named after the TF signature: note=:1, onset=:2, contour=:0
    want = {"note": "StatefulPartitionedCall:1", "onset": "StatefulPartitionedCall:2"}
    for k, v in want.items():
        if v not in names:
            raise ShowtimeError("unexpected note model (outputs %s)" % names, hint="use the nmp.onnx that ships with showtime")
    overlap_len = N_OVERLAP_FRAMES * FFT_HOP
    hop = AUDIO_N_SAMPLES - overlap_len
    x = np.asarray(audio, dtype=np.float32).reshape(-1)
    n_orig = int(x.shape[0])
    if n_orig == 0:
        raise ShowtimeError("no audio to read the notes from")
    x = np.concatenate([np.zeros(overlap_len // 2, dtype=np.float32), x])
    outs: Dict[str, List[np.ndarray]] = {"note": [], "onset": []}
    for i in range(0, x.shape[0], hop):
        w = x[i:i + AUDIO_N_SAMPLES]
        if len(w) < AUDIO_N_SAMPLES:
            w = np.pad(w, (0, AUDIO_N_SAMPLES - len(w)))
        res = sess.run([want["note"], want["onset"]], {in_name: w.reshape(1, -1, 1)})
        outs["note"].append(res[0])
        outs["onset"].append(res[1])
    n_olap = N_OVERLAP_FRAMES // 2
    n_keep = int(math.floor(n_orig * (ANNOT_FPS / float(SR))))
    if n_keep <= 0:
        raise ShowtimeError("no usable audio in the clip (under about 12 ms of sound)", hint="x-ray reads the notes from the clip's sound: pass a clip with audio")
    out = {}
    for k, parts in outs.items():
        o = np.concatenate(parts)[:, n_olap:-n_olap, :]
        out[k] = o.reshape(o.shape[0] * o.shape[1], o.shape[2])[:n_keep, :]
    return out


# ------------------------------------------------------------------ note creation (port of basic_pitch.note_creation)

def _inferred_onsets(onsets: np.ndarray, frames: np.ndarray, n_diff: int = 2) -> np.ndarray:
    diffs = []
    for n in range(1, n_diff + 1):
        app = np.concatenate([np.zeros((n, frames.shape[1])), frames])
        diffs.append(app[n:, :] - app[:-n, :])
    d = np.min(diffs, axis=0)
    d[d < 0] = 0
    d[:n_diff, :] = 0
    mx = np.max(d)
    d = np.max(onsets) * d / mx if mx > 0 else d
    return np.max([onsets, d], axis=0)


def frame_times(n_frames: int) -> np.ndarray:
    """basic_pitch.note_creation.model_frames_to_time: frame index -> seconds (with its per-window drift correction)."""
    t = np.arange(n_frames) * FFT_HOP / float(SR)
    win = np.floor(np.arange(n_frames) / ANNOT_N_FRAMES)
    offset = FRAME_S * (ANNOT_N_FRAMES - AUDIO_N_SAMPLES / float(FFT_HOP)) + 0.0018
    return t - offset * win


def notes_from_output(frames: np.ndarray, onsets: np.ndarray, *, onset_thresh: float = ONSET_THRESH,
                      frame_thresh: float = FRAME_THRESH, min_note_len: int = MIN_NOTE_LEN, infer_onsets: bool = True,
                      melodia_trick: bool = True, energy_tol: int = ENERGY_TOL) -> List[Tuple[int, int, int, float]]:
    """basic_pitch output_to_notes_polyphonic: [(start_frame, end_frame, midi, amplitude)] (no frequency limits)."""
    from scipy import signal
    frames = np.array(frames, dtype=np.float64)
    onsets = np.array(onsets, dtype=np.float64)
    n_frames = frames.shape[0]
    if infer_onsets:
        onsets = _inferred_onsets(onsets, frames)
    peak = np.zeros(onsets.shape)
    pk = signal.argrelmax(onsets, axis=0)
    peak[pk] = onsets[pk]
    oi = np.where(peak >= onset_thresh)
    o_t = oi[0][::-1]
    o_f = oi[1][::-1]
    rem = frames.copy()
    events: List[Tuple[int, int, int, float]] = []
    for start, fi in zip(o_t, o_f):
        if start >= n_frames - 1:
            continue
        i = start + 1
        k = 0
        while i < n_frames - 1 and k < energy_tol:
            k = k + 1 if rem[i, fi] < frame_thresh else 0
            i += 1
        i -= k
        if i - start <= min_note_len:
            continue
        rem[start:i, fi] = 0
        if fi < MAX_FREQ_IDX:
            rem[start:i, fi + 1] = 0
        if fi > 0:
            rem[start:i, fi - 1] = 0
        events.append((int(start), int(i), int(fi) + MIDI_OFFSET, float(np.mean(frames[start:i, fi]))))
    if melodia_trick:
        shape = rem.shape
        while np.max(rem) > frame_thresh:
            i_mid, fi = np.unravel_index(np.argmax(rem), shape)
            rem[i_mid, fi] = 0
            i = i_mid + 1
            k = 0
            while i < n_frames - 1 and k < energy_tol:
                k = k + 1 if rem[i, fi] < frame_thresh else 0
                rem[i, fi] = 0
                if fi < MAX_FREQ_IDX:
                    rem[i, fi + 1] = 0
                if fi > 0:
                    rem[i, fi - 1] = 0
                i += 1
            i_end = i - 1 - k
            i = i_mid - 1
            k = 0
            while i > 0 and k < energy_tol:
                k = k + 1 if rem[i, fi] < frame_thresh else 0
                rem[i, fi] = 0
                if fi < MAX_FREQ_IDX:
                    rem[i, fi + 1] = 0
                if fi > 0:
                    rem[i, fi - 1] = 0
                i -= 1
            i_start = i + 1 + k
            if i_end - i_start <= min_note_len:
                continue
            events.append((int(i_start), int(i_end), int(fi) + MIDI_OFFSET, float(np.mean(frames[i_start:i_end, fi]))))
    return events


def detect_notes(audio: np.ndarray, t_offset: float = 0.0) -> List[Dict[str, Any]]:
    """Audio -> notes [{t, end, pitch, velocity, confidence}] sorted by time (times + t_offset)."""
    out = infer(audio)
    ev = notes_from_output(out["note"], out["onset"])
    times = frame_times(out["note"].shape[0])
    onset = out["onset"]
    notes = []
    for s, e, p, amp in ev:
        lo, hi = max(0, s - 2), min(onset.shape[0], s + 3)
        conf = float(np.max(onset[lo:hi, p - MIDI_OFFSET])) if hi > lo else 0.0
        notes.append({"t": float(times[s]) + t_offset, "end": float(times[min(e, len(times) - 1)]) + t_offset, "pitch": p,
                      "velocity": float(min(1.0, max(0.0, amp))), "confidence": float(min(1.0, max(0.0, conf)))})
    notes.sort(key=lambda n: (n["t"], n["pitch"]))
    return notes


# ------------------------------------------------------------------ voices

def clusters(notes: Sequence[Dict[str, Any]], gap: float = CLUSTER_S) -> List[List[int]]:
    """Note indexes grouped by onset: a note joins the group when it starts within `gap` of the group's first note."""
    order = sorted(range(len(notes)), key=lambda i: notes[i]["t"])
    out: List[List[int]] = []
    for i in order:
        if out and notes[i]["t"] - notes[out[-1][0]]["t"] <= gap:
            out[-1].append(i)
        else:
            out.append([i])
    return out


def voices(notes: Sequence[Dict[str, Any]]) -> Dict[str, List[int]]:
    """melody = at each onset the loudest note from E4 up with confidence >= 0.4; bass = the lowest note under the melody
    (under E4 where the onset has no melody note)."""
    mel: List[int] = []
    bass: List[int] = []
    for grp in clusters(notes):
        cand = [i for i in grp if notes[i]["pitch"] >= MELODY_MIN_PITCH and notes[i]["confidence"] >= MELODY_MIN_CONF]
        top = None
        if cand:
            top = max(cand, key=lambda i: (notes[i]["velocity"], notes[i]["pitch"]))
            mel.append(top)
        ref = notes[top]["pitch"] if top is not None else MELODY_MIN_PITCH
        low = [i for i in grp if notes[i]["pitch"] < ref and notes[i]["confidence"] >= BASS_MIN_CONF]
        if low:
            bass.append(min(low, key=lambda i: (notes[i]["pitch"], -notes[i]["velocity"])))
    return {"melody": sorted(mel), "bass": sorted(bass)}


# ------------------------------------------------------------------ tempo, quantize

def _onset_times(notes: Sequence[Dict[str, Any]]) -> List[float]:
    return [float(np.mean([notes[i]["t"] for i in g])) for g in clusters(notes)]


def tempo_map(onsets: Sequence[float], sigma: float = 2.5, grid: float = 0.5) -> Dict[str, Any]:
    """A smooth tempo map: beats from the median inter-onset interval (folded to 60..180 bpm), each onset put on the
    nearest `grid` (half beat; a quarter for drums) after the one before it, then a local weighted linear fit of beat against time (gaussian
    weights, `sigma` seconds) evaluated at the onsets. Never snaps a scroll to the last note: use `beat_of`.
    Returns {"bpm", "map": [[t, beat], ...]} (beat 0 at the first onset; knots at the onsets and 1 s past each end)."""
    t = np.asarray(sorted(onsets), dtype=float)
    if len(t) < 3:
        bpm = 100.0
        t0 = float(t[0]) if len(t) else 0.0
        return {"bpm": bpm, "map": [[round(t0, 4), 0.0], [round(t0 + 60.0 / bpm * 4, 4), 4.0]]}
    ioi = np.diff(t)
    ioi = ioi[(ioi >= 0.06) & (ioi <= 3.0)]
    period = float(np.median(ioi)) if len(ioi) else 0.5
    while period < 60.0 / 180.0:
        period *= 2
    while period > 1.0:
        period /= 2
    slope = np.full(len(t), period)                  # seconds per beat, per onset
    beats = np.zeros(len(t))
    for _ in range(3):
        beats = np.zeros(len(t))
        for i in range(1, len(t)):
            step = max(grid, round((t[i] - t[i - 1]) / slope[i - 1] / grid) * grid)
            beats[i] = beats[i - 1] + step
        sm = np.zeros(len(t))
        new_slope = np.zeros(len(t))
        for i in range(len(t)):
            w = np.exp(-0.5 * ((t - t[i]) / sigma) ** 2)
            sw = w.sum()
            mt = (w * t).sum() / sw
            mb = (w * beats).sum() / sw
            vt = (w * (t - mt) ** 2).sum()
            b = (w * (t - mt) * (beats - mb)).sum() / vt if vt > 1e-9 else 1.0 / period
            b = b if b > 1e-6 else 1.0 / period
            sm[i] = mb + b * (t[i] - mt)
            new_slope[i] = 1.0 / b
        sm = np.maximum.accumulate(sm)
        slope = np.clip(new_slope, period * 0.5, period * 2.0)
        beats = sm
    beats = beats - beats[0]
    knots_t = list(t)
    knots_b = list(beats)
    knots_t.insert(0, t[0] - 1.0)
    knots_b.insert(0, beats[0] - 1.0 / slope[0])
    knots_t.append(t[-1] + 1.0)
    knots_b.append(beats[-1] + 1.0 / slope[-1])
    # strictly increasing beats (np.interp needs it for the inverse)
    kb = np.maximum.accumulate(np.asarray(knots_b))
    for i in range(1, len(kb)):
        if kb[i] <= kb[i - 1]:
            kb[i] = kb[i - 1] + 1e-4
    bpm = 60.0 / float(np.median(slope))
    return {"bpm": round(bpm, 2), "map": [[round(float(a), 4), round(float(b), 4)] for a, b in zip(knots_t, kb)]}


def beat_of(t: Any, tmap: Sequence[Sequence[float]]) -> Any:
    """Time (s) -> beat on the smooth map (linear between knots, extrapolated at the ends with the end slopes)."""
    mt = np.array([k[0] for k in tmap], dtype=float)
    mb = np.array([k[1] for k in tmap], dtype=float)
    x = np.asarray(t, dtype=float)
    y = np.interp(x, mt, mb)
    if len(mt) >= 2:
        s0 = (mb[1] - mb[0]) / (mt[1] - mt[0])
        s1 = (mb[-1] - mb[-2]) / (mt[-1] - mt[-2])
        y = np.where(x < mt[0], mb[0] + (x - mt[0]) * s0, y)
        y = np.where(x > mt[-1], mb[-1] + (x - mt[-1]) * s1, y)
    return float(y) if np.ndim(t) == 0 else y


def time_of(beat: Any, tmap: Sequence[Sequence[float]]) -> Any:
    """Beat -> time (s), the inverse of beat_of."""
    mt = np.array([k[0] for k in tmap], dtype=float)
    mb = np.array([k[1] for k in tmap], dtype=float)
    x = np.asarray(beat, dtype=float)
    y = np.interp(x, mb, mt)
    if len(mt) >= 2:
        s0 = (mt[1] - mt[0]) / (mb[1] - mb[0])
        s1 = (mt[-1] - mt[-2]) / (mb[-1] - mb[-2])
        y = np.where(x < mb[0], mt[0] + (x - mb[0]) * s0, y)
        y = np.where(x > mb[-1], mt[-1] + (x - mb[-1]) * s1, y)
    return float(y) if np.ndim(beat) == 0 else y


def quantize(notes: Sequence[Dict[str, Any]], tmap: Sequence[Sequence[float]]) -> List[Dict[str, Any]]:
    """Each note's start and length in beats, rounded to eighths (half beats), never shorter than an eighth."""
    out = []
    for i, n in enumerate(notes):
        b0 = beat_of(n["t"], tmap)
        b1 = beat_of(n["end"], tmap)
        beat = max(0.0, round(b0 * 2.0) / 2.0)
        dur = max(0.5, round((b1 - b0) * 2.0) / 2.0)
        out.append({"i": i, "beat": beat, "dur_beats": dur})
    return out


# ------------------------------------------------------------------ key and chords

def _pc_weights(notes: Sequence[Dict[str, Any]]) -> np.ndarray:
    pcw = np.zeros(12)
    for n in notes:
        pcw[n["pitch"] % 12] += max(0.05, n["end"] - n["t"])
    return pcw


def detect_key(notes: Sequence[Dict[str, Any]]) -> Optional[str]:
    """Krumhansl-Schmuckler on duration-weighted pitch classes: "A minor", "C major" (None without notes)."""
    pcw = _pc_weights(notes)
    if pcw.sum() <= 0:
        return None
    best = (-2.0, "")
    for mode, prof, names in (("major", KS_MAJOR, KEY_NAMES_MAJOR), ("minor", KS_MINOR, KEY_NAMES_MINOR)):
        p = np.asarray(prof)
        for tonic in range(12):
            r = _corr(pcw, np.roll(p, tonic))
            if r > best[0]:
                best = (r, "%s %s" % (names[tonic], mode))
    return best[1]


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    d = math.sqrt(float((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / d) if d > 0 else 0.0


def chords(notes: Sequence[Dict[str, Any]], tmap: Sequence[Sequence[float]], per_beats: float = 1.0) -> List[Dict[str, Any]]:
    """Per beat: the template (major, minor, 7, dim) best matching the pitch-class energy of the notes sounding in it;
    equal neighbours merge. A beat with fewer than two pitch classes of substance has no chord."""
    if not notes:
        return []
    b_end = max(beat_of(n["end"], tmap) for n in notes)
    b_start = min(beat_of(n["t"], tmap) for n in notes)
    nb = beat_of([n["t"] for n in notes], tmap)
    ne = beat_of([n["end"] for n in notes], tmap)
    out: List[Dict[str, Any]] = []
    b = math.floor(max(0.0, b_start) / per_beats) * per_beats
    while b < b_end:
        e = np.zeros(12)
        for k, n in enumerate(notes):
            ov = min(ne[k], b + per_beats) - max(nb[k], b)
            if ov > 0:
                e[n["pitch"] % 12] += ov * (0.3 + n["velocity"])
        name = None
        if e.sum() > 0:
            strong = (e >= 0.15 * e.max()).sum()
            if strong >= 2:
                best = (-1.0, None)
                for root in range(12):
                    for suffix, tpl in CHORD_TEMPLATES:
                        v = np.zeros(12)
                        for s in tpl:
                            v[(root + s) % 12] = 1.0
                        sc = float(v @ e) / (math.sqrt(float(v @ v)) * math.sqrt(float(e @ e))) - (0.04 if suffix in ("7", "dim") else 0.0)
                        if sc > best[0]:
                            best = (sc, CHORD_NAMES[root] + suffix)
                name = best[1]
        if name:
            t0, t1 = float(time_of(b, tmap)), float(time_of(b + per_beats, tmap))
            if out and out[-1]["name"] == name and abs(out[-1]["end"] - t0) < 1e-6:
                out[-1]["end"] = round(t1, 4)
            else:
                out.append({"t": round(t0, 4), "end": round(t1, 4), "name": name})
        b += per_beats
    return out


# ------------------------------------------------------------------ guitar

def guitar_map(notes: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Standard tuning E2 A2 D3 G3 B3 E4: each note on the lowest fret that fits, open position (frets 0-4) first, and
    not on a string that is still ringing another note. Right hand p for strings 6-4, i/m/a for 3/2/1; `lh` is the
    left-hand finger (0 open, 1-4 from the hand's lowest fret in the neighbourhood). Notes outside the neck are left out."""
    busy = [-1.0] * 7                                  # string -> time its last note ends
    rows: List[Dict[str, Any]] = []
    for i, n in enumerate(notes):
        cands = [(s + 1, n["pitch"] - GUITAR_OPEN[s]) for s in range(6) if 0 <= n["pitch"] - GUITAR_OPEN[s] <= GUITAR_FRETS]
        if not cands:
            continue
        free = [c for c in cands if busy[c[0]] <= n["t"] + 0.02]
        pool = free or cands
        open_pos = [c for c in pool if c[1] <= 4]
        pool = open_pos or pool
        string, fret = min(pool, key=lambda c: (c[1], c[0]))
        busy[string] = n["end"]
        rows.append({"i": i, "string": string, "fret": fret, "finger": "p" if string >= 4 else {3: "i", 2: "m", 1: "a"}[string]})
    for k, r in enumerate(rows):
        near = [q["fret"] for q in rows[max(0, k - 3):k + 4] if q["fret"] > 0]
        base = min(near) if near else 1
        r["lh"] = 0 if r["fret"] == 0 else int(min(4, max(1, r["fret"] - base + 1)))
    return rows


def guess_instrument(notes: Sequence[Dict[str, Any]]) -> str:
    """auto: a music box lives in the high register (median pitch from C5 up); everything else reads as piano.
    A guitar is only chosen when asked for."""
    if not notes:
        return "piano"
    med = float(np.median([n["pitch"] for n in notes]))
    return "musicbox" if med >= 72 else "piano"


# ------------------------------------------------------------------ MIDI

def _vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(reversed(out))


def midi_bytes(notes: Sequence[Dict[str, Any]], bpm: float, ppq: int = 480, channel: int = 0) -> bytes:
    """A format-0 standard MIDI file: one tempo, notes at their real times (ticks = seconds * bpm / 60 * ppq)."""
    bpm = max(20.0, float(bpm))
    k = bpm / 60.0 * ppq
    ev: List[Tuple[int, int, bytes]] = []
    for n in notes:
        a = int(round(n["t"] * k))
        b = max(a + 1, int(round(n["end"] * k)))
        vel = int(min(127, max(1, round(n["velocity"] * 127))))
        ev.append((a, 1, bytes([0x90 | channel, n["pitch"] & 0x7F, vel])))
        ev.append((b, 0, bytes([0x80 | channel, n["pitch"] & 0x7F, 0])))
    ev.sort(key=lambda e: (e[0], e[1]))
    trk = bytearray()
    trk += b"\x00\xff\x51\x03" + struct.pack(">I", int(round(60000000.0 / bpm)))[1:]
    trk += b"\x00\xff\x58\x04\x04\x02\x18\x08"
    last = 0
    for tick, _, data in ev:
        trk += _vlq(tick - last) + data
        last = tick
    trk += b"\x00\xff\x2f\x00"
    return b"MThd" + struct.pack(">IHHH", 6, 0, 1, ppq) + b"MTrk" + struct.pack(">I", len(trk)) + bytes(trk)


def write_midi(path: Any, notes: Sequence[Dict[str, Any]], bpm: float) -> Path:
    p = Path(path)
    p.write_bytes(midi_bytes(notes, bpm))
    return p


# ------------------------------------------------------------------ MusicXML

DIV = 2                                                # divisions per quarter: an eighth is 1
MEASURE = 4 * DIV
_TYPES = {1: ("eighth", False), 2: ("quarter", False), 3: ("quarter", True), 4: ("half", False), 6: ("half", True),
          8: ("whole", False)}
_STEP = {0: ("C", 0), 1: ("C", 1), 2: ("D", 0), 3: ("D", 1), 4: ("E", 0), 5: ("F", 0), 6: ("F", 1), 7: ("G", 0), 8: ("G", 1),
         9: ("A", 0), 10: ("A", 1), 11: ("B", 0)}
_FIFTHS_MAJOR = {"C": 0, "G": 1, "D": 2, "A": 3, "E": 4, "B": 5, "F#": 6, "Db": -5, "Ab": -4, "Eb": -3, "Bb": -2, "F": -1}


def key_fifths(key: Optional[str]) -> int:
    if not key:
        return 0
    name, mode = key.split()
    if mode == "major":
        return _FIFTHS_MAJOR.get(name, 0)
    names = KEY_NAMES_MAJOR
    try:
        rel = names[(KEY_NAMES_MINOR.index(name) + 3) % 12]
    except ValueError:
        return 0
    return _FIFTHS_MAJOR.get(rel, 0)


def _pieces(d: int) -> List[int]:
    out = []
    for p in (8, 6, 4, 3, 2, 1):
        while d >= p:
            out.append(p)
            d -= p
    return out


def _note_xml(pitches: Sequence[int], dur: int, staff: int, tie_stop: bool, tie_start: bool, two_staves: bool) -> str:
    typ, dot = _TYPES[dur]
    xs = []
    for k, p in enumerate(pitches):
        step, alter = _STEP[p % 12]
        s = "<note>"
        if k:
            s += "<chord/>"
        s += "<pitch><step>%s</step>%s<octave>%d</octave></pitch>" % (step, "<alter>%d</alter>" % alter if alter else "", p // 12 - 1)
        s += "<duration>%d</duration>" % dur
        if tie_stop:
            s += '<tie type="stop"/>'
        if tie_start:
            s += '<tie type="start"/>'
        s += "<voice>%d</voice><type>%s</type>%s" % (staff, typ, "<dot/>" if dot else "")
        if two_staves:
            s += "<staff>%d</staff>" % staff
        if tie_stop or tie_start:
            s += "<notations>%s%s</notations>" % ('<tied type="stop"/>' if tie_stop else "", '<tied type="start"/>' if tie_start else "")
        xs.append(s + "</note>")
    return "".join(xs)


def _rest_xml(dur: int, staff: int, two_staves: bool) -> str:
    typ, dot = _TYPES[dur]
    return "<note><rest/><duration>%d</duration><voice>%d</voice><type>%s</type>%s%s</note>" % (
        dur, staff, typ, "<dot/>" if dot else "", "<staff>%d</staff>" % staff if two_staves else "")


def _staff_events(notes: Sequence[Dict[str, Any]], quant: Sequence[Dict[str, Any]], idxs: Sequence[int]) -> List[Tuple[int, int, List[int]]]:
    """[(start, duration, [pitches])] in divisions, one entry per onset, each cut at the next onset."""
    by: Dict[int, Dict[int, int]] = {}
    for i in idxs:
        q = quant[i]
        st = int(round(q["beat"] * DIV))
        d = max(1, int(round(q["dur_beats"] * DIV)))
        slot = by.setdefault(st, {})
        slot[notes[i]["pitch"]] = max(slot.get(notes[i]["pitch"], 0), d)
    starts = sorted(by)
    ev = []
    for k, st in enumerate(starts):
        d = min(by[st].values())
        if k + 1 < len(starts):
            d = min(d, starts[k + 1] - st)
        ev.append((st, max(1, d), sorted(by[st])))
    return ev


def _staff_measures(ev: Sequence[Tuple[int, int, List[int]]], n_meas: int, staff: int, two: bool) -> List[str]:
    """XML of each measure for one staff: notes (tied across bar lines and into unwritable lengths) and rests."""
    items: List[Tuple[int, int, Optional[List[int]], bool, bool]] = []     # start, dur, pitches, tie_stop, tie_start
    pos = 0

    def add(st: int, d: int, pitches: Optional[List[int]]) -> None:
        cuts = []
        while d > 0:
            room = MEASURE - (st % MEASURE)
            take = min(d, room)
            for p in _pieces(take):
                cuts.append((st, p))
                st += p
            d -= take
        for k, (s, p) in enumerate(cuts):
            items.append((s, p, pitches, pitches is not None and k > 0, pitches is not None and k < len(cuts) - 1))

    for st, d, ps in ev:
        if st > pos:
            add(pos, st - pos, None)
        add(st, d, ps)
        pos = st + d
    if pos < n_meas * MEASURE:
        add(pos, n_meas * MEASURE - pos, None)
    meas = ["" for _ in range(n_meas)]
    for st, d, ps, ts, tt in items:
        m = st // MEASURE
        if m < n_meas:
            meas[m] += _note_xml(ps, d, staff, ts, tt, two) if ps else _rest_xml(d, staff, two)
    return meas


def musicxml(notes: Sequence[Dict[str, Any]], quant: Sequence[Dict[str, Any]], bpm: float, key: Optional[str],
             bass: Sequence[int] = (), two_staves: bool = False, title: str = "x-ray notes") -> str:
    """A valid score-partwise MusicXML 3.1 file, one part. With `two_staves` (piano) the `bass` notes go to the lower staff."""
    bset = set(bass) if two_staves else set()
    upper = [i for i in range(len(notes)) if i not in bset]
    lower = sorted(bset)
    ends = [int(round((q["beat"] + q["dur_beats"]) * DIV)) for q in quant] or [MEASURE]
    n_meas = max(1, int(math.ceil(max(ends) / float(MEASURE))))
    up = _staff_measures(_staff_events(notes, quant, upper), n_meas, 1, two_staves)
    lo = _staff_measures(_staff_events(notes, quant, lower), n_meas, 2, True) if two_staves else None
    x = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">',
         '<score-partwise version="3.1"><work><work-title>%s</work-title></work>' % escape(title),
         '<identification><encoding><software>showtime xray notes</software></encoding></identification>',
         '<part-list><score-part id="P1"><part-name>%s</part-name></score-part></part-list><part id="P1">' % ("Piano" if two_staves else "Notes")]
    for m in range(n_meas):
        x.append('<measure number="%d">' % (m + 1))
        if m == 0:
            x.append('<attributes><divisions>%d</divisions><key><fifths>%d</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time>'
                     % (DIV, key_fifths(key)))
            if two_staves:
                x.append('<staves>2</staves><clef number="1"><sign>G</sign><line>2</line></clef><clef number="2"><sign>F</sign><line>4</line></clef>')
            else:
                x.append('<clef><sign>G</sign><line>2</line></clef>')
            x.append('</attributes><direction placement="above"><direction-type><metronome><beat-unit>quarter</beat-unit>'
                     '<per-minute>%d</per-minute></metronome></direction-type><sound tempo="%d"/></direction>' % (round(bpm), round(bpm)))
        x.append(up[m])
        if lo is not None:
            x.append("<backup><duration>%d</duration></backup>" % MEASURE)
            x.append(lo[m])
        x.append("</measure>")
    x.append("</part></score-partwise>")
    return "".join(x)


# ------------------------------------------------------------------ check picture

def check_sheet(doc: Dict[str, Any], audio: np.ndarray, t0: float, dest: Path, width: int = 1600) -> Path:
    """A piano roll over the waveform: one bar per note (melody in orange, bass in blue, the rest grey), a tick at each onset."""
    from PIL import Image, ImageDraw
    notes = doc["notes"]
    dur = len(audio) / float(SR)
    t1 = t0 + max(dur, 0.1)
    pitches = [n["pitch"] for n in notes] or [60]
    lo, hi = max(21, min(pitches) - 2), min(108, max(pitches) + 2)
    wave_h, roll_h, pad = 140, max(240, (hi - lo + 1) * 9), 28
    H = pad + wave_h + 8 + roll_h + 24
    img = Image.new("RGB", (width, H), (18, 20, 26))
    d = ImageDraw.Draw(img)

    def px(t: float) -> int:
        return int(round((t - t0) / (t1 - t0) * (width - 1)))

    mid = pad + wave_h // 2
    n_px = width
    seg = max(1, len(audio) // n_px)
    for x in range(n_px):
        s = audio[x * seg:(x + 1) * seg]
        if len(s):
            a = int(float(np.max(np.abs(s))) * (wave_h / 2 - 2) / max(1e-6, float(np.max(np.abs(audio))) if len(audio) else 1.0))
            d.line([(x, mid - a), (x, mid + a)], fill=(84, 112, 150))
    top = pad + wave_h + 8
    row = roll_h / float(hi - lo + 1)
    for p in range(lo, hi + 1):
        y = top + (hi - p) * row
        if p % 12 == 0:
            d.line([(0, y + row), (width, y + row)], fill=(46, 50, 62))
            d.text((3, y + row - 11), note_name(p), fill=(120, 128, 150))
    mel = set(doc["voices"]["melody"])
    bas = set(doc["voices"]["bass"])
    for n in notes:
        col = (255, 150, 40) if n["i"] in mel else (80, 160, 255) if n["i"] in bas else (150, 156, 170)
        x0, x1 = px(n["t"]), max(px(n["t"]) + 2, px(n["end"]))
        y = top + (hi - n["pitch"]) * row
        d.rectangle([x0, y, x1, y + max(2, row - 1)], fill=col)
        d.line([(x0, pad), (x0, pad + wave_h)], fill=(255, 90, 90))
    d.text((8, 6), "%s: %d notes, %s, %.0f bpm, key %s" % (doc["source"]["file"], len(notes), doc.get("instrument", ""),
                                                           doc["tempo"]["bpm"], doc.get("key") or "-"), fill=(230, 232, 240))
    for s in range(int(math.ceil(t0)), int(t1) + 1):
        d.text((px(s) + 2, H - 16), "%ds" % s, fill=(130, 136, 154))
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(dest), quality=88)
    return dest


# ------------------------------------------------------------------ the command

def analyze(clip: Any, out_dir: Any, *, t_from: float = 0.0, t_to: Optional[float] = None, instrument: str = "auto") -> Dict[str, Any]:
    """Write notes.json, notes.mid, notes.musicxml and check-notes.jpg to `out_dir`; returns the notes.json dict."""
    from . import xray
    clip = Path(clip)
    if instrument not in INSTRUMENTS:
        raise ShowtimeError("--instrument is one of %s (got %r)" % ("|".join(INSTRUMENTS), instrument))
    if not clip.is_file():
        raise ShowtimeError("clip not found: %s" % clip, hint="pass the video you filmed, or the recording (a WAV)")
    if t_to is not None and t_to <= t_from:
        raise ShowtimeError("--to (%g) must be after --from (%g)" % (t_to, t_from))
    if instrument == "drums":
        from . import xray_drums
        return xray_drums.analyze(clip, out_dir, t_from=t_from, t_to=t_to)
    out = Path(out_dir)
    src = xray._source_info(clip)
    if not src.pop("has_audio"):
        raise ShowtimeError("%s has no sound to read notes from" % clip.name, hint="x-ray reads the notes from the clip's audio")
    out.mkdir(parents=True, exist_ok=True)
    t_from = max(0.0, t_from)
    audio = load_audio(clip, t_from, t_to)
    notes = detect_notes(audio, t_from)
    if instrument == "auto":
        instrument = guess_instrument(notes)
    fps = float(src["fps"])
    for i, n in enumerate(notes):
        n.update({"i": i, "frame": xray.frame_of(n["t"], fps), "name": note_name(n["pitch"])})
    onsets = _onset_times(notes)
    tm = tempo_map(onsets)
    quant = quantize(notes, tm["map"])
    vo = voices(notes)
    key = detect_key(notes)
    rows = [{"i": n["i"], "t": round(n["t"], 4), "end": round(n["end"], 4), "frame": n["frame"], "pitch": n["pitch"],
             "name": n["name"], "velocity": round(n["velocity"], 3), "confidence": round(n["confidence"], 3)} for n in notes]
    doc: Dict[str, Any] = {
        "schema": SCHEMA, "source": src, "engine": ENGINE, "instrument": instrument,
        "range": {"from": t_from, "to": t_to}, "notes": rows,
        "tempo": tm, "key": key, "chords": chords(notes, tm["map"]), "voices": vo,
        "quantized": [{"i": q["i"], "beat": q["beat"], "dur_beats": q["dur_beats"]} for q in quant]}
    if instrument == "guitar":
        doc["guitar"] = guitar_map(notes)
    write_json(out / "notes.json", doc)
    write_midi(out / "notes.mid", notes, tm["bpm"])
    xml = musicxml(notes, quant, tm["bpm"], key, vo["bass"], two_staves=(instrument == "piano"), title=clip.stem)
    (out / "notes.musicxml").write_text(xml, encoding="utf-8")
    check_sheet(doc, audio, t_from, out / "check-notes.jpg")
    return doc

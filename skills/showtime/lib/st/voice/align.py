"""Word timings for any audio + its known script.

Methods (auto picks the first that applies):

  ctc      English. wav2vec2-base-960h (ONNX, 95 MB quantized, fetched on first use)
           gives per-frame letter probabilities; a Viterbi pass forces the
           script's letters through them. ~20 ms resolution.
  tts      Any language Kokoro speaks. The script is synthesized with Kokoro
           (exact word times), then that reference is warped onto the audio
           with dynamic time warping over MFCC features. No extra download.
  whisper  faster-whisper word timestamps (small.en for English, large-v3-turbo
           otherwise), mapped back onto the script's words by sequence
           alignment, so spelling and punctuation stay the script's.
  even     Last resort: words spread over the voiced regions by length.

Every method ends with energy snapping: word edges move to where the voice
actually starts and stops (10 ms frames, threshold set from the noise floor).
The script is authoritative: output words are exactly the script's words.
"""
from __future__ import annotations

import difflib
import os
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from ..common import ShowtimeError, debug, info, warn
from . import audio_io as aio
from . import models
from .textnorm import Token, base_lang, en_number, normalize_tokens, plain_text, tokenize

PathLike = Union[str, "os.PathLike[str]"]
METHODS = ("auto", "ctc", "tts", "whisper", "even")


# --------------------------------------------------------------------------
# Energy snapping
# --------------------------------------------------------------------------

def _voiced(x: np.ndarray, sr: int, hop: float = 0.01) -> np.ndarray:
    db = aio.frame_db(x, sr, hop)
    if db.size == 0:
        return np.zeros(0, dtype=bool)
    floor = float(np.percentile(db, 10))
    thr = max(-45.0, min(floor + 15.0, -25.0))
    return db > thr


def refine_onsets(words: List[Dict[str, Any]], x: np.ndarray, sr: int, before: float = 0.08,
                  after: float = 0.04) -> List[Dict[str, Any]]:
    """Move a word start onto a silence-to-voice transition when one lies
    within [start - before, start + after] (words after a pause or a stop
    consonant); starts inside continuous voicing are left alone."""
    hop = 0.01
    v = _voiced(x, sr, hop)
    n = len(v)
    out = [dict(w) for w in words]
    for i, w in enumerate(out):
        s = float(w["start"])
        lo = max(1, int((s - before) / hop))
        if i > 0:
            lo = max(lo, int(np.ceil(out[i - 1]["end"] / hop)))
        hi = min(n - 1, int((s + after) / hop))
        best = None
        for k in range(lo, hi + 1):
            if v[k] and not v[k - 1] and (best is None or abs(k * hop - s) < abs(best * hop - s)):
                best = k
        if best is not None:
            w["start"] = round(best * hop, 3)
            if w["end"] < w["start"] + 0.03:
                w["end"] = round(w["start"] + 0.03, 3)
    return out


def snap(words: List[Dict[str, Any]], x: np.ndarray, sr: int, grow: bool = True,
         max_back: float = 0.15, max_fwd: float = 0.25, trim_starts: bool = True) -> List[Dict[str, Any]]:
    """Move word edges onto voice onsets/offsets.

    Always trims silence inside a word's span (a phrase-final word whose
    timing runs into the following pause). With grow=True, starts may move
    earlier (<= max_back) and ends later (<= max_fwd) over voiced frames,
    never crossing a neighbour.
    """
    hop = 0.01
    v = _voiced(x, sr, hop)
    n = len(v)
    if n == 0 or not words:
        return words
    out = [dict(w) for w in words]
    for i, w in enumerate(out):
        s, e = float(w["start"]), float(w["end"])
        fs, fe = int(s / hop), max(int(s / hop) + 1, int(np.ceil(e / hop)))
        fs, fe = min(fs, n), min(fe, n)
        seg = v[fs:fe]
        if seg.any():
            idx = np.flatnonzero(seg)
            s2, e2 = (fs + idx[0]) * hop, (fs + idx[-1] + 1) * hop
            if not trim_starts:
                s2 = s
            # keep a short tail: unvoiced finals (s, t, f) sit under the threshold
            e2 = min(e, e2 + 0.04)
        else:
            s2, e2 = s, e
        if grow:
            lo = out[i - 1]["end"] if i > 0 else 0.0
            k = int(round(s2 / hop))
            while k - 1 >= 0 and v[k - 1] and (k - 1) * hop >= max(lo, s2 - max_back):
                k -= 1
            s2 = k * hop
        w["start"], w["end"] = s2, max(e2, s2 + 0.03)
    if grow:
        for i, w in enumerate(out):
            nxt = out[i + 1]["start"] if i + 1 < len(out) else n * hop
            k = int(round(w["end"] / hop))
            while k < n and v[k] and (k + 1) * hop <= min(nxt, w["end"] + max_fwd):
                k += 1
            w["end"] = max(w["end"], min(k * hop, nxt))
    prev = 0.0
    for w in out:
        w["start"] = round(max(w["start"], prev), 3)
        w["end"] = round(max(w["end"], w["start"] + 0.03), 3)
        prev = w["end"]
    return out


# --------------------------------------------------------------------------
# CTC forced alignment (English)
# --------------------------------------------------------------------------

_W2V = {"sess": None, "vocab": None}


def _w2v_session(allow_download: bool = True):
    if _W2V["sess"] is not None:
        return _W2V["sess"], _W2V["vocab"]
    d = models.ensure_aligner(allow_download)
    if d is None:
        return None, None
    import json
    import onnxruntime as rt
    so = rt.SessionOptions()
    so.log_severity_level = 3
    thr = os.environ.get("SHOWTIME_THREADS")
    if thr and thr.isdigit():
        so.intra_op_num_threads = int(thr)
    _W2V["sess"] = rt.InferenceSession(str(d / models.aligner_model_name()), sess_options=so,
                                       providers=["CPUExecutionProvider"])
    _W2V["vocab"] = json.loads((d / "vocab.json").read_text(encoding="utf-8"))
    return _W2V["sess"], _W2V["vocab"]


def _emissions(x16: np.ndarray, sess, chunk: float = 20.0, ctx: float = 1.0) -> Tuple[np.ndarray, float]:
    """Log-probabilities (frames x 32) at 20 ms per frame, computed in
    overlapping chunks so memory stays flat for long files."""
    sr = 16000
    x = (x16 - x16.mean()) / (x16.std() + 1e-7)
    hop = 320
    n_frames = max(1, len(x) // hop)
    out = np.zeros((n_frames, 32), dtype=np.float32)
    step = int(chunk * sr)
    c = int(ctx * sr)
    name = sess.get_inputs()[0].name
    pos = 0
    while pos < len(x):
        a, b = max(0, pos - c), min(len(x), pos + step + c)
        seg = x[a:b].astype(np.float32)
        if len(seg) < 400:
            seg = np.pad(seg, (0, 400 - len(seg)))
        logits = sess.run(None, {name: seg[None, :]})[0][0]
        lp = logits - logits.max(axis=1, keepdims=True)
        lp = lp - np.log(np.exp(lp).sum(axis=1, keepdims=True))
        f0 = (pos - a) // hop
        keep_from, keep_to = pos // hop, min(n_frames, (pos + step) // hop)
        m = keep_to - keep_from
        take = lp[f0:f0 + m]
        out[keep_from:keep_from + len(take)] = take
        if len(take) < m:  # pad the tail with the last frame
            out[keep_from + len(take):keep_to] = take[-1] if len(take) else 0
        pos += step
    return out, hop / sr


def ctc_viterbi(logp: np.ndarray, tokens: Sequence[int], blank: int = 0) -> List[Optional[Tuple[int, int]]]:
    """Force `tokens` through CTC log-probs. Returns (first, last+1) frame per token."""
    T = logp.shape[0]
    ext = [blank]
    for t in tokens:
        ext += [t, blank]
    S = len(ext)
    ext_a = np.asarray(ext)
    NEG = -1e30
    dp = np.full(S, NEG, dtype=np.float64)
    dp[0] = logp[0, ext[0]]
    if S > 1:
        dp[1] = logp[0, ext[1]]
    bp = np.zeros((T, S), dtype=np.int8)
    can_skip = np.zeros(S, dtype=bool)
    can_skip[2:] = (ext_a[2:] != blank) & (ext_a[2:] != ext_a[:-2])
    emis = logp[:, ext_a].astype(np.float64)
    for t in range(1, T):
        step = np.empty(S)
        step[0] = NEG
        step[1:] = dp[:-1]
        skip = np.full(S, NEG)
        skip[2:] = np.where(can_skip[2:], dp[:-2], NEG)
        best = dp.copy()
        arg = np.zeros(S, dtype=np.int8)
        m = step > best
        best[m] = step[m]
        arg[m] = 1
        m = skip > best
        best[m] = skip[m]
        arg[m] = 2
        dp = best + emis[t]
        bp[t] = arg
    s = S - 1 if S == 1 or dp[S - 1] >= dp[S - 2] else S - 2
    spans: Dict[int, List[int]] = {}
    for t in range(T - 1, -1, -1):
        if s % 2 == 1:
            k = (s - 1) // 2
            sp = spans.get(k)
            if sp is None:
                spans[k] = [t, t + 1]
            else:
                sp[0] = t
        s -= int(bp[t, s])
        if s < 0:
            break
    return [tuple(spans[k]) if k in spans else None for k in range(len(tokens))]


def _en_spoken(tok: Token) -> str:
    """Letters a CTC model hears for one English token."""
    s = tok.spoken or tok.core
    s = re.sub(r"\d+", lambda m: en_number(int(m.group(0))) if len(m.group(0)) < 13 else m.group(0), s)
    s = s.replace("%", " percent").replace("&", " and ").replace("+", " plus ").replace("@", " at ")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.upper().replace("’", "'")
    return " ".join(re.findall(r"[A-Z']+", s))


def align_ctc(x: np.ndarray, sr: int, tokens: List[Token], allow_download: bool = True
              ) -> Optional[List[Dict[str, Any]]]:
    sess, vocab = _w2v_session(allow_download)
    if sess is None:
        return None
    x16 = aio.resample(x, sr, 16000) if sr != 16000 else x
    logp, fdur = _emissions(x16, sess)
    seq: List[int] = []
    owner: List[int] = []
    bar = vocab.get("|", 4)
    for wi, tok in enumerate(tokens):
        letters = _en_spoken(tok)
        chars = [c for c in letters.replace(" ", "|") if c in vocab]
        if not chars:
            continue
        if seq:
            seq.append(bar)
            owner.append(-1)
        for c in chars:
            seq.append(vocab[c])
            owner.append(wi)
    if not seq:
        return None
    if len(seq) * 2 + 1 > logp.shape[0]:
        warn("audio too short for its text: CTC alignment skipped")
        return None
    spans = ctc_viterbi(logp, seq, blank=vocab.get("<pad>", 0))
    words: List[Dict[str, Any]] = []
    for wi, tok in enumerate(tokens):
        ss = [spans[k] for k in range(len(seq)) if owner[k] == wi and spans[k]]
        if ss:
            words.append({"text": tok.text, "start": ss[0][0] * fdur, "end": ss[-1][1] * fdur})
        else:
            words.append({"text": tok.text, "start": None, "end": None})
    from .engines.kokoro import fill_missing
    return fill_missing(words, len(x) / float(sr))


def extend_ends(words: List[Dict[str, Any]], max_ext: float = 0.35) -> List[Dict[str, Any]]:
    """CTC letters are spikes: a word really lasts until just before the next
    one starts (bounded); energy trimming then removes any pause."""
    out = [dict(w) for w in words]
    for a, b in zip(out, out[1:]):
        a["end"] = round(max(a["end"], min(b["start"] - 0.01, a["end"] + max_ext)), 3)
    return out


# --------------------------------------------------------------------------
# TTS reference + DTW (any Kokoro language)
# --------------------------------------------------------------------------

def _mel_fb(sr: int, n_fft: int, n_mels: int = 40, fmin: float = 60.0, fmax: float = 7600.0) -> np.ndarray:
    def hz2mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def mel2hz(m):
        return 700.0 * (10 ** (m / 2595.0) - 1.0)
    mels = np.linspace(hz2mel(fmin), hz2mel(min(fmax, sr / 2)), n_mels + 2)
    hz = mel2hz(mels)
    bins = np.floor((n_fft + 1) * hz / sr).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1))
    for m in range(1, n_mels + 1):
        a, b, c = bins[m - 1], bins[m], bins[m + 1]
        for k in range(a, b):
            fb[m - 1, k] = (k - a) / max(1, b - a)
        for k in range(b, c):
            fb[m - 1, k] = (c - k) / max(1, c - b)
    return fb


def mfcc(x: np.ndarray, sr: int = 16000, hop: float = 0.01, n: int = 20) -> np.ndarray:
    """MFCC + deltas, mean/variance normalized per file: (frames, 2n)."""
    n_fft = 512
    h = int(sr * hop)
    x = np.pad(x.astype(np.float64), (n_fft // 2, n_fft // 2))
    frames = 1 + (len(x) - n_fft) // h
    idx = np.arange(n_fft)[None, :] + h * np.arange(frames)[:, None]
    win = np.hanning(n_fft)
    spec = np.abs(np.fft.rfft(x[idx] * win, axis=1)) ** 2
    mel = np.log(spec @ _mel_fb(sr, n_fft).T + 1e-8)
    k = np.arange(mel.shape[1])
    dct = np.cos(np.pi / mel.shape[1] * (k[None, :] + 0.5) * np.arange(n)[:, None])
    c = mel @ dct.T
    d = np.gradient(c, axis=0)
    f = np.hstack([c, d])
    f = (f - f.mean(0)) / (f.std(0) + 1e-6)
    return f.astype(np.float32)


def dtw_path(A: np.ndarray, B: np.ndarray, band: float = 0.2) -> np.ndarray:
    """DTW between feature sequences (cosine distance). Returns path (k, 2)
    of (i in A, j in B). Rows are solved with a vectorized min-plus scan;
    a Sakoe-Chiba band (fraction of length) bounds the search."""
    N, M = len(A), len(B)
    An = A / (np.linalg.norm(A, axis=1, keepdims=True) + 1e-9)
    Bn = B / (np.linalg.norm(B, axis=1, keepdims=True) + 1e-9)
    INF = np.float32(1e18)
    D = np.full((N, M), INF, dtype=np.float32)
    w = max(int(band * max(N, M)), abs(N - M) + 20)
    for i in range(N):
        center = int(round(i * (M - 1) / max(1, N - 1)))
        lo, hi = max(0, center - w), min(M, center + w + 1)
        c = (1.0 - An[i] @ Bn[lo:hi].T).astype(np.float64)
        if i == 0:
            D[0, lo:hi] = np.cumsum(c)   # the band always starts at column 0 here
            continue
        prev = D[i - 1, lo:hi].astype(np.float64)
        diag = np.empty(hi - lo)
        diag[0] = D[i - 1, lo - 1] if lo > 0 else INF
        diag[1:] = D[i - 1, lo:hi - 1]
        a = c + np.minimum(prev, diag + 0.0)
        # horizontal moves: D[j] = min(a[j], D[j-1] + c[j])  (min-plus scan)
        S = np.cumsum(c)
        row = np.minimum.accumulate(a - S) + S
        D[i, lo:hi] = row
    # backtrack
    i, j = N - 1, M - 1
    path = [(i, j)]
    while i > 0 or j > 0:
        cands = []
        if i > 0 and j > 0:
            cands.append((D[i - 1, j - 1], i - 1, j - 1))
        if i > 0:
            cands.append((D[i - 1, j], i - 1, j))
        if j > 0:
            cands.append((D[i, j - 1], i, j - 1))
        _, i, j = min(cands, key=lambda z: z[0])
        path.append((i, j))
    return np.array(path[::-1])


def align_tts(x: np.ndarray, sr: int, text: str, lang: str, voice: Optional[str] = None
              ) -> Optional[List[Dict[str, Any]]]:
    from . import tts, voices
    try:
        spec = voices.resolve(voice or voices.DEFAULTS.get(lang) or voices.DEFAULTS.get(base_lang(lang)), lang=lang)
    except ShowtimeError:
        return None
    if spec.engine != "kokoro":
        return None
    ref = tts.synthesize(text, voice=spec.id, lang=lang, align_method="none", pad=(0.0, 0.0))
    if not ref.words or ref.timing != "exact":
        return None
    ra = aio.resample(ref.audio, ref.sample_rate, 16000)
    ta = aio.resample(x, sr, 16000) if sr != 16000 else x
    # trim leading/trailing silence of the target so the warp starts on speech
    s0, s1 = aio.speech_bounds(ta, 16000)
    s0, s1 = max(0.0, s0 - 0.05), min(len(ta) / 16000.0, s1 + 0.05)
    tseg = ta[int(s0 * 16000):int(s1 * 16000)]
    r0, r1 = aio.speech_bounds(ra, 16000)
    r0, r1 = max(0.0, r0 - 0.05), min(len(ra) / 16000.0, r1 + 0.05)
    rseg = ra[int(r0 * 16000):int(r1 * 16000)]
    hop = 0.01 if len(tseg) * len(rseg) / (16000.0 ** 2) < 60 * 60 else 0.02
    A, B = mfcc(rseg, 16000, hop), mfcc(tseg, 16000, hop)
    path = dtw_path(A, B)
    # map every reference frame to the median target frame on the path
    mapping = np.zeros(len(A))
    for i in range(len(A)):
        js = path[path[:, 0] == i, 1]
        mapping[i] = np.median(js) if js.size else (mapping[i - 1] if i else 0)

    def warp(t: float) -> float:
        f = (t - r0) / hop
        f = min(max(f, 0.0), len(A) - 1.0)
        a = int(f)
        b = min(a + 1, len(A) - 1)
        y = mapping[a] + (mapping[b] - mapping[a]) * (f - a)
        return s0 + y * hop

    words = [{"text": w["text"], "start": warp(w["start"]), "end": warp(w["end"])} for w in ref.words]
    return words


# --------------------------------------------------------------------------
# Whisper (faster-whisper) mapped onto the script
# --------------------------------------------------------------------------

def _norm_word(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^\w]", "", s)


def align_whisper(path: PathLike, x: np.ndarray, sr: int, tokens: List[Token], lang: str
                  ) -> Optional[List[Dict[str, Any]]]:
    bl = base_lang(lang)
    names = (["small.en", "large-v3-turbo", "small", "base.en", "tiny.en"] if bl == "en"
             else ["large-v3-turbo", "small", "base", "medium"])
    mdir = next((models.whisper_dir(n) for n in names if models.whisper_dir(n)), None)
    if mdir is None:
        return None
    try:
        from faster_whisper import WhisperModel
    except Exception as e:  # noqa: BLE001
        debug("faster-whisper unavailable: %s" % e)
        return None
    info("aligning with Whisper (%s)" % mdir.name)
    thr = os.environ.get("SHOWTIME_THREADS")
    model = WhisperModel(str(mdir), device="cpu", compute_type="int8", cpu_threads=int(thr) if thr and thr.isdigit() else 0)
    x16 = aio.resample(x, sr, 16000) if sr != 16000 else x
    prompt = " ".join(t.core for t in tokens)[:600]
    segs, _ = model.transcribe(x16, language=bl if len(bl) == 2 else None,
                               word_timestamps=True, beam_size=5, condition_on_previous_text=False,
                               initial_prompt=prompt, vad_filter=False)
    hyp = [w for s in segs for w in (s.words or [])]
    if not hyp:
        return None
    a = [_norm_word(t.spoken or t.core) for t in tokens]
    b = [_norm_word(w.word) for w in hyp]
    words: List[Dict[str, Any]] = [{"text": t.text, "start": None, "end": None} for t in tokens]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                words[i1 + k]["start"], words[i1 + k]["end"] = float(hyp[j1 + k].start), float(hyp[j1 + k].end)
        elif tag == "replace" and j2 > j1:
            # spread the script words over the hypothesis span (e.g. "Showtime" heard as "show time")
            s, e = float(hyp[j1].start), float(hyp[j2 - 1].end)
            n = i2 - i1
            for k in range(n):
                words[i1 + k]["start"] = s + (e - s) * k / n
                words[i1 + k]["end"] = s + (e - s) * (k + 1) / n
    from .engines.kokoro import fill_missing
    return fill_missing(words, len(x) / float(sr))


# --------------------------------------------------------------------------
# Even spread over voiced regions
# --------------------------------------------------------------------------

def align_even(x: np.ndarray, sr: int, tokens: List[Token]) -> List[Dict[str, Any]]:
    v = _voiced(x, sr)
    idx = np.flatnonzero(v)
    if idx.size == 0:
        idx = np.arange(max(1, len(x) * 100 // sr))
    voiced_times = idx * 0.01
    weights = np.array([max(1, len(re.sub(r"\W", "", t.spoken or t.core))) for t in tokens], dtype=float)
    cum = np.concatenate([[0], np.cumsum(weights)]) / weights.sum()
    pos = (cum * (len(voiced_times) - 1)).astype(int)
    words = []
    for i, t in enumerate(tokens):
        words.append({"text": t.text, "start": float(voiced_times[pos[i]]),
                      "end": float(voiced_times[max(pos[i], pos[i + 1] - 1)] + 0.01), "estimated": True})
    return words


# --------------------------------------------------------------------------
# Front door
# --------------------------------------------------------------------------

def align_audio(x: np.ndarray, sr: int, text: str, lang: str = "en", method: str = "auto",
                path: Optional[PathLike] = None, voice: Optional[str] = None, snap_edges: bool = True,
                allow_download: bool = True) -> Tuple[List[Dict[str, Any]], str]:
    """Align `text` to mono audio `x`. Returns (words, method_used)."""
    if method not in METHODS:
        raise ShowtimeError("unknown alignment method %r" % method, hint="methods: " + ", ".join(METHODS))
    clean = plain_text(text)
    tokens = tokenize(clean)
    if not tokens:
        raise ShowtimeError("the text has no words to align")
    normalize_tokens(tokens, lang)
    bl = base_lang(lang)
    order = [method] if method != "auto" else (["ctc", "tts", "whisper", "even"] if bl == "en"
                                                 else ["tts", "whisper", "even"])
    words, used = None, "even"
    for m in order:
        t0 = time.time()
        try:
            if m == "ctc":
                if bl != "en":
                    if method == "ctc":
                        raise ShowtimeError("the CTC aligner is English-only", hint="use --method tts or whisper")
                    continue
                words = align_ctc(x, sr, tokens, allow_download)
            elif m == "tts":
                words = align_tts(x, sr, clean, lang, voice)
                if words is not None and len(words) != len(tokens):
                    words = None
            elif m == "whisper":
                if method == "whisper" and allow_download:   # asked for by name: fetch it on first use
                    from .. import lazy
                    lazy.ensure_asr("whisper", "small.en" if base_lang(lang) == "en" else "*", "Whisper alignment")
                words = align_whisper(path or "", x, sr, tokens, lang)
            else:
                words = align_even(x, sr, tokens)
        except ShowtimeError:
            if method != "auto":
                raise
            words = None
        if words:
            used = m
            debug("aligned with %s in %.2fs" % (m, time.time() - t0))
            break
        if method != "auto":
            raise ShowtimeError("alignment method %r is not available here" % m,
                                hint="try --method auto (falls back through ctc, tts, whisper)")
    if snap_edges and words:
        if used in ("whisper", "even"):
            # coarse timings: let edges grow over voiced frames
            words = snap(words, x, sr, grow=True)
        else:
            # precise timings: trim silence at ends, snap starts to clear onsets. CTC
            # fires on the vowel, so it looks further back (fricative onsets).
            if used == "ctc":
                words = extend_ends(refine_onsets(words, x, sr, before=0.15))
            words = refine_onsets(snap(words, x, sr, grow=False, trim_starts=False), x, sr)
    for w in words:
        w["start"], w["end"] = round(float(w["start"]), 3), round(float(w["end"]), 3)
    return words, used


def align(path: PathLike, text: str, lang: str = "en", method: str = "auto", voice: Optional[str] = None,
          snap_edges: bool = True) -> Tuple[List[Dict[str, Any]], str, float]:
    """Align a script to an audio file. Returns (words, method, duration)."""
    x, sr = aio.read(path)
    words, used = align_audio(x, sr, text, lang, method, path=path, voice=voice, snap_edges=snap_edges)
    return words, used, len(x) / float(sr)

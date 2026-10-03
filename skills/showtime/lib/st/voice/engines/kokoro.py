"""Kokoro-82M through kokoro-onnx (timestamped fp16 ONNX export, CPU), with exact word timings.

Word timings come from the timestamped export's per-phoneme durations. The
text is phonemized here (not inside kokoro-onnx) so that:

- pronunciation overrides (inline IPA, lexicon) are spliced in per word;
- every phoneme is tagged with the word it belongs to. espeak-ng merges
  some neighbours ("for the" -> "fɚðə") and expands numbers, so a phrase's
  phonemes are aligned character by character with each word phonemized on
  its own; a merged chunk is split where the per-word phonemes say.

kokoro-onnx then batches the phonemes under the model's 510-token limit
(cutting at sentence, then clause, then word boundaries) and tops up the
pauses after punctuation.
"""
from __future__ import annotations

import difflib
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ...common import ShowtimeError, debug, ort_telemetry_off
from .. import espeak, models
from ..textnorm import Token
from ..voices import VoiceSpec
from .base import Engine, EngineResult, check_speed

STRESS = "ˈˌ"
# The waveform runs ~50 ms behind the model's duration grid (measured against
# acoustic onsets and a CTC aligner over 6 voices x 3 speeds), so phoneme
# times are shifted earlier by this much before words are built.
LAG = float(os.environ.get("SHOWTIME_KOKORO_LAG", "0.05"))
PUNCT_PH = ';:,.!?—…"()“”¡¿'
_lock = threading.Lock()


def _is_letter(ch: str) -> bool:
    return not (ch.isspace() or ch in PUNCT_PH or ch in STRESS or ch in "-'")


def _threads() -> int:
    env = os.environ.get("SHOWTIME_THREADS")
    if env and env.isdigit():
        return max(1, int(env))
    return 0  # onnxruntime default (physical cores)


def _model_source(path):
    """What onnxruntime loads: the file path, or for a half-precision export the
    in-memory model with its 0/0 phase guard (see voice/onnx_patch.py)."""
    name = os.path.basename(str(path)).lower()
    if "fp16" not in name and "f16" not in name:
        return str(path)
    from ..onnx_patch import guard_nan_atan
    with open(str(path), "rb") as fh:
        data, n = guard_nan_atan(fh.read())
    debug("kokoro: %d half-precision phase guard(s) added to %s" % (n, name))
    return data


class KokoroEngine(Engine):
    name = "kokoro"
    speed_range = (0.5, 2.0)

    def __init__(self) -> None:
        self._k = None
        self._model_path: Optional[str] = None
        self.has_timings = False

    # -- availability / loading ------------------------------------------
    def available(self) -> Tuple[bool, str]:
        try:
            import kokoro_onnx  # noqa: F401
        except Exception as e:  # noqa: BLE001
            return False, "kokoro-onnx not installed (%s)" % e
        f = models.kokoro_files()
        if not f["model"] or not f["voices"]:
            return False, "Kokoro model files missing in %s" % models.paths()["kokoro"]
        return True, "timestamped" if f["timestamped"] else "stock model (words are aligned afterwards)"

    def prepare(self, spec: VoiceSpec) -> None:
        self.load()

    def model_id(self, spec: VoiceSpec) -> str:
        f = models.kokoro_files()
        m = f["model"]
        return "kokoro:%s:%s" % (m.name if m else "?", m.stat().st_size if m else 0)

    def load(self):
        if self._k is not None:
            return self._k
        ok, why = self.available()
        if not ok:
            raise ShowtimeError("Kokoro is not ready: " + why, hint="run `showtime setup` (installs Kokoro, ~190 MB)")
        f = models.kokoro_files()
        import onnxruntime as rt
        from kokoro_onnx import Kokoro
        ort_telemetry_off(rt)
        so = rt.SessionOptions()
        n = _threads()
        if n:
            so.intra_op_num_threads = n
        so.log_severity_level = 3
        providers = [os.environ["ONNX_PROVIDER"]] if os.environ.get("ONNX_PROVIDER") else ["CPUExecutionProvider"]
        sess = rt.InferenceSession(_model_source(f["model"]), sess_options=so, providers=providers)
        if not getattr(sess, "_model_path", None):
            sess._model_path = str(f["model"])   # loaded from bytes: kokoro-onnx still checks the file exists
        k = Kokoro.from_session(sess, str(f["voices"]), espeak_config=espeak.config())
        outputs = {o.name for o in sess.get_outputs()}
        # The timestamped export names its second output "durations".
        k.has_timings = bool(outputs & {"duration", "durations"})
        self.has_timings = k.has_timings
        self._k = k
        self._model_path = str(f["model"])
        debug("kokoro loaded %s (timings=%s)" % (f["model"], k.has_timings))
        return k

    def voice_style(self, spec: VoiceSpec) -> np.ndarray:
        k = self.load()
        if spec.blend:
            style = None
            for name, w in spec.blend:
                s = k.get_voice_style(name) * np.float32(w)
                style = s if style is None else style + s
            return style.astype(np.float32)
        return k.get_voice_style(spec.name)

    # -- phonemes with word ownership -----------------------------------
    def _run_phonemes(self, run: List[Tuple[int, Token]], lang: str) -> Tuple[str, List[int]]:
        text = " ".join((t.lead + (t.spoken or t.core) + t.trail) for _, t in run)
        ph = espeak.phonemize(text, lang)
        refs = espeak.phonemize([(t.spoken or t.core) for _, t in run], lang)
        owners = [-1] * len(ph)
        p_idx = [i for i, c in enumerate(ph) if _is_letter(c)]
        r_chars: List[str] = []
        r_own: List[int] = []
        for (ti, _), r in zip(run, refs):
            for c in r:
                if _is_letter(c):
                    r_chars.append(c)
                    r_own.append(ti)
        sm = difflib.SequenceMatcher(None, [ph[i] for i in p_idx], r_chars, autojunk=False)
        for a, b, size in sm.get_matching_blocks():
            for k in range(size):
                owners[p_idx[a + k]] = r_own[b + k]
        _fill_owners(ph, owners, [ti for ti, _ in run])
        return ph, owners

    def phoneme_stream(self, tokens: List[Token], lang: str, lexicon) -> Tuple[str, List[int]]:
        pieces: List[Tuple[str, List[int]]] = []
        run: List[Tuple[int, Token]] = []

        def flush() -> None:
            if run:
                pieces.append(self._run_phonemes(run, lang))
                run.clear()

        for i, t in enumerate(tokens):
            ipa = t.ipa or (lexicon.ipa(t.core, lang) if (lexicon is not None and not t.say) else None)
            if ipa:
                flush()
                lead = "".join(c for c in t.lead if c in PUNCT_PH)
                trail = "".join(c for c in t.trail if c in PUNCT_PH)
                s = lead + ipa + trail
                pieces.append((s, [i if _is_letter(c) or c in STRESS else -1 for c in s]))
            else:
                run.append((i, t))
        flush()
        stream, owners = "", []
        for s, o in pieces:
            if stream:
                stream += " "
                owners.append(-1)
            stream += s
            owners += o
        return stream, owners

    # -- synthesis ------------------------------------------------------
    def synth(self, tokens: List[Token], spec: VoiceSpec, speed: float, lexicon,
              sentence_pause: float = 0.3, clause_pause: float = 0.12) -> EngineResult:
        check_speed(self, speed)
        k = self.load()
        lang = spec.lang
        stream, owners = self.phoneme_stream(tokens, lang, lexicon)
        if not any(_is_letter(c) for c in stream):
            raise ShowtimeError("nothing to say: the text has no pronounceable words")
        style = self.voice_style(spec)
        with _lock:
            audio, sr, timings = k.create_timed(stream, voice=style, speed=float(speed), lang=espeak.espeak_lang(lang),
                                                is_phonemes=True, trim=True, sentence_pause=sentence_pause,
                                                clause_pause=clause_pause)
        audio = np.asarray(audio, dtype=np.float32).ravel()
        words = None
        if k.has_timings and timings:
            words = _words_from_timings(tokens, stream, owners, timings, len(audio) / float(sr))
        return EngineResult(audio=audio, sample_rate=int(sr), words=words, phonemes=stream,
                            meta={"model": os.path.basename(self._model_path or ""), "timings": bool(words)})


def _fill_owners(ph: str, owners: List[int], run_ids: List[int]) -> None:
    """Give unmatched letters and stress marks the owner of their phoneme word."""
    n = len(ph)
    i = 0
    while i < n:
        if ph[i].isspace():
            i += 1
            continue
        j = i
        while j < n and not ph[j].isspace():
            j += 1
        # one whitespace-delimited phoneme word: ph[i:j]
        span = range(i, j)
        known = [owners[x] for x in span if owners[x] >= 0]
        last = -1
        for x in span:
            c = ph[x]
            if c in PUNCT_PH:
                owners[x] = -1
                continue
            if owners[x] >= 0:
                last = owners[x]
                continue
            if c in STRESS or _is_letter(c) or c in "-'":
                nxt = next((owners[y] for y in range(x + 1, j) if owners[y] >= 0), -1)
                if c in STRESS and nxt >= 0:
                    owners[x] = nxt
                elif last >= 0:
                    owners[x] = last
                elif nxt >= 0:
                    owners[x] = nxt
                elif known:
                    owners[x] = known[0]
        i = j
    # Phoneme words with no match at all (e.g. "a" said as "ɐ" but looked up
    # alone as "eɪ") go to the words between their matched neighbours that
    # still have no phonemes; otherwise they join the previous word.
    words_ph: List[Tuple[int, int]] = []
    i = 0
    while i < n:
        if ph[i].isspace():
            i += 1
            continue
        j = i
        while j < n and not ph[j].isspace():
            j += 1
        words_ph.append((i, j))
        i = j
    owned = {o for o in owners if o >= 0}
    order = {t: k for k, t in enumerate(run_ids)}

    def speakable(a: int, b: int) -> bool:
        return any(_is_letter(ph[x]) for x in range(a, b))

    prev = -1
    pending: List[Tuple[int, int]] = []

    def settle(nxt: int) -> None:
        if not pending:
            return
        lo = order.get(prev, -1) + 1
        hi = order.get(nxt, len(run_ids)) if nxt >= 0 else len(run_ids)
        missing = [run_ids[k] for k in range(lo, hi) if run_ids[k] not in owned]
        for idx, (a, b) in enumerate(pending):
            tgt = missing[min(len(missing) - 1, idx * len(missing) // len(pending))] if missing else \
                (prev if prev >= 0 else nxt)
            for x in range(a, b):
                if _is_letter(ph[x]) or ph[x] in STRESS:
                    owners[x] = tgt
            owned.add(tgt)
        pending.clear()

    for a, b in words_ph:
        mine = [owners[x] for x in range(a, b) if owners[x] >= 0]
        if mine:
            settle(mine[0])
            prev = mine[-1]
        elif speakable(a, b):
            pending.append((a, b))
    settle(-1)


def _words_from_timings(tokens: List[Token], stream: str, owners: List[int], timings, total: float
                        ) -> List[Dict[str, Any]]:
    spans: Dict[int, List[float]] = {}
    j = 0
    n = len(stream)
    for t in timings:
        c = t.phoneme
        while j < n and stream[j] != c:
            j += 1
        if j >= n:
            break
        o = owners[j]
        j += 1
        if o < 0 or c in PUNCT_PH or c.isspace():
            continue
        if t.end <= t.start and c in STRESS:
            continue
        s = spans.setdefault(o, [t.start, t.end])
        s[0] = min(s[0], t.start)
        s[1] = max(s[1], t.end)
    words: List[Dict[str, Any]] = []
    for i, tok in enumerate(tokens):
        if i in spans:
            a, b = spans[i]
            a, b = max(0.0, a - LAG), max(0.0, b - LAG)
            words.append({"text": tok.text, "start": round(a, 3), "end": round(max(b, a + 0.02), 3)})
        else:
            words.append({"text": tok.text, "start": None, "end": None})
    return fill_missing(words, total)


def fill_missing(words: List[Dict[str, Any]], total: float) -> List[Dict[str, Any]]:
    """Interpolate words that got no timing between their neighbours and keep
    every word monotonic and non-overlapping."""
    n = len(words)
    i = 0
    while i < n:
        if words[i]["start"] is not None:
            i += 1
            continue
        j = i
        while j < n and words[j]["start"] is None:
            j += 1
        lo = words[i - 1]["end"] if i > 0 else 0.0
        hi = words[j]["start"] if j < n else total
        hi = max(hi, lo + 0.05 * (j - i))
        step = (hi - lo) / (j - i)
        for k in range(i, j):
            words[k]["start"] = round(lo + (k - i) * step, 3)
            words[k]["end"] = round(lo + (k - i + 1) * step, 3)
            words[k]["estimated"] = True
        i = j
    prev_end = 0.0
    for w in words:
        if w["start"] < prev_end:
            w["start"] = round(prev_end, 3)
        if w["end"] < w["start"] + 0.02:
            w["end"] = round(w["start"] + 0.02, 3)
        prev_end = w["end"]
    return words


ENGINE = KokoroEngine()

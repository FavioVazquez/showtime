"""`showtime edit moments`: the best moments of a long recording, as ranked candidates for short clips.

Suggestions only: the agent reads the table, picks a few (and may move their edges), then `showtime edit clips`
turns the picks into finished clips. Everything is local and explainable: the transcript's words, sentences,
speakers and audio events, plus the source audio (numpy). No model calls; topics come from lexical cohesion
(showtime ships no text-embedding model).

Candidates: every run of whole sentences of one source whose clip would last --min..--max seconds once fillers
and long pauses are trimmed (`edit clips` trims them). A candidate starts on a sentence start, ends on a sentence
end and holds no pause longer than BREAK_PAUSE. Signals, each 0..1:

  hook      the first ~3 s (the rest of the first sentence at half): a question, a number, a strong claim, a
            contrast, a story opener, emotion, direct address
  complete  a clean start (no "and", "because", "that's why"), a full stop at the end, a pause or a new speaker
            on both sides
  energy    louder, more varied in level and pitch, and faster than the speaker's own median
  events    laughter, applause or cheering inside the moment or right after its last word (music under it counts
            against it)
  lines     a line worth quoting (a strong claim, a contrast, emotion), short punchy sentences, a phrase repeated
  topic     inside one topic segment (TextTiling over content words), focused on a few of them
  flow      no long pauses inside, few fillers
  length    near the middle of --min..--max

The score is the weighted sum of the signals that could be measured (the others are left out and the weights
renormalised; the report says which). The top --count candidates that do not overlap (nor come within MIN_GAP of
each other) win; each moment names its topic segment, so the spread over the recording shows. Introductions,
thanks, logistics and sponsor reads (HOUSEKEEPING) rank lower whatever their signals.

Times are word boundaries on the source's own clock (`start` = the first word's start, `end` = the last word's
end): `edit clips` adds the padding and trims fillers and pauses inside.
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..common import ShowtimeError
from . import util as U

MOMENTS_VERSION = 1
WEIGHTS = {"hook": 0.20, "complete": 0.18, "energy": 0.14, "events": 0.16, "lines": 0.10, "topic": 0.10,
           "flow": 0.08, "length": 0.04}
HOOK_SECONDS = 3.0
BREAK_PAUSE = 3.0           # a pause this long ends a thought: never inside a moment
SENT_GAP = 1.0              # a pause this long ends a sentence even without punctuation
MAX_SENT_WORDS = 45         # an unpunctuated run this long is split at its longest pause
KEEP_PAUSE, MAX_PAUSE = 0.3, 0.5   # the clip's pause trimming (edit clips' defaults), for the length estimate
EVENT_AFTER = 5.0           # an event this soon after the last word (and before the next one) answers the moment:
                            # the tagger's 2 s windows place an onset up to ~2.5 s late
HOUSEKEEPING_FACTOR = 0.7   # score factor for introductions, thanks, logistics, sponsor reads
TURN_MIN_WORDS = 4          # a speaker label held for fewer words (and under 1.5 s) is diarization noise
MIN_GAP = 3.0               # seconds between two picked moments of one source (never back-to-back slices)
SENT_END = re.compile(r"[.!?\u2026\u3002\uff01\uff1f]['\")\]\u201d\u2019]*$")
QUESTION_END = re.compile(r"[?\uff1f]['\")\]\u201d\u2019]*$")

# English and Spanish word lists for the hook and the clean start; other languages count punctuation and digits
WH = {"en": {"what", "why", "how", "who", "when", "where", "which", "whats", "hows", "whos"},
      "es": {"qué", "que", "por", "cómo", "como", "quién", "quien", "cuándo", "cuando", "dónde", "donde", "cuál",
             "cual"}}
AUX_Q = {"en": {"do", "does", "did", "have", "has", "can", "could", "would", "will", "is", "are", "was", "were",
                "should", "ever"},
         "es": set()}
NUMBER_WORDS = {"en": {"two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
                       "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
                       "hundreds", "thousand", "thousands", "million", "millions", "billion", "billions", "percent",
                       "half", "dozen"},
                "es": {"dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "cien", "ciento",
                       "mil", "millón", "millones", "mitad"}}
CLAIM = {"en": {"most", "best", "worst", "never", "always", "every", "everyone", "everybody", "nobody", "nothing",
                "only", "biggest", "greatest", "hardest", "fastest", "impossible", "incredible", "amazing",
                "unbelievable", "remarkable", "huge", "secret", "truth", "key", "problem", "important", "mistake",
                "wrong", "real", "ever", "absolutely", "definitely", "certainly", "exactly", "proud", "honor"},
         "es": {"nunca", "siempre", "mejor", "peor", "todos", "nadie", "nada", "único", "única", "imposible",
                "increíble", "secreto", "verdad", "clave", "problema", "importante", "error"}}
CONTRAST = {"en": {"but", "however", "actually", "instead", "although", "though", "yet", "except", "unless",
                   "despite", "until", "not", "no", "never"},
            "es": {"pero", "sin", "embargo", "aunque", "sino", "realmente", "no", "nunca"}}
STORY = {"en": ("i remember", "i'll never forget", "i will never forget", "let me tell you", "true story",
                "funny story", "one time", "one day", "the day", "the moment", "the first time", "the last time",
                "picture this", "imagine", "here's the thing", "here is the thing", "the thing is", "the truth is",
                "turns out", "it turned out", "believe it or not", "i'll tell you", "i will tell you"),
         "es": ("me acuerdo", "recuerdo", "nunca olvidaré", "una vez", "un día", "el día", "imagina",
                "la verdad es")}
EMOTION = {"en": {"dream", "dreams", "passion", "inspire", "inspired", "inspiring", "courage", "hope", "proud",
                  "surrender", "legacy", "heart", "goosebumps", "chills", "tears", "cried", "laughed", "hell", "died",
                  "dead", "death", "killed", "afraid", "scared", "fear", "danger", "dangerous", "risk", "emergency",
                  "fire", "explosion", "crash", "failed", "failure", "lost", "survive", "survived", "panic",
                  "terrified", "crazy", "worried", "nervous", "love", "hate", "abort", "disaster", "trouble", "alive"},
           "es": {"sueño", "pasión", "orgullo", "esperanza", "murió", "muerte", "miedo", "peligro", "riesgo",
                  "emergencia", "fuego", "fallo", "perdimos", "pánico", "loco", "lloré", "amor", "desastre"}}
ADDRESS = {"en": {"you", "your", "you're", "imagine", "picture", "listen", "look"},
           "es": {"tú", "usted", "ustedes", "imagina", "imagínate", "mira", "escucha"}}
# talk around the content: introductions, thanks, logistics, sponsor reads (a moment made of it is not a highlight,
# and the applause after an introduction is for the person, not for a line)
HOUSEKEEPING = {"en": ("welcome to", "welcome back", "please welcome", "please join me", "join me in welcoming",
                       "give it up for", "round of applause", "i'd like to introduce", "introduce our", "introduce the",
                       "going to introduce", "our next panelist", "our first panelist", "our panelists",
                       "thank you for joining", "thanks for joining", "thank you all for", "thanks for having me",
                       "thank you for having me", "housekeeping", "qr code", "restroom", "silence your", "sponsored by",
                       "our sponsor", "promo code", "use code", "subscribe", "patreon", "link in the", "show notes",
                       "before we begin", "before we get started", "let's get started", "without further ado",
                       "ladies and gentlemen", "president and ceo", "want to recognize", "honored to be joined",
                       "joining us today", "joining us remotely", "have to wrap", "can you hear me", "check your mic",
                       "loud and clear", "questions from the audience", "questions coming in", "next question",
                       "during your visit", "be sure to visit", "please be sure", "my great pleasure", "my pleasure to",
                       "thrilled to", "excited to welcome", "help me welcome"),
                "es": ("bienvenidos a", "gracias por acompañarnos", "gracias por estar", "suscríbete", "patrocinador",
                       "código de descuento", "les presento", "vamos a empezar", "damas y caballeros")}
# a sentence that ends on one of these goes on after the pause (never a clean end)
CONT_END = {"en": {"and", "but", "or", "so", "the", "a", "an", "of", "to", "that", "because", "with", "for", "in",
                   "on", "at", "from", "by", "my", "our", "your", "their", "his", "her", "its", "is", "was", "were",
                   "are", "be", "if", "when", "which", "who", "than", "as", "like", "then"},
            "es": {"y", "pero", "o", "el", "la", "los", "las", "un", "una", "de", "del", "a", "que", "porque", "con",
                   "para", "en", "por", "mi", "su", "es", "si", "cuando", "como"}}
# a last sentence that starts like this asks the next speaker for something: a question in all but its mark
ASK = {"en": ("talk about", "tell us", "tell me", "share with", "can you", "could you", "would you", "will you",
              "describe", "walk us through", "explain"),
       "es": ("cuéntanos", "cuéntame", "háblanos", "puedes", "podrías", "explícanos")}
# words that do not stop a laugh or applause from belonging to the moment before them ("... a little girl. So" then
# applause): a trailing discourse word, a filler
TRAILING = {"so", "and", "but", "um", "uh", "well", "yeah", "okay", "ok", "oh", "right", "y", "pues", "bueno"}
# a moment that starts on one of these continues an earlier thought
CONT_STRONG = {"en": {"and", "because", "or", "which", "also", "plus", "that's", "thats", "whereas", "therefore",
                      "anyway", "cause", "'cause"},
               "es": {"y", "porque", "o", "que", "también", "además", "entonces"}}
CONT_SOFT = {"en": {"but", "so", "then", "he", "she", "it", "they", "this", "that", "those", "these", "him", "her",
                    "them", "there"},
             "es": {"pero", "él", "ella", "ellos", "eso", "esto"}}
# a sentence made only of these is a reply, not an opening (a listener's "Yeah." or the "Thank you." after applause)
REPLY_WORDS = {"yeah", "yes", "yep", "no", "nope", "right", "okay", "ok", "sure", "exactly", "absolutely", "thank",
               "thanks", "you", "well", "oh", "wow", "great", "good", "mhm", "mm-hmm", "uh-huh", "true", "indeed",
               "correct", "alright", "all", "so", "and", "sí", "claro", "bueno", "vale", "gracias", "exacto"}
STOPWORDS = {"en": set("""a about above after again against all am an and any are aren't as at be because been before
being below between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during
each few for from further had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself
him himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself let's me more most mustn't my
myself no nor not of off on once only or other ought our ours ourselves out over own same shan't she she'd she'll
she's should shouldn't so some such than that that's the their theirs them themselves then there there's these
they they'd they'll they're they've this those through to too under until up very was wasn't we we'd we'll we're
we've were weren't what what's when when's where where's which while who who's whom why why's with won't would
wouldn't you you'd you'll you're you've your yours yourself yourselves yeah okay ok oh well just really like know
think thing things going gonna get got go went say said mean kind sort lot lots actually also something anything
everything one two way time yes right little bit much many even still now back see come came make made want
wanted us around sure whole maybe probably able""".split()),
             "es": set("""a al algo como con de del el ella ellos en entonces es esa ese eso esta este esto fue ha hay
la las le lo los más me mi muy no nos o para pero por que qué se ser si sí sin son su sus también te tiene todo un
una uno y ya yo bueno pues o sea""".split())}


# ------------------------------------------------------------------------------------------------ helpers

def _lang(tr: Dict[str, Any]) -> str:
    return str(tr.get("language") or "en").split("-")[0].lower()


def _bare(t: str) -> str:
    return U.bare(str(t).replace("\u2019", "'"))


def _clock(t: float) -> str:
    """Seconds as m:ss.s (h:mm:ss.s past an hour), for tables and why lines."""
    t = max(0.0, float(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return ("%d:%02d:%04.1f" % (h, m, s)) if h >= 1 else ("%d:%04.1f" % (m, s))


def _text(words: Sequence[Dict[str, Any]]) -> str:
    return " ".join(str(w["text"]).strip() for w in words if str(w.get("text", "")).strip())


def _stem(t: str) -> str:
    t = _bare(t)
    if t.endswith("'s"):
        t = t[:-2]
    t = t.replace("'", "")
    for suf, keep in (("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", ""), ("ly", "")):
        if t.endswith(suf) and len(t) - len(suf) >= 4 and not (suf == "s" and t.endswith("ss")):
            return t[: len(t) - len(suf)] + keep
    return t


def _pct_ranks(vals: Sequence[Optional[float]]) -> List[Optional[float]]:
    """Percentile rank (0..1) of each value among the non-None ones (ties share their mean rank)."""
    idx = sorted((v, i) for i, v in enumerate(vals) if v is not None and v == v)
    out: List[Optional[float]] = [None] * len(vals)
    n = len(idx)
    if not n:
        return out
    k = 0
    while k < n:
        j = k
        while j + 1 < n and idx[j + 1][0] == idx[k][0]:
            j += 1
        r = ((k + j) / 2.0) / max(1, n - 1) if n > 1 else 0.5
        for q in range(k, j + 1):
            out[idx[q][1]] = r
        k = j + 1
    return out


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# ------------------------------------------------------------------------------------------------ sentences

def turns(words: Sequence[Dict[str, Any]]) -> List[str]:
    """The speaker of each word with diarization noise smoothed out: a label held for fewer than TURN_MIN_WORDS
    words and under 1.5 s takes the label before it (or after it, at the start). Words without labels are "S0"."""
    labels = [str(w.get("speaker") or "S0") for w in words]
    runs: List[List[Any]] = []          # [label, first, last]
    for k, lab in enumerate(labels):
        if runs and runs[-1][0] == lab:
            runs[-1][2] = k
        else:
            runs.append([lab, k, k])
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for r in range(len(runs)):
            lab, a, b = runs[r]
            short = b - a + 1 < TURN_MIN_WORDS and float(words[b]["end"]) - float(words[a]["start"]) < 1.5
            if not short:
                continue
            new = runs[r - 1][0] if r > 0 else runs[r + 1][0]
            if new == lab:
                continue
            runs[r][0] = new
            changed = True
        merged: List[List[Any]] = []
        for run in runs:
            if merged and merged[-1][0] == run[0]:
                merged[-1][2] = run[2]
            else:
                merged.append(run)
        runs = merged
    out = labels[:]
    for lab, a, b in runs:
        for k in range(a, b + 1):
            out[k] = lab
    return out


def sentences(words: List[Dict[str, Any]], *, gap: float = SENT_GAP, punctuated: bool = True,
              lang: str = "en", spk: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Sentences of a word list: [{"a": first index, "b": last index, "start", "end", "clean_start", "clean_end"}].

    A sentence ends at end punctuation, a pause of `gap` s or more, or a change of (smoothed) speaker after a pause of
    0.3 s or more (an unpunctuated transcript: pauses of 0.6 s, speaker changes after 0.2 s). clean_end: it ends on end
    punctuation, or on a pause or a new speaker without a trailing comma or a word that needs more ("and", "the");
    clean_start: the sentence before ended cleanly and it does not start in lower case (a cased transcript)."""
    n = len(words)
    spk = list(spk) if spk is not None else turns(words)
    cont = CONT_END.get(lang, set())
    cased = sum(1 for w in words if str(w["text"])[:1].isupper() and
                _bare(w["text"]) not in ("i", "i'm", "i'll", "i've", "i'd")) >= max(2, n // 50)
    brk_gap, spk_gap = (gap, 0.3) if punctuated else (0.6, 0.2)
    out: List[Dict[str, Any]] = []
    a = 0
    for k in range(n):
        end = k == n - 1
        if not end:
            g = float(words[k + 1]["start"]) - float(words[k]["end"])
            end = g >= brk_gap or (spk[k] != spk[k + 1] and g >= spk_gap) or \
                (punctuated and bool(SENT_END.search(str(words[k]["text"]).strip())))
        if end:
            out.append({"a": a, "b": k})
            a = k + 1
    # an unpunctuated run that is too long: split at its longest pause (repeatedly)
    split: List[Dict[str, Any]] = []
    for s in out:
        stack = [(s["a"], s["b"])]
        while stack:
            x, y = stack.pop()
            if y - x + 1 <= MAX_SENT_WORDS:
                split.append({"a": x, "b": y})
                continue
            gaps = [(float(words[k + 1]["start"]) - float(words[k]["end"]), k) for k in range(x + 8, y - 8)]
            if not gaps:
                split.append({"a": x, "b": y})
                continue
            _g, k = max(gaps)
            stack.append((k + 1, y))
            stack.append((x, k))
    split.sort(key=lambda s: s["a"])
    for i, s in enumerate(split):
        first, last = words[s["a"]], words[s["b"]]
        s["start"], s["end"] = float(first["start"]), float(last["end"])
        txt = str(last["text"]).strip()
        if i == len(split) - 1:
            s["clean_end"] = True
        elif punctuated and SENT_END.search(txt):
            s["clean_end"] = True
        else:
            nxt = words[split[i + 1]["a"]]
            g = float(nxt["start"]) - float(last["end"])
            dangling = txt.endswith((",", ";", ":", "-")) or _bare(txt) in cont
            s["clean_end"] = g >= BREAK_PAUSE or (not dangling and (
                g >= gap or (spk[s["b"]] != spk[split[i + 1]["a"]] and g >= 0.6) or (not punctuated and g >= 0.6)))
    for i, s in enumerate(split):
        t = str(words[s["a"]]["text"]).strip()
        lower = cased and t[:1].islower() and _bare(t) != "i"
        s["clean_start"] = i == 0 or (split[i - 1]["clean_end"] and not lower)
    return split


def snap(words: Sequence[Dict[str, Any]], start: float, end: float) -> Tuple[int, int]:
    """(first, last) indices of the words a start..end range keeps, never cutting a word: a word an edge falls
    inside stays whole (the edge moves out to its boundary); an edge in a pause moves in to the next word.
    Raises when no word lies in the range."""
    first = next((i for i, w in enumerate(words) if float(w["end"]) > start + 1e-6), None)
    last = next((i for i in range(len(words) - 1, -1, -1) if float(words[i]["start"]) < end - 1e-6), None)
    if first is None or last is None or last < first:
        raise ShowtimeError("no words between %.2f and %.2f s" % (start, end),
                            hint="pick start/end around spoken words (moments.json lists them)")
    return first, last


# ------------------------------------------------------------------------------------------------ audio

def source_audio(path: Path, track: int = 0):
    """(16 kHz mono float32, sr) of a source's audio track: the WAV `showtime transcribe` cached, else decoded
    once into the same cache."""
    wav = U.cache_dir("transcripts") / ("%s.t%d.16k.wav" % (U.quick_hash(path), int(track or 0)))
    if not wav.is_file():
        U.extract_wav(path, wav, sr=16000, track=int(track or 0))
    return U.load_audio(wav, sr=16000)


def pitch_track(x, sr: int, hop: float = 0.02, frame: float = 0.04, fmin: float = 70.0, fmax: float = 400.0):
    """Fundamental frequency per hop (Hz, NaN where unvoiced): normalised autocorrelation of each frame (FFT, in
    blocks), the best lag in fmin..fmax with parabolic refinement; voiced = loud enough and periodic (peak >= 0.5).
    Good enough for how much a voice's pitch moves, not for music."""
    import numpy as np
    h = max(1, int(round(sr * hop)))
    n = max(64, int(round(sr * frame)))
    count = max(0, (len(x) - n) // h + 1)
    out = np.full(count, np.nan, dtype=np.float32)
    if count == 0:
        return out
    nfft = 1 << int(math.ceil(math.log2(2 * n)))
    lo, hi = int(sr / fmax), min(n - 1, int(sr / fmin))
    win = np.hanning(n).astype(np.float32)
    db_all = U.frame_db(x, sr, hop)
    thr, _floor, _pk = U.voice_threshold(db_all)
    block = 4096
    for b0 in range(0, count, block):
        b1 = min(count, b0 + block)
        idx = np.arange(b0, b1) * h
        fr = np.lib.stride_tricks.as_strided(x[idx[0]:], shape=(b1 - b0, n), strides=(h * x.strides[0], x.strides[0]))
        fr = (fr - fr.mean(axis=1, keepdims=True)) * win
        spec = np.fft.rfft(fr, nfft, axis=1)
        ac = np.fft.irfft(spec * np.conj(spec), nfft, axis=1)[:, : n]
        ac0 = ac[:, :1] + 1e-9
        r = ac[:, lo:hi + 1] / ac0
        k = np.argmax(r, axis=1)
        peak = r[np.arange(len(k)), k]
        lag = (k + lo).astype(np.float64)
        # parabolic refinement around the peak
        kk = np.clip(k, 1, r.shape[1] - 2)
        y0, y1, y2 = r[np.arange(len(kk)), kk - 1], r[np.arange(len(kk)), kk], r[np.arange(len(kk)), kk + 1]
        den = (y0 - 2 * y1 + y2)
        with np.errstate(divide="ignore", invalid="ignore"):
            shift = np.where(np.abs(den) > 1e-9, 0.5 * (y0 - y2) / np.where(np.abs(den) > 1e-9, den, 1.0), 0.0)
        lag = np.where((k >= 1) & (k <= r.shape[1] - 2), kk + lo + np.clip(shift, -1, 1), lag)
        f0 = sr / np.maximum(lag, 1.0)
        dbs = db_all[np.minimum(len(db_all) - 1, (idx + n // 2) // h)] if len(db_all) else np.zeros(len(k))
        voiced = (peak >= 0.5) & (dbs > thr)
        out[b0:b1] = np.where(voiced, f0, np.nan)
    return out


def word_prosody(words: Sequence[Dict[str, Any]], x, sr: int) -> Dict[str, List[Optional[float]]]:
    """Per word: level (dB, RMS over the word), pitch (semitones over 100 Hz, the median of its voiced frames)."""
    import numpy as np
    hop = 0.01
    db = U.frame_db(x, sr, hop)
    f0 = pitch_track(x, sr)
    phop = 0.02
    lv: List[Optional[float]] = []
    pt: List[Optional[float]] = []
    for w in words:
        a, b = float(w["start"]), float(w["end"])
        i0, i1 = int(a / hop), max(int(a / hop) + 1, int(b / hop))
        seg = db[i0:i1]
        if len(seg):
            p = np.power(10.0, seg.astype(np.float64) / 10.0)
            lv.append(round(float(10 * np.log10(np.mean(p) + 1e-12)), 2))
        else:
            lv.append(None)
        j0, j1 = int(a / phop), max(int(a / phop) + 1, int(b / phop))
        fs = f0[j0:j1]
        fs = fs[~np.isnan(fs)] if len(fs) else fs
        pt.append(round(float(12 * np.log2(np.median(fs) / 100.0)), 2) if len(fs) else None)
    return {"level": lv, "pitch": pt}


# ------------------------------------------------------------------------------------------------ topics

def _content_tokens(words: Sequence[Dict[str, Any]], lang: str) -> List[List[str]]:
    stop = STOPWORDS.get(lang, set())
    out = []
    for w in words:
        b = _bare(w["text"])
        if len(b) < 3 or b in stop or U.is_filler(b, lang) or b.isdigit():
            out.append([])
        else:
            out.append([_stem(b)])
    return out


def topics(words: Sequence[Dict[str, Any]], sents: Sequence[Dict[str, Any]], lang: str, *,
           block: int = 4, min_len: Optional[float] = None) -> Dict[str, Any]:
    """Topic segments by lexical cohesion (TextTiling): at each sentence gap, the cosine similarity of the content
    words of the `block` sentences before against the `block` after; boundaries at the deepest valleys (depth >
    mean + std / 2), at least `min_len` s apart (default: an eighth of the recording, 15-60 s). Content words: stems, minus stop words and minus any stem used in
    over a third of the sentences (so it works in languages without a stop list). Returns {"bounds": [sentence
    index of each segment start], "segments": [{start, end, a, b, keywords}], "sent_seg": [segment per sentence],
    "tokens": [stems per sentence]}."""
    if min_len is None:
        total = float(sents[-1]["end"]) - float(sents[0]["start"]) if sents else 0.0
        min_len = max(15.0, min(60.0, total / 8.0))
    toks_w = _content_tokens(words, lang)
    sent_toks: List[List[str]] = [[t for k in range(s["a"], s["b"] + 1) for t in toks_w[k]] for s in sents]
    df: Dict[str, int] = {}
    for st in sent_toks:
        for t in set(st):
            df[t] = df.get(t, 0) + 1
    ns = max(1, len(sents))
    common = {t for t, c in df.items() if c > max(8, ns / 3.0)}
    sent_toks = [[t for t in st if t not in common] for st in sent_toks]
    gaps: List[float] = []
    for g in range(1, len(sents)):
        left: Dict[str, int] = {}
        right: Dict[str, int] = {}
        for st in sent_toks[max(0, g - block):g]:
            for t in st:
                left[t] = left.get(t, 0) + 1
        for st in sent_toks[g:g + block]:
            for t in st:
                right[t] = right.get(t, 0) + 1
        num = sum(v * right.get(t, 0) for t, v in left.items())
        den = math.sqrt(sum(v * v for v in left.values()) * sum(v * v for v in right.values())) or 1.0
        gaps.append(num / den)
    sm = [sum(gaps[max(0, i - 1):i + 2]) / len(gaps[max(0, i - 1):i + 2]) for i in range(len(gaps))] if gaps else []
    depth: List[float] = []
    for i, v in enumerate(sm):
        lp = v
        j = i
        while j > 0 and sm[j - 1] >= lp:
            j -= 1
            lp = sm[j]
        rp = v
        j = i
        while j < len(sm) - 1 and sm[j + 1] >= rp:
            j += 1
            rp = sm[j]
        d = (lp - v) + (rp - v)
        # a long pause before the sentence deepens the valley a little (a pause often ends a topic)
        pause = float(sents[i + 1]["start"]) - float(sents[i]["end"])
        depth.append(d + (0.08 if pause >= 2.5 else 0.0))
    bounds = [0]
    if depth:
        mean = sum(depth) / len(depth)
        sd = math.sqrt(sum((d - mean) ** 2 for d in depth) / len(depth))
        cut = mean + sd / 2.0
        for i in sorted(range(len(depth)), key=lambda i: -depth[i]):
            if depth[i] <= cut:
                break
            g = i + 1
            t = float(sents[g]["start"])
            if all(abs(t - float(sents[b]["start"])) >= min_len for b in bounds) and \
                    float(sents[-1]["end"]) - t >= min_len / 2.0:
                bounds.append(g)
    bounds.sort()
    sent_seg = [0] * len(sents)
    segs = []
    for si, g in enumerate(bounds):
        h = bounds[si + 1] - 1 if si + 1 < len(bounds) else len(sents) - 1
        for q in range(g, h + 1):
            sent_seg[q] = si
        segs.append({"a": g, "b": h, "start": round(float(sents[g]["start"]), 2), "end": round(float(sents[h]["end"]), 2)})
    # keywords per segment: tf-idf of stems (idf over segments), shown as the most frequent surface form
    surface: Dict[str, Dict[str, int]] = {}
    for k, w in enumerate(words):
        for t in toks_w[k]:
            f = surface.setdefault(t, {})
            b = _bare(w["text"])
            f[b] = f.get(b, 0) + 1
    seg_tf: List[Dict[str, int]] = []
    for s in segs:
        tf: Dict[str, int] = {}
        for q in range(s["a"], s["b"] + 1):
            for t in sent_toks[q]:
                tf[t] = tf.get(t, 0) + 1
        seg_tf.append(tf)
    sdf: Dict[str, int] = {}
    for tf in seg_tf:
        for t in tf:
            sdf[t] = sdf.get(t, 0) + 1
    for s, tf in zip(segs, seg_tf):
        sc = sorted(((c * math.log(1 + len(segs) / sdf[t]), t) for t, c in tf.items() if c >= 2), reverse=True)
        s["keywords"] = [max(surface[t].items(), key=lambda kv: kv[1])[0] for _v, t in sc[:5]]
    return {"bounds": bounds, "segments": segs, "sent_seg": sent_seg, "tokens": sent_toks, "surface": surface}


# ------------------------------------------------------------------------------------------------ signals

def _hook(words: Sequence[Dict[str, Any]], a: int, b: int, sent_end: int, lang: str) -> Tuple[float, List[str], str]:
    """(score, reasons, the opening text) of a moment that starts at word a: what is said in the first HOOK_SECONDS
    counts fully (a question, a number, a strong claim, a contrast, a story opener, emotion, direct address); the
    rest of the first sentence (up to 10 s) counts half."""
    t0 = float(words[a]["start"])
    k3 = a
    while k3 + 1 <= b and float(words[k3 + 1]["start"]) < t0 + HOOK_SECONDS:
        k3 += 1
    k3 = min(max(k3, min(b, a + 3)), a + 13)
    k10 = sent_end
    while k10 > k3 and float(words[k10]["start"]) > t0 + 10.0:
        k10 -= 1
    first3 = [_bare(w["text"]) for w in words[a:k3 + 1]]
    rest = [_bare(w["text"]) for w in words[k3 + 1:k10 + 1]] if k10 > k3 else []
    first_sent = words[a:sent_end + 1]
    opening = _text(first_sent[:24]) + (" ..." if len(first_sent) > 24 else "")
    why: List[str] = []
    sc = 0.0
    q_end = float(words[sent_end]["end"]) - t0 <= 10.0 and bool(QUESTION_END.search(str(words[sent_end]["text"]).strip()))
    q_start = bool(first3) and (first3[0] in WH.get(lang, set()) or
                                (len(first3) > 1 and first3[0] in AUX_Q.get(lang, set()) and first3[1] in
                                 ("you", "we", "i", "it", "they", "anyone", "anybody", "he", "she")))
    if q_end or (q_start and "?" in _text(first_sent)) or str(words[a]["text"]).startswith("\u00bf"):
        sc += 0.45
        why.append("opens with a question")

    def kinds(toks: List[str]) -> List[Tuple[str, float, str]]:
        low = " ".join(toks)
        out = []
        nums = [t for t in toks if any(ch.isdigit() for ch in t) or t in NUMBER_WORDS.get(lang, set())]
        if nums:
            out.append(("a number", 0.3, nums[0]))
        cl = [t for t in toks if t in CLAIM.get(lang, set())]
        if cl:
            out.append(("a strong claim", min(0.4, 0.25 + 0.08 * (len(cl) - 1)), cl[0]))
        con = [t for t in toks if t in CONTRAST.get(lang, set())]
        if con:
            out.append(("a contrast", 0.15, con[0]))
        story = [x for x in STORY.get(lang, ()) if x in low]
        if story:
            out.append(("a story opener", 0.3, story[0]))
        emo = [t for t in toks if t in EMOTION.get(lang, set())]
        if emo:
            out.append(("emotion", 0.2, emo[0]))
        return out

    seen = set()
    for label, val, word in kinds(first3):
        sc += val
        seen.add(label)
        why.append("%s in the first seconds (%s)" % (label, word))
    for label, val, word in kinds(rest):
        if label in seen:
            continue
        sc += val / 2.0
        why.append("%s in the first sentence (%s)" % (label, word))
    if any(t in ADDRESS.get(lang, set()) for t in first3):
        sc += 0.1
    # weak openings: a filler or a reply first, or the thanks after applause
    if first3 and (U.is_filler(first3[0], lang) or first3[0] in ("yeah", "yes", "okay", "ok", "well", "oh")):
        sc -= 0.15
    if str(words[a]["text"]).strip().lower().startswith("thank"):
        sc -= 0.3
    return _clamp(sc), why, opening


def _cont(words: Sequence[Dict[str, Any]], a: int, lang: str) -> Tuple[float, Optional[str]]:
    """(penalty, the word) when a moment starting at word a continues an earlier thought."""
    t = _bare(words[a]["text"])
    two = (t + " " + _bare(words[a + 1]["text"])) if a + 1 < len(words) else t
    if t in CONT_STRONG.get(lang, set()) or two in ("that's why", "so that", "and then", "and so"):
        return 0.55, str(words[a]["text"]).strip()
    if a + 1 < len(words) and _bare(words[a + 1]["text"]) in ("also", "too", "either", "again", "también"):
        return 0.35, "%s %s" % (str(words[a]["text"]).strip(), str(words[a + 1]["text"]).strip())
    if t in CONT_SOFT.get(lang, set()):
        return 0.2, str(words[a]["text"]).strip()
    return 0.0, None


def _is_trailing(words: Sequence[Dict[str, Any]], s: Dict[str, Any], lang: str) -> bool:
    """A sentence of only a trailing discourse word or fillers ("So", "And um"): never the end of a moment."""
    toks = [_bare(words[k]["text"]) for k in range(s["a"], s["b"] + 1)]
    return all(t in TRAILING or U.is_filler(t, lang) or not t for t in toks)


def _is_reply(words: Sequence[Dict[str, Any]], s: Dict[str, Any], lang: str) -> bool:
    toks = [_bare(words[k]["text"]) for k in range(s["a"], s["b"] + 1)]
    toks = [t for t in toks if t and not U.is_filler(t, lang)]
    return not toks or (len(toks) <= 4 and all(t in REPLY_WORDS for t in toks))


def _lines(words: Sequence[Dict[str, Any]], sents: Sequence[Dict[str, Any]], i: int, j: int, lang: str
           ) -> Tuple[float, List[str]]:
    """(score, reasons): the moment's best line (claims, contrast, emotion, a number, an exclamation), its short punchy
    sentences (2-6 words: "It can be done."), and a phrase of 3+ words said twice ("one hell of a job")."""
    best, best_txt = 0.0, ""
    punchy: List[str] = []
    grams: Dict[Tuple[str, ...], int] = {}
    stop = STOPWORDS.get(lang, set())
    for q in range(i, j + 1):
        s = sents[q]
        toks = [_bare(w["text"]) for w in words[s["a"]:s["b"] + 1] if not U.is_filler(w["text"], lang)]
        toks = [t for t in toks if t]
        if 2 <= len(toks) <= 6 and not all(t in REPLY_WORDS for t in toks):
            punchy.append(_text([w for w in words[s["a"]:s["b"] + 1] if not U.is_filler(w["text"], lang)]))
        if 4 <= len(toks) <= 20:
            ts = set(toks)
            sc = 0.3 * len(ts & CLAIM.get(lang, set())) + 0.15 * len(ts & CONTRAST.get(lang, set())) + \
                0.25 * len(ts & EMOTION.get(lang, set())) + \
                (0.2 if any(any(ch.isdigit() for ch in t) or t in NUMBER_WORDS.get(lang, set()) for t in toks) else 0.0) + \
                (0.2 if str(words[s["b"]]["text"]).strip().endswith("!") else 0.0)
            if sc > best:
                best, best_txt = sc, _best_phrase(words, s["a"], s["b"], lang)[1] or _text(words[s["a"]:s["b"] + 1])
        for k in range(len(toks) - 2):
            g = tuple(toks[k:k + 3])
            if sum(1 for t in g if t not in stop) >= 1 and len(set(g)) == 3:
                grams[g] = grams.get(g, 0) + 1
    rep = sorted((g for g, c in grams.items() if c >= 2), key=lambda g: -sum(1 for t in g if t not in stop))
    why = []
    if best >= 0.4:
        why.append("a line worth quoting (\"%s\")" % (best_txt[:64] + ("..." if len(best_txt) > 64 else "")))
    if len(punchy) >= 2:
        why.append("short punchy lines (\"%s\")" % punchy[0][:40])
    if rep:
        why.append("repeats \"%s\"" % " ".join(rep[0]))
    return _clamp(0.5 * min(1.0, best) + 0.25 * min(1.0, len(punchy) / 3.0) + (0.25 if rep else 0.0)), why


# ------------------------------------------------------------------------------------------------ ranking

def _sources(paths: Sequence[Path]) -> List[Dict[str, Any]]:
    out = []
    keys: Dict[str, int] = {}
    for p in paths:
        tr = U.load_transcript(p)
        src = Path(tr.get("source") or "")
        key = U.bare(Path(str(src or p)).stem).replace(" ", "-") or "src"
        n = keys.get(key, 0) + 1
        keys[key] = n
        if n > 1:
            key = "%s%d" % (key, n)
        out.append({"key": key, "transcript": Path(p).resolve(), "tr": tr, "media": src if src.is_file() else None,
                    "track": int(tr.get("audio_track") or 0)})
    return out


def _speaker_median(words, vals) -> Dict[str, float]:
    import numpy as np
    by: Dict[str, List[float]] = {}
    for w, v in zip(words, vals):
        if v is not None:
            by.setdefault(str(w.get("speaker") or "S0"), []).append(v)
    return {k: float(np.median(v)) for k, v in by.items() if v}


def _iqr(v) -> Optional[float]:
    import numpy as np
    v = [x for x in v if x is not None]
    if len(v) < 6:
        return None
    q1, q3 = np.percentile(v, [25, 75])
    return float(q3 - q1)


def analyse(src: Dict[str, Any], *, min_len: float, max_len: float, audio: bool = True) -> Dict[str, Any]:
    """Every candidate of one source with its raw features (the ranking normalises them across sources)."""
    import numpy as np
    tr = src["tr"]
    lang = _lang(tr)
    words = sorted((w for w in U.words_of(tr) if str(w.get("text", "")).strip()), key=lambda w: float(w["start"]))
    events = sorted((w for w in tr.get("words", []) if w.get("type") == "audio_event"), key=lambda w: float(w["start"]))
    if len(words) < 8:
        raise ShowtimeError("%s has only %d words: nothing to rank" % (src["transcript"].name, len(words)),
                            hint="moments need a transcribed recording (`showtime transcribe <media>`)")
    punct = sum(1 for w in words if SENT_END.search(str(w["text"]).strip())) >= max(2, len(words) // 200)
    spk = turns(words)
    sents = sentences(words, punctuated=punct, lang=lang, spk=spk)
    topic = topics(words, sents, lang)
    n = len(words)
    ws = np.array([float(w["start"]) for w in words])
    we = np.array([float(w["end"]) for w in words])
    filler = np.array([1 if (U.is_filler(w["text"], lang) or w.get("filler")) else 0 for w in words])
    gap = np.concatenate([[0.0], ws[1:] - we[:-1]]).clip(min=0.0)
    # the clip's length once fillers and long pauses are trimmed (edit clips' defaults): prefix sums
    wdur = np.where(filler == 1, 0.0, we - ws)
    gkeep = np.where(gap > MAX_PAUSE, KEEP_PAUSE, gap)
    c_wdur = np.concatenate([[0.0], np.cumsum(wdur)])
    c_gap = np.concatenate([[0.0], np.cumsum(gkeep)])
    c_fill = np.concatenate([[0], np.cumsum(filler)])
    long_gap = np.where(gap > 1.2, gap - 1.2, 0.0)
    c_long = np.concatenate([[0.0], np.cumsum(long_gap)])
    lows = [_bare(w["text"]) for w in words]
    pros = None
    notes: List[str] = []
    if audio and src.get("media") is not None:
        try:
            x, sr = source_audio(src["media"], src["track"])
            pros = word_prosody(words, x, sr)
        except Exception as e:  # noqa: BLE001 - the energy signal is optional
            notes.append("speaker energy was not measured (%s)" % e)
    elif audio:
        notes.append("speaker energy was not measured: the transcript's source media is missing")
    by_spk = [{"speaker": lab} for lab in spk]
    if pros is not None:
        lv_med = _speaker_median(by_spk, pros["level"])
        pt_med = _speaker_median(by_spk, pros["pitch"])
    spk_rate: Dict[str, List[float]] = {}
    for s in sents:
        d = float(we[s["b"]] - ws[s["a"]])
        if d > 1.5:
            spk_rate.setdefault(spk[s["a"]], []).append((s["b"] - s["a"] + 1) / d)
    rate_med = {k: float(np.median(v)) for k, v in spk_rate.items() if v}
    ev = [{"kind": str(e["text"]).strip("()[] ").lower(), "start": float(e["start"]), "end": float(e["end"])}
          for e in events]
    house = HOUSEKEEPING.get(lang, ())
    cands: List[Dict[str, Any]] = []
    S = len(sents)
    for i in range(S):
        si = sents[i]
        if not si["clean_start"] or _is_reply(words, si, lang):
            continue
        a = si["a"]
        for j in range(i, S):
            sj = sents[j]
            b = sj["b"]
            if j > i and float(ws[sj["a"]] - we[sents[j - 1]["b"]]) >= BREAK_PAUSE:
                break
            span = float(we[b] - ws[a])
            if span > max_len * 1.8:
                break
            est = float(c_wdur[b + 1] - c_wdur[a] + c_gap[b + 1] - c_gap[a + 1]) + 0.2
            if est > max_len:
                break
            if est < min_len or not sj["clean_end"] or _is_trailing(words, sj, lang):
                continue
            cands.append({"i": i, "j": j, "a": a, "b": b, "est": est, "span": span})
    if not cands:
        return {"src": src, "words": words, "sents": sents, "topic": topic, "cands": [], "lang": lang,
                "punct": punct, "notes": notes + ["no run of whole sentences lasts %g-%g s" % (min_len, max_len)],
                "events": ev, "pros": pros, "turns": spk}
    for c in cands:
        a, b, i, j = c["a"], c["b"], c["i"], c["j"]
        nw = b - a + 1
        t0, t1 = float(ws[a]), float(we[b])
        # hook
        c["hook"], c["hook_why"], c["opening"] = _hook(words, a, b, sents[i]["b"], lang)
        # complete: the start, the end, whole turns
        pen, wcont = _cont(words, a, lang)
        g_before = float(ws[a] - we[a - 1]) if a > 0 else 9.0
        # the next word that counts: a trailing "So" or filler said into a pause (or into applause) does not
        k_next = b + 1
        while k_next < n and (filler[k_next] or lows[k_next] in TRAILING) and k_next - b <= 2:
            k_next += 1
        g_after = float(ws[k_next] - we[b]) if k_next < n else 9.0
        new_turn = a == 0 or spk[a - 1] != spk[a]
        end_turn = k_next >= n or spk[min(k_next, n - 1)] != spk[b]
        last_txt = str(words[b]["text"]).strip()
        start_q = 1.0 - pen
        if not (g_before >= 0.4 or new_turn):
            start_q -= 0.2
        end_q = 1.0
        last_sent = " ".join(lows[sents[j]["a"]:sents[j]["b"] + 1])
        if QUESTION_END.search(last_txt) or last_sent.startswith(ASK.get(lang, ())):
            end_q -= 0.45                                   # ends on a question: a cliffhanger in a clip
        elif not SENT_END.search(last_txt):
            end_q -= 0.25
        if not (g_after >= 0.5 or end_turn):
            end_q -= 0.25
        cut_answer = False
        if spk[b] != spk[a] and not end_turn:
            end_q -= 0.3                                    # a question or a cue, then an answer that goes on
            cut_answer = True
        # a clip is as complete as its weaker edge
        c["complete"] = _clamp(0.5 * min(start_q, end_q) + 0.25 * (start_q + end_q) +
                               (0.1 if new_turn and end_turn else 0.0))
        c["lines"], c["lines_why"] = _lines(words, sents, i, j, lang)
        c["cont"], c["cut_answer"] = wcont, cut_answer
        c["new_turn"], c["end_turn"] = bool(new_turn), bool(end_turn)
        # flow: long pauses inside, fillers
        excess = float(c_long[b + 1] - c_long[a + 1])
        fill_rate = float(c_fill[b + 1] - c_fill[a]) / max(1, nw) * 100.0
        c["flow"] = _clamp(1.0 - 0.12 * excess - 0.04 * max(0.0, fill_rate - 1.0))
        c["fillers"] = int(c_fill[b + 1] - c_fill[a])
        c["long_pause"] = round(float(gap[a + 1:b + 1].max()) if b > a else 0.0, 2)
        # length
        mid = (min_len + max_len) / 2.0
        c["length"] = _clamp(1.0 - abs(c["est"] - mid) / max(1.0, (max_len - min_len)))
        # speakers (smoothed turns)
        cnt: Dict[str, int] = {}
        for k in range(a, b + 1):
            cnt[spk[k]] = cnt.get(spk[k], 0) + 1
        c["speakers"] = {k: round(v / float(nw), 2) for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])}
        main = next(iter(c["speakers"]))
        # energy (raw; normalised across candidates later)
        if pros is not None:
            lvv = [pros["level"][k] - lv_med.get(spk[k], 0.0) for k in range(a, b + 1) if pros["level"][k] is not None]
            ptv = [pros["pitch"][k] - pt_med.get(spk[k], 0.0) for k in range(a, b + 1) if pros["pitch"][k] is not None]
            c["e_level"] = float(np.median(lvv)) if len(lvv) >= 6 else None
            c["e_spread"] = _iqr(lvv)
            c["e_pitch"] = _iqr(ptv)
        speech = float(c_wdur[b + 1] - c_wdur[a]) + float(np.minimum(gap[a + 1:b + 1], 0.3).sum())
        c["e_rate"] = (nw / speech / rate_med.get(main, nw / speech)) if speech > 0 else None
        # events: laughter, applause or cheering inside or right after the end (before anyone speaks again);
        # music under the speech counts against it
        nxt = float(ws[k_next]) if k_next < n else t1 + 60.0
        evs = []
        music = 0.0
        for e in ev:
            if e["kind"] == "music":
                music += max(0.0, min(e["end"], t1) - max(e["start"], t0))
            elif e["kind"] in ("laughter", "applause", "cheering") and e["end"] > t0 + 1.0 and \
                    e["start"] < min(t1 + EVENT_AFTER, nxt + 0.5):
                evs.append(e)
        esc = 0.0
        ewhy = []
        for e in evs:
            after = e["start"] >= t1 - 1.0
            if e["kind"] == "laughter":
                esc += 0.45 if after else 0.3
            elif after:
                esc += 0.6
            elif e["start"] - t0 > 0.6 * (t1 - t0):
                esc += 0.3
            else:
                esc -= 0.1                                   # applause early on: the end of an earlier moment
            ewhy.append("%s right after the end" % e["kind"] if after else "%s at %s" % (e["kind"], _clock(e["start"])))
        c["music"] = round(music / max(1e-6, t1 - t0), 2)
        if c["music"] >= 0.3:
            esc -= 0.3
            ewhy.append("music under %d%% of it" % round(100 * c["music"]))
        c["events"] = _clamp(esc) if ev else None
        c["event_list"] = [{"type": e["kind"], "at": round(e["start"], 2)} for e in evs]
        c["events_why"] = ewhy
        # housekeeping: introductions, thanks, logistics, sponsor reads
        low = " " + " ".join(lows[a:b + 1]) + " "
        c["housekeeping"] = [h for h in house if (" %s " % h) in low][:3]
        # topic: inside one segment, focused
        segs = [topic["sent_seg"][q] for q in range(i, j + 1)]
        main_seg = max(set(segs), key=segs.count)
        c["seg"] = main_seg
        dur_in = sum(float(sents[q]["end"] - sents[q]["start"]) for q in range(i, j + 1) if topic["sent_seg"][q] == main_seg)
        dur_all = sum(float(sents[q]["end"] - sents[q]["start"]) for q in range(i, j + 1)) or 1.0
        toks = [t for q in range(i, j + 1) for t in topic["tokens"][q]]
        tf: Dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        top = sorted(tf.items(), key=lambda kv: -kv[1])[:5]
        c["focus"] = (sum(v for _t, v in top) / float(len(toks))) if len(toks) >= 8 else None
        c["topic_frac"] = dur_in / dur_all
        c["at_bound"] = i in topic["bounds"]
        c["keywords"] = [max(topic["surface"][t].items(), key=lambda kv: kv[1])[0] for t, v in top[:3] if v >= 2]
    return {"src": src, "words": words, "sents": sents, "topic": topic, "cands": cands, "lang": lang, "punct": punct,
            "notes": notes, "events": ev, "pros": pros, "turns": spk}


def _best_phrase(words: Sequence[Dict[str, Any]], a: int, b: int, lang: str, first_bonus: float = 0.0,
                 punctuated: bool = True) -> Tuple[float, str]:
    """The most quotable stretch of 1-3 clauses inside words a..b (one sentence): 4-12 words, at most 64 characters,
    ending on a clause or sentence boundary; a question, emotion, a strong claim, a number count. (score, text)."""
    stop = STOPWORDS.get(lang, set())
    toks = [w for w in words[a:b + 1] if not U.is_filler(w["text"], lang)]
    clauses: List[List[Dict[str, Any]]] = [[]]
    for w in toks:
        clauses[-1].append(w)
        if re.search(r"[,;:\u2014-]$", str(w["text"]).strip()):
            clauses.append([])
    clauses = [c for c in clauses if c]
    best: Tuple[float, str] = (-9.0, "")
    for x in range(len(clauses)):
        for y in range(x, min(len(clauses), x + 3)):
            p = [w for c in clauses[x:y + 1] for w in c]
            while p and (_bare(p[0]["text"]) in CONT_STRONG.get(lang, set()) or
                         _bare(p[0]["text"]) in ("so", "well", "yeah", "oh", "now", "but", "okay", "ok", "generally")):
                p = p[1:]
            if not (4 <= len(p) <= 12):
                continue
            txt = _text(p).strip(" ,;:-\u2014")
            if len(txt) > 64:
                continue
            low = [_bare(w["text"]) for w in p]
            ls = set(low)
            sc = 1.0 - abs(len(p) - 7) / 8.0 + first_bonus
            if QUESTION_END.search(txt):
                sc += 1.2
            if any(any(ch.isdigit() for ch in t) or t in NUMBER_WORDS.get(lang, set()) for t in low):
                sc += 0.5
            sc += 0.5 * len(ls & CLAIM.get(lang, set())) + 0.6 * len(ls & EMOTION.get(lang, set())) + \
                0.2 * len(ls & CONTRAST.get(lang, set()))
            if sum(1 for t in low if t in stop) > 0.7 * len(low):
                sc -= 1.0
            if low[0] in CONT_SOFT.get(lang, set()) and low[0] not in ("this", "that"):
                sc -= 0.3
            if low[-1] in CONT_END.get(lang, set()) or (punctuated and not re.search(r"[.!?,;:]$", str(p[-1]["text"]).strip())):
                sc -= 0.8                                    # ends in the middle of a phrase ("... I almost")
            if sc > best[0]:
                best = (sc, txt)
    return best


def _title(words: Sequence[Dict[str, Any]], sents: Sequence[Dict[str, Any]], i: int, j: int, lang: str,
           punctuated: bool = True) -> str:
    """A suggested title in the speaker's own words: the most quotable phrase of the moment (_best_phrase; the
    opening sentence breaks ties)."""
    best: Tuple[float, str] = (-9.0, "")
    for q in range(i, j + 1):
        cand = _best_phrase(words, sents[q]["a"], sents[q]["b"], lang, 0.3 if q == i else 0.0, punctuated)
        if cand[0] > best[0]:
            best = cand
    t = best[1] or _text(words[sents[i]["a"]:sents[i]["b"] + 1][:8])
    t = re.sub(r"[.,;:\u2014-]+$", "", t).strip()
    return (t[:1].upper() + t[1:]) if t else t


def rank(transcripts: Sequence[Path], *, count: int = 8, min_len: float = 20.0, max_len: float = 60.0,
         audio: bool = True) -> Dict[str, Any]:
    """Rank candidate moments across one or more transcripts. Returns the moments document (see the module doc)."""
    if min_len <= 0 or max_len <= min_len:
        raise ShowtimeError("--min must be above 0 and below --max (got %g and %g)" % (min_len, max_len),
                            hint="e.g. --min 20 --max 60")
    if count < 1:
        raise ShowtimeError("--count must be 1 or more")
    t_start = time.time()
    srcs = _sources([Path(p) for p in transcripts])
    results = [analyse(s, min_len=min_len, max_len=max_len, audio=audio) for s in srcs]
    allc = [(r, c) for r in results for c in r["cands"]]
    notes: List[str] = []
    for r in results:
        notes += ["%s: %s" % (r["src"]["key"], x) for x in r["notes"]]
        if not r["punct"]:
            notes.append("%s: the transcript has no punctuation, so sentences end at pauses and speaker changes"
                         % r["src"]["key"])
        if r["lang"] not in WH:
            notes.append("%s: hook words are English and Spanish; for %r only questions and numbers count"
                         % (r["src"]["key"], r["lang"]))
    has_events = any(r["events"] for r in results)
    measured = {"hook": True, "complete": True, "lines": True, "flow": True, "length": True, "topic": True,
                "energy": any(r["pros"] is not None for r in results), "events": has_events}
    if not has_events:
        try:
            from . import events as EV
            ok = EV.available()[0]
        except Exception:  # noqa: BLE001
            ok = False
        notes.append("no laughter or applause in the transcript, so audio events did not count" +
                     ("" if ok else " (the tagger is not installed: `showtime setup --with events`, then "
                                    "`showtime transcribe <media> --force`)"))
    # normalise the raw energy and focus features across all candidates (percentile ranks)
    cs = [c for _r, c in allc]
    feats = {}
    for k in ("e_level", "e_spread", "e_pitch", "e_rate", "focus"):
        feats[k] = _pct_ranks([c.get(k) for c in cs])
    for q, c in enumerate(cs):
        parts = [(0.35, feats["e_level"][q]), (0.2, feats["e_spread"][q]), (0.3, feats["e_pitch"][q]),
                 (0.15, feats["e_rate"][q])]
        have = [(w, v) for w, v in parts if v is not None]
        c["energy"] = (sum(w * v for w, v in have) / sum(w for w, _v in have)) if have and measured["energy"] else None
        foc = feats["focus"][q]
        c["topic"] = _clamp(0.5 * c["topic_frac"] + 0.3 * (foc if foc is not None else 0.5) +
                            (0.2 if c["at_bound"] else 0.0))
        sig = {k: c.get(k) for k in WEIGHTS}
        use = {k: v for k, v in sig.items() if v is not None and measured.get(k, True)}
        wsum = sum(WEIGHTS[k] for k in use) or 1.0
        c["score"] = sum(WEIGHTS[k] * v for k, v in use.items()) / wsum
        if c.get("housekeeping"):
            c["score"] *= HOUSEKEEPING_FACTOR
        c["signals"] = {k: (round(v, 2) if v is not None else None) for k, v in sig.items()}
    # pick: best first, never overlapping (nor closer than MIN_GAP to) an earlier pick of the same source
    picked: List[int] = []
    for q in sorted(range(len(allc)), key=lambda q: -allc[q][1]["score"]):
        r, c = allc[q]
        t0, t1 = float(r["words"][c["a"]]["start"]), float(r["words"][c["b"]]["end"])
        if any(allc[p][0] is r and t0 < float(r["words"][allc[p][1]["b"]]["end"]) + MIN_GAP and
               t1 > float(r["words"][allc[p][1]["a"]]["start"]) - MIN_GAP for p in picked):
            continue
        picked.append(q)
        if len(picked) >= count:
            break
    moments = []
    for rk, q in enumerate(sorted(picked, key=lambda q: -allc[q][1]["score"]), 1):
        r, c = allc[q]
        moments.append(_moment(r, c, rk))
    doc = {
        "version": MOMENTS_VERSION, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "params": {"count": count, "min": min_len, "max": max_len, "audio": bool(audio)},
        "sources": {r["src"]["key"]: {"transcript": str(r["src"]["transcript"]),
                                      "media": str(r["src"]["media"]) if r["src"]["media"] else None,
                                      "duration": round(float(r["src"]["tr"].get("duration") or 0.0), 2),
                                      "language": r["lang"], "words": len(r["words"]), "sentences": len(r["sents"]),
                                      "candidates": len(r["cands"]),
                                      "topics": [{"start": s["start"], "end": s["end"], "keywords": s["keywords"]}
                                                 for s in r["topic"]["segments"]]}
                    for r in results},
        "signals": {"weights": WEIGHTS, "measured": measured},
        "candidates": len(allc), "seconds": round(time.time() - t_start, 2), "notes": notes,
        "moments": moments,
    }
    return doc


def _moment(r: Dict[str, Any], c: Dict[str, Any], rk: int) -> Dict[str, Any]:
    words, sents, lang = r["words"], r["sents"], r["lang"]
    a, b, i, j = c["a"], c["b"], c["i"], c["j"]
    why = list(c["hook_why"][:2])
    if c.get("lines", 0) >= 0.4:
        why += c["lines_why"][:2]
    if c["events_why"]:
        why.append(", ".join(c["events_why"][:2]))
    if c.get("energy") is not None and c["energy"] >= 0.7:
        bits = []
        if c.get("e_level") is not None and c["e_level"] >= 1.0:
            bits.append("%.0f dB louder than the speaker's median" % c["e_level"])
        if c.get("e_pitch") is not None and c["e_pitch"] >= 3.0:
            bits.append("lively pitch")
        if c.get("e_rate") is not None and c["e_rate"] >= 1.1:
            bits.append("faster than usual")
        why.append("energy: " + (", ".join(bits) if bits else "above most of the recording"))
    if c.get("cut_answer"):
        why.append("the answer goes on after the end: check it")
    elif c["complete"] >= 0.9:
        why.append("a complete thought (%s)" % ("one full turn" if c["new_turn"] and c["end_turn"] else
                                                "clean start and end"))
    elif c.get("cont"):
        why.append("starts on \"%s\": check it stands alone" % c["cont"])
    if c["topic_frac"] >= 0.99 and c.get("keywords"):
        why.append("one topic (%s)" % ", ".join(c["keywords"]))
    if c["long_pause"] >= 1.5:
        why.append("a %.1f s pause inside (trimmed in the clip)" % c["long_pause"])
    voices = {k: v for k, v in c["speakers"].items() if v >= 0.1}
    main = next(iter(c["speakers"]))
    if len(voices) <= 1:
        why.append("one speaker (%s)" % main)
    else:
        why.append("%d speakers" % len(voices))
    if c.get("housekeeping"):
        why.append("housekeeping (\"%s\"): introductions, thanks or logistics rank lower" % c["housekeeping"][0])
    last = words[sents[j]["a"]:b + 1]
    closing = (" ... " if len(last) > 16 else "") + _text(last[-16:])
    txt = _text(words[a:b + 1])
    return {"id": "m%d" % rk, "rank": rk, "score": round(c["score"], 3), "source": r["src"]["key"],
            "transcript": str(r["src"]["transcript"]),
            "start": round(float(words[a]["start"]), 3), "end": round(float(words[b]["end"]), 3),
            "span": round(c["span"], 2), "duration": round(c["est"], 1),
            "words": [words[a].get("id"), words[b].get("id")], "title": _title(words, sents, i, j, lang, r["punct"]),
            "opening": c["opening"], "closing": closing.strip(), "keywords": c.get("keywords") or [],
            "signals": c["signals"], "why": why, "speakers": c["speakers"], "events": c["event_list"],
            "topic": c["seg"], "fillers": c["fillers"], "housekeeping": c.get("housekeeping") or [], "text": txt}


# ------------------------------------------------------------------------------------------------ output

def format_text(doc: Dict[str, Any], out: Optional[Path] = None) -> str:
    lines = []
    for k, s in doc["sources"].items():
        lines.append("%s: %s, %d sentences, %d topic segment(s), %d candidates" % (
            k, U.fmt_time(s["duration"]), s["sentences"], len(s["topics"]), s["candidates"]))
    m = doc["signals"]["measured"]
    lines.append("signals: %s%s" % (", ".join(k for k in WEIGHTS if m.get(k)),
                                    "; not measured: %s" % ", ".join(k for k in WEIGHTS if not m.get(k))
                                    if not all(m.get(k) for k in WEIGHTS) else ""))
    lines.append("")
    lines.append(" #  id   score  source time         clip    title")
    for mo in doc["moments"]:
        lines.append("%2d  %-4s %5.0f  %-20s %5.0f s  %s" % (
            mo["rank"], mo["id"], mo["score"] * 100, "%s-%s" % (_clock(mo["start"]), _clock(mo["end"])),
            mo["duration"], mo["title"]))
        lines.append("                  opens: \"%s\"" % mo["opening"])
        if mo["why"]:
            lines.append("                  why:   %s" % "; ".join(mo["why"]))
    if not doc["moments"]:
        lines.append("  (no candidate: every run of whole sentences is shorter than --min or longer than --max)")
    for n in doc.get("notes") or []:
        lines.append("note: %s" % n)
    lines.append("")
    lines.append("suggestions only: read each moment's text in the JSON, keep the ones that stand alone (set "
                 "\"pick\": true, or pass --pick), move start/end if needed (edges snap to whole words)")
    return "\n".join(lines)

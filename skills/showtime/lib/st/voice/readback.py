"""Read-back: the voice-over is heard again and compared with the script, so a name said wrong is caught
before it ships.

The script can spell a name right and the voice still say it wrong (a respelling "Open A I" reads the lone
"A" as the article, and the voice swallows it: viewers hear "open eye"). `voice script` and `voice say`
transcribe what they wrote with the local recognizer (`showtime transcribe`'s Parakeet, cached by the line's
audio, so an unchanged line costs nothing), line the words that were heard up with the script sound by
sound, and list every word that matters and was heard differently:

  names       capitalised words inside a sentence (and the same word at a sentence start), camelCase
              (OpenAI, GitHub, arXiv), acronyms (SQL, GPT)
  numbers     digits and number words ("sixty-eight" and "68" are the same number)
  lexicon     words with a lexicon entry, an inline [word](/ipa/) or [word](respelling)

Harmless differences pass: case, punctuation, spelling of the same sound (colour / color), number words
against digits, and the recognizer writing the name itself ("OpenAI", "open AI" and "Open A I" are the same
letters). What fails is a sound that is missing or different: "OpenI" or "open eye" for OpenAI.

Comparison: both sides become phonemes (espeak-ng, the voice's own front end; the script side is exactly
what the voice was told, lexicon overrides included), aligned with an edit distance. A word passes when
the recognizer wrote its letters, or the same number, or every one of its sounds was heard.

A recognizer can also respell a rare name the voice said right (Parakeet writes "JSO" for a good "JSON").
So each line with a flagged word is heard once more by a second recognizer when one is installed (Whisper
small.en for English): `confirmed` is true when it also hears the word differently, false when it hears it as
written. A person who listened to a flagged word clears it in showtime.json, `"readback": {"ok": ["JSON"]}`.

qa runs the same check on the project's voice/vo.wav (reusing voice/readback.json when it belongs to that
file) and lists the words as `readback`: WARN, and FAIL only for a name in the title, the brand or the
project's lexicon that the second recognizer also hears differently. review-pack writes the table into the
critic's audio.txt. SHOWTIME_READBACK=0 turns it off.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple

READBACK_VERSION = 1
FILE = "readback.json"
NOT_INSTALLED = "the speech recognizer is not installed"

# ------------------------------------------------------------------ switches


def enabled() -> bool:
    return os.environ.get("SHOWTIME_READBACK", "1").strip().lower() not in ("0", "off", "no", "false")


def asr_ready(lang: str) -> Tuple[bool, str]:
    """(usable, why not): the local recognizer is installed and covers the language. Never downloads."""
    base = (lang or "en").split("-")[0].lower()
    try:
        from ..footage import transcribe as T
        from ..footage.asr_models import PARAKEET_V3_LANGS
    except Exception as e:  # noqa: BLE001 - a missing optional dependency only skips the read-back
        return False, "the speech recognizer cannot load (%s)" % str(e).splitlines()[0][:80]
    if base not in PARAKEET_V3_LANGS:
        return False, "the local recognizer (Parakeet) does not cover language %r" % base
    try:
        with _quiet():
            eng, name = T.choose_model("auto", base)
        if not T._installed(eng, name):
            return False, "%s (%s)" % (NOT_INSTALLED, fetch_hint(name))
    except Exception as e:  # noqa: BLE001
        return False, "the speech recognizer cannot load (%s)" % str(e).splitlines()[0][:80]
    return True, ""


def fetch_hint(name: str = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8") -> str:
    """The command that installs the recognizer the read-back uses (never run on its own: ~490 MB)."""
    try:
        from ..footage import asr_models
        from ..footage.transcribe import PARAKEET_ITEMS
        item = asr_models.ITEMS[PARAKEET_ITEMS.get(name, "parakeet-v3")]["item"]
    except Exception:  # noqa: BLE001
        item = "parakeet-tdt-0.6b-v3-int8"
    return "showtime setup --fetch %s, about 490 MB" % item


@contextlib.contextmanager
def _quiet() -> Iterator[None]:
    """Hold transcribe's progress lines back (only warnings show)."""
    from .. import common
    old = common._LOG_LEVEL
    if os.environ.get("SHOWTIME_DEBUG") != "1":
        common._LOG_LEVEL = "warn"
    try:
        yield
    finally:
        common._LOG_LEVEL = old


# ------------------------------------------------------------------ phonemes

_STRIP = str.maketrans("", "", "ˈˌːˑ‿-'’ ̩̯̃")
_EQUIV_ALL = [("ɚ", "əɹ"), ("ɝ", "ɜɹ"), ("ɐ", "ə"), ("ᵻ", "ɪ"), ("ɫ", "l"), ("ɜ", "ə"), ("ʌ", "ə"), ("ʔ", "t"),
              ("ɡ", "g"), ("r", "ɹ"), ("əʊ", "oʊ")]
_EQUIV = {"en": [("ɾ", "t")], "es": [("β", "b"), ("ð", "d"), ("ɣ", "g"), ("ɹ", "ɾ")]}
_SYM = re.compile(r"oʊ|eɪ|aɪ|aʊ|ɔɪ|tʃ|dʒ|.", re.S)
_VOWEL = set("aeiouyæɑɒəɛɜɪʊɔøœɯɤʏɵɘɞɨʉ")


def symbols(ipa: str, lang: str = "en") -> List[str]:
    """IPA -> comparable sound symbols: stress, length and spaces dropped, near-identical sounds merged."""
    s = unicodedata.normalize("NFC", ipa or "").translate(_STRIP)
    base = (lang or "en").split("-")[0]
    for a, b in _EQUIV.get(base, []) + _EQUIV_ALL:
        s = s.replace(a, b)
    if base == "es":
        s = s.replace("ɹ", "r").replace("ɾ", "r")
    s = re.sub(r"(?<=[tdnszlθ])j(?=u)", "", s)          # "new", "sudo": with or without the y sound
    out: List[str] = []
    for m in _SYM.finditer(s):
        sym = m.group(0)
        if sym.isspace() or (out and out[-1] == sym and not _is_vowel(sym)):
            continue                                    # a doubled consonant is one sound ("ONNX": ŋŋ)
        out.append(sym)
    if base == "en":                # British and American alike: an r before a consonant or at the end is dropped
        out =[x for i, x in enumerate(out) if x != "ɹ" or (i + 1 < len(out) and _is_vowel(out[i + 1]))]
    return out


_VOICING = {frozenset(p) for p in (("t", "d"), ("p", "b"), ("k", "g"), ("s", "z"), ("f", "v"), ("θ", "ð"),
                                    ("tʃ", "dʒ"), ("ʃ", "ʒ"))}


def _soft(a: Optional[str], b: Optional[str], span: int) -> bool:
    """An edit an accent or the recognizer's spelling explains: a vowel's quality in a word of 5+ sounds
    ("JSON" heard "Jason"), a voicing pair in a word of 4+ sounds ("Cuda" written "Cuta"), a y sound. A short
    name keeps every sound ("Claude" heard "cloud" fails)."""
    if a is None or b is None:
        return (a or b) == "j"
    if _is_vowel(a) and _is_vowel(b):
        return span >= 5
    return frozenset((a, b)) in _VOICING and span >= 4


def _told_wrong(toks: list, idx: Sequence[int], ph: List[List[str]], lang: str) -> List[str]:
    """Letters spelled out inside a name ("Open A I") that the voice is told to read as a word: espeak reads a
    lone "A" between capitals as the article ("uh"). -> the letters whose sounds differ from their names."""
    if len(idx) < 2:
        return []
    from . import espeak
    out = []
    for x in idx:
        c = toks[x].core
        if len(c) == 1 and c.isalpha() and c.isupper() and not (toks[x].ipa or toks[x].say):
            if ph[x] != symbols(espeak.phonemize([c], lang)[0], lang):
                out.append(c)
    return out


def _is_vowel(sym: str) -> bool:
    return sym[:1] in _VOWEL


def _engine():
    from .engines.kokoro import KokoroEngine
    return KokoroEngine()


def owned_phonemes(tokens: list, lang: str, lexicon=None) -> List[List[str]]:
    """Per token, the sound symbols the voice is given for it (in context: espeak-ng on the phrase, the
    lexicon's IPA spliced in; the same front end Kokoro reads)."""
    from .engines.kokoro import STRESS, _is_letter
    if not tokens:
        return []
    stream, owners = _engine().phoneme_stream(tokens, lang, lexicon)
    raw = [""] * len(tokens)
    for c, o in zip(stream, owners):
        if 0 <= o < len(tokens) and (_is_letter(c) or c in STRESS):
            raw[o] += c
    return [symbols(r, lang) for r in raw]


# ------------------------------------------------------------------ letters and numbers

def letters(s: str) -> str:
    """Lower-case letters and digits only, accents dropped ("Open A I" -> "openai", "Colour's" -> "colours")."""
    t = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in t.casefold() if c.isalnum() and not unicodedata.combining(c))


_EN_NUM: Dict[str, Tuple[int, str]] = {}
for _i, _w in enumerate(["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]):
    _EN_NUM[_w] = (_i, "unit")
for _i, _w in enumerate(["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
                         "eighteen", "nineteen"]):
    _EN_NUM[_w] = (10 + _i, "teen")
for _i, _w in enumerate(["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]):
    _EN_NUM[_w] = (20 + 10 * _i, "tens")
_EN_NUM.update({"hundred": (100, "hundred"), "thousand": (1000, "scale"), "million": (10 ** 6, "scale"),
                "billion": (10 ** 9, "scale")})
_ES_NUM: Dict[str, Tuple[int, str]] = {}
for _i, _w in enumerate(["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve"]):
    _ES_NUM[_w] = (_i, "unit")
_ES_NUM.update({"un": (1, "unit"), "una": (1, "unit")})
for _i, _w in enumerate(["diez", "once", "doce", "trece", "catorce", "quince", "dieciseis", "diecisiete",
                         "dieciocho", "diecinueve", "veinte", "veintiuno", "veintidos", "veintitres",
                         "veinticuatro", "veinticinco", "veintiseis", "veintisiete", "veintiocho", "veintinueve"]):
    _ES_NUM[_w] = (10 + _i, "teen")
_ES_NUM["veintiun"] = (21, "teen")
for _i, _w in enumerate(["treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"]):
    _ES_NUM[_w] = (30 + 10 * _i, "tens")
for _v, _w in ((100, "cien"), (100, "ciento"), (200, "doscientos"), (300, "trescientos"), (400, "cuatrocientos"),
               (500, "quinientos"), (600, "seiscientos"), (700, "setecientos"), (800, "ochocientos"),
               (900, "novecientos")):
    _ES_NUM[_w] = (_v, "hundreds")
_ES_NUM.update({"mil": (1000, "scale"), "millon": (10 ** 6, "scale"), "millones": (10 ** 6, "scale")})
_NUM = {"en": _EN_NUM, "es": _ES_NUM}
_JOIN = {"en": {"and"}, "es": {"y"}}
_POINT = {"en": {"point"}, "es": {"coma", "punto"}}
_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")


def _plain(w: str) -> str:
    t = unicodedata.normalize("NFKD", w.casefold())
    return "".join(c for c in t if not unicodedata.combining(c)).strip(".,;:!?…\"“”'’()¿¡")


def _parts(word: str) -> List[str]:
    return [p for p in re.split(r"[-‐–\s]+", _plain(word)) if p]


def is_number(word: str, lang: str) -> bool:
    ps = _parts(word)
    table = _NUM.get(lang.split("-")[0], {})
    return bool(ps) and all(_DIGITS.fullmatch(p) or p in table for p in ps) and any(c.isalnum() for c in word)


def number_value(words: Sequence[str], lang: str) -> Optional[str]:
    """The digits a run of number words or numerals says: "sixty-eight" -> "68", "twenty eighteen" and
    "two thousand and eighteen" -> "2018", "three point five" -> "3.5". None when a word is not a number."""
    bl = lang.split("-")[0]
    table = _NUM.get(bl, {})
    chunks: List[str] = []
    st = {"total": 0, "cur": 0, "last": None, "open": False}

    def brk() -> None:
        if st["open"]:
            chunks.append(str(st["total"] + st["cur"]))
        st.update(total=0, cur=0, last=None, open=False)

    for w in words:
        for p in _parts(w):
            if _DIGITS.fullmatch(p):
                brk()
                q = p.replace(",", "") if bl == "en" else p.replace(".", "").replace(",", ".")
                chunks.append(q)
                continue
            if p in _JOIN.get(bl, ()) and st["open"]:
                continue
            if p in _POINT.get(bl, ()):
                brk()
                chunks.append(".")
                continue
            if p not in table:
                return None
            v, kind = table[p]
            last = st["last"]
            if kind == "hundred":
                st["cur"] = (st["cur"] or 1) * v
            elif kind == "scale":
                st["total"] += (st["cur"] or 1) * v
                st["cur"] = 0
            else:
                stop = {"unit": ("unit", "teen"), "teen": ("unit", "teen", "tens"),
                        "tens": ("unit", "teen", "tens"), "hundreds": ("unit", "teen", "tens", "hundreds")}[kind]
                if last in stop:
                    brk()
                st["cur"] += v
            st["last"] = kind
            st["open"] = True
    brk()
    out = "".join(chunks)
    return out or None


# ------------------------------------------------------------------ what matters in a script line

_SENT_END = ".!?…:"
_WEAK = {"en": {"i", "i'm", "i’m", "i'll", "i’ll", "i've", "i’ve", "i'd", "i’d"}}


def _has_upper_inside(core: str) -> bool:
    return any(c.isupper() for c in core[1:]) and any(c.islower() for c in core)


def _acronym(core: str) -> bool:
    s = re.sub(r"[^A-Za-z0-9]", "", core)
    return len(s) >= 2 and s.isupper() and any(c.isalpha() for c in s)


def capital_words(texts: Iterable[str]) -> Set[str]:
    """Words written with a capital inside a sentence anywhere in the script (casefolded): names, so the
    same word at the start of a sentence is a name too."""
    from .textnorm import plain_text, tokenize
    out: Set[str] = set()
    for text in texts:
        toks = tokenize(plain_text(text))
        for i, t in enumerate(toks):
            start = i == 0 or any(c in _SENT_END for c in toks[i - 1].trail)
            if t.core[:1].isupper() and not start:
                out.add(t.core.casefold())
    return out


def units(tokens: list, lang: str, lexicon=None, names: Set[str] = frozenset(), critical: Set[str] = frozenset(),
          weak_ok: bool = False) -> List[Dict[str, Any]]:
    """The words of a line that must be heard as written: [{idx: [token indexes], text, kind, critical}].
    A run of neighbouring name tokens is one unit ("Open A I", "Hugging Face"), a run of number words
    another ("twenty eighteen")."""
    bl = lang.split("-")[0]
    weak = _WEAK.get(bl, set())
    marks: List[Optional[str]] = []
    for i, t in enumerate(tokens):
        core = t.core
        start = i == 0 or any(c in _SENT_END for c in tokens[i - 1].trail)
        folded = core.casefold()
        kind = None
        has_lex = lexicon is not None and bool(lexicon.ipa(core, lang) or lexicon.say(core, lang))
        if t.ipa or t.say:
            kind = "respelled"
        elif has_lex:
            kind = "lexicon"
        elif re.search(r"\d", core) or is_number(core, bl):
            kind = "number"
        elif _acronym(core) and folded not in weak:
            kind = "acronym"
        elif _has_upper_inside(core):
            kind = "name"
        elif core[:1].isupper() and (not start or folded in names or folded in critical):
            kind = "weak" if folded in weak else "name"
        elif folded in critical:                     # a brand written in lower case ("showtime")
            kind = "name"
        marks.append(kind)
    out: List[Dict[str, Any]] = []
    i = 0
    n = len(tokens)
    while i < n:
        k = marks[i]
        if k is None:
            i += 1
            continue
        j = i + 1
        if k == "number":
            while j < n and not any(c in ".!?…;:," for c in tokens[j - 1].trail):
                if marks[j] == "number":
                    j += 1
                elif tokens[j].core.casefold() in _JOIN.get(bl, ()) and j + 1 < n and marks[j + 1] == "number":
                    j += 2
                else:
                    break
        else:
            while j < n and marks[j] in ("name", "acronym", "weak", "lexicon", "respelled") \
                    and not any(c in ".!?…;:,—–" for c in tokens[j - 1].trail):
                j += 1
        idx = list(range(i, j))
        kinds = [marks[x] for x in idx]
        if all(x == "weak" for x in kinds) and not weak_ok:
            i = j
            continue
        kind = next((x for x in ("respelled", "lexicon", "acronym", "name", "number") if x in kinds), "name")
        keys = {tokens[x].core.casefold() for x in idx} | {letters(" ".join(tokens[x].core for x in idx))}
        out.append({"idx": idx, "text": " ".join(tokens[x].core for x in idx), "kind": kind,
                    "critical": bool(keys & set(critical)), "keys": sorted(keys)})
        i = j
    return out


# ------------------------------------------------------------------ alignment

def _cost(a: str, b: str) -> float:
    if a == b:
        return 0.0
    va, vb = _is_vowel(a), _is_vowel(b)
    if va and vb:
        return 0.6
    if va != vb:
        return 1.4
    return 0.9


def align(s: Sequence[str], h: Sequence[str]) -> List[Tuple[Optional[int], Optional[int]]]:
    """Edit-distance alignment of two symbol lists -> [(script index | None, heard index | None)]."""
    n, m = len(s), len(h)
    D = [[0.0] * (m + 1) for _ in range(n + 1)]
    B = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        D[i][0], B[i][0] = float(i), 1
    for j in range(1, m + 1):
        D[0][j], B[0][j] = float(j), 2
    for i in range(1, n + 1):
        si = s[i - 1]
        Di, Dp = D[i], D[i - 1]
        for j in range(1, m + 1):
            best, how = Dp[j - 1] + _cost(si, h[j - 1]), 0
            d = Dp[j] + 1.0
            if d < best:
                best, how = d, 1
            ins = Di[j - 1] + 1.0
            if ins < best:
                best, how = ins, 2
            Di[j], B[i][j] = best, how
    out: List[Tuple[Optional[int], Optional[int]]] = []
    i, j = n, m
    while i > 0 or j > 0:
        how = B[i][j]
        if i > 0 and j > 0 and how == 0:
            out.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and (how == 1 or j == 0):
            out.append((i - 1, None))
            i -= 1
        else:
            out.append((None, j - 1))
            j -= 1
    out.reverse()
    return out


# ------------------------------------------------------------------ one line

def _heard_tokens(words: Sequence[Dict[str, Any]], lang: str) -> Tuple[list, List[int]]:
    from .textnorm import normalize_tokens, tokenize
    toks: list = []
    owner: List[int] = []
    for k, w in enumerate(words):
        for t in tokenize(str(w.get("text") or "")):
            toks.append(t)
            owner.append(k)
    normalize_tokens(toks, lang)          # never merges tokens in English; keep the owner list in step
    if len(owner) != len(toks):
        owner = (owner + [owner[-1] if owner else 0] * len(toks))[:len(toks)]
    return toks, owner


def _bare(w: str) -> str:
    return w.strip(".,;:!?…\"“”'’()¿¡—–")


def _say_forms(t, lexicon, lang: str) -> List[str]:
    forms = [t.core]
    if t.say:
        forms.append(t.say)
    elif lexicon is not None:
        v = lexicon.say(t.core, lang)
        if v:
            forms.append(v)
    return forms


def compare_line(text: str, heard: Sequence[Dict[str, Any]], lang: str = "en", lexicon=None,
                 names: Set[str] = frozenset(), critical: Set[str] = frozenset(),
                 script_ph: Optional[Tuple[list, List[List[str]]]] = None) -> Dict[str, Any]:
    """Line up one script line (markup allowed) with the words heard: {script, heard, checked, suspects}.
    heard: [{text, start, end}] in seconds from the line's start (or any clock: suspects keep it)."""
    from .textnorm import normalize_tokens, plain_text, split_pauses, tokenize
    if script_ph is None:
        toks = tokenize(" ".join(seg.text for seg in split_pauses(text)))
        normalize_tokens(toks, lang)
        ph = owned_phonemes(toks, lang, lexicon)
    else:
        toks, ph = script_ph
    us = units(toks, lang, lexicon, names, critical)
    htoks, howner = _heard_tokens(heard, lang)
    hph = owned_phonemes(htoks, lang, None) if htoks else []
    S = [(sym, i) for i, syms in enumerate(ph) for sym in syms]
    H = [(sym, howner[k]) for k, syms in enumerate(hph) for sym in syms]
    pairs = align([x[0] for x in S], [x[0] for x in H])
    heard_text = " ".join(str(w.get("text") or "") for w in heard).strip()
    out: Dict[str, Any] = {"script": plain_text(text), "heard": heard_text, "checked": len(us), "suspects": []}
    for u in us:
        want = set(u["idx"])
        pos = [k for k, (_, ti) in enumerate(S) if ti in want]
        if not pos:
            continue
        lo, hi = pos[0], pos[-1]
        span = hi - lo + 1
        edits, soft, got = 0, 0, []
        hsyms: List[str] = []
        last_s = -1
        for si, hj in pairs:
            if si is not None:
                last_s = si
            inside = (si is not None and lo <= si <= hi) or (si is None and lo <= last_s < hi)
            if not inside:
                continue
            a = S[si][0] if si is not None else None
            b = H[hj][0] if hj is not None else None
            if hj is not None:
                hsyms.append(b)
                if H[hj][1] not in got:
                    got.append(H[hj][1])
            if a != b:
                if _soft(a, b, span):
                    soft += 1
                else:
                    edits += 1
        got.sort()
        hw = [str(heard[k].get("text") or "") for k in got]
        span_syms = [S[k][0] for k in range(lo, hi + 1)]
        told = _told_wrong(toks, u["idx"], ph, lang)
        ok = edits == 0 and soft <= 1 and not told
        how = "sounds" if ok else ""
        if not ok and not told:
            forms = {letters(" ".join(_say_forms(toks[x], lexicon, lang)[0] for x in u["idx"]))}
            forms |= {letters(f) for x in u["idx"] for f in _say_forms(toks[x], lexicon, lang)[1:]
                      if len(u["idx"]) == 1}
            forms.discard("")
            runs = [" ".join(hw[a:b]) for a in range(len(hw)) for b in range(a + 1, len(hw) + 1)]
            if any(letters(r) in forms for r in runs):
                ok, how = True, "letters"
            elif u["kind"] == "number":
                v = number_value([toks[x].core for x in u["idx"]], lang)
                if v and any(number_value(hw[a:b], lang) == v for a in range(len(hw))
                             for b in range(a + 1, len(hw) + 1)):
                    ok, how = True, "number"
        if ok:
            continue
        t = None
        if got:
            t = heard[got[0]].get("start")
        out["suspects"].append({
            "word": u["text"], "heard": " ".join(x for x in (_bare(w) for w in hw) if x), "kind": u["kind"],
            "critical": u["critical"], "keys": u["keys"], "t": round(float(t), 3) if t is not None else None,
            "said": "".join(span_syms), "heard_sounds": "".join(hsyms), "lone_a": "A" in told, "told": told})
    return out


# ------------------------------------------------------------------ hearing the audio

def _cache_dir() -> Path:
    from ..common import home
    d = home() / "cache" / "voice" / "readback"
    d.mkdir(parents=True, exist_ok=True)
    return d


def audio_key(audio: Any, sr: int) -> str:
    """Content hash of a line's raw speech (its cache key: mastering the whole voice-over does not change it)."""
    import numpy as np
    h = hashlib.sha256(b"rb1:%d:" % int(sr))
    h.update(np.ascontiguousarray(np.asarray(audio, dtype=np.float32)).tobytes())
    return h.hexdigest()[:24]


def model_name(model: str, lang: str) -> str:
    """The recognizer `model` resolves to for a language ("auto" follows SHOWTIME_ASR_MODEL): its cache name."""
    try:
        from ..footage import transcribe as T
        with _quiet():
            return os.path.basename(str(T.choose_model(model, lang)[1]))
    except Exception:  # noqa: BLE001
        return re.sub(r"[^\w.-]+", "_", str(model or "auto"))


def heard_words(wav: Path, lang: str, key: Optional[str] = None, model: str = "auto") -> List[Dict[str, Any]]:
    """What a local recognizer hears in a file: [{text, start, end}] (seconds from the file's start).
    Cached by `key` (else the file's content) and the recognizer, so an unchanged line is never transcribed
    twice by the same model, and a change of model (SHOWTIME_ASR_MODEL, an update) hears it again."""
    from ..footage import transcribe as T
    from ..footage.util import quick_hash
    base = (lang or "en").split("-")[0]
    k = "%s-%s-%s" % (key or quick_hash(wav), base, model_name(model, base))
    cf = _cache_dir() / (k + ".json")
    if cf.is_file():
        try:
            doc = json.loads(cf.read_text(encoding="utf-8"))
            if isinstance(doc.get("words"), list):
                return doc["words"]
        except (OSError, ValueError):
            pass
    tmp = _cache_dir() / (k + ".asr.json")
    with _quiet():
        doc, _ = T.transcribe(wav, model=model, language=base, events="off", refine=False, gap_scan=False,
                              separate="off", use_stem=False, out_path=tmp, edit_dir=_cache_dir())
    words = [{"text": str(w["text"]), "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3)}
             for w in doc.get("words") or [] if w.get("type") == "word"]
    from ..common import write_json
    write_json(cf, {"words": words, "model": doc.get("model"), "created": time.strftime("%Y-%m-%dT%H:%M:%S")})
    try:
        tmp.unlink()
    except OSError:
        pass
    return words


# ------------------------------------------------------------------ a second opinion

_LABEL = {"whisper": "Whisper %s", "parakeet": "Parakeet", "crisper": "CrisperWhisper %s"}


def _recognizer_ready(engine: str, name: str) -> bool:
    """The model and everything its engine needs are installed (never downloads)."""
    try:
        from .. import lazy
        from ..footage import transcribe as T
        if not T._installed(engine, name):
            return False
        man = lazy.manifest()
        pips = man.get("lazy_pip") or {}
        return all(lazy.pip_ready(c, man) if c in pips else lazy.item_ready(c)
                   for c in lazy.asr_components(engine, name))
    except Exception:  # noqa: BLE001
        return False


def second_recognizer(lang: str) -> Optional[Dict[str, str]]:
    """{model, label} of an installed recognizer other than the read-back's own, to hear a flagged line again:
    Whisper small.en (English), small, turbo, else Parakeet when the first one is Whisper. None when there is none."""
    base = (lang or "en").split("-")[0].lower()
    try:
        from ..footage import transcribe as T
        from ..footage.asr_models import PARAKEET_V3_LANGS
        first = model_name("auto", base)
    except Exception:  # noqa: BLE001
        return None
    cands = (["small.en"] if base == "en" else []) + ["small", "turbo"] + (
        ["parakeet-v3"] if base in PARAKEET_V3_LANGS else [])
    for m in cands:
        eng, name = T.MODELS[m]
        if os.path.basename(name) != first and _recognizer_ready(eng, name):
            lab = _LABEL.get(eng, "%s")
            return {"model": m, "label": lab % os.path.basename(name) if "%s" in lab else lab}
    return None


def second_opinion(lines: Sequence[Dict[str, Any]], suspects: Sequence[Dict[str, Any]], lexicon=None,
                   critical: Set[str] = frozenset(), hear2: Any = None, label: str = "") -> None:
    """Hear every line with a suspect once more (hear2(line) -> words) and mark each suspect: "confirmed"
    True when the second recognizer also hears the word differently, False when it hears it as written."""
    names = capital_words([str(ln.get("text") or "") for ln in lines])
    by_id = {str(ln.get("id")): ln for ln in lines}
    for lid in dict.fromkeys(str(s.get("line")) for s in suspects):
        ln = by_id.get(lid)
        mine = [s for s in suspects if str(s.get("line")) == lid]
        if ln is None:
            continue
        lang = str(ln.get("lang") or "en-us")
        try:
            heard = hear2(ln) or []
        except Exception as e:  # noqa: BLE001 - a second opinion, never a reason to fail
            for s in mine:
                s["second"] = {"by": label, "error": (str(e).splitlines() or [type(e).__name__])[0][:120]}
            continue
        text = str(ln.get("text") or "")
        res = compare_line(text, heard, lang, lexicon, names, critical, script_ph=_line_tokens(text, lang, lexicon))
        again = {x["word"]: x for x in res["suspects"]}
        for s in mine:
            x = again.get(s["word"])
            s["confirmed"] = x is not None
            s["second"] = {"by": label, "heard": x["heard"] if x else None, "line": res["heard"]}


def _project_cfg(project_dir: Optional[Path]) -> Dict[str, Any]:
    from ..common import read_json
    if project_dir is None:
        return {}
    d = Path(project_dir)
    for c in (d / "showtime.json", d.parent / "showtime.json"):
        if c.is_file():
            cfg = read_json(c, {}) or {}
            return cfg if isinstance(cfg, dict) else {}
    return {}


def cleared_words(project_dir: Optional[Path]) -> List[str]:
    """Words a person listened to and found right: showtime.json "readback": {"ok": ["JSON", ...]}."""
    rb = _project_cfg(project_dir).get("readback")
    ok = rb.get("ok") if isinstance(rb, dict) else None
    return [str(w) for w in ok if isinstance(w, str) and w.strip()] if isinstance(ok, list) else []


def apply_cleared(rep: Dict[str, Any], ok: Sequence[str]) -> Dict[str, Any]:
    """Move the suspects a person cleared (by spelling or letters: "Open A I" clears "OpenAI") into
    rep["cleared"]; the others stay suspects. Summary updated."""
    if rep.get("skipped"):
        return rep
    keys = {w.casefold() for w in ok} | {letters(w) for w in ok}
    keys.discard("")
    every = list(rep.get("suspects") or []) + list(rep.get("cleared") or [])
    every.sort(key=lambda s: (s.get("t") is None, s.get("t") or 0.0))
    hit = lambda s: str(s.get("word") or "").casefold() in keys or letters(str(s.get("word") or "")) in keys  # noqa: E731
    rep["suspects"] = [s for s in every if not hit(s)]
    rep["cleared"] = [s for s in every if hit(s)]
    if not rep["cleared"]:
        rep.pop("cleared")
    lines_sus = {}
    for s in rep["suspects"]:
        lines_sus.setdefault(str(s.get("line")), []).append(s["word"])
    for ln in rep.get("lines") or []:
        if "suspects" in ln:
            ln["suspects"] = lines_sus.get(str(ln.get("id")), [])
    rep["summary"] = summary(rep)
    return rep


# ------------------------------------------------------------------ names that must be right

def critical_names(project_dir: Optional[Path], lexicon=None) -> Set[str]:
    """Casefolded names a misheard voice must never ship: the name-like words of showtime.json's title,
    the brand's name (brand.json) and the words of the project's own lexicon (not the built-in list)."""
    from ..common import read_json
    from .textnorm import tokenize
    out: Set[str] = set()
    d = Path(project_dir) if project_dir else None
    texts: List[str] = []
    if d is not None:
        cfg = _project_cfg(d)
        if isinstance(cfg.get("title"), str):
            texts.append(cfg["title"])
        for c in (d / "brand.json", d.parent / "brand.json"):
            if c.is_file():
                kit = read_json(c, {}) or {}
                if isinstance(kit, dict) and isinstance(kit.get("name"), str):
                    out |= {t.core.casefold() for t in tokenize(kit["name"])}
                    out.add(letters(kit["name"]))
                break
    for text in texts:
        toks = tokenize(text)
        for i, t in enumerate(toks):
            if _acronym(t.core) or _has_upper_inside(t.core) or (i > 0 and t.core[:1].isupper()
                                                                 and not any(c in _SENT_END for c in toks[i - 1].trail)):
                out.add(t.core.casefold())
    if lexicon is not None:
        from . import lexicon as lexmod
        try:
            builtin = lexmod.Lexicon().load(lexmod.BUILTIN)
        except Exception:  # noqa: BLE001
            builtin = lexmod.Lexicon()
        for k, e in lexicon.folded.items():
            if builtin.folded.get(k) != e:
                out.add(k)
        for k, e in lexicon.exact.items():
            if builtin.exact.get(k) != e:
                out.add(k.casefold())
    return {x for x in out if x}


# ------------------------------------------------------------------ whole voice-overs

def _line_tokens(text: str, lang: str, lexicon):
    from .textnorm import normalize_tokens, split_pauses, tokenize
    toks = tokenize(" ".join(seg.text for seg in split_pauses(text)))
    normalize_tokens(toks, lang)
    return toks, owned_phonemes(toks, lang, lexicon)


_READY: Dict[str, Tuple[bool, str]] = {}


def _ready(lang: str) -> Tuple[bool, str]:
    base = (lang or "en").split("-")[0].lower()
    if base not in _READY:
        _READY[base] = asr_ready(base)
    return _READY[base]


def check_lines(lines: Sequence[Dict[str, Any]], lexicon=None, critical: Set[str] = frozenset(),
                hear: Any = None, second: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The read-back of a voice-over. lines: [{id, text (source, markup allowed), lang, start, heard?}];
    hear(line) -> heard words (seconds from the line's start) for a line without "heard". Suspect times are
    absolute (line start + heard time). second: {"label", "hear"(line) -> words} of a second recognizer, which
    hears the lines with a suspect again (second_opinion)."""
    t0 = time.time()
    names = capital_words([str(ln.get("text") or "") for ln in lines])
    rows: List[Dict[str, Any]] = []
    sus: List[Dict[str, Any]] = []
    checked = 0
    for ln in lines:
        lang = str(ln.get("lang") or "en-us")
        heard = ln.get("heard")
        st = float(ln.get("start") or 0.0)
        if heard is None and hear is not None:
            ready, why = _ready(lang)
            if not ready:                          # a line in a language the recognizer does not cover
                rows.append({"id": str(ln.get("id")), "start": round(st, 3), "lang": lang,
                             "script": str(ln.get("text") or ""), "heard": None, "skipped": why, "suspects": []})
                continue
            heard = hear(ln)
        heard = heard or []
        res = compare_line(str(ln.get("text") or ""), heard, lang, lexicon, names, critical,
                           script_ph=_line_tokens(str(ln.get("text") or ""), lang, lexicon))
        checked += res["checked"]
        for s in res["suspects"]:
            s = dict(s, line=str(ln.get("id")), t=round(st + s["t"], 3) if s.get("t") is not None
                     else round(float(ln.get("speech_start", st)), 3))
            sus.append(s)
        rows.append({"id": str(ln.get("id")), "start": round(st, 3), "lang": lang, "script": res["script"],
                     "heard": res["heard"], "heard_words": [dict(w) for w in heard],
                     "suspects": [s["word"] for s in res["suspects"]]})
    if sus and second and second.get("hear"):
        second_opinion(lines, sus, lexicon, critical, second["hear"], str(second.get("label") or ""))
    rep = {"version": READBACK_VERSION, "lines": rows, "suspects": sus, "checked": checked,
           "seconds": round(time.time() - t0, 2)}
    rep["summary"] = summary(rep)
    return rep


def summary(rep: Dict[str, Any]) -> str:
    if rep.get("skipped"):
        return "read-back skipped: %s" % rep["skipped"]
    sus = rep.get("suspects") or []
    n = len(rep.get("lines") or [])
    clr = rep.get("cleared") or []
    tail = ("; cleared after listening (showtime.json readback.ok): %s" % ", ".join(
        sorted({'"%s"' % s["word"] for s in clr}))) if clr else ""
    if not sus:
        return "read-back: %d line%s heard back, %d name%s and number%s as written%s" % (
            n, "" if n == 1 else "s", rep.get("checked", 0), "" if rep.get("checked") == 1 else "s",
            "" if rep.get("checked") == 1 else "s", tail)
    return "read-back: %d word%s heard differently in %d line%s (%s)%s" % (
        len(sus), "" if len(sus) == 1 else "s", n, "" if n == 1 else "s",
        ", ".join('"%s" as "%s"' % (s["word"], s["heard"] or "nothing") for s in sus[:3]) + (" ..." if len(sus) > 3 else ""),
        tail)


def second_note(s: Dict[str, Any]) -> str:
    """What the second recognizer made of a suspect ("" when none heard it)."""
    sec = s.get("second") or {}
    by = sec.get("by") or "a second recognizer"
    if s.get("confirmed") is True:
        return "%s also hears \"%s\"" % (by, sec.get("heard") or "something else")
    if s.get("confirmed") is False:
        return "%s hears it as written" % by
    return ""


def tag(s: Dict[str, Any]) -> str:
    """The note after a suspect: a title/brand/lexicon name, and what the second recognizer heard."""
    parts = ["a name in the title, brand or lexicon"] if s.get("critical") else []
    if second_note(s):
        parts.append(second_note(s))
    return "; ".join(parts)


def is_fail(s: Dict[str, Any]) -> bool:
    """qa FAILs a suspect only when it is a title/brand/lexicon name AND a second recognizer also heard it
    differently: one recognizer alone can respell a rare name the voice said right."""
    return bool(s.get("critical")) and s.get("confirmed") is True


def fix_for(s: Dict[str, Any], clip: Optional[str] = None) -> str:
    """What to try for one suspect word (and how to clear it after listening)."""
    fix = _fix(s, clip)
    clear = ("if it sounds right when you listen, clear it: \"readback\": {\"ok\": [\"%s\"]} in showtime.json"
             % s["word"])
    if s.get("confirmed") is False:
        where = clip or "the line"
        return "%s, so the voice is likely right: listen to %s; %s. If it is wrong: %s" % (
            second_note(s), where, clear, fix)
    return "%s; %s" % (fix, clear)


def _fix(s: Dict[str, Any], clip: Optional[str] = None) -> str:
    w = s["word"]
    if s.get("lone_a"):
        one = re.sub(r"\s+", "", w)
        return ("the voice reads a lone \"A\" as the article (\"uh\") and swallows it: write the name as one word "
                "(%s) and voice it again; `showtime voice ipa \"%s\"` shows what the voice is told" % (one, one))
    if s["kind"] == "number":
        return ("write the number as the words to say (\"twenty eighteen\", \"sixty-eight\") and voice the line "
                "again; listen to %s to confirm" % (clip or "the line"))
    one = w.split()[0] if " " in w else w
    return ("`showtime voice ipa \"%s\"` shows what the voice is told; add {\"%s\": {\"say\": \"...\"}} (any voice) "
            "or {\"%s\": {\"ipa\": \"...\"}} (Kokoro) to lexicon.json next to the script, voice it again%s" % (
                w, one, one, "; listen to %s at %.1fs to confirm" % (clip, s["t"]) if clip and s.get("t") is not None
                else ""))


def report_lines(rep: Dict[str, Any], limit: int = 6) -> List[str]:
    """The short "heard back" block `voice script` / `voice say` print."""
    if rep.get("skipped"):
        return ["read-back skipped: %s" % rep["skipped"]]
    out = [rep.get("summary") or summary(rep)]
    for s in (rep.get("suspects") or [])[:limit]:
        out.append("  %s %7s  %s: \"%s\" heard as \"%s\"%s" % (
            "FAIL" if is_fail(s) else "WARN", "%.2fs" % s["t"] if s.get("t") is not None else "?", s["line"], s["word"], s["heard"] or "(nothing)",
            "  [%s]" % tag(s) if tag(s) else ""))
        out.append("        fix: %s" % fix_for(s, s.get("clip")))
    if len(rep.get("suspects") or []) > limit:
        out.append("  ... %d more in readback.json" % (len(rep["suspects"]) - limit))
    return out


def for_voice(out_dir: Path, items: Sequence[Dict[str, Any]], speeches: Sequence[Any], lexicon,
              project_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Read-back for `voice script`: every line's clip (out_dir/<file>) transcribed (cached by its raw
    speech), compared, written to out_dir/readback.json. items: the timeline lines."""
    from ..common import write_json
    lang = str(items[0].get("lang") or "en") if items else "en"
    ok, why = asr_ready(lang)
    if not ok:
        rep = {"version": READBACK_VERSION, "skipped": why, "lines": [], "suspects": [], "checked": 0}
    else:
        lines = []
        for it, sp in zip(items, speeches):
            key = audio_key(sp.audio, sp.sample_rate)
            it["audio_key"] = key
            lines.append({"id": it["id"], "text": it.get("source_text") or it["text"], "lang": it.get("lang"),
                          "start": it["start"], "speech_start": it.get("speech_start"), "file": it["file"],
                          "key": key})
        hear = lambda ln: heard_words(out_dir / ln["file"], str(ln["lang"]), ln["key"])  # noqa: E731
        rep = check_lines(lines, lexicon, critical_names(project_dir, lexicon), hear=hear,
                          second=_second(lang, lambda ln, m: heard_words(out_dir / ln["file"], str(ln["lang"]),
                                                                          ln["key"], model=m)))
        files = {ln["id"]: ln["file"] for ln in lines}
        for s in rep["suspects"]:
            s["clip"] = files.get(s["line"])
        apply_cleared(rep, cleared_words(project_dir))
    rep["summary"] = summary(rep)
    try:
        from ..footage.util import quick_hash
        vo = out_dir / "vo.wav"
        rep["vo_hash"] = quick_hash(vo) if vo.is_file() else None
    except OSError:
        rep["vo_hash"] = None
    write_json(out_dir / FILE, rep)
    return rep


def for_speech(text: str, speech: Any, wav: Path, lexicon, project_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Read-back for `voice say`: the one clip it wrote."""
    ok, why = asr_ready(speech.lang)
    if not ok:
        return {"version": READBACK_VERSION, "skipped": why, "lines": [], "suspects": [], "checked": 0,
                "summary": "read-back skipped: %s" % why}
    key = audio_key(speech.audio, speech.sample_rate)
    rep = check_lines([{"id": wav.stem, "text": text, "lang": speech.lang, "start": 0.0}], lexicon,
                      critical_names(project_dir, lexicon), hear=lambda ln: heard_words(wav, speech.lang, key),
                      second=_second(speech.lang, lambda ln, m: heard_words(wav, speech.lang, key, model=m)))
    for s in rep["suspects"]:
        s["clip"] = wav.name
    return apply_cleared(rep, cleared_words(project_dir))


def _second(lang: str, hear_with: Any) -> Optional[Dict[str, Any]]:
    """check_lines' `second`: the second recognizer (when installed) with hear_with(line, model)."""
    sec = second_recognizer(lang)
    if not sec:
        return None
    return {"label": sec["label"], "hear": lambda ln: hear_with(ln, sec["model"])}


# ------------------------------------------------------------------ qa

def script_lexicon(voice_dir: Path, tl: Dict[str, Any]):
    """The lexicon `voice script` used for this timeline (the script's own settings), else the project's."""
    from . import lexicon as lexmod
    sp = None
    src = tl.get("script")
    if isinstance(src, str) and src and not src.startswith(("showtime:", "showtime-home:")):
        cand = (voice_dir / src).resolve()
        if cand.is_file():
            sp = cand
    if sp is None:
        return lexmod.load(project_dir=voice_dir.parent)
    try:
        from .script import load_script
        cfg, _ = load_script(sp)
    except Exception:  # noqa: BLE001
        cfg = {}
    extra: List[str] = []
    inline = None
    lx = cfg.get("lexicon") if isinstance(cfg, dict) else None
    if isinstance(lx, str):
        p = Path(lx)
        extra.append(str(p if p.is_absolute() else sp.parent / p))
    elif isinstance(lx, dict):
        inline = lx
    try:
        lex = lexmod.load([e for e in extra if Path(e).is_file()], project_dir=sp.parent)
    except Exception:  # noqa: BLE001
        lex = lexmod.load(project_dir=sp.parent)
    for w, e in (inline or {}).items():
        try:
            lex.add(w, e)
        except Exception:  # noqa: BLE001
            pass
    return lex


def for_project(proj: Path, video: Optional[Path] = None, allow_asr: bool = True) -> Optional[Dict[str, Any]]:
    """The read-back of a project's voice-over (voice/timeline.json + vo.wav), in voice time. None when the
    project has no voice timeline (or it is newer than the video, so it is not what the video plays)."""
    from ..common import read_json
    from ..footage.util import quick_hash
    vd = proj / "voice"
    tp = vd / "timeline.json"
    if not tp.is_file():
        return None
    try:
        if video is not None and tp.stat().st_mtime > video.stat().st_mtime + 1:
            return None
    except OSError:
        return None
    tl = read_json(tp, {}) or {}
    items = [ln for ln in tl.get("lines") or [] if isinstance(ln, dict) and ln.get("text")]
    if not items:
        return None
    vo = vd / str(tl.get("file") or "vo.wav")
    if not vo.is_file():
        return None
    lex = script_lexicon(vd, tl)
    crit = critical_names(proj, lex)
    ok_words = cleared_words(proj)
    vo_hash = quick_hash(vo)
    lang = str(items[0].get("lang") or "en")
    lines = [{"id": ln.get("id"), "text": ln.get("source_text") or ln["text"], "lang": ln.get("lang") or lang,
              "start": float(ln.get("start") or 0.0), "speech_start": ln.get("speech_start"),
              "end": float(ln.get("end") or ln.get("start") or 0.0), "file": ln.get("file"),
              "key": ln.get("audio_key")} for ln in items]
    clips = all(ln["file"] and (vd / str(ln["file"])).is_file() for ln in lines)
    vo_words: Dict[str, List[Dict[str, Any]]] = {}

    def hear_with(ln: Dict[str, Any], model: str = "auto") -> List[Dict[str, Any]]:
        if clips:
            return heard_words(vd / str(ln["file"]), str(ln["lang"]), ln["key"], model=model)
        if model not in vo_words:
            vo_words[model] = heard_words(vo, lang, model=model)
        # a heard word belongs to the line whose speech is nearest: cut halfway through each pause
        ss = [float(it.get("speech_start", it.get("start") or 0.0)) for it in items]
        se = [float(it.get("speech_end", it.get("end") or 0.0)) for it in items]
        cut = [-1e9] + [(se[k] + ss[k + 1]) / 2 for k in range(len(items) - 1)] + [1e9]
        k = lines.index(ln)
        return [dict(w, start=round(w["start"] - ln["start"], 3), end=round(w["end"] - ln["start"], 3))
                for w in vo_words[model] if cut[k] <= (w["start"] + w["end"]) / 2 < cut[k + 1]]

    stored = read_json(vd / FILE, None) if (vd / FILE).is_file() else None
    if isinstance(stored, dict) and stored.get("version") == READBACK_VERSION and stored.get("vo_hash") == vo_hash \
            and not stored.get("skipped"):
        rep = dict(stored)
        every = list(rep.get("suspects") or []) + list(rep.get("cleared") or [])
        for s in every:
            s["critical"] = bool(set(s.get("keys") or []) & crit)
        # voice script ran without a second recognizer: hear the flagged lines again now, when one is here
        todo = [s for s in every if "confirmed" not in s]
        if todo and allow_asr:
            sec = _second(lang, hear_with)
            if sec:
                try:
                    second_opinion(lines, todo, lex, crit, sec["hear"], sec["label"])
                except Exception:  # noqa: BLE001 - a second opinion, never a reason to fail
                    pass
        rep["source"] = "voice/readback.json (written by voice script for this vo.wav)"
        return apply_cleared(rep, ok_words)
    ok, why = asr_ready(lang)
    if not ok or not allow_asr:
        return {"version": READBACK_VERSION, "skipped": why or "not run", "lines": [], "suspects": [], "checked": 0,
                "summary": "read-back skipped: %s" % (why or "not run")}
    source = "the line clips in voice/lines" if clips else "voice/%s" % vo.name
    rep = check_lines(lines, lex, crit, hear=hear_with, second=_second(lang, hear_with))
    for s in rep["suspects"]:
        s["clip"] = next((str(ln["file"]) for ln in lines if str(ln["id"]) == s["line"] and clips), "voice/" + vo.name)
    rep["source"] = source
    rep["vo_hash"] = vo_hash
    return apply_cleared(rep, ok_words)

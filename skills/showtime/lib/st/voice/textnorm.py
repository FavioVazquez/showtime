"""Text preparation for speech: markup, tokens, and read-aloud normalization.

Markup understood in any narration text ("SSML-lite"):

    [pause 0.4]  [pause 400ms]  [pause]      silence (default 0.5 s)
    [Showtime](/ʃˈoʊtaɪm/)                   inline IPA for one word (Kokoro)
    [SQL](sequel)                            inline respelling (any engine)
    <!-- stage direction -->                 ignored, never spoken

Normalization rewrites what the engines read badly ("3.5", "Dr.", "e.g.",
"showtime.dev", "v2.0", "&") into words, per language, while the caption
text keeps the original spelling.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

DEFAULT_PAUSE = 0.5
_PAUSE = re.compile(r"\[\s*(?:pause|break|silence)(?:\s*[=:]?\s*([0-9]*\.?[0-9]+)\s*(ms|s)?)?\s*\]", re.I)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_INLINE = re.compile(r"\[([^\[\]]+?)\]\(\s*(/[^()]*?/|[^()]*?)\s*\)")
PUNCT = ".,!?;:…—–-\"'“”‘’«»¡¿()[]"
SENTENCE_END = ".!?…"


@dataclass
class Token:
    text: str                    # display text, punctuation attached ("Showtime,")
    core: str                    # the word without surrounding punctuation
    lead: str = ""               # leading punctuation
    trail: str = ""              # trailing punctuation
    ipa: Optional[str] = None    # forced pronunciation (inline or lexicon)
    say: Optional[str] = None    # forced respelling
    spoken: str = ""             # normalized text an engine should read


@dataclass
class Segment:
    """Speech between two pauses."""
    text: str
    pause_after: float = 0.0
    overrides: List[Tuple[str, str, str]] = field(default_factory=list)  # (display, kind, value)


def parse_pause(m: "re.Match[str]") -> float:
    val, unit = m.group(1), (m.group(2) or "").lower()
    if not val:
        return DEFAULT_PAUSE
    v = float(val)
    if unit == "ms" or (not unit and v > 20):
        v /= 1000.0
    return max(0.0, min(v, 30.0))


def strip_comments(text: str) -> str:
    return _COMMENT.sub(" ", text)


def split_pauses(text: str) -> List[Segment]:
    """Split on [pause] markers. A leading pause becomes an empty segment."""
    text = strip_comments(text)
    segs: List[Segment] = []
    pos = 0
    for m in _PAUSE.finditer(text):
        chunk = text[pos:m.start()]
        p = parse_pause(m)
        if chunk.strip() or not segs:
            segs.append(Segment(" ".join(chunk.split()), p))
        else:
            segs[-1].pause_after += p
        pos = m.end()
    tail = " ".join(text[pos:].split())
    if tail or not segs:
        segs.append(Segment(tail, 0.0))
    return segs


def plain_text(text: str) -> str:
    """The caption text: markup removed, inline pronunciations reduced to their word."""
    t = _PAUSE.sub(" ", strip_comments(text))
    t = _INLINE.sub(lambda m: m.group(1), t)
    return " ".join(t.split())


def _split_affixes(tok: str) -> Tuple[str, str, str]:
    i, j = 0, len(tok)
    while i < j and (tok[i] in PUNCT or unicodedata.category(tok[i]).startswith("P")):
        i += 1
    while j > i and (tok[j - 1] in PUNCT or unicodedata.category(tok[j - 1]).startswith("P")):
        j -= 1
    return tok[:i], tok[i:j], tok[j:]


def tokenize(text: str) -> List[Token]:
    """Whitespace tokens with inline [word](/ipa/) or [word](respell) overrides.

    Pure punctuation tokens ("—", "&" is kept as a word) are attached to the
    previous token's display text so every Token is a spoken word.
    """
    marks: List[Tuple[str, Optional[str], Optional[str]]] = []

    def sub(m: "re.Match[str]") -> str:
        word, val = m.group(1).strip(), m.group(2).strip()
        if val.startswith("/") and val.endswith("/") and len(val) > 2:
            marks.append((word, val[1:-1], None))
        else:
            marks.append((word, None, val))
        return " \u0000%d\u0000 " % (len(marks) - 1)

    work = _INLINE.sub(sub, text)
    out: List[Token] = []
    pending_lead = ""
    parts = work.split()
    k = 0
    while k < len(parts):
        raw = parts[k]
        k += 1
        m = re.fullmatch(r"\u0000(\d+)\u0000", raw)
        if m:
            word, ipa, say = marks[int(m.group(1))]
            trail = ""
            # punctuation right after the markup: "[Showtime](/../),"
            while k < len(parts) and all(c in PUNCT for c in parts[k]):
                trail += parts[k]
                k += 1
            out.append(Token(text=pending_lead + word + trail, core=word, lead=pending_lead, trail=trail,
                             ipa=ipa, say=say))
            pending_lead = ""
            continue
        if raw.startswith("\u0000"):
            continue
        if raw in ("&", "+", "=", "@", "#", "%"):
            out.append(Token(text=pending_lead + raw, core=raw, lead=pending_lead))
            pending_lead = ""
            continue
        lead, core, trail = _split_affixes(raw)
        if not any(ch.isalnum() for ch in core):
            # pure punctuation: glue to the neighbour
            if out:
                out[-1].text += (" " + raw) if raw in "—–" else raw
                out[-1].trail += raw
            else:
                pending_lead += raw
            continue
        out.append(Token(text=pending_lead + raw, core=core, lead=pending_lead + lead, trail=trail))
        pending_lead = ""
    return out


# --------------------------------------------------------------------------
# Language-aware normalization of one token's core
# --------------------------------------------------------------------------

_POINT = {"en": "point", "es": "punto", "fr": "virgule", "it": "virgola", "pt": "vírgula", "hi": "dashamlav",
          "de": "Komma", "ja": "ten", "zh": "dian"}
_COMMA = {"es": "coma", "fr": "virgule", "it": "virgola", "pt": "vírgula", "de": "Komma"}   # decimal comma
_GROUPING = ("es", "fr", "it", "pt", "de")    # "60 000" / "60.000" group thousands; "13,7" is a decimal
_DOT = {"en": "dot", "es": "punto", "fr": "point", "it": "punto", "pt": "ponto", "de": "Punkt"}
_AND = {"en": "and", "es": "y", "fr": "et", "it": "e", "pt": "e", "de": "und"}
_VERSION = {"en": "version", "es": "versión", "fr": "version", "it": "versione", "pt": "versão", "de": "Version"}
_ABBR = {
    "en": {"dr.": "doctor", "mr.": "mister", "mrs.": "missus", "ms.": "miz", "st.": "saint", "vs.": "versus",
           "vs": "versus", "e.g.": "for example", "i.e.": "that is", "etc.": "et cetera", "approx.": "approximately",
           "no.": "number", "min.": "minutes", "sec.": "seconds", "jr.": "junior", "sr.": "senior",
           "inc.": "incorporated", "ltd.": "limited", "w/": "with", "w/o": "without"},
    "es": {"sr.": "señor", "sra.": "señora", "srta.": "señorita", "dr.": "doctor", "dra.": "doctora",
           "etc.": "etcétera", "ej.": "ejemplo", "p.ej.": "por ejemplo", "núm.": "número", "aprox.": "aproximadamente",
           "ud.": "usted", "uds.": "ustedes", "vs.": "contra"},
    "fr": {"m.": "monsieur", "mme": "madame", "etc.": "et cetera", "p.ex.": "par exemple"},
    "it": {"sig.": "signor", "dott.": "dottore", "ecc.": "eccetera"},
    "pt": {"sr.": "senhor", "sra.": "senhora", "dr.": "doutor", "etc.": "etcétera"},
}
_YEAR_CTX = re.compile(r"(?i)^(in|since|by|until|till|from|of|year|before|after|circa|during|"
                       r"january|february|march|april|may|june|july|august|september|october|november|december)$")
_ONES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
         "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def en_number(n: int) -> str:
    """English words for 0 <= n < 10**12 (used for alignment and years)."""
    if n == 0:
        return "zero"
    parts = []
    for div, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand"), (1, "")):
        q, n = divmod(n, div)
        if not q:
            continue
        h, r = divmod(q, 100)
        words = []
        if h:
            words += [_ONES[h], "hundred"]
        if r >= 20:
            words.append(_TENS[r // 10] + ("-" + _ONES[r % 10] if r % 10 else ""))
        elif r:
            words.append(_ONES[r])
        if name:
            words.append(name)
        parts.append(" ".join(words))
    return " ".join(parts)


def en_year(n: int) -> str:
    hi, lo = divmod(n, 100)
    if lo == 0:
        return en_number(hi) + " hundred"
    if lo < 10:
        return en_number(hi) + " oh " + en_number(lo)
    return en_number(hi) + " " + en_number(lo)


def base_lang(lang: str) -> str:
    lg = (lang or "en").lower()
    if lg in ("cmn",):
        return "zh"
    return lg.split("-")[0]


def normalize_core(core: str, lang: str, prev: str = "") -> str:
    """Rewrite one token's core into words the engine reads correctly."""
    bl = base_lang(lang)
    low = core.lower()
    abbr = _ABBR.get(bl, {})
    if low in abbr:
        return abbr[low]
    s = core
    # version strings: v2.0, v1.2.3
    m = re.fullmatch(r"[vV](\d+(?:\.\d+)+)", s)
    if m:
        return "%s %s" % (_VERSION.get(bl, "version"), m.group(1).replace(".", " %s " % _POINT.get(bl, "point")))
    # a glottal stop letter (the Hawaiian ʻokina, U+02BB, often typed as U+2018): silent, never spelled
    s = s.replace("\u02bb", "")
    s = re.sub(r"(?<=\w)\u2018(?=\w)", "", s)
    if s != core and not s:
        return s
    # thousands grouped with periods in comma-decimal languages: 60.000 / 1.234.567 (,5)
    if bl in _GROUPING and re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", s):
        s = s.replace(".", "")
    # decimals: 3.5 (and 3,5 in comma-decimal languages)
    if re.fullmatch(r"\d+\.\d+", s):
        a, b = s.split(".")
        return "%s %s %s" % (a, _POINT.get(bl, "point"), " ".join(b) if len(b) > 1 and bl == "en" else b)
    if bl in _GROUPING and re.fullmatch(r"\d+,\d{1,2}", s):
        a, b = s.split(",")
        return "%s %s %s" % (a, _COMMA.get(bl, "coma"), b)
    # dotted names / domains: showtime.dev, node.js
    if re.fullmatch(r"[A-Za-z][\w-]*(?:\.[A-Za-z][\w-]*)+", s) and not re.fullmatch(r"(?:[A-Za-z]\.)+[A-Za-z]?", s):
        return (" %s " % _DOT.get(bl, "dot")).join(s.split("."))
    if s == "&":
        return _AND.get(bl, "and")
    # English years in context: "in 2026" -> "twenty twenty-six"
    if bl == "en" and re.fullmatch(r"(19|20)\d\d", s) and _YEAR_CTX.match(prev or "") and s not in ("2000",):
        n = int(s)
        if not (2000 < n < 2010):
            return en_year(n)
    # emoji and symbols the engines cannot read
    s = "".join(ch for ch in s if unicodedata.category(ch)[0] != "S" or ch in "%$€£&+=@#°")
    return s


def merge_digit_groups(tokens: List[Token], lang: str) -> None:
    """ "60 000" (thousands grouped with a space, the RAE/SI style of es, fr, pt, it, de) is one number:
    merge the tokens so the engine reads "sesenta mil", not "sesenta, cero cero cero"."""
    if base_lang(lang) not in _GROUPING:
        return
    i = 0
    while i < len(tokens) - 1:
        t = tokens[i]
        if re.fullmatch(r"\d{1,3}", t.core) and not t.trail and not (t.ipa or t.say):
            j = i + 1
            while j < len(tokens) and re.fullmatch(r"\d{3}", tokens[j].core) and not tokens[j].lead \
                    and not (tokens[j].ipa or tokens[j].say) and not tokens[j - 1].trail:
                j += 1
            # the last group may carry a decimal part: 1 234,5
            if j < len(tokens) and j > i and re.fullmatch(r"\d{3},\d+", tokens[j].core) and not tokens[j].lead \
                    and not tokens[j - 1].trail and not (tokens[j].ipa or tokens[j].say):
                j += 1
            if j > i + 1:
                group = tokens[i:j]
                tokens[i:j] = [Token(text=" ".join(g.text for g in group), core="".join(g.core for g in group),
                                     lead=group[0].lead, trail=group[-1].trail)]
        i += 1


def normalize_tokens(tokens: List[Token], lang: str) -> None:
    """Fill Token.spoken. An abbreviation's own period is dropped from the
    spoken punctuation ("Dr. Smith" must not end a sentence). Space-grouped numbers
    ("60 000") become one token in comma-decimal languages (the list is edited in place)."""
    merge_digit_groups(tokens, lang)
    prev = ""
    abbr = _ABBR.get(base_lang(lang), {})
    for i, t in enumerate(tokens):
        if t.say:
            t.spoken = t.say
        elif t.core and t.trail.startswith(".") and (t.core.lower() + ".") in abbr:
            t.spoken = abbr[t.core.lower() + "."]
            last = i == len(tokens) - 1
            if not last:
                t.trail = t.trail[1:]
        else:
            t.spoken = normalize_core(t.core, lang, prev) if t.core else ""
        prev = t.core


def spoken_text(tokens: List[Token], keep_punct: bool = True) -> str:
    """The text an engine should read (normalized cores + punctuation)."""
    parts = []
    for t in tokens:
        core = t.spoken or t.core
        parts.append((t.lead + core + t.trail) if keep_punct else core)
    return " ".join(p for p in parts if p)


def words_per_second_estimate(text: str, wps: float = 2.6) -> float:
    """Rough reading time in seconds for planning before synthesis."""
    n = len(tokenize(plain_text(text)))
    return n / max(wps, 0.1)


def sentences(text: str) -> List[str]:
    """Split text at sentence ends (keeps the punctuation)."""
    parts = re.split(r"(?<=[.!?…])\s+(?=[\"“¿¡(]?[A-ZÁÉÍÓÚÑ0-9])", text.strip())
    return [p.strip() for p in parts if p.strip()]

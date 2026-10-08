"""Pronunciation lexicon: fix how brand names and jargon are spoken.

An entry gives either IPA (exact, Kokoro only) or a respelling ("say", works
with every engine), optionally per language:

    {
      "Showtime": "ʃˈoʊtaɪm",                              # IPA for every language
      "Kubernetes": {"ipa": "kˌuːbɚnˈɛtiːz"},
      "SQL": {"say": "sequel"},
      "GIF": {"ipa": {"en": "ɡˈɪf", "es": "ɡˈif"}},
      "Nginx": {"say": {"*": "engine x", "es": "enyin equis"}, "case": false}
    }

Files are merged in this order (later wins): the built-in list
(voice/lexicon.json), $SHOWTIME_LEXICON, a project `lexicon.json` or the
"pronunciations" of a `brand.json`, then files passed with --lexicon.
Matching is case-insensitive unless the entry sets "case": true. A
possessive ("Showtime's") reuses the entry and adds the "s" sound.

IPA must use Kokoro's phoneme set (the symbols espeak-ng produces); run
`showtime voice ipa "word"` to see what espeak says and edit from there.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple, Union

from ..common import ShowtimeError

PathLike = Union[str, "os.PathLike[str]"]
BUILTIN = Path(__file__).with_name("lexicon.json")


class Lexicon:
    def __init__(self) -> None:
        self.exact: Dict[str, Dict[str, Any]] = {}
        self.folded: Dict[str, Dict[str, Any]] = {}
        self.sources: list = []

    # -- loading ----------------------------------------------------------
    def add(self, word: str, entry: Any) -> None:
        if isinstance(entry, str):
            entry = {"ipa": entry}
        if not isinstance(entry, dict) or not ({"ipa", "say"} & set(entry)):
            raise ShowtimeError("lexicon entry for %r needs \"ipa\" or \"say\"" % word)
        e = dict(entry)
        e["word"] = word
        if e.get("case"):
            self.exact[word] = e
        else:
            # a later file wins: its entry replaces an earlier case-sensitive one for the same word
            for k in [k for k in self.exact if k.casefold() == word.casefold()]:
                del self.exact[k]
            self.folded[word.casefold()] = e

    def load(self, path: PathLike, key: Optional[str] = None) -> "Lexicon":
        p = Path(path)
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
        except OSError as e:
            raise ShowtimeError("cannot read lexicon %s: %s" % (p, e))
        except ValueError as e:
            raise ShowtimeError("invalid JSON in lexicon %s: %s" % (p, e))
        if key:
            data = data.get(key, {}) if isinstance(data, dict) else {}
        if isinstance(data, dict) and "words" in data and isinstance(data["words"], dict):
            data = data["words"]
        if not isinstance(data, dict):
            raise ShowtimeError("lexicon %s must be a JSON object {word: ipa | {ipa|say}}" % p)
        for w, e in data.items():
            if w.startswith("_"):
                continue
            self.add(w, e)
        self.sources.append(str(p))
        return self

    def update(self, other: "Lexicon") -> "Lexicon":
        self.exact.update(other.exact)
        self.folded.update(other.folded)
        self.sources += other.sources
        return self

    def __len__(self) -> int:
        return len(self.exact) + len(self.folded)

    # -- lookup -----------------------------------------------------------
    def entry(self, word: str) -> Tuple[Optional[Dict[str, Any]], bool]:
        """(entry, possessive) for a token core."""
        for w, poss in ((word, False),) + (((word[:-2], True),) if word[-2:] in ("'s", "’s") else ()):
            e = self.exact.get(w) or self.folded.get(w.casefold())
            if e:
                return e, poss
        return None, False

    @staticmethod
    def _pick(val: Any, lang: str) -> Optional[str]:
        if val is None or isinstance(val, str):
            return val
        if isinstance(val, dict):
            base = lang.split("-")[0]
            for k in (lang, base, "*", "default"):
                if k in val:
                    return val[k]
        return None

    def ipa(self, word: str, lang: str) -> Optional[str]:
        e, poss = self.entry(word)
        v = self._pick(e.get("ipa"), lang) if e else None
        if v and poss:
            v = v + ("s" if v[-1] in "ptkfθ" else "z")
        return v

    def say(self, word: str, lang: str) -> Optional[str]:
        e, poss = self.entry(word)
        v = self._pick(e.get("say"), lang) if e else None
        if v and poss:
            v = v + "'s"
        return v


def load(extra: Iterable[PathLike] = (), project_dir: Optional[PathLike] = None,
         builtin: bool = True) -> Lexicon:
    """Merge the built-in, environment, project and explicit lexicons."""
    lex = Lexicon()
    if builtin and BUILTIN.is_file():
        lex.load(BUILTIN)
    env = os.environ.get("SHOWTIME_LEXICON")
    if env:
        for part in env.split(os.pathsep):
            if part and Path(part).is_file():
                lex.load(part)
    if project_dir:
        d = Path(project_dir)
        for cand in (d / "lexicon.json", d.parent / "lexicon.json"):
            if cand.is_file():
                lex.load(cand)
                break
        for cand in (d / "brand.json", d.parent / "brand.json"):
            if cand.is_file():
                try:
                    lex.load(cand, key="pronunciations")
                except ShowtimeError:
                    pass
                break
    for p in extra:
        if p:
            lex.load(p)
    return lex

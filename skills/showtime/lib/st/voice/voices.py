"""Voice catalog for every engine, and voice-id resolution.

Voice ids:
  af_heart, em_alex, ...          Kokoro (prefix letter = language, second = gender)
  af_heart:60+am_michael:40       Kokoro blend (weights are normalized)
  supertonic:F1 / st:M2           Supertonic 3 presets (F1-F5, M1-M5; 31 languages)
  piper:es_MX-claude-high         Piper voice via sherpa-onnx (only commercially usable voices)
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

from ..common import ShowtimeError

# Kokoro prefix letter -> public language code
KOKORO_LANG = {"a": "en-us", "b": "en-gb", "e": "es", "f": "fr", "h": "hi", "i": "it", "j": "ja",
               "p": "pt-br", "z": "zh"}

# (id, upstream quality grade, notes). Grades are the model author's published
# ones (A best ... F); Spanish and Portuguese voices were never graded.
_KOKORO = [
    ("af_heart", "A", "warm, natural; the best all-rounder (default)"),
    ("af_bella", "A-", "bright, energetic; promos and social"),
    ("af_nicole", "B-", "soft, close-mic, whispery; calm explainers"),
    ("af_aoede", "C+", ""), ("af_kore", "C+", ""), ("af_sarah", "C+", "clear, neutral; docs"),
    ("af_nova", "C", "crisp; product demos"), ("af_alloy", "C", ""), ("af_sky", "C-", "airy; marketing"),
    ("af_jessica", "D", ""), ("af_river", "D", ""),
    ("am_michael", "C+", "steady, trustworthy; the best male default"),
    ("am_fenrir", "C+", "deep, confident; trailers and launches"),
    ("am_puck", "C+", "lively; upbeat promos"),
    ("am_echo", "D", ""), ("am_eric", "D", ""), ("am_liam", "D", ""), ("am_onyx", "D", "deep"),
    ("am_santa", "D-", "novelty"), ("am_adam", "F+", ""),
    ("bf_emma", "B-", "British, polished; docs and tutorials"), ("bf_isabella", "C", "British"),
    ("bf_alice", "D", "British"), ("bf_lily", "D", "British"),
    ("bm_george", "C", "British, authoritative; documentary"), ("bm_fable", "C", "British, storyteller"),
    ("bm_lewis", "D+", "British"), ("bm_daniel", "D", "British"),
    ("ef_dora", "-", "Spanish female; clear, the best Kokoro Spanish voice"),
    ("em_alex", "-", "Spanish male"), ("em_santa", "-", "Spanish male, novelty"),
    ("ff_siwis", "B-", "French female"),
    ("hf_alpha", "C", "Hindi"), ("hf_beta", "C", "Hindi"), ("hm_omega", "C", "Hindi"), ("hm_psi", "C", "Hindi"),
    ("if_sara", "C", "Italian"), ("im_nicola", "C", "Italian"),
    ("jf_alpha", "C+", "Japanese (espeak phonemes: approximate)"), ("jf_gongitsune", "C", "Japanese"),
    ("jf_nezumi", "C-", "Japanese"), ("jf_tebukuro", "C", "Japanese"), ("jm_kumo", "C-", "Japanese"),
    ("pf_dora", "-", "Brazilian Portuguese"), ("pm_alex", "-", "Brazilian Portuguese"),
    ("pm_santa", "-", "Brazilian Portuguese, novelty"),
    ("zf_xiaobei", "D", "Mandarin (espeak phonemes: approximate)"), ("zf_xiaoni", "D", "Mandarin"),
    ("zf_xiaoxiao", "D", "Mandarin"), ("zf_xiaoyi", "D", "Mandarin"), ("zm_yunjian", "D", "Mandarin"),
    ("zm_yunxi", "D", "Mandarin"), ("zm_yunxia", "D", "Mandarin"), ("zm_yunyang", "D", "Mandarin"),
]

SUPERTONIC_VOICES = ["F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5"]
SUPERTONIC_LANGS = ["en", "ko", "ja", "ar", "bg", "cs", "da", "de", "el", "es", "et", "fi", "fr", "hi", "hr",
                    "hu", "id", "it", "lt", "lv", "nl", "pl", "pt", "ro", "ru", "sk", "sl", "sv", "tr", "uk", "vi"]

# Piper voices whose training data allows commercial use. Everything else in
# the Piper catalog (lessac, ryan, hfc_*, amy, daniela, ...) is excluded on
# purpose: non-commercial, share-alike or unclear dataset licenses.
PIPER_VOICES: Dict[str, Dict[str, object]] = {
    "en_US-ljspeech-high": {"lang": "en-us", "gender": "f", "license": "public domain (LJ Speech)",
                            "size": 115817679, "sha256": "00c6408d2409050312193b0d40ae07fde28af7d3d45a56efcc55440db516b935"},
    "en_US-john-medium": {"lang": "en-us", "gender": "m", "license": "public domain (LibriVox)",
                          "size": 67249181, "sha256": "d90362cfa48e429d3096f644785184446145b6e38216f2eaf4c0601b8aad5a36"},
    "en_US-kristin-medium": {"lang": "en-us", "gender": "f", "license": "public domain (LibriVox)",
                             "size": 67259230, "sha256": "c2206f572df2956c50b1ae3367eebce3853c663e890cba8048cd62b1e4dbe6c7"},
    "en_US-norman-medium": {"lang": "en-us", "gender": "m", "license": "public domain (LibriVox)",
                            "size": 67203672, "sha256": "1f32065d480abe9abc7c7f91442125d0b34c1cc065d1e600466cac408eabf3b8"},
    "en_US-libritts_r-medium": {"lang": "en-us", "gender": "multi", "license": "CC-BY-4.0 (LibriTTS-R): credit required",
                                "attribution": "Piper en_US-libritts_r voice, trained on LibriTTS-R (CC BY 4.0)",
                                "size": 82038311, "sha256": "10dc268f3e371696d721486123e2705a9fc1faa113491979fde4d88dba1f1b1c"},
    "en_GB-cori-high": {"lang": "en-gb", "gender": "f", "license": "public domain (LibriVox)",
                        "size": 115574061, "sha256": "42922f07738fcde2e49eed4e959635692f73b933de35a6b7c1010162ff566292"},
    "en_GB-alba-medium": {"lang": "en-gb", "gender": "f", "license": "CC-BY-4.0: credit required",
                          "attribution": "Piper en_GB-alba voice, dataset by the University of Edinburgh (CC BY 4.0)",
                          "size": 67212349, "sha256": "fcd45962906933eec4431d3688f7d74aaac8713c87c6717f91fd3b23463aa1a1"},
    "es_MX-claude-high": {"lang": "es", "gender": "m", "license": "Apache-2.0",
                          "size": 67207890, "sha256": "ec33fb689c248fe64810aab564cba97babf0f506672cfd404928d46e751a4721"},
    "es_MX-ald-medium": {"lang": "es", "gender": "m", "license": "Unlicense",
                         "size": 67196497, "sha256": "c60cf7bc853eb01a875fba0756523fecf9d9f46c763b19785d223fc981fb4fb6"},
    "es_ES-davefx-medium": {"lang": "es", "gender": "m", "license": "CC0",
                            "size": 67184952, "sha256": "a3f6beb54a9cb893279f72978a22f807a4d9fc9c7848157b524d5cc7b7f58b22"},
    "es_ES-sharvard-medium": {"lang": "es", "gender": "multi", "license": "CC-BY-3.0: credit required",
                              "attribution": "Piper es_ES-sharvard voice, Sharvard corpus (CC BY 3.0)",
                              "size": 80318184, "sha256": "b30a7a83df0518f0ee1c7039506648cade99f1f9b498fc49ed2ced2e2536bb5a"},
}
PIPER_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-%s.tar.bz2"

# Recommended defaults per language (engine-qualified ids).
DEFAULTS = {"en": "af_heart", "en-us": "af_heart", "en-gb": "bf_emma", "es": "ef_dora", "fr": "ff_siwis",
            "it": "if_sara", "pt": "pf_dora", "pt-br": "pf_dora", "hi": "hf_alpha", "ja": "jf_alpha",
            "zh": "zf_xiaobei"}


@dataclass
class VoiceInfo:
    id: str
    engine: str
    lang: str
    gender: str
    grade: str = "-"
    notes: str = ""
    license: str = ""
    installed: bool = True
    attribution: str = ""
    langs: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        d = asdict(self)
        if not d["langs"]:
            d.pop("langs")
        if not d["attribution"]:
            d.pop("attribution")
        return d


@dataclass
class VoiceSpec:
    """A resolved voice request."""
    engine: str                       # kokoro | supertonic | piper
    name: str                         # canonical id without engine prefix
    lang: str                         # public language code
    blend: List[Tuple[str, float]] = field(default_factory=list)   # kokoro blends

    @property
    def id(self) -> str:
        if self.engine == "kokoro":
            return self.name
        return "%s:%s" % (self.engine, self.name)


def kokoro_catalog() -> List[VoiceInfo]:
    out = []
    for vid, grade, notes in _KOKORO:
        out.append(VoiceInfo(id=vid, engine="kokoro", lang=KOKORO_LANG[vid[0]],
                             gender={"f": "f", "m": "m"}[vid[1]], grade=grade, notes=notes,
                             license="Apache-2.0 (Kokoro-82M weights)"))
    return out


KOKORO_IDS = {v[0] for v in _KOKORO}
_BLEND = re.compile(r"^[a-z]{2}_[a-z]+(?::\d+(?:\.\d+)?)?(?:\+[a-z]{2}_[a-z]+(?::\d+(?:\.\d+)?)?)+$")


def parse_blend(voice: str) -> List[Tuple[str, float]]:
    parts = []
    for p in voice.split("+"):
        name, _, w = p.partition(":")
        parts.append((name.strip(), float(w) if w else 1.0))
    total = sum(w for _, w in parts) or 1.0
    return [(n, w / total) for n, w in parts]


def configured_voice(lang: str) -> Optional[str]:
    """The user's default voice ($SHOWTIME_VOICE, set from the plugin settings
    or the environment) when it speaks `lang`; None otherwise, so a request in
    another language still gets that language's default voice."""
    v = (os.environ.get("SHOWTIME_VOICE") or "").strip()
    if not v or not re.match(r"^[A-Za-z0-9_:+.\-]{1,120}$", v):
        return None
    low = v.lower()
    want = (lang or "en").lower().split("-")[0]
    if low.startswith(("supertonic:", "st:")):
        return v
    if low.startswith("piper:"):
        info = PIPER_VOICES.get(v.split(":", 1)[1])
        return v if info and str(info["lang"]).lower().split("-")[0] == want else None
    if ":" in low:
        e0 = low.split(":", 1)[0]
        if e0 not in ("kokoro", "piper", "supertonic", "st"):
            return v
    first = low[len("kokoro:"):] if low.startswith("kokoro:") else low
    have = KOKORO_LANG.get(first[:1], "")
    return v if have.split("-")[0] == want else None


def resolve(voice: Optional[str], lang: Optional[str] = None, engine: Optional[str] = None) -> VoiceSpec:
    """Turn a user voice id (or nothing) into a VoiceSpec. Never silently
    swaps an explicitly requested voice for another one."""
    eng = (engine or "").strip().lower() or None
    if eng in ("auto", ""):
        eng = None
    v = (voice or "").strip()
    if not v:
        lg = (lang or os.environ.get("SHOWTIME_LANG") or "en").strip().lower() or "en"
        if eng == "supertonic":
            v = "supertonic:F1"
        elif eng == "piper":
            v = "piper:" + ("es_MX-claude-high" if lg.startswith("es") else "en_US-ljspeech-high")
        else:
            v = configured_voice(lg) or DEFAULTS.get(lg) or DEFAULTS.get(lg.split("-")[0]) or "af_heart"
    low = v.lower()
    if low.startswith(("supertonic:", "st:")) or (eng == "supertonic"):
        name = v.split(":", 1)[1] if ":" in v else v
        name = name.upper()
        if name not in SUPERTONIC_VOICES:
            raise ShowtimeError("unknown Supertonic voice %r" % name,
                                hint="Supertonic voices: " + ", ".join(SUPERTONIC_VOICES))
        lg = (lang or "en").lower().split("-")[0]
        if lg not in SUPERTONIC_LANGS:
            raise ShowtimeError("Supertonic does not speak %r" % lang, hint="languages: " + " ".join(SUPERTONIC_LANGS))
        return VoiceSpec("supertonic", name, lg)
    if low.startswith("piper:") or eng == "piper" or v in PIPER_VOICES:
        name = v.split(":", 1)[1] if low.startswith("piper:") else v
        if name not in PIPER_VOICES:
            raise ShowtimeError("unknown or excluded Piper voice %r" % name,
                                hint="commercially usable Piper voices: " + ", ".join(sorted(PIPER_VOICES)))
        return VoiceSpec("piper", name, str(PIPER_VOICES[name]["lang"]))
    if eng and eng not in ("kokoro", "piper", "supertonic"):
        name = v.split(":", 1)[-1] if ":" in v else v
        from .engines import get as get_engine
        get_engine(eng)
        lg = (lang or "en").lower().split("-")[0] or "en"
        return VoiceSpec(eng, name or eng, lg)
    if ":" in low:
        e0, _, _rest = low.partition(":")
        if e0 not in ("kokoro", "piper", "supertonic", "st"):
            from .engines import get as get_engine
            get_engine(e0)
            lg = (lang or "en").lower().split("-")[0] or "en"
            return VoiceSpec(e0, v.split(":", 1)[1], lg)
    if low.startswith("kokoro:"):
        v = v.split(":", 1)[1]
    if eng not in (None, "kokoro"):
        raise ShowtimeError("voice %r is a Kokoro voice but --engine %s was requested" % (v, eng))
    if "+" in v:
        if not _BLEND.match(v):
            raise ShowtimeError("bad voice blend %r" % v, hint="use e.g. af_heart:60+am_michael:40")
        blend = parse_blend(v)
        for n, _ in blend:
            if n not in KOKORO_IDS:
                raise ShowtimeError("unknown Kokoro voice %r in blend" % n, hint="run `showtime voice list`")
        first = blend[0][0]
        return VoiceSpec("kokoro", v, lang or KOKORO_LANG[first[0]], blend)
    if v not in KOKORO_IDS:
        close = [k for k in sorted(KOKORO_IDS) if k.split("_")[1] == v.lower() or k.startswith(v.lower()[:2])][:6]
        raise ShowtimeError("unknown voice %r" % v,
                            hint="run `showtime voice list`" + (" (did you mean %s?)" % ", ".join(close) if close else ""))
    return VoiceSpec("kokoro", v, lang or KOKORO_LANG[v[0]])

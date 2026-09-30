"""A different default score for every film project: `showtime new film` writes score.js from a signature.

The film template's score.js is a worked example (D major, 80 bpm, one motif). Kept as it was, every
film made from the template sounds the same. score_for() instead picks a signature from small curated
tables, per mood (calm, upbeat, tension, playful, cinematic):

  key + mode     the tonic (C3..Bb3) and major or minor
  tempo + meter  a pair that keeps the cues on bar lines: 80 bpm 4/4 and 60 bpm 3/4 (a 3 s bar), 100 bpm
                 5/4 (3 s), 120 bpm 3/4 and 160 bpm 4/4 (1.5 s); `showtime retime` then scales the tempo
  progression    five chords for title | metaphor | data (two) | end card, tonic first and last
  motif          a question (title) and its answer (end card), as scale degrees
  palette        the melody and arpeggio instruments, pad brightness, reverb
  drums          the groove the data section lifts with

The seed is the project (and its job's brief), plus the look history's length. The history records
the signature (score.js carries it on its first line as `showtime-score: {...}`), and a new score
avoids the key and tempo of the last job and every full signature of the last HISTORY_JOBS jobs.
The mood comes from the brief's words (the job's goal, the title, the folder name); none found: a
seeded choice. `showtime audio film-score <project>` writes a new one (--mood, --seed).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..common import ShowtimeError

MARK = "showtime-score:"
HISTORY_JOBS = 6
KEYS = ("C", "D", "Eb", "E", "F", "G", "A", "Bb")      # the tonic in octave 3; the bass sits an octave down

PROGRESSIONS = {   # title | metaphor | data A | data B | end
    "major": {
        "anthem": ["Imaj7", "vi7", "IVmaj7", "V", "I"],
        "hopeful": ["Iadd9", "iii7", "vi7", "IVmaj7", "I"],
        "open": ["Isus2", "IVmaj7", "vi7", "V", "I"],
        "bright": ["I", "iii7", "IV", "V7", "I"],
        "warm": ["Imaj7", "ii7", "IVmaj7", "Vsus4", "I"],
        "lydian": ["I", "II", "IVmaj7", "V", "Iadd9"],
    },
    "minor": {
        "epic": ["i", "VI", "III", "VII", "i"],
        "dark": ["i", "iv7", "VI", "V", "i"],
        "dawn": ["i", "VI", "III", "VII", "I"],
        "drift": ["i7", "VImaj7", "iv7", "VII", "i"],
        "pulse": ["isus2", "VII", "VI", "VII", "i"],
    },
}
MOTIFS = {   # (scale degree, beats): a question that ends off the tonic, an answer that lands on it
    "arch": ([(2, 1), (4, 1), (1, 1.5), (0, 0.5)], [(2, 1), (1, 1), (0, 2)]),
    "rise": ([(0, 0.5), (2, 0.5), (4, 1), (5, 1.5)], [(4, 1), (2, 1), (0, 2)]),
    "call": ([(4, 1), (3, 0.5), (2, 0.5), (1, 2)], [(1, 1), (2, 1), (0, 2)]),
    "step": ([(0, 1), (1, 1), (2, 1), (4, 1)], [(4, 0.5), (2, 0.5), (1, 1), (0, 2)]),
    "leap": ([(0, 1), (4, 1), (7, 1.5), (6, 0.5)], [(4, 1), (1, 1), (0, 2)]),
    "sigh": ([(5, 1.5), (4, 0.5), (2, 1), (1, 1)], [(2, 1), (1, 1), (0, 2)]),
    "echo": ([(2, 0.5), (2, 0.5), (4, 1), (3, 2)], [(3, 0.5), (2, 0.5), (1, 1), (0, 2)]),
}
PALETTES = {   # melody, arpeggio, melody level, pad cutoff (Hz), reverb seconds, reverb wet
    "glass": ("bell", "pluck", 0.34, 1300, 2.6, 0.8),
    "wood": ("marimba", "marimba", 0.4, 1000, 1.6, 0.5),
    "felt": ("pluck", "bell", 0.36, 900, 3.2, 0.85),
    "synth": ("lead", "pluck", 0.2, 1800, 2.0, 0.6),
    "chime": ("bell", "marimba", 0.32, 1500, 3.0, 0.85),
}
DRUMS = ("soft", "pulse", "halftime", "shuffle")
METERS = {80: 4, 60: 3, 100: 5, 120: 3, 160: 4}          # bpm -> beats per bar (every pair keeps the cues on bars)
MOODS = {
    "calm": dict(modes=("major", "major", "minor"), tempos=(60, 80), drums=("soft",),
                 palettes=("glass", "felt", "chime"), motifs=("arch", "sigh", "step", "echo")),
    "upbeat": dict(modes=("major",), tempos=(160, 120, 80), drums=("pulse", "halftime", "shuffle"),
                   palettes=("synth", "wood", "glass"), motifs=("rise", "step", "echo", "arch")),
    "tension": dict(modes=("minor",), tempos=(100, 80, 160), drums=("halftime", "pulse"),
                    palettes=("synth", "felt", "glass"), motifs=("call", "leap", "sigh")),
    "playful": dict(modes=("major",), tempos=(120, 160), drums=("shuffle", "pulse"),
                    palettes=("wood", "chime", "synth"), motifs=("rise", "echo", "step")),
    "cinematic": dict(modes=("major", "minor"), tempos=(80, 60, 100), drums=("halftime", "soft"),
                      palettes=("glass", "felt", "synth", "chime"), motifs=("arch", "leap", "rise", "call")),
}
MOOD_WORDS = {
    "calm": ("calm", "meditat", "relax", "yoga", "sleep", "mindful", "breath", "spa", "gentle", "quiet", "peace",
             "wellness", "soft", "serene", "ambient", "slow"),
    "upbeat": ("launch", "hackathon", "recap", "release", "startup", "product", "energ", "celebrat", "sale", "promo",
               "fitness", "sport", "quarterly", "update", "announce", "teaser", "tech", "app"),
    "tension": ("sci-fi", "scifi", "thriller", "horror", "myster", "suspense", "dark", "heist", "danger", "space",
                "alien", "cyber", "hack ", "crime", "trailer"),
    "playful": ("birthday", "party", "kid", "cooking", "recipe", "food", "game", "cute", "pet", "fun", "silly",
                "cartoon", "toy", "holiday"),
    "cinematic": ("epic", "story", "journey", "documentary", "mission", "history", "adventure", "legacy", "film",
                  "wedding", "memorial", "nature", "travel"),
}


def mood_of(text: str) -> Optional[str]:
    """The mood a brief's words name (the most hits; ties go to the earlier mood), or None."""
    low = " %s " % (text or "").lower()
    hits = {m: sum(1 for w in ws if w in low) for m, ws in MOOD_WORDS.items()}
    best = max(hits.values()) if hits else 0
    return next((m for m in MOODS if hits[m] == best), None) if best else None


def _h(*parts: Any) -> int:
    return int(hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12], 16)


def _order(items: Sequence[Any], seed: int, salt: str) -> List[Any]:
    return sorted(items, key=lambda x: _h(seed, salt, x))


def signature_id(sig: Dict[str, Any]) -> str:
    return "%s%s/%g/%s/%s/%s/%s" % (sig["key"], "m" if sig["mode"] == "minor" else "", sig["bpm"],
                                     sig["progression"], sig["motif"], sig["palette"], sig["drums"])


def recent_signatures(key: Optional[str] = None, n: int = HISTORY_JOBS) -> List[Dict[str, Any]]:
    """Score signatures of the last n recorded jobs (newest first), leaving out `key` (the project)."""
    from ..variety import history
    if not history.enabled()[0]:
        return []
    out: List[Dict[str, Any]] = []
    for lk in reversed(history.load()):
        if key and (str(lk.get("project") or "") == key or lk.get("job") == key):
            continue
        for m in lk.get("music") or []:
            if m.get("ref") == "score:synth" and isinstance(m.get("signature"), dict):
                out.append(m["signature"])
                break
        else:
            continue
        if len(out) >= n:
            break
    return out


def choose(mood: Optional[str], seed: int, recent: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """A signature for `mood` (None: a seeded mood), avoiding the key+tempo of the newest recent one,
    every full signature in `recent`, and (when it can) their progressions and motifs."""
    mood = mood if mood in MOODS else _order(sorted(MOODS), seed, "mood")[0]
    t = MOODS[mood]
    last = recent[0] if recent else {}
    used_sig = {signature_id(s) for s in recent if s.get("key")}
    used_prog = {s.get("progression") for s in recent[:3]}
    used_motif = {s.get("motif") for s in recent[:3]}
    fallback = None
    mode = t["modes"][_h(seed, "mode") % len(t["modes"])]      # a mode listed twice is twice as likely
    for key in _order(KEYS, seed, "key"):
        for bpm in _order(t["tempos"], seed, "bpm"):
            if last and key == last.get("key") and bpm == last.get("bpm"):
                continue
            for prog in _order(sorted(PROGRESSIONS[mode]), seed, "prog"):
                for motif in _order(t["motifs"], seed, "motif"):
                    sig = {"mood": mood, "key": key, "mode": mode, "bpm": bpm, "meter": METERS[bpm],
                           "progression": prog, "motif": motif,
                           "palette": _order(t["palettes"], seed, "pal")[0],
                           "drums": _order(t["drums"], seed, "drums")[0]}
                    if signature_id(sig) in used_sig:
                        continue
                    if fallback is None:
                        fallback = sig
                    if prog in used_prog or motif in used_motif:
                        continue
                    # a palette and drums the last job did not use, when the mood has others
                    for k, salt, table in (("palette", "pal", "palettes"), ("drums", "drums", "drums")):
                        sig[k] = ([x for x in _order(t[table], seed, salt) if x != last.get(k)] or [sig[k]])[0]
                    return sig
    if fallback is None:
        raise ShowtimeError("no film score signature left for mood %s" % mood)
    return fallback


def _degrees(line: Sequence[Any]) -> str:
    return "[%s]" % ", ".join("[key.degree(%d, 2), %g]" % (d, b) for d, b in line)


def _drums(feel: str, beats: int) -> Dict[str, str]:
    """16th-note patterns (4 steps a beat) for one bar of `beats` beats."""
    n = 4 * beats

    def on(steps: Sequence[int]) -> str:
        return "".join("x" if i in steps else "." for i in range(n))

    mid = beats // 2 if beats != 3 else 2
    if feel == "pulse":
        return {"kick": on([4 * b for b in range(beats)]), "hat": on([4 * b + 2 for b in range(beats)])}
    if feel == "halftime":
        return {"kick": on([0]), "snare": on([4 * mid]), "hat": on([2 * i for i in range(2 * beats)])}
    if feel == "shuffle":
        return {"kick": on([0, 4 * mid]), "hat": on([4 * b + k for b in range(beats) for k in (0, 3)])}
    return {"kick": on([0, 4 * mid] if beats >= 4 else [0]), "hat": on([4 * b + 2 for b in range(beats)])}


def render_js(sig: Dict[str, Any]) -> str:
    """score.js for the film template's cue table (CUE.title, metaphor, untangle, data, end, button, duration)."""
    mel, arp, mvel, cutoff, rev_s, rev_wet = PALETTES[sig["palette"]]
    chords = PROGRESSIONS[sig["mode"]][sig["progression"]]
    q, a = MOTIFS[sig["motif"]]
    beats = int(sig["meter"])
    drums = _drums(sig["drums"], beats)
    header = json.dumps(sig, sort_keys=True)
    return """/* %s %s
 * Score for this film: %s %s, %g bpm in %d/4, progression %s (%s), motif %s, palette %s, drums %s.
 * Written by `showtime new film` from the look history so films made from the template do not share a
 * score (st/audio/filmscore.py); `showtime audio film-score <project> [--mood M]` writes another.
 * Arc: calm (title) -> tension (metaphor, pulse) -> lift (data, drums) -> resolution (end card, the
 * motif answers on the tonic). Every hit uses the CUE times of the picture and lengths come from the
 * gaps between cues, so `showtime retime` moves picture and music together. Edit freely. */
'use strict';

var FILM_SCORE = Synth.score(function (m) {
  var g = m.grid({ bpm: CUE.bpm, beatsPerBar: %d });
  var bar = g.barDur;
  function span(a, b) { return b - a; }                   // section length in seconds
  function barOf(t) { return Math.round(g.beatAt(t) / g.beatsPerBar); }
  function bars(a, b) { return Math.max(1, Math.round((b - a) / bar)); }
  var key = Synth.scale('%s3', '%s');
  var ch = Synth.progression('%s3', '%s', %s);
  var root = key.degree(-7), mel = { inst: '%s', vel: %g };

  // ---- 1. title: soft pad from frame 1 + the motif (a question: it ends off the tonic)
  m.pad(ch[0], CUE.title, span(CUE.title, CUE.metaphor), { vel: 0.42, attack: 0.25, cutoff: %d });
  m.melody(g, 0.5, %s, mel);
  m.bass(root, CUE.title, span(CUE.title, CUE.metaphor), { vel: 0.35, cutoff: 300 });

  // ---- 2. metaphor: the second chord, an 8th-note pulse, an arpeggio as the idea untangles
  m.pad(ch[1], CUE.metaphor, span(CUE.metaphor, CUE.data), { vel: 0.4, cutoff: %d });
  m.bassline([ch[1]], g, barOf(CUE.metaphor), { pattern: 'pulse8', vel: 0.45, cutoff: 380, barsPerChord: bars(CUE.metaphor, CUE.data) });
  m.arp(ch[1], CUE.untangle, CUE.data, { grid: g, div: 4, inst: '%s', octaves: 2, vel: 0.22, decay: 0.5, pan: 0.2 });
  m.riser(CUE.data, { dur: 1.6, vel: 0.5, note: key.degree(-3) });
  m.sweep('music', CUE.data - 1.2, CUE.data - 0.02, 20000, 1400); // muffle into the cut...

  // ---- 3. data: the lift. The groove enters on the cut, two chords share the section
  m.sweep('music', CUE.data, CUE.data + 0.05, 1400, 20000);       // ...and open on it
  m.impact(CUE.data, { vel: 0.45, note: root });
  var half = span(CUE.data, CUE.end) / 2;
  m.pad(ch[2], CUE.data, half, { vel: 0.42 });
  m.pad(ch[3], CUE.data + half, half, { vel: 0.42 });
  m.bassline([ch[2], ch[3]], g, barOf(CUE.data), { pattern: 'octave8', vel: 0.5, cutoff: 480, barsPerChord: bars(CUE.data, CUE.end) / 2 });
  m.drums(g, barOf(CUE.data), bars(CUE.data, CUE.end), %s, { vel: 0.6 });
  m.arp(ch[2].concat(ch[3]), CUE.data, CUE.end, { grid: g, div: 4, inst: '%s', vel: 0.24, decay: 0.4, pattern: 'updown' });
  m.tick(CUE.data + 0.4); m.tick(CUE.data + 0.55);
  m.duck('music', CUE.data, { depth: 5, release: 0.6 });

  // ---- 4. end card: resolution. Chime on the cut, the motif answers on the tonic
  m.chime([key.degree(7), key.degree(9), key.degree(11), key.degree(14)], CUE.end, { vel: 0.35 });
  m.pad(ch[4], CUE.end, span(CUE.end, CUE.duration) + 1, { vel: 0.45, attack: 0.1, release: 2.2 });
  m.melody(g, g.beatAt(CUE.end) + 0.5, %s, mel);
  m.bass(root, CUE.end, span(CUE.end, CUE.duration), { vel: 0.4, cutoff: 300 });
  m.subDrop(CUE.end, { note: key.degree(-14), dur: 1.4, vel: 0.5 });
  m.bell(key.degree(21), CUE.button, { vel: 0.4, decay: 3 });      // the button: final hit on the logo
  m.kick(CUE.button, { vel: 0.5, decay: 0.6 });
  m.end(CUE.duration, { fade: 1.2 });
}, { bpm: CUE.bpm, seed: %d, reverb: { seconds: %g, wet: %g } });
""" % (MARK, header, sig["key"], sig["mode"], sig["bpm"], beats, " ".join(chords), sig["progression"], sig["motif"],
       sig["palette"], sig["drums"], beats, sig["key"], sig["mode"], sig["key"], sig["mode"], json.dumps(chords),
       mel, mvel, cutoff, _degrees(q), max(700, cutoff - 200), arp, json.dumps(drums), arp, _degrees(a),
       int(sig.get("seed", 3)), rev_s, rev_wet)


def read_signature(project: Path) -> Optional[Dict[str, Any]]:
    """The signature a generated score.js carries on its first line, or None (a hand-written score)."""
    p = Path(project) / "score.js"
    try:
        head = p.read_text(encoding="utf-8")[:600]
    except OSError:
        return None
    m = re.search(re.escape(MARK) + r"\s*(\{.*?\})\s*$", head.splitlines()[0] if head else "")
    if not m:
        return None
    try:
        sig = json.loads(m.group(1))
    except ValueError:
        return None
    return sig if isinstance(sig, dict) else None


def _set_bpm(cues: Path, bpm: float) -> None:
    text = cues.read_text(encoding="utf-8")
    new = re.sub(r"(\bbpm\s*:\s*)[0-9.]+", lambda m: m.group(1) + ("%g" % bpm), text, count=1)
    new = re.sub(r"^( \* )80 bpm: one beat = 0\.75 s, one 4-beat bar = 3 s, so every section starts on a downbeat\.",
                 lambda m: m.group(1) + "bpm and score.js's meter put every section start on a downbeat.",
                 new, count=1, flags=re.M)
    cues.write_text(new, encoding="utf-8")


def cue_scale(project: Path) -> float:
    """How far the cue table was stretched from the template's 3 s bars (1 for a fresh project)."""
    try:
        text = (Path(project) / "cues.js").read_text(encoding="utf-8")
        m = re.search(r"\bmetaphor\s*:\s*([0-9.]+)", text)
        return float(m.group(1)) / 3.0 if m and float(m.group(1)) > 0 else 1.0
    except (OSError, ValueError):
        return 1.0


def apply(project: Path, brief: str = "", mood: Optional[str] = None, seed: Optional[int] = None,
          force: bool = False) -> Optional[Dict[str, Any]]:
    """Write a fresh score.js (and the tempo in cues.js) for a film project. Returns the signature, or
    None when the project's score.js is hand-written (not the template's, not generated) and not `force`."""
    from ..variety import history
    project = Path(project).resolve()
    sj, cj = project / "score.js", project / "cues.js"
    if not (sj.is_file() and cj.is_file()):
        return None
    text = sj.read_text(encoding="utf-8")
    if not force and MARK not in text and "Score for the film template" not in text:
        return None
    key = str(project)
    mine = read_signature(project)
    recent = ([mine] if mine else []) + recent_signatures(key)     # a new score differs from the one it replaces
    n_hist = len(history.load()) if history.enabled()[0] else 0
    s = _h(key, brief, n_hist) if seed is None else int(seed)
    sig = choose(mood or mood_of(" ".join([brief, project.name.replace("-", " ")])), s, recent)
    sig["seed"] = s % 997 + 1
    # a retimed project's cues are k times the template's: a whole multiple of bpm / k keeps them on bars
    k = cue_scale(project)
    bpm = min((float(sig["bpm"]) * n / k for n in (1, 2, 3, 4)), key=lambda b: abs(math.log(b / float(sig["bpm"]))))
    sj.write_text(render_js(sig), encoding="utf-8")
    _set_bpm(cj, round(bpm, 3))
    return sig

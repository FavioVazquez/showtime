"""Procedural music composer: style + bpm + key + duration + section markers
-> multi-stem music with an exact-length ending, MIDI and beats.json.

Pipeline
  1. plan_timeline(): one global tempo within +-6 % of the request, nudged per
     section (usually < 2 %) so every section marker lands exactly on a
     downbeat; the final tonic hit is snapped to the grid inside the style's
     ring-out window, and the file is exactly duration * 48000 samples.
  2. Composer: per bar and role (drums, bass, pad, arp, lead, keys) from the
     style's patterns; section moves (crash on section downbeats, fills,
     accelerating rolls into drops, optional pre-drop gap), cadence into the
     final hit, a two-cell motif developed across phrases.
  3. Render each stem: SoundFont (tinysoundfont, sample-accurate event
     scheduling), numpy synth voices, or a hybrid (synth drums/bass, SoundFont
     for acoustic parts). Falls back to the numpy synth when tinysoundfont or
     a SoundFont is missing.
  4. Post chain per stem (scipy EQ/compression/chorus/delay/convolution reverb),
     stem balance by role targets, kick sidechain for electronic styles,
     transition SFX (riser into drops, reverse cymbals, impacts, downlifters).
     Restrained styles (underscore, minimal-pulse, ambient-pad, piano-emotional,
     corporate-minimal) skip the stock gestures: no crash on every section, no
     tom fills, no snare rolls into builds, no transition SFX.
  5. Master (st.audio.master, music preset) to the target loudness.

Outputs for `-o bed.wav`: bed.wav, bed.mid, bed.beats.json, bed.stems/*.wav.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..common import ShowtimeError, debug, home, warn, write_json
from . import SR, dsp, master, sfx, wav
from .dsp import midi_to_hz, parse_key

# Bumped when a change alters how existing styles sound; `audio lib generate` re-renders library beds
# composed by an older revision. 2: restrained styles, sustained chords held for the whole chord.
COMPOSER_REV = 2

# ---------------------------------------------------------------------------------------------
# Styles. roles: role -> (GM program (0-based) or None, pattern, numpy synth voice)
# prog: diatonic degrees (0 = tonic); bpc: bars per chord; sev: seventh chords
# backend: preferred renderer (sf = SoundFont, synth = numpy, hybrid = synth drums/bass + SoundFont)
# restrained: no section crashes, drum fills, build rolls or transition SFX (the gestures that make a
#   bed sound like stock music); stem_db: per-role balance overrides (dBFS RMS, see STEM_TARGET_DB)
# ---------------------------------------------------------------------------------------------
STYLES: Dict[str, dict] = {
    "underscore": dict(
        bpm=76, key="Dm", prog=[0, 5, 2, 6], bpc=2, sev=True, swing=0.0, tail=3.5, drums="none", cadence=5,
        sidechain=False, drop_gap=False, restrained=True, backend="sf",
        stem_db=dict(pad=-21.0, bass=-22.0, arp=-27.0, keys=-29.0),
        moods=["serious", "thoughtful", "calm", "cinematic", "premium"],
        desc="Documentary underscore: sustained strings, low contrabass, a soft felt-piano pulse, no drums, no melody.",
        use="explainers, data stories, reports, math, documentaries; the default bed under a voice-over",
        roles={"pad": (49, "sustain", "strings_pad"), "bass": (43, "sustain", "strings_pad"),
               "arp": (0, "pulse_soft", "piano"), "lead": (None, None, None), "keys": (89, "sustain_hi", "warm_pad")}),
    "minimal-pulse": dict(
        bpm=92, key="Am", prog=[0, 5, 2, 6], bpc=2, sev=True, swing=0.0, tail=2.5, drums="soft", cadence=5,
        sidechain=False, drop_gap=False, restrained=True, backend="synth",
        stem_db=dict(drums=-24.0, bass=-19.0, pad=-22.0, arp=-25.0),
        moods=["modern", "focused", "calm", "technical", "premium"],
        desc="Modern minimal pulse: warm analog pad, sub bass, a muted pluck ostinato, a soft kick; no snare, no melody.",
        use="tech and data explainers, product walkthroughs, reports that need gentle forward motion",
        roles={"pad": (89, "sustain", "warm_pad"), "bass": (38, "sustain", "sub_bass"),
               "arp": (45, "pulse_mute", "pluck"), "lead": (None, None, None), "keys": (None, None, None)}),
    "upbeat-tech": dict(
        bpm=124, key="C", prog=[0, 4, 5, 3], bpc=1, sev=False, swing=0.0, tail=1.8, drums="house", cadence=4,
        sidechain=True, drop_gap=True, backend="synth", moods=["bright", "uplifting", "driving", "modern"],
        desc="Four-on-the-floor tech launch groove: supersaw pad, offbeat bass, 16th arps, square lead.",
        use="product launches, feature reels, SaaS promos",
        roles={"pad": (89, "sustain", "supersaw_pad"), "bass": (38, "offbeat8", "saw_bass"),
               "arp": (81, "arp16", "pluck"), "lead": (80, "motif", "square_lead"), "keys": (4, "stabs", "fm_keys")}),
    "corporate-minimal": dict(
        bpm=104, key="G", prog=[0, 3, 5, 4], bpc=1, sev=False, swing=0.0, tail=1.8, drums="corporate", cadence=4,
        sidechain=False, drop_gap=False, restrained=True, backend="sf", stem_db=dict(drums=-19.0, arp=-25.0),
        moods=["bright", "positive", "clean", "upbeat"],
        desc="Bright corporate bed: piano 8ths, soft strings, a sparse piano motif, shaker pulse.",
        use="upbeat company intros, feature tours with a positive tone (for explainers and data prefer underscore)",
        roles={"pad": (48, "sustain", "strings_pad"), "bass": (33, "root4", "round_bass"),
               "arp": (0, "piano8", "piano"), "lead": (0, "motif_sparse", "piano"), "keys": (None, None, None)}),
    "cinematic-build": dict(
        bpm=90, key="Dm", prog=[0, 5, 3, 6], bpc=2, sev=False, swing=0.0, tail=3.0, drums="cinematic", cadence=6,
        sidechain=False, drop_gap=True, impact=True, backend="sf", moods=["epic", "dark", "building", "serious"],
        desc="Orchestral build: string ostinato, horn melody, timpani, toms, riser and impact into the drop.",
        use="reveals, keynote openers, 'the big moment'",
        roles={"pad": (49, "sustain", "strings_pad"), "bass": (43, "sustain", "strings_pad"),
               "arp": (48, "ostinato8", "strings_stac"), "lead": (60, "motif_slow", "brass"),
               "keys": (47, "timpani", "timpani")}),
    "epic-trailer": dict(
        bpm=84, key="Cm", prog=[0, 5, 6, 0], bpc=1, sev=False, swing=0.0, tail=3.0, drums="trailer", cadence=6,
        sidechain=False, drop_gap=True, impact=True, backend="sf", moods=["epic", "intense", "heroic", "dark"],
        desc="Trailer: taiko toms, 16th string ostinato, brass and choir, braams and impacts.",
        use="trailers, big announcements, dramatic hooks",
        roles={"pad": (52, "sustain", "choir"), "bass": (61, "sustain", "brass"),
               "arp": (48, "ostinato16", "strings_stac"), "lead": (61, "motif_slow", "brass"),
               "keys": (47, "timpani", "timpani")}),
    "lofi-chill": dict(
        bpm=78, key="F", prog=[1, 4, 0, 5], bpc=1, sev=True, swing=0.62, tail=2.5, drums="boombap", cadence=4,
        sidechain=False, drop_gap=False, crackle=True, backend="hybrid", moods=["relaxed", "calm", "warm", "cozy"],
        desc="Lo-fi hip-hop: swung boom-bap, Rhodes comping, soft bass, vibraphone, vinyl crackle.",
        use="study/coding vibes, relaxed tutorials, dev logs",
        roles={"pad": (4, "comp", "rhodes"), "bass": (33, "lofi", "round_bass"), "lead": (11, "motif_sparse", "bell"),
               "arp": (None, None, None), "keys": (None, None, None)}),
    "synthwave": dict(
        bpm=100, key="Am", prog=[0, 5, 2, 6], bpc=1, sev=False, swing=0.0, tail=2.2, drums="synthwave", cadence=6,
        sidechain=True, drop_gap=True, backend="synth", moods=["retro", "nostalgic", "driving", "neon"],
        desc="80s synthwave: octave bass, polysynth pad, square arps, saw lead, gated-reverb drums.",
        use="retro tech, gaming, night-drive aesthetics",
        roles={"pad": (90, "sustain", "supersaw_pad"), "bass": (38, "octave8", "saw_bass"),
               "arp": (80, "arp16", "square_arp"), "lead": (81, "motif", "saw_lead"), "keys": (None, None, None)}),
    "ambient-pad": dict(
        bpm=70, key="E", prog=[0, 3, 5, 3], bpc=2, sev=True, swing=0.0, tail=4.0, drums="none", cadence=3,
        sidechain=False, drop_gap=False, restrained=True, backend="hybrid", moods=["calm", "dreamy", "spacious", "soft"],
        desc="Drumless ambient: slow pads, sparse piano motif, halo shimmer.",
        use="meditative intros, product beauty shots, soft backgrounds",
        roles={"pad": (88, "sustain", "warm_pad"), "bass": (89, "sustain", "warm_pad"), "arp": (None, None, None),
               "lead": (0, "motif_sparse", "piano"), "keys": (94, "sustain_hi", "warm_pad")}),
    "playful-pizzicato": dict(
        bpm=116, key="D", prog=[0, 5, 3, 4], bpc=1, sev=False, swing=0.0, tail=1.2, drums="playful", cadence=4,
        sidechain=False, drop_gap=False, backend="sf", moods=["playful", "humorous", "bouncy", "light"],
        desc="Quirky pizzicato: bouncing bassoon, pizz strings, glockenspiel, woodblock and claps.",
        use="comedy, kids' content, deliberately silly products (only when the user asks for playful)",
        roles={"pad": (None, None, None), "bass": (70, "bounce", "round_bass"), "arp": (45, "pizz8", "pizz"),
               "lead": (9, "motif", "bell"), "keys": (71, "counter", "fm_keys")}),
    "deep-house": dict(
        bpm=122, key="Am", prog=[0, 3], bpc=2, sev=True, swing=0.0, tail=2.0, drums="house", cadence=4,
        sidechain=True, drop_gap=True, backend="synth", moods=["groovy", "cool", "night", "smooth"],
        desc="Deep house: minor 7th organ stabs, rolling sub bass, open hats, warm pad.",
        use="fashion/lifestyle, smooth product showcases, event recaps",
        roles={"pad": (89, "sustain", "warm_pad"), "bass": (38, "deep", "sub_bass"), "arp": (None, None, None),
               "lead": (None, None, None), "keys": (16, "house_stab", "organ")}),
    "hip-hop-beat": dict(
        bpm=90, key="Cm", prog=[0, 5, 3, 4], bpc=1, sev=True, swing=0.58, tail=2.0, drums="hiphop", cadence=4,
        sidechain=False, drop_gap=True, backend="hybrid", moods=["confident", "urban", "groovy", "bold"],
        desc="Hip-hop: heavy kick and snare, 808-style bass, Rhodes chords, bell melody.",
        use="bold social clips, creator content, street-style promos",
        roles={"pad": (4, "comp", "rhodes"), "bass": (38, "808", "sub_bass"), "arp": (None, None, None),
               "lead": (11, "motif_sparse", "bell"), "keys": (None, None, None)}),
    "acoustic-folk": dict(
        bpm=100, key="G", prog=[0, 4, 5, 3], bpc=1, sev=False, swing=0.0, tail=2.0, drums="folk", cadence=4,
        sidechain=False, drop_gap=False, backend="sf", moods=["warm", "honest", "uplifting", "organic"],
        desc="Acoustic folk: strummed steel guitar, upright bass, whistle-like flute, tambourine and claps.",
        use="human stories, small business, travel, 'made with care'",
        roles={"pad": (None, None, None), "bass": (32, "root_fifth", "round_bass"), "arp": (25, "strum", "guitar"),
               "lead": (73, "motif", "flute"), "keys": (46, "counter", "pizz")}),
    "piano-emotional": dict(
        bpm=72, key="C", prog=[5, 3, 0, 4], bpc=1, sev=False, swing=0.0, tail=3.5, drums="none", cadence=4,
        sidechain=False, drop_gap=False, restrained=True, backend="sf", moods=["emotional", "hopeful", "tender", "reflective"],
        desc="Emotional piano: flowing broken chords, cello bass, soft strings, simple melody.",
        use="testimonials, mission statements, thank-you videos",
        roles={"pad": (48, "sustain", "strings_pad"), "bass": (42, "sustain", "strings_pad"),
               "arp": (0, "piano_arp", "piano"), "lead": (0, "motif_slow", "piano"), "keys": (None, None, None)}),
    "dark-tension": dict(
        bpm=80, key="Dm", prog=[0, 0, 5, 1], bpc=2, sev=False, swing=0.0, tail=3.0, drums="tension", cadence=4,
        sidechain=False, drop_gap=True, impact=True, backend="hybrid", moods=["dark", "suspense", "mysterious", "tense"],
        desc="Suspense: pulsing low strings, drone, heartbeat kick, sparse dissonant piano.",
        use="problem statements, security/threat topics, mystery teasers",
        roles={"pad": (95, "sustain", "drone_pad"), "bass": (48, "pulse8", "strings_stac"),
               "arp": (None, None, None), "lead": (0, "motif_sparse", "piano"), "keys": (47, "timpani", "timpani")}),
    "retro-8bit": dict(
        bpm=140, key="C", prog=[0, 5, 3, 4], bpc=1, sev=False, swing=0.0, tail=1.2, drums="chip", cadence=4,
        sidechain=False, drop_gap=False, backend="synth", moods=["playful", "retro", "game", "energetic"],
        desc="Chiptune: pulse-wave lead, fast arpeggios, triangle bass, noise drums.",
        use="games, dev humour, retro product nods",
        roles={"pad": (None, None, None), "bass": (38, "octave8", "chip_triangle"), "arp": (80, "chip_arp", "chip_pulse"),
               "lead": (80, "motif", "chip_square"), "keys": (None, None, None)}),
    "news-bumper": dict(
        bpm=120, key="D", prog=[0, 3, 4, 0], bpc=1, sev=False, swing=0.0, tail=2.0, drums="news", cadence=4,
        sidechain=False, drop_gap=False, impact=True, backend="hybrid", moods=["urgent", "serious", "bright", "driving"],
        desc="News bumper: urgent 16th pulses, brass stabs, timpani and toms, big final hit.",
        use="announcements, changelogs, 'breaking' updates, weekly recaps",
        roles={"pad": (48, "sustain", "strings_pad"), "bass": (33, "pulse8", "saw_bass"),
               "arp": (48, "ostinato16", "strings_stac"), "lead": (61, "motif_slow", "brass"),
               "keys": (61, "brass_stabs", "brass")}),
    "lounge-jazz": dict(
        bpm=112, key="F", prog=[1, 4, 0, 5], bpc=1, sev=True, swing=0.64, tail=2.0, drums="jazz", cadence=4,
        sidechain=False, drop_gap=False, backend="sf", moods=["relaxed", "classy", "smooth", "warm"],
        desc="Lounge jazz: walking bass, ride cymbal swing, Rhodes comping, vibraphone melody.",
        use="hospitality, lifestyle, laid-back product tours",
        roles={"pad": (4, "comp", "rhodes"), "bass": (32, "walking", "round_bass"), "arp": (None, None, None),
               "lead": (11, "motif", "bell"), "keys": (None, None, None)}),
}

ALIASES = {"documentary": "underscore", "doc": "underscore", "documentary-underscore": "underscore",
           "cinematic-underscore": "underscore", "pulse": "minimal-pulse", "minimal": "minimal-pulse",
           "minimal-corporate": "corporate-minimal", "corporate": "corporate-minimal", "tech": "upbeat-tech",
           "lofi": "lofi-chill", "lo-fi": "lofi-chill", "cinematic": "cinematic-build", "trailer": "epic-trailer",
           "epic": "epic-trailer", "ambient": "ambient-pad", "pizzicato": "playful-pizzicato",
           "playful": "playful-pizzicato", "house": "deep-house", "hiphop": "hip-hop-beat", "hip-hop": "hip-hop-beat",
           "folk": "acoustic-folk", "acoustic": "acoustic-folk", "piano": "piano-emotional",
           "emotional": "piano-emotional", "tension": "dark-tension", "dark": "dark-tension", "suspense": "dark-tension",
           "8bit": "retro-8bit", "8-bit": "retro-8bit", "chiptune": "retro-8bit", "news": "news-bumper",
           "jazz": "lounge-jazz", "lounge": "lounge-jazz", "80s": "synthwave", "retrowave": "synthwave"}

SECTION_TYPES = {
    "intro": dict(energy=0.35, drums=0, roles=("pad", "arp", "keys")),
    "verse": dict(energy=0.6, drums=1, roles=("pad", "bass", "arp", "keys")),
    "build": dict(energy=0.7, drums=1, roles=("pad", "bass", "arp", "keys"), roll=True),
    "drop": dict(energy=1.0, drums=2, roles=("pad", "bass", "arp", "lead", "keys")),
    "chorus": dict(energy=1.0, drums=2, roles=("pad", "bass", "arp", "lead", "keys")),
    "break": dict(energy=0.4, drums=0, roles=("pad", "keys", "lead")),
    "bridge": dict(energy=0.55, drums=1, roles=("pad", "bass", "keys", "lead")),
    "outro": dict(energy=0.5, drums=1, roles=("pad", "bass", "keys")),
}
SECTION_ALIASES = {"hook": "drop", "main": "drop", "climax": "drop", "peak": "drop", "rise": "build",
                   "breakdown": "break", "calm": "break", "end": "outro", "ending": "outro", "start": "intro",
                   "open": "intro", "body": "verse"}

GM_DRUM = dict(kick=36, snare=38, clap=39, rim=37, hat=42, phat=44, ohat=46, crash=49, ride=51,
               tom_lo=41, tom_mid=45, tom_hi=48, tamb=54, shaker=70, wood_hi=76, wood_lo=77, cabasa=69,
               ride_bell=53)

# stem RMS (dBFS, over active frames) before mastering -> balance independent of the SoundFont
STEM_TARGET_DB = dict(drums=-15.0, bass=-18.0, pad=-24.0, arp=-23.0, lead=-21.0, keys=-24.0, sfx=-24.0)
ROLES = ("drums", "bass", "pad", "arp", "lead", "keys")


def resolve_style(name: str) -> str:
    k = (name or "").strip().lower().replace("_", "-").replace(" ", "-")
    k = ALIASES.get(k, k)
    if k not in STYLES:
        raise ShowtimeError("unknown style %r" % name, hint="run `showtime audio styles` (choose: %s)" % ", ".join(STYLES))
    return k


def style_list() -> List[dict]:
    return [{"style": k, "bpm": v["bpm"], "key": v["key"], "moods": v["moods"], "description": v["desc"],
             "use_for": v["use"], "backend": v["backend"], "drums": v["drums"] != "none",
             "aliases": sorted(a for a, t in ALIASES.items() if t == k)} for k, v in STYLES.items()]


# ---------------------------------------------------------------------------------------------
@dataclass
class Section:
    name: str
    start: float
    end: float
    beats: int
    bpm: float
    kind: str = "drop"

    @property
    def beat_len(self) -> float:
        return (self.end - self.start) / self.beats

    @property
    def bar_len(self) -> float:
        return 4 * self.beat_len

    @property
    def bars(self) -> int:
        return int(math.ceil(self.beats / 4))

    def bar_beats(self, bar: int) -> int:
        return min(4, self.beats - 4 * bar)


def section_kind(name: str) -> str:
    k = name.lower().rstrip("0123456789").strip("-_ ")
    k = SECTION_ALIASES.get(k, k)
    return k if k in SECTION_TYPES else "drop"


def parse_sections(spec, duration: float) -> List[Tuple[str, float]]:
    """'0:intro,4:build,8:drop,16:outro' | 'intro:0 build:4' | [{'name','start'}] | {'intro':0,...}."""
    if spec is None or spec == "" or spec == "auto":
        return default_sections(duration)
    items: List[Tuple[str, float]] = []
    if isinstance(spec, dict):
        items = [(str(k), float(v)) for k, v in spec.items()]
    elif isinstance(spec, (list, tuple)):
        for it in spec:
            if isinstance(it, dict):
                items.append((str(it.get("name") or it.get("label") or "drop"), float(it.get("start", it.get("t", 0)))))
            else:
                items += parse_sections(str(it), duration)
    else:
        for tok in str(spec).replace(";", ",").replace(" ", ",").split(","):
            tok = tok.strip()
            if not tok:
                continue
            if ":" not in tok:
                raise ShowtimeError("bad section %r (use time:name, e.g. 0:intro,8:drop)" % tok)
            a, b = tok.split(":", 1)
            try:
                items.append((b.strip(), float(a)))
            except ValueError:
                try:
                    items.append((a.strip(), float(b)))
                except ValueError:
                    raise ShowtimeError("bad section %r (use time:name, e.g. 0:intro,8:drop)" % tok)
    items = sorted(items, key=lambda m: m[1])
    for nm, t in items:
        if t < 0 or t >= duration:
            raise ShowtimeError("section %s at %.2fs is outside the track (0-%.2fs)" % (nm, t, duration))
    return items


def default_sections(duration: float) -> List[Tuple[str, float]]:
    d = duration
    if d < 8:
        return [("intro", 0.0), ("drop", round(d * 0.3, 2))]
    if d < 16:
        return [("intro", 0.0), ("build", round(d * 0.25, 2)), ("drop", round(d * 0.5, 2))]
    if d < 40:
        return [("intro", 0.0), ("build", round(d * 0.2, 2)), ("drop", round(d * 0.4, 2)), ("outro", round(d * 0.8, 2))]
    return [("intro", 0.0), ("verse", round(d * 0.12, 2)), ("build", round(d * 0.35, 2)), ("drop", round(d * 0.45, 2)),
            ("break", round(d * 0.7, 2)), ("chorus", round(d * 0.78, 2)), ("outro", round(d * 0.9, 2))]


def plan_timeline(style: dict, bpm: float, duration: float, markers: List[Tuple[str, float]]) -> Tuple[List[Section], float]:
    """One global tempo (+-6 %) minimising the worst per-section tempo bend, then each
    section's tempo nudged so every marker lands on a downbeat; the final hit is
    snapped to the grid inside the style's ring-out window."""
    tail = min(style["tail"], duration * 0.2)
    end_hit = duration - tail
    markers = sorted(markers, key=lambda m: m[1])
    if not markers or markers[0][1] > 0:
        markers.insert(0, ("intro", 0.0))
    markers = [m for m in markers if m[1] < end_hit - 0.3] or [("drop", 0.0)]
    bounds = [(nm, t0, markers[i + 1][1] if i + 1 < len(markers) else end_hit) for i, (nm, t0) in enumerate(markers)]
    bounds = [b for b in bounds if b[2] - b[1] > 0.3]

    def assign(cand):
        out = []
        for _, t0, t1 in bounds:
            d = t1 - t0
            beats = 2 * max(1, int(round(d * cand / 120.0)))
            if abs(60.0 * beats / d - cand) / cand > 0.03:
                beats = max(1, int(round(d * cand / 60.0)))
            out.append(beats)
        return out

    best = None
    for cand in np.arange(bpm * 0.94, bpm * 1.06 + 1e-9, 0.05):
        pairs = list(zip(assign(cand), bounds))
        use = pairs[:-1] or pairs
        dev = [abs(60.0 * b / (t1 - t0) - cand) / cand for b, (_, t0, t1) in use]
        cost = max(dev) + 0.25 * float(np.mean(dev)) + 0.35 * abs(cand - bpm) / bpm
        if best is None or cost < best[0]:
            best = (cost, float(cand))
    unit = 2 * 60.0 / best[1]
    name, t0, t1 = bounds[-1]
    k = max(1, round((t1 - t0) / unit))
    for kk in sorted({k, k - 1, k + 1}, key=lambda q: abs(q - (t1 - t0) / unit)):
        cand_end = t0 + kk * unit
        if kk >= 1 and 0.6 * tail <= duration - cand_end <= 1.6 * tail and duration - cand_end >= min(0.8, tail):
            end_hit = cand_end
            bounds[-1] = (name, t0, end_hit)
            break
    secs = [Section(nm, a, b, beats, 60.0 * beats / (b - a), section_kind(nm))
            for (nm, a, b), beats in zip(bounds, assign(best[1]))]
    return secs, end_hit


TEMPO_NOTE = 0.03   # a tempo bend above this is reported (the plan allows about 6 %)


def fitting_bpm(requested: float, markers: List[Tuple[str, float]], end_hit: float, tol: float = 0.01,
                lo: float = 0.75, hi: float = 1.34) -> Optional[float]:
    """The bpm closest to `requested` at which every marker interval is a whole number of 4-beat bars
    (within `tol` of that tempo). The last section ends at the final hit, so it is left free."""
    ts = sorted(t for _, t in markers)
    if not ts or ts[0] > 0:
        ts = [0.0] + ts
    ivals = [b - a for a, b in zip(ts, ts[1:]) if b < end_hit and b - a > 0.3]
    if not ivals:
        return None
    cands = sorted(np.arange(requested * lo, requested * hi, 0.1), key=lambda c: abs(c - requested))
    for c in cands:
        ok = True
        for d in ivals:
            bars = max(1, int(round(d * c / 240.0)))
            if abs(240.0 * bars / d - c) / c > tol:
                ok = False
                break
        if ok:
            return round(float(c), 1)
    return None


def plan_notes(requested: float, markers: List[Tuple[str, float]], secs: List[Section], end_hit: float,
               user_markers: bool) -> List[str]:
    """What the plan changed that a user would not expect: a tempo bend over 3 %, half bars, markers
    dropped because they fall inside the final hit's ring-out."""
    notes: List[str] = []
    kept = {(sec.name, round(sec.start, 3)) for sec in secs}
    for nm, t in markers:
        if t > 0 and (nm, round(t, 3)) not in kept and t >= end_hit - 0.3:
            notes.append("section %s at %.2fs merged into the ending: it starts inside the final hit's ring-out "
                         "(final hit at %.2fs); move it at least 0.3 s before the hit, or make the track longer"
                         % (nm, t, end_hit))
    if not user_markers:
        return notes
    dev = max((abs(sec.bpm - requested) / requested for sec in secs), default=0.0)
    halves = [sec for sec in secs[:-1] if sec.beats % 4]
    if dev > TEMPO_NOTE or halves:
        worst = max(secs, key=lambda sec: abs(sec.bpm - requested))
        msg = []
        if dev > TEMPO_NOTE:
            msg.append("the tempo bends %+.1f %% (%s at %.1f bpm, asked %.0f) to land every section on a downbeat"
                       % (100 * (worst.bpm - requested) / requested, worst.name, worst.bpm, requested))
        if halves:
            msg.append("%s %s a 2-beat bar" % (", ".join(sec.name for sec in halves), "has" if len(halves) == 1 else "have"))
        fit = fitting_bpm(requested, markers, end_hit)
        bar = 240.0 / requested
        snapped = ",".join("%g:%s" % (round(round(t / bar) * bar, 2), nm) for nm, t in markers)
        hint = ("Use --bpm %g: it fits every marker on whole bars" % fit) if fit else \
            ("No bpm near %.0f puts every marker on whole bars" % requested)
        notes.append("; ".join(msg) + ". %s; or keep %.0f bpm with markers on whole bars: --sections %s"
                     % (hint, requested, snapped))
    return notes


def chord_pcs(key: str, degree: int, seventh: bool) -> List[int]:
    pc, sc = dsp.scale_of(key)
    idx = [degree, degree + 2, degree + 4] + ([degree + 6] if seventh else [])
    return [(pc + sc[i % 7] + 12 * (i // 7)) for i in idx]


def voice_chord(chord: List[int], center: float, prev: Optional[List[int]], lo: int = 52, hi: int = 76) -> List[int]:
    """Chord tones near `center` with minimal motion from the previous voicing."""
    best, bcost = None, 1e9
    for base in range(24, 96, 12):
        for inv in range(len(chord)):
            tones = sorted(((c % 12) + base + (12 if j < inv else 0)) for j, c in enumerate(chord))
            if tones[0] < lo or tones[-1] > hi:
                continue
            cost = abs(float(np.mean(tones)) - center)
            if prev:
                cost += 0.7 * sum(min(abs(t - p) for p in prev) for t in tones)
            if cost < bcost:
                best, bcost = tones, cost
    return best or sorted(c % 12 + 60 for c in chord)


# ---------------------------------------------------------------------------------------------
class Composer:
    def __init__(self, style_name: str, bpm: Optional[float], key: Optional[str], duration: float,
                 markers: List[Tuple[str, float]], seed: int = 0):
        self.sn = resolve_style(style_name)
        self.st = STYLES[self.sn]
        self.bpm = float(bpm or self.st["bpm"])
        self.key = key or self.st["key"]
        parse_key(self.key)
        self.dur = float(duration)
        self.r = np.random.default_rng(seed)
        self.seed = seed
        self.secs, self.end_hit = plan_timeline(self.st, self.bpm, self.dur, markers)
        self.notes: Dict[str, list] = {k: [] for k in ROLES}
        self.cc: List[Tuple[float, int, int]] = []          # pad expression (t, cc, value)
        self.sfx: List[tuple] = []
        self.beats: List[dict] = []
        self.events: List[dict] = []
        self.motif = self._make_motifs()

    # -- helpers --------------------------------------------------------------------------------
    def t(self, sec: Section, bar: int, beat: float) -> float:
        sw = self.st["swing"]
        if sw and abs((beat * 2) % 2 - 1) < 1e-9:           # off-beat 8th -> swung
            beat = math.floor(beat) + sw
        return sec.start + (4 * bar + beat) * sec.beat_len

    def add(self, role, sec, bar, beat, dur_beats, pitch, vel, humanize=0.004):
        t0 = self.t(sec, bar, beat)
        if beat > 0 and humanize:
            t0 += float(self.r.normal(0, humanize))
        t1 = t0 + dur_beats * sec.beat_len
        v = int(np.clip(vel + self.r.normal(0, 4), 1, 127))
        self.notes[role].append([max(0.0, t0), min(t1, self.dur), int(np.clip(pitch, 0, 127)), v])

    def chord_at(self, gbar: int, sec: Section, bar: int) -> Tuple[int, List[int]]:
        prog, bpc = self.st["prog"], self.st["bpc"]
        deg = prog[(gbar // bpc) % len(prog)]
        if sec is self.secs[-1] and bar == sec.bars - 1 and sec.bars >= 2:
            deg = self.st["cadence"]
        return deg, chord_pcs(self.key, deg, self.st["sev"])

    def _make_motifs(self):
        """Two 2-bar cells (A, B) per rhythm family: (beat, dur, scale_step, strong)."""
        rhythms = {
            "motif": [[(0, .75), (.75, .75), (1.5, .5), (2, 1), (3, .5), (3.5, .5), (4, .75), (4.75, .75), (5.5, .5), (6, 2)],
                      [(0, .5), (.5, .5), (1, 1), (2.5, .5), (3, 1), (4, .5), (4.5, .5), (5, .5), (5.5, .5), (6, 1.5)]],
            "motif_slow": [[(0, 2), (2, 1), (3, 1), (4, 3), (7, 1)], [(0, 1), (1, 1), (2, 2), (4, 1.5), (5.5, .5), (6, 2)]],
            "motif_sparse": [[(0, 1.5), (1.5, .5), (2, 2), (4.5, 1), (5.5, .5), (6, 2)], [(1, 1), (2, 1.5), (4, 1), (5, 3)]],
        }
        out = {}
        for k, cells in rhythms.items():
            made = []
            for rh in cells:
                step, cell = 0, []
                for b, d in rh:
                    strong = (b % 2 == 0)
                    step = int(np.clip(step + self.r.choice([-2, -1, 1, 2, 0, 3]), -2, 6))
                    cell.append((b, d, step, strong))
                made.append(cell)
            out[k] = made
        return out

    # -- per-bar writer -------------------------------------------------------------------------
    def write_bar(self, sec: Section, bar: int, gbar: int, prev_voicing):
        stype = SECTION_TYPES[sec.kind]
        E = stype["energy"]
        if sec.kind == "build":
            E = 0.55 + 0.4 * bar / max(1, sec.bars - 1)
        if sec.kind == "outro":
            E = 0.6 - 0.3 * bar / max(1, sec.bars)
        vel = int(55 + 60 * E)
        deg, ch = self.chord_at(gbar, sec, bar)
        pc, sc = dsp.scale_of(self.key)
        roles = self.st["roles"]
        active = set(stype["roles"])
        # sparse arrangements (no pad) keep the arp/bass in the intro so nothing is silent
        if roles.get("pad", (None,))[0] is None and sec.kind == "intro":
            active |= {"arp", "bass"}
        last_build_bar = sec.kind == "build" and bar == sec.bars - 1
        bb = sec.bar_beats(bar)
        cut = bb - 0.5 if (last_build_bar and self.st.get("drop_gap")) else float(bb)
        v = voice_chord(ch, 64, prev_voicing)
        # a sustained chord lasts to the next chord change (bpc bars), not just this bar: with two bars
        # per chord, capping it at the bar left the second bar silent (pads, drones and bass dropped out)
        chord_left = (self.st["bpc"] - gbar % self.st["bpc"]) * 4
        hold = min(chord_left, sec.beats - 4 * bar)
        if sec.kind == "build" and self.st.get("drop_gap") and 4 * bar + hold >= sec.beats:
            hold = max(0.5, hold - 0.5)
        root = 36 + ((pc + sc[deg % 7]) % 12)
        if root > 45:
            root -= 12

        # PAD
        prog, pat, _ = roles.get("pad", (None, None, None))
        if prog is not None and "pad" in active:
            if pat == "comp":
                for b, d in [(0, 1.4), (1.5, .4), (2.5, 1.2)]:
                    if b < cut:
                        for p in v:
                            self.add("pad", sec, bar, b + float(self.r.uniform(0, .04)), min(d, cut - b), p, vel - 15)
            elif gbar % self.st["bpc"] == 0 or bar == 0:
                for p in v:
                    self.add("pad", sec, bar, 0, hold, p, vel - 20, humanize=0)
        # BASS
        prog, pat, _ = roles.get("bass", (None, None, None))
        if prog is not None and "bass" in active:
            bv = vel - 5
            if pat == "offbeat8":
                for b in np.arange(0.5, cut, 1.0):
                    self.add("bass", sec, bar, b, .45, root, bv)
            elif pat == "octave8":
                for i, b in enumerate(np.arange(0, cut, .5)):
                    self.add("bass", sec, bar, b, .4, root + (12 if i % 2 else 0), bv - (8 if i % 2 else 0))
            elif pat == "root4":
                for b, off in [(0, 0), (1, 7), (2, 0), (3, 7)]:
                    if b < cut:
                        self.add("bass", sec, bar, b, .9, root + off, bv)
            elif pat == "root_fifth":
                for b, off in [(0, 0), (2, 7)]:
                    if b < cut:
                        self.add("bass", sec, bar, b, 1.8, root + off, bv)
            elif pat == "lofi":
                for b, d, off in [(0, 1.2, 0), (1.75, .5, 7), (2.5, 1.2, 0), (3.5, .4, 10)]:
                    if b < cut:
                        self.add("bass", sec, bar, b, d, root + off, bv - 10)
            elif pat == "bounce":
                for b, off in [(0, 0), (1, 7), (2, 12), (3, 7)]:
                    if b < cut:
                        self.add("bass", sec, bar, b, .5, root + off, bv - 5)
            elif pat == "deep":
                for b, d, off in [(0, .75, 0), (1.5, .5, 0), (2.5, .4, 12), (3, .75, 0)]:
                    if b < cut:
                        self.add("bass", sec, bar, b, d, root + off, bv - (12 if off else 0))
            elif pat == "808":
                for b, d in [(0, 1.4), (1.75, .7), (2.5, 1.4)]:
                    if b < cut:
                        self.add("bass", sec, bar, b, min(d, cut - b), root - 12 if root > 40 else root, bv)
            elif pat == "pulse8":
                for i, b in enumerate(np.arange(0, cut, .5)):
                    self.add("bass", sec, bar, b, .4, root, bv - (0 if i % 4 == 0 else 12))
            elif pat == "walking":
                third = 3 if (sc[(deg + 2) % 7] - sc[deg % 7]) % 12 == 3 else 4
                line = [0, third, 7, 10 if self.st["sev"] else 12]
                if self.r.random() < 0.5:
                    line = [0, 7, 5, 2]
                for b in range(int(min(4, math.ceil(cut)))):
                    self.add("bass", sec, bar, b, .9, root + line[b % 4], bv - (0 if b == 0 else 10))
            else:  # sustain
                if gbar % self.st["bpc"] == 0 or bar == 0:
                    self.add("bass", sec, bar, 0, hold, root, bv - 10, humanize=0)
        # ARP / ostinato / accompaniment
        prog, pat, _ = roles.get("arp", (None, None, None))
        arp_ok = prog is not None and "arp" in active
        if arp_ok and sec.kind == "intro" and bar < sec.bars // 2 and pat not in ("arp16", "piano_arp", "strum", "chip_arp") \
                and roles.get("pad", (None,))[0] is not None:
            arp_ok = False
        if arp_ok:
            tones = [p + 12 for p in v] if pat in ("arp16", "chip_arp") else v
            if pat in ("arp16", "ostinato16", "chip_arp"):
                step = .25
                if pat == "arp16":
                    seq = tones + tones[::-1][1:-1]
                elif pat == "chip_arp":
                    seq = tones + [tones[0] + 12]
                else:
                    seq = [tones[0], tones[0] + 12 if tones[0] < 60 else tones[0], tones[1], tones[0]]
                for i, b in enumerate(np.arange(0, cut, step)):
                    acc = 12 if i % 4 == 0 else 0
                    self.add("arp", sec, bar, b, step * .88, seq[i % len(seq)] - (12 if pat == "ostinato16" else 0), vel - 25 + acc)
            elif pat == "ostinato8":
                low = [p - 12 for p in v]
                for i, b in enumerate(np.arange(0, cut, .5)):
                    self.add("arp", sec, bar, b, .4, low[[0, 1, 0, 2][i % 4] % len(low)], vel - 20 + (10 if i % 2 == 0 else 0))
            elif pat == "piano8":
                for b in np.arange(0, cut, .5):
                    for p in (v if b % 1 == 0 else [v[-1]]):
                        self.add("arp", sec, bar, b, .3, p, vel - 25)
            elif pat == "pulse_soft":
                # felt-piano pulse: two inner chord tones rocking in 8ths, soft, a slight lift on the
                # downbeat; the calm engine of documentary underscore (no melody, no attack peaks)
                a_, b_ = (v[1], v[-1]) if len(v) > 2 else (v[0], v[-1])
                for i, b in enumerate(np.arange(0, cut, .5)):
                    self.add("arp", sec, bar, b, .45, a_ if i % 2 == 0 else b_, vel - 42 + (6 if i % 8 == 0 else 0))
            elif pat == "pulse_mute":
                # muted pluck ostinato on the chord's root and fifth an octave up, 8ths, ghosted offbeats
                r5 = [root + 24, root + 31, root + 24, root + 36]
                for i, b in enumerate(np.arange(0, cut, .5)):
                    self.add("arp", sec, bar, b, .22, r5[i % 4], vel - 30 - (10 if i % 2 else 0))
            elif pat == "pizz8":
                seq = [v[0], v[2] if len(v) > 2 else v[1], v[1], v[2] if len(v) > 2 else v[0]]
                for i, b in enumerate(np.arange(0, cut, .5)):
                    self.add("arp", sec, bar, b, .3, seq[i % 4] + (12 if i % 4 == 2 else 0), vel - 10)
            elif pat == "piano_arp":
                low = root + 12 if root + 12 < v[0] else root
                seq = [low, v[0], v[1], v[2] if len(v) > 2 else v[0] + 12, v[0] + 12, v[2] if len(v) > 2 else v[1], v[1], v[0]]
                for i, b in enumerate(np.arange(0, cut, .5)):
                    self.add("arp", sec, bar, b, 1.2 if i % 4 == 0 else .9, seq[i % 8], vel - 22 + (8 if i % 4 == 0 else 0))
            elif pat == "strum":
                strum = [(0, 1, 1.0), (1, .5, .6), (1.5, 1, .8), (2.5, .5, .6), (3, 1, .9), (3.5, .5, .5)]
                six = sorted(set([root + 12] + v + [v[0] + 12]))[:6]
                for b, d, g in strum:
                    if b >= cut:
                        continue
                    down = int(b * 2) % 2 == 0
                    order = six if down else six[::-1]
                    for j, p in enumerate(order):
                        self.add("arp", sec, bar, b + j * 0.012 / max(sec.beat_len, 0.2), d, p, int((vel - 18) * g), humanize=0.002)
        # LEAD (two cells, question/answer, developing across phrases)
        prog, pat, _ = roles.get("lead", (None, None, None))
        if prog is not None and "lead" in active and pat:
            cells = self.motif[pat]
            phrase_bar = bar % 8
            cell = cells[1] if phrase_bar in (4, 5) else cells[0]
            half = bar % 2
            answer = (bar // 2) % 2 == 1
            lift = 2 if (sec.kind in ("drop", "chorus") and phrase_bar >= 6) else 0
            for b, d, step, strong in cell:
                if not (half * 4 <= b < half * 4 + 4):
                    continue
                bb_ = b - half * 4
                if bb_ >= cut:
                    continue
                s = (step if not answer else -step + 2) + lift
                pitch = 72 + pc + sc[s % 7] + 12 * (s // 7)
                if strong:
                    pitch = min(((p % 12) + 12 * k for p in ch for k in range(4, 9)), key=lambda q: abs(q - pitch))
                if answer and half == 1 and b == cell[-1][0]:
                    pitch = 72 + pc
                self.add("lead", sec, bar, bb_, min(d, cut - bb_) * .95, pitch, vel - 5)
        # KEYS / colour
        prog, pat, _ = roles.get("keys", (None, None, None))
        if prog is not None and "keys" in active:
            if pat == "stabs" and sec.kind in ("drop", "chorus"):
                for b in (0.5, 1.5, 2.75):
                    if b < cut:
                        for p in v:
                            self.add("keys", sec, bar, b, .2, p + 12, vel - 25)
            elif pat == "house_stab":
                for b in (0.5, 1.75, 2.5) if sec.kind in ("drop", "chorus") else (0.5, 2.5):
                    if b < cut:
                        for p in v:
                            self.add("keys", sec, bar, b, .3, p, vel - 20)
            elif pat == "brass_stabs" and sec.kind in ("drop", "chorus", "build", "verse"):
                for b in (0, 1.5, 3) if sec.kind in ("drop", "chorus") else (0,):
                    if b < cut:
                        for p in v[:3]:
                            self.add("keys", sec, bar, b, .45, p, vel - 10)
            elif pat == "timpani":
                if sec.kind in ("build", "drop", "chorus", "outro"):
                    hits = [0, 2] if sec.kind != "build" else [0, 1, 2, 3]
                    for b in hits:
                        if b < cut:
                            self.add("keys", sec, bar, b, .9, root + 12 if root < 40 else root, vel - 10 + (10 if b == 0 else 0))
            elif pat == "counter" and sec.kind in ("drop", "chorus", "verse"):
                for b in (1, 3):
                    if b < cut:
                        self.add("keys", sec, bar, b, .9, v[1] + 12, vel - 25)
            elif pat == "sustain_hi" and (gbar % self.st["bpc"] == 0 or bar == 0):
                for p in v[1:]:
                    self.add("keys", sec, bar, 0, hold, p + 12, vel - 30, humanize=0)
        self.write_drums(sec, bar, E, cut)
        return v

    def write_drums(self, sec: Section, bar: int, E: float, cut: float):
        fam = self.st["drums"]
        if fam == "none":
            return
        lvl = SECTION_TYPES[sec.kind]["drums"]
        if sec.kind == "outro" and bar >= sec.bars - 1:
            lvl = min(lvl, 1)
        if sec.kind == "intro" and bar >= sec.bars - 1 and sec.bars > 1:
            lvl = 1
        D, vel = GM_DRUM, int(60 + 55 * E)
        hits: List[Tuple[float, int, int]] = []
        if lvl >= 1:
            if fam == "house":
                hits += [(b, D["kick"], vel + 10) for b in range(4)]
                hits += [(b + .5, D["ohat" if lvl == 2 else "hat"], vel - 25) for b in range(4)]
                if lvl == 2:
                    hits += [(b, D["clap"], vel) for b in (1, 3)]
                    hits += [(b / 4, D["hat"], vel - 40 + (10 if b % 2 else 0)) for b in range(16) if b % 4 != 2]
            elif fam == "synthwave":
                hits += [(0, D["kick"], vel + 10), (2, D["kick"], vel + 5)] + ([(2.5, D["kick"], vel - 10)] if lvl == 2 else [])
                hits += [(b, D["snare"], vel + 5) for b in (1, 3)] if lvl == 2 else [(3, D["snare"], vel - 10)]
                hits += [(b / 2, D["hat"], vel - 30 + (10 if b % 2 == 0 else 0)) for b in range(8)]
            elif fam in ("boombap", "hiphop"):
                hits += [(0, D["kick"], vel + 5), (1.75, D["kick"], vel - 15), (2.5, D["kick"], vel)]
                hits += [(b, D["snare"] if lvl == 2 else D["rim"], vel - (0 if lvl == 2 else 15)) for b in (1, 3)]
                if fam == "hiphop" and lvl == 2:
                    hits += [(b / 4, D["hat"], vel - 35 + int(self.r.integers(0, 15))) for b in range(16)]
                else:
                    hits += [(b / 2, D["hat"], vel - 35 + int(self.r.integers(0, 15))) for b in range(8)]
            elif fam == "corporate":
                hits += [(0, D["kick"], vel), (2, D["kick"], vel - 5)]
                hits += [(b / 4, D["shaker"], vel - 45 + (15 if b % 2 == 0 else 0)) for b in range(16)]
                if lvl == 2:
                    hits += [(b, D["clap"], vel - 5) for b in (1, 3)] + [(3.5, D["kick"], vel - 20)]
            elif fam == "playful":
                hits += [(0, D["kick"], vel - 10), (2, D["kick"], vel - 15)]
                hits += [(b + .5, D["wood_hi"], vel - 30) for b in range(4)]
                if lvl == 2:
                    hits += [(b, D["clap"], vel - 10) for b in (1, 3)] + [(b / 2, D["tamb"], vel - 40) for b in range(8)]
            elif fam == "folk":
                hits += [(0, D["kick"], vel - 10), (2, D["kick"], vel - 15)]
                hits += [(b / 2, D["tamb"], vel - 40 + (10 if b % 2 else 0)) for b in range(8)]
                if lvl == 2:
                    hits += [(b, D["clap"], vel - 10) for b in (1, 3)]
            elif fam == "jazz":
                hits += [(b, D["ride"], vel - 25) for b in range(4)] + [(b + self.st["swing"], D["ride"], vel - 35) for b in (1, 3)]
                hits += [(b, D["phat"], vel - 35) for b in (1, 3)] + [(0, D["kick"], vel - 30)]
                if lvl == 2:
                    hits += [(2.5 + self.st["swing"] - .5, D["snare"], vel - 40), (3.5 + self.st["swing"] - .5, D["kick"], vel - 35)]
            elif fam == "soft":
                # a soft heartbeat: kick on 1 (and 3 at full energy), a quiet closed hat on the offbeats
                hits += [(0, D["kick"], vel - 20)] + ([(2, D["kick"], vel - 28)] if lvl == 2 else [])
                if lvl == 2:
                    hits += [(b + .5, D["hat"], vel - 50) for b in range(4)]
            elif fam == "chip":
                hits += [(0, D["kick"], vel), (2, D["kick"], vel - 5)] + [(b, D["snare"], vel - 5) for b in (1, 3)]
                hits += [(b / 2, D["hat"], vel - 30) for b in range(8)]
            elif fam == "news":
                hits += [(b, D["kick"], vel) for b in (0, 1.5, 2)] + [(b, D["snare"], vel) for b in (1, 3)]
                hits += [(b / 4, D["hat"], vel - 35 + (10 if b % 2 == 0 else 0)) for b in range(16)]
                if lvl == 2:
                    hits += [(3.5, D["tom_lo"], vel - 5), (3.75, D["tom_lo"], vel)]
            elif fam == "tension":
                hits += [(0, D["kick"], vel), (0.35, D["kick"], vel - 25)]
                if lvl == 2:
                    hits += [(2, D["kick"], vel - 5), (2.35, D["kick"], vel - 25), (3, D["tom_lo"], vel - 10)]
            elif fam in ("trailer", "cinematic"):
                hits += [(0, D["kick"], vel + 10)]
                if lvl == 2 or sec.kind == "build":
                    pat = [0, .75, 1.5, 2, 2.5, 3, 3.5] if fam == "trailer" else [0, 1, 2, 3, 3.5]
                    toms = [D["tom_lo"], D["tom_mid"], D["tom_lo"], D["tom_lo"], D["tom_mid"], D["tom_lo"], D["tom_hi"]]
                    hits += [(b, toms[i % len(toms)], vel - 5) for i, b in enumerate(pat)]
                if lvl == 2:
                    hits += [(1, D["snare"], vel), (3, D["snare"], vel), (2, D["kick"], vel)]
        restrained = bool(self.st.get("restrained"))
        if bar == 0 and sec is not self.secs[0] and SECTION_TYPES[sec.kind]["energy"] >= 0.5 and not restrained:
            hits.append((0, D["crash"], 110))
            self.events.append({"t": round(sec.start, 4), "type": "crash", "section": sec.name})
        if restrained:
            pass
        elif sec.kind == "build" and bar >= sec.bars - 2:
            last = bar == sec.bars - 1
            step = .25 if (last or sec.bars == 1) else .5
            inst = D["tom_lo"] if fam in ("trailer", "cinematic", "tension") else D["snare"]
            for b in np.arange(0, cut, step):
                prog_ = (b / 4 + (1 if last else 0)) / 2
                hits.append((float(b), inst, int(50 + 70 * prog_)))
        elif bar == sec.bars - 1 and sec is not self.secs[-1] and lvl >= 1 and sec.kind != "build":
            f0 = cut - 1
            hits = [h for h in hits if h[0] < f0] + [(f0, D["tom_hi"], vel - 10), (f0 + .25, D["tom_hi"], vel - 15),
                                                      (f0 + .5, D["tom_mid"], vel - 10), (f0 + .75, D["tom_lo"], vel - 5)]
        for b, p, vv in hits:
            if b < cut:
                self.add("drums", sec, bar, b, .25, p, vv, humanize=0.003 if p != D["kick"] else 0)

    def write_ending(self, last_voicing):
        pc, _ = dsp.scale_of(self.key)
        ch = chord_pcs(self.key, 0, self.st["sev"] and self.sn not in ("epic-trailer", "news-bumper"))
        v = voice_chord(ch, 64, last_voicing)
        ring = self.dur - self.end_hit
        roles = self.st["roles"]
        for role in ("pad", "keys", "lead"):
            if roles.get(role, (None,))[0] is not None:
                for p in (v if role != "lead" else [72 + pc]):
                    self.notes[role].append([self.end_hit, self.dur - 0.05, p + (12 if role == "keys" else 0), 90])
        if roles.get("arp", (None,))[0] is not None:
            for p in v:
                self.notes["arp"].append([self.end_hit, self.end_hit + min(ring, 1.5), p, 85])
        if roles.get("bass", (None,))[0] is not None:
            self.notes["bass"].append([self.end_hit, self.dur - 0.05, 36 + pc if pc < 10 else 24 + pc, 100])
        if self.st["drums"] != "none":
            ends = (GM_DRUM["kick"],) if self.st.get("restrained") else (GM_DRUM["kick"], GM_DRUM["crash"])
            for p in ends:
                self.notes["drums"].append([self.end_hit, self.end_hit + 0.25, p, 90 if self.st.get("restrained") else 115])
        self.events.append({"t": round(self.end_hit, 4), "type": "end_hit"})

    def compose(self):
        gbar, prev = 0, None
        for pad_sec in self.secs:
            if pad_sec.kind == "build":
                for k in range(8):
                    self.cc.append((pad_sec.start + (pad_sec.end - pad_sec.start) * k / 8, 11, 80 + int(47 * k / 7)))
            else:
                self.cc.append((pad_sec.start, 11, 110))
        for si, sec in enumerate(self.secs):
            for bar in range(sec.bars):
                prev = self.write_bar(sec, bar, gbar, prev)
                for b in range(sec.bar_beats(bar)):
                    self.beats.append(dict(t=round(sec.start + (4 * bar + b) * sec.beat_len, 5), bar=gbar, beat=b,
                                           section=sec.name))
                gbar += 1
            nxt = self.secs[si + 1] if si + 1 < len(self.secs) else None
            if nxt is not None and not self.st.get("restrained"):
                if nxt.kind in ("drop", "chorus") and sec.kind == "build":
                    rise = min(sec.end - sec.start, 2 * sec.bar_len, 6.0)
                    self.sfx.append(("riser", nxt.start, dict(dur=max(0.6, rise)), -3))
                    self.events.append({"t": round(nxt.start, 4), "type": "riser_end", "section": nxt.name})
                    if self.st.get("impact"):
                        self.sfx.append(("impact", nxt.start, dict(dur=3.0), -2))
                        self.events.append({"t": round(nxt.start, 4), "type": "impact", "section": nxt.name})
                if SECTION_TYPES[nxt.kind]["energy"] >= 0.5:
                    self.sfx.append(("reverse-cymbal", nxt.start, dict(dur=max(0.4, min(sec.bar_len, 2.5))), -8))
                if nxt.kind in ("outro", "break"):
                    self.sfx.append(("downlifter", nxt.start, dict(dur=max(0.5, min(2 * nxt.bar_len, 3.0))), -9))
        self.write_ending(prev)
        self.beats.append(dict(t=round(self.end_hit, 5), bar=gbar, beat=0, section="END_HIT"))

    def to_midi(self, roles: Optional[Sequence[str]] = None):
        import pretty_midi as pm
        m = pm.PrettyMIDI(initial_tempo=self.bpm, resolution=960)
        for role, notes in self.notes.items():
            if (roles and role not in roles) or not notes:
                continue
            prog = 0 if role == "drums" else (self.st["roles"][role][0] or 0)
            inst = pm.Instrument(program=int(prog), is_drum=(role == "drums"), name=role)
            for s, e, p, v in notes:
                inst.notes.append(pm.Note(int(v), int(p), float(s), float(max(e, s + 0.02))))
            if role == "pad":
                for t_, c, val in self.cc:
                    inst.control_changes.append(pm.ControlChange(c, val, float(t_)))
            m.instruments.append(inst)
        return m


# ---------------------------------------------------------------------------------------------
# SoundFont rendering (tinysoundfont), sample-accurate
# ---------------------------------------------------------------------------------------------
_TSF: Dict[str, tuple] = {}


def soundfonts() -> List[Path]:
    d = home() / "soundfonts"
    return sorted([p for p in d.glob("*") if p.suffix.lower() in (".sf2", ".sf3")]) if d.is_dir() else []


def find_soundfont(name: Optional[str] = None) -> Optional[Path]:
    """A SoundFont by path or (partial) name; default: GeneralUser GS if installed (optional extra),
    else MuseScore_General, else FluidR3Mono (core default)."""
    if name:
        p = Path(os.path.expanduser(name))
        if p.is_file():
            return p
        for sf_ in soundfonts():
            if name.lower() in sf_.name.lower():
                return sf_
        raise ShowtimeError("SoundFont %r not found" % name,
                            hint="installed: %s" % (", ".join(s.name for s in soundfonts()) or "none (run `showtime setup`)"))
    fonts = soundfonts()
    for pref in ("GeneralUser", "MuseScore_General", "FluidR3"):
        for f in fonts:
            if f.name.startswith(pref):
                return f
    return fonts[0] if fonts else None


def tsf_available() -> bool:
    try:
        import tinysoundfont  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _synth_for(sf_path: Path):
    key = str(sf_path)
    if key not in _TSF:
        import tinysoundfont as tsf
        s = tsf.Synth(samplerate=SR, gain=-3)
        sfid = s.sfload(str(sf_path))
        _TSF[key] = (s, sfid)
    return _TSF[key]


def render_sf(notes: list, program: int, is_drum: bool, n_samples: int, sf_path: Path,
              cc: Sequence[Tuple[float, int, int]] = ()) -> np.ndarray:
    s, sfid = _synth_for(sf_path)
    s.sounds_off()
    ch = 9 if is_drum else 0
    try:
        s.program_select(ch, sfid, 128 if is_drum else 0, 0 if is_drum else int(program), is_drum)
    except Exception:  # noqa: BLE001 - some banks lack bank 128 presets
        s.program_select(ch, sfid, 0, int(program), is_drum)
    s.control_change(ch, 7, 110)
    s.control_change(ch, 11, 127)
    ev = []
    for st_, en, p, v in notes:
        a = int(round(st_ * SR))
        b = max(a + 1, int(round(en * SR)))
        ev.append((a, 1, int(p), int(v)))
        ev.append((b, 0, int(p), 0))
    for t_, c, val in cc:
        ev.append((int(round(t_ * SR)), 2, int(c), int(val)))
    ev.sort(key=lambda e: (e[0], e[1]))
    out = np.zeros((n_samples, 2), np.float32)
    pos = 0

    def gen(k):
        nonlocal pos
        while k > 0:
            m = min(k, 65536)
            buf = np.frombuffer(s.generate(m), dtype=np.float32).reshape(-1, 2)
            out[pos:pos + m] = buf[:m]
            pos += m
            k -= m
    for smp, typ, a1, a2 in ev:
        smp = min(smp, n_samples)
        if smp > pos:
            gen(smp - pos)
        if typ == 1:
            s.noteon(ch, a1, a2)
        elif typ == 0:
            s.noteoff(ch, a1)
        else:
            s.control_change(ch, a1, a2)
    if pos < n_samples:
        gen(n_samples - pos)
    s.sounds_off()
    return out


# ---------------------------------------------------------------------------------------------
# numpy synth voices
# ---------------------------------------------------------------------------------------------
def _gate(x: np.ndarray, dur: float, rel: float) -> np.ndarray:
    N = len(x)
    g = np.ones(N, np.float32)
    k = min(N, dsp.n(dur))
    if k < N:
        g[k:] = np.exp(-np.arange(N - k) / max(1.0, rel * SR))
    return x * g


def voice_note(voice: str, pitch: int, dur: float, vel: int, r) -> np.ndarray:
    """One note (mono float32) from a numpy synth voice; includes its release tail."""
    f = float(midi_to_hz(pitch))
    a = vel / 127.0
    tail = 0.5
    if voice in ("supersaw_pad", "warm_pad", "strings_pad", "choir", "drone_pad"):
        tail = 0.8
    N = dsp.n(dur + tail)
    tt = np.arange(N) / SR
    if voice in ("saw_bass",):
        x = dsp.osc("saw", f, N) * 0.6 + np.sin(2 * np.pi * f * tt) * 0.8
        x = dsp.butter(x, min(700 + 1500 * a, 4000), "low", 2) * dsp.env_adsr(N, 0.004, 0.15, 0.7, 0.08)
        rel = 0.06
    elif voice == "sub_bass":
        x = np.sin(2 * np.pi * f * tt) + 0.25 * np.sin(4 * np.pi * f * tt)
        x = dsp.softclip(x * dsp.env_adsr(N, 0.004, 0.3, 0.8, 0.1), 1.3)
        rel = 0.08
    elif voice == "round_bass":
        x = np.sin(2 * np.pi * f * tt) * 0.9 + dsp.osc("triangle", f, N) * 0.3
        x = x * np.exp(-tt / 1.2) * np.minimum(1, tt / 0.004)
        rel = 0.06
    elif voice in ("supersaw_pad", "warm_pad", "drone_pad"):
        det = 14 if voice == "supersaw_pad" else 8
        x = dsp.supersaw(f, N, 5, det, r).mean(1)
        x = dsp.butter(x, 2500 if voice == "supersaw_pad" else 1400, "low", 2)
        x = x * dsp.env_adsr(N, min(0.5, dur / 3), 0.3, 0.8, 0.5)
        rel = 0.5
    elif voice == "strings_pad":
        x = sum(dsp.osc("saw", f * (1 + d), N, float(r.uniform(0, 6.28))) for d in (-0.004, 0.0, 0.005)) / 3
        vib = 1 + 0.004 * np.sin(2 * np.pi * 5.2 * tt)
        x = dsp.butter(x * vib, 3200, "low", 2) * dsp.env_adsr(N, min(0.35, dur / 3), 0.2, 0.85, 0.4)
        rel = 0.35
    elif voice == "strings_stac":
        x = sum(dsp.osc("saw", f * (1 + d), N) for d in (-0.003, 0.004)) / 2
        x = dsp.butter(x, 3500, "low", 2) * dsp.env_adsr(N, 0.01, 0.08, 0.5, 0.08)
        rel = 0.08
    elif voice == "choir":
        src = sum(dsp.osc("saw", f * (1 + d), N) for d in (-0.005, 0.0, 0.006)) / 3
        x = sum(dsp.resonator(src, fr, 6) * g for fr, g in ((700, 1.0), (1200, 0.5), (2600, 0.25)))
        x = x * dsp.env_adsr(N, min(0.4, dur / 3), 0.2, 0.9, 0.5)
        rel = 0.5
    elif voice == "brass":
        env = dsp.env_adsr(N, 0.04, 0.2, 0.75, 0.15)
        x = dsp.osc("saw", f, N) * 0.7 + dsp.osc("saw", f * 1.004, N) * 0.5
        x = dsp.svf(x, 400 + 2600 * env * a, 1.1, "lp", block=64) * env
        rel = 0.15
    elif voice in ("fm_keys", "rhodes"):
        idx, ratio = (1.6, 1.0) if voice == "rhodes" else (2.2, 1.0)
        mod = np.sin(2 * np.pi * f * ratio * tt) * idx * np.exp(-tt / 0.4)
        x = np.sin(2 * np.pi * f * tt + mod) * np.exp(-tt / 1.2) * np.minimum(1, tt / 0.002)
        x = x * (1 + (0.15 * np.sin(2 * np.pi * 4.5 * tt) if voice == "rhodes" else 0))
        rel = 0.2
    elif voice == "piano":
        x = sum(g * np.sin(2 * np.pi * f * h * tt * (1 + 0.0004 * h * h)) * np.exp(-tt * (0.8 + 0.9 * h))
                for h, g in ((1, 1.0), (2, 0.5), (3, 0.25), (4, 0.12), (5, 0.06)))
        x = x * np.minimum(1, tt / 0.002) + dsp.butter(dsp.noise(N, "white", r), 2500, "high", 2) * np.exp(-tt / 0.01) * 0.05
        rel = 0.25
    elif voice == "bell":
        x = dsp.fm_tone(f, dur + tail, 2.0, 3.5, 0.8, 0.1)[:N]
        rel = 0.4
    elif voice == "organ":
        x = sum(g * np.sin(2 * np.pi * f * h * tt) for h, g in ((0.5, 0.5), (1, 1.0), (2, 0.5), (3, 0.3), (4, 0.2)))
        x = x * dsp.env_adsr(N, 0.005, 0.05, 0.9, 0.05) * (1 + 0.1 * np.sin(2 * np.pi * 6 * tt))
        rel = 0.05
    elif voice in ("pluck", "guitar", "pizz"):
        decay = {"pluck": 0.994, "guitar": 0.9975, "pizz": 0.985}[voice]
        x = dsp.karplus(f, dur + tail, r, bright=0.7 if voice == "pluck" else 0.5, decay=decay)
        if voice == "pluck":
            x = dsp.butter(x, 5000, "low", 2)
        rel = 0.05 if voice != "guitar" else 0.3
    elif voice == "flute":
        x = np.sin(2 * np.pi * f * tt * (1 + 0.003 * np.sin(2 * np.pi * 5 * tt))) + 0.1 * np.sin(4 * np.pi * f * tt)
        x = x * dsp.env_adsr(N, 0.06, 0.1, 0.85, 0.1) + dsp.butter(dsp.noise(N, "white", r), 2000, "high", 2) * 0.03
        rel = 0.1
    elif voice == "timpani":
        fr = f * (1 + 0.05 * np.exp(-tt / 0.05))
        x = np.sin(2 * np.pi * np.cumsum(fr) / SR) * np.exp(-tt / 0.7) + dsp.butter(dsp.noise(N, "brown", r), 300, "low", 2) * np.exp(-tt / 0.1) * 0.5
        rel = 0.8
    elif voice in ("chip_square", "chip_pulse", "square_arp"):
        pw = {"chip_square": 0.5, "chip_pulse": 0.25, "square_arp": 0.5}[voice]
        x = dsp.osc("pulse", f, N, pw=pw) * dsp.env_adsr(N, 0.002, 0.05, 0.7, 0.03)
        if voice == "square_arp":
            x = dsp.butter(x, 3500, "low", 2)
        rel = 0.03
    elif voice == "chip_triangle":
        x = np.round(dsp.osc("triangle", f, N) * 8) / 8 * dsp.env_adsr(N, 0.002, 0.05, 0.9, 0.03)
        rel = 0.03
    elif voice == "saw_lead":
        x = dsp.osc("saw", f * (1 + 0.004 * np.sin(2 * np.pi * 5.5 * tt)), N) * 0.6 + dsp.osc("saw", f * 1.007, N) * 0.4
        x = dsp.butter(x, 3800, "low", 2) * dsp.env_adsr(N, 0.006, 0.1, 0.7, 0.1)
        rel = 0.1
    else:  # square_lead and anything unknown
        x = dsp.osc("square", f * (1 + 0.003 * np.sin(2 * np.pi * 5 * tt)), N)
        x = dsp.butter(x, 3500, "low", 2) * dsp.env_adsr(N, 0.004, 0.1, 0.6, 0.08)
        rel = 0.08
    return (_gate(np.asarray(x, dtype=np.float32), dur, rel) * a).astype(np.float32)


def drum_hit(p: int, vel: int, r, kit: str = "acoustic") -> np.ndarray:
    a = vel / 127.0
    D = GM_DRUM
    if kit == "chip":
        if p in (D["kick"], 35):
            N = dsp.n(0.15)
            tt = np.arange(N) / SR
            x = np.sign(np.sin(2 * np.pi * np.cumsum(60 + 200 * np.exp(-tt / 0.02)) / SR)) * np.exp(-tt / 0.06) * 0.6
        elif p in (D["snare"], D["clap"], D["rim"]):
            N = dsp.n(0.15)
            tt = np.arange(N) / SR
            x = np.sign(r.standard_normal(N)) * np.exp(-tt / 0.05) * 0.5
        else:
            N = dsp.n(0.05)
            tt = np.arange(N) / SR
            x = dsp.butter(np.sign(r.standard_normal(N)), 6000, "high", 2) * np.exp(-tt / 0.015) * 0.4
        return (x * a).astype(np.float32)
    if p in (D["kick"], 35):
        N = dsp.n(0.5)
        tt = np.arange(N) / SR
        base, dec = (45, 0.35) if kit == "808" else (48, 0.18)
        f = base + 110 * np.exp(-tt / 0.03)
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / dec) + dsp.noise(N, "white", r) * np.exp(-tt / 0.002) * 0.3
        x = dsp.softclip(x, 1.5)
    elif p in (D["snare"], 40, D["rim"]):
        N = dsp.n(0.3)
        tt = np.arange(N) / SR
        x = np.sin(2 * np.pi * 185 * tt) * np.exp(-tt / 0.05) * 0.6 + dsp.butter(dsp.noise(N, "white", r), 1200, "high", 2) * np.exp(-tt / 0.09)
        if p == D["rim"]:
            x = dsp.resonator(x, 1700, 6) * np.exp(-tt / 0.02)
    elif p == D["clap"]:
        N = dsp.n(0.35)
        tt = np.arange(N) / SR
        e = sum(np.exp(-np.clip(tt - o, 0, None) / 0.006) * (tt >= o) for o in (0, 0.011, 0.023)) + 0.5 * np.exp(-tt / 0.12)
        x = dsp.butter(dsp.noise(N, "white", r), [900, 5000], "band", 2) * e
    elif p in (D["hat"], D["phat"], D["ohat"], D["crash"], D["ride"], D["tamb"], D["shaker"], D["cabasa"], D["ride_bell"]):
        dec = {D["hat"]: 0.04, D["phat"]: 0.03, D["ohat"]: 0.25, D["crash"]: 1.6, D["ride"]: 0.6, D["ride_bell"]: 0.8}.get(p, 0.06)
        N = dsp.n(dec * 4)
        tt = np.arange(N) / SR
        metal = sum(dsp.osc("square", fq * 1.6, N) for fq in (205.3, 304.4, 369.6, 522.7, 540, 800))
        x = dsp.butter(metal * 0.3 + dsp.noise(N, "white", r), 7000 if p not in (D["crash"], D["ride"]) else 4500, "high", 2) * np.exp(-tt / dec)
        if p == D["shaker"]:
            x = dsp.butter(dsp.noise(N, "white", r), 5000, "high", 2) * np.exp(-tt / 0.03) * np.minimum(1, tt / 0.008)
        if p == D["tamb"]:
            x = x * 0.7 + dsp.resonator(dsp.noise(N, "white", r), 7000, 4) * np.exp(-tt / 0.05) * 0.4
    elif p in (D["tom_lo"], D["tom_mid"], D["tom_hi"], 43, 47, 50):
        base = {D["tom_lo"]: 80, D["tom_mid"]: 110, D["tom_hi"]: 150}.get(p, 100)
        N = dsp.n(0.5)
        tt = np.arange(N) / SR
        x = np.sin(2 * np.pi * np.cumsum(base * (1 + 0.5 * np.exp(-tt / 0.02))) / SR) * np.exp(-tt / 0.25)
    else:
        N = dsp.n(0.12)
        tt = np.arange(N) / SR
        x = dsp.resonator(dsp.noise(N, "white", r) * np.exp(-tt / 0.002), 1200 if p == D["wood_hi"] else 800, 15)
        x = x / (np.abs(x).max() + 1e-9)
    return (np.asarray(x) * a).astype(np.float32)


_PAN = {"arp": -0.35, "keys": 0.35, "lead": 0.1}


def render_numpy(notes: list, role: str, voice: str, n_samples: int, seed: int = 0, kit: str = "acoustic") -> np.ndarray:
    r = np.random.default_rng(seed)
    out = np.zeros((n_samples, 2), np.float32)
    cache: dict = {}
    D = GM_DRUM
    for s, e, p, v in notes:
        if role == "drums":
            k = (p, v // 8)
            if k not in cache:
                cache[k] = drum_hit(p, v, r, kit)
            x = cache[k]
            pn = {D["hat"]: 0.25, D["ohat"]: 0.3, D["shaker"]: -0.3, D["tom_hi"]: -0.3, D["tom_lo"]: 0.3,
                  D["ride"]: 0.3, D["tamb"]: -0.25}.get(p, 0.0)
        else:
            k = (p, round(e - s, 2), v // 8)
            if k not in cache:
                cache[k] = voice_note(voice, p, max(0.02, e - s), v, r)
            x = cache[k]
            pn = _PAN.get(role, 0.0)
        dsp.mix_at(out, dsp.pan(x, pn), int(round(s * SR)))
    if role == "pad":
        out = dsp.widen(out, 15, 0.8)
    return out


# ---------------------------------------------------------------------------------------------
# post chain
# ---------------------------------------------------------------------------------------------
def active_rms_db(x: np.ndarray) -> float:
    m = x.mean(1) if x.ndim == 2 else x
    hop = dsp.n(0.05)
    k = len(m) // hop
    if k == 0:
        return -120.0
    fr = np.sqrt((m[: k * hop].reshape(k, hop) ** 2).mean(1))
    act = fr[fr > fr.max() * 0.03] if fr.max() > 0 else fr
    return float(20 * np.log10(np.sqrt((act ** 2).mean()) + 1e-12))


def sidechain_env(kick_times: Sequence[float], n_samples: int, depth_db: float = -7.0, release: float = 0.18) -> np.ndarray:
    g = np.ones(n_samples, np.float32)
    rel = dsp.n(release)
    curve = 1 - (1 - 10 ** (depth_db / 20)) * np.exp(-np.arange(rel) / (rel / 4))
    atk = dsp.n(0.004)
    seg = np.concatenate([np.linspace(1, curve[0], atk), curve]).astype(np.float32)
    for t in kick_times:
        i = int(t * SR) - atk
        if 0 <= i < n_samples:
            e = min(n_samples, i + len(seg))
            g[i:e] = np.minimum(g[i:e], seg[: e - i])
    return g


def process_stem(role: str, x: np.ndarray, style: dict, bpm: float) -> np.ndarray:
    beat = 60.0 / bpm
    N = len(x)
    if role == "drums":
        y = dsp.eq(x, [("hp", 30, 0.707, 0), ("highshelf", 8000, 0.707, 2.0)])
        y = dsp.compress(y, -14, 3, 0.005, 0.09)
        if style["drums"] in ("synthwave", "trailer", "cinematic", "tension"):
            y = dsp.conv_reverb(y, t60=1.4 if style["drums"] == "synthwave" else 2.2, wet=0.18, tail=False, seed=3)
    elif role == "bass":
        y = dsp.eq(x, [("hp", 32, 0.707, 0), ("lp", 5000, 0.707, 0)])
        y = dsp.compress(y, -18, 4, 0.01, 0.12)
    elif role == "pad":
        y = dsp.eq(x, [("hp", 160, 0.707, 0), ("peak", 400, 1.0, -3)])
        y = dsp.chorus(y, 0.3, 3.0, 11.0, 0.3)
        y = dsp.conv_reverb(y, t60=2.8, wet=0.35, tail=False, seed=5)
    elif role == "arp":
        y = dsp.eq(x, [("hp", 180, 0.707, 0)])
        y = dsp.delay(y, beat * 0.75, 0.3, 0.22)
        y = dsp.conv_reverb(y, t60=1.8, wet=0.2, tail=False, seed=6)
    elif role == "lead":
        y = dsp.eq(x, [("hp", 200, 0.707, 0), ("peak", 3000, 1.0, 2.0)])
        if style["bpm"] > 80:
            y = dsp.delay(y, beat * 0.75, 0.25, 0.18)
        y = dsp.conv_reverb(y, t60=2.0 if style["bpm"] > 80 else 3.0, wet=0.2 if style["bpm"] > 80 else 0.32, tail=False, seed=8)
    else:
        y = dsp.eq(x, [("hp", 120, 0.707, 0)])
        y = dsp.conv_reverb(y, t60=2.0, wet=0.25, tail=False, seed=9)
    return dsp.pad_to(y, N).astype(np.float32)


# ---------------------------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------------------------
def _backend_for(style: dict, requested: str, sf_path: Optional[Path]) -> str:
    req = (requested or "auto").lower()
    if req not in ("auto", "sf", "synth", "hybrid", "soundfont", "numpy"):
        raise ShowtimeError("unknown backend %r (auto, sf, synth, hybrid)" % requested)
    req = {"soundfont": "sf", "numpy": "synth"}.get(req, req)
    want = style["backend"] if req == "auto" else req
    if want in ("sf", "hybrid") and (not tsf_available() or sf_path is None):
        why = "tinysoundfont is not installed" if not tsf_available() else "no SoundFont found in ~/.showtime/soundfonts"
        if req != "auto":
            warn("%s backend unavailable (%s); using the numpy synth" % (want, why))
        else:
            debug("SoundFont rendering unavailable (%s); numpy synth" % why)
        return "synth"
    return want


def build(style: str, duration: float, out: Path, bpm: Optional[float] = None, key: Optional[str] = None,
          sections=None, seed: int = 0, backend: str = "auto", soundfont: Optional[str] = None,
          lufs: float = -14.0, tp: float = -1.0, stems: bool = True, with_sfx: bool = True,
          midi: bool = True) -> dict:
    """Compose and render. Returns a summary dict (also written into <out>.beats.json)."""
    t_start = time.perf_counter()
    if duration < 2.0:
        raise ShowtimeError("duration must be at least 2 seconds")
    if duration > 600:
        raise ShowtimeError("duration above 10 minutes is not supported (compose sections and join them)")
    sn = resolve_style(style)
    st = STYLES[sn]
    markers = parse_sections(sections, duration)
    C = Composer(sn, bpm, key, duration, list(markers), seed)
    plan_msgs = plan_notes(C.bpm, markers, C.secs, C.end_hit, sections not in (None, "", "auto"))
    C.compose()
    N = int(round(duration * SR))
    sf_path = None
    if backend not in ("synth", "numpy"):
        try:
            sf_path = find_soundfont(soundfont)
        except ShowtimeError:
            if soundfont:
                raise
    be = _backend_for(st, backend, sf_path)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    stem_dir = out.with_name(out.stem + ".stems")
    kit = "chip" if st["drums"] == "chip" else ("808" if st["drums"] == "hiphop" else "acoustic")
    rendered: Dict[str, np.ndarray] = {}
    for role in ROLES:
        notes = C.notes.get(role) or []
        if not notes:
            continue
        prog, _, voice = (0, None, None) if role == "drums" else st["roles"][role]
        use_sf = be == "sf" or (be == "hybrid" and role not in ("drums", "bass"))
        if use_sf:
            x = render_sf(notes, int(prog or 0), role == "drums", N, sf_path, C.cc if role == "pad" else ())
        else:
            x = render_numpy(notes, role, voice or "square_lead", N, seed, kit)
        rendered[role] = x
    mix = np.zeros((N, 2), np.float32)
    kick_times = [s for s, e, p, v in C.notes.get("drums", []) if p == GM_DRUM["kick"]]
    stem_gain = {}
    mean_bpm = float(np.mean([s.bpm for s in C.secs]))
    stems_out: Dict[str, np.ndarray] = {}
    for role, x in rendered.items():
        if np.abs(x).max() < 1e-6:
            continue
        y = process_stem(role, x, st, mean_bpm)
        g = st.get("stem_db", {}).get(role, STEM_TARGET_DB[role]) - active_rms_db(y)
        y = y * 10 ** (g / 20)
        if st.get("sidechain") and role in ("pad", "arp", "keys", "bass") and kick_times:
            y = y * sidechain_env(kick_times, N, -8 if role == "pad" else -4)[:, None]
        stem_gain[role] = round(float(g), 1)
        stems_out[role] = y
        mix += y
    placed = []
    if with_sfx and C.sfx:
        bus = np.zeros((N, 2), np.float32)
        for name, at, kw, gdb in C.sfx:
            y, meta = sfx.render(name, key=C.key, seed=seed, intensity=0.8, level=False, **kw)
            y = dsp.normalize_peak(y, -1)
            start = int(round((at - meta["hit"]) * SR))
            dsp.mix_at(bus, y, start, 10 ** (gdb / 20))
            placed.append({"sfx": name, "hit_at": round(at, 4), "start": round(start / SR, 4)})
        if np.abs(bus).max() > 0:
            g = STEM_TARGET_DB["sfx"] - active_rms_db(bus)
            bus *= 10 ** (min(g, 6) / 20)
            stems_out["sfx"] = bus
            mix += bus
    if st.get("crackle"):
        r = np.random.default_rng(seed)
        cr = (r.random(N) < 0.0006) * r.standard_normal(N) * 0.5 + dsp.noise(N, "pink", r) * 0.02
        cr = dsp.butter(cr.astype(np.float32), [300, 9000], "band", 2)
        mix += dsp.to_stereo(cr) * 10 ** (-34 / 20)
    mix = dsp.fade(mix, 0.0, 0.25)
    y, minfo = master.process(mix, "music", lufs, tp)
    y = dsp.fade(dsp.pad_to(y, N), 0.0, 0.03)
    wav.save(out, y, bits=24)
    written = {"audio": str(out)}
    if stems:
        stem_dir.mkdir(parents=True, exist_ok=True)
        # stems carry the same master gain so they sum to (roughly) the master
        mg = 10 ** (minfo.get("gain_db", 0.0) / 20)
        for role, s_ in stems_out.items():
            wav.save(stem_dir / ("%s.wav" % role), s_ * mg, bits=24)
        written["stems"] = str(stem_dir)
    if midi:
        mp = out.with_suffix(".mid")
        C.to_midi().write(str(mp))
        written["midi"] = str(mp)
    downbeats = [b["t"] for b in C.beats if b["beat"] == 0 and b["section"] != "END_HIT"]
    beats_doc = {
        "schema": "showtime.beats/1", "source": "composed", "file": str(out), "style": sn, "key": C.key,
        "bpm": round(mean_bpm, 3), "requested_bpm": C.bpm, "time_signature": 4, "duration": duration,
        "end_hit": round(C.end_hit, 4), "rhythmic": st["drums"] != "none", "pacing": "beat_cut" if st["drums"] != "none" else "phrase_flow",
        "sections": [{"name": s.name, "kind": s.kind, "start": round(s.start, 4), "end": round(s.end, 4), "bars": s.bars,
                      "beats": s.beats, "bpm": round(s.bpm, 3), "energy": SECTION_TYPES[s.kind]["energy"]} for s in C.secs],
        "beats": [b["t"] for b in C.beats if b["section"] != "END_HIT"],
        "downbeats": downbeats,
        "bars": [{"t": b["t"], "bar": b["bar"], "section": b["section"]} for b in C.beats if b["beat"] == 0],
        "events": sorted(C.events, key=lambda e: e["t"]),
        "cues": {s.name: round(s.start, 4) for s in C.secs},
        "backend": be, "soundfont": sf_path.name if (sf_path and be != "synth") else None, "notes": plan_msgs,
    }
    beats_path = out.with_name(out.stem + ".beats.json")
    write_json(beats_path, beats_doc)
    written["beats"] = str(beats_path)
    # a composed bed is the user's own generated work: say so, so a mix that uses the file directly
    # credits it correctly instead of warning that it has no license information
    lic_path = out.with_name(out.name + ".license.json")
    write_json(lic_path, {
        "source": "showtime audio compose", "file": out.name, "license": "generated", "license_class": "free",
        "attribution_required": False,
        "credit": "composed locally with showtime audio compose (%s, key %s, %s backend, seed %d)" % (sn, C.key, be, seed),
        "fetched": time.strftime("%Y-%m-%dT%H:%M:%S")})
    written["license"] = str(lic_path)
    summary = {
        "style": sn, "key": C.key, "bpm": round(mean_bpm, 2), "requested_bpm": C.bpm, "duration": duration,
        "samples": N, "backend": be, "soundfont": sf_path.name if (sf_path and be != "synth") else None,
        "end_hit": round(C.end_hit, 4), "sections": beats_doc["sections"], "sfx": placed, "stem_gain_db": stem_gain,
        "master": minfo, "notes": {k: len(v) for k, v in C.notes.items() if v}, "plan_notes": plan_msgs, "outputs": written,
        "seconds": round(time.perf_counter() - t_start, 2),
    }
    return summary


def cache_key(spec: dict) -> str:
    """Stable hash of a compose spec (for mix-time caching)."""
    return hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]

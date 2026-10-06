"""The showreel tone ("go all out"): one switch that changes what the agent aims for and what the checks judge.

A showreel, a hype reel or a "go all out" / "show off" brief is judged on energy, density, craft, surprise and the
ending, not on restraint (references/tones.md "showreel", motion-craft.md section 11). When it is on:

  showtime check   flash words (data-st-flash, or F.text(..., {flash: true}) on a canvas) may be held under their
                   reading time when they are texture, not message: at most FLASH_MAX_WORDS words and FLASH_MAX_CHARS
                   characters, on screen at least FLASH_MIN_S. Every other text keeps the reading rule, and at least
                   one text (the hero line: the name, the one message) must be held its full reading time (no_hero_line).
                   Size, contrast, overlaps and platform UI zones are judged as always.
  showtime qa      the launch grammar (at most 6 scenes, at most 5 hard cuts) does not apply; a reel with fewer than
                   shots_per_15s_min shots per 15 s is showreel_sparse, an end card that holds still over
                   end_hold_max_frac of the reel (or a last shot over end_shot_max_frac) is showreel_long_end, two
                   shots that look alike are showreel_repeats (st.qa.reel measures all three, and the energy dips).
                   Frozen and black frames, loudness, the flash safety limit and the phone check are judged as always.
  review-pack      the critic gets the showreel rubric (energy, density, variety, craft, surprise, ending; long
                   holds, repeats and dips count against the reel) instead of the launch checklist and the restraint
                   questions.

Where it comes from, first match wins (resolve()):
  1. the project's showtime.json "tone" (`showtime new ... --tone showreel`, the `showreel` template); any other
     tone there turns it off
  2. the job's "tone" (job.json)
  3. the brief's words: the job's goal and request ("showreel", "demo reel", "hype reel", "go all out", "show off")
  4. off

The JS twin is scripts/lib/showreel.mjs (`showtime check`); change both together: tests/test_showreel.py checks they
agree on the words and the numbers. Stdlib only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

TONE = "showreel"
THRESHOLDS_FILE = Path(__file__).resolve().parents[2] / "runtime" / "thresholds.json"
# runtime/thresholds.json "showreel" wins over these (the fallback only)
DEFAULTS: Dict[str, float] = {
    "flash_max_words": 3,      # a flash word is texture: a word or three, never a sentence
    "flash_max_chars": 24,
    "flash_min_s": 0.2,        # under this it is a glitch frame, not a word
    "shots_per_15s_min": 12,   # round 5 (2026-10-05): the winner cut 13-14 shots in 15 s, the losing takes 9-11
    "shots_per_15s_max": 14,
    "end_hold_max_frac": 0.1,  # the end card holds still at most 10% of the reel (~1 s of 15 s); the losers held 2.5-3.5 s
    "end_shot_max_frac": 0.2,  # and the last shot, moving or not, runs at most 20%
    "repeat_hist_max": 0.3,    # two shots look alike: colour histogram distance under this ...
    "repeat_layout_min": 0.7,  # ... and coarse layout correlation over this (the same technique or layout twice)
    "dip_max_s": 1.0,          # nothing moves much for longer than this before the end card: an energy dip
}

# The brief's words. Bare "hype" stays a launch word (st.qa.rhythm.LAUNCH_WORDS): a hype video for a product is a launch.
WORDS = re.compile(
    r"\b(?:(?:show|demo|sizzle|hype|motion|portfolio|design)[\s-]?reels?"
    r"|go(?:es|ing)?\s+all[\s-]out|went\s+all[\s-]out|all-out"
    r"|show(?:s|ing)?[\s-]off)\b", re.I)
NEGATION = re.compile(r"\b(?:don'?t|do\s+not|no\s+need\s+to|not|never|without)\s+(?:\w+\s+)?$", re.I)


def brief_words(text: Any) -> Optional[str]:
    """The first showreel phrase in a brief ('go all out', 'showreel' ...), None when there is none or it is negated."""
    if not isinstance(text, str) or not text:
        return None
    for m in WORDS.finditer(text):
        if NEGATION.search(text[max(0, m.start() - 24):m.start()]):
            continue
        return re.sub(r"\s+", " ", m.group(0).lower())
    return None


def thresholds() -> Dict[str, float]:
    """DEFAULTS with runtime/thresholds.json "showreel" over them (positive numbers only)."""
    out = dict(DEFAULTS)
    try:
        doc = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8")).get("showreel") or {}
        for k in out:
            v = doc.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                out[k] = float(v)
    except (OSError, ValueError, AttributeError):
        pass
    return out


def _tone(v: Any) -> Optional[str]:
    return v.strip().lower() if isinstance(v, str) and v.strip() else None


def resolve(cfg: Optional[Dict[str, Any]] = None, job: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """{"on": bool, "source": "project" | "job" | "brief" | "default", "detail": the tone or the words found}.

    cfg: the project's showtime.json; job: its job.json (goal, request, tone)."""
    cfg = cfg if isinstance(cfg, dict) else {}
    job = job if isinstance(job, dict) else {}
    for src, d in (("project", cfg), ("job", job)):
        t = _tone(d.get("tone"))
        if t:
            return {"on": t == TONE, "source": src, "detail": t}
    for key in ("goal", "request"):
        w = brief_words(job.get(key))
        if w:
            return {"on": True, "source": "brief", "detail": w}
    return {"on": False, "source": "default", "detail": ""}


def describe(r: Dict[str, Any]) -> str:
    """One line for check, qa and the opening line: 'showreel tone (the brief says "go all out")'."""
    if not r.get("on"):
        return "showreel tone: off"
    why = {"project": "showtime.json tone", "job": "the job's tone",
           "brief": 'the brief says "%s"' % r.get("detail", "")}.get(r.get("source"), r.get("source", ""))
    return "showreel tone (%s): flash words allowed, density and energy judged instead of restraint" % why


def for_project(proj: Optional[Any], cfg: Optional[Dict[str, Any]] = None, job_dir: Optional[Any] = None) -> Dict[str, Any]:
    """resolve() for a project folder: its showtime.json and the job that holds it (or `job_dir`)."""
    if cfg is None and proj:
        try:
            cfg = json.loads((Path(str(proj)) / "showtime.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cfg = {}
    job: Dict[str, Any] = {}
    jd = Path(str(job_dir)) if job_dir else None
    if jd is None and proj:
        try:
            from .job import ledger
            jd = ledger.enclosing_job(proj)
        except Exception:  # noqa: BLE001 - the job is optional
            jd = None
    if jd is not None and (jd / "job.json").is_file():
        try:
            job = json.loads((jd / "job.json").read_text(encoding="utf-8")) or {}
        except (OSError, ValueError):
            job = {}
    return resolve(cfg, job)

"""Review modes: how much reviewing a finished video gets.

  quality (the default)  every finished video gets the full review: a first look, qa and a look after the
                         final render, and a critic round (review-pack + a critic sub-agent; pairwise against
                         the previous render when there is one) before delivery.
  lean (opt-in)          a cheaper draft pass: one look per stage, and the critic round only when the video is
                         publish-bound or the user asks. check, qa and the looks still run.

The efficient plumbing (brief command output, `showtime guide` sections, `job init` checking setup, splice
renders, looks through a disposable reviewer) is always on; only the amount of reviewing changes.

Where the mode comes from, first match wins:
  1. the job's own mode (`showtime job init --mode lean`, `showtime job note --mode quality`)
  2. the project's showtime.json "review_mode" (`showtime new ... --mode lean`, the MCP new_project tool)
  3. SHOWTIME_MODE=lean|quality in the environment
  4. the saved default (`showtime config mode lean`, or the plugin option in Claude Code's /config)
  5. quality

Stdlib only: `showtime config` runs before setup.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

MODES = ("quality", "lean")
DEFAULT = "quality"
ENV = "SHOWTIME_MODE"
SETTING = "mode"          # the key in plugin-settings.json

SUMMARY = {
    "quality": "full review on every finished video: looks, qa after the final render and a critic round "
               "(review-pack + critic) before delivery",
    "lean": "cheaper draft pass: one look per stage; the critic round only when publish-bound or asked for",
}
# what lean leaves out, for --help texts and doctor
LEAN_SKIPS = ("lean skips the critic round (review-pack + a critic sub-agent) unless the video is publish-bound "
              "or the user asks, and takes one look per stage; check, qa and the looks still run")
SWITCH = "lean (a cheaper draft pass) only when the user asks: --mode lean or showtime config mode lean"

SOURCES = {
    "flag": "--mode",
    "job": "the job",
    "project": "the project's showtime.json",
    "env": ENV,
    "config": "showtime config",
    "default": "default",
}


def normalize(value: Any) -> Optional[str]:
    """'lean' / 'quality' (any case, surrounding spaces) or None for anything else."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    return v if v in MODES else None


# ------------------------------------------------------------------ saved default (plugin-settings.json)

def settings_file() -> Path:
    """The settings file the launcher reads (SHOWTIME_SETTINGS, else ~/.showtime/plugin-settings.json)."""
    from .launcher import settings_file as _sf
    return _sf()


def load_settings() -> Dict[str, Any]:
    try:
        data = json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_setting(key: str, value: Any) -> Path:
    """Set (value not None) or clear (None) one saved setting, keeping every other key. Atomic write."""
    f = settings_file()
    data = load_settings()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    if key == SETTING:
        data.pop("_mode_from", None)      # set here, not by the plugin option: the plugin keeps it
    data.setdefault("_about", "showtime settings. Claude Code's plugin options (/config) are saved here when a "
                              "session starts; `showtime config` sets the review mode. SHOWTIME_* environment "
                              "variables override them.")
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name("%s.%d.tmp" % (f.name, os.getpid()))
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(str(tmp), str(f))
    return f


def default_mode() -> Tuple[str, str]:
    """(mode, source) for a new job with no --mode: SHOWTIME_MODE, the saved default, else quality."""
    env = os.environ.get(ENV, "")
    if env and "${" not in env:
        m = normalize(env)
        if m:
            return m, "env"
    m = normalize(load_settings().get(SETTING))
    if m:
        return m, "config"
    return DEFAULT, "default"


def resolve(explicit: Optional[str] = None) -> Tuple[str, str]:
    """(mode, source): an explicit --mode value wins, else default_mode()."""
    m = normalize(explicit)
    if m:
        return m, "flag"
    return default_mode()


def project_mode(project: Optional[Any]) -> Optional[str]:
    """The "review_mode" a project's showtime.json asks for (None when absent or unreadable)."""
    if not project:
        return None
    try:
        cfg = json.loads((Path(str(project)) / "showtime.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return normalize(cfg.get("review_mode")) if isinstance(cfg, dict) else None


def job_mode(data: Optional[Dict[str, Any]], project: Optional[Any] = None) -> Tuple[str, str]:
    """(mode, source) that applies to a job: its own, its project's, else the default."""
    data = data or {}
    m = normalize(data.get("review_mode"))
    if m:
        return m, "job"
    pm = project_mode(project or data.get("project") or (data.get("pointers") or {}).get("project"))
    if pm:
        return pm, "project"
    return default_mode()


def describe(mode: str, source: str) -> str:
    """One line: 'quality (default): full review on every ...; say 'lean' for a cheaper draft pass'."""
    src = SOURCES.get(source, source)
    tail = ("; " + SWITCH) if mode == "quality" else "; `showtime config mode quality` (or --mode quality) for the full review"
    return "%s (%s): %s%s" % (mode, src, SUMMARY[mode], tail)


def info() -> Dict[str, Any]:
    """The current default as data (doctor --json, config --json)."""
    m, s = default_mode()
    return {"mode": m, "source": s, "source_text": SOURCES.get(s, s), "summary": SUMMARY[m],
            "settings_file": str(settings_file()), "env": ENV, "modes": list(MODES), "lean_skips": LEAN_SKIPS}

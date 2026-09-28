"""Narration cues for Manim scenes: the voice timeline (or an estimate) in the shape the scene kit reads.

    {"fps": 30, "estimated": false, "source": "voice/timeline.json", "audio": "/abs/voice/vo.wav",
     "duration": 24.1, "lines": [{"id": "hook", "index": 0, "text": "...", "start": 0.35, "end": 4.1,
       "slot_start": 0.35, "slot_end": 4.6, "speech_start": 0.43, "speech_end": 3.9,
       "file": "/abs/voice/lines/01-hook.wav", "words": [["Add", 0.43, 0.72], ...]}]}

All times are seconds on the video's clock, which is the voice file's clock: scene k of a project
starts at the slot start of its first beat, so the concatenated scenes line up with vo.wav exactly.

Without a voice yet, `estimate()` times narration.md at a calm reading pace, so a draft is already
paced like the finished video; renders say the timing is estimated until `showtime voice script` ran.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..common import ShowtimeError

EST_WPS = 2.6          # words per second of a calm explainer read
EST_PAUSE = 0.45       # pause after each line
EST_LEAD = 0.35        # silence before the first line
EST_TAIL = 1.5         # hold after the last line


def norm_word(w: str) -> str:
    """Case- and punctuation-insensitive form used to match cue words."""
    return re.sub(r"[^\w]+", "", w.lower(), flags=re.UNICODE)


def from_timeline(path: Path, fps: float) -> Dict[str, Any]:
    """Voice `timeline.json` (showtime voice script) -> cues."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ShowtimeError("cannot read the voice timeline %s: %s" % (path, e),
                            hint="create it with: showtime voice script narration.md -o voice/")
    if isinstance(data, dict) and data.get("lines") and "slot_start" in data["lines"][0]:
        return _normalise_cues(data, fps, path)      # already a cues file
    lines_in = data.get("lines") if isinstance(data, dict) else None
    if not lines_in:
        raise ShowtimeError("%s has no lines" % path, why="a voice timeline lists one entry per narration line",
                            hint="re-create it with: showtime voice script narration.md -o voice/")
    base = path.parent
    lines: List[Dict[str, Any]] = []
    for i, ln in enumerate(lines_in):
        slot = ln.get("slot") or {}
        words = [[w.get("text", ""), float(w["start"]), float(w["end"])] for w in ln.get("words") or []
                 if "start" in w and "end" in w]
        f = ln.get("file")
        lines.append({
            "id": str(ln.get("id") or "line%d" % (i + 1)), "index": i, "text": ln.get("text", ""),
            "start": float(ln.get("start", 0.0)), "end": float(ln.get("end", ln.get("start", 0.0))),
            "slot_start": float(slot.get("start", ln.get("start", 0.0))),
            "slot_end": float(slot.get("end", ln.get("end", 0.0))),
            "speech_start": float(ln.get("speech_start", ln.get("start", 0.0))),
            "speech_end": float(ln.get("speech_end", ln.get("end", 0.0))),
            "file": str((base / f).resolve()) if f else None, "words": words,
        })
    audio = data.get("file")
    dur = float(data.get("duration") or (lines[-1]["slot_end"] if lines else 0.0))
    if lines and lines[-1]["slot_end"] < dur:
        lines[-1]["slot_end"] = dur
    return {"fps": fps, "estimated": False, "source": str(path), "duration": dur,
            "audio": str((base / audio).resolve()) if audio else None, "lines": lines}


def _normalise_cues(data: Dict[str, Any], fps: float, path: Path) -> Dict[str, Any]:
    out = dict(data)
    out["fps"] = fps
    out.setdefault("source", str(path))
    out.setdefault("estimated", False)
    return out


def parse_narration(text: str) -> List[Dict[str, str]]:
    """narration.md: `## id` headings, each followed by the line's text (comments and markup dropped)."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    out: List[Dict[str, str]] = []
    cur: Optional[Dict[str, str]] = None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r"^#{2,3}\s+(.+?)\s*$", line)
        if m:
            cur = {"id": m.group(1).strip().split()[0], "text": ""}
            out.append(cur)
            continue
        if line.startswith("#") or not line or cur is None:
            continue
        line = re.sub(r"\[pause [\d.]+\]", " ", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)   # [word](pronunciation) -> word
        cur["text"] = (cur["text"] + " " + line).strip()
    return [ln for ln in out if ln["text"]]


def estimate(narration: Path, fps: float, wps: float = EST_WPS) -> Dict[str, Any]:
    """Cues timed from narration.md at `wps` words per second (a stand-in until the voice exists)."""
    lines_in = parse_narration(Path(narration).read_text(encoding="utf-8"))
    if not lines_in:
        raise ShowtimeError("%s has no narration lines" % narration,
                            hint="write one `## id` heading per line, with the spoken text under it")
    t = EST_LEAD
    lines: List[Dict[str, Any]] = []
    for i, ln in enumerate(lines_in):
        words = []
        for w in ln["text"].split():
            dur = max(0.18, (len(norm_word(w)) + 2) / (6.0 * wps) * 1.0)
            words.append([w, round(t, 3), round(t + dur * 0.85, 3)])
            t += dur
            if w.endswith((".", "!", "?")):
                t += 0.25
            elif w.endswith((",", ";", ":")):
                t += 0.12
        start = lines[-1]["slot_end"] if lines else EST_LEAD
        speech_end = words[-1][2] if words else t
        slot_end = speech_end + EST_PAUSE
        lines.append({"id": ln["id"], "index": i, "text": ln["text"], "start": start, "end": speech_end,
                      "slot_start": start, "slot_end": round(slot_end, 3), "speech_start": words[0][1] if words else start,
                      "speech_end": speech_end, "file": None, "words": words})
        t = slot_end
    if lines:
        lines[-1]["slot_end"] = round(lines[-1]["slot_end"] + EST_TAIL, 3)
    return {"fps": fps, "estimated": True, "source": str(narration), "audio": None,
            "duration": lines[-1]["slot_end"] if lines else 0.0, "lines": lines}


def load(cues_arg: Optional[str], project_dir: Path, voice_rel: Optional[str], narration_rel: Optional[str],
         fps: float) -> Optional[Dict[str, Any]]:
    """The cues for a render/check: --cues, else manim.json `voice` when it exists, else an estimate
    from narration.md, else None (scenes then run on their own timing)."""
    if cues_arg:
        p = Path(cues_arg)
        if not p.is_absolute() and not p.exists():
            p = project_dir / cues_arg
        if not p.is_file():
            raise ShowtimeError("cue file not found: %s" % cues_arg,
                                hint="make it with: showtime voice script narration.md -o voice/  (then pass "
                                     "--cues voice/timeline.json)")
        if p.suffix.lower() == ".md":
            return estimate(p, fps)
        return from_timeline(p, fps)
    if voice_rel and (project_dir / voice_rel).is_file():
        return from_timeline(project_dir / voice_rel, fps)
    if narration_rel and (project_dir / narration_rel).is_file():
        return estimate(project_dir / narration_rel, fps)
    return None


def describe(cues: Dict[str, Any]) -> List[str]:
    """Human-readable cue table: each line with its slot and numbered words (what until()/at() accept)."""
    out = ["%s cues from %s (%d lines, %.2f s)" % ("estimated" if cues.get("estimated") else "voice",
                                                   cues.get("source"), len(cues["lines"]), cues.get("duration", 0))]
    for ln in cues["lines"]:
        out.append("## %s  slot %.2f-%.2f  speech %.2f-%.2f" % (ln["id"], ln["slot_start"], ln["slot_end"],
                                                              ln["speech_start"], ln["speech_end"]))
        seen: Dict[str, int] = {}
        parts = []
        for w, s, _e in ln["words"]:
            k = norm_word(w)
            seen[k] = seen.get(k, 0) + 1
            parts.append("%s%s %.2f" % (k, ("#%d" % seen[k]) if seen[k] > 1 else "", s))
        out.append("   " + "  ".join(parts))
    return out

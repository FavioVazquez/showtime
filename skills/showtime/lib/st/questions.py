"""Stop-and-ask questions (showtime.json "questions"): the times of their "pause and think" beats.

The Python twin of scripts/lib/questions.mjs, for the mixer (a `"questions"` block in a mix spec ducks
the music under every beat and can tick through its countdown). Same rules: `at` is seconds or a voice
cue, the id of a narration line ("ask-sum" = the end of its speech, "ask-sum.start", "ask-sum.end+0.4"),
looked up where the mix plays each line (a `vo-<id>` track of `retime --from-voice` or a track playing
the line's own file, voice/lines/NN-id.wav, else the vo.wav track's start, else 0: voice/timeline.json
times are vo.wav times, not video times); `think` defaults to 3 s; the pause lands on a frame. Questions that do
not resolve are left out here (`showtime check` names them).

Stdlib only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

THINK_DEFAULT = 3.0
_CUE = re.compile(r"^([A-Za-z0-9_][\w-]*)(?:\.(start|end))?\s*(?:([+-])\s*(\d+(?:\.\d+)?|\.\d+))?$")


def _read(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def _num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _start(t: Optional[Dict[str, Any]]) -> float:
    return _num(t.get("start", t.get("at", 0))) if t else 0.0


def line_offsets(tl: Dict[str, Any], tl_dir: Path, tracks: List[Dict[str, Any]], where: Callable[[Any], Path]) -> Dict[str, float]:
    """{line id: seconds to add to its timeline.json times (vo.wav times) for where the mix plays it}: a
    `vo-<id>` track or a voice track playing the line's own file (`file` in the timeline, next to it) at its
    `start`, else the start of the voice track playing the whole vo.wav, else 0. `where` resolves a track's
    file the way the mix does. st.qa.hearing places lines with this too."""
    voices = [t for t in tracks if isinstance(t, dict) and t.get("kind") == "voice"]
    vo = (Path(tl_dir) / str(tl.get("file") or "vo.wav")).resolve()
    whole = next((t for t in voices if t.get("file") and where(t["file"]) == vo), None)
    out: Dict[str, float] = {}
    for ln in tl.get("lines") or []:
        if not isinstance(ln, dict) or ln.get("id") is None:
            continue
        lid = str(ln["id"])
        mine = next((t for t in voices if str(t.get("id", "")) == "vo-" + lid), None)
        if mine is None and ln.get("file"):
            f = (Path(tl_dir) / str(ln["file"])).resolve()
            mine = next((t for t in voices if t.get("file") and where(t["file"]) == f), None)
        s0 = _num(ln.get("start", (ln.get("slot") or {}).get("start", 0)))
        out[lid] = _start(mine) - s0 if mine is not None else _start(whole)
    return out


def voice_cues(project: Path, tracks: List[Dict[str, Any]], mix_dir: Optional[Path] = None) -> Dict[str, Dict[str, float]]:
    """{line id: {start, end, from}} in video seconds (speech start/end, slot start), each line placed where
    the mix plays it (line_offsets)."""
    project = Path(project)

    def where(f: Any) -> Path:
        for b in (mix_dir, project):
            if b is not None and (Path(b) / str(f)).exists():
                return (Path(b) / str(f)).resolve()
        return (project / str(f)).resolve()

    dirs: List[Path] = []
    for t in tracks:
        if isinstance(t, dict) and t.get("kind") == "voice" and t.get("file"):
            d = where(t["file"]).parent
            if d.name == "lines":
                d = d.parent
            if d not in dirs:
                dirs.append(d)
    vdir = (project / "voice").resolve()
    if vdir not in dirs:
        dirs.append(vdir)

    out: Dict[str, Dict[str, float]] = {}
    for d in dirs:
        tl = _read(d / "timeline.json")
        if not isinstance(tl, dict) or not isinstance(tl.get("lines"), list):
            continue
        offs = line_offsets(tl, d, tracks, where)
        for ln in tl["lines"]:
            if not isinstance(ln, dict) or ln.get("id") is None or str(ln["id"]) in out:
                continue
            lid = str(ln["id"])
            s0 = _num(ln.get("start", (ln.get("slot") or {}).get("start", 0)))
            off = offs.get(lid, 0.0)
            ss = _num(ln.get("speech_start", ln.get("start", 0)))
            se = _num(ln.get("speech_end", ln.get("end", ss)), ss)
            out[lid] = {"start": round(ss + off, 4), "end": round(se + off, 4), "from": round(s0 + off, 4)}
    return out


def resolve_at(at: Any, cues: Dict[str, Dict[str, float]]) -> Optional[float]:
    if isinstance(at, bool):
        return None
    if isinstance(at, (int, float)):
        return float(at)
    if not isinstance(at, str) or not at.strip():
        return None
    s = at.strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    m = _CUE.match(s)
    if not m or m.group(1) not in cues:
        return None
    c = cues[m.group(1)]
    off = (-1 if m.group(3) == "-" else 1) * float(m.group(4)) if m.group(3) else 0.0
    return round((c["start"] if m.group(2) == "start" else c["end"]) + off, 4)


def project_mix(project: Path, cfg: Dict[str, Any]) -> Optional[tuple]:
    """The showtime.json "audio" mix as (tracks, folder its paths start from), or None."""
    aud = cfg.get("audio")
    if isinstance(aud, str) and aud.lower().endswith(".json"):
        f = (Path(project) / aud).resolve()
        j = _read(f)
        return (j["tracks"], f.parent) if isinstance(j, dict) and isinstance(j.get("tracks"), list) else None
    if isinstance(aud, list):
        return [t for t in aud if isinstance(t, dict)], Path(project)
    if isinstance(aud, dict) and isinstance(aud.get("tracks"), list):
        return aud["tracks"], Path(project)
    return None


def beats(project: Path, tracks: Optional[List[Dict[str, Any]]] = None, mix_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """[{id, t, think, resume}] for every question that resolves, by time. Voice cues are looked up in
    the project's own mix (showtime.json "audio"), as `showtime export` and `check` do; `tracks` (the
    mix being rendered) is the fallback when the project names none."""
    cfg = _read(Path(project) / "showtime.json")
    qs = cfg.get("questions") if isinstance(cfg, dict) else None
    if not isinstance(qs, list):
        return []
    own = project_mix(Path(project), cfg)
    if own:
        tracks, mix_dir = own
    tracks = [t for t in tracks or [] if isinstance(t, dict)]
    fps = _num(cfg.get("fps"), 30.0) or 30.0
    cues: Optional[Dict[str, Dict[str, float]]] = None
    out = []
    for i, q in enumerate(qs):
        if not isinstance(q, dict):
            continue
        at = q.get("at")
        if isinstance(at, str) and not re.fullmatch(r"\s*\d+(\.\d+)?\s*", at) and cues is None:
            cues = voice_cues(Path(project), tracks, mix_dir)
        t = resolve_at(at, cues or {})
        think = _num(q.get("think", THINK_DEFAULT), THINK_DEFAULT)
        if t is None or t < 0 or not (0 < think <= 60):
            continue
        t = round(round(t * fps) / fps, 4)
        out.append({"id": str(q.get("id", "q%d" % (i + 1))), "t": t, "think": think, "resume": round(t + think, 4)})
    return sorted(out, key=lambda b: b["t"])

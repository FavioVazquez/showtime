"""`showtime clean`: free disk space by removing intermediates that showtime itself wrote.

Provenance rules:
- The target must be a showtime job folder (job.json or render.json) or a project
  (showtime.json). Anything else is refused.
- Only known intermediate folders are removed, and only inside that target:
  frame dumps, check/snap/qa/review scratch, audio intermediates, diagnostics,
  and in Manim projects (manim.json, e.g. <job>/manim/) the build/ scene cache
  and the *-draft* renders in out/.
- Deliverables are never touched: final/preview videos, poster, exports/,
  credits, share text, job.json, render.json, SHOWTIME.md, studio/, the person's
  notes on the video (review/notes/) and anything the user put there. Symlinks are
  never followed.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..common import ShowtimeError, human_size

# (relative path, level) - level "frames" is included in "default" which is included in "all"
JOB_ITEMS: List[Tuple[str, str]] = [
    ("work/frames", "frames"), ("work/splice", "frames"),
    ("work/check", "default"), ("work/snap", "default"), ("work/qa", "default"),
    ("work/audio", "default"), ("work/diagnostics", "default"), ("work/review-frames", "default"),
    ("work/video.mp4", "default"), ("work/video.mov", "default"), ("work/video.webm", "default"),
    ("work/mux.mp4", "default"), ("work/mux.mov", "default"), ("work/mux.webm", "default"),
    ("review", "all"), ("work/logs", "all"),
]
PROJECT_ITEMS: List[Tuple[str, str]] = [
    ("work/frames", "frames"),
    ("work/check", "default"), ("work/snap", "default"), ("work/qa", "default"),
    ("work/diagnostics", "default"), ("work/review", "all"),
]
LEVELS = {"frames": 0, "default": 1, "all": 2}
# Manim projects (manim.json) inside a job, or cleaned directly: the per-scene render cache and logs
# under build/ (the next `manim render` rebuilds what it needs) and draft renders in out/ (*-draft*).
# Finals in out/ and everything else in the project stay.
MANIM_FILE = "manim.json"


def _size(p: Path) -> Tuple[int, int]:
    """(bytes, files) under p without following symlinks."""
    if p.is_symlink():
        return 0, 1
    if p.is_file():
        return p.stat().st_size, 1
    total = n = 0
    for dirpath, dirnames, filenames in os.walk(p, followlinks=False):
        for fn in filenames:
            fp = Path(dirpath) / fn
            try:
                total += fp.lstat().st_size
            except OSError:
                pass
            n += 1
    return total, n


def kind_of(target: Path) -> str:
    if (target / "job.json").is_file() or (target / "render.json").is_file():
        return "job"
    if (target / "showtime.json").is_file():
        return "project"
    if (target / MANIM_FILE).is_file():
        return "manim"
    return ""


def manim_projects(target: Path, max_depth: int = 2) -> List[Path]:
    """Manim project folders (manim.json) at or under `target` (a job's manim/ usually)."""
    out = [target] if (target / MANIM_FILE).is_file() else []
    for pat in ("*/" + MANIM_FILE, "*/*/" + MANIM_FILE)[:max_depth]:
        for m in sorted(target.glob(pat)):
            if not m.parent.is_symlink() and m.parent not in out and "work" not in m.relative_to(target).parts[:1]:
                out.append(m.parent)
    return out


def _manim_items(proj: Path, level: str) -> List[Tuple[Path, str]]:
    if LEVELS[level] < LEVELS["default"]:
        return []
    items: List[Tuple[Path, str]] = [(proj / "build", "manim scene cache and logs (the next render rebuilds them)")]
    od = proj / "out"
    if od.is_dir() and not od.is_symlink():
        for f in sorted(od.iterdir()):
            if f.is_file() and not f.is_symlink() and "-draft" in f.stem:
                items.append((f, "manim draft render"))
    return items


def plan(target: Path, level: str = "default") -> Dict[str, Any]:
    """What would be removed. -> {target, kind, items: [{path, bytes, files}], bytes, kept: [...]}"""
    target = target.resolve()
    kind = kind_of(target)
    if not kind:
        raise ShowtimeError("%s is not a showtime job or project; refusing to clean it" % target,
                            hint="pass a folder under showtime-out/ (with job.json/render.json), a project with "
                                 "showtime.json, or a Manim project with manim.json")
    table = JOB_ITEMS if kind == "job" else PROJECT_ITEMS if kind == "project" else []
    items: List[Dict[str, Any]] = []
    cands: List[Path] = [target / rel for rel, lv in table if LEVELS[lv] <= LEVELS[level]]
    what: Dict[Path, str] = {}
    for mp in manim_projects(target):
        for c, label in _manim_items(mp, level):
            cands.append(c)
            what[c] = label
    review = target / "review"
    if review in cands and (review / "notes").is_dir() and not review.is_symlink():
        # the person's notes on the video (showtime review) are theirs, not scratch: keep review/notes/
        cands = [c for c in cands if c != review] + sorted(c for c in review.iterdir() if c.name != "notes")
    if kind == "job":
        # a render into a job (--job, -o) keeps its intermediates in <stem>.work/ (span clips: work/<span>.work/,
        # studio media: work/renders/<name>.work/). Renders since 0.4.0 tidy their own; older ones left the
        # silent video copy (as large as the final) and the WAV stems there
        works = sorted(target.glob("*.work")) + sorted(target.glob("work/*.work")) + sorted(target.glob("work/renders/*.work"))
        for w in works:
            if w.is_dir() and not w.is_symlink():
                cands += [w / "frames", w / "splice"]
                if LEVELS[level] >= LEVELS["default"]:
                    cands += [w / "audio", w / "diagnostics"]
                    cands += [w / ("%s.%s" % (n, e)) for n in ("video", "mux") for e in ("mp4", "mov", "webm")]
                if LEVELS[level] >= LEVELS["all"]:
                    cands = [c for c in cands if not str(c).startswith(str(w))] + [w]
    seen = set()
    for c in cands:
        if c in seen or not c.exists() or c.is_symlink():
            continue
        try:
            c.resolve().relative_to(target)
        except ValueError:
            continue  # escapes the target (should not happen without symlinks)
        seen.add(c)
        b, n = _size(c)
        items.append({"path": str(c), "rel": c.relative_to(target).as_posix(), "bytes": b, "files": n,
                      "what": what.get(c, "")})
    kept = []
    work = target / "work"
    if work.is_dir():
        planned = {Path(i["path"]) for i in items}
        for child in sorted(work.iterdir()):
            if child not in planned:
                kept.append(str(child.relative_to(target)))
    return {"target": str(target), "kind": kind, "level": level, "items": items,
            "bytes": sum(i["bytes"] for i in items), "files": sum(i["files"] for i in items), "kept": kept}


def execute(p: Dict[str, Any]) -> int:
    freed = 0
    target = Path(p["target"])
    for it in p["items"]:
        path = Path(it["path"])
        if path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
        freed += it["bytes"]
    work = target / "work"
    if work.is_dir() and not any(work.iterdir()):
        work.rmdir()
    return freed


def describe(p: Dict[str, Any]) -> List[str]:
    lines = ["clean %s (%s, level %s)" % (p["target"], p["kind"], p["level"])]
    if not p["items"]:
        lines.append("  nothing to remove")
    for it in p["items"]:
        lines.append("  remove  %-28s %9s  (%d files)%s" % (it["rel"], human_size(it["bytes"]), it["files"],
                                                          "  " + it["what"] if it.get("what") else ""))
    if p["kept"]:
        lines.append("  keep    " + ", ".join(p["kept"][:12]) + (" ..." if len(p["kept"]) > 12 else ""))
    lines.append("  total   %s in %d files" % (human_size(p["bytes"]), p["files"]))
    return lines

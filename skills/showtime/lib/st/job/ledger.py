"""The job ledger: job.json (for tools) + SHOWTIME.md (for people and a resumed session).

A job is one folder `showtime-out/<slug>-<timestamp>/`. job.json records what
ran and what was learned: versions, OS/arch, ffmpeg and browser, stage timings,
cache hits, warnings, what was verified and what was only assumed, open
questions, and the next command. SHOWTIME.md is regenerated from it at every
update; anything written under its "## Notes" heading is kept.

Stdlib only.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from .. import __version__
from .. import platform as plat
from ..common import ShowtimeError, home, log, read_json, skill_dir, slugify, timestamp, write_json

PathLike = Union[str, "os.PathLike[str]"]

SCHEMA = 1
MODES = ("quick", "studio")
STATUSES = ("started", "done", "failed", "skipped")
NOTES_HEAD = "## Notes"
REQUEST_MAX = 4000                       # characters of the request kept verbatim (job.json "request")
RENDER_KINDS = ("full", "preview", "partial")


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _parse_iso(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


# ------------------------------------------------------------------ environment

def _git_sha(start: Path) -> Optional[str]:
    """HEAD commit of the checkout containing `start`, read from .git without running git."""
    for d in [start] + list(start.parents):
        g = d / ".git"
        if g.is_file():  # worktree: "gitdir: <path>"
            m = re.match(r"gitdir:\s*(.+)", g.read_text(encoding="utf-8", errors="replace").strip())
            if not m:
                return None
            g = (d / m.group(1).strip()).resolve()
        if g.is_dir():
            head = (g / "HEAD").read_text(encoding="utf-8", errors="replace").strip() if (g / "HEAD").is_file() else ""
            if head.startswith("ref:"):
                ref = head[4:].strip()
                rp = g / ref
                if rp.is_file():
                    return rp.read_text(encoding="utf-8").strip()[:12]
                common = g
                cd = g / "commondir"
                if cd.is_file():
                    common = (g / cd.read_text(encoding="utf-8").strip()).resolve()
                    if (common / ref).is_file():
                        return (common / ref).read_text(encoding="utf-8").strip()[:12]
                packed = common / "packed-refs"
                if packed.is_file():
                    for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
                        if line.endswith(" " + ref):
                            return line.split()[0][:12]
                return None
            return head[:12] or None
    return None


def _browser_version(path: str) -> Optional[str]:
    p = Path(path)
    try:
        if plat.IS_MAC:
            for parent in p.parents:
                if parent.suffix == ".app":
                    info = parent / "Contents" / "Info.plist"
                    if info.is_file():
                        with info.open("rb") as fh:
                            return str(plistlib.load(fh).get("CFBundleShortVersionString") or "") or None
            return None
        if plat.IS_WINDOWS:
            vers = [d.name for d in p.parent.iterdir() if d.is_dir() and re.match(r"^\d+\.\d+\.\d+\.\d+$", d.name)]
            return sorted(vers, key=lambda v: [int(x) for x in v.split(".")])[-1] if vers else None
        cp = subprocess.run([str(p), "--version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=5, encoding="utf-8", errors="replace")
        m = re.search(r"(\d+\.\d+\.\d+\.\d+)", cp.stdout or "")
        return m.group(1) if m else None
    except (OSError, ValueError, subprocess.SubprocessError, plistlib.InvalidFileException):
        return None


def env_snapshot() -> Dict[str, Any]:
    """Versions and platform facts recorded in job.json (cheap: no browser launch)."""
    state = read_json(home() / "state.json", {}) or {}
    s = plat.summary()
    env: Dict[str, Any] = {
        "showtime": __version__, "skill": str(skill_dir()), "git": _git_sha(skill_dir()),
        "os": s["os"], "arch": s["arch"], "platform": s["key"], "python": s["python"], "cpus": s["cpus"],
        "setup_tier": (state.get("installed") or {}).get("tier"),
        "extras": (state.get("installed") or {}).get("extras"),
    }
    node = (state.get("node") or {}).get("node")
    if not node:
        exe = plat.which("node")
        if exe:
            try:
                cp = subprocess.run([exe, "--version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5,
                                    encoding="utf-8", errors="replace")
                node = (cp.stdout or "").strip().lstrip("v") or None
            except (OSError, subprocess.SubprocessError):
                node = None
    env["node"] = node
    try:
        from .. import ff
        r = ff.resolve()
        env["ffmpeg"] = {"path": r.ffmpeg, "version": r.version, "source": r.source}
    except Exception as e:  # noqa: BLE001 - a missing ffmpeg is itself a fact worth recording
        env["ffmpeg"] = {"error": str(e).splitlines()[0]}
    b = plat.find_chrome(home() / "browsers")
    if b:
        env["browser"] = {"kind": b["kind"], "path": b["path"], "version": _browser_version(b["path"])}
    else:
        env["browser"] = None
    return env


# ------------------------------------------------------------------ locating jobs

JOB_NAME_RE = re.compile(r"^(?P<slug>.+?)-(?P<ts>\d{8}-\d{6})(?:-(?P<n>\d+))?$")


def is_job(d: Path) -> bool:
    return d.is_dir() and ((d / "job.json").is_file() or (d / "render.json").is_file())


def out_roots(base: Optional[PathLike] = None) -> List[Path]:
    roots: List[Path] = []
    cands = [Path(base)] if base else []
    if os.environ.get("SHOWTIME_OUT"):
        cands.append(Path(os.environ["SHOWTIME_OUT"]))
    cands.append(Path.cwd())
    for c in cands:
        c = c.expanduser().resolve()
        r = c if c.name == "showtime-out" else c / "showtime-out"
        if r.is_dir() and r not in roots:
            roots.append(r)
    # run from inside a job (or deeper): the showtime-out/ folder above the current folder
    for up in list(Path.cwd().resolve().parents)[:8]:
        if up.name == "showtime-out":
            if up not in roots:
                roots.append(up)
            break
    return roots


def _job_mtime(d: Path) -> float:
    ts = [p.stat().st_mtime for p in (d / "job.json", d / "render.json", d / "SHOWTIME.md") if p.is_file()]
    return max(ts) if ts else d.stat().st_mtime


def list_jobs(base: Optional[PathLike] = None) -> List[Path]:
    jobs: List[Path] = []
    for r in out_roots(base):
        for d in r.iterdir():
            if is_job(d):
                jobs.append(d)
    jobs.sort(key=_job_mtime, reverse=True)
    return jobs


def latest(base: Optional[PathLike] = None) -> Optional[Path]:
    js = list_jobs(base)
    return js[0] if js else None


def slug_of(name: str) -> str:
    """`launch-20260926-101500` / `launch-20260926-101500-2` -> `launch` (other names unchanged)."""
    m = JOB_NAME_RE.match(name)
    return m.group("slug") if m else name


def _created_key(d: Path) -> Tuple[str, int, float]:
    """Newest-created first sort key: the folder's timestamp, its -N suffix, then mtime."""
    m = JOB_NAME_RE.match(d.name)
    if m:
        return (m.group("ts"), int(m.group("n") or 1), _job_mtime(d))
    return ("", 0, _job_mtime(d))


def enclosing_job(path: PathLike, levels: int = 4) -> Optional[Path]:
    """The job folder that contains `path` (the folder itself, or up to `levels` parents).

    A folder counts when it has job.json, or render.json and sits directly in showtime-out/.
    The walk stops at a showtime-out/ folder, so a project next to showtime-out/ is never a job.
    """
    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except OSError:
        return None
    if p.is_file() or not p.exists():
        p = p.parent
    for d in [p] + list(p.parents)[:levels]:
        if d.name == "showtime-out":
            return None
        if (d / "job.json").is_file() or ((d / "render.json").is_file() and d.parent.name == "showtime-out"):
            return d
    return None


def find_jobs(name: str, base: Optional[PathLike] = None) -> Tuple[List[Path], str]:
    """Jobs matching a bare name, newest first, and how they matched ("exact", "slug", "prefix" or "")."""
    names = [name]
    sl = slugify(name, default="")
    if sl and sl != name:
        names.append(sl)
    roots = out_roots(base)
    for n in names:
        for r in roots:
            d = r / n
            if d.is_dir() and (is_job(d) or (d / "studio").is_dir()):
                return [d], "exact"
    for n in names:
        hits = [d for r in roots for d in r.iterdir() if d.is_dir() and is_job(d) and slug_of(d.name) == n]
        if hits:
            return sorted(hits, key=_created_key, reverse=True), "slug"
    for n in names:
        hits = [d for r in roots for d in r.iterdir() if d.is_dir() and is_job(d) and d.name.startswith(n)]
        if hits:
            return sorted(hits, key=_created_key, reverse=True), "prefix"
    return [], ""


def resolve_name(name: str, base: Optional[PathLike] = None) -> Optional[Path]:
    """A bare job name or slug -> the newest matching job folder (None when nothing matches).

    `launch` matches `launch-<timestamp>` folders (newest wins); a prefix such as `lau` works when it
    names one slug only; a prefix shared by several slugs is an error that lists them.
    """
    hits, how = find_jobs(name, base)
    if not hits:
        return None
    if how == "prefix":
        slugs = sorted({slug_of(h.name) for h in hits})
        if len(slugs) > 1:
            newest = [next(h for h in hits if slug_of(h.name) == sl).name for sl in slugs]
            raise ShowtimeError("%r matches more than one job: %s" % (name, ", ".join(newest[:8])),
                                why="a partial name must point at one job",
                                hint="pass the full name or the folder, e.g. %s" % hits[0])
    return hits[0]


def resolve(arg: Optional[PathLike] = None, base: Optional[PathLike] = None) -> Path:
    """A job folder from a path (the folder, a file or folder inside it) or a name/slug.

    No argument: the job the current folder is inside, else the newest job under showtime-out/.
    A bare slug resolves to the newest `showtime-out/<slug>-<timestamp>/`.
    """
    if arg is None or str(arg) == "":
        here = enclosing_job(Path.cwd())
        if here is not None:
            return here
        j = latest(base)
        if j is None:
            raise ShowtimeError("no showtime job found under %s" % (", ".join(str(r) for r in out_roots(base)) or
                                                                    str(Path.cwd() / "showtime-out")),
                                hint="start one: showtime job init <slug>, or pass the job folder")
        return j
    raw = str(arg)
    p = Path(raw).expanduser()
    bare = not any(sep in raw for sep in ("/", "\\")) and not raw.startswith((".", "~"))
    if p.exists():
        p = p.resolve()
        if bare and not is_job(p) and enclosing_job(p) is None:
            j = resolve_name(raw, base)  # a folder named like the job (e.g. the project) is not the job
            if j is not None:
                return j
        if p.is_dir() and is_job(p):
            return p
        if p.is_dir() and (p.name == "showtime-out" or (p / "showtime-out").is_dir()):
            j = latest(p)
            if j:
                return j
        j = enclosing_job(p)
        if j is not None:
            return j
        if p.is_dir() and p.parent.name == "showtime-out" and (p / "studio").is_dir():
            return p  # a studio-only folder from an older release
        raise ShowtimeError("%s is not a showtime job folder (no job.json or render.json here or above it)" % p,
                            hint="job folders live in showtime-out/; create one with: showtime job init <slug>")
    if not bare:
        raise ShowtimeError("not found: %s" % p, hint="pass an existing job folder, or a job name (showtime job list)")
    j = resolve_name(raw, base)
    if j is None:
        raise ShowtimeError("no job named %r under %s" % (raw, ", ".join(str(r) for r in out_roots(base)) or
                                                          str(Path.cwd() / "showtime-out")),
                            hint="list jobs with: showtime job list (or create it: showtime job init %s)" % raw)
    return j


# ------------------------------------------------------------------ latest outputs

OUTPUT_KINDS = ("final", "preview", "edl", "poster", "share", "credits", "captions", "animatic")
# Kinds whose files live under <job>/studio/: a render there is a board asset (animatic), never the
# job's final or preview, so `showtime qa <job>` keeps checking the real video.
STUDIO_DIR = "studio"
VIDEO_EXTS = (".mp4", ".mov", ".webm", ".m4v", ".mkv")
_KIND_RE = re.compile(r"^(%s)=(.+)$" % "|".join(OUTPUT_KINDS), re.S)


def infer_kind(path: PathLike) -> Optional[str]:
    """Which latest-pointer a produced file updates (None for files that are not tracked)."""
    p = Path(path)
    name, suf = p.name.lower(), p.suffix.lower()
    if suf in VIDEO_EXTS:
        return "preview" if name.startswith(("preview", "draft")) else "final"
    if suf in (".jpg", ".jpeg", ".png", ".webp") and "poster" in name:
        return "poster"
    if suf in (".srt", ".vtt", ".ass"):
        return "captions"
    if suf == ".txt" and "credits" in name:
        return "credits"
    if suf in (".txt", ".md") and name.startswith("share"):
        return "share"
    if suf == ".json" and "edl" in name and not name.endswith(".report.json"):
        return "edl"
    return None


def parse_output(spec: str) -> Tuple[Optional[str], str]:
    """`final=path` -> ("final", "path"); a bare path -> (inferred kind or None, path)."""
    m = _KIND_RE.match(spec.strip())
    if m:
        return m.group(1), m.group(2).strip()
    return infer_kind(spec), spec


def _secs(x: Any) -> str:
    """12.0 -> "12", 2.5 -> "2.5" (seconds in a ledger line)."""
    return ("%.2f" % float(x)).rstrip("0").rstrip(".")


def _mtime_iso(p: Path) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(p.stat().st_mtime))


# Fallback file patterns (newest wins) for folders whose ledger has no pointer yet.
_FALLBACK = {
    "final": ("final*.mp4", "final*.mov", "final*.webm"),
    "preview": ("preview*.mp4", "draft*.mp4", "preview*.mov", "preview*.webm"),
    "edl": ("edl*.json", "edit/edl*.json"),
    "poster": ("poster*.jpg", "*.poster.jpg", "poster*.png"),
    "share": ("share*.txt",),
    "credits": ("credits*.txt", "CREDITS*.txt", "*.credits.txt"),
    "captions": ("*.srt", "*.vtt"),
    "animatic": ("studio/media/animatic/*.mp4", "studio/media/animatic/*.webm"),
}


def in_studio(job: Path, path: PathLike) -> bool:
    """True when `path` sits under <job>/studio/ (board media: animatics, frames)."""
    try:
        Path(path).expanduser().resolve().relative_to((job / STUDIO_DIR).resolve())
        return True
    except (ValueError, OSError):
        return False


LATEST_EXTS = (".mp4", ".m4v")
SPAN_PREFIX = "span-"


def is_span_report(r: Any) -> bool:
    """A render.json of a span clip (`render --from/--to` that was not spliced into a full final): the report
    says kind "span" (0.3.0), or its range starts after 0 (before 0.3.0 a span was written as final-N.mp4)."""
    if not isinstance(r, dict):
        return False
    if r.get("span") or r.get("kind") == "span" or r.get("deliverable") is False:
        return True
    rng = r.get("range")
    try:
        return isinstance(rng, list) and float(rng[0]) > 1e-6
    except (TypeError, ValueError, IndexError):
        return False


def is_span_video(video: PathLike) -> bool:
    """True for a span clip: named span-*, or its render report says it is one. Never a job's deliverable."""
    v = Path(video)
    if v.name.lower().startswith(SPAN_PREFIX):
        return True
    for rj in (v.parent / (v.stem + ".work") / "render.json", v.parent / "render.json"):
        r = read_json(rj, None) if rj.is_file() else None
        if isinstance(r, dict) and r.get("output") and Path(str(r["output"])).name == v.name:
            return is_span_report(r)
    return False
_LATEST_NAME = {"final": ("final",), "preview": ("preview", "draft", "final")}


def variant_reason(job: Path, kind: Optional[str], path: PathLike, data: Optional[Dict[str, Any]] = None
                   ) -> Optional[str]:
    """Why a video a tool produced in the job is logged as a variant instead of becoming the latest
    final/preview (None when it does become it). Rule for tool-recorded renders: an .mp4 whose name
    starts with final (preview: preview/draft/final), or a derived copy of the current latest one
    (launch.poster.mp4 of launch.mp4). An alpha overlay (.webm/.mov), a bumper.mp4 or a second
    aspect named shorts-9x16.mp4 stays out, so `showtime qa <job>` keeps checking the main video.
    `showtime job note --output final=<file>` (without --auto) sets any file explicitly."""
    if kind not in ("final", "preview"):
        return None
    p = Path(path)
    name = p.name.lower()
    if p.suffix.lower() not in LATEST_EXTS:
        return "a %s file (an overlay or alpha master), not an .mp4" % p.suffix.lower()
    if name.startswith(_LATEST_NAME[kind]):
        return None
    try:
        cur = latest_output(job, kind, data)
    except Exception:  # noqa: BLE001
        cur = None
    if cur is not None and name.startswith(cur.stem.lower() + "."):
        return None
    return "its name does not start with %s" % "/".join(_LATEST_NAME[kind])


def role_kind(job: Path, kind: Optional[str], path: PathLike, auto: bool = False,
              data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """The pointer a produced file really updates: a final/preview video under <job>/studio/ is the
    job's animatic (a studio board render), so it never replaces the latest final or preview.
    auto (a tool recorded it): a variant (see variant_reason) updates no pointer."""
    if kind in ("final", "preview") and in_studio(job, path):
        return "animatic"
    if auto and variant_reason(job, kind, path, data):
        return None
    return kind


def latest_output(job: Path, kind: str, data: Optional[Dict[str, Any]] = None) -> Optional[Path]:
    """The current file of one kind: the ledger pointer when it exists, else the newest matching file."""
    if kind not in OUTPUT_KINDS:
        raise ValueError("unknown output kind %r" % kind)
    if data is None:
        try:
            data = load(job)
        except ShowtimeError:
            data = {}
    outs = data.get("outputs") if isinstance(data.get("outputs"), dict) else {}
    v = outs.get(kind)
    if v:
        p = Path(v)
        if not p.is_absolute():
            p = job / p
        if p.is_file() and not (kind in ("final", "preview") and in_studio(job, p)):
            return p
    cands: List[Path] = []
    for pat in _FALLBACK[kind]:
        for c in job.glob(pat):
            if not c.is_file() or c.name.endswith(".report.json"):
                continue
            if kind == "final" and c.name.lower().startswith(("preview", "draft")):
                continue
            if kind == "credits" and not c.name.lower().endswith(".txt"):
                continue
            # a span clip (render --from/--to) is only a few seconds: never the job's final or preview
            if kind in ("final", "preview") and is_span_video(c):
                continue
            cands.append(c)
    if kind in ("final", "preview"):
        for rj in [job / "render.json"] + sorted(job.glob("*.work/render.json")):
            r = read_json(rj, None) if rj.is_file() else None
            if isinstance(r, dict) and r.get("output") and Path(r["output"]).is_file() \
                    and bool(r.get("preview")) == (kind == "preview") and not is_span_report(r):
                cands.append(Path(r["output"]))
    if not cands:
        return None
    return max(set(cands), key=lambda c: c.stat().st_mtime)


def latest_video(job: Path, data: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Path], Optional[str]]:
    """(video, kind): the latest final, else the latest preview."""
    for kind in ("final", "preview"):
        v = latest_output(job, kind, data)
        if v is not None:
            return v, kind
    return None, None


def outputs_view(job: Path, data: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """Every kind with a current file (pointer or fallback), as absolute paths."""
    out: Dict[str, str] = {}
    for k in OUTPUT_KINDS:
        p = latest_output(job, k, data)
        if p is not None:
            out[k] = str(p)
    return out


def media_arg(arg: Optional[PathLike], kind: str = "video", *, say: Any = None,
              base: Optional[PathLike] = None) -> Tuple[Path, Optional[Path], bool]:
    """Resolve a command's <video>/<edl> argument: (file, job or None, came_from_pointer).

    A file is used as given (with a note when its job has a newer file of the same kind).
    A job folder, a slug, or nothing (the job the current folder is in, else the newest job)
    gives the job's latest pointer, and `say` is called with "using <path> (latest <kind>)".
    kind: "video" (final, else preview) or one of OUTPUT_KINDS.
    """
    if arg is not None and str(arg) != "":
        p = Path(str(arg)).expanduser()
        if p.is_file():
            p = p.resolve()
            job = enclosing_job(p)
            if job is not None and say is not None:
                k = infer_kind(p) if kind == "video" else kind
                if k in OUTPUT_KINDS:
                    cur = latest_output(job, k)
                    if cur is not None and cur.resolve() != p and cur.stat().st_mtime > p.stat().st_mtime:
                        say("note: %s is not the latest %s of %s; the latest is %s (pass the job folder to use it)"
                            % (p.name, k, job.name, cur))
            return p, job, False
        if p.suffix.lower() in VIDEO_EXTS + (".json",) and not p.exists():
            what = "video" if kind in ("video", "final", "preview") else kind
            raise ShowtimeError("%s not found: %s" % (what, p.resolve()),
                                hint="pass the rendered file (e.g. showtime-out/<job>/final.mp4), or the job folder or name "
                                     "to use its latest %s" % what)
    job = resolve(arg, base)
    data = load(job) if (job / "job.json").is_file() or (job / "render.json").is_file() else {}
    if kind == "video":
        f, k = latest_video(job, data)
    else:
        f, k = latest_output(job, kind, data), kind
    if f is None:
        what = "video (final or preview)" if kind == "video" else kind
        raise ShowtimeError("job %s has no %s yet" % (job.name, what),
                            hint="render first, or pass the file itself")
    if say is not None:
        say("using %s (latest %s)" % (f, k))
    return f, job, True


def record_outputs(target: PathLike, outputs: Sequence[str], *, stage: Optional[str] = None,
                   seconds: Optional[float] = None, event: Optional[str] = None,
                   baked: Optional[Dict[str, float]] = None, project: Optional[PathLike] = None,
                   auto: bool = True, render: Optional[Dict[str, Any]] = None) -> Optional[Path]:
    """Set latest pointers for files produced inside a job (no-op outside one). Returns the job.
    auto: a variant video (variant_reason) is logged without becoming the latest final/preview."""
    first = Path(parse_output(outputs[0])[1]) if outputs else Path(target)
    job = enclosing_job(target) or enclosing_job(first)
    if job is None:
        return None
    data = note(job, stage=stage, seconds=seconds, outputs=outputs, event=event, baked=baked, project=project, auto=auto,
                render=render)
    for o in data.get("_recorded") or []:
        if o.get("variant"):
            log("job %s: %s logged as a variant, not the latest %s (%s). To make it the latest: showtime job note %s "
                "--output %s=%s" % (job.name, Path(o["path"]).name, o["variant"], o["why"], job.name, o["variant"], o["path"]))
    return job


def recorded_as(data: Dict[str, Any], path: PathLike) -> Optional[Dict[str, Any]]:
    """The output_log entry `note` wrote for `path` in this call (kind, or variant + why)."""
    for o in reversed(data.get("_recorded") or []):
        if Path(str(o.get("path"))).name == Path(str(path)).name:
            return o
    return None


# ------------------------------------------------------------------ the project a job renders

_NOT_PROJECT = ("work", "review", "studio", "exports", "edit", "frames")


def detect_project(job: Path) -> Optional[Path]:
    """A project folder inside the job (e.g. `showtime new <template> <job>/project`): the newest
    subfolder with a showtime.json. None when there is none."""
    try:
        cands = [d for d in job.iterdir() if d.is_dir() and d.name not in _NOT_PROJECT and not d.name.endswith(".work")
                 and (d / "showtime.json").is_file()]
    except OSError:
        return None
    if not cands:
        return None
    return max(cands, key=lambda d: (d / "showtime.json").stat().st_mtime)


def _render_project(video: Path) -> Optional[Path]:
    """The project a rendered video came from (its render.json), when that project still exists."""
    for rj in (video.with_suffix(".work") / "render.json", video.parent / (video.stem + ".work") / "render.json",
               video.parent / "render.json"):
        r = read_json(rj, None) if rj.is_file() else None
        if isinstance(r, dict) and r.get("project") and \
                (not r.get("output") or Path(str(r["output"])).name == video.name):
            p = Path(str(r["project"]))
            if (p / "showtime.json").is_file() or (p / "index.html").is_file():
                return p
    return None


def project_of(job: Path, data: Dict[str, Any]) -> Optional[str]:
    """The job's project folder: job.json "project" / pointers.project, else one found in the job."""
    p = data.get("project") or (data.get("pointers") or {}).get("project")
    if p:
        return str(p)
    d = detect_project(job)
    return str(d) if d else None


def _set_project(data: Dict[str, Any], proj: PathLike) -> bool:
    ps = str(Path(proj).expanduser().resolve())
    changed = data.get("project") != ps or (data.get("pointers") or {}).get("project") != ps
    data["project"] = ps
    data.setdefault("pointers", {})["project"] = ps
    return changed


def attach_project(project: PathLike, job: Optional[PathLike] = None) -> Optional[Path]:
    """Record `project` as the job's project (pointers.project). `job` defaults to the job that contains
    the project folder; a no-op (None) when there is no job. For `showtime new <t> <dir> [--job J]`."""
    j = resolve(job) if job else enclosing_job(project)
    if j is None:
        return None
    if not job:
        # Scratch projects under <job>/crew/ (a crew member's style frames or scene fragment) or
        # <job>/studio/ (board compositions) are never the job's video; only an explicit --job records them.
        try:
            first = Path(project).resolve().relative_to(Path(j).resolve()).parts[:1]
        except ValueError:
            first = ()
        if first and first[0] in ("crew", "studio"):
            return None
    note(j, project=project, event="project %s" % Path(project).name)
    return j


# ------------------------------------------------------------------ git ignore

def in_git_repo(d: Path) -> bool:
    for p in [d] + list(d.parents):
        if (p / ".git").exists():
            return True
    return False


def ensure_self_ignored(root: Path) -> bool:
    """Inside a git repo, make showtime-out/ ignore itself (never edits the repo's own .gitignore)."""
    gi = root / ".gitignore"
    if gi.exists() or not in_git_repo(root.parent):
        return False
    gi.write_text("# showtime output (renders, frames, caches): never commit\n*\n", encoding="utf-8")
    return True


# ------------------------------------------------------------------ load / save

def new_data(slug: str, mode: str, goal: Optional[str], job_dir: Path, project: Optional[Path]) -> Dict[str, Any]:
    return {
        "schema": SCHEMA, "slug": slug, "mode": mode, "goal": goal or "", "request": "", "dir": str(job_dir),
        "project": str(project) if project else None, "created": now_iso(), "updated": now_iso(),
        "command": " ".join(sys.argv[1:])[:300], "env": env_snapshot(),
        "stage": None, "stages": [], "verified": [], "assumed": [], "questions": [], "next": None,
        "platform": None, "pointers": {}, "outputs": {}, "output_log": [], "warnings": [],
        "cache": {"hits": 0, "misses": 0}, "qa": None, "renders": [],
        "history": [{"at": now_iso(), "event": "job created (%s mode)" % mode}],
    }


def init(slug: str, mode: str = "quick", goal: Optional[str] = None, base: Optional[PathLike] = None,
         project: Optional[PathLike] = None, assumed: Sequence[str] = (), questions: Sequence[str] = (),
         next_cmd: Optional[str] = None, platform: Optional[str] = None,
         request: Optional[str] = None, review_mode: Optional[str] = None) -> Tuple[Path, Dict[str, Any]]:
    if mode not in MODES:
        raise ShowtimeError("unknown mode %r" % mode, hint="use quick or studio (and lean or quality for the review)")
    from .. import review_mode as rmode
    if review_mode is not None and rmode.normalize(review_mode) is None:
        raise ShowtimeError("unknown review mode %r" % review_mode, hint="use quality (the default) or lean")
    rv, rv_src = rmode.resolve(review_mode)
    root = Path(base).expanduser().resolve() if base else Path(os.environ.get("SHOWTIME_OUT") or Path.cwd()).resolve()
    if root.name != "showtime-out":
        root = root / "showtime-out"
    root.mkdir(parents=True, exist_ok=True)
    ignored = ensure_self_ignored(root)
    stem = "%s-%s" % (slugify(slug), timestamp())
    d = root / stem
    n = 2
    while d.exists():  # never reuse an existing folder
        d = root / ("%s-%d" % (stem, n))
        n += 1
    d.mkdir(parents=False)
    (d / "work" / "logs").mkdir(parents=True)
    proj = Path(project).expanduser().resolve() if project else None
    data = new_data(slugify(slug), mode, goal, d, proj)
    data["review_mode"], data["review_mode_source"] = rv, rv_src
    data["history"][-1]["event"] = "job created (%s mode, %s review from %s)" % (mode, rv, rmode.SOURCES.get(rv_src, rv_src))
    if request:
        data["request"] = str(request).strip()[:REQUEST_MAX]
        if not goal:   # `--request` alone is enough: the goal line is its first 200 characters on one line
            data["goal"] = " ".join(data["request"].split())[:200]
    for a in assumed:
        _add_item(data["assumed"], a, "init")
    for q in questions:
        data["questions"].append({"text": q, "at": now_iso(), "answer": None})
    if next_cmd:
        data["next"] = next_cmd
    if platform:
        data["platform"] = platform.lower().strip()
    if proj:
        data["pointers"]["project"] = str(proj)
    if mode == "studio":
        data["pointers"].setdefault("studio", str(d / "studio"))
    data["gitignore_written"] = ignored
    save(d, data)
    return d, data


def adopt(job: Path) -> Dict[str, Any]:
    """A ledger for a folder that `showtime render` made before any `job init`."""
    rj = read_json(job / "render.json", {}) or {}
    slug = re.sub(r"-\d{8}-\d{6}(-\d+)?$", "", job.name) or job.name
    proj = Path(rj["project"]) if rj.get("project") else None
    data = new_data(slug, "quick", "", job, proj)
    data["history"] = [{"at": now_iso(), "event": "ledger adopted from render.json"}]
    if rj:
        tm = rj.get("timings") or {}
        data["stages"].append({"name": "render", "status": "done" if rj.get("ok", True) else "failed",
                               "seconds": round((tm.get("total") or 0) / 1000.0, 1) or None,
                               "ended": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime((job / "render.json").stat().st_mtime))})
        data["stage"] = "render"
        if rj.get("output") and is_span_report(rj):
            # a span clip (render --from/--to): logged, never the latest final
            data["output_log"].append({"path": rj["output"], "at": data["stages"][-1]["ended"], "stage": "render",
                                       "kind": None, "span": rj.get("span") or rj.get("range")})
        elif rj.get("output"):
            data["output_log"].append({"path": rj["output"], "at": data["stages"][-1]["ended"], "stage": "render",
                                       "kind": "preview" if rj.get("preview") else "final"})
            data["outputs"]["preview" if rj.get("preview") else "final"] = rj["output"]
            pst = (rj.get("poster") or {}).get("file") if isinstance(rj.get("poster"), dict) else None
            if pst:
                data["outputs"]["poster"] = pst
            if rj.get("credits"):
                data["outputs"]["credits"] = rj["credits"]
        for w in rj.get("warnings") or []:
            data["warnings"].append(str(w))
        if rj.get("browser"):
            data["env"]["render_browser"] = rj["browser"]
        if proj:
            data["pointers"]["project"] = str(proj)
    qas = sorted((job / "work" / "qa").glob("*/qa.json"), key=lambda p: p.stat().st_mtime) if (job / "work" / "qa").is_dir() else []
    if qas:
        q = read_json(qas[-1], {}) or {}
        s = q.get("summary") or {}
        data["qa"] = {"verdict": q.get("verdict"), "report": str(qas[-1]), "at": q.get("created"), "video": q.get("video"),
                      "fail": s.get("fail"), "warn": s.get("warn")}
        data["pointers"]["qa"] = str(qas[-1])
    return data


_DEFAULTS: Dict[str, Any] = {
    "schema": SCHEMA, "mode": "quick", "goal": "", "project": None, "stage": None, "stages": [], "verified": [],
    "assumed": [], "questions": [], "next": None, "platform": None, "pointers": {}, "outputs": {}, "output_log": [],
    "warnings": [], "cache": {"hits": 0, "misses": 0}, "qa": None, "history": [], "env": {},
    "request": "", "renders": [],
}


def normalize(data: Dict[str, Any], job: Optional[Path] = None) -> Dict[str, Any]:
    """Fill missing keys (ledgers written by older releases or by hand) and migrate the outputs list.

    Older ledgers kept "outputs" as a list of {path, at, stage}; it is now the history "output_log"
    and "outputs" maps each kind (final, preview, edl, poster, share, credits, captions) to the latest file.
    """
    for k, v in _DEFAULTS.items():
        if k not in data or data[k] is None and isinstance(v, (list, dict)):
            data[k] = json.loads(json.dumps(v))
    if job is not None:
        data.setdefault("slug", slug_of(job.name))
        data.setdefault("dir", str(job))
    outs = data.get("outputs")
    if isinstance(outs, list):
        data["output_log"] = list(data.get("output_log") or []) + [o for o in outs if isinstance(o, dict)]
        data["outputs"] = {}
        for o in data["output_log"]:
            k = o.get("kind") or infer_kind(o.get("path", ""))
            if k and o.get("path"):
                data["outputs"][k] = o["path"]
    elif not isinstance(outs, dict):
        data["outputs"] = {}
    return data


def load(job: Path) -> Dict[str, Any]:
    p = job / "job.json"
    if p.is_file():
        data = read_json(p, None)
        if not isinstance(data, dict):
            raise ShowtimeError("%s is not a job ledger" % p)
        data = normalize(data, job)
        if not data.get("project"):
            ptr = (data.get("pointers") or {}).get("project")
            found = Path(ptr) if ptr else detect_project(job)
            if found is not None:
                _set_project(data, found)  # kept in memory; the next save records it
        return data
    if (job / "render.json").is_file():
        return adopt(job)
    raise ShowtimeError("%s has no job.json" % job, hint="showtime job init <slug>")


def save(job: Path, data: Dict[str, Any]) -> None:
    data["updated"] = now_iso()
    data["history"] = data.get("history", [])[-200:]
    write_json(job / "job.json", data)
    md = job / "SHOWTIME.md"
    notes = ""
    if md.is_file():
        txt = md.read_text(encoding="utf-8", errors="replace")
        i = txt.find("\n" + NOTES_HEAD)
        if i >= 0:
            notes = txt[i + 1 + len(NOTES_HEAD):].strip("\n")
    md.write_text(render_md(job, data, notes), encoding="utf-8", newline="\n")


def _add_item(lst: List[Dict[str, Any]], text: str, stage: Optional[str]) -> bool:
    t = " ".join(str(text).split())
    if not t or any(x["text"].lower() == t.lower() for x in lst):
        return False
    lst.append({"text": t, "at": now_iso(), "stage": stage})
    return True


# ------------------------------------------------------------------ updates

def note(job: Path, *, stage: Optional[str] = None, status: Optional[str] = None, seconds: Optional[float] = None,
         verified: Sequence[str] = (), assumed: Sequence[str] = (), questions: Sequence[str] = (),
         answers: Sequence[str] = (), next_cmd: Optional[str] = None, pointers: Sequence[str] = (),
         warnings: Sequence[str] = (), goal: Optional[str] = None, outputs: Sequence[str] = (),
         cache_hits: int = 0, cache_misses: int = 0, event: Optional[str] = None,
         mode: Optional[str] = None, platform: Optional[str] = None, project: Optional[PathLike] = None,
         baked: Optional[Dict[str, float]] = None, auto: bool = False,
         request: Optional[str] = None, render: Optional[Dict[str, Any]] = None,
         review_mode: Optional[str] = None) -> Dict[str, Any]:
    """Update the ledger. `outputs` entries are paths or KIND=PATH (KIND: final, preview, edl, poster,
    share, credits, captions, animatic); each is logged, and a known kind becomes that kind's latest
    pointer. A final/preview video under <job>/studio/ is recorded as the animatic instead.
    `project` sets the job's project (also inferred from a recorded render's render.json).
    `baked` maps video paths to the poster time baked into their frame 0.
    auto: the outputs come from a tool (render, edit render, captions --burn, deliver): a variant
    video (an alpha overlay, a bumper.mp4, see variant_reason) is logged but updates no pointer.
    request: the user's request as typed (kept verbatim in job.json "request"; the receipt quotes it).
    render: one render for the receipt, {"kind": full|preview|partial, "file": name, "seconds": s,
    "span": [from, to], "base": name}; appended to job.json "renders" (a span clip makes no output pointer; a
    partial render with a "base" was spliced into a copy of that full render, and its output entry says so).
    The returned data carries "_recorded" (not saved): what each output became."""
    data = load(job)
    if request is not None and str(request).strip():
        data["request"] = str(request).strip()[:REQUEST_MAX]
    if render:
        rk = str(render.get("kind") or "")
        if rk not in RENDER_KINDS:
            raise ShowtimeError("unknown render kind %r" % rk, hint="use one of: " + ", ".join(RENDER_KINDS))
        rec_r = {"kind": rk, "file": Path(str(render.get("file") or "")).name, "at": now_iso()}
        if render.get("seconds") is not None:
            rec_r["seconds"] = round(float(render["seconds"]), 1)
        if render.get("span"):
            rec_r["span"] = [round(float(x), 2) for x in list(render["span"])[:2]]
        if render.get("base"):
            if rk != "partial" or not rec_r.get("span"):
                raise ShowtimeError("a render base is only for a partial render with a span",
                                    hint="--render partial=FILE --render-span A-B --render-base FILE")
            rec_r["spliced_from"] = Path(str(render["base"])).name
        data["renders"] = (list(data.get("renders") or []) + [rec_r])[-200:]
    if project is not None and str(project) != "":
        _set_project(data, project)
    if platform is not None:
        data["platform"] = platform.lower().strip() or None
    cur = stage or data.get("stage")
    if goal is not None:
        data["goal"] = goal
    if mode:
        if mode not in MODES:
            raise ShowtimeError("unknown mode %r" % mode, hint="use quick or studio (and lean or quality for the review)")
        data["mode"] = mode
    if review_mode:
        from .. import review_mode as rmode
        rv = rmode.normalize(review_mode)
        if rv is None:
            raise ShowtimeError("unknown review mode %r" % review_mode, hint="use quality (the default) or lean")
        if data.get("review_mode") != rv:
            data["history"].append({"at": now_iso(), "event": "review mode %s -> %s" % (data.get("review_mode") or "default", rv)})
        data["review_mode"], data["review_mode_source"] = rv, "flag"
    if stage:
        st = status or "done"
        if st not in STATUSES:
            raise ShowtimeError("unknown status %r" % st, hint="use one of: " + ", ".join(STATUSES))
        rec = next((s for s in reversed(data["stages"]) if s["name"] == stage and s.get("status") == "started"), None)
        if rec is None or st == "started":
            rec = {"name": stage, "status": st}
            data["stages"].append(rec)
        rec["status"] = st
        if st == "started":
            rec["started"] = now_iso()
        else:
            rec["ended"] = now_iso()
            if seconds is None and rec.get("started"):
                a, b = _parse_iso(rec["started"]), _parse_iso(rec["ended"])
                if a is not None and b is not None:
                    seconds = b - a
        if seconds is not None:
            rec["seconds"] = round(float(seconds), 1)
        data["stage"] = stage
        data["history"].append({"at": now_iso(), "event": "stage %s %s" % (stage, st)})
    for v in verified:
        vt = " ".join(v.split()).lower()
        data["assumed"] = [a for a in data["assumed"] if a["text"].lower() != vt]
        _add_item(data["verified"], v, cur)
    for a in assumed:
        _add_item(data["assumed"], a, cur)
    for q in questions:
        if not any(x["text"].lower() == q.lower() for x in data["questions"]):
            data["questions"].append({"text": " ".join(q.split()), "at": now_iso(), "answer": None})
    open_q = [q for q in data["questions"] if not q.get("answer")]
    for ans in answers:
        m = re.match(r"^\s*(\d+)\s*[:=]\s*(.+)$", ans, re.S)
        if not m:
            raise ShowtimeError("--answer must look like N:answer (N = open question number, see showtime status)")
        i = int(m.group(1)) - 1
        if not (0 <= i < len(open_q)):
            raise ShowtimeError("there is no open question %s (open: %d)" % (m.group(1), len(open_q)))
        open_q[i]["answer"] = " ".join(m.group(2).split())
        open_q[i]["answered"] = now_iso()
    if next_cmd is not None:
        data["next"] = next_cmd or None
    elif stage or any(role_kind(job, parse_output(str(o))[0], parse_output(str(o))[1], auto, data) in ("final", "preview")
                      for o in outputs):
        # a hand-set "next" was for the job as it stood; a new stage or render supersedes it
        data["next"] = None
    for p in pointers:
        k, sep, v = p.partition("=")
        if not sep or not k.strip():
            raise ShowtimeError("--pointer must look like name=path (e.g. brief=studio/brief.md)")
        data["pointers"][k.strip()] = v.strip()
    for w in warnings:
        if w not in data["warnings"]:
            data["warnings"].append(w)
    recorded: List[Dict[str, Any]] = []
    for o in outputs:
        kind, raw = parse_output(str(o))
        rp = Path(raw).expanduser()
        if not rp.is_absolute():
            rp = Path.cwd() / rp
        op = str(rp.resolve()) if rp.exists() else raw
        why = variant_reason(job, kind, op, data) if auto and not in_studio(job, op) else None
        asked = kind
        kind = role_kind(job, kind, op, auto, data)
        entry = {"path": op, "at": now_iso(), "stage": cur, "kind": kind}
        if render and render.get("base") and render.get("span") and Path(op).name == Path(str(render.get("file"))).name:
            # a full final made by splicing a re-rendered span into a copy of an earlier final
            entry["spliced"] = "%s-%s from %s" % (_secs(render["span"][0]), _secs(render["span"][1]), Path(str(render["base"])).name)
        if why:
            entry["variant"] = asked
            entry["why"] = why
            data["history"].append({"at": now_iso(), "event": "%s logged as a variant, not the latest %s (%s)" % (
                Path(op).name, asked, why)})
        data["output_log"].append(entry)
        data["output_log"] = data["output_log"][-200:]
        recorded.append(entry)
        if kind:
            data["outputs"][kind] = op
        if kind in ("final", "preview") and project is None and rp.is_file():
            rproj = _render_project(rp)
            if rproj is not None and (not data.get("project") or not Path(str(data["project"])).exists()):
                _set_project(data, rproj)
    if baked:
        data.setdefault("baked", {}).update({str(k): round(float(v), 3) for k, v in baked.items()})
    if cache_hits or cache_misses:
        data["cache"]["hits"] = int(data["cache"].get("hits", 0)) + int(cache_hits)
        data["cache"]["misses"] = int(data["cache"].get("misses", 0)) + int(cache_misses)
    if event:
        data["history"].append({"at": now_iso(), "event": event})
    save(job, data)
    data["_recorded"] = recorded
    return data


def discard(job: Path, target: PathLike) -> Dict[str, Any]:
    """Take an unused render out of the job: the file (and its .work/ folder, poster, credits and edit
    report) moves to <job>/work/discarded/, and every pointer to it falls back to the newest remaining
    file of that kind. Caption files (final.srt, ...) stay: they usually belong to the job's cut, not
    to one render (discard them by naming them). Nothing is deleted."""
    import shutil
    data = load(job)
    p = Path(str(target)).expanduser()
    if not p.is_absolute():
        p = (job / p) if (job / p).exists() else (Path.cwd() / p)
    p = p.resolve()
    if not p.is_file():
        raise ShowtimeError("not found: %s" % p, hint="pass a file inside %s (showtime job show %s lists them)" % (job, job.name))
    try:
        p.relative_to(job.resolve())
    except ValueError:
        raise ShowtimeError("%s is not inside the job %s" % (p, job))
    dest_dir = job / "work" / "discarded"
    dest_dir.mkdir(parents=True, exist_ok=True)
    moved: List[str] = []
    stem = p.stem
    companions = [p]
    if p.suffix.lower() in VIDEO_EXTS:
        companions += [p.with_suffix(".work"), p.parent / ("%s.poster.jpg" % stem), p.parent / ("%s.credits.txt" % stem),
                       p.with_suffix(".report.json")]
    for c in companions:
        if c.exists():
            d = dest_dir / c.name
            n = 2
            while d.exists():
                d = dest_dir / ("%s-%d%s" % (c.stem, n, c.suffix))
                n += 1
            shutil.move(str(c), str(d))
            moved.append(str(d))
    gone = {str(c.resolve()) for c in companions}
    for k, v in list(data.get("outputs", {}).items()):
        try:
            hit = str(Path(v).resolve()) in gone
        except OSError:
            hit = False
        if hit:
            del data["outputs"][k]
            nxt = latest_output(job, k, data)
            if nxt is not None:
                data["outputs"][k] = str(nxt)
    data["next"] = None
    data.setdefault("discarded", []).append({"path": str(p), "at": now_iso(), "moved_to": moved[0] if moved else None})
    data["history"].append({"at": now_iso(), "event": "discarded %s (moved to work/discarded/)" % p.name})
    save(job, data)
    kept = [str(c) for c in (p.with_suffix(x) for x in (".srt", ".vtt", ".ass")) if c.is_file() and c != p]
    return {"job": str(job), "discarded": str(p), "moved": moved, "kept": kept, "outputs": outputs_view(job, data)}


def _qa_line_file(text: str) -> Optional[str]:
    m = re.match(r"^qa \w+ on (.+?): ", text)
    return m.group(1) if m else None


def record_qa(video: Path, rep: Dict[str, Any]) -> bool:
    """Called by `showtime qa`: log the verdict in the job ledger when the video sits in a job folder.

    Verdicts are kept per file ("qa_files"). The job's verdict ("qa", which status and the next
    command read) changes only for the job's latest video (final, else preview), so checking an
    export or a variant never makes the latest final look unchecked."""
    job = enclosing_job(video)
    if job is None:
        return False
    data = load(job)
    s = rep.get("summary") or {}
    loud = rep.get("loudness") or {}
    pr = rep.get("probe") or {}
    vp = Path(video).resolve()
    rec = {"verdict": rep.get("verdict"), "report": rep.get("report"), "at": now_iso(),
           "video": str(vp), "fail": s.get("fail"), "warn": s.get("warn")}
    if rep.get("lufs_arg") is not None:
        rec["lufs"] = rep["lufs_arg"]
    if (rep.get("target") or {}).get("source") == "--platform":
        rec["platform"] = rep["target"].get("name")
    files = data.get("qa_files") if isinstance(data.get("qa_files"), dict) else {}
    files[str(vp)] = rec
    data["qa_files"] = dict(list(files.items())[-40:])
    cur, _kind = latest_video(job, data)
    is_latest = cur is None or cur.resolve() == vp
    line = "qa %s on %s: %sx%s %.2fs" % (rep.get("verdict"), vp.name, pr.get("width"), pr.get("height"),
                                        pr.get("duration") or 0)
    if loud.get("integrated_lufs") is not None:
        line += ", %.1f LUFS, TP %.1f dBTP" % (loud["integrated_lufs"], loud.get("true_peak_dbtp") or 0)
    # one "qa ..." verified line per file; the latest video's line also retires older root renders' lines
    root_videos = {c.name for c in job.iterdir() if c.suffix.lower() in VIDEO_EXTS} if is_latest else set()

    def superseded(text: str) -> bool:
        if not text.startswith("qa "):
            return False
        f = _qa_line_file(text)
        return f is None or f == vp.name or f in root_videos
    data["verified"] = [v for v in data["verified"] if not superseded(v["text"])]
    if rep.get("verdict") in ("PASS", "WARN"):
        _add_item(data["verified"], line, "qa")
    for f in rep.get("findings", []):
        if f["severity"] == "FAIL":
            w = "qa FAIL %s%s on %s: %s" % (f["rule"], " at %.2fs" % f["t"] if f.get("t") is not None else "", vp.name,
                                            f["message"])
            if w[:300] not in data["warnings"]:
                data["warnings"].append(w[:300])
    if is_latest:
        data["qa"] = rec
        data["stages"].append({"name": "qa", "status": "done" if rep.get("verdict") != "FAIL" else "failed",
                               "ended": now_iso(), "seconds": rep.get("seconds")})
        data["stage"] = "qa"
        data["next"] = None   # the verdict decides what comes next
        data["pointers"]["qa"] = rep.get("report")
    else:
        line += " (not the latest %s; the job's qa verdict is unchanged)" % (_kind or "video")
    data["history"].append({"at": now_iso(), "event": line})
    save(job, data)
    if is_latest:
        from . import receipt
        receipt.refresh(job, share=False)   # the receipt follows the latest render; the share.txt line waits for deliver
    return True


def qa_of(data: Dict[str, Any], video: Optional[Path]) -> Dict[str, Any]:
    """The qa record of one file (its own per-file verdict), else the job's verdict."""
    qa = data.get("qa") or {}
    if video is None:
        return qa
    try:
        vr = str(Path(video).resolve())
    except OSError:
        return qa
    if qa.get("video") and str(Path(str(qa["video"])).resolve()) == vr:
        return qa
    rec = (data.get("qa_files") or {}).get(vr) if isinstance(data.get("qa_files"), dict) else None
    return rec if isinstance(rec, dict) and rec.get("verdict") else qa


# ------------------------------------------------------------------ views

def last_output(job: Path, data: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """(path, when) of the newest video: the latest final or preview (pointer, else newest file)."""
    vids = [v for v in (latest_output(job, "final", data), latest_output(job, "preview", data)) if v is not None]
    if not vids:
        return None
    v = max(vids, key=lambda x: x.stat().st_mtime)
    return str(v), _mtime_iso(v)


def studio_state(job: Path) -> Optional[Dict[str, Any]]:
    """Studio board state for jobs that use studio mode (None otherwise).

    Asks `showtime studio status <job> --json`; falls back to reading studio/board.json.
    """
    board = job / "studio" / "board.json"
    if not board.is_file():
        return None
    # `studio` is a node command (scripts/studio.mjs), so the state is read from the files directly:
    # board.json for rev/phase, studio/feedback.json events for picks and the approval (an approval
    # stands until it is retracted; a later board revision does not undo it)
    b = read_json(board, {}) or {}
    st: Dict[str, Any] = {k: b.get(k) for k in ("rev", "phase")}
    fb = read_json(job / "studio" / "feedback.json", {}) or {}
    events = fb.get("events") if isinstance(fb, dict) else None
    retracted = {e.get("target") for e in events or [] if isinstance(e, dict) and e.get("type") == "retract"}
    approved = None
    picks: Dict[str, Any] = {}
    for e in events or []:
        if not isinstance(e, dict) or e.get("id") in retracted:
            continue
        if e.get("type") == "approve":
            approved = {"target": e.get("target"), "rev": e.get("rev"), "ts": e.get("ts")}
        elif e.get("type") == "pick":
            picks[e.get("slot") or "concept"] = e.get("target")
        elif e.get("type") == "unpick":
            picks.pop(e.get("slot") or "concept", None)
    st["approved"] = approved
    if picks:
        st["picks"] = picks
    if events:
        st["feedback"] = len(events)
    return st


def _studio_text(st: Dict[str, Any]) -> str:
    def count(v: Any) -> Any:
        return len(v) if isinstance(v, (list, dict)) else v
    bits = ["phase %s" % st.get("phase")] if st.get("phase") else []
    if st.get("rev") is not None:
        bits.append("rev %s" % st["rev"])
    for k in ("concepts", "feedback", "picks"):
        if st.get(k) not in (None, [], {}):
            bits.append("%s %s" % (k, count(st[k])))
    bits.append("approved" if st.get("approved") else "not approved")
    url = (st.get("server") or {}).get("url") if isinstance(st.get("server"), dict) else None
    if url:
        bits.append("board open")
    return "studio: " + ", ".join(bits)


def _qa_rules(report: Optional[str], severity: str) -> List[str]:
    """Rule ids of one severity in a qa.json (empty when unreadable)."""
    rep = read_json(Path(report), None) if report and Path(report).is_file() else None
    out: List[str] = []
    for f in (rep or {}).get("findings", []) if isinstance(rep, dict) else []:
        if f.get("severity") == severity and f.get("rule") not in out:
            out.append(f["rule"])
    return out


_WARN_FIX = {
    "frozen": "showtime check {proj} --find-first frozen",
    "final_hold": "shorten the end hold or add motion",
    "resolution": "render at the platform size",
    "upscale": "use a smaller output size or a sharper source",
    "loudness": "showtime audio master",
    "true_peak": "showtime audio master",
    "aspect": "build the layout for the platform aspect",
}


def suggest_next(job: Path, data: Dict[str, Any]) -> str:
    """The one command to run next (SHOWTIME.md "Next command" and `showtime status`)."""
    if data.get("next"):
        return data["next"]
    studio = studio_state(job) if data.get("mode") == "studio" or (job / "studio" / "board.json").is_file() else None
    if studio is not None and not studio.get("approved"):
        return "showtime studio feedback %s --new" % job.name
    jn = job.name
    proj = project_of(job, data)
    vid, kind = latest_video(job, data)
    qa = qa_of(data, vid)
    edl = latest_output(job, "edl", data)
    if proj:
        rerender = "showtime render %s --job %s" % (proj, jn)
    elif edl is not None:
        rerender = "showtime edit render %s -o %s" % (jn, job / "final.mp4")
    else:
        rerender = "re-render"
    verdict = qa.get("verdict")
    if verdict and vid is not None and qa.get("video"):
        try:
            same = Path(str(qa["video"])).resolve() == vid.resolve()
        except OSError:
            same = False
        if not same:
            return "showtime qa %s   (the latest %s, %s, has not been checked yet)" % (jn, kind, vid.name)
    if verdict == "FAIL":
        return "fix the FAIL findings in %s, re-render (%s), then showtime qa %s" % (qa.get("report"), rerender, jn)
    if verdict == "WARN":
        rules = _qa_rules(qa.get("report"), "WARN")
        fixes = [_WARN_FIX[r].format(proj=proj or "<project>") for r in rules if r in _WARN_FIX]
        return ("fix the qa warnings first (%s; details in %s)%s, re-render (%s), then showtime qa %s   "
                "(export only once each warning is fixed or knowingly accepted)" % (
                    ", ".join(rules) or "see the report", qa.get("report"),
                    ": " + "; ".join(dict.fromkeys(fixes)) if fixes else "", rerender, jn))
    last_stage = (data.get("stages") or [{}])[-1] if data.get("stages") else {}
    if verdict in ("PASS", "WARN") and last_stage.get("name") in ("deliver", "done") and last_stage.get("status") == "done":
        rv = _review(job, data, vid) if kind == "final" else {}
        if rv.get("pending") and rv.get("next"):
            return "%s   (delivered, but the quality-mode critic round is still open)" % rv["next"]
        return "nothing required: %s was checked (qa %s) and delivered. To change it: edit, %s, then showtime qa %s" % (
            vid.name if vid is not None else "the final", verdict, rerender, jn)
    if verdict == "PASS":
        if kind == "preview":
            return "%s   (qa passed the preview; now the final)" % (rerender if rerender != "re-render" else
                                                                  "render the final into %s" % jn)
        rv = _review(job, data, vid)
        if rv.get("pending") and rv.get("next"):
            return "%s   (quality mode: the critic round comes before delivery)" % rv["next"]
        if rv.get("mode") == "quality":
            return "showtime deliver exports %s --targets <platforms>" % jn
        return "showtime deliver exports %s --targets <platforms>   (or showtime review-pack %s)" % (jn, jn)
    if vid is not None:
        return "showtime qa %s" % jn
    if proj:
        return "showtime check %s   then   showtime render %s --job %s --preview" % (proj, proj, jn)
    if edl is not None:
        return "showtime edit render %s --preview" % jn
    return ("showtime new <template> %s   (the job records the project itself; then showtime check it and "
            "showtime render it --job %s)" % (job / "project", jn))


def _review(job: Path, data: Dict[str, Any], video: Optional[Path] = None) -> Dict[str, Any]:
    """The job's review state (st.job.review_state); {} when it cannot be read (never breaks status)."""
    try:
        from . import review_state
        return review_state.state(job, data, video)
    except Exception:  # noqa: BLE001 - the review line is a convenience
        return {}


def _ago(iso: Optional[str]) -> str:
    t = _parse_iso(iso)
    if t is None:
        return "?"
    s = max(0, time.time() - t)
    if s < 90:
        return "%ds ago" % s
    if s < 5400:
        return "%dm ago" % (s // 60)
    if s < 172800:
        return "%.1fh ago" % (s / 3600)
    return "%dd ago" % (s // 86400)


def status_lines(job: Path, data: Optional[Dict[str, Any]] = None, absolute: bool = False) -> List[str]:
    data = data or load(job)
    st = data["stages"][-1] if data.get("stages") else None
    where = ("%s %s" % (st["name"], st.get("status", ""))) if st else "not started"
    goal = (" | goal: " + _short(data["goal"], 60)) if data.get("goal") else ""
    when = (data.get("updated") or "")[:16].replace("T", " ") if absolute else _ago(data.get("updated"))
    rv = _review(job, data)
    l1 = "%s (%s%s): %s, updated %s%s" % (job.name, data.get("mode", "quick"),
                                          ", %s review" % rv["mode"] if rv.get("mode") else "", where, when, goal)
    lo = last_output(job, data)
    qa = qa_of(data, latest_video(job, data)[0])
    open_q = [q for q in data.get("questions", []) if not q.get("answer")]
    l2 = "verified %d, assumed %d, open questions %d" % (len(data.get("verified", [])), len(data.get("assumed", [])), len(open_q))
    if lo:
        l2 += "; last output %s (%s)" % (_rel(lo[0], job), lo[1][:16].replace("T", " ") if absolute else _ago(lo[1]))
    if qa.get("verdict"):
        l2 += "; qa %s" % qa["verdict"]
    if rv.get("pending"):
        l2 += "; review pending"
    elif rv.get("status") in ("done", "cap"):
        l2 += "; " + rv["message"]
    studio = studio_state(job)
    if studio is not None:
        l2 += "; " + _studio_text(studio)
    l3 = "next: " + suggest_next(job, data)
    return [l1, l2, l3]


def _short(s: str, n: int) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _rel(p: str, job: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(job.resolve()))
    except (ValueError, OSError):
        return str(p)


_REVIEW_TEXT = {"quality": "full review: looks, qa and a critic round before delivery",
                "lean": "a draft pass: the critic round only when publish-bound or asked"}


def render_md(job: Path, data: Dict[str, Any], notes: str = "") -> str:
    L: List[str] = []
    L.append("# SHOWTIME: %s" % data.get("slug", job.name))
    L.append("")
    L.append("<!-- Generated from job.json by showtime. Update it with `showtime job note`. "
             "Text under \"## Notes\" is kept. Read this first when resuming. -->")
    L.append("")
    L.append("## Goal")
    L.append(data.get("goal") or "(not recorded yet: `showtime job note %s --goal \"...\"`)" % job.name)
    L.append("")
    rv = _review(job, data)
    L.append("Mode: %s%s. Created %s.%s" % (data.get("mode", "quick"),
                                          (", %s review (%s)" % (rv["mode"], _REVIEW_TEXT.get(rv["mode"], "")))
                                          if rv.get("mode") else "",
                                          (data.get("created") or "")[:16].replace("T", " "),
                                          " Project: `%s`." % data["project"] if data.get("project") else ""))
    L.append("")
    L.append("## Where we are")
    for line in status_lines(job, data, absolute=True)[:2]:
        L.append("- " + line)
    qa = qa_of(data, latest_video(job, data)[0])
    if qa.get("verdict"):
        L.append("- QA %s (%s fail, %s warn), report `%s`" % (qa["verdict"], qa.get("fail"), qa.get("warn"), qa.get("report")))
    if rv.get("message") and rv.get("status") not in ("lean", "no final"):
        L.append("- %s%s" % (rv["message"], (" -> `%s`" % rv["next"]) if rv.get("next") else ""))
    L.append("")
    L.append("## Verified")
    if data.get("verified"):
        for v in data["verified"]:
            L.append("- %s%s" % (v["text"], " (%s)" % v["stage"] if v.get("stage") else ""))
    else:
        L.append("- (nothing checked yet)")
    L.append("")
    L.append("## Assumed (not yet checked)")
    if data.get("assumed"):
        for a in data["assumed"]:
            L.append("- %s%s" % (a["text"], " (%s)" % a["stage"] if a.get("stage") else ""))
    else:
        L.append("- (none recorded)")
    L.append("")
    L.append("## Open questions")
    open_q = [q for q in data.get("questions", []) if not q.get("answer")]
    done_q = [q for q in data.get("questions", []) if q.get("answer")]
    if open_q:
        for i, q in enumerate(open_q, 1):
            L.append("%d. %s" % (i, q["text"]))
    else:
        L.append("- (none open)")
    if done_q:
        L.append("")
        L.append("Answered (do not ask again):")
        for q in done_q:
            L.append("- %s: %s" % (q["text"], q["answer"]))
    L.append("")
    L.append("## Next command")
    L.append("```")
    L.append(suggest_next(job, data))
    L.append("```")
    L.append("")
    L.append("## Pointers")
    ptr = dict(data.get("pointers") or {})
    ptr.setdefault("ledger", "job.json")
    ptr.setdefault("logs", "work/logs/")
    for k, v in ptr.items():
        L.append("- %s: `%s`" % (k, _rel(v, job) if v else v))
    for k, v in outputs_view(job, data).items():
        L.append("- latest %s: `%s`" % (k, _rel(v, job)))
    L.append("")
    if data.get("stages"):
        L.append("## Stages")
        L.append("| stage | status | seconds | ended |")
        L.append("|---|---|---|---|")
        for s in data["stages"][-30:]:
            L.append("| %s | %s | %s | %s |" % (s["name"], s.get("status", ""), s.get("seconds") if s.get("seconds") is not None else "",
                                              (s.get("ended") or s.get("started") or "")[:16].replace("T", " ")))
        L.append("")
    if data.get("warnings"):
        L.append("## Warnings")
        for w in data["warnings"][-20:]:
            L.append("- " + w)
        L.append("")
    env = data.get("env") or {}
    ffv = (env.get("ffmpeg") or {}).get("version")
    br = env.get("browser") or {}
    L.append("## Environment")
    L.append("showtime %s%s on %s (%s cpus), python %s, node %s, ffmpeg %s, browser %s %s." % (
        env.get("showtime"), " (%s)" % env["git"] if env.get("git") else "", env.get("platform"), env.get("cpus"),
        env.get("python"), env.get("node"), ffv, br.get("kind") if br else "none", (br.get("version") or "") if br else ""))
    c = data.get("cache") or {}
    if c.get("hits") or c.get("misses"):
        L.append("Cache: %s hits, %s misses." % (c.get("hits", 0), c.get("misses", 0)))
    L.append("")
    L.append(NOTES_HEAD)
    L.append(notes if notes else "(free text; kept across updates)")
    L.append("")
    return "\n".join(L)

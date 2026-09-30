#!/usr/bin/env python3
"""The logic of the showtime-video GitHub Action (stdlib only, runs anywhere Python 3.8+ does).

action.yml only wires inputs and environment and calls this file, so everything here can be run and
tested on a laptop. Inputs arrive as INPUT_<NAME> environment variables (NAME in capitals, dashes
turned into underscores: notes-file -> INPUT_NOTES_FILE), the way action.yml passes them.

  run.py prepare      print the cache key and the showtime home (step outputs)
  run.py setup        install or verify the showtime runtime (idempotent; skipped when a cache restored it)
  run.py run          the video: release, project or agent mode (the default subcommand)
  run.py upload       upload the video files to a GitHub release (gh release upload --clobber)

Add --dry-run to any of them to print the exact commands and the resolved notes, title and version
without running anything. Every command runs through the showtime launcher of the checkout this file
lives in (skills/showtime/bin/showtime), or of the checkout named by INPUT_SHOWTIME_PATH.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = Path(__file__).resolve().parent
DEFAULT_CHECKOUT = HERE.parents[2]  # .github/actions/showtime-video -> the repository root
SETUP_FILES = ("manifest.json", "requirements.txt", "package.json", "package-lock.json", "setup.py")
NOTES_MAX_BYTES = 200_000  # a release body is a few KB; refuse an accidental whole-file dump
MODES = ("release", "project", "agent")
UPLOADS = ("artifact", "release", "none")
# what the home cache holds (relative to the showtime home); logs, scratch and run caches stay out
CACHE_EXCLUDE = ("logs", "cache", "runs")


class ActionError(Exception):
    """A problem the user can fix; printed as one message, exit code 1."""


# ---------------------------------------------------------------------------
# inputs and the GitHub environment
# ---------------------------------------------------------------------------

def get_input(env: Dict[str, str], name: str, default: str = "") -> str:
    """INPUT_<NAME> with dashes as underscores; empty means not set."""
    key = "INPUT_" + name.upper().replace("-", "_")
    val = env.get(key)
    if val is None or not val.strip():
        return default
    return val.strip()


def truthy(text: str) -> bool:
    return text.strip().lower() in ("1", "true", "yes", "on")


def read_event(env: Dict[str, str]) -> Dict[str, Any]:
    """The webhook payload GitHub saved for this run (GITHUB_EVENT_PATH), or {}."""
    path = env.get("GITHUB_EVENT_PATH", "")
    if not path or not Path(path).is_file():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def repo_name(env: Dict[str, str]) -> str:
    repo = env.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        return repo.split("/", 1)[1]
    return repo or Path(env.get("GITHUB_WORKSPACE") or os.getcwd()).name


def slugify(*parts: str, limit: int = 40) -> str:
    text = "-".join(p for p in parts if p)
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:limit].strip("-")) or "release"


def write_output(env: Dict[str, str], key: str, value: str) -> None:
    """Append key=value to the file GITHUB_OUTPUT names; a multi-line value uses a heredoc delimiter."""
    path = env.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        if "\n" in value or "\r" in value:
            delim = "ST_EOF_%d" % int(time.time() * 1000)
            f.write("%s<<%s\n%s\n%s\n" % (key, delim, value, delim))
        else:
            f.write("%s=%s\n" % (key, value))


def write_summary(env: Dict[str, str], markdown: str) -> None:
    path = env.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(markdown.rstrip() + "\n")


# ---------------------------------------------------------------------------
# where showtime is
# ---------------------------------------------------------------------------

def skill_dir(env: Dict[str, str]) -> Path:
    """skills/showtime of this checkout, or of INPUT_SHOWTIME_PATH (a checkout root or the skill folder)."""
    override = get_input(env, "showtime-path")
    root = Path(override).expanduser() if override else DEFAULT_CHECKOUT
    for cand in (root / "skills" / "showtime", root):
        if (cand / "lib" / "st" / "launcher.py").is_file():
            return cand.resolve()
    raise ActionError("no showtime checkout at %s (looked for skills/showtime/lib/st/launcher.py)" % root)


def showtime_home(env: Dict[str, str]) -> Path:
    home = env.get("SHOWTIME_HOME")
    if home:
        return Path(os.path.expanduser(home))
    return Path(os.path.expanduser("~")) / ".showtime"


def launcher_cmd(env: Dict[str, str]) -> List[str]:
    """The command prefix that runs showtime. POSIX: the sh shim. Windows: the venv's (else this) Python on
    launcher.py, because arguments with & % ^ | would be re-read by cmd.exe if they went through showtime.cmd."""
    sk = skill_dir(env)
    if os.name == "nt":
        venv_py = showtime_home(env) / "venv" / "Scripts" / "python.exe"
        py = str(venv_py) if venv_py.is_file() else sys.executable
        return [py, str(sk / "lib" / "st" / "launcher.py")]
    return [str(sk / "bin" / "showtime")]


def shim_path(env: Dict[str, str]) -> str:
    """The user-facing entry point, given to an agent command as SHOWTIME_BIN."""
    sk = skill_dir(env)
    return str(sk / "bin" / ("showtime.cmd" if os.name == "nt" else "showtime"))


def cache_key(env: Dict[str, str]) -> Tuple[str, str]:
    """(key, hash) for the runtime cache: OS, arch, Python, tier and the setup files' contents."""
    setup = skill_dir(env) / "setup"
    h = hashlib.sha256()
    for name in SETUP_FILES:
        p = setup / name
        h.update(name.encode() + b"\0")
        if p.is_file():
            h.update(p.read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    tier = get_input(env, "tier", "minimal")
    h.update(("tier=%s" % tier).encode())
    digest = h.hexdigest()[:16]
    key = "showtime-action-%s-%s-py%s-%s-%s" % (
        env.get("RUNNER_OS", platform.system()), env.get("RUNNER_ARCH", platform.machine()),
        platform.python_version(), tier, digest)
    return key, digest


# ---------------------------------------------------------------------------
# notes: where the words on screen come from
# ---------------------------------------------------------------------------

class Notes:
    """Resolved input for `showtime release-video`: markdown text plus the flags around it."""

    def __init__(self) -> None:
        self.markdown = ""
        self.source = ""
        self.kind = "release"
        self.name = ""
        self.version = ""
        self.date = ""
        self.url = ""
        self.changelog_version = ""  # set when markdown is a whole CHANGELOG file

    def describe(self) -> str:
        return "source=%s kind=%s name=%r version=%r date=%r url=%r chars=%d%s" % (
            self.source, self.kind, self.name, self.version, self.date, self.url, len(self.markdown),
            " (CHANGELOG section %s)" % self.changelog_version if self.changelog_version else "")


def _workspace(env: Dict[str, str]) -> Path:
    return Path(env.get("GITHUB_WORKSPACE") or os.getcwd())


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise ActionError("file not found: %s" % path)
    if path.stat().st_size > NOTES_MAX_BYTES * 5:
        raise ActionError("%s is larger than expected for release notes (%d bytes)" % (path, path.stat().st_size))
    return path.read_text(encoding="utf-8", errors="replace")


def resolve_notes(env: Dict[str, str], event: Optional[Dict[str, Any]] = None) -> Notes:
    """Order: notes input, notes-file, changelog (+ version), then the GitHub event (release or pull_request)."""
    event = read_event(env) if event is None else event
    n = Notes()
    n.name = get_input(env, "name") or repo_name(env)
    n.version = get_input(env, "version")
    n.url = get_input(env, "url")
    ev_name = env.get("GITHUB_EVENT_NAME", "")
    release = event.get("release") if isinstance(event.get("release"), dict) else None
    pr = event.get("pull_request") if isinstance(event.get("pull_request"), dict) else None
    server = env.get("GITHUB_SERVER_URL", "https://github.com")
    repo_url = "%s/%s" % (server, env["GITHUB_REPOSITORY"]) if env.get("GITHUB_REPOSITORY") else ""

    text = get_input(env, "notes")
    notes_file = get_input(env, "notes-file")
    changelog = get_input(env, "changelog")
    if text:
        n.markdown, n.source = text, "input notes"
    elif notes_file:
        n.markdown, n.source = _read_text(_workspace(env) / notes_file), "file %s" % notes_file
    elif changelog or (n.version and (_workspace(env) / "CHANGELOG.md").is_file() and not release and not pr):
        changelog = changelog or "CHANGELOG.md"
        if not n.version:
            raise ActionError("input 'changelog' needs input 'version' (which CHANGELOG section to use)")
        n.markdown, n.source = _read_text(_workspace(env) / changelog), "changelog %s" % changelog
        n.changelog_version = n.version
    elif ev_name == "release" and release:
        n.markdown = str(release.get("body") or "")
        n.source = "release event"
        n.version = n.version or str(release.get("tag_name") or release.get("name") or "")
        n.url = n.url or str(release.get("html_url") or "")
        n.date = str(release.get("published_at") or release.get("created_at") or "")[:10]
        if not n.markdown.strip():
            raise ActionError("the release %s has no description: write the release notes on the release, or pass "
                              "the notes, notes-file or changelog input" % (n.version or ""))
    elif ev_name.startswith("pull_request") and pr:
        title = str(pr.get("title") or "").strip()
        body = str(pr.get("body") or "").strip()
        n.markdown = ("# %s\n\n%s\n" % (title, body)) if title else body
        n.source = "pull request event"
        n.kind = "pr"
        n.version = n.version or ("#%s" % (pr.get("number") or event.get("number") or ""))
        n.url = n.url or str(pr.get("html_url") or "")
        if not body:
            raise ActionError("pull request #%s has no description to make a video from" % (pr.get("number") or ""))
    else:
        raise ActionError("no notes to make a video from (event: %s): pass the notes, notes-file or changelog + "
                          "version input, or run on a release or pull_request event" % (ev_name or "none"))
    if not n.markdown.strip():
        raise ActionError("the notes are empty (%s)" % n.source)
    if len(n.markdown.encode("utf-8")) > NOTES_MAX_BYTES:
        raise ActionError("the notes are longer than %d bytes (%s)" % (NOTES_MAX_BYTES, n.source))
    n.url = n.url or repo_url
    return n


# ---------------------------------------------------------------------------
# running commands
# ---------------------------------------------------------------------------

def quote(cmd: Sequence[str]) -> str:
    # display only; the action's steps run in bash on every runner (Windows included), so bash quoting everywhere
    return " ".join(shlex.quote(str(c)) for c in cmd)


class Runner:
    """Runs (or, with dry_run, only lists) commands; keeps every command for tests and the summary."""

    def __init__(self, env: Dict[str, str], dry_run: bool = False) -> None:
        self.env = env
        self.dry_run = dry_run
        self.commands: List[List[str]] = []
        self.st = launcher_cmd(env)
        self.work = Path(get_input(env, "work-dir") or (env.get("RUNNER_TEMP") or tempdir()) + "/showtime-work")
        self.child_env = dict(os.environ)
        self.child_env.update({k: v for k, v in env.items() if k in ("SHOWTIME_HOME",)})
        self.child_env.update({"PYTHONUTF8": "1", "NO_COLOR": "1", "SHOWTIME_PROGRESS": "plain",
                               "SHOWTIME_OUT": str(self.work)})

    def say(self, text: str) -> None:
        print(text, flush=True)

    def showtime(self, *args: str, capture: bool = False, cwd: Optional[Path] = None,
                 check: bool = True, echo: bool = True) -> "subprocess.CompletedProcess[str]":
        return self.run(self.st + [str(a) for a in args], capture=capture, cwd=cwd, check=check, echo=echo)

    def run(self, cmd: Sequence[str], capture: bool = False, cwd: Optional[Path] = None, check: bool = True,
            env_extra: Optional[Dict[str, str]] = None, shown: Optional[str] = None,
            echo: bool = True) -> "subprocess.CompletedProcess[str]":
        cmd = [str(c) for c in cmd]
        self.commands.append(cmd)
        self.say("+ " + (shown or self._short(cmd)))
        if self.dry_run:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        env = dict(self.child_env)
        env.update(env_extra or {})
        try:
            cp = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, universal_newlines=True,
                                encoding="utf-8", errors="replace",
                                stdout=subprocess.PIPE if capture else None,
                                stderr=subprocess.STDOUT if capture else None)
        except OSError as e:
            raise ActionError("could not start %s: %s" % (cmd[0], e))
        if capture and echo and cp.stdout:
            sys.stdout.write(cp.stdout)
            sys.stdout.flush()
        if check and cp.returncode != 0:
            raise ActionError("%s failed (exit %d)" % (" ".join(cmd[len(self.st):len(self.st) + 2]) or cmd[0],
                                                       cp.returncode))
        return cp

    def _short(self, cmd: Sequence[str]) -> str:
        """Show the launcher as `showtime` so logs read like what a person types."""
        if list(cmd[:len(self.st)]) == self.st:
            return quote(["showtime"] + list(cmd[len(self.st):]))
        return quote(cmd)


def tempdir() -> str:
    import tempfile
    return tempfile.gettempdir()


# ---------------------------------------------------------------------------
# job helpers
# ---------------------------------------------------------------------------

JOB_PLACEHOLDER = "<job>"


def parse_json_tail(text: str) -> Dict[str, Any]:
    i = text.find("{")
    if i < 0:
        return {}
    try:
        return json.loads(text[i:])
    except ValueError:
        return {}


def init_job(r: Runner, slug: str, goal: str, project: str = "") -> str:
    if not r.dry_run:
        r.work.mkdir(parents=True, exist_ok=True)
    args = ["job", "init", slug, "--goal", goal, "--base", str(r.work), "--json"]
    if project:
        args += ["--project", project]
    platform_ = get_input(r.env, "platform")
    if platform_:
        args += ["--platform", platform_]
    cp = r.showtime(*args, capture=True)
    if r.dry_run:
        return JOB_PLACEHOLDER
    job = parse_json_tail(cp.stdout or "").get("job")
    if not job:
        raise ActionError("showtime job init printed no job folder")
    return str(job)


def newest_job(work: Path) -> Optional[Path]:
    out = work / "showtime-out"
    if not out.is_dir():
        return None
    jobs = [p for p in out.iterdir() if p.is_dir() and (p / "job.json").is_file()]
    return max(jobs, key=lambda p: p.stat().st_mtime) if jobs else None


def job_project(job: Path) -> Optional[Path]:
    """The project folder a job renders: job.json "project", else <job>/project."""
    try:
        led = json.loads((job / "job.json").read_text(encoding="utf-8"))
        p = led.get("project")
        if p and (Path(p) / "showtime.json").is_file():
            return Path(p)
    except (OSError, ValueError, AttributeError):
        pass
    cand = job / "project"
    return cand if (cand / "showtime.json").is_file() else None


def latest_final(job: Path) -> Optional[Path]:
    """The newest final render in the job: final.mp4, final-2.mp4 ..."""
    def number(p: Path) -> int:  # final.mp4 is 1, final-2.mp4 is 2 ...; never by clock (equal times on fast disks)
        m = re.match(r"final(?:-(\d+))?(?:\.captioned)?\.mp4$", p.name)
        return int(m.group(1) or 1) if m else 0
    finals = sorted((p for p in job.glob("final*.mp4") if number(p)), key=lambda p: (number(p), p.name.endswith(".captioned.mp4")))
    plain = [p for p in finals if not p.name.endswith(".captioned.mp4")]
    return (plain or finals)[-1] if finals else None


def qa_verdict(job: Path, video: Optional[Path]) -> str:
    """PASS, WARN or FAIL from the qa.json qa wrote for this video ('' when there is none)."""
    if video is None:
        return ""
    for cand in (job / "work" / "qa" / video.stem / "qa.json", video.with_suffix(".qa") / "qa.json"):
        if cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            v = str(data.get("verdict") or data.get("status") or "").upper()
            if v:
                return v
    return ""


def qa_line(job: Path, video: Optional[Path]) -> str:
    if video is None:
        return ""
    for cand in (job / "work" / "qa" / video.stem / "qa.json", video.with_suffix(".qa") / "qa.json"):
        if cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            bits = []
            for key, label in (("integrated_lufs", "LUFS"), ("lufs", "LUFS"), ("true_peak_dbtp", "dBTP"),
                               ("true_peak", "dBTP")):
                val = _dig(data, key)
                if isinstance(val, (int, float)) and label not in [b.split()[-1] for b in bits]:
                    bits.append("%.1f %s" % (val, label))
            return ", ".join(bits)
    return ""


def _dig(data: Any, key: str) -> Any:
    if isinstance(data, dict):
        if key in data:
            return data[key]
        for v in data.values():
            found = _dig(v, key)
            if found is not None:
                return found
    elif isinstance(data, list):
        for v in data:
            found = _dig(v, key)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------------------
# the three modes
# ---------------------------------------------------------------------------

class Result:
    def __init__(self) -> None:
        self.job = ""
        self.video = ""
        self.html = ""
        self.poster = ""
        self.qa = ""
        self.vertical = ""
        self.files: List[str] = []
        self.qa_detail = ""
        self.error = ""
        self.slug = "showtime-video"
        self.extras: List[Tuple[str, str]] = []  # (path, suffix) files that go up with the video

    def outputs(self) -> Dict[str, str]:
        return {"video": self.video, "html": self.html, "poster": self.poster, "qa": self.qa, "job": self.job,
                "vertical": self.vertical, "files": "\n".join(self.files)}



def _write_lf(path: Path, text: str) -> None:
    """Write text with LF line ends on every OS (Path.write_text's newline= needs Python 3.10)."""
    with open(str(path), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

def collect(res: Result, job: Path) -> None:
    """Fill the result from what is on disk in the job (safe to call after a failure, too)."""
    res.job = str(job)
    final = latest_final(job)
    if final:
        res.video = str(final)
        poster = final.with_name(final.stem + ".poster.jpg")
        if not poster.is_file():
            poster = final.with_name("poster.jpg") if final.name == "final.mp4" else poster
        if poster.is_file():
            res.poster = str(poster)
    exports = job / "exports"
    if exports.is_dir():
        htmls = sorted(exports.glob("*.html"), key=lambda p: p.stat().st_mtime)
        if htmls:
            res.html = str(htmls[-1])
    verticals = sorted(job.glob("*x*.mp4"), key=lambda p: p.stat().st_mtime)
    verticals = [p for p in verticals if re.match(r"^\d+x\d+\.mp4$", p.name)]
    if verticals:
        res.vertical = str(verticals[-1])
    verdict = qa_verdict(job, final)
    if verdict:
        res.qa = verdict
        res.qa_detail = qa_line(job, final)
    res.extras = []
    if exports.is_dir():
        small = sorted(exports.glob("*.github*.mp4"), key=lambda p: p.stat().st_mtime)
        if small:
            res.extras.append((str(small[-1]), "-github.mp4"))
    if final:
        qa_json = job / "work" / "qa" / final.stem / "qa.json"
        if qa_json.is_file():
            res.extras.append((str(qa_json), "-qa.json"))
    for extra in ("share.txt", "credits.txt"):
        if (job / extra).is_file():
            res.extras.append((str(job / extra), "-" + extra))


def stage(res: Result, work: Path) -> None:
    """Copy the deliverables to <work>/upload/ under names that say what they are (final.mp4 would collide
    on a release page); res.files lists them, one per line in the step output."""
    up = work / "upload"
    if up.exists():
        shutil.rmtree(str(up), ignore_errors=True)
    todo = [(res.video, ".mp4"), (res.vertical, "-9x16.mp4"), (res.html, ".html"), (res.poster, "-poster.jpg")]
    todo += res.extras
    staged: List[str] = []
    for src, suffix in todo:
        if src and Path(src).is_file():
            up.mkdir(parents=True, exist_ok=True)
            dst = up / (res.slug + suffix)
            shutil.copyfile(src, str(dst))
            staged.append(str(dst))
    res.files = staged


def render_and_check(r: Runner, res: Result, job: str, project: str, slug: str, vertical: bool) -> None:
    """check, render, qa, export html (and the 9:16 render): shared by release and project modes."""
    r.showtime("check", project)
    r.showtime("render", project, "--job", job)
    qa_args = ["qa", job]
    cp = r.showtime(*qa_args, check=False)
    if not r.dry_run:
        collect(res, Path(job))
    if cp.returncode != 0:
        res.qa = res.qa or "FAIL"
        raise ActionError("showtime qa found a FAIL in the finished video (see the report above; the frames and "
                          "sheet are in %s)" % (Path(job) / "work" / "qa"))
    html_out = str(Path(job) / "exports" / (slug + ".html")) if not r.dry_run else "%s/exports/%s.html" % (job, slug)
    r.showtime("export", "html", project, "-o", html_out)
    # a copy under GitHub's 10 MB embed limit, for release pages, PR comments and READMEs (the master is
    # often 1-2 MB per second of video); a failure here never fails the job
    r.showtime("deliver", "exports", job, "--targets", "github", check=False)
    if not r.dry_run:
        collect(res, Path(job))
    if vertical:
        r.showtime("render", project, "--job", job, "--size", "9:16")
        vids = [] if r.dry_run else sorted(Path(job).glob("1080x1920.mp4"))
        target = str(vids[0]) if vids else "%s/1080x1920.mp4" % job
        cpv = r.showtime("qa", target, "--platform", "reels", check=False)
        if cpv.returncode != 0:
            if not r.dry_run:
                collect(res, Path(job))
            raise ActionError("showtime qa found a FAIL in the 9:16 video")


def do_release(r: Runner, res: Result) -> None:
    env = r.env
    n = resolve_notes(env)
    r.say("notes: " + n.describe())
    slug = slugify("release" if n.kind == "release" else "pr", n.name, n.version)
    res.slug = slug
    goal = "%s video for %s %s (GitHub Action, from %s)" % (
        "Release" if n.kind == "release" else "Pull request", n.name, n.version,
        "the release notes" if n.kind == "release" else "the pull request description")
    notes_file = r.work / "notes.md"
    if r.dry_run:
        r.say("write %s (%d chars):\n%s" % (notes_file, len(n.markdown), _indent(n.markdown[:600])))
    else:
        r.work.mkdir(parents=True, exist_ok=True)
        _write_lf(notes_file, n.markdown)
    job = init_job(r, slug, goal)
    project = "%s/project" % job
    rv = ["release-video", str(notes_file), "-o", project, "--name", n.name]
    if n.changelog_version:
        rv += ["--changelog-version", n.changelog_version]
    if n.version:
        rv += ["--version", n.version]
    if n.kind == "pr":
        rv += ["--kind", "pr"]
    if n.date:
        rv += ["--date", n.date]
    install = get_input(env, "install")
    if install:
        rv += ["--install", install]
    if n.url:
        rv += ["--url", n.url]
    max_items = get_input(env, "max-items")
    if max_items:
        rv += ["--max-items", max_items]
    r.showtime(*rv)
    if not r.dry_run:
        res.job = job
    render_and_check(r, res, job, project, slug, truthy(get_input(env, "vertical", "false")))


def do_project(r: Runner, res: Result) -> None:
    env = r.env
    rel = get_input(env, "project")
    if not rel:
        raise ActionError("mode 'project' needs the input 'project' (a showtime project folder in the repository)")
    project = Path(rel)
    if not project.is_absolute():
        project = _workspace(env) / project
    if not r.dry_run and not (project / "showtime.json").is_file():
        raise ActionError("%s is not a showtime project (no showtime.json)" % project)
    slug = slugify("project", project.name)
    res.slug = slug
    job = init_job(r, slug, "Render the committed project %s (GitHub Action)" % project.name, project=str(project))
    if not r.dry_run:
        res.job = job
    render_and_check(r, res, job, str(project), slug, truthy(get_input(env, "vertical", "false")))


def do_agent(r: Runner, res: Result) -> None:
    env = r.env
    command = get_input(env, "agent-command")
    prompt = get_input(env, "prompt")
    if not command:
        raise ActionError("mode 'agent' needs the input 'agent-command' (the shell command that runs your coding agent)")
    if not prompt:
        raise ActionError("mode 'agent' needs the input 'prompt' (what the agent should make)")
    slug = slugify("agent", repo_name(env))
    res.slug = slug
    job = init_job(r, slug, prompt[:200])
    extra = {"SHOWTIME_PROMPT": prompt, "SHOWTIME_BIN": shim_path(env), "SHOWTIME_JOB": job,
             "SHOWTIME_OUT": str(r.work), "SHOWTIME_WORKDIR": str(r.work)}
    try:
        n = resolve_notes(env)
    except ActionError:
        n = None
    if n is not None:
        nf = r.work / "notes.md"
        if r.dry_run:
            r.say("notes for the agent: SHOWTIME_NOTES=%s (%s)" % (nf, n.describe()))
        else:
            _write_lf(nf, n.markdown)
        extra["SHOWTIME_NOTES"] = str(nf)
    bash = shutil.which("bash")
    shell = [bash, "-c", command] if bash else (["cmd", "/c", command] if os.name == "nt" else ["sh", "-c", command])
    cwd = _workspace(env)
    r.say("agent command runs in %s with SHOWTIME_PROMPT, SHOWTIME_BIN, SHOWTIME_JOB, SHOWTIME_OUT%s set"
          % (cwd, ", SHOWTIME_NOTES" if n is not None else ""))
    r.run(shell, cwd=cwd if not r.dry_run else None, env_extra=extra, shown="%s   # agent command" % command)
    if r.dry_run:
        r.showtime("qa", JOB_PLACEHOLDER)
        r.showtime("export", "html", "<job>/project", "-o", "<job>/exports/%s.html" % slug)
        r.showtime("deliver", "exports", JOB_PLACEHOLDER, "--targets", "github")
        return
    jobp = Path(job)
    if latest_final(jobp) is None:
        other = newest_job(r.work)
        if other is not None and latest_final(other) is not None:
            jobp = other
    final = latest_final(jobp)
    if final is None:
        raise ActionError("the agent command finished but no final video exists in %s (a render writes final.mp4 "
                          "into the job; check the agent's output above)" % job)
    res.job = str(jobp)
    cp = r.showtime("qa", str(jobp), check=False)
    collect(res, jobp)
    if cp.returncode != 0:
        res.qa = res.qa or "FAIL"
        raise ActionError("showtime qa found a FAIL in the video the agent made")
    proj = job_project(jobp)
    if proj is not None:
        r.showtime("export", "html", str(proj), "-o", str(jobp / "exports" / (slug + ".html")), check=False)
        collect(res, jobp)
    else:
        r.say("note: no project folder found in the job, so no HTML export (the MP4 is the deliverable)")
    r.showtime("deliver", "exports", str(jobp), "--targets", "github", check=False)
    collect(res, jobp)


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------

def cmd_prepare(env: Dict[str, str], dry_run: bool) -> int:
    key, digest = cache_key(env)
    home = showtime_home(env)
    print("cache key: %s\nhome: %s" % (key, home))
    write_output(env, "key", key)
    write_output(env, "hash", digest)
    write_output(env, "home", str(home))
    # forward slashes everywhere: the cache action's glob reads them on Windows too
    write_output(env, "path", "\n".join([home.as_posix()] + ["!" + (home / x).as_posix() for x in CACHE_EXCLUDE]))
    return 0


def cmd_setup(env: Dict[str, str], dry_run: bool) -> int:
    r = Runner(env, dry_run)
    tier = get_input(env, "tier", "minimal")
    hit = env.get("CACHE_HIT", "") == "true"
    t0 = time.time()
    skipped = False
    if hit:
        cp = r.showtime("doctor", "--quick", "--json", capture=True, check=False, echo=False)
        rows = parse_json_tail(cp.stdout or "")
        if rows.get("counts"):
            r.say("doctor --quick: %s" % ", ".join("%s %s" % (v, k) for k, v in rows["counts"].items()))
        if dry_run or (cp.returncode == 0 and rows.get("ok")):
            r.say("the cached showtime home passes doctor --quick: setup skipped")
            skipped = True
    if not skipped:
        r.showtime("setup", "--tier", tier)
    if sys.platform.startswith("linux") and truthy(get_input(env, "browser-deps", "true")):
        install_browser_deps(r)
    r.showtime("doctor", check=False)
    write_output(env, "setup-seconds", "%.0f" % (time.time() - t0))
    write_output(env, "setup-skipped", "true" if skipped else "false")
    return 0


def install_browser_deps(r: Runner) -> None:
    """Like scripts/e2e.py: only when the browser does not start, install Chromium's system libraries."""
    if r.dry_run:
        r.say("(if `showtime doctor --json` reports browser launch: fail)")
        r.run(["sudo", "-n", "node", str(showtime_home(r.env) / "node" / "node_modules" / "playwright" / "cli.js"),
               "install-deps", "chromium"])
        return
    cp = subprocess.run(r.st + ["doctor", "--json"], env=r.child_env, stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL, universal_newlines=True, encoding="utf-8", errors="replace")
    rows = parse_json_tail(cp.stdout or "").get("checks", [])
    launch = next((x for x in rows if x.get("check") == "browser launch"), {})
    if launch.get("status") != "fail":
        r.say("browser system libraries: not needed (browser launch: %s)" % launch.get("status", "unknown"))
        return
    cli = showtime_home(r.env) / "node" / "node_modules" / "playwright" / "cli.js"
    r.run(["sudo", "-n", shutil.which("node") or "node", str(cli), "install-deps", "chromium"])


def cmd_run(env: Dict[str, str], dry_run: bool) -> int:
    mode = get_input(env, "mode", "release")
    if mode not in MODES:
        raise ActionError("mode must be one of %s (got %r)" % (", ".join(MODES), mode))
    r = Runner(env, dry_run)
    res = Result()
    t0 = time.time()
    print("showtime-video: mode=%s work=%s" % (mode, r.work), flush=True)
    code = 0
    try:
        {"release": do_release, "project": do_project, "agent": do_agent}[mode](r, res)
    except ActionError as e:
        res.error = str(e)
        code = 1
    finally:
        if not dry_run:
            if not res.job and r.work.is_dir():
                nj = newest_job(r.work)
                if nj is not None:
                    res.job = str(nj)
            if res.job:
                collect(res, Path(res.job))  # whatever exists now, also after a failure
                stage(res, r.work)
            for k, v in res.outputs().items():
                write_output(env, k, v)
            write_summary(env, summary_markdown(res, mode, time.time() - t0))
    if res.error:
        sys.stderr.write("showtime-video: %s\n" % res.error)
        if env.get("GITHUB_ACTIONS") == "true":
            print("::error title=showtime-video::%s" % res.error.replace("\n", " "))
    if code == 0 and not dry_run:
        print("video: %s\nhtml: %s\nposter: %s\nqa: %s %s\njob: %s" % (
            res.video, res.html or "-", res.poster or "-", res.qa or "-", res.qa_detail, res.job))
    if code == 0 and dry_run:
        print("dry run: nothing was run or written (%d commands)" % len(r.commands))
    return code


def summary_markdown(res: Result, mode: str, seconds: float) -> str:
    lines = ["### showtime-video (%s mode)" % mode, ""]
    if res.error:
        lines.append("**Failed:** %s" % res.error)
        lines.append("")
    if res.qa:
        lines.append("- qa: **%s**%s" % (res.qa, " (%s)" % res.qa_detail if res.qa_detail else ""))
    for label, path in (("video", res.video), ("vertical 9:16", res.vertical), ("html video", res.html),
                        ("poster", res.poster)):
        if path and Path(path).is_file():
            lines.append("- %s: `%s` (%.1f MB)" % (label, Path(path).name, Path(path).stat().st_size / 1e6))
    lines.append("- time: %.0f s" % seconds)
    return "\n".join(lines) + "\n"


def cmd_upload(env: Dict[str, str], dry_run: bool) -> int:
    files = [f for f in (get_input(env, "upload-files") or "").splitlines() if f.strip()]
    if not files:
        raise ActionError("nothing to upload: the run produced no files")
    tag = get_input(env, "release-tag")
    if not tag:
        ev = read_event(env)
        rel = ev.get("release") if isinstance(ev.get("release"), dict) else {}
        tag = str(rel.get("tag_name") or "")
    if not tag:
        raise ActionError("upload: release needs a tag: run on a release event or set the input 'release-tag'")
    if not dry_run and not get_input(env, "github-token"):
        raise ActionError("upload: release needs the github-token input (and `permissions: contents: write`)")
    # what goes up is what the run staged: the video files, the HTML video, the poster, the qa report and
    # share.txt / credits.txt when they exist; nothing else leaves the runner
    wanted = [f for f in files if Path(f).is_file() or dry_run]
    r = Runner(env, dry_run)
    cmd = ["gh", "release", "upload", tag] + wanted + ["--clobber"]
    r.run(cmd, env_extra={"GH_TOKEN": get_input(env, "github-token")}, shown=quote(cmd))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], epilog=__doc__.split("\n\n", 1)[1],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="run", choices=["prepare", "setup", "run", "upload"])
    ap.add_argument("--dry-run", action="store_true",
                    help="print the commands and the resolved notes, title and version; run nothing, write nothing")
    a = ap.parse_args(argv)
    env = dict(os.environ)
    try:
        return {"prepare": cmd_prepare, "setup": cmd_setup, "run": cmd_run, "upload": cmd_upload}[a.command](
            env, a.dry_run)
    except ActionError as e:
        sys.stderr.write("showtime-video: %s\n" % e)
        if env.get("GITHUB_ACTIONS") == "true":
            print("::error title=showtime-video::%s" % str(e).replace("\n", " "))
        return 1


def _indent(text: str) -> str:
    return "\n".join("    " + line for line in text.splitlines())


if __name__ == "__main__":
    sys.exit(main())

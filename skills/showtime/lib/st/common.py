"""Shared helpers for every showtime module.

Stdlib only and Python 3.8+ compatible (the doctor and launcher import it
before the virtualenv exists). Provides:

- paths:   home(), skill_dir(), paths(), venv_python(), node_modules()
- logging: log(), info(), warn(), error(), debug(), get_logger()
- process: run() with argument lists only, RunError with a stderr tail
- json:    read_json(), write_json() (atomic), print_json()
- output:  slugify(), timestamp(), output_dir()
- misc:    ShowtimeError, sha256_file(), human_size(), ensure_dir()
- ux:      use_color(), paint(), Progress (n/N, rate, ETA), estimate(),
           fmt_duration(), extra_installed(), require_extra(), debug_enabled()
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Union

from . import platform as plat

PathLike = Union[str, "os.PathLike[str]"]

__all__ = [
    "ShowtimeError", "RunError", "home", "skill_dir", "paths", "venv_python",
    "node_modules", "ensure_dir", "log", "info", "warn", "error", "debug",
    "get_logger", "run", "read_json", "write_json", "print_json", "slugify",
    "timestamp", "output_dir", "sha256_file", "human_size", "which", "portable_path", "resolve_portable",
    "use_color", "paint", "Progress", "estimate", "fmt_duration", "extra_info", "extra_installed",
    "require_extra", "debug_enabled",
]


class ShowtimeError(Exception):
    """A user-facing error: the CLI prints it without a traceback.

    message = what went wrong, why = the cause (optional), hint = the exact
    fix (a command when possible). The CLI prints:

        error: <message>
          why: <why>
          fix: <hint>
    """

    def __init__(self, message: str, hint: Optional[str] = None, code: int = 1, why: Optional[str] = None):
        super().__init__(message)
        self.hint = hint
        self.code = code
        self.why = why

    @property
    def message(self) -> str:
        return super().__str__()

    def __str__(self) -> str:  # pragma: no cover - trivial
        msg = super().__str__()
        if self.why:
            msg += "\n  why: " + self.why
        return msg + ("\n  hint: " + self.hint if self.hint else "")

    def format(self, color: bool = False) -> str:
        """The what / why / fix block (without the leading 'error: ')."""
        lines = [self.message]
        if self.why:
            lines.append("  %s %s" % (paint("why:", "dim", force=color), self.why))
        if self.hint:
            lines.append("  %s %s" % (paint("fix:", "green", force=color), self.hint))
        return "\n".join(lines)


class RunError(ShowtimeError):
    """A subprocess failed. Carries the command, exit code and output tail."""

    def __init__(self, cmd: Sequence[str], returncode: int, stderr: str = "", stdout: str = ""):
        self.cmd = [str(c) for c in cmd]
        self.returncode = returncode
        self.stderr = stderr or ""
        self.stdout = stdout or ""
        tail = "\n".join((self.stderr or self.stdout).strip().splitlines()[-15:])
        name = Path(self.cmd[0]).name if self.cmd else "?"
        msg = "%s exited with code %s" % (name, returncode)
        if tail:
            msg += ":\n" + "\n".join("    " + line for line in tail.splitlines())
        super().__init__(msg)


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

def home() -> Path:
    """Runtime home (~/.showtime, overridable with SHOWTIME_HOME)."""
    env = os.environ.get("SHOWTIME_HOME")
    if env:
        return Path(os.path.expanduser(env))
    return plat.user_home() / ".showtime"


def skill_dir() -> Path:
    """The skill directory (…/skills/showtime), overridable with SHOWTIME_SKILL."""
    env = os.environ.get("SHOWTIME_SKILL")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def paths() -> Dict[str, Path]:
    """Every well-known location, keyed by short name."""
    h = home()
    s = skill_dir()
    m = h / "models"
    a = h / "assets"
    return {
        "home": h,
        "skill": s,
        "bin": h / "bin",
        "venv": h / "venv",
        "venv_python": plat.venv_python(h / "venv"),
        "node": h / "node",
        "node_modules": h / "node" / "node_modules",
        "browsers": h / "browsers",
        "models": m,
        "hf": m / "hf",
        "whisper": m / "whisper",
        "kokoro": m / "kokoro",
        "sherpa": m / "sherpa",
        "supertonic": m / "supertonic3",
        "arnndn": m / "arnndn",
        "yunet": m / "yunet",
        "luts": m / "luts",
        "soundfonts": h / "soundfonts",
        "library": h / "library",
        "assets": a,
        "fonts": a / "fonts",
        "icons": a / "icons",
        "emoji": a / "emoji",
        "media": a / "media",
        "cache": h / "cache",
        "downloads": h / "cache" / "downloads",
        "state": h / "state.json",
        "templates": Path(os.environ["SHOWTIME_TEMPLATES"]) if os.environ.get("SHOWTIME_TEMPLATES") else s / "templates",
        "scripts": s / "scripts",
        "runtime": s / "runtime",
        "setup": s / "setup",
    }


def venv_python() -> Path:
    return plat.venv_python(home() / "venv")


def node_modules() -> Path:
    return home() / "node" / "node_modules"


def ensure_dir(p: PathLike) -> Path:
    path = Path(p)
    path.mkdir(parents=True, exist_ok=True)
    return path


def which(name: str) -> Optional[str]:
    """Find an executable, looking in ~/.showtime/bin first."""
    return plat.which(name, [home() / "bin"])


# --------------------------------------------------------------------------
# Logging (stderr; stdout stays clean for JSON output)
# --------------------------------------------------------------------------

_LOG_LEVEL = os.environ.get("SHOWTIME_LOG", "info").lower()
_LEVELS = {"debug": 10, "info": 20, "warn": 30, "warning": 30, "error": 40, "quiet": 50}


_STYLES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "blue": "34",
           "magenta": "35", "cyan": "36", "bold_cyan": "1;36"}
_VT_READY: Dict[int, bool] = {}


def _enable_windows_vt(stream: Any) -> bool:
    """Turn on ANSI escape handling for a Windows 10+ console (best effort)."""
    if os.name != "nt":
        return True
    key = id(stream)
    if key in _VT_READY:
        return _VT_READY[key]
    ok = False
    try:
        import ctypes  # noqa: PLC0415
        import msvcrt  # noqa: PLC0415
        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = ctypes.c_uint32()
        k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        if k32.GetConsoleMode(handle, ctypes.byref(mode)):
            ok = bool(k32.SetConsoleMode(handle, mode.value | 0x0004))  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:  # noqa: BLE001
        ok = False
    _VT_READY[key] = ok
    return ok


def is_terminal(stream: Any = None) -> bool:
    """True when `stream` (default stdin) is an interactive terminal. On Windows `isatty()` is also
    true for the NUL device (what hosts pass as an empty stdin), so a console is confirmed with
    GetConsoleMode: a prompt must never wait on, or read an empty answer from, NUL."""
    stream = stream if stream is not None else sys.stdin
    try:
        if stream is None or not stream.isatty():
            return False
    except (AttributeError, ValueError, OSError):
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes  # noqa: PLC0415
        import msvcrt  # noqa: PLC0415
        mode = ctypes.c_uint32()
        return bool(ctypes.windll.kernel32.GetConsoleMode(  # type: ignore[attr-defined]
            msvcrt.get_osfhandle(stream.fileno()), ctypes.byref(mode)))
    except Exception:  # noqa: BLE001
        return False


def brief_output(verbose: bool = False, stream: Any = None) -> bool:
    """Lean mode: print a short summary (paths + verdict) instead of the full report?

    On by default when nobody watches a terminal (agents, pipes, the MCP server); a terminal keeps the full
    report. `verbose` (a command's --verbose), SHOWTIME_VERBOSE=1 or SHOWTIME_OUTPUT=full turn it off;
    SHOWTIME_OUTPUT=brief turns it on.
    """
    mode = os.environ.get("SHOWTIME_OUTPUT", "").lower()
    if verbose or os.environ.get("SHOWTIME_VERBOSE") == "1" or mode in ("full", "verbose"):
        return False
    if mode == "brief":
        return True
    stream = stream if stream is not None else sys.stdout
    try:
        tty = stream.isatty()
    except (AttributeError, ValueError):
        tty = False
    return os.environ.get("SHOWTIME_MCP") == "1" or not tty


def use_color(stream: Any = None) -> bool:
    """True when colored output should go to `stream` (default stderr).

    Off when the stream is not a TTY, NO_COLOR is set, TERM=dumb or
    SHOWTIME_COLOR=never; forced on with SHOWTIME_COLOR=always / FORCE_COLOR.
    """
    stream = stream if stream is not None else sys.stderr
    mode = os.environ.get("SHOWTIME_COLOR", "auto").lower()
    if mode in ("never", "no", "off", "0"):
        return False
    if mode in ("always", "yes", "on", "1") or os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError, OSError):
        return False
    return _enable_windows_vt(stream)


def paint(text: str, style: str, stream: Any = None, force: Optional[bool] = None) -> str:
    """Wrap text in an ANSI style (bold, dim, red, green, yellow, cyan...) when color is on."""
    on = use_color(stream) if force is None else force
    code = _STYLES.get(style, style)
    return "\033[%sm%s\033[0m" % (code, text) if on and code else text


def _color(code: str, text: str) -> str:
    return paint(text, code)


def debug_enabled() -> bool:
    return os.environ.get("SHOWTIME_DEBUG") == "1" or _LOG_LEVEL == "debug"


def _emit(level: str, msg: str) -> None:
    if _LEVELS.get(level, 20) < _LEVELS.get(_LOG_LEVEL, 20):
        return
    prefix = {"debug": _color("2", "debug"), "info": _color("36", "showtime"),
              "warn": _color("33", "warning"), "error": _color("31", "error")}[level]
    try:
        print("%s: %s" % (prefix, msg), file=sys.stderr, flush=True)
    except UnicodeEncodeError:  # legacy Windows consoles
        print(("%s: %s" % (prefix, msg)).encode("ascii", "replace").decode(), file=sys.stderr)


def log(msg: str) -> None:
    _emit("info", msg)


info = log


def warn(msg: str) -> None:
    _emit("warn", msg)


def error(msg: str) -> None:
    _emit("error", msg)


def debug(msg: str) -> None:
    _emit("debug", msg)


def get_logger(name: str = "showtime") -> logging.Logger:
    """A stdlib logger writing concise lines to stderr (level from SHOWTIME_LOG)."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(name)s: %(levelname)s: %(message)s"))
        logger.addHandler(h)
        logger.setLevel(_LEVELS.get(_LOG_LEVEL, 20))
        logger.propagate = False
    return logger


# --------------------------------------------------------------------------
# Subprocess
# --------------------------------------------------------------------------

def run(args: Sequence[Union[str, PathLike]], *, check: bool = True, capture: bool = True,
        cwd: Optional[PathLike] = None, env: Optional[Mapping[str, str]] = None,
        timeout: Optional[float] = None, input: Optional[Union[str, bytes]] = None,
        text: bool = True, quiet: bool = False) -> subprocess.CompletedProcess:
    """Run a command given as an argument list (never a shell string).

    capture=True collects stdout/stderr; on failure (check=True) a RunError
    with the last lines of stderr is raised. `env` entries are merged over
    os.environ. Path objects are converted to str.
    """
    if isinstance(args, (str, bytes)):
        raise TypeError("run() takes an argument list, not a shell string")
    argv = [os.fspath(a) for a in args]
    full_env = None
    if env is not None:
        full_env = dict(os.environ)
        full_env.update({k: str(v) for k, v in env.items()})
    if not quiet:
        debug("run: " + " ".join(_q(a) for a in argv))
    kwargs: Dict[str, Any] = {}
    if text:
        kwargs.update(encoding="utf-8", errors="replace")
    try:
        cp = subprocess.run(
            argv, cwd=os.fspath(cwd) if cwd else None, env=full_env, timeout=timeout,
            input=input,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            **kwargs)
    except FileNotFoundError:
        raise ShowtimeError("command not found: %s" % argv[0],
                            hint="run `showtime doctor` to check your installation")
    except subprocess.TimeoutExpired as e:
        raise ShowtimeError("command timed out after %ss: %s" % (timeout, Path(argv[0]).name)) from e
    if check and cp.returncode != 0:
        raise RunError(argv, cp.returncode, cp.stderr if capture else "", cp.stdout if capture else "")
    return cp


def _q(a: str) -> str:
    return a if re.match(r"^[\w@%+=:,./\\-]+$", a) else '"%s"' % a.replace('"', '\\"')


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------

def read_json(path: PathLike, default: Any = None) -> Any:
    """Load JSON (UTF-8, with or without the byte-order mark that Windows PowerShell 5.1 and some
    Windows editors write). Returns `default` if the file is missing and a default was given; raises
    ShowtimeError on malformed JSON."""
    p = Path(path)
    if not p.exists():
        if default is not None:
            return default
        raise ShowtimeError("file not found: %s" % p)
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        raise ShowtimeError("invalid JSON in %s: %s" % (p, e)) from e


def _file_mode() -> int:
    """The mode a plain new file gets (0666 minus the umask): mkstemp's 0600 would otherwise stick."""
    old = os.umask(0)
    os.umask(old)
    return 0o666 & ~old


def write_json(path: PathLike, data: Any, indent: int = 2) -> Path:
    """Write JSON atomically (temp file + replace), UTF-8, trailing newline, normal file permissions."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".%s." % p.name, dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False, default=_json_default)
            f.write("\n")
        try:
            os.chmod(tmp, _file_mode())
        except OSError:
            pass
        os.replace(tmp, str(p))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def part_path(path: PathLike) -> Path:
    """A temporary sibling for writing `path` and then os.replace-ing it into place.

    The name is unique per process and call (pid + random), so two renders filling the same shared
    cache entry at once never write into, or rename away, each other's temp file. The extension is
    kept last so tools that infer the format from it (ffmpeg, soundfile) still work."""
    import uuid
    p = Path(path)
    return p.with_name(".%s.%d-%s.part%s" % (p.stem, os.getpid(), uuid.uuid4().hex[:8], p.suffix))


@contextlib.contextmanager
def cache_lock(path: PathLike, timeout: float = 600.0, stale: float = 3600.0) -> Iterator[bool]:
    """Hold `<path>.lock` while one process fills a shared cache entry (a composed bed, a synth hit).

    Others wait (up to `timeout` s) and then find the finished entry instead of computing it again.
    Cross-platform (O_CREAT|O_EXCL on a lock file). A lock older than `stale` s is left over from a
    killed process and is taken over. After the timeout the caller proceeds without the lock: writes
    are atomic (part_path + os.replace), so the worst case is duplicate work, never a broken file.
    Yields True when the lock was acquired."""
    lock = Path(str(path) + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    got = False
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, ("%d\n" % os.getpid()).encode("ascii"))
            os.close(fd)
            got = True
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale:
                    lock.unlink()
                    continue
            except OSError:
                continue
            if time.time() - t0 > timeout:
                debug("cache lock %s still held after %.0fs; continuing without it" % (lock, timeout))
                break
            time.sleep(0.2)
        except OSError as e:          # read-only or odd file system: no locking, writes stay atomic
            debug("cache lock %s: %s" % (lock, e))
            break
    try:
        yield got
    finally:
        if got:
            try:
                lock.unlink()
            except OSError:
                pass


def _json_default(o: Any) -> Any:
    if isinstance(o, Path):
        return str(o)
    if hasattr(o, "tolist"):
        return o.tolist()
    if hasattr(o, "__dict__"):
        return o.__dict__
    raise TypeError("not JSON serializable: %r" % type(o))


def print_json(data: Any) -> None:
    """Print JSON to stdout (for --json outputs)."""
    sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False, default=_json_default) + "\n")
    sys.stdout.flush()


# --------------------------------------------------------------------------
# Output folders
# --------------------------------------------------------------------------

def slugify(text: str, max_len: int = 48, default: str = "video") -> str:
    """ASCII, lowercase, dash-separated slug safe on every filesystem."""
    t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^a-zA-Z0-9]+", "-", t).strip("-").lower()
    t = t[:max_len].strip("-")
    return t or default


def timestamp(t: Optional[float] = None) -> str:
    """Local time as YYYYMMDD-HHMMSS."""
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(t))


def output_dir(name: str, base: Optional[PathLike] = None, create: bool = True) -> Path:
    """A fresh output folder: <base>/showtime-out/<slug>-YYYYMMDD-HHMMSS/.

    base defaults to $SHOWTIME_OUT or the current directory. A numeric
    suffix is added if the folder already exists (two runs in one second).
    """
    root = Path(base) if base else Path(os.environ.get("SHOWTIME_OUT") or Path.cwd())
    if root.name != "showtime-out":
        root = root / "showtime-out"
    stem = "%s-%s" % (slugify(name), timestamp())
    d = root / stem
    n = 2
    while d.exists():
        d = root / ("%s-%d" % (stem, n))
        n += 1
    if create:
        d.mkdir(parents=True, exist_ok=False)
    return d


# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------

def sha256_file(path: PathLike, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def portable_path(target: PathLike, base: PathLike) -> str:
    """A path to write into a sidecar that may be shared or published: relative to `base` (forward
    slashes), `showtime:<path>` for files inside the skill, else the file name alone. Never an
    absolute home, temp or scratch path."""
    t = Path(target).expanduser().resolve()
    try:
        return "showtime:" + t.relative_to(skill_dir().resolve()).as_posix()
    except (ValueError, OSError):
        pass
    try:  # the runtime home (~/.showtime: library, models, cache)
        return "showtime-home:" + t.relative_to(home().resolve()).as_posix()
    except (ValueError, OSError):
        pass
    try:
        return Path(os.path.relpath(str(t), str(Path(base).expanduser().resolve()))).as_posix()
    except ValueError:  # another drive on Windows
        return t.name


def resolve_portable(value: Optional[str], base: PathLike) -> Optional[Path]:
    """Inverse of portable_path: an absolute Path for a sidecar's (possibly relative) path."""
    if not value:
        return None
    if value.startswith("showtime:"):
        return skill_dir() / value[len("showtime:"):]
    if value.startswith("showtime-home:"):
        return home() / value[len("showtime-home:"):]
    p = Path(value).expanduser()
    return p if p.is_absolute() else (Path(base) / p).resolve()


def human_size(n: Optional[float]) -> str:
    """Decimal units (1 MB = 1,000,000 bytes), the unit platform upload limits use."""
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1000 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1000.0
    return "%.1f TB" % n


def parse_time(value: Union[str, float, int]) -> float:
    """Parse '12.5', '1:02.5', '00:01:02.5' or '250ms' into seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().lower()
    try:
        if s.endswith("ms"):
            return float(s[:-2]) / 1000.0
        if s.endswith("s"):
            return float(s[:-1])
        parts = [float(x) for x in s.split(":")]
    except ValueError:
        raise ShowtimeError("invalid time value: %r (use seconds, mm:ss or hh:mm:ss)" % value)
    total = 0.0
    for part in parts:
        total = total * 60 + part
    return total


def iter_files(root: PathLike, patterns: Iterable[str]) -> List[Path]:
    r = Path(root)
    out: List[Path] = []
    for pat in patterns:
        out.extend(sorted(r.glob(pat)))
    return out


# --------------------------------------------------------------------------
# Progress, ETA and time estimates
# --------------------------------------------------------------------------

def fmt_duration(seconds: Optional[float]) -> str:
    """12.3 -> '12 s', 95 -> '1:35', 4000 -> '1:06:40'; None -> '?'."""
    if seconds is None or seconds != seconds or seconds < 0:
        return "?"
    s = int(round(seconds))
    if s < 60:
        return "%d s" % s
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return ("%d:%02d:%02d" % (h, m, sec)) if h else ("%d:%02d" % (m, sec))


def estimate(label: str, seconds: Optional[float], threshold: float = 30.0) -> None:
    """Announce a time estimate before a long step (only when > threshold s).

    Example: estimate("rendering 900 frames", 900 / 25) prints
    `showtime: rendering 900 frames: about 36 s`.
    """
    if seconds is None or seconds <= threshold:
        return
    if os.environ.get("SHOWTIME_PROGRESS", "").lower() == "json":
        _progress_json({"estimate": label, "seconds": round(float(seconds), 1)})
        return
    approx = seconds if seconds < 120 else round(seconds / 60.0) * 60
    log("%s: about %s" % (label, fmt_duration(approx)))


def _progress_json(obj: Dict[str, Any]) -> None:
    try:
        sys.stderr.write(json.dumps(obj) + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


# Progress log: long commands append one JSON line per milestone (start, every 10%, end)
# to <home>/logs/progress.jsonl, the same file the Node scripts write. The optional
# plugin monitor (mcp/progress-monitor.mjs) tails it. SHOWTIME_PROGRESS_LOG=0 turns it off.
_PLOG: Dict[str, Any] = {"started": False, "t0": 0.0, "cmd": "showtime", "ended": False}


def _plog_write(obj: Dict[str, Any]) -> None:
    try:
        d = home() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        f = d / "progress.jsonl"
        if not _PLOG["started"]:
            try:
                if f.stat().st_size > 1024 * 1024:
                    os.replace(str(f), str(f) + ".1")
            except OSError:
                pass
        rec = {"ts": int(time.time() * 1000), "pid": os.getpid(), "cmd": _PLOG["cmd"], "cwd": os.getcwd()}
        rec.update(obj)
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")
    except (OSError, ValueError):
        pass


def progress_log(event: Dict[str, Any]) -> None:
    """Record a progress milestone; the first one also records the start."""
    if os.environ.get("SHOWTIME_PROGRESS_LOG", "").lower() in ("0", "off", "false", "no"):
        return
    if not _PLOG["started"]:
        _plog_write({"ev": "start"})
        _PLOG["started"] = True
        _PLOG["t0"] = time.time()
    _plog_write(event)


def progress_log_command(argv: Sequence[str]) -> None:
    """Name the running command for the progress log (e.g. `showtime audio compose`)."""
    words = []
    for a in list(argv)[:2]:
        if not re.match(r"^[a-z][a-z0-9-]*$", a):
            break
        words.append(a)
    _PLOG["cmd"] = " ".join(["showtime"] + words)


def progress_log_end(code: int, error_text: Optional[str] = None) -> None:
    """Record the end of a command that logged progress (no-op otherwise)."""
    if not _PLOG["started"] or _PLOG["ended"]:
        return
    _PLOG["ended"] = True
    ev: Dict[str, Any] = {"ev": "end", "code": int(code), "seconds": round(time.time() - _PLOG["t0"], 1)}
    if error_text and code:
        ev["error"] = error_text.splitlines()[0][:300] if error_text else ""
    _plog_write(ev)


class Progress:
    """Progress with rate and ETA on stderr, for any long loop.

        with Progress(total=450, label="frames", unit="fps") as pr:
            for i in range(450):
                ...
                pr.update()          # or pr.set(done)

    TTY: one line redrawn in place (at most 10 times a second), e.g.
    `frames 120/450  27%  26.7 fps  ETA 12 s`. Not a TTY (logs, an agent's
    tool output): one plain line every `every` seconds and a final line.
    SHOWTIME_PROGRESS=json prints one JSON object per update line instead;
    SHOWTIME_PROGRESS=off silences it. `unit` names the rate ("fps",
    "files/s"); total=None gives a counter without ETA.
    """

    def __init__(self, total: Optional[float], label: str = "progress", unit: str = "/s",
                 every: float = 5.0, stream: Any = None, enabled: bool = True) -> None:
        self.total = float(total) if total else None
        self.label = label
        self.unit = unit
        self.every = every
        self.stream = stream if stream is not None else sys.stderr
        mode = os.environ.get("SHOWTIME_PROGRESS", "auto").lower()
        self.mode = "off" if (not enabled or mode == "off" or _LEVELS.get(_LOG_LEVEL, 20) > 20) else mode
        try:
            self.tty = self.mode == "auto" and self.stream.isatty()
        except (AttributeError, ValueError, OSError):
            self.tty = False
        self.done = 0.0
        self.t0 = time.time()
        self._last = 0.0
        self._closed = False
        self._final_done = False
        self._width = 0
        self._log_pct = -1
        if self.total:
            progress_log({"ev": "progress", "label": label, "done": 0, "total": self.total, "pct": 0})

    def __enter__(self) -> "Progress":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close(ok=exc_type is None)

    # -- numbers
    @property
    def elapsed(self) -> float:
        return time.time() - self.t0

    @property
    def rate(self) -> Optional[float]:
        el = self.elapsed
        return (self.done / el) if el > 0.05 and self.done > 0 else None

    @property
    def eta(self) -> Optional[float]:
        r = self.rate
        if not self.total or not r:
            return None
        return max(0.0, (self.total - self.done) / r)

    def text(self) -> str:
        parts = [self.label]
        if self.total:
            parts.append("%d/%d" % (self.done, self.total))
            parts.append("%d%%" % int(100 * self.done / self.total))
        else:
            parts.append("%d" % self.done)
        r = self.rate
        if r is not None:
            parts.append(("%.1f %s" % (r, self.unit)) if self.unit != "/s" else "%.1f/s" % r)
        if self.eta is not None and self.done < (self.total or 0):
            parts.append("ETA %s" % fmt_duration(self.eta))
        return "  ".join(parts)

    # -- updates
    def update(self, n: float = 1) -> None:
        self.set(self.done + n)

    def set(self, done: float) -> None:
        self.done = float(done)
        if self.total:
            pct = int(100 * self.done / self.total)
            if pct >= self._log_pct + 10 or (pct >= 100 and self._log_pct < 100):
                self._log_pct = 100 if pct >= 100 else pct - pct % 10
                ev = {"ev": "progress", "label": self.label, "done": self.done, "total": self.total, "pct": pct}
                if self.eta is not None:
                    ev["eta_s"] = round(self.eta)
                progress_log(ev)
        if self.mode == "off":
            return
        now = time.time()
        interval = 0.1 if self.tty else self.every
        finished = bool(self.total) and self.done >= (self.total or 0)
        if now - self._last < interval and not finished:
            return
        self._last = now
        self._emit(final=finished)

    def _emit(self, final: bool = False) -> None:
        if final:
            if self._final_done:
                return
            self._final_done = True
        if self.mode == "json":
            _progress_json({"progress": self.label, "done": self.done, "total": self.total,
                            "rate": round(self.rate, 3) if self.rate else None,
                            "eta": round(self.eta, 1) if self.eta is not None else None,
                            "elapsed": round(self.elapsed, 1), "final": final})
            return
        line = self.text()
        try:
            if self.tty:
                pad = max(0, self._width - len(line))
                self.stream.write("\r" + paint(line, "cyan", self.stream) + " " * pad + ("\n" if final else ""))
                self._width = len(line)
            else:
                self.stream.write("%s: %s\n" % (paint("showtime", "cyan", self.stream), line))
            self.stream.flush()
        except (OSError, ValueError, UnicodeEncodeError):
            pass

    def close(self, ok: bool = True, message: Optional[str] = None) -> None:
        if self._closed:
            return
        self._closed = True
        if self.mode == "off":
            return
        if message:
            self.label = message
            self._final_done = False
        if ok or self.done:
            self._emit(final=True)
        elif self.tty:
            try:
                self.stream.write("\n")
            except (OSError, ValueError):
                pass


# --------------------------------------------------------------------------
# Optional extras (lazy install)
# --------------------------------------------------------------------------

def extra_info(name: str) -> Dict[str, Any]:
    """Manifest facts about an optional extra: description, download_bytes, installed."""
    try:
        man = json.loads((skill_dir() / "setup" / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        man = {}
    ex = (man.get("extras") or {}).get(name)
    if ex is None:
        return {"name": name, "known": False, "description": "", "download_bytes": 0, "installed": False}
    key = plat.platform_key()
    size = 0
    for it in man.get("items", []):
        if it.get("extra") != name:
            continue
        files = plat.pick_for_platform(it["platform_files"], key) if "platform_files" in it else it.get("files", [])
        size += sum(int(f.get("size") or 0) for f in (files or []))
    return {"name": name, "known": True, "description": ex.get("description", ""),
            "download_bytes": size or int(ex.get("approx_bytes") or 0), "pip": ex.get("pip", []),
            "lazy": bool(ex.get("lazy")), "auto": bool(ex.get("auto")), "installed": extra_installed(name)}


def extra_installed(name: str) -> bool:
    """True when `showtime setup --with <name>` (or the full tier) installed this extra."""
    try:
        st = json.loads(paths()["state"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return name in ((st.get("installed") or {}).get("extras") or [])


def require_extra(name: str, feature: str, available: Optional[bool] = None, install: Optional[bool] = None) -> None:
    """Make sure optional extra `name` is present before `feature` runs.

    available: result of the caller's own check (e.g. an import or model
    file test); when None, the setup state decides. When it is missing:
      - an extra marked "auto" in the manifest (Manim, ManimGL) is fetched
        now, announced with its size (`showtime setup --fetch <name>`);
        offline, the error names `setup --full` / `--seed`;
      - install=True (or SHOWTIME_AUTO_INSTALL=1): print a one-line notice
        with the download size and run `showtime setup --with <name>`;
      - otherwise raise a ShowtimeError whose fix is that exact command
        (nothing big is ever installed without a notice).
    """
    info = extra_info(name)
    if available is None and info.get("lazy"):
        return   # fetched by its own module on first use (with its own notice)
    ok = extra_installed(name) if available is None else bool(available)
    if ok:
        return
    if info.get("auto") and install is not False:
        from . import lazy
        lazy.ensure_extra(name, feature)
        return
    size = (" (about %s download)" % human_size(info["download_bytes"])) if info.get("download_bytes") else ""
    cmd = "showtime setup --with %s" % name
    auto = install if install is not None else os.environ.get("SHOWTIME_AUTO_INSTALL") == "1"
    if auto:
        log("%s needs the optional '%s' extra%s; installing it now: %s" % (feature, name, size, cmd))
        base = getattr(sys, "_base_executable", None) or sys.executable
        rc = subprocess.call([base, str(skill_dir() / "setup" / "setup.py"), "--with", name])
        if rc != 0:
            raise ShowtimeError("installing the '%s' extra failed (exit %d)" % (name, rc),
                                hint="run `%s` yourself to see the details, then `showtime doctor`" % cmd)
        return
    raise ShowtimeError("%s needs the optional '%s' extra, which is not installed" % (feature, name),
                        why=(info.get("description") or "it is not part of the default install") + size,
                        hint="%s   (or set SHOWTIME_AUTO_INSTALL=1 to install extras on first use)" % cmd,
                        code=3)

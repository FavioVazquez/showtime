"""Operating-system and architecture helpers for showtime.

Stdlib only and Python 3.8+ compatible: the launcher, the installer and the
doctor import this module before the showtime virtualenv exists.

Everything that differs between macOS, Windows and Linux lives here:
platform keys, executable suffixes, browser discovery, opening files,
Chrome GPU flag sets and ffmpeg filter-argument escaping.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path, PurePath, PureWindowsPath
from typing import Dict, Iterable, List, Optional, Union

PathLike = Union[str, "os.PathLike[str]"]

IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")


# --------------------------------------------------------------------------
# OS / architecture
# --------------------------------------------------------------------------

def os_name() -> str:
    """Return 'mac', 'windows' or 'linux' (other Unixes report 'linux')."""
    if IS_MAC:
        return "mac"
    if IS_WINDOWS:
        return "windows"
    return "linux"


def _machine() -> str:
    # sysconfig/platform.machine() would do; avoid importing the stdlib
    # `platform` module under a name clash when this file is run oddly.
    m = ""
    try:
        m = os.uname().machine  # type: ignore[attr-defined]
    except AttributeError:
        m = os.environ.get("PROCESSOR_ARCHITEW6432") or os.environ.get("PROCESSOR_ARCHITECTURE", "")
    return (m or sysconfig.get_platform().split("-")[-1]).lower()


def _mac_is_translated() -> bool:
    """True when this (x86_64) process runs under Rosetta on Apple Silicon."""
    if not IS_MAC:
        return False
    try:
        out = subprocess.run(["sysctl", "-n", "sysctl.proc_translated"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() == "1"
    except (OSError, subprocess.SubprocessError):
        return False


def arch() -> str:
    """Hardware architecture: 'arm64' or 'x64' (others returned verbatim).

    On an Apple Silicon Mac this reports 'arm64' even when the current
    Python runs under Rosetta, so native binaries get installed.
    """
    m = _machine()
    if m in ("arm64", "aarch64", "armv8l", "arm64e"):
        return "arm64"
    if m in ("x86_64", "amd64", "x64", "i686-64"):
        if _mac_is_translated():
            return "arm64"
        return "x64"
    return m


def platform_key() -> str:
    """'mac-arm64', 'mac-x64', 'win-x64', 'win-arm64', 'linux-x64', 'linux-arm64'."""
    o = {"mac": "mac", "windows": "win", "linux": "linux"}[os_name()]
    return "%s-%s" % (o, arch())


def exe(name: str) -> str:
    """Append '.exe' on Windows (idempotent)."""
    if IS_WINDOWS and not name.lower().endswith(".exe"):
        return name + ".exe"
    return name


def venv_python(venv_dir: PathLike) -> Path:
    """Path of the interpreter inside a virtualenv on this OS."""
    v = Path(venv_dir)
    if IS_WINDOWS:
        return v / "Scripts" / "python.exe"
    return v / "bin" / "python"


def venv_bin(venv_dir: PathLike) -> Path:
    v = Path(venv_dir)
    return v / ("Scripts" if IS_WINDOWS else "bin")


def which(name: str, extra_dirs: Iterable[PathLike] = ()) -> Optional[str]:
    """shutil.which that first looks in `extra_dirs` (handles .exe/.cmd)."""
    for d in extra_dirs:
        d = Path(d)
        for cand in (d / name, d / exe(name)):
            if cand.is_file() and os.access(str(cand), os.X_OK):
                return str(cand)
    return shutil.which(name)


def user_home() -> Path:
    return Path(os.path.expanduser("~"))


def _version_key(name: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", name)[:3])


def default_tool_dirs(name: str) -> List[Path]:
    """Folders the official installers put `uv` / `node` in, for when they are not on PATH yet.

    Installing uv or Node.js updates PATH for new terminals only: an app that was already open
    (Claude Code, an editor) keeps the old PATH until it restarts. Looking in the default install
    folders makes a fresh install work at once. Existing folders only, most likely first."""
    h = user_home()
    env = os.environ
    local = Path(env["LOCALAPPDATA"]) if env.get("LOCALAPPDATA") else h / "AppData" / "Local"
    roaming = Path(env["APPDATA"]) if env.get("APPDATA") else h / "AppData" / "Roaming"
    cands: List[Path] = []
    if name == "uv":
        # the uv installer (XDG_BIN_HOME, then ~/.local/bin; ~/.cargo/bin for older installs), winget
        if env.get("XDG_BIN_HOME"):
            cands.append(Path(env["XDG_BIN_HOME"]))
        cands += [h / ".local" / "bin", h / ".cargo" / "bin"]
        if os_name() == "windows":
            cands.append(local / "Microsoft" / "WinGet" / "Links")
        else:
            cands += [Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    elif name == "node":
        if os_name() == "windows":
            for var in ("ProgramFiles", "ProgramW6432"):
                if env.get(var):
                    cands.append(Path(env[var]) / "nodejs")
            if env.get("NVM_SYMLINK"):
                cands.append(Path(env["NVM_SYMLINK"]))
            cands += [local / "Volta" / "bin", roaming / "fnm" / "aliases" / "default"]
        else:
            cands += [Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/usr/bin"),
                      h / ".volta" / "bin",
                      h / ".local" / "share" / "fnm" / "aliases" / "default" / "bin",
                      h / "Library" / "Application Support" / "fnm" / "aliases" / "default" / "bin",
                      h / ".fnm" / "aliases" / "default" / "bin"]
            # nvm: the newest installed version
            nvm = Path(env.get("NVM_DIR") or (h / ".nvm")) / "versions" / "node"
            try:
                vers = sorted((d for d in nvm.iterdir() if d.is_dir()), key=lambda d: _version_key(d.name), reverse=True)
                cands += [d / "bin" for d in vers[:1]]
            except OSError:
                pass
    out: List[Path] = []
    for d in cands:
        f = d / exe(name)
        if d not in out and f.is_file() and (os_name() == "windows" or os.access(str(f), os.X_OK)):
            out.append(d)
    return out


def find_tool(name: str, path: Optional[str] = None) -> Optional[str]:
    """`uv` / `node` on PATH (or `path`), else in its default install folder."""
    found = shutil.which(name, path=path)
    if found:
        return found
    dirs = default_tool_dirs(name)
    return str(dirs[0] / exe(name)) if dirs else None


# --------------------------------------------------------------------------
# Browsers (Chrome / Edge / Chromium) discovery
# --------------------------------------------------------------------------

def _mac_app_candidates() -> List[tuple]:
    apps = [
        ("chrome", "Google Chrome.app/Contents/MacOS/Google Chrome"),
        ("chrome", "Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta"),
        ("chrome", "Google Chrome Dev.app/Contents/MacOS/Google Chrome Dev"),
        ("chrome", "Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary"),
        ("chrome-for-testing", "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"),
        ("edge", "Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        ("chromium", "Chromium.app/Contents/MacOS/Chromium"),
    ]
    roots = [Path("/Applications"), user_home() / "Applications"]
    return [(kind, root / rel) for kind, rel in apps for root in roots]


def _win_candidates() -> List[tuple]:
    roots = []
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA", "PROGRAMW6432"):
        v = os.environ.get(var)
        if v:
            roots.append(Path(v))
    rels = [
        ("chrome", "Google/Chrome/Application/chrome.exe"),
        ("chrome", "Google/Chrome Beta/Application/chrome.exe"),
        ("chrome", "Google/Chrome SxS/Application/chrome.exe"),
        ("edge", "Microsoft/Edge/Application/msedge.exe"),
        ("chromium", "Chromium/Application/chrome.exe"),
    ]
    return [(kind, root / rel) for kind, rel in rels for root in roots]


def _linux_candidates() -> List[tuple]:
    out = []
    for kind, name in (("chrome", "google-chrome-stable"), ("chrome", "google-chrome"),
                       ("chromium", "chromium"), ("chromium", "chromium-browser"),
                       ("edge", "microsoft-edge-stable"), ("edge", "microsoft-edge")):
        p = shutil.which(name)
        if p:
            out.append((kind, Path(p)))
    for kind, p in (("chrome", "/opt/google/chrome/chrome"),
                    ("edge", "/opt/microsoft/msedge/msedge"),
                    ("chromium", "/usr/lib/chromium/chromium"),
                    ("chromium", "/snap/bin/chromium")):
        out.append((kind, Path(p)))
    return out


def playwright_chromium(browsers_dir: Optional[PathLike] = None) -> Optional[Path]:
    """Newest Chromium installed by `playwright install chromium` in browsers_dir."""
    base = Path(browsers_dir) if browsers_dir else None
    if base is None:
        env = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        if env and env != "0":
            base = Path(env)
    if base is None or not base.is_dir():
        return None
    patterns = [
        "chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
        "chromium-*/chrome-win*/chrome.exe",
        "chromium-*/chrome-linux*/chrome",
    ]
    found: List[Path] = []
    for pat in patterns:
        found.extend(base.glob(pat))

    def rev(p: Path) -> int:
        m = re.search(r"chromium-(\d+)", str(p))
        return int(m.group(1)) if m else 0

    found = [p for p in found if p.is_file()]
    return max(found, key=rev) if found else None


def find_browsers(browsers_dir: Optional[PathLike] = None) -> List[Dict[str, str]]:
    """All usable Chromium-family browsers, best first.

    Order: $SHOWTIME_CHROME, then system Chrome, Edge, Chromium, then the
    Playwright-managed Chromium in `browsers_dir`.
    """
    seen = set()
    result: List[Dict[str, str]] = []

    def add(kind: str, path: Union[str, Path], source: str) -> None:
        p = str(path)
        key = os.path.normcase(os.path.realpath(p))
        if key in seen or not os.path.isfile(p):
            return
        seen.add(key)
        result.append({"kind": kind, "path": p, "source": source})

    env = os.environ.get("SHOWTIME_CHROME") or os.environ.get("CHROME_PATH")
    if env:
        add("custom", env, "env")
    cands = {"mac": _mac_app_candidates, "windows": _win_candidates,
             "linux": _linux_candidates}[os_name()]()
    for kind in ("chrome", "edge", "chromium", "chrome-for-testing"):
        for k, p in cands:
            if k == kind:
                add(kind, p, "system")
    pw = playwright_chromium(browsers_dir)
    if pw:
        add("playwright", pw, "playwright")
    return result


def find_chrome(browsers_dir: Optional[PathLike] = None) -> Optional[Dict[str, str]]:
    """Best browser for rendering, or None."""
    b = find_browsers(browsers_dir)
    return b[0] if b else None


# --------------------------------------------------------------------------
# Chrome launch flags (single source of truth shared with scripts/lib/chrome.mjs)
# --------------------------------------------------------------------------

def _flags_file() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "lib" / "chrome-flags.json"


def chrome_flags(gpu: str = "auto", os_key: Optional[str] = None) -> List[str]:
    """Launch flags for headless capture.

    gpu: 'auto' (per-OS hardware path), 'on' (same as auto), 'off'/'software'
    (SwiftShader, slower but closer to bit-exact across machines).
    """
    data = json.loads(_flags_file().read_text(encoding="utf-8"))
    o = os_key or os_name()
    flags = list(data["common"])
    mode = "software" if gpu in ("off", "software", "swiftshader") else "gpu"
    if mode == "gpu":
        flags += data["gpu"].get(o, [])
    else:
        flags += data["software"]
    return flags


# --------------------------------------------------------------------------
# Opening files / URLs for the user
# --------------------------------------------------------------------------

def open_path(target: Union[str, PathLike], browser: Optional[str] = None) -> bool:
    """Open a file, folder or URL with the desktop's default handler.

    If `browser` (an executable path) is given and target is a URL or HTML
    file, open it in that browser instead. Returns False if nothing worked.
    """
    t = str(target)
    is_url = bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", t))
    try:
        if browser:
            subprocess.Popen([browser, t if is_url else Path(t).resolve().as_uri()],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        if IS_WINDOWS:
            os.startfile(t)  # type: ignore[attr-defined]
            return True
        if IS_MAC:
            subprocess.Popen(["open", t], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        opener = shutil.which("xdg-open") or shutil.which("gio")
        if opener:
            args = [opener, t] if opener.endswith("xdg-open") else [opener, "open", t]
            subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    except OSError:
        pass
    import webbrowser
    return webbrowser.open(t if is_url else Path(t).resolve().as_uri())


# --------------------------------------------------------------------------
# ffmpeg filtergraph escaping
# --------------------------------------------------------------------------

_WIN_ABS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|//)")


def _to_ffmpeg_path_string(p: Union[str, PurePath], absolute: bool) -> str:
    """Normalise to the forward-slash form ffmpeg accepts on every OS."""
    s = str(p)
    windows_style = (isinstance(p, PureWindowsPath) or bool(_WIN_ABS.match(s))
                     or (IS_WINDOWS and "\\" in s))
    if absolute and not _WIN_ABS.match(s) and (IS_WINDOWS or not windows_style):
        # Only make real local paths absolute (pure Windows paths in unit
        # tests on POSIX are left alone).
        s = os.path.abspath(s)
    if windows_style or IS_WINDOWS:
        return PureWindowsPath(s).as_posix()
    return s


def _av_escape(s: str, special: str) -> str:
    """Escape for libavutil's av_get_token(): backslash-escape `special`,
    backslash and quote; protect leading/trailing whitespace."""
    out = []
    for i, ch in enumerate(s):
        if ch in special or ch in "\\'":
            out.append("\\" + ch)
        elif ch in " \t\r\n" and (i == 0 or i == len(s) - 1):
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def filter_value(value: str) -> str:
    """Escape an arbitrary option value for use inside a filtergraph string.

    Two escaping levels are applied: the filter's own option parser
    (special ':') and the filtergraph parser (special '[],;'). The result
    is meant for arg-list subprocess calls (no shell quoting needed), e.g.
    ["-vf", "subtitles=filename=" + filter_path(p)].
    """
    # '=' matters for positional values such as subtitles=<path>, where the
    # option parser first tries to read a key terminated by '=' or ':'.
    level1 = _av_escape(value, ":=")
    return _av_escape(level1, "[],;")


def filter_path(p: Union[str, PurePath], absolute: bool = True) -> str:
    """Escape a file path for ffmpeg filter options (subtitles=, ass=,
    lut3d=, movie=, amovie=, drawtext fontfile=/textfile=, arnndn m=...).

    - Windows paths become forward-slash paths (``C:/Users/me/x.ass``); the
      drive colon is escaped so it is not read as an option separator.
    - Quotes, backslashes, ``: , ; [ ]`` and edge whitespace are escaped for
      both parsing levels.
    Pass the result as part of an argument list, never through a shell.
    """
    return filter_value(_to_ffmpeg_path_string(p, absolute))


def concat_list_path(p: Union[str, PurePath]) -> str:
    """Quote a path for an ffmpeg concat-demuxer list file line: file '<here>'."""
    s = _to_ffmpeg_path_string(p, True)
    return "'" + s.replace("'", "'\\''") + "'"


# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------

def cpu_count() -> int:
    try:
        return len(os.sched_getaffinity(0))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return os.cpu_count() or 2


XVFB_FIX = ("install Xvfb (a virtual display): Debian/Ubuntu: sudo apt install xvfb; Fedora: sudo dnf install "
            "xorg-x11-server-Xvfb; Arch: sudo pacman -S xorg-server-xvfb")


def gl_display_prefix(env: Optional[Dict[str, str]] = None, os_key: Optional[str] = None) -> tuple:
    """Command prefix that gives an OpenGL program (ManimGL) a display: (prefix, problem).

    macOS, Windows and Linux desktops need nothing. A Linux server without DISPLAY / WAYLAND_DISPLAY gets
    `xvfb-run` when it is installed; otherwise the prefix is empty and `problem` says how to fix it."""
    env = os.environ if env is None else env
    if (os_key or os_name()) != "linux" or env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"):
        return [], None
    xr = shutil.which("xvfb-run", path=env.get("PATH"))
    if xr:
        return [xr, "-a", "-s", "-screen 0 1920x1080x24"], None
    return [], "no display on this Linux machine and no xvfb-run: " + XVFB_FIX


def uptime_seconds() -> Optional[float]:
    """Seconds since the machine booted, or None when it cannot be read (never raises)."""
    try:
        if IS_LINUX:
            with open("/proc/uptime", "r") as f:
                return float(f.read().split()[0])
        if IS_WINDOWS:
            import ctypes
            fn = ctypes.windll.kernel32.GetTickCount64  # type: ignore[attr-defined]
            fn.restype = ctypes.c_ulonglong
            return fn() / 1000.0
        if IS_MAC:
            import time as _time
            out = subprocess.run(["sysctl", "-n", "kern.boottime"], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, encoding="utf-8", timeout=5).stdout
            m = re.search(r"sec\s*=\s*(\d+)", out or "")
            return (_time.time() - int(m.group(1))) if m else None
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return None
    return None


def summary() -> Dict[str, str]:
    return {
        "os": os_name(),
        "arch": arch(),
        "key": platform_key(),
        "python": sys.version.split()[0],
        "python_exe": sys.executable,
        "cpus": str(cpu_count()),
    }


if __name__ == "__main__":  # pragma: no cover - manual inspection helper
    print(json.dumps({"platform": summary(), "browsers": find_browsers()}, indent=2))

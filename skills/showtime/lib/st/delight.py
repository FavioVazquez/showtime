"""Small touches for a person at a terminal: the brand mark, a completion card, an opt-in sound.

All of it is decoration, so all of it steps aside by itself. Nothing here prints or plays unless the
stream is an interactive terminal, and never with --json, NO_COLOR, TERM=dumb, CI, SHOWTIME_COLOR=never
or SHOWTIME_PROGRESS=json. Claude's tool calls, pipes and logs therefore see exactly the plain output they
always did. On Windows the mark needs a console that accepts VT sequences (Windows 10+).

    header("showtime doctor 0.1.0", "mac-x64  ·  home ~/.showtime")   -> 2 lines, or None
    show_card("final.mp4 is ready", path, ["20.0 s", "1920x1080", "4.2 MB"], "showtime qa <job>")
    maybe_chime(elapsed_seconds)      # SHOWTIME_SOUND=1 and a job over 20 s: the short sound logo

scripts/lib/delight.mjs is the same thing for the Node commands (render, export). Stdlib only, 3.8+.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence, Union

from . import platform as plat

VELVET = (0xB3, 0x12, 0x1F)   # shapes only: never text on a dark terminal
GOLD = (0xE9, 0xB9, 0x49)
PROGRAMME = (0xB6, 0xA7, 0x95)
# nearest xterm-256 and basic-16 codes for terminals without truecolor
_C256 = {VELVET: 124, GOLD: 179, PROGRAMME: 181}
_C16 = {VELVET: "31", GOLD: "33", PROGRAMME: "2"}

LONG_JOB_S = 20.0
SOUND_FILE = Path(__file__).resolve().parent / "sounds" / "sound-logo-short.wav"
_TRUECOLOR_APPS = ("iTerm.app", "WezTerm", "vscode", "ghostty", "Hyper", "Tabby", "rio")
_MARK_U = ("▐█▀▀▀█▌", "▐█", "▄▄▄", "█▌")
_MARK_A = ('|"""""|', "|_", "===", "_|")
_DOT_U, _DOT_A = "·", "-"


def _off(v: Optional[str]) -> bool:
    return str(v or "").strip().lower() in ("0", "false", "no", "off", "never")


def _on(v: Optional[str]) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def in_ci(env: Optional[Mapping[str, str]] = None) -> bool:
    env = os.environ if env is None else env
    return bool(env.get("CI")) and not _off(env.get("CI"))


def decor_ok(stream: Any = None, argv: Optional[Sequence[str]] = None,
             env: Optional[Mapping[str, str]] = None) -> bool:
    """True when decoration (mark, card, sound) may go to `stream` (default stdout).

    Off for: --json on the command line, NO_COLOR, TERM=dumb, CI, SHOWTIME_COLOR=never,
    SHOWTIME_PROGRESS=json, a stream that is not a terminal, and a Windows console without VT
    support. FORCE_COLOR / SHOWTIME_COLOR=always do not turn it on for a pipe: colour yes, decoration no.
    """
    env = os.environ if env is None else env
    argv = sys.argv[1:] if argv is None else argv
    if "--json" in argv:
        return False
    if env.get("NO_COLOR") or env.get("TERM") == "dumb" or in_ci(env):
        return False
    if _off(env.get("SHOWTIME_COLOR")) or str(env.get("SHOWTIME_PROGRESS", "")).lower() == "json":
        return False
    stream = sys.stdout if stream is None else stream
    try:
        if not stream.isatty():
            return False
    except (AttributeError, ValueError, OSError):
        return False
    from .common import _enable_windows_vt
    return _enable_windows_vt(stream)


def color_depth(env: Optional[Mapping[str, str]] = None, os_key: Optional[str] = None) -> int:
    """24 (truecolor), 8 (256 colours) or 4 (the basic 16)."""
    env = os.environ if env is None else env
    if str(env.get("COLORTERM", "")).lower() in ("truecolor", "24bit"):
        return 24
    if (os_key or plat.os_name()) == "windows" or env.get("WT_SESSION"):
        return 24          # Windows 10+ consoles with VT on take 24-bit colour
    if env.get("TERM_PROGRAM") in _TRUECOLOR_APPS:
        return 24
    return 8 if "256" in str(env.get("TERM", "")) else 4


def unicode_ok(stream: Any = None) -> bool:
    """Can the stream print the block glyphs? (They are in CP437 too, so only odd code pages fail.)"""
    enc = getattr(sys.stdout if stream is None else stream, "encoding", None) or "ascii"
    try:
        (_MARK_U[0] + _MARK_U[2] + _DOT_U).encode(enc)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _fg(rgb: tuple, depth: int) -> str:
    if depth >= 24:
        return "38;2;%d;%d;%d" % rgb
    if depth >= 8:
        return "38;5;%d" % _C256[rgb]
    return _C16[rgb]


def _sgr(text: str, code: str, depth: int) -> str:
    return "\033[%sm%s\033[0m" % (code, text) if depth and code else text


def mark(depth: int = 24, unicode: bool = True) -> tuple:
    """The two-line curtain: velvet drapes and valance, the gold pool of light on the stage."""
    top, side_l, pool, side_r = _MARK_U if unicode else _MARK_A
    v, g = _fg(VELVET, depth), _fg(GOLD, depth)
    return (_sgr(top, v, depth), _sgr(side_l, v, depth) + _sgr(pool, g, depth) + _sgr(side_r, v, depth))


def format_header(title: str, subtitle: str = "", depth: int = 24, unicode: bool = True) -> str:
    """Brand mark beside a title (bold gold) and a subtitle (secondary colour)."""
    m1, m2 = mark(depth, unicode)
    t = _sgr(title, "1;" + _fg(GOLD, depth) if depth > 4 else "1", depth)
    s = _sgr(subtitle, _fg(PROGRAMME, depth), depth) if subtitle else ""
    if not unicode:
        s = s.replace(_DOT_U, _DOT_A)
    return "%s  %s\n%s  %s" % (m1, t, m2, s)


def header(title: str, subtitle: str = "", stream: Any = None) -> Optional[str]:
    """The header block for `stream`, or None when decoration is off (print your plain line then)."""
    stream = sys.stdout if stream is None else stream
    if not decor_ok(stream):
        return None
    return format_header(title, subtitle, color_depth(), unicode_ok(stream))


def display_path(p: Union[str, "os.PathLike[str]"], cwd: Optional[str] = None) -> str:
    """Relative to the current folder when the file is inside it, else absolute."""
    ap = os.path.abspath(str(p))
    base = os.path.abspath(cwd or os.getcwd())
    try:
        rel = os.path.relpath(ap, base)
    except ValueError:        # another drive on Windows
        return ap
    return ap if rel.startswith("..") else rel


def shell_path(p: Union[str, "os.PathLike[str]"]) -> str:
    """A path ready to paste into a command: relative when inside the current folder, quoted when needed."""
    d = display_path(p)
    return '"%s"' % d if any(ch in d for ch in " \t'&()") else d


def open_hint(p: Union[str, "os.PathLike[str]"], os_key: Optional[str] = None) -> str:
    """The shell command that opens a file or folder with its default app."""
    q = shell_path(p)
    o = os_key or plat.os_name()
    if o == "windows":
        return 'start "" %s' % (q if q.startswith('"') else '"%s"' % q)
    return ("open %s" if o == "mac" else "xdg-open %s") % q


def fmt_len(seconds: Optional[float]) -> Optional[str]:
    """Video length for a card: '20.0 s', '1:35', or None."""
    if seconds is None:
        return None
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return None
    if s < 60:
        return "%.1f s" % s
    from .common import fmt_duration
    return fmt_duration(s)


_QA_CODE = {"PASS": "32", "WARN": "33", "FAIL": "31"}


def format_card(title: str, path: Optional[Union[str, "os.PathLike[str]"]] = None, facts: Sequence[Optional[str]] = (),
                next_step: Optional[str] = None, qa: Optional[str] = None, depth: int = 24,
                unicode: bool = True, cwd: Optional[str] = None) -> str:
    """The completion card: what was made, where it is, the one obvious next step.

        ▐█▀▀▀█▌  final.mp4 is ready  ·  20.0 s  ·  1920x1080  ·  4.2 MB  ·  qa PASS
        ▐█▄▄▄█▌  showtime-out/launch-20260927-101500/final.mp4
                 next  showtime qa showtime-out/launch-20260927-101500

    depth=0 gives plain text (no escape codes); unicode=False the ASCII version.
    """
    dot = _DOT_U if unicode else _DOT_A
    sep = "  %s  " % _sgr(dot, _fg(PROGRAMME, depth), depth)
    bits = [_sgr(title, "1", depth)] + [_sgr(f, _fg(PROGRAMME, depth), depth) for f in facts if f]
    if qa:
        v = str(qa).upper()
        bits.append("qa " + _sgr(v, _QA_CODE.get(v, ""), depth))
    m1, m2 = mark(depth, unicode)
    lines = ["%s  %s" % (m1, sep.join(bits))]
    lines.append("%s  %s" % (m2, display_path(path, cwd) if path else ""))
    if next_step:
        label = _sgr("next", _fg(GOLD, depth), depth)
        lines.append("%s  %s  %s" % (" " * 7, label, next_step))
    return "\n".join(line.rstrip() for line in lines)


def show_card(title: str, path: Optional[Union[str, "os.PathLike[str]"]] = None,
              facts: Sequence[Optional[str]] = (), next_step: Optional[str] = None, qa: Optional[str] = None,
              stream: Any = None) -> bool:
    """Print the card to `stream` (default stdout) when decoration is on. True if printed."""
    stream = sys.stdout if stream is None else stream
    if not decor_ok(stream):
        return False
    try:
        stream.write("\n" + format_card(title, path, facts, next_step, qa, color_depth(), unicode_ok(stream)) + "\n")
        stream.flush()
    except (OSError, ValueError, UnicodeEncodeError):
        return False
    return True


def qa_verdict(video: Union[str, "os.PathLike[str]"], job: Optional[Union[str, "os.PathLike[str]"]] = None) -> Optional[str]:
    """The qa verdict recorded for exactly this file in its job.json, else None (no new work)."""
    import json
    v = Path(video).resolve()
    j = Path(job) if job else v.parent
    for d in (j, j.parent):
        try:
            data = json.loads((d / "job.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        files = data.get("qa_files") if isinstance(data.get("qa_files"), dict) else {}
        rec = files.get(str(v))
        if not isinstance(rec, dict):
            q = data.get("qa") if isinstance(data.get("qa"), dict) else {}
            rec = q if q.get("video") and str(Path(str(q["video"])).resolve()) == str(v) else None
        return str(rec["verdict"]) if rec and rec.get("verdict") else None
    return None


# --------------------------------------------------------------------------
# Opt-in sound logo
# --------------------------------------------------------------------------

def sound_enabled(env: Optional[Mapping[str, str]] = None, argv: Optional[Sequence[str]] = None) -> bool:
    """SHOWTIME_SOUND=1 (or the plugin's "sound" option) and a person at an interactive terminal."""
    env = os.environ if env is None else env
    if not _on(env.get("SHOWTIME_SOUND")):
        return False
    return decor_ok(sys.stdout, argv, env) and decor_ok(sys.stderr, argv, env)


def player_command(sound: Union[str, "os.PathLike[str]"], os_key: Optional[str] = None,
                   which: Any = None) -> Optional[List[str]]:
    """A command that plays a WAV and exits, with a player the system already has (None if none)."""
    which = which or shutil.which
    f = str(sound)
    o = os_key or plat.os_name()
    ffplay_args = ["-nodisp", "-autoexit", "-loglevel", "quiet", f]
    try:  # showtime's own ffplay first, when the install has one
        from .common import home
        local = home() / "bin" / ("ffplay.exe" if o == "windows" else "ffplay")
        if local.is_file():
            return [str(local)] + ffplay_args
    except Exception:  # noqa: BLE001
        pass
    if o == "mac" and which("afplay"):
        return ["afplay", f]
    if o == "windows":
        ps = which("powershell") or which("pwsh")
        if ps:
            return [ps, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command",
                    "(New-Object System.Media.SoundPlayer '%s').PlaySync()" % f.replace("'", "''")]
    if o == "linux":
        for name, args in (("paplay", []), ("pw-play", []), ("aplay", ["-q"])):
            exe = which(name)
            if exe:
                return [exe] + args + [f]
    ffplay = which("ffplay")
    return [ffplay] + ffplay_args if ffplay else None


def play_sound(sound: Optional[Union[str, "os.PathLike[str]"]] = None) -> bool:
    """Start the player in the background and return at once; never raises."""
    f = Path(sound) if sound else SOUND_FILE
    try:
        if not f.is_file():
            return False
        cmd = player_command(f)
        if not cmd:
            return False
        kw: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                    "close_fds": True}
        if os.name == "nt":
            kw["creationflags"] = 0x08000000 | 0x00000200   # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        subprocess.Popen(cmd, **kw)
        return True
    except Exception:  # noqa: BLE001 - a sound must never fail a command
        return False


def maybe_chime(elapsed: float, ok: bool = True, argv: Optional[Sequence[str]] = None,
                env: Optional[Mapping[str, str]] = None) -> bool:
    """Play the short sound logo after a successful job longer than LONG_JOB_S, when enabled."""
    if not ok or elapsed < LONG_JOB_S:
        return False
    if not sound_enabled(env, argv):
        return False
    return play_sound()

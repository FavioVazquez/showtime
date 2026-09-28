"""showtime launcher (stdlib only, Python 3.8+).

bin/showtime, bin/showtime.cmd and bin/showtime.ps1 all run this file with
whatever Python they find. It prepares the environment and routes:

  showtime setup ...        -> setup/setup.py (works before anything is installed)
  showtime doctor ...       -> st.doctor (stdlib; works before the venv exists)
  showtime <name> ...       -> node scripts/<name>.mjs ...   if that file exists
  showtime <name> ...       -> <venv python> -m st.cli <name> ...   otherwise

Environment exported to every child process:
  SHOWTIME_HOME, SHOWTIME_SKILL, SHOWTIME_PYTHON (venv python), SHOWTIME_NODE_MODULES,
  PATH (~/.showtime/bin and the venv's bin first), PYTHONPATH (+SKILL/lib),
  HF_HOME (~/.showtime/models/hf), PLAYWRIGHT_BROWSERS_PATH (~/.showtime/browsers),
  NODE_PATH, SUPERTONIC_CACHE_DIR, U2NET_HOME, PYTHONUTF8=1, and the saved plugin
  settings (SHOWTIME_VOICE, SHOWTIME_LANG, SHOWTIME_OPEN_BROWSER, SHOWTIME_MAX_WORKERS,
  SHOWTIME_THREADS, SHOWTIME_SOUND) unless those are already set; see settings_file().
"""
import os
import sys

# This file lives inside the `st` package, and st/platform.py would shadow
# the stdlib `platform` module if our own directory stayed on sys.path[0].
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.getcwd()) != _HERE]

import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

LIB_DIR = Path(_HERE).parent            # SKILL/lib
SKILL_DIR = LIB_DIR.parent              # SKILL
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from st import __version__  # noqa: E402
from st import platform as plat  # noqa: E402

BUILTINS = {
    "setup": "Install or update everything showtime needs (~/.showtime)",
    "doctor": "Check the installation: PASS/WARN/FAIL with a one-line fix each",
    "version": "Print the showtime version (--json for details)",
    "help": "Show this help, or `showtime help <command>`",
}
STDLIB_CLI = ("paths", "new", "retime", "data")   # stdlib-only commands that also run without the venv

# Top-level help: groups in the order a video gets made. A command a module
# adds later shows up under "more" until it is listed here. Examples are only
# printed when their command exists in this install.
GROUPS = [
    ("make", "Make a video from an HTML/canvas project",
     ["new", "retime", "data", "preview", "render", "export", "check", "snap", "score", "motion", "code", "server",
      "manim"],
     ["showtime new dom my-launch --aspect 16:9",
      "showtime retime my-launch -d 20            # or --from-voice voice/timeline.json",
      "showtime preview my-launch",
      "showtime render my-launch --preview        # fast draft first",
      "showtime render my-launch -o final.mp4",
      "showtime manim new my-math                 # equations, proofs, graphs (Manim)"]),
    ("audio", "Music, sound effects, mixing and loudness",
     ["audio"],
     ["showtime audio compose --style underscore --dur 45 -o bed.wav",
      "showtime audio sfx whoosh -o whoosh.wav",
      "showtime audio mix audio/mix.json -o audio/mix.wav"]),
    ("voice", "Narration with word timings",
     ["voice"],
     ['showtime voice say "Meet showtime." -o vo.wav',
      "showtime voice script narration.md"]),
    ("footage", "Edit real footage by transcript",
     ["transcribe", "pack", "edit", "captions", "footage", "autozoom"],
     ["showtime transcribe raw/take1.mp4",
      "showtime edit cut edit/transcripts/take1.json -o edit/edl.json",
      "showtime captions edit/transcripts/take1.json --style clean -o subs.ass"]),
    ("capture/assets", "Websites, app demos, documents, fonts, icons, media",
     ["site", "demo", "doc", "assets"],
     ["showtime site capture https://example.com",
      "showtime doc extract paper.pdf -o research/paper   # text, images, figures, page renders",
      "showtime demo record walkthrough.mjs --url http://localhost:3000",
      "showtime assets font inter"]),
    ("studio", "Pick a direction together on local boards (opt-in), brand kit",
     ["studio", "brand"],
     ["showtime studio init launch-teaser",
      "showtime studio open launch-teaser",
      "showtime brand init --from ."]),
    ("job/qa", "Where a job stands, and proof it is done",
     ["status", "qa", "review-pack", "job", "clean"],
     ["showtime status",
      "showtime qa final.mp4 --project my-video",
      "showtime review-pack showtime-out/launch-20260926-101500"]),
    ("deliver", "Posters, platform exports, thumbnails",
     ["deliver"],
     ["showtime deliver exports final.mp4 --targets youtube,reels,square",
      "showtime deliver poster final.mp4 --bake"]),
    ("setup", "Install, check and locate things",
     ["setup", "doctor", "report", "paths", "version", "help"],
     ["showtime setup                 # core install, once",
      "showtime doctor",
      "showtime setup --with asr-turbo"]),
]
INSTALL_DOC = "https://github.com/faviovazquez/showtime#install"


# User settings. Claude Code's plugin options (/config) reach showtime through the
# plugin's MCP server, which writes them to this file when a session starts; the
# launcher turns them into environment defaults. An environment variable that is
# already set always wins, and a command-line flag wins over both.
SETTINGS_ENV = {
    "voice": "SHOWTIME_VOICE",                # default narration voice, e.g. af_heart
    "language": "SHOWTIME_LANG",              # default narration language, e.g. en, es
    "open_browser": "SHOWTIME_OPEN_BROWSER",  # studio boards open in the browser by themselves
    "max_workers": "SHOWTIME_MAX_WORKERS",    # cap on parallel render browsers and CPU threads
    "sound": "SHOWTIME_SOUND",                # short sound logo when a long job finishes (terminals only)
}


def settings_file() -> Path:
    env = os.environ.get("SHOWTIME_SETTINGS")
    return Path(os.path.expanduser(env)) if env else plat.user_home() / ".showtime" / "plugin-settings.json"


def load_settings() -> dict:
    """The saved plugin settings ({} when there are none or the file is unreadable)."""
    try:
        import json as _json
        data = _json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def settings_env(settings: dict) -> dict:
    """Plugin settings as SHOWTIME_* environment values (unset ones left out)."""
    out = {}
    for key, var in SETTINGS_ENV.items():
        val = settings.get(key)
        if val is None or val == "":
            continue
        if isinstance(val, bool):
            out[var] = "1" if val else "0"
        elif key == "max_workers":
            try:
                n = int(val)
            except (TypeError, ValueError):
                continue
            if n > 0:
                out[var] = str(n)
                out["SHOWTIME_THREADS"] = str(n)
        else:
            out[var] = str(val)
    return out


def showtime_home() -> Path:
    env = os.environ.get("SHOWTIME_HOME")
    if env:
        return Path(os.path.expanduser(env))
    configured = load_settings().get("home")
    if isinstance(configured, str) and configured.strip():
        return Path(os.path.expanduser(configured.strip()))
    return plat.user_home() / ".showtime"


def build_env(home: Path) -> dict:
    env = dict(os.environ)
    venv = home / "venv"
    vpy = plat.venv_python(venv)
    path_parts = [str(home / "bin")]
    if vpy.exists():
        path_parts.append(str(plat.venv_bin(venv)))
    old_path = env.get("PATH", "")
    tail = []
    # uv / Node.js installed after this app started are not on its PATH yet: use their default folders
    for tool in ("node", "uv"):
        if not shutil.which(tool, path=old_path or None):
            tail += [str(d) for d in plat.default_tool_dirs(tool)[:1] if str(d) not in tail]
    env["PATH"] = os.pathsep.join(path_parts + ([old_path] if old_path else []) + tail)
    env["SHOWTIME_HOME"] = str(home)
    env["SHOWTIME_SKILL"] = str(SKILL_DIR)
    for var, val in settings_env(load_settings()).items():
        if not env.get(var):
            env[var] = val
    if env.get("SHOWTIME_MAX_WORKERS", "").isdigit() and int(env["SHOWTIME_MAX_WORKERS"]) > 0:
        env.setdefault("SHOWTIME_THREADS", env["SHOWTIME_MAX_WORKERS"])
    if vpy.exists():
        env["SHOWTIME_PYTHON"] = str(vpy)
    nm = home / "node" / "node_modules"
    env["SHOWTIME_NODE_MODULES"] = str(nm)
    env["NODE_PATH"] = str(nm) + ((os.pathsep + env["NODE_PATH"]) if env.get("NODE_PATH") else "")
    pp = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(LIB_DIR) + ((os.pathsep + pp) if pp else "")
    env["HF_HOME"] = str(home / "models" / "hf")
    env.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    env.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(home / "browsers"))
    env.setdefault("SUPERTONIC_CACHE_DIR", str(home / "models" / "supertonic3"))
    env.setdefault("U2NET_HOME", str(home / "models" / "u2net"))
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


# --------------------------------------------------------------------------
# Discovery for help
# --------------------------------------------------------------------------

def node_scripts() -> dict:
    """{name: one-line help} for SKILL/scripts/*.mjs (first // comment line)."""
    out = {}
    d = SKILL_DIR / "scripts"
    if not d.is_dir():
        return out
    for f in sorted(d.glob("*.mjs")):
        if f.name.startswith("_"):
            continue
        desc = ""
        try:
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    s = line.strip()
                    if i == 0 and s.startswith("#!"):
                        continue
                    if s.startswith("//"):
                        desc = s.lstrip("/").strip()
                        desc = re.sub(r"^showtime\s+%s\s*[-:—]+\s*" % re.escape(f.stem), "", desc)
                        break
                    if s.startswith("/*") or s.startswith("*"):
                        desc = s.strip("/* ").strip()
                        if desc:
                            break
                        continue
                    if s:
                        break
        except OSError:
            pass
        out[f.stem] = desc or "(node script)"
    return out


def python_commands() -> dict:
    """{name: help} from every st/cli_*.py COMMANDS literal (no imports)."""
    try:
        from st.cli import discover, read_commands  # stdlib-only module
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for _mod, path in discover():
        for k, v in read_commands(path).items():
            out.setdefault(k, v)
    return out


def _paint(text: str, style: str, stream=None) -> str:
    try:
        from st.common import paint
    except Exception:  # noqa: BLE001
        return text
    return paint(text, style, stream if stream is not None else sys.stdout)


def _brand_header(title: str, subtitle: str):
    """The brand mark header on an interactive terminal, else None (see st/delight.py)."""
    try:
        from st.delight import header
        return header(title, subtitle, sys.stdout)
    except Exception:  # noqa: BLE001 - decoration never breaks help
        return None


def _short(desc: str, limit: int = 84) -> str:
    """Trim a one-line description at a clause or word boundary."""
    if len(desc) <= limit:
        return desc
    cut = desc[:limit]
    out = None
    for sep in (": ", "; ", " (", ", "):
        i = cut.rfind(sep)
        if i > limit // 2:
            out = cut[:i].rstrip(" ,;:(")
            break
    if out is None:
        out = cut[:cut.rfind(" ")].rstrip(" ,;:") + " ..."
    if out.count("(") > out.count(")"):
        out += ")"
    return out


def all_commands() -> dict:
    cmds = dict(python_commands())
    for k, v in node_scripts().items():
        cmds.setdefault(k, v)
    for k, v in BUILTINS.items():
        cmds.setdefault(k, v)
    return cmds


def _write(text: str) -> None:
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:  # legacy Windows code pages
        sys.stdout.write(text.encode("ascii", "replace").decode("ascii"))


def print_help(home: Path, verbose: bool = False) -> None:
    w = _write
    cmds = all_commands()
    head = _brand_header("showtime %s" % __version__, "make videos on your own machine, with Claude as the director")
    if head:
        w(head + "\n\n")
    else:
        w("%s %s: make videos on your own machine, with Claude as the director\n\n"
          % (_paint("showtime", "bold"), __version__))
    w("usage: showtime <command> [args...]      showtime <command> --help   (details and examples)\n")
    w("       --debug  full tracebacks     --json  machine output (where offered)     NO_COLOR=1  plain text\n\n")
    listed = set()
    width = 13
    for key, title, names, examples in GROUPS:
        present = [n for n in names if n in cmds]
        if not present:
            continue
        w("%s  %s\n" % (_paint(key, "bold_cyan"), _paint(title, "dim")))
        for n in present:
            listed.add(n)
            desc = cmds[n] if verbose else _short(cmds[n])
            w("  %s %s\n" % (n.ljust(width), desc))
        shown = [e for e in examples if e.split()[1] in cmds]
        for e in shown:
            w("    %s %s\n" % (_paint("$", "dim"), e))
        w("\n")
    rest = {k: v for k, v in cmds.items() if k not in listed}
    if rest:
        w("%s\n" % _paint("more", "bold_cyan"))
        for n in sorted(rest):
            w("  %s %s\n" % (n.ljust(width), rest[n] if verbose else _short(rest[n])))
        w("\n")
    vpy = plat.venv_python(home / "venv")
    if not vpy.exists():
        w(_paint("not installed yet:", "yellow") + " run `showtime setup` first (%s).\n" % _estimate_text(home))
    w("home:   %s  (override with SHOWTIME_HOME)\nskill:  %s\n" % (home, SKILL_DIR))


def _setup_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("showtime_setup", str(SKILL_DIR / "setup" / "setup.py"))
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _estimate_text(home: Path, tier: str = "core") -> str:
    try:
        su = _setup_module()
        return su.describe_estimate(su.install_estimate(tier, (), home))
    except Exception:  # noqa: BLE001 - never let an estimate break help
        return "about 3 GB, usually 5-15 min"


def first_run_message(cmd: str, home: Path, what: str = "the showtime environment") -> str:
    """Exactly what to do when a command runs before setup."""
    import shutil as _sh
    lines = [
        "%s `%s` needs %s, and setup has not been run yet." % (_paint("showtime:", "yellow", sys.stderr), cmd, what),
        "  run:   showtime setup",
        "         core install: %s." % _estimate_text(home),
        "         Everything goes into %s; nothing else on the system changes." % home,
        "  needs: uv and Node.js 20+ (setup prints how to install them if they are missing)",
        "  then:  showtime doctor, and run your command again",
    ]
    if not _sh.which("showtime"):
        shim = SKILL_DIR / "bin" / ("showtime.cmd" if os.name == "nt" else "showtime")
        lines.append("  (showtime is %s)" % shim)
    return "\n".join(lines) + "\n"


def print_version(as_json: bool, home: Path) -> int:
    info = {"version": __version__, "skill": str(SKILL_DIR), "home": str(home),
            "platform": plat.platform_key(), "python": sys.version.split()[0],
            "installed": plat.venv_python(home / "venv").exists(),
            "settings": {"file": str(settings_file()), "saved": load_settings(),
                         "effective": {v: os.environ[v] for v in list(SETTINGS_ENV.values()) + ["SHOWTIME_THREADS"]
                                       if os.environ.get(v)}}}
    try:
        import json as _json
        st = _json.loads((home / "state.json").read_text(encoding="utf-8"))
        info["setup"] = st.get("installed")
        info["setup_version"] = st.get("showtime_version")
    except (OSError, ValueError):
        info["setup"] = None
    if as_json:
        import json as _json
        print(_json.dumps(info, indent=2))
    else:
        print("showtime %s" % __version__)
    return 0


# --------------------------------------------------------------------------
# Process handoff
# --------------------------------------------------------------------------

def _handoff(argv: list, env: dict) -> int:
    """Replace this process (POSIX) or run and wait (Windows)."""
    if os.name != "nt":
        try:
            sys.stdout.flush()
            sys.stderr.flush()
            os.execve(argv[0], argv, env)
        except OSError as e:
            sys.stderr.write("showtime: cannot run %s: %s\n" % (argv[0], e))
            return 127
    proc = None
    try:
        proc = subprocess.Popen(argv, env=env)
        job = _die_with_launcher(proc)  # noqa: F841  (held open until this process ends)
        return proc.wait()
    except KeyboardInterrupt:
        if proc is not None:
            try:
                return proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        return 130
    except OSError as e:
        sys.stderr.write("showtime: cannot run %s: %s\n" % (argv[0], e))
        return 127


def _die_with_launcher(proc: "subprocess.Popen"):
    """Windows: tie the child (node, the venv python) to this launcher, as exec does on POSIX. Without
    it, a host that stops `showtime server|preview|render` kills only the launcher and the child keeps
    running (a server holding its port, a render holding the CPU). The child goes into a job object
    that is killed when this process's handle closes, i.e. when the launcher exits or is killed.
    SILENT_BREAKAWAY_OK keeps the child's own children out of the job: Node already kills its attached
    children when it dies, and a server that `preview` detaches on purpose keeps running.
    Returns the job handle (keep a reference) or None; best effort."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class _Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", ctypes.c_ulonglong * 6),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000 | 0x1000  # KILL_ON_JOB_CLOSE | SILENT_BREAKAWAY_OK
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):  # 9: extended limits
            return None
        if not k32.AssignProcessToJobObject(job, int(proc._handle)):  # type: ignore[attr-defined]
            return None
        return job
    except (AttributeError, OSError, ValueError):
        return None


def _base_python() -> str:
    """A Python outside the showtime venv (setup may rebuild the venv)."""
    base = getattr(sys, "_base_executable", None)
    if base and os.path.isfile(base) and os.path.abspath(base) != os.path.abspath(sys.executable):
        return base
    return sys.executable


RESTART_HINT = "if you just installed it, restart Claude Code (or open a new terminal) so it sees the new PATH"


def _node_hint() -> str:
    o = plat.os_name()
    if o == "mac":
        how = "install Node.js 24 or 22 LTS (20+) from https://nodejs.org (or `brew install node`)"
    elif o == "windows":
        how = "install Node.js 24 or 22 LTS (20+) from https://nodejs.org (or `winget install OpenJS.NodeJS.LTS --source winget`)"
    else:
        how = ("install Node.js 24 or 22 LTS (20+) with fnm (https://github.com/Schniz/fnm: `fnm install --lts`) or "
               "NodeSource; distribution packages are often too old")
    return how + "; " + RESTART_HINT


def _is_current_interpreter(p: Path) -> bool:
    try:
        return os.path.samefile(str(p), sys.executable)
    except OSError:
        return False


def run_python_cli(args: list, env: dict, home: Path) -> int:
    vpy = plat.venv_python(home / "venv")
    cmd = args[0] if args else ""
    known = set(python_commands()) | set(node_scripts()) | set(BUILTINS)
    if known and cmd and not cmd.startswith("-") and cmd not in known:
        import difflib
        close = difflib.get_close_matches(cmd, sorted(known), n=3, cutoff=0.6)
        sys.stderr.write("%s unknown command '%s'.%s\n  fix: run `showtime --help` for the list of commands.\n" % (
            _paint("error:", "red", sys.stderr), cmd, (" Did you mean: %s?" % ", ".join(close)) if close else ""))
        return 2
    if vpy.exists() and not _is_current_interpreter(vpy):
        return _handoff([str(vpy), "-m", "st.cli"] + args, env)
    if vpy.exists() or cmd in STDLIB_CLI:
        os.environ.update(env)
        from st.cli import main as cli_main
        return cli_main(args)
    sys.stderr.write(first_run_message(cmd, home))
    return 2


def _node_ready(home: Path) -> bool:
    return (home / "node" / "node_modules" / "playwright").is_dir()


def utf8_stdio(streams=None) -> None:
    """Windows: write UTF-8 when stdout/stderr go to a pipe or file, as every child process does
    (build_env sets PYTHONIOENCODING=utf-8). Commands run in this process otherwise print in the ANSI
    code page (cp1252), so Claude Code and other hosts that read the pipe as UTF-8 get broken text,
    and characters outside the code page (a non-Latin file name, a transcript) raise
    UnicodeEncodeError. Real consoles already print Unicode; an explicit PYTHONIOENCODING wins."""
    if os.name != "nt" or os.environ.get("PYTHONIOENCODING"):
        return
    for s in (streams if streams is not None else (sys.stdout, sys.stderr)):
        try:
            if s is not None and (getattr(s, "encoding", "") or "").lower().replace("-", "").replace("_", "") != "utf8":
                s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv=None) -> int:
    utf8_stdio()
    args = list(sys.argv[1:] if argv is None else argv)
    home = showtime_home()
    env = build_env(home)
    if "--debug" in args:
        env["SHOWTIME_DEBUG"] = "1"
        os.environ["SHOWTIME_DEBUG"] = "1"
    if "--no-color" in args:
        args = [a for a in args if a != "--no-color"]
        env["NO_COLOR"] = os.environ["NO_COLOR"] = "1"

    if not args or args[0] in ("-h", "--help"):
        print_help(home, verbose="-v" in args or "--verbose" in args)
        return 0
    if args[0] in ("--version", "-V", "version"):
        os.environ.update(env)
        return print_version("--json" in args[1:], home)
    if args[0] == "help":
        if len(args) > 1:
            return main(args[1:2] + ["--help"])
        print_help(home)
        return 0

    cmd, rest = args[0], args[1:]

    if cmd == "setup":
        setup_py = SKILL_DIR / "setup" / "setup.py"
        return _handoff([_base_python(), str(setup_py)] + [a for a in rest if a != "--debug"], env)

    if cmd == "doctor":
        os.environ.update(env)
        from st.doctor import main as doctor_main
        return doctor_main([a for a in rest if a != "--debug"])

    script = SKILL_DIR / "scripts" / (cmd + ".mjs")
    if re.match(r"^[A-Za-z0-9][\w-]*$", cmd) and script.is_file():
        node = env.get("SHOWTIME_NODE") or plat.find_tool("node", env.get("PATH"))
        if not node:
            sys.stderr.write("%s `%s` needs Node.js, which was not found.\n  fix: %s\n       then run `showtime setup`\n"
                             % (_paint("error:", "red", sys.stderr), cmd, _node_hint()))
            return 127
        wants_help = any(a in ("-h", "--help") for a in rest)
        if not _node_ready(home) and not wants_help:
            sys.stderr.write(first_run_message(cmd, home, "the showtime browser tools (Playwright and friends)"))
            return 2
        return _handoff([node, str(script)] + rest, env)

    return run_python_cli(args, env, home)


def _friendly_crash(exc: BaseException) -> int:
    """Last-resort handler: what / why / fix, the traceback only with --debug."""
    import traceback
    debug = os.environ.get("SHOWTIME_DEBUG") == "1" or "--debug" in sys.argv
    if debug:
        traceback.print_exc()
    log_note = ""
    try:
        logs = showtime_home() / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "last-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        log_note = " (traceback saved to %s)" % (logs / "last-error.log")
    except OSError:
        pass
    sys.stderr.write("%s showtime could not start: %s: %s\n"
                     "  why: this is a bug or a damaged install%s\n"
                     "  fix: run `showtime doctor`; re-run with --debug to see the traceback\n"
                     % (_paint("error:", "red", sys.stderr), type(exc).__name__, exc, log_note))
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as _e:  # noqa: BLE001
        sys.exit(_friendly_crash(_e))

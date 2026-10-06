"""showtime command-line root.

Run as `python -m st.cli <command> ...` (the launcher does this for you).

Commands are contributed by modules named `st/cli_<module>.py`. Each such
module must expose:

    COMMANDS = {"name": "one-line help", ...}   # literal dict, read without importing
    def register(subparsers) -> None:           # add its argparse sub-commands

and each registered sub-command sets `func=<handler(args) -> int|None>` via
`parser.set_defaults(func=...)`. Handlers raise `st.common.ShowtimeError` for
user-facing errors. A module that fails to import (missing optional
dependency) still shows up: its commands print the import error instead.
"""
from __future__ import annotations

import argparse
import ast
import importlib
import os
import pkgutil
import sys
import time
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import __version__
from .common import ShowtimeError, error, home, paint

PKG_DIR = Path(__file__).resolve().parent


def read_commands(path: Path) -> Dict[str, str]:
    """Extract the literal COMMANDS dict from a cli module without importing it."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "COMMANDS" for t in node.targets):
            try:
                val = ast.literal_eval(node.value)
                if isinstance(val, dict):
                    return {str(k): str(v) for k, v in val.items()}
            except ValueError:
                return {}
    return {}


def discover() -> List[Tuple[str, Path]]:
    """(module_name, file) for every st/cli_*.py, sorted with core first."""
    mods = []
    for info in pkgutil.iter_modules([str(PKG_DIR)]):
        if info.name.startswith("cli_"):
            mods.append((info.name, PKG_DIR / (info.name + ".py")))
    mods.sort(key=lambda m: (m[0] != "cli_core", m[0]))
    return mods


class ShowtimeParser(argparse.ArgumentParser):
    """ArgumentParser whose errors say what went wrong and how to get help.

    Sub-parsers inherit this class (argparse uses type(parent) for them), so
    every `showtime <cmd> <sub>` reports bad arguments the same way.
    """

    def error(self, message: str) -> "NoReturn":  # type: ignore[name-defined]
        self.print_usage(sys.stderr)
        sys.stderr.write("%s %s\n  fix: run `%s --help` for every option, with examples\n"
                         % (paint("error:", "red"), message, self.prog))
        sys.exit(2)


class _Formatter(argparse.RawDescriptionHelpFormatter):
    def __init__(self, prog: str) -> None:
        super().__init__(prog, max_help_position=30, width=min(100, _term_width()))


def _term_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 100


def build_parser() -> argparse.ArgumentParser:
    parser = ShowtimeParser(
        prog="showtime",
        description="showtime: make videos locally (render, voice, music, footage, delivery).",
        epilog="Run `showtime --help` for the grouped command list with examples,\n"
               "and `showtime <command> --help` for details on one command.",
        formatter_class=_Formatter,
    )
    parser.add_argument("--version", action="version", version="showtime " + __version__)
    parser.add_argument("--debug", action="store_true", help="show tracebacks on errors (anywhere on the line)")
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    taken: Dict[str, str] = {}
    for mod_name, path in discover():
        try:
            mod = importlib.import_module("st." + mod_name)
        except Exception as e:  # noqa: BLE001 - keep the CLI usable
            _register_stubs(sub, mod_name, path, e, taken)
            continue
        register = getattr(mod, "register", None)
        if not callable(register):
            continue
        try:
            register(sub)
        except argparse.ArgumentError as e:
            error("%s: could not register commands: %s" % (mod_name, e))
            continue
        for name in read_commands(path) or {}:
            taken.setdefault(name, mod_name)
    return parser


def _register_stubs(sub, mod_name: str, path: Path, exc: BaseException, taken: Dict[str, str]) -> None:
    cmds = read_commands(path) or {mod_name[4:]: "(unavailable)"}
    reason = "%s: %s" % (type(exc).__name__, exc)

    def handler(args: argparse.Namespace, _reason: str = reason, _mod: str = mod_name) -> int:
        raise ShowtimeError("the '%s' commands are unavailable (%s)" % (_mod[4:], _reason),
                            hint="run `showtime doctor`; `showtime setup` installs missing dependencies")

    for name, help_text in cmds.items():
        if name in taken:
            continue
        p = sub.add_parser(name, help=help_text + " [unavailable]", add_help=True)
        p.add_argument("rest", nargs=argparse.REMAINDER)
        p.set_defaults(func=handler)
        taken[name] = mod_name


GLOBAL_FLAGS = ("--debug", "--no-color")


def _save_traceback() -> Optional[Path]:
    try:
        d = home() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "last-error.log"
        p.write_text("showtime %s\nargv: %r\n\n%s" % (__version__, sys.argv, traceback.format_exc()),
                     encoding="utf-8")
        return p
    except OSError:
        return None


def explain(exc: BaseException) -> ShowtimeError:
    """Turn an unexpected exception into a what / why / fix error."""
    import errno as _errno
    if isinstance(exc, ShowtimeError):
        return exc
    if isinstance(exc, FileNotFoundError):
        return ShowtimeError("file not found: %s" % (exc.filename or exc),
                             hint="check the path (relative paths start from %s)" % os.getcwd())
    if isinstance(exc, PermissionError):
        return ShowtimeError("permission denied: %s" % (exc.filename or exc),
                             hint="choose a folder you can write to, or fix the file's permissions")
    if isinstance(exc, OSError) and exc.errno == _errno.ENOSPC:
        return ShowtimeError("the disk is full", why=str(exc),
                             hint="free some space (`showtime clean <job>` removes render leftovers), then run the command again")
    if isinstance(exc, MemoryError):
        return ShowtimeError("ran out of memory", hint="try --preview, a shorter --from/--to range or fewer --workers")
    if isinstance(exc, ModuleNotFoundError):
        return ShowtimeError("a Python package is missing: %s" % exc.name,
                             why="the showtime environment is incomplete or this feature needs an optional extra",
                             hint="run `showtime doctor`; `showtime setup` installs what is missing")
    where = ""
    tb = exc.__traceback__
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    if tb is not None:
        where = " at %s:%d" % (Path(tb.tb_frame.f_code.co_filename).name, tb.tb_lineno)
    return ShowtimeError("unexpected %s: %s" % (type(exc).__name__, exc),
                         why="this is a bug in showtime%s (or an input it does not handle yet)" % where,
                         hint="re-run with --debug for the full traceback and report it with the command you ran")


def _chime(elapsed: float, rc: int, argv: Sequence[str]) -> None:
    """Opt-in sound logo after a long successful command (SHOWTIME_SOUND=1, terminals only)."""
    try:
        from .delight import maybe_chime
        maybe_chime(elapsed, ok=rc == 0, argv=argv)
    except Exception:  # noqa: BLE001 - never fail a finished command over a sound
        pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    debug_mode = "--debug" in argv or os.environ.get("SHOWTIME_DEBUG") == "1"
    if "--no-color" in argv:
        os.environ["NO_COLOR"] = "1"
    # global flags work anywhere on the line (`showtime audio mix x.json --debug`)
    argv = [a for a in argv if a not in GLOBAL_FLAGS]
    if debug_mode:
        os.environ["SHOWTIME_DEBUG"] = "1"
    parser = build_parser()
    if not argv:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        # A group was given without a sub-command: show that group's help.
        try:
            parser.parse_args(argv + ["--help"])
        except SystemExit:
            pass
        return 2
    from .common import progress_log_command, progress_log_end
    progress_log_command(argv)
    t0 = time.time()
    try:
        rc = int(func(args) or 0)
        progress_log_end(rc)
        _chime(time.time() - t0, rc, argv)
        return rc
    except KeyboardInterrupt:
        error("interrupted")
        progress_log_end(130, "interrupted")
        return 130
    except BrokenPipeError:
        return 0
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - every failure gets what / why / fix
        known = isinstance(e, ShowtimeError)
        if debug_mode:
            traceback.print_exc()
        saved = None if known else _save_traceback()
        err = explain(e)
        text = err.format(color=paint("x", "red") != "x")
        if saved is not None and not debug_mode:
            text += "\n  (traceback saved to %s)" % saved
        error(text)
        progress_log_end(err.code if known else 1, str(e))
        return err.code if known else 1


if __name__ == "__main__":
    sys.exit(main())

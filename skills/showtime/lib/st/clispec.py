"""What a `showtime` command accepts, read from the command line's own definitions.

The MCP server (mcp/server.mjs) maps each tool argument to a flag of the command it runs. This module
describes those commands the same way whichever side defines them, so tests/test_mcp.py can hold the
two against each other (a renamed flag, a new choice, a changed default fails there, not in a host):

  * Python commands: the argparse parser of `showtime <cmd> [<sub> ...]` (st.cli.build_parser, and
    st.doctor.build_parser for `doctor`, which the launcher runs before the CLI);
  * Node commands (scripts/<cmd>.mjs): their SPEC, printed by `--help-json` (scripts/lib/cli.mjs
    parseCli); positionals come from the usage line (`<name>` is required, `[name]` is optional).

describe(["render"]) -> {"command": "render", "source": "node", "options": {"--from": {...}}, "positionals": [...]}
Each option: kind ("bool" takes no value, "value", "list" repeats), type ("int", "float", "str" or None for
an unchecked string), choices (a list or None), required, help. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

SKILL = Path(__file__).resolve().parents[2]
SCRIPTS = SKILL / "scripts"

_BOOL_ACTIONS = (argparse._StoreTrueAction, argparse._StoreFalseAction, argparse._StoreConstAction,
                 argparse._CountAction)
_LIST_ACTIONS = (argparse._AppendAction, argparse._ExtendAction) if hasattr(argparse, "_ExtendAction") \
    else (argparse._AppendAction,)


def _type_name(t: Any) -> Optional[str]:
    if t is None or t is str:
        return None
    if t is int:
        return "int"
    if t is float:
        return "float"
    return "str"                     # a converter (a time, a size): takes text


def _help(a: argparse.Action) -> str:
    return "" if a.help in (None, argparse.SUPPRESS) else str(a.help).replace("%%", "%")


def _from_parser(p: argparse.ArgumentParser, command: str) -> Dict[str, Any]:
    options: Dict[str, Dict[str, Any]] = {}
    positionals: List[Dict[str, Any]] = []
    for a in p._actions:
        if isinstance(a, (argparse._HelpAction, argparse._VersionAction, argparse._SubParsersAction)):
            continue
        choices = sorted(str(c) for c in a.choices) if a.choices else None
        if not a.option_strings:
            positionals.append({"name": a.dest, "required": a.nargs not in ("?", "*"),
                                "many": a.nargs in ("*", "+"), "type": _type_name(a.type), "choices": choices,
                                "help": _help(a), "hidden": a.help == argparse.SUPPRESS})
            continue
        kind = "bool" if isinstance(a, _BOOL_ACTIONS) else "list" if isinstance(a, _LIST_ACTIONS) else "value"
        info = {"flags": list(a.option_strings), "kind": kind, "type": None if kind == "bool" else _type_name(a.type),
                "choices": choices, "required": bool(a.required), "help": _help(a), "hidden": a.help == argparse.SUPPRESS}
        for f in a.option_strings:
            options[f] = info
    return {"command": command, "source": "python", "options": options, "positionals": positionals}


_ROOT: Optional[argparse.ArgumentParser] = None


def _root() -> argparse.ArgumentParser:
    global _ROOT
    if _ROOT is None:
        from .cli import build_parser
        _ROOT = build_parser()
    return _ROOT


def _python_parser(words: Sequence[str]) -> Optional[argparse.ArgumentParser]:
    if list(words[:1]) == ["doctor"]:
        from .doctor import build_parser as doctor_parser
        return doctor_parser() if len(words) == 1 else None
    cur: argparse.ArgumentParser = _root()
    for w in words:
        subs = [a for a in cur._actions if isinstance(a, argparse._SubParsersAction)]
        if not subs or w not in subs[0].choices:
            return None
        cur = subs[0].choices[w]
    return cur


def _usage_positionals(usage: str, words: Sequence[str]) -> List[Dict[str, Any]]:
    """`showtime render <project> [-o out.mp4]` -> [{"name": "project", "required": True}]."""
    line = usage.splitlines()[0]
    rest = line.split(None, 1 + len(words))
    tail = rest[-1] if len(rest) > 1 + len(words) else ""
    out: List[Dict[str, Any]] = []
    for m in re.finditer(r"<([^<>]+)>(\s*\.\.\.)?|\[([^\[\]]+)\]", tail):
        if m.group(1):
            out.append({"name": m.group(1).strip(), "required": True, "many": bool(m.group(2)), "type": None,
                        "choices": None, "help": m.group(1).strip(), "hidden": False})
        elif not m.group(3).lstrip().startswith("-"):
            name = m.group(3).strip().strip("<>")
            out.append({"name": name, "required": False, "many": False, "type": None, "choices": None,
                        "help": name, "hidden": False})
    return out


def _node(words: Sequence[str], node: Optional[str] = None) -> Optional[Dict[str, Any]]:
    script = SCRIPTS / (words[0] + ".mjs")
    if not script.is_file():
        return None
    node = node or os.environ.get("SHOWTIME_NODE") or shutil.which("node")
    if not node:
        raise RuntimeError("describing `showtime %s` needs Node.js" % " ".join(words))
    cp = subprocess.run([node, str(script)] + list(words[1:]) + ["--help-json"], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=120,
                        env=dict(os.environ, NO_COLOR="1"))
    line = (cp.stdout.strip().splitlines() or [""])[-1]
    try:
        spec = json.loads(line)
    except ValueError:
        raise RuntimeError("`showtime %s --help-json` printed no spec (exit %s): %s"
                           % (" ".join(words), cp.returncode, (cp.stderr or cp.stdout)[-500:]))
    options: Dict[str, Dict[str, Any]] = {}
    for name, o in (spec.get("options") or {}).items():
        flags = ["--" + name] + (["-" + o["short"]] if o.get("short") else [])
        info = {"flags": flags, "kind": "bool" if o.get("type") == "boolean" else "list" if o.get("multiple") else "value",
                "type": None, "choices": None, "required": False, "help": o.get("help") or "", "hidden": False}
        for f in flags:
            options[f] = info
    # the shared flags every Node command takes
    for f, h in (("--debug", "show stack traces on errors"), ("--verbose", "full report on stdout")):
        options.setdefault(f, {"flags": [f], "kind": "bool", "type": None, "choices": None, "required": False,
                               "help": h, "hidden": False})
    return {"command": " ".join(words), "source": "node", "options": options,
            "positionals": _usage_positionals(spec.get("usage") or "", words)}


def describe(words: Sequence[str], node: Optional[str] = None) -> Dict[str, Any]:
    """The options and positionals of `showtime <words...>`; raises KeyError for an unknown command."""
    words = [w for w in words if w]
    p = _python_parser(words)
    if p is not None:
        return _from_parser(p, " ".join(words))
    d = _node(words, node)
    if d is None:
        raise KeyError("no command `showtime %s`" % " ".join(words))
    return d


if __name__ == "__main__":   # python -m st.clispec render | deliver exports ...
    import sys
    print(json.dumps(describe(sys.argv[1:]), indent=1))

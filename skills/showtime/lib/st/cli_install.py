"""`showtime install`: make showtime available in another coding agent (stdlib only).

The work is in st/hosts.py; this module is the command line around it.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import List

from .common import ShowtimeError, home, paint, print_json, skill_dir

COMMANDS = {
    "install": "Add showtime to another agent: skill, crew agents and MCP config (showtime install --agent codex)",
}

_F = argparse.RawDescriptionHelpFormatter


def register(sub: argparse._SubParsersAction) -> None:
    from . import hosts
    names = ", ".join(sorted(hosts.HOSTS))
    p = sub.add_parser("install", help=COMMANDS["install"], formatter_class=_F, description=(
        "Make showtime work in another coding agent. For the agent you name it adds, where that agent\n"
        "looks for them:\n"
        "  skill  a link to this skill folder (only where the agent does not already see it)\n"
        "  crew   the ten crew agents, in the agent's own format (not for agents without custom agents)\n"
        "  mcp    the showtime MCP server in the agent's config, started as <SHOWTIME_HOME>/bin/showtime mcp\n"
        "It never touches other settings: config files are merged (a copy of the original is kept once as\n"
        "<file>.before-showtime), and a file it cannot parse is left alone with the entry printed to paste.\n"
        "Run it again after updating showtime; --uninstall removes only what it added.\n\n"
        "Agents: " + names + "\n"
        "(Plugin routes bring all of this: Claude Code, Codex, Cursor, Devin and Copilot install the repository as a\n"
        "plugin; https://github.com/FavioVazquez/showtime/blob/main/docs/agents.md has the exact commands for each agent.)"),
        epilog=("Examples:\n"
                "  showtime install --agent codex               # for your user\n"
                "  showtime install --agent cursor --project    # into the current project only\n"
                "  showtime install --agent kiro --print        # show what it would write, change nothing\n"
                "  showtime install --agent gemini,opencode     # several at once\n"
                "  showtime install --agent codex --uninstall\n"
                "  showtime install --list                      # every agent, and where showtime is installed"))
    p.add_argument("--agent", "-a", metavar="NAME[,NAME]", help="the agent(s) to install into: " + names)
    p.add_argument("--project", nargs="?", const=".", metavar="DIR",
                   help="install into this project folder (default: the current folder) instead of for your user")
    p.add_argument("--print", dest="dry_run", action="store_true",
                   help="print what would be written (files and config entries) and change nothing")
    p.add_argument("--uninstall", action="store_true", help="remove what `showtime install` added for that agent")
    p.add_argument("--no-skill", action="store_true", help="skip the skill link")
    p.add_argument("--no-crew", action="store_true", help="skip the crew agents")
    p.add_argument("--no-mcp", action="store_true", help="skip the MCP server entry")
    p.add_argument("--list", action="store_true", help="list the agents it knows and where showtime is installed")
    p.add_argument("--json", action="store_true", help="machine-readable result")
    p.set_defaults(func=cmd_install)


def _hosts(spec: str) -> List:
    from . import hosts
    out = []
    for name in [s for s in spec.replace(" ", ",").split(",") if s]:
        try:
            h = hosts.resolve_host(name)
        except KeyError:
            raise ShowtimeError("unknown agent %r" % name, why="showtime install knows: %s" % ", ".join(sorted(hosts.HOSTS)),
                                hint="pick one of those names, e.g. `showtime install --agent codex`", code=2)
        if h not in out:
            out.append(h)
    if not out:
        raise ShowtimeError("no agent named", hint="`showtime install --agent codex` (or --list)", code=2)
    return out


STATE_COLOR = {"created": "green", "updated": "green", "removed": "green", "unchanged": "dim", "done": "green",
               "kept": "dim", "skipped": "yellow", "paste": "yellow", "run": "yellow", "failed": "red"}


def _print_plan(plan, dry: bool) -> None:
    h = plan.host
    print(paint("%s%s (%s)" % ("would install into " if dry else "", h.label, plan.where.scope), "bold"))
    for a in plan.actions:
        if dry and a["state"] == "would write" and a["kind"] == "crew":
            print("  %-6s %s" % (a["kind"], a["path"]))
            print("\n".join("         | " + ln for ln in a["content"].splitlines()[:6]) + "\n         | ...")
            continue
        state = paint(a["state"], STATE_COLOR.get(a["state"], "cyan"))
        where = a["path"] or ""
        line = "  %-6s %s %s" % (a["kind"], state, where)
        if a["detail"]:
            line += ("  (%s)" % a["detail"]) if where else a["detail"]
        print(line.rstrip())
        if a["content"] and (a["state"] in ("paste", "would write") or dry):
            print("\n".join("         " + ln for ln in a["content"].rstrip("\n").splitlines()))
    for n in plan.notes:
        print("  note   " + n)


def cmd_install(args: argparse.Namespace) -> int:
    from . import hosts
    h_home = home()
    if args.list:
        rows = [{"agent": k, "label": v.label, "crew": bool(v.crew), "mcp": (v.mcp or ("",))[0] or None}
                for k, v in sorted(hosts.HOSTS.items())]
        inst = hosts.installed(h_home)
        if args.json:
            print_json({"agents": rows, "installed": inst})
            return 0
        print("Agents showtime can install into (showtime install --agent <name>):")
        for r in rows:
            print("  %-12s %s%s" % (r["agent"], r["label"], "" if r["crew"] else "  (no crew: the host has no custom agents)"))
        if inst:
            print("\nInstalled by this command:")
            for e in inst:
                print("  %-12s %s %s" % (e["host"], e["scope"], e["root"]))
        return 0
    if not args.agent:
        raise ShowtimeError("which agent?", hint="`showtime install --agent codex` (see `showtime install --list`)", code=2)
    project = Path(args.project).resolve() if args.project else None
    if project is not None and not project.is_dir():
        raise ShowtimeError("%s is not a folder" % project, hint="pass an existing project folder to --project", code=2)
    where = hosts.Where(Path(os.path.expanduser("~")), project)
    parts = [p for p, off in (("skill", args.no_skill), ("crew", args.no_crew), ("mcp", args.no_mcp)) if not off]
    results = []
    for h in _hosts(args.agent):
        if args.uninstall:
            plan = hosts.uninstall(h, where, h_home, skill_dir(), write=not args.dry_run)
        else:
            plan = hosts.install(h, where, h_home, skill_dir(), write=not args.dry_run, parts=parts)
        results.append(plan)
    if args.json:
        print_json({"results": [p.as_json() for p in results], "dry_run": args.dry_run})
    else:
        for i, plan in enumerate(results):
            if i:
                print()
            _print_plan(plan, args.dry_run)
        if not args.uninstall and not args.dry_run:
            print("\nStart a new session of the agent so it picks up the changes; then ask it for a video.")
    failed = any(a["state"] == "failed" for p in results for a in p.actions)
    return 1 if failed else 0

#!/usr/bin/env python3
"""Keep the crew agent copies in sync with agents/*.md (stdlib only, any OS, Python 3.8+).

    python scripts/build_agents.py            # rewrite the copies that are out of date
    python scripts/build_agents.py --check    # exit 1 and name the stale files (CI, tests)

agents/*.md (Claude Code format) is the only source. Two copies are generated from it and committed:

  skills/showtime/setup/agents/*.md        verbatim, so a skill installed on its own (npx skills add, a
                                           copied folder) still has the crew for `showtime install --agent`
  com.github.copilot/agents/*.agent.md     GitHub Copilot's format, in the client folder the Agent Plugins
                                           spec gives each host: Copilot reads a root plugin.json first and
                                           takes agents only from com.github.copilot/agents/ then
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "skills" / "showtime" / "lib"))

from st import hosts  # noqa: E402

AGENTS = REPO / "agents"
SKILL_COPY = REPO / "skills" / "showtime" / "setup" / "agents"
COPILOT = REPO / "com.github.copilot" / "agents"


def wanted(repo: Path = REPO) -> Dict[Path, str]:
    """{path: content} of every generated file."""
    out: Dict[Path, str] = {}
    for f in sorted((repo / "agents").glob("*.md")):
        text = f.read_text(encoding="utf-8")
        out[repo / "skills" / "showtime" / "setup" / "agents" / f.name] = text
        meta, body = hosts.parse_agent(text)
        name, content = hosts.render_agent("copilot", meta, body, hosts.PLUGIN_REF)
        out[repo / "com.github.copilot" / "agents" / name] = content
    return out


def stale(repo: Path = REPO) -> List[Path]:
    want = wanted(repo)
    bad = [p for p, t in want.items() if not p.is_file() or p.read_text(encoding="utf-8") != t]
    for d in (repo / "skills" / "showtime" / "setup" / "agents", repo / "com.github.copilot" / "agents"):
        if d.is_dir():
            bad += [p for p in sorted(d.iterdir()) if p.is_file() and p not in want]
    return bad


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="only report stale copies (exit 1 when any)")
    args = ap.parse_args(argv)
    bad = stale()
    if args.check:
        for p in bad:
            print("stale: %s" % p.relative_to(REPO))
        if bad:
            print("fix: python scripts/build_agents.py")
        return 1 if bad else 0
    want = wanted()
    for p in bad:
        if p in want:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(str(p), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(want[p])
            print("wrote %s" % p.relative_to(REPO))
        else:
            p.unlink()
            print("removed %s" % p.relative_to(REPO))
    if not bad:
        print("crew copies are up to date (%d files)" % len(want))
    return 0


if __name__ == "__main__":
    sys.exit(main())

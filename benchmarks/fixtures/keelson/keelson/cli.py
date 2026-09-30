"""The keelson command: check, diff and init."""
import argparse
import os
import sys
from typing import List, Optional

from . import __version__, envfile, report, rules


def cmd_check(a) -> int:
    try:
        env, example = envfile.read(a.env), envfile.read(a.example)
    except (OSError, envfile.ParseError) as e:
        print("keelson: %s" % e, file=sys.stderr)
        return report.CANNOT_READ
    found = rules.check(env, example, a.env, a.example, strict=a.strict)
    print(report.as_json(found) if a.format == "json" else report.text(found, "%s vs %s" % (a.env, a.example)))
    return report.exit_code(found)


def cmd_diff(a) -> int:
    try:
        d = rules.diff(envfile.read(a.first), envfile.read(a.second))
    except (OSError, envfile.ParseError) as e:
        print("keelson: %s" % e, file=sys.stderr)
        return report.CANNOT_READ
    for label, keys in (("only in " + a.first, d["only_in_first"]), ("only in " + a.second, d["only_in_second"]),
                        ("different values", d["different_values"])):
        print("%s: %s" % (label, ", ".join(keys) if keys else "none"))
    return report.OK


def cmd_init(a) -> int:
    if os.path.exists(a.example) and not a.force:
        print("keelson: %s exists (use --force to overwrite)" % a.example, file=sys.stderr)
        return report.FOUND_ERRORS
    try:
        with open(a.env, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as e:
        print("keelson: %s" % e, file=sys.stderr)
        return report.CANNOT_READ
    out = []
    for line in lines:
        m = envfile.KEY_RE.match(line.strip())
        out.append(line if not m else ("export " if line.strip().startswith("export ") else "") + m.group(1) + "=")
    with open(a.example, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print("wrote %s (%d keys, values blanked)" % (a.example, sum(1 for l in out if l.endswith("="))))
    return report.OK


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="keelson", description="Check a .env file against .env.example.")
    ap.add_argument("--version", action="version", version="keelson " + __version__)
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("check", help="compare an env file with its example")
    c.add_argument("--env", default=".env")
    c.add_argument("--example", default=".env.example")
    c.add_argument("--strict", action="store_true", help="empty values are errors")
    c.add_argument("--format", choices=["text", "json"], default="text")
    c.set_defaults(fn=cmd_check)
    d = sub.add_parser("diff", help="keys that differ between two env files (values never printed)")
    d.add_argument("first")
    d.add_argument("second")
    d.set_defaults(fn=cmd_diff)
    i = sub.add_parser("init", help="write .env.example from .env with values blanked")
    i.add_argument("--env", default=".env")
    i.add_argument("--example", default=".env.example")
    i.add_argument("--force", action="store_true")
    i.set_defaults(fn=cmd_init)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

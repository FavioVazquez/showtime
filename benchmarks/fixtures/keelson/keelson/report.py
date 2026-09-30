"""Print findings as text or JSON and choose the exit code. Values are never printed."""
import json
from typing import List

from .rules import Finding

OK, FOUND_ERRORS, CANNOT_READ = 0, 1, 2


def exit_code(findings: List[Finding]) -> int:
    return FOUND_ERRORS if any(f.severity == "error" for f in findings) else OK


def text(findings: List[Finding], title: str) -> str:
    lines = [title]
    width = max([len(f.key) for f in findings] + [8])
    for f in findings:
        lines.append("  %-8s %-10s %-*s  (%s)" % (f.severity, f.rule, width, f.key, f.where))
    errors = sum(f.severity == "error" for f in findings)
    warnings = len(findings) - errors
    lines.append("%d error%s, %d warning%s" % (errors, "" if errors == 1 else "s", warnings, "" if warnings == 1 else "s")
                 if findings else "all keys match")
    return "\n".join(lines)


def as_json(findings: List[Finding]) -> str:
    return json.dumps({"findings": [f._asdict() for f in findings],
                       "errors": sum(f.severity == "error" for f in findings),
                       "warnings": sum(f.severity == "warning" for f in findings)}, indent=2)

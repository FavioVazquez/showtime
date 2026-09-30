"""Parse env files: KEY=value lines, `export KEY=value`, comments, blank lines and quoted values."""
import re
from typing import List, NamedTuple

KEY_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


class Entry(NamedTuple):
    key: str
    value: str
    line: int


class ParseError(ValueError):
    pass


def _unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        return raw[1:-1]
    if " #" in raw:  # an inline comment after an unquoted value
        raw = raw.split(" #", 1)[0].rstrip()
    return raw


def parse(text: str, name: str = "<env>") -> List[Entry]:
    entries = []
    for n, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = KEY_RE.match(s)
        if not m:
            raise ParseError("%s line %d: expected KEY=value, got %r" % (name, n, s[:40]))
        entries.append(Entry(m.group(1), _unquote(m.group(2)), n))
    return entries


def read(path: str) -> List[Entry]:
    with open(path, encoding="utf-8") as fh:
        return parse(fh.read(), path)

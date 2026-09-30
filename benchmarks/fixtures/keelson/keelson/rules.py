"""Compare an env file with its example. Each rule returns findings; nothing here prints."""
from typing import Dict, List, NamedTuple

from .envfile import Entry


class Finding(NamedTuple):
    severity: str   # "error" or "warning"
    rule: str       # missing, extra, duplicate, empty
    key: str
    where: str


def _first(entries: List[Entry]) -> Dict[str, Entry]:
    out: Dict[str, Entry] = {}
    for e in entries:
        out.setdefault(e.key, e)
    return out


def missing(env: List[Entry], example: List[Entry], env_name: str, ex_name: str) -> List[Finding]:
    have = _first(env)
    return [Finding("error", "missing", e.key, "line %d of %s" % (e.line, ex_name))
            for e in _first(example).values() if e.key not in have]


def extra(env: List[Entry], example: List[Entry], env_name: str, ex_name: str) -> List[Finding]:
    known = _first(example)
    return [Finding("warning", "extra", e.key, "line %d of %s, not in %s" % (e.line, env_name, ex_name))
            for e in _first(env).values() if e.key not in known]


def duplicate(env: List[Entry], example: List[Entry], env_name: str, ex_name: str) -> List[Finding]:
    seen: Dict[str, int] = {}
    out = []
    for e in env:
        if e.key in seen:
            out.append(Finding("error", "duplicate", e.key, "lines %d and %d of %s" % (seen[e.key], e.line, env_name)))
        else:
            seen[e.key] = e.line
    return out


def empty(env: List[Entry], example: List[Entry], env_name: str, ex_name: str, strict: bool = False) -> List[Finding]:
    sev = "error" if strict else "warning"
    return [Finding(sev, "empty", e.key, "line %d of %s" % (e.line, env_name)) for e in _first(env).values() if e.value == ""]


def check(env: List[Entry], example: List[Entry], env_name: str = ".env", ex_name: str = ".env.example",
          strict: bool = False) -> List[Finding]:
    found = []
    for rule in (missing, duplicate, extra):
        found += rule(env, example, env_name, ex_name)
    found += empty(env, example, env_name, ex_name, strict)
    order = {"error": 0, "warning": 1}
    return sorted(found, key=lambda f: order[f.severity])


def diff(a: List[Entry], b: List[Entry]) -> Dict[str, List[str]]:
    ka, kb = _first(a), _first(b)
    return {"only_in_first": sorted(set(ka) - set(kb)), "only_in_second": sorted(set(kb) - set(ka)),
            "different_values": sorted(k for k in set(ka) & set(kb) if ka[k].value != kb[k].value)}

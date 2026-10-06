#!/usr/bin/env python3
"""Re-check the free graders of a plugin-eval case on a recorded trace, offline and at no cost.

`claude plugin eval` grades every run once, while it runs. This reads the same case files
(benchmarks/plugin-eval/<case>/prompt.md and graders/*.md) and applies the deterministic graders
(`regex`, `tool_used`) to a recorded trace (the run's stream-json, `trace.jsonl`), so a pattern can be
tightened and checked against earlier runs without spending a token. Model graders (`llm`, `baseline`)
are listed as "needs a judge" and not scored here.

    python3 benchmarks/scoring/eval_graders.py benchmarks/plugin-eval/missing-input trace.jsonl [...]
    python3 benchmarks/scoring/eval_graders.py <case dir> <trace> --arm without

How a grader reads a trace (the eval's own rules, as documented for `claude plugin eval`):
  last_message  the final reply: the result line's text, else the last assistant message's text
  trace         every line of the trace
  tool_used     calls of `tool` whose input, as compact JSON, matches `input_match`; passes when the count is
                within [min (default 1), max]. Without `arm`, a `tool_used: Skill` grader is a with-only
                indicator in a two-arm run (reported, not scored); `arm: both` scores it in both arms.
Patterns are JavaScript regexes; the ones used here are also valid Python (named groups are converted).

Stdlib only, Python 3.8+.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

FREE = ("regex", "tool_used")
PAID = ("llm", "baseline")
TYPES = FREE + PAID + ("tool_order", "file_exists")
# the frontmatter keys `claude plugin eval` accepts in prompt.md (anything else is refused at load time)
PROMPT_KEYS = {"schema_version", "name", "description", "tags", "plugins", "runs", "expected_outcome",
               "model", "max_turns", "timeout_seconds", "allowed_tools", "artifact_publish",
               "growthbook_overrides", "append_system_prompt", "env"}
GRADER_KEYS = {
    "regex": {"type", "name", "target", "pattern", "flags", "match", "weight", "arm"},
    "tool_used": {"type", "name", "tool", "input_match", "min", "max", "weight", "arm"},
    "llm": {"type", "name", "criteria", "focus", "weight", "arm"},
}


# ------------------------------------------------------------------ case files

def _scalar(v: str) -> Any:
    v = v.strip()
    if not v:
        return ""
    if v[0] == "'" and v[-1] == "'" and len(v) >= 2:
        return v[1:-1].replace("''", "'")
    if v[0] == '"' and v[-1] == '"' and len(v) >= 2:
        return json.loads(v)
    if v[0] == "[" and v[-1] == "]":
        return [_scalar(x) for x in v[1:-1].split(",") if x.strip()]
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v)
    if v in ("true", "false"):
        return v == "true"
    return v


def frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """The flat `key: value` frontmatter of a case file (the forms these cases use) and the body."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm: Dict[str, Any] = {}
    for line in text[3:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        k, sep, v = line.partition(":")
        if not sep:
            raise ValueError("not a key: value line: %r" % line)
        fm[k.strip()] = _scalar(v)
    body = text[end + 4:]
    return fm, body.lstrip("\n")


def load_case(case_dir: Path) -> Dict[str, Any]:
    case_dir = Path(case_dir)
    fm, body = frontmatter((case_dir / "prompt.md").read_text(encoding="utf-8"))
    graders = []
    for g in sorted((case_dir / "graders").glob("*.md")):
        gfm, gbody = frontmatter(g.read_text(encoding="utf-8"))
        gfm = dict(gfm, name=g.stem)
        if gfm.get("type") in PAID and gbody.strip():
            gfm["criteria"] = gbody.strip()
        graders.append(gfm)
    return {"name": case_dir.name, "dir": str(case_dir), "frontmatter": fm, "prompt": body.strip(),
            "tags": list(fm.get("tags") or []), "graders": graders}


# ------------------------------------------------------------------ traces

def read_trace(path: Path) -> List[Dict[str, Any]]:
    out = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def last_message(events: List[Dict[str, Any]]) -> str:
    for e in reversed(events):
        if e.get("type") == "result" and isinstance(e.get("result"), str) and e["result"].strip():
            return e["result"]
    last_id, parts = None, []
    for e in events:
        if e.get("type") != "assistant" or e.get("parent_tool_use_id"):
            continue
        msg = e.get("message") or {}
        texts = [b.get("text", "") for b in msg.get("content") or [] if isinstance(b, dict) and b.get("type") == "text"]
        if not texts:
            continue
        mid = msg.get("id")
        if mid is None or mid != last_id:
            parts = []
        last_id = mid
        parts += texts
    return "\n".join(parts)


def tool_calls(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for e in events:
        if e.get("type") != "assistant":
            continue
        for b in (e.get("message") or {}).get("content") or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                seen[str(b.get("id") or len(seen))] = b
    return list(seen.values())


# ------------------------------------------------------------------ graders

def js_regex(pattern: str, flags: str = "") -> "re.Pattern[str]":
    f = 0
    if "i" in flags:
        f |= re.IGNORECASE
    if "m" in flags:
        f |= re.MULTILINE
    if "s" in flags:
        f |= re.DOTALL
    return re.compile(re.sub(r"\(\?<([A-Za-z_]\w*)>", r"(?P<\1>", pattern), f)


def scored(grader: Dict[str, Any], arm: str) -> bool:
    """Whether a grader counts toward the run's score in this arm (two-arm rules)."""
    if grader.get("arm") == "with-only":
        return arm == "with"
    if grader.get("arm") is None and grader.get("type") == "tool_used" and grader.get("tool") == "Skill":
        return False                       # the plugin-fired indicator: reported, never scored
    return True


def grade(grader: Dict[str, Any], events: List[Dict[str, Any]], raw: str = "") -> Dict[str, Any]:
    """{name, type, passed (True/False, None for a judge grader), explanation}."""
    typ = grader.get("type")
    out: Dict[str, Any] = {"name": grader.get("name"), "type": typ}
    if typ == "regex":
        target = grader.get("target", "last_message")
        if target == "last_message":
            text = last_message(events)
        elif target == "trace":
            text = raw or "\n".join(json.dumps(e) for e in events)
        else:
            return dict(out, passed=None, explanation="target %r is not read offline" % (target,))
        rx = js_regex(str(grader["pattern"]), str(grader.get("flags", "")))
        n = sum(1 for _ in rx.finditer(text))
        match = str(grader.get("match", "contains"))
        if match == "contains":
            ok = n > 0
        elif match == "not_contains":
            ok = n == 0
        elif match.startswith("count:"):
            ok = n == int(match[6:])
        else:
            raise ValueError("unknown match %r" % match)
        return dict(out, passed=ok, explanation="%d match(es) in %s, expected %s" % (n, target, match))
    if typ == "tool_used":
        rx = js_regex(str(grader["input_match"])) if grader.get("input_match") else None
        n = 0
        for c in tool_calls(events):
            if c.get("name") != grader.get("tool"):
                continue
            if rx is None or rx.search(json.dumps(c.get("input") or {}, separators=(",", ":"), ensure_ascii=False)):
                n += 1
        lo = int(grader.get("min", 1))
        hi = grader.get("max")
        ok = n >= lo and (hi is None or n <= int(hi))
        return dict(out, passed=ok, explanation="%s called %dx (expected %d..%s)" % (
            grader.get("tool"), n, lo, "any" if hi is None else hi))
    if typ in PAID:
        return dict(out, passed=None, explanation="needs a judge (model grader): not scored offline")
    return dict(out, passed=None, explanation="grader type %r is not read offline" % (typ,))


def grade_case(case: Dict[str, Any], trace: Path, arm: str = "with") -> List[Dict[str, Any]]:
    raw = Path(trace).read_text(encoding="utf-8", errors="replace")
    events = read_trace(trace)
    res = []
    for g in case["graders"]:
        r = grade(g, events, raw)
        r["scored"] = scored(g, arm)
        res.append(r)
    return res


def check_case_files(case: Dict[str, Any]) -> List[str]:
    """Problems `claude plugin eval` would refuse or that break the scoreboard (empty list: fine)."""
    probs = []
    for k in case["frontmatter"]:
        if k not in PROMPT_KEYS:
            probs.append("prompt.md: unknown frontmatter key %r" % k)
    if not case["prompt"]:
        probs.append("prompt.md: no prompt")
    if not case["graders"]:
        probs.append("no graders")
    for g in case["graders"]:
        t = g.get("type")
        if t not in TYPES:
            probs.append("%s: unknown type %r" % (g["name"], t))
            continue
        extra = set(g) - GRADER_KEYS.get(t, set(g))
        if extra:
            probs.append("%s: keys %s are not valid for %s" % (g["name"], sorted(extra), t))
        if t == "regex":
            try:
                js_regex(str(g.get("pattern", "")), str(g.get("flags", "")))
            except re.error as e:
                probs.append("%s: pattern does not compile: %s" % (g["name"], e))
            if not str(g.get("pattern", "")):
                probs.append("%s: empty pattern" % g["name"])
        if t in PAID and not g.get("criteria"):
            probs.append("%s: no criteria" % g["name"])
    return probs


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("case", help="a case folder, e.g. benchmarks/plugin-eval/missing-input")
    ap.add_argument("traces", nargs="+", help="recorded trace.jsonl files")
    ap.add_argument("--arm", choices=("with", "without"), default="with")
    a = ap.parse_args(list(argv) if argv is not None else None)
    case = load_case(Path(a.case))
    probs = check_case_files(case)
    for p in probs:
        print("case problem: %s" % p)
    worst = 1 if probs else 0
    for t in a.traces:
        print("%s (%s arm):" % (t, a.arm))
        for r in grade_case(case, Path(t), a.arm):
            mark = {True: "PASS", False: "FAIL", None: "----"}[r["passed"]]
            note = "" if r["scored"] else "  [not scored in this arm]"
            print("  %s  %s: %s%s" % (mark, r["name"], r["explanation"], note))
            if r["passed"] is False and r["scored"]:
                worst = 1
    return worst


if __name__ == "__main__":
    sys.exit(main())

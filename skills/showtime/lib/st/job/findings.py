"""Critic findings that gate delivery: every Blocker and Should-fix is fixed or waived before a job finishes.

Once a critic has answered (any FINDINGS.md in <job>/review/, quality or lean mode, a self-review included),
`showtime job note <job> --stage deliver` refuses to record the delivery while a Blocker or Should-fix is
open, and `qa`, `status`, `deliver exports` and the receipt name what is open. A job no critic answered keeps
its old behaviour (quality mode says "review pending"; lean says nothing). Polish never gates.

Each finding has an id from its place in the file, so the maker and a later critic can name it:
  r1-B2     round 1's FINDINGS.md, the second bullet under BLOCKERS (S: SHOULD-FIX)
  r2o1-S1   round 2 is pairwise: order-1/FINDINGS.md, the first SHOULD-FIX bullet
Which findings count: every Blocker and Should-fix bullet of a single round ("none" is no finding); in a
pairwise round only those tagged with the version that came out best (review-verdict's winner; before the
verdict, the new version). A finding about the version that lost is not about the video that ships.

Statements, one per line (a bullet, backticks or bold around them are fine):
  fixed r1-S2: what changed            the maker (review/round-N/RESPONSE.md) or a later critic (PREVIOUS)
  not fixed r1-S2: what is still wrong a later critic, or the maker: opens it again
  waived r1-S2: why it ships as is     the maker only (RESPONSE.md); `won't fix r1-S2: ...` is the same
Several ids may share one statement (`fixed r1-S1, r1-S2: ...`). A waiver needs its reason; a critic cannot
waive. Statements are read oldest round first, the critic's FINDINGS.md before the maker's RESPONSE.md in each
round, and the last one about an id wins. `showtime review-respond` writes the maker's lines into the latest
answered round's RESPONSE.md (an unanswered round is rebuilt by review-pack, so nothing is written there).

A critic that cannot write files returns its answer as text; `showtime review-findings` cuts the reply to the
answer (extract), checks it against CRITIC.md's format (shape) and saves it as the round's FINDINGS.md.

Read-only and stdlib only, like st.job.review_state.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

KEYS = ".pairwise-keys"            # st.qa.pairwise.KEYS
RESPONSE = "RESPONSE.md"
SEVERITY = {"B": "blocker", "S": "should-fix"}

# a section heading: "BLOCKERS:", "**SHOULD-FIX:**", "## Polish", "FIRST VIEWER (one line per part):"
_HEAD = re.compile(r"^\W*(BLOCKERS?|SHOULD[- ]?FIX(?:ES)?|POLISH|WHAT WORKS|DECLINED TO JUDGE|BEST POSTER FRAME|"
                   r"VERDICT|PREFERENCE|WOULD I POST|PREVIOUS|FIRST[- ]VIEWER|HEARING)\b", re.I)
_BULLET = re.compile(r"^(?:[-*+•]|\d+[.)])\s+(.*)$")
_EMPTY = re.compile(r"^\W*(none|n/?a|nothing|no\s+(blockers?|should[- ]?fix(es)?|findings?|issues?))\b\W*$|^\W*$|^\.\.\.$",
                    re.I)
_LABEL = re.compile(r"\[\s*([XY])\s*\]")
_SIDE_FRAME = re.compile(r"(?:^|[\s(`/\\])\.\./([XY])[/\\]|(?:^|[\s(`])([XY])[/\\]frames[/\\]")
ID = r"r\d+(?:o[12])?-[BS]\d+"
_ID = re.compile(ID, re.I)
_STATEMENT = re.compile(r"^(not\s+fixed|fixed|waived?|won['\u2019]?t\s+fix|will\s+not\s+fix)\s*[:(\[]?\s*"
                        r"(%s(?:\s*[\])]?\s*(?:,|&|\band\b)\s*[\[(]?\s*%s)*)\s*[\])*_]*\s*(?:[:\-–—]+\s*(.*))?$"
                        % (ID, ID), re.I)


def _read(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _text(f: Path) -> str:
    try:
        return f.read_text(encoding="utf-8", errors="replace")[:60000] if f.is_file() else ""
    except OSError:
        return ""


def norm_id(s: str) -> str:
    """'R1-s2' -> 'r1-S2' (ids are matched without regard to case)."""
    m = re.fullmatch(r"\s*r(\d+)(?:o([12]))?-([BS])(\d+)\s*", s, re.I)
    if not m:
        return s.strip()
    return "r%s%s-%s%s" % (m.group(1), "o" + m.group(2) if m.group(2) else "", m.group(3).upper(), m.group(4))


# ------------------------------------------------------------------ parsing one FINDINGS.md

def parse(text: str, prefix: str) -> List[Dict[str, Any]]:
    """The Blocker and Should-fix bullets of one FINDINGS.md, in order: [{id, severity, text, video}].
    prefix is "r1" (a single round) or "r2o1" (order 1 of pairwise round 2); video is the [X]/[Y] tag of a
    pairwise finding (None when it names neither)."""
    out: List[Dict[str, Any]] = []
    sev: Optional[str] = None
    count = {"B": 0, "S": 0}
    for raw in text.splitlines():
        line = raw.strip().strip("`").strip()
        b = _BULLET.match(line)
        if b:
            body = b.group(1)
        else:
            h = _HEAD.match(line)
            if h:
                word = h.group(1).upper()
                sev = "B" if word.startswith("BLOCKER") else "S" if word.startswith("SHOULD") else None
            # a finding on the heading's own line ("BLOCKERS: t=0.00s frames/... black"), not a "(...)" note
            body = line[h.end():].lstrip(" :*_") if h and sev else ""
            if not body or body.startswith("("):
                continue
        if sev is None:
            continue
        body = body.strip().strip("`").strip()
        if _EMPTY.match(body):
            continue
        count[sev] += 1
        lab = _LABEL.search(body)
        side = None if lab else _SIDE_FRAME.search(body)
        video = lab.group(1).upper() if lab else ((side.group(1) or side.group(2)).upper() if side else None)
        out.append({"id": "%s-%s%d" % (prefix, sev, count[sev]), "severity": SEVERITY[sev], "text": " ".join(body.split()),
                    "video": video})
    return out


def statements(text: str, who: str) -> List[Dict[str, Any]]:
    """fixed / not fixed / waived lines of one file: [{ids, status, note, by}]. who: 'critic' or 'maker';
    a critic's waiver does not count, and a waiver without a reason is no waiver."""
    out: List[Dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        b = _BULLET.match(line)
        line = (b.group(1) if b else line).strip().strip("`*_").strip()
        m = _STATEMENT.match(line)
        if not m:
            continue
        verb = m.group(1).lower()
        note = re.sub(r"\s*\(finding:.*$", "", " ".join((m.group(3) or "").split())).strip("`*_ ").lstrip("> ")
        status = "open" if verb.startswith("not") else "fixed" if verb == "fixed" else "waived"
        if status == "waived" and (who != "maker" or not note):
            continue
        out.append({"ids": [norm_id(i) for i in _ID.findall(m.group(2))], "status": status, "note": note, "by": who})
    return out


# ------------------------------------------------------------------ the job

def _round_dirs(job: Path) -> List[Tuple[int, Path]]:
    root = job / "review"
    out = []
    if root.is_dir():
        for d in root.glob("round-*"):
            m = re.fullmatch(r"round-(\d+)", d.name)
            if m and d.is_dir():
                out.append((int(m.group(1)), d))
    return sorted(out)


def _answered(f: Path) -> bool:
    return f.is_file() and f.stat().st_size > 0


def _best_label(root: Path, n: int, d: Path) -> Optional[str]:
    """The label ([X]/[Y]) of the version that came out best in pairwise round n (before review-verdict: the
    new one); None when the round is not pairwise."""
    key = _read(root / KEYS / ("round-%d.json" % n))
    if not isinstance(key, dict):
        return None
    v = _read(d / "verdict.json")
    winner = "new"
    if isinstance(v, dict) and v.get("winner") in ("new", "old"):
        winner = v["winner"]
    elif isinstance(v, dict) and "improved" in v:
        winner = "new" if v.get("improved") else "old"
    lab = (key.get(winner) or {}).get("label") if isinstance(key.get(winner), dict) else None
    return str(lab).upper() if lab else "?"


def collect(job: Path) -> Dict[str, Any]:
    """Every gating finding of the job with its state:
    {applies, findings: [{id, round, severity, text, file, status, by, note}], open, fixed, waived, unknown}.
    applies: a critic answered at least once (otherwise nothing here gates)."""
    rounds = _round_dirs(job)
    found: List[Dict[str, Any]] = []
    stmts: List[Dict[str, Any]] = []
    applies = False
    for n, d in rounds:
        best = _best_label(job / "review", n, d)
        files = [(d / "FINDINGS.md", "r%d" % n)] if best is None else \
            [(d / ("order-%d" % k) / "FINDINGS.md", "r%do%d" % (n, k)) for k in (1, 2)]
        for f, prefix in files:
            if not _answered(f):
                continue
            applies = True
            text = _text(f)
            for it in parse(text, prefix):
                if best is not None and it["video"] != best:
                    continue            # about the version that lost, or names no version: not the video that ships
                found.append({"id": it["id"], "round": n, "severity": it["severity"], "text": it["text"],
                              "file": str(f), "status": "open", "by": None, "note": ""})
            stmts += statements(text, "critic")
        stmts += statements(_text(d / RESPONSE), "maker")
    by_id = {f["id"]: f for f in found}
    unknown: List[str] = []
    for s in stmts:
        for i in s["ids"]:
            f = by_id.get(i)
            if f is None:
                unknown.append(i)
                continue
            f.update(status=s["status"], by=s["by"], note=s["note"])
    sev = {"blocker": 0, "should-fix": 1}
    found.sort(key=lambda f: (f["status"] != "open", sev[f["severity"]], f["round"], f["id"]))
    return {"applies": applies, "findings": found,
            "open": [f for f in found if f["status"] == "open"],
            "fixed": [f for f in found if f["status"] == "fixed"],
            "waived": [f for f in found if f["status"] == "waived"],
            "unknown": sorted(set(unknown))}


def latest_answered_round(job: Path) -> Optional[Path]:
    """The newest round folder a critic answered: where the maker's RESPONSE.md lines go."""
    for n, d in reversed(_round_dirs(job)):
        if _answered(d / "FINDINGS.md") or any(_answered(d / ("order-%d" % k) / "FINDINGS.md") for k in (1, 2)):
            return d
    return None


# ------------------------------------------------------------------ messages

def short(f: Dict[str, Any], width: int = 110) -> str:
    t = f["text"]
    return t if len(t) <= width else t[:width - 1].rstrip() + "…"


def how_to(job_name: str, ids: Sequence[str] = ()) -> str:
    """The exact commands that close a finding."""
    i = ids[0] if ids else "<id>"
    return ("fix %s, then record it: showtime review-respond %s --fixed %s \"what changed\"; or, to ship it as is, "
            "waive it with a one-line reason: showtime review-respond %s --waive %s \"why\" (a blocker only with "
            "the user's OK)" % ("each" if len(ids) > 1 else "it", job_name, i, job_name, i))


def summary(g: Dict[str, Any]) -> str:
    """'2 critic findings open: r1-B1 (blocker) ..., r1-S2 (should-fix) ...'."""
    op = g["open"]
    head = "%d critic finding%s open" % (len(op), "" if len(op) == 1 else "s")
    shown = ["%s (%s) %s" % (f["id"], f["severity"], short(f, 80)) for f in op[:3]]
    more = "; +%d more" % (len(op) - 3) if len(op) > 3 else ""
    return head + ": " + "; ".join(shown) + more


def gate_error(job: Path, g: Dict[str, Any]) -> Tuple[str, str]:
    """(message, hint) for the refusal at `job note --stage deliver`."""
    op = g["open"]
    lines = ["the job cannot be marked delivered: %d critic finding%s %s neither fixed nor waived" % (
        len(op), "" if len(op) == 1 else "s", "is" if len(op) == 1 else "are")]
    for f in op[:12]:
        lines.append("    %-9s %-10s round %d: %s" % (f["id"], f["severity"], f["round"], short(f)))
    if len(op) > 12:
        lines.append("    ... and %d more (showtime review-respond %s lists them all)" % (len(op) - 12, job.name))
    return "\n".join(lines), how_to(job.name, [f["id"] for f in op])


# ------------------------------------------------------------------ a critic's answer as text (review-findings)
# A critic sub-agent the host denies Write returns its answer in its reply; `showtime review-findings` saves
# that text as the round's FINDINGS.md once its shape is right, so the director never retypes it.

_START = re.compile(r"^\W*(SELF-REVIEW|VERDICT|PREFERENCE)\b", re.I)
_FENCE = re.compile(r"^\s*(```|~~~)")
_T = re.compile(r"\bt\s*=\s*\d+(?:\.\d+)?\s*s\b", re.I)


def _filled(lines: Sequence[str]) -> int:
    return sum(1 for x in lines if x.strip())


def extract(text: str) -> Tuple[str, int]:
    """(the answer, non-blank lines left out): the fenced block that holds the answer when the reply wraps it in one,
    else everything from its first SELF-REVIEW / VERDICT / PREFERENCE line (a sentence of chat before it is
    not part of FINDINGS.md)."""
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i, n = 0, len(lines)
    while i < n:
        if _FENCE.match(lines[i]):
            j = i + 1
            while j < n and not _FENCE.match(lines[j]):
                j += 1
            block = lines[i + 1:j]
            if any(_START.match(x.strip().strip("`*")) for x in block):
                return "\n".join(block).strip("\n") + "\n", _filled(lines) - _filled(block)
            i = j + 1
            continue
        i += 1
    for k, ln in enumerate(lines):
        if _START.match(ln.strip().strip("`*")):
            body = "\n".join(lines[k:]).rstrip()
            return body + "\n", _filled(lines[:k])
    return "\n".join(lines).strip("\n") + "\n", 0


def _headings(text: str) -> List[str]:
    """The section words of an answer, upper case, in order (BLOCKERS, SHOULD-FIX, POLISH, VERDICT ...)."""
    out = []
    for raw in text.splitlines():
        line = raw.strip().strip("`").strip()
        if _BULLET.match(line):
            continue
        h = _HEAD.match(line)
        if h:
            w = h.group(1).upper()
            out.append("BLOCKERS" if w.startswith("BLOCKER") else "SHOULD-FIX" if w.startswith("SHOULD") else
                       "WOULD I POST" if w.startswith("WOULD") else w)
    return out


def shape(text: str, round_no: int = 1, order: Optional[int] = None) -> Tuple[List[str], List[str]]:
    """(problems, warnings) of a critic's answer against CRITIC.md's format. A problem means the answer
    cannot count (no verdict, no WOULD I POST line, a missing Blockers / Should-fix / Polish section);
    a warning is saved anyway (a finding without a timestamp, a pairwise finding that names no video)."""
    from . import review_state            # review_state imports this module
    problems: List[str] = []
    warnings: List[str] = []
    heads = set(_headings(text))
    posts = review_state.parse_would_post(text)
    if order is None:
        if review_state.parse_verdict(text) is None:
            problems.append("no readable VERDICT line (ship | ship after fixes | not ready -- one reason)")
        if "" not in posts:
            problems.append("no answered WOULD I POST THIS line (yes | no -- one reason)")
    else:
        # the parser review-verdict uses, so the two never disagree ("neither" is a tie, "X over Y" is X)
        from ..qa.pairwise import parse_findings
        if parse_findings(text)["preference"] is None:
            problems.append("no readable PREFERENCE line (X, Y or tie -- one reason)")
        for lab in ("X", "Y"):
            if lab not in posts:
                problems.append("no answered WOULD I POST %s line (yes | no -- one reason)" % lab)
    missing = [h for h in ("BLOCKERS", "SHOULD-FIX", "POLISH") if h not in heads]
    if missing:
        problems.append("no %s section (write it with `- none` when it is empty)" % ", ".join(missing))
    prefix = "r%d" % round_no if order is None else "r%do%d" % (round_no, order)
    for f in parse(text, prefix):
        if not _T.search(f["text"]):
            warnings.append("%s cites no timestamp (t=..s): %s" % (f["id"], short(f, 70)))
        if order is not None and f["video"] is None:
            warnings.append("%s names neither video ([X] or [Y]), so it counts for neither: %s" % (f["id"], short(f, 70)))
    if order is None and round_no > 1 and "PREVIOUS" not in heads:
        warnings.append("no PREVIOUS section: round %d answers each earlier blocker and should-fix by its id" % round_no)
    return problems, warnings

"""Where a job's critic review stands, and whether its review mode still asks for one.

Quality mode (the default) asks for a critic round on every finished video before delivery: `showtime qa`
on the job's final, `showtime deliver exports` and `showtime job note --stage deliver` say "review pending"
(a WARN line, never a change to the video's own qa verdict) until a round with a verdict exists. Lean
mode asks for none. Read-only: this module only reads <job>/review/ and job.json.

A round has a verdict when
  * a single round's FINDINGS.md carries a VERDICT line (ship / ship after fixes / not ready), or
  * a pairwise round (review-pack --against) was decided with `showtime review-verdict` (verdict.json).
It is still pending when no round was answered yet, a built pack waits for its critic, a pairwise round
waits for its second critic or for review-verdict, or the last answered round said "not ready" and fewer
than three rounds were used (fix, re-render, then a pairwise round against the best version).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import review_mode

MAX_ROUNDS = 3             # the critic protocol's cap (st.qa.review.MAX_ROUNDS)
KEYS = ".pairwise-keys"    # st.qa.pairwise.KEYS
_VERDICT = re.compile(r"^\W*VERDICT\W*:?\s*(.*)$", re.I)


def _read(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def parse_verdict(text: str) -> Optional[str]:
    """'ship', 'ship after fixes' or 'not ready' from a single round's FINDINGS.md (None when unreadable,
    e.g. the template's 'ship | ship after fixes | not ready' left as is)."""
    for raw in text.splitlines():
        m = _VERDICT.match(raw.strip().strip("`*"))
        if not m:
            continue
        v = re.split(r"\s--\s|\s-\s|\s—\s", m.group(1), maxsplit=1)[0].strip().strip("*").lower()
        if "|" in v:
            return None
        if "not ready" in v:
            return "not ready"
        if "after fix" in v:
            return "ship after fixes"
        if v.startswith("ship"):
            return "ship"
        return None
    return None


def _answered(f: Path) -> bool:
    return f.is_file() and f.stat().st_size > 0


def rounds(job: Path) -> List[Dict[str, Any]]:
    """Every review round of the job, oldest first: {round, kind, answered, verdict, video, self_review}."""
    root = job / "review"
    out: List[Dict[str, Any]] = []
    if not root.is_dir():
        return out
    for d in root.glob("round-*"):
        m = re.fullmatch(r"round-(\d+)", d.name)
        if not (m and d.is_dir()):
            continue
        n = int(m.group(1))
        key = _read(root / KEYS / ("round-%d.json" % n))
        row: Dict[str, Any] = {"round": n, "dir": str(d), "incomplete": (d / "INCOMPLETE").is_file()}
        if isinstance(key, dict):
            row["kind"] = "pairwise"
            orders = [_answered(d / ("order-%d" % k) / "FINDINGS.md") for k in (1, 2)]
            row["orders_answered"] = sum(orders)
            row["answered"] = any(orders)
            v = _read(d / "verdict.json")
            row["decided"] = isinstance(v, dict)
            row["verdict"] = ("new version wins" if v.get("improved") else "no improvement") if isinstance(v, dict) else None
            row["video"] = str((key.get("new") or {}).get("video") or "")
            row["against"] = str((key.get("old") or {}).get("video") or "")
            row["best"] = str(v.get("best") or "") if isinstance(v, dict) else ""
        else:
            row["kind"] = "single"
            f = d / "FINDINGS.md"
            row["answered"] = _answered(f)
            text = ""
            if row["answered"]:
                try:
                    text = f.read_text(encoding="utf-8", errors="replace")[:40000]
                except OSError:
                    text = ""
            row["verdict"] = parse_verdict(text) if text else None
            row["decided"] = row["verdict"] is not None
            row["self_review"] = text.lstrip().upper().startswith("SELF-REVIEW")
            man = _read(d / "manifest.json")
            row["video"] = str(man.get("video") or "") if isinstance(man, dict) else ""
        out.append(row)
    return sorted(out, key=lambda r: r["round"])


def _same_render(a: str, b: Path) -> bool:
    """a and b are the same render (a baked poster copy counts as its source)."""
    if not a:
        return False
    try:
        pa, pb = Path(a).resolve(), b.resolve()
    except OSError:
        return False
    if pa == pb:
        return True
    strip = lambda s: re.sub(r"\.poster$", "", s)  # noqa: E731
    return pa.parent == pb.parent and strip(pa.stem) == strip(pb.stem)


def previous_final(job: Path, data: Dict[str, Any], current: Path) -> Optional[Path]:
    """The newest earlier full final of the job (for a pairwise first round), None when there is none."""
    seen = set()
    for o in reversed(data.get("output_log") or []):
        if not isinstance(o, dict) or o.get("kind") != "final" or not o.get("path"):
            continue
        p = Path(str(o["path"]))
        if not p.is_absolute():
            p = job / p
        if str(p) in seen or not p.is_file() or _same_render(str(p), current):
            continue
        seen.add(str(p))
        if "discarded" in p.parts:
            continue
        return p
    return None


def state(job: Path, data: Optional[Dict[str, Any]] = None, video: Optional[Path] = None) -> Dict[str, Any]:
    """The job's review state: {mode, mode_source, required, status, pending, message, next, rounds}.

    status: 'lean' (not required), 'no final' (nothing finished yet), 'pending', 'waiting' (a pack waits for
    its critic or for review-verdict), 'not ready' (the last round said so; fix and pair again), 'done',
    'cap' (three rounds used)."""
    from . import ledger
    if data is None:
        data = ledger.load(job)
    mode, source = review_mode.job_mode(data, ledger.project_of(job, data))
    jn = job.name
    res: Dict[str, Any] = {"mode": mode, "mode_source": source, "required": mode == "quality", "pending": False,
                           "status": "", "message": "", "next": None, "rounds": []}
    rs = rounds(job)
    res["rounds"] = [{k: r.get(k) for k in ("round", "kind", "answered", "verdict", "self_review", "decided")
                      if r.get(k) is not None} for r in rs]
    answered = [r for r in rs if r["answered"]]
    res["rounds_answered"] = len(answered)
    if video is None:
        video, kind = ledger.latest_video(job, data)
        if kind != "final":
            video = None
    if mode == "lean":
        res["status"] = "lean"
        res["message"] = "lean mode: no critic round required (review-pack + critic when publish-bound or asked)"
        return res
    if video is None:
        res["status"] = "no final"
        res["message"] = "quality mode: a critic round follows the final render"
        return res
    last = rs[-1] if rs else None
    if last is not None and not last["answered"]:
        res.update(status="waiting", pending=True)
        res["message"] = ("review pending: round-%d is built but no critic has answered (FINDINGS.md missing)"
                          % last["round"])
        crit = Path(last["dir"]) / ("order-1/CRITIC.md" if last["kind"] == "pairwise" else "CRITIC.md")
        res["next"] = ("give a fresh critic sub-agent only %s%s and ask for FINDINGS.md next to it (no sub-agent tool: "
                       "answer it yourself as a SELF-REVIEW); a newer render: showtime review-pack %s rebuilds it"
                       % (crit, " (and a second one order-2/CRITIC.md)" if last["kind"] == "pairwise" else "", jn))
        return res
    if last is not None and last["kind"] == "pairwise" and not last["decided"]:
        res.update(status="waiting", pending=True)
        if last.get("orders_answered", 0) < 2:
            res["message"] = "review pending: pairwise round-%d has one critic's answer; it needs both orders" % last["round"]
            res["next"] = "give a second fresh critic only %s" % (Path(last["dir"]) / "order-2" / "CRITIC.md")
        else:
            res["message"] = "review pending: pairwise round-%d is answered but not decided" % last["round"]
            res["next"] = "showtime review-verdict %s" % jn
        return res
    if not answered:
        prev = previous_final(job, data, video)
        res.update(status="pending", pending=True)
        res["message"] = "review pending (quality mode): %s has had no critic round yet" % video.name
        res["next"] = ("showtime review-pack %s%s, then give a fresh critic sub-agent only the CRITIC.md path "
                       "(references/review.md)" % (jn, (" --against %s" % prev) if prev else ""))
        if prev:
            res["against"] = str(prev)
        return res
    if len(answered) >= MAX_ROUNDS:
        res["status"] = "cap"
        res["message"] = ("review done: %d critic rounds used (the cap); ship the best version with its open findings "
                          "listed" % len(answered))
        return res
    lr = answered[-1]
    if lr["kind"] == "single" and not lr.get("verdict"):
        res.update(status="waiting", pending=True)
        res["message"] = "review pending: round-%d's FINDINGS.md has no readable VERDICT line" % lr["round"]
        res["next"] = ("have the critic finish %s with one line: VERDICT: ship | ship after fixes | not ready -- why"
                       % (Path(lr["dir"]) / "FINDINGS.md"))
        return res
    if lr["kind"] == "single" and lr.get("verdict") == "not ready":
        res.update(status="not ready", pending=True)
        newer = not _same_render(lr.get("video", ""), video)
        res["message"] = "review pending: round-%d said not ready%s" % (
            lr["round"], "; %s has not been reviewed" % video.name if newer else "; fix its blockers")
        res["next"] = ("showtime review-pack %s --against best   (pairs %s with the reviewed version)" % (jn, video.name)
                       if newer else "fix the blockers in %s, re-render, then showtime review-pack %s --against best"
                       % (Path(lr["dir"]) / "FINDINGS.md", jn))
        return res
    res["status"] = "done"
    v = lr.get("verdict") or "answered"
    res["message"] = "review done: round-%d %s%s" % (lr["round"], v, " (a self-review)" if lr.get("self_review") else "")
    if lr["kind"] == "single" and v == "ship after fixes" and not _same_render(lr.get("video", ""), video):
        res["next"] = ("prove each fix: showtime snap %s --at <t> --compare %s" % (video, lr.get("video"))
                       if lr.get("video") else None)
    return res


def pending_line(st: Dict[str, Any]) -> Optional[str]:
    """The one WARN line for qa / deliver / job note, or None when nothing is pending."""
    if not st.get("pending"):
        return None
    return "WARN  %s -> %s" % (st["message"], st["next"]) if st.get("next") else "WARN  %s" % st["message"]

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

The quality floor (quality mode; lean only warns):
  * the absolute verdict. Every FINDINGS.md carries `WOULD I POST THIS: yes | no -- one reason` (pairwise:
    one per video, `WOULD I POST X: ...`), judged on the video alone, never against another version. A
    "no" (for a pairwise round: either critic's "no" for the winning version) holds delivery like "not
    ready", even when the pairwise preferred the new version; a missing line keeps the round pending.
  * caption should-fixes cannot ship silently. A SHOULD-FIX (or BLOCKER) line that names captions or
    subtitles stays open until a later text says what happened to it: a line that also names captions
    and says `fixed` or `won't fix: <reason>`, in a later round's FINDINGS.md or in the maker's
    review/round-N/RESPONSE.md (N = the round that raised it, or any later one). Plain word matching,
    nothing smarter: name the captions in the answer.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import review_mode

MAX_ROUNDS = 3             # the critic protocol's cap (st.qa.review.MAX_ROUNDS)
KEYS = ".pairwise-keys"    # st.qa.pairwise.KEYS
_VERDICT = re.compile(r"^\W*VERDICT\W*:?\s*(.*)$", re.I)
# the absolute verdict: "WOULD I POST THIS: no -- the captions look cheap" (pairwise: "WOULD I POST X: yes -- ...")
_POST = re.compile(r"^\W*WOULD\s+I\s+POST(?:\s+THIS)?\s*(?:\[?\s*([XY])\s*\]?)?\s*[:=]?\s*(.*)$", re.I)
_CAPTION = re.compile(r"\b(captions?|subtitles?|subs)\b", re.I)
_FIXED = re.compile(r"(?<!not )(?<!n't )\bfixed\b|\bwon'?t\s+fix\s*:\s*\S|\bwill\s+not\s+fix\s*:\s*\S", re.I)
_SECTION = re.compile(r"^\W*(BLOCKERS?|SHOULD[- ]FIX|POLISH|WHAT WORKS|DECLINED TO JUDGE|BEST POSTER FRAME|VERDICT|"
                      r"PREFERENCE|WOULD I POST|PREVIOUS)\b", re.I)


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


def parse_would_post(text: str) -> Dict[str, Tuple[str, str]]:
    """The absolute verdict lines: {"": ("yes"|"no", reason)} for a single round, {"X": ..., "Y": ...} for a
    pairwise order. A template line left as is ("yes | no") is not an answer."""
    out: Dict[str, Tuple[str, str]] = {}
    for raw in text.splitlines():
        m = _POST.match(raw.strip().strip("`*"))
        if not m:
            continue
        rest = m.group(2).strip().strip("*").strip()
        head = re.split(r"\s--\s|\s-\s|\s—\s", rest, maxsplit=1)
        v = head[0].strip().lower()
        if "|" in v or not re.match(r"(yes|no)\b", v):
            continue
        answer = "yes" if v.startswith("yes") else "no"
        reason = head[1].strip() if len(head) > 1 else re.sub(r"^(yes|no)\W*", "", head[0].strip(), flags=re.I)
        out[(m.group(1) or "").upper()] = (answer, reason)
    return out


def caption_should_fixes(text: str) -> List[str]:
    """SHOULD-FIX and BLOCKER bullets of one FINDINGS.md that name captions or subtitles."""
    out: List[str] = []
    sev = ""
    for raw in text.splitlines():
        line = raw.strip().strip("`")
        h = _SECTION.match(line)
        if h:
            sev = h.group(1).upper()
            continue
        b = re.match(r"(?:[-*]|\d+[.)])\s*(.*)", line)
        if b and sev.startswith(("SHOULD", "BLOCKER")) and _CAPTION.search(b.group(1)):
            body = b.group(1).strip()
            if body.strip(".() ").lower() not in ("none", "n/a", "..."):
                out.append(body)
    return out


def resolves_captions(text: str) -> bool:
    """A line that names captions/subtitles and says `fixed` or `won't fix: <reason>`."""
    return any(_CAPTION.search(ln) and _FIXED.search(ln) for ln in text.splitlines())


def _read_text(f: Path) -> str:
    try:
        return f.read_text(encoding="utf-8", errors="replace")[:40000] if f.is_file() else ""
    except OSError:
        return ""


def _findings_texts(d: Path) -> List[str]:
    return [t for t in (_read_text(d / "FINDINGS.md"), _read_text(d / "order-1" / "FINDINGS.md"),
                        _read_text(d / "order-2" / "FINDINGS.md")) if t]


def open_caption_fixes(job: Path, rs: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Caption should-fixes that no later text resolved: [{round, text}] (see the module docstring)."""
    rs = rounds(job) if rs is None else rs
    out: List[Dict[str, Any]] = []
    for i, r in enumerate(rs):
        d = Path(r["dir"])
        raised = [c for t in _findings_texts(d) for c in caption_should_fixes(t)]
        if not raised:
            continue
        later = [_read_text(d / "RESPONSE.md")]
        for r2 in rs[i + 1:]:
            later += _findings_texts(Path(r2["dir"])) + [_read_text(Path(r2["dir"]) / "RESPONSE.md")]
        if not any(resolves_captions(t) for t in later if t):
            out += [{"round": r["round"], "text": c} for c in raised]
    return out


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
            wp = v.get("would_post") if isinstance(v, dict) else None
            row["would_post"] = wp.get("answer") if isinstance(wp, dict) else None
            row["would_post_reason"] = wp.get("reason") if isinstance(wp, dict) else None
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
            wp = parse_would_post(text).get("") if text else None
            row["would_post"] = wp[0] if wp else None
            row["would_post_reason"] = wp[1] if wp else None
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
    res["rounds"] = [{k: r.get(k) for k in ("round", "kind", "answered", "verdict", "self_review", "decided", "would_post")
                      if r.get(k) is not None} for r in rs]
    answered = [r for r in rs if r["answered"]]
    res["rounds_answered"] = len(answered)
    if video is None:
        video, kind = ledger.latest_video(job, data)
        if kind != "final":
            video = None
    caps = open_caption_fixes(job, rs)
    if caps:
        res["caption_fixes_open"] = caps
    if mode == "lean":
        res["status"] = "lean"
        res["message"] = "lean mode: no critic round required (review-pack + critic when publish-bound or asked)"
        if caps:
            res["warn"] = _caption_message(caps)
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
    lr = answered[-1]
    cap = len(answered) >= MAX_ROUNDS
    if cap:
        res["status"] = "cap"
        res["message"] = ("review done: %d critic rounds used (the cap); ship the best version with its open findings "
                          "listed" % len(answered))
        if lr.get("would_post") == "no":
            res["message"] += "; the last critic would not post it (%s): tell the user" % (
                lr.get("would_post_reason") or "no reason given")
    if not cap and lr["kind"] == "single" and not lr.get("verdict"):
        res.update(status="waiting", pending=True)
        res["message"] = "review pending: round-%d's FINDINGS.md has no readable VERDICT line" % lr["round"]
        res["next"] = ("have the critic finish %s with one line: VERDICT: ship | ship after fixes | not ready -- why"
                       % (Path(lr["dir"]) / "FINDINGS.md"))
        return res
    if not cap and lr["kind"] == "single" and lr.get("verdict") == "not ready":
        res.update(status="not ready", pending=True)
        newer = not _same_render(lr.get("video", ""), video)
        res["message"] = "review pending: round-%d said not ready%s" % (
            lr["round"], "; %s has not been reviewed" % video.name if newer else "; fix its blockers")
        res["next"] = ("showtime review-pack %s --against best   (pairs %s with the reviewed version)" % (jn, video.name)
                       if newer else "fix the blockers in %s, re-render, then showtime review-pack %s --against best"
                       % (Path(lr["dir"]) / "FINDINGS.md", jn))
        return res
    if not cap and lr.get("would_post") is None:
        res.update(status="waiting", pending=True)
        pair = lr["kind"] == "pairwise"
        res["message"] = ("review pending: round-%d has no absolute verdict (WOULD I POST THIS: yes | no), which "
                          "quality mode requires" % lr["round"])
        res["next"] = ("have %s add one line: %s -- one reason, judged on the video alone%s"
                       % ("each critic (order-1/ and order-2/FINDINGS.md)" if pair else "the critic of %s" % (
                           Path(lr["dir"]) / "FINDINGS.md"),
                          "WOULD I POST X: yes | no, and WOULD I POST Y: yes | no" if pair else "WOULD I POST THIS: yes | no",
                          "; then showtime review-verdict %s" % jn if pair else ""))
        return res
    if not cap and lr.get("would_post") == "no":
        res.update(status="would not post", pending=True)
        seen = lr.get("video", "") if lr["kind"] == "single" else lr.get("best", "")
        newer = not _same_render(seen, video)
        res["message"] = ("review pending: round-%d's critic would not post %s under their own name (%s), whatever a "
                          "comparison said" % (lr["round"], "the reviewed version" if newer else video.name,
                                               lr.get("would_post_reason") or "no reason given"))
        res["next"] = ("showtime review-pack %s --against best   (%s has not been reviewed)" % (jn, video.name) if newer
                       else "fix what the critic named in %s, re-render, then showtime review-pack %s --against best"
                       % (lr["dir"], jn))
        return res
    if caps:
        res.update(status="caption fix open", pending=True)
        res["message"] = "review pending: " + _caption_message(caps)
        res["next"] = ("fix it, re-render and pair again (the critic answers `fixed: <the caption finding>`), or write "
                       "`won't fix: <reason>` about the captions in %s"
                       % (job / "review" / ("round-%d" % caps[-1]["round"]) / "RESPONSE.md"))
        return res
    if cap:
        return res
    res["status"] = "done"
    v = lr.get("verdict") or "answered"
    res["message"] = "review done: round-%d %s%s" % (lr["round"], v, " (a self-review)" if lr.get("self_review") else "")
    if lr["kind"] == "single" and v == "ship after fixes" and not _same_render(lr.get("video", ""), video):
        res["next"] = ("prove each fix: showtime snap %s --at <t> --compare %s" % (video, lr.get("video"))
                       if lr.get("video") else None)
    return res


def _caption_message(caps: List[Dict[str, Any]]) -> str:
    c = caps[0]
    return ("a caption should-fix from round-%d is unresolved%s: %s (no later `fixed` or `won't fix: <reason>` naming "
            "the captions)" % (c["round"], " (+%d more)" % (len(caps) - 1) if len(caps) > 1 else "", c["text"][:140]))


def pending_line(st: Dict[str, Any]) -> Optional[str]:
    """The one WARN line for qa / deliver / job note, or None when nothing is pending (lean mode: a caption
    should-fix left open still warns)."""
    if not st.get("pending"):
        return ("WARN  %s" % st["warn"]) if st.get("warn") else None
    return "WARN  %s -> %s" % (st["message"], st["next"]) if st.get("next") else "WARN  %s" % st["message"]

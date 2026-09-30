"""The job receipt: what a video took, stated plainly.

Every job ends with `<job>/receipt.md` (for people), `<job>/receipt.json` (the stable format, schema 1,
for the gallery and the site) and one line in `<job>/share.txt`. Both are built from what showtime
recorded: job.json (request, assumptions, renders, qa), the review rounds and image folders on disk,
and, when the agent's own session log is named, the token counts in it. See references/receipt.md.

Rules: never estimate silently (an unknown says "not reported by this agent"), never copy anything from
a session log except numbers, and never write a path from the user's machine.

Stdlib only, Python 3.8+.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import __version__
from ..common import ShowtimeError, fmt_duration, read_json, write_json
from . import ledger, usage

SCHEMA = 1
NOT_REPORTED = usage.NOT_REPORTED
BLOCK_START = "--- Receipt (optional, delete if you like) ---"
BLOCK_END = "--- end receipt ---"
SOURCE_FILE = "work/logs/receipt-source.json"    # which session log this job's usage was read from (a path, kept locally)
TAIL_SECONDS = 30 * 60                            # session time after the job's last ledger update that still counts
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
IMAGE_KINDS = (
    ("review", "Review packs (contact sheets, scene and cut strips, key frames)"),
    ("qa", "qa contact sheets and frames"),
    ("snap", "Stills and contact sheets from snap"),
    ("check", "Project check sheets"),
    ("views", "Footage edit views"),
    ("looks", "Look and composite images"),
)


# ------------------------------------------------------------------ privacy

def mask(text: str) -> str:
    """Home paths, keys, tokens and e-mail addresses masked (a receipt is meant to be shared)."""
    from . import report
    s = str(text)
    for h in report._home_variants():
        s = s.replace(h, "~")
    for name, rx in report._SECRET_PATTERNS:
        if name == "bearer":
            s = rx.sub(lambda m: m.group(1) + m.group(2) + "<REDACTED>", s)
        elif name == "kv-secret":
            s = rx.sub(lambda m: m.group(1) + m.group(2) + m.group(3) + "<REDACTED>", s)
        elif name == "url-cred":
            s = rx.sub(lambda m: m.group(1) + "<REDACTED>@", s)
        elif name == "url-query-secret":
            s = rx.sub(lambda m: m.group(1) + "<REDACTED>", s)
        else:
            s = rx.sub("<REDACTED>", s)
    return report._EMAIL.sub("<email>", s)


# ------------------------------------------------------------------ what is on disk

def _epoch(iso: Optional[str]) -> Optional[float]:
    return ledger._parse_iso(iso)


def _images(job: Path) -> Dict[str, int]:
    """Image files showtime made for looking at, by kind (folders it writes; never the render's frame dumps)."""
    counts = {k: 0 for k, _ in IMAGE_KINDS}
    skip = {"node_modules", "exports", "frames", ".git", "discarded"}
    root = str(job)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirnames[:] = [d for d in dirnames if d not in skip and depth < 8 and not d.startswith("st-")]
        parts = [p.lower() for p in Path(rel).parts] if rel != "." else []
        imgs = sum(1 for f in filenames if f.lower().endswith(IMAGE_EXTS))
        if not imgs or not parts:
            continue
        kind = None
        if parts[0] == "review":
            kind = "review"
        elif "views" in parts:
            kind = "views"
        elif any(p.startswith(("looks", "composite")) for p in parts):
            kind = "looks"
        elif "work" in parts:
            after = parts[parts.index("work") + 1:]
            if after and after[0] == "qa":
                kind = "qa"
            elif after and after[0].startswith("snap"):
                kind = "snap"
            elif after and after[0].startswith("check"):
                kind = "check"
        if kind:
            counts[kind] += imgs
    return counts


def _review(job: Path) -> Dict[str, Any]:
    rounds = sorted((d for d in (job / "review").glob("round-*") if d.is_dir()),
                    key=lambda d: int(re.sub(r"\D", "", d.name) or 0)) if (job / "review").is_dir() else []
    info: List[Dict[str, Any]] = []
    for d in rounds:
        f = d / "FINDINGS.md"
        row = {"round": int(re.sub(r"\D", "", d.name) or 0), "findings": f.is_file(), "self_review": False}
        if f.is_file():
            try:
                row["self_review"] = "self-review" in f.read_text(encoding="utf-8", errors="replace")[:20000].lower()
            except OSError:
                pass
        info.append(row)
    return {"packed": len(info), "with_findings": sum(1 for r in info if r["findings"]),
            "self_reviewed": sum(1 for r in info if r["self_review"]), "rounds": info}


def _review_state(job: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """The review mode and critic-round state (st.job.review_state); {} when unreadable."""
    try:
        from . import review_state
        return review_state.state(job, data)
    except Exception:  # noqa: BLE001 - the receipt never fails over it
        return {}


def _renders(data: Dict[str, Any]) -> Dict[str, Any]:
    rl = [r for r in (data.get("renders") or []) if isinstance(r, dict)]
    src = "recorded by render"
    if not rl:
        # a job from before renders were recorded: the stage log (no partial renders there)
        for s in data.get("stages") or []:
            if s.get("name") in ("render", "preview") and s.get("status") == "done":
                rl.append({"kind": "full" if s["name"] == "render" else "preview", "file": "", "seconds": s.get("seconds")})
        src = "counted from the stage log" if rl else "none recorded"
    def n(k: str) -> int:
        return sum(1 for r in rl if r.get("kind") == k)
    secs = sum(float(r.get("seconds") or 0) for r in rl)
    return {"full": n("full"), "preview": n("preview"), "partial": n("partial"), "seconds": round(secs, 1),
            "spliced": sum(1 for r in rl if r.get("kind") == "partial" and r.get("spliced_from")),
            "source": src, "list": [{k: r[k] for k in ("kind", "file", "seconds", "span", "spliced_from") if r.get(k) not in (None, "")}
                                    for r in rl][-40:]}


def _end_of_job(job: Path, data: Dict[str, Any]) -> Tuple[Optional[float], str]:
    """(epoch, label) of the moment the video was done: the newest final (else preview) file, else the last update."""
    lo = ledger.last_output(job, data)
    if lo:
        try:
            return Path(lo[0]).stat().st_mtime, "final" if "final" in Path(lo[0]).name.lower() else "latest render"
        except OSError:
            pass
    return _epoch(data.get("updated")), "last update (no render yet)"


def _agent(us: Dict[str, Any]) -> Optional[str]:
    if us.get("host") == "claude-code":
        return "Claude Code"
    if us.get("host") == "codex":
        return "Codex"
    name = re.sub(r"[^\w .+/-]", "", os.environ.get("SHOWTIME_AGENT", "")).strip()[:60]
    return ("%s (through MCP)" % name) if name else None


# ------------------------------------------------------------------ the source of the session log

def remember_source(job: Path, transcript: str, host: Optional[str] = None, session: Optional[str] = None) -> None:
    """Keep which session log to read next time (a local path in work/logs; never copied into the receipt)."""
    try:
        p = job / SOURCE_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        write_json(p, {"transcript": str(transcript), "host": host, "session": session})
    except OSError:
        pass


def _source(job: Path) -> Dict[str, Any]:
    d = read_json(job / SOURCE_FILE, {}) or {}
    return d if isinstance(d, dict) else {}


# ------------------------------------------------------------------ build

def build(job: Path, transcript: Optional[str] = None, host: Optional[str] = None,
          whole_session: bool = False) -> Dict[str, Any]:
    data = ledger.load(job)
    src = _source(job)
    tpath = transcript or os.environ.get("SHOWTIME_TRANSCRIPT") or src.get("transcript")
    thost = host or (src.get("host") if not transcript else None)
    start = _epoch(data.get("created"))
    end, end_label = _end_of_job(job, data)
    upd = _epoch(data.get("updated"))
    since = None if whole_session else start
    until = None if whole_session else ((max(x for x in (upd, end) if x is not None) + TAIL_SECONDS)
                                        if (upd or end) else None)
    if tpath:
        us = usage.read_usage(tpath, since, until, thost)
        if us.get("status") == "reported":
            us["window"] = "the whole session" if whole_session else "from the job's start to its last update (and 30 min after)"
            if us.get("cost_usd") is not None:
                us["cost_note"] += "; counted from the session log, so work the host keeps elsewhere is not included"
            if transcript:
                remember_source(job, transcript, us.get("host"))
    else:
        us = {"status": "not_reported", "host": None, "note": "no session log was given"}
    agent = _agent(us)

    request = str(data.get("request") or "").strip()
    goal = str(data.get("goal") or "").strip()
    if request:
        req = {"text": mask(request), "source": "as typed"}
    elif goal:
        req = {"text": mask(goal), "source": "the job goal (the agent's wording; the original request was not recorded)"}
    else:
        req = {"text": "", "source": "not recorded"}

    verified = [v["text"] for v in data.get("verified") or [] if not str(v.get("text", "")).startswith("qa ")]
    qa = data.get("qa") or {}
    prev = read_json(job / "receipt.json", {}) or {}
    img = _images(job)
    old_img = ((prev.get("images") or {}).get("by_kind") or {}) if isinstance(prev, dict) else {}
    for k in img:                      # a clean removes the images, not the fact that they were made
        img[k] = max(img[k], int(old_img.get(k) or 0))
    wall = (end - start) if (start is not None and end is not None and end >= start) else None

    rstate = _review_state(job, data)
    rec: Dict[str, Any] = {
        "schema": SCHEMA, "job": job.name, "showtime": __version__, "generated": ledger.now_iso(),
        "request": req, "mode": data.get("mode"), "platform": data.get("platform"), "agent": agent,
        "review_mode": {"mode": rstate.get("mode"), "source": rstate.get("mode_source"),
                        "critic_round": rstate.get("status")},
        "assumptions": {
            "not_checked": [mask(a["text"]) for a in data.get("assumed") or []],
            "checked": [mask(t) for t in verified][:12],
            "decisions": [{"question": mask(q["text"]), "answer": mask(q["answer"])}
                          for q in data.get("questions") or [] if q.get("answer")],
            "open_questions": [mask(q["text"]) for q in data.get("questions") or [] if not q.get("answer")],
        },
        "review": dict(_review(job), status=rstate.get("status"), note=rstate.get("message")),
        "qa": {"runs": sum(1 for s in data.get("stages") or [] if s.get("name") == "qa") or (1 if qa else 0),
               "verdict": qa.get("verdict"), "fail": qa.get("fail"), "warn": qa.get("warn"),
               "file": Path(str(qa["video"])).name if qa.get("video") else None},
        "renders": _renders(data),
        "images": {"total": sum(img.values()), "by_kind": img,
                   "note": "made by showtime for the agent to look at; whether each was opened is not known to showtime"},
        "time": {"start": data.get("created"), "end": ledger._mtime_iso(Path(ledger.last_output(job, data)[0]))
                 if ledger.last_output(job, data) else data.get("updated"), "ends_at": end_label,
                 "wall_seconds": round(wall, 1) if wall is not None else None,
                 "render_seconds": _renders(data)["seconds"],
                 "note": "includes any time spent waiting for the user"},
        "usage": us,
    }
    return rec


# ------------------------------------------------------------------ text

def _n(n: int, one: str, many: Optional[str] = None) -> str:
    return "%d %s" % (n, one if n == 1 else (many or one + "s"))


def _dur(sec: Optional[float]) -> str:
    if sec is None:
        return NOT_REPORTED
    s = int(round(sec))
    if s < 60:
        return "%d s" % s
    m, r = divmod(s, 60)
    if m < 60:
        return "%d min %02d s" % (m, r)
    h, m = divmod(m, 60)
    return "%d h %02d min" % (h, m)


def _tok(n: int) -> str:
    return "{:,}".format(int(n))


def usd_text(us: Dict[str, Any]) -> str:
    if us.get("status") != "reported":
        return NOT_REPORTED
    if us.get("cost_usd") is None:
        return NOT_REPORTED
    return "about $%.2f (API-equivalent)" % us["cost_usd"]


def line(rec: Dict[str, Any]) -> str:
    """The single line for share.txt."""
    r, rv = rec["renders"], rec["review"]
    bits = [_n(r["full"], "full render")]
    if r["partial"]:
        bits.append(_n(r["partial"], "partial render"))
    if r["preview"]:
        bits.append(_n(r["preview"], "preview"))
    bits.append(_n(rv["packed"], "review round"))
    bits.append(_dur(rec["time"]["wall_seconds"]) + " from start to final" if rec["time"]["wall_seconds"] is not None
                else "time " + NOT_REPORTED)
    us = rec["usage"]
    bits.append("cost " + usd_text(us) if us.get("status") == "reported" and us.get("cost_usd") is not None
                else "cost " + NOT_REPORTED)
    return "Made with showtime: " + ", ".join(bits) + ". Receipt: receipt.md"


def to_markdown(rec: Dict[str, Any]) -> str:
    L: List[str] = []
    a = L.append
    a("# Receipt: %s" % rec["job"])
    a("")
    a("What this video took, from what showtime recorded. Anything unknown says \"%s\"." % NOT_REPORTED)
    a("")
    a("## Request")
    a("")
    if rec["request"]["text"]:
        for ln in rec["request"]["text"].splitlines() or [""]:
            a("> " + ln if ln.strip() else ">")
        a("")
        a("(%s)" % rec["request"]["source"])
    else:
        a("Not recorded.")
    a("")
    a("## Setup")
    a("")
    a("- Agent: %s" % (rec["agent"] or NOT_REPORTED))
    models = list((rec["usage"].get("models") or {}).keys())
    a("- Models: %s" % (", ".join(models) if models else NOT_REPORTED))
    rmode = (rec.get("review_mode") or {}).get("mode")
    a("- Mode: %s%s%s" % (rec.get("mode") or "quick", ", %s review" % rmode if rmode else "",
                          ", for %s" % rec["platform"] if rec.get("platform") else ""))
    a("- showtime %s" % rec["showtime"])
    a("")
    a("## Assumptions")
    a("")
    asm = rec["assumptions"]
    if asm["not_checked"]:
        a("Assumed, not checked:")
        L.extend("- " + t for t in asm["not_checked"])
    else:
        a("Nothing was left assumed.")
    if asm["checked"]:
        a("")
        a("Checked:")
        L.extend("- " + t for t in asm["checked"])
    if asm["decisions"]:
        a("")
        a("Decided by the user:")
        L.extend("- %s: %s" % (d["question"], d["answer"]) for d in asm["decisions"])
    if asm["open_questions"]:
        a("")
        a("Still open:")
        L.extend("- " + t for t in asm["open_questions"])
    a("")
    a("## Rounds")
    a("")
    rv, qa = rec["review"], rec["qa"]
    if rv["packed"]:
        extra = []
        if rv["with_findings"] != rv["packed"]:
            extra.append("%d with findings saved" % rv["with_findings"])
        else:
            extra.append("all with findings saved")
        if rv["self_reviewed"]:
            extra.append("%d answered by the agent itself, not a separate critic" % rv["self_reviewed"])
        a("- Review rounds: %d (%s)" % (rv["packed"], "; ".join(extra)))
    else:
        a("- Review rounds: 0")
    if rv.get("note") and rv.get("status") not in ("no final",):
        a("- Critic round: %s" % rv["note"])
    if qa["runs"]:
        a("- qa runs: %d, latest %s%s" % (qa["runs"], qa["verdict"] or "?",
                                        " (%s fail, %s warn)" % (qa["fail"], qa["warn"]) if qa.get("fail") is not None else ""))
    else:
        a("- qa runs: 0")
    a("")
    a("## Renders")
    a("")
    r = rec["renders"]
    if r["source"] == "none recorded":
        a("- No render was recorded in this job.")
    else:
        a("- Full renders: %d" % r["full"])
        a("- Previews: %d" % r["preview"])
        a("- Partial renders (only a span re-rendered): %d%s" % (
            r["partial"], " (%d spliced into a copy of the full video, making a new final)" % r["spliced"] if r.get("spliced") else ""))
        a("- Render time in total: %s" % _dur(r["seconds"]))
        if r["source"] != "recorded by render":
            a("- (%s; partial renders are not in it)" % r["source"])
    a("")
    a("## Images made for looking")
    a("")
    im = rec["images"]
    if im["total"]:
        a("showtime made %d images for the agent to look at:" % im["total"])
        names = dict(IMAGE_KINDS)
        L.extend("- %s: %d" % (names[k], im["by_kind"][k]) for k, _ in IMAGE_KINDS if im["by_kind"].get(k))
    else:
        a("showtime made no review images in this job.")
    a("")
    a("Whether the agent opened each of them is not known to showtime.")
    a("")
    a("## Time")
    a("")
    t = rec["time"]
    a("- Wall time, job start to %s: %s" % (t["ends_at"], _dur(t["wall_seconds"])))
    a("- %s." % (t["note"][0].upper() + t["note"][1:]))
    a("")
    a("## Tokens and cost")
    a("")
    us = rec["usage"]
    if us.get("status") != "reported":
        a("- Tokens: %s" % NOT_REPORTED)
        a("- Cost: %s" % NOT_REPORTED)
        if us.get("note"):
            a("- (%s)" % us["note"])
    elif us.get("host") == "codex":
        tk = us["tokens"]
        a("- Tokens: %s in (%s cached), %s out (%s of them reasoning)" % (
            _tok(tk["input"]), _tok(tk["cached_input"]), _tok(tk["output"]), _tok(tk["reasoning"])))
        a("- Cost: %s" % NOT_REPORTED)
        a("- %s" % us["cost_note"])
    else:
        tk = us["tokens"]
        a("- Tokens: %s input, %s output, %s cache read, %s cache write" % (
            _tok(tk["input"]), _tok(tk["output"]), _tok(tk["cache_read"]), _tok(tk["write_5m"] + tk["write_1h"])))
        a("- Cost: %s" % usd_text(us))
        for m, row in us["models"].items():
            a("  - %s: %s output, %s" % (m, _tok(row["output"]),
                                         "$%.2f" % row["cost_usd"] if row.get("cost_usd") is not None else "cost " + NOT_REPORTED))
        a("- %s" % us["cost_note"])
        a("- Window: %s." % us["window"])
    a("")
    a("---")
    a("Generated by `showtime receipt` on %s. Format: references/receipt.md." % rec["generated"][:10])
    return "\n".join(L).rstrip() + "\n"


# ------------------------------------------------------------------ write

def _put(path: Path, text: str) -> None:
    with open(str(path), "w", encoding="utf-8", newline="\n") as f:       # Path.write_text(newline=) needs Python 3.10
        f.write(text)


def upsert_line(text: str, ln: str) -> str:
    """share.txt with the receipt block replaced (or appended); the rest of the text is untouched."""
    block = "%s\n%s\n%s" % (BLOCK_START, ln, BLOCK_END)
    pat = re.compile(re.escape(BLOCK_START) + r".*?" + re.escape(BLOCK_END), re.S)
    if pat.search(text):
        return pat.sub(lambda _m: block, text)
    base = text.rstrip()
    return (base + "\n\n" if base else "") + block + "\n"


def write(job: Path, transcript: Optional[str] = None, host: Optional[str] = None, whole_session: bool = False,
          share: bool = True) -> Dict[str, Any]:
    rec = build(job, transcript, host, whole_session)
    md = to_markdown(rec)
    _put(job / "receipt.md", md)
    write_json(job / "receipt.json", rec)
    files = {"receipt": str(job / "receipt.md"), "json": str(job / "receipt.json")}
    if share:
        sp = job / "share.txt"
        old = sp.read_text(encoding="utf-8", errors="replace") if sp.is_file() else ""
        new = upsert_line(old, line(rec))
        if new != old:
            _put(sp, new)
        files["share"] = str(sp)
    return {"receipt": rec, "files": files, "line": line(rec)}


def refresh(job: Path, share: bool = True) -> bool:
    """Best effort, quiet: called at the end of the normal flow (qa of the latest render: receipt.md and
    receipt.json; deliver: also the share.txt line). Only for a job that has a render, and never fails the
    command that called it."""
    try:
        if ledger.last_output(job, ledger.load(job)) is None:
            return False
        write(job, share=share)
        return True
    except Exception:  # noqa: BLE001 - a receipt is never worth failing a render, qa or export
        return False

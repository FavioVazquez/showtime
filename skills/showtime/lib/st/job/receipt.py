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
    """Review rounds and their FINDINGS files. A pairwise round (blind A/B, both orders) has one FINDINGS.md
    per order (order-1/, order-2/): it has its findings when both orders were answered."""
    try:
        from . import review_state
        rs = review_state.rounds(job)
    except Exception:  # noqa: BLE001 - the receipt never fails over it
        rs = []
    info: List[Dict[str, Any]] = []
    for r in rs:
        d = Path(r["dir"])
        pair = r.get("kind") == "pairwise"
        files = [d / ("order-%d" % k) / "FINDINGS.md" for k in (1, 2)] if pair else [d / "FINDINGS.md"]
        saved = [f for f in files if f.is_file()]
        selfr = False
        for f in saved:
            try:
                selfr = selfr or "self-review" in f.read_text(encoding="utf-8", errors="replace")[:20000].lower()
            except OSError:
                pass
        info.append({"round": r["round"], "kind": r.get("kind") or "single", "findings": len(saved) == len(files),
                     "findings_files": len(saved), "self_review": selfr})
    return {"packed": len(info), "with_findings": sum(1 for r in info if r["findings"]),
            "pairwise": sum(1 for r in info if r["kind"] == "pairwise"),
            "findings_files": sum(r["findings_files"] for r in info),
            "self_reviewed": sum(1 for r in info if r["self_review"]), "rounds": info}


def _lead_review(rv: Dict[str, Any], us: Dict[str, Any]) -> bool:
    """Findings saved, none marked as a self-review, yet no sub-agent ran in the session: the lead model
    (e.g. the lead of a Devin Fusion session, reviewing its sidekick's build) wrote them, not a critic."""
    return (us.get("status") == "reported" and us.get("subagents") == 0 and rv["findings_files"] > 0
            and rv["self_reviewed"] < sum(1 for r in rv["rounds"] if r["findings_files"]))


def _findings(job: Path) -> Optional[Dict[str, Any]]:
    """The critic's blockers and should-fixes and what became of each (st.job.findings); None when no critic
    answered. Texts and reasons are masked: a receipt is meant to be shared."""
    try:
        from . import findings
        g = findings.collect(job)
    except Exception:  # noqa: BLE001 - the receipt never fails over it
        return None
    if not g["applies"]:
        return None
    def row(f: Dict[str, Any]) -> Dict[str, Any]:
        out = {"id": f["id"], "severity": f["severity"], "text": mask(findings.short(f, 160))}
        if f["status"] != "open":
            out["by"] = f["by"]
            out["reason" if f["status"] == "waived" else "note"] = mask(f.get("note") or "")
        return out
    fs = g["findings"]
    return {"raised": len(fs), "blockers": sum(1 for f in fs if f["severity"] == "blocker"),
            "should_fix": sum(1 for f in fs if f["severity"] == "should-fix"),
            "fixed": [row(f) for f in g["fixed"]], "waived": [row(f) for f in g["waived"]],
            "open": [row(f) for f in g["open"]]}


def _qa_report(data: Dict[str, Any]) -> Dict[str, Any]:
    rp = (data.get("qa") or {}).get("report")
    rep = read_json(Path(str(rp)), {}) if rp and Path(str(rp)).is_file() else {}
    return rep if isinstance(rep, dict) else {}


def _delivery(job: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    """The facts of the delivery card (references/modes.md section 5) that showtime knows: the files, length,
    size, loudness and the qa verdict of the job's latest final. File names only, never a full path."""
    out: Dict[str, Any] = {}
    try:
        vid, kind = ledger.latest_video(job, data)
        view = ledger.outputs_view(job, data)
    except Exception:  # noqa: BLE001
        return out
    if vid is None:
        return out
    out["final"] = vid.name
    out["kind"] = kind
    for k in ("poster", "share", "credits", "captions"):
        if view.get(k):
            out[k] = Path(view[k]).name
    ex = job / "exports"
    out["exports"] = sorted(f.name for f in ex.iterdir() if f.is_file() and not f.name.startswith("."))[:20]         if ex.is_dir() else []
    qa = ledger.qa_of(data, vid)
    rep = _qa_report(data)
    if Path(str(rep.get("video") or "")).name != vid.name:
        rep = {}                       # the job's last qa report is about another file: no numbers from it
    pr, loud = rep.get("probe") or {}, rep.get("loudness") or {}
    out["duration"] = pr.get("duration")
    out["size"] = "%sx%s" % (pr["width"], pr["height"]) if pr.get("width") else None
    out["fps"] = pr.get("fps")
    out["lufs"] = loud.get("integrated_lufs")
    out["true_peak"] = loud.get("true_peak_dbtp")
    out["target_lufs"] = loud.get("target_lufs")
    out["qa"] = qa.get("verdict") if qa.get("video") and Path(str(qa["video"])).name == vid.name else None
    out["qa_fail"], out["qa_warn"] = (qa.get("fail"), qa.get("warn")) if out["qa"] else (None, None)
    rb = (rep.get("hearing") or {}).get("readback") if isinstance(rep.get("hearing"), dict) else None
    if isinstance(rb, dict) and rb.get("summary"):
        sus = [s for s in rb.get("suspects") or [] if isinstance(s, dict)]
        out["readback"] = {"summary": str(rb["summary"]), "words": [
            {"word": s.get("word"), "heard": s.get("heard"), "t": s.get("t"), "critical": bool(s.get("critical"))}
            for s in sus[:10]]}
    return out


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
    if us.get("host") == "devin":
        return "Devin"
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


def _devin_here() -> bool:
    """Running under Devin (its environment) with its session database on this machine."""
    try:
        from ..sandbox import detect_host
        return detect_host() == "devin" and usage.devin_db() is not None
    except Exception:  # noqa: BLE001
        return False


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
    if not tpath and _devin_here():
        tpath, thost = str(usage.devin_db()), "devin"         # Devin keeps its sessions in one database
    start = _epoch(data.get("created"))
    end, end_label = _end_of_job(job, data)
    upd = _epoch(data.get("updated"))
    since = None if whole_session else start
    until = None if whole_session else ((max(x for x in (upd, end) if x is not None) + TAIL_SECONDS)
                                        if (upd or end) else None)
    if tpath:
        us = usage.read_usage(tpath, since, until, thost, where=job)
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
    rv = dict(_review(job), status=rstate.get("status"), note=rstate.get("message"))
    rv["lead_review"] = _lead_review(rv, us)
    rv["findings"] = _findings(job)
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
        "review": rv,
        "qa": {"runs": sum(1 for s in data.get("stages") or [] if s.get("name") == "qa") or (1 if qa else 0),
               "verdict": qa.get("verdict"), "fail": qa.get("fail"), "warn": qa.get("warn"),
               "file": Path(str(qa["video"])).name if qa.get("video") else None},
        "renders": _renders(data),
        "delivery": _delivery(job, data),
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
    if us.get("host") == "devin":
        return "about $%.2f (est., at listed prices)" % us["cost_usd"]
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
        if rv.get("pairwise"):
            extra.append("%d pairwise (blind A/B, both orders)" % rv["pairwise"])
        if rv["with_findings"] != rv["packed"]:
            extra.append("%d with findings saved" % rv["with_findings"])
        else:
            extra.append("all with findings saved")
        if rv.get("findings_files", 0) != rv["with_findings"]:
            extra.append(_n(rv["findings_files"], "FINDINGS file"))
        if rv["self_reviewed"]:
            extra.append("%d answered by the agent itself, not a separate critic" % rv["self_reviewed"])
        a("- Review rounds: %d (%s)" % (rv["packed"], "; ".join(extra)))
        if rv.get("lead_review"):
            a("- Critic: not an independent critic (no sub-agent ran; the session's lead model wrote the findings)")
    else:
        a("- Review rounds: 0")
    if rv.get("note") and rv.get("status") not in ("no final",):
        a("- Critic round: %s" % rv["note"])
    fd = rv.get("findings")
    if fd:
        a("- Critic findings: %s and %s raised; %d fixed, %d waived, %d open" % (
            _n(fd["blockers"], "blocker"), _n(fd["should_fix"], "should-fix", "should-fix"), len(fd["fixed"]),
            len(fd["waived"]), len(fd["open"])))
        L.extend("  - waived %s (%s): %s. Finding: %s" % (f["id"], f["severity"], f["reason"].rstrip("."), f["text"])
                 for f in fd["waived"])
        L.extend("  - open %s (%s): %s" % (f["id"], f["severity"], f["text"]) for f in fd["open"])
    if qa["runs"]:
        a("- qa runs: %d, latest %s%s" % (qa["runs"], qa["verdict"] or "?",
                                        " (%s fail, %s warn)" % (qa["fail"], qa["warn"]) if qa.get("fail") is not None else ""))
    else:
        a("- qa runs: 0")
    a("")
    a("## Delivery")
    a("")
    dv = rec.get("delivery") or {}
    if dv.get("final"):
        for ln in card_facts(rec):
            a("- " + ln)
    else:
        a("- No final yet.")
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
            share = ", %d%% of the tokens" % round(100 * row["token_share"]) if row.get("token_share") is not None else ""
            reqs = "%s, " % _n(row.get("messages", 0), "request") if us.get("host") == "devin" else ""
            a("  - %s: %s%s output%s, %s" % (m, reqs, _tok(row["output"]), share,
                                             "$%.2f" % row["cost_usd"] if row.get("cost_usd") is not None else "cost " + NOT_REPORTED))
        a("- %s" % us["cost_note"])
        a("- Window: %s." % us["window"])
    a("")
    a("---")
    a("Generated by `showtime receipt` on %s. Format: references/receipt.md." % rec["generated"][:10])
    return "\n".join(L).rstrip() + "\n"


# ------------------------------------------------------------------ the delivery card

def _len(sec: Optional[float]) -> str:
    if sec is None:
        return "?"
    m, x = divmod(float(sec), 60)
    return "%d:%04.1f" % (m, x) if m else "%.1f s" % x


def card_facts(rec: Dict[str, Any]) -> List[str]:
    """The lines of the delivery card showtime can fill in (files, length, loudness, QA, review, findings,
    cost), in the card's order (references/modes.md section 5)."""
    dv, rv, us = rec.get("delivery") or {}, rec.get("review") or {}, rec.get("usage") or {}
    files = [dv.get("final") or "?"] + [dv[k] for k in ("poster", "share", "credits", "captions") if dv.get(k)]
    if dv.get("exports"):
        files.append("exports/ (%s)" % ", ".join(dv["exports"][:6]) + (" ..." if len(dv["exports"]) > 6 else ""))
    out = ["Files: " + ", ".join(files)]
    out.append("Length: %s%s%s" % (_len(dv.get("duration")), ", %s" % dv["size"] if dv.get("size") else "",
                                   ", %.3g fps" % dv["fps"] if dv.get("fps") else ""))
    if dv.get("lufs") is not None:
        out.append("Loudness: %.1f LUFS integrated, %.1f dBTP true peak%s" % (
            dv["lufs"], dv.get("true_peak") or 0, " (target %g)" % dv["target_lufs"] if dv.get("target_lufs") is not None else ""))
    else:
        out.append("Loudness: not measured (run showtime qa on the final)")
    rb = dv.get("readback") or {}
    heard = ""
    if dv.get("qa") and rb.get("summary"):
        ws = rb.get("words") or []
        heard = ("; read-back: %s" % "; ".join("\"%s\" heard as \"%s\"%s" % (
            w.get("word"), w.get("heard") or "nothing", " at %.1fs" % w["t"] if w.get("t") is not None else "")
            for w in ws[:4])) if ws else "; %s" % rb["summary"]
    out.append("QA: %s" % ("%s (%s fail, %s warn) on %s%s" % (dv["qa"], dv.get("qa_fail"), dv.get("qa_warn"), dv["final"],
                                                              heard)
                          if dv.get("qa") else "not run on %s" % (dv.get("final") or "the final")))
    mode = (rec.get("review_mode") or {}).get("mode")
    note = rv.get("note") or ""
    if not rv.get("packed"):
        out.append("Review: %s" % ("no critic round ran (lean mode)" if mode == "lean" else note or "no critic round ran"))
    else:
        extra = []
        if rv.get("self_reviewed"):
            extra.append("%d a self-review" % rv["self_reviewed"])
        if rv.get("lead_review"):
            extra.append("not an independent critic")
        out.append("Review: %s%s" % (note or "%d round(s)" % rv["packed"], " (%s)" % "; ".join(extra) if extra else ""))
    fd = rv.get("findings")
    if fd:
        bits = ["%d open%s" % (len(fd["open"]), " (%s)" % ", ".join(f["id"] for f in fd["open"]) if fd["open"] else "")]
        if fd["fixed"]:
            bits.append("fixed %s" % ", ".join(f["id"] for f in fd["fixed"]))
        if fd["waived"]:
            bits.append("waived %s" % "; ".join("%s (%s)" % (f["id"], f["reason"]) for f in fd["waived"]))
        out.append("Findings: " + "; ".join(bits))
    else:
        out.append("Findings: none raised (no critic answered)" if not rv.get("packed") else "Findings: none raised")
    if us.get("status") == "reported":
        tk = us.get("tokens") or {}
        tot = tk.get("total") or sum(int(v or 0) for k, v in tk.items() if k != "total")
        out.append("Cost: %s, %s tokens" % (usd_text(us), _tok(tot)))
    else:
        out.append("Cost: %s" % NOT_REPORTED)
    return out


def card(rec: Dict[str, Any]) -> str:
    """The delivery card with every fact showtime knows filled in and the lines only the agent can write left
    as prompts, Look: first among them (references/modes.md section 5)."""
    dv = rec.get("delivery") or {}
    fmt = ", ".join(x for x in (dv.get("size"), "%.3g fps" % dv["fps"] if dv.get("fps") else None) if x)
    L = ["Done: <one line: what it is>%s" % (" (%s)" % fmt if fmt else "")]
    facts = card_facts(rec)
    L += ["  " + ln for ln in facts[:-1]]
    L.append("  Look: <which frames or sheets you opened yourself, at what size, and what you saw in them>")
    L.append("  " + facts[-1])                                   # Cost
    L.append("Assumed: <every assumption that reached the video>")
    L.append("Cheap to change: <...>   Costly: <...>")
    L.append("Next, pick one:\n  1. <...> (about N min)\n  2. <...>\n  3. <...>")
    return "\n".join(L) + "\n"


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

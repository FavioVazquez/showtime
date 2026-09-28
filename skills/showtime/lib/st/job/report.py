"""A local, redacted bug report (`showtime report`, also meant for `showtime doctor --report`).

Collects the environment, the doctor table, the job ledger, the tail of every
log that mentions an error, and the check/qa verdicts into one Markdown file.
Home paths, the user name, e-mail addresses and anything that looks like a
secret are replaced before writing; a second pass re-scans the result and
repeats until nothing matches. Nothing is uploaded, ever: the user reads the
file and decides what to share.
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import __version__
from .. import platform as plat
from ..common import read_json

LOG_TAIL = 40
MAX_LOG_BYTES = 256 * 1024

_SECRET_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("bearer", re.compile(r"(?i)\b(bearer|token|authorization)(\s*[:=]\s*|\s+)([A-Za-z0-9._~+/=-]{12,})")),
    ("kv-secret", re.compile(r"(?i)\b([A-Z0-9_]*(?:api[_-]?key|secret|passw(?:or)?d|token|access[_-]?key)[A-Z0-9_]*)"
                             r"(\s*[:=]\s*)(['\"]?)([^\s'\"]{6,})")),
    ("url-cred", re.compile(r"(?i)(https?://)([^/\s:@]+):([^/\s@]+)@")),
    ("url-query-secret", re.compile(r"(?i)([?&](?:key|token|sig|signature|access_token|api_key|auth)=)([^&\s]+)")),
    ("known-token", re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
                               r"xox[abposr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|"
                               r"hf_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{16,})")),
    ("long-hex", re.compile(r"\b[0-9a-fA-F]{40,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
]
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def _user_names() -> List[str]:
    names = set()
    for k in ("USER", "USERNAME", "LOGNAME"):
        v = os.environ.get(k)
        if v and len(v) >= 2:
            names.add(v)
    try:
        names.add(plat.user_home().name)
    except Exception:  # noqa: BLE001
        pass
    return sorted((n for n in names if n and n.lower() not in ("root", "user", "admin", "home")), key=len, reverse=True)


def _home_variants() -> List[str]:
    h = str(plat.user_home())
    out = {h, h.replace("\\", "/"), h.replace("/", "\\"), h.replace("\\", "\\\\")}  # + JSON-escaped Windows form
    return sorted(out, key=len, reverse=True)


def redact(text: str) -> str:
    s = text
    for h in _home_variants():
        s = s.replace(h, "~")
    for name, rx in _SECRET_PATTERNS:
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
    s = _EMAIL.sub("<email>", s)
    for n in _user_names():
        s = re.sub(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(n), "<user>", s)
    return s


def audit(text: str) -> List[str]:
    """Anything a reviewer would still call sensitive. Empty list = clean."""
    hits: List[str] = []
    for h in _home_variants():
        if h in text:
            hits.append("home path")
    for name, rx in _SECRET_PATTERNS:
        for m in rx.finditer(text):
            if "<REDACTED>" not in m.group(0):
                hits.append(name)
                break
    if _EMAIL.search(text):
        hits.append("email")
    for n in _user_names():
        if re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(n), text):
            hits.append("user name")
    return hits


def scrub(text: str, rounds: int = 5) -> Tuple[str, List[str]]:
    for _ in range(rounds):
        left = audit(text)
        if not left:
            return text, []
        text = redact(text)
    return text, audit(text)


def _tail(path: Path, n: int = LOG_TAIL) -> List[str]:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > MAX_LOG_BYTES:
                fh.seek(size - MAX_LOG_BYTES)
            data = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return data.splitlines()[-n:]


def _doctor_json() -> Optional[Dict[str, Any]]:
    """Run the doctor quickly in a child process and parse its JSON."""
    try:
        cp = subprocess.run([sys.executable, "-m", "st.doctor", "--json", "--quick"], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=120, encoding="utf-8", errors="replace",
                            env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]) +
                                     os.pathsep + os.environ.get("PYTHONPATH", "")))
        return json.loads(cp.stdout) if cp.stdout.strip().startswith("{") else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def build(job: Optional[Path] = None, out: Optional[Path] = None, *, doctor: bool = True,
          problem: str = "", doctor_json: Optional[Path] = None) -> Dict[str, Any]:
    """Write bug-report.md; returns {path, redactions_left, sections}."""
    from . import ledger
    L: List[str] = ["# showtime bug report", "",
                    "Generated %s by `showtime report`. Nothing was uploaded. Read it, remove anything you do not "
                    "want to share, then attach it to an issue yourself." % time.strftime("%Y-%m-%d %H:%M"), ""]
    L += ["## What happened", "", problem.strip() or
          "(describe: what you expected, what you saw, and at which timestamp of the video)", ""]
    env = ledger.env_snapshot()
    L += ["## Environment", "", "| item | value |", "|---|---|"]
    rows = [("showtime", "%s%s" % (env.get("showtime"), " (%s)" % env["git"] if env.get("git") else "")),
            ("platform", "%s (%s cpus)" % (env.get("platform"), env.get("cpus"))), ("python", env.get("python")),
            ("node", env.get("node")), ("setup tier", "%s %s" % (env.get("setup_tier"), ",".join(env.get("extras") or []))),
            ("ffmpeg", "%s (%s) %s" % ((env.get("ffmpeg") or {}).get("version"), (env.get("ffmpeg") or {}).get("source"),
                                       (env.get("ffmpeg") or {}).get("path"))),
            ("browser", "%s %s %s" % tuple(((env.get("browser") or {}).get(k) or "") for k in ("kind", "version", "path")))]
    for k, v in rows:
        L.append("| %s | %s |" % (k, str(v).replace("|", "\\|")))
    L.append("")
    sections = ["environment"]
    if doctor or doctor_json:
        d = read_json(doctor_json, None) if doctor_json else _doctor_json()
        if d:
            sections.append("doctor")
            L += ["## Doctor (quick)", "", "| check | status | detail |", "|---|---|---|"]
            for c in d.get("checks", d.get("results", [])) or []:
                if isinstance(c, dict):
                    fix = (" (fix: %s)" % c["hint"]) if c.get("hint") and c.get("status") in ("warn", "fail", "WARN", "FAIL") else ""
                    L.append("| %s | %s | %s |" % (c.get("check") or c.get("name"), c.get("status"),
                                                   (str(c.get("detail", "")) + fix).replace("|", "\\|").replace("\n", " ")[:240]))
            L.append("")
    if job is not None:
        sections.append("job")
        L += ["## Job", "", "Folder: `%s`" % job, ""]
        data = None
        try:
            data = ledger.load(job)
        except Exception:  # noqa: BLE001
            data = None
        if data:
            L += ["```", "\n".join(ledger.status_lines(job, data)), "```", ""]
            slim = {k: data.get(k) for k in ("mode", "stage", "stages", "warnings", "cache", "qa", "command")}
            L += ["job.json (excerpt):", "", "```json", json.dumps(slim, indent=2)[:6000], "```", ""]
        rj = read_json(job / "render.json", None) if (job / "render.json").is_file() else None
        if isinstance(rj, dict):
            slim = {k: rj.get(k) for k in ("ok", "width", "height", "fps", "duration", "frames", "workers", "browser",
                                           "capture", "encode", "audio", "warnings", "timings", "fps_capture")}
            L += ["render.json (excerpt):", "", "```json", json.dumps(slim, indent=2)[:4000], "```", ""]
        for qa in sorted((job / "work" / "qa").glob("*/qa.json")) if (job / "work" / "qa").is_dir() else []:
            q = read_json(qa, {}) or {}
            L += ["QA `%s`: **%s**" % (qa.parent.name, q.get("verdict")), ""]
            for f in (q.get("findings") or [])[:15]:
                t = " t=%.2fs" % f["t"] if f.get("t") is not None else ""
                L.append("- %s %s%s: %s" % (f.get("severity"), f.get("rule"), t, f.get("message")))
            if q.get("sheet"):
                L.append("- contact sheet: `%s`" % q["sheet"])
            L.append("")
        proj = Path(data["project"]) if data and data.get("project") else None
        ck = proj / "work" / "check" / "report.json" if proj else None
        if ck and ck.is_file():
            c = read_json(ck, {}) or {}
            L += ["Last `showtime check`: %s errors, %s warnings" % ((c.get("summary") or {}).get("errors"),
                                                                    (c.get("summary") or {}).get("warnings")), ""]
            for f in (c.get("findings") or [])[:12]:
                L.append("- %s %s: %s" % (f.get("severity"), f.get("code"), f.get("message")))
            L.append("")
        logs = []
        for root in (job / "work" / "logs", job / "work" / "diagnostics"):
            if root.is_dir():
                logs += sorted(p for p in root.rglob("*") if p.is_file() and p.suffix in (".log", ".txt", ".json"))
        shown = 0
        for lp in logs:
            tail = _tail(lp)
            if not any(re.search(r"(?i)error|fail|exception|traceback", x) for x in tail) and shown >= 2:
                continue
            shown += 1
            L += ["Log tail `%s` (last %d lines):" % (lp.relative_to(job), len(tail)), "", "```", "\n".join(tail), "```", ""]
            if shown >= 8:
                break
    text, left = scrub("\n".join(L) + "\n")
    dest = Path(out) if out else ((job / "bug-report.md") if job else Path.cwd() / "showtime-bug-report.md")
    if dest.exists():
        stem, n = dest.with_suffix(""), 2
        while Path("%s-%d.md" % (stem, n)).exists():
            n += 1
        dest = Path("%s-%d.md" % (stem, n))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8", newline="\n")
    return {"path": str(dest), "redactions_left": left, "sections": sections, "bytes": len(text.encode("utf-8"))}

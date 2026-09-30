"""Token counts (and API-equivalent cost) from the agent's own session log, for the job receipt.

What is read, and only that:
  * a file the caller names (`showtime receipt --transcript FILE`, the plugin's Stop hook, or
    $SHOWTIME_TRANSCRIPT): the CURRENT session's log. Nothing else is ever looked up or scanned.
  * from every line, only the numbers of the model's usage record, the model name and the time stamp.
    No prompt, reply, tool call or file content is kept, printed or copied.

Hosts:
  * Claude Code   session JSONL, one usage record per model message (input, output, cache read, cache
                  write) plus the sub-agent logs kept beside it (<session>/subagents/*.jsonl).
  * Codex         rollout JSONL with cumulative `token_count` events (tokens only: it reports no dollars).
  * Devin         the CLI's session database (SQLite, read-only): per request, the model id and the token
                  metrics of `message_nodes`, selected in SQL; never a message's text. The sessions counted
                  are the ones whose working folder holds the job. Devin shows tokens, not dollars: the cost
                  is an estimate at its listed per-token prices (DEVIN_PRICES, dated) and says so.
  * anything else "not reported by this agent".

Cost is what the same tokens cost at the public API list price (PRICES, dated). A subscription plan
does not pay per video; the figure says what the work weighs, not what was charged.

Stdlib only, Python 3.8+.
"""
from __future__ import annotations

import calendar
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

NOT_REPORTED = "not reported by this agent"
MAX_LOG_BYTES = 400 * 1024 * 1024        # a session log larger than this is skipped, not read

# USD per million tokens, Anthropic first-party API list prices. write_1h is the price of the 1-hour
# cache write (Claude Code's default), write_5m the 5-minute one (1.25x input). Checked against the cost
# Claude Code itself reported for a benchmark run of claude-opus-5-5 (within a cent).
PRICES_AS_OF = "2026-09-29"
PRICES: Dict[str, Dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.20, "write_5m": 5.0, "write_1h": 8.0, "fast": 2.0},
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cache_read": 0.20, "write_5m": 2.5, "write_1h": 4.0},
    "claude-sonnet-5": {"input": 2.0, "output": 10.0, "cache_read": 0.20, "write_5m": 2.5, "write_1h": 4.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cache_read": 0.10, "write_5m": 1.25, "write_1h": 2.0},
}
# Devin's listed per-token prices (USD per million tokens) for the models it runs; it lists no cache-write
# price, so a cache write counts at the input price. A model not listed here is not priced (a lower bound).
DEVIN_PRICES_AS_OF = "2026-09-30"
DEVIN_PRICES: Dict[str, Dict[str, float]] = {
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cache_read": 0.20, "write_5m": 4.0, "write_1h": 4.0},
    "swe-2": {"input": 0.0, "output": 0.0, "cache_read": 0.0, "write_5m": 0.0, "write_1h": 0.0},
}
_DEVIN_EFFORT = re.compile(r"-(?:minimal|low|medium|high|xhigh|max|slow|fast)$")
WEB_SEARCH_USD = 0.01                    # per search request
_DATE_SUFFIX = re.compile(r"-\d{8}$")
FIELDS = ("input", "output", "cache_read", "write_5m", "write_1h")


def canonical_model(name: Optional[str]) -> str:
    return _DATE_SUFFIX.sub("", str(name or "").strip())


def parse_ts(s: Any) -> Optional[float]:
    """An ISO time stamp (UTC 'Z' or with an offset) as epoch seconds; None when it is not one."""
    if not isinstance(s, str) or len(s) < 19:
        return None
    try:
        t = calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None
    m = re.search(r"([+-])(\d\d):?(\d\d)$", s[19:])
    if m:
        off = (int(m.group(2)) * 3600 + int(m.group(3)) * 60) * (1 if m.group(1) == "+" else -1)
        t -= off
    return float(t)


def _int(v: Any) -> int:
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0


def _lines(path: Path) -> Iterable[str]:
    with open(str(path), "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            yield line


def sniff(path: Path) -> Optional[str]:
    """'claude', 'codex' or 'devin' by the shape of the first records; None when it is none of them."""
    try:
        with open(str(path), "rb") as f:
            if f.read(16) == b"SQLite format 3\x00":
                return "devin"
        if path.stat().st_size > MAX_LOG_BYTES:
            return None
        n = 0
        for line in _lines(path):
            n += 1
            if '"token_count"' in line and '"payload"' in line:
                return "codex"
            if '"usage"' in line and '"input_tokens"' in line:
                return "claude"
            if n > 4000:
                break
    except OSError:
        return None
    return None


# ------------------------------------------------------------------ Claude Code

def _claude_files(path: Path) -> List[Path]:
    files = [path]
    sub = path.with_suffix("") / "subagents"
    if sub.is_dir():
        files += sorted(sub.glob("*.jsonl"))
    return files


def read_claude(path: Path, since: Optional[float] = None, until: Optional[float] = None) -> Dict[str, Any]:
    """Sum the usage records of a Claude Code session log (and its sub-agent logs).

    A message that was logged more than once (one line per content block, or a resumed session) counts
    once: records are keyed by message id and the largest count of each field wins. `since`/`until`
    (epoch seconds) keep only messages stamped inside that window."""
    seen: Dict[str, Dict[str, Any]] = {}
    subs = set()
    files = 0
    for f in _claude_files(path):
        try:
            if f.stat().st_size > MAX_LOG_BYTES:
                continue
            files += 1
            for n, line in enumerate(_lines(f)):
                if '"usage"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                msg = d.get("message") if isinstance(d, dict) else None
                if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
                    continue
                ts = parse_ts(d.get("timestamp"))
                if ts is not None and ((since is not None and ts < since) or (until is not None and ts > until)):
                    continue
                if ts is None and since is not None:
                    continue                      # cannot place it in the window: do not guess
                u = msg["usage"]
                cc = u.get("cache_creation") if isinstance(u.get("cache_creation"), dict) else None
                if cc:
                    w5, w1 = _int(cc.get("ephemeral_5m_input_tokens")), _int(cc.get("ephemeral_1h_input_tokens"))
                else:
                    w5, w1 = _int(u.get("cache_creation_input_tokens")), 0   # no split: the cheaper (5 min) price
                st = u.get("server_tool_use") if isinstance(u.get("server_tool_use"), dict) else {}
                rec = {"model": canonical_model(msg.get("model")), "fast": u.get("speed") == "fast",
                       "input": _int(u.get("input_tokens")), "output": _int(u.get("output_tokens")),
                       "cache_read": _int(u.get("cache_read_input_tokens")), "write_5m": w5, "write_1h": w1,
                       "searches": _int(st.get("web_search_requests")), "ts": ts}
                if f != path and rec["model"] != "<synthetic>" and any(rec[k] for k in FIELDS):
                    subs.add(str(f))              # a sub-agent that worked inside the window
                key = str(msg.get("id") or d.get("requestId") or "%s:%d" % (f.name, n))
                old = seen.get(key)
                if old:
                    for k in FIELDS + ("searches",):
                        rec[k] = max(rec[k], old[k])
                    rec["ts"] = old["ts"] if old["ts"] is not None else rec["ts"]
                seen[key] = rec
        except OSError:
            continue
    models: Dict[str, Dict[str, Any]] = {}
    first = last = None
    for rec in seen.values():
        m = rec["model"]
        if not m or m == "<synthetic>" or not any(rec[k] for k in FIELDS):
            continue
        b = models.setdefault(m, {"messages": 0, "searches": 0, "fast": {k: 0 for k in FIELDS},
                                   **{k: 0 for k in FIELDS}})
        b["messages"] += 1
        b["searches"] += rec["searches"]
        tgt = b["fast"] if rec["fast"] else b
        for k in FIELDS:
            tgt[k] += rec[k]
        if rec["ts"] is not None:
            first = rec["ts"] if first is None else min(first, rec["ts"])
            last = rec["ts"] if last is None else max(last, rec["ts"])
    for b in models.values():
        if not any(b["fast"].values()):
            del b["fast"]
    return {"host": "claude-code", "files": files, "messages": sum(b["messages"] for b in models.values()),
            "models": models, "first": first, "last": last, "subagents": len(subs)}


# ------------------------------------------------------------------ Codex

def read_codex(path: Path, since: Optional[float] = None, until: Optional[float] = None) -> Dict[str, Any]:
    """Tokens of a Codex rollout log: the cumulative `token_count` at the end of the window minus the one
    at its start. Codex reports tokens, not dollars."""
    base: Dict[str, int] = {}
    end: Dict[str, int] = {}
    model = None
    first = last = None
    n = 0
    try:
        if path.stat().st_size > MAX_LOG_BYTES:
            return {"host": "codex", "files": 0, "models": {}, "messages": 0}
        for line in _lines(path):
            if '"token_count"' not in line and '"turn_context"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            pl = d.get("payload") if isinstance(d, dict) else None
            if not isinstance(pl, dict):
                continue
            if pl.get("type") is None and isinstance(pl.get("model"), str):
                model = model or pl["model"]           # turn_context
            if pl.get("type") != "token_count":
                continue
            info = pl.get("info")
            tot = info.get("total_token_usage") if isinstance(info, dict) else None
            if not isinstance(tot, dict):
                continue
            cur = {"input": _int(tot.get("input_tokens")), "cached_input": _int(tot.get("cached_input_tokens")),
                   "output": _int(tot.get("output_tokens")), "reasoning": _int(tot.get("reasoning_output_tokens"))}
            ts = parse_ts(d.get("timestamp"))
            if since is not None and ts is not None and ts < since:
                base = cur
                continue
            if until is not None and ts is not None and ts > until:
                continue
            end = cur
            n += 1
            if ts is not None:
                first = ts if first is None else min(first, ts)
                last = ts if last is None else max(last, ts)
    except OSError:
        return {"host": "codex", "files": 0, "models": {}, "messages": 0}
    if not end:
        return {"host": "codex", "files": 1, "models": {}, "messages": 0}
    delta = {k: max(0, end[k] - base.get(k, 0)) for k in end}
    return {"host": "codex", "files": 1, "messages": n, "first": first, "last": last,
            "models": {canonical_model(model) or "unknown": {"messages": n, **delta}}}


# ------------------------------------------------------------------ Devin

def devin_db(env: Optional[Dict[str, str]] = None) -> Optional[Path]:
    """The Devin CLI's session database on this machine, None when there is none."""
    env = dict(os.environ if env is None else env)
    bases = [env.get("XDG_DATA_HOME") or "", str(Path.home() / ".local" / "share"), env.get("LOCALAPPDATA") or "",
             env.get("APPDATA") or "", str(Path.home() / "Library" / "Application Support")]
    for b in bases:
        if b:
            p = Path(b) / "devin" / "cli" / "sessions.db"
            if p.is_file():
                return p
    return None


_DEVIN_KEYS = ("message_id", "metadata.created_at", "metadata.generation_model", "metadata.metrics.input_tokens",
               "metadata.metrics.output_tokens", "metadata.metrics.cache_read_tokens",
               "metadata.metrics.cache_creation_tokens")


def _dig(d: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        d = d.get(part) if isinstance(d, dict) else None
    return d if isinstance(d, (int, float, str)) and not isinstance(d, bool) else None


def devin_model(name: Any) -> str:
    """A Devin model id without its effort suffix (claude-opus-5-5-high -> claude-opus-5-5, swe-2-medium -> swe-2)."""
    return _DEVIN_EFFORT.sub("", canonical_model(name))


def _inside(folder: str, target: Optional[Path]) -> bool:
    if target is None:
        return True
    try:
        f = Path(folder).expanduser().resolve()
        t = target.expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return f == t or f in t.parents


def read_devin(path: Path, since: Optional[float] = None, until: Optional[float] = None,
               where: Optional[Path] = None) -> Dict[str, Any]:
    """Token metrics of the Devin CLI sessions that worked in `where` (the job folder or a parent of it).

    Read-only, and only numbers: SQL selects each assistant message's id, model id, time and token metrics
    (chat_message -> metadata.metrics); the message text is never selected. A message stored in several
    nodes of the session forest counts once (keyed by its message id)."""
    empty = {"host": "devin", "files": 0, "models": {}, "messages": 0}
    try:
        con = sqlite3.connect("%s?mode=ro" % path.resolve().as_uri(), uri=True, timeout=5)
    except (sqlite3.Error, OSError, ValueError):
        return empty
    try:
        sessions = [sid for sid, wd in con.execute("SELECT id, working_directory FROM sessions")
                    if _inside(str(wd or ""), where)]
        if not sessions:
            return dict(empty, files=1, note="no Devin session worked in this job's folder")
        marks = ",".join("?" * len(sessions))
        try:
            rows = con.execute("SELECT session_id, created_at, %s FROM message_nodes WHERE session_id IN (%s) "
                               "AND json_extract(chat_message, '$.metadata.metrics') IS NOT NULL"
                               % (", ".join("json_extract(chat_message, '$.%s')" % k for k in _DEVIN_KEYS), marks),
                               sessions).fetchall()
        except sqlite3.OperationalError:          # an SQLite without JSON functions: parse, keep the same fields
            rows = []
            for sid, created, raw in con.execute("SELECT session_id, created_at, chat_message FROM message_nodes "
                                                 "WHERE session_id IN (%s) AND chat_message LIKE '%%\"metrics\"%%'"
                                                 % marks, sessions):
                try:
                    d = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                rows.append((sid, created) + tuple(_dig(d, k) for k in _DEVIN_KEYS))
                del d
        try:
            heads = con.execute("SELECT updated_at FROM subagent_heads WHERE session_id IN (%s)" % marks,
                                sessions).fetchall()
        except sqlite3.Error:
            heads = []
    except sqlite3.Error:
        return dict(empty, files=1)
    finally:
        con.close()

    def when(v: Any) -> Optional[float]:
        try:
            t = float(v)
        except (TypeError, ValueError):
            return None
        return t / 1000.0 if t > 1e11 else t          # seconds (milliseconds on some builds)

    seen: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for n, (sid, created, mid, stamp, model, i, o, cr, cc) in enumerate(rows):
        ts = parse_ts(stamp)
        ts = ts if ts is not None else when(created)
        key = (str(sid), str(mid or "row:%d" % n))
        old = seen.get(key)
        if old is not None:                         # the same message in another node: once, at its first time
            if ts is not None and (old["ts"] is None or ts < old["ts"]):
                old["ts"] = ts
            continue
        seen[key] = {"model": canonical_model(model) or "unknown", "input": _int(i), "output": _int(o),
                     "cache_read": _int(cr), "write_5m": _int(cc), "write_1h": 0, "ts": ts}
    for key in [k for k, r in seen.items() if (r["ts"] is None and since is not None) or (r["ts"] is not None and (
            (since is not None and r["ts"] < since) or (until is not None and r["ts"] > until)))]:
        del seen[key]
    models: Dict[str, Dict[str, Any]] = {}
    first = last = None
    for rec in seen.values():
        if not any(rec[k] for k in FIELDS):
            continue
        b = models.setdefault(rec["model"], {"messages": 0, "searches": 0, **{k: 0 for k in FIELDS}})
        b["messages"] += 1
        for k in FIELDS:
            b[k] += rec[k]
        if rec["ts"] is not None:
            first = rec["ts"] if first is None else min(first, rec["ts"])
            last = rec["ts"] if last is None else max(last, rec["ts"])
    subagents = sum(1 for (u,) in heads if since is None or (when(u) or 0) >= since)
    return {"host": "devin", "files": 1, "sessions": len({k[0] for k in seen}), "subagents": subagents,
            "messages": sum(b["messages"] for b in models.values()), "models": models, "first": first, "last": last}


# ------------------------------------------------------------------ cost and the summary block

def price_of(model: str, host: Optional[str] = None) -> Optional[Dict[str, float]]:
    if host == "devin":
        return DEVIN_PRICES.get(devin_model(model))
    return PRICES.get(canonical_model(model))


def cost_usd(bucket: Dict[str, Any], model: str, host: Optional[str] = None) -> Optional[float]:
    p = price_of(model, host)
    if p is None:
        return None
    usd = sum(bucket.get(k, 0) * p[k] for k in FIELDS) / 1e6
    fast = bucket.get("fast")
    if fast:
        mult = p.get("fast")
        if mult is None:
            return None                     # a fast-mode price we do not know: no cost, never a guess
        usd += mult * sum(fast.get(k, 0) * p[k] for k in FIELDS) / 1e6
    usd += bucket.get("searches", 0) * WEB_SEARCH_USD
    return usd


def summarize(rd: Dict[str, Any], transcript_note: str = "") -> Dict[str, Any]:
    """The receipt's usage block from a read_claude/read_codex result."""
    models = rd.get("models") or {}
    if not models:
        return {"status": "not_reported", "host": rd.get("host"),
                "note": rd.get("note") or "the session log has no model usage in this window"}
    host = rd.get("host")
    devin = host == "devin"
    out_models: Dict[str, Any] = {}
    tot = {k: 0 for k in FIELDS}
    usd = 0.0
    unpriced: List[str] = []
    codex = rd.get("host") == "codex"
    for m, b in sorted(models.items()):
        row = {k: b.get(k, 0) + (b.get("fast") or {}).get(k, 0) for k in
               (("input", "cached_input", "output", "reasoning") if codex else FIELDS)}
        row["messages"] = b.get("messages", 0)
        if not codex:
            c = cost_usd(b, m, host)
            row["cost_usd"] = round(c, 4) if c is not None else None
            if c is None:
                unpriced.append(m)
            else:
                usd += c
            for k in FIELDS:
                tot[k] += row[k]
        else:
            row["cost_usd"] = None
        out_models[m] = row
    res: Dict[str, Any] = {"status": "reported", "host": rd.get("host"), "messages": rd.get("messages"),
                           "models": out_models}
    if rd.get("subagents") is not None:
        res["subagents"] = rd["subagents"]
    if codex:
        t = {k: sum(r.get(k, 0) for r in out_models.values()) for k in ("input", "cached_input", "output", "reasoning")}
        res["tokens"] = t
        res["cost_usd"] = None
        res["cost_note"] = "Codex reports tokens, not dollars: cost %s" % NOT_REPORTED
        return res
    res["tokens"] = dict(tot, total=sum(tot.values()))
    if len(out_models) > 1 and res["tokens"]["total"]:
        for row in out_models.values():             # e.g. a Devin Fusion session: the lead and its sidekick
            row["token_share"] = round(sum(row[k] for k in FIELDS) / float(res["tokens"]["total"]), 4)
    if devin:
        res["sessions"] = rd.get("sessions")
        res["prices_as_of"] = DEVIN_PRICES_AS_OF
        priced = [m for m in out_models if m not in unpriced]
        if not priced:
            res["cost_usd"] = None
            res["cost_note"] = "Devin reports tokens, not dollars; no listed price for %s: cost %s" % (
                ", ".join(unpriced), NOT_REPORTED)
        else:
            res["cost_usd"] = round(usd, 2)
            res["cost_note"] = ("est., at Devin's listed per-token prices as of %s (Devin reports tokens, not dollars; "
                                "cache writes at the input price); a plan does not pay per video" % DEVIN_PRICES_AS_OF)
            if unpriced:
                res["cost_note"] += "; %s not priced, so this is a lower bound" % ", ".join(unpriced)
        if transcript_note:
            res["note"] = transcript_note
        return res
    res["prices_as_of"] = PRICES_AS_OF
    if unpriced and len(unpriced) == len(out_models):
        res["cost_usd"] = None
        res["cost_note"] = "no price table for %s: cost %s" % (", ".join(unpriced), NOT_REPORTED)
    else:
        res["cost_usd"] = round(usd, 2)
        res["cost_note"] = ("API-equivalent at list prices as of %s; a plan does not pay per video" % PRICES_AS_OF)
        if unpriced:
            res["cost_note"] += "; %s not priced, so this is a lower bound" % ", ".join(unpriced)
    if transcript_note:
        res["note"] = transcript_note
    return res


def read_usage(path: Any, since: Optional[float] = None, until: Optional[float] = None,
               host: Optional[str] = None, where: Optional[Path] = None) -> Dict[str, Any]:
    """The usage block for a session log. Never raises: a missing or unreadable file is 'not reported'.
    `where` (the job folder) picks the Devin sessions that worked there."""
    p = Path(str(path)).expanduser() if path else None
    if p is None or not p.is_file():
        return {"status": "not_reported", "host": host, "note": "no session log to read"}
    kind = host if host in ("claude", "codex", "devin") else sniff(p)
    if kind == "devin":
        return summarize(read_devin(p, since, until, where))
    if kind == "claude":
        return summarize(read_claude(p, since, until))
    if kind == "codex":
        return summarize(read_codex(p, since, until))
    return {"status": "not_reported", "host": host, "note": "the session log is not a format showtime reads"}

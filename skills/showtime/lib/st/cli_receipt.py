"""`showtime receipt`: what a job took (request, assumptions, rounds, renders, images, time, tokens, cost)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .common import ShowtimeError, log, print_json

COMMANDS = {
    "receipt": "Write the job's receipt: request, assumptions, rounds, renders, time, tokens and cost (receipt.md)",
}

RAW = argparse.RawDescriptionHelpFormatter
HOOK_MAX_AGE = 12 * 3600      # the hook only refreshes a job that was worked on in the last 12 hours


def register(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("receipt", help=COMMANDS["receipt"], formatter_class=RAW, description=(
        "Write <job>/receipt.md (people), <job>/receipt.json (the stable format, schema 1) and one line in\n"
        "<job>/share.txt: the request as typed, the assumptions, review rounds, full vs partial renders, the\n"
        "images showtime made for looking, wall time from job start to final, and tokens and cost when the\n"
        "agent's session log is named. What is not known says \"not reported by this agent\"; nothing is\n"
        "estimated. It is rewritten by qa, deliver and this command, so it can always be regenerated.\n\n"
        "Tokens and cost: only from a session log you name (--transcript, $SHOWTIME_TRANSCRIPT, or the\n"
        "plugin's Stop hook for Claude Code), only the current session, and only its numbers: no prompt,\n"
        "reply or file content is read out or copied. Claude Code logs are priced at the public API list\n"
        "price (dated in the receipt; a plan does not pay per video). Codex logs give tokens only. Under Devin\n"
        "its CLI session database is read by itself (the sessions that worked in the job's folder; numbers\n"
        "only), and the cost is an estimate at Devin's listed per-token prices, labelled as one."),
        epilog=("examples:\n"
                "  showtime receipt                         # the current or newest job\n"
                "  showtime receipt launch-teaser --transcript ~/.claude/projects/<project>/<session>.jsonl\n"
                "  showtime receipt --whole-session --transcript rollout.jsonl --host codex\n"
                "  showtime receipt --print                 # show it, write nothing\n"
                "  showtime receipt my-job --card           # the delivery card's facts, ready for the Look: line"))
    p.add_argument("job", nargs="?", help="job folder or name (default: the current or newest job)")
    p.add_argument("--transcript", metavar="FILE", help="the current session's log (Claude Code .jsonl, a Codex rollout, "
                   "or Devin's sessions.db)")
    p.add_argument("--host", choices=["claude", "codex", "devin"], help="the log's format (default: detected)")
    p.add_argument("--whole-session", action="store_true",
                   help="count the whole session, not only the time from the job's start to its last update")
    p.add_argument("--no-share", action="store_true", help="do not touch share.txt")
    p.add_argument("--print", dest="print_only", action="store_true", help="print the receipt, write nothing")
    p.add_argument("--card", action="store_true",
                   help="print the delivery card with the facts showtime knows filled in (files, length, loudness, qa, "
                        "review, findings, cost) and the lines only you can write (Look:, Assumed:, Next) as prompts; "
                        "writes nothing (references/modes.md section 5)")
    p.add_argument("--hook", action="store_true", help=argparse.SUPPRESS)   # the Stop hook: JSON on stdin, no output
    p.add_argument("--json", action="store_true", help="print receipt.json instead of the file paths")
    p.set_defaults(func=cmd_receipt)


def _hook() -> int:
    """Claude Code Stop hook: refresh the receipt of the job worked on in this session. Silent, never fails."""
    try:
        payload = {}
        if not sys.stdin.isatty():
            try:
                payload = json.loads(sys.stdin.read() or "{}")
            except ValueError:
                payload = {}
        cwd = payload.get("cwd")
        if isinstance(cwd, str) and os.path.isdir(cwd):
            os.chdir(cwd)
        from .job import ledger, receipt
        job = ledger.latest()
        if job is None or not (job / "job.json").is_file():
            return 0
        data = ledger.load(job)
        upd = ledger._parse_iso(data.get("updated"))
        if upd is None or time.time() - upd > HOOK_MAX_AGE or ledger.last_output(job, data) is None:
            return 0
        tp = payload.get("transcript_path")
        tp = tp if isinstance(tp, str) and os.path.isfile(tp) else None
        if tp:
            receipt.remember_source(job, tp, "claude", str(payload.get("session_id") or "") or None)
        receipt.write(job, transcript=tp, host="claude" if tp else None)
    except Exception:  # noqa: BLE001 - a hook must never get in the way of the session
        pass
    return 0


def cmd_receipt(args: argparse.Namespace) -> int:
    if args.hook:
        return _hook()
    from .job import ledger, receipt
    job = ledger.resolve(args.job)
    if args.card:
        sys.stdout.write(receipt.card(receipt.build(job, args.transcript, args.host, args.whole_session)))
        return 0
    if args.print_only:
        rec = receipt.build(job, args.transcript, args.host, args.whole_session)
        if args.json:
            print_json(rec)
        else:
            sys.stdout.write(receipt.to_markdown(rec))
            print(receipt.line(rec))
        return 0
    res = receipt.write(job, transcript=args.transcript, host=args.host, whole_session=args.whole_session,
                        share=not args.no_share)
    if args.json:
        print_json(res["receipt"])
        return 0
    us = res["receipt"]["usage"]
    if us.get("status") != "reported":
        log("tokens and cost: not reported by this agent (name the session log with --transcript to fill them in)")
    print(res["line"])
    for k in ("receipt", "json", "share"):
        if res["files"].get(k):
            print(res["files"][k])
    return 0

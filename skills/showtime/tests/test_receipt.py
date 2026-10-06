#!/usr/bin/env python3
"""Job receipt tests (no browser, no ffmpeg render): receipt.md / receipt.json / the share.txt line.

  * usage: token sums from a hand-made Claude Code session log (a message logged twice counts once, the
    largest count wins, sub-agent logs are added, the time window is honoured, an unpriced model makes a lower
    bound and says so), the price arithmetic, a Codex rollout (tokens only), a Devin sessions.db (numbers selected in
    SQL, a copied node counts once, only sessions in the job's folder, an estimate labelled "est.", Fusion token
    shares), and every "not reported" path
  * review rounds: a pairwise round counts both orders' FINDINGS; findings in a session with no sub-agent are
    flagged "not an independent critic"
  * privacy: nothing but numbers leaves a session log (prompt, reply and secrets never reach the receipt, and
    neither does the log's path); the request is masked for keys, e-mail addresses and home paths
  * receipt from a fixture job: the request as typed, assumptions, review rounds (self-review noticed),
    full/preview/partial renders, images made for looking, wall time, share.txt block replaced not appended
  * `job note --render`, `--request`, the deliver note and qa refresh the receipt; `receipt --hook` is silent
  * the Stop hook manifest and the MCP tool are wired to files that exist

Stdlib only. usage: python tests/test_receipt.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import calendar
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
REPO = SKILL.parent.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402
from st.job import ledger, receipt, usage  # noqa: E402

ENV = build_env(showtime_home())
ENV.pop("SHOWTIME_OUT", None)
ENV.pop("SHOWTIME_TRANSCRIPT", None)
ENV.pop("SHOWTIME_AGENT", None)
ENV["SHOWTIME_OFFLINE"] = "1"


def showtime(*args, check=True, cwd=None, stdin_text=None, timeout=180):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, cwd=cwd,
                        input=stdin_text if stdin_text is not None else "", stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def epoch(iso):
    return float(calendar.timegm(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")))


def iso_utc(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(t))


def jl(rows):
    return "\n".join(json.dumps(r) for r in rows) + "\n"


def asst(mid, model, ts, inp=0, out=0, cr=0, cc=None, cc_split=None, searches=0, text="SECRET-REPLY-TEXT"):
    u = {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cr}
    if cc_split is not None:
        u["cache_creation"] = {"ephemeral_5m_input_tokens": cc_split[0], "ephemeral_1h_input_tokens": cc_split[1]}
        u["cache_creation_input_tokens"] = sum(cc_split)
    elif cc is not None:
        u["cache_creation_input_tokens"] = cc
    if searches:
        u["server_tool_use"] = {"web_search_requests": searches}
    return {"type": "assistant", "timestamp": ts, "requestId": "req_" + mid,
            "message": {"id": mid, "model": model, "role": "assistant", "content": [{"type": "text", "text": text}], "usage": u}}


SECRET_PROMPT = "SECRET-PROMPT-TEXT sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"


def claude_fixture(root: Path) -> Path:
    """A small session log: 3 model families, a duplicate line, a sub-agent log, a message before the window."""
    root.mkdir(parents=True, exist_ok=True)
    main = root / "session.jsonl"
    main.write_text(jl([
        {"type": "user", "timestamp": "2026-01-01T10:00:00.000Z", "message": {"role": "user", "content": SECRET_PROMPT}},
        asst("m4", "claude-opus-5-5", "2026-01-01T09:00:00.000Z", inp=5, out=5),                       # before the window
        asst("m1", "claude-opus-5-5", "2026-01-01T10:00:10.000Z", inp=10, out=100, cr=1000, cc_split=(0, 2000)),
        asst("m1", "claude-opus-5-5", "2026-01-01T10:00:11.000Z", inp=10, out=500, cr=1000, cc_split=(0, 2000)),  # same message, final count
        asst("m2", "claude-haiku-4-5-20251001", "2026-01-01T10:01:00.000Z", inp=1000, out=200, cc=400, searches=3),
        asst("m3", "<synthetic>", "2026-01-01T10:01:30.000Z"),
        asst("m5", "claude-mystery-9", "2026-01-01T10:02:00.000Z", inp=100, out=100),
        {"type": "system", "subtype": "cost-state", "timestamp": "2026-01-01T10:02:30.000Z"},
    ]), encoding="utf-8")
    sub = root / "session" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-a.jsonl").write_text(jl([
        asst("m6", "claude-sonnet-5-5", "2026-01-01T10:03:00.000Z", inp=50, out=1000, cr=2000, cc_split=(100, 0)),
        asst("m2", "claude-haiku-4-5-20251001", "2026-01-01T10:01:00.000Z", inp=1000, out=200, cc=400, searches=3),
    ]), encoding="utf-8")
    return main


def codex_fixture(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)

    def tc(ts, i, c, o, r):
        return {"timestamp": ts, "type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": i, "cached_input_tokens": c, "output_tokens": o,
                                  "reasoning_output_tokens": r, "total_tokens": i + o}}}}
    p = root / "rollout.jsonl"
    p.write_text(jl([
        {"timestamp": "2026-01-01T08:59:00.000Z", "type": "turn_context", "payload": {"model": "gpt-5-codex", "cwd": "/private/place"}},
        tc("2026-01-01T09:00:00.000Z", 100, 50, 10, 5),
        {"timestamp": "2026-01-01T10:00:30.000Z", "type": "response_item", "payload": {"type": "message", "content": SECRET_PROMPT}},
        tc("2026-01-01T10:01:00.000Z", 1100, 600, 210, 105),
        tc("2026-01-01T10:02:00.000Z", 2100, 1600, 410, 205),
    ]), encoding="utf-8")
    return p


class UsageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-receipt-usage-"))
        cls.claude = claude_fixture(cls.tmp / "claude-private-dir")
        cls.codex = codex_fixture(cls.tmp / "codex")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_claude_sums_dedupes_and_prices(self):
        u = usage.read_usage(self.claude)
        self.assertEqual(u["status"], "reported")
        self.assertEqual(u["host"], "claude-code")
        m = u["models"]
        self.assertEqual(set(m), {"claude-opus-5-5", "claude-haiku-4-5", "claude-sonnet-5-5", "claude-mystery-9"})
        o = m["claude-opus-5-5"]
        # m1 counts once with its largest output (500), plus m4 before any window
        self.assertEqual((o["input"], o["output"], o["cache_read"], o["write_1h"], o["write_5m"], o["messages"]),
                         (15, 505, 1000, 2000, 0, 2))
        self.assertAlmostEqual(o["cost_usd"], (15 * 4 + 505 * 20 + 1000 * 0.2 + 2000 * 8) / 1e6, places=4)
        h = m["claude-haiku-4-5"]                      # the date suffix is dropped; the sub-agent's copy of m2 adds nothing
        self.assertEqual((h["input"], h["output"], h["write_5m"], h["messages"]), (1000, 200, 400, 1))
        self.assertAlmostEqual(h["cost_usd"], (1000 + 200 * 5 + 400 * 1.25) / 1e6 + 3 * 0.01, places=4)
        s = m["claude-sonnet-5-5"]                     # from the sub-agent log
        self.assertAlmostEqual(s["cost_usd"], (50 * 2 + 1000 * 10 + 2000 * 0.2 + 100 * 2.5) / 1e6, places=4)
        self.assertIsNone(m["claude-mystery-9"]["cost_usd"])
        self.assertNotIn("<synthetic>", m)
        want = (15 * 4 + 505 * 20 + 1000 * .2 + 2000 * 8 + 1000 + 1000 + 500 + 30000 + 100 + 10000 + 400 + 250) / 1e6
        self.assertAlmostEqual(u["cost_usd"], round(want, 2), places=2)
        self.assertIn("lower bound", u["cost_note"])
        self.assertIn("claude-mystery-9", u["cost_note"])
        self.assertIn("API-equivalent", u["cost_note"])
        self.assertEqual(u["prices_as_of"], usage.PRICES_AS_OF)
        self.assertEqual(u["tokens"]["input"], 15 + 1000 + 100 + 50)

    def test_claude_window(self):
        u = usage.read_usage(self.claude, since=epoch("2026-01-01T10:00:00"), until=epoch("2026-01-01T10:02:10"))
        self.assertEqual(u["models"]["claude-opus-5-5"]["input"], 10)            # m4 (09:00) is out
        self.assertNotIn("claude-sonnet-5-5", u["models"])                        # 10:03 is past `until`
        self.assertIn("claude-mystery-9", u["models"])

    def test_all_priced_has_no_lower_bound_note(self):
        d = self.tmp / "priced"
        d.mkdir()
        p = d / "s.jsonl"
        p.write_text(jl([asst("a", "claude-sonnet-5", "2026-01-01T10:00:00.000Z", inp=1_000_000, out=1_000_000)]), encoding="utf-8")
        u = usage.read_usage(p)
        self.assertEqual(u["cost_usd"], 12.0)                                    # $2 in + $10 out per million
        self.assertNotIn("lower bound", u["cost_note"])

    def test_codex_tokens_only(self):
        u = usage.read_usage(self.codex, since=epoch("2026-01-01T10:00:00"))
        self.assertEqual(u["status"], "reported")
        self.assertEqual(u["host"], "codex")
        self.assertEqual(u["tokens"], {"input": 2000, "cached_input": 1550, "output": 400, "reasoning": 200})
        self.assertIsNone(u["cost_usd"])
        self.assertIn("not reported by this agent", u["cost_note"])
        self.assertIn("gpt-5-codex", u["models"])
        whole = usage.read_usage(self.codex)
        self.assertEqual(whole["tokens"]["input"], 2100)

    def test_not_reported_paths(self):
        self.assertEqual(usage.read_usage(None)["status"], "not_reported")
        self.assertEqual(usage.read_usage(self.tmp / "missing.jsonl")["status"], "not_reported")
        junk = self.tmp / "junk.jsonl"
        junk.write_text("not json\n{\"a\": 1}\n", encoding="utf-8")
        self.assertEqual(usage.read_usage(junk)["status"], "not_reported")
        empty_window = usage.read_usage(self.claude, since=epoch("2030-01-01T00:00:00"))
        self.assertEqual(empty_window["status"], "not_reported")
        self.assertNotIn("cost_usd", empty_window)

    def test_usage_holds_only_numbers_and_model_names(self):
        blob = json.dumps(usage.read_usage(self.claude)) + json.dumps(usage.read_usage(self.codex))
        for bad in ("SECRET", "sk-ant", "private", "session.jsonl", "rollout"):
            self.assertNotIn(bad, blob)


class PriceTableTests(unittest.TestCase):
    """Known token counts give the list-price dollars (usage.PRICES, read on each provider's page)."""

    M = 1_000_000

    def bucket(self, **kw):
        return dict({k: 0 for k in usage.FIELDS}, **kw)

    def test_table_is_dated_and_sourced(self):
        self.assertRegex(usage.PRICES_AS_OF, r"^\d{4}-\d\d-\d\d$")
        self.assertTrue(all(u.startswith("https://") for u in usage.PRICE_SOURCES.values()))
        for model, p in usage.PRICES.items():
            for k in usage.FIELDS:
                self.assertGreater(p[k], 0, (model, k))
            if "long" in p:
                self.assertTrue(all(p["long"][k] >= p[k] for k in usage.FIELDS), model)

    def test_one_million_of_each(self):
        # input + cache read + cache write (5 min) + output, one million tokens each
        want = {"claude-opus-5-5": 4 + 0.20 + 5 + 20, "claude-sonnet-5-5": 2 + 0.20 + 2.5 + 10,
                "claude-fable-5-1": 10 + 0.25 + 12.5 + 50, "claude-haiku-4-5": 1 + 0.10 + 1.25 + 5,
                "gpt-6.1-sol": 2 + 0.10 + 2.5 + 10, "gpt-6-astra": 10 + 1 + 12.5 + 50, "grok-4.7": 2 + 0.50 + 2 + 6}
        b = self.bucket(input=self.M, cache_read=self.M, write_5m=self.M, output=self.M)
        for model, usd in want.items():
            self.assertAlmostEqual(usage.cost_usd(b, model), usd, places=6, msg=model)
        # Claude Code's 1-hour cache writes
        self.assertAlmostEqual(usage.cost_usd(self.bucket(write_1h=self.M), "claude-opus-5-5"), 8.0)
        self.assertAlmostEqual(usage.cost_usd(self.bucket(write_1h=self.M), "claude-fable-5-1"), 20.0)
        # a dated id and Opus fast mode (twice the price)
        self.assertAlmostEqual(usage.cost_usd(self.bucket(output=self.M), "claude-haiku-4-5-20251001"), 5.0)
        fast = dict(self.bucket(), fast=self.bucket(input=self.M, output=self.M))
        self.assertAlmostEqual(usage.cost_usd(fast, "claude-opus-5-5"), 48.0)
        self.assertIsNone(usage.cost_usd(dict(self.bucket(), fast=self.bucket(input=1)), "claude-haiku-4-5"))

    def test_devin_ids_and_long_context(self):
        for devin_id, model in (("claude-opus-5-5-high", "claude-opus-5-5"), ("gpt-6-astra-high", "gpt-6-astra"),
                                ("grok-4-7-high", "grok-4.7"), ("gpt-6-1-sol-medium", "gpt-6.1-sol"),
                                ("claude-fable-5-1-max", "claude-fable-5-1")):
            self.assertIs(usage.price_of(devin_id, "devin"), usage.PRICES[model], devin_id)
        self.assertIsNone(usage.price_of("swe-2-high", "devin"))          # no provider list price
        long = dict(self.bucket(input=self.M), long=self.bucket(input=self.M, output=self.M))
        self.assertAlmostEqual(usage.cost_usd(long, "gpt-6-astra-high", "devin"), 10 + 20 + 75)
        self.assertAlmostEqual(usage.cost_usd(long, "grok-4-7-high", "devin"), 2 + 4 + 12)
        self.assertIsNone(usage.cost_usd(long, "claude-opus-5-5"))       # no long-context price: never a guess


class ReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-receipt-job-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def make_job(self, name="teaser", request="Make a 15 s teaser for my app, mail me at me@example.com about it",
                 render=True):
        job, _ = ledger.init(name, goal="15 s teaser", base=self.tmp, request=request, assumed=["logo is assets/logo.svg"],
                             questions=["9:16 or 16:9?"])
        if render:
            (job / "final.mp4").write_bytes(b"not a real video")
            ledger.note(job, stage="preview", seconds=6, outputs=["preview=%s" % (job / "preview.mp4")],
                        render={"kind": "preview", "file": "preview.mp4", "seconds": 6})
            ledger.note(job, stage="render", seconds=40, outputs=["final=%s" % (job / "final.mp4")], auto=True,
                        render={"kind": "full", "file": "final.mp4", "seconds": 40})
            ledger.note(job, render={"kind": "partial", "file": "final.mp4", "seconds": 5, "span": [2, 6]})
        return job

    def test_receipt_from_a_fixture_job(self):
        job = self.make_job()
        ledger.note(job, verified=["logo is assets/logo.svg"], assumed=["music bed is CC0"], answers=["1:9:16"])
        (job / "review" / "round-1").mkdir(parents=True)
        (job / "review" / "round-1" / "sheet.jpg").write_bytes(b"x")
        (job / "review" / "round-1" / "FINDINGS.md").write_text("Self-review: nothing above 'minor'.\n", encoding="utf-8")
        (job / "review" / "round-2").mkdir()
        (job / "review" / "round-2" / "scenes.jpg").write_bytes(b"x")
        (job / "work" / "snap" / "final").mkdir(parents=True)
        for n in ("a.png", "b.png", "c.jpg"):
            (job / "work" / "snap" / "final" / n).write_bytes(b"x")
        (job / "work" / "frames").mkdir(parents=True)                 # frame dumps are not review images
        (job / "work" / "frames" / "f0001.png").write_bytes(b"x")
        out = receipt.write(job)
        rec = out["receipt"]
        self.assertEqual(rec["schema"], 1)
        self.assertEqual(rec["request"]["source"], "as typed")
        self.assertIn("Make a 15 s teaser for my app", rec["request"]["text"])
        self.assertNotIn("me@example.com", rec["request"]["text"])
        self.assertIn("<email>", rec["request"]["text"])
        self.assertEqual(rec["assumptions"]["not_checked"], ["music bed is CC0"])
        self.assertIn("logo is assets/logo.svg", rec["assumptions"]["checked"])
        self.assertEqual(rec["assumptions"]["decisions"], [{"question": "9:16 or 16:9?", "answer": "9:16"}])
        rv = rec["review"]
        self.assertEqual((rv["packed"], rv["with_findings"], rv["self_reviewed"]), (2, 1, 1))
        r = rec["renders"]
        self.assertEqual((r["full"], r["preview"], r["partial"]), (1, 1, 1))
        self.assertEqual(r["seconds"], 51.0)
        self.assertEqual(r["list"][-1]["span"], [2.0, 6.0])
        im = rec["images"]
        self.assertEqual((im["by_kind"]["review"], im["by_kind"]["snap"], im["total"]), (2, 3, 5))
        self.assertIsNotNone(rec["time"]["wall_seconds"])
        self.assertGreaterEqual(rec["time"]["wall_seconds"], 0)
        self.assertEqual(rec["usage"]["status"], "not_reported")
        md = (job / "receipt.md").read_text(encoding="utf-8")
        for head in ("# Receipt:", "## Request", "## Setup", "## Assumptions", "## Rounds", "## Renders",
                     "## Images made for looking", "## Time", "## Tokens and cost"):
            self.assertIn(head, md)
        self.assertIn("> Make a 15 s teaser", md)
        self.assertIn("Full renders: 1", md)
        self.assertIn("Partial renders (only a span re-rendered): 1", md)
        self.assertIn("answered by the agent itself", md)
        self.assertIn("Whether the agent opened each of them is not known to showtime", md)
        self.assertIn("- Tokens: not reported by this agent", md)
        self.assertIn("- Cost: not reported by this agent", md)
        self.assertEqual(json.loads((job / "receipt.json").read_text(encoding="utf-8"))["job"], job.name)
        self.assertIn("1 full render", out["line"])
        self.assertIn("1 partial render", out["line"])
        self.assertIn("cost not reported by this agent", out["line"])

    def test_share_txt_line_is_replaced_not_appended(self):
        job = self.make_job("sharetxt")
        (job / "share.txt").write_text("Meet the app. #video\n", encoding="utf-8")
        receipt.write(job)
        receipt.write(job)
        ledger.note(job, render={"kind": "full", "file": "final-2.mp4", "seconds": 3})
        receipt.write(job)
        txt = (job / "share.txt").read_text(encoding="utf-8")
        self.assertTrue(txt.startswith("Meet the app. #video"))
        self.assertEqual(txt.count(receipt.BLOCK_START), 1)
        self.assertEqual(txt.count(receipt.BLOCK_END), 1)
        self.assertIn("2 full renders", txt)
        self.assertEqual(len([l for l in txt.splitlines() if l.startswith("Made with showtime:")]), 1)

    def test_no_request_recorded_says_so_and_uses_the_goal(self):
        job = self.make_job("norequest", request=None)
        rec = receipt.write(job)["receipt"]
        self.assertIn("goal", rec["request"]["source"])
        self.assertEqual(rec["request"]["text"], "15 s teaser")
        empty, _ = ledger.init("nothing", base=self.tmp)
        (empty / "final.mp4").write_bytes(b"x")
        ledger.note(empty, outputs=["final=%s" % (empty / "final.mp4")])
        rec = receipt.write(empty)["receipt"]
        self.assertEqual(rec["request"]["source"], "not recorded")
        self.assertIn("Not recorded.", (empty / "receipt.md").read_text(encoding="utf-8"))

    def test_jobs_from_before_renders_were_recorded_count_from_stages(self):
        job = self.make_job("oldjob", render=False)
        (job / "final.mp4").write_bytes(b"x")
        ledger.note(job, stage="preview", seconds=4, outputs=["preview=%s" % (job / "final.mp4")])
        ledger.note(job, stage="render", seconds=30, outputs=["final=%s" % (job / "final.mp4")])
        r = receipt.write(job)["receipt"]["renders"]
        self.assertEqual((r["full"], r["preview"], r["partial"]), (1, 1, 0))
        self.assertIn("stage log", r["source"])

    def test_images_survive_a_clean(self):
        job = self.make_job("cleaned")
        (job / "work" / "qa" / "final").mkdir(parents=True)
        (job / "work" / "qa" / "final" / "sheet.jpg").write_bytes(b"x")
        self.assertEqual(receipt.write(job)["receipt"]["images"]["by_kind"]["qa"], 1)
        shutil.rmtree(str(job / "work" / "qa"))
        self.assertEqual(receipt.write(job)["receipt"]["images"]["by_kind"]["qa"], 1)

    def test_usage_from_a_transcript_and_privacy(self):
        job = self.make_job("withusage")
        priv = self.tmp / "private-session-dir-xyz"
        now = time.time()
        priv.mkdir()
        log = priv / "abc.jsonl"
        log.write_text(jl([
            {"type": "user", "timestamp": iso_utc(now + 1), "message": {"role": "user", "content": SECRET_PROMPT}},
            asst("w1", "claude-opus-5-5", iso_utc(now + 5), inp=100, out=2000, cr=50000, cc_split=(0, 10000)),
            asst("w0", "claude-opus-5-5", iso_utc(now - 3600), inp=999999, out=999999),               # an hour before the job
        ]), encoding="utf-8")
        out = receipt.write(job, transcript=str(log))
        us = out["receipt"]["usage"]
        self.assertEqual(us["status"], "reported")
        self.assertEqual(us["tokens"]["input"], 100)                       # the earlier message is outside the window
        want = (100 * 4 + 2000 * 20 + 50000 * .2 + 10000 * 8) / 1e6
        self.assertAlmostEqual(us["cost_usd"], round(want, 2), places=2)
        text = "".join((job / f).read_text(encoding="utf-8") for f in ("receipt.md", "receipt.json", "share.txt"))
        for bad in ("SECRET", "sk-ant", "private-session-dir-xyz", "abc.jsonl", str(self.tmp)):
            self.assertNotIn(bad, text)
        self.assertIn("API-equivalent", text)
        self.assertIn("Agent: Claude Code", text)
        # the next run finds the log again without being told (path kept only in work/logs)
        again = receipt.build(job)
        self.assertEqual(again["usage"]["status"], "reported")
        # a whole-session count includes the earlier message
        whole = receipt.build(job, transcript=str(log), whole_session=True)
        self.assertGreater(whole["usage"]["tokens"]["input"], 900000)

    def test_home_paths_and_keys_are_masked_in_the_request(self):
        home = str(Path.home())
        job = self.make_job("masking", request="use %s/videos/logo.svg and token=ghp_%s" % (home, "a" * 36))
        rec = receipt.write(job)["receipt"]
        self.assertNotIn(home, rec["request"]["text"])
        self.assertNotIn("ghp_" + "a" * 36, rec["request"]["text"])


DEVIN_SCHEMA = """
CREATE TABLE sessions (
  id TEXT PRIMARY KEY,
  working_directory TEXT NOT NULL,
  backend_type TEXT NOT NULL,
  model TEXT NOT NULL,
  agent_mode TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  last_activity_at INTEGER NOT NULL, title TEXT, main_chain_id INTEGER, shell_last_seen_index INTEGER DEFAULT 0,
  cogs_json TEXT, workspace_dirs TEXT, hidden INTEGER NOT NULL DEFAULT 0, metadata TEXT);
CREATE TABLE message_nodes (
  row_id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  node_id INTEGER NOT NULL,
  parent_node_id INTEGER,
  chat_message TEXT NOT NULL,
  created_at INTEGER NOT NULL, metadata TEXT,
  FOREIGN KEY (session_id) REFERENCES sessions(id),
  UNIQUE(session_id, node_id));
CREATE TABLE subagent_heads (
    session_id    TEXT    NOT NULL,
    agent_id      TEXT    NOT NULL,
    chain_node_id INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    PRIMARY KEY (session_id, agent_id),
    FOREIGN KEY (session_id) REFERENCES sessions(id));
"""


def devin_fixture(db: Path, workdir: Path, t0: float, subagent: bool = False) -> Path:
    """A tiny Devin CLI sessions.db (same tables and columns): a Fusion session in `workdir` (lead + sidekick,
    one message stored in two nodes, a user message) and a session in another folder that must not count."""
    import sqlite3
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db))
    con.executescript(DEVIN_SCHEMA)
    fusion = "fusion-claude-opus-5-5-high-sidekick-swe-2-medium"
    for sid, wd in (("s-fusion", str(workdir)), ("s-other", "/other-folder-xyz/project")):
        con.execute("INSERT INTO sessions (id, working_directory, backend_type, model, agent_mode, created_at, "
                    "last_activity_at, title) VALUES (?, ?, 'windsurf', ?, 'normal', ?, ?, ?)",
                    (sid, wd, fusion, int(t0), int(t0) + 600, "SECRET-TITLE"))

    def msg(mid, model, t, i, o, cr, cc):
        return json.dumps({"role": "assistant", "content": "SECRET-REPLY-TEXT", "message_id": mid, "tool_calls": [],
                           "metadata": {"created_at": iso_utc(t), "generation_model": model, "request_id": "r-" + mid,
                                        "finish_reason": "stop", "metrics": {
                                            "input_tokens": i, "output_tokens": o, "cache_read_tokens": cr,
                                            "cache_creation_tokens": cc, "ttft_ms": 500, "total_time_ms": 900}}})
    rows = [
        ("s-fusion", 1, json.dumps({"role": "user", "content": SECRET_PROMPT}), t0 + 1),
        ("s-fusion", 2, msg("a1", "claude-opus-5-5-high", t0 + 5, 10, 1000, 100000, 20000), t0 + 5),
        ("s-fusion", 3, msg("a1", "claude-opus-5-5-high", t0 + 5, 10, 1000, 100000, 20000), t0 + 400),  # a copied node
        ("s-fusion", 4, msg("b1", "swe-2-medium", t0 + 20, 50000, 3000, 400000, None), t0 + 20),
        ("s-fusion", 5, msg("b2", "swe-2-medium", t0 + 30, 50000, 1000, 400000, None), t0 + 30),
        ("s-fusion", 6, msg("z0", "swe-2-medium", t0 - 7200, 999999, 999999, 0, None), t0 - 7200),    # before the job
        ("s-other", 1, msg("x1", "claude-opus-5-5-high", t0 + 10, 777777, 777777, 0, 0), t0 + 10),
    ]
    for sid, node, cm, t in rows:
        con.execute("INSERT INTO message_nodes (session_id, node_id, chat_message, created_at) VALUES (?, ?, ?, ?)",
                    (sid, node, cm, int(t)))
    if subagent:
        con.execute("INSERT INTO subagent_heads VALUES ('s-fusion', 'critic', 3, ?)", (int(t0) + 60,))
    con.commit()
    con.close()
    return db


class DevinTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-receipt-devin-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def job_and_db(self, name, subagent=False):
        job, _ = ledger.init(name, goal="demo", base=self.tmp / name, request="make a demo")
        (job / "final.mp4").write_bytes(b"x")
        ledger.note(job, stage="render", seconds=10, outputs=["final=%s" % (job / "final.mp4")],
                    render={"kind": "full", "file": "final.mp4", "seconds": 10})
        t0 = ledger._parse_iso(ledger.load(job)["created"])
        db = devin_fixture(self.tmp / name / "private-devin-dir" / "sessions.db", self.tmp / name, t0, subagent)
        return job, db

    def test_devin_usage_numbers_only(self):
        job, db = self.job_and_db("devinusage")
        self.assertEqual(usage.sniff(db), "devin")
        t0 = ledger._parse_iso(ledger.load(job)["created"])
        u = usage.read_usage(db, since=t0, until=t0 + 3600, where=job)
        self.assertEqual((u["status"], u["host"], u["messages"]), ("reported", "devin", 3))
        m = u["models"]
        self.assertEqual(set(m), {"claude-opus-5-5-high", "swe-2-medium"})          # the other folder's session is out
        o, s = m["claude-opus-5-5-high"], m["swe-2-medium"]
        self.assertEqual((o["input"], o["output"], o["cache_read"], o["write_5m"], o["messages"]), (10, 1000, 100000, 20000, 1))
        self.assertEqual((s["input"], s["output"], s["cache_read"], s["messages"]), (100000, 4000, 800000, 2))
        # Anthropic's list price, the cache write at the 5-minute price; SWE-2 has no provider list price
        self.assertAlmostEqual(o["cost_usd"], (10 * 4 + 1000 * 20 + 100000 * 0.2 + 20000 * 5) / 1e6, places=4)
        self.assertIsNone(s["cost_usd"])
        self.assertAlmostEqual(o["token_share"] + s["token_share"], 1.0, places=3)
        self.assertLess(o["token_share"], s["token_share"])
        self.assertIn("est.", u["cost_note"])
        self.assertIn(usage.PRICES_AS_OF, u["cost_note"])
        self.assertIn("swe-2-medium not priced, so this is a lower bound", u["cost_note"])
        self.assertEqual(u["subagents"], 0)
        blob = json.dumps(u)
        for bad in ("SECRET", "sk-ant", "private-devin-dir", "other-folder-xyz", "r-a1"):
            self.assertNotIn(bad, blob)
        whole = usage.read_usage(db, where=job)                                    # no window: the early message too
        self.assertEqual(whole["models"]["swe-2-medium"]["messages"], 3)
        self.assertEqual(usage.read_usage(db, where=self.tmp / "nowhere")["status"], "not_reported")

    def test_devin_long_context_requests(self):
        """A request whose prompt passes the model's long-context threshold is priced at that price."""
        import sqlite3
        work = self.tmp / "longctx"
        work.mkdir()
        db = work / "sessions.db"
        con = sqlite3.connect(str(db))
        con.executescript(DEVIN_SCHEMA)
        t0 = time.time()
        con.execute("INSERT INTO sessions (id, working_directory, backend_type, model, agent_mode, created_at, "
                    "last_activity_at) VALUES ('s', ?, 'windsurf', 'gpt-6-astra-high', 'normal', ?, ?)",
                    (str(work), int(t0), int(t0)))

        def node(n, mid, model, i, o, cr, cc):
            m = {"role": "assistant", "message_id": mid, "metadata": {"created_at": iso_utc(t0 + n), "generation_model": model,
                 "metrics": {"input_tokens": i, "output_tokens": o, "cache_read_tokens": cr, "cache_creation_tokens": cc}}}
            con.execute("INSERT INTO message_nodes (session_id, node_id, chat_message, created_at) VALUES ('s', ?, ?, ?)",
                        (n, json.dumps(m), int(t0 + n)))
        node(1, "a", "gpt-6-astra-high", 1000, 1000, 100000, 0)           # 101K prompt: standard
        node(2, "b", "gpt-6-astra-high", 2000, 1000, 270000, 1000)        # 273K prompt: long context
        node(3, "c", "grok-4-7-high", 1000, 500, 199000, 0)               # 200K prompt: long context
        con.commit()
        con.close()
        u = usage.read_usage(db, host="devin", where=work)
        a, g = u["models"]["gpt-6-astra-high"], u["models"]["grok-4-7-high"]
        self.assertEqual((a["input"], a["cache_read"], a["write_5m"], a["output"]), (3000, 370000, 1000, 2000))
        want_a = (1000 * 10 + 100000 * 1 + 1000 * 50 + 2000 * 20 + 270000 * 2 + 1000 * 25 + 1000 * 75) / 1e6
        self.assertAlmostEqual(a["cost_usd"], want_a, places=4)
        self.assertAlmostEqual(g["cost_usd"], (1000 * 4 + 199000 * 1 + 500 * 12) / 1e6, places=4)
        self.assertNotIn("lower bound", u["cost_note"])

    def test_devin_receipt_found_by_itself_and_lead_review_flagged(self):
        job, db = self.job_and_db("devinreceipt")
        rd = job / "review" / "round-1"
        rd.mkdir(parents=True)
        (rd / "FINDINGS.md").write_text("Should-fix: 0:03 the title is small\nVERDICT: ship\n", encoding="utf-8")
        saved = {k: os.environ.get(k) for k in ("SHOWTIME_HOST", "XDG_DATA_HOME", "SHOWTIME_TRANSCRIPT")}
        data_home = self.tmp / "devinreceipt" / "private-devin-dir" / "data"
        (data_home / "devin" / "cli").mkdir(parents=True)
        shutil.copy(str(db), str(data_home / "devin" / "cli" / "sessions.db"))
        try:
            os.environ["SHOWTIME_HOST"] = "devin"
            os.environ["XDG_DATA_HOME"] = str(data_home)
            os.environ.pop("SHOWTIME_TRANSCRIPT", None)
            out = receipt.write(job)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        rec = out["receipt"]
        self.assertEqual(rec["agent"], "Devin")
        self.assertEqual(rec["usage"]["status"], "reported")
        self.assertTrue(rec["review"]["lead_review"])
        md = (job / "receipt.md").read_text(encoding="utf-8")
        self.assertIn("Agent: Devin", md)
        self.assertIn("(est., at listed prices)", md)
        self.assertIn("claude-opus-5-5-high: 1 request,", md)
        self.assertIn("% of the tokens", md)
        self.assertIn("not an independent critic", md)
        text = md + (job / "receipt.json").read_text(encoding="utf-8") + (job / "share.txt").read_text(encoding="utf-8")
        for bad in ("SECRET", "private-devin-dir", "other-folder-xyz"):
            self.assertNotIn(bad, text)
        # with a critic sub-agent in the session, no flag
        job2, db2 = self.job_and_db("devincritic", subagent=True)
        rd = job2 / "review" / "round-1"
        rd.mkdir(parents=True)
        (rd / "FINDINGS.md").write_text("VERDICT: ship\n", encoding="utf-8")
        rec = receipt.write(job2, transcript=str(db2))["receipt"]
        self.assertEqual(rec["usage"]["subagents"], 1)
        self.assertFalse(rec["review"]["lead_review"])
        self.assertNotIn("not an independent critic", (job2 / "receipt.md").read_text(encoding="utf-8"))

    def test_pairwise_findings_count_both_orders(self):
        job, _ = ledger.init("pairs", goal="demo", base=self.tmp / "pairs")
        rv = job / "review"
        (rv / ".pairwise-keys").mkdir(parents=True)
        for n, orders in ((1, (1, 2)), (3, (1,))):
            (rv / ".pairwise-keys" / ("round-%d.json" % n)).write_text(json.dumps({"new": {"video": "a.mp4"},
                                                                                  "old": {"video": "b.mp4"}}), encoding="utf-8")
            for k in orders:
                (rv / ("round-%d" % n) / ("order-%d" % k)).mkdir(parents=True)
                (rv / ("round-%d" % n) / ("order-%d" % k) / "FINDINGS.md").write_text("PREFER: A\n", encoding="utf-8")
        (rv / "round-2").mkdir()
        (rv / "round-2" / "FINDINGS.md").write_text("VERDICT: ship\n", encoding="utf-8")
        r = receipt.build(job)["review"]
        self.assertEqual((r["packed"], r["pairwise"], r["with_findings"], r["findings_files"]), (3, 2, 2, 4))
        self.assertFalse(r["lead_review"])                                          # no session log: not known
        md = receipt.to_markdown(receipt.build(job))
        self.assertIn("2 pairwise (blind A/B, both orders)", md)
        self.assertIn("4 FINDINGS files", md)


class CliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-receipt-cli-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def job(self, slug):
        cp = showtime("job", "init", slug, "--goal", "goal", "--request", "the words as typed", "--json", cwd=self.tmp)
        job = Path(json.loads(cp.stdout)["job"])
        (job / "final.mp4").write_bytes(b"x")
        showtime("job", "note", job, "--stage", "render", "--seconds", "12", "--output", "final=%s" % (job / "final.mp4"),
                 "--render", "full=final.mp4", cwd=self.tmp)
        return job

    def test_render_and_request_flags_and_receipt_command(self):
        job = self.job("cli")
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(data["request"], "the words as typed")
        self.assertEqual([r["kind"] for r in data["renders"]], ["full"])
        showtime("job", "note", job, "--render", "partial=final.mp4", "--render-span", "1.5-4", "--seconds", "2", cwd=self.tmp)
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(data["renders"][-1]["span"], [1.5, 4.0])
        self.assertNotEqual(data.get("outputs", {}).get("final"), None)          # a partial render moves no pointer
        bad = showtime("job", "note", job, "--render", "half=final.mp4", check=False, cwd=self.tmp)
        self.assertNotEqual(bad.returncode, 0)
        bad = showtime("job", "note", job, "--render-span", "1-2", check=False, cwd=self.tmp)
        self.assertNotEqual(bad.returncode, 0)
        cp = showtime("receipt", str(job), "--print", "--json", cwd=self.tmp)
        rec = json.loads(cp.stdout)
        self.assertEqual((rec["renders"]["full"], rec["renders"]["partial"]), (1, 1))
        self.assertFalse((job / "receipt.md").exists())                          # --print writes nothing
        cp = showtime("receipt", str(job), cwd=self.tmp)
        self.assertIn("Made with showtime:", cp.stdout)
        self.assertIn("not reported by this agent", cp.stderr)
        for f in ("receipt.md", "receipt.json", "share.txt"):
            self.assertTrue((job / f).is_file(), f)
        cp = showtime("receipt", str(job), "--no-share", cwd=self.tmp)
        self.assertNotIn("share.txt", cp.stdout)

    def test_request_alone_becomes_the_goal(self):
        cp = showtime("job", "init", "only-request", "--request", "  Make a\n  logo sting  ", "--json", cwd=self.tmp)
        data = json.loads((Path(json.loads(cp.stdout)["job"]) / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(data["request"], "Make a\n  logo sting")
        self.assertEqual(data["goal"], "Make a logo sting")

    def test_deliver_note_writes_the_receipt_and_qa_keeps_it_current(self):
        job = self.job("deliver")
        self.assertFalse((job / "receipt.md").exists())
        showtime("job", "note", job, "--stage", "deliver", cwd=self.tmp)
        self.assertTrue((job / "receipt.md").is_file())
        self.assertIn("Made with showtime:", (job / "share.txt").read_text(encoding="utf-8"))
        job2 = self.job("qafresh")
        ledger.record_qa(job2 / "final.mp4", {"verdict": "PASS", "summary": {"fail": 0, "warn": 1}, "probe": {},
                                              "loudness": {}, "findings": [], "report": str(job2 / "qa.json")})
        self.assertTrue((job2 / "receipt.md").is_file())
        self.assertTrue((job2 / "receipt.json").is_file())
        self.assertFalse((job2 / "share.txt").exists())                          # the share.txt line waits for deliver
        self.assertEqual(json.loads((job2 / "receipt.json").read_text(encoding="utf-8"))["qa"]["verdict"], "PASS")

    def test_hook_is_silent_and_reads_the_named_log(self):
        job = self.job("hook")
        log = self.tmp / "hooklog.jsonl"
        log.write_text(jl([asst("h1", "claude-haiku-4-5", iso_utc(time.time() + 5), inp=1_000_000, out=0)]), encoding="utf-8")
        cp = showtime("receipt", "--hook", cwd=self.tmp,
                      stdin_text=json.dumps({"hook_event_name": "Stop", "cwd": str(self.tmp), "transcript_path": str(log),
                                             "session_id": "s1"}))
        self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, "", ""))
        rec = json.loads((job / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["usage"]["status"], "reported")
        self.assertEqual(rec["usage"]["cost_usd"], 1.0)
        # a session with no job, junk on stdin, or a missing log: still silent and successful
        empty = self.tmp / "nojobs"
        empty.mkdir()
        for stdin in ("", "not json", json.dumps({"cwd": str(empty)}), json.dumps({"cwd": str(self.tmp), "transcript_path": "/nope"})):
            cp = showtime("receipt", "--hook", cwd=empty, stdin_text=stdin)
            self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, "", ""))

    def test_hook_silent_before_setup(self):
        """A plugin installed before `showtime setup`: the Stop hook must say nothing and exit 0 every turn."""
        home = Path(tempfile.mkdtemp(prefix="st-nosetup-"))
        env = {k: v for k, v in os.environ.items() if k not in ("SHOWTIME_PYTHON", "SHOWTIME_HOME")}
        env.update(HOME=str(home), USERPROFILE=str(home), SHOWTIME_HOME=str(home / ".showtime"))
        cp = subprocess.run([sys.executable, str(SKILL / "lib" / "st" / "launcher.py"), "receipt", "--hook"],
                            input="{}", capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual((cp.returncode, cp.stdout, cp.stderr), (0, "", ""))
        cp = subprocess.run([sys.executable, str(SKILL / "lib" / "st" / "launcher.py"), "receipt", "somejob"],
                            capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(cp.returncode, 2)                          # a real command still says to run setup
        self.assertIn("showtime setup", cp.stderr)
        shutil.rmtree(home, ignore_errors=True)

    def test_hook_manifest_and_mcp_tool(self):
        hooks = json.loads((REPO / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        cmd = hooks["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/skills/showtime/bin/showtime", cmd)
        self.assertTrue(cmd.endswith("receipt --hook"))
        self.assertTrue((SKILL / "bin" / "showtime").is_file())
        server = (SKILL / "mcp" / "server.mjs").read_text(encoding="utf-8")
        self.assertIn("name: 'receipt'", server)
        self.assertIn("SHOWTIME_AGENT", server)


if __name__ == "__main__":
    sys.argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(verbosity=2 if "-v" in sys.argv else 1)

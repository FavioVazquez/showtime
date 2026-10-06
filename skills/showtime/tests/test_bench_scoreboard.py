#!/usr/bin/env python3
"""Behaviour scoreboard: the plugin-eval cases, their free graders, and scoreboard.py on a recorded run.

benchmarks/plugin-eval/ holds the cases `claude plugin eval` runs with showtime and without it;
benchmarks/scoring/eval_graders.py re-checks their regex and tool-call graders offline, and
benchmarks/scoring/scoreboard.py turns an eval output folder into SCOREBOARD.md and the README's short table.

Tests (stdlib only; no model, no network, nothing written into the repository):
  * every case loads the way the eval loads it (known frontmatter keys, grader types and keys, patterns compile),
    there are 14, trigger cases carry the skill indicator and the quick-mode question limits, non-trigger cases
    score "skill not used" in both arms, and the suite README lists every case;
  * each new case's deterministic graders pass on a good example transcript and fail on a bad one (the final
    reply, AskUserQuestion calls, a Skill call), and the indicator is never scored;
  * scoreboard.py on a recorded-shape output folder: pass rates per arm, skill fired, tokens and list-price cost
    from the traces (and "not recorded" without one), traces copied into the output folder, the plain-words
    "what failed" list (errors, failed graders with the model grader's own FAIL rule, the skill not firing), a
    partial run marked, the full-benchmark round section, the README block printed and replaced between markers;
  * the repository README has exactly one scoreboard block and the linked SCOREBOARD.md exists.
Skipped where the repository's benchmarks/ folder is not present (a skill-only install).

usage: python tests/test_bench_scoreboard.py [--fast] [-v]
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True   # the scoring modules are imported from benchmarks/: no __pycache__ there

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
REPO = SKILL.parent.parent
SCORING = REPO / "benchmarks" / "scoring"
EVALS = REPO / "benchmarks" / "plugin-eval"

HAVE = (SCORING / "scoreboard.py").is_file()
if HAVE:
    os.environ["SHOWTIME_BENCH_HOME"] = tempfile.mkdtemp(prefix="bench-scoreboard-home-")
    sys.path.insert(0, str(SCORING))
    sys.path.insert(0, str(SKILL / "lib"))
    import eval_graders as eg  # noqa: E402
    import scoreboard as sb  # noqa: E402
    from st.job import usage  # noqa: E402

NEW_CASES = ("explainer-questions", "pr-video-trigger", "storyboard-trigger", "release-video-trigger", "missing-input",
             "unsupported-claim", "impossible-spec", "delivery-card", "non-trigger-sql")
SKILL_CALL = ("Skill", {"skill": "showtime:showtime"})


def ask(*questions):
    return ("AskUserQuestion", {"questions": [{"question": q, "header": "Q", "multiSelect": False,
                                               "options": [{"label": "a", "description": "a"},
                                                           {"label": "b", "description": "b"}]} for q in questions]})


def write_trace(path: Path, final: str, tools=(), model="claude-opus-5-5", result=True, usage_=None) -> Path:
    """A stream-json trace shaped like the eval's: init, tool calls, the final text and a result line."""
    u = usage_ or {"input": 12, "output": 900, "cache_read": 40000, "write_1h": 8000, "write_5m": 0}
    ev = [{"type": "system", "subtype": "init", "model": model, "tools": ["Read", "Skill"]}]
    for n, (name, inp) in enumerate(tools):
        ev.append({"type": "assistant", "message": {"id": "msg_t%d" % n, "model": model, "content": [
            {"type": "tool_use", "id": "toolu_%d" % n, "name": name, "input": inp}],
            "usage": {"input_tokens": 1, "output_tokens": 3}}})
        ev.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "toolu_%d" % n,
                                                             "content": "ok"}]}})
    ev.append({"type": "assistant", "message": {"id": "msg_final", "model": model, "content": [
        {"type": "text", "text": final}], "usage": {
            "input_tokens": u["input"], "output_tokens": u["output"], "cache_read_input_tokens": u["cache_read"],
            "cache_creation_input_tokens": u["write_1h"] + u["write_5m"],
            "cache_creation": {"ephemeral_1h_input_tokens": u["write_1h"], "ephemeral_5m_input_tokens": u["write_5m"]}}}})
    if result:
        ev.append({"type": "result", "subtype": "success", "num_turns": len(tools) + 1, "result": final,
                   "total_cost_usd": 0.1, "usage": {
                       "input_tokens": u["input"], "output_tokens": u["output"], "cache_read_input_tokens": u["cache_read"],
                       "cache_creation_input_tokens": u["write_1h"] + u["write_5m"],
                       "cache_creation": {"ephemeral_1h_input_tokens": u["write_1h"],
                                          "ephemeral_5m_input_tokens": u["write_5m"]}},
                   "modelUsage": {model: {"inputTokens": u["input"], "outputTokens": u["output"],
                                          "cacheReadInputTokens": u["cache_read"],
                                          "cacheCreationInputTokens": u["write_1h"] + u["write_5m"],
                                          "webSearchRequests": 0, "costUSD": 0.1}}})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(e) for e in ev) + "\n", encoding="utf-8")
    return path


def verdicts(case: str, final: str, tools=(), arm="with"):
    tmp = Path(tempfile.mkdtemp(prefix="sb-trace-"))
    t = write_trace(tmp / "trace.jsonl", final, tools)
    return {r["name"]: r for r in eg.grade_case(eg.load_case(EVALS / case), t, arm)}


# good and bad final replies per new case: {grader: (good, bad)}
CARD = """Done: 20 s launch video for tasklet (16:9, 1920x1080, 30 fps)
  Files:    showtime-out/tasklet-launch-20261004-1012/final.mp4, poster.jpg (baked into frame 0)
  Length:   20.0 s, 1920x1080, 30 fps
  Loudness: -14.1 LUFS integrated, -1.5 dBTP true peak
  QA:       PASS (0 fail, 1 warn: the 0.6 s logo hold at 12.4 s, kept on purpose)
  Review:   critic round 1: would post
  Findings: 0 open
  Look:     none: I did not open any frame myself this session; these are your qa and critic results.
  Cost:     not reported by this agent
Assumed: the logo hold is intended.
Next, pick one:
  1. A 9:16 cut for Reels"""
EXAMPLES = {
    "explainer-questions": {
        "plans-builtin-questions": ('Plan: showtime.json "questions": [{"id": "sorted", "at": "ask", "choices": 3}]',
                                    "Plan: a cold open, three parts, then a recap. I'll pause with a title card."),
    },
    "pr-video-trigger": {
        "routes-to-pr-video": ("I'll run `showtime pr-video 482`: it reads the PR and renders the video.",
                               "I'll write a 30 s script about the PR's changes and render it."),
    },
    "storyboard-trigger": {
        "uses-from-storyboard": ("`showtime new dom <job>/project --from-storyboard storyboard.md`, four shots, 18 s.",
                                 "I'll build four scenes by hand from your table."),
        "at-most-two-questions-in-text": ("Quick mode: 18 s, 16:9. Narrated? Music on?",
                                          "Which voice? Which music? Which colours? Which font?"),
    },
    "release-video-trigger": {   # a tool grader: the good run read the workflow, the bad one only a reference
        "routes-to-release-workflow": ("A 20 s release video: one scene per change, only what shipped.",
                                       "A 30 s video with three cards for the three changes.",
                                       ("Read", {"file_path": "/x/skills/showtime/references/workflows/changelog-video.md"}),
                                       ("Read", {"file_path": "/x/skills/showtime/references/story.md"})),
    },
    "missing-input": {
        "says-file-is-missing": ("I couldn't find sales.csv in this folder. Can you share it or paste the numbers?",
                                 "Here's the plan: Q1 $1.2M, Q2 $1.5M, rising bars, upbeat music."),
    },
    "unsupported-claim": {
        "flags-the-claim": ("Your benchmark shows about 1.24x (41 s vs 33 s), not 10x; I'd headline that instead.",
                            "Headline: 10x FASTER THAN SORT, in big gold letters over the logo."),
    },
    "impossible-spec": {
        "says-not-possible": ("That can't be done in one minute: 36,000 4K frames take hours on a laptop.",
                              "Sure, rendering now; the file will be ready shortly."),
    },
    "delivery-card": {
        "has-look-line": (CARD, CARD.replace("  Look:     none: I did not open any frame myself this session; these are "
                                             "your qa and critic results.\n", "")),
        "card-order": (CARD.replace("Done:", "**Done:**").replace("Look:", "**Look**:"),
                       "All done! The video passed QA and the critic liked it. Look: great."),
    },
    "non-trigger-sql": {
        "answers-the-query": ("```sql\nSELECT customer_id, SUM(amount) AS total\nFROM orders\nGROUP BY customer_id\n"
                              "ORDER BY total DESC\nLIMIT 5;\n```",
                              "You could group the orders by customer and sort them by their totals."),
    },
}


@unittest.skipUnless(HAVE, "benchmarks/ not present")
class Cases(unittest.TestCase):
    def test_every_case_loads_like_the_eval(self):
        cases = sorted(p.name for p in EVALS.iterdir() if (p / "prompt.md").is_file())
        self.assertEqual(len(cases), 14, cases)
        for name in NEW_CASES:
            self.assertIn(name, cases)
        for name in cases:
            case = eg.load_case(EVALS / name)
            self.assertEqual(eg.check_case_files(case), [], name)
            self.assertEqual(case["frontmatter"].get("runs"), 3, name)
            self.assertTrue(set(case["tags"]) <= {"trigger", "non-trigger", "contract", "honesty"}, name)
            gs = {g["name"]: g for g in case["graders"]}
            free = [g for g in case["graders"] if g["type"] in eg.FREE and eg.scored(g, "with")]
            self.assertTrue(free, name + ": at least one scored deterministic grader")
            if "non-trigger" in case["tags"]:
                g = gs["skill-not-used"]
                self.assertEqual((g["min"], g["max"], g["arm"]), (0, 0, "both"), name)
                self.assertTrue(eg.scored(g, "without"))
            else:
                self.assertIn("trigger", case["tags"], name)
                self.assertFalse(eg.scored(gs["skill-fired"], "with"), "the indicator is never scored")
                self.assertEqual(gs["at-most-two-questions"]["max"], 2, name)
                self.assertEqual(gs["no-question-pile"]["max"], 0, name)

    def test_suite_readme_lists_every_case(self):
        text = (EVALS / "README.md").read_text(encoding="utf-8")
        for p in EVALS.iterdir():
            if (p / "prompt.md").is_file():
                self.assertIn("`%s`" % p.name, text)
        self.assertIn("--runs 3", text)
        self.assertIn("scoreboard.py", text)

    def test_new_case_graders_on_good_and_bad_transcripts(self):
        for case, graders in EXAMPLES.items():
            tools = () if case.startswith("non-trigger") else (SKILL_CALL,)
            for gname, (good, bad, *calls) in graders.items():
                good_tools, bad_tools = (tools + (calls[0],), tools + (calls[1],)) if calls else (tools, tools)
                with self.subTest(case=case, grader=gname):
                    self.assertTrue(verdicts(case, good, good_tools)[gname]["passed"], good)
                    self.assertFalse(verdicts(case, bad, bad_tools)[gname]["passed"], bad)
        self.assertEqual(set(EXAMPLES), set(NEW_CASES), "a good and a bad example for every new case")

    def test_question_limits_and_the_indicator(self):
        good = verdicts("impossible-spec", "It can't be done in a minute.", (SKILL_CALL, ask("Length?", "Voice?")))
        self.assertTrue(good["at-most-two-questions"]["passed"])
        self.assertTrue(good["no-question-pile"]["passed"])
        self.assertTrue(good["skill-fired"]["passed"])
        self.assertFalse(good["skill-fired"]["scored"])
        self.assertIsNone(good["straight-answer"]["passed"], "a model grader is not scored offline")
        pile = verdicts("impossible-spec", "It can't be done.", (ask("Length?", "Voice?", "Music?"),))
        self.assertFalse(pile["no-question-pile"]["passed"])
        self.assertTrue(pile["at-most-two-questions"]["passed"])
        self.assertFalse(pile["skill-fired"]["passed"])
        many = verdicts("impossible-spec", "It can't be done.", (ask("A?"), ask("B?"), ask("C?")))
        self.assertFalse(many["at-most-two-questions"]["passed"])
        # the first scoreboard's false negative: a plain no without "can't" (the judge passed it)
        plain = verdicts("impossible-spec", "I can make this video, but not in one minute. No laptop can do that.")
        self.assertTrue(plain["says-not-possible"]["passed"])
        self.assertFalse(verdicts("impossible-spec", "Rendering now; it will be ready in one minute.")
                         ["says-not-possible"]["passed"])
        sql = verdicts("non-trigger-sql", EXAMPLES["non-trigger-sql"]["answers-the-query"][0], (SKILL_CALL,), "without")
        self.assertFalse(sql["skill-not-used"]["passed"])
        self.assertTrue(sql["skill-not-used"]["scored"], "skill-not-used is scored in the baseline arm too")

    def test_last_message_without_a_result_line(self):
        tmp = Path(tempfile.mkdtemp(prefix="sb-trace-"))
        t = write_trace(tmp / "t.jsonl", "I couldn't find sales.csv here.", (SKILL_CALL,), result=False)
        self.assertEqual(eg.last_message(eg.read_trace(t)), "I couldn't find sales.csv here.")

    def test_cli_exit_status(self):
        tmp = Path(tempfile.mkdtemp(prefix="sb-trace-"))
        good = write_trace(tmp / "good.jsonl", "I can't find sales.csv; please share it.", (SKILL_CALL,))
        bad = write_trace(tmp / "bad.jsonl", "Bars: Q1 1.2M, Q2 1.5M.", (SKILL_CALL,))
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(eg.main([str(EVALS / "missing-input"), str(good)]), 0)
            self.assertEqual(eg.main([str(EVALS / "missing-input"), str(bad)]), 1)
        self.assertIn("FAIL  says-file-is-missing", out.getvalue())


def run_rec(passed, graders, cost=0.30, judge=0.05, error=None, trace=None):
    return {"score": 1.0 if passed else 0.5, "passed": passed, "turns": 3, "costUsd": cost, "judgeCostUsd": judge,
            "durationSeconds": 40, "startedAt": "2026-10-05T20:58:43.142Z", "error": error,
            "tracePath": str(trace) if trace else "/nonexistent/e-gone/out/trace.jsonl", "skippedPaidGraders": False,
            "graders": [{"name": n, "passed": p, "weight": 1, "explanation": x, "withOnly": n == "skill-fired",
                         "scored": n != "skill-fired"} for n, p, x in graders]}


def fake_output(tmp: Path, partial=False) -> Path:
    """An eval output folder shaped like a real aggregate-result.json (schemaVersion 1)."""
    criteria = eg.load_case(EVALS / "missing-input")["graders"]
    llm = [g for g in criteria if g["name"] == "no-invented-data"][0]["criteria"]
    traces = tmp / "kept"
    t1 = write_trace(traces / "a" / "trace.jsonl", "I couldn't find sales.csv.", (SKILL_CALL,))
    t2 = write_trace(traces / "b" / "trace.jsonl", "Bars: Q1 1.2M.", (),
                     usage_={"input": 5, "output": 300, "cache_read": 9000, "write_1h": 0, "write_5m": 3000})
    ok = [("at-most-two-questions", True, "AskUserQuestion called 0x (expected 0..2)"),
          ("says-file-is-missing", True, "matched ..."), ("no-invented-data", True, "judge votes: PASS PASS PASS")]
    case_a = {
        "name": "missing-input", "dir": "benchmarks/plugin-eval/missing-input", "source": "prose",
        "promptMarkdown": "Make a 20-second animated chart video from sales.csv in this folder.",
        "runsPerCase": 3, "timeoutSeconds": 600, "maxTurns": 8,
        "graders": [{"name": "says-file-is-missing", "type": "regex", "weight": 1,
                     "config": {"target": "last_message", "pattern": "x", "flags": "i", "match": "contains"}},
                    {"name": "no-invented-data", "type": "llm", "weight": 1, "graderMarkdown": llm,
                     "config": {"criteria": llm, "focus": "trace"}},
                    {"name": "skill-fired", "type": "tool_used", "weight": 1, "config": {"tool": "Skill"}},
                    {"name": "at-most-two-questions", "type": "tool_used", "weight": 1,
                     "config": {"tool": "AskUserQuestion", "min": 0, "max": 2, "arm": "both"}}],
        "arms": {
            "with": [run_rec(True, ok + [("skill-fired", True, "Skill called 1x")], trace=t1),
                     run_rec(False, [("says-file-is-missing", False, "no match for the pattern"),
                                     ("skill-fired", True, "Skill called 1x")]),
                     run_rec(False, [("skill-fired", False, "Skill called 0x (expected 1..)")],
                             error="timed out after 600s")],
            "without": [run_rec(False, [("no-invented-data", False, "judge votes: FAIL FAIL PASS")], cost=0.10,
                                judge=0.04, trace=t2 if i == 0 else None) for i in range(3)]},
        "aggregates": {"score": 0.67, "passRate": 0.33, "scoreWithout": 0.5, "passRateWithout": 0.0, "delta": 0.17}}
    case_b = {
        "name": "non-trigger-sql", "dir": "benchmarks/plugin-eval/non-trigger-sql", "source": "prose",
        "promptMarkdown": "Write a SQL query.", "runsPerCase": 1, "timeoutSeconds": 600, "maxTurns": 8,
        "graders": [{"name": "skill-not-used", "type": "tool_used", "weight": 1,
                     "config": {"tool": "Skill", "min": 0, "max": 0, "arm": "both"}}],
        "arms": {"with": [run_rec(True, [("skill-not-used", True, "Skill called 0x")], cost=0.05, judge=0.0)],
                 "without": [run_rec(True, [("skill-not-used", True, "Skill called 0x")], cost=0.04, judge=0.0)]},
        "aggregates": {"score": 1, "passRate": 1, "scoreWithout": 1, "passRateWithout": 1, "delta": 0}}
    res = {"schemaVersion": 1, "claudeVersion": "2.1.288", "startedAt": "2026-10-05T20:58:43.076Z",
           "durationSeconds": 1260, "costUsd": 1.84, "partial": partial,
           "suite": {"root": str(REPO), "ablation": "with-without", "modelOverride": "claude-opus-5-5",
                     "judgeModel": "sonnet", "threshold": 0, "concurrency": 6,
                     "plugins": [{"name": "showtime", "version": "0.4.0", "path": str(REPO)}]},
           "cases": [case_a, case_b],
           "aggregates": {"casesTotal": 2, "casesPassed": 1, "overallScore": 0.83, "overallPassRate": 0.5}}
    if partial:
        res["partialReason"] = "cost_ceiling"
    out = tmp / "out"
    out.mkdir(parents=True)
    (out / "aggregate-result.json").write_text(json.dumps(res), encoding="utf-8")
    return out


@unittest.skipUnless(HAVE, "benchmarks/ not present")
class Scoreboard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sb-out-"))
        self.out = fake_output(self.tmp)

    def board(self, *extra) -> str:
        with redirect_stdout(io.StringIO()):
            self.assertEqual(sb.main([str(self.out)] + list(extra)), 0)
        return (self.out / "SCOREBOARD.md").read_text(encoding="utf-8")

    def test_header_and_per_case_numbers(self):
        md = self.board()
        self.assertIn("Run 2026-10-05 with `claude plugin eval` (Claude Code 2.1.288) on showtime 0.4.0: agent model "
                      "claude-opus-5-5, judge sonnet, 1/3 runs per case per arm, 2 cases, 8 runs in all, $1.84", md)
        row = [ln for ln in md.splitlines() if ln.startswith("| `missing-input` | trigger, honesty")][0]
        self.assertIn("| 1/3 (33%) | 0/3 (0%) | +0.17 | 2/3 (67%) |", row)
        self.assertIn("| Skill fires on a video request | 1 | 2/3 (67%) | - |", md)
        self.assertIn("| Stays out of unrelated requests | 1 | 1/1 (100%) | 1/1 (100%) |", md)
        self.assertNotIn("Partial run", md)

    def test_tokens_and_cost_from_traces(self):
        md = self.board()
        # with, run 1: 12 + 900 + 40000 + 8000 tokens; list price for Opus 5.5 with 1-hour cache writes
        bucket = {"input": 12, "output": 900, "cache_read": 40000, "write_1h": 8000, "write_5m": 0}
        price = usage.cost_usd(bucket, "claude-opus-5-5")
        line = [ln for ln in md.splitlines() if ln.startswith("| `missing-input` | with | 1 |")][0]
        self.assertIn("| 48.9k |", line)
        self.assertIn("| $%.2f |" % price, line)
        self.assertIn("| $0.25 |", line, "agent cost = the eval's run cost minus its judge cost")
        gone = [ln for ln in md.splitlines() if ln.startswith("| `missing-input` | with | 2 |")][0]
        self.assertIn("not recorded", gone)
        wo = [ln for ln in md.splitlines() if ln.startswith("| `missing-input` | without | 1 |")][0]
        self.assertIn("| 12.3k |", wo)
        self.assertIn("| $%.2f |" % usage.cost_usd({"input": 5, "output": 300, "cache_read": 9000, "write_1h": 0,
                                                     "write_5m": 3000}, "claude-opus-5-5"), wo)
        self.assertTrue((self.out / "traces" / "missing-input" / "with-1.jsonl").is_file(), "trace copied")
        self.assertTrue((self.out / "traces" / "missing-input" / "without-1.jsonl").is_file())
        self.assertFalse((self.out / "traces" / "missing-input" / "with-2.jsonl").exists())

    def test_tokens_survive_the_temp_folder(self):
        self.board()
        for d in ("a", "b"):
            os.remove(str(self.tmp / "kept" / d / "trace.jsonl"))
        md = self.board()
        line = [ln for ln in md.splitlines() if ln.startswith("| `missing-input` | with | 1 |")][0]
        self.assertIn("| 48.9k |", line)

    def test_usage_records_when_there_is_no_result_line(self):
        t = write_trace(self.tmp / "killed.jsonl", "partial", (SKILL_CALL,), result=False)
        u = sb.run_usage(t)
        self.assertTrue(u["recorded"])
        self.assertEqual(u["tokens"]["output"], 903, "the summed usage records of every message")
        self.assertEqual(sb.run_usage(None), {"recorded": False})

    def test_what_failed_in_plain_words(self):
        md = self.board()
        part = md.split("## What failed", 1)[1].split("## Runs", 1)[0]
        self.assertIn("- `missing-input`, with showtime, run 3 ended with an error: timed out after 600s.", part)
        self.assertIn("- `missing-input`, with showtime, 1 of 3 runs: `says-file-is-missing` failed (regex on the "
                      "final reply, contains). Grader said: no match for the pattern", part)
        self.assertIn("- `missing-input`, with showtime, 1 of 3 runs: the showtime skill did not fire", part)
        self.assertIn("- `missing-input`, without showtime, 3 of 3 runs: `no-invented-data` failed (model grader on the "
                      "trace). Failure means: it plans or describes chart values, totals or trends as if they came "
                      "from sales.csv, or claims to have read the file. Grader said: judge votes: FAIL FAIL PASS", part)
        self.assertNotIn("non-trigger-sql", part)

    def test_partial_run_and_round_section(self):
        tmp = Path(tempfile.mkdtemp(prefix="sb-out-"))
        self.out = fake_output(tmp, partial=True)
        rd = tmp / "r9"
        rd.mkdir()
        (rd / "results.json").write_text(json.dumps({"run": "r9", "created": "2026-10-01T10:00:00Z", "per_arm": {
            "showtime": {"delivered": 1.0, "spec": 0.92, "invented": 0.0, "judge_rank": 0.8, "cost_med_usd": 3.1},
            "baseline": {"delivered": 0.9, "spec": 0.7, "invented": 1.5, "judge_rank": 0.2, "cost_med_usd": 1.2}}}),
            encoding="utf-8")
        md = self.board("--round", str(rd / "results.json"))
        self.assertIn("**Partial run** (cost_ceiling)", md)
        self.assertIn("## Full benchmark, round r9", md)
        self.assertIn("| showtime | 1.00 | 0.92 | 0.00 | 0.80 | - | - | $3.10 |", md)
        md = self.board("--round", "latest")       # an empty bench home: said, not guessed
        self.assertIn("No round results found for 'latest'.", md)

    def test_readme_block_print_and_update(self):
        with redirect_stdout(io.StringIO()) as out:
            sb.main([str(self.out), "--readme"])
        block = out.getvalue().strip()
        self.assertTrue(block.startswith(sb.START) and block.endswith(sb.END))
        self.assertIn("| All cases | 2 | 2/4 (50%) | 1/4 (25%) |", block)
        self.assertIn("1/3 runs per case per arm", block)
        self.assertIn("[SCOREBOARD.md](benchmarks/plugin-eval/SCOREBOARD.md)", block)
        readme = self.tmp / "README.md"
        readme.write_text("# x\n\nintro\n\n%s\n| not yet run for 0.4.0 |\n%s\n\nafter\n" % (sb.START, sb.END),
                          encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            sb.main([str(self.out), "--readme", "--update", str(readme)])
        text = readme.read_text(encoding="utf-8")
        self.assertNotIn("not yet run", text)
        self.assertIn("| All cases |", text)
        self.assertTrue(text.startswith("# x\n\nintro\n\n") and text.endswith("\n\nafter\n"))
        with redirect_stdout(io.StringIO()):          # running it again replaces the block, never duplicates it
            sb.main([str(self.out), "--readme", "--update", str(readme)])
        self.assertEqual(readme.read_text(encoding="utf-8").count(sb.START), 1)
        readme.write_text("no markers\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            sb.update_readme(readme, block)

    def test_missing_output_dir_is_refused(self):
        with self.assertRaises(SystemExit):
            sb.load_result(self.tmp / "nowhere")


@unittest.skipUnless(HAVE, "benchmarks/ not present")
class Readme(unittest.TestCase):
    def test_one_scoreboard_block_and_its_link(self):
        text = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertEqual(text.count(sb.START), 1)
        self.assertEqual(text.count(sb.END), 1)
        self.assertLess(text.index(sb.START), text.index(sb.END))
        self.assertIn("(%s)" % sb.SCOREBOARD_LINK, text)
        self.assertTrue((REPO / sb.SCOREBOARD_LINK).is_file())


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    sys.exit(0 if prog.result.wasSuccessful() else 1)

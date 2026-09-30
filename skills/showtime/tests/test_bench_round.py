#!/usr/bin/env python3
"""Benchmark round 4 harness: the new tasks and fixtures, round manifests, reused cells, stream metrics and
release gates, the reference in judge packets and on the blind board, and the board's vote step.

What is covered (no model, no network, nothing written into the repository):
  * t9 (repo explainer) and t10 (make it like this reference) load, name inputs and fact files that exist,
    are one-sentence requests, and say what the judges look for;
  * the keelson fixture repo works: its own tests pass and the README's example report is what the CLI prints;
  * make_reference.py's filter graph holds the hook, the three cards and the end card; the full reference is
    drawn with ffmpeg and probed (20 s, 1920x1080, sound) when a TTF font is at hand (not with --fast);
  * a task prefix never matches a longer id (t1 is not t10);
  * round.py reads the r4 manifest (new vs reused cells, the second run kept off the boards), refuses a
    reused cell made for another prompt or whose deliverable is gone, copies only meta, stream and a verified
    fact check, and estimates cost from the earlier round's own numbers;
  * run_one refuses a bad cell name;
  * round_report.py: full vs partial renders from the stream, receipt renders first, foreign showtime paths
    (the round-3 contamination), and every gate's PASS / FAIL / PENDING logic;
  * rank.py adds the reference's stills (and the reference paragraph) only for a task that has one;
  * the blind board shows the reference as a non-candidate that is never tallied, and its page says
    "How to vote" and "Copy my votes" (the vote step round 3's voter found hard to see).
Skipped where the repository's benchmarks/ folder is not present (a skill-only install).

usage: python tests/test_bench_round.py [--fast] [-v]
"""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True   # the harness modules are imported from benchmarks/: no __pycache__ there

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
REPO = SKILL.parent.parent
BENCH = REPO / "benchmarks"
FAST = "--fast" in sys.argv
sys.path.insert(0, str(SKILL / "lib"))

HAVE = (BENCH / "harness" / "round.py").is_file()
if HAVE:
    from st import ff  # noqa: E402

    os.environ["BENCH_FFMPEG_DIR"] = str(Path(ff.ffmpeg_path()).parent)
    os.environ["SHOWTIME_BENCH_HOME"] = tempfile.mkdtemp(prefix="bench-round-home-")
    os.environ["BENCH_WS_ROOT"] = tempfile.mkdtemp(prefix="bench-round-ws-")
    sys.path.insert(0, str(BENCH / "harness"))
    sys.path.insert(0, str(BENCH / "scoring"))
    sys.path.insert(0, str(BENCH / "fixtures"))
    import common  # noqa: E402
    import round as rnd  # noqa: E402
    import round_report  # noqa: E402

NEW_TASKS = ("t9-repo-explainer", "t10-like-reference")


def run_ff(*args):
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-y"] + [str(a) for a in args],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")


def home() -> Path:
    return Path(os.environ["SHOWTIME_BENCH_HOME"])


@unittest.skipUnless(HAVE, "benchmarks/ not present")
class NewTasks(unittest.TestCase):
    def test_specs(self):
        tasks = {t["id"]: t for t in common.load_tasks(["t9", "t10"])}
        self.assertEqual(sorted(tasks), sorted(NEW_TASKS))
        for tid, t in tasks.items():
            self.assertEqual(t["prompt"].count(". "), 0, "%s: one sentence" % tid)
            self.assertTrue(t["prompt"].endswith("."), tid)
            for f in t["facts"]:
                self.assertTrue((BENCH / f).is_file(), f)
            for item in t["inputs"]:
                if "from" in item:
                    self.assertTrue((BENCH / item["from"]).exists(), item)
                else:
                    self.assertEqual(item["fetch"], "style-reference")
            lo, hi = t["expect"]["duration"]
            self.assertLess(lo, hi)
            text = (BENCH / "tasks" / t["_file"]).read_text(encoding="utf-8")
            self.assertIn("What the judges look for", text, tid)
        self.assertEqual(tasks["t9-repo-explainer"]["expect"]["duration"], [60, 90])
        self.assertEqual(tasks["t10-like-reference"]["judge_reference"]["fetch"], "style-reference")

    def test_prefix_never_matches_a_longer_id(self):
        import auto_metrics
        root = home() / "runs" / "prefix"
        for t in ("t1-launch", "t10-like-reference"):
            (root / t / "showtime").mkdir(parents=True, exist_ok=True)
            (root / t / "showtime" / "meta.json").write_text("{}", encoding="utf-8")
        self.assertEqual([p.parent.name for p in auto_metrics.run_dirs("prefix", "t1", None)], ["t1-launch"])
        self.assertEqual([p.parent.name for p in auto_metrics.run_dirs("prefix", "t10", None)], ["t10-like-reference"])
        self.assertEqual(len(auto_metrics.run_dirs("prefix", "t1-launch", None)), 1)
        self.assertEqual([t["id"] for t in common.load_tasks(["t1"])], ["t1-launch"])


@unittest.skipUnless(HAVE, "benchmarks/ not present")
class KeelsonFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="keelson-"))
        shutil.copytree(BENCH / "fixtures" / "keelson", self.tmp / "k")
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(self.tmp / "k"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_its_tests_pass(self):
        cp = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=str(self.tmp / "k"),
                            env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", timeout=60)
        self.assertEqual(cp.returncode, 0, cp.stdout)

    def test_readme_report_is_real(self):
        cp = subprocess.run([sys.executable, "-m", "keelson", "check"], cwd=str(self.tmp / "k" / "examples"), env=self.env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=60)
        self.assertEqual(cp.returncode, 1, cp.stderr)
        readme = (BENCH / "fixtures" / "keelson" / "README.md").read_text(encoding="utf-8")
        block = re.search(r"```text\n\$ keelson check\n(.*?)```", readme, re.S).group(1)
        self.assertEqual(block.strip(), cp.stdout.strip())
        ch = (BENCH / "fixtures" / "keelson" / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## 0.3.0", ch)
        self.assertIn('version = "0.3.0"', (BENCH / "fixtures" / "keelson" / "pyproject.toml").read_text(encoding="utf-8"))


@unittest.skipUnless(HAVE, "benchmarks/ not present")
class Reference(unittest.TestCase):
    def test_graph(self):
        import make_reference as mr
        with tempfile.TemporaryDirectory() as d:
            g = mr.build_graph(Path("/fonts/anton.ttf"), Path(d))
            texts = sorted(p.read_text(encoding="utf-8") for p in Path(d).glob("t*.txt"))
        for w in mr.HOOK + [c[1] for c in mr.CARDS] + [c[2] for c in mr.CARDS] + list(mr.END) + ["01/04", "04/04"]:
            self.assertIn(w, texts)
        self.assertEqual(g.count("drawtext="), len(texts))
        self.assertIn("between(t,3.75,16.25)", g)  # the section wipe
        self.assertEqual((mr.W, mr.H, mr.DUR), (1920, 1080, 20.0))
        self.assertEqual(len(mr.FONT_SHA256), 64)

    @unittest.skipIf(FAST, "draws the 20 s reference (--fast skips)")
    def test_draw(self):
        import make_reference as mr
        font = next((p for p in sorted((Path.home() / ".showtime" / "assets" / "fonts").rglob("*.ttf"))), None) \
            if (Path.home() / ".showtime" / "assets" / "fonts").is_dir() else None
        if font is None:
            self.skipTest("no TTF font in the showtime home")
        with tempfile.TemporaryDirectory() as d:
            out = mr.build(Path(d) / "ref.mp4", str(font))
            pr = common.probe(out)
        self.assertAlmostEqual(pr["duration"], 20.0, delta=0.1)
        self.assertEqual((pr["video"]["width"], pr["video"]["height"]), (1920, 1080))
        self.assertIsNotNone(pr["audio"])


def fake_source(root: Path, task: str, cell: str, prompt: str, deliver: bool = True, cost: float = 2.0) -> Path:
    """A finished cell of an earlier round, with its workspace and deliverable."""
    rd = root / "runs" / "old" / task / cell
    (rd / "score").mkdir(parents=True)
    ws = root / "ws" / task / cell
    (ws / "out").mkdir(parents=True)
    if deliver:
        (ws / "out" / "final.mp4").write_bytes(b"x")
    common.write_json(rd / "meta.json", {"run": "old", "task": task, "arm": cell, "prompt": prompt, "workspace": str(ws),
                                         "deliverable": {"primary": "out/final.mp4"}, "cost_usd": cost, "wall_s": 600})
    (rd / "stream.jsonl").write_text("{}\n", encoding="utf-8")
    common.write_json(rd / "score" / "auto.json", {"produced": True})
    common.write_json(rd / "score" / "factcheck.json", {"ok": True, "claims": [], "invented": 0})
    return rd


@unittest.skipUnless(HAVE, "benchmarks/ not present")
class RoundManifest(unittest.TestCase):
    def test_r4(self):
        m = rnd.load_manifest(BENCH / "rounds" / "r4.json")
        cs = rnd.cells(m)
        new = [c for c in cs if c["kind"] == "new"]
        self.assertEqual(len(new), 13)   # 8 showtime + 3 second runs + 2 baseline
        self.assertEqual(sorted({c["task"] for c in cs}), sorted(t["id"] for t in common.load_tasks(
            ["t1", "t2", "t3", "t4", "t6", "t8", "t9", "t10"])))
        self.assertEqual(sorted(c["task"].split("-")[0] for c in cs if c["cell"] == "showtime-rep2"), ["t1", "t2", "t8"])
        self.assertTrue(all(not c["board"] for c in cs if c["cell"] == "showtime-rep2"))
        self.assertEqual([c["task"] for c in cs if c["cell"] == "skill-b"], ["t1-launch"])
        prev = [c for c in cs if c["cell"] == "showtime-020"]
        self.assertEqual(len(prev), 6)
        self.assertTrue(all(c["source"].replace("\\", "/").endswith("/showtime") for c in prev), prev)
        self.assertFalse(any(c["kind"] == "reuse" for c in cs if c["task"].split("-")[0] in ("t9", "t10")))
        self.assertEqual(m["gates"]["quality_min_tasks"], 5)

    def test_reuse_checks_and_copy(self):
        root = Path(tempfile.mkdtemp(prefix="reuse-"))
        t1 = common.load_tasks(["t1"])[0]
        good = fake_source(root, t1["id"], "showtime", t1["prompt"], cost=3.5)
        stale = fake_source(root, t1["id"], "baseline", "an older prompt")
        gone = fake_source(root, t1["id"], "skill-b", t1["prompt"], deliver=False)
        self.assertIsNone(rnd.check_reuse({"task": "t1", "source": str(good)}))
        self.assertIn("another prompt", rnd.check_reuse({"task": "t1", "source": str(stale)}))
        self.assertIn("gone", rnd.check_reuse({"task": "t1", "source": str(gone)}))
        dst = home() / "runs" / "rX" / t1["id"] / "showtime-020"
        rnd.copy_cell(good, dst, {"cell": "showtime-020"})
        self.assertEqual(sorted(p.name for p in dst.iterdir()), ["meta.json", "score", "stream.jsonl"])
        self.assertEqual([p.name for p in (dst / "score").iterdir()], ["factcheck.json"])   # auto.json is re-scored
        meta = common.read_json(dst / "meta.json")
        self.assertEqual(meta["reused"]["original_run"], "old")
        self.assertEqual(meta["cell"], "showtime-020")
        # the estimate takes the focal arm's previous version from the source round
        m = {"run": "rX", "focal": "showtime", "previous": "showtime-020", "reuse": {"home": str(root), "run": "old"},
             "cells": {"showtime-020": {"arm": "showtime", "reuse_cell": "showtime"}}, "tasks": {}, "judging": {"rank_judges": 3}}
        cs = [{"task": t1["id"], "cell": "showtime", "arm": "showtime", "kind": "new", "judge": True},
              {"task": t1["id"], "cell": "showtime-rep2", "arm": "showtime", "kind": "new", "judge": True},
              {"task": "t9-repo-explainer", "cell": "baseline", "arm": "baseline", "kind": "new", "judge": True},
              {"task": t1["id"], "cell": "showtime-020", "arm": "showtime", "kind": "reuse", "judge": True}]
        est = rnd.estimate(m, cs)
        self.assertEqual([r["usd"] for r in est["cells"]], [3.5, 3.5, rnd.EST_NEW["baseline"][0]])
        self.assertAlmostEqual(est["rank_usd"], 3 * rnd.JUDGE_USD_PER_CANDIDATE * 3, delta=0.01)
        shutil.rmtree(root, ignore_errors=True)

    def test_primary_prefers_the_asked_length(self):
        import run_one
        import time as _t
        ws = Path(tempfile.mkdtemp(prefix="pick-"))
        run_ff("-f", "lavfi", "-i", "testsrc2=s=160x90:r=10:d=6", "-pix_fmt", "yuv420p", ws / "final.mp4")
        _t.sleep(1.1)
        run_ff("-f", "lavfi", "-i", "testsrc2=s=160x90:r=10:d=2", "-pix_fmt", "yuv420p", ws / "final-2.mp4")   # newer, partial
        text = "Full video: final.mp4. I re-rendered one span as final-2.mp4."
        self.assertEqual(run_one.pick_primary(ws, "video", set(), text)["primary"], "final-2.mp4")   # newest wins a tie
        self.assertEqual(run_one.pick_primary(ws, "video", set(), text, {"duration": [5, 7]})["primary"], "final.mp4")
        shutil.rmtree(ws, ignore_errors=True)

    def test_bad_cell_name(self):
        import run_one
        with self.assertRaises(SystemExit):
            run_one.run_one("showtime", "t1", "rY", cell_name="Show Time")


def calls(*cmds):
    return [{"name": "Bash", "input": {"command": c}} if isinstance(c, str) else c for c in cmds]


@unittest.skipUnless(HAVE, "benchmarks/ not present")
class StreamAndGates(unittest.TestCase):
    def test_renders_from_stream(self):
        got = round_report.renders_from_stream(calls(
            'cd /w/p; SH=/h/.showtime/bin/showtime; ID=$($SH render showtime-out/j/project --background)',
            '$ST render showtime-out/j/project --from 3 --to 5 -o x.mp4',
            '/snap/plugin/skills/showtime/bin/showtime edit render showtime-out/j',
            'showtime snap final.mp4 --count 12', 'npx other-tool render', 'echo "render done"',
            {"name": "mcp__plugin_showtime_showtime__render", "input": {"project": "p"}},
            {"name": "mcp__plugin_showtime_showtime__render", "input": {"project": "p", "from": 2, "to": 4}}))
        self.assertEqual((got["full"], got["partial"]), (3, 2))

    def test_receipt_first(self):
        ws = Path(tempfile.mkdtemp(prefix="ws-"))
        job = ws / "showtime-out" / "launch-1"
        job.mkdir(parents=True)
        common.write_json(job / "receipt.json", {"renders": {"full": 1, "partial": 2, "preview": 0},
                                                 "usage": {"cost_usd": 1.02}})
        got = round_report.renders_from_job(ws, "showtime-out/launch-1/final.mp4")
        self.assertEqual((got["full"], got["source"]), (1, "receipt.json"))
        self.assertEqual(round_report.receipt_for(ws, None)["usage"]["cost_usd"], 1.02)
        shutil.rmtree(ws, ignore_errors=True)

    def test_foreign_paths(self):
        cs = calls('S=/srv/arms/a1/prefix/plugin/skills/showtime/bin/showtime; $S check',
                   'cat /opt/op/w/docs/skills/showtime/templates/short/README.md',
                   'ls /srv/arms/a1/hm/.showtime/bin', 'ls /opt/op/.showtime/cache',
                   {"name": "Read", "input": {"file_path": "/opt/op/w/docs/skills/showtime/SKILL.md"}})
        got = round_report.foreign_paths(cs, ["/srv/arms/a1/hm/.showtime", "/srv/arms/a1/prefix/plugin"])
        self.assertEqual(got, ["/opt/op/w/docs/skills/showtime", "/opt/op/.showtime"])
        self.assertEqual(len(round_report.foreign_paths(cs, [])), 4)   # a baseline may touch none
        # a heredoc's newline is not part of the path; the shared venv linked into the overlay is allowed, its bin/ is not
        cs2 = calls('cat > /w/look/verdicts.md <<EOF\nx\nEOF\nST=/srv/arms/a1/prefix/plugin/skills/showtime; $ST check',
                    'ls /opt/op/.showtime/venv/bin/python3*', 'ls /opt/op/.showtime/bin/showtime')
        got2 = round_report.foreign_paths(cs2, ["/srv/arms/a1/prefix/plugin", "/opt/op/.showtime/venv"])
        self.assertEqual(got2, ["/opt/op/.showtime"])
        self.assertEqual(round_report.foreign_paths(cs2[:2], ["/srv/arms/a1/prefix/plugin", "/opt/op/.showtime/venv"]), [])

    def _round(self, name, votes=None):
        root = home() / "runs" / name
        m = json.loads((BENCH / "rounds" / "r4.json").read_text(encoding="utf-8"))
        m["run"] = name
        rows = []
        tids = {t["id"].split("-")[0]: t["id"] for t in common.load_tasks()}
        for key, spec in m["tasks"].items():
            for cell in spec.get("new", []) + spec.get("reuse", []):
                arm = m["cells"][cell]["arm"]
                reused = cell in spec.get("reuse", [])
                cost = 1.0 if cell == "showtime" else 1.2 if cell == "baseline" else 2.5
                rows.append({"task": tids[key], "cell": cell, "arm": arm, "reused": reused, "cost_usd": cost,
                             "images_main": 8, "renders": {"full": 1, "source": "receipt.json"}, "receipt": not reused,
                             "receipt_cost": 1.0, "foreign_paths": []})
                common.write_json(root / tids[key] / cell / "score" / "auto.json",
                                  {"qa": {"summary": {"fail": 0}}})
        per_task = {}
        for key in m["gates"]["quality_tasks"]:
            per_task[tids[key]] = {"showtime": {"mean_rank": 1.0}, "showtime-020": {"mean_rank": 2.0},
                                   "baseline": {"mean_rank": 3.0}}
        per_task[tids["t1"]].update({"skill-b": {"mean_rank": 1.5}, "showtime-rep2": {"mean_rank": 4.0}})
        common.write_json(root / "rank_summary.json", {"per_task": per_task})
        pairs = [{"task": tids[k], "a": "showtime", "b": "showtime-020", "winner": "showtime"} for k in (votes or [])]
        common.write_json(root / "human_summary.json", {"pairs": pairs})
        return m, rows, root

    def test_gates_pass_and_pending(self):
        m, rows, root = self._round("g1")
        gs = {g["id"]: g for g in round_report.gates(m, rows, root)}
        self.assertEqual(gs["cost"]["status"], "PASS")
        self.assertEqual((gs["cost"]["focal_median"], gs["cost"]["baseline_median"]), (1.0, 1.2))
        self.assertEqual(gs["images"]["status"], "PASS")
        self.assertEqual(gs["renders"]["status"], "PASS")
        self.assertEqual(gs["quality"]["status"], "PENDING")   # the judge says yes, the vote is not in yet
        self.assertEqual(gs["launch"]["status"], "PENDING")
        self.assertEqual(gs["qa"]["status"], "PASS")
        self.assertEqual(gs["receipts"]["status"], "PASS")
        self.assertEqual(gs["isolation"]["status"], "PASS")
        m, rows, root = self._round("g2", votes=["t1", "t2", "t3", "t4", "t6"])
        gs = {g["id"]: g for g in round_report.gates(m, rows, root)}
        self.assertEqual(gs["quality"]["status"], "PASS")        # 5 of 6 won, t8 still pending
        self.assertEqual(gs["quality"]["passed"], 5)
        self.assertEqual(gs["launch"]["status"], "PASS")          # t1 voted as pairs only: it won its pair
        self.assertIn("blind pairs won 1 of 1", gs["launch"]["detail"])
        hs = common.read_json(root / "human_summary.json")
        hs["pairs"] = [dict(p, winner="showtime-020") if p["task"] == "t1-launch" else p for p in hs["pairs"]]
        common.write_json(root / "human_summary.json", hs)
        gs = {g["id"]: g for g in round_report.gates(m, rows, root)}
        self.assertEqual(gs["launch"]["status"], "FAIL")          # lost every pair it was in

    def test_gates_fail(self):
        m, rows, root = self._round("g3")
        for r in rows:
            if r["cell"] == "showtime":
                r.update(cost_usd=2.0, images_main=30, renders={"full": 3, "source": "stream (estimate)"})
        rows[0]["foreign_paths"] = ["/opt/op/w/docs/skills/showtime"]
        common.write_json(root / "t1-launch" / "showtime" / "score" / "auto.json", {"qa": {"summary": {"fail": 1}}})
        rk = common.read_json(root / "rank_summary.json")
        rk["per_task"]["t1-launch"]["showtime"]["mean_rank"] = 3.5        # behind baseline and skill-b; rep2 not counted
        for t in ("t2-data-story", "t3-vertical-short"):
            rk["per_task"][t]["showtime"]["mean_rank"] = 2.5
        common.write_json(root / "rank_summary.json", rk)
        gs = {g["id"]: g for g in round_report.gates(m, rows, root)}
        for gid in ("cost", "images", "renders", "qa", "launch", "isolation", "quality"):
            self.assertEqual(gs[gid]["status"], "FAIL", (gid, gs[gid]))

    def test_tables(self):
        m, rows, root = self._round("g4")
        md = round_report.metrics_table(rows)
        self.assertIn("| images main |", md)
        self.assertIn("showtime-rep2", round_report.spread_table(rows, "showtime"))


@unittest.skipUnless(HAVE, "benchmarks/ not present")
class ReferenceForJudgesAndVoters(unittest.TestCase):
    def test_rank_packet(self):
        import rank
        with tempfile.TemporaryDirectory() as d:
            vid = Path(d) / "ref.mp4"
            run_ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=10:d=4", "-pix_fmt", "yuv420p", vid)
            pk = Path(d) / "pk"
            pk.mkdir()
            label = rank.add_reference(pk, {"id": "tX", "judge_reference": {"from": str(vid), "label": "reference"}})
            self.assertEqual(label, "reference")
            frames = sorted(p.name for p in (pk / "reference" / "frames").iterdir())
            self.assertIn("00.jpg", frames)
            self.assertIn("INDEX.txt", frames)
            self.assertEqual(rank.add_reference(pk, {"id": "tY"}), "")
        t10 = common.load_tasks(["t10"])[0]
        self.assertTrue(Path(rank.reference_video(t10)).as_posix().endswith("fixtures/media/style-reference.mp4"))
        self.assertIsNone(rank.reference_video(common.load_tasks(["t1"])[0]))

    def test_parallel_judges_record_a_page_once(self):
        """rank.py runs a task's judges in threads; an HTML deliverable must be screen-recorded once, not by
        every judge into the same file at the same time (the round-4 dry run got a corrupt recording)."""
        import threading
        import time as _t
        import human_board
        import pairwise
        ws = Path(tempfile.mkdtemp(prefix="html-ws-"))
        (ws / "report.html").write_text("<html></html>", encoding="utf-8")
        rd = home() / "runs" / "rec" / "t6-html-report" / "baseline"
        rd.mkdir(parents=True)
        common.write_json(rd / "meta.json", {"workspace": str(ws), "deliverable": {"primary": "report.html"}})
        state = {"now": 0, "max": 0, "calls": 0}

        def fake_record(src, dst, rerecord):
            state["now"] += 1
            state["calls"] += 1
            state["max"] = max(state["max"], state["now"])
            _t.sleep(0.2)
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b"mp4")
            common.write_json(dst.with_suffix(".json"), {"report": {"ok": True}})
            state["now"] -= 1
            return {"ok": True}

        real = human_board.record_html
        human_board.record_html = fake_record
        try:
            th = [threading.Thread(target=pairwise.html_recording, args=("rec", "t6-html-report", "baseline")) for _ in range(3)]
            [t.start() for t in th]
            [t.join() for t in th]
        finally:
            human_board.record_html = real
            shutil.rmtree(ws, ignore_errors=True)
        self.assertEqual((state["max"], state["calls"]), (1, 1))

    def test_board_reference_is_not_a_candidate(self):
        import human_board
        with tempfile.TemporaryDirectory() as d:
            vid = Path(d) / "ref.mp4"
            run_ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=10:d=3", "-pix_fmt", "yuv420p", vid)
            task = dict(common.load_tasks(["t10"])[0], judge_reference={"from": str(vid)})
            ref = human_board.reference_for(task)
            key = {"A": "showtime", "B": "baseline"}
            probe = {"ok": True, "duration": 20.0, "video": {"width": 1920, "height": 1080}, "audio": {}}
            cands = {a: {"probe": probe, "has_audio": True} for a in key.values()}
            s = {"box": 960, "video_kbps": 900, "audio_kbps": 96}
            b = human_board.board_json(task, Path(d) / "job", key, cands, ["A", "B"], {}, s, False, False, "showtime",
                                       ["baseline", "showtime"], ("r4", 11), ref=ref)
        tags = [c["tag"] for c in b["concepts"]]
        self.assertEqual(tags, ["A", "B", "REF"])
        self.assertTrue(b["blind"])
        self.assertFalse(any("REF" in q["text"] for q in b["questions"]))
        self.assertEqual(b["concepts"][-1]["title"], "Reference (not a candidate)")   # short: selects size to it
        digest = ('STUDIO FEEDBACK - Blind vote\nReactions:\n  - A "Version A": 4/5\n  - REF "Reference": 5/5\n')
        self.assertEqual(human_board.parse_digest(digest)["ratings"], {"A": 4})

    def test_vote_step_on_blind_boards(self):
        js = (SKILL / "runtime" / "studio" / "board.js").read_text(encoding="utf-8")
        css = (SKILL / "runtime" / "studio" / "board.css").read_text(encoding="utf-8")
        self.assertIn("How to vote", js)
        self.assertIn("'Copy my votes'", js)
        self.assertIn("(b.blind ? renderVoteHowto() : '')", js)          # only on blind boards
        self.assertIn("S.board && S.board.blind ? 'Copy my votes' : 'Copy for your agent'", js)
        self.assertIn(".vote-howto", css)


PHONE_DRIVER = r"""
import { pathToFileURL } from 'node:url';
const [chromeLib, page, outPath] = process.argv.slice(2);
const fs = await import('node:fs');
const { launchBrowser } = await import(pathToFileURL(chromeLib).href);
const { browser } = await launchBrowser({});
const R = { errors: [] };
try {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
  const p = await ctx.newPage();
  p.on('pageerror', (e) => R.errors.push(e.message));
  await p.goto(pathToFileURL(page).href);
  await p.waitForSelector('.vote-howto');
  R.howto = await p.$eval('.vote-howto', (e) => { const b = e.getBoundingClientRect(); return { top: b.top, bottom: b.bottom, text: e.innerText }; });
  R.howtoButton = await p.$eval('.vote-howto [data-act="handoff"]', (e) => e.textContent.trim());
  R.bar = await p.$eval('#mCopy', (e) => ({ text: e.textContent.trim(), shown: getComputedStyle(e.parentElement).display !== 'none' }));
  R.phases = await p.$$eval('main .phases, main [class*="phase"]', (els) => els.length);
  R.wide = await p.evaluate(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('main *, .mbar *')]
    .filter((e) => { const b = e.getBoundingClientRect(); return b.width > 0 && b.right > W + 1; }).map((e) => e.tagName + '#' + e.id + '.' + e.className).slice(0, 5); });
  R.innerWidth = await p.evaluate(() => window.innerWidth);
  await p.evaluate(() => { window.__copied = null; Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: (t) => { window.__copied = t; return Promise.resolve(); } } }); });
  await p.click('.card [data-act="rate"][data-v="4"]');
  await p.click('.vote-howto [data-act="handoff"]');
  await p.waitForFunction(() => typeof window.__copied === 'string');
  R.copied = await p.evaluate(() => window.__copied);
  R.same = await p.evaluate(() => window.__copied === window.StudioBoard.digest());
  R.toast = await p.$eval('#toasts', (e) => e.textContent);
} catch (e) { R.errors.push(String(e && e.message || e)); }
fs.writeFileSync(outPath, JSON.stringify(R));
await browser.close();
"""


@unittest.skipUnless(HAVE, "benchmarks/ not present")
class BlindBoardOnAPhone(unittest.TestCase):
    """A real blind board (studio export --target artifact, as the benchmark publishes it) at phone size."""

    @unittest.skipIf(FAST, "builds a studio board and opens it in Chrome (--fast skips)")
    def test_vote_step(self):
        import human_board
        node = shutil.which("node")
        if not node:
            self.skipTest("node not found")
        root = Path(tempfile.mkdtemp(prefix="blind-board-"))
        try:
            r = human_board.st(["studio", "init", "vote-tX", "--title", "Blind vote", "--brief", "b", "--json"], root, root)
            self.assertEqual(r.returncode, 0, r.stderr)
            info = json.loads(r.stdout)
            jdir = Path(info.get("job_dir") or Path(info["studio_dir"]).parent)
            media = jdir / "studio" / "media"
            for sub in ("animatic", "thumbs"):
                (media / sub).mkdir(parents=True, exist_ok=True)
            for L in ("A", "B", "C", "REF"):
                run_ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=10:d=2", "-pix_fmt", "yuv420p", media / "animatic" / (L + ".mp4"))
                run_ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=1:d=1", "-frames:v", "1", media / "thumbs" / (L + ".jpg"))
            key = {"A": "showtime", "B": "baseline", "C": "showtime-020"}
            probe = {"ok": True, "duration": 2.0, "video": {"width": 320, "height": 180}, "audio": None}
            cands = {a: {"probe": probe, "has_audio": False} for a in key.values()}
            ref = {"src": media / "animatic" / "REF.mp4", "probe": probe}
            b = human_board.board_json(common.load_tasks(["t10"])[0], jdir, key, cands, ["A", "B", "C"], {},
                                       {"box": 320, "video_kbps": 300, "audio_kbps": 64}, False, False, "showtime",
                                       sorted(key.values()), ("rT", 11), ref=ref)
            common.write_json(jdir / "studio" / "board.json", b)
            r = human_board.st(["studio", "board", str(jdir)], root, root)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            page = root / "board.html"
            r = human_board.st(["studio", "export", str(jdir), "--target", "artifact", "-o", str(page), "--json"], root, root)
            self.assertEqual(r.returncode, 0, r.stderr)
            drv, out = root / "phone.mjs", root / "phone.json"
            drv.write_text(PHONE_DRIVER, encoding="utf-8")
            cp = subprocess.run([node, str(drv), str(SKILL / "scripts" / "lib" / "chrome.mjs"), str(page), str(out)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=180)
            if not out.exists():
                self.skipTest("no browser could start: " + (cp.stderr or cp.stdout)[-300:])
            res = json.loads(out.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual(res["errors"], [])
        self.assertLess(res["howto"]["top"], 300, "How to vote is at the top of the page")
        self.assertIn("How to vote", res["howto"]["text"])
        self.assertEqual(res["howtoButton"], "Copy my votes")
        self.assertEqual(res["bar"], {"text": "Copy my votes", "shown": True})
        self.assertEqual(res["phases"], 0, "no production phases on a blind vote")
        self.assertEqual(res["wide"], [], "nothing wider than the phone")
        self.assertEqual(res["innerWidth"], 390)
        self.assertTrue(res["copied"].startswith("STUDIO FEEDBACK"), res["copied"][:200])
        self.assertTrue(res["same"])
        self.assertIn("Votes copied", res["toast"])
        self.assertEqual(human_board.parse_digest(res["copied"])["ratings"], {"A": 4})

SITE_TOOLS = REPO / "site" / "tools"


@unittest.skipUnless((SITE_TOOLS / "benchmark_pages.py").is_file(), "site/ not present")
class BenchmarkPages(unittest.TestCase):
    """site/tools/benchmark_pages.py: one page per report version, the latest also at /benchmark/, a version bar."""

    def test_versions_latest_and_links(self):
        sys.path.insert(0, str(SITE_TOOLS))
        import benchmark_pages as bp
        root = Path(tempfile.mkdtemp(prefix="bench-pages-"))
        src, out = root / "src", root / "out"
        for v, page in (("v0.2.0", "<title>old</title><p>fragment report</p>"),
                        ("v0.10.0", '<!doctype html><html><head><title>new</title></head><body>'
                                    '<a href="../v0.2.0/">old</a><a href="#m">m</a><img src="a.png">'
                                    '<a href="https://example.com/x">x</a></body></html>'),
                        ("v0.3.0", "<!doctype html><html><head></head><body>mid</body></html>")):
            (src / v).mkdir(parents=True)
            (src / v / "index.html").write_text(page, encoding="utf-8")
        (src / "notes").mkdir()
        self.assertEqual(bp.build(src, out), ["v0.10.0", "v0.3.0", "v0.2.0"])      # numeric order, not text
        vs = json.loads((out / "versions.json").read_text(encoding="utf-8"))
        self.assertEqual([(x["version"], x["path"], x["latest"]) for x in vs],
                         [("v0.10.0", "", True), ("v0.3.0", "v0.3.0/", False), ("v0.2.0", "v0.2.0/", False)])
        latest = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="v0.2.0/">old', latest)                  # ../v0.2.0/ seen from /benchmark/
        self.assertIn('src="v0.10.0/a.png"', latest)
        self.assertIn('href="#m"', latest)
        self.assertIn('href="https://example.com/x"', latest)
        self.assertIn('<a class="stbv-v" href="./" aria-current="page">v0.10.0<small>latest</small>', latest)
        old = (out / "v0.2.0" / "index.html").read_text(encoding="utf-8")
        self.assertTrue(old.startswith("<!doctype html>"))            # a fragment gets a document and a viewport
        self.assertIn('name="viewport"', old)
        self.assertLess(old.index("</head>"), old.index("<body>"))
        self.assertLess(old.index("<body>"), old.index('<nav class="stbv"'))
        self.assertIn('<a class="stbv-v" href="../v0.2.0/" aria-current="page">', old)
        self.assertIn('<a class="stbv-home" href="../../">', old)
        again = bp.inject(old, bp.bar("v0.2.0", ["v0.2.0"], "../", "../../"))   # rebuilding keeps one bar
        self.assertEqual(again.count('<nav class="stbv"'), 1)
        self.assertEqual(again.count('id="stbv-style"'), 1)
        self.assertEqual(bp.build(root / "none", root / "o2") if (root / "none").mkdir() is None else None, [])
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    sys.exit(0 if prog.result.wasSuccessful() else 1)

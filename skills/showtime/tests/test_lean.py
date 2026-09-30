#!/usr/bin/env python3
"""Lean mode: looks out of the agent's context, check before render, brief output.

  * brief output: `brief_output()` (terminal vs agent, --verbose, SHOWTIME_OUTPUT), qa's brief text (the
    loudness line, FAIL/WARN with frame and fix, notes as a count), doctor's brief text and its details file;
  * `showtime look`: its pure helpers (key times from a scene table, the reviewer brief, a job's target,
    check freshness) and, with setup, real looks of a project, a video and a job (one composite at the asked
    width, numbered per job, a brief and verdicts.md, full-size stills on request, scene frames from a
    current check report);
  * `showtime check` prints a brief summary to agents and the full report with --verbose and in report.txt;
  * `showtime render` nudges before a full render of an unchecked or changed project, never before a preview,
    and names the section render after a second full render;
  * the MCP snap tool runs `look` with look=true;
  * benchmarks/scoring/stream_cost.py counts images in the main context vs sub-agents and the context per call.

Stdlib only. The pure parts need no setup; the rest skips without Node + Playwright (showtime setup).
usage: python tests/test_lean.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import os
import shutil
import struct
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

from st import common  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402
from st.qa import video as qa  # noqa: E402

HOME = showtime_home()
ENV = build_env(HOME)
NODE = shutil.which("node", path=ENV.get("PATH"))
READY = bool(NODE) and (HOME / "node" / "node_modules" / "playwright").is_dir()
TMP = Path(tempfile.mkdtemp(prefix="st-lean-"))


def tearDownModule():
    shutil.rmtree(str(TMP), ignore_errors=True)


def showtime(*args, check=True, timeout=600, env=None, cwd=None):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=env or ENV, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def node_eval(code, timeout=60):
    """Run an ES module snippet with the skill's scripts importable; -> parsed JSON of its last stdout line."""
    cp = subprocess.run([NODE, "--input-type=module", "-e", code], env=ENV, cwd=str(TMP), stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", timeout=timeout)
    if cp.returncode != 0:
        raise AssertionError("node failed:\n%s\n%s" % (cp.stdout[-2000:], cp.stderr[-2000:]))
    return json.loads(cp.stdout.strip().splitlines()[-1])


def url(p: Path) -> str:
    return Path(p).resolve().as_uri()


def jpeg_size(path):
    data = Path(path).read_bytes()
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        mk = data[i + 1]
        if mk in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        ln = struct.unpack(">H", data[i + 2:i + 4])[0]
        i += 2 + ln
    raise AssertionError("no JPEG frame header in %s" % path)


# --------------------------------------------------------------------------- brief output (pure)

class TestBriefOutput(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ("SHOWTIME_OUTPUT", "SHOWTIME_VERBOSE", "SHOWTIME_MCP")}
        for k in self.saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_terminal_gets_the_full_report_agents_get_brief(self):
        class Tty:
            def isatty(self):
                return True

        class Pipe:
            def isatty(self):
                return False

        self.assertFalse(common.brief_output(stream=Tty()))
        self.assertTrue(common.brief_output(stream=Pipe()))
        self.assertFalse(common.brief_output(True, stream=Pipe()), "--verbose wins")
        os.environ["SHOWTIME_MCP"] = "1"
        self.assertTrue(common.brief_output(stream=Tty()), "the MCP server always gets brief output")
        os.environ["SHOWTIME_OUTPUT"] = "full"
        self.assertFalse(common.brief_output(stream=Pipe()))
        os.environ["SHOWTIME_OUTPUT"] = "brief"
        os.environ.pop("SHOWTIME_MCP")
        self.assertTrue(common.brief_output(stream=Tty()))
        os.environ["SHOWTIME_VERBOSE"] = "1"
        self.assertFalse(common.brief_output(stream=Pipe()))

    def test_qa_brief_keeps_what_to_act_on(self):
        notes = [{"severity": "INFO", "rule": "final_hold", "t": 40.0 + i, "message": "hold %d" % i} for i in range(25)]
        rep = {
            "video": "/x/final.mp4", "probe": {"width": 1920, "height": 1080, "fps": 30, "duration": 45.1, "size_bytes": 3.5e6},
            "target": {"name": "youtube"},
            "passed": ["file: h264 High, yuv420p", "loudness -14.0 LUFS (target -14), true peak -2.4 dBTP",
                       "no silent gaps (audio from 0.00s to 44.45s)", "frame 0 flows into frame 1 (no poster flash)"],
            "findings": [{"severity": "FAIL", "rule": "black_segment", "t": 9.73, "message": "black from 9.73s",
                          "frame": "/x/work/qa/final/frames/t0009.733s.jpg", "fix": "check clip timing"},
                         {"severity": "WARN", "rule": "frozen", "t": 30.47, "message": "no change for 4.4s",
                          "frame": "/x/f.jpg", "fix": "add motion"}] + notes,
            "rhythm": {"summary": "8 layouts"}, "sheet": "/x/sheet.jpg", "report": "/x/qa.json",
            "summary": {"fail": 1, "warn": 1, "info": 25}, "verdict": "FAIL", "seconds": 9.8,
        }
        full = qa.format_text(rep)
        brief = qa.format_text(rep, brief=True)
        self.assertLess(len(brief.splitlines()), len(full.splitlines()))
        self.assertLessEqual(len(brief.splitlines()), 14, brief)
        for must in ("-14.0 LUFS", "true peak -2.4 dBTP", "black_segment", "t0009.733s.jpg", "fix: check clip timing",
                     "frozen", "fix: add motion", "/x/qa.json", "25 note(s)", "verdict: FAIL", "platform  youtube", "showtime look /x/final.mp4"):
            self.assertIn(must, brief)
        self.assertNotIn("hold 3", brief, "notes are counted, not listed")
        self.assertIn("also file, no silent gaps, frame 0 flows into frame 1", brief)

    def test_doctor_brief_and_verbose(self):
        home = TMP / "doctor-home"
        home.mkdir(parents=True, exist_ok=True)
        env = dict(ENV, SHOWTIME_HOME=str(home), SHOWTIME_OFFLINE="1")
        env.pop("SHOWTIME_OUTPUT", None)
        brief = showtime("doctor", "--quick", env=env, check=False, timeout=300).stdout
        lines = brief.strip().splitlines()
        self.assertTrue(lines[0].startswith("showtime doctor "), brief)
        self.assertIn("not ready", lines[0], "a fresh home fails: the verdict is on the first line")
        self.assertIn("fix:", brief)
        self.assertNotIn("PASS ", brief, "passing checks are only counted")
        details = home / "logs" / "doctor.txt"
        self.assertTrue(details.is_file(), "the full table goes to a file")
        self.assertIn("PASS", details.read_text(encoding="utf-8"))
        self.assertIn(str(details), brief)
        full = showtime("doctor", "--quick", "--verbose", env=env, check=False, timeout=300).stdout
        self.assertIn("PASS", full)
        self.assertGreater(len(full.splitlines()), len(lines))


# --------------------------------------------------------------------------- stream accounting (pure)

class TestStreamCost(unittest.TestCase):
    def test_images_main_vs_subagent_and_context(self):
        sys.path.insert(0, str(REPO / "benchmarks" / "scoring"))
        import stream_cost
        img = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}
        rows = [
            {"type": "assistant", "message": {"id": "m1", "usage": {"input_tokens": 5, "cache_read_input_tokens": 10000,
                                                                     "cache_creation_input_tokens": 2000},
                                              "content": [{"type": "tool_use", "id": "t1", "name": "Read",
                                                           "input": {"file_path": "/j/work/snap/sheet.jpg"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": [img]}]}},
            {"type": "assistant", "message": {"id": "m2", "usage": {"input_tokens": 5, "cache_read_input_tokens": 30000},
                                              "content": [{"type": "tool_use", "id": "t2", "name": "Bash",
                                                           "input": {"command": "showtime check p"}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": "x" * 900}]}},
            {"type": "assistant", "parent_tool_use_id": "t9", "message": {"id": "s1", "usage": {"input_tokens": 1,
                                                                                               "cache_read_input_tokens": 90000},
                                                                      "content": [{"type": "tool_use", "id": "t3", "name": "Read",
                                                                                   "input": {"file_path": "/j/f.png"}}]}},
            {"type": "user", "parent_tool_use_id": "t9",
             "message": {"content": [{"type": "tool_result", "tool_use_id": "t3", "content": [img, img]}]}},
            {"type": "result", "total_cost_usd": 1.234, "num_turns": 3},
        ]
        f = TMP / "stream.jsonl"
        f.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        r = stream_cost.analyse(f)
        self.assertEqual((r["images_main"], r["images_sub"]), (1, 2))
        self.assertEqual(r["ctx_max"], 30005, "sub-agent calls do not count toward the main context")
        self.assertEqual(r["calls_main"], 2)
        self.assertEqual(r["cost_usd"], 1.23)
        self.assertEqual(r["image_sources"], {"Read .jpg": 1})
        self.assertEqual(r["largest_outputs"][0]["chars"], 900)
        self.assertIn("showtime check p", r["largest_outputs"][0]["tool"])


# --------------------------------------------------------------------------- look helpers (node, no browser)

@unittest.skipUnless(READY, "needs Node and showtime setup (Playwright)")
class TestLookHelpers(unittest.TestCase):
    def test_key_times_from_scenes(self):
        look = url(SKILL / "scripts" / "look.mjs")
        r = node_eval("""
const L = await import(%s);
const info = { duration: 10, fps: 30 };
const a = L.keyTimes(info, [{id: 'intro', start: 0, end: 4}, {id: 'demo', start: 4, end: 8}, {name: 'end card', start: 8, end: 10}], 8);
const b = L.keyTimes(info, null, 4);
const many = L.keyTimes({ duration: 60, fps: 30 }, Array.from({length: 30}, (_, i) => ({ id: 's' + i, start: 2 * i, end: 2 * i + 2 })), 8);
console.log(JSON.stringify({ a, b, many: many.length }));
""" % json.dumps(look))
        self.assertEqual([x["t"] for x in r["a"]], [0, 2.4, 6.4, 9.2, 9.966666666666667])
        self.assertEqual([x["label"] for x in r["a"]], ["first", "intro", "demo", "end card", "last"])
        self.assertEqual(len(r["b"]), 6, "the opening frame, 4 evenly spaced, the last")
        self.assertLessEqual(r["many"], 16, "one look is one small image")

    def test_brief_and_job_target_and_freshness(self):
        job = TMP / "showtime-out" / "demo-20260929-101500"
        proj = job / "project"
        (proj / "work" / "check").mkdir(parents=True)
        (proj / "showtime.json").write_text("{}", encoding="utf-8")
        (proj / "index.html").write_text("<html></html>", encoding="utf-8")
        (job / "job.json").write_text(json.dumps({"outputs": {}}), encoding="utf-8")
        rep = proj / "work" / "check" / "report.json"
        look = url(SKILL / "scripts" / "look.mjs")
        lean = url(SKILL / "scripts" / "lib" / "lean.mjs")
        code = """
const L = await import(%s); const N = await import(%s);
const out = {};
out.none = N.checkFreshness(%s, 'index.html', null).state;
out.target1 = L.jobTarget(%s);
console.log(JSON.stringify(out));
""" % (json.dumps(look), json.dumps(lean), json.dumps(str(proj)), json.dumps(str(job)))
        r = node_eval(code)
        self.assertEqual(r["none"], "none")
        self.assertEqual(r["target1"]["why"], "project", "no video yet: the job's project")
        rep.write_text(json.dumps({"scenes": []}), encoding="utf-8")
        old = time.time() - 600
        os.utime(str(proj / "index.html"), (old, old))
        os.utime(str(proj / "showtime.json"), (old, old))
        (job / "final.mp4").write_bytes(b"x")
        (job / "preview.mp4").write_bytes(b"x")
        os.utime(str(job / "preview.mp4"), (time.time() + 5, time.time() + 5))
        r = node_eval(code.replace("out.none", "out.fresh"))
        self.assertEqual(r["fresh"], "fresh")
        self.assertEqual(Path(r["target1"]["target"]).name, "final.mp4", "a final wins over a newer preview")
        later = time.time() + 120
        os.utime(str(proj / "index.html"), (later, later))
        r = node_eval(code.replace("out.none = N.checkFreshness(", "out.stale = N.checkFreshness(").replace(".state;", ";"))
        self.assertEqual(r["stale"]["state"], "stale")
        self.assertTrue(r["stale"]["changed"].endswith("index.html"))
        (job / "job.json").write_text(json.dumps({"outputs": {"final": "preview.mp4"}}), encoding="utf-8")
        r = node_eval(code)
        self.assertEqual(r["target1"]["why"], "latest final", "the ledger pointer wins")
        b = node_eval("""
const L = await import(%s);
console.log(JSON.stringify(L.reviewerBrief({ n: 3, title: 'Demo', image: '/j/work/look/look-3.jpg', stills: null,
  frames: [{t: 0}, {t: 2}], note: 'is the chart label readable?', verdicts: '/j/work/look/verdicts.md' })));
""" % json.dumps(look))
        for must in ("# Look 3: Demo", "look-3.jpg (2 frames", "is the chart label readable?", "VERDICT: ok | fix",
                     '"## look 3"', "verdicts.md", "at most 12 lines"):
            self.assertIn(must, b)
        self.assertNotIn("Full-size frames", b)


# --------------------------------------------------------------------------- real runs (setup + browser)

@unittest.skipUnless(READY, "needs Node and showtime setup (Playwright, a browser)")
class TestLeanRuns(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = TMP / "runs"
        cls.base.mkdir(parents=True, exist_ok=True)
        cls.env = dict(ENV)
        for k in ("SHOWTIME_OUTPUT", "SHOWTIME_VERBOSE", "SHOWTIME_MCP"):
            cls.env.pop(k, None)
        cls.job = Path(json.loads(showtime("job", "init", "lean", "--json", cwd=cls.base, env=cls.env).stdout)["job"])
        cls.proj = cls.job / "project"
        showtime("new", "dom", cls.proj, "--duration", 3, "--size", "480x270", cwd=cls.base, env=cls.env)

    def run_st(self, *args, check=True):
        return showtime(*args, cwd=self.base, env=self.env, check=check)

    def test_1_check_brief_then_verbose(self):
        cp = self.run_st("check", self.proj, "--no-determinism", check=False)
        self.assertIn(cp.returncode, (0, 1), cp.stderr)
        out = cp.stdout
        self.assertIn("result:", out)
        self.assertIn("report.txt", out)
        self.assertIn("showtime look ", out, "the brief output points at the lean look, not the full sheet")
        self.assertLessEqual(len(out.splitlines()), 15, out)
        self.assertEqual(out.count("fix: hold it longer"), 1, "a repeated problem is one line with one fix")
        self.assertNotIn("sampled", cp.stderr, "progress steps are for terminals")
        txt = self.proj / "work" / "check" / "report.txt"
        self.assertTrue(txt.is_file())
        self.assertIn("PASS  page loads cleanly", txt.read_text(encoding="utf-8"))
        self.assertNotIn("\x1b[", txt.read_text(encoding="utf-8"))
        full = self.run_st("check", self.proj, "--no-determinism", "--verbose", check=False).stdout
        self.assertIn("PASS  page loads cleanly", full)
        self.assertIn("sheet", full)

    def test_2_look_project(self):
        self.run_st("check", self.proj, "--no-determinism", check=False)
        r = json.loads(self.run_st("look", self.proj, "--json").stdout)
        look_dir = self.job / "work" / "look"
        self.assertEqual(Path(r["image"]).parent, look_dir, "looks of a project inside a job count per job")
        self.assertTrue(1260 <= jpeg_size(r["image"])[0] <= 1280, jpeg_size(r["image"]))
        self.assertEqual(r["scenes_from"], "check report", "a current check report gives the scene frames")
        self.assertEqual(r["frames"][0]["t"], 0)
        self.assertTrue(Path(r["brief"]).is_file() and Path(r["verdicts"]).is_file())
        self.assertIn(r["image"], Path(r["brief"]).read_text(encoding="utf-8"))
        cp = self.run_st("look", self.proj, "--at", "0.5,1.5", "--width", 640, "--stills", "--note", "title legible?")
        lines = cp.stdout.strip().splitlines()
        self.assertLessEqual(len(lines), 6, cp.stdout)
        self.assertTrue(lines[0].startswith("look %d/12" % (r["look"] + 1)), cp.stdout)
        n = r["look"] + 1
        self.assertTrue(620 <= jpeg_size(look_dir / ("look-%d.jpg" % n))[0] <= 640)
        self.assertEqual(len(list((look_dir / ("look-%d" % n)).glob("*.jpg"))), 2)
        self.assertIn("title legible?", (look_dir / ("look-%d.md" % n)).read_text(encoding="utf-8"))
        bad = self.run_st("look", self.proj, "--at", ",".join(str(0.1 * i) for i in range(17)), check=False)
        self.assertNotEqual(bad.returncode, 0, "more than 16 times is not one small image")

    def test_3_render_nudges_and_look_at_the_job(self):
        fresh = self.base / "unchecked"
        showtime("new", "dom", fresh, "--duration", 2, "--size", "480x270", cwd=self.base, env=self.env)
        cp = self.run_st("render", fresh, "--preview")
        self.assertNotIn("showtime check", cp.stderr, "a preview is cheap: no nudge")
        out = self.base / "renders" / "final.mp4"
        cp = self.run_st("render", fresh, "-o", out)
        self.assertIn("no `showtime check` has run on this project", cp.stderr)
        self.assertNotIn("next fix:", cp.stdout, "a first full render")
        self.run_st("check", fresh, "--no-determinism", check=False)
        cp = self.run_st("render", fresh, "-o", out)
        self.assertNotIn("showtime check", cp.stderr, "checked since the last edit: no nudge")
        self.assertIn("next fix:", cp.stdout, "a second full render names the section render")
        self.assertIn("--from S --to S", cp.stdout)
        later = time.time() + 5
        os.utime(str(fresh / "index.html"), (later, later))
        cp = self.run_st("render", fresh, "-o", out, "--json")
        self.assertIn("index.html changed", cp.stderr)
        self.assertEqual(len(json.loads(cp.stdout)["nudges"]), 1, "the render report keeps the nudge")
        cp = self.run_st("render", fresh, "-o", out, "--from", 0, "--to", 1)
        self.assertNotIn("changed", cp.stderr, "a section render is the cheap fix path: no nudge")
        # a job: look at its latest final
        self.run_st("check", self.proj, "--no-determinism", check=False)
        self.run_st("render", self.proj, "--job", self.job)
        cp = self.run_st("look", self.job)
        self.assertIn("using ", cp.stdout)
        self.assertIn("(latest final)", cp.stdout)
        self.assertRegex(cp.stdout, r"look \d+/12  .*look-\d+\.jpg")


# --------------------------------------------------------------------------- MCP

@unittest.skipUnless(NODE, "Node.js is not installed")
class TestMcpLook(unittest.TestCase):
    def test_snap_tool_with_look_runs_look(self):
        sys.path.insert(0, str(TESTS_DIR))
        from test_mcp import call, clean_env, mcp, text_of
        proj = TMP / "mcp-proj"
        proj.mkdir(parents=True, exist_ok=True)
        (proj / "showtime.json").write_text('{"duration": 2}', encoding="utf-8")
        (proj / "index.html").write_text("<html></html>", encoding="utf-8")
        env = {"SHOWTIME_HOME": str(TMP / "mcp-home")}
        out = mcp([{"method": "tools/list"},
                   call("snap", {"target": str(proj), "look": True, "at": [0.5] * 17})], TMP, env=env)
        tools = {t["name"]: t for t in out["results"][1]["response"]["result"]["tools"]}
        self.assertIn("look", tools["snap"]["inputSchema"]["properties"])
        bad = out["results"][2]
        self.assertTrue(bad["response"]["result"]["isError"])
        self.assertIn("with look, at takes 1-16 times", text_of(bad))
        del clean_env


if __name__ == "__main__":
    t0 = time.time()
    argv = [a for a in sys.argv if a != "--fast"]
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    print("test_lean: %.1fs" % (time.time() - t0), file=sys.stderr)
    sys.exit(0 if prog.result.wasSuccessful() else 1)

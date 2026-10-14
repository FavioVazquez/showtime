#!/usr/bin/env python3
"""Waits scaled to the page's measured cost (0.4.1): runtime/stage.js pace + scripts/lib/stagehost.mjs.

The fixed waits (page load, fonts, images, videos, ST.waitFor gates, seeks, ready, render's page open) fail a
slow machine or a heavy page. The page measures the gaps between its frames while it gets ready and its first
seeks, and every wait is its fixed value times a factor of 1-5 (never shorter than today).

  * units (node, no browser): a paced deadline grows when the factor rises while it waits, a factor never
    drops, the render.json/check record names the slowest page; SHOWTIME_PACE=0 keeps the fixed waits
  * a page whose every frame takes 3.2 s of main-thread work, with the waits shrunk for the test
    (SHOWTIME_TEST_WAIT_SCALE=0.04: a seek gets 2.4 s, as 60 s does on a real machine): with the fixed waits
    (SHOWTIME_PACE=0) the render fails on the seek deadline; paced, it renders and render.json records the
    factor (5, the ceiling) and the seek cost
  * a page whose ST.waitFor gate takes 4 s of work in 400 ms pieces from the moment ST.ready() is called (scale
    0.03: the gate gets 1.8 s): with the fixed waits the page never becomes ready; paced, the gaps between its
    frames raise the factor and it does
  * the page-open deadline (stagehost openGuarded, SHOWTIME_TEST_OPEN_TIMEOUT shortens it): render's first page
    and check's pages are tried once more in a new browser, then the command fails naming the step; a browser
    really stopped (SIGSTOP) before check opens its page is killed and check finishes in a new one, and stopped
    later the watchdog ends check with an error naming its last step
  * a screenshot whose frame never comes (SHOWTIME_TEST_STOP_GPU stops the browser's GPU process just before a
    screenshot, as the macOS CI runners' virtual GPU stalled): render's screenshot fails once the browser's drawing
    processes have done no work for 30 s (it waited a flat 10 minutes, longer than any caller) and the frame is
    drawn again in a new browser; check, whose screenshots had no deadline, ends with an error naming its step;
    SHOWTIME_TIMEOUT ends a render at the caller's limit with an error naming each part's step
  * a clipped screenshot's read of the page's size, which waits for the frame the seek drew (issue #14): a main
    thread held past the old flat 60 s (15 s x the page's pace at the test scale) while its renderer works is waited
    for; a stopped renderer still fails the read with the stuck-frame guard's error
  * a page load that never reaches DOMContentLoaded fails as the page (check's ready_failed, with a report) at the
    load deadline inside the page-open one, never as a stuck browser; on check's second pages it stays a soft
    finding (issue #14 review)
  * the stuck-frame guard on a browser that cannot report its work (CDP replies faked, node only): one whose
    SystemInfo.getProcessInfo answers with an error is asked once and then only the screenshot cap applies, a late
    frame still comes through; one that does not answer at all is stuck after twice the idle time, and named so
    even on the tick that also reaches the cap
  * only Linux render browsers have --disable-frame-rate-limit (with it a renderer keeps working after the GPU
    process stops, so on macOS the guard never sees the stop; likely what stalled the macOS CI runners in 0.4.1)

Needs a browser. usage: python tests/test_pace.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
STAGEHOST = (SKILL / "scripts" / "lib" / "stagehost.mjs").as_uri()
SERVER = (SKILL / "scripts" / "server.mjs").as_uri()
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
ENV.pop("SHOWTIME_OUT", None)
ENV.pop("SHOWTIME_PACE", None)
ENV.pop("SHOWTIME_TEST_WAIT_SCALE", None)
ENV["SHOWTIME_OFFLINE"] = "1"
NODE = shutil.which("node", path=ENV.get("PATH")) or shutil.which("node")

HEAD = '<!doctype html><html><head><meta charset="utf-8"><script src="/_st/stage.js"></script>'
# the stage's clock is virtual in a render: busy loops read the real one
BUSY_JS = "const realNow = Date.prototype.constructor.now;\nfunction busy(ms) { const t0 = realNow(); while (realNow() - t0 < ms) { /* work */ } }\n"


def node(code, env=None, timeout=300):
    cp = subprocess.run([NODE, "--input-type=module", "-e", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding="utf-8", errors="replace", timeout=timeout, env=env or ENV)
    assert cp.returncode == 0, cp.stderr[-3000:]
    return json.loads(cp.stdout.strip().splitlines()[-1])


def showtime(*args, env=None, timeout=600):
    return subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=env or ENV,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                          timeout=timeout)


# the stuck-frame guard's two verdicts (stagehost guardShot): the drawing processes did no work, or the browser stopped
# saying what they do. With the GPU process stopped Chrome now and then stops answering SystemInfo.getProcessInfo too
# (2 of 8 stopped-GPU checks on a 6-core Mac, 11 Oct), so either one is the guard ending a frame that never comes.
STUCK_FRAME = (r"\((its GPU process and renderers did no work for \d+ s: the frame is not coming|"
               r"the browser did not say what it was doing for \d+ s)\)")

STUCK_AT = (r"stuck at: (creating the browser context|opening a tab|setting up the tab|loading the page|"
            r"waiting for the page to be ready)")


def shot_idle_ms():
    """stagehost's SHOT_IDLE_MS: the stuck-frame guard's idle window before the test scale (tests derive from it)."""
    return node("const S = await import(%s); console.log(JSON.stringify(S.SHOT_IDLE_MS));" % json.dumps(STAGEHOST))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestUnits(unittest.TestCase):
    def test_paced_deadline_and_record(self):
        r = node("""
const S = await import(%s);
const out = {};
// a deadline of 0.3 s that the page's factor raises to 3 while it waits: a 0.6 s job finishes
const pace = S.newPace();
setTimeout(() => S.notePace(pace, { factor: 3, frame_ms: 150, seek_ms: null }), 100);
const t0 = Date.now();
out.grew = await S.withPacedTimeout(new Promise((r) => setTimeout(() => r('done'), 600)), 300, 'job', pace);
out.ms = Date.now() - t0;
// without a higher factor the same job times out, with the usual message
out.fixed = await S.withPacedTimeout(new Promise((r) => setTimeout(r, 600)), 300, 'job', S.newPace()).then(() => 'done', (e) => e.message);
// a factor never drops, and is capped at 5
S.notePace(pace, { factor: 1.5 }); out.kept = pace.factor;
S.notePace(pace, { factor: 9 }); out.capped = pace.factor;
// the record names the slowest page
out.summary = S.paceSummary([{ pace: { factor: 1, page: { frame_ms: 16, seek_ms: 40, ceiling: 5 } } },
  { pace: { factor: 2.4, page: { frame_ms: 120, seek_ms: 600, ceiling: 5 } } }, { pace: null }]);
out.none = S.paceSummary([]);
console.log(JSON.stringify(out));
""" % json.dumps(STAGEHOST))
        self.assertEqual(r["grew"], "done")
        self.assertGreaterEqual(r["ms"], 550)
        self.assertRegex(r["fixed"], r"^timed out after \d+s: job$")
        self.assertEqual(r["kept"], 3)
        self.assertEqual(r["capped"], 5)
        self.assertEqual(r["summary"], {"factor": 2.4, "frame_ms": 120, "seek_ms": 600, "ceiling": 5})
        self.assertEqual(r["none"]["factor"], 1)

    def test_pace_off(self):
        r = node("""
const S = await import(%s);
const pace = S.newPace();
S.notePace(pace, { factor: 4 });
console.log(JSON.stringify({ factor: pace.factor, summary: S.paceSummary([{ pace }]) }));
""" % json.dumps(STAGEHOST), env=dict(ENV, SHOWTIME_PACE="0"))
        self.assertEqual(r["factor"], 1)
        self.assertTrue(r["summary"].get("off"))


    # The guard's fake-browser runs (node only). Every wait is derived from stagehost's own SHOT_IDLE_MS under the test
    # scale: idle = SHOT_IDLE_MS x scale (each read of the browser's work may take that long too), a browser that
    # answers nothing is stuck once it has said nothing for 2 x idle, and the work is read every POLL_MS.
    GUARD_JS = """
const S = await import(%s);
const never = () => new Promise(() => {});
const fake = (send) => { const b = { sessions: 0, sends: 0 };
  b.newBrowserCDPSession = async () => { b.sessions++; return { send: async (m) => { b.sends++; return send(m); }, detach: async () => {} }; };
  return b; };
const rejects = () => { throw new Error("Protocol error (SystemInfo.getProcessInfo): 'SystemInfo.getProcessInfo' wasn't found"); };
const run = async (b, frame, cache) => { const t0 = Date.now();
  const o = await S.guardShot(frame, b, 'screenshot', S.newPace(), cache, %d).then((v) => ({ ok: v }), (e) => ({ err: e.message, stuck: !!e.browserStuck }));
  return { ...o, ms: Date.now() - t0 }; };
const out = { idle: S.baseWait(S.SHOT_IDLE_MS), cap: S.SHOT_MAX_MS };
"""
    POLL_MS = 50

    def guard(self, scale, cap_ms, body):
        return node((self.GUARD_JS % (json.dumps(STAGEHOST), self.POLL_MS)) + body + "\nconsole.log(JSON.stringify(out));\n",
                    env=dict(ENV, SHOWTIME_TEST_WAIT_SCALE=str(scale), SHOWTIME_SHOT_TIMEOUT=str(cap_ms / 1000),
                             SHOWTIME_PACE="1"))

    def test_stuck_frame_guard_browser_cannot_report_its_work(self):
        """The stuck-frame guard (stagehost guardShot) reads the browser's drawing work with CDP
        SystemInfo.getProcessInfo. A browser that ANSWERS WITH AN ERROR (an older headless shell without that method)
        cannot say what it is doing: the guard remembers it (cache.noWork), stops asking, and only the screenshot cap
        (SHOT_MAX_MS) applies; it never reads the silence as a stuck browser. One that does not answer at all is
        different: it is stuck once it has said nothing for twice the idle time. The CDP replies are faked, the waits
        shrunk (idle 30 s -> 0.3 s, polls every 50 ms). The cap (4 s) is far past the silent browser's verdict (about
        1.05 s: three unanswered reads of 0.3 s each): with a 2 s cap a loaded Windows runner's late timers reached
        the cap first (nightly 14 Oct)."""
        scale, cap_ms = 0.01, 4000
        idle = shot_idle_ms() * scale
        late_ms = int((2 * idle + cap_ms) / 2)   # well past twice the idle time, well before the cap
        r = self.guard(scale, cap_ms, """
// 1. the browser answers with an error and the frame never comes: only the cap ends it, not the idle rules
let b = fake(rejects), cache = {};
out.cap_run = await run(b, never(), cache);
out.cap_run.sessions = b.sessions; out.cap_run.sends = b.sends; out.cap_run.noWork = cache.noWork === true;
// 2. the same browser, a frame that comes late (past twice the idle time): it is not called stuck
b = fake(rejects); cache = {};
out.late = await run(b, new Promise((r) => setTimeout(() => r('frame'), %d)), cache);
out.late.noWork = cache.noWork === true;
// 3. a browser that does not answer: stuck after twice the idle time, long before the cap
b = fake(never); cache = {};
out.silent = await run(b, never(), cache);
out.silent.noWork = cache.noWork === true;
""" % late_ms)
        self.assertEqual((r["idle"], r["cap"]), (idle, cap_ms), r)   # the waits this test derives are the module's
        cap, late, silent = r["cap_run"], r["late"], r["silent"]
        # the cap's value exactly; the time it took (rounded, so a late tick may say a second more) is checked by ms
        self.assertRegex(cap["err"], r"^timed out after \d+s: screenshot \(still not there after %d s, the longest a "
                         r"screenshot may take\)$" % (cap_ms // 1000))
        self.assertTrue(cap["stuck"])
        self.assertGreaterEqual(cap["ms"], cap_ms - 100)   # not before the cap
        self.assertEqual((cap["sessions"], cap["sends"], cap["noWork"]), (1, 1, True), cap)   # asked once, then never again
        self.assertEqual(late["ok"], "frame", late)
        self.assertGreaterEqual(late["ms"], late_ms - 100, late)
        self.assertTrue(late["noWork"])
        self.assertRegex(silent["err"], r"\(the browser did not say what it was doing for \d+ s\)$")
        self.assertTrue(silent["stuck"])
        self.assertGreaterEqual(silent["ms"], 2 * idle - 100, silent)   # not before twice the idle time
        self.assertLess(silent["ms"], cap_ms - 100, silent)
        self.assertFalse(silent["noWork"])

    def test_stuck_frame_guard_names_the_stuck_browser_at_the_cap(self):
        """On a tick that finds both a browser silent for twice the idle time and the cap reached, the error names the
        silent browser, not the cap (the cap check came first: a busy machine's late tick, a cap set low, or a size
        read that used most of a shot's shared budget then got the less helpful reason). The browser does not
        answer; each unanswered read takes the idle time, so the reads end about (poll + idle) apart and the silence
        is known at the third. The cap falls between the second and the third (at 2.6 x (poll + idle)): it is
        reached on the tick that finds the silence, with 0.6 x (poll + idle) to spare for late timers before the
        second. Idle 6 s here (scale 0.2): 3.6 s to spare, over three times the late timers that ended the old cap
        test on a loaded Windows runner (at least about 1 s)."""
        scale = 0.2
        idle = shot_idle_ms() * scale
        step = self.POLL_MS + idle
        cap_ms = int(2.6 * step)
        r = self.guard(scale, cap_ms, """
const b = fake(never), cache = {};
out.both = await run(b, never(), cache);
""")
        self.assertEqual((r["idle"], r["cap"]), (idle, cap_ms), r)
        both = r["both"]
        self.assertRegex(both["err"], r"\(the browser did not say what it was doing for \d+ s\)$", both)
        self.assertTrue(both["stuck"])
        self.assertGreaterEqual(both["ms"], cap_ms - 100, both)   # the cap was reached on that tick too

    def test_no_frame_rate_limit_flag(self):
        """render's browsers draw on Chrome's own frame clock on macOS and Windows: with --disable-frame-rate-limit a
        renderer keeps spending CPU after the GPU process stops, so on macOS the stuck-frame guard never sees a stopped
        GPU process (the stall test fails with it on an Intel Mac), and it is the likely cause of the 0.4.1 stalls on
        the 3-thread macOS CI runners. Linux renders keep it (about 10 % faster): the guard ends a frame that never
        comes there with it on (TestFrameNeverComes). No other browser gets it."""
        flags = json.loads((SKILL / "scripts" / "lib" / "chrome-flags.json").read_text(encoding="utf-8"))
        every = [f for k, v in flags.items() if isinstance(v, list) for f in v] + \
                [f for v in flags["gpu"].values() for f in v]
        self.assertNotIn("--disable-frame-rate-limit", every)
        self.assertEqual({o: "--disable-frame-rate-limit" in flags["render"][o] for o in ("mac", "windows", "linux")},
                         {"mac": False, "windows": False, "linux": True})


class TestSlowPages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-pace-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_busy_frames_render_when_paced(self):
        proj = self.tmp / "busy"
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 10, "duration": 0.2, "background": "#202830"}))
        write(proj / "index.html", HEAD + "<style>body{margin:0;background:#202830}#box{position:absolute;left:40px;top:40px;"
              "width:120px;height:80px;background:#f4f4f4}</style></head><body><div id=\"box\"></div><script>" + BUSY_JS +
              "const box = document.getElementById('box');\n"
              "ST.onSeek((t) => { busy(3200); box.style.transform = 'translateX(' + Math.round(t * 200) + 'px)'; });"
              "</script></body></html>")
        env = dict(ENV, SHOWTIME_TEST_WAIT_SCALE="0.04")
        # the fixed waits: the seek deadline (2.4 s here, 60 s on a real machine) runs out on every try
        cp = showtime("render", proj, "-o", self.tmp / "fixed.mp4", "--no-check", "--workers", "1",
                      env=dict(env, SHOWTIME_PACE="0"))
        self.assertNotEqual(cp.returncode, 0, cp.stdout[-1500:])
        self.assertRegex(cp.stderr, r"timed out after \d+s: seek to")
        # paced: the first seek measured 3.2 s, so every wait is x5 (the ceiling) and the render finishes
        cp = showtime("render", proj, "-o", self.tmp / "paced.mp4", "--no-check", "--workers", "1", "--json", env=env)
        self.assertEqual(cp.returncode, 0, cp.stderr[-3000:])
        rep = json.loads(cp.stdout)
        self.assertEqual(rep["frames"], 2)
        self.assertEqual(rep["pace"]["factor"], 5, rep["pace"])
        self.assertGreaterEqual(rep["pace"]["seek_ms"], 3000)
        log = Path(rep["log"]).read_text(encoding="utf-8")
        self.assertIn("waits x5 for this page's pace", log)

    def test_slow_gate_ready_when_paced(self):
        proj = self.tmp / "gate"
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 10, "duration": 1, "background": "#202830"}))
        # The gate's deadline starts when ST.ready() reaches the gates, not when the gate starts. A gate that started
        # while the page parsed had done some of its work by then, as much as the host's calls between the first
        # load and ST.ready() took (each waits for a 200 ms piece: 5 on a Mac, 2 more on a busy Windows runner, where
        # 3 s of work in 200 ms pieces then fit the fixed 1.8 s and the fixed run passed). Started by ST.ready() itself,
        # one piece is done before its deadline starts on any machine: 4 s of work in 400 ms pieces leaves 3.6 s,
        # twice the fixed wait, and frames 150-200 ms apart make it x3-4 paced (5.4-7.2 s).
        write(proj / "index.html", HEAD + "</head><body><script>" + BUSY_JS +
              "let go; const started = new Promise((r) => { go = r; });\n"
              "const ready = ST.ready; ST.ready = function (o) { go(); return ready.call(this, o); };\n"
              "ST.waitFor(started.then(async () => { for (let k = 0; k < 10; k++) { busy(400); await new Promise((r) => setTimeout(r, 0)); } }), 'heavy init');\n"
              "ST.onSeek(() => {});</script></body></html>")
        code = """
const S = await import(%s);
const { startServer } = await import(%s);
const server = await startServer({ root: %s, port: 0 });
const b = await S.openBrowser({});
let out;
try {
  const sess = await S.openStage(b.browser, { url: server.url, page: 'index.html', config: { width: 320, height: 180, fps: 10, duration: 1 } });
  out = { ok: true, pace: sess.info.pace, factor: sess.pace.factor };
  await sess.close();
} catch (e) { out = { ok: false, error: String(e.message || e) }; }
await b.browser.close();
console.log(JSON.stringify(out));
process.exit(0);
""" % (json.dumps(STAGEHOST), json.dumps(SERVER), json.dumps(str(proj)))
        env = dict(ENV, SHOWTIME_TEST_WAIT_SCALE="0.03")     # the gate gets 1.8 s (60 s on a real machine)
        fixed = node(code, env=dict(env, SHOWTIME_PACE="0"))
        self.assertFalse(fixed["ok"], fixed)
        self.assertIn("heavy init", fixed["error"])
        paced = node(code, env=env)
        self.assertTrue(paced["ok"], paced)
        self.assertGreater(paced["pace"]["frame_ms"], 50, paced)
        self.assertGreater(paced["factor"], 1, paced)

    def test_first_page_open_deadline(self):
        """render's first page has the workers' page-open deadline (5 min; SHOWTIME_TEST_OPEN_TIMEOUT shortens
        it): a browser that never answers while it opens the page is given up, the page tried once more in a new
        browser, and then the render fails with the deadline instead of waiting with none (the first page and
        the WebGL probe had no deadline of their own)."""
        proj = self.tmp / "slowopen"
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 10, "duration": 0.5, "background": "#202830"}))
        write(proj / "index.html", HEAD + "</head><body><script>"
              "ST.waitFor(new Promise((r) => setTimeout(r, 20000)), 'slow open');\n"
              "ST.onSeek(() => {});</script></body></html>")
        cp = showtime("render", proj, "-o", self.tmp / "slowopen.mp4", "--no-check", "--workers", "1",
                      env=dict(ENV, SHOWTIME_TEST_OPEN_TIMEOUT="3"), timeout=300)
        self.assertNotEqual(cp.returncode, 0, cp.stdout[-1500:])
        self.assertIn("trying once more in a new browser", cp.stderr)
        self.assertEqual(cp.stderr.count("trying once more"), 1, cp.stderr[-2000:])
        # the deadline is x the page's pace (a busy runner's frames raise it while the page waits)
        self.assertRegex(cp.stderr, r"timed out after \d+s( \(x[\d.]+ for this page's pace\))?: opening the page")
        # names the step (on a fast machine the page's own 20 s wait; a slow one may still be setting the tab up)
        self.assertRegex(cp.stderr, STUCK_AT)

    def slow_open_project(self, name):
        proj = self.tmp / name
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 10, "duration": 0.5, "background": "#202830"}))
        write(proj / "index.html", HEAD + "</head><body><script>"
              "ST.waitFor(new Promise((r) => setTimeout(r, 20000)), 'slow open');\n"
              "ST.onSeek(() => {});</script></body></html>")
        return proj

    def test_check_open_deadline(self):
        """check opens its pages the way render does (stagehost openGuarded): the page-open deadline, once more in
        a new browser, then an error naming the step it was stuck at; never a check that does not return (a
        macOS CI runner's check outlived its caller's 5 minutes)."""
        proj = self.slow_open_project("slowcheck")
        cp = showtime("check", proj, "--json", "--no-determinism", "--no-timeline", "--no-history", "--samples", "2",
                      env=dict(ENV, SHOWTIME_TEST_OPEN_TIMEOUT="3"), timeout=300)
        self.assertNotEqual(cp.returncode, 0, cp.stdout[-1500:])
        self.assertEqual(cp.stderr.count("trying once more in a new browser"), 1, cp.stderr[-2000:])
        self.assertIn("the browser stopped answering", cp.stderr)
        # names the step (on a fast machine the page's own 20 s wait; a slow one may still be setting the tab up)
        self.assertRegex(cp.stderr, STUCK_AT)
        self.assertIn("in a new browser too", cp.stderr)

    def test_load_that_never_finishes_is_the_page(self):
        """A page whose load never reaches DOMContentLoaded (a parser-blocking script from a local server that never
        answers) fails as the page: check's ready_failed finding with a report, at the page's load deadline
        (PAGE_LOAD_MS, 3/5 of the page-open deadline: 18 s here), never as a stuck browser killed and tried again
        with no report (a load with no deadline of its own ran into the page-open deadline twice)."""
        with hanging_server() as port:
            proj = self.tmp / "neverloads"
            write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 10, "duration": 1, "background": "#202830"}))
            write(proj / "index.html", HEAD + '<script src="http://127.0.0.1:%d/never.js"></script></head><body>'
                  "<script>ST.onSeek(() => {});</script></body></html>" % port)
            t0 = time.time()
            cp = showtime("check", proj, "--json", "--no-determinism", "--no-timeline", "--no-history", "--samples", "2",
                          env=dict(ENV, SHOWTIME_TEST_OPEN_TIMEOUT="30"), timeout=300)
            took = time.time() - t0
        self.assertTrue(cp.stdout.strip(), "check printed no report (rc=%d):\n%s" % (cp.returncode, cp.stderr[-2000:]))
        rep = json.loads(cp.stdout)
        ready = [f for f in rep["findings"] if f["code"] == "ready_failed"]
        self.assertEqual(len(ready), 1, rep["findings"])
        self.assertIn("could not open", ready[0]["message"])
        self.assertNotIn("the browser stopped answering", cp.stderr)
        self.assertNotIn("trying once more", cp.stderr)
        self.assertLess(took, 120, cp.stderr[-1500:])

    def test_second_page_load_is_a_finding(self):
        """check's second pages (the determinism load, the cut walk, the no-GPU probe) whose load never finishes stay
        soft findings: the first page loads its script, every later load waits for ever, and check reports it
        (cut_probe_failed, determinism_incomplete) and finishes instead of ending with a stuck browser."""
        with hanging_server(answer_first=True) as port:
            proj = self.tmp / "secondhangs"
            write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 10, "duration": 1, "background": "#202830"}))
            write(proj / "index.html", HEAD + '<script src="http://127.0.0.1:%d/once.js"></script></head><body style="margin:0;'
                  'background:#234"><h1 style="color:#fff;font:40px sans-serif">Hi</h1>'
                  "<script>ST.onSeek(() => {});</script></body></html>" % port)
            cp = showtime("check", proj, "--json", "--no-timeline", "--no-history", "--samples", "2",
                          env=dict(ENV, SHOWTIME_TEST_OPEN_TIMEOUT="30"), timeout=400)
        self.assertTrue(cp.stdout.strip(), "check printed no report (rc=%d):\n%s" % (cp.returncode, cp.stderr[-2000:]))
        rep = json.loads(cp.stdout)
        soft = [f for f in rep["findings"] if f["code"] in ("cut_probe_failed", "determinism_incomplete")]
        self.assertTrue(soft, [(f["code"], f["message"][:120]) for f in rep["findings"]])
        for f in soft:
            self.assertIn(f["severity"], ("info", "warning"), f)
            self.assertIn("could not open", f["message"])
        self.assertNotIn("the browser stopped answering", cp.stderr)

    @unittest.skipIf(sys.platform == "win32", "SIGSTOP is POSIX")
    def test_check_stopped_browser(self):
        """A browser that really stops answering (SIGSTOP, SHOWTIME_TEST_STOP_BROWSER): stopped before the first
        page opens, check gives it up at the deadline, kills it and finishes in a new browser; stopped after the
        image lab page opened, the watchdog ends check with an error naming its last step. Each returns in under 120 s
        (about 25 s on a quiet Mac) and leaves no stopped browser of its own behind.
        The open deadline is 20 s here, not 3 s: a stopped browser never answers, so any deadline finds it and a
        longer one only costs that wait; the healthy browser that replaces it must open its page inside the same
        deadline, and on a busy macOS CI runner a fresh browser took over 3 s just to create its context and tab
        (the 0.4.2 release PR). The page's own load gets 3/5 of it (PAGE_LOAD_MS: 1.8 s at 3 s, 12 s here), and the
        watchdog pings the healthy browser with the same deadline. One value on every machine, so a local run is
        the CI run."""
        proj = self.tmp / "stopped"
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 10, "duration": 1, "background": "#202830"}))
        write(proj / "index.html", HEAD + "</head><body style=\"margin:0;background:#234\"><h1 style=\"color:#fff;"
              "font:40px sans-serif\">Hi</h1><script>ST.onSeek(() => {});</script></body></html>")
        args = ("check", proj, "--json", "--no-determinism", "--no-timeline", "--no-history", "--samples", "2")
        own = own_tmp(self.tmp / "stopped-tmp")
        env = dict(ENV, SHOWTIME_TEST_OPEN_TIMEOUT="20", TMPDIR=own, TEMP=own, TMP=own)
        t0 = time.time()
        cp1, groups = run_watching(args, dict(env, SHOWTIME_TEST_STOP_BROWSER="open"), own, 180)
        took1 = time.time() - t0
        self.assertEqual(cp1.returncode, 0, cp1.stderr[-2000:])
        self.assertTrue(json.loads(cp1.stdout)["ok"], cp1.stdout[-1500:])
        self.assertEqual(cp1.stderr.count("trying once more in a new browser"), 1, cp1.stderr[-2000:])
        # the browser is stopped before its first page opens, so the step is always the first one
        self.assertIn("stuck at: creating the browser context", cp1.stderr)
        # the 20 s deadline, a new browser and a short check: never the 180 s the subprocess may take
        self.assertLess(took1, 120, cp1.stderr[-1500:])
        t0 = time.time()
        cp2, g2 = run_watching(args, dict(env, SHOWTIME_TEST_STOP_BROWSER="ready:2"), own, 180)
        took2 = time.time() - t0
        groups |= g2
        self.assertEqual(cp2.returncode, 1, cp2.stderr[-2000:])
        self.assertIn("the browser stopped answering", cp2.stderr)
        self.assertIn("check's last step: opened the image lab page", cp2.stderr)
        # two pages opened, then the watchdog: a ping every 5 s, each with the 20 s deadline
        self.assertLess(took2, 120, cp2.stderr[-1500:])
        # The stuck browser is killed (SIGKILL to its process group, which a stopped process cannot ignore) as check
        # ends; on a busy machine ps can still list it for a moment, so it is asked again for up to 10 s before that
        # counts as left behind. Only this test's own browsers count (own_tmp, run_watching).
        for _ in range(20):
            left = own_stopped(own, groups)
            if not left:
                break
            time.sleep(0.5)
        self.assertEqual(left, [], "a stopped browser was left behind: %s\nfirst check's stderr:\n%s\nsecond check's "
                         "stderr:\n%s" % (describe(left), cp1.stderr[-1500:], cp2.stderr[-1500:]))


class TestSizeReadWaitsForTheFrame(unittest.TestCase):
    """A clipped screenshot (check's timeline and thumbnails, render's --preview and --scale below 1) first reads the
    page's layout size (issue #49). That read is the first call on the page's main thread after a seek, so it waits
    for the frame the seek drew: without a GPU, while SwiftShader draws a WebGL frame in the GPU process (the seek
    itself returns in milliseconds, so the page's pace stays 1). It had a flat 60 s and ended check on a 4-core CI
    runner without a GPU ("timed out after 60s: reading the page's size", issue #14). It is now guarded like the
    screenshot it belongs to (guardShot): waited for while the browser's drawing processes work, failed once they do
    nothing. Here a renderer kept busy past the old deadline stands in for the GPU process at work, and a stopped
    renderer for a page that is truly stuck.

    The busy page runs at SHOWTIME_TEST_WAIT_SCALE=0.25 (15 s for the old 60 s, x the page's pace). The scale also
    shrinks what the guard allows the browser to answer it (SystemInfo.getProcessInfo): one read may take the idle
    time (SHOT_IDLE_MS x scale) and a browser silent for twice that is stuck. At 0.05 that was 1.5 s and 3 s, and on
    a loaded Windows runner two late answers ended a busy read as "the browser did not say what it was doing"
    (nightly 14 Oct); on a real machine they are 15 s and 60 s. At 0.25 they are 7.5 s and 15 s: reads every 5 s
    start at 5 s, so the browser cannot be found silent before about 27 s, after the page lets go. The stopped page
    keeps 0.05 (it fails in seconds: the idle window is 1.5 s)."""

    OLD_READ_MS = 60000   # the read's flat deadline before guardShot (x the page's pace)
    BUSY_MARGIN_MS = 5000   # the page is held this long past the old deadline

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-sizeread-"))
        cls.proj = cls.tmp / "p"
        write(cls.proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 10, "duration": 1, "background": "#202830"}))
        write(cls.proj / "index.html", HEAD + "</head><body style=\"margin:0;background:#202830\"><div id=\"box\" style=\""
              "position:absolute;left:40px;top:40px;width:120px;height:80px;background:#f4f4f4\"></div><script>" + BUSY_JS +
              "const box = document.getElementById('box');\n"
              "ST.onSeek((t) => { box.style.transform = 'translateX(' + Math.round(t * 100) + 'px)'; });"
              "</script></body></html>")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def run_shot(self, stop, scale):
        # the main thread is held right after the seek returns (a task queued by a call that returns at once, not
        # onSeek, which would hold the seek itself and raise the page's pace), then a clipped screenshot is taken;
        # it is held past the old deadline at the pace the page measured (the pace does not change after the seek)
        code = """
const S = await import(%s);
const { startServer } = await import(%s);
const server = await startServer({ root: %s, port: 0 });
const b = await S.openBrowser({});
const stop = %s;
let out, extra = {}, stopped = [];
try {
  const sess = await S.openStage(b.browser, { url: server.url, page: 'index.html', config: { width: 320, height: 180, fps: 10, duration: 1 } });
  await sess.seek(0.5);
  const old = S.baseWait(%d) * sess.pace.factor, hold = old + %d;
  extra = { old, hold, idle: S.baseWait(S.SHOT_IDLE_MS), pace: sess.pace.factor };
  await sess.page.evaluate((ms) => { setTimeout(() => busy(ms), 0); return true; }, hold);
  if (stop) {
    const cdp = await b.browser.newBrowserCDPSession();
    const info = await cdp.send('SystemInfo.getProcessInfo');
    stopped = info.processInfo.filter((p) => p.type === 'renderer').map((p) => p.id);
    for (const pid of stopped) process.kill(pid, 'SIGSTOP');
  }
  const t0 = Date.now();
  try {
    const img = await sess.shot({ format: 'jpeg', scale: 0.5 });
    out = { ok: true, ms: Date.now() - t0, size: S.imageSize(img) };
  } catch (e) { out = { ok: false, ms: Date.now() - t0, error: String(e.message || e) }; }
  out = { ...out, ...extra };
  for (const pid of stopped) { try { process.kill(pid, 'SIGCONT'); } catch {} }
  await sess.close();
} catch (e) { out = { ok: false, error: 'setup: ' + String(e.message || e) }; }
for (const pid of stopped) { try { process.kill(pid, 'SIGCONT'); } catch {} }
await S.closeSoon(b.browser.close());
await server.close().catch(() => {});
console.log(JSON.stringify(out));
process.exit(0);
""" % (json.dumps(STAGEHOST), json.dumps(SERVER), json.dumps(str(self.proj)), "true" if stop else "false",
       self.OLD_READ_MS, self.BUSY_MARGIN_MS)
        # the hold is at most 5 x the old deadline (the pace's ceiling) plus the margin; the rest is the browser
        timeout = int(5 * self.OLD_READ_MS * scale / 1000 + self.BUSY_MARGIN_MS / 1000) + 150
        return node(code, env=dict(ENV, SHOWTIME_TEST_WAIT_SCALE=str(scale)), timeout=timeout)

    def test_busy_page_is_waited_for(self):
        """The read waits out a main thread held past the old deadline (15 s x the page's pace here, 60 s x pace on
        a real machine) by 5 s, because the renderer keeps working. On the CI runners the pace stays 1 (the seek is
        fast: a 20 s hold); a slow runner's page may measure more, and the old deadline and the hold grow with it."""
        scale = 0.25
        r = self.run_shot(stop=False, scale=scale)
        self.assertEqual((r.get("old"), r.get("idle")), (self.OLD_READ_MS * scale * r.get("pace", 1),
                                                         shot_idle_ms() * scale), r)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["size"], [160, 90], r)
        self.assertGreater(r["ms"], r["old"], r)   # past the old deadline at the page's pace
        self.assertGreaterEqual(r["ms"], r["hold"] - 2000, r)   # the read ended with the hold, not before

    @unittest.skipIf(sys.platform == "win32", "SIGSTOP is POSIX")
    def test_stopped_page_still_fails(self):
        """A renderer that does no work at all (stopped) still fails the read, as a stuck screenshot does (#24), in
        seconds here (the idle window is 1.5 s at this scale, read every 5 s), naming the step."""
        r = self.run_shot(stop=True, scale=0.05)
        self.assertFalse(r["ok"], r)
        self.assertRegex(r["error"], r"timed out after \d+s: reading the page's size " + STUCK_FRAME)
        self.assertLess(r["ms"], 60000, r)


class hanging_server:
    """A local HTTP server whose requests never get an answer (answer_first: the first one gets a small script, every
    later one waits): a page load that never reaches DOMContentLoaded. -> its port"""

    def __init__(self, answer_first=False):
        self.answer_first = answer_first
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.held = []
        self.done = False

    def serve(self):
        n = 0
        while not self.done:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            self.held.append(c)
            try:
                c.settimeout(5)
                c.recv(65536)
            except OSError:
                continue
            n += 1
            if self.answer_first and n == 1:
                body = b"window.__once = 1;"
                c.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/javascript\r\nCache-Control: no-store\r\n"
                          b"Connection: close\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))
                c.close()

    def __enter__(self):
        threading.Thread(target=self.serve, daemon=True).start()
        return self.sock.getsockname()[1]

    def __exit__(self, *exc):
        self.done = True
        for c in self.held:
            try:
                c.close()
            except OSError:
                pass
        self.sock.close()


# Stopped browsers left behind: only this test's own count. Another run on the same machine (a second agent, a
# parallel test file) stops browsers too, so a machine-wide scan of stopped Chromes failed this file for processes it
# never started. Each run gets a TMPDIR of its own (own_tmp), which every browser it launches names in its profile
# (--user-data-dir); while the command runs, the process groups of those browsers are noted too (run_watching), as a
# browser's helper processes keep its group but need not name the profile.
def own_tmp(base):
    """A TMPDIR for one command's browsers (resolved: the profile path in their command lines is this one)."""
    d = Path(os.path.realpath(str(base)))
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


def ps_rows():
    """Every process: (pid, ppid, pgid, stat, etime, command)."""
    out = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,stat=,etime=,command="], stdout=subprocess.PIPE,
                         encoding="utf-8", errors="replace").stdout
    return [tuple(f) for f in (l.split(None, 5) for l in out.splitlines()) if len(f) == 6]


def run_watching(args, env, tag, timeout):
    """showtime(*args), noting every 0.5 s while it runs the process groups of the processes that name tag.
    -> (CompletedProcess, {pgid})"""
    p = subprocess.Popen([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, encoding="utf-8", errors="replace")
    groups, t0 = set(), time.time()
    while True:
        try:
            out, err = p.communicate(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            groups |= {r[2] for r in ps_rows() if tag in r[5]}
            if time.time() - t0 > timeout:
                p.kill()
                p.communicate()
                raise
    return subprocess.CompletedProcess(p.args, p.returncode, out, err), groups


def own_stopped(tag, groups, kind=None):
    """This run's processes in state T (stopped): they name tag or are in one of its browsers' groups; kind: a
    substring of the command line (e.g. --type=gpu-process). -> [row]"""
    return [r for r in ps_rows() if r[3].startswith("T") and (tag in r[5] or r[2] in groups) and (kind is None or kind in r[5])]


def describe(rows):
    """pid, ppid, etime and profile of each process, for an assertion message (the command lines are too long)."""
    def udd(cmd):
        m = re.search(r"--user-data-dir=(\S+)", cmd)
        return m.group(1) if m else "(no --user-data-dir)"
    return "; ".join("pid %s ppid %s pgid %s stat %s etime %s %s %s" % (r[0], r[1], r[2], r[3], r[4],
                     (re.search(r"--type=\S+", r[5]) or ["main"])[0], udd(r[5])) for r in rows)


@unittest.skipIf(sys.platform == "win32", "SIGSTOP is POSIX")
class TestFrameNeverComes(unittest.TestCase):
    """A frame that never comes: the browser's GPU process stopped (SIGSTOP, SHOWTIME_TEST_STOP_GPU=shot:N) just before
    the N-th screenshot, as the virtual GPU of the macOS CI runners stalled now and then. Before 0.4.1's fix render
    waited a flat 10 minutes for that screenshot (then drew it again in a new browser) and check waited for ever:
    both outlived their callers (a test file's 15 minutes, test_motion's 10) with no word on where they were."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-nevercomes-"))
        cls.proj = cls.tmp / "gl"
        # a WebGL canvas drawn on every seek: its pixels come from the GPU process with or without a GPU (SwiftShader)
        write(cls.proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 10, "duration": 2, "background": "#202830"}))
        write(cls.proj / "index.html", HEAD + "</head><body style=\"margin:0;background:#202830\">"
              "<canvas id=\"c\" width=\"320\" height=\"180\"></canvas><script>"
              "const gl = document.getElementById('c').getContext('webgl', { preserveDrawingBuffer: true });\n"
              "ST.onSeek((t) => { gl.clearColor(t / 2, 0.3, 1 - t / 2, 1); gl.clear(gl.COLOR_BUFFER_BIT); });"
              "</script></body></html>")
        cls.own = own_tmp(cls.tmp / "tmp")
        cls.env = dict(ENV, TMPDIR=cls.own, TEMP=cls.own, TMP=cls.own)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def injected(self, cp):
        # the test switch says when it stopped a GPU process; a browser without one cannot show this
        if "stopped the GPU process before screenshot" not in cp.stderr:
            self.skipTest("this browser has no GPU process to stop: " + cp.stderr[-300:])

    def sh(self, *args, timeout, **extra):
        """showtime(*args) in this class's own TMPDIR, noting its browsers' process groups (for assertNoStoppedGpu)."""
        cp, self.groups = run_watching(args, dict(self.env, **extra), self.own, timeout)
        return cp

    def assertNoStoppedGpu(self, cp):
        # the stuck browser is killed as the command ends; on a busy machine ps can still list its stopped GPU process
        # for a moment, so it is asked again for up to 10 s before that counts as left behind. Only this run's own.
        for _ in range(20):
            time.sleep(0.5)
            left = own_stopped(self.own, self.groups, "--type=gpu-process")
            if not left:
                break
        self.assertEqual(left, [], "a stopped GPU process was left behind: %s\nthe command's stderr:\n%s"
                         % (describe(left), cp.stderr[-2000:]))

    def test_render_draws_the_frame_again(self):
        """The screenshot fails once the GPU process and the renderers have done no work for 30 s (x the page's
        pace), the frame is drawn again in a new browser (the stuck one killed), and the render finishes with every
        frame and the retry in render.json."""
        t0 = time.time()
        cp = self.sh("render", self.proj, "-o", self.tmp / "render.mp4", "--no-check", "--workers", "1", "--no-audio",
                      "--poster", "none", "--json", SHOWTIME_TEST_STOP_GPU="shot:6", timeout=400)
        took = time.time() - t0
        self.injected(cp)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        rep = json.loads(cp.stdout)
        self.assertEqual(rep["frames"], 20)
        self.assertEqual(rep["capture"]["retries"], 1, rep["capture"])
        self.assertRegex(cp.stderr, r"timed out after \d+s: screenshot at 0\.500s " + STUCK_FRAME + r"; retrying")
        # 30 s x the pace (5 at most) and a new browser: never the 10 minutes it was
        self.assertLess(took, 300, cp.stderr[-1500:])
        self.assertNoStoppedGpu(cp)

    def test_check_ends_with_its_step(self):
        """check's screenshots had no deadline (its watchdog pings the browser process, which answers while the
        frame never comes): check now ends with an error naming the screenshot and its last step."""
        cp = self.sh("check", self.proj, "--json", "--no-determinism", "--no-timeline", "--no-history", "--samples", "2",
                      SHOWTIME_TEST_STOP_GPU="shot:1", timeout=400)
        self.injected(cp)
        self.assertEqual(cp.returncode, 1, cp.stderr[-2000:])
        self.assertRegex(cp.stderr, r"the browser stopped drawing: timed out after \d+s: screenshot " + STUCK_FRAME +
                         r"; check's last step: \S")
        self.assertNoStoppedGpu(cp)

    def test_command_timeout_names_the_step(self):
        """SHOWTIME_TIMEOUT (the caller's limit) ends a render that is still waiting with an error naming where each of
        its parts is, in its log too, and its browsers go with it. The waits are stretched (x3: the stuck screenshot
        gets 90 s) so the 50 s limit comes first on a slow runner too."""
        out = self.tmp / "limit.mp4"
        t0 = time.time()
        cp = self.sh("render", self.proj, "-o", out, "--no-check", "--workers", "1", "--no-audio", "--poster", "none",
                      SHOWTIME_TEST_STOP_GPU="shot:6", SHOWTIME_TIMEOUT="50", SHOWTIME_TEST_WAIT_SCALE="3", timeout=200)
        took = time.time() - t0
        self.injected(cp)
        self.assertEqual(cp.returncode, 1, cp.stderr[-2000:])
        m = re.search(r"did not finish within 50 s \(SHOWTIME_TIMEOUT\); stuck at: (.+)", cp.stderr)
        self.assertTrue(m, cp.stderr[-2000:])
        self.assertRegex(m.group(1), r"worker 0: screenshot at 0\.500s \(\d+ s\)")
        self.assertRegex(m.group(1), r"main: waiting for the workers \(\d+ s\)")
        self.assertLess(took, 90)
        log = (self.tmp / "limit.work" / "logs" / "render.log").read_text(encoding="utf-8")
        self.assertIn("error: did not finish within 50 s (SHOWTIME_TIMEOUT); stuck at: ", log)
        self.assertNoStoppedGpu(cp)


if __name__ == "__main__":
    unittest.main(argv=[a for a in sys.argv if a != "--fast"])

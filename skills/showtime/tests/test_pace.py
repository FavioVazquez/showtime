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
  * the stuck-frame guard on a browser that cannot report its work (CDP replies faked, node only): one whose
    SystemInfo.getProcessInfo answers with an error is asked once and then only the screenshot cap applies, a late
    frame still comes through; one that does not answer at all is stuck after twice the idle time
  * only Linux render browsers have --disable-frame-rate-limit (with it a renderer keeps working after the GPU
    process stops, so on macOS the guard never sees the stop; likely what stalled the macOS CI runners in 0.4.1)

Needs a browser. usage: python tests/test_pace.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import re
import shutil
import subprocess
import sys
import tempfile
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


STUCK_AT = (r"stuck at: (creating the browser context|opening a tab|setting up the tab|loading the page|"
            r"waiting for the page to be ready)")


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


    def test_stuck_frame_guard_browser_cannot_report_its_work(self):
        """The stuck-frame guard (stagehost guardShot) reads the browser's drawing work with CDP
        SystemInfo.getProcessInfo. A browser that ANSWERS WITH AN ERROR (an older headless shell without that method)
        cannot say what it is doing: the guard remembers it (cache.noWork), stops asking, and only the screenshot cap
        (SHOT_MAX_MS) applies; it never reads the silence as a stuck browser. One that does not answer at all is
        different: it is stuck once it has said nothing for twice the idle time. The CDP replies are faked, the waits
        shrunk (idle 30 s -> 0.3 s, polls every 50 ms, cap 2 s)."""
        r = node("""
const S = await import(%s);
const never = () => new Promise(() => {});
const fake = (send) => { const b = { sessions: 0, sends: 0 };
  b.newBrowserCDPSession = async () => { b.sessions++; return { send: async (m) => { b.sends++; return send(m); }, detach: async () => {} }; };
  return b; };
const rejects = () => { throw new Error("Protocol error (SystemInfo.getProcessInfo): 'SystemInfo.getProcessInfo' wasn't found"); };
const run = async (b, frame, cache) => { const t0 = Date.now();
  const o = await S.guardShot(frame, b, 'screenshot', S.newPace(), cache, 50).then((v) => ({ ok: v }), (e) => ({ err: e.message, stuck: !!e.browserStuck }));
  return { ...o, ms: Date.now() - t0 }; };
const out = {};
// 1. the browser answers with an error and the frame never comes: only the cap ends it, not the idle rules
let b = fake(rejects), cache = {};
out.cap = await run(b, never(), cache);
out.cap.sessions = b.sessions; out.cap.sends = b.sends; out.cap.noWork = cache.noWork === true;
// 2. the same browser, a frame that comes late (well past twice the idle time, 0.6 s): it is not called stuck
b = fake(rejects); cache = {};
out.late = await run(b, new Promise((r) => setTimeout(() => r('frame'), 1400)), cache);
out.late.noWork = cache.noWork === true;
// 3. a browser that does not answer: stuck after twice the idle time, long before the cap
b = fake(never); cache = {};
out.silent = await run(b, never(), cache);
out.silent.noWork = cache.noWork === true;
console.log(JSON.stringify(out));
""" % json.dumps(STAGEHOST), env=dict(ENV, SHOWTIME_TEST_WAIT_SCALE="0.01", SHOWTIME_SHOT_TIMEOUT="2", SHOWTIME_PACE="1"))
        cap, late, silent = r["cap"], r["late"], r["silent"]
        self.assertRegex(cap["err"], r"^timed out after 2s: screenshot \(still not there after 2 s, the longest a screenshot may take\)$")
        self.assertTrue(cap["stuck"])
        self.assertGreaterEqual(cap["ms"], 1900)   # not before the cap
        self.assertEqual((cap["sessions"], cap["sends"], cap["noWork"]), (1, 1, True), cap)   # asked once, then never again
        self.assertEqual(late["ok"], "frame", late)
        self.assertTrue(late["noWork"])
        self.assertRegex(silent["err"], r"\(the browser did not say what it was doing for \d+ s\)$")
        self.assertTrue(silent["stuck"])
        self.assertLess(silent["ms"], 1900)
        self.assertFalse(silent["noWork"])

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

    @unittest.skipIf(sys.platform == "win32", "SIGSTOP is POSIX")
    def test_check_stopped_browser(self):
        """A browser that really stops answering (SIGSTOP, SHOWTIME_TEST_STOP_BROWSER): stopped before the first
        page opens, check gives it up at the deadline, kills it and finishes in a new browser; stopped after the
        image lab page opened, the watchdog ends check with an error naming its last step. Both return in seconds
        (the open deadline is 3 s here) and leave no stopped browser behind."""
        proj = self.tmp / "stopped"
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 10, "duration": 1, "background": "#202830"}))
        write(proj / "index.html", HEAD + "</head><body style=\"margin:0;background:#234\"><h1 style=\"color:#fff;"
              "font:40px sans-serif\">Hi</h1><script>ST.onSeek(() => {});</script></body></html>")
        args = ("check", proj, "--json", "--no-determinism", "--no-timeline", "--no-history", "--samples", "2")
        env = dict(ENV, SHOWTIME_TEST_OPEN_TIMEOUT="3")
        before = {l for l in subprocess.run(["ps", "-axo", "stat=,command="], stdout=subprocess.PIPE, encoding="utf-8",
                                            errors="replace").stdout.splitlines() if l.strip().startswith("T")}
        cp = showtime(*args, env=dict(env, SHOWTIME_TEST_STOP_BROWSER="open"), timeout=180)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        self.assertTrue(json.loads(cp.stdout)["ok"], cp.stdout[-1500:])
        self.assertEqual(cp.stderr.count("trying once more in a new browser"), 1, cp.stderr[-2000:])
        self.assertIn("stuck at: ", cp.stderr)
        cp = showtime(*args, env=dict(env, SHOWTIME_TEST_STOP_BROWSER="ready:2"), timeout=180)
        self.assertEqual(cp.returncode, 1, cp.stderr[-2000:])
        self.assertIn("the browser stopped answering", cp.stderr)
        self.assertIn("check's last step: opened the image lab page", cp.stderr)
        ps = subprocess.run(["ps", "-axo", "stat=,command="], stdout=subprocess.PIPE, encoding="utf-8", errors="replace").stdout
        # the run's browsers hold a temp profile (--user-data-dir) of their own; the command line never names the
        # project, so a stopped (state T) Chrome after the run is any stopped Chrome that was not stopped before
        stopped = [l for l in ps.splitlines() if l.strip().startswith("T") and "--user-data-dir" in l and "chrom" in l.lower()]
        self.assertEqual([l for l in stopped if l not in before], [], "a stopped browser was left behind")


def stopped_gpu_processes():
    """Chrome GPU processes in state T (stopped) on this machine."""
    ps = subprocess.run(["ps", "-axo", "pid=,stat=,command="], stdout=subprocess.PIPE, encoding="utf-8", errors="replace").stdout
    return {l.split()[0] for l in ps.splitlines() if len(l.split()) > 2 and l.split()[1].startswith("T") and "--type=gpu-process" in l}


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
        cls.stopped_before = stopped_gpu_processes()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def injected(self, cp):
        # the test switch says when it stopped a GPU process; a browser without one cannot show this
        if "stopped the GPU process before screenshot" not in cp.stderr:
            self.skipTest("this browser has no GPU process to stop: " + cp.stderr[-300:])

    def assertNoStoppedGpu(self):
        time.sleep(1)
        self.assertEqual(stopped_gpu_processes() - self.stopped_before, set(), "a stopped GPU process was left behind")

    def test_render_draws_the_frame_again(self):
        """The screenshot fails once the GPU process and the renderers have done no work for 30 s (x the page's
        pace), the frame is drawn again in a new browser (the stuck one killed), and the render finishes with every
        frame and the retry in render.json."""
        t0 = time.time()
        cp = showtime("render", self.proj, "-o", self.tmp / "render.mp4", "--no-check", "--workers", "1", "--no-audio",
                      "--poster", "none", "--json", env=dict(ENV, SHOWTIME_TEST_STOP_GPU="shot:6"), timeout=400)
        took = time.time() - t0
        self.injected(cp)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        rep = json.loads(cp.stdout)
        self.assertEqual(rep["frames"], 20)
        self.assertEqual(rep["capture"]["retries"], 1, rep["capture"])
        self.assertRegex(cp.stderr, r"timed out after \d+s: screenshot at 0\.500s \(its GPU process and renderers did no work "
                                    r"for \d+ s: the frame is not coming\); retrying")
        # 30 s x the pace (5 at most) and a new browser: never the 10 minutes it was
        self.assertLess(took, 300, cp.stderr[-1500:])
        self.assertNoStoppedGpu()

    def test_check_ends_with_its_step(self):
        """check's screenshots had no deadline (its watchdog pings the browser process, which answers while the
        frame never comes): check now ends with an error naming the screenshot and its last step."""
        cp = showtime("check", self.proj, "--json", "--no-determinism", "--no-timeline", "--no-history", "--samples", "2",
                      env=dict(ENV, SHOWTIME_TEST_STOP_GPU="shot:1"), timeout=400)
        self.injected(cp)
        self.assertEqual(cp.returncode, 1, cp.stderr[-2000:])
        self.assertRegex(cp.stderr, r"the browser stopped drawing: timed out after \d+s: screenshot \(its GPU process and "
                                    r"renderers did no work for \d+ s: the frame is not coming\); check's last step: \S")
        self.assertNoStoppedGpu()

    def test_command_timeout_names_the_step(self):
        """SHOWTIME_TIMEOUT (the caller's limit) ends a render that is still waiting with an error naming where each of
        its parts is, in its log too, and its browsers go with it. The waits are stretched (x3: the stuck screenshot
        gets 90 s) so the 50 s limit comes first on a slow runner too."""
        out = self.tmp / "limit.mp4"
        t0 = time.time()
        cp = showtime("render", self.proj, "-o", out, "--no-check", "--workers", "1", "--no-audio", "--poster", "none",
                      env=dict(ENV, SHOWTIME_TEST_STOP_GPU="shot:6", SHOWTIME_TIMEOUT="50", SHOWTIME_TEST_WAIT_SCALE="3"),
                      timeout=200)
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
        self.assertNoStoppedGpu()


if __name__ == "__main__":
    unittest.main(argv=[a for a in sys.argv if a != "--fast"])

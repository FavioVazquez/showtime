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
  * a page whose ST.waitFor gate takes 3 s of work in 200 ms pieces (scale 0.03: the gate gets 1.8 s): with the
    fixed waits the page never becomes ready; paced, the gaps between its frames raise the factor and it does

Needs a browser. usage: python tests/test_pace.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import shutil
import subprocess
import sys
import tempfile
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
        write(proj / "index.html", HEAD + "</head><body><script>" + BUSY_JS +
              "ST.waitFor((async () => { for (let k = 0; k < 15; k++) { busy(200); await new Promise((r) => setTimeout(r, 0)); } })(), 'heavy init');\n"
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


if __name__ == "__main__":
    unittest.main(argv=[a for a in sys.argv if a != "--fast"])

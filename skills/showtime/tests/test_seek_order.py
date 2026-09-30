#!/usr/bin/env python3
"""Frames are a function of t alone, whatever order the stage is seeked in.

A clip that is not active can still be on screen: a transition keeps the outgoing scene through its
window (after the scene's end) and an `end`-aligned window shows the incoming scene before its
start. Their `--t`/`--p` used to keep whatever the last seek that activated them wrote, so the
same time looked different after a forward, a backward or a random walk (check's "frames depend on
seek order", and chunk joins in a parallel render).

One small page, probed in one browser session: an in-order walk over every frame is the reference
(what a single-worker render sees); forward, backward, random-order and far-jump walks must give
the same clip state and the same pixels at every sampled time.
Skipped with --fast (needs a browser). usage: python tests/test_seek_order.py [--fast] [-v]
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
sys.path.insert(0, str(SKILL / "lib"))

from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())

# 4 s at 30 fps. #a (0-1.5 s) holds its last frame through b's crossfade window [1.5, 2.1); its
# nested clip #a2 ends before #a does. #c's window is end-aligned, [2.4, 3.0): #c is on screen before
# its start. The bars read --p and --t with no fallback, so a stale or missing value shows.
PAGE = """<!doctype html><html><head><meta charset="utf-8">
<script src="/_st/stage.js"></script>
<link rel="stylesheet" href="/_st/themes/neutral.css">
<script>ST.config({"width": 640, "height": 360, "fps": 30, "duration": 4});</script>
<script type="module" src="/_st/components/index.js"></script>
<style>
.scene { position: absolute; inset: 0; }
.bar { position: absolute; left: 0; height: 40px; width: calc(var(--p) * 100%); }
.tbar { position: absolute; left: 0; height: 40px; width: calc(var(--t) * 200px); }
</style></head><body><div class="stage">
<section class="scene" id="a" data-start="0" data-dur="1.5" style="background:#402">
  <div class="bar" style="top:40px;background:#fc3"></div><div class="tbar" style="top:100px;background:#3cf"></div>
  <div id="a2" data-start="+0.5" data-dur="0.6" style="position:absolute;inset:0"><div class="bar" style="top:160px;background:#f6c"></div></div>
</section>
<section class="scene" id="b" data-start="#a" data-dur="1.5" data-transition="crossfade 0.6" style="background:#024">
  <div class="bar" style="top:220px;background:#9f6"></div><div class="tbar" style="top:280px;background:#fff"></div>
</section>
<section class="scene" id="c" data-start="#b" data-dur="1" data-transition="crossfade 0.6 end" style="background:#240">
  <div class="bar" style="top:40px;background:#f93"></div><div class="tbar" style="top:100px;background:#ccc"></div>
</section>
</div></body></html>
"""

TIMES = [0.2, 0.9, 1.2, 1.5, 1.6, 1.9, 2.0, 2.4, 2.5, 2.9, 3.0, 3.5, 3.9667]

PROBE = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const skill = process.argv[2], dir = process.argv[3];
const times = JSON.parse(process.argv[4]);
const imp = (p) => import(pathToFileURL(path.join(skill, 'scripts', p)).href);
const { startServer } = await imp('server.mjs');
const { openBrowser, openStage, openLab } = await imp('lib/stagehost.mjs');
const server = await startServer({ root: dir, port: 0 });
const b = await openBrowser({ gpu: 'auto' });
const fps = 30;
const R = { walks: {} };
const state = (s) => s.page.evaluate(() => Object.fromEntries(['a', 'a2', 'b', 'c'].map((id) => {
  const el = document.getElementById(id), cs = getComputedStyle(el);
  const bars = [...el.querySelectorAll(':scope > .bar, :scope > .tbar')].map((x) => Math.round(x.getBoundingClientRect().width * 100) / 100);
  return [id, { shown: cs.display !== 'none', t: cs.getPropertyValue('--t').trim(), p: cs.getPropertyValue('--p').trim(), bars }];
})));
let rng = 7;
const rand = () => { rng = (rng * 1103515245 + 12345) % 2147483648; return rng / 2147483648; };
const shuffled = (arr) => { const a = arr.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(rand() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
try {
  const s = await openStage(b.browser, { url: server.url, page: 'index.html', config: {} });
  const lab = await openLab(b.browser, server.url);
  const shots = {};
  // the reference: every frame in order (a single-worker render)
  const want = new Set(times.map((t) => Math.round(t * fps)));
  const ref = {};
  for (let f = 0; f <= Math.round(times[times.length - 1] * fps); f++) {
    await s.seek(f / fps);
    if (want.has(f)) { ref[f] = await state(s); shots['ref' + f] = await s.shot({ format: 'png' }); }
  }
  R.ref = ref;
  const walks = {
    forward: times.map((t) => [null, t]),
    backward: times.slice().reverse().map((t) => [null, t]),
    random: shuffled(times).map((t) => [null, t]),
    jumps: times.map((t, i) => [i % 2 ? 0 : 3.9667, t]),   // every time reached straight from the start or the end
  };
  for (const [name, seq] of Object.entries(walks)) {
    const got = {};
    for (const [pre, t] of seq) {
      if (pre !== null) await s.seek(pre);
      await s.seek(t);
      const f = Math.round(t * fps);
      const st = await state(s);
      const shot = await s.shot({ format: 'png' });
      const refShot = shots['ref' + f];
      const d = shot.equals(refShot) ? { same: true } : await lab.diff(refShot, shot, 8);
      got[f] = { state: st, same: !!d.same, changedPct: d.changedPct || 0, solid: d.solid || 0, maxDelta: d.maxDelta || 0 };
    }
    R.walks[name] = got;
  }
  await s.close();
} finally { await b.browser.close(); await server.close(); }
console.log(JSON.stringify(R));
"""


def node_exe():
    return ENV.get("SHOWTIME_NODE") or plat.which("node") or shutil.which("node") or "node"


@unittest.skipIf(FAST, "needs a browser")
class SeekOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-seekorder-"))
        proj = cls.tmp / "proj"
        proj.mkdir()
        (proj / "index.html").write_text(PAGE, encoding="utf-8")
        probe = cls.tmp / "probe.mjs"
        probe.write_text(PROBE, encoding="utf-8")
        cp = subprocess.run([node_exe(), str(probe), str(SKILL), str(proj), json.dumps(TIMES)], env=ENV,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        if cp.returncode != 0:
            raise AssertionError("probe failed:\n%s\n%s" % (cp.stdout[-3000:], cp.stderr[-3000:]))
        cls.R = json.loads(cp.stdout.strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_reference_holds_and_rests(self):
        """The in-order walk: the outgoing scene holds its last frame, the early incoming one rests at 0."""
        ref = self.R["ref"]
        a = ref["48"]["a"]                         # 1.6 s: inside b's window, a ended at 1.5 s
        self.assertTrue(a["shown"])
        self.assertEqual((a["t"], a["p"]), ("1.4667", "0.9778"))   # frame 44 = 1.4667 s, its last frame
        c = ref["75"]["c"]                         # 2.5 s: inside c's end-aligned window, c starts at 3.0 s
        self.assertTrue(c["shown"])
        self.assertEqual((c["t"], c["p"]), ("0.0000", "0.0000"))
        self.assertEqual(c["bars"], [0, 0])
        self.assertEqual(ref["48"]["b"]["p"], "0.0667")          # active clips: unchanged (0.1 s of 1.5 s)

    def test_every_order_gives_the_same_frames(self):
        ref = self.R["ref"]
        for name, got in self.R["walks"].items():
            self.assertEqual(sorted(got, key=int), sorted(ref, key=int), name)
            for f, g in got.items():
                with self.subTest(walk=name, t=int(f) / 30):
                    self.assertEqual(g["state"], ref[f], "%s walk, t=%.3f: clip state differs from the in-order walk" % (name, int(f) / 30))
                    # pixels: identical, or at most rasterisation noise on edges
                    self.assertTrue(g["same"] or (g["solid"] == 0 and g["changedPct"] < 0.5),
                                    "%s walk, t=%.3f: frame differs (%s)" % (name, int(f) / 30, g))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + [a for a in sys.argv[1:] if a != "--fast"])

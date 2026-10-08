#!/usr/bin/env python3
"""Shutter blur on chosen elements (data-st-blur and ST.blur in runtime/stage.js, F.motionBlur in runtime/film.js,
the check rules in scripts/lib/blurcheck.mjs).

  * the runtime parses, thresholds.json has the "blur" numbers, check wires the rules in, the docs and the showreel
    template use it (the flash words carry data-st-blur on the word, never on its full-frame wrapper)
  * the rules, as pure functions under Node: a snap passes; a drift, a gentle entrance, a ticker, text never shown
    sharp, a low threshold on text, a scene, a full-frame layer, a container, a film draw that returns a point,
    motion the blur cannot see and an inline box each give their warning
  * the threshold, frame by frame in a browser: copies only on the fast frames (as many as `samples`), none at rest,
    while slow or on the frame it lands; a slow drift never blurs; `threshold`, `off` and `max` work; a pose given
    to ST.blur blurs; motion from a plain onSeek handler is not seen; page code never meets the copies
  * frame-exact: DOM and canvas-film pages rendered with 1 and with 3 workers give the same PNG frames; against the
    same page without the blur, only the fast frames differ (the landing frame and every frame at rest are byte for
    byte the same), and the fast frames really are smeared
  * `showtime check` warns blur_slow, blur_text, blur_container, blur_unsampled and blur_inline on a page that has
    each, says nothing on a clean snap, and reads a film's F.motionBlur too

Needs a browser. usage: python tests/test_blur.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from _listen import skip_if_listen_refused

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
RUNTIME = SKILL / "runtime"
sys.path.insert(0, str(SKILL / "lib"))

from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
FILES = [RUNTIME / "stage.js", RUNTIME / "film.js", SKILL / "scripts" / "lib" / "blurcheck.mjs", SKILL / "scripts" / "check.mjs"]
CODES = ("blur_text", "blur_slow", "blur_container", "blur_unsampled", "blur_inline")


def node_exe():
    return ENV.get("SHOWTIME_NODE") or plat.which("node") or shutil.which("node") or "node"


def showtime(*args, check=True, timeout=900):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    skip_if_listen_refused(cp)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


HEAD = """<!doctype html><html><head><meta charset="utf-8"><script src="/_st/stage.js"></script>
<link rel="stylesheet" href="/_st/themes/fonts/anton.css">
<style>body{background:#11131c;margin:0;font-family:'Anton',sans-serif;color:#f1ede4} .scene{position:absolute;inset:0}
%s</style></head><body>"""

# a whip (0.3 s in), a scale punch (0.9 s in), a mask reveal under overflow: hidden (1.4 s in), a slow drift, a pose
# function (1.8 s in), an element moved by a plain onSeek handler, one with a huge threshold, one switched off
SNAPS_CSS = """
 #w { position:absolute; left:30px; top:20px; font-size:64px; line-height:1; animation: whip .3s cubic-bezier(.16,1,.3,1) .3s both; }
 @keyframes whip { from { transform: translateX(-520px) } to { transform: none } }
 #c { position:absolute; left:330px; top:30px; width:150px; height:90px; animation: punch .35s cubic-bezier(.16,1,.3,1) .9s both; }
 .scene > .card { border-radius:12px; display:grid; place-items:center; background:linear-gradient(135deg,#ff4fd8,#2337ff); color:#fff; font-size:30px; }
 .scene > .card b { color: #d8ff3a; }
 @keyframes punch { from { transform: scale(2.6) } to { transform: none } }
 .line { position:absolute; left:30px; top:150px; height:70px; width:260px; overflow:hidden; }
 .line span { display:inline-block; font-size:62px; line-height:1.1; color:#29e7ff; animation: up .3s cubic-bezier(.16,1,.3,1) 1.4s both; }
 @keyframes up { from { transform: translateY(110%) } to { transform: none } }
 #d { position:absolute; left:330px; top:160px; font-size:30px; animation: drift 2.5s linear both; }
 @keyframes drift { from { transform: translateX(0) } to { transform: translateX(40px) } }
 #sq { position:absolute; left:30px; top:250px; width:60px; height:60px; background:#d8ff3a; border-radius:8px; }
 #hd { position:absolute; left:330px; top:250px; width:60px; height:60px; background:#ff3b30; }
 #hi, #off { position:absolute; top:300px; font-size:24px; animation: whip .3s cubic-bezier(.16,1,.3,1) .3s both; }
 #hi { left:200px } #off { left:420px }
"""
SNAPS_BODY = """<section class="scene" data-start="0" data-dur="2.5">
 <div id="w" data-st-blur>WHIP</div>
 <div id="c" class="card" data-st-blur><b>PUN</b>CH</div>
 <div class="line"><span id="m" data-st-blur>MASK</span></div>
 <div id="d" data-st-blur>drift</div>
 <div id="sq"></div>
 <div id="hd" data-st-blur></div>
 <div id="hi" data-st-blur="threshold 100000">high</div>
 <div id="off" data-st-blur="off">off</div>
</section>
<script>
 const sq = document.getElementById('sq'), hd = document.getElementById('hd');
 ST.blur(sq, { pose: (t) => { const p = ST.progress(t, 1.8, 2.1, ST.ease.outCubic);
   sq.style.transform = `translateX(${(p * 400).toFixed(2)}px) rotate(${(p * 200).toFixed(2)}deg)`; } });
 ST.onSeek((t) => { const p = ST.progress(t, 1.8, 2.1, ST.ease.outCubic); hd.style.transform = `translateX(${(p * 200).toFixed(2)}px)`; });
 // page code reads the page while it seeks: it must never meet a copy
 window.__seen = 0;
 ST.onSeek(() => { window.__seen = Math.max(window.__seen, document.querySelectorAll('#w, [data-st-copy]').length); });
</script>
</body></html>"""


def snaps_page(blur=True):
    body = SNAPS_BODY
    if not blur:
        body = re.sub(r' data-st-blur(="[^"]*")?', '', body).replace("ST.blur(sq, { pose: (t) => {", "ST.onSeek((t) => {").replace("rotate(${(p * 200).toFixed(2)}deg)`; } });", "rotate(${(p * 200).toFixed(2)}deg)`; });")
    return HEAD % SNAPS_CSS + body


FILM = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="/_lib/@fontsource-variable/inter/index.css">
<script src="/_st/stage.js"></script><script src="/_st/film.js"></script></head><body><script>
const BLUR = %s;
Film.start({ look: 'dark', design: [1920, 1080], scenes(T, g, F) {
  const word = (t) => { const x = F.tween(t, 0.3, 0.25, -700, 960, 'outExpo');
    F.text('SNAP', x, 540, { size: 220, weight: 800, align: 'center', baseline: 'middle', color: F.pal.ink });
    return [x - 330, 430, 660, 220]; };
  const card = (t, c) => { const s = F.tween(t, 0.8, 0.3, 2.6, 1, 'outExpo');
    c.save(); c.translate(1500, 820); c.scale(s, s); F.box(-180, -100, 360, 200, 24, { fill: F.pal.accent }); c.restore();
    return [1500 - 180 * s, 820 - 100 * s, 360 * s, 200 * s]; };
  if (BLUR) { F.motionBlur(T, word, { id: 'word' }); F.motionBlur(T, card); } else { word(T); card(T, g); }
} });
</script></body></html>"""

PROBE = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [skill, dir] = process.argv.slice(2);
const imp = (p) => import(pathToFileURL(path.join(skill, 'scripts', p)).href);
const { startServer } = await imp('server.mjs');
const { openBrowser, openStage } = await imp('lib/stagehost.mjs');
const cfg = { width: 640, height: 360, fps: 30, duration: 2.5 };
const server = await startServer({ root: dir, port: 0 });
const b = await openBrowser({ gpu: 'auto' });
const R = { frames: [] };
try {
  const s = await openStage(b.browser, { url: server.url, page: 'index.html', config: cfg });
  // every frame in order, then a few again out of order: the state of a frame depends on its time only
  const order = [...Array(75).keys(), 40, 12, 66, 13, 0, 30, 29, 28, 31];
  for (const f of order) {
    await s.seek(f / 30);
    const st = await s.page.evaluate(() => {
      const out = {};
      for (const it of window.__stBlur.items()) {
        const el = document.querySelector(it.sel.replace(/^(div|span)/, ''));
        const host = el && el.nextElementSibling;
        out[it.sel] = { on: !!(it.last && it.last.on), why: it.last ? it.last.why : '', L: it.last ? it.last.L : 0, S: it.last ? it.last.S || 0 : 0,
          copies: host && host.localName === 'st-blur' ? host.querySelectorAll('[data-st-copy]').length : -1,
          box: (() => { const c = host && host.querySelector('[data-st-copy]'); if (!c) return null; const r = c.getBoundingClientRect(), b = c.querySelector('b');
            return [Math.round(r.width), Math.round(r.height), getComputedStyle(c).backgroundImage.slice(0, 24), b ? getComputedStyle(b).color : '']; })(),
          hidden: !!(el && el.hasAttribute('data-st-blurring')) };
      }
      return out;
    });
    R.frames.push([f, st]);
  }
  R.seen = await s.page.evaluate(() => window.__seen);
  // what a review note on a blurred frame points at (audit.mjs elementSnapshot): the element, never its copies
  const { elementSnapshot } = await imp('lib/audit.mjs');
  await s.seek(12 / 30);   // the whip mid-smear, on the frame
  const snap = await s.page.evaluate(elementSnapshot, { width: 640, height: 360, t: 12 / 30, duration: 2.5 });
  R.where = (snap.elements || []).map((e) => [e.sel, e.text]);
  R.errors = (await s.diag()).errors;
  await s.close();
} finally { await b.browser.close(); await server.close(); }
console.log(JSON.stringify(R));
"""


def frames_of(out):
    fdir = out.parent / (out.stem + ".work") / "frames"
    return sorted(p for p in fdir.iterdir() if p.suffix == ".png")


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


class BlurTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-blur-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def project(self, name, html, w=640, h=360, dur=2.5, page="index.html"):
        proj = self.tmp / name
        write(proj / "showtime.json", json.dumps({"width": w, "height": h, "fps": 30, "duration": dur, "background": "#11131c"}))
        write(proj / page, html)
        return proj

    def test_01_runtime_docs_and_template(self):
        node = node_exe()
        for f in FILES:
            self.assertTrue(f.is_file(), f)
            cp = subprocess.run([node, "--check", str(f)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            self.assertEqual(cp.returncode, 0, "%s: %s" % (f.name, cp.stderr))
        stage = (RUNTIME / "stage.js").read_text(encoding="utf-8")
        self.assertIn("blur: function (target, opts)", stage)
        self.assertIn("plus-lighter", stage)
        self.assertIn("[data-st-blurring]{visibility:hidden!important}", stage)
        self.assertIn("F.motionBlur = function", (RUNTIME / "film.js").read_text(encoding="utf-8"))
        th = json.loads((RUNTIME / "thresholds.json").read_text(encoding="utf-8"))["blur"]
        for k in ("min_motion", "text_run_s", "container_frac", "container_nodes", "default_threshold"):
            self.assertGreater(th[k], 0, k)
        self.assertEqual(th["default_threshold"], 6)
        self.assertIn("blurcheck.mjs", (SKILL / "scripts" / "check.mjs").read_text(encoding="utf-8"))
        refs = SKILL / "references"
        self.assertIn("## Shutter blur", (refs / "stage-api.md").read_text(encoding="utf-8"))
        for doc in ("motion-craft.md", "components.md", "film-api.md", "render.md", "qa.md", "typography.md"):
            text = (refs / doc).read_text(encoding="utf-8")
            self.assertTrue("data-st-blur" in text or "F.motionBlur" in text, doc)
        render = (refs / "render.md").read_text(encoding="utf-8")
        for code in CODES:
            self.assertIn(code, render)
        reel = (SKILL / "templates" / "showreel" / "index.html").read_text(encoding="utf-8")
        flash = re.search(r'<section class="scene" id="flash".*?</section>', reel, re.S).group(0)
        self.assertEqual(flash.count("<span data-st-blur>"), 3, flash)
        self.assertNotIn('class="w display" data-st-blur', flash)
        self.assertFalse(re.search(r'class="w[^"]*"[^>]*data-st-blur', flash), "the blur belongs on the word, not on its full-frame .w")

    def test_02_rules(self):
        rules = (SKILL / "scripts" / "lib" / "blurcheck.mjs").as_uri()
        script = """
import { blurFindings, blurSummary, blurConfig, DEFAULTS } from %s;
const fr = (speeds, on, size, area) => speeds.map((v, i) => [+(i / 30).toFixed(4), v, v / 2, on[i] ? 1 : 0, size, area]);
const base = { sel: 'div#x', text: 'SNAP', chars: 4, nodes: 0, clip: false, nested: false, media: false, decor: false, shutter: 180, samples: 8,
  threshold: 6, max: '50%%', off: false, step: 1, why: '', probes: [] };
const pad = (a, n, v) => a.concat(Array(n).fill(v));
const snap = pad([0, 420, 180, 70, 20, 7], 30, 0), snapOn = pad([0, 1, 1, 1, 1, 1], 30, 0);
const cases = {
  snap: { ...base, frames: fr(snap, snapOn, 120, 0.03) },
  drift: { ...base, text: 'drift', frames: fr(Array(60).fill(1.5), Array(60).fill(0), 90, 0.02) },
  gentle: { ...base, frames: fr(pad([0, 9, 7, 6.5, 6.2], 30, 0), pad([0, 1, 1, 1, 1], 30, 0), 100, 0.02) },
  ticker: { ...base, text: 'BREAKING NEWS', frames: fr(Array(40).fill(40), Array(40).fill(1), 70, 0.05) },
  never: { ...base, frames: fr([0, 160, 160, 160, 160, 160], [0, 1, 1, 1, 1, 1], 100, 0.02) },
  lowth: { ...base, threshold: 1, frames: fr(pad([0, 420, 180, 70, 20, 7, 3, 2], 30, 0), pad([0, 1, 1, 1, 1, 1, 1, 1], 30, 0), 120, 0.03) },
  scene: { ...base, text: 'WHOLE SCENE', clip: true, nested: true, frames: fr(snap, snapOn, 1080, 1) },
  layer: { ...base, text: '', chars: 0, frames: fr(snap, snapOn, 1080, 0.8) },
  nodes: { ...base, text: '', chars: 0, nodes: 90, frames: fr(snap, snapOn, 300, 0.2) },
  point: { ...base, wholeCanvas: true, frames: fr(snap, snapOn, 120, 0.03) },
  handler: { ...base, text: '', chars: 0, why: 'still', frames: [], probes: [{ from: 2.5, t: 2.5333, actual: 268, predicted: 0 }] },
  still: { ...base, text: '', chars: 0, why: 'still', frames: [] },
  inline: { ...base, why: 'inline', frames: [] },
  off: { ...base, off: true, frames: [] },
  decor: { ...base, decor: true, frames: fr(Array(40).fill(40), Array(40).fill(1), 70, 0.05) },
};
const out = {};
for (const [k, it] of Object.entries(cases)) out[k] = blurFindings(it, DEFAULTS, { fps: 30 }).map((f) => f.code);
out.summary = blurSummary(cases.snap, 30);
out.cfg = blurConfig({ blur: { min_motion: 0.4, text_run_s: -1 } });
console.log(JSON.stringify(out));
""" % json.dumps(rules)
        f = self.tmp / "rules.mjs"
        write(f, script)
        cp = subprocess.run([node_exe(), str(f)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", env=ENV)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertEqual(r["snap"], [], r)
        self.assertEqual(r["drift"], ["blur_slow"])
        self.assertEqual(r["gentle"], ["blur_slow"])
        self.assertEqual(r["ticker"], ["blur_text"])
        self.assertEqual(r["never"], ["blur_text"])
        self.assertEqual(r["lowth"], ["blur_text"])
        self.assertIn("blur_container", r["scene"])
        self.assertIn("blur_container", r["layer"])
        self.assertIn("blur_container", r["nodes"])
        self.assertIn("blur_container", r["point"])
        self.assertEqual(r["handler"], ["blur_unsampled"])
        self.assertEqual(r["still"], ["blur_slow"])
        self.assertEqual(r["inline"], ["blur_inline"])
        self.assertEqual(r["off"], [])
        self.assertEqual(r["decor"], [], "UI-mockup detail is not text being read")
        self.assertEqual(r["summary"]["blurred"], 5)
        self.assertEqual(r["summary"]["peak"], 420)
        self.assertEqual(r["cfg"]["min_motion"], 0.4)
        self.assertEqual(r["cfg"]["text_run_s"], 0.4, "a non-positive value keeps the default")

    def test_03_threshold_frame_by_frame(self):
        proj = self.project("threshold", snaps_page())
        f = self.tmp / "probe.mjs"
        write(f, PROBE)
        cp = subprocess.run([node_exe(), str(f), str(SKILL), str(proj)], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace", timeout=600)
        skip_if_listen_refused(cp)
        self.assertEqual(cp.returncode, 0, cp.stdout[-2000:] + cp.stderr[-2000:])
        R = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertEqual(R["errors"], [])
        self.assertEqual(R["seen"], 1, "page code met a copy of #w (copies must be gone before the handlers run)")
        first = {}
        for fnum, st in R["frames"]:
            if fnum not in first:
                first[fnum] = st
            else:
                self.assertEqual({k: (v["on"], v["copies"], v["box"]) for k, v in st.items()}, {k: (v["on"], v["copies"], v["box"]) for k, v in first[fnum].items()},
                                 "frame %d reached again out of order differs" % fnum)
        on = lambda sel: sorted(f for f, st in first.items() if st[sel]["on"])
        # the whip runs over frames 9-18 (0.3-0.6 s): blurred only on its fast start, sharp as it lands and at rest
        w = on("div#w")
        self.assertTrue(w and w[0] == 10 and len(w) >= 3, w)
        self.assertTrue(all(9 < x < 18 for x in w), w)
        for x in range(0, 75):
            st = first[x]["div#w"]
            if st["on"]:
                self.assertEqual(st["copies"], 8, "frame %d: %s" % (x, st))
                self.assertTrue(st["hidden"], x)
            else:
                self.assertEqual(st["copies"], 0, "frame %d: %s" % (x, st))
                self.assertFalse(st["hidden"], x)
        self.assertIn(first[9]["div#w"]["why"], ("slow", "rest"), "the first frame of the move starts sharp")
        self.assertFalse(first[18]["div#w"]["on"])
        self.assertTrue(on("div#c") and all(27 <= x <= 37 for x in on("div#c")), on("div#c"))   # the punch, 0.9-1.25 s
        for x in on("div#c"):
            box = first[x]["div#c"]["box"]
            self.assertTrue(box and box[2].startswith("linear-gradient") and box[3] == "rgb(216, 255, 58)", "frame %d: %s" % (x, box))
        self.assertTrue(on("span#m") and all(42 <= x <= 51 for x in on("span#m")), on("span#m"))  # the mask reveal, 1.4-1.7 s
        self.assertEqual(on("div#d"), [], "a slow drift never blurs")
        self.assertEqual(on("div#hi"), [], "threshold 100000 never blurs")
        self.assertEqual(on("div#off"), [], "data-st-blur=off never blurs")
        self.assertEqual(on("div#hd"), [], "motion from a plain onSeek handler is not seen")
        self.assertTrue(on("div#sq") and all(54 < x < 63 for x in on("div#sq")), on("div#sq"))    # the pose function, 1.8-2.1 s
        # max (50 %% of the shorter side) shortens the shutter of the fastest whip frame: S under half a frame
        self.assertLess(first[10]["div#w"]["S"], 0.5 / 30 - 1e-4, first[10]["div#w"])
        self.assertLessEqual(first[10]["div#w"]["L"], 1e6)
        self.assertTrue(first[12]["div#w"]["on"], first[12])
        self.assertFalse([w for w in R["where"] if "st-blur" in w[0]], "a note on a blurred frame names the copies: %s" % R["where"])
        self.assertEqual([w for w in R["where"] if w[1] == "WHIP"], [["#w", "WHIP"]], "a note on a blurred frame names the blurred element once: %s" % R["where"])

    def test_04_frame_exact_and_sharp_landing(self):
        for name, blur, plain in (("dom", snaps_page(), snaps_page(False)), ("film", FILM % "true", FILM % "false")):
            proj = self.project(name, blur, w=480, h=270, dur=2.5 if name == "dom" else 1.5)
            write(proj / "plain.html", plain)
            hashes, files = {}, {}
            for tag, page, w in (("w1", "index.html", 1), ("w3", "index.html", 3), ("plain", "plain.html", 3)):
                out = self.tmp / ("out-%s-%s" % (name, tag)) / "v.mp4"
                showtime("render", proj, "--page", page, "-o", out, "--workers", w, "--format", "png", "--keep-frames",
                         "--no-audio", "--poster", "none", "--quiet")
                files[tag] = frames_of(out)
                hashes[tag] = [digest(p) for p in files[tag]]
            n = len(hashes["w1"])
            self.assertEqual(n, len(hashes["w3"]))
            self.assertEqual([i for i in range(n) if hashes["w1"][i] != hashes["w3"][i]], [], "%s: frames differ between 1 and 3 workers" % name)
            differ = [i for i in range(n) if hashes["w1"][i] != hashes["plain"][i]]
            if name == "dom":
                # only the fast frames of the whip (10-17), the punch (28-36), the mask (43-50) and the pose (55-62) differ
                self.assertTrue(differ, name)
                for i in differ:
                    self.assertTrue(10 <= i <= 17 or 27 <= i <= 37 or 42 <= i <= 51 or 54 <= i <= 63, "%s: frame %d differs at rest" % (name, i))
                for i in (0, 9, 18, 20, 38, 52, 64, 74):
                    self.assertNotIn(i, differ, "%s: frame %d (at rest, or the landing) is not sharp" % (name, i))
                self.assertTrue(any(10 <= i <= 17 for i in differ) and any(27 <= i <= 37 for i in differ), differ)
            else:
                self.assertTrue(differ and all(9 <= i <= 18 or 24 <= i <= 34 for i in differ), "film: %s" % differ)
                for i in (0, 9, 20, 40, 44):
                    self.assertNotIn(i, differ, "film: frame %d is not sharp" % i)

    def test_05_check_warnings(self):
        css = """
 #drift { position:absolute; left:20px; top:20px; font-size:40px; animation: dr 3s linear both; }
 @keyframes dr { from { transform: translateX(0) } to { transform: translateX(40px) } }
 #ticker { position:absolute; left:0; top:90px; font-size:32px; white-space:nowrap; animation: tk 2s linear both; }
 @keyframes tk { from { transform: translateX(700px) } to { transform: translateX(-600px) } }
 #scene2 { position:absolute; inset:0; animation: sl .3s cubic-bezier(.16,1,.3,1) 1s both; }
 @keyframes sl { from { transform: translateX(-640px) } to { transform: none } }
 #scene2 p { position:absolute; left:300px; top:200px; margin:0; font-size:30px; }
 #handler { position:absolute; left:20px; top:250px; width:60px; height:60px; background:#d8ff3a; }
 #inl { font-size:24px; animation: sm .2s ease-out 2s both; }
 @keyframes sm { from { transform: translateY(-200px) } to { transform: none } }
"""
        body = """<section class="scene" data-start="0" data-dur="3">
 <div id="drift" data-st-blur>DRIFT</div>
 <div id="ticker" data-st-blur>BREAKING: A LONG TICKER LINE THAT RACES</div>
 <div id="handler" data-st-blur></div>
 <p style="position:absolute;left:300px;top:300px;margin:0">an <span id="inl" data-st-blur>inline</span> word</p>
</section>
<section id="scene2" data-start="0" data-dur="3" data-st-blur><p>WHOLE SCENE</p></section>
<script>const hd = document.getElementById('handler');
 ST.onSeek((t) => { const p = ST.progress(t, 2.0, 2.3, ST.ease.outCubic); hd.style.transform = `translateX(${(p * 400).toFixed(1)}px)`; });</script>
</body></html>"""
        bad = self.project("bad", HEAD % css + body, dur=3)
        good = self.project("good", snaps_page().replace('<div id="d" data-st-blur>drift</div>', '').replace('<div id="hd" data-st-blur></div>', '<div id="hd"></div>')
                            .replace('<div id="hi" data-st-blur="threshold 100000">high</div>', ''))
        film = self.project("filmcheck", FILM % "true", w=640, h=360, dur=1.5)
        reports = {}
        for name, proj in (("bad", bad), ("good", good), ("film", film)):
            cp = showtime("check", proj, "--json", "--no-history", "--no-determinism", "--samples", "3", check=False)
            try:
                reports[name] = json.loads(cp.stdout)
            except ValueError:
                raise AssertionError("check gave no JSON (rc=%d):\n%s\n%s" % (cp.returncode, cp.stdout[-2000:], cp.stderr[-2000:]))
        found = lambda rep: {(f["code"], re.search(r"#(\w+)|F\.motionBlur \S+", f["message"]).group(0)) for f in rep["findings"] if f["code"].startswith("blur_")}
        bad_found = found(reports["bad"])
        for want in (("blur_slow", "#drift"), ("blur_text", "#ticker"), ("blur_container", "#scene2"), ("blur_unsampled", "#handler"), ("blur_inline", "#inl")):
            self.assertIn(want, bad_found, json.dumps([f for f in reports["bad"]["findings"] if f["code"].startswith("blur")], indent=1)[:3000])
        self.assertEqual(found(reports["good"]), set(), [f["message"] for f in reports["good"]["findings"] if f["code"].startswith("blur")])
        items = {it["sel"]: it for it in reports["good"]["blur"]["items"]}
        self.assertGreater(items["div#w"]["ratio"], 1, items["div#w"])
        self.assertGreater(items["div#w"]["blurred"], 2)
        fitems = {it["sel"]: it for it in reports["film"]["blur"]["items"]}
        self.assertIn("F.motionBlur word", fitems, list(fitems))
        self.assertGreater(fitems["F.motionBlur word"]["blurred"], 2, fitems)
        self.assertEqual(found(reports["film"]), set(), [f["message"] for f in reports["film"]["findings"] if f["code"].startswith("blur")])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

#!/usr/bin/env python3
"""The xray template and the mechanism library: templates/xray, skills/showtime/library/xray, `showtime new xray`.

  * static: the template's sample is consistent (xray.json events carry frame = floor(t * fps), the sample clip is
    the analyzed file, the sync marker sits at (W-10, H-10) and skipped events never light it); every library
    entry registers a mechanism with its design box, four anchors and a draw function, and has a README with the
    clip it was verified on; the guide is routed from SKILL.md
  * CLI: `new xray` copies a runnable project (no layout variants left behind); --mechanism copies a library entry
    and drops the sample clip's evidence for another object; an unknown mechanism, or --mechanism on another
    template, is an error; --layout sets showtime.json "xray".layout
  * notes.json is optional: a 404 for it is no missing file in an X-ray project (check and render), a 404 for
    xray.json still is; a fresh project without notes passes `showtime check` (browser, skipped with --fast)

Stdlib only. usage: python tests/test_xray_template.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
TEMPLATE = SKILL / "templates" / "xray"
LIBRARY = SKILL / "library" / "xray"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
TMP = Path(tempfile.mkdtemp(prefix="st-xray-tpl-"))
FAST = "--fast" in sys.argv
NODE = shutil.which("node", path=ENV.get("PATH"))


def showtime(*args, check=True, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


class TestStatic(unittest.TestCase):
    def test_sample_is_consistent(self):
        doc = json.loads((TEMPLATE / "xray.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["schema"], "showtime.xray/1")
        src = doc["source"]
        clip = TEMPLATE / "media" / src["file"]
        self.assertTrue(clip.is_file(), clip)
        self.assertEqual(hashlib.sha256(clip.read_bytes()).hexdigest(), src["sha256"], "the sample clip is the analyzed file")
        self.assertLess(clip.stat().st_size, 256 * 1024, "binaries over 256 KiB need a manual review")
        for e in doc["events"]:
            self.assertEqual(e["frame"], math.floor(e["t"] * src["fps"]), e)
        track = doc["track"]
        self.assertLessEqual(abs(len(track["H"]) - src["duration"] * src["fps"]), 2, "one homography per frame")
        self.assertTrue(all(len(h) == 9 for h in track["H"]))
        cfg = json.loads((TEMPLATE / "showtime.json").read_text(encoding="utf-8"))
        xr = cfg["xray"]
        kept = [e for e in doc["events"] if e["i"] not in xr["skip"]]
        self.assertEqual(len(xr["text"]), len(kept), "one character of the paper per kept keystroke")
        self.assertEqual(cfg["render"]["poster_bake"], "off", "a baked poster would put a stray marker on frame 0")
        self.assertGreaterEqual(float(re.search(r"endcard:\s*([0-9.]+)", (TEMPLATE / "cue.js").read_text()).group(1)),
                                src["duration"] - 0.05, "the end card starts after the clip")

    def test_marker_contract(self):
        html = (TEMPLATE / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="xmark"', html)
        self.assertRegex(html, r"#xmark\s*\{[^}]*width:\s*6px;[^}]*height:\s*6px;[^}]*background:\s*#000;[^}]*z-index:\s*99")
        js = (TEMPLATE / "xray.js").read_text(encoding="utf-8")
        self.assertIn("px(S.W - 10)", js)
        self.assertIn("px(S.H - 10)", js)
        self.assertRegex(js, r"e\.frame === f && e\.kind !== 'skip'")
        for bad in ("Math.random", "Date.now", "setTimeout", "setInterval", "performance.now"):
            self.assertNotIn(bad, js)

    def test_one_cue_table(self):
        tables = [p.name for p in TEMPLATE.glob("*.js") if re.search(r"\bvar CUE\s*=\s*\{", p.read_text(encoding="utf-8"))]
        self.assertEqual(tables, ["cue.js"])

    def test_library_entries(self):
        names = sorted(p.parent.name for p in LIBRARY.glob("*/mechanism.js"))
        self.assertIn("typewriter", names)
        self.assertTrue((LIBRARY / "README.md").is_file())
        for n in names:
            js = (LIBRARY / n / "mechanism.js").read_text(encoding="utf-8")
            self.assertIn("XRAY.mechanism(", js, n)
            for key in ("name:", "box:", "anchors:", "draw:", "drawn:"):
                self.assertIn(key, js, (n, key))
            anchors = re.search(r"anchors:\s*\{([^}]*)\}", js).group(1)
            self.assertGreaterEqual(len(re.findall(r"\w+:\s*(?:\[|[A-Z])", anchors)), 4, n)
            readme = (LIBRARY / n / "README.md").read_text(encoding="utf-8")
            self.assertIn("Verified on", readme, n)
            self.assertIn("Measured", readme, n)
            for bad in ("Math.random", "Date.now"):
                self.assertNotIn(bad, js, n)
        self.assertEqual((TEMPLATE / "mechanism.js").read_text(encoding="utf-8"),
                         (LIBRARY / "typewriter" / "mechanism.js").read_text(encoding="utf-8"),
                         "the template's mechanism is the library's typewriter")

    def test_anchors_not_collinear(self):
        """Four anchors place a mechanism with a homography: three of them in a line make it degenerate (nothing
        draws in place). Checked with node on each mechanism's own anchors."""
        import shutil as _sh
        node = _sh.which("node", path=ENV.get("PATH"))
        if not node:
            self.skipTest("node not found")
        for p in sorted(LIBRARY.glob("*/mechanism.js")):
            js = ("var out=null;var XRAY={mechanism:function(m){out=m;}};" + p.read_text(encoding="utf-8") +
                  ";var a=Object.keys(out.anchors).slice(0,4).map(function(k){return out.anchors[k];});var bad=[];"
                  "for(var i=0;i<4;i++)for(var j=i+1;j<4;j++)for(var k=j+1;k<4;k++){var A=a[i],B=a[j],C=a[k];"
                  "var cr=(B[0]-A[0])*(C[1]-A[1])-(B[1]-A[1])*(C[0]-A[0]);if(Math.abs(cr)<1e-6)bad.push([i,j,k]);}"
                  "console.log(JSON.stringify({n:a.length,bad:bad}));")
            cp = subprocess.run([node, "-e", js], stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            self.assertEqual(cp.returncode, 0, (p, cp.stderr[-500:]))
            res = json.loads(cp.stdout.strip().splitlines()[-1])
            self.assertEqual(res["n"], 4, p)
            self.assertEqual(res["bad"], [], "%s: three anchors in a line" % p.parent.name)

    def test_guide_routed(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        routes = skill[skill.index("## Situation"):skill.index("## Red flags")]
        self.assertRegex(routes, r"\| [^\n]*`xray`[^\n]*\|\n", "SKILL.md routes the xray guide in its family row")
        self.assertTrue((SKILL / "references" / "workflows" / "xray.md").is_file())


class TestCLI(unittest.TestCase):
    def test_new_xray(self):
        d = TMP / "plain"
        showtime("new", "xray", d)
        for f in ("index.html", "xray.js", "mechanism.js", "cue.js", "xray.json", "media/clip.webm", "audio/mix.json"):
            self.assertTrue((d / f).is_file(), f)
        self.assertFalse((d / "diagram.html").exists())
        self.assertFalse((d / "README.md").exists())
        self.assertEqual(json.loads((d / "showtime.json").read_text())["xray"]["layout"], "through")

    def test_layout_and_mechanism(self):
        d = TMP / "split"
        showtime("new", "xray", d, "--layout", "split", "--mechanism", "typewriter")
        xr = json.loads((d / "showtime.json").read_text())["xray"]
        self.assertEqual(xr["layout"], "split")
        self.assertEqual(xr["text"], "Sounds of changes.", "the typewriter keeps the sample's evidence")
        others = [p.parent.name for p in LIBRARY.glob("*/mechanism.js") if p.parent.name != "typewriter"]
        if others:
            d2 = TMP / "other"
            cp = showtime("new", "xray", d2, "--mechanism", others[0])
            self.assertEqual((d2 / "mechanism.js").read_text(), (LIBRARY / others[0] / "mechanism.js").read_text())
            xr2 = json.loads((d2 / "showtime.json").read_text())["xray"]
            for k in ("text", "place", "skip"):
                self.assertNotIn(k, xr2, "another object never inherits the typewriter clip's evidence")
            self.assertIn("still the typewriter sample", cp.stdout + cp.stderr)

    def test_diagram_without_scene_falls_back_to_split(self):
        d = TMP / "nodiag"
        cp = showtime("new", "xray", d, "--layout", "diagram", "--mechanism", "piano")
        self.assertEqual(json.loads((d / "showtime.json").read_text())["xray"]["layout"], "split")
        self.assertFalse((d / "diagram.js").exists())
        self.assertNotIn("XRAY_DIAGRAM", (d / "index.html").read_text(encoding="utf-8"))
        self.assertIn("split", cp.stdout + cp.stderr)

    def test_offset_frames_in_both_pages(self):
        for name in ("xray.js", "diagram.html"):
            t = (TEMPLATE / name).read_text(encoding="utf-8")
            self.assertIn("offset_frames", t, name)
            self.assertIn("> 0.01", t, name)           # verify's retime threshold
            self.assertIn("data-offset", t, name)

    def test_theme(self):
        d = TMP / "light"
        showtime("new", "xray", d, "--theme", "light")
        cfg = json.loads((d / "showtime.json").read_text())
        self.assertEqual(cfg["xray"]["theme"], "light")
        self.assertEqual(cfg["background"], "#f4f0e7")
        cp = showtime("new", "xray", TMP / "white", "--theme", "white", check=False)
        self.assertNotEqual(cp.returncode, 0)
        js = (TEMPLATE / "xray.js").read_text(encoding="utf-8")
        self.assertIn("light: {", js)
        for p in [TEMPLATE / "xray.js"] + sorted(LIBRARY.glob("*/mechanism.js")):
            self.assertNotRegex(p.read_text(encoding="utf-8"), r"'rgba\(\d", "%s: colours come from the theme (C.l/C.i/C.bg/C.h)" % p.name)

    def test_errors(self):
        cp = showtime("new", "xray", TMP / "bad", "--mechanism", "no-such-thing", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("typewriter", cp.stdout + cp.stderr)
        cp = showtime("new", "dom", TMP / "bad2", "--mechanism", "typewriter", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("xray template", cp.stdout + cp.stderr)


MISSING = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL] = process.argv.slice(2);
const { missing404 } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'stagehost.mjs')).href);
const B = 'http://127.0.0.1:9';
const log = { http: [{ url: B + '/notes.json', status: 404 }, { url: B + '/xray.json?x=1', status: 404 }, { url: B + '/a.png', status: 500 }] };
const urls = (cfg) => missing404(log, cfg, B).map((h) => h.url.replace(B, ''));
console.log(JSON.stringify({ xray: urls({ xray: {} }), plain: urls({}), none: urls(null) }));
"""


STRIP = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, PROJ, W, H, TIMES] = process.argv.slice(2);
const S = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'stagehost.mjs')).href);
const { startServer } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'server.mjs')).href);
const server = await startServer({ root: PROJ, port: 0 });
const b = await S.openBrowser({});
const out = {};
try {
  const sess = await S.openStage(b.browser, { url: server.url, page: 'index.html', config: { width: +W, height: +H, fps: 30, duration: 16.4 } });
  await sess.page.evaluate(() => {
    window.__calls = [];
    for (const id of ['cv', 'strip-cv']) {
      const c = document.getElementById(id);
      if (!c) continue;
      const g = c.getContext('2d');
      for (const n of ['fillRect', 'moveTo']) {
        const o = g[n].bind(g);
        g[n] = (...a) => { window.__calls.push([id, n, ...a.map(Number), c.width]); return o(...a); };
      }
      const ft = g.fillText.bind(g);   // a text: where it starts and how wide it is
      g.fillText = (s, x, y) => { window.__calls.push([id, 'fillText', +x, +y, g.measureText(s).width, c.width]); return ft(s, x, y); };
    }
  });
  for (const t of TIMES.split(',').map(Number)) {
    await sess.page.evaluate(() => { window.__calls = []; });
    await sess.seek(t);
    out[t] = await sess.page.evaluate(() => [window.__calls, (document.getElementById('scan') || {}).style?.opacity ?? null]);
  }
  await sess.close();
} catch (e) { out.error = String(e.stack || e); }
await b.browser.close(); await server.close();
process.stdout.write(JSON.stringify(out) + '\n', () => process.exit(0));   // a pipe: exit only once it is written (64 KB+)
"""


MECH_TRACE = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, PROJ, W, H, TIMES, OUT] = process.argv.slice(2);
const fs = await import('node:fs');
const S = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'stagehost.mjs')).href);
const { startServer } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'server.mjs')).href);
const server = await startServer({ root: PROJ, port: 0 });
const b = await S.openBrowser({});
const out = {};
try {
  const sess = await S.openStage(b.browser, { url: server.url, page: 'index.html', config: { width: +W, height: +H, fps: 30, duration: 16.4 } });
  // every path, text and transform the mechanism's draw(k) makes, numbers rounded (what it draws, not how bright)
  await sess.page.evaluate(() => {
    const m = window.XRAY.mech, draw = m.draw, g = document.getElementById('cv').getContext('2d');
    let on = false;
    for (const n of ['moveTo', 'lineTo', 'rect', 'arc', 'fillText', 'translate', 'scale', 'quadraticCurveTo', 'bezierCurveTo', 'ellipse']) {
      const o = g[n].bind(g);
      g[n] = (...a) => { if (on) window.__trace.push([n, ...a.map((v) => (typeof v === 'number' ? Math.round(v * 100) / 100 : String(v)))]); return o(...a); };
    }
    m.draw = (k) => { on = true; try { return draw(k); } finally { on = false; } };
  });
  for (const t of TIMES.split(',').map(Number)) {
    await sess.page.evaluate(() => { window.__trace = []; });
    await sess.seek(t);
    out[t] = await sess.page.evaluate(() => window.__trace);
  }
  await sess.close();
} catch (e) { out.error = String(e.stack || e); }
await b.browser.close(); await server.close();
fs.writeFileSync(OUT, JSON.stringify(out));          // a file: a trace is longer than a pipe takes before exit
process.exit(0);
"""


@unittest.skipIf(not NODE or FAST, "needs node and a browser")
class TestMusicOnTheRecordingClock(unittest.TestCase):
    """B11b: notes.json times and its tempo map are seconds of the recording. The piano, drums and guitar placed a
    lone note (one no event took) at floor(t * fps), and scrolled the staff by the film's time, so with
    "xray".offset_frames both ran that many frames early. With offset 90 (the clip 3 s into the film) a mechanism
    must draw at film time t + 3 s exactly what it draws at t with no offset: the kit's k.rt and k.frameAt(t)."""

    OFF = 90
    TIMES = (1.5, 2.1, 2.4, 3.3, 4.75, 6.2)                    # recording times around the lone notes (2.2 s, 4.65 s)
    TEMPO = {"bpm": 96, "map": [[0.0, 0.0], [1.25, 2.0], [2.5, 4.0], [4.0, 6.4], [9.5, 15.2]]}

    def music(self, mech):
        # two lone notes, each more than 0.2 s from every event of the template's xray.json (no event takes them)
        notes = [{"i": 0, "t": 2.2, "end": 2.9, "pitch": 60, "confidence": 0.9},
                 {"i": 1, "t": 4.65, "end": 5.0, "pitch": 64, "confidence": 0.9}]
        doc = {"tempo": self.TEMPO, "key": "C"}
        if mech == "drums":
            doc["drums"] = [{"i": 0, "t": 2.2, "piece": "snare", "velocity": 0.9},
                            {"i": 1, "t": 4.65, "piece": "kick", "velocity": 0.8}]
        else:
            doc["notes"] = notes
        if mech == "guitar":
            doc["guitar"] = [{"i": 0, "string": 2, "fret": 1}, {"i": 1, "string": 1, "fret": 0}]
        return doc

    def trace(self, mech, off):
        d = TMP / ("music-%s-%d" % (mech, off))
        if not d.exists():
            showtime("new", "xray", d, "--mechanism", mech)
            (d / "notes.json").write_text(json.dumps(self.music(mech)), encoding="utf-8")
            cfg = json.loads((d / "showtime.json").read_text(encoding="utf-8"))
            cfg["xray"]["offset_frames"] = off
            cfg["duration"] = 16.4
            (d / "showtime.json").write_text(json.dumps(cfg), encoding="utf-8")
            cue = (d / "cue.js").read_text(encoding="utf-8")
            cue = re.sub(r"duration: [\d.]+", "duration: 16.4", re.sub(r"endcard: [\d.]+", "endcard: 13.4", cue))
            (d / "cue.js").write_text(cue, encoding="utf-8")
        cfg = json.loads((d / "showtime.json").read_text(encoding="utf-8"))
        drv = TMP / "mechtrace.mjs"
        drv.write_text(MECH_TRACE, encoding="utf-8")
        times = [round(t + off / 30, 4) for t in self.TIMES]
        cp = subprocess.run([NODE, str(drv), str(SKILL), str(d), str(cfg["width"]), str(cfg["height"]),
                             ",".join(map(str, times)), str(d / "trace.json")], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        r = json.loads((d / "trace.json").read_text(encoding="utf-8"))
        self.assertNotIn("error", r, r.get("error"))
        return [r[str(int(t)) if t == int(t) else str(t)] for t in times]      # JSON keys as JS writes numbers

    def test_events_are_clear_of_the_lone_notes(self):
        ev = [e["t"] for e in json.loads((TEMPLATE / "xray.json").read_text(encoding="utf-8"))["events"]]
        for t in (2.2, 4.65):
            self.assertGreater(min(abs(t - e) for e in ev), 0.2, t)

    def test_piano_drums_guitar_offset_draws_the_same_later(self):
        for mech in ("piano", "drums", "guitar"):
            base, late = self.trace(mech, 0), self.trace(mech, self.OFF)
            for t, a, b in zip(self.TIMES, base, late):
                self.assertTrue(a, (mech, t, "the mechanism drew nothing"))
                if a != b:
                    diff = next(i for i, (x, y) in enumerate(zip(a, b)) if x != y) if len(a) == len(b) else None
                    self.fail("%s at recording %.1f s: %d calls with no offset, %d with offset %d (first difference at "
                              "%s: %s vs %s)" % (mech, t, len(a), len(b), self.OFF, diff,
                                                 a[diff] if diff is not None else "-", b[diff] if diff is not None else "-"))


@unittest.skipIf(not NODE or FAST, "needs node and a browser")
class TestStripOffset(unittest.TestCase):
    """The sound strip is the recording's timeline. With "xray".offset_frames the clip starts that many frames into
    the film, so a tick sits at (its film frame - offset) and the caret at (the film frame - offset) over the
    recording's length: every tick inside the strip, the caret at its start before the clip begins and still moving
    near the end (it used to place both by film time: late ticks past the strip's end, the caret stuck at the end)."""

    OFF = 90                                                   # the clip starts 3 s into the film
    TIMES = (2.0, 10.0, 11.0, 12.0)

    def project(self, name, *extra, doc=None, xray=None, times=None):
        d = TMP / name
        showtime("new", "xray", d, *extra)
        if doc:
            x = json.loads((d / "xray.json").read_text(encoding="utf-8"))
            doc(x)
            (d / "xray.json").write_text(json.dumps(x), encoding="utf-8")
        cfg = json.loads((d / "showtime.json").read_text(encoding="utf-8"))
        cfg["xray"]["offset_frames"] = self.OFF
        cfg["xray"].update(xray or {})
        cfg["duration"] = 16.4
        (d / "showtime.json").write_text(json.dumps(cfg), encoding="utf-8")
        cue = (d / "cue.js").read_text(encoding="utf-8")
        cue = re.sub(r"duration: [\d.]+", "duration: 16.4", re.sub(r"endcard: [\d.]+", "endcard: 13.4", cue))
        (d / "cue.js").write_text(cue, encoding="utf-8")
        drv = TMP / "strip.mjs"
        drv.write_text(STRIP, encoding="utf-8")
        cp = subprocess.run([NODE, str(drv), str(SKILL), str(d), str(cfg["width"]), str(cfg["height"]),
                             ",".join(map(str, times or self.TIMES))], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace", timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertNotIn("error", r, r.get("error"))
        return {float(k): v for k, v in r.items()}

    def check(self, ticks, caret, dur=None):
        doc = json.loads((TEMPLATE / "xray.json").read_text(encoding="utf-8"))
        dur, last = dur or doc["source"]["duration"], doc["events"][-1]["frame"]
        for t in self.TIMES:
            self.assertEqual(len(ticks[t]), len(doc["events"]), (t, ticks[t]))
            self.assertTrue(all(-0.01 <= x <= 1.01 for x in ticks[t]), ("a tick past the strip", t, ticks[t]))
            self.assertAlmostEqual(max(ticks[t]), last / 30 / dur, delta=0.02)
        self.assertAlmostEqual(caret[2.0], 0, delta=0.01, msg="before the clip starts the caret waits at 0")
        c = [caret[t] for t in self.TIMES[1:]]
        for t, x in zip(self.TIMES[1:], c):
            self.assertAlmostEqual(x, (t * 30 - self.OFF) / 30 / dur, delta=0.02, msg=(t, c))
        self.assertTrue(c[0] < c[1] < c[2] < 1, ("the caret keeps moving to the end", c))

    def xray_strip(self, r):
        ticks, caret = {}, {}
        for t, (calls, _) in r.items():
            # the plate: (x0 - 16, y0 - pad, w + 32, h + pad + 16), 104 px tall at 16:9 (pad 38, ticks 50), 94 at 9:16
            # (pad 22, ticks 56); at 9:16 the label sits on the ticks' row and the ticks start 28 px after it
            bg = [c for c in calls if c[0] == "cv" and c[1] == "fillRect" and c[5] in (104, 94)]
            self.assertTrue(bg, (t, "no strip background"))
            _, _, bx, by, bw, bh, _ = bg[-1]
            pad = 38 if bh == 104 else 22
            x0, y0, w, h = bx + 16, by + pad, bw - 32, bh - pad - 16
            lab = [c for c in calls if c[0] == "cv" and c[1] == "fillText" and abs(c[2] - x0) < 0.01 and abs(c[3] - (y0 + h / 2)) < 0.01]
            sx = x0 + lab[0][4] + 28 if lab else x0
            sw = x0 + w - sx
            ticks[t] = [(c[2] + 2 - sx) / sw for c in calls
                        if c[0] == "cv" and c[1] == "fillRect" and c[4] == 4 and abs(c[3] + c[5] / 2 - (y0 + h / 2)) < 0.6]
            mv = [c for c in calls if c[0] == "cv" and c[1] == "moveTo" and abs(c[3] - (y0 - 8)) < 0.01]
            self.assertEqual(len(mv), 1, (t, mv))
            caret[t] = (mv[0][2] + 9 - sx) / sw
        return ticks, caret

    def diagram_strip(self, r):
        ticks, caret = {}, {}
        for t, (calls, _) in r.items():
            sc = [c for c in calls if c[0] == "strip-cv" and c[1] == "fillRect"]
            self.assertTrue(sc, (t, "no strip drawn"))
            w = sc[0][-1]
            ticks[t] = [(c[2] + 2 - 2) / (w - 4) for c in sc if c[4] == 4]
            cr = [c for c in sc if c[4] == 2 and c[3] == 0]
            self.assertEqual(len(cr), 1, (t, cr))
            caret[t] = (cr[0][2] - 1) / (w - 4)
        return ticks, caret

    def test_xray_page(self):
        self.check(*self.xray_strip(self.project("stripoff")))

    def test_diagram_page(self):
        self.check(*self.diagram_strip(self.project("stripoffd", "--layout", "diagram")))

    @staticmethod
    def no_length(x):
        x["source"].pop("duration", None)

    def test_no_measured_length(self):
        """With no source.duration the recording is taken to run from the clip's start to the film's end (the
        diagram: to the endcard), so the strip still spans the recording, not the recording plus the offset."""
        self.check(*self.xray_strip(self.project("stripoffn", doc=self.no_length)), dur=16.4 - self.OFF / 30)
        self.check(*self.diagram_strip(self.project("stripoffnd", "--layout", "diagram", doc=self.no_length)),
                   dur=13.4 - self.OFF / 30)

    def test_track_until_on_the_clip_clock(self):
        """"xray".track_until is the clip's seconds: with the clip 3 s into the film the see-through fades out at
        film time track_until + 3 s, not at track_until (it used to vanish 3 s early)."""
        def track(x):
            x["track"] = {"H": [[1, 0, 0, 0, 1, 0, 0, 0, 1]] * 283, "region": [[100, 80], [540, 80], [540, 280], [100, 280]]}
        r = self.project("stripofft", doc=track, xray={"track_until": 5.0}, times=(7.0, 8.0, 8.15, 8.6))
        op = {t: float(v[1]) for t, v in r.items()}
        self.assertEqual(op[7.0], 1.0, op)                     # clip 4.0 s: still tracked
        self.assertEqual(op[8.0], 1.0, op)                     # clip 5.0 s: the fade starts
        self.assertTrue(0 < op[8.15] < 1, op)                  # clip 5.15 s: fading
        self.assertEqual(op[8.6], 0.0, op)                     # clip 5.6 s: gone

CANVAS_TEXT = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, PROJ, W, H, T] = process.argv.slice(2);
const S = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'stagehost.mjs')).href);
const { startServer } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'server.mjs')).href);
const server = await startServer({ root: PROJ, port: 0 });
const b = await S.openBrowser({});
let out = {};
try {
  const sess = await S.openStage(b.browser, { url: server.url, page: 'index.html', config: { width: +W, height: +H, fps: 30, duration: 12.8 } });
  await sess.page.evaluate(() => {
    window.__texts = [];
    const g = document.getElementById('cv').getContext('2d'), o = g.fillText.bind(g);
    g.fillText = (...a) => { window.__texts.push([String(a[0]), g.font, g.measureText(String(a[0])).width]); return o(...a); };
  });
  await sess.seek(+T);
  out = { texts: await sess.page.evaluate(() => window.__texts) };
  await sess.close();
} catch (e) { out.error = String(e.stack || e); }
await b.browser.close(); await server.close();
console.log(JSON.stringify(out));
process.exit(0);
"""


LABELS = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, PROJ, W, H, TIMES] = process.argv.slice(2);
const S = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'stagehost.mjs')).href);
const { startServer } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'server.mjs')).href);
const server = await startServer({ root: PROJ, port: 0 });
const b = await S.openBrowser({});
const out = {};
try {
  const sess = await S.openStage(b.browser, { url: server.url, page: 'index.html', config: { width: +W, height: +H, fps: 30, duration: 12.8 } });
  await sess.page.evaluate(() => {
    window.__ops = [];
    const g = document.getElementById('cv').getContext('2d');
    for (const n of ['beginPath', 'moveTo', 'lineTo', 'stroke', 'strokeRect', 'fillRect']) {
      const o = g[n].bind(g);
      g[n] = (...a) => { window.__ops.push([n, ...a.map(Number)]); return o(...a); };
    }
    const ft = g.fillText.bind(g);
    g.fillText = (s, x, y) => { window.__ops.push(['fillText', String(s), +x, +y, g.font]); return ft(s, x, y); };
  });
  for (const t of TIMES.split(',').map(Number)) {
    await sess.page.evaluate(() => { window.__ops = []; });
    await sess.seek(t);
    out[t] = await sess.page.evaluate(() => window.__ops);
  }
  await sess.close();
} catch (e) { out.error = String(e.stack || e); }
await b.browser.close(); await server.close();
process.stdout.write(JSON.stringify(out) + '\n', () => process.exit(0));
"""


@unittest.skipIf(not NODE or FAST, "needs node and a browser")
class TestFreshProjectChecks(unittest.TestCase):
    """A fresh 16:9 X-ray project passes its own check (#68: the brand 48 px from the edge, the counters in the player
    controls' strip, 24 px labels, the end card over the drawing's labels, the red letter under 4.5:1), and the sound
    strip's label, drawn on the canvas where check's size rule does not look, is readable (#73: it was 18 px)."""

    LAYOUT = {"low_contrast", "control_strip", "edge_margin", "text_overlap", "tiny_text", "safe_zone", "text_off_canvas"}

    def test_the_strip_label_is_readable(self):
        d = TMP / "label169"
        showtime("new", "xray", d, "--aspect", "16:9")
        drv = TMP / "canvastext.mjs"
        drv.write_text(CANVAS_TEXT, encoding="utf-8")
        cp = subprocess.run([NODE, str(drv), str(SKILL), str(d), "1920", "1080", "5"], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertNotIn("error", r, r.get("error"))
        sizes = {t: float(re.search(r"([\d.]+)px", f).group(1)) for t, f, _ in r["texts"]}
        label = [t for t in sizes if t.startswith("THE CLIP")]
        self.assertEqual(len(label), 1, sizes)
        self.assertGreaterEqual(sizes[label[0]], 26, sizes)
        self.assertTrue(all(v >= 25 for v in sizes.values()), ("canvas text under 25 px at 16:9", sizes))

    def strip_label(self, d, w, h):
        drv = TMP / "canvastext.mjs"
        drv.write_text(CANVAS_TEXT, encoding="utf-8")
        cp = subprocess.run([NODE, str(drv), str(SKILL), str(d), str(w), str(h), "5"], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertNotIn("error", r, r.get("error"))
        label = [(t, float(re.search(r"([\d.]+)px", f).group(1)), wd) for t, f, wd in r["texts"]
                 if t.startswith(("THE CLIP", "RED = "))]
        self.assertEqual(len(set(label)), 1, r["texts"])
        return label[0]

    def test_a_long_mechanism_word_fits_the_strip(self):
        """#73 follow-up: the label is the mechanism's own word ("one"), so a long one ran past the strip's plate. It
        shrinks to the floor (2.2% of the frame height: 24 px at 16:9, 43 px at 9:16), then drops "the clip's sound",
        then ends in an ellipsis, inside its room (the strip's 852 px at 16:9; at 9:16, on the ticks' row, 56% of the
        strip, which is 78% of the width)."""
        word = "a hammer striking the left string group"           # 39 characters: too long for the full label at 24 px
        cases = (("16:9", 1920, 1080, 852, "a soft tap on the left key row", "THE CLIP"),   # 30: shrinks, keeps it all
                 ("16:9", 1920, 1080, 852, word, "RED = " + word.upper()),
                 ("16:9", 1920, 1080, 852, " ".join([word] * 3), "RED = A HAMMER"),
                 ("9:16", 1080, 1920, 1080 * 0.78 * 0.56, " ".join([word] * 3), "RED = A HAMMER"))
        for i, (aspect, w, h, room, one, starts) in enumerate(cases):
            d = TMP / ("longlabel%d" % i)
            showtime("new", "xray", d, "--aspect", aspect)
            mech = d / "mechanism.js"
            js = mech.read_text(encoding="utf-8")
            self.assertIn("one: 'a keystroke'", js)
            mech.write_text(js.replace("one: 'a keystroke'", "one: %r" % one), encoding="utf-8")
            text, px, width = self.strip_label(d, w, h)
            where = (aspect, one, text, px, width)
            self.assertTrue(text.startswith(starts), where)
            self.assertGreaterEqual(px, math.ceil(h * 0.022), where)
            self.assertLessEqual(width, room, where)
            if len(one) > 60:
                self.assertTrue(text.endswith("\u2026"), where)
            if i == 0:
                self.assertLess(px, 26, ("the 30-character word is meant to need the shrink", where))

    def canvas_ops(self, d, times="2,6,9"):
        drv = TMP / "labels.mjs"
        drv.write_text(LABELS, encoding="utf-8")
        cp = subprocess.run([NODE, str(drv), str(SKILL), str(d), "1080", "1920", times], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertNotIn("error", r, r.get("error"))
        return r

    def columns(self, where, ops):
        """The part labels' plates (in a column at the reels box's left edge, x 64, or ending at its right edge, x 916;
        one or two lines of 44 px, padded 16, 8 or 4 px), their lines of text and their leaders, checked: inside the
        box, none on another, no two leaders of a column crossing."""
        plates = [o[1:5] for o in ops if o[0] == "fillRect" and o[4] in (60, 106, 52, 98, 48, 94) and 760 < o[2] < 1190
                  and (abs(o[1] - 64) < 0.01 or abs(o[1] + o[3] - 916) < 0.01)]
        self.assertTrue(plates, where)
        for i, a in enumerate(plates):
            self.assertTrue(64 - 0.01 <= a[0] and a[0] + a[2] <= 916 + 0.01, (where, a))
            for b in plates[i + 1:]:
                apart = a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] + 2 - 0.01 <= b[1] or b[1] + b[3] + 2 - 0.01 <= a[1]
                self.assertTrue(apart, (where, "labels on each other", a, b))
        texts = []
        for o in ops:
            if o[0] == "fillText":
                for x, y, w, h in plates:
                    if abs(o[2] - (x + 11)) < 0.01 and y < o[3] < y + h:
                        self.assertIn(" 44px", o[4], (where, o))
                        texts.append(o)
        paths, cur = [], None
        for o in ops:
            if o[0] == "beginPath":
                cur = []
            elif o[0] in ("moveTo", "lineTo") and cur is not None:
                cur.append((o[1], o[2]))
            elif o[0] == "stroke" and cur is not None:
                paths.append(cur)
                cur = None
        # each leader: moveTo(the plate's edge, its row) -> lineTo(the column's edge, its row) -> lineTo(its part)
        leaders = [p for p in paths if len(p) == 3 and p[0][1] == p[1][1]
                   and any(abs(p[0][1] - (y + h / 2)) < 0.01 and min(abs(p[0][0] - x), abs(p[0][0] - x - w)) < 0.01 for x, y, w, h in plates)]
        self.assertEqual(len(leaders), len(plates), (where, leaders))

        def crosses(a, b):
            side = lambda p, q, o: (q[0] - p[0]) * (o[1] - p[1]) - (q[1] - p[1]) * (o[0] - p[0])
            return side(a[0], a[1], b[0]) * side(a[0], a[1], b[1]) < 0 and side(b[0], b[1], a[0]) * side(b[0], b[1], a[1]) < 0

        slants = [(p[1], p[2]) for p in leaders]
        bad = [(a, b) for i, a in enumerate(slants) for b in slants[i + 1:] if a[0][0] == b[0][0] and crosses(a, b)]
        self.assertEqual(bad, [], (where, "leaders cross"))
        return plates, texts, leaders, paths

    def test_9x16_part_labels_in_columns(self):
        """9:16 (the X-ray as the hero): the part labels sit in a column at the reels box's left edge (x 64), 44 px
        (the phone floor), a long one on two lines, none on another, and no two leaders cross; parts at rest in weight
        500, the ones acting now in 600; no column covers the drawing, and the drawing stays left of x 916, where the
        platform's buttons begin."""
        d = TMP / "labels916"
        showtime("new", "xray", d, "--aspect", "9:16")
        r = self.canvas_ops(d)
        words = sorted("PRINT POINT MAINSPRING TYPEBARS KEY LEVERS ESCAPEMENT".split())
        weights = {}
        for t, ops in r.items():
            plates, texts, leaders, paths = self.columns(("typewriter", t), ops)
            self.assertEqual(len(plates), 5, (t, plates))
            self.assertTrue(all(abs(x - 64) < 0.01 for x, _, _, _ in plates), (t, "one column, on the left", plates))
            self.assertEqual(sorted(w for o in texts for w in o[1].split()), words, (t, texts))
            weights.setdefault(t, []).extend(o[4].split()[0] for o in texts)
            # the drawing (every other path in the panel) clear of the column's plates
            right = max(x + w for x, _, w, _ in plates)
            pts = [q for p in paths if p not in leaders for q in p if 760 < q[1] < 1190]   # the panel, over the strip
            self.assertTrue(pts)
            self.assertGreaterEqual(min(x for x, _ in pts), right, (t, "the column covers the drawing"))
            self.assertLessEqual(max(x for x, _ in pts), 916, (t, "the drawing runs under the platform's buttons"))
        self.assertEqual(set(weights["6"]), {"500"}, weights)                  # 6 s: every part at rest
        self.assertIn("600", weights["9"], weights)                            # 9 s: a keystroke, its parts red and bold
        frames = [o for ops in r.values() for o in ops if o[0] == "strokeRect" and 760 < o[2] < 1200]
        self.assertTrue(frames)
        self.assertLessEqual(max(o[1] + o[3] for o in frames), 916, ("the panel's frame runs under the buttons", frames))

    def test_9x16_more_labels_than_one_column_holds(self):
        """The drums name 8 parts, more than one column holds at 44 px: a second column at the safe box's right edge, each
        part's label on its side; the drums' caption sits in a row over the columns at 44 px (it was 28 px, under the
        first label). The guitar's string names (e B G D A E, 26 px on lines 21 px apart) are labels in the column,
        their case kept."""
        d = TMP / "drums916"
        showtime("new", "xray", d, "--aspect", "9:16", "--mechanism", "drums")
        for t, ops in self.canvas_ops(d, "2,6").items():
            plates, texts, _, _ = self.columns(("drums", t), ops)
            left = [p for p in plates if abs(p[0] - 64) < 0.01]
            self.assertEqual((len(left), len(plates) - len(left)), (4, 4), (t, plates))
            self.assertEqual(sorted(w for o in texts for w in o[1].split()),
                             sorted("CRASH RIDE HI-HAT TOM TOM SNARE FLOOR TOM KICK".split()), (t, texts))
            cap = [o for o in ops if o[0] == "fillText" and o[1].startswith(("HITS, NO PIECES", "PIECES SORTED"))]
            self.assertEqual(len(cap), 1, (t, cap))
            self.assertIn("600 44px", cap[0][4], cap)
            self.assertAlmostEqual(cap[0][2], 64, delta=0.01, msg=cap)
            self.assertLessEqual(cap[0][3] + 22, min(y for _, y, _, _ in plates), (t, "the caption on a label", cap, plates))
        g = TMP / "guitar916"
        showtime("new", "xray", g, "--aspect", "9:16", "--mechanism", "guitar")
        for t, ops in self.canvas_ops(g, "6").items():
            plates, texts, _, _ = self.columns(("guitar", t), ops)
            self.assertEqual([o[1] for o in sorted(texts, key=lambda o: o[3])], list("eBGDAE"), (t, texts))
            small = [o for o in ops if o[0] == "fillText" and re.search(r" (\d+(\.\d+)?)px", o[4]) and float(re.search(r" (\d+(\.\d+)?)px", o[4]).group(1)) < 43
                     and 760 < o[3] < 1300 and o[1].strip()]
            self.assertEqual(small, [], (t, "text under 43 px in the panel"))
        # with notes.json (the key and tempo: a caption over the column) six 60 px rows no longer fit under it: the plates
        # tighten (8 px of padding) and stay under the caption, none on another
        (g / "notes.json").write_text(json.dumps({"tempo": {"bpm": 96}, "key": "C", "notes": [{"i": 0, "t": 2.2, "pitch": 60}],
                                                  "guitar": [{"i": 0, "string": 2, "fret": 1}]}), encoding="utf-8")
        for t, ops in self.canvas_ops(g, "6").items():
            plates, texts, _, _ = self.columns(("guitar with notes", t), ops)
            self.assertEqual([o[1] for o in sorted(texts, key=lambda o: o[3])], list("eBGDAE"), (t, texts))
            cap = [o for o in ops if o[0] == "fillText" and "BPM" in o[1]]
            self.assertEqual(len(cap), 1, (t, cap))
            self.assertIn("600 44px", cap[0][4], cap)
            self.assertLessEqual(cap[0][3] + 22, min(y for _, y, _, _ in plates), (t, "the caption on a label", cap, plates))
            self.assertEqual({h for _, _, _, h in plates}, {52}, (t, plates))

    def test_fresh_16x9_projects_pass_check(self):
        self.fresh_projects_pass_check("16:9")

    def test_fresh_9x16_projects_pass_check(self):
        """9:16: the sound strip and every label sit inside the reels safe box (the strip was under it, y 1472-1676)
        and at the phone floor (43 px at 1920; the labels were 24-34 px), and the part labels do not overlap."""
        self.fresh_projects_pass_check("9:16")

    # 4:5 and 1:1 keep the portrait and wide layouts as they were (the reels layout is 9:16 only): their findings, per
    # mechanism and kind, as on 0.4.5's code; they may only go down (the fix is its own change, with a critic round)
    RATCHET = {
        ("drums", "1:1"): {"text_overlap": 1, "tiny_text": 1}, ("drums", "4:5"): {"safe_zone": 3, "text_overlap": 1, "tiny_text": 2},
        ("guitar", "1:1"): {"text_overlap": 1, "tiny_text": 1}, ("guitar", "4:5"): {"safe_zone": 3, "text_overlap": 6, "tiny_text": 1},
        ("musicbox", "1:1"): {"text_overlap": 2, "tiny_text": 1}, ("musicbox", "4:5"): {"safe_zone": 3, "text_overlap": 1, "tiny_text": 1},
        ("piano", "1:1"): {"text_overlap": 1, "tiny_text": 1}, ("piano", "4:5"): {"safe_zone": 3, "tiny_text": 1},
        ("switch", "1:1"): {"text_overlap": 2, "tiny_text": 1}, ("switch", "4:5"): {"safe_zone": 3, "text_overlap": 2, "tiny_text": 1},
        ("typewriter", "1:1"): {"text_overlap": 2, "tiny_text": 1}, ("typewriter", "4:5"): {"safe_zone": 3, "text_overlap": 1, "tiny_text": 1},
    }

    def test_every_mechanism_at_every_aspect(self):
        """Every mechanism in the library at 9:16, 4:5 and 1:1: 9:16 passes check (0 layout findings); 4:5 and 1:1 have
        no more findings of any kind than RATCHET."""
        mechs = sorted(p.parent.name for p in LIBRARY.glob("*/mechanism.js"))
        self.assertEqual(sorted({m for m, _ in self.RATCHET}), mechs, "a mechanism without its row in RATCHET")

        def one(cell):
            m, aspect = cell
            d = TMP / ("mx-%s-%s" % (m, aspect.replace(":", "x")))
            showtime("new", "xray", d, "--aspect", aspect, "--mechanism", m)
            cp = showtime("check", d, "--json", check=False, timeout=900)
            rep = json.loads(cp.stdout[cp.stdout.index("{"):])
            return cell, [f for f in rep["findings"] if f["severity"] == "error" or (f["severity"] == "warning" and f.get("code") in self.LAYOUT)]

        import concurrent.futures
        cells = [(m, a) for m in mechs for a in ("9:16", "4:5", "1:1")]
        with concurrent.futures.ThreadPoolExecutor(3) as ex:
            for (m, aspect), found in ex.map(one, cells):
                if aspect == "9:16":
                    self.assertEqual(["%s: %s" % (f.get("code"), f.get("message")) for f in found], [], (m, aspect))
                    continue
                got, cap = Counter(f.get("code") for f in found), self.RATCHET[(m, aspect)]
                worse = {k: (v, cap.get(k, 0)) for k, v in got.items() if v > cap.get(k, 0)}
                self.assertEqual(worse, {}, (m, aspect, "more findings than before", [f.get("message") for f in found]))

    def fresh_projects_pass_check(self, aspect):
        for name, extra in (("check", ()), ("checklight", ("--theme", "light"))):
            d = TMP / (name + aspect.replace(":", "x"))
            showtime("new", "xray", d, "--aspect", aspect, *extra)
            cp = showtime("check", d, "--json", check=False, timeout=600)
            rep = json.loads(cp.stdout[cp.stdout.index("{"):])
            bad = ["%s %s: %s" % (f["severity"], f.get("code"), f.get("message")) for f in rep["findings"]
                   if f["severity"] == "error" or (f["severity"] == "warning" and f.get("code") in self.LAYOUT)]
            self.assertEqual(bad, [], (aspect, name))


@unittest.skipIf(not NODE, "needs node")
class TestOptionalNotes(unittest.TestCase):
    """xray.js fetches notes.json in case `showtime xray notes` wrote one; without it the project is fine."""

    def test_the_filter(self):
        drv = TMP / "missing.mjs"
        drv.write_text(MISSING, encoding="utf-8")
        cp = subprocess.run([NODE, str(drv), str(SKILL)], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertEqual(r["xray"], ["/xray.json?x=1"], "notes.json is optional in an X-ray project, xray.json is not")
        self.assertEqual(r["plain"], ["/notes.json", "/xray.json?x=1"])
        self.assertEqual(r["none"], ["/notes.json", "/xray.json?x=1"])
        self.assertIn("getJSON('notes.json').catch", (TEMPLATE / "xray.js").read_text(encoding="utf-8"), "the page goes on without it")
        for f in ("check.mjs", "render.mjs"):
            self.assertIn("missing404(", (SKILL / "scripts" / f).read_text(encoding="utf-8"), f)

    @unittest.skipIf(FAST, "--fast: no browser")
    def test_a_project_without_notes_passes_check(self):
        proj = TMP / "nonotes"
        showtime("new", "xray", proj)
        self.assertFalse((proj / "notes.json").exists())
        cp = showtime("check", proj, "--json", check=False, timeout=600)
        rep = json.loads(cp.stdout[cp.stdout.index("{"):])
        miss = [f["message"] for f in rep["findings"] if f.get("code") == "missing_file"]
        self.assertEqual(miss, [])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

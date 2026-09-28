#!/usr/bin/env python3
"""Chart value labels stay readable when there are many bars (headless Chrome through the stage host).

The case: 18 decade bars from -0.27 to +1.05 with a "+" prefix and 2 decimals (illustrative sample
values), at 1920x1080 and 1080x1920.
  - the value label under the lowest negative bar never reaches the category labels below the plot
  - valueLabels "auto" (the default) keeps a gap between neighbouring labels: it shrinks them a little,
    then hides the least important ones (the max, the min, the first and the last always show)
  - category labels that do not fit their slot are thinned (tall frames)
  - labels planned per state fade across a morph (no pop), and "all" keeps every label
  - `showtime check` compares SVG labels one by one: a crowded chart with valueLabels "all" is
    labels_crowded, the default chart reports nothing
Skipped with --fast (needs a browser). usage: python tests/test_chart_labels.py [--fast] [-v]
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
sys.path.insert(0, str(SKILL / "lib"))

from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())

# illustrative values (not real measurements)
VALUES = [-0.11, -0.09, -0.02, -0.01, -0.24, -0.27, -0.27, -0.13, -0.05, 0.03, -0.02, 0.02, 0.10, 0.26, 0.44, 0.62, 0.87, 1.05]
DECADES = [{"label": str(1850 + 10 * i), "value": v} for i, v in enumerate(VALUES)]


def node_exe():
    return ENV.get("SHOWTIME_NODE") or plat.which("node") or shutil.which("node") or "node"


def showtime(*args, check=True, timeout=600):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                    cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def page(opts, dur=4):
    return ("""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>chart labels</title>
<script src="/_st/stage.js"></script><script>ST.config({"width": 1920, "height": 1080, "fps": 30, "duration": @DUR@});</script>
<link rel="stylesheet" href="/_st/themes/editorial.css">
<script type="module" src="/_st/components/index.js"></script>
<style>.scene{padding:7cqh 7cqw;background:var(--bg)} .chart{position:absolute;inset:7cqh 7cqw 10cqh}
@container (max-aspect-ratio: 5/6){.chart{inset:13% 19% 27% 7%}}</style></head>
<body><div class="stage"><section class="scene" data-start="0" data-dur="@DUR@">
<div class="chart" id="ch" data-st="chart" data-type="bar" data-at="0.15" data-options='@OPTS@'></div>
</section></div></body></html>""".replace("@DUR@", str(dur)).replace("@OPTS@", json.dumps(opts)))


BASE = {"title": "Sample data: decade averages", "prefix": "+", "decimals": 2, "count": False, "data": DECADES}
PAGES = {
    "auto.html": page(BASE),
    "all.html": page(dict(BASE, valueLabels="all")),
    # state 1: one-digit labels (room to spare); state 2: five-digit labels of nearly equal bars (one crowded row)
    "morph.html": page({"title": "Sample data", "prefix": "", "decimals": 0, "states": [
        {"at": 0, "data": [{"label": str(i), "value": 1 + (i * 7) % 9} for i in range(18)]},
        {"at": 2.2, "data": [{"label": str(i), "value": 20000 + ((i * 7) % 9) * 10} for i in range(18)]}]}, dur=5),
}

PROBE = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const skill = process.argv[2], dir = process.argv[3];
const imp = (p) => import(pathToFileURL(path.join(skill, 'scripts', p)).href);
const { startServer } = await imp('server.mjs');
const { openBrowser, openStage } = await imp('lib/stagehost.mjs');
const server = await startServer({ root: dir, port: 0 });
const b = await openBrowser({ gpu: 'auto' });
const R = {};
// painted glyph boxes (not line boxes) of the visible value and category labels
const labels = () => {
  const ctx = document.createElement('canvas').getContext('2d');
  const ink = (e) => {
    const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    ctx.font = `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
    const m = ctx.measureText(e.textContent), k = r.height / (m.fontBoundingBoxAscent + m.fontBoundingBoxDescent);
    return [r.left, r.top + (m.fontBoundingBoxAscent - m.actualBoundingBoxAscent) * k, r.right, r.top + (m.fontBoundingBoxAscent + m.actualBoundingBoxDescent) * k];
  };
  const shown = (e) => getComputedStyle(e).display !== 'none' && parseFloat(getComputedStyle(e).opacity) > 0.02;
  const pick = (q) => [...document.querySelectorAll(q)].filter(shown).map((e) => ({ t: e.textContent, box: ink(e), fs: parseFloat(getComputedStyle(e).fontSize), op: parseFloat(getComputedStyle(e).opacity) }));
  return { vals: pick('#ch .st-chart-val'), xl: pick('#ch .st-chart-xl'), all: document.querySelectorAll('#ch .st-chart-val').length,
    ops: [...document.querySelectorAll('#ch .st-chart-val')].map((e) => parseFloat(getComputedStyle(e).opacity)) };
};
try {
  for (const [name, size] of [['auto', null], ['auto', { width: 1080, height: 1080 * 16 / 9 }], ['all', null]]) {
    const s = await openStage(b.browser, { url: server.url, page: name + '.html', config: {}, size: size || undefined });
    await s.seek(3.9);
    R[name + (size ? '-tall' : '')] = await s.page.evaluate(labels);
    await s.close();
  }
  const s = await openStage(b.browser, { url: server.url, page: 'morph.html', config: {} });
  R.morph = {};
  for (const t of [2.1, 3.0, 4.9]) { await s.seek(t); R.morph[t] = await s.page.evaluate(labels); }
  await s.close();
} finally { await b.browser.close(); await server.close(); }
console.log(JSON.stringify(R));
"""


def hits(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 0 and min(a[3], b[3]) - max(a[1], b[1]) > 0


def same_row_gaps(items):
    """Horizontal gaps between labels whose glyph rows overlap: [(gap_px, font_px, a, b)]."""
    out = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            A, B = a["box"], b["box"]
            if min(A[3], B[3]) - max(A[1], B[1]) <= 0:
                continue
            out.append((max(A[0], B[0]) - min(A[2], B[2]), min(a["fs"], b["fs"]), a["t"], b["t"]))
    return out


@unittest.skipIf(FAST, "needs a browser")
class ChartLabels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-chartlabels-"))
        cls.proj = cls.tmp / "proj"
        cls.proj.mkdir()
        (cls.proj / "showtime.json").write_text(json.dumps({"width": 1920, "height": 1080, "fps": 30, "duration": 4}), encoding="utf-8")
        for name, html in PAGES.items():
            (cls.proj / name).write_text(html, encoding="utf-8")
        probe = cls.tmp / "probe.mjs"
        probe.write_text(PROBE, encoding="utf-8")
        cp = subprocess.run([node_exe(), str(probe), str(SKILL), str(cls.proj)], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        if cp.returncode != 0:
            raise AssertionError("probe failed:\n%s\n%s" % (cp.stdout[-3000:], cp.stderr[-3000:]))
        cls.R = json.loads(cp.stdout.strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def check_layout(self, r):
        self.assertTrue(r["vals"], r)
        for v in r["vals"]:
            for x in r["xl"]:
                self.assertFalse(hits(v["box"], x["box"]), "value label %s sits on category label %s" % (v["t"], x["t"]))
        for gap, fs, a, b in same_row_gaps(r["vals"]):
            self.assertGreaterEqual(gap, 0.25 * fs, "value labels %s and %s are %.1fpx apart" % (a, b, gap))
        for gap, fs, a, b in same_row_gaps(r["xl"]):
            self.assertGreater(gap, 0, "category labels %s and %s touch" % (a, b))
        texts = [v["t"] for v in r["vals"]]
        for must in ("+1.05", "−0.27"):   # max and min always show
            self.assertIn(must, texts)

    def test_landscape_labels_clear_of_axis_and_each_other(self):
        r = self.R["auto"]
        self.check_layout(r)
        self.assertLess(len(r["vals"]), r["all"], "crowded labels were thinned")
        self.assertGreaterEqual(len(r["vals"]), 10, "but most of them still show at 1920x1080")

    def test_vertical_labels_clear_of_axis_and_each_other(self):
        r = self.R["auto-tall"]
        self.check_layout(r)
        self.assertLess(len(r["xl"]), len(DECADES), "category labels were thinned in the narrow plot")
        self.assertIn("2020", [x["t"] for x in r["xl"]], "the last category label always shows")

    def test_all_keeps_every_label_and_negative_room(self):
        r = self.R["all"]
        self.assertEqual(len(r["vals"]), 18)
        for v in r["vals"]:
            for x in r["xl"]:
                self.assertFalse(hits(v["box"], x["box"]), "value label %s sits on category label %s" % (v["t"], x["t"]))

    def test_label_plan_fades_across_a_morph(self):
        m = self.R["morph"]
        self.assertEqual(len(m["2.1"]["vals"]), 18, "one-digit labels all fit")
        settled = m["4.9"]
        self.assertLess(len(settled["vals"]), 18, "five-digit labels are thinned in the second state")
        for gap, fs, a, b in same_row_gaps(settled["vals"]):
            self.assertGreaterEqual(gap, 0.25 * fs, (a, b, gap))
        self.assertTrue(any(0.05 < o < 0.95 for o in m["3"]["ops"]), "labels leaving fade out during the morph: %s" % m["3"]["ops"])

    def test_check_reports_crowded_svg_labels(self):
        def findings(pg):
            rep = json.loads(showtime("check", self.proj, "--page", pg, "--json", "--no-determinism", "--no-timeline", check=False).stdout)
            return [f for f in rep["findings"] if f["code"] in ("labels_crowded", "text_overlap")]
        crowded = findings("all.html")
        warn = [f for f in crowded if f["code"] == "labels_crowded" and f["severity"] == "warning"]
        self.assertTrue(warn, crowded)
        self.assertIn("valueLabels", warn[0].get("fix", ""))
        self.assertEqual([f for f in findings("auto.html") if f["severity"] != "info"], [])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

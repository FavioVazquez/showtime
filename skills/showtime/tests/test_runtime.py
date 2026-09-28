#!/usr/bin/env python3
"""Runtime fixes from the batch-2 examples (headless Chrome through the showtime stage host).

One small project with several pages, probed in one browser session:
  - a transition whose start is written within 1 ms after a frame boundary starts on that frame
    (the outgoing scene is still on screen), and a later overlay layer stays above the window
  - `wipe left` is the straight (linear) wipe
  - check's text audit sees a lower third that has pointer-events: none over an opaque scene,
    measures SVG text through its transforms, and keeps the full text of a long line
  - chart hbar honours valueLabels: false; count-up follows <html lang>
  - a component defined by a page module after index.js mounted the page is mounted
  - lower-third `in` scales the entrance; 9:16 gets the larger type
  - `showtime snap` follows a page's own ST.config size, gives each page its own folder, writes
    `-o file.jpg`, and `--size` renders a page at another size
  - `demo record` redacts query strings and credentials in logged URLs, and --platform makes the page
    see mac, windows or linux on any machine
Skipped with --fast (needs a browser). usage: python tests/test_runtime.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import shutil
import struct
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


def node_exe():
    return ENV.get("SHOWTIME_NODE") or plat.which("node") or shutil.which("node") or "node"


def showtime(*args, check=True, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                    cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def image_size(path: Path):
    b = path.read_bytes()
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", b[16:24])
    i = 2
    while i < len(b):  # JPEG: walk to the SOF marker
        if b[i] != 0xFF:
            i += 1
            continue
        m = b[i + 1]
        if m in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", b[i + 5:i + 9])
            return w, h
        i += 2 + struct.unpack(">H", b[i + 2:i + 4])[0]
    return None


HEAD = """<!doctype html><html%(lang)s><head><meta charset="utf-8">
<script src="/_st/stage.js"></script>
<link rel="stylesheet" href="/_st/themes/neutral.css">
<script>ST.config(%(cfg)s);</script>
<script type="module" src="/_st/components/index.js"></script>
<style>%(css)s</style>%(extra)s</head><body><div class="stage">"""
TAIL = "</div></body></html>"


def page(body, cfg, css="", extra="", lang=""):
    return HEAD % {"cfg": json.dumps(cfg), "css": css, "extra": extra, "lang": (' lang="%s"' % lang) if lang else ""} + body + TAIL


PAGES = {
    # b starts 0.3 ms after frame 30 (1.0 s at 30 fps): the stage snaps it onto frame 30
    "tx.html": page(
        '<section class="scene" id="a" data-start="0" data-dur="1.0003" style="background:#b00"><h1>A</h1></section>'
        '<section class="scene" id="b" data-start="1.0003" data-dur="1" data-transition="crossfade 0.5" style="background:#00b"><h1>B</h1></section>'
        '<section class="scene" id="c" data-start="2.0003" data-dur="1" data-transition="wipe left 0.4" style="background:#0b0"><h1>C</h1></section>'
        '<div class="ov" data-start="0" data-dur="3" style="position:absolute;left:10px;top:10px;width:100px;height:40px;background:#fff">map</div>',
        {"width": 640, "height": 360, "fps": 30, "duration": 3}),
    "audit.html": page(
        '<section class="scene" data-start="0" data-dur="3" style="background:#224">'
        '<div style="position:absolute;inset:0;background:#335"></div>'
        '<div data-st="lower-third" data-name="Leah Cheshier" data-role="Host" data-at="0" data-hold="2.5" style="z-index:40"></div>'
        '<svg style="position:absolute;left:20px;top:200px" width="200" height="100" viewBox="0 0 100 50">'
        '<g transform="scale(2)"><text x="2" y="12" font-size="10" fill="#fff">Reykjavik</text></g></svg>'
        '<p style="position:absolute;left:20px;top:20px;width:600px;font-size:18px;color:#fff">Source: U.S. Energy Information '
        'Administration, Monthly Energy Review, Table 7.2a, released August 2026</p>'
        '</section>',
        {"width": 640, "height": 360, "fps": 30, "duration": 3}),
    "chart.html": page(
        '<section class="scene" data-start="0" data-dur="3"><div id="ch" data-st="chart" data-type="hbar" data-value-labels="false" '
        'data-data=\'{"labels":["a","b","c"],"values":[3,2,1]}\' style="position:absolute;inset:40px"></div>'
        '<div id="cu" data-st="count-up" data-value="13.7" data-decimals="1" data-dur="0.5"></div></section>',
        {"width": 640, "height": 360, "fps": 30, "duration": 3}, lang="es"),
    "late.html": page(
        '<section class="scene" data-start="0" data-dur="2"><div id="bd" data-st="probe-badge"></div>'
        '<div id="lt" data-st="lower-third" data-name="Ada" data-role="Host" data-in="0.4"></div></section>',
        {"width": 1080, "height": 1920, "fps": 30, "duration": 2},
        extra='<script type="module">import { define } from "/_st/components/index.js";'
              'define({ name: "probe-badge", setup(el) { el.textContent = "mounted"; return { duration: 0.1, update() {} }; } });</script>'),
    "square.html": page('<section class="scene" data-start="0" data-dur="1" style="background:#933"><h1>sq</h1></section>',
                        {"width": 540, "height": 540, "fps": 30, "duration": 1}),
}
PAGES["crop.html"] = page(
    '<section class="scene" data-start="0" data-dur="2" style="background:#10141c;color:#f3efe6">'
    '<p id="ln1" style="position:absolute;left:120px;top:300px;margin:0;font:700 64px/1.1 Inter,sans-serif;white-space:nowrap">'
    'Heat pumps move heat instead of making it</p>'
    '<p id="ln2" style="position:absolute;left:120px;top:520px;margin:0;font:400 44px/1.1 Inter,sans-serif;white-space:nowrap">'
    'A small fridge running backwards, all winter long</p></section>',
    {"width": 1920, "height": 1080, "fps": 30, "duration": 2})
PAGES["index.html"] = PAGES["square.html"]

PROBE = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const skill = process.argv[2], dir = process.argv[3];
const imp = (p) => import(pathToFileURL(path.join(skill, 'scripts', p)).href);
const { startServer } = await imp('server.mjs');
const { openBrowser, openStage } = await imp('lib/stagehost.mjs');
const { textSnapshot } = await imp('lib/audit.mjs');
const { redactUrl, newCaptureContext, emulatePlatform, chromeUA } = await imp('lib/capture.mjs');
const server = await startServer({ root: dir, port: 0 });
const b = await openBrowser({ gpu: 'auto' });
const R = {};
const open = (page) => openStage(b.browser, { url: server.url, page, config: {} });
try {
  let s = await open('tx.html');
  R.txSize = [s.width, s.height];
  await s.seek(30 / 30);
  R.frame30 = await s.page.evaluate(() => ({
    aShown: getComputedStyle(document.querySelector('#a')).display !== 'none',
    bOpacity: getComputedStyle(document.querySelector('#b')).opacity,
    ovZ: getComputedStyle(document.querySelector('.ov')).zIndex,
  }));
  await s.seek(1.2);
  R.mid = await s.page.evaluate(() => ({ ovZ: getComputedStyle(document.querySelector('.ov')).zIndex, bZ: getComputedStyle(document.querySelector('#b')).zIndex }));
  await s.seek(2.1);
  R.wipe = await s.page.evaluate(() => getComputedStyle(document.querySelector('#c')).clipPath);
  await s.close();

  s = await open('audit.html');
  await s.seek(2);
  const snap = await s.page.evaluate(textSnapshot, { width: 640, height: 360, full: true });
  R.blocks = snap.blocks.map((x) => ({ text: x.text, fontSize: x.fontSize, scale: x.scale }));
  R.leaves = snap.leaves.map((x) => ({ own: x.own, fontSize: x.fontSize }));
  R.pointerAfter = await s.page.evaluate(() => getComputedStyle(document.querySelector('.st-lower-third')).pointerEvents);
  await s.close();

  s = await open('chart.html');
  await s.seek(2.9);
  R.chart = await s.page.evaluate(() => ({ vals: document.querySelectorAll('#ch .st-chart-val').length, rows: document.querySelectorAll('#ch .st-chart-row').length,
    cu: (document.querySelector('#cu .st-cu-num') || {}).textContent }));
  await s.close();

  s = await open('late.html');
  await s.seek(1);
  R.late = await s.page.evaluate(() => ({ badge: document.querySelector('#bd').textContent, ready: document.querySelector('#bd').hasAttribute('data-st-ready'),
    tall: document.querySelector('#lt').classList.contains('st-lt-tall'), landed: document.querySelector('#lt').__stComponent.sync.landed,
    nameFs: parseFloat(getComputedStyle(document.querySelector('#lt .st-lt-name')).fontSize) }));
  R.lateWarn = s.log.console.filter((m) => /unknown component/.test(m.text)).length;
  // fast speech (4 words/s): word cards cap at 2 words; phrase cards break at punctuation
  R.groups = await s.page.evaluate(async () => {
    const { groupWords } = await import('/_st/components/captions.js');
    const txt = 'la fisura 8 se abrió en mayo, y la lava llegó al mar.'.split(' ');
    const words = txt.map((w, i) => ({ text: w, start: i * 0.25, end: i * 0.25 + 0.22 }));
    const cards = (o) => groupWords(words.map((w) => ({ ...w })), o).map((g) => g.words.map((w) => w.text).join(' '));
    return { words: cards({ maxWords: 4, maxChars: 60 }), phrase: cards({ maxWords: 8, maxChars: 60, phrase: true, minShow: 1 }) };
  });
  await s.close();
  // demo record --platform: the page sees the chosen OS on any machine
  R.platforms = {};
  for (const os of ['mac', 'windows', 'linux']) {
    const ctx = await newCaptureContext(b.browser, { css: { width: 320, height: 200 }, dpr: 1 }, { userAgent: chromeUA(b.browser.version(), { platform: os }) });
    await emulatePlatform(ctx, os);
    const pg = await ctx.newPage();
    await pg.goto(server.url + '/square.html');
    R.platforms[os] = await pg.evaluate(() => [navigator.platform, /Mac OS X|Windows NT|Linux x86_64/.exec(navigator.userAgent)[0]]);
    await ctx.close();
  }
  s = await open('crop.html');
  await s.seek(1);
  R.cropRects = await s.page.evaluate(() => ['#ln1', '#ln2'].map((q) => { const r = document.querySelector(q).getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }));
  const fs = await import('node:fs');
  fs.writeFileSync(path.join(dir, 'crop-frame.png'), await s.shot({ format: 'png' }));
  await s.close();
  R.redact = [redactUrl('http://127.0.0.1:4000/board/?k=s3cret&view=1#c2'), redactUrl('https://me:pw@example.com/a?token=x')];
} finally { await b.browser.close(); await server.close(); }
console.log(JSON.stringify(R));
"""


@unittest.skipIf(FAST, "needs a browser")
class RuntimeFixes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-runtime-"))
        cls.proj = cls.tmp / "proj"
        cls.proj.mkdir()
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

    def test_transition_starts_on_the_snapped_frame(self):
        f = self.R["frame30"]
        self.assertTrue(f["aShown"], "the outgoing scene must still be on screen on the incoming scene's first frame")
        self.assertLess(float(f["bOpacity"]), 0.05, "the crossfade starts at 0 on that frame")

    def test_overlay_stays_above_the_transition(self):
        self.assertEqual(self.R["mid"]["ovZ"], "10")
        self.assertGreater(int(self.R["mid"]["ovZ"]), int(self.R["mid"]["bZ"]))

    def test_wipe_with_direction_is_linear(self):
        self.assertTrue(self.R["wipe"].startswith("inset("), self.R["wipe"])

    def test_page_size_is_followed(self):
        self.assertEqual(self.R["txSize"], [640, 360])

    def test_audit_sees_pointer_events_none_text_svg_scale_and_full_lines(self):
        texts = [b["text"] for b in self.R["blocks"]]
        self.assertTrue(any("Leah Cheshier" in t for t in texts), texts)
        self.assertEqual(self.R["pointerAfter"], "none", "the audit restores pointer-events")
        svg = [b for b in self.R["blocks"] if b["text"] == "Reykjavik"]
        self.assertTrue(svg and abs(svg[0]["fontSize"] - 40) < 1, svg)   # 10 x scale(2) x viewBox 2
        self.assertTrue(any(t.endswith("released August 2026") for t in texts), texts)

    def test_chart_value_labels_and_locale(self):
        self.assertEqual(self.R["chart"]["rows"], 3)
        self.assertEqual(self.R["chart"]["vals"], 0)
        self.assertEqual(self.R["chart"]["cu"], "13,7")

    def test_late_defined_component_mounts(self):
        L = self.R["late"]
        self.assertEqual(L["badge"], "mounted")
        self.assertTrue(L["ready"])
        self.assertEqual(self.R["lateWarn"], 0, "no 'unknown component' warning for a component defined later")

    def test_phrase_cards_for_fast_speech(self):
        g = self.R["groups"]
        self.assertEqual(g["phrase"], ["la fisura 8 se abrió en mayo,", "y la lava llegó al mar."])
        self.assertGreater(len(g["words"]), len(g["phrase"]))

    def test_lower_third_in_and_tall_type(self):
        L = self.R["late"]
        self.assertTrue(L["tall"])
        self.assertAlmostEqual(L["landed"], 0.4, places=3)
        self.assertGreaterEqual(L["nameFs"], 0.022 * 1920)

    def test_demo_platform_emulation(self):
        self.assertEqual(self.R["platforms"], {"mac": ["MacIntel", "Mac OS X"], "windows": ["Win32", "Windows NT"],
                                               "linux": ["Linux x86_64", "Linux x86_64"]})

    def test_check_notes_a_poster_that_will_not_bake(self):
        proj = self.tmp / "poster"
        proj.mkdir()
        (proj / "showtime.json").write_text(json.dumps({"width": 320, "height": 180, "fps": 30, "duration": 3, "poster": 2}), encoding="utf-8")
        (proj / "index.html").write_text(
            '<!doctype html><html><head><script src="/_st/stage.js"></script><style>body{margin:0}section{position:absolute;inset:0}</style></head>'
            '<body><section data-start="0" data-dur="1.5" style="background:#111"></section>'
            '<section data-start="1.5" data-dur="1.5" style="background:#eee"></section></body></html>', encoding="utf-8")
        rep = json.loads(showtime("check", proj, "--json", "--no-timeline", "--no-determinism", check=False).stdout)
        codes = [f["code"] for f in rep["findings"]]
        self.assertIn("poster_not_baked", codes)

    def test_review_text_crops_hold_whole_lines(self):
        """review-pack's type detail crops cover whole text lines (they used to cut words into fragments
        such as "l is a f")."""
        from st.qa import textcrops
        res = textcrops.crops([(1.0, "frame", self.proj / "crop-frame.png")], self.tmp / "crops", per_frame=2)
        self.assertEqual(len(res), 2, res)
        for (l, t, r, b) in self.R["cropRects"]:
            hit = [c for c in res if c["box"][1] <= t + 40 and c["box"][1] + c["box"][3] >= b - 40]
            self.assertTrue(hit, (l, t, r, b, res))
            x0, _, w, _ = hit[0]["box"]
            self.assertLessEqual(x0, l + 4, "the crop starts before the line's first letter")
            self.assertGreaterEqual(x0 + w, r - 4, "and ends after its last one")

    def test_redacted_urls(self):
        a, b = self.R["redact"]
        self.assertNotIn("s3cret", a)
        self.assertIn("k=redacted", a)
        self.assertNotIn("#c2", a)
        self.assertNotIn("pw", b)
        self.assertNotIn("token=x", b)

    def test_snap_page_size_folder_file_and_size(self):
        out = json.loads(showtime("snap", self.proj, "--page", "square.html", "--at", "0.5", "--json").stdout)
        f = Path(out["stills"][0]["file"])
        self.assertEqual(f.parent, self.proj / "work" / "snap-square")
        self.assertEqual(image_size(f), (540, 540), "the page's own ST.config size")
        one = self.tmp / "stills" / "one.jpg"
        out = json.loads(showtime("snap", self.proj, "--at", "0.5", "-o", one, "--json").stdout)
        self.assertEqual(Path(out["stills"][0]["file"]), one)
        self.assertEqual(image_size(one), (540, 540))
        out = json.loads(showtime("snap", self.proj, "--page", "square.html", "--size", "9:16", "--at", "0.5", "--json").stdout)
        f = Path(out["stills"][0]["file"])
        self.assertEqual(f.parent, self.proj / "work" / "snap-square-1080x1920")
        self.assertEqual(image_size(f), (1080, 1920))
        # render: the same page at another size for one run
        vid = self.tmp / "vertical.mp4"
        showtime("render", self.proj, "--page", "square.html", "--size", "9:16", "-o", vid, "--no-audio", "--workers", "1", "--quiet")
        from st import ff
        cp = subprocess.run([ff.ffprobe_path(), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                             "-of", "csv=p=0", str(vid)], stdout=subprocess.PIPE, encoding="utf-8", timeout=60)
        self.assertEqual(cp.stdout.strip(), "1080,1920")
        bad = showtime("snap", self.proj, "--at", "0.5,1", "-o", self.tmp / "two.jpg", check=False)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("exactly one --at", bad.stderr + bad.stdout)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

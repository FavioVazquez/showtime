#!/usr/bin/env python3
"""Living diagrams: runtime/diagram.js, runtime/diagram.css, templates/diagram, `showtime new diagram --theme`.

  * static: the files exist; the runtime has no wall clocks, timers or unseeded randomness; every example scene
    keeps its beat times in a CUE table; the guide is routed from SKILL.md
  * CLI: `new diagram --theme dark` sets the page's data-theme, showtime.json theme and background; --duration
    scales the CUE table; --theme on another template is an error
  * browser: spec validation names the bad keys; two seeks to the same t from different frames give the same
    SVG; pipes start on their ports and the depth order follows the port rule; a label pushed onto a part is
    reported as a collision; both themes render a frame (light paper, dark ground)

Stdlib only. usage: python tests/test_diagram.py [--fast] [-v]
  --fast   skip everything that needs a browser
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
RUNTIME = SKILL / "runtime" / "diagram.js"
TEMPLATE = SKILL / "templates" / "diagram"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
NODE = shutil.which("node", path=ENV.get("PATH"))
TMP = Path(tempfile.mkdtemp(prefix="st-diagram-"))


def showtime(*args, check=True, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


class TestStatic(unittest.TestCase):
    def test_files_present(self):
        for p in (RUNTIME, SKILL / "runtime" / "diagram.css", SKILL / "runtime" / "figure-film.js", SKILL / "runtime" / "figure.js",
                  SKILL / "runtime" / "figure.css", TEMPLATE / "figure.html", TEMPLATE / "examples" / "econ-lab.js",
                  TEMPLATE / "index.html", TEMPLATE / "scene.js",
                  TEMPLATE / "showtime.json", TEMPLATE / "examples" / "market.js", TEMPLATE / "examples" / "enter.js",
                  SKILL / "references" / "workflows" / "diagram.md"):
            self.assertTrue(p.is_file(), p)

    def test_no_clocks_timers_or_unseeded_random(self):
        # figure-film.js is loaded by every diagram film (index.html) and holds Figure.film: it is film code. The live
        # page's clock and timers are in figure.js, which only figure.html loads (TestLivePageStaysOffFilms).
        for p in [RUNTIME, SKILL / "runtime" / "figure-film.js"] + sorted(TEMPLATE.rglob("*.js")):
            code = re.sub(r"/\*.*?\*/|//[^\n]*", "", p.read_text(encoding="utf-8"), flags=re.S)
            for bad in ("Math.random", "Date.now", "new Date", "performance.now", "setTimeout", "setInterval",
                        "requestAnimationFrame", ".animate("):
                self.assertNotIn(bad, code, "%s uses %s" % (p.name, bad))

    def test_no_css_motion(self):
        """Motion in CSS (transitions, animations) runs on the wall clock, not on ST time."""
        for p in [SKILL / "runtime" / "diagram.css", SKILL / "runtime" / "figure.css", TEMPLATE / "index.html", TEMPLATE / "figure.html"]:
            css = re.sub(r"/\*.*?\*/", "", p.read_text(encoding="utf-8"), flags=re.S)
            for bad in ("transition", "animation", "@keyframes"):
                self.assertNotIn(bad, css, "%s uses CSS %s" % (p.name, bad))

    def test_live_page_stays_off_films(self):
        """The wall-clock live page (figure.js) is loaded by figure.html only, never by a film page."""
        self.assertNotIn("/_st/figure.js", (TEMPLATE / "index.html").read_text(encoding="utf-8"))
        self.assertIn("/_st/figure-film.js", (TEMPLATE / "index.html").read_text(encoding="utf-8"))
        fig = (TEMPLATE / "figure.html").read_text(encoding="utf-8")
        self.assertLess(fig.index("/_st/figure-film.js"), fig.index("/_st/figure.js"))

    def test_scenes_keep_beats_in_a_cue_table(self):
        """`showtime retime` scales `var CUE = {...}`: every scene has one, one number per line."""
        for p in [TEMPLATE / "scene.js"] + sorted((TEMPLATE / "examples").glob("*.js")):
            text = p.read_text(encoding="utf-8")
            m = re.search(r"var CUE = \{\n(.*?)\n\};", text, re.S)
            self.assertIsNotNone(m, p.name)
            lines = [l for l in m.group(1).splitlines() if l.strip()]
            self.assertTrue(all(re.match(r"^\s+\w+: [0-9.]+,$", l) for l in lines), (p.name, lines))
            self.assertTrue(any(l.strip().startswith("duration:") for l in lines), p.name)

    def test_template_poster_is_never_baked(self):
        cfg = json.loads((TEMPLATE / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg.get("render", {}).get("poster_bake"), "off")
        self.assertGreater(cfg["poster"], cfg["duration"] * 0.6, "the poster is the built figure, near the end")
        self.assertEqual(cfg.get("theme"), "light")

    def test_skill_routes_the_guide(self):
        self.assertIn("`diagram`", (SKILL / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("workflows/diagram.md", (SKILL / "references" / "index.md").read_text(encoding="utf-8"))


class TestCli(unittest.TestCase):
    def test_theme_dark(self):
        d = TMP / "dark"
        showtime("new", "diagram", d, "--theme", "dark")
        self.assertIn('data-theme="dark"', (d / "index.html").read_text(encoding="utf-8"))
        cfg = json.loads((d / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual((cfg["theme"], cfg["background"]), ("dark", "#0A0F19"))

    def test_duration_scales_the_cue_table(self):
        d = TMP / "long"
        showtime("new", "diagram", d, "-d", "30")
        old = re.search(r"compressor: ([0-9.]+),", (TEMPLATE / "scene.js").read_text(encoding="utf-8")).group(1)
        new = re.search(r"compressor: ([0-9.]+),", (d / "scene.js").read_text(encoding="utf-8")).group(1)
        old_d = json.loads((TEMPLATE / "showtime.json").read_text(encoding="utf-8"))["duration"]
        self.assertAlmostEqual(float(new), float(old) * 30 / old_d, places=2)
        self.assertEqual(json.loads((d / "showtime.json").read_text(encoding="utf-8"))["duration"], 30)

    def test_example_takes_its_own_length(self):
        """--example makes an example the scene at its own CUE.duration, so --duration scales from that base."""
        ex = (TEMPLATE / "examples" / "enter.js").read_text(encoding="utf-8")
        base = float(re.search(r"^  duration: ([0-9.]+),$", ex, re.M).group(1))
        answer = float(re.search(r"^  answer: ([0-9.]+),$", ex, re.M).group(1))
        d = TMP / "ex-enter"
        showtime("new", "diagram", d, "--example", "enter")
        cfg = json.loads((d / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["duration"], base)
        self.assertAlmostEqual(cfg["poster"], base - 0.8, places=2)
        self.assertIn("press *Enter*", (d / "scene.js").read_text(encoding="utf-8"))
        d2 = TMP / "ex-enter-30"
        showtime("new", "diagram", d2, "--example", "enter", "-d", "30")
        got = float(re.search(r"^  answer: ([0-9.]+),$", (d2 / "scene.js").read_text(encoding="utf-8"), re.M).group(1))
        self.assertAlmostEqual(got, answer * 30 / base, places=2)
        cp = showtime("new", "diagram", TMP / "ex-nope", "--example", "nope", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("examples of diagram: econ-lab, enter, market", cp.stderr + cp.stdout)

    def test_theme_keeps_an_explicit_background(self):
        d = TMP / "dark-bg"
        showtime("new", "diagram", d, "--theme", "dark", "--background=#112233")
        cfg = json.loads((d / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual((cfg["theme"], cfg["background"]), ("dark", "#112233"))

    def test_storyboard_is_refused_for_a_diagram(self):
        sb = TMP / "board.md"
        sb.write_text("| Shot | Length | Visual | Narration |\n|---|---|---|---|\n| a | 3 s | a plate | hello |\n", encoding="utf-8")
        cp = showtime("new", "diagram", TMP / "sb-diagram", "--from-storyboard", sb, check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("draws one scene spec", cp.stderr + cp.stdout)

    def test_theme_on_another_template_is_an_error(self):
        cp = showtime("new", "dom", TMP / "dom", "--theme", "dark", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("--theme is for the diagram template", cp.stderr + cp.stdout)
        self.assertFalse((TMP / "dom").exists() and any((TMP / "dom").iterdir()), "nothing is copied")


# The footer scene: footers on both sides, plates running under both, a tag 4 px above footer L's box, a small
# part just above footer R's text (inside the old CSS mask's feather), and footer R revealed only at 3 s
FOOT_SCENE = r"""
var CUE = {
  duration: 4,
};
window.SCENE = {
  page: { kicker: 'Footer test', title: 'Footer *mask*', dek: 'Plates fade under the footers; nothing else does.',
          footL: 'Illustrative sample · footer test', footR: 'made with showtime' },
  world: { scale: 10, origin: [400, 900] },
  items: [
    { id: 'plate', part: 'plate', at: [-10, -10, -2], size: [30, 30, 2], grid: 5 },
    { id: 'plate-r', part: 'plate', at: [70, -75, -2], size: [18, 18, 2], grid: 5 },
    { id: 'crate', part: 'box', at: [76.5, -68, 0], size: [3, 3, 1] },
  ],
  tags: [{ anchor: [0, 0, 0], tone: 'mute', text: 'near the footer', at: 0, off: [0, 35] }],
  reveal: [{ sel: '.ld-foot.r', at: 3 }],
};
"""

DRIVER = r"""
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, LIGHT, DARK, ENTER, MARKET, FOOT, FOOTDARK] = process.argv.slice(2);
const imp = (p) => import(pathToFileURL(path.join(SKILL, 'scripts', p)).href);
const { startServer } = await imp('server.mjs');
const { openBrowser, openStage } = await imp('lib/stagehost.mjs');
const { browser } = await openBrowser({ headless: true });
const out = {};
const consoleLines = [], pageErrors = [];
async function open(dir) {
  const srv = await startServer({ root: dir });
  const cfg = JSON.parse(fs.readFileSync(path.join(dir, 'showtime.json'), 'utf8'));
  const sess = await openStage(browser, { url: srv.url, config: cfg });
  sess.page.on('console', (m) => consoleLines.push(m.text()));
  sess.page.on('pageerror', (e) => pageErrors.push(String(e.message || e)));
  return { srv, sess, page: sess.page };
}
// the whole stage (svg and the HTML beat lines) at t, reached from different frames in different orders
async function sameT(dir) {
  const S = await open(dir);
  const dur = await S.page.evaluate(() => window.ST.duration || 20);
  const ts = []; for (let i = 0; i < 24; i++) ts.push(Math.round((0.3 + i * (dur - 0.6) / 23) * 1000) / 1000);
  const grab = async (order) => { const m = {}; for (const t of order) m[t] = await S.page.evaluate(async (x) => { await window.ST.seek(x); return document.querySelector('.ld-stage').outerHTML; }, t); return m; };
  const fwd = await grab(ts);
  const rev = await grab(ts.slice().reverse());
  const strided = await grab(ts.filter((t, i) => i % 3 === 0).concat(ts.filter((t, i) => i % 3 === 1).reverse(), ts.filter((t, i) => i % 3 === 2)));
  const bad = ts.filter((t) => fwd[t] !== rev[t] || fwd[t] !== strided[t]);
  await S.sess.close(); await S.srv.close?.();
  return { n: ts.length, bad };
}
const svgAt = (page, t) => page.evaluate(async (x) => { await window.ST.seek(x); return document.querySelector('#ld svg').outerHTML; }, t);
try {
  const L = await open(LIGHT);
  const page = L.page;
  // 1. validation names what is wrong
  out.errors = await page.evaluate(() => Diagram.validate({ world: { scale: 8, origin: [0, 0] }, items: [
    { id: 'a', part: 'sprocket', at: [0, 0, 0] }, { id: 'p', kind: 'pipe', from: 'ghost.top', to: 'a.top' }],
    labels: [{ for: 'nobody', at: 'soon', title: 'X' }], flows: [{ at: 1, path: [{ pipe: 'missing' }] }] }));
  out.okErrors = await page.evaluate(() => Diagram.validate(window.SCENE));
  // 2. determinism: the same t from different frames
  const a1 = await svgAt(page, 9.4); await svgAt(page, 0.5); await svgAt(page, 17.9);
  const a2 = await svgAt(page, 9.4);
  out.same = a1 === a2; out.len = a1.length;
  if (!out.same) { let i = 0; while (i < a1.length && a1[i] === a2[i]) i++; out.diff = [a1.slice(Math.max(0, i - 300), i + 200), a2.slice(Math.max(0, i - 300), i + 200)]; }
  // 3. ports and depth
  out.ports = await page.evaluate(() => {
    const D = Diagram.current, p = D.pipes;
    const end = (id, k) => (k ? p[id].p3[p[id].p3.length - 1] : p[id].p3[0]).map((v) => Math.round(v * 100) / 100);
    const ids = D.order.map((it) => it.id);
    return { suctionStart: end('suction', 0), suctionEnd: end('suction', 1), dischargeEnd: end('discharge', 1), order: ids, report: Diagram.report };
  });
  // 4b. depth without ports: a box wholly behind another along x is drawn first, even where the tie-break key
  //     says otherwise; a pinwheel of three boxes is a cycle, and the cycle is reported
  out.depth = await page.evaluate(() => {
    const mount = (id, items) => { const h = document.createElement('div'); h.id = id; h.style.cssText = 'position:absolute;left:0;top:0;width:1920px;height:1080px;visibility:hidden'; document.body.appendChild(h);
      return Diagram.mount({ world: { scale: 10, origin: [960, 300] }, avoid: '#none', items }, { host: '#' + id }); };
    const a = mount('ld-depth', [{ id: 'near', part: 'box', at: [3, 0, 0], size: [2, 2, 2] }, { id: 'long', part: 'box', at: [0, 0, 0], size: [2, 30, 2] }]);
    const b = mount('ld-cycle', [{ id: 'A', part: 'box', at: [0, 0, 2], size: [1, 10, 1] }, { id: 'B', part: 'box', at: [1, 0, 0], size: [1, 1, 3] }, { id: 'C', part: 'box', at: [0, 1, 0], size: [2, 1, 2] }]);
    return { order: a.order.map((it) => it.id), cycle: b.report.warnings };
  });
  // 4b'. a leader that runs up a tall part whose outline holds the anchor (a tower behind a crate) is reported:
  //      that part counts like the label's own (past halfway), it is not skipped
  out.tower = await page.evaluate(async () => {
    const h = document.createElement('div'); h.id = 'ld-tower'; h.style.cssText = 'position:absolute;left:0;top:0;width:1920px;height:1080px;visibility:hidden'; document.body.appendChild(h);
    const api = Diagram.mount({ world: { scale: 10, origin: [960, 700] }, avoid: '#none', items: [
      { id: 'tower', part: 'box', at: [0, 0, 0], size: [10, 10, 60] }, { id: 'crate', part: 'box', at: [10, 10, 0], size: [6, 6, 6] }],
      labels: [{ for: 'crate', at: 0, title: 'Crate', sub: 'in front of the tower', elbow: [-60, -500], side: 'left' }] }, { host: '#ld-tower' });
    await api.ready;
    return api.report.warnings;
  });
  // 4c. a scene without a world says so and stops (no exception); scene strings cannot break SVG attributes
  out.noWorld = await page.evaluate(() => { const h = document.createElement('div'); h.id = 'ld-noworld'; document.body.appendChild(h);
    try { return Diagram.mount({ items: [] }, { host: '#ld-noworld' }) === null; } catch (e) { return 'threw: ' + e.message; } });
  out.dash = await page.evaluate(() => { const h = document.createElement('div'); h.id = 'ld-dash'; h.style.cssText = 'visibility:hidden'; document.body.appendChild(h);
    const api = Diagram.mount({ world: { scale: 10, origin: [960, 300] }, items: [{ id: 'l', kind: 'link', path: [[0, 0, 0], [10, 0, 0]], dash: '6 4" data-x="1', opacity: '1" data-y="2', build: [-1, 0.1] }] }, { host: '#ld-dash' });
    api.render(1); return h.innerHTML; });
  // 4d. text that never shows inside the text safe zone is reported: a label in the bottom band (y 990-1000),
  //     a tag pushed off the frame, floor text outside the frame
  out.unsafe = await page.evaluate(async () => {
    const h = document.createElement('div'); h.id = 'ld-unsafe'; h.style.cssText = 'position:absolute;left:0;top:0;width:1920px;height:1080px;visibility:hidden'; document.body.appendChild(h);
    // the box's anchor sits at y 610, so the label's plate ends at y ~994: inside the old layout zone (1000), in the
    // phone band the renderer hides (below 990)
    const api = Diagram.mount({ world: { scale: 10, origin: [960, 660] }, avoid: '#none', items: [
      { id: 'a', part: 'box', at: [0, 0, 0], size: [10, 10, 10] }, { kind: 'floortext', at: [80, 80, 0], text: 'FAR AWAY', at0: 0 }],
      labels: [{ for: 'a', at: 0.5, title: 'Low', sub: 'in the band', elbow: [40, 335] }],
      tags: [{ for: 'a', text: 'gone', at: 0.5, off: [0, 900] }] }, { host: '#ld-unsafe' });
    await api.ready;
    const lb = api.report.labels.find((x) => x.title === 'Low');
    return api.report.warnings.concat(['rect-check ' + JSON.stringify(lb && lb.elbow)]);
  });
  // 4. a label pushed onto a part is reported
  out.collide = await page.evaluate(async () => {
    const host = document.createElement('div'); host.id = 'ld-test'; host.style.cssText = 'position:absolute;left:0;top:0;width:1920px;height:1080px;visibility:hidden';
    document.body.appendChild(host);
    const api = Diagram.mount({ world: { scale: 10, origin: [960, 300] }, avoid: '#none', items: [
      { id: 'a', part: 'box', at: [0, 0, 0], size: [20, 20, 20] }, { id: 'b', part: 'box', at: [24, 0, 0], size: [20, 20, 20] }],
      labels: [{ for: 'a', at: 0, title: 'Box A', sub: 'sits on box B', elbow: [180, 120], side: 'right' },
               { for: 'b', at: 0, title: 'Box B', sub: 'leader over A', elbow: [-330, 40], side: 'left' }] }, { host: '#ld-test' });
    await api.ready;
    return api.report;
  });
  await L.sess.close(); await L.srv.close?.();
  // 5. both themes render a frame
  const shot = async (dir) => {
    const S = await open(dir);
    await S.page.evaluate(async () => { await window.ST.seek(12); });
    const r = await S.page.evaluate(() => ({ theme: Diagram.report.theme, ground: getComputedStyle(document.querySelector('.ld-stage')).backgroundColor,
      parts: document.querySelectorAll('#ld-draw polygon').length, labels: [...document.querySelectorAll('[data-ld-label]')].filter((g) => g.getAttribute('visibility') === 'visible').length }));
    const png = await S.page.screenshot({ clip: { x: 60, y: 1000, width: 4, height: 4 } });
    r.png = png.length;
    await S.sess.close(); await S.srv.close?.();
    return r;
  };
  out.light = await shot(LIGHT);
  out.dark = await shot(DARK);
  // 7. the footer mask touches the floor layer only: a tag 4 px above a footer keeps its full colour, parts and text
  //    are never under a mask, the footers paint no backing, an empty footer paints nothing
  async function footCheck(dir) {
    const S = await open(dir);
    await S.page.evaluate(async () => { await window.ST.seek(2); });
    const o = await S.page.evaluate(() => {
      const masked = (sel) => { const e = document.querySelector(sel); return !!(e && (e.closest('[mask]'))); };
      const tag = document.querySelector('[data-ld-tag] rect'), tb = tag.getBoundingClientRect();
      const f = getComputedStyle(document.querySelector('.ld-foot.l'));
      return { rects: Diagram.report.footerMask, floor: masked('#ld-floor'), draw: masked('#ld-draw'), wtext: masked('#ld-wtext'),
        over: masked('#ld-over'), pillFill: getComputedStyle(tag).fill, shadow: f.boxShadow, bg: f.backgroundColor,
        tagBox: [tb.left, tb.top, tb.width, tb.height], footTop: document.querySelector('.ld-foot.l').getBoundingClientRect().top,
        warnings: Diagram.report.warnings };
    });
    // the pill's lowest rows, nearest the footer: inside the rounded end and below the text's baseline
    const b = o.tagBox, clip = { x: Math.round(b[0] + b[3] / 2 + 8), y: Math.round(b[1] + b[3] - 7), width: 6, height: 3 };
    const pixels = async (c) => S.page.evaluate(async (data) => {
      const img = new Image(); img.src = 'data:image/png;base64,' + data; await img.decode();
      const cv = document.createElement('canvas'); cv.width = img.width; cv.height = img.height; const g = cv.getContext('2d'); g.drawImage(img, 0, 0);
      return Array.from(g.getImageData(0, 0, img.width, img.height).data);
    }, (await S.page.screenshot({ clip: c })).toString('base64'));
    o.pillPixels = await pixels(clip);
    // how much of the plate shows inside each footer's box: mask on vs off, against the ground with no floor at all;
    // the footers' own text is made transparent so only the floor changes
    await S.page.addStyleTag({ content: '.ld-foot, .ld-foot * { color: transparent !important; }' });
    const box = (r) => ({ x: r[0] + 10, y: r[1] + 8, width: r[2] - 20, height: r[3] - 16 });
    const shot = async (t, how, c) => {
      await S.page.evaluate(async (a) => { await window.ST.seek(a.t);
        if (a.how === 'off') document.querySelector('#ld-floormask').removeAttribute('mask');
        if (a.how === 'ground') document.querySelector('#ld-floor').style.display = 'none'; }, { t, how });
      const p = await pixels(c);
      await S.page.evaluate(() => { document.querySelector('#ld-floor').style.display = ''; });
      return p;
    };
    const kept = async (t, r) => {   // share of the plate's difference from the ground that survives the mask
      const c = box(r), on = await shot(t, 'on', c), off = await shot(t, 'off', c), g = await shot(t, 'ground', c);
      let a = 0, b = 0, same = 0; for (let i = 0; i < on.length; i += 4) for (let k = 0; k < 3; k++) {
        a += Math.abs(on[i + k] - g[i + k]); b += Math.abs(off[i + k] - g[i + k]); same += Math.abs(on[i + k] - off[i + k]); }
      return { kept: b ? a / b : null, plate: b, onVsOff: same };
    };
    const [L, R] = o.rects;
    o.keptL = await kept(2, L);          // footer L is on screen from the start: its plate fades
    o.keptRBefore = await kept(1, R);    // footer R is revealed at 3 s: before, the plate under it is untouched
    o.keptRAfter = await kept(3.6, R);   // after the reveal it fades too
    o.emptyDisplay = await S.page.evaluate(() => { const r = document.querySelector('.ld-foot.r'); r.textContent = ''; return getComputedStyle(r).display; });
    await S.sess.close(); await S.srv.close?.();
    return o;
  }
  out.foot = await footCheck(FOOT);
  out.footDark = await footCheck(FOOTDARK);
  // 6. same t, same stage, on the examples that use leave/return labels, typed and pressed tags, packets, steps
  out.enterSame = await sameT(ENTER);
  out.marketSame = await sameT(MARKET);
  out.console = consoleLines.filter((l) => l.indexOf('[showtime] diagram:') === 0);
  out.pageErrors = pageErrors;
} finally { await browser.close(); }
console.log(JSON.stringify(out));
process.exit(0);
"""


@unittest.skipIf(FAST or not NODE, "--fast: no browser")
class TestBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        light, dark, enter, market = TMP / "b-light", TMP / "b-dark", TMP / "b-enter", TMP / "b-market"
        showtime("new", "diagram", light)
        showtime("new", "diagram", dark, "--theme", "dark")
        showtime("new", "diagram", enter, "--example", "enter")
        showtime("new", "diagram", market, "--example", "market")
        foot = TMP / "b-foot"
        showtime("new", "diagram", foot, "-d", "4")
        (foot / "scene.js").write_text(FOOT_SCENE, encoding="utf-8")
        foot_dark = TMP / "b-foot-dark"
        showtime("new", "diagram", foot_dark, "-d", "4", "--theme", "dark")
        (foot_dark / "scene.js").write_text(FOOT_SCENE, encoding="utf-8")
        drv = TMP / "drv.mjs"
        drv.write_text(DRIVER, encoding="utf-8")
        cp = subprocess.run([NODE, str(drv), str(SKILL), str(light), str(dark), str(enter), str(market), str(foot),
                             str(foot_dark)], env=ENV,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=600)
        assert cp.returncode == 0, cp.stderr[-3000:]
        cls.r = json.loads(cp.stdout.strip().splitlines()[-1])

    def test_validation_names_the_bad_keys(self):
        e = "\n".join(self.r["errors"])
        for want in ('unknown part "sprocket"', 'unknown part "ghost"', 'labels[0] "X": needs anchor', "at must be a number",
                     'unknown pipe "missing"'):
            self.assertIn(want, e)
        self.assertEqual(self.r["okErrors"], [], "the template's own scene is valid")

    def test_same_t_same_svg(self):
        self.assertTrue(self.r["same"], "two seeks to 9.4 s drew different SVG: %s" % self.r.get("diff"))
        self.assertGreater(self.r["len"], 20000)

    def test_pipes_start_on_their_ports(self):
        p = self.r["ports"]
        self.assertEqual(p["suctionStart"], [34, 37, 11.52])          # outdoor.out
        self.assertEqual(p["suctionEnd"][:2], [50, 30.6])            # compressor.in (its y+ side)
        self.assertEqual(p["dischargeEnd"], [66, 26, 22])            # wall.in (custom port)

    def test_depth_follows_the_port_rule(self):
        order = self.r["ports"]["order"]
        # discharge enters the wall's back face: drawn before the wall; suction leaves the outdoor unit's front face
        self.assertLess(order.index("discharge"), order.index("wall"))
        self.assertLess(order.index("outdoor"), order.index("suction"))
        self.assertLess(order.index("liquid"), order.index("indoor"))     # hangs from the indoor unit's bottom

    def test_template_labels_are_placed_clean(self):
        self.assertEqual(self.r["ports"]["report"]["warnings"], [])
        self.assertEqual(len(self.r["ports"]["report"]["labels"]), 4)

    def test_collision_is_reported(self):
        w = "\n".join(self.r["collide"]["warnings"])
        self.assertIn('label "Box A" collides', w)
        self.assertIn("part b", w)

    def test_leader_across_a_part_is_reported(self):
        self.assertRegex("\n".join(self.r["collide"]["warnings"]), r'label "Box B" collides:[^\n]*leader across part a')

    def test_leader_up_an_anchor_holding_part_is_reported(self):
        self.assertRegex("\n".join(self.r["tower"]), r'label "Crate" collides:[^\n]*leader across part tower \(\d+%\)')

    def test_collision_reaches_the_console_check_reads(self):
        """`showtime check` lists `[showtime] ...` console warnings: the collision must be there, not only in the report."""
        self.assertTrue(any(l.startswith('[showtime] diagram: label "Box A" collides') for l in self.r["console"]), self.r["console"])

    def test_text_outside_the_safe_zone_is_reported(self):
        w = "\n".join(self.r["unsafe"])
        self.assertTrue(re.search(r'label "Low" collides: outside|"Low" never shows fully inside', w), w)   # B1: the bottom band
        self.assertIn('"gone" never shows fully inside', w)
        self.assertIn('"FAR AWAY" never shows fully inside', w)
        self.assertTrue(any('"Low"' in l for l in self.r["console"]), self.r["console"])

    def test_depth_without_ports(self):
        o = self.r["depth"]["order"]
        self.assertLess(o.index("long"), o.index("near"), "a box wholly behind another along x is drawn first")
        self.assertTrue(any("cycle" in w for w in self.r["depth"]["cycle"]), self.r["depth"]["cycle"])

    def test_no_world_and_attribute_strings(self):
        self.assertIs(self.r["noWorld"], True)
        self.assertNotIn("data-x", self.r["dash"])
        self.assertNotIn("data-y", self.r["dash"])
        self.assertEqual(self.r["pageErrors"], [])

    def test_footer_mask_touches_the_floor_only(self):
        for theme, key in (("light", "foot"), ("dark", "footDark")):
            with self.subTest(theme=theme):
                self._floor_only(self.r[key])

    def _floor_only(self, f):
        self.assertEqual(len(f["rects"]), 2, f["rects"])                 # one hole per footer line with text
        self.assertTrue(f["floor"], "the floor layer is masked under the footers")
        self.assertFalse(f["draw"] or f["wtext"] or f["over"], "parts, floor text and tags are never masked")
        self.assertEqual(f["shadow"], "none")                            # the footers paint no backing of their own
        self.assertIn(f["bg"], ("rgba(0, 0, 0, 0)", "transparent"))
        self.assertEqual(f["emptyDisplay"], "none")                      # an empty footer paints nothing
        self.assertLess(f["tagBox"][1] + f["tagBox"][3], f["footTop"])   # the tag sits just above the footer box
        self.assertGreater(f["tagBox"][1] + f["tagBox"][3], f["footTop"] - 12)
        # the pill's lowest rows keep the fill the theme paints the tag with (read from the page, not hard-coded)
        want = [int(x) for x in re.findall(r"\d+", f["pillFill"])[:3]]
        px = f["pillPixels"]
        off = max(abs(px[i + k] - want[k]) for i in range(0, len(px), 4) for k in range(3))
        self.assertLessEqual(off, 16, "the tag's pill keeps its fill %s next to the footer: %s" % (f["pillFill"], px))
        self.assertEqual(f["warnings"], [])

    def test_footer_holes_fade_the_floor_and_follow_reveal(self):
        for theme, key in (("light", "foot"), ("dark", "footDark")):
            with self.subTest(theme=theme):
                self._holes(self.r[key])

    def _holes(self, f):
        for k in ("keptL", "keptRBefore", "keptRAfter"):
            self.assertGreater(f[k]["plate"], 0, "%s: no plate under the footer to measure (%s)" % (k, f[k]))
        self.assertLess(f["keptL"]["kept"], 0.2, f["keptL"])                    # the hole is where the footer is
        # not cut before its footer appears (the masked layer may differ by a few levels of raster noise, not a hole)
        self.assertGreater(f["keptRBefore"]["kept"], 0.99, f["keptRBefore"])
        self.assertLess(f["keptRAfter"]["kept"], 0.2, f["keptRAfter"])          # cut once it is on screen

    def test_same_t_same_stage_on_the_examples(self):
        for k in ("enterSame", "marketSame"):
            self.assertEqual(self.r[k]["bad"], [], "%s: different stage at %s after reseeking" % (k, self.r[k]["bad"]))
            self.assertEqual(self.r[k]["n"], 24)

    def test_both_themes_render(self):
        lt, dk = self.r["light"], self.r["dark"]
        self.assertEqual((lt["theme"], dk["theme"]), ("light", "dark"))
        self.assertGreater(lt["parts"], 25)
        self.assertGreater(dk["parts"], 25)
        self.assertGreaterEqual(lt["labels"], 1)
        lum = lambda c: sum(int(x) for x in re.findall(r"\d+", c)[:3]) / 3  # noqa: E731
        self.assertGreater(lum(lt["ground"]), 200)
        self.assertLess(lum(dk["ground"]), 60)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

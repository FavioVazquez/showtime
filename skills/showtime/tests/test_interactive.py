#!/usr/bin/env python3
"""Interactive living diagrams: Diagram.live (set / fire / focus / hit), the white theme, the engine fixes the live
figure needed, runtime/figure.js, `showtime export html --interactive` and check's walk through a figure's states.

  * film untouched: the film frames of the template (light, dark) and the examples are the ones the engine drew
    before live mode existed. tests/fixtures/diagram/film-frames.json is made by tests/fixtures/diagram/film-frames.sh
    <rev> from the diagram engine of that older revision (it checks the revision out in a temporary git worktree and
    draws today's template and examples with its runtime); the world drawing only (labels and tags depend on measured
    text, so they are compared within one browser elsewhere)
  * engine fixes, each with a test that fails on the old code: a stack shrinks when its count goes down; flow dashes
    on a link of their own colour show
  * live API: set (store level, stack count, tag text), fire (pulse, token route), focus (the veil on one part and
    its own wires), hit (the part under a point); film mode is unchanged by an idle live mount
  * the figure page, export --interactive and check: see the classes below

Stdlib only. usage: python tests/test_interactive.py [--fast] [-v] [--write-golden [--engine-from SKILL_DIR]]
  --fast          skip everything that needs a browser
  --write-golden  rewrite the film-frames fixture (film-frames.sh calls it with --engine-from)
  --engine-from   draw the frames with the runtime of this skill folder (an older checkout)
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
RUNTIME = SKILL / "runtime"
GOLDEN = TESTS_DIR / "fixtures" / "diagram" / "film-frames.json"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
WRITE_GOLDEN = "--write-golden" in sys.argv
ENGINE_FROM = None
if "--engine-from" in sys.argv:
    i = sys.argv.index("--engine-from")
    ENGINE_FROM = Path(sys.argv[i + 1]).resolve()
    del sys.argv[i:i + 2]
for flag in ("--fast", "--write-golden"):
    if flag in sys.argv:
        sys.argv.remove(flag)
ENV = build_env(showtime_home())
NODE = shutil.which("node", path=ENV.get("PATH"))
TMP = Path(tempfile.mkdtemp(prefix="st-interactive-"))


def showtime(*args, check=True, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def run_driver(src: str, *args, timeout=600, skill: Path = SKILL) -> dict:
    drv = TMP / ("drv-%d.mjs" % abs(hash(src)))
    drv.write_text(src, encoding="utf-8")
    # the showtime server inside a driver serves /_st/ from SHOWTIME_SKILL first: it must be the skill folder the
    # driver is run for (an older checkout with --engine-from), never the launcher's own
    cp = subprocess.run([NODE, str(drv), str(skill)] + [str(a) for a in args], env=dict(ENV, SHOWTIME_SKILL=str(skill)), stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout)
    assert cp.returncode == 0, cp.stderr[-3000:] + cp.stdout[-2000:]
    return json.loads(cp.stdout.strip().splitlines()[-1])


# the film's world drawing at 30 times per project: the plate, parts, pipes, flows, packets, veil and camera
FILM_DRIVER = r"""
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, ...DIRS] = process.argv.slice(2);
const imp = (p) => import(pathToFileURL(path.join(SKILL, 'scripts', p)).href);
const { startServer } = await imp('server.mjs');
const { openBrowser, openStage } = await imp('lib/stagehost.mjs');
const { browser } = await openBrowser({ headless: true });
const out = { frames: {} };
try {
  for (const dir of DIRS) {
    const srv = await startServer({ root: dir });
    // the engine drawing these frames is the one in SKILL (the old checkout when rebuilding the baseline)
    const served = await (await fetch(srv.url + '/_st/diagram.js')).text();
    out.served = (out.served !== false) && served === fs.readFileSync(path.join(SKILL, 'runtime', 'diagram.js'), 'utf8');
    const cfg = JSON.parse(fs.readFileSync(path.join(dir, 'showtime.json'), 'utf8'));
    const sess = await openStage(browser, { url: srv.url, config: cfg });
    const dur = await sess.page.evaluate(() => window.ST.duration || 20);
    const frames = {};
    for (let i = 0; i < 30; i++) {
      const t = Math.round((0.3 + i * (dur - 0.6) / 29) * 1000) / 1000;
      frames[t.toFixed(3)] = await sess.page.evaluate(async (x) => {
        await window.ST.seek(x);
        const q = (s) => { const e = document.querySelector('#ld ' + s); return e ? e.innerHTML : ''; };
        const s = document.querySelector('#ld #ld-world').getAttribute('transform') + '|' + q('#ld-floor') + '|' + q('#ld-draw') + '|' + q('#ld-bands');
        let h = 0x811c9dc5; for (let k = 0; k < s.length; k++) { h ^= s.charCodeAt(k); h = Math.imul(h, 0x01000193) >>> 0; }
        return h.toString(16) + ':' + s.length;
      }, t);
    }
    out.frames[path.basename(dir)] = frames;
    await sess.close(); await srv.close?.();
  }
} finally { await browser.close(); }
console.log(JSON.stringify(out));
process.exit(0);
"""


def film_projects() -> list:
    out = []
    for name, extra in (("light", ()), ("dark", ("--theme", "dark")), ("enter", ("--example", "enter")),
                        ("market", ("--example", "market"))):
        d = TMP / ("film-" + name)
        if not d.exists():
            showtime("new", "diagram", d, *extra)
        out.append(d)
    return out


@unittest.skipIf(FAST or not NODE, "--fast: no browser")
class TestFilmUntouched(unittest.TestCase):
    def test_a_planted_engine_change_changes_the_frames(self):
        """The rebuild recipe can see a difference: an engine copy with one extra element drawn differs everywhere."""
        mut = TMP / "mutant-skill"
        if not mut.exists():
            mut.mkdir()
            for e in SKILL.iterdir():
                if e.name != "runtime":
                    (mut / e.name).symlink_to(e)
            # the runtime is copied, not linked: the server refuses a file whose real path leaves its folder
            shutil.copytree(SKILL / "runtime", mut / "runtime")
            src = (SKILL / "runtime" / "diagram.js").read_text(encoding="utf-8")
            a = "gDraw.innerHTML = shadows + body + toks + top;"
            self.assertEqual(src.count(a), 1)
            (mut / "runtime" / "diagram.js").write_text(src.replace(a, "gDraw.innerHTML = '<g data-planted=\"1\"></g>' + shadows + body + toks + top;"), encoding="utf-8")
        res = run_driver(FILM_DRIVER, *film_projects()[:1], skill=mut)
        self.assertTrue(res["served"], "the server must serve the mutant's runtime")
        want = json.loads(GOLDEN.read_text(encoding="utf-8"))["film-light"]
        got = res["frames"]["film-light"]
        self.assertEqual([t for t in want if got.get(t) == want[t]], [], "every frame should differ from the baseline")

    def test_film_frames_match_the_engine_before_live_mode(self):
        # the server inside the driver serves /_st/ from the skill folder the driver imports it from: --engine-from
        # draws with that checkout's runtime (an older diagram.js), today's template and examples
        res = run_driver(FILM_DRIVER, *film_projects(), skill=ENGINE_FROM or SKILL)
        self.assertTrue(res["served"], "the frames must be drawn by the engine in %s" % (ENGINE_FROM or SKILL))
        got = res["frames"]
        if WRITE_GOLDEN:
            GOLDEN.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            self.skipTest("wrote %s" % GOLDEN)
        want = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(sorted(got), sorted(want))
        for name in want:
            bad = [t for t in want[name] if got[name].get(t) != want[name][t]]
            self.assertEqual(bad, [], "%s: the film's world drawing changed at t = %s" % (name, ", ".join(bad[:6])))


# the engine on its own, in the template's page: fixes and the live API (each live call is checked against the same
# keys written into a film spec: a live figure draws exactly what a film with those keys would)
ENGINE_DRIVER = r"""
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, DIR] = process.argv.slice(2);
const imp = (p) => import(pathToFileURL(path.join(SKILL, 'scripts', p)).href);
const { startServer } = await imp('server.mjs');
const { openBrowser, openStage } = await imp('lib/stagehost.mjs');
const { browser } = await openBrowser({ headless: true });
const out = {};
try {
  const srv = await startServer({ root: DIR });
  const cfg = JSON.parse(fs.readFileSync(path.join(DIR, 'showtime.json'), 'utf8'));
  const sess = await openStage(browser, { url: srv.url, config: cfg });
  const page = sess.page;
  const logs = []; page.on('console', (m) => logs.push(m.text()));
  Object.assign(out, await page.evaluate(async () => {
    let n = 0;
    const host = () => { const h = document.createElement('div'); h.id = 'ld-t' + (++n); h.style.cssText = 'position:absolute;left:0;top:0;width:1920px;height:1080px;visibility:hidden'; document.body.appendChild(h); return h; };
    const W = { world: { scale: 10, origin: [960, 400] }, avoid: '#none' };
    const film = (spec) => { const h = host(); return { h, api: Diagram.mount(Object.assign({}, W, spec), { host: h }) }; };
    const live = (spec) => { const h = host(); return { h, api: Diagram.live(Object.assign({}, W, spec), { host: h }) }; };
    const draw = (m, t) => { m.api.render(t); return m.h.querySelector('#ld-draw').innerHTML; };
    const r = {};
    // 1. a stack whose count goes down loses cells (the old engine kept every cell it had ever shown)
    const st = film({ items: [{ id: 's', part: 'stack', at: [0, 0, 0], size: [4, 4], max: 8, count: [[0, 2], [1, 6], [2, 3]] }] });
    const polys = (t) => (draw(st, t).match(/<polygon/g) || []).length;
    r.stack = { at05: polys(0.5), at18: polys(1.8), at25: polys(2.5) };
    // 2. flow dashes over a link of their own colour: they show as travelling gaps in the pipe body colour
    const fl = film({ items: [{ id: 'a', part: 'box', at: [0, 0, 0], size: [4, 4, 4] }, { id: 'b', part: 'box', at: [30, 0, 0], size: [4, 4, 4] },
      { id: 'w', kind: 'link', from: 'a.x+', to: 'b.x-', w: 3, tone: 'cold', build: [-1, 0.01] }],
      flows: [{ at: 0, speed: 60, spacing: 30, dash: 12, path: [{ pipe: 'w' }] }] });
    const svg = draw(fl, 3);
    const stroke = (svg.match(/<path d="[^"]*" fill="none" stroke="(#[0-9A-Fa-f]{6})"/) || [])[1];
    const fills = [...svg.matchAll(/<rect [^>]*fill="(#[0-9A-Fa-f]{6})"/g)].map((m) => m[1]);
    r.dash = { stroke, fills: [...new Set(fills)], n: fills.length, body: Diagram.themes.light.pipe.body };
    // 3. live keys draw what the same keys in a film spec draw
    const base = () => ({ items: [{ id: 'p', part: 'plate', at: [-5, -5, -1], size: [40, 40, 1], build: -1, lift: 0 },
      { id: 'a', part: 'box', at: [0, 0, 0], size: [5, 5, 5], build: -1 }, { id: 'tray', part: 'store', at: [10, 0, 0], size: [8, 6, 4], tone: 'hot', fill: 0.5, build: -1 },
      { id: 'stk', part: 'stack', at: [22, 0, 0], size: [4, 4], max: 8, count: [[-1, 3]], build: -1 },
      { id: 'w', kind: 'link', from: 'a.x+', to: 'tray.x-', w: 3, tone: 'mute', build: [-1, 0.01] }],
      tokens: [{ id: 'k', tone: 'hot', r: 1.2, moves: [] }] });
    const L = live(base());
    L.api.set('tray', 0.9, { at: 1, dur: 0.5 }); L.api.set('stk', 6, { at: 1.2 }); L.api.set('stk', 2, { at: 3 });
    L.api.fire('a', { at: 1.5, tone: 'hot', dur: 0.8 });
    L.api.fire('k', { at: 2, moves: [{ at: 0, dur: 0.01, to: 'a.top' }, { at: 0.1, dur: 0.8, along: 'w' }], stay: 0.4 });
    L.api.focus('a', { at: 4 });
    // the same keys written into a film spec
    const F2 = film(Object.assign(base(), {
      items: base().items.map((it) => it.id === 'tray' ? Object.assign({}, it, { fill: [[1, 0.5], [1.5, 0.9]] }) : it.id === 'stk' ? Object.assign({}, it, { count: [[-1, 3], [1.2, 6], [3, 2]] }) : it),
      states: [{ target: 'a', at: 1.5, tone: 'hot', dur: 0.8, pulse: true }],
      tokens: [{ id: 'k', tone: 'hot', r: 1.2, moves: [{ at: 2, dur: 0.01, to: 'a.top' }, { at: 2.1, dur: 0.8, along: 'w' }], until: 2.1 + 0.8 + 0.4 }],
      focus: [{ part: 'a', with: ['w'], at: 4, dur: 0.15, out: 0.15 }] }));
    r.same = [0.5, 1.2, 1.4, 1.9, 2.5, 3.1, 3.6, 4.1, 5].map((t) => ({ t, ok: draw(L, t) === draw(F2, t) }));
    r.incident = L.api.incident('a');
    // 4. live tags: a new value, its tone, then hidden
    const T = live({ items: [{ id: 'a', part: 'box', at: [0, 0, 0], size: [5, 5, 5], build: -1 }], tags: [{ id: 'v', for: 'a', text: 'name', at: -1, tone: 'mute' }] });
    await T.api.ready;
    const tagAt = (t) => { T.api.render(t); const g = T.h.querySelector('[data-ld-tag]'); const vis = [...g.querySelectorAll('text')].filter((e) => e.getAttribute('visibility') === 'visible').map((e) => e.textContent);
      return { vis, shown: g.getAttribute('visibility'), pill: g.querySelector('rect').getAttribute('fill') }; };
    r.tag0 = tagAt(0.5);
    T.api.set('v', 'up 1.3', { at: 1, tone: 'hot' });
    r.tag1 = tagAt(1.6);
    T.api.set('v', null, { at: 2 });
    r.tag2 = tagAt(2.6);
    T.api.set('v', 'back', { at: 3 });
    r.tag3 = tagAt(3.6);
    r.hotTag = Diagram.themes.light.tones.hot.tag;
    // 5. hit: the topmost part under a point; nothing on the empty ground
    const H = live({ items: [{ id: 'back', part: 'box', at: [0, 0, 0], size: [6, 6, 6], build: -1 }, { id: 'front', part: 'box', at: [6, 6, 0], size: [6, 6, 6], build: -1 }] });
    const c = (id) => { const b = H.api.box(id, 1); return [b.x + b.w / 2, b.y + b.h / 2]; };
    const cb = c('back'), cf = c('front');
    r.hit = { back: H.api.hit(cb[0], cb[1] - 20, 1), front: H.api.hit(cf[0], cf[1], 1), none: H.api.hit(20, 20, 1) };
    // 6. an idle live mount of the template draws the film's frames
    const A = film(window.SCENE), B = live(window.SCENE);
    r.idle = [1, 4.5, 9, 13.5, 18].map((t) => draw(A, t) === draw(B, t));
    // 7. the white theme
    const Wt = { h: host() }; Wt.api = Diagram.mount(Object.assign({}, W, { items: [{ id: 'a', part: 'box', at: [0, 0, 0], size: [5, 5, 5], build: -1 }] }), { host: Wt.h, theme: 'white' });
    r.white = { name: Wt.api.report.theme, ground: Diagram.themes.white.ground, top: draw(Wt, 1).indexOf(Diagram.themes.white.faces.top) >= 0 };
    return r;
  }));
  out.warnings = logs.filter((l) => /\[showtime\] diagram: (set|fire|focus)/.test(l));
  await sess.close(); await srv.close?.();
} finally { await browser.close(); }
console.log(JSON.stringify(out));
process.exit(0);
"""


@unittest.skipIf(FAST or not NODE, "--fast: no browser")
class TestEngine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = TMP / "engine"
        showtime("new", "diagram", d)
        cls.r = run_driver(ENGINE_DRIVER, d)

    def test_stack_shrinks_when_its_count_goes_down(self):
        s = self.r["stack"]
        per = (s["at18"] - s["at05"]) / 4.0          # count 2 -> 6: four cells
        self.assertGreater(per, 0)
        self.assertEqual(s["at25"], s["at05"] + per, "count 3 at t=2.5 should draw one cell more than count 2: %s" % s)

    def test_dashes_show_on_a_link_of_their_colour(self):
        d = self.r["dash"]
        self.assertGreater(d["n"], 2, d)
        self.assertNotIn(d["stroke"], d["fills"], "every dash is the link's own colour: invisible (%s)" % d)
        self.assertEqual(d["fills"], [d["body"]], d)

    def test_live_keys_draw_what_film_keys_draw(self):
        bad = [x["t"] for x in self.r["same"] if not x["ok"]]
        self.assertEqual(bad, [], "set/fire/focus differ from the same keys in a film spec at t = %s" % bad)
        self.assertEqual(self.r["incident"], ["w"])

    def test_live_tag_values_tone_and_hiding(self):
        self.assertEqual(self.r["tag0"]["vis"], ["name"])
        self.assertEqual(self.r["tag1"]["vis"], ["up 1.3"])
        self.assertEqual(self.r["tag1"]["pill"], self.r["hotTag"], "the value's tone colours the pill")
        self.assertEqual(self.r["tag2"]["shown"], "hidden")
        self.assertEqual(self.r["tag3"]["vis"], ["back"])
        self.assertEqual(self.r["tag3"]["shown"], "visible")

    def test_hit_finds_the_topmost_part(self):
        self.assertEqual(self.r["hit"], {"back": "back", "front": "front", "none": None})

    def test_an_idle_live_mount_draws_the_film(self):
        self.assertEqual(self.r["idle"], [True] * 5)

    def test_white_theme(self):
        w = self.r["white"]
        self.assertEqual(w["name"], "white")
        self.assertEqual(w["ground"], "#FFFFFF")
        self.assertTrue(w["top"])
        self.assertEqual(self.r["warnings"], [])


# the live page (figure.html through the showtime server) and the film a live scene makes of its tour
FIGURE_DRIVER = r"""
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, ECON, HEAT, ENTER] = process.argv.slice(2);
const imp = (p) => import(pathToFileURL(path.join(SKILL, 'scripts', p)).href);
const { startServer, injectStage } = await imp('server.mjs');
const { openBrowser, openStage } = await imp('lib/stagehost.mjs');
const { browser } = await openBrowser({ headless: true });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
// every positive check waits on the page's state (never on a fixed delay); the few negative ones ("nothing
// happens") wait a short bounded time after the state that would have made something happen
const until = (page, fn, arg) => page.waitForFunction(fn, arg, { timeout: 30000, polling: 50 });
const out = { errors: [] };
const srv = await startServer({ root: ECON }), heat = await startServer({ root: HEAT }), ent = await startServer({ root: ENTER });
const open = async (url, opts = {}, tourAfter = 60000) => {
  const ctx = await browser.newContext(Object.assign({ viewport: { width: 1440, height: 900 } }, opts));
  await ctx.addInitScript((ms) => { window.SHOWTIME_TEST_TOUR_AFTER = ms; }, tourAfter);
  const page = await ctx.newPage();
  page.on('pageerror', (e) => out.errors.push(String(e.message || e)));
  await page.goto(url);
  await until(page, () => window.Figure && Figure.current && Figure.current.api);
  await page.evaluate(() => Figure.current.api.ready);
  await until(page, () => Figure.current.cost.n >= 1);   // drawn at least once (reduced motion draws only on change)
  return { ctx, page };
};
const ro = (page) => page.evaluate(() => [...document.querySelectorAll('.fg-ro .ro')].map((e) => e.querySelector('.k').textContent + ' ' + e.querySelector('.v').textContent));
const board = (page) => page.evaluate(() => [...document.querySelectorAll('.fg-ld [data-ld-tag]')].filter((g) => g.getAttribute('visibility') === 'visible')
  .map((g) => [...g.querySelectorAll('text')].filter((t) => t.getAttribute('visibility') === 'visible').map((t) => t.textContent).join('')));
const roHas = (page, s) => until(page, (x) => [...document.querySelectorAll('.fg-ro .ro')].some((e) => (e.querySelector('.k').textContent + ' ' + e.querySelector('.v').textContent) === x), s);
const boardHas = (page, s) => until(page, (x) => [...document.querySelectorAll('.fg-ld [data-ld-tag]')].filter((g) => g.getAttribute('visibility') === 'visible' && +g.getAttribute('opacity') > 0.9)
  .some((g) => [...g.querySelectorAll('text')].some((t) => t.getAttribute('visibility') === 'visible' && t.textContent.indexOf(x) >= 0)), s);
try {
  // 1. desktop: live from the first frame, the tour, steps, the knob, hover, keys, the pointer
  { const { ctx, page } = await open(srv.url + '/figure.html', {}, 400);
    out.title = await page.evaluate(() => document.title);
    out.stage = await page.evaluate(() => !!window.ST);
    await page.evaluate(() => { window.__d0 = document.querySelector('.fg-ld #ld-draw').innerHTML; window.__n0 = Figure.current.cost.n; });
    await until(page, () => Figure.current.cost.n > window.__n0 + 5 && document.querySelector('.fg-ld #ld-draw').innerHTML !== window.__d0);
    out.moving = true;
    await until(page, () => Figure.current.tour()); out.tourOn = await page.isVisible('.fg-tour');
    await page.mouse.move(700, 300); await page.mouse.move(705, 305);
    await until(page, () => !Figure.current.tour()); out.tourAfterTouch = await page.isVisible('.fg-tour');
    await page.keyboard.press('3'); await roHas(page, 'Inflation +1.28'); out.cost15 = await ro(page);
    await page.click('.seg button:nth-child(3)'); await roHas(page, 'Inflation +0.84'); await boardHas(page, '(was +1.28)');
    out.cost3 = await ro(page); out.board3 = await board(page); out.hash3 = await page.evaluate(() => location.hash);
    await page.focus('.fg-part[data-part="infl"]');
    await until(page, () => Figure.current.S.hover === 'infl' && !document.querySelector('.fg-card').hidden && document.querySelector('.fg-card .n').textContent === 'Inflation'
      && /opacity="0\.6/.test(document.querySelector('.fg-ld #ld-draw').innerHTML));
    out.hover = await page.evaluate(() => ({ hover: Figure.current.S.hover, card: !document.querySelector('.fg-card').hidden, name: document.querySelector('.fg-card .n').textContent,
      value: document.querySelector('.fg-card .v').textContent, tone: document.querySelector('.fg-card .v').className, veil: true }));
    await page.evaluate(() => document.activeElement.blur()); await page.keyboard.press('Escape');
    await page.keyboard.press('ArrowRight'); await until(page, () => Figure.current.S.step === 3);
    out.afterRight = await page.evaluate(() => Figure.current.S.step);
    const p2 = await page.evaluate(() => {
      const F = Figure.current, fig = document.querySelector('.fg-fig').getBoundingClientRect(), st = document.querySelector('.fg .ld-stage');
      const m = /translate\(([-\d.]+)px,\s*([-\d.]+)px\) scale\(([\d.]+)\)/.exec(st.style.transform);
      const k = +m[3], ox = +m[1], oy = +m[2], b = F.api.box('firm', 50);
      return [fig.left + ox + (b.x + b.w / 2) * k, fig.top + oy + (b.y + b.h * 0.7) * k];
    });
    await page.mouse.move(p2[0], p2[1]); await page.mouse.move(p2[0] + 1, p2[1] + 1);
    await until(page, () => Figure.current.S.hover === 'firm'); out.pointer = 'firm';
    // hidden: the loop stops drawing
    await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange')); });
    await wait(200); const h0 = await page.evaluate(() => Figure.current.cost.n); await wait(800);
    out.hiddenFrames = (await page.evaluate(() => Figure.current.cost.n)) - h0;
    await ctx.close(); }
  // 2. a deep link opens a state
  { const { ctx, page } = await open(srv.url + '/figure.html#step=puzzle&q=12&part=infl');
    await roHas(page, 'Inflation today ×236.5');
    out.deep = await page.evaluate(() => ({ step: Figure.current.S.step, q: Figure.current.state.q, pin: Figure.current.S.pin, hash: location.hash }));
    out.deepRo = await ro(page);
    await ctx.close(); }
  // 3. reduced motion: no tour, still, input still works
  { const { ctx, page } = await open(srv.url + '/figure.html', { reducedMotion: 'reduce' }, 200);
    await wait(1200); out.rmTour = await page.isVisible('.fg-tour');
    const a = await page.screenshot(); await wait(700); const b = await page.screenshot(); out.rmStill = a.equals(b);
    await page.keyboard.press('2'); await roHas(page, 'Inflation +0.35'); out.rmRo = await ro(page);
    await ctx.close(); }
  // 4. phone: the words leave the drawing, chips in their own colours, nothing wider than the screen
  { const { ctx, page } = await open(srv.url + '/figure.html#step=cost&rule=3', { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
    await until(page, () => [...document.querySelectorAll('.fg-board span')].some((s) => /was/.test(s.textContent)));
    out.phone = await page.evaluate(() => ({ cls: document.documentElement.classList.contains('fg-phone'), wide: document.documentElement.scrollWidth, inner: innerWidth,
      labels: [...document.querySelectorAll('.fg-ld [data-ld-label]')].map((e) => getComputedStyle(e).display),
      chips: [...document.querySelectorAll('.fg-board span')].map((s) => [s.textContent, s.style.background]) }));
    await ctx.close(); }
  // 5. the walk: every state of the econ lab, the Enter teaser and the heat pump (no steps: its parts)
  { const { ctx, page } = await open(srv.url + '/figure.html'); out.walk = await page.evaluate(() => Figure.current.walk()); await ctx.close(); }
  { const { ctx, page } = await open(ent.url + '/figure.html'); out.walkEnter = await page.evaluate(() => Figure.current.walk());
    // the permission check asks: A answers it
    await page.evaluate(() => { Figure.current.setKnob('permission', 'ask'); Figure.current.enter(2); });
    await page.keyboard.press('a'); await until(page, () => Figure.current.state.answer === 'yes');
    out.enterAllow = await page.evaluate(() => [Figure.current.state.permission, Figure.current.state.answer]);
    await ctx.close(); }
  // a link cut after a % still opens the page (the bad pair is left out)
  { const { ctx, page } = await open(ent.url + '/figure.html#step=gate&part=bogus%'); await until(page, () => Figure.current.S.step === 2);
    out.badLink = await page.evaluate(() => ({ step: Figure.current.S.step, pin: Figure.current.S.pin, text: document.querySelector('.fg-step .t').textContent })); await ctx.close(); }
  // Enter: the setting and the answer tell one story
  { const { ctx, page } = await open(ent.url + '/figure.html#step=gate&permission=allow', { reducedMotion: 'reduce' });
    const board = () => page.evaluate(() => [...document.querySelectorAll('.fg-ld [data-ld-tag]')].filter((g) => g.getAttribute('visibility') === 'visible')
      .map((g) => [...g.querySelectorAll('text')].filter((t) => t.getAttribute('visibility') === 'visible').map((t) => t.textContent).join('')));
    await until(page, () => Figure.current.S.step === 2);
    out.enterAllow0 = { board: await board(), text: await page.evaluate(() => document.querySelector('.fg-step .t').textContent) };
    const shows = (t) => until(page, (x) => [...document.querySelectorAll('.fg-ld [data-ld-tag]')].some((g) => g.getAttribute('visibility') === 'visible'
      && [...g.querySelectorAll('text')].some((e) => e.getAttribute('visibility') === 'visible' && e.textContent === x)), t);
    await page.click('.seg button:nth-child(2)'); await shows('asks you');
    out.enterAsk = await board();
    out.enterButtons = await page.evaluate(() => [...document.querySelectorAll('.fg-keybtns button')].map((b) => b.textContent));
    await page.keyboard.press('d'); await shows('you said no');
    out.enterButtonsAfter = await page.evaluate(() => [...document.querySelectorAll('.fg-keybtns button')].length);
    out.enterNo = { board: await board(), text: await page.evaluate(() => document.querySelector('.fg-step .t').textContent) };
    await ctx.close(); }
  { const { ctx, page } = await open(heat.url + '/figure.html'); out.walkHeat = await page.evaluate(() => Figure.current.walk()); out.heatTitle = await page.evaluate(() => document.title); await ctx.close(); }
  // 6. the film of the tour: the same t from different frames, and the tour's values on the board
  { const cfg = JSON.parse(fs.readFileSync(path.join(ECON, 'showtime.json'), 'utf8'));
    const sess = await openStage(browser, { url: srv.url, config: cfg });
    const svgAt = (t) => sess.page.evaluate(async (x) => { await window.ST.seek(x); return document.querySelector('#ld svg').outerHTML; }, t);
    const a = await svgAt(15.5); await svgAt(40); await svgAt(3); const b = await svgAt(15.5);
    out.filmSame = a === b;
    out.filmLen = await sess.page.evaluate(() => Diagram.current.filmLength);
    out.filmLive = await sess.page.evaluate(() => typeof Figure.mount);
    await svgAt(15.5);
    out.filmBoard = await sess.page.evaluate(() => [...document.querySelectorAll('[data-ld-tag]')].filter((g) => g.getAttribute('visibility') === 'visible')
      .map((g) => [...g.querySelectorAll('text')].filter((t) => t.getAttribute('visibility') === 'visible').map((t) => t.textContent).join('')));
    await sess.close(); }
  out.inject = { live: injectStage('<html data-st-live><head></head></html>').includes('stage.js'), film: injectStage('<html><head></head></html>').includes('stage.js') };
} finally { await browser.close(); await srv.close?.(); await heat.close?.(); await ent.close?.(); }
console.log(JSON.stringify(out));
process.exit(0);
"""


def econ_project(name="econ") -> Path:
    d = TMP / name
    if not d.exists():
        showtime("new", "diagram", d, "--example", "econ-lab", "--theme", "white")
    return d


@unittest.skipIf(FAST or not NODE, "--fast: no browser")
class TestFigure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        heat, enter = TMP / "heat", TMP / "enter"
        showtime("new", "diagram", heat, "--theme", "white")
        showtime("new", "diagram", enter, "--example", "enter", "--theme", "white")
        cls.r = run_driver(FIGURE_DRIVER, econ_project(), heat, enter)

    def test_no_page_errors_and_no_stage(self):
        self.assertEqual(self.r["errors"], [])
        self.assertFalse(self.r["stage"], "a live page gets no stage.js")
        self.assertEqual(self.r["inject"], {"live": False, "film": True})

    def test_title_comes_from_the_scene(self):
        self.assertEqual(self.r["title"], "The lab with three equations")
        self.assertEqual(self.r["heatTitle"], "How a heat pump moves heat")

    def test_live_from_the_first_frame(self):
        self.assertTrue(self.r["moving"], "the loop's flow moves the drawing with nothing touched")

    def test_idle_tour_and_touch(self):
        self.assertTrue(self.r["tourOn"], "the tour starts when nobody touches the figure")
        self.assertFalse(self.r["tourAfterTouch"], "any input stops it")

    def test_steps_and_the_rule_knob(self):
        self.assertIn("Inflation +1.28", self.r["cost15"])
        self.assertIn("Inflation +0.84", self.r["cost3"])
        self.assertTrue(any("(was +1.28)" in t for t in self.r["board3"]), self.r["board3"])
        self.assertIn("rule=3", self.r["hash3"])
        self.assertIn("step=cost", self.r["hash3"])

    def test_hover_card_and_veil(self):
        h = self.r["hover"]
        self.assertEqual(h["hover"], "infl")
        self.assertTrue(h["card"])
        self.assertEqual(h["name"], "Inflation")
        self.assertIn("+0.84", h["value"])
        self.assertIn("fg-tone-hot", h["tone"], "inflation's value is warm on the card")
        self.assertTrue(h["veil"], "the focus veil is drawn over the other parts")

    def test_keys_and_pointer(self):
        self.assertEqual(self.r["afterRight"], 3, "ArrowRight goes to the next step")
        self.assertEqual(self.r["pointer"], "firm", "the pointer over a part hovers it")

    def test_a_cut_link_still_opens(self):
        b = self.r["badLink"]
        self.assertEqual((b["step"], b["pin"]), (2, ""), b)

    def test_enter_settings_and_answers_agree(self):
        a0 = self.r["enterAllow0"]
        self.assertIn("allowed", a0["board"])
        self.assertIn("Your settings allow it", a0["text"])
        self.assertNotIn("you said yes", " ".join(a0["board"]), "nobody was asked")
        self.assertIn("asks you", self.r["enterAsk"])
        self.assertNotIn("Bash: running the tests", self.r["enterAsk"], "switching to ask undoes allow's run")
        no = self.r["enterNo"]
        self.assertIn("you said no", no["board"])
        self.assertNotIn("Bash: running the tests", no["board"])
        self.assertIn("you said no", no["text"])
        self.assertEqual(self.r["enterButtons"], ["Allow (A)", "Deny (D)"], "a phone has no keys: the answers are buttons")
        self.assertEqual(self.r["enterButtonsAfter"], 0, "once answered, the buttons go")

    def test_hidden_page_draws_nothing(self):
        self.assertEqual(self.r["hiddenFrames"], 0)

    def test_deep_link(self):
        d = self.r["deep"]
        self.assertEqual((d["step"], d["q"], d["pin"]), (4, 12, "infl"))
        self.assertIn("Inflation today ×236.5", self.r["deepRo"])

    def test_reduced_motion(self):
        self.assertFalse(self.r["rmTour"])
        self.assertTrue(self.r["rmStill"], "under reduced motion the figure holds still")
        self.assertIn("Inflation +0.35", self.r["rmRo"], "and input still works")

    def test_phone(self):
        p = self.r["phone"]
        self.assertTrue(p["cls"])
        self.assertEqual(p["wide"], p["inner"], "nothing wider than the screen")
        self.assertEqual(set(p["labels"]), {"none"}, "labels leave the drawing on a phone")
        self.assertTrue(p["chips"], "the board's words are chips under the figure")
        self.assertTrue(all(bg for _, bg in p["chips"]), "each chip in its tag's colour: %s" % p["chips"])

    def test_walk_finds_nothing_on_the_examples(self):
        w = self.r["walk"]
        self.assertGreaterEqual(w["states"], 60)
        self.assertEqual(w["problems"], [])
        self.assertGreaterEqual(self.r["walkEnter"]["states"], 50)
        self.assertEqual(self.r["walkEnter"]["problems"], [])
        self.assertEqual(self.r["enterAllow"], ["ask", "yes"], "A answers the check when it asks; the setting stays ask")
        self.assertGreaterEqual(self.r["walkHeat"]["states"], 2)
        self.assertEqual(self.r["walkHeat"]["problems"], [])

    def test_the_film_of_the_tour(self):
        self.assertTrue(self.r["filmSame"], "the same t from different frames draws the same film frame")
        self.assertEqual(self.r["filmLive"], "undefined", "a film page loads figure-film.js only, never the live page")
        self.assertAlmostEqual(self.r["filmLen"], 67.3, places=2)
        self.assertTrue(any(t.startswith("↑ gap") for t in self.r["filmBoard"]), self.r["filmBoard"])


# export --interactive: one offline file, the scene's title, no network, every state clean; check walks a figure
FILE_DRIVER = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, FILE] = process.argv.slice(2);
const imp = (p) => import(pathToFileURL(path.join(SKILL, 'scripts', p)).href);
const { openBrowser } = await imp('lib/stagehost.mjs');
const { browser } = await openBrowser({ headless: true });
const out = { errors: [], requests: [] };
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => out.errors.push(String(e.message || e)));
  page.on('console', (m) => { if (m.type() === 'error') out.errors.push(m.text()); });
  page.on('request', (r) => { if (!/^(file|data|blob):/.test(r.url())) out.requests.push(r.url()); });
  await page.goto(pathToFileURL(FILE).href + '#step=cost&rule=0.8');
  await page.waitForFunction(() => window.Figure && Figure.current);
  await page.evaluate(() => Figure.current.api.ready);
  await new Promise((r) => setTimeout(r, 1500));
  out.fonts = await page.evaluate(() => [...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family));
  out.walk = await page.evaluate(() => Figure.current.walk());
  await ctx.close();
} finally { await browser.close(); }
console.log(JSON.stringify(out));
process.exit(0);
"""


@unittest.skipIf(FAST or not NODE, "--fast: no browser")
class TestExportInteractive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.econ = econ_project("econ-x")
        cls.out = TMP / "econ-figure.html"
        cp = showtime("export", "html", cls.econ, "--interactive", "-o", cls.out, "--json")
        cls.report = json.loads(cp.stdout)
        cls.html = cls.out.read_text(encoding="utf-8")
        cls.r = run_driver(FILE_DRIVER, cls.out)

    def test_one_offline_file(self):
        self.assertTrue(self.report["interactive"])
        self.assertLess(self.report["bytes"], 1000 * 1000, "a live figure stays under 1 MB")
        self.assertIn('http-equiv="Content-Security-Policy"', self.html)
        self.assertNotRegex(self.html, r'(?:src|href)="/_(?:st|lib)/', "every runtime file is inlined")
        self.assertNotIn("/_st/stage.js", self.html)
        self.assertEqual(self.r["requests"], [])
        self.assertEqual(self.r["errors"], [])
        self.assertEqual(set(self.r["fonts"]), {"Inter", "JetBrains Mono"})

    def test_title_and_link_preview(self):
        self.assertIn("<title>The lab with three equations</title>", self.html)
        self.assertIn('property="og:title" content="The lab with three equations"', self.html)
        self.assertIn('property="og:description"', self.html)

    def test_every_state_clean_offline(self):
        self.assertGreaterEqual(self.r["walk"]["states"], 60)
        self.assertEqual(self.r["walk"]["problems"], [])

    def test_export_runs_no_project_code(self):
        """The export reads the scene's words; it never runs scene.js (project code only runs inside the browser)."""
        d = TMP / "hostile"
        showtime("new", "diagram", d, "--theme", "white")
        m1, m2 = TMP / "pwned-require.txt", TMP / "pwned-process.txt"
        with open(d / "scene.js", "a", encoding="utf-8") as f:
            f.write("\ntry { require('fs').writeFileSync(%s, 'x'); } catch (e) {}\n"
                    "try { this.constructor.constructor('return process')().getBuiltinModule('fs').writeFileSync(%s, 'x'); } catch (e) {}\n"
                    % (json.dumps(str(m1)), json.dumps(str(m2))))
        out = TMP / "hostile.html"
        showtime("export", "html", d, "--interactive", "-o", out)
        self.assertFalse(m1.exists())
        self.assertFalse(m2.exists())
        self.assertIn("<title>How a heat pump moves heat</title>", out.read_text(encoding="utf-8"))

    def test_licence_notices(self):
        head = self.html.split("-->", 1)[0]
        self.assertIn("SIL Open Font License", head)
        self.assertIn("@fontsource-variable/inter", head)
        self.assertIn("@fontsource-variable/jetbrains-mono", head)
        self.assertIn("MIT licensed", head)

    def test_artifact_target_and_refusals(self):
        out = TMP / "econ-artifact.html"
        showtime("export", "html", self.econ, "--interactive", "--target", "artifact", "-o", out)
        self.assertTrue(out.is_file())
        cp = showtime("export", "html", self.econ, "--interactive", "--folder", "-o", TMP / "dir-out", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("--interactive writes one file", cp.stderr + cp.stdout)
        bare = TMP / "bare"
        bare.mkdir(exist_ok=True)
        (bare / "showtime.json").write_text('{"title": "x", "width": 1920, "height": 1080, "fps": 30, "duration": 5}', encoding="utf-8")
        (bare / "index.html").write_text("<!doctype html><html><body>x</body></html>", encoding="utf-8")
        cp = showtime("export", "html", bare, "--interactive", "-o", TMP / "bare.html", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("no scene.js", cp.stderr + cp.stdout)


# words that look like markup or replacement patterns stay words: in the live page and in the exported file
EVIL_SCENE = r"""
window.SCENE.labels[0].title = '</script><img src=x onerror="window.__pwned=1">';
window.SCENE.tags = (window.SCENE.tags || []).concat([{ id: 'evil', for: 'compressor', text: '<img src=x onerror=window.__pwned=2>', at: -1 }]);
window.SCENE.interactive.title = 'Evil </script><img src=x onerror=window.__pwned=3> $& $\' $1 title';
window.SCENE.interactive.steps = [{ id: 's1', kicker: '<img src=x onerror=window.__pwned=4>', text: '</script><b>bold?</b>' }];
window.SCENE.tags = window.SCENE.tags.concat([{ id: 'dbl', for: 'valve', text: 'a<!--<script>b', at: -1 }, { id: 'caps', for: 'outdoor', text: '</SCRIPT >x', at: -1 }]);
"""
EVIL_TITLE = "Evil </script><img src=x onerror=window.__pwned=3> $& $' $1 title"

EVIL_DRIVER = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, DIR, FILE] = process.argv.slice(2);
const imp = (p) => import(pathToFileURL(path.join(SKILL, 'scripts', p)).href);
const { startServer } = await imp('server.mjs');
const { openBrowser } = await imp('lib/stagehost.mjs');
const { browser } = await openBrowser({ headless: true });
const srv = await startServer({ root: DIR });
const out = {};
const look = async (url) => {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(url);
  await page.waitForFunction(() => window.Figure && Figure.current, null, { timeout: 30000 });
  await page.evaluate(() => Figure.current.api.ready);
  await page.waitForFunction(() => Figure.current.cost.n > 2, null, { timeout: 30000 });
  const r = await page.evaluate(() => ({ pwned: window.__pwned || null, imgs: document.querySelectorAll('img').length, bold: document.querySelectorAll('.fg b').length,
    title: document.title, h1: document.querySelector('.fg h1').textContent, kicker: document.querySelector('.fg-step .k').textContent,
    texts: [...document.querySelectorAll('.fg-ld text')].map((t) => t.textContent) }));
  await ctx.close();
  return r;
};
try { out.live = await look(srv.url + '/figure.html'); out.file = await look(pathToFileURL(FILE).href); }
finally { await browser.close(); await srv.close?.(); }
console.log(JSON.stringify(out));
process.exit(0);
"""


# scene code the escaping must leave working: a name that starts with "script" after a < (the minifier writes
# `i<scriptSteps`), and comment openers inside strings
CODE_SCENE = r"""
var scriptSteps = 2; for (var i = 0; i < scriptSteps; i++) { window.__steps = i; }
var Scripted = { n: 3 }; window.__cmp = 1 < Scripted.n;
window.__cmt = 'a<!--<script>b' + "c<!--d" + `e<!--<SCRIPT>f`;
"""

CODE_DRIVER = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, FILE] = process.argv.slice(2);
const imp = (p) => import(pathToFileURL(path.join(SKILL, 'scripts', p)).href);
const { openBrowser } = await imp('lib/stagehost.mjs');
const { browser } = await openBrowser({ headless: true });
const out = { errors: [] };
try {
  const page = await (await browser.newContext()).newPage();
  page.on('pageerror', (e) => out.errors.push(String(e.message || e)));
  await page.goto(pathToFileURL(FILE).href);
  await page.waitForFunction(() => window.Figure && Figure.current, null, { timeout: 30000 }).catch(() => {});
  out.r = await page.evaluate(() => ({ figure: !!(window.Figure && Figure.current), steps: window.__steps, cmp: window.__cmp, cmt: window.__cmt, charset: document.characterSet }));
} finally { await browser.close(); }
console.log(JSON.stringify(out));
process.exit(0);
"""


@unittest.skipIf(FAST or not NODE, "--fast: no browser")
class TestExportKeepsCodeWorking(unittest.TestCase):
    def test_script_names_and_comment_openers(self):
        d = TMP / "code"
        showtime("new", "diagram", d, "--theme", "white")
        with open(d / "scene.js", "a", encoding="utf-8") as f:
            f.write(CODE_SCENE)
        out = TMP / "code-figure.html"
        showtime("export", "html", d, "--interactive", "-o", out)
        html = out.read_bytes()
        self.assertLess(html.find(b'<meta charset="utf-8">'), 1024, "the charset sits in the first 1024 bytes")
        r = run_driver(CODE_DRIVER, out)
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["r"], {"figure": True, "steps": 1, "cmp": True, "cmt": "a<!--<script>bc<!--de<!--<SCRIPT>f", "charset": "UTF-8"})


class TestSceneWords(unittest.TestCase):
    """The export reads the scene's title as text: the interactive block's own keys, outside comments and strings."""
    def words(self, src):
        d = TMP / ("words-%d" % abs(hash(src)))
        d.mkdir(exist_ok=True)
        (d / "scene.js").write_text(src, encoding="utf-8")
        cp = subprocess.run([NODE, "--input-type=module", "-e",
                             "import { sceneInfo } from %s; console.log(JSON.stringify(sceneInfo(%s)));" % (
                                 json.dumps((SKILL / "scripts" / "lib" / "export" / "figure.mjs").as_uri()), json.dumps(str(d)))],
                            env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        return json.loads(cp.stdout)

    @unittest.skipIf(not NODE, "no node")
    def test_own_keys_only(self):
        w = self.words("window.SCENE = { labels: [{ title: 'A label' }], interactive: { steps: [{ title: 'nested' }], sub: 'Sub' },"
                       " page: { title: 'The *page* title' } };")
        self.assertEqual(w, {"title": "The page title", "description": "Sub"})

    @unittest.skipIf(not NODE, "no node")
    def test_comments_strings_and_escapes(self):
        w = self.words("// interactive: { title: 'commented' }\nvar s = 'interactive: { title: \"in a string\" }';\n"
                       "window.SCENE = { interactive: { title: 'Real \\u2019s \\'quoted\\'', sub: 'a' + 'b' } };")
        self.assertEqual(w["title"], "Real \u2019s 'quoted'")
        self.assertEqual(w["description"], "", "a value built by code is not read")


@unittest.skipIf(FAST or not NODE, "--fast: no browser")
class TestEscaping(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = TMP / "evil"
        showtime("new", "diagram", d, "--theme", "white")
        with open(d / "scene.js", "a", encoding="utf-8") as f:
            f.write(EVIL_SCENE)
        cls.out = TMP / "evil-figure.html"
        showtime("export", "html", d, "--interactive", "-o", cls.out, "--title", EVIL_TITLE)
        cls.html = cls.out.read_text(encoding="utf-8")
        cls.r = run_driver(EVIL_DRIVER, d, cls.out)

    def test_markup_in_scene_words_stays_text(self):
        for where in ("live", "file"):
            r = self.r[where]
            self.assertIsNone(r["pwned"], where)
            self.assertEqual(r["imgs"], 0, where)
            self.assertEqual(r["bold"], 0, where)
            self.assertEqual(r["h1"], EVIL_TITLE, where)
            self.assertEqual(r["kicker"], "<img src=x onerror=window.__pwned=4>", where)
            self.assertIn('</script><img src=x onerror="window.__pwned=1">', r["texts"], where)
            self.assertIn("<img src=x onerror=window.__pwned=2>", r["texts"], where)
            self.assertIn("a<!--<script>b", r["texts"], "%s: a comment opener in a scene string keeps the page working" % where)
            self.assertIn("</SCRIPT >x", r["texts"], "%s: the text keeps its own case" % where)

    def test_exported_title_is_verbatim(self):
        self.assertEqual(self.r["file"]["title"], EVIL_TITLE, "replacement patterns ($& $' $1) and markup stay text")
        self.assertNotIn("<!--<script", self.html.split("-->", 1)[1], "no comment opener reaches the parser inside a script")
        self.assertIn("$&amp; $'", self.html)
        self.assertNotIn("</script><img", self.html, "scene text cannot close the script it is packed in")
        self.assertNotIn("</script><b>", self.html)


# the walk catches what it says it checks: planted faults at states only a full walk reaches
PLANTED = r"""
(function () {
  var I = window.SCENE.interactive, r0 = I.readouts;
  I.steps[1].id = 'loop';                                   // two steps share an id: a link to the second opens the first
  I.readouts = function (s, st) {                           // a broken readout at one value inside the slider's range
    var o = r0(s, st); if (st === 'puzzle' && s.q === 5) o.rows = o.rows.concat([{ k: 'planted', v: String(1 / 0), u: '' }]); return o;
  };
  I.keys = { z: function (fx, s, st) { if (st === 'cost') s.planted = true; } };
  I.agree = function (s, st) { return s.planted ? ['planted contradiction after Z'] : []; };
})();
"""

WALK_DRIVER = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, DIR] = process.argv.slice(2);
const imp = (p) => import(pathToFileURL(path.join(SKILL, 'scripts', p)).href);
const { startServer } = await imp('server.mjs');
const { openBrowser } = await imp('lib/stagehost.mjs');
const { browser } = await openBrowser({ headless: true });
const srv = await startServer({ root: DIR });
let out = {};
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, reducedMotion: 'reduce' });
  const page = await ctx.newPage();
  await page.goto(srv.url + '/figure.html');
  await page.waitForFunction(() => window.Figure && Figure.current, null, { timeout: 30000 });
  await page.evaluate(() => Figure.current.api.ready);
  out = await page.evaluate(() => Figure.current.walk());
} finally { await browser.close(); await srv.close?.(); }
console.log(JSON.stringify(out));
process.exit(0);
"""


@unittest.skipIf(FAST or not NODE, "--fast: no browser")
class TestWalkCatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = TMP / "planted-walk"
        showtime("new", "diagram", d, "--example", "econ-lab", "--theme", "white")
        with open(d / "scene.js", "a", encoding="utf-8") as f:
            f.write(PLANTED)
        cls.r = run_driver(WALK_DRIVER, d)
        cls.msgs = [(p["code"], p.get("where", ""), p["message"]) for p in cls.r["problems"]]

    def test_duplicate_step_id_and_the_link_it_breaks(self):
        self.assertTrue(any(c == "figure_link" and "share the id" in m for c, w, m in self.msgs), self.msgs)
        self.assertTrue(any(c == "figure_link" and "opens another state" in m for c, w, m in self.msgs), self.msgs)

    def test_every_value_of_a_short_range(self):
        self.assertTrue(any(c == "figure_readout" and "q=5" in w for c, w, m in self.msgs), self.msgs)

    def test_the_scenes_keys_and_its_story(self):
        self.assertEqual(self.r["keys"], 1)
        self.assertTrue(any(c == "figure_story" and "key Z" in w for c, w, m in self.msgs), self.msgs)


@unittest.skipIf(FAST or not NODE, "--fast: no browser")
class TestCheckWalk(unittest.TestCase):
    def test_check_reports_a_figure_overlap(self):
        d = TMP / "planted"
        showtime("new", "diagram", d, "--theme", "white")
        # two tags on the same spot of the same part: the walk sees them overlap in the figure's first state
        with open(d / "scene.js", "a", encoding="utf-8") as f:
            f.write("\nwindow.SCENE.tags = (window.SCENE.tags || []).concat([{ id: 'p1', for: 'compressor', text: 'PLANTED ONE', at: -1, off: [0, -60] },"
                    " { id: 'p2', for: 'compressor', text: 'PLANTED TWO', at: -1, off: [10, -56] }]);\n")
        cp = showtime("check", d, "--json", check=False, timeout=900)
        rep = json.loads(cp.stdout)
        codes = [(f["code"], f["message"]) for f in rep["findings"] if f["code"].startswith("figure_")]
        self.assertTrue(any(c == "figure_text_overlap" and "PLANTED" in m for c, m in codes), codes)
        self.assertGreaterEqual(rep["figure"]["states"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2 if "-v" in sys.argv else 1)

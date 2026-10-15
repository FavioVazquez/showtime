#!/usr/bin/env python3
"""The "press a key" living diagram: `showtime new diagram <dir> --example computer`
(templates/diagram/examples/computer.js), a live figure you type on.

  * static: the example's USB HID usage ids are the standard ones (Keyboard/Keypad page 0x07), its numbers are
    marked typical and illustrative, the honest line is on the film and the live page, it films its tour
  * browser: the exported figure (one offline file) takes typing from the keyboard: 'hi' lands on the screen tag
    and in the RAM buffer, the controller shows the last key's code (0x0C for 'i'); Backspace and Enter work; a
    click on a key types it; no console error and no network request; every state walks clean

Stdlib only. usage: python tests/test_figure_computer.py [--fast] [-v]
  --fast   skip the browser check
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
EXAMPLE = SKILL / "templates" / "diagram" / "examples" / "computer.js"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
NODE = shutil.which("node", path=ENV.get("PATH"))
TMP = Path(tempfile.mkdtemp(prefix="st-figure-computer-"))


def showtime(*args, check=True, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def run_driver(src: str, *args, timeout=600) -> dict:
    drv = TMP / "drv.mjs"
    drv.write_text(src, encoding="utf-8")
    cp = subprocess.run([NODE, str(drv), str(SKILL)] + [str(a) for a in args], env=dict(ENV, SHOWTIME_SKILL=str(SKILL)),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout)
    assert cp.returncode == 0, cp.stderr[-3000:] + cp.stdout[-2000:]
    return json.loads(cp.stdout.strip().splitlines()[-1])


class TestComputerExample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = EXAMPLE.read_text(encoding="utf-8")

    def test_hid_usage_ids_are_the_standard_ones(self):
        js = self.js
        self.assertIn("HID[c] = 0x04 + i", js, "a-z are 0x04-0x1D")
        self.assertIn("HID[c] = 0x1E + i", js, "1-9 are 0x1E-0x26 and 0 is 0x27, in the order '1234567890'")
        self.assertIn("'1234567890'", js)
        for key, code in (("'\\n'", "0x28"), ("'\\b'", "0x2A"), ("'\\t'", "0x2B"), ("' '", "0x2C"), ("'-'", "0x2D"),
                          ("';'", "0x33"), ("'/'", "0x38"), ("shiftL", "0xE1")):
            self.assertRegex(js, re.escape(key) + r": " + code + r"\b", key)

    def test_honest_numbers(self):
        line = "Simplified and illustrative: real machines add layers (drivers, compositor) and vary."
        self.assertIn("footL: '%s'" % line, self.js, "the film says it")
        self.assertIn("source: '%s" % line, self.js, "the live page says it")
        self.assertIn("typical", self.js)
        self.assertIn("illustrative", self.js)
        self.assertNotRegex(self.js, r"\b[Mm]easured\b(?! machines often take longer)", "nothing is presented as measured")

    def test_films_its_tour(self):
        self.assertIn("film: 'tour'", self.js)
        self.assertRegex(self.js, r"var CUE = \{\n  duration: [0-9.]+,\n\};")
        self.assertIn("type: { hint: 'Type on it', run:", self.js)

    def test_new_takes_the_example(self):
        d = TMP / "static"
        showtime("new", "diagram", d, "--example", "computer", "--theme", "white")
        cfg = json.loads((d / "showtime.json").read_text(encoding="utf-8"))
        dur = float(re.search(r"duration: ([0-9.]+),", self.js).group(1))
        self.assertEqual(cfg["duration"], dur)
        self.assertEqual(cfg["title"], "What happens when you press a key")


FILE_DRIVER = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, FILE] = process.argv.slice(2);
const imp = (p) => import(pathToFileURL(path.join(SKILL, 'scripts', p)).href);
const { openBrowser } = await imp('lib/stagehost.mjs');
const { browser } = await openBrowser({ headless: true });
const out = { errors: [], requests: [] };
const until = (page, fn, arg) => page.waitForFunction(fn, arg, { timeout: 30000, polling: 50 });
const tag = (page, id) => page.evaluate((x) => { const g = document.querySelector('.fg-ld [data-ld-tag="' + x + '"]');
  if (!g || g.getAttribute('visibility') !== 'visible') return null;
  return [...g.querySelectorAll('text')].filter((t) => t.getAttribute('visibility') === 'visible').map((t) => t.textContent).join(''); }, id);
const tagIs = (page, id, s) => until(page, (a) => { const g = document.querySelector('.fg-ld [data-ld-tag="' + a[0] + '"]');
  return g && g.getAttribute('visibility') === 'visible' && +g.getAttribute('opacity') > 0.9
    && [...g.querySelectorAll('text')].some((t) => t.getAttribute('visibility') === 'visible' && t.textContent.replace(/\u00a0/g, ' ') === a[1]); }, [id, s]);
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.addInitScript(() => { window.SHOWTIME_TEST_TOUR_AFTER = 600000; });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => out.errors.push(String(e.message || e)));
  page.on('console', (m) => { if (m.type() === 'error') out.errors.push(m.text()); });
  page.on('request', (r) => { if (!/^(file|data|blob):/.test(r.url())) out.requests.push(r.url()); });
  await page.goto(pathToFileURL(FILE).href);
  await until(page, () => window.Figure && Figure.current && Figure.current.api);
  await page.evaluate(() => Figure.current.api.ready);
  out.typeField = await page.isVisible('.fg-type input');
  // real typing, from the page's keyboard
  await page.mouse.click(4, 4);
  await page.keyboard.type('hi', { delay: 90 });
  await tagIs(page, 'screen', 'on screen: hi');
  out.screen = await tag(page, 'screen');
  out.buffer = await tag(page, 'buffer');
  out.code = await tag(page, 'code');
  out.ro = await page.evaluate(() => [...document.querySelectorAll('.fg-ro .ro')].map((e) => e.querySelector('.k').textContent + ' ' + e.querySelector('.v').textContent));
  // Backspace, then Enter: a new, empty line
  await page.keyboard.press('Backspace');
  await tagIs(page, 'screen', 'on screen: h');
  await page.keyboard.press('Enter');
  await tagIs(page, 'screen', 'on screen: (empty line)');
  out.buffer2 = await tag(page, 'buffer');
  // a click on the drawn 'a' key types it
  const pt = await page.evaluate(() => {
    const svg = document.querySelector('#ld-world').ownerSVGElement, F = Figure.current, cam = F.api.camera(F.api.render ? 0 : 0);
    const U = 2.2, x = 0.3 + 1.75 * U + 0.5 * U, y = 30.8 + 2 * U + 0.5 * U, p = F.api.project(x, y, 1.6);
    const q = svg.createSVGPoint(); q.x = cam.ex + p[0] * cam.z; q.y = cam.ey + p[1] * cam.z;
    const r = q.matrixTransform(svg.getScreenCTM()); return [r.x, r.y];
  });
  await page.mouse.click(pt[0], pt[1]);
  await tagIs(page, 'screen', 'on screen: a');
  out.pin = await page.evaluate(() => Figure.current.S.pin);
  // the Type field: a 200-character cap per event, 16px text, an input method's text kept until it is committed,
  // and a focused summary or slider keeps its own Space
  const presses = () => page.evaluate(() => { const e = [...document.querySelectorAll('.fg-ro .ro')].find((r) => r.querySelector('.k').textContent === 'Keys pressed'); return e ? +e.querySelector('.v').textContent : -1; });
  const base = await presses();
  out.field = await page.evaluate(() => { const i = document.querySelector('.fg-type input'); return [i.getAttribute('maxlength'), getComputedStyle(i).fontSize]; });
  await page.evaluate(() => { const i = document.querySelector('.fg-type input'); i.value = 'q'.repeat(500); i.dispatchEvent(new Event('input', { bubbles: true })); });
  out.burst = (await presses()) - base;
  await page.evaluate(() => { const i = document.querySelector('.fg-type input'); i.value = 'ni'; i.dispatchEvent(new InputEvent('input', { bubbles: true, isComposing: true })); });
  out.composing = await page.evaluate(() => document.querySelector('.fg-type input').value);
  out.composingKeys = (await presses()) - base - out.burst;
  await page.evaluate(() => document.querySelector('.fg-type input').dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: 'ni' })));
  out.committed = (await presses()) - base - out.burst;
  out.ownKeys = await page.evaluate(() => {
    const res = [];
    for (const html of ['<details><summary>Narration</summary>x</details>', '<div role="slider" tabindex="0"></div>', '<button type="button">b</button>', '<a href="#x">a</a>']) {
      const w = document.createElement('div'); w.innerHTML = html; document.querySelector('.fg').appendChild(w);
      const t = w.firstChild.firstChild && w.firstChild.firstChild.nodeType === 1 ? w.firstChild.firstChild : w.firstChild;
      res.push(['h', ' ', 'Enter', 'Backspace'].map((k) => { const ev = new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }); t.dispatchEvent(ev); return ev.defaultPrevented; }));
      w.remove();
    }
    return res;
  });
  // whole characters: one emoji is one key press, never two halves
  const before = await presses();
  await page.evaluate(() => { const i = document.querySelector('.fg-type input'); i.value = '\u{1F600}'; i.dispatchEvent(new Event('input', { bubbles: true })); });
  out.emoji = (await presses()) - before;
  // Backspace on an empty field where the key is reported as "Unidentified" (Android): only beforeinput tells
  const b2 = await presses();
  out.androidBackspace = await page.evaluate(() => { const i = document.querySelector('.fg-type input'); i.value = '';
    const ev = new InputEvent('beforeinput', { inputType: 'deleteContentBackward', bubbles: true, cancelable: true }); i.dispatchEvent(ev); return ev.defaultPrevented; });
  out.backspaceKeys = (await presses()) - b2;
  out.walk = await page.evaluate(() => Figure.current.walk());
  await ctx.close();
} finally { await browser.close(); }
console.log(JSON.stringify(out));
process.exit(0);
"""


@unittest.skipIf(FAST or not NODE, "--fast: no browser")
class TestComputerFigure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proj = TMP / "computer"
        showtime("new", "diagram", cls.proj, "--example", "computer", "--theme", "white")
        cls.out = TMP / "computer-figure.html"
        cp = showtime("export", "html", cls.proj, "--interactive", "-o", cls.out, "--json")
        cls.report = json.loads(cp.stdout)
        cls.r = run_driver(FILE_DRIVER, cls.out)

    def test_one_offline_file(self):
        self.assertTrue(self.report["interactive"])
        self.assertLess(self.report["bytes"], 1000 * 1000)
        self.assertEqual(self.r["requests"], [], "no network request")
        self.assertEqual(self.r["errors"], [], "no console error")
        self.assertTrue(self.r["typeField"], "a Type field for phones")

    def test_typing_reaches_the_screen(self):
        self.assertEqual(self.r["screen"].replace("\u00a0", " "), "on screen: hi")
        self.assertEqual(self.r["buffer"], '"hi"', "the editor's text in RAM")
        self.assertEqual(self.r["code"], "i \u2192 0x0C", "the USB HID usage id of 'i'")
        self.assertIn("Keys pressed 2", self.r["ro"])

    def test_backspace_enter_and_a_click(self):
        self.assertEqual(self.r["buffer2"], '"h\\n"', "Backspace took the i, Enter started a line")
        self.assertEqual(self.r["pin"], "", "a key click types; it does not pin the keyboard")

    def test_type_field_edges(self):
        self.assertEqual(self.r["field"], ["200", "16px"], "capped, and no iOS focus zoom")
        self.assertEqual(self.r["burst"], 200, "a 500-character burst types 200")
        self.assertEqual(self.r["composing"], "ni", "an input method's text is left alone while composing")
        self.assertEqual(self.r["composingKeys"], 0)
        self.assertEqual(self.r["committed"], 2, "and typed when it is committed")
        self.assertEqual(self.r["ownKeys"], [[False] * 4] * 4,
                         "a focused summary, slider, button and link keep all of their keys (letters, Space, Enter, Backspace)")
        self.assertEqual(self.r["emoji"], 1, "an emoji is one key press, not two halves of a surrogate pair")
        self.assertTrue(self.r["androidBackspace"], "Backspace reported only through beforeinput is taken")
        self.assertEqual(self.r["backspaceKeys"], 1)

    def test_every_state_walks_clean(self):
        w = self.r["walk"]
        self.assertTrue(w["typing"])
        self.assertGreaterEqual(w["presses"], 4)
        self.assertGreaterEqual(w["states"], 30)
        self.assertEqual(w["problems"], [])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    try:
        unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

#!/usr/bin/env python3
"""The diagram template's live-figure examples you touch (templates/diagram/examples/, runtime/figure.js).

  * typewriter: `showtime new diagram <dir> --example typewriter` makes the scene; `showtime export html --interactive`
    packs one offline figure; in a headless browser, typing "hi" and Enter on the page types it on the machine: "hi"
    lands on a fresh line of its own (after the first step's demo keystroke), stays on the paper above the new line
    after Return, the readouts count three lines, and the page logs no console error and makes no network request

Stdlib only. usage: python tests/test_figure_examples.py [--fast] [-v]
  --fast   skip the browser check
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
EXAMPLES = SKILL / "templates" / "diagram" / "examples"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
NODE = shutil.which("node", path=ENV.get("PATH"))
TMP = Path(tempfile.mkdtemp(prefix="st-figure-examples-"))


def showtime(*args, check=True, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


_FIG = {}


def figure(name):
    """A fresh `showtime new diagram --example <name>` project, exported once as its live figure."""
    if name not in _FIG:
        proj = TMP / ("proj-" + name)
        showtime("new", "diagram", proj, "--example", name, "--theme", "white")
        out = TMP / (name + "-figure.html")
        showtime("export", "html", proj, "--interactive", "-o", out, "--json")
        _FIG[name] = (proj, out)
    return _FIG[name]


TYPE = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, FILE] = process.argv.slice(2);
const { openBrowser } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'stagehost.mjs')).href);
const { browser } = await openBrowser({ headless: true });
const out = { errors: [], net: [] };
try {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx.addInitScript(() => { window.SHOWTIME_TEST_TOUR_AFTER = 1e9; });   // no idle tour typing over the test
  const pg = await ctx.newPage();
  pg.on('console', (m) => { if (m.type() === 'error') out.errors.push(m.text()); });
  pg.on('pageerror', (e) => out.errors.push(String(e.message || e)));
  pg.on('request', (r) => { if (!/^(file|blob|data):/.test(r.url())) out.net.push(r.url()); });
  await pg.goto(pathToFileURL(FILE).href);
  await pg.waitForFunction(() => window.Figure && window.Figure.current && document.querySelector('[data-paper-line]'), null, { timeout: 20000, polling: 100 });
  await pg.waitForTimeout(800);   // the first step's own keystroke settles
  await pg.mouse.click(4, 4);
  await pg.keyboard.type('hi', { delay: 120 });
  await pg.waitForTimeout(500);
  out.before = await pg.evaluate(() => [...document.querySelectorAll('[data-paper-line]')].map((g) => [g.getAttribute('data-paper-line'), g.getAttribute('data-text')]));
  await pg.keyboard.press('Enter');
  await pg.waitForTimeout(1200);
  out.after = await pg.evaluate(() => [...document.querySelectorAll('[data-paper-line]')].map((g) => [g.getAttribute('data-paper-line'), g.getAttribute('data-text')]));
  out.readouts = await pg.evaluate(() => [...document.querySelectorAll('.fg-ro .ro')].map((d) => [d.querySelector('.k').textContent, d.querySelector('.v').textContent]));
  out.state = await pg.evaluate(() => ({ typed: Figure.current.state.typed, col: Figure.current.state.col, line: Figure.current.state.line }));
} catch (e) { out.error = String(e && e.stack || e); }
await browser.close();
console.log(JSON.stringify(out));
"""


class TestTypewriterStatic(unittest.TestCase):
    def test_example_is_listed(self):
        self.assertTrue((EXAMPLES / "typewriter.js").is_file())
        cli = (SKILL / "lib" / "st" / "cli_core.py").read_text(encoding="utf-8")
        self.assertIn("typewriter", cli[cli.index("--example"):], "the CLI help names the example")

    def test_scene_contract(self):
        src = (EXAMPLES / "typewriter.js").read_text(encoding="utf-8")
        for k in ("type: {", "film: 'tour'", "press:", "readouts:", "not a specific model"):
            self.assertIn(k, src)


@unittest.skipIf(FAST or not NODE, "--fast: no browser")
class TestTypewriterFigure(unittest.TestCase):
    def test_typing_lands_on_the_paper(self):
        _, out = figure("typewriter")
        html = out.read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy", html, "one offline file")
        drv = TMP / "type.mjs"
        drv.write_text(TYPE, encoding="utf-8")
        cp = subprocess.run([NODE, str(drv), str(SKILL), str(out)], env=ENV, cwd=str(TMP), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertNotIn("error", r, r.get("error"))
        self.assertEqual(r["errors"], [], "no console error")
        self.assertEqual(r["net"], [], "no network request")
        before = dict(r["before"])
        self.assertEqual(before.get("0"), "hi", "the typed letters are on the typing line (a fresh one after the demo's): %s" % r["before"])
        after = dict(r["after"])
        self.assertEqual(after.get("0"), "", "Return starts a new, empty line: %s" % r["after"])
        self.assertEqual(after.get("1"), "hi", "the paper keeps \"hi\" on the line above: %s" % r["after"])
        self.assertEqual(r["state"]["col"], 0, "the carriage is home")
        self.assertEqual(r["state"]["line"], 3, "the demo's line, the line typed on, the new one")
        ro = dict(r["readouts"])
        self.assertEqual(ro.get("Line"), "3", r["readouts"])
        self.assertTrue(ro.get("Carriage", "").startswith("0 of "), r["readouts"])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

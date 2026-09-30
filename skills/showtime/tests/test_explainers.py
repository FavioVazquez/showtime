#!/usr/bin/env python3
"""Explainers from repos and papers: the two workflows and the code-block's file line numbers.

- references/workflows/repo-explainer.md and paper-explainer.md exist, open with a "Read this when" line,
  are routed from SKILL.md and listed in references/index.md, and keep their promises in the text
  (claims traced to file:line or page, a saved trace, the narration guide, the lengths).
- code-block `firstLine` (browser): an excerpt keeps its file's numbering, and highlight takes those
  file line numbers (a repo explainer shows lines 258-262 of a file as 258-262, never as 1-5).

usage: python tests/test_explainers.py [--fast] [-v]
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
sys.path.insert(0, str(SKILL / "lib"))

from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
WF = SKILL / "references" / "workflows"


def node_exe():
    return ENV.get("SHOWTIME_NODE") or plat.which("node") or shutil.which("node") or "node"


class Workflows(unittest.TestCase):
    def read(self, name):
        return (WF / name).read_text(encoding="utf-8")

    def test_routed_and_indexed(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        index = (SKILL / "references" / "index.md").read_text(encoding="utf-8")
        for name in ("repo-explainer.md", "paper-explainer.md"):
            self.assertTrue((WF / name).is_file(), name)
            lines = [l for l in self.read(name).splitlines() if l.strip()]
            self.assertTrue(lines[0].startswith("# Workflow:"), name)
            self.assertTrue(lines[1].startswith("Read this when"), name)
            # the router names `showtime guide` topics (the file name without .md)
            self.assertIn("`%s`" % name[:-3], skill, "SKILL.md does not route to %s" % name)
            self.assertIn("references/workflows/" + name, index, "index.md does not list %s" % name)

    def test_repo_explainer_promises(self):
        t = self.read("repo-explainer.md").lower()
        for must in ("what it does", "code map", "life of one request", "core abstractions", "a real trace",
                     "work/evidence", "claims.md", "file:line", "data-first-line", "data-st=\"fit\"", "9:16",
                     "60-120 s", "Claudisms"):
            self.assertTrue(must.lower() in t, "repo-explainer.md lost %r" % must)

    def test_paper_explainer_promises(self):
        t = self.read("paper-explainer.md").lower()
        for must in ("showtime doc extract", "figures.md", "page", "license", "credits.txt", "showtime manim",
                     "60-180 s", "arXiv"):
            self.assertTrue(must.lower() in t, "paper-explainer.md lost %r" % must)

    def test_narration_guide_is_shared_not_copied(self):
        # the lecturer's guide lives once (repo-explainer) and the paper workflow points to it
        self.assertIn("## Narration", self.read("repo-explainer.md"))
        self.assertIn("repo-explainer.md", self.read("paper-explainer.md"))


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>first line</title>
<script src="/_st/stage.js"></script><script>ST.config({"width": 1920, "height": 1080, "fps": 30, "duration": 3});</script>
<link rel="stylesheet" href="/_st/themes/neutral.css">
<script type="module" src="/_st/components/index.js"></script>
<style>.cb{position:absolute;inset:10cqh 10cqw}</style></head>
<body><div class="stage"><section class="scene" data-start="0" data-dur="3">
<div class="cb" id="a" data-st="code-block" data-reveal="none" data-first-line="258"
     data-highlight='[{"lines":"260","at":0.2}]'>def run(video):
    probe = raw_probe(video)
    findings = Findings()
    check(findings, probe)
    return findings</div>
</section><section class="scene" data-start="0" data-dur="3" style="opacity:0">
<div class="cb" id="b" data-st="code-block" data-reveal="none">x = 1
y = 2</div></section></div></body></html>"""

PROBE = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const skill = process.argv[2], dir = process.argv[3];
const imp = (p) => import(pathToFileURL(path.join(skill, 'scripts', p)).href);
const { startServer } = await imp('server.mjs');
const { openBrowser, openStage } = await imp('lib/stagehost.mjs');
const server = await startServer({ root: dir, port: 0 });
const b = await openBrowser({ gpu: 'auto' });
let R = {};
try {
  const s = await openStage(b.browser, { url: server.url, page: 'index.html', config: {} });
  await s.seek(2.5);
  R = await s.page.evaluate(() => {
    const rows = (id) => [...document.querySelectorAll('#' + id + ' .st-code-line')].map((r) => {
      const m = /opacity\(([\d.]+)\)/.exec(r.style.filter || '');   // highlight dims the other rows with filter: opacity()
      return { n: r.dataset.n, ln: (r.querySelector('.st-code-ln') || {}).textContent, op: m ? parseFloat(m[1]) : 1 };
    });
    return { a: rows('a'), b: rows('b') };
  });
  await s.close();
} finally { await b.browser.close(); await server.close(); }
console.log(JSON.stringify(R));
"""


@unittest.skipIf(FAST, "needs a browser")
class CodeBlockFirstLine(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-firstline-"))
        proj = cls.tmp / "proj"
        proj.mkdir()
        (proj / "showtime.json").write_text(json.dumps({"width": 1920, "height": 1080, "fps": 30, "duration": 3}),
                                            encoding="utf-8")
        (proj / "index.html").write_text(PAGE, encoding="utf-8")
        probe = cls.tmp / "probe.mjs"
        probe.write_text(PROBE, encoding="utf-8")
        cp = subprocess.run([node_exe(), str(probe), str(SKILL), str(proj)], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        if cp.returncode != 0:
            raise AssertionError("probe failed:\n%s\n%s" % (cp.stdout[-3000:], cp.stderr[-3000:]))
        cls.R = json.loads(cp.stdout.strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_numbers_follow_the_file(self):
        a = self.R["a"]
        self.assertEqual([r["ln"] for r in a], ["258", "259", "260", "261", "262"])
        self.assertEqual([r["n"] for r in a], ["258", "259", "260", "261", "262"])
        self.assertEqual([r["ln"] for r in self.R["b"]], ["1", "2"])          # default unchanged

    def test_highlight_takes_file_numbers(self):
        a = {r["n"]: r["op"] for r in self.R["a"]}
        self.assertGreater(a["260"], a["258"] + 0.2, a)                        # 260 lit, the rest dimmed
        self.assertAlmostEqual(a["258"], a["262"], places=2)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

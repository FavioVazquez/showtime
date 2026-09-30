#!/usr/bin/env python3
"""brand first for launches: `showtime brand capture | apply | skip`, `new launch` applying the kit, and the
brand findings of `showtime check`.

  - the README/CHANGELOG copy is read verbatim with file:line (install line, commands, features, release)
  - `brand capture <repo> --no-site` writes brand.json + brand.md, the wordmark from the site folder's <h1>,
    the real UI of a CLI, and records the kit in the job (job.json + SHOWTIME.md); refuses to overwrite
  - a site capture merges in: the rendered site's ground, ink and accent win; the wordmark's runs get roles;
    the code-block look is kept
  - `new launch` inside the job applies the kit (tokens, window in the code colours, end card filled from
    the copy); `--no-brand` leaves the template alone; re-applying replaces the block
  - colours are deepened only for legibility: accent >= 4.8:1 on the ground, the window accent also on its mark
  - qa: a 1:1 or 4:5 master is native on x/linkedin (no aspect warning)
  - qa: contact-sheet frames are re-extracted after a re-render to the same path
  - `brand skip` records why; the check verdict (scripts/lib/brandcheck.mjs) for each case
  - in the browser (skipped with --fast): a real `brand capture` of a served site folder, then `showtime check`
    reports `brand` for the branded project, `brand_not_applied` when the page drops the kit, `brand_missing`
    for a launch job with neither, `brand_none` after `brand skip`

usage: python tests/test_brand_first.py [--fast] [-v]
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
sys.path.insert(0, str(SKILL / "lib"))

from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
ENV.pop("SHOWTIME_OUT", None)
ENV.pop("SHOWTIME_BRAND", None)


def showtime(*args, check=True, cwd=None, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=timeout, stdin=subprocess.DEVNULL)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


README = """# tidyline

Sort, dedupe and tidy the lines of any text file, from the command line.

## Install

```bash
pip install tidyline        # or copy tidyline.py anywhere on your PATH
```

## Use

```bash
tidyline names.txt                  # sorted, to stdout
tidyline names.txt --natural        # "file2" before "file10"
cat log.txt | tidyline --reverse    # works on stdin too
```

## Features

- Natural sort order (`--natural`): numbers inside lines compare as numbers.
- In-place editing with an automatic `.bak` backup (`-i`).
"""

CHANGELOG = """# Changelog

## Unreleased

- Nothing yet.

## 3.1.0

- New: `--natural` sort order.
- Changed: `--unique` keeps the first occurrence.

## 3.0.0

- First release.
"""

SITE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>tidyline: tidy lines</title>
<style>
  :root { --ink: #1d2433; --paper: #fbf8f1; --accent: #2f6f5e; --muted: #5b6475; }
  body { margin: 0; font: 18px/1.5 system-ui, sans-serif; color: var(--ink); background: var(--paper); }
  header, section { max-width: 760px; margin: 0 auto; padding: 32px 20px; }
  h1 { font-size: 56px; margin: 0; } h1 span { color: var(--accent); }
  pre { background: var(--ink); color: #e8edf5; padding: 16px; border-radius: 10px; }
  .cta { display: inline-block; background: var(--accent); color: #fff; padding: 12px 22px; border-radius: 8px; }
</style></head><body>
<header><h1>tidy<span>line</span></h1><p>Sort, dedupe and tidy the lines of any text file.</p>
<a class="cta" href="#install">Get tidyline 3.1</a></header>
<section><pre>$ tidyline files.txt --natural
file1.txt
file2.txt
file10.txt</pre></section>
<section id="install"><h2>Install</h2><pre>pip install tidyline</pre></section>
</body></html>
"""


def make_repo(root: Path) -> Path:
    (root / "site").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "README.md").write_text(README, encoding="utf-8")
    (root / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (root / "tidyline.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "site" / "index.html").write_text(SITE, encoding="utf-8")
    return root


def new_job(base: Path, slug: str) -> Path:
    return Path(json.loads(showtime("job", "init", slug, "--json", cwd=base).stdout)["job"])


def node_verdict(case: dict) -> list:
    node = plat.which("node") or shutil.which("node", path=ENV.get("PATH")) or "node"
    mod = (SKILL / "scripts" / "lib" / "brandcheck.mjs").as_uri()
    code = "import { brandVerdict } from %s; console.log(JSON.stringify(brandVerdict(%s)));" % (
        json.dumps(mod), json.dumps(case))
    cp = subprocess.run([node, "--input-type=module", "-e", code], env=ENV, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", timeout=60)
    if cp.returncode != 0:
        raise AssertionError(cp.stderr[-2000:])
    return json.loads(cp.stdout.strip().splitlines()[-1])


class BrandFirstTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-brandfirst-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_01_copy_is_verbatim_with_sources(self):
        from st.brand import capture as cap
        repo = make_repo(self.tmp / "copyrepo")
        c = cap.readme_copy(repo, "tidyline")
        self.assertEqual(c["title"]["text"], "tidyline")
        self.assertEqual(c["tagline"]["text"], "Sort, dedupe and tidy the lines of any text file, from the command line.")
        self.assertEqual(c["tagline"]["source"], "README.md:3")
        self.assertEqual(c["install"]["command"], "pip install tidyline")
        self.assertEqual(c["install"]["comment"], "or copy tidyline.py anywhere on your PATH")
        self.assertEqual(c["install"]["source"], "README.md:8")
        cmds = [x["command"] for x in c["commands"]]
        self.assertEqual(cmds, ["tidyline names.txt", "tidyline names.txt --natural", "cat log.txt | tidyline --reverse"])
        self.assertEqual(c["commands"][1]["comment"], '"file2" before "file10"')
        self.assertEqual(len(c["features"]), 2)
        self.assertTrue(c["features"][1]["text"].startswith("In-place editing"))
        rel = cap.changelog_copy(repo)
        self.assertEqual(rel["version"], "3.1.0")          # "Unreleased" is skipped
        self.assertEqual([i["text"] for i in rel["items"]], ["New: `--natural` sort order.", "Changed: `--unique` keeps the first occurrence."])
        self.assertEqual(rel["items"][0]["source"], "CHANGELOG.md:9")
        self.assertEqual(cap.site_folders(repo), [repo / "site"])
        wm = cap.html_wordmark(repo / "site" / "index.html")
        self.assertEqual([(r["text"], r["role"]) for r in wm["runs"]], [("tidy", "ink"), ("line", "accent")])

    def test_02_capture_repo_records_in_job_and_new_launch_applies(self):
        base = self.tmp / "ws2"
        repo = make_repo(base)
        job = new_job(base, "tidyline-launch")
        cp = showtime("brand", "capture", repo, "--job", job, "--no-site", "--no-font-lookup", cwd=base)
        bj = job / "brand" / "brand.json"
        self.assertTrue(bj.is_file(), cp.stderr)
        kit = json.loads(bj.read_text(encoding="utf-8"))
        self.assertEqual(kit["palette"]["bg"], "#fbf8f1")     # --paper is the ground, never the ink
        self.assertEqual(kit["palette"]["ink"], "#1d2433")
        self.assertEqual(kit["palette"]["accent"], "#2f6f5e")
        self.assertEqual(kit["copy"]["install"]["command"], "pip install tidyline")
        self.assertEqual(kit["copy"]["release"]["version"], "3.1.0")
        self.assertEqual([r["text"] for r in kit["wordmark"]["runs"]], ["tidy", "line"])
        self.assertEqual(kit["real_ui"]["kind"], "cli")
        self.assertNotIn(str(self.tmp), bj.read_text(encoding="utf-8"))   # paths relative to brand.json
        md = (job / "brand" / "brand.md").read_text(encoding="utf-8")
        for s in ("## For the storyboard (brand first)", "`pip install tidyline` (README.md:8)", "Latest release **3.1.0**",
                  "\"tidy\" in ink", "\"line\" in accent", "its real UI is the terminal"):
            self.assertIn(s, md)
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(data["brand"]["kit"]), bj)
        self.assertEqual(Path(data["pointers"]["brand"]), bj)
        self.assertIn("brand kit", (job / "SHOWTIME.md").read_text(encoding="utf-8"))
        # never overwrites without --force
        cp = showtime("brand", "capture", repo, "--job", job, "--no-site", check=False, cwd=base)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("already exists", cp.stderr)
        # new launch finds <job>/brand/brand.json and applies it
        proj = job / "project"
        cp = showtime("new", "launch", proj, "--duration", 30, cwd=base)
        self.assertIn("brand tidyline applied", cp.stderr + cp.stdout)
        page = (proj / "index.html").read_text(encoding="utf-8")
        self.assertEqual(page.count('<style id="st-brand">'), 1)
        block = page[page.index('<style id="st-brand">'):]
        block = block[:block.index("</style>")]
        self.assertIn("--bg: #fbf8f1;", block)
        self.assertIn("--accent: #2f6f5e;", block)
        self.assertIn("--win-bg: #1d2433;", block)           # a light product shows commands in a dark block
        self.assertIn("color-scheme: light;", block)
        self.assertIn('tidy<span class="wm-accent">line</span><em>3.1.0</em>', page)
        self.assertIn('<p class="value" style="--i:1">Sort, dedupe and tidy the lines of any text file, from the command line.</p>', page)
        self.assertIn('<span class="ps">$ </span>pip install tidyline</div>', page)
        self.assertIn('<p class="label">tidyline <b>&middot;</b> 3.1.0</p>', page)
        cfg = json.loads((proj / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["background"], "#fbf8f1")
        self.assertEqual(cfg["brand"]["file"], "../brand/brand.json")
        self.assertEqual(cfg["subtitle"], "Sort, dedupe and tidy the lines of any text file, from the command line.")
        # re-applying replaces the block (one block, SLOT text the director wrote is left alone)
        page = page.replace("SLOT: What it does, <em>in 3-6 words.</em>", "Numbers sort as <em>numbers.</em>")
        (proj / "index.html").write_text(page, encoding="utf-8")
        showtime("brand", "apply", proj, cwd=base)
        page2 = (proj / "index.html").read_text(encoding="utf-8")
        self.assertEqual(page2.count('<style id="st-brand">'), 1)
        self.assertEqual(page2.count("<!-- brand kit:"), 1)
        self.assertIn("Numbers sort as <em>numbers.</em>", page2)
        # --no-brand: the template as it ships
        showtime("new", "launch", job / "plain", "--no-brand", cwd=base)
        self.assertNotIn("st-brand", (job / "plain" / "index.html").read_text(encoding="utf-8"))

    def test_03_colours_only_deepened_for_legibility(self):
        from st.brand import contrast
        from st.brand.apply import MARK, mix, tokens
        kit = {"colors": [{"role": "bg", "hex": "#ffffff"}, {"role": "ink", "hex": "#333333"},
                          {"role": "accent", "hex": "#7fd1b9"}], "code": {"bg": "#0f172a", "fg": "#e2e8f0"}}
        t, notes = tokens(kit)
        self.assertEqual(t["--bg"], "#ffffff")
        self.assertGreaterEqual(contrast(t["--accent"], "#ffffff"), 4.8)
        self.assertNotEqual(t["--accent"], "#7fd1b9")
        self.assertTrue(any("accent #7fd1b9" in n for n in notes))
        self.assertEqual(t["--win-bg"], "#0f172a")
        self.assertEqual(t["--win-fg"], "#e2e8f0")
        wa = t["--win-accent"]
        self.assertGreaterEqual(contrast(wa, "#0f172a"), 4.8)
        self.assertGreaterEqual(contrast(wa, mix("#0f172a", wa, MARK)), 4.8)   # the marked result line too
        # a dark brand keeps its colours when they already read
        t, notes = tokens({"palette": {"bg": "#0b0d12", "ink": "#f4f2ee", "accent": "#f2c14e"}})
        self.assertEqual((t["--bg"], t["--fg"], t["--accent"]), ("#0b0d12", "#f4f2ee", "#f2c14e"))
        self.assertEqual(t["color-scheme"], "dark")
        self.assertEqual(notes, [])
        # no bg/ink pair: nothing to apply
        self.assertEqual(tokens({"palette": {"accent": "#ff0000"}})[0], {})

    def test_04_site_merge_wins_for_what_people_see(self):
        from st.brand import capture as cap
        kit = {"colors": [{"role": "bg", "hex": "#000000", "source": "a.css:1"}, {"role": "ink", "hex": "#ffffff"},
                          {"role": "muted", "hex": "#888888"}], "fonts": {}, "logo": {}, "palette": {}}
        skit = {"colors": [{"role": "bg", "hex": "#fbf8f1", "source": "site"}, {"role": "ink", "hex": "#1d2433"},
                           {"role": "accent", "hex": "#2f6f5e"}], "fonts": {"display": {"family": "Inter"}},
                "logo": {"path": None}, "url": "http://127.0.0.1:5555/"}
        notes = cap.merge_site(kit, skit, {})
        self.assertEqual(kit["palette"]["bg"], "#fbf8f1")
        self.assertEqual(kit["palette"]["ink"], "#1d2433")
        self.assertEqual(kit["palette"]["accent"], "#2f6f5e")
        self.assertEqual(kit["palette"]["muted"], "#888888")
        self.assertEqual(kit["fonts"]["display"]["family"], "Inter")
        self.assertIsNone(kit.get("url"))                      # a local server is not the product's URL
        self.assertTrue(any(n.startswith("bg: the site shows #fbf8f1") for n in notes))
        # the site's "text" colour can be a code block's light text: it never becomes the ink of a light ground
        k2 = {"colors": [{"role": "ink", "hex": "#1d2433"}], "fonts": {}, "logo": {}, "palette": {}}
        n2 = cap.merge_site(k2, {"colors": [{"role": "bg", "hex": "#fbf8f1"}, {"role": "ink", "hex": "#e8edf5"}]}, {})
        self.assertEqual(k2["palette"]["ink"], "#1d2433")
        self.assertTrue(any("does not read on its ground" in n for n in n2))
        site = {"wordmark": {"text": "tidyline", "tag": "h1", "runs": [{"text": "tidy", "color": "#1d2433"},
                                                                      {"text": "line", "color": "#2f6f5e"}]},
                "code": {"bg": "#1d2433", "fg": "#e8edf5"}, "headings": [{"level": 1, "text": "tidyline"}],
                "ctas": [{"text": "Get tidyline 3.1", "primary": True}]}
        cap.site_extras(kit, site, Path("site.json"))
        self.assertEqual([r["role"] for r in kit["wordmark"]["runs"]], ["ink", "accent"])
        self.assertEqual(kit["code"]["fg"], "#e8edf5")
        self.assertEqual(kit["copy"]["ctas"][0]["text"], "Get tidyline 3.1")

    def test_05_skip_and_check_verdicts(self):
        base = self.tmp / "ws5"
        base.mkdir()
        job = new_job(base, "house-style")
        cp = showtime("brand", "skip", job, "--why", "the user asked for our house style", cwd=base)
        self.assertIn("no brand kit", cp.stderr + cp.stdout)
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(data["brand"]["none"], "the user asked for our house style")
        self.assertIn("no brand kit: the user asked for our house style", (job / "SHOWTIME.md").read_text(encoding="utf-8"))
        cp = showtime("new", "launch", job / "project", cwd=base)
        self.assertNotIn("no brand kit found", cp.stderr)
        # the check verdicts, case by case
        kit = {"name": "tidyline", "status": "draft", "palette": {"bg": "#fbf8f1", "ink": "#1d2433", "accent": "#2f6f5e"}}
        v = node_verdict({"kind": "launch", "kit": None, "job": "/x/showtime-out/j1"})
        self.assertEqual([(f["severity"], f["code"]) for f in v], [("warning", "brand_missing")])
        self.assertIn("showtime brand skip j1", v[0]["fix"])
        v = node_verdict({"kind": "launch", "kit": None, "job": None})
        self.assertEqual([(f["severity"], f["code"]) for f in v], [("info", "brand_missing")])
        v = node_verdict({"kind": "promo", "kit": None, "job": "/x/j1", "jobBrand": {"none": "house style"}})
        self.assertEqual([(f["severity"], f["code"]) for f in v], [("info", "brand_none")])
        v = node_verdict({"kind": "launch", "kit": kit, "kitFile": "/j/brand/brand.json", "page": {"bg": "#0c0d10", "accent": "#f2c14e"}})
        self.assertEqual([(f["severity"], f["code"]) for f in v], [("warning", "brand_not_applied")])
        self.assertIn("accent #f2c14e", v[0]["message"])
        v = node_verdict({"kind": "launch", "kit": kit, "page": {"bg": "#fbf8f1", "accent": "#2f6f5e"}})
        self.assertEqual([(f["severity"], f["code"]) for f in v], [("info", "brand")])
        v = node_verdict({"kind": "launch", "kit": kit, "page": {"bg": "#fbf8f1", "accent": "#1f5a4a", "applied": True}})
        self.assertEqual([(f["severity"], f["code"]) for f in v], [("info", "brand")])   # deepened by brand apply
        self.assertEqual(node_verdict({"kind": "explainer", "kit": None, "job": "/x/j1"}), [])

    def test_05b_qa_square_plays_natively_on_x(self):
        """A 1:1 cut for X (the benchmark asks for 16:9 and 1:1) is not an aspect warning: X keeps 4:5 to 16:9."""
        from st.qa import video as qv
        for (w, h), plat, warn in (((1080, 1080), "x", False), ((1080, 1350), "linkedin", False),
                                   ((1080, 1920), "x", True), ((1080, 1080), "youtube", True), ((1920, 1080), "x", False)):
            F = qv.Findings()
            qv._check_platform(F, qv.target_for(plat), {}, 30.0, w, h, 10_000_000)
            self.assertEqual(any(f["rule"] == "aspect" for f in F.items), warn, (w, h, plat, F.items))

    def test_05c_qa_frames_follow_a_rerender(self):
        """qa's contact-sheet frames are cached per time; a re-render to the same path must not show old frames."""
        import os
        import time
        from st import ff
        from st.qa import media
        v = self.tmp / "rerender" / "final.mp4"
        v.parent.mkdir(parents=True)
        out = v.parent / "sheet-frames"

        def make(color):
            ff.run_ffmpeg(["-f", "lavfi", "-i", "color=c=%s:s=64x36:d=1:r=10" % color, "-pix_fmt", "yuv420p",
                           "-y", os.fspath(v)], check=True)

        def red_of(p):
            raw = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-i", os.fspath(p), "-vf", "scale=1:1", "-f", "rawvideo",
                                  "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, check=True).stdout
            return raw[0]
        make("red")
        p1 = media.extract_frames(v, [0.5], out, duration=1.0, fps=10)[0]
        self.assertGreater(red_of(p1), 200)
        time.sleep(1.1)
        make("blue")
        p2 = media.extract_frames(v, [0.5], out, duration=1.0, fps=10)[0]
        self.assertEqual(p1, p2)
        self.assertLess(red_of(p2), 60)
        p3 = media.extract_frames(v, [0.5], out, duration=1.0, fps=10)[0]   # unchanged video: reused
        self.assertEqual(p3.stat().st_mtime, p2.stat().st_mtime)

    def test_06_browser_capture_and_check(self):
        if FAST:
            self.skipTest("--fast (needs a browser)")
        base = self.tmp / "ws6"
        repo = make_repo(base)
        job = new_job(base, "tidyline-site")
        res = json.loads(showtime("brand", "capture", repo, "--job", job, "--aspect", "16:9,1:1", "--no-font-lookup",
                                  "--json", cwd=base, timeout=600).stdout)
        kit = res["kit"]
        self.assertEqual((kit["palette"]["bg"], kit["palette"]["ink"], kit["palette"]["accent"]), ("#fbf8f1", "#1d2433", "#2f6f5e"))
        self.assertEqual([(r["text"], r["role"]) for r in kit["wordmark"]["runs"]], [("tidy", "ink"), ("line", "accent")])
        self.assertEqual((kit["code"]["bg"], kit["code"]["fg"]), ("#1d2433", "#e8edf5"))
        self.assertEqual(kit["real_ui"]["kind"], "cli")          # a CLI with a marketing site: the terminal is the product
        self.assertIn("site", kit["real_ui"])
        self.assertTrue(any(c["text"] == "Get tidyline 3.1" for c in kit["copy"]["ctas"]))
        shots = kit["capture"]["screens"]
        self.assertTrue(shots["16:9"] and shots["1:1"])
        self.assertTrue((job / "brand" / shots["16:9"][0]).is_file())
        self.assertTrue((job / "brand" / "capture" / "contact-sheet.jpg").is_file())
        proj = job / "project"
        showtime("new", "launch", proj, "--duration", 12, cwd=base)

        def brand_codes(p):
            rep = json.loads(showtime("check", p, "--json", "--samples", 2, "--no-timeline", "--no-determinism",
                                      check=False, cwd=base).stdout)
            return [(f["severity"], f["code"]) for f in rep["findings"] if f["code"].startswith("brand")]
        self.assertEqual(brand_codes(proj), [("info", "brand")])
        page = (proj / "index.html").read_text(encoding="utf-8")
        (proj / "index.html").write_text(re.sub(r"<!-- brand kit:.*?</style>\n", "", page, flags=re.S), encoding="utf-8")
        self.assertEqual(brand_codes(proj), [("warning", "brand_not_applied")])
        job2 = new_job(base, "nobrand")
        showtime("new", "launch", job2 / "project", "--duration", 12, cwd=base)
        self.assertEqual(brand_codes(job2 / "project"), [("warning", "brand_missing")])
        showtime("brand", "skip", job2, "--why", "no product to capture", cwd=base)
        self.assertEqual(brand_codes(job2 / "project"), [("info", "brand_none")])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

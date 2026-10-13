#!/usr/bin/env python3
"""The xray template and the mechanism library: templates/xray, skills/showtime/library/xray, `showtime new xray`.

  * static: the template's sample is consistent (xray.json events carry frame = floor(t * fps), the sample clip is
    the analyzed file, the sync marker sits at (W-10, H-10) and skipped events never light it); every library
    entry registers a mechanism with its design box, four anchors and a draw function, and has a README with the
    clip it was verified on; the guide is routed from SKILL.md
  * CLI: `new xray` copies a runnable project (no layout variants left behind); --mechanism copies a library entry
    and drops the sample clip's evidence for another object; an unknown mechanism, or --mechanism on another
    template, is an error; --layout sets showtime.json "xray".layout

Stdlib only. usage: python tests/test_xray_template.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
import unittest
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
        self.assertIn("| `xray` |", skill)
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


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

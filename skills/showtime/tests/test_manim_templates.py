#!/usr/bin/env python3
"""The Manim templates users start from pass `showtime manim check`, and a narrated scene opens on its hook.

  01  (stdlib) the example's narration line ids are never spoken words (at("tiles") can only mean the
      word), every beat() in its scenes.py names a line, and check's black-frame fix states qa's rule
      (99.5 % dark), not the old 98 % one
  02  (manim) a fresh `manim new --template example` passes `manim check` (dry run + the draft pass with
      qa's black and frozen-frame detectors) with 0 errors and 0 warnings, in 16:9 and 9:16
  03  (manim) every pattern template (equation, graph, plane, refine, blank) passes check with 0 errors
      and opens on a visible frame 0
  04  (manim) the first beat's lead-in: `beat("hook"); add(title); play(...)` has the title on frame 0
      (the kit holds the voice's lead-in on it), while fading the title in after beat() still opens on
      an empty frame and check still reports first_frame_black for it

usage: python tests/test_manim_templates.py [--fast] [-v]
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
EXAMPLE = SKILL / "templates" / "manim" / "example"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402
from st.manim_run import cues as cues_mod  # noqa: E402
from st.manim_run import draft as draft_mod  # noqa: E402
from st.manim_run.render import manim_installed  # noqa: E402

ENV = build_env(showtime_home())
TMP = Path(tempfile.mkdtemp(prefix="st-manim-tpl-"))
HAVE_MANIM = manim_installed()
NO_MANIM = "manim extra not installed: showtime setup --with manim"
PATTERNS = ("equation", "graph", "plane", "refine", "blank")


def tearDownModule():
    shutil.rmtree(str(TMP), ignore_errors=True)


def showtime(*args, check=True, timeout=900):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                    cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def new(name, template, aspect=None):
    d = TMP / name
    if d.exists():
        shutil.rmtree(str(d))
    showtime("manim", "new", d, "--template", template, *(["--aspect", aspect] if aspect else []))
    return d


def check(d, *extra):
    cp = showtime("manim", "check", d, "--json", *extra, check=False)
    try:
        return json.loads(cp.stdout)
    except ValueError:
        raise AssertionError("manim check printed no JSON (rc=%d):\n%s\n%s" % (cp.returncode, cp.stdout[-2000:],
                                                                             cp.stderr[-2000:]))


def listed(res, levels=("ERROR", "WARN")):
    return ["%s %s [%s] %s" % (i["level"], i["code"], i.get("scene"), i["message"]) for i in res["findings"]
            if i["level"] in levels]


class T01Static(unittest.TestCase):
    def test_line_ids_are_not_spoken(self):
        lines = cues_mod.parse_narration((EXAMPLE / "narration.md").read_text(encoding="utf-8"))
        ids = [ln["id"] for ln in lines]
        words = {cues_mod.norm_word(w) for ln in lines for w in ln["text"].split()}
        self.assertEqual([i for i in ids if cues_mod.norm_word(i) in words], [], ids)
        beats = re.findall(r'self\.beat\("([^"]+)"\)', (EXAMPLE / "scenes.py").read_text(encoding="utf-8"))
        self.assertEqual(sorted(set(beats)), sorted(ids))

    def test_black_fix_states_qas_rule(self):
        self.assertIn("99.5 %", draft_mod.BLACK_FIX)
        self.assertNotIn("98 %", draft_mod.BLACK_FIX)
        self.assertIn("add()", draft_mod.BLACK_FIX)
        self.assertNotIn("98 %", draft_mod.__doc__)


@unittest.skipUnless(HAVE_MANIM, NO_MANIM)
class T02Example(unittest.TestCase):
    def test_fresh_example_is_clean(self):
        for aspect in (None, "9:16"):
            with self.subTest(aspect=aspect or "16:9"):
                d = new("example-%s" % (aspect or "16:9").replace(":", "x"), "example", aspect)
                res = check(d)
                self.assertTrue(res["draft"], "the draft pass ran")
                self.assertEqual((res["errors"], res["warnings"]), (0, 0), listed(res))


@unittest.skipUnless(HAVE_MANIM, NO_MANIM)
class T03Patterns(unittest.TestCase):
    def test_patterns_have_no_errors(self):
        for t in PATTERNS:
            with self.subTest(template=t):
                res = check(new("pattern-" + t, t))
                self.assertEqual(res["errors"], 0, listed(res))
                self.assertFalse([i for i in res["findings"] if i["code"] in ("first_frame_black",
                                                                               "black_segment")], listed(res))


HOOK = '''from st_manim import *


class Open(ShowScene):
    def construct(self):
        self.beat("hook")
        t = title("Odd numbers")
        %s
        self.play(t.animate.scale(1.1), run_time=0.8)
        self.hold(1.5)
'''


@unittest.skipUnless(HAVE_MANIM, NO_MANIM)
class T04LeadIn(unittest.TestCase):
    def project(self, name, body):
        d = TMP / name
        if d.exists():
            shutil.rmtree(str(d))
        d.mkdir(parents=True)
        (d / "scenes.py").write_text(HOOK % body, encoding="utf-8")
        (d / "manim.json").write_text(json.dumps({"title": name}), encoding="utf-8")
        # estimated cues start the voice 0.35 s in: the lead-in the kit has to show something on
        (d / "narration.md").write_text("## hook\nOdd numbers add up to squares.\n", encoding="utf-8")
        return d

    def test_hook_on_frame_zero(self):
        res = check(self.project("added", "self.add(t)"))
        self.assertFalse([i for i in res["findings"] if i["code"] == "first_frame_black"], listed(res))
        log = json.loads((TMP / "added" / "build" / "check" / "Open.log.json").read_text(encoding="utf-8"))
        first_play = next(e for e in log["events"] if e["kind"] == "play")
        self.assertGreater(first_play["f"], 0, "the lead-in is still waited for (on the title)")
        # fading the title in after the lead-in: frame 0 is empty, and check says so
        res = check(self.project("faded", "self.play(FadeIn(t), run_time=0.5)"))
        self.assertIn("first_frame_black", [i["code"] for i in res["findings"]], listed(res))


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

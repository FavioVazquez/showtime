#!/usr/bin/env python3
"""`showtime manim check` agrees with `showtime qa` on black and frozen frames (the draft pass).

  01  a stubbed draft (ffmpeg-made: a near-black ground with one small light bar mid-video, an unchanging
      stretch of 4 s) gets qa's `black_segment` and `frozen` findings with a Manim fix, on qa's thresholds;
      a scene the dry run already flagged as a static_hold is not reported twice; a lively light
      picture gets nothing. Needs ffmpeg only (manim is stubbed out).
  02  references/manim.md: the integration pointer names the section that is called Integration
  03  a real project (manim extra): a dark, sparse scene and a small Indicate on one text are found by
      `showtime manim check` before the full render, `--no-draft` skips the pass, and the same file
      with "light": true has no black finding (skipped without manim)

usage: python tests/test_manim_draft.py [--fast] [-v]
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

from st import ff  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402
from st.manim_run import draft as draft_mod  # noqa: E402
from st.manim_run import render as render_mod  # noqa: E402
from st.manim_run.check import Findings  # noqa: E402
from st.manim_run.project import Project  # noqa: E402

ENV = build_env(showtime_home())
TMP = Path(tempfile.mkdtemp(prefix="st-manim-draft-"))
HAVE_MANIM = render_mod.manim_installed()


def tearDownModule():
    shutil.rmtree(str(TMP), ignore_errors=True)


def make_video(path: Path, lavfi: str, seconds: float, fps: int = 15) -> None:
    ff.run_ffmpeg(["-f", "lavfi", "-i", lavfi, "-t", str(seconds), "-r", str(fps), "-pix_fmt", "yuv420p", str(path)])


def showtime(*args, check=True, timeout=900):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                    cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def project(name, scenes_py, cfg=None):
    d = TMP / name
    if d.exists():
        shutil.rmtree(str(d))
    d.mkdir(parents=True)
    (d / "scenes.py").write_text(scenes_py, encoding="utf-8")
    (d / "manim.json").write_text(json.dumps(cfg or {"title": name}), encoding="utf-8")
    return d


LIVE = "testsrc2=s=320x180:r=15"
DARK = "color=c=0x0d0b0a:s=320x180:r=15,drawbox=x=t*20:y=80:w=12:h=6:color=white:t=fill"   # a small light bar moving


def make_draft(path: Path, parts) -> None:
    """parts: [(kind, seconds)], kind = live (busy light picture), still (one unchanging frame), dark (near-black
    ground with one small light bar), black. Joined into one H.264 file at 15 fps."""
    files = []
    for i, (kind, secs) in enumerate(parts):
        f = TMP / ("seg%d-%s.mp4" % (i, path.stem))
        if kind == "live":
            make_video(f, LIVE, secs)
        elif kind == "dark":
            make_video(f, DARK, secs)
        elif kind == "black":
            make_video(f, "color=c=black:s=320x180:r=15", secs)
        else:
            make_video(f, "color=c=0xe8e2d4:s=320x180:r=15,drawbox=x=100:y=60:w=120:h=60:color=0x3552c9:t=fill", secs)
        files.append(f)
    lst = TMP / ("list-%s.txt" % path.stem)
    lst.write_text("".join("file '%s'\n" % f for f in files), encoding="utf-8")
    ff.run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lst), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])


SPLIT = [("A", 6 * 15), ("B", 2 * 15)]     # scene A holds the 2-6 s still stretch


class Stubbed(unittest.TestCase):
    """draft_findings with render() replaced by a synthetic draft."""

    def setUp(self):
        self.real = render_mod.render
        self.d = project("stub", "from st_manim import *\n\nclass A(ShowScene):\n    def construct(self):\n"
                                 "        self.wait(1)\n\nclass B(ShowScene):\n    def construct(self):\n        self.wait(1)\n")

    def tearDown(self):
        render_mod.render = self.real

    def run_draft(self, parts, held=(), scenes=None):
        total = sum(s for _, s in parts)
        scenes = scenes or [("A", int(total / 2 * 15)), ("B", int(total / 2 * 15))]

        def fake(target, **kw):
            out = Path(kw["out"])
            make_draft(out, parts)
            return {"output": str(out), "duration": float(total), "fps": 15.0,
                    "scenes": [{"name": n, "frames": fr} for n, fr in scenes]}
        render_mod.render = fake
        f = Findings()
        for n in held:
            f.add("WARN", "static_hold", "held", scene=n)
        info = draft_mod.draft_findings(self.d, Project(self.d), f, scenes=None, aspect="16:9", cues_arg=None,
                                        brand=None)
        return f, info

    def test_dark_sparse_ground_is_black_like_qa(self):
        # a near-black ground with one tiny light bar (under 0.5 % of the frame) mid-video: black for qa
        f, info = self.run_draft([("live", 2), ("dark", 2), ("live", 2)])
        black = [i for i in f.items if i["code"] == "black_segment"]
        self.assertTrue(black, f.items)
        self.assertEqual(black[0]["level"], "ERROR")      # qa: black for 1 s or more is a FAIL
        self.assertIn('"light": true', black[0]["fix"])
        self.assertIn("manim.json", black[0]["fix"])
        self.assertEqual(black[0]["scene"], "A")
        self.assertTrue(info["black"])
        self.assertAlmostEqual(black[0]["at"], 2.0, delta=0.2)

    def test_dark_opening_is_a_black_first_frame(self):
        f, info = self.run_draft([("dark", 2), ("live", 4)])
        first = [i for i in f.items if i["code"] == "first_frame_black"]
        self.assertTrue(first, f.items)
        self.assertEqual(first[0]["level"], "ERROR")
        self.assertIn("add()", first[0]["fix"])
        self.assertIn('"light": true', first[0]["fix"])

    def test_unchanging_stretch_is_frozen_like_qa(self):
        f, info = self.run_draft([("live", 2), ("still", 4), ("live", 2)], scenes=SPLIT)
        fro = [i for i in f.items if i["code"] == "frozen"]
        self.assertTrue(fro, f.items)
        self.assertIn(fro[0]["level"], ("WARN", "ERROR"))
        self.assertIn("Indicate", fro[0]["fix"])
        self.assertIn("2.5", fro[0]["fix"])              # qa's threshold, read from thresholds.json
        self.assertIn("qa", fro[0]["message"])
        self.assertEqual(fro[0]["scene"], "A")
        self.assertAlmostEqual(fro[0]["at"], 2.0, delta=0.3)
        # the same stretch when the dry run already reported a hold in that scene: not twice
        f, _ = self.run_draft([("live", 2), ("still", 4), ("live", 2)], held=["A"], scenes=SPLIT)
        self.assertFalse([i for i in f.items if i["code"] == "frozen"], f.items)
        # a hold in another scene does not hide it
        f, _ = self.run_draft([("live", 2), ("still", 4), ("live", 2)], held=["B"], scenes=SPLIT)
        self.assertTrue([i for i in f.items if i["code"] == "frozen"], f.items)

    def test_short_stillness_and_lively_light_picture_are_clean(self):
        f, info = self.run_draft([("live", 2), ("still", 2), ("live", 2)])      # under qa's 2.5 s
        self.assertEqual([i["code"] for i in f.items if i["level"] != "INFO"], [], f.items)

    def test_thresholds_are_qas(self):
        from st.qa import video as qa_video
        f, _ = self.run_draft([("live", 2), ("still", 4), ("live", 2)], scenes=SPLIT)
        fro = [i for i in f.items if i["code"] == "frozen"][0]
        self.assertIn("%.1f s and FAILs from %.0f s" % (qa_video.thresholds()["still_hold_s"],
                                                       qa_video.thresholds()["frozen_fail_s"]), fro["fix"])

    def test_render_failure_is_a_warning(self):
        from st.common import ShowtimeError

        def boom(target, **kw):
            raise ShowtimeError("no scene")
        render_mod.render = boom
        f = Findings()
        self.assertIsNone(draft_mod.draft_findings(self.d, Project(self.d), f, scenes=None, aspect="16:9",
                                                   cues_arg=None, brand=None))
        self.assertEqual([i["code"] for i in f.items], ["draft_failed"])
        self.assertEqual(f.items[0]["level"], "WARN")


class Docs(unittest.TestCase):
    def test_integration_pointer(self):
        text = (SKILL / "references" / "manim.md").read_text(encoding="utf-8")
        m = re.search(r"^## (\d+)\. Integration", text, re.M)
        self.assertTrue(m)
        self.assertIn("overlay on footage (section %s)" % m.group(1), text)
        for n in re.findall(r"\(section (\d+)\)", text):
            self.assertTrue(re.search(r"^## %s\. " % n, text, re.M), "section %s does not exist" % n)

    def test_cli_help_names_the_draft_pass(self):
        out = showtime("manim", "check", "--help").stdout
        self.assertIn("--no-draft", out)
        self.assertIn("frozen", out)


DARK_SPARSE = '''from st_manim import *

class Sparse(ShowScene):
    def construct(self):
        t = title("Tiles make squares")
        place(t, "top")
        self.play(FadeIn(t), run_time=0.5)
        e = label("a + b")
        self.play(FadeIn(e), run_time=0.5)
        self.play(Indicate(e), run_time=1)
        self.play(Indicate(e), run_time=1)
        self.play(Indicate(e), run_time=1)
        self.play(Indicate(e), run_time=1)
'''


@unittest.skipUnless(HAVE_MANIM, "manim extra not installed: showtime setup --with manim")
class Real(unittest.TestCase):
    def test_dark_sparse_and_small_indicate(self):
        d = project("dark", DARK_SPARSE)
        res = json.loads(showtime("manim", "check", d, "--json", check=False).stdout)
        codes = {i["code"] for i in res["findings"]}
        self.assertTrue(codes & {"black_segment", "first_frame_black"}, res["findings"])
        self.assertTrue(res["draft"], res)
        self.assertTrue(codes & {"frozen", "static_hold"}, res["findings"])
        self.assertGreater(res["errors"], 0)
        skipped = json.loads(showtime("manim", "check", d, "--json", "--no-draft", check=False).stdout)
        self.assertFalse({i["code"] for i in skipped["findings"]} & {"black_segment", "first_frame_black"})
        self.assertIsNone(skipped["draft"])
        # same scene on the light theme: no black finding
        d2 = project("light", DARK_SPARSE, {"title": "light", "light": True})
        res2 = json.loads(showtime("manim", "check", d2, "--json", check=False).stdout)
        self.assertFalse({i["code"] for i in res2["findings"]} & {"black_segment", "first_frame_black"},
                         res2["findings"])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

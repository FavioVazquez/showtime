#!/usr/bin/env python3
"""Manim module tests: `showtime manim new|render|check|cues`, the st_manim kit, cues and alpha.

Stdlib-only parts always run (CLI help, templates, cue maths, frame sizes, cache-key scoping, the
hue set, LaTeX FIX lines). Render tests need the `manim` extra (skipped with the install line when
it is missing); equation tests also need LaTeX (skipped with this OS's FIX line when it is missing).
Renders are tiny (160-256 px, 10 fps) and go to temporary folders.

  01  help, `new` for every template, a broken manim.json explained (what / why / fix)
  02  cue maths: timeline -> cues, narration estimate, word lookup, frame units, sizes
  03  cache keys: editing one scene changes only its key; a cue line change only its scene
  04  theme: every hue is text-safe and apart from the emphasis colour; LaTeX FIX lines per OS
  05  Text-only scene renders (no LaTeX): frame count equals the kit's clock, sheet + poster written
  06  MathTex / eq() renders when LaTeX is present; morph keeps each concept's colour
  07  vertical: 9:16 frame is 8 x 14.22 units and an 7.9-unit bar spans the width
  08  cue sync: every at()/fit()/beat lands within one frame of its cue; scenes sit on the voice clock;
      the output carries the voice
  09  alpha: VP9 webm keeps alpha (corner transparent, shape opaque)
  10  check: a planted 5 s hold, an over-budget label, an unknown cue word and missing LaTeX are caught
  11  cache: a second render re-uses every scene
  12  ManimGL extra (when installed, full mode only): a manimlib scene renders at the asked size
  13  type lines: mixed_line() puts "Why" + pi r^2 + "?" and "Area =" + pi r^2 on one baseline (checked on
      the glyphs: the foot of "h"/"A" against the foot of the math "r") at a matched x-height;
      align_baseline() holds a label and a counter on one baseline while the number grows a comma;
      check flags a planted hand-made line (baseline_mismatch, xheight_mismatch, mixed_type) and not
      the helper's lines

usage: python tests/test_manim.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import glob
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402
from st.manim_run import cues as cues_mod  # noqa: E402
from st.manim_run import palette, tex  # noqa: E402
from st.manim_run.project import Project, frame_units, size_for  # noqa: E402
from st.manim_run.render import gl_python, manim_installed  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
TMP = Path(tempfile.mkdtemp(prefix="st-manim-"))
HAVE_MANIM = manim_installed()
TEX = tex.find()
NO_MANIM = "manim extra not installed: showtime setup --with manim"
NO_TEX = "LaTeX not found (equations need it): " + tex.fix_text()


def tearDownModule():
    shutil.rmtree(str(TMP), ignore_errors=True)


def showtime(*args, check=True, env=None, timeout=900):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=env or ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                    cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def project(name, scenes_py, manim_json=None, narration=None):
    d = TMP / name
    if d.exists():
        shutil.rmtree(str(d))
    d.mkdir(parents=True)
    (d / "scenes.py").write_text(scenes_py, encoding="utf-8")
    (d / "manim.json").write_text(json.dumps(manim_json or {"title": name}), encoding="utf-8")
    if narration:
        (d / "narration.md").write_text(narration, encoding="utf-8")
    return d


def probe(path):
    cp = subprocess.run([ff.ffprobe_path(), "-v", "error", "-count_frames", "-show_entries",
                         "stream=codec_type,codec_name,width,height,nb_read_frames:stream_tags=alpha_mode",
                         "-of", "json", str(path)], stdout=subprocess.PIPE, encoding="utf-8", timeout=120)
    return json.loads(cp.stdout)["streams"]


def rgba_frame(path, w, h, alpha_decoder=False, at=None):
    args = [ff.ffmpeg_path(), "-v", "error"]
    if alpha_decoder:
        args += ["-c:v", "libvpx-vp9"]
    if at is not None:
        args += ["-ss", str(at)]
    args += ["-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgba", "-"]
    cp = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    data = cp.stdout
    assert len(data) >= w * h * 4, cp.stderr.decode(errors="replace")[-400:]

    def px(x, y):
        i = (y * w + x) * 4
        return tuple(data[i:i + 4])
    return px


def sine_wav(path, seconds, freq=440.0, rate=48000):
    path.parent.mkdir(parents=True, exist_ok=True)
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate)))
                               for i in range(n)))


TEXT_SCENE = '''from st_manim import *

class Card(ShowScene):
    def construct(self):
        t = title("Tiles make squares")
        place(t, "top")
        self.play(FadeIn(t, shift=0.2 * UP), run_time=0.5)
        sq = Square(side_length=2).set_fill(T.hue(1), opacity=1).set_stroke(width=0)
        n = counter(0)
        n.next_to(sq, RIGHT)
        self.play(GrowFromCenter(sq), run_time=0.35)
        self.play(count_to(n, 9), run_time=0.6)
        self.mark("poster")
        self.hold(0.44)
'''


class T01Cli(unittest.TestCase):
    def test_help_and_new(self):
        out = showtime("manim", "--help").stdout
        for sub in ("new", "render", "check", "cues"):
            self.assertIn(sub, out)
        self.assertIn("Examples", showtime("manim", "render", "--help").stdout)
        for t in ("example", "equation", "graph", "plane", "refine", "blank"):
            d = TMP / ("new-" + t)
            r = json.loads(showtime("manim", "new", d, "--template", t, "--aspect", "9:16", "--json").stdout)
            self.assertTrue((d / "scenes.py").is_file() and (d / "manim.json").is_file(), r)
            cfg = json.loads((d / "manim.json").read_text(encoding="utf-8"))
            self.assertEqual(cfg["aspect"], "9:16")
            p = Project(d)
            self.assertTrue(p.scene_classes(), t)
            compile((d / "scenes.py").read_text(encoding="utf-8"), str(d / "scenes.py"), "exec")
        self.assertTrue((TMP / "new-example" / "narration.md").is_file())
        self.assertIn("## intro", (TMP / "new-refine" / "narration.md").read_text(encoding="utf-8"),
                      "pattern templates get a narration stub too")
        # <job>/manim is titled after the job, not "manim"
        jd = TMP / "circle-area-20260927-101500" / "manim"
        showtime("manim", "new", jd, "--template", "refine")
        self.assertEqual(json.loads((jd / "manim.json").read_text(encoding="utf-8"))["title"], "circle-area")
        # never overwrites
        cp = showtime("manim", "new", TMP / "new-example", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("not empty", cp.stderr)
        # a broken manim.json is explained
        (TMP / "broken").mkdir(exist_ok=True)
        (TMP / "broken" / "manim.json").write_text("{nope", encoding="utf-8")
        (TMP / "broken" / "scenes.py").write_text("x = 1\n", encoding="utf-8")
        cp = showtime("manim", "check", TMP / "broken", "--static", check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("not valid JSON", cp.stderr)
        self.assertIn("fix:", cp.stderr)
        cp = showtime("new", "manim", TMP / "x", check=False)
        self.assertIn("showtime manim new", cp.stderr)


class T02Cues(unittest.TestCase):
    def test_timeline_estimate_and_sizes(self):
        md = TMP / "n.md"
        md.write_text("<!-- c -->\n## hook\nOne, plus three. [pause 0.3]\n\n## rule\nSo [n](en) squared.\n",
                      encoding="utf-8")
        c = cues_mod.estimate(md, 30)
        self.assertTrue(c["estimated"])
        self.assertEqual([l["id"] for l in c["lines"]], ["hook", "rule"])
        self.assertEqual([w[0] for w in c["lines"][1]["words"]], ["So", "n", "squared."])
        self.assertAlmostEqual(c["lines"][1]["slot_start"], c["lines"][0]["slot_end"])
        self.assertEqual(cues_mod.norm_word("Sixteen."), "sixteen")
        tl = {"file": "vo.wav", "duration": 5.0, "lines": [
            {"id": "a", "start": 0.0, "end": 2.0, "speech_start": 0.1, "speech_end": 1.9,
             "slot": {"start": 0.0, "end": 2.4}, "file": "lines/01.wav",
             "words": [{"text": "Hi", "start": 0.1, "end": 0.4}]},
            {"id": "b", "start": 2.4, "end": 4.0, "slot": {"start": 2.4, "end": 4.4}, "words": []}]}
        p = TMP / "tl" / "timeline.json"
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(tl), encoding="utf-8")
        c = cues_mod.from_timeline(p, 30)
        self.assertEqual(c["lines"][1]["slot_end"], 5.0, "the last slot runs to the end of the voice")
        self.assertTrue(c["audio"].endswith("vo.wav"))
        self.assertEqual(c["lines"][0]["words"], [["Hi", 0.1, 0.4]])
        self.assertIn("hi 0.10", "\n".join(cues_mod.describe(c)))
        self.assertEqual(size_for("16:9", "final"), (1920, 1080))
        self.assertEqual(size_for("9:16", "final"), (1080, 1920))
        self.assertEqual(size_for("9:16", "draft"), (480, 854))
        self.assertEqual(size_for("1:1", "draft"), (480, 480))
        self.assertEqual(frame_units(1080, 1920), (8.0, 8.0 * 1920 / 1080))
        self.assertEqual(frame_units(1920, 1080)[1], 8.0)


@unittest.skipUnless(HAVE_MANIM, NO_MANIM)
class T02cRefine(unittest.TestCase):
    def test_start_and_tag(self):
        import st_manim._patterns as pat
        from manim import FadeIn, ReplacementTransform, Square, Text, Transform

        class Rec:
            def __init__(self):
                self.plays = []

            def play(self, *anims, run_time=1.0):
                self.plays.append([type(a).__name__ for a in anims])

            def hold(self, s):
                pass
        sc = Rec()
        start = Square()
        tags = []
        pat.refine(sc, lambda n: Square(side_length=n / 4), ns=(4, 8), start=start,
                   tag=lambda n: tags.append(n) or Text(str(n)))
        self.assertEqual(sc.plays[0], ["ReplacementTransform", "FadeIn"], "start= is transformed, not faded in")
        self.assertEqual(tags, [4, 8])
        sc2 = Rec()
        pat.refine(sc2, lambda n: Square(side_length=n / 4), ns=(4, 8), tag=None)
        self.assertEqual(sc2.plays, [["FadeIn"], ["ReplacementTransform"]], "tag=None: no label")


class T02bCueIds(unittest.TestCase):
    CUES = {"fps": 10, "duration": 6, "lines": [
        {"id": "half", "speech_start": 0.2, "speech_end": 1.8, "slot_start": 0, "slot_end": 2,
         "words": [["Cut", 0.2, 0.5], ["it", 0.5, 0.7]]},
        {"id": "sweep", "speech_start": 2.2, "speech_end": 5.0, "slot_start": 2, "slot_end": 6,
         "words": [["Take", 2.2, 2.5], ["half", 3.0, 3.4], ["now", 3.5, 3.8]]}]}

    def test_check_warns_when_a_line_id_is_spoken(self):
        from st.manim_run import check as check_mod
        d = project("ids", 'from st_manim import *\n\nclass A(ShowScene):\n    def construct(self):\n'
                           '        self.beat("sweep")\n        self.at("half")\n')
        f = check_mod.Findings()
        check_mod.static_checks(Project(d), ["A"], self.CUES, f)
        amb = [i for i in f.items if i["code"] == "cue_ambiguous"]
        self.assertEqual(len(amb), 1, f.items)
        self.assertIn("'half'", amb[0]["message"])
        self.assertIn("sweep", amb[0]["message"])

    @unittest.skipUnless(HAVE_MANIM, NO_MANIM)
    def test_word_wins_inside_the_current_line(self):
        from st_manim._beats import _Beats
        b = _Beats.__new__(_Beats)
        b.st_cues, b.st_fps, b.st_origin, b.st_line = self.CUES, 10.0, 0, None
        self.assertEqual(b.cue_time("half"), 0.2, "outside any line, a line id is the line's start")
        b.st_line = self.CUES["lines"][1]
        self.assertEqual(b.cue_time("half"), 3.0, "inside a line that says it, the word wins")
        self.assertEqual(b.cue_time("sweep"), 2.2)


class T03CacheKeys(unittest.TestCase):
    def test_scoped(self):
        src = ('from st_manim import *\nK = 1\n\nclass A(ShowScene):\n    def construct(self):\n'
               '        self.beat("a")\n        self.wait(1)\n\nclass B(ShowScene):\n    def construct(self):\n'
               '        self.beat("b")\n        self.wait(1)\n')
        d = project("keys", src)
        cues = {"fps": 10, "lines": [{"id": "a", "words": [], "slot_start": 0, "slot_end": 1},
                                     {"id": "b", "words": [], "slot_start": 1, "slot_end": 2}]}

        def keys(c=cues):
            p = Project(d)
            return {n: p.cache_key(n, {"w": 1}, c, "kit") for n in p.scene_classes()}
        k0 = keys()
        self.assertEqual(set(k0), {"A", "B"})
        (d / "scenes.py").write_text(src.replace('self.beat("b")\n        self.wait(1)',
                                                 'self.beat("b")\n        self.wait(2)'), encoding="utf-8")
        k1 = keys()
        self.assertEqual(k1["A"], k0["A"])
        self.assertNotEqual(k1["B"], k0["B"])
        c2 = json.loads(json.dumps(cues))
        c2["lines"][1]["slot_end"] = 3
        k2 = keys(c2)
        self.assertEqual(k2["A"], k1["A"])
        self.assertNotEqual(k2["B"], k1["B"])
        (d / "scenes.py").write_text(src.replace("K = 1", "K = 2"), encoding="utf-8")
        k3 = keys()
        self.assertNotEqual(k3["A"], k0["A"], "module-level code changes every scene")
        # a module-level helper class (a layout, a custom mobject) is code too: editing it changes every key,
        # while editing another scene class still does not
        src2 = src.replace("K = 1", "class Lay:\n    GAP = 1\n")
        (d / "scenes.py").write_text(src2, encoding="utf-8")
        k4 = keys()
        (d / "scenes.py").write_text(src2.replace("GAP = 1", "GAP = 2"), encoding="utf-8")
        k5 = keys()
        self.assertNotEqual(k5["A"], k4["A"], "a helper class change invalidates the cache")
        self.assertNotEqual(k5["B"], k4["B"])


class T04Theme(unittest.TestCase):
    def test_hues_and_fix_lines(self):
        brand = json.loads((SKILL.parent.parent / "assets" / "brand" / "brand.json").read_text(encoding="utf-8")) \
            if (SKILL.parent.parent / "assets" / "brand" / "brand.json").is_file() else None
        for kit, light in ((None, False), (None, True), (brand, False)):
            th = palette.build(kit, light=light)
            self.assertGreaterEqual(len(th["hues"]), 3)
            for h in th["hues"]:
                self.assertGreaterEqual(palette.contrast(h, th["bg"]), 4.5, (h, th["bg"]))
                self.assertGreaterEqual(palette.distance(h, th["emph"]), palette.MIN_EMPH_DISTANCE)
        if brand:
            th = palette.build(brand)
            self.assertNotIn(th["accent2"], th["hues"], "a brand colour that is not text-safe is never a hue")
            self.assertTrue(any("not text-safe" in n for n in th["notes"]))
        self.assertEqual(palette.resolve_color("hue2", th), th["hues"][1])
        mac = tex.fix_text("mac")
        self.assertIn("brew install --cask basictex", mac)
        self.assertIn("babel-english", mac)
        self.assertNotIn(" ms ", " " + tex.TLMGR_LIST + " ")
        self.assertIn("MiKTeX", tex.fix_text("windows"))
        self.assertIn("AutoInstall=1", tex.fix_text("windows"))
        self.assertIn("apt install", tex.fix_text("linux"))
        self.assertIn("brew install cairo pango pkg-config", tex.cairo_fix_lines("mac")[0])
        self.assertTrue(tex.uses_tex("e = eq(r'a^2')"))
        self.assertTrue(tex.uses_tex("x = MathTex('a')"))
        self.assertFalse(tex.uses_tex("t = title('Hi')\n# MathTex in a comment"))


@unittest.skipUnless(HAVE_MANIM, NO_MANIM)
class T05TextRender(unittest.TestCase):
    def test_text_scene(self):
        d = project("text", TEXT_SCENE)
        r = json.loads(showtime("manim", "render", d, "--size", "256x144", "--fps", "10", "--json").stdout)
        self.assertEqual(r["size"], [256, 144])
        frames = r["scenes"][0]["frames"]
        self.assertEqual(frames, 5 + 4 + 6 + 4, "every play and hold is snapped to whole frames")
        st = [s for s in probe(r["output"]) if s["codec_type"] == "video"][0]
        self.assertEqual((st["width"], st["height"]), (256, 144))
        self.assertEqual(int(st["nb_read_frames"]), frames)
        self.assertTrue(Path(r["sheet"]).is_file())
        f = json.loads(showtime("manim", "render", d, "--size", "256x144", "--fps", "10", "--quality", "final",
                                "--json").stdout)
        self.assertTrue(Path(f["poster"]).is_file())
        # -o <job>/final.mp4: poster.jpg beside it (as `showtime render` names it), also for final-2.mp4
        job = TMP / "text-job"
        for want in ("final.mp4", "final-2.mp4"):
            g = json.loads(showtime("manim", "render", d, "--size", "256x144", "--fps", "10", "--quality", "final",
                                    "-o", job / "final.mp4", "--json").stdout)
            self.assertEqual(Path(g["output"]).name, want)
            self.assertEqual(Path(g["poster"]), (job / "poster.jpg").resolve())
        g = json.loads(showtime("manim", "render", d, "--size", "256x144", "--fps", "10", "--quality", "final",
                                "-o", job / "teaser.mp4", "--json").stdout)
        self.assertEqual(Path(g["poster"]).name, "teaser.poster.jpg")


@unittest.skipUnless(HAVE_MANIM, NO_MANIM)
class T06MathTex(unittest.TestCase):
    def test_eq_and_morph(self):
        if not TEX["ok"]:
            self.skipTest(NO_TEX)
        src = ('from st_manim import *\n\nclass Eqn(ShowScene):\n    def construct(self):\n'
               '        a = eq(r"a^2 + b^2 = c^2")\n        assert a.keys == ["a^2", "+", "b^2", "=", "c^2"], a.keys\n'
               '        f = eq(r"1 + \\frac{a}{b} + (2n-1) = n^2", isolate=["(2n-1)"])\n'
               '        assert "(2n-1)" in f.keys and r"\\frac{a}{b}" in f.keys, f.keys\n'
               '        self.play(Write(a), run_time=0.5)\n'
               '        b = eq(r"a^2 = c^2 - b^2").move_to(a)\n'
               '        self.play(morph(a, b, key_map={"+": "-"}), run_time=0.5)\n'
               '        c = eq(r"A = \\pi r", isolate=[r"\\pi r"])\n'
               '        e = eq(r"A = \\pi r^2", isolate=[r"\\pi r^2"])\n'
               '        m = morph(c, e, key_map={r"\\pi r": r"\\pi r^2"})\n'
               '        assert len(m.animations) == 3, "key_map keys with spaces match declared keys"\n'
               '        self.hold(0.3)\n')
        d = project("eqn", src, {"title": "eqn", "colors": {"a": "hue1", "c^2": "emph"}})
        r = json.loads(showtime("manim", "render", d, "--size", "320x180", "--fps", "10", "--json").stdout)
        self.assertEqual(r["frames"], 13)
        lg = json.loads(Path(glob.glob(str(d / "build" / "cache" / "Eqn-*.log.json"))[0]).read_text(encoding="utf-8"))
        self.assertEqual(len(lg["colors"]["a^2"]), 1, lg["colors"])
        self.assertEqual(lg["colors"]["c^2"], [lg["declared"]["c^2"]])


@unittest.skipUnless(HAVE_MANIM, NO_MANIM)
class T07Vertical(unittest.TestCase):
    def test_frame_units(self):
        src = ('from st_manim import *\n\nclass Tall(ShowScene):\n    def construct(self):\n'
               '        bar = Rectangle(width=7.9, height=1).set_fill(WHITE, 1).set_stroke(width=0)\n'
               '        self.add(bar)\n        self.hold(0.2)\n')
        d = project("tall", src, {"title": "tall", "aspect": "9:16"})
        r = json.loads(showtime("manim", "render", d, "--size", "144x256", "--fps", "10", "--json").stdout)
        self.assertEqual(r["size"], [144, 256])
        self.assertAlmostEqual(r["frame_units"][0], 8.0)
        self.assertAlmostEqual(r["frame_units"][1], 8.0 * 256 / 144, places=4)
        lg = json.loads(Path(glob.glob(str(d / "build" / "cache" / "Tall-*.log.json"))[0]).read_text(encoding="utf-8"))
        self.assertAlmostEqual(lg["frame_units"][0], 8.0)
        px = rgba_frame(r["output"], 144, 256)
        self.assertGreater(px(4, 128)[0], 200, "a 7.9-unit bar reaches the left edge of an 8-unit wide frame")
        self.assertGreater(px(139, 128)[0], 200)
        self.assertLess(px(72, 20)[0], 60)


@unittest.skipUnless(HAVE_MANIM, NO_MANIM)
class T08CueSync(unittest.TestCase):
    def test_on_the_voice_clock(self):
        fps = 10
        src = ('from st_manim import *\n\nclass A(ShowScene):\n    def construct(self):\n'
               '        self.beat("one")\n        s = Square()\n        self.at("alpha")\n'
               '        self.play(FadeIn(s), run_time=0.5)\n        self.fit(s.animate.shift(RIGHT), until="beta")\n\n'
               'class B(ShowScene):\n    def construct(self):\n        self.beat("two")\n        c = Circle()\n'
               '        self.at("gamma", lead=0)\n        self.play(Create(c), run_time=0.3)\n'
               '        self.fit(c.animate.shift(UP), until="delta#2", lead=0.1)\n')
        d = project("sync", src, {"title": "sync", "scenes": ["A", "B"]})
        v = d / "voice"
        sine_wav(v / "vo.wav", 3.77)
        sine_wav(v / "lines" / "01-one.wav", 2.03)
        sine_wav(v / "lines" / "02-two.wav", 1.74)
        tl = {"file": "vo.wav", "duration": 3.77, "lines": [
            {"id": "one", "start": 0.0, "end": 1.6, "speech_start": 0.43, "speech_end": 1.5,
             "slot": {"start": 0.0, "end": 2.03}, "file": "lines/01-one.wav",
             "words": [{"text": "Alpha,", "start": 0.47, "end": 0.8}, {"text": "beta.", "start": 1.13, "end": 1.5}]},
            {"id": "two", "start": 2.03, "end": 3.5, "speech_start": 2.5, "speech_end": 3.4,
             "slot": {"start": 2.03, "end": 3.77}, "file": "lines/02-two.wav",
             "words": [{"text": "gamma", "start": 2.61, "end": 2.9}, {"text": "delta", "start": 2.95, "end": 3.0},
                       {"text": "delta", "start": 3.26, "end": 3.4}]}]}
        (v / "timeline.json").write_text(json.dumps(tl), encoding="utf-8")
        r = json.loads(showtime("manim", "render", d, "--size", "160x90", "--fps", str(fps), "--json").stdout)
        logs = {}
        for n in ("A", "B"):
            logs[n] = json.loads(Path(glob.glob(str(d / "build" / "cache" / ("%s-*.log.json" % n)))[0])
                                 .read_text(encoding="utf-8"))
        a_plays = [e for e in logs["A"]["events"] if e["kind"] == "play"]
        b_plays = [e for e in logs["B"]["events"] if e["kind"] == "play"]
        within = 1.0 / fps + 1e-9
        self.assertLessEqual(abs(a_plays[0]["f"] / fps - (0.47 - 0.3)), within)       # at("alpha")
        self.assertLessEqual(abs((a_plays[1]["f"] + a_plays[1]["n"]) / fps - 1.13), within)   # fit until beta
        origin = logs["B"]["origin"]
        self.assertEqual(origin, round(2.03 * fps))
        self.assertLessEqual(abs((origin + b_plays[0]["f"]) / fps - 2.61), within)    # at gamma, lead 0
        self.assertLessEqual(abs((origin + b_plays[1]["f"] + b_plays[1]["n"]) / fps - (3.26 - 0.1)), within)
        self.assertEqual(logs["A"]["frames"], round(2.03 * fps), "a scene ends on its last line's slot end")
        self.assertEqual(logs["A"]["frames"] + logs["B"]["frames"], round(3.77 * fps))
        self.assertFalse([e for n in logs for e in logs[n]["events"] if e["kind"] == "late"])
        kinds = {s["codec_type"] for s in probe(r["output"])}
        self.assertEqual(kinds, {"video", "audio"})
        self.assertIn("vo.wav", r["audio_note"])
        cp = showtime("manim", "cues", d)
        self.assertIn("delta#2 3.26", cp.stdout)


@unittest.skipUnless(HAVE_MANIM, NO_MANIM)
class T09Alpha(unittest.TestCase):
    def test_webm_alpha(self):
        src = ('from st_manim import *\n\nclass Over(ShowScene):\n    def construct(self):\n'
               '        self.add(Square(side_length=4).set_fill(T.emph, 1).set_stroke(width=0))\n        self.hold(0.3)\n')
        d = project("alpha", src)
        out = d / "over.webm"
        r = json.loads(showtime("manim", "render", d, "--size", "160x90", "--fps", "10", "--alpha", "-o", out,
                                "--json").stdout)
        self.assertEqual(Path(r["output"]).suffix, ".webm")
        st = [s for s in probe(r["output"]) if s["codec_type"] == "video"][0]
        self.assertEqual(st["codec_name"], "vp9")
        self.assertEqual(str((st.get("tags") or {}).get("alpha_mode")), "1")
        px = rgba_frame(r["output"], 160, 90, alpha_decoder=True)
        self.assertLess(px(2, 2)[3], 10, "the background is transparent")
        self.assertGreater(px(80, 45)[3], 245, "the shape is opaque")


@unittest.skipUnless(HAVE_MANIM, NO_MANIM)
class T10Check(unittest.TestCase):
    def test_planted_defects(self):
        src = ('from st_manim import *\n\nclass Slow(ShowScene):\n    def construct(self):\n'
               '        self.beat("hook")\n        t = label("far too many words for a label here")\n'
               '        self.play(FadeIn(t), run_time=0.5)\n        self.wait(5)\n'
               '        self.play(FadeOut(t), run_time=0.5)\n        self.hold(2)\n')
        d = project("slow", src, narration="## hook\nA short line.\n")
        # the dry run alone (--no-draft): the draft pass adds qa's black-frame FAIL for this label on a dark ground
        # (tests/test_manim_draft.py); exit codes below are about the dry run's warnings
        cp = showtime("manim", "check", d, "--json", "--no-draft", check=False)
        res = json.loads(cp.stdout)
        codes = {i["code"]: i for i in res["findings"]}
        self.assertIn("static_hold", codes, res["findings"])
        self.assertAlmostEqual(codes["static_hold"]["seconds"], 5.0, places=1)
        self.assertIn("word_budget", codes)
        self.assertEqual(cp.returncode, 0, "warnings alone pass")
        self.assertEqual(showtime("manim", "check", d, "--strict", "--no-draft", check=False).returncode, 1)
        # an unknown cue word is an error (static), with the fix pointing at the cue list
        (d / "scenes.py").write_text(src.replace('self.wait(5)', 'self.at("nowhere")'), encoding="utf-8")
        res = json.loads(showtime("manim", "check", d, "--json", check=False).stdout)
        self.assertIn("cue_not_found", [i["code"] for i in res["findings"]])
        # equations without LaTeX: an error with this OS's install line
        (d / "scenes.py").write_text(src.replace('label("far too many words for a label here")', 'eq("x^2")'),
                                     encoding="utf-8")
        env = dict(ENV, SHOWTIME_MANIM_FAKE_NO_TEX="1")
        cp = showtime("manim", "check", d, "--json", check=False, env=env)
        res = json.loads(cp.stdout)
        miss = [i for i in res["findings"] if i["code"] == "latex_missing"]
        self.assertTrue(miss, res["findings"])
        self.assertIn(tex.fix_lines()[0].split()[0], miss[0]["fix"])
        self.assertEqual(cp.returncode, 1)
        cp = showtime("manim", "render", d, "--size", "160x90", check=False, env=env)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("LaTeX", cp.stderr)
        self.assertIn("fix:", cp.stderr)


@unittest.skipUnless(HAVE_MANIM, NO_MANIM)
class T10bHolds(unittest.TestCase):
    """check holds agree with qa: a thin line sweeping is still a hold (qa's frozen-frame detector cannot see
    it), still frames across a scene cut are one hold, and --aspect checks the portrait layout."""

    def test_subtle_plays_and_joined_scenes(self):
        src = ('from st_manim import *\n\nclass A(ShowScene):\n    def construct(self):\n'
               '        self.play(FadeIn(Square(side_length=3).set_fill(T.hue(1), 1)), run_time=0.5)\n'
               '        ln = Line(ORIGIN, 2 * RIGHT, stroke_width=2)\n        self.add(ln)\n'
               '        self.play(Rotate(ln, angle=PI / 3, about_point=ORIGIN), run_time=1.5)\n'
               '        self.wait(1.5)\n'
               '        self.play(FadeIn(Circle(radius=2).set_fill(T.hue(2), 1).shift(3 * LEFT)), run_time=0.5)\n'
               '        self.wait(1.5)\n\n'
               'class B(ShowScene):\n    def construct(self):\n        self.wait(1.5)\n'
               '        self.play(FadeIn(Square(side_length=4).set_fill(T.hue(3), 1)), run_time=0.5)\n'
               '        self.hold(1)\n')
        d = project("holds", src)
        res = json.loads(showtime("manim", "check", d, "--json", check=False).stdout)
        holds = [i for i in res["findings"] if i["code"] == "static_hold"]
        self.assertEqual(len(holds), 2, holds)
        self.assertAlmostEqual(holds[0]["at"], 0.5, places=1)
        self.assertAlmostEqual(holds[0]["seconds"], 3.0, places=1)
        self.assertIn("too small for qa", holds[0]["message"])
        self.assertAlmostEqual(holds[1]["seconds"], 3.0, places=1, msg="1.5 s + 1.5 s across the cut")
        self.assertIn("A -> B", holds[1]["message"])
        self.assertTrue(all(h["level"] == "WARN" for h in holds))
        res = json.loads(showtime("manim", "check", d, "--aspect", "9:16", "--json", check=False).stdout)
        self.assertEqual(res["aspect"], "9:16")


@unittest.skipUnless(HAVE_MANIM, NO_MANIM)
class T11Cache(unittest.TestCase):
    def test_second_render_cached(self):
        d = project("cache", TEXT_SCENE)
        showtime("manim", "render", d, "--size", "160x90", "--fps", "10", "--json")
        r = json.loads(showtime("manim", "render", d, "--size", "160x90", "--fps", "10", "--json").stdout)
        self.assertTrue(all(s["cached"] for s in r["scenes"]), r["scenes"])
        self.assertTrue(Path(r["output"]).is_file())


TYPE_SCENES = r"""from st_manim import *
import json

OUT = %r


def feet(g):
    return float(g.get_bottom()[1])


class Good(ShowScene):
    def construct(self):
        self.beat("hook")
        q = mixed_line("Why", tex(r"\pi r^2"), "?", size=88)
        a = mixed_line("Area =", tex(r"\pi r^2"), tier="callout")
        lab, num = label("rings"), counter(8, font_size=44)
        g = VGroup(lab, num).arrange(RIGHT, buff=0.25)
        align_baseline(lab, num)
        VGroup(q, a, g).arrange(DOWN, buff=0.6)
        self.add(q, a, g)
        rq, ra = q[1][0][1], a[1][0][1]          # the glyph "r" of each pi r^2 (one declared part)
        m = {"why_h": feet(q[0][1]), "why_r": feet(rq), "why_cap": q[0][0].height,
             "why_q": baseline(q[2]), "why_base": q.baseline(),
             "area_A": feet(a[0][0]), "area_r": feet(ra), "area_cap": a[0][0].height,
             "xh_text_r": a[0][1].height, "xh_math_r": ra.height,
             "xh_why": x_height(q[0]), "xh_pi": x_height(q[1]),
             "rings_base0": baseline(lab), "num_base0": baseline(num)}
        self.play(count_to(num, 1200), run_time=0.5)
        m["num_base1"] = baseline(num)
        json.dump(m, open(OUT, "w"))
        self.hold(0.3)


class Bad(ShowScene):
    def construct(self):
        self.beat("bad")
        q = VGroup(title("Why", size=88), eq(r"\pi r^2", font_size=116), title("?", size=88)).arrange(
            RIGHT, buff=0.22, aligned_edge=DOWN)
        self.add(q)
        self.play(Indicate(q[1]), run_time=0.5)
        self.hold(0.3)
"""


@unittest.skipUnless(HAVE_MANIM, NO_MANIM)
class T13TypeLines(unittest.TestCase):
    def test_mixed_line_and_check(self):
        if not TEX["ok"]:
            self.skipTest(NO_TEX)
        out = TMP / "type-metrics.json"
        d = project("typelines", TYPE_SCENES % str(out), {"title": "typelines", "scenes": ["Good", "Bad"],
                                                          "colors": {"\\pi r^2": "hue1"}},
                    narration="## hook\nWhy is it pi r squared?\n\n## bad\nThe same line by hand.\n")
        cp = showtime("manim", "check", d, "--json", check=False)
        res = json.loads(cp.stdout)
        m = json.loads(out.read_text(encoding="utf-8"))
        # one baseline, measured on the glyphs (not the boxes): the foot of the text's "h" / "A" and the
        # foot of the math "r" within 4 % of the cap height (CM's r overshoots the baseline a little)
        self.assertLess(abs(m["why_h"] - m["why_r"]) / m["why_cap"], 0.04, m)
        self.assertLess(abs(m["area_A"] - m["area_r"]) / m["area_cap"], 0.04, m)
        self.assertLess(abs(m["why_q"] - m["why_base"]) / m["why_cap"], 0.01, m)
        # matched x-height: kit metrics equal, and the glyph "r" of both engines within 12 %
        self.assertLess(abs(m["xh_pi"] / m["xh_why"] - 1), 0.02, m)
        self.assertLess(abs(m["xh_math_r"] / m["xh_text_r"] - 1), 0.12, m)
        # a counter keeps the label's baseline, also after "1,200" adds a descending comma
        self.assertLess(abs(m["rings_base0"] - m["num_base0"]), 1e-3, m)
        self.assertLess(abs(m["num_base1"] - m["num_base0"]), 1e-3, m)
        by_scene = {}
        for i in res["findings"]:
            by_scene.setdefault(i.get("scene"), set()).add(i["code"])
        line_codes = {"baseline_mismatch", "xheight_mismatch", "mixed_type"}
        self.assertFalse(by_scene.get("Good", set()) & line_codes, res["findings"])
        self.assertTrue(line_codes <= by_scene.get("Bad", set()), res["findings"])
        bad = [i for i in res["findings"] if i["code"] == "baseline_mismatch" and i["scene"] == "Bad"]
        self.assertIn("mixed_line(", bad[0]["fix"])
        self.assertGreater(max(abs(i["baseline_off"]) for i in bad), 0.2, "the descender of 'y' drags the box")


@unittest.skipIf(FAST, "full mode only")
class T12ManimGL(unittest.TestCase):
    def test_gl_scene(self):
        if gl_python() is None:
            self.skipTest("ManimGL extra not installed: showtime setup --with manimgl")
        src = ("from manimlib import *\n\nclass Ring(Scene):\n    def construct(self):\n"
               "        self.play(ShowCreation(Circle(radius=3)), run_time=0.5)\n")
        d = project("gl", src, {"title": "gl", "aspect": "9:16"})
        r = json.loads(showtime("manim", "render", d, "--json").stdout)
        self.assertEqual(r["engine"], "manimgl")
        st = [s for s in probe(r["output"]) if s["codec_type"] == "video"][0]
        self.assertEqual((st["width"], st["height"]), (480, 854))


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

#!/usr/bin/env python3
"""The first frame after a hard cut: drawn on that frame in a render with the default settings.

A showreel drew a canvas or WebGL shot in ST.onSeek only while its scene was on screen, testing
`t >= start` with the times from ST.clips(). Its scene times were written a hair after the frame
(1.9667 for frame 118 at 60 fps): the stage showed the new scene on frame 118 (a time within 1 ms of a
frame is that frame), while `t >= 1.9667` was still false there, so the first frame after every cut
came out blank in the MP4. `snap` and `check` looked right: they reach a frame after other frames, and
the canvas still held an earlier drawing. "render": {"settle": "raf2"} changed nothing.

One 640x360 page at 30 fps, six scenes of ten frames, cut on the frame, written as rounded times a hair
after it (0.3334, 0.6667, 1.0001 ...); even scenes draw a 2D canvas, odd ones WebGL:

  * ST.clips() reports the windows frame-exact (start = the frame's time)
  * good.html (draws while ST.clips() says the scene is on screen), rendered with the default settings:
    every frame shows its scene's colour, the first frame after each cut included
  * own.html (draws from its own copy of the typed times): the render's first frame after each cut is
    blank, and `showtime check` reports late_first_frame for those cuts (good.html: none)
  * the built-in showreel template (`showtime new showreel`): check walks its cuts and finds none late

Skipped with --fast (needs a browser). usage: python tests/test_cut_frames.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import math
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

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
FPS, LEN, N, W, H = 30, 10, 6, 640, 360
BG = (0, 0, 0)


def color(i):
    return (40 + (i * 53) % 200, 60 + (i * 97) % 180, 80 + (i * 31) % 160)


# scene k starts on frame k*LEN, written rounded up to 4 decimals (a hair after the frame), the way
# a script or an agent writes 1.9667 for frame 118 at 60 fps
STARTS = [0.0] + [math.ceil(k * LEN / FPS * 1e4 + 0.5) / 1e4 for k in range(1, N)]

PAGE = """<!doctype html><html><head><meta charset="utf-8"><script src="/_st/stage.js"></script>
<style>body { background: #000; } .scene { position: absolute; inset: 0; }
canvas { position: absolute; inset: 0; width: 100%%; height: 100%%; display: block; }</style></head><body>
%(sections)s
<script>
var STARTS = %(starts)s, COLORS = %(colors)s, OWN = %(own)s;
var draws = [];
document.querySelectorAll('section canvas').forEach(function (c, i) {
  var col = COLORS[i];
  if (i %% 2 === 0) {
    var g = c.getContext('2d');
    draws.push(function (u) {
      g.fillStyle = 'rgb(' + col.join(',') + ')'; g.fillRect(0, 0, c.width, c.height);
      g.fillStyle = '#fff'; g.fillRect(40 + u * 300, 40, 60, 60);
    });
  } else {
    var gl = c.getContext('webgl', { preserveDrawingBuffer: true });
    draws.push(function (u) {
      gl.viewport(0, 0, c.width, c.height);
      gl.clearColor(col[0] / 255, col[1] / 255, col[2] / 255, 1); gl.clear(gl.COLOR_BUFFER_BIT);
      gl.enable(gl.SCISSOR_TEST); gl.scissor(Math.round(40 + u * 300), c.height - 100, 60, 60);
      gl.clearColor(1, 1, 1, 1); gl.clear(gl.COLOR_BUFFER_BIT); gl.disable(gl.SCISSOR_TEST);
    });
  }
});
ST.onSeek(function (t) {
  var cl = ST.clips();
  for (var i = 0; i < draws.length; i++) {
    // own.html: its own copy of the typed times; good.html: the stage's windows
    var s = OWN ? STARTS[i] : cl[i].start, e = OWN ? (STARTS[i + 1] || 1e9) : (cl[i].end == null ? 1e9 : cl[i].end);
    if (t >= s && t < e) draws[i](t - s);
  }
});
</script></body></html>
"""


def page_html(own):
    secs = []
    for i, s in enumerate(STARTS):
        dur = (STARTS[i + 1] - s) if i + 1 < N else (N * LEN / FPS - s)
        secs.append('<section class="scene" id="s%d" data-start="%s" data-dur="%s"><canvas width="%d" height="%d"></canvas></section>'
                    % (i, ("%.4f" % s).rstrip("0").rstrip(".") or "0", "%.4f" % dur, W, H))
    return PAGE % {"sections": "\n".join(secs), "starts": json.dumps(STARTS), "colors": json.dumps([list(color(i)) for i in range(N)]),
                   "own": "true" if own else "false"}


def showtime(*args, check=True, timeout=600):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def frame_colors(video):
    """The colour at (480, 270) of every frame (away from the moving white square): [(r, g, b)]."""
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-i", str(video), "-vf",
                         "crop=8:8:476:266,scale=1:1:flags=area,format=rgb24", "-f", "rawvideo", "-"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")
    b = cp.stdout
    return [tuple(b[i:i + 3]) for i in range(0, len(b) - 2, 3)]


def near(a, b, tol=14):
    return max(abs(x - y) for x, y in zip(a, b)) <= tol


@unittest.skipIf(FAST, "needs a browser")
class CutFrames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-cuts-"))
        cls.proj = cls.tmp / "cuts"
        cls.proj.mkdir()
        (cls.proj / "showtime.json").write_text(json.dumps({"title": "Cuts", "width": W, "height": H, "fps": FPS,
                                                             "duration": N * LEN / FPS, "background": "#000000"}), encoding="utf-8")
        (cls.proj / "index.html").write_text(page_html(False), encoding="utf-8")
        (cls.proj / "own.html").write_text(page_html(True), encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def render(self, page):
        out = self.tmp / ("%s.mp4" % page.split(".")[0])
        showtime("render", self.proj, "--page", page, "--no-audio", "--poster", "none", "-o", out, "-q")
        cols = frame_colors(out)
        self.assertEqual(len(cols), N * LEN)
        return cols

    def check(self, page):
        cp = showtime("check", self.proj, "--page", page, "--json", "--no-determinism", "--samples", "3", check=False)
        return json.loads(cp.stdout)

    def test_scene_times_are_a_hair_after_the_frame(self):
        for k in range(1, N):
            self.assertGreater(STARTS[k], k * LEN / FPS)
            self.assertLess(STARTS[k] - k * LEN / FPS, 1e-3)

    def test_default_render_draws_every_first_frame(self):
        cols = self.render("index.html")
        wrong = [(f, cols[f]) for f in range(N * LEN) if not near(cols[f], color(f // LEN))]
        self.assertEqual(wrong, [], "frames without their scene's colour (frame, rgb)")

    def test_check_names_a_page_that_draws_late(self):
        cols = self.render("own.html")
        # the mechanism: the stage shows each scene from its frame, the page draws it a frame later
        for k in range(1, N):
            self.assertTrue(near(cols[k * LEN], BG), "frame %d: %r" % (k * LEN, cols[k * LEN]))
            self.assertTrue(near(cols[k * LEN + 1], color(k)), "frame %d: %r" % (k * LEN + 1, cols[k * LEN + 1]))
        rep = self.check("own.html")
        late = [f for f in rep["findings"] if f["code"] == "late_first_frame"]
        self.assertEqual(len(late), 1, rep["findings"])
        self.assertEqual(late[0]["severity"], "error")
        self.assertEqual([round(t * FPS) for t in late[0]["times"]], [k * LEN for k in range(1, N)])
        for k in range(1, N):
            self.assertIn("#s%d" % k, late[0]["message"])
        good = self.check("index.html")
        self.assertEqual([f for f in good["findings"] if f["code"] == "late_first_frame"], [])
        self.assertTrue(all(not c["late"] for c in good["cuts"]), good["cuts"])

    def test_clips_are_frame_exact(self):
        # check's cut frames are ceil(start * fps) of ST.clips(): a raw 0.3334 would give frame 11, not 10
        rep = self.check("index.html")
        self.assertEqual([c["frame"] for c in rep["cuts"]], [k * LEN for k in range(1, N)])

    def test_showreel_template_cuts(self):
        reel = self.tmp / "reel"
        showtime("new", "showreel", reel)
        cp = showtime("check", reel, "--json", "--no-determinism", "--samples", "3", check=False, timeout=900)
        rep = json.loads(cp.stdout)
        self.assertEqual([f for f in rep["findings"] if f["code"] == "late_first_frame"], [])
        self.assertGreaterEqual(len(rep.get("cuts") or []), 5, rep.get("cuts"))
        self.assertFalse([c for c in rep["cuts"] if c["late"]], rep["cuts"])


if __name__ == "__main__":
    unittest.main(argv=[a for a in sys.argv if a != "--fast"])

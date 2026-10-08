#!/usr/bin/env python3
"""WebGL looks (runtime/effects/gl.js; components fluted-glass, tilt-shift, liquid-metal, mesh-gradient, god-rays,
marble, metaballs).

  * the modules parse, `showtime motion` lists the seven looks, the shaders keep GLSL ES 1.00 portable
    (no reversed smoothstep edges, no reserved words as names), and every pass kind a look registers has a cost
  * frame-exact: one page with the first three looks moving (keys, drift, flow) rendered with 1 and with 3 workers
    gives the same PNG frames (frames 0, 37 and 90 checked, and every other frame), and the looks move; the same for
    a page with the four newer looks (mesh-gradient, god-rays, marble, metaballs), and for that page without WebGL
    (the metaballs fallback moves, so its frames are compared too)
  * without WebGL (getContext('webgl') returns null, as in a browser that has none) each look draws its
    fallback: `showtime check` lists them as fallbacks (look_fallback), the frame is not empty and differs from
    the WebGL one; the metaballs fallback still moves, the others are still
  * `showtime check` warns when a look costs more per frame without a GPU than runtime/thresholds.json
    "look_budget_ms" (a tilt-shift at full size over a box larger than 1080p; a marble at twice the size) and stays
    quiet for the defaults (each of the newer looks at 1080p estimates under the budget)
  * WebGL contexts (Chrome keeps about 16 per page): 20 looks in one scene all draw (none white or empty) and
    check fails the page with look_contexts; 20 scenes with a look each draw every scene, give the same frames
    with 1 and 3 workers, pass check's shuffled-order probe, and count one look on screen at a time

Needs a browser. usage: python tests/test_looks.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

from _listen import skip_if_listen_refused

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
RUNTIME = SKILL / "runtime"
sys.path.insert(0, str(SKILL / "lib"))

from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())
LOOKS = ("fluted-glass", "tilt-shift", "liquid-metal")
NEW = ("mesh-gradient", "god-rays", "marble", "metaballs")
ALL = LOOKS + NEW
FILES = [RUNTIME / "effects" / "gl.js"] + [RUNTIME / "components" / (n + ".js") for n in ALL]


def showtime(*args, check=True, timeout=900):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    skip_if_listen_refused(cp)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def check(proj, *extra):
    cp = showtime("check", proj, "--json", "--no-determinism", "--no-timeline", "--no-history", "--samples", "2", *extra, check=False)
    try:
        return json.loads(cp.stdout)
    except ValueError:
        raise AssertionError("check gave no JSON (rc=%d):\n%s\n%s" % (cp.returncode, cp.stdout[-2000:], cp.stderr[-2000:]))


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def png(path, w=320, h=200):
    """A small colourful test picture (gradients, a checker, a bright disc): edges for the blur to soften."""
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            chk = ((x // 20) + (y // 20)) % 2
            d = ((x - 220) ** 2 + (y - 80) ** 2) ** 0.5
            r = int(40 + 180 * x / w) if not chk else 230
            g = int(60 + 150 * y / h) if not chk else 230
            b = 240 if d < 38 else (90 if chk else 160)
            row += bytes((r, g, b))
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def panel_diff(a, b, w=640):
    """Changed pixels in each third of two frames, and the largest change (to say which look moved)."""
    from st import ff
    raw = [subprocess.run([ff.ffmpeg_path(), "-v", "error", "-i", str(p), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                          stdout=subprocess.PIPE, check=True).stdout for p in (a, b)]
    counts, big = [0, 0, 0], 0
    for i in range(0, min(len(raw[0]), len(raw[1])), 3):
        d = max(abs(raw[0][i + k] - raw[1][i + k]) for k in range(3))
        if d:
            counts[min(2, ((i // 3) % w) * 3 // w)] += 1
            big = max(big, d)
    return counts, big


NO_WEBGL = """<script>
  // as in a browser without WebGL: every WebGL context request fails
  (function () { var g = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (t, o) { return /webgl/i.test(String(t)) ? null : g.call(this, t, o); }; })();
</script>"""


def page(extra_head="", body=None):
    body = body or """
  <div class="p" style="left:0"><div data-st="fluted-glass" data-preset="prism"
    data-keys='[{"at":0,"depth":0},{"at":0.2,"dur":1.4,"depth":0.7}]'><canvas id="src" width="320" height="200"></canvas></div></div>
  <script>
    // a canvas the page draws once, before the components mount: the fluted glass reads it as its picture
    (function () { var g = document.getElementById('src').getContext('2d');
      var gr = g.createLinearGradient(0, 0, 320, 200); gr.addColorStop(0, '#ff4fd8'); gr.addColorStop(1, '#29e7ff');
      g.fillStyle = gr; g.fillRect(0, 0, 320, 200);
      g.fillStyle = '#05060f'; for (var i = 0; i < 8; i++) g.fillRect(i * 40 + 10, 30 + (i % 3) * 40, 18, 90);
      g.fillStyle = '#fff'; g.beginPath(); g.arc(200, 110, 40, 0, 7); g.fill(); })();
  </script>
  <div class="p" style="left:33.333%"><div data-st="tilt-shift" data-src="media/plate.png" data-preset="miniature"
    data-keys='[{"at":0.3,"dur":2,"y":0.25}]'></div></div>
  <div class="p" style="left:66.666%"><div data-st="liquid-metal" data-shape="blob" data-text="Look" data-size="0.9" data-in="0.5"></div></div>"""
    return ("""<!doctype html><html><head><meta charset="utf-8">%s<script src="/_st/stage.js"></script>
<link rel="stylesheet" href="/_st/themes/neon.css"><script type="module" src="/_st/components/index.js"></script>
<style>body{background:#05060f;margin:0} .p{position:absolute;top:0;bottom:0;width:33.334%%;overflow:hidden}</style>
</head><body>%s
</body></html>""" % (extra_head, body))


def quad_diff(a, b, w=640, h=360):
    """Changed pixels in each quadrant of two frames (top-left, top-right, bottom-left, bottom-right) and the largest change."""
    from st import ff
    raw = [subprocess.run([ff.ffmpeg_path(), "-v", "error", "-i", str(p), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                          stdout=subprocess.PIPE, check=True).stdout for p in (a, b)]
    counts, big = [0, 0, 0, 0], 0
    for i in range(0, min(len(raw[0]), len(raw[1])), 3):
        d = max(abs(raw[0][i + k] - raw[1][i + k]) for k in range(3))
        if d:
            px = i // 3
            counts[(2 if (px // w) >= h // 2 else 0) + (1 if (px % w) >= w // 2 else 0)] += 1
            big = max(big, d)
    return counts, big


def page2(extra_head="", theme="neon"):
    """The four newer looks, one per quadrant, each moving (keys, drift, flow, growing in)."""
    body = """
  <div class="q" style="left:0;top:0"><div data-st="mesh-gradient" data-preset="aurora" data-move="0.3" data-speed="4"
    data-keys='[{"at":0,"intensity":0.3},{"at":0.4,"dur":1.6,"intensity":1}]'></div></div>
  <div class="q" style="left:50%;top:0"><div data-st="god-rays" data-text="Rays" data-size="0.34" data-in="0.6"
    data-keys='[{"at":0.5,"dur":2,"x":0.3}]'></div></div>
  <div class="q" style="left:0;top:50%"><div data-st="marble" data-preset="ink" data-speed="6"></div></div>
  <div class="q" style="left:50%;top:50%"><div data-st="metaballs" data-size="0.22" data-in="0.5" data-speed="2"
    data-keys='[{"at":1.2,"dur":1.2,"spread":0.4}]'></div></div>"""
    return ("""<!doctype html><html><head><meta charset="utf-8">%s<script src="/_st/stage.js"></script>
<link rel="stylesheet" href="/_st/themes/%s.css"><script type="module" src="/_st/components/index.js"></script>
<style>body{margin:0;background:var(--bg)} .q{position:absolute;width:50%%;height:50%%;overflow:hidden;background:var(--bg)}</style>
</head><body>%s
</body></html>""" % (extra_head, theme, body))


class LooksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-looks-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def project(self, name, html, w=640, h=360, dur=3.1):
        proj = self.tmp / name
        write(proj / "showtime.json", json.dumps({"width": w, "height": h, "fps": 30, "duration": dur, "background": "#05060f"}))
        write(proj / "index.html", html)
        png(proj / "media" / "plate.png")
        return proj

    def test_01_modules_and_catalog(self):
        node = plat.which("node") or shutil.which("node")
        for f in FILES:
            self.assertTrue(f.is_file(), f)
            if node:
                cp = subprocess.run([node, "--check", str(f)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
                self.assertEqual(cp.returncode, 0, "%s: %s" % (f.name, cp.stderr))
        index = (RUNTIME / "components" / "index.js").read_text(encoding="utf-8")
        for n in ALL:
            self.assertIn("./%s.js" % n, index)
        comps = {c["name"]: c for c in json.loads(showtime("motion", "components", "--json").stdout)["components"]}
        for n in ALL:
            self.assertIn(n, comps)
            self.assertIn("scale", comps[n]["options"])
            self.assertIn("keys", comps[n]["options"])
        for f in FILES:
            src = f.read_text(encoding="utf-8")
            # GLSL portability: reversed smoothstep edges are undefined behaviour on some GPUs
            for m in re.finditer(r"smoothstep\(\s*(-?[0-9.]+)\s*,\s*(-?[0-9.]+)\s*,", src):
                self.assertLess(float(m.group(1)), float(m.group(2)), "%s: reversed smoothstep %s" % (f.name, m.group(0)))
            # GLSL ES 1.00 reserves these names; a variable called one fails to compile on strict drivers
            for word in ("half", "input", "output", "filter", "sizeof", "cast", "namespace", "using", "fixed"):
                self.assertNotRegex(src, r"\b(float|vec[234]|int)\s+%s\b" % word, "%s declares a reserved word: %s" % (f.name, word))
        # every pass kind a look registers has a measured cost (a kind missing from COST_1080P would count as 0 ms)
        gl = (RUNTIME / "effects" / "gl.js").read_text(encoding="utf-8")
        costs = set(re.findall(r"(\w+):\s*[\d.]+", re.search(r"COST_1080P = \{(.*?)\}", gl, re.S).group(1)))
        for n in ALL:
            src = (RUNTIME / "components" / (n + ".js")).read_text(encoding="utf-8")
            kinds = {k for block in re.findall(r"passes: \[(.*?)\] \}\)", src, re.S) for k in re.findall(r"'([\w-]+)'", block)}
            self.assertTrue(kinds, "%s registers no passes" % n)
            self.assertFalse(kinds - costs, "%s: pass kinds without a cost in COST_1080P: %s" % (n, kinds - costs))
        th = json.loads((RUNTIME / "thresholds.json").read_text(encoding="utf-8"))
        self.assertEqual(th["look_budget_ms"], 50)
        self.assertIn("look_budget", (SKILL / "scripts" / "check.mjs").read_text(encoding="utf-8"))

    def test_02_frame_exact_one_and_three_workers(self):
        proj = self.project("exact", page())
        # without a GPU (SwiftShader, what a render box has) and with this machine's own GPU when it has one
        for gpu in ("off", "auto"):
            frames, files = {}, {}
            for w in (1, 3):
                out = self.tmp / ("out-%s-w%d" % (gpu, w)) / "v.mp4"
                showtime("render", proj, "-o", out, "--workers", w, "--gpu", gpu, "--format", "png", "--keep-frames",
                         "--no-audio", "--poster", "none", "--quiet")
                fdir = out.parent / "v.work" / "frames"
                files[w] = sorted(p for p in fdir.iterdir() if p.suffix == ".png")
                self.assertEqual(len(files[w]), 93, "gpu %s, w=%d: %d frames in %s" % (gpu, w, len(files[w]), fdir))
                frames[w] = [hashlib.sha256(p.read_bytes()).hexdigest() for p in files[w]]
            diff = [i for i in range(93) if frames[1][i] != frames[3][i]]
            where = [(i, panel_diff(files[1][i], files[3][i])) for i in diff[:4]]
            for i in (0, 37, 90):
                self.assertEqual(frames[1][i], frames[3][i], "gpu %s: frame %d differs between 1 and 3 workers; first "
                                 "differences (frame, changed pixels per panel, largest change): %s" % (gpu, i, where))
            self.assertEqual(diff, [], "gpu %s: frames that differ between 1 and 3 workers: %s; %s" % (gpu, diff[:12], where))
            self.assertEqual(len({frames[1][0], frames[1][37], frames[1][90]}), 3, "the looks do not move")

    def test_03_no_webgl_draws_the_fallback(self):
        gl = self.project("gl", page())
        nogl = self.project("nogl", page(NO_WEBGL))
        rep = check(nogl)
        items = (rep.get("looks") or {}).get("items") or []
        self.assertEqual(sorted(x["look"] for x in items), sorted(LOOKS), json.dumps(rep.get("looks"))[:800])
        self.assertTrue(all(not x["gl"] for x in items), items)
        codes = [f["code"] for f in rep["findings"]]
        self.assertEqual(codes.count("look_fallback"), 3, codes)
        self.assertFalse([f for f in rep["findings"] if f["code"] in ("page_error", "console_error", "ready_failed")], rep["findings"])
        stills = {}
        for name, proj in (("gl", gl), ("nogl", nogl)):
            r = json.loads(showtime("snap", proj, "--at", "2", "-o", self.tmp / ("snap-" + name), "--format", "png", "--json").stdout)
            stills[name] = Path(r["stills"][0]["file"])
        from st import ff
        sizes = {}
        for name, p in stills.items():
            # 3 x 1 average colours per panel and the spread inside each: fallbacks are drawn, not empty
            cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-i", str(p), "-vf", "scale=3:1:flags=area", "-f", "rawvideo",
                                 "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, check=True)
            sizes[name] = list(cp.stdout)
            cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-i", str(p), "-vf", "scale=48:27:flags=area", "-f", "rawvideo",
                                 "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE, check=True)
            px = list(cp.stdout)
            for k in range(3):
                col = [px[y * 48 + x] for y in range(27) for x in range(k * 16, k * 16 + 16)]
                self.assertGreater(max(col) - min(col), 25, "%s: panel %d is flat" % (name, k))
        d = sum(abs(a - b) for a, b in zip(sizes["gl"], sizes["nogl"])) + \
            abs(stills["gl"].stat().st_size - stills["nogl"].stat().st_size)
        self.assertGreater(d, 0, "the fallback frame is the WebGL frame")

    def test_04_budget_warning(self):
        body = """
  <div class="p" style="left:0;width:50%%"><div data-st="tilt-shift" data-src="media/plate.png" data-scale="1" data-blur="2"
    style="inset:auto;left:0;top:0;width:2400px;height:1350px" id="big"></div></div>
  <div class="p" style="left:50%%;width:50%%"><div data-st="tilt-shift" data-src="media/plate.png" id="small"></div></div>"""
        rep = check(self.project("budget", page(body=body.replace("%%", "%"))))
        items = {x["sel"]: x for x in (rep.get("looks") or {}).get("items", [])}
        self.assertIn("#big", items, items)
        self.assertGreater(items["#big"]["ms"], 50, items["#big"])
        self.assertLess(items["#small"]["ms"], 50, items["#small"])
        warn = [f for f in rep["findings"] if f["code"] == "look_budget"]
        self.assertEqual(len(warn), 1, warn)
        self.assertIn("#big", warn[0]["message"])
        self.assertIn("data-scale", warn[0].get("fix", ""))

    # ------------------------------------------- WebGL contexts (Chrome keeps about 16 per page)
    def gray(self, png_path, w, h):
        from st import ff
        return list(subprocess.run([ff.ffmpeg_path(), "-v", "error", "-i", str(png_path), "-vf", "scale=%d:%d:flags=area" % (w, h),
                                    "-f", "rawvideo", "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE, check=True).stdout)

    def test_05_twenty_looks_at_once(self):
        """20 looks in one scene (more than Chrome's contexts): every tile is drawn (no white, lost tiles), and
        check fails the page (look_contexts) without any lost context."""
        tiles = "".join('<div class="c"><div data-st="fluted-glass" data-preset="reeded" data-seed="%d"></div></div>' % i
                        for i in range(20))
        body = ('<section class="scene" data-start="0" data-dur="3" style="position:absolute;inset:0;display:grid;'
                'grid-template-columns:repeat(5,1fr);gap:8px;padding:8px;background:#111">%s</section>' % tiles)
        proj = self.project("twenty", page(body=body), w=640, h=360, dur=3)
        write(proj / "index.html", (proj / "index.html").read_text(encoding="utf-8").replace(
            "</style>", ".c{position:relative;overflow:hidden}</style>"))
        r = json.loads(showtime("snap", proj, "--at", "1,2", "--gpu", "off", "-o", self.tmp / "twenty-shots", "--format", "png", "--json").stdout)
        for st in r["stills"]:
            px = self.gray(st["file"], 5, 4)            # one value per tile
            self.assertTrue(all(v < 200 for v in px), "a white tile at %s s: %s" % (st["t"], px))
            self.assertTrue(all(v > 20 for v in px), "an empty tile at %s s: %s" % (st["t"], px))
        rep = check(proj, "--gpu", "off")
        self.assertEqual((rep.get("looks") or {}).get("peak", {}).get("looks"), 20, rep.get("looks", {}).get("peak"))
        codes = [f["code"] for f in rep["findings"]]
        err = [f for f in rep["findings"] if f["code"] == "look_contexts"]
        self.assertEqual(len(err), 1, codes)
        self.assertEqual(err[0]["severity"], "error")
        self.assertNotIn("look_lost", codes)

    def test_06_twenty_scenes_seek_anywhere(self):
        """20 scenes with one look each: every scene draws, 1 and 3 workers give the same frames (a worker that
        starts mid-video builds its looks again), check's shuffled-order probe matches, and check counts one
        look on screen at a time (no look_contexts)."""
        scenes = "".join(
            '<section class="scene" id="s%d" data-start="%.1f" data-dur="0.2" style="position:absolute;inset:0;background:#05060f">'
            '<div data-st="fluted-glass" data-preset="%s" data-seed="%d"></div></section>'
            % (i, i * 0.2, ("reeded", "fluted", "prism")[i % 3], i) for i in range(20))
        proj = self.project("scenes", page(body=scenes), w=320, h=180, dur=4)
        frames = {}
        for w in (1, 3):
            out = self.tmp / ("scenes-w%d" % w) / "v.mp4"
            showtime("render", proj, "-o", out, "--workers", w, "--gpu", "off", "--format", "png", "--keep-frames",
                     "--no-audio", "--poster", "none", "--quiet")
            files = sorted((out.parent / "v.work" / "frames").glob("*.png"))
            self.assertEqual(len(files), 120)
            frames[w] = [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]
            if w == 1:
                for i in range(0, 120, 6):          # the first frame of every scene: glass drawn, not the bare ground
                    px = self.gray(files[i], 8, 4)
                    self.assertGreater(max(px) - min(px), 20, "scene %d's first frame is flat" % (i // 6))
        diff = [i for i in range(120) if frames[1][i] != frames[3][i]]
        self.assertEqual(diff, [], "frames that differ between 1 and 3 workers: %s" % diff[:12])
        rep = check(proj, "--gpu", "off")
        self.assertEqual(rep["looks"]["peak"]["looks"], 1, rep["looks"]["peak"])
        codes = [f["code"] for f in rep["findings"]]
        for bad in ("look_contexts", "look_lost", "nondeterministic", "unstable_frame", "page_error"):
            self.assertNotIn(bad, codes, rep["findings"])
        rep = json.loads(showtime("check", proj, "--json", "--determinism", "--no-timeline", "--no-history", "--gpu", "off",
                                  check=False).stdout)
        self.assertTrue(rep.get("determinism"), "no determinism probe ran")
        self.assertFalse([f for f in rep["findings"] if f["code"] in ("nondeterministic", "unstable_frame")], rep["findings"])

    # ------------------------------------------------- the newer looks: mesh-gradient, god-rays, marble, metaballs
    def frames_of(self, proj, tag, workers, gpu):
        out = self.tmp / ("%s-%s-w%d" % (tag, gpu, workers)) / "v.mp4"
        showtime("render", proj, "-o", out, "--workers", workers, "--gpu", gpu, "--format", "png", "--keep-frames",
                 "--no-audio", "--poster", "none", "--quiet")
        files = sorted(p for p in (out.parent / "v.work" / "frames").iterdir() if p.suffix == ".png")
        return files, [hashlib.sha256(p.read_bytes()).hexdigest() for p in files]

    def test_07_newer_looks_frame_exact(self):
        """The four newer looks moving on one page: the same frames with 1 and 3 workers, with and without a GPU,
        and each quadrant moves; without WebGL (fallbacks) too, where the metaballs fallback still moves."""
        cases = [("new", page2(), ("off", "auto")), ("new-nogl", page2(NO_WEBGL), ("off",))]
        for tag, html, gpus in cases:
            proj = self.project(tag, html)
            for gpu in gpus:
                files, frames = {}, {}
                for w in (1, 3):
                    files[w], frames[w] = self.frames_of(proj, tag, w, gpu)
                    self.assertEqual(len(files[w]), 93, "%s gpu %s, w=%d: %d frames" % (tag, gpu, w, len(files[w])))
                diff = [i for i in range(93) if frames[1][i] != frames[3][i]]
                where = [(i, quad_diff(files[1][i], files[3][i])) for i in diff[:4]]
                self.assertEqual(diff, [], "%s gpu %s: frames that differ between 1 and 3 workers: %s; first differences "
                                 "(frame, changed pixels per quadrant, largest change): %s" % (tag, gpu, diff[:12], where))
                moved = quad_diff(files[1][15], files[1][80])[0]
                if tag == "new":
                    self.assertTrue(all(c > 200 for c in moved), "%s: a look does not move (changed pixels per quadrant "
                                    "between 0.5 s and 2.67 s: %s)" % (tag, moved))
                else:
                    # still fallbacks (mesh, rays, marble) and the metaballs one, which moves
                    self.assertGreater(moved[3], 200, "the metaballs fallback does not move: %s" % moved)
                    self.assertEqual(moved[:3], [0, 0, 0], "a still fallback moved: %s" % moved)

    def test_08_newer_looks_fallbacks(self):
        """Without WebGL each newer look draws its fallback: check lists four, each quadrant is drawn (not flat) and
        differs from the WebGL frame."""
        gl = self.project("new-gl", page2(theme="neutral"))
        nogl = self.project("new-nogl2", page2(NO_WEBGL, theme="neutral"))
        rep = check(nogl)
        items = (rep.get("looks") or {}).get("items") or []
        self.assertEqual(sorted(x["look"] for x in items), sorted(NEW), json.dumps(rep.get("looks"))[:800])
        self.assertTrue(all(not x["gl"] for x in items), items)
        fb = [f for f in rep["findings"] if f["code"] == "look_fallback"]
        self.assertEqual(len(fb), 4, [f["code"] for f in rep["findings"]])
        self.assertTrue(any("metaballs" in f["message"] and "still fallback" not in f["message"] for f in fb), fb)
        self.assertFalse([f for f in rep["findings"] if f["code"] in ("page_error", "console_error", "ready_failed")], rep["findings"])
        stills = {}
        for name, proj in (("gl", gl), ("nogl", nogl)):
            r = json.loads(showtime("snap", proj, "--at", "2", "-o", self.tmp / ("snap-new-" + name), "--format", "png", "--json").stdout)
            stills[name] = Path(r["stills"][0]["file"])
            px = self.gray(stills[name], 16, 8)
            for qy in (0, 1):
                for qx in (0, 1):
                    q = [px[y * 16 + x] for y in range(qy * 4, qy * 4 + 4) for x in range(qx * 8, qx * 8 + 8)]
                    self.assertGreater(max(q) - min(q), 12, "%s: quadrant %d,%d is flat: %s" % (name, qx, qy, q))
        counts, big = quad_diff(stills["gl"], stills["nogl"])
        self.assertTrue(all(c > 0 for c in counts), "a fallback frame is the WebGL frame: %s" % counts)

    def test_09_newer_looks_budget(self):
        """At their defaults over a 1080p frame the newer looks estimate under the budget; a marble at twice the
        size warns, with its knob."""
        looks = {
            "mesh": '<div data-st="mesh-gradient" id="mesh"></div>',
            "rays": '<div data-st="god-rays" data-text="Northlight" id="rays"></div>',
            "stone": '<div data-st="marble" id="stone"></div>',
            "goo": '<div data-st="metaballs" id="goo"></div>',
            "big": '<div data-st="marble" data-scale="2" id="big"></div>',
        }
        body = "".join('<section class="scene" data-start="%d" data-dur="1" style="position:absolute;inset:0">%s</section>' % (i, el)
                       for i, el in enumerate(looks.values()))
        proj = self.project("new-budget", page(body=body), w=1920, h=1080, dur=5)
        rep = check(proj)
        items = {x["sel"]: x for x in (rep.get("looks") or {}).get("items", [])}
        for k in ("mesh", "rays", "stone", "goo"):
            self.assertIn("#" + k, items, items)
            self.assertGreater(items["#" + k]["ms"], 0, items["#" + k])
            self.assertLess(items["#" + k]["ms"], 50, items["#" + k])
        self.assertGreater(items["#big"]["ms"], 50, items["#big"])
        warn = [f for f in rep["findings"] if f["code"] == "look_budget"]
        self.assertEqual(len(warn), 1, warn)
        self.assertIn("#big", warn[0]["message"])
        self.assertIn("data-scale", warn[0].get("fix", ""))


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

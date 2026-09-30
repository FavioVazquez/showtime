#!/usr/bin/env python3
"""`showtime adopt`: videos written as a function of time become showtime projects, unchanged.

Fixtures (tests/fixtures/adopt/), written the way a model writes them with no tools:
  html-seek       DOM page, `function seek(t)` + `window.seek`, top-level `const DURATION`, a rAF preview loop
  canvas-draw     canvas `window.draw(t)` whose puppeteer driver injects data with `window.setData(rows)`
  css-clock       CSS @keyframes only (the virtual clock drives it; length inferred from the animations)
  python-pil      Pillow `render(t)` + W/H/FPS/DURATION + a main guard (frames drawn in separate processes)
  python-capture  no frame function, no main guard: its own run writes clip.mp4 with a tone (ingested)

Fast (no browser): the Python harness (static scan, frame function pick, bytes frames, the two-order
hash that catches state kept between frames, the network guard) and the static page/driver scan.
Full: every fixture adopted into a project; contract, size, fps and length as expected; the original
folder byte-identical afterwards; determinism measured; `check` clean; `render --from/--to`; `snap`
shows the injected data (setup script); `export html`; a nondeterministic page and a missing setup
fail with what/why/fix; `--refresh` picks up an edited original.

usage: python tests/test_adopt.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
HARNESS = SKILL / "lib" / "st" / "adopt_harness.py"
FIX = TESTS_DIR / "fixtures" / "adopt"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
TMP = Path(tempfile.mkdtemp(prefix="st-adopt-"))


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def showtime(*args, check=True, cwd=None, timeout=900):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-4000:]))
    return cp


def tree_hash(d: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(d.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(d)).encode())
            h.update(p.read_bytes())
            h.update(str(p.stat().st_mtime_ns).encode())
    return h.hexdigest()


def harness(*args, cwd=None, env=None):
    return subprocess.run([sys.executable, str(HARNESS)] + [str(a) for a in args], cwd=cwd, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)


def node_eval(code: str):
    node = shutil.which("node", path=ENV.get("PATH")) or "node"
    cp = subprocess.run([node, "--input-type=module", "-e", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding="utf-8", timeout=60, cwd=str(SKILL))
    if cp.returncode:
        raise AssertionError(cp.stderr[-2000:])
    return json.loads(cp.stdout)


BYTES_GEN = '''
W, H = 8, 4
FPS = 10
DURATION = 1.5
def render_frame(i):
    return bytes([(i * 7) % 256, 10, 20]) * (W * H)
if __name__ == "__main__":
    pass
'''

STATEFUL_GEN = '''
W, H, FPS, DURATION = 4, 2, 10, 1.0
_n = [0]
def render(t):
    _n[0] += 1
    return bytes([_n[0] % 256, 0, 0]) * (W * H)
if __name__ == "__main__":
    pass
'''

NET_GEN = '''
import socket
W, H, FPS, DURATION = 2, 2, 1, 1
try:
    socket.create_connection(("example.com", 80), timeout=2)
    NET = "open"
except PermissionError as e:
    NET = "blocked"
except OSError:
    NET = "oserror"
def render(t):
    assert NET == "blocked", NET
    return bytes(12)
if __name__ == "__main__":
    pass
'''


class Harness(unittest.TestCase):
    """The Python side, stdlib frames (no Pillow needed)."""

    def write(self, name, text):
        d = TMP / ("h-" + name)
        d.mkdir(exist_ok=True)
        f = d / (name + ".py")
        f.write_text(text)
        return f

    def test_inspect_picks_frame_function_and_numbers(self):
        f = self.write("bytesgen", BYTES_GEN)
        cp = harness("inspect", f, cwd=f.parent)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode())
        i = json.loads(cp.stdout)
        self.assertTrue(i["import_safe"])
        self.assertEqual(i["fn"]["name"], "render_frame")
        self.assertEqual(i["fn"]["unit"], "frame")
        self.assertEqual(i["fn"]["nbytes"], 8 * 4 * 3)
        self.assertEqual(i["numbers"]["FPS"], 10)
        self.assertEqual(i["numbers"]["DURATION"], 1.5)

    def test_frames_stream_in_order(self):
        f = self.write("bytesgen2", BYTES_GEN)
        cp = harness("frames", f, "--fn", "render_frame", "--unit", "frame", "--fps", "10", "--size", "8x4",
                     "--from", "3", "--to", "6", cwd=f.parent)
        self.assertEqual(cp.returncode, 0, cp.stderr.decode())
        fb = 8 * 4 * 3
        self.assertEqual(len(cp.stdout), 3 * fb)
        self.assertEqual([cp.stdout[k * fb] for k in range(3)], [21, 28, 35])

    def test_hash_catches_state_between_frames(self):
        good = self.write("good", BYTES_GEN)
        h = json.loads(harness("hash", good, "--fn", "render_frame", "--unit", "frame", "--fps", "10", "--size", "8x4",
                               "--frames", "0,5,9", cwd=good.parent).stdout)
        self.assertEqual(h["pass1"], h["pass2"])
        bad = self.write("stateful", STATEFUL_GEN)
        h = json.loads(harness("hash", bad, "--fn", "render", "--unit", "s", "--fps", "10", "--size", "4x2",
                               "--frames", "0,5,9", cwd=bad.parent).stdout)
        self.assertNotEqual(h["pass1"], h["pass2"])

    def test_network_is_refused_inside_the_script(self):
        f = self.write("netgen", NET_GEN)
        cp = harness("inspect", f, cwd=f.parent)
        i = json.loads(cp.stdout)
        self.assertNotIn("import_error", i, i)
        self.assertEqual(i.get("fn", {}).get("name"), "render", i)

    def test_no_main_guard_is_not_imported(self):
        f = self.write("noguard", "W, H = 2, 2\nopen('ran.txt', 'w').write('x')\ndef render(t):\n    return bytes(12)\n")
        i = json.loads(harness("inspect", f, cwd=f.parent).stdout)
        self.assertFalse(i["import_safe"])
        self.assertFalse((f.parent / "ran.txt").exists(), "inspect ran a script without a main guard")


class Scan(unittest.TestCase):
    """Static page/driver detection (node, no browser)."""

    def test_page_and_driver(self):
        r = node_eval(
            "import fs from 'node:fs';"
            "import { scanPage, scanDriver, pickSource, listFiles } from './scripts/lib/adopt/scan.mjs';"
            "const f = (p) => fs.readFileSync(p, 'utf8');"
            "const seek = scanPage(f('tests/fixtures/adopt/html-seek/video.html'));"
            "const canvas = scanPage(f('tests/fixtures/adopt/canvas-draw/story.html'));"
            "const drv = scanDriver(f('tests/fixtures/adopt/canvas-draw/render.js'), 'render.js');"
            "const root = 'tests/fixtures/adopt/canvas-draw';"
            "const pick = pickSource(root, listFiles(root));"
            "console.log(JSON.stringify({ seek, canvas, drv, pick: { kind: pick.kind, file: pick.file } }));")
        self.assertEqual([f["name"] for f in r["seek"]["fns"]][:1], ["seek"])
        self.assertEqual(r["seek"]["durations"].get("DURATION"), 4)
        self.assertEqual(r["seek"]["size"]["width"], 1280)
        self.assertEqual(r["canvas"]["fns"][0]["name"], "draw")
        self.assertIn("setData", r["canvas"]["setters"])
        self.assertEqual(r["drv"]["calls"][0]["name"], "draw")
        self.assertEqual(r["drv"]["calls"][0]["unit"], "s")
        self.assertEqual([s["name"] for s in r["drv"]["setup"]], ["setData"])
        self.assertEqual((r["drv"]["size"]["width"], r["drv"]["size"]["height"]), (1280, 720))
        self.assertEqual(r["pick"], {"kind": "page", "file": "story.html"})


@unittest.skipIf(FAST, "--fast")
class Adopt(unittest.TestCase):
    """Real adoptions of the fixtures (browser, ffmpeg, Pillow from showtime's venv)."""

    def adopt(self, fixture, *extra, name=None, check=True):
        src = FIX / fixture
        before = tree_hash(src)
        out = TMP / (name or fixture)
        cp = showtime("adopt", src, "-o", out, *extra, check=check)
        self.assertEqual(tree_hash(src), before, "adopt changed the original folder")
        rep = json.loads((out / "adopt.json").read_text()) if (out / "adopt.json").exists() else None
        return cp, out, rep

    def test_html_seek(self):
        cp, out, rep = self.adopt("html-seek")
        self.assertEqual(rep["contract"], "page: seek(t)")
        self.assertEqual((rep["width"], rep["height"], rep["fps"], rep["duration"]), (1280, 720, 30, 4))
        self.assertEqual(rep["determinism"]["verdict"], "deterministic", rep["determinism"])
        self.assertEqual(rep["check"]["errors"], 0, rep["check"])
        self.assertTrue((out / "src" / "video.html").exists())
        cfg = json.loads((out / "showtime.json").read_text())
        self.assertEqual(cfg["adopt"]["entry"], "video.html")
        showtime("render", out, "--from", "1", "--to", "2", "--preview", "-o", TMP / "seek-part.mp4")
        self.assertTrue((TMP / "preview.mp4").exists() or any(TMP.glob("seek-part*.mp4")))
        showtime("export", "html", out, "-o", TMP / "seek.html")
        self.assertGreater((TMP / "seek.html").stat().st_size, 10000)

    def test_canvas_needs_setup_then_setup_works(self):
        cp, out, rep = self.adopt("canvas-draw", name="canvas-nosetup", check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("setData", cp.stderr)
        self.assertIn("fix:", cp.stderr)
        self.assertIn("--setup", cp.stderr)
        cp, out, rep = self.adopt("canvas-draw", "--setup", FIX / "canvas-draw" / "setup.js", name="canvas")
        self.assertEqual(rep["contract"], "page: draw(t)")
        self.assertEqual(rep["duration"], 3)
        self.assertEqual(rep["determinism"]["verdict"], "deterministic")
        showtime("snap", out, "--at", "2.5")
        from PIL import Image
        im = Image.open(out / "work" / "snap" / "t0002.500s.png").convert("RGB")
        greens = sum(1 for x in range(0, 1280, 8) for y in range(300, 640, 8) if im.getpixel((x, y)) == (63, 185, 80))
        self.assertGreater(greens, 100, "the bars from data.json are not drawn: the setup script did not run")

    def test_css_clock(self):
        cp, out, rep = self.adopt("css-clock", "--no-check")
        self.assertTrue(rep["contract"].startswith("clock"), rep["contract"])
        self.assertAlmostEqual(rep["duration"], 3, places=2)
        self.assertEqual(rep["determinism"]["verdict"], "deterministic")

    def test_python_frames(self):
        cp, out, rep = self.adopt("python-pil")
        self.assertEqual(rep["kind"], "python")
        self.assertTrue(rep["contract"].startswith("python: render(t)"), rep["contract"])
        self.assertEqual((rep["width"], rep["height"], rep["fps"], rep["duration"]), (640, 360, 24, 2))
        self.assertEqual(rep["determinism"]["verdict"], "deterministic")
        self.assertTrue((out / "media" / "frames.webm").exists())
        self.assertFalse(list((FIX / "python-pil").glob("*.mp4")), "the original folder got a video")
        showtime("render", out, "-o", TMP / "pil.mp4")
        q = showtime("qa", TMP / "pil.mp4", "--project", out, "--json", check=False)
        self.assertIn(json.loads(q.stdout)["verdict"], ("PASS", "WARN"), q.stdout[-2000:])

    def test_python_capture(self):
        cp, out, rep = self.adopt("python-capture")
        self.assertEqual(rep["kind"], "capture")
        self.assertEqual((rep["width"], rep["height"], rep["fps"]), (320, 180, 20))
        self.assertAlmostEqual(rep["duration"], 2, delta=0.1)
        self.assertTrue((out / "media" / "original-audio.wav").exists())
        mix = json.loads((out / "audio" / "mix.json").read_text())
        self.assertEqual(mix["tracks"][0]["file"], "media/original-audio.wav")
        self.assertFalse((FIX / "python-capture" / "clip.mp4").exists())

    def test_nondeterministic_page_fails(self):
        d = TMP / "stateful-page"
        d.mkdir()
        (d / "index.html").write_text(
            "<!doctype html><html><head><style>body{margin:0;width:640px;height:360px;background:#222}"
            "#b{position:absolute;top:100px;width:120px;height:120px;background:#fc0}</style></head><body><div id=b></div>"
            "<script>let x = 0; window.DURATION = 2; window.render = function (t) { x += 25; "
            "document.getElementById('b').style.left = (x % 500) + 'px'; };</script></body></html>")
        cp = showtime("adopt", d, "-o", TMP / "stateful-out", "--no-check", check=False)
        self.assertEqual(cp.returncode, 1, cp.stderr)
        self.assertIn("frames differ", cp.stderr)
        self.assertIn("fix:", cp.stderr)

    def test_errors_say_what_why_fix(self):
        empty = TMP / "empty"
        empty.mkdir()
        (empty / "notes.txt").write_text("hi")
        cp = showtime("adopt", empty, "-o", TMP / "empty-out", check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("no video source found", cp.stderr)
        self.assertIn("fix:", cp.stderr)

    def test_refresh_after_editing_the_original(self):
        src = TMP / "editable"
        shutil.copytree(FIX / "html-seek", src)
        out = TMP / "editable-out"
        showtime("adopt", src, "-o", out, "--no-check")
        page = src / "video.html"
        page.write_text(page.read_text().replace("const DURATION = 4;", "const DURATION = 5;"))
        showtime("adopt", out, "--refresh", "--no-check")
        rep = json.loads((out / "adopt.json").read_text())
        self.assertEqual(rep["duration"], 5)
        self.assertIn("DURATION = 5", (out / "src" / "video.html").read_text())
        cp = showtime("adopt", out, check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("--refresh", cp.stderr)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv)

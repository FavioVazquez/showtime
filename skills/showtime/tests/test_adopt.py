#!/usr/bin/env python3
"""`showtime adopt`: videos written as a function of time become showtime projects, unchanged.

Fixtures (tests/fixtures/adopt/), written the way a model writes them with no tools:
  html-seek       DOM page, `function seek(t)` + `window.seek`, top-level `const DURATION`, a rAF preview loop
  canvas-draw     canvas `window.draw(t)` whose puppeteer driver injects data with `window.setData(rows)`
  css-clock       CSS @keyframes only (the virtual clock drives it; length inferred from the animations)
  python-pil      Pillow `render(t)` + W/H/FPS/DURATION + a main guard (frames drawn in separate processes)
  python-capture  no frame function, no main guard: its own run writes clip.mp4 with a tone (ingested)
  design-dc       a Claude Design export as it is structured (<x-dc> template, a DCLogic class on a performance.now
                  requestAnimationFrame clock with `% 5` and `Math.min(t, 4)`, $preview 640x360, a Google Fonts link),
                  run by a small stand-in runtime written for these tests (dc-mini.js; the real one is not copied)
  design-loop     the same shape at 360x640 animated only by CSS keyframes that repeat forever (4 s loop)

Fast (no browser): the Python harness (static scan, frame function pick, bytes frames, the two-order
hash that catches state kept between frames, the network guard) and the static page/driver scan.
Full: every fixture adopted into a project; contract, size, fps and length as expected; the original
folder byte-identical afterwards; determinism measured; `check` clean; a Python render shows every
frame at its own time (none black, none late: renders draw the video on a canvas); `render --from/--to`;
`snap` shows the injected data (setup script); `export html`; a nondeterministic page and a missing
setup fail with what/why/fix; `--refresh` picks up an edited original; a Claude Design zip fills a 1920x1080
frame (CSS zoom, box at 3x), its length comes from the clock and its loop renders exactly one period whose
next frame is frame 0; Google Fonts are copied with their licenses (download mocked) or say what to run offline.

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


def video_rows(video, y, width=640):
    """Pixel row y of every frame of a video, as RGB bytes."""
    from st import ff
    raw = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-i", str(video), "-vf", "format=rgb24,crop=%d:1:0:%d" % (width, y),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, check=True).stdout
    return [raw[i:i + 3 * width] for i in range(0, len(raw), 3 * width)]


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

    def test_claude_design_export(self):
        r = node_eval(
            "import fs from 'node:fs';"
            "import { pickSource, listFiles } from './scripts/lib/adopt/scan.mjs';"
            "import { scanClaudeDesign, jsClockLength } from './scripts/lib/adopt/design.mjs';"
            "const f = (p) => fs.readFileSync(p, 'utf8');"
            "const dc = scanClaudeDesign(f('tests/fixtures/adopt/design-dc/Main.dc.html'));"
            "const loop = scanClaudeDesign(f('tests/fixtures/adopt/design-loop/Main.dc.html'));"
            "const plain = scanClaudeDesign(f('tests/fixtures/adopt/html-seek/video.html'));"
            "const quoted = scanClaudeDesign('<x-dc><div></div></x-dc><script src=\"support.js\"></script>' +"
            "  '<script type=\"text/x-dc\" data-dc-script data-props=\"{&quot;$preview&quot;:{&quot;width&quot;:1080,&quot;height&quot;:1350}}\">class Component extends DCLogic {}</script>');"
            "const root = 'tests/fixtures/adopt/design-dc';"
            "const pick = pickSource(root, listFiles(root));"
            "console.log(JSON.stringify({ dc: dc.artboard, loop: loop.artboard, plain, quoted: quoted.artboard, pick: pick.file,"
            "  clock: jsClockLength(dc.logic), none: jsClockLength(loop.logic) }));")
        self.assertEqual(r["dc"], {"width": 640, "height": 360})
        self.assertEqual(r["loop"], {"width": 360, "height": 640})
        self.assertIsNone(r["plain"])
        self.assertEqual(r["quoted"], {"width": 1080, "height": 1350})
        self.assertEqual(r["pick"], "Main.dc.html")
        self.assertEqual((r["clock"]["seconds"], r["clock"]["loop"]), (4, False))
        self.assertIn("Math.min(t, 4)", r["clock"]["how"])
        self.assertIsNone(r["none"])

    def test_js_clock_length(self):
        r = node_eval(
            "import { jsClockLength } from './scripts/lib/adopt/design.mjs';"
            "const out = {"
            "  sample: jsClockLength('componentDidMount(){ this._s = performance.now(); const tick = (now) => {'"
            "    + ' const t = ((now - this._s) / 1000) % 13; this.setState({ t: Math.min(t, 12) }); requestAnimationFrame(tick); }; }'"
            "    + ' renderVals(){ const t = this.state.t; const blink = Math.floor(t * 2) % 2; const c = Math.min(1, t); }'),"
            "  ms: jsClockLength('function frame(now){ const t = (now - start) % 6000; requestAnimationFrame(frame); }'),"
            "  named: jsClockLength('const LOOP = 8, END = 7;\\nfunction f(now){ let time = (performance.now() / 1000) % LOOP;\\n time = Math.min(time, END); requestAnimationFrame(f); }'),"
            "  noclock: jsClockLength('const t = 3 % 2;'),"
            # a cursor blink before the clock line is not the loop (it used to give a 2 s loop and drop the clamp)
            "  blink: jsClockLength('componentDidMount(){ this._s = performance.now(); const tick = (now) => {'"
            "    + '\\n const caret = Math.floor(performance.now() / 530) % 2;'"
            "    + '\\n const t = ((now - this._s) / 1000) % 13; this.setState({ t: Math.min(t, 12), caret }); requestAnimationFrame(tick); }; }'),"
            "  secs: jsClockLength('function f(){ const t = (performance.now() / 1000) % 9; requestAnimationFrame(f); }'),"
            "};"
            "console.log(JSON.stringify(out));")
        self.assertEqual((r["sample"]["seconds"], r["sample"]["loop"]), (12, False))
        self.assertIn("13 s loop", r["sample"]["how"])
        self.assertEqual((r["ms"]["seconds"], r["ms"]["loop"]), (6, True))
        self.assertEqual((r["named"]["seconds"], r["named"]["loop"]), (7, False))
        self.assertIsNone(r["noclock"])
        self.assertEqual((r["blink"]["seconds"], r["blink"]["loop"]), (12, False), r["blink"])
        self.assertEqual((r["secs"]["seconds"], r["secs"]["loop"]), (9, True))

    def test_css_loop_length(self):
        r = node_eval(
            "import { cssLoopLength } from './scripts/lib/adopt/design.mjs';"
            "const inf = (name, duration, direction = 'normal', delay = 0) => ({ name, duration, direction, delay, iterations: null });"
            "console.log(JSON.stringify({"
            "  sample: cssLoopLength([inf('sky', 10000, 'alternate'), inf('glow', 5000, 'alternate'), inf('wait-in', 10000), inf('line-1', 10000)]),"
            "  one: cssLoopLength([inf('spin', 3000), inf('spin2', 3000)]),"
            "  delayed: cssLoopLength([inf('a', 2000, 'normal', 500)]),"
            "  mixed: cssLoopLength([inf('a', 2000), { name: 'intro', duration: 5000, delay: 1000, iterations: 1, direction: 'normal' }]),"
            "  apart: cssLoopLength([inf('a', 7000), inf('b', 11000), inf('c', 13000)]),"
            "  finite: cssLoopLength([{ name: 'x', duration: 3000, delay: 0, iterations: 1, direction: 'normal' }]),"
            "}));")
        self.assertEqual((r["sample"]["seconds"], r["sample"]["loop"]), (20, True))
        self.assertIn("there and back", r["sample"]["how"])
        self.assertIn("--duration 10", r["sample"]["how"])
        self.assertEqual((r["one"]["seconds"], r["one"]["loop"]), (3, True))
        self.assertEqual((r["delayed"]["seconds"], r["delayed"]["loop"]), (2, False))
        self.assertEqual((r["mixed"]["seconds"], r["mixed"]["loop"]), (6, False))
        self.assertEqual((r["apart"]["seconds"], r["apart"]["loop"]), (13, False))
        self.assertIsNone(r["finite"])

    def test_artboard_fit(self):
        r = node_eval(
            "import { fitArtboard, fitCss } from './scripts/lib/adopt/design.mjs';"
            "const sq = fitArtboard({ width: 1280, height: 720 }, { width: 1080, height: 1080 });"
            "console.log(JSON.stringify({ wide: fitArtboard({ width: 1280, height: 720 }), tall: fitArtboard({ width: 540, height: 960 }),"
            "  same: fitArtboard({ width: 1920, height: 1080 }), sq, sqCss: fitCss(sq), sameCss: fitCss(fitArtboard({ width: 1920, height: 1080 })) }));")
        self.assertEqual((r["wide"]["width"], r["wide"]["height"], r["wide"]["zoom"]), (1920, 1080, 1.5))
        self.assertEqual((r["tall"]["width"], r["tall"]["height"], r["tall"]["zoom"]), (1080, 1920, 2))
        self.assertEqual((r["sq"]["width"], r["sq"]["height"], r["sq"]["x"]), (1080, 1080, 0))
        self.assertAlmostEqual(r["sq"]["y"], 280, delta=1)
        self.assertIn("html{zoom:0.844}", r["sqCss"])
        self.assertIn("top:", r["sqCss"])
        # the body is the frame in zoomed pixels (1080 / 0.844), not 1080 CSS px that clip at 911 on screen
        self.assertIn("width:1279.621px!important;height:1279.621px!important", r["sqCss"])
        self.assertEqual(r["sameCss"], "")

    def test_font_links_become_local(self):
        r = node_eval(
            "import fs from 'node:fs';"
            "import { googleFontLinks, dropFontLinks } from './scripts/lib/adopt/design.mjs';"
            "const html = fs.readFileSync('tests/fixtures/adopt/design-dc/Main.dc.html', 'utf8') +"
            "  '<style>@import url(\"https://fonts.googleapis.com/css?family=Inter\");</style>';"
            "const links = googleFontLinks(html);"
            "const out = dropFontLinks(html, links.map((l) => l.url));"
            "const kept = dropFontLinks(html, []);"
            "console.log(JSON.stringify({ links: links.map((l) => l.url), out, same: kept === html }));")
        self.assertEqual(r["links"], ["https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@700&display=swap",
                                      "https://fonts.googleapis.com/css?family=Inter"])
        self.assertNotIn("fonts.googleapis.com", r["out"])
        self.assertIn("font-family: 'Space Grotesk'", r["out"])
        self.assertTrue(r["same"], "nothing made local: the page keeps its links")

    def test_font_failures_are_told_apart(self):
        r = node_eval(
            "import { fontFetchFailure } from './scripts/lib/adopt/design.mjs';"
            "console.log(JSON.stringify({"
            "  lic: fontFetchFailure('error: Spare Font is licensed unknown (not in the Fontsource catalog)\\n  fix: showtime copies OFL/Apache/MIT/UFL fonts by default; pass --allow-license to override\\n'),"
            "  off: fontFetchFailure('showtime: copying\\nerror: offline mode (SHOWTIME_OFFLINE=1): cannot fetch https://fonts.googleapis.com/css2?family=Inter\\n'),"
            "  net: fontFetchFailure('error: network error fetching https://fonts.googleapis.com/css2: timed out\\n  fix: check your internet connection'),"
            "  host: fontFetchFailure('error: the stylesheet names a font file outside https://fonts.gstatic.com/: http://x/y.woff2\\n  fix: ...'),"
            "  none: fontFetchFailure('', 2),"
            "}));")
        self.assertEqual(r["lic"]["code"], "fonts_license")
        self.assertEqual(r["lic"]["why"], "Spare Font is licensed unknown (not in the Fontsource catalog)", "the error line, not the fix line")
        self.assertEqual((r["off"]["code"], r["net"]["code"]), ("fonts_offline", "fonts_offline"))
        self.assertEqual(r["host"]["code"], "fonts_failed")
        self.assertEqual(r["none"], {"code": "fonts_failed", "why": "exit 2"})

    def test_zip_unpacking_caps_entries_and_keeps_the_old_folder(self):
        import re
        import zipfile
        text = (SKILL / "scripts" / "adopt.mjs").read_text(encoding="utf-8")
        code = re.search(r"const UNZIP_PY = `(.*?)`;", text, re.S).group(1).replace("\\\\", "\\")
        d = TMP / "unzip"
        d.mkdir()

        def unzip(z, out, *cap):
            return subprocess.run([sys.executable, "-c", code, str(z), str(out), *map(str, cap)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        many = d / "many.zip"
        with zipfile.ZipFile(many, "w") as z:
            for i in range(30):
                z.writestr("m/f%02d" % i, b"")
        out = d / "src"
        out.mkdir()
        (out / "old.txt").write_text("before")
        cp = unzip(many, out, 20)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("30 entries (more than 20)", cp.stderr)
        # a zip that fails its CRC halfway: the old folder stays whole, no half-unpacked copy is left
        bad = d / "bad.zip"
        with zipfile.ZipFile(bad, "w", zipfile.ZIP_STORED) as z:
            z.writestr("a.txt", b"first file")
            z.writestr("b.txt", b"hello world, this is the second file")
        raw = bytearray(bad.read_bytes())
        k = raw.find(b"second file")
        raw[k] ^= 0x20
        bad.write_bytes(bytes(raw))
        cp = unzip(bad, out)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("nothing was replaced", cp.stderr)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["old.txt"])
        self.assertFalse((d / "src.new").exists())
        good = d / "good.zip"
        with zipfile.ZipFile(good, "w") as z:
            z.writestr("index.html", "<html></html>")
        cp = unzip(good, out)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["index.html"])
        self.assertFalse((d / "src.new").exists())

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


GOOGLE_CSS = """/* latin-ext */
@font-face {
  font-family: 'Space Grotesk';
  font-style: normal;
  font-weight: 700;
  font-display: swap;
  src: url(https://fonts.gstatic.com/s/spacegrotesk/v1/ext.woff2) format('woff2');
  unicode-range: U+0100-02BA;
}
/* latin */
@font-face {
  font-family: 'Space Grotesk';
  font-style: normal;
  font-weight: 700;
  font-display: swap;
  src: url(https://fonts.gstatic.com/s/spacegrotesk/v1/latin.woff2) format('woff2');
  unicode-range: U+0000-00FF;
}
/* latin */
@font-face {
  font-family: 'Spare Font';
  font-style: normal;
  font-weight: 400;
  src: url(https://fonts.gstatic.com/s/spare/v1/latin.woff2) format('woff2');
}
"""


class GoogleFonts(unittest.TestCase):
    """fonts.from_css: the files a Google Fonts link serves, local, with their licenses (network mocked)."""

    def setUp(self):
        from st.assets import fonts, net
        self.fonts, self.net = fonts, net
        self.calls = []
        self.saved = {k: getattr(net, k) for k in ("get_bytes", "download")}
        self.saved.update({k: getattr(fonts, k) for k in ("find", "details", "_fetch_license_text")})
        self.licenses = {"Space Grotesk": "OFL-1.1", "Spare Font": "OFL-1.1"}

        def get_bytes(url, headers=None, **kw):
            self.calls.append(("css", url, (headers or {}).get("User-Agent", "")))
            return GOOGLE_CSS.encode(), "text/css"

        def download(url, dest, **kw):
            self.calls.append(("file", url))
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            body = b"wOF2" + url.encode()
            dest.write_bytes(body)
            return {"path": str(dest), "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                    "content_type": "font/woff2", "ext": "woff2"}

        def lic_text(meta, dest):
            dest.write_text("SIL Open Font License 1.1\n")
            return "mock"

        net.get_bytes, net.download = get_bytes, download
        fonts.find = lambda fam: {"id": fonts.to_id(fam), "family": fam, "license": self.licenses[fam]}
        fonts.details = lambda fid: {"id": fid}
        fonts._fetch_license_text = lic_text

    def tearDown(self):
        for k in ("get_bytes", "download"):
            setattr(self.net, k, self.saved[k])
        for k in ("find", "details", "_fetch_license_text"):
            setattr(self.fonts, k, self.saved[k])

    def test_from_css(self):
        dest = TMP / "gf-fonts"
        url = "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@700&amp;display=swap"
        m = self.fonts.from_css(url, dest)
        self.assertIn("Chrome", self.calls[0][2], "Google serves WOFF2 only to a browser agent")
        self.assertEqual(self.calls[0][1], url.replace("&amp;", "&"))
        self.assertEqual([f["family"] for f in m["families"]], ["Space Grotesk", "Spare Font"])
        css = (dest / "fonts.css").read_text()
        self.assertNotIn("gstatic", css.split("*/", 1)[1])
        self.assertIn('src: url("space-grotesk/space-grotesk-latin-700-normal.woff2") format("woff2")', css)
        self.assertIn("unicode-range: U+0000-00FF;", css)
        self.assertNotIn("font-display: swap", css)
        self.assertEqual(css.count("font-display: block"), 3)
        for f in ("space-grotesk/space-grotesk-latin-700-normal.woff2", "space-grotesk/space-grotesk-latin-ext-700-normal.woff2",
                  "space-grotesk/LICENSE.txt", "spare-font/spare-font-latin-400-normal.woff2"):
            self.assertTrue((dest / f).is_file(), f)
        lic = json.loads((dest / "space-grotesk" / "space-grotesk.license.json").read_text())
        self.assertEqual((lic["license"], lic["source"], lic["license_class"]), ("OFL-1.1", "google-fonts", "free"))
        self.assertEqual(lic["stylesheet"], url.replace("&amp;", "&"))
        # again: the same files are kept, nothing is downloaded
        n = len([c for c in self.calls if c[0] == "file"])
        self.fonts.from_css(url, dest)
        self.assertEqual(len([c for c in self.calls if c[0] == "file"]), n)

    def test_refuses_other_hosts_and_licenses(self):
        from st.common import ShowtimeError
        with self.assertRaises(ShowtimeError):
            self.fonts.from_css("https://example.com/css2?family=Inter", TMP / "gf-x")
        self.licenses["Spare Font"] = "Proprietary"
        with self.assertRaises(ShowtimeError) as cm:
            self.fonts.from_css("https://fonts.googleapis.com/css2?family=Spare+Font", TMP / "gf-y")
        self.assertIn("Proprietary", str(cm.exception))

    def test_refresh_offline_keeps_the_local_fonts(self):
        from st.common import ShowtimeError
        dest = TMP / "gf-offline"
        url = "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@700"
        self.fonts.from_css(url, dest)
        css = (dest / "fonts.css").read_text()
        (dest / "fonts.css").unlink()

        def offline(*a, **k):
            raise ShowtimeError("offline mode (SHOWTIME_OFFLINE=1): cannot fetch %s" % a[0])
        self.net.get_bytes = self.net.download = offline
        self.fonts.find = self.fonts.details = offline
        # every file is still there with its sha256: no network, the same stylesheet written again
        m = self.fonts.from_css(url, dest)
        self.assertEqual(m["css"], "fonts.css")
        self.assertEqual((dest / "fonts.css").read_text(), css)
        self.assertEqual([f["family"] for f in m["families"]], ["Space Grotesk", "Spare Font"])
        # a file that changed is fetched again (and offline, that fails and says so)
        (dest / "spare-font" / "spare-font-latin-400-normal.woff2").write_bytes(b"wOF2changed")
        with self.assertRaises(ShowtimeError) as cm:
            self.fonts.from_css(url, dest)
        self.assertIn("offline", str(cm.exception))

    def test_tampered_stylesheet_stays_inside_the_fonts_folder(self):
        from st.common import ShowtimeError
        out = TMP / "gf-tamper"
        dest = out / "project" / "fonts"
        evil = ("/* latin */\n@font-face { font-family: 'Space Grotesk'; font-style: x/../../../../escape/pwn; font-weight: 400;\n"
                "  src: url(%s) format('x/../y'); }\n")

        def css(body):
            def get_bytes(url, headers=None, **kw):
                self.calls.append(("css", url, ""))
                return (evil % body).encode(), "text/css"
            return get_bytes
        # a font file from another host is refused before anything is fetched or written
        self.net.get_bytes = css("http://198.51.100.7/anything.woff2")
        with self.assertRaises(ShowtimeError) as cm:
            self.fonts.from_css("http://fonts.googleapis.com/css2?family=Space+Grotesk", dest)
        self.assertIn("outside https://fonts.gstatic.com/", str(cm.exception))
        self.assertEqual(self.calls[-1][1], "https://fonts.googleapis.com/css2?family=Space+Grotesk", "the link is fetched over https")
        self.assertFalse([c for c in self.calls if c[0] == "file"])
        self.assertFalse(list(out.rglob("*.woff2")))
        # Google's host over http: fetched over https, the name made of clean pieces, the extension from the bytes
        self.net.get_bytes = css("http://fonts.gstatic.com/s/x.woff2")
        m = self.fonts.from_css("http://fonts.googleapis.com/css2?family=Space+Grotesk", dest)
        self.assertEqual([c[1] for c in self.calls if c[0] == "file"], ["https://fonts.gstatic.com/s/x.woff2"])
        written = [p.relative_to(out).as_posix() for p in out.rglob("*.woff2")]
        self.assertEqual(written, ["project/fonts/space-grotesk/space-grotesk-latin-400-x-..-..-..-..-escape-pwn.woff2"])
        self.assertEqual(m["families"][0]["files"][0]["file"], "space-grotesk-latin-400-x-..-..-..-..-escape-pwn.woff2")
        self.assertFalse((out / "escape").exists())


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
        self.assertIn('<canvas id="frames-still" data-st-video="frames">', (out / "index.html").read_text())
        showtime("render", out, "-o", TMP / "pil.mp4")
        q = showtime("qa", TMP / "pil.mp4", "--project", out, "--json", check=False)
        self.assertIn(json.loads(q.stdout)["verdict"], ("PASS", "WARN"), q.stdout[-2000:])
        # every frame is the one drawn for its time, not the one before (or black): the progress bar is
        # 520 * t / 2 px long (10.8 px a frame) and the box crosses row 180 from frame 0
        bars = video_rows(TMP / "pil.mp4", 306)
        self.assertEqual(len(bars), 48)
        shown = [round(sum(1 for x in range(640) if r[3 * x + 1] > 120 and r[3 * x] < 120) / (520 / 48)) for r in bars]
        self.assertEqual(shown, list(range(48)), "frame k shows the bar of frame shown[k]")
        box = video_rows(TMP / "pil.mp4", 180)[0]
        self.assertGreater(sum(1 for x in range(640) if box[3 * x] > 200 and box[3 * x + 2] < 120), 80, "frame 0 has no box")

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

    def test_claude_design_zip(self):
        import zipfile
        z = TMP / "Design clock (4s, 16 9)-html.zip"
        with zipfile.ZipFile(z, "w") as zf:
            for f in sorted((FIX / "design-dc").iterdir()):
                zf.write(f, f.name)
        before = hashlib.sha256(z.read_bytes()).hexdigest()
        out = TMP / "design-dc"
        env = dict(ENV, SHOWTIME_OFFLINE="1")   # the font download says what to run later
        cp = subprocess.run([sys.executable, str(LAUNCHER), "adopt", str(z), "-o", str(out), "--no-check"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=900)
        self.assertEqual(cp.returncode, 0, cp.stderr[-3000:])
        self.assertEqual(hashlib.sha256(z.read_bytes()).hexdigest(), before)
        rep = json.loads((out / "adopt.json").read_text())
        self.assertEqual(rep["made"], "Claude Design export")
        self.assertIn("Claude Design export", cp.stderr)
        self.assertTrue(rep["contract"].startswith("clock"), rep["contract"])
        self.assertEqual((rep["width"], rep["height"], rep["duration"]), (1920, 1080, 4))
        self.assertEqual(rep["design"]["zoom"], 3)
        self.assertIn("Math.min(t, 4)", rep["sources"]["duration"])
        self.assertEqual(rep["determinism"]["verdict"], "deterministic", rep["determinism"])
        self.assertTrue((out / "src" / "Main.dc.html").is_file())
        self.assertIn("<style data-st-adopt-fit>html{zoom:3}body{width:640px!important;height:360px!important}</style>",
                      (out / "index.html").read_text())
        self.assertIn("fonts_offline",[f["code"] for f in rep["findings"]])
        self.assertIn("--refresh", cp.stderr)
        # the artboard fills the frame: at 2 s the 60 px box is at 3 x (40 + 120 x 2) = 840 px, 180 px wide
        showtime("snap", out, "--at", "2")
        from PIL import Image
        im = Image.open(out / "work" / "snap" / "t0002.000s.png").convert("RGB")
        self.assertEqual(im.size, (1920, 1080))
        red = [x for x in range(0, 1920, 4) if im.getpixel((x, 540))[0] > 200 and im.getpixel((x, 540))[1] < 100]
        self.assertTrue(red and abs(red[0] - 840) <= 4 and abs(red[-1] - 1016) <= 4, (red[:1], red[-1:]))
        showtime("adopt", out, "--refresh", "--no-check")
        rep = json.loads((out / "adopt.json").read_text())
        self.assertEqual((rep["source"], rep["duration"]), (str(z), 4))

    def design_box(self, name, w, h, *extra):
        """The design-dc fixture as a w x h artboard with a green box in its bottom-right corner, adopted
        (offline: fonts skipped) and snapped at 2 s -> (adopt.json, image, the box's corners on screen)."""
        from PIL import Image
        src = TMP / name
        shutil.copytree(FIX / "design-dc", src)
        page = src / "Main.dc.html"
        bw, bh = w // 6, h // 5
        html = page.read_text().replace("width: 640px; height: 360px", "width: %dpx; height: %dpx" % (w, h))
        html = html.replace('"width":640,"height":360', '"width":%d,"height":%d' % (w, h))
        html = html.replace('<div style="position: absolute; left: 40px; top: 40px;',
                            '<div style="position: absolute; right: 0; bottom: 0; width: %dpx; height: %dpx; background: #22c55e"></div>\n'
                            '<div style="position: absolute; left: 40px; top: 40px;' % (bw, bh))
        page.write_text(html)
        out = TMP / (name + "-out")
        cp = subprocess.run([sys.executable, str(LAUNCHER), "adopt", str(src), "-o", str(out), "--no-check", *extra],
                            env=dict(ENV, SHOWTIME_OFFLINE="1"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace", timeout=900)
        self.assertEqual(cp.returncode, 0, cp.stderr[-3000:])
        rep = json.loads((out / "adopt.json").read_text())
        showtime("snap", out, "--at", "2")
        im = Image.open(out / "work" / "snap" / "t0002.000s.png").convert("RGB")
        z, off = rep["design"]["zoom"], rep["design"]["offset"] or {"x": 0, "y": 0}
        x0, y0 = (w - bw + off["x"]) * z, (h - bh + off["y"]) * z
        x1, y1 = (w + off["x"]) * z, (h + off["y"]) * z
        return rep, im, (x0, y0, x1, y1)

    def test_artboard_larger_than_the_frame_is_not_cropped(self):
        # CSS zoom below 1 also shrinks the stage's own W x H body, which used to clip the artboard
        # a 1280x720 design fitted into 1080x1080 (zoom 0.844): the right sixth was cut off
        rep, im, (x0, y0, x1, y1) = self.design_box("design-1280", 1280, 720, "--size", "1080x1080")
        self.assertEqual((rep["width"], rep["height"], rep["design"]["zoom"]), (1080, 1080, 0.844))
        self.assertEqual(im.size, (1080, 1080))
        for xy in ((x0 + 6, y0 + 6), (x1 - 6, y1 - 6)):
            px = im.getpixel(tuple(int(v) for v in xy))
            self.assertTrue(px[1] > 150 and px[0] < 100, "the box near the artboard's right edge is cut off at %s: %s" % (xy, px))
        # a 2560x1440 artboard rendered at 1920x1080 (zoom 0.75) keeps its bottom-right box
        rep, im, (x0, y0, x1, y1) = self.design_box("design-2560", 2560, 1440)
        self.assertEqual((rep["width"], rep["height"], rep["design"]["zoom"]), (1920, 1080, 0.75))
        for xy in ((x0 + 6, y0 + 6), (x1 - 6, y1 - 6)):
            px = im.getpixel(tuple(int(v) for v in xy))
            self.assertTrue(px[1] > 150 and px[0] < 100, "the bottom-right box is cut off at %s: %s" % (xy, px))

    def test_claude_design_css_loop(self):
        cp, out, rep = self.adopt("design-loop")
        self.assertEqual(rep["made"], "Claude Design export")
        # check measures the zoomed artboard in one unit: the text inside a box that overflows it is not "clipped"
        self.assertEqual(rep["check"]["errors"], 0, rep["check"])
        report = json.loads(Path(rep["check"]["report"]).read_text())
        self.assertNotIn("text_clipped", [f.get("code") for f in report.get("findings", [])])
        self.assertEqual((rep["width"], rep["height"], rep["duration"]), (1080, 1920, 4))
        self.assertIn("one loop is 4 s", rep["sources"]["duration"])
        self.assertTrue(rep["loop"]["seamless"], rep["loop"])
        self.assertTrue(rep["loop"]["seam"]["same"], rep["loop"])
        self.assertEqual(rep["loop"]["seam"]["t"], 4)
        self.assertIn("seamless", cp.stderr)
        cp, out, rep = self.adopt("design-loop", "--no-check", "--duration", "3", name="design-loop-3")
        self.assertEqual(rep["duration"], 3)

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

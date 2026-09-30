#!/usr/bin/env python3
"""Small render fixes.

  1  snap stills carry no colour chunks (cICP/cHRM/gAMA/iCCP/sRGB): a browser drew a still decoded
     from a BT.709 video darker than the same frame in <video>. The PNG chunk filter is unit-tested
     on a synthetic PNG (fast); a snap of a tagged video is checked end to end (needs ffmpeg)
  2  `showtime check`: text inside data-st-decor (and its descendants) is UI-mockup detail, never
     short_text; the same text outside decor still is (needs a browser)
  3  chart: a positive yMin is the axis floor (ticks start there, bars grow from it) instead of being
     clamped to zero (needs a browser)
  4  `export html` packs every image of a per-frame sequence (one file per frame, swapped by the page), not
     only the ones its 0.5 s probe happened to land on (needs a browser)
usage: python tests/test_render_fixes.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())


def node_exe():
    return ENV.get("SHOWTIME_NODE") or plat.which("node") or shutil.which("node") or "node"


def showtime(*args, check=True, timeout=600):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                    cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png_chunks(buf: bytes) -> list:
    out, i = [], 8
    while i + 12 <= len(buf):
        n = struct.unpack(">I", buf[i:i + 4])[0]
        out.append(buf[i + 4:i + 8].decode("latin1"))
        i += 12 + n
    return out


def synthetic_png() -> bytes:
    """A 2x2 RGB PNG tagged like an ffmpeg still of a BT.709 video (plus iCCP and sRGB)."""
    raw = b"".join(b"\x00" + bytes([200, 100, 50] * 2) for _ in range(2))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + chunk(b"pHYs", struct.pack(">IIB", 1, 1, 0)) + chunk(b"cICP", bytes([1, 1, 0, 1]))
            + chunk(b"cHRM", b"\x00" * 32) + chunk(b"gAMA", struct.pack(">I", 45455))
            + chunk(b"iCCP", b"x\x00\x00" + zlib.compress(b"profile")) + chunk(b"sRGB", b"\x00")
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG_UNIT = r"""
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const png = await import(pathToFileURL(path.join(process.argv[2], 'scripts', 'lib', 'png.mjs')).href);
const src = fs.readFileSync(process.argv[3]);
const out = png.stripColorChunks(src);
fs.writeFileSync(process.argv[4], out);
const jpg = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]);
console.log(JSON.stringify({ before: png.pngChunks(src), after: png.pngChunks(out), jpgSame: png.stripColorChunks(jpg) === jpg,
  cleanSame: png.stripColorChunks(out) === out }));
"""


class Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="st-renderfix-"))

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)


# ------------------------------------------------------------------ 1. snap colour chunks

class SnapColour(Tmp):
    def test_chunk_filter(self):
        src, dst, f = self.tmp / "in.png", self.tmp / "out.png", self.tmp / "u.mjs"
        src.write_bytes(synthetic_png())
        f.write_text(PNG_UNIT, encoding="utf-8")
        cp = subprocess.run([node_exe(), str(f), str(SKILL), str(src), str(dst)], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", timeout=60)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        r = json.loads(cp.stdout)
        self.assertEqual(r["before"], ["IHDR", "pHYs", "cICP", "cHRM", "gAMA", "iCCP", "sRGB", "IDAT", "IEND"])
        self.assertEqual(r["after"], ["IHDR", "pHYs", "IDAT", "IEND"])
        self.assertTrue(r["jpgSame"])
        self.assertTrue(r["cleanSame"])
        # the kept chunks are intact (CRCs checked by a real decoder when Pillow is there)
        out = dst.read_bytes()
        i = 8
        while i < len(out):
            n = struct.unpack(">I", out[i:i + 4])[0]
            self.assertEqual(struct.unpack(">I", out[i + 8 + n:i + 12 + n])[0], zlib.crc32(out[i + 4:i + 8 + n]) & 0xFFFFFFFF)
            i += 12 + n
        try:
            from PIL import Image  # type: ignore
        except ImportError:
            return
        with Image.open(str(dst)) as im:
            self.assertEqual(im.convert("RGB").getpixel((1, 1)), (200, 100, 50))

    @unittest.skipIf(FAST, "renders a tagged clip with ffmpeg and snaps it")
    def test_snap_of_a_bt709_video_has_no_colour_chunks(self):
        from st import ff
        clip = self.tmp / "clip.mp4"
        ff.run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=1", "-pix_fmt", "yuv420p",
                       "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv",
                       "-c:v", "libx264", str(clip)])
        out = self.tmp / "still.png"
        showtime("snap", clip, "--at", "0.5", "-o", out)
        chunks = png_chunks(out.read_bytes())
        self.assertIn("IDAT", chunks)
        for c in ("cICP", "cHRM", "gAMA", "iCCP", "sRGB"):
            self.assertNotIn(c, chunks)


# ------------------------------------------------------------------ 2. decor is not short_text

DECOR_PAGE = """<!doctype html><html><head><script src="/_st/stage.js"></script>
<style>body{margin:0;background:#f2eee3}.s{position:absolute;inset:0;background:#f2eee3;color:#141414;
font:700 60px sans-serif;padding:60px 80px}</style></head><body>
<section class="s" data-start="0" data-dur="0.4">%s</section>
<section class="s" data-start="0.4" data-dur="3"><p>Hold</p></section>
</body></html>"""
LONG = "A settings panel with many readable words in it"


@unittest.skipIf(FAST, "browser check (skipped with --fast)")
class DecorShortText(Tmp):
    def check(self, name, body):
        proj = self.tmp / name
        proj.mkdir()
        (proj / "index.html").write_text(DECOR_PAGE % body, encoding="utf-8")
        (proj / "showtime.json").write_text(json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 3.4}), encoding="utf-8")
        cp = showtime("check", proj, "--json", "--no-determinism", "--no-history", check=False)
        rep = json.loads(cp.stdout)
        return [f for f in rep["findings"] if f["code"] == "short_text"]

    def test_decor_and_its_descendants_are_exempt(self):
        self.assertEqual(self.check("decor", '<div data-st-decor><div><p>%s</p></div></div>' % LONG), [])
        self.assertEqual(self.check("decor-self", '<p data-st-decor>%s</p>' % LONG), [])

    def test_the_same_text_outside_decor_is_short_text(self):
        self.assertTrue(self.check("plain", '<div><p>%s</p></div>' % LONG))


# ------------------------------------------------------------------ 3. chart yMin

CHART_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<script src="/_st/stage.js"></script><script>ST.config({"width": 1280, "height": 720, "fps": 30, "duration": 4});</script>
<link rel="stylesheet" href="/_st/themes/editorial.css">
<script type="module" src="/_st/components/index.js"></script>
<style>.chart{position:absolute;inset:60px 80px 80px}</style></head>
<body><div class="stage"><section class="scene" data-start="0" data-dur="4">
<div class="chart" id="ch" data-st="chart" data-type="@TYPE@" data-at="0.1" data-options='@OPTS@'></div>
</section></div></body></html>"""

CHART_PROBE = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const skill = process.argv[2], dir = process.argv[3];
const imp = (p) => import(pathToFileURL(path.join(skill, 'scripts', p)).href);
const { startServer } = await imp('server.mjs');
const { openBrowser, openStage } = await imp('lib/stagehost.mjs');
const server = await startServer({ root: dir, port: 0 });
const b = await openBrowser({ gpu: 'auto' });
const R = {};
try {
  for (const name of ['bar', 'line', 'auto']) {
    const s = await openStage(b.browser, { url: server.url, page: name + '.html', config: {} });
    await s.seek(3.9);
    R[name] = await s.page.evaluate(() => {
      const shown = (e) => getComputedStyle(e).display !== 'none';
      const ticks = [...document.querySelectorAll('#ch .st-chart-tick')].filter(shown).map((e) => e.textContent);
      const plot = [...document.querySelectorAll('#ch .st-chart-grid line')].filter(shown).map((l) => l.getBoundingClientRect().bottom);
      const bars = [...document.querySelectorAll('#ch .st-chart-bar')].map((r) => { const q = r.getBoundingClientRect(); return [q.top, q.bottom]; });
      const path = document.querySelector('#ch path.st-chart-line, #ch .st-chart-line path, #ch path[class*=line]');
      const pb = path ? path.getBoundingClientRect() : null;
      return { ticks, gridBottom: Math.max(...plot), bars, line: pb ? [pb.top, pb.bottom] : null };
    });
    await s.close();
  }
} finally { await b.browser.close(); await server.close(); }
console.log(JSON.stringify(R));
"""


@unittest.skipIf(FAST, "needs a browser")
class ChartYMin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-chartymin-"))
        proj = cls.tmp / "proj"
        proj.mkdir()
        (proj / "showtime.json").write_text(json.dumps({"width": 1280, "height": 720, "fps": 30, "duration": 4}), encoding="utf-8")
        data = [{"label": str(2019 + i), "value": v} for i, v in enumerate([92, 94, 95, 97, 99])]
        for name, typ, opts in (("bar", "bar", {"yMin": 90, "yMax": 100, "count": False, "data": data}),
                                ("line", "line", {"yMin": 90, "yMax": 100, "data": data}),
                                ("auto", "bar", {"count": False, "data": data})):
            (proj / (name + ".html")).write_text(CHART_PAGE.replace("@TYPE@", typ).replace("@OPTS@", json.dumps(opts)), encoding="utf-8")
        probe = cls.tmp / "probe.mjs"
        probe.write_text(CHART_PROBE, encoding="utf-8")
        cp = subprocess.run([node_exe(), str(probe), str(SKILL), str(proj)], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        if cp.returncode != 0:
            raise AssertionError("probe failed:\n%s\n%s" % (cp.stdout[-3000:], cp.stderr[-3000:]))
        cls.R = json.loads(cp.stdout.strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def nums(self, ticks):
        return [float(t.replace("−", "-")) for t in ticks]

    def test_positive_ymin_is_the_axis_floor(self):
        r = self.R["bar"]
        ticks = self.nums(r["ticks"])
        self.assertTrue(ticks, r)
        self.assertGreaterEqual(min(ticks), 90, r["ticks"])
        self.assertLessEqual(max(ticks), 100, r["ticks"])
        # bars grow from the floor: they end at the plot's bottom, and the 92 bar is far shorter than the 99 one
        heights = [b - t for t, b in r["bars"]]
        for t, b in r["bars"]:
            self.assertAlmostEqual(b, r["gridBottom"], delta=2.5)
        self.assertLess(heights[0] * 2.5, heights[-1], heights)

    def test_line_uses_the_floor(self):
        r = self.R["line"]
        self.assertGreaterEqual(min(self.nums(r["ticks"])), 90, r["ticks"])

    def test_without_ymin_the_axis_starts_at_zero(self):
        self.assertEqual(min(self.nums(self.R["auto"]["ticks"])), 0, self.R["auto"]["ticks"])



@unittest.skipIf(FAST, "needs a browser")
class ExportSequenceTests(unittest.TestCase):
    def test_every_frame_of_an_image_sequence_is_packed(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-export-seq-"))
        try:
            proj = tmp / "seq"
            (proj / "seq").mkdir(parents=True)
            png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)) + \
                chunk(b"IDAT", zlib.compress(b"\x00\x80")) + chunk(b"IEND", b"")
            for i in range(30):                                   # frames 30-59: one image per frame from 1.0 s
                (proj / "seq" / ("f_%04d.png" % (30 + i))).write_bytes(png)
            (proj / "showtime.json").write_text(json.dumps({"title": "Seq", "width": 320, "height": 180, "fps": 30,
                                                            "duration": 3}), encoding="utf-8")
            (proj / "index.html").write_text(
                '<!doctype html><html><head><script src="/_st/stage.js"></script></head><body style="margin:0">'
                '<img id="im" width="320" height="180"><script>'
                "ST.onSeek(function (t, frame) { var f = frame; var im = document.getElementById('im');"
                "  if (f >= 30 && f < 60) { var s = 'seq/f_' + String(f).padStart(4, '0') + '.png';"
                "    if (im.getAttribute('src') !== s) im.setAttribute('src', s); } });"
                "</script></body></html>", encoding="utf-8")
            out = tmp / "out" / "seq.html"
            rep = json.loads(showtime("export", "html", proj, "-o", out, "--json", "-q", "--folder").stdout)
            html = "".join(p.read_text(encoding="utf-8", errors="replace") for p in Path(rep["output"]).parent.rglob("*")
                           if p.is_file() and p.suffix in (".html", ".js"))
            names = {n for n in ("f_%04d.png" % (30 + i) for i in range(30))
                     if n in html or any(q.name == n for q in Path(rep["output"]).parent.rglob(n))}
            self.assertEqual(len(names), 30, sorted(set("f_%04d.png" % (30 + i) for i in range(30)) - names))
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)

if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv)

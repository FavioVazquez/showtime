#!/usr/bin/env python3
"""`showtime check`: rules found on real jobs (0.4.1).

  * WebGPU: a page that asks for WebGPU passed check silently and rendered a flat ground without a GPU
    (showtime never needs one). With no WebGL / 2D fallback that draws, `webgpu` is an error naming the
    page line; with a 2D fallback that draws when WebGPU is gone, a warning. Pages without WebGPU: nothing.
  * low_contrast at the settled opacity: a text sampled while it was still fading in was failed at that
    opacity. It is judged again at the frame of its visible window where it is most opaque, and passes;
    a text that is faint at its most opaque frame still fails there, and the message says where it was
    first sampled.
  * caption_zone: a label drawn where caption-karaoke's cards sit, while a caption shows, is a warning
    naming the element, the time and the overlap. Full-frame backgrounds, elements under 10 % opacity,
    text above the zone and elements marked data-st-caption-ok are not.
  * cancelled image loads: a page whose seeks swap an image's src before the last one arrived has its loads
    cancelled (net::ERR_ABORTED) while check scrubs. They are counted (cancelled_loads), never a finding,
    and a real failed request next to them is still a request_failed warning.

Needs a browser (each check runs with --no-timeline and a few samples). usage: python tests/test_check_rules.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

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
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

ENV = build_env(showtime_home())


def showtime(*args, timeout=300):
    return subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                          errors="replace", timeout=timeout)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def check(proj, *extra):
    cp = showtime("check", proj, "--json", "--no-determinism", "--no-timeline", "--no-history", *extra)
    try:
        return json.loads(cp.stdout)
    except ValueError:
        raise AssertionError("check gave no JSON (rc=%d):\n%s\n%s" % (cp.returncode, cp.stdout[-2000:], cp.stderr[-2000:]))


HEAD = ('<!doctype html><html><head><meta charset="utf-8"><script src="/_st/stage.js"></script>'
        '<link rel="stylesheet" href="/_lib/@fontsource-variable/inter/index.css">')

# WebGPU: clear the canvas to a colour that follows t; the fallback (when FALLBACK) draws the same in 2D
GPU_JS = """const cv = document.getElementById('gfx');
let dev = null, ctx = null, g2 = null;
ST.waitFor((async () => {
  if (navigator.gpu) {
    const ad = await navigator.gpu.requestAdapter();
    if (ad) {
      dev = await ad.requestDevice();
      ctx = cv.getContext('webgpu');
      ctx.configure({ device: dev, format: navigator.gpu.getPreferredCanvasFormat(), alphaMode: 'opaque' });
      return;
    }
  }
  if (FALLBACK) g2 = cv.getContext('2d');
})(), 'gfx');
ST.onSeek((t) => {
  if (dev) {
    const enc = dev.createCommandEncoder();
    const pass = enc.beginRenderPass({ colorAttachments: [{ view: ctx.getCurrentTexture().createView(),
      clearValue: { r: 0.2 + t / 8, g: 0.4, b: 0.7, a: 1 }, loadOp: 'clear', storeOp: 'store' }] });
    pass.end();
    dev.queue.submit([enc.finish()]);
  } else if (g2) {
    g2.fillStyle = 'rgb(' + Math.round(51 + t * 32) + ', 102, 178)';
    g2.fillRect(0, 0, cv.width, cv.height);
    g2.fillStyle = '#f4f4f4';
    g2.fillRect(40, 40, 120, 80);
  }
});
"""


class CheckRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-check-rules-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    # ------------------------------------------------------------------ WebGPU
    def gpu_project(self, name, fallback):
        proj = self.tmp / name
        write(proj / "showtime.json", json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 2, "background": "#101010"}))
        write(proj / "gfx.js", "const FALLBACK = %s;\n%s" % ("true" if fallback else "false", GPU_JS))
        write(proj / "index.html", HEAD + "<style>body{margin:0;background:#101010}canvas{position:absolute;inset:0;width:100%;height:100%}</style>"
              "</head><body><canvas id=\"gfx\" width=\"640\" height=\"360\"></canvas><script src=\"gfx.js\"></script></body></html>")
        return proj

    def test_webgpu_without_fallback_is_an_error(self):
        rep = check(self.gpu_project("gpu-only", False), "--samples", "2")
        gpu = [f for f in rep["findings"] if f["code"] == "webgpu"]
        self.assertEqual(len(gpu), 1, rep["findings"])
        self.assertEqual(gpu[0]["severity"], "error", gpu)
        self.assertIn("gfx.js:", gpu[0]["message"])              # the page line that asks
        self.assertIn("no WebGL or 2D fallback", gpu[0]["message"])
        self.assertIn("shaderLayer", gpu[0]["fix"])
        self.assertFalse(rep["ok"])
        self.assertIsNone(rep["webgpu"]["fallback"], rep["webgpu"])

    def test_webgpu_with_a_2d_fallback_is_a_warning(self):
        rep = check(self.gpu_project("gpu-fallback", True), "--samples", "2")
        gpu = [f for f in rep["findings"] if f["code"] == "webgpu"]
        self.assertEqual([f["severity"] for f in gpu], ["warning"], rep["findings"])
        self.assertIn("falls back to 2D", gpu[0]["message"])
        self.assertIn("#gfx", gpu[0]["message"])
        self.assertEqual(rep["webgpu"]["fallback"]["ctx"], "2D")

    # ------------------------------------------------------------------ contrast at the settled opacity
    def test_contrast_is_judged_at_the_settled_opacity(self):
        proj = self.tmp / "fades"
        write(proj / "showtime.json", json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 4}))
        # #fade and #pale fade in over 1.0-3.0 s, hold to 3.5 s and are gone by 3.8 s: the only samples
        # (--samples 1: 2.0 s, and the last frame) catch them at 50 % opacity
        write(proj / "index.html", HEAD + "<style>body{margin:0;background:#fff;font-family:'Inter Variable'}"
              ".s{position:absolute;inset:0;background:#fff}p{position:absolute;left:40px;margin:0;font-size:28px;font-weight:600}"
              "#fade{top:40px;color:#333}#pale{top:120px;color:#bbb}#faint{top:200px;color:#333;opacity:0.35}</style></head><body>"
              "<section class=\"s\" data-start=\"0\" data-dur=\"4\"><p id=\"fade\">Fades in slowly</p><p id=\"pale\">Pale even when settled</p>"
              "<p id=\"faint\">Always faint</p></section><script>"
              "const io = (t) => Math.min(1, Math.max(0, (t - 1) / 2)) * (1 - Math.min(1, Math.max(0, (t - 3.5) / 0.3)));"
              "ST.onSeek((t) => { for (const id of ['fade', 'pale']) document.getElementById(id).style.opacity = io(t).toFixed(3); });"
              "</script></body></html>")
        rep = check(proj, "--samples", "1")
        low = [f for f in rep["findings"] if f["code"] == "low_contrast"]
        msgs = " | ".join(f["message"] for f in low)
        # sampled mid-fade, settled at full opacity: passes (judged at its most opaque frame, 3.0-3.5 s)
        self.assertNotIn("Fades in slowly", msgs)
        fade = next(c for c in rep["contrast"] if c["text"] == "Fades in slowly")
        self.assertGreaterEqual(fade["ratio"], 4.5, fade)
        self.assertGreaterEqual(fade["t"], 2.95, fade)
        self.assertLessEqual(fade["t"], 3.5, fade)
        self.assertEqual(fade["sampled"], 2.0, fade)
        # pale colour: still an error, at its most opaque frame, saying where it was first sampled
        pale = [f for f in low if "Pale even when settled" in f["message"]]
        self.assertEqual(len(pale), 1, low)
        self.assertEqual(pale[0]["severity"], "error")
        self.assertIn("most opaque frame", pale[0]["message"])
        self.assertIn("first sampled at 0:02.00 at 50% opacity", pale[0]["message"])
        self.assertGreaterEqual(pale[0]["t"], 2.95)
        # faint at every frame: fails at its own opacity
        faint = [f for f in low if "Always faint" in f["message"]]
        self.assertEqual([f["severity"] for f in faint], ["error"], low)
        self.assertIn("35% opacity", faint[0]["message"])
        self.assertNotIn("webgpu", [f["code"] for f in rep["findings"]])   # no WebGPU here: no finding

    # ------------------------------------------------------------------ caption zone
    def test_caption_zone(self):
        proj = self.tmp / "capzone"
        write(proj / "showtime.json", json.dumps({"width": 1280, "height": 720, "fps": 30, "duration": 4}))
        write(proj / "words.json", json.dumps([{"text": w, "start": 0.5 + i * 0.5, "end": 0.95 + i * 0.5}
                                               for i, w in enumerate("Plants turn sunlight into sugar".split())]))
        write(proj / "index.html", HEAD + "<script type=\"module\" src=\"/_st/components/index.js\"></script>"
              "<style>body{margin:0;background:#f6f0e4;font-family:'Inter Variable'}.s{position:absolute;inset:0}"
              ".ground{position:absolute;inset:0;background:#efe6d4}p{position:absolute;margin:0;font-size:26px;color:#1c1a17}"
              ".head{left:80px;top:60px;font-size:48px}.src{left:420px;top:600px}.ok{left:760px;top:600px}.ghost{left:560px;top:610px;opacity:0.05}"
              "svg{position:absolute;left:600px;top:420px;width:200px;height:220px}</style></head><body>"
              "<section class=\"s\" data-start=\"0\" data-dur=\"4\"><div class=\"ground\"></div><p class=\"head\">Photosynthesis</p>"
              "<p class=\"src\">Source: lab notes</p><p class=\"ok\" data-st-caption-ok>Intended</p><p class=\"ghost\">Ghost label</p>"
              "<svg id=\"chart\" viewBox=\"0 0 200 220\"><rect x=\"20\" y=\"20\" width=\"40\" height=\"60\" fill=\"#c85a2a\"/>"
              "<rect x=\"120\" y=\"150\" width=\"40\" height=\"70\" fill=\"#2b8a8f\"/></svg>"
              "<div data-st=\"caption-karaoke\" data-src=\"words.json\" data-style=\"boxed-pill\"></div></section></body></html>")
        rep = check(proj, "--samples", "3")
        cz = [f for f in rep["findings"] if f["code"] == "caption_zone"]
        self.assertTrue(rep.get("caption_zone"), rep.keys())
        z = rep["caption_zone"]
        self.assertGreater(z["y"], 720 * 0.6)                      # the bottom band of a wide frame
        names = " | ".join(f["message"] for f in cz)
        src = [f for f in cz if '"Source: lab notes"' in f["message"]]
        self.assertEqual(len(src), 1, cz)
        self.assertEqual(src[0]["severity"], "warning")
        self.assertIn("p.src", src[0]["message"])
        self.assertIn("while a caption shows", src[0]["message"])
        self.assertGreater(src[0]["overlap"]["h"], 4)
        self.assertIn("data-st-caption-ok", src[0]["fix"])
        self.assertTrue([f for f in cz if "svg#chart" in f["message"] or "#chart" in f["message"]], cz)   # the chart's lower bar
        for quiet in ("Intended", "Ghost label", "Photosynthesis", "ground"):
            self.assertNotIn(quiet, names)

    # ------------------------------------------------------------------ image loads check's scrubbing cancels
    def test_cancelled_image_loads_are_not_failures(self):
        proj = self.tmp / "swap"
        for i in range(3):
            png(proj / ("img%d.png" % i), 600, 400)
        write(proj / "showtime.json", json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 3, "background": "#101010"}))
        # each seek points the picture at one image, then at another before the first arrives (its load is
        # cancelled: net::ERR_ABORTED), and waits for the second; a request to a closed local port really fails
        write(proj / "index.html", HEAD + "<style>body{margin:0;background:#101010}img{position:absolute;inset:0;width:100%;"
              "height:100%;object-fit:cover}#gone{width:10px;height:10px}</style></head><body>"
              "<img id=\"pic\" src=\"img0.png\" alt=\"picture\"><img id=\"gone\" src=\"http://127.0.0.1:9/gone.png\" alt=\"\">"
              "<script>const pic = document.getElementById('pic');\n"
              "ST.onSeek(async (t, f) => { pic.src = 'img' + ((f + 1) % 3) + '.png?early=' + f; await Promise.resolve(); "
              "await Promise.resolve(); pic.src = 'img' + (f % 3) + '.png?f=' + f; await pic.decode(); });</script></body></html>")
        rep = check(proj, "--samples", "6")
        self.assertGreater(rep.get("cancelled_loads", 0), 0, "the fixture should cancel loads while check scrubs")
        self.assertGreaterEqual(rep["pace"]["factor"], 1, rep.get("pace"))       # the waits' scale is in the report
        failed = [f for f in rep["findings"] if f["code"] in ("request_failed", "missing_file", "console_error")]
        self.assertEqual([f for f in failed if "img" in f["message"]], [], failed)
        # a real failure is still reported next to the cancelled loads
        self.assertTrue([f for f in failed if f["code"] == "request_failed" and "gone.png" in f["message"]], rep["findings"])


def png(path, w, h):
    """A noisy RGB PNG (large enough that a load is still running when the next src replaces it)."""
    import struct
    import zlib
    rows = b"".join(b"\x00" + os.urandom(w * 3) for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows, 1)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    unittest.main(argv=[a for a in sys.argv if a != "--fast"])

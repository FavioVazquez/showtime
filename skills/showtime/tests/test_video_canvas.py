#!/usr/bin/env python3
"""The canvas route: in a render every <video> is drawn on a canvas that takes its place.

On a busy or slow machine Chrome can put a paused video's seeked frame on screen after the capture
(the frame before, or nothing for the first one). Render mode draws each video's frame on a canvas
that gets the video's computed style every frame (runtime/stage.js, syncVideoCanvases).

One page with five videos: an absolutely placed clip with a rotation, a scale, rounded corners,
opacity and a filter; a flex item with a border, object-fit and a CSS keyframe rotation next to a
text label; a transparent (alpha) clip inside a static wrapper with a gradient behind it; a clip larger
than 4K; a video that is a timed clip itself (data-start/data-dur). The same page
with data-st-video="native" on every video is the reference.

- every video is drawn on a canvas in the render (and none in the native page); data-st-video="native"
  keeps a plain video
- frames match the native reference at several times (within the tiny colour difference between
  Chrome's video and canvas paths)
- `check`'s layout snapshot (text boxes) is the same, and each video reports its canvas's box
- frame-coded clips show the frame their time names at every frame of a walk, also with the CPU
  throttled 6x (the slow machine that used to get the frame before), with no duplicate frames
- a clip larger than 4K is drawn at its full size; an alpha clip keeps its transparency

Skipped with --fast (needs a browser). usage: python tests/test_video_canvas.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
W, H, FPS, N = 320, 180, 30, 90     # the frame-coded clip: 3 s

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<script src="/_st/stage.js"></script>
<script>ST.config({"width": 640, "height": 360, "fps": 30, "duration": 3});</script>
<style>
body { background: #1d2733; font: 600 18px/1.2 sans-serif; color: #fff; }
.scene { position: absolute; inset: 0; }
#a { position: absolute; left: 40px; top: 34px; width: 280px; height: 170px; object-fit: cover; border-radius: 18px;
     transform: rotate(-4deg) scale(1.05); opacity: 0.9; filter: contrast(1.15); }
.row { position: absolute; left: 340px; top: 40px; width: 270px; display: flex; gap: 10px; align-items: center; }
#b { flex: 1; min-width: 0; height: 120px; object-fit: contain; border: 3px solid #fc3; background: #402; animation: tilt 3s linear both; }
@keyframes tilt { from { transform: rotate(0deg); } to { transform: rotate(12deg); } }
.wrap { position: absolute; left: 380px; top: 200px; padding: 10px; background: linear-gradient(90deg, #c33, #36c); line-height: 0; }
.label { position: absolute; left: 60px; top: 280px; }
#big { position: absolute; right: 8px; bottom: 8px; width: 160px; }
#d { position: absolute; left: 250px; top: 300px; width: 96px; }
</style></head><body><div class="scene" data-start="0" data-dur="3">
<video id="a" src="media/code.webm" muted playsinline__NATIVE__></video>
<div class="row"><video id="b" src="media/code.webm" data-offset="0.5" muted playsinline__NATIVE__></video><span class="tag">B-roll</span></div>
<div class="wrap"><video id="c" src="media/alpha.webm" muted playsinline__NATIVE__></video></div>
<video id="big" src="media/big.webm" muted playsinline__NATIVE__></video>
<video id="d" src="media/code.webm" data-start="1" data-dur="1" muted playsinline__NATIVE__></video>
<div class="label">Over the footage</div>
</div></body></html>
"""

TIMES = [0, 0.5, 1.0333, 1.5, 2.2, 2.9333]

PROBE = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const skill = process.argv[2], dir = process.argv[3];
const times = JSON.parse(process.argv[4]);
const imp = (p) => import(pathToFileURL(path.join(skill, 'scripts', p)).href);
const { startServer } = await imp('server.mjs');
const { openBrowser, openStage, openLab } = await imp('lib/stagehost.mjs');
const { textSnapshot } = await imp('lib/audit.mjs');
const server = await startServer({ root: dir, port: 0 });
const b = await openBrowser({ gpu: 'auto' });
const R = { pages: {} };
// the frame number coded in the clip's bars, read off a screenshot through the page's own canvas
const decodeJs = async (page, png, boxes) => page.evaluate(async ([b64, boxes]) => {
  const bin = atob(b64), u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  const bmp = await createImageBitmap(new Blob([u]));
  const c = new OffscreenCanvas(bmp.width, bmp.height), g = c.getContext('2d');
  g.drawImage(bmp, 0, 0);
  return boxes.map((bx) => {
    let n = 0;
    for (let k = 0; k < 7; k++) {
      const x = Math.round(bx.x + bx.w * (25 + k * 38) / 320), y = Math.round(bx.y + bx.h * 0.5);
      const d = g.getImageData(x, y, 1, 1).data;
      if ((d[0] + d[1] + d[2]) / 3 > 125) n |= 1 << k;
    }
    return n;
  });
}, [png.toString('base64'), boxes]);
const layout = (s) => s.page.evaluate(() => {
  const out = {};
  for (const id of ['a', 'b', 'c', 'big', 'd']) {
    const v = document.getElementById(id), c = v.__stCanvas;
    const r = v.getBoundingClientRect();
    out[id] = { rect: [r.x, r.y, r.width, r.height].map((x) => Math.round(x * 100) / 100), canvas: !!(c && c.isConnected),
      hidden: v.hasAttribute('data-st-hidden'), buf: c ? [c.width, c.height] : null, next: !!c && v.nextSibling === c,
      canvasRect: c ? (() => { const q = c.getBoundingClientRect(); return [q.x, q.y, q.width, q.height].map((x) => Math.round(x * 100) / 100); })() : null };
  }
  return out;
});
const text = async (s) => {
  const snap = await s.page.evaluate(textSnapshot, { width: 640, height: 360, full: true, labelGapEm: 0.5 });
  return JSON.stringify((snap.leaves || []).map((l) => [l.text, l.box]));
};
try {
  const lab = await openLab(b.browser, server.url);
  const shots = {};
  for (const name of ['native', 'canvas']) {
    const s = await openStage(b.browser, { url: server.url, page: name + '.html', config: {} });
    const P = R.pages[name] = { layout: {}, text: {} };
    for (const t of times) {
      await s.seek(t);
      if (name === 'native') {
        // the reference: give Chrome's own video path all the time it needs
        await s.page.waitForTimeout(400);
        await s.page.evaluate(() => window.ST._paint());
        await s.page.waitForTimeout(200);
      }
      const png = await s.shot({ format: 'png' });
      shots[name + t] = png;
      // ST_VC_DUMP=<folder>: keep the frames, to look at a difference
      if (process.env.ST_VC_DUMP) (await import('node:fs')).writeFileSync(path.join(process.env.ST_VC_DUMP, name + '-' + t + '.png'), png);
      P.layout[t] = await layout(s);
      // the alpha clip (#c at 390,210): inside the square, and beside it where the gradient shows through
      P.alpha = P.alpha || {};
      P.alpha[t] = (await lab.boxColors(png, [{ x: 10 + t * 20 + 390 + 20, y: 235, w: 10, h: 10 }, { x: 392, y: 278, w: 6, h: 6 },
        { x: 390 + 1 + t * 20, y: 245, w: 3, h: 10 }])).map((b) => b && b.median);
      P.text[t] = await text(s);
    }
    await s.close();
  }
  R.diffs = {};
  for (const t of times) R.diffs[t] = await lab.diff(shots['native' + t], shots['canvas' + t], 8);
  // a frame-coded walk over every frame, at full speed and with the CPU throttled
  for (const [name, rate] of [['canvas', 1], ['canvas', 6], ['native', 6]]) {
    const s = await openStage(b.browser, { url: server.url, page: 'walk-' + name + '.html', config: {} });
    if (rate > 1) await s.cdp.send('Emulation.setCPUThrottlingRate', { rate });
    const got = [];
    for (let f = 0; f < 60; f++) {
      await s.seek(f / 30);
      const png = await s.shot({ format: 'png' });
      got.push((await decodeJs(s.page, png, [{ x: 0, y: 0, w: 320, h: 180 }, { x: 320, y: 0, w: 320, h: 180 }])));
    }
    R['walk_' + name + '_' + rate] = got;
    await s.close();
  }
  await lab.close();
} finally { await b.browser.close(); await server.close(); }
console.log(JSON.stringify(R));
"""

WALK = """<!doctype html><html><head><meta charset="utf-8"><script src="/_st/stage.js"></script>
<script>ST.config({"width": 640, "height": 180, "fps": 30, "duration": 2});</script>
<style>body{background:#000} video{width:320px;height:180px;display:block;float:left}</style></head><body>
<div data-start="0" data-dur="2"><video src="media/code.webm" muted playsinline__NATIVE__></video>
<video src="media/code.webm" data-offset="0.5" muted playsinline__NATIVE__></video></div></body></html>
"""


def node_exe():
    return ENV.get("SHOWTIME_NODE") or plat.which("node") or shutil.which("node") or "node"


def ffmpeg(args, stdin=None):
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-y"] + [str(a) for a in args], input=stdin,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=600)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")


def coded_frames():
    """Frame k shows k in binary: 7 bars, white for a 1 bit, on dark grey."""
    out = bytearray()
    for k in range(N):
        f = bytearray([40]) * (W * H)
        for b in range(7):
            if (k >> b) & 1:
                x0 = 10 + b * 38
                for y in range(40, 140):
                    f[y * W + x0:y * W + x0 + 30] = bytes([230]) * 30
        out += f
    return bytes(out)


@unittest.skipIf(FAST, "needs a browser")
class VideoCanvas(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-vcanvas-"))
        proj = cls.tmp / "proj"
        media = proj / "media"
        media.mkdir(parents=True)
        vp9 = ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8", "-crf", "18", "-b:v", "0", "-g", "60"]
        ffmpeg(["-f", "rawvideo", "-pix_fmt", "gray", "-s", "%dx%d" % (W, H), "-r", FPS, "-i", "-"] + vp9 +
               ["-pix_fmt", "yuv420p", media / "code.webm"], stdin=coded_frames())
        # a yellow square moving over a transparent ground
        ffmpeg(["-f", "lavfi", "-i", "color=c=yellow:s=120x80:r=30:d=3,format=yuva420p,geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':"
                "a='if(between(X,10+T*20,60+T*20)*between(Y,15,65),255,0)'"] + vp9 +
               ["-auto-alt-ref", "0", "-pix_fmt", "yuva420p", media / "alpha.webm"])
        # larger than 4K: drawn on a canvas of its own size
        ffmpeg(["-i", media / "code.webm", "-vf", "scale=4480:2520:flags=neighbor", "-frames:v", "8"] + vp9 +
               ["-pix_fmt", "yuv420p", media / "big.webm"])
        (proj / "canvas.html").write_text(PAGE.replace("__NATIVE__", ""), encoding="utf-8")
        (proj / "native.html").write_text(PAGE.replace("__NATIVE__", ' data-st-video="native"'), encoding="utf-8")
        (proj / "walk-canvas.html").write_text(WALK.replace("__NATIVE__", ""), encoding="utf-8")
        (proj / "walk-native.html").write_text(WALK.replace("__NATIVE__", ' data-st-video="native"'), encoding="utf-8")
        probe = cls.tmp / "probe.mjs"
        probe.write_text(PROBE, encoding="utf-8")
        cp = subprocess.run([node_exe(), str(probe), str(SKILL), str(proj), json.dumps(TIMES)], env=ENV,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=900)
        if cp.returncode != 0:
            raise AssertionError("probe failed:\n%s\n%s" % (cp.stdout[-3000:], cp.stderr[-3000:]))
        cls.R = json.loads(cp.stdout.strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_every_video_is_drawn_on_a_canvas(self):
        canvas, native = self.R["pages"]["canvas"]["layout"], self.R["pages"]["native"]["layout"]
        for t in canvas:
            for vid in ("a", "b", "c", "big", "d"):
                if vid == "d" and not 1 <= float(t) < 2:
                    # a clip that is not on: no box, nothing drawn
                    self.assertEqual(canvas[t][vid]["rect"], [0, 0, 0, 0])
                    continue
                with self.subTest(t=t, video=vid):
                    self.assertTrue(canvas[t][vid]["canvas"] and canvas[t][vid]["hidden"] and canvas[t][vid]["next"], canvas[t][vid])
                    self.assertFalse(native[t][vid]["canvas"] or native[t][vid]["hidden"], "data-st-video=native keeps a plain video")
        self.assertEqual(canvas["0"]["big"]["buf"], [4480, 2520], "a clip larger than 4K is drawn at its full size")
        self.assertEqual(canvas["0"]["c"]["buf"], [120, 80])

    def test_same_layout(self):
        """Each video reports its canvas's box, which is where the plain video was; check's text boxes are unchanged."""
        canvas, native = self.R["pages"]["canvas"], self.R["pages"]["native"]
        for t in canvas["layout"]:
            for vid in ("a", "b", "c", "big", "d"):
                with self.subTest(t=t, video=vid):
                    got, want = canvas["layout"][t][vid], native["layout"][t][vid]
                    if got["canvas"]:       # (a clip that has not been on yet has no canvas)
                        self.assertEqual(got["rect"], got["canvasRect"])
                    for g, w in zip(got["rect"], want["rect"]):
                        self.assertAlmostEqual(g, w, delta=0.02, msg="%s at %s: %s vs native %s" % (vid, t, got["rect"], want["rect"]))
            self.assertEqual(canvas["text"][t], native["text"][t], "check's text layout differs at %s" % t)

    def test_frames_match_the_native_reference(self):
        for t, d in self.R["diffs"].items():
            with self.subTest(t=t):
                # identical, or resampling differences on the edges of the scaled and rotated clip: Chrome
                # filters a video's planes and a canvas's pixels a little differently (a whole bar off, a late
                # frame, would be thousands of solid pixels)
                self.assertTrue(d["same"] or (d["meanDelta"] < 1.5 and d["solidPct"] < 0.1), "t=%s: %s" % (t, d))

    def test_transparent_video(self):
        """The alpha clip's square is yellow and the gradient shows around it, as in the plain video; the
        square's place in the frame before leaves no trace."""
        for t in ("0.5", "1.5", "2.2"):
            with self.subTest(t=t):
                (sq, ground, was), (sq_n, ground_n, was_n) = self.R["pages"]["canvas"]["alpha"][t], self.R["pages"]["native"]["alpha"][t]
                self.assertTrue(sq[0] > 200 and sq[1] > 200 and sq[2] < 80, "square %s" % sq)
                self.assertTrue(ground[0] > 150 and ground[2] < 120, "the gradient behind the clip %s" % ground)
                # just left of the square: where it was in the frame captured before
                self.assertTrue(was[2] > 40 and was[1] < 150, "the square's old place %s" % was)
                for a, b in ((sq, sq_n), (ground, ground_n), (was, was_n)):
                    self.assertLessEqual(max(abs(x - y) for x, y in zip(a, b)), 6)

    def test_every_frame_at_its_time(self):
        """In order, at full speed and with the CPU throttled 6x: frame f of the walk shows frame f (and
        f + 15 for the clip offset by 0.5 s); no frame repeats the one before."""
        want = [[f, f + 15] for f in range(60)]
        for key in ("walk_canvas_1", "walk_canvas_6"):
            with self.subTest(walk=key):
                self.assertEqual(self.R[key], want)
        # the plain video path under the same throttle, for the report (Chrome may or may not skip here)
        late = sum(1 for g, w in zip(self.R["walk_native_6"], want) if g != w)
        print("\n  plain <video> path, CPU throttled 6x: %d of 60 frames late or wrong" % late)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + [a for a in sys.argv[1:] if a != "--fast"])

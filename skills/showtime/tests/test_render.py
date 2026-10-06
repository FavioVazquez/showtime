#!/usr/bin/env python3
"""render-core smoke tests: stage runtime, server, render, check, snap, preview CLI.

Real runs: renders templates/dom cut to 4 s at 1280x720 (with its generated
music + sfx mix at -14 LUFS), checks the full template, and renders a canvas page with an
offline WebAudio score, then verifies the files with ffprobe (size, fps, frame
count, duration, BT.709 tags), audio/video sync, loudness, alpha output, the
determinism probe and that `check` catches planted defects. Prints measured
capture throughput.

Stdlib only. usage: python tests/test_render.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import array
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
RESULTS = {}


def showtime(*args, check=True, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def probe_streams(path):
    cp = subprocess.run([ff.ffprobe_path(), "-v", "error", "-count_packets", "-show_streams", "-show_format",
                         "-of", "json", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding="utf-8", timeout=120)
    assert cp.returncode == 0, cp.stderr
    return json.loads(cp.stdout)


def ffmpeg_bytes(args):
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin"] + [str(a) for a in args],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")
    return cp.stdout


def png_size(path):
    with open(path, "rb") as fh:
        head = fh.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", head[16:24])


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


CANVAS_HTML = """<!doctype html><html><head><script src="/_st/stage.js"></script></head>
<body><canvas id="c" width="1280" height="720"></canvas>
<script>
const g = document.getElementById('c').getContext('2d');
const R = ST.rand(42);
const dots = Array.from({length: 250}, () => [R(), R(), R.range(2, 9), R()]);
ST.onSeek((t) => {
  g.fillStyle = '#10141c'; g.fillRect(0, 0, 1280, 720);
  for (const [x, y, r, h] of dots) {
    g.fillStyle = 'hsl(' + (h * 360) + ', 80%, 60%)';
    g.beginPath(); g.arc((x * 1280 + t * 90 * (h + .3)) % 1280, y * 720 + ST.noise(t + h * 10, 1) * 40, r, 0, 7); g.fill();
  }
  // white box on the first frame of every half second; the score beeps at the same times
  const k = Math.round(t * 30);
  g.fillStyle = (k % 15 === 0) ? '#ffffff' : '#223344'; g.fillRect(40, 40, 120, 120);
});
ST.score = async (ctx, dest) => {
  for (let t = 0.5; t < 4; t += 0.5) {
    const o = ctx.createOscillator(), a = ctx.createGain();
    o.frequency.value = 880; a.gain.setValueAtTime(0.0001, 0); a.gain.setValueAtTime(0.4, t);
    a.gain.exponentialRampToValueAtTime(0.001, t + 0.1);
    o.connect(a).connect(dest); o.start(t); o.stop(t + 0.12);
  }
};
</script></body></html>
"""

BAD_HTML = """<!doctype html><html><head><script src="/_st/stage.js"></script><style>
body{background:#222;font-family:Helvetica,Arial,sans-serif;color:#eee}
.low{position:absolute;left:80px;top:80px;font-size:30px;color:#333}
.a{position:absolute;left:300px;top:300px;font-size:60px}.b{position:absolute;left:340px;top:310px;font-size:60px}
.box{position:absolute;left:0;top:500px;width:120px;height:120px;background:#e44}
</style></head><body>
<div class="low">Low contrast label</div><div class="a">Overlapping</div><div class="b">Text here</div>
<div class="box" id="box"></div><img src="missing.png"><img src="https://example.com/remote.png">
<script>let x = 0; setInterval(() => { x = (x + 9) % 1100; document.getElementById('box').style.left = x + 'px'; }, 20);</script>
</body></html>
"""


FILM_HOLE_HTML = """<!doctype html><html><head><link rel="stylesheet" href="/_lib/@fontsource-variable/inter/index.css">
<script src="/_st/stage.js"></script><script src="/_st/film.js"></script></head><body><script>
Film.start({ look: 'paper', fonts: ['650 1em "Inter Variable"'], scenes: function (T, g, F) {
  F.sequence(T, [{ t0: 0, t1: 2, draw: function () {
    F.text('Hello there', F.W / 2, F.H / 2, { size: 120, weight: 650, align: 'center', alpha: F.seg(T, 0, 0.5) }); } }]);
} });
</script></body></html>
"""


IMPORTS_JS = r"""import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const root = process.argv[2];
const files = [...fs.readdirSync(path.join(root, 'scripts')).map((f) => path.join(root, 'scripts', f)),
  ...fs.readdirSync(path.join(root, 'scripts', 'lib')).map((f) => path.join(root, 'scripts', 'lib', f))].filter((f) => f.endsWith('.mjs'));
const bad = [];
let n = 0;
for (const f of files) {
  const src = fs.readFileSync(f, 'utf8').replace(/^\s*\/\/.*$/gm, '');
  for (const m of src.matchAll(/import\s*\{([^}]*)\}\s*from\s*['"](\.{1,2}\/[^'"]+)['"]/g)) {
    const target = path.resolve(path.dirname(f), m[2]);
    const mod = await import(pathToFileURL(target).href);
    for (const raw of m[1].split(',')) {
      const name = raw.trim().split(/\s+as\s+/)[0].trim();
      if (!name) continue;
      n++;
      if (!(name in mod)) bad.push(`${path.relative(root, f)} imports ${name} from ${m[2]}, which does not export it`);
    }
  }
}
console.log(JSON.stringify({ checked: n, bad }));
"""

class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-render-"))
        cls.out = cls.tmp / "out"
        cls.out.mkdir()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    # ------------------------------------------------------------------ CLI
    def test_00_script_imports_resolve(self):
        """Every named import between scripts/*.mjs and scripts/lib/*.mjs exists (score.mjs, check.mjs,
        preview.mjs ... share render-core's helpers; a renamed export must fail here, not at run time)."""
        js = self.tmp / "imports.mjs"
        js.write_text(IMPORTS_JS, encoding="utf-8")
        node = shutil.which("node") or "node"
        cp = subprocess.run([node, str(js), str(SKILL)], capture_output=True, text=True, timeout=120)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        rep = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertGreater(rep["checked"], 50)
        self.assertEqual(rep["bad"], [])

    def test_01_help(self):
        for cmd in ("render", "check", "snap", "preview", "server"):
            cp = showtime(cmd, "--help")
            self.assertIn("usage:", cp.stdout, cmd)
            self.assertIn("examples:", cp.stdout, cmd)
        cp = showtime("render", "--no-such-flag", check=False)
        self.assertEqual(cp.returncode, 2)
        cp = showtime("render", str(self.tmp / "does-not-exist"), check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("fix:", cp.stderr)

    # ------------------------------------------------------ template render
    def test_02_template_render(self):
        # a 4 s cut of the template (its later scenes fall after the end: fine for a render test; the
        # check test below uses the full-length template, which must pass with no warnings)
        proj = self.tmp / "dom4"
        showtime("new", "dom", proj, "--width", 1280, "--height", 720, "--duration", 4)
        t0 = time.time()
        cp = showtime("render", proj, "--out-dir", self.out, "--poster", 2, "--json")
        wall = time.time() - t0
        rep = json.loads(cp.stdout)
        mp4 = Path(rep["output"])
        self.assertTrue(mp4.is_file())
        self.assertEqual(mp4.name, "final.mp4")
        self.assertTrue((mp4.parent / "poster.jpg").is_file())
        # baked only when the poster frame looks like the opening (else frame 0 would flash)
        self.assertEqual(rep["poster"]["baked"], rep["poster"].get("opening_diff", 0) <= 12, rep["poster"])
        info = probe_streams(mp4)
        v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
        self.assertEqual((v["width"], v["height"]), (1280, 720))
        self.assertEqual(v["codec_name"], "h264")
        self.assertEqual(v["pix_fmt"], "yuv420p")
        self.assertEqual(v["r_frame_rate"], "30/1")
        self.assertEqual(int(v["nb_read_packets"]), 120)
        self.assertAlmostEqual(float(info["format"]["duration"]), 4.0, delta=0.02)
        for k in ("color_space", "color_primaries", "color_transfer"):
            self.assertEqual(v.get(k), "bt709", k)
        self.assertEqual(v.get("color_range"), "tv")
        # the template ships audio/mix.json (composed bed + synth sfx): sound out of the box at -14 LUFS
        a = [s for s in info["streams"] if s["codec_type"] == "audio"]
        self.assertTrue(a, "the dom template rendered without sound")
        self.assertIn("mix", rep["audio"]["sources"])
        self.assertAlmostEqual(rep["audio"]["lufs"], -14.0, delta=1.0)
        self.assertLessEqual(rep["audio"]["true_peak"], -0.9)
        # after success the work folder keeps only what later commands read: render.json (beside the video
        # here), logs, the AAC master, the mix report and the narration stem; frames, the silent video copy and
        # the WAV stems are gone
        work = mp4.parent / "work"
        self.assertFalse((work / "frames").exists())
        self.assertFalse((work / "video.mp4").exists(), "the silent video copy is removed")
        self.assertTrue((work / "logs" / "render.log").is_file())
        self.assertTrue((work / "audio" / "master.m4a").is_file())
        self.assertTrue((work / "audio" / "mix.report.json").is_file())
        wavs = [p.name for p in (work / "audio").glob("*.wav") if not p.name.endswith(".voice.wav")]
        self.assertEqual(wavs, [], "WAV stems are removed")
        self.assertIn("removed", (work / "logs" / "render.log").read_text(encoding="utf-8"))
        RESULTS["template_1280x720"] = {"frames": 120, "capture_fps": rep["fps_capture"], "overall_fps": rep["fps_overall"],
                                        "workers": rep["workers"], "wall_s": round(wall, 1)}

    def test_03_check_template_passes(self):
        proj = self.tmp / "dom"
        if not proj.exists():
            showtime("new", "dom", proj, "--width", 1280, "--height", 720)
        args = ["check", proj, "--json"] + (["--no-timeline"] if FAST else [])
        cp = showtime(*args, check=False)
        rep = json.loads(cp.stdout)
        errors = [f for f in rep["findings"] if f["severity"] == "error"]
        self.assertEqual(errors, [], "check found errors in the template: %s" % errors)
        warns = [f for f in rep["findings"] if f["severity"] == "warning"]
        self.assertEqual(warns, [], "check found warnings in the template: %s" % warns)
        self.assertEqual(cp.returncode, 0)
        det = rep["determinism"]
        # identical, or anti-aliasing noise on edges only (no solid changed regions)
        self.assertTrue(all(d["same"] or (d.get("solid", 0) <= 150 and d["changedPct"] <= 2) for d in det["diffs"]), det)
        self.assertFalse(det["unstable"])
        self.assertTrue(Path(rep["sheet"]).is_file())
        self.assertTrue(any(v["custom"] for v in rep["fonts"]["used"].values()), rep["fonts"])

    def test_04_check_catches_defects(self):
        proj = self.tmp / "bad"
        write(proj / "showtime.json", json.dumps({"width": 1280, "height": 720, "fps": 30, "duration": 3}))
        write(proj / "index.html", BAD_HTML)
        cp = showtime("check", proj, "--json", "--no-timeline", check=False)
        self.assertEqual(cp.returncode, 1, cp.stderr)
        codes = {f["code"] for f in json.loads(cp.stdout)["findings"]}
        for want in ("network", "missing_file", "low_contrast", "text_overlap", "font_not_embedded", "timers"):
            self.assertIn(want, codes)
        self.assertTrue(codes & {"nondeterministic", "unstable_frame"}, codes)

    # ------------------------------------------------ canvas + score + sync
    def test_05_canvas_score_sync(self):
        proj = self.tmp / "canvas"
        write(proj / "showtime.json", json.dumps({"title": "Canvas", "width": 1280, "height": 720, "fps": 30, "duration": 4}))
        write(proj / "index.html", CANVAS_HTML)
        cp = showtime("render", proj, "--out-dir", self.out, "--poster", "none", "--json")
        rep = json.loads(cp.stdout)
        mp4 = Path(rep["output"])
        info = probe_streams(mp4)
        a = [s for s in info["streams"] if s["codec_type"] == "audio"]
        v = [s for s in info["streams"] if s["codec_type"] == "video"][0]
        self.assertTrue(a, "no audio stream")
        self.assertEqual(a[0]["codec_name"], "aac")
        self.assertEqual(int(a[0]["sample_rate"]), 48000)
        self.assertAlmostEqual(float(a[0]["duration"]), 4.0, delta=0.03)
        self.assertEqual(int(v["nb_read_packets"]), 120)
        self.assertEqual(rep["audio"]["sources"], ["score"])
        # video: which frames have the white box
        lum = ffmpeg_bytes(["-i", mp4, "-vf", "crop=100:100:50:50,scale=1:1,format=gray", "-f", "rawvideo", "-"])
        flashes = [i for i, b in enumerate(lum) if b > 200]
        self.assertEqual(flashes, list(range(0, 120, 15)))
        # audio: beep onsets must land on the flash frames (0.5 s grid) within 5 ms
        pcm = array.array("h")
        pcm.frombytes(ffmpeg_bytes(["-i", mp4, "-vn", "-ac", "1", "-ar", "48000", "-f", "s16le", "-"]))
        if sys.byteorder == "big":
            pcm.byteswap()
        peak = max(abs(x) for x in pcm)
        thr = peak * 0.1
        errs = []
        for k in range(1, 8):
            want = int(k * 0.5 * 48000)
            lo = max(0, want - 2400)
            onset = next((i for i in range(lo, want + 2400) if abs(pcm[i]) > thr), None)
            self.assertIsNotNone(onset, "no beep near %.1fs" % (k * 0.5))
            errs.append((onset - want) / 48.0)
        self.assertLess(max(abs(e) for e in errs), 5.0, "A/V offsets in ms: %s" % errs)
        RESULTS["canvas_1280x720"] = {"capture_fps": rep["fps_capture"], "av_offset_ms_max": round(max(abs(e) for e in errs), 2),
                                      "lufs": rep["audio"]["lufs"]}

    def test_06_mix_loudness_and_range(self):
        proj = self.tmp / "mixproj"
        (proj / "audio").mkdir(parents=True, exist_ok=True)
        subprocess.run([ff.ffmpeg_path(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=4:sample_rate=44100",
                        "-af", "volume=-20dB", str(proj / "audio" / "tone.wav")], check=True, timeout=60)
        write(proj / "showtime.json", json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 3,
                                                  "audio": [{"file": "audio/tone.wav", "fade_out": 0.2}]}))
        write(proj / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script></head>"
              "<body><div style=\"position:absolute;left:0;top:0;height:100px;width:calc(var(--st-p) * 640px);background:#6af\"></div></body></html>")
        cp = showtime("render", proj, "--out-dir", self.out, "--json", "--from", 1, "--to", 2.5, "--preview")
        rep = json.loads(cp.stdout)
        self.assertEqual(rep["frames"], 45)
        self.assertEqual(Path(rep["output"]).name, "span-1-2.5.mp4", "a section render is a span clip, never preview/final")
        info = probe_streams(rep["output"])
        a = [s for s in info["streams"] if s["codec_type"] == "audio"][0]
        self.assertAlmostEqual(float(a["duration"]), 1.5, delta=0.03)
        lufs = rep["audio"]["lufs"]
        self.assertIsNotNone(lufs)
        self.assertAlmostEqual(lufs, -14.0, delta=0.6)
        self.assertLessEqual(rep["audio"]["true_peak"], -0.8)

    # ---------------------------------------------------------------- alpha
    def test_07_alpha_webm(self):
        if FAST:
            self.skipTest("--fast")
        if not ff.has_encoder("libvpx-vp9"):
            self.skipTest("this ffmpeg has no libvpx-vp9")
        proj = self.tmp / "overlay"
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 30, "duration": 0.5}))
        write(proj / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script></head><body>"
              "<div style=\"position:absolute;left:100px;top:60px;width:120px;height:60px;background:#fff\"></div></body></html>")
        out = self.out / "overlay.webm"
        showtime("render", proj, "--alpha", "webm", "-o", out)
        corner = ffmpeg_bytes(["-c:v", "libvpx-vp9", "-i", out, "-vf", "select=eq(n\\,5),alphaextract,crop=4:4:0:0,scale=1:1",
                               "-f", "rawvideo", "-pix_fmt", "gray", "-"])
        center = ffmpeg_bytes(["-c:v", "libvpx-vp9", "-i", out, "-vf", "select=eq(n\\,5),alphaextract,crop=4:4:150:80,scale=1:1",
                               "-f", "rawvideo", "-pix_fmt", "gray", "-"])
        self.assertLess(corner[0], 10)
        self.assertGreater(center[0], 245)
        self.assertEqual(probe_streams(out)["streams"][0].get("color_space"), "bt709")

    def test_07b_alpha_prores_colours_match_their_bt709_tags(self):
        """ProRes 4444 is tagged BT.709, so it must be converted with that matrix: an editor decoding it as
        tagged gets the page's colours back (swscale's default BT.601 turned #B3121F into #C1221D)."""
        if FAST:
            self.skipTest("--fast")
        if not ff.has_encoder("prores_ks"):
            self.skipTest("this ffmpeg has no prores_ks")
        proj = self.tmp / "overlay-709"
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 30, "duration": 0.2}))
        write(proj / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script></head><body>"
              "<div style=\"position:absolute;left:100px;top:60px;width:120px;height:60px;background:#B3121F\"></div></body></html>")
        out = self.out / "overlay-709.mov"
        showtime("render", proj, "--alpha", "prores", "-o", out)
        st = probe_streams(out)["streams"][0]
        self.assertEqual((st.get("color_space"), st.get("color_primaries"), st.get("color_transfer")), ("bt709",) * 3)
        px = ffmpeg_bytes(["-i", out, "-vf", "select=eq(n\\,2),crop=8:8:156:86,"
                           "scale=1:1:in_color_matrix=bt709:in_range=tv:out_range=pc,format=rgb24",
                           "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
        for got, want in zip(px[:3], (0xB3, 0x12, 0x1F)):
            self.assertLessEqual(abs(got - want), 3, "decoded %s, want #B3121F" % px[:3].hex())

    def test_07c_alpha_animation_is_small_and_transparent(self):
        """--alpha animation: QuickTime Animation (lossless RGBA .mov) keeps the alpha and is a fraction of
        the ProRes 4444 size for flat graphics (20.5: 1 s stingers were 27-32 MB as ProRes)."""
        if FAST:
            self.skipTest("--fast")
        if not (ff.has_encoder("qtrle") and ff.has_encoder("prores_ks")):
            self.skipTest("this ffmpeg has no qtrle/prores_ks")
        proj = self.tmp / "overlay-anim"
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 30, "duration": 0.3}))
        write(proj / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script></head><body>"
              "<div style=\"position:absolute;left:100px;top:60px;width:120px;height:60px;background:#E9B949\"></div></body></html>")
        anim, pr = self.out / "overlay-anim.mov", self.out / "overlay-anim-prores.mov"
        showtime("render", proj, "--alpha", "animation", "-o", anim)
        showtime("render", proj, "--alpha", "prores", "-o", pr)
        st = probe_streams(anim)["streams"][0]
        self.assertEqual((st.get("codec_name"), st.get("pix_fmt")), ("qtrle", "argb"))
        corner = ffmpeg_bytes(["-i", anim, "-vf", "select=eq(n\\,2),alphaextract,crop=4:4:0:0,scale=1:1",
                               "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"])
        center = ffmpeg_bytes(["-i", anim, "-vf", "select=eq(n\\,2),alphaextract,crop=4:4:150:80,scale=1:1",
                               "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"])
        self.assertLess(corner[0], 10)
        self.assertGreater(center[0], 245)
        self.assertLess(anim.stat().st_size, pr.stat().st_size / 3)

    # ---------------------------------------------------------------- snap
    def test_08_snap(self):
        proj = self.tmp / "canvas"
        if not proj.exists():
            self.skipTest("needs test_05")
        cp = showtime("snap", proj, "--at", "0.5,1.25", "--sheet", "--json")
        rep = json.loads(cp.stdout)
        self.assertEqual(len(rep["stills"]), 2)
        for s in rep["stills"]:
            self.assertEqual(png_size(s["file"]), (1280, 720))
        self.assertTrue(Path(rep["sheet"]).is_file())

    def test_08b_snap_video_and_compare(self):
        """snap takes a rendered video too: nearest frame, files named by the requested time, a note for
        duplicates, and --compare writes a before|after sheet."""
        d = self.tmp / "snapvid"
        d.mkdir(exist_ok=True)
        for name, src in (("new.mp4", "testsrc2"), ("old.mp4", "testsrc")):
            ffmpeg_bytes(["-y", "-f", "lavfi", "-i", "%s=s=320x180:r=30:d=2" % src, "-pix_fmt", "yuv420p", str(d / name)])
        rep = json.loads(showtime("snap", d / "new.mp4", "--at", "0.5,0.51,1.2", "--compare", d / "old.mp4",
                                  "-o", d / "out", "--json").stdout)
        self.assertEqual(rep["kind"], "video")
        self.assertEqual([Path(x["file"]).name for x in rep["stills"]], ["t0000.500s.png", "t0000.510s.png", "t0001.200s.png"])
        self.assertEqual([x["frame"] for x in rep["stills"]], [15, 15, 36])
        self.assertTrue(any("same frame" in n for n in rep["notes"]), rep["notes"])
        self.assertEqual(png_size(rep["stills"][0]["file"]), (320, 180))
        self.assertTrue(Path(rep["compare"]).is_file())
        # nearest frame, not floor: 1.966 s at 30 fps is frame 59 (floor gave 58)
        rep = json.loads(showtime("snap", d / "new.mp4", "--at", "1.966", "-o", d / "out2", "--json").stdout)
        self.assertEqual(rep["stills"][0]["frame"], 59)

    def test_08d_snap_project_lands_on_the_frame(self):
        """A project still shows the frame it names: --at 0.7333 is frame 22 at 30 fps, and its time rounded to
        six decimals (0.733333) sits a hair before the boundary, which the stage used to floor to frame 21."""
        proj = self.tmp / "snapedge"
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 30, "duration": 1}))
        write(proj / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script></head>"
              "<body style=\"margin:0\"><script>ST.onSeek(function (t) { document.body.style.background = "
              "t >= 0.7333 ? '#ffffff' : '#000000'; });</script></body></html>")
        rep = json.loads(showtime("snap", proj, "--at", "0.7,0.7333", "-o", self.tmp / "snapedge-out", "--json").stdout)
        self.assertEqual([x["frame"] for x in rep["stills"]], [21, 22])
        lum = [ffmpeg_bytes(["-i", x["file"], "-vf", "crop=8:8:156:86,scale=1:1", "-f", "rawvideo", "-pix_fmt", "gray", "-"])[0]
               for x in rep["stills"]]
        self.assertLess(lum[0], 30, "frame 21 should be black")
        self.assertGreater(lum[1], 225, "frame 22 should be white (the snap showed frame 21)")

    def test_08e_snap_video_frames_exact(self):
        """A <video> in a project shows the frame its time names: 24 random stills of a frame-coded clip (GOP 60,
        B-frames) decode to the expected frame numbers, and so does a looping clip that a handler adds while
        seeking (its length is known only once it loads: the loop point is computed after that)."""
        if FAST:
            self.skipTest("--fast (needs a browser)")
        import random
        W, H, FPS, N = 320, 180, 30, 150
        proj = self.tmp / "vcoded"
        (proj / "media").mkdir(parents=True)

        def frame(k):
            f = bytearray([40]) * (W * H)
            for b in range(8):
                if (k >> b) & 1:
                    for y in range(50, 130):
                        x0 = 10 + b * 38
                        f[y * W + x0:y * W + x0 + 30] = bytes([230]) * 30
            return bytes(f)
        p = subprocess.Popen([ff.ffmpeg_path(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "%dx%d" % (W, H),
                              "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "16", "-g", "60", "-bf", "2", "-pix_fmt", "yuv420p",
                              str(proj / "media" / "coded.mp4")], stdin=subprocess.PIPE)
        for k in range(N):
            p.stdin.write(frame(k))
        p.stdin.close()
        self.assertEqual(p.wait(), 0)
        write(proj / "showtime.json", json.dumps({"width": W, "height": H, "fps": FPS, "duration": 8}))
        write(proj / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script><style>body{margin:0;background:#000}"
              "video{position:absolute;left:0;top:0;width:320px;height:180px}</style></head><body>"
              "<video id=\"a\" src=\"media/coded.mp4\" muted playsinline data-start=\"0\" data-dur=\"5\"></video>"
              "<div id=\"host\"></div><script>ST.onSeek(function (t) { var h = document.getElementById('host');"
              " if (t >= 5 && !h.firstChild) { var v = document.createElement('video'); v.src = 'media/coded.mp4'; v.muted = true;"
              " v.loop = true; h.appendChild(v); } });</script></body></html>")

        def decode(png):
            raw = ffmpeg_bytes(["-i", str(png), "-vf", "scale=%d:%d,format=gray" % (W, H), "-f", "rawvideo", "-pix_fmt", "gray", "-"])
            return sum(1 << b for b in range(8) if raw[90 * W + 25 + b * 38] > 125)
        rng = random.Random(5)
        frames = sorted(rng.sample(range(0, N - 1), 24))
        times = [k / FPS for k in frames] + [7.0]            # 7.0 s: the looping clip the handler adds (5 s long)
        rep = json.loads(showtime("snap", proj, "--at", ",".join("%.6f" % t for t in times), "-o", self.tmp / "vcoded-out",
                                  "--json", timeout=600).stdout)
        got = [decode(x["file"]) for x in rep["stills"]]
        # the added video is a child of an unscheduled element: its local time is the film time, looped at 5 s
        self.assertEqual(got, frames + [round((7.0 % 5.0) * FPS)])

    def test_08c_snap_big_sheet_from_master(self):
        """A long --every sheet from a full-HD video goes through the per-frame thumbnail path (frames are
        shrunk one by one before the sheet is laid out) and finishes. Smoke test: the crash it guards against
        (a hundred detailed 1080p frames sent to the lab page in one message) needs minutes of decoding to
        reproduce, so it was verified by hand on a real 1080p master, not here."""
        d = self.tmp / "snapbig"
        d.mkdir(exist_ok=True)
        ffmpeg_bytes(["-y", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30:d=40", "-pix_fmt", "yuv420p", "-crf", "12", str(d / "big.mp4")])
        rep = json.loads(showtime("snap", d / "big.mp4", "--every", "0.5", "--thumb", "480", "-o", d / "out", "--json", timeout=400).stdout)
        self.assertTrue(Path(rep["sheet"]).is_file())
        self.assertGreater(Path(rep["sheet"]).stat().st_size, 100000)

    # --------------------------------------------------------------- server
    def test_09_server(self):
        proj = self.tmp / "srv"
        write(proj / "index.html", "<!doctype html><html><head><title>x</title></head><body>hi</body></html>")
        (proj / "blob.bin").write_bytes(bytes(range(256)) * 4)
        node = shutil.which("node", path=ENV.get("PATH"))
        p = subprocess.Popen([node, str(SKILL / "scripts" / "server.mjs"), str(proj), "--port", "0", "--json"], env=ENV,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        try:
            line = p.stdout.readline()
            info = json.loads(line)
            url, key = info["url"], info["key"]
            self.assertIn("k=" + key, info["preview"])     # the printed links open the server

            def get(path, headers=None, keyed=True):
                h = dict(headers or {})
                if keyed:
                    h["X-Showtime-Key"] = key
                req = urllib.request.Request(url + path, headers=h)
                try:
                    with urllib.request.urlopen(req, timeout=10) as r:
                        return r.status, dict(r.headers), r.read()
                except urllib.error.HTTPError as e:
                    return e.code, dict(e.headers), e.read()

            st, _, body = get("/index.html", keyed=False)
            self.assertEqual(st, 403)                      # the session key guards every path
            self.assertIn(b"session key", body)
            st, h, body = get("/blob.bin", {"Range": "bytes=10-19"})
            self.assertEqual(st, 206)
            self.assertEqual(body, bytes(range(10, 20)))
            self.assertEqual(h.get("Content-Range"), "bytes 10-19/1024")
            st, h, body = get("/index.html")
            self.assertEqual(st, 200)
            self.assertIn(b"/_st/stage.js", body)          # injected into pages that lack it
            self.assertTrue(h.get("Content-Type", "").startswith("text/html"))
            st, _, body = get("/_st/stage.js")
            self.assertEqual(st, 200)
            st, h, _ = get("/_lib/animejs/package.json")
            self.assertEqual(st, 200)
            self.assertTrue(h.get("Content-Type", "").startswith("application/json"))
            st, _, _ = get("/%2e%2e/%2e%2e/etc/passwd")
            self.assertIn(st, (403, 404))
            st, _, _ = get("/_st/preview?page=/index.html")
            self.assertEqual(st, 200)
            st, _, _ = get("/favicon.ico")
            self.assertEqual(st, 204)                      # no 404 noise in check / preview
            # emoji images for stage.js: an installed Noto SVG, or a 404 that says how to install it
            st, h, body = get("/_st/emoji/1f680.svg")
            if st == 200:
                self.assertTrue(h.get("Content-Type", "").startswith("image/svg"))
            else:
                self.assertEqual(st, 404)
                self.assertIn(b"showtime assets emoji", body)
            st, _, _ = get("/_st/emoji/..%2f..%2fsecret.svg")
            self.assertEqual(st, 404)
        finally:
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
            for fh in (p.stdout, p.stderr):
                if fh:
                    fh.close()

    # ------------------------------------------------ retimed template (S1)
    def test_10_retimed_template_fills_duration(self):
        """`new dom --duration 20` scales scenes, poster and mix: check finds no dead air, and the render's
        picture, poster and music all run to 20 s."""
        proj = self.tmp / "dom20"
        showtime("new", "dom", proj, "--size", "640x360", "--duration", 20)
        cfg = json.loads((proj / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["duration"], 20)
        # the poster is the hook frame (claim + product teaser, before the camera move); a longer hero keeps
        # the offset from its start (the hero now runs 0-9.067 s), so it stays inside the hook
        self.assertGreater(cfg["poster"], 1.0)
        self.assertLess(cfg["poster"], 2.3)
        mix = json.loads((proj / "audio" / "mix.json").read_text(encoding="utf-8"))
        secs = mix["tracks"][0]["compose"]["sections"]
        self.assertTrue(secs.endswith("16:outro"), secs)           # the outro starts with the retimed close scene
        self.assertEqual(max(t.get("at", 0) for t in mix["tracks"]), 17.45)   # the logo sting keeps its offset
        args = ["check", proj, "--json", "--no-determinism", "--samples", "3"]
        cp = showtime(*args, check=False)
        rep = json.loads(cp.stdout)
        bad = [f for f in rep["findings"] if f["severity"] == "error" or f["code"] in ("dead_air", "timeline_gap", "short_text")]
        self.assertEqual(bad, [], bad)
        self.assertEqual(rep.get("timeline_holes", []), [])
        clips = rep["info"]["clips"]
        self.assertGreaterEqual(clips, 4)
        if FAST:
            return
        cp = showtime("render", proj, "--out-dir", self.out, "--json", timeout=600)
        r = json.loads(cp.stdout)
        self.assertAlmostEqual(r["poster"]["time"], round(cfg["poster"] * 30) / 30, places=3)
        info = probe_streams(r["output"])
        self.assertAlmostEqual(float(info["format"]["duration"]), 20.0, delta=0.05)
        a = [s for s in info["streams"] if s["codec_type"] == "audio"][0]
        self.assertAlmostEqual(float(a["duration"]), 20.0, delta=0.05)
        # the music is still playing in the last scene (the bed follows the 20 s length, not the old 15 s)
        pcm = ffmpeg_bytes(["-ss", "17", "-t", "2", "-i", r["output"], "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"])
        smp = array.array("h", pcm)
        rms = (sum(x * x for x in smp) / max(1, len(smp))) ** 0.5
        self.assertGreater(rms, 300, "the soundtrack is silent at 17-19 s")

    def test_11_check_errors_on_dead_air(self):
        """A timeline that ends before showtime.json's duration is an error, not a warning."""
        proj = self.tmp / "hole"
        write(proj / "showtime.json", json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 6}))
        write(proj / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script>"
              "<style>body{background:#123}.s{position:absolute;inset:0;display:grid;place-items:center;color:#fff;font:600 40px sans-serif}"
              ".bar{position:absolute;left:0;bottom:0;height:20px;background:#fc3;width:calc(var(--p) * 100%)}</style></head><body>"
              "<section class=\"s\" id=\"a\" data-start=\"0\" data-dur=\"1.5\"><div class=\"bar\"></div></section>"
              "<section class=\"s\" id=\"b\" data-start=\"3.5\" data-dur=\"1\"><div class=\"bar\"></div></section>"
              "</body></html>")
        cp = showtime("check", proj, "--json", "--no-determinism", "--samples", "3", check=False)
        self.assertEqual(cp.returncode, 1, cp.stdout[-2000:])
        rep = json.loads(cp.stdout)
        errs = [f for f in rep["findings"] if f["severity"] == "error" and f["code"] == "dead_air"]
        self.assertEqual(len(errs), 2, rep["findings"])            # the gap 1.5-3.5 and the end 4.5-6
        holes = rep["timeline_holes"]
        self.assertEqual([h["at_end"] for h in holes], [False, True])
        self.assertAlmostEqual(holes[0]["from"], 1.5, delta=0.11)
        self.assertAlmostEqual(holes[1]["to"], 6.0, delta=0.01)
        self.assertIn("showtime retime", errs[-1]["fix"])
        # without the dense timeline the clip table still points at the holes (as warnings)
        cp = showtime("check", proj, "--json", "--no-determinism", "--no-timeline", "--samples", "3", check=False)
        codes = [f["code"] for f in json.loads(cp.stdout)["findings"]]
        self.assertEqual(codes.count("timeline_gap"), 2, codes)
        # canvas film whose scenes stop at 2 s of a 4 s video: only the paper backdrop is left
        film = self.tmp / "filmhole"
        write(film / "showtime.json", json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 4}))
        write(film / "index.html", FILM_HOLE_HTML)
        cp = showtime("check", film, "--json", "--no-determinism", "--samples", "3", check=False)
        rep = json.loads(cp.stdout)
        self.assertEqual(cp.returncode, 1, rep["findings"])
        self.assertEqual([(h["from"], h["to"], h["at_end"]) for h in rep["timeline_holes"]], [(2.0, 4.0, True)])

    # ------------------------------------------------ round 3: check agrees with qa, badges, transitions
    def test_12_check_still_hold_matches_qa(self):
        """A 3 s still hold inside a scene is a warning by default (qa's 2.5 s rule, not the old 4 s);
        a short still ending is only a final_hold note."""
        th = json.loads((SKILL / "runtime" / "thresholds.json").read_text(encoding="utf-8"))
        self.assertEqual(th["still_hold_s"], 2.5)
        page = ("<!doctype html><html><head><script src=\"/_st/stage.js\"></script>"
                "<style>body{background:#123}.s{position:absolute;inset:0}"
                ".bar{position:absolute;left:0;top:0;height:120px;background:#fc3;"
                "width:calc(clamp(0, (var(--t) - %s) / %s, 1) * 100%%)}</style></head><body>"
                "<section class=\"s\" id=\"a\" data-start=\"0\" data-dur=\"%s\"><div class=\"bar\"></div></section></body></html>")
        hold = self.tmp / "hold"
        write(hold / "showtime.json", json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 6}))
        write(hold / "index.html", page % ("3.5", "1.5", "6"))          # still 0-3.5 s, moves 3.5-5, still to 6
        rep = json.loads(showtime("check", hold, "--json", "--no-determinism", "--samples", "2", check=False).stdout)
        dead = [f for f in rep["findings"] if f["code"] == "dead_air"]
        self.assertEqual(len(dead), 1, rep["findings"])
        self.assertEqual(dead[0]["severity"], "warning")
        self.assertAlmostEqual(dead[0]["seconds"], 3.5, delta=0.3)
        self.assertIn("qa flags still holds of 2.5s", dead[0]["message"])
        end = self.tmp / "endhold"
        write(end / "showtime.json", json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 5}))
        write(end / "index.html", page % ("0", "2", "5"))               # moves 0-2 s, then a 3 s end card hold
        rep = json.loads(showtime("check", end, "--json", "--no-determinism", "--samples", "2", check=False).stdout)
        codes = [(f["code"], f["severity"]) for f in rep["findings"]]
        self.assertIn(("final_hold", "info"), codes)
        self.assertNotIn(("dead_air", "warning"), codes)
        cp = showtime("check", end, "--no-determinism", "--samples", "2", "--dead-air", "5", "--verbose", check=False)
        self.assertIn("no still holds of 5s or more", cp.stdout)
        # a few small characters typed over a still screen is still a hold (qa's freezedetect agrees)
        typing = self.tmp / "typinghold"
        write(typing / "showtime.json", json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 4}))
        write(typing / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script>"
              "<style>body{margin:0;background:#f4efe6;font:12px monospace;color:#222}"
              "#t{position:absolute;left:40px;top:300px}</style></head><body><div id=t></div>"
              "<script>ST.onSeek((t) => { document.getElementById('t').textContent = 'note: ' + 'abcdefgh'.slice(0, Math.floor(t * 2)); });</script>"
              "</body></html>")
        rep = json.loads(showtime("check", typing, "--json", "--no-determinism", "--samples", "2", check=False).stdout)
        self.assertTrue([f for f in rep["findings"] if f["code"] in ("dead_air", "final_hold")], rep["findings"])

    def test_13_check_badge_over_label_and_small_text_group(self):
        """Text hidden under a badge (an opaque box with its own text) is an overlap warning, and many
        small labels are one grouped note."""
        proj = self.tmp / "badge"
        write(proj / "showtime.json", json.dumps({"width": 1280, "height": 720, "fps": 30, "duration": 2}))
        small = "".join("<span class=\"sm\" style=\"left:%dpx\">tick %d</span>" % (100 + i * 160, i) for i in range(6))
        write(proj / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script>"
              "<link rel=\"stylesheet\" href=\"/_lib/@fontsource-variable/inter/index.css\">"
              "<style>body{background:#f4efe6;font-family:'Inter Variable';color:#111}"
              ".v{position:absolute;left:300px;top:300px;font-size:40px;font-weight:600}"
              ".badge{position:absolute;left:260px;top:280px;padding:24px 40px;background:#111;color:#fff;font-size:32px}"
              ".sm{position:absolute;top:620px;font-size:12px}</style></head><body>"
              "<section data-start=\"0\" data-dur=\"2\"><div class=\"v\">3,120</div><div class=\"badge\">remote cache on</div>" + small +
              "</section></body></html>")
        rep = json.loads(showtime("check", proj, "--json", "--no-determinism", "--no-timeline", "--samples", "2", check=False).stdout)
        ov = [f for f in rep["findings"] if f["code"] == "text_overlap"]
        self.assertTrue(any("hidden under" in f["message"] and "3,120" in f["message"] and f["severity"] == "warning" for f in ov), ov)
        smalls = [f for f in rep["findings"] if f["code"] == "small_text"]
        self.assertEqual(len(smalls), 1, smalls)
        self.assertEqual(smalls[0]["count"], 6)
        self.assertIn("6 small labels", smalls[0]["message"])

    def test_13b_check_canvas_callouts_and_dims(self):
        """Canvas films: a callout card over readable text is a text_overlap ("hidden under the callout"), a
        card pointing off the frame or cut by its edge is callout_off_target, and text under a spotlight's dim
        is not judged for contrast (a dimmed_text note) nor reported as hidden when a card rests on it."""
        proj = self.tmp / "filmcovers"
        write(proj / "showtime.json", json.dumps({"width": 1280, "height": 720, "fps": 30, "duration": 2}))
        write(proj / "index.html", """<!doctype html><html><head><link rel="stylesheet" href="/_lib/@fontsource-variable/inter/index.css">
<script src="/_st/stage.js"></script><script src="/_st/film.js"></script></head><body><script>
Film.start({ look: 'paper', fonts: ['650 1em "Inter Variable"'], scenes: function (T, g, F) {
  F.text('Revenue grew', 200, 200, { size: 56, weight: 650 });
  F.callout(560, 190, 300, 190, 'Covers the headline', { p: 1, align: 'center' });
  F.callout(-60, 400, 200, 420, 'Points at nothing', { p: 1 });
  F.text('Faint side note', 700, 560, { size: 30, color: '#d8d2c4' });
  F.text('Dimmed label', 900, 640, { size: 30, weight: 650 });
  F.spotlight({ x: 100, y: 100, w: 200, h: 100 }, { p: 1, dim: 0.5 });
  F.callout(1000, 600, 1000, 640, 'Rests on dim', { p: 1, align: 'center' });
} });
</script></body></html>""")
        rep = json.loads(showtime("check", proj, "--json", "--no-determinism", "--no-timeline", "--samples", "2", check=False).stdout)
        msgs = [(f["code"], f["severity"], f["message"]) for f in rep["findings"]]
        self.assertTrue(any(c == "text_overlap" and '"Revenue grew"' in m and "hidden under the callout" in m for c, _, m in msgs), msgs)
        self.assertTrue(any(c == "callout_off_target" and "Points at nothing" in m and sev == "warning" for c, sev, m in msgs), msgs)
        self.assertFalse(any("Dimmed label" in m for c, _, m in msgs if c in ("text_overlap", "low_contrast")), msgs)
        self.assertFalse(any("Faint side note" in m for c, _, m in msgs if c == "low_contrast"), msgs)
        self.assertTrue(any(c == "dimmed_text" for c, _, _ in msgs), msgs)

    def test_14_check_judges_settled_frame_after_transition(self):
        """Text sliding through the vertical safe zone during a push transition is a note naming the
        transition; the settled frame after it is sampled and passes."""
        proj = self.tmp / "txsafe"
        write(proj / "showtime.json", json.dumps({"width": 540, "height": 960, "fps": 30, "duration": 4}))
        write(proj / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script>"
              "<link rel=\"stylesheet\" href=\"/_lib/@fontsource-variable/inter/index.css\">"
              "<script type=\"module\" src=\"/_st/components/index.js\"></script>"
              "<style>body{background:#123;font-family:'Inter Variable'}.scene{position:absolute;inset:0;display:grid;place-items:center;background:#123}"
              "h1{color:#fff;font-size:30px;margin:0}</style></head><body>"
              "<section class=\"scene\" id=\"a\" data-start=\"0\" data-dur=\"2\"><h1>Sunlight is photons</h1></section>"
              "<section class=\"scene\" id=\"b\" data-start=\"#a\" data-dur=\"2\" data-transition=\"push up 0.8\"><h1>Plants catch them</h1></section>"
              "</body></html>")
        rep = json.loads(showtime("check", proj, "--json", "--no-determinism", "--no-timeline", "--samples", "3",
                                  "--at", "2.2,2.4", check=False).stdout)
        self.assertEqual([(w["type"], w["to"]) for w in rep["transitions"]], [("push", "b")])
        self.assertEqual([(x["id"], x["start"], x["end"]) for x in rep["scenes"]], [("a", 0, 2), ("b", 2, 4)])   # for review-pack
        safe = [f for f in rep["findings"] if f["code"] == "safe_zone"]
        self.assertTrue(safe, rep["findings"])
        self.assertTrue(all(f["severity"] == "info" and "mid-transition: push into #b" in f["message"] for f in safe), safe)
        self.assertIn(round(2.8 + 2 / 30, 3), [round(x["t"], 3) for x in rep["samples"]])   # the settled frame

    def test_14b_contrast_mid_transition_is_a_note(self):
        """Contrast measured only mid-transition (two scenes overlap, so the ground behind a text is not its
        own) is a note naming the transition, like layout; a text that is low while settled stays an error.
        Scene b is on screen only inside transitions (its own crossfade in, then c's crossfade over it)."""
        proj = self.tmp / "txcontrast-mid"
        write(proj / "showtime.json", json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 4}))
        write(proj / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script>"
              "<script type=\"module\" src=\"/_st/components/index.js\"></script>"
              "<link rel=\"stylesheet\" href=\"/_lib/@fontsource-variable/inter/index.css\">"
              "<style>body{font-family:'Inter Variable'}.scene{position:absolute;inset:0;display:grid;place-items:center;background:#f4f4f4}"
              "h1{color:#111;font-size:34px;margin:0}#b{background:#102030}#b h1{color:#3a4a5a}</style></head><body>"
              "<section class=\"scene\" id=\"a\" data-start=\"0\" data-dur=\"2\"><h1>Launch day</h1></section>"
              "<section class=\"scene\" id=\"b\" data-start=\"#a\" data-dur=\"0.6\" data-transition=\"crossfade 0.6\"><h1>Proof point</h1></section>"
              "<section class=\"scene\" id=\"c\" data-start=\"#b\" data-dur=\"1.4\" data-transition=\"crossfade 0.6\"><h1>Try it</h1></section>"
              "</body></html>")
        rep = json.loads(showtime("check", proj, "--json", "--no-determinism", "--no-timeline", "--samples", "3",
                                  "--at", "2.3", check=False).stdout)
        low = [f for f in rep["findings"] if f["code"] == "low_contrast"]
        mid = [f for f in low if "mid-transition" in f["message"]]
        self.assertTrue(mid, low)
        self.assertTrue(all(f["severity"] == "info" for f in mid), mid)
        self.assertFalse([f for f in rep["findings"] if f["severity"] == "error"], rep["findings"])
        # a text that is low while settled is still an error
        proj = self.tmp / "txcontrast-plain"
        write(proj / "showtime.json", json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 4}))
        write(proj / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script>"
              "<link rel=\"stylesheet\" href=\"/_lib/@fontsource-variable/inter/index.css\">"
              "<style>body{background:#102030;font-family:'Inter Variable'}.scene{position:absolute;inset:0;display:grid;place-items:center}"
              "h1{color:#1a2a3a;font-size:34px;margin:0}</style></head><body>"
              "<section class=\"scene\" id=\"a\" data-start=\"0\" data-dur=\"2\"><h1>Night mode ships</h1></section>"
              "<section class=\"scene\" id=\"b\" data-start=\"#a\" data-dur=\"2\" data-transition=\"crossfade 0.6\"><h1>Day mode too</h1></section>"
              "</body></html>")
        rep = json.loads(showtime("check", proj, "--json", "--no-determinism", "--no-timeline", "--samples", "3",
                                  "--at", "1.0", check=False).stdout)
        self.assertTrue([f for f in rep["findings"] if f["code"] == "low_contrast" and f["severity"] == "error"
                         and "Night mode" in f["message"] and "mid-transition" not in f["message"]], rep["findings"])

    def test_14c_design_floor_contrast_tiny_text_flat(self):
        """Design floor: any readable text under 4.5:1 is an error (a small label too, not only big type);
        readable text under 2.2% of the frame height is a tiny_text warning, but UI-mockup detail marked
        data-st-decor is exempt; a flat, unlit ground and a mostly empty frame get design notes."""
        proj = self.tmp / "floor"
        write(proj / "showtime.json", json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 3}))
        write(proj / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script>"
              "<link rel=\"stylesheet\" href=\"/_lib/@fontsource-variable/inter/index.css\">"
              "<style>body{margin:0;background:#1b1d22;font-family:'Inter Variable'}.s{position:absolute;inset:0;background:#1b1d22}"
              "p{position:absolute;margin:0;left:40px}.lo{top:40px;font-size:12px;color:#5d616a}.tiny{top:80px;font-size:6px;color:#fff}"
              ".ui{top:120px;font-size:6px;color:#ddd}</style></head><body>"
              "<section class=\"s\" data-start=\"0\" data-dur=\"3\"><p class=\"lo\">Low label here</p>"
              "<p class=\"tiny\">tiny words here</p><p class=\"ui\" data-st-decor>mock toolbar</p></section>"
              "</body></html>")
        rep = json.loads(showtime("check", proj, "--json", "--no-determinism", "--samples", "3", check=False).stdout)
        f = rep["findings"]
        self.assertTrue([x for x in f if x["code"] == "low_contrast" and x["severity"] == "error" and "Low label" in x["message"]], f)
        self.assertTrue([x for x in f if x["code"] == "tiny_text" and x["severity"] == "warning" and "tiny words" in x["message"]], f)
        self.assertFalse([x for x in f if x["code"] == "tiny_text" and "mock toolbar" in x["message"]], f)
        self.assertTrue([x for x in f if x["code"] == "flat_background" and x["severity"] == "info"], f)
        self.assertTrue([x for x in f if x["code"] == "sparse_frame" and x["severity"] == "info"], f)
        self.assertGreaterEqual(rep["design"]["flat_share"], 0.75)

    def test_14d_contrast_of_caption_words_and_faded_text(self):
        """A caption word is judged at its colours, not at a karaoke state: sampled while its card fades in
        and the word is still upcoming (dimmed in the minimal style), the accent #e9b949 on #17120e is
        10.18:1, not the 2.98:1 of a 45% opacity. A caption accent that is really low still fails, and plain
        text faded to 45% fails with its opacity named, so the colours and the ratio in the message agree."""
        proj = self.tmp / "capcontrast"
        write(proj / "showtime.json", json.dumps({"width": 1280, "height": 720, "fps": 30, "duration": 4}))
        # one card, on screen 1.90-3.60 s: at the 2.00 s sample it is fading in and "Claude" is upcoming
        write(proj / "words.json", json.dumps([{"text": "Works", "start": 1.95, "end": 2.1}, {"text": "in", "start": 2.1, "end": 2.2},
                                               {"text": "Claude", "start": 2.2, "end": 2.5, "emph": True}, {"text": "Code.", "start": 2.5, "end": 2.8}]))
        page = ("<!doctype html><html><head><script src=\"/_st/stage.js\"></script>"
                "<link rel=\"stylesheet\" href=\"/_lib/@fontsource-variable/inter/index.css\">"
                "<script type=\"module\" src=\"/_st/components/index.js\"></script>"
                "<style>body{margin:0;background:#17120e;font-family:'Inter Variable'}.s{position:absolute;inset:0;background:#17120e}"
                ".st-cap{--cap-ink:#f5ebdc;--cap-accent:%s;--cap-outline:#17120e}"
                "p{position:absolute;left:60px;top:60px;margin:0;font-size:40px;color:#e9b949;opacity:%s}</style></head><body>"
                "<section class=\"s\" data-start=\"0\" data-dur=\"4\"><p>Faded note</p>"
                "<div data-st=\"caption-karaoke\" data-src=\"words.json\" data-style=\"minimal\" data-emphasis=\"free\"></div>"
                "</section></body></html>")

        def run(accent, note_opacity):
            write(proj / "index.html", page % (accent, note_opacity))
            rep = json.loads(showtime("check", proj, "--json", "--no-determinism", "--no-timeline", "--samples", "1", check=False).stdout)
            low = [f for f in rep["findings"] if f["code"] == "low_contrast"]
            cap = next(c for c in rep["contrast"] if c["text"].startswith("Works in"))
            return low, cap
        low, cap = run("#e9b949", "1")
        self.assertFalse(low, low)
        self.assertAlmostEqual(cap["ratio"], 10.18, delta=0.05)
        self.assertEqual((cap["fg"], cap["bg"]), ("#e9b949", "#17120e"))
        # a caption accent that is low against the ground is still reported
        low, cap = run("#4a3a20", "1")
        self.assertTrue([f for f in low if '"Claude"' in f["message"]], low)
        self.assertLess(cap["ratio"], 2)
        # plain text at 45% opacity: still an error, and the message says what was measured
        low, _ = run("#e9b949", "0.45")
        faded = [f for f in low if "Faded note" in f["message"]]
        self.assertTrue(faded and faded[0]["severity"] == "error", low)
        self.assertIn("#e9b949 at 45% opacity", faded[0]["message"])
        self.assertAlmostEqual(faded[0]["ratio"], 2.98, delta=0.05)

    def test_15_server_hint_for_static_site(self):
        """`showtime server` on a folder without showtime.json points at `site capture --serve`."""
        site = self.tmp / "static-site"
        write(site / "index.html", "<!doctype html><title>s</title><h1>hi</h1>")
        node = shutil.which("node", path=ENV.get("PATH"))
        p = subprocess.Popen([node, str(SKILL / "scripts" / "server.mjs"), str(site), "--port", "0", "--json"], env=ENV,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        try:
            self.assertIn("url", json.loads(p.stdout.readline()))
        finally:
            p.terminate()
            _, err = p.communicate(timeout=10)
        self.assertIn("not a showtime project", err)
        self.assertIn("site capture --serve", err)
        empty = self.tmp / "empty-site"
        empty.mkdir()
        cp = subprocess.run([node, str(SKILL / "scripts" / "server.mjs"), str(empty), "--port", "0"], env=ENV,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=30)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("site capture --serve", cp.stderr)

    def test_16_render_log_and_studio_media(self):
        """Every render tees its ffmpeg/browser output into <work>/logs/render.log; a render into
        <job>/studio/ is logged in the job but does not become the job's latest preview/final."""
        proj = self.tmp / "tiny"
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 30, "duration": 0.5}))
        write(proj / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script></head><body style=\"background:#246\">"
              "<script>console.error('probe console error'); ST.onSeek((t) => { document.body.style.background = t > 0.25 ? '#642' : '#246'; });</script></body></html>")
        base = self.tmp / "jobs"
        job = Path(json.loads(showtime("job", "init", "logtest", "--base", base, "--json").stdout)["job"])
        out = job / "studio" / "media" / "animatic.mp4"
        rep = json.loads(showtime("render", proj, "-o", out, "--preview", "--poster", "none", "--no-audio", "--json").stdout)
        log = Path(rep["log"])
        self.assertTrue(log.is_file(), rep)
        text = log.read_text(encoding="utf-8")
        self.assertIn("$ ffmpeg", text)
        self.assertIn("probe console error", text)
        ledger = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertFalse((ledger.get("outputs") or {}).get("preview"), ledger.get("outputs"))
        self.assertIn("studio render", json.dumps(ledger))
        # the render's scratch folder stays out of studio/ (studio/media holds only media)
        self.assertFalse((job / "studio" / "media" / "animatic.work").exists())
        self.assertTrue(log.is_relative_to(job / "work" / "renders"), log)

    def test_16b_keep_work_and_interrupted_render(self):
        """--keep-work keeps the whole work folder; an interrupted render removes its frames (--keep-frames
        keeps them) and leaves its log."""
        proj = self.tmp / "tidy"
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 30, "duration": 0.5}))
        write(proj / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script></head>"
              "<body style=\"background:#246\"><script>ST.onSeek((t) => { document.body.style.background = "
              "t > 0.25 ? '#642' : '#246'; });</script></body></html>")
        job = Path(json.loads(showtime("job", "init", "tidy", "--base", self.tmp / "tidyjobs", "--json").stdout)["job"])
        showtime("render", proj, "--job", job, "--preview", "--poster", "none", "--no-audio", "--keep-work")
        self.assertTrue((job / "preview.work" / "video.mp4").is_file(), "--keep-work keeps the silent video")
        self.assertFalse((job / "preview.work" / "frames").exists())
        if os.name == "nt":
            return                        # no SIGINT to send to a child process on Windows
        import signal
        # interrupted: a long render, stopped once frames are on disk
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 30, "duration": 120}))
        for keep in (False, True):
            out = self.tmp / ("stopped-%d" % keep) / "stopped.mp4"
            args = [shutil.which("node") or "node", str(SKILL / "scripts" / "render.mjs"), str(proj), "-o", str(out),
                    "--workers", "1", "--no-audio", "--poster", "none"] + (["--keep-frames"] if keep else [])
            errf = self.tmp / ("stopped-%d.err" % keep)
            with open(str(errf), "wb") as fh:
                p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=fh, env=ENV)
                frames = out.parent / "stopped.work" / "frames"
                t_end = time.time() + 240
                while time.time() < t_end and p.poll() is None and not (frames.is_dir() and len(os.listdir(frames)) >= 10):
                    time.sleep(0.2)
                self.assertIsNone(p.poll(), "the render ended before it could be interrupted")
                p.send_signal(signal.SIGINT)
                p.wait(timeout=60)
            err = errf.read_text(encoding="utf-8", errors="replace")
            self.assertEqual(p.returncode, 130, err[-800:])
            self.assertIn("interrupted", err)
            self.assertEqual(frames.is_dir() and any(frames.iterdir()), keep, err[-800:])
            self.assertTrue((out.parent / "stopped.work" / "logs" / "render.log").is_file())
            self.assertFalse(out.exists())

    def test_17_poster_flash_render_block_and_rerender_info(self):
        """A poster that does not look like the opening is written as poster.jpg but not baked into
        frame 0 (it would flash); showtime.json "render" sets encode defaults; a re-render next to an
        existing final is an info line, not a warning."""
        proj = self.tmp / "posterflash"
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 30, "duration": 1.0, "poster": 0.9,
                                                  "render": {"crf": 30, "x264_preset": "veryfast"}}))
        write(proj / "index.html", "<!doctype html><html><head><script src=\"/_st/stage.js\"></script></head><body style=\"margin:0;background:#000\">"
              "<script>ST.onSeek((t) => { document.body.style.background = t > 0.6 ? '#fff' : '#000'; });</script></body></html>")
        out = self.tmp / "posterflash-out" / "final.mp4"
        r1 = json.loads(showtime("render", proj, "-o", out, "--no-audio", "--workers", 1, "--json").stdout)
        self.assertFalse(r1["poster"]["baked"], r1["poster"])
        self.assertGreater(r1["poster"]["opening_diff"], 12)
        self.assertTrue(Path(r1["poster"]["file"]).is_file())
        self.assertEqual(r1["encode"]["crf"], 30)
        self.assertEqual(r1["encode"]["preset"], "veryfast")
        # frame 0 stays the black opening
        f0 = ffmpeg_bytes(["-i", str(out), "-frames:v", "1", "-vf", "scale=8:8,format=gray", "-f", "rawvideo", "-"])
        self.assertLess(max(f0), 40)
        cp = showtime("render", proj, "-o", out, "--no-audio", "--workers", 1, "--poster-bake", "force")
        self.assertNotIn("warning", cp.stdout + cp.stderr.replace("0 warning", ""))
        self.assertIn("final-2.mp4", cp.stdout)
        self.assertIn("renders never overwrite", cp.stdout + cp.stderr)
        f0 = ffmpeg_bytes(["-i", str(out.with_name("final-2.mp4")), "-frames:v", "1", "-vf", "scale=8:8,format=gray", "-f", "rawvideo", "-"])
        self.assertGreater(min(f0), 200)   # forced bake: frame 0 is the white poster

    def test_18_score_output_in_job_and_narration_gap(self):
        """`showtime score` on a project inside a job writes <job>/work/score/ (never a showtime-out/
        inside the project), and with a voice track in the mix it reports the voice-over-bed gap."""
        base = self.tmp / "scorejob"
        job = Path(json.loads(showtime("job", "init", "scorejob", "--base", base, "--json").stdout)["job"])
        proj = job / "project"
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 30, "duration": 2, "audio": "audio/mix.json"}))
        write(proj / "audio" / "mix.json", json.dumps({"tracks": [{"kind": "voice", "file": "voice/vo.wav"}]}))
        write(proj / "index.html", CANVAS_HTML)
        cp = subprocess.run([sys.executable, str(LAUNCHER), "score", str(proj), "--json"], env=ENV, cwd=str(proj),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        rep = json.loads(cp.stdout)
        self.assertEqual(Path(rep["output"]).parent, job / "work" / "score")
        self.assertFalse((proj / "showtime-out").exists())
        self.assertTrue(rep["narrated"])
        self.assertFalse(any("very quiet" in w for w in rep["warnings"]), rep["warnings"])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    t0 = time.time()
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    print("render-core results: %s" % json.dumps(RESULTS))
    print("elapsed: %.1fs" % (time.time() - t0))
    sys.exit(0 if prog.result.wasSuccessful() else 1)

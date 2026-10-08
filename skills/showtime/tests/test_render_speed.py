#!/usr/bin/env python3
"""Render speed (0.4.1): the work split, the encoder fed during the capture, the worker count, the soundtrack reuse.

  * units (no browser): CaptureQueue hands every frame of a plan out exactly once while workers finish at
    different times, and moves the back half of the largest part to a worker that is done (never a part
    smaller than the warm-up makes worth it); autoWorkers picks 3 with a GPU, one per 8 CPU threads (3-8)
    without one, within the frame, memory and SHOWTIME_MAX_WORKERS limits; the software-GL pattern knows
    SwiftShader, llvmpipe and WARP and no hardware GPU; --disable-frame-rate-limit is in render's flags only
  * OrderedFeed (real ffmpeg, no browser): frames that land out of order are fed in order through a pipe and
    the H.264 file is byte for byte the encode of the same frames read from disk; a held frame 0 (the poster
    bake) waits for its stand-in; a stopped feed kills the encoder
  * render (real, software GL so the pixels are exact): the default encode is x264 veryfast during the capture,
    the file is the same as the encode after the capture (SHOWTIME_PIPE_ENCODE=0) and 3 workers with hand-overs
    give the same file as 1 worker, and so do 2 workers with two parts each; render.json says how many workers and why; a poster baked into frame 0
    while the encoder runs; a splice into a render made with another preset uses that preset and still cuts
  * soundtrack reuse: an unchanged mix is reused by the next render (same bytes), a page edit keeps it, a
    changed audio file mixes it again, SHOWTIME_AUDIO_CACHE=0 never reuses

Stdlib only. usage: python tests/test_render_speed.py [--fast] [-v]
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
PIPELINE = (SKILL / "scripts" / "lib" / "pipeline.mjs").as_uri()
STAGEHOST = (SKILL / "scripts" / "lib" / "stagehost.mjs").as_uri()
CHROME = (SKILL / "scripts" / "lib" / "chrome.mjs").as_uri()
AUDIOCACHE = (SKILL / "scripts" / "lib" / "audiocache.mjs").as_uri()
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
ENV.pop("SHOWTIME_OUT", None)
ENV["SHOWTIME_OFFLINE"] = "1"
# one screenshot that never returns on a starved machine would otherwise use the render's whole 600 s wait,
# the same as these tests' own time limit (review W2): a stuck one is retried after 60 s instead
ENV["SHOWTIME_SHOT_TIMEOUT"] = "60"
NODE = shutil.which("node", path=ENV.get("PATH")) or shutil.which("node")


def node(code, timeout=180):
    cp = subprocess.run([NODE, "--input-type=module", "-e", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding="utf-8", errors="replace", timeout=timeout, env=ENV)
    assert cp.returncode == 0, cp.stderr[-3000:]
    return json.loads(cp.stdout.strip().splitlines()[-1])


def showtime(*args, check=True, env=None, timeout=600):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=env or ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def render(proj, out, *args, env=None):
    cp = showtime("render", proj, "-o", out, "--no-check", "--json", *args, env=env)
    return json.loads(cp.stdout), cp


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def run_ff(*args):
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-y"] + [str(a) for a in args],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")[-2000:]
    return cp.stdout


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# a page whose last third is slow to draw: the worker on it falls behind and the others take its frames
SLOW_TAIL_HTML = """<!doctype html><html><head><script src="/_st/stage.js"></script></head>
<body style="margin:0;background:#111"><canvas id="c" width="320" height="180"></canvas><script>
const g = document.getElementById('c').getContext('2d');
ST.onSeek((t) => {
  g.fillStyle = '#123'; g.fillRect(0, 0, 320, 180);
  const n = t > %(slow)s ? 60000 : 50;
  for (let i = 0; i < n; i++) { g.fillStyle = 'hsl(' + ((i * 7 + t * 90) %% 360) + ',70%%,55%%)'; g.fillRect((i * 37 + t * 60) %% 320, (i * 53) %% 180, 3, 3); }
  g.fillStyle = '#fff'; g.fillRect((t * 80) %% 300, 80, 20, 20);
});
</script></body></html>
"""


@unittest.skipUnless(NODE, "Node.js is not installed")
class TestUnits(unittest.TestCase):
    def test_queue_hands_out_every_frame_once(self):
        r = node("""
import { CaptureQueue } from '%s';
const out = [];
for (const [plan, W, speeds] of [
  [[[0, 450]], 3, [1, 1, 4]], [[[0, 450]], 3, [1, 1, 1]], [[[0, 30], [60, 120], [200, 260]], 2, [1, 3]],
  [[[0, 900]], 8, [1, 2, 3, 1, 1, 5, 1, 2]], [[[0, 40]], 3, [1, 9, 1]],
  // worker 2 never gets its page open: the others take its whole part
  [[[0, 450]], 3, [1, 1, null]]]) {
  // splitPlan's parts: contiguous, about equal
  const total = plan.reduce((n, [s, e]) => n + e - s, 0), chunk = Math.ceil(total / W), parts = [];
  let cur = [], room = chunk;
  for (const [s0, e0] of plan) { let s = s0; while (s < e0) { const e = Math.min(e0, s + room); cur.push([s, e]); room -= e - s; s = e; if (!room) { parts.push(cur); cur = []; room = chunk; } } }
  if (cur.length) parts.push(cur);
  const q = new CaptureQueue(parts, { minSteal: 24 });
  const seen = new Map(), clock = parts.map(() => 0), run = parts.map(() => null), done = speeds.map((x) => x === null);
  let jumps = 0; const last = parts.map(() => null);
  for (let guard = 0; guard < 100000 && done.some((d) => !d); guard++) {
    let w = -1; for (let k = 0; k < parts.length; k++) if (!done[k] && (w < 0 || clock[k] < clock[w])) w = k;
    if (!run[w]) { run[w] = q.take(w); if (!run[w]) { done[w] = true; continue; } if (last[w] !== null && run[w].next !== last[w]) jumps++; }
    const i = q.claim(w);
    if (i === null) { run[w] = null; continue; }
    seen.set(i, (seen.get(i) || 0) + 1); last[w] = i + 1; clock[w] += speeds[w];
  }
  const want = []; for (const [s, e] of plan) for (let i = s; i < e; i++) want.push(i);
  out.push({ all: want.every((i) => seen.get(i) === 1) && seen.size === want.length, steals: q.steals, handed: q.handed, left: q.left(),
             finish: Math.max(...clock), never: q.lanes.map((l) => l.started), ideal: Math.ceil(want.length / speeds.reduce((n, s) => n + 1 / s, 0)) });
}
console.log(JSON.stringify(out));
""" % PIPELINE)
        for k, x in enumerate(r):
            self.assertTrue(x["all"], (k, x))
            self.assertEqual(x["left"], 0)
            for _, _, s, e in x["handed"]:
                self.assertGreaterEqual(e - s, 12, "a hand-over is at least half of minSteal (%s)" % x)
        self.assertGreater(r[0]["steals"], 0, "the slow worker's frames are handed over")
        self.assertLess(r[0]["finish"], 0.7 * (450 // 3) * 4, "and it no longer finishes alone (%s)" % r[0])
        self.assertEqual(r[1]["steals"], 0, "equal workers keep their parts (no extra warm-ups)")
        self.assertEqual(r[4]["steals"], 0, "parts shorter than minSteal are never split")
        self.assertEqual(r[5]["never"], [True, True, False], r[5])
        self.assertTrue(any(f == 2 and (s, e) == (300, 450) for f, _, s, e in r[5]["handed"]), "the whole part of a worker that never started")

    def test_auto_workers_and_software_gl(self):
        r = node("""
import { autoWorkers, machineLimits } from '%s';
import { SOFTWARE_GL } from '%s';
import { renderFlags, chromeFlags } from '%s';
const a = (o) => autoWorkers({ memGB: 64, frames: 2700, ...o }).workers;
console.log(JSON.stringify({
  box: a({ cpus: 64, software: true }), mac_off: a({ cpus: 6, software: true }), mac_gpu: a({ cpus: 6, software: false }),
  big_gpu: a({ cpus: 64, software: false }), quad_gpu: a({ cpus: 4, software: false }), sw16: a({ cpus: 16, software: true }),
  sw256: a({ cpus: 256, software: true }), sw4: a({ cpus: 4, software: true }), sw32: a({ cpus: 32, software: true }), short: a({ cpus: 64, software: true, frames: 100 }),
  capped: a({ cpus: 64, software: true, cap: 2 }), lowmem: autoWorkers({ cpus: 64, software: true, frames: 2700, memGB: 8 }).workers,
  why: autoWorkers({ cpus: 64, memGB: 128, software: true, frames: 2700, renderer: 'ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)' }).why,
  why_cap: autoWorkers({ cpus: 6, memGB: 32, software: false, frames: 60 }).why,
  lim_box: machineLimits({ totalBytes: 128 * 2 ** 30, constrained: 4 * 2 ** 30, cpuMax: '400000 100000\\n' }),
  lim_free: machineLimits({ totalBytes: 16 * 2 ** 30, constrained: 0, cpuMax: 'max 100000\\n' }),
  lim_here: machineLimits(),
  render_flag: renderFlags().includes('--disable-frame-rate-limit'),
  common_flag: [...chromeFlags('auto', 'mac'), ...chromeFlags('auto', 'windows'), ...chromeFlags('auto', 'linux'), ...chromeFlags('off')].includes('--disable-frame-rate-limit'),
  sw: ['ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)', 'llvmpipe (LLVM 20.1.2, 256 bits)',
       'ANGLE (Microsoft, Microsoft Basic Render Driver (0x0000008C) Direct3D11 vs_5_0 ps_5_0, D3D11)', 'Google SwiftShader'].map((s) => SOFTWARE_GL.test(s)),
  hw: ['ANGLE (AMD, AMD Radeon Pro 570X OpenGL Engine, OpenGL 4.1)', 'ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)',
       'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 (0x00002503) Direct3D11 vs_5_0 ps_5_0, D3D11)', 'ANGLE (Intel, Intel(R) UHD Graphics 630, OpenGL 4.1)',
       'ANGLE (Qualcomm, Qualcomm(R) Adreno(TM) X1-85 GPU, D3D11)'].map((s) => SOFTWARE_GL.test(s)),
}));
""" % (PIPELINE, STAGEHOST, CHROME))
        self.assertEqual((r["box"], r["mac_off"], r["mac_gpu"], r["big_gpu"], r["quad_gpu"]), (8, 3, 3, 3, 2))
        # without a GPU never fewer than 0.4.0's 3 (DOM pages were 50 % slower with 1 on 6 threads), 2 on 4 threads
        self.assertEqual((r["sw4"], r["sw16"], r["sw32"], r["sw256"]), (2, 3, 4, 8))
        self.assertEqual((r["short"], r["capped"], r["lowmem"]), (2, 2, 2))
        self.assertIn("SwiftShader", r["why"])
        self.assertIn("one browser per 8 of 64 CPU threads", r["why"])
        self.assertIn("1 because of 60 frames", r["why_cap"])
        # a container's memory limit caps the memory the worker count sees; its CPU quota is reported (review S4)
        self.assertEqual((r["lim_box"]["memGB"], r["lim_box"]["quotaCpus"]), (4, 4))
        self.assertIn("memory limit 4.0 GB of 128.0 GB", r["lim_box"]["note"])
        self.assertIn("cgroup cpu.max 400000 100000 (4 CPUs)", r["lim_box"]["note"])
        self.assertEqual((r["lim_free"]["memGB"], r["lim_free"]["quotaCpus"], r["lim_free"]["note"]), (16, None, ""))
        self.assertGreater(r["lim_here"]["memGB"], 0)
        self.assertEqual(r["sw"], [True] * 4)
        self.assertEqual(r["hw"], [False] * 5)
        # the frame-rate flag is for render's browsers only (live playback, e.g. an HTML video's audio start, breaks with it)
        self.assertEqual((r["render_flag"], r["common_flag"]), (True, False))


@unittest.skipUnless(NODE, "Node.js is not installed")
class TestOrderedFeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-feed-"))
        cls.frames = cls.tmp / "frames"
        cls.frames.mkdir()
        run_ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=2", "-q:v", "3", cls.frames / "f_%06d.jpg")
        # the encode of the files, read from disk after the "capture" (as before 0.4.1)
        cls.vf = ("crop=trunc(iw/2)*2:trunc(ih/2)*2,scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int,"
                  "format=yuv420p,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709")
        cls.venc = ["-vf", cls.vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-profile:v", "high", "-bf", "0",
                    "-x264-params", "aq-mode=3", "-g", "60", "-pix_fmt", "yuv420p", "-video_track_timescale", "90000",
                    "-movflags", "+faststart", "-r", "30", "-an"]
        run_ff("-framerate", "30", "-start_number", "1", "-i", cls.frames / "f_%06d.jpg", *cls.venc, cls.tmp / "files.mp4")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def feed(self, out, extra=""):
        return node("""
import { OrderedFeed } from '%s';
import path from 'node:path';
const dir = %s, out = %s, venc = %s;
const pathOf = (i) => path.join(dir, 'f_' + String(i + 1).padStart(6, '0') + '.jpg');
const order = Array.from({ length: 60 }, (_, i) => i);
const feed = new OrderedFeed({ order, pathOf, args: ['-f', 'image2pipe', '-framerate', '30', '-c:v', 'mjpeg', '-i', '-', ...venc, out] });
%s
feed.start();
// frames "land" out of order: three workers on three thirds, the last third first
const land = [...order.slice(40), ...order.slice(20, 40), ...order.slice(0, 20)];
for (const i of land) { await new Promise((r) => setTimeout(r, 2)); feed.ready(i); }
let err = null;
try { await feed.finish(); } catch (e) { err = String(e.message || e); }
console.log(JSON.stringify({ fed: feed.fed, err }));
""" % (PIPELINE, json.dumps(str(self.frames)), json.dumps(str(out)), json.dumps(self.venc), extra))

    def test_pipe_encode_is_the_file_encode(self):
        r = self.feed(self.tmp / "pipe.mp4")
        self.assertEqual((r["fed"], r["err"]), (60, None))
        self.assertEqual(md5(self.tmp / "pipe.mp4"), md5(self.tmp / "files.mp4"), "the same bytes as the encode of the files")

    def test_hold_sends_a_stand_in_for_frame_0(self):
        r = self.feed(self.tmp / "held.mp4", "feed.hold(0, async () => { await feed.wait(45); return pathOf(45); });")
        self.assertEqual((r["fed"], r["err"]), (60, None))
        first = run_ff("-i", self.tmp / "held.mp4", "-frames:v", "1", "-vf", "scale=16:9,format=gray", "-f", "rawvideo", "-")
        f45 = run_ff("-ss", "1.5", "-i", self.tmp / "files.mp4", "-frames:v", "1", "-vf", "scale=16:9,format=gray", "-f", "rawvideo", "-")
        f0 = run_ff("-i", self.tmp / "files.mp4", "-frames:v", "1", "-vf", "scale=16:9,format=gray", "-f", "rawvideo", "-")
        mad = lambda a, b: sum(abs(x - y) for x, y in zip(a, b)) / len(a)  # noqa: E731
        self.assertLess(mad(first, f45), 3)
        self.assertGreater(mad(first, f0), 3)

    def test_stopped_feed_kills_the_encoder(self):
        r = node("""
import { OrderedFeed } from '%s';
const feed = new OrderedFeed({ order: [0, 1, 2], pathOf: () => 'nope', args: ['-f', 'image2pipe', '-c:v', 'mjpeg', '-i', '-', '-f', 'null', '-'] });
feed.start();
setTimeout(() => feed.fail(new Error('stopped by test')), 200);
let err = null;
try { await feed.finish(); } catch (e) { err = String(e.message || e); }
console.log(JSON.stringify({ err }));
""" % PIPELINE)
        self.assertTrue(r["err"], r)

    RACE_JS = """
import { OrderedFeed } from '%s';
const f = %s;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const feed = new OrderedFeed({ order: [0, 1, 2], pathOf: () => f, args: ['-f', 'image2pipe', '-c:v', 'mjpeg', '-i', '-', '-f', 'null', '-'] });
// frame 1 is held 1.5 s (the poster decision, a slow disk): the encoder exits meanwhile
feed.hold(1, async () => { await sleep(1500); return f; });
feed.start();
[0, 1, 2].forEach((i) => feed.ready(i));
const t0 = Date.now();
const res = await Promise.race([feed.finish().then(() => 'finished', (e) => 'rejected: ' + String(e.message).split('\\n')[0]),
  sleep(15000).then(() => 'HUNG')]);
console.log(JSON.stringify({ res, dead: !!feed.dead, fed: feed.fed, ms: Date.now() - t0 }));
process.exit(0);
"""

    @unittest.skipIf(os.name == "nt", "the stand-in encoder is a script with a #! line")
    def test_encoder_that_exits_between_frames_never_hangs_the_feed(self):
        """An encoder that reads everything it is sent and exits 1 a second later, while frame 1 is still held:
        no EPIPE comes, Node has closed the pipe, and finish() must reject with the encoder's error instead of
        waiting forever for a drain (review S1, the reviewer's harness). The real ffmpeg finishes the same feed."""
        fake = self.tmp / "dying-ffmpeg.mjs"
        fake.write_text("#!" + NODE + "\n"
                        "if (process.argv.includes('-version')) { console.log('ffmpeg version fake'); process.exit(0); }\n"
                        "process.stdin.on('data', () => {});\n"
                        "setTimeout(() => { process.stderr.write('encoder died\\n'); process.exit(1); }, 1000);\n", encoding="utf-8")
        fake.chmod(0o755)
        js = self.RACE_JS % (PIPELINE, json.dumps(str(self.frames / "f_000001.jpg")))
        cp = subprocess.run([NODE, "--input-type=module", "-e", js], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", timeout=120, env=dict(ENV, SHOWTIME_FFMPEG=str(fake)))
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertEqual(r["res"], "rejected: ffmpeg failed (exit 1): encoder died", r)
        self.assertTrue(r["dead"], r)
        real = node(js)
        self.assertEqual((real["res"], real["fed"]), ("finished", 3), real)


@unittest.skipUnless(NODE, "Node.js is not installed")
class TestRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-speed-"))
        cls.proj = cls.tmp / "proj"
        # 10 fps: a 1 s warm-up is 10 frames, so the parts are big enough to hand over
        write(cls.proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 10, "duration": 15, "poster": 0}))
        write(cls.proj / "index.html", SLOW_TAIL_HTML % {"slow": 10})

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_1_pipe_and_handover_keep_the_bytes(self):
        """software GL: 3 workers with hand-overs and the encoder fed during the capture give the file that
        1 worker and an encode after the capture give."""
        o = self.tmp / "o"
        r3, cp3 = render(self.proj, o / "w3" / "final.mp4", "--gpu", "off", "--workers", 3, "--no-audio")
        seq_env = dict(ENV, SHOWTIME_PIPE_ENCODE="0")
        r1, _ = render(self.proj, o / "w1" / "final.mp4", "--gpu", "off", "--workers", 1, "--no-audio", env=seq_env)
        self.assertEqual(r3["encode"], {"codec": "libx264", "preset": "veryfast", "crf": 16, "during_capture": True})
        self.assertEqual(r1["encode"], {"codec": "libx264", "preset": "veryfast", "crf": 16})
        self.assertEqual((r3["workers"], r3["workers_why"]), (3, "--workers 3"))
        self.assertTrue(r3["browser"]["software_gl"])
        self.assertEqual(r3["frames"], 150)
        self.assertEqual(md5(r3["output"]), md5(r1["output"]), "same bytes: 3 workers + encode during capture vs 1 worker + encode after")
        # two parts per worker (the default with a GPU): each worker jumps to its second part with a warm-up
        r2, _ = render(self.proj, o / "p2" / "final.mp4", "--gpu", "off", "--workers", 2, "--no-audio", env=dict(ENV, SHOWTIME_RENDER_PARTS="2"))
        self.assertEqual(md5(r2["output"]), md5(r1["output"]), "same bytes with two parts per worker")
        self.assertIn("2 part(s) each", Path(r2["log"]).read_text(encoding="utf-8"))
        log = Path(r3["log"]).read_text(encoding="utf-8")
        self.assertIn("hand-over", log)
        self.assertIn("frames on stdin", log)

    def test_2_auto_workers_say_why(self):
        r, cp = render(self.proj, self.tmp / "auto" / "final.mp4", "--gpu", "off", "--no-audio")
        self.assertIn("no GPU", r["workers_why"])
        self.assertIn("workers: no GPU", cp.stderr)
        self.assertTrue(r["browser"]["webgl"])

    def test_3_poster_baked_while_encoding(self):
        """A poster that looks like the opening is baked into frame 0 while the encoder already runs."""
        proj = self.tmp / "poster"
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 10, "duration": 6, "poster": 4.0}))
        write(proj / "index.html", SLOW_TAIL_HTML % {"slow": 99})
        r, _ = render(proj, self.tmp / "poster-out" / "final.mp4", "--gpu", "off", "--workers", 2, "--no-audio", "--keep-frames")
        self.assertTrue(r["poster"]["baked"], r["poster"])
        self.assertTrue(r["encode"].get("during_capture"))
        frames = Path(r["output"]).parent / "final.work" / "frames"
        self.assertEqual(md5(frames / "f_000000.jpg"), md5(frames / "f_000040.jpg"), "frame 0 on disk is the poster frame")
        g = lambda f, ss: run_ff("-ss", ss, "-i", f, "-frames:v", "1", "-vf", "scale=16:9,format=gray", "-f", "rawvideo", "-")  # noqa: E731
        mad = lambda a, b: sum(abs(x - y) for x, y in zip(a, b)) / len(a)  # noqa: E731
        self.assertLess(mad(g(r["output"], "0"), g(r["output"], "4.0")), 2, "frame 0 of the video is the poster")

    @unittest.skipIf(os.name == "nt", "the stand-in encoder is a script with a #! line")
    def test_3b_dying_encoder_fails_cleanly_without_a_poster(self):
        """The encoder dies during the capture while the poster was already decided: the render fails with the
        encoder's error (no hang), and no poster.jpg is left beside a video that was never written (review P1)."""
        proj = self.tmp / "poster-die"
        write(proj / "showtime.json", json.dumps({"width": 320, "height": 180, "fps": 10, "duration": 6, "poster": 1.0}))
        write(proj / "index.html", SLOW_TAIL_HTML % {"slow": 99})
        fake = self.tmp / "ffmpeg-dies-on-pipe.mjs"
        fake.write_text("#!" + NODE + "\n"
                        "import { spawnSync } from 'node:child_process';\n"
                        "const args = process.argv.slice(2);\n"
                        "if (!args.includes('image2pipe')) process.exit(spawnSync(%s, args, { stdio: 'inherit' }).status ?? 1);\n"
                        "process.stdin.on('data', () => {});\n"
                        "setTimeout(() => { process.stderr.write('simulated encoder death\\n'); process.exit(1); }, 1500);\n"
                        % json.dumps(ff.ffmpeg_path()), encoding="utf-8")
        fake.chmod(0o755)
        out = self.tmp / "poster-die-out" / "final.mp4"
        cp = showtime("render", proj, "-o", out, "--no-check", "--gpu", "off", "--workers", 2, "--no-audio", check=False,
                      env=dict(ENV, SHOWTIME_FFMPEG=str(fake)), timeout=300)
        self.assertNotEqual(cp.returncode, 0, cp.stdout[-1500:])
        self.assertIn("simulated encoder death", cp.stderr)
        self.assertFalse(out.exists())
        self.assertFalse((out.parent / "poster.jpg").exists(), sorted(p.name for p in out.parent.iterdir()))

    def test_4_splice_keeps_the_base_preset(self):
        """A full render made with --x264-preset medium: a fix spliced into it without a preset uses medium (the
        parameter sets match) and cuts instead of encoding the whole video again."""
        base = self.tmp / "splicejob"
        job = Path(json.loads(showtime("job", "init", "speed", "--base", base, "--json").stdout)["job"])
        proj = self.tmp / "sp"
        write(proj / "showtime.json", json.dumps({"width": 256, "height": 144, "fps": 30, "duration": 4, "poster": 0}))
        write(proj / "index.html", SLOW_TAIL_HTML % {"slow": 99})
        showtime("render", proj, "--job", job, "--no-check", "--no-audio", "--workers", 1, "--x264-preset", "medium")
        write(proj / "index.html", (SLOW_TAIL_HTML % {"slow": 99}).replace("'#fff'", "'#f00'"))
        sp = json.loads(showtime("render", proj, "--job", job, "--no-check", "--no-audio", "--workers", 1, "--from", 2.1, "--to", 2.4, "--json").stdout)
        self.assertEqual(sp["splice"]["mode"], "cut", sp["splice"])
        self.assertEqual(sp["encode"]["preset"], "medium")

    def test_5_failed_write_and_the_gpu_decision(self):
        """A frame whose write fails halfway is captured again (no hang); every page gets the render's GPU-or-not
        decision (__ST_RENDER__.softwareGL, read by the looks through gl.js softwareGL), render.json records it,
        and a span spliced into a job's full render takes that render's decision."""
        proj = self.tmp / "gpu"
        # 256x144, the size of the other small pages here: at 128x72 (the only page this small in the suite) a
        # no-GPU Ubuntu machine (SwiftShader) saw this test's screenshots wait out the 60 s shot timeout, about 4
        # minutes instead of seconds
        write(proj / "showtime.json", json.dumps({"width": 256, "height": 144, "fps": 10, "duration": 2, "poster": 0}))
        write(proj / "index.html", GL_DECISION_HTML)
        r, _ = render(proj, self.tmp / "gpu-out" / "final.mp4", "--gpu", "off", "--workers", 2, "--no-audio",
                      env=dict(ENV, SHOWTIME_TEST_FAIL_WRITE="5"))
        self.assertEqual(r["frames"], 20)
        self.assertIn("frame(s) missing after capture; re-capturing", " ".join(r.get("warnings") or []))
        self.assertIn("frame 5: the write failed", Path(r["log"]).read_text(encoding="utf-8"))
        self.assertTrue(r["browser"]["page_software_gl"])
        self.assertEqual(colour(r["output"], 1.0), "red", "the page was told: no GPU")
        # a span into a job whose full render decided the other way draws as that render did
        base = self.tmp / "gpujob"
        job = Path(json.loads(showtime("job", "init", "gpu", "--base", base, "--json").stdout)["job"])
        full = json.loads(showtime("render", proj, "--job", job, "--no-check", "--no-audio", "--workers", 1, "--gpu", "off",
                                   "--json").stdout)
        self.assertTrue(full["browser"]["page_software_gl"])
        reports = [p for p in job.glob("**/render.json") if json.loads(p.read_text(encoding="utf-8")).get("output") == full["output"]]
        self.assertTrue(reports, "the full render's render.json")
        rep = json.loads(reports[0].read_text(encoding="utf-8"))
        rep["browser"]["page_software_gl"] = False          # as if the full render had been made with a GPU
        reports[0].write_text(json.dumps(rep), encoding="utf-8")
        sp = json.loads(showtime("render", proj, "--job", job, "--no-check", "--no-audio", "--workers", 1, "--gpu", "off",
                                 "--from", 1.0, "--to", 1.3, "--json").stdout)
        self.assertFalse(sp["browser"]["page_software_gl"], sp["browser"])
        self.assertTrue(sp["browser"]["software_gl"])
        self.assertEqual(colour(sp["output"], 1.1), "green", "the spliced frames draw as the full render did")


# the colour says what the page was told: red = no GPU, green = a GPU, blue = not told (gl.js probed)
GL_DECISION_HTML = """<!doctype html><html><head><script src="/_st/stage.js"></script></head>
<body style="margin:0;background:#000"><canvas id="c" width="256" height="144"></canvas>
<script type="module">import { softwareGL } from '/_st/effects/gl.js';
window.__told = !!window.__ST_RENDER__ && 'softwareGL' in window.__ST_RENDER__; window.__sw = softwareGL();</script>
<script>
const g = document.getElementById('c').getContext('2d');
ST.onSeek((t) => {
  g.fillStyle = !window.__told ? '#0000ff' : window.__sw ? '#ff0000' : '#00ff00'; g.fillRect(0, 0, 256, 144);
  g.fillStyle = '#fff'; g.fillRect((t * 40) % 120, 4, 6, 6);
});
</script></body></html>
"""


def colour(video, t):
    px = run_ff("-ss", "%.3f" % t, "-i", video, "-frames:v", "1", "-vf", "crop=8:8:60:40,scale=1:1", "-f", "rawvideo",
                "-pix_fmt", "rgb24", "-")
    r, g, b = px[0], px[1], px[2]
    return "red" if r > 150 and g < 90 else "green" if g > 150 and r < 90 else "blue" if b > 150 else "other %s" % ((r, g, b),)


@unittest.skipUnless(NODE, "Node.js is not installed")
class TestSoundtrackKey(unittest.TestCase):
    """The key changes with what the audio module reads beside the spec (review S2, P2)."""

    def test_key_follows_sidecars_catalog_queries_and_settings(self):
        tmp = Path(tempfile.mkdtemp(prefix="st-audiokey-"))
        try:
            proj, shared, music, hist = tmp / "proj", tmp / "shared", tmp / "music", tmp / "hist"
            for d in (proj / "audio", shared, music, hist):
                d.mkdir(parents=True)
            (shared / "bed.wav").write_bytes(b"RIFF fake wav")
            write(proj / "showtime.json", json.dumps({"duration": 3, "audio": "audio/mix.json"}))
            write(proj / "audio" / "mix.json", json.dumps({"tracks": [{"kind": "music", "file": "../../shared/bed.wav"}]}))
            write(proj / "audio" / "q.json", json.dumps({"tracks": [{"kind": "music", "catalog": {"use": "launch"}}]}))
            write(proj / "audio" / "id.json", json.dumps({"tracks": [{"kind": "music", "catalog": "some-track-id"}]}))
            js = """
import { audioKey } from '%(m)s';
import fs from 'node:fs';
const P = %(proj)s, S = %(shared)s, M = %(music)s;
const key = (aud) => audioKey({ projDir: P, aud, scoreFile: null, settings: { dur: 3 }, ffmpeg: null });
const out = {};
out.a = await key('audio/mix.json');
fs.writeFileSync(S + '/bed.wav.license.json', JSON.stringify({ license: 'CC-BY-4.0', attribution_required: true }));
out.lic = await key('audio/mix.json');
fs.writeFileSync(S + '/bed.words.json', '[]');
out.words = await key('audio/mix.json');
fs.writeFileSync(S + '/other.wav.license.json', '{}');
out.other = await key('audio/mix.json');
out.q1 = await key('audio/q.json'); out.id1 = await key('audio/id.json');
fs.writeFileSync(M + '/vetoes.json', JSON.stringify({ vetoed: { x: 1 } }));
out.q2 = await key('audio/q.json'); out.id2 = await key('audio/id.json');
process.env.SHOWTIME_LIBRARY = '/elsewhere';
out.lib = await key('audio/mix.json');
console.log(JSON.stringify(out));
""" % {"m": AUDIOCACHE, "proj": json.dumps(str(proj)), "shared": json.dumps(str(shared)), "music": json.dumps(str(music))}
            cp = subprocess.run([NODE, "--input-type=module", "-e", js], stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                                timeout=120, env=dict(ENV, SHOWTIME_MUSIC_CACHE=str(music), SHOWTIME_HISTORY_DIR=str(hist)))
            self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
            k = json.loads(cp.stdout.strip().splitlines()[-1])
            self.assertTrue(all(k.values()), k)
            self.assertNotEqual(k["a"], k["lic"], "a license sidecar beside a file outside the project changes the key")
            self.assertNotEqual(k["lic"], k["words"], "so does a word-timing sidecar")
            self.assertEqual(k["words"], k["other"], "another file's sidecar does not")
            self.assertNotEqual(k["q1"], k["q2"], "a catalog query depends on the vetoes")
            self.assertEqual(k["id1"], k["id2"], "a catalog id does not")
            self.assertNotEqual(k["other"], k["lib"], "SHOWTIME_LIBRARY is in the key")
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


@unittest.skipUnless(NODE, "Node.js is not installed")
class TestSoundtrackReuse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-audiocache-"))
        cls.proj = cls.tmp / "proj"
        write(cls.proj / "showtime.json", json.dumps({"width": 256, "height": 144, "fps": 10, "duration": 3, "poster": 0, "audio": "audio/tone.wav"}))
        write(cls.proj / "index.html", SLOW_TAIL_HTML % {"slow": 99})
        (cls.proj / "audio").mkdir()
        run_ff("-f", "lavfi", "-i", "sine=frequency=440:duration=3:sample_rate=48000", "-ac", "2", cls.proj / "audio" / "tone.wav")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def m4a(self, rep):
        return md5(Path(rep["output"]).parent / "final.work" / "audio" / "master.m4a")

    def test_reuse_and_invalidate(self):
        a, _ = render(self.proj, self.tmp / "a" / "final.mp4", "--workers", 1)
        self.assertFalse(a["audio"].get("reused"))
        b, cpb = render(self.proj, self.tmp / "b" / "final.mp4", "--workers", 1)
        self.assertTrue(b["audio"].get("reused"), b["audio"])
        self.assertIn("soundtrack reused", cpb.stderr)
        self.assertEqual(self.m4a(a), self.m4a(b))
        # the picture changes: the soundtrack is still the same
        write(self.proj / "index.html", (SLOW_TAIL_HTML % {"slow": 99}).replace("'#fff'", "'#0f0'"))
        c, _ = render(self.proj, self.tmp / "c" / "final.mp4", "--workers", 1)
        self.assertTrue(c["audio"].get("reused"))
        # an audio file changes: mixed again
        run_ff("-f", "lavfi", "-i", "sine=frequency=660:duration=3:sample_rate=48000", "-ac", "2", self.proj / "audio" / "tone.wav")
        d, _ = render(self.proj, self.tmp / "d" / "final.mp4", "--workers", 1)
        self.assertFalse(d["audio"].get("reused"))
        self.assertNotEqual(self.m4a(a), self.m4a(d))
        # another loudness target: mixed again
        e, _ = render(self.proj, self.tmp / "e" / "final.mp4", "--workers", 1, "--lufs", -16)
        self.assertFalse(e["audio"].get("reused"))
        # off
        f, _ = render(self.proj, self.tmp / "f" / "final.mp4", "--workers", 1, env=dict(ENV, SHOWTIME_AUDIO_CACHE="0"))
        self.assertFalse(f["audio"].get("reused"))


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + [a for a in sys.argv[1:] if a != "--fast"])

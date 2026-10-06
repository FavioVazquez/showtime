#!/usr/bin/env python3
"""QA smoke tests: every planted defect is caught ("prove it bites") and the clean template passes.

Real runs:
  * tests/fixtures/defects/<name>/ with tool "check": `showtime check` must report the rule at the
    stated severity (error/warning/info map to FAIL/WARN/INFO).
  * fixtures with tool "qa": the project is rendered small, then `showtime qa` on the MP4 must report it.
  * templates/dom rendered at 640x360 for 3 s must get a qa verdict without FAIL and a check without errors.
  * `showtime check --find-first` bisects to the right frame (frozen fixture, a page that turns
    nondeterministic at 1.2 s).
  * canvas films: Film.frameInfo() text is audited (contrast, off-frame) and listed in report.texts.
  * expect block, captions sidecar and review-pack on synthetic ffmpeg videos (no browser).

--fast (CI): skips everything that needs a browser; the ffmpeg-only tests still run.
Stdlib only. usage: python tests/test_qa.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
FIXTURES = TESTS_DIR / "fixtures" / "defects"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
SEV = {"error": "FAIL", "warning": "WARN", "info": "INFO"}
TIMES = {}


def showtime(*args, check=True, timeout=300, cwd=None):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def ffmpeg(*args):
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-y"] + [str(a) for a in args],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")


def synth_video(path, dur=4.0, size="640x360", tone=True, bt709=True):
    """Moving test pattern + tone, tagged and faststart like a showtime master."""
    args = ["-f", "lavfi", "-i", "testsrc2=s=%s:r=30:d=%s" % (size, dur)]
    if tone:
        args += ["-f", "lavfi", "-i", "sine=f=330:d=%s:sample_rate=48000" % dur]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast"]
    if bt709:
        args += ["-vf", "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv",
                 "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    if tone:   # a well-made master ends its sound with a fade (qa's abrupt_end otherwise)
        args += ["-af", "volume=7.8dB,afade=t=out:st=%g:d=0.6" % (float(dur) - 0.6), "-c:a", "aac", "-b:a", "192k",
                 "-shortest"]
    ffmpeg(*(args + ["-movflags", "+faststart", str(path)]))
    return path


def held_video(path, kind, sound=True, dur=9.0, fps=30, W=320, H=180):
    """A long hold that freezedetect reports. kind: "live" (camera footage of a speaker holding still:
    sensor noise everywhere, lips and blinks move), "grain" (a still card under a grain overlay) or
    "typing" (a still card where a few characters are typed)."""
    import numpy as np
    rng = np.random.default_rng(3)
    yy, xx = np.mgrid[0:H, 0:W]
    base = (70 + 40 * xx / W + 20 * yy / H).astype(np.float32)
    face = ((xx - 160) / 38.0) ** 2 + ((yy - 88) / 48.0) ** 2 < 1
    tex = np.where(face, rng.normal(0, 10, (H, W)), 0).astype(np.float32)
    base[face] = 170
    base += tex
    cmd = [ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-f", "rawvideo",
           "-pix_fmt", "gray", "-s", "%dx%d" % (W, H), "-r", str(fps), "-i", "-", "-f", "lavfi", "-i",
           ("aevalsrc=0.25*sin(2*PI*190*t)*(0.55+0.45*sin(2*PI*4*t)):s=48000:d=%g" % dur) if sound
           else "anullsrc=r=48000:cl=stereo:d=%g" % dur,
           "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac", "-shortest",
           str(path)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for i in range(int(dur * fps)):
        t = i / fps
        f = base.copy()
        if kind == "live":
            f[(np.abs(xx - 160) < 22) & (np.abs(yy - 114) < 2 + 6 * abs(np.sin(t * 9)))] = 150
            f[((np.abs(xx - 142) < 8) | (np.abs(xx - 178) < 8)) & (np.abs(yy - 76) < (1 if (i // 7) % 5 == 0 else 4))] = 150
            f += rng.normal(0, 1.6, (H, W))
        elif kind == "grain":
            f += rng.normal(0, 1.6, (H, W))
        elif kind == "typing":
            f[150:160, 100:100 + 4 * int(t * 3)] = 240
        if t >= dur - 1:
            f = 255 - f                     # the last second cuts away: the hold is inside the video
        p.stdin.write(np.clip(f, 0, 255).astype(np.uint8).tobytes())
    err = p.communicate()[1]
    assert p.returncode == 0, err.decode("utf-8", "replace")
    return path


def defects():
    out = []
    for d in sorted(FIXTURES.iterdir()):
        if d.is_dir() and (d / "DEFECT.json").is_file():
            out.append((d, json.loads((d / "DEFECT.json").read_text(encoding="utf-8"))))
    return out


def findings_of(rep, key):
    return [(f.get(key), SEV.get(f.get("severity"), f.get("severity"))) for f in rep["findings"]]


class QATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-qa-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def copy_fixture(self, src):
        dst = self.tmp / "fx" / src.name
        if dst.exists():
            shutil.rmtree(str(dst))
        shutil.copytree(str(src), str(dst))
        return dst

    # ------------------------------------------------------------------ CLI
    def test_01_help(self):
        for cmd in (["qa"], ["review-pack"], ["check"]):
            cp = showtime(*(cmd + ["--help"]))
            self.assertIn("usage:", cp.stdout)
            self.assertIn("example", cp.stdout)
        self.assertIn("--find-first", showtime("check", "--help").stdout)
        cp = showtime("qa", self.tmp / "nope.mp4", check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("video not found", cp.stderr)
        self.assertNotIn("Traceback", cp.stderr)
        cp = showtime("check", self.copy_fixture(FIXTURES / "low-contrast"), "--find-first", "sparkles", check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("unknown --find-first probe", cp.stderr)

    def test_02_fixture_inventory(self):
        """Every fixture declares a known tool, a rule and a severity; the required set exists."""
        names = {d.name for d, _ in defects()}
        for want in ("black-first-frame", "text-outside-safe-zone", "low-contrast", "clipping-audio",
                     "unseeded-random", "realtime-timer", "missing-font", "system-font", "overflow-text",
                     "frozen-segment", "silent-gap", "missing-credits", "clipped-text", "choppy-launch"):
            self.assertIn(want, names)
        for d, spec in defects():
            self.assertIn(spec["tool"], ("check", "qa"), d.name)
            self.assertIn(spec["severity"], ("FAIL", "WARN", "INFO"), d.name)
            self.assertTrue(spec.get("rule") and spec.get("why"), d.name)
            self.assertTrue((d / "showtime.json").is_file() and (d / "index.html").is_file(), d.name)

    # ------------------------------------------------------- page-level defects
    def test_03_check_catches_each_defect(self):
        if FAST:
            self.skipTest("--fast (needs a browser)")
        for src, spec in defects():
            if spec["tool"] != "check":
                continue
            with self.subTest(fixture=src.name):
                proj = self.copy_fixture(src)
                t0 = time.time()
                cp = showtime("check", proj, "--json", *spec.get("check_args", []), check=False, timeout=240)
                TIMES["check " + src.name] = round(time.time() - t0, 1)
                rep = json.loads(cp.stdout)
                got = findings_of(rep, "code")
                self.assertIn((spec["rule"], spec["severity"]), got, "%s: %s" % (src.name, got))
                if spec["severity"] == "FAIL":
                    self.assertEqual(cp.returncode, 1, src.name)

    # ------------------------------------------------------- file-level defects
    def test_04_qa_catches_each_defect(self):
        if FAST:
            self.skipTest("--fast (renders in a browser)")
        for src, spec in defects():
            if spec["tool"] != "qa":
                continue
            with self.subTest(fixture=src.name):
                proj = self.copy_fixture(src)
                out = self.tmp / "renders"
                t0 = time.time()
                cp = showtime("render", proj, "--out-dir", out, "--json", *spec.get("render_args", []), timeout=300)
                video = Path(json.loads(cp.stdout)["output"])
                cp = showtime("qa", video, "--json", check=False)
                TIMES["render+qa " + src.name] = round(time.time() - t0, 1)
                rep = json.loads(cp.stdout)
                got = findings_of(rep, "rule")
                self.assertIn((spec["rule"], spec["severity"]), got, "%s: %s" % (src.name, got))
                f = next(x for x in rep["findings"] if x["rule"] == spec["rule"])
                if f.get("t") is not None:
                    self.assertTrue(f.get("frame") and Path(f["frame"]).is_file(), f)
                self.assertTrue(Path(rep["sheet"]).is_file())
                self.assertEqual(cp.returncode, 1 if rep["verdict"] == "FAIL" else 0)
                self.assertEqual(rep["verdict"] == "FAIL", spec["severity"] == "FAIL" or rep["summary"]["fail"] > 0)

    # ------------------------------------------------------- the clean template passes
    def test_05_clean_template_passes(self):
        if FAST:
            self.skipTest("--fast (renders in a browser)")
        proj = self.tmp / "clean-dom"
        showtime("new", "dom", proj, "--width", 640, "--height", 360, "--duration", 3)
        t0 = time.time()
        cp = showtime("render", proj, "--out-dir", self.tmp / "clean-out", "--poster", 2, "--json", timeout=300)
        video = Path(json.loads(cp.stdout)["output"])
        cp = showtime("qa", video, "--json", check=False)
        rep = json.loads(cp.stdout)
        TIMES["render+qa clean dom"] = round(time.time() - t0, 1)
        fails = [f for f in rep["findings"] if f["severity"] == "FAIL"]
        self.assertEqual(fails, [], fails)
        self.assertEqual(cp.returncode, 0)
        self.assertIn(rep["verdict"], ("PASS", "WARN"))
        self.assertTrue(rep["probe"]["faststart"])
        self.assertAlmostEqual(rep["loudness"]["integrated_lufs"], -14.0, delta=1.0)
        cp = showtime("check", proj, "--json", "--no-timeline", "--samples", "3", check=False)
        errors = [f for f in json.loads(cp.stdout)["findings"] if f["severity"] == "error"]
        self.assertEqual(errors, [], errors)
        self.__class__.clean_job = video.parent
        # the qa run was recorded in the job ledger (render folders adopt one)
        led = json.loads((video.parent / "job.json").read_text(encoding="utf-8"))
        self.assertIn(led["qa"]["verdict"], ("PASS", "WARN"))

    def test_06_review_pack(self):
        job = getattr(self.__class__, "clean_job", None)
        if job is None:
            job = self.tmp / "rp-job"
            job.mkdir(exist_ok=True)
            synth_video(job / "final.mp4", dur=4)
            (job / "render.json").write_text(json.dumps({"output": str(job / "final.mp4"), "duration": 4.0}), encoding="utf-8")
        cp = showtime("review-pack", job, "--json")
        m = json.loads(cp.stdout)
        pack = Path(m["dir"])
        self.assertEqual(pack.name, "round-1")
        for name in ("CRITIC.md", "sheet.jpg", "manifest.json", "qa/qa.json", "loudness.png"):
            self.assertTrue((pack / name).is_file(), name)
        brief = (pack / "CRITIC.md").read_text(encoding="utf-8")
        for word in ("Blocker", "Should-fix", "Polish", "VERDICT", "DECLINED TO JUDGE", "timestamp", "at most 3",
                     "No scores", "WOULD I POST THIS", "under your own name"):
            self.assertIn(word, brief)
        self.assertTrue(all(Path(k["path"]).is_file() for k in m["key_frames"]))
        self.assertIn("type detail pass", brief)
        self.assertIn("text_crops", m)
        self.assertTrue(all(Path(c["path"]).is_file() for c in m["text_crops"]))
        self.assertFalse((pack / "text-frames").exists(), "the full-size source frames are removed")
        self.assertFalse((pack / "INCOMPLETE").exists())
        # no FINDINGS.md yet: the next pack rebuilds round 1 instead of using up a round
        self.assertEqual(Path(json.loads(showtime("review-pack", job, "--json").stdout)["dir"]).name, "round-1")
        (pack / "FINDINGS.md").write_text("VERDICT: ship after fixes\n", encoding="utf-8")
        r2 = Path(json.loads(showtime("review-pack", job, "--json").stdout)["dir"])
        self.assertEqual(r2.name, "round-2")
        self.assertIn("round-1/FINDINGS.md", (r2 / "CRITIC.md").read_text(encoding="utf-8").replace("\\", "/"))
        # an interrupted round 2 (no FINDINGS.md) is rebuilt, never counted
        (r2 / "INCOMPLETE").write_text("x", encoding="utf-8")
        self.assertEqual(Path(json.loads(showtime("review-pack", job, "--json").stdout)["dir"]).name, "round-2")
        (r2 / "FINDINGS.md").write_text("VERDICT: ship after fixes\n", encoding="utf-8")
        r3 = Path(json.loads(showtime("review-pack", job, "--json").stdout)["dir"])
        self.assertEqual(r3.name, "round-3")
        (r3 / "FINDINGS.md").write_text("VERDICT: ship\n", encoding="utf-8")
        cp = showtime("review-pack", job, check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("stops at 3", cp.stderr)
        self.assertIn("--compare", cp.stderr)

    def test_06b_text_crops(self):
        """The type detail pass: the tallest text line of a frame is found and cut out at full size;
        a big circle outline and a thin rule are not text; a line held in place is cropped once."""
        from PIL import Image, ImageDraw
        from st.qa import images, textcrops
        d = self.tmp / "textcrops"
        d.mkdir(exist_ok=True)
        im = Image.new("RGB", (1920, 1080), (12, 10, 9))
        dr = ImageDraw.Draw(im)
        dr.ellipse((150, 200, 850, 900), outline=(110, 140, 255), width=6)
        dr.line((100, 1000, 1800, 1000), fill=(200, 200, 200), width=4)
        dr.text((1000, 420), "Why pi r2?", font=images.font(110), fill=(245, 240, 230))
        dr.text((1000, 700), "rings 8", font=images.font(40), fill=(200, 196, 190))
        src = d / "frame.png"
        im.save(src)
        lines = textcrops.find_lines(src, 3)
        self.assertGreaterEqual(len(lines), 2, lines)
        x, y, w, h = lines[0]["box"]
        self.assertTrue(990 <= x <= 1010 and 420 <= y <= 470 and w > 400, lines[0])
        self.assertTrue(all(l["box"][1] < 950 for l in lines), "the rule is not a text line")
        out = textcrops.crops([(0.0, "frame 0", src), (1.5, "hook", src)], d / "frames")
        self.assertEqual([c["t"] for c in out], [0.0, 0.0], "the same line on a later frame is not repeated")
        with Image.open(out[0]["path"]) as c0:
            self.assertGreater(c0.size[0], w, "cropped at full size with padding")

    # ------------------------------------------------------- bisection
    def test_07_find_first(self):
        if FAST:
            self.skipTest("--fast (needs a browser)")
        proj = self.copy_fixture(FIXTURES / "frozen-segment")
        cp = showtime("check", proj, "--find-first", "frozen", "--json", check=False)
        self.assertEqual(cp.returncode, 1, cp.stderr)
        r = json.loads(cp.stdout)
        self.assertTrue(r["found"])
        self.assertAlmostEqual(r["t"], 1.5, delta=1.5 / 24)   # the pause starts at 1.5 s (24 fps)
        self.assertAlmostEqual(r["end"], 4.5, delta=2.5 / 24)
        self.assertTrue(Path(r["images"]["bad"]).is_file())
        # a page that becomes nondeterministic at 1.2 s (a real-time timer only drives the late part)
        proj = self.tmp / "late-timer"
        proj.mkdir(exist_ok=True)
        (proj / "showtime.json").write_text(json.dumps({"width": 320, "height": 180, "fps": 30, "duration": 3}), encoding="utf-8")
        (proj / "index.html").write_text("""<!doctype html><html><head><script src="/_st/stage.js"></script>
<style>html,body{margin:0;background:#111;overflow:hidden}#b{position:absolute;top:60px;width:40px;height:40px;background:#fc0}</style>
</head><body><div id="b"></div><script>
let wall = 0; setInterval(() => { wall = (wall + 13) % 260; }, 7);
ST.onSeek((t) => { document.getElementById('b').style.left = (t < 1.2 ? 20 + t * 50 : wall) + 'px'; });
</script></body></html>""", encoding="utf-8")
        cp = showtime("check", proj, "--find-first", "nondeterministic", "--json", check=False)
        r = json.loads(cp.stdout)
        self.assertTrue(r["found"], r)
        self.assertAlmostEqual(r["t"], 1.2, delta=2.5 / 30)
        cp = showtime("check", self.copy_fixture(FIXTURES / "low-contrast"), "--find-first", "black", "--json", check=False)
        self.assertEqual(cp.returncode, 0)
        self.assertFalse(json.loads(cp.stdout)["found"])

    # ------------------------------------------------------- canvas films
    def test_08_canvas_film_audits(self):
        if FAST:
            self.skipTest("--fast (needs a browser)")
        proj = self.tmp / "film-defects"
        proj.mkdir(exist_ok=True)
        (proj / "showtime.json").write_text(json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 2}), encoding="utf-8")
        (proj / "index.html").write_text("""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="/_lib/@fontsource-variable/inter/index.css">
<script src="/_st/stage.js"></script><script src="/_st/film.js"></script></head><body><script>
Film.start({ look: 'dark', design: [1920, 1080], scenes(T, g, F) {
  F.text('Bright headline', 160, 300, { size: 110, weight: 800, color: '#ffffff' });
  F.text('A quiet grey note nobody can read', 160, 600, { size: 56, color: '#262a33' });
  F.text('Cut off at the edge', 1250, 900, { size: 120, weight: 800, color: '#ffffff' });
}});
</script></body></html>""", encoding="utf-8")
        cp = showtime("check", proj, "--json", "--no-timeline", "--samples", "2", check=False)
        rep = json.loads(cp.stdout)
        got = {(f["code"], f.get("source")) for f in rep["findings"]}
        self.assertIn(("low_contrast", "canvas"), got, rep["findings"])
        self.assertIn(("text_off_canvas", "canvas"), got, rep["findings"])
        self.assertNotIn("Bright headline", " ".join(f["message"] for f in rep["findings"]))
        self.assertIn("Bright headline", [t["text"] for t in rep["texts"]])

    # ------------------------------------------------------- expect block + captions (ffmpeg only)
    def test_09_expect_block(self):
        proj = self.tmp / "expect-proj"
        proj.mkdir(exist_ok=True)
        (proj / "index.html").write_text("<p>Acme ships v2</p>", encoding="utf-8")
        (proj / "showtime.json").write_text(json.dumps({
            "width": 640, "height": 360, "fps": 30, "duration": 4,
            "expect": {"duration": 10, "tolerance": 0.5, "platform": "reels", "must_show": ["Acme ships v2", "Nonexistent claim"],
                       "captions": True}}), encoding="utf-8")
        video = synth_video(self.tmp / "expect.mp4", dur=4)
        cp = showtime("qa", video, "--project", proj, "--json", check=False)
        self.assertEqual(cp.returncode, 1)
        rep = json.loads(cp.stdout)
        got = findings_of(rep, "rule")
        for want in (("duration", "FAIL"), ("aspect", "WARN"), ("must_show", "FAIL"), ("must_show_unverified", "WARN"),
                     ("captions_missing", "WARN")):
            self.assertIn(want, got)
        # a check report listing the on-screen texts turns "unverified" into verified
        (proj / "work" / "check").mkdir(parents=True, exist_ok=True)
        time.sleep(0.05)
        (proj / "work" / "check" / "report.json").write_text(json.dumps({"texts": [
            {"text": "Acme ships v2", "first": 0.5, "last": 3.0, "source": "dom", "caption": False}]}), encoding="utf-8")
        ex = self.tmp / "expect.json"
        ex.write_text(json.dumps({"expect": {"duration": 4, "must_show": [{"text": "acme SHIPS v2", "at": 1.0}], "lufs": -14}}), encoding="utf-8")
        cp = showtime("qa", video, "--project", proj, "--expect", ex, "--json", check=False)
        rep = json.loads(cp.stdout)
        self.assertNotIn("must_show", [f["rule"] for f in rep["findings"]], rep["findings"])
        self.assertNotIn("duration", [f["rule"] for f in rep["findings"]])
        self.assertTrue(any("must_show" in p for p in rep["passed"]), rep["passed"])

    def test_10_file_rules_and_captions(self):
        # untagged, no faststart, no audio, odd captions
        bad = self.tmp / "plain.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
               "-preset", "veryfast", str(bad))
        srt = self.tmp / "plain.srt"
        srt.write_text("1\n00:00:00,500 --> 00:00:02,000\nThis caption line is far too long to read comfortably on a phone\n\n"
                       "2\n00:00:02,500 --> 00:00:05,000\nRuns past the end\n", encoding="utf-8")
        cp = showtime("qa", bad, "--json", check=False)
        rep = json.loads(cp.stdout)
        got = findings_of(rep, "rule")
        for want in (("no_audio", "WARN"), ("color_tags", "WARN"), ("faststart", "WARN"), ("captions_past_end", "FAIL"),
                     ("caption_line_long", "WARN")):
            self.assertIn(want, got)
        self.assertEqual(cp.returncode, 1)
        # a well-made synthetic master passes everything that applies to it
        gdir = self.tmp / "good"
        gdir.mkdir(exist_ok=True)
        good = synth_video(gdir / "master.mp4", dur=4)
        cp = showtime("qa", good, "--json", check=False)
        rep = json.loads(cp.stdout)
        self.assertEqual([f for f in rep["findings"] if f["severity"] != "INFO"], [], rep["findings"])
        self.assertEqual(rep["verdict"], "PASS")
        self.assertTrue(Path(rep["sheet"]).is_file())
        # --strict turns WARN into a failing exit code
        cp = showtime("qa", bad, "--strict", "--no-sheet", check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("verdict: FAIL", cp.stdout)

    # ------------------------------------------------------- which file / which platform
    def test_11_latest_pointer_and_platform(self):
        """qa and review-pack follow the job's latest render (not final.mp4); the platform comes from
        --platform, then showtime.json, then job.json; credits.txt is found in either case."""
        base = self.tmp / "latest"
        base.mkdir()
        job = Path(json.loads(showtime("job", "init", "qa-latest-probe", "--platform", "reels", "--json", cwd=base).stdout)["job"])
        synth_video(job / "final.mp4", dur=2, size="360x640")
        time.sleep(1.1)
        synth_video(job / "final-2.mp4", dur=4, size="360x640")
        showtime("job", "note", job, "--output", "final=%s" % (job / "final-2.mp4"), cwd=base)
        # a job name: its latest final, with the platform from job.json
        cp = showtime("qa", "qa-latest-probe", "--json", "--no-sheet", cwd=base, check=False)
        rep = json.loads(cp.stdout)
        self.assertEqual(Path(rep["video"]).name, "final-2.mp4")
        self.assertIn("using %s (latest final)" % (job / "final-2.mp4"), cp.stderr)
        self.assertEqual((rep["target"] or {}).get("name"), "reels")
        self.assertEqual(rep["target"]["source"], "job.json")
        self.assertNotIn("too_short", [f["rule"] for f in rep["findings"]])  # final.mp4 (2 s) would be too short for reels
        # no argument inside the job folder: same file; the text output names the platform source
        cp = showtime("qa", "--no-sheet", cwd=job / "work", check=False)
        self.assertIn("final-2.mp4", cp.stderr)
        self.assertIn("platform  reels (from job.json)", cp.stdout)
        # an explicit older file is checked as asked, with a note about the newer one
        cp = showtime("qa", job / "final.mp4", "--no-sheet", cwd=base, check=False)
        self.assertIn("not the latest final", cp.stderr)
        self.assertIn("final.mp4", cp.stdout.splitlines()[0])
        # --platform beats job.json; showtime.json "platform" beats job.json
        rep = json.loads(showtime("qa", job, "--platform", "youtube", "--json", "--no-sheet", cwd=base, check=False).stdout)
        self.assertEqual((rep["target"]["name"], rep["target"]["source"]), ("youtube", "--platform"))
        proj = base / "proj"
        proj.mkdir()
        (proj / "showtime.json").write_text(json.dumps({"width": 360, "height": 640, "fps": 30, "duration": 4,
                                                        "platform": "shorts"}), encoding="utf-8")
        rep = json.loads(showtime("qa", job, "--project", proj, "--json", "--no-sheet", cwd=base, check=False).stdout)
        self.assertEqual((rep["target"]["name"], rep["target"]["source"]), ("shorts", "showtime.json"))
        # a video outside any job with no platform anywhere: generic checks, and the text says how to add one
        solo = synth_video(self.tmp / "solo.mp4", dur=2)
        cp = showtime("qa", solo, "--no-sheet", check=False)
        self.assertIn("platform  none", cp.stdout)
        self.assertIn("--platform", showtime("qa", "--help").stdout)
        # credits: lowercase, upper-case and <stem>.credits.txt all count
        from st.qa import video as qv
        cdir = self.tmp / "credits"
        cdir.mkdir()
        v = cdir / "final-2.mp4"
        v.write_bytes(b"x")
        self.assertIsNone(qv.find_credits(v))
        (cdir / "CREDITS.txt").write_text("a", encoding="utf-8")
        self.assertEqual(qv.find_credits(v).name.lower(), "credits.txt")
        (cdir / "final-2.credits.txt").write_text("b", encoding="utf-8")
        self.assertEqual(qv.find_credits(v).name, "final-2.credits.txt")
        # review-pack of the job reviews the latest render and reads the poster time from <video>.work/render.json
        wk = job / "final-2.work"
        wk.mkdir()
        (wk / "render.json").write_text(json.dumps({"output": str(job / "final-2.mp4"),
                                                    "poster": {"file": str(job / "final-2.poster.jpg"), "time": 2.5}}),
                                        encoding="utf-8")
        cp = showtime("review-pack", "qa-latest-probe", "--json", cwd=base)
        m = json.loads(cp.stdout)
        self.assertEqual(Path(m["video"]).name, "final-2.mp4")
        self.assertIn("poster", [k["label"] for k in m["key_frames"]])
        self.assertIn("(latest final)", cp.stderr)

    def test_12_render_into_job(self):
        """render --job / -o inside a job: credits.txt next to the video, latest pointers in job.json,
        a re-render moves them to final-2.mp4, and qa of the job checks that file."""
        if FAST:
            self.skipTest("--fast (renders in a browser)")
        base = self.tmp / "render-job"
        base.mkdir()
        proj = base / "proj"
        proj.mkdir()
        (proj / "showtime.json").write_text(json.dumps({"width": 320, "height": 180, "fps": 30, "duration": 1,
                                                        "poster": 0.5}), encoding="utf-8")
        (proj / "index.html").write_text(
            "<!doctype html><html><head><script src=\"/_st/stage.js\"></script></head>"
            "<body style=\"margin:0;background:#234;color:#fff;font:48px sans-serif\"><div id=t>0</div>"
            "<script>ST.onSeek(function(t){document.getElementById('t').textContent=t.toFixed(2)})</script></body></html>",
            encoding="utf-8")
        (proj / "CREDITS.txt").write_text("Credits\n\nThis video uses the following third-party material:\n\n"
                                          "- \"Test Bed\" by A. Person (CC BY 4.0)\n", encoding="utf-8")
        job = Path(json.loads(showtime("job", "init", "render-into-job", "--json", cwd=base).stdout)["job"])
        t0 = time.time()
        r1 = json.loads(showtime("render", proj, "--job", "render-into-job", "--workers", 1, "--json", cwd=base).stdout)
        # compare real paths: on Windows one side can be the 8.3 short form (C:/Users/RUNNER~1/...)
        same = lambda a, b: self.assertEqual(Path(a).resolve(), Path(b).resolve())
        same(r1["output"], job / "final.mp4")
        same(r1["credits"], job / "credits.txt")
        self.assertIn("Test Bed", (job / "credits.txt").read_text(encoding="utf-8"))
        same(r1["poster"]["file"], job / "poster.jpg")
        self.assertTrue(r1["poster"]["baked"])
        r2 = json.loads(showtime("render", proj, "--job", job, "--workers", 1, "--json", cwd=base).stdout)
        self.assertEqual(Path(r2["output"]).name, "final-2.mp4")
        self.assertEqual(Path(r2["credits"]).name, "final-2.credits.txt")
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual({k: Path(v).name for k, v in data["outputs"].items()},
                         {"final": "final-2.mp4", "poster": "final-2.poster.jpg", "credits": "final-2.credits.txt"})
        # -o inside the job (a subfolder) also records itself; a name that is not final*/preview* (a second
        # aspect, a bumper, an alpha overlay) is logged as a variant and never becomes the latest (17.5/19.9/20.11)
        r3 = json.loads(showtime("render", proj, "-o", job / "exports" / "square.mp4", "--preview", "--workers", 1,
                                 "--json", cwd=base).stdout)
        self.assertEqual(Path(r3["job"]), job)
        self.assertIn("does not start with", r3.get("job_variant") or "")
        self.assertTrue((job / "exports" / "square.credits.txt").is_file())
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertNotIn("preview", data["outputs"])
        self.assertTrue(any(o.get("variant") == "preview" and Path(o["path"]).name == "square.mp4" for o in data["output_log"]))
        self.assertEqual(Path(data["outputs"]["final"]).name, "final-2.mp4")
        cp = showtime("qa", "render-into-job", "--json", "--no-sheet", cwd=base, check=False)
        rep = json.loads(cp.stdout)
        self.assertEqual(Path(rep["video"]).name, "final-2.mp4")
        self.assertNotIn("missing_credits", [f["rule"] for f in rep["findings"]])
        cp = showtime("render", proj, "--job", "no-such-job-here", cwd=base, check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("no job named", cp.stderr)
        TIMES["render into job x3 + qa"] = round(time.time() - t0, 1)

    # ------------------------------------------------------- round 3: size, upscale, captions pointer, scenes, deliver
    def test_13_resolution_and_upscale(self):
        """P1: a preview-size file for a platform WARNs `resolution`; P2: an edit that enlarged its source
        more than 1.5x WARNs `upscale` (read from the edit render report, also for a poster-baked copy)."""
        d = self.tmp / "res"
        d.mkdir()
        small = synth_video(d / "small.mp4", dur=2, size="360x640")
        rep = json.loads(showtime("qa", small, "--platform", "reels", "--json", "--no-sheet", check=False).stdout)
        res = [f for f in rep["findings"] if f["rule"] == "resolution"]
        self.assertEqual([f["severity"] for f in res], ["WARN"])
        self.assertIn("1080x1920", res[0]["message"])
        full = synth_video(d / "full.mp4", dur=1, size="1080x1920")
        rep = json.loads(showtime("qa", full, "--platform", "reels", "--json", "--no-sheet", check=False).stdout)
        self.assertNotIn("resolution", [f["rule"] for f in rep["findings"]])
        # upscale from the edit render report
        cut = d / "cut.mp4"
        shutil.copy2(str(small), str(cut))
        (d / "cut.report.json").write_text(json.dumps({
            "output": str(cut), "edl": str(d / "edl.json"),
            "segments": [{"i": 0, "source": "talk", "out_start": 0.0}, {"i": 1, "source": "talk", "out_start": 1.0}],
            "segment_meta": [{"upscale": {"factor": 2.67, "detail": "1280x720 source -> 1080x1920 frame, fit cover"}},
                             {"upscale": {"factor": 1.2}}]}), encoding="utf-8")
        rep = json.loads(showtime("qa", cut, "--json", "--no-sheet", check=False).stdout)
        up = [f for f in rep["findings"] if f["rule"] == "upscale"]
        self.assertEqual(len(up), 1)
        self.assertIn("2.67x", up[0]["message"])
        shutil.copy2(str(small), str(d / "cut.poster.mp4"))
        rep = json.loads(showtime("qa", d / "cut.poster.mp4", "--json", "--no-sheet", check=False).stdout)
        self.assertIn("upscale", [f["rule"] for f in rep["findings"]])

    def test_14_job_captions_pointer(self):
        """ROUND2: qa of a job's latest final (a baked final.poster.mp4) also checks the job's captions pointer."""
        base = self.tmp / "cap-ptr"
        base.mkdir()
        job = Path(json.loads(showtime("job", "init", "cap-ptr", "--json", cwd=base).stdout)["job"])
        synth_video(job / "final.mp4", dur=2)
        (job / "final.srt").write_text("1\n00:00:00,500 --> 00:00:05,000\nTHIS CAPTION RUNS PAST THE END\n", encoding="utf-8")
        shutil.copy2(str(job / "final.mp4"), str(job / "final.poster.mp4"))
        showtime("job", "note", job, "--output", "final=%s" % (job / "final.poster.mp4"),
                 "--output", "captions=%s" % (job / "final.srt"), cwd=base)
        cp = showtime("qa", "cap-ptr", "--json", "--no-sheet", cwd=base, check=False)
        rep = json.loads(cp.stdout)
        self.assertEqual(Path(rep["video"]).name, "final.poster.mp4")
        self.assertIn(str((job / "final.srt").resolve()), rep["captions"])
        self.assertTrue(any(f["rule"].startswith("caption") and Path(f.get("file", "")).name == "final.srt"
                            for f in rep["findings"]), rep["findings"])
        # a file that is not the job's latest video does not pick up the pointer
        synth_video(job / "older-cut.mp4", dur=2)
        rep = json.loads(showtime("qa", job / "older-cut.mp4", "--json", "--no-sheet", cwd=base, check=False).stdout)
        self.assertEqual(rep["captions"], [])

    def test_15_review_pack_uses_planned_scenes(self):
        """S12: review-pack takes scene starts from the project's clips (not the pixel cut detector, which finds
        nothing in a transition-joined render), and CRITIC.md carries the eight judging questions."""
        base = self.tmp / "planned"
        base.mkdir()
        proj = base / "proj"
        proj.mkdir()
        (proj / "showtime.json").write_text(json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 3}), encoding="utf-8")
        (proj / "index.html").write_text(
            '<!doctype html><body><section id="intro" data-start="0" data-dur="1"><h1 data-start="0.2">Hi</h1></section>'
            '<section id="middle" data-start="#intro" data-dur="1" data-transition="push left 0.5"></section>'
            '<section id="outro" data-start="#middle" data-dur="1"></section></body>', encoding="utf-8")
        job = Path(json.loads(showtime("job", "init", "planned", "--json", cwd=base).stdout)["job"])
        synth_video(job / "final.mp4", dur=3)
        (job / "final.work").mkdir()
        (job / "final.work" / "render.json").write_text(json.dumps({"output": str(job / "final.mp4"), "project": str(proj),
                                                                     "range": [0, 3]}), encoding="utf-8")
        showtime("job", "note", job, "--output", "final=%s" % (job / "final.mp4"), cwd=base)
        cp = showtime("review-pack", "planned", cwd=base)
        self.assertIn("3 scenes, 2 cuts, from the project's clips (data-start)", cp.stdout)
        m = json.loads((Path(cp.stdout.strip().splitlines()[-1]) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["cuts"], [1.0, 2.0])
        self.assertEqual(m["scenes"], [[0.0, 1.0], [1.0, 2.0], [2.0, 3.0]])
        self.assertTrue(any("(middle)" in f["label"] for f in m["scene_frames"]))
        brief = (Path(m["dir"]) / "CRITIC.md").read_text(encoding="utf-8")
        for q in ("Hook: at 1.5 s", "Clarity:", "Readability:", "Craft:", "Distinctness:", "Poster:", "Honesty:", "Story logic:"):
            self.assertIn(q, brief)
        # 0.4.0: the first-viewer pass gets the parts in order with their middle frames and narration
        for word in ("First-viewer pass", "story.txt", "transcript.txt", "FIRST VIEWER", "how it connects to what"):
            self.assertIn(word, brief)
        story = (Path(m["dir"]) / "story.txt").read_text(encoding="utf-8")
        self.assertIn("part 1  0.00-1.00s  (intro)  frame: `frames/", story)
        self.assertIn("part 3  2.00-3.00s  (outro)", story)
        self.assertIn("no narration transcript", story)
        self.assertTrue((Path(m["dir"]) / "transcript.txt").is_file())
        # every frame around each cut (2 before .. 4 after), and a variant in the job is named, not packed
        self.assertTrue(Path(m["cut_strips"]).is_file())
        self.assertEqual(len(list((Path(m["dir"]) / "cut-frames").glob("*.jpg"))), 14)
        shutil.copy2(str(job / "final.mp4"), str(job / "final-16x9.mp4"))
        (job / "final.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")
        (Path(m["dir"]) / "FINDINGS.md").write_text("VERDICT: ship\n", encoding="utf-8")
        m2 = json.loads(showtime("review-pack", "planned", "--json", cwd=base).stdout)
        self.assertEqual([Path(x).name for x in m2["not_in_pack"]], ["final-16x9.mp4"])
        self.assertIn("Not in this pack", (Path(m2["dir"]) / "CRITIC.md").read_text(encoding="utf-8"))
        self.assertTrue(any(Path(c).name == "final.srt" for c in m2["context"]), m2["context"])
        story = (Path(m2["dir"]) / "story.txt").read_text(encoding="utf-8")
        part1 = story.split("part 2")[0]
        self.assertIn("Hi", part1)                                # the line said during part 1, in part 1
        self.assertIn("Narration from its caption file .srt", story)
        self.assertIn("Hi", (Path(m2["dir"]) / "transcript.txt").read_text(encoding="utf-8"))
        # 10: the pack carries the packed video's own mix report, not another mix's report in <job>/work
        (job / "work").mkdir(exist_ok=True)
        (job / "work" / "mix.report.json").write_text(json.dumps({"which": "side mix"}), encoding="utf-8")
        (job / "final.work" / "audio").mkdir(parents=True, exist_ok=True)
        (job / "final.work" / "audio" / "mix.report.json").write_text(json.dumps({"which": "own"}), encoding="utf-8")
        (Path(m2["dir"]) / "FINDINGS.md").write_text("VERDICT: ship\n", encoding="utf-8")
        m3 = json.loads(showtime("review-pack", "planned", "--json", "--force-round", cwd=base).stdout)
        mr = json.loads((Path(m3["dir"]) / "context" / "mix.report.json").read_text(encoding="utf-8"))
        self.assertEqual(mr["which"], "own")
        # scene labels keep accented letters (Inter, not the bitmap fallback)
        from st.qa import images
        self.assertNotIn("ImageFont.ImageFont", repr(type(images.font(13))))
        # no project, no EDL report: the detector is still the fallback
        from st.qa import review
        self.assertIsNone(review.planned_scenes(job / "final.mp4", None, 3.0))

    def test_16_deliver_job_pointers_and_bake_once(self):
        """ROUND2: deliver commands take a job; poster --bake records final=<baked> and poster=, and a second
        bake of an already-baked file (by deliver or by render) is skipped."""
        base = self.tmp / "deliver-job"
        base.mkdir()
        job = Path(json.loads(showtime("job", "init", "dj", "--json", cwd=base).stdout)["job"])
        synth_video(job / "final.mp4", dur=3, size="320x180")
        showtime("job", "note", job, "--output", "final=%s" % (job / "final.mp4"), cwd=base)
        cp = showtime("deliver", "poster", "dj", "--bake", "--at", "1", "--json", cwd=base)
        self.assertIn("(latest final)", cp.stderr)
        r = json.loads(cp.stdout)
        baked = job / "final.poster.mp4"
        self.assertEqual(Path(r["bake"]["output"]).resolve(), baked.resolve())
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(data["outputs"]["final"]).name, "final.poster.mp4")
        self.assertEqual(Path(data["outputs"]["poster"]).name, "final.poster.png")
        self.assertAlmostEqual(list(data["baked"].values())[0], 1.0)
        # baked once: the job's latest final is the baked file; asking again does nothing
        cp = showtime("deliver", "poster", "dj", "--bake", cwd=base)
        self.assertIn("nothing to do", cp.stderr)
        self.assertEqual(Path(cp.stdout.strip()).resolve(), baked.resolve())
        self.assertFalse((job / "final.poster-2.mp4").exists())
        # a different time bakes again, into a new file (never overwrites)
        showtime("deliver", "poster", "dj", "--bake", "--at", "2", cwd=base)
        self.assertTrue((job / "final.poster-2.mp4").is_file())
        # render already baked the showtime.json poster: detected from render.json
        solo = base / "solo"
        solo.mkdir()
        v = synth_video(solo / "final.mp4", dur=2, size="320x180")
        (solo / "render.json").write_text(json.dumps({"output": str(v), "poster": {"time": 1.5, "baked": True}}),
                                          encoding="utf-8")
        cp = showtime("deliver", "poster", v, "--bake", cwd=base)
        self.assertIn("already frame 0", cp.stderr)
        self.assertFalse((solo / "final.poster.mp4").exists())
        # thumb and exports accept the job too (its latest final)
        cp = showtime("deliver", "thumb", "dj", "--size", "320x180", cwd=base)
        self.assertTrue(Path(cp.stdout.strip()).is_file())
        self.assertIn("final.poster-2", Path(cp.stdout.strip()).name)
        cp = showtime("deliver", "exports", "dj", "--targets", "square", "--preview", "--json", cwd=base)
        ex = json.loads(cp.stdout)
        self.assertEqual(Path(ex["input"]).name, "final.poster-2.mp4")
        self.assertTrue(Path(ex["exports"][0]["output"]).is_file())

    def test_17_shared_limits_with_writers_and_check(self):
        """ROUND3: qa reads the caption limits from st.captions_rules and the hold thresholds from
        runtime/thresholds.json, the same sources the caption writers and `showtime check` use."""
        from st import captions_rules as R
        from st.qa import captions as Q
        from st.qa import video as V
        # timing thresholds: the file check.mjs and retime read, with the literals only as a fallback
        self.assertEqual(V.THRESHOLDS_FILE.resolve(), (SKILL / "runtime" / "thresholds.json").resolve())
        doc = json.loads(V.THRESHOLDS_FILE.read_text(encoding="utf-8"))
        th = V.thresholds()
        for k in ("still_hold_s", "final_hold_max_s", "frozen_fail_s"):
            self.assertEqual(th[k], float(doc[k]), k)
        alt = self.tmp / "thresholds-alt.json"
        alt.write_text(json.dumps(dict(doc, still_hold_s=3.25)), encoding="utf-8")
        saved = V.THRESHOLDS_FILE
        try:
            V.THRESHOLDS_FILE = alt
            self.assertEqual(V.thresholds()["still_hold_s"], 3.25)
            V.THRESHOLDS_FILE = self.tmp / "missing.json"
            self.assertEqual(V.thresholds()["still_hold_s"], 2.5)
        finally:
            V.THRESHOLDS_FILE = saved
        # caption limits: the checker follows the shared module (patch it and qa moves with it)
        for wh in ((1080, 1920), (1920, 1080), (1080, 1350)):
            self.assertEqual(Q.safe_box(*wh), R.safe_box(*wh))
        cap = {"cues": [{"start": 0.0, "end": 1.0, "text": "one two three four five six", "lines": ["x" * 34]}]}
        rules = lambda: {f["rule"] for f in Q.check(cap, 5, 1080, 1920)}  # noqa: E731
        self.assertEqual(rules() & {"caption_line_long", "caption_fast"}, {"caption_line_long", "caption_fast"})
        old = (R.MAX_LINE_CHARS_VERTICAL, R.MAX_CPS)
        try:
            R.MAX_LINE_CHARS_VERTICAL, R.MAX_CPS = 40, 30.0
            self.assertFalse(rules() & {"caption_line_long", "caption_fast"})
        finally:
            R.MAX_LINE_CHARS_VERTICAL, R.MAX_CPS = old
        src = (SKILL / "lib" / "st" / "qa" / "captions.py").read_text(encoding="utf-8")
        self.assertNotIn("32 if vertical else 42", src)

    def test_18_size_capped_export_and_poster_flash(self):
        """deliver exports --max-mb lands under the cap at the master's size (two-pass), github/chat/web
        exist as targets, and qa WARNs poster_flash when frame 0 differs sharply from frame 1."""
        d = self.tmp / "capped"
        d.mkdir()
        src = d / "master.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=4", "-f", "lavfi", "-i", "sine=f=330:d=4:sample_rate=48000",
               "-c:v", "libx264", "-crf", "8", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src))
        self.assertGreater(src.stat().st_size, 1_000_000)
        rep = json.loads(showtime("deliver", "exports", src, "--targets", "original", "--max-mb", "0.6", "--out-dir", d / "ex",
                                  "--json").stdout)
        r = rep["exports"][0]
        self.assertEqual(Path(r["output"]).name, "master.0.6mb.mp4")
        self.assertEqual((r["width"], r["height"]), (640, 360))
        self.assertLessEqual(Path(r["output"]).stat().st_size, 600_000)
        self.assertGreater(Path(r["output"]).stat().st_size, 300_000)   # it used the budget, not a tiny file
        # the export never runs past the picture: audio longer than the video is cut at the video's end
        long_src = d / "long.mp4"
        ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3", "-f", "lavfi", "-i", "sine=f=330:d=3.25:sample_rate=48000",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(long_src))
        lr = json.loads(showtime("deliver", "exports", long_src, "--targets", "original", "--max-mb", "0.4", "--out-dir", d / "lx",
                                 "--json").stdout)["exports"][0]
        from st import ff as FF
        lp = FF.probe(lr["output"])
        self.assertAlmostEqual(lp["video_duration"], 3.0, delta=0.01)
        self.assertLessEqual(lp["audio_streams"][0]["duration"], lp["video_duration"] + 1 / 30.0)
        self.assertLessEqual(lp["duration"], 3.0 + 1 / 30.0)
        from st.deliver import exports as X
        self.assertTrue({"original", "github", "chat", "web"} <= set(X.TARGETS))
        self.assertNotIn("github", [t.name for t in X.parse_targets("all")])
        self.assertEqual(X.TARGETS["web"].audio, False)
        # a padded export records where the picture sits; qa judges black/frozen inside it
        sq = json.loads(showtime("deliver", "exports", src, "--targets", "square", "--fit", "pad", "--preview",
                                 "--out-dir", d / "sq", "--json").stdout)["exports"][0]
        self.assertEqual(sq["picture"], [0, 236, 1080, 608])
        side = json.loads(Path(sq["output"] + ".export.json").read_text(encoding="utf-8"))
        self.assertEqual(side["fit"], "pad")
        q = json.loads(showtime("qa", sq["output"], "--json", "--no-sheet", check=False).stdout)
        self.assertEqual(q["detect"]["picture"], [0, 236, 1080, 608])
        # poster flash: a bright frame 0 over a dark opening
        flash = d / "flash.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=c=white:s=320x180:r=30:d=0.033", "-f", "lavfi", "-i", "color=c=0x202020:s=320x180:r=30:d=2",
               "-filter_complex", "[1:v]drawbox=x=40:y=40:w=80:h=60:c=red:t=fill[b];[0:v][b]concat=n=2:v=1[v]", "-map", "[v]",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(flash))
        q = json.loads(showtime("qa", flash, "--json", "--no-sheet", check=False).stdout)
        self.assertIn(("poster_flash", "WARN"), findings_of(q, "rule"))
        q = json.loads(showtime("qa", src, "--json", "--no-sheet", check=False).stdout)
        self.assertNotIn("poster_flash", [f["rule"] for f in q["findings"]])

    # ------------------------------------------------------- batch 2: which sidecars, verdicts per file, exports
    def test_19_sidecars_belong_to_their_video(self):
        """22.7/22.17/21.9: in a job only <stem>.* sidecars (plus the job's captions pointer for its latest
        final, same aspect) are checked; --captions replaces auto-discovery; 21.10: every fast cue is listed;
        an ASS vector drawing (a caption plate) is not a cue."""
        base = self.tmp / "sidecars"
        base.mkdir()
        job = Path(json.loads(showtime("job", "init", "sidecars", "--json", cwd=base).stdout)["job"])
        synth_video(job / "final.mp4", dur=2, size="640x360")
        (job / "final.srt").write_text("1\n00:00:00,500 --> 00:00:05,000\nTHE 16:9 CUT RUNS PAST THE END\n", encoding="utf-8")
        (job / "captions.srt").write_text("1\n00:00:00,500 --> 00:00:09,000\nNOT FOR THE SHORT\n", encoding="utf-8")
        showtime("job", "note", job, "--output", "final=%s" % (job / "final.mp4"),
                 "--output", "captions=%s" % (job / "final.srt"), cwd=base)
        short = synth_video(job / "shorts-9x16.mp4", dur=2, size="360x640")
        rep = json.loads(showtime("qa", short, "--json", "--no-sheet", cwd=base, check=False).stdout)
        self.assertEqual(rep["captions"], [])
        self.assertFalse([f for f in rep["findings"] if f["rule"].startswith("caption")], rep["findings"])
        # --captions replaces what would be found: the short's own file only
        own = job / "work" / "short.srt"
        own.parent.mkdir(exist_ok=True)
        own.write_text("1\n00:00:00,100 --> 00:00:01,500\nThe short's own line\n", encoding="utf-8")
        rep = json.loads(showtime("qa", short, "--captions", own, "--json", "--no-sheet", cwd=base, check=False).stdout)
        self.assertEqual([Path(c).name for c in rep["captions"]], ["short.srt"])
        # the latest final still gets the job's pointer (and not captions.srt)
        rep = json.loads(showtime("qa", "sidecars", "--json", "--no-sheet", cwd=base, check=False).stdout)
        self.assertEqual([Path(c).name for c in rep["captions"]], ["final.srt"])
        # a 9:16 made the latest final by hand: the 16:9 pointer is not checked against it
        showtime("job", "note", job, "--output", "final=%s" % short, cwd=base)
        cp = showtime("qa", "sidecars", "--json", "--no-sheet", cwd=base, check=False)
        self.assertEqual(json.loads(cp.stdout)["captions"], [])
        self.assertIn("made for another aspect", showtime("qa", "sidecars", "--no-sheet", cwd=base, check=False).stderr)
        # a missing --captions file is a clear error
        cp = showtime("qa", short, "--captions", job / "nope.srt", "--no-sheet", cwd=base, check=False)
        self.assertEqual(cp.returncode, 1)
        self.assertIn("caption file not found", cp.stderr)
        # every fast cue in one run (not only the first)
        from st.qa import captions as Q
        fast = "\n".join("%d\n00:00:%02d,000 --> 00:00:%02d,600\nthis cue has far too many words for its time\n" % (i + 1, i * 2, i * 2)
                         for i in range(3))
        (base / "fast.srt").write_text(fast, encoding="utf-8")
        found = [f for f in Q.check(Q.parse(base / "fast.srt"), 30, 1920, 1080) if f["rule"] == "caption_fast"]
        self.assertEqual([f["t"] for f in found], [0.0, 2.0, 4.0])
        self.assertIn("(1 of 3 fast cues)", found[0]["message"])
        ass = base / "plate.ass"
        ass.write_text("[Script Info]\nPlayResX: 640\nPlayResY: 360\n\n[V4+ Styles]\nFormat: Name, Fontsize, Alignment, MarginV\n"
                       "Style: Cap,40,2,40\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                       "Dialogue: 0,0:00:00.00,0:00:01.00,Cap,,0,0,0,,{\\an7\\pos(0,0)\\p1}m 0 0 l 100 0 100 50 0 50{\\p0}\n"
                       "Dialogue: 1,0:00:00.00,0:00:01.00,Cap,,0,0,0,,Hello there\n", encoding="utf-8")
        cues = Q.parse(ass)["cues"]
        self.assertEqual([c["text"] for c in cues], ["Hello there"])

    def test_20_verdict_per_file_and_capped_export(self):
        """14.11/16.9: qa of an export keeps the latest final's verdict (per-file records); 15.1: a size-capped
        platform accepts the master when a capped export exists (INFO naming the qa command), else FAIL with the
        exact export command; 21.11: review-pack --lufs, and it reuses the last qa --lufs of the file."""
        base = self.tmp / "perfile"
        base.mkdir()
        job = Path(json.loads(showtime("job", "init", "perfile", "--json", cwd=base).stdout)["job"])
        synth_video(job / "final.mp4", dur=3, size="320x180")
        showtime("job", "note", job, "--output", "final=%s" % (job / "final.mp4"), cwd=base)
        showtime("qa", "perfile", "--no-sheet", "--lufs", "-16", cwd=base, check=False)
        (job / "exports").mkdir()
        shutil.copy2(str(job / "final.mp4"), str(job / "exports" / "final.chat.mp4"))
        showtime("qa", job / "exports" / "final.chat.mp4", "--no-sheet", cwd=base, check=False)
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(data["qa"]["video"]).name, "final.mp4")
        self.assertEqual({Path(k).name for k in data["qa_files"]}, {"final.mp4", "final.chat.mp4"})
        st = json.loads(showtime("status", "perfile", "--json", cwd=base).stdout)
        self.assertNotIn("has not been checked", st["next"])
        self.assertTrue(any("final.chat.mp4" in v["text"] for v in data["verified"]) or
                        data["qa_files"][str((job / "exports" / "final.chat.mp4").resolve())]["verdict"] == "FAIL")
        # review-pack judges loudness like the last qa of the file (--lufs -16), or as asked
        m = json.loads(showtime("review-pack", "perfile", "--json", cwd=base).stdout)
        q = json.loads(Path(m["qa"]["report"]).read_text(encoding="utf-8"))
        self.assertEqual(q["loudness"]["target_lufs"], -16.0)
        (Path(m["dir"]) / "FINDINGS.md").write_text("VERDICT: ship\n", encoding="utf-8")
        m = json.loads(showtime("review-pack", "perfile", "--lufs", "-23", "--json", cwd=base).stdout)
        self.assertEqual(json.loads(Path(m["qa"]["report"]).read_text(encoding="utf-8"))["loudness"]["target_lufs"], -23.0)
        # size cap (in-process: no 10 MB file needed)
        from st.qa import video as V
        F = V.Findings()
        V._check_platform(F, V.target_for("github"), {}, 3.0, 320, 180, 12_000_000, job / "final.mp4")
        f = [x for x in F.items if x["rule"] == "file_size"][0]
        self.assertEqual(f["severity"], "FAIL")
        self.assertIn("showtime deliver exports %s --targets github" % (job / "final.mp4"), f["fix"])
        shutil.copy2(str(job / "final.mp4"), str(job / "exports" / "final.github.mp4"))
        F = V.Findings()
        V._check_platform(F, V.target_for("github"), {}, 3.0, 320, 180, 12_000_000, job / "final.mp4")
        f = [x for x in F.items if x["rule"] == "file_size"][0]
        self.assertEqual(f["severity"], "INFO")
        self.assertIn("showtime qa %s --platform github" % (job / "exports" / "final.github.mp4"), f["fix"])

    def test_21_review_scenes_skip_overlays(self):
        """13.4/16.7/19.12: overlay clips are not scenes; 18.4: every `key: number` pair in CUE counts;
        showtime.json chapters and a film's acts come before DOM clips."""
        from st.qa import review
        d = self.tmp / "scenes"
        d.mkdir()
        (d / "index.html").write_text(
            '<div id="stage"><div id="a" data-start="0" data-dur="4"></div><div id="b" data-start="4" data-dur="4"></div>'
            '<div id="kicker" data-start="1" data-dur="2"></div><div id="map" data-start="0.5"></div>'
            '<div id="c" data-start="8"></div></div>', encoding="utf-8")
        self.assertEqual(review._clip_scenes(d), [(0.0, "a"), (4.0, "b"), (8.0, "c")])
        (d / "index.html").write_text('<section class="scene" id="s1" data-start="0" data-dur="3"></section>'
                                      '<section class="scene" id="s2" data-start="3" data-dur="3"></section>'
                                      '<div class="lower-third" data-start="1" data-dur="4"></div>', encoding="utf-8")
        self.assertEqual(review._clip_scenes(d), [(0.0, "s1"), (3.0, "s2")])
        (d / "cues.js").write_text("const CUE = {\n  open: 0, title: 2.5,\n  burnAt: 8.171, burnDur: 0.8, arrive: 8.571,\n};\n"
                                   "CUE.acts = [[CUE.open, 'Open'], [CUE.title, 'Title'], [CUE.arrive, 'Arrive']];\n",
                                   encoding="utf-8")
        self.assertEqual(review._cue_scenes(d), [(0.0, "Open"), (2.5, "Title"), (8.571, "Arrive")])
        (d / "showtime.json").write_text(json.dumps({"chapters": [[0, "Intro"], {"t": 5, "label": "Demo"}]}), encoding="utf-8")
        v = synth_video(d / "v.mp4", dur=10, size="320x180")
        pl = review.planned_scenes(v, d, 10.0)
        self.assertEqual((pl["source"], pl["scenes"]), ("showtime.json chapters", [(0.0, "Intro"), (5.0, "Demo")]))
        (d / "showtime.json").write_text("{}", encoding="utf-8")
        self.assertEqual(review.planned_scenes(v, d, 10.0)["source"], "the film's CUE.acts")


    # ------------------------------------------------------- final pass: talking heads are not frozen pictures
    def test_22_held_camera_shot_is_not_frozen(self):
        """A speaker holding still (camera noise everywhere + lips/blinks) with sound is a held_shot INFO, not a
        frozen FAIL; without sound it is a WARN. A still card under grain, a card where a few characters are typed,
        and any hold in a project whose page plays no <video> stay frozen FAILs."""
        d = self.tmp / "held"
        d.mkdir()

        def frozen(rep):
            return [(f["rule"], f["severity"]) for f in rep["findings"] if f["rule"] in ("frozen", "held_shot")]

        live = held_video(d / "talking.mp4", "live")
        rep = json.loads(showtime("qa", live, "--json", "--no-sheet", check=False).stdout)
        self.assertEqual(frozen(rep), [("held_shot", "INFO")], rep["findings"])
        self.assertTrue(rep["detect"]["live"][0]["live"], rep["detect"])
        mute = held_video(d / "talking-mute.mp4", "live", sound=False)
        rep = json.loads(showtime("qa", mute, "--json", "--no-sheet", check=False).stdout)
        self.assertEqual(frozen(rep), [("frozen", "WARN")], rep["findings"])
        for kind in ("grain", "typing"):
            v = held_video(d / ("%s.mp4" % kind), kind)
            rep = json.loads(showtime("qa", v, "--json", "--no-sheet", check=False).stdout)
            self.assertIn(("frozen", "FAIL"), frozen(rep), (kind, rep["findings"]))
            self.assertFalse(any(x["live"] for x in rep["detect"].get("live", [])), (kind, rep["detect"]))
        # the same live picture rendered from a motion-graphics project (no <video> on the page) is frozen
        proj = d / "mg"
        proj.mkdir()
        (proj / "showtime.json").write_text(json.dumps({"duration": 9}), encoding="utf-8")
        (proj / "index.html").write_text('<div id="stage"><h1 data-start="0" data-dur="9">Hello</h1></div>', encoding="utf-8")
        rep = json.loads(showtime("qa", live, "--project", proj, "--json", "--no-sheet", check=False).stdout)
        self.assertIn(("frozen", "FAIL"), frozen(rep), rep["findings"])
        (proj / "index.html").write_text('<div id="stage"><video src="talk.mp4" data-start="0" data-dur="9"></video></div>',
                                         encoding="utf-8")
        rep = json.loads(showtime("qa", live, "--project", proj, "--json", "--no-sheet", check=False).stdout)
        self.assertEqual(frozen(rep), [("held_shot", "INFO")], rep["findings"])

    def test_23_review_pack_cuts_inside_chapters(self):
        """Chapters are navigation: review-pack adds the project's clip starts and the cuts seen in the picture
        that fall inside a chapter, so each gets its frame strip (a 4-clip page with 2 chapters has 3 cuts)."""
        d = self.tmp / "chapcuts"
        proj = d / "proj"
        proj.mkdir(parents=True)
        (proj / "showtime.json").write_text(json.dumps({"width": 320, "height": 180, "fps": 30, "duration": 10,
                                                        "chapters": [[0, "Intro"], [5, "Requests"]]}), encoding="utf-8")
        (proj / "index.html").write_text(
            '<!doctype html><body><div id="stage"><div id="open" data-start="0" data-dur="2.5"></div>'
            '<div id="r1" data-start="2.5" data-dur="2.5"></div><div id="r2" data-start="5" data-dur="2.5"></div>'
            '<div id="r3" data-start="7.5" data-dur="2.5"></div></div></body>', encoding="utf-8")
        v = d / "cuts.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=c=0x301010:s=320x180:r=30:d=2.5", "-f", "lavfi", "-i", "color=c=0xd0d0f0:s=320x180:r=30:d=2.5",
               "-f", "lavfi", "-i", "color=c=0x103020:s=320x180:r=30:d=2.5", "-f", "lavfi", "-i", "color=c=0xf0e060:s=320x180:r=30:d=2.5",
               "-f", "lavfi", "-i", "sine=f=330:d=10:sample_rate=48000",
               "-filter_complex", "[0:v][1:v][2:v][3:v]concat=n=4:v=1[v]", "-map", "[v]", "-map", "4:a",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(v))
        m = json.loads(showtime("review-pack", v, "--project", proj, "--json", timeout=600).stdout)
        self.assertEqual(m["cuts"], [2.5, 5.0, 7.5], m["scenes_source"])
        self.assertIn("showtime.json chapters", m["scenes_source"])
        self.assertTrue(any("(r1)" in f["label"] for f in m["scene_frames"]), [f["label"] for f in m["scene_frames"]])
        self.assertEqual(len(list((Path(m["dir"]) / "cut-frames").glob("*.jpg"))), 21)      # 7 frames x 3 cuts
        # a page whose clips do not say where the cuts are: the picture does
        (proj / "index.html").write_text('<!doctype html><body><div id="stage"></div></body>', encoding="utf-8")
        (Path(m["dir"]) / "FINDINGS.md").write_text("VERDICT: fix\n", encoding="utf-8")
        m = json.loads(showtime("review-pack", v, "--project", proj, "--json", timeout=600).stdout)
        self.assertEqual(m["cuts"], [2.5, 5.0, 7.5], m["scenes_source"])
    def test_24_footage_job_ignores_its_cards_subproject(self):
        """A footage job's edit render is judged by its own edit report, not by the job's cards/ sub-project
        (a 5.5 s showtime.json duration must not fail a 3 s edit without --expect)."""
        base = self.tmp / "footagejob"
        base.mkdir()
        job = Path(json.loads(showtime("job", "init", "talk", "--json", cwd=base).stdout)["job"])
        cards = job / "cards"
        cards.mkdir()
        (cards / "showtime.json").write_text(json.dumps({"duration": 5.5, "fps": 30}), encoding="utf-8")
        (cards / "index.html").write_text("<!doctype html><body></body>", encoding="utf-8")
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        data["project"] = str(cards)
        (job / "job.json").write_text(json.dumps(data), encoding="utf-8")
        # the cards' own render.json names another output
        (job / "render.json").write_text(json.dumps({"project": str(cards), "output": str(job / "cards.mp4"),
                                                     "duration": 5.5}), encoding="utf-8")
        v = synth_video(job / "final.mp4", dur=3, size="640x360")
        (job / "final.report.json").write_text(json.dumps({"output": str(v), "edl": str(job / "edit" / "edl.json"),
                                                           "duration": 3.0}), encoding="utf-8")
        q = json.loads(showtime("qa", v, "--json", "--no-sheet", check=False).stdout)
        self.assertNotIn(("duration", "FAIL"), findings_of(q, "rule"))
        self.assertIsNone(q["project"])
        self.assertTrue(any("edit render report" in p for p in q["passed"]), q["passed"])
        # the edit report's length is still checked
        (job / "final.report.json").write_text(json.dumps({"output": str(v), "edl": "edl.json", "duration": 6.0}),
                                               encoding="utf-8")
        q = json.loads(showtime("qa", v, "--json", "--no-sheet", check=False).stdout)
        self.assertIn(("duration", "FAIL"), findings_of(q, "rule"))

    def test_25_poster_still_matches_its_frame(self):
        """qa compares the render's poster still with its video frame (mean luma) and flags PNG colour chunks."""
        import struct
        import zlib
        from st.qa import media as M
        d = self.tmp / "posters"
        d.mkdir()
        v = d / "final.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=c=0x606870:s=320x180:r=30:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(v))
        poster = d / "poster.png"
        ffmpeg("-ss", "1", "-i", v, "-frames:v", "1", poster)
        (d / "render.json").write_text(json.dumps({"output": str(v), "duration": 2,
                                                   "poster": {"file": "poster.png", "time": 1.0}}), encoding="utf-8")
        rules = lambda: [f["rule"] for f in json.loads(  # noqa: E731
            showtime("qa", v, "--json", "--no-sheet", check=False).stdout)["findings"]]
        self.assertEqual(M.png_colour_chunks(poster), [])
        self.assertNotIn("poster_mismatch", rules())
        # a darker still (taken from another frame or another grade)
        ffmpeg("-ss", "1", "-i", v, "-frames:v", "1", "-vf", "eq=brightness=-0.08", poster)
        self.assertIn("poster_mismatch", rules())
        # the same pixels with a gAMA chunk: a browser draws it darker than the video
        ffmpeg("-ss", "1", "-i", v, "-frames:v", "1", poster)
        raw = poster.read_bytes()
        body = b"gAMA" + struct.pack(">I", 45455)
        chunk = struct.pack(">I", 4) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        poster.write_bytes(raw[:33] + chunk + raw[33:])                      # right after the IHDR chunk
        self.assertEqual(M.png_colour_chunks(poster), ["gAMA"])
        self.assertIn("poster_mismatch", rules())
        # deliver poster writes PNGs without them (the same strip)
        self.assertEqual(M.strip_png_colour_chunks(poster), 1)
        self.assertEqual(M.png_colour_chunks(poster), [])
        self.assertEqual(poster.read_bytes(), raw)
        self.assertNotIn("poster_mismatch", rules())


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    t0 = time.time()
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    res = prog.result
    n = res.testsRun - len(res.skipped)
    print("\n%d checks passed, %d skipped in %.1fs" % (n - len(res.failures) - len(res.errors), len(res.skipped), time.time() - t0))
    for k, v in TIMES.items():
        print("  %-40s %5.1fs" % (k, v))
    sys.exit(0 if res.wasSuccessful() else 1)

#!/usr/bin/env python3
"""Span renders (`render --from/--to`): spliced into the job's full video, or a clearly named span clip.

  * units (no browser): the Annex B access-unit parser, keyframe ranges, the capture split, a byte splice
    of two x264 streams that decodes frame for frame; `latest_video`, the render.json fallback, `adopt` and
    review never pick a span clip (also the pre-0.3.0 final-2.mp4 whose range starts after 0); `job note
    --render-base` writes `spliced` on the output entry and `spliced_from` on the render; the receipt counts it
  * splice (real renders): a job with a full render, the project fixed inside 2.2-2.8 s, then
    `render --from 2.2 --to 2.8 --job` writes final-2.mp4 with the same frame count and length; frames outside
    the re-rendered GOPs are the old render's frames byte for byte (decoded hashes), frames inside match a full
    render of the fixed project and not their neighbours (frame-exact seams), the fix is visible, the audio is
    as long as the video and at -14 LUFS; the ledger records it as the latest final, spliced from final.mp4, and
    the receipt counts a partial render. Other encode settings (--crf 18) fall back to one whole encode; a new
    poster time re-renders frame 0's GOP and bakes it like a full render
  * span clips: no full render in the job -> <job>/work/span-1-2.mp4 (never final*), a changed length -> a span
    and `showtime qa <job>` still checks final.mp4, no job -> span-*.mp4 in a new folder that has no final,
    -o final.mp4 -> span beside it, -o clip.mp4 as given, a range covering the whole video -> an ordinary final

Stdlib only. usage: python tests/test_splice.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import os
import re
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
SPLICE_MJS = SKILL / "scripts" / "lib" / "splice.mjs"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402
from st.job import ledger  # noqa: E402

ENV = build_env(showtime_home())
ENV.pop("SHOWTIME_OUT", None)
ENV["SHOWTIME_OFFLINE"] = "1"
NODE = shutil.which("node", path=ENV.get("PATH")) or shutil.which("node")

W, H, FPS, DUR = 256, 144, 30, 6
TOTAL = FPS * DUR


def showtime(*args, check=True, cwd=None, timeout=600):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def run_ff(*args, out=True):
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-y"] + [str(a) for a in args],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")[-2000:]
    return cp.stdout


def node(code):
    cp = subprocess.run([NODE, "--input-type=module", "-e", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding="utf-8", timeout=120, env=ENV)
    assert cp.returncode == 0, cp.stderr[-2000:]
    return json.loads(cp.stdout)


def probe(path):
    cp = subprocess.run([ff.ffprobe_path(), "-v", "error", "-count_packets", "-show_streams", "-show_format", "-of", "json",
                         str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=120)
    assert cp.returncode == 0, cp.stderr
    j = json.loads(cp.stdout)
    v = [s for s in j["streams"] if s["codec_type"] == "video"][0]
    a = [s for s in j["streams"] if s["codec_type"] == "audio"]
    return {"frames": int(v["nb_read_packets"]), "duration": float(j["format"]["duration"]), "width": v["width"],
            "height": v["height"], "fps": v["avg_frame_rate"], "color": (v.get("color_space"), v.get("color_range")),
            "audio": float(a[0]["duration"]) if a else None}


def frame_hashes(path):
    """md5 of every decoded frame, in order."""
    txt = run_ff("-i", path, "-map", "0:v:0", "-f", "framemd5", "-").decode()
    return [ln.split(",")[-1].strip() for ln in txt.splitlines() if ln and not ln.startswith("#")]


def gray_frames(path, w=64, h=36):
    """Every frame as a small grayscale byte string (for frame-by-frame comparisons)."""
    raw = run_ff("-i", path, "-map", "0:v:0", "-vf", "scale=%d:%d:flags=area,format=gray" % (w, h), "-f", "rawvideo", "-")
    n = w * h
    return [raw[i:i + n] for i in range(0, len(raw), n)]


def mad(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / float(len(a))


def pixel(path, n, x, y):
    raw = run_ff("-i", path, "-vf", "select=eq(n\\,%d),crop=4:4:%d:%d,scale=1:1:flags=area,format=rgb24" % (n, x, y),
                 "-frames:v", "1", "-f", "rawvideo", "-")
    return tuple(raw[:3])


def loudness(path):
    cp = subprocess.run([ff.ffmpeg_path(), "-nostdin", "-hide_banner", "-i", str(path), "-vn", "-af",
                         "ebur128=peak=true:framelog=quiet", "-f", "null", "-"], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=120)
    t = cp.stderr[cp.stderr.rfind("Summary:"):]
    return float(re.search(r"I:\s*(-?[\d.]+) LUFS", t).group(1)), float(re.search(r"Peak:\s*(-?[\d.]+)", t).group(1))


def write_project(d, color="#e02020", duration=DUR, extra=None):
    """A page where every frame differs (a striped band moving 16 px per frame) and one box that shows only
    from 2.2 to 2.8 s: the "fix" changes its colour. A tone makes the soundtrack."""
    d.mkdir(parents=True, exist_ok=True)
    (d / "audio").mkdir(exist_ok=True)
    tone = d / "audio" / "tone.wav"
    if not tone.is_file():
        run_ff("-f", "lavfi", "-i", "sine=frequency=330:duration=%d:sample_rate=44100" % DUR, "-af", "volume=-20dB", tone)
    cfg = {"width": W, "height": H, "fps": FPS, "duration": duration, "audio": [{"file": "audio/tone.wav", "fade_out": 0.2}]}
    cfg.update(extra or {})
    (d / "showtime.json").write_text(json.dumps(cfg), encoding="utf-8")
    (d / "index.html").write_text(
        "<!doctype html><html><head><script src=\"/_st/stage.js\"></script><style>"
        "body{margin:0;background:#12203a}"
        "#band{position:absolute;left:0;top:0;width:%dpx;height:40px;"
        "background:repeating-linear-gradient(90deg,#ffe066 0 10px,#12203a 10px 20px);"
        "background-position:calc(var(--st-t) * 500px) 0}"
        "#mover{position:absolute;top:50px;left:calc(var(--st-p) * 200px);width:40px;height:80px;background:#8fd}"
        "#fix{position:absolute;left:160px;top:70px;width:80px;height:60px;background:%s}"
        "</style></head><body><div id=\"band\"></div><div id=\"mover\"></div>"
        "<div id=\"fix\" data-start=\"2.2\" data-dur=\"0.6\"></div></body></html>" % (W, color), encoding="utf-8")
    return d


def new_job(slug, cwd):
    cp = showtime("job", "init", slug, "--goal", "splice test", "--json", cwd=cwd)
    return Path(json.loads(cp.stdout)["job"])


def render(proj, *args, cwd=None):
    cp = showtime("render", proj, "--json", "--no-check", *args, cwd=cwd)
    return json.loads(cp.stdout), cp


# --------------------------------------------------------------------------- units (no browser)

@unittest.skipUnless(NODE, "Node.js is not installed")
class TestSpliceUnits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-splice-u-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def enc(self, name, src, extra=()):
        out = self.tmp / name
        run_ff("-f", "lavfi", "-i", src, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-bf", "0", "-g", "30",
               "-pix_fmt", "yuv420p", *extra, out)
        run_ff("-i", out, "-c:v", "copy", "-bsf:v", "h264_mp4toannexb", "-f", "h264", out.with_suffix(".h264"))
        return out

    def test_access_units_and_byte_splice(self):
        a = self.enc("a.mp4", "testsrc2=s=160x90:r=30:d=4")
        b = self.enc("b.mp4", "testsrc2=s=160x90:r=30:d=4,negate")
        out = self.tmp / "joined.mp4"
        r = node("""
import * as S from %s;
const a = S.readStream(%s), b = S.readStream(%s);
const idr = S.idrFrames(a.aus);
const [s, e] = S.gopRange(idr, a.aus.length, 40, 50);
// b's frames 30-60 as a stream of their own: its access units from its own IDR at 30
const seg = { buf: b.buf, aus: b.aus.slice(s, e), params: b.params };
S.joinStreams(a, [{ range: [s, e], stream: seg }], a.aus.length, %s);
await S.muxAnnexB(%s, 30, null, %s);
console.log(JSON.stringify({ n: a.aus.length, idr, range: [s, e], same: S.sameParamSets(a.params, b.params),
  merged: S.mergeRanges([[60, 120], [0, 60], [1, 2], [130, 131], [5, 5]]),
  split: S.splitPlan([[0, 60], [60, 61], [100, 160]], 3), gop0: S.gopRange(idr, 120, 0, 1), end: S.gopRange(idr, 120, 100, 120) }));
""" % tuple(json.dumps(str(x)) for x in (SPLICE_MJS.as_uri(), a.with_suffix(".h264"), b.with_suffix(".h264"),
                                         self.tmp / "joined.h264", self.tmp / "joined.h264", out)))
        self.assertEqual(r["n"], 120)
        self.assertEqual(r["idr"], [0, 30, 60, 90])
        self.assertEqual(r["range"], [30, 60])
        self.assertTrue(r["same"], "same encoder settings, same size: the same SPS/PPS")
        self.assertEqual(r["merged"], [[0, 120], [130, 131]])
        self.assertEqual(r["split"], [[[0, 41]], [[41, 60], [60, 61], [100, 121]], [[121, 160]]])
        self.assertEqual((r["gop0"], r["end"]), ([0, 30], [90, 120]))
        ha, hb, hj = frame_hashes(a), frame_hashes(b), frame_hashes(out)
        self.assertEqual(len(hj), 120)
        self.assertEqual(hj[:30], ha[:30])
        self.assertEqual(hj[30:60], hb[30:60], "the spliced GOP decodes exactly as in its own stream")
        self.assertEqual(hj[60:], ha[60:])
        p = probe(out)
        self.assertEqual((p["frames"], p["fps"]), (120, "30/1"))
        self.assertAlmostEqual(p["duration"], 4.0, delta=0.001)
        c = self.enc("c.mp4", "testsrc2=s=160x90:r=30:d=1", ("-crf", "30"))
        r = node("import * as S from %s; console.log(JSON.stringify(S.sameParamSets(S.readStream(%s).params, S.readStream(%s).params)));"
                 % (json.dumps(SPLICE_MJS.as_uri()), json.dumps(str(a.with_suffix(".h264"))), json.dumps(str(c.with_suffix(".h264")))))
        self.assertFalse(r, "another CRF changes the PPS: the streams cannot be joined")

    def fake_job(self, slug):
        d = self.tmp / "showtime-out" / ("%s-20260929-120000" % slug)
        d.mkdir(parents=True)
        return d

    def test_latest_video_never_picks_a_span(self):
        job = self.fake_job("spans")
        full = job / "final.mp4"
        full.write_bytes(b"full")
        (job / "final.work").mkdir()
        (job / "final.work" / "render.json").write_text(json.dumps({"output": str(full), "range": [0, 6], "kind": "full"}))
        time.sleep(0.05)
        # a pre-0.3.0 span render named final-2.mp4 (range starts after 0), and a 0.3.0 span clip in the root
        legacy = job / "final-2.mp4"
        legacy.write_bytes(b"span")
        (job / "final-2.work").mkdir()
        (job / "final-2.work" / "render.json").write_text(json.dumps({"output": str(legacy), "range": [2.2, 2.8], "preview": False}))
        span = job / "span-1-2.mp4"
        span.write_bytes(b"span")
        (job / "span-1-2.work").mkdir()
        (job / "span-1-2.work" / "render.json").write_text(json.dumps({"output": str(span), "range": [1, 2], "kind": "span", "span": [1, 2]}))
        now = time.time() + 5
        for f in (legacy, span):
            os.utime(str(f), (now, now))
        (job / "job.json").write_text(json.dumps({"slug": "spans", "outputs": {}}))
        self.assertTrue(ledger.is_span_video(legacy))
        self.assertTrue(ledger.is_span_video(span))
        self.assertFalse(ledger.is_span_video(full))
        v, k = ledger.latest_video(job)
        self.assertEqual((v, k), (full, "final"))
        self.assertEqual(ledger.latest_output(job, "final"), full)
        # a folder a no-job span render made: render.json at the root says span; adopting it sets no final
        solo = self.fake_job("solo")
        clip = solo / "span-1-2.mp4"
        clip.write_bytes(b"span")
        (solo / "render.json").write_text(json.dumps({"output": str(clip), "range": [1, 2], "kind": "span", "span": [1, 2],
                                                      "deliverable": False, "project": str(self.tmp)}))
        data = ledger.load(solo)
        self.assertNotIn("final", data["outputs"])
        self.assertEqual(ledger.latest_video(solo, data), (None, None))
        from st.qa import review
        with self.assertRaises(Exception):
            review.resolve_video(solo)

    def test_note_render_base_and_receipt(self):
        cp = showtime("job", "init", "noted", "--goal", "g", "--json", cwd=self.tmp)
        job = Path(json.loads(cp.stdout)["job"])
        (job / "final.mp4").write_bytes(b"x")
        showtime("job", "note", job, "--stage", "render", "--output", "final=%s" % (job / "final.mp4"), "--render", "full=final.mp4",
                 "--seconds", "20", cwd=self.tmp)
        (job / "final-2.mp4").write_bytes(b"y")
        showtime("job", "note", job, "--stage", "render", "--output", "final=%s" % (job / "final-2.mp4"), "--auto",
                 "--render", "partial=final-2.mp4", "--render-span", "2.2-2.8", "--render-base", "final.mp4", "--seconds", "4",
                 cwd=self.tmp)
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(data["outputs"]["final"]).name, "final-2.mp4")
        entry = [o for o in data["output_log"] if Path(o["path"]).name == "final-2.mp4"][-1]
        self.assertEqual(entry["spliced"], "2.2-2.8 from final.mp4")
        self.assertEqual(entry["kind"], "final")
        self.assertEqual(data["renders"][-1], {**data["renders"][-1], "kind": "partial", "span": [2.2, 2.8], "spliced_from": "final.mp4"})
        rec = json.loads(showtime("receipt", str(job), "--print", "--json", cwd=self.tmp).stdout)
        self.assertEqual((rec["renders"]["full"], rec["renders"]["partial"], rec["renders"]["spliced"]), (1, 1, 1))
        self.assertEqual(rec["renders"]["list"][-1]["spliced_from"], "final.mp4")
        showtime("receipt", str(job), "--no-share", cwd=self.tmp)
        self.assertIn("Partial renders (only a span re-rendered): 1 (1 spliced into a copy of the full video",
                      (job / "receipt.md").read_text(encoding="utf-8"))
        bad = showtime("job", "note", job, "--render", "full=final.mp4", "--render-base", "final.mp4", check=False, cwd=self.tmp)
        self.assertNotEqual(bad.returncode, 0, "a base only makes sense for a partial render with a span")


# --------------------------------------------------------------------------- real renders

@unittest.skipUnless(NODE, "Node.js is not installed")
class TestSpliceRender(unittest.TestCase):
    """One job, renders in order: full (red box) -> fix (blue) -> splice -> reference -> crf splice -> poster splice."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-splice-"))
        cls.proj = write_project(cls.tmp / "proj")
        cls.job = new_job("splice", cls.tmp)
        cls.full, _ = render(cls.proj, "--job", cls.job, cwd=cls.tmp)
        write_project(cls.proj, color="#2050f0")                      # the fix: only frames 66-83 change
        cls.sp, cls.sp_cp = render(cls.proj, "--from", 2.2, "--to", 2.8, "--job", cls.job, cwd=cls.tmp)
        cls.ref, _ = render(cls.proj, "-o", cls.tmp / "ref" / "fixed.mp4", cwd=cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_1_spliced_final_is_the_whole_video(self):
        sp = self.sp
        out = Path(sp["output"])
        self.assertEqual(out, self.job / "final-2.mp4")
        self.assertEqual(sp["kind"], "spliced")
        self.assertEqual(Path(sp["splice"]["base"]).name, "final.mp4")
        self.assertEqual(sp["splice"]["mode"], "cut", sp["splice"])
        self.assertEqual((sp["frames"], sp["duration"], sp["range"]), (TOTAL, DUR, [0, DUR]))
        p, pb = probe(out), probe(self.full["output"])
        self.assertEqual((p["frames"], p["width"], p["height"], p["fps"]), (TOTAL, W, H, "30/1"))
        self.assertAlmostEqual(p["duration"], pb["duration"], delta=0.001)
        self.assertEqual(p["color"], ("bt709", "tv"))
        self.assertAlmostEqual(p["audio"], DUR, delta=0.03)
        lufs, tp = loudness(out)
        self.assertAlmostEqual(lufs, -14.0, delta=0.6)
        self.assertLessEqual(tp, -0.8)
        self.assertIn("splice: 2.20-2.80s into a copy of final.mp4 -> final-2.mp4 (the full 6.00s video)", self.sp_cp.stderr)
        self.assertTrue(Path(sp["poster"]["file"]).is_file())

    def test_2_frame_exact_seams(self):
        rr = self.sp["splice"]["rerendered"]
        self.assertEqual(len(rr), 1)
        s0, e0 = round(rr[0][0] * FPS), round(rr[0][1] * FPS)
        self.assertLessEqual(s0, 66)
        self.assertGreaterEqual(e0, 84)
        self.assertTrue(s0 > 0 and e0 < TOTAL, "this span sits between two keyframes: old frames on both sides (%s)" % rr)
        hs, hb = frame_hashes(self.sp["output"]), frame_hashes(self.full["output"])
        self.assertEqual(len(hs), TOTAL)
        self.assertEqual(hs[:s0], hb[:s0], "frames before the re-rendered GOPs are the old render's")
        self.assertEqual(hs[e0:], hb[e0:], "frames after them too")
        self.assertNotEqual(hs[66:84], hb[66:84])
        # inside and at both seams every frame matches the full render of the fixed project, and not its neighbours
        gs, gr = gray_frames(self.sp["output"]), gray_frames(self.ref["output"])
        self.assertEqual(len(gr), TOTAL)
        for i in sorted({s0 - 1, s0, s0 + 1, 65, 66, 83, 84, e0 - 1, e0, e0 + 1}):
            same = mad(gs[i], gr[i])
            self.assertLess(same, 1.5, "frame %d differs from the reference render" % i)
            for j in (i - 1, i + 1):
                if 0 <= j < TOTAL:
                    self.assertGreater(mad(gs[i], gr[j]), same + 3, "frame %d looks like reference frame %d (a shifted seam)" % (i, j))
        worst = max(mad(a, b) for a, b in zip(gs, gr))
        self.assertLess(worst, 1.5, "every frame of the splice matches the full render of the fixed project")

    def test_3_the_fix_is_in_and_only_in_the_span(self):
        blue, red = pixel(self.sp["output"], 75, 190, 95), pixel(self.full["output"], 75, 190, 95)
        self.assertGreater(blue[2], blue[0] + 80, blue)
        self.assertGreater(red[0], red[2] + 80, red)
        self.assertEqual(pixel(self.sp["output"], 100, 190, 95), pixel(self.full["output"], 100, 190, 95))

    def test_4_ledger_receipt_and_qa_pick_the_splice(self):
        data = json.loads((self.job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(data["outputs"]["final"]).name, "final-2.mp4")
        entry = [o for o in data["output_log"] if Path(o["path"]).name == "final-2.mp4"][-1]
        self.assertEqual(entry["spliced"], "2.2-2.8 from final.mp4")
        last = data["renders"][-1]
        self.assertEqual((last["kind"], last["file"], last["span"], last["spliced_from"]), ("partial", "final-2.mp4", [2.2, 2.8], "final.mp4"))
        self.assertTrue(any("spliced 2.20-2.80s from final.mp4" in h["event"] for h in data["history"]))
        self.assertEqual(ledger.latest_video(self.job)[0].name, "final-2.mp4")
        rec = json.loads(showtime("receipt", str(self.job), "--print", "--json", cwd=self.tmp).stdout)
        self.assertEqual((rec["renders"]["full"], rec["renders"]["partial"], rec["renders"]["spliced"]), (1, 1, 1))
        rj = json.loads((self.job / "final-2.work" / "render.json").read_text(encoding="utf-8"))
        self.assertEqual(rj["kind"], "spliced")
        self.assertFalse(ledger.is_span_report(rj))

    def test_5_other_settings_encode_once_and_chain(self):
        """--crf 18 changes the parameter sets: the whole video is encoded once (spliced into final-2, itself a splice)."""
        cp = showtime("render", self.proj, "--no-check", "--from", 4.1, "--to", 4.3, "--job", self.job, "--crf", 18, cwd=self.tmp)
        self.assertIn("into a copy of final-2.mp4 (encoded once as a whole): final-3.mp4 is the full video", cp.stdout)
        self.assertIn("(latest final -> final-3.mp4)", cp.stdout)
        sp = json.loads((self.job / "final-3.work" / "render.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(sp["output"]).name, "final-3.mp4")
        self.assertEqual(Path(sp["splice"]["base"]).name, "final-2.mp4")
        self.assertEqual(sp["splice"]["mode"], "reencode", sp["splice"])
        self.assertIn("other settings", sp["splice"]["why"])
        p = probe(sp["output"])
        self.assertEqual(p["frames"], TOTAL)
        self.assertAlmostEqual(p["duration"], DUR, delta=0.001)
        self.assertAlmostEqual(p["audio"], DUR, delta=0.03)
        worst = max(mad(a, b) for a, b in zip(gray_frames(sp["output"]), gray_frames(self.ref["output"])))
        self.assertLess(worst, 2.0)
        # a new poster time inside the span: frame 0's GOP is re-rendered and the poster baked as in a full render
        write_project(self.proj, color="#2050f0", extra={"poster": 2.5})
        sp, _ = render(self.proj, "--from", 2.2, "--to", 2.8, "--job", self.job, "--crf", 18, cwd=self.tmp)
        self.assertEqual(Path(sp["output"]).name, "final-4.mp4")
        self.assertEqual(sp["splice"]["rerendered"][0][0], 0, sp["splice"])
        self.assertEqual(sp["poster"]["time"], 2.5)
        g = gray_frames(sp["output"])
        gr = gray_frames(self.ref["output"])
        want = gr[75] if sp["poster"]["baked"] else gr[0]
        self.assertLess(mad(g[0], want), 2.0, "frame 0 is the baked poster (or the opening frame when not baked)")
        self.assertLess(mad(g[1], gr[1]), 2.0)
        self.assertEqual(probe(sp["output"])["frames"], TOTAL)


@unittest.skipUnless(NODE, "Node.js is not installed")
class TestSpanClips(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-span-"))
        cls.proj = write_project(cls.tmp / "proj", duration=3)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_no_full_render_in_the_job(self):
        job = new_job("fresh", self.tmp)
        rep, cp = render(self.proj, "--from", 1, "--to", 2, "--job", job, cwd=self.tmp)
        out = Path(rep["output"])
        self.assertEqual(out, job / "work" / "span-1-2.mp4")
        self.assertEqual((rep["kind"], rep["deliverable"], rep["frames"], rep["span"]), ("span", False, 30, [1, 2]))
        self.assertIn("no full render", rep["span_reason"])
        self.assertEqual(list(job.glob("final*")), [])
        self.assertIsNone(rep["poster"])
        self.assertAlmostEqual(probe(out)["audio"], 1.0, delta=0.03)
        self.assertEqual(ledger.latest_video(job), (None, None))
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertNotIn("final", data.get("outputs") or {})
        self.assertEqual((data["renders"][-1]["kind"], data["renders"][-1]["span"]), ("partial", [1, 2]))
        cp = showtime("render", self.proj, "--from", 1, "--to", 2, "--job", job, "--no-check", cwd=self.tmp)
        self.assertIn("not the video to deliver", cp.stdout)
        self.assertIn("--job", cp.stdout.split("not the video to deliver", 1)[1])
        self.assertTrue((job / "work" / "span-1-2-2.mp4").is_file(), "spans never overwrite either")
        q = showtime("qa", job, "--json", check=False, cwd=self.tmp)
        self.assertNotEqual(q.returncode, 0)
        self.assertIn("no video", q.stdout + q.stderr)

    def test_changed_length_stays_a_span_and_qa_checks_the_final(self):
        proj = write_project(self.tmp / "proj2", duration=3)
        job = new_job("changed", self.tmp)
        full, _ = render(proj, "--job", job, cwd=self.tmp)
        write_project(proj, duration=2)
        rep, _ = render(proj, "--from", 0.5, "--to", 1, "--job", job, cwd=self.tmp)
        self.assertEqual(rep["kind"], "span")
        self.assertIn("length changed", rep["span_reason"])
        self.assertEqual(Path(rep["output"]).parent, job / "work")
        self.assertEqual(ledger.latest_video(job)[0], Path(full["output"]))
        q = json.loads(showtime("qa", job, "--json", check=False, cwd=self.tmp).stdout)
        self.assertEqual(Path(q["video"]).name, "final.mp4")

    def test_no_job_and_o_paths(self):
        out_root = self.tmp / "outs"
        rep, _ = render(self.proj, "--from", 1, "--to", 2, "--out-dir", out_root, cwd=self.tmp)
        folder = Path(rep["folder"])
        self.assertEqual(Path(rep["output"]).name, "span-1-2.mp4")
        self.assertEqual(list(folder.glob("final*")), [])
        self.assertEqual(ledger.latest_video(folder), (None, None))
        self.assertIn("not rendered into a job", rep["span_reason"])
        # -o final.mp4 outside a job with no full render there: a span beside it; -o with its own name: as given
        rep, _ = render(self.proj, "--from", 1, "--to", 2, "-o", self.tmp / "o" / "final.mp4", cwd=self.tmp)
        self.assertEqual(Path(rep["output"]), self.tmp / "o" / "span-1-2.mp4")
        rep, _ = render(self.proj, "--from", 1, "--to", 2, "-o", self.tmp / "o" / "clip.mp4", cwd=self.tmp)
        self.assertEqual((Path(rep["output"]).name, rep["kind"]), ("clip.mp4", "span"))
        self.assertTrue(ledger.is_span_video(self.tmp / "o" / "clip.mp4"))
        # a --preview span is a draft of those seconds
        job = new_job("prev", self.tmp)
        rep, _ = render(self.proj, "--from", 1, "--to", 2, "--job", job, "--preview", cwd=self.tmp)
        self.assertEqual((Path(rep["output"]).parent, rep["kind"]), (job / "work", "preview"))
        self.assertEqual(ledger.latest_video(job), (None, None))

    def test_whole_range_is_an_ordinary_final(self):
        job = new_job("whole", self.tmp)
        rep, _ = render(self.proj, "--from", 0, "--to", 3, "--job", job, cwd=self.tmp)
        self.assertEqual((Path(rep["output"]), rep["kind"]), (job / "final.mp4", "full"))
        self.assertTrue((job / "final.work" / "render.json").is_file())
        self.assertFalse((job / "work" / "span-0-3.work").exists(), "the provisional span folder is gone")
        self.assertEqual(ledger.latest_video(job)[0], job / "final.mp4")


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

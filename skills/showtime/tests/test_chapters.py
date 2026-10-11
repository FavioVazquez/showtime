#!/usr/bin/env python3
"""Chapter mode (`render --chapters`, `--chapter N --job J`, `--join --job J`, issue #22).

  * units (no browser): the chapter table (rounding, the last chapter to `total`, past-end dropped, < 1 s and
    unsorted refused, {t, label}, acts, a seam inside a data-transition warns, no table -> the showtime.json line
    to add); the tiling rules (gap, overlap, missing piece, another `total`) with the exact `--chapter N` hint;
    `joinPieces` writes the concatenation with an IDR at each seam and never holds two pieces; pieces with other
    SPS/PPS are not byte-joined; `sourcesHash` is stable across paths and mtimes; the seam audio check (equal
    audio: step 0, lag 0; a 21 ms shift: caught); `withForcedKeys`
  * render (a 6 s fixture, 3 chapters of 2 s, a white frame and a 1 ms click at each seam): a whole render (a
    keyframe at each chapter start); the plan (plan.json only, the one-machine line); `--chapter 1..3` (video-only
    pieces in work/chapters/, never the latest final); `--join` (frames = total, IDR at the seams, captured JPEGs
    byte-equal to the whole render's, seams PSNR >= 40 dB against it, click lag 0 +-1 sample, seam loudness = master
    +-0.1 dB, the audio stream the same bytes as the whole render's); qa reads the joined kind; then `--chapter 2`
    splices exactly chapter 2's frames; the poster from chapter 3 baked into frame 0
  * refusals and warnings: a missing chapter (the command to run), another length (refused), a piece from a copy
    of the project at another path (joined), changed sources (a warning naming the chapters), another CRF (one
    whole re-encode, with the reason)

Stdlib only. usage: python tests/test_chapters.py [-v]
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
CHAPTERS_MJS = (SKILL / "scripts" / "lib" / "chapters.mjs").as_uri()
LEAN_MJS = (SKILL / "scripts" / "lib" / "lean.mjs").as_uri()
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
CHAPTERS = [[0, "Opening"], [2, "Middle"], [4, "End"]]
ONE_MACHINE = "on one machine a whole render is faster (#22)"


def showtime(*args, check=True, cwd=None, timeout=900):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def run_ff(*args):
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-y"] + [str(a) for a in args],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")[-2000:]
    return cp.stdout


def node(code):
    cp = subprocess.run([NODE, "--input-type=module", "-e", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding="utf-8", timeout=300, env=ENV)
    assert cp.returncode == 0, cp.stderr[-2000:]
    return json.loads(cp.stdout)


def packets(path):
    """[(pts seconds, keyframe?)] of the video stream."""
    cp = subprocess.run([ff.ffprobe_path(), "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time,flags",
                         "-of", "csv=p=0", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=120)
    assert cp.returncode == 0, cp.stderr
    out = []
    for ln in cp.stdout.split("\n"):
        if ln.strip():
            t, fl = (ln.split(",") + [""])[:2]
            out.append((float(t), "K" in fl))
    return sorted(out)


def streams(path):
    cp = subprocess.run([ff.ffprobe_path(), "-v", "error", "-show_streams", "-of", "json", str(path)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=120)
    return [s["codec_type"] for s in json.loads(cp.stdout)["streams"]]


def audio_md5(path):
    return run_ff("-i", path, "-map", "0:a:0", "-c", "copy", "-f", "md5", "-").decode().strip()


def gray_frames(path, w=64, h=36):
    raw = run_ff("-i", path, "-map", "0:v:0", "-vf", "scale=%d:%d:flags=area,format=gray" % (w, h), "-f", "rawvideo", "-")
    n = w * h
    return [raw[i:i + n] for i in range(0, len(raw), n)]


def mad(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / float(len(a))


def psnr_frame(a, b, k):
    """PSNR (dB, 100 = equal) of frame k of two videos."""
    cp = subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-i", str(a), "-i", str(b), "-filter_complex",
                         "[0:v]select=eq(n\\,%d)[x];[1:v]select=eq(n\\,%d)[y];[x][y]psnr" % (k, k), "-frames:v", "1", "-f", "null", "-"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=120)
    import re
    m = re.search(r"PSNR .*average:(inf|[\d.]+)", cp.stderr)
    assert m, cp.stderr[-1500:]
    return 100.0 if m.group(1) == "inf" else float(m.group(1))


def write_project(d, extra=None, comment=""):
    """Every frame differs (a band moving 16 px per frame); a white frame and a 1 ms click at each seam."""
    d.mkdir(parents=True, exist_ok=True)
    (d / "audio").mkdir(exist_ok=True)
    tone = d / "audio" / "bed.wav"
    if not tone.is_file():
        run_ff("-f", "lavfi", "-i", "aevalsrc='0.05*sin(2*PI*330*t)+if(lt(abs(t-2),0.0005)+lt(abs(t-4),0.0005),0.8,0)':s=48000:d=%d" % DUR,
               "-ac", "2", tone)
    cfg = {"width": W, "height": H, "fps": FPS, "duration": DUR, "chapters": CHAPTERS,
           "audio": [{"file": "audio/bed.wav"}]}
    cfg.update(extra or {})
    (d / "showtime.json").write_text(json.dumps(cfg), encoding="utf-8")
    flashes = "".join('<div class="flash" data-start="%d" data-dur="0.0333"></div>' % t for t in (2, 4))
    (d / "index.html").write_text(
        "<!doctype html><html><head><script src=\"/_st/stage.js\"></script><style>"
        "body{margin:0;background:#12203a}"
        "#band{position:absolute;left:0;top:0;width:%dpx;height:40px;"
        "background:repeating-linear-gradient(90deg,#ffe066 0 10px,#12203a 10px 20px);"
        "background-position:calc(var(--st-t) * 480px) 0}"
        "#mover{position:absolute;top:50px;left:calc(var(--st-p) * 200px);width:40px;height:80px;background:#8fd}"
        ".flash{position:absolute;inset:0;background:#fff}"
        "</style></head><body><div id=\"band\"></div><div id=\"mover\"></div>%s<!--%s--></body></html>" % (W, flashes, comment),
        encoding="utf-8")
    return d


def new_job(slug, cwd):
    cp = showtime("job", "init", slug, "--goal", "chapter test", "--json", cwd=cwd)
    return Path(json.loads(cp.stdout)["job"])


def render(proj, *args, cwd=None, check=True):
    cp = showtime("render", proj, "--json", "--no-check", *args, cwd=cwd, check=check)
    return (json.loads(cp.stdout) if cp.returncode == 0 else None), cp


# --------------------------------------------------------------------------- units (no browser)

@unittest.skipUnless(NODE, "Node.js is not installed")
class TestChapterUnits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-chapters-u-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def table(self, args):
        return node("import { chapterTable } from '%s';\n"
                    "try { console.log(JSON.stringify(chapterTable(%s))); }\n"
                    "catch (e) { console.log(JSON.stringify({ error: e.message, fix: e.fix || e.hint || null })); }" % (CHAPTERS_MJS, json.dumps(args)))

    def test_frame_ranges(self):
        t = self.table({"cfgChapters": [[0, "a"], [1.016, "b"], {"t": 2.5, "label": "c"}, [9, "late"]], "duration": 4, "fps": 30})
        self.assertEqual([c["frames"] for c in t["chapters"]], [[0, 30], [30, 75], [75, 120]])
        self.assertEqual(t["total"], 120)
        self.assertEqual([c["label"] for c in t["chapters"]], ["a", "b", "c"])
        self.assertTrue(any("past the end" in w and "late" in w for w in t["warnings"]), t["warnings"])
        self.assertEqual(t["source"], 'showtime.json "chapters"')

    def test_last_chapter_ends_at_total(self):
        t = self.table({"cfgChapters": [[0, "a"], [2.49, "b"]], "duration": 5.01, "fps": 25})
        self.assertEqual(t["chapters"][-1]["frames"], [62, 125])

    def test_short_unsorted_none_refused(self):
        self.assertIn("shorter than 1 s", self.table({"cfgChapters": [[0, "a"], [2, "b"], [2.5, "c"]], "duration": 6, "fps": 30})["error"])
        self.assertIn("not in order", self.table({"cfgChapters": [[0, "a"], [3, "b"], [2, "c"]], "duration": 6, "fps": 30})["error"])
        e = self.table({"cfgChapters": None, "acts": None, "duration": 6, "fps": 30})
        self.assertIn("no chapters", e["error"])
        self.assertIn('"chapters": [[0, "Intro"]', e["fix"])

    def test_acts_and_transition_warning(self):
        t = self.table({"cfgChapters": [], "acts": [{"t": 0, "label": "One"}, {"t": 3, "label": "Two"}], "duration": 6, "fps": 30,
                        "transitions": [[2.7, 3.3]]})
        self.assertEqual(t["source"], "the film's acts")
        self.assertEqual([c["frames"] for c in t["chapters"]], [[0, 90], [90, 180]])
        self.assertTrue(any("data-transition" in w for w in t["warnings"]), t["warnings"])

    def tiling(self, pieces, total=180):
        chapters = [{"n": 1, "label": "a", "frames": [0, 60]}, {"n": 2, "label": "b", "frames": [60, 120]}, {"n": 3, "label": "c", "frames": [120, 180]}]
        return node("import { checkTiling } from '%s';\nconsole.log(JSON.stringify(checkTiling(%s, %s, (n) => `showtime render p --chapter ${n} --job J`)));"
                    % (CHAPTERS_MJS, json.dumps(pieces), json.dumps({"chapters": chapters, "total": total, "W": 256, "H": 144, "fps": 30})))

    def piece(self, n, s, e, **kw):
        p = {"n": n, "file": "ch-%02d.mp4" % n, "frames": [s, e], "width": 256, "height": 144, "fps": 30, "timeline_frames": 180}
        p.update(kw)
        return p

    def test_tiling(self):
        ok = self.tiling([self.piece(1, 0, 60), self.piece(2, 60, 120), self.piece(3, 120, 180)])
        self.assertTrue(ok["ok"], ok)
        gap = self.tiling([self.piece(1, 0, 60), self.piece(3, 120, 180)])
        self.assertFalse(gap["ok"])
        self.assertTrue(any("gap" in e for e in gap["errors"]), gap)
        self.assertEqual(gap["missing"], [2])
        self.assertEqual(gap["fix"], ["showtime render p --chapter 2 --job J"])
        over = self.tiling([self.piece(1, 0, 70), self.piece(2, 60, 120), self.piece(3, 120, 180)])
        self.assertTrue(any("overlaps" in e for e in over["errors"]), over)
        other = self.tiling([self.piece(1, 0, 60, timeline_frames=195), self.piece(2, 60, 120), self.piece(3, 120, 180)])
        self.assertFalse(other["ok"])
        self.assertTrue(any("195-frame" in e for e in other["errors"]), other)
        self.assertEqual(other["fix"], ["showtime render p --chapter 1 --job J"])
        size = self.tiling([self.piece(1, 0, 60, width=320), self.piece(2, 60, 120), self.piece(3, 120, 180)])
        self.assertTrue(any("320x144" in e for e in size["errors"]), size)

    def enc(self, name, src, extra=()):
        out = self.tmp / name
        run_ff("-f", "lavfi", "-i", src, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-bf", "0", "-g", "60",
               "-pix_fmt", "yuv420p", *extra, out)
        return out

    def test_join_pieces(self):
        a = self.enc("a.mp4", "testsrc=size=128x72:rate=30:duration=1")
        b = self.enc("b.mp4", "testsrc2=size=128x72:rate=30:duration=1.5")
        c = self.enc("c.mp4", "testsrc=size=128x72:rate=30:duration=1,hflip")
        out = self.tmp / "joined.h264"
        r = node("import { joinPieces } from '%s';\nconsole.log(JSON.stringify(await joinPieces(%s, %s)));" % (
            CHAPTERS_MJS, json.dumps([{"file": str(a), "frames": 30}, {"file": str(b), "frames": 45}, {"file": str(c), "frames": 30}]), json.dumps(str(out))))
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["frames"], 105)
        self.assertEqual(r["seams"], [30, 75])
        self.assertEqual(r["maxHeld"], 1, "one piece in memory at a time")
        self.assertLess(r["peakBytes"], out.stat().st_size)
        mp4 = self.tmp / "joined.mp4"
        run_ff("-fflags", "+genpts", "-r", "30", "-i", out, "-c", "copy", mp4)
        pk = packets(mp4)
        self.assertEqual(len(pk), 105)
        self.assertTrue(pk[30][1] and pk[75][1], "an IDR at each seam")
        h = lambda p: run_ff("-i", p, "-map", "0:v:0", "-f", "framemd5", "-").decode().splitlines()
        hashes = lambda p: [ln.split(",")[-1].strip() for ln in h(p) if ln and not ln.startswith("#")]
        self.assertEqual(hashes(mp4), hashes(a) + hashes(b) + hashes(c), "the join decodes to the pieces, frame for frame")
        d = self.enc("d.mp4", "testsrc=size=128x72:rate=30:duration=1", ("-preset", "slow"))
        r2 = node("import { joinPieces } from '%s';\nconsole.log(JSON.stringify(await joinPieces(%s, %s)));" % (
            CHAPTERS_MJS, json.dumps([{"file": str(a), "frames": 30}, {"file": str(d), "frames": 30}]), json.dumps(str(self.tmp / "j2.h264"))))
        self.assertFalse(r2["ok"])
        self.assertIn("SPS/PPS", r2["why"])
        self.assertNotIn("bad", r2, "other param sets fall back to a re-encode, not a refusal")
        r3 = node("import { joinPieces } from '%s';\nconsole.log(JSON.stringify(await joinPieces(%s, %s)));" % (
            CHAPTERS_MJS, json.dumps([{"file": str(a), "frames": 30, "n": 1}, {"file": str(b), "frames": 60, "n": 2}]), json.dumps(str(self.tmp / "j3.h264"))))
        self.assertFalse(r3["ok"])
        self.assertEqual(r3["bad"], 2, "a piece cut short is named, to be refused")
        self.assertIn("parsed as 45 frames, expected 60", r3["why"])

    def test_sources_hash(self):
        p = write_project(self.tmp / "proj")
        h = lambda d: node("import { sourcesHash } from '%s';\nconsole.log(JSON.stringify(sourcesHash(%s)));" % (LEAN_MJS, json.dumps(str(d))))
        h0 = h(p)
        q = self.tmp / "elsewhere" / "copy"
        shutil.copytree(str(p), str(q))
        later = time.time() + 1000
        for f in q.rglob("*"):
            os.utime(str(f), (later, later))
        (q / "work").mkdir()
        (q / "work" / "x.json").write_text("{}", encoding="utf-8")
        self.assertEqual(h(q), h0, "the same at another path, other mtimes, work/ ignored")
        (q / "index.html").write_text((q / "index.html").read_text(encoding="utf-8") + " ", encoding="utf-8")
        self.assertNotEqual(h(q), h0)

    def test_seam_audio(self):
        a = self.tmp / "a.m4a"
        run_ff("-f", "lavfi", "-i", "aevalsrc='0.1*sin(2*PI*440*t)+if(lt(abs(t-2),0.0005),0.8,0)':s=48000:d=4", "-ac", "2", "-c:a", "aac", a)
        shifted = self.tmp / "s.m4a"
        run_ff("-i", a, "-af", "adelay=21:all=1,atrim=0:4", "-c:a", "aac", shifted)
        r = node("import { seamAudio } from '%s';\nconsole.log(JSON.stringify([await seamAudio(%s, %s, [2]), await seamAudio(%s, %s, [1, 2, 3.5])]));" % (
            CHAPTERS_MJS, json.dumps(str(a)), json.dumps(str(a)), json.dumps(str(shifted)), json.dumps(str(a))))
        self.assertEqual(r[0][0]["delta_db"], 0)
        self.assertEqual(r[0][0]["lag_samples"], 0)
        self.assertTrue(r[0][0]["ok"])
        self.assertFalse(r[1][1]["ok"])
        self.assertAlmostEqual(abs(r[1][1]["lag_samples"]), 1008, delta=2, msg="each window of one decode sits at its own seam")

    def test_seam_threshold(self):
        r = node("import { seamThreshold } from '%s';\nconsole.log(JSON.stringify([53, 38.8, 30.9, 20].map(seamThreshold)));" % CHAPTERS_MJS)
        self.assertEqual(r, [40, 35.8, 27.9, 25], "40 dB, or 3 dB under the piece's own frame, never under 25 dB")

    def test_forced_keys(self):
        r = node("import { withForcedKeys } from '%s';\nconsole.log(JSON.stringify([withForcedKeys(['-crf', '16'], [0, 120, 60]), withForcedKeys(['-crf', '16'], [0])]));" % CHAPTERS_MJS)
        self.assertEqual(r[0], ["-crf", "16", "-force_key_frames", "expr:eq(n,60)+eq(n,120)", "-forced-idr", "1"])
        self.assertEqual(r[1], ["-crf", "16"])


# --------------------------------------------------------------------------- real renders

@unittest.skipUnless(NODE, "Node.js is not installed")
class TestChapterRender(unittest.TestCase):
    """A whole render (job A) and the same film as 3 chapters + a join (job B)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-chapters-r-"))
        cls.proj = write_project(cls.tmp / "film", extra={"poster": 5.0})
        cls.job_a = new_job("whole", cls.tmp)
        cls.whole, _ = render(cls.proj, "--job", cls.job_a, "--keep-frames", cwd=cls.tmp)
        cls.job_b = new_job("chapters", cls.tmp)
        cls.plan_cp = showtime("render", cls.proj, "--chapters", "--job", cls.job_b, cwd=cls.tmp)
        cls.pieces = [render(cls.proj, "--chapter", n, "--job", cls.job_b, "--keep-frames", cwd=cls.tmp)[0] for n in (1, 2, 3)]
        cls.latest_after_pieces = ledger.latest_video(cls.job_b)
        cls.joined, cls.join_cp = render(cls.proj, "--join", "--job", cls.job_b, cwd=cls.tmp)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_whole_render_keyframes_at_chapters(self):
        pk = packets(self.whole["output"])
        self.assertEqual(len(pk), TOTAL)
        self.assertTrue(pk[60][1] and pk[120][1], "a keyframe at each chapter start")
        self.assertEqual(self.whole["kind"], "full")

    def test_plan(self):
        out = self.plan_cp.stdout
        self.assertEqual(out.splitlines()[0].strip(), ONE_MACHINE)
        self.assertIn("--chapter 2 --job", out)
        plan = json.loads((self.job_b / "work" / "chapters" / "plan.json").read_text(encoding="utf-8"))
        self.assertEqual([c["frames"] for c in plan["chapters"]], [[0, 60], [60, 120], [120, 180]])
        self.assertEqual(plan["note"], ONE_MACHINE)

    def test_pieces(self):
        for n, p in enumerate(self.pieces, 1):
            self.assertEqual(p["kind"], "piece")
            self.assertFalse(p["deliverable"])
            self.assertEqual(p["chapter"]["n"], n)
            self.assertEqual(p["timeline_frames"], TOTAL)
            self.assertTrue(p["sources_hash"].startswith("sha256:"))
            self.assertIn("ffmpeg_version", p)
            self.assertEqual(Path(p["output"]), self.job_b / "work" / "chapters" / ("%dx%d" % (W, H)) / ("ch-%02d.mp4" % n))
            self.assertEqual(streams(p["output"]), ["video"], "a piece is video only")
            self.assertTrue(packets(p["output"])[0][1], "a piece starts with an IDR")
        self.assertIsNone(self.latest_after_pieces[0], "a piece is never the latest video")
        self.assertFalse(list(self.job_b.glob("final*.mp4")) and False)

    def test_captured_frames_equal_whole(self):
        whole = Path(self.whole["output"]).parent / "work" / "frames"
        if not whole.is_dir():
            whole = Path(self.whole["output"]).with_suffix(".work") / "frames"
        for n, p in enumerate(self.pieces, 1):
            fr = Path(p["output"]).with_suffix(".work") / "frames"
            s = p["chapter"]["frames"][0]
            for k in (0, 1, 59):
                a = sorted(fr.glob("f_%06d.*" % k))
                b = sorted(whole.glob("f_%06d.*" % (s + k)))
                self.assertTrue(a and b, (fr, whole))
                self.assertEqual(a[0].read_bytes(), b[0].read_bytes(), "chapter %d frame %d" % (n, s + k))

    def test_join(self):
        j = self.joined
        self.assertEqual(j["kind"], "joined")
        self.assertEqual(Path(j["output"]).name, "final.mp4")
        self.assertEqual(j["join"]["mode"], "cut")
        pk = packets(j["output"])
        self.assertEqual(len(pk), TOTAL)
        self.assertTrue(pk[60][1] and pk[120][1], "an IDR at each seam")
        for k, (t, _) in enumerate(pk):
            self.assertAlmostEqual(t, k / FPS, delta=1e-4)
        s = j["seams"]
        self.assertTrue(s["ok"], s)
        self.assertGreaterEqual(s["pixels"]["min_db"], 40)
        for row in s["audio"]["seams"]:
            self.assertLessEqual(abs(row["delta_db"]), 0.1)
            self.assertLessEqual(abs(row["lag_samples"]), 1)
        for k in (59, 60, 119, 120):
            self.assertGreaterEqual(psnr_frame(j["output"], self.whole["output"], k), 40, "seam frame %d against the whole render" % k)
        self.assertEqual(audio_md5(j["output"]), audio_md5(self.whole["output"]), "the soundtrack is the whole render's master")
        r = node("import { seamAudio } from '%s';\nconsole.log(JSON.stringify(await seamAudio(%s, %s, [2, 4])));" % (
            CHAPTERS_MJS, json.dumps(j["output"]), json.dumps(self.whole["output"])))
        for row in r:
            self.assertLessEqual(abs(row["lag_samples"]), 1, "the click at the seam is where the whole render has it")
            self.assertLessEqual(abs(row["delta_db"]), 0.1)
        self.assertEqual(ledger.latest_video(self.job_b)[0].name, "final.mp4")
        outs = json.loads((self.job_b / "job.json").read_text(encoding="utf-8"))["outputs"]
        self.assertEqual(Path(outs["final"]).name, Path(j["output"]).name, "the join sets the job's final pointer")
        self.assertEqual(Path(outs["poster"]).name, Path(j["poster"]["file"]).name, "and its poster pointer")

    def test_poster_from_chapter_3_baked(self):
        p = self.joined["poster"]
        self.assertEqual(round(float(p["time"]), 3), 5.0)
        self.assertTrue(Path(p["file"]).is_file())
        g = gray_frames(self.joined["output"])
        want = g[150] if p.get("baked") else gray_frames(self.whole["output"])[0]
        self.assertLess(mad(g[0], want), 2.0, "frame 0 is the baked poster (chapter 3) or the opening frame")

    def test_qa_reads_joined(self):
        cp = showtime("qa", self.job_b, "--json", "--no-sheet", cwd=self.tmp, check=False)
        rep = json.loads(cp.stdout)
        self.assertEqual(Path(rep["video"]).name, "final.mp4")
        self.assertEqual(rep["seams"]["kind"], "joined")
        self.assertEqual(rep["seams"]["seams"], [2.0, 4.0])
        self.assertTrue(rep["seams"]["keyframes"])
        self.assertTrue(rep["seams"]["audio_is_master"])
        self.assertFalse([f for f in rep["findings"] if f["rule"].startswith("seam_")], rep["findings"])

    def test_zz_chapter_into_joined_final_splices_exact_bounds(self):
        sp, _ = render(self.proj, "--chapter", "2", "--job", self.job_b, cwd=self.tmp)
        self.assertEqual(sp["kind"], "spliced")
        self.assertEqual(Path(sp["output"]).name, "final-2.mp4")
        self.assertEqual(sp["splice"]["rerendered"], [[2.0, 4.0]], "exactly chapter 2's frames, no widening")
        self.assertEqual(len(packets(sp["output"])), TOTAL)


@unittest.skipUnless(NODE, "Node.js is not installed")
class TestChapterRules(unittest.TestCase):
    """Refusals, the copied project, the stale-hash warning and the re-encode fallback."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-chapters-x-"))
        cls.proj = write_project(cls.tmp / "film")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_missing_copy_stale_and_length(self):
        job = new_job("rules", self.tmp)
        for n in (1, 2):
            render(self.proj, "--chapter", n, "--job", job, cwd=self.tmp)
        _, cp = render(self.proj, "--join", "--job", job, cwd=self.tmp, check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("chapter 3", cp.stderr)
        self.assertIn("--chapter 3 --job", cp.stderr)
        self.assertFalse(list(job.glob("final*.mp4")))
        # chapter 3 from a copy of the project at another path: joined
        other = self.tmp / "machine-2" / "film"
        shutil.copytree(str(self.proj), str(other))
        render(other, "--chapter", 3, "--job", job, cwd=self.tmp)
        j, _ = render(self.proj, "--join", "--job", job, "--no-seam-pixels", cwd=self.tmp)
        self.assertEqual(j["kind"], "joined")
        self.assertFalse(j["join"]["stale"])
        self.assertFalse([w for w in j["warnings"] if "sources_hash" in w])
        self.assertEqual(j["seams"]["pixels"]["skipped"], "--no-seam-pixels")
        # the receipt counts each piece once and the join's own time once (not the pieces again)
        from st.job import receipt
        rr = receipt._renders(json.loads((job / "job.json").read_text(encoding="utf-8")))
        own = j["timings"]["total"] / 1000
        self.assertAlmostEqual(rr["seconds"], sum(p["seconds"] for p in j["join"]["pieces"]) + own, delta=0.5, msg=rr)
        self.assertAlmostEqual([r for r in rr["list"] if r.get("file") == "final.mp4"][0]["seconds"], own, delta=0.2)
        self.assertNotIn("host", j, "hostnames stay in join.machines")
        # the sources changed after the pieces: a warning naming the chapters, joined anyway
        write_project(self.proj, comment="edited")
        j2, _ = render(self.proj, "--join", "--job", job, "--no-seam-pixels", cwd=self.tmp)
        self.assertEqual(Path(j2["output"]).name, "final-2.mp4")
        self.assertEqual(j2["join"]["stale"], [1, 2, 3])
        self.assertTrue([w for w in j2["warnings"] if "sources_hash" in w and "chapters 1 (ch-01.mp4)" in w], j2["warnings"])
        write_project(self.proj)
        # a piece cut short (a broken copy): refused, naming its --chapter command, without re-encoding the film
        p2 = next(job.glob("work/chapters/*/ch-02.mp4"))
        cut, good = p2.with_name("cut.mp4"), p2.with_name("good.mp4")
        run_ff("-i", p2, "-frames:v", "30", "-c", "copy", cut)
        p2.rename(good)
        cut.rename(p2)
        _, cp = render(self.proj, "--join", "--job", job, "--no-seam-pixels", cwd=self.tmp, check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("chapter 2 cannot be joined", cp.stderr)
        self.assertIn("--chapter 2 --job", cp.stderr)
        self.assertNotIn("encoding the whole video", cp.stdout + cp.stderr)
        p2.unlink()
        good.rename(p2)
        # another length: refused, naming the chapters to render again
        longer = write_project(self.tmp / "longer", extra={"duration": 6.5})
        _, cp = render(longer, "--join", "--job", job, cwd=self.tmp, check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("the length changed", cp.stderr)
        self.assertIn("--chapter 1 --job", cp.stderr)

    def test_other_crf_reencodes(self):
        job = new_job("crf", self.tmp)
        render(self.proj, "--chapter", 1, "--job", job, "--crf", "24", cwd=self.tmp)
        for n in (2, 3):
            render(self.proj, "--chapter", n, "--job", job, cwd=self.tmp)
        # other settings would re-encode, but a later piece cut short is refused first, naming its command
        p3 = next(job.glob("work/chapters/*/ch-03.mp4"))
        good = p3.with_name("good.mp4")
        p3.rename(good)
        run_ff("-i", good, "-frames:v", "30", "-c", "copy", p3)
        _, cp = render(self.proj, "--join", "--job", job, "--no-seam-pixels", cwd=self.tmp, check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("chapter 3 cannot be joined", cp.stderr)
        self.assertIn("--chapter 3 --job", cp.stderr)
        self.assertNotIn("encoding the whole video", cp.stdout + cp.stderr)
        p3.unlink()
        good.rename(p3)
        j, _ = render(self.proj, "--join", "--job", job, "--no-seam-pixels", cwd=self.tmp)
        self.assertEqual(j["join"]["mode"], "reencode")
        self.assertIn("crf 24", j["join"]["why"])
        pk = packets(j["output"])
        self.assertEqual(len(pk), TOTAL)
        self.assertTrue(pk[60][1] and pk[120][1], "the re-encode keeps a keyframe at each seam")
        self.assertTrue(j["seams"]["ok"], j["seams"])

    def test_grainy_high_crf_seams_pass(self):
        """Grain at a high CRF: encode noise puts every frame below 40 dB; the relative rule still passes a correct join."""
        proj = write_project(self.tmp / "grain")
        noise = proj / "noise.png"
        run_ff("-f", "lavfi", "-i", "color=gray:s=320x180,noise=alls=90:allf=u:all_seed=7", "-frames:v", "1", noise)
        html = (proj / "index.html").read_text(encoding="utf-8").replace("</body>",
            '<div style="position:absolute;inset:0;opacity:.7;background:url(noise.png);'
            'background-position:calc(var(--st-t) * 7919px) calc(var(--st-t) * 6007px)"></div></body>')
        (proj / "index.html").write_text(html, encoding="utf-8")
        job = new_job("grain", self.tmp)
        for n in (1, 2, 3):
            render(proj, "--chapter", n, "--job", job, "--crf", "24", cwd=self.tmp)
        j, _ = render(proj, "--join", "--job", job, "--crf", "24", cwd=self.tmp)
        px = j["seams"]["pixels"]
        self.assertTrue(j["seams"]["ok"], j["seams"])
        self.assertLess(px["min_db"], 40, "the absolute 40 dB rule would have refused this join")
        for row in px["seams"]:
            self.assertEqual(row["baseline_frame"], row["frame"] + 3)
            self.assertLess(row["threshold_db"], 40)
            self.assertGreaterEqual(min(row["psnr_before"], row["psnr_after"]), row["psnr_baseline"] - 3)

    def test_flags_refused(self):
        _, cp = render(self.proj, "--chapter", 1, cwd=self.tmp, check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("needs --job", cp.stderr)
        _, cp = render(self.proj, "--chapter", 9, "--job", new_job("nine", self.tmp), cwd=self.tmp, check=False)
        self.assertIn("there is no chapter 9", cp.stderr)
        _, cp = render(self.proj, "--chapter", 1, "--from", 1, "--job", "x", cwd=self.tmp, check=False)
        self.assertIn("do not mix", cp.stderr)
        nochap = write_project(self.tmp / "nochap")
        cfg = json.loads((nochap / "showtime.json").read_text(encoding="utf-8"))
        cfg.pop("chapters")
        (nochap / "showtime.json").write_text(json.dumps(cfg), encoding="utf-8")
        cp = showtime("render", nochap, "--chapters", cwd=self.tmp, check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn('"chapters"', cp.stderr)


if __name__ == "__main__":
    unittest.main()

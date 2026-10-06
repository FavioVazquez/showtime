#!/usr/bin/env python3
"""Variety guard and style references (st.variety, `showtime history`, `showtime reference`).

Real runs on small generated videos (ffmpeg lavfi sources, no downloads):
  * look extraction from a project's files (theme, palette, type pair, transitions, camera, music, structure),
    and `showtime new` records the template name;
  * the look history: record, exclude itself, repeats per aspect with two alternatives each, the brand
    exemption, opt-out (history off, SHOWTIME_HISTORY=off), clear; `history check --strict` exit codes;
  * `showtime qa` on a job's passing final records its look; a second project then repeats it;
  * `showtime reference` on a four-shot fixture: cut times, shot lengths, pace, per-shot palette, a push-in
    and a pan detected as camera verbs, the 1 fps sheet, reference.md with the brief, the credit line in
    credits.txt and share.txt, a direct URL served from 127.0.0.1 and a page URL refused;
  * the near-copy guard: a re-encode and a scaled, brightened copy fail, unrelated video passes, flat
    video is inconclusive; qa reports reference_copy / reference_credit; share.txt keeps one credit line.
Browser runs (skipped with --fast): `showtime check` reports look_repeat, and render keeps the credit.

Stdlib + the showtime venv. usage: python tests/test_variety.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import functools
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import warnings
from pathlib import Path

from _listen import needs_listen

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
warnings.simplefilter("ignore", ResourceWarning)   # Pillow files closed by the garbage collector
ENV = build_env(showtime_home())
TMP = Path(tempfile.mkdtemp(prefix="st-variety-"))


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


def showtime(*args, check=True, timeout=600, cwd=None, env=None):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=env or ENV, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
                        timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def ffmpeg(*args):
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-y"] + [str(a) for a in args],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")


def shots_video(path: Path, specs, size="320x180", tone=True) -> Path:
    """Concatenated lavfi sources: [(source expression, seconds)], each a shot; a tone underneath."""
    args, labels = [], []
    for i, (src, d) in enumerate(specs):
        args += ["-f", "lavfi", "-i", "%s,trim=duration=%g,setpts=PTS-STARTPTS,scale=%s,setsar=1,fps=30,format=yuv420p"
                 % (src.format(size=size), d, size.replace("x", ":"))]
        labels.append("[%d:v]" % i)
    total = sum(d for _s, d in specs)
    fc = "%sconcat=n=%d:v=1:a=0[v]" % ("".join(labels), len(specs))
    if tone:
        args += ["-f", "lavfi", "-i", "sine=f=330:d=%g:sample_rate=48000" % total]
    args += ["-filter_complex", fc, "-map", "[v]"]
    if tone:
        args += ["-map", "%d:a" % len(specs), "-c:a", "aac", "-b:a", "128k"]
    ffmpeg(*(args + ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-t", "%g" % total, str(path)]))
    return path


@functools.lru_cache(maxsize=None)
def still(name: str, src: str, size: str) -> Path:
    p = TMP / ("%s.png" % name)
    ffmpeg("-f", "lavfi", "-i", "%s=s=%s:r=1:d=1" % (src, size), "-frames:v", "1", str(p))
    return p


@functools.lru_cache(maxsize=None)
def reference_fixture() -> Path:
    """Shots 2.0 / 1.5 / 2.0 / 1.5 s: moving pattern, a camera push-in on a still, a pan across a wide
    still, a flat colour. Cuts at 2.0, 3.5, 5.5."""
    zoom = TMP / "zoom.mp4"
    ffmpeg("-loop", "1", "-framerate", "30", "-t", "1.6", "-i", still("rgb", "testsrc", "640x360"), "-vf",
           "zoompan=z='1+0.006*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=320x180:fps=30,format=yuv420p",
           "-t", "1.5", "-c:v", "libx264", "-preset", "veryfast", str(zoom))
    pan = TMP / "pan.mp4"
    ffmpeg("-loop", "1", "-t", "2.1", "-framerate", "30", "-i", still("wide", "testsrc", "800x180"), "-vf",
           "crop=320:180:x='t*60':y=0,format=yuv420p", "-t", "2.0", "-c:v", "libx264", "-preset", "veryfast", str(pan))
    return shots_video(TMP / "reference.mp4", [
        ("testsrc2=s={size}:r=30:d=2", 2.0),
        ("movie=%s" % plat.filter_path(zoom), 1.5),
        ("movie=%s" % plat.filter_path(pan), 2.0),
        ("color=c=0x224488:s={size}:r=30:d=2", 1.5),
    ])


@functools.lru_cache(maxsize=None)
def unrelated_fixture() -> Path:
    return shots_video(TMP / "unrelated.mp4", [
        ("life=s={size}:r=30:mold=10:ratio=0.5:death_color=#203040:life_color=#e0c070", 2.5),
        ("cellauto=s={size}:r=30:rule=110", 2.0),
        ("sierpinski=s={size}:r=30", 2.5),
    ])


def make_job(slug: str) -> Path:
    base = TMP / ("jobs-" + slug)
    base.mkdir(parents=True, exist_ok=True)
    showtime("job", "init", slug, "--goal", "a test video for %s" % slug, cwd=base)
    return sorted((base / "showtime-out").glob(slug + "-*"))[-1]


def write_project(d: Path, *, theme="bold", transitions=("push left 0.5", "push left 0.5", "dip 0.6"),
                  display="Bricolage Grotesque", body="Inter", accent="#ff5a1f", catalog="buckley-with-these-hands",
                  camera=True, template=None) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    cfg = {"title": "T", "width": 640, "height": 360, "fps": 30, "duration": 8.0, "background": "#0d0b0a",
           "audio": "audio/mix.json"}
    if template:
        cfg["template"] = template
    (d / "showtime.json").write_text(json.dumps(cfg), encoding="utf-8")
    (d / "audio").mkdir(exist_ok=True)
    (d / "audio" / "mix.json").write_text(json.dumps({"tracks": [{"id": "m", "kind": "music", "catalog": catalog}]}),
                                          encoding="utf-8")
    scenes = ['<section class="scene" id="s0" data-start="0" data-dur="2">%s<h1>A</h1>%s</section>' % (
        '<div class="cam" data-st="camera" data-path=\'[{"at":0,"zoom":1},{"at":1,"dur":1,"zoom":1.3}]\' data-drift="0.01">'
        if camera else "", "</div>" if camera else "")]
    prev = "s0"
    for i, tr in enumerate(transitions, 1):
        attr = ' data-transition="%s"' % tr if tr else ""
        scenes.append('<section class="scene" id="s%d" data-start="#%s" data-dur="2"%s><h2>B</h2></section>' % (i, prev, attr))
        prev = "s%d" % i
    html = """<!doctype html><html><head><script src="/_st/stage.js"></script>
<link rel="stylesheet" href="/_st/themes/%s.css">
<style>:root { --accent: %s; --font-display: '%s', sans-serif; --font-body: '%s', sans-serif; }</style>
</head><body>%s</body></html>""" % (theme, accent, display, body, "\n".join(scenes))
    (d / "index.html").write_text(html, encoding="utf-8")
    return d


class TestLook(unittest.TestCase):
    def test_project_look_fields(self):
        from st.variety import look
        p = write_project(TMP / "look-a", template="dom")
        lk = look.project_look(p)
        self.assertEqual(lk["template"], "dom")
        self.assertEqual(lk["template_source"], "showtime.json")
        self.assertEqual(lk["theme"], "bold")
        self.assertEqual(lk["type"][:2], ["Bricolage Grotesque", "Inter"])
        self.assertIn("#ff5a1f", lk["palette"])
        self.assertIn("#0d0b0a", lk["palette"])                      # the bold theme's ground
        self.assertEqual(lk["transitions"], {"push": 2, "dip": 1})
        self.assertIn("push-in", lk["camera"])
        self.assertIn("drift", lk["camera"])
        self.assertEqual(lk["music"][0]["ref"], "catalog:buckley-with-these-hands")
        self.assertTrue(lk["music"][0].get("shelf"), "the catalog's shelf travels with the track")
        self.assertEqual(lk["structure"]["scenes"], 4)
        self.assertEqual(lk["structure"]["durations"], [2.0, 2.0, 2.0, 2.0])
        self.assertEqual(lk["structure"]["shape"], "even")
        self.assertEqual(lk["structure"]["aspect"], "16:9")

    def test_cut_counted_and_inferred_template(self):
        from st.variety import look
        p = write_project(TMP / "look-b", transitions=("", "blur-dissolve 0.6"), camera=False)
        lk = look.project_look(p)
        self.assertEqual(lk["transitions"], {"cut": 1, "blur-dissolve": 1})
        self.assertEqual(lk["template"], "dom")
        self.assertEqual(lk["template_source"], "inferred")
        self.assertNotIn("camera", lk)

    def test_new_records_template(self):
        d = TMP / "new-dom"
        showtime("new", "dom", d)
        cfg = json.loads((d / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg.get("template"), "dom")
        from st.variety import look
        self.assertEqual(look.project_look(d)["theme"], "bold")

    def test_shipped_templates_read(self):
        """Every shipped template yields a look with a theme or palette and a type pair (no crash)."""
        from st.variety import look
        for t in ("dom", "launch", "short", "data", "film", "tutorial"):
            lk = look.project_look(SKILL / "templates" / t)
            self.assertTrue(lk.get("palette"), t)
            self.assertTrue(lk.get("type"), t)
            self.assertTrue(look.summary(lk), t)


class HistoryCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="hist-", dir=str(TMP)))
        self.old = os.environ.get("SHOWTIME_HISTORY_DIR")
        os.environ["SHOWTIME_HISTORY_DIR"] = str(self.dir)
        os.environ.pop("SHOWTIME_HISTORY", None)

    def tearDown(self):
        if self.old is None:
            os.environ.pop("SHOWTIME_HISTORY_DIR", None)
        else:
            os.environ["SHOWTIME_HISTORY_DIR"] = self.old
        os.environ.pop("SHOWTIME_HISTORY", None)


class TestHistory(HistoryCase):
    def look(self, name, **kw):
        from st.variety import look
        lk = look.project_look(write_project(TMP / ("h-" + name), **kw))
        lk["job"] = name
        lk["job_path"] = str(TMP / ("job-" + name))
        return lk

    def test_repeats_and_alternatives(self):
        from st.variety import history as h
        h.record(self.look("one"))
        h.record(self.look("two", theme="paper", display="Fraunces", accent="#2f6fbf", catalog="incompetech-crossing-the-chasm",
                           transitions=("crossfade 0.5",), camera=False))
        res = h.check(self.look("three"))
        self.assertEqual(res["compared"], ["two", "one"])
        self.assertEqual(res["level"], "warning")
        aspects = {r["aspect"]: r for r in res["repeats"]}
        for a in ("theme", "palette", "type", "transitions", "camera", "music", "structure"):
            self.assertIn(a, aspects, a)
            self.assertEqual(aspects[a]["jobs"], ["one"], a)
            alts = aspects[a]["alternatives"]
            self.assertEqual(len(alts), 2, (a, alts))
        # alternatives never propose what the recent jobs used
        self.assertFalse(any("theme bold" in x or "theme paper" in x for x in aspects["theme"]["alternatives"]))
        self.assertFalse(any(x.startswith(("push ", "dip ", "crossfade ")) for x in aspects["transitions"]["alternatives"]))
        self.assertFalse(any("buckley-with-these-hands" in x or "incompetech-crossing-the-chasm" in x
                             for x in aspects["music"]["alternatives"]))
        self.assertIn("theme (look) bold", res["message"])
        self.assertIn("theme (look):", res["fix"])
        text = h.format_text(res)
        self.assertIn("WARN", text)
        self.assertIn("try:", text)

    def test_fresh_look_and_self_excluded(self):
        from st.variety import history as h
        a = self.look("a")
        h.record(a)
        res = h.check(a)                      # the job itself is not a repeat of itself
        self.assertEqual(res["compared"], [])
        self.assertIn("no earlier jobs", h.format_text(res))
        b = self.look("b", theme="terminal", display="JetBrains Mono", body="JetBrains Mono", accent="#5cff8a",
                      catalog="incompetech-crossing-the-chasm", transitions=("", "", "", ""), camera=False, template="film")
        res = h.check(b)
        self.assertEqual(res["level"], "ok", res["repeats"])
        self.assertIn("look is fresh", h.format_text(res))

    def test_same_primary_transition_is_a_repeat(self):
        from st.variety import history as h
        h.record(self.look("push-led", transitions=("push left 0.5", "push left 0.5", "push left 0.5", "blur-dissolve 0.6",
                                                     "dip 0.6")))
        b = self.look("push-only", theme="paper", display="Fraunces", accent="#2f6fbf", catalog="incompetech-crossing-the-chasm",
                      transitions=("push left 0.4",) * 4, camera=False)
        self.assertIn("transitions", {r["aspect"] for r in h.check(b)["repeats"]})
        c = self.look("dip-led", theme="paper", display="Fraunces", accent="#2f6fbf", catalog="incompetech-crossing-the-chasm",
                      transitions=("dip 0.6",) * 3 + ("push left 0.5",), camera=False)
        self.assertNotIn("transitions", {r["aspect"] for r in h.check(c)["repeats"]})

    def test_same_brand_shares_palette_and_type(self):
        from st.variety import history as h
        a, b = self.look("brand-a"), self.look("brand-b", transitions=("crossfade 0.5",), camera=False,
                                                 catalog="incompetech-crossing-the-chasm")
        a["brand"] = b["brand"] = "Acme"
        h.record(a)
        aspects = {r["aspect"] for r in h.check(b)["repeats"]}
        self.assertNotIn("palette", aspects)
        self.assertNotIn("type", aspects)
        self.assertIn("theme", aspects)

    def test_only_last_five_and_cap(self):
        from st.variety import history as h
        h.record(self.look("old"))
        for i in range(5):
            h.record(self.look("other%d" % i, theme="neon", display="Unbounded", accent="#29e7ff",
                               catalog="incompetech-crossing-the-chasm", transitions=("crossfade 0.5",), camera=False))
        res = h.check(self.look("new"))
        self.assertNotIn("old", res["compared"])
        self.assertFalse(any("old" in r["jobs"] for r in res["repeats"]))
        for i in range(h.MAX_KEEP + 5):
            h.record({"job": "j%d" % i, "job_path": "/x/j%d" % i})
        self.assertEqual(len(h.load()), h.MAX_KEEP)

    def test_opt_out_and_clear(self):
        from st.variety import history as h
        os.environ["SHOWTIME_HISTORY"] = "off"
        self.assertIsNone(h.record(self.look("x")))
        self.assertFalse(h.file().exists())
        self.assertFalse(h.check(self.look("y"))["enabled"])
        os.environ.pop("SHOWTIME_HISTORY")
        h.set_enabled(False)
        self.assertIsNone(h.record(self.look("x")))
        h.set_enabled(True)
        h.record(self.look("x"))
        h.record(self.look("z"))
        self.assertEqual(h.clear("x"), 1)
        self.assertEqual([x["job"] for x in h.load()], ["z"])
        self.assertEqual(h.clear(), 1)
        self.assertFalse(h.file().exists())

    def test_cli_list_check_strict_off(self):
        env = dict(ENV, SHOWTIME_HISTORY_DIR=str(self.dir))
        from st.variety import history as h
        h.record(self.look("cli-one"))
        p = write_project(TMP / "h-cli-two")
        out = showtime("history", env=env).stdout
        self.assertIn("cli-one", out)
        self.assertIn("recently used", out)
        self.assertIn("local only", out)
        cp = showtime("history", "check", p, "--json", env=env)
        res = json.loads(cp.stdout)
        self.assertEqual(res["level"], "warning")
        self.assertEqual(showtime("history", "check", p, "--strict", env=env, check=False).returncode, 1)
        self.assertEqual(showtime("history", "check", p, env=env).returncode, 0)
        showtime("history", "off", env=env)
        self.assertIn("off", showtime("history", env=env).stdout)
        self.assertEqual(json.loads(showtime("history", "check", p, "--json", env=env).stdout)["enabled"], False)
        showtime("history", "on", env=env)
        self.assertIn("removed 1", showtime("history", "clear", env=env).stdout)


class TestReference(HistoryCase):
    @classmethod
    def setUpClass(cls):
        cls.video = reference_fixture()
        cls.out = TMP / "ref-a"
        from st.variety import reference
        cls.rep = reference.analyze(str(cls.video), cls.out, title="Pattern reel", target=20)

    def test_cuts_shots_pace(self):
        rep = self.rep
        self.assertEqual(len(rep["cuts"]), 3, rep["cuts"])
        for got, want in zip(rep["cuts"], (2.0, 3.5, 5.5)):
            self.assertAlmostEqual(got, want, delta=0.1)
        self.assertEqual(len(rep["shots"]), 4)
        self.assertEqual([c["kind"] for c in rep["scene_changes"]], ["cut"] * 3)
        self.assertAlmostEqual(rep["shot_lengths"]["median"], 1.75, delta=0.1)
        self.assertAlmostEqual(rep["pace"]["per_10s"], 3 * 10 / 7.0, delta=0.1)

    def test_push_transition_is_a_scene_change(self):
        """A 0.4 s slide between two held stills has no hard cut; it is still one scene change."""
        v = TMP / "slide.mp4"
        ffmpeg("-loop", "1", "-framerate", "30", "-t", "3", "-i", still("rgb", "testsrc", "640x360"),
               "-loop", "1", "-framerate", "30", "-t", "3", "-i", still("bars", "smptebars", "640x360"),
               "-filter_complex", "[0:v]format=yuv420p,setsar=1[a];[1:v]format=yuv420p,setsar=1[b];"
               "[a][b]xfade=transition=slideleft:duration=0.4:offset=2.5,format=yuv420p[v]",
               "-map", "[v]", "-c:v", "libx264", "-preset", "veryfast", "-t", "5.5", v)
        from st.variety import reference
        ch, _pic = reference.scene_changes(v, 5.5, 30.0)
        self.assertEqual(len(ch), 1, ch)
        self.assertAlmostEqual(ch[0]["t"], 2.7, delta=0.35)
        self.assertNotEqual(ch[0]["kind"], "cut")

    def test_per_shot_palette_motion_camera(self):
        shots = self.rep["shots"]
        self.assertEqual(shots[1]["camera"], "push-in", shots[1])
        self.assertEqual(shots[2]["camera"], "pan-right", shots[2])
        self.assertEqual(shots[3]["motion_label"], "still")
        self.assertEqual(shots[3]["camera"], "hold")
        self.assertEqual(shots[3]["palette"][0]["hex"][:2], "#2")          # 0x224488 -> #284888 bin
        self.assertGreater(shots[3]["palette"][0]["share"], 0.9)
        self.assertIn(shots[0]["motion_label"], ("medium", "fast", "slow"))
        self.assertTrue(self.rep["sound"]["present"])
        self.assertLess(self.rep["sound"]["silence_share"], 0.1)

    def test_files_and_brief(self):
        for f in ("reference.md", "reference.json", "sheet.jpg", "shots.jpg", "fingerprint.npz"):
            self.assertTrue((self.out / f).is_file(), f)
        md = (self.out / "reference.md").read_text(encoding="utf-8")
        for s in ("## Brief for the storyboard", "**Carry over (the style):**", "**Never (content):**",
                  "Style reference: Pattern reel", "about 11 shots or scenes in a 20 s video", "## Shots", "Its content never goes into your video"):
            self.assertIn(s, md)
        from PIL import Image
        with Image.open(self.out / "sheet.jpg") as im:
            w, h = im.size
        self.assertGreater(w, 500)
        self.assertFalse((self.out / "frames").exists(), "temporary frames are removed")

    def test_cli_into_job_with_credit(self):
        job = make_job("refjob")
        cp = showtime("reference", self.video, "--job", job, "--title", "Pattern reel", "--for", "15")
        self.assertIn("credit  \"Style reference: Pattern reel\"", cp.stdout)
        ref_dir = job / "references" / "pattern-reel"
        self.assertTrue((ref_dir / "reference.md").is_file())
        for name in ("credits.txt", "share.txt"):
            self.assertIn("Style reference: Pattern reel", (job / name).read_text(encoding="utf-8"), name)
        data = json.loads((job / "job.json").read_text(encoding="utf-8"))
        self.assertEqual(Path(data["pointers"]["reference"]).resolve(), ref_dir.resolve())
        # idempotent credit, a second analysis gets its own folder
        showtime("reference", "credit", job)
        self.assertEqual((job / "share.txt").read_text(encoding="utf-8").count("Style reference: Pattern reel"), 1)
        showtime("reference", self.video, "--job", job, "--title", "Pattern reel")
        self.assertTrue((job / "references" / "pattern-reel-2" / "reference.md").is_file())
        self.assertIn("pattern-reel-2", showtime("reference", "list", job).stdout)

    @needs_listen
    def test_url_direct_file_and_page(self):
        root = TMP / "served"
        root.mkdir(exist_ok=True)
        shutil.copy2(str(self.video), str(root / "clip.mp4"))
        (root / "page.html").write_text("<!doctype html><html><body>video page</body></html>", encoding="utf-8")
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):  # noqa: D401 - keep the test output clean
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(root)))
        th = threading.Thread(target=srv.serve_forever, daemon=True)
        th.start()
        try:
            port = srv.server_address[1]
            out = TMP / "ref-url"
            showtime("reference", "http://127.0.0.1:%d/clip.mp4" % port, "-o", out)
            rj = json.loads((out / "reference.json").read_text(encoding="utf-8"))
            self.assertEqual(len(rj["cuts"]), 3)
            self.assertTrue(rj["source"].startswith("http://127.0.0.1"))
            self.assertIn("127.0.0.1", rj["credit"])
            self.assertTrue(Path(rj["kept_copy"]).is_file())
            cp = showtime("reference", "http://127.0.0.1:%d/page.html" % port, "-o", TMP / "ref-page", check=False)
            self.assertNotEqual(cp.returncode, 0)
            self.assertIn("direct links to a video file", cp.stderr)
        finally:
            srv.shutdown()
            srv.server_close()


class TestGuard(HistoryCase):
    @classmethod
    def setUpClass(cls):
        cls.ref = reference_fixture()
        cls.ref_dir = TMP / "guard-ref"
        from st.variety import reference
        reference.analyze(str(cls.ref), cls.ref_dir, title="Pattern reel")
        cls.copy = TMP / "copy.mp4"
        ffmpeg("-i", cls.ref, "-c:v", "libx264", "-crf", "34", "-preset", "veryfast", "-c:a", "copy", cls.copy)
        cls.graded = TMP / "graded.mp4"
        ffmpeg("-i", cls.ref, "-vf", "crop=iw*0.94:ih*0.94,scale=640:360,eq=brightness=0.05:saturation=1.2",
               "-c:v", "libx264", "-preset", "veryfast", "-c:a", "copy", cls.graded)
        cls.flat = TMP / "flat.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=c=0x101418:s=320x180:r=30:d=5", "-c:v", "libx264", "-pix_fmt", "yuv420p", cls.flat)

    def cmp(self, video):
        from st.variety import guard
        return guard.compare(guard.fingerprint_video(video), guard.load_fingerprint(self.ref_dir / "fingerprint.npz"))

    def test_copies_fail(self):
        for v in (self.copy, self.graded):
            res = self.cmp(v)
            self.assertEqual(res["verdict"], "copy", (v.name, res))
            from st.variety import guard
            self.assertGreaterEqual(res["copy_share"], guard.COPY_FAIL)
            sev, rule, text = guard.message(dict(res, reference="Pattern reel"))
            self.assertEqual((sev, rule), ("FAIL", "reference_copy"))
            self.assertIn("Pattern reel", text)

    def test_unrelated_passes_flat_inconclusive(self):
        res = self.cmp(unrelated_fixture())
        self.assertEqual(res["verdict"], "ok", res)
        self.assertLess(res["copy_share"], 0.05)
        self.assertEqual(self.cmp(self.flat)["verdict"], "inconclusive")

    def test_rhythm_similarity(self):
        from st.variety import guard
        a = [2.0, 1.5, 2.0, 1.5, 3.0]
        self.assertEqual(guard.rhythm_similarity(a, [x * 2 for x in a]), 1.0)          # same rhythm, scaled
        self.assertLess(guard.rhythm_similarity(a, [1.0, 4.0, 1.0, 3.5, 0.5]), 0.5)
        self.assertEqual(guard.rhythm_similarity(a, [1.0] * 12), 0.0)                 # counts differ a lot
        self.assertIsNone(guard.rhythm_similarity([3.0, 4.0], a))

    def test_cli_check_against(self):
        cp = showtime("reference", "check", self.copy, "--against", self.ref_dir, check=False)
        self.assertEqual(cp.returncode, 1, cp.stdout)
        self.assertIn("FAIL  the render copies", cp.stdout)
        cp = showtime("reference", "check", unrelated_fixture(), "--against", self.ref)
        self.assertIn("PASS  not a copy", cp.stdout)

    def test_qa_guard_and_credit(self):
        job = make_job("guardjob")
        showtime("reference", self.ref, "--job", job, "--title", "Pattern reel")
        final = job / "final.mp4"
        shutil.copy2(str(self.copy), str(final))
        showtime("job", "note", job, "--output", "final=%s" % final)
        cp = showtime("qa", job, "--json", "--no-sheet", check=False)
        rep = json.loads(cp.stdout)
        rules = {f["rule"]: f for f in rep["findings"]}
        self.assertEqual(rules["reference_copy"]["severity"], "FAIL", rules)
        self.assertIn("fix", rules["reference_copy"])
        self.assertNotIn("reference_credit", rules)
        # an honest final passes the guard; a lost credit is a warning
        shutil.copy2(str(unrelated_fixture()), str(final))
        (job / "credits.txt").unlink()
        rep = json.loads(showtime("qa", final, "--json", "--no-sheet", check=False).stdout)
        rules = {f["rule"]: f for f in rep["findings"]}
        self.assertNotIn("reference_copy", rules)
        self.assertTrue(any("not a copy of the style reference" in p for p in rep["passed"]), rep["passed"])
        self.assertEqual(rules["reference_credit"]["severity"], "WARN")
        showtime("reference", "credit", job)
        rep = json.loads(showtime("qa", final, "--json", "--no-sheet", check=False).stdout)
        self.assertNotIn("reference_credit", {f["rule"] for f in rep["findings"]})

    def test_share_block_takes_over_the_line(self):
        from st.audio import credits
        block = credits.BLOCK_START + "\nTrack by Someone\nStyle reference: Pattern reel\n" + credits.BLOCK_END
        text = "My post\n\nStyle reference: Pattern reel\n"
        out = credits.upsert_block(text, block)
        self.assertEqual(out.count("Style reference: Pattern reel"), 1)
        self.assertTrue(out.startswith("My post"))
        # without the line in the block, the standalone line stays
        out = credits.upsert_block(text, credits.BLOCK_START + "\nTrack\n" + credits.BLOCK_END)
        self.assertEqual(out.count("Style reference: Pattern reel"), 1)


class TestQaRecordsLook(HistoryCase):
    def test_passing_final_is_recorded_then_repeated(self):
        env = dict(ENV, SHOWTIME_HISTORY_DIR=str(self.dir))
        job = make_job("lookjob")
        write_project(job / "project", template="dom")
        showtime("job", "note", job, "--project", job / "project", env=env)
        final = job / "final.mp4"
        shots_video(final, [("testsrc2=s={size}:r=30:d=4", 4.0)], size="640x360", tone=False)
        showtime("job", "note", job, "--output", "final=%s" % final, env=env)
        cfg = json.loads((job / "project" / "showtime.json").read_text(encoding="utf-8"))
        cfg["duration"] = 4.0
        (job / "project" / "showtime.json").write_text(json.dumps(cfg), encoding="utf-8")
        rep = json.loads(showtime("qa", job, "--json", "--no-sheet", env=env, check=False).stdout)
        self.assertIn(rep["verdict"], ("PASS", "WARN"), rep["findings"])
        looks = json.loads((self.dir / "looks.json").read_text(encoding="utf-8"))["looks"]
        self.assertEqual([x["job"] for x in looks], [job.name])
        self.assertEqual(looks[0]["theme"], "bold")
        # a preview or an export is not the job's final: nothing more is recorded
        showtime("qa", shots_video(TMP / "other.mp4", [("testsrc2=s={size}:r=30:d=2", 2.0)]), "--no-sheet",
                 env=env, check=False)
        self.assertEqual(len(json.loads((self.dir / "looks.json").read_text(encoding="utf-8"))["looks"]), 1)
        p2 = write_project(TMP / "second-project")
        res = json.loads(showtime("history", "check", p2, "--json", env=env).stdout)
        self.assertEqual(res["compared"], [job.name])
        self.assertIn("theme", {r["aspect"] for r in res["repeats"]})


@unittest.skipIf(FAST, "--fast: needs a browser (check and render)")
class TestBrowser(HistoryCase):
    def test_check_look_repeat_and_render_credit(self):
        env = dict(ENV, SHOWTIME_HISTORY_DIR=str(self.dir))
        from st.variety import history as h, look
        first = write_project(TMP / "b-first")
        lk = look.project_look(first)
        lk["job"] = "earlier-job"
        h.record(lk)
        job = make_job("browserjob")
        proj = job / "project"
        # the template's own look (a look signature would steer away from the earlier job: no repeat to report)
        showtime("new", "dom", proj, "--duration", "2", "--size", "640x360", "--look", "template", env=env)
        cp = showtime("check", proj, "--json", "--no-determinism", "--samples", "3", env=env, check=False)
        rep = json.loads(cp.stdout)
        codes = {f["code"]: f for f in rep["findings"]}
        self.assertIn("look_repeat", codes, [f["code"] for f in rep["findings"]])
        self.assertEqual(codes["look_repeat"]["severity"], "warning")
        self.assertIn("earlier-job", codes["look_repeat"]["message"])
        self.assertIn("showtime history check", codes["look_repeat"]["fix"])
        self.assertIn("repeats", rep["look"])
        rep2 = json.loads(showtime("check", proj, "--json", "--no-determinism", "--samples", "3", "--no-history",
                                   env=env, check=False).stdout)
        self.assertNotIn("look_repeat", {f["code"] for f in rep2["findings"]})
        # render keeps the style reference credit next to the final
        showtime("reference", reference_fixture(), "--job", job, "--title", "Pattern reel", env=env)
        showtime("render", proj, "--job", job, env=env)
        self.assertIn("Style reference: Pattern reel", (job / "credits.txt").read_text(encoding="utf-8"))
        self.assertIn("Style reference: Pattern reel", (job / "share.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

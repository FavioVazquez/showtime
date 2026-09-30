#!/usr/bin/env python3
"""The phone check: text held long enough to read, big enough on a phone, clear of platform UI, captions readable.

  * unit tests of scripts/lib/phone.mjs (reading speed per language, points at phone width, minimum size
    per aspect, the summary line) run through node, no browser; its defaults must equal runtime/thresholds.json;
  * `showtime qa` on a small synthetic video with a fabricated `showtime check` report and caption sidecars:
    PASS / FAIL with timestamps / PARTIAL (no report, another size, stale), captions counted in the line
    (no browser: runs under --fast);
  * `showtime check` on planted projects: small type, a line that disappears too soon, the same line held
    for the same time in English and in Japanese, a 9:16 call to action under the platform UI, --no-timeline.

--fast (CI): skips everything that needs a browser. Stdlib only. usage: python tests/test_phone.py [--fast] [-v]
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
PHONE_MJS = SKILL / "scripts" / "lib" / "phone.mjs"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())


def showtime(*args, check=True, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def node_json(code):
    """Run a snippet of ES-module JS with phone.mjs imported as P; it must console.log one JSON value."""
    head = "import * as P from %s;\n" % json.dumps(PHONE_MJS.as_uri())
    cp = subprocess.run([shutil.which("node") or "node", "--input-type=module", "-e", head + code],
                        capture_output=True, text=True, timeout=60)
    assert cp.returncode == 0, cp.stderr[-2000:]
    return json.loads(cp.stdout.strip().splitlines()[-1])


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_video(path, size="360x640", secs=3):
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                         "testsrc2=size=%s:rate=30" % size, "-t", str(secs), "-pix_fmt", "yuv420p", str(path)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")
    return path


def page(body, style=""):
    return ("<!doctype html><html><head><meta charset=\"utf-8\"><script src=\"/_st/stage.js\"></script>"
            "<style>body{margin:0;background:#101418;color:#f4f6fa;font:600 44px sans-serif}"
            ".s{position:absolute;inset:0}.t{position:absolute;left:100px;width:1000px}.bar{position:absolute;left:0;top:0;height:8px;"
            "background:#fc3;width:calc(var(--p) * 100%%)}" + style + "</style></head><body>" + body + "</body></html>")


def phone_of(proj, *args):
    cp = showtime("check", proj, "--json", "--no-determinism", "--samples", "3", *args, check=False, timeout=240)
    rep = json.loads(cp.stdout)
    return rep, rep["phone"]


class UnitTests(unittest.TestCase):
    def test_00_defaults_equal_thresholds_json(self):
        th = json.loads((SKILL / "runtime" / "thresholds.json").read_text(encoding="utf-8"))
        d = node_json("console.log(JSON.stringify(P.DEFAULTS))")
        for k in ("phone_width_pt", "phone_min_pt", "reading_lead_s", "reading_min_s", "reading"):
            self.assertEqual(th[k], d[k], k)
        cfg = node_json("console.log(JSON.stringify(P.phoneConfig(%s)))" % json.dumps(th))
        self.assertEqual(cfg["phone_min_pt"], th["phone_min_pt"])
        self.assertEqual(cfg["reading"]["ja"]["cps"], 4)

    def test_01_reading_speed_per_language(self):
        r = node_json("""
const en = 'x'.repeat(34), few = 'a b c d e f g h i j';
console.log(JSON.stringify({
  en: P.readNeed(en, 'en'), es: P.readNeed(en, 'es-419'), nolang: P.readNeed(en, ''), short: P.readNeed('Hi', 'en'),
  words: P.readNeed(few, 'en'), ja: P.readNeed('x'.repeat(20), 'ja'), zh: P.readNeed('x'.repeat(18), 'zh-Hans'),
  ko: P.readNeed('x'.repeat(24), 'ko'), chars: P.readNeed('whatever', 'en', undefined, 51),
  tokens: P.readNeed('a % b · c', 'en'),
  rateEn: P.readingRate('en'), rateJa: P.readingRate('ja'),
  custom: P.readNeed(en, 'en', P.phoneConfig({ reading: { default: { cps: 10, wps: 2 } }, reading_lead_s: 0 })),
}));""")
        self.assertAlmostEqual(r["en"], 0.3 + 34 / 17, places=6)      # the long-standing rule: 17 characters/s + 0.3 s
        self.assertEqual(r["es"], r["en"])
        self.assertEqual(r["nolang"], r["en"])
        self.assertEqual(r["short"], 1.0)                              # never under one second
        self.assertAlmostEqual(r["words"], 0.3 + 10 / 3.0, places=6)   # ten one-letter words: the words/s time wins
        self.assertAlmostEqual(r["ja"], 0.3 + 20 / 4.0, places=6)      # characters/s only
        self.assertAlmostEqual(r["zh"], 0.3 + 18 / 9.0, places=6)
        self.assertAlmostEqual(r["ko"], 0.3 + 24 / 12.0, places=6)
        self.assertAlmostEqual(r["chars"], 0.3 + 51 / 17, places=6)    # check passes a block's own character count
        self.assertAlmostEqual(r["tokens"], 0.3 + 3 / 3.0)             # 3 words: "%" and "·" are not words
        self.assertEqual(r["rateEn"], {"cps": 17, "wps": 3})
        self.assertEqual(r["rateJa"], {"cps": 4, "wps": None})
        self.assertAlmostEqual(r["custom"], 34 / 10.0, places=6)

    def test_02_points_and_minimum_per_aspect(self):
        r = node_json("""
console.log(JSON.stringify({
  asp: [P.aspectClass(1920, 1080), P.aspectClass(1080, 1920), P.aspectClass(1080, 1350), P.aspectClass(1080, 1080),
        P.aspectClass(3840, 2160), P.aspectClass(360, 640), P.aspectClass(1024, 1280)],
  pt: P.ptOf(48, 1920), pt2: P.ptOf(48, 1080),
  m169: P.minSize(1920, 1080), m916: P.minSize(1080, 1920), m11: P.minSize(1080, 1080), m45: P.minSize(1080, 1350),
  lang: [P.langBase('es-419'), P.langBase('JA'), P.langBase(''), P.langBase(null), P.langBase('zh_Hans')],
}));""")
        self.assertEqual(r["asp"], ["16:9", "9:16", "4:5", "1:1", "16:9", "9:16", "4:5"])
        self.assertAlmostEqual(r["pt"], 48 * 390 / 1920)
        self.assertAlmostEqual(r["pt2"], 48 * 390 / 1080)
        th = json.loads((SKILL / "runtime" / "thresholds.json").read_text(encoding="utf-8"))["phone_min_pt"]
        self.assertEqual(r["m169"]["pt"], th["16:9"])
        self.assertAlmostEqual(r["m169"]["px"], th["16:9"] * 1920 / 390)
        self.assertAlmostEqual(r["m916"]["px"], th["9:16"] * 1080 / 390)
        self.assertEqual((r["m11"]["aspect"], r["m45"]["aspect"]), ("1:1", "4:5"))
        self.assertEqual(r["lang"], ["es", "ja", "en", "en", "zh"])
        # vertical formats are phone-only, so their minimum is higher than a landscape frame's
        self.assertGreater(th["9:16"], th["4:5"])
        self.assertGreater(th["4:5"], th["1:1"] - 1)
        self.assertGreater(th["1:1"], th["16:9"])

    def test_03_summary_and_line(self):
        r = node_json("""
const ph = P.createPhone({ W: 1920, H: 1080, lang: 'en' });
ph.observe('a', 'Big title', 120, 1.0); ph.observe('b', 'Small print', 40, 2.5); ph.observe('b', 'Small print', 60, 3.0);
const ok = ph.summarize([{ severity: 'info', code: 'small_text', message: 'x' }, { severity: 'warning', code: 'dead_air', message: 'x' }]);
const bad = ph.summarize([
  { severity: 'warning', code: 'tiny_text', t: 4, px: 20, message: '"Free tier" is 20px on screen' },
  { severity: 'warning', code: 'short_text', t: 1.5, held: 0.8, need: 2.1, message: '"Sign up today" is readable for only ~0.8s' },
  { severity: 'warning', code: 'safe_zone', t: 9, message: '"Link in bio" is outside the vertical safe zone' }]);
const nt = P.createPhone({ W: 1080, H: 1920 }).summarize([], { timelineRan: false });
console.log(JSON.stringify({ ok, bad, line_ok: P.phoneLine(ok), line_bad: P.phoneLine(bad), line_nt: P.phoneLine(nt), none: P.phoneLine(null) }));""")
        self.assertTrue(r["ok"]["ok"])
        self.assertEqual(r["ok"]["items"], [])                         # notes and other warnings are not phone items
        self.assertEqual(r["ok"]["smallest"]["px"], 40)                # the smallest sighting of a text
        self.assertEqual(r["ok"]["smallest"]["pt"], round(40 * 390 / 1920, 1))
        self.assertEqual(r["ok"]["scale"], round(390 / 1920, 4))
        self.assertEqual(r["ok"]["texts"], 2)
        self.assertEqual([i["part"] for i in r["bad"]["items"]], ["reading", "size", "zone"])   # by time
        self.assertFalse(r["bad"]["ok"])
        self.assertTrue(r["line_ok"].startswith("phone check: PASS ("), r["line_ok"])
        self.assertIn("smallest text 8.1 pt", r["line_ok"])
        self.assertIn("17 characters/s or 3 words/s (en)", r["line_ok"])
        self.assertTrue(r["line_bad"].startswith("phone check: FAIL - "), r["line_bad"])
        for want in ('reading "Sign up today" 0.8s of 2.1s at 0:01.5', 'type 4.1 pt "Free tier" at 0:04.0', 'under platform UI "Link in bio" at 0:09.0'):
            self.assertIn(want, r["line_bad"])
        self.assertIn("reading time not checked", r["line_nt"])
        self.assertEqual(r["none"], "phone check: not run")


class QaPhoneTests(unittest.TestCase):
    """qa's line, on a synthetic 9:16 video with a hand-made check report (no browser)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-phone-"))
        cls.video = make_video(cls.tmp / "v.mp4")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def project(self, name, phone=None, size=(360, 640), stale=False):
        proj = self.tmp / name
        write(proj / "index.html", "<!doctype html><title>x</title>")
        write(proj / "showtime.json", json.dumps({"width": size[0], "height": size[1], "fps": 30, "duration": 3}))
        if phone is not None:
            write(proj / "work" / "check" / "report.json", json.dumps({"info": {"width": size[0], "height": size[1]}, "phone": phone, "texts": []}))
            if stale:
                old = (proj / "work" / "check" / "report.json").stat().st_mtime - 100
                os.utime(proj / "index.html", (old + 200, old + 200))
                os.utime(proj / "work" / "check" / "report.json", (old, old))
        return proj

    def qa(self, proj=None, *extra):
        args = ["qa", self.video, "--json", "--no-sheet", "--out", self.tmp / "qa-out"]
        if proj is not None:
            args += ["--project", proj]
        cp = showtime(*(args + list(extra)), check=False)
        return json.loads(cp.stdout)

    GOOD = {"ok": True, "aspect": "9:16", "min_pt": 15, "lang": "en", "reading": {"cps": 17, "wps": 3.0},
            "checked": {"size": True, "zones": True, "reading": True}, "smallest": {"text": "Hook", "px": 60, "pt": 21.7, "t": 1},
            "items": []}

    def test_01_no_report_is_partial_and_only_a_note(self):
        rep = self.qa(self.project("noreport"))
        self.assertEqual(rep["phone"]["verdict"], "PARTIAL")
        self.assertTrue(rep["phone"]["line"].startswith("phone check: PARTIAL ("), rep["phone"]["line"])
        self.assertIn("showtime check", rep["phone"]["line"])
        rules = {f["rule"]: f["severity"] for f in rep["findings"]}
        self.assertEqual(rules.get("phone_unverified"), "INFO")        # never a WARN: nothing that passed before fails now
        self.assertFalse([f for f in rep["findings"] if f["rule"].startswith("phone_") and f["severity"] != "INFO"])
        rep = self.qa(None)                                             # no project at all
        self.assertEqual(rep["phone"]["verdict"], "PARTIAL")
        self.assertIn("no project found", rep["phone"]["line"])

    def test_02_pass_line_with_captions(self):
        srt = write(self.tmp / "ok.srt", "1\n00:00:00,200 --> 00:00:02,000\nThe hook lands here\n\n2\n00:00:02,100 --> 00:00:02,900\nThen it ends\n") or self.tmp / "ok.srt"
        rep = self.qa(self.project("good", self.GOOD), "--captions", srt)
        self.assertEqual(rep["phone"]["verdict"], "PASS", rep["phone"]["line"])
        line = rep["phone"]["line"]
        self.assertTrue(line.startswith("phone check: PASS ("), line)
        for want in ("smallest text 21.7 pt", "minimum 15 pt for 9:16", "17 characters/s or 3 words/s (en)", "nothing under platform UI",
                     "captions: 2 cues, longest line 19 characters"):
            self.assertIn(want, line)
        self.assertFalse([f for f in rep["findings"] if f["rule"].startswith("phone_")])
        # the text output prints it as its own line, before the findings
        cp = showtime("qa", self.video, "--project", self.tmp / "good", "--no-sheet", "--out", self.tmp / "qa-out2", "--captions", srt, check=False)
        self.assertIn("\n  phone check: PASS (", cp.stdout)

    def test_03_failing_items_carry_timestamps(self):
        bad = dict(self.GOOD, ok=False, items=[
            {"part": "size", "code": "tiny_text", "severity": "warning", "t": 4.0, "pt": 6.1, "px": 17, "message": '"Free tier" is 17px on screen'},
            {"part": "reading", "code": "short_text", "severity": "warning", "t": 1.5, "held": 0.8, "need": 2.1, "message": '"Sign up today" is readable for only ~0.8s'},
            {"part": "zone", "code": "safe_zone", "severity": "warning", "t": 2.5, "message": '"Link in bio" is outside the vertical safe zone'}])
        rep = self.qa(self.project("bad", bad))
        ph = rep["phone"]
        self.assertEqual(ph["verdict"], "FAIL")
        for want in ('type 6.1 pt "Free tier" at 0:04.0', 'reading "Sign up today" 0.8s of 2.1s at 0:01.5', 'under platform UI "Link in bio" at 0:02.5'):
            self.assertIn(want, ph["line"])
        got = {(f["rule"], f["severity"], f.get("t")) for f in rep["findings"] if f["rule"].startswith("phone_")}
        self.assertEqual(got, {("phone_size", "WARN", 4.0), ("phone_reading", "WARN", 1.5), ("phone_zone", "WARN", 2.5)})
        self.assertEqual(rep["verdict"], "WARN")                        # a phone-check failure is a WARN, never a FAIL
        self.assertTrue(all(f.get("frame") for f in rep["findings"] if f["rule"].startswith("phone_") and f["t"] < 3), "frames at the timestamps")

    def test_04_caption_problems_are_part_of_the_line(self):
        srt = self.tmp / "fast.srt"
        write(srt, "1\n00:00:00,100 --> 00:00:00,900\nThis caption is far too long to read in under a second\n\n"
                   "2\n00:00:01,000 --> 00:00:02,900\nThe second one is short and fine\n")
        rep = self.qa(self.project("goodcap", self.GOOD), "--captions", srt)
        self.assertEqual(rep["phone"]["verdict"], "FAIL", rep["phone"]["line"])
        self.assertIn("caption too fast to read at 0:00.1", rep["phone"]["line"])
        self.assertIn("caption_fast", [f["rule"] for f in rep["findings"]])
        # captions alone: no check report, a good sidecar
        ok = self.tmp / "ok2.srt"
        write(ok, "1\n00:00:00,200 --> 00:00:02,500\nA short readable caption\n")
        rep = self.qa(self.project("capsonly"), "--captions", ok)
        self.assertEqual(rep["phone"]["verdict"], "PARTIAL")
        self.assertIn("captions: 1 cues", rep["phone"]["line"])

    def test_05_other_size_and_stale_report_are_partial_or_noted(self):
        other = self.project("other", self.GOOD, size=(1920, 1080))     # the report is for a 16:9 project, the video is 9:16
        rep = self.qa(other)
        self.assertEqual(rep["phone"]["verdict"], "PARTIAL")
        self.assertIn("ran at 1920x1080", rep["phone"]["line"])
        rep = self.qa(self.project("stale", self.GOOD, stale=True))
        self.assertEqual(rep["phone"]["verdict"], "PASS")
        self.assertIn("older than the project sources", rep["phone"]["line"])
        nt = dict(self.GOOD, checked={"size": True, "zones": True, "reading": False})
        rep = self.qa(self.project("notimeline", nt))
        self.assertIn("reading time was not checked", rep["phone"]["line"])
        self.assertNotIn("held to its reading time", rep["phone"]["line"])

    def test_06_rules_are_documented(self):
        doc = (SKILL / "references" / "qa.md").read_text(encoding="utf-8")
        from st.qa import video as V
        for rule in ("phone_size", "phone_reading", "phone_zone", "phone_unverified"):
            self.assertIn(rule, V.RULES)
            self.assertTrue("`%s`" % rule in doc, "qa.md does not document " + rule)
        self.assertIn("phone check", doc)


@unittest.skipIf(FAST, "--fast (needs a browser)")
class CheckPhoneTests(unittest.TestCase):
    """`showtime check` on planted projects (1280x720 unless noted): the phone block of report.json."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-phone-check-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def make(self, name, body, *, size=(1280, 720), duration=6, extra=None, style=""):
        proj = self.tmp / name
        cfg = {"width": size[0], "height": size[1], "fps": 30, "duration": duration, "background": "#101418"}
        cfg.update(extra or {})
        write(proj / "showtime.json", json.dumps(cfg))
        write(proj / "index.html", page(body, style))
        return proj

    def test_01_readable_project_passes(self):
        proj = self.make("ok", '<section class="s" data-start="0" data-dur="6"><div class="bar"></div><div class="t" style="top:280px">Ship it on Friday</div></section>')
        rep, ph = phone_of(proj)
        self.assertTrue(ph["ok"], ph["items"])
        self.assertEqual((ph["aspect"], ph["min_pt"], ph["lang"]), ("16:9", 5, "en"))
        self.assertTrue(ph["checked"]["reading"])
        self.assertEqual(ph["smallest"]["px"], 44)
        self.assertEqual(ph["smallest"]["pt"], round(44 * 390 / 1280, 1))
        cp = showtime("check", proj, "--no-determinism", "--samples", "3", check=False, timeout=240)
        self.assertIn("phone check: PASS (", cp.stdout)

    def test_02_small_type_is_flagged_in_points(self):
        proj = self.make("small", '<section class="s" data-start="0" data-dur="6"><div class="bar"></div><div class="t" style="top:280px">Ship it on Friday</div>'
                                   '<div class="t" style="top:500px;font-size:13px">Terms and conditions apply to every offer</div></section>')
        rep, ph = phone_of(proj)
        self.assertFalse(ph["ok"])
        it = [i for i in ph["items"] if i["part"] == "size"]
        self.assertEqual(len(it), 1, ph["items"])
        self.assertEqual(it[0]["px"], 13)
        self.assertAlmostEqual(it[0]["pt"], 13 * 390 / 1280, delta=0.06)
        self.assertLess(it[0]["pt"], ph["min_pt"])
        self.assertIn("pt on a 390 pt wide phone", it[0]["message"])
        self.assertIn("Terms and conditions", it[0]["message"])
        self.assertEqual([f["severity"] for f in rep["findings"] if f["code"] == "tiny_text"], ["warning"])
        cp = showtime("check", proj, "--no-determinism", "--samples", "3", check=False, timeout=240)
        self.assertIn("phone check: FAIL - type", cp.stdout)
        self.assertRegex(cp.stdout, r'type [0-9.]+ pt "Terms and conditions[^"]*" at 0:0')

    def test_03_text_that_disappears_too_soon(self):
        long_line = "Every note stays on your own device for good"      # 44 characters: needs ~2.9 s
        proj = self.make("fast", '<section class="s" data-start="0" data-dur="1"><div class="bar"></div><div class="t" style="top:280px">%s</div></section>'
                                  '<section class="s" data-start="1" data-dur="5"><div class="bar"></div><div class="t" style="top:280px">Ship it on Friday</div></section>' % long_line)
        rep, ph = phone_of(proj)
        it = [i for i in ph["items"] if i["part"] == "reading"]
        self.assertEqual(len(it), 1, ph["items"])
        self.assertLess(it[0]["held"], it[0]["need"])
        self.assertAlmostEqual(it[0]["need"], max(0.3 + 44 / 17, 0.3 + 9 / 3.0), delta=0.02)   # 44 characters, 9 words
        self.assertLess(it[0]["t"], 0.5)
        self.assertIn("17 characters/s or 3 words/s (en)", it[0]["message"])
        self.assertFalse(ph["ok"])

    def test_04_reading_speed_follows_the_language(self):
        text = "Notes stay on device"                                  # 20 characters, 4 words
        body = ('<section class="s" data-start="0" data-dur="3"><div class="bar"></div><div class="t" style="top:280px">%s</div></section>'
                '<section class="s" data-start="3" data-dur="3"><div class="bar"></div><div class="t" style="top:280px">Ship it on Friday</div></section>' % text)
        rep, ph = phone_of(self.make("en", body))
        self.assertEqual([i for i in ph["items"] if i["part"] == "reading"], [])   # 0.3 + 20/17 = 1.5 s, held 3 s
        rep, ph = phone_of(self.make("ja", body, extra={"lang": "ja"}))
        it = [i for i in ph["items"] if i["part"] == "reading"]
        self.assertEqual(len(it), 1, ph["items"])                       # 0.3 + 20/4 = 5.3 s
        self.assertEqual(ph["lang"], "ja")
        self.assertEqual(ph["reading"]["cps"], 4)
        self.assertIsNone(ph["reading"]["wps"])

    def test_05_no_timeline_says_reading_was_not_checked(self):
        proj = self.make("nt", '<section class="s" data-start="0" data-dur="6"><div class="bar"></div><div class="t" style="top:280px">Ship it on Friday</div></section>')
        rep, ph = phone_of(proj, "--no-timeline")
        self.assertFalse(ph["checked"]["reading"])
        cp = showtime("check", proj, "--no-determinism", "--no-timeline", "--samples", "3", check=False, timeout=240)
        self.assertIn("reading time not checked", cp.stdout)

    def test_06_vertical_text_under_platform_ui(self):
        src = TESTS_DIR / "fixtures" / "defects" / "text-outside-safe-zone"
        proj = self.tmp / "zone"
        shutil.copytree(str(src), str(proj))
        rep, ph = phone_of(proj, "--no-timeline")
        self.assertEqual(ph["aspect"], "9:16")
        zone = [i for i in ph["items"] if i["part"] == "zone"]
        self.assertTrue(zone and zone[0]["code"] == "safe_zone", ph["items"])
        self.assertIn("Link in bio", zone[0]["message"])
        self.assertFalse(ph["ok"])

    def test_07_qa_reads_the_check_report(self):
        """check writes the block, qa (on a video of the same size) quotes it: the two agree."""
        proj = self.make("qa", '<section class="s" data-start="0" data-dur="6"><div class="bar"></div><div class="t" style="top:280px">Ship it on Friday</div>'
                                '<div class="t" style="top:500px;font-size:13px">Terms and conditions apply</div></section>')
        rep, ph = phone_of(proj)
        video = make_video(self.tmp / "q.mp4", size="1280x720", secs=6)
        cp = showtime("qa", video, "--project", proj, "--json", "--no-sheet", "--out", self.tmp / "qa-out", check=False)
        q = json.loads(cp.stdout)
        self.assertEqual(q["phone"]["verdict"], "FAIL")
        self.assertIn("Terms and conditions", q["phone"]["line"])
        self.assertEqual(len([i for i in q["phone"]["items"] if i["part"] == "size"]), 1)


class SourcesMatchThresholds(unittest.TestCase):
    """The reading-speed numbers were once written from memory: they are now checked against the public sources,
    and references/qa.md must cite each one and quote the same value as runtime/thresholds.json."""
    SOURCES = {
        "ja": ("215767517-Japanese-Timed-Text-Style-Guide", "Japanese 4 "),
        "zh": ("215986007-Chinese-Simplified-Timed-Text-Style-Guide", "Simplified Chinese 9 "),
        "ko": ("216001127-Korean-Timed-Text-Style-Guide", "Korean 12 "),
    }

    def setUp(self):
        self.th = json.loads((SKILL / "runtime" / "thresholds.json").read_text(encoding="utf-8"))["reading"]
        text = (SKILL / "references" / "qa.md").read_text(encoding="utf-8")
        row = [ln for ln in text.splitlines() if ln.startswith("| Reading time")]
        self.assertEqual(len(row), 1)
        self.row = row[0]

    def test_each_number_cites_its_source_and_agrees(self):
        for lang, (url, quoted) in self.SOURCES.items():
            self.assertIn("https://partnerhelp.netflixstudios.com/hc/en-us/articles/" + url, self.row, lang)
            self.assertIn(quoted, self.row, lang)
            self.assertIn("`%s` %d" % (lang, self.th[lang]["cps"]), self.row, lang)
        self.assertIn("English 20 characters/s (17 for children", self.row)
        self.assertIn("default 17 characters/s", self.row)
        self.assertEqual(self.th["default"]["cps"], 17)
        # 3 words/s is 180 words/min: the top of the BBC's 160-180 wpm, under the 238 wpm silent adult rate
        self.assertEqual(self.th["default"]["wps"] * 60, 180)
        for want in ("160-180 wpm", "clevercast.com/bbc-subtitling-guidelines", "238 wpm", "10.1016/j.jml.2019.104047"):
            self.assertIn(want, self.row)
        self.assertNotIn("Recalled from", self.row)


if __name__ == "__main__":
    sys.argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(verbosity=2 if "-v" in sys.argv else 1)

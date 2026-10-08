#!/usr/bin/env python3
"""The showreel tone ("go all out"): picked from the brief's words or set explicitly, and what it changes.

  * the brief's words: lib/st/showreel.py and its JS twin scripts/lib/showreel.mjs agree on every brief, and on the
    numbers (runtime/thresholds.json "showreel"); the precedence (showtime.json tone, the job's tone, the brief);
  * the flash-word exemption is tight: only marked text, only in the showreel tone, only 1-3 words, never under
    0.2 s; the phone check names the hero line and counts the exempt words;
  * qa: the flash safety limit on every video, showreel density (12 per 15 s), a long end card and look-alike
    shots instead of the launch grammar (st.qa.reel), the critic brief's showreel rubric; `showtime new --tone` and a
    job whose brief says showreel; the showreel template at the bar (13-14 shots, a ~1 s end card, no trick twice);
  * `showtime check` on planted projects (browser): flash words pass only in the tone, a long line still fails,
    an all-flash reel has no hero line, a frozen stretch is still a problem.

--fast (CI): skips the browser part. Stdlib only. usage: python tests/test_showreel.py [--fast] [-v]
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
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
REEL_MJS = SKILL / "scripts" / "lib" / "showreel.mjs"
PHONE_MJS = SKILL / "scripts" / "lib" / "phone.mjs"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff, showreel  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())

ROUND1 = ("make a dynamic 15-second motion graphics video that shows what an incredible motion designer you are, "
          "like it's your showreel for a résumé. go all out.")
BRIEFS = [
    ROUND1,
    "Go all out on this one",
    "an all-out sizzle for the conference",
    "cut a demo reel from these clips",
    "make my 2026 motion reel",
    "a hype reel for the team offsite",
    "Show off what the renderer can do",
    "showing off the new shaders",
    "Show-reel, 20 seconds, vertical",
    "a launch video for acme-cli",                 # none
    "a hype video for our launch",                 # bare "hype" stays a launch word
    "don't go all out, keep it calm",              # negated
    "no need to go all out here",                  # negated
    "we rolled the feature out to all users",      # no phrase
    "",
]


def showtime(*args, check=True, timeout=300, cwd=None):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV, cwd=cwd,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def node_json(code, mod=REEL_MJS, name="R"):
    head = "import * as %s from %s;\n" % (name, json.dumps(mod.as_uri()))
    cp = subprocess.run([shutil.which("node") or "node", "--input-type=module", "-e", head + code],
                        capture_output=True, text=True, timeout=60)
    assert cp.returncode == 0, cp.stderr[-2000:]
    return json.loads(cp.stdout.strip().splitlines()[-1])


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def ffmpeg(*args):
    cp = subprocess.run([ff.ffmpeg_path(), "-v", "error", "-nostdin", "-y"] + [str(a) for a in args],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")


# fourteen flat colours, each in its own cell of qa's 64-bin colour histogram (channels at 32, 96, 160 or 224)
FOURTEEN = ["#e02020", "#2020e0", "#e0e0e0", "#202020", "#e0e020", "#e020e0", "#20e0e0", "#20e020", "#a06020",
            "#6020a0", "#20a060", "#a0a0a0", "#606060", "#e0a060"]


def cuts_video(path, colors, seg, still_tail=0.0):
    """Hard cuts between flat colours with moving grain (never frozen), `seg` seconds each, 320x180 at 30 fps;
    still_tail: the last colour then holds that many more seconds without grain (a still end card)."""
    parts = ["color=c=%s:s=320x180:r=30:d=%g,noise=alls=14:allf=t,format=yuv420p[v%d]" % (c, seg, i)
             for i, c in enumerate(colors)]
    if still_tail:
        parts.append("color=c=%s:s=320x180:r=30:d=%g,format=yuv420p[v%d]" % (colors[-1], still_tail, len(colors)))
        colors = list(colors) + [colors[-1]]
    parts = ";".join(parts)
    ins = "".join("[v%d]" % i for i in range(len(colors)))
    ffmpeg("-filter_complex", "%s;%sconcat=n=%d:v=1:a=0[o]" % (parts, ins, len(colors)), "-map", "[o]",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", path)
    return path


class BriefWordsTests(unittest.TestCase):
    def test_python_and_js_agree_on_every_brief(self):
        js = node_json("console.log(JSON.stringify(%s.map((b) => R.briefWords(b))))" % json.dumps(BRIEFS))
        py = [showreel.brief_words(b) for b in BRIEFS]
        self.assertEqual(py, js)
        self.assertEqual(py[0], "showreel")                      # the round-1 prompt
        self.assertEqual(py[1:9], ["go all out", "all-out", "demo reel", "motion reel", "hype reel", "show off",
                                   "showing off", "show-reel"])
        self.assertEqual(py[9:], [None] * 6)

    def test_numbers_agree(self):
        th = json.loads((SKILL / "runtime" / "thresholds.json").read_text(encoding="utf-8"))["showreel"]
        self.assertEqual(showreel.DEFAULTS, th)
        self.assertEqual(node_json("console.log(JSON.stringify(R.DEFAULTS))"), th)
        self.assertEqual(showreel.thresholds(), th)
        self.assertEqual(node_json("console.log(JSON.stringify(R.showreelConfig({showreel: {flash_min_s: 0.3, x: 1}})))"),
                         dict(th, flash_min_s=0.3))

    def test_precedence(self):
        goal = {"goal": "go all out"}
        cases = [
            ({"tone": "showreel"}, {}, (True, "project")),
            ({"tone": "Showreel "}, {}, (True, "project")),
            ({"tone": "polished"}, goal, (False, "project")),     # an explicit other tone wins over the brief
            ({"tone": "default"}, {"tone": "showreel"}, (False, "project")),
            ({}, {"tone": "showreel"}, (True, "job")),
            ({}, dict(goal, tone="cinematic"), (False, "job")),
            ({}, goal, (True, "brief")),
            ({}, {"goal": "a launch video", "request": ROUND1}, (True, "brief")),
            ({}, {"goal": "a launch video"}, (False, "default")),
            (None, None, (False, "default")),
        ]
        js = node_json("console.log(JSON.stringify(%s.map(([c, j]) => R.resolveShowreel(c, j))))"
                       % json.dumps([[c, j] for c, j, _ in cases]))
        for (c, j, want), got_js in zip(cases, js):
            got = showreel.resolve(c, j)
            self.assertEqual((got["on"], got["source"]), want, (c, j))
            self.assertEqual(got, got_js, (c, j))


class FlashRuleTests(unittest.TestCase):
    def verdicts(self, rows):
        return node_json("console.log(JSON.stringify(%s.map((r) => R.flashVerdict(r).reason)))" % json.dumps(rows))

    def test_exemption_is_tight(self):
        base = {"text": "TYPE.", "flash": True, "held": 0.33, "on": True}
        rows = [
            base,
            dict(base, flash=False),                                   # unmarked text keeps the reading rule
            dict(base, on=False),                                      # marked, but not a showreel
            dict(base, text="Ship it on Friday, every week"),          # a sentence is message, not texture
            dict(base, text="ABCDEFGHIJKLMNOPQRSTUVWXYZ"),             # 26 characters: too long
            dict(base, text="TYPE IN MOTION"),                         # 3 words, 14 characters: texture
            dict(base, held=0.1),                                      # a glitch frame, not a word
            dict(base, held=0.15, slack=0.05),                         # within the sampling step
        ]
        self.assertEqual(self.verdicts(rows), ["flash", "unmarked", "tone-off", "too-long", "too-long", "flash",
                                               "too-short", "flash"])
        notes = node_json("console.log(JSON.stringify(['tone-off', 'too-long', 'too-short', 'unmarked'].map((r) => R.flashNote(r))))")
        self.assertIn('"tone": "showreel"', notes[0])
        self.assertIn("3 words and 24 characters", notes[1])
        self.assertIn("0.2s", notes[2])
        self.assertEqual(notes[3], "")

    def test_phone_check_names_the_hero_line(self):
        r = node_json("""
const f = { severity: 'warning', code: 'no_hero_line', t: 1.5, message: 'every text in this showreel is a flash word' };
const ph = P.createPhone({ W: 1920, H: 1080 });
const bad = ph.summarize([f], { flashExempt: 4 });
const good = P.createPhone({ W: 1920, H: 1080 }).summarize([], { flashExempt: 3 });
console.log(JSON.stringify({ part: P.partOf(f), line: P.phoneLine(bad), ok: P.phoneLine(good), n: good.flash_exempt }));""",
                      mod=PHONE_MJS, name="P")
        self.assertEqual(r["part"], "reading")
        self.assertIn("no hero line held its reading time", r["line"])
        self.assertIn("except 3 flash word(s) (showreel tone)", r["ok"])
        self.assertEqual(r["n"], 3)
        from st.qa import phone as qphone
        self.assertIn("no hero line", qphone._describe({"part": "reading", "code": "no_hero_line", "t": 1.0}))


class QaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-showreel-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def qa(self, video, proj):
        cp = showtime("qa", video, "--project", proj, "--json", "--no-sheet", "--out", self.tmp / ("qa-" + proj.name),
                      check=False, timeout=300)
        return json.loads(cp.stdout)

    def project(self, name, **cfg):
        proj = self.tmp / name
        write(proj / "showtime.json", json.dumps(dict({"width": 320, "height": 180, "fps": 30, "duration": 15}, **cfg)))
        write(proj / "index.html", "<!doctype html><html><body></body></html>")
        return proj

    def rules(self, rep):
        return {f["rule"] for f in rep["findings"]}

    def test_flash_rate_counts_opposing_pairs(self):
        from st.qa import rhythm
        self.assertEqual(rhythm.flash_rate([0, 1, -1, 1, -1, 1, -1, 1, -1], 30)["max_per_s"], 4)
        self.assertEqual(rhythm.flash_rate([0, 1, 1, 1, -1], 30)["max_per_s"], 1)       # one way, then back: one flash
        self.assertEqual(rhythm.flash_rate([0, 1] + [0] * 40 + [-1], 30)["max_per_s"], 0)  # a cut and a cut back 1.4 s later
        self.assertEqual(rhythm.flash_rate([0] * 10, 30)["max_per_s"], 0)

    def test_strobe_is_a_flash_risk_in_any_tone(self):
        video = self.tmp / "strobe.mp4"
        ffmpeg("-f", "lavfi", "-i", "color=c=white:s=320x180:r=30:d=3,format=gray,geq=lum='if(mod(floor(N/2),2),235,16)'",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", video)
        for name, cfg in (("strobe-plain", {}), ("strobe-reel", {"tone": "showreel"})):
            rep = self.qa(video, self.project(name, duration=3, **cfg))
            hit = [f for f in rep["findings"] if f["rule"] == "flash_risk"]
            self.assertEqual(len(hit), 1, (name, sorted(self.rules(rep))))
            self.assertEqual(hit[0]["severity"], "WARN")
            self.assertGreater(rep["rhythm"]["picture"]["flashes"]["max_per_s"], 3)

    def test_showreel_density_replaces_the_launch_grammar(self):
        many = cuts_video(self.tmp / "many.mp4", FOURTEEN, 15.0 / 14)
        few = cuts_video(self.tmp / "few.mp4", FOURTEEN[:3], 5.0)
        launch = self.qa(many, self.project("launch", kind="launch"))
        self.assertIn("edit_choppy", self.rules(launch))
        self.assertNotIn("showreel_sparse", self.rules(launch))
        reel = self.qa(many, self.project("reel", kind="launch", tone="showreel"))
        self.assertFalse({"edit_choppy", "too_many_scenes", "showreel_sparse", "showreel_long_end", "showreel_repeats"}
                         & self.rules(reel), sorted(self.rules(reel)))
        self.assertTrue(reel["rhythm"]["showreel"])
        self.assertTrue(reel["showreel"]["on"])
        self.assertEqual(reel["rhythm"]["reel"]["n_shots"], 14)
        self.assertIn("showreel: 14 shots", reel["rhythm"]["summary"])
        sparse = self.qa(few, self.project("sparse", tone="showreel"))
        hit = [f for f in sparse["findings"] if f["rule"] == "showreel_sparse"]
        self.assertEqual(len(hit), 1, sorted(self.rules(sparse)))
        self.assertIn("12-14 times per 15 s", hit[0]["message"])
        ten = self.qa(cuts_video(self.tmp / "ten.mp4", FOURTEEN[:10], 1.5), self.project("ten", tone="showreel"))
        self.assertIn("showreel_sparse", self.rules(ten))         # the old bar (8 per 15 s) passed 10 shots; 12 does not

    def test_long_end_and_repeats(self):
        # 12 shots of 1 s, the 3rd colour again as the 7th (a look-alike pair), then the last colour held still 3 s
        cols = FOURTEEN[:6] + [FOURTEEN[2]] + FOURTEEN[7:12]
        video = cuts_video(self.tmp / "tail.mp4", cols, 1.0, still_tail=3.0)
        rep = self.qa(video, self.project("tail", tone="showreel"))
        rules = self.rules(rep)
        self.assertIn("showreel_long_end", rules, sorted(rules))
        self.assertIn("showreel_repeats", rules, sorted(rules))
        self.assertGreaterEqual(rep["rhythm"]["reel"]["end"]["still_s"], 2.5)
        pairs = [(round(x["a"]), round(x["b"])) for x in rep["rhythm"]["reel"]["repeats"]]
        self.assertEqual(pairs, [(2, 6)])
        plain = self.qa(video, self.project("tail-plain"))           # outside the tone none of this is judged
        self.assertFalse({"showreel_long_end", "showreel_repeats", "showreel_sparse"} & self.rules(plain))
        self.assertNotIn("reel", plain.get("rhythm") or {})

    def test_reel_measures(self):
        import numpy as np
        from st.qa import reel
        th = showreel.thresholds()
        fps = 30.0
        seq = [0, 1, 2, 3, 0, 5]                                      # the 5th shot repeats the 1st (not neighbours)
        H = np.array([np.eye(64)[k] for k in seq for _ in range(15)])                       # one colour cell per shot
        S = np.array([np.random.RandomState(k).rand(576) * 200 for k in seq for _ in range(15)])   # one layout each
        mad = np.full(len(H), 5.0)
        mad[-12:] = 0.1                                               # the last 0.4 s still
        r = reel.analyze(H, S, mad, fps, th)
        self.assertEqual(r["n_shots"], 6)
        self.assertEqual([round(x["t"], 1) for x in r["shots"]], [0.0, 0.5, 1.0, 1.5, 2.0, 2.5])
        self.assertEqual([(x["a"], x["b"]) for x in r["repeats"]], [(0.0, 2.0)])
        self.assertAlmostEqual(r["end"]["still_s"], 0.267, places=2)    # whole 0.25 s windows (8 frames) of stillness
        self.assertEqual(r["dips"], [])
        mad[10:60] = 0.1                                              # 1.7 s of nothing moving mid-reel
        self.assertEqual(len(reel.analyze(H, S, mad, fps, th)["dips"]), 1)
        self.assertIn("6 shots", reel.summary(r))

    def test_frozen_still_fails_in_the_tone(self):
        video = self.tmp / "frozen.mp4"       # 3 s moving, 7 s frozen, 3 s moving
        ffmpeg("-filter_complex", "testsrc2=s=320x180:r=30:d=3,format=yuv420p[a];color=c=#2337ff:s=320x180:r=30:d=7,"
               "format=yuv420p[b];testsrc2=s=320x180:r=30:d=3,format=yuv420p[c];[a][b][c]concat=n=3:v=1:a=0[o]",
               "-map", "[o]", "-c:v", "libx264", "-pix_fmt", "yuv420p", video)
        rep = self.qa(video, self.project("frozen-reel", duration=13, tone="showreel"))
        frozen = [f for f in rep["findings"] if f["rule"] == "frozen"]
        self.assertTrue(frozen and frozen[0]["severity"] == "FAIL", sorted(self.rules(rep)))
        self.assertEqual(rep["verdict"], "FAIL")

    def test_critic_brief_gets_the_showreel_rubric(self):
        from st.qa import review
        m = {"context": [], "key_frames": [], "text_crops": [], "round": 1, "max_rounds": 3, "video": "/x/final.mp4",
             "size": [1920, 1080], "fps": 30, "duration": 15.0, "sheet": "/x/sheet.jpg", "scenes_sheet": "/x/scenes.jpg",
             "loudness_graph": "/x/loud.png", "thumbnail_preview": "/x/thumb.jpg", "cut_strips": "/x/cuts.jpg"}
        q = {"findings": [], "verdict": "PASS", "summary": {"fail": 0, "warn": 0}, "report": "/x/qa.json",
             "rhythm": {"launch": False, "showreel": True, "summary": "11 scene(s)"}, "showreel": {"on": True}}
        reel = review.critic_brief(m, q, Path("/x"))
        self.assertIn("## Showreel rubric", reel)
        self.assertIn("Measured by qa: 11 scene(s)", reel)
        self.assertIn("2. Energy and density", reel)
        for part in ("Long holds", "Repeats", "Energy dips", "at least 8 distinct kinds"):
            self.assertIn(part, reel)
        self.assertNotIn("2. Clarity", reel)
        self.assertNotIn("Launch film checklist", reel)
        q2 = dict(q, rhythm={"launch": True, "summary": "5 scene(s)"}, showreel={"on": False})
        plain = review.critic_brief(m, q2, Path("/x"))
        self.assertIn("Launch film checklist", plain)
        self.assertIn("2. Clarity", plain)
        self.assertNotIn("Showreel rubric", plain)


class NewProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-showreel-new-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def cfg(self, d):
        return json.loads((d / "showtime.json").read_text(encoding="utf-8"))

    def test_template_and_flag(self):
        showtime("new", "showreel", self.tmp / "reel")
        self.assertEqual(self.cfg(self.tmp / "reel")["tone"], "showreel")
        self.assertEqual(self.cfg(self.tmp / "reel")["duration"], 15.0)
        showtime("new", "dom", self.tmp / "dom-reel", "--tone", "showreel")
        self.assertEqual(self.cfg(self.tmp / "dom-reel")["tone"], "showreel")
        showtime("new", "showreel", self.tmp / "calm", "--tone", "default")
        self.assertEqual(self.cfg(self.tmp / "calm")["tone"], "default")
        showtime("new", "dom", self.tmp / "plain")
        self.assertNotIn("tone", self.cfg(self.tmp / "plain"))

    def test_template_meets_the_bar(self):
        """The showreel template: 13-14 shots on the 120 BPM grid in 15 s, the end card about the name's reading time
        (at most 10% of the reel), every technique shot tagged once (no technique twice), the new kinds in it."""
        import re
        html = (SKILL / "templates" / "showreel" / "index.html").read_text(encoding="utf-8")
        scenes = re.findall(r'<section class="scene" id="([\w-]+)"[^>]*data-dur="([\d.]+)"', html)
        self.assertTrue(13 <= len(scenes) <= 14, scenes)
        durs = [float(d) for _, d in scenes]
        self.assertAlmostEqual(sum(durs), 15.0, places=3)
        for d in durs:
            self.assertAlmostEqual((d * 4) % 1, 0.0, places=6, msg="every cut on the 120 BPM grid (half beats)")
        self.assertLessEqual(max(durs), 1.75)
        self.assertEqual(scenes[-1][0], "end")
        self.assertLessEqual(durs[-1], 0.1 * 15.0)
        tags = re.findall(r'class="tag"[^>]*><b>\d+</b>([^<]+)<', html)
        self.assertGreaterEqual(len(tags), 11)
        self.assertEqual(len(tags), len(set(tags)), tags)
        for kind in ("chart(", "morph(", "spiro(", "halftone(", "burst(", "tunnel(", "ST.three(", "mix-blend-mode: multiply"):
            self.assertIn(kind, html)

    def test_chart_counter_stays_in_square_and_tall_frames(self):
        """reel.js chart(): in a square frame (and 4:5, 9:16) the counter takes the tall layout, and its clip box and
        ring stay inside the frame through the shot's camera push (example 30's 1:1 ran off the right edge with
        `tall = H > W`); the ring stays above the label. The counter's cell is measureText('0') * 1.04 in the page:
        0.56 em here, a little wider than Anton's digits."""
        mod = self.tmp / "reel.mjs"                      # reel.js is a browser module: node imports it as .mjs
        shutil.copy(str(SKILL / "templates" / "showreel" / "reel.js"), str(mod))
        html = (SKILL / "templates" / "showreel" / "index.html").read_text(encoding="utf-8")
        import re
        dur = float(re.search(r'id="data"[^>]*data-dur="([\d.]+)"', html).group(1))
        sizes = [[1080, 1080], [1080, 1350], [1080, 1920], [1920, 1080]]
        lays = node_json("console.log(JSON.stringify(%s.map(([w, h]) => R.chartLayout(w, h))))" % json.dumps(sizes),
                         mod=mod)
        z = 1 + 0.06 * dur                               # the push at the shot's last frame, round (W/2, 0.55 H)
        for (w, h), lay in zip(sizes, lays):
            push = lambda x, y: (w / 2 + (x - w / 2) * z, 0.55 * h + (y - 0.55 * h) * z)
            self.assertEqual(lay["tall"], h >= w, (w, h))
            if not lay["tall"]:
                continue
            size, cell = lay["size"], lay["size"] * 0.56 * 1.04
            left = lay["cx"] - cell * 3 / 2                  # three digits (900)
            ring_y, r = lay["cy"] - size * 0.42, size * 0.95
            boxes = {"counter": (left - cell * 0.2, lay["cy"] - size * 0.95, left + cell * 3.2, lay["cy"] + size * 0.05),
                     "ring": (lay["cx"] - r, ring_y - r, lay["cx"] + r, ring_y + r)}
            for name, (ax, ay, bx, by) in boxes.items():
                (ax, ay), (bx, by) = push(ax, ay), push(bx, by)
                self.assertTrue(0 <= ax and bx <= w and 0 <= ay and by <= h,
                                "%s box %s outside %dx%d" % (name, [round(v) for v in (ax, ay, bx, by)], w, h))
            label_top = lay["labelY"] - min(w, h) * 0.05 * 0.8
            self.assertLess(ring_y + r, label_top, (w, h))
            self.assertLess(lay["labelY"], lay["top"], (w, h))

    def test_brief_words_set_the_tone(self):
        cp = showtime("job", "init", "reel-job", "--request", ROUND1, "--base", self.tmp, "--no-check")
        self.assertIn('tone: showreel tone (the brief says "showreel")', cp.stderr + cp.stdout)
        reel_job = cp.stdout.strip().splitlines()[-1]          # job init prints the job folder last
        cp = showtime("new", "dom", self.tmp / "p1", "--job", reel_job)
        self.assertEqual(self.cfg(self.tmp / "p1")["tone"], "showreel")
        self.assertIn("showreel tone", cp.stderr + cp.stdout)
        showtime("new", "dom", self.tmp / "p2", "--job", reel_job, "--tone", "polished")
        self.assertEqual(self.cfg(self.tmp / "p2")["tone"], "polished")
        cp = showtime("job", "init", "launch-job", "--goal", "a 20 s launch video for acme-cli", "--base", self.tmp, "--no-check")
        self.assertNotIn("tone:", cp.stderr + cp.stdout)
        showtime("new", "dom", self.tmp / "p3", "--job", cp.stdout.strip().splitlines()[-1])
        self.assertNotIn("tone", self.cfg(self.tmp / "p3"))


def page(body, style=""):
    return ("<!doctype html><html><head><meta charset=\"utf-8\"><script src=\"/_st/stage.js\"></script>"
            "<style>body{margin:0;background:#101418;color:#f4f6fa;font:600 60px sans-serif}"
            ".s{position:absolute;inset:0}.t{position:absolute;left:100px;width:1000px}.bar{position:absolute;left:0;top:0;height:8px;"
            "background:#fc3;width:calc(var(--p) * 100%%)}" + style + "</style></head><body>" + body + "</body></html>")


# three flash words, 0.3 s each (under the 0.35 s of a word-per-beat line, so only the flash rule can pass them),
# then a held line to the end (the hero line)
FLASHES = ('<section class="s" data-start="0" data-dur="0.9"><div class="bar"></div>'
           '<div class="t" style="top:280px" data-start="+0" data-dur="0.3" data-st-flash>TYPE.</div>'
           '<div class="t" style="top:280px" data-start="+0.3" data-dur="0.3" data-st-flash>SHAPE.</div>'
           '<div class="t" style="top:280px" data-start="+0.6" data-dur="0.3" data-st-flash>LIGHT.</div></section>')
HERO = '<section class="s" data-start="0.9" data-dur="3.1"><div class="bar"></div><div class="t" style="top:280px">Your Name</div></section>'


@unittest.skipIf(FAST, "--fast (needs a browser)")
class CheckTests(unittest.TestCase):
    """`showtime check` on planted 1280x720 projects: the flash-word exemption only where it belongs."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-showreel-check-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def check(self, name, body, **cfg):
        proj = self.tmp / name
        write(proj / "showtime.json", json.dumps(dict({"width": 1280, "height": 720, "fps": 30, "duration": 4,
                                                       "background": "#101418"}, **cfg)))
        write(proj / "index.html", page(body))
        cp = showtime("check", proj, "--json", "--no-determinism", "--samples", "3", check=False, timeout=240)
        return json.loads(cp.stdout)

    def codes(self, rep, code):
        return [f for f in rep["findings"] if f["code"] == code]

    def test_flash_words_pass_only_in_the_tone(self):
        rep = self.check("reel", FLASHES + HERO, tone="showreel")
        self.assertEqual(self.codes(rep, "short_text"), [], rep["findings"])
        note = self.codes(rep, "flash_text")
        self.assertEqual(len(note), 1)
        self.assertEqual(note[0]["severity"], "info")
        self.assertIn("3 flash word(s)", note[0]["message"])
        self.assertTrue(rep["phone"]["ok"], rep["phone"]["items"])
        self.assertEqual(rep["phone"]["flash_exempt"], 3)
        self.assertTrue(rep["showreel"]["on"])
        # the same page without the tone: every flash word is short_text, and says why the mark did not count
        rep = self.check("plain", FLASHES + HERO)
        short = self.codes(rep, "short_text")
        self.assertEqual(len(short), 3, rep["findings"])
        self.assertIn("only in the showreel tone", short[0]["message"])
        self.assertFalse(rep["phone"]["ok"])

    def test_a_job_brief_turns_it_on(self):
        job = self.tmp / "showtime-out" / "reel-brief"
        write(job / "job.json", json.dumps({"schema": 1, "slug": "reel-brief", "goal": "a 4 s teaser, go all out"}))
        proj = job / "project"
        write(proj / "showtime.json", json.dumps({"width": 1280, "height": 720, "fps": 30, "duration": 4, "background": "#101418"}))
        write(proj / "index.html", page(FLASHES + HERO))
        rep = json.loads(showtime("check", proj, "--json", "--no-determinism", "--samples", "3", check=False, timeout=240).stdout)
        self.assertEqual((rep["showreel"]["on"], rep["showreel"]["source"]), (True, "brief"))
        self.assertEqual(self.codes(rep, "short_text"), [])

    def test_real_problems_still_count(self):
        # an unmarked sentence and an over-long "flash" line both stay short_text; a frozen gap is still dead air
        body = ('<section class="s" data-start="0" data-dur="0.5"><div class="t" style="top:280px">'
                'Every frame here is written in code by hand</div></section>'
                '<section class="s" data-start="0.5" data-dur="0.5"><div class="t" style="top:280px" data-st-flash>'
                'This flash line is far too long to be texture</div></section>' + HERO.replace('data-start="0.9"', 'data-start="2.6"').replace('data-dur="3.1"', 'data-dur="1.4"'))
        rep = self.check("bad", body, tone="showreel")
        short = self.codes(rep, "short_text")
        self.assertEqual(len(short), 2, rep["findings"])
        self.assertTrue(any("is message, hold it" in f["message"] for f in short))
        self.assertTrue(self.codes(rep, "dead_air"), [f["code"] for f in rep["findings"]])
        self.assertFalse(rep["ok"])

    def test_template_checks_clean_at_every_aspect(self):
        """The showreel template lays out for 16:9 and recomposes for tall and square frames: `check --size` at 9:16
        (the platform UI zones) and 1:1 finds no error and no warning."""
        proj = self.tmp / "tpl"
        showtime("new", "showreel", proj)
        for size in ("16:9", "9:16", "1:1"):
            cp = showtime("check", proj, "--json", "--size", size, "--no-determinism", "--samples", "6", check=False, timeout=300)
            rep = json.loads(cp.stdout)
            bad = [(f["code"], f.get("message", "")[:90]) for f in rep["findings"] if f["severity"] in ("error", "warning")]
            self.assertEqual(bad, [], size)

    def test_all_flash_has_no_hero_line(self):
        rep = self.check("nohero", FLASHES, tone="showreel", duration=0.9)
        hero = self.codes(rep, "no_hero_line")
        self.assertEqual(len(hero), 1, rep["findings"])
        self.assertEqual(hero[0]["severity"], "warning")
        self.assertFalse(rep["phone"]["ok"])
        self.assertEqual([i["code"] for i in rep["phone"]["items"]], ["no_hero_line"])


if __name__ == "__main__":
    sys.argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(verbosity=2 if "-v" in sys.argv else 1)

#!/usr/bin/env python3
"""Pacing and motion defects: slow scenes, holds, dead stops, same-frame entrances, the look's transition frame.

Round-4 benchmark judges and the owner found showtime videos "readable but slow, not dynamic", with
4-5 s still holds in launch films; a practitioner's list adds dead stops and same-frame entrances.
  - `showtime check` slow_scene: a chart scene that holds on long past its last change and reading time
    (a slow push keeps it from counting as frozen) is a warning; a second chart state clears it; the
    last scene (an end card) may hold up to final_hold_max_s
  - a launch film warns on a 4 s still hold (launch_hold_s 3.5, was 5)
  - camera data-drift="hold" keeps a 6 s text hold from counting as still in check
  - check same_frame_entrance: three siblings whose CSS entrance starts on the same frame; a stagger clears it
  - qa dead_stop (st.qa.motion): a linear move that halts in one frame, not an eased one or a hard cut
  - look: the middle of the fastest transition is one of the key frames
Browser parts are skipped with --fast. usage: python tests/test_pacing.py [--fast] [-v]
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
sys.path.insert(0, str(SKILL / "lib"))

from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402
from st.qa import motion  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())


def node_exe():
    return ENV.get("SHOWTIME_NODE") or plat.which("node") or shutil.which("node") or "node"


def showtime(*args, check=True, timeout=600):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (" ".join(map(str, args)), cp.returncode,
                                                                    cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


HEAD = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>pacing</title>
<script src="/_st/stage.js"></script><link rel="stylesheet" href="/_st/themes/editorial.css">
<script type="module" src="/_st/components/index.js"></script>
<style>.scene{padding:7cqh 7cqw;background:var(--bg)} .chart{position:absolute;inset:7cqh 7cqw 10cqh;transform:scale(calc(1 + .04 * var(--p, 0)))}
h1{position:absolute;left:8cqw;top:36cqh;margin:0;font:600 9cqh/1.05 serif;color:var(--fg);max-width:70cqw}
@keyframes up{from{opacity:0;transform:translateY(0.4em)}to{opacity:1;transform:none}}
ul{position:absolute;left:8cqw;top:30cqh;margin:0;padding:0;list-style:none;font:500 6cqh/1.3 serif;color:var(--fg)}
li{animation:up .6s cubic-bezier(0.16,1,0.3,1) both} .stag li{animation-delay:calc(var(--i) * 0.1s)}
.cam{position:absolute;inset:0}</style></head><body><div class="stage">@BODY@</div></body></html>"""

# illustrative sample values (not real measurements)
BARS = [{"label": m, "value": v} for m, v in zip(["Jan", "Feb", "Mar", "Apr", "May", "Jun"], [42, 39, 35, 31, 24, 11])]


def chart_scene(sid, start, dur, opts):
    return ('<section class="scene" id="%s" data-start="%s" data-dur="%s"><div class="chart" data-st="chart" data-type="bar" '
            'data-at="0.2" data-options=\'%s\'></div></section>' % (sid, start, dur, json.dumps(opts)))


END = '<section class="scene" id="end" data-start="#s1" data-dur="3"><h1>Sample data: the end</h1></section>'
PROJECTS = {
    # one 10 s chart scene: the bars land by ~1.3 s, the text is read by ~4 s, then 6 s of nothing new
    "slow": (chart_scene("s1", 0, 10, {"title": "Sample data: build time fell", "data": BARS}) + END, 13, {}),
    # the same scene with a second state at 4 s and a callout: a beat about every 2 s
    "beats": (chart_scene("s1", 0, 7, {"title": "Sample data: build time fell", "annotate": {"label": "Jun", "text": "cache on"},
                                         "states": [{"at": 0, "data": BARS}, {"at": 3.2, "title": "Sample data: and stayed down",
                                                                              "data": [dict(b, value=b["value"] - 2) for b in BARS]}]}) + END, 10, {}),
    # a launch film holding a still headline for 4 s mid-film
    "launch4": ('<section class="scene" id="s1" data-start="0" data-dur="4"><h1>A still headline, held</h1></section>'
                '<section class="scene" id="s2" data-start="#s1" data-dur="3"><h1 style="top:20cqh">Next</h1></section>', 7, {"kind": "launch"}),
    # the same text held 6 s, with and without the hold push
    "still": ('<section class="scene" id="s1" data-start="0" data-dur="6"><div class="cam" data-st="camera" data-path=\'[{"at":0,"zoom":1}]\'>'
              '<h1>A held headline that should not look frozen</h1></div></section>', 6, {}),
    "drift": ('<section class="scene" id="s1" data-start="0" data-dur="6"><div class="cam" data-st="camera" data-drift="hold" data-path=\'[{"at":0,"zoom":1}]\'>'
              '<h1>A held headline that should not look frozen</h1></div></section>', 6, {}),
    # three list items entering on one frame, and the same list staggered
    "same": ('<section class="scene" id="s1" data-start="0" data-dur="3"><ul><li>One sample item</li><li>Two sample items</li><li>Three sample items</li></ul></section>', 3, {}),
    "stagger": ('<section class="scene" id="s1" data-start="0" data-dur="3"><ul class="stag"><li style="--i:0">One sample item</li>'
                '<li style="--i:1">Two sample items</li><li style="--i:2">Three sample items</li></ul></section>', 3, {}),
}


class DeadStops(unittest.TestCase):
    """st.qa.motion on frame-difference series (levels 0-255)."""

    def test_linear_move_that_halts_is_a_dead_stop(self):
        mad = [0.0] * 10 + [4.0] * 12 + [0.0] * 20
        found = motion.dead_stops(mad, 30.0)
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0]["frame"], 22)
        txt = motion.describe(found[0], 30.0)
        self.assertIn("frame 22", txt["message"])
        self.assertIn("frame 14", txt["fix"])

    def test_eased_landing_is_fine(self):
        eased = [4.0 * (1 - k / 12.0) ** 3 for k in range(12)]
        mad = [0.0] * 10 + [4.0] * 6 + eased + [0.0] * 20
        self.assertEqual(motion.dead_stops(mad, 30.0), [])

    def test_hard_cut_is_not_a_move(self):
        mad = [0.0] * 10 + [30.0] + [0.0] * 20
        self.assertEqual(motion.dead_stops(mad, 30.0), [])
        # footage moving, then a cut to a still card: the cut frame is not the end of a move
        mad2 = [0.0] * 5 + [2.0] * 10 + [25.0] + [0.0] * 20
        self.assertEqual(motion.dead_stops(mad2, 30.0, cuts=[15 / 30.0]), [])

    @unittest.skipIf(FAST, "encodes two short clips")
    def test_on_rendered_clips(self):
        try:
            import numpy  # noqa: F401  (the showtime venv has it; run_all uses that interpreter)
        except ImportError:
            self.skipTest("numpy is not installed for this interpreter")
        from st import ff
        from st.qa import rhythm
        tmp = Path(tempfile.mkdtemp(prefix="st-deadstop-"))
        try:
            # a 40 px square slides 500 px and stops at 1.25 s: linearly (a dead stop), or eased out
            clips = {"linear": "min(t*400,500)", "eased": "500*(1-pow(1-min(t/1.25,1),3))"}
            found = {}
            for name, xexpr in clips.items():
                out = tmp / (name + ".mp4")
                cp = subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-loglevel", "error",
                                     "-f", "lavfi", "-i", "color=c=0xf4efe6:s=640x360:r=30:d=3",
                                     "-f", "lavfi", "-i", "color=c=0x1d2433:s=80x80:r=30:d=3",
                                     "-filter_complex", "[0][1]overlay=x='%s':y=140:eval=frame" % xexpr.replace(",", "\\,"),
                                     "-pix_fmt", "yuv420p", str(out)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
                self.assertEqual(cp.returncode, 0, cp.stderr)
                found[name] = rhythm.measure(out, 3.0, 30.0)["dead_stops"]
            self.assertTrue(found["linear"], "a linear slide that halts at 1.25 s is a dead stop")
            self.assertAlmostEqual(found["linear"][0]["t"], 1.25, delta=0.1)
            self.assertEqual(found["eased"], [], "an ease-out landing is not")
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)


class LookTransition(unittest.TestCase):
    def test_key_times_include_the_middle_of_the_fastest_transition(self):
        look = (SKILL / "scripts" / "look.mjs").resolve().as_uri()
        code = """
const L = await import(%s);
const info = { duration: 12, fps: 30 };
const scenes = [{id: 'a', start: 0, end: 4}, {id: 'b', start: 4, end: 8}, {id: 'c', start: 8, end: 12}];
const tx = [{type: 'dip', start: 3.6, dur: 0.7}, {type: 'push', start: 7.7, dur: 0.6}];
const k = L.keyTimes(info, scenes, 8, tx);
const many = L.keyTimes({ duration: 60, fps: 30 }, Array.from({length: 30}, (_, i) => ({ id: 's' + i, start: 2 * i, end: 2 * i + 2 })), 8, tx);
console.log(JSON.stringify({ k, many: many.length, fx: L.fastestTransition(tx), none: L.fastestTransition([]) }));
""" % json.dumps(look)
        cp = subprocess.run([node_exe(), "--input-type=module", "-e", code], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", timeout=60)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertEqual(r["fx"]["type"], "push", "a push moves more than a dip")
        mids = [x for x in r["k"] if x["label"].startswith("mid ")]
        self.assertEqual(len(mids), 1, r["k"])
        self.assertAlmostEqual(mids[0]["t"], 8.0, delta=1 / 30)
        self.assertLessEqual(r["many"], 16, "still one small image")
        self.assertIsNone(r["none"])


@unittest.skipIf(FAST, "needs a browser")
class PacingChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-pacing-"))
        cls.rep = {}
        for name, (body, dur, extra) in PROJECTS.items():
            p = cls.tmp / name
            p.mkdir()
            (p / "showtime.json").write_text(json.dumps(dict({"width": 1920, "height": 1080, "fps": 30, "duration": dur}, **extra)), encoding="utf-8")
            (p / "index.html").write_text(HEAD.replace("@BODY@", body), encoding="utf-8")
            cp = showtime("check", p, "--json", "--no-determinism", check=False)
            cls.rep[name] = json.loads(cp.stdout)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def codes(self, name, code):
        return [f for f in self.rep[name]["findings"] if f["code"] == code]

    def test_slow_chart_scene_is_reported(self):
        slow = self.codes("slow", "slow_scene")
        self.assertEqual(len(slow), 1, self.rep["slow"]["findings"])
        self.assertEqual(slow[0]["severity"], "warning")
        self.assertIn("#s1", slow[0]["message"])
        self.assertIn("beat", slow[0]["fix"])
        self.assertTrue(self.rep["slow"]["pacing"] and self.rep["slow"]["pacing"][0]["tail"] > 4, self.rep["slow"]["pacing"])
        self.assertEqual(self.codes("slow", "dead_air"), [], "the slow push keeps it from being a still hold")

    def test_beats_clear_it(self):
        self.assertEqual(self.codes("beats", "slow_scene"), [], self.rep["beats"].get("pacing"))

    def test_launch_film_warns_on_a_four_second_hold(self):
        holds = [f for f in self.codes("launch4", "dead_air") if f["severity"] == "warning"]
        self.assertTrue(holds, self.rep["launch4"]["findings"])
        self.assertIn("3.5s", holds[0]["message"])

    def test_hold_push_keeps_a_hold_alive(self):
        self.assertTrue(self.codes("still", "dead_air"), "a 6 s still text hold is reported")
        self.assertEqual(self.codes("drift", "dead_air"), [], "data-drift=\"hold\" is change enough")

    def test_same_frame_entrance(self):
        same = self.codes("same", "same_frame_entrance")
        self.assertEqual(len(same), 1, self.rep["same"]["findings"])
        self.assertIn("frame 0", same[0]["message"])
        self.assertIn("frame 3", same[0]["fix"])
        self.assertEqual(self.codes("stagger", "same_frame_entrance"), [])


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

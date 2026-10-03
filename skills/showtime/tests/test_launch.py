#!/usr/bin/env python3
"""launch-film tests: the premium launch grammar's engine and tools.

  - the music-led cut plan (st.audio.cutplan) on a synthetic analysis: the excerpt puts the swell on the
    end card and every scene change on the bar grid
  - `showtime retime --cuts` moves scene changes to given times (and refuses a wrong count)
  - `showtime audio cuts <file> --apply <project>` analyses a real audio file, retimes the project and
    writes the excerpt as the mix's music track
  - the qa edit-rhythm measures (st.qa.rhythm): hard cuts vs a continuous zoom, layout changes
  - the critic brief carries the launch checklist for launch films
  - in the browser (skipped with --fast): the through (letter counter), match and pan transitions and the
    camera component, probed at mid-window; the launch template passes `showtime check` at 16:9 and 9:16
    and renders a section

usage: python tests/test_launch.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import math
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())


def showtime(*args, check=True, timeout=600):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def scene_starts(proj: Path):
    from st.cli_core import _Tags, _split_tops
    scenes, _ = _split_tops(_Tags((proj / "index.html").read_text(encoding="utf-8")).resolve())
    return [round(c["t0"], 3) for c in scenes], [round(c["t1"], 3) for c in scenes]


def synthetic_analysis(total=120.0, bpm=120.0, lift_at=90.0):
    """A regular 4/4 grid and an energy curve: sparse, a body, then a +9 dB lift at `lift_at`."""
    period = 60.0 / bpm
    beats = [round(i * period, 4) for i in range(int(total / period))]
    downbeats = beats[::4]
    hop = 0.5
    vals = []
    for i in range(int(total / hop)):
        t = i * hop
        v = 0.12 if t < 40 else (0.3 if t < lift_at else 0.85)
        vals.append(v * (1 + 0.05 * math.sin(t)))
    return {"schema": "showtime.beats/1", "duration": total, "bpm": bpm, "bpm_confidence": 0.9, "rhythmic": True,
            "beats": beats, "downbeats": downbeats, "energy": {"hop": hop, "values": vals}}


def write_track(path: Path, total=90.0, bpm=120.0, lift_at=62.0, sr=22050):
    """A test track: a chord pad with a kick on every beat, 10 dB louder after `lift_at`."""
    import numpy as np
    t = np.arange(int(total * sr)) / sr
    pad = sum(np.sin(2 * np.pi * f * t) for f in (220.0, 277.18, 329.63)) / 3
    period = 60.0 / bpm
    ph = (t % period)
    kick = np.sin(2 * np.pi * 60 * ph) * np.exp(-ph * 18)
    bar = (t % (4 * period)) < period
    x = 0.25 * pad + 0.5 * kick * np.where(bar, 1.3, 0.8)
    x *= np.where(t < lift_at, 0.3, 1.0)
    y = np.clip(x / (np.abs(x).max() + 1e-9) * 0.8, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype("<i2").tobytes())
    return path


HOOK_PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<script src="/_st/stage.js"></script>
<link rel="stylesheet" href="/_st/themes/neutral.css">
<script type="module" src="/_st/components/index.js"></script>
<style>
  .scene { position: absolute; inset: 0; background: #f6f2ea; overflow: hidden; }
  .hook { position: absolute; left: 6cqw; top: 38cqh; margin: 0; font: 800 6cqw/1.05 sans-serif; color: #1d2433; white-space: nowrap; }
  .hook em { font-style: normal; color: #2f6f5e; }
  .label { position: absolute; left: 6cqw; top: 30cqh; font: 600 2.4cqw monospace; color: #1d2433; }
  #verb { background: #1d2433; color: #fff; }
  #verb p { position: absolute; left: 10cqw; top: 40cqh; font: 700 5cqw sans-serif; margin: 0; }
</style></head>
<body><div class="stage">
  <section class="scene" id="hook" data-start="0" data-dur="1">
    <p class="label">quillsort 2.0</p>
    <h1 class="hook"><em>fil<span data-portal="counter">e</span>2</em> comes before file10.</h1>
  </section>
  <section class="scene" id="verb" data-start="#hook" data-dur="3" data-transition="through 1.3"><p>Numbers sort as numbers.</p></section>
</div></body></html>
"""


class LaunchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-launch-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    # ----------------------------------------------------------------- cut plan
    def test_01_cutplan_puts_the_swell_on_the_end_card(self):
        from st.audio import cutplan
        an = synthetic_analysis()
        p = cutplan.plan(an, 30.0, 5)
        self.assertEqual(len(p["cuts"]), 4)
        self.assertEqual(p["scene_starts"][0], 0.0)
        self.assertEqual(p["cuts"], sorted(p["cuts"]))
        self.assertIsNotNone(p["lift"], p)
        # the lift at 90 s of the track is where the end card starts
        self.assertAlmostEqual(p["offset"] + p["cuts"][-1], 90.0, delta=1.0)
        self.assertGreaterEqual(p["lift_db"], 5)
        # every scene change and the excerpt start sit on the bar grid (2 s at 120 bpm)
        for c in [0.0] + p["cuts"]:
            x = (p["offset"] + c) % 2.0
            self.assertTrue(min(x, 2.0 - x) < 0.05, (c, p["offset"]))
        self.assertTrue(all(b - a >= 2.8 for a, b in zip(p["scene_starts"], p["scene_starts"][1:] + [30.0])))
        self.assertGreaterEqual(p["cuts_on_phrase"] + p["cuts_on_half_phrase"], 2, p)
        # a chosen excerpt is kept; a track shorter than the film is refused
        self.assertEqual(cutplan.plan(an, 30.0, 5, offset=10.0)["offset"], 10.0)
        with self.assertRaises(Exception):
            cutplan.plan(synthetic_analysis(total=20.0), 30.0, 5)
        self.assertIn("scene starts", cutplan.summary(p))

    def test_02_retime_cuts(self):
        proj = self.tmp / "retime"
        showtime("new", "launch", proj)
        showtime("retime", proj, "--cuts", "4,11,17.5,24", "-d", "28")
        starts, ends = scene_starts(proj)
        self.assertEqual(starts, [0.0, 4.0, 11.0, 17.5, 24.0])
        self.assertEqual(ends[-1], 28.0)
        self.assertEqual(json.loads((proj / "showtime.json").read_text())["duration"], 28.0)
        cp = showtime("retime", proj, "--cuts", "4,11", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("needs 4", cp.stderr)
        self.assertNotIn("Traceback", cp.stderr)

    def test_03_audio_cuts_apply(self):
        proj = self.tmp / "cuts"
        showtime("new", "launch", proj, "--duration", 24)
        track = write_track(self.tmp / "theme.wav")
        rep = json.loads(showtime("audio", "cuts", track, "--apply", proj, "--json").stdout)
        self.assertEqual(rep["scenes"], 5)
        self.assertEqual(rep["dur"], 24.0)
        starts, _ = scene_starts(proj)
        self.assertEqual(len(starts), 5)
        for got, want in zip(starts, rep["scene_starts"]):
            self.assertAlmostEqual(got, want, delta=0.04)
        mix = json.loads((proj / "audio" / "mix.json").read_text())
        music = [t for t in mix["tracks"] if t["kind"] == "music"]
        self.assertEqual(len(music), 1)
        self.assertTrue(music[0]["file"].endswith("theme.wav"), music[0])
        self.assertNotIn("catalog", music[0])
        self.assertAlmostEqual(music[0]["offset"], rep["offset"], places=2)
        self.assertEqual(music[0]["dur"], 24.0)
        # the swell (the level step at 62 s) lands at the end card
        self.assertIsNotNone(rep["lift"], rep)
        self.assertAlmostEqual(rep["offset"] + rep["cuts"][-1], 62.0, delta=1.5)
        # plain text output names the plan
        out = showtime("audio", "cuts", track, "--dur", 20, "--scenes", 4).stdout
        self.assertIn("scene starts", out)
        self.assertIn("mix track", out)

    # ----------------------------------------------------------------- qa rhythm
    def test_04_rhythm_counts_cuts_not_camera_moves(self):
        from st.qa import rhythm
        cuts = self.tmp / "cuts.mp4"
        ff.run_ffmpeg(["-f", "lavfi", "-i", "color=c=0x1f4fd6:s=320x180:r=24:d=2", "-f", "lavfi", "-i",
                       "color=c=0xd8342c:s=320x180:r=24:d=2", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=2",
                       "-filter_complex", "[0][1][2]concat=n=3:v=1:a=0", "-pix_fmt", "yuv420p", cuts])
        r = rhythm.picture(cuts, 24.0)
        self.assertEqual(r["n_hard_cuts"], 2, r["hard_cuts"])
        self.assertAlmostEqual(r["hard_cuts"][0], 2.0, delta=0.1)
        self.assertEqual(r["n_layouts"], 3)
        self.assertTrue(all(c["kind"] in ("cut", "fast") for c in r["layout_changes"]), r["layout_changes"])
        zoom = self.tmp / "zoom.mp4"
        ff.run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=640x360:r=24:d=4", "-vf",
                       "zoompan=z='1+0.1*on/96':d=1:s=320x180:fps=24", "-frames:v", "96", "-pix_fmt", "yuv420p", zoom])
        z = rhythm.picture(zoom, 24.0)
        self.assertEqual(z["n_hard_cuts"], 0, z["hard_cuts"])
        self.assertEqual(z["n_layouts"], 1)
        self.assertGreater(z["moving_fraction"], 0.5)
        self.assertTrue(rhythm.launch_like({"kind": "launch"}, {}, None))
        self.assertTrue(rhythm.launch_like({}, {}, "Make a 30-second launch video for x"))
        self.assertFalse(rhythm.launch_like({}, {}, "explain how a heat pump works"))
        self.assertFalse(rhythm.launch_like({"kind": "explainer"}, {}, "a launch video"))

    def test_05_critic_brief_has_the_launch_checklist(self):
        from st.qa import review
        m = {"round": 1, "max_rounds": 2, "video": "final.mp4", "size": [1920, 1080], "fps": 30, "duration": 30,
             "context": [], "key_frames": [], "sheet": "", "scenes_sheet": "", "loudness_graph": "",
             "thumbnail_preview": "", "cut_strips": ""}
        q = {"findings": [], "verdict": "PASS", "summary": {"fail": 0, "warn": 0}, "report": "",
             "rhythm": {"launch": True, "summary": "5 layout(s): 4 move(s)"}}
        brief = review.critic_brief(m, q, self.tmp)
        self.assertIn("Launch film checklist", brief)
        self.assertIn("5 layout(s): 4 move(s)", brief)
        q["rhythm"]["launch"] = False
        self.assertNotIn("Launch film checklist", review.critic_brief(m, q, self.tmp))

    # ----------------------------------------------------------------- browser
    def _probe(self, proj, t, js, before=()):
        node = plat.which("node") or shutil.which("node")
        code = PROBE_JS % {"skill": json.dumps(str(SKILL)), "proj": json.dumps(str(proj)), "t": t, "js": json.dumps(js),
                           "before": json.dumps(list(before))}
        cp = subprocess.run([node, "--input-type=module", "-e", code], env=ENV, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", timeout=420)   # a busy 3-core CI runner can take minutes
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        return json.loads(cp.stdout.strip().splitlines()[-1])

    def test_06_camera_transitions(self):
        if FAST:
            self.skipTest("--fast (needs a browser)")
        proj = self.tmp / "tx"
        proj.mkdir()
        (proj / "showtime.json").write_text(json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 10}), encoding="utf-8")
        (proj / "index.html").write_text(TX_PAGE, encoding="utf-8")
        js = """(() => {
          const g = (id) => document.getElementById(id);
          const st = (el) => ({ t: el.style.transform || '', clip: el.style.clipPath || '', op: el.style.opacity || '',
                                tr: el.style.translate || '', sc: el.style.scale || '', vis: getComputedStyle(el).display });
          const hole = window.__hole ? window.__hole() : null;
          return { s1: st(g('s1')), s2: st(g('s2')), s3: st(g('s3')), s4: st(g('s4')), s5: st(g('s5')),
                   win2: st(document.querySelector('#s3 [data-match]')), cam: st(document.querySelector('#s1 .cam')), hole };
        })()"""
        mid_through = self._probe(proj, 2.6, js)
        self.assertIn("scale(", mid_through["s1"]["t"])
        self.assertTrue(mid_through["s2"]["clip"].startswith("ellipse("), mid_through["s2"])
        z = float(mid_through["s1"]["t"].split("scale(")[1].rstrip(")"))
        self.assertGreater(z, 1.5)
        self.assertIsNotNone(mid_through["hole"], "the counter of the o was not found")
        self.assertIn("scale(", mid_through["cam"]["t"])            # the camera component moves scene 1
        # one continuous dolly: the opening keeps its shape (no separate clip growth), the zoom rises
        # smoothly with no jump between frames, and it lands on the incoming scene at exactly 1:1
        sc = lambda st: float(st["t"].split("scale(")[1].rstrip(")"))
        frames = [self._probe(proj, round(2.0 + i / 30.0, 4), js) for i in range(2, 36, 3)]
        clips = {f["s2"]["clip"] for f in frames if f["s2"]["clip"]}
        self.assertEqual(len(clips), 1, clips)
        zs = [sc(f["s2"]) for f in frames if "scale(" in f["s2"]["t"]]
        self.assertEqual(zs, sorted(zs))
        steps = [math.log(b / a) for a, b in zip(zs, zs[1:])]
        for x, y in zip(steps, steps[1:]):
            self.assertLess(abs(y - x), 0.5 * max(steps) + 1e-6, steps)   # no step in speed between samples
        self.assertGreater(zs[-1], 0.9)
        end_through = self._probe(proj, 3.25, js)
        self.assertEqual(end_through["s2"]["t"], "")                 # the window is over: scene 2 as laid out
        mid_match = self._probe(proj, 4.4, js)
        self.assertTrue(mid_match["win2"]["tr"], mid_match)          # the shared window flies
        self.assertLess(float(mid_match["win2"]["op"] or 1), 1.0)
        mid_pan = self._probe(proj, 6.5, js)
        for k in ("s3", "s4"):
            self.assertIn("translate(", mid_pan[k]["t"])
        s = float(mid_pan["s4"]["t"].split("scale(")[1].rstrip(")"))
        self.assertLess(s, 1.0)                                      # the pull-back arc
        # a camera push "to": "stay" zooms about its focus: the word keeps its centre and doubles in size
        rect = """(() => { const r = document.getElementById('nx').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2, r.width]; })()"""
        a0, a1 = self._probe(proj, 7.1, rect), self._probe(proj, 7.9, rect)
        self.assertAlmostEqual(a0[0], a1[0], delta=1.5)
        self.assertAlmostEqual(a0[1], a1[1], delta=1.5)
        self.assertAlmostEqual(a1[2] / a0[2], 2.0, delta=0.05)
        inv = self._probe(proj, 8.5, js)
        self.assertTrue(inv["s4"]["clip"].startswith("inset("), inv)  # the old scene shrinks into the tile
        # pixels: mid-window frames differ from both ends and are not black
        shots = self.tmp / "tx-shots"
        rep = json.loads(showtime("snap", proj, "--at", "1.9,2.6,3.3,3.9,4.4,5.1,5.9,6.5,7.2", "-o", shots,
                                  "--format", "png", "--json").stdout)
        self.assertEqual(len(rep["stills"]), 9)
        # frames inside the camera moves do not depend on seek order: the portal (on a word that is still
        # animating) and the shared elements are measured after the stage has seeked this frame's CSS animations
        for t in (2.6, 4.4):
            a = self._probe(proj, t, js, before=[0.3])
            b = self._probe(proj, t, js, before=[9.5])
            self.assertEqual(a, b, "t=%s depends on the frame seeked before it" % t)

    def test_06b_fit_keeps_terminal_lines_whole(self):
        """data-st="fit" shrinks a terminal's type until its longest line fits the window, at any frame size,
        and `showtime check` passes the page it would otherwise fail with text_clipped."""
        if FAST:
            self.skipTest("--fast (needs a browser)")
        proj = self.tmp / "fit"
        shutil.copytree(str(TESTS_DIR / "fixtures" / "defects" / "clipped-text"), str(proj))
        (proj / "DEFECT.json").unlink()
        page = (proj / "index.html").read_text(encoding="utf-8")
        page = page.replace('<div class="term">', '<div class="term" data-st="fit">').replace(
            '<link rel="stylesheet" href="/_st/themes/neutral.css">',
            '<link rel="stylesheet" href="/_st/themes/neutral.css"><script type="module" src="/_st/components/index.js"></script>')
        (proj / "index.html").write_text(page, encoding="utf-8")
        js = """(() => { const t = document.querySelector('.term'), w = document.querySelector('.win');
                   const r = document.createRange(); r.selectNodeContents(t);
                   return { k: Number(t.dataset.fitScale), right: r.getBoundingClientRect().right, win: w.getBoundingClientRect().right,
                            wrap: t.classList.contains('st-fit-wrap') }; })()"""
        got = self._probe(proj, 1.0, js)
        self.assertLess(got["k"], 1.0)
        self.assertFalse(got["wrap"])
        self.assertLessEqual(got["right"], got["win"])
        rep = json.loads(showtime("check", proj, "--json", "--no-determinism", "--samples", "2", check=False, timeout=300).stdout)
        self.assertEqual([f for f in rep["findings"] if f["code"] == "text_clipped"], [])

    def test_06c_through_never_cuts_the_headline(self):
        """Flying through a letter of a long headline: the words outside the portal's word fade before the
        zoom reaches the frame edge (no still reads "file2 comes befor"), and `showtime check`, which samples
        inside the move, errors when they do not fade (text_cropped_in_move)."""
        if FAST:
            self.skipTest("--fast (needs a browser)")
        page = HOOK_PAGE
        proj = self.tmp / "hook"
        proj.mkdir()
        cfg = json.dumps({"width": 960, "height": 540, "fps": 30, "duration": 4})
        (proj / "showtime.json").write_text(cfg, encoding="utf-8")
        (proj / "index.html").write_text(page, encoding="utf-8")
        js = """(() => { const f = document.querySelector('.scene').getBoundingClientRect(); const out = [];
                   for (const el of document.querySelectorAll('#hook [data-st-tx-text]')) {
                     const r = el.getBoundingClientRect(), op = Number(getComputedStyle(el).opacity);
                     const cut = r.left < f.left - 1 || r.right > f.right + 1 || r.top < f.top - 1 || r.bottom > f.bottom + 1;
                     const onscreen = r.right > f.left && r.left < f.right && r.bottom > f.top && r.top < f.bottom;
                     out.push({ text: el.textContent.trim(), op, cut, onscreen }); }
                   return out; })()"""
        for t in (1.1, 1.25, 1.4, 1.55, 1.7, 1.85, 2.0):
            runs = self._probe(proj, t, js)
            self.assertTrue(any("comes before" in r["text"] for r in runs), runs)
            for r in runs:
                if r["cut"] and r["onscreen"]:
                    self.assertLess(r["op"], 0.05, "t=%s: %r is cut by the frame edge but still visible" % (t, r))
        rep = json.loads(showtime("check", proj, "--json", "--no-determinism", "--samples", "2", check=False, timeout=300).stdout)
        self.assertEqual([f for f in rep["findings"] if f["code"] == "text_cropped_in_move"], [])
        # a page that pins the text's opacity (so it cannot fade) is caught by the check
        bad = self.tmp / "hook-bad"
        bad.mkdir()
        (bad / "showtime.json").write_text(cfg, encoding="utf-8")
        (bad / "index.html").write_text(page.replace("</style>", "  #hook [data-st-tx-text] { opacity: 1 !important; }\n</style>"), encoding="utf-8")
        rep = json.loads(showtime("check", bad, "--json", "--no-determinism", "--samples", "2", check=False, timeout=300).stdout)
        got = [f for f in rep["findings"] if f["code"] == "text_cropped_in_move"]
        self.assertTrue(got, [f["code"] for f in rep["findings"]])
        self.assertEqual(got[0]["severity"], "error")
        self.assertNotIn("file2", got[0]["message"].split('"')[1].split()[0])   # the portal's word is exempt

    def test_07_launch_template(self):
        if FAST:
            self.skipTest("--fast (needs a browser)")
        proj = self.tmp / "tpl"
        showtime("new", "launch", proj, "--duration", 20)
        for extra in ([], ["--size", "9:16"]):
            rep = json.loads(showtime("check", proj, "--json", "--samples", "2", *extra, check=False, timeout=300).stdout)
            bad = [f for f in rep["findings"] if f["severity"] in ("error", "warning")]
            self.assertEqual(bad, [], extra)
        rep = json.loads(showtime("render", proj, "--out-dir", self.tmp / "out", "--from", 2.5, "--to", 5.5,
                                  "--scale", 0.5, "--poster", "none", "--no-audio", "--json", timeout=1200).stdout)
        self.assertTrue(Path(rep["output"]).is_file())
        q = json.loads(showtime("qa", rep["output"], "--json", check=False).stdout)
        self.assertIn("rhythm", q)
        self.assertEqual(q["rhythm"]["picture"]["n_hard_cuts"], 0, q["rhythm"]["picture"])


PROBE_JS = """
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const skill = %(skill)s;
const imp = (p) => import(pathToFileURL(path.join(skill, 'scripts', p)).href);
const { startServer } = await imp('server.mjs');
const { openBrowser, openStage } = await imp('lib/stagehost.mjs');
const { resolveProject } = await imp('lib/cli.mjs');
const proj = resolveProject(%(proj)s);
const server = await startServer({ root: proj.dir, port: 0 });
const b = await openBrowser({ gpu: 'auto' });
try {
  const s = await openStage(b.browser, { url: server.url, page: proj.page, config: proj.config });
  for (const bt of %(before)s) await s.seek(bt);
  await s.seek(%(t)s);
  console.log(JSON.stringify(await s.page.evaluate(%(js)s)));
  await s.close();
} finally { await b.browser.close(); await server.close(); }
"""

TX_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<script src="/_st/stage.js"></script>
<link rel="stylesheet" href="/_st/themes/neutral.css">
<script type="module">
  import { counterOf } from '/_st/components/portal.js';
  window.__hole = () => counterOf(document.querySelector('[data-portal="counter"]'));
</script>
<script type="module" src="/_st/components/index.js"></script>
<style>
 .scene { display: grid; place-items: center; background: #1d2230; color: #fff; }
 .cam { position: absolute; inset: 0; display: grid; place-items: center; }
 h1 { font-size: 16cqh; margin: 0; font-family: var(--font-display); }
 #s1 h1 { animation: drift 3.2s linear both; }   /* still moving while the camera flies through its o */
 @keyframes drift { from { transform: translateX(-6cqw); } to { transform: translateX(6cqw); } }
 .win { position: absolute; left: 55%; top: 30%; width: 30%; height: 40%; border-radius: 2cqh; background: #3a7bd5; }
 .win2 { left: 10%; top: 20%; width: 50%; height: 60%; }
 .tile { position: absolute; left: 40%; top: 40%; width: 20%; height: 20%; border-radius: 1cqh; background: #b8452c; }
</style></head><body><div class="stage">
<section class="scene" id="s1" data-start="0" data-dur="2"><div class="cam" data-st="camera" data-path='[{"at":0,"zoom":1},{"at":0.2,"dur":1.8,"zoom":1.1}]'><h1>fl<span data-portal="counter">o</span>w</h1></div></section>
<section class="scene" id="s2" data-start="#s1" data-dur="2" data-transition="through 1.2" style="background:#b8452c"><h1>inside</h1><div class="win" data-match="w"></div></section>
<section class="scene" id="s3" data-start="#s2" data-dur="2" data-transition="match 0.8"><div class="win win2" data-match="w"></div></section>
<section class="scene" id="s4" data-start="#s3" data-dur="2" data-transition="pan left 1"><div class="cam" data-st="camera" data-keep-text="false" data-path='[{"at":0,"zoom":1},{"at":1.2,"dur":0.5,"zoom":2,"focus":"#nx","to":"stay"}]'><h1 id="nx" style="position:absolute;left:8%;top:10%">next</h1></div></section>
<section class="scene" id="s5" data-start="#s4" data-dur="2" data-transition="through 1" data-transition-options='{"inverse":true}'><div class="tile" data-portal></div><h1 style="position:absolute;top:10%">wall</h1></section>
</div></body></html>"""


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

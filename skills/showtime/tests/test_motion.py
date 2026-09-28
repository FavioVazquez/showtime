#!/usr/bin/env python3
"""motion smoke tests: DOM components, CSS + WebGL transitions, themes, templates.

Real runs (headless Chrome through the showtime CLI):
  - every runtime module parses (node --check); catalog, themes and shaders agree
  - `showtime motion --json` and `showtime code` (shiki tokens, line diff)
  - all 11 WebGL shader transitions render mid-transition frames that differ from both scenes
    (and are not black) via `showtime snap`
  - templates dom (16:9, with the sdf-iris shader), short (9:16, karaoke captions) and data
    (charts) render 3-4 s sections with `showtime render`; ffprobe checks size and frame count
  - `showtime check` passes the short template with no errors (skipped with --fast)
  - the preview player drives the dom template (components, shader transition, audio mix; skipped with --fast)

Stdlib only. usage: python tests/test_motion.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
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
RUNTIME = SKILL / "runtime"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
RESULTS = {}


def showtime(*args, check=True, timeout=600):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def node_exe():
    return plat.which("node") or shutil.which("node")


def mean_rgb(image):
    """Average colour of an image file as (r, g, b) via ffmpeg (scale to 1x1)."""
    cp = subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(image),
                         "-vf", "scale=1:1:flags=area,format=rgb24", "-f", "rawvideo", "-"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if cp.returncode != 0 or len(cp.stdout) < 3:
        raise AssertionError("ffmpeg could not read %s: %s" % (image, cp.stderr.decode(errors="replace")[-500:]))
    return tuple(cp.stdout[:3])


def dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def probe_video(path):
    cp = subprocess.run([ff.ffprobe_path(), "-v", "error", "-count_packets", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height,nb_read_packets,r_frame_rate", "-of", "json", str(path)],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=60)
    return json.loads(cp.stdout)["streams"][0]


SHADER_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<script src="/_st/stage.js"></script>
<link rel="stylesheet" href="/_st/themes/neutral.css">
<style>
  .scene { display: grid; place-items: center; }
  .a { background: #d8342c; color: #fff; }
  .b { background: #1f4fd6; color: #fff; }
</style>
<script type="module">
  import { transition, GL_TYPES } from '/_st/transitions/transitions.js';
  const stage = document.querySelector('.stage');
  const n = GL_TYPES.length;
  for (let i = 0; i <= n; i++) {
    const s = document.createElement('section');
    s.className = 'scene ' + (i % 2 ? 'b' : 'a');
    s.id = 's' + i;
    s.dataset.start = i; s.dataset.dur = 1;
    s.innerHTML = '<h1 class="t-display">Scene ' + i + '</h1>';
    stage.append(s);
  }
  GL_TYPES.forEach((type, i) => transition({ from: '#s' + i, to: '#s' + (i + 1), type, dur: 0.6 }));
</script></head><body><div class="stage"></div></body></html>"""


# evaluate a snippet in a project page at time t (render-mode page, via the stage host)
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
  await s.seek(%(t)s);
  console.log(JSON.stringify(await s.page.evaluate(%(js)s)));
  await s.close();
} finally { await b.browser.close(); await server.close(); }
"""


class MotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-motion-"))
        cls.out = cls.tmp / "out"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)
        if RESULTS:
            print("\nmotion results: " + json.dumps(RESULTS), file=sys.stderr)

    # ---------------------------------------------------------------- static
    def test_01_modules_parse(self):
        node = node_exe()
        if not node:
            self.skipTest("node not found")
        files = sorted(RUNTIME.glob("components/*.js")) + sorted(RUNTIME.glob("transitions/*.js")) + [SKILL / "scripts" / "code.mjs"]
        self.assertGreaterEqual(len(files), 20)
        bad = []
        for f in files:
            cp = subprocess.run([node, "--check", str(f)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            if cp.returncode != 0:
                bad.append("%s: %s" % (f.name, cp.stderr.strip()[-300:]))
        self.assertEqual(bad, [])

    def test_01b_caption_cards_no_flash_keep_and_skip(self):
        """05: fast speech never makes sub-0.4 s karaoke cards (short cards join a neighbour), words of a
        skipped voice line are hidden, and "hidden": true words are skipped."""
        node = node_exe()
        if not node:
            self.skipTest("node not found")
        js = ("const m = await import(%s);"
              "const W = []; let t = 0.1;"
              "for (const w of 'Hit N for a fresh note. Then save it.'.split(' ')) { W.push({text: w, start: t, end: t + 0.12, line: 'tip'}); t += 0.16; }"
              "W.push({text: 'secret', start: t, end: t + 0.3, hidden: true});"
              "const g = m.groupWords(m.normalizeWords(W), {maxWords: 3, maxChars: 36});"
              "console.log(JSON.stringify({cards: g.map((x) => [x.words.map((w) => w.text).join(' '), x.out - x.in]),"
              " lines: m.normalizeWords(W).map((w) => w.line)}));") % json.dumps((RUNTIME / "components" / "captions.js").as_uri())
        cp = subprocess.run([node, "--input-type=module", "-e", js], stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertTrue(all(d >= 0.4 - 1e-6 for _, d in out["cards"]), out)
        self.assertNotIn("secret", " ".join(c for c, _ in out["cards"]))
        self.assertEqual(set(out["lines"]), {"tip"})
        src = (RUNTIME / "components" / "captions.js").read_text(encoding="utf-8")
        for opt in ("skipLines", "keep:", "minShow"):
            self.assertIn(opt, src)

    def test_02_catalog_matches_code(self):
        cat = json.loads((RUNTIME / "transitions" / "catalog.json").read_text(encoding="utf-8"))
        names = {t["name"]: t for t in cat["transitions"]}
        tx = (RUNTIME / "transitions" / "transitions.js").read_text(encoding="utf-8")
        shaders = (RUNTIME / "transitions" / "shaders.js").read_text(encoding="utf-8")
        css_types = re.findall(r"'([a-z-]+)'", re.search(r"CSS_TYPES = \[(.*?)\]", tx).group(1))
        gl_types = re.findall(r"'([a-z-]+)'", re.search(r"GL_TYPES = \[(.*?)\]", tx).group(1))
        self.assertGreaterEqual(len(gl_types), 8, "need at least 8 WebGL transitions")
        self.assertEqual(set(css_types) | set(gl_types), set(names), "catalog.json and transitions.js disagree")
        for g in gl_types:
            self.assertEqual(names[g]["kind"], "webgl")
            self.assertIn("'%s': `" % g, shaders, "shader source missing for " + g)
            self.assertIn(names[g]["fallback"], css_types)
        # GLSL portability: reversed smoothstep edges are undefined behaviour on some GPUs
        for m in re.finditer(r"smoothstep\(\s*([0-9.]+)\s*,\s*(-?[0-9.]+)\s*,", shaders):
            self.assertLess(float(m.group(1)), float(m.group(2)), "reversed smoothstep: " + m.group(0))

    def test_03_themes_define_tokens(self):
        need = ["--bg", "--fg", "--muted", "--surface", "--accent", "--accent-2", "--accent-ink", "--font-display",
                "--font-body", "--font-mono", "--radius", "--dur-in", "--dur-out", "--ease-in", "--ease-out",
                "--ease-move", "--cap-font", "--cap-ink", "--cap-accent", "--cap-outline", "--grain"]
        themes = [p for p in (RUNTIME / "themes").glob("*.css") if p.name not in ("base.css", "fonts.css")]
        self.assertGreaterEqual(len(themes), 6)
        for t in themes:
            text = t.read_text(encoding="utf-8")
            for tok in need:
                self.assertRegex(text, re.escape(tok) + r"\s*:", "%s lacks %s" % (t.name, tok))
            for imp in re.findall(r"@import url\('([^']+)'\)", text):
                self.assertTrue((t.parent / imp).is_file(), "%s imports missing %s" % (t.name, imp))
        nm = Path(ENV.get("SHOWTIME_NODE_MODULES") or (showtime_home() / "node" / "node_modules"))
        if nm.is_dir():
            for f in (RUNTIME / "themes" / "fonts").glob("*.css"):
                for rel in set(re.findall(r"url\(/_lib/([^)]+)\)", f.read_text(encoding="utf-8"))):
                    self.assertTrue((nm / rel).is_file(), "font file missing: %s (%s)" % (rel, f.name))

    def test_04_motion_cli(self):
        rep = json.loads(showtime("motion", "--json").stdout)
        comps = {c["name"] for c in rep["components"]}
        for want in ("kinetic-type", "typewriter", "caption-karaoke", "lower-third", "count-up", "chart", "code-block",
                     "browser-frame", "device-frame", "cursor", "keystrokes", "logo-reveal", "end-card", "feature-grid",
                     "chat-thread", "notifications", "steps", "ken-burns", "world-map", "grain"):
            self.assertIn(want, comps)
        self.assertGreaterEqual(len([t for t in rep["transitions"] if t["kind"] == "webgl"]), 8)
        self.assertEqual({t["name"] for t in rep["themes"]}, {"neutral", "bold", "editorial", "neon", "paper", "terminal"})
        self.assertIn("transitions", showtime("motion", "--help").stdout)

    def test_05_code_tokens(self):
        a = self.tmp / "old.py"
        b = self.tmp / "new.py"
        a.write_text("def f(x):\n    return x + 1\n\nprint(f(2))\n", encoding="utf-8")
        b.write_text("def f(x, k=1):\n    return x + k\n\nprint(f(2))\n", encoding="utf-8")
        out = self.tmp / "diff.json"
        rep = json.loads(showtime("code", a, "--to", b, "-o", out, "--json").stdout)
        self.assertEqual((rep["added"], rep["removed"]), (2, 2))
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(doc["lang"], "python")
        self.assertTrue(all(tok["color"].startswith("#") for line in doc["lines"] for tok in line["tokens"]))
        cp = showtime("code", self.tmp / "missing.py", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("not found", cp.stderr)

    # ----------------------------------------------------------------- WebGL
    def test_06_shader_transitions_render(self):
        proj = self.tmp / "shaders"
        proj.mkdir()
        n = 11
        (proj / "showtime.json").write_text(json.dumps({"width": 640, "height": 360, "fps": 30, "duration": n + 1}), encoding="utf-8")
        (proj / "index.html").write_text(SHADER_PAGE, encoding="utf-8")
        times = []
        for i in range(1, n + 1):
            times += [i - 0.1, i + 0.3, i + 0.75]   # before (scene A), middle, after (scene B); all distinct
        shots = self.tmp / "shots"
        t0 = time.time()
        rep = json.loads(showtime("snap", proj, "--at", ",".join("%.2f" % t for t in times), "-o", shots,
                                  "--format", "png", "--json").stdout)
        stills = rep["stills"]
        self.assertEqual(len(stills), len(times))
        paths = [Path(s["file"]) for s in sorted(stills, key=lambda s: s["t"])]
        order = json.loads((RUNTIME / "transitions" / "catalog.json").read_text(encoding="utf-8"))
        gl = [t["name"] for t in order["transitions"] if t["kind"] == "webgl"]
        failures = []
        for k in range(n):
            a, mid, b = (mean_rgb(p) for p in paths[3 * k:3 * k + 3])
            if dist(a, b) < 60:
                failures.append("%s: scenes not distinct %s %s" % (gl[k], a, b))
            if max(mid) < 25:
                failures.append("%s: black middle frame %s" % (gl[k], mid))
            if dist(mid, a) < 8 or dist(mid, b) < 8:
                failures.append("%s: middle frame equals an end frame (a=%s mid=%s b=%s)" % (gl[k], a, mid, b))
        RESULTS["shader_snaps"] = {"frames": len(times), "seconds": round(time.time() - t0, 1)}
        self.assertEqual(failures, [])

    # ------------------------------------------------------------- templates
    def _render(self, template, frm, to, scale, want_size):
        proj = self.tmp / template
        showtime("new", template, proj)
        t0 = time.time()
        rep = json.loads(showtime("render", proj, "--out-dir", self.out, "--from", frm, "--to", to, "--scale", scale,
                                  "--poster", "none", "--no-audio", "--json").stdout)
        mp4 = Path(rep["output"])
        self.assertTrue(mp4.is_file(), rep)
        v = probe_video(mp4)
        self.assertEqual((v["width"], v["height"]), want_size)
        frames = int(v["nb_read_packets"])
        self.assertAlmostEqual(frames, round((to - frm) * 30), delta=1)
        RESULTS["render_" + template] = {"size": "%dx%d" % want_size, "frames": frames, "wall_s": round(time.time() - t0, 1)}
        return mp4

    def test_07_template_dom_with_shader(self):
        # the last 3.5 s: proof scene, sdf-iris shader transition, end card
        mp4 = self._render("dom", 11.5, 15.0, 0.6667, (1280, 720))
        frames = self.tmp / "dom_frames"
        frames.mkdir()
        for name, t in (("before", "0.8"), ("mid", "1.35"), ("after", "3.2")):
            ff.run_ffmpeg(["-ss", t, "-i", mp4, "-frames:v", "1", frames / (name + ".png")])
        a, mid, b = (mean_rgb(frames / (x + ".png")) for x in ("before", "mid", "after"))
        self.assertGreater(max(mid), 10, "shader frame is black")
        self.assertGreater(dist(mid, a) + dist(mid, b), 6, (a, mid, b))

    def test_08_template_short(self):
        self._render("short", 0.0, 3.5, 0.5, (540, 960))

    def test_09_template_data(self):
        self._render("data", 2.2, 5.8, 0.6667, (1280, 720))

    def test_10_check_short(self):
        if FAST:
            self.skipTest("--fast")
        proj = self.tmp / "short_check"
        showtime("new", "short", proj)
        cp = showtime("check", proj, "--json", "--no-timeline", check=False)
        rep = json.loads(cp.stdout)
        errors = [f for f in rep["findings"] if f["severity"] == "error"]
        self.assertEqual(errors, [], errors)
        self.assertFalse(rep["determinism"]["unstable"])
        used = rep["fonts"]["used"]
        self.assertTrue(used and all(v.get("custom") for k, v in used.items() if k.lower() not in ("", "none")), used)

    def test_11_preview_player_with_components(self):
        """The preview player (no virtual-time shim) drives the dom template's components, CSS and WebGL
        transitions and its generated audio mix: scrubbing, play, frame step, no page errors."""
        if FAST:
            self.skipTest("--fast")
        proj = self.tmp / "preview_dom"
        showtime("new", "dom", proj, "--width", 960, "--height", 540)
        info = json.loads(showtime("preview", proj, "--no-open", "--json", "--port", 4870, timeout=300).stdout.strip().splitlines()[-1])
        try:
            js = self.tmp / "preview_probe.mjs"
            js.write_text(PREVIEW_JS.replace("__CHROME_MJS__", (SKILL / "scripts" / "lib" / "chrome.mjs").as_uri()),
                          encoding="utf-8")
            cp = subprocess.run([node_exe(), str(js), info["url"]], capture_output=True, text=True, timeout=300)
            self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
            rep = json.loads(cp.stdout.strip().splitlines()[-1])
        finally:
            showtime("preview", proj, "--stop", check=False)
        self.assertIn("audio: mix", rep["status"])
        by_t = {s["t"]: s for s in rep["shots"]}
        self.assertEqual(by_t[1.0]["active"], ["hero"])
        self.assertEqual(by_t[4.9]["active"], ["hero"])
        self.assertEqual(by_t[8.6]["active"], ["features"])
        self.assertEqual(by_t[12.3]["gl"], 1, "the sdf-iris shader transition did not draw in the player")
        self.assertTrue(all(s["mounted"] >= 8 for s in rep["shots"]), rep["shots"])
        self.assertGreater(rep["afterPlay"]["t"], 1.0)
        self.assertIn("mix", rep["afterPlay"]["bufs"])
        self.assertFalse(rep["afterStep"]["playing"])
        self.assertEqual(rep["errors"], [])

    def test_12_templates_retime_coherently(self):
        """Every shipped template, lengthened and shortened with `new --duration`: the scenes (or the canvas
        cue table) end exactly at the new length, and poster, music sections and sfx stay inside it."""
        sys.path.insert(0, str(SKILL / "lib"))
        from st.cli_core import _Tags, list_templates
        names = [t["name"] for t in list_templates()]
        self.assertTrue({"dom", "short", "data", "film", "tutorial"} <= set(names), names)
        for name in names:
            old = float(json.loads((SKILL / "templates" / name / "showtime.json").read_text(encoding="utf-8"))["duration"])
            for new in (round(old * 1.4, 1), round(old * 0.8, 1)):
                proj = self.tmp / ("rt-%s-%s" % (name, new))
                showtime("new", name, proj, "--duration", new)
                cfg = json.loads((proj / "showtime.json").read_text(encoding="utf-8"))
                self.assertEqual(cfg["duration"], new)
                self.assertLess(cfg["poster"], new, name)
                html = (proj / "index.html").read_text(encoding="utf-8")
                scenes = [c for c in _Tags(html).resolve() if c["parent"] is None]
                if scenes:
                    self.assertAlmostEqual(max(c["t1"] for c in scenes), new, places=3, msg=name)
                    starts = sorted(c["t0"] for c in scenes)
                else:
                    cues = (proj / "cues.js").read_text(encoding="utf-8")
                    self.assertRegex(cues, r"\n\s*duration: %s," % re.escape(("%g" % new)), name)
                    starts = []
                mix = proj / "audio" / "mix.json"
                if mix.is_file():
                    spec = json.loads(mix.read_text(encoding="utf-8"))
                    for tr in spec["tracks"]:
                        self.assertLess(tr.get("at", 0), new, (name, tr))
                        secs = (tr.get("compose") or {}).get("sections")
                        if secs:
                            times = [float(x.split(":")[0]) for x in secs.split(",")]
                            for t in times:             # every music section starts on a scene start
                                self.assertTrue(any(abs(t - s0) < 0.002 for s0 in starts), (name, new, secs, starts))


    def test_12b_retime_overlays_and_frames(self):
        """14.3/17.7/12.1: `retime --from-voice` treats top-level clips that are not scenes as overlays (a credit
        spanning two scenes, an open-ended logo bug) instead of refusing them, and every scene start lands on a
        whole frame, written at or just below the frame time (53.434 for frame 53.4333 made a one-frame flash)."""
        from st.cli_core import _Tags, _split_tops
        proj = self.tmp / "rt-overlay"
        (proj / "voice").mkdir(parents=True, exist_ok=True)
        (proj / "showtime.json").write_text(json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 12}),
                                            encoding="utf-8")
        (proj / "index.html").write_text(
            '<!doctype html><html><body><div class="stage">'
            '<section class="scene" id="open" data-start="0" data-dur="4"><h1>a</h1></section>'
            '<section class="scene" id="mid" data-start="4" data-dur="4"><h1>b</h1></section>'
            '<section class="scene" id="end" data-start="8" data-dur="4"><h1>c</h1></section>'
            '<div class="credit" data-start="5" data-dur="5">Photo: USGS</div>'
            '<div class="bug" data-start="1">logo</div>'
            '</div></body></html>', encoding="utf-8")
        lines = []
        t = 0.0
        # open ends at 0.3 pad + 3.2004 = 3.5004 s: 0.4 ms after frame 105 (3.5 s at 30 fps)
        for lid, d in (("open", 3.2004), ("mid", 5.1234), ("end", 2.0417)):
            lines.append({"id": lid, "file": "lines/%s.wav" % lid, "start": t, "end": t + d - 0.3,
                          "slot": {"start": t, "end": t + d, "duration": d}, "words": []})
            t += d
        (proj / "voice" / "timeline.json").write_text(json.dumps({"file": "vo.wav", "duration": t, "lines": lines}),
                                                      encoding="utf-8")
        showtime("retime", proj, "--from-voice", proj / "voice" / "timeline.json")
        clips = _Tags((proj / "index.html").read_text(encoding="utf-8")).resolve()
        scenes, overlays = _split_tops(clips)
        self.assertEqual([c["id"] for c in scenes], ["open", "mid", "end"])
        self.assertEqual(len(overlays), 2)
        # an edge within 1 ms of a frame is written at or just below it; other times are kept
        for c in scenes:
            for v in (c["t0"], c["t1"]):
                n = v * 30
                if abs(n - round(n)) < 0.031:
                    self.assertLessEqual(v, round(n) / 30 + 1e-9, "%s: %s is after its frame time" % (c["id"], v))
        self.assertEqual(round(scenes[0]["t1"], 4), 3.5)
        credit = next(c for c in overlays if c["attrs"].get("class") == "credit")
        mid, end = scenes[1], scenes[2]
        self.assertGreater(credit["t0"], mid["t0"])
        self.assertLess(credit["t0"], mid["t1"], "the credit still starts inside the middle scene")
        self.assertGreater(credit["t1"], end["t0"], "and still ends inside the last one")
        cp = showtime("retime", "--help")
        self.assertIn("animation-delay", cp.stdout)

    # ------------------------------------------------ round 3
    def _check(self, proj, *extra):
        cp = showtime("check", proj, "--json", "--no-determinism", *extra, check=False)
        return json.loads(cp.stdout)

    def test_13_data_template_labels_and_callout(self):
        """The data template's chart labels are legible (no small_text notes), the annotate badge sits
        above the value labels (check's badge-over-label audit finds nothing) and the stat block's
        count-up has no gap/overlap between number and suffix."""
        proj = self.tmp / "data_labels"
        showtime("new", "data", proj, "--size", "1280x720")
        rep = self._check(proj, "--no-timeline", "--samples", "3", "--at", "5.2,6.4,12.6,13.5")
        bad = [f for f in rep["findings"] if f["severity"] != "info" or f["code"] == "small_text"]
        self.assertEqual(bad, [], bad)
        # a callout on the tallest bar, next to tall neighbours: the axis makes room above the labels
        csvf = self.tmp / "tall.csv"
        csvf.write_text("m,v\nA,95\nB,99\nC,100\nD,98\nE,97\n", encoding="utf-8")
        showtime("data", "import", csvf, proj, "--y", "v", "--scene", "bars", "--highlight", "max",
                 "--annotate", "a long callout text here", "--title", "Tall bars")
        rep = self._check(proj, "--no-timeline", "--samples", "2", "--at", "5.0,6.4")
        ov = [f for f in rep["findings"] if f["code"] in ("text_overlap", "text_off_canvas", "text_clipped")]
        self.assertEqual(ov, [], ov)
        css = (RUNTIME / "components" / "components.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.st-chart-plot \{[^}]*font-size: max\(2\.3cqmin, var\(--chart-min-font, max\(2\.7vmin, 2\.3vh\)\)\)")
        self.assertRegex(css, r"\.st-cu-figure \{[^}]*gap: 0\.06em")

    def test_13b_chart_negatives_decimals_ties_ref(self):
        """07: a bar chart of anomalies draws negative bars below a zero line; `decimals` from the JSON
        file is used (no data-decimals on the element) for value and tick labels; count: false shows
        the final values; a reference line is labelled; tied hbar values get a row each."""
        proj = self.tmp / "chartneg"
        (proj / "data").mkdir(parents=True)
        (proj / "data" / "a.json").write_text(json.dumps({
            "data": [{"label": "1976", "value": -0.49}, {"label": "2015", "value": 0.9}, {"label": "2024", "value": 1.29}],
            "decimals": 2, "prefix": "+", "suffix": " °C", "count": False,
            "ref": {"value": 0.75, "label": "2014: +0.75", "sub": "next warmest"}}), encoding="utf-8")
        (proj / "data" / "h.json").write_text(json.dumps({"type": "hbar", "data": [
            {"label": "a", "value": 1.01}, {"label": "b", "value": 1.01}, {"label": "c", "value": 0.85}]}), encoding="utf-8")
        (proj / "showtime.json").write_text(json.dumps({"width": 1280, "height": 720, "fps": 30, "duration": 4}), encoding="utf-8")
        (proj / "index.html").write_text(
            '<!doctype html><html><head><script src="/_st/stage.js"></script>'
            '<link rel="stylesheet" href="/_st/themes/editorial.css"><script type="module" src="/_st/components/index.js"></script>'
            '</head><body><div class="stage"><section class="scene" data-start="0" data-dur="4">'
            '<div id="c" data-st="chart" data-src="data/a.json" style="position:absolute;left:5%;top:8%;width:55%;height:80%"></div>'
            '<div id="h" data-st="chart" data-src="data/h.json" style="position:absolute;left:64%;top:8%;width:32%;height:60%"></div>'
            '</section></div></body></html>', encoding="utf-8")
        rep = self._check(proj, "--no-timeline", "--samples", "2", "--at", "3.8")
        texts = " | ".join(t["text"] for t in rep["texts"])
        for want in ("−0.49 °C", "+1.29 °C", "2014: +0.75", "next warmest"):
            self.assertIn(want, texts)
        self.assertRegex(texts, r"[+−]?0\.5 °C")          # tick labels carry the step's decimals
        self.assertNotIn("+-", texts)
        # geometry, from the page: the 1976 bar hangs below the zero line; tied hbar rows differ
        js = ("const c=document.querySelectorAll('#c rect.st-chart-bar');const z=document.querySelector('#c .st-chart-zero');"
              "const rows=[...document.querySelectorAll('#h .st-chart-row')].map(r=>r.getAttribute('transform'));"
              "JSON.stringify({negTop:+c[0].getAttribute('y'), zero:+z.getAttribute('y1'), posBottom:+c[2].getAttribute('y')+ +c[2].getAttribute('height'), rows})")
        drv = self.tmp / "chartneg-probe.mjs"
        drv.write_text(PROBE_JS % {"skill": json.dumps(str(SKILL)), "proj": json.dumps(str(proj)), "t": 3.8, "js": json.dumps(js)},
                       encoding="utf-8")
        cp = subprocess.run([node_exe(), str(drv)], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=180)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        g = json.loads(json.loads(cp.stdout.strip().splitlines()[-1]))
        self.assertAlmostEqual(g["negTop"], g["zero"], delta=1.0)
        self.assertAlmostEqual(g["posBottom"], g["zero"], delta=1.0)
        self.assertEqual(len(set(g["rows"])), 3, g["rows"])

    def test_13c_browser_frame_scroll_overlay_camera(self):
        """01/10: a data-scroll step on a data-src screenshot really scrolls (targets are measured in
        setup, not on the first, hidden, frame); children next to data-src stay as an overlay; camera
        "frame" scales the whole window."""
        proj = self.tmp / "bwscroll"
        (proj / "shots").mkdir(parents=True)
        (proj / "shots" / "tall.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="3000">'
                                                 '<rect width="800" height="3000" fill="#eee"/><rect y="1500" width="800" height="200" fill="#c33"/></svg>',
                                                 encoding="utf-8")
        (proj / "showtime.json").write_text(json.dumps({"width": 960, "height": 540, "fps": 30, "duration": 4}), encoding="utf-8")
        (proj / "index.html").write_text(
            '<!doctype html><html><head><script src="/_st/stage.js"></script>'
            '<link rel="stylesheet" href="/_st/themes/neutral.css"><script type="module" src="/_st/components/index.js"></script>'
            '</head><body><div class="stage">'
            '<section class="scene" data-start="0" data-dur="1"><h1>First</h1></section>'
            '<section class="scene" data-start="1" data-dur="3">'
            '<div id="bw" data-st="browser-frame" data-src="shots/tall.svg" data-scroll=\'[{"at":0.3,"to":0.5,"dur":0.6}]\' '
            'style="position:absolute;inset:8% 10%"><div id="ring" style="position:absolute;left:10%;top:10%;width:20%;height:5%;border:3px solid red"></div></div>'
            '<div id="bw2" data-st="browser-frame" data-src="shots/tall.svg" data-camera="frame" data-zoom=\'[{"at":0.2,"scale":1.5,"x":50,"y":50,"dur":0.4}]\' '
            'style="position:absolute;inset:60% 60% 5% 5%"></div>'
            '</section></div></body></html>', encoding="utf-8")
        js = ("JSON.stringify({page: document.querySelector('#bw .st-bw-page').style.transform,"
              " ring: !!document.querySelector('#bw .st-frame-overlay #ring'),"
              " frame: document.querySelector('#bw2').style.transform, view: document.querySelector('#bw2 .st-bw-view').style.transform})")
        drv = self.tmp / "bw-probe.mjs"
        drv.write_text(PROBE_JS % {"skill": json.dumps(str(SKILL)), "proj": json.dumps(str(proj)), "t": 2.5, "js": json.dumps(js)},
                       encoding="utf-8")
        cp = subprocess.run([node_exe(), str(drv)], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", timeout=180)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        g = json.loads(json.loads(cp.stdout.strip().splitlines()[-1]))
        m = re.search(r"translateY\((-?[\d.]+)px\)", g["page"])
        self.assertTrue(m and float(m.group(1)) < -50, g)
        self.assertTrue(g["ring"], g)
        self.assertIn("scale(1.5", g["frame"])
        self.assertEqual(g["view"], "")

    def test_14_end_card_logo_and_name(self):
        """end-card with data-logo AND data-text shows both the mark and the product name."""
        proj = self.tmp / "endcard"
        (proj / "shots").mkdir(parents=True)
        (proj / "shots" / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">'
                                                 '<circle cx="32" cy="32" r="28" fill="#7c5cff"/></svg>', encoding="utf-8")
        (proj / "showtime.json").write_text(json.dumps({"width": 960, "height": 540, "fps": 30, "duration": 3}), encoding="utf-8")
        (proj / "index.html").write_text(
            '<!doctype html><html><head><script src="/_st/stage.js"></script>'
            '<link rel="stylesheet" href="/_st/themes/bold.css"><script type="module" src="/_st/components/index.js"></script>'
            '</head><body><div class="stage"><section class="scene" data-start="0" data-dur="3">'
            '<div data-st="end-card" data-logo="shots/logo.svg" data-text="Nimbus" data-tagline="Weather for teams" data-cta="Try it"></div>'
            '</section></div></body></html>', encoding="utf-8")
        rep = self._check(proj, "--no-timeline", "--samples", "2", "--at", "2.8")
        texts = [t["text"] for t in rep["texts"]]
        self.assertTrue(any(t.startswith("Nimbus") for t in texts), texts)
        self.assertIn("Weather for teams", texts)
        self.assertEqual([f for f in rep["findings"] if f["severity"] == "error"], [])
        js = (RUNTIME / "components" / "end-card.js").read_text(encoding="utf-8")
        self.assertIn("st-ec-brand", js)

    def test_15_still_screenshot_drifts(self):
        """A browser-frame around a still image gets a slow push-in by default, so a 4 s scene is not
        a still hold; data-drift="none" turns it off (and check then warns, like qa)."""
        if FAST:
            self.skipTest("--fast")
        proj = self.tmp / "drift"
        (proj / "shots").mkdir(parents=True)
        ff.run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=1280x800:rate=1", "-frames:v", "1", proj / "shots" / "app.png"])
        (proj / "showtime.json").write_text(json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 4.5}), encoding="utf-8")
        page = ('<!doctype html><html><head><script src="/_st/stage.js"></script>'
                '<link rel="stylesheet" href="/_st/themes/neutral.css"><script type="module" src="/_st/components/index.js"></script>'
                '<style>.bf{position:absolute;inset:8%% 10%%}</style></head><body><div class="stage">'
                '<section class="scene" data-start="0" data-dur="4.5"><div class="bf" data-st="browser-frame" data-src="shots/app.png" %s></div>'
                '</section></div></body></html>')
        (proj / "index.html").write_text(page % "", encoding="utf-8")
        rep = self._check(proj, "--samples", "2")
        self.assertEqual([f for f in rep["findings"] if f["code"] == "dead_air"], [])
        (proj / "index.html").write_text(page % 'data-drift="none"', encoding="utf-8")
        rep = self._check(proj, "--samples", "2")
        self.assertTrue([f for f in rep["findings"] if f["code"] in ("dead_air", "final_hold")], rep["findings"])


PREVIEW_JS = r"""
import { launchBrowser } from '__CHROME_MJS__';
const url = process.argv[2];
const { browser } = await launchBrowser({ headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
const errs = [];
try {
  const page = await browser.newPage({ viewport: { width: 1100, height: 760 } });
  page.on('pageerror', (e) => errs.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errs.push('console: ' + m.text()); });
  await page.goto(url);
  await page.waitForFunction(() => window.__stPlayer && window.__stPlayer.state.ready, null, { timeout: 90000 });
  await page.waitForFunction(() => /audio/.test(document.querySelector('#st-status')?.textContent || ''), null, { timeout: 120000 }).catch(() => {});
  const res = { status: await page.evaluate(() => document.querySelector('#st-status')?.textContent || ''), shots: [] };
  for (const t of [1.0, 4.9, 8.6, 12.3]) {
    await page.evaluate((x) => window.__stPlayer.go(x), t);
    await page.waitForTimeout(t === 12.3 ? 1500 : 400);
    res.shots.push({ t, ...(await page.evaluate(() => {
      const d = document.querySelector('iframe').contentDocument;
      return {
        active: [...d.querySelectorAll('section.scene')].filter((s) => getComputedStyle(s).display !== 'none').map((s) => s.id),
        mounted: [...d.querySelectorAll('[data-st]')].filter((e) => e.children.length || e.shadowRoot || e.tagName === 'CANVAS').length,
        gl: [...d.querySelectorAll('canvas[data-st-gl]')].filter((c) => getComputedStyle(c).display !== 'none').length,
      };
    })) });
  }
  await page.evaluate(() => { window.__stPlayer.go(0); window.__stPlayer.play(); });
  await page.waitForTimeout(2000);
  res.afterPlay = await page.evaluate(() => ({ t: window.__stPlayer.state.t, bufs: Object.keys((window.__stPlayer.state.audio || {}).buffers || {}) }));
  await page.keyboard.press('Space');
  await page.keyboard.press('ArrowRight');
  res.afterStep = await page.evaluate(() => ({ t: window.__stPlayer.state.t, playing: window.__stPlayer.state.playing }));
  res.errors = errs;
  console.log(JSON.stringify(res));
} finally {
  await browser.close();
}
"""


class DataImportTests(unittest.TestCase):
    """12.5/12.6/12.9: `data import` writes the data even when --scene has no chart element (and prints the
    element to add), --names sets display names, --where reduces a long table."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-data-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_where_names_and_scene_without_chart(self):
        proj = self.tmp / "proj"
        showtime("new", "data", proj)
        table = self.tmp / "eia.csv"
        table.write_text("MSN,YYYYMM,Value\nCLETPUS,202401,10\nCLETPUS,202413,120\nNGETPUS,202413,300\n"
                         "WSETPUS,202413,90\nCLETPUS,202313,130\nNGETPUS,202313,280\nWSETPUS,202313,70\n",
                         encoding="utf-8")
        cp = showtime("data", "import", table, proj, "--where", "YYYYMM~13$", "--x", "YYYYMM", "--y", "Value",
                      "--series", "MSN", "--chart", "line", "--names", "CLETPUS=Coal,NGETPUS=Natural gas",
                      "--names", "WSETPUS=Wind + solar", "--scene", "stat", "--title", "Coal fell", "--json")
        res = json.loads(cp.stdout)
        data = json.loads(Path(res["output"]).read_text(encoding="utf-8"))
        self.assertEqual(data["data"]["labels"], ["202413", "202313"], "the monthly row is filtered out")
        self.assertEqual([x["name"] for x in data["data"]["series"]], ["Coal", "Natural gas", "Wind + solar"])
        self.assertIsNone(res["scene"])
        self.assertTrue(any("no chart element" in n and 'data-st="chart"' in n for n in res["notes"]), res["notes"])
        self.assertTrue(any("kept 6 of 7 rows" in n for n in res["notes"]), res["notes"])
        cp = showtime("data", "import", table, proj, "--where", "MSN=NOPE", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("no row matches", cp.stderr)
        wide = self.tmp / "mix.csv"
        wide.write_text("year,wind_solar,coal\n2023,10,20\n2024,15,18\n", encoding="utf-8")
        res = json.loads(showtime("data", "import", wide, proj, "--chart", "line", "--names", "wind_solar=Wind + solar",
                                  "--title", "t", "--json").stdout)
        self.assertEqual([x["name"] for x in res["data"]["data"]["series"]], ["Wind + solar", "Coal"])


class AssetsTests(unittest.TestCase):
    """17.9 cutout --max-size, 19.4 Commons thumbnail steps and Retry-After, 14.5 fetch a URL with a license
    sidecar (offline: a local server)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-assets-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_cutout_size_cap(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")
        from st.assets import cutout
        p = self.tmp / "cut.png"
        im = Image.new("RGBA", (3000, 1500), (0, 0, 0, 0))
        for x in range(800, 2200):
            for y in range(400, 402):
                im.putpixel((x, y), (255, 0, 0, 255))
        im.paste((200, 30, 30, 255), (1000, 500, 2000, 1200))
        im.save(p)
        r = cutout._post(p, self.tmp / "mask.png", False, 0, 1800)
        self.assertEqual((r["width"], r["height"]), (1800, 900))
        self.assertEqual(r["resized_from"], [3000, 1500])
        with Image.open(self.tmp / "mask.png") as m:
            self.assertEqual(m.size, (1800, 900), "the mask matches the PNG")
        r = cutout._post(p, None, False, 0, 0)
        self.assertEqual(r["width"], 1800)
        self.assertIn("--max-size", showtime("assets", "cutout", "--help").stdout)

    def test_commons_steps_retry_after_and_url_fetch(self):
        import http.server
        import threading
        from st.assets import licenses, media, net
        self.assertEqual(media.commons_step(2560), 1920)
        self.assertEqual(media.commons_step(3840), 3840)
        self.assertEqual(media.commons_step(100), media.COMMONS_STEPS[0])
        self.assertEqual(net.retry_after("7"), 7.0)
        self.assertIsNone(net.retry_after("soon"))
        self.assertGreater(net.retry_after("Wed, 21 Oct 2099 07:28:00 GMT"), 1e6)
        root = self.tmp / "www"
        root.mkdir()
        (root / "fig3.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 2000)

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **k):
                super().__init__(*a, directory=str(root), **k)

            def log_message(self, *a):
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        old_paths = media.paths
        media.paths = lambda: {"media": self.tmp / "cache"}
        try:
            url = "http://127.0.0.1:%d/fig3.png" % srv.server_address[1]
            with self.assertRaises(Exception) as cm:
                media.fetch_url(url, license=None)
            self.assertIn("--license", str(getattr(cm.exception, "hint", "")) + str(cm.exception))
            res = media.fetch_url(url, license="public-domain", source_page="https://pubs.example/page",
                                  author="USGS", project=self.tmp / "proj")
            side = licenses.read_sidecar(Path(res["path"]))
            self.assertEqual(side["license"], "public-domain")
            self.assertEqual(side["landing_url"], "https://pubs.example/page")
            self.assertEqual(side["file_url"], url)
            self.assertFalse(res["attribution_required"])
            self.assertTrue(Path(res["path"]).is_file())
        finally:
            media.paths = old_paths
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

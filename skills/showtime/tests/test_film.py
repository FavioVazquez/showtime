#!/usr/bin/env python3
"""Film module smoke tests: runtime/film.js, runtime/synth.js, templates/film, templates/tutorial,
templates/series (+ scripts/series.mjs), scripts/score.mjs, the export minifier.

  * unit checks of the pure JS helpers under Node (easing, springs, keyframes, noise, theory, named
    UI rects, state from events, camera clamping, the minifier and runtime part pruning)
  * static checks: no wall clocks / unseeded randomness in the runtime or templates, files present
  * full mode: `showtime new` + `showtime render` of both templates at 1280x720, probe the MP4s,
    frames not blank, `showtime score` loudness/sections, and click timing in the score WAV;
    seeking the procedural score (a render that starts mid-film equals the same stretch of a render
    from 0: pads, bass, leads, risers, whooshes and ducks resume at their phase and level; short
    sounds are not played twice), realtime playback from mid-pad measured with an AnalyserNode;
    the series pattern (new series, check/sync/add, episodes render)

Stdlib only. usage: python tests/test_film.py [--fast] [-v]
  --fast   skip everything that needs a browser (CI smoke)
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from array import array
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
NODE = shutil.which("node", path=ENV.get("PATH"))


def showtime(*args, check=True, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def last_json(text):
    """Parse the JSON document printed on stdout (tolerates log lines before it)."""
    i = text.find("{")
    if i < 0:
        raise AssertionError("no JSON in output:\n" + text[-2000:])
    return json.loads(text[i:])


def read_wav(path):
    """-> (sample_rate, channels, samples[list of floats, interleaved]) for PCM16 or float32 WAV."""
    data = Path(path).read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise AssertionError("%s is not a WAV file" % path)
    pos, fmt, sr, ch, bits, samples = 12, None, 0, 0, 0, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt, ch, sr = struct.unpack("<HHI", body[:8])
            bits = struct.unpack("<H", body[14:16])[0]
        elif cid == b"data":
            if fmt == 3 and bits == 32:
                samples = array("f")
                samples.frombytes(body[: len(body) // 4 * 4])
            elif fmt == 1 and bits == 16:
                raw = array("h")
                raw.frombytes(body[: len(body) // 2 * 2])
                samples = array("f", (v / 32768.0 for v in raw))
            else:
                raise AssertionError("unsupported WAV format %s/%s" % (fmt, bits))
            if sys.byteorder == "big":
                samples.byteswap()
        pos += 8 + size + (size & 1)
    if samples is None:
        raise AssertionError("no data chunk in %s" % path)
    return sr, ch, samples


def run_node(code):
    cp = subprocess.run([NODE, "-e", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        encoding="utf-8", errors="replace", timeout=60)
    if cp.returncode != 0:
        raise AssertionError("node failed:\n" + cp.stderr[-3000:])
    return json.loads(cp.stdout.strip().splitlines()[-1])


# --------------------------------------------------------------------------- static checks

class TestFiles(unittest.TestCase):
    RUNTIME = [SKILL / "runtime" / "film.js", SKILL / "runtime" / "synth.js"]
    TEMPLATES = [SKILL / "templates" / "film", SKILL / "templates" / "tutorial"]
    SERIES = SKILL / "templates" / "series"

    def test_series_template(self):
        for name in ("showtime.json", "series.json", "index.html", "cues.js", "opener.js", "kit.js", "README.md",
                     "episode-01/showtime.json", "episode-01/index.html", "episode-01/episode.js", "episode-01/kit.js"):
            self.assertTrue((self.SERIES / name).is_file(), name)
        kit = (self.SERIES / "kit.js").read_text(encoding="utf-8")
        copy = (self.SERIES / "episode-01" / "kit.js").read_text(encoding="utf-8")
        self.assertTrue(copy.endswith(kit), "episode-01/kit.js must be a synced copy of kit.js (run `showtime series sync`)")
        bad = re.compile(r"Math\.random\s*\(|Date\.now\s*\(|performance\.now\s*\(|new Date\s*\(")
        for f in [self.SERIES / "kit.js", self.SERIES / "cues.js", self.SERIES / "opener.js", self.SERIES / "episode-01" / "episode.js"]:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("//")[0]
                if not code.strip().startswith("*"):
                    self.assertIsNone(bad.search(code), "%s:%d uses a clock or unseeded random" % (f.name, i))

    def test_files_present(self):
        for p in self.RUNTIME + [SKILL / "references" / "film-api.md", SKILL / "references" / "synth-score.md",
                                 SKILL / "scripts" / "score.mjs"]:
            self.assertTrue(p.is_file(), p)
        for t in self.TEMPLATES:
            for name in ("showtime.json", "index.html", "README.md", "cues.js", "scenes.js", "score.js"):
                self.assertTrue((t / name).is_file(), t / name)
            cfg = json.loads((t / "showtime.json").read_text(encoding="utf-8"))
            for k in ("width", "height", "fps", "duration"):
                self.assertGreater(float(cfg[k]), 0, "%s: %s" % (t.name, k))

    def test_no_clocks_or_unseeded_random(self):
        bad = re.compile(r"Math\.random\s*\(|Date\.now\s*\(|performance\.now\s*\(|new Date\s*\(")
        files = list(self.RUNTIME)
        for t in self.TEMPLATES:
            files += sorted(t.glob("*.js"))
        for f in files:
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("//")[0]
                if code.strip().startswith("*"):
                    continue
                self.assertIsNone(bad.search(code), "%s:%d uses a clock or unseeded random: %s" % (f.name, i, line.strip()))

    def test_templates_use_explicit_fonts_and_runtime(self):
        for t in self.TEMPLATES:
            html = (t / "index.html").read_text(encoding="utf-8")
            self.assertIn("/_st/stage.js", html)
            self.assertIn("/_st/film.js", html)
            self.assertIn("/_st/synth.js", html)
            self.assertRegex(html, r"/_lib/@fontsource(-variable)?/", "fonts must come from bundled files")
            # no symbols the bundled fonts lack inside drawn text (they would differ per OS)
            for js in t.glob("*.js"):
                for i, line in enumerate(js.read_text(encoding="utf-8").splitlines(), 1):
                    if "F.text(" in line or "F.reveal(" in line:
                        self.assertIsNone(re.search(r"[←-⇿⌀-⏿]", line),
                                          "%s:%d draws a symbol as text; use F.glyph/F.keycap" % (js.name, i))


# --------------------------------------------------------------------------- node unit checks

@unittest.skipUnless(NODE, "node not found")
class TestRuntimeUnits(unittest.TestCase):
    def test_film_math(self):
        film = str(SKILL / "runtime" / "film.js")
        r = run_node("""
require(%s); const F = globalThis.Film;
const sp = F.spring(0.5, 0.7), sd = F.spring(0.4, 1);
const bz = F.bezier(0.16, 1, 0.3, 1);
let mono = true, prev = -1; for (let i = 0; i <= 100; i++) { const v = bz(i / 100); if (v < prev - 1e-9) mono = false; prev = v; }
const r1 = F.rng(42), r2 = F.rng(42);
const out = {
  springEnds: [sp(0), sp(1), sd(1)], springDur: sp.duration, springOvershoot: Math.max(...Array.from({length: 200}, (_, i) => sp(i / 199))),
  bezierMono: mono, bezierEnds: [bz(0), bz(1)],
  seg: [F.seg(1, 2, 3), F.seg(2.5, 2, 3), F.seg(4, 2, 3)],
  win: [F.win(0.5, 1, 3, 0.5), F.win(2, 1, 3, 0.5), F.win(3.5, 1, 3, 0.5)],
  kf: F.kf(1.5, [[1, 0], [2, 10, 'linear']]), kfColor: F.kf(0.5, [[0, '#000000'], [1, '#ffffff', 'linear']]),
  hash: [F.hash(7) === F.hash(7), F.hash(7) !== F.hash(8)], rng: r1() === r2() && r1() === r2(),
  noiseRange: Math.max(...Array.from({length: 500}, (_, i) => Math.abs(F.noise(i * 0.37, 3)))),
  stagger: [F.stagger(0.2, 0, 5, 0, {each: 0.1, dur: 0.4, ease: 'linear'}), F.stagger(0.2, 4, 5, 0, {each: 0.1, dur: 0.4})],
  easeNames: ['reveal', 'enter', 'exit', 'camera', 'snappy', 'outExpo', 'inOutBack'].map(n => F.ease(n, 1)),
  fmt: F.formatNumber(1234567.891, 2, ','), contrast: +F.contrast('#000', '#fff').toFixed(1),
  glyphs: ['⌘', '↵', '→', 'P'].map(F.glyphName),
};
console.log(JSON.stringify(out));
""" % json.dumps(film))
        self.assertEqual(r["springEnds"], [0, 1, 1])
        self.assertGreater(r["springDur"], 0.2)
        self.assertGreater(r["springOvershoot"], 1.0, "damping 0.7 should overshoot")
        self.assertTrue(r["bezierMono"])
        self.assertEqual(r["bezierEnds"], [0, 1])
        self.assertEqual(r["seg"], [0, 0.5, 1])
        self.assertEqual(r["win"][0], 0)
        self.assertEqual(r["win"][1], 1)
        self.assertEqual(r["win"][2], 0)
        self.assertAlmostEqual(r["kf"], 5.0)
        self.assertEqual(r["kfColor"], "rgba(128,128,128,1)")
        self.assertEqual(r["hash"], [True, True])
        self.assertTrue(r["rng"])
        self.assertLessEqual(r["noiseRange"], 1.0)
        self.assertAlmostEqual(r["stagger"][0], 0.5)
        self.assertEqual(r["stagger"][1], 0)
        self.assertEqual(r["easeNames"], [1] * 7)
        self.assertEqual(r["fmt"], "1,234,567.89")
        self.assertEqual(r["contrast"], 21.0)
        self.assertEqual(r["glyphs"], ["cmd", "return", "right", None])

    def test_film_ui_helpers(self):
        film = str(SKILL / "runtime" / "film.js")
        r = run_node("""
require(%s); const F = globalThis.Film;
const ui = F.rects({ save: [100, 20, 80, 40], row: (i) => [0, 100 + i * 50, 300, 40] }, { origin: [200, 300] });
const ev = [[5, { open: true }], [2, (s) => { s.n += 1; }], [5, (s, dt) => { s.dt = dt; }], [9, { open: false }]];
const init = { n: 0, open: false, list: [1] };
const a = F.fold(7, init, ev), b = F.fold(1, init, ev);
a.list.push(2);
let err = null; try { ui.rect('nope'); } catch (e) { err = String(e.message); }
const keys = F.namedKeys([[1, 'save', { click: true }], [2, 'row:2', { at: 'left' }], [3, 10, 20]], ui);
const cam = F.camera(1, [[0, 'save', 2]], { ui: ui });
const clamped = F.camera(0, [[0, 50, 60, 2]], { clamp: true });
const inWin = F.camera(0, [[0, 1900, 1000, 1.5]], { clamp: [200, 100, 1500, 840] });
const wide = F.clampCam({ x: 0, y: 0, zoom: 0.5 }, [200, 100, 1500, 840]);
console.log(JSON.stringify({ rect: ui.rect('save'), local: ui.local('save'), row: ui.rect('row', 2), rowStr: ui.rect('row:2'),
  center: ui.center('save'), right: ui.point('save', 'right'), err, a, b, init, keys, cam, clamped, inWin, wide }));
""" % json.dumps(film))
        self.assertEqual(r["rect"], {"x": 300, "y": 320, "w": 80, "h": 40})
        self.assertEqual(r["local"], {"x": 100, "y": 20, "w": 80, "h": 40})
        self.assertEqual(r["row"], r["rowStr"])
        self.assertEqual(r["row"]["y"], 300 + 200)
        self.assertEqual(r["center"], [340, 340])
        self.assertEqual(r["right"], [380, 340])
        self.assertIn("no rect named", r["err"])
        self.assertEqual(r["a"], {"n": 1, "open": True, "list": [1, 2], "dt": 2})
        self.assertEqual(r["b"], {"n": 0, "open": False, "list": [1]})
        self.assertEqual(r["init"], {"n": 0, "open": False, "list": [1]}, "fold must not change its initial state")
        self.assertEqual(r["keys"][0][:3], [1, 340, 340])
        self.assertEqual(r["keys"][1][:3], [2, 200, 520])
        self.assertEqual(r["keys"][2], [3, 10, 20])
        self.assertEqual((r["cam"]["x"], r["cam"]["y"], r["cam"]["zoom"]), (340, 340, 2))
        # clamped: the view never leaves the frame / the window
        self.assertEqual((r["clamped"]["x"], r["clamped"]["y"]), (480, 270))
        self.assertAlmostEqual(r["inWin"]["x"], 200 + 1500 - 1920 / 3, places=6)
        self.assertAlmostEqual(r["inWin"]["y"], 100 + 840 - 1080 / 3, places=6)
        self.assertEqual((r["wide"]["x"], r["wide"]["y"]), (950, 520), "a view wider than the bounds is centred on them")

    def test_decor_flag(self):
        """F.decor / {decor: true} mark canvas text as UI-mockup detail in Film.frameInfo() (check notes, not warnings)."""
        film = str(SKILL / "runtime" / "film.js")
        r = run_node(r"""
const ctx = new Proxy({ font: '', fillStyle: '#000', globalAlpha: 1, textAlign: 'left', textBaseline: 'alphabetic',
  measureText: (s) => ({ width: String(s).length * 10 }), getTransform: () => ({ a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }),
  createLinearGradient: () => ({ addColorStop() {} }), createRadialGradient: () => ({ addColorStop() {} }),
  getImageData: (x, y, w, h) => ({ data: new Uint8ClampedArray(4 * (w || 1) * (h || 1)) }),
  createImageData: (w, h) => ({ data: new Uint8ClampedArray(4 * w * (h || w)) }), createPattern: () => ({}) },
  { get: (t, k) => (k in t ? t[k] : () => {}), set: (t, k, v) => { t[k] = v; return true; } });
const el = () => ({ style: {}, setAttribute() {}, appendChild(c) { return c; }, getContext: () => ctx, addEventListener() {}, classList: { add() {} } });
globalThis.document = { createElement: el, body: el(), getElementById: () => null, querySelector: () => null,
  fonts: { add() {}, load: () => Promise.resolve([]), ready: Promise.resolve(), check: () => true } };
globalThis.window = globalThis; globalThis.devicePixelRatio = 1; globalThis.location = { search: '', hash: '' }; globalThis.requestAnimationFrame = () => 0;
console.warn = () => {};
require(%s); const F = globalThis.Film;
F.start({ width: 640, height: 360, duration: 2, scenes: (T, g, F) => {
  F.text('Headline', 20, 60, { size: 40 });
  F.text('tiny label', 20, 100, { size: 8, decor: true });
  F.decor(() => { F.text('mock menu', 20, 140, { size: 8 }); F.paragraph('a\nb', 20, 180, { size: 8 }); });
  try { F.decor(() => { throw new Error('x'); }); } catch (e) { /* the flag must not leak */ }
  F.text('after', 20, 220, { size: 30 });
} });
F.seek(1);
const fi = F.frameInfo();
console.log(JSON.stringify({ error: fi.error, texts: fi.texts.map((t) => [t.text, t.decor]) }));
""" % json.dumps(film))
        self.assertIsNone(r["error"])
        self.assertEqual(r["texts"], [["Headline", False], ["tiny label", True], ["mock menu", True], ["a", True],
                                      ["b", True], ["after", False]])

    def test_covers_for_qa(self):
        """Film.frameInfo().covers: callout cards (with their anchor), captions, the step band, spotlight dims
        and F.box {dims: true}, each with a draw order (z) after the texts under it; the band's number picks
        the readable one of white and the ground on a light accent."""
        film = str(SKILL / "runtime" / "film.js")
        r = run_node(r"""
const ctx = new Proxy({ font: '', fillStyle: '#000', globalAlpha: 1, textAlign: 'left', textBaseline: 'alphabetic',
  measureText: (s) => ({ width: String(s).length * 10 }), getTransform: () => ({ a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }),
  createLinearGradient: () => ({ addColorStop() {} }), createRadialGradient: () => ({ addColorStop() {} }),
  getImageData: (x, y, w, h) => ({ data: new Uint8ClampedArray(4 * (w || 1) * (h || 1)) }),
  createImageData: (w, h) => ({ data: new Uint8ClampedArray(4 * w * (h || w)) }), createPattern: () => ({}) },
  { get: (t, k) => (k in t ? t[k] : () => {}), set: (t, k, v) => { t[k] = v; return true; } });
const el = () => ({ style: {}, setAttribute() {}, appendChild(c) { return c; }, getContext: () => ctx, addEventListener() {}, classList: { add() {} } });
globalThis.document = { createElement: el, body: el(), getElementById: () => null, querySelector: () => null,
  fonts: { add() {}, load: () => Promise.resolve([]), ready: Promise.resolve(), check: () => true } };
globalThis.window = globalThis; globalThis.devicePixelRatio = 1; globalThis.location = { search: '', hash: '' }; globalThis.requestAnimationFrame = () => 0;
console.warn = () => {};
require(%s); const F = globalThis.Film;
F.start({ width: 640, height: 360, duration: 2, palette: { bg: '#06282E', accent: '#3CC5C0' }, scenes: (T, g, F) => {
  F.text('Title under a card', 100, 100, { size: 40 });
  F.spotlight({ x: 10, y: 10, w: 50, h: 50 }, { p: 1 });
  F.box(0, 200, 640, 100, 0, { fill: 'rgba(0,0,0,0.4)', dims: true });
  F.box(0, 0, 640, 40, 0, { fill: '#000' });   // no dims: not recorded
  F.callout(-30, 120, 120, 100, 'Look here', { p: 1 });
  F.stepBand(T, [[0, 'First step']], { end: 2 });
  F.caption('Spoken words', 1, {});
} });
F.seek(1);
const fi = F.frameInfo();
const title = fi.texts.find((t) => t.text === 'Title under a card');
const badge = fi.texts.find((t) => t.text === '1');
console.log(JSON.stringify({ error: fi.error, covers: fi.covers.map((c) => [c.kind, c.text, !!c.hole, c.anchor || null, c.z > title.z]),
  badge: badge && badge.color }));
""" % json.dumps(film))
        self.assertIsNone(r["error"])
        kinds = [c[0] for c in r["covers"]]
        self.assertEqual(kinds, ["dim", "dim", "callout", "band", "caption"], r["covers"])
        self.assertTrue(r["covers"][0][2], "a spotlight dim carries its hole")
        self.assertFalse(r["covers"][1][2], "a dims box has no hole")
        self.assertEqual(r["covers"][2][1], "Look here")
        self.assertEqual(r["covers"][2][3], [-30, 120], "a callout records its anchor (here off the frame)")
        self.assertTrue(all(c[4] for c in r["covers"]), "every cover is drawn after the text under it")
        self.assertEqual(r["badge"].lower(), "#06282e", "white on a light accent fails: the ground colour is used")

    def test_minifier_and_parts(self):
        mod = (SKILL / "scripts" / "lib" / "export" / "minify.mjs").as_uri()
        film = str(SKILL / "runtime" / "film.js")
        code = r"""
import fs from 'node:fs';
import vm from 'node:vm';
const { minifyJs, minifyCss, pruneParts } = await import(%s);
const out = {};
for (const f of ['film.js', 'synth.js', 'stage.js', 'player/player.js', 'player/boot.js', 'player/limiter.js']) {
  const src = fs.readFileSync(%s + f, 'utf8'), m = minifyJs(src);
  out[f] = { ok: m.ok, ratio: m.text.length / src.length };
}
// the minified film runtime computes exactly what the original does
const run = (src) => { const box = {}; box.globalThis = box; vm.runInNewContext(src, box); const F = box.Film;
  return JSON.stringify([F.seg(2.5, 2, 3), F.kf(1.5, [[1, 0], [2, 10]]), F.hash(7), F.noise(1.37, 3), F.ease('reveal', 0.3), F.formatNumber(1234.5, 1, ','), F.rects({a: [1, 2, 3, 4]}).center('a')]); };
const src = fs.readFileSync(%s, 'utf8');
out.same = run(src) === run(minifyJs(src).text);
// tricky syntax survives: regex vs division, templates, ASI across lines, strings with comment markers
const tricky = "var a = 4 / 2 / 1; var r = /\\/\\/[/]x/g; var t = `a ${a + `b${1}`} // not a comment`;\nvar s = '/* keep */'; var b = a\n++a\nvar o = { k: 1 } /* c */\nvar d = a - -1, e = a + +1; if (a) /x/.test('x'); var f = a++ + ++a;";
const box = {}; vm.runInNewContext(tricky, box); const want = JSON.stringify(box);
const m = minifyJs(tricky); const box2 = {}; vm.runInNewContext(m.text, box2);
out.tricky = { same: JSON.stringify(box2) === want, want, got: JSON.stringify(box2) };
out.css = minifyCss('a  :hover { color : red ; }\n/* x */ b > c , d { margin : 0 1px ; }');
const p1 = pruneParts(src, 'Film.start({scenes(T){ Film.text(\"x\") }})'), p2 = pruneParts(src, 'Film.bars([1], r, 1); Film.cursorPath(T, k)');
out.parts = { d1: p1.dropped, d2: p2.dropped };
out.prunedRuns = (() => { const box = {}; box.globalThis = box; vm.runInNewContext(p1.text, box); return typeof box.Film.text === 'function' && box.Film.bars === undefined; })();
console.log(JSON.stringify(out));
""" % (json.dumps(mod), json.dumps(str(SKILL / "runtime") + "/"), json.dumps(film))
        f = Path(tempfile.mkdtemp(prefix="st-min-")) / "t.mjs"
        f.write_text(code, encoding="utf-8")
        cp = subprocess.run([NODE, str(f)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=120)
        shutil.rmtree(str(f.parent), ignore_errors=True)
        self.assertEqual(cp.returncode, 0, cp.stderr[-3000:])
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        for name in ("film.js", "synth.js", "stage.js", "player/player.js", "player/boot.js"):
            self.assertTrue(r[name]["ok"], name)
            self.assertLess(r[name]["ratio"], 0.8, "%s barely shrank" % name)
        self.assertTrue(r["same"], "minified film.js computes something else")
        self.assertTrue(r["tricky"]["same"], r["tricky"])
        self.assertEqual(r["css"], "a :hover{color:red}b>c,d{margin:0 1px}")
        self.assertIn("charts", r["parts"]["d1"])
        self.assertIn("tutorial", r["parts"]["d1"])
        self.assertNotIn("charts", r["parts"]["d2"])
        self.assertNotIn("paths", r["parts"]["d2"], "charts draw lines with F.path: kept with them")
        self.assertNotIn("tutorial", r["parts"]["d2"])
        self.assertTrue(r["prunedRuns"])

    def test_synth_theory(self):
        synth = str(SKILL / "runtime" / "synth.js")
        r = run_node("""
require(%s); const S = globalThis.Synth;
const k = S.scale('D3', 'dorian');
const prog = S.progression('C3', 'major', ['I', 'vi', 'IV', 'V7', 'bVII']);
const moves = prog.slice(1).map((c, i) => c.reduce((s, n) => s + Math.min(...prog[i].map(p => Math.abs(p - n))), 0));
const g = S.grid({ bpm: 120, swing: 0.5 });
console.log(JSON.stringify({
  midi: [S.midi('A4'), S.midi('C#4'), S.midi('Eb3'), S.midi('C')], hz: Math.round(S.hz('A4')),
  names: [S.noteName(61), S.noteName(61, true)],
  dorian: k.notes(1), deg: [k.degree(-1), k.degree(7)], chord: S.chord('Dm7', 3), slash: S.chord('C/E', 3),
  prog: prog, maxMove: Math.max(...moves),
  grid: [g.t(1), g.t(0, 2), g.step(1, 4), g.step(2, 4)],
}));
""" % json.dumps(synth))
        self.assertEqual(r["midi"], [69, 61, 51, 60])
        self.assertEqual(r["hz"], 440)
        self.assertEqual(r["names"], ["C#4", "Db4"])
        self.assertEqual(r["dorian"], [50, 52, 53, 55, 57, 59, 60, 62])
        self.assertEqual(r["deg"], [48, 62])
        self.assertEqual(r["chord"], [50, 53, 57, 60])
        self.assertEqual(r["slash"], [40, 48, 52, 55])
        self.assertEqual(len(r["prog"]), 5)
        self.assertEqual(sorted(x % 12 for x in r["prog"][4]), sorted([10, 2, 5]))   # bVII = Bb major
        self.assertLessEqual(r["maxMove"], 8, "voice leading should keep chord moves small")
        self.assertEqual(r["grid"][:2], [2.0, 1.0])
        self.assertAlmostEqual(r["grid"][2], 0.125 + 0.5 * 0.125 * 0.5)    # swung 16th
        self.assertAlmostEqual(r["grid"][3], 0.25)


# --------------------------------------------------------------------------- score seeking (browser)

SEEK_DRIVER = r"""
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const SKILL = process.argv[2];
const { launchBrowser } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'chrome.mjs')).href);
const { browser } = await launchBrowser({ gpu: 'auto', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
try {
  const page = await (await browser.newContext()).newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e.message || e)));
  await page.setContent('<html><body></body></html>');
  await page.addScriptTag({ content: fs.readFileSync(path.join(SKILL, 'runtime', 'synth.js'), 'utf8') });
  const r = await page.evaluate(async () => {
    const sr = 48000;
    const render = async (fn, from, len) => {
      const ctx = new OfflineAudioContext(2, Math.round(len * sr), sr);
      await fn(ctx, ctx.destination, { from, to: from + len, lead: 0 });
      return ctx.startRendering();
    };
    // level of x over [a, b) seconds and of the difference to y (y starts `off` seconds later)
    const cmp = (X, Y, off, a, b) => {
      let e = 0, d = 0, n = 0;
      for (let c = 0; c < 2; c++) {
        const x = X.getChannelData(c), y = Y.getChannelData(c), o = Math.round(off * sr);
        for (let i = Math.round(a * sr); i < Math.round(b * sr); i++) { e += x[i + o] ** 2; d += (x[i + o] - y[i]) ** 2; n++; }
      }
      const db = (v) => (v > 0 ? 20 * Math.log10(Math.sqrt(v / n)) : -200);
      return { ref: +db(e).toFixed(1), diff: +db(d).toFixed(1) };
    };
    const peakIn = (B, a, b) => { let p = 0; for (let c = 0; c < 2; c++) { const x = B.getChannelData(c); for (let i = Math.round(a * sr); i < Math.round(b * sr); i++) p = Math.max(p, Math.abs(x[i])); } return p; };
    const out = {};
    // 1. every sustained sound resumes where a render from 0 has it (after reverb/compressors settle)
    const cases = {
      pad: (m) => m.pad('Dm7', 1.37, 7, { vel: 0.6 }),
      bass: (m) => m.bass('A1', 1.777, 5),
      lead: (m) => m.lead('E5', 2.6, 6.5),
      riser: (m) => m.riser(6, { dur: 4 }),
      duckFadeSweep: (m) => { m.pad('C3', 0, 9); m.duck('music', 3.3, { hold: 0.3, release: 1 }); m.fade('music', 2, 6, -20); m.sweep('music', 2, 7, 300, 8000); m.end(8, { fade: 4 }); },
      mix: (m) => { m.pad('Fmaj7', 0.5, 7); m.bass('F2', 0.5, 7); m.whoosh(3.3, { dur: 1.2 }); m.glitch(2.8, { dur: 0.5 }); m.click(2.0); m.click(4.5); m.arp(['F4', 'A4', 'C5'], 0.5, 7, { rate: 0.25, inst: 'pluck' }); },
    };
    const FROM = 3.0;
    for (const [name, fn] of Object.entries(cases)) {
      const score = Synth.score(fn, { seed: 4 });
      const full = await render(score, 0, 9), part = await render(score, FROM, 6);
      out[name] = { settle: cmp(full, part, FROM, 0.02, 0.5), after: cmp(full, part, FROM, 3.0, 5.5) };
    }
    // 2. a short sound that started before the seek is not played again; one after it plays once
    {
      const score = Synth.score((m) => { m.click(FROM - 0.1, { vel: 1 }); m.click(FROM + 0.2, { vel: 1 }); }, { seed: 2, reverb: { wet: 0 } });
      const part = await render(score, FROM, 1);
      out.noDouble = { before: peakIn(part, 0, 0.15), after: peakIn(part, 0.19, 0.24) };
    }
    // 3. realtime: start playing in the middle of a pad and listen with an AnalyserNode: the pad is
    //    heard at once at the level a render from 0 has there (it does not restart or fade in)
    {
      const score = Synth.score((m) => { m.pad('Dm7', 0, 12, { vel: 0.6 }); }, { seed: 5 });
      const full = await render(score, 0, 6);
      const ctx = new AudioContext({ sampleRate: sr });
      const an = ctx.createAnalyser(); an.fftSize = 4096; an.connect(ctx.destination);
      const pb = Synth.play(score, { from: 4.0, ctx, dest: an });
      await pb.ready;
      const t0 = ctx.currentTime, buf = new Float32Array(an.fftSize), got = [];
      while (ctx.currentTime - t0 < 0.8) {
        await new Promise((res) => setTimeout(res, 50));
        an.getFloatTimeDomainData(buf);
        let s = 0; for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
        got.push([+(ctx.currentTime - t0).toFixed(3), 20 * Math.log10(Math.sqrt(s / buf.length) + 1e-12)]);
      }
      pb.stop();
      await ctx.close();
      let s = 0, n = 0;
      for (let c = 0; c < 2; c++) { const x = full.getChannelData(c); for (let i = Math.round(4.2 * sr); i < Math.round(4.8 * sr); i++) { s += x[i] * x[i]; n++; } }
      out.realtime = { levels: got, refDb: 20 * Math.log10(Math.sqrt(s / n)) };
    }
    return out;
  });
  r.errors = errors;
  console.log(JSON.stringify(r));
} finally { await browser.close(); }
"""


@unittest.skipIf(FAST or not NODE, "--fast: no browser")
class TestScoreSeek(unittest.TestCase):
    """A Synth score rendered from any time equals that stretch of a render from 0."""

    @classmethod
    def setUpClass(cls):
        d = Path(tempfile.mkdtemp(prefix="st-seek-"))
        (d / "drv.mjs").write_text(SEEK_DRIVER, encoding="utf-8")
        cp = subprocess.run([NODE, str(d / "drv.mjs"), str(SKILL)], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace", timeout=240)
        shutil.rmtree(str(d), ignore_errors=True)
        assert cp.returncode == 0, cp.stderr[-3000:]
        cls.r = json.loads(cp.stdout.strip().splitlines()[-1])

    def test_sustained_sounds_resume_exactly(self):
        for name in ("pad", "bass", "lead", "riser", "duckFadeSweep", "mix"):
            a = self.r[name]["after"]
            self.assertLess(a["diff"], a["ref"] - 40, "%s after a seek differs from the render from 0: %s" % (name, a))
        # right at the seek point the pad is already at its level (no fade-in from silence, no gap)
        s = self.r["pad"]["settle"]
        self.assertLess(s["diff"], s["ref"] - 6, s)

    def test_short_sounds_not_repeated(self):
        nd = self.r["noDouble"]
        self.assertLess(nd["before"], 1e-3, "a click from before the seek was played again")
        self.assertGreater(nd["after"], 0.05, "a click after the seek is missing")

    def test_realtime_seek_into_pad(self):
        rt = self.r["realtime"]
        late = [db for t, db in rt["levels"] if t >= 0.25]
        self.assertTrue(late, rt)
        # the analyser (mono mix of both channels' samples) sees the pad at the render-from-0 level
        self.assertLess(abs(sorted(late)[len(late) // 2] - rt["refDb"]), 4.0, rt)
        # and at once: already within 6 dB of it in the first reading after the start
        first = [db for t, db in rt["levels"] if t >= 0.1][0]
        self.assertGreater(first, rt["refDb"] - 6, rt)

    def test_no_page_errors(self):
        self.assertEqual(self.r["errors"], [])


# --------------------------------------------------------------------------- series pattern

@unittest.skipIf(FAST, "--fast: no browser")
class TestSeries(unittest.TestCase):
    """showtime new series + series check/sync/add; episodes render with the shared kit."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-series-"))
        cls.dir = cls.tmp / "howto"
        showtime("new", "series", cls.dir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def test_a_check_sync_add(self):
        d = self.dir
        self.assertEqual(showtime("series", "check", d, check=False).returncode, 0)
        kit = d / "kit.js"
        kit.write_text(kit.read_text(encoding="utf-8").replace("Small steps, every day.", "One card at a time."), encoding="utf-8")
        cp = showtime("series", "check", d, "--json", check=False)
        self.assertEqual(cp.returncode, 1, "an edited kit must make check fail until synced")
        self.assertEqual(json.loads(cp.stdout)["episodes"][0]["kit"], "stale")
        cp = showtime("series", "sync", d, "--json")
        self.assertTrue(json.loads(cp.stdout)["episodes"][0]["changed"])
        self.assertEqual(showtime("series", "check", d, check=False).returncode, 0)
        self.assertIn("One card at a time.", (d / "episode-01" / "kit.js").read_text(encoding="utf-8"))
        rep = json.loads(showtime("series", "add", d, "--title", "Move cards", "--json").stdout)
        ep2 = Path(rep["episode"])
        self.assertEqual(ep2.name, "episode-02")
        for name in ("showtime.json", "index.html", "episode.js", "kit.js"):
            self.assertTrue((ep2 / name).is_file(), name)
        self.assertIn("episode-02", json.loads((d / "series.json").read_text(encoding="utf-8"))["episodes"])
        cfg = json.loads((ep2 / "showtime.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["title"], "02 · Move cards")
        self.assertEqual(json.loads(showtime("series", "list", d, "--json").stdout)["ok"], True)

    def test_b_episodes_render(self):
        # every project of the series draws with the kit without page errors
        for proj, times in ((self.dir / "episode-01", "2,11,16.8,31"), (self.dir, "4.5"), (self.dir / "episode-02", "2,7")):
            if not proj.exists():
                continue
            out = self.tmp / ("snap-" + proj.name)
            cp = showtime("snap", proj, "--at", times, "-o", out, "--width", 960, timeout=300)
            self.assertNotIn("error", cp.stderr.lower(), "%s: %s" % (proj.name, cp.stderr[-1500:]))
            pngs = sorted(out.glob("*.png"))
            self.assertEqual(len(pngs), len(times.split(",")), "%s: %s" % (proj.name, cp.stdout[-500:]))
            for p in pngs:
                self.assertGreater(p.stat().st_size, 15000, "%s looks blank" % p)


# --------------------------------------------------------------------------- full renders

@unittest.skipIf(FAST, "--fast: no browser renders")
class TestTemplatesRender(unittest.TestCase):
    """Render both templates at 1280x720 through the real CLI."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-film-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def _project(self, template):
        d = self.tmp / template
        if not d.exists():
            showtime("new", template, d, "--width", 1280, "--height", 720)
        return d

    def _render(self, template, duration):
        from st import ff  # noqa: WPS433 (import after sys.path setup)
        d = self._project(template)
        out = self.tmp / ("%s.mp4" % template)
        cp = showtime("render", d, "-o", out, "--preview", "--json", "--poster", "none", timeout=400)
        rep = last_json(cp.stdout)
        self.assertTrue(rep.get("ok"), rep)
        self.assertEqual((rep["width"], rep["height"]), (1280, 720))
        self.assertEqual(rep["frames"], int(round(duration * 30)))
        self.assertEqual(rep.get("warnings"), [], rep.get("warnings"))
        self.assertIn("score", (rep.get("audio") or {}).get("sources", []))
        self.assertAlmostEqual(rep["audio"]["lufs"], -14.0, delta=1.0)
        pr = ff.probe(out)
        self.assertEqual((pr["width"], pr["height"], pr["vcodec"]), (1280, 720, "h264"))
        self.assertEqual(pr["nb_frames"], int(round(duration * 30)))
        self.assertAlmostEqual(pr["duration"], duration, delta=0.05)
        self.assertTrue(pr["has_audio"], "rendered film has no audio stream")
        self.assertEqual(pr["color_primaries"], "bt709")
        # frames are not blank: luma range at a few times
        for t in (1.5, duration * 0.55, duration - 1.0):
            cp2 = ff.run_ffmpeg(["-ss", "%.2f" % t, "-i", str(out), "-frames:v", "1", "-vf", "signalstats,metadata=print",
                                 "-f", "null", "-"], loglevel="info", overwrite=False)
            txt = cp2.stderr or ""
            ymin = float(re.search(r"YMIN=(\d+)", txt).group(1))
            ymax = float(re.search(r"YMAX=(\d+)", txt).group(1))
            self.assertGreater(ymax - ymin, 60, "frame at %.2fs of %s looks blank" % (t, template))
        return d, rep

    def _score(self, d, sections=None):
        wav = self.tmp / ("%s-score.wav" % d.name)
        args = ["score", d, "-o", wav, "--json"] + (["--sections", sections] if sections else [])
        rep = last_json(showtime(*args, timeout=200).stdout)
        self.assertTrue(Path(rep["output"]).is_file())
        self.assertIsNotNone(rep["lufs"], "score is silent")
        self.assertGreater(rep["lufs"], -24, "raw score too quiet: %s LUFS" % rep["lufs"])
        self.assertLess(rep["lufs"], -10, "raw score too loud: %s LUFS" % rep["lufs"])
        self.assertLess(rep["sample_peak_db"], 0.0)
        self.assertLess(rep["first_sound"], 0.1, "music should start on frame 1")
        for s in rep["sections"]:
            self.assertGreater(s["rms_db"], -45, "section %s is nearly silent" % s)
        self.assertEqual(rep["warnings"], [])
        return rep

    def test_film_template(self):
        d, _ = self._render("film", 12.0)
        rep = self._score(d)
        self.assertEqual([s["label"] for s in rep["sections"]], ["Title", "Metaphor", "Data", "End card"])
        # the arc: the data section (drums enter) is louder than the title
        self.assertGreater(rep["sections"][2]["rms_db"], rep["sections"][0]["rms_db"] + 3)

    def test_tutorial_template_and_click_sync(self):
        d, _ = self._render("tutorial", 15.0)
        rep = self._score(d, "0,4.6,9.5,13.8")
        cues = (d / "cues.js").read_text(encoding="utf-8")
        click1 = float(re.search(r"click1:\s*([0-9.]+)", cues).group(1))
        click2 = float(re.search(r"click2:\s*([0-9.]+)", cues).group(1))
        sr, ch, x = read_wav(rep["output"])
        for cue in (click1, click2):
            a, b = int((cue - 0.03) * sr), int((cue + 0.03) * sr)
            # first-difference (high-pass) of the left channel emphasises the click over the bed
            d1 = [abs(x[(i + 1) * ch] - x[i * ch]) for i in range(a, b)]
            peak = max(d1)
            onset = next(i for i, v in enumerate(d1) if v > peak * 0.5)
            err_ms = ((a + onset) / sr - cue) * 1000
            self.assertLess(abs(err_ms), 3.0, "click at %.2fs lands %.1f ms off" % (cue, err_ms))


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)

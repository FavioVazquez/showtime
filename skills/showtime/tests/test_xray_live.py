#!/usr/bin/env python3
"""The X-ray live page: `showtime export html <xray project> --interactive` (scripts/lib/export/xray.mjs,
runtime/xray-live/pre.js, live.js, live.css).

  * static: the live page's parts exist; pre.js runs the stage in render mode and answers the page's fetch() from the
    packed data; live.js reaches no network and no wall-clock randomness; the sync marker is hidden; export.mjs sends
    an X-ray project's --interactive to the live page and a living diagram's to its figure
  * CLI: the template sample exports one offline file (a Content-Security-Policy, the clip packed once, the second
    copy a canvas mirror, no file left to fetch), under 16 MB, named <slug>-live.html; the diagram layout too
  * browser: the page starts, jumping to event i lands on its frame with the kit's strike at its peak (cur = i,
    s = 1) for several events, the marker is not shown, 0.25x plays around the event and ends on it, the theme
    switches on the same frame; no console error, no request off the file
  * touch: #hit4 opens on the 4th event; the typewriter's pads are its keys (a letter plays the next one, the
    plain letter is a pad, Shift+S is 0.25x); dragging the picture scrubs; a click on it plays the next event; a
    link names the hit; framed with #embed, the page reports its height to the host; --prompt travels

Stdlib only. usage: python tests/test_xray_live.py [--fast] [-v]
  --fast   skip the browser check
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
LIVE = SKILL / "runtime" / "xray-live"
sys.path.insert(0, str(SKILL / "lib"))

from st import platform as plat  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
NODE = shutil.which("node", path=ENV.get("PATH"))
# the browser the drivers' openBrowser would start (stagehost: $SHOWTIME_CHROME, a system Chrome, Playwright's)
BROWSER = plat.find_chrome(ENV.get("PLAYWRIGHT_BROWSERS_PATH"))
NO_BROWSER = "--fast: no browser" if FAST else ("needs node" if not NODE else ("needs Chromium (showtime setup)"
                                                                               if not BROWSER else ""))
TMP = Path(tempfile.mkdtemp(prefix="st-xray-live-"))


def showtime(*args, check=True, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


_SAMPLE = {}


def sample(layout=None):
    """A fresh `showtime new xray` project (the typewriter sample), exported once as a live page."""
    key = layout or "through"
    if key not in _SAMPLE:
        proj = TMP / ("proj-" + key)
        showtime("new", "xray", proj, *(["--layout", layout] if layout else []))
        out = TMP / ("live-" + key + ".html")
        cp = showtime("export", "html", proj, "--interactive", "-o", out, "--json")
        _SAMPLE[key] = (proj, out, json.loads(cp.stdout))
    return _SAMPLE[key]


class TestStatic(unittest.TestCase):
    def test_parts_exist(self):
        for n in ("pre.js", "live.js", "live.css", "embed.js"):
            self.assertTrue((LIVE / n).is_file(), n)
        self.assertTrue((SKILL / "scripts" / "lib" / "export" / "xray.mjs").is_file())

    def test_pre_runs_the_stage_in_render_mode_offline(self):
        pre = (LIVE / "pre.js").read_text(encoding="utf-8")
        self.assertIn("__ST_RENDER__", pre, "the film's own clock: render mode, the same frames as the MP4")
        self.assertRegex(pre, r"W\.fetch\s*=\s*function", "the page's fetch() answers from the packed data")
        self.assertIn("status: 404", pre, "a file that was not packed is a 404, never a network request")
        self.assertIn("__XL_REAL__", pre, "the controls keep the real clocks")

    def test_live_reaches_no_network_and_no_wall_clock(self):
        js = (LIVE / "live.js").read_text(encoding="utf-8")
        code = re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", js)
        for bad in ("XMLHttpRequest", "fetch(", "sendBeacon", "WebSocket", "Math.random", "Date.now", "import("):
            self.assertNotIn(bad, code, bad)
        self.assertIn("X.mech.draw = function", code, "the mechanism's own drawing, wrapped, never redrawn here")
        self.assertIn("ST.seek(", code, "frames are drawn by the stage, on the scrubbed time")

    def test_links_are_plain_anchors(self):
        pre = (LIVE / "pre.js").read_text(encoding="utf-8")
        self.assertIn("hit-?(\\d+)", pre, "#hit4: a plain anchor, the form framed hosts pass on")
        self.assertIn("k === 'event'", pre, "the older #event=4 still opens")
        js = (LIVE / "live.js").read_text(encoding="utf-8")
        self.assertNotRegex(re.sub(r"/\*[\s\S]*?\*/|//[^\n]*", "", js), r"'#t='|'&theme='", "links are written as plain tokens")

    def test_embed_element(self):
        js = (LIVE / "embed.js").read_text(encoding="utf-8")
        self.assertIn("customElements.define('showtime-xray'", js)
        self.assertIn("'#embed'", js, "the frame opens on the page's embed layout")
        self.assertIn("showtime-xray:size", js)

    def test_marker_hidden(self):
        css = (LIVE / "live.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"#xmark\s*\{\s*display:\s*none\s*!important", "the sync marker is for verify, not viewers")

    def test_export_routes_xray_projects(self):
        src = (SKILL / "scripts" / "export.mjs").read_text(encoding="utf-8")
        self.assertIn("isXrayProject(proj.dir, cfg)", src)
        self.assertRegex(src, r"if \(xrayLive\) return exportXrayLive\(")
        self.assertLess(src.index("if (xrayLive) return exportXrayLive("), src.index("if (a.interactive) return exportFigure("))


class TestCli(unittest.TestCase):
    def test_sample_exports_one_offline_file(self):
        proj, out, rep = sample()
        self.assertTrue(out.is_file())
        self.assertEqual(rep["kind"], "xray-live")
        self.assertTrue(rep["tracked"], "the sample clip is tracked: see-through and split")
        self.assertLess(rep["bytes"], 16 * 1000 * 1000)
        html = out.read_text(encoding="utf-8")
        self.assertRegex(html, r'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'')
        self.assertEqual(html.count("data-xl-media="), 1, "the clip is packed once")
        self.assertIn("data-xl-mirror=", html, "the radiograph copy of the clip is a canvas mirror, never a second file")
        self.assertIn('id="xmark"', html, "the marker element stays (xray.js sets it); live.css hides it")
        self.assertNotRegex(html, r'(?<![\w-])src="(?!data:|blob:)[^"]+"', "no file left to fetch")
        cfg = json.loads(re.search(r'<script type="application/json" id="xl-cfg">(.*?)</script>', html, re.S).group(1))
        self.assertIn("xray.json", cfg["data"])
        self.assertIn("xray", json.loads(cfg["data"]["showtime.json"]), "the page's own settings travel (skip, text, credit)")
        self.assertNotIn("audio", json.loads(cfg["data"]["showtime.json"]), "no local paths")

    def test_default_name(self):
        proj, _, _ = sample()
        jobs = TMP / "jobs"
        jobs.mkdir(exist_ok=True)
        cp = showtime("export", "html", proj, "--interactive", "--out-dir", jobs, "--json")
        self.assertTrue(json.loads(cp.stdout)["output"].endswith("-live.html"))

    def test_the_pages_own_font_faces_are_packed(self):
        # #71: a project's own @font-face in the page's <style> (url("fonts/...")) is packed like the theme fonts; the
        # page's policy allows only data: fonts, so a font left as a file never loads. The living diagram's figure too.
        face = b"wOF2" + bytes(range(60))                            # synthetic bytes: packing never parses a font
        b64 = __import__("base64").b64encode(face).decode()
        for tpl, page in (("xray", "index.html"), ("diagram", "figure.html")):
            proj = TMP / ("ownfont-" + tpl)
            showtime("new", tpl, proj)
            (proj / "fonts").mkdir()
            (proj / "fonts" / "own face.woff2").write_bytes(face)
            html = (proj / page).read_text(encoding="utf-8")
            style = ('<style media="all">@font-face { font-family: "Own Face"; src: url("fonts/own%20face.woff2") '
                     'format("woff2"); } h1, .brand { font-family: "Own Face", sans-serif; }</style>\n</head>')
            (proj / page).write_text(html.replace("</head>", style, 1), encoding="utf-8")
            out = TMP / ("ownfont-" + tpl + ".html")
            showtime("export", "html", proj, "--interactive", "-o", out, "--json")
            got = out.read_text(encoding="utf-8")
            self.assertIn("url(data:font/woff2;base64,%s)" % b64, got, tpl)
            self.assertNotIn("own%20face.woff2", got, tpl)
            self.assertIn('<style media="all">', got, "the block keeps its attributes")
            # a page font that is not there stops the export with its name, instead of a page that falls back
            (proj / "fonts" / "own face.woff2").unlink()
            cp = showtime("export", "html", proj, "--interactive", "-o", TMP / ("ownfont-miss-" + tpl + ".html"), check=False)
            self.assertNotEqual(cp.returncode, 0, tpl)
            self.assertIn("own face.woff2", unquote(cp.stdout + cp.stderr), tpl)

    def test_an_inline_script_is_never_rewritten(self):
        # #71 review: the page's <style> packing must not reach into an inline <script> whose text holds "<style>",
        # "@font-face" or "url(": the script stays byte for byte (its url names no file, so a rewrite would also fail)
        script = ('<script>window.__css = \'<style>@font-face { font-family: "Code Face"; src: url("fonts/none.woff2"); }'
                  '</style>\'; window.__u = "url(x)";</script>')
        for tpl, page in (("xray", "index.html"), ("diagram", "figure.html")):
            proj = TMP / ("inlinescript-" + tpl)
            showtime("new", tpl, proj)
            html = (proj / page).read_text(encoding="utf-8")
            (proj / page).write_text(html.replace("</body>", script + "\n</body>", 1), encoding="utf-8")
            out = TMP / ("inlinescript-" + tpl + ".html")
            showtime("export", "html", proj, "--interactive", "-o", out, "--json")
            self.assertIn(script, out.read_text(encoding="utf-8"), tpl)

    def test_a_page_style_cannot_reach_outside_the_project(self):
        # #71 review: a url() in the page's own <style> is read only inside the project; an encoded ".." that climbs
        # out stops the export by its name, and a plain "../.." stays at the project's root (no such file there)
        face = b"wOF2" + bytes(range(60, 120))
        b64 = __import__("base64").b64encode(face).decode()
        for tpl, page in (("xray", "index.html"), ("diagram", "figure.html")):
            proj = TMP / "climb" / tpl / "proj"
            showtime("new", tpl, proj)
            (proj.parent / "outside.woff2").write_bytes(face)
            (proj.parent.parent / "outside.woff2").write_bytes(face)
            html = (proj / page).read_text(encoding="utf-8")
            for i, url in enumerate(("../outside.woff2", "%2e%2e/outside.woff2", "..%2foutside.woff2",
                                     "/_st/%2e%2e/%2e%2e/outside.woff2")):
                style = '<style>@font-face { font-family: "Far"; src: url("%s"); }</style>\n</head>' % url
                (proj / page).write_text(html.replace("</head>", style, 1), encoding="utf-8")
                out = TMP / "climb" / ("%s-%d.html" % (tpl, i))
                cp = showtime("export", "html", proj, "--interactive", "-o", out, check=False)
                where = (tpl, url, (cp.stdout + cp.stderr)[-600:])
                self.assertNotEqual(cp.returncode, 0, where)
                self.assertIn("outside.woff2", unquote(cp.stdout + cp.stderr), where)
                self.assertFalse(out.exists() and b64 in out.read_text(encoding="utf-8"), where)

    def test_from_inside_a_job_it_writes_into_the_job(self):
        # #72: run from a job folder (or on a project inside one), the live page lands in the job, noted in job.json,
        # never in a new showtime-out/ folder nested inside it
        base = TMP / "jobs72"
        base.mkdir(exist_ok=True)
        job = Path(json.loads(showtime("job", "init", "live72", "--base", base, "--no-check", "--json").stdout)["job"])
        showtime("new", "xray", job / "project")
        for cwd, arg in ((job, "project"), (TMP, str(job / "project"))):
            cp = subprocess.run([sys.executable, str(LAUNCHER), "export", "html", arg, "--interactive", "--json"], env=ENV,
                                cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                                errors="replace", timeout=300)
            self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
            rep = json.loads(cp.stdout)
            self.assertEqual(Path(rep["output"]).parent.resolve(), job.resolve(), (cwd, rep["output"]))
            self.assertEqual(Path(rep["job"]).resolve(), job.resolve())
        self.assertFalse((job / "showtime-out").exists(), "no nested showtime-out folder")
        self.assertFalse((TMP / "showtime-out").exists(), "the project's job wins over the folder it was run from")
        hist = [h["event"] for h in json.loads((job / "job.json").read_text(encoding="utf-8"))["history"]]
        self.assertEqual(len([h for h in hist if h.startswith("export html --interactive ") and "live" in h]), 2, hist)

    def test_from_a_job_only_its_own_project_goes_in(self):
        # #72 review: the folder the command runs from picks the job only for that job's own project (kept elsewhere
        # and named by job.json "project"); another project exported from inside a job goes where it always did
        base = TMP / "jobs72b"
        base.mkdir(exist_ok=True)
        own, other = TMP / "own72", TMP / "other72"
        showtime("new", "xray", own)
        showtime("new", "xray", other)
        job = Path(json.loads(showtime("job", "init", "live72b", "--base", base, "--project", own, "--no-check",
                                       "--json").stdout)["job"])

        def export(arg):
            cp = subprocess.run([sys.executable, str(LAUNCHER), "export", "html", str(arg), "--interactive", "--json"],
                                env=ENV, cwd=str(job), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                                errors="replace", timeout=300)
            self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
            return json.loads(cp.stdout)

        rep = export(own)
        self.assertEqual(Path(rep["output"]).parent.resolve(), job.resolve(), rep["output"])
        self.assertEqual(Path(rep["job"]).resolve(), job.resolve())
        rep = export(other)
        out = Path(rep["output"]).resolve()
        self.assertNotEqual(out.parent, job.resolve(), "another project's page is not written into this job")
        self.assertEqual(out.parent.parent.name, "showtime-out", out)
        self.assertFalse(rep.get("job"), rep)
        hist = [h["event"] for h in json.loads((job / "job.json").read_text(encoding="utf-8"))["history"]]
        self.assertEqual(len([h for h in hist if h.startswith("export html --interactive ")]), 1, hist)

    def test_from_a_job_its_project_written_another_way_goes_in(self):
        # #72 on Windows: job.json holds the project's long path while the argument can be its 8.3 short form (a temp
        # folder under a short home name) or another letter case; it is still the job's own project, so the page goes in
        base = TMP / "jobs72c"
        base.mkdir(exist_ok=True)
        own = TMP / "Own72c"
        showtime("new", "xray", own)
        variant = own.with_name(own.name.lower())
        if not variant.exists():
            self.skipTest("a case-sensitive file system: no other spelling of the same folder")
        job = Path(json.loads(showtime("job", "init", "live72c", "--base", base, "--project", own, "--no-check",
                                       "--json").stdout)["job"])
        cp = subprocess.run([sys.executable, str(LAUNCHER), "export", "html", str(variant), "--interactive", "--json"],
                            env=ENV, cwd=str(job), stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                            errors="replace", timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        rep = json.loads(cp.stdout)
        self.assertEqual(Path(rep["output"]).parent.resolve(), job.resolve(), rep["output"])
        self.assertEqual(Path(rep["job"]).resolve(), job.resolve())

    def test_diagram_layout(self):
        _, out, rep = sample("diagram")
        self.assertEqual(rep["layout"], "diagram")
        self.assertIn("XRAY_DIAGRAM", out.read_text(encoding="utf-8"))


DRIVER = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, FILE] = process.argv.slice(2);
const { openBrowser } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'stagehost.mjs')).href);
const { browser } = await openBrowser({ headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
const out = { logs: [], net: [], jumps: [] };
try {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const pg = await ctx.newPage();
  pg.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') out.logs.push(m.text()); });
  pg.on('pageerror', (e) => out.logs.push(String(e.message || e)));
  pg.on('request', (r) => { if (!/^(file|blob|data):/.test(r.url())) out.net.push(r.url()); });
  await pg.goto(pathToFileURL(FILE).href);
  const st = await pg.evaluate('xrayLive.ready');
  out.start = { frame: st.frame, kept: st.kept, parts: st.parts };
  for (const i of [st.kept[0], st.kept[Math.floor(st.kept.length / 2)], st.kept[st.kept.length - 1]]) {
    const s = await pg.evaluate(`xrayLive.jump(${i})`);
    out.jumps.push({ i, frame: s.frame, evframe: s.events.find((e) => e.i === i).frame, cur: s.kit && s.kit.cur, s: s.kit && s.kit.s });
  }
  // what a viewer does: a key, a click on a tick, the pointer on a part label, space
  await pg.evaluate(`xrayLive.jump(${st.kept[0]})`);
  const wantKey = await pg.evaluate(`xrayLive.state().events.find((e) => e.i === ${st.kept[1]}).frame`);
  await pg.keyboard.press('ArrowRight');
  // wait for the key's jump itself (the start frame already satisfied "frame > 0", so a slow runner was read too early)
  await pg.waitForFunction((w) => !window.xrayLive.state().playing && window.xrayLive.state().frame === w, wantKey, { polling: 100, timeout: 10000 }).catch(() => {});
  out.key = await pg.evaluate(`({ frame: xrayLive.state().frame, want: ${wantKey}, playing: xrayLive.state().playing, focus: document.activeElement && (document.activeElement.className || document.activeElement.tagName) })`);
  const nth = Math.floor(st.kept.length / 2);
  await pg.locator('.xl-tick:not(.is-skip)').nth(nth).click();
  // wait for the jump itself (a slow runner seeks for longer than a fixed pause); if it never lands, say what the page shows
  const wantTick = await pg.evaluate(`xrayLive.state().events.find((e) => e.i === ${st.kept[nth]}).frame`);
  await pg.waitForFunction((w) => !window.xrayLive.state().playing && window.xrayLive.state().frame === w, wantTick, { polling: 100, timeout: 10000 }).catch(() => {});
  out.tick = await pg.evaluate(`({ frame: xrayLive.state().frame, want: ${wantTick}, playing: xrayLive.state().playing, focus: document.activeElement && (document.activeElement.className || document.activeElement.tagName) })`);
  const lab = await pg.evaluate('xrayLive.seek(2.5).then((s) => s.labels[0] || null)');
  if (lab) {
    const box = await pg.evaluate(() => { const r = document.querySelector('.xl-scale').getBoundingClientRect(); return { x: r.left, y: r.top, k: r.width / document.getElementById('stage').offsetWidth }; });
    await pg.mouse.move(box.x + (lab.x + lab.w / 2) * box.k, box.y + (lab.y + lab.h / 2) * box.k);
    await pg.waitForFunction((w) => window.xrayLive.state().hot === w, lab.name.toLowerCase(), { polling: 100, timeout: 10000 }).catch(() => {});
    out.hover = { want: lab.name.toLowerCase(), hot: await pg.evaluate('xrayLive.state().hot') };
    await pg.mouse.move(1, 1);
  }
  await pg.locator('.xl-play').focus(); await pg.locator('.xl-play').blur();
  await pg.keyboard.press(' ');
  await pg.waitForFunction(() => window.xrayLive.state().playing, null, { polling: 100, timeout: 10000 }).catch(() => {});
  out.spacePlays = await pg.evaluate('xrayLive.state().playing');
  await pg.evaluate('xrayLive.pause()');
  out.marker = await pg.evaluate("getComputedStyle(document.getElementById('xmark')).display");
  out.scrollW = await pg.evaluate('document.documentElement.scrollWidth');
  const mid = st.kept[Math.floor(st.kept.length / 2)];
  await pg.evaluate(`xrayLive.jump(${mid})`);
  out.slow = await pg.evaluate('xrayLive.slow().then(() => ({ rate: xrayLive.state().rate, slow: xrayLive.state().slow }))');
  // function predicates polled on a timer: the page's CSP has no eval, and the stage's render mode queues rAF
  await pg.waitForFunction(() => !window.xrayLive.state().slow && !window.xrayLive.state().playing, null, { timeout: 20000, polling: 100 });
  out.slowEnd = await pg.evaluate('xrayLive.state().frame');
  out.midFrame = await pg.evaluate(`xrayLive.state().events.find((e) => e.i === ${mid}).frame`);
  await pg.evaluate('xrayLive.theme("light")');
  await pg.waitForTimeout(300);
  await pg.waitForFunction(() => window.xrayLive && window.xrayLive.state().ready && window.xrayLive.state().theme === 'light', null, { timeout: 20000, polling: 100 });
  out.light = await pg.evaluate('({ frame: xrayLive.state().frame, theme: xrayLive.state().theme })');
} catch (e) { out.error = String(e && e.stack || e); }
await browser.close();
console.log(JSON.stringify(out));
"""


TOUCH = r"""
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, FILE, HOST] = process.argv.slice(2);
const { openBrowser } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'stagehost.mjs')).href);
const { browser } = await openBrowser({ headless: true, args: ['--autoplay-policy=no-user-gesture-required', '--allow-file-access-from-files'] });
const out = { logs: [] };
const until = (pg, fn, ms = 5000) => pg.waitForFunction(fn, null, { timeout: ms, polling: 30 }).then(() => true, () => false);
try {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
  const pg = await ctx.newPage();
  pg.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') out.logs.push(m.text()); });
  pg.on('pageerror', (e) => out.logs.push(String(e.message || e)));
  await pg.goto(pathToFileURL(FILE).href + '#hit4');
  const st = await pg.evaluate('xrayLive.ready');
  out.hit4 = { frame: st.frame, want: st.events.find((e) => e.i === st.kept[3]).frame };
  out.pads = st.pads;
  out.made = await pg.evaluate("[...document.querySelectorAll('.xl-made textarea')].map((t) => t.value)");
  const pad = st.pads.keys.find((k) => k.key.length === 1 && /[a-z]/.test(k.key));
  await pg.mouse.click(2, 2);
  await pg.keyboard.press(pad.key);
  out.keyStrike = await until(pg, () => window.xrayLive.state().strike);
  await until(pg, () => !window.xrayLive.state().strike && !window.xrayLive.state().playing, 10000);
  out.afterKey = await pg.evaluate('xrayLive.state().frame');
  out.padFrames = await pg.evaluate(`xrayLive.state().events.filter((e) => e.ch && e.ch.toLowerCase() === ${JSON.stringify(pad.key)}).map((e) => e.frame)`);
  const vb = await pg.locator('.xl-view').boundingBox();
  const f0 = await pg.evaluate('xrayLive.state().frame');
  await pg.mouse.move(vb.x + vb.width * 0.2, vb.y + vb.height * 0.5);
  await pg.mouse.down(); await pg.mouse.move(vb.x + vb.width * 0.5, vb.y + vb.height * 0.52, { steps: 8 }); await pg.mouse.up();
  await pg.waitForTimeout(500);
  out.drag = { f0, f1: await pg.evaluate('xrayLive.state().frame'), playing: await pg.evaluate('xrayLive.state().playing') };
  await pg.mouse.click(vb.x + 4, vb.y + vb.height - 4);
  out.clickStrike = await until(pg, () => window.xrayLive.state().strike);
  await until(pg, () => !window.xrayLive.state().strike && !window.xrayLive.state().playing, 10000);
  await pg.keyboard.press('Shift+S');
  out.shiftS = await until(pg, () => window.xrayLive.state().slow);
  await pg.evaluate('xrayLive.pause()');
  await pg.evaluate(`xrayLive.jump(${st.kept[2]})`);
  out.link = await pg.evaluate('xrayLive.link()');
  // framed with #embed: the host hears the page's height
  const host = await ctx.newPage();
  host.on('pageerror', (e) => out.logs.push('host: ' + String(e.message || e)));
  await host.goto(pathToFileURL(HOST).href);
  out.embedHeight = await host.waitForFunction(() => window.__h > 0 && window.__h, null, { timeout: 30000, polling: 100 }).then((h) => h.jsonValue(), () => 0);
} catch (e) { out.error = String(e && e.stack || e); }
await browser.close();
console.log(JSON.stringify(out));
"""


@unittest.skipIf(NO_BROWSER, NO_BROWSER)
class TestTouch(unittest.TestCase):
    def test_play_it(self):
        proj, _, _ = sample()
        out = TMP / "live-touch.html"
        rep = json.loads(showtime("export", "html", proj, "--interactive", "-o", out, "--json",
                                  "--prompt", "X-ray this clip of my typewriter.").stdout)
        self.assertEqual((rep.get("made") or {}).get("prompt"), "X-ray this clip of my typewriter.")
        host = TMP / "host.html"
        host.write_text('<!doctype html><meta charset="utf-8"><body style="margin:0;width:900px">'
                        '<iframe id="f" style="width:900px;height:400px;border:0" src="%s#embed_hit2"></iframe>'
                        '<script>addEventListener("message",function(e){if(e.data&&e.data.type==="showtime-xray:size")window.__h=e.data.height;});</script>'
                        % out.as_uri(), encoding="utf-8")
        drv = TMP / "touch.mjs"
        drv.write_text(TOUCH, encoding="utf-8")
        cp = subprocess.run([NODE, str(drv), str(SKILL), str(out), str(host)], env=ENV, cwd=str(TMP), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertNotIn("error", r, r.get("error"))
        self.assertEqual(r["logs"], [], "no console error")
        self.assertEqual(r["hit4"]["frame"], r["hit4"]["want"], "#hit4 opens on the 4th event's frame")
        self.assertEqual(r["pads"]["by"], "ch", "a typewriter's pads are its keys")
        self.assertEqual(r["pads"]["verb"], "Type on it")
        self.assertEqual(r["made"][0], "X-ray this clip of my typewriter.", "the line that made it is on the page")
        self.assertTrue(r["keyStrike"], "a plain letter plays that key's next keystroke")
        self.assertTrue(any(0 <= r["afterKey"] - f <= 10 for f in r["padFrames"]), "it rests just after that key's keystroke: %s" % r)
        self.assertNotEqual(r["drag"]["f0"], r["drag"]["f1"], "dragging the picture scrubs")
        self.assertFalse(r["drag"]["playing"])
        self.assertTrue(r["clickStrike"], "a click on the picture plays the next event")
        self.assertTrue(r["shiftS"], "Shift+S is 0.25x")
        self.assertTrue(r["link"].endswith("#hit3"), "a link names the hit: %s" % r["link"])
        self.assertGreater(r["embedHeight"], 200, "framed with #embed, the page reports its height")


EMBED = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, HOST, HOW] = process.argv.slice(2);
const { openBrowser } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'stagehost.mjs')).href);
const { browser } = await openBrowser({ headless: true, args: ['--allow-file-access-from-files'] });
const out = { logs: [] };
let server = null;
try {
  let url = pathToFileURL(HOST).href;
  if (HOW === 'http') {   // the host served over http from its own folder (127.0.0.1 only)
    const http = await import('node:http'), fs = await import('node:fs');
    server = http.createServer((q, s) => {
      const f = path.join(path.dirname(HOST), decodeURIComponent(new URL(q.url, 'http://x').pathname));
      fs.readFile(f, (err, b) => { if (err) { s.statusCode = 404; s.end(); return; }
        s.setHeader('content-type', f.endsWith('.js') ? 'text/javascript' : 'text/html; charset=utf-8'); s.end(b); });
    });
    await new Promise((r) => server.listen(0, '127.0.0.1', r));
    url = 'http://127.0.0.1:' + server.address().port + '/' + path.basename(HOST);
  }
  const ctx = await browser.newContext({ viewport: { width: 1000, height: 800 } });
  const pg = await ctx.newPage();
  pg.on('pageerror', (e) => out.logs.push(String(e.message || e)));
  await pg.goto(url);
  out.loaded = await pg.evaluate(() => [...document.querySelectorAll('showtime-xray')].map((el) => {
    const f = el.load(false);
    return f ? { src: f.getAttribute('src'), sandbox: f.getAttribute('sandbox'), h: f.style.height } : null;
  }));
  const h0 = out.loaded[0] && out.loaded[0].h;
  // the page in the sandboxed frame still tells the host its height
  out.resized = await pg.waitForFunction((h) => document.querySelector('showtime-xray iframe').style.height !== h, h0, { timeout: 30000, polling: 100 }).then(() => true, () => false);
  out.frames = await pg.evaluate(() => document.querySelectorAll('showtime-xray iframe').length);
} catch (e) { out.error = String(e && e.stack || e); }
await browser.close();
if (server) server.close();
console.log(JSON.stringify(out));
"""


COPY = r"""
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const [SKILL, HOST, GRANT] = process.argv.slice(2);
const { openBrowser } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'stagehost.mjs')).href);
const { browser } = await openBrowser({ headless: true });
const out = { logs: [] };
let server = null;
try {
  // the host served over http from its own folder (127.0.0.1 only), the way a site embeds the page
  const http = await import('node:http'), fs = await import('node:fs');
  server = http.createServer((q, s) => {
    const f = path.join(path.dirname(HOST), decodeURIComponent(new URL(q.url, 'http://x').pathname));
    fs.readFile(f, (err, b) => { if (err) { s.statusCode = 404; s.end(); return; }
      s.setHeader('content-type', f.endsWith('.js') ? 'text/javascript' : 'text/html; charset=utf-8'); s.end(b); });
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const ctx = await browser.newContext({ viewport: { width: 1000, height: 900 } });
  if (GRANT === 'grant') await ctx.grantPermissions(['clipboard-read', 'clipboard-write'], { origin });
  // a host that refuses the clipboard (a browser setting, a policy): writeText rejects, in every frame
  if (GRANT === 'refuse') await ctx.addInitScript(() => { Object.defineProperty(navigator, 'clipboard', { configurable: true,
    value: { writeText: () => Promise.reject(new DOMException('refused', 'NotAllowedError')) } }); });
  const pg = await ctx.newPage();
  pg.on('pageerror', (e) => out.logs.push(String(e.message || e)));
  await pg.goto(origin + '/' + path.basename(HOST));
  await pg.evaluate(() => document.querySelector('showtime-xray').load(false));
  const fr = await (await pg.waitForSelector('showtime-xray iframe')).contentFrame();
  await fr.waitForFunction(() => window.xrayLive && document.querySelector('.xl-embed'), null, { timeout: 30000, polling: 100 });
  out.sandbox = await pg.evaluate(() => document.querySelector('showtime-xray iframe').getAttribute('sandbox'));
  // real clicks in the frame (the clipboard needs the gesture): open the embed snippets, press the first Copy. The
  // page posts its height to the host as it starts and as the panel opens, and the host resizes the frame: a click
  // aimed while the frame moves on the host lands on nothing (the frame's own stability check cannot see that), so
  // each click waits for the page to be ready and for the frame's place on the host to hold still for 250 ms
  await fr.evaluate(() => Promise.race([window.xrayLive.ready,
    new Promise((ok, no) => setTimeout(() => no(new Error('the page did not start in 30 s')), 30000))]));
  // each settle forgets the last place first, so it always needs two equal reads 250 ms apart
  const settle = async () => { await pg.evaluate(() => { window.__frameAt = null; });
    await pg.waitForFunction(() => { const r = document.querySelector('showtime-xray iframe').getBoundingClientRect();
      const k = [r.y, r.height, scrollY].join(); const same = k === window.__frameAt; window.__frameAt = k; return same; },
      null, { timeout: 10000, polling: 250 }); };
  // say which way a step failed: the panel toggled closed, emptied, or the frame hidden or resized on the host
  const failed = async (e) => {
    const st = await fr.evaluate(() => ({ expanded: document.querySelector('.xl-embed').getAttribute('aria-expanded'),
      hidden: document.querySelector('.xl-share').hidden, what: document.querySelector('.xl-share').getAttribute('data-what'),
      copies: document.querySelectorAll('.xl-copy').length, inPanel: document.querySelectorAll('.xl-share .xl-copy').length,
      ready: !!(window.xrayLive && document.querySelector('.xl-veil') && document.querySelector('.xl-veil').hidden) })).catch((x) => String(x));
    const host = await pg.evaluate(() => { const f = document.querySelector('showtime-xray iframe'), r = f.getBoundingClientRect(), c = getComputedStyle(f);
      return [Math.round(r.y), Math.round(r.height), c.display, c.visibility, scrollY]; }).catch((x) => String(x));
    return new Error(e.message.split('\n')[0] + ' | frame ' + JSON.stringify(st) + ' | host ' + JSON.stringify(host));
  };
  await settle();
  await fr.click('.xl-embed');
  try { await fr.waitForSelector('.xl-share:not([hidden]) .xl-copy', { timeout: 10000 }); } catch (e) { throw await failed(e); }
  await settle();
  // the share panel's own Copy (a field outside the panel has one too), and wait for one of Copy's two answers: the
  // page's start hint sits in the same toast, so "any text" could read the hint
  try { await fr.click('.xl-share .xl-field .xl-copy', { timeout: 15000 }); } catch (e) { throw await failed(e); }
  try {
    await fr.waitForFunction(() => ['Copied', 'Press Ctrl+C or \u2318C to copy'].includes(document.querySelector('.xl-toast').textContent),
      null, { timeout: 10000, polling: 50 });
  } catch (e) {
    const shown = await fr.evaluate(() => document.querySelector('.xl-toast').textContent).catch((x) => String(x));
    throw new Error('Copy gave no answer in 10 s; the toast reads ' + JSON.stringify(shown));
  }
  out.toast = await fr.evaluate(() => document.querySelector('.xl-toast').textContent);
  out.field = await fr.evaluate(() => { const t = document.querySelector('.xl-share .xl-field textarea'), a = document.activeElement;
    return { value: t.value, focused: a === t, start: t.selectionStart, end: t.selectionEnd }; });
  out.clip = GRANT === 'grant' ? await pg.evaluate(() => navigator.clipboard.readText()).catch((e) => 'unreadable: ' + e) : null;
} catch (e) { out.error = String(e && e.stack || e); }
await browser.close();
if (server) server.close();
console.log(JSON.stringify(out));
"""


@unittest.skipIf(NO_BROWSER, NO_BROWSER)
class TestEmbed(unittest.TestCase):
    def test_a_web_page_never_takes_a_file_address(self):
        """Served over http, the element loads a relative address and leaves the poster for a file: one (only a page
        opened from disk may name a film on disk; a web page could never load it, and now it says so by not trying)."""
        _, live, _ = sample()
        shutil.copy(str(LIVE / "embed.js"), str(TMP / "embed.js"))
        host = TMP / "embed-host-http.html"
        host.write_text('<!doctype html><meta charset="utf-8"><script src="embed.js"></script><body style="width:900px">'
                        '<showtime-xray src="%s" ratio="16/9"></showtime-xray><showtime-xray src="%s" ratio="16/9">'
                        '</showtime-xray>' % (live.name, live.as_uri()), encoding="utf-8")
        drv = TMP / "embed.mjs"
        drv.write_text(EMBED, encoding="utf-8")
        cp = subprocess.run([NODE, str(drv), str(SKILL), str(host), "http"], env=ENV, cwd=str(TMP),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertNotIn("error", r, r.get("error"))
        self.assertEqual(r["logs"], [], "no page error")
        self.assertIsNotNone(r["loaded"][0], "a relative address loads from a web page")
        self.assertTrue(r["loaded"][0]["src"].startswith("http://127.0.0.1:"), r["loaded"][0])
        self.assertIsNone(r["loaded"][1], "a file: address from a web page leaves the poster")

    def test_copy_buttons_in_the_sandboxed_frame(self):
        """In the frame embed.js makes (sandbox allow-scripts, an opaque origin), a real click on Copy copies (checked on
        the clipboard where the test may read it), and a host that refuses the clipboard gets the text selected with how
        to copy it: never "Copied" with nothing copied."""
        _, live, _ = sample()
        shutil.copy(str(LIVE / "embed.js"), str(TMP / "embed.js"))
        host = TMP / "copy-host.html"
        host.write_text('<!doctype html><meta charset="utf-8"><script src="embed.js"></script><body style="width:900px">'
                        '<showtime-xray src="%s" ratio="16/9"></showtime-xray>' % live.name, encoding="utf-8")
        drv = TMP / "copy.mjs"
        drv.write_text(COPY, encoding="utf-8")
        seen = {}
        for how in ("plain", "grant", "refuse"):
            cp = subprocess.run([NODE, str(drv), str(SKILL), str(host), how], env=ENV, cwd=str(TMP), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
            self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
            r = json.loads(cp.stdout.strip().splitlines()[-1])
            self.assertNotIn("error", r, r.get("error"))
            self.assertEqual(r["logs"], [], "no page error")
            self.assertEqual(r["sandbox"], "allow-scripts")
            self.assertIn("<showtime-xray", r["field"]["value"], "the first field is the embed snippet")
            self.assertIn(r["toast"], ("Copied", "Press Ctrl+C or \u2318C to copy"), (how, r["toast"]))
            if how == "grant":
                self.assertEqual(r["toast"], "Copied", r)
                # Windows' clipboard holds text with \r\n line ends; a textarea's value always has \n
                self.assertEqual(r["clip"].replace("\r\n", "\n"), r["field"]["value"],
                                 "the sandboxed frame's copy is on the clipboard")
            if r["toast"] != "Copied":
                self.assertTrue(r["field"]["focused"], (how, r["field"]))
                self.assertEqual((r["field"]["start"], r["field"]["end"]), (0, len(r["field"]["value"])),
                                 "the whole snippet is selected, ready for Ctrl+C")
            seen[how] = r["toast"]
        self.assertEqual(seen["refuse"], "Press Ctrl+C or \u2318C to copy", "a refused clipboard selects the text")

    def test_sources_and_the_sandboxed_frame(self):
        _, live, _ = sample()
        host = TMP / "embed-host.html"
        srcs = [live.name + "#old", "javascript:alert(1)", "data:text/html,<p>x</p>", "vbscript:x", "java\tscript:alert(1)"]
        host.write_text('<!doctype html><meta charset="utf-8"><script src="%s"></script><body style="width:900px">%s'
                        % ((LIVE / "embed.js").as_uri(), "".join(
                            '<showtime-xray src="%s" ratio="16/9"%s></showtime-xray>' % (v, ' hit="2"' if k == 0 else "")
                            for k, v in enumerate(srcs))), encoding="utf-8")
        drv = TMP / "embed.mjs"
        drv.write_text(EMBED, encoding="utf-8")
        cp = subprocess.run([NODE, str(drv), str(SKILL), str(host)], env=ENV, cwd=str(TMP), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertNotIn("error", r, r.get("error"))
        self.assertEqual(r["logs"], [], "no page error")
        ok = r["loaded"][0]
        self.assertIsNotNone(ok, "a page opened from disk (file:) loads its film")
        # compared decoded: the browser writes a Windows 8.3 short name's "~" (RUNNER~1) as %7E, the same file
        self.assertEqual(unquote(ok["src"]), unquote(live.as_uri()) + "#embed_hit2", "built from the parsed address, its old fragment replaced")
        self.assertEqual(ok["sandbox"], "allow-scripts", "the frame gets no storage, forms, popups or top navigation")
        self.assertEqual(r["loaded"][1:], [None] * 4, "javascript:, data: and vbscript: leave the poster")
        self.assertEqual(r["frames"], 1)
        self.assertTrue(r["resized"], "the sandboxed page still reports its height to the host")


@unittest.skipIf(NO_BROWSER, NO_BROWSER)
class TestBrowser(unittest.TestCase):
    def test_jump_lands_on_the_peak(self):
        _, out, _ = sample()
        drv = TMP / "drv.mjs"
        drv.write_text(DRIVER, encoding="utf-8")
        cp = subprocess.run([NODE, str(drv), str(SKILL), str(out)], env=ENV, cwd=str(TMP), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=300)
        self.assertEqual(cp.returncode, 0, cp.stderr[-2000:])
        r = json.loads(cp.stdout.strip().splitlines()[-1])
        self.assertNotIn("error", r, r.get("error"))
        self.assertEqual(r["logs"], [], "no console error")
        self.assertEqual(r["net"], [], "no request off the file")
        self.assertGreaterEqual(len(r["start"]["kept"]), 3)
        for j in r["jumps"]:
            self.assertEqual(j["frame"], j["evframe"], j)
            self.assertEqual(j["cur"], j["i"], "the kit's acting event is the one jumped to: %s" % j)
            self.assertEqual(j["s"], 1, "the strike peaks on its event's frame: %s" % j)
        self.assertEqual(r["key"]["frame"], r["key"]["want"], "→ lands on the next event's frame: %s" % r["key"])
        self.assertEqual(r["tick"]["frame"], r["tick"]["want"], "a click on a tick lands on its event's frame: %s" % r["tick"])
        self.assertIn("hover", r, "the sample draws part labels")
        self.assertEqual(r["hover"]["hot"], r["hover"]["want"], "the pointer on a part label lights it")
        self.assertTrue(r["spacePlays"], "space plays")
        self.assertEqual(r["marker"], "none")
        self.assertLessEqual(r["scrollW"], 390, "no sideways scroll on a phone")
        self.assertEqual(r["slow"], {"rate": 0.25, "slow": True})
        self.assertEqual(r["slowEnd"], r["midFrame"], "0.25x ends on the event's frame")
        self.assertEqual(r["light"]["theme"], "light")
        self.assertEqual(r["light"]["frame"], r["midFrame"], "the theme switches on the same frame")


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    try:
        unittest.main(argv=argv, verbosity=2 if "-v" in argv else 1)
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

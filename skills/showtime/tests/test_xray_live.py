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

from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
NODE = shutil.which("node", path=ENV.get("PATH"))
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


@unittest.skipIf(FAST or not NODE, "--fast: no browser")
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
const [SKILL, HOST] = process.argv.slice(2);
const { openBrowser } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'stagehost.mjs')).href);
const { browser } = await openBrowser({ headless: true, args: ['--allow-file-access-from-files'] });
const out = { logs: [] };
try {
  const ctx = await browser.newContext({ viewport: { width: 1000, height: 800 } });
  const pg = await ctx.newPage();
  pg.on('pageerror', (e) => out.logs.push(String(e.message || e)));
  await pg.goto(pathToFileURL(HOST).href);
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
console.log(JSON.stringify(out));
"""


@unittest.skipIf(FAST or not NODE, "--fast: no browser")
class TestEmbed(unittest.TestCase):
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


@unittest.skipIf(FAST or not NODE, "--fast: no browser")
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

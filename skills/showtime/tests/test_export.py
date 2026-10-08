#!/usr/bin/env python3
"""HTML export smoke tests: `showtime export html` (scripts/export.mjs, runtime/player/).

Real runs, each opened in headless Chrome with every network request blocked:
  - templates/film   -> one file, live ST.score (--audio auto picks score) streamed in pieces:
                        first sound fast, the stream equals a whole render of the score (verify()),
                        a seek into the middle of a pad sounds at once (AnalyserNode on the output);
                        start screen (title + Play with the length) in the film's fonts; key map (space/k, arrows +-1 s, shift+arrow
                        one frame, 1-9 chapters, [ ] prev/next chapter, r restart, c link);
                        deep links #t= and #chapter=; minified + compressed, well under 400 KB
  - templates/dom    -> one file, embedded AAC mix (components, shader transitions, fonts); on a phone
                        held upright: picture full width on the film's ground, chapters under it,
                        controls docked at the bottom; in a sandboxed host frame: detected as hosted
  - templates/short  -> --folder (index.html + assets/), vertical, captions + embedded mix,
                        opened from file:// and from a static http server
  - a fixture page   -> <video>, fetch() of JSON (also via new URL(p, location.href)), ES modules
                        with import.meta.url, a page import map with bare and prefix specifiers,
                        innerHTML images, CSS backgrounds and an emoji: all from the packed files;
                        exported with -o <folder>/ (the file goes inside the folder)
  - templates/data in an artifact-viewer host: a sandboxed frame on another origin whose CSP allows
                        inline styles only and no fonts at all (no blob:/data: stylesheets or fonts):
                        the stage text is still in the theme's fonts at the theme's sizes; a page whose
                        font file is broken reports it (player.warnings, console)
  - templates/dom in a browser without AAC -> plays silently and says so on screen
  - film with --controls none --autoplay-muted --loop
  - the --max-mb budget refuses an oversize export with a breakdown; --target artifact
Asserted for every export: zero network requests, no console errors, the player starts after a
click, currentTime advances, the soundtrack is present and not silent, the picture never steps
back or runs ahead of the sound (from the click, and after a seek while playing), the stage frame
asks for no permissions, the size is under the limit; for film, dom and the fixture: a frame seeked in the player matches `showtime snap` at the
same time (PSNR).

Stdlib only. usage: python tests/test_export.py [--fast] [-v]
"""
from __future__ import annotations

import _isolate  # noqa: F401  (run from a scratch folder: never write into the repository)

import concurrent.futures
import functools
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from _listen import needs_listen

TESTS_DIR = Path(__file__).resolve().parent
SKILL = TESTS_DIR.parent
LAUNCHER = SKILL / "lib" / "st" / "launcher.py"
sys.path.insert(0, str(SKILL / "lib"))

from st import ff  # noqa: E402
from st.launcher import build_env, showtime_home  # noqa: E402

FAST = "--fast" in sys.argv
ENV = build_env(showtime_home())
MB = 1000 * 1000
PSNR_MIN = 38.0   # same runtime, same browser: frames are normally identical (inf); allow AA noise
TMP = None


def showtime(*args, check=True, timeout=300):
    cp = subprocess.run([sys.executable, str(LAUNCHER)] + [str(a) for a in args], env=ENV,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8",
                        errors="replace", timeout=timeout)
    if check and cp.returncode != 0:
        raise AssertionError("showtime %s failed (rc=%d):\n%s\n%s" % (
            " ".join(map(str, args)), cp.returncode, cp.stdout[-3000:], cp.stderr[-3000:]))
    return cp


def export(project, out, *extra):
    cp = showtime("export", "html", project, "-o", out, "--json", "-q", *extra)
    return json.loads(cp.stdout)


def psnr(a, b):
    cp = subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-nostdin", "-i", str(a), "-i", str(b), "-lavfi",
                         "[0]format=rgb24[x];[1]format=rgb24[y];[x][y]psnr", "-f", "null", "-"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=120)
    m = re.search(r"average:(inf|[\d.]+)", cp.stderr)
    assert m, cp.stderr[-2000:]
    return float("inf") if m.group(1) == "inf" else float(m.group(1))


# Browser driver: opens an export with the network blocked and reports what happened.
DRIVER = r"""
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const SKILL = process.argv[2];
const job = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const { launchBrowser } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'chrome.mjs')).href);
const { browser } = await launchBrowser({ gpu: 'auto', headless: true, args: ['--disable-lcd-text', '--proxy-server=http://127.0.0.1:9'] });
const out = [];
try {
  for (const c of job.cases) {
    const ctx = await browser.newContext({ viewport: { width: c.width, height: c.height }, deviceScaleFactor: 1, isMobile: !!c.mobile, hasTouch: !!c.mobile });
    const page = await ctx.newPage();
    const r = { name: c.name, requests: [], console: [], errors: [] };
    const allowed = (u) => /^(data|blob|about):/.test(u) || (c.origin ? u.startsWith(c.origin) || (!!c.origin2 && u.startsWith(c.origin2)) : u.startsWith('file:'));
    page.on('request', (q) => { const u = q.url(); if (!/^(data|blob):/.test(u) && !allowed(u)) r.requests.push(u); });
    page.on('console', (m) => { if (m.type() === 'error') r.console.push(m.text().slice(0, 300)); });
    page.on('pageerror', (e) => r.errors.push(String(e.message || e).slice(0, 300)));
    if (c.noAac) {  // a browser without AAC (Chromium builds without proprietary codecs)
      await page.addInitScript(() => {
        const o = HTMLMediaElement.prototype.canPlayType;
        HTMLMediaElement.prototype.canPlayType = function (t) { return /mp4a|^audio\/mp4/.test(String(t)) ? '' : o.call(this, t); };
      });
    }
    const t0 = Date.now();
    await page.goto(c.url, { waitUntil: 'load', timeout: 60000 });
    try {
      let T = page;   // where the player lives: the page, or a (sandboxed) frame of a host page
      for (let i = 0; c.frame && i < 100; i++) {
        const f = page.frames().find((x) => x.url().endsWith(c.frame));
        if (f) { T = f; break; }
        await page.waitForTimeout(50);
      }
      r.info = await T.evaluate(() => window.showtimePlayer.ready);
      r.readyMs = Date.now() - t0;
      r.before = await T.evaluate(() => ({ paused: window.showtimePlayer.paused, muted: window.showtimePlayer.muted,
        bar: getComputedStyle(document.querySelector('.stp-bar')).display, big: !!document.querySelector('.stp-big'),
        allow: document.querySelector('.stp-frame').getAttribute('allow'), card: document.getElementById('stp').classList.contains('has-start'),
        startTime: window.showtimePlayer.startTime, started: window.showtimePlayer.started,
        hosted: document.getElementById('stp').classList.contains('is-hosted'),
        linkShown: getComputedStyle(document.querySelector('.stp-link')).display !== 'none',
        title: document.title }));
      if (c.card) {   // the start screen: title and Play over the poster frame, in the film's own fonts
        for (let i = 0; i < 60 && !(await T.evaluate(() => document.getElementById('stp').classList.contains('start-set'))); i++) await page.waitForTimeout(50);
        r.cardText = await T.evaluate(() => { const e = document.querySelector('.stp-sbox'); return e ? e.innerText : null; });
        r.cardFont = await T.evaluate(() => { const e = document.querySelector('.stp-h'); return e ? getComputedStyle(e).fontFamily : null; });
        r.cardFaces = await T.evaluate(() => [...document.fonts].filter((f) => f.status === 'loaded' && /^stp /.test(f.family.replace(/["']/g, ''))).map((f) => f.family));
        r.cardPos = await T.evaluate(() => document.querySelector('.stp-start').getAttribute('data-pos'));
        r.cardDense = await T.evaluate(() => document.querySelector('.stp-start').hasAttribute('data-dense'));
        r.cardSh = await T.evaluate(() => document.querySelector('.stp-start').style.getPropertyValue('--stp-sh'));
      }
      if (c.layout) {   // where the picture, the details and the controls sit
        // let the controls' fade-in finish first (on a loaded machine it can still be running here)
        for (let i = 0; i < 40 && Number(await T.evaluate(() => getComputedStyle(document.querySelector('.stp-bar')).opacity)) < 0.99; i++) await page.waitForTimeout(50);
        r.layout = await T.evaluate(() => {
          const q = (s) => document.querySelector(s), box = (s) => { const b = q(s).getBoundingClientRect(); return [b.left, b.top, b.width, b.height].map(Math.round); };
          return { mode: q('#stp').getAttribute('data-layout'), holder: box('.stp-holder'), bar: box('.stp-bar'), go: box('.stp-go'),
            info: getComputedStyle(q('.stp-info')).display, chapters: document.querySelectorAll('.stp-chlist button').length,
            pageBg: getComputedStyle(document.body).backgroundColor, stpBg: getComputedStyle(q('#stp')).backgroundColor,
            barOpacity: getComputedStyle(q('.stp-bar')).opacity, vw: innerWidth, vh: innerHeight };
        });
      }
      // every frame drawn from the click on: [frame, audio time]; and the transport events, for failure messages
      await T.evaluate(() => { const p = window.showtimePlayer; window.__fs = []; window.__ev = []; const t0 = performance.now();
        p.on('frame', (f) => { const A = p.audio; window.__fs.push([f, A && !A.paused ? A.currentTime : null]); });
        for (const e of ['play', 'pause', 'ended', 'seek', 'loop']) p.on(e, () => { const A = p.audio;
          if (window.__ev.length < 40) window.__ev.push([e, Math.round(performance.now() - t0), +p.currentTime.toFixed(3),
            A ? +A.currentTime.toFixed(3) : null, A ? A.paused : null]); }); });
      const w0 = Date.now();   // from the click: on a starved browser the click alone can take seconds
      if (c.clickSel) await T.click(c.clickSel);
      else if (!c.noClick) await page.mouse.click(Math.round(c.width / 2), Math.round(c.height / 2));
      const t1 = await T.evaluate(() => window.showtimePlayer.currentTime);
      await page.waitForTimeout(1500);
      r.after = await T.evaluate(() => {
        const p = window.showtimePlayer, A = p.audio;
        return { t: p.currentTime, paused: p.paused, muted: p.muted, error: p.error,
          audio: A ? { duration: A.duration, readyState: A.readyState, t: A.currentTime, paused: A.paused } : null };
      });
      r.advanced = r.after.t - t1;
      r.windowMs = Date.now() - w0;   // click + the 1.5 s window, as the driver lived it (much longer: a starved browser)
      r.startFrames = await T.evaluate(() => window.__fs.splice(0));
      r.ui = await T.evaluate(() => { const m = document.querySelector('.stp-msg');
        return { msg: m.hidden ? '' : m.textContent, muteDisabled: document.querySelector('.stp-mute').disabled }; });
      if (c.stageText) {   // the stage document's text: which font it is set in, and how big it is
        await T.evaluate((x) => { window.showtimePlayer.pause(); return window.showtimePlayer.seek(x); }, c.stageText.at);
        await page.waitForTimeout(400);
        const S = page.frames().find((f) => f.parentFrame() === T);
        r.stageText = S ? await S.evaluate((sels) => {
          const out = {};
          for (const s of sels) {
            const el = document.querySelector(s);
            if (!el) { out[s] = null; continue; }
            const b = el.getBoundingClientRect(), cs = getComputedStyle(el);
            const fam = cs.fontFamily.split(',')[0].trim().replace(/^["']|["']$/g, '');
            out[s] = { family: fam, fontSize: parseFloat(cs.fontSize), h: b.height, frameH: innerHeight,
              loaded: [...document.fonts].some((f) => f.status === 'loaded' && f.family.replace(/["']/g, '') === fam) };
          }
          return out;
        }, c.stageText.sels) : null;
        for (let i = 0; i < 20 && c.stageText.warn && !(await T.evaluate(() => window.showtimePlayer.warnings.length)); i++) await page.waitForTimeout(100);
        r.warnings = await T.evaluate(() => window.showtimePlayer.warnings);
      }
      if (c.seekPlaying) {   // jump while playing (L: +5 s): the picture must not step back once the sound resumes
        r.seekFrom = await T.evaluate(() => window.showtimePlayer.currentTime);
        await page.keyboard.press('l');
        await page.waitForTimeout(900);
        // a busy machine (parallel test files) draws fewer frames: wait (up to 6 s) for a dozen past the jump
        const past = Math.floor((r.seekFrom + 5.0) * 30) - 3;
        for (let i = 0; i < 50 && (await T.evaluate((m) => new Set(window.__fs.filter((x) => x[0] >= m).map((x) => x[0])).size, past)) < 12; i++)
          await page.waitForTimeout(100);
        r.seekFrames = await T.evaluate(() => window.__fs.splice(0));
      }
      r.events = await T.evaluate(() => window.__ev || []);
      if (c.keys) {
        const now = () => T.evaluate(() => window.showtimePlayer.currentTime);
        const k = {};
        await page.keyboard.press('k'); k.pausedAfterK = await T.evaluate(() => window.showtimePlayer.paused);
        await page.keyboard.press('Digit3'); k.digit3 = await now();
        await page.keyboard.press('ArrowRight'); k.right = await now();
        await page.keyboard.press('Shift+ArrowRight'); k.shiftRight = await now();
        await page.keyboard.press('Comma'); k.comma = await now();
        await page.keyboard.press('BracketRight'); k.nextChapter = await now();
        await page.keyboard.press('BracketLeft'); k.prevChapter = await now();
        await page.keyboard.press('ArrowLeft'); k.left = await now();
        await page.keyboard.press('Shift+Slash'); k.help = await T.evaluate(() => !document.querySelector('.stp-help').hidden);
        await page.keyboard.press('Escape'); k.helpClosed = await T.evaluate(() => document.querySelector('.stp-help').hidden);
        await page.keyboard.press('c'); await page.waitForTimeout(80);
        k.toast = await T.evaluate(() => { const t = document.querySelector('.stp-toast'); return t && !t.hidden ? t.textContent : ''; });
        k.link = await T.evaluate(() => window.showtimePlayer.link(12.34));
        await page.keyboard.press('r'); await page.waitForTimeout(120);
        k.restart = await T.evaluate(() => ({ t: window.showtimePlayer.currentTime, paused: window.showtimePlayer.paused }));
        await page.keyboard.press('m'); k.muted = await T.evaluate(() => window.showtimePlayer.muted);
        await page.keyboard.press('m');
        r.keys = k;
      }
      if (c.live) {   // the procedural score, streamed: a seek into the middle of a pad sounds at once
        r.live = await T.evaluate(async (at) => {
          const p = window.showtimePlayer, A = p.audio;
          const an = A.tap();
          const buf = new Float32Array(an.fftSize);
          if (p.paused) p.play();
          p.currentTime = at;
          const t0 = performance.now();
          let firstLoudMs = null, rmsAt = [];
          while (performance.now() - t0 < 1500) {
            await new Promise((res) => setTimeout(res, 40));
            an.getFloatTimeDomainData(buf);
            let s = 0; for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
            const rms = Math.sqrt(s / buf.length);
            rmsAt.push([Math.round(performance.now() - t0), +rms.toFixed(4), +A.currentTime.toFixed(3)]);
            if (firstLoudMs === null && rms > 0.01) firstLoudMs = Math.round(performance.now() - t0);
          }
          p.pause();
          // let the background stream finish, then compare it with a whole render of the score
          for (let i = 0; i < 100 && A.rendered().reduce((s, r) => s + r[1] - r[0], 0) < p.duration - 0.05; i++) await new Promise((res) => setTimeout(res, 100));
          const v = await A.verify(0, p.duration);
          return { firstLoudMs, rmsAt, verify: v, seams: A.seams, rendered: A.rendered(), firstPieceMs: A.firstPieceMs, kind: A.kind };
        }, c.live);
      }
      if (c.audio === true) {
        r.rms = await T.evaluate(async () => {
          const A = window.showtimePlayer.audio;
          if (A && A.kind === 'score') { const l = A.level(0, 3); return { rms: l.rms, duration: A.duration, rendered: l.rendered }; }
          if (!A || !A.src) return null;
          const ab = await (await fetch(A.src)).arrayBuffer();
          const buf = await new OfflineAudioContext(2, 48000, 48000).decodeAudioData(ab);
          let s = 0; const d = buf.getChannelData(0);
          for (let i = 0; i < d.length; i++) s += d[i] * d[i];
          return { rms: Math.sqrt(s / d.length), duration: buf.duration };
        });
      }
      if (c.ended) {   // the last frame: the end card stays readable, the replay control moves off centre
        r.ended = await T.evaluate(async () => {
          const p = window.showtimePlayer;
          p.seek(Math.max(0, p.duration - 0.3)); p.play();
          for (let i = 0; i < 100 && !p.ended; i++) await new Promise((res) => setTimeout(res, 50));
          await new Promise((res) => setTimeout(res, 400));   // let the vignette fade finish
          const q = (s) => document.querySelector(s), box = (el) => { const b = el.getBoundingClientRect(); return [b.left, b.top, b.width, b.height]; };
          const big = q('.stp-big');
          return { ended: p.ended, big: box(big), holder: box(q('.stp-holder')), label: big.getAttribute('aria-label'),
            display: getComputedStyle(big).display, text: big.textContent.trim(),
            vignette: +getComputedStyle(q('.stp-cover'), '::before').opacity };
        });
      }
      if (c.shots && c.shots.length) {
        await T.evaluate(() => window.showtimePlayer.pause());
        await page.addStyleTag({ content: '.stp-bar,.stp-start,.stp-cover,.stp-unmute{display:none!important}' });
        r.shots = {};
        for (const t of c.shots) {
          await T.evaluate((x) => window.showtimePlayer.seek(x), t);
          // headless Chrome (seen on Linux) can keep compositing a paused <video>'s previous frame after a
          // seek until the page asks for a video frame: ask in the stage frame (300 ms at most per video)
          const HF = T === page ? page.mainFrame() : T, SF = page.frames().find((f) => f.parentFrame() === HF);
          if (SF) await SF.evaluate(() => Promise.all([...document.querySelectorAll('video')].map((v) => new Promise((res) => {
            if (typeof v.requestVideoFrameCallback !== 'function') return res();
            const timer = setTimeout(res, 300);
            v.requestVideoFrameCallback(() => { clearTimeout(timer); res(); });
          })))).catch(() => {});
          await page.waitForTimeout(60);
          const f = path.join(c.shotDir, `export-${t.toFixed(3)}.png`);
          fs.writeFileSync(f, await page.screenshot({ type: 'png' }));
          r.shots[t.toFixed(3)] = f;
        }
      }
    } catch (e) { r.fatal = String(e.message || e).slice(0, 500); }
    out.push(r);
    await ctx.close();
  }
} finally { await browser.close(); }
fs.writeFileSync(job.result, JSON.stringify(out, null, 2));
"""


def drive(cases):
    job = TMP / ("job-%d.json" % int(time.time() * 1000))
    res = TMP / (job.stem + ".out.json")
    job.write_text(json.dumps({"cases": cases, "result": str(res)}), encoding="utf-8")
    drv = TMP / "driver.mjs"
    drv.write_text(DRIVER, encoding="utf-8")
    node = shutil.which("node", path=ENV.get("PATH")) or "node"
    cp = subprocess.run([node, str(drv), str(SKILL), str(job)], env=ENV, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, encoding="utf-8", errors="replace", timeout=240)
    assert cp.returncode == 0 and res.exists(), "driver failed:\n%s\n%s" % (cp.stdout[-2000:], cp.stderr[-3000:])
    return {r["name"]: r for r in json.loads(res.read_text(encoding="utf-8"))}


def snap(project, times, outdir):
    showtime("snap", project, "--at", ",".join("%.3f" % t for t in times), "-o", outdir)
    return {"%.3f" % t: Path(outdir) / ("t%ss.png" % ("%.3f" % t).rjust(8, "0")) for t in times}


FIXTURE_HTML = """<!doctype html><html><head><meta charset="utf-8">
<script src="/_st/stage.js"></script>
<link rel="stylesheet" href="/_lib/@fontsource-variable/inter/index.css">
<style>
 body{font-family:'Inter Variable';color:#fff}
 .bg{position:absolute;right:10px;top:10px;width:64px;height:64px;background:url(media/tile.png)}
 video{position:absolute;left:10px;bottom:10px;width:320px;height:180px}
 #t{position:absolute;left:20px;top:20px;font-size:28px}
</style></head><body>
<div class="bg"></div>
<div id="t">Party \U0001F389 <span id="j">...</span> <span id="m"></span></div>
<video src="media/clip.webm" muted playsinline data-start="0"></video>
<script type="importmap">{"imports": {"kit": "./vendor/kit.js", "kit/": "./vendor/kit/"}}</script>
<div id="k" style="position:absolute;left:20px;top:80px;font-size:22px">...</div>
<script type="module">
import { mount, base } from './js/mod.js';
import { label } from 'kit/extra.js';
mount(document.getElementById('m'));
ST.waitFor(fetch(new URL('data/stats.json', location.href)).then(r => r.json()).then(d => {
  document.getElementById('k').textContent = label + ' / ' + d.value; }), 'kit');
const probe = new Image(); probe.src = base;
ST.waitFor(fetch('data/stats.json').then(r => r.json()).then(d => { document.getElementById('j').textContent = d.label + ' ' + d.value; }), 'data');
ST.waitFor(probe.decode(), 'img');
</script>
</body></html>
"""


def make_fixture(root):
    d = root / "fixture"
    for sub in ("media", "js", "data"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    fx = ff.ffmpeg_path()
    subprocess.run([fx, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=3", "-c:v", "libvpx-vp9",
                    "-b:v", "0", "-crf", "40", "-g", "30", "-an", str(d / "media" / "clip.webm")], check=True, timeout=120)
    subprocess.run([fx, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x3366cc:s=64x64", "-frames:v", "1",
                    str(d / "media" / "tile.png")], check=True, timeout=60)
    (d / "showtime.json").write_text(json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 3,
                                                 "background": "#101418", "title": "Export fixture"}), encoding="utf-8")
    (d / "data" / "stats.json").write_text('{"label": "from json", "value": 42}', encoding="utf-8")
    (d / "js" / "mod.js").write_text(
        "import { helper } from './helper.js';\n"
        "export const base = new URL('../media/tile.png', import.meta.url).href;\n"
        "export function mount(el) { el.innerHTML = '<img src=\"media/tile.png\" width=\"32\" height=\"32\">' + helper(); }\n",
        encoding="utf-8")
    (d / "js" / "helper.js").write_text("export const helper = () => '<b>ok</b>';\n"
                                        "/* the raw take lives in ../data/unused.bin (not loaded) */\n"
                                        "// and a note: data/unused.bin is regenerated, never shipped\n", encoding="utf-8")
    # a large file that only comments name: the export must not pack it
    (d / "data" / "unused.bin").write_bytes(os.urandom(300_000))
    # a page import map with a prefix entry, and a module importing a bare specifier
    (d / "vendor" / "kit").mkdir(parents=True, exist_ok=True)
    (d / "vendor" / "kit.js").write_text("export const name = 'kit';\n", encoding="utf-8")
    (d / "vendor" / "kit" / "extra.js").write_text("import { name } from 'kit';\nexport const label = name + ' extra';\n",
                                                  encoding="utf-8")
    (d / "index.html").write_text(FIXTURE_HTML, encoding="utf-8")
    return d


# what an artifact viewer may allow: inline styles only (no blob:/data: stylesheets) and no fonts at all
STRICT_CSP = ("default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob: data:; style-src 'unsafe-inline'; "
              "img-src data: blob:; media-src data: blob:; connect-src data: blob:")


def serve(folder):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def end_headers(self):
            if self.path.startswith("/strict/"):   # pages under /strict/ get the strict CSP
                self.send_header("Content-Security-Policy", STRICT_CSP)
            super().end_headers()
    handler = functools.partial(Quiet, directory=str(folder))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@needs_listen
class ExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global TMP
        TMP = Path(tempfile.mkdtemp(prefix="st-export-test-"))
        cls.tmp = TMP
        for t in ("film", "dom", "short", "data"):
            shutil.copytree(SKILL / "templates" / t, TMP / t)
        # a page whose font file is broken: the export must say so (the text falls back to its stack)
        bf = TMP / "badfont"
        (bf / "fonts").mkdir(parents=True)
        (bf / "fonts" / "broken.woff2").write_bytes(b"wOF2" + os.urandom(2000))
        (bf / "showtime.json").write_text(json.dumps({"title": "Bad font", "width": 640, "height": 360, "fps": 30,
                                                      "duration": 2}), encoding="utf-8")
        (bf / "index.html").write_text(
            '<!doctype html><html><head><script src="/_st/stage.js"></script>'
            '<link rel="stylesheet" href="/_lib/@fontsource-variable/inter/index.css"><style>'
            '@font-face{font-family:"Broken Face";src:url(fonts/broken.woff2) format("woff2")}'
            'body{margin:0;background:#123;color:#fff}#t{font:700 40px/1.2 "Broken Face","Inter Variable",sans-serif;padding:40px}'
            '</style></head><body><div id="t">A broken font file</div></body></html>', encoding="utf-8")
        cls.fixture = make_fixture(TMP)
        # the fixture's emoji is packed only when it is installed, and a fresh machine has none: install it
        # the way the export's own warning tells a user to (a cached no-op when it is already there)
        cls.emoji_ok = showtime("assets", "emoji", "1f389", "--json", check=False).returncode == 0
        # a dark film whose poster frame is a bright, nearly empty page: no text in the corners, so only its
        # brightness tells the start screen that the dark scrim needs deepening
        lp = TMP / "lightposter"
        lp.mkdir()
        (lp / "showtime.json").write_text(json.dumps({"title": "Light Poster", "width": 1280, "height": 720, "fps": 30,
                                                      "duration": 3, "poster": 1.5}), encoding="utf-8")
        (lp / "index.html").write_text(
            '<!doctype html><html><head><link rel="stylesheet" href="/_lib/@fontsource-variable/inter/index.css">'
            '<script src="/_st/stage.js"></script><script src="/_st/film.js"></script></head><body><script>'
            "Film.start({ look: 'dark', fonts: ['650 1em \"Inter Variable\"'], scenes: function (T, g, F) {"
            "  F.box(0, 0, F.W, F.H, 0, { fill: '#f7f7f5' });"
            "  F.text('A bright app window', F.W / 2, F.H / 2, { size: 40, weight: 650, align: 'center', color: '#222' });"
            "} });</script></body></html>", encoding="utf-8")
        t0 = time.time()
        shots = TMP / "shots"
        cls.times = {"film": [2.0, 7.5], "dom": [1.5, 9.2], "fixture": [0.5, 2.2]}
        for name in cls.times:
            (shots / name).mkdir(parents=True, exist_ok=True)
        jobs = {
            "dom": lambda: export(TMP / "dom", TMP / "out" / "launch.html"),
            "short": lambda: export(TMP / "short", TMP / "out" / "short", "--folder"),
            "film": lambda: export(TMP / "film", TMP / "out" / "film.html"),
            "lightposter": lambda: export(lp, TMP / "out" / "light.html"),
            "data": lambda: export(TMP / "data", TMP / "out" / "strict" / "data.html", "--audio", "none", "--target", "artifact"),
            "badfont": lambda: export(bf, TMP / "out" / "strict" / "badfont.html", "--audio", "none"),
            # -o an existing-or-new folder (trailing slash): the file goes inside it
            "fixture": lambda: export(cls.fixture, str(TMP / "out" / "fixdir") + "/"),
            "bare": lambda: export(TMP / "film", TMP / "out" / "bare.html", "--controls", "none", "--autoplay-muted",
                                   "--loop", "--poster", "none"),
            "snap-film": lambda: snap(TMP / "film", cls.times["film"], shots / "film" / "snap"),
            "snap-dom": lambda: snap(TMP / "dom", cls.times["dom"], shots / "dom" / "snap"),
            "snap-fixture": lambda: snap(cls.fixture, cls.times["fixture"], shots / "fixture" / "snap"),
        }
        # at most 3 browsers at a time (the machine is shared)
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futs = {k: pool.submit(f) for k, f in jobs.items()}
            done = {k: f.result() for k, f in futs.items()}
        cls.rep = {k: v for k, v in done.items() if not k.startswith("snap-")}
        cls.snaps = {k[5:]: v for k, v in done.items() if k.startswith("snap-")}
        cls.export_s = time.time() - t0
        (TMP / "out" / "host.html").write_text(
            '<!doctype html><html><head><link rel="icon" href="data:,"></head><body style="margin:0">'
            '<iframe sandbox="allow-scripts" src="launch.html" style="width:960px;height:540px;border:0"></iframe></body></html>',
            encoding="utf-8")
        # an artifact viewer: the page on its own origin (localhost vs 127.0.0.1), sandboxed, under the strict CSP
        for n in ("data", "badfont"):
            (TMP / "out" / ("host-%s.html" % n)).write_text(
                '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<link rel="icon" href="data:,"></head><body style="margin:0"><iframe sandbox="allow-scripts" '
                'src="http://localhost:%%PORT%%/strict/%s.html" style="position:fixed;inset:0;width:100%%;height:100%%;border:0">'
                '</iframe></body></html>' % n, encoding="utf-8")
        cls.srv = serve(TMP / "out")
        port = cls.srv.server_address[1]
        origin = "http://127.0.0.1:%d" % port
        origin2 = "http://localhost:%d" % port
        for n in ("data", "badfont"):
            h = TMP / "out" / ("host-%s.html" % n)
            h.write_text(h.read_text(encoding="utf-8").replace("%PORT%", str(port)), encoding="utf-8")

        def case(name, file, w, h, **kw):
            c = {"name": name, "url": Path(file).resolve().as_uri(), "width": w, "height": h, "audio": True,
                 "shotDir": str(shots / name.split("-")[0]), "shots": []}
            c.update(kw)
            return c
        film_url = Path(cls.rep["film"]["output"]).resolve().as_uri()
        cls.res = drive([
            case("film", cls.rep["film"]["output"], 1920, 1080, shots=cls.times["film"], keys=True, card=True, live=4.4),
            # deep links: the video opens at a time, or at a chapter by name (after the click to begin)
            dict(case("link-t", cls.rep["film"]["output"], 960, 540), url=film_url + "#t=7.5", card=True),
            dict(case("link-ch", cls.rep["film"]["output"], 960, 540, audio=False, ended=True), url=film_url + "#chapter=data"),
            case("dom", cls.rep["dom"]["output"], 1920, 1080, shots=cls.times["dom"], seekPlaying=True),
            # the same file in a browser that cannot decode AAC: plays silently and says so
            case("noaac", cls.rep["dom"]["output"], 960, 540, audio=False, noAac=True),
            case("fixture", cls.rep["fixture"]["output"], 640, 360, shots=cls.times["fixture"], audio=False),
            case("short-file", cls.rep["short"]["output"], 540, 960, audio="element"),
            dict(case("short-http", cls.rep["short"]["output"], 540, 960), url=origin + "/short/index.html", origin=origin),
            # a host that sandboxes the page without allow-same-origin (the stage frame gets its own origin)
            dict(case("sandboxed", cls.rep["dom"]["output"], 960, 540), url=origin + "/host.html", origin=origin,
                 frame="/launch.html"),
            case("bare", cls.rep["bare"]["output"], 960, 540, noClick=True),
            # an artifact viewer on a phone: another origin, sandboxed, inline styles only, no fonts allowed
            dict(case("artifact", cls.rep["data"]["output"], 390, 844, audio=False, mobile=True),
                 url=origin + "/host-data.html", origin=origin, origin2=origin2, frame="/strict/data.html", clickSel=".stp-go",
                 stageText={"at": 1.8, "sels": [".kicker", "#open h1"]}),
            dict(case("badfont", cls.rep["badfont"]["output"], 960, 540, audio=False),
                 url=origin + "/host-badfont.html", origin=origin, origin2=origin2, frame="/strict/badfont.html",
                 stageText={"at": 1.0, "sels": ["#t"], "warn": True}),
            case("light", cls.rep["lightposter"]["output"], 1280, 720, audio=False, card=True),
            # a phone held upright: the picture full width on the film's ground, details and controls under it
            case("phone", cls.rep["dom"]["output"], 390, 844, mobile=True, layout=True, clickSel=".stp-go"),
        ])

    @classmethod
    def tearDownClass(cls):
        try:
            cls.srv.shutdown()
        except Exception:
            pass
        shutil.rmtree(TMP, ignore_errors=True)

    def check_common(self, name, audio=True):
        r = self.res[name]
        self.assertNotIn("fatal", r, r.get("fatal"))
        self.assertIsNone(r["before"]["allow"], "the stage frame needs no permissions (allow=%r)" % r["before"]["allow"])
        self.assertEqual(r["requests"], [], "%s made network requests: %s" % (name, r["requests"][:5]))
        self.assertEqual(r["console"], [], "%s console errors: %s" % (name, r["console"][:5]))
        self.assertEqual(r["errors"], [], "%s page errors: %s" % (name, r["errors"][:5]))
        a = r["after"]["audio"]
        if audio:
            self.assertIsNotNone(a, "%s has no audio element" % name)
            self.assertAlmostEqual(a["duration"], r["info"]["duration"], delta=0.15)
            if audio != "element":   # --folder from file:// cannot read the file back (browsers refuse fetch there)
                self.assertIsNotNone(r.get("rms"))
                self.assertGreater(r["rms"]["rms"], 0.005, "%s soundtrack is silent" % name)
        # from here on the checks watch playback in real time: they need a machine that can play it
        slow = self.too_slow(r)
        if slow:
            self.skipTest("%s: %s, too slow for the real-time playback checks (the checks above passed)" % (name, slow))
        if audio:
            self.assertGreaterEqual(a["readyState"], 2, "%s: the sound cannot play yet: %s" % (name, self.diag(r)))
        self.assertFalse(r["after"]["paused"], "%s is not playing: %s" % (name, self.diag(r)))
        self.assertGreater(r["advanced"], 0.5, "%s: currentTime did not advance (%.3f)" % (name, r["advanced"]))
        if audio:
            # picture follows the audio clock
            self.assertLess(abs(a["t"] - r["after"]["t"]), 0.3)
            self.check_start(name, r)
        return r

    @staticmethod
    def too_slow(r):
        """Why this browser cannot be watched in real time, or None. A 2-core runner drawing 1080p with a
        software GPU can take 10 s to get through the driver's 1.5 s window (the video plays on in real
        time meanwhile), or draw only a few frames in it; so can a 4-core CI runner (the Windows image drew
        1 frame in the window while the clock ran on). A player bug shows up on a normal machine: outside
        CI, on more than 2 cores, these checks always run."""
        ms = r.get("windowMs") or 0
        if ms > 3000:
            return "the click and the driver's 1.5 s playback window took %.1f s" % (ms / 1000)
        cores = os.cpu_count() or 1
        ci = bool(os.environ.get("CI"))
        if cores > 2 and not ci:
            return None
        where = "a %d-core %s" % (cores, "CI runner" if ci else "machine")
        n = len(r.get("startFrames") or [])
        if n < 5:
            return "the player drew %d frames in 1.5 s on %s" % (n, where)
        a = (r.get("after") or {}).get("audio") or {}
        if a and (a.get("readyState") or 0) < 2:
            return "the sound was still loading (readyState %s) after 1.5 s on %s" % (a.get("readyState"), where)
        return None

    @staticmethod
    def diag(r):
        """What the driver saw, for a failure message (a failure on a CI runner explains itself)."""
        info = r.get("info") or {}
        return json.dumps({"after": r.get("after"), "ui": r.get("ui"), "readyMs": r.get("readyMs"),
                           "advanced": r.get("advanced"), "windowMs": r.get("windowMs"), "frames": (r.get("startFrames") or [])[:12],
                           "duration": info.get("duration"), "fps": info.get("fps"), "seekFrom": r.get("seekFrom"),
                           "events": r.get("events"), "before": r.get("before")},
                          default=str)[:3000]

    def check_start(self, name, r):
        """From the click on, frames only move forward and never run ahead of the sound (the audio
        clock stands still for a moment after play(): the picture must wait for it)."""
        fr = r["startFrames"]
        # enough frames to judge their order: a 2-core CI runner drawing with a software GPU manages about
        # 10 in the 1.5 s window, a desktop 40 or more
        self.assertGreaterEqual(len(fr), 5, "%s drew only %d frames: %s" % (name, len(fr), self.diag(r)))
        fps = r["info"]["fps"]
        back = [(a[0], b[0]) for a, b in zip(fr, fr[1:]) if b[0] < a[0]]
        self.assertEqual(back, [], "%s: the picture stepped back while playing: %s" % (name, back[:5]))
        # 2.5 frames; on a machine with 2 cores or fewer the audio element's clock can update in coarse steps,
        # and between steps the player extrapolates it by at most 0.25 s (ElementSound.time in player.js)
        tol = 2.5 / fps if (os.cpu_count() or 1) > 2 else 0.25 + 1.0 / fps
        ahead = [(f, round(t, 3)) for f, t in fr if t is not None and f / fps - t > tol]
        self.assertEqual(ahead, [], "%s: the picture ran ahead of the sound (frame, audio time): %s" % (name, ahead[:5]))

    def check_frames(self, name):
        r = self.res[name]
        for key, snap_png in self.snaps[name].items():
            got = psnr(r["shots"][key], snap_png)
            self.assertGreaterEqual(got, PSNR_MIN, "%s frame at %ss differs from `showtime snap` (PSNR %.1f dB)" % (name, key, got))

    def test_film_score_mode(self):
        rep = self.rep["film"]
        self.assertEqual(rep["audio"]["mode"], "score")
        self.assertLess(rep["bytes"], 16 * MB)
        # a procedural film is tiny: runtime minified + unused parts left out + text gzip-packed, no poster image
        self.assertLess(rep["bytes"], 400 * 1024, "a score-only film should be a few hundred KB (%d)" % rep["bytes"])
        self.assertTrue(rep["minified"] and rep["compressed"])
        self.assertTrue(rep["unused_parts"], "the film template does not use every runtime part")
        self.assertEqual(rep["start"], "card")
        self.assertIsNotNone(rep["audio"]["lufs"])
        self.assertLess(abs(rep["audio"]["lufs"] - (-14)), 1.5)
        r = self.res["film"]
        self.assertTrue(r["before"]["card"], "no start screen")
        self.assertIn("Film Template", r.get("cardText") or "", "the start screen shows the title")
        self.assertIn("PLAY", (r.get("cardText") or "").upper())
        self.assertIn("0:12", r.get("cardText") or "", "the Play button says how long the film is")
        self.assertIn("SOUND ON", (r.get("cardText") or "").upper())
        self.assertRegex(r.get("cardFont") or "", "(?i)stp (inter|instrument)", "the start screen uses the film's own font")
        self.assertTrue(r.get("cardFaces"), "the film's font files did not reach the player")
        self.assertIn(r.get("cardPos"), ("bl", "tl", "br", "tr"))
        self.assertEqual(r["before"]["title"], "Film Template", "the page title is the project title")
        self.assertFalse(r["before"]["hosted"], "opened from disk is not a hosted frame")
        self.assertTrue(r["before"]["linkShown"])
        # still frames first: they do not depend on the machine's speed; then the real-time checks
        self.check_frames("film")
        self.check_common("film")

    def test_light_poster_deepens_the_scrim(self):
        """A bright poster frame under a dark film's scrim: the start screen switches to the deep scrim
        (data-dense), sized to the title block (--stp-sh), even with no text in the corners."""
        r = self.res["light"]
        self.assertTrue(r["before"]["card"], "no start screen")
        self.assertIn("Light Poster", r.get("cardText") or "")
        self.assertTrue(r.get("cardDense"), "a light poster under a dark scrim must get the deep scrim")
        self.assertRegex(r.get("cardSh") or "", r"^\d+(\.\d+)?%$")

    def test_film_keys(self):
        k = self.res["film"]["keys"]
        ch = {c["label"]: c["t"] for c in self.rep["film"]["chapter_list"]}
        self.assertTrue(k["pausedAfterK"], "k did not pause")
        self.assertAlmostEqual(k["digit3"], ch["Data"], delta=0.02, msg="3 = third chapter")
        self.assertAlmostEqual(k["right"], k["digit3"] + 1.0, delta=0.02, msg="right arrow = +1 s")
        self.assertAlmostEqual(k["shiftRight"], k["right"] + 1 / 30, delta=0.005, msg="shift+right = one frame")
        self.assertAlmostEqual(k["comma"], k["right"], delta=0.005, msg=", = one frame back")
        self.assertAlmostEqual(k["nextChapter"], ch["End card"], delta=0.02, msg="] = next chapter")
        self.assertAlmostEqual(k["prevChapter"], ch["Data"], delta=0.02, msg="[ at a chapter start = the chapter before")
        self.assertAlmostEqual(k["left"], k["prevChapter"] - 1.0, delta=0.02, msg="left arrow = -1 s")
        self.assertTrue(k["help"] and k["helpClosed"], "? shows the key map, Esc hides it")
        self.assertTrue(k["toast"], "c should say the link was copied (or show it)")
        self.assertTrue(k["link"]["url"].endswith("#t=12.3"), k["link"])
        self.assertTrue(k["link"]["full"])
        self.assertLess(k["restart"]["t"], 0.5, "r restarts from the beginning")
        self.assertFalse(k["restart"]["paused"], "r plays")
        self.assertTrue(k["muted"])

    def test_film_live_score(self):
        L = self.res["film"]["live"]
        self.assertEqual(L["kind"], "score")
        self.assertIsNotNone(L["firstPieceMs"])
        self.assertLess(L["firstPieceMs"], 4000, "the first piece of the score should be ready fast")
        # seek into the middle of a pad while playing: sound within a few frames of the new position
        self.assertIsNotNone(L["firstLoudMs"], "no sound after seeking into the pad: %s" % L["rmsAt"][:10])
        # 700 ms on a real machine; a CI runner's audio clock can stand still longer after the seek (the
        # Windows 11 on Arm runner, under x64 emulation, took 848 ms with the clock parked for 0.5 s), so CI
        # gets 1.5 s: a player that never resumes the sound still fails, and so does one that is slow here
        budget = 1500 if os.environ.get("CI") else 700
        self.assertLess(L["firstLoudMs"], budget, L["rmsAt"][:10])
        if os.environ.get("CI"):
            # a slow runner starts the clock late: judge it by how far it ran once the sound was back
            # (the Windows 11 on Arm runner ran 0.74 s in the sampled 0.9 s after a 0.85 s restart)
            ran_ms = L["rmsAt"][-1][0] - L["firstLoudMs"]
            self.assertGreater(ran_ms, 0, L["rmsAt"][-5:])
            self.assertGreaterEqual(L["rmsAt"][-1][2] - 4.4, 0.5 * ran_ms / 1000,
                                    "the audio clock did not run on after the seek: %s" % L["rmsAt"][-5:])
        else:
            self.assertGreaterEqual(L["rmsAt"][-1][2], 4.4 + 0.8, "the audio clock did not run on after the seek")
        # the stream (pieces rendered with pre-roll, seams, the seek) is the whole render, sample for sample
        v = L["verify"]
        self.assertGreater(v["seconds"], 11, v)
        self.assertLess(v["diffDb"], v["refDb"] - 40, "the streamed score differs from a whole render: %s" % v)
        self.assertGreaterEqual(len(L["seams"]), 2, "the score should stream in several pieces")

    def test_deep_links(self):
        r = self.res["link-t"]
        self.assertNotIn("fatal", r, r.get("fatal"))
        self.assertAlmostEqual(r["before"]["startTime"], 7.5, delta=0.01)
        self.assertIn("0:07", r.get("cardText") or "", "the start card says where it starts")
        self.assertFalse(r["before"]["started"])
        self.assertGreaterEqual(r["after"]["t"], 7.5, "#t=7.5 did not start there")
        self.assertLess(r["after"]["t"], 7.5 + 3)
        r2 = self.res["link-ch"]
        self.assertNotIn("fatal", r2, r2.get("fatal"))
        ch = {c["label"]: c["t"] for c in self.rep["film"]["chapter_list"]}
        self.assertAlmostEqual(r2["before"]["startTime"], ch["Data"], delta=0.01)
        self.assertGreaterEqual(r2["after"]["t"], ch["Data"])

    def test_replay_leaves_the_end_card_readable(self):
        """On the last frame the replay control is a small pill in the top-right corner, not a disc over the
        centre of the end card (where titles and taglines sit), and the dimming vignette is gone."""
        e = self.res["link-ch"].get("ended")
        self.assertIsNotNone(e, self.res["link-ch"].get("fatal"))
        self.assertTrue(e["ended"], "the film did not reach its end")
        self.assertEqual(e["label"], "Replay")
        self.assertIn("Replay", e["text"])
        self.assertNotEqual(e["display"], "none")
        bx, by, bw, bh = e["big"]
        hx, hy, hw, hh = e["holder"]
        self.assertGreater(bx, hx + hw * 0.6, "replay should sit at the right edge: %s in %s" % (e["big"], e["holder"]))
        self.assertLess(by + bh, hy + hh * 0.25, "replay should sit at the top: %s in %s" % (e["big"], e["holder"]))
        cx0, cy0, cx1, cy1 = hx + hw * 0.25, hy + hh * 0.25, hx + hw * 0.75, hy + hh * 0.75
        self.assertFalse(bx < cx1 and bx + bw > cx0 and by < cy1 and by + bh > cy0, "replay covers the centre of the frame")
        self.assertLess(e["vignette"], 0.05, "the end card should not be dimmed")

    def test_dom_embed_mode(self):
        rep = self.rep["dom"]
        self.assertEqual(rep["audio"]["mode"], "embed")
        self.assertEqual(rep["audio"]["codec"], "aac")
        self.assertLess(rep["bytes"], 16 * MB)
        self.assertGreaterEqual(rep["chapters"], 3)
        self.assertLess(abs(rep["audio"]["lufs"] - (-14)), 1.5)
        html = Path(rep["output"]).read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy", html)
        self.assertNotIn("http://127.0.0.1", html)
        self.check_frames("dom")   # before the real-time checks (which may skip)
        self.check_common("dom")
        # jump 5 s ahead while playing: after the jump the frames only move forward
        fr = self.res["dom"]["seekFrames"]
        target = int((self.res["dom"]["seekFrom"] + 5.0) * 30) - 3
        k = next((i for i, x in enumerate(fr) if x[0] >= target), None)
        self.assertIsNotNone(k, "the l key did not jump: %s; %s" % (fr[:10], self.diag(self.res["dom"])))
        after = [x[0] for x in fr[k:]]
        self.assertEqual(after, sorted(after), "dom: frames stepped back after a seek while playing: %s" % after[:12])
        self.assertGreater(len(set(after)), 10)

    def test_no_aac_browser(self):
        r = self.check_common("noaac", audio=False)
        self.assertIn("soundtrack", r["after"]["error"] or "")
        self.assertIn("No sound", r["ui"]["msg"])
        self.assertTrue(r["ui"]["muteDisabled"])

    def test_fixture_virtual_files(self):
        if not self.emoji_ok:
            self.skipTest("the fixture's emoji could not be installed (`showtime assets emoji 1f389` failed: offline?)")
        rep = self.rep["fixture"]
        self.assertEqual(rep["audio"]["mode"], "none")
        out = Path(rep["output"])
        self.assertEqual((out.parent.name, out.suffix), ("fixdir", ".html"), "-o folder/ should write inside it: %s" % out)
        self.check_frames("fixture")   # before the real-time checks (which may skip)
        self.check_common("fixture", audio=False)
        self.assertNotIn("/data/unused.bin", [x["path"] for x in rep["largest"]], "a file named only in comments was packed")

    def test_short_folder_file_and_http(self):
        rep = self.rep["short"]
        self.assertTrue(rep["folder"])
        out = Path(rep["output"]).parent
        self.assertTrue((out / "assets" / "vfs.js").exists())
        media = list((out / "assets" / "media").rglob("*.m4a"))
        self.assertTrue(media, "the soundtrack should be a real file in --folder mode")
        self.assertLess((out / "index.html").stat().st_size, 300 * 1024, "index.html should only hold the player and page")
        self.check_common("short-file", audio="element")
        self.check_common("short-http")
        self.assertEqual(self.res["short-http"]["info"]["height"], 1920)

    def test_sandboxed_host(self):
        r = self.check_common("sandboxed")
        self.assertTrue(r["before"]["hosted"], "a sandboxed frame should be detected as a host")
        self.assertFalse(r["before"]["linkShown"], "no 'copy link' inside a host's frame")

    def test_artifact_viewer_csp(self):
        # the bug this guards: under a host CSP without blob: stylesheets and fonts, the theme and every
        # font vanished and the stage text fell back to a 16 px serif in a 1920x1080 frame
        r = self.check_common("artifact", audio=False)
        st = r.get("stageText") or {}
        kicker, hero = st.get(".kicker"), st.get("#open h1")
        self.assertIsNotNone(kicker, "no kicker in the stage: %r" % st)
        self.assertIsNotNone(hero, "no title in the stage: %r" % st)
        self.assertEqual(kicker["family"], "IBM Plex Mono", kicker)
        self.assertEqual(hero["family"], "Instrument Serif", hero)
        self.assertTrue(kicker["loaded"] and hero["loaded"], "the theme's fonts did not load: %r" % st)
        self.assertEqual(kicker["frameH"], 1080)
        self.assertGreater(kicker["h"] / kicker["frameH"], 0.02, "kicker too small: %r" % kicker)
        self.assertGreater(hero["h"] / hero["frameH"], 0.08, "title too small: %r" % hero)
        self.assertGreater(hero["fontSize"], 100, hero)
        self.assertEqual(r["warnings"], [], "an export that loads fully reports nothing")

    def test_broken_font_is_reported(self):
        r = self.res["badfont"]
        self.assertNotIn("fatal", r, r.get("fatal"))
        self.assertEqual(r["errors"], [], r["errors"][:5])
        self.assertTrue(any("Broken Face" in w for w in r.get("warnings") or []), "no warning: %r" % r.get("warnings"))
        t = (r.get("stageText") or {}).get("#t")
        self.assertIsNotNone(t)
        self.assertEqual(t["family"], "Broken Face")
        self.assertGreater(t["h"], 30, "the fallback font must keep the text's size: %r" % t)

    def test_phone_upright(self):
        r = self.res["phone"]
        self.assertNotIn("fatal", r, r.get("fatal"))
        L = r["layout"]
        self.assertEqual(L["mode"], "stacked")
        self.assertEqual(L["holder"][2], L["vw"], "a 16:9 film is full width on a phone held upright: %s" % L)
        self.assertEqual(L["info"], "flex")
        self.assertGreaterEqual(L["chapters"], 3, "the chapters are listed under the picture")
        self.assertEqual(L["pageBg"], L["stpBg"])
        self.assertNotEqual(L["stpBg"], "rgb(0, 0, 0)", "the page around the picture is the film's ground, not black")
        self.assertGreater(L["bar"][1] + L["bar"][3], L["vh"] - 2, "the controls sit at the bottom (thumb reach)")
        # visible (read while its fade-in may still be finishing on a loaded machine)
        self.assertGreater(float(L["barOpacity"]), 0.9, "the controls stay shown on a phone")
        self.assertGreater(L["go"][1], L["holder"][1] + L["holder"][3] - 1, "the Play button is under the picture, not over it")
        self.assertGreaterEqual(L["go"][3], 44, "touch target")
        self.assertEqual(r["console"], [])
        self.assertEqual(r["errors"], [])
        self.assertFalse(r["after"]["paused"], "the Play button did not start it")
        self.assertGreater(r["advanced"], 0.5)

    def test_target_artifact(self):
        out = TMP / "out" / "artifact.html"
        cp = showtime("export", "html", self.fixture, "-o", out, "--target", "artifact", "--json", "-q")
        rep = json.loads(cp.stdout)
        self.assertEqual(rep["target"], "artifact")
        self.assertIn('"host":"artifact"', out.read_text(encoding="utf-8"))
        cp = showtime("export", "html", self.fixture, "-o", TMP / "out" / "af", "--target", "artifact", "--folder", check=False)
        self.assertNotEqual(cp.returncode, 0, "--target artifact is one file")

    def test_controls_none_autoplay_muted(self):
        r = self.res["bare"]
        self.assertEqual(r["before"]["bar"], "none")
        self.assertNotIn("fatal", r, r.get("fatal"))
        self.assertEqual(r["requests"], [])
        self.assertEqual(r["console"], [])
        self.assertFalse(r["after"]["paused"], "--autoplay-muted did not start playing")
        self.assertTrue(r["after"]["muted"])
        self.assertGreater(r["advanced"], 0.5)
        html = Path(self.rep["bare"]["output"]).read_text(encoding="utf-8")
        self.assertIn('"controls":"none"', html)
        self.assertIn('"loop":true', html)

    def test_job_and_output_name(self):
        """12.8: --job J -o name.html writes that name inside the job folder (was: "pass either -o or --job")."""
        job = TMP / "job-embed"
        job.mkdir(exist_ok=True)
        (job / "job.json").write_text(json.dumps({"schema": "showtime.job/1", "slug": "job-embed"}), encoding="utf-8")
        cp = showtime("export", "html", self.fixture, "--job", job, "-o", "embed.html", "--json", "-q")
        rep = json.loads(cp.stdout)
        self.assertEqual(Path(rep["output"]).resolve(), (job / "embed.html").resolve())
        self.assertTrue((job / "embed.html").is_file())
        cp = showtime("export", "html", self.fixture, "--job", job, "-o", TMP / "elsewhere" / "x.html", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("inside the job folder", cp.stderr)

    def test_audio_file(self):
        """--audio-file embeds exactly the given sound (a shipped MP4's soundtrack) instead of the score and
        the mix: one command for a project whose voice WAVs are gone."""
        from st import ff
        src = TMP / "tone.wav"
        subprocess.run([ff.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                        "sine=f=440:d=2", "-ac", "2", str(src)], check=True, timeout=60)
        cp = showtime("export", "html", self.fixture, "-o", TMP / "out" / "given-audio.html", "--audio-file", src, "--json", "-q")
        rep = json.loads(cp.stdout)
        self.assertEqual(rep["audio"]["mode"], "embed")
        self.assertEqual(rep["audio"]["sources"], ["tone.wav"])
        bad = showtime("export", "html", self.fixture, "-o", TMP / "out" / "x.html", "--audio-file", src, "--audio", "score", check=False)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("--audio-file", bad.stderr)

    def test_player_language(self):
        """--lang (default: the project's language) sets <html lang> and the player's own words: a Spanish
        page no longer shows "Play" and "Sound on"."""
        out = TMP / "out" / "es.html"
        showtime("export", "html", self.fixture, "-o", out, "--lang", "es", "--audio", "none", "-q")
        self.assertIn('<html lang="es"', out.read_text(encoding="utf-8")[:400])
        en = TMP / "out" / "en.html"
        showtime("export", "html", self.fixture, "-o", en, "--audio", "none", "-q")
        r = drive([{"name": "es", "url": out.as_uri(), "width": 1280, "height": 800, "card": True, "noClick": True},
                   {"name": "en", "url": en.as_uri(), "width": 1280, "height": 800, "card": True, "noClick": True}])
        self.assertIn("Reproducir", r["es"]["cardText"])
        self.assertNotIn("Play", r["es"]["cardText"])
        self.assertIn("Play", r["en"]["cardText"])
        bad = showtime("export", "html", self.fixture, "-o", TMP / "out" / "bad.html", "--lang", "español", check=False)
        self.assertNotEqual(bad.returncode, 0)

    def test_size_budget(self):
        cp = showtime("export", "html", self.fixture, "-o", TMP / "out" / "tiny.html", "--max-mb", "0.05", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("over the 0.05 MB limit", cp.stderr)
        self.assertIn("largest:", cp.stderr)
        self.assertIn("fix:", cp.stderr)
        self.assertIn(" player ", cp.stderr, "the breakdown should count the player and stage runtime")
        self.assertNotIn("--audio score", cp.stderr, "no score here: --audio score is not a way down")
        self.assertFalse((TMP / "out" / "tiny.html").exists())

    def test_fit_footage_under_the_limit(self):
        """A single file over --max-mb because of an embedded clip: the clip is re-encoded for this export only
        (2-pass, the bitrate that fits), the file lands under the limit and the project's clip is untouched;
        --fit off stops with the size breakdown instead."""
        d = TMP / "fitclip"
        (d / "media").mkdir(parents=True)
        clip = d / "media" / "clip.mp4"
        subprocess.run([ff.ffmpeg_path(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=6",
                        "-vf", "noise=alls=18:allf=t", "-c:v", "libx264", "-b:v", "3500k", "-pix_fmt", "yuv420p", "-an",
                        str(clip)], check=True, timeout=180)
        before = clip.read_bytes()
        (d / "showtime.json").write_text(json.dumps({"width": 640, "height": 360, "fps": 30, "duration": 6,
                                                     "title": "Fit clip"}), encoding="utf-8")
        (d / "index.html").write_text(
            '<!doctype html><html><head><script src="/_st/stage.js"></script><style>body{margin:0;background:#000}'
            'video{width:640px;height:360px;display:block}</style></head><body>'
            '<video src="media/clip.mp4" muted playsinline data-start="0" data-dur="6"></video></body></html>', encoding="utf-8")
        self.assertGreater(len(before), 2 * MB)
        r = export(d, TMP / "out" / "fit.html", "--max-mb", "2", "--audio", "none")
        self.assertLessEqual(r["bytes"], 2 * MB)
        self.assertEqual([x["path"] for x in r["footage_refit"]], ["/media/clip.mp4"])
        self.assertLess(r["footage_refit"][0]["after"], r["footage_refit"][0]["before"])
        self.assertTrue(any("re-encoded for this export only" in w for w in r["warnings"]), r["warnings"])
        self.assertEqual(clip.read_bytes(), before, "the project's clip must not change")
        cp = showtime("export", "html", d, "-o", TMP / "out" / "nofit.html", "--max-mb", "2", "--fit", "off", "--audio", "none",
                      check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("over the 2 MB limit", cp.stderr)
        self.assertIn("--fit auto", cp.stderr)
        self.assertFalse((TMP / "out" / "nofit.html").exists())

    def test_zz_timing(self):
        print("\n  exports took %.1fs; film %s, launch %s, short folder %s" % (
            self.export_s, fmt(self.rep["film"]["bytes"]), fmt(self.rep["dom"]["bytes"]), fmt(self.rep["short"]["bytes"])),
            file=sys.stderr)


def fmt(n):
    return "%.2f MB" % (n / MB)


# Range links (#t=10-20): each case opens the export from disk and plays a scenario.
RANGE_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><script src="/_st/stage.js"></script>
<style>body{margin:0;background:#101418;color:#fff;font:700 60px sans-serif}#n{position:absolute;left:40px;top:40px}</style>
</head><body><div id="n">0</div><script>ST.onSeek(function (t, f) { document.getElementById('n').textContent = 'frame ' + f; });</script>
</body></html>
"""
RANGE_DRIVER = r"""
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const SKILL = process.argv[2];
const job = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const { launchBrowser } = await import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'chrome.mjs')).href);
const { browser } = await launchBrowser({ gpu: 'auto', headless: true, args: ['--proxy-server=http://127.0.0.1:9'] });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const out = [];
try {
  for (const c of job.cases) {
    const ctx = await browser.newContext({ viewport: { width: 960, height: 540 }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    const r = { name: c.name, errors: [], requests: [], s: {} };
    page.on('pageerror', (e) => r.errors.push(String(e.message || e).slice(0, 300)));
    page.on('request', (q) => { const u = q.url(); if (!/^(data|blob|about|file):/.test(u)) r.requests.push(u); });
    const P = (fn, arg) => page.evaluate(fn, arg);
    const waitFor = async (fn, arg, ms = 20000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await P(fn, arg)) return true; await sleep(30); } return false; };
    const st = () => P(() => { const p = window.showtimePlayer, band = document.querySelector('.stp-range');
      return { t: p.currentTime, paused: p.paused, ended: p.ended, range: p.range, loop: p.loop, question: p.question,
        loopPressed: document.querySelector('.stp-loop').getAttribute('aria-pressed'),
        band: band && !band.hidden ? { left: parseFloat(band.style.left), width: parseFloat(band.style.width) } : null,
        from: (document.querySelector('.stp-from') || {}).textContent || '' }; });
    try {
      await page.goto(pathToFileURL(job.file).href + (c.hash || ''), { waitUntil: 'load', timeout: 60000 });
      await P(() => window.showtimePlayer.ready);
      await P(() => { window.__ev = []; const p = window.showtimePlayer; window.__maxT = 0;
        for (const n of ['loop', 'question', 'answer', 'continue', 'range', 'rangeend', 'seek']) p.on(n, (d) => window.__ev.push([n, d && d.id ? d.id : (n === 'seek' ? +(+d).toFixed(3) : d), +p.currentTime.toFixed(3)]));
        p.on('frame', () => { if (p.range && p.currentTime > window.__maxT) window.__maxT = p.currentTime; }); });
      r.s.before = await st();
      r.s.startTime = await P(() => window.showtimePlayer.startTime);
      if (c.kind === 'loop') {
        await page.click('.stp-go');
        r.s.asked = await waitFor(() => window.showtimePlayer.question === 'q1');
        r.s.atAsk = await st();
        if (c.pass) await page.keyboard.press('k');                  // play through it: passed, asked again next loop
        else { await page.keyboard.press('a'); await waitFor(() => !!document.querySelector('.stp-q-reply')); await page.keyboard.press('Enter'); }
        r.s.looped = await waitFor(() => window.__ev.filter((e) => e[0] === 'loop').length >= 1);
        if (c.pass) r.s.askedAgain = await waitFor(() => window.__ev.filter((e) => e[0] === 'question').length >= 2);
        else await sleep(1500);
        r.s.after = await st();
        r.s.maxT = await P(() => window.__maxT);
        // seeking outside the range leaves it, and the loop button goes back to how it was
        await P(() => { window.showtimePlayer.pause(); window.showtimePlayer.currentTime = 7.5; });
        r.s.outside = await st();
      } else if (c.kind === 'stop') {
        await page.click('.stp-go');
        await waitFor(() => !window.showtimePlayer.paused);
        await page.mouse.move(480, 500);
        await page.click('.stp-loop');                                  // loop off: play stops at the end of the range
        r.s.loopOff = await st();
        r.s.stopped = await waitFor(() => window.showtimePlayer.paused, null, 15000);
        r.s.atStop = await st();
        await P(() => window.showtimePlayer.play());
        await sleep(200);
        r.s.again = await st();
      } else if (c.kind === 'pick') {
        await page.click('.stp-go');
        await waitFor(() => !window.showtimePlayer.paused);
        await page.keyboard.press('k');
        await page.mouse.move(480, 300);
        const b = await P(() => { const x = document.querySelector('.stp-scrub').getBoundingClientRect(); return [x.left, x.top + x.height / 2, x.width]; });
        await page.keyboard.down('Shift');
        await page.mouse.move(b[0] + 0.2 * b[2], b[1]);
        await page.mouse.down();
        await page.mouse.move(b[0] + 0.3 * b[2], b[1], { steps: 3 });
        await page.mouse.move(b[0] + 0.4 * b[2], b[1], { steps: 3 });
        await page.mouse.up();
        await page.keyboard.up('Shift');
        r.s.picked = await st();
        r.s.link = await P(() => window.showtimePlayer.link());
        await P(() => { window.__copied = null; Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: (t) => { window.__copied = t; return Promise.resolve(); } } }); });
        await page.keyboard.press('c');
        await sleep(100);
        r.s.copied = await P(() => window.__copied);
        r.s.toast = await P(() => document.querySelector('.stp-toast').textContent);
        await page.keyboard.press('Escape');
        r.s.cleared = await st();
        // a link changed in the address bar while it plays; the API
        await P(() => { location.hash = '#t=6-8'; });
        await waitFor(() => !!window.showtimePlayer.range);
        r.s.hashed = await st();
        r.s.api = await P(() => { const p = window.showtimePlayer; const set = p.setRange(1, 2); return { set, link: p.link().hash, linkRange: p.linkRange(3, 4.25).hash, cleared: p.setRange(null), range: p.range }; });
        r.s.help = await P(() => document.querySelector('.stp-help').textContent);
      }
      r.events = await P(() => window.__ev);
    } catch (e) { r.fatal = String(e.message || e).slice(0, 500); }
    out.push(r);
    await ctx.close();
  }
} finally { await browser.close(); }
fs.writeFileSync(job.result, JSON.stringify(out, null, 2));
"""


@needs_listen
@unittest.skipIf(FAST, "needs a browser")
class RangeLinkTest(unittest.TestCase):
    """#t=2-5 (and #t=0:02-0:05): the player starts at 2 s, says so on the start card, shows the range on the
    scrubber, loops back at 5 s (never shows a later frame), and still asks a question inside the range (again
    on every loop until it is answered); with the loop button off it stops at the end of the range and plays it
    again from its start; seeking outside leaves the range; shift + drag on the scrubber picks one, `c` copies
    its link, Esc clears it; a hash changed while playing and the API (range, setRange, link, linkRange)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-range-test-"))
        proj = cls.tmp / "range"
        proj.mkdir()
        (proj / "showtime.json").write_text(json.dumps({
            "title": "Range links", "width": 640, "height": 360, "fps": 30, "duration": 9, "background": "#101418",
            "questions": [{"id": "q1", "at": 3.0, "think": 1.0, "prompt": "Which one?", "choices": ["This", "That"], "answer": 0}]}),
            encoding="utf-8")
        (proj / "index.html").write_text(RANGE_PAGE, encoding="utf-8")
        cls.rep = export(proj, cls.tmp / "out" / "range.html", "--audio", "none")
        job = cls.tmp / "job.json"
        res = cls.tmp / "res.json"
        f = cls.rep["output"]
        job.write_text(json.dumps({"file": f, "result": str(res), "cases": [
            {"name": "answered", "kind": "loop", "hash": "#t=2-5"},
            {"name": "passed", "kind": "loop", "hash": "#t=0:02-0:05", "pass": True},
            {"name": "stop", "kind": "stop", "hash": "#t=6-7.5"},
            {"name": "pick", "kind": "pick"},
        ]}), encoding="utf-8")
        drv = cls.tmp / "range-driver.mjs"
        drv.write_text(RANGE_DRIVER, encoding="utf-8")
        node = shutil.which("node", path=ENV.get("PATH")) or "node"
        cp = subprocess.run([node, str(drv), str(SKILL), str(job)], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace", timeout=300)
        assert cp.returncode == 0 and res.exists(), "driver failed:\n%s\n%s" % (cp.stdout[-2000:], cp.stderr[-3000:])
        cls.res = {r["name"]: r for r in json.loads(res.read_text(encoding="utf-8"))}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def ok(self, name):
        r = self.res[name]
        self.assertNotIn("fatal", r, json.dumps(r, indent=1)[:3000])
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["requests"], [])
        return r["s"]

    def test_range_loops_and_asks(self):
        for name in ("answered", "passed"):
            s = self.ok(name)
            b = s["before"]
            self.assertEqual(b["range"], {"a": 2, "b": 5}, name)
            self.assertAlmostEqual(s["startTime"], 2.0, places=3)
            self.assertEqual((b["loop"], b["loopPressed"]), (True, "true"))
            self.assertIn("0:02 – 0:05", b["from"])                       # the start card says what plays
            self.assertAlmostEqual(b["band"]["left"], 100 * 2 / 9, delta=0.1)
            self.assertAlmostEqual(b["band"]["width"], 100 * 3 / 9, delta=0.1)
            self.assertTrue(s["asked"], name)                               # the question inside the range asks
            self.assertAlmostEqual(s["atAsk"]["t"], 3.0, places=3)
            self.assertTrue(s["looped"], name)
            self.assertLess(s["maxT"], 5.0 + 1e-6, "a frame after the range was shown")
            self.assertEqual(s["after"]["range"], {"a": 2, "b": 5})
            self.assertGreaterEqual(s["after"]["t"], 2.0 - 1e-6)
            self.assertIsNone(s["outside"]["range"])                        # a seek outside leaves the range
            self.assertFalse(s["outside"]["loop"])
            loops = [e for e in self.res[name]["events"] if e[0] == "loop"]
            self.assertTrue(loops)
        asked = lambda n: [e for e in self.res[n]["events"] if e[0] == "question"]  # noqa: E731
        self.assertEqual(len(asked("answered")), 1)                         # answered: not asked again
        self.assertTrue(self.res["passed"]["s"]["askedAgain"])              # passed: asked again on the next loop

    def test_loop_off_stops_at_the_end(self):
        s = self.ok("stop")
        self.assertEqual(s["before"]["range"], {"a": 6, "b": 7.5})
        self.assertFalse(s["loopOff"]["loop"])
        self.assertTrue(s["stopped"])
        st = s["atStop"]
        self.assertTrue(st["paused"])
        self.assertFalse(st["ended"])
        self.assertAlmostEqual(st["t"], 7.5 - 1 / 30, delta=0.002)          # the last frame of the range
        self.assertEqual(st["range"], {"a": 6, "b": 7.5})
        self.assertIn("rangeend", [e[0] for e in self.res["stop"]["events"]])
        self.assertLess(abs(s["again"]["t"] - 6.0), 0.4)                     # play again: from the start of the range

    def test_pick_copy_clear(self):
        s = self.ok("pick")
        p = s["picked"]["range"]
        self.assertIsNotNone(p, s)
        self.assertAlmostEqual(p["a"], 1.8, delta=0.1)
        self.assertAlmostEqual(p["b"], 3.6, delta=0.1)
        self.assertAlmostEqual(s["picked"]["t"], p["a"], delta=0.05)
        self.assertTrue(s["picked"]["loop"])
        self.assertRegex(s["link"]["hash"], r"^#t=\d+(\.\d)?-\d+(\.\d)?$")
        self.assertTrue(s["copied"].endswith(s["link"]["hash"]), (s["copied"], s["link"]))
        self.assertIn("0:01 – 0:03", s["toast"])
        self.assertIsNone(s["cleared"]["range"])                             # Esc
        self.assertEqual(s["hashed"]["range"], {"a": 6, "b": 8})
        self.assertAlmostEqual(s["hashed"]["t"], 6.0, delta=0.4)
        a = s["api"]
        self.assertEqual(a["set"], {"a": 1, "b": 2})
        self.assertEqual(a["link"], "#t=1-2")
        self.assertEqual(a["linkRange"], "#t=3-4.3")
        self.assertIsNone(a["cleared"])
        self.assertIsNone(a["range"])
        self.assertIn("Shift + drag", s["help"])
        self.assertIn("#t=1:05-1:20", s["help"])


class DeliverExportsTest(unittest.TestCase):
    """`showtime deliver exports` arguments (batch 2): a small master is never inflated toward a size cap,
    a bare --max-mb leaves the upload platforms alone (per-target caps with target:MB), x/linkedin keep a
    1:1 master's aspect, and the job's loudness target wins over the platform's -14 LUFS."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-deliver-test-"))
        cls.src = cls.tmp / "job" / "final.mp4"
        cls.src.parent.mkdir(parents=True)
        # a 1:1, mostly static 3 s master with a quiet tone: small (about 0.1-0.3 MB)
        ff.run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=s=540x540:r=30:d=3", "-f", "lavfi", "-i",
                       "sine=f=330:d=3:sample_rate=48000", "-vf", "boxblur=8", "-c:v", "libx264", "-crf", "30",
                       "-pix_fmt", "yuv420p", "-af", "volume=-20dB", "-c:a", "aac", "-shortest", str(cls.src)])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(str(cls.tmp), ignore_errors=True)

    def run_exports(self, *args):
        cp = showtime("deliver", "exports", self.src, "--json", *args)
        return json.loads(cp.stdout)["exports"]

    def test_caps_and_aspect(self):
        from st.deliver import exports as X
        bare, per = X.parse_max_mb("20,shorts:19")
        self.assertEqual((bare, per), (20.0, {"shorts": 19.0}))
        names = ["youtube", "original"]
        self.assertEqual(X.cap_for(X.TARGETS["youtube"], 20.0, {}, names), (None, False), "youtube is not capped")
        self.assertEqual(X.cap_for(X.TARGETS["original"], 20.0, {}, names), (20.0, True))
        self.assertEqual(X.cap_for(X.TARGETS["shorts"], 19.0, {}, ["shorts"]), (19.0, True),
                         "with only platform targets, a bare cap applies to them")
        self.assertEqual(X.native_size(1080, 1080, X.TARGETS["x"]), (1080, 1080))
        self.assertIsNone(X.native_size(1080, 1920, X.TARGETS["linkedin"]))
        self.assertIsNone(X.native_size(1080, 1080, X.TARGETS["youtube"]))
        master = self.src.stat().st_size
        web = self.run_exports("--targets", "web", "--out-dir", self.tmp / "web")[0]
        self.assertLessEqual(web["size_bytes"], master * 1.5 + 50_000, "a small master was inflated toward the cap")
        self.assertTrue(any("already small" in n for n in web["notes"]), web["notes"])
        x = self.run_exports("--targets", "x", "--preview", "--out-dir", self.tmp / "x")[0]
        self.assertEqual((x["width"], x["height"]), (540, 540))
        self.assertTrue(any("kept the master" in n for n in x["notes"]))
        xb = self.run_exports("--targets", "x", "--fit", "pad", "--preview", "--out-dir", self.tmp / "xb")[0]
        self.assertEqual((xb["width"], xb["height"]), (1920, 1080))
        cp = showtime("deliver", "exports", self.src, "--targets", "youtube", "--max-mb", "reels:5", check=False)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("not in --targets", cp.stderr)

    def test_job_loudness(self):
        from st.deliver import exports as X
        job = self.src.parent
        (job / "job.json").write_text(json.dumps({"qa_files": {str(self.src.resolve()): {"verdict": "PASS", "lufs": -16}}}),
                                      encoding="utf-8")
        self.assertEqual(X.job_loudness(self.src)[0], -16.0)
        r = self.run_exports("--targets", "youtube", "--preview", "--out-dir", self.tmp / "yt")[0]
        self.assertAlmostEqual(r["loudness"]["output_lufs"], -16.0, delta=1.0)
        self.assertEqual(r["loudness"]["target"], -16.0)
        self.assertTrue(any("-16.0 LUFS" in n for n in r["notes"]), r["notes"])
        r = self.run_exports("--targets", "youtube", "--preview", "--lufs", "-14", "--out-dir", self.tmp / "yt2")[0]
        self.assertAlmostEqual(r["loudness"]["output_lufs"], -14.0, delta=1.0)


# collect.mjs against a server whose kept-alive sockets die (what minifying a large script between two
# batches of requests did to the export's own server), and the share-tag helpers (share.mjs).
COLLECT_DRIVER = r"""
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const SKILL = process.argv[2], TMPD = process.argv[3];
const imp = (p) => import(pathToFileURL(path.join(SKILL, 'scripts', 'lib', 'export', p)).href);
const { collectFiles, fetchFile } = await imp('collect.mjs');
const S = await imp('share.mjs');
const out = {};
// any second request on a connection is dropped without an answer; /data/flaky.json loses its first one too
const perSock = new WeakMap();
const drops = { '/data/flaky.json': 1 };
const srv = http.createServer((req, res) => {
  const n = (perSock.get(req.socket) || 0) + 1; perSock.set(req.socket, n);
  const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  if (n > 1 || drops[p]) { if (drops[p]) drops[p]--; req.socket.destroy(); return; }
  const js = (t) => { res.writeHead(200, { 'content-type': 'text/javascript' }); res.end(t); };
  const m = /^\/scenes\/s(\d+)\.js$/.exec(p);
  if (p === '/main.js') return js(Array.from({ length: 40 }, (_, i) => `import './scenes/s${i}.js';`).join('\n') + "\nfetch('data/flaky.json'); new Audio('sfx/click.wav');");
  if (m) return js(`export const s${m[1]} = ${m[1]};`);
  if (p === '/data/flaky.json') { res.writeHead(200, { 'content-type': 'application/json' }); return res.end('{"file": "../voice/vo.wav", "click": "../sfx/click.wav"}'); }
  if (/\.wav$/.test(p)) { res.writeHead(200, { 'content-type': 'audio/wav' }); return res.end(Buffer.alloc(1000)); }
  res.writeHead(404); res.end();
});
await new Promise((r) => srv.listen(0, '127.0.0.1', r));
const base = `http://127.0.0.1:${srv.address().port}`;
const r = await collectFiles({ serverUrl: base, pagePath: '/index.html', pageHtml: '<script type="module" src="main.js"></script>',
  requests: ['/main.js', '/data/flaky.json', '/sfx/click.wav', '/gone.js'], allFonts: true, fetchOptions: { delayMs: 5 } });
out.collect = { files: [...r.files.keys()].sort(), failures: r.failures };
out.dead = await fetchFile('http://127.0.0.1:9', '/x.js', { tries: 2, delayMs: 5 });
srv.close();
// share tags
const poster = Buffer.from('JPEG');
const fresh = (f) => f;
fs.writeFileSync(path.join(TMPD, 'card.png'), 'PNG');
const cfg = { title: 'T', share: { url: 'https://example.org/films/launch', description: 'A <b>"quoted"</b> one' } };
out.folderUrl = S.resolveShare({ cfg, folder: true, out: path.join(TMPD, 'site'), poster, width: 1920, height: 1080, fresh });
out.folderNoUrl = S.resolveShare({ cfg: {}, folder: true, out: path.join(TMPD, 'site'), poster, width: 1920, height: 1080, fresh });
out.fileUrl = S.resolveShare({ cfg: {}, flags: { url: 'https://example.org/v/launch.html' }, folder: false, out: path.join(TMPD, 'launch.html'), poster, width: 1280, height: 720, fresh });
out.fileNoUrl = S.resolveShare({ cfg: {}, folder: false, out: path.join(TMPD, 'launch.html'), poster, fresh });
out.localImage = S.resolveShare({ cfg: { share: { image: 'card.png' } }, flags: { url: 'https://example.org/v/' }, folder: true, out: path.join(TMPD, 'site'), dirs: [TMPD], poster, fresh });
out.remoteImage = S.resolveShare({ cfg: {}, flags: { image: 'https://cdn.example.org/c.jpg' }, folder: false, out: path.join(TMPD, 'a.html'), poster, fresh });
try { S.resolveShare({ cfg: {}, flags: { url: 'example.org/x' } }); out.badUrl = 'accepted'; } catch (e) { out.badUrl = e.user ? e.message : 'not a user error'; }
for (const k of ['folderUrl', 'folderNoUrl', 'fileUrl', 'fileNoUrl', 'localImage', 'remoteImage']) {
  const v = out[k];
  out[k] = { ...v, files: v.files.map((f) => f.rel), beside: v.beside ? path.basename(v.beside.file) : null };
}
out.meta = S.shareMeta({ title: 'A & B', ...S.resolveShare({ cfg, folder: true, out: 'x', poster, width: 10, height: 20 }) });
out.titles = ['Project', 'project', 'Untitled', 'Film Template', 'A telescope made of ice', 'Projections'].map(S.genericTitle);
out.chapters = [
  [{ t: 0, label: 'Shot 1' }, { t: 3, label: 'Shot 2' }, { t: 6, label: 'Shot 3' }],
  [{ t: 0, label: 'Intro' }, { t: 3, label: 'Scene 2' }, { t: 6, label: 'How it works' }],
  [{ t: 0, label: '' }, { t: 3, label: 'S 2' }],
  [{ t: 0, label: 'Shot 1' }],
].map(S.genericChapters);
console.log(JSON.stringify(out));
"""

SHARE_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><script src="/_st/stage.js"></script>
<style>body{margin:0;background:#101418;color:#fff;font:700 40px sans-serif}section{position:absolute;inset:0;padding:40px}</style>
</head><body>
<section id="shot-1" data-start="0" data-dur="1">One</section>
<section id="shot-2" data-start="#shot-1" data-dur="1">Two</section>
<script>fetch('data/timeline.json').then(function (r) { return r.json(); }).then(function (j) { document.body.dataset.t = j.title; });</script>
</body></html>
"""


@needs_listen
class ExportFilesTest(unittest.TestCase):
    """Every file the page needs is packed or the export stops; sound files only data names stay out;
    link-preview tags; .nojekyll in a folder."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="st-export-files-"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def project(self, name, cfg, html, files=None):
        d = self.tmp / name
        d.mkdir(parents=True)
        (d / "showtime.json").write_text(json.dumps(dict({"width": 640, "height": 360, "fps": 30, "duration": 2}, **cfg)),
                                         encoding="utf-8")
        (d / "index.html").write_text(html, encoding="utf-8")
        for rel, data in (files or {}).items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return d

    def test_collect_and_share_helpers(self):
        drv = self.tmp / "collect.mjs"
        drv.write_text(COLLECT_DRIVER, encoding="utf-8")
        node = shutil.which("node", path=ENV.get("PATH")) or "node"
        cp = subprocess.run([node, str(drv), str(SKILL), str(self.tmp)], env=ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace", timeout=120)
        self.assertEqual(cp.returncode, 0, cp.stderr[-3000:])
        r = json.loads(cp.stdout)
        files = r["collect"]["files"]
        # dead keep-alive sockets and a dropped first answer: every file arrives (the old code lost a batch of 16)
        self.assertEqual(len([f for f in files if f.startswith("/scenes/")]), 40, files)
        self.assertIn("/data/flaky.json", files)
        # a sound the page plays is packed; one that only a data file names is not
        self.assertIn("/sfx/click.wav", files)
        self.assertNotIn("/voice/vo.wav", files)
        self.assertEqual([(f["path"], f["status"]) for f in r["collect"]["failures"]], [("/gone.js", 404)])
        self.assertEqual(r["dead"]["status"], 0)
        self.assertTrue(r["dead"]["err"])
        # share tags: a folder with a page URL gets the poster as an absolute image
        fu = r["folderUrl"]
        self.assertEqual(fu["image"]["href"], "https://example.org/films/launch/assets/poster.jpg")
        self.assertEqual(fu["files"], ["assets/poster.jpg"])
        self.assertEqual(fu["card"], "summary_large_image")
        self.assertEqual(fu["description"], 'A <b>"quoted"</b> one')
        # without a URL the image stays relative, and the export says previews need an absolute one
        self.assertEqual(r["folderNoUrl"]["image"]["href"], "assets/poster.jpg")
        self.assertTrue(any("absolute" in n for n in r["folderNoUrl"]["notes"]), r["folderNoUrl"]["notes"])
        # one file with a URL: the poster beside it, resolved against the page's folder
        self.assertEqual(r["fileUrl"]["beside"], "launch.share.jpg")
        self.assertEqual(r["fileUrl"]["image"]["href"], "https://example.org/v/launch.share.jpg")
        # one file without a URL: no image (data: URIs are no use to link previews), a summary card
        self.assertIsNone(r["fileNoUrl"]["image"])
        self.assertEqual(r["fileNoUrl"]["card"], "summary")
        self.assertEqual(r["localImage"]["files"], ["assets/share.png"])
        self.assertEqual(r["localImage"]["image"]["href"], "https://example.org/v/assets/share.png")
        self.assertEqual(r["remoteImage"]["image"]["href"], "https://cdn.example.org/c.jpg")
        self.assertIn("https://", r["badUrl"])
        meta = r["meta"]
        for tag in ('property="og:title" content="A &amp; B"', 'property="og:url" content="https://example.org/films/launch"',
                    'property="og:description" content="A &lt;b&gt;&quot;quoted&quot;&lt;/b&gt; one"',
                    'property="og:image:width" content="10"', 'name="twitter:card" content="summary_large_image"'):
            self.assertIn(tag, meta)
        self.assertEqual(r["titles"], [True, True, True, True, False, False])
        self.assertEqual(r["chapters"], [True, False, True, False])

    def test_folder_share_tags_nojekyll_and_warnings(self):
        d = self.project("shared", {"title": "Project", "share": {"url": "https://example.org/films/demo/",
                                                                   "description": "Two scenes, one test."}},
                         SHARE_PAGE, {"data/timeline.json": '{"title": "x", "file": "vo.wav"}', "data/vo.wav": os.urandom(200_000)})
        out = self.tmp / "out" / "shared"
        rep = export(d, out, "--folder", "--audio", "none")
        html = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn('<meta property="og:title" content="Project">', html)
        self.assertIn('<meta property="og:description" content="Two scenes, one test.">', html)
        self.assertIn('<meta property="og:url" content="https://example.org/films/demo/">', html)
        self.assertIn('<meta property="og:image" content="https://example.org/films/demo/assets/poster.jpg">', html)
        self.assertIn('<meta name="twitter:card" content="summary_large_image">', html)
        self.assertTrue((out / "assets" / "poster.jpg").stat().st_size > 1000)
        self.assertTrue((out / ".nojekyll").is_file(), "a folder export needs .nojekyll for GitHub Pages")
        self.assertEqual(rep["share"]["image"], "https://example.org/films/demo/assets/poster.jpg")
        # the page fetched the JSON; the WAV it names is never played, so it is not packed
        vfs = (out / "assets" / "vfs.js").read_text(encoding="utf-8")
        self.assertIn("/data/timeline.json", vfs)
        self.assertNotIn("/data/vo.wav", vfs)
        self.assertFalse((out / "assets" / "media" / "data" / "vo.wav").exists())
        w = " | ".join(rep["warnings"])
        self.assertIn('the title is "Project"', w)
        self.assertIn('"Shot 1"', w)
        self.assertIn('"chapters"', w)

    def test_missing_project_file_stops_the_export(self):
        page = SHARE_PAGE.replace("</body>", '<script type="module">import "./scenes/gone.js";</script></body>')
        d = self.project("gone", {"title": "Gone file", "chapters": [[0, "One"], [1, "Two"]]}, page,
                         {"data/timeline.json": '{"title": "x"}'})
        cp = showtime("export", "html", d, "-o", self.tmp / "out" / "gone.html", "--audio", "none", check=False)
        self.assertNotEqual(cp.returncode, 0, cp.stdout[-2000:])
        self.assertIn("/scenes/gone.js", cp.stderr)
        self.assertIn("could not be packed", cp.stderr)
        self.assertFalse((self.tmp / "out" / "gone.html").exists())
        self.assertNotIn("the title is", cp.stderr)
        self.assertNotIn('"Shot 1"', cp.stderr)


if __name__ == "__main__":
    argv = [a for a in sys.argv if a != "--fast"]
    t0 = time.time()
    prog = unittest.main(argv=argv, exit=False, verbosity=2 if "-v" in argv else 1)
    print("test_export: %.1fs" % (time.time() - t0), file=sys.stderr)
    sys.exit(0 if prog.result.wasSuccessful() else 1)

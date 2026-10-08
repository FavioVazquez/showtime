// Record a scripted app walkthrough as paced frames + a cursor/click/keystroke log
//
//   showtime demo record <script.mjs> [outdir] [--url URL | --serve DIR] [--size 1440x900] [--fps 30]
//   showtime demo init <script.mjs>          write a commented starter script
//
// The script drives the app with a small helper API (click, type, hover, scroll, press, wait...).
// Time is virtual: every helper advances the clock by whole frames and captures each frame, so the
// result is smooth and identical on a fast or a slow machine. Output: frames/, events.json, demo.mp4.
// Then: `showtime autozoom <outdir>` adds smooth auto zoom, a cursor and click ripples.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { launchGuarded, openGuarded, closeSoon } from './lib/stagehost.mjs';
import { parseCli, runMain, UserError, info, warn, c, jobDir, fmtDuration, printHelp, Progress } from './lib/cli.mjs';
import { newCaptureContext, installConsent, waitConsent, cleanupOverlays, robustGoto, detectBotWall, blockedMarkdown, slug, sleep, serveStatic, landingProblem, redactUrl, chromeUA, emulatePlatform, hostPlatform } from './lib/capture.mjs';
import { resolveFF, ffmpeg, fpsArg } from './lib/ff.mjs';

const TOP = {
  name: 'demo',
  usage: 'showtime demo <record|init> ...',
  summary: 'Record scripted product walkthroughs (paced frames + cursor/click/keystroke events).',
  description: 'commands:\n' +
    '  record <script.mjs> [outdir]   run the script against the app and capture every frame\n' +
    '  init <script.mjs>              write a starter script with every helper explained',
  examples: [
    'showtime demo init walkthrough.mjs',
    'showtime demo record walkthrough.mjs --url http://localhost:3000',
    'showtime demo record walkthrough.mjs --serve ./dist --size 1280x800 --fps 30',
    'showtime autozoom showtime-out/walkthrough-demo-20260926-101500',
  ],
};

const STARTER = `// showtime demo script. Record with:
//   showtime demo record ${'<this file>'} --url http://localhost:3000
// Every helper advances a virtual clock and captures frames, so pacing is exact.
// Targets are Playwright selectors ("#id", ".class", "text=Sign up", "role=button[name=Save]")
// or points {x, y} in CSS pixels. Times are in seconds.

export const options = {
  // url: 'http://localhost:3000',   // or pass --url / --serve
  size: '1440x900',                   // CSS viewport; frames are captured at --dpr (default 2)
  fps: 30,
};

export default async function (demo) {
  await demo.goto('/');                          // relative to --url / --serve
  await demo.wait(1.0);                          // hold on the first screen
  await demo.chapter('Create a project');        // chapter marker (titles, YouTube chapters)
  await demo.click('text=New project');          // cursor glides there, clicks (logged for zoom)
  await demo.type('#name', 'Launch video', { cps: 14 });  // clicks #name, types at 14 characters/second
  await demo.type(' and trailer', { cps: 14 });           // no target: types into the focused field
  await demo.press('Enter');                     // key presses show as keycaps in autozoom
  await demo.waitFor('.toast');                  // waits in real time WITHOUT recording (skips loading)
  await demo.wait(1.5);                          // let the viewer read the result
  await demo.scroll('#pricing', { duration: 1.2 });  // smooth scroll to an element
  await demo.hover('.plan.pro');
  await demo.focus('.plan.pro', { zoom: 1.6, duration: 2 });  // explicit camera hint for autozoom
  await demo.wait(1.0);
}
`;

// ------------------------------------------------------------------------------------ helpers

const easeInOut = (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);

function hash01(i, seed) {
  let h = (i * 374761393 + seed * 668265263) >>> 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177) >>> 0;
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

/** Pixel size of a baseline/progressive JPEG (SOFn marker), or null. */
export function jpegSize(buf) {
  let i = 2;
  while (i + 9 < buf.length) {
    if (buf[i] !== 0xff) { i++; continue; }
    const m = buf[i + 1];
    if (m === 0xd8 || m === 0x01 || (m >= 0xd0 && m <= 0xd7)) { i += 2; continue; }
    const len = buf.readUInt16BE(i + 2);
    if (m >= 0xc0 && m <= 0xcf && m !== 0xc4 && m !== 0xc8 && m !== 0xcc) return { height: buf.readUInt16BE(i + 5), width: buf.readUInt16BE(i + 7) };
    i += 2 + len;
  }
  return null;
}

/** type() arguments: (target, text, opts) | (text) | (text, opts) | (null, text, opts). */
export function typeArgs(target, text, opts) {
  if (typeof target === 'string' && (text === undefined || (text !== null && typeof text === 'object' && !Array.isArray(text)))) {
    return { target: null, text: target, opts: text || opts || {} };
  }
  return { target: target ?? null, text, opts: opts || {} };
}

function parseSize(s) {
  const m = /^(\d{3,4})\s*[x:]\s*(\d{3,4})$/.exec(String(s || '').trim());
  if (!m) throw new UserError(`--size must look like 1440x900 (got ${s})`);
  return { width: Number(m[1]), height: Number(m[2]) };
}

class Recorder {
  constructor({ page, cdp, out, fps, dpr, viewport, baseUrl, quality, animations }) {
    Object.assign(this, { page, cdp, out, fps, dpr, viewport, baseUrl, quality, animations });
    this.dt = 1 / fps;
    this.clipScale = dpr;
    this.n = 0;
    this.cursor = { x: viewport.width * 0.62, y: viewport.height * 0.72, down: 0 };
    this.cursorLog = [];
    this.events = [];
    this.framesDir = path.join(out, 'frames');
    fs.mkdirSync(this.framesDir, { recursive: true });
    this.prog = null;
  }

  get t() { return this.n * this.dt; }

  async _advanceAnimations() {
    if (this.animations !== 'step') return;
    // the document timeline is paused (playback rate 0); step every running animation by one frame
    await this.page.evaluate((ms) => {
      for (const a of document.getAnimations()) {
        if (a.playState === 'running' || a.playState === 'pending') {
          const t = Number(a.currentTime) || 0;
          try { a.currentTime = t + ms; } catch { /* ignore */ }
        }
      }
    }, this.dt * 1000).catch(() => {});
  }

  /** One screenshot of the viewport at size x dpr. A plain CDP capture ignores the context's
   *  deviceScaleFactor on some Chrome builds (1x frames while events.json claims dpr x), so the
   *  viewport is captured through an explicit clip whose scale is checked on the first frame. */
  async _shot() {
    const m = await this.cdp.send('Page.getLayoutMetrics');
    const vv = m.cssVisualViewport || m.visualViewport || { pageX: 0, pageY: 0 };
    const clip = { x: vv.pageX || 0, y: vv.pageY || 0, width: this.viewport.width, height: this.viewport.height, scale: this.clipScale };
    const r = await this.cdp.send('Page.captureScreenshot', { format: 'jpeg', quality: this.quality, optimizeForSpeed: true, clip });
    return Buffer.from(r.data, 'base64');
  }

  async _firstShot() {
    const want = Math.round(this.viewport.width * this.dpr);
    let buf = await this._shot();
    for (let i = 0; i < 2; i++) {
      const size = jpegSize(buf);
      if (!size || size.width === want) return buf;
      this.clipScale *= want / size.width;   // this Chrome already applies (part of) the dpr
      buf = await this._shot();
    }
    const size = jpegSize(buf);
    if (size && Math.abs(size.width - want) > 1) {
      throw new UserError(`frames come out ${size.width}x${size.height}, not ${want}x${Math.round(this.viewport.height * this.dpr)} (--dpr ${this.dpr})`,
        'try --dpr 1, or record with a larger --size; report this Chrome version with `showtime doctor --report`');
    }
    return buf;
  }

  /** Capture one frame and advance the clock. */
  async frame() {
    await this._advanceAnimations();
    const buf = this.n === 0 ? await this._firstShot() : await this._shot();
    this.n++;
    fs.writeFileSync(path.join(this.framesDir, `${String(this.n).padStart(5, '0')}.jpg`), buf);
    this.cursorLog.push([Number(((this.n - 1) * this.dt).toFixed(4)), Math.round(this.cursor.x * 10) / 10, Math.round(this.cursor.y * 10) / 10, this.cursor.down]);
    if (this.prog) this.prog.tick(1);
    if (this.n > this.maxFrames) throw new UserError(`the demo is longer than --max-duration (${(this.maxFrames * this.dt).toFixed(0)} s)`, 'raise --max-duration or shorten the script');
  }

  async frames(seconds) {
    const k = Math.max(0, Math.round(seconds * this.fps));
    for (let i = 0; i < k; i++) await this.frame();
  }

  event(e) { const ev = { t: Number(this.t.toFixed(4)), ...e }; this.events.push(ev); return ev; }

  async resolve(target, { scroll = true } = {}) {
    if (target && typeof target === 'object' && 'x' in target && 'y' in target) {
      return { x: Number(target.x), y: Number(target.y), bbox: null, selector: null };
    }
    if (typeof target !== 'string') throw new UserError(`bad target ${JSON.stringify(target)}: use a selector string or {x, y}`);
    const loc = this.page.locator(target).first();
    try {
      await loc.waitFor({ state: 'visible', timeout: 10000 });
    } catch {
      throw new UserError(`demo script: nothing visible matches ${target} (waited 10 s)`, 'check the selector, or add `await demo.waitFor(...)` before this step');
    }
    if (scroll) {
      const inView = await loc.evaluate((el) => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth; });
      if (!inView) await this.scrollTo(target, { duration: 0.8 });
    }
    const b = await loc.boundingBox();
    if (!b) throw new UserError(`demo script: ${target} has no box (hidden?)`);
    return { x: b.x + b.width / 2, y: b.y + b.height / 2, bbox: [b.x, b.y, b.width, b.height].map((v) => Math.round(v * 10) / 10), selector: target, locator: loc };
  }

  async moveTo(target, { duration } = {}) {
    const p = await this.resolve(target);
    const from = { ...this.cursor };
    const d = Math.hypot(p.x - from.x, p.y - from.y);
    const diag = Math.hypot(this.viewport.width, this.viewport.height);
    const dur = duration ?? Math.min(0.9, Math.max(0.35, 0.35 + (d / diag) * 0.8));
    const k = Math.max(1, Math.round(dur * this.fps));
    // slight arc: control point offset perpendicular to the path
    const side = hash01(this.events.length + 1, 7) < 0.5 ? -1 : 1;
    const mx = (from.x + p.x) / 2 - ((p.y - from.y) * 0.12) * side, my = (from.y + p.y) / 2 + ((p.x - from.x) * 0.12) * side;
    if (d > 1) {
      for (let i = 1; i <= k; i++) {
        const u = easeInOut(i / k);
        this.cursor.x = (1 - u) * (1 - u) * from.x + 2 * (1 - u) * u * mx + u * u * p.x;
        this.cursor.y = (1 - u) * (1 - u) * from.y + 2 * (1 - u) * u * my + u * u * p.y;
        await this.page.mouse.move(this.cursor.x, this.cursor.y);
        await this.frame();
      }
    }
    this.cursor.x = p.x; this.cursor.y = p.y;
    return p;
  }

  async scrollTo(target, { duration = 1.0 } = {}) {
    const from = await this.page.evaluate(() => window.scrollY);
    let to;
    if (typeof target === 'number') to = from + target;
    else if (target && typeof target === 'object' && 'y' in target) to = Number(target.y);
    else if (target === 'bottom') to = await this.page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
    else if (target === 'top') to = 0;
    else {
      const loc = this.page.locator(target).first();
      await loc.waitFor({ state: 'attached', timeout: 10000 }).catch(() => { throw new UserError(`demo script: nothing matches ${target}`); });
      to = await loc.evaluate((el) => { const r = el.getBoundingClientRect(); return window.scrollY + r.top - Math.max(40, (innerHeight - r.height) / 2); });
    }
    to = Math.max(0, Math.min(to, await this.page.evaluate(() => document.documentElement.scrollHeight - innerHeight)));
    const ev = this.event({ type: 'scroll', from: Math.round(from), to: Math.round(to), target: typeof target === 'string' ? target : null });
    const k = Math.max(1, Math.round(duration * this.fps));
    await this.page.evaluate(() => { document.documentElement.style.scrollBehavior = 'auto'; });
    for (let i = 1; i <= k; i++) {
      const y = from + (to - from) * easeInOut(i / k);
      await this.page.evaluate((yy) => window.scrollTo(0, yy), y);
      await this.frame();
    }
    ev.end = Number(this.t.toFixed(4));
  }
}

function makeApi(rec, baseUrl) {
  const api = {
    get page() { return rec.page; },
    get t() { return rec.t; },
    fps: rec.fps,
    viewport: rec.viewport,
    baseUrl,
    async goto(u = '/', { hold = 0 } = {}) {
      const url = baseUrl ? new URL(u, baseUrl).href : u;
      const nav = await robustGoto(rec.page, url, { timeout: 60000, settle: 500 });
      const wrong = await landingProblem(rec.page);
      if (wrong) throw new UserError(`wrong page: ${wrong.reason} (${url})`, wrong.hint);
      const wall = await detectBotWall(rec.page, nav.status);
      if (wall.blocked) {
        fs.writeFileSync(path.join(rec.out, 'BLOCKED.md'), blockedMarkdown(url, wall));
        const e = new UserError(`${url} shows a bot check (${wall.reasons.join(', ')}); showtime does not bypass it`, 'record your local build instead (--serve ./dist or --url http://localhost:...)');
        e.exitCode = 3;
        throw e;
      }
      if (rec.consentLog) await waitConsent(rec.consentLog, 3000);
      await cleanupOverlays(rec.page, { hide: true });
      rec.event({ type: 'navigate', url: redactUrl(url) });
      if (hold) await rec.frames(hold);
      return nav;
    },
    async wait(seconds = 1) { await rec.frames(Number(seconds)); },
    async waitFor(what, { timeout = 30000 } = {}) {
      // real-time wait, nothing recorded: loading never shows up in the video
      if (typeof what === 'function') await rec.page.waitForFunction(what, null, { timeout });
      else if (typeof what === 'number') await sleep(what * 1000);
      else await rec.page.locator(what).first().waitFor({ state: 'visible', timeout }).catch(() => { throw new UserError(`demo script: ${what} did not appear within ${timeout / 1000} s`); });
    },
    async moveTo(target, o = {}) { await rec.moveTo(target, o); },
    async hover(target, { hold = 0.4, ...o } = {}) {
      const p = await rec.moveTo(target, o);
      rec.event({ type: 'hover', x: p.x, y: p.y, bbox: p.bbox, target: p.selector });
      await rec.frames(hold);
    },
    async click(target, { hold = 0.35, move, button = 'left', count = 1 } = {}) {
      const p = await rec.moveTo(target, { duration: move });
      rec.event({ type: 'click', x: Math.round(p.x), y: Math.round(p.y), bbox: p.bbox, target: p.selector, button, count });
      rec.cursor.down = 1;
      await rec.page.mouse.down({ button, clickCount: count });
      await rec.frames(2 / rec.fps);
      await rec.page.mouse.up({ button, clickCount: count });
      rec.cursor.down = 0;
      await rec.frames(hold);
    },
    async dblclick(target, o = {}) { await api.click(target, { ...o, count: 2 }); },
    async type(targetArg, textArg, optsArg) {
      // type('#field', 'text', {cps}) clicks the field first; type('text', {cps}) or
      // type(null, 'text', {cps}) types into whatever has focus (no click, no caret move)
      const { target, text, opts } = typeArgs(targetArg, textArg, optsArg);
      const { cps = 14, clear = false, hold = 0.3, jitter = 0.35 } = opts;
      if (text === undefined || text === null) throw new UserError('demo.type: missing text', "use demo.type('#field', 'text') or demo.type('text') for the focused field");
      let bbox = null, sel = null;
      if (target) {
        const p = await rec.moveTo(target);
        rec.event({ type: 'click', x: Math.round(p.x), y: Math.round(p.y), bbox: p.bbox, target: p.selector, button: 'left', count: 1 });
        await rec.page.mouse.click(p.x, p.y);
        await rec.frames(0.15);
        bbox = p.bbox; sel = p.selector;
        if (clear) { await rec.page.keyboard.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A'); await rec.page.keyboard.press('Backspace'); }
      } else {
        // no target: log the focused element's box so autozoom can still frame the typing
        bbox = await rec.page.evaluate(() => {
          const el = document.activeElement;
          if (!el || el === document.body || el === document.documentElement) return null;
          const r = el.getBoundingClientRect();
          return r.width && r.height ? [r.x, r.y, r.width, r.height].map((v) => Math.round(v * 10) / 10) : null;
        }).catch(() => null);
      }
      // a password field logs dots, never the typed text (events.json and the key overlay)
      const secret = await rec.page.evaluate(() => { const el = document.activeElement; return !!(el && el.tagName === 'INPUT' && /^password$/i.test(el.type)); }).catch(() => false);
      const ev = rec.event({ type: 'type', text: secret ? '•'.repeat([...String(text)].length) : String(text), bbox, target: sel });
      const chars = [...String(text)];
      let debt = 0;
      for (let i = 0; i < chars.length; i++) {
        await rec.page.keyboard.type(chars[i]);
        // deterministic human-like rhythm: +/- jitter around 1/cps, a longer beat after spaces
        const base = 1 / Math.max(1, cps);
        const j = 1 + (hash01(i + 1, chars.length) * 2 - 1) * jitter + (chars[i] === ' ' ? 0.4 : 0);
        debt += base * j * rec.fps;
        const k = Math.floor(debt);
        debt -= k;
        for (let f = 0; f < k; f++) await rec.frame();
      }
      ev.end = Number(rec.t.toFixed(4));
      await rec.frames(hold);
    },
    async press(keys, { hold = 0.4 } = {}) {
      rec.event({ type: 'key', keys: String(keys) });
      await rec.page.keyboard.press(String(keys));
      await rec.frames(hold);
    },
    async select(target, value, o = {}) {
      await api.click(target, o);
      await rec.page.locator(target).first().selectOption(value);
      await rec.frames(0.3);
    },
    async drag(from, to, { duration = 0.8 } = {}) {
      const a = await rec.moveTo(from);
      rec.cursor.down = 1;
      await rec.page.mouse.down();
      const ev = rec.event({ type: 'drag', x: Math.round(a.x), y: Math.round(a.y), bbox: a.bbox, target: a.selector });
      const b = await rec.moveTo(to, { duration });
      await rec.page.mouse.up();
      rec.cursor.down = 0;
      Object.assign(ev, { end: Number(rec.t.toFixed(4)), x2: Math.round(b.x), y2: Math.round(b.y) });
      await rec.frames(0.3);
    },
    async scroll(target, { duration = 1.0 } = {}) { await rec.scrollTo(target, { duration }); },
    async focus(target, { zoom = 1.6, duration = 1.5 } = {}) {
      const p = await rec.resolve(target);
      rec.event({ type: 'focus', x: Math.round(p.x), y: Math.round(p.y), bbox: p.bbox, target: p.selector, zoom, end: Number((rec.t + duration).toFixed(4)) });
    },
    async chapter(title) { rec.event({ type: 'chapter', title: String(title) }); },
    // tell autozoom to go wide here (end any zoomed shot); a chapter marker also keeps shots apart
    async wide() { rec.event({ type: 'wide' }); },
    async note(text) { rec.event({ type: 'note', text: String(text) }); },
    async frame() { await rec.frame(); },
  };
  return api;
}

// ------------------------------------------------------------------------------------ record

async function record(argv) {
  const spec = {
    name: 'demo record',
    usage: 'showtime demo record <script.mjs> [outdir] [options]',
    summary: 'Run a demo script against a web app and capture paced frames plus an event log.',
    description: 'Target: --url (a running app) or --serve <dir> (a static folder, served by a plain static server\n' +
      'on 127.0.0.1 and stopped when done). Never record through `showtime server`/`preview`.\n' +
      'Output (default ./showtime-out/<script>-demo-<time>/, printed at the end):\n' +
      '  frames/00001.jpg ...   every frame at size x dpr (clean: no cursor drawn)\n' +
      '  events.json            fps, viewport, per-frame cursor [t,x,y,down], clicks/typing/keys/scrolls\n' +
      '                         with element boxes, chapters, and ready-made overlay data (cursor path,\n' +
      '                         keystrokes) for the runtime cursor/keystrokes components\n' +
      '  demo.mp4               the frames as video (no cursor)\n' +
      'Next: showtime autozoom <outdir>   (zoom + cursor + click ripples + keycaps)\n' +
      'Page animations are stepped frame by frame (--animations step) so CSS/Web Animations run at\n' +
      'recorded speed; JavaScript timers still run in real time (use demo.waitFor for app state).',
    options: {
      url: { short: 'u', help: 'base URL of the app (e.g. http://localhost:3000)', metavar: 'URL' },
      serve: { help: 'serve this static folder on 127.0.0.1 (plain static server) and use it as the base URL', metavar: 'DIR' },
      size: { short: 's', help: 'CSS viewport WxH (default 1440x900 or the script options)', metavar: 'WxH' },
      dpr: { help: 'device pixel ratio for frames (default 2: sharp when zoomed)', metavar: 'N' },
      fps: { help: 'frames per second (default 30)', metavar: 'N' },
      quality: { default: '90', help: 'JPEG quality of frames (default 90)' },
      dark: { type: 'boolean', help: 'dark colour scheme' },
      platform: { help: 'mac | windows | linux: the OS the page sees (user agent, navigator.platform), so shortcut labels and modifier keys match the narration on any machine (default: this machine, or the script options)', metavar: 'OS' },
      animations: { default: 'step', help: 'step (frame-exact CSS animations) | real' },
      'max-duration': { default: '300', help: 'safety limit in seconds (default 300)', metavar: 'S' },
      'no-mp4': { type: 'boolean', help: 'keep frames only' },
      'no-consent': { type: 'boolean', help: 'do not dismiss cookie banners' },
      gpu: { default: 'auto', help: 'auto | off' },
      headed: { type: 'boolean', help: 'show the browser window while recording' },
      json: { type: 'boolean', help: 'print a JSON summary on stdout' },
    },
    examples: [
      'showtime demo record walkthrough.mjs --url http://localhost:3000',
      'showtime demo record walkthrough.mjs ./rec --serve ./dist --size 1280x800 --dpr 2',
      'showtime demo record walkthrough.mjs --url https://staging.example.com --fps 60',
      'showtime demo record walkthrough.mjs --serve ./dist --platform mac   # Cmd shortcuts on any OS',
    ],
  };
  const o = parseCli(spec, argv);
  const scriptPath = o._[0] ? path.resolve(o._[0]) : null;
  if (!scriptPath) throw new UserError('missing <script.mjs>', 'create one with: showtime demo init walkthrough.mjs');
  if (!fs.existsSync(scriptPath)) throw new UserError(`script not found: ${scriptPath}`, 'create one with: showtime demo init ' + path.basename(scriptPath));
  let mod;
  try {
    mod = await import(pathToFileURL(scriptPath).href + `?t=${Date.now()}`);
  } catch (e) {
    throw new UserError(`could not load ${path.basename(scriptPath)}: ${String(e.message).split('\n')[0]}`, 'check the script for syntax errors (it is an ES module: export default async function (demo) {...})');
  }
  const run = mod.default;
  if (typeof run !== 'function') throw new UserError(`${path.basename(scriptPath)} must export a default async function (demo) { ... }`);
  const so = mod.options || {};
  const viewport = parseSize(o.size || so.size || '1440x900');
  const fps = Number(o.fps || so.fps || 30);
  if (!(fps >= 1 && fps <= 120)) throw new UserError('--fps must be between 1 and 120');
  const dpr = Number(o.dpr || so.dpr || 2);
  if (!(dpr >= 0.5 && dpr <= 4)) throw new UserError('--dpr must be between 0.5 and 4');
  if (o.serve && o.url) throw new UserError('pass either --url or --serve, not both');
  const out = o._[1] ? path.resolve(o._[1]) : jobDir(`${slug(path.basename(scriptPath, path.extname(scriptPath)))}-demo`);
  fs.mkdirSync(out, { recursive: true });
  for (const f of fs.readdirSync(out)) if (f === 'frames') fs.rmSync(path.join(out, f), { recursive: true, force: true });
  let server = null;
  let baseUrl = o.url || so.url || null;
  if (o.serve) {
    server = await serveStatic(o.serve);
    baseUrl = server.page.endsWith('/') ? server.page : server.url + '/';
  }
  if (baseUrl && !/^[a-z]+:\/\//i.test(baseUrl)) baseUrl = (/^(localhost|127\.)/.test(baseUrl) ? 'http://' : 'https://') + baseUrl;
  const t0 = Date.now();
  info(`${c.bold('demo record')} ${path.basename(scriptPath)} ${c.dim(`${viewport.width}x${viewport.height} @${dpr}x, ${fps} fps${baseUrl ? ', ' + baseUrl : ''}`)}`);
  if (server) info(c.dim(`  serving ${server.root} (plain static server, stopped when done)`));
  info(c.dim(`  output ${out}`));
  const B = await launchGuarded({ gpu: o.gpu, headless: !o.headed });
  let rec;
  try {
    const platform = String(o.platform || so.platform || hostPlatform()).toLowerCase();
    // the context, the tab and its CDP session under the page-open deadline (once more in a new browser)
    const { consentLog, page, cdp } = await openGuarded(B, async (browser, track) => {
      track.step = 'creating the browser context';
      const ctx = await newCaptureContext(browser, { css: viewport, dpr, mobile: false }, { dark: !!o.dark, reducedMotion: 'no-preference',
        userAgent: chromeUA(browser.version(), { platform }) });
      await emulatePlatform(ctx, platform);
      track.step = 'setting up the consent clicker';
      const consentLog = o['no-consent'] ? null : await installConsent(ctx);
      track.step = 'opening a tab';
      const page = await ctx.newPage();
      track.step = 'opening the tab\'s CDP session';
      const cdp = await ctx.newCDPSession(page);
      return { consentLog, page, cdp, close: () => ctx.close() };
    }, { label: 'opening the recording tab' });
    if (platform !== hostPlatform()) info(c.dim(`  the page sees ${platform} (recording on ${hostPlatform()})`));
    const animations = o.animations === 'real' ? 'real' : 'step';
    rec = new Recorder({ page, cdp, out, fps, dpr, viewport, baseUrl, quality: Math.min(100, Math.max(40, Number(o.quality))), animations });
    rec.consentLog = consentLog;
    rec.maxFrames = Math.round(Number(o['max-duration']) * fps);
    if (animations === 'step') {
      await cdp.send('Animation.enable');
      await cdp.send('Animation.setPlaybackRate', { playbackRate: 0 });
    }
    rec.prog = new Progress('frames', rec.maxFrames, { quiet: true });
    const api = makeApi(rec, baseUrl);
    const tick = setInterval(() => { if (rec.n && process.stderr.isTTY) process.stderr.write(c.dim(`\r  recorded ${rec.n} frames (${rec.t.toFixed(1)} s of video)`)); }, 1000);
    try {
      await run(api);
    } finally {
      clearInterval(tick);
      if (process.stderr.isTTY) process.stderr.write('\r\x1b[2K');
    }
    if (!rec.n) throw new UserError('the script finished without recording any frame', 'add steps like `await demo.wait(1)` or `await demo.click(...)`');
  } finally {
    await closeSoon(B.browser.close());
    if (server) { try { await server.close(); } catch { /* already closed */ } }
  }
  const duration = rec.n / fps;
  const frameSize = { width: Math.round(viewport.width * dpr), height: Math.round(viewport.height * dpr) };
  // ready-made overlay data for the runtime cursor / keystrokes components (x/y in % of the frame)
  const pct = (x, y) => ({ x: Number(((100 * x) / viewport.width).toFixed(2)), y: Number(((100 * y) / viewport.height).toFixed(2)) });
  const cursorPath = [];
  const first = rec.cursorLog[0];
  if (first) cursorPath.push({ at: 0, ...pct(first[1], first[2]) });
  for (const e of rec.events) if (['click', 'hover', 'drag'].includes(e.type)) cursorPath.push({ at: e.t, ...pct(e.x, e.y), click: e.type === 'click' || undefined, hover: e.type === 'hover' || undefined });
  const keystrokes = rec.events.filter((e) => e.type === 'key' || e.type === 'type').map((e) => (e.type === 'key' ? { at: e.t, keys: e.keys.replace(/\+/g, ' ') } : { at: e.t, text: e.text }));
  const chapters = rec.events.filter((e) => e.type === 'chapter').map((e) => ({ t: e.t, title: e.title }));
  const events = {
    version: 1, tool: 'showtime demo record', script: path.basename(scriptPath), fps, frames: rec.n, duration: Number(duration.toFixed(4)),
    viewport, dpr, frame_size: frameSize, frame_pattern: 'frames/%05d.jpg', video: o['no-mp4'] ? null : 'demo.mp4',
    coordinates: 'CSS pixels of the viewport; multiply by dpr for frame pixels', animations: rec.animations,
    cursor: rec.cursorLog, events: rec.events, chapters, overlays: { cursor_path: cursorPath, keystrokes },
  };
  fs.writeFileSync(path.join(out, 'events.json'), JSON.stringify(events, null, 1));
  let mp4 = null;
  if (!o['no-mp4']) {
    resolveFF();
    mp4 = path.join(out, 'demo.mp4');
    const W = frameSize.width + (frameSize.width % 2), H = frameSize.height + (frameSize.height % 2);
    await ffmpeg(['-framerate', fpsArg(fps), '-i', path.join(out, 'frames', '%05d.jpg'),
      '-vf', `scale=${W}:${H}:flags=lanczos:out_color_matrix=bt709:out_range=tv,format=yuv420p`,
      '-c:v', 'libx264', '-preset', 'medium', '-crf', '16', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
      '-movflags', '+faststart', mp4]);
  }
  const summary = { ok: true, out, frames: rec.n, duration: Number(duration.toFixed(2)), fps, events: path.join(out, 'events.json'), video: mp4,
    clicks: rec.events.filter((e) => e.type === 'click').length, keys: keystrokes.length, chapters: chapters.length, seconds: Number(((Date.now() - t0) / 1000).toFixed(1)) };
  if (o.json) console.log(JSON.stringify(summary, null, 2));
  else {
    info(`${c.green('done')}: ${rec.n} frames = ${duration.toFixed(1)} s of video (${summary.clicks} clicks, ${summary.keys} key/typing events) in ${fmtDuration(Date.now() - t0)}`);
    info(c.dim(o['no-mp4'] && rec.n <= fps * 2 ? '  (a short still recording: use frames/ as an image; autozoom is for walkthroughs)' : `  next: showtime autozoom ${out}`));
    console.log(out);
    if (mp4) console.log(mp4);
    console.log(path.join(out, 'events.json'));
  }
  return 0;
}

async function init(argv) {
  const o = parseCli({ name: 'demo init', usage: 'showtime demo init <script.mjs> [--force]', summary: 'Write a starter demo script.',
    options: { force: { type: 'boolean', help: 'overwrite an existing file' } }, examples: ['showtime demo init walkthrough.mjs'] }, argv);
  const f = path.resolve(o._[0] || 'demo.mjs');
  if (fs.existsSync(f) && !o.force) throw new UserError(`${f} exists`, 'pick another name or pass --force');
  fs.mkdirSync(path.dirname(f), { recursive: true });
  fs.writeFileSync(f, STARTER.replace('<this file>', path.basename(f)));
  console.log(f);
  return 0;
}

const [cmd, ...rest] = process.argv.slice(2);
const table = { record, init };
if (!cmd || cmd === '--help' || cmd === '-h' || cmd === 'help') {
  printHelp({ ...TOP, options: {} });
  process.exit(cmd ? 0 : 2);
} else if (!table[cmd]) {
  process.stderr.write(`showtime demo: unknown command "${cmd}"\n  commands: record, init (see \`showtime demo --help\`)\n`);
  process.exit(2);
} else {
  runMain(async () => {
    try { return await table[cmd](rest); } catch (e) { if (e && e.exitCode === 3) { process.stderr.write(`${c.yellow('showtime demo: blocked:')} ${e.message}\n`); return 3; } throw e; }
  });
}

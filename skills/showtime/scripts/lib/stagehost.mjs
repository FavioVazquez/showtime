// Open a showtime project page in a headless browser with the render-mode stage runtime
// injected before any page script, then seek and capture frames. Shared by render, check
// and snap so every tool sees exactly the same pixels.
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { skillDir } from './deps.mjs';
import { launchBrowser } from './chrome.mjs';
import { UserError, warn } from './cli.mjs';

const STAGE_SRC = () => fs.readFileSync(path.join(skillDir(), 'runtime', 'stage.js'), 'utf8');
let stageCache = null;
export function stageSource() { return stageCache || (stageCache = STAGE_SRC()); }

const LOCAL_HOSTS = new Set(['127.0.0.1', 'localhost', '[::1]', '::1']);
export function isLocalUrl(u) {
  if (/^(data|blob|about|chrome|chrome-extension|devtools):/i.test(u)) return true;
  try { return LOCAL_HOSTS.has(new URL(u).hostname); } catch { return true; }
}

/**
 * Launch one browser (retrying once in software mode if the GPU path fails to start).
 * -> { browser, kind, version, executablePath, flags, relaunch() }  (relaunch: a new one the same way, for
 * openGuarded below)
 */
// Extra flags for capture on top of the shared set (scripts/lib/chrome-flags.json).
// --disable-lcd-text: text in composited layers is always grayscale-antialiased while text in the
// root layer may use LCD antialiasing, so a frame's pixels would depend on whether an element was
// promoted to a layer earlier (e.g. by a blur animation) -> frames would differ between workers.
export const CAPTURE_ARGS = ['--disable-lcd-text'];

export async function openBrowser({ gpu = 'auto', headless = true, args = [], ownSignals = false } = {}) {
  const extra = [...CAPTURE_ARGS, ...args];
  let rec;
  try {
    rec = await launchBrowser({ gpu, headless, args: extra, ownSignals });
  } catch (e) {
    if (gpu === 'off') throw e;
    rec = await launchBrowser({ gpu: 'off', headless, args: extra, ownSignals });
  }
  rec.relaunch = () => openBrowser({ gpu, headless, args, ownSignals });
  rec.pid = await browserPid(rec.browser);
  return rec;
}

/**
 * A browser record from launchBrowser made ready for openGuarded: relaunch() (a function that returns another
 * such record) and the process id. -> rec
 */
export async function guardable(rec, relaunch) {
  rec.relaunch = relaunch;
  rec.pid = await browserPid(rec.browser);
  return rec;
}

/** launchBrowser(o) as a record for openGuarded (relaunch() the same way, the process id). */
export async function launchGuarded(o = {}) {
  const launch = async () => guardable(await launchBrowser(o), launch);
  return launch();
}

/** The browser's process id (CDP SystemInfo.getProcessInfo), or null. */
async function browserPid(browser) {
  try {
    const s = await withTimeout(browser.newBrowserCDPSession(), 15000, 'reading the browser process id');
    const r = await withTimeout(s.send('SystemInfo.getProcessInfo'), 15000, 'reading the browser process id');
    s.detach().catch(() => {});
    const p = ((r && r.processInfo) || []).find((x) => x.type === 'browser');
    return p && Number.isInteger(p.id) && p.id > 0 ? p.id : null;
  } catch { return null; }
}

/**
 * Give up a browser that stopped answering: close it if it still can, and kill its process (its process group:
 * Playwright starts it as a group leader) so it never keeps the command alive or holds the machine.
 */
export function abandonBrowser(rec) {
  if (!rec || !rec.browser) return;
  closeSoon(rec.browser.close(), 3000);
  const pid = rec.pid;
  if (!pid) { warn('the browser stopped answering and its process id is unknown: it was only asked to close; it ends with this command'); return; }
  if (process.platform === 'win32') {
    try { spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true }).on('error', () => {}); } catch { /* gone */ }
  } else {
    try { process.kill(-pid, 'SIGKILL'); } catch { try { process.kill(pid, 'SIGKILL'); } catch { /* gone */ } }
  }
}

// tests only: SHOWTIME_TEST_STOP_BROWSER=open stops (SIGSTOP) the browser just before the first page opens,
// =ready:N just after the N-th page opened: a real browser that stops answering, for the deadline and the
// watchdog (POSIX only)
const TEST_STOP = /^(open|ready)(?::(\d+))?$/.exec(process.platform === 'win32' ? '' : String(process.env.SHOWTIME_TEST_STOP_BROWSER || ''));
let testStop = TEST_STOP ? { when: TEST_STOP[1], n: Number(TEST_STOP[2] || 1) } : null;
let opened = 0;
function testStopNow(b, when) {
  if (when === 'ready') opened++;
  if (!testStop || testStop.when !== when || (when === 'ready' && opened !== testStop.n) || !b.pid) return;
  testStop = null;
  try { process.kill(b.pid, 'SIGSTOP'); } catch { /* gone */ }
}

// ------------------------------------------------------------------ opening a page, with a deadline
// A browser on a very busy machine can stop answering while it opens a page (a render once waited 14 minutes;
// on macOS CI runners a render and a check outlived their callers' deadlines): creating its context, its page
// or its CDP session has no deadline of its own. Every page showtime opens goes through openGuarded: the whole
// open (context, page, the first navigation, the page getting ready) gets PAGE_OPEN_MS, longer than the load and
// ready timeouts inside, times the page's pace factor; past it the browser is given up (killed), the open tried
// once more in a new browser, and then the command fails naming the step it was stuck at instead of waiting with
// no end.
// SHOWTIME_TEST_OPEN_TIMEOUT=<seconds> shortens it (tests).
export const PAGE_OPEN_MS = Number(process.env.SHOWTIME_TEST_OPEN_TIMEOUT) > 0 ? Number(process.env.SHOWTIME_TEST_OPEN_TIMEOUT) * 1000 : 300000;

/** close() of a browser or page that may not answer: never waits more than ms. */
export function closeSoon(p, ms = 10000) {
  return withTimeout(Promise.resolve().then(() => p), ms, 'closing a browser').catch(() => {});
}

/**
 * Run open(browser, track, pace) under the page-open deadline. b is a browser record ({browser, relaunch()}, as
 * openBrowser returns): a browser that never answers is closed and replaced in b itself (Object.assign), so the
 * caller's later pages and its own close use the new one. open() keeps track.step current ('creating the
 * browser context', ...) for the error, and may report the page's pace into pace (its deadline grows with it).
 * onRetry(message, what) is told before the second try (default: a warning on stderr); what is the step it was
 * stuck at. It may throw instead (a caller that holds pages of the old browser cannot go on in a new one).
 * -> whatever open() returns (it must have close() if it holds anything)
 */
export async function openGuarded(b, open, { label = 'opening the page', onRetry = (m) => warn(m) } = {}) {
  for (let attempt = 1; ; attempt++) {
    const track = { step: 'starting' };
    const pace = newPace();
    testStopNow(b, 'open');
    const p = Promise.resolve().then(() => open(b.browser, track, pace));
    try {
      const got = await withPacedTimeout(p, PAGE_OPEN_MS, label, pace);
      testStopNow(b, 'ready');
      return got;
    } catch (e) {
      if (!e || e.deadline !== label) throw e;
      p.then((x) => x && typeof x.close === 'function' && closeSoon(x.close(), 5000), () => {});
      const what = `${String(e.message)} (stuck at: ${track.step})`;
      // a record without relaunch() lends a browser that others use (render's soundtrack borrows worker 0's):
      // the caller decides what to do with it
      if (typeof b.relaunch === 'function') abandonBrowser(b);
      if (attempt > 1 || typeof b.relaunch !== 'function') {
        throw Object.assign(new UserError(`the browser stopped answering: ${what}${attempt > 1 ? ', in a new browser too' : ''}`, STUCK_HINT),
          { browserStuck: true });
      }
      onRetry(`the browser did not answer while ${label}: ${what}; trying once more in a new browser`, what);
      Object.assign(b, await b.relaunch());
    }
  }
}

export const STUCK_HINT = 'the machine is too busy or the browser is stuck: close other heavy programs and retry, or try --gpu off; `showtime doctor` checks the browser';

/**
 * Watch a browser record while a command works with it (calls on a page have no deadline of their own): a
 * browser that does not answer a ping (CDP Browser.getVersion, answered by the browser process however busy its
 * pages are) within PAGE_OPEN_MS has stopped. onStuck(message, hint) is called once, after the browser is killed;
 * the command then ends with that error instead of waiting with no end. A browser replaced meanwhile
 * (openGuarded) is pinged anew. -> stop()
 */
export function watchBrowser(b, onStuck) {
  const every = Math.min(30000, Math.max(500, PAGE_OPEN_MS / 4));
  let stopped = false, timer = null, sess = null, sessFor = null;
  const tick = async () => {
    if (stopped) return;
    const br = b.browser;
    const t0 = Date.now();
    try {
      if (sessFor !== br) { sess = null; sessFor = br; sess = await withTimeout(br.newBrowserCDPSession(), PAGE_OPEN_MS, 'answering a ping'); }
      await withTimeout(sess.send('Browser.getVersion'), PAGE_OPEN_MS, 'answering a ping');
    } catch (e) {
      if (stopped) return;
      if (e && e.deadline && b.browser === br) {
        stopped = true;
        abandonBrowser(b);
        onStuck(`the browser stopped answering (no answer for ${Math.round((Date.now() - t0) / 1000)} s)`, STUCK_HINT);
        return;
      }
      sessFor = null;   // closed or replaced: a new session next time
    }
    if (!stopped) { timer = setTimeout(tick, every); timer.unref(); }
  };
  timer = setTimeout(tick, every);
  timer.unref();
  return () => { stopped = true; clearTimeout(timer); if (sess) sess.detach().catch(() => {}); };
}

/** openStage under openGuarded: b is a browser record (see openBrowser); its browser may be replaced once. */
export function openPage(b, o, opts = {}) {
  return openGuarded(b, (browser, track, pace) => openStage(browser, { ...o, pace, track }), opts);
}

// WebGL renderer strings of a CPU rasteriser: Chrome's SwiftShader, Mesa's llvmpipe/softpipe, Windows' WARP
// ("Microsoft Basic Render Driver").
export const SOFTWARE_GL = /swiftshader|llvmpipe|softpipe|basic render driver|\bwarp\b|software/i;

/**
 * The browser's WebGL renderer, from a blank page: {renderer, software}. software is true for a CPU rasteriser
 * (or when WebGL is missing), null when the page could not tell. Costs a fraction of a second.
 */
export async function glRenderer(browser) {
  let context = null;
  try {
    // one deadline for the whole probe: a browser that stopped answering (a busy machine) never answers
    // newContext or newPage either, and the render must not wait for it here (it gets a new one for its page)
    const renderer = await withTimeout((async () => {
      context = await browser.newContext({ viewport: { width: 64, height: 64 }, deviceScaleFactor: 1 });
      const page = await context.newPage();
      return page.evaluate(() => {
        const gl = document.createElement('canvas').getContext('webgl');
        if (!gl) return '';
        const ext = gl.getExtension('WEBGL_debug_renderer_info');
        return String(ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
      });
    })(), 30000, 'WebGL probe');
    return { renderer: renderer || 'none (no WebGL)', software: !renderer || SOFTWARE_GL.test(renderer) };
  } catch {
    return { renderer: 'unknown', software: null };
  } finally {
    if (context) await withTimeout(context.close(), 5000, 'closing the WebGL probe').catch(() => {});
  }
}

// ------------------------------------------------------------------ pace
// The page measures its own cost (runtime/stage.js, ST.pace(): the gaps between its frames while it gets ready,
// its first seeks) and scales its waits by a factor of 1-5. The host scales its deadlines (ready, seek, layer
// passes, render's page open) by the same factor, read while it waits, so a slow machine or a heavy page gets
// more time and a fast one keeps today's values. SHOWTIME_PACE=0 keeps every wait at its fixed value.
const PACE_ON = !['0', 'false', 'off', 'no'].includes(String(process.env.SHOWTIME_PACE || '').toLowerCase());
// tests only: shrinks every base wait (page and host) so a test can show a wait running out in seconds
const WAIT_SCALE = Number(process.env.SHOWTIME_TEST_WAIT_SCALE) > 0 ? Number(process.env.SHOWTIME_TEST_WAIT_SCALE) : 1;

/** A pace record shared by the deadlines of one page (and a caller such as render's page-open timeout). */
export function newPace() { return { factor: 1, page: null }; }
/** Take the page's ST.pace() report into a pace record; the factor never drops while the page stays open. */
export function notePace(pace, rep) {
  if (!pace || !rep || typeof rep !== 'object') return;
  pace.page = rep;
  const f = Number(rep.factor);
  if (PACE_ON && f > pace.factor) pace.factor = Math.min(f, 5);
}
/**
 * The record of render.json and check's report: the largest factor among the pages (1 = the fixed waits) and
 * what that page measured (frame_ms: median gap between its frames while it got ready; seek_ms: its first seeks).
 */
export function paceSummary(sessions) {
  let best = null;
  for (const s of sessions) if (s && s.pace && (!best || s.pace.factor > best.factor)) best = s.pace;
  const pg = (best && best.page) || {};
  return { factor: best ? best.factor : 1, frame_ms: pg.frame_ms ?? null, seek_ms: pg.seek_ms ?? null,
    ceiling: pg.ceiling ?? 5, ...(PACE_ON ? {} : { off: true }) };
}
/** ms for a base wait under the test scale (never shorter than base otherwise). */
export function baseWait(ms) { return ms * WAIT_SCALE; }

/**
 * withTimeout whose deadline is baseMs x the pace factor, read again while it waits: the page may report a
 * higher factor meanwhile (a browser that stopped answering never does, so it still times out).
 */
export function withPacedTimeout(p, baseMs, label, pace) {
  const t0 = Date.now();
  let timer;
  return Promise.race([
    p,
    new Promise((_, rej) => {
      const tick = () => {
        const f = pace && pace.factor > 1 ? pace.factor : 1;
        const lim = baseWait(baseMs) * f;
        const left = lim - (Date.now() - t0);
        if (left <= 0) {
          rej(Object.assign(new Error(`timed out after ${Math.round(lim / 1000)}s${f > 1 ? ` (x${f} for this page's pace)` : ''}: ${label}`), { deadline: label }));
          return;
        }
        timer = setTimeout(tick, Math.min(left, 1000));
      };
      tick();
    }),
  ]).finally(() => clearTimeout(timer));
}

/**
 * Open the project page in render mode.
 * @param browser  Playwright browser
 * @param o.url        http://127.0.0.1:port
 * @param o.page       page path relative to the project ('index.html')
 * @param o.config     showtime.json contents (plus CLI overrides applied)
 * @param o.override   {fps?, duration?} values that beat both showtime.json and ST.config
 * @param o.scale      device scale factor (output = viewport * scale)
 * @param o.alpha      transparent background
 * @param o.settle     'raf2' | 'raf1' | 'none' : how long a seek waits for paint
 * @param o.seed       base seed for Math.random
 * @param o.layers     answer the transition layer protocol (window.__stLayers): each pending layer is
 *                     screenshotted solo and handed back to the page for exact shader transitions (default true)
 * @param o.readyTimeout ms
 * @param o.size       "WxH" or "9:16": render the page at this size for this run (beats showtime.json)
 * @param o.followPageSize  reopen at the page's own ST.config size when nothing else sets one (default true)
 * @param o.init       extra init script source, run before the page's own scripts (check's WebGPU probe)
 * @param o.pace       a newPace() record to keep up to date while the page opens (render's open timeout reads it)
 * -> session { page, cdp, info, log, pace, close() }
 */
export async function openStage(browser, o) {
  const size = parseSize(o.size);
  o = o.pace ? o : { ...o, pace: newPace() };
  const track = o.track || {};
  const opts = size ? { ...o, override: { ...(o.override || {}), width: size.width, height: size.height } } : o;
  const sess = await openStageOnce(browser, opts);
  const cfg = o.config || {};
  const fixed = size || (o.override && (o.override.width || o.override.height)) || cfg.width || cfg.height;
  if (!fixed && o.followPageSize !== false && sess.info &&
      (sess.info.width !== sess.width || sess.info.height !== sess.height)) {
    // the page set its own size with ST.config and nothing else did: reopen at that size, so snap,
    // check, studio frames and exports see the page as render does (a 1080x1080 page is not stretched)
    const w = sess.info.width, h = sess.info.height;
    track.step = 'closing the page to reopen it at its own size';
    await sess.close();
    return openStageOnce(browser, { ...o, override: { ...(o.override || {}), width: w, height: h } });
  }
  return sess;
}

/** "1080x1920", "9:16" (height 1920 for the long side), {width, height} -> {width, height} | null */
export function parseSize(v) {
  if (!v) return null;
  if (typeof v === 'object' && v.width && v.height) return { width: Math.round(v.width), height: Math.round(v.height) };
  const s = String(v).trim().toLowerCase();
  let m = /^(\d{2,5})\s*[x×]\s*(\d{2,5})$/.exec(s);
  if (m) return { width: Number(m[1]), height: Number(m[2]) };
  m = /^(\d{1,2})\s*[:/]\s*(\d{1,2})$/.exec(s);
  if (m) {
    const a = Number(m[1]), b = Number(m[2]);
    if (!(a > 0 && b > 0)) return null;
    // the long side is 1920 (1080 for a square); both sides even
    const even = (x) => Math.round(x / 2) * 2;
    if (a === b) return { width: 1080, height: 1080 };
    return a > b ? { width: 1920, height: even(1920 * b / a) } : { width: even(1920 * a / b), height: 1920 };
  }
  throw new UserError(`--size must be WIDTHxHEIGHT (1080x1920) or an aspect (9:16, 1:1, 4:5), got "${v}"`);
}

async function openStageOnce(browser, o) {
  const cfg = o.config || {};
  const ov = o.override || {};
  const width = Math.round(Number(ov.width) || Number(cfg.width) || 1920);
  const height = Math.round(Number(ov.height) || Number(cfg.height) || 1080);
  const scale = Number(o.scale) || 1;
  // Chrome lays out a smaller viewport for a device scale factor < 1 instead of downscaling,
  // so downscaling happens in the capture (clip.scale); supersampling (> 1) uses the DSF.
  const dsf = scale > 1 ? scale : 1;
  const clipScale = scale < 1 ? scale : null;
  const track = o.track || {};
  track.step = 'creating the browser context';
  const context = await browser.newContext({
    viewport: { width, height }, deviceScaleFactor: dsf, colorScheme: 'light',
    reducedMotion: 'no-preference', locale: 'en-US', timezoneId: 'UTC', serviceWorkers: 'block',
  });
  track.step = 'opening a tab';
  const page = await context.newPage();
  const log = { console: [], errors: [], requests: [], failed: [], blocked: [], http: [], cancelled: 0 };
  const ring = (arr, v, max = 200) => { arr.push(v); if (arr.length > max) arr.shift(); };
  page.on('console', (m) => {
    const type = m.type();
    if (type === 'error' || type === 'warning' || type === 'warn') {
      const loc = m.location ? m.location() : null;
      ring(log.console, { type: type === 'warn' ? 'warning' : type, text: m.text().slice(0, 500), url: loc && loc.url ? loc.url : '', line: loc ? loc.lineNumber : null });
    }
  });
  page.on('pageerror', (e) => ring(log.errors, { message: String(e.message || e).slice(0, 500), stack: String(e.stack || '').split('\n').slice(0, 4).join('\n') }));
  page.on('requestfailed', (r) => {
    const f = r.failure();
    const error = f ? f.errorText : 'failed';
    // a load cancelled while it ran (an image whose src changed again before it arrived, as when check scrubs a
    // page that swaps pictures) is not a failure: counted, and kept out of the ring so it never pushes real
    // failures out of it
    if (/ERR_ABORTED/.test(error)) { log.cancelled++; return; }
    if (!log.blocked.includes(r.url())) ring(log.failed, { url: r.url(), error });
  });
  page.on('response', (r) => { if (r.status() >= 400) ring(log.http, { url: r.url(), status: r.status() }); });
  page.on('request', (r) => ring(log.requests, r.url(), 500));
  track.step = 'setting up the tab';
  await page.route('**/*', (route) => {
    const u = route.request().url();
    if (isLocalUrl(u)) return route.continue();
    if (!log.blocked.includes(u)) log.blocked.push(u);
    return route.abort('blockedbyclient');
  });
  const layers = o.layers !== false;
  const renderCfg = {
    config: cfg, override: o.override || null, alpha: !!o.alpha, settle: o.settle || 'raf1', layers,
    seed: o.seed === undefined ? (cfg.seed === undefined ? 1 : cfg.seed) : o.seed,
    ...(PACE_ON ? {} : { pace: false }), ...(WAIT_SCALE !== 1 ? { waitScale: WAIT_SCALE } : {}),
    // the render's GPU-or-not decision for the looks (runtime/effects/gl.js softwareGL), the same in every worker
    ...(typeof o.softwareGL === 'boolean' ? { softwareGL: o.softwareGL } : {}),
  };
  const pace = o.pace || newPace();
  await page.addInitScript({ content: `window.__ST_RENDER__=${JSON.stringify(renderCfg)};\n${stageSource()}` });
  if (o.init) await page.addInitScript({ content: String(o.init) });
  const cdp = await context.newCDPSession(page);
  const target = `${o.url}/${String(o.page || 'index.html').replace(/^\/+/, '')}`;
  track.step = 'loading the page';
  try {
    await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 60000 });
  } catch (e) {
    await context.close().catch(() => {});
    throw new UserError(`could not open ${target}: ${e.message.split('\n')[0]}`);
  }
  if (o.alpha) await cdp.send('Emulation.setDefaultBackgroundColorOverride', { color: { r: 0, g: 0, b: 0, a: 0 } });
  let info;
  // while the page gets ready, read its pace every second (a page busy in a long task answers when it is done)
  let polling = null;
  const poll = setInterval(() => {
    if (polling) return;
    polling = page.evaluate(() => (window.ST && typeof window.ST.pace === 'function' ? window.ST.pace() : null))
      .then((r) => notePace(pace, r), () => {}).finally(() => { polling = null; });
  }, 1000);
  track.step = 'waiting for the page to be ready';
  try {
    info = await withPacedTimeout(page.evaluate(() => window.ST.ready()), o.readyTimeout || 120000, 'the page never became ready', pace);
    notePace(pace, info && info.pace);
  } catch (e) {
    const d = await page.evaluate(() => (window.ST ? window.ST.diag() : null)).catch(() => null);
    const pend = d && d.waits ? d.waits.filter((w) => w.state === 'pending').map((w) => w.label) : [];
    const firstErr = log.errors[0] ? ` First page error: ${log.errors[0].message}` : '';
    await context.close().catch(() => {});
    throw new UserError(`${String(e.message || e).split('\n')[0].replace(/^page\.evaluate: (Error: )?/, '')}` +
      (pend.length ? ` (still waiting for: ${pend.join(', ')})` : '') + firstErr,
      'run `showtime check <project>` for the full list of page errors');
  } finally {
    clearInterval(poll);
  }
  const sess = {
    page, cdp, context, info, log, width, height, scale, pace,
    /** Seek; the deadline is timeoutMs x the page's pace factor. */
    async seek(t, timeoutMs = 60000) {
      const r = await withPacedTimeout(page.evaluate(async (x) => {
        await window.ST.seek(x);
        const L = window.__stLayers;
        return { pending: L && typeof L.pending === 'function' ? L.pending() : null,
          pace: typeof window.ST.pace === 'function' ? window.ST.pace() : null };
      }, t), timeoutMs, `seek to ${t.toFixed(3)}s`, pace);
      notePace(pace, r && r.pace);
      const pending = r && r.pending;
      if (layers && pending && pending.length) await this.layerPass(pending, timeoutMs);
      return t;
    },
    /** Transition layer protocol: screenshot each layer on its own, hand it back, let the page compose. */
    async layerPass(pending, timeoutMs = 60000) {
      const fmt = o.alpha ? 'png' : 'jpeg';
      for (const { id } of pending) {
        const ok = await page.evaluate(async (i) => { const r = window.__stLayers.solo(i); await window.ST._paint(); return r; }, id);
        if (!ok) continue;
        const img = await this.shot({ format: fmt, quality: 95, scale: 1 / dsf });
        const url = `data:image/${fmt};base64,${img.toString('base64')}`;
        await withPacedTimeout(page.evaluate(([i, u]) => window.__stLayers.put(i, u), [id, url]), timeoutMs, `layer ${id}`, pace);
      }
      await withPacedTimeout(page.evaluate(async () => { await window.__stLayers.compose(); await window.ST._paint(); }), timeoutMs, 'layer compose', pace);
    },
    /** Screenshot of the viewport: Buffer. */
    async shot({ format = 'jpeg', quality = 92, scale: s } = {}) {
      const params = { format, fromSurface: true, captureBeyondViewport: false };
      if (format === 'jpeg' || format === 'webp') { params.quality = quality; params.optimizeForSpeed = true; }
      else params.optimizeForSpeed = !o.alpha; // lossless either way; the fast PNG path crushes alpha to 0/255
      const cs = s !== undefined ? s : clipScale;
      if (cs && cs !== 1) params.clip = { x: 0, y: 0, width, height, scale: cs };
      const r = await cdp.send('Page.captureScreenshot', params);
      return Buffer.from(r.data, 'base64');
    },
    async diag() { return page.evaluate(() => window.ST.diag()); },
    async close() { await context.close().catch(() => {}); },
  };
  return sess;
}

export function withTimeout(p, ms, label) {
  let timer;
  return Promise.race([
    p,
    new Promise((_, rej) => { timer = setTimeout(() => rej(Object.assign(new Error(`timed out after ${Math.round(ms / 1000)}s: ${label}`), { deadline: label })), ms); }),
  ]).finally(() => clearTimeout(timer));
}

/** Save a screenshot, the DOM and the log tail next to a failure, for debugging. */
export async function writeDiagnostics(sess, dir, tag) {
  try {
    fs.mkdirSync(dir, { recursive: true });
    const png = await sess.shot({ format: 'png' }).catch(() => null);
    if (png) fs.writeFileSync(path.join(dir, `${tag}.png`), png);
    const html = await sess.page.content().catch(() => '');
    if (html) fs.writeFileSync(path.join(dir, `${tag}.html`), html);
    const d = await sess.diag().catch(() => null);
    fs.writeFileSync(path.join(dir, `${tag}.json`), JSON.stringify({ log: sess.log, diag: d }, null, 2));
    return dir;
  } catch { return null; }
}

/**
 * Pull the offline-rendered ST.score as Float32 channels (chunked base64 transfer).
 * -> { channels: [Float32Array, Float32Array], sampleRate, peak } | null when the page has no score
 */
export async function pullScore(page, { duration, sampleRate = 48000 }) {
  const meta = await page.evaluate(async ({ duration, sampleRate }) => {
    if (typeof window.ST.score !== 'function') return null;
    const buf = await window.ST.renderScore({ duration, sampleRate });
    if (!buf) return null;
    window.__stScoreBuf = buf;
    let peak = 0;
    for (let c = 0; c < buf.numberOfChannels; c++) {
      const d = buf.getChannelData(c);
      for (let i = 0; i < d.length; i++) { const a = Math.abs(d[i]); if (a > peak) peak = a; }
    }
    return { length: buf.length, channels: buf.numberOfChannels, sampleRate: buf.sampleRate, peak };
  }, { duration, sampleRate });
  if (!meta) return null;
  const channels = [];
  const CHUNK = 48000 * 8;
  for (let c = 0; c < meta.channels; c++) {
    const out = new Float32Array(meta.length);
    for (let off = 0; off < meta.length; off += CHUNK) {
      const b64 = await page.evaluate(({ c, off, n }) => {
        const d = window.__stScoreBuf.getChannelData(c).subarray(off, off + n);
        const u8 = new Uint8Array(d.buffer, d.byteOffset, d.byteLength);
        let s = '';
        for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
        return btoa(s);
      }, { c, off, n: Math.min(CHUNK, meta.length - off) });
      const bytes = Buffer.from(b64, 'base64');
      out.set(new Float32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4), off);
    }
    channels.push(out);
  }
  await page.evaluate(() => { delete window.__stScoreBuf; });
  if (channels.length === 1) channels.push(channels[0]);
  return { channels, sampleRate: meta.sampleRate, peak: meta.peak };
}

/**
 * A blank page served by our server, for image math (diffs, contact sheets, colour sampling). b: a browser record
 * (openBrowser; opened under openGuarded, its browser may be replaced once) or a bare Playwright browser.
 */
export async function openLab(b, url, opts = {}) {
  if (b && b.browser) return openGuarded(b, (browser, track) => openLabOn(browser, url, track), { label: 'opening the image lab page', ...opts });
  return openLabOn(b, url, {});
}

async function openLabOn(browser, url, track) {
  track.step = 'creating the browser context';
  const context = await browser.newContext({ viewport: { width: 800, height: 600 }, deviceScaleFactor: 1 });
  track.step = 'opening a tab';
  const page = await context.newPage();
  track.step = 'loading the page';
  await page.goto(`${url}/_st/lab`, { waitUntil: 'load' });
  await page.addScriptTag({ content: LAB_JS });
  return {
    page,
    async close() { await context.close().catch(() => {}); },
    /** Pixel difference between two images. -> {same, changed, maxDelta, meanDelta, width, height} */
    diff(a, b, tol = 8) {
      return page.evaluate(([a, b, tol]) => window.__lab.diff(a, b, tol), [a.toString('base64'), b.toString('base64'), tol]);
    },
    /** Tiny grayscale signature per image (for motion / dead-air checks). */
    signatures(bufs, w = 48, h = 27) {
      return page.evaluate(([list, w, h]) => window.__lab.signatures(list, w, h), [bufs.map((b) => b.toString('base64')), w, h]);
    },
    /** Median colour inside each box [{x,y,w,h}] of an image. */
    boxColors(buf, boxes) {
      return page.evaluate(([b, boxes]) => window.__lab.boxColors(b, boxes), [buf.toString('base64'), boxes]);
    },
    /** Mean absolute RGB difference inside each box between two same-size images. */
    boxDiff(a, b, boxes) {
      return page.evaluate(([a, b, boxes]) => window.__lab.boxDiff(a, b, boxes), [a.toString('base64'), b.toString('base64'), boxes]);
    },
    /** Contact sheet: [{buf, label}] -> JPEG Buffer */
    async sheet(items, o = {}) {
      const b64 = await page.evaluate(([list, o]) => window.__lab.sheet(list, o), [items.map((i) => ({ b: i.buf.toString('base64'), label: i.label || '', sub: i.sub || '' })), o]);
      return Buffer.from(b64, 'base64');
    },
    /** Encode an image buffer to JPEG/PNG at a given width. */
    async resize(buf, width, type = 'image/jpeg', quality = 0.9) {
      const b64 = await page.evaluate(([b, w, t, q]) => window.__lab.resize(b, w, t, q), [buf.toString('base64'), width, type, quality]);
      return Buffer.from(b64, 'base64');
    },
  };
}

// Runs inside the lab page.
const LAB_JS = `
(function(){
  function load(b64){
    var bin = atob(b64), u = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
    return createImageBitmap(new Blob([u]));
  }
  function pixels(bmp, w, h){
    var c = new OffscreenCanvas(w || bmp.width, h || bmp.height), g = c.getContext('2d', { willReadFrequently: true });
    g.imageSmoothingQuality = 'high';
    g.drawImage(bmp, 0, 0, c.width, c.height);
    return g.getImageData(0, 0, c.width, c.height);
  }
  function toB64(blob){
    return blob.arrayBuffer().then(function(ab){
      var u = new Uint8Array(ab), s = '';
      for (var i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
      return btoa(s);
    });
  }
  var fontReady = null;
  function labelFont(){
    if (fontReady) return fontReady;
    var f = new FontFace('stlab', 'url(/_lib/@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2)');
    fontReady = f.load().then(function(ff){ document.fonts.add(ff); return 'stlab'; }).catch(function(){ return 'monospace'; });
    return fontReady;
  }
  window.__lab = {
    diff: async function(a, b, tol){
      var A = await load(a), B = await load(b);
      if (A.width !== B.width || A.height !== B.height) return { same: false, changed: -1, maxDelta: 255, meanDelta: 255, width: A.width, height: A.height, sizeMismatch: true };
      var W = A.width, H = A.height, pa = pixels(A).data, pb = pixels(B).data, changed = 0, max = 0, sum = 0;
      var mask = new Uint8Array(W * H);
      for (var i = 0, j = 0; i < pa.length; i += 4, j++) {
        var d = Math.max(Math.abs(pa[i]-pb[i]), Math.abs(pa[i+1]-pb[i+1]), Math.abs(pa[i+2]-pb[i+2]), Math.abs(pa[i+3]-pb[i+3]));
        if (d > max) max = d;
        sum += d;
        if (d > tol) { changed++; mask[j] = 1; }
      }
      // "solid" changes: changed pixels whose 8 neighbours changed too. Moved or recoloured
      // objects produce solid regions; rasterisation noise only touches thin edges.
      var core = 0;
      if (changed) for (var y = 1; y < H - 1; y++) for (var x = 1; x < W - 1; x++) {
        var k = y * W + x;
        if (mask[k] && mask[k-1] && mask[k+1] && mask[k-W] && mask[k+W] && mask[k-W-1] && mask[k-W+1] && mask[k+W-1] && mask[k+W+1]) core++;
      }
      var n = W * H;
      return { same: max === 0, changed: changed, changedPct: 100 * changed / n, solid: core, solidPct: 100 * core / n, maxDelta: max, meanDelta: sum / n, width: W, height: H };
    },
    signatures: async function(list, w, h){
      var out = [];
      for (var k = 0; k < list.length; k++) {
        var px = pixels(await load(list[k]), w, h).data, sig = new Array(w * h);
        for (var i = 0, j = 0; i < px.length; i += 4, j++) sig[j] = Math.round(0.2126 * px[i] + 0.7152 * px[i+1] + 0.0722 * px[i+2]);
        out.push(sig);
      }
      return out;
    },
    boxColors: async function(b64, boxes){
      var bmp = await load(b64), img = pixels(bmp), W = img.width, H = img.height, d = img.data, out = [];
      for (var k = 0; k < boxes.length; k++) {
        var bx = boxes[k], x0 = Math.max(0, Math.floor(bx.x)), y0 = Math.max(0, Math.floor(bx.y));
        var x1 = Math.min(W, Math.ceil(bx.x + bx.w)), y1 = Math.min(H, Math.ceil(bx.y + bx.h));
        var rs = [], gs = [], bs = [], step = Math.max(1, Math.floor(Math.sqrt(((x1-x0)*(y1-y0)) / 4000)));
        for (var y = y0; y < y1; y += step) for (var x = x0; x < x1; x += step) { var i = (y * W + x) * 4; rs.push(d[i]); gs.push(d[i+1]); bs.push(d[i+2]); }
        if (!rs.length) { out.push(null); continue; }
        var by = function(p, q){ return p - q; };
        rs.sort(by); gs.sort(by); bs.sort(by);
        var at = function(a, f){ return a[Math.min(a.length - 1, Math.floor(a.length * f))]; };
        out.push({ median: [at(rs, 0.5), at(gs, 0.5), at(bs, 0.5)], p10: [at(rs, 0.1), at(gs, 0.1), at(bs, 0.1)],
          p90: [at(rs, 0.9), at(gs, 0.9), at(bs, 0.9)], n: rs.length });
      }
      return out;
    },
    boxDiff: async function(a, b, boxes){
      var A = pixels(await load(a)), B = pixels(await load(b));
      if (A.width !== B.width || A.height !== B.height) return boxes.map(function(){ return null; });
      var W = A.width, H = A.height, da = A.data, db = B.data;
      return boxes.map(function(bx){
        var x0 = Math.max(0, Math.floor(bx.x)), y0 = Math.max(0, Math.floor(bx.y)), x1 = Math.min(W, Math.ceil(bx.x + bx.w)), y1 = Math.min(H, Math.ceil(bx.y + bx.h));
        var s = 0, n = 0;
        for (var y = y0; y < y1; y++) for (var x = x0; x < x1; x++) { var i = (y * W + x) * 4; s += (Math.abs(da[i]-db[i]) + Math.abs(da[i+1]-db[i+1]) + Math.abs(da[i+2]-db[i+2])) / 3; n++; }
        return n ? s / n : null;
      });
    },
    resize: async function(b64, width, type, q){
      var bmp = await load(b64), w = Math.max(1, Math.round(width)), h = Math.round(bmp.height * w / bmp.width);
      var c = new OffscreenCanvas(w, h), g = c.getContext('2d');
      g.imageSmoothingQuality = 'high'; g.drawImage(bmp, 0, 0, w, h);
      return toB64(await c.convertToBlob({ type: type, quality: q }));
    },
    sheet: async function(list, o){
      var font = await labelFont();
      var cols = o.cols || Math.min(4, list.length), tw = o.thumb || 480, pad = 10, lab = 26;
      var bmps = [];
      for (var i = 0; i < list.length; i++) bmps.push(await load(list[i].b));
      var th = Math.round(tw * bmps[0].height / bmps[0].width);
      var rows = Math.ceil(list.length / cols), head = o.title ? 34 : 0;
      var c = new OffscreenCanvas(pad + cols * (tw + pad), head + pad + rows * (th + lab + pad)), g = c.getContext('2d');
      g.fillStyle = '#16181d'; g.fillRect(0, 0, c.width, c.height);
      g.textBaseline = 'middle';
      if (o.title) { g.fillStyle = '#e8eaf0'; g.font = '600 16px ' + font; g.fillText(o.title, pad, 20); }
      g.imageSmoothingQuality = 'high';
      for (var k = 0; k < list.length; k++) {
        var x = pad + (k % cols) * (tw + pad), y = head + pad + Math.floor(k / cols) * (th + lab + pad);
        g.fillStyle = '#000'; g.fillRect(x, y, tw, th);
        g.drawImage(bmps[k], x, y, tw, th);
        g.strokeStyle = '#2d3039'; g.strokeRect(x + 0.5, y + 0.5, tw - 1, th - 1);
        g.fillStyle = '#e8eaf0'; g.font = '600 14px ' + font; g.fillText(list[k].label, x + 2, y + th + lab / 2);
        if (list[k].sub) { g.fillStyle = '#9aa0ad'; g.font = '400 12px ' + font; g.textAlign = 'right'; g.fillText(list[k].sub, x + tw - 2, y + th + lab / 2); g.textAlign = 'left'; }
      }
      return toB64(await c.convertToBlob({ type: 'image/jpeg', quality: 0.88 }));
    }
  };
})();`;

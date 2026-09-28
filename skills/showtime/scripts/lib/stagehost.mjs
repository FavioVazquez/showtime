// Open a showtime project page in a headless browser with the render-mode stage runtime
// injected before any page script, then seek and capture frames. Shared by render, check
// and snap so every tool sees exactly the same pixels.
import fs from 'node:fs';
import path from 'node:path';
import { skillDir } from './deps.mjs';
import { launchBrowser } from './chrome.mjs';
import { UserError } from './cli.mjs';

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
 * -> { browser, kind, version, executablePath, flags }
 */
// Extra flags for capture on top of the shared set (scripts/lib/chrome-flags.json).
// --disable-lcd-text: text in composited layers is always grayscale-antialiased while text in the
// root layer may use LCD antialiasing, so a frame's pixels would depend on whether an element was
// promoted to a layer earlier (e.g. by a blur animation) -> frames would differ between workers.
export const CAPTURE_ARGS = ['--disable-lcd-text'];

export async function openBrowser({ gpu = 'auto', headless = true, args = [] } = {}) {
  const extra = [...CAPTURE_ARGS, ...args];
  try {
    return await launchBrowser({ gpu, headless, args: extra });
  } catch (e) {
    if (gpu === 'off') throw e;
    return launchBrowser({ gpu: 'off', headless, args: extra });
  }
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
 * -> session { page, cdp, info, log, close() }
 */
export async function openStage(browser, o) {
  const size = parseSize(o.size);
  const opts = size ? { ...o, override: { ...(o.override || {}), width: size.width, height: size.height } } : o;
  const sess = await openStageOnce(browser, opts);
  const cfg = o.config || {};
  const fixed = size || (o.override && (o.override.width || o.override.height)) || cfg.width || cfg.height;
  if (!fixed && o.followPageSize !== false && sess.info &&
      (sess.info.width !== sess.width || sess.info.height !== sess.height)) {
    // the page set its own size with ST.config and nothing else did: reopen at that size, so snap,
    // check, studio frames and exports see the page as render does (a 1080x1080 page is not stretched)
    const w = sess.info.width, h = sess.info.height;
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
  const context = await browser.newContext({
    viewport: { width, height }, deviceScaleFactor: dsf, colorScheme: 'light',
    reducedMotion: 'no-preference', locale: 'en-US', timezoneId: 'UTC', serviceWorkers: 'block',
  });
  const page = await context.newPage();
  const log = { console: [], errors: [], requests: [], failed: [], blocked: [], http: [] };
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
    if (!log.blocked.includes(r.url())) ring(log.failed, { url: r.url(), error: f ? f.errorText : 'failed' });
  });
  page.on('response', (r) => { if (r.status() >= 400) ring(log.http, { url: r.url(), status: r.status() }); });
  page.on('request', (r) => ring(log.requests, r.url(), 500));
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
  };
  await page.addInitScript({ content: `window.__ST_RENDER__=${JSON.stringify(renderCfg)};\n${stageSource()}` });
  const cdp = await context.newCDPSession(page);
  const target = `${o.url}/${String(o.page || 'index.html').replace(/^\/+/, '')}`;
  try {
    await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 60000 });
  } catch (e) {
    await context.close().catch(() => {});
    throw new UserError(`could not open ${target}: ${e.message.split('\n')[0]}`);
  }
  if (o.alpha) await cdp.send('Emulation.setDefaultBackgroundColorOverride', { color: { r: 0, g: 0, b: 0, a: 0 } });
  let info;
  try {
    info = await withTimeout(page.evaluate(() => window.ST.ready()), o.readyTimeout || 120000, 'the page never became ready');
  } catch (e) {
    const d = await page.evaluate(() => (window.ST ? window.ST.diag() : null)).catch(() => null);
    const pend = d && d.waits ? d.waits.filter((w) => w.state === 'pending').map((w) => w.label) : [];
    const firstErr = log.errors[0] ? ` First page error: ${log.errors[0].message}` : '';
    await context.close().catch(() => {});
    throw new UserError(`${String(e.message || e).split('\n')[0].replace(/^page\.evaluate: (Error: )?/, '')}` +
      (pend.length ? ` (still waiting for: ${pend.join(', ')})` : '') + firstErr,
      'run `showtime check <project>` for the full list of page errors');
  }
  const sess = {
    page, cdp, context, info, log, width, height, scale,
    async seek(t, timeoutMs = 60000) {
      const pending = await withTimeout(page.evaluate(async (x) => {
        await window.ST.seek(x);
        const L = window.__stLayers;
        return L && typeof L.pending === 'function' ? L.pending() : null;
      }, t), timeoutMs, `seek to ${t.toFixed(3)}s`);
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
        await withTimeout(page.evaluate(([i, u]) => window.__stLayers.put(i, u), [id, url]), timeoutMs, `layer ${id}`);
      }
      await withTimeout(page.evaluate(async () => { await window.__stLayers.compose(); await window.ST._paint(); }), timeoutMs, 'layer compose');
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
    new Promise((_, rej) => { timer = setTimeout(() => rej(new Error(`timed out after ${Math.round(ms / 1000)}s: ${label}`)), ms); }),
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

/** A blank page served by our server, for image math (diffs, contact sheets, colour sampling). */
export async function openLab(browser, url) {
  const context = await browser.newContext({ viewport: { width: 800, height: 600 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
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

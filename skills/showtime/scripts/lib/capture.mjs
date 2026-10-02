// Shared browser-capture helpers for site.mjs and demo.mjs:
// contexts with realistic settings, cookie/consent handling (@duckduckgo/autoconsent, loaded
// by file path), robust navigation, bot-wall detection (report only, never bypass), lazy-load
// scrolling, overlay cleanup, SSRF-safe bounded downloads and HTML contact sheets.
import fs from 'node:fs';
import path from 'node:path';
import dns from 'node:dns';
import net from 'node:net';
import { pathToFileURL } from 'node:url';
import { depPath } from './deps.mjs';
import { UserError } from './cli.mjs';
import { realpathUnderRoot, symlinkRefusal, escapesBySymlink } from './pathguard.mjs';

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------------------------
// aspect ratios -> viewports

/**
 * "16:9" -> { name, css: {width, height}, dpr, mobile }
 * Landscape and square use a desktop layout (1440 / 1080 CSS px wide); portrait uses a phone
 * layout (390 CSS px wide, touch, DPR 3) because that is what a 9:16 viewer expects.
 */
export function aspectViewport(spec, { dpr, width } = {}) {
  const m = /^\s*(\d+(?:\.\d+)?)\s*[:x/]\s*(\d+(?:\.\d+)?)\s*$/.exec(String(spec));
  if (!m) throw new UserError(`not an aspect ratio: "${spec}"`, 'use W:H, e.g. 16:9, 9:16, 1:1, 4:5');
  const a = Number(m[1]) / Number(m[2]);
  if (!(a > 0.2 && a < 5)) throw new UserError(`aspect ratio out of range: ${spec}`);
  const name = `${m[1]}x${m[2]}`;
  if (a < 0.95) {
    const w = width || 390;
    return { name, spec, css: { width: w, height: Math.round(w / a) }, dpr: dpr || 3, mobile: true };
  }
  const w = width || (a < 1.05 ? 1080 : 1440);
  return { name, spec, css: { width: w, height: Math.round(w / a) }, dpr: dpr || 2, mobile: false };
}

/** 'mac' | 'windows' | 'linux' for this machine. */
export function hostPlatform() {
  return process.platform === 'darwin' ? 'mac' : process.platform === 'win32' ? 'windows' : 'linux';
}

export function chromeUA(version, { mobile = false, platform = null } = {}) {
  const v = String(version || '140.0.0.0').replace(/^[^\d]*/, '');
  if (mobile) return `Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${v} Mobile Safari/537.36`;
  const os = platform || hostPlatform();
  const plat = os === 'mac' ? 'Macintosh; Intel Mac OS X 10_15_7'
    : os === 'windows' ? 'Windows NT 10.0; Win64; x64' : 'X11; Linux x86_64';
  return `Mozilla/5.0 (${plat}) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${v} Safari/537.36`;
}

/**
 * Make a context look like another OS to the page: user agent, navigator.platform and
 * navigator.userAgentData.platform. Apps that pick shortcut labels or modifier keys from the platform
 * (Cmd K on a Mac, Ctrl K elsewhere) then behave the same whatever machine records.
 */
export async function emulatePlatform(ctx, platform) {
  const nav = { mac: ['MacIntel', 'macOS'], windows: ['Win32', 'Windows'], linux: ['Linux x86_64', 'Linux'] }[platform];
  if (!nav) throw new UserError(`--platform must be mac, windows or linux (got ${platform})`);
  await ctx.addInitScript(([p, uad]) => {
    try { Object.defineProperty(Navigator.prototype, 'platform', { get: () => p, configurable: true }); } catch { /* ignore */ }
    try {
      const d = navigator.userAgentData;
      if (d) Object.defineProperty(d, 'platform', { get: () => uad, configurable: true });
    } catch { /* ignore */ }
  }, nav);
}

/** A browser context configured for clean captures. */
export async function newCaptureContext(browser, vp, { dark = false, locale = 'en-US', userAgent, reducedMotion = 'no-preference', extraHTTPHeaders } = {}) {
  const ua = userAgent || chromeUA(browser.version(), { mobile: vp.mobile });
  return browser.newContext({
    viewport: vp.css,
    deviceScaleFactor: vp.dpr,
    isMobile: !!vp.mobile,
    hasTouch: !!vp.mobile,
    colorScheme: dark ? 'dark' : 'light',
    reducedMotion,
    locale,
    userAgent: ua,
    ignoreHTTPSErrors: false,
    serviceWorkers: 'block',
    extraHTTPHeaders,
  });
}

// ---------------------------------------------------------------------------------------------
// cookie / consent banners

let _ac = null;
function autoconsentFiles() {
  if (_ac !== null) return _ac;
  try {
    const script = fs.readFileSync(depPath('@duckduckgo/autoconsent', 'dist', 'autoconsent.playwright.js'), 'utf8');
    const rules = JSON.parse(fs.readFileSync(depPath('@duckduckgo/autoconsent', 'rules', 'rules.json'), 'utf8'));
    _ac = { script, rules };
  } catch {
    _ac = false;
  }
  return _ac;
}

/**
 * Install autoconsent on a context (opt-out of non-essential cookies, the privacy-preserving
 * choice). Returns a log array that fills with {type, cmp, url} as banners are handled.
 */
export async function installConsent(context, { action = 'optOut' } = {}) {
  const log = [];
  const files = autoconsentFiles();
  if (!files) { log.push({ type: 'unavailable', detail: '@duckduckgo/autoconsent not installed' }); return log; }
  const config = {
    enabled: true, autoAction: action, disabledCmps: [], enablePrehide: true, enableCosmeticRules: true,
    enableGeneratedRules: true, enableHeuristicDetection: true, heuristicMode: 'tier2', detectRetries: 20,
    isMainWorld: false, prehideTimeout: 2000,
    logs: { lifecycle: false, rulesteps: false, detectionsteps: false, evals: false, errors: false, messages: false, waits: false },
  };
  await context.exposeBinding('autoconsentSendMessage', async (source, msg) => {
    if (!msg || typeof msg !== 'object') return;
    const frame = source.frame;
    const send = (m) => frame.evaluate((x) => window.autoconsentReceiveMessage && window.autoconsentReceiveMessage(x), m).catch(() => {});
    if (msg.type === 'init') return send({ type: 'initResp', config, rules: files.rules });
    if (msg.type === 'eval') {
      let result = false;
      try { result = await frame.evaluate(msg.code); } catch { result = false; }
      return send({ type: 'evalResp', id: msg.id, result });
    }
    if (['cmpDetected', 'popupFound', 'optOutResult', 'optInResult', 'autoconsentDone', 'autoconsentError'].includes(msg.type)) {
      log.push({ type: msg.type, cmp: msg.cmp || null, result: msg.result ?? null, url: msg.url || null });
    }
  });
  await context.addInitScript({ content: files.script });
  return log;
}

/** Wait until autoconsent finished (or nothing was detected) — bounded. */
export async function waitConsent(log, ms = 4000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if (log.some((e) => e.type === 'autoconsentDone' || e.type === 'optOutResult' || e.type === 'autoconsentError')) return;
    if (!log.some((e) => e.type === 'cmpDetected' || e.type === 'popupFound') && Date.now() - t0 > 1500) return;
    await sleep(200);
  }
}

/**
 * Fallback cleanup after autoconsent: click "reject/decline/close" inside cookie or consent
 * containers, then hide big fixed/sticky overlays that are not the site header.
 * Returns what it did (for the inventory).
 */
export async function cleanupOverlays(page, { hide = true } = {}) {
  return page.evaluate((hideOverlays) => {
    const done = { clicked: [], hidden: [] };
    const words = /^(reject|reject all|decline|deny|refuse|necessary only|only necessary|essential only|close|dismiss|no thanks|not now|×|✕|x)$/i;
    const scope = '[id*=cookie i],[class*=cookie i],[id*=consent i],[class*=consent i],[id*=gdpr i],[class*=gdpr i],[aria-label*=cookie i],[role=dialog],[aria-modal=true],[class*=banner i],[class*=popup i],[class*=modal i]';
    for (const root of document.querySelectorAll(scope)) {
      const r = root.getBoundingClientRect();
      if (r.width < 50 || r.height < 20) continue;
      for (const b of root.querySelectorAll('button,[role=button],a')) {
        const t = (b.innerText || b.getAttribute('aria-label') || '').trim();
        if (t && t.length < 40 && words.test(t)) {
          try { b.click(); done.clicked.push(t); } catch { /* ignore */ }
          break;
        }
      }
    }
    if (hideOverlays) {
      const vw = innerWidth, vh = innerHeight;
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
      let n = 0, el;
      while ((el = walker.nextNode()) && n++ < 5000) {
        const r = el.getBoundingClientRect();
        if (r.height < 40 || r.width < 40) continue;
        const cs = getComputedStyle(el);
        if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
        if (el.closest('header,nav,[role=banner],[role=navigation]')) continue;
        const named = /cookie|consent|gdpr|modal|popup|newsletter|subscribe|chat|widget|intercom|drift|crisp|hubspot|zendesk|launcher|toast|promo/i.test(el.id + ' ' + (typeof el.className === 'string' ? el.className : ''));
        if (!named && (r.height < 80 || r.width < vw * 0.3)) continue;
        const z = parseInt(cs.zIndex, 10);
        const covers = r.height > vh * 0.25 || named;
        if ((isNaN(z) || z < 100) && !covers) continue;
        if (r.top < 2 && r.height < 140 && cs.position === 'sticky') continue; // a sticky nav bar
        // an app's own dialog (a command palette the URL opened, an editor panel) is the subject,
        // not an obstruction: keep it unless it looks like consent / newsletter / promo
        const txt = (el.innerText || '').slice(0, 300);
        const appDialog = (el.matches('[role=dialog],[aria-modal=true],dialog') || el.querySelector('input,textarea,[contenteditable]'))
          && !/cookie|consent|gdpr|newsletter|subscribe|promo|sign up|signup|chat|intercom|drift|crisp|hubspot|zendesk|launcher|widget/i.test(el.id + ' ' + (typeof el.className === 'string' ? el.className : '') + ' ' + txt);
        const label = el.id ? '#' + el.id : el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/)[0] : '');
        if (appDialog) { (done.kept = done.kept || []).push(`${label} (${Math.round(r.width)}x${Math.round(r.height)}, app dialog)`); continue; }
        el.setAttribute('data-st-hidden', '1');
        el.style.setProperty('display', 'none', 'important');
        done.hidden.push(`${label} (${Math.round(r.width)}x${Math.round(r.height)})`);
      }
      if (document.body && getComputedStyle(document.body).overflow === 'hidden' && done.hidden.length) {
        document.body.style.setProperty('overflow', 'auto', 'important');
        document.documentElement.style.setProperty('overflow', 'auto', 'important');
      }
    }
    return done;
  }, hide).catch(() => ({ clicked: [], hidden: [] }));
}

// ---------------------------------------------------------------------------------------------
// navigation + bot walls

const WALL_TITLES = /(just a moment|attention required|access denied|403 forbidden|forbidden|verify you are human|are you a robot|checking your browser|pardon our interruption|request unsuccessful|security check|captcha|ddos protection|bot verification|please verify)/i;

/** Load a URL with fallbacks. -> { response, status, finalUrl, warnings } */
export async function robustGoto(page, url, { timeout = 45000, settle = 1500 } = {}) {
  const warnings = [];
  let response = null;
  try {
    response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout });
  } catch (e) {
    const msg = String(e.message || e);
    if (/ERR_NAME_NOT_RESOLVED/.test(msg)) throw new UserError(`could not resolve the host of ${url}`, 'check the URL spelling and your internet connection');
    if (/ERR_CONNECTION_REFUSED/.test(msg)) throw new UserError(`connection refused: ${url}`, 'is the site (or your local dev server) running?');
    if (/ERR_CERT|SSL/.test(msg)) throw new UserError(`TLS/certificate error for ${url}`, 'the site has an invalid certificate; showtime does not ignore certificate errors');
    if (/Timeout/i.test(msg)) {
      warnings.push(`page did not finish loading within ${Math.round(timeout / 1000)}s; captured what was there`);
    } else {
      throw e;
    }
  }
  await page.waitForLoadState('load', { timeout: Math.min(15000, timeout) }).catch(() => warnings.push('load event did not fire within 15s'));
  await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => { /* long-polling sites never go idle */ });
  if (settle) await sleep(settle);
  return { response, status: response ? response.status() : null, finalUrl: page.url(), warnings };
}

/** Detect a challenge/bot wall. Strong signals only; low text alone is just a warning. */
export async function detectBotWall(page, status) {
  const s = await page.evaluate(() => {
    const body = document.body;
    const text = body ? (body.innerText || '').trim() : '';
    const challenge = document.querySelector('#challenge-running,#challenge-form,#challenge-stage,.cf-turnstile,iframe[src*="challenges.cloudflare.com"],[data-sitekey],#px-captcha,.g-recaptcha,iframe[src*="recaptcha"],iframe[src*="hcaptcha"],#cf-please-wait,[id^="sec-if-cpt"],#ddos-protection');
    return { title: document.title || '', textLen: text.length, children: body ? body.children.length : 0, challenge: challenge ? (challenge.id || challenge.className || challenge.tagName) : null, snippet: text.slice(0, 280) };
  }).catch(() => ({ title: '', textLen: 0, children: 0, challenge: null, snippet: '' }));
  const minimal = s.textLen < 600 && s.children <= 12;
  const reasons = [];
  if (s.challenge) reasons.push(`challenge element (${String(s.challenge).slice(0, 40)})`);
  if ([401, 403, 429, 503].includes(status)) reasons.push(`HTTP ${status}`);
  if (WALL_TITLES.test(s.title)) reasons.push(`title "${s.title.slice(0, 60)}"`);
  const blocked = minimal && reasons.length > 0 && (s.challenge || WALL_TITLES.test(s.title) || [401, 403, 429].includes(status));
  return { blocked: !!blocked, reasons, lowText: s.textLen < 100, title: s.title, snippet: s.snippet };
}

export function blockedMarkdown(url, wall) {
  return `# Capture blocked\n\n` +
    `The page at ${url} answered with a bot check or access wall (${wall.reasons.join(', ')}).\n` +
    `showtime does not try to get around these checks.\n\n` +
    `Page title: ${wall.title || '(none)'}\n\n` +
    `## What to do (ask the user)\n\n` +
    `- Ask for screenshots or a screen recording of the pages they want in the video, then use those files.\n` +
    `- Ask for a different public URL (a docs site, a landing page on another host, a staging URL).\n` +
    `- For their own product: run it locally and capture \`http://localhost:...\` instead.\n` +
    `- If it is their own site, they can allow-list the capture in their bot-protection settings.\n`;
}

// ---------------------------------------------------------------------------------------------
// scrolling

/** Scroll the whole page in steps so lazy content loads, then return to the top. */
export async function lazyScroll(page, { budgetMs = 15000, step = 0.7, pause = 350 } = {}) {
  const t0 = Date.now();
  let steps = 0;
  for (;;) {
    const r = await page.evaluate((f) => {
      const h = Math.max(document.body ? document.body.scrollHeight : 0, document.documentElement.scrollHeight);
      const y = window.scrollY + innerHeight * f;
      window.scrollTo(0, Math.min(y, h));
      return { y: window.scrollY, h, vh: innerHeight };
    }, step).catch(() => null);
    steps++;
    if (!r) break;
    await sleep(pause);
    if (r.y + r.vh >= r.h - 2 || Date.now() - t0 > budgetMs || steps > 200) break;
  }
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight)).catch(() => {});
  await sleep(600);
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    const pending = await page.evaluate(() => [...document.images].filter((i) => !i.complete && i.loading !== 'lazy').length).catch(() => 0);
    if (!pending) break;
    await sleep(250);
  }
  await page.evaluate(() => window.scrollTo(0, 0)).catch(() => {});
  await sleep(400);
  return { steps, ms: Date.now() - t0 };
}

export async function scrollMetrics(page) {
  return page.evaluate(() => ({
    height: Math.max(document.body ? document.body.scrollHeight : 0, document.documentElement.scrollHeight),
    vh: innerHeight, vw: innerWidth,
  }));
}

/** Make fixed/sticky elements static (for full-page plates); returns a restore function. */
export async function neutralizeFixed(page) {
  await page.evaluate(() => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
    let el, n = 0;
    while ((el = walker.nextNode()) && n++ < 8000) {
      const p = getComputedStyle(el).position;
      if (p === 'fixed' || p === 'sticky') {
        el.setAttribute('data-st-pos', el.style.position || '');
        el.style.setProperty('position', p === 'fixed' && el.getAttribute('data-st-hidden') ? 'fixed' : 'static', 'important');
      }
    }
  }).catch(() => {});
  return () => page.evaluate(() => {
    for (const el of document.querySelectorAll('[data-st-pos]')) {
      const v = el.getAttribute('data-st-pos');
      el.style.removeProperty('position');
      if (v) el.style.position = v;
      el.removeAttribute('data-st-pos');
    }
  }).catch(() => {});
}

// ---------------------------------------------------------------------------------------------
// safe downloads

export function isPrivateIP(ip) {
  if (net.isIPv4(ip)) {
    const [a, b] = ip.split('.').map(Number);
    return a === 10 || a === 127 || a === 0 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127) || a >= 224;
  }
  if (net.isIPv6(ip)) {
    const s = ip.toLowerCase();
    if (s === '::1' || s === '::') return true;
    if (s.startsWith('fe80') || s.startsWith('fc') || s.startsWith('fd')) return true;
    const m = /::ffff:(\d+\.\d+\.\d+\.\d+)$/.exec(s);
    if (m) return isPrivateIP(m[1]);
  }
  return false;
}

/**
 * 'private' | 'public' | 'unknown' (the name does not resolve here: offline, or DNS only through a
 * proxy). Folding 'unknown' into "public" would let a host whose DNS lookup merely failed pass the
 * SSRF guard below -- the bug this guards against.
 */
export async function hostPrivacy(hostname) {
  const h = String(hostname || '').replace(/^\[|\]$/g, '');
  if (!h || h === 'localhost' || h.endsWith('.localhost') || h.endsWith('.test') || h.endsWith('.local')) return 'private';
  if (net.isIP(h)) return isPrivateIP(h) ? 'private' : 'public';
  try {
    const addrs = await dns.promises.lookup(h, { all: true });
    if (!addrs.length) return 'unknown';
    return addrs.some((a) => isPrivateIP(a.address)) ? 'private' : 'public';
  } catch { return 'unknown'; }
}

/** SSRF guard: true unless the host is known to be public (fails closed when DNS cannot tell). */
export async function hostIsPrivate(hostname) {
  return (await hostPrivacy(hostname)) !== 'public';
}

/**
 * True when a proxy is configured for `url` (HTTP_PROXY/http_proxy for http:, HTTPS_PROXY/https_proxy
 * for https:) and NO_PROXY/no_proxy does not bypass it for this host. Behind an explicit proxy with no
 * local DNS resolver, dns.lookup() fails for every public host even though the proxy reaches it fine:
 * the proxy's own policy governs what it can reach, so an unresolved lookup there is not evidence the
 * host is unreachable the way it would be with no proxy configured at all.
 */
export function proxyConfiguredFor(url) {
  let u;
  try { u = typeof url === 'string' ? new URL(url) : url; } catch { return false; }
  const env = process.env;
  const proxy = u.protocol === 'http:' ? (env.HTTP_PROXY || env.http_proxy) : (env.HTTPS_PROXY || env.https_proxy);
  if (!proxy) return false;
  const host = u.hostname.toLowerCase();
  const bypass = String(env.NO_PROXY || env.no_proxy || '').split(',').map((s) => s.trim().toLowerCase()).filter(Boolean);
  return !bypass.some((e) => e === '*' || host === e.replace(/^\./, '') || host.endsWith(e.startsWith('.') ? e : '.' + e));
}

const TRACKERS = /(^|\.)(doubleclick\.net|googlesyndication\.com|google-analytics\.com|googletagmanager\.com|facebook\.com\/tr|bat\.bing\.com|clarity\.ms|hotjar\.com|segment\.io|mixpanel\.com|adsrvr\.org|scorecardresearch\.com|quantserve\.com)|\b(analytics|pixel|tracking|beacon)\./i;
export function isTracker(u) { return TRACKERS.test(u); }

/** Unwrap image-proxy URLs (/_next/image?url=..., cdn-cgi/image/...) and drop size params. */
export function canonicalAssetUrl(u) {
  try {
    const x = new URL(u);
    if (/\/_next\/image\/?$/.test(x.pathname) && x.searchParams.get('url')) return canonicalAssetUrl(new URL(x.searchParams.get('url'), x).href);
    const m = /\/cdn-cgi\/image\/[^/]+\/(.+)$/.exec(x.pathname);
    if (m) return canonicalAssetUrl(new URL('/' + m[1], x).href);
    for (const k of ['w', 'q', 'dpr', 'width', 'quality', 'auto', 'fm', 'fit']) x.searchParams.delete(k);
    x.hash = '';
    return x.href;
  } catch { return u; }
}

const MAGIC = [
  [[0x89, 0x50, 0x4e, 0x47], 'png'], [[0xff, 0xd8, 0xff], 'jpg'], [[0x47, 0x49, 0x46, 0x38], 'gif'],
  [[0x1a, 0x45, 0xdf, 0xa3], 'webm'], [[0x77, 0x4f, 0x46, 0x32], 'woff2'], [[0x00, 0x00, 0x01, 0x00], 'ico'],
];
export function sniffExt(buf) {
  for (const [sig, ext] of MAGIC) if (sig.every((b, i) => buf[i] === b)) return ext;
  if (buf.length > 12 && buf.toString('latin1', 0, 4) === 'RIFF' && buf.toString('latin1', 8, 12) === 'WEBP') return 'webp';
  if (buf.length > 12 && buf.toString('latin1', 4, 8) === 'ftyp') {
    const brand = buf.toString('latin1', 8, 12);
    if (/^avi[fs]/.test(brand)) return 'avif';
    if (brand === 'qt  ') return 'mov';
    return 'mp4';
  }
  const head = buf.toString('utf8', 0, Math.min(buf.length, 1024)).trimStart().toLowerCase();
  if (head.startsWith('<svg') || (head.startsWith('<?xml') && head.includes('<svg'))) return 'svg';
  if (head.startsWith('<!doctype html') || head.startsWith('<html')) return 'html';
  return null;
}

/**
 * Download with SSRF protection (every redirect hop re-checked), a per-file cap and a shared
 * byte budget. -> { ok, file, bytes, ext, contentType } or { ok:false, reason }
 *
 * A host whose DNS this process cannot resolve ('unknown', not 'private'/'public') is refused as
 * 'unresolved-host' unless a proxy is configured for it (proxyConfiguredFor): behind an explicit
 * proxy with no local resolver, that is not evidence the host is unreachable, only that this process
 * cannot tell by itself, so the proxy's own reachability policy is allowed to decide.
 */
export async function safeDownload(url, destNoExt, { allowPrivate = false, maxBytes = 20e6, budget, headers = {}, timeout = 15000 } = {}) {
  let cur = url;
  for (let hop = 0; hop < 6; hop++) {
    let u;
    try { u = new URL(cur); } catch { return { ok: false, reason: 'bad-url' }; }
    if (!['http:', 'https:'].includes(u.protocol)) return { ok: false, reason: 'scheme' };
    if (!allowPrivate) {
      const kind = await hostPrivacy(u.hostname);
      if (kind === 'private' || (kind === 'unknown' && !proxyConfiguredFor(u))) {
        return { ok: false, reason: kind === 'private' ? 'private-host' : 'unresolved-host' };
      }
    }
    const ac = new AbortController();
    const timer = setTimeout(() => ac.abort(), timeout);
    let res;
    try {
      res = await fetch(u.href, { redirect: 'manual', headers, signal: ac.signal });
    } catch (e) {
      clearTimeout(timer);
      return { ok: false, reason: ac.signal.aborted ? 'timeout' : 'network' };
    }
    if (res.status >= 300 && res.status < 400 && res.headers.get('location')) {
      clearTimeout(timer);
      cur = new URL(res.headers.get('location'), u).href;
      continue;
    }
    if (!res.ok) { clearTimeout(timer); return { ok: false, reason: `http-${res.status}` }; }
    const ctype = (res.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
    if (/^text\/html|xml$/.test(ctype) && !/svg/.test(ctype)) { clearTimeout(timer); try { await res.body?.cancel(); } catch { /* */ } return { ok: false, reason: 'html-body' }; }
    const chunks = [];
    let total = 0;
    try {
      for await (const chunk of res.body) {
        total += chunk.length;
        if (total > maxBytes) { ac.abort(); clearTimeout(timer); return { ok: false, reason: 'too-large' }; }
        if (budget && budget.used + total > budget.max) { ac.abort(); clearTimeout(timer); return { ok: false, reason: 'budget' }; }
        chunks.push(chunk);
      }
    } catch {
      clearTimeout(timer);
      return { ok: false, reason: ac.signal.aborted ? 'timeout' : 'network' };
    }
    clearTimeout(timer);
    const buf = Buffer.concat(chunks.map((c) => Buffer.from(c)));
    const ext = sniffExt(buf) || (/svg/.test(ctype) ? 'svg' : null) || (/(\.[a-z0-9]{2,5})(?:$|\?)/i.exec(u.pathname)?.[1] || '').slice(1).toLowerCase() || 'bin';
    if (ext === 'html') return { ok: false, reason: 'html-body' };
    if (budget) budget.used += buf.length;
    const file = `${destNoExt}.${ext === 'jpeg' ? 'jpg' : ext}`;
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, buf);
    return { ok: true, file, bytes: buf.length, ext, contentType: ctype, finalUrl: u.href };
  }
  return { ok: false, reason: 'redirects' };
}

// ---------------------------------------------------------------------------------------------
// contact sheets

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/**
 * Render a grid of images with captions to a JPEG using the browser.
 * items: [{file, label}] (paths relative to dir or absolute). Returns the output path or null.
 */
export async function contactSheet(browser, items, outFile, { title = '', cols = 3, cell = 520, dir } = {}) {
  const list = items.filter((it) => it && it.file && fs.existsSync(path.resolve(dir || '.', it.file)));
  if (!list.length) return null;
  const base = path.dirname(path.resolve(outFile));
  const htmlFile = path.join(base, `.${path.basename(outFile, path.extname(outFile))}.html`);
  const cells = list.map((it, i) => {
    const src = pathToFileURL(path.resolve(dir || '.', it.file)).href;
    return `<figure><div class="im"><img src="${esc(src)}"></div><figcaption><b>${i + 1}</b> ${esc(it.label || path.basename(it.file))}</figcaption></figure>`;
  }).join('\n');
  const width = cols * (cell + 12) + 12;
  fs.writeFileSync(htmlFile, `<!doctype html><html><head><meta charset="utf-8"><style>
    html,body{margin:0;background:#141417;color:#e8e8ec;font:14px/1.3 ui-sans-serif,system-ui,sans-serif}
    h1{font-size:16px;font-weight:600;margin:0;padding:12px 12px 0}
    main{display:grid;grid-template-columns:repeat(${cols},${cell}px);gap:12px;padding:12px;width:${width - 24}px}
    figure{margin:0;background:#1f1f24;border-radius:6px;overflow:hidden}
    .im{height:${Math.round(cell * 0.62)}px;display:flex;align-items:center;justify-content:center;background:#26262c;
      background-image:linear-gradient(45deg,#2b2b31 25%,transparent 25%,transparent 75%,#2b2b31 75%),linear-gradient(45deg,#2b2b31 25%,transparent 25%,transparent 75%,#2b2b31 75%);
      background-size:16px 16px;background-position:0 0,8px 8px}
    img{max-width:100%;max-height:100%;object-fit:contain;display:block}
    figcaption{padding:6px 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:13px;color:#c9c9d1}
    b{color:#fff;margin-right:4px}
  </style></head><body>${title ? `<h1>${esc(title)}</h1>` : ''}<main>${cells}</main></body></html>`);
  const page = await browser.newPage({ viewport: { width, height: 800 }, deviceScaleFactor: 1 });
  try {
    await page.goto(pathToFileURL(htmlFile).href, { waitUntil: 'load', timeout: 60000 });
    await page.evaluate(() => Promise.all([...document.images].map((i) => i.decode().catch(() => {}))));
    fs.mkdirSync(path.dirname(path.resolve(outFile)), { recursive: true });
    await page.screenshot({ path: outFile, fullPage: true, type: 'jpeg', quality: 82 });
  } finally {
    await page.close();
    try { fs.unlinkSync(htmlFile); } catch { /* keep */ }
  }
  return outFile;
}

export function slug(s, max = 40) {
  return String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^A-Za-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '').toLowerCase().slice(0, max).replace(/-+$/, '') || 'item';
}

export function relPath(from, to) {
  return path.relative(from, to).split(path.sep).join('/');
}

// ---------------------------------------------------------------------------------------------
// plain static server for `--serve DIR` (site capture/record/component, demo record)

const STATIC_MIME = {
  '.html': 'text/html; charset=utf-8', '.htm': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8', '.cjs': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.map': 'application/json; charset=utf-8', '.webmanifest': 'application/manifest+json',
  '.txt': 'text/plain; charset=utf-8', '.md': 'text/plain; charset=utf-8', '.xml': 'application/xml', '.csv': 'text/csv; charset=utf-8',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
  '.webp': 'image/webp', '.avif': 'image/avif', '.ico': 'image/x-icon', '.bmp': 'image/bmp',
  '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf', '.otf': 'font/otf',
  '.mp4': 'video/mp4', '.m4v': 'video/mp4', '.webm': 'video/webm', '.mov': 'video/quicktime', '.ogv': 'video/ogg',
  '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.m4a': 'audio/mp4', '.ogg': 'audio/ogg', '.opus': 'audio/ogg',
  '.flac': 'audio/flac', '.wasm': 'application/wasm', '.pdf': 'application/pdf',
};

/** `root` + URL path (decoded) -> absolute file, or null when it escapes root: lexically (.., drive
 * letters, NUL) or through a symlink inside the tree that points outside it. */
export function staticJoin(root, rel) {
  const parts = String(rel).replace(/\\/g, '/').split('/').filter((s) => s && s !== '.');
  if (parts.some((s) => s === '..' || s.includes('\0') || s.includes(':'))) return null;
  const abs = path.resolve(root, ...parts);
  const r = path.relative(path.resolve(root), abs);
  if (r.startsWith('..') || path.isAbsolute(r)) return null;
  return realpathUnderRoot(root, abs) ? abs : null;
}

/**
 * Serve a folder exactly as a static host would: files, `index.html` for folders, byte ranges,
 * no directory listings, no showtime runtime, no preview player, no script injection.
 * Extension-less paths that do not exist fall back to /index.html (single-page apps).
 * Binds 127.0.0.1 on a random free port. -> { url, port, root, page, close() }
 * `target` may be a folder or an .html file (then its folder is served and `page` points at it).
 */
export async function serveStatic(target, { spa = true } = {}) {
  let root = path.resolve(String(target));
  let page = '/';
  let st;
  try { st = fs.statSync(root); } catch { throw new UserError(`--serve: not found: ${root}`, 'pass the folder that contains index.html (e.g. ./dist or ./public)'); }
  if (st.isFile()) {
    if (!/\.html?$/i.test(root)) throw new UserError(`--serve expects a folder or an .html file, got ${root}`);
    page = '/' + encodeURIComponent(path.basename(root));
    root = path.dirname(root);
  } else if (!fs.existsSync(path.join(root, 'index.html')) && !fs.existsSync(path.join(root, 'index.htm'))) {
    const htmls = fs.readdirSync(root).filter((f) => /\.html?$/i.test(f)).sort();
    if (!htmls.length) {
      throw new UserError(`--serve: ${root} has no index.html (and no other .html file)`,
        'point --serve at the built site folder (often dist/, build/, out/ or public/), or run the dev server and pass its URL');
    }
    page = '/' + encodeURIComponent(htmls[0]);
  }
  const http = await import('node:http');
  const fsp = fs.promises;
  const send = async (req, res, file, status = 200) => {
    // staticJoin already checked the *requested* path; the caller below also hands this function
    // names it picked itself (index.html, a pretty-URL ".html", the SPA fallback, 404.html) that were
    // never checked -- re-check the file actually about to be streamed, once, here.
    if (!realpathUnderRoot(root, file)) { res.writeHead(403); return res.end(symlinkRefusal(path.relative(root, file))); }
    const s = await fsp.stat(file);
    const type = STATIC_MIME[path.extname(file).toLowerCase()] || 'application/octet-stream';
    const headers = { 'Content-Type': type, 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-store' };
    const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '');
    if (status === 200 && m && (m[1] !== '' || m[2] !== '')) {
      let start, end;
      if (m[1] === '') { start = Math.max(0, s.size - Number(m[2])); end = s.size - 1; } else {
        start = Number(m[1]); end = m[2] === '' ? s.size - 1 : Math.min(Number(m[2]), s.size - 1);
      }
      if (start >= s.size || start > end) { res.writeHead(416, { ...headers, 'Content-Range': `bytes */${s.size}` }); return res.end(); }
      res.writeHead(206, { ...headers, 'Content-Range': `bytes ${start}-${end}/${s.size}`, 'Content-Length': end - start + 1 });
      if (req.method === 'HEAD') return res.end();
      return fs.createReadStream(file, { start, end }).on('error', () => res.destroy()).pipe(res);
    }
    res.writeHead(status, { ...headers, 'Content-Length': s.size });
    if (req.method === 'HEAD') return res.end();
    fs.createReadStream(file).on('error', () => res.destroy()).pipe(res);
  };
  const isFile = (f) => { try { return fs.statSync(f).isFile(); } catch { return false; } };
  const server = http.createServer(async (req, res) => {
    try {
      const h = String(req.headers.host || '').replace(/:\d+$/, '').replace(/^\[|\]$/g, '');
      if (h && !['127.0.0.1', 'localhost', '::1'].includes(h)) { res.writeHead(403); return res.end('forbidden host\n'); }
      if (req.method !== 'GET' && req.method !== 'HEAD') { res.writeHead(405); return res.end(); }
      let p;
      try { p = decodeURIComponent(new URL(req.url, 'http://127.0.0.1').pathname); } catch { res.writeHead(400); return res.end('bad path\n'); }
      let file = staticJoin(root, p);
      if (!file) { res.writeHead(403); return res.end(escapesBySymlink(root, p) ? symlinkRefusal(p.replace(/^\/+/, '')) : 'forbidden path\n'); }
      if (!isFile(file)) {
        const idx = ['index.html', 'index.htm'].map((n) => path.join(file, n)).find(isFile);
        if (idx) file = idx;
        else if (isFile(file + '.html')) file = file + '.html';            // /about -> about.html (pretty URLs)
        else {
          const isDir = (() => { try { return fs.statSync(file).isDirectory(); } catch { return false; } })();
          const fallback = spa && !isDir && !path.extname(p) && ['index.html', 'index.htm'].map((n) => path.join(root, n)).find(isFile);
          if (fallback) return await send(req, res, fallback);
          const nf = ['404.html'].map((n) => path.join(root, n)).find(isFile);
          if (nf) return await send(req, res, nf, 404);
          res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
          return res.end(`404 not found: ${p}\n`);
        }
      }
      return await send(req, res, file);
    } catch {
      if (!res.headersSent) res.writeHead(500);
      res.end();
    }
  });
  server.keepAliveTimeout = 5000;
  const port = await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolve(server.address().port));
  });
  server.unref();   // never keeps the process alive on its own (an error path cannot hang the command)
  const url = `http://127.0.0.1:${port}`;
  return {
    url, port, root, page: url + page,
    close() { return new Promise((r) => { server.closeAllConnections?.(); server.close(() => r()); }); },
  };
}

// ---------------------------------------------------------------------------------------------
// wrong-page guard: showtime's own preview/runtime pages and bare directory listings

/**
 * Did the browser land somewhere that is not the site? -> null, or { kind, reason, hint }.
 * kinds: 'showtime-preview' (the page was wrapped in showtime's preview player: it was served by
 * `showtime server`/`preview`; also that server's 403 "needs its session key" page), 'showtime-runtime' (any other /_st/ page), 'directory-listing'.
 */
export async function landingProblem(page) {
  const s = await page.evaluate(() => {
    const title = document.title || '';
    const h1 = (document.querySelector('h1')?.innerText || '').trim();
    return {
      path: location.pathname, title, h1,
      player: typeof window.__ST_PLAYER__ !== 'undefined',
      keyWall: /^403 forbidden: this showtime preview server needs its session key/.test((document.body?.innerText || '').trim()),
      listingTable: !!document.querySelector('table#files, ul#files, #listing, .directory-listing'),
      otherEls: document.querySelectorAll('img,video,canvas,svg,button,input,form,section,article,header,footer,nav').length,
    };
  }).catch(() => null);
  if (!s) return null;
  const hintServe = 'capture the folder with `--serve <dir>` (a plain static server), or the app\'s own dev-server URL; ' +
    'never through `showtime server` / `showtime preview`, which wrap pages in the preview player';
  if (s.keyWall) {
    return { kind: 'showtime-preview', reason: 'the URL is showtime\'s own project server (`showtime server` / `preview`), which ' +
      'refused it for lack of its session key; it wraps pages in the preview player, so it is not the site', hint: hintServe };
  }
  if (s.player || /\s-\sshowtime preview$/.test(s.title) || s.path === '/_st/preview') {
    return { kind: 'showtime-preview', reason: `the page is showtime's preview player ("${s.title}"), not the site`, hint: hintServe };
  }
  if (s.path.startsWith('/_st/')) {
    return { kind: 'showtime-runtime', reason: `the browser landed on showtime's runtime page ${s.path}, not the site`, hint: hintServe };
  }
  const listingTitle = /^(index of\s|directory listing for\s|listing directory\s|files within\s)/i;
  if (listingTitle.test(s.title) || listingTitle.test(s.h1) || (s.listingTable && s.otherEls === 0)) {
    return {
      kind: 'directory-listing', reason: `the page is a directory listing ("${s.title || s.h1}"), not the site`,
      hint: 'point at the folder that holds index.html (e.g. dist/ or public/), or pass the page path in the URL',
    };
  }
  return null;
}

/**
 * A URL for the event log: query values, the fragment and any user:password are replaced, so a
 * studio board link (?k=<key>) or a session token never lands in events.json. Param names stay.
 */
export function redactUrl(u) {
  let x;
  try { x = new URL(String(u)); } catch { return String(u).replace(/[?#].*$/, ''); }
  if (x.username || x.password) { x.username = ''; x.password = ''; }
  const names = [...new Set([...x.searchParams.keys()])];
  x.search = names.length ? '?' + names.map((n) => `${encodeURIComponent(n)}=redacted`).join('&') : '';
  if (x.hash) x.hash = '';
  return x.href;
}

// Probe a project for `showtime export html`: open it in render mode (live shader transitions, as
// the exported player draws them), play through the timeline and record every file the page asks
// the server for, the chapters, the poster frame and (on request) the offline ST.score.
import { openBrowser, stageSource, isLocalUrl, withTimeout, pullScore } from '../stagehost.mjs';
import { UserError } from '../cli.mjs';

// Film.start() options are private to film.js; this hook keeps its `acts` (or `chapters`) for the
// chapter ticks and its subtitle/kicker for the start card.
const FILM_HOOK = `(function(){try{var F;Object.defineProperty(window,'Film',{configurable:true,enumerable:true,
get:function(){return F},set:function(v){F=v;if(v&&typeof v.start==='function'&&!v.start.__stHook){var s=v.start;
v.start=function(o){try{window.__stFilmActs=o&&(o.chapters||o.acts)||null;window.__stFilmCard={subtitle:o&&o.subtitle||'',
kicker:o&&o.kicker||''}}catch(e){}return s.apply(this,arguments)};v.start.__stHook=1}}})}catch(e){}})();`;

// What the start card needs from the page: the colours, and the font of the largest text in the
// poster frame (the film's display face) plus its body face.
function pageLook() {
  const out = { colors: {}, font: '', fontWeight: 700, bodyFont: '' };
  const parse = (f) => {
    const m = /^(?:(?:italic|oblique|normal)\s+)?(?:(?:small-caps|normal)\s+)?(\d{3}|bold|normal)?\s*[\d.]+px(?:\/\S+)?\s+(.+)$/.exec(String(f || '').trim());
    return m ? { weight: m[1] === 'bold' ? 700 : m[1] === 'normal' || !m[1] ? 400 : +m[1], family: m[2] } : null;
  };
  const F = window.Film;
  if (F && F.pal && typeof F.frameInfo === 'function') {
    for (const k of ['bg', 'ink', 'muted', 'accent']) if (typeof F.pal[k] === 'string') out.colors[k] = F.pal[k];
    const texts = (F.frameInfo().texts || []).slice().sort((a, b) => (b.size || 0) - (a.size || 0));
    const big = texts[0] && parse(texts[0].font);
    const small = texts.length && parse(texts[texts.length - 1].font);
    if (big) { out.font = big.family; out.fontWeight = Math.max(600, big.weight); }
    if (small) out.bodyFont = small.family;
    if (!out.bodyFont && F.FONTS) out.bodyFont = F.FONTS.sans;
  } else {
    const cs = getComputedStyle(document.body || document.documentElement), rs = getComputedStyle(document.documentElement);
    const v = (n) => (rs.getPropertyValue(n) || '').trim();
    out.colors.bg = v('--bg') || v('--st-bg') || cs.backgroundColor;
    out.colors.ink = v('--fg') || v('--ink') || cs.color;
    out.colors.muted = v('--muted') || '';
    out.colors.accent = v('--accent') || '';
    let best = null, bestSize = 0;
    for (const el of document.querySelectorAll('h1,h2,h3,[class*="title"],[class*="headline"],p,span,div')) {
      if (!el.textContent || !el.textContent.trim() || el.children.length > 3) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) continue;
      const st = getComputedStyle(el);
      if (st.visibility === 'hidden' || +st.opacity === 0) continue;
      const size = parseFloat(st.fontSize) || 0;
      if (size > bestSize) { bestSize = size; best = st; }
    }
    if (best) { out.font = best.fontFamily; out.fontWeight = Math.max(600, parseInt(best.fontWeight, 10) || 700); }
    out.bodyFont = cs.fontFamily;
  }
  for (const k of Object.keys(out.colors)) if (!out.colors[k] || /^rgba\(0, 0, 0, 0\)$/.test(out.colors[k])) delete out.colors[k];
  const hook = window.__stFilmCard || {};
  out.subtitle = hook.subtitle || '';
  out.kicker = hook.kicker || '';
  return out;
}

const SEQ_RE = /^(.*?)(\d{2,})\.(png|jpe?g|webp|avif|gif)$/i;

/** Time spans [from, to] (seconds) around the requests of numbered image sequences (name_0007.png ...). */
export function sequenceSpans(requests, firstAt, step) {
  const groups = new Map();
  for (const p of requests) {
    const m = SEQ_RE.exec(p);
    if (!m || !firstAt.has(p)) continue;
    const k = `${m[1]}#${m[3].toLowerCase()}`;
    const g = groups.get(k) || [];
    g.push(firstAt.get(p));
    groups.set(k, g);
  }
  const spans = [];
  for (const ts of groups.values()) spans.push([Math.min(...ts) - step, Math.max(...ts) + step]);
  return spans;
}

/**
 * @param o.url server base URL   @param o.page page path   @param o.config showtime.json (+ overrides)
 * @param o.posterT seconds, 'auto' (40%) or null   @param o.wantScore pull ST.score as float channels
 * @param o.gpu   @param o.log (line) => void
 * -> { info, requests: [path], failed: [{path,status}], errors, consoleErrors, chapters, poster: Buffer|null,
 *      posterT, score: {channels, sampleRate, peak}|null, samples }
 */
export async function probeProject(o) {
  const cfg = o.config || {};
  const width = Math.round(Number(cfg.width) || 1920);
  const height = Math.round(Number(cfg.height) || 1080);
  const b = await openBrowser({ gpu: o.gpu || 'auto' });
  const origin = new URL(o.url).origin;
  const requests = [];
  const seen = new Set();
  const firstAt = new Map(); // path -> the probe time that first requested it
  let curT = 0;
  const failed = [];
  const errors = [];
  const consoleErrors = [];
  const blocked = [];
  try {
    const context = await b.browser.newContext({
      viewport: { width, height }, deviceScaleFactor: 1, colorScheme: 'light', reducedMotion: 'no-preference',
      locale: 'en-US', timezoneId: 'UTC', serviceWorkers: 'block',
    });
    const page = await context.newPage();
    page.on('request', (r) => {
      const u = r.url();
      if (!u.startsWith(origin + '/')) return;
      const p = decodeURIComponent(new URL(u).pathname);
      if (!seen.has(p)) { seen.add(p); requests.push(p); firstAt.set(p, curT); }
    });
    page.on('response', (r) => {
      if (r.status() >= 400 && r.url().startsWith(origin + '/')) failed.push({ path: decodeURIComponent(new URL(r.url()).pathname), status: r.status() });
    });
    page.on('pageerror', (e) => errors.push(String(e.message || e).slice(0, 400)));
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 400)); });
    await page.route('**/*', (route) => {
      const u = route.request().url();
      if (isLocalUrl(u)) return route.continue();
      if (!blocked.includes(u)) blocked.push(u);
      return route.abort('blockedbyclient');
    });
    const seed = cfg.seed === undefined ? 1 : cfg.seed;
    const renderCfg = { config: cfg, override: null, alpha: false, settle: 'raf1', layers: false, seed };
    await page.addInitScript({ content: `window.__ST_RENDER__=${JSON.stringify(renderCfg)};\n${FILM_HOOK}\n${stageSource()}` });
    const target = `${o.url}/${String(o.page || 'index.html').replace(/^\/+/, '')}`;
    try {
      await page.goto(target, { waitUntil: 'load', timeout: 60000 });
    } catch (e) {
      throw new UserError(`could not open ${target}: ${e.message.split('\n')[0]}`);
    }
    let info;
    try {
      info = await withTimeout(page.evaluate(() => window.ST.ready()), 120000, 'the page never became ready');
    } catch (e) {
      throw new UserError(`${String(e.message || e).split('\n')[0].replace(/^page\.evaluate: (Error: )?/, '')}` +
        (errors[0] ? ` (first page error: ${errors[0]})` : ''), 'run `showtime check <project>` to see what the page is waiting for');
    }
    const D = info.duration, fps = info.fps;
    const lastT = Math.max(0, (Math.round(D * fps) - 1) / fps);
    const q = (x) => Math.min(lastT, Math.max(0, Math.floor(x * fps + 1e-9) / fps));

    // chapters: showtime.json > Film acts > top-level clips
    const meta = await page.evaluate(() => {
      const clips = window.ST.clips();
      const els = Array.from(document.querySelectorAll('[data-start]'));
      const tops = [];
      els.forEach((el, i) => {
        const p = el.parentElement && el.parentElement.closest('[data-start]');
        const c = clips[i];
        if (!p && c && isFinite(c.start)) tops.push({ t: c.start, end: c.end, label: el.getAttribute('data-name') || el.id || '' });
      });
      let acts = null;
      try { acts = window.__stFilmActs ? JSON.parse(JSON.stringify(window.__stFilmActs)) : null; } catch (e) { acts = null; }
      return { clips: clips.map((c) => ({ start: c.start, end: c.end })), tops, acts };
    });
    const chapters = pickChapters(cfg.chapters, meta.acts, meta.tops, D);

    // play through: every clip edge, every half second (at most ~300 seeks), the chapters
    const times = new Set();
    const step = Math.max(0.5, D / 300);
    for (let t = 0; t <= lastT + 1e-9; t += step) times.add(q(t));
    for (const c of meta.clips) {
      for (const x of [c.start, c.end]) if (isFinite(x) && x !== null) { times.add(q(x)); times.add(q(x + 0.2)); }
    }
    for (const c of chapters) times.add(q(c.t + 0.1));
    times.add(lastT);
    const list = [...times].filter((x) => x >= 0 && x <= lastT).sort((x, y) => x - y);
    const visit = async (t) => {
      curT = t;
      // every character on the page at that time (for dropping font subsets nothing uses)
      await withTimeout(page.evaluate(async (x) => {
        await window.ST.seek(x);
        const set = window.__stChars || (window.__stChars = new Set());
        for (const ch of (document.body ? document.body.textContent : '')) set.add(ch);
        // canvas films: the font families the frame drew text with
        const F = window.Film;
        if (F && typeof F.frameInfo === 'function') {
          const fams = window.__stFams || (window.__stFams = new Set());
          for (const f of F.frameInfo().fonts || []) fams.add(f);
        }
      }, t), 60000, `seek to ${t.toFixed(3)}s`);
    };
    for (const t of list) await visit(t);
    // per-frame images (a numbered sequence, one file per frame) change between the samples: visit every
    // frame around the times the sweep met one, so each image of the sequence is requested and packed
    const extra = [];
    for (const [a, b] of sequenceSpans(requests, firstAt, step)) {
      for (let f = Math.max(0, Math.floor(a * fps)); f / fps <= Math.min(b, lastT) + 1e-9; f++) {
        const t = q(f / fps);
        if (!times.has(t)) { times.add(t); extra.push(t); }
      }
    }
    for (const t of extra) await visit(t);
    list.push(...extra);
    const domText = await page.evaluate(() => [...(window.__stChars || [])].join(''));
    // families drawn on the canvas (null: not a canvas film, or text in the page's DOM too)
    const canvasFonts = await page.evaluate(() => {
      if (!window.__stFams || !window.Film) return null;
      const domText = (document.body ? document.body.innerText : '').trim();
      if (domText) return null;
      const out = new Set();
      for (const stack of window.__stFams) {
        const first = String(stack).split(',')[0].trim().replace(/^['"]|['"]$/g, '').toLowerCase();
        if (first) out.add(first);
      }
      return [...out];
    });
    await page.waitForTimeout(250); // late fetches (icons, data) started by the last seeks

    // poster frame (a JPEG when the export shows it before the page is ready; with the start card the
    // live page draws it, so only the time is needed) and the start card's colours and fonts
    let poster = null, posterT = null, look = null;
    const wantPoster = o.posterT === 'auto' ? D * 0.4 : o.posterT;
    if (wantPoster !== null && wantPoster !== undefined && isFinite(wantPoster)) {
      posterT = q(clampNum(wantPoster, 0, lastT));
      await page.evaluate(async (x) => { await window.ST.seek(x); await window.ST._paint(); }, posterT);
      if (o.posterImage !== false) poster = await page.screenshot({ type: 'jpeg', quality: o.posterQuality || 82, clip: { x: 0, y: 0, width, height } });
    }
    try { look = await page.evaluate(`(${pageLook.toString()})()`); } catch { look = null; }

    let score = null;
    if (o.wantScore && info.hasScore) score = await pullScore(page, { duration: D, sampleRate: 48000 });
    await context.close().catch(() => {});
    return { info, requests, failed, errors, consoleErrors, blocked, chapters, poster, posterT, score, samples: list.length, domText, look, canvasFonts };
  } finally {
    await b.browser.close().catch(() => {});
  }
}

function clampNum(x, a, b) { return Math.min(b, Math.max(a, Number(x))); }

function pretty(label) {
  const s = String(label || '').replace(/[-_]+/g, ' ').trim();
  return s ? s[0].toUpperCase() + s.slice(1) : '';
}

/** [{t, label}] from showtime.json "chapters", Film acts, or the top-level clips. */
export function pickChapters(cfgChapters, acts, tops, D) {
  const norm = (arr) => (arr || []).map((a) => (Array.isArray(a) ? { t: Number(a[0]), label: String(a[1] ?? '') } : { t: Number(a.t ?? a.at ?? a.start ?? a.s), label: String(a.label ?? a.title ?? a.name ?? '') }))
    .filter((c) => isFinite(c.t) && c.t >= 0 && c.t < D);
  let out = norm(cfgChapters);
  if (!out.length) out = norm(acts);
  if (!out.length) {
    out = (tops || []).filter((c) => (c.end === null || c.end === undefined || c.end - c.t >= 0.3) && c.t < D)
      .map((c) => ({ t: c.t, label: pretty(c.label) }));
  }
  const seen = new Set();
  return out.sort((a, b) => a.t - b.t).filter((c) => {
    const k = c.t.toFixed(2);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  }).slice(0, 100).map((c) => ({ t: +c.t.toFixed(4), label: c.label.slice(0, 80) }));
}

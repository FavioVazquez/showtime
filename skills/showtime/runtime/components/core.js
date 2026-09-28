// showtime motion core: easing, time envelopes, seeded randomness, text splitting,
// theme tokens and the component mount helpers every component in this folder uses.
//
// Contract: a component is a pure function of time. It registers one ST.onSeek handler,
// computes everything from `t` on every seek (never from accumulated state or callbacks),
// and does its measuring once, after fonts have loaded (inside ST.waitFor).

/* ------------------------------------------------------------------ math */

export const TAU = Math.PI * 2;
export const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
export const lerp = (a, b, p) => a + (b - a) * p;
export const invLerp = (a, b, x) => (a === b ? (x >= b ? 1 : 0) : clamp((x - a) / (b - a)));
export const remap = (x, a, b, c, d, fn = linear) => lerp(c, d, fn(invLerp(a, b, x)));
export const smoothstep = (a, b, x) => { const p = invLerp(a, b, x); return p * p * (3 - 2 * p); };
export const round = (x, d = 3) => { const k = 10 ** d; return Math.round(x * k) / k; };

/* ---------------------------------------------------------------- easing */

export const linear = (p) => p;
const mk = (fin) => ({ in: fin, out: (p) => 1 - fin(1 - p), inOut: (p) => (p < 0.5 ? fin(2 * p) / 2 : 1 - fin(2 - 2 * p) / 2) });
const pow = (n) => mk((p) => p ** n);
const FAMILIES = {
  power1: pow(2), power2: pow(3), power3: pow(4), power4: pow(5),
  quad: pow(2), cubic: pow(3), quart: pow(4), quint: pow(5),
  sine: mk((p) => 1 - Math.cos((p * Math.PI) / 2)),
  expo: mk((p) => (p <= 0 ? 0 : 2 ** (10 * p - 10))),
  circ: mk((p) => 1 - Math.sqrt(1 - p * p)),
};

/** CSS-style cubic-bezier(x1, y1, x2, y2) as a function of progress. */
export function cubicBezier(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const sx = (t) => ((ax * t + bx) * t + cx) * t;
  const sy = (t) => ((ay * t + by) * t + cy) * t;
  const dx = (t) => (3 * ax * t + 2 * bx) * t + cx;
  return (p) => {
    if (p <= 0) return 0;
    if (p >= 1) return 1;
    let t = p;
    for (let i = 0; i < 8; i++) { const e = sx(t) - p; const d = dx(t); if (Math.abs(e) < 1e-6) return sy(t); if (Math.abs(d) < 1e-6) break; t -= e / d; }
    let lo = 0, hi = 1; t = p;
    for (let i = 0; i < 40; i++) { const v = sx(t); if (Math.abs(v - p) < 1e-6) break; if (v < p) lo = t; else hi = t; t = (lo + hi) / 2; }
    return sy(t);
  };
}

/** Overshooting "back" ease. Keep s <= 2 (anything more reads as cartoon). */
export const back = (s = 1.7) => mk((p) => p * p * ((s + 1) * p - s));

/**
 * Closed-form damped spring (seek-safe: a pure function of progress).
 * response = seconds per undamped oscillation (0.3-0.6 for entrances); damping = zeta
 * (1 = no overshoot, 0.8 ~ 1-2% overshoot, 0.65 playful). The returned ease has a
 * `.duration` (settle time in seconds) so callers can time the move naturally.
 */
export function spring(response = 0.5, damping = 0.85) {
  const w = TAU / Math.max(0.05, response);
  const z = Math.max(0.05, damping);
  let x;
  if (z < 1) {
    const wd = w * Math.sqrt(1 - z * z);
    x = (t) => 1 - Math.exp(-z * w * t) * (Math.cos(wd * t) + ((z * w) / wd) * Math.sin(wd * t));
  } else if (z === 1) {
    x = (t) => 1 - Math.exp(-w * t) * (1 + w * t);
  } else {
    const wo = w * Math.sqrt(z * z - 1);
    x = (t) => 1 - Math.exp(-z * w * t) * (Math.cosh(wo * t) + ((z * w) / wo) * Math.sinh(wo * t));
  }
  const decay = z <= 1 ? z * w : (z - Math.sqrt(z * z - 1)) * w;
  const horizon = 12 / decay;
  let T = horizon;
  const step = horizon / 600;
  for (let t = horizon; t > 0; t -= step) { if (Math.abs(1 - x(t)) > 0.001) { T = t + step; break; } }
  const xT = x(T);
  const f = (p) => (p <= 0 ? 0 : p >= 1 ? 1 : x(p * T) + p * (1 - xT));
  f.duration = T;
  return f;
}

/**
 * "Glide": a premium arrival that covers most of the distance early and keeps easing in
 * for the rest of the duration (reach ~87% at 20% of the time). Built once as a table.
 */
export const glide = (() => {
  const N = 512;
  const vel = (t, tau) => (1 - Math.exp(-t / 0.04)) * (Math.exp(-t / tau) + 0.1 * Math.exp(-t / 0.29));
  const build = (tau) => {
    const acc = new Float64Array(N + 1);
    for (let i = 1; i <= N; i++) acc[i] = acc[i - 1] + vel((i - 0.5) / N, tau) / N;
    for (let i = 0; i <= N; i++) acc[i] /= acc[N];
    return acc;
  };
  let lo = 0.01, hi = 1, tab = null;
  for (let k = 0; k < 40; k++) {
    const mid = (lo + hi) / 2; tab = build(mid);
    if (tab[Math.round(0.2 * N)] > 0.87) lo = mid; else hi = mid;
  }
  return (p) => { if (p <= 0) return 0; if (p >= 1) return 1; const f = p * N; const i = Math.floor(f); return lerp(tab[i], tab[i + 1], f - i); };
})();

export const steps = (n = 4, jump = 'end') => (p) => clamp((jump === 'start' ? Math.ceil(p * n) : Math.floor(p * n)) / n);

/** Named curves (CSS cubic-bezier values) used across themes and docs. */
export const CURVES = {
  ease: [0.25, 0.1, 0.25, 1], 'ease-in': [0.42, 0, 1, 1], 'ease-out': [0, 0, 0.58, 1], 'ease-in-out': [0.42, 0, 0.58, 1],
  standard: [0.2, 0, 0, 1], emphasized: [0.05, 0.7, 0.1, 1], exit: [0.3, 0, 0.8, 0.15],
  premium: [0.16, 1, 0.3, 1], camera: [0.65, 0, 0.35, 1], snap: [0.5, 0, 0.1, 1],
};

const easeCache = new Map();
/**
 * Resolve an easing from a name or function:
 *   'power3.out' 'expo.inOut' 'sine.in' 'back.out(1.4)' 'spring(0.5,0.8)' 'glide' 'steps(6)'
 *   'cubic-bezier(.16,1,.3,1)' 'premium' 'standard' 'linear' or any function p -> p'.
 */
export function ease(name, fallback = 'power3.out') {
  if (typeof name === 'function') return name;
  if (name == null || name === '') return ease(fallback);
  const key = String(name).trim();
  if (easeCache.has(key)) return easeCache.get(key);
  let fn = null;
  const m = key.match(/^([a-z0-9-]+)(?:\.(in|out|inOut))?(?:\(([^)]*)\))?$/i);
  if (key === 'linear' || key === 'none') fn = linear;
  else if (key === 'glide') fn = glide;
  else if (CURVES[key]) fn = cubicBezier(...CURVES[key]);
  else if (/^cubic-bezier\(/.test(key)) { const a = key.slice(13, -1).split(',').map(Number); if (a.length === 4 && a.every(Number.isFinite)) fn = cubicBezier(...a); }
  else if (m) {
    const [, fam, dir = 'out', arg] = m;
    const args = arg ? arg.split(',').map(Number) : [];
    if (fam === 'spring') fn = spring(args[0] ?? 0.5, args[1] ?? 0.85);
    else if (fam === 'steps') fn = steps(args[0] || 4);
    else if (fam === 'back') fn = back(args[0] ?? 1.7)[dir];
    else if (FAMILIES[fam]) fn = FAMILIES[fam][dir];
  }
  if (!fn) {
    console.warn(`[showtime] unknown ease "${key}", using ${fallback}`);
    fn = ease(fallback);
  }
  easeCache.set(key, fn);
  return fn;
}

/* ------------------------------------------------------------------ time */

/** Eased progress of a segment [start, start+dur] at time t (clamped 0..1). */
export function seg(t, start, dur, fn = linear) {
  if (dur <= 0) return t >= start ? 1 : 0;
  return ease(fn)(clamp((t - start) / dur));
}

/**
 * In / hold / out envelope: 0 -> 1 over [start, start+inDur], holds, then 1 -> 0 over
 * [end-outDur, end]. With end = Infinity it never exits.
 */
export function envelope(t, { start = 0, in: inDur = 0.4, end = Infinity, out: outDur = 0.3, easeIn = 'power3.out', easeOut = 'power2.in' } = {}) {
  if (t < start) return 0;
  const a = seg(t, start, inDur, easeIn);
  if (!Number.isFinite(end)) return a;
  return Math.min(a, 1 - seg(t, end - outDur, outDur, easeOut));
}

/**
 * Stagger offset for item i of n. The whole group stays inside `cap` seconds so long
 * lists never drag (each = min(each, cap/(n-1))). from: start|end|center|edges|random.
 */
export function stagger(i, n, each = 0.05, { cap = 0.5, from = 'start', seed = 1 } = {}) {
  if (n <= 1) return 0;
  const e = Math.min(each, cap / (n - 1));
  let k = i;
  if (from === 'end') k = n - 1 - i;
  else if (from === 'center') k = Math.abs(i - (n - 1) / 2) * 2;
  else if (from === 'edges') k = ((n - 1) / 2 - Math.abs(i - (n - 1) / 2)) * 2;
  else if (from === 'random') k = hash(i, seed) * (n - 1);
  return k * e;
}

/* ------------------------------------------------------------ randomness */

/** Deterministic hash of an integer (and seed) to [0, 1). */
export function hash(i, seed = 0) {
  let h = Math.imul((i | 0) ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul((seed | 0) + 0x632be5ab, 0xc2b2ae35);
  h ^= h >>> 16; h = Math.imul(h, 0x7feb352d); h ^= h >>> 15; h = Math.imul(h, 0x846ca68b); h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
}

/** Seeded PRNG (mulberry32). rng(seed)() -> [0, 1). */
export function rng(seed = 1) {
  let a = seed >>> 0;
  return () => { a = (a + 0x6d2b79f5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

/** Smooth 1-D value noise in [-1, 1], deterministic. */
export function noise1(x, seed = 0) {
  const i = Math.floor(x); const f = x - i; const u = f * f * f * (f * (f * 6 - 15) + 10);
  return lerp(hash(i, seed), hash(i + 1, seed), u) * 2 - 1;
}

/* ------------------------------------------------------------------- DOM */

export const $ = (sel, root = document) => (typeof sel === 'string' ? root.querySelector(sel) : sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

/** Create an element: h('div', {class: 'x', style: {...}}, children...) */
export function h(tag, attrs = {}, ...kids) {
  const el = tag.includes(':') ? document.createElementNS('http://www.w3.org/2000/svg', tag.split(':')[1]) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'text') el.textContent = v;
    else if (k === 'html') el.innerHTML = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return el;
}

export const svg = (tag, attrs, ...kids) => h('svg:' + tag, attrs, ...kids);

export function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** Set a CSS custom property only when the value changed (cheap per-frame writes). */
export function setVar(el, name, value) {
  const v = String(value);
  const cache = el.__stv || (el.__stv = {});
  if (cache[name] !== v) { cache[name] = v; el.style.setProperty(name, v); }
}

/** Apply a style object (property names as in CSS, e.g. 'clip-path'). */
export function style(el, props) {
  for (const k in props) {
    const v = props[k];
    if (k.startsWith('--') || k.includes('-')) el.style.setProperty(k, v == null ? '' : String(v));
    else el.style[k] = v == null ? '' : v;
  }
}

/* ------------------------------------------------------------ text split */

const graphemes = (s) => {
  if (typeof Intl !== 'undefined' && Intl.Segmenter) return Array.from(new Intl.Segmenter(undefined, { granularity: 'grapheme' }).segment(s), (x) => x.segment);
  return Array.from(s);
};

/**
 * Split an element's text into word spans (.st-w > .st-wi) and, optionally, char spans (.st-c),
 * keeping inline markup (<em>, <b>, <span class=accent>) and normal line wrapping.
 * Idempotent: a second call returns the cached result.
 */
export function splitText(el, { chars = true } = {}) {
  if (el.__stSplit) return el.__stSplit;
  const words = [], allChars = [];
  const walk = (node) => {
    for (const child of Array.from(node.childNodes)) {
      if (child.nodeType === 3) {
        const pre = getComputedStyle(node).whiteSpace.startsWith('pre');
        const parts = child.textContent.split(/(\s+)/);
        const frag = document.createDocumentFragment();
        for (const part of parts) {
          if (!part) continue;
          if (/^\s+$/.test(part)) { frag.append(document.createTextNode(pre ? part : ' ')); continue; }
          const inner = h('span', { class: 'st-wi' });
          const w = h('span', { class: 'st-w' }, inner);
          if (chars) {
            for (const g of graphemes(part)) { const c = h('span', { class: 'st-c' }, g); c.dataset.ch = g; inner.append(c); allChars.push(c); }
          } else inner.textContent = part;
          w.dataset.word = part;
          words.push(w); frag.append(w);
        }
        child.replaceWith(frag);
      } else if (child.nodeType === 1 && !child.matches('svg, img, br, .st-nosplit')) walk(child);
    }
  };
  walk(el);
  words.forEach((w, i) => { w.style.setProperty('--i', i); });
  allChars.forEach((c, i) => { c.style.setProperty('--ci', i); });
  const res = { words, chars: allChars, lines: null };
  el.__stSplit = res;
  return res;
}

/** Group word spans into visual lines (call after fonts are loaded and layout is stable). */
export function measureLines(words) {
  const lines = [];
  let top = null, cur = null;
  for (const w of words) {
    const y = Math.round(w.offsetTop);
    if (top === null || Math.abs(y - top) > 2) { cur = []; lines.push(cur); top = y; }
    cur.push(w);
  }
  return lines;
}

/* --------------------------------------------------------------- fonts */

/** Load the fonts an element subtree uses (so measurement happens with the real font). */
export async function ensureFonts(el) {
  if (!document.fonts) return;
  const seen = new Set();
  const nodes = [el, ...Array.from(el.querySelectorAll('*')).slice(0, 80)];
  for (const n of nodes) {
    const cs = getComputedStyle(n);
    const f = `${cs.fontStyle} ${cs.fontWeight} 32px ${cs.fontFamily}`;
    if (!seen.has(f)) seen.add(f);
  }
  const text = (el.textContent || '').slice(0, 200) || 'Ag';
  await Promise.all(Array.from(seen, (f) => document.fonts.load(f, text).catch(() => null)));
  await document.fonts.ready;
}

/* -------------------------------------------------------- theme tokens */

export function token(el, name, fallback = '') {
  const v = getComputedStyle(el || document.documentElement).getPropertyValue(name.startsWith('--') ? name : '--' + name).trim();
  return v || fallback;
}

const num = (s, d) => { const v = parseFloat(s); return Number.isFinite(v) ? (/ms$/.test(String(s).trim()) ? v / 1000 : v) : d; };

/** Motion tokens from the active theme (seconds and ease functions), with defaults. */
export function motion(el) {
  const g = (n, d) => token(el, n, d);
  return {
    energy: g('--motion-energy', 'medium'),
    durIn: num(g('--dur-in', '0.6'), 0.6),
    durOut: num(g('--dur-out', '0.4'), 0.4),
    beat: num(g('--dur-beat', '0.5'), 0.5),
    stagger: num(g('--stagger', '0.05'), 0.05),
    easeIn: g('--ease-in-js', '') || g('--ease-in', 'cubic-bezier(0.3,0,0.8,0.15)'),
    easeOut: g('--ease-out-js', '') || g('--ease-out', 'cubic-bezier(0.16,1,0.3,1)'),
    easeMove: g('--ease-move-js', '') || g('--ease-move', 'cubic-bezier(0.65,0,0.35,1)'),
    easeEmph: g('--ease-emph-js', '') || g('--ease-emph', 'cubic-bezier(0.16,1,0.3,1)'),
  };
}

/* ------------------------------------------------------------- options */

const kebab = (s) => s.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase());

function coerce(raw, def) {
  if (raw == null) return def;
  if (typeof def === 'number') { const v = parseFloat(raw); return Number.isFinite(v) ? v : def; }
  if (typeof def === 'boolean') return raw === '' || raw === 'true' || raw === '1' || raw === 'yes';
  if (def !== null && typeof def === 'object') { try { return JSON.parse(raw); } catch { return def; } }
  if (def === null || def === undefined) {
    const s = raw.trim();
    if (/^[[{]/.test(s)) { try { return JSON.parse(s); } catch { return raw; } }
    if (/^-?\d+(\.\d+)?$/.test(s)) return parseFloat(s);
    if (s === 'true' || s === 'false') return s === 'true';
  }
  return raw;
}

/** Merge defaults <- data-* attributes (and a data-options JSON blob) <- JS options. */
export function readOptions(el, defaults, js = {}) {
  const o = { ...defaults };
  if (el.dataset.options) { try { Object.assign(o, JSON.parse(el.dataset.options)); } catch (e) { console.warn('[showtime] bad data-options JSON on', el, e.message); } }
  for (const k of Object.keys(defaults)) {
    const attr = el.getAttribute('data-' + kebab(k));
    if (attr != null) o[k] = coerce(attr, defaults[k]);
  }
  for (const [k, v] of Object.entries(js || {})) if (v !== undefined) o[k] = v;
  return o;
}

/* ---------------------------------------------------------- stage glue */

function stage() {
  const ST = window.ST;
  if (!ST || typeof ST.onSeek !== 'function') {
    throw new Error('[showtime] /_st/stage.js must be loaded (as a classic <script>) before motion components.');
  }
  return ST;
}

export const onSeek = (fn) => stage().onSeek(fn);
export const waitFor = (p) => { const ST = window.ST; if (ST && ST.waitFor) ST.waitFor(p); return p; };

/** The stage's resolved clip record ({start, end}) for the nearest clip around el, or null. */
function clipRecord(el) {
  const c = el.closest('[data-start]');
  if (!c) return null;
  const ST = window.ST;
  if (ST && typeof ST.clips === 'function') {
    const list = ST.clips();
    const els = document.querySelectorAll('[data-start]');
    const i = Array.prototype.indexOf.call(els, c);
    if (list.length === els.length && i >= 0 && Number.isFinite(list[i].start)) return { start: list[i].start, end: list[i].end ?? Infinity };
  }
  // no stage clip table: plain numbers are absolute, "+N" is relative to the parent clip
  const spec = c.getAttribute('data-start').trim();
  const parent = c.parentElement ? clipRecord(c.parentElement) : null;
  const v = parseFloat(spec.replace(/^\+/, '')) || 0;
  const start = spec.startsWith('+') ? (parent ? parent.start : 0) + v : v;
  const d = parseFloat(c.getAttribute('data-dur'));
  return { start, end: Number.isFinite(d) ? start + d : Infinity };
}

/**
 * Composition time at which an element's clip starts (0 when it is not inside a clip).
 * Component times (at, cues, exitAt...) are local to this, so a component inside
 * <section data-start="4" data-dur="3"> with at=0.5 starts at 4.5 s.
 */
export function clipStart(el) {
  const r = clipRecord(el);
  return r ? r.start : 0;
}

/** Visible duration of the clip that contains el (Infinity when not inside a clip). */
export function clipDuration(el) {
  const r = clipRecord(el);
  return r ? r.end - r.start : Infinity;
}

let cssPromise = null;
/** Inject components.css once (idempotent; skipped when the page already links it). */
export function ensureCSS() {
  if (cssPromise) return cssPromise;
  const href = new URL('./components.css', import.meta.url).href;
  const existing = Array.from(document.querySelectorAll('link[rel=stylesheet], style[data-st-href]'))
    .find((l) => (l.getAttribute('data-st-href') || l.href) === href);
  if (existing) { cssPromise = Promise.resolve(); return cssPromise; }
  // an exported HTML video: the sheet goes in as <style> text (a host page may refuse blob: stylesheets)
  const ex = window.__ST_EXPORT__;
  const text = ex && typeof ex.css === 'function' ? ex.css(href) : null;
  if (text !== null) {
    const style = h('style', { 'data-st-href': href, 'data-st-inline': '' });
    style.textContent = text;
    document.head.prepend(style);
    cssPromise = Promise.resolve();
    return cssPromise;
  }
  const link = h('link', { rel: 'stylesheet', href });
  cssPromise = new Promise((res) => { link.onload = res; link.onerror = () => { console.warn('[showtime] could not load', href); res(); }; });
  // first in <head>, so the page's own styles (and the theme) override component defaults
  document.head.prepend(link);
  return waitFor(cssPromise);
}

const forced = new Map();
/**
 * Make the clips around el visible (the stage hides inactive [data-start] clips with
 * display:none, and before the first seek every clip is inactive) so el can be measured.
 * Returns a function that undoes it. Reference-counted, so overlapping setups are safe.
 */
export function forceVisible(el) {
  const list = [];
  for (let e = el; e && e.nodeType === 1; e = e.parentElement) if (e.hasAttribute('data-start')) list.push(e);
  for (const e of list) {
    const n = forced.get(e) || 0;
    if (!n && !e.hasAttribute('data-active')) { e.setAttribute('data-active', ''); e.__stForced = true; }
    forced.set(e, n + 1);
  }
  let done = false;
  return () => {
    if (done) return;
    done = true;
    for (const e of list) {
      const n = (forced.get(e) || 1) - 1;
      forced.set(e, n);
      if (!n && e.__stForced) { e.removeAttribute('data-active'); e.__stForced = false; }
    }
  };
}

/** Wait until every <img> (decoded) and <video> (first frame) inside el is ready. */
export function mediaReady(el) {
  const imgs = Array.from(el.querySelectorAll('img')).map((img) => {
    const loaded = img.complete ? Promise.resolve() : new Promise((r) => { img.addEventListener('load', r, { once: true }); img.addEventListener('error', r, { once: true }); });
    return loaded.then(() => (img.naturalWidth && img.decode ? img.decode().catch(() => {}) : null));
  });
  const vids = Array.from(el.querySelectorAll('video')).map((v) => (v.readyState >= 2 || v.error ? null : new Promise((r) => {
    // the 15 s fallback timer is cleared as soon as the video answers (a pending timer that fires
    // during playback is reported by check and render as nondeterminism)
    let timer = 0;
    const done = () => { clearTimeout(timer); r(); };
    v.addEventListener('loadeddata', done, { once: true }); v.addEventListener('error', done, { once: true });
    timer = setTimeout(done, 15000);
  })));
  return Promise.all([...imgs, ...vids]);
}

const registry = new Map();

/**
 * Define a component. spec = { name, defaults, setup(el, o, api) -> { update(lt, t), duration, sync } }.
 * Returns a factory (target, options) -> controller. The controller exposes
 * { el, options, ready, update(t), duration, sync } where sync maps named beats to
 * composition seconds (for aligning SFX or narration).
 */
export function define(spec) {
  const factory = (target, options = {}) => {
    const el = $(target);
    if (!el) throw new Error(`[showtime] ${spec.name}: element not found: ${target}`);
    if (el.__stComponent) return el.__stComponent;
    ensureCSS();
    el.classList.add('st-' + spec.name);
    const o = readOptions(el, spec.defaults || {}, options);
    const ctrl = { el, name: spec.name, options: o, state: null, base: 0, sync: {}, duration: 0 };
    el.__stComponent = ctrl;
    const init = async () => {
      await cssPromise;
      const release = forceVisible(el);
      try {
        await ensureFonts(el);
        ctrl.base = clipStart(el) + (Number(o.at) || 0);
        ctrl.state = await spec.setup(el, o, { base: ctrl.base, clipDur: clipDuration(el), motion: motion(el) });
        await mediaReady(el);
      } finally { release(); }
      ctrl.duration = ctrl.state?.duration ?? 0;
      for (const [k, v] of Object.entries(ctrl.state?.sync || {})) ctrl.sync[k] = ctrl.base + v;
      el.dataset.stReady = '';
    };
    ctrl.ready = waitFor(init().catch((e) => { console.error(`[showtime] ${spec.name} setup failed:`, e); throw e; }));
    // a promise returned by update (e.g. work deferred until CSS animations are seeked) gates the frame
    ctrl.update = (t) => (ctrl.state ? ctrl.state.update(t - ctrl.base, t) : undefined);
    onSeek((t) => ctrl.update(t));
    return ctrl;
  };
  factory.componentName = spec.name;
  factory.defaults = spec.defaults || {};
  registry.set(spec.name, factory);
  // a page module that defines its own component after index.js mounted the page: mount its
  // [data-st="name"] elements now (index.js runs first when the page module imports it)
  if (autoMounted) {
    pendingUnknown.delete(spec.name);
    for (const el of $$('[data-st]')) if (!el.__stComponent && el.getAttribute('data-st').trim() === spec.name) factory(el);
  }
  return factory;
}

let autoMounted = false;
const pendingUnknown = new Set();
function warnUnknown(name) {
  console.warn(`[showtime] unknown component data-st="${name}". Known: ${[...registry.keys()].join(', ')}`);
}

/**
 * Mount every [data-st="name"] element under root that is not mounted yet.
 * opts.auto (index.js): names that are not defined yet may still be defined by a page module
 * (define() then mounts them); the warning waits for the page's load event.
 */
export function mountAll(root = document, opts = {}) {
  const out = [];
  if (opts.auto && !autoMounted) {
    autoMounted = true;
    const late = () => { for (const n of pendingUnknown) if (!registry.has(n)) warnUnknown(n); pendingUnknown.clear(); };
    if (document.readyState === 'complete') setTimeout(late, 0);
    else window.addEventListener('load', late, { once: true });
  }
  for (const el of $$('[data-st]', root)) {
    if (el.__stComponent) continue;
    const name = el.getAttribute('data-st').trim();
    const f = registry.get(name);
    if (!f) { if (opts.auto) pendingUnknown.add(name); else warnUnknown(name); continue; }
    out.push(f(el));
  }
  return out;
}

export const components = () => [...registry.keys()];

/* ----------------------------------------------------------- data loading */

/** Fetch JSON (relative to the page), gated on stage readiness. */
export function loadJSON(url) {
  return waitFor(fetch(url).then((r) => { if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`); return r.json(); }));
}

const scripts = new Map();
/** Load a classic script once (e.g. '/_lib/d3/dist/d3.min.js'), gated on readiness. */
export function loadScript(src) {
  if (!scripts.has(src)) {
    scripts.set(src, waitFor(new Promise((res, rej) => {
      const s = h('script', { src });
      s.onload = res;
      s.onerror = () => rej(new Error(`[showtime] could not load ${src} (is setup complete? run: showtime doctor)`));
      document.head.append(s);
    })));
  }
  return scripts.get(src);
}

/** d3 (UMD build served from the showtime node_modules at /_lib). */
export async function d3() {
  if (!window.d3) await loadScript('/_lib/d3/dist/d3.min.js');
  return window.d3;
}

/* ------------------------------------------------------------- layout */

/** Aspect class of a box: 'wide' (> 1.2), 'tall' (< 0.83) or 'square'. */
export function aspectOf(el) {
  const r = (el.clientWidth || innerWidth) / (el.clientHeight || innerHeight);
  return r > 1.2 ? 'wide' : r < 0.83 ? 'tall' : 'square';
}

/**
 * Title-safe insets (fractions of width/height) per aspect. Tall frames keep clear of the
 * platform UI of short-form apps (top bar, caption/handle block, right-hand action rail).
 */
export function safeInsets(aspect) {
  if (aspect === 'tall') return { top: 0.115, bottom: 0.25, left: 0.06, right: 0.15 };
  if (aspect === 'square') return { top: 0.06, bottom: 0.08, left: 0.06, right: 0.06 };
  return { top: 0.06, bottom: 0.08, left: 0.05, right: 0.05 };
}

/** Parse "3-5,8" into [3,4,5,8]. */
export function parseRanges(spec) {
  if (Array.isArray(spec)) return spec.map(Number);
  const out = [];
  for (const part of String(spec ?? '').split(',').map((s) => s.trim()).filter(Boolean)) {
    const m = part.match(/^(\d+)\s*-\s*(\d+)$/);
    if (m) for (let i = +m[1]; i <= +m[2]; i++) out.push(i);
    else if (/^\d+$/.test(part)) out.push(+part);
  }
  return out;
}

/** Format a number: grouping, decimals, compact (1.2k / 3.4M). */
/** The number locale of the page: <html lang="es"> formats 13,7 and 60.000; en-US otherwise. */
export function pageLocale(fallback = 'en-US') {
  const lang = (document.documentElement.getAttribute('lang') || '').trim();
  try { if (lang && Intl.NumberFormat.supportedLocalesOf([lang]).length) return lang; } catch { /* invalid tag */ }
  return fallback;
}

export function formatNumber(v, { decimals = 0, group = true, compact = false, locale = 'en-US' } = {}) {
  if (compact) {
    const a = Math.abs(v);
    const [d, s] = a >= 1e9 ? [1e9, 'B'] : a >= 1e6 ? [1e6, 'M'] : a >= 1e3 ? [1e3, 'k'] : [1, ''];
    return (v / d).toLocaleString(locale, { minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: group }) + s;
  }
  return v.toLocaleString(locale, { minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: group });
}

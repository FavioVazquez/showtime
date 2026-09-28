// showtime transitions: scene-to-scene handoffs as pure functions of progress.
//
//   import { transition } from '/_st/transitions/transitions.js';
//   transition({ from: '#s1', to: '#s2', type: 'push', dir: 'left' });        // at = start of #s2
//   transition({ from: '#s2', to: '#s3', type: 'domain-warp', dur: 0.8 });    // WebGL shader
//
// Or declaratively, on the incoming scene (the previous sibling scene is the outgoing one):
//   <section class="scene" data-start="4" data-dur="4" data-transition="blur-dissolve 0.6">
//   <section class="scene" data-start="8" data-dur="4" data-transition="push left">
// and call autoTransitions() (index.js does it for you).
//
// Timing: the transition window is [at, at + dur] with at = the incoming scene's start by
// default ("align":"start"); the outgoing scene is kept on screen through the window holding
// its last frame, so no start time moves (voice, captions and SFX stay aligned).
// align "center" straddles the cut, align "end" finishes exactly at the cut.
//
// CSS types:  crossfade, dip, blur-dissolve, push, slide, zoom-through, whip-pan, iris, wipe,
//             glitch, flash, stagger
// WebGL types: domain-warp, ridged-burn, sdf-iris, ripple, chromatic-split, cross-zoom,
//             light-leak, pixel-dissolve, morph-warp, whip-blur, signal-glitch
import { clamp, ease, lerp, hash, h, clipStart } from '../components/core.js';

export const CSS_TYPES = ['crossfade', 'dip', 'blur-dissolve', 'push', 'slide', 'zoom-through', 'whip-pan', 'iris', 'wipe', 'glitch', 'flash', 'stagger'];
export const GL_TYPES = ['domain-warp', 'ridged-burn', 'sdf-iris', 'ripple', 'chromatic-split', 'cross-zoom', 'light-leak', 'pixel-dissolve', 'morph-warp', 'whip-blur', 'signal-glitch'];
// What a shader falls back to when WebGL is unavailable.
const GL_FALLBACK = { 'domain-warp': 'blur-dissolve', 'ridged-burn': 'dip', 'sdf-iris': 'iris', ripple: 'blur-dissolve', 'chromatic-split': 'glitch', 'cross-zoom': 'zoom-through', 'light-leak': 'flash', 'pixel-dissolve': 'crossfade', 'morph-warp': 'blur-dissolve', 'whip-blur': 'whip-pan', 'signal-glitch': 'glitch' };
const DEFAULTS = {
  crossfade: { dur: 0.5, ease: 'power2.inOut' }, dip: { dur: 0.7, ease: 'power2.inOut' }, 'blur-dissolve': { dur: 0.6, ease: 'power2.inOut' },
  push: { dur: 0.55, ease: 'power3.inOut' }, slide: { dur: 0.6, ease: 'power3.inOut' }, 'zoom-through': { dur: 0.55, ease: 'linear' },
  'whip-pan': { dur: 0.45, ease: 'power3.inOut' }, iris: { dur: 0.6, ease: 'power2.inOut' }, wipe: { dur: 0.6, ease: 'power2.inOut' },
  glitch: { dur: 0.35, ease: 'linear' }, flash: { dur: 0.4, ease: 'linear' }, stagger: { dur: 0.9, ease: 'linear' },
  'domain-warp': { dur: 0.9, ease: 'sine.inOut' }, 'ridged-burn': { dur: 0.8, ease: 'power1.inOut' }, 'sdf-iris': { dur: 0.65, ease: 'power2.inOut' },
  ripple: { dur: 0.8, ease: 'sine.inOut' }, 'chromatic-split': { dur: 0.4, ease: 'power2.inOut' }, 'cross-zoom': { dur: 0.5, ease: 'power2.inOut' },
  'light-leak': { dur: 0.8, ease: 'sine.inOut' }, 'pixel-dissolve': { dur: 0.6, ease: 'linear' }, 'morph-warp': { dur: 0.8, ease: 'sine.inOut' },
  'whip-blur': { dur: 0.45, ease: 'power3.inOut' }, 'signal-glitch': { dur: 0.35, ease: 'linear' },
};

const DIRS = { left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1] };

/* ------------------------------------------------------------ helpers */

let svgDefs = null;
/** A one-axis gaussian blur filter (for motion blur); returns its url() and a setter. */
function dirBlur(id) {
  if (!svgDefs) {
    svgDefs = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svgDefs.setAttribute('width', '0'); svgDefs.setAttribute('height', '0');
    svgDefs.style.position = 'absolute';
    svgDefs.innerHTML = '<defs></defs>';
    document.body.append(svgDefs);
  }
  let f = svgDefs.querySelector('#' + id);
  if (!f) {
    svgDefs.firstChild.insertAdjacentHTML('beforeend', `<filter id="${id}" x="-20%" y="-5%" width="140%" height="110%" color-interpolation-filters="sRGB"><feGaussianBlur stdDeviation="0 0"/></filter>`);
    f = svgDefs.querySelector('#' + id);
  }
  const blur = f.firstChild;
  return { url: `url(#${id})`, set: (x, y) => blur.setAttribute('stdDeviation', `${x.toFixed(2)} ${y.toFixed(2)}`) };
}
function glitchFilter(id) {
  if (!svgDefs) dirBlur('st-tx-probe');
  let f = svgDefs.querySelector('#' + id);
  if (!f) {
    svgDefs.firstChild.insertAdjacentHTML('beforeend', `<filter id="${id}" x="-5%" y="-5%" width="110%" height="110%" color-interpolation-filters="sRGB">
      <feTurbulence type="turbulence" baseFrequency="0.0001 0.06" numOctaves="1" seed="1" result="n"/>
      <feDisplacementMap in="SourceGraphic" in2="n" scale="0" xChannelSelector="R" yChannelSelector="B" result="d"/>
      <feColorMatrix in="d" type="matrix" values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0" result="r"/>
      <feOffset in="r" dx="0" result="ro"/>
      <feColorMatrix in="d" type="matrix" values="0 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 1 0" result="gb"/>
      <feOffset in="gb" dx="0" result="gbo"/>
      <feBlend in="ro" in2="gbo" mode="screen"/></filter>`);
    f = svgDefs.querySelector('#' + id);
  }
  const [turb, disp, , off1, , off2] = f.children;
  return {
    url: `url(#${id})`,
    set(k, step, W) {
      turb.setAttribute('seed', String(1 + (step % 97)));
      turb.setAttribute('baseFrequency', `0.0001 ${(0.02 + hash(step, 5) * 0.08).toFixed(4)}`);
      disp.setAttribute('scale', (k * W * 0.06).toFixed(2));
      off1.setAttribute('dx', (k * W * 0.012).toFixed(2));
      off2.setAttribute('dx', (-k * W * 0.012).toFixed(2));
    },
  };
}

function overlayFor(parent) {
  let o = parent.querySelector(':scope > .st-tx-overlay');
  if (!o) { o = h('div', { class: 'st-tx-overlay', style: { position: 'absolute', inset: '0', pointerEvents: 'none', opacity: '0', display: 'none' } }); parent.append(o); }
  return o;
}

/* ---------------------------------------------------- CSS transitions */
// Each: (ctx) => void. ctx: { p (eased), r (linear), A (out), B (in), W, H, o (options), set(el, props), overlay() }

const CSS = {
  crossfade({ p, B, set }) { set(B, { opacity: p }); },

  dip({ r, A, B, set, overlay, o }) {
    const ov = overlay();
    ov.style.background = o.color || 'var(--bg, #000)';
    const half = r < 0.5;
    const k = half ? ease('power2.in')(r * 2) : 1 - ease('power2.out')((r - 0.5) * 2);
    ov.style.opacity = k.toFixed(4);
    set(A, { visibility: half ? 'visible' : 'hidden' });
    set(B, { visibility: half ? 'hidden' : 'visible' });
  },

  'blur-dissolve'({ p, r, A, B, W, set, o }) {
    const b = Number(o.blur) || Math.min(24, W * 0.0125);
    set(A, { filter: `blur(${(b * p).toFixed(2)}px)`, scale: (1 + 0.035 * p).toFixed(4) });
    set(B, { opacity: ease('power1.inOut')(clamp((r - 0.12) / 0.76)).toFixed(4), filter: `blur(${(b * (1 - p)).toFixed(2)}px)`, scale: lerp(0.97, 1, p).toFixed(4) });
  },

  push({ p, r, A, B, W, set, o, id }) {
    const [dx, dy] = DIRS[o.dir] || DIRS.left;
    set(A, { translate: `${(dx * p * 100).toFixed(3)}% ${(dy * p * 100).toFixed(3)}%` });
    set(B, { translate: `${(-dx * (1 - p) * 100).toFixed(3)}% ${(-dy * (1 - p) * 100).toFixed(3)}%` });
    if (o.blur) {
      const f = dirBlur(id + '-mb');
      const k = Math.sin(Math.PI * r) * Math.min(16, W * 0.009);
      f.set(Math.abs(dx) * k, Math.abs(dy) * k);
      set(A, { filter: f.url }); set(B, { filter: f.url });
    }
  },

  slide({ p, A, B, set, o }) {
    const [dx, dy] = DIRS[o.dir] || DIRS.left;
    set(A, { translate: `${(dx * p * 30).toFixed(3)}% ${(dy * p * 30).toFixed(3)}%`, filter: `brightness(${lerp(1, 0.55, p).toFixed(3)})` });
    set(B, { translate: `${(-dx * (1 - p) * 100).toFixed(3)}% ${(-dy * (1 - p) * 100).toFixed(3)}%`, 'z-index': 3 });
  },

  'zoom-through'({ r, A, B, set, o }) {
    // exit accelerates into the lens, entry decelerates out of it; they meet at peak speed
    const inv = !!o.inverse;
    const a = ease('power3.in')(clamp(r / 0.6));
    const b = ease('expo.out')(clamp((r - 0.4) / 0.6));
    set(A, { scale: (inv ? lerp(1, 0.8, a) : lerp(1, 2.2, a)).toFixed(4), filter: `blur(${(a * 10).toFixed(2)}px)`, opacity: (1 - clamp((r - 0.35) / 0.25)).toFixed(4) });
    set(B, { scale: (inv ? lerp(1.25, 1, b) : lerp(0.6, 1, b)).toFixed(4), filter: `blur(${((1 - b) * 10).toFixed(2)}px)`, opacity: clamp((r - 0.4) / 0.2).toFixed(4) });
  },

  'whip-pan'({ p, r, A, B, W, set, o, id }) {
    const [dx, dy] = DIRS[o.dir] || DIRS.left;
    const f = dirBlur(id + '-whip');
    const k = Math.sin(Math.PI * r) ** 1.5 * Math.min(22, W * 0.0125);
    f.set(Math.abs(dx) * k, Math.abs(dy) * k);
    set(A, { translate: `${(dx * p * 100).toFixed(3)}% ${(dy * p * 100).toFixed(3)}%`, filter: f.url });
    set(B, { translate: `${(-dx * (1 - p) * 100).toFixed(3)}% ${(-dy * (1 - p) * 100).toFixed(3)}%`, filter: f.url });
  },

  iris({ p, B, W, H, set, o }) {
    const [cx, cy] = Array.isArray(o.center) ? o.center : [50, 50];
    const fx = Math.max(cx, 100 - cx) / 100 * W, fy = Math.max(cy, 100 - cy) / 100 * H;
    const R = Math.hypot(fx, fy) * 1.02 * p;
    set(B, { 'clip-path': `circle(${R.toFixed(2)}px at ${cx}% ${cy}%)`, scale: lerp(1.04, 1, p).toFixed(4), 'transform-origin': `${cx}% ${cy}%` });
  },

  wipe({ p, r, B, set, o }) {
    const shape = o.shape || 'diagonal';
    if (shape === 'linear') {
      const [dx, dy] = DIRS[o.dir] || DIRS.left;
      const k = ((1 - p) * 100).toFixed(3);
      const ins = dx < 0 ? `0 0 0 ${k}%` : dx > 0 ? `0 ${k}% 0 0` : dy < 0 ? `${k}% 0 0 0` : `0 0 ${k}% 0`;
      set(B, { 'clip-path': `inset(${ins})` });
    } else if (shape === 'diamond') {
      const s = p * 100;
      set(B, { 'clip-path': `polygon(50% ${50 - s}%, ${50 + s}% 50%, 50% ${50 + s}%, ${50 - s}% 50%)` });
    } else if (shape === 'bars' || shape === 'blinds') {
      // N staggered bars (mask layers); vertical bars sweep top to bottom
      const n = Number(o.count) || 7;
      const layers = [], sizes = [], pos = [];
      for (let i = 0; i < n; i++) {
        const q = ease('power3.inOut')(clamp((r - (i / n) * 0.35) / 0.65));
        layers.push('linear-gradient(#000,#000)');
        sizes.push(`${(100 / n + 0.2).toFixed(3)}% ${(q * 100).toFixed(3)}%`);
        pos.push(`${((i / (n - 1)) * 100).toFixed(3)}% 0%`);
      }
      const m = { 'mask-image': layers.join(','), 'mask-size': sizes.join(','), 'mask-position': pos.join(','), 'mask-repeat': 'no-repeat' };
      set(B, { ...m, '-webkit-mask-image': m['mask-image'], '-webkit-mask-size': m['mask-size'], '-webkit-mask-position': m['mask-position'], '-webkit-mask-repeat': 'no-repeat' });
    } else {
      // diagonal edge sweeping from the top-left corner
      const e = p * 2 * 100;
      set(B, { 'clip-path': `polygon(0 0, ${e}% 0, ${e - 100}% 100%, 0 100%)` });
    }
  },

  glitch({ r, A, B, W, set, id }) {
    const f = glitchFilter(id + '-gl');
    const step = Math.floor(r * 14);
    const k = Math.sin(Math.PI * r) * (0.55 + 0.45 * hash(step, 3));
    f.set(k, step, W);
    const cut = r >= 0.5;
    set(A, { visibility: cut ? 'hidden' : 'visible', filter: f.url, translate: `${((hash(step, 7) - 0.5) * k * 3).toFixed(2)}% 0` });
    set(B, { visibility: cut ? 'visible' : 'hidden', filter: f.url, translate: `${((hash(step, 9) - 0.5) * k * 3).toFixed(2)}% 0` });
  },

  flash({ r, A, B, set, overlay, o }) {
    const ov = overlay();
    ov.style.background = o.color || '#fff';
    const cut = 0.35;
    const k = r < cut ? ease('power2.in')(r / cut) : 1 - ease('power2.out')((r - cut) / (1 - cut));
    ov.style.opacity = k.toFixed(4);
    set(A, { visibility: r < cut ? 'visible' : 'hidden' });
    set(B, { visibility: r < cut ? 'hidden' : 'visible' });
  },

  stagger({ r, A, B, set, o }) {
    // outgoing items leave in reading order, the scene swaps, incoming items arrive
    const pick = (scene) => {
      let items = Array.from(scene.querySelectorAll(o.items || '[data-stagger-item], [data-stagger] > *'));
      if (!items.length) {
        // default: the scene's own children (or the children of its single wrapper)
        const kids = Array.from(scene.children).filter((c) => !c.matches('script, style, .st-cursor, .st-keystrokes, .st-grain, .glow, .vignette'));
        items = kids.length === 1 && kids[0].children.length ? Array.from(kids[0].children) : kids;
      }
      return items.slice(0, 16);
    };
    const outs = A.__stItems || (A.__stItems = pick(A));
    const ins = B.__stItems || (B.__stItems = pick(B));
    const E = ease('power3.in'), X = ease('power3.out');
    outs.forEach((el, i) => {
      const q = E(clamp((r - i * (0.3 / Math.max(1, outs.length))) / 0.3));
      set(el, { translate: `0 ${(-q * 3).toFixed(3)}cqmin`, filter: `opacity(${(1 - q).toFixed(4)})` });
    });
    ins.forEach((el, i) => {
      const q = X(clamp((r - 0.5 - i * (0.25 / Math.max(1, ins.length))) / 0.35));
      set(el, { translate: `0 ${((1 - q) * 3).toFixed(3)}cqmin`, filter: `opacity(${q.toFixed(4)})` });
    });
    const swap = clamp((r - 0.42) / 0.12);
    set(B, { opacity: swap.toFixed(4) });
  },
};

/* ------------------------------------------------------------ manager */

const list = [];
const touched = new Map(); // el -> Map(prop -> original inline value)
let installed = false;
let glMod = null;
let ids = 0;
const RENDER = window.__ST_RENDER__ || null;
const LAYERS = !!(RENDER && RENDER.layers);
let frameLayers = null; // layer-protocol state for the current frame

function remember(el, prop) {
  let m = touched.get(el);
  if (!m) { m = new Map(); touched.set(el, m); }
  if (!m.has(prop)) m.set(prop, el.style.getPropertyValue(prop));
}
function makeSet() {
  return (el, props) => {
    for (const [k, v] of Object.entries(props)) { remember(el, k); el.style.setProperty(k, String(v)); }
  };
}
function resetAll() {
  for (const [el, m] of touched) for (const [k, v] of m) el.style.setProperty(k, v);
  for (const tr of list) if (tr.overlay) { tr.overlay.style.display = 'none'; tr.overlay.style.opacity = '0'; }
}

function install() {
  if (installed) return;
  installed = true;
  const ST = window.ST;
  if (!ST) throw new Error('[showtime] transitions need /_st/stage.js loaded first');
  ST.adapter('transitions', (t) => {
    resetAll();
    // the window's edges snap to frames exactly like the stage's clip edges (a start written as 6.6667 or
    // 53.434, within 1 ms of a frame, is on that frame); otherwise the incoming clip is shown alone for
    // one frame before the transition starts
    const active = list.filter((tr) => t >= snapEdge(tr.start) - 1e-6 && t < snapEdge(tr.start + tr.dur) - 1e-6);
    for (const tr of list) if (tr.gl && !active.includes(tr) && tr.gl.comp) tr.gl.comp.show(false);
    frameLayers = null;
    if (!active.length) return;
    const jobs = [];
    for (const tr of active) {
      // keep both scenes on screen for the whole window (the stage hides inactive clips)
      for (const s of [tr.A, tr.B]) if (s.hasAttribute('data-start') && !s.hasAttribute('data-active')) s.setAttribute('data-active', '');
      const set = makeSet();
      const r = clamp((t - tr.start) / tr.dur);
      const p = tr.ease(r);
      set(tr.A, { 'z-index': tr.zA }); set(tr.B, { 'z-index': tr.zB });
      liftOverlays(tr, set);
      if (tr.gl) { jobs.push(runGL(tr, p, r, set)); continue; }
      const ctx = { p, r, A: tr.A, B: tr.B, W: tr.W, H: tr.H, o: tr.o, id: tr.id, set, overlay: () => { tr.overlay = overlayFor(tr.parent); tr.overlay.style.display = ''; tr.overlay.style.zIndex = tr.zB + 1; return tr.overlay; } };
      CSS[tr.type](ctx);
    }
    if (jobs.length) return Promise.all(jobs).then(() => undefined);
    return undefined;
  });
}

// A time within 1 ms of a frame boundary is on that frame (the stage's rule for clip edges).
function snapEdge(t) {
  const fps = Number(window.ST?.cfg?.fps) || 0;
  if (!(fps > 0) || !isFinite(t)) return t;
  const x = t * fps, f = Math.round(x);
  return Math.abs(x - f) < Math.max(1e-3, fps * 1e-3) ? f / fps : t;
}

// Inside a window the two scenes get z-index 1-3 and the shader canvas / CSS overlay one more.
// Layers placed after the incoming scene (a persistent map, labels, a logo bug, captions) have no
// z-index of their own and would drop under them for the whole window, so lift them above the
// transition for the window's duration; the parent is isolated so the scene z-indices stay local.
const OVERLAY_Z = 10;
function liftOverlays(tr, set) {
  const parent = tr.parent;
  if (!parent) return;
  if (getComputedStyle(parent).isolation !== 'isolate') set(parent, { isolation: 'isolate' });
  let after = false;
  for (const el of parent.children) {
    if (el === tr.B) { after = true; continue; }
    if (el === tr.A) continue;
    if (!after || el.classList.contains('st-tx-overlay') || el.hasAttribute('data-st-gl')) continue;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.position === 'static' || s.zIndex !== 'auto') continue;
    set(el, { 'z-index': OVERLAY_Z });
  }
}

async function runGL(tr, p, r) {
  if (!glMod) glMod = await import('./gl.js');
  const g = tr.gl;
  if (!g.comp) {
    g.comp = new glMod.Compositor(tr.parent, tr.W, tr.H);
    if (!g.comp.ok) {
      console.warn(`[showtime] WebGL unavailable: "${tr.type}" falls back to the CSS "${GL_FALLBACK[tr.type]}" transition`);
      tr.gl = null; tr.type = GL_FALLBACK[tr.type];
      return;
    }
    g.colors = glMod.colorsFor(tr.parent);
  }
  const comp = g.comp;
  comp.canvas.style.zIndex = String(tr.zB + 1);
  const uniforms = { p, r, accent: g.colors.accent, accent2: g.colors.accent2, seed: tr.seed, a: tr.o.a, b: tr.o.b };
  if (LAYERS) {
    // the renderer captures both layers solo, then calls compose()
    comp.show(false);
    frameLayers = frameLayers || [];
    frameLayers.push({ tr, uniforms, images: {} });
    return;
  }
  // wait one microtask so every other seek handler has updated the scenes first, then for
  // any video inside the two scenes to land on its frame
  await Promise.resolve();
  const vids = [...tr.A.querySelectorAll('video'), ...tr.B.querySelectorAll('video')];
  await Promise.all(vids.map((v) => (v.seeking ? new Promise((res) => { v.addEventListener('seeked', res, { once: true }); v.addEventListener('error', res, { once: true }); }) : null)));
  const src = (scene) => (scene.tagName === 'CANVAS' ? Promise.resolve(scene) : glMod.snapshot(scene, tr.W, tr.H));
  const [a, b] = await Promise.all([src(tr.A), src(tr.B)]);
  const ua = await glMod.uploadSafe(comp, 0, a, () => src(tr.A));
  const ub = await glMod.uploadSafe(comp, 1, b, () => src(tr.B));
  comp.draw(tr.type, ua, ub, uniforms);
  comp.show(true);
}

/** The layer protocol used by the renderer when window.__ST_RENDER__.layers is true. */
window.__stLayers = {
  version: 1,
  pending() {
    if (!frameLayers) return [];
    return frameLayers.flatMap((f, i) => [{ id: `${i}:A` }, { id: `${i}:B` }]);
  },
  solo(id) {
    const [i, side] = id.split(':');
    const f = frameLayers && frameLayers[+i];
    if (!f) return false;
    this._undo && this._undo();
    this._undo = glMod.solo(side === 'A' ? f.tr.A : f.tr.B);
    return true;
  },
  unsolo() { if (this._undo) { this._undo(); this._undo = null; } },
  async put(id, dataUrl) {
    const [i, side] = id.split(':');
    const f = frameLayers && frameLayers[+i];
    if (!f) return false;
    const img = new Image();
    img.src = dataUrl;
    await img.decode();
    f.images[side] = img;
    return true;
  },
  async compose() {
    this.unsolo();
    for (const f of frameLayers || []) {
      if (!f.images.A || !f.images.B) continue;
      f.tr.gl.comp.draw(f.tr.type, f.images.A, f.images.B, f.uniforms);
      f.tr.gl.comp.show(true);
    }
    return true;
  },
};

/**
 * Register a transition between two scenes.
 * opts: { from, to, type='crossfade', at, dur, ease, align='start'|'center'|'end', dir, blur,
 *         color, shape, count, center:[x%,y%], inverse, items, a, b, seed }
 * Returns the transition record ({start, dur, type, ...}).
 */
export function transition(opts = {}) {
  const A = typeof opts.from === 'string' ? document.querySelector(opts.from) : opts.from;
  const B = typeof opts.to === 'string' ? document.querySelector(opts.to) : opts.to;
  if (!A || !B) throw new Error(`[showtime] transition: scene not found (${opts.from} -> ${opts.to}). Scenes must exist before transitions are registered.`);
  let type = String(opts.type || 'crossfade');
  const gl = GL_TYPES.includes(type);
  if (!gl && !CSS[type]) throw new Error(`[showtime] transition: unknown type "${type}". CSS: ${CSS_TYPES.join(', ')}. WebGL: ${GL_TYPES.join(', ')}`);
  const d = DEFAULTS[type] || { dur: 0.6, ease: 'power2.inOut' };
  const dur = Math.max(1 / 60, Number(opts.dur) || d.dur);
  let start = opts.at != null ? Number(opts.at) : clipStart(B);
  if (opts.at == null) {
    if (opts.align === 'center') start -= dur / 2;
    else if (opts.align === 'end') start -= dur;
    // peak: the transition's cut (the white of a flash, the swap of a glitch) lands on the scene
    // start, i.e. on the beat the scene was placed on
    else if (opts.align === 'peak') start -= dur * (CUT_AT[type] ?? 0.5);
  }
  const parent = B.parentElement;
  const W = Math.round(parent.clientWidth || window.ST?.cfg?.width || innerWidth);
  const H = Math.round(parent.clientHeight || window.ST?.cfg?.height || innerHeight);
  const zBase = 1;
  // "wipe left" names a direction: that is the straight wipe (the default shape is a diagonal sweep)
  if (type === 'wipe' && opts.dir && !opts.shape) opts = { ...opts, shape: 'linear' };
  const topOut = type === 'zoom-through' && opts.inverse;
  const tr = {
    id: 'st-tx-' + (++ids), type, A, B, parent, start, dur, W, H, o: opts,
    ease: ease(opts.ease || d.ease), seed: Number(opts.seed ?? ids),
    zA: topOut ? zBase + 2 : zBase, zB: topOut ? zBase + 1 : zBase + 2,
    gl: gl ? { comp: null } : null, overlay: null,
  };
  list.push(tr);
  install();
  return tr;
}

// where in its window each hard-cut transition swaps scenes (for align "peak")
const CUT_AT = { flash: 0.35, glitch: 0.5, 'signal-glitch': 0.5, 'light-leak': 0.5, 'chromatic-split': 0.5, 'whip-pan': 0.5, 'whip-blur': 0.5 };

/** Parse "push left 0.5", "domain-warp 0.8s", "iris" into {type, dir, dur}. */
export function parseSpec(spec) {
  const parts = String(spec || '').trim().split(/\s+/).filter(Boolean);
  const out = {};
  for (const p of parts) {
    if (/^\d*\.?\d+s?$/.test(p)) out.dur = parseFloat(p);
    else if (DIRS[p]) out.dir = p;
    else if (/^(center|end|start|peak)$/.test(p)) out.align = p;
    else if (!out.type) out.type = p;
  }
  return out;
}

/**
 * Wire every scene that has data-transition="<type> [dir] [seconds]" to the scene before it
 * (previous sibling with data-start). Extra options can go in data-transition-options (JSON).
 */
export function autoTransitions(root = document) {
  const made = [];
  for (const B of root.querySelectorAll('[data-transition]')) {
    if (B.__stTx) continue;
    const spec = parseSpec(B.getAttribute('data-transition'));
    if (!spec.type || spec.type === 'cut' || spec.type === 'none') continue;
    let A = B.previousElementSibling;
    while (A && !A.hasAttribute('data-start')) A = A.previousElementSibling;
    if (!A) { console.warn('[showtime] data-transition on the first scene has nothing to transition from', B); continue; }
    let extra = {};
    try { extra = JSON.parse(B.getAttribute('data-transition-options') || '{}'); } catch (e) { console.warn('[showtime] bad data-transition-options JSON', e.message); }
    B.__stTx = transition({ from: A, to: B, ...spec, ...extra });
    made.push(B.__stTx);
  }
  return made;
}

/** All registered transitions (for tools and tests). */
export const transitions = () => list.map((t) => ({ type: t.type, start: t.start, dur: t.dur, gl: !!t.gl, from: t.A.id || '', to: t.B.id || '' }));
// `showtime check` reads the windows so layout found mid-transition is judged on the settled frame.
window.__stTransitions = transitions;


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
//             glitch, flash, stagger, and the camera moves through (fly into a portal element of
//             the outgoing scene: the next scene is inside it), pan (travel to the next scene laid
//             beside this one) and match (shared elements, data-match="name", carry across the cut)
// WebGL types: domain-warp, ridged-burn, sdf-iris, ripple, chromatic-split, cross-zoom,
//             light-leak, pixel-dissolve, morph-warp, whip-blur, signal-glitch
import { clamp, ease, lerp, hash, h, clipStart } from '../components/core.js';
import { portalShape } from '../components/portal.js';

export const CSS_TYPES = ['crossfade', 'dip', 'blur-dissolve', 'push', 'slide', 'zoom-through', 'whip-pan', 'iris', 'wipe', 'glitch', 'flash', 'stagger', 'through', 'pan', 'match'];
export const GL_TYPES = ['domain-warp', 'ridged-burn', 'sdf-iris', 'ripple', 'chromatic-split', 'cross-zoom', 'light-leak', 'pixel-dissolve', 'morph-warp', 'whip-blur', 'signal-glitch'];
// What a shader falls back to when WebGL is unavailable.
const GL_FALLBACK = { 'domain-warp': 'blur-dissolve', 'ridged-burn': 'dip', 'sdf-iris': 'iris', ripple: 'blur-dissolve', 'chromatic-split': 'glitch', 'cross-zoom': 'zoom-through', 'light-leak': 'flash', 'pixel-dissolve': 'crossfade', 'morph-warp': 'blur-dissolve', 'whip-blur': 'whip-pan', 'signal-glitch': 'glitch' };
const DEFAULTS = {
  crossfade: { dur: 0.5, ease: 'power2.inOut' }, dip: { dur: 0.7, ease: 'power2.inOut' }, 'blur-dissolve': { dur: 0.6, ease: 'power2.inOut' },
  push: { dur: 0.55, ease: 'power3.inOut' }, slide: { dur: 0.6, ease: 'power3.inOut' }, 'zoom-through': { dur: 0.55, ease: 'linear' },
  'whip-pan': { dur: 0.45, ease: 'power3.inOut' }, iris: { dur: 0.6, ease: 'power2.inOut' }, wipe: { dur: 0.6, ease: 'power2.inOut' },
  glitch: { dur: 0.35, ease: 'linear' }, flash: { dur: 0.4, ease: 'linear' }, stagger: { dur: 0.9, ease: 'linear' },
  through: { dur: 1.5, ease: 'power2.inOut' }, pan: { dur: 1.2, ease: 'power3.inOut' }, match: { dur: 0.9, ease: 'power3.inOut' },
  'domain-warp': { dur: 0.9, ease: 'sine.inOut' }, 'ridged-burn': { dur: 0.8, ease: 'power1.inOut' }, 'sdf-iris': { dur: 0.65, ease: 'power2.inOut' },
  ripple: { dur: 0.8, ease: 'sine.inOut' }, 'chromatic-split': { dur: 0.4, ease: 'power2.inOut' }, 'cross-zoom': { dur: 0.5, ease: 'power2.inOut' },
  'light-leak': { dur: 0.8, ease: 'sine.inOut' }, 'pixel-dissolve': { dur: 0.6, ease: 'linear' }, 'morph-warp': { dur: 0.8, ease: 'sine.inOut' },
  'whip-blur': { dur: 0.45, ease: 'power3.inOut' }, 'signal-glitch': { dur: 0.35, ease: 'linear' },
};

const DIRS = { left: [-1, 0], right: [1, 0], up: [0, -1], down: [0, 1] };
const MEASURED = new Set(['through', 'match']);

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
  crossfade({ p, A, B, set }) {
    set(B, { opacity: p });
    if (seeThrough(B)) set(A, { opacity: (1 - p).toFixed(4) });   // no opaque ground to cover the old scene
  },

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
    const inB = ease('power1.inOut')(clamp((r - 0.12) / 0.76));
    set(B, { opacity: inB.toFixed(4), filter: `blur(${(b * (1 - p)).toFixed(2)}px)`, scale: lerp(0.97, 1, p).toFixed(4) });
    if (seeThrough(B)) set(A, { opacity: (1 - ease('power1.inOut')(clamp((r - 0.05) / 0.7))).toFixed(4) });
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

  through({ p, A, B, W, H, o, set, tr }) {
    // One continuous camera move: the camera flies into a portal element of the outgoing scene
    // (data-portal, or `into`), and the incoming scene is what was inside it. With `inverse` the
    // camera pulls back out of a portal of the incoming scene instead (the outgoing scene shrinks
    // into it). Zoom runs in log space, so the push feels even from 1x to 40x.
    const inv = !!o.inverse;
    const outer = inv ? B : A, inner = inv ? A : B;
    const q = inv ? 1 - p : p;
    const origin = tr.parent.getBoundingClientRect();
    const k = origin.width / W || 1;
    const portal = findPortal(outer, o.into || o.portal);
    if (!portal) {
      if (!tr.warned) { tr.warned = true; console.warn(`[showtime] through: no [data-portal] in #${outer.id || 'scene'}; using a blur-dissolve`); }
      CSS['blur-dissolve']({ p, r: p, A, B, W, set, o: {} });
      return;
    }
    const sh = portalShape(portal, origin);
    const px = sh.x / k, py = sh.y / k, pw = Math.max(1, sh.w / k), ph = Math.max(1, sh.h / k);
    const cx = px + pw / 2, cy = py + ph / 2, CX = W / 2, CY = H / 2;
    // One pure zoom, no second motion: the opening keeps its own shape and simply grows with the camera.
    // The incoming scene starts CONTAINED in the opening (an ellipse: inscribed so the frame's corners are
    // inside it) and ends at 1:1 exactly when the opening covers the whole frame, so nothing is clipped,
    // grown or swapped separately: the letter's ink flies past the lens at the speed of the zoom.
    const s0 = sh.kind === 'ellipse' ? Math.min(pw / (Math.SQRT2 * W), ph / (Math.SQRT2 * H)) : Math.min(pw / W, ph / H);
    const z = Math.exp(q * Math.log(1 / s0));               // camera zoom on the outer scene
    // a dolly toward ONE fixed point: the screen point P that stays put while the camera zooms is chosen so the
    // opening lands on the frame centre exactly at the end (no pan first and zoom after: one motion)
    const z1 = 1 / s0;
    const Px = (CX - z1 * cx) / (1 - z1), Py = (CY - z1 * cy) / (1 - z1);
    const qx = Px + z * (cx - Px), qy = Py + z * (cy - Py);   // where the opening's centre is on screen now
    // text of the outer scene fades out before the zoom carries it across the frame edge, so no frame
    // shows a headline cut mid-word ("file2 comes befor"); the portal's own word flies through whole (measured
    // before the camera transform is set)
    fadeCropped(tr, outer, portal, origin, k, { W, H, z, q, z1, Px, Py, ox: qx - z * cx, oy: qy - z * cy }, set);
    set(outer, { 'transform-origin': '0 0', transform: `translate(${(qx - z * cx).toFixed(3)}px, ${(qy - z * cy).toFixed(3)}px) scale(${z.toFixed(5)})` });
    const zi = z * s0;
    set(inner, { 'transform-origin': '0 0', transform: `translate(${(qx - zi * CX).toFixed(3)}px, ${(qy - zi * CY).toFixed(3)}px) scale(${zi.toFixed(5)})` });
    // the opening, fixed: in the inner scene's coordinates (centred, 1/s0 times the portal) and cut out of
    // the outer scene at the portal itself (so a see-through incoming scene never shows the outer behind it)
    const f = (x) => x.toFixed(2);
    const outerFrame = `M0 0H${f(W)}V${f(H)}H0Z`;
    if (sh.kind === 'ellipse') {
      const rx = sh.rx / k / s0, ry = sh.ry / k / s0;
      set(inner, { 'clip-path': `ellipse(${f(rx)}px ${f(ry)}px at 50% 50%)` });
      const ox = sh.rx / k, oy = sh.ry / k;
      set(outer, { 'clip-path': `path(evenodd, "${outerFrame} M${f(cx - ox)} ${f(cy)}a${f(ox)} ${f(oy)} 0 1 0 ${f(2 * ox)} 0a${f(ox)} ${f(oy)} 0 1 0 ${f(-2 * ox)} 0Z")` });
    } else {
      const hw = pw / s0 / 2, hh = ph / s0 / 2, rad = sh.radius / k / s0;
      set(inner, { 'clip-path': `inset(${f(CY - hh)}px ${f(W - CX - hw)}px ${f(H - CY - hh)}px ${f(CX - hw)}px round ${f(rad * (1 - q))}px)` });
      set(outer, { 'clip-path': `path(evenodd, "${outerFrame} M${f(px)} ${f(py)}H${f(px + pw)}V${f(py + ph)}H${f(px)}Z")` });
    }
    if (q >= 0.999) set(outer, { visibility: 'hidden' });
    // pulling back: the old scene dissolves into the portal's own picture as it lands
    if (inv && !o.keep) set(inner, { opacity: ease('power1.inOut')(clamp(q / 0.22)).toFixed(4) });
  },

  pan({ p, r, A, B, W, H, o, set, id }) {
    // The camera travels to the next scene, laid beside this one in one world, with a slight
    // pull-back arc (`arc`, default 0.06 = 6 % smaller mid-move) and a gap between the frames.
    const [dx, dy] = DIRS[o.dir] || DIRS.left;
    const gap = o.gap != null ? Number(o.gap) : 0.06;
    const Dx = -dx * W * (1 + gap), Dy = -dy * H * (1 + gap);
    const arc = o.arc != null ? Number(o.arc) : 0.06;
    const s = 1 - arc * Math.sin(Math.PI * p);
    const CX = W / 2, CY = H / 2;
    const Kx = CX + Dx * p, Ky = CY + Dy * p;
    const place = (el, Ox, Oy) => set(el, { 'transform-origin': '0 0',
      transform: `translate(${(CX + s * (Ox - Kx)).toFixed(3)}px, ${(CY + s * (Oy - Ky)).toFixed(3)}px) scale(${s.toFixed(5)})` });
    place(A, 0, 0);
    place(B, Dx, Dy);
    if (o.blur) {
      const f = dirBlur(id + '-pan');
      const b = Math.sin(Math.PI * r) ** 2 * Math.min(10, W * 0.005);
      f.set(Math.abs(dx) * b, Math.abs(dy) * b);
      set(A, { filter: f.url }); set(B, { filter: f.url });
    }
  },

  match({ p, r, A, B, W, o, set, tr }) {
    // Shared elements carry across the cut: every [data-match="name"] in the incoming scene flies
    // from where its partner sits in the outgoing scene to its own place; everything else in the
    // outgoing scene fades out and the rest of the incoming scene fades in around it. Scenes on the
    // same ground read as one continuous shot.
    const origin = tr.parent.getBoundingClientRect();
    const k = origin.width / W || 1;
    const pairs = [];
    for (const b of B.querySelectorAll('[data-match]')) {
      const a = A.querySelector(`[data-match="${CSS_ESC(b.getAttribute('data-match'))}"]`);
      if (a) pairs.push([a, b]);
    }
    const eo = ease('power2.inOut')(clamp(r / 0.55));
    const ei = ease('power2.inOut')(clamp((r - 0.35) / 0.65));
    // the incoming ground fades in on its own layer (under the scene's content), so the shared
    // elements never disappear behind it
    const cs = getComputedStyle(B);
    let ground = B.querySelector(':scope > .st-tx-ground');
    if (!ground) { ground = h('div', { class: 'st-tx-ground', 'data-st-decor': '', style: { position: 'absolute', inset: '0', zIndex: '-1', pointerEvents: 'none', display: 'none' } }); B.prepend(ground); }
    set(ground, { display: 'block', 'background-color': cs.backgroundColor, 'background-image': cs.backgroundImage });
    set(B, { background: 'transparent' });
    fadeAround(A, pairs.map((x) => x[0]), 1 - eo, set);
    fadeAround(B, pairs.map((x) => x[1]), ei, set);
    const ki = ease('power1.inOut')(clamp((r - 0.15) / 0.6));
    for (const [a, b] of pairs) {
      const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      const dxp = (rb.left + rb.width / 2 - ra.left - ra.width / 2) / k, dyp = (rb.top + rb.height / 2 - ra.top - ra.height / 2) / k;
      const sab = rb.width / Math.max(1, ra.width);
      set(a, { translate: `${(dxp * p).toFixed(3)}px ${(dyp * p).toFixed(3)}px`, scale: lerp(1, sab, p).toFixed(5), 'transform-origin': '50% 50%' });
      set(b, { translate: `${(-dxp * (1 - p)).toFixed(3)}px ${(-dyp * (1 - p)).toFixed(3)}px`, scale: lerp(1 / sab, 1, p).toFixed(5), 'transform-origin': '50% 50%',
        opacity: (o.swap === 'cut' ? (r >= 0.5 ? 1 : 0) : ki).toFixed(4) });
    }
  },
};

/** A scene with no ground of its own (transparent background: the page's world shows through it). */
function seeThrough(el) {
  const cs = getComputedStyle(el);
  const m = cs.backgroundColor.match(/rgba?\(([^)]+)\)/);
  const alpha = m ? (m[1].split(',').length === 4 ? parseFloat(m[1].split(',')[3]) : 1) : (cs.backgroundColor === 'transparent' ? 0 : 1);
  return alpha < 0.05 && (!cs.backgroundImage || cs.backgroundImage === 'none');
}

const CSS_ESC = (s) => (window.CSS && window.CSS.escape ? window.CSS.escape(s) : String(s).replace(/["\\]/g, '\\$&'));

/** The portal element of a scene: a selector, else the first [data-portal] inside it. */
function findPortal(scene, sel) {
  if (sel && typeof sel !== 'string') return sel;
  return (sel && (scene.querySelector(sel) || document.querySelector(sel))) || scene.querySelector('[data-portal]');
}

/** The text of `scene` as runs the camera can fade one by one: each non-blank text node outside the
 * portal's own word is wrapped once in <span data-st-tx-text> (inline, so the layout does not change).
 * The portal's word (the portal and its inline ancestors) is marked data-st-portal-word. */
function textRuns(tr, scene, portal) {
  if (tr.textRuns && tr.textRuns.scene === scene) return tr.textRuns.list;
  let word = portal;
  while (word.parentElement && word.parentElement !== scene && /^inline/.test(getComputedStyle(word.parentElement).display)) word = word.parentElement;
  word.setAttribute('data-st-portal-word', '');
  const nodes = [];
  const tw = document.createTreeWalker(scene, NodeFilter.SHOW_TEXT);
  for (let n = tw.nextNode(); n; n = tw.nextNode()) {
    if (!n.nodeValue.trim() || word.contains(n)) continue;
    const pe = n.parentElement;
    if (!pe || pe.closest('script,style,svg,[data-st-decor]')) continue;
    nodes.push(n);
  }
  const out = [];
  for (const n of nodes) {
    const pe = n.parentElement;
    if (pe.hasAttribute('data-st-tx-text')) { out.push(pe); continue; }
    const sp = document.createElement('span');
    sp.setAttribute('data-st-tx-text', '');
    n.replaceWith(sp);
    sp.append(n);
    out.push(sp);
  }
  tr.textRuns = { scene, list: out };
  return out;
}

/** Fade each text run of `scene` as the camera transform (screen = o + z * page) brings it within a
 * small margin of the frame edge: gone before any of it is cut. Measured untransformed (the manager
 * resets the scene's transform before each frame). */
function fadeCropped(tr, scene, portal, origin, k, cam, set) {
  if (!(cam.z > 1.0005)) return;
  const ramp = 0.025 * Math.min(cam.W, cam.H);
  for (const el of textRuns(tr, scene, portal)) {
    const b = el.getBoundingClientRect();
    if (b.width < 1 || b.height < 1) continue;
    const x0 = cam.ox + cam.z * ((b.left - origin.left) / k), x1 = cam.ox + cam.z * ((b.right - origin.left) / k);
    const y0 = cam.oy + cam.z * ((b.top - origin.top) / k), y1 = cam.oy + cam.z * ((b.bottom - origin.top) / k);
    if (x1 < 0 || y1 < 0 || x0 > cam.W || y0 > cam.H) { set(el, { opacity: '0' }); continue; }
    // how far it has come toward the edge compared with where it was laid out (text laid out near an
    // edge on purpose is not dimmed at the start of the move)
    const d = Math.min(x0, y0, cam.W - x1, cam.H - y1);
    const d0 = Math.min((b.left - origin.left) / k, (b.top - origin.top) / k, cam.W - (b.right - origin.left) / k, cam.H - (b.bottom - origin.top) / k);
    if (!(d0 > 1)) continue;
    // dim along the whole approach: find the zoom progress at which this word reaches the frame edge in
    // the dolly (x(z) = P + z (x - P)) and fade over that span, so words dissolve as the camera travels
    // instead of vanishing in a beat just before the edge
    let withMove = 1;
    if (cam.q != null && cam.z1 > 1) {
      const lx0 = (b.left - origin.left) / k, lx1 = (b.right - origin.left) / k, ly0 = (b.top - origin.top) / k, ly1 = (b.bottom - origin.top) / k;
      const zs = [];
      if (lx0 < cam.Px) zs.push(cam.Px / (cam.Px - lx0));
      if (lx1 > cam.Px) zs.push((cam.W - cam.Px) / (lx1 - cam.Px));
      if (ly0 < cam.Py) zs.push(cam.Py / (cam.Py - ly0));
      if (ly1 > cam.Py) zs.push((cam.H - cam.Py) / (ly1 - cam.Py));
      const zc = Math.max(1.0001, Math.min(...zs, cam.z1));
      const qc = Math.log(zc) / Math.log(cam.z1);
      withMove = 1 - ease('sine.inOut')(clamp(cam.q / (0.9 * qc)));
    }
    const a = Math.min(clamp(d / Math.min(ramp, d0)), withMove);
    if (a < 1) set(el, { opacity: a.toFixed(4) });
  }
}

/** Set opacity on everything in `scene` except the given elements and their ancestors. */
function fadeAround(scene, keep, alpha, set) {
  const path = new Set();
  for (const el of keep) for (let e = el; e && e !== scene; e = e.parentElement) path.add(e);
  const walk = (node) => {
    for (const c of node.children) {
      if (keep.includes(c)) continue;
      if (path.has(c)) walk(c);
      else set(c, { opacity: alpha.toFixed(4) });
    }
  };
  walk(scene);
}

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
      const ctx = { p, r, A: tr.A, B: tr.B, W: tr.W, H: tr.H, o: tr.o, id: tr.id, tr, set, overlay: () => { tr.overlay = overlayFor(tr.parent); tr.overlay.style.display = ''; tr.overlay.style.zIndex = tr.zB + 1; return tr.overlay; } };
      // camera moves measure the page (a portal, shared elements): run them after the stage has seeked the
      // CSS animations of this frame (handlers run first), so the measure never sees the previous frame
      if (MEASURED.has(tr.type)) jobs.push(Promise.resolve().then(() => CSS[tr.type](ctx)));
      else CSS[tr.type](ctx);
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
 *         color, shape, count, center:[x%,y%], inverse, items, a, b, seed,
 *         into (through: the portal selector), keep (through inverse: no dissolve), arc, gap (pan),
 *         swap (match: 'cut' swaps shared elements at the midpoint instead of dissolving) }
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
  const topOut = (type === 'zoom-through' || type === 'through') && opts.inverse;
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


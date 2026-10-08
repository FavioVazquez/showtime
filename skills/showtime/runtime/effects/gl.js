// showtime looks: the small WebGL layer the look components share (fluted-glass, tilt-shift,
// liquid-metal, mesh-gradient, god-rays, marble, metaballs in runtime/components). Original code, GLSL ES
// 1.00 on WebGL 1, so it runs the same on a GPU and on SwiftShader (a machine without one).
//
// What it gives a look:
//   lookLayer(el, {name, scale, alpha, fallback})
//                                          a canvas filling the element at its box size x devicePixelRatio
//                                          x scale, or null when WebGL is missing (use the fallback). It holds
//                                          a WebGL context (preserveDrawingBuffer: the renderer screenshots it)
//                                          only while the look's clip is on screen (context lifecycle, below);
//                                          in a render on a GPU each frame is read back into a 2D canvas
//                                          (frames read back, below)
//   layer.program(frag, defines)           compile a fragment shader (HEADER is prepended); variants by
//                                          #define, never by a branch on a uniform (a CPU renderer pays both)
//   layer.texture(source, {mips, wrap})    upload an <img> or <canvas>; mips: a power-of-two copy with
//                                          mipmaps (cheap prefiltered blur and minification); wrap 'repeat'
//                                          tiles a power-of-two source (or the mipmapped copy across)
//   layer.target(w, h)                     an offscreen colour target (for multi-pass looks)
//   layer.draw(prog, uniforms, target)     one fullscreen pass
//   palette(el)                            --bg --fg --accent --accent-2 as 0..1 sRGB triples
//   oklab(rgb), OKLAB_GLSL                 colours blended in Oklab (no grey or muddy middles)
//   softwareGL()                           whether WebGL is drawn on the CPU here (a cheaper default then)
//   keyed(values, keys, lt)                option values moved by keyframes [{at, dur, ease, ...values}]
//   register(entry)                        what `showtime check` reads (window.__stLooks): size, passes, cost
//
// The cost model is the no-GPU cost measured on our 64-core test machine (SwiftShader, one browser, 1080p, each frame a
// seek and a JPEG screenshot as render takes it, against the same page without the look): extra ms per frame
// for one full-frame pass of each kind, and how that grows with the pass's size (cost x (pixels / 1080p) ^ exp:
// a CPU renderer does not pay in proportion to pixels, its canvas and caches cost more at full size). `showtime
// check` warns above runtime/thresholds.json "look_budget_ms".
import { clamp, clipDuration, clipStart, ease, lerp, token } from '../components/core.js';

export const COST_1080P = { glass: 40, blur13: 66, tap2: 25, sphere: 22, march: 57, mesh: 22, rays: 122, lit: 27, marble: 51, metaballs: 30 };
export const COST_EXP = { glass: 0.76, march: 1.2, mesh: 0.57, rays: 1.5, lit: 0.5, marble: 1.4, metaballs: 1.3 };
const PX_1080P = 1920 * 1080;

const VERT = `attribute vec2 aPos; varying vec2 vUv;
void main() { vUv = vec2(aPos.x * 0.5 + 0.5, 0.5 - aPos.y * 0.5); gl_Position = vec4(aPos, 0.0, 1.0); }`;

/** Prepended to every look shader. vUv (0,0) is the top-left of the target; uRes its size in px. */
export const HEADER = `
precision highp float;
varying vec2 vUv;
uniform vec2 uRes;
uniform float uT;
uniform float uSeed;
float hash(vec2 p) {
  vec3 q = fract(vec3(p.xyx) * vec3(0.1127, 0.1393, 0.1219) + uSeed * 0.0137);
  q += dot(q, q.zyx + 41.73);
  return fract((q.x + q.z) * q.y);
}
// +-half a code value of noise fixed per pixel: smooth gradients stay smooth after 8-bit capture
// and compression instead of stepping into bands
vec3 dither(vec3 c) { return c + (hash(gl_FragCoord.xy + 17.0) - 0.5) / 255.0; }
vec3 toLinear(vec3 c) { return pow(max(c, 0.0), vec3(2.2)); }
vec3 toSrgb(vec3 c) { return pow(max(c, 0.0), vec3(1.0 / 2.2)); }
float luma(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }
`;

/* ------------------------------------------------------------ colours */

let probe = null;
/** Any CSS colour (hex, rgb(), oklch() ...) -> [r, g, b] in 0..1 sRGB, through a 1x1 canvas. */
export function rgb(str, fallback = '#808080') {
  if (!probe) { const c = document.createElement('canvas'); c.width = c.height = 1; probe = c.getContext('2d', { willReadFrequently: true }); }
  probe.clearRect(0, 0, 1, 1);
  probe.fillStyle = fallback;
  try { probe.fillStyle = String(str || '').trim() || fallback; } catch { /* keep the fallback */ }
  probe.fillRect(0, 0, 1, 1);
  const d = probe.getImageData(0, 0, 1, 1).data;
  return [d[0] / 255, d[1] / 255, d[2] / 255];
}

export const lum = (c) => 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
export const mixRgb = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
export const cssRgb = (c, a = 1) => `rgb(${c.map((v) => Math.round(clamp(v) * 255)).join(' ')}${a < 1 ? ` / ${a}` : ''})`;

/**
 * 0..1 sRGB -> Oklab (with the same 2.2 gamma the shaders use), for colour fields blended in a perceptual
 * space: a mix of two colours keeps its lightness and does not go muddy in the middle. OKLAB_GLSL turns it back.
 */
export function oklab(c) {
  const [r, g, b] = c.map((v) => Math.pow(Math.max(0, v), 2.2));
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
export const OKLAB_GLSL = `
vec3 fromOklab(vec3 c) {
  vec3 q = mat3(1.0, 1.0, 1.0, 0.3963377774, -0.1055613458, -0.0894841775, 0.2158037573, -0.0638541728, -1.291485548) * c;
  q = q * q * q;
  return mat3(4.0767416621, -1.2684380046, -0.0041960863, -3.3077115913, 2.6097574011, -0.7034186147,
    0.2309699292, -0.3413193965, 1.707614701) * q;
}`;

/** The theme palette around el (look signatures and brand kits set these tokens). */
export function palette(el) {
  const t = (n, d) => rgb(token(el, n, d), d);
  const bg = t('--bg', '#101218');
  const fg = t('--fg', '#f4f4f6');
  const accent = t('--accent', '#ff9a3c');
  const accent2 = rgb(token(el, '--accent-2', '') || token(el, '--accent', '#3cc8ff'), '#3cc8ff');
  return { bg, fg, accent, accent2, dark: lum(bg) < 0.45 };
}

/* ---------------------------------------------------------- keyframes */

/**
 * Option values moved over time by keyframes: keys = [{at, dur, ease, ...values}], `at` in seconds of
 * the look's local time; each key moves the named values from where they are to its own over
 * [at, at + dur] (dur 0: a cut). A pure function of lt.
 */
export function keyed(values, keys, lt) {
  const v = { ...values };
  if (!Array.isArray(keys) || !keys.length) return v;
  const list = keys.filter((k) => k && Number.isFinite(Number(k.at))).sort((a, b) => a.at - b.at);
  for (const k of list) {
    const at = Number(k.at);
    if (lt < at) break;
    const dur = Math.max(0, Number(k.dur) || 0);
    const p = dur > 0 ? ease(k.ease || 'camera')(clamp((lt - at) / dur)) : 1;
    for (const n of Object.keys(values)) if (k[n] != null && Number.isFinite(Number(k[n]))) v[n] = lerp(v[n], Number(k[n]), p);
  }
  return v;
}

/* ------------------------------------------------------------ sources */

/** The media a look reads: data-src (an image URL), else a child <img> or <canvas>. */
export function findSource(el, src) {
  if (src) {
    const img = document.createElement('img');
    img.alt = '';
    img.decoding = 'sync';
    img.src = src;
    el.prepend(img);
    return img;
  }
  return el.querySelector(':scope > img, :scope > canvas:not(.st-look-canvas), :scope > picture img') || null;
}

export function sourceReady(src) {
  if (!src || src.tagName !== 'IMG') return Promise.resolve();
  const loaded = src.complete && src.naturalWidth ? Promise.resolve() : new Promise((r) => { src.addEventListener('load', r, { once: true }); src.addEventListener('error', r, { once: true }); });
  return loaded.then(() => (src.naturalWidth && src.decode ? src.decode().catch(() => {}) : null));
}

export const sourceSize = (s) => (s.tagName === 'IMG' ? [s.naturalWidth, s.naturalHeight] : [s.width, s.height]);

/**
 * Cover-fit of a source into a box (like object-fit: cover), with a focus point [x%, y%]:
 * returns [sx, sy, ox, oy] for uvSrc = (uvBox - 0.5) * s + 0.5 + o.
 */
export function coverFit(srcW, srcH, boxW, boxH, focus = [50, 50]) {
  const ra = srcW / Math.max(1, srcH), rb = boxW / Math.max(1, boxH);
  const sx = ra > rb ? rb / ra : 1, sy = ra > rb ? 1 : ra / rb;
  const fx = clamp((Number(focus[0]) || 50) / 100), fy = clamp((Number(focus[1]) || 50) / 100);
  return [sx, sy, (fx - 0.5) * (1 - sx), (fy - 0.5) * (1 - sy)];
}

/* -------------------------------------------------------------- layer */

const POT = (n) => 2 ** Math.round(Math.log2(Math.max(1, n)));

/** The element's box in CSS px (layout size: transforms such as a camera push do not change it). */
export function boxSize(el) {
  let w = el.clientWidth, h = el.clientHeight;
  if (!w || !h) {
    const cfg = (window.ST && window.ST.cfg) || {};
    w = w || cfg.width || innerWidth; h = h || cfg.height || innerHeight;
  }
  return [w, h];
}

/* ------------------------------------------------------- no GPU? */

// WebGL renderer strings of a CPU rasteriser (the same list as scripts/lib/stagehost.mjs SOFTWARE_GL)
const SOFTWARE_GL = /swiftshader|llvmpipe|softpipe|basic render driver|\bwarp\b|software/i;
let software = null;
/**
 * Whether WebGL here is drawn on the CPU (SwiftShader and the like: a machine without a GPU). In a render the
 * renderer says (__ST_RENDER__.softwareGL: one answer for every worker, and a span spliced into a full render
 * gets that render's answer); elsewhere it is read once from a throwaway 1x1 context given back at once. A look
 * may pick a cheaper default from it and stay frame-exact.
 */
export function softwareGL() {
  if (software !== null) return software;
  // a render decides once for all its workers (and a span takes the decision of the render it is spliced into)
  const R = window.__ST_RENDER__;
  if (R && typeof R.softwareGL === 'boolean') return (software = R.softwareGL);
  software = false;
  try {
    const c = document.createElement('canvas');
    c.width = c.height = 1;
    const gl = c.getContext('webgl');
    if (gl) {
      const ext = gl.getExtension('WEBGL_debug_renderer_info');
      software = SOFTWARE_GL.test(String(ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER)));
      const lose = gl.getExtension('WEBGL_lose_context');
      if (lose) lose.loseContext();
    }
  } catch { software = false; }
  return software;
}

/* ------------------------------------------------- context lifecycle */

// Chrome keeps about 16 WebGL contexts per page and drops the oldest past that. A look holds a context only
// while its clip is on screen: a look records what it needs (programs, textures, targets) and builds it on a
// fresh context the first time it draws in a clip; after its clip it gives the context back. A seek back
// into the clip builds the same things again from the same recorded sources, so the frame is the same.
const LIVE = new Set();
const LIVE_MAX = 12;                 // room left for transitions and the page's own canvases
let lastUse = 0, hooked = false;

function hookSeeks() {
  if (hooked || !window.ST || typeof window.ST.adapter !== 'function') return;
  hooked = true;
  // registered after the looks' own handlers, so it runs after they drew: off-screen looks give back
  window.ST.adapter('looks', () => { for (const L of [...LIVE]) if (!onScreen(L.el)) L.release(); });
}

function material(gl, h) {
  if (h.kind === 'program') {
    const sh = (type, code) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, code);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(`[showtime] ${h.name}: shader failed to compile: ${gl.getShaderInfoLog(s)}`);
      return s;
    };
    const prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VERT));
    const defs = Object.entries(h.defines).map(([k, v]) => `#define ${k} ${v}\n`).join('');
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, defs + HEADER + h.frag));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(`[showtime] ${h.name}: shader failed to link: ${gl.getProgramInfoLog(prog)}`);
    Object.assign(h, { prog, aPos: gl.getAttribLocation(prog, 'aPos'), loc: {} });
  } else if (h.kind === 'texture') {
    const t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    const { source, mips, wrap, max } = h;
    let up = h.pixels || source, ok = !!source;
    if (source && mips && !h.pixels) {
      const lim = gl.getParameter(gl.MAX_TEXTURE_SIZE) || 4096;
      const [sw, sh] = sourceSize(source);
      const c = document.createElement('canvas');
      c.width = Math.min(max, lim, POT(sw)); c.height = Math.min(max, lim, POT(sh));
      // a CPU canvas (willReadFrequently), read back as bytes once and kept: a GPU-drawn copy can differ by a
      // code value between browser processes (frames would differ between render workers), and the bytes kept
      // make a rebuilt context get exactly the same texture
      const g = c.getContext('2d', { willReadFrequently: true });
      g.imageSmoothingQuality = 'high';
      g.drawImage(source, 0, 0, c.width, c.height);
      try { up = h.pixels = g.getImageData(0, 0, c.width, c.height); } catch { up = c; }
    }
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    try {
      if (ok) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, up);
    } catch (e) { ok = false; console.warn(`[showtime] ${h.name}: could not upload the source image (${e.message})`); }
    if (!ok) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 0]));
    // repeat needs a power-of-two texture on WebGL 1: the mipmapped copy is one, or the source already is
    // (and then it repeats both ways, as a tiling noise does)
    const [tw, th] = source ? sourceSize(source) : [1, 1];
    const pot = !mips && tw > 0 && th > 0 && (tw & (tw - 1)) === 0 && (th & (th - 1)) === 0;
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, wrap === 'repeat' && (mips || pot) ? gl.REPEAT : gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, wrap === 'repeat' && pot ? gl.REPEAT : gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    if (ok && mips) { gl.generateMipmap(gl.TEXTURE_2D); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR); }
    else gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    Object.assign(h, { tex: t, mips: ok && mips });
  } else {
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, h.w, h.h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    for (const [k, v] of [[gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR], [gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
    const fb = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    Object.assign(h, { tex, fb });
  }
}

/* ---------------------------------------------- frames read back on a GPU */

// In a render on a GPU the screenshot of a WebGL canvas can come out stale: the compositor reads the canvas's
// buffer before the GPU has finished writing it, and the frame shows what that buffer held a few frames
// earlier (seen on the macOS CI runner's virtual GPU: one look 3 frames behind in one frame of 93, so 1 and 3
// workers differed). There each look draws on a WebGL canvas kept out of the page, reads its pixels back
// (readPixels waits for the GPU) and puts them on a 2D canvas the page shows, as Chrome itself does without
// a GPU. window.ST_LOOKS_READBACK (true / false) forces it on or off, for tests.
function readbackHere() {
  if (typeof window.ST_LOOKS_READBACK === 'boolean') return window.ST_LOOKS_READBACK;
  return !!window.__ST_RENDER__ && !softwareGL();
}

/**
 * A WebGL look filling `el`: a canvas at its box size x devicePixelRatio x scale. Returns null when WebGL is
 * missing or a test turned it off (window.ST_LOOKS_GL === false); the look then draws its fallback.
 * program(), texture() and target() return handles the look keeps; draw() builds them on a context when it
 * needs one. fallback: drawn (once) if a context can no longer be had mid-video.
 */
export function lookLayer(el, { name, scale = 1, alpha = false, fallback = null } = {}) {
  const [bw, bh] = boxSize(el);
  const dpr = window.devicePixelRatio || 1;
  const W = Math.max(2, Math.round(bw * dpr * scale)), H = Math.max(2, Math.round(bh * dpr * scale));
  if (window.ST_LOOKS_GL === false) return null;
  const opts = { preserveDrawingBuffer: true, premultipliedAlpha: true, antialias: false, alpha, depth: false, stencil: false };
  const handles = [];
  const readback = readbackHere();
  // what check reports (looks[].present): 'readback' (a 2D canvas the frames are read into) or 'webgl'
  el.__stLookPresent = readback ? 'readback' : 'webgl';
  const layer = {
    el, gl: null, glc: null, canvas: null, ctx: null, px: null, buf: null, W, H, dpr, scale, box: [bw, bh], used: 0, failed: false, readback,
    /** Get a context (a new canvas each time) and build every handle on it. false when WebGL cannot be had. */
    acquire() {
      while (LIVE.size >= LIVE_MAX) {
        const all = [...LIVE].sort((a, b) => a.used - b.used);
        (all.find((L) => !onScreen(L.el)) || all[0]).release();
      }
      const canvas = document.createElement('canvas');
      canvas.className = 'st-look-canvas';
      canvas.width = W; canvas.height = H;
      canvas.setAttribute('aria-hidden', 'true');
      let gl = null;
      try { gl = canvas.getContext('webgl', opts) || canvas.getContext('experimental-webgl', opts); } catch { gl = null; }
      if (!gl) return false;
      // a context the browser takes back (too many at once, a GPU reset) is reported: check says look_lost
      canvas.addEventListener('webglcontextlost', () => {
        if (canvas.__stReleased) return;
        if (el.__stLook) el.__stLook.lost = (el.__stLook.lost || 0) + 1;
        if (layer.glc === canvas) { layer.gl = null; LIVE.delete(layer); }
      });
      if (readback) {
        // the WebGL canvas stays out of the page; the page shows one 2D canvas (a CPU one) for the look's life
        if (!layer.canvas) {
          const shown = document.createElement('canvas');
          shown.className = 'st-look-canvas';
          shown.width = W; shown.height = H;
          shown.setAttribute('aria-hidden', 'true');
          el.prepend(shown);
          layer.canvas = shown;
          layer.ctx = shown.getContext('2d', { alpha, willReadFrequently: true });
          layer.px = layer.ctx.createImageData(W, H);
        }
      } else {
        if (layer.canvas && layer.canvas.isConnected) layer.canvas.replaceWith(canvas); else el.prepend(canvas);
        layer.canvas = canvas;
      }
      layer.glc = canvas; layer.gl = gl;
      layer.buf = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, layer.buf);
      gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      for (const h of handles) material(gl, h);
      LIVE.add(layer);
      hookSeeks();
      return true;
    },
    /**
     * Give the context back. Off screen the canvas just stays (it is drawn again before its clip shows); a look
     * that must give it back while on screen (more looks at once than contexts) leaves a 2D copy of this frame.
     */
    release() {
      const gl = layer.gl;
      LIVE.delete(layer);
      layer.gl = null;
      if (!gl) return;
      const old = layer.glc;
      old.__stReleased = true;
      // read back, the page's 2D canvas keeps this frame by itself
      if (!readback && onScreen(el)) {
        const still = document.createElement('canvas');
        still.className = old.className;
        still.width = W; still.height = H;
        still.setAttribute('aria-hidden', 'true');
        still.getContext('2d').drawImage(old, 0, 0);
        old.replaceWith(still);
        layer.canvas = still;
      }
      const ext = gl.getExtension('WEBGL_lose_context');
      if (ext) ext.loseContext();
    },
    /** defines: {NAME: value} become #define lines, for variants compiled apart instead of branched per pixel */
    program(frag, defines = {}) {
      const h = { kind: 'program', name, frag, defines, prog: null, aPos: -1, loc: {} };
      handles.push(h);
      if (layer.gl) material(layer.gl, h);
      return h;
    },
    /** Upload an image or canvas. mips: draw it into a power-of-two canvas first and build mipmaps. */
    texture(source, { mips = false, wrap = 'clamp', max = 2048 } = {}) {
      const h = { kind: 'texture', name, source, mips, wrap, max, pixels: null, tex: null, update() {
        // a canvas source drawn by the page: upload its current pixels (no mipmaps)
        const gl = layer.gl;
        if (!gl || !h.tex) return;
        gl.bindTexture(gl.TEXTURE_2D, h.tex);
        try { gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source); } catch { /* keep the last */ }
      } };
      handles.push(h);
      if (layer.gl) material(layer.gl, h);
      return h;
    },
    /** An offscreen RGBA target of w x h px (linear filtering, clamped). */
    target(w, h) {
      const t = { kind: 'target', name, w, h, tex: null, fb: null };
      handles.push(t);
      if (layer.gl) material(layer.gl, t);
      return t;
    },
    /**
     * One fullscreen pass. u: {name: number | [a, b] | [a, b, c] | [a, b, c, d] | {tex, unit}}.
     * target: an offscreen target, or null for the canvas.
     */
    draw(P, u, target = null) {
      if (!layer.gl && !layer.failed && !layer.acquire()) {
        // no context to be had any more: the look's still fallback, once
        layer.failed = true;
        if (layer.canvas) layer.canvas.style.visibility = 'hidden';
        if (el.__stLook) { el.__stLook.lost = (el.__stLook.lost || 0) + 1; el.__stLook.gl = false; }
        if (fallback) fallback();
      }
      const gl = layer.gl;
      if (!gl) return;
      layer.used = ++lastUse;
      gl.bindFramebuffer(gl.FRAMEBUFFER, target ? target.fb : null);
      const w = target ? target.w : W, h = target ? target.h : H;
      gl.viewport(0, 0, w, h);
      gl.useProgram(P.prog);
      const loc = (k) => (k in P.loc ? P.loc[k] : (P.loc[k] = gl.getUniformLocation(P.prog, k)));
      const all = { uRes: [w, h], ...u };
      let unit = 0;
      for (const [k, v] of Object.entries(all)) {
        const l = loc(k);
        if (l == null) continue;
        if (v && v.tex) { gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, v.tex); gl.uniform1i(l, unit); unit++; }
        else if (Array.isArray(v)) gl['uniform' + v.length + 'f'](l, ...v);
        else gl.uniform1f(l, Number(v) || 0);
      }
      gl.bindBuffer(gl.ARRAY_BUFFER, layer.buf);
      gl.enableVertexAttribArray(P.aPos);
      gl.vertexAttribPointer(P.aPos, 2, gl.FLOAT, false, 0, 0);
      if (alpha && !target) { gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); }
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      if (readback && !target) layer.present();
    },
    /** Read the canvas pass back and put it on the page's 2D canvas (readback only). */
    present() {
      const gl = layer.gl, img = layer.px, d = img.data, stride = W * 4;
      // readPixels returns once the GPU has drawn the pass: the frame is complete, never a buffer still being written
      gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(d.buffer, d.byteOffset, d.length));
      // WebGL rows run bottom-up, ImageData rows top-down
      const row = layer.row || (layer.row = new Uint8ClampedArray(stride));
      for (let a = 0, b = (H - 1) * stride; a < b; a += stride, b -= stride) {
        row.set(d.subarray(a, a + stride));
        d.copyWithin(a, b, b + stride);
        d.set(row, b);
      }
      // the drawing buffer holds premultiplied colour; ImageData takes it straight
      if (alpha) {
        for (let i = 0; i < d.length; i += 4) {
          const k = d[i + 3];
          if (k > 0 && k < 255) { const f = 255 / k; d[i] *= f; d[i + 1] *= f; d[i + 2] *= f; }
        }
      }
      layer.ctx.putImageData(img, 0, 0);
    },
  };
  // WebGL must be there at setup (else the caller draws its fallback); the shaders are checked on this first
  // context, which goes back after the first seek if the look's clip is not on screen
  if (!layer.acquire()) return null;
  return layer;
}

/* ---------------------------------------------------------- registry */

/** Extra ms per frame without a GPU for a list of passes [{kind, w, h}] (px). */
export function estimateMs(passes) {
  let ms = 0;
  for (const p of passes) ms += (COST_1080P[p.kind] || 0) * Math.pow((p.w * p.h) / PX_1080P, COST_EXP[p.kind] || 1);
  return Math.round(ms * 10) / 10;
}

function selectorOf(el) {
  if (el.id) return '#' + el.id;
  const scene = el.closest('[id]');
  const cls = [...el.classList].filter((c) => !c.startsWith('st-')).slice(0, 2).map((c) => '.' + c).join('');
  return (scene ? '#' + scene.id + ' ' : '') + (cls || `[data-st="${el.getAttribute('data-st') || ''}"]`);
}

/**
 * Record a look for `showtime check`: window.__stLooks = [{look, sel, gl, preset, box, passes, ms, note, clip, lost,
 * present, software}]. gl false means the fallback drew (no WebGL here); clip is the [start, end] the look is on screen (end
 * null: to the end); lost counts contexts the browser took back; present is how a WebGL look reaches the page:
 * 'webgl' (its own canvas) or 'readback' (read into a 2D canvas: a render on a GPU), null for a fallback;
 * software whether WebGL is drawn on the CPU here (softwareGL), null for a fallback.
 */
export function register(el, entry) {
  const list = window.__stLooks || (window.__stLooks = []);
  const start = clipStart(el), dur = clipDuration(el);
  const rec = { look: entry.look, sel: selectorOf(el), gl: !!entry.gl, preset: entry.preset || null,
    box: entry.box, passes: entry.passes || [], ms: entry.passes ? estimateMs(entry.passes) : 0, note: entry.note || null,
    clip: [start, Number.isFinite(dur) ? start + dur : null], lost: 0,
    present: entry.gl ? el.__stLookPresent || 'webgl' : null, software: entry.gl ? softwareGL() : null };
  list.push(rec);
  el.__stLook = rec;
  el.dataset.stLook = entry.gl ? 'webgl' : 'fallback';
  return rec;
}

/** Whether the clip el sits in is on screen at this seek (the stage sets data-active before handlers run). */
export function onScreen(el) {
  const c = el.closest('[data-start]');
  return !c || c.hasAttribute('data-active');
}

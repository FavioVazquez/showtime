// WebGL transition compositor: blends two scene layers through a GLSL shader.
//
// Where the two layers come from, in order of preference:
//   1. Layer capture by the renderer (exact pixels): when window.__ST_RENDER__.layers is true the
//      renderer, after each seek, asks window.__stLayers.pending(), screenshots each layer solo,
//      hands the images back with put(), then calls compose(). See references/transitions.md.
//   2. In-page rasterisation (default, also used by the preview player): each scene is cloned
//      with its ancestor chain, the page CSS (fonts and images inlined as data URLs) is embedded,
//      and the result is drawn through an SVG <foreignObject> image. Canvases and videos are
//      frozen to images first; CSS animations are frozen at their current values.
// Scenes that are themselves <canvas> (film.js) are uploaded directly.
import { HEADER, SHADERS, PARAMS } from './shaders.js';

const VERT = `attribute vec2 aPos; varying vec2 vUv;
void main() { vUv = vec2(aPos.x * 0.5 + 0.5, 0.5 - aPos.y * 0.5); gl_Position = vec4(aPos, 0.0, 1.0); }`;

/* ------------------------------------------------------------ colours */

function parseColor(str) {
  const c = document.createElement('canvas').getContext('2d');
  c.fillStyle = '#000';
  c.fillStyle = str || '#ff9933';
  const v = c.fillStyle; // normalised to #rrggbb or rgba()
  if (v.startsWith('#')) { const n = parseInt(v.slice(1), 16); return [(n >> 16) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255]; }
  const m = v.match(/[\d.]+/g) || [255, 153, 51];
  return [m[0] / 255, m[1] / 255, m[2] / 255];
}

/* --------------------------------------------------------- compositor */

export class Compositor {
  constructor(parent, W, H) {
    this.W = W; this.H = H;
    this.canvas = document.createElement('canvas');
    this.canvas.className = 'st-gl-layer';
    this.canvas.width = W; this.canvas.height = H;
    Object.assign(this.canvas.style, { position: 'absolute', left: '0', top: '0', width: '100%', height: '100%', pointerEvents: 'none', display: 'none' });
    this.canvas.setAttribute('data-st-gl', '');
    parent.append(this.canvas);
    const opts = { preserveDrawingBuffer: true, premultipliedAlpha: false, antialias: false, alpha: false, depth: false, stencil: false };
    this.gl = this.canvas.getContext('webgl', opts) || this.canvas.getContext('experimental-webgl', opts);
    if (!this.gl) { this.canvas.remove(); this.ok = false; return; }
    this.ok = true;
    const gl = this.gl;
    this.buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    this.programs = {};
    this.tex = [this.texture(), this.texture()];
  }

  texture() {
    const gl = this.gl;
    const t = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([0, 0, 0, 255]));
    return t;
  }

  program(name) {
    if (this.programs[name]) return this.programs[name];
    const src = SHADERS[name];
    if (!src) throw new Error(`[showtime] unknown shader transition "${name}". Known: ${Object.keys(SHADERS).join(', ')}`);
    const gl = this.gl;
    const sh = (type, code) => {
      const s = gl.createShader(type);
      gl.shaderSource(s, code);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(`[showtime] shader "${name}" failed to compile: ${gl.getShaderInfoLog(s)}`);
      return s;
    };
    const frag = HEADER + src + '\nvoid main() { gl_FragColor = vec4(clamp(blend(vUv).rgb, 0.0, 1.0), 1.0); }\n';
    const prog = gl.createProgram();
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, frag));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(`[showtime] shader "${name}" failed to link: ${gl.getProgramInfoLog(prog)}`);
    const u = {};
    for (const k of ['uFrom', 'uTo', 'uP', 'uR', 'uRes', 'uAspect', 'uAccent', 'uAccent2', 'uSeed', 'uA', 'uB']) u[k] = gl.getUniformLocation(prog, k);
    this.programs[name] = { prog, u, aPos: gl.getAttribLocation(prog, 'aPos') };
    return this.programs[name];
  }

  upload(i, source) {
    const gl = this.gl;
    gl.activeTexture(gl.TEXTURE0 + i);
    gl.bindTexture(gl.TEXTURE_2D, this.tex[i]);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
  }

  /** Draw shader `name` blending sources a -> b. u = {p, r, accent, accent2, seed, a, b} */
  draw(name, a, b, u) {
    const gl = this.gl;
    const P = this.program(name);
    gl.viewport(0, 0, this.W, this.H);
    gl.useProgram(P.prog);
    this.upload(0, a);
    this.upload(1, b);
    gl.uniform1i(P.u.uFrom, 0);
    gl.uniform1i(P.u.uTo, 1);
    gl.uniform1f(P.u.uP, u.p);
    gl.uniform1f(P.u.uR, u.r);
    gl.uniform2f(P.u.uRes, this.W, this.H);
    gl.uniform1f(P.u.uAspect, this.W / this.H);
    gl.uniform3fv(P.u.uAccent, u.accent);
    gl.uniform3fv(P.u.uAccent2, u.accent2);
    gl.uniform1f(P.u.uSeed, u.seed || 0);
    const d = PARAMS[name]?.defaults || {};
    gl.uniform1f(P.u.uA, u.a ?? d.a ?? 0);
    gl.uniform1f(P.u.uB, u.b ?? d.b ?? 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buf);
    gl.enableVertexAttribArray(P.aPos);
    gl.vertexAttribPointer(P.aPos, 2, gl.FLOAT, false, 0, 0);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    gl.finish();
  }

  show(on) { this.canvas.style.display = on ? '' : 'none'; }
}

/* ------------------------------------------------ in-page rasteriser */

const dataUrlCache = new Map();
function blobToDataURL(blob) {
  return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = () => rej(r.error); r.readAsDataURL(blob); });
}
async function fetchDataURL(url) {
  if (url.startsWith('data:')) return url;
  if (!dataUrlCache.has(url)) {
    dataUrlCache.set(url, fetch(url).then((r) => (r.ok ? r.blob() : null)).then((b) => (b ? blobToDataURL(b) : '')).catch(() => ''));
  }
  return dataUrlCache.get(url);
}

async function inlineUrls(text, base) {
  const re = /url\(\s*(['"]?)([^'")]+)\1\s*\)/g;
  const found = [...text.matchAll(re)];
  if (!found.length) return text;
  const map = new Map();
  await Promise.all(found.map(async (m) => {
    const raw = m[2];
    if (raw.startsWith('data:') || raw.startsWith('#') || map.has(raw)) return;
    let abs;
    try { abs = new URL(raw, base).href; } catch { return; }
    map.set(raw, await fetchDataURL(abs));
  }));
  return text.replace(re, (all, q, raw) => (map.get(raw) ? `url("${map.get(raw)}")` : all));
}

const norm = (s) => String(s || '').replace(/["'\s]/g, '').toLowerCase();
function parseRange(str) {
  const out = [];
  for (const part of String(str || 'U+0-10FFFF').split(',')) {
    const m = part.trim().match(/^U\+([0-9A-F?]+)(?:-([0-9A-F]+))?$/i);
    if (!m) continue;
    if (m[1].includes('?')) out.push([parseInt(m[1].replace(/\?/g, '0'), 16), parseInt(m[1].replace(/\?/g, 'F'), 16)]);
    else out.push([parseInt(m[1], 16), parseInt(m[2] || m[1], 16)]);
  }
  return out;
}

// Page CSS as a list of rules; @font-face rules are kept apart so each snapshot embeds only
// the faces its own text needs (the stage preloads every declared face, so "loaded" is no filter).
async function sheetRules(sheet, base, out) {
  let rules;
  try { rules = sheet.cssRules; } catch { out.incomplete = true; return; }
  for (const r of rules) {
    if (r.type === CSSRule.IMPORT_RULE) {
      if (r.styleSheet) await sheetRules(r.styleSheet, r.styleSheet.href || base, out); else out.incomplete = true;
      continue;
    }
    if (r.type === CSSRule.FONT_FACE_RULE) {
      out.fonts.push({ css: r.cssText, base, family: norm(r.style.getPropertyValue('font-family')), ranges: parseRange(r.style.getPropertyValue('unicode-range')), inlined: null });
      continue;
    }
    out.text.push(r.cssText.includes('url(') ? await inlineUrls(r.cssText, base) : r.cssText);
  }
}

let cssCache = null;
async function pageCSS() {
  if (cssCache) return cssCache;
  const out = { text: [], fonts: [], incomplete: false };
  for (const sheet of document.styleSheets) await sheetRules(sheet, sheet.href || location.href, out);
  const res = { text: out.text.join('\n').replace(/\]\]>/g, ']] >'), fonts: out.fonts };
  // only cache a complete picture (a stylesheet still loading is picked up next frame)
  if (!out.incomplete && document.readyState === 'complete') cssCache = res;
  return res;
}

/** @font-face rules needed by the text inside `el` (families in use x code points present). */
async function fontCSS(el, fonts) {
  const fams = new Set();
  const nodes = [el, ...el.querySelectorAll('*')];
  for (const n of nodes.slice(0, 2000)) {
    const ff = getComputedStyle(n).fontFamily;
    for (const f of ff.split(',')) fams.add(norm(f));
  }
  const cps = new Set();
  for (const ch of el.textContent || '') cps.add(ch.codePointAt(0));
  cps.add(32);
  const hit = (ranges) => { for (const cp of cps) for (const [a, b] of ranges) if (cp >= a && cp <= b) return true; return false; };
  const need = fonts.filter((f) => fams.has(f.family) && hit(f.ranges));
  await Promise.all(need.map(async (f) => { if (f.inlined == null) f.inlined = await inlineUrls(f.css, f.base); }));
  return need.map((f) => f.inlined).join('\n');
}

const imgCache = new Map();
async function imageDataURL(img) {
  const src = img.currentSrc || img.src;
  if (!src || !img.naturalWidth) return src || '';
  const w = Math.max(1, Math.round(Math.min(img.naturalWidth, (img.offsetWidth || img.naturalWidth) * 1.5)));
  const h = Math.max(1, Math.round((img.naturalHeight / img.naturalWidth) * w));
  const key = `${src}|${w}x${h}`;
  if (!imgCache.has(key)) {
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    c.getContext('2d').drawImage(img, 0, 0, w, h);
    let url;
    try { url = c.toDataURL('image/webp', 0.94); } catch { url = await fetchDataURL(src); }
    imgCache.set(key, url);
  }
  return imgCache.get(key);
}

function frameDataURL(source, w, h) {
  const c = document.createElement('canvas');
  c.width = Math.max(1, w); c.height = Math.max(1, h);
  try { c.getContext('2d').drawImage(source, 0, 0, c.width, c.height); return c.toDataURL('image/webp', 0.94); } catch { return ''; }
}

function copyBox(from, to) {
  for (const a of from.attributes) if (a.name !== 'src' && a.name !== 'srcset' && a.name !== 'width' && a.name !== 'height') to.setAttribute(a.name, a.value);
  if (!to.style.width) to.style.width = from.offsetWidth ? from.offsetWidth + 'px' : '';
  if (!to.style.height) to.style.height = from.offsetHeight ? from.offsetHeight + 'px' : '';
  if (getComputedStyle(from).display === 'inline') to.style.display = 'inline-block';
}

async function fixClone(orig, clone) {
  const O = [orig, ...orig.querySelectorAll('*')];
  const C = [clone, ...clone.querySelectorAll('*')];
  if (O.length !== C.length) return;
  // freeze CSS animations at their current value
  const anims = document.getAnimations ? document.getAnimations() : [];
  const animated = new Map();
  for (const a of anims) {
    const t = a.effect && a.effect.target;
    if (!t || !(t === orig || orig.contains(t))) continue;
    const props = new Set();
    try { for (const k of a.effect.getKeyframes()) for (const p of Object.keys(k)) if (!['offset', 'easing', 'composite', 'computedOffset'].includes(p)) props.add(p); } catch { /* ignore */ }
    animated.set(t, new Set([...(animated.get(t) || []), ...props]));
  }
  const jobs = [];
  for (let i = 0; i < O.length; i++) {
    const o = O[i], c = C[i];
    const tag = o.tagName;
    if (animated.has(o)) {
      const cs = getComputedStyle(o);
      for (const p of animated.get(o)) { const kebab = p.replace(/[A-Z]/g, (m) => '-' + m.toLowerCase()); c.style.setProperty(kebab, cs.getPropertyValue(kebab)); }
      c.style.setProperty('animation', 'none');
      c.style.setProperty('transition', 'none');
    }
    if (tag === 'SCRIPT') { c.remove(); continue; }
    // a render draws videos on a canvas of their own (stage.js, the canvas route): the clone shows the
    // video in its own place instead, as an image like any other video
    if (o.__stVideo) { c.remove(); continue; }
    if (tag === 'IMG') jobs.push(imageDataURL(o).then((u) => { c.setAttribute('src', u); c.removeAttribute('srcset'); c.removeAttribute('loading'); }));
    else if (tag === 'CANVAS' && !o.hasAttribute('data-st-gl')) {
      const img = document.createElement('img');
      img.setAttribute('src', frameDataURL(o, o.width, o.height));
      copyBox(o, img);
      c.replaceWith(img);
    } else if (tag === 'VIDEO') {
      const img = document.createElement('img');
      img.setAttribute('src', o.readyState >= 2 ? frameDataURL(o, o.videoWidth, o.videoHeight) : '');
      copyBox(o, img);
      img.removeAttribute('data-st-hidden');
      img.removeAttribute('data-st-canvas');
      img.style.objectFit = getComputedStyle(o).objectFit;
      c.replaceWith(img);
    } else if (tag === 'IFRAME') {
      c.replaceWith(document.createElement('div'));
    }
  }
  await Promise.all(jobs);
}

let taintFree = null; // whether blob: SVG images keep WebGL uploads legal
/**
 * Rasterise one scene (with its ancestors, without its siblings) at the frame size.
 * Returns an HTMLImageElement ready for texImage2D.
 */
export async function snapshot(scene, W, H) {
  const page = await pageCSS();
  const css = page.text + '\n' + (await fontCSS(scene, page.fonts));
  const chain = [];
  for (let e = scene; e && e !== document.documentElement; e = e.parentElement) chain.unshift(e);
  let root = null, parent = null;
  for (const el of chain) {
    const c = el === scene ? el.cloneNode(true) : el.cloneNode(false);
    if (parent) parent.appendChild(c); else root = c;
    parent = c;
  }
  await fixClone(scene, parent);
  const de = document.documentElement;
  const attrs = Array.from(de.attributes).filter((a) => a.name !== 'xmlns').map((a) => ` ${a.name}="${a.value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')}"`).join('');
  const body = new XMLSerializer().serializeToString(root);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"${attrs}>` +
    `<style><![CDATA[${css}]]></style><foreignObject x="0" y="0" width="${W}" height="${H}">` +
    `<html xmlns="http://www.w3.org/1999/xhtml"${attrs}>${body}</html></foreignObject></svg>`;
  const img = new Image();
  img.decoding = 'sync';
  let url = null;
  if (taintFree !== false) { url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' })); img.src = url; }
  else img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  try { await img.decode(); } catch (e) { if (url) URL.revokeObjectURL(url); throw new Error('[showtime] could not rasterise scene for the shader transition: ' + e.message); }
  if (url) img.addEventListener('load', () => URL.revokeObjectURL(url), { once: true });
  img.__blob = url;
  return img;
}

/** Upload with a taint check: switch to data: URLs if blob: SVG images are refused. */
export async function uploadSafe(comp, i, img, rerender) {
  try { comp.upload(i, img); if (img.__blob) taintFree = true; return img; } catch (e) {
    if (img.__blob) { taintFree = false; const again = await rerender(); comp.upload(i, again); return again; }
    throw e;
  }
}

/* -------------------------------------------------- layer protocol */

export function colorsFor(el) {
  const cs = getComputedStyle(el);
  return { accent: parseColor(cs.getPropertyValue('--accent').trim() || '#ff9933'), accent2: parseColor(cs.getPropertyValue('--accent-2').trim() || cs.getPropertyValue('--accent').trim() || '#33aaff') };
}

/** Hide everything except the path to `scene` (for solo layer screenshots). Returns undo(). */
export function solo(scene) {
  const saved = [];
  for (let e = scene; e && e.parentElement; e = e.parentElement) {
    for (const sib of e.parentElement.children) {
      if (sib === e || sib.tagName === 'SCRIPT' || sib.tagName === 'STYLE' || sib.tagName === 'LINK') continue;
      if (sib.__stVideo === e) continue;   // the canvas a render draws this video on (stage.js)
      saved.push([sib, sib.style.visibility]);
      sib.style.visibility = 'hidden';
    }
  }
  return () => { for (const [el, v] of saved) el.style.visibility = v; };
}

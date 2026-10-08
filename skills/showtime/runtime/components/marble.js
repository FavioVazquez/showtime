// marble: veined stone or marbled ink that flows slowly, tinted by the theme. Smooth gradient noise (a small
// tileable texture made once in JS, so a CPU renderer pays one lookup per octave) bends the plane twice over
// (domain warping), and the bent plane is drawn as stone (cloudy tone, a network of veins where a noise
// crosses its middle, finer hairlines and a soft halo around the veins) or as marbled paper (bands of the
// theme's colours combed into each other, with a fine line between them). A WebGL look (runtime/effects/gl.js);
// without WebGL the same field is worked out once in JS at a quarter of the size and drawn still, so the
// fallback is the look's own first frame, only softer.
//
//   <div data-st="marble"></div>                                          (fills its scene; text on top)
//   <div data-st="marble" data-preset="ink" data-speed="1.5"></div>
//
// Presets: auto (default: carrara on a light ground, nero on a dark one), carrara (white stone, grey veins
// with a trace of --accent-2), nero (dark stone, light veins with a trace of --accent), ink (marbled paper:
// bands of --bg, --accent, a light paper tone and --accent-2). Options override the preset: zoom (the
// pattern's scale, larger is finer), angle (the main direction of the bands, degrees), turbulence (how much
// the plane is bent, 0-2), veins (how strong the veins or band lines are, 0-1.5), speed (1 = a slow flow; 0 a
// still stone), sheen (a soft polished highlight, 0-1), colors (a comma list: stone, vein, second vein; ink:
// up to four band colours), keys [{at, dur, ease, zoom, turbulence, veins, sheen}], scale (render scale,
// default 0.75), seed.
import { define, clamp, hash, TAU } from './core.js';
import { lookLayer, palette, keyed, register, onScreen, rgb, mixRgb, lum } from '../effects/gl.js';

const PRESETS = {
  carrara: { zoom: 1, angle: 28, turbulence: 1, veins: 1, speed: 1, sheen: 0.3, kind: 0, cloud: 0.7 },
  nero: { zoom: 1, angle: -22, turbulence: 1.1, veins: 1, speed: 1, sheen: 0.4, kind: 0, cloud: 0.18 },
  ink: { zoom: 1, angle: 12, turbulence: 0.8, veins: 1, speed: 1.5, sheen: 0, kind: 1, cloud: 0 },
};
const N = 256, CELLS = 16;              // the noise texture: 256 px, 16 noise cells across, tiles both ways
const OCT = 3;                          // octaves of the warps

/**
 * Three independent channels of tileable gradient noise (quintic fade) in a 256 x 256 RGBA canvas, from the
 * seed: pure arithmetic, so every render worker builds the same bytes.
 */
function noiseCanvas(seed) {
  const S = N / CELLS;
  const img = new ImageData(N, N);
  const fade = (t) => t * t * t * (t * (t * 6 - 15) + 10);
  for (let ch = 0; ch < 3; ch++) {
    const gx = new Float32Array(CELLS * CELLS), gy = new Float32Array(CELLS * CELLS);
    for (let k = 0; k < CELLS * CELLS; k++) { const a = hash(k, seed * 31 + ch * 7 + 1) * TAU; gx[k] = Math.cos(a); gy[k] = Math.sin(a); }
    const dot = (i, j, dx, dy) => { const k = (j % CELLS) * CELLS + (i % CELLS); return gx[k] * dx + gy[k] * dy; };
    for (let y = 0; y < N; y++) {
      const fy = y / S, j = Math.floor(fy), v = fy - j, qv = fade(v);
      for (let x = 0; x < N; x++) {
        const fx = x / S, i = Math.floor(fx), u = fx - i, qu = fade(u);
        const a = dot(i, j, u, v), b = dot(i + 1, j, u - 1, v), c = dot(i, j + 1, u, v - 1), d = dot(i + 1, j + 1, u - 1, v - 1);
        const top = a + (b - a) * qu, bot = c + (d - c) * qu;
        img.data[(y * N + x) * 4 + ch] = Math.round(clamp(0.5 + (top + (bot - top) * qv) * 0.72) * 255);
      }
    }
  }
  for (let k = 3; k < img.data.length; k += 4) img.data[k] = 255;
  const c = document.createElement('canvas');
  c.width = c.height = N;
  c.getContext('2d', { willReadFrequently: true }).putImageData(img, 0, 0);
  c.bytes = img.data;
  return c;
}

// Stone (KIND 0) or ink (KIND 1) are compiled apart. The warps flow with time (offsets worked out in JS).
const FRAG = `
uniform sampler2D uNoise;
uniform float uAspect;
uniform float uZoom;
uniform vec2 uDir;
uniform float uTurb;
uniform float uVeins;
uniform float uSheen;
uniform vec2 uFlow0;
uniform vec2 uFlow1;
uniform float uLine;
uniform vec3 uStone;
uniform vec3 uStone2;
uniform vec3 uVein;
uniform vec3 uVein2;
uniform vec3 uInk3;
uniform float uCloud;
// three octaves of the three noise channels at once (the texture tiles every 16 cells; it has no mipmaps: a
// coarse level, where the warp stretches the plane, would show its texels as kinks, and a CPU renderer reads a
// plain bilinear texel cheaper)
vec3 fbm(vec2 p) {
  vec3 s = vec3(0.0);
  float a = 0.5;
  for (int i = 0; i < ${OCT}; i++) {
    s += a * texture2D(uNoise, p * ${(1 / CELLS).toFixed(4)}).rgb;
    p = mat2(1.6, 1.2, -1.2, 1.6) * p + vec2(5.3, 1.9);
    a *= 0.5;
  }
  return s * ${(1 / (1 - 0.5 ** OCT)).toFixed(5)};
}
void main() {
  vec2 p = vec2((vUv.x - 0.5) * uAspect, vUv.y - 0.5) * uZoom * 3.2 + uSeed * vec2(3.7, 1.3);
  // the plane bent twice over: the second warp reads the first one's result
  vec3 w1 = fbm(p * 0.55 + uFlow0);
  vec2 q = p + uTurb * 2.2 * (w1.xy - 0.5);
  vec3 w2 = fbm(q * 0.9 + uFlow1);
  vec2 r = q + uTurb * 1.3 * (w2.xy - 0.5);
#if KIND == 0
  // stone: a cloudy tone; veins where a noise on the bent plane crosses its middle, squeezed across the main
  // direction so they run long along it: a soft body with a darker core, some bold and some a thread (the width
  // follows a slow noise), a broad smoky cloud around them, and hairlines from a finer noise
  float tone = smoothstep(0.28, 0.72, w1.z * 0.55 + w2.z * 0.45);
  vec3 c = mix(uStone2, uStone, tone);
  vec2 across = vec2(-uDir.y, uDir.x);
  // a finer turbulence crinkles the veins; a second, finer family branches off the main one where w2 allows;
  // the veins come and go across the slab, leaving open stone between
  vec2 rv = r + 0.38 * (texture2D(uNoise, r * 0.21 + vec2(0.13, 0.57)).rg - 0.5);
  float n1 = texture2D(uNoise, (rv + dot(rv, across) * across * 0.9) * 0.026).r;
  float n1b = texture2D(uNoise, (rv + dot(rv, across) * across * 0.6) * 0.06 + vec2(0.51, 0.23)).b;
  float n2 = texture2D(uNoise, r * 0.11 + vec2(0.37, 0.71)).g;
  float mask = smoothstep(0.24, 0.62, w1.z * 0.7 + w2.x * 0.3);
  float dA = abs(n1 - 0.5), dB = abs(n1b - 0.5) * 0.5, d2 = abs(n2 - 0.5) * 0.3;
  float wide = uLine * (1.0 + 2.6 * smoothstep(0.4, 0.85, w1.z));
  float cloud = (1.0 - smoothstep(0.0, wide * 22.0, dA)) * mask;
  float body = (1.0 - smoothstep(wide * 0.6, wide * 2.6, dA)) * mask;
  float core = (1.0 - smoothstep(wide * 0.25, wide * 0.95, dA)) * mask;
  float branch = (1.0 - smoothstep(uLine * 0.5, uLine * 1.8, dB)) * smoothstep(0.35, 0.75, w2.z) * mask;
  float hair = (1.0 - smoothstep(uLine * 0.5, uLine * 1.5, d2)) * smoothstep(0.45, 0.8, w2.z);
  float k = clamp(uVeins, 0.0, 1.5), k1 = min(k, 1.0);
  c = mix(c, mix(c, uVein, 0.35), cloud * cloud * uCloud * k);
  c = mix(c, uVein2, hair * 0.3 * k);
  c = mix(c, mix(uVein, c, 0.45), branch * 0.6 * k1);
  c = mix(c, mix(uVein, c, 0.35), body * 0.75 * k1);
  c = mix(c, uVein, core * 0.7 * k1);
#else
  // marbled paper: fine stripes along the bent plane, each period a ground, a band of --accent, a thin line
  // and a band of --accent-2 (their widths breathing with the noise), every edge a pixel soft
  float f = dot(r, uDir) * 1.7 + w2.z * 2.6;
  float b = fract(f);
  float aa = uLine * 1.6;
  float t1 = 0.52 + 0.14 * (w1.z - 0.5), t2 = t1 + 0.17 + 0.08 * (w2.y - 0.5), t3 = t2 + 0.04, t4 = t3 + 0.14 + 0.08 * (w2.x - 0.5);
  vec3 c = mix(uStone, uStone2, smoothstep(0.35, 0.65, w1.z));
  c = mix(c, uVein, smoothstep(t1 - aa, t1 + aa, b) - smoothstep(t2 - aa, t2 + aa, b));
  c = mix(c, uInk3, (smoothstep(t2 - aa, t2 + aa, b) - smoothstep(t3 - aa, t3 + aa, b)) * clamp(uVeins, 0.0, 1.5));
  c = mix(c, uVein2, smoothstep(t3 - aa, t3 + aa, b) - smoothstep(t4 - aa, t4 + aa, b));
#endif
  // polish: a broad soft highlight from the upper left
  float sh = 1.0 - smoothstep(0.0, 1.1, length(vUv - vec2(0.25, 0.15)));
  c += uSheen * 0.08 * sh * sh;
  c += (hash(floor(gl_FragCoord.xy)) - 0.5) * 0.012;
  gl_FragColor = vec4(dither(clamp(c, 0.0, 1.0)), 1.0);
}`;

function colours(pal, kind, o) {
  let list = o.colors;
  if (typeof list === 'string') list = list.split(',').map((s) => s.trim()).filter(Boolean);
  const W = [1, 1, 1];
  const { bg, fg, accent: a1, accent2: a2 } = pal;
  let c;
  if (kind === 'ink') {
    // the ground is the page's own (with a paler cloud in it), the line between the bands the far tone
    c = { stone: bg, stone2: mixRgb(bg, pal.dark ? fg : W, 0.1), vein: a1, vein2: a2, ink3: pal.dark ? mixRgb(fg, bg, 0.2) : fg.map((v) => v * 0.8) };
  } else if (kind === 'nero') {
    const base = mixRgb(bg.map((v) => v * 0.4), [0.025, 0.025, 0.03], 0.5);
    c = { stone: mixRgb(base, fg, 0.05), stone2: base.map((v) => v * 0.6), vein: mixRgb(mixRgb(fg, W, 0.4), a1, 0.22), vein2: mixRgb(fg, a1, 0.35) };
  } else {
    const base = mixRgb(W, lum(bg) > 0.5 ? bg : mixRgb(W, a2, 0.06), 0.3);
    c = { stone: base, stone2: mixRgb(base, mixRgb([0.66, 0.67, 0.7], a2, 0.2), 0.62), vein: mixRgb([0.3, 0.32, 0.36], a2, 0.2), vein2: mixRgb([0.52, 0.5, 0.48], a1, 0.18) };
  }
  if (Array.isArray(list) && list.length) {
    const L = list.map((s) => rgb(s));
    if (kind === 'ink') Object.assign(c, { stone: L[0], vein: L[1] || L[0], stone2: L[2] || L[0], vein2: L[3] || L[1] || L[0] });
    else Object.assign(c, { stone: L[0], vein: L[1] || c.vein, vein2: L[2] || L[1] || c.vein2, stone2: mixRgb(L[0], L[1] || c.vein, 0.15) });
  }
  if (!c.ink3) c.ink3 = c.vein;
  return c;
}

/** The warps' flow at time tt: each one drifts on its own slow course (in noise cells). */
const flows = (tt, speed) => {
  const s = tt * speed;
  return [[s * 0.045, s * 0.028], [-s * 0.032, s * 0.05]];
};

/** Without WebGL: the shader's field worked out once in JS at w x h px and drawn still (the browser scales it up). */
function fallback(el, U, noise, w, h, kind) {
  el.classList.add('st-look-fallback');
  const c = document.createElement('canvas');
  c.className = 'st-look-canvas';
  c.width = w; c.height = h;
  const g = c.getContext('2d', { willReadFrequently: true });
  const img = g.createImageData(w, h);
  const B = noise.bytes;
  // the texture as the GPU reads it: bilinear, repeating
  const tex = (s, t, ch) => {
    const x = s * N - 0.5, y = t * N - 0.5, i = Math.floor(x), j = Math.floor(y), fx = x - i, fy = y - j;
    const at = (a, b) => B[((((b % N) + N) % N) * N + (((a % N) + N) % N)) * 4 + ch] / 255;
    const top = at(i, j) + (at(i + 1, j) - at(i, j)) * fx, bot = at(i, j + 1) + (at(i + 1, j + 1) - at(i, j + 1)) * fx;
    return top + (bot - top) * fy;
  };
  const fbm = (x, y) => {
    const s = [0, 0, 0];
    let a = 0.5;
    for (let o = 0; o < OCT; o++) {
      for (let ch = 0; ch < 3; ch++) s[ch] += a * tex(x / CELLS, y / CELLS, ch);
      [x, y] = [1.6 * x - 1.2 * y + 5.3, 1.2 * x + 1.6 * y + 1.9];
      a *= 0.5;
    }
    return s.map((v) => v / (1 - 0.5 ** OCT));
  };
  const sm = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
  const mix3 = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
  const [f0, f1] = U.flow;
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const px = ((x + 0.5) / w - 0.5) * U.aspect * U.zoom * 3.2 + U.seed * 3.7, py = ((y + 0.5) / h - 0.5) * U.zoom * 3.2 + U.seed * 1.3;
      const w1 = fbm(px * 0.55 + f0[0], py * 0.55 + f0[1]);
      const qx = px + U.turb * 2.2 * (w1[0] - 0.5), qy = py + U.turb * 2.2 * (w1[1] - 0.5);
      const w2 = fbm(qx * 0.9 + f1[0], qy * 0.9 + f1[1]);
      const rx = qx + U.turb * 1.3 * (w2[0] - 0.5), ry = qy + U.turb * 1.3 * (w2[1] - 0.5);
      let col;
      if (kind === 1) {
        const f = (rx * U.dir[0] + ry * U.dir[1]) * 1.7 + w2[2] * 2.6, b = f - Math.floor(f), aa = U.line * 1.6;
        const t1 = 0.52 + 0.14 * (w1[2] - 0.5), t2 = t1 + 0.17 + 0.08 * (w2[1] - 0.5), t3 = t2 + 0.04, t4 = t3 + 0.14 + 0.08 * (w2[0] - 0.5);
        const band = (lo, hi) => sm(lo - aa, lo + aa, b) - sm(hi - aa, hi + aa, b);
        col = mix3(U.stone, U.stone2, sm(0.35, 0.65, w1[2]));
        col = mix3(col, U.vein, band(t1, t2));
        col = mix3(col, U.ink3, band(t2, t3) * Math.min(1.5, U.veins));
        col = mix3(col, U.vein2, band(t3, t4));
      } else {
        col = mix3(U.stone2, U.stone, sm(0.28, 0.72, w1[2] * 0.55 + w2[2] * 0.45));
        const vx = rx + 0.38 * (tex(rx * 0.21 + 0.13, ry * 0.21 + 0.57, 0) - 0.5), vy = ry + 0.38 * (tex(rx * 0.21 + 0.13, ry * 0.21 + 0.57, 1) - 0.5);
        const ax = -U.dir[1], ay = U.dir[0], dd = (vx * ax + vy * ay) * 0.9;
        const dA = Math.abs(tex((vx + dd * ax) * 0.026, (vy + dd * ay) * 0.026, 0) - 0.5);
        const mask = sm(0.24, 0.62, w1[2] * 0.7 + w2[0] * 0.3);
        const wide = U.line * (1 + 2.6 * sm(0.4, 0.85, w1[2])), k1 = Math.min(1, U.veins), cloud = (1 - sm(0, wide * 22, dA)) * mask;
        col = mix3(col, mix3(col, U.vein, 0.35), cloud * cloud * U.cloud * U.veins);
        col = mix3(col, mix3(U.vein, col, 0.35), (1 - sm(wide * 0.6, wide * 2.6, dA)) * mask * 0.75 * k1);
        col = mix3(col, U.vein, (1 - sm(wide * 0.25, wide * 0.95, dA)) * mask * 0.7 * k1);
      }
      const i = (y * w + x) * 4;
      img.data[i] = col[0] * 255; img.data[i + 1] = col[1] * 255; img.data[i + 2] = col[2] * 255; img.data[i + 3] = 255;
    }
  }
  g.putImageData(img, 0, 0);
  el.prepend(c);
}

export const Marble = define({
  name: 'marble',
  defaults: { at: 0, preset: 'auto', zoom: null, angle: null, turbulence: null, veins: null, speed: null, sheen: null, colors: null, keys: null, scale: 0.75, seed: 5 },
  async setup(el, o) {
    const pal = palette(el);
    const kind = o.preset in PRESETS ? o.preset : (pal.dark ? 'nero' : 'carrara');
    const P = { ...PRESETS[kind] };
    for (const k of ['zoom', 'angle', 'turbulence', 'veins', 'speed', 'sheen']) if (o[k] != null && o[k] !== '' && Number.isFinite(Number(o[k]))) P[k] = Number(o[k]);
    const C = colours(pal, kind, o);
    const seed = Number(o.seed) || 0;
    const scale = clamp(Number(o.scale) || 0.75, 0.25, 2);
    const noise = noiseCanvas(seed);
    const a = (P.angle * Math.PI) / 180;
    const dir = [Math.cos(a), Math.sin(a)];
    const still = () => {
      const box = [el.clientWidth || 640, el.clientHeight || 360];
      const w = Math.min(480, Math.max(16, Math.round(box[0] / 4))), h = Math.max(9, Math.round((w * box[1]) / box[0]));
      fallback(el, { ...C, aspect: box[0] / box[1], zoom: P.zoom, turb: P.turbulence, veins: P.veins, cloud: P.cloud, dir, seed, flow: flows(0, P.speed), line: (1.8 * P.zoom) / h }, noise, w, h, P.kind);
      return box;
    };
    const layer = lookLayer(el, { name: 'marble', scale, fallback: still });
    if (!layer) {
      const box = still();
      register(el, { look: 'marble', gl: false, preset: kind, box, note: 'no WebGL: drew the first frame still, from JS at a quarter size' });
      return { duration: 0, update() {} };
    }
    const prog = layer.program(FRAG, { KIND: P.kind });
    const tex = layer.texture(noise, { wrap: 'repeat' });
    register(el, { look: 'marble', gl: true, preset: kind, box: layer.box, passes: [{ kind: 'marble', w: layer.W, h: layer.H }] });
    const draw = (lt) => {
      const v = keyed(P, o.keys, lt);
      const tt = Math.max(0, lt);
      const [f0, f1] = flows(tt, P.speed);
      const zoom = Math.max(0.1, v.zoom);
      layer.draw(prog, {
        uNoise: tex, uSeed: seed, uAspect: layer.W / layer.H, uZoom: zoom, uDir: dir, uTurb: Math.max(0, v.turbulence),
        uVeins: clamp(v.veins, 0, 1.5), uSheen: clamp(v.sheen, 0, 1), uFlow0: f0, uFlow1: f1,
        // about a pixel at this size, in the units of the noise the veins are read from
        uLine: (1.8 * zoom) / layer.H,
        uStone: C.stone, uStone2: C.stone2, uVein: C.vein, uVein2: C.vein2, uInk3: C.ink3, uCloud: P.cloud,
      });
    };
    return { duration: 0, update(lt) { if (onScreen(el)) draw(lt); } };
  },
});

export default Marble;

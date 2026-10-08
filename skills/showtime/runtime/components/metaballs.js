// metaballs: gooey blobs in the theme's accent that merge and split: a playful beat (satellites that gather into
// a central blob and part again), a slow lava-lamp ground, or a gooey wipe for a transition. Each ball adds
// r^2 / (d^2 + 0.12 r^2) to a field (bounded, so balls deep inside a merged blob leave no bumps) and the blobs
// are drawn where the field passes 1, with an edge a pixel soft at any size. Shades of --accent blend in Oklab
// where blobs merge, and the field's slope shades them like soft candy (a dome, a key light, a crisp highlight,
// a rim lit in --accent-2). A WebGL look (runtime/effects/gl.js) on a transparent canvas over the scene's own
// ground; without WebGL the same blobs are traced on a 2D canvas on every frame (flat colour, crisp edge), so
// they still move.
//
//   <div data-st="metaballs"></div>                                        (fills its scene; text on top)
//   <div data-st="metaballs" data-preset="merge" data-x="0.68"><b class="n">3 in 1</b></div>
//   <div data-st="metaballs" data-preset="wipe" data-dur="1.2" data-from="left"></div>
//        (in a layer over a cut: the goo covers the whole frame in the middle of its run, at least from
//        at + 0.46 * dur to at + 0.54 * dur, so the cut goes at at + dur / 2)
//
// Presets: merge (default), lava (blobs rising and sinking across the frame, for a playful ground), wipe (a
// gooey band crosses the frame, covers all of it halfway through and leaves the other side). Options override
// the preset: count (3-12), size (the main blob's radius, fraction of the frame height), x, y (centre,
// fractions of the box), spread (how far the satellites travel; 0 keeps them merged), speed, gloss (0 flat - 1
// candy), glow (a halo on a dark ground, a soft shadow on a light one, 0-1), colors (a comma list or JSON array
// of CSS colours, in turn; the wipe's cover is the first), from (wipe: left | right | top | bottom), dur (wipe: seconds), in (seconds for the blobs to
// grow in from `at`), keys [{at, dur, ease, x, y, size, spread, gloss, glow}], scale (render scale, default
// 0.75), seed.
import { define, clamp, ease, hash, TAU } from './core.js';
import { lookLayer, palette, keyed, register, onScreen, rgb, oklab, OKLAB_GLSL, mixRgb, cssRgb } from '../effects/gl.js';

const PRESETS = {
  merge: { count: 7, size: 0.15, spread: 1, speed: 1, gloss: 0.85, glow: 0.5, x: 0.5, y: 0.5 },
  lava: { count: 8, size: 0.1, spread: 1, speed: 1, gloss: 0.7, glow: 0.4, x: 0.5, y: 0.5 },
  wipe: { count: 10, size: 0.075, spread: 1, speed: 1, gloss: 0.35, glow: 0, x: 0.5, y: 0.5 },
};
const FROM = { left: [1, 0], right: [-1, 0], top: [0, 1], bottom: [0, -1] };
const HOLD = 0.08;
const toLin = (c) => c.map((v) => Math.pow(Math.max(0, v), 2.2));                          // the wipe covers the whole frame for this share of its time

// Balls are separate uniforms (uB0 = x, y, radius in frame heights; uC0 = Oklab colour), the sum unrolled;
// WIPE adds the band, SHADOW (light grounds) a soft offset shadow instead of the halo.
const frag = (n) => `
${Array.from({ length: n }, (_, i) => `uniform vec3 uB${i};\nuniform vec3 uC${i};`).join('\n')}
uniform float uAspect;
uniform float uGloss;
uniform float uGlow;
uniform float uDome;
uniform vec2 uShadowOff;
uniform vec4 uBand;
uniform float uBandR;
uniform vec3 uBandC;
uniform vec3 uRimC;
${OKLAB_GLSL}
void main() {
  vec2 p = vec2((vUv.x - 0.5) * uAspect, vUv.y - 0.5);
  float f = 0.0, fs = 0.0, wsum = 1e-9;
  vec2 g = vec2(0.0);
  vec3 lab = vec3(0.0);
  vec2 d;
  float q, k;
${Array.from({ length: n }, (_, i) => `  d = p - uB${i}.xy; q = dot(d, d) + 0.12 * uB${i}.z * uB${i}.z + 1e-6; k = uB${i}.z * uB${i}.z / q; f += k; g -= 2.0 * k / q * d; q = k * sqrt(k) * uB${i}.z * uB${i}.z; lab += uC${i} * q; wsum += q;
#ifdef SHADOW
  d -= uShadowOff; fs += uB${i}.z * uB${i}.z / (dot(d, d) + 0.12 * uB${i}.z * uB${i}.z + 1e-6);
#endif`).join('\n')}
#ifdef WIPE
  // the band: full inside [T, L] along the wipe's direction, falling off past its edges like a ball's field
  float s = dot(p, uBand.xy);
  float x = max(max(uBand.z - s, s - uBand.w), 0.0);
  float rb = uBandR * uBandR;
  float den = x * x + rb;
  float kb = 1.5 * rb / den;
  f += kb;
  g += -3.0 * rb * x / (den * den) * uBand.xy * (step(uBand.w, s) - step(s, uBand.z));
  lab += uBandC * kb * sqrt(kb); wsum += kb * sqrt(kb);
#ifdef SHADOW
  float ss = s - dot(uShadowOff, uBand.xy);
  float xs = max(max(uBand.z - ss, ss - uBand.w), 0.0);
  fs += 1.5 * rb / (xs * xs + rb);
#endif
#endif
  // the edge: the field's distance to 1 over its slope is the distance to the outline (in frame heights)
  float slope = max(length(g), 1e-4);
  float cov = clamp((f - 1.0) / slope * uRes.y + 0.5, 0.0, 1.0);
  vec3 base = max(fromOklab(lab / wsum), 0.0);
  // a dome over the outline (a hemisphere over one ball), lit from the upper left
  // h = sqrt(1 - 1 / f^2): steep at the outline, nearly flat where the field is high, so blobs that have
  // merged read as one body instead of a bump per ball
  float fi = 1.0 / max(f, 1.0);
  float h = sqrt(clamp(1.0 - fi * fi, 0.0, 1.0));
  vec3 n = normalize(vec3(-g * fi * fi * fi / max(h, 0.04) * uDome, 1.0));
  vec3 L = normalize(vec3(-0.45, -0.62, 0.64));
  float dif = clamp(dot(n, L), 0.0, 1.0);
  float hv = clamp(dot(n, normalize(L + vec3(0.0, 0.0, 1.0))), 0.0, 1.0);
  float rim = 1.0 - n.z;
  float back = clamp(dot(normalize(n.xy + 1e-5), vec2(0.55, 0.83)), 0.0, 1.0) * rim * rim;
  vec3 lit = base * (0.6 + 0.48 * dif) * (1.0 - 0.25 * rim * rim);
  lit += mix(base, uRimC, 0.6) * 0.5 * back + uRimC * 0.2 * back * back;
  float hv2 = hv * hv, hv4 = hv2 * hv2, hv8 = hv4 * hv4, hv16 = hv8 * hv8;
  lit += vec3(1.0) * (smoothstep(0.978, 0.995, hv) * 0.6 + hv16 * hv16 * 0.14);
  vec3 col = toSrgb(mix(base, lit, uGloss));
#ifdef SHADOW
  float halo = uGlow * 0.24 * smoothstep(0.3, 1.0, fs) * (1.0 - cov);
  gl_FragColor = vec4(dither(clamp(col, 0.0, 1.0)) * cov, cov + halo);
#else
  float halo = uGlow * 0.26 * smoothstep(0.32, 1.0, f) * (1.0 - cov);
  vec3 hc = toSrgb(base);
  gl_FragColor = vec4(dither(clamp(col, 0.0, 1.0)) * cov + hc * halo, cov + halo);
#endif
}`;

/** The balls' colours: from data-colors, else shades of the two accents in turn (the first one leads). */
function colours(pal, o, n, preset) {
  let list = o.colors;
  if (typeof list === 'string') list = list.split(',').map((s) => s.trim()).filter(Boolean);
  if (Array.isArray(list) && list.length) return Array.from({ length: n + 1 }, (_, i) => rgb(list[i % list.length]));
  const { accent: a1 } = pal;
  const W = [1, 1, 1], K = [0, 0, 0];
  if (preset === 'wipe') return Array.from({ length: n + 1 }, () => a1);
  // one family, lighter and deeper shades of --accent (two accents mixed where blobs merge meet in grey);
  // --accent-2 lights the rims
  const ring = [a1, mixRgb(a1, W, 0.3), mixRgb(a1, K, 0.15), mixRgb(a1, W, 0.14), mixRgb(a1, K, 0.08)];
  return Array.from({ length: n + 1 }, (_, i) => ring[i % ring.length]);
}

/**
 * Ball positions and radii at local time lt for a preset: [[x, y, r], ...] in frame heights around the
 * frame's centre (x spans +-aspect/2), and for the wipe the band [dirX, dirY, T, L].
 */
function mover(preset, n, seed, aspect, o) {
  const H = (i, k) => hash(i, seed * 13 + k);
  if (preset === 'wipe') {
    const dir = FROM[o.from] || FROM.left;
    const along = dir[0] ? aspect / 2 : 0.5, across = dir[0] ? 1 : aspect;
    const nl = Math.ceil(n / 2);
    const E = ease('sine.inOut');
    const dur = Math.max(0.2, Number(o.dur) || 1.2);
    return (lt, v) => {
      const u = clamp(lt / dur), r0 = v.size;
      // far enough past the frame that the merged edge (band and balls together reach beyond either) is off it
      const half = along + 0.14 + 2.4 * r0;
      const m = 0.5 - HOLD / 2;
      const pa = clamp(u / m), pb = clamp((u - 0.5 - HOLD / 2) / m);
      const Lx = -half + 2 * half * E(pa), Tx = -half + 2 * half * E(pb);
      const out = [];
      for (let i = 0; i < n; i++) {
        const lead = i < nl, k = lead ? i : i - nl, cnt = lead ? nl : n - nl;
        const w = (k + 0.5) / cnt - 0.5 + (H(i, 1) - 0.5) * 0.6 / cnt;
        const reach = (0.05 + 0.13 * H(i, 2)) * v.spread;
        const s = lead ? Lx + reach * Math.sin(Math.PI * Math.min(1, pa * (1 + 0.4 * H(i, 3)))) : Tx - reach * Math.sin(Math.PI * Math.min(1, pb * (1 + 0.4 * H(i, 3))));
        const t = w * across;
        out.push([s * dir[0] - t * dir[1], s * dir[1] + t * dir[0], r0 * (0.75 + 0.55 * H(i, 4))]);
      }
      return { balls: out, band: [dir[0], dir[1], Tx, Lx] };
    };
  }
  if (preset === 'lava') {
    const P = Array.from({ length: n }, (_, i) => ({
      x: ((i + 0.5) / n - 0.5) * 0.86 + (H(i, 1) - 0.5) * 0.5 / n, nu: 0.2 + 0.22 * H(i, 2), ph: H(i, 3) * TAU,
      ph2: H(i, 4) * TAU, r: 0.62 + 0.76 * H(i, 5), amp: 0.3 + 0.12 * H(i, 6),
    }));
    return (lt, v) => {
      const t = lt * v.speed;
      const cx = (v.x - 0.5) * aspect, cy = v.y - 0.5;
      return { balls: P.map((b) => [cx + b.x * aspect + 0.05 * Math.sin(0.27 * t + b.ph2),
        cy + b.amp * v.spread * Math.sin(b.nu * t + b.ph), v.size * b.r * (1 + 0.06 * Math.sin(0.5 * t + b.ph2))]) };
    };
  }
  // merge: a central blob and satellites on slow orbits that come in, merge with it and part again
  // the satellites share most of one slow in-and-out cycle (they gather and part nearly together), each a
  // little early or late
  const S = Array.from({ length: n - 1 }, (_, i) => ({
    a0: (i / (n - 1)) * TAU + (H(i, 1) - 0.5) * 0.8, w: (0.18 + 0.2 * H(i, 2)) * (i % 2 ? -1 : 1),
    nu: 0.62 + 0.16 * H(i, 3), ph: 2.2 + (H(i, 4) - 0.5) * 1.6, r: 0.36 + 0.3 * H(i, 5),
  }));
  return (lt, v) => {
    const t = lt * v.speed;
    const cx = (v.x - 0.5) * aspect, cy = v.y - 0.5, R = v.size * (1 + 0.035 * Math.sin(t * 0.9));
    const balls = [[cx, cy, R]];
    for (const s of S) {
      const c = 0.5 - 0.5 * Math.cos(s.nu * t + s.ph), e = c * c * (3 - 2 * c);
      const D = R * v.spread * (0.95 + 2.15 * e * e * (3 - 2 * e));
      const a = s.a0 + s.w * t;
      balls.push([cx + D * Math.cos(a), cy + D * Math.sin(a) * 0.82, R * s.r]);
    }
    return { balls };
  };
}

/** The field minus 1 at (x, y) (frame heights from the centre): > 0 inside a blob. */
function field(x, y, st) {
  let f = 0;
  for (const [bx, by, r] of st.balls) { const dx = x - bx, dy = y - by; f += (r * r) / (dx * dx + dy * dy + 0.12 * r * r + 1e-6); }
  if (st.band) {
    const s = x * st.band[0] + y * st.band[1], d = Math.max(st.band[2] - s, s - st.band[3], 0), rb = st.bandR * st.bandR;
    f += (1.5 * rb) / (d * d + rb);
  }
  return f - 1;
}

/**
 * Without WebGL: the outline traced on a coarse grid (marching squares, edges placed by interpolation) and
 * filled as one path, so it stays crisp and has no seams, on a CPU canvas (the same in every render worker).
 */
function flatDrawer(el, cols, aspect) {
  el.classList.add('st-look-fallback');
  const [bw, bh] = [el.clientWidth || 640, el.clientHeight || 360];
  const dpr = window.devicePixelRatio || 1;
  const c = document.createElement('canvas');
  c.className = 'st-look-canvas';
  c.width = Math.max(2, Math.round(bw * dpr)); c.height = Math.max(2, Math.round(bh * dpr));
  c.setAttribute('aria-hidden', 'true');
  el.prepend(c);
  const g = c.getContext('2d', { willReadFrequently: true });
  const W = c.width, Hh = c.height;
  const cs = Math.max(3, Math.round(Hh / 140));
  const nx = Math.ceil(W / cs) + 1, ny = Math.ceil(Hh / cs) + 1;
  const v = new Float32Array(nx * ny);
  const grad = g.createLinearGradient(0, 0, W, Hh);
  grad.addColorStop(0, cssRgb(cols[0])); grad.addColorStop(1, cssRgb(cols[1] || cols[0]));
  return (st) => {
    g.clearRect(0, 0, W, Hh);
    for (let j = 0; j < ny; j++) {
      const y = (j * cs) / Hh - 0.5;
      for (let i = 0; i < nx; i++) v[j * nx + i] = field(((i * cs) / W - 0.5) * aspect, y, st);
    }
    const path = new Path2D();
    const P = [[0, 0], [1, 0], [1, 1], [0, 1]];
    for (let j = 0; j < ny - 1; j++) {
      let run = -1;
      for (let i = 0; i <= nx - 1; i++) {
        const a = i < nx - 1 ? [v[j * nx + i], v[j * nx + i + 1], v[(j + 1) * nx + i + 1], v[(j + 1) * nx + i]] : null;
        const full = a && a[0] > 0 && a[1] > 0 && a[2] > 0 && a[3] > 0;
        if (full) { if (run < 0) run = i; continue; }
        if (run >= 0) { path.rect(run * cs, j * cs, (i - run) * cs, cs); run = -1; }
        if (!a || !(a[0] > 0 || a[1] > 0 || a[2] > 0 || a[3] > 0)) continue;
        let first = true;
        for (let k = 0; k < 4; k++) {
          const k2 = (k + 1) % 4;
          if (a[k] > 0) { const px = (i + P[k][0]) * cs, py = (j + P[k][1]) * cs; if (first) path.moveTo(px, py); else path.lineTo(px, py); first = false; }
          if ((a[k] > 0) !== (a[k2] > 0)) {
            const t = a[k] / (a[k] - a[k2]);
            const px = (i + P[k][0] + (P[k2][0] - P[k][0]) * t) * cs, py = (j + P[k][1] + (P[k2][1] - P[k][1]) * t) * cs;
            if (first) path.moveTo(px, py); else path.lineTo(px, py);
            first = false;
          }
        }
        path.closePath();
      }
    }
    g.fillStyle = grad;
    g.fill(path);
  };
}

export const Metaballs = define({
  name: 'metaballs',
  defaults: { at: 0, preset: 'merge', count: null, size: null, x: null, y: null, spread: null, speed: null, gloss: null, glow: null, colors: null, from: 'left', dur: 1.2, in: 0, keys: null, scale: 0.75, seed: 6 },
  async setup(el, o) {
    const preset = o.preset in PRESETS ? o.preset : 'merge';
    const P = { ...PRESETS[preset] };
    for (const k of Object.keys(P)) if (o[k] != null && o[k] !== '' && Number.isFinite(Number(o[k]))) P[k] = Number(o[k]);
    const n = clamp(Math.round(P.count), 3, 12);
    const pal = palette(el);
    const seed = Number(o.seed) || 0;
    const cols = colours(pal, o, n, preset);
    const scale = clamp(Number(o.scale) || 0.75, 0.25, 2);
    const box = [el.clientWidth || 640, el.clientHeight || 360];
    const aspect = box[0] / Math.max(1, box[1]);
    const move = mover(preset, n, seed, aspect, o);
    const grow = Math.max(0, Number(o.in) || 0);
    const G = ease('back.out(1.5)');
    const bandR = 0.06;
    const state = (lt) => {
      const v = keyed(P, o.keys, lt);
      const k = grow > 0 ? Math.max(0, G(clamp(lt / grow))) : 1;
      const st = move(Math.max(0, lt), v);
      if (k < 1) st.balls = st.balls.map(([x, y, r]) => [x, y, r * k]);
      st.bandR = bandR;
      return { v, st };
    };
    let flat = null;
    const flatFrame = (lt) => { if (!flat) flat = flatDrawer(el, cols, aspect); flat(state(lt).st); };
    let failed = false;
    const layer = lookLayer(el, { name: 'metaballs', scale, alpha: true, fallback: () => { failed = true; } });
    if (!layer) {
      register(el, { look: 'metaballs', gl: false, preset, box, note: 'no WebGL: traced the blobs flat on a 2D canvas, and they still move' });
      return { duration: grow, update(lt) { if (onScreen(el)) flatFrame(lt); } };
    }
    const defs = {};
    if (preset === 'wipe') defs.WIPE = 1;
    if (!pal.dark) defs.SHADOW = 1;
    const prog = layer.program(frag(n), defs);
    register(el, { look: 'metaballs', gl: true, preset, box: layer.box, passes: [{ kind: 'metaballs', w: layer.W, h: layer.H }] });
    const lab = cols.map(oklab);
    const draw = (lt) => {
      const { v, st } = state(lt);
      const u = { uAspect: layer.W / layer.H, uSeed: seed, uGloss: clamp(v.gloss, 0, 1), uGlow: clamp(v.glow, 0, 1),
        uDome: v.size * 0.85, uRimC: toLin(mixRgb(pal.accent2, [1, 1, 1], 0.25)), uShadowOff: [0.012, 0.03], uBandR: bandR, uBandC: lab[n], uBand: st.band || [1, 0, -9, -9] };
      for (let i = 0; i < n; i++) { u['uB' + i] = st.balls[i]; u['uC' + i] = lab[i]; }
      layer.draw(prog, u);
    };
    return {
      duration: preset === 'wipe' ? Math.max(grow, Number(o.dur) || 1.2) : grow,
      update(lt) {
        if (!onScreen(el)) return;
        if (!failed) draw(lt);
        if (failed) flatFrame(lt);
      },
    };
  },
});

export default Metaballs;

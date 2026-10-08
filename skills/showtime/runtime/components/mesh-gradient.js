// mesh-gradient: a soft colour field that moves slowly, built from the theme palette: 4-6 colour points
// drift on long closed paths, the field between them is blended in Oklab (no muddy middles) and bent by a
// smooth warp, with a fine grain so the gradient never steps into bands after compression. The quiet
// background an explainer needs. A WebGL look (runtime/effects/gl.js); without WebGL a still CSS field.
//
//   <div data-st="mesh-gradient"></div>                                   (fills its scene; text on top)
//   <div data-st="mesh-gradient" data-preset="aurora" data-colors="#ff7f61,#6fd3c1,#1b3337"></div>
//
// Presets: calm (default: close to --bg, low contrast, for text over it), aurora (accent glows in the
// dark), vivid (the accents at full strength, for a title or a reel). Options override the preset:
// points (4-6), intensity (how far the colours depart from --bg, 0-1), warp (0-1.5), move (how far each
// point travels, fraction of the frame height), speed (1 = a loop of about half a minute), grain (0-0.08),
// colors (a comma list or JSON array of CSS colours, used in turn for the points), keys [{at, dur, ease,
// intensity, warp, move, grain}], scale (render scale, default 0.5: the field is smooth), seed.
import { define, clamp, hash } from './core.js';
import { lookLayer, palette, keyed, register, onScreen, rgb, oklab, OKLAB_GLSL, mixRgb, cssRgb, boxSize } from '../effects/gl.js';

const PRESETS = {
  calm: { points: 5, intensity: 0.42, warp: 0.6, move: 0.14, speed: 1, grain: 0.022 },
  aurora: { points: 5, intensity: 0.85, warp: 0.9, move: 0.18, speed: 1.3, grain: 0.03 },
  vivid: { points: 6, intensity: 1, warp: 0.75, move: 0.2, speed: 1.5, grain: 0.03 },
};
// where the points rest, in frame fractions (x, y), for each count: a loose ring, never a grid
const LAYOUT = {
  4: [[0.18, 0.22], [0.84, 0.3], [0.7, 0.86], [0.22, 0.74]],
  5: [[0.16, 0.2], [0.62, 0.14], [0.9, 0.6], [0.46, 0.88], [0.12, 0.68]],
  6: [[0.14, 0.2], [0.52, 0.1], [0.9, 0.3], [0.82, 0.84], [0.4, 0.9], [0.1, 0.62]],
};

const frag = (n) => `
${Array.from({ length: n }, (_, i) => `uniform vec2 uP${i};\nuniform vec3 uC${i};`).join('\n')}
uniform float uAspect;
uniform vec4 uWarpA;
uniform float uWarp;
uniform float uGrain;
uniform float uStep;
${OKLAB_GLSL}
void main() {
  vec2 p = vec2((vUv.x - 0.5) * uAspect, vUv.y - 0.5);
  // the warp: two octaves of slow sines bend the field, so the colour boundaries curl instead of meeting in
  // straight seams (phases are worked out in JS from time)
  vec2 w = vec2(sin(p.y * 2.3 + uWarpA.x), sin(p.x * 1.9 + uWarpA.y));
  w += 0.45 * vec2(sin((p.x + p.y) * 4.1 + uWarpA.z), sin((p.x - p.y) * 3.7 + uWarpA.w));
  p += uWarp * 0.11 * w;
  // inverse-square-distance weights (Shepard): each point owns a soft region, the regions blend smoothly
  vec3 acc = vec3(0.0);
  float sum = 0.0;
  vec2 d;
  float q;
${Array.from({ length: n }, (_, i) => `  d = p - uP${i}; q = dot(d, d) + 0.035; q = 1.0 / (q * q); acc += uC${i} * q; sum += q;`).join('\n')}
  vec3 col = toSrgb(fromOklab(acc / sum));
  // film grain: a new pattern 12 times a second, centred, so the mean colour stays put
  float g = hash(floor(gl_FragCoord.xy) + uStep * vec2(37.0, 17.0)) + hash(floor(gl_FragCoord.xy) * 1.31 + uStep * 7.0 + 3.0) - 1.0;
  col += g * uGrain * (0.35 + 0.65 * (1.0 - luma(col)));
  gl_FragColor = vec4(dither(clamp(col, 0.0, 1.0)), 1.0);
}`;

/**
 * On a dark ground, the accent nearest the ground's own hue (Oklab), or the cooler one on a grey ground: a
 * warm accent mixed down toward a dark cool ground turns brown, so it only ever comes in as a light glow.
 */
function nearAccent(pal) {
  const [, ga, gb] = oklab(pal.bg);
  const hue = (c) => { const [, x, y] = oklab(c); return [Math.atan2(y, x), Math.hypot(x, y), 0.5 * x + y]; };
  const [h1, , w1] = hue(pal.accent), [h2, , w2] = hue(pal.accent2);
  if (Math.hypot(ga, gb) < 0.02) return w1 <= w2 ? [pal.accent, pal.accent2] : [pal.accent2, pal.accent];
  const hg = Math.atan2(gb, ga), dist = (h) => Math.abs(Math.atan2(Math.sin(h - hg), Math.cos(h - hg)));
  return dist(h1) <= dist(h2) ? [pal.accent, pal.accent2] : [pal.accent2, pal.accent];
}

/** The point colours: from data-colors, else from the palette at the preset's strength. */
function colours(pal, o, n, preset) {
  let list = o.colors;
  if (typeof list === 'string') list = list.split(',').map((s) => s.trim()).filter(Boolean);
  if (Array.isArray(list) && list.length) return Array.from({ length: n }, (_, i) => rgb(list[i % list.length]));
  const { bg, accent: a1, accent2: a2, dark } = pal;
  const deep = bg.map((v) => v * (dark ? 0.55 : 0.9));
  // lighter and deeper shades of each accent, never the two accents mixed (complementary pairs meet in grey)
  const W = [1, 1, 1], K = [0, 0, 0];
  if (preset === 'vivid') return [a1, a2, mixRgb(a1, W, 0.3), mixRgb(a2, K, 0.35), mixRgb(a2, W, 0.3), mixRgb(a1, K, 0.3)].slice(0, n);
  if (dark) {
    const [near, far] = nearAccent(pal);
    if (preset === 'aurora') return [mixRgb(near, bg, 0.12), deep, mixRgb(far, W, 0.15), mixRgb(near, W, 0.25), deep, mixRgb(near, bg, 0.5)].slice(0, n);
    // calm: the ground lifted toward the nearer accent in a few soft steps, one deeper patch, the ground itself
    return [mixRgb(near, bg, 0.3), deep, mixRgb(bg, mixRgb(near, W, 0.3), 0.45), mixRgb(near, bg, 0.6), bg, deep.map((v) => v * 0.8)].slice(0, n);
  }
  if (preset === 'aurora') return [mixRgb(a2, bg, 0.15), deep, mixRgb(a1, bg, 0.25), mixRgb(a2, W, 0.2), deep, mixRgb(a1, bg, 0.5)].slice(0, n);
  // calm on a light ground: the ground tinted toward each accent, one deeper patch, one lifted toward white and
  // one of the ground itself (never grey: the type colour mixed into the ground reads as haze behind the words)
  return [mixRgb(a2, bg, 0.25), deep, mixRgb(a1, bg, 0.3), mixRgb(bg, W, 0.6), bg, mixRgb(a2, bg, 0.55)].slice(0, n);
}

/** Point positions at time tt (seconds): each on its own slow closed path around its rest point. */
function mover(n, seed, aspect) {
  const rest = LAYOUT[n];
  const P = rest.map(([x, y], i) => ({
    x: (x - 0.5) * aspect, y: y - 0.5,
    r: 0.6 + 0.4 * hash(i, seed * 7 + 1), ph: hash(i, seed * 7 + 2) * Math.PI * 2, ph2: hash(i, seed * 7 + 3) * Math.PI * 2,
    w: (Math.PI * 2) / (26 + 14 * hash(i, seed * 7 + 4)) * (i % 2 ? -1 : 1),
  }));
  return (tt, move, speed) => P.map((p) => {
    const a = p.w * tt * speed;
    return [p.x + move * p.r * aspect * 0.6 * Math.cos(a + p.ph), p.y + move * p.r * Math.sin(a * 0.83 + p.ph2)];
  });
}

function fallback(el, pal, cols, pos, aspect) {
  // the same points at the look's first frame as CSS radial gradients over the ground
  el.classList.add('st-look-fallback');
  const g = pos.map(([x, y], i) => `radial-gradient(${46}% ${58}% at ${((x / aspect + 0.5) * 100).toFixed(1)}% ${((y + 0.5) * 100).toFixed(1)}%, ${cssRgb(cols[i])} 0%, ${cssRgb(cols[i], 0)} 100%)`);
  el.style.background = [...g, cssRgb(pal.bg)].join(', ');
}

export const MeshGradient = define({
  name: 'mesh-gradient',
  defaults: { at: 0, preset: 'calm', points: null, intensity: null, warp: null, move: null, speed: null, grain: null, colors: null, keys: null, scale: 0.5, seed: 2 },
  async setup(el, o) {
    const preset = o.preset in PRESETS ? o.preset : 'calm';
    const P = { ...PRESETS[preset] };
    for (const k of Object.keys(P)) if (o[k] != null && o[k] !== '' && Number.isFinite(Number(o[k]))) P[k] = Number(o[k]);
    const n = clamp(Math.round(P.points), 4, 6);
    const pal = palette(el);
    const seed = Number(o.seed) || 0;
    const cols = colours(pal, o, n, preset);
    const scale = clamp(Number(o.scale) || 0.5, 0.25, 2);
    const box = boxSize(el);
    const aspect = box[0] / Math.max(1, box[1]);
    const at = mover(n, seed, aspect);
    // a colour's strength is how far it departs from the ground; mixed in Oklab
    const lab = cols.map(oklab), labBg = oklab(pal.bg);
    const strength = (k) => lab.map((c) => c.map((v, j) => labBg[j] + (v - labBg[j]) * k));
    const still = () => fallback(el, pal, cols.map((c) => mixRgb(pal.bg, c, clamp(P.intensity, 0, 1))), at(0, P.move, P.speed), aspect);
    const layer = lookLayer(el, { name: 'mesh-gradient', scale, fallback: still });
    if (!layer) {
      still();
      register(el, { look: 'mesh-gradient', gl: false, preset, box, note: 'no WebGL: drew a still CSS field' });
      return { duration: 0, update() {} };
    }
    const prog = layer.program(frag(n));
    register(el, { look: 'mesh-gradient', gl: true, preset, box: layer.box, passes: [{ kind: 'mesh', w: layer.W, h: layer.H }] });
    const draw = (lt) => {
      const v = keyed(P, o.keys, lt);
      const tt = Math.max(0, lt);
      const pts = at(tt, v.move, P.speed);
      const c = strength(clamp(v.intensity, 0, 1.2));
      const u = { uAspect: aspect, uSeed: seed, uWarp: v.warp, uGrain: clamp(v.grain, 0, 0.2), uStep: Math.floor(tt * 12) % 997 };
      const s = tt * 0.09 * P.speed + seed;
      u.uWarpA = [s * 1.3, s * 1.1 + 1.7, s * 0.7 + 2.9, s * 0.9 + 4.1];
      for (let i = 0; i < n; i++) { u['uP' + i] = pts[i]; u['uC' + i] = c[i]; }
      layer.draw(prog, u);
    };
    return { duration: 0, update(lt) { if (onScreen(el)) draw(lt); } };
  },
});

export default MeshGradient;

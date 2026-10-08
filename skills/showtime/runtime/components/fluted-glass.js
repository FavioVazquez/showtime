// fluted-glass: a pane of reeded glass over an image or the theme's own colours. Vertical (or angled)
// flutes each refract the picture behind them, with a chromatic split, a highlight down each flute and
// a fine seam between them. A WebGL look (runtime/effects/gl.js); without WebGL it draws a CSS pane.
//
//   <div data-st="fluted-glass" data-src="media/plate.jpg"></div>              (fills its scene)
//   <div data-st="fluted-glass" data-preset="prism"><h1>Over the glass</h1></div>   (palette glows behind)
//
// Presets: reeded (fine, quiet), fluted (default), prism (wide, angled, strong split). Options override
// the preset: width (flute width, px at the frame size), depth (refraction, 0-1.5), angle (degrees),
// split (chromatic, 0-0.6), frost (0-3: a softer picture inside the flutes), light (highlights, 0-1),
// flow (flutes slide, px/s), drift (the picture behind pushes in, zoom per second), focus [x%, y%],
// keys [{at, dur, ease, depth, width, angle, split, frost, light}], scale (render scale; default 1, or 0.75
// where WebGL runs on the CPU: the same pane at about two thirds of the cost).
import { define, clamp } from './core.js';
import { lookLayer, palette, keyed, findSource, sourceReady, sourceSize, coverFit, register, onScreen, softwareGL } from '../effects/gl.js';

const PRESETS = {
  reeded: { width: 26, depth: 0.42, angle: 0, split: 0.1, frost: 0.4, light: 0.55, flow: 0 },
  fluted: { width: 64, depth: 0.62, angle: 0, split: 0.16, frost: 0, light: 0.7, flow: 0 },
  prism: { width: 90, depth: 0.6, angle: 10, split: 0.18, frost: 0, light: 0.75, flow: 6 },
};

// Compiled twice: with SRC defined (a picture) or without (the palette glows). A branch on a uniform would
// cost both paths per pixel on a CPU renderer, and everything that depends only on time is worked out in JS.
const FRAG = `
uniform sampler2D uSrc;
uniform vec4 uFit;
uniform float uZoom;
uniform float uFlute;
uniform vec2 uDir;
uniform float uDepth;
uniform float uSplit;
uniform float uFrost;
uniform float uLight;
uniform float uShift;
uniform vec3 uBase0;
uniform vec3 uBase1;
uniform vec2 uG0;
uniform vec2 uG1;
uniform vec2 uG2;
uniform vec2 uG3;
uniform vec3 uC0;
uniform vec3 uC1;
uniform vec3 uC2;
uniform vec3 uC3;
uniform vec4 uK;

#ifdef SRC
vec3 plate(vec2 uv) {
  vec2 q = (uv - 0.5) / uZoom + 0.5;
  q = (q - 0.5) * uFit.xy + 0.5 + uFit.zw;
  return texture2D(uSrc, q, uFrost).rgb;
}
#else
// the palette ground used when there is no picture: compact glows with a firm core (the flutes need edges to
// bend; a smooth wash shows nothing) drifting on slow closed paths
vec3 glow(vec3 c, vec2 p, vec2 at, float r, vec3 col, float k) {
  vec2 d = p - at;
  float l2 = dot(d, d);
  float core = 1.0 - smoothstep(r * r * 0.04, r * r, l2);
  float halo = r * r / (r * r + 2.5 * l2);
  return mix(c, col, k * (0.72 * core + 0.28 * halo * halo));
}
vec3 plate(vec2 uv) {
  vec2 p = vec2((uv.x - 0.5) * uRes.x / uRes.y, uv.y - 0.5);
  vec3 c = mix(uBase0, uBase1, smoothstep(-0.5, 0.6, p.y));
  c = glow(c, p, uG0, 0.26, uC0, uK.x);
  c = glow(c, p, uG1, 0.3, uC1, uK.y);
  c = glow(c, p, uG2, 0.15, uC2, uK.z);
  c = glow(c, p, uG3, 0.11, uC3, uK.w);
  return c;
}
#endif

void main() {
  vec2 px = vUv * uRes;
  vec2 dir = uDir;
  float u = dot(px - 0.5 * uRes, dir) / uFlute + uShift;
  float f = fract(u);
  float s = f * 2.0 - 1.0;
  // a shallow cylinder: the slope (and so the shift) grows toward each flute's edges, so every flute shows
  // a squeezed copy of a wider strip of the picture
  float slope = s * (0.75 + 0.45 * s * s);
  vec2 off = dir * slope * uDepth * uFlute / uRes;
  vec3 col;
  col.r = plate(vUv + off * (1.0 + uSplit)).r;
  col.g = plate(vUv + off).g;
  col.b = plate(vUv + off * (1.0 - uSplit)).b;
  // light: a bright line where the flute faces the key light (upper left), a soft shade on the far side,
  // a fine dark seam with a lit lip where two flutes meet (the seam also hides the jump in the refraction)
  float nz = sqrt(max(0.0, 1.0 - s * s));
  float d1 = clamp(dot(vec2(s, nz), vec2(-0.47, 0.88)), 0.0, 1.0);
  float d2 = d1 * d1, d4 = d2 * d2, d8 = d4 * d4;
  float sheen = d4 * d2;
  float spec = d8 * d8 * d8 * d8 * d8;
  float shade = smoothstep(0.15, 1.0, s);
  float edge = min(f, 1.0 - f) * uFlute;
  float seam = 1.0 - smoothstep(0.35, 1.6, edge);
  float lip = (1.0 - smoothstep(1.2, 3.2, edge)) * step(0.5, f) * (1.0 - seam);
  float l = uLight;
  col *= 1.0 - l * (0.22 * shade);
  // highlights are screened, so a bright picture is lifted, never clipped to flat white
  float hl = l * (0.06 * sheen + 0.26 * spec + 0.1 * lip);
  col = 1.0 - (1.0 - col) * (1.0 - hl);
  col = mix(col, col * 0.42, seam * l);
  gl_FragColor = vec4(dither(clamp(col, 0.0, 1.0)), 1.0);
}`;

/** The palette glows behind the glass when there is no picture: colours once, positions per frame (seconds). */
function glows(pal, asp, seed) {
  const mixc = (a, b, t) => a.map((x, i) => x + (b[i] - x) * t);
  const dark = pal.dark;
  const warm = dark ? mixc(pal.fg, pal.accent, 0.45) : mixc(pal.bg, pal.accent, 0.55);
  const fixed = {
    uBase0: pal.bg, uBase1: pal.bg.map((x) => x * (dark ? 0.6 : 0.92)),
    uC0: pal.accent, uC1: pal.accent2, uC2: warm, uC3: mixc(pal.accent2, pal.fg, 0.3), uK: [0.95, 0.92, 0.85, dark ? 0.7 : 0.5],
  };
  return (tt) => {
    const t = tt * 0.12 + seed * 0.37;
    return { ...fixed,
      uG0: [-0.32 * asp + 0.12 * Math.sin(t * 1.3), -0.06 + 0.12 * Math.cos(t * 0.9)],
      uG1: [0.26 * asp + 0.12 * Math.cos(t * 1.1 + 1.7), 0.12 + 0.1 * Math.sin(t * 1.5 + 0.4)],
      uG2: [-0.02 * asp + 0.16 * Math.sin(t * 0.7 + 2.9), -0.2 + 0.1 * Math.cos(t * 0.8 + 1.1)],
      uG3: [0.36 * asp + 0.08 * Math.sin(t * 0.9 + 4.0), -0.28 + 0.06 * Math.cos(t * 1.2)] };
  };
}

function fallback(el, o, pal, src) {
  // a CSS pane: the picture (or the palette glows) under flute shading at the same width and angle
  el.classList.add('st-look-fallback');
  if (src) src.classList.add('st-look-src');
  else {
    const c = (a) => `rgb(${a.map((v) => Math.round(v * 255)).join(' ')})`;
    el.style.background = `radial-gradient(60% 75% at 22% 40%, ${c(pal.accent)} 0%, transparent 70%), radial-gradient(55% 70% at 78% 65%, ${c(pal.accent2)} 0%, transparent 70%), ${c(pal.bg)}`;
  }
  const w = Math.max(6, o.width);
  const pane = document.createElement('div');
  pane.className = 'st-fg-pane';
  pane.style.background = `repeating-linear-gradient(${90 + o.angle}deg, rgb(0 0 0 / ${0.32 * o.light}) 0, rgb(255 255 255 / ${0.04 * o.light}) 1.5px, rgb(255 255 255 / ${0.22 * o.light}) ${(w * 0.26).toFixed(1)}px, rgb(255 255 255 / 0) ${(w * 0.5).toFixed(1)}px, rgb(0 0 0 / ${0.16 * o.light}) ${(w - 1.5).toFixed(1)}px, rgb(0 0 0 / ${0.32 * o.light}) ${w}px)`;
  if (src) src.style.filter = `blur(${(1 + 2 * o.depth).toFixed(1)}px) saturate(1.05)`;
  el.prepend(pane);
  if (src) el.prepend(src);
}

export const FlutedGlass = define({
  name: 'fluted-glass',
  defaults: { at: 0, preset: 'fluted', src: '', width: null, depth: null, angle: null, split: null, frost: null, light: null, flow: null, drift: 0.008, focus: null, keys: null, scale: null, seed: 1 },
  async setup(el, o) {
    const P = { ...(PRESETS[o.preset] || PRESETS.fluted) };
    for (const k of Object.keys(P)) if (o[k] != null && Number.isFinite(Number(o[k]))) P[k] = Number(o[k]);
    const src = findSource(el, o.src);
    await sourceReady(src);
    const pal = palette(el);
    // without a GPU the pane draws at 0.75 unless a scale is given (scaled up, it looks the same at the frame size)
    const auto = o.scale == null || o.scale === '';
    const scale = auto ? (softwareGL() ? 0.75 : 1) : clamp(Number(o.scale) || 1, 0.25, 2);
    const layer = lookLayer(el, { name: 'fluted-glass', scale, fallback: () => { if (src) src.classList.remove('st-look-hidden'); fallback(el, P, pal, src); } });
    if (!layer) {
      fallback(el, P, pal, src);
      register(el, { look: 'fluted-glass', gl: false, preset: o.preset, box: [el.clientWidth, el.clientHeight], note: 'no WebGL: drew the CSS pane' });
      return { duration: 0, update() {} };
    }
    if (src) src.classList.add('st-look-src', 'st-look-hidden');
    const prog = layer.program(FRAG, src ? { SRC: 1 } : {});
    const tex = src ? layer.texture(src, { mips: src.tagName === 'IMG' }) : null;
    const live = src && src.tagName === 'CANVAS';
    const fit = src ? coverFit(...sourceSize(src), layer.W, layer.H, Array.isArray(o.focus) ? o.focus : [50, 50]) : [1, 1, 0, 0];
    const k = layer.dpr * scale;
    const ground = glows(pal, layer.W / layer.H, Number(o.seed) || 0);
    // the cost check estimates is the one without a GPU: at the size it would draw there
    const kc = auto ? 0.75 / scale : 1;
    register(el, { look: 'fluted-glass', gl: true, preset: o.preset, box: layer.box, passes: [{ kind: 'glass', w: Math.round(layer.W * kc), h: Math.round(layer.H * kc) }] });
    const draw = (lt) => {
      const v = keyed(P, o.keys, lt);
      const tt = Math.max(0, lt);
      const a = (v.angle * Math.PI) / 180;
      layer.draw(prog, {
        ...(tex ? { uSrc: tex } : ground(tt)), uT: tt, uSeed: Number(o.seed) || 0, uFit: fit,
        uZoom: 1 + Math.min(0.12, Math.max(0, Number(o.drift) || 0) * tt),
        uFlute: Math.max(4, v.width * k), uDir: [Math.cos(a), Math.sin(a)], uDepth: v.depth, uSplit: v.split,
        uFrost: tex && tex.mips ? v.frost : 0, uLight: v.light, uShift: (v.flow * tt) / Math.max(4, v.width),
      });
    };
    return {
      duration: 0,
      update(lt) {
        if (!onScreen(el)) return undefined;
        if (!live) { draw(lt); return undefined; }
        // a canvas drawn by the page: after this seek's other handlers have drawn it
        return Promise.resolve().then(() => { tex.update(); draw(lt); });
      },
    };
  },
});

export default FlutedGlass;

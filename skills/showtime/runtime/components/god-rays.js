// god-rays: shafts of light through a word or a logo. A light sits behind the shape (or above the frame, or
// the shape itself shines) and its light is gathered along rays from the light point, so light leaks out
// between and inside the letters in beams and the shape's shadow streaks away from it. A WebGL look
// (runtime/effects/gl.js): the light is traced at a quarter of the frame size in three nested passes of 8
// taps (each one smears every pixel over one step of the next, so 512 steps in all) and lit at half size;
// the shape itself is a sharp 2D canvas over them. Without WebGL: a still CSS glow and beams behind the shape.
//
//   <div data-st="god-rays" data-text="Northlight"></div>                            (fills its scene)
//   <div data-st="god-rays" data-logo="media/mark.svg" data-preset="spotlight"
//        data-keys='[{"at":0,"x":0.2},{"at":0.2,"dur":2.4,"x":0.5,"ease":"sine.inOut"}]'></div>
//
// Presets: dawn (a warm light right behind the shape: beams burst out around and between the letters, the
// shape a dark silhouette with a lit rim), spotlight (a cool light above the frame: beams fall through the air
// and the letters cast long shadows down them), glow (the shape itself shines in the accent and streams out).
// Options override the preset: text or logo (an image URL; or an <img> inside the element), size (the word's
// height, fraction of the frame height), cx, cy (the shape's centre, fractions), x, y (the light, fractions
// of the box; outside it for a light off the frame), length (how far the rays reach, 0-1), strength (0-2),
// decay (0.5-1: how fast the light fades along a ray), shafts (how broken the light is into separate beams,
// 0-1), disc (the light's size: dawn, a share of the shape's half width; spotlight, frame heights), color
// (the light's colour, any CSS colour), drift (the light sways a little, 0 holds it), in (seconds for the
// light to come up from `at`), keys [{at, dur, ease, x, y, length, strength, decay, shafts}], scale (the size
// the light is drawn at, default 0.5), seed.
import { define, clamp, ease } from './core.js';
import { lookLayer, palette, keyed, register, onScreen, rgb, mixRgb, cssRgb, lum } from '../effects/gl.js';

const PRESETS = {
  dawn: { x: 0.5, y: 0.46, length: 0.75, strength: 1, decay: 0.97, shafts: 0.4, disc: 0.45, mode: 'behind' },
  spotlight: { x: 0.36, y: -0.3, length: 1, strength: 0.7, decay: 0.93, shafts: 0.85, disc: 0.62, mode: 'sky' },
  glow: { x: 0.5, y: 0.5, length: 0.7, strength: 1, decay: 0.72, shafts: 0.3, disc: 0.4, mode: 'glow' },
};
const TAPS = 8;
const SWAY = 0.012;                 // how far the light sways (fraction of the frame) with drift 1
const REACH = 1.25;                 // distances to the light are counted in this many frame heights

// The passes into offscreen targets work in texture space (gl_FragCoord / uRes, y up), so a target reads back
// the way it was written. A light off the frame gets the targets padded by uPad (a share of the frame on each
// side) so every ray runs inside them: frame uv = target uv * (1 + 2 uPad) - uPad. The mask was uploaded top
// row first.

// the light before the rays: what each pixel would send toward the viewer if nothing stood in the way. BEHIND:
// a bright halo right behind the shape (its mask blurred once at setup) and the light's own core, with the
// shape cut out, so light leaks out around and between the letters; SKY (a light off the frame): the air near
// the light broken into beams, with the shape cut out; GLOW: the shape itself and its halo. At the rays' size.
const EMIT = `
uniform sampler2D uMask;
uniform sampler2D uHaloTex;
uniform vec2 uLight;
uniform float uAspect;
uniform float uDisc;
uniform float uPad;
uniform float uPhase;
uniform float uShafts;
float sector(float i) { return hash(vec2(mod(i, SECTORS), 7.0)); }
void main() {
  vec2 p = gl_FragCoord.xy / uRes * (1.0 + 2.0 * uPad) - uPad;
  vec2 d = vec2((p.x - uLight.x) * uAspect, p.y - uLight.y);
  float r = length(d);
  vec2 mq = vec2(p.x, 1.0 - p.y);
  float inside = step(0.0, p.x) * step(p.x, 1.0) * step(0.0, p.y) * step(p.y, 1.0);
  float m = texture2D(uMask, mq).a * inside;
  // the light broken into beams: smooth noise over SECTORS sectors around the light point, turning slowly
  float a = (atan(d.y, d.x) / 6.2831853 + 0.5) * SECTORS + uPhase;
  float i = floor(a), fa = fract(a);
  float beams = mix(sector(i), sector(i + 1.0), fa * fa * (3.0 - 2.0 * fa));
#ifdef SKY
  beams = mix(1.0, 2.6 * beams * beams * beams, uShafts);
#else
  beams = mix(1.0, 0.3 + 1.05 * beams, uShafts);
#endif
  float halo = texture2D(uHaloTex, mq).a * inside;
  float core = 1.0 - smoothstep(0.0, uDisc, r);
#ifdef GLOW
  // the shape, its halo and a soft core at the light point (the middle of the shape would otherwise send a
  // dark streak out wherever its gaps line up with the light)
  float e = (m * 0.75 + smoothstep(0.0, 0.6, halo) * 0.45 + core * core * 0.2) * (0.75 + 0.25 * beams);
#else
#ifdef SKY
  float e = core * beams * (1.0 - m);
#else
  float e = (smoothstep(0.0, 0.45, halo) * 0.85 + core * core * 0.7) * beams * (1.0 - m);
#endif
#endif
  // times its distance to the light (the passes take samples evenly spaced in proportion to that distance, so
  // this makes their plain average an even average along the ray; the compose divides the distance out again),
  // stored as a square root with a little noise: the targets hold 8 bits, and a faint light far from its
  // source would otherwise step into blotches once the passes average it and the compose brightens it
  gl_FragColor = vec4(vec3(sqrt(clamp(e * min(1.0, r / ${REACH.toFixed(2)}), 0.0, 1.0)) + (hash(gl_FragCoord.xy) - 0.5) / 255.0), 1.0);
}`;

// one pass of the rays: the plain average of TAPS samples toward the light, each one uRatio times nearer to it
// than the last (so the passes nest in proportion: a pass smears each pixel over one step of the next one,
// wherever it is; plain averages, so no step in weight shows where a bright edge crosses from one tap to the next)
const RAYS = `
uniform sampler2D uSrc;
uniform vec2 uLight;
uniform float uRatio;
void main() {
  vec2 p = gl_FragCoord.xy / uRes;
  vec2 d = p - uLight;
  float acc = 0.0, sum = 0.0, f = 1.0;
  for (int i = 0; i < ${TAPS}; i++) {
    // only taps inside the target count (a light past the padding): past its edge every pixel's far taps would
    // read the same edge texels and split the picture along the line under the light
    vec2 q = uLight + d * f;
    float k = step(0.0, q.x) * step(q.x, 1.0) * step(0.0, q.y) * step(q.y, 1.0);
    float v = texture2D(uSrc, q).r;
    acc += v * v * k;
    sum += k;
    f *= uRatio;
  }
  gl_FragColor = vec4(vec3(sqrt(acc / max(sum, 1e-6)) + (hash(gl_FragCoord.xy + uRatio * 977.0) - 0.5) / 255.0), 1.0);
}`;

// the ground lit by the rays, with a filmic roll-off; at half size (the shape is drawn sharp over it)
const COMPOSE = `
uniform sampler2D uRays;
uniform vec3 uGround;
uniform vec3 uGround2;
uniform vec3 uLightCol;
uniform float uStrength;
uniform vec2 uLight;
uniform float uAspect;
uniform float uPad;
uniform float uSpan;
uniform float uDecay;
void main() {
  vec2 d = vec2((vUv.x - uLight.x) * uAspect, vUv.y - uLight.y);
  // the air: lighter toward the light, darker toward the corners
  float near = 1.0 / (1.0 + dot(d, d) * 2.5);
  vec3 g = mix(uGround2, uGround, near);
  float r = texture2D(uRays, (vec2(vUv.x, 1.0 - vUv.y) + uPad) / (1.0 + 2.0 * uPad)).r;
  // the samples' mean distance to the light (uSpan: the mean of the proportional steps) divided out, and the
  // light fading the further the pixel is from it (decay)
  float dl = min(1.0, length(d) / ${REACH.toFixed(2)});
  r = r * r / max(dl * uSpan, 0.02) * pow(uDecay, dl * 8.0);
  vec3 c = toLinear(g) + toLinear(uLightCol) * (r * 3.2 + 0.05 * near) * uStrength;
  // a soft shoulder above 0.7: the light's core rolls off instead of clipping into a flat disc
  vec3 over = max(c - 0.7, 0.0);
  c = min(c, 0.7) + 0.3 * (1.0 - exp(-over / 0.3));
  gl_FragColor = vec4(dither(toSrgb(c)), 1.0);
}`;

/** The shape as a 2D canvas of w x h px (CPU canvas, so it is the same in every render worker); .halfW its half width. */
async function shapeCanvas(el, o, src, w, h) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const g = c.getContext('2d', { willReadFrequently: true });
  const cx = o.cx * w, cy = o.cy * h;
  c.halfW = 0;
  if (src) {
    const [iw, ih] = src.tagName === 'IMG' ? [src.naturalWidth, src.naturalHeight] : [src.width, src.height];
    const s = Math.min((o.size * 2.2 * h) / Math.max(1, ih), (0.7 * w) / Math.max(1, iw));
    g.drawImage(src, cx - (iw * s) / 2, cy - (ih * s) / 2, iw * s, ih * s);
    c.halfW = (iw * s) / 2;
    return c;
  }
  if (!o.text) return c;
  const cs = getComputedStyle(el);
  const fam = cs.getPropertyValue('--font-display').trim() || cs.fontFamily || 'sans-serif';
  const weight = cs.getPropertyValue('--weight-display').trim() || '800';
  let px = o.size * h;
  if (document.fonts) await document.fonts.load(`${weight} ${Math.round(px)}px ${fam}`, o.text).catch(() => null);
  g.font = `${weight} ${px}px ${fam}`;
  const tw = g.measureText(o.text).width;
  if (tw > 0.82 * w) { px *= (0.82 * w) / tw; g.font = `${weight} ${px}px ${fam}`; }
  const track = parseFloat(cs.getPropertyValue('--tracking-display')) || 0;
  if ('letterSpacing' in g) g.letterSpacing = `${(track * px).toFixed(2)}px`;
  g.textAlign = 'center';
  g.textBaseline = 'alphabetic';
  const mt = g.measureText(o.text);
  // centred on the ink, not on the line box
  g.fillText(o.text, cx, cy + (mt.actualBoundingBoxAscent - mt.actualBoundingBoxDescent) / 2);
  c.halfW = mt.width / 2;
  return c;
}

function colours(pal, P, o) {
  const W = [1, 1, 1];
  const light = lum(pal.bg) > 0.5;
  const lightCol = o.color ? rgb(o.color) : P.mode === 'glow' ? mixRgb(pal.accent, W, 0.08)
    : P.mode === 'sky' ? mixRgb(pal.accent2, W, 0.5) : mixRgb(pal.accent, W, 0.35);
  // the air the light shows in: the ground a few steps down (light needs dark air to show), darker toward the
  // corners; on a light ground a dusk in the theme's own ink colour
  const ground = light ? mixRgb(pal.fg, pal.bg, 0.16) : pal.bg.map((v) => v * 0.62);
  const ground2 = light ? pal.fg.map((v) => v * 0.55) : pal.bg.map((v) => v * 0.3);
  const ink = P.mode === 'glow' ? mixRgb(mixRgb(light ? pal.bg : pal.fg, W, 0.6), lightCol, 0.12) : (light ? pal.fg : pal.bg).map((v) => v * 0.3);
  return { light, lightCol, ground, ground2, ink };
}

/** The sharp shape over the light, in the ink colour; behind a light, a thin rim lit on its edges. */
function inkCanvas(full, P, C, opt, box, dpr) {
  const ink = document.createElement('canvas');
  ink.width = full.width; ink.height = full.height;
  ink.className = 'st-look-canvas st-gr-shape';
  ink.setAttribute('aria-hidden', 'true');
  const ig = ink.getContext('2d', { willReadFrequently: true });
  const tint = (fill) => {
    const t = document.createElement('canvas');
    t.width = full.width; t.height = full.height;
    const tg = t.getContext('2d', { willReadFrequently: true });
    tg.drawImage(full, 0, 0);
    tg.globalCompositeOperation = 'source-in';
    tg.fillStyle = fill;
    tg.fillRect(0, 0, t.width, t.height);
    return t;
  };
  ig.drawImage(tint(P.mode === 'glow' ? cssRgb(C.ink) : cssRgb(mixRgb(C.ink, C.lightCol, 0.75))), 0, 0);
  if (P.mode !== 'glow') {
    const dx = (opt.cx - P.x) * box[0], dy = (opt.cy - P.y) * box[1], dl = Math.hypot(dx, dy) || 1;
    const rim = Math.max(1, opt.size * box[1] * 0.012) * dpr;
    ig.globalCompositeOperation = 'source-atop';
    ig.drawImage(tint(cssRgb(C.ink)), (dx / dl) * rim, (dy / dl) * rim);
    ig.globalCompositeOperation = 'source-over';
  }
  return ink;
}

function fallback(el, P, C, ink) {
  // the light as a radial glow and its beams as a soft conic pattern around it, the shape over them
  el.classList.add('st-look-fallback');
  const at = `${(P.x * 100).toFixed(1)}% ${(P.y * 100).toFixed(1)}%`;
  const a = (k) => cssRgb(C.lightCol, k);
  el.style.background = [
    `radial-gradient(circle at ${at}, ${a(0.9)} 0%, ${a(0.32)} 14%, ${a(0)} ${P.mode === 'sky' ? 95 : 60}%)`,
    `repeating-conic-gradient(from 0deg at ${at}, ${a(0)} 0deg, ${a(0.14 * P.strength)} 2.5deg, ${a(0)} 6deg, ${a(0)} 11deg)`,
    `radial-gradient(120% 120% at ${at}, ${cssRgb(C.ground)} 0%, ${cssRgb(C.ground2)} 100%)`,
  ].join(', ');
  if (!ink.isConnected) el.prepend(ink);
}

export const GodRays = define({
  name: 'god-rays',
  defaults: { at: 0, preset: 'dawn', text: '', logo: '', size: 0.22, cx: 0.5, cy: 0.5, x: null, y: null, length: null, strength: null, decay: null, shafts: null, disc: null, color: '', drift: 1, in: 0, keys: null, scale: 0.5, seed: 4 },
  async setup(el, o) {
    const preset = o.preset in PRESETS ? o.preset : 'dawn';
    const P = { ...PRESETS[preset] };
    for (const k of ['x', 'y', 'length', 'strength', 'decay', 'shafts', 'disc']) if (o[k] != null && o[k] !== '' && Number.isFinite(Number(o[k]))) P[k] = Number(o[k]);
    const opt = { ...o, size: clamp(Number(o.size) || 0.22, 0.04, 0.8), cx: Number(o.cx), cy: Number(o.cy) };
    let src = null;
    if (o.logo) {
      src = new Image(); src.decoding = 'sync'; src.src = o.logo;
      try { await src.decode(); } catch { src = null; }
    } else src = el.querySelector(':scope > img');
    if (src && !src.naturalWidth) { try { await src.decode(); } catch { src = null; } }
    if (src && src.parentElement === el) src.remove();
    if (!src && !o.text) throw new Error('god-rays needs a shape: data-text="Word", data-logo="logo.png", or an <img> inside the element');
    if (o.text) el.setAttribute('aria-label', o.text);
    const pal = palette(el);
    const C = colours(pal, P, o);
    const scale = clamp(Number(o.scale) || 0.5, 0.25, 1);
    const dpr = window.devicePixelRatio || 1;
    let ink = null;
    const layer = lookLayer(el, { name: 'god-rays', scale, fallback: () => fallback(el, P, C, ink) });
    const box = layer ? layer.box : [el.clientWidth || 640, el.clientHeight || 360];
    // the shape, drawn once at the frame size: the mask the light reads and, tinted, the sharp shape on top
    const full = await shapeCanvas(el, opt, src, Math.round(box[0] * dpr), Math.round(box[1] * dpr));
    ink = inkCanvas(full, P, C, opt, box, dpr);
    if (!layer) {
      fallback(el, P, C, ink);
      register(el, { look: 'god-rays', gl: false, preset, box, note: 'no WebGL: drew a still CSS glow and beams behind the shape' });
      return { duration: 0, update() {} };
    }
    layer.canvas.after(ink);
    // a light off the frame (or keyed off it): the targets grow by that much on each side, so its rays stay in them
    const lights = [P, ...(Array.isArray(o.keys) ? o.keys : [])].flatMap((k) => [Number(k && k.x), Number(k && k.y)]).filter(Number.isFinite);
    const pad = clamp(Math.max(0, ...lights.map((v) => Math.max(-v, v - 1))) + (lights.some((v) => v < 0 || v > 1) ? SWAY * 2 : 0), 0, 0.6);
    const qw = Math.max(2, Math.round((layer.W / 2) * (1 + 2 * pad))), qh = Math.max(2, Math.round((layer.H / 2) * (1 + 2 * pad)));
    const mask = layer.texture(full, { mips: true });
    // the halo behind the shape: its mask blurred to about a sixth of its height, once, on a CPU canvas at the
    // rays' size (the same bytes in every render worker)
    const rw = Math.max(2, Math.round(layer.W / 2)), rh = Math.max(2, Math.round(layer.H / 2));
    const hc = document.createElement('canvas');
    hc.width = rw; hc.height = rh;
    const hg = hc.getContext('2d', { willReadFrequently: true });
    hg.filter = `blur(${Math.max(1, opt.size * rh * (src ? 2.2 : 1) * 0.16).toFixed(2)}px)`;
    hg.drawImage(full, 0, 0, rw, rh);
    const halo = layer.texture(hc);
    const emit = layer.program(EMIT, P.mode === 'glow' ? { GLOW: 1, SECTORS: '40.0' } : P.mode === 'sky' ? { SKY: 1, SECTORS: '110.0' } : { SECTORS: '40.0' });
    const rays = layer.program(RAYS);
    const comp = layer.program(COMPOSE);
    const A = layer.target(qw, qh), B = layer.target(qw, qh);
    // the light (its emission and three ray passes, at the rays' size) and the lit ground (at the canvas size)
    register(el, { look: 'god-rays', gl: true, preset, box: layer.box, passes: [{ kind: 'rays', w: qw, h: qh }, { kind: 'lit', w: layer.W, h: layer.H }] });
    const grow = Math.max(0, Number(o.in) || 0);
    const drift = Math.max(0, Number(o.drift) || 0);
    const E = ease('sine.out');
    const seed = Number(o.seed) || 0;
    const aspect = layer.W / layer.H;
    // the light behind the shape: dawn's disc is a share of the shape's half width, the spotlight's in frame heights
    const disc = P.mode === 'sky' ? Math.max(0.05, P.disc) : Math.max(0.05, P.disc * ((full.halfW || 0.3 * full.width) / full.height));
    const draw = (lt) => {
      const v = keyed(P, o.keys, lt);
      const tt = Math.max(0, lt);
      const up = grow > 0 ? E(clamp(lt / grow)) : 1;
      // the light sways a little, so the shafts sweep across the shape
      const lx = v.x + SWAY * drift * Math.sin(0.35 * tt + seed), ly = v.y + SWAY * 0.7 * drift * Math.cos(0.27 * tt + seed * 2);
      const Lt = [lx, 1 - ly], Lq = [(lx + pad) / (1 + 2 * pad), (1 - ly + pad) / (1 + 2 * pad)];
      const len = clamp(v.length, 0, 1);
      layer.draw(emit, { uMask: mask, uHaloTex: halo, uLight: Lt, uAspect: aspect, uShafts: clamp(v.shafts, 0, 1), uDisc: disc, uPad: pad, uPhase: tt * 0.3 + seed * 5.3 }, A);
      // three passes of TAPS taps, in proportion: the last one's taps reach from the pixel to (1 - length) of
      // its distance to the light, each earlier pass covers exactly one step of the next (TAPS^3 steps in all)
      const rho = Math.max(0.02, 1 - len), r2 = Math.pow(rho, 1 / TAPS);
      const r1 = Math.pow(r2, 1 / TAPS), r0 = Math.pow(r1, 1 / TAPS);
      layer.draw(rays, { uSrc: A, uLight: Lq, uRatio: r0 }, B);
      layer.draw(rays, { uSrc: B, uLight: Lq, uRatio: r1 }, A);
      layer.draw(rays, { uSrc: A, uLight: Lq, uRatio: r2 }, B);
      // the mean of TAPS^3 proportional steps from 1 down to rho: (1 - rho) / -ln(rho) for a fine enough step
      const span = (1 - rho) / Math.max(1e-3, -Math.log(rho));
      layer.draw(comp, { uRays: B, uGround: C.ground, uGround2: C.ground2, uLightCol: C.lightCol, uStrength: Math.max(0, v.strength) * up,
        uLight: [lx, ly], uAspect: aspect, uPad: pad, uSpan: span, uDecay: clamp(v.decay, 0.3, 1) });
    };
    return { duration: grow, update(lt) { if (onScreen(el)) draw(lt); } };
  },
});

export default GodRays;

// liquid-metal: a chrome hero object (sphere, blob or ring) with a slowly flowing surface. It reflects a
// studio built from the theme palette, and an optional word or logo on a sign behind the viewer. A WebGL
// look (runtime/effects/gl.js) on a transparent canvas, so it sits on the scene's own ground; without
// WebGL it draws a still 2D chrome sphere.
//
//   <div data-st="liquid-metal"></div>                                         (fills its scene)
//   <div data-st="liquid-metal" data-shape="blob" data-text="Tidepool" data-x="0.7" data-size="0.5"></div>
//
// Presets: auto (chrome on a dark ground, pearl on a light one), chrome, pearl, neon (accent lights in
// the dark). Options: shape (sphere | blob | ring), size (radius, fraction of half the shorter side),
// x, y (centre, fractions of the box), liquid (how much the surface flows, 0-1), speed, turn (the studio
// turns, degrees per second), text or logo (an image URL) for the reflected sign, shadow (0-1), in
// (seconds to grow in from `at`), keys [{at, dur, ease, x, y, size, liquid}], scale (render scale; default 1,
// or 0.75 where WebGL runs on the CPU: the same picture at half the cost), seed.
import { define, clamp, ease } from './core.js';
import { lookLayer, palette, keyed, register, onScreen, lum, softwareGL } from '../effects/gl.js';

const SHAPES = { sphere: 0, blob: 1, ring: 2 };
const D = 4.0;                                  // camera distance; the object's radius is 1
const TAN_SIL = Math.tan(Math.asin(1 / D));     // tangent of the silhouette's angular radius

const FRAG = `
uniform vec2 uCenter;
uniform float uSize;
uniform float uTanH;
uniform float uLiquid;
uniform float uFlowT;
uniform vec4 uTurn;
uniform float uFade;
uniform float uShadow;
uniform vec3 uZenith;
uniform vec3 uHorizon;
uniform vec3 uGround;
uniform vec3 uFloor;
uniform vec3 uStripA;
uniform vec3 uStripB;
uniform vec3 uStripC;
uniform vec3 uPanel;
uniform vec3 uSpec;
uniform vec3 uTint;
uniform vec3 uInk;
uniform sampler2D uText;
uniform float uExposure;
uniform vec4 uRing;

const float D = ${D.toFixed(1)};
const float PI = 3.14159265;

// a smooth, slowly turning vector field: three layers of sines fed into each other (no noise lattice)
vec3 flow(vec3 p, float t) {
  vec3 q = p * 1.35 + vec3(uSeed * 1.37, uSeed * 0.71, uSeed * 2.13);
  q += 0.7 * sin(q.yzx * 1.7 + vec3(0.0, 1.3, 2.6) + t * vec3(0.43, 0.37, 0.31));
  q += 0.42 * sin(q.zxy * 2.9 + vec3(2.1, 0.4, 1.7) - t * vec3(0.29, 0.33, 0.41));
  q += 0.18 * sin(q.yzx * 5.3 + vec3(1.1, 2.7, 0.3) + t * vec3(0.23, 0.31, 0.27));
  return sin(q * 1.6);
}

// the shape's slow swell: the first layer of the flow only (the SDF runs up to 20 times a pixel)
float swell(vec3 p, float t) {
  vec3 q = p * 1.35 + vec3(uSeed * 1.37, uSeed * 0.71, uSeed * 2.13);
  q += 0.7 * sin(q.yzx * 1.7 + vec3(0.0, 1.3, 2.6) + t * vec3(0.43, 0.37, 0.31));
  vec3 s = sin(q * 1.6);
  return s.x + s.y + s.z;
}

float sdf(vec3 p) {
#if SHAPE == 2
  vec3 q = p;
  q.yz = mat2(uRing.x, uRing.y, -uRing.y, uRing.x) * q.yz;
  q.xz = mat2(uRing.z, uRing.w, -uRing.w, uRing.z) * q.xz;
  vec2 tq = vec2(length(q.xz) - 0.74, q.y);
  return length(tq) - 0.27 + 0.018 * uLiquid * swell(p * 1.3, uFlowT);
#else
  return length(p) - 0.92 + 0.06 * uLiquid * swell(p, uFlowT);
#endif
}

vec3 sdfNormal(vec3 p) {
  vec2 k = vec2(1.0, -1.0) * 0.0025;
  return normalize(k.xyy * sdf(p + k.xyy) + k.yyx * sdf(p + k.yyx) + k.yxy * sdf(p + k.yxy) + k.xxx * sdf(p + k.xxx));
}

// 1 inside [-h, h], falling off smoothly over soft beyond it: soft boxes, never hard-edged
float win(float x, float h, float soft) { return 1.0 - smoothstep(h, h + soft, abs(x)); }
float strip(float az, float el, vec2 c, vec2 h, float soft) {
  return win(mod(az - c.x + PI, 2.0 * PI) - PI, h.x, soft) * win(el - c.y, h.y, soft);
}

// the studio: a bright horizon, a smooth sky above it and a darker floor below, and three soft boxes
// (lights in a dark studio; dark cards, CARDS, in a white one)
vec3 env(vec3 r) {
  r.xz = mat2(uTurn.x, uTurn.y, -uTurn.y, uTurn.x) * r.xz;
  float el = r.y;
  float az = atan(r.x, -r.z);                   // 0: past the object; +-PI: behind the viewer
  vec3 sky = mix(uHorizon, uZenith, sqrt(clamp(el, 0.0, 1.0)));
  vec3 flo = mix(uGround, uFloor, smoothstep(0.0, 0.7, -el));
  // a dim bounce card on the floor in front of the object, so the lower half is graded, not a void
  flo += uGround * 0.4 * strip(az, el, vec2(3.14, -0.4), vec2(1.1, 0.02), 0.4);
  vec3 c = mix(flo, sky, smoothstep(-0.015, 0.015, el));
  float a = strip(az, el, vec2(-1.6, 0.52), vec2(0.4, 0.12), 0.2);      // key: wide, upper left
  float b = strip(az, el, vec2(1.35, 0.22), vec2(0.04, 0.42), 0.12);    // tall strip, right
  float s = strip(az, el, vec2(-0.8, 0.15), vec2(0.035, 0.36), 0.1);    // tall strip, left and behind
#ifdef CARDS
  c *= (1.0 - 0.88 * a) * (1.0 - 0.8 * b) * (1.0 - 0.7 * s);
#else
  c += uStripA * a + uStripB * b + uStripC * s;
#endif
  return c;
}

void main() {
  float hm = 0.5 * min(uRes.x, uRes.y);
  vec2 p = (vUv * uRes - uCenter * uRes) / hm;
  p.y = -p.y;
  vec3 ro = vec3(0.0, 0.0, D);
  vec3 rd = normalize(vec3(p * uTanH, -1.0));
  float pixW = D * uTanH / hm;                 // world size of a pixel at the object

  float cov = 0.0;
  vec3 pos = vec3(0.0, 0.0, 1.0);
  vec3 n = vec3(0.0, 0.0, 1.0);
  float b = dot(ro, rd);
  float wobble = 0.6;
#if SHAPE == 0
  {
    float c0 = dot(ro, ro) - b * b;              // squared distance of the ray from the centre
    cov = clamp((1.0 - sqrt(max(0.0, c0))) / pixW + 0.5, 0.0, 1.0);
    float h = 1.0 - c0;
    pos = h > 0.0 ? ro + rd * (-b - sqrt(h)) : normalize(ro - rd * b);
    n = normalize(pos);
  }
#else
  {
    // a shape that stays within a few hundredths of its bounding sphere: a few steps from that sphere reach it
    wobble = 0.3;
    float bound = SHAPE == 2 ? 1.12 : 1.1;
    float h = b * b - (dot(ro, ro) - bound * bound);
    float minD = 1e3;
    if (h > 0.0) {
      float t = -b - sqrt(h);
      float tEnd = -b + sqrt(h);
      for (int i = 0; i < 20; i++) {
        vec3 q = ro + rd * t;
        float d = sdf(q);
        minD = min(minD, d / pixW);
        if (d < 0.4 * pixW) { pos = q; minD = -1.0; break; }    // closer than half a pixel: a hit
        t += d * 0.9;
        if (t > tEnd) break;
      }
      if (minD < 0.0) { cov = 1.0; n = sdfNormal(pos); }
      else {
        cov = clamp(1.0 - minD, 0.0, 1.0) * step(minD, 1.5);
        pos = ro + rd * (-b);
        n = normalize(pos);
      }
    }
  }
#endif

  // a soft contact shadow on the floor under the object; pixels the object does not cover stop here
  vec2 shp = (p - vec2(0.0, -uSize * (SHAPE == 2 ? 0.95 : 1.06))) / vec2(uSize * 0.92, uSize * 0.17);
  float sh = uShadow * pow(clamp(1.0 - length(shp), 0.0, 1.0), 1.6);
  if (cov <= 0.0) { gl_FragColor = vec4(0.0, 0.0, 0.0, sh * uFade); return; }

  // the liquid: the normal bent along the surface by the flow field, a little calmer where the surface
  // faces the viewer so the sign reflected there keeps its shape
  vec3 f = flow(pos * (SHAPE == 0 ? 1.0 : 1.4), uFlowT);
  float calm = 1.0 - 0.55 * n.z * n.z;
  n = normalize(n + wobble * calm * uLiquid * (f - dot(f, n) * n));

  vec3 r = reflect(rd, n);
  vec3 col = env(r);
  // a soft box behind the viewer, facing the object: it fills the middle of the metal, and carries the word
  vec3 rr = r;
  rr.xz = mat2(uTurn.z, uTurn.w, -uTurn.w, uTurn.z) * rr.xz;
  float facing = smoothstep(0.08, 0.32, rr.z);
  vec2 sp = vec2(rr.x, rr.y - 0.3 * rr.z) / max(rr.z, 0.08);
  float panel = win(sp.x, 1.45, 0.3) * win(sp.y, 0.3, 0.16) * facing;
  col += uPanel * panel;
#ifdef SIGN
  vec2 suv = vec2(sp.x * 0.25 + 0.5, 0.5 - sp.y * 0.5);
  float inside = step(0.0, suv.x) * step(suv.x, 1.0) * step(0.0, suv.y) * step(suv.y, 1.0);
  col = mix(col, uInk, texture2D(uText, suv).a * inside * facing * 0.94);
#endif
  // the key light's own highlight: a tight core and a soft bloom around it
  float hl = max(dot(r, normalize(vec3(-0.5, 0.62, 0.6))), 0.0);
  float h2 = hl * hl, h4 = h2 * h2, h8 = h4 * h4, h16 = h8 * h8;
  col += uSpec * (h16 * h16 * h16 * h16 * 9.0 + h8 * h4 * 0.22);

  // fresnel: the metal reflects more toward its edges
  float cosT = clamp(dot(-rd, n), 0.0, 1.0);
  float fr = 1.0 - cosT;
  col *= uTint + (1.0 - uTint) * (fr * fr * fr * fr * fr);
  // filmic shoulder (whites roll off instead of clipping into flat patches), then polish: a little contrast
  // and saturation
  col *= uExposure;
  col = clamp((col * (2.51 * col + 0.03)) / (col * (2.43 * col + 0.59) + 0.14), 0.0, 1.0);
  col = toSrgb(col);
  col = mix(col, col * col * (3.0 - 2.0 * col), 0.25);
  col = clamp(mix(vec3(luma(col)), col, 1.12), 0.0, 1.0);

  float al = cov * uFade;
  gl_FragColor = vec4(dither(col) * al, al + sh * uFade * (1.0 - al));
}`;

/* ------------------------------------------------------------- studio */

// the ring's tilt (rocking slowly) and turn at flow time ft, as cos/sin pairs for the shader
const ring = (ft) => { const a = -0.95 + 0.12 * Math.sin(ft * 0.31), b = ft * 0.18; return [Math.cos(a), Math.sin(a), Math.cos(b), Math.sin(b)]; };
// the studio's turn (the sign behind the viewer turns half as fast), as cos/sin pairs
const turn = (a) => [Math.cos(a), Math.sin(a), Math.cos(a * 0.5), Math.sin(a * 0.5)];
const lin = (c) => c.map((v) => Math.pow(v, 2.2));
const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t);
const mul = (a, k) => a.map((v) => v * k);
const WHITE = [1, 1, 1];

function studio(preset, pal) {
  const bg = lin(pal.bg), fg = lin(pal.fg), a1 = lin(pal.accent), a2 = lin(pal.accent2);
  const kind = preset === 'auto' || !preset ? (pal.dark ? 'chrome' : 'pearl') : preset;
  if (kind === 'pearl') {
    // a white studio: dark cards (flags) give white metal its edges, the floor is a soft grey
    return { kind, cards: true, zenith: mul(mix(WHITE, a2, 0.06), 0.72), horizon: mul(WHITE, 1.05), ground: mul(WHITE, 0.5),
      floor: mul(mix(bg, fg, 0.3), 0.4), stripA: WHITE, stripB: mix(WHITE, a1, 0.3), stripC: mix(WHITE, a2, 0.3),
      panel: mul(WHITE, 0.25), spec: mul(WHITE, 1.4), tint: [0.86, 0.85, 0.83], ink: mul(fg, 0.6), shadow: 0.22, exposure: 1.0 };
  }
  if (kind === 'neon') {
    return { kind, cards: false, zenith: mul(a2, 0.05), horizon: mul(mix(a1, WHITE, 0.2), 1.1), ground: mul(a1, 0.22), floor: mul(bg, 0.12),
      stripA: mul(mix(a2, WHITE, 0.3), 2.4), stripB: mul(a1, 2.6), stripC: mul(mix(a1, a2, 0.5), 2.0),
      panel: mul(mix(a2, WHITE, 0.5), 1.1), spec: mul(WHITE, 2.5), tint: [0.8, 0.8, 0.84], ink: mul(bg, 0.5), shadow: 0.55, exposure: 0.95 };
  }
  // chrome: a dark studio with white soft boxes, the theme's colours as a faint tint in the sky and two strips
  return { kind: 'chrome', cards: false, zenith: mix([0.05, 0.05, 0.055], mul(a2, 0.18), 0.35), horizon: mul(mix(WHITE, a2, 0.1), 1.25),
    ground: mul(mix(WHITE, a1, 0.08), 0.32), floor: mix([0.025, 0.025, 0.028], mul(bg, 0.5), 0.4),
    stripA: mul(mix(WHITE, a2, 0.1), 3.0), stripB: mul(mix(WHITE, a1, 0.3), 2.4), stripC: mul(mix(WHITE, a2, 0.3), 1.8),
    panel: mul(WHITE, 1.5), spec: mul(WHITE, 3.0), tint: [0.8, 0.81, 0.83], ink: mix([0.02, 0.02, 0.025], mul(bg, 0.6), 0.5), shadow: 0.5, exposure: 0.95 };
}

/** The sign the metal reflects: a word or a logo on a transparent 1024x512 canvas. */
async function signCanvas(el, o) {
  const c = document.createElement('canvas');
  c.width = 1024; c.height = 512;
  // a CPU canvas: drawn on the GPU, its antialiased edges can differ by a code value between browser processes
  const g = c.getContext('2d', { willReadFrequently: true });
  if (o.logo) {
    const img = new Image();
    img.decoding = 'sync';
    img.src = o.logo;
    try { await img.decode(); } catch { return null; }
    const s = Math.min(760 / img.naturalWidth, 340 / img.naturalHeight);
    g.drawImage(img, (1024 - img.naturalWidth * s) / 2, (512 - img.naturalHeight * s) / 2, img.naturalWidth * s, img.naturalHeight * s);
    return c;
  }
  if (!o.text) return null;
  const cs = getComputedStyle(el);
  const fam = cs.getPropertyValue('--font-display').trim() || cs.fontFamily || 'sans-serif';
  const weight = cs.getPropertyValue('--weight-display').trim() || '800';
  let size = 200;
  if (document.fonts) await document.fonts.load(`${weight} ${size}px ${fam}`, o.text).catch(() => null);
  g.font = `${weight} ${size}px ${fam}`;
  const w = g.measureText(o.text).width;
  size = Math.min(230, Math.floor(size * 760 / Math.max(1, w)));
  g.font = `${weight} ${size}px ${fam}`;
  g.fillStyle = '#fff';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillText(o.text, 512, 262);
  return c;
}

function fallback(el, o, st) {
  // a still chrome sphere on a 2D canvas: horizon band, key highlight, accent rim, contact shadow
  el.classList.add('st-look-fallback');
  const [bw, bh] = [el.clientWidth || 640, el.clientHeight || 360];
  const dpr = window.devicePixelRatio || 1;
  const c = document.createElement('canvas');
  c.className = 'st-look-canvas';
  c.width = Math.round(bw * dpr); c.height = Math.round(bh * dpr);
  el.prepend(c);
  const g = c.getContext('2d');
  const srgb = (v, k = 1) => `rgb(${v.map((x) => Math.round(255 * Math.min(1, Math.pow(Math.max(0, x * k), 1 / 2.2)))).join(' ')})`;
  const R = o.size * 0.5 * Math.min(c.width, c.height) * (o.shape === 'ring' ? 0.95 : 0.94);
  const cx = o.x * c.width, cy = o.y * c.height;
  const sh = g.createRadialGradient(cx, cy + R * 1.05, 0, cx, cy + R * 1.05, R);
  sh.addColorStop(0, `rgb(0 0 0 / ${st.shadow})`); sh.addColorStop(1, 'rgb(0 0 0 / 0)');
  g.save(); g.translate(0, cy + R * 1.05); g.scale(1, 0.18); g.translate(0, -(cy + R * 1.05));
  g.fillStyle = sh; g.fillRect(cx - R, cy + R * 1.05 - R, 2 * R, 2 * R); g.restore();
  g.save();
  g.beginPath(); g.arc(cx, cy, R, 0, Math.PI * 2);
  if (o.shape === 'ring') g.arc(cx, cy, R * 0.42, 0, Math.PI * 2, true);
  g.clip('evenodd');
  // the studio as the GL look sees it: a dim dome, a bright band over a crisp horizon, a dark floor
  const v = g.createLinearGradient(0, cy - R, 0, cy + R);
  v.addColorStop(0, srgb(st.zenith, 1.4)); v.addColorStop(0.36, srgb(st.zenith));
  v.addColorStop(0.47, srgb(st.horizon)); v.addColorStop(0.495, srgb(st.horizon));
  v.addColorStop(0.505, srgb(st.horizon, 0.3)); v.addColorStop(0.68, srgb(st.floor)); v.addColorStop(1, srgb(st.floor));
  g.fillStyle = v; g.fillRect(cx - R, cy - R, 2 * R, 2 * R);
  // the key box upper left and a cap on top: lights in a dark studio, dark cards in a white one
  const card = st.cards ? 'rgb(30 30 34 / 0.8)' : 'rgb(255 255 255 / 0.96)';
  const blob = (x, y, rx, ry) => {
    g.save(); g.translate(x, y); g.scale(rx / ry, 1);
    const k = g.createRadialGradient(0, 0, 0, 0, 0, ry);
    k.addColorStop(0, card); k.addColorStop(0.75, card); k.addColorStop(1, card.replace(/[\d.]+\)$/, '0)'));
    g.fillStyle = k; g.beginPath(); g.arc(0, 0, ry, 0, Math.PI * 2); g.fill(); g.restore();
  };
  blob(cx - R * 0.42, cy - R * 0.48, R * 0.3, R * 0.17);
  blob(cx + R * 0.05, cy - R * 0.86, R * 0.36, R * 0.07);
  // thin coloured rims on both sides
  g.lineCap = 'round';
  for (const [col, a0, a1] of [[st.stripB, -0.55, 0.5], [st.stripC, Math.PI - 0.45, Math.PI + 0.5]]) {
    g.strokeStyle = srgb(col, 0.35); g.lineWidth = Math.max(1, R * 0.035);
    g.beginPath(); g.arc(cx, cy, R * 0.9, a0, a1); g.stroke();
  }
  g.restore();
}

export const LiquidMetal = define({
  name: 'liquid-metal',
  defaults: { at: 0, preset: 'auto', shape: 'sphere', size: 0.62, x: 0.5, y: 0.5, liquid: 0.55, speed: 1, turn: 6, text: '', logo: '', shadow: null, in: 0, keys: null, scale: null, seed: 3 },
  async setup(el, o) {
    const pal = palette(el);
    const st = studio(o.preset, pal);
    const shape = o.shape in SHAPES ? o.shape : 'sphere';
    const base = { x: Number(o.x), y: Number(o.y), size: clamp(Number(o.size) || 0.62, 0.05, 1.6), liquid: clamp(Number(o.liquid), 0, 1.5) };
    const shadow = o.shadow != null && o.shadow !== '' ? clamp(Number(o.shadow)) : st.shadow;
    // without a GPU the metal draws at 0.75 unless a scale is given: on the CPU that halves its cost, and at the
    // frame size the scaled-up canvas looks the same (its edges and the sign are soft already)
    const auto = o.scale == null || o.scale === '';
    const scale = auto ? (softwareGL() ? 0.75 : 1) : clamp(Number(o.scale) || 1, 0.25, 2);
    const layer = lookLayer(el, { name: 'liquid-metal', scale, alpha: true, fallback: () => fallback(el, { ...base, shape }, { ...st, shadow }) });
    if (!layer) {
      fallback(el, { ...base, shape }, { ...st, shadow });
      register(el, { look: 'liquid-metal', gl: false, preset: st.kind, box: [el.clientWidth, el.clientHeight], note: 'no WebGL: drew a still chrome sphere' });
      return { duration: 0, update() {} };
    }
    const signC = await signCanvas(el, o);
    const defs = { SHAPE: SHAPES[shape] };
    if (signC) defs.SIGN = 1;
    if (st.cards) defs.CARDS = 1;
    const prog = layer.program(FRAG, defs);
    const sign = signC ? layer.texture(signC, { mips: true }) : null;
    // the cost check estimates is the one without a GPU: at the size it would draw there
    const k = auto ? 0.75 / scale : 1;
    register(el, { look: 'liquid-metal', gl: true, preset: st.kind, box: layer.box,
      passes: [{ kind: shape === 'sphere' ? 'sphere' : 'march', w: Math.round(layer.W * k), h: Math.round(layer.H * k) }] });
    const grow = Math.max(0, Number(o.in) || 0);
    const E = ease('premium');
    const draw = (lt) => {
      const v = keyed(base, o.keys, lt);
      const tt = Math.max(0, lt);
      const g = grow > 0 ? E(clamp(lt / grow)) : 1;
      const size = v.size * (0.88 + 0.12 * g);
      layer.draw(prog, {
        uT: tt, uSeed: Number(o.seed) || 0, uCenter: [v.x, v.y], uSize: size, uTanH: TAN_SIL / size,
        uLiquid: v.liquid, uFlowT: tt * 0.55 * (Number(o.speed) || 0), uTurn: turn((tt * (Number(o.turn) || 0) * Math.PI) / 180),
        uFade: g, uShadow: shadow, uZenith: st.zenith, uHorizon: st.horizon, uGround: st.ground, uFloor: st.floor,
        uStripA: st.stripA, uStripB: st.stripB, uStripC: st.stripC, uPanel: st.panel, uSpec: st.spec, uTint: st.tint,
        uInk: st.ink, ...(sign ? { uText: sign } : {}), uExposure: st.exposure,
        uRing: ring(tt * 0.55 * (Number(o.speed) || 0)),
      });
    };
    return {
      duration: grow,
      update(lt) { if (onScreen(el)) draw(lt); },
    };
  },
});

export default LiquidMetal;

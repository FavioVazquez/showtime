// tilt-shift: a sharp band across an image with a blur that grows away from it, like a tilted lens or a
// miniature. The quiet use: point at one region of a screenshot or a photo without boxes or arrows.
// A WebGL look (runtime/effects/gl.js): two separable 13-tap blur passes at reduced size, then the sharp
// picture and the blur are mixed at full size, so the band stays crisp. Without WebGL: a CSS version.
//
//   <div data-st="tilt-shift" data-src="shots/app.png" data-preset="focus" data-y="0.62"></div>
//   <div data-st="tilt-shift" data-src="media/town.jpg"
//        data-keys='[{"at":0.5,"dur":2,"y":0.4,"ease":"sine.inOut"}]'></div>       (the band moves)
//
// Presets: miniature (narrow band, strong blur, richer colour), focus (wide band, soft blur, the rest
// dimmed a little), progressive (sharp below the band, blur growing toward the top edge). Options
// override the preset: y (band centre, 0 top .. 1 bottom), angle (degrees), width (half-height of the
// sharp band, fraction of the frame height), feather (how far the blur takes to reach full), blur (px
// at the frame size, a gaussian sigma), side (both | top | bottom), dim (0-0.6), saturate, contrast,
// drift (zoom per second), focus [x%, y%] (cover-fit centre), keys [{at, dur, ease, y, angle, width,
// feather, blur, dim}], scale (the largest size the blur passes run at, default 0.35; strong blurs run
// smaller on their own).
import { define, clamp } from './core.js';
import { lookLayer, keyed, findSource, sourceReady, sourceSize, coverFit, register, onScreen } from '../effects/gl.js';

const PRESETS = {
  miniature: { y: 0.56, angle: 0, width: 0.07, feather: 0.26, blur: 11, dim: 0, saturate: 1.28, contrast: 1.07, side: 'both' },
  focus: { y: 0.5, angle: 0, width: 0.15, feather: 0.2, blur: 7, dim: 0.22, saturate: 0.85, contrast: 1, side: 'both' },
  progressive: { y: 0.62, angle: 0, width: 0.0, feather: 0.55, blur: 12, dim: 0, saturate: 1, contrast: 1, side: 'top' },
};
const SIDES = { both: 0, top: 1, bottom: 2 };
// the blur taps: 13 at sigma * 2.5 / 6 apart, so a pass never steps more than 1.5 of its own pixels
const MAX_SIGMA_PX = 3.6;

// SIDE (0 both, 1 top, 2 bottom) and FIRST (the pass that reads the picture) are #defines: variants are
// compiled apart, never branched per pixel (a CPU renderer would pay for every branch)
const MASK = `
uniform float uY;
uniform vec2 uNormal;
uniform float uWidth;
uniform float uFeather;
uniform float uAspect;
// 0 inside the sharp band, 1 where the blur is full
float ramp(vec2 uv) {
  float d = dot(vec2((uv.x - 0.5) * uAspect, uv.y - uY), uNormal);
#if SIDE == 1
  d = max(0.0, -d);
#elif SIDE == 2
  d = max(0.0, d);
#else
  d = abs(d);
#endif
  float r = clamp((d - uWidth) / max(0.001, uFeather), 0.0, 1.0);
  return r * r * (3.0 - 2.0 * r);
}
`;

// 13 gaussian taps sigma * 2.5 / 6 apart: the weights are fixed numbers, written out
const TAPS = (() => {
  const w = [];
  for (let i = -6; i <= 6; i++) w.push(Math.exp(-0.5 * (i * 0.41667) ** 2));
  const sum = w.reduce((a, b) => a + b, 0);
  return w.map((x, k) => `  acc += ${(x / sum).toFixed(6)} * TAP(${(k - 6).toFixed(1)});`).join('\n');
})();

const BLUR = MASK + `
uniform sampler2D uSrc;
uniform vec2 uDir;
uniform float uSigma;
uniform vec4 uFit;
uniform float uZoom;
void main() {
  float stepPx = uSigma * ramp(vUv) * 2.5 / 6.0;
  vec2 st = uDir * stepPx / uRes;
  vec3 acc = vec3(0.0);
#ifdef FIRST
  // the picture, prefiltered by its mipmaps to the tap spacing, covering the box with the drift applied
  float bias = log2(max(1.0, stepPx));
  vec2 base = ((vUv - 0.5) / uZoom) * uFit.xy + 0.5 + uFit.zw;
  vec2 stp = st / uZoom * uFit.xy;
#define TAP(k) texture2D(uSrc, base + stp * k, bias).rgb
#else
#define TAP(k) texture2D(uSrc, vUv + st * k).rgb
#endif
${TAPS}
  gl_FragColor = vec4(acc, 1.0);
}`;

const COMPOSE = MASK + `
uniform sampler2D uSrc;
uniform sampler2D uBlur;
uniform vec4 uFit;
uniform float uZoom;
uniform float uSigma;
uniform float uPassScale;
uniform float uDim;
uniform float uSat;
uniform float uCon;
void main() {
  vec2 q = (vUv - 0.5) / uZoom + 0.5;
  q = (q - 0.5) * uFit.xy + 0.5 + uFit.zw;
  vec3 sharp = texture2D(uSrc, q).rgb;
  vec3 soft = texture2D(uBlur, vUv).rgb;
  float r = ramp(vUv);
  // below about one blur-pass pixel of blur the sharp picture leads, so the band's edge has no step
  float m = clamp(uSigma * r * uPassScale / 1.2, 0.0, 1.0);
  vec3 c = mix(sharp, soft, m);
  float g = luma(c);
  c = mix(vec3(g), c, mix(1.0, uSat, r));
  c = (c - 0.5) * mix(1.0, uCon, r) + 0.5;
  c *= 1.0 - uDim * r;
  gl_FragColor = vec4(dither(clamp(c, 0.0, 1.0)), 1.0);
}`;

function fallback(el, o, src) {
  // the picture sharp, and over it a blurred copy shown only outside the band (a CSS mask)
  el.classList.add('st-look-fallback');
  src.classList.add('st-look-src');
  const copy = src.tagName === 'IMG' ? src.cloneNode() : document.createElement('img');
  if (src.tagName === 'CANVAS') { try { copy.src = src.toDataURL(); } catch { /* tainted: no blur */ } }
  copy.classList.add('st-look-src', 'st-ts-blur');
  copy.style.filter = `blur(${Math.round(o.blur)}px) saturate(${o.saturate}) brightness(${(1 - o.dim).toFixed(2)})`;
  const a = o.y * 100, w = o.width * 100, f = Math.max(1, o.feather * 100);
  const clear = 'rgb(0 0 0 / 0)', full = 'rgb(0 0 0 / 1)';
  const stops = o.side === 'top' ? `${full} 0%, ${full} ${a - w - f}%, ${clear} ${a - w}%, ${clear} 100%`
    : o.side === 'bottom' ? `${clear} 0%, ${clear} ${a + w}%, ${full} ${a + w + f}%, ${full} 100%`
      : `${full} 0%, ${full} ${a - w - f}%, ${clear} ${a - w}%, ${clear} ${a + w}%, ${full} ${a + w + f}%, ${full} 100%`;
  const mask = `linear-gradient(${180 + o.angle}deg, ${stops})`;
  copy.style.maskImage = mask;
  copy.style.webkitMaskImage = mask;
  src.after(copy);
}

export const TiltShift = define({
  name: 'tilt-shift',
  defaults: { at: 0, preset: 'miniature', src: '', y: null, angle: null, width: null, feather: null, blur: null, side: null, dim: null, saturate: null, contrast: null, drift: 0.006, focus: null, keys: null, scale: 0.35 },
  async setup(el, o) {
    const P = { ...(PRESETS[o.preset] || PRESETS.miniature) };
    for (const k of Object.keys(P)) if (o[k] != null && o[k] !== '') P[k] = k === 'side' ? String(o[k]) : Number(o[k]);
    if (!(P.side in SIDES)) P.side = 'both';
    const src = findSource(el, o.src);
    if (!src) throw new Error('tilt-shift needs a picture: data-src="image.jpg", or an <img> or <canvas> inside the element');
    await sourceReady(src);
    const layer = lookLayer(el, { name: 'tilt-shift', scale: 1, fallback: () => { src.classList.remove('st-look-hidden'); fallback(el, P, src); } });
    if (!layer) {
      fallback(el, P, src);
      register(el, { look: 'tilt-shift', gl: false, preset: o.preset, box: [el.clientWidth, el.clientHeight], note: 'no WebGL: drew the CSS blur' });
      return { duration: 0, update() {} };
    }
    src.classList.add('st-look-src', 'st-look-hidden');
    const side = SIDES[P.side];
    const firstProg = layer.program(BLUR, { SIDE: side, FIRST: 1 });
    const blurProg = layer.program(BLUR, { SIDE: side });
    const compProg = layer.program(COMPOSE, { SIDE: side });
    const tex = layer.texture(src, { mips: src.tagName === 'IMG' });
    const live = src.tagName === 'CANVAS';
    // the blur passes run at the largest scale that keeps their taps 1.5 px apart or closer
    const sigmaMax = Math.max(P.blur, ...((Array.isArray(o.keys) ? o.keys : []).map((k) => Number(k && k.blur) || 0)));
    const k = layer.dpr;
    const passScale = clamp(Math.min(Number(o.scale) || 0.35, MAX_SIGMA_PX / Math.max(0.5, sigmaMax * k)), 0.08, 1);
    const bw = Math.max(2, Math.round(layer.W * passScale)), bh = Math.max(2, Math.round(layer.H * passScale));
    const A = layer.target(bw, bh), B = layer.target(bw, bh);
    const fit = coverFit(...sourceSize(src), layer.W, layer.H, Array.isArray(o.focus) ? o.focus : [50, 50]);
    register(el, { look: 'tilt-shift', gl: true, preset: o.preset, box: layer.box,
      passes: [{ kind: 'blur13', w: bw, h: bh }, { kind: 'blur13', w: bw, h: bh }, { kind: 'tap2', w: layer.W, h: layer.H }] });
    el.dataset.stBlurScale = passScale.toFixed(3);
    const draw = (lt) => {
      const v = keyed(P, o.keys, lt);
      const tt = Math.max(0, lt);
      const zoom = 1 + Math.min(0.12, Math.max(0, Number(o.drift) || 0) * tt);
      const a = (v.angle * Math.PI) / 180;
      const mask = { uY: v.y, uNormal: [-Math.sin(a), Math.cos(a)], uWidth: v.width, uFeather: v.feather, uAspect: layer.W / layer.H };
      const sigma = v.blur * k * passScale;   // in blur-pass pixels
      layer.draw(firstProg, { ...mask, uSrc: tex, uDir: [1, 0], uSigma: sigma, uFit: fit, uZoom: zoom }, A);
      layer.draw(blurProg, { ...mask, uSrc: A, uDir: [0, 1], uSigma: sigma }, B);
      layer.draw(compProg, { ...mask, uSrc: tex, uBlur: B, uFit: fit, uZoom: zoom, uSigma: v.blur * k, uPassScale: passScale,
        uDim: v.dim, uSat: v.saturate, uCon: v.contrast });
    };
    return {
      duration: 0,
      update(lt) {
        if (!onScreen(el)) return undefined;
        if (!live) { draw(lt); return undefined; }
        return Promise.resolve().then(() => { tex.update(); draw(lt); });
      },
    };
  },
});

export default TiltShift;

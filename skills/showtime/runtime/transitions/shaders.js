// showtime GLSL transition shaders (WebGL 1, GLSL ES 1.00). Original work.
//
// Every shader defines `vec4 blend(vec2 uv)` and may use:
//   srcA(uv) / srcB(uv)   outgoing / incoming scene (edge-clamped)
//   uP        eased progress 0..1        uR   raw (linear) progress 0..1
//   uRes      frame size in px           uAspect  width / height
//   uAccent / uAccent2    theme accent colours (linear-ish 0..1 RGB)
//   uSeed     per-transition seed        uA, uB   shader parameters (see PARAMS)
//   noise(p), fbm(p), rnd(p)             value noise, 5-octave fractal noise, hash
// The compositor draws a fullscreen quad; uv (0,0) is the top-left of the frame.

export const HEADER = `
precision highp float;
varying vec2 vUv;
uniform sampler2D uFrom;
uniform sampler2D uTo;
uniform float uP;
uniform float uR;
uniform vec2 uRes;
uniform float uAspect;
uniform vec3 uAccent;
uniform vec3 uAccent2;
uniform float uSeed;
uniform float uA;
uniform float uB;

vec4 srcA(vec2 uv) { return texture2D(uFrom, clamp(uv, vec2(0.0005), vec2(0.9995))); }
vec4 srcB(vec2 uv) { return texture2D(uTo, clamp(uv, vec2(0.0005), vec2(0.9995))); }

// hash: folds the input through fract() with odd constants; no trig, stable on every GPU
float rnd(vec2 p) {
  vec3 q = fract(vec3(p.xyx) * vec3(0.1127, 0.1393, 0.1219) + uSeed * 0.0137);
  q += dot(q, q.zyx + 41.73);
  return fract((q.x + q.z) * q.y);
}
float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
  float a = rnd(i), b = rnd(i + vec2(1.0, 0.0)), c = rnd(i + vec2(0.0, 1.0)), d = rnd(i + vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
float fbm(vec2 p) {
  float s = 0.0, amp = 0.52;
  mat2 turn = mat2(0.877, 0.479, -0.479, 0.877); // ~28.6 degrees per octave hides the lattice
  for (int i = 0; i < 5; i++) { s += amp * noise(p); p = turn * p * 2.07 + 17.3; amp *= 0.5; }
  return s;
}
vec3 filmic(vec3 x) { return clamp((x * (2.4 * x + 0.04)) / (x * (2.3 * x + 0.62) + 0.16), 0.0, 1.0); }
`;

export const SHADERS = {
  // Ink bloom: a slow fractal field decides where the new scene seeps in; both images are
  // pushed along the field, and the moving front glows in the accent colour.
  'domain-warp': `
vec4 blend(vec2 uv) {
  vec2 p = vec2(uv.x * uAspect, uv.y) * 2.6;
  vec2 q = vec2(fbm(p + vec2(0.0, 1.7)), fbm(p + vec2(5.2, -2.1)));
  vec2 r = vec2(fbm(p + 3.6 * q + vec2(1.9, 8.3)), fbm(p + 3.6 * q + vec2(8.1, 2.4)));
  float n = fbm(p + 2.8 * r);
  float front = uP * 1.25 - 0.12;
  float m = smoothstep(front - 0.07, front + 0.07, n);
  vec2 push = (r - 0.5) * 0.18;
  vec4 a = srcA(uv + push * uP);
  vec4 b = srcB(uv - push * (1.0 - uP));
  vec4 col = mix(b, a, m);
  float edge = 1.0 - smoothstep(0.0, 0.045, abs(n - front));
  vec3 glow = mix(uAccent * 0.45, mix(uAccent, vec3(1.0), 0.35), edge);
  col.rgb += glow * edge * edge * 0.9 * (1.0 - smoothstep(0.85, 1.0, uP)) * smoothstep(0.0, 0.06, uP);
  return col;
}`,

  // Burn-through: ridged noise sets a jagged ignition front; a hot rim ramps from ember to
  // white, with sparks just ahead of the front and charring just behind it.
  'ridged-burn': `
float ridge(vec2 p) {
  // value noise's creases follow its square lattice: turn the domain, warp it gently and turn each
  // octave again, so the burn front reads as torn paper rather than a grid of glowing cells
  mat2 turn = mat2(0.877, 0.479, -0.479, 0.877);
  p = mat2(0.788, 0.616, -0.616, 0.788) * p;
  p += (vec2(noise(p * 0.8 + 3.1), noise(p * 0.8 + 7.7)) - 0.5) * 0.8;
  float s = 0.0, amp = 0.55;
  for (int i = 0; i < 5; i++) { float n = 1.0 - abs(noise(p) * 2.0 - 1.0); s += amp * n * n; p = turn * p * 2.13 + 9.1; amp *= 0.48; }
  return s;
}
vec4 blend(vec2 uv) {
  vec2 p = vec2(uv.x * uAspect, uv.y) * 3.4;
  float n = ridge(p) * 0.75 + (1.0 - uv.y) * 0.25 + uA * (uv.x - 0.5);
  float front = uP * 1.6 - 0.3;
  float d = n - front;
  float burnt = 1.0 - smoothstep(-0.035, 0.035, d);
  vec4 a = srcA(uv);
  vec4 b = srcB(uv);
  float char = (1.0 - smoothstep(0.0, 0.16, d)) * (1.0 - burnt);
  a.rgb *= 1.0 - 0.75 * char;
  float heat = exp(-abs(d) * 22.0) * step(-0.02, d);
  vec3 hot = mix(uAccent * 0.6, mix(uAccent, vec3(1.0, 0.95, 0.85), 0.55), heat);
  vec4 col = mix(a, b, burnt);
  col.rgb += hot * heat * 2.2 * (1.0 - smoothstep(0.9, 1.0, uP));
  // embers: round points, one per 9 px cell at most (thresholded value noise drew square blocks)
  vec2 sq = uv * uRes / 9.0 + uR * 40.0;
  vec2 sc = floor(sq);
  vec2 so = vec2(rnd(sc + 3.1), rnd(sc + 7.3)) * 0.5 + 0.25;
  float spark = step(0.965, rnd(sc)) * (1.0 - smoothstep(0.08, 0.24, length(fract(sq) - so))) * exp(-abs(d - 0.05) * 30.0);
  col.rgb += vec3(1.0, 0.85, 0.6) * spark * 1.5 * (1.0 - uP);
  return col;
}`,

  // Iris: an anti-aliased circle opens from a point (uA, uB in 0..1, default centre),
  // trailed by a thin accent rim and two fading echoes; the incoming scene settles from 5 % zoom.
  'sdf-iris': `
vec4 blend(vec2 uv) {
  vec2 c = vec2(uA < 0.0 ? 0.5 : uA, uB < 0.0 ? 0.5 : uB);
  vec2 d = (uv - c) * vec2(uAspect, 1.0);
  float far = length(max(abs(c - 0.5) + 0.5, vec2(0.0)) * vec2(uAspect, 1.0));
  float rad = uP * far * 1.02;
  float dist = length(d) - rad;
  float aa = 1.5 / uRes.y;
  float inside = 1.0 - smoothstep(-aa, aa, dist);
  float z = mix(1.05, 1.0, uP);
  vec4 b = srcB(c + (uv - c) / z);
  vec4 col = mix(srcA(uv), b, inside);
  float life = sin(3.14159 * uP);
  float rim = exp(-abs(dist) * uRes.y * 0.09) * life;
  float echo = exp(-abs(dist + 0.035) * uRes.y * 0.05) * 0.45 + exp(-abs(dist + 0.075) * uRes.y * 0.04) * 0.2;
  col.rgb += mix(uAccent, vec3(1.0), 0.25) * (rim * 0.9 + echo * life * (1.0 - inside) * 0.6);
  return col;
}`,

  // Ripple: circular waves travel out from the centre and bend both images; the new scene is
  // revealed behind the leading wave.
  'ripple': `
vec4 blend(vec2 uv) {
  vec2 d = (uv - 0.5) * vec2(uAspect, 1.0);
  float r = length(d);
  vec2 dir = r > 0.0001 ? d / r : vec2(0.0);
  float env = sin(3.14159 * uP);
  float wave = sin(r * 38.0 - uR * 26.0) * exp(-r * 1.6);
  vec2 off = dir * wave * 0.028 * (uA > 0.0 ? uA : 1.0) * env / vec2(uAspect, 1.0);
  float reveal = 1.0 - smoothstep(uP * 1.6 - 0.5, uP * 1.6 - 0.3, r);
  vec4 col = mix(srcA(uv + off), srcB(uv - off * 0.7), reveal);
  col.rgb += uAccent * max(wave, 0.0) * env * 0.12;
  return col;
}`,

  // Chromatic split: the outgoing frame tears into red / green / blue copies that fly apart
  // from the centre; the incoming frame arrives the same way in reverse and locks together.
  'chromatic-split': `
vec3 split(vec2 uv, float k, bool incoming) {
  vec2 d = uv - 0.5;
  vec2 o = d * k * 0.12 + vec2(k * 0.018, 0.0);
  if (incoming) return vec3(srcB(uv - o).r, srcB(uv).g, srcB(uv + o).b);
  return vec3(srcA(uv + o).r, srcA(uv).g, srcA(uv - o).b);
}
vec4 blend(vec2 uv) {
  float ka = smoothstep(0.0, 0.6, uP);
  float kb = 1.0 - smoothstep(0.4, 1.0, uP);
  float m = smoothstep(0.35, 0.65, uP);
  vec3 col = mix(split(uv, ka, false), split(uv, kb, true), m);
  col += uAccent2 * 0.08 * sin(3.14159 * uP);
  return vec4(col, 1.0);
}`,

  // Cross-zoom: a radial zoom blur that peaks mid-way while the scenes swap under it, with
  // slight per-channel scale for a lens fringe and an exposure bump at the peak.
  'cross-zoom': `
vec4 blend(vec2 uv) {
  float k = sin(3.14159 * uP);
  vec2 c = vec2(0.5);
  vec3 acc = vec3(0.0);
  float m = smoothstep(0.38, 0.62, uP);
  for (int i = 0; i < 16; i++) {
    float f = float(i) / 15.0;
    float s = 1.0 - f * 0.22 * k;
    vec2 u0 = c + (uv - c) * s;
    vec2 ur = c + (uv - c) * (s * (1.0 + 0.012 * k));
    vec2 ub = c + (uv - c) * (s * (1.0 - 0.012 * k));
    vec3 a = vec3(srcA(ur).r, srcA(u0).g, srcA(ub).b);
    vec3 b = vec3(srcB(ur).r, srcB(u0).g, srcB(ub).b);
    acc += mix(a, b, m);
  }
  vec3 col = acc / 16.0;
  col *= 1.0 + 0.35 * k * k;
  return vec4(col, 1.0);
}`,

  // Light leak: a warm, overexposed flare sweeps in from a corner (accent tinted), the
  // outgoing frame blooms toward white under a filmic curve, and the new scene appears as
  // the leak clears. uA = strength (default 1; 0.5 = half the flare and bloom).
  'light-leak': `
vec4 blend(vec2 uv) {
  float s = uA > 0.0 ? uA : 1.0;
  vec2 src = vec2(1.25 - uP * 0.5, -0.25 + uP * 0.3);
  vec2 d = (uv - src) * vec2(uAspect, 1.0);
  float leak = exp(-length(d) * mix(3.2, 1.2, sin(3.14159 * uP))) * smoothstep(0.0, 0.35, uP) * (1.0 - smoothstep(0.7, 1.0, uP));
  vec2 dd = (uv - vec2(1.0, 0.0)) * vec2(uAspect, 1.0);
  float streak = exp(-abs(dd.x + dd.y * 0.6) * 9.0) * 0.35 * sin(3.14159 * uP);
  leak *= s; streak *= s;
  vec3 tint = mix(uAccent, vec3(1.0, 0.78, 0.45), 0.5);
  float m = smoothstep(0.4, 0.72, uP);
  vec3 a = srcA(uv).rgb;
  vec3 b = srcB(uv).rgb;
  vec3 base = mix(a * (1.0 + 1.6 * leak), b, m);
  vec3 col = mix(base, filmic(base + tint * (leak * 1.7 + streak)), clamp(sin(3.14159 * uP) * 1.6 * s, 0.0, 1.0));
  return vec4(col, 1.0);
}`,

  // Pixel dissolve: the frame coarsens into blocks that flip to the new scene in a seeded
  // random order, then sharpens again. uA = peak block size as a fraction of the height.
  'pixel-dissolve': `
vec4 blend(vec2 uv) {
  float peak = uA > 0.0 ? uA : 0.045;
  float k = sin(3.14159 * uP);
  float cells = max(1.0, floor(1.0 / max(peak * k, 1.0 / uRes.y)));
  vec2 grid = vec2(cells * uAspect, cells);
  vec2 cell = floor(uv * grid);
  vec2 q = k > 0.02 ? (cell + 0.5) / grid : uv;
  float order = rnd(floor(uv * vec2(24.0 * uAspect, 24.0)));
  float flip = step(order, smoothstep(0.2, 0.8, uP));
  return mix(srcA(q), srcB(q), flip);
}`,

  // Flow morph: a noise flow field drags the outgoing frame forward and the incoming frame
  // backward while a soft noisy front hands one to the other. Organic, calm.
  'morph-warp': `
vec4 blend(vec2 uv) {
  vec2 p = vec2(uv.x * uAspect, uv.y) * 2.2;
  vec2 flow = vec2(fbm(p + vec2(3.1, 0.0)), fbm(p + vec2(0.0, 7.7))) - 0.5;
  float n = fbm(p * 1.3 + 11.0);
  float m = smoothstep(0.42, 0.58, n + uP * 1.2 - 0.6);
  vec4 a = srcA(uv + flow * 0.22 * uP);
  vec4 b = srcB(uv - flow * 0.22 * (1.0 - uP));
  return mix(a, b, m);
}`,

  // Whip blur: both scenes ride one strip sideways (uA = direction, 1 left / -1 right) under a
  // heavy horizontal smear that peaks mid-move.
  'whip-blur': `
vec4 blend(vec2 uv) {
  float dir = uA == 0.0 ? 1.0 : sign(uA);
  float x = uP;
  float blur = sin(3.14159 * uR) * 0.075;
  vec3 acc = vec3(0.0);
  for (int i = 0; i < 14; i++) {
    float f = (float(i) / 13.0 - 0.5) * blur;
    float sx = uv.x + x * dir + f;
    vec3 c;
    if (dir > 0.0) c = sx < 1.0 ? srcA(vec2(sx, uv.y)).rgb : srcB(vec2(sx - 1.0, uv.y)).rgb;
    else c = sx > 0.0 ? srcA(vec2(sx, uv.y)).rgb : srcB(vec2(sx + 1.0, uv.y)).rgb;
    acc += c;
  }
  return vec4(acc / 14.0, 1.0);
}`,

  // Signal glitch: stepped (frame-quantised) row tears, block jumps and an RGB shift that
  // peak at the cut; the swap to the new scene happens inside the noise.
  'signal-glitch': `
vec4 blend(vec2 uv) {
  float amt = sin(3.14159 * uR);
  float step1 = floor(uR * 14.0);
  float rows = floor(uv.y * 48.0);
  float tear = (rnd(vec2(rows, step1)) - 0.5) * 0.12 * amt * step(0.55, rnd(vec2(rows * 0.7, step1 + 3.0)));
  vec2 blk = floor(uv * vec2(10.0, 7.0));
  float jump = step(0.84, rnd(blk + step1 * 1.7)) * amt;
  vec2 u = uv + vec2(tear, 0.0) + (vec2(rnd(blk + 9.1), rnd(blk + 4.3)) - 0.5) * 0.08 * jump;
  float shift = 0.02 * amt;
  bool to = uR > 0.5;
  vec3 col = to ? vec3(srcB(u + vec2(shift, 0.0)).r, srcB(u).g, srcB(u - vec2(shift, 0.0)).b)
                : vec3(srcA(u + vec2(shift, 0.0)).r, srcA(u).g, srcA(u - vec2(shift, 0.0)).b);
  col *= 1.0 - 0.18 * amt * step(0.5, fract(uv.y * uRes.y * 0.25));
  col = mix(col, floor(col * 6.0) / 6.0, amt * 0.5);
  return vec4(col, 1.0);
}`,
};

// Parameter meaning per shader, for docs and for the compositor's defaults.
export const PARAMS = {
  'sdf-iris': { a: 'centre x (0..1, default 0.5)', b: 'centre y (0..1, default 0.5)', defaults: { a: -1, b: -1 } },
  'ridged-burn': { a: 'sideways bias of the burn (-1..1)', defaults: { a: 0.35 } },
  'pixel-dissolve': { a: 'peak block size, fraction of height (default 0.045)', defaults: { a: 0.045 } },
  'whip-blur': { a: 'direction: 1 = leftward, -1 = rightward', defaults: { a: 1 } },
  ripple: { a: 'wave strength (default 1; 0.6 = 40 % less displacement)', defaults: { a: 1 } },
  'light-leak': { a: 'strength (default 1; 0.5 = half the flare and bloom)', defaults: { a: 1 } },
};

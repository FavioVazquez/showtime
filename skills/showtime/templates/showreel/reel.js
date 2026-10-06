// reel.js: small, deterministic techniques for the showreel template (no dependencies, original code).
// Every draw is a pure function of the scene's local time, so frames match in any order on any machine
// (references/stage-api.md, "The one rule"). Recipes: references/motion-craft.md, section 11.
//
//   shaderLayer(canvas, frag)   a full-frame WebGL fragment shader (u_res, u_t and your own uniforms)
//   burst(canvas, opts)         a particle burst on a beat: closed-form ballistic paths with drag, drawn as streaks
//   tunnel(canvas, opts)        a fly-through of square rings (zoom-through into the next shot)
//   chart(canvas, opts)         live data: bars spring up, a line draws on with a head, a counter rolls to a number
//   morph(canvas, opts)         one filled shape morphing through a list of outlines on the beats, turning
//   spiro(canvas, opts)         a generative line drawing (a hypotrochoid) drawing itself on with a glowing head
//   halftone(canvas, opts)      a dot field: a lit sphere in halftone dots, its light swinging round, ripples outside
//   localTime(id, t)            seconds since the scene <section id=...> started (its resolved clip window)

/** Seconds since the clip `id` started (negative before it, past its length after); null when there is no such clip. */
export function localTime(id, t) {
  const c = (ST.clips() || []).find((x) => x.id === id);
  return c ? t - c.start : null;
}

/** Whether clip `id` is on screen at video time t: ST.clips() windows are frame-exact, the frames the stage
 * shows the scene on (end null: it runs to the end of the video). Gate drawing on this, never on times typed again. */
export function active(id, t) {
  const c = (ST.clips() || []).find((x) => x.id === id);
  return !!c && t >= c.start && (c.end == null || t < c.end);
}

const VERT = 'attribute vec2 p; void main() { gl_Position = vec4(p, 0.0, 1.0); }';

// canvases are sized from the stage: a scene that has not started yet is display:none and measures 0
function stageSize() {
  const st = document.querySelector('.stage') || document.body;
  const r = st.getBoundingClientRect();
  return [Math.round(r.width) || (ST.cfg && ST.cfg.width) || 1920, Math.round(r.height) || (ST.cfg && ST.cfg.height) || 1080];
}

/**
 * A full-frame fragment shader on `canvas` (the stage's size times `scale`). frag gets
 * `uniform vec2 u_res; uniform float u_t;` plus any floats or vec3s you pass to draw(t, {name: value}).
 * preserveDrawingBuffer keeps the frame for the renderer's screenshot.
 */
export function shaderLayer(canvas, frag, { scale = 1 } = {}) {
  const [w, h] = stageSize();
  canvas.width = Math.max(2, Math.round(w * scale));
  canvas.height = Math.max(2, Math.round(h * scale));
  const gl = canvas.getContext('webgl', { preserveDrawingBuffer: true, antialias: false, premultipliedAlpha: false });
  if (!gl) throw new Error('WebGL is not available: render with --gpu auto (the default), or replace this layer with a CSS gradient');
  const sh = (type, src) => {
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error('shader: ' + gl.getShaderInfoLog(s));
    return s;
  };
  const prog = gl.createProgram();
  gl.attachShader(prog, sh(gl.VERTEX_SHADER, VERT));
  gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, 'precision highp float;\nuniform vec2 u_res;\nuniform float u_t;\n' + frag));
  gl.linkProgram(prog);
  gl.useProgram(prog);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'p');
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const uni = {};
  const u = (name) => (name in uni ? uni[name] : (uni[name] = gl.getUniformLocation(prog, name)));
  return {
    draw(t, values = {}) {
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(u('u_res'), canvas.width, canvas.height);
      gl.uniform1f(u('u_t'), t);
      for (const [k, v] of Object.entries(values)) {
        if (Array.isArray(v)) gl.uniform3f(u(k), v[0], v[1], v[2]);
        else gl.uniform1f(u(k), v);
      }
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    },
  };
}

function ctx2d(canvas) {
  [canvas.width, canvas.height] = stageSize();
  return canvas.getContext('2d');
}

/**
 * A particle burst: `n` particles leave the centre at τ = 0 (the beat), slow down with drag `k` and swirl.
 * Positions are closed-form (x = v (1 - e^-kτ) / k), so any frame can be drawn alone. colors: CSS colours.
 */
export function burst(canvas, { n = 900, seed = 'burst', colors = ['#ff4fd8', '#29e7ff', '#ffffff'], k = 2.6, swirl = 0.9 } = {}) {
  const g = ctx2d(canvas);
  const W = canvas.width, H = canvas.height, S = Math.min(W, H);
  const r = ST.rand(seed);
  const P = Array.from({ length: n }, () => ({
    a: r() * Math.PI * 2, v: S * (0.35 + 1.25 * Math.pow(r(), 1.6)), w: 2 + r() * 5,
    c: colors[Math.floor(r() * colors.length)], s: r.sign() * (0.4 + r() * swirl), life: 1.7 + r() * 1.6,
  }));
  const pos = (p, tau) => {
    const d = p.v * (1 - Math.exp(-k * tau)) / k;
    const a = p.a + p.s * (1 - Math.exp(-1.2 * tau));
    return [W / 2 + Math.cos(a) * d, H / 2 + Math.sin(a) * d * (W >= H ? 0.82 : 1.35)];   // spread to the frame's shape
  };
  return {
    draw(tau) {
      g.globalCompositeOperation = 'source-over';
      g.clearRect(0, 0, W, H);
      if (tau < 0) return;
      // the flash of the hit: a soft core that fades in 0.25 s (small: under a quarter of the frame)
      const core = Math.max(0, 1 - tau / 0.25);
      if (core > 0) {
        const rg = g.createRadialGradient(W / 2, H / 2, 0, W / 2, H / 2, S * 0.28);
        rg.addColorStop(0, `rgba(255,255,255,${0.9 * core})`);
        rg.addColorStop(1, 'rgba(255,255,255,0)');
        g.fillStyle = rg;
        g.fillRect(0, 0, W, H);
      }
      g.globalCompositeOperation = 'lighter';
      g.lineCap = 'round';
      for (const p of P) {
        const fade = Math.max(0, 1 - tau / p.life);
        if (fade <= 0) continue;
        const [x0, y0] = pos(p, Math.max(0, tau - 0.07));
        const [x1, y1] = pos(p, tau);
        g.strokeStyle = p.c;
        g.globalAlpha = fade;
        g.lineWidth = p.w * (0.6 + fade);
        g.beginPath();
        g.moveTo(x0, y0);
        g.lineTo(x1 + 0.01, y1);
        g.stroke();
      }
      g.globalAlpha = 1;
    },
  };
}

/** A fly-through: square rings rush toward the camera; `speed` rings per second, alternating two colours. `into`: a colour
 * that opens from the centre over the last 0.3 s of a `dur`-second shot, so the cut lands on the next shot's ground. */
export function tunnel(canvas, { rings = 22, speed = 2.2, colors = ['#29e7ff', '#ff4fd8'], ground = '#05060f', into = null, dur = 1 } = {}) {
  const g = ctx2d(canvas);
  const W = canvas.width, H = canvas.height, S = Math.min(W, H);
  const [ax, ay] = W >= H ? [1, 0.62] : [0.62, 1];   // the rings take the frame's shape (wide or tall)
  return {
    draw(tau, twist = 0) {
      g.fillStyle = ground;
      g.fillRect(0, 0, W, H);
      g.save();
      g.translate(W / 2, H / 2);
      for (let i = rings - 1; i >= 0; i--) {
        const z = ((i - tau * speed) % rings + rings) % rings / rings + 0.02;   // 0 (near) .. 1 (far)
        const s = (S * 0.09) / z;
        if (s > Math.max(W, H) * 1.6 || s < S * 0.06) continue;   // far rings thinner than ~2 px only make moire
        const idx = Math.floor(i - tau * speed + 1e6);
        g.save();
        g.rotate(twist * (1 - z) + z * 0.6);
        g.globalAlpha = Math.min(1, (1 - z) * 1.6);
        g.strokeStyle = colors[((idx % colors.length) + colors.length) % colors.length];
        g.lineWidth = Math.max(1, s * 0.035);
        g.strokeRect(-s * ax, -s * ay, s * 2 * ax, s * 2 * ay);
        g.restore();
      }
      // into: the next shot's ground opens from the centre over the last 0.3 s (a match into the next shot)
      const k = into ? Math.max(0, Math.min(1, (tau - (dur - 0.3)) / 0.3)) : 0;
      if (k > 0) {
        const e = k * k * (3 - 2 * k), w = (S * 0.12 * ax + (W - S * 0.12 * ax) * e) / 2, h = (S * 0.12 * ay + (H - S * 0.12 * ay) * e) / 2;
        g.globalAlpha = 1;
        g.fillStyle = into;
        g.fillRect(-w, -h, w * 2, h * 2);
      }
      g.restore();
      g.globalAlpha = 1;
    },
  };
}

const TAU = Math.PI * 2;
const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);
const outCubic = (p) => 1 - Math.pow(1 - clamp01(p), 3);
const inOutCubic = (p) => { p = clamp01(p); return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2; };
// a damped spring from 0 to 1 (overshoots once, then settles): p = time over the move's length
const spring = (p) => (p <= 0 ? 0 : 1 - Math.exp(-6 * p) * Math.cos(9 * p));

/**
 * Live data: `bars` values (0..1) spring up one after another, a line through `line` values draws on with a
 * head, a ring gauge closes and a counter rolls like an odometer to `value`, all landed by `land` seconds.
 * ground/ink/accent: CSS colours; font: the counter's face (a family the page has loaded). Drawn on the canvas,
 * the number and the label are texture, not copy (put a figure the viewer must read in the DOM instead).
 */
export function chart(canvas, { bars = [0.28, 0.36, 0.31, 0.45, 0.41, 0.53, 0.49, 0.63, 0.58, 0.72, 0.69, 0.92],
  line = null, value = 900, ground = '#f1ede4', ink = '#05060f', accent = '#ff3b30', font = 'Anton',
  label = 'INDEX', land = 1.2 } = {}) {
  const g = ctx2d(canvas);
  const W = canvas.width, H = canvas.height, S = Math.min(W, H), tall = H > W;
  const L = line || bars.map((v, i) => Math.min(0.98, v * 0.8 + 0.12 + i * 0.006));
  // wide: the chart on the left, the counter on the right, the label over the chart; tall: the counter on top, the
  // label and the chart under it (inside the vertical safe box, clear of the shot tag and the platform UI)
  const [x0, x1, base, top] = tall ? [W * 0.1, W * 0.9, H * 0.73, H * 0.64] : [W * 0.08, W * 0.6, H * 0.84, H * 0.34];
  const [cx, cy, size] = tall ? [W * 0.5, H * 0.47, S * 0.36] : [W * 0.8, H * 0.62, S * 0.3];
  const labelY = tall ? H * 0.615 : top - H * 0.07;
  const slot = (x1 - x0) / bars.length;
  const bx = (i) => x0 + slot * (i + 0.5);
  return {
    draw(tau) {
      g.fillStyle = ground;
      g.fillRect(0, 0, W, H);
      // a camera push the whole shot long, so the landed chart keeps moving
      g.save();
      const z = 1 + 0.06 * tau;
      g.translate(W * 0.5, H * 0.55);
      g.scale(z, z);
      g.translate(-W * 0.5, -H * 0.55);
      // grid: hairlines that draw out from the axis
      const gp = outCubic(tau / 0.35);
      g.fillStyle = ink;
      for (let k = 0; k <= 4; k++) {
        const y = base - (base - top) * (k / 4);
        g.globalAlpha = k === 0 ? 1 : 0.16;
        g.fillRect(x0, y - (k === 0 ? 1.5 : 0.5), (x1 - x0) * gp, k === 0 ? 3 : 1);
      }
      g.globalAlpha = 1;
      // bars: a spring each, staggered
      for (let i = 0; i < bars.length; i++) {
        const h = bars[i] * (base - top) * spring((tau - 0.08 - i * 0.045) / 0.55);
        if (h <= 0.5) continue;
        g.fillStyle = i === bars.length - 1 ? accent : ink;
        g.fillRect(bx(i) - slot * 0.3, base - h, slot * 0.6, h);
      }
      // the line, drawn on with a head
      const lp = inOutCubic((tau - 0.25) / (land - 0.25));
      if (lp > 0) {
        const pts = L.map((v, i) => [bx(i), base - v * (base - top) - S * 0.02]);
        const n = (pts.length - 1) * lp, whole = Math.floor(n), f = n - whole;
        const a = pts[whole], b = pts[Math.min(whole + 1, pts.length - 1)];
        const hx = a[0] + (b[0] - a[0]) * f, hy = a[1] + (b[1] - a[1]) * f;
        g.strokeStyle = accent;
        g.lineWidth = Math.max(2, S * 0.006);
        g.lineJoin = 'round';
        g.beginPath();
        g.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i <= whole; i++) g.lineTo(pts[i][0], pts[i][1]);
        g.lineTo(hx, hy);
        g.stroke();
        g.fillStyle = accent;
        g.beginPath();
        g.arc(hx, hy, S * 0.014 * (1 + 0.3 * Math.sin(tau * 18)), 0, TAU);
        g.fill();
      }
      // the counter: an odometer, each wheel turning only while the one below it passes 9 -> 0
      const v = value * outCubic((tau - 0.15) / (land - 0.15));
      const digits = String(Math.round(value)).length;
      g.font = size + "px '" + font + "', sans-serif";
      g.textBaseline = 'alphabetic';
      g.textAlign = 'center';
      const cell = g.measureText('0').width * 1.04;
      const left = cx - (cell * digits) / 2;
      g.save();
      g.beginPath();
      g.rect(left - cell * 0.2, cy - size * 0.95, cell * (digits + 0.4), size * 1.0);
      g.clip();
      g.fillStyle = ink;
      for (let i = 0; i < digits; i++) {
        const place = Math.pow(10, digits - 1 - i);
        const d = (v / place) % 10, whole = Math.floor(d);
        const frac = i === digits - 1 ? d - whole : clamp01(((v % place) / place - 0.9) * 10);
        const x = left + cell * (i + 0.5);
        g.fillText(String(whole % 10), x, cy - frac * size * 1.1);
        g.fillText(String((whole + 1) % 10), x, cy + (1 - frac) * size * 1.1);
      }
      g.restore();
      // a ring gauge closing round the counter
      const rp = outCubic((tau - 0.2) / land);
      g.strokeStyle = accent;
      g.lineWidth = S * 0.012;
      g.lineCap = 'round';
      g.beginPath();
      g.arc(cx, cy - size * 0.42, size * 0.95, -Math.PI / 2, -Math.PI / 2 + TAU * 0.999 * rp);
      g.stroke();
      // the label (texture)
      g.textAlign = 'left';
      g.fillStyle = ink;
      g.globalAlpha = outCubic(tau / 0.3);
      g.font = S * 0.05 + "px '" + font + "', sans-serif";
      g.fillText(label, x0, labelY);
      g.globalAlpha = 1;
      g.restore();
    },
  };
}

/** Outlines for morph(): r(theta) of a unit shape. */
export const SHAPES = {
  circle: () => 0.92,
  square: (a) => 0.8 / Math.max(Math.abs(Math.cos(a)), Math.abs(Math.sin(a))),
  star: (a) => 0.55 + 0.5 * Math.pow(Math.abs(Math.cos((a * 5) / 2)), 4),
  flower: (a) => 0.74 + 0.26 * Math.cos(a * 6),
};

/**
 * One filled shape that morphs through `steps` (names in SHAPES) every `every` seconds, eased, turning, with
 * outline echoes trailing it. color/echo/ground: CSS colours.
 */
export function morph(canvas, { steps = ['circle', 'star', 'square', 'flower'], every = 0.25, color = '#05060f',
  echo = '#2337ff', ground = '#d8ff3a', size = 0.34 } = {}) {
  const g = ctx2d(canvas);
  const W = canvas.width, H = canvas.height, R = Math.min(W, H) * size;
  const fns = steps.map((s) => SHAPES[s] || SHAPES.circle);
  const path = (tau, scale, turn) => {
    const k = Math.max(0, Math.floor(tau / every)), f = inOutCubic((tau - k * every) / (every * 0.7));
    const a = fns[Math.min(k, fns.length - 1)], b = fns[Math.min(k + 1, fns.length - 1)];
    g.beginPath();
    for (let i = 0; i <= 240; i++) {
      const th = (i / 240) * TAU;
      const r = R * scale * (a(th) * (1 - f) + b(th) * f);
      const x = W / 2 + Math.cos(th + turn) * r, y = H / 2 + Math.sin(th + turn) * r;
      if (i) g.lineTo(x, y); else g.moveTo(x, y);
    }
    g.closePath();
  };
  return {
    draw(tau) {
      g.fillStyle = ground;
      g.fillRect(0, 0, W, H);
      const turn = tau * 1.6;
      g.strokeStyle = echo;
      g.lineWidth = Math.max(2, R * 0.025);
      for (let e = 3; e >= 1; e--) { path(Math.max(0, tau - e * 0.05), 1 + e * 0.16, turn - e * 0.12); g.stroke(); }
      g.fillStyle = color;
      path(tau, 1, turn);
      g.fill();
    },
  };
}

/**
 * A line drawing: a hypotrochoid (R, r, d) draws itself on over `dur` seconds with a glowing head, turning,
 * over a fainter copy turning the other way. ink/glow/ground: CSS colours.
 */
export function spiro(canvas, { R = 5, r = 3, d = 4.6, turns = 3, dur = 1.1, ink = '#05060f', glow = '#ffffff',
  ground = '#ff4fd8', size = 0.4 } = {}) {
  const g = ctx2d(canvas);
  const W = canvas.width, H = canvas.height, S = (Math.min(W, H) * size) / (R - r + d);
  const N = 1400;
  const pt = (u, rot) => {
    const t = u * TAU * turns;
    const x = (R - r) * Math.cos(t) + d * Math.cos(((R - r) / r) * t);
    const y = (R - r) * Math.sin(t) - d * Math.sin(((R - r) / r) * t);
    const c = Math.cos(rot), s = Math.sin(rot);
    return [W / 2 + (x * c - y * s) * S, H / 2 + (x * s + y * c) * S];
  };
  return {
    draw(tau) {
      g.fillStyle = ground;
      g.fillRect(0, 0, W, H);
      const rot = tau * 0.5, p = outCubic(tau / dur);
      g.lineJoin = 'round';
      g.lineCap = 'round';
      // a rosette of faint, already-drawn copies turning the other way
      g.strokeStyle = ink;
      g.globalAlpha = 0.22;
      g.lineWidth = Math.max(1, Math.min(W, H) * 0.003);
      for (let c = 0; c < 3; c++) {
        g.beginPath();
        for (let i = 0; i <= N; i++) { const [x, y] = pt(i / N, -rot * 0.6 + (c * TAU) / 9); if (i) g.lineTo(x, y); else g.moveTo(x, y); }
        g.stroke();
      }
      g.globalAlpha = 1;
      // the drawn line: a white core under the ink, so it reads as a pen with a highlight
      const m = Math.max(1, Math.floor(N * p));
      const trace = () => { g.beginPath(); for (let i = 0; i <= m; i++) { const [x, y] = pt(i / N, rot); if (i) g.lineTo(x, y); else g.moveTo(x, y); } };
      g.strokeStyle = glow;
      g.lineWidth = Math.max(4, Math.min(W, H) * 0.016);
      trace();
      g.stroke();
      g.strokeStyle = ink;
      g.lineWidth = Math.max(2, Math.min(W, H) * 0.008);
      trace();
      g.stroke();
      const [hx, hy] = pt(m / N, rot);
      const gr = Math.min(W, H) * 0.05, rg = g.createRadialGradient(hx, hy, 0, hx, hy, gr);
      rg.addColorStop(0, glow);
      rg.addColorStop(1, 'rgba(255,255,255,0)');
      g.fillStyle = rg;
      g.fillRect(hx - gr, hy - gr, gr * 2, gr * 2);
    },
  };
}

/**
 * A halftone dot field: dots on a grid (`cell` of the frame's shorter side) sized by the shade of a lit sphere whose
 * light swings round, and small dots rippling outward around it. dot/ground: CSS colours.
 */
export function halftone(canvas, { cell = 0.028, dot = '#05060f', ground = '#ff6a1f', size = 0.36 } = {}) {
  const g = ctx2d(canvas);
  const W = canvas.width, H = canvas.height, S = Math.min(W, H), c = S * cell, R = S * size;
  return {
    draw(tau) {
      g.fillStyle = ground;
      g.fillRect(0, 0, W, H);
      g.fillStyle = dot;
      const a = -0.6 + tau * 2.4;                   // the light swings round the sphere
      const L = [Math.cos(a) * 0.8, -0.45, Math.sin(a) * 0.8 + 0.35];
      const ln = Math.hypot(L[0], L[1], L[2]);
      const grow = outCubic(tau / 0.3);
      for (let y = c / 2; y < H; y += c) {
        for (let x = c / 2; x < W; x += c) {
          const dx = (x - W / 2) / R, dy = (y - H / 2) / R, q = dx * dx + dy * dy;
          let rad;
          if (q < 1) {
            const lit = Math.max(0, (dx * L[0] + dy * L[1] + Math.sqrt(1 - q) * L[2]) / ln);
            rad = (0.12 + 0.88 * (1 - lit)) * 0.5 * c * grow;
          } else {
            const dist = Math.sqrt(q);
            rad = (0.5 * c * Math.max(0, 0.42 * Math.sin(dist * 5 - tau * 9)) / (0.6 + dist * 0.5)) * grow;
          }
          if (rad < 0.6) continue;
          g.beginPath();
          g.arc(x, y, rad, 0, TAU);
          g.fill();
        }
      }
    },
  };
}

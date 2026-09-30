// camera: a scene-level camera that moves over the scene's content as a pure function of time.
// The camera element wraps the content (it fills the scene); the path says where the camera looks
// and how close it is, and the moves between keys are eased in log-zoom space, so a 1x -> 2x push
// feels as even as 2x -> 4x. Use it instead of layout jumps: one frame, the camera travels.
//
//   <div class="cam" data-st="camera" data-path='[
//       {"at": 0,   "zoom": 1},
//       {"at": 1.2, "dur": 1.4, "focus": "#result", "zoom": 1.35},
//       {"at": 4.5, "dur": 1.2, "focus": [30, 50], "zoom": 1.15, "to": [40, 50]}]'
//     data-drift="0.008">
//     <div class="glow" data-depth="0.3"></div>   (a far layer: moves 30 % as much as the content)
//     ...content...
//   </div>
//
// Key fields: at (s from the scene start), dur (move length; 0 = a cut to this framing), zoom,
// focus (a selector inside the camera, or [x%, y%] of the camera box; default: the previous focus),
// to ([x%, y%] where the focus lands on screen, or "stay": zoom about the focus where it is laid
// out, so nothing else is pushed off frame; default [50, 50]), ease (default "camera").
// contain (default true): at zoom >= 1 the content always covers the frame (no empty borders).
// drift: after the last move, a slow push-in of this much zoom per second (capped at +6 %), so a
// hold is never frozen; data-drift="hold" is the documented default for holds (0.012 = 1.2 %/s). Children with data-depth="k" (0..1) move k times as much as the camera
// (parallax); they must fill the camera box (position: absolute; inset: 0).
import { define, clamp, ease, lerp, $$ } from './core.js';

const num = (v, d) => (Number.isFinite(Number(v)) ? Number(v) : d);
export const HOLD_DRIFT = 0.012;

export const Camera = define({
  name: 'camera',
  defaults: { at: 0, path: null, drift: 0, contain: true, keepText: true, margin: 0.035, ease: 'camera' },
  async setup(el, o) {
    // components inside (a fitted terminal, a typewriter) settle their layout first
    await Promise.all($$('[data-st]', el).map((c) => c.__stComponent && c.__stComponent.ready).filter(Boolean));
    const W = el.clientWidth || el.offsetWidth || 1, H = el.clientHeight || el.offsetHeight || 1;
    el.style.transformOrigin = '0 0';
    const box = el.getBoundingClientRect();
    const sx = box.width / W || 1, sy = box.height / H || 1;   // the page may be scaled (preview player)
    const focusOf = (f, prev) => {
      if (Array.isArray(f)) return [num(f[0], 50) / 100 * W, num(f[1], 50) / 100 * H];
      if (typeof f === 'string' && f) {
        const t = el.querySelector(f);
        if (!t) { console.warn(`[showtime] camera: focus "${f}" not found inside the camera`); return prev; }
        const r = t.getBoundingClientRect();
        return [(r.left + r.width / 2 - box.left) / sx, (r.top + r.height / 2 - box.top) / sy];
      }
      return prev;
    };
    const raw = Array.isArray(o.path) ? o.path : [];
    const keys = [];
    let prev = { at: 0, dur: 0, z: 1, f: [W / 2, H / 2], s: [W / 2, H / 2], e: ease(o.ease) };
    for (const k of raw.slice().sort((a, b) => num(a.at, 0) - num(b.at, 0))) {
      const f = focusOf(k.focus, prev.f);
      // to: where the focus lands on screen; "stay" keeps it where it is laid out (a zoom about the focus)
      const to = Array.isArray(k.to) ? [num(k.to[0], 50) / 100 * W, num(k.to[1], 50) / 100 * H] : (k.to === 'stay' ? f.slice() : [W / 2, H / 2]);
      const key = { at: num(k.at, 0), dur: Math.max(0, num(k.dur, keys.length ? 1.2 : 0)), z: Math.max(0.05, num(k.zoom, prev.z)), f, s: to, e: ease(k.ease || o.ease) };
      keys.push(key);
      prev = key;
    }
    if (!keys.length) keys.push(prev);
    // depth layers: net motion = camera^k (see the matrix note in update)
    const layers = $$('[data-depth]', el).filter((d) => d.parentElement === el).map((d) => ({ el: d, k: clamp(num(d.dataset.depth, 1), 0, 2) }));
    for (const L of layers) L.el.style.transformOrigin = '0 0';
    // drift: true / "hold" = HOLD_DRIFT, the documented hold push (1.2 % per second: `showtime check` and
    // qa's frozen detector both count it as change on light and dark text frames; 0.8 %/s is borderline
    // and 0.4 %/s fails check on a light text frame, measured 2026-09-30)
    const rawDrift = el.getAttribute('data-drift') ?? o.drift;   // read as written: "hold" is not a number
    const drift = ['true', 'hold', 'auto'].includes(String(rawDrift).trim().toLowerCase()) || rawDrift === true ? HOLD_DRIFT : Math.max(0, num(rawDrift, 0));
    // keepText: the union of every visible text box stays inside the frame (minus a margin) while the
    // camera moves, so a push or a lean never slides a headline off the edge
    let tb = null;
    if (o.keepText !== false && o.keepText !== 'false') {
      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (!n.data.trim()) continue;
        const pe = n.parentElement;
        if (!pe || pe.closest('[data-st-decor]') || getComputedStyle(pe).visibility === 'hidden') continue;
        const rg = document.createRange(); rg.selectNodeContents(n);
        const r = rg.getBoundingClientRect();
        if (!r.width || !r.height) continue;
        const x0 = (r.left - box.left) / sx, y0 = (r.top - box.top) / sy, x1 = x0 + r.width / sx, y1 = y0 + r.height / sy;
        tb = tb ? [Math.min(tb[0], x0), Math.min(tb[1], y0), Math.max(tb[2], x1), Math.max(tb[3], y1)] : [x0, y0, x1, y1];
      }
    }
    // the safe area: a margin at 16:9 and 1:1; the feed-safe box at 9:16 (x 64-916, y 220-1440 of 1080x1920)
    const tall = H > W * 1.3;
    const safe = tall ? [64 / 1080 * W, 220 / 1920 * H, 916 / 1080 * W, 1440 / 1920 * H]
      : [num(o.margin, 0.035) * W, num(o.margin, 0.035) * H, W - num(o.margin, 0.035) * W, H - num(o.margin, 0.035) * H];
    const keepIn = (t, z, a0, a1, lo0, hi0) => {
      const lo = lo0 - z * a0, hi = hi0 - z * a1;
      if (a1 - a0 <= 0) return t;
      return lo <= hi ? Math.min(hi, Math.max(lo, t)) : (lo + hi) / 2;
    };
    const moving = (lt) => keys.some((k, i) => i > 0 && k.dur > 0 && lt > k.at && lt < k.at + k.dur);
    const contain = o.contain !== false && o.contain !== 'false';
    const last = keys[keys.length - 1];
    const tEnd = last.at + last.dur;

    // the framing at local time lt: zoom z, and the content point F shown at screen point S
    function state(lt) {
      let a = keys[0];
      if (lt <= a.at) return { z: a.z, F: a.f, S: a.s };
      for (let i = 1; i < keys.length; i++) {
        const b = keys[i];
        if (lt < b.at) return { z: a.z, F: a.f, S: a.s };
        if (lt < b.at + b.dur) {
          const p = b.e(clamp((lt - b.at) / b.dur));
          // log-zoom interpolation; the looked-at point and its screen spot travel with the same curve
          const z = Math.exp(lerp(Math.log(a.z), Math.log(b.z), p));
          return { z, F: [lerp(a.f[0], b.f[0], p), lerp(a.f[1], b.f[1], p)], S: [lerp(a.s[0], b.s[0], p), lerp(a.s[1], b.s[1], p)] };
        }
        a = b;
      }
      let z = a.z;
      if (drift > 0 && lt > tEnd) z *= 1 + Math.min(0.06, drift * (lt - tEnd));
      return { z, F: a.f, S: a.s };
    }

    return {
      duration: tEnd,
      update(lt) {
        const { z, F, S } = state(lt);
        // screen = S + z (x - F)  ->  translate(S - zF) scale(z), origin 0 0
        let tx = S[0] - z * F[0], ty = S[1] - z * F[1];
        if (contain && z >= 1) {
          tx = clamp(tx, W - z * W, 0);
          ty = clamp(ty, H - z * H, 0);
        }
        if (tb && Math.abs(z - 1) > 1e-4) {
          tx = keepIn(tx, z, tb[0], tb[2], safe[0], safe[2]);
          ty = keepIn(ty, z, tb[1], tb[3], safe[1], safe[3]);
        }
        if (!moving(lt) && drift === 0) {
          // a hold: whole pixels, so type sits still instead of shimmering between subpixel positions
          tx = Math.round(tx); ty = Math.round(ty);
        }
        el.style.transform = `translate(${tx.toFixed(3)}px, ${ty.toFixed(3)}px) scale(${z.toFixed(5)})`;
        // a child with depth k should move as camera^k: C = (z, t), C^k = (z^k, k t) (for small moves);
        // its own transform X = C^-1 C^k: scale z^(k-1), translate (k - 1) t / z
        for (const L of layers) {
          const zk = Math.pow(z, L.k - 1);
          L.el.style.transform = `translate(${((L.k - 1) * tx / z).toFixed(3)}px, ${((L.k - 1) * ty / z).toFixed(3)}px) scale(${zk.toFixed(5)})`;
        }
      },
    };
  },
});

export default Camera;

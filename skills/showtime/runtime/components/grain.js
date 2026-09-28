// grain: animated film grain overlay, seeded per frame step (deterministic), to add texture
// and hide gradient banding after compression. Keep it subtle: opacity 0.03-0.06.
//
//   <div data-st="grain"></div>                 (uses the theme's --grain opacity)
//   <div data-st="grain" data-opacity="0.05" data-fps="12"></div>
import { define, h, hash, rng, token } from './core.js';

let TILE = null;
function tile() {
  if (TILE) return TILE;
  const n = 256;
  const c = document.createElement('canvas');
  c.width = c.height = n;
  const x = c.getContext('2d');
  const img = x.createImageData(n, n);
  const r = rng(4242);
  for (let i = 0; i < n * n; i++) {
    // roughly gaussian grain (sum of uniforms), mid-grey centred
    const v = Math.max(0, Math.min(255, 128 + ((r() + r() + r() - 1.5) * 150)));
    img.data[i * 4] = img.data[i * 4 + 1] = img.data[i * 4 + 2] = v;
    img.data[i * 4 + 3] = 255;
  }
  x.putImageData(img, 0, 0);
  TILE = c;
  return c;
}

export const Grain = define({
  name: 'grain',
  defaults: { at: 0, opacity: null, fps: 24, size: 1.5, blend: 'overlay' },
  setup(el, o) {
    const op = o.opacity ?? (parseFloat(token(el, '--grain', '0.04')) || 0.04);
    const frame = el.parentElement || document.body;
    const W = Math.ceil((frame.clientWidth || innerWidth) / o.size), H = Math.ceil((frame.clientHeight || innerHeight) / o.size);
    const canvas = h('canvas', { width: W, height: H });
    el.textContent = '';
    el.append(canvas);
    el.style.opacity = op;
    el.style.mixBlendMode = o.blend;
    const ctx = canvas.getContext('2d');
    const t0 = tile();
    let last = null;
    return {
      duration: 0,
      update(lt) {
        const step = Math.floor(Math.max(0, lt) * o.fps);
        if (step === last) return;
        last = step;
        const dx = Math.floor(hash(step, 11) * 256), dy = Math.floor(hash(step, 29) * 256);
        for (let y = -dy; y < H; y += 256) for (let x = -dx; x < W; x += 256) ctx.drawImage(t0, x, y);
      },
    };
  },
});

export default Grain;

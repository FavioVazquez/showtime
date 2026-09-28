// ken-burns: a slow, eased pan and zoom over a still image (or any element), as a pure
// function of time. Use a scale change of 4-12 % over the whole shot; more reads as a zoom.
//
//   <div data-st="ken-burns" data-src="photo.jpg" data-from='{"scale":1,"x":0,"y":0}'
//        data-to='{"scale":1.1,"x":-3,"y":-2}' data-dur="6"></div>
//   KenBurns('#hero', { src: 'shot.png', focus: [70, 30], zoom: 1.15 })   // push toward a point
import { define, h, clamp, ease, lerp } from './core.js';

export const KenBurns = define({
  name: 'ken-burns',
  defaults: { at: 0, src: '', from: null, to: null, focus: null, zoom: 1.1, dur: null, ease: 'sine.inOut', fit: 'cover', fade: null, mask: null },
  setup(el, o, { clipDur }) {
    let target = el.querySelector('img, video, picture, canvas');
    if (o.src) {
      el.textContent = '';
      target = h('img', { src: o.src, alt: '', decoding: 'sync' });
      el.append(target);
    }
    if (!target) target = el.firstElementChild || el;
    target.classList.add('st-kb-media');
    // object-fit comes from the stylesheet (.st-kb-media: cover), so page CSS can change it; an
    // explicit data-fit / fit option sets it inline
    if (el.hasAttribute('data-fit') || o.fit !== 'cover') target.style.objectFit = o.fit;
    // a mask on the moving picture (not on the fixed wrapper), so it scales with the zoom
    if (o.mask) { target.style.maskImage = o.mask; target.style.webkitMaskImage = o.mask; }
    // fade-in: none when the shot starts with its scene (the cut or the scene's transition is the
    // entrance; a fade there dips every beat cut to black), 0.4 s when it appears mid-scene
    const fade = o.fade != null ? Number(o.fade) : ((Number(o.at) || 0) > 0 ? 0.4 : 0);
    let from = o.from || { scale: 1, x: 0, y: 0 };
    let to = o.to;
    if (!to) {
      // push toward a focus point [x%, y%] (default: a gentle drift up-left)
      const [fx, fy] = Array.isArray(o.focus) ? o.focus : [50, 45];
      const z = Number(o.zoom) || 1.1;
      to = { scale: z, x: (50 - fx) * (z - 1), y: (50 - fy) * (z - 1) };
    }
    const dur = Number(o.dur) || (Number.isFinite(clipDur) ? clipDur - (Number(o.at) || 0) : 6);
    const E = ease(o.ease);
    return {
      duration: dur,
      update(lt) {
        const p = E(clamp(lt / dur));
        const s = lerp(from.scale ?? 1, to.scale ?? 1, p), x = lerp(from.x ?? 0, to.x ?? 0, p), y = lerp(from.y ?? 0, to.y ?? 0, p);
        target.style.transform = `translate(${x.toFixed(4)}%, ${y.toFixed(4)}%) scale(${s.toFixed(5)})`;
        if (fade > 0) el.style.opacity = clamp(lt / fade).toFixed(3);
      },
    };
  },
});

export default KenBurns;

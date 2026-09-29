// fit: shrink an element's type so its longest line fits its box at every frame size (a terminal, a
// code panel, a command pill). Lines never break mid-command and never run under the box's edge;
// only when even `min` of the size does not fit do lines wrap, with a hanging indent.
//
//   <div class="term" data-st="fit" data-min="0.6">$ quillsort files.txt --natural ...</div>
//
// Measured once, after the components inside it (a typewriter reserves its full text) are ready, at the
// frame size of the run: `showtime render --size 9:16` re-fits the same page. `box` (default: the
// element's parent) bounds the height: the lines must also fit between the element's top and the box's
// bottom. Sets --fit-scale on the element.
import { define, $$ } from './core.js';

export const Fit = define({
  name: 'fit',
  defaults: { at: 0, min: 0.55, box: null, wrap: true },
  async setup(el, o) {
    // the components inside (typewriter ghosts, code tokens) must have laid out their final text first
    await Promise.all($$('[data-st]', el).map((c) => c.__stComponent && c.__stComponent.ready).filter(Boolean));
    const cs = getComputedStyle(el);
    const base = parseFloat(cs.fontSize) || 16;
    const padX = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
    const box = (o.box && el.closest(o.box)) || el.parentElement || el;
    const measure = () => {
      const availW = el.clientWidth - padX;
      // the longest line's own width: the element at max-content (scrollWidth never drops below the box)
      const saved = el.style.width;
      el.style.width = 'max-content';
      const needW = el.offsetWidth - padX;
      el.style.width = saved;
      const availH = box.getBoundingClientRect().bottom - el.getBoundingClientRect().top;
      const needH = el.scrollHeight;
      // 3 % of the width stays free for a caret and the optical margin
      const w = availW * 0.97;
      return { sw: w > 0 && needW > w ? w / needW : 1, sh: availH > 0 && needH > availH ? availH / needH : 1 };
    };
    let k = 1;
    for (let i = 0; i < 3; i++) {             // font metrics are not perfectly linear: settle in a few passes
      const m = measure();
      const f = Math.min(m.sw, m.sh);
      if (f >= 0.999) break;
      k = Math.max(Number(o.min) || 0.55, k * f * 0.995);
      el.style.fontSize = (base * k).toFixed(2) + 'px';
      if (k <= (Number(o.min) || 0.55)) break;
    }
    if (measure().sw < 0.999 && o.wrap !== false && o.wrap !== 'false') {
      // last resort: wrap long lines with a hanging indent (continuations sit two characters in)
      el.classList.add('st-fit-wrap');
      for (const n of [el, ...$$('*', el)]) n.style.setProperty('white-space', 'pre-wrap', 'important');
      el.style.paddingLeft = `calc(${cs.paddingLeft} + 2ch)`;
      el.style.textIndent = '-2ch';
    }
    el.style.setProperty('--fit-scale', k.toFixed(4));
    el.dataset.fitScale = k.toFixed(3);
    return { duration: 0, update() {} };
  },
});

export default Fit;

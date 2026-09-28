// feature-grid: a grid of feature cards (icon, title, one line) that assemble with a short
// stagger, then optionally spotlight one card at a time. Columns adapt to the frame aspect.
// Cards come from `items` or from the element's existing children (each child = one card).
// Icons: an .svg path (inlined, takes the accent colour; the lucide set is at /_lib/lucide-static/icons/),
// raw <svg> markup, an image, or text. Avoid emoji: they render with each OS's own emoji font.
//
//   <div data-st="feature-grid" data-items='[{"icon":"/_lib/lucide-static/icons/zap.svg","title":"Fast","text":"Renders in seconds"}]'
//        data-focus='[{"at":2,"index":0},{"at":3,"index":1}]'></div>
import { define, h, clamp, ease, lerp, stagger, aspectOf } from './core.js';

export const FeatureGrid = define({
  name: 'feature-grid',
  defaults: { at: 0, items: null, columns: null, focus: [], stagger: 0.09, cap: 0.55, dim: 0.5 },
  async setup(el, o, { motion }) {
    // .svg icons are inlined so they take the theme colour (stroke/fill = currentColor)
    if (Array.isArray(o.items)) {
      await Promise.all(o.items.map(async (it) => {
        if (it.icon && /\.svg(\?|$)/i.test(it.icon)) {
          try { const txt = await (await fetch(it.icon)).text(); if (/<svg[\s>]/i.test(txt)) it.icon = txt.slice(txt.search(/<svg[\s>]/i)); } catch { /* keep as <img> */ }
        }
      }));
    }
    let cards;
    if (Array.isArray(o.items) && o.items.length) {
      el.textContent = '';
      cards = o.items.map((it) => {
        const icon = it.icon ? (/^<svg/i.test(it.icon) ? h('div', { class: 'st-fg-icon', html: it.icon }) : /\.(svg|png|jpe?g|webp)$/i.test(it.icon) ? h('div', { class: 'st-fg-icon' }, h('img', { src: it.icon, alt: '' })) : h('div', { class: 'st-fg-icon' }, it.icon)) : null;
        const c = h('div', { class: 'st-fg-card' }, icon, h('div', { class: 'st-fg-title' }, it.title || ''), it.text ? h('div', { class: 'st-fg-text' }, it.text) : null);
        el.append(c);
        return c;
      });
    } else {
      cards = Array.from(el.children);
      cards.forEach((c) => c.classList.add('st-fg-card'));
    }
    const n = cards.length;
    const aspect = aspectOf(el.closest('.scene, .stage') || document.body);
    const cols = o.columns || (aspect === 'tall' ? (n <= 3 ? 1 : 2) : aspect === 'square' ? (n <= 2 ? n : 2) : n <= 4 ? n : n <= 6 ? 3 : 4);
    el.style.setProperty('--cols', cols);
    const E = ease(motion.easeOut);
    const dur = motion.durIn;
    const starts = cards.map((_, i) => stagger(i, n, o.stagger, { cap: Number(o.cap) > 0 ? Number(o.cap) : 0.55 }));
    const focus = (Array.isArray(o.focus) ? o.focus : []).map((f) => ({ at: Number(f.at) || 0, index: Number(f.index) })).sort((a, b) => a.at - b.at);
    const landed = (starts[n - 1] || 0) + dur;
    return {
      duration: Math.max(landed, ...focus.map((f) => f.at + 0.5)),
      sync: { landed },
      update(lt) {
        // spotlight: blend from the previous focus state to the current over 0.4 s
        let cur = -1, prev = -1, since = 1;
        for (const f of focus) if (lt >= f.at) { prev = cur; cur = f.index; since = clamp((lt - f.at) / 0.4); }
        const fs = E(since);
        for (let i = 0; i < n; i++) {
          const p = E(clamp((lt - starts[i]) / dur));
          const w = (idx) => (idx < 0 ? 0 : idx === i ? 1 : -1); // 1 focused, -1 dimmed, 0 neutral
          const f = lerp(w(prev), w(cur), fs);
          const scale = lerp(0.94, 1, p) * (1 + 0.035 * Math.max(0, f));
          const c = cards[i];
          c.style.opacity = (clamp(p * 1.4) * (f < 0 ? lerp(1, o.dim, -f) : 1)).toFixed(3);
          c.style.transform = `translateY(${((1 - p) * 4).toFixed(3)}cqmin) scale(${scale.toFixed(4)})`;
          c.style.setProperty('--focus', Math.max(0, f).toFixed(3));
        }
      },
    };
  },
});

export default FeatureGrid;

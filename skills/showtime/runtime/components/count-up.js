// count-up: an animated statistic. The number arrives (fade + rise), counts with an ease-out
// on tabular figures so the width never jitters, lands with one small pulse, and an optional
// ring or bar fills in lockstep. Never invent numbers: pass the real value.
//
//   <div data-st="count-up" data-value="74" data-suffix="%" data-label="faster builds"
//        data-variant="ring" data-at="0.4"></div>
//   CountUp('#stat', { value: 12800, compact: true, prefix: '$', label: 'saved per month' })
import { define, h, clamp, ease, lerp, formatNumber, pageLocale } from './core.js';

export const CountUp = define({
  name: 'count-up',
  defaults: {
    at: 0, value: 100, from: 0, decimals: 0, prefix: '', suffix: '', label: '', dur: 1.6, ease: 'power3.out',
    compact: false, group: true, variant: 'plain', of: null, pulse: true, align: 'center', suffixAlign: 'auto',
    locale: null, // number format; default: the page's <html lang>, else en-US
  },
  setup(el, o, { motion }) {
    const value = Number(o.value) || 0, from = Number(o.from) || 0;
    el.textContent = '';
    el.classList.add('st-cu-v-' + (['ring', 'bar'].includes(o.variant) ? o.variant : 'plain'));
    el.style.textAlign = o.align;
    const locale = o.locale || pageLocale();
    const fmt = (v) => formatNumber(v, { decimals: o.decimals, group: o.group, compact: o.compact, locale });
    // Reserve the widest string so centring never drifts while digits change.
    const widest = fmt(Math.max(Math.abs(value), Math.abs(from)) * (value < 0 || from < 0 ? -1 : 1));
    const numEl = h('span', { class: 'st-cu-num' }, fmt(from));
    const numBox = h('span', { class: 'st-cu-numbox' }, h('span', { class: 'st-cu-ghost', 'aria-hidden': 'true' }, widest), numEl);
    const lift = /^[$€£¥₹#+\-−~≈]$/.test(o.prefix) ? ' st-cu-lift' : '';
    // a degree sign sits high by nature: "°C" at a small baseline-aligned size reads as "◦C"
    const top = o.suffixAlign === 'top' || (o.suffixAlign === 'auto' && /^°/.test(String(o.suffix)));
    const figure = h('div', { class: 'st-cu-figure' },
      o.prefix ? h('span', { class: 'st-cu-affix' + lift }, o.prefix) : null, numBox,
      o.suffix ? h('span', { class: 'st-cu-affix st-cu-suffix' + (top ? ' st-cu-top' : '') }, o.suffix) : null);
    const label = o.label ? h('div', { class: 'st-cu-label' }, o.label) : null;
    let meter = null, fillEl = null;
    if (o.variant === 'ring') {
      meter = h('svg:svg', { class: 'st-cu-ring', viewBox: '0 0 100 100' },
        h('svg:circle', { cx: 50, cy: 50, r: 44, class: 'st-cu-track' }),
        (fillEl = h('svg:circle', { cx: 50, cy: 50, r: 44, class: 'st-cu-fill', pathLength: 100 })));
      el.append(...[h('div', { class: 'st-cu-ringwrap' }, meter, h('div', { class: 'st-cu-center' }, figure)), label].filter(Boolean));
    } else if (o.variant === 'bar') {
      meter = h('div', { class: 'st-cu-bar' }, (fillEl = h('div', { class: 'st-cu-barfill' })));
      el.append(...[figure, label, meter].filter(Boolean));
    } else {
      el.append(...[figure, label].filter(Boolean));
    }
    // proportional display fonts (no tabular figures) make some counting values wider than the final
    // one: reserve the widest string the count shows, measured in the real font
    try {
      const k0 = 10 ** (Number(o.decimals) || 0);
      const cands = new Set([widest]);
      for (let i = 0; i <= 40; i++) cands.add(fmt(Math.round(lerp(from, value, i / 40) * k0) / k0));
      const cs = getComputedStyle(numEl);
      const ctx = document.createElement('canvas').getContext('2d');
      ctx.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
      let best = widest, bw = ctx.measureText(widest).width;
      for (const c of cands) { const w = ctx.measureText(c).width; if (w > bw + 0.01) { best = c; bw = w; } }
      numBox.firstChild.textContent = best;
    } catch { /* keep the final value's width */ }
    const total = o.of != null ? Number(o.of) : (o.suffix === '%' ? 100 : Math.max(value, 1));
    const E = ease(o.ease), IN = ease(motion.easeOut);
    const arrive = 0.38, start = 0.12;
    const land = start + Number(o.dur);
    const decimals = Number(o.decimals) || 0;
    const k = 10 ** decimals;
    return {
      duration: land + 0.35,
      sync: { land },
      update(lt) {
        const a = IN(clamp(lt / arrive));
        el.style.opacity = clamp(lt / (arrive * 0.6)).toFixed(3);
        figure.style.transform = `translateY(${((1 - a) * 2.2).toFixed(3)}cqh) scale(${lerp(0.98, 1, a).toFixed(4)})`;
        const p = E(clamp((lt - start) / Number(o.dur)));
        const v = Math.round(lerp(from, value, p) * k) / k;
        const s = fmt(v);
        if (numEl.textContent !== s) numEl.textContent = s;
        // one landing pulse (1.07) on the number only
        if (o.pulse) {
          const q = clamp((lt - land) / 0.33);
          const s2 = q > 0 && q < 1 ? 1 + 0.07 * Math.sin(Math.PI * q) : 1;
          numBox.style.transform = s2 !== 1 ? `scale(${s2.toFixed(4)})` : '';
        }
        if (label) { const l = IN(clamp((lt - 0.25) / 0.5)); label.style.opacity = l; label.style.transform = `translateY(${((1 - l) * 0.4).toFixed(3)}em)`; }
        if (fillEl) {
          const f = clamp(lerp(from, value, p) / total);
          if (o.variant === 'ring') fillEl.style.strokeDashoffset = (100 - f * 100).toFixed(3);
          else fillEl.style.transform = `scaleX(${f.toFixed(4)})`;
        }
      },
    };
  },
});

export default CountUp;

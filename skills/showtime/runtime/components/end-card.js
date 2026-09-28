// logo-reveal and end-card.
//
// LogoReveal animates a logo (an <img>, inline <svg>, or a text wordmark) with one of:
//   assemble (letters cascade in, accent dot lands last) | mask (wipes up from a baseline) |
//   blur (resolves from a soft blur with a glow bloom) | draw (inline SVG strokes draw on, then fill)
// EndCard lays out logo + tagline + call-to-action pill + URL and holds (keep it >= 2.5 s).
// With both a logo image (data-logo or a child <img>/<svg>) and data-text, it shows the mark
// next to the name (stacked in tall frames): the mark resolves first, the wordmark follows.
//
//   <div data-st="logo-reveal" data-text="northwind" data-style="assemble"></div>
//   <div data-st="end-card" data-text="northwind" data-tagline="Ship video from your terminal"
//        data-cta="Try it free" data-url="northwind.dev" data-at="0.2"></div>
//   <div data-st="end-card" data-logo="shots/logo.svg" data-text="Nimbus" data-tagline="..."></div>
import { define, h, clamp, ease, lerp, stagger, splitText } from './core.js';

function buildLogo(el, o) {
  // existing children (img/svg) win; else a text wordmark with an accent full stop
  const existing = el.querySelector('img, svg');
  if (existing) { existing.classList.add('st-logo-mark'); return { mark: existing, chars: null }; }
  const word = h('div', { class: 'st-logo-word' }, o.text || 'logo');
  el.textContent = '';
  el.append(word);
  if (o.dot !== false) word.append(h('span', { class: 'st-logo-dot' }, o.dot === true || o.dot == null ? '.' : String(o.dot)));
  const { chars } = splitText(word, { chars: true });
  return { mark: word, chars: chars.filter((c) => !c.closest('.st-logo-dot')), dot: word.querySelector('.st-logo-dot') };
}

function logoAnimator(el, o, motion) {
  const logo = buildLogo(el, o);
  const style = ['assemble', 'mask', 'blur', 'draw'].includes(o.style) ? o.style : (logo.chars ? 'assemble' : 'blur');
  el.classList.add('st-logo-' + style);
  const E = ease(motion.easeOut), S = ease('spring(0.5,0.62)');
  let paths = [];
  if (style === 'draw' && logo.mark.tagName.toLowerCase() === 'svg') {
    paths = Array.from(logo.mark.querySelectorAll('path, circle, rect, line, polyline, polygon, ellipse'));
    for (const p of paths) {
      const len = p.getTotalLength ? p.getTotalLength() : 1000;
      p.style.strokeDasharray = `${len} ${len}`; p.dataset.len = len;
      if (!p.getAttribute('stroke')) p.style.stroke = 'currentColor';
      if (!p.style.strokeWidth) p.style.strokeWidth = '1.5';
    }
  }
  const n = logo.chars ? logo.chars.length : 0;
  const D = style === 'draw' ? 1.6 : style === 'assemble' ? 0.5 + stagger(n - 1, n, 0.05, { cap: 0.45 }) + 0.35 : 0.9;
  const update = (lt) => {
    if (style === 'assemble' && logo.chars) {
      logo.chars.forEach((c, i) => {
        const p = E(clamp((lt - stagger(i, n, 0.05, { cap: 0.45 })) / 0.5));
        c.style.opacity = clamp(p * 1.6); c.style.transform = `translateY(${((1 - p) * 0.45).toFixed(3)}em)`;
        c.style.filter = p < 1 ? `blur(${((1 - p) * 0.06).toFixed(3)}em)` : '';
      });
      if (logo.dot) {
        const t0 = stagger(n - 1, n, 0.05, { cap: 0.45 }) + 0.3;
        const p = S(clamp((lt - t0) / 0.45));
        logo.dot.style.opacity = clamp((lt - t0) / 0.06);
        logo.dot.style.transform = `translateY(${((1 - p) * -0.9).toFixed(3)}em) scale(${lerp(0.4, 1, p).toFixed(3)})`;
      }
    } else if (style === 'mask') {
      const p = E(clamp(lt / 0.8));
      logo.mark.style.clipPath = `inset(${((1 - p) * 100).toFixed(2)}% 0 0 0)`;
      logo.mark.style.transform = `translateY(${((1 - p) * 30).toFixed(2)}%)`;
      if (logo.dot) logo.dot.style.opacity = 1;
    } else if (style === 'blur') {
      const p = E(clamp(lt / 0.9));
      logo.mark.style.opacity = clamp(p * 1.5);
      logo.mark.style.filter = p < 1 ? `blur(${((1 - p) * 2.2).toFixed(3)}cqmin)` : '';
      logo.mark.style.transform = `scale(${lerp(1.14, 1, p).toFixed(4)})`;
    } else if (style === 'draw') {
      const p = ease('power2.inOut')(clamp(lt / 1.2));
      paths.forEach((pth, i) => {
        const len = +pth.dataset.len;
        const q = clamp(p * 1.25 - (i / Math.max(1, paths.length)) * 0.25);
        pth.style.strokeDashoffset = ((1 - q) * len).toFixed(2);
      });
      logo.mark.style.setProperty('--fill-o', E(clamp((lt - 1.0) / 0.6)).toFixed(3));
    }
    // glow bloom behind the logo peaks as it lands
    // (bloom: false turns it off: brand rules often forbid glows on a wordmark)
    el.style.setProperty('--bloom', o.bloom === false ? '0' : (Math.sin(Math.PI * clamp((lt - D * 0.4) / (D * 1.2))) * 0.9).toFixed(3));
  };
  return { update, duration: D, style };
}

export const LogoReveal = define({
  name: 'logo-reveal',
  defaults: { at: 0, text: '', style: 'assemble', dot: true, bloom: true },
  setup(el, o, { motion }) {
    el.classList.add('st-logo');
    const a = logoAnimator(el, o, motion);
    return { duration: a.duration, sync: { landed: a.duration }, update: (lt) => a.update(lt) };
  },
});

export const EndCard = define({
  name: 'end-card',
  defaults: { at: 0, text: '', logo: '', style: 'assemble', tagline: '', cta: '', url: '', dot: true, bloom: true },
  setup(el, o, { motion }) {
    const logoHost = h('div', { class: 'st-logo' });
    const existing = el.querySelector('img, svg');
    let mark = null;
    if (o.logo) mark = h('img', { src: o.logo, alt: o.text || '' });
    else if (existing) mark = existing;
    el.textContent = '';
    let brand = logoHost, a, b = null, delay = 0;
    if (mark && o.text) {
      // mark + name: both are shown (a logo image never replaces the product name)
      const markHost = h('div', { class: 'st-logo st-ec-mark' }, mark);
      const wordHost = h('div', { class: 'st-logo st-ec-word' });
      brand = h('div', { class: 'st-ec-brand' }, markHost, wordHost);
      const markStyle = ['mask', 'blur', 'draw'].includes(o.style) ? o.style : 'blur';
      a = logoAnimator(markHost, { ...o, style: markStyle }, motion);
      b = logoAnimator(wordHost, { ...o, style: ['assemble', 'mask', 'blur'].includes(o.style) ? o.style : 'assemble' }, motion);
      delay = Math.min(0.35, a.duration * 0.4);
    } else {
      if (mark) { logoHost.append(mark); logoHost.classList.add('st-ec-mark'); }
      // an image alone has no letters to assemble: resolve it (blur) unless mask/draw was asked for
      a = logoAnimator(logoHost, mark && !['mask', 'blur', 'draw'].includes(o.style) ? { ...o, style: 'blur' } : o, motion);
    }
    const tag = o.tagline ? h('div', { class: 'st-ec-tagline' }, o.tagline) : null;
    const cta = o.cta ? h('div', { class: 'st-ec-cta' }, o.cta) : null;
    const url = o.url ? h('div', { class: 'st-ec-url' }, o.url) : null;
    el.append(h('div', { class: 'st-ec-stack' }, brand, tag, cta, url));
    const E = ease(motion.easeOut), S = ease('spring(0.42,0.6)');
    const logoDur = Math.max(a.duration, b ? delay + b.duration : 0);
    const t1 = logoDur * 0.75;
    return {
      duration: t1 + 1.2,
      sync: { logo: logoDur, cta: t1 + 0.35 },
      update(lt) {
        a.update(lt);
        if (b) b.update(lt - delay);
        if (tag) { const p = E(clamp((lt - t1) / 0.6)); tag.style.opacity = p; tag.style.transform = `translateY(${((1 - p) * 0.6).toFixed(3)}em)`; }
        if (cta) { const p = S(clamp((lt - t1 - 0.35) / 0.5)); cta.style.opacity = clamp((lt - t1 - 0.35) / 0.1); cta.style.transform = `scale(${lerp(0.7, 1, p).toFixed(4)})`; }
        if (url) { const p = E(clamp((lt - t1 - 0.6) / 0.5)); url.style.opacity = p; }
      },
    };
  },
});

export default EndCard;

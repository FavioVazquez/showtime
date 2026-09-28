// lower-third: name + role identification in four looks. Enters, holds, exits; sits inside the
// title-safe area (higher up in 9:16 so it clears the app UI).
//
// Variants: bar (accent bar grows, name slides out of it) | card (surface card wipes in,
//           underline draws) | kicker (small label, big name, drawn rule) | pill (rounded chip
//           with avatar or status dot, springs in)
//
//   <div data-st="lower-third" data-variant="card" data-name="Ada Park" data-role="Staff engineer"
//        data-at="1.2" data-hold="3"></div>
import { define, h, clamp, ease, lerp, aspectOf, safeInsets } from './core.js';

export const LowerThird = define({
  name: 'lower-third',
  defaults: { at: 0, variant: 'bar', name: '', role: '', kicker: '', avatar: '', side: 'left', hold: null, exit: true, position: 'auto', in: null },
  setup(el, o, { motion, clipDur }) {
    const name = o.name || el.getAttribute('data-name') || el.textContent.trim() || 'Name';
    el.textContent = '';
    const v = ['bar', 'card', 'kicker', 'pill'].includes(o.variant) ? o.variant : 'bar';
    el.classList.add('st-lt-v-' + v, 'st-lt-' + (o.side === 'right' ? 'right' : 'left'));
    const frame = el.closest('.scene, .stage') || document.body;
    const aspect = aspectOf(frame);
    const safe = safeInsets(aspect);
    // tall frames are read on a phone: bigger type (st-lt-tall) so name and role clear check's floor
    if (aspect === 'tall') el.classList.add('st-lt-tall');
    const sideProp = o.side === 'right' ? 'right' : 'left';
    const sideVal = ((o.side === 'right' ? safe.right : safe.left) * 100 + 1).toFixed(2) + '%';
    if (o.position === 'auto') {
      el.style.bottom = ((aspect === 'wide' ? 0.12 : aspect === 'tall' ? safe.bottom + 0.06 : 0.12) * 100).toFixed(2) + '%';
      el.style[sideProp] = sideVal;
    } else if (o.position === 'top') {
      // above the content, below the platform's top UI: clears a caption band in the lower half
      el.style.top = ((safe.top + 0.03) * 100).toFixed(2) + '%';
      el.style[sideProp] = sideVal;
    }

    const nameEl = h('div', { class: 'st-lt-name' }, h('span', { class: 'st-lt-name-in' }, name));
    const roleEl = o.role ? h('div', { class: 'st-lt-role' }, o.role) : null;
    const kickEl = o.kicker ? h('div', { class: 'st-lt-kicker' }, o.kicker) : null;
    const accent = h('div', { class: 'st-lt-accent' });
    const box = h('div', { class: 'st-lt-box' });
    if (v === 'pill') {
      const av = o.avatar ? h('img', { class: 'st-lt-avatar', src: o.avatar, alt: '' }) : h('span', { class: 'st-lt-dot' });
      box.append(av, h('div', { class: 'st-lt-text' }, nameEl, roleEl));
    } else {
      box.append(accent, h('div', { class: 'st-lt-text' }, kickEl, nameEl, roleEl));
    }
    el.append(box);

    // `in` (seconds) scales the whole entrance; the default is 0.85 s (kicker 1.0 s)
    const IN0 = v === 'kicker' ? 1.0 : 0.85;
    const IN = Number(o.in) > 0 ? Number(o.in) : IN0;
    const K = IN / IN0;
    const OUT = Math.max(0.3, motion.durOut);
    let hold = o.hold;
    if (hold == null) hold = Number.isFinite(clipDur) ? Math.max(1, clipDur - (Number(o.at) || 0) - IN - OUT - 0.1) : 3.5;
    const exitAt = o.exit ? IN + Number(hold) : Infinity;
    const E = ease(motion.easeOut), X = ease(motion.easeIn), S = ease('spring(0.45,0.72)');
    const seg = (t, a, d, f = E) => f(clamp((t - a) / d));
    const dir = o.side === 'right' ? -1 : 1;

    return {
      duration: Number.isFinite(exitAt) ? exitAt + OUT : IN,
      sync: { in: 0, landed: IN, ...(Number.isFinite(exitAt) ? { exit: exitAt } : {}) },
      update(lt) {
        if (lt < 0 || lt > exitAt + OUT) { el.style.visibility = 'hidden'; return; }
        el.style.visibility = '';
        const q = Number.isFinite(exitAt) ? X(clamp((lt - exitAt) / OUT)) : 0;
        const nameIn = nameEl.firstChild;
        const le = lt / K; // entrance clock (the entrance choreography is written for IN0)
        if (v === 'bar') {
          const a = seg(le, 0, 0.35);
          accent.style.transform = `scaleY(${a.toFixed(4)})`;
          const n = seg(le, 0.18, 0.55);
          nameIn.style.transform = `translateX(${(-(1 - n) * 105 * dir).toFixed(2)}%)`;
          if (roleEl) { const r = seg(le, 0.4, 0.45); roleEl.style.opacity = r; roleEl.style.transform = `translateY(${((1 - r) * 0.5).toFixed(3)}em)`; }
        } else if (v === 'card') {
          const w = seg(le, 0, 0.55);
          box.style.clipPath = `inset(0 ${((1 - w) * 100).toFixed(2)}% 0 0 round var(--radius, 1cqmin))`;
          const n = seg(le, 0.15, 0.5);
          nameIn.style.transform = `translateY(${((1 - n) * 0.6).toFixed(3)}em)`; nameIn.style.opacity = n;
          accent.style.transform = `scaleX(${seg(le, 0.35, 0.5).toFixed(4)})`;
          if (roleEl) { const r = seg(le, 0.35, 0.45); roleEl.style.opacity = r; }
        } else if (v === 'kicker') {
          if (kickEl) { const k = seg(le, 0, 0.3, S); kickEl.style.opacity = clamp(k * 2); kickEl.style.transform = `scale(${lerp(0.7, 1, k).toFixed(4)})`; }
          const n = seg(le, 0.12, 0.6);
          nameIn.style.transform = `translateY(${((1 - n) * 105).toFixed(2)}%)`;
          accent.style.transform = `scaleX(${seg(le, 0.4, 0.6).toFixed(4)})`;
          if (roleEl) { const r = seg(le, 0.5, 0.5); roleEl.style.opacity = r; }
        } else {
          const p = seg(le, 0, 0.5, S);
          box.style.transform = `scale(${lerp(0.82, 1, p).toFixed(4)})`;
          box.style.opacity = clamp(le / 0.12);
          const n = seg(le, 0.12, 0.45);
          nameIn.style.opacity = n; nameIn.style.transform = `translateX(${((1 - n) * -0.4).toFixed(3)}em)`;
          if (roleEl) roleEl.style.opacity = seg(le, 0.25, 0.4);
        }
        // exit: slide back toward the anchored side and fade, faster than the entrance
        el.style.opacity = (1 - q).toFixed(3);
        el.style.transform = q > 0 ? `translateX(${(-q * 2.5 * dir).toFixed(3)}cqmin)` : '';
      },
    };
  },
});

export default LowerThird;

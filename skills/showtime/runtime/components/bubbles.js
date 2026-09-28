// chat-thread and notifications: generic messaging UI (no real app branding).
//
// ChatThread: messages pop in from the sender's corner; replies from the other side are
// preceded by a typing indicator; the thread scrolls up smoothly once it overflows.
// `stream: true` on a reply makes its words arrive in bursts, inking from grey (AI answers).
// Timing is automatic (reading time per message) unless a message has `at`.
//
//   <div data-st="chat-thread" data-messages='[{"from":"me","text":"Can you cut a 15 s teaser?"},
//        {"from":"them","text":"Done. Rendering now.","stream":true}]'></div>
//
// Notifications: banners drop in from the top with a spring and stack (newest on top).
//   <div data-st="notifications" data-items='[{"app":"Build","title":"Deploy finished","text":"12 s","at":0.5}]'></div>
import { define, h, clamp, ease, lerp, rng, aspectOf, safeInsets } from './core.js';

export const ChatThread = define({
  name: 'chat-thread',
  defaults: { at: 0, messages: [], typing: 0.9, gap: 0.35, speed: 1, names: false },
  setup(el, o, { motion }) {
    const msgs = (Array.isArray(o.messages) ? o.messages : []).map((m) => ({ ...m, me: m.from === 'me' || m.side === 'right' }));
    el.textContent = '';
    const col = h('div', { class: 'st-chat-col' });
    el.append(col);
    // schedule
    let t = 0.3;
    const items = msgs.map((m, i) => {
      const words = String(m.text || '').split(/\s+/).filter(Boolean);
      const typing = !m.me && o.typing > 0 ? Number(o.typing) : 0;
      const at = m.at != null ? Number(m.at) : t + typing;
      const bubble = h('div', { class: 'st-chat-msg ' + (m.me ? 'st-chat-me' : 'st-chat-them') },
        o.names && m.from && !m.me ? h('div', { class: 'st-chat-name' }, m.from) : null,
        h('div', { class: 'st-chat-bubble' }));
      const body = bubble.lastChild;
      let wordEls = null;
      if (m.stream) {
        wordEls = words.map((w) => h('span', { class: 'st-chat-word' }, w + ' '));
        body.append(...wordEls);
      } else body.textContent = m.text || '';
      col.append(bubble);
      // streamed words arrive in bursts (seeded gaps; zeros mean words land together)
      const r = rng(97 + i);
      let wt = 0;
      const wordTimes = words.map(() => { const g = r() < 0.3 ? 0 : 0.05 + r() * 0.16; wt += g / o.speed; return wt; });
      const readTime = m.stream ? wt + 0.4 : 0.45 + String(m.text || '').length * 0.028;
      t = at + readTime / o.speed + o.gap;
      return { m, at, typing, bubble, wordEls, wordTimes };
    });
    const typingEl = h('div', { class: 'st-chat-msg st-chat-them st-chat-typing' }, h('div', { class: 'st-chat-bubble' }, h('i'), h('i'), h('i')));
    col.append(typingEl);
    // measure final layout
    const tops = items.map((it) => it.bubble.offsetTop);
    const bottoms = items.map((it) => it.bubble.offsetTop + it.bubble.offsetHeight);
    const typingH = typingEl.offsetHeight;
    const viewH = el.clientHeight;
    const pad = parseFloat(getComputedStyle(el).paddingBottom) || 0;
    const S = ease('spring(0.36,0.7)'), E = ease(motion.easeOut), M = ease('power3.inOut');
    const scrollFor = (bottom) => Math.max(0, bottom - (viewH - pad));
    return {
      duration: t,
      sync: Object.fromEntries(items.map((it, i) => ['msg' + (i + 1), it.at])),
      update(lt) {
        let visibleBottom = 0, typingOn = null;
        items.forEach((it, i) => {
          const p = S(clamp((lt - it.at) / 0.34));
          const on = lt >= it.at;
          it.bubble.style.opacity = on ? clamp((lt - it.at) / 0.08).toFixed(3) : 0;
          it.bubble.style.transform = `scale(${lerp(0.72, 1, p).toFixed(4)})`;
          if (on) visibleBottom = bottoms[i];
          if (it.wordEls) it.wordEls.forEach((w, k) => {
            const q = clamp((lt - it.at - it.wordTimes[k]) / 0.27);
            w.style.opacity = lt >= it.at + it.wordTimes[k] ? 1 : 0;
            w.style.setProperty('--ink', q.toFixed(3));
          });
          if (it.typing && lt >= it.at - it.typing && lt < it.at) typingOn = { i, since: lt - (it.at - it.typing) };
        });
        // typing indicator sits where the next bubble will appear
        if (typingOn) {
          const y = tops[typingOn.i];
          typingEl.style.opacity = clamp(typingOn.since / 0.12).toFixed(3);
          typingEl.style.transform = `translateY(${(y - typingEl.offsetTop).toFixed(2)}px) scale(${lerp(0.8, 1, E(clamp(typingOn.since / 0.2))).toFixed(3)})`;
          Array.from(typingEl.firstChild.children).forEach((d, k) => {
            const ph = (typingOn.since / 0.9 - k * 0.18) * Math.PI * 2;
            d.style.opacity = (0.35 + 0.65 * Math.max(0, Math.sin(ph))).toFixed(3);
            d.style.transform = `translateY(${(-0.12 * Math.max(0, Math.sin(ph))).toFixed(3)}em)`;
          });
          visibleBottom = Math.max(visibleBottom, y + typingH);
        } else typingEl.style.opacity = 0;
        // scroll: ease toward the target whenever it changes (computed from the event times)
        let scroll = 0;
        const events = [];
        items.forEach((it, i) => { if (it.typing) events.push({ t: it.at - it.typing, b: tops[i] + typingH }); events.push({ t: it.at, b: bottoms[i] }); });
        events.sort((a, b) => a.t - b.t);
        let from = 0;
        for (const ev of events) {
          if (lt < ev.t) break;
          const target = scrollFor(ev.b);
          scroll = lerp(from, target, M(clamp((lt - ev.t) / 0.35)));
          from = scroll;
        }
        col.style.transform = `translateY(${(-scroll).toFixed(2)}px)`;
      },
    };
  },
});

export const Notifications = define({
  name: 'notifications',
  defaults: { at: 0, items: [], every: 0.9, max: 4, position: 'top', top: null },
  setup(el, o) {
    const items = (Array.isArray(o.items) ? o.items : []).map((it, i) => ({ ...it, at: it.at != null ? Number(it.at) : 0.3 + i * o.every }));
    el.textContent = '';
    const frame = el.closest('.scene, .stage') || document.body;
    const aspect = aspectOf(frame);
    const safe = safeInsets(aspect);
    // `top` (any CSS length) or a `top` from the page's own CSS wins over the safe-area default
    if (o.top != null && o.top !== '') el.style.top = /^-?[\d.]+$/.test(String(o.top)) ? o.top + '%' : String(o.top);
    else if (o.position === 'top' && getComputedStyle(el).top === 'auto') el.style.top = ((safe.top + 0.01) * 100).toFixed(2) + '%';
    const cards = items.map((it) => {
      const icon = it.icon ? (/\.(svg|png|jpe?g|webp)$/i.test(it.icon) ? h('img', { src: it.icon, alt: '' }) : h('span', {}, it.icon)) : h('span', {}, (it.app || '•').slice(0, 1));
      const c = h('div', { class: 'st-note' },
        h('div', { class: 'st-note-icon' }, icon),
        h('div', { class: 'st-note-body' },
          h('div', { class: 'st-note-head' }, h('span', { class: 'st-note-app' }, it.app || ''), h('span', { class: 'st-note-time' }, it.time || 'now')),
          it.title ? h('div', { class: 'st-note-title' }, it.title) : null,
          it.text ? h('div', { class: 'st-note-text' }, it.text) : null));
      el.append(c);
      return c;
    });
    const hts = cards.map((c) => c.offsetHeight);
    const gap = parseFloat(getComputedStyle(el).rowGap) || 10;
    const S = ease('spring(0.42,0.74)');
    return {
      duration: (items.at(-1)?.at ?? 0) + 0.8,
      sync: Object.fromEntries(items.map((it, i) => ['note' + (i + 1), it.at])),
      update(lt) {
        // each card's y = sum of the heights of newer visible cards above it (springing)
        cards.forEach((c, i) => {
          const p = S(clamp((lt - items[i].at) / 0.55));
          let y = 0;
          for (let j = i + 1; j < cards.length; j++) y += (hts[j] + gap) * S(clamp((lt - items[j].at) / 0.55));
          const depth = cards.slice(i + 1).filter((_, k) => lt >= items[i + 1 + k].at).length;
          const hidden = depth >= o.max;
          c.style.opacity = lt < items[i].at || hidden ? 0 : clamp((lt - items[i].at) / 0.1).toFixed(3);
          c.style.transform = `translateY(calc(${(y).toFixed(2)}px + ${((1 - p) * -120).toFixed(2)}%)) scale(${(1 - Math.min(depth, 3) * 0.03).toFixed(3)})`;
          c.style.zIndex = String(100 + i);
        });
      },
    };
  },
});

export default ChatThread;

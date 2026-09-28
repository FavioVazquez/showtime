// cursor and keystrokes: a synthetic pointer for product demos and a keycap overlay.
//
// Cursor travels between waypoints on a slight arc with an ease-in-out, arriving exactly at
// each waypoint's `at` (so clicks line up with narration or SFX). A click dips the cursor,
// presses the target (CSS `scale`, so the target's own transform is untouched) and throws a
// ripple ring. `hover: true` marks the target with [data-st-hover] until the cursor leaves.
// Waypoints take x/y in % of the frame, or `target: "#selector"` (its centre, plus dx/dy %).
//
//   <div data-st="cursor" data-path='[{"at":0,"x":80,"y":80},{"at":1.2,"target":"#buy","click":true}]'></div>
//
// Keystrokes shows keycaps ("⌘ K", "Ctrl+Shift+P") or typed text in a bubble, bottom centre.
//   <div data-st="keystrokes" data-items='[{"at":1,"keys":"⌘ K"},{"at":2.2,"text":"deploy prod"}]'></div>
import { define, h, clamp, ease, lerp, hash, aspectOf, forceVisible } from './core.js';

const ARROW = '<svg viewBox="0 0 24 24"><path d="M4.2 2.6 19.4 13.9c.6.5.3 1.4-.5 1.5l-6.1.6 3.5 6.5c.2.5 0 1-.4 1.2l-2 1c-.5.2-1 0-1.2-.4l-3.4-6.5-4.4 4.2c-.6.5-1.5.1-1.5-.7V3.3c0-.7.8-1.1 1.4-.7Z"/></svg>';
const HAND = '<svg viewBox="0 0 24 24"><path d="M9.6 1.8c1 0 1.8.8 1.8 1.8v6.2l1-.2c.9 0 1.6.6 1.8 1.4l.9-.1c.9 0 1.6.6 1.8 1.4l.6-.1c1 0 1.9.8 1.9 1.9v4.3c0 3-2.4 5.4-5.4 5.4h-2.3c-1.6 0-3.1-.8-4.1-2.1l-3.6-4.8c-.6-.8-.4-1.9.4-2.4.7-.5 1.7-.4 2.3.2l1.2 1.3V3.6c0-1 .8-1.8 1.8-1.8Z"/></svg>';

export const Cursor = define({
  name: 'cursor',
  defaults: { at: 0, path: [], style: 'arrow', size: 3.4, arc: 0.12, hideAfter: null, seed: 5 },
  setup(el, o, { motion }) {
    // coordinates are relative to the cursor layer itself (it fills its container)
    el.textContent = '';
    const pointer = h('div', { class: 'st-cursor-ptr st-cursor-' + o.style, html: o.style === 'dot' ? '' : o.style === 'hand' ? HAND : ARROW });
    const ripple = h('div', { class: 'st-cursor-ripple' });
    el.append(ripple, pointer);
    el.style.setProperty('--cursor-size', o.size + 'cqmin');
    const fr = el.getBoundingClientRect();
    const W = fr.width || innerWidth, H = fr.height || innerHeight;
    // resolve waypoints to pixels in the frame
    const pts = (Array.isArray(o.path) ? o.path : []).map((p) => {
      let x = (Number(p.x ?? 50) / 100) * W, y = (Number(p.y ?? 50) / 100) * H, target = null;
      if (p.target) {
        target = document.querySelector(p.target);
        if (!target) console.warn(`[showtime] cursor: target ${p.target} not found`);
        else {
          const release = forceVisible(target);
          const r = target.getBoundingClientRect();
          release();
          x = r.left - fr.left + r.width * (0.5 + (Number(p.dx) || 0) / 100);
          y = r.top - fr.top + r.height * (0.5 + (Number(p.dy) || 0) / 100);
          if (p.click || p.press) target.style.transformOrigin ||= '50% 50%';
        }
      }
      return { at: Number(p.at) || 0, x, y, dx: Number(p.dx) || 0, dy: Number(p.dy) || 0, click: !!p.click, hover: !!p.hover, target, dur: p.dur != null ? Number(p.dur) : null };
    }).sort((a, b) => a.at - b.at);
    if (!pts.length) pts.push({ at: 0, x: W * 0.7, y: H * 0.7 });
    // travel time scales with distance (0.35-0.9 s) unless given; the move ends at `at`
    for (let i = 1; i < pts.length; i++) {
      const a = pts[i - 1], b = pts[i];
      const d = Math.hypot(b.x - a.x, b.y - a.y);
      const want = b.dur ?? clamp(0.35 + (d / Math.max(W, H)) * 0.8, 0.35, 0.9);
      b.dur = Math.min(want, Math.max(0.1, b.at - a.at - (a.click ? 0.2 : 0)));
      b.side = hash(i, o.seed) < 0.5 ? -1 : 1;
    }
    const M = ease('power2.inOut'), R = ease('power2.out');
    const lastAt = pts[pts.length - 1].at;
    return {
      duration: lastAt + 0.6,
      sync: Object.fromEntries(pts.filter((p) => p.click).map((p, i) => ['click' + (i + 1), p.at + 0.05])),
      // the stage seeks CSS animations after the onSeek handlers: measure targets in a microtask,
      // once every transform (keyframed camera moves included) is at this frame's time
      update(lt) { return Promise.resolve().then(() => draw(lt)); },
    };
    function draw(lt) {
        // targets are tracked live, so the cursor follows elements that move or tilt
        const box = el.getBoundingClientRect();
        for (const p of pts) {
          if (!p.target || !p.target.isConnected) continue;
          const r = p.target.getBoundingClientRect();
          if (!r.width && !r.height) continue;
          p.x = r.left - box.left + r.width * (0.5 + (p.dx || 0) / 100);
          p.y = r.top - box.top + r.height * (0.5 + (p.dy || 0) / 100);
        }
        // position
        let x = pts[0].x, y = pts[0].y;
        for (let i = 1; i < pts.length; i++) {
          const a = pts[i - 1], b = pts[i];
          if (lt >= b.at) { x = b.x; y = b.y; continue; }
          if (lt > b.at - b.dur) {
            const p = M(clamp((lt - (b.at - b.dur)) / b.dur));
            const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1;
            const bow = Math.sin(Math.PI * p) * d * o.arc * b.side;
            x = lerp(a.x, b.x, p) + (-dy / d) * bow;
            y = lerp(a.y, b.y, p) + (dx / d) * bow;
          } else { x = a.x; y = a.y; }
          break;
        }
        // clicks: dip + ripple + target press; hover flags
        let dip = 0, rip = -1, rx = 0, ry = 0;
        for (const p of pts) {
          if (p.click) {
            const k = lt - p.at - 0.05;
            if (k >= 0 && k < 0.22) dip = Math.sin(Math.PI * (k / 0.22));
            if (k >= 0 && k < 0.45) { rip = k / 0.45; rx = p.x; ry = p.y; }
            if (p.target) p.target.style.scale = k >= 0 && k < 0.22 ? (1 - 0.045 * Math.sin(Math.PI * (k / 0.22))).toFixed(4) : '';
          }
          if (p.hover && p.target) {
            const next = pts[pts.indexOf(p) + 1];
            const on = lt >= p.at - 0.05 && (!next || lt < next.at - next.dur * 0.5);
            p.target.toggleAttribute('data-st-hover', on);
          }
        }
        let vis = clamp(lt / 0.2);
        if (o.hideAfter != null) vis *= 1 - clamp((lt - lastAt - Number(o.hideAfter)) / 0.3);
        pointer.style.opacity = vis.toFixed(3);
        pointer.style.transform = `translate(${x.toFixed(2)}px, ${y.toFixed(2)}px) scale(${(1 - 0.15 * dip).toFixed(4)})`;
        if (rip >= 0) {
          ripple.style.opacity = ((1 - R(rip)) * 0.55).toFixed(3);
          ripple.style.transform = `translate(${rx.toFixed(2)}px, ${ry.toFixed(2)}px) scale(${lerp(0.2, 1, R(rip)).toFixed(4)})`;
        } else ripple.style.opacity = 0;
    }
  },
});

// Modifier and control glyphs drawn as SVG so keycaps look the same on every OS (the
// bundled fonts do not cover these symbols, and system fallbacks differ per platform).
const KEY_ICONS = {
  '⌘': 'M9 6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3z',
  '⇧': 'M12 4 3.5 12.5H8V20h8v-7.5h4.5z',
  '⌥': 'M3 6h5.5l7 12H21M14.5 6H21',
  '⌃': 'M6 14.5 12 8.5l6 6',
  '↵': 'M20 5v7a3 3 0 0 1-3 3H5.5M9.5 11l-4 4 4 4', '⏎': 'M20 5v7a3 3 0 0 1-3 3H5.5M9.5 11l-4 4 4 4',
  '⌫': 'M21 5.5H9l-6 6.5 6 6.5h12zM11.5 9l6 6M17.5 9l-6 6',
  '⇥': 'M3.5 12h14M13.5 8l4 4-4 4M20.5 6v12',
  '←': 'M19 12H5M11 6l-6 6 6 6', '→': 'M5 12h14M13 6l6 6-6 6', '↑': 'M12 19V5M6 11l6-6 6 6', '↓': 'M12 5v14M6 13l6 6 6-6',
};
function keyCap(k) {
  const cap = h('kbd', { class: 'st-key' + (k.length > 1 ? ' st-key-wide' : '') });
  if (KEY_ICONS[k]) cap.innerHTML = `<svg viewBox="0 0 24 24" class="st-key-icon"><path d="${KEY_ICONS[k]}"/></svg>`;
  else cap.textContent = k;
  return cap;
}

export const Keystrokes = define({
  name: 'keystrokes',
  defaults: { at: 0, items: [], hold: 1.5 },
  setup(el, o) {
    const frame = el.closest('.scene, .stage') || document.body;
    const aspect = aspectOf(frame);
    el.style.bottom = aspect === 'tall' ? '30%' : '9%';
    el.textContent = '';
    const items = (Array.isArray(o.items) ? o.items : []).map((it) => ({ ...it, at: Number(it.at) || 0 })).sort((a, b) => a.at - b.at);
    const groups = items.map((it, i) => {
      let node, caps = [];
      if (it.text != null) {
        node = h('div', { class: 'st-keys-text' }, h('span', {}, ''));
      } else {
        const keys = String(it.keys || '').split(/\s*\+\s*|\s+/).filter(Boolean);
        caps = keys.map(keyCap);
        node = h('div', { class: 'st-keys-row' }, ...caps);
      }
      el.append(node);
      const next = items[i + 1];
      const typeDur = it.text != null ? String(it.text).length * 0.055 : caps.length * 0.07;
      const end = Math.min(next ? next.at : Infinity, it.at + typeDur + Number(o.hold));
      return { it, node, caps, typeDur, end };
    });
    const S = ease('spring(0.3,0.6)');
    return {
      duration: groups.length ? groups[groups.length - 1].end + 0.3 : 0,
      update(lt) {
        for (const g of groups) {
          const on = lt >= g.it.at && lt < g.end + 0.3;
          g.node.style.display = on ? '' : 'none';
          if (!on) continue;
          const vis = clamp((lt - g.it.at) / 0.15) * (1 - clamp((lt - g.end) / 0.3));
          g.node.style.opacity = vis.toFixed(3);
          g.node.style.transform = `translateY(${((1 - clamp((lt - g.it.at) / 0.15)) * 1).toFixed(3)}cqmin)`;
          if (g.it.text != null) {
            const s = String(g.it.text).slice(0, Math.floor(clamp((lt - g.it.at) / Math.max(0.01, g.typeDur)) * String(g.it.text).length));
            const span = g.node.firstChild;
            if (span.textContent !== s) span.textContent = s;
          } else {
            g.caps.forEach((c, k) => {
              const t0 = g.it.at + k * 0.07;
              const p = S(clamp((lt - t0) / 0.3));
              const press = lt >= t0 && lt < t0 + 0.12 ? Math.sin(Math.PI * (lt - t0) / 0.12) : 0;
              c.style.opacity = clamp((lt - t0) / 0.06).toFixed(3);
              c.style.transform = `translateY(${(press * 0.25).toFixed(3)}em) scale(${lerp(0.7, 1, p).toFixed(4)})`;
            });
          }
        }
      },
    };
  },
});

export default Cursor;

// portal: the window the camera flies through in a `through` transition.
//
// Any element can be a portal: `data-portal` on a window, a card, a phone screen or a video tile
// makes its box (with its border-radius) the opening. `data-portal="counter"` on a single letter
// (<span data-portal="counter">o</span>) makes the enclosed hole of the glyph the opening: the
// counter of an o, a, e, d, g, p, q, b, 0, 6, 8 or 9, measured from the real font once.
//
// portalShape(el, origin) -> { x, y, w, h, rx, ry, kind: 'box' | 'ellipse', radius } in the
// coordinates of `origin` (a DOMRect; the transition's parent), for the element as it is on screen
// right now (its transforms included).

const holeCache = new WeakMap();

/** The enclosed counter of the first glyph of el, as fractions of the element's box, or null. */
export function counterOf(el) {
  if (holeCache.has(el)) return holeCache.get(el);
  const text = (el.textContent || '').trim();
  const ch = text ? Array.from(text)[0] : '';
  let res = null;
  if (ch) {
    const cs = getComputedStyle(el);
    const fs = parseFloat(cs.fontSize) || 16;
    // measure where the glyph's box and baseline sit inside the element (layout, no transforms)
    const lr = el.getBoundingClientRect();
    const w = el.offsetWidth || lr.width || fs, hgt = el.offsetHeight || lr.height || fs;
    const mk = document.createElement('i');
    mk.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline';
    el.appendChild(mk);
    // baseline as a fraction of the element's height (ratios survive a uniform scale transform)
    const er = el.getBoundingClientRect(), mr = mk.getBoundingClientRect();
    const baseline = er.height ? (mr.top - er.top) / er.height * hgt : fs * 0.8;
    el.removeChild(mk);
    const S = 4, pad = Math.ceil(fs * 0.25 * S);
    const Wc = Math.ceil(fs * 1.5 * S) + 2 * pad, Hc = Math.ceil(fs * 1.7 * S);
    const c = document.createElement('canvas');
    c.width = Wc; c.height = Hc;
    const g = c.getContext('2d', { willReadFrequently: true });
    g.font = `${cs.fontStyle} ${cs.fontWeight} ${fs * S}px ${cs.fontFamily}`;
    try { if ('fontVariationSettings' in g) g.fontVariationSettings = cs.fontVariationSettings; } catch { /* older canvas */ }
    g.fillStyle = '#fff';
    const by = Math.round(Hc * 0.75);
    g.fillText(ch, pad, by);
    const d = g.getImageData(0, 0, Wc, Hc).data, N = Wc * Hc;
    const ink = new Uint8Array(N), seen = new Uint8Array(N);
    for (let i = 0; i < N; i++) ink[i] = d[i * 4 + 3] > 100 ? 1 : 0;
    // flood the outside from the corner; whatever blank is left is enclosed by ink
    const st = [0]; seen[0] = 1;
    while (st.length) {
      const i = st.pop(), x = i % Wc, y = (i / Wc) | 0;
      if (x > 0 && !seen[i - 1] && !ink[i - 1]) { seen[i - 1] = 1; st.push(i - 1); }
      if (x < Wc - 1 && !seen[i + 1] && !ink[i + 1]) { seen[i + 1] = 1; st.push(i + 1); }
      if (y > 0 && !seen[i - Wc] && !ink[i - Wc]) { seen[i - Wc] = 1; st.push(i - Wc); }
      if (y < Hc - 1 && !seen[i + Wc] && !ink[i + Wc]) { seen[i + Wc] = 1; st.push(i + Wc); }
    }
    let x0 = 1e9, x1 = -1, y0 = 1e9, y1 = -1, n = 0;
    for (let i = 0; i < N; i++) if (!ink[i] && !seen[i]) {
      const x = i % Wc, y = (i / Wc) | 0; n++;
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
    }
    if (n > 16) {
      // canvas px -> element px (x from the glyph's left edge, y from the baseline)
      const cx = ((x0 + x1) / 2 - pad) / S, cy = baseline + ((y0 + y1) / 2 - by) / S;
      res = { fx: cx / w, fy: cy / hgt, frx: (x1 - x0) / 2 / S / w, fry: (y1 - y0) / 2 / S / hgt };
    }
  }
  if (!res) console.warn(`[showtime] portal: "${ch}" has no enclosed counter; using the element's box`);
  holeCache.set(el, res);
  return res;
}

/** The opening of a portal element on screen, relative to `origin` (a DOMRect). */
export function portalShape(el, origin) {
  const r = el.getBoundingClientRect();
  const ox = origin ? origin.left : 0, oy = origin ? origin.top : 0;
  const mode = (el.getAttribute('data-portal') || '').trim();
  if (mode === 'counter' || mode === 'letter') {
    const hole = counterOf(el);
    if (hole) {
      const cx = r.left - ox + hole.fx * r.width, cy = r.top - oy + hole.fy * r.height;
      const rx = hole.frx * r.width, ry = hole.fry * r.height;
      return { kind: 'ellipse', x: cx - rx, y: cy - ry, w: 2 * rx, h: 2 * ry, rx, ry, radius: 0 };
    }
  }
  const layoutW = el.offsetWidth || r.width || 1;
  const k = r.width / layoutW;
  const radius = (parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0) * k;
  return { kind: 'box', x: r.left - ox, y: r.top - oy, w: r.width, h: r.height, rx: r.width / 2, ry: r.height / 2, radius };
}

// In-page audits used by `showtime check`. Each exported function is passed to
// page.evaluate(), so it must be self-contained (no closures over module scope).

/**
 * Text layout snapshot at the current seek position.
 * o: { width, height, full: boolean, labelGapEm?: number (SVG labels closer than this are crowded, default 0.15) }
 * -> { blocks: [{bid, text, len, rect, opacity, fontSize, scale, decor, flash, sel, clipped, offCanvas, onCanvas, caption, moving}],
 *      leaves: [{lid, bid, rect, color:[r,g,b,a], opacity, readOpacity, fontSize, scale, decor, weight, outlined, sel}] (full only),
 *      readOpacity = the opacity contrast is judged at (a caption word's: without its card fade or karaoke dim),
 *      scale = on-screen size / CSS size (transforms such as a camera push or a scaled mockup),
 *      decor = inside [data-st-decor] (UI mockups, thumbnails: detail, not copy the viewer must read)
 *      flash = inside [data-st-flash] (a flash word: texture in the showreel tone, scripts/lib/showreel.mjs)
 *      overlaps: [[bidA, bidB, frac]] (full only), heavy: n (full only),
 *      covers: [{text, by, sel, bySel, rect}] (full only): text hidden under a small opaque element that
 *      carries its own text (a badge, callout or pill on top of a label),
 *      svgPairs: [{kind: 'overlap'|'crowded', dir: 'touch'|'row'|'stack', gid, a, b, lids, gap, em, frac, px, decor,
 *      moving, sel}] (full only): SVG labels within one <svg> whose glyphs overlap or touch, or that sit side by
 *      side (or one above the other) closer than labelGapEm }
 */
export function textSnapshot(o) {
  const W = o.width, H = o.height;
  const csCache = new Map();
  const cs = (el) => { let s = csCache.get(el); if (!s) { s = getComputedStyle(el); csCache.set(el, s); } return s; };
  const blurCache = new Map();
  function blurred(el) {
    if (!el || el.nodeType !== 1) return false;
    if (blurCache.has(el)) return blurCache.get(el);
    const f = cs(el).filter;
    const v = (f && f !== 'none' && /blur\((?!0px)/.test(f)) || blurred(el.parentElement);
    blurCache.set(el, v);
    return v;
  }
  const opCache = new Map();
  function opacity(el) {
    if (!el || el.nodeType !== 1) return 1;
    if (opCache.has(el)) return opCache.get(el);
    const s = cs(el);
    let v = s.display === 'none' ? 0 : parseFloat(s.opacity);
    if (isNaN(v)) v = 1;
    if (v > 0) v *= opacity(el.parentElement);
    opCache.set(el, v);
    return v;
  }
  const INLINE = /^(inline|inline-block|inline-flex|inline-grid|contents|ruby|ruby-text)$/;
  function blockOf(el) {
    let e = el;
    while (e && e !== document.body && INLINE.test(cs(e).display)) e = e.parentElement;
    return e || el;
  }
  function sel(el) {
    if (el.id) return '#' + el.id;
    const parts = [];
    let e = el;
    for (let i = 0; e && e.nodeType === 1 && i < 3; i++, e = e.parentElement) {
      let p = e.tagName.toLowerCase();
      if (e.id) { parts.unshift('#' + e.id + ' ' + p); break; }
      if (e.classList && e.classList.length) p += '.' + [...e.classList].slice(0, 2).join('.');
      parts.unshift(p);
    }
    return parts.join(' > ');
  }
  const cnv = document.createElement('canvas'); cnv.width = cnv.height = 1;
  const g = cnv.getContext('2d', { willReadFrequently: true });
  function rgba(str) {
    g.clearRect(0, 0, 1, 1); g.fillStyle = '#000'; g.fillStyle = str; g.fillRect(0, 0, 1, 1);
    const d = g.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  }
  let nextId = Number(document.documentElement.getAttribute('data-st-next') || 1);
  function idOf(el, attr) {
    let v = el.getAttribute(attr);
    if (!v) { v = String(nextId++); el.setAttribute(attr, v); }
    return v;
  }
  // how much transforms (scale, 3D tilt) shrink or grow this element's text on screen
  const scaleCache = new Map();
  function scaleOf(el) {
    if (scaleCache.has(el)) return scaleCache.get(el);
    const hgt = el.offsetHeight, r = el.getBoundingClientRect();
    const v = hgt > 0 && r.height > 0 ? Math.max(0.05, Math.min(4, r.height / hgt)) : 1;
    scaleCache.set(el, v);
    return v;
  }
  // SVG text: font-size is in user units; the element's transforms and the viewBox scale it (a map
  // label in <g transform="scale(2)"> at font-size 17 is ~34 px). CSS transforms outside the <svg>
  // are measured on the block, like HTML text.
  function svgScale(el) {
    if (typeof SVGElement === 'undefined' || !(el instanceof SVGElement) || !el.getCTM) return 1;
    try {
      const m = el.getCTM();
      const k = m ? Math.hypot(m.b, m.d) : 1;
      return k > 0.01 && k < 100 ? k : 1;
    } catch { return 1; }
  }
  const decorOf = (el) => !!(el.closest && el.closest('[data-st-decor]'));
  // flash word (data-st-flash): texture in the showreel tone, may leave before its reading time (scripts/lib/showreel.mjs)
  const flashOf = (el) => !!(el.closest && el.closest('[data-st-flash]'));
  // mid-way through a short entrance on the element or an ancestor: a finite animation (<= 1.5 s) of
  // opacity, colour, filter or a clip/mask (a slow push-in on the scene is not an entrance)
  const ENTER_PROPS = /^(opacity|color|filter|backdropFilter|clipPath|mask|maskImage|webkitMaskImage|backgroundColor|background)$/;
  function animatingOf(el) {
    for (let e = el; e && e !== document.body && e !== document.documentElement; e = e.parentElement) {
      for (const a of (e.getAnimations ? e.getAnimations() : [])) {
        const ct = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : null;
        if (!ct || ct.iterations === Infinity || ct.progress === null || !(ct.progress > 0.001 && ct.progress < 0.999)) continue;
        if (!(Number(ct.activeDuration) <= 1500)) continue;
        let props = [];
        try { props = (a.effect.getKeyframes() || []).flatMap((k) => Object.keys(k)); } catch { props = []; }
        if (props.some((k) => ENTER_PROPS.test(k))) return true;
      }
    }
    return false;
  }
  const union = (a, b) => (!a ? { ...b } : { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), r: Math.max(a.r, b.r), b: Math.max(a.b, b.b) });
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
  const leafMap = new Map();
  const range = document.createRange();
  // glyph ink: a line box includes the font's ascent/descent (big display type has a lot of empty
  // leading), so overlaps are measured on where the letters are actually painted
  const inkCanvas = document.createElement('canvas').getContext('2d');
  const inkCache = new Map();
  function inkMetrics(el, text) {
    const s = cs(el);
    const font = `${s.fontStyle} ${s.fontWeight} ${s.fontSize} ${s.fontFamily}`;
    const key = font + '|' + text.slice(0, 64);
    if (inkCache.has(key)) return inkCache.get(key);
    let m = null;
    try {
      inkCanvas.font = font;
      const t = inkCanvas.measureText(text.slice(0, 64));
      if (t.fontBoundingBoxAscent !== undefined && isFinite(t.actualBoundingBoxAscent)) {
        m = { fa: t.fontBoundingBoxAscent, fd: t.fontBoundingBoxDescent, aa: t.actualBoundingBoxAscent, ad: t.actualBoundingBoxDescent };
      }
    } catch { m = null; }
    inkCache.set(key, m);
    return m;
  }
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.nodeValue || !n.nodeValue.trim()) continue;
    const p = n.parentElement;
    if (!p || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|TITLE|TEXTAREA)$/.test(p.tagName)) continue;
    if (p.closest('[data-st-ignore]')) continue;
    range.selectNodeContents(n);
    const rs = range.getClientRects();
    let box = null, ink = null;
    const im = inkMetrics(p, n.nodeValue.trim());
    for (const r of rs) {
      if (!(r.width > 0.5 && r.height > 0.5)) continue;
      box = union(box, { x: r.left, y: r.top, r: r.right, b: r.bottom });
      if (im && im.fa + im.fd > 0) {
        const k = r.height / (im.fa + im.fd);   // on-screen scale of this line fragment
        ink = union(ink, { x: r.left, y: r.top + (im.fa - im.aa) * k, r: r.right, b: r.top + (im.fa + im.ad) * k });
      } else ink = union(ink, { x: r.left, y: r.top, r: r.right, b: r.bottom });
    }
    if (!box) continue;
    const op = opacity(p);
    if (op <= 0.02 || cs(p).visibility !== 'visible') continue;
    let leaf = leafMap.get(p);
    if (!leaf) { leaf = { el: p, box: null, ink: null, chars: 0 }; leafMap.set(p, leaf); }
    leaf.box = union(leaf.box, box);
    leaf.ink = union(leaf.ink, ink);
    leaf.chars += n.nodeValue.trim().length;
  }
  // Text fully covered by an opaque element painted above it (e.g. the outgoing scene under the
  // incoming one during a transition) is not visible: leave it out of layout and contrast checks.
  const TRANSLUCENT = /transparent|rgba\([^)]*,\s*(0?\.\d+|0)\s*\)|\/\s*(0?\.\d+|0)\s*\)/;
  function paintsOpaque(e) {
    if (e.hasAttribute && e.hasAttribute('data-st-gl')) return true; // a WebGL transition frame (opaque)
    const s = cs(e);
    if (rgba(s.backgroundColor)[3] >= 0.9) return true;
    const bi = s.backgroundImage;
    return !!bi && bi !== 'none' && /gradient\(/.test(bi) && !/url\(/.test(bi) && !TRANSLUCENT.test(bi);
  }
  // -> null when (some of) the text is visible, else the opaque element on top of it
  function covered(el, box) {
    const pts = [[0.5, 0.5], [0.15, 0.5], [0.85, 0.5], [0.5, 0.2], [0.5, 0.8]];
    let tested = 0, top = null;
    for (const [fx, fy] of pts) {
      const x = box.x + (box.r - box.x) * fx, y = box.y + (box.b - box.y) * fy;
      if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
      tested++;
      const hit = document.elementFromPoint(x, y);
      if (!hit || hit === el || el.contains(hit) || hit.contains(el)) return null;
      let opaque = null;
      for (let e = hit; e && !e.contains(el); e = e.parentElement) {
        if (opacity(e) < 0.9) break;
        if (paintsOpaque(e)) { opaque = e; break; }
      }
      if (!opaque) return null;
      top = top || opaque;
    }
    return tested > 0 ? top : null;
  }
  // a badge: a small opaque box with its own text, not a scene or a transition layer
  function isBadge(e) {
    if (!e || e.nodeType !== 1 || e.hasAttribute('data-start') || e.hasAttribute('data-st-gl') || e.tagName === 'CANVAS') return false;
    const r = e.getBoundingClientRect();
    if (r.width * r.height > 0.25 * W * H) return false;
    const t = (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim();
    return t.length > 0 && t.length <= 80;
  }
  // Text scrolled or masked out of an overflow:hidden/clip ancestor (odometer digit reels, mask
  // reveals, ticker rows) is not visible either; keep the visible part for overlap tests.
  const clipCache = new Map();
  function clipRect(el) {
    if (!el || el === document.body || el === document.documentElement) return null;
    if (clipCache.has(el)) return clipCache.get(el);
    let r = clipRect(el.parentElement);
    const s = cs(el);
    const ins = s.clipPath && s.clipPath !== 'none' ? /inset\(([^)]*)\)/.exec(s.clipPath) : null;
    if (/(hidden|clip)/.test(s.overflowX + ' ' + s.overflowY) || ins) {
      const c = el.getBoundingClientRect();
      const own = { x: c.left, y: c.top, r: c.right, b: c.bottom };
      if (ins) {
        // clip-path: inset(top right bottom left [round ...]) in px or % of the box (a wipe or mask reveal)
        const v = ins[1].split(/\s+round\s+/)[0].trim().split(/\s+/);
        const q = [v[0], v[1] ?? v[0], v[2] ?? v[0], v[3] ?? v[1] ?? v[0]];
        const px = (x, len) => (/%$/.test(x) ? (parseFloat(x) / 100) * len : parseFloat(x) || 0);
        own.y += px(q[0], c.height); own.r -= px(q[1], c.width); own.b -= px(q[2], c.height); own.x += px(q[3], c.width);
      }
      r = r ? { x: Math.max(r.x, own.x), y: Math.max(r.y, own.y), r: Math.min(r.r, own.r), b: Math.min(r.b, own.b) } : own;
    }
    clipCache.set(el, r);
    return r;
  }
  for (const [el, leaf] of [...leafMap]) {
    const c = clipRect(el), b = leaf.box;
    const ib = leaf.ink || b;
    if (!c) { leaf.vbox = b; leaf.ibox = ib; continue; }
    const v = { x: Math.max(b.x, c.x), y: Math.max(b.y, c.y), r: Math.min(b.r, c.r), b: Math.min(b.b, c.b) };
    const area = (q) => Math.max(0, q.r - q.x) * Math.max(0, q.b - q.y);
    if (area(v) < 0.15 * area(b)) { leafMap.delete(el); continue; }
    leaf.vbox = v;
    leaf.ibox = { x: Math.max(ib.x, c.x), y: Math.max(ib.y, c.y), r: Math.min(ib.r, c.r), b: Math.min(ib.b, c.b) };
  }
  // Hit testing skips elements with pointer-events: none, and components set it on their cards (a
  // lower third, captions, an overlay over a transition) and shader canvases: the hit would land on
  // the scene below and call the text covered. Make everything hit-testable while we look.
  const hitStyle = document.createElement('style');
  hitStyle.setAttribute('data-st-audit', '');
  hitStyle.textContent = '*, *::before, *::after { pointer-events: auto !important; }';
  (document.head || document.documentElement).append(hitStyle);
  const covers = [];
  try {
    for (const [el, leaf] of [...leafMap]) {
      const top = covered(el, leaf.box);
      if (!top) continue;
      if (o.full && isBadge(top) && opacity(el) >= 0.5) {
        covers.push({ decor: decorOf(el), text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80), by: (top.innerText || top.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80),
          sel: sel(el), bySel: sel(top), rect: { x: leaf.box.x, y: leaf.box.y, w: leaf.box.r - leaf.box.x, h: leaf.box.b - leaf.box.y } });
      }
      leafMap.delete(el);
    }
  } finally {
    hitStyle.remove();
  }
  const blocks = new Map();
  const leaves = [];
  for (const leaf of leafMap.values()) {
    const b = blockOf(leaf.el);
    const bid = idOf(b, 'data-st-bid');
    let blk = blocks.get(bid);
    if (!blk) {
      const text = (b.innerText || b.textContent || '').replace(/\s+/g, ' ').trim();
      blk = { bid, el: b, box: null, opacity: 0, fontSize: 0, scale: scaleOf(b), decor: decorOf(b), flash: flashOf(b), text: text.slice(0, 2000), len: text.length, sel: sel(b),
        caption: !!b.closest('[data-caption],[data-vo],[data-st-read]') };
      blocks.set(bid, blk);
    }
    blk.box = union(blk.box, leaf.box);
    blk.vbox = union(blk.vbox, leaf.vbox || leaf.box);
    blk.ibox = union(blk.ibox, leaf.ibox || leaf.vbox || leaf.box);
    const op = opacity(leaf.el);
    const s = cs(leaf.el);
    const fs = (parseFloat(s.fontSize) || 0) * svgScale(leaf.el);
    blk.opacity = Math.max(blk.opacity, op);
    blk.fontSize = Math.max(blk.fontSize, fs);
    if (o.full) {
      const outlined = (s.textShadow && s.textShadow !== 'none') || parseFloat(s.webkitTextStrokeWidth) > 0;
      const clipText = /text/.test(s.webkitBackgroundClip || s.backgroundClip || '');
      // SVG <text> is painted with `fill`, not `color`
      const svgFill = typeof SVGElement !== 'undefined' && leaf.el instanceof SVGElement && s.fill && s.fill !== 'none' && !/url\(/.test(s.fill) ? s.fill : null;
      const color = rgba(svgFill || (s.webkitTextFillColor && s.webkitTextFillColor !== s.color && !/rgba\(0, 0, 0, 0\)/.test(s.webkitTextFillColor) ? s.webkitTextFillColor : s.color));
      // a caption-karaoke word: its card's fade in/out and the dim of a word not yet said are timing states,
      // so its contrast is judged at the caption's own opacity (the word as it reads when it is spoken)
      const cap = leaf.el.closest && leaf.el.closest('.st-cap[data-caption]');
      leaves.push({ lid: idOf(leaf.el, 'data-st-lid'), bid, own: (leaf.el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60), rect: { x: leaf.box.x, y: leaf.box.y, w: leaf.box.r - leaf.box.x, h: leaf.box.b - leaf.box.y },
        color, opacity: op, readOpacity: cap ? opacity(cap) : op, fontSize: fs, scale: scaleOf(leaf.el), decor: blk.decor, weight: parseInt(s.fontWeight, 10) || 400, outlined, clipText, sel: sel(leaf.el), chars: leaf.chars, blurred: blurred(leaf.el),
        entering: animatingOf(leaf.el), portal: !!(leaf.el.closest && leaf.el.closest('[data-st-portal-word],[data-portal]')),
        family: s.fontFamily, style: s.fontStyle });
    }
  }
  document.documentElement.setAttribute('data-st-next', String(nextId));
  const out = [];
  for (const blk of blocks.values()) {
    const r = blk.box;
    const rect = { x: r.x, y: r.y, w: r.r - r.x, h: r.b - r.y };
    const ix = Math.max(0, Math.min(r.r, W) - Math.max(r.x, 0)), iy = Math.max(0, Math.min(r.b, H) - Math.max(r.y, 0));
    const inside = rect.w * rect.h > 0 ? (ix * iy) / (rect.w * rect.h) : 0;
    const offCanvas = inside > 0.2 && (r.x < -2 || r.y < -2 || r.r > W + 2 || r.b > H + 2);
    let clipped = null;
    if (o.full) {
      for (let e = blk.el; e && e !== document.body && e !== document.documentElement; e = e.parentElement) {
        const s = cs(e);
        if (!/(hidden|clip|scroll|auto)/.test(s.overflowX + ' ' + s.overflowY)) continue;
        // nothing overflows this box in layout terms (transform-independent, so a 3D-tilted
        // container whose projected rect differs from its layout size is not a false alarm)
        if (e.scrollWidth <= e.clientWidth + 2 && e.scrollHeight <= e.clientHeight + 2) continue;
        const c = e.getBoundingClientRect();
        const bl = parseFloat(s.borderLeftWidth) || 0, bt = parseFloat(s.borderTopWidth) || 0;
        const cx = c.left + bl, cy = c.top + bt, cr = c.left + bl + e.clientWidth, cb = c.top + bt + e.clientHeight;
        const over = Math.max(cx - r.x, cy - r.y, r.r - cr, r.b - cb);
        if (over > 2) {
          const vis = Math.max(0, Math.min(r.r, cr) - Math.max(r.x, cx)) * Math.max(0, Math.min(r.b, cb) - Math.max(r.y, cy));
          if (vis > 0) { clipped = { by: sel(e), px: Math.round(over) }; break; }
        }
      }
    }
    const v = blk.vbox || r;
    const iv = blk.ibox || v;
    out.push({ bid: blk.bid, text: blk.text, len: blk.len, rect, opacity: +blk.opacity.toFixed(3), fontSize: blk.fontSize, scale: +blk.scale.toFixed(3), decor: blk.decor, flash: blk.flash, sel: blk.sel,
      clipped, offCanvas, onCanvas: inside, caption: blk.caption, moving: !!(blk.el.closest && blk.el.closest('[data-st-moving]')), vrect: { x: v.x, y: v.y, w: v.r - v.x, h: v.b - v.y },
      irect: { x: iv.x, y: iv.y, w: Math.max(0, iv.r - iv.x), h: Math.max(0, iv.b - iv.y) } });
  }
  const res = { blocks: out };
  if (o.full) {
    const overlaps = [];
    const vis = out.filter((b) => b.opacity >= 0.5 && b.onCanvas > 0 && b.rect.w * b.rect.h > 4);
    const byId = new Map([...blocks.values()].map((b) => [b.bid, b.el]));
    for (let i = 0; i < vis.length && i < 150; i++) {
      for (let j = i + 1; j < vis.length && j < 150; j++) {
        // painted glyphs (ink), not line boxes: large display type has tall empty line boxes
        const A = vis[i].irect || vis[i].vrect, B = vis[j].irect || vis[j].vrect;
        const ix = Math.min(A.x + A.w, B.x + B.w) - Math.max(A.x, B.x), iy = Math.min(A.y + A.h, B.y + B.h) - Math.max(A.y, B.y);
        if (ix <= 1 || iy <= 1) continue;
        const ea = byId.get(vis[i].bid), eb = byId.get(vis[j].bid);
        if (ea.contains(eb) || eb.contains(ea)) continue;
        const frac = (ix * iy) / Math.max(1, Math.min(A.w * A.h, B.w * B.h));
        if (frac > 0.15) overlaps.push([vis[i].bid, vis[j].bid, +frac.toFixed(2), Math.round(Math.min(ix, iy))]);
      }
    }
    res.overlaps = overlaps;
    // SVG labels (chart values and axes, map names), pair by pair within each <svg>, on their painted
    // glyphs. The overlap test above only fires past 15% of the smaller text, so labels that touch or
    // sit shoulder to shoulder ("−0.02−0.01") pass it: here glyphs that touch at all, or labels side by
    // side on one row (or stacked in one column) closer than o.labelGapEm of the smaller font, are 'crowded'. An 'overlap' is only reported
    // for labels the block test cannot see (tspans or text folded into one block). `moving`: the
    // graphic is still growing or morphing (a chart sets data-st-moving); its settled frame is judged.
    const gapEm = Number.isFinite(o.labelGapEm) ? o.labelGapEm : 0.15;
    const groups = new Map();
    for (const [el, leaf] of leafMap) {
      if (typeof SVGElement === 'undefined' || !(el instanceof SVGElement)) continue;
      const root = el.closest('svg');
      if (!root || opacity(el) < 0.5) continue;
      const ib = leaf.ibox || leaf.vbox || leaf.box;
      if (!(ib.r - ib.x > 1 && ib.b - ib.y > 1) || ib.r < 0 || ib.b < 0 || ib.x > W || ib.y > H) continue;
      if (!groups.has(root)) groups.set(root, []);
      const blk = blockOf(root);
      groups.get(root).push({ el, blk: blockOf(el), text: el.closest('text') || el, ib, own: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60), lid: idOf(el, 'data-st-lid'),
        em: (parseFloat(cs(el).fontSize) || 0) * svgScale(el) * scaleOf(blk) });
    }
    const svgPairs = [];
    for (const [root, items] of groups) {
      if (items.length < 2) continue;
      const list = items.slice(0, 200);
      const gid = idOf(root, 'data-st-gid');
      const decor = decorOf(root);
      const moving = !!root.closest('[data-st-moving]');
      for (let i = 0; i < list.length; i++) {
        for (let j = i + 1; j < list.length; j++) {
          const a = list[i], b = list[j];
          if (a.text === b.text) continue; // tspans of one label
          const A = a.ib, B = b.ib;
          const iy = Math.min(A.b, B.b) - Math.max(A.y, B.y);
          const ix = Math.min(A.r, B.r) - Math.max(A.x, B.x);
          const hMin = Math.min(A.b - A.y, B.b - B.y), wMin = Math.min(A.r - A.x, B.r - B.x);
          const em = Math.min(a.em || hMin, b.em || hMin);
          const frac = ix > 1 && iy > 1 ? (ix * iy) / Math.max(1, Math.min((A.r - A.x) * (A.b - A.y), (B.r - B.x) * (B.b - B.y))) : 0;
          let kind = null, dir = null, gap = 0;
          if (frac > 0.15) { if (a.blk === b.blk) kind = 'overlap'; }                                   // separate blocks: reported above
          else if (ix > 1 && iy > 1) { kind = 'crowded'; dir = 'touch'; gap = -Math.min(ix, iy); }     // glyphs touch
          else if (iy > 0.3 * hMin && -ix < gapEm * em) { kind = 'crowded'; dir = 'row'; gap = -ix; }  // side by side on one row
          else if (ix > 0.3 * wMin && -iy < gapEm * em) { kind = 'crowded'; dir = 'stack'; gap = -iy; } // one right above the other
          if (!kind) continue;
          svgPairs.push({ kind, dir, gid, a: a.own, b: b.own, lids: [a.lid, b.lid], gap: +gap.toFixed(1), em: +em.toFixed(1), frac: +frac.toFixed(2), px: Math.round(Math.max(0, Math.min(ix, iy))),
            decor, moving, sel: sel(root) });
          if (svgPairs.length >= 400) break;
        }
      }
    }
    res.svgPairs = svgPairs;
    res.covers = covers;
    res.leaves = leaves.slice(0, 300);
    let heavy = 0;
    for (const el of document.querySelectorAll('body *')) {
      const s = cs(el);
      if ((s.backdropFilter && s.backdropFilter !== 'none') || /blur\((?:[1-9]\d|\d{3,})/.test(s.filter)) heavy++;
      if (heavy > 200) break;
    }
    res.heavy = heavy;
    res.gifs = [...document.images].filter((i) => /\.gif(\?|$)/i.test(i.currentSrc || i.src) && i.getClientRects().length).map((i) => i.currentSrc || i.src).slice(0, 5);
  }
  return res;
}

/** Hide (or restore) all text paint without changing layout; resolves after it is painted. */
export async function hideText(on) {
  const painted = () => (window.ST && window.ST._paint ? window.ST._paint() : Promise.resolve());
  let s = document.getElementById('st-hide-text');
  if (!on) { if (s) s.remove(); await painted(); return; }
  if (!s) {
    s = document.createElement('style');
    s.id = 'st-hide-text';
    s.textContent = '*,*::before,*::after{color:transparent!important;-webkit-text-fill-color:transparent!important;' +
      'text-shadow:none!important;-webkit-text-stroke-color:transparent!important;text-decoration-color:transparent!important;' +
      'caret-color:transparent!important}svg text,svg tspan,svg textPath{fill:transparent!important;stroke:transparent!important}';
    document.head.appendChild(s);
  }
  await painted();
}

/** Declared @font-face families and their load status. */
export function fontInfo() {
  const faces = [];
  document.fonts.forEach((f) => faces.push({ family: f.family.replace(/^["']|["']$/g, ''), weight: f.weight, style: f.style, status: f.status }));
  return faces;
}

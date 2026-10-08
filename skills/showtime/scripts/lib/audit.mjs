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
  // a CSS blur filter, or a shutter blur on this frame (data-st-blurring: the element is hidden and its copies,
  // smeared, are drawn in its place; it is on screen, judged at a sharp frame)
  function blurred(el) {
    if (!el || el.nodeType !== 1) return false;
    if (blurCache.has(el)) return blurCache.get(el);
    const f = cs(el).filter;
    const v = el.hasAttribute('data-st-blurring') || (f && f !== 'none' && /blur\((?!0px)/.test(f)) || blurred(el.parentElement);
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
    if (op <= 0.02 || (cs(p).visibility !== 'visible' && !p.closest('[data-st-blurring]'))) continue;
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
        // CSS zoom (an adopted artboard scaled to the frame): the rect is zoomed, client sizes and borders are not
        const z = e.currentCSSZoom || 1;
        const bl = (parseFloat(s.borderLeftWidth) || 0) * z, bt = (parseFloat(s.borderTopWidth) || 0) * z;
        const cx = c.left + bl, cy = c.top + bt, cr = c.left + bl + e.clientWidth * z, cb = c.top + bt + e.clientHeight * z;
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

/**
 * How opaque each text leaf ([data-st-lid], set by textSnapshot) is at the current frame, measured as the
 * contrast pass measures it: the element's opacity times its ancestors', times the alpha of its colour
 * (a caption-karaoke word at its caption's opacity, without the card fade or the karaoke dim).
 * lids: ['12', ...] -> { [lid]: { alpha, blurred, entering, on } | null (gone from the page) }
 *   on = the leaf has a box on the frame; entering = a short entrance animation (<= 1.5 s) runs on it
 */
export function leafAlpha(lids) {
  const out = {};
  const cnv = document.createElement('canvas'); cnv.width = cnv.height = 1;
  const g = cnv.getContext('2d', { willReadFrequently: true });
  const alphaOf = (str) => { g.clearRect(0, 0, 1, 1); g.fillStyle = '#000'; g.fillStyle = str; g.fillRect(0, 0, 1, 1); return g.getImageData(0, 0, 1, 1).data[3] / 255; };
  const opacity = (el) => {
    let v = 1;
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.display === 'none') return 0;
      const o = parseFloat(s.opacity);
      v *= Number.isFinite(o) ? o : 1;
      if (v <= 0) return 0;
    }
    return v;
  };
  const ENTER = /^(opacity|color|filter|backdropFilter|clipPath|mask|maskImage|webkitMaskImage|backgroundColor|background)$/;
  const entering = (el) => {
    for (let e = el; e && e !== document.body && e !== document.documentElement; e = e.parentElement) {
      for (const a of (e.getAnimations ? e.getAnimations() : [])) {
        const ct = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : null;
        if (!ct || ct.iterations === Infinity || ct.progress === null || !(ct.progress > 0.001 && ct.progress < 0.999)) continue;
        if (!(Number(ct.activeDuration) <= 1500)) continue;
        let props = [];
        try { props = (a.effect.getKeyframes() || []).flatMap((k) => Object.keys(k)); } catch { props = []; }
        if (props.some((k) => ENTER.test(k))) return true;
      }
    }
    return false;
  };
  const blurred = (el) => { for (let e = el; e && e.nodeType === 1; e = e.parentElement) { if (e.hasAttribute('data-st-blurring')) return true; const f = getComputedStyle(e).filter; if (f && f !== 'none' && /blur\((?!0px)/.test(f)) return true; } return false; };
  for (const lid of lids) {
    const el = document.querySelector(`[data-st-lid="${lid}"]`);
    if (!el) { out[lid] = null; continue; }
    const s = getComputedStyle(el);
    const svgFill = typeof SVGElement !== 'undefined' && el instanceof SVGElement && s.fill && s.fill !== 'none' && !/url\(/.test(s.fill) ? s.fill : null;
    const col = svgFill || (s.webkitTextFillColor && s.webkitTextFillColor !== s.color && !/rgba\(0, 0, 0, 0\)/.test(s.webkitTextFillColor) ? s.webkitTextFillColor : s.color);
    const cap = el.closest && el.closest('.st-cap[data-caption]');
    const r = el.getBoundingClientRect();
    const on = r.width > 1 && r.height > 1 && r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight &&
      (s.visibility === 'visible' || !!el.closest('[data-st-blurring]'));
    out[lid] = { alpha: on ? +(opacity(cap || el) * alphaOf(col)).toFixed(3) : 0, blurred: blurred(el), entering: entering(el), on };
  }
  return out;
}

/**
 * Caption-zone collisions at the current frame. The zone is where caption-karaoke's cards sit (every
 * card measured once at rest, unioned; the block is placed by the component: bottom band on wide and
 * square frames, from 62 % of the height on tall ones). While a caption card shows, any other visible
 * element that paints inside the zone is a hit: text, images, video, canvas, boxes with a background
 * or border, SVG shapes (reported per <svg>). Ignored: the captions, full-frame backgrounds (>= half
 * the frame, or full-width bands without text), anything under 10 % opacity, [data-st-ignore], and
 * intentional overlaps marked [data-st-caption-ok] (on the element or an ancestor).
 * o: { width, height, minOpacity?: 0.1 } -> { captions: n, captioned: bool, zone: {x,y,w,h}|null,
 *   hits: [{key, sel, text, kind, rect:{x,y,w,h}, overlap:{x,y,w,h}}] }
 */
export function captionCollisions(o) {
  const W = o.width, H = o.height, minOp = Number.isFinite(o.minOpacity) ? o.minOpacity : 0.1;
  const caps = [...document.querySelectorAll('.st-cap[data-caption]')];
  const res = { captions: caps.length, captioned: false, zone: null, hits: [] };
  if (!caps.length) return res;
  const csCache = new Map();
  const cs = (el) => { let s = csCache.get(el); if (!s) { s = getComputedStyle(el); csCache.set(el, s); } return s; };
  const opCache = new Map();
  const opacity = (el) => {
    if (!el || el.nodeType !== 1) return 1;
    if (opCache.has(el)) return opCache.get(el);
    const s = cs(el);
    let v = s.display === 'none' ? 0 : parseFloat(s.opacity);
    if (!Number.isFinite(v)) v = 1;
    if (v > 0) v *= opacity(el.parentElement);
    opCache.set(el, v);
    return v;
  };
  // the zone: measured once per caption block (cards are laid out at rest, one at a time, then restored)
  const cache = window.__stCapZone || (window.__stCapZone = new WeakMap());
  let zone = null;
  const union = (a, b) => (!a ? { ...b } : { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), r: Math.max(a.r, b.r), b: Math.max(a.b, b.b) });
  for (const cap of caps) {
    let z = cache.get(cap);
    if (!z) {
      const cards = [...cap.querySelectorAll('.st-cap-card')];
      const saved = cards.map((c) => [c.style.display, c.style.transform]);
      for (const c of cards) c.style.display = 'none';
      for (const c of cards) {
        c.style.display = ''; c.style.transform = 'none';
        const line = c.querySelector('.st-cap-line') || c;
        const r = line.getBoundingClientRect();
        if (r.width > 1 && r.height > 1) z = union(z, { x: r.left, y: r.top, r: r.right, b: r.bottom });
        c.style.display = 'none';
      }
      cards.forEach((c, i) => { c.style.display = saved[i][0]; c.style.transform = saved[i][1]; });
      if (z) cache.set(cap, z);
    }
    if (z) zone = union(zone, z);
    // a captioned moment: a card of this block is on screen
    if (opacity(cap) >= minOp && cs(cap).visibility === 'visible' &&
        [...cap.querySelectorAll('.st-cap-card')].some((c) => c.style.display !== 'none' && opacity(c) >= minOp)) res.captioned = true;
  }
  if (!zone) return res;
  zone = { x: Math.max(0, zone.x), y: Math.max(0, zone.y), r: Math.min(W, zone.r), b: Math.min(H, zone.b) };
  res.zone = { x: zone.x, y: zone.y, w: zone.r - zone.x, h: zone.b - zone.y };
  if (!res.captioned) return res;
  const sel = (el) => {
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
  };
  // the visible part of an element: clipped by overflow/clip ancestors and the frame
  const clipOf = (el, r) => {
    let v = { x: Math.max(0, r.x), y: Math.max(0, r.y), r: Math.min(W, r.r), b: Math.min(H, r.b) };
    for (let e = el.parentElement; e && e !== document.body && e !== document.documentElement; e = e.parentElement) {
      if (!/(hidden|clip)/.test(cs(e).overflowX + ' ' + cs(e).overflowY)) continue;
      const c = e.getBoundingClientRect();
      v = { x: Math.max(v.x, c.left), y: Math.max(v.y, c.top), r: Math.min(v.r, c.right), b: Math.min(v.b, c.bottom) };
    }
    return v;
  };
  const inter = (a) => ({ x: Math.max(a.x, zone.x), y: Math.max(a.y, zone.y), r: Math.min(a.r, zone.r), b: Math.min(a.b, zone.b) });
  const SHAPES = /^(path|rect|circle|ellipse|line|polyline|polygon|text|image|use)$/i;
  const range = document.createRange();
  const textRect = (el) => {
    let box = null;
    for (const n of el.childNodes) {
      if (n.nodeType !== 3 || !n.nodeValue.trim()) continue;
      range.selectNodeContents(n);
      for (const r of range.getClientRects()) if (r.width > 0.5 && r.height > 0.5) box = union(box, { x: r.left, y: r.top, r: r.right, b: r.bottom });
    }
    return box;
  };
  const isSvg = (el) => typeof SVGElement !== 'undefined' && el instanceof SVGElement;
  const found = new Map();   // element (or its <svg>) -> hit
  for (const el of document.body.querySelectorAll('*')) {
    if (/^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|LINK|META|BR|svg)$/i.test(el.tagName)) continue;
    if (el.closest('.st-cap[data-caption], [data-st-caption-ok], [data-st-ignore], [data-st-audit]')) continue;
    if (caps.some((c) => el.contains(c))) continue;
    const br = el.getBoundingClientRect();
    if (!(br.width > 0.5 && br.height > 0.5) || br.right <= zone.x || br.left >= zone.r || br.bottom <= zone.y || br.top >= zone.b) continue;
    const svg = isSvg(el);
    let kind = null, rect = null;
    const box = { x: br.left, y: br.top, r: br.right, b: br.bottom };
    if (svg) {
      const t = /^(text|tspan|textPath)$/i.test(el.tagName) ? textRect(el) : null;
      if (t) { kind = 'text'; rect = t; } else {
        if (!SHAPES.test(el.tagName)) continue;
        const s = cs(el);
        const fills = s.fill && s.fill !== 'none' && parseFloat(s.fillOpacity) !== 0;
        const strokes = s.stroke && s.stroke !== 'none' && parseFloat(s.strokeWidth) > 0 && parseFloat(s.strokeOpacity) !== 0;
        if (!fills && !strokes && !/^(image|use)$/i.test(el.tagName)) continue;
        kind = 'graphic'; rect = box;
      }
    } else if (/^(IMG|VIDEO|CANVAS|PICTURE|IFRAME|OBJECT|EMBED)$/.test(el.tagName)) { kind = 'media'; rect = box; }
    else {
      const s = cs(el);
      const bgA = (() => { const m = /rgba?\(([^)]+)\)/.exec(s.backgroundColor); if (!m) return 0; const p = m[1].split(/[\s,/]+/).filter(Boolean); return p.length > 3 ? parseFloat(p[3]) : 1; })();
      const bdr = ['Top', 'Right', 'Bottom', 'Left'].some((k) => parseFloat(s['border' + k + 'Width']) > 0 && s['border' + k + 'Style'] !== 'none' && !/rgba\([^)]*,\s*0\)|transparent/.test(s['border' + k + 'Color']));
      const paints = bgA >= 0.1 || (s.backgroundImage && s.backgroundImage !== 'none') || bdr;
      const t = textRect(el);
      if (!paints && !t) continue;
      kind = t ? 'text' : 'box'; rect = paints ? box : t;
    }
    const v = clipOf(el, rect);
    if (!(v.r - v.x > 0.5 && v.b - v.y > 0.5)) continue;
    // full-frame backgrounds and full-width bands with no text of their own (a scrim, a ground, a rule)
    if ((v.r - v.x) * (v.b - v.y) >= 0.5 * W * H || (kind !== 'text' && kind !== 'media' && v.r - v.x >= 0.9 * W)) continue;
    if (opacity(el) < minOp || cs(el).visibility !== 'visible') continue;
    const ov = inter(v);
    if (!(ov.r - ov.x >= 4 && ov.b - ov.y >= 4)) continue;
    let owner = el;
    if (svg) { let s = el.ownerSVGElement; while (s && s.ownerSVGElement) s = s.ownerSVGElement; owner = s || el; }
    const cur = found.get(owner);
    if (cur) {
      cur.overlap = union(cur.overlap, ov);
      cur.rect = union(cur.rect, v);
      if (kind === 'text' && cur.kind !== 'text') cur.kind = 'text';
      continue;
    }
    found.set(owner, { el: owner, kind: owner !== el ? (kind === 'text' ? 'text' : 'graphic') : kind, rect: v, overlap: ov });
  }
  // one hit per thing on screen: an element whose ancestor is a hit too is part of it (a card and its label)
  const els = [...found.keys()];
  for (const [el, h] of found) {
    if (els.some((o) => o !== el && o.contains(el))) continue;
    const txt = ((el.getAttribute && (el.getAttribute('aria-label') || '')) || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60);
    const label = el.tagName.toLowerCase() === 'img' ? (el.getAttribute('alt') || (el.getAttribute('src') || '').split('/').pop()) : txt;
    const rr = (q) => ({ x: Math.round(q.x), y: Math.round(q.y), w: Math.round(q.r - q.x), h: Math.round(q.b - q.y) });
    res.hits.push({ key: sel(el) + '|' + label, sel: sel(el), text: label, kind: h.kind, rect: rr(h.rect), overlap: rr(h.overlap) });
    if (res.hits.length >= 40) break;
  }
  return res;
}

/**
 * Init script (added before the page's own scripts): records WebGPU use in window.__stGpu with the page
 * line that asked (navigator.gpu read, requestAdapter and its result, getContext('webgpu')), and marks
 * every canvas with the context types asked of it (data-st-ctx). With off = true, WebGPU is gone, as on
 * a machine without a GPU: navigator.gpu is undefined and getContext('webgpu') returns null.
 */
export function gpuProbeScript(off) {
  return `(() => {
  const rec = window.__stGpu = { reads: [], adapters: [], contexts: [], off: ${off ? 'true' : 'false'} };
  const where = () => {
    const lines = String(new Error().stack || '').split('\\n').slice(2);
    for (const l of lines) { const m = /(https?:\\/\\/[^\\s)]+):(\\d+):(\\d+)/.exec(l); if (m) return m[1] + ':' + m[2]; }
    return '';
  };
  const push = (arr, v) => { if (arr.length < 20) arr.push(v); };
  try {
    const desc = Object.getOwnPropertyDescriptor(Navigator.prototype, 'gpu');
    if (desc || ${off ? 'true' : 'false'}) {
      Object.defineProperty(Navigator.prototype, 'gpu', { configurable: true, enumerable: true, get() {
        push(rec.reads, where());
        if (rec.off || !desc) return undefined;
        const gpu = desc.get.call(this);
        if (gpu && !gpu.__stWrapped) {
          const req = gpu.requestAdapter.bind(gpu);
          gpu.requestAdapter = (...a) => { const w = where(); return req(...a).then((ad) => { push(rec.adapters, { where: w, got: !!ad }); return ad; }); };
          gpu.__stWrapped = true;
        }
        return gpu;
      } });
    }
  } catch (e) { /* leave navigator.gpu alone */ }
  const wrap = (proto) => {
    if (!proto || !proto.getContext) return;
    const orig = proto.getContext;
    proto.getContext = function (type, ...rest) {
      const t = String(type || '').toLowerCase();
      const w = where();
      try {
        if (this.setAttribute) {
          const have = (this.getAttribute('data-st-ctx') || '').split(' ').filter(Boolean);
          if (!have.includes(t)) { have.push(t); this.setAttribute('data-st-ctx', have.join(' ')); }
          // asked by the page (or a library it loads), not by showtime's runtime (/_st/)
          if (w && !/\\/_st\\//.test(w) && !this.hasAttribute('data-st-ctx-page')) this.setAttribute('data-st-ctx-page', '');
        }
      } catch (e) { /* offscreen */ }
      if (t === 'webgpu') { push(rec.contexts, w); if (rec.off) return null; }
      return orig.call(this, type, ...rest);
    };
  };
  wrap(window.HTMLCanvasElement && HTMLCanvasElement.prototype);
  wrap(window.OffscreenCanvas && OffscreenCanvas.prototype);
})();`;
}

/** Declared @font-face families and their load status. */
export function fontInfo() {
  const faces = [];
  document.fonts.forEach((f) => faces.push({ family: f.family.replace(/^["']|["']$/g, ''), weight: f.weight, style: f.style, status: f.status }));
  return faces;
}

/**
 * What is on the frame at the current seek position, for `showtime review notes`: a note's spot or box is
 * resolved against this (scripts/lib/review/where.mjs) to the scene and the elements under it.
 * o: { width, height, t, duration, max?: 800 }
 * -> { width, height, t, film, scenes: [{id, name, start, end, on}] (top-level clips, `on` at t),
 *      elements: [{i, parent (i of the nearest listed ancestor, or -1), kind, sel, tag, comp, root, text, scene,
 *      x, y, w, h}] }
 *   kind: 'text' (a block with words; its box is where the words are, not the whole block), 'media' (img,
 *   video, canvas, svg, iframe), 'component' (a data-st root), 'shape' (a box with a fill or a border),
 *   'backdrop' (a fill over most of the frame). Only what shows: invisible, off-frame and fully covered
 *   elements are left out. A Film page's F.text calls are listed as text on its canvas. Boxes in frame px.
 */
export function elementSnapshot(o) {
  const W = o.width, H = o.height, t = Number(o.t) || 0, D = Number(o.duration) || Infinity, MAX = o.max || 800;
  const csCache = new Map();
  const cs = (el) => { let s = csCache.get(el); if (!s) { s = getComputedStyle(el); csCache.set(el, s); } return s; };
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
  const cnv = document.createElement('canvas'); cnv.width = cnv.height = 1;
  const g = cnv.getContext('2d', { willReadFrequently: true });
  function alphaOf(str) {
    if (!str || str === 'transparent') return 0;
    g.clearRect(0, 0, 1, 1); g.fillStyle = '#000'; g.fillStyle = str; g.fillRect(0, 0, 1, 1);
    return g.getImageData(0, 0, 1, 1).data[3] / 255;
  }
  // the page's own classes: st-* ones are added by the runtime and its components, not in the source
  const clsOf = (el) => [...(el.classList || [])].filter((c) => !/^st-/.test(c)).slice(0, 2);
  function sel(el) {
    if (el.id) return '#' + el.id;
    const parts = [];
    let e = el;
    for (let i = 0; e && e.nodeType === 1 && e !== document.body && i < 4; i++, e = e.parentElement) {
      if (e.id) { parts.unshift('#' + e.id); break; }
      let p = e.tagName.toLowerCase();
      const cl = clsOf(e);
      if (cl.length) p += '.' + cl.join('.');
      else if (e.getAttribute('data-st')) p += `[data-st="${e.getAttribute('data-st')}"]`;
      parts.unshift(p);
    }
    return parts.join(' > ');
  }
  const clean = (s, n = 100) => { const x = String(s || '').replace(/\s+/g, ' ').trim(); return x.length > n ? x.slice(0, n - 1) + '…' : x; };

  // scenes: top-level clips, matched to their elements as check does
  const scenes = [], sceneOf = new Map();
  try {
    const all = [...document.querySelectorAll('[data-start]')];
    const cl = window.ST && typeof window.ST.clips === 'function' ? window.ST.clips() : [];
    if (cl.length === all.length) {
      all.forEach((el, i) => {
        if (el.parentElement && el.parentElement.closest('[data-start]')) return;
        const c = cl[i];
        if (!c || !isFinite(c.start)) return;
        const end = c.end == null ? D : Math.min(D, c.end);
        sceneOf.set(el, scenes.length);
        scenes.push({ id: el.id || null, name: el.id ? '#' + el.id : (c.name || el.tagName.toLowerCase()), start: c.start,
          end: isFinite(end) ? end : null, on: t >= c.start - 1e-6 && (!isFinite(end) || t < end - 1e-6) });
      });
    }
  } catch { /* no clip table */ }
  const sceneFor = (el) => {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) if (sceneOf.has(e)) return scenes[sceneOf.get(e)].name;
    return null;
  };

  const cands = new Map();   // element -> {kinds, trect: where its words are}
  const add = (el, kind, rect) => {
    let c = cands.get(el);
    if (!c) { c = { el, kinds: new Set(), trect: null }; cands.set(el, c); }
    c.kinds.add(kind);
    if (rect) c.trect = !c.trect ? { ...rect } : { x: Math.min(c.trect.x, rect.x), y: Math.min(c.trect.y, rect.y), r: Math.max(c.trect.r, rect.r), b: Math.max(c.trect.b, rect.b) };
  };
  // a shutter blur hides the element on its fast frames (data-st-blurring) and draws smeared copies in an <st-blur>
  // host right after it: the element is what shows, never its copies
  const visible = (el) => opacity(el) > 0.05 && (cs(el).visibility === 'visible' || !!el.closest('[data-st-blurring]'));
  const blurCopy = (el) => !!el.closest('st-blur');
  const onFrame = (r) => r.right > 0 && r.bottom > 0 && r.left < W && r.top < H && r.width >= 1 && r.height >= 1;
  const INLINE = /^(inline|inline-block|inline-flex|inline-grid|contents|ruby|ruby-text)$/;
  const SKIP = /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|TITLE|TEXTAREA|META|LINK|HEAD)$/;

  // words: each text node counts for its block (an <em> in a heading is the heading's), an SVG label for its <text>
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (!n.nodeValue || !n.nodeValue.trim()) continue;
    const p = n.parentElement;
    if (!p || SKIP.test(p.tagName) || blurCopy(p) || !visible(p)) continue;
    let holder;
    if (p.closest('svg') && !p.closest('foreignObject')) holder = p.closest('text') || p;
    else {
      holder = p;
      while (holder.parentElement && holder !== document.body && INLINE.test(cs(holder).display) && !holder.hasAttribute('data-st')) holder = holder.parentElement;
    }
    range.selectNodeContents(n);
    for (const r of range.getClientRects()) {
      if (!(r.width > 0.5 && r.height > 0.5) || !onFrame(r)) continue;
      add(holder, 'text', { x: r.left, y: r.top, r: r.right, b: r.bottom });
    }
  }
  // pictures, components, boxes with a fill or a border
  const order = new Map();
  let k = 0;
  const ew = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_ELEMENT);
  for (let el = ew.currentNode; el; el = ew.nextNode()) {
    order.set(el, k++);
    if (el === document.body || el === document.documentElement || SKIP.test(el.tagName) || sceneOf.has(el)) continue;
    const tag = el.tagName.toLowerCase();
    if (typeof SVGElement !== 'undefined' && el instanceof SVGElement && tag !== 'svg') continue;
    if (blurCopy(el) || !visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (!onFrame(r)) continue;
    if (/^(img|video|canvas|svg|iframe|object|embed)$/.test(tag)) add(el, 'media');
    if (el.hasAttribute('data-st')) add(el, 'component');
    const s = cs(el);
    const filled = alphaOf(s.backgroundColor) >= 0.15 || (s.backgroundImage && s.backgroundImage !== 'none');
    const bordered = ['Top', 'Right', 'Bottom', 'Left'].some((side) => parseFloat(s['border' + side + 'Width']) > 0 &&
      s['border' + side + 'Style'] !== 'none' && alphaOf(s['border' + side + 'Color']) >= 0.15);
    if (filled || bordered) add(el, r.width * r.height >= 0.6 * W * H ? 'backdrop' : 'shape');
  }

  // covered: every sample point lands on an opaque element painted over it (the outgoing scene under the
  // incoming one, a card over a label). Elements that do not take the pointer are hit-tested too.
  const style = document.createElement('style');
  style.textContent = '*{pointer-events:auto!important}';
  (document.head || document.documentElement).appendChild(style);
  const TRANSLUCENT = /transparent|rgba\([^)]*,\s*(0?\.\d+|0)\s*\)|\/\s*(0?\.\d+|0)\s*\)/;
  const paintsOpaque = (e) => {
    if (e.hasAttribute('data-st-gl') || /^(IMG|VIDEO)$/.test(e.tagName)) return true;
    const s = cs(e);
    if (alphaOf(s.backgroundColor) >= 0.9) return true;
    const bi = s.backgroundImage || '';
    return /gradient\(/.test(bi) && !/url\(/.test(bi) && !TRANSLUCENT.test(bi);
  };
  function covered(el, b) {
    let tested = 0;
    for (const [fx, fy] of [[0.5, 0.5], [0.2, 0.5], [0.8, 0.5], [0.5, 0.25], [0.5, 0.75]]) {
      const x = b.x + b.w * fx, y = b.y + b.h * fy;
      if (x < 0 || y < 0 || x >= W || y >= H) continue;
      tested++;
      const hit = document.elementFromPoint(x, y);
      if (!hit || hit === el || el.contains(hit) || hit.contains(el)) return false;
      const host = hit.closest('st-blur');
      if (host && host.previousElementSibling === el) return false;   // its own shutter-blur copies
      let opaque = false;
      for (let e = hit; e && !e.contains(el); e = e.parentElement) {
        if (opacity(e) < 0.9) break;
        if (paintsOpaque(e)) { opaque = true; break; }
      }
      if (!opaque) return false;
    }
    return tested > 0;
  }
  const RANK = ['component', 'media', 'text', 'shape', 'backdrop'];
  const list = [];
  try {
    for (const c of [...cands.values()].sort((a, b) => (order.get(a.el) || 0) - (order.get(b.el) || 0))) {
      const el = c.el;
      let kind = RANK.find((x) => c.kinds.has(x));
      let b;
      if (kind === 'text' && c.trect) b = { x: c.trect.x, y: c.trect.y, w: c.trect.r - c.trect.x, h: c.trect.b - c.trect.y };
      else { const r = el.getBoundingClientRect(); b = { x: r.left, y: r.top, w: r.width, h: r.height }; }
      // a picture, overlay or component over most of the frame (a background photo, grain) is the ground
      if (kind !== 'text' && b.w * b.h >= 0.6 * W * H) kind = 'backdrop';
      if (kind !== 'backdrop' && covered(el, b)) continue;
      const tag = el.tagName.toLowerCase();
      let text = clean(typeof SVGElement !== 'undefined' && el instanceof SVGElement ? el.textContent : el.innerText || (el.closest('[data-st-blurring]') ? el.textContent : ''));
      if (!text && kind === 'media') {
        text = clean(el.getAttribute('alt') || el.getAttribute('aria-label') || el.getAttribute('title') ||
          String(el.currentSrc || el.getAttribute('src') || '').split(/[?#]/)[0].split('/').pop(), 60);
      }
      const host = el.closest('[data-st]');
      list.push({ el, i: list.length, kind, sel: sel(el), tag, comp: host ? host.getAttribute('data-st') : null, root: el.hasAttribute('data-st'),
        text, scene: sceneFor(el), x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.w), h: Math.round(b.h) });
      if (list.length >= MAX) break;
    }
  } finally { style.remove(); }
  const idx = new Map(list.map((e) => [e.el, e.i]));
  const out = list.map((e) => {
    let parent = -1;
    for (let p = e.el.parentElement; p; p = p.parentElement) if (idx.has(p)) { parent = idx.get(p); break; }
    const { el, ...rest } = e;   // eslint-disable-line no-unused-vars
    return { ...rest, parent };
  });
  // a Film page draws on one canvas: its F.text calls of this frame are the words on it
  let film = false;
  try {
    if (window.Film && typeof window.Film.frameInfo === 'function') {
      film = true;
      const fi = window.Film.frameInfo();
      const ci = out.findIndex((e) => e.tag === 'canvas');
      for (const x of (fi.texts || [])) {
        if (!(x.alpha > 0.05) || out.length >= MAX) continue;
        out.push({ i: out.length, parent: ci, kind: 'text', sel: 'canvas (Film text)', tag: 'canvas', comp: null, root: false,
          text: clean(x.text), scene: ci >= 0 ? out[ci].scene : null, x: x.x, y: x.y, w: x.w, h: x.h });
      }
    }
  } catch { /* not a film */ }
  return { width: W, height: H, t, film, scenes, elements: out };
}

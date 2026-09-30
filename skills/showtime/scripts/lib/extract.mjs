// In-page extraction for `showtime site capture`: copy, CTAs, testimonials, stats, design tokens,
// colours with roles, fonts, logo candidates, images and videos. Everything runs inside ONE
// page.evaluate (the function below is serialized by Playwright; keep it self-contained).

export function extractPage(opts) {
  const MAX_EL = opts.maxElements || 2500;
  const abs = (u) => { try { return u ? new URL(u, location.href).href : null; } catch { return null; } };
  const clean = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const vis = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const cs = getComputedStyle(el);
    return cs.visibility !== 'hidden' && cs.display !== 'none' && Number(cs.opacity) > 0.05;
  };
  const box = (el) => { const r = el.getBoundingClientRect(); return [Math.round(r.left + scrollX), Math.round(r.top + scrollY), Math.round(r.width), Math.round(r.height)]; };

  // ---- colour normalisation (handles oklch/lab/color-mix via a 1x1 canvas)
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const cache = new Map();
  function toHex(c) {
    if (!c || c === 'transparent' || c === 'none') return null;
    if (cache.has(c)) return cache.get(c);
    let out = null;
    const m = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+%?))?\s*\)$/.exec(c);
    let a = 1;
    if (m) {
      a = m[4] === undefined ? 1 : (m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]));
      if (a >= 0.5) out = '#' + [m[1], m[2], m[3]].map((x) => Math.round(Number(x)).toString(16).padStart(2, '0')).join('');
    } else {
      try {
        cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c; cx.fillRect(0, 0, 1, 1);
        const d = cx.getImageData(0, 0, 1, 1).data;
        if (d[3] >= 128) out = '#' + [d[0], d[1], d[2]].map((x) => x.toString(16).padStart(2, '0')).join('');
      } catch { out = null; }
    }
    cache.set(c, out);
    return out;
  }
  const lum = (hex) => { const n = parseInt(hex.slice(1), 16); const r = (n >> 16) / 255, g = ((n >> 8) & 255) / 255, b = (n & 255) / 255; return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
  const sat = (hex) => { const n = parseInt(hex.slice(1), 16); const r = n >> 16, g = (n >> 8) & 255, b = n & 255; const mx = Math.max(r, g, b), mn = Math.min(r, g, b); return mx ? (mx - mn) / mx : 0; };
  const chroma = (hex) => { const n = parseInt(hex.slice(1), 16); const r = n >> 16, g = (n >> 8) & 255, b = n & 255; return Math.max(r, g, b) - Math.min(r, g, b); };
  const role = (hex) => { const L = lum(hex), S = sat(hex); if (L < 0.04) return 'bg-dark'; if (L > 0.9 && S < 0.2) return 'bg-light'; if (S > 0.4 && chroma(hex) > 60 && L > 0.08 && L < 0.8) return 'accent'; if (L < 0.2) return 'surface-dark'; if (L > 0.7) return 'surface-light'; return 'neutral'; };

  // ---- meta
  const metaTags = {};
  for (const m of document.querySelectorAll('meta[property],meta[name]')) {
    const k = (m.getAttribute('property') || m.getAttribute('name') || '').toLowerCase();
    if (/^(og:|twitter:|description$|theme-color$|application-name$|generator$|keywords$|author$|color-scheme$)/.test(k) && m.content) metaTags[k] = m.content.slice(0, 500);
  }
  const icons = [...document.querySelectorAll('link[rel~="icon" i],link[rel="apple-touch-icon" i],link[rel="apple-touch-icon-precomposed" i],link[rel="mask-icon" i]')].map((l) => ({
    href: abs(l.getAttribute('href')), rel: (l.getAttribute('rel') || '').toLowerCase(), sizes: l.getAttribute('sizes') || null, type: l.getAttribute('type') || null,
  })).filter((x) => x.href);
  const meta = {
    title: document.title || '', description: metaTags.description || metaTags['og:description'] || '',
    lang: document.documentElement.lang || null, canonical: abs(document.querySelector('link[rel=canonical]')?.getAttribute('href')),
    themeColor: metaTags['theme-color'] || null, colorScheme: metaTags['color-scheme'] || null,
    ogImage: abs(metaTags['og:image'] || metaTags['twitter:image']), tags: metaTags, icons,
    manifest: abs(document.querySelector('link[rel=manifest]')?.getAttribute('href')),
  };

  // ---- headings + copy
  const headings = [];
  for (const h of document.querySelectorAll('h1,h2,h3,h4')) {
    if (headings.length >= 120 || !vis(h)) continue;
    const t = clean(h.innerText);
    if (t && t.length < 300) headings.push({ level: Number(h.tagName[1]), text: t, y: box(h)[1] });
  }
  const headingFor = (el) => {
    const sec = el.closest('section,article,header,footer,[class*=hero i],[class*=section i],main > div') || document.body;
    const h = sec.querySelector('h1,h2,h3');
    return h ? clean(h.innerText).slice(0, 120) : null;
  };
  const seen = new Set();
  const copy = [];
  for (const el of document.querySelectorAll('p,li,dd,figcaption,[class*=subtitle i],[class*=lead i],[class*=description i]')) {
    if (copy.length >= 80) break;
    if (el.closest('nav,footer,[role=navigation],script,style,noscript,form,blockquote,figure:has(blockquote),[class*=testimonial i]') || !vis(el)) continue;
    if (el.tagName === 'LI' && el.querySelector('p,li')) continue;
    const t = clean(el.innerText);
    if (t.length < 30 || t.length > 700 || seen.has(t)) continue;
    seen.add(t);
    copy.push({ text: t, tag: el.tagName.toLowerCase(), section: headingFor(el), y: box(el)[1] });
  }

  // ---- CTAs
  const ctas = [];
  const candidates = document.querySelectorAll('a,button,[role=button],input[type=submit],input[type=button]');
  let ci = 0;
  for (const el of candidates) {
    if (ci++ > 1500) break;
    if (!vis(el)) continue;
    const t = clean(el.innerText || el.value || el.getAttribute('aria-label'));
    if (!t || t.length > 40) continue;
    const cs = getComputedStyle(el);
    const bg = toHex(cs.backgroundColor);
    const r = el.getBoundingClientRect();
    const cls = (typeof el.className === 'string' ? el.className : '') + ' ' + (el.id || '');
    const buttonish = el.tagName === 'BUTTON' || /btn|button|cta/i.test(cls) || (bg && parseFloat(cs.paddingLeft) >= 8 && r.height >= 28 && r.height <= 90);
    if (!buttonish) continue;
    const inNav = !!el.closest('nav,header,[role=navigation]');
    const area = r.width * r.height;
    const score = area * (bg ? 1.5 + sat(bg) : 0.6) * (inNav ? 0.6 : 1) * (r.top + scrollY < innerHeight ? 1.6 : 1);
    ctas.push({ text: t, href: el.tagName === 'A' ? abs(el.getAttribute('href')) : null, bg, fg: toHex(cs.color),
      radius: cs.borderRadius, fontWeight: cs.fontWeight, fontSize: cs.fontSize, inNav, box: box(el), score: Math.round(score) });
  }
  ctas.sort((a, b) => b.score - a.score);
  const ctaSeen = new Set();
  const ctaList = ctas.filter((c) => { const k = c.text.toLowerCase(); if (ctaSeen.has(k)) return false; ctaSeen.add(k); return true; }).slice(0, 24);
  ctaList.forEach((c, i) => { c.primary = i < 3 && !!c.bg; });

  // ---- testimonials
  const testimonials = [];
  const tSeen = new Set();
  // quotes inside a live app (a markdown preview next to its editor) are content, not testimonials
  const inApp = (el) => {
    let a = el.parentElement;
    for (let k = 0; a && k < 5 && a !== document.body; k++, a = a.parentElement) {
      if (a.matches('main,[role=main],[role=application]') || a.querySelector('textarea,[contenteditable=""],[contenteditable=true],[role=textbox]')) {
        return !!a.querySelector('textarea,[contenteditable=""],[contenteditable=true],[role=textbox]');
      }
    }
    return false;
  };
  for (const el of document.querySelectorAll('blockquote,[class*=testimonial i],[class*=review i],[class*=quote i],figure:has(blockquote)')) {
    if (testimonials.length >= 16 || !vis(el) || inApp(el)) continue;
    const q = el.querySelector('blockquote,p,[class*=text i],[class*=content i]') || el;
    const text = clean(q.innerText);
    if (text.length < 30 || text.length > 700 || tSeen.has(text)) continue;
    let author = el.querySelector('cite,figcaption,[class*=author i],[class*=name i],[class*=person i]');
    const who = author ? clean(author.innerText).slice(0, 120) : null;
    tSeen.add(text);
    const img = el.querySelector('img');
    testimonials.push({ text: who && text.endsWith(who) ? text.slice(0, -who.length).trim() : text, author: who, avatar: img ? abs(img.currentSrc || img.src) : null, box: box(el) });
  }

  // ---- stats ("10x faster", "99.9%", "2M+ users")
  const stats = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
  let el, n = 0;
  while ((el = walker.nextNode()) && n++ < MAX_EL * 2 && stats.length < 24) {
    if (el.children.length > 1) continue;
    const t = clean(el.innerText);
    if (!/^[~<>≈+$€£]?\s?\d[\d.,]*\s?(%|x|k|m|b|\+|ms|s|h|m\+|k\+|b\+|million|billion|×)?\+?$/i.test(t) || t.length > 14) continue;
    if (!vis(el)) continue;
    const parent = el.parentElement;
    const label = parent ? clean(parent.innerText.replace(t, '')).slice(0, 80) : '';
    stats.push({ value: t, label, box: box(el) });
  }

  // ---- nav
  const nav = [];
  for (const a of document.querySelectorAll('header a,nav a,[role=navigation] a')) {
    if (nav.length >= 40 || !vis(a)) continue;
    const t = clean(a.innerText);
    if (t && t.length < 40) nav.push({ text: t, href: abs(a.getAttribute('href')) });
  }

  // ---- design tokens: CSS custom properties
  const vars = {};
  const addVar = (k, v) => { if (Object.keys(vars).length < 500 && !(k in vars)) vars[k] = String(v).trim().slice(0, 200); };
  let crossOrigin = 0;
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch { crossOrigin++; continue; }
    const walk = (list) => {
      for (const r of list) {
        if (r.cssRules && !r.selectorText) { walk(r.cssRules); continue; }
        if (!r.selectorText || !/(^|,)\s*(:root|html)\b/.test(r.selectorText)) continue;
        for (let i = 0; i < r.style.length; i++) {
          const p = r.style[i];
          if (p.startsWith('--')) addVar(p, r.style.getPropertyValue(p));
        }
      }
    };
    walk(rules);
  }
  const rootCs = getComputedStyle(document.documentElement);
  for (let i = 0; i < rootCs.length; i++) {
    const p = rootCs[i];
    if (p.startsWith('--')) addVar(p, rootCs.getPropertyValue(p));
  }
  const colorVars = {};
  for (const [k, v] of Object.entries(vars)) {
    if (/^(#|rgb|hsl|oklch|oklab|lab|lch|color\()/i.test(v)) { const hx = toHex(v); if (hx) colorVars[k] = hx; }
  }

  // ---- colours (weighted by area / text) and radii / shadows
  const weights = new Map();
  const add = (hex, w, kind) => { if (!hex) return; const e = weights.get(hex) || { hex, weight: 0, bg: 0, text: 0, border: 0 }; e.weight += w; e[kind] += w; weights.set(hex, e); };
  const radii = new Map(), shadows = new Map();
  const docArea = Math.max(1, document.documentElement.scrollWidth * document.documentElement.scrollHeight);
  const all = document.body ? document.body.getElementsByTagName('*') : [];
  const htmlBg = toHex(getComputedStyle(document.documentElement).backgroundColor);
  const bodyBg = toHex(getComputedStyle(document.body).backgroundColor);
  add(bodyBg || htmlBg || '#ffffff', 0.5, 'bg');
  for (let i = 0; i < all.length && i < MAX_EL; i++) {
    const e = all[i];
    const r = e.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    const cs = getComputedStyle(e);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const area = (r.width * r.height) / docArea;
    add(toHex(cs.backgroundColor), Math.min(area, 0.6), 'bg');
    const direct = [...e.childNodes].filter((c) => c.nodeType === 3).map((c) => c.textContent.trim()).join('');
    if (direct) add(toHex(cs.color), Math.min(direct.length, 200) * parseFloat(cs.fontSize) / 40000, 'text');
    if (parseFloat(cs.borderTopWidth) > 0 && cs.borderTopStyle !== 'none') add(toHex(cs.borderTopColor), 0.0005, 'border');
    if (cs.borderRadius && cs.borderRadius !== '0px' && r.height > 20) radii.set(cs.borderRadius, (radii.get(cs.borderRadius) || 0) + 1);
    if (cs.boxShadow && cs.boxShadow !== 'none') shadows.set(cs.boxShadow, (shadows.get(cs.boxShadow) || 0) + 1);
    const bgi = cs.backgroundImage;
    if (bgi && bgi.includes('gradient')) for (const m of bgi.matchAll(/(rgba?\([^)]+\)|#[0-9a-f]{3,8}|oklch\([^)]+\)|hsla?\([^)]+\))/gi)) add(toHex(m[1]), Math.min(area, 0.2) / 3, 'bg');
  }
  const palette = [...weights.values()].sort((a, b) => b.weight - a.weight).slice(0, 18)
    .map((c) => ({ hex: c.hex, role: role(c.hex), weight: Number(c.weight.toFixed(4)), usage: c.bg >= c.text ? 'background' : 'text' }));
  // a white or black button is not a brand colour: fall back to the palette's accent instead
  const neutral = (hex) => sat(hex) < 0.08 && (lum(hex) > 0.85 || lum(hex) < 0.06);
  const primaryCta = ctaList.find((c) => c.bg && sat(c.bg) > 0.15) || ctaList.find((c) => c.bg && !neutral(c.bg));
  const textColor = [...weights.values()].sort((a, b) => b.text - a.text)[0];
  const roles = {
    background: bodyBg || htmlBg || palette.find((p) => p.usage === 'background')?.hex || null,
    text: textColor ? textColor.hex : null,
    primary: primaryCta ? primaryCta.bg : (palette.find((p) => p.role === 'accent')?.hex || null),
    onPrimary: primaryCta ? primaryCta.fg : null,
    accent: palette.find((p) => p.role === 'accent' && (!primaryCta || p.hex !== primaryCta.bg) && p.hex !== (textColor && textColor.hex))?.hex || null,
    surface: palette.find((p) => p.usage === 'background' && p.hex !== (bodyBg || htmlBg))?.hex || null,
    themeColor: metaTags['theme-color'] ? toHex(metaTags['theme-color']) : null,
  };

  // ---- fonts
  const fontsLoaded = [];
  try {
    for (const f of document.fonts) {
      const fam = f.family.replace(/^["']|["']$/g, '');
      if (/placeholder|fallback/i.test(fam)) continue;
      if (f.status !== 'loaded') continue;
      const k = fam + '|' + f.weight + '|' + f.style;
      if (!fontsLoaded.some((x) => x.key === k)) fontsLoaded.push({ key: k, family: fam, weight: f.weight, style: f.style, variable: /\d+\s+\d+/.test(f.weight) });
    }
  } catch { /* ignore */ }
  const roleFont = (sel) => { const e = document.querySelector(sel); if (!e) return null; const cs = getComputedStyle(e); return { family: cs.fontFamily, weight: cs.fontWeight, size: cs.fontSize, letterSpacing: cs.letterSpacing, lineHeight: cs.lineHeight }; };
  const fontRoles = { h1: roleFont('h1'), h2: roleFont('h2'), body: roleFont('main p') || roleFont('p') || roleFont('body'), button: roleFont('button') || roleFont('a[class*=btn i]'), code: roleFont('code,pre'), nav: roleFont('nav a') };
  const fontFaces = [];
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch { continue; }
    for (const r of rules) {
      if (r.type === 5 && fontFaces.length < 40) {
        const fam = (r.style.getPropertyValue('font-family') || '').replace(/["']/g, '').trim();
        const src = r.style.getPropertyValue('src') || '';
        const u = /url\(["']?([^"')]+)/.exec(src);
        fontFaces.push({ family: fam, weight: r.style.getPropertyValue('font-weight') || null, url: u ? abs(u[1]) : null });
      }
    }
  }

  // ---- images, backgrounds, videos, inline SVG logos
  const fold = innerHeight;
  const images = [];
  const imgSeen = new Set();
  for (const img of document.images) {
    const src = abs(img.currentSrc || img.src);
    if (!src || src.startsWith('data:') || imgSeen.has(src)) continue;
    const r = img.getBoundingClientRect();
    imgSeen.add(src);
    const inHeader = !!img.closest('header,nav,[role=banner]');
    const home = img.closest('a[href]');
    const href = home ? home.getAttribute('href') : '';
    const inHomeLink = !!home && (/^(\/|#|\.\/|\/index\.html?)$/.test(href) || (() => { try { const u = new URL(href, location.href); return u.origin === location.origin && (u.pathname === '/' || u.pathname === ''); } catch { return false; } })());
    const alt = clean(img.alt || img.getAttribute('aria-label') || img.title);
    const brand = (document.title.split(/[-|—:·•]/).map((s) => s.trim().toLowerCase()).filter((s) => s.length >= 2 && s.length < 30));
    images.push({ url: src, alt, natural: [img.naturalWidth, img.naturalHeight], rendered: [Math.round(r.width), Math.round(r.height)],
      aboveFold: r.top + scrollY < fold, inHeader, inHomeLink, logo: (inHeader && inHomeLink) || /logo/i.test(alt + ' ' + src.split('/').pop()) || brand.some((b) => alt.toLowerCase().includes(b)) && inHeader,
      section: headingFor(img), y: Math.round(r.top + scrollY) });
    if (images.length >= 300) break;
  }
  const backgrounds = [];
  for (let i = 0; i < all.length && i < MAX_EL && backgrounds.length < 40; i++) {
    const e = all[i];
    const cs = getComputedStyle(e);
    if (!cs.backgroundImage || !cs.backgroundImage.includes('url(')) continue;
    const r = e.getBoundingClientRect();
    if (r.width * r.height < 40000) continue;
    for (const m of cs.backgroundImage.matchAll(/url\(["']?([^"')]+)["']?\)/g)) {
      const u = abs(m[1]);
      if (u && !u.startsWith('data:') && !imgSeen.has(u)) { imgSeen.add(u); backgrounds.push({ url: u, rendered: [Math.round(r.width), Math.round(r.height)], section: headingFor(e), y: Math.round(r.top + scrollY) }); }
    }
  }
  const videos = [];
  for (const v of document.querySelectorAll('video')) {
    const srcs = [v.currentSrc, v.src, ...[...v.querySelectorAll('source')].map((s) => s.src)].map(abs).filter((u) => u && !u.startsWith('blob:'));
    const r = v.getBoundingClientRect();
    videos.push({ urls: [...new Set(srcs)], poster: abs(v.poster), rendered: [Math.round(r.width), Math.round(r.height)], autoplay: v.autoplay, loop: v.loop, muted: v.muted, section: headingFor(v) });
  }
  const svgs = [];
  for (const s of document.querySelectorAll('header svg,nav svg,a[href="/"] svg,[class*=logo i] svg,svg[class*=logo i]')) {
    if (svgs.length >= 12) break;
    const r = s.getBoundingClientRect();
    if (r.width < 16 || r.height < 10) continue;
    const html = s.outerHTML;
    if (html.length > 80000) continue;
    const home = s.closest('a[href]');
    const inHomeLink = !!home && /^(\/|#|\.\/)$/.test(home.getAttribute('href') || '');
    const clone = s.cloneNode(true);
    if (!clone.getAttribute('xmlns')) clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    const color = getComputedStyle(s).color;
    let out = clone.outerHTML.replace(/currentColor/g, toHex(color) || '#000000');
    svgs.push({ svg: out, rendered: [Math.round(r.width), Math.round(r.height)], inHomeLink, logo: inHomeLink || /logo/i.test((s.getAttribute('class') || '') + (s.closest('[class*=logo i]') ? ' logo' : '')) });
  }

  // ---- wordmark: the name as the site sets it (a short h1 or a text logo), split into runs by colour,
  // so a launch film can set it the same way ("quill" in ink, "sort" in the accent)
  let wordmark = null;
  const wmCands = [...document.querySelectorAll('header [class*=logo i], a[href="/"], h1')].filter((el) => vis(el) && !el.querySelector('img,svg'));
  for (const el of wmCands) {
    const t = clean(el.innerText);
    if (!t || t.length > 28 || t.split(' ').length > 3) continue;
    const runs = [];
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      const s = n.nodeValue.replace(/\s+/g, ' ');
      if (!s.trim()) continue;
      const cs = getComputedStyle(n.parentElement);
      const color = toHex(cs.color);
      const last = runs[runs.length - 1];
      if (last && last.color === color && last.weight === cs.fontWeight) last.text += s;
      else runs.push({ text: s, color, weight: cs.fontWeight });
    }
    if (!runs.length) continue;
    const cs = getComputedStyle(el);
    wordmark = { text: t, runs: runs.map((r) => ({ ...r, text: r.text.trim() })).filter((r) => r.text), tag: el.tagName.toLowerCase(),
      font: { family: cs.fontFamily, weight: cs.fontWeight, size: cs.fontSize, letterSpacing: cs.letterSpacing } };
    break;
  }
  // ---- code blocks: how the product shows a command (its terminal look)
  let code = null;
  for (const el of document.querySelectorAll('pre, [class*=terminal i], [class*=codeblock i], [class*=code-block i]')) {
    if (!vis(el)) continue;
    const cs = getComputedStyle(el);
    const bg = toHex(cs.backgroundColor);
    if (!bg) continue;
    code = { bg, fg: toHex(cs.color), radius: cs.borderRadius, family: cs.fontFamily, sample: clean(el.innerText).slice(0, 200) };
    break;
  }

  // ---- sections (for element screenshots)
  const sections = [];
  const secCands = document.querySelectorAll('header,main>section,main>div,section,footer,[class*=hero i],[id*=pricing i],[class*=pricing i],[class*=testimonial i],[class*=feature i]');
  const docW = document.documentElement.clientWidth;
  for (const s of secCands) {
    if (sections.length >= 40) break;
    const r = s.getBoundingClientRect();
    if (r.height < 160 || r.height > 4000 || r.width < docW * 0.6 || !vis(s)) continue;
    if (sections.some((o) => o.el.contains(s) || s.contains(o.el))) continue;
    const h = s.querySelector('h1,h2,h3');
    sections.push({ el: s, label: h ? clean(h.innerText).slice(0, 80) : (s.id || s.tagName.toLowerCase()), box: box(s) });
  }
  sections.sort((a, b) => a.box[1] - b.box[1]);
  sections.forEach((s, i) => s.el.setAttribute('data-st-section', String(i)));

  const layout = {
    height: Math.max(document.body.scrollHeight, document.documentElement.scrollHeight), width: document.documentElement.scrollWidth,
    bgLuminance: roles.background ? Number(lum(roles.background).toFixed(3)) : null,
    darkSupport: [...document.styleSheets].some((sh) => { try { return [...sh.cssRules].some((r) => r.media && /prefers-color-scheme:\s*dark/.test(r.media.mediaText)); } catch { return false; } }) || /dark/.test(metaTags['color-scheme'] || ''),
    libraries: {
      three: !!window.THREE || !!document.querySelector('canvas[data-engine*=three]'), gsap: !!window.gsap, lottie: !!window.lottie || !!document.querySelector('lottie-player,dotlottie-player'),
      framer: !!document.querySelector('[data-framer-name],[class*=framer-]'), webflow: !!document.documentElement.getAttribute('data-wf-site'),
      nextjs: !!document.getElementById('__next') || !!window.__NEXT_DATA__, canvasCount: document.querySelectorAll('canvas').length,
    },
  };

  return {
    meta, headings, copy, ctas: ctaList, testimonials, stats, nav,
    tokens: { cssVariables: vars, colorVariables: colorVars, crossOriginSheets: crossOrigin,
      radii: [...radii.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([v, c]) => ({ value: v, count: c })),
      shadows: [...shadows.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([v, c]) => ({ value: v, count: c })) },
    colors: { roles, palette },
    fonts: { loaded: fontsLoaded.map(({ key, ...f }) => f).slice(0, 40), roles: fontRoles, faces: fontFaces },
    images, backgrounds, videos, svgs, wordmark, code,
    sections: sections.map(({ el, ...s }) => s), layout,
    text: clean(document.body.innerText).slice(0, 20000),
  };
}

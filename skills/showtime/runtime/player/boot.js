/* showtime export: boot script of the stage document inside an exported HTML video.
 *
 * The player (runtime/player/player.js) loads the project page into an <iframe srcdoc> whose head
 * holds, in this order: <base href> on the export's virtual origin, the packed files (inline JSON,
 * or assets/vfs.js with --folder), a small config (#st-cfg) and this script, inline. This script:
 *   1. turns the packed files into blob: URLs created by this document (so it works even when the
 *      host sandboxes the page and the two documents do not share an origin);
 *   2. hands stage.js the settings the renderer uses (showtime.json, seed): the same frames as
 *      `showtime render` (virtual clock, seeded randomness);
 *   3. maps every URL the page asks for at run time (fetch, XHR, img.src, setAttribute, innerHTML,
 *      FontFace, styles) to the packed files, so nothing touches the network;
 *   4. writes the page itself (URLs rewritten) into the document with document.write;
 *   5. answers the player over postMessage: ready, seek, paint, score (the whole score, or a piece
 *      of it from any time: the player streams a Synth score in pieces), look (the font files of
 *      the film's title and body families, so the player's start screen uses them, and where text
 *      sits in the current frame, so the start screen does not cover it), and forwards key presses.
 */
(function () {
  'use strict';
  var W = window, D = document;
  var cfgEl = D.getElementById('st-cfg');
  if (!cfgEl) return;
  var C = JSON.parse(cfgEl.textContent);
  var VORIGIN = C.vorigin;
  var FILES = W.__ST_FILES__ || null;
  var packEl = D.getElementById('st-pack');
  if (!FILES && packEl) FILES = JSON.parse(packEl.textContent);
  FILES = FILES || {};
  if (packEl) packEl.textContent = '';
  cfgEl.textContent = '';
  var PARENT = W.parent !== W ? W.parent : null;
  function post(msg, transfer) { if (PARENT) { try { PARENT.postMessage(msg, '*', transfer || []); } catch (e) { /* gone */ } } }

  // ------------------------------------------------------------------ packed files -> blob: URLs
  var blobs = {};
  function b64bytes(b64) {
    var bin = atob(b64), n = bin.length, u = new Uint8Array(n);
    for (var i = 0; i < n; i++) u[i] = bin.charCodeAt(i);
    return u;
  }
  function pathOf(abs) {
    if (typeof abs !== 'string' || abs.indexOf(VORIGIN + '/') !== 0) return null;
    var p = abs.slice(VORIGIN.length).split('#')[0].split('?')[0];
    try { p = decodeURIComponent(p); } catch (e) { /* keep */ }
    return p;
  }
  function absOf(u, base) { try { return new URL(u, base).href; } catch (e) { return null; } }
  function hashOf(abs) { var i = abs.indexOf('#'); return i < 0 ? '' : abs.slice(i); }
  function isCssEntry(e) { return !!e && /^text\/css/.test(e.t || ''); }
  function isFontEntry(p, e) { return !!e && (/^font\//.test(e.t || '') || /\.(woff2?|ttf|otf)$/i.test(p)); }
  // Stylesheet text and font bytes stay readable after their blob: URL is made: styles are written
  // inline and fonts become FontFace objects built from their bytes (see "styles and fonts" below).
  var keep = {};
  function rawOf(p) {
    if (Object.prototype.hasOwnProperty.call(keep, p)) return keep[p];
    var e = FILES[p];
    if (!e || e.u) return null;
    var v = typeof e.s === 'string' ? e.s : (typeof e.b === 'string' ? b64bytes(e.b) : null);
    if (v !== null && (isCssEntry(e) || isFontEntry(p, e))) keep[p] = v;
    return v;
  }
  function blobFor(p, busy) {
    if (blobs[p]) return blobs[p];
    var e = FILES[p];
    if (!e) return null;
    if (e.u) return (blobs[p] = absOf(e.u, C.assetBase)); // --folder: media stays a real file
    busy = busy || {};
    if (busy[p]) return VORIGIN + p;                        // CSS import cycle
    busy[p] = true;
    var data = rawOf(p);
    if (data === null) return null;
    if (typeof data === 'string' && isCssEntry(e)) data = rewriteCss(data, VORIGIN + p, busy);
    blobs[p] = URL.createObjectURL(new Blob([data], { type: e.t || 'application/octet-stream' }));
    blobPaths[blobs[p]] = p;
    e.b = null; e.s = null;
    return blobs[p];
  }
  var blobPaths = {};
  /** Absolute URL on the virtual origin -> blob: URL of a packed file, or null. */
  function urlFor(abs) {
    var p = pathOf(abs);
    if (p === null) return null;
    var b = blobFor(p);
    return b ? b + hashOf(abs) : null;
  }
  function rewriteCss(text, base, busy) {
    text = String(text).replace(/@import\s+(?:url\(\s*)?(['"]?)([^'")\s;]+)\1\s*\)?/gi, function (all, q, u) {
      var p = pathOf(absOf(u, base));
      var b = p && FILES[p] ? blobFor(p, busy) : null;
      return b ? '@import url("' + b + '")' : all;
    });
    return text.replace(/url\(\s*(['"]?)([^'")]*?)\1\s*\)/gi, function (all, q, u) {
      if (!u || /^(data:|blob:|#|about:)/i.test(u)) return all;
      var abs = absOf(u, base);
      if (!abs) return all;
      var p = pathOf(abs);
      var b = p && FILES[p] ? blobFor(p, busy) : null;
      return 'url("' + (b ? b + hashOf(abs) : abs) + '")';
    });
  }

  // ------------------------------------------------------------------ styles and fonts, inline
  // A host may serve this page under a Content-Security-Policy stricter than the export's own: an
  // artifact viewer that allows inline styles only ("style-src 'unsafe-inline'", no blob: or data:)
  // and fonts from its own font CDN only. There a <link> to a blob: stylesheet and an @font-face
  // url(blob:) are both refused: the theme, the components' CSS and every font vanish, and the
  // text falls back to the browser's 16 px serif. So nothing here depends on those fetches:
  //   - every stylesheet is written into the page as <style> text, its @imports inlined;
  //   - every @font-face whose file is packed (or a data: URL) becomes a FontFace built from the
  //     font's bytes: an ArrayBuffer source is no fetch, so no font-src rule applies to it.
  // Fonts that still fail are reported (console, and the player: on screen with #st-debug).
  var RealFontFace = typeof W.FontFace === 'function' ? W.FontFace : null;
  var cssFaces = [];      // faces made here, for look(): {family, src: ArrayBuffer, d}
  var faceKeys = {};
  var warned = {};
  function warn(m) {
    if (warned[m]) return;
    warned[m] = true;
    try { console.warn('[showtime] ' + m); } catch (e) { /* ignore */ }
    post({ st: 'warn', message: m });
  }
  /** Split a CSS value on top-level `sep` (not inside quotes or parentheses). */
  function splitTop(v, sep) {
    var out = [], cur = '', q = '', depth = 0;
    v = String(v || '');
    for (var i = 0; i < v.length; i++) {
      var ch = v[i];
      if (q) { if (ch === '\\') { cur += ch + (v[i + 1] || ''); i++; continue; } if (ch === q) q = ''; }
      else if (ch === '"' || ch === "'") q = ch;
      else if (ch === '(') depth++;
      else if (ch === ')') depth = Math.max(0, depth - 1);
      else if (ch === sep && !depth) { out.push(cur); cur = ''; continue; }
      cur += ch;
    }
    out.push(cur);
    return out.map(function (s) { return s.trim(); }).filter(Boolean);
  }
  function declsOf(body) {
    var out = {};
    splitTop(body, ';').forEach(function (d) {
      var i = d.indexOf(':');
      if (i > 0) out[d.slice(0, i).trim().toLowerCase()] = d.slice(i + 1).trim();
    });
    return out;
  }
  function toBuf(u8) { return u8.byteOffset === 0 && u8.byteLength === u8.buffer.byteLength ? u8.buffer : u8.slice().buffer; }
  /** The bytes of a font URL (a packed file, one of its blob: URLs, or a data: URL) -> ArrayBuffer | null. */
  function fontBytes(u, base) {
    u = String(u || '').trim();
    var m = /^data:([^,]*),([\s\S]*)$/i.exec(u);
    if (m) {
      try { return /;base64$/i.test(m[1]) ? toBuf(b64bytes(m[2].replace(/\s+/g, ''))) : toBuf(new TextEncoder().encode(decodeURIComponent(m[2]))); } catch (e) { return null; }
    }
    var p = /^blob:/i.test(u) ? blobPaths[u.split('#')[0]] : pathOf(absOf(u, base));
    if (p === null || p === undefined || !isFontEntry(p, FILES[p])) return null;
    var raw = rawOf(p);
    return raw && typeof raw !== 'string' ? toBuf(raw) : null;
  }
  var FACE_DESC = { 'font-weight': 'weight', 'font-style': 'style', 'font-stretch': 'stretch', 'unicode-range': 'unicodeRange',
    'font-display': 'display', 'font-feature-settings': 'featureSettings', 'font-variation-settings': 'variationSettings',
    'ascent-override': 'ascentOverride', 'descent-override': 'descentOverride', 'line-gap-override': 'lineGapOverride', 'size-adjust': 'sizeAdjust' };
  function unquote(s) { return String(s || '').trim().replace(/^(['"])([\s\S]*)\1$/, '$2'); }
  /** Register a face from bytes (once per family, descriptors and file). */
  function addFace(family, buf, d, key) {
    if (!RealFontFace || !D.fonts) return false;
    if (faceKeys[key]) return true;
    var f;
    try { f = new RealFontFace(family, buf, d); D.fonts.add(f); } catch (e) {
      warn('font "' + family + '" could not be used: ' + clean(e));
      return false;
    }
    faceKeys[key] = f;
    if (cssFaces.length < 60) cssFaces.push({ family: family, src: buf, d: d });
    f.loaded.catch(function (e) { warn('font "' + family + '" (' + (d.weight || '400') + ' ' + (d.style || 'normal') + ') could not be read: ' + clean(e)); });
    return true;
  }
  /** @font-face rules with a usable source -> FontFace objects (the rule is removed); others stay. */
  function extractFaces(text, base) {
    return text.replace(/@font-face\s*\{([^{}]*)\}/gi, function (all, body) {
      var d = declsOf(body), fam = unquote(d['font-family']);
      if (!fam || !d.src || !RealFontFace) return all;
      var items = splitTop(d.src, ','), buf = null, src = '';
      for (var i = 0; i < items.length && !buf; i++) {
        var m = /url\(\s*(['"]?)([\s\S]*?)\1\s*\)/i.exec(items[i]);
        if (m) { src = m[2]; buf = fontBytes(src, base); }
      }
      if (!buf) return all;
      var desc = {};
      Object.keys(FACE_DESC).forEach(function (k) { if (d[k]) desc[FACE_DESC[k]] = unquote(d[k]); });
      var id = src.length > 300 ? src.length + ':' + src.slice(-80) : (pathOf(absOf(src, base)) || blobPaths[src] || src);
      return addFace(fam, buf, desc, [fam, desc.weight, desc.style, desc.stretch, desc.unicodeRange, id].join('|')) ? '' : all;
    });
  }
  /** `@import x layer(l) supports(s) media` conditions around inlined text. */
  function wrapCond(css, cond) {
    cond = String(cond || '').trim();
    var pre = '', post = '', m;
    if ((m = /^layer(?:\(\s*([^)]*?)\s*\))?/i.exec(cond))) {
      pre += '@layer' + (m[1] ? ' ' + m[1] : '') + '{'; post = '}' + post; cond = cond.slice(m[0].length).trim();
    }
    if (/^supports\(/i.test(cond)) {
      var depth = 0, i = 9;
      for (; i < cond.length; i++) { if (cond[i] === '(') depth++; else if (cond[i] === ')') { if (!depth) break; depth--; } }
      var s = cond.slice(9, i).trim();
      pre += '@supports ' + (/^\(/.test(s) || /^(not|selector|font-)/i.test(s) ? s : '(' + s + ')') + '{'; post = '}' + post;
      cond = cond.slice(i + 1).trim();
    }
    if (cond) { pre += '@media ' + cond + '{'; post = '}' + post; }
    return pre + css + post;
  }
  var IMPORT_RE = /@import\s+(?:url\(\s*(['"]?)([^'")]+)\1\s*\)|(['"])([^'"]+)\3)\s*([^;]*);?/gi;
  /**
   * Stylesheet text as it is written inline: packed @imports replaced by their (processed) text,
   * packed fonts turned into FontFaces, other url()s mapped to the packed files.
   */
  function inlineCss(text, base, seen) {
    seen = seen || {};
    var parts = [], hoist = [];
    text = String(text).replace(/\/\*[\s\S]*?\*\//g, '').replace(IMPORT_RE, function (all, q1, u1, q2, u2, cond) {
      var u = u1 || u2, abs = absOf(u, base), p = abs ? pathOf(abs) : null, e = p !== null ? FILES[p] : null;
      if (e && !e.u && isCssEntry(e) && !seen[p] && typeof rawOf(p) === 'string') {
        var s2 = {};
        for (var k in seen) s2[k] = 1;
        s2[p] = 1;
        parts.push(wrapCond(inlineCss(rawOf(p), abs, s2), cond));
        return '\u0000' + (parts.length - 1) + '\u0000';
      }
      if (p !== null && !e) warn('stylesheet ' + p + ' is not in this file (imported from ' + (pathOf(base) || base) + ')');
      hoist.push('@import url("' + ((abs && urlFor(abs)) || abs || u) + '")' + (cond && cond.trim() ? ' ' + cond.trim() : '') + ';');
      return '';
    });
    text = rewriteCss(extractFaces(text, base), base);
    text = text.replace(/\u0000(\d+)\u0000/g, function (a, i) { return parts[+i]; });
    return hoist.join('') + text;
  }
  /** Text for a <style> element (a literal "</style" would end it early). */
  function styleText(css) { return String(css).replace(/<\/(style)/gi, '<\\/$1'); }
  /** A stylesheet URL that is a packed CSS file -> {p, abs} | null. */
  function cssHit(u, base) {
    if (u === null || u === undefined) return null;
    var s = String(u);
    var p = /^blob:/i.test(s) ? blobPaths[s.split('#')[0]] : null;
    var abs = p ? VORIGIN + p : absOf(s, base || D.baseURI);
    if (!p) p = abs ? pathOf(abs) : null;
    var e = p !== null && p !== undefined ? FILES[p] : null;
    return e && !e.u && isCssEntry(e) && typeof rawOf(p) === 'string' ? { p: p, abs: abs.split('#')[0] } : null;
  }
  /** Links to packed stylesheets made by script: written as <style> next to the link, which never fetches. */
  function hookLink(link, hit) {
    link.__stCss = hit;
    setAttr.call(link, 'data-st-href', hit.abs);
    if (link.isConnected) Promise.resolve().then(function () { convertLink(link); });
  }
  function convertLink(link) {
    var hit = link.__stCss;
    if (!hit || link.__stDone || !link.isConnected) return;
    link.__stDone = true;
    if (!/(^|\s)stylesheet(\s|$)/i.test(link.rel || '')) {   // a preload or an icon: a plain URL is fine
      setAttr.call(link, 'href', blobFor(hit.p) || hit.abs);
      return;
    }
    var st = D.createElement('style');
    st.__stMapped = true;
    setAttr.call(st, 'data-st-href', hit.abs);
    if (link.media) st.media = link.media;
    setAttr.call(st, 'data-st-inline', '');
    st.textContent = styleText(inlineCss(rawOf(hit.p), hit.abs));
    link.parentNode.insertBefore(st, link.nextSibling);
    link.__stStyle = st;
    setTimeout(function () { try { link.dispatchEvent(new Event('load')); } catch (e) { /* ignore */ } }, 0);
  }

  // ------------------------------------------------------------------ render settings
  W.__ST_RENDER__ = C.renderConfig;
  W.__ST_EXPORT__ = {
    version: C.generator, mode: 'export',
    /** A packed stylesheet's text, ready for a <style> element (null when the URL is not one). */
    css: function (u) { var h = cssHit(u); return h ? styleText(inlineCss(rawOf(h.p), h.abs)) : null; },
  };
  // Canvas pages size their backing store by devicePixelRatio: 1 gives the render's exact pixels.
  try { Object.defineProperty(W, 'devicePixelRatio', { configurable: true, get: function () { return 1; } }); } catch (e) { /* ignore */ }

  // ------------------------------------------------------------------ run-time URL mapping
  function mapUrl(u) {
    if (u === null || u === undefined) return u;
    var s = String(u);
    if (!s || /^(data:|blob:|javascript:|about:|mailto:|#)/i.test(s)) return s;
    var abs = absOf(s, D.baseURI);
    if (!abs) return s;
    return urlFor(abs) || s;
  }
  function mapSrcset(v) {
    return String(v).split(',').map(function (part) {
      var p = part.trim().split(/\s+/);
      if (p[0]) p[0] = mapUrl(p[0]);
      return p.join(' ');
    }).join(', ');
  }
  function mapCss(text) { return rewriteCss(String(text), D.baseURI); }
  function mapHtml(html) {
    var s = String(html);
    if (!/(src|href|poster|data|srcset)\s*=|url\(/i.test(s)) return s;
    s = s.replace(/(\s(?:src|href|poster|data|xlink:href)\s*=\s*)("([^"]*)"|'([^']*)')/gi, function (all, pre, q, a, b) {
      var v = a !== undefined ? a : b;
      var m = mapUrl(v.replace(/&amp;/g, '&'));
      return m === v ? all : pre + '"' + m + '"';
    });
    s = s.replace(/(\ssrcset\s*=\s*)("([^"]*)"|'([^']*)')/gi, function (all, pre, q, a, b) {
      return pre + '"' + mapSrcset(a !== undefined ? a : b) + '"';
    });
    if (/url\(/i.test(s)) s = mapCss(s);
    return s;
  }
  // This document's own URL is about:srcdoc: code that resolves against location.href / document.URL
  // (new URL('data/x.json', location.href)) gets the page's URL on the virtual origin instead.
  var RealURL = W.URL;
  function fixBase(b) {
    var s;
    try { s = b && typeof b === 'object' && 'href' in b ? b.href : String(b); } catch (e) { return b; }
    return /^about:srcdoc/i.test(s) ? D.baseURI : b;
  }
  if (typeof RealURL === 'function') {
    try {
      var StURL = class URL extends RealURL {
        constructor(u, b) { if (arguments.length > 1 && b !== undefined) super(u, fixBase(b)); else super(u); }
      };
      if (RealURL.canParse) StURL.canParse = function (u, b) { return b === undefined ? RealURL.canParse(u) : RealURL.canParse(u, fixBase(b)); };
      if (RealURL.parse) StURL.parse = function (u, b) { return b === undefined ? RealURL.parse(u) : RealURL.parse(u, fixBase(b)); };
      W.URL = StURL;
    } catch (e) { /* keep the real one */ }
  }
  var realFetch = W.fetch;
  if (realFetch) {
    W.fetch = function (input, init) {
      try {
        if (typeof input === 'string' || (RealURL && input instanceof RealURL)) return realFetch.call(W, mapUrl(String(input)), init);
        if (input && typeof input.url === 'string') {
          var m = mapUrl(input.url);
          if (m !== input.url) return realFetch.call(W, new Request(m, input), init);
        }
      } catch (e) { /* fall through */ }
      return realFetch.call(W, input, init);
    };
  }
  var xo = W.XMLHttpRequest && W.XMLHttpRequest.prototype.open;
  if (xo) {
    W.XMLHttpRequest.prototype.open = function (method, url) {
      var args = Array.prototype.slice.call(arguments);
      args[1] = mapUrl(url);
      return xo.apply(this, args);
    };
  }
  function patchProp(Ctor, prop, fn) {
    if (!Ctor) return;
    var proto = Ctor.prototype;
    var d = Object.getOwnPropertyDescriptor(proto, prop);
    if (!d || !d.set) return;
    Object.defineProperty(proto, prop, {
      configurable: true, enumerable: d.enumerable, get: d.get,
      set: function (v) { d.set.call(this, fn(v)); },
    });
  }
  if (W.HTMLLinkElement) {
    var lhd = Object.getOwnPropertyDescriptor(W.HTMLLinkElement.prototype, 'href');
    if (lhd && lhd.set) {
      Object.defineProperty(W.HTMLLinkElement.prototype, 'href', {
        configurable: true, enumerable: lhd.enumerable, get: lhd.get,
        set: function (v) {
          var hit = this.ownerDocument === D ? cssHit(v) : null;
          if (hit) hookLink(this, hit); else lhd.set.call(this, mapUrl(v));
        },
      });
    }
  }
  [['HTMLImageElement', 'src'], ['HTMLScriptElement', 'src'], ['HTMLMediaElement', 'src'],
    ['HTMLSourceElement', 'src'], ['HTMLVideoElement', 'poster'], ['HTMLIFrameElement', 'src'], ['HTMLEmbedElement', 'src'],
    ['HTMLObjectElement', 'data'], ['HTMLInputElement', 'src'], ['HTMLTrackElement', 'src']].forEach(function (p) {
    patchProp(W[p[0]], p[1], mapUrl);
  });
  patchProp(W.HTMLImageElement, 'srcset', mapSrcset);
  patchProp(W.HTMLSourceElement, 'srcset', mapSrcset);
  var URL_ATTRS = { src: 1, href: 1, poster: 1, data: 1, 'xlink:href': 1 };
  var EP = W.Element.prototype;
  var setAttr = EP.setAttribute, setAttrNS = EP.setAttributeNS;
  EP.setAttribute = function (name, value) {
    var n = String(name).toLowerCase();
    if (n === 'href' && this.tagName === 'LINK' && this.ownerDocument === D) {
      var hit = cssHit(value);
      if (hit) return hookLink(this, hit);
    }
    if (URL_ATTRS[n] && this.tagName !== 'A' && this.tagName !== 'a') value = mapUrl(value);
    else if (n === 'srcset') value = mapSrcset(value);
    else if (n === 'style' && /url\(/i.test(String(value))) value = mapCss(value);
    return setAttr.call(this, name, value);
  };
  EP.setAttributeNS = function (ns, name, value) {
    if (/(^|:)href$/i.test(String(name)) && this.tagName !== 'A' && this.tagName !== 'a') value = mapUrl(value);
    return setAttrNS.call(this, ns, name, value);
  };
  patchProp(W.Element, 'innerHTML', mapHtml);
  patchProp(W.Element, 'outerHTML', mapHtml);
  var iah = EP.insertAdjacentHTML;
  EP.insertAdjacentHTML = function (pos, html) { return iah.call(this, pos, mapHtml(html)); };
  if (W.Range && W.Range.prototype.createContextualFragment) {
    var ccf = W.Range.prototype.createContextualFragment;
    W.Range.prototype.createContextualFragment = function (html) { return ccf.call(this, mapHtml(html)); };
  }
  var CSD = W.CSSStyleDeclaration && W.CSSStyleDeclaration.prototype;
  if (CSD) {
    var sp = CSD.setProperty;
    CSD.setProperty = function (name, value, prio) {
      if (value && /url\(/i.test(String(value))) value = mapCss(value);
      return sp.call(this, name, value, prio);
    };
    ['cssText', 'background', 'backgroundImage', 'maskImage', 'webkitMaskImage', 'borderImage', 'borderImageSource',
      'listStyle', 'listStyleImage', 'content', 'cursor', 'mask', 'webkitMask'].forEach(function (p) {
      var d = Object.getOwnPropertyDescriptor(CSD, p);
      if (!d || !d.set) return;
      Object.defineProperty(CSD, p, {
        configurable: true, enumerable: d.enumerable, get: d.get,
        set: function (v) { d.set.call(this, v && /url\(/i.test(String(v)) ? mapCss(v) : v); },
      });
    });
  }
  if (W.MutationObserver) {
    // <style> elements created from script: their imports inlined, fonts made FontFaces, URLs mapped;
    // <link>s to packed stylesheets created from script: written as <style> (see hookLink)
    var onAdded = function (n) {
      if (n.tagName === 'STYLE' && !n.__stMapped && !n.hasAttribute('data-st-inline')) {
        n.__stMapped = true;
        if (/url\(|@import|@font-face/i.test(n.textContent || '')) n.textContent = styleText(inlineCss(n.textContent, D.baseURI));
      } else if (n.tagName === 'LINK' && n.__stCss) convertLink(n);
    };
    new MutationObserver(function (recs) {
      for (var i = 0; i < recs.length; i++) {
        var add = recs[i].addedNodes;
        for (var k = 0; k < add.length; k++) {
          var n = add[k];
          if (n.nodeType !== 1) continue;
          onAdded(n);
          if (n.firstElementChild && n.querySelectorAll) Array.prototype.forEach.call(n.querySelectorAll('style,link'), onAdded);
        }
      }
    }).observe(D, { childList: true, subtree: true });
  }
  function wrapCtor(name, argFix) {
    var Real = W[name];
    if (typeof Real !== 'function') return;
    var Wrapped = function () {
      var args = Array.prototype.slice.call(arguments);
      argFix(args);
      return new (Function.prototype.bind.apply(Real, [null].concat(args)))();
    };
    Wrapped.prototype = Real.prototype;
    try { Object.defineProperty(Wrapped, 'name', { value: name }); } catch (e) { /* ignore */ }
    W[name] = Wrapped;
  }
  // faces the page registers from script (Film.loadFonts): kept so the player can use the title font
  var scriptFaces = [];
  wrapCtor('FontFace', function (a) {
    if (typeof a[1] === 'string') {
      // url() of a packed font (or data:): its bytes, so no font-src rule of the host can refuse it
      var items = splitTop(a[1], ','), buf = null;
      for (var i = 0; i < items.length && !buf; i++) {
        var m = /url\(\s*(['"]?)([\s\S]*?)\1\s*\)/i.exec(items[i]);
        if (m) buf = fontBytes(m[2], D.baseURI);
      }
      a[1] = buf || mapCss(a[1]);
    }
    if (scriptFaces.length < 40) scriptFaces.push({ family: a[0], src: a[1], d: a[2] || {} });
  });
  wrapCtor('Audio', function (a) { if (typeof a[0] === 'string') a[0] = mapUrl(a[0]); });
  wrapCtor('Worker', function (a) { if (typeof a[0] === 'string' || (RealURL && a[0] instanceof RealURL)) a[0] = mapUrl(String(a[0])); });

  // ------------------------------------------------------------------ the page
  var URL_TAGS = { SCRIPT: ['src'], LINK: ['href'], IMG: ['src', 'srcset'], VIDEO: ['src', 'poster'], AUDIO: ['src'],
    SOURCE: ['src', 'srcset'], TRACK: ['src'], IFRAME: ['src'], EMBED: ['src'], OBJECT: ['data'], INPUT: ['src'],
    IMAGE: ['href', 'xlink:href'], USE: ['href', 'xlink:href'], FEIMAGE: ['href', 'xlink:href'] };
  function mapAttr(v, base) {
    if (!v || /^(data:|blob:|javascript:|about:|#)/i.test(v)) return v;
    var abs = absOf(v, base);
    return (abs && urlFor(abs)) || abs || v;
  }
  /** Page import-map entries -> dst, targets resolved to the packed files' blob: URLs. */
  function foldImports(dst, src, base) {
    if (!src || typeof src !== 'object') return;
    Object.keys(src).forEach(function (k) {
      if (typeof src[k] !== 'string') return;
      var target = absOf(src[k], base);
      if (!target) return;
      // URL-like keys ("./a.js", "/x/") are URLs themselves
      var key = /^(\.{0,2}\/)/.test(k) ? (absOf(k, base) || k) : k;
      if (/\/$/.test(key)) {
        Object.keys(FILES).forEach(function (p) {
          var e = FILES[p], v = VORIGIN + encodeURI(p);
          if (e.u || v.indexOf(target) !== 0 || v === target) return;
          dst[key + v.slice(target.length)] = blobFor(p);
        });
        dst[key] = target;
        return;
      }
      var p = pathOf(target);
      var b = p !== null && FILES[p] ? blobFor(p) : null;
      dst[key] = b ? b + hashOf(target) : target;
    });
  }
  function writePage() {
    var base = VORIGIN + C.page;
    var doc = new DOMParser().parseFromString(C.html, 'text/html');
    Array.prototype.forEach.call(doc.querySelectorAll('base'), function (b) { b.remove(); });
    Array.prototype.forEach.call(doc.querySelectorAll('script[src]'), function (s) {
      if (/(^|\/)_st\/stage\.js(\?|#|$)/.test(s.getAttribute('src') || '')) s.remove();
    });
    // stylesheets become <style> text (a host may refuse blob: stylesheets); preloads are not needed
    Array.prototype.forEach.call(doc.querySelectorAll('link[href]'), function (l) {
      var rel = String(l.getAttribute('rel') || '').toLowerCase();
      var hit = /(^|\s)stylesheet(\s|$)/.test(rel) && !/alternate/.test(rel) ? cssHit(l.getAttribute('href'), base) : null;
      if (hit) {
        var st = doc.createElement('style');
        st.setAttribute('data-st-href', hit.abs);
        st.setAttribute('data-st-inline', '');
        if (l.getAttribute('media')) st.setAttribute('media', l.getAttribute('media'));
        if (l.id) st.id = l.id;
        st.textContent = styleText(inlineCss(rawOf(hit.p), hit.abs));
        l.replaceWith(st);
      } else if (/(^|\s)(preload|prefetch)(\s|$)/.test(rel) && /^(font|style)$/i.test(l.getAttribute('as') || '')) l.remove();
      else if (/(^|\s)stylesheet(\s|$)/.test(rel)) {
        var abs = absOf(l.getAttribute('href'), base), p = abs ? pathOf(abs) : null;
        if (p !== null && !FILES[p]) warn('stylesheet ' + p + ' is not in this file');
      }
    });
    var all = doc.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
      var el = all[i], names = URL_TAGS[el.tagName.toUpperCase()];
      if (names) {
        for (var k = 0; k < names.length; k++) {
          var n = names[k];
          if (!el.hasAttribute(n)) continue;
          var v = el.getAttribute(n);
          if (/srcset$/.test(n)) {
            el.setAttribute(n, v.split(',').map(function (part) {
              var bits = part.trim().split(/\s+/); if (bits[0]) bits[0] = mapAttr(bits[0], base); return bits.join(' ');
            }).join(', '));
          } else el.setAttribute(n, mapAttr(v, base));
        }
      }
      var st = el.getAttribute('style');
      if (st && /url\(/i.test(st)) el.setAttribute('style', rewriteCss(st, base));
      if (el.tagName === 'STYLE' && !el.hasAttribute('data-st-inline')) {
        el.textContent = styleText(inlineCss(el.textContent, base));
        el.setAttribute('data-st-inline', '');
      }
    }
    var root = doc.documentElement;
    for (var a = 0; a < root.attributes.length; a++) D.documentElement.setAttribute(root.attributes[a].name, root.attributes[a].value);
    var imports = {};
    Object.keys(FILES).forEach(function (p) {
      var e = FILES[p];
      if (!e.u && /javascript/.test(e.t || '')) imports[VORIGIN + encodeURI(p)] = blobFor(p);
    });
    // The page's own import maps ("three": "/_lib/three/build/three.module.js", "three/addons/": ...)
    // point at virtual URLs, and an import map's result is never mapped again: fold them into this
    // one map with blob: targets (prefix entries expanded per packed file) and drop the originals.
    Array.prototype.forEach.call(doc.querySelectorAll('script[type="importmap"]'), function (s) {
      var j = null;
      try { j = JSON.parse(s.textContent || '{}'); } catch (e) { j = null; }
      s.remove();
      if (!j || typeof j !== 'object') return;
      foldImports(imports, j.imports, base);
      // module URLs are blob: URLs here, so scopes cannot match by URL: their entries apply everywhere
      if (j.scopes && typeof j.scopes === 'object') {
        Object.keys(j.scopes).forEach(function (sc) {
          var extra = {};
          foldImports(extra, j.scopes[sc], base);
          Object.keys(extra).forEach(function (k) { if (!(k in imports)) imports[k] = extra[k]; });
        });
      }
    });
    var bodyAttrs = '';
    for (var b = 0; b < doc.body.attributes.length; b++) {
      var at = doc.body.attributes[b];
      bodyAttrs += ' ' + at.name + '="' + at.value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;') + '"';
    }
    D.write('<script type="importmap">' + JSON.stringify({ imports: imports }).replace(/</g, '\\u003c') + '<\/script>' +
      '<script src="' + String(blobFor(C.stage)).replace(/&/g, '&amp;').replace(/"/g, '&quot;') + '"><\/script>' +
      doc.head.innerHTML + '</head><body' + bodyAttrs + '>' + doc.body.innerHTML);
  }

  // ------------------------------------------------------------------ the player's side of the conversation
  function clean(e) { return String(e && e.message || e); }
  function waitST(cb) { if (W.ST && W.ST.ready) return cb(W.ST); setTimeout(function () { waitST(cb); }, 20); }
  W.addEventListener('load', function () {
    waitST(function (ST) {
      ST.ready().then(function (info) {
        // a Synth score (or one marked .seekable) sounds the same rendered from any time: it can stream
        info.scoreSeekable = !!(typeof ST.score === 'function' && ST.score.seekable);
        post({ st: 'ready', info: info });
        try { fontReport(); } catch (e) { /* a report only */ }
      }, function (e) { post({ st: 'error', message: clean(e) }); });
    });
  });
  W.addEventListener('message', function (e) {
    if (e.source !== PARENT) return;
    var d = e.data || {};
    var ST = W.ST;
    if (!d.st || !ST) return;
    var reply = function (p) {
      p.then(function (v) { post({ st: 'done', id: d.id, value: v }); }, function (err) { post({ st: 'done', id: d.id, error: clean(err) }); });
    };
    if (d.st === 'seek') reply(ST.seek(d.t).then(function () { return null; }));
    else if (d.st === 'paint') reply(ST._paint().then(function () { return null; }));
    else if (d.st === 'look') {
      look(d.families || []).then(function (v) {
        post({ st: 'done', id: d.id, value: v }, v.fonts.map(function (f) { return f.data; }));
      }, function (err) { post({ st: 'done', id: d.id, error: clean(err) }); });
    }
    else if (d.st === 'score') {
      if (typeof ST.score !== 'function') return post({ st: 'done', id: d.id, value: null });
      renderScore(d.from || 0, d.duration, d.sampleRate || 48000).then(function (buf) {
        if (!buf) return post({ st: 'done', id: d.id, value: null });
        var chs = [];
        for (var c = 0; c < buf.numberOfChannels; c++) chs.push(new Float32Array(buf.getChannelData(c)));
        post({ st: 'done', id: d.id, value: { channels: chs, sampleRate: buf.sampleRate } }, chs.map(function (x) { return x.buffer; }));
      }, function (err) { post({ st: 'done', id: d.id, error: clean(err) }); });
    }
  });
  /** The score from film time `from` for `dur` seconds (the whole film when from = 0 and no dur). */
  function renderScore(from, dur, sr) {
    if (!from && !dur) return ST.renderScore({ sampleRate: sr });
    var len = Math.max(1, Math.ceil(dur * sr));
    var ctx = new OfflineAudioContext(2, len, sr);
    var bus = ctx.createGain();
    bus.connect(ctx.destination);
    return Promise.resolve(ST.score(ctx, bus, { duration: dur, sampleRate: sr, offline: true, from: from, to: from + dur }))
      .then(function () { return ctx.startRendering(); });
  }

  /** Say which fonts and stylesheets did not make it (console, and the player's #st-debug note). */
  function fontReport() {
    Array.prototype.forEach.call(D.querySelectorAll('link[rel~="stylesheet"]'), function (l) {
      var ok = false;
      try { ok = !!(l.sheet && l.sheet.cssRules); } catch (e) { ok = false; }
      if (!ok && !l.__stStyle) warn('stylesheet ' + (l.getAttribute('data-st-href') || l.getAttribute('href') || '?') + ' did not load: its rules are missing');
    });
    if (!D.fonts) return;
    var fams = {};
    D.fonts.forEach(function (f) {
      var k = famKey(f.family), r = fams[k] || (fams[k] = { name: unquote(f.family), ok: 0, bad: 0 });
      if (f.status === 'loaded') r.ok++; else if (f.status === 'error') r.bad++;
    });
    var bad = Object.keys(fams).filter(function (k) { return fams[k].bad && !fams[k].ok; });
    if (!bad.length) return;
    var used = {}, all = D.body ? D.body.getElementsByTagName('*') : [];
    for (var i = 0; i < all.length && i < 4000; i++) {
      for (var n = all[i].firstChild; n; n = n.nextSibling) {
        if (n.nodeType === 3 && /\S/.test(n.nodeValue)) { used[famKey(splitTop(getComputedStyle(all[i]).fontFamily, ',')[0])] = true; break; }
      }
    }
    bad.forEach(function (k) {
      warn('font "' + fams[k].name + '" did not load' + (used[k] ? ': the text set in it shows in the next font of its stack' : ''));
    });
  }

  // ------------------------------------------------------------------ look (for the player's start screen)
  function famKey(f) { return String(f || '').trim().replace(/^['"]|['"]$/g, '').toLowerCase(); }
  /** Every font face this document knows with its source: @font-face rules and script FontFaces. */
  function knownFaces() {
    var out = [];
    var walk = function (rules) {
      for (var i = 0; rules && i < rules.length; i++) {
        var r = rules[i];
        try {
          if (r.type === 5 && r.style) {        // CSSFontFaceRule
            out.push({ family: r.style.getPropertyValue('font-family'), src: r.style.getPropertyValue('src'),
              weight: r.style.getPropertyValue('font-weight') || '400', style: r.style.getPropertyValue('font-style') || 'normal',
              range: r.style.getPropertyValue('unicode-range') || '' });
          } else if (r.styleSheet) walk(r.styleSheet.cssRules);   // @import
          else if (r.cssRules) walk(r.cssRules);                   // @media, @supports, @layer
        } catch (e) { /* unreadable */ }
      }
    };
    for (var s = 0; s < D.styleSheets.length; s++) { try { walk(D.styleSheets[s].cssRules); } catch (e) { /* unreadable */ } }
    cssFaces.concat(scriptFaces).forEach(function (f) {
      out.push({ family: f.family, src: f.src, weight: String(f.d.weight || '400'), style: f.d.style || 'normal', range: f.d.unicodeRange || '' });
    });
    return out;
  }
  function firstUrl(src) {
    if (src && typeof src !== 'string') return src;   // an ArrayBuffer source
    var m = /url\(\s*(['"]?)([^'")]+)\1\s*\)/.exec(String(src || ''));
    return m ? m[2] : null;
  }
  /**
   * What shows in the current frame, as [x, y, w, h, weight] in 0-1 of the frame: text (weight 1),
   * pictures and panels such as a product window or a card (weight 0.5; the full-frame background
   * is left out).
   */
  function textRects() {
    var vw = W.innerWidth || 1, vh = W.innerHeight || 1, out = [];
    var F = W.Film;
    if (F && typeof F.frameInfo === 'function') {
      var fi = F.frameInfo() || {}, fw = fi.width || vw, fh = fi.height || vh;
      // only what is on screen (a zoomed camera draws plenty of text outside the frame)
      (fi.texts || []).forEach(function (t) {
        if (!(t.alpha > 0.15 && t.w > 2) || t.x + t.w < 0 || t.y + t.h < 0 || t.x > fw || t.y > fh) return;
        out.push([t.x / fw, t.y / fh, t.w / fw, t.h / fh, 1]);
      });
      return out.slice(0, 200);
    }
    var all = D.body ? D.body.getElementsByTagName('*') : [], area = vw * vh;
    for (var i = 0; i < all.length && out.length < 160; i++) {
      var el = all[i], has = false;
      if (/^(SCRIPT|STYLE|TEMPLATE|NOSCRIPT|HEAD|META|LINK)$/.test(el.tagName)) continue;
      for (var n = el.firstChild; n; n = n.nextSibling) if (n.nodeType === 3 && /\S/.test(n.nodeValue)) { has = true; break; }
      var r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2 || r.right < 0 || r.bottom < 0 || r.left > vw || r.top > vh) continue;
      var frac = r.width * r.height / area, weight = 1;
      if (!has) {
        if (frac < 0.01 || frac > 0.8) continue;                 // specks, and the backdrop
        var picture = /^(IMG|svg|VIDEO|CANVAS|PICTURE)$/i.test(el.tagName), cs = null;
        if (!picture) {
          cs = getComputedStyle(el);
          var bgc = /rgba?\(([^)]+)\)/.exec(cs.backgroundColor || ''), alpha = bgc ? (bgc[1].split(/[,\s/]+/).length > 3 ? parseFloat(bgc[1].split(/[,\s/]+/)[3]) : 1) : 0;
          if (!(alpha > 0.3 || (cs.backgroundImage && cs.backgroundImage !== 'none' && frac < 0.6))) continue;
        }
        weight = 0.5;
      }
      if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) continue;
      out.push([r.left / vw, r.top / vh, r.width / vw, r.height / vh, weight]);
    }
    return out;
  }
  /**
   * The poster frame's brightness as a 32 x 18 grid (0..1, row by row) read from the film's canvas,
   * so the start screen can deepen its scrim over a light picture. null when there is no canvas or
   * it cannot be read.
   */
  function lumaGrid() {
    try {
      var cv = D.querySelector('canvas');
      if (!cv || !cv.width || !cv.height) return null;
      var c = D.createElement('canvas'); c.width = 32; c.height = 18;
      var x = c.getContext('2d');
      x.drawImage(cv, 0, 0, 32, 18);
      var d = x.getImageData(0, 0, 32, 18).data, out = [];
      for (var i = 0; i < d.length; i += 4) out.push(+((0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2]) / 255).toFixed(3));
      return out;
    } catch (e) { return null; }
  }
  /** -> {fonts: [{family, weight, style, range, data: ArrayBuffer}], rects, luma} */
  function look(families) {
    var want = {};
    families.forEach(function (f) { var k = famKey(f); if (k) want[k] = true; });
    var faces = knownFaces().filter(function (f) { return want[famKey(f.family)]; }).slice(0, 8);
    var total = 0;
    var jobs = faces.map(function (f) {
      var u = firstUrl(f.src);
      if (!u) return Promise.resolve(null);
      var p = typeof u === 'string' ? W.fetch(u).then(function (r) { return r.arrayBuffer(); }) : Promise.resolve(u.slice ? u.slice(0) : u);
      return p.then(function (buf) {
        if (!buf || total + buf.byteLength > 1.5e6) return null;
        total += buf.byteLength;
        return { family: famKey(f.family), weight: f.weight, style: f.style, range: f.range, data: buf };
      }, function () { return null; });
    });
    return Promise.all(jobs).then(function (r) { return { fonts: r.filter(Boolean), rects: textRects(), luma: lumaGrid() }; });
  }

  W.addEventListener('keydown', function (e) {
    post({ st: 'key', key: e.key, code: e.code, shiftKey: e.shiftKey, metaKey: e.metaKey, ctrlKey: e.ctrlKey, altKey: e.altKey });
    if (!e.metaKey && !e.ctrlKey && !e.altKey && /^( |.|ArrowLeft|ArrowRight|ArrowUp|ArrowDown|Home|End|PageUp|PageDown|Enter)$/.test(e.key)) e.preventDefault();
  });
  W.addEventListener('error', function (e) { post({ st: 'pageerror', message: String(e.message || e.error || 'error') }); });

  writePage();
})();

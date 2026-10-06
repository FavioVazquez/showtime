/* showtime stage runtime (served at /_st/stage.js).
 *
 * One file, three roles:
 *   render  - injected by the renderer before any page script (virtual clock,
 *             seeded randomness, rAF queue) and driven frame by frame via ST.seek(t)
 *   preview - loaded by the page itself; inside the preview player it is driven by
 *             the player, opened on its own it redirects to the player
 *   player  - the preview player UI (scrubber, play/pause, frame step, loop, audio)
 *
 * The public API is the global `ST` (see references/stage-api.md). Loading this
 * file twice is harmless: the second copy returns immediately.
 */
(function () {
  'use strict';
  var W = window;
  if (W.ST && W.ST.__stage) return;

  var VERSION = '1.0.0';
  var EPOCH = 1767225600000; // 2026-01-01T00:00:00Z: what Date.now() reports at t = 0 in render mode

  // Real clocks and timers, saved before any shim replaces them.
  var real = {
    setTimeout: W.setTimeout.bind(W),
    clearTimeout: W.clearTimeout.bind(W),
    setInterval: W.setInterval.bind(W),
    raf: W.requestAnimationFrame ? W.requestAnimationFrame.bind(W) : function (cb) { return real.setTimeout(function () { cb(Date.now()); }, 16); },
    now: W.performance && W.performance.now ? W.performance.now.bind(W.performance) : Date.now,
    random: Math.random,
    Date: W.Date,
  };

  var RENDER = W.__ST_RENDER__ || null;
  var PLAYER = W.__ST_PLAYER__ || null;
  var search = '';
  try { search = W.location.search || ''; } catch (e) { /* opaque origin */ }
  var params = {};
  search.replace(/^\?/, '').split('&').forEach(function (kv) {
    if (!kv) return;
    var i = kv.indexOf('=');
    var k = decodeURIComponent(i < 0 ? kv : kv.slice(0, i));
    params[k] = i < 0 ? '1' : decodeURIComponent(kv.slice(i + 1));
  });
  var EMBED = params.st === 'embed';
  var RAW = params.st === 'raw';
  var MODE = RENDER ? 'render' : (PLAYER ? 'player' : 'preview');

  // ------------------------------------------------------------------ helpers
  function num(x) { var n = typeof x === 'number' ? x : parseFloat(x); return isFinite(n) ? n : NaN; }
  function clamp(x, a, b) { return x < a ? a : x > b ? b : x; }
  function isPromise(x) { return x instanceof Promise; } // NOT thenables: timelines are thenables that never settle
  function timeout(ms) { return new Promise(function (r) { real.setTimeout(r, ms); }); }
  function race(p, ms, label) {
    var timer;
    return Promise.race([p, new Promise(function (_, rej) {
      timer = real.setTimeout(function () { rej(new Error('timed out after ' + ms + ' ms: ' + label)); }, ms);
    })]).then(function (v) { real.clearTimeout(timer); return v; }, function (e) { real.clearTimeout(timer); throw e; });
  }
  function nextFrame() { return new Promise(function (r) { real.raf(function () { r(); }); }); }

  // ------------------------------------------------ deterministic randomness
  function hashStr(s) {
    var h = 2166136261 >>> 0;
    s = String(s);
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
    return h >>> 0;
  }
  function seedOf(seed) {
    if (seed === undefined || seed === null) return 0x5eed1234;
    return typeof seed === 'number' && isFinite(seed) ? (Math.floor(seed * 1000003) ^ 0x9e3779b9) >>> 0 : hashStr(seed);
  }
  function mulberry(a) {
    return function () {
      a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  /** ST.rand(seed) -> () => [0,1) with .range(a,b) .int(a,b) .pick(arr) .sign() */
  function rand(seed) {
    var r = mulberry(seedOf(seed));
    r.range = function (a, b) { return a + (b - a) * r(); };
    r.int = function (a, b) { return Math.floor(a + (b - a + 1) * r()); };
    r.pick = function (arr) { return arr[Math.floor(r() * arr.length)]; };
    r.sign = function () { return r() < 0.5 ? -1 : 1; };
    return r;
  }
  function lattice(i, seed) {
    var h = Math.imul((i | 0) ^ seed, 0x27d4eb2d) ^ Math.imul(seed + 0x165667b1, 0x85ebca6b);
    h ^= h >>> 15; h = Math.imul(h, 0x2c1b3c6d); h ^= h >>> 12;
    return ((h >>> 0) / 4294967296) * 2 - 1;
  }
  function fade(t) { return t * t * t * (t * (t * 6 - 15) + 10); }
  /** ST.noise(x, seed) -> smooth 1D gradient noise in [-1, 1] */
  function noise(x, seed) {
    var s = seedOf(seed), i = Math.floor(x), f = x - i;
    var g0 = lattice(i, s), g1 = lattice(i + 1, s);
    var v = g0 * f + (g1 * (f - 1) - g0 * f) * fade(f);
    return clamp(v * 2, -1, 1);
  }
  /** ST.noise2(x, y, seed) -> smooth 2D gradient noise in [-1, 1] */
  function noise2(x, y, seed) {
    var s = seedOf(seed);
    var xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
    function g(ix, iy, dx, dy) {
      var a = (lattice(ix * 73856093 ^ iy * 19349663, s) + 1) * Math.PI;
      return Math.cos(a) * dx + Math.sin(a) * dy;
    }
    var u = fade(xf), v = fade(yf);
    var n00 = g(xi, yi, xf, yf), n10 = g(xi + 1, yi, xf - 1, yf);
    var n01 = g(xi, yi + 1, xf, yf - 1), n11 = g(xi + 1, yi + 1, xf - 1, yf - 1);
    var nx0 = n00 + u * (n10 - n00), nx1 = n01 + u * (n11 - n01);
    return clamp((nx0 + v * (nx1 - nx0)) * 1.414, -1, 1);
  }

  // --------------------------------------------------------- virtual clock
  var clock = { ms: 0, frame: 0 };
  var diag = {
    timers: { setTimeout: 0, setInterval: 0, where: [] },
    random: 0, transitions: 0, errors: [], videos: {}, clips: [], waits: [],
    rafFlushed: 0, seeks: 0,
  };
  var started = false;       // true after the first seek: timer use from here on is flagged
  var shimmed = false;
  var randState = 0x5eed1234;

  function callerLine() {
    try {
      var st = String(new Error().stack || '').split('\n');
      for (var i = 2; i < st.length; i++) {
        if (st[i].indexOf('/_st/stage.js') < 0 && /https?:\/\/[^\s)]+:\d+:\d+/.test(st[i])) {
          return st[i].trim().replace(/^at\s+/, '');
        }
      }
    } catch (e) { /* ignore */ }
    return '';
  }
  function installShim(seed) {
    if (shimmed) return;
    shimmed = true;
    randState = seedOf(seed);
    var RealDate = real.Date;
    var vnow = function () { return EPOCH + Math.round(clock.ms); };
    W.Date = new Proxy(RealDate, {
      construct: function (target, args, newTarget) {
        return Reflect.construct(target, args.length ? args : [vnow()], newTarget);
      },
      apply: function () { return new RealDate(vnow()).toString(); },
      get: function (target, prop, recv) {
        if (prop === 'now') return vnow;
        return Reflect.get(target, prop, recv);
      },
    });
    try { Object.defineProperty(W.performance, 'now', { configurable: true, writable: true, value: function () { return clock.ms; } }); } catch (e) { /* ignore */ }
    var rafQ = new Map(), rafId = 0;
    W.requestAnimationFrame = function (cb) { rafId += 1; rafQ.set(rafId, cb); return rafId; };
    W.cancelAnimationFrame = function (id) { rafQ.delete(id); };
    shimFlush = function () {
      if (!rafQ.size) return;
      var cbs = Array.from(rafQ.values());
      rafQ.clear();
      diag.rafFlushed += cbs.length;
      for (var i = 0; i < cbs.length; i++) {
        try { cbs[i](clock.ms); } catch (e) { reportError('requestAnimationFrame callback', e); }
      }
    };
    var gen = mulberry(randState);
    Math.random = function () { diag.random++; return gen(); };
    reseed = function (frame) { gen = mulberry((randState ^ Math.imul(frame + 1, 0x9e3779b1)) >>> 0); };
    try {
      var cr = W.crypto;
      if (cr && cr.getRandomValues) {
        cr.getRandomValues = function (arr) {
          var bytes = new Uint8Array(arr.buffer, arr.byteOffset, arr.byteLength);
          for (var i = 0; i < bytes.length; i++) bytes[i] = Math.floor(gen() * 256);
          return arr;
        };
        if (cr.randomUUID) {
          cr.randomUUID = function () {
            var h = '';
            for (var i = 0; i < 32; i++) h += Math.floor(gen() * 16).toString(16);
            return h.slice(0, 8) + '-' + h.slice(8, 12) + '-4' + h.slice(13, 16) + '-' +
              ((parseInt(h[16], 16) & 3) | 8).toString(16) + h.slice(17, 20) + '-' + h.slice(20, 32);
          };
        }
      }
    } catch (e) { /* ignore */ }
    // Timers stay real (asset loading needs them). Callbacks that run during playback are
    // counted (with where they were registered) so `showtime check` can point at them.
    function wrapTimer(kind, orig) {
      return function (fn, delay) {
        var args = Array.prototype.slice.call(arguments);
        var d = +delay || 0;
        if (typeof fn === 'function' && d > 0) {
          var where = diag.timers.where.length < 5 ? callerLine() : '';
          var f = fn;
          args[0] = function () {
            if (started) {
              diag.timers[kind]++;
              if (where && diag.timers.where.indexOf(where) < 0 && diag.timers.where.length < 5) diag.timers.where.push(where);
            }
            return f.apply(this, arguments);
          };
        }
        return orig.apply(W, args);
      };
    }
    W.setTimeout = wrapTimer('setTimeout', real.setTimeout);
    W.setInterval = wrapTimer('setInterval', real.setInterval);
  }
  var shimFlush = function () {};
  var reseed = function () {};

  // ----------------------------------------------------------------- config
  var cfg = { width: 1920, height: 1080, fps: 30, duration: 0, background: '#000', title: '' };
  var pageCfg = {};          // what the page passed to ST.config()
  var fileCfg = null;        // showtime.json (render: injected; preview: fetched)
  var cfgConflicts = [];
  var CFG_KEYS = ['width', 'height', 'fps', 'duration', 'background', 'title', 'poster'];
  function mergeConfig() {
    var out = { width: 1920, height: 1080, fps: 30, duration: 0, background: '#000', title: '' };
    cfgConflicts = [];
    CFG_KEYS.forEach(function (k) {
      var f = fileCfg && fileCfg[k] !== undefined && fileCfg[k] !== null ? fileCfg[k] : undefined;
      var p = pageCfg[k];
      if (f !== undefined) {
        out[k] = f;
        if (p !== undefined && String(p) !== String(f)) cfgConflicts.push({ key: k, page: p, file: f });
      } else if (p !== undefined) {
        out[k] = p;
      }
    });
    if (RENDER && RENDER.override) Object.keys(RENDER.override).forEach(function (k) { if (RENDER.override[k] != null) out[k] = RENDER.override[k]; });
    out.width = Math.round(num(out.width)) || 1920;
    out.height = Math.round(num(out.height)) || 1080;
    out.fps = num(out.fps) > 0 ? num(out.fps) : 30;
    out.duration = num(out.duration) > 0 ? num(out.duration) : 0;
    cfg = out;
    return cfg;
  }
  if (RENDER && RENDER.config) fileCfg = RENDER.config;
  mergeConfig();

  // ------------------------------------------------------------- base style
  var styleEl = null;
  function baseCSS() {
    var bg = RENDER && RENDER.alpha ? 'transparent' : (cfg.background || '#000');
    var css = '[data-start]:not([data-active]):not([data-keep]){display:none!important}' +
      '[data-start][data-keep]:not([data-active]){visibility:hidden!important}' +
      'html{background:' + bg + ';overflow:hidden}' +
      'html,body{margin:0;padding:0}' +
      'body{width:' + cfg.width + 'px;height:' + cfg.height + 'px;overflow:hidden;position:relative}' +
      'img.st-emoji{height:1em;width:1em;margin:0 .05em;vertical-align:-.12em;display:inline-block}';
    // alpha renders: the page ground and the themes' default scene/stage fills (--scene-bg, --bg) are
    // transparent; a background a scene sets itself (a plate) still paints
    if (RENDER && RENDER.alpha) css += 'html,body{background:transparent!important;background-image:none!important}' +
      ':root{--scene-bg:transparent!important}.stage{background:transparent!important}';
    // the canvas route (see syncVideoCanvases): a canvas-drawn video steps out of the flow, hidden.
    // Its transitions are off for good (a render finishes every transition at once anyway), so taking
    // data-st-hidden away to read the video's own style starts none.
    if (RENDER) css += 'video[data-st-canvas]{transition:none!important}' +
      'video[data-st-hidden]{position:absolute!important;left:0!important;top:0!important;width:1px!important;height:1px!important;' +
      'min-width:0!important;min-height:0!important;max-width:none!important;max-height:none!important;margin:0!important;' +
      'padding:0!important;border:0!important;visibility:hidden!important;pointer-events:none!important}';
    return css;
  }
  function injectStyle() {
    if (MODE === 'player') return true;
    var root = document.head || document.documentElement;
    if (!root) return false;
    if (!styleEl) {
      styleEl = document.createElement('style');
      styleEl.setAttribute('data-st-base', '');
      root.insertBefore(styleEl, root.firstChild);
    }
    styleEl.textContent = baseCSS();
    return true;
  }
  if (!injectStyle()) document.addEventListener('DOMContentLoaded', injectStyle, { once: true });

  // ------------------------------------------------------------------ clips
  var clipsDirty = true;
  var clipList = [];         // [{el, start, end, id, name}]
  var clipMap = new WeakMap();
  var mo = null;
  function watchClips() {
    if (mo || !W.MutationObserver || !document.documentElement) return;
    mo = new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var m = muts[i];
        if (m.type === 'childList' || (m.type === 'attributes' && m.attributeName !== 'data-active' && m.attributeName !== 'style')) { clipsDirty = true; return; }
      }
    });
    mo.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-start', 'data-dur', 'data-end', 'id'] });
  }
  var TIME_RE = /^\s*(?:(#[A-Za-z_][\w:.-]*)\s*(?:([+-])\s*(\d*\.?\d+))?|([+])?\s*(-?\d*\.?\d+)\s*s?)\s*$/;
  function parseClips() {
    clipsDirty = false;
    clipMap = new WeakMap();
    var els = document.querySelectorAll('[data-start]');
    var byId = {};
    var list = [];
    var invalid = [];
    for (var i = 0; i < els.length; i++) {
      var c = { el: els[i], start: NaN, end: Infinity, id: els[i].id || '', name: els[i].getAttribute('data-name') || els[i].id || '', state: 0 };
      list.push(c);
      clipMap.set(els[i], c);
      if (c.id) byId[c.id] = c;
    }
    function parentClip(c) {
      var p = c.el.parentElement;
      while (p) { var pc = clipMap.get(p); if (pc) return pc; p = p.parentElement; }
      return null;
    }
    function resolveSpec(c, spec, relTo, what) {
      var m = TIME_RE.exec(spec || '');
      if (!m) { invalid.push({ clip: c.name || tagOf(c.el), attr: what, value: spec, reason: 'not a time' }); return NaN; }
      if (m[1]) {
        var ref = byId[m[1].slice(1)];
        if (!ref) { invalid.push({ clip: c.name || tagOf(c.el), attr: what, value: spec, reason: 'no element with id ' + m[1] }); return NaN; }
        var e = resolve(ref).end;
        if (!isFinite(e)) { invalid.push({ clip: c.name || tagOf(c.el), attr: what, value: spec, reason: m[1] + ' has no end' }); return NaN; }
        var d = m[3] ? parseFloat(m[3]) : 0;
        return m[2] === '-' ? e - d : e + d;
      }
      var v = parseFloat(m[5]);
      if (m[4] === '+') return relTo + v;
      return v;
    }
    function resolve(c) {
      if (c.state === 2) return c;
      if (c.state === 1) { invalid.push({ clip: c.name || tagOf(c.el), attr: 'data-start', value: c.el.getAttribute('data-start'), reason: 'circular reference' }); c.start = NaN; return c; }
      c.state = 1;
      var pc = parentClip(c);
      var base = pc ? resolve(pc).start : 0;
      if (!isFinite(base)) base = 0;
      c.start = resolveSpec(c, c.el.getAttribute('data-start'), base, 'data-start');
      var dur = c.el.getAttribute('data-dur');
      var endA = c.el.getAttribute('data-end');
      if (dur !== null && dur !== '') {
        var dv = num(dur);
        if (isNaN(dv) || dv < 0) invalid.push({ clip: c.name || tagOf(c.el), attr: 'data-dur', value: dur, reason: 'must be a number >= 0' });
        c.end = c.start + (isNaN(dv) ? 0 : dv);
      } else if (endA !== null && endA !== '') {
        c.end = resolveSpec(c, endA, c.start, 'data-end');
        if (c.end < c.start) invalid.push({ clip: c.name || tagOf(c.el), attr: 'data-end', value: endA, reason: 'ends before it starts' });
      }
      c.state = 2;
      return c;
    }
    list.forEach(resolve);
    clipList = list;
    diag.clips = invalid;
    return list;
  }
  function tagOf(el) {
    if (!el || !el.tagName) return '?';
    var s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    else if (el.className && typeof el.className === 'string') s += '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.');
    return s;
  }
  function frameOf(t) { return Math.round(t * cfg.fps); }
  // a time written with a few decimals (7.0667 for frame 212 at 30 fps) snaps to that frame:
  // anything within 1 ms of a frame boundary is on it (-> that frame, else null)
  function onFrame(t) {
    var x = t * cfg.fps, r = Math.round(x);
    return Math.abs(x - r) < Math.max(1e-3, cfg.fps * 1e-3) ? r : null;
  }
  function edgeFrame(t) {
    var r = onFrame(t);
    return r !== null ? r : Math.ceil(t * cfg.fps);
  }
  function clipActive(c, f) {
    if (!isFinite(c.start)) return false;
    var sf = edgeFrame(c.start);
    if (f < sf) return false;
    if (!isFinite(c.end)) return true;
    var ef = edgeFrame(c.end);
    if (f < ef) return true;
    return cfg.duration > 0 && c.end >= cfg.duration - 1e-6; // a clip that reaches the end owns the last frame
  }
  function setVar(el, name, v) {
    if (el.style.getPropertyValue(name) !== v) el.style.setProperty(name, v);
  }
  function applyClips(t) {
    if (clipsDirty) parseClips();
    var f = frameOf(t);
    for (var i = 0; i < clipList.length; i++) {
      var c = clipList[i], el = c.el;
      var on = clipActive(c, f);
      var len = isFinite(c.end) ? c.end - c.start : (cfg.duration > 0 ? cfg.duration - c.start : 0);
      if (on) {
        if (!el.hasAttribute('data-active')) el.setAttribute('data-active', '');
        var local = Math.max(0, t - c.start);
        el.style.setProperty('--t', local.toFixed(4));
        el.style.setProperty('--p', (len > 0 ? clamp(local / len, 0, 1) : 1).toFixed(4));
        continue;
      }
      if (el.hasAttribute('data-active')) el.removeAttribute('data-active');
      if (!isFinite(c.start)) continue;
      // An inactive clip can still be on screen (a transition keeps the outgoing scene, and an
      // early-aligned window the incoming one), so its --t/--p are a function of t alone, never of
      // the previous seek: before its start it rests at 0, after its end it holds its last frame
      // (the value an in-order render leaves there).
      var before = f < edgeFrame(c.start), held = 0;
      if (!before) held = Math.max(0, (edgeFrame(c.end) - 1) / cfg.fps - c.start);
      setVar(el, '--t', held.toFixed(4));
      setVar(el, '--p', (before ? 0 : len > 0 ? clamp(held / len, 0, 1) : 1).toFixed(4));
    }
    var root = document.documentElement;
    if (root) {
      root.style.setProperty('--st-t', t.toFixed(4));
      root.style.setProperty('--st-p', (cfg.duration > 0 ? clamp(t / cfg.duration, 0, 1) : 0).toFixed(4));
    }
  }
  function baseTimeOf(el) {
    while (el) {
      var c = clipMap.get(el);
      if (c) return isFinite(c.start) ? c.start : 0;
      el = el.parentElement || (el.host || null); // host: pseudo/shadow content
    }
    return 0;
  }

  // ------------------------------------------------ handlers and adapters
  var handlers = [];         // [{name, fn}]
  function addHandler(name, fn) {
    if (typeof fn !== 'function') throw new TypeError('ST.' + (name ? 'adapter' : 'onSeek') + ' needs a function');
    handlers.push({ name: name || ('onSeek#' + (handlers.length + 1)), fn: fn });
    if (started && MODE !== 'render') real.setTimeout(function () { ST.seek(ST.t); }, 0);
    return function off() { handlers = handlers.filter(function (h) { return h.fn !== fn; }); };
  }
  function reportError(where, e) {
    var msg = where + ': ' + (e && e.message ? e.message : String(e));
    if (diag.errors.length < 50) diag.errors.push({ where: where, message: msg, t: clock.ms / 1000 });
    try { console.error('[showtime] ' + msg); } catch (x) { /* ignore */ }
    return msg;
  }

  // CSS animations, CSS transitions and Web Animations: pause and seek.
  var seekAnimations = function (t) {
    if (!document.getAnimations) return;
    var anims = document.getAnimations();
    for (var i = 0; i < anims.length; i++) {
      var a = anims[i];
      try {
        if (W.CSSTransition && a instanceof W.CSSTransition) { diag.transitions++; a.finish(); continue; }
        var target = a.effect && a.effect.target;
        if (target && target.closest && target.closest('[data-st-free]')) continue;
        var base = target ? baseTimeOf(target) : 0;
        if (a.playState !== 'paused') a.pause();
        a.currentTime = Math.max(0, (t - base) * 1000);
      } catch (e) { reportError('animation seek', e); }
    }
  };
  // Render mode: animations start held, not running. One that runs from page load until the
  // first seek goes to the compositor (transform, opacity), and pausing it there leaves the
  // last real-time value on screen until the property changes again: frame 0 came out with
  // the element a few pixels along, and composited layers were rasterised differently depending
  // on the frames seeked before ("raster noise"). Held from the start, a frame depends only on t.
  function holdAnimations() {
    var FREE = ':not([data-st-free],[data-st-free] *)';
    try {
      var sheet = new CSSStyleSheet();
      sheet.replaceSync(FREE + ',' + FREE + '::before,' + FREE + '::after' +
        '{animation-play-state:paused!important}');
      document.adoptedStyleSheets = document.adoptedStyleSheets.concat([sheet]);
    } catch (e) { reportError('animation hold', e); }
    var animate = W.Element && W.Element.prototype.animate;
    if (typeof animate !== 'function') return;
    W.Element.prototype.animate = function () {
      var a = animate.apply(this, arguments);
      try { if (!(this.closest && this.closest('[data-st-free]'))) a.pause(); } catch (e) { /* ignore */ }
      return a;
    };
  }

  // <video>: seek to the middle of the source frame and wait for 'seeked'.
  function videoTarget(v, t) {
    var base = v.hasAttribute('data-start') ? baseTimeOf(v) : baseTimeOf(v.parentElement);
    var off = num(v.getAttribute('data-offset')); if (isNaN(off)) off = 0;
    var rate = num(v.getAttribute('data-rate')); if (!(rate > 0)) rate = 1;
    var sfps = num(v.getAttribute('data-fps')); if (!(sfps > 0)) sfps = cfg.fps;
    var local = off + Math.max(0, t - base) * rate;
    var dur = v.duration;
    if (isFinite(dur) && dur > 0) {
      if (v.loop || v.hasAttribute('data-loop')) local = local % dur;
      local = Math.min(local, Math.max(0, dur - 0.5 / sfps));
    }
    return local + 0.5 / sfps;
  }
  // the video's own boxes (render mode reports a canvas-drawn video's boxes from its canvas, see below)
  var elementRects = W.Element && W.Element.prototype.getClientRects;
  function videoVisible(v) { return (elementRects ? elementRects.call(v) : v.getClientRects()).length > 0; }
  function seekVideos(t, playing) {
    var vids = document.querySelectorAll('video');
    var waits = [];
    for (var i = 0; i < vids.length; i++) {
      var v = vids[i];
      if (v.getAttribute('data-st') === 'off') continue;
      if (!v.muted) v.muted = true;
      var key = v.currentSrc || v.src || ('video#' + i);
      if (v.error) { diag.videos[key] = 'error ' + v.error.code + ' (codec not supported by this browser?)'; continue; }
      if (!videoVisible(v)) { if (!v.paused) v.pause(); continue; }
      var target = videoTarget(v, t);
      if (MODE !== 'render' && playing) {
        if (v.paused) { var p = v.play(); if (p && p.catch) p.catch(function () {}); }
        if (Math.abs(v.currentTime - target) > 0.25) v.currentTime = target;
        continue;
      }
      if (!v.paused) v.pause();
      if (Math.abs(v.currentTime - target) < 1e-4 && v.readyState >= 2 && !v.seeking) continue;
      if (MODE !== 'render') { v.currentTime = target; continue; }
      waits.push(seekVideo(v, t, key));
    }
    return waits;
  }
  function seekVideo(v, t, key) {
    return race(seekOne(v, t), 15000, 'video seek ' + key).catch(function (e) { diag.videos[key] = e.message; });
  }

  // ------------------------------------------- the canvas route for <video>
  // Render mode draws every <video> the page shows on a <canvas>. Chrome puts a paused video's new
  // frame on screen through a compositor submission of the video's own, and skips it while its
  // previous one is still unacknowledged (a busy or slow machine): the capture then shows the frame
  // before, or nothing for the first one, although 'seeked' and requestVideoFrameCallback have fired.
  // A canvas is in the page's own frame, which the capture waits for.
  //
  // Each video gets a canvas right after it that takes its place: the canvas is given the video's
  // computed style every frame (display, position, size, margins, flex and grid placement, object-fit,
  // transforms, opacity, filters, border-radius, masks, z-index, visibility...), read with the video
  // back in its own place, so it lays out and paints where the video did. The video itself steps out
  // of the flow, hidden (data-st-hidden), and keeps running its animations; its boxes
  // (getBoundingClientRect, offsetWidth...) report the canvas's, so scripts and `showtime check`
  // measure the same layout. Preview and live playback keep the plain <video>.
  //   data-st-video="native" on a <video>: leave it a plain video in renders too.
  //   <canvas data-st-video="ID">: the page's own canvas for <video id="ID"> (styled by the page,
  //   which `showtime adopt` writes); the frame is drawn there and the video hidden.
  var VIDEO_CANVAS_MAX = 268435456;  // Chrome's largest canvas (pixels); a bigger video stays a plain one
  var MIRROR_PROPS = ('display position float clear top right bottom left z-index box-sizing width height ' +
    'min-width min-height max-width max-height aspect-ratio margin-top margin-right margin-bottom margin-left ' +
    'padding-top padding-right padding-bottom padding-left ' +
    'border-top-width border-right-width border-bottom-width border-left-width ' +
    'border-top-style border-right-style border-bottom-style border-left-style ' +
    'border-top-color border-right-color border-bottom-color border-left-color ' +
    'border-top-left-radius border-top-right-radius border-bottom-right-radius border-bottom-left-radius ' +
    'border-image-source border-image-slice border-image-width border-image-outset border-image-repeat ' +
    'vertical-align flex-grow flex-shrink flex-basis order align-self justify-self ' +
    'grid-row-start grid-row-end grid-column-start grid-column-end ' +
    'object-fit object-position object-view-box image-rendering overflow-x overflow-y overflow-clip-margin ' +
    'opacity visibility filter backdrop-filter mix-blend-mode isolation clip-path ' +
    'mask-image mask-size mask-position mask-repeat mask-origin mask-clip mask-composite mask-mode ' +
    'transform transform-origin transform-box transform-style translate rotate scale backface-visibility ' +
    'offset-path offset-distance offset-rotate offset-anchor offset-position ' +
    'box-shadow outline-width outline-style outline-color outline-offset ' +
    'background-color background-image background-size background-position-x background-position-y ' +
    'background-repeat background-clip background-origin background-attachment background-blend-mode ' +
    'shape-outside shape-margin will-change contain zoom pointer-events').split(' ');
  var mirrorProps = null;  // the ones this browser knows
  var mirrors = new Set();
  function nativeVideo(v) { return v.getAttribute('data-st') === 'off' || v.getAttribute('data-st-video') === 'native'; }
  function pageCanvas(v) {
    if (!v.id) return null;
    var cs = document.querySelectorAll('canvas[data-st-video]');
    for (var i = 0; i < cs.length; i++) if (cs[i].getAttribute('data-st-video') === v.id) return cs[i];
    return null;
  }
  function canvasFits(v) { return !v.videoWidth || (v.videoWidth <= 32767 && v.videoHeight <= 32767 && v.videoWidth * v.videoHeight <= VIDEO_CANVAS_MAX); }
  /** In a render, is this video's frame captured from a canvas? (Its seek then waits longer for the frame.) */
  function drawnOnCanvas(v) { return MODE === 'render' && !nativeVideo(v) && (!!pageCanvas(v) || canvasFits(v)); }
  function drawFrame(v, c) {
    if (v.readyState < 2 || !v.videoWidth) return false;
    if (c.width !== v.videoWidth || c.height !== v.videoHeight) { c.width = v.videoWidth; c.height = v.videoHeight; c.__stT = NaN; }
    var src = v.currentSrc || v.src;
    if (c.__stT === v.currentTime && c.__stSrc === src) return true;
    var g = c.getContext('2d');
    if (!g) throw new Error('no 2D context for a ' + c.width + 'x' + c.height + ' canvas');
    g.clearRect(0, 0, c.width, c.height);            // transparent video: no trace of the frame before
    g.drawImage(v, 0, 0, c.width, c.height);
    c.__stT = v.currentTime; c.__stSrc = src;
    return true;
  }
  // inherited ones: the canvas is the video's sibling, so a value the video only inherits stays
  // `inherit` (a scene hidden after the seek, as the transition layer pass does, hides the canvas too)
  var MIRROR_INHERITED = { visibility: 1, 'pointer-events': 1, 'image-rendering': 1 };
  function readMirrorStyle(v) {
    var m = v.computedStyleMap(), out = {}, pm = v.parentElement ? v.parentElement.computedStyleMap() : null;
    if (!mirrorProps) mirrorProps = MIRROR_PROPS.filter(function (p) { try { m.getAll(p); return true; } catch (e) { return false; } });
    for (var i = 0; i < mirrorProps.length; i++) {
      var p = mirrorProps[i], val = m.getAll(p).map(String).join(', ');
      if (MIRROR_INHERITED[p] && pm && pm.getAll(p).map(String).join(', ') === val) val = 'inherit';
      out[p] = val;
    }
    return out;
  }
  function applyMirrorStyle(c, s) {
    var had = c.__stStyle || {};
    for (var k in s) if (had[k] !== s[k]) c.style.setProperty(k, s[k], 'important');
    c.__stStyle = s;
  }
  function unmirror(v, why) {
    var c = v.__stCanvas;
    v.removeAttribute('data-st-hidden'); v.removeAttribute('data-st-canvas');
    if (c) { mirrors.delete(c); c.remove(); c.__stVideo = null; }
    v.__stCanvas = null;
    if (why) {
      diag.videoNative = diag.videoNative || [];
      if (diag.videoNative.length < 20) diag.videoNative.push({ video: v.currentSrc || v.src || tagOf(v), why: why });
    }
  }
  /** After every seek in a render: draw each video's frame on its canvas and give the canvas its style. */
  function syncVideoCanvases() {
    mirrors.forEach(function (c) {
      var v = c.__stVideo;
      if (!v || !v.isConnected || v.__stCanvas !== c || nativeVideo(v)) { if (v && v.__stCanvas === c) unmirror(v); else { mirrors.delete(c); c.remove(); } }
    });
    var vids = document.querySelectorAll('video'), todo = [];
    for (var i = 0; i < vids.length; i++) {
      var v = vids[i];
      if (nativeVideo(v)) continue;
      var pc = pageCanvas(v);
      if (pc) {
        if (v.__stCanvas) unmirror(v);
        try { if (drawFrame(v, pc) && v.style.visibility !== 'hidden') v.style.visibility = 'hidden'; } catch (e) { reportError('video canvas #' + v.id, e); }
        continue;
      }
      if (!v.__stCanvas) {
        if (v.error || v.readyState < 2 || !v.videoWidth || !v.parentNode || !videoVisible(v)) continue;  // nothing to draw yet: the plain video
        if (!canvasFits(v)) continue;
        if (typeof v.computedStyleMap !== 'function') continue;
      }
      todo.push(v);
    }
    if (!todo.length) return;
    // read every video's style in its own place (one style pass, no layout), then hide them again
    todo.forEach(function (v) { if (v.__stCanvas) v.removeAttribute('data-st-hidden'); });
    var styles = todo.map(function (v) { try { return readMirrorStyle(v); } catch (e) { return e; } });
    todo.forEach(function (v, k) {
      var s = styles[k];
      if (s instanceof Error) { unmirror(v, 'style: ' + s.message); return; }
      var c = v.__stCanvas, fresh = !c;
      try {
        if (fresh) {
          c = document.createElement('canvas');
          c.setAttribute('data-st-videoframe', '');
          c.setAttribute('aria-hidden', 'true');
          c.__stVideo = v;
          v.__stCanvas = c;
          mirrors.add(c);
          v.setAttribute('data-st-canvas', '');
        }
        if (s.display !== 'none') drawFrame(v, c);
        if (v.nextSibling !== c) v.parentNode.insertBefore(c, v.nextSibling);
        applyMirrorStyle(c, s);
        v.setAttribute('data-st-hidden', '');
      } catch (e) { unmirror(v, e && e.message ? e.message : String(e)); }
    });
  }
  // A canvas-drawn video is out of the flow, 1 px and hidden; its boxes are its canvas's, so code that
  // measures the video (a cursor or camera aimed at it, check's layout audit) sees where it is drawn.
  function delegateVideoBoxes() {
    var P = W.HTMLVideoElement && W.HTMLVideoElement.prototype;
    if (!P) return;
    function drawnOn(v) { var c = v.__stCanvas; return c && c.isConnected && v.hasAttribute('data-st-hidden') ? c : null; }
    ['getBoundingClientRect', 'getClientRects'].forEach(function (k) {
      var f = W.Element.prototype[k];
      if (typeof f !== 'function') return;
      Object.defineProperty(P, k, { configurable: true, writable: true, value: function () { return f.call(drawnOn(this) || this); } });
    });
    [[W.HTMLElement, ['offsetLeft', 'offsetTop', 'offsetWidth', 'offsetHeight', 'offsetParent']],
      [W.Element, ['clientLeft', 'clientTop', 'clientWidth', 'clientHeight']]].forEach(function (pair) {
      pair[1].forEach(function (k) {
        var d = Object.getOwnPropertyDescriptor(pair[0].prototype, k);
        if (!d || !d.get) return;
        Object.defineProperty(P, k, { configurable: true, get: function () { return d.get.call(drawnOn(this) || this); } });
      });
    });
  }
  // A video that appeared after the page loaded (added by a handler, a new src) has no data yet: a
  // seek set then does nothing (no 'seeked' ever comes) and the frame shows nothing. Load it first.
  function videoData(v) {
    if (v.readyState >= 2 || v.error) return Promise.resolve();
    if (v.preload === 'none') v.preload = 'auto';
    return new Promise(function (res) {
      function ok() { v.removeEventListener('loadeddata', ok); v.removeEventListener('error', ok); res(); }
      v.addEventListener('loadeddata', ok);
      v.addEventListener('error', ok);
      // nothing to load at all: no src and no <source>
      if (!v.getAttribute('src') && !v.currentSrc && !v.querySelector('source')) { ok(); return; }
      // NETWORK_EMPTY: loading never started. (NETWORK_NO_SOURCE is also what a freshly set src reports
      // while the browser picks the resource, so it is not taken as "nothing to load".)
      if (v.networkState === 0) { try { v.load(); } catch (e) { ok(); } }
    });
  }
  function seekOne(v, t) {
    return videoData(v).then(function () {
      if (v.error) return null;
      var target = videoTarget(v, t);                    // again: the duration is known now
      if (Math.abs(v.currentTime - target) < 1e-4 && !v.seeking) return null;
      return new Promise(function (res) {
        // 'seeked' comes before the new frame reaches the compositor: a capture right after it can
        // still show the previous frame (black for the first one) on a slow machine. The wait also
        // takes the frame being presented (requestVideoFrameCallback, which fires after every seek of
        // a file with a picture), or 500 ms after 'seeked' if it never comes. It fires when the frame is
        // the player's current one, not when it is on screen (see the canvas route above); a canvas draws
        // the current one, so a video drawn on a canvas waits for it longer.
        var seeked = false, shown = typeof v.requestVideoFrameCallback !== 'function' || !v.videoWidth, timer = null;
        var exact = !shown && drawnOnCanvas(v);
        function end() {
          real.clearTimeout(timer);
          v.removeEventListener('seeked', done); v.removeEventListener('error', end); res();
        }
        // a 'seeked' that belongs to an earlier seek can still be queued: only ours ends the wait
        function done() {
          if (v.seeking) return;
          seeked = true;
          // a canvas-drawn video waits longer (2 s) for its frame callback; never forever, in case a browser never calls it
          if (shown) end(); else if (!timer) timer = real.setTimeout(end, exact ? 2000 : 500);
        }
        if (!shown) v.requestVideoFrameCallback(function () { shown = true; if (seeked) end(); });
        v.addEventListener('seeked', done);
        v.addEventListener('error', end);
        v.currentTime = target;
      });
    }).then(function () { return videoData(v); });
  }

  // ----------------------------------------------------------------- emoji
  // Emoji typed as text would be drawn by each OS's own emoji font (different art on macOS, Windows
  // and Linux, empty boxes on minimal Linux). Text emoji are swapped for Noto SVG images served at
  // /_st/emoji/<codepoints>.svg (install one with `showtime assets emoji <char>`). Opt out with
  // data-st-emoji="off" on any ancestor. Text-style symbols (©, ™, ↔ without U+FE0F) are left alone.
  var EMOJI_RE = null;
  try {
    EMOJI_RE = new RegExp('[\\u{1F1E6}-\\u{1F1FF}]{2}|(?:\\p{Emoji_Presentation}|\\p{Extended_Pictographic}\\uFE0F)' +
      '(?:\\uFE0F|[\\u{1F3FB}-\\u{1F3FF}]|\\u200D\\p{Extended_Pictographic}\\uFE0F?[\\u{1F3FB}-\\u{1F3FF}]?)*', 'gu');
  } catch (e) { EMOJI_RE = null; }
  var emojiPending = null;   // text nodes changed since the last scan (null = scan everything)
  var emojiObserver = null;
  function emojiCode(str) {
    var out = [];
    for (var ch of str) out.push(ch.codePointAt(0).toString(16));
    return out.join('-');
  }
  function emojiSkip(node) {
    var p = node.parentElement;
    if (!p || /^(SCRIPT|STYLE|NOSCRIPT|TEMPLATE|TITLE|TEXTAREA|OPTION)$/.test(p.tagName)) return true;
    if (p.namespaceURI && p.namespaceURI !== 'http://www.w3.org/1999/xhtml') return true;
    return !!(p.closest && p.closest('[data-st-emoji="off"]'));
  }
  function emojifyNode(node, imgs) {
    var text = node.nodeValue;
    if (!text || !EMOJI_RE || emojiSkip(node)) return;
    EMOJI_RE.lastIndex = 0;
    if (!EMOJI_RE.test(text)) return;
    EMOJI_RE.lastIndex = 0;
    var frag = document.createDocumentFragment(), last = 0, m;
    while ((m = EMOJI_RE.exec(text))) {
      if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      var img = document.createElement('img');
      img.className = 'st-emoji';
      img.alt = m[0];
      img.draggable = false;
      img.src = '/_st/emoji/' + emojiCode(m[0]) + '.svg';
      frag.appendChild(img);
      imgs.push(img);
      last = m.index + m[0].length;
    }
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
    if (node.parentNode) node.parentNode.replaceChild(frag, node);
  }
  /** Swap emoji in changed text for images; returns promises that settle when they are decoded. */
  function emojify() {
    if (!EMOJI_RE || !document.body || document.documentElement.getAttribute('data-st-emoji') === 'off') return [];
    var imgs = [], nodes = [];
    if (emojiPending === null) {
      var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      for (var n = w.nextNode(); n; n = w.nextNode()) nodes.push(n);
    } else {
      emojiPending.forEach(function (n) {
        if (n.nodeType === 3) nodes.push(n);
        else if (n.nodeType === 1) {
          var w2 = document.createTreeWalker(n, NodeFilter.SHOW_TEXT);
          for (var k = w2.nextNode(); k; k = w2.nextNode()) nodes.push(k);
        }
      });
    }
    emojiPending = new Set();
    if (!emojiObserver && W.MutationObserver) {
      emojiObserver = new MutationObserver(function (recs) {
        if (!emojiPending) return;
        recs.forEach(function (r) {
          if (r.type === 'characterData') emojiPending.add(r.target);
          else r.addedNodes.forEach(function (a) { if (!(a.nodeType === 1 && a.classList.contains('st-emoji'))) emojiPending.add(a); });
        });
      });
      emojiObserver.observe(document.body, { subtree: true, childList: true, characterData: true });
    }
    nodes.forEach(function (n) { if (n.isConnected) emojifyNode(n, imgs); });
    if (imgs.length) diag.emoji = (diag.emoji || 0) + imgs.length;
    return imgs.map(function (img) {
      return new Promise(function (r) {
        if (img.complete) return r();
        img.addEventListener('load', r, { once: true }); img.addEventListener('error', r, { once: true });
      }).then(function () { if (img.naturalWidth > 0 && img.decode) return img.decode().catch(function () {}); });
    });
  }

  // ------------------------------------------------------------- readiness
  var readyWaits = [];       // [{p, label, state}]
  var frameWaits = null;     // non-null while handlers run inside a seek
  function waitFor(p, label) {
    if (typeof p === 'function') p = p();
    if (!p || typeof p.then !== 'function') return p;
    var pr = Promise.resolve(p);
    if (frameWaits) { frameWaits.push(pr); return p; }
    var w = { p: pr, label: label || ('waitFor#' + (readyWaits.length + 1)), state: 'pending' };
    pr.then(function () { w.state = 'done'; }, function (e) { w.state = 'failed: ' + (e && e.message ? e.message : e); });
    readyWaits.push(w);
    return p;
  }
  function docLoaded() {
    if (document.readyState === 'complete') return Promise.resolve();
    return new Promise(function (r) { W.addEventListener('load', function () { r(); }, { once: true }); });
  }
  function preloadFonts() {
    if (!document.fonts) return Promise.resolve();
    var faces = [];
    document.fonts.forEach(function (f) { if (faces.length < 300) faces.push(f); });
    return Promise.all(faces.map(function (f) { return f.status === 'loaded' ? 0 : f.load().catch(function () { /* check reports it */ }); }))
      .then(function () { return document.fonts.ready; });
  }
  function decodeImages() {
    var imgs = Array.prototype.slice.call(document.images || []);
    return Promise.all(imgs.map(function (img) {
      var loaded = img.complete ? Promise.resolve() : new Promise(function (r) {
        img.addEventListener('load', r, { once: true }); img.addEventListener('error', r, { once: true });
      });
      return race(loaded, 15000, 'image ' + img.currentSrc).then(function () {
        if (img.naturalWidth > 0 && img.decode) return img.decode().catch(function () {});
      }).catch(function () {});
    }));
  }
  function videosLoaded() {
    var vids = Array.prototype.slice.call(document.querySelectorAll('video'));
    return Promise.all(vids.map(function (v) {
      if (v.getAttribute('data-st') === 'off') return 0;
      v.muted = true;
      if (v.preload === 'none') v.preload = 'auto';
      if (v.readyState >= 2 || v.error) return 0;
      return race(new Promise(function (r) {
        v.addEventListener('loadeddata', r, { once: true }); v.addEventListener('error', r, { once: true });
        if (v.networkState === 3) r();
      }), 15000, 'video ' + (v.currentSrc || v.src)).catch(function (e) { diag.videos[v.currentSrc || v.src || 'video'] = e.message; });
    }));
  }
  function inferDuration() {
    if (clipsDirty) parseClips();
    var end = 0, open = false;
    clipList.forEach(function (c) { if (isFinite(c.end)) end = Math.max(end, c.end); else if (isFinite(c.start)) open = true; });
    if (end > 0) return { seconds: end, source: 'clips' + (open ? ' (some clips have no end)' : '') };
    if (document.getAnimations) {
      var a = document.getAnimations(), m = 0;
      for (var i = 0; i < a.length; i++) {
        try {
          var ct = a[i].effect.getComputedTiming();
          if (isFinite(ct.endTime)) m = Math.max(m, ct.endTime / 1000 + baseTimeOf(a[i].effect.target));
        } catch (e) { /* ignore */ }
      }
      if (m > 0) return { seconds: m, source: 'css animations' };
    }
    return null;
  }
  var fileCfgP = null;
  function loadFileConfig() {
    if (fileCfg || RENDER) return Promise.resolve();
    if (!/^https?:$/.test(W.location.protocol)) return Promise.resolve();
    if (fileCfgP) return fileCfgP;
    fileCfgP = race(fetch('/showtime.json', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }), 5000, 'showtime.json')
      .then(function (j) { if (j && typeof j === 'object') { fileCfg = j; mergeConfig(); injectStyle(); } })
      .catch(function (e) { reportError('showtime.json', e); });
    return fileCfgP;
  }
  /**
   * showtime.json "questions" with their times resolved (the tools resolve voice cues before the
   * page sees them): [{id, t (pause), think, resume, from, prompt, choices, answer, reply: [...]}].
   */
  function questions() {
    var q = fileCfg && Array.isArray(fileCfg.questions) ? fileCfg.questions : [];
    return q.filter(function (x) { return x && isFinite(x.t); }).map(function (x) { return JSON.parse(JSON.stringify(x)); });
  }

  var readyPromise = null;
  var durationSource = 'config';
  function ready(opts) {
    if (readyPromise) return readyPromise;
    opts = opts || {};
    readyPromise = (async function () {
      await loadFileConfig();
      injectStyle();
      watchClips();
      await race(docLoaded(), 30000, 'page load event').catch(function (e) { reportError('ready', e); });
      // 60 s like the author gates below: a look signature's faces on a cold, busy 4-core runner (Windows on Arm,
      // check's several pages at once) took over 20 s, which failed check while the render of the same page passed
      await race(preloadFonts(), 60000, 'fonts').catch(function (e) { reportError('ready', e); });
      emojify();
      await decodeImages();
      await videosLoaded();
      // author gates, including ones added while earlier gates resolved
      for (var n = 0; n < 5; n++) {
        var pending = readyWaits.filter(function (w) { return w.state === 'pending'; });
        if (!pending.length) break;
        await race(Promise.all(pending.map(function (w) { return w.p.catch(function () {}); })), 60000,
          'ST.waitFor: ' + pending.map(function (w) { return w.label; }).join(', '));
      }
      parseClips();
      if (!(cfg.duration > 0)) {
        var inf = inferDuration();
        if (!inf) throw new Error('the video has no duration: set "duration" in showtime.json (or ST.config({duration})), ' +
          'or give clips data-start/data-dur');
        cfg.duration = inf.seconds;
        durationSource = inf.source;
      }
      await seek(opts.at || 0);
      return info();
    })();
    return readyPromise;
  }

  // ------------------------------------------------------------------ seek
  var seekChain = Promise.resolve();
  var current = 0;
  var playingHint = false;
  function quantize(t) {
    t = num(t);
    if (isNaN(t)) t = 0;
    var f = Math.floor(t * cfg.fps + 1e-9);
    if (cfg.duration > 0) f = Math.min(f, Math.max(0, Math.ceil(cfg.duration * cfg.fps - 1e-9) - 1));
    return Math.max(0, f) / cfg.fps;
  }
  function settle() {
    var mode = RENDER && RENDER.settle ? RENDER.settle : 'raf1';
    if (mode === 'none') return Promise.resolve();
    if (mode === 'raf1') return nextFrame();
    return nextFrame().then(nextFrame);
  }
  async function doSeek(tIn) {
    var t = quantize(tIn);
    var f = Math.round(t * cfg.fps);
    current = t;
    clock.ms = t * 1000;
    clock.frame = f;
    reseed(f);
    diag.seeks++;
    applyClips(t);
    var waits = [];
    var errs = [];
    frameWaits = waits;
    try {
      for (var i = 0; i < handlers.length; i++) {
        try {
          var r = handlers[i].fn(t, f);
          if (isPromise(r)) waits.push(r);
        } catch (e) { errs.push(reportError(handlers[i].name + ' at t=' + t.toFixed(3), e)); }
      }
    } finally { frameWaits = null; }
    if (emojiPending && emojiPending.size) waits = waits.concat(emojify());
    seekAnimations(t);
    shimFlush();
    waits = waits.concat(seekVideos(t, playingHint));
    if (waits.length) {
      await Promise.all(waits.map(function (p) {
        return p.catch(function (e) { errs.push(reportError('async onSeek at t=' + t.toFixed(3), e)); });
      }));
    }
    if (MODE === 'render') syncVideoCanvases();
    if (document.fonts && document.fonts.status === 'loading') await race(document.fonts.ready, 10000, 'fonts').catch(function () {});
    started = true;
    if (MODE === 'render') {
      await settle();
      if (errs.length) throw new Error(errs[0] + (errs.length > 1 ? ' (+' + (errs.length - 1) + ' more)' : ''));
    }
    return t;
  }
  function seek(t) {
    var p = seekChain.then(function () { return doSeek(t); });
    seekChain = p.catch(function () {});
    return p;
  }

  // ----------------------------------------------------------- audio score
  async function renderScore(o) {
    o = o || {};
    if (typeof ST.score !== 'function') return null;
    var sr = o.sampleRate || 48000;
    var dur = o.duration || cfg.duration;
    if (!(dur > 0)) throw new Error('renderScore: unknown duration');
    var ctx = new OfflineAudioContext(2, Math.ceil(dur * sr), sr);
    var bus = ctx.createGain();
    bus.connect(ctx.destination);
    await ST.score(ctx, bus, { duration: dur, sampleRate: sr, offline: true, from: 0 });
    return ctx.startRendering();
  }

  // ------------------------------------------------------------ public API
  function info() {
    if (clipsDirty && document.documentElement) parseClips();
    return {
      version: VERSION, mode: MODE, width: cfg.width, height: cfg.height, fps: cfg.fps,
      duration: cfg.duration, durationSource: durationSource,
      frames: Math.max(0, Math.round(cfg.duration * cfg.fps)), background: cfg.background,
      title: cfg.title || '', poster: cfg.poster, clips: clipList.length, handlers: handlers.map(function (h) { return h.name; }),
      hasScore: typeof ST.score === 'function', conflicts: cfgConflicts.slice(),
    };
  }
  // A clip edge as the stage applies it: a time within 1 ms of a frame (1.9667 at 60 fps) is that frame's
  // time (1.966666...), the frame the clip starts or ends on. Pages compare these with t (t >= start),
  // so they must agree with the stage: with the written 1.9667, frame 118 (t = 1.96667) showed the new
  // scene while `t >= start` was still false, and a canvas drawn only "while active" stayed blank on
  // the first frame after every cut.
  function edgeTime(x) {
    var r = isFinite(x) ? onFrame(x) : null;
    return r !== null ? r / cfg.fps : x;
  }
  function clips() {
    if (clipsDirty) parseClips();
    return clipList.map(function (c) {
      return { name: c.name, id: c.id, tag: tagOf(c.el), start: edgeTime(c.start), end: isFinite(c.end) ? edgeTime(c.end) : null };
    });
  }
  function progress(t, a, b, ease) {
    var p = b > a ? clamp((t - a) / (b - a), 0, 1) : (t >= a ? 1 : 0);
    return typeof ease === 'function' ? ease(p) : p;
  }
  var ease = {
    linear: function (p) { return p; },
    inQuad: function (p) { return p * p; },
    outQuad: function (p) { return 1 - (1 - p) * (1 - p); },
    inOutQuad: function (p) { return p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2; },
    outCubic: function (p) { return 1 - Math.pow(1 - p, 3); },
    inOutCubic: function (p) { return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2; },
    outExpo: function (p) { return p >= 1 ? 1 : 1 - Math.pow(2, -10 * p); },
    inOutExpo: function (p) { return p <= 0 ? 0 : p >= 1 ? 1 : p < 0.5 ? Math.pow(2, 20 * p - 10) / 2 : (2 - Math.pow(2, -20 * p + 10)) / 2; },
    outBack: function (p) { var c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2); },
    outElastic: function (p) { var c4 = (2 * Math.PI) / 3; return p <= 0 ? 0 : p >= 1 ? 1 : Math.pow(2, -10 * p) * Math.sin((p * 10 - 0.75) * c4) + 1; },
    // the rest of the standard set, same names as Film's F.E (pages written from memory use them)
    inSine: function (p) { return 1 - Math.cos(p * Math.PI / 2); },
    outSine: function (p) { return Math.sin(p * Math.PI / 2); },
    inOutSine: function (p) { return -(Math.cos(Math.PI * p) - 1) / 2; },
    inCubic: function (p) { return p * p * p; },
    inQuart: function (p) { return p * p * p * p; },
    outQuart: function (p) { return 1 - Math.pow(1 - p, 4); },
    inOutQuart: function (p) { return p < 0.5 ? 8 * p * p * p * p : 1 - Math.pow(-2 * p + 2, 4) / 2; },
    inExpo: function (p) { return p <= 0 ? 0 : Math.pow(2, 10 * p - 10); },
    inCirc: function (p) { return 1 - Math.sqrt(1 - p * p); },
    outCirc: function (p) { return Math.sqrt(1 - Math.pow(p - 1, 2)); },
    inBack: function (p) { var c1 = 1.70158; return (c1 + 1) * p * p * p - c1 * p * p; },
    inOutBack: function (p) {
      var c2 = 1.70158 * 1.525;
      return p < 0.5 ? (Math.pow(2 * p, 2) * ((c2 + 1) * 2 * p - c2)) / 2 : (Math.pow(2 * p - 2, 2) * ((c2 + 1) * (p * 2 - 2) + c2) + 2) / 2;
    },
  };

  // Library helpers. None of them returns the library object: several animation
  // libraries hand back "thenables" that only settle when playback ends.
  function animeHelper(tl, o) {
    o = o || {};
    var off = num(o.offset) || 0;
    if (tl && typeof tl.pause === 'function') { try { tl.pause(); } catch (e) { /* ignore */ } }
    addHandler(o.name || 'anime', function (t) { tl.seek(Math.max(0, t - off) * 1000, true); });
    return tl;
  }
  function gsapHelper(tl, o) {
    o = o || {};
    var off = num(o.offset) || 0;
    if (tl && tl.pause) tl.pause();
    addHandler(o.name || 'gsap', function (t) {
      var x = Math.max(0, t - off);
      tl.totalTime(x + 0.001, true); // forces a re-render even when x equals the cached time
      tl.totalTime(x, false);
    });
    return tl;
  }
  function lottieHelper(anim, o) {
    o = o || {};
    var off = num(o.offset) || 0;
    if (anim && anim.isLoaded === false && anim.addEventListener) {
      waitFor(new Promise(function (r) { anim.addEventListener('DOMLoaded', r); anim.addEventListener('data_failed', r); }), o.name || 'lottie');
    }
    addHandler(o.name || 'lottie', function (t) {
      var total = anim.totalFrames || 0, fr = anim.frameRate || 30;
      var frame = Math.max(0, t - off) * fr * (o.speed || 1);
      if (o.loop && total > 0) frame = frame % total;
      if (total > 0) frame = Math.min(frame, total - 1);
      anim.goToAndStop(frame, true);
    });
    return anim;
  }
  function threeHelper(a, b, c, d) {
    if (typeof a === 'function' && !b) { addHandler('three', a); return; }
    var o = a && a.renderer ? a : { renderer: a, scene: b, camera: c, update: d };
    addHandler(o.name || 'three', function (t, f) {
      var r = o.update ? o.update(t, f) : undefined;
      o.renderer.render(o.scene, o.camera);
      return isPromise(r) ? r : undefined;
    });
  }

  var ST = {
    __stage: true,
    version: VERSION,
    get mode() { return MODE; },
    get t() { return current; },
    get frame() { return Math.round(current * cfg.fps); },
    get cfg() { return Object.assign({}, cfg); },
    /** Stop-and-ask questions from showtime.json (see references/html-export.md § Questions). */
    get questions() { return questions(); },
    /** Resolves once showtime.json is read (at once in a render; a preview fetches it). */
    configReady: function () { return loadFileConfig(); },
    config: function (o) {
      if (o && typeof o === 'object') {
        Object.keys(o).forEach(function (k) { pageCfg[k] = o[k]; });
        mergeConfig();
        injectStyle();
      }
      return Object.assign({}, cfg);
    },
    onSeek: function (fn) { return addHandler('', fn); },
    adapter: function (name, fn) { return addHandler(String(name), fn); },
    waitFor: waitFor,
    rand: rand,
    noise: noise,
    noise2: noise2,
    seek: seek,
    ready: ready,
    info: info,
    clips: clips,
    diag: function () { return JSON.parse(JSON.stringify(Object.assign({}, diag, { waits: readyWaits.map(function (w) { return { label: w.label, state: w.state }; }) }))); },
    renderScore: renderScore,
    score: null,
    anime: animeHelper,
    gsap: gsapHelper,
    lottie: lottieHelper,
    three: threeHelper,
    progress: progress,
    ease: ease,
    clamp: clamp,
    lerp: function (a, b, p) { return a + (b - a) * p; },
    _setPlaying: function (v) { playingHint = !!v; },
    /** Wait for two real painted frames (tools use this after changing styles outside a seek). */
    _paint: function () { return nextFrame().then(nextFrame); },
  };
  Object.defineProperty(W, 'ST', { value: ST, configurable: false, writable: false, enumerable: true });

  if (RENDER) {
    installShim(RENDER.seed);
    holdAnimations();
    delegateVideoBoxes();
    return;
  }

  // ------------------------------------------------------------- preview
  if (MODE === 'preview') {
    if (EMBED) {
      if (params['st-shim'] !== '0') installShim('preview');
      return; // the player drives ST.seek()
    }
    var servedByShowtime = false;
    try {
      var scripts = document.getElementsByTagName('script');
      for (var si = 0; si < scripts.length; si++) if (/\/_st\/stage\.js(\?|$)/.test(scripts[si].src)) servedByShowtime = true;
    } catch (e) { /* ignore */ }
    if (!RAW && servedByShowtime && W.top === W) {
      W.location.replace('/_st/preview?page=' + encodeURIComponent(W.location.pathname));
      return;
    }
    // raw mode: loop in real time, no UI (keyboard: space pauses)
    var rawPaused = false, rawT0 = 0, rawP0 = 0;
    document.addEventListener('keydown', function (e) {
      if (e.code === 'Space') { rawPaused = !rawPaused; rawT0 = current; rawP0 = real.now(); e.preventDefault(); }
    });
    ready().then(function () {
      rawP0 = real.now();
      (function loop() {
        if (!rawPaused) {
          var t = rawT0 + (real.now() - rawP0) / 1000;
          if (t >= cfg.duration) { rawT0 = 0; rawP0 = real.now(); t = 0; }
          seek(t);
        }
        real.raf(loop);
      })();
    }).catch(function (e) { reportError('ready', e); });
    return;
  }

  // -------------------------------------------------------------- player
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { bootPlayer(PLAYER); }, { once: true });
  else bootPlayer(PLAYER);

  function bootPlayer(P) {
    var state = {
      t: 0, playing: false, loop: true, rate: 1, muted: false, safe: false, fit: true,
      duration: 0, fps: 30, width: 1920, height: 1080, busy: false, pending: null,
      clockT0: 0, clockP0: 0, audio: null, ready: false, err: null,
    };
    var $ = function (sel, root) { return (root || document).querySelector(sel); };
    var css = [
      ':root{--bg:#0e0f12;--panel:#17191e;--line:#2a2d35;--fg:#e8eaf0;--dim:#8b90a0;--accent:#6aa9ff;--bad:#ff6b6b;',
      'color-scheme:dark;font:13px/1.4 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}',
      '*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--fg);overflow:hidden}',
      '#st-app{display:flex;flex-direction:column;height:100%}',
      '#st-stagewrap{flex:1;position:relative;overflow:auto;display:flex;align-items:center;justify-content:center;min-height:0}',
      '#st-holder{position:relative;flex:none;box-shadow:0 0 0 1px var(--line),0 12px 40px rgba(0,0,0,.5)}',
      '#st-frame{position:absolute;left:0;top:0;border:0;transform-origin:0 0;background:#000}',
      '#st-safe{position:absolute;inset:0;pointer-events:none;display:none}',
      '#st-safe div{position:absolute;border:1px dashed rgba(255,214,10,.85)}#st-safe div.b{border-color:rgba(106,169,255,.8)}',
      '#st-bar{flex:none;background:var(--panel);border-top:1px solid var(--line);padding:8px 12px 10px}',
      '#st-track{position:relative;height:26px;cursor:pointer;touch-action:none}',
      '#st-rail{position:absolute;left:0;right:0;top:11px;height:4px;background:var(--line);border-radius:2px}',
      '#st-fill{position:absolute;left:0;top:11px;height:4px;background:var(--accent);border-radius:2px}',
      '#st-head{position:absolute;top:5px;width:2px;height:16px;background:#fff;margin-left:-1px;border-radius:1px}',
      '.st-mark{position:absolute;top:3px;width:1px;height:6px;background:var(--dim)}',
      '.st-mark span{position:absolute;top:-2px;left:3px;font-size:10px;color:var(--dim);white-space:nowrap;pointer-events:none}',
      '#st-row{display:flex;align-items:center;gap:8px;margin-top:4px;flex-wrap:wrap}',
      '#st-row button,#st-row select{background:#23262e;color:var(--fg);border:1px solid var(--line);border-radius:6px;',
      'padding:4px 9px;font:inherit;cursor:pointer;min-width:30px}',
      '#st-row button:hover{border-color:var(--accent)}#st-row button[aria-pressed=true]{background:#2c3b55;border-color:var(--accent)}',
      '#st-time{font-variant-numeric:tabular-nums;min-width:170px;font-family:ui-monospace,Menlo,Consolas,monospace}',
      '#st-status{color:var(--dim);margin-left:auto;font-size:12px;max-width:45%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
      '#st-err{display:none;background:#3a1518;color:#ffd7d7;border-bottom:1px solid var(--bad);padding:6px 12px;white-space:pre-wrap;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;max-height:30%;overflow:auto}',
      '#st-help{color:var(--dim);font-size:11px;margin-top:4px}',
    ].join('');
    var st = document.createElement('style');
    st.textContent = css;
    (document.head || document.documentElement).appendChild(st);
    document.title = (P.title ? P.title + ' - ' : '') + 'showtime preview';
    var app = document.getElementById('st-app') || document.body.appendChild(document.createElement('div'));
    app.id = 'st-app';
    app.innerHTML =
      '<div id="st-err"></div>' +
      '<div id="st-stagewrap"><div id="st-holder"><iframe id="st-frame" title="stage"></iframe><div id="st-safe"></div></div></div>' +
      '<div id="st-bar"><div id="st-track"><div id="st-rail"></div><div id="st-fill"></div><div id="st-marks"></div><div id="st-head"></div></div>' +
      '<div id="st-row">' +
      '<button id="st-play" title="Play / pause (Space)">Play</button>' +
      '<button id="st-back" title="Previous frame (Left, Shift+Left = 1 s)">&#9664;|</button>' +
      '<button id="st-fwd" title="Next frame (Right, Shift+Right = 1 s)">|&#9654;</button>' +
      '<span id="st-time">0:00.00 / 0:00.00</span>' +
      '<button id="st-loop" aria-pressed="true" title="Loop (L)">Loop</button>' +
      '<select id="st-rate" title="Speed"><option value="0.25">0.25x</option><option value="0.5">0.5x</option><option value="1" selected>1x</option><option value="2">2x</option></select>' +
      '<button id="st-mute" aria-pressed="false" title="Mute (M)">Sound</button>' +
      '<button id="st-safebtn" aria-pressed="false" title="Safe zones (S)">Safe</button>' +
      '<button id="st-fitbtn" aria-pressed="true" title="Fit to window / 100% (F)">Fit</button>' +
      '<span id="st-status">loading</span></div>' +
      '<div id="st-help">Space play/pause &middot; Left/Right frame &middot; Shift+Left/Right 1 s &middot; Home/End &middot; L loop &middot; M mute &middot; S safe zones &middot; F fit</div></div>';

    var frame = $('#st-frame'), holder = $('#st-holder'), wrap = $('#st-stagewrap');
    var statusEl = $('#st-status'), errEl = $('#st-err');
    function status(s) { statusEl.textContent = s; statusEl.title = s; }
    function showErr(msg) {
      if (!msg) { errEl.style.display = 'none'; errEl.textContent = ''; return; }
      errEl.style.display = 'block';
      errEl.textContent = (errEl.textContent ? errEl.textContent + '\n' : '') + msg;
    }
    function fmt(t) {
      t = Math.max(0, t);
      var m = Math.floor(t / 60), s = t - m * 60;
      return m + ':' + (s < 10 ? '0' : '') + s.toFixed(2);
    }
    function layout() {
      var w = state.width, h = state.height;
      frame.style.width = w + 'px'; frame.style.height = h + 'px';
      var s = 1;
      if (state.fit) {
        var aw = wrap.clientWidth - 24, ah = wrap.clientHeight - 24;
        s = Math.max(0.05, Math.min(aw / w, ah / h));
      }
      frame.style.transform = 'scale(' + s + ')';
      holder.style.width = Math.round(w * s) + 'px';
      holder.style.height = Math.round(h * s) + 'px';
      drawSafe(s);
    }
    function drawSafe(s) {
      var el = $('#st-safe');
      el.style.display = state.safe ? 'block' : 'none';
      if (!state.safe) return;
      var w = state.width, h = state.height, boxes = [];
      if (h > w) {
        // universal vertical box for feed UIs (TikTok / Reels / Shorts), scaled from 1080x1920
        var kx = w / 1080, ky = h / 1920;
        boxes.push(['', 64 * kx, 220 * ky, (1080 - 64 - 164) * kx, (1920 - 220 - 480) * ky]);
      } else {
        boxes.push(['', w * 0.05, h * 0.05, w * 0.9, h * 0.9]);
        boxes.push(['b', w * 0.1, h * 0.1, w * 0.8, h * 0.8]);
      }
      el.innerHTML = boxes.map(function (b) {
        return '<div class="' + b[0] + '" style="left:' + b[1] * s + 'px;top:' + b[2] * s + 'px;width:' + b[3] * s + 'px;height:' + b[4] * s + 'px"></div>';
      }).join('');
    }
    W.addEventListener('resize', layout);

    // ---- stage document
    var child = null;
    function childST() { try { return frame.contentWindow && frame.contentWindow.ST; } catch (e) { return null; } }
    function load(keepT) {
      state.ready = false;
      status('loading');
      showErr('');
      var sep = P.page.indexOf('?') >= 0 ? '&' : '?';
      frame.src = P.page + sep + 'st=embed&_=' + Date.now();
      frame.onload = function () {
        var cw = frame.contentWindow;
        try {
          cw.addEventListener('error', function (e) { showErr('page error: ' + (e.message || e.error)); });
          cw.addEventListener('unhandledrejection', function (e) { showErr('unhandled rejection: ' + (e.reason && e.reason.message || e.reason)); });
        } catch (e) { /* ignore */ }
        var tries = 0;
        (function poll() {
          child = childST();
          if (!child) {
            if (++tries > 100) { showErr('the page did not load /_st/stage.js'); status('error'); return; }
            return real.setTimeout(poll, 50);
          }
          child.ready().then(function (inf) {
            state.duration = inf.duration; state.fps = inf.fps; state.width = inf.width; state.height = inf.height;
            state.ready = true;
            layout();
            drawMarks();
            var t = Math.min(keepT || 0, Math.max(0, inf.duration - 1 / inf.fps));
            go(t);
            status(inf.width + 'x' + inf.height + ' @ ' + inf.fps + ' fps, ' + inf.duration.toFixed(2) + ' s' +
              (inf.conflicts.length ? ' (showtime.json overrides ST.config: ' + inf.conflicts.map(function (c) { return c.key; }).join(', ') + ')' : ''));
            prepareAudio();
          }).catch(function (e) { showErr('ready() failed: ' + (e && e.message || e)); status('error'); });
        })();
      };
    }
    function drawMarks() {
      var marks = $('#st-marks');
      var cl = [];
      try { cl = child.clips(); } catch (e) { /* ignore */ }
      var seen = {};
      marks.innerHTML = cl.filter(function (c) {
        if (!isFinite(c.start) || !c.name || seen[c.start.toFixed(2)]) return false;
        seen[c.start.toFixed(2)] = 1; return true;
      }).slice(0, 60).map(function (c) {
        var x = state.duration > 0 ? (c.start / state.duration) * 100 : 0;
        return '<div class="st-mark" style="left:' + x + '%" title="' + c.name + ' @ ' + c.start.toFixed(2) + 's"><span>' + c.name + '</span></div>';
      }).join('');
    }

    // ---- time + clock
    function render() {
      var d = state.duration || 1;
      var p = clamp(state.t / d, 0, 1) * 100;
      $('#st-fill').style.width = p + '%';
      $('#st-head').style.left = p + '%';
      var f = Math.floor(state.t * state.fps + 1e-9);
      $('#st-time').textContent = fmt(state.t) + ' / ' + fmt(state.duration) + '  f' + f;
      $('#st-play').textContent = state.playing ? 'Pause' : 'Play';
    }
    function go(t) {
      state.t = clamp(t, 0, Math.max(0, state.duration - 1e-6));
      render();
      push();
    }
    function push() {
      if (!child || !state.ready) return;
      if (state.busy) { state.pending = state.t; return; }
      state.busy = true;
      try { child._setPlaying(state.playing); } catch (e) { /* ignore */ }
      child.seek(state.t).catch(function (e) { showErr(String(e && e.message || e)); }).then(function () {
        state.busy = false;
        if (state.pending !== null) { state.pending = null; push(); } // catch up with the latest requested time
      });
    }
    function clockNow() {
      var a = state.audio;
      if (a && a.ctx && a.running && a.ctx.state === 'running') return state.clockT0 + Math.max(0, a.ctx.currentTime - a.c0) * state.rate;
      return state.clockT0 + (real.now() - state.clockP0) / 1000 * state.rate;
    }
    function play() {
      if (!state.ready) return;
      if (state.t >= state.duration - 1 / state.fps) state.t = 0;
      state.playing = true;
      state.clockT0 = state.t; state.clockP0 = real.now();
      startAudio();
      render();
    }
    function pause() {
      state.playing = false;
      stopAudio();
      try { child && child._setPlaying(false); } catch (e) { /* ignore */ }
      go(Math.floor(state.t * state.fps + 1e-9) / state.fps);
    }
    function tick() {
      if (state.playing) {
        var t = clockNow();
        if (t >= state.duration) {
          if (state.loop) { state.t = 0; state.clockT0 = 0; state.clockP0 = real.now(); stopAudio(); startAudio(); t = 0; }
          else { state.t = Math.max(0, state.duration - 1 / state.fps); pause(); real.raf(tick); return; }
        }
        state.t = t;
        render();
        push();
      }
      real.raf(tick);
    }
    real.raf(tick);
    function step(df) { if (state.playing) pause(); go((Math.floor(state.t * state.fps + 1e-9) + df) / state.fps); }

    // ---- audio: pre-rendered score + mix file, started at an offset so scrubbing stays in sync
    function prepareAudio() {
      var a = state.audio = state.audio || { buffers: {}, ctx: null, sources: [], running: false, c0: 0 };
      var jobs = [];
      if (P.mix) {
        jobs.push(fetch(P.mix, { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.arrayBuffer(); })
          .then(function (ab) { return decode(ab); }).then(function (b) { a.buffers.mix = b; })
          .catch(function (e) { showErr('could not load audio ' + P.mix + ': ' + e.message); }));
      }
      var inf = child.info();
      if (inf.hasScore) {
        status('rendering score audio...');
        jobs.push(child.renderScore({ sampleRate: 48000 }).then(function (buf) {
          if (!buf) return;
          var ctx = audioCtx();
          var copy = ctx.createBuffer(buf.numberOfChannels, buf.length, buf.sampleRate);
          for (var c = 0; c < buf.numberOfChannels; c++) copy.copyToChannel(buf.getChannelData(c), c);
          a.buffers.score = copy;
        }).catch(function (e) { showErr('ST.score failed: ' + (e && e.message || e)); }));
      }
      Promise.all(jobs).then(function () {
        var names = Object.keys(a.buffers);
        status(state.width + 'x' + state.height + ' @ ' + state.fps + ' fps, ' + state.duration.toFixed(2) + ' s' +
          (names.length ? ', audio: ' + names.join(' + ') : ', no audio'));
        if (state.playing) { stopAudio(); state.clockT0 = state.t; state.clockP0 = real.now(); startAudio(); }
      });
    }
    function audioCtx() {
      var a = state.audio;
      if (!a.ctx) a.ctx = new (W.AudioContext || W.webkitAudioContext)({ sampleRate: 48000 });
      return a.ctx;
    }
    function decode(ab) {
      var ctx = audioCtx();
      return new Promise(function (res, rej) { ctx.decodeAudioData(ab, res, rej); });
    }
    function startAudio() {
      var a = state.audio;
      if (!a || state.muted || state.rate !== 1) return;
      var names = Object.keys(a.buffers);
      if (!names.length) return;
      var ctx = audioCtx();
      if (ctx.state !== 'running') {
        // autoplay policy: keep time with the wall clock until the context runs, then join in sync
        ctx.resume().then(function () {
          if (state.playing && !state.audio.running) { state.clockT0 = clockNow(); state.clockP0 = real.now(); state.t = state.clockT0; startAudio(); }
        }).catch(function () {});
        return;
      }
      var when = ctx.currentTime + 0.05;
      a.sources = names.map(function (n) {
        var src = ctx.createBufferSource();
        src.buffer = a.buffers[n];
        src.connect(ctx.destination);
        var off = state.t;
        if (off < src.buffer.duration) src.start(when, off);
        return src;
      });
      a.running = true;
      a.c0 = when;
      state.clockT0 = state.t;
    }
    function stopAudio() {
      var a = state.audio;
      if (!a) return;
      (a.sources || []).forEach(function (s) { try { s.stop(); } catch (e) { /* ignore */ } });
      a.sources = [];
      if (a.running) { state.clockT0 = clockNow(); state.clockP0 = real.now(); }
      a.running = false;
    }

    // ---- controls
    function toggle(id, on) { $(id).setAttribute('aria-pressed', on ? 'true' : 'false'); }
    $('#st-play').onclick = function () { state.playing ? pause() : play(); };
    $('#st-back').onclick = function (e) { step(e.shiftKey ? -Math.round(state.fps) : -1); };
    $('#st-fwd').onclick = function (e) { step(e.shiftKey ? Math.round(state.fps) : 1); };
    $('#st-loop').onclick = function () { state.loop = !state.loop; toggle('#st-loop', state.loop); };
    $('#st-mute').onclick = function () {
      state.muted = !state.muted; toggle('#st-mute', state.muted);
      $('#st-mute').textContent = state.muted ? 'Muted' : 'Sound';
      if (state.playing) { stopAudio(); startAudio(); }
    };
    $('#st-safebtn').onclick = function () { state.safe = !state.safe; toggle('#st-safebtn', state.safe); layout(); };
    $('#st-fitbtn').onclick = function () { state.fit = !state.fit; toggle('#st-fitbtn', state.fit); layout(); };
    $('#st-rate').onchange = function () {
      var was = state.playing;
      if (was) { stopAudio(); state.clockT0 = clockNow(); state.clockP0 = real.now(); }
      state.rate = parseFloat(this.value) || 1;
      if (was) { state.clockT0 = state.t; state.clockP0 = real.now(); startAudio(); }
    };
    var track = $('#st-track');
    function scrubTo(e) {
      var r = track.getBoundingClientRect();
      var p = clamp((e.clientX - r.left) / r.width, 0, 1);
      go(p * state.duration);
      if (state.playing) { stopAudio(); state.clockT0 = state.t; state.clockP0 = real.now(); startAudio(); }
    }
    track.addEventListener('pointerdown', function (e) {
      track.setPointerCapture(e.pointerId);
      var wasPlaying = state.playing;
      if (wasPlaying) pause();
      scrubTo(e);
      function mv(ev) { scrubTo(ev); }
      function up() { track.removeEventListener('pointermove', mv); track.removeEventListener('pointerup', up); if (wasPlaying) play(); }
      track.addEventListener('pointermove', mv);
      track.addEventListener('pointerup', up);
    });
    function onKey(e) {
      if (e.target && /INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
      var k = e.code;
      if (k === 'Space') { state.playing ? pause() : play(); }
      else if (k === 'ArrowLeft') step(e.shiftKey ? -Math.round(state.fps) : -1);
      else if (k === 'ArrowRight') step(e.shiftKey ? Math.round(state.fps) : 1);
      else if (k === 'Home') { if (state.playing) pause(); go(0); }
      else if (k === 'End') { if (state.playing) pause(); go(state.duration - 1 / state.fps); }
      else if (k === 'KeyL') $('#st-loop').onclick();
      else if (k === 'KeyM') $('#st-mute').onclick();
      else if (k === 'KeyS') $('#st-safebtn').onclick();
      else if (k === 'KeyF') $('#st-fitbtn').onclick();
      else return;
      e.preventDefault();
    }
    W.addEventListener('keydown', onKey);
    frame.addEventListener('load', function () {
      try { frame.contentWindow.addEventListener('keydown', onKey); } catch (e) { /* ignore */ }
    });

    // ---- live reload (server-sent events from `showtime preview`)
    if (W.EventSource && P.events !== false) {
      try {
        var es = new EventSource('/_st/events');
        es.addEventListener('reload', function (ev) {
          var what = ''; try { what = JSON.parse(ev.data).file || ''; } catch (e) { /* ignore */ }
          if (/\.(wav|mp3|m4a|ogg|flac)$/i.test(what)) { if (state.audio) { state.audio.buffers = {}; prepareAudio(); } return; }
          var keep = state.t;
          if (state.playing) pause();
          if (state.audio) state.audio.buffers = {};
          load(keep);
        });
      } catch (e) { /* ignore */ }
    }
    layout();
    load(0);
    W.__stPlayer = { state: state, go: go, play: play, pause: pause };
  }
})();

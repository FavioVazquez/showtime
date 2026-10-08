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
  function nextFrame() { return new Promise(function (r) { real.raf(function () { r(); }); }); }

  // ------------------------------------------------------------------ pace
  // The waits below (page load, fonts, images, videos, ST.waitFor gates, per-seek fonts and video seeks) are
  // their fixed values on a normal machine. On a slow one (no GPU, a busy runner, a heavy page) the same page
  // needs longer, so each wait is scaled by the page's measured cost: the gaps between its frames while it
  // gets ready (a frame should come every ~17 ms; PACE.frameRef is 3 of them) and the time its first seeks
  // take (PACE.seekRef, a heavy frame without a GPU). factor = the larger ratio, at least 1 (never a wait
  // shorter than the fixed value), at most PACE.ceil. The host (stagehost.mjs) reads it with ST.pace() and
  // scales its own deadlines the same way; render.json and check's report record it.
  var PACE = { ceil: 5, frameRef: 50, seekRef: 250, samples: 8 };
  var paceOn = !(RENDER && RENDER.pace === false);
  var waitScale = RENDER && RENDER.waitScale > 0 ? +RENDER.waitScale : 1;   // tests only: shrinks every base wait
  var pace = { factor: 1, frameMs: null, seekMs: null, gaps: [], seeks: [] };
  function median(a) {
    var s = a.slice().sort(function (x, y) { return x - y; }), n = s.length;
    return n ? (n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2) : null;
  }
  function paceUpdate() {
    var f = 1;
    if (pace.gaps.length >= 3) {
      // the mean, not the median: a page busy in 200 ms pieces draws a frame after each piece and often another
      // right away, so half its gaps are short
      pace.frameMs = pace.gaps.reduce(function (x, y) { return x + y; }, 0) / pace.gaps.length;
      f = Math.max(f, pace.frameMs / PACE.frameRef);
    }
    if (pace.seeks.length) { pace.seekMs = median(pace.seeks); f = Math.max(f, pace.seekMs / PACE.seekRef); }
    pace.factor = paceOn ? Math.round(clamp(f, 1, PACE.ceil) * 100) / 100 : 1;
  }
  var sampling = false;
  /** While the page gets ready: keep the last few gaps between real frames. */
  function sampleFrames() {
    if (sampling) return;
    sampling = true;
    var last = null;
    (function tick() {
      if (!sampling) return;
      var now = real.now();
      if (last !== null) {
        pace.gaps.push(now - last);
        if (pace.gaps.length > PACE.samples) pace.gaps.shift();
        paceUpdate();
      }
      last = now;
      real.raf(tick);
    })();
  }
  function paceSeek(ms) {
    if (pace.seeks.length >= PACE.samples) return;   // the first few seeks
    pace.seeks.push(ms);
    paceUpdate();
  }
  function paceInfo() {
    return { factor: pace.factor, frame_ms: pace.frameMs === null ? null : Math.round(pace.frameMs),
      seek_ms: pace.seekMs === null ? null : Math.round(pace.seekMs), seeks: pace.seeks.length,
      ceiling: PACE.ceil, on: paceOn };
  }
  /**
   * Promise.race against a deadline of baseMs times the pace factor, read again while it waits: it grows when
   * the page turns out slower, and never shrinks (the slow stretch may be why this wait is long).
   */
  function pacedRace(p, baseMs, label) {
    var t0 = real.now(), timer, f = 1;
    return Promise.race([p, new Promise(function (_, rej) {
      (function tick() {
        f = Math.max(f, pace.factor);
        var lim = Math.round(baseMs * waitScale * f), left = lim - (real.now() - t0);
        if (left <= 0) return rej(new Error('timed out after ' + lim + ' ms' + (f > 1 ? ' (x' + f + ' for this page\'s pace)' : '') + ': ' + label));
        timer = real.setTimeout(tick, Math.min(left, 250));
      })();
    })]).then(function (v) { real.clearTimeout(timer); return v; }, function (e) { real.clearTimeout(timer); throw e; });
  }

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
      'img.st-emoji{height:1em;width:1em;margin:0 .05em;vertical-align:-.12em;display:inline-block}' +
      '[data-st-blurring]{visibility:hidden!important}';
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
        if (inBlurHost(m.target)) continue;   // the shutter copies (see blurFrame) come and go every frame
        if (m.type === 'attributes' && m.attributeName === 'data-st-blur') { blurDirty = true; continue; }
        if (m.type === 'childList' && !blurDirty) blurDirty = hasElement(m.addedNodes) || hasElement(m.removedNodes);
        if (m.type === 'childList' || (m.type === 'attributes' && m.attributeName !== 'data-active' && m.attributeName !== 'style')) clipsDirty = true;
      }
    });
    mo.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-start', 'data-dur', 'data-end', 'id', 'data-st-blur'] });
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
  function addHandler(name, fn, light) {
    if (typeof fn !== 'function') throw new TypeError('ST.' + (name ? 'adapter' : 'onSeek') + ' needs a function');
    handlers.push({ name: name || ('onSeek#' + (handlers.length + 1)), fn: fn, light: !!light });
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
    return pacedRace(seekOne(v, t), 15000, 'video seek ' + key).catch(function (e) { diag.videos[key] = e.message; });
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
          if (inBlurHost(r.target)) return;
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

  // ------------------------------------------------------------ shutter blur
  // Motion blur on chosen elements, for snap beats (a whip, a slam, a scale punch): `data-st-blur` on the
  // element ("shutter 180; samples 8; threshold 6; max 50%", all optional) or ST.blur(el, {...}). While
  // the element moves faster than `threshold` px a frame, the frame shows `samples` copies of it posed at
  // sub-frame times from t back to t - shutter (180 deg = half a frame), averaged in its place: every copy
  // adds its share (mix-blend-mode: plus-lighter) inside an isolated group, so the smear is the box filter
  // a camera shutter gives and an opaque element stays opaque where all the copies cover it. The copies are
  // averaged in a balanced tree of groups (pairs of halves), so 8-bit rounding adds at most a level or two
  // instead of one level per copy. `max` caps the smear (px, or % of the element's shorter side on screen)
  // by shortening the shutter for that frame. At rest, moving slowly, or on the frame it comes to rest, the
  // element draws itself, sharp.
  //
  // Nothing is captured twice: poses are computed. The element's own sources are set to each sample time
  // and read back: its CSS animations and Web Animations (and its descendants'), the showtime component
  // around it, the `pose(t)` function given to ST.blur, and the timelines handed to ST.anime / ST.gsap.
  // Motion that comes from an onSeek handler of the page or from an ancestor is not seen (check reports it:
  // blur_unsampled). The copies live in a <st-blur> made once right after the element (so selectors see
  // the same tree on every frame and in every worker) and are rebuilt from t on every frame they show.
  var BLUR_DEFAULTS = { shutter: 180, samples: 8, threshold: 6, max: '50%' };
  // the host and its groups take nothing from the page's rules (all: unset) but pass on what the element's parent
  // passes on (inherited properties: its font, colour, letter-spacing...), as the element itself inherits them
  var BLUR_BOX = 'all:unset!important;position:absolute!important;left:0!important;top:0!important;width:0!important;' +
    'height:0!important;margin:0!important;padding:0!important;border:0!important;overflow:visible!important;' +
    'pointer-events:none!important;visibility:inherit!important;';
  // never copied from the element to a copy: where it sits and how it composites are the copy's own
  var BLUR_SKIP = /^(position|inset|top|right|bottom|left|margin|float|clear|z-index|transition|animation|will-change|visibility|pointer-events|mix-blend-mode|isolation|opacity|transform$|translate$|rotate$|scale$|view-transition|anchor-|position-|content-visibility|(min|max)-(width|height|inline-size|block-size)$|-webkit-transition|-webkit-animation)/;
  var BLUR_POS = 'right:auto!important;bottom:auto!important;margin:0!important;float:none!important;z-index:auto!important;' +
    'min-width:0!important;min-height:0!important;max-width:none!important;max-height:none!important;' +
    'visibility:inherit!important;pointer-events:none!important;mix-blend-mode:plus-lighter!important;animation:none!important;' +
    'transition:none!important;will-change:auto!important;content-visibility:visible!important;view-transition-name:none!important;';
  var REPLACED = /^(IMG|VIDEO|CANVAS|IFRAME|EMBED|OBJECT|INPUT|SELECT|TEXTAREA|BUTTON|svg)$/i;
  var blurRecs = [];
  var blurMap = new WeakMap();   // element -> record
  var blurDirty = true;
  var blurCost = { frames: 0, ms: 0, copies: 0 };
  var blurIds = 0;

  function hasElement(list) {
    for (var i = 0; i < list.length; i++) if (list[i].nodeType === 1) return true;
    return false;
  }
  function inBlurHost(n) {
    for (var e = n && n.nodeType === 1 ? n : n && n.parentNode; e && e.nodeType === 1; e = e.parentNode) {
      if (e.localName === 'st-blur') return true;
    }
    return false;
  }
  function blurParse(s) {
    s = String(s == null ? '' : s).trim();
    var o = {};
    if (!s) return o;
    if (/^(off|none|false|no)$/i.test(s)) return { off: true };
    if (s.charAt(0) === '{') { try { return JSON.parse(s) || {}; } catch (e) { reportError('data-st-blur', e); return o; } }
    s.split(/[;,]/).forEach(function (part) {
      var m = /^\s*([a-z][\w-]*)\s*(?::|=|\s)\s*(\S.*?)\s*$/i.exec(part);
      if (m) o[m[1].toLowerCase()] = m[2];
    });
    return o;
  }
  function blurOptions(raw) {
    var o = {}, k;
    for (k in BLUR_DEFAULTS) o[k] = raw[k] != null && raw[k] !== '' ? raw[k] : BLUR_DEFAULTS[k];
    var sh = num(o.shutter), n = Math.round(num(o.samples)), th = num(o.threshold), mx = String(o.max).trim();
    o.shutter = sh > 0 ? Math.min(sh, 720) : BLUR_DEFAULTS.shutter;
    o.samples = n >= 2 ? Math.min(n, 32) : BLUR_DEFAULTS.samples;
    o.threshold = th >= 0 ? th : BLUR_DEFAULTS.threshold;
    o.maxFrac = 0; o.maxPx = Infinity;
    if (/%$/.test(mx) && num(mx) > 0) o.maxFrac = num(mx) / 100;
    else if (num(mx) > 0) o.maxPx = num(mx);
    else if (!/^(none|off|infinity)$/i.test(mx)) o.maxFrac = 0.5;
    o.off = !!raw.off;
    return o;
  }
  function blurRecord(el) {
    var rec = blurMap.get(el);
    if (!rec) {
      rec = { el: el, host: null, attr: null, js: null, pose: null, o: blurOptions({}), on: false, last: null };
      blurMap.set(el, rec);
      blurRecs.push(rec);
    }
    return rec;
  }
  function blurSettle(rec) {
    var raw = {}, k;
    if (rec.attr) for (k in rec.attr) raw[k] = rec.attr[k];
    if (rec.js) for (k in rec.js) if (rec.js[k] !== undefined && k !== 'pose') raw[k] = rec.js[k];
    rec.o = blurOptions(raw);
  }
  function blurDrop(rec) {
    blurOff(rec);
    if (rec.host && rec.host.parentNode) rec.host.parentNode.removeChild(rec.host);
    rec.host = null;
    blurMap.delete(rec.el);
  }
  function scanBlurs() {
    blurDirty = false;
    if (!document.documentElement) return;
    var els = document.querySelectorAll('[data-st-blur]'), seen = new Set();
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (inBlurHost(el) || el === document.body || el === document.documentElement) continue;
      seen.add(el);
      var rec = blurRecord(el);
      rec.attr = blurParse(el.getAttribute('data-st-blur'));
      blurSettle(rec);
    }
    blurRecs = blurRecs.filter(function (r) {
      if (r.attr && !seen.has(r.el)) { r.attr = null; blurSettle(r); }
      var keep = r.el.isConnected && !!(r.attr || r.js);
      if (!keep) blurDrop(r);
      return keep;
    });
    // the copies' home, made once right after each element: the same tree on every frame
    blurRecs.forEach(blurHostOf);
  }
  function blurHostOf(rec) {
    var el = rec.el, h = rec.host, p = el.parentNode;
    if (!h) {
      h = document.createElement('st-blur');
      h.setAttribute('data-st-blur-host', '');
      h.setAttribute('data-st-ignore', '');   // check's text audits look at the element, not at its copies
      h.setAttribute('aria-hidden', 'true');
      h.style.cssText = BLUR_BOX + 'display:none!important;';
      rec.host = h;
    }
    if (p && p.nodeType === 1 && el.nextSibling !== h) p.insertBefore(h, el.nextSibling);
    return h;
  }
  /** ST.blur(el | selector | list, {shutter, samples, threshold, max, pose}) -> off() */
  function blurApi(target, opts) {
    var els = typeof target === 'string' ? document.querySelectorAll(target) : target && target.nodeType === 1 ? [target] : target;
    var recs = [];
    opts = opts || {};
    var pose = typeof opts.pose === 'function' ? opts.pose : null;
    for (var i = 0; els && i < els.length; i++) {
      if (!els[i] || els[i].nodeType !== 1) continue;
      var rec = blurRecord(els[i]);
      rec.js = opts;
      if (pose) rec.pose = pose;
      blurSettle(rec);
      recs.push(rec);
    }
    if (!recs.length) reportError('ST.blur', new Error('no element matches ' + String(target)));
    // pose(t) is the element's motion: it runs on every seek, like an onSeek handler
    var offPose = pose ? addHandler('blur pose', function (t) { return pose(t); }) : null;
    blurDirty = true;
    return function off() {
      if (offPose) offPose();
      recs.forEach(function (r) { r.js = null; r.pose = null; blurSettle(r); });
      blurDirty = true;
    };
  }

  // ---- poses at any time: the element's own sources, set to tau and read back
  function blurSources(rec) {
    var el = rec.el, comp = null;
    for (var e = el; e && e.nodeType === 1; e = e.parentElement) {
      if (e.__stComponent && typeof e.__stComponent.update === 'function') { comp = e.__stComponent; break; }
    }
    var anims = [], bases = [];
    var list = el.getAnimations ? el.getAnimations({ subtree: true }) : [];
    for (var i = 0; i < list.length; i++) {
      var a = list[i], target = a.effect && a.effect.target;
      if (W.CSSTransition && a instanceof W.CSSTransition) continue;
      if (target && target.closest && target.closest('[data-st-free]')) continue;
      anims.push(a);
      bases.push(target ? baseTimeOf(target) : 0);
    }
    rec.comp = comp; rec.anims = anims; rec.bases = bases;
    rec.light = rec.pose ? [] : handlers.filter(function (h) { return h.light; });
  }
  function blurPose(rec, tau) {
    try {
      if (rec.comp) rec.comp.update(tau);
      if (rec.pose) rec.pose(tau);
      for (var i = 0; i < rec.light.length; i++) rec.light[i].fn(tau, Math.round(tau * cfg.fps));
    } catch (e) { reportError('shutter blur pose at t=' + tau.toFixed(4), e); }
    for (var j = 0; j < rec.anims.length; j++) {
      try { rec.anims[j].currentTime = Math.max(0, (tau - rec.bases[j]) * 1000); } catch (e2) { /* ignore */ }
    }
  }
  function lenPx(v, ref) { v = String(v || '0'); return /%$/.test(v) ? parseFloat(v) / 100 * ref : parseFloat(v) || 0; }
  /** The element's own transform (translate, rotate, scale, transform about transform-origin), as CSS composes it. */
  function blurMatrix(cs, w, h) {
    var o = String(cs.transformOrigin || '0 0').split(/\s+/);
    var ox = lenPx(o[0], w), oy = lenPx(o[1], h), oz = parseFloat(o[2]) || 0;
    var m = new DOMMatrix().translateSelf(ox, oy, oz);
    var tr = cs.translate;
    if (tr && tr !== 'none') {
      var p = tr.split(/\s+/);
      m.translateSelf(lenPx(p[0], w), p.length > 1 ? lenPx(p[1], h) : 0, p.length > 2 ? parseFloat(p[2]) || 0 : 0);
    }
    var ro = cs.rotate;
    if (ro && ro !== 'none') {
      var q = ro.trim().split(/\s+/), ang = q[q.length - 1];
      var fn = q.length === 1 ? 'rotate(' + ang + ')' : q.length === 2 ? 'rotate' + q[0].toUpperCase() + '(' + ang + ')' : 'rotate3d(' + q.slice(0, 3).join(',') + ',' + ang + ')';
      try { m.multiplySelf(new DOMMatrix(fn)); } catch (e) { /* ignore */ }
    }
    var sc = cs.scale;
    if (sc && sc !== 'none') {
      var s = sc.trim().split(/\s+/).map(function (x) { return /%$/.test(x) ? parseFloat(x) / 100 : parseFloat(x); });
      m.scaleSelf(s[0], s.length > 1 ? s[1] : s[0], s.length > 2 ? s[2] : 1);
    }
    if (cs.transform && cs.transform !== 'none') { try { m.multiplySelf(new DOMMatrix(cs.transform)); } catch (e) { /* ignore */ } }
    return m.translateSelf(-ox, -oy, -oz);
  }
  function blurCorners(m, w, h) {
    var pts = [0, 0, w, 0, 0, h, w, h], out = [];
    for (var i = 0; i < 8; i += 2) {
      var p = m.transformPoint(new DOMPoint(pts[i], pts[i + 1], 0, 1)), k = p.w ? 1 / p.w : 1;
      out.push(p.x * k, p.y * k);
    }
    return out;
  }
  function blurDist(a, b, sx, sy) {
    var d = 0;
    for (var i = 0; i < 8; i += 2) d = Math.max(d, Math.hypot((a[i] - b[i]) * sx, (a[i + 1] - b[i + 1]) * sy));
    return d;
  }
  function blurRead(rec, tau) {
    blurPose(rec, tau);
    var cs = getComputedStyle(rec.el);
    return blurCorners(blurMatrix(cs, rec.w, rec.h), rec.w, rec.h);
  }
  /** When the element appears (the latest start of the clips around it): samples never reach before it. */
  function blurT0(el) {
    if (clipsDirty) parseClips();
    var t0 = 0;
    for (var e = el; e && e.nodeType === 1; e = e.parentElement) {
      var c = clipMap.get(e);
      if (c && isFinite(c.start)) t0 = Math.max(t0, edgeTime(c.start));
    }
    return t0;
  }
  /**
   * Measure one element at t (the page is posed at t): size, scale on screen, and the shutter decision.
   * -> {on, v (px a frame), L (smear px), rest, S (shutter seconds), size} ; leaves the element posed at t.
   */
  function blurMeasure(rec, t) {
    var el = rec.el, o = rec.o, dt = 1 / cfg.fps;
    var st = { on: false, v: 0, L: 0, rest: false, S: o.shutter / 360 * dt, size: 0, why: '' };
    if (o.off) { st.why = 'off'; return st; }
    if (!el.isConnected || !el.getClientRects().length) { st.why = 'hidden'; return st; }
    var cs = getComputedStyle(el);
    if (cs.visibility !== 'visible') { st.why = 'hidden'; return st; }
    // a non-replaced inline box is never transformed (CSS), so it never moves
    if (cs.display === 'inline' && !REPLACED.test(el.tagName)) { st.why = 'inline'; return st; }
    rec.w = el.offsetWidth != null ? el.offsetWidth : parseFloat(cs.width) || 0;
    rec.h = el.offsetHeight != null ? el.offsetHeight : parseFloat(cs.height) || 0;
    if (!(rec.w > 0 && rec.h > 0)) { var bb = el.getBoundingClientRect(); rec.w = rec.w || bb.width; rec.h = rec.h || bb.height; }
    var m0 = blurMatrix(cs, rec.w, rec.h), c0 = blurCorners(m0, rec.w, rec.h);
    // the ancestors' scale (a camera zoom): screen box against the element's own transformed box
    var r = el.getBoundingClientRect(), xs = [c0[0], c0[2], c0[4], c0[6]], ys = [c0[1], c0[3], c0[5], c0[7]];
    // where it really is on screen at this frame (check compares it with what its sources say)
    if (!rec.seen) { rec.seen = {}; rec.seenN = 0; }
    var fk = Math.round(t * cfg.fps);
    if (rec.seen[fk] || rec.seenN < 4000) { if (!rec.seen[fk]) rec.seenN++; rec.seen[fk] = [r.left, r.top, r.right, r.bottom, el.offsetWidth, el.offsetHeight]; }
    var lw = Math.max.apply(null, xs) - Math.min.apply(null, xs), lh = Math.max.apply(null, ys) - Math.min.apply(null, ys);
    rec.sx = lw > 0.5 && r.width > 0 ? r.width / lw : 1;
    rec.sy = lh > 0.5 && r.height > 0 ? r.height / lh : 1;
    var a2 = Math.abs(m0.a * m0.d - m0.b * m0.c);
    st.size = Math.min(rec.w, rec.h) * Math.sqrt(a2 || 1) * Math.min(rec.sx, rec.sy);
    blurSources(rec);
    if (!rec.anims.length && !rec.comp && !rec.pose && !rec.light.length) { st.why = 'still'; return st; }
    rec.t0 = blurT0(el);
    var cS = blurRead(rec, Math.max(rec.t0, t - st.S));
    st.L = blurDist(c0, cS, rec.sx, rec.sy);
    st.v = st.L * 360 / o.shutter;
    if (st.v >= o.threshold && st.L >= 0.5) {
      // the frame it comes to rest on is drawn sharp: nothing moves from t to the next frame
      st.rest = blurDist(c0, blurRead(rec, t + dt), rec.sx, rec.sy) < 0.25;
      st.on = !st.rest;
      if (st.rest) st.why = 'rest';
    } else st.why = 'slow';
    rec.c0 = c0;
    blurPose(rec, t);
    return st;
  }
  function blurOff(rec) {
    if (rec.el.hasAttribute('data-st-blurring')) rec.el.removeAttribute('data-st-blurring');
    var h = rec.host;
    if (h && (h.firstChild || h.style.getPropertyValue('display') !== 'none')) {
      while (h.firstChild) h.removeChild(h.firstChild);
      h.style.cssText = BLUR_BOX + 'display:none!important;';
    }
    rec.on = false;
  }
  function blurDecl(map) {
    var s = '';
    for (var k in map) s += k + ':' + map[k] + '!important;';
    return s;
  }
  // ancestors that clip the element (overflow) but not its copies: the host is positioned, so its containing
  // block is above any static ancestor (a mask reveal's overflow: hidden line). Their box clips the host.
  function isContainingBlock(cs) {
    return cs.position !== 'static' || cs.transform !== 'none' || (cs.translate && cs.translate !== 'none') ||
      (cs.rotate && cs.rotate !== 'none') || (cs.scale && cs.scale !== 'none') || cs.perspective !== 'none' ||
      cs.filter !== 'none' || (cs.backdropFilter && cs.backdropFilter !== 'none') || /paint|layout|strict|content/.test(cs.contain || '') ||
      /transform|perspective|filter/.test(cs.willChange || '');
  }
  function blurClip(rec) {
    var box = null;
    for (var a = rec.el.parentElement; a && a !== document.body && a !== document.documentElement; a = a.parentElement) {
      var cs = getComputedStyle(a);
      if (isContainingBlock(cs)) break;
      if (cs.overflowX === 'visible' && cs.overflowY === 'visible') continue;
      var r = a.getBoundingClientRect();
      var b = { x: r.left + parseFloat(cs.borderLeftWidth) * rec.sx, y: r.top + parseFloat(cs.borderTopWidth) * rec.sy,
        r: r.right - parseFloat(cs.borderRightWidth) * rec.sx, b: r.bottom - parseFloat(cs.borderBottomWidth) * rec.sy };
      box = box ? { x: Math.max(box.x, b.x), y: Math.max(box.y, b.y), r: Math.min(box.r, b.r), b: Math.min(box.b, b.b) } : b;
    }
    if (!box) return '';
    var hr = rec.host.getBoundingClientRect();
    var X = function (x) { return ((x - hr.left) / rec.sx).toFixed(3) + 'px'; }, Y = function (y) { return ((y - hr.top) / rec.sy).toFixed(3) + 'px'; };
    return 'clip-path:polygon(' + X(box.x) + ' ' + Y(box.y) + ',' + X(box.r) + ' ' + Y(box.y) + ',' + X(box.r) + ' ' + Y(box.b) + ',' + X(box.x) + ' ' + Y(box.b) + ')!important;';
  }
  /** The copy of the element at one sample time: a clone (inline styles at tau) and the values to pin on it. */
  function blurSample(rec, tau, desc) {
    blurPose(rec, tau);
    var el = rec.el, cs = getComputedStyle(el), own = {}, k, i;
    own.transform = cs.transform; own.translate = cs.translate; own.rotate = cs.rotate; own.scale = cs.scale;
    // what the element's own animations and its inline style (a component, a pose function) set at tau
    for (i = 0; i < el.style.length; i++) { k = el.style[i]; if (!BLUR_SKIP.test(k) && k.indexOf('--') !== 0) own[k] = cs.getPropertyValue(k); }
    var sub = [];
    for (i = 0; i < rec.anims.length; i++) {
      var a = rec.anims[i], target = a.effect && a.effect.target, pseudo = a.effect && a.effect.pseudoElement;
      var props = rec.props[i];
      if (!target || pseudo) continue;
      if (target === el) { for (k = 0; k < props.length; k++) if (!BLUR_SKIP.test(props[k])) own[props[k]] = cs.getPropertyValue(props[k]); continue; }
      var idx = desc.get(target);
      if (idx === undefined) continue;
      var tcs = getComputedStyle(target), vals = {};
      for (k = 0; k < props.length; k++) vals[props[k]] = tcs.getPropertyValue(props[k]);
      vals.animation = 'none';
      sub.push([idx, vals]);
    }
    var c = blurCorners(blurMatrix(cs, rec.w, rec.h), rec.w, rec.h);
    return { tau: tau, op: parseFloat(cs.opacity), own: own, sub: sub, c: c, clone: el.cloneNode(true) };
  }
  function keyProps(a) {
    var out = [];
    try {
      (a.effect.getKeyframes() || []).forEach(function (kf) {
        for (var k in kf) {
          if (k === 'offset' || k === 'computedOffset' || k === 'easing' || k === 'composite') continue;
          var p = k === 'cssFloat' ? 'float' : k.replace(/[A-Z]/g, function (c) { return '-' + c.toLowerCase(); });
          if (out.indexOf(p) < 0) out.push(p);
        }
      });
    } catch (e) { /* ignore */ }
    return out;
  }
  /** Clones are inert copies: no clip timing, no component mount, no nested blur; canvases keep their picture. */
  function blurCleanClone(clone, el) {
    var orig = [el].concat(Array.prototype.slice.call(el.querySelectorAll('*')));
    var copy = [clone].concat(Array.prototype.slice.call(clone.querySelectorAll('*')));
    for (var i = 0; i < copy.length && i < orig.length; i++) {
      var c = copy[i], o = orig[i];
      if (c.hasAttribute('data-start')) {
        if (!o.hasAttribute('data-active')) c.style.setProperty(o.hasAttribute('data-keep') ? 'visibility' : 'display', o.hasAttribute('data-keep') ? 'hidden' : 'none', 'important');
        c.removeAttribute('data-start'); c.removeAttribute('data-dur'); c.removeAttribute('data-end');
      }
      if (c.hasAttribute('data-st')) c.removeAttribute('data-st');
      if (c.hasAttribute('data-st-blur')) c.removeAttribute('data-st-blur');
      if (c.hasAttribute('data-st-blurring')) c.removeAttribute('data-st-blurring');
      var tag = c.localName;
      if (tag === 'canvas' && o.width && o.height) {
        try { c.width = o.width; c.height = o.height; var g = c.getContext('2d'); if (g) g.drawImage(o, 0, 0); } catch (e) { /* tainted or lost */ }
      } else if (tag === 'img') {
        c.setAttribute('decoding', 'sync'); c.removeAttribute('loading');
      } else if (tag === 'video') {
        c.removeAttribute('src'); while (c.firstChild) c.removeChild(c.firstChild); c.style.setProperty('visibility', 'hidden', 'important');
      }
    }
    return copy;
  }
  function blurGroupCss(w) {
    return BLUR_BOX + 'display:block!important;isolation:isolate!important;mix-blend-mode:plus-lighter!important;opacity:' + w + '!important;';
  }
  /** Draw the average of the copies under parent, weighted w within it: halves in groups, down to pairs. */
  function blurAverage(parent, items, w) {
    if (items.length === 1) {
      var it = items[0];
      it.node.style.setProperty('opacity', String(+(w * it.op).toFixed(6)), 'important');
      parent.appendChild(it.node);
      return;
    }
    var g = parent;
    if (w !== 1 || parent === null) {
      g = document.createElement('st-blur');
      g.style.cssText = blurGroupCss(+w.toFixed(6));
      parent.appendChild(g);
    }
    var half = Math.ceil(items.length / 2);
    blurAverage(g, items.slice(0, half), half / items.length);
    blurAverage(g, items.slice(half), (items.length - half) / items.length);
  }
  // The copies sit in another parent, so a selector like `.line > span` may no longer reach them: what the page's
  // rules give a copy where it sits is compared with the element's computed style, and only what differs is pinned,
  // by one rule per element ([data-st-copy="id"]) in a sheet of the stage's own (parsed once, not in every copy).
  // A colour that follows the text colour (currentcolor: -webkit-text-fill-color, caret-color...) is left to
  // follow it, so the copy's descendants still take their own colour.
  var blurSheet = null, blurSheetText = '';
  var BLUR_CURRENT = /^(-webkit-text-fill-color|-webkit-text-stroke-color|text-emphasis-color|caret-color|column-rule-color|outline-color|text-decoration-color|border-(top|right|bottom|left|block-start|block-end|inline-start|inline-end)-color)$/;
  // a descendant is compared on these first (what selectors usually set); only one that differs is compared in full
  var BLUR_KEY = ('color background-color background-image font-family font-size font-weight font-style line-height ' +
    'letter-spacing word-spacing text-transform text-align white-space display position top left width height ' +
    'padding-top padding-right padding-bottom padding-left margin-top margin-left border-top-width border-top-style ' +
    'border-top-color border-top-left-radius box-shadow text-shadow opacity filter transform visibility vertical-align ' +
    'clip-path -webkit-text-fill-color -webkit-text-stroke-width text-decoration-line fill stroke').split(' ');
  function blurDiff(pl) {
    var cs = getComputedStyle(pl.items[0].node), out = '', i, p, v;
    for (i = 0; i < pl.vals.length; i++) {
      p = pl.vals[i][0]; v = pl.vals[i][1];
      if (cs.getPropertyValue(p) === v) continue;
      if (BLUR_CURRENT.test(p) && v === pl.color) continue;
      out += p + ':' + v + '!important;';
    }
    pl.pin = out;
    // descendants: a rule anchored outside the element (`.scene > .card b`) no longer reaches the copy's own
    pl.subPins = [];
    var copy = pl.items[0].copy;
    if (pl.list.length > 60) return;   // a container (check warns blur_container): not worth the reads
    for (var d = 1; d < copy.length && d <= pl.list.length; d++) {
      var oc = getComputedStyle(pl.list[d - 1]), cc = getComputedStyle(copy[d]), differs = false;
      for (i = 0; i < BLUR_KEY.length && !differs; i++) differs = oc.getPropertyValue(BLUR_KEY[i]) !== cc.getPropertyValue(BLUR_KEY[i]);
      if (!differs) continue;
      var pins = '', col = oc.color;
      for (i = 0; i < oc.length; i++) {
        p = oc[i];
        if ((p.charCodeAt(0) === 45 && p.charCodeAt(1) === 45) || /^(animation|transition|will-change)/.test(p)) continue;
        v = oc.getPropertyValue(p);
        if (cc.getPropertyValue(p) === v || (BLUR_CURRENT.test(p) && v === col)) continue;
        pins += p + ':' + v + '!important;';
      }
      if (pins) pl.subPins.push([d, pins]);
    }
  }
  function blurRules(plans) {
    if (!blurSheet) {
      try { blurSheet = new CSSStyleSheet(); document.adoptedStyleSheets = document.adoptedStyleSheets.concat([blurSheet]); } catch (e) { blurSheet = false; }
    }
    // a descendant's pins go inline on that descendant of every copy (rare: only where a rule stopped matching)
    plans.forEach(function (pl) {
      (pl.subPins || []).forEach(function (sp) { pl.items.forEach(function (it) { var c = it.copy[sp[0]]; if (c) c.style.cssText += sp[1]; }); });
    });
    if (!blurSheet) {
      plans.forEach(function (pl) { if (pl.pin) pl.items.forEach(function (it) { it.node.style.cssText += pl.pin; }); });
      return;
    }
    var text = plans.filter(function (pl) { return pl.pin; }).map(function (pl) { return '[data-st-copy="' + pl.rec.id + '"]{' + pl.pin + '}'; }).join('\n');
    if (text !== blurSheetText) { blurSheet.replaceSync(text); blurSheetText = text; }
  }
  /** Everything a blurred frame of one element needs, read before any copy enters the page (reads stay cheap). */
  function blurPlan(rec, t, st) {
    var el = rec.el, o = rec.o, S = st.S, i;
    var maxLen = o.maxFrac > 0 ? o.maxFrac * st.size : o.maxPx;
    if (st.L > maxLen && maxLen > 0) S *= maxLen / st.L;
    var n = o.samples, desc = new Map(), list = el.querySelectorAll('*');
    for (i = 0; i < list.length; i++) desc.set(list[i], i + 1);   // index in [el, ...descendants]
    rec.props = rec.anims.map(keyProps);
    if (!rec.id) rec.id = ++blurIds;
    var samples = [];
    for (i = 0; i < n; i++) samples.push(blurSample(rec, Math.max(rec.t0, t - S * i / (n - 1)), desc));
    blurPose(rec, t);
    // a CSS transition started by a pose function's style changes would still be running at the capture
    el.getAnimations({ subtree: true }).forEach(function (a) { if (W.CSSTransition && a instanceof W.CSSTransition) a.finish(); });
    // the element's computed style at t, less what each copy pins for its own time (its animated and inline
    // properties): compared with each copy's own once the copies are in (blurDiff)
    var own = samples[0].own, cs = getComputedStyle(el), vals = [];
    for (i = 0; i < cs.length; i++) { var p = cs[i]; if ((p.charCodeAt(0) !== 45 || p.charCodeAt(1) !== 45) && !BLUR_SKIP.test(p) && !(p in own)) vals.push([p, cs.getPropertyValue(p)]); }
    var zi = cs.zIndex;
    // z-index places the element when it is positioned or a flex or grid item: the host takes the same layer
    var zOn = zi !== 'auto' && (cs.position !== 'static' || /flex|grid/.test(getComputedStyle(el.parentElement).display));
    return { rec: rec, t: t, S: S, n: n, maxLen: maxLen, list: list, samples: samples, vals: vals, color: cs.color, zi: zOn ? zi : null };
  }
  /** Put one element's copies in its host (no reads: every host fills before the one layout that places them). */
  function blurBuild(pl) {
    var rec = pl.rec, el = rec.el, h = blurHostOf(rec), samples = pl.samples;
    while (h.firstChild) h.removeChild(h.firstChild);
    h.style.cssText = BLUR_BOX + 'display:block!important;isolation:isolate!important;' + (pl.zi !== null ? 'z-index:' + pl.zi + '!important;' : '') + (pl.clip || '');
    var x0 = pl.x0, y0 = pl.y0;
    var items = samples.map(function (sm) {
      var copy = blurCleanClone(sm.clone, el), node = copy[0];
      for (var j = 0; j < sm.sub.length; j++) { var c = copy[sm.sub[j][0]]; if (c) c.style.cssText += blurDecl(sm.sub[j][1]); }
      node.setAttribute('data-st-copy', String(rec.id));
      node.style.cssText = (node.getAttribute('style') || '') + ';' + blurDecl(sm.own) + BLUR_POS +
        'position:absolute!important;left:' + x0 + 'px!important;top:' + y0 + 'px!important;';
      return { node: node, op: isFinite(sm.op) ? sm.op : 1, tau: sm.tau, copy: copy };
    });
    // 8 copies spread over a long smear leave steps: a gaussian along the motion, half a step wide, joins
    // them into one ramp (the copies' own edges across the motion stay sharp)
    var gx = 0, gy = 0, ux0 = Infinity, uy0 = Infinity, ux1 = -Infinity, uy1 = -Infinity;
    samples.forEach(function (sm, k) {
      for (var j = 0; j < 8; j += 2) {
        ux0 = Math.min(ux0, sm.c[j]); ux1 = Math.max(ux1, sm.c[j]); uy0 = Math.min(uy0, sm.c[j + 1]); uy1 = Math.max(uy1, sm.c[j + 1]);
        if (k) { gx = Math.max(gx, Math.abs(sm.c[j] - samples[k - 1].c[j])); gy = Math.max(gy, Math.abs(sm.c[j + 1] - samples[k - 1].c[j + 1])); }
      }
    });
    gx *= 0.5; gy *= 0.5;
    var tree = h;
    if (gx > 0.3 || gy > 0.3) {
      var fid = 'st-blur-f' + rec.id;
      var mx = 3 * gx + 0.2 * rec.w + 16, my = 3 * gy + 0.2 * rec.h + 16;
      var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('width', '0'); svg.setAttribute('height', '0');
      svg.style.cssText = 'position:absolute!important;width:0!important;height:0!important;overflow:hidden!important;';
      svg.innerHTML = '<filter id="' + fid + '" filterUnits="userSpaceOnUse" color-interpolation-filters="sRGB" x="' + (x0 + ux0 - mx).toFixed(1) +
        '" y="' + (y0 + uy0 - my).toFixed(1) + '" width="' + (ux1 - ux0 + 2 * mx).toFixed(1) + '" height="' + (uy1 - uy0 + 2 * my).toFixed(1) +
        '"><feGaussianBlur stdDeviation="' + gx.toFixed(2) + ' ' + gy.toFixed(2) + '"/></filter>';
      h.appendChild(svg);
      tree = document.createElement('st-blur');
      tree.style.cssText = BLUR_BOX + 'display:block!important;isolation:isolate!important;filter:url(#' + fid + ')!important;';
      h.appendChild(tree);
    }
    blurAverage(tree, items, 1);
    // pseudo-element animations in the copies come from the page's rules: seek them to their sample time
    items.forEach(function (it) {
      var anims = it.node.getAnimations ? it.node.getAnimations({ subtree: true }) : [];
      for (var j = 0; j < anims.length; j++) {
        var tg = anims[j].effect && anims[j].effect.target, ix = it.copy.indexOf(tg);
        var orig = ix === 0 ? el : ix > 0 ? pl.list[ix - 1] : null;
        try { anims[j].currentTime = Math.max(0, (it.tau - (orig ? baseTimeOf(orig) : baseTimeOf(el))) * 1000); } catch (e) { /* ignore */ }
      }
    });
    pl.items = items;
  }
  /** After the one layout: the newest copy is posed as the element is at t, so their boxes must agree (sub-pixel). */
  function blurPlace(pl) {
    var rec = pl.rec, el = rec.el, items = pl.items;
    var re = el.getBoundingClientRect(), rc = items[0].node.getBoundingClientRect();
    pl.dx = (re.left - rc.left) / rec.sx; pl.dy = (re.top - rc.top) / rec.sy;
  }
  function blurFix(pl) {
    var rec = pl.rec, el = rec.el;
    if (Math.abs(pl.dx) > 0.001 || Math.abs(pl.dy) > 0.001) {
      var L = (pl.x0 + pl.dx).toFixed(3) + 'px', T = (pl.y0 + pl.dy).toFixed(3) + 'px';
      pl.items.forEach(function (it) { it.node.style.setProperty('left', L, 'important'); it.node.style.setProperty('top', T, 'important'); });
    }
    if (!el.hasAttribute('data-st-blurring')) el.setAttribute('data-st-blurring', '');
    rec.on = true;
  }
  /** Before a seek's handlers run: last frame's copies go, so page code never meets them (blurFrame redraws them). */
  function blurClear() {
    for (var i = 0; i < blurRecs.length; i++) if (blurRecs[i].on) blurOff(blurRecs[i]);
  }
  /**
   * After every seek: the shutter copies of each moving [data-st-blur] element. In phases, so the page lays out
   * once: every element is measured and sampled while no copy is in the page, then every host is filled, then
   * one layout places them all.
   */
  function blurFrame(t) {
    if (blurDirty) scanBlurs();
    if (!blurRecs.length) return;
    var t1 = real.now(), plans = [], i, pl;
    for (i = 0; i < blurRecs.length; i++) {
      var rec = blurRecs[i];
      try {
        if (!rec.el.isConnected) { blurDirty = true; continue; }
        if (rec.el.hasAttribute('data-st-blurring')) rec.el.removeAttribute('data-st-blurring');
        if (rec.on || rec.host && rec.host.firstChild) blurOff(rec);
        var st = blurMeasure(rec, t);
        rec.last = { t: t, on: st.on, v: +st.v.toFixed(2), L: +st.L.toFixed(2), why: st.why, size: +st.size.toFixed(1) };
        if (!st.on) continue;
        pl = blurPlan(rec, t, st);
        var h = blurHostOf(rec);
        h.style.cssText = BLUR_BOX + 'display:block!important;';
        pl.clip = blurClip(rec);
        pl.x0 = rec.el.offsetLeft != null ? rec.el.offsetLeft - h.offsetLeft : 0;
        pl.y0 = rec.el.offsetTop != null ? rec.el.offsetTop - h.offsetTop : 0;
        plans.push(pl);
      } catch (e) { reportError('shutter blur ' + tagOf(rec.el), e); try { blurOff(rec); } catch (e2) { /* ignore */ } }
    }
    if (plans.length) {
      // last frame's pins come off first: each copy is compared with the element as the page's rules alone style it
      if (blurSheet && blurSheetText) { blurSheet.replaceSync(''); blurSheetText = ''; }
      var ok = plans.filter(function (p) {
        try { blurBuild(p); return true; } catch (e) { reportError('shutter blur ' + tagOf(p.rec.el), e); blurOff(p.rec); return false; }
      });
      ok.forEach(function (p) { try { blurDiff(p); } catch (e) { p.pin = ''; } });   // one style pass for every copy
      blurRules(ok);
      ok.forEach(function (p) { try { blurPlace(p); } catch (e) { p.dx = p.dy = 0; } });   // one layout
      ok.forEach(function (p) {
        blurFix(p);
        p.rec.last.S = +p.S.toFixed(5);
        blurCost.copies += p.n;
      });
    }
    blurCost.frames++;
    blurCost.ms += real.now() - t1;
  }
  /** The frames an element is on screen: the latest start and the earliest end of the clips around it. */
  function blurWindow(el) {
    if (clipsDirty) parseClips();
    var a = 0, b = Infinity;
    for (var e = el; e && e.nodeType === 1; e = e.parentElement) {
      var c = clipMap.get(e);
      if (!c || !isFinite(c.start)) continue;
      a = Math.max(a, edgeTime(c.start));
      if (isFinite(c.end)) b = Math.min(b, edgeTime(c.end));
    }
    return [a, b];
  }
  /**
   * For `showtime check` (window.__stBlur.scan()): each blurred element's motion on every frame it is on
   * screen, computed from its own sources as blurFrame sees them (no capture), plus a few real seeks that
   * catch motion those sources do not explain (an onSeek handler, a moving ancestor).
   */
  async function blurScan(opt) {
    opt = opt || {};
    if (blurDirty) scanBlurs();
    var fps = cfg.fps, total = Math.max(1, Math.round(cfg.duration * fps)), back = current, out = [];
    var maxFrames = opt.maxFrames || 900;
    for (var i = 0; i < blurRecs.length; i++) {
      var rec = blurRecs[i], el = rec.el, o = rec.o;
      var win = blurWindow(el);
      var f0 = Math.min(total - 1, Math.max(0, edgeFrame(win[0])));
      var f1 = isFinite(win[1]) && win[1] < cfg.duration - 1e-6 ? Math.min(total, edgeFrame(win[1])) : total;
      var text = String(el.textContent || '').replace(/\s+/g, ' ').trim();
      var item = {
        sel: tagOf(el), text: text.slice(0, 60), chars: text.length, nodes: el.querySelectorAll('*').length,
        clip: el.hasAttribute('data-start'), nested: !!el.querySelector('[data-start]'),
        media: /^(CANVAS|VIDEO|IFRAME)$/.test(el.tagName) || !!el.querySelector('canvas,video,iframe'),
        decor: !!(el.closest && el.closest('[data-st-decor]')), flash: !!(el.closest && el.closest('[data-st-flash]')),
        shutter: o.shutter, samples: o.samples, threshold: o.threshold, max: o.maxFrac ? Math.round(o.maxFrac * 100) + '%' : o.maxPx,
        off: o.off, pose: !!rec.pose, from: [f0 / fps, f1 / fps], frames: [], why: '',
      };
      out.push(item);
      if (o.off || f1 <= f0) { item.why = o.off ? 'off' : 'never on screen'; continue; }
      // the element on screen and the page posed at a frame inside its window
      var fm = f0, st = null;
      for (var tries = 0; tries < 3; tries++) {
        fm = tries === 0 ? f0 : tries === 1 ? Math.floor((f0 + f1) / 2) : f1 - 1;
        await seek(fm / fps);
        blurOff(rec);
        st = blurMeasure(rec, fm / fps);
        if (st.why !== 'hidden') break;
      }
      item.why = st.why === 'inline' || st.why === 'still' || st.why === 'hidden' ? st.why : '';
      item.w = rec.w; item.h = rec.h;
      if (!item.why) {
        var step = Math.max(1, Math.ceil((f1 - f0) / maxFrames)), dt = 1 / fps, S = o.shutter / 360 * dt, prev = null;
        item.step = step;
        for (var f = f0; f < f1; f += step) {
          var tau = f / fps;
          var c = blurRead(rec, tau), cS = blurRead(rec, Math.max(rec.t0, tau - S)), cN = blurRead(rec, tau + dt);
          var L = blurDist(c, cS, rec.sx, rec.sy), v = L * 360 / o.shutter;
          var on = v >= o.threshold && L >= 0.5 && !(blurDist(c, cN, rec.sx, rec.sy) < 0.25);
          var ex = Math.hypot((c[2] - c[0]) * rec.sx, (c[3] - c[1]) * rec.sy), ey = Math.hypot((c[4] - c[0]) * rec.sx, (c[5] - c[1]) * rec.sy);
          var area = Math.abs((c[2] - c[0]) * (c[5] - c[1]) - (c[3] - c[1]) * (c[4] - c[0])) * rec.sx * rec.sy;
          var maxLen = o.maxFrac > 0 ? o.maxFrac * Math.min(ex, ey) : o.maxPx;
          item.frames.push([+tau.toFixed(4), prev ? +(blurDist(c, prev, rec.sx, rec.sy) / step).toFixed(2) : 0, +Math.min(L, maxLen).toFixed(2),
            on ? 1 : 0, +Math.min(ex, ey).toFixed(1), +(area / (cfg.width * cfg.height)).toFixed(4)]);
          prev = c;
        }
        blurPose(rec, fm / fps);
      }
      // where it really was on screen at the frames the page was seeked to (check's samples and timeline, plus a
      // few here when those are sparse): a change between two of them that its sources do not explain is motion
      // the blur cannot pose (an onSeek handler of the page, a moving ancestor)
      var seenAt = function () { return Object.keys(rec.seen || {}).map(Number).filter(function (x) { return x >= f0 && x < f1; }); };
      if (seenAt().length < 8) {
        var P = Math.min(8, f1 - f0);
        for (var k = 0; k < P; k++) {
          var pf = P > 1 ? Math.round(f0 + (f1 - 1 - f0) * k / (P - 1)) : f0;
          if (!rec.seen || !rec.seen[pf]) await seek(pf / fps);
        }
      }
      var fs = seenAt().sort(function (x, y) { return x - y; }), probes = [];
      var moved = function (a, b) {   // both edges of an axis moved: the box went somewhere, it did not just change size
        return Math.max(Math.min(Math.abs(b[0] - a[0]), Math.abs(b[2] - a[2])), Math.min(Math.abs(b[1] - a[1]), Math.abs(b[3] - a[3])));
      };
      for (var q = 1; q < fs.length; q++) {
        var A = rec.seen[fs[q - 1]], B = rec.seen[fs[q]];
        if (A[4] !== B[4] || A[5] !== B[5]) continue;   // its layout changed (new text): not a move
        var predicted = 0;
        item.frames.forEach(function (x) { var ff = Math.round(x[0] * fps); if (ff > fs[q - 1] && ff <= fs[q]) predicted += x[1] * (item.step || 1); });
        probes.push({ from: +(fs[q - 1] / fps).toFixed(4), t: +(fs[q] / fps).toFixed(4), actual: +moved(A, B).toFixed(2), predicted: +predicted.toFixed(2) });
      }
      item.probes = probes;
    }
    await seek(back);
    blurClear();   // the tools that look next meet the page, not the copies
    return out;
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
      return pacedRace(loaded, 15000, 'image ' + img.currentSrc).then(function () {
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
      return pacedRace(new Promise(function (r) {
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
    fileCfgP = pacedRace(fetch('/showtime.json', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }), 5000, 'showtime.json')
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
      sampleFrames();          // the waits below grow with the gaps between this page's frames (pace)
      await pacedRace(docLoaded(), 30000, 'page load event').catch(function (e) { reportError('ready', e); });
      // 60 s like the author gates below: a look signature's faces on a cold, busy 4-core runner (Windows on Arm,
      // check's several pages at once) took over 20 s, which failed check while the render of the same page passed
      await pacedRace(preloadFonts(), 60000, 'fonts').catch(function (e) { reportError('ready', e); });
      emojify();
      await decodeImages();
      await videosLoaded();
      // author gates, including ones added while earlier gates resolved
      for (var n = 0; n < 5; n++) {
        var pending = readyWaits.filter(function (w) { return w.state === 'pending'; });
        if (!pending.length) break;
        await pacedRace(Promise.all(pending.map(function (w) { return w.p.catch(function () {}); })), 60000,
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
      sampling = false;
      await seek(opts.at || 0);
      return info();
    })();
    readyPromise.catch(function () {}).then(function () { sampling = false; });
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
    var t0 = real.now();
    current = t;
    clock.ms = t * 1000;
    clock.frame = f;
    reseed(f);
    diag.seeks++;
    blurClear();
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
    blurFrame(t);
    if (document.fonts && document.fonts.status === 'loading') await pacedRace(document.fonts.ready, 10000, 'fonts').catch(function () {});
    started = true;
    if (MODE === 'render') {
      await settle();
      paceSeek(real.now() - t0);
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
      hasScore: typeof ST.score === 'function', conflicts: cfgConflicts.slice(), pace: paceInfo(),
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
    addHandler(o.name || 'anime', function (t) { tl.seek(Math.max(0, t - off) * 1000, true); }, true);
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
    }, true);
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
    /** How much the waits are scaled for this page: {factor, frame_ms, seek_ms, seeks, ceiling, on}. */
    pace: paceInfo,
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
    /** Motion blur on an element while it moves fast (references/stage-api.md § Shutter blur). */
    blur: function (target, opts) { return blurApi(target, opts); },
    _setPlaying: function (v) { playingHint = !!v; },
    /** Wait for two real painted frames (tools use this after changing styles outside a seek). */
    _paint: function () { return nextFrame().then(nextFrame); },
  };
  Object.defineProperty(W, 'ST', { value: ST, configurable: false, writable: false, enumerable: true });
  // for tools (showtime check): the blurred elements, their last frame, and their motion over the video
  W.__stBlur = {
    items: function () { return blurRecs.map(function (r) { return { sel: tagOf(r.el), options: r.o, pose: !!r.pose, last: r.last }; }); },
    cost: function () { return Object.assign({}, blurCost); },
    scan: blurScan,
  };

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

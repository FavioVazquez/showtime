/* showtime adopt bridge (served at /_st/adopt.js).
 *
 * Loaded right after /_st/stage.js by the index.html that `showtime adopt` writes around a page
 * someone else wrote (a model, a person) as a pure function of time: `window.seek(t)`, `__seek(t)`,
 * `render(t)`, a canvas `draw(t)`, `setTime(t)` ... The page itself is not changed. The bridge
 * reads its settings from `window.__ST_ADOPT__` and
 *
 *   - waits for the page's own readiness signal (a `ready` promise, a flag, or a setup script),
 *   - registers one stage adapter that calls the page's time function on every seek, in seconds,
 *     milliseconds or frames, and waits for it when it returns a real Promise,
 *   - with no time function ("clock" pages: CSS animations, Web Animations, requestAnimationFrame
 *     loops) it adds nothing: the stage's virtual clock drives those.
 *
 * Settings (all optional except `seek` for a time-function page):
 *   seek:  "seek" | "__seek" | "render" | "app.seekTo" ...   global name or dotted path
 *   unit:  "s" (default) | "ms" | "frame"
 *   ready: global name of a promise, a function returning one, or a flag that becomes true
 *   setup: project-relative URL of a script run once before the first frame (its body may use await)
 *   probe: true -> only report what the page defines (used by `showtime adopt` while detecting)
 */
(function () {
  'use strict';
  var W = window;
  var A = W.__ST_ADOPT__ || {};
  var ST = W.ST;
  if (!ST || W.__stAdoptBridge) return;
  W.__stAdoptBridge = true;
  var NAME = /^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*$/;

  // A global by name, including top-level `const`/`let`/`function` of classic scripts (not on window).
  function lookup(name) {
    if (!name || !NAME.test(name)) return undefined;
    var parts = name.split('.');
    var v;
    try {
      v = (0, eval)('typeof ' + parts[0] + ' !== "undefined" ? ' + parts[0] + ' : undefined');
    } catch (e) { return undefined; }
    for (var i = 1; i < parts.length && v != null; i++) v = v[parts[i]];
    return v;
  }
  function owner(name) {
    var parts = String(name || '').split('.');
    if (parts.length < 2) return W;
    return lookup(parts.slice(0, -1).join('.')) || W;
  }
  function loaded() {
    if (document.readyState === 'complete') return Promise.resolve();
    return new Promise(function (r) { W.addEventListener('load', function () { r(); }, { once: true }); });
  }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  async function waitReady() {
    if (!A.ready) return;
    var v = lookup(A.ready);
    if (typeof v === 'function' && A.readyCall) v = v();
    if (v && typeof v.then === 'function') { await Promise.resolve(v); return; }
    if (v === false || v === 0 || v == null) {
      // a flag the page sets when it is done (window.ready = true): poll it, like the page's own driver did
      for (var i = 0; i < 300; i++) {
        await sleep(50);
        var x = lookup(A.ready);
        if (x && typeof x.then === 'function') { await Promise.resolve(x); return; }
        if (x) return;
      }
      throw new Error('the page never set `' + A.ready + '` (waited 15 s)');
    }
  }

  async function runSetup() {
    if (!A.setup) return;
    var r = await fetch(A.setup, { cache: 'no-store' });
    if (!r.ok) throw new Error('adopt setup script ' + A.setup + ': HTTP ' + r.status);
    var src = await r.text();
    var AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
    await new AsyncFunction(src + '\n//# sourceURL=' + A.setup)();
  }

  // read when adopt asks, after the stage is ready: its first seek has run, so a page that builds itself on
  // its first animation frame (a Claude Design component mounts there) is already on the page
  if (A.probe) {
    W.__stAdoptProbe = function () { return describe(); };
  }

  ST.waitFor(loaded().then(waitReady).then(runSetup), 'adopted page (' + (A.seek || 'clock') + ')');

  if (A.seek && !A.probe) {
    var warned = false;
    ST.adapter('adopt:' + A.seek, function (t, frame) {
      var fn = lookup(A.seek);
      if (typeof fn !== 'function') {
        if (warned) return;
        warned = true;
        throw new Error('the adopted page has no function `' + A.seek + '` (it was there when `showtime adopt` ran)');
      }
      var x = A.unit === 'ms' ? t * 1000 : A.unit === 'frame' ? frame : t;
      var r = fn.call(owner(A.seek), x);
      // only a real Promise is awaited: timeline objects are thenables that settle when playback ends
      return r instanceof Promise ? r : undefined;
    });
  }

  // What the page defines, for detection (`showtime adopt` reads it through __stAdoptProbe()).
  function describe() {
    var FN = ['seek', '__seek', 'seekTo', 'render', 'renderAt', 'renderFrame', 'draw', 'drawFrame', 'drawAt', 'setTime',
      'setFrame', 'goto', 'gotoTime', 'frame', 'update', 'tick', 'paint', '__render', '__draw', '__setTime'];
    var OBJ = ['app', 'video', 'scene', 'player', 'timeline', 'anim', 'animation', 'film', 'movie', 'comp', 'composition', 'VIDEO', 'APP'];
    var DUR = ['DURATION', 'duration', 'TOTAL', 'TOTAL_DURATION', 'totalDuration', 'LENGTH', 'VIDEO_DURATION', '__duration',
      'DUR', 'END', 'T_END', 'TOTAL_TIME', 'totalTime'];
    var FPSN = ['FPS', 'fps', '__fps', 'FRAME_RATE', 'frameRate'];
    var WN = ['WIDTH', 'W', 'VIDEO_WIDTH', '__width'], HN = ['HEIGHT', 'H', 'VIDEO_HEIGHT', '__height'];
    var READY = ['ready', '__ready', 'isReady', 'READY', 'fontsReady', 'loaded', '__loaded'];
    var out = { functions: [], numbers: {}, ready: [], setters: [], canvases: [], doc: null, animations: 0, timing: [], timers: 0 };
    FN.forEach(function (n) {
      var f = lookup(n);
      if (typeof f === 'function') out.functions.push({ name: n, arity: f.length, src: String(f).slice(0, 160) });
    });
    OBJ.forEach(function (o) {
      var obj = lookup(o);
      if (!obj || typeof obj !== 'object') return;
      ['seek', 'seekTo', 'render', 'draw', 'setTime', 'goto', 'renderAt'].forEach(function (m) {
        if (typeof obj[m] === 'function') out.functions.push({ name: o + '.' + m, arity: obj[m].length, src: String(obj[m]).slice(0, 160) });
      });
      ['duration', 'DURATION', 'length'].forEach(function (k) {
        if (typeof obj[k] === 'number' && isFinite(obj[k]) && !(o + '.' + k in out.numbers)) out.numbers[o + '.' + k] = obj[k];
      });
    });
    DUR.concat(FPSN, WN, HN).forEach(function (n) {
      var v = lookup(n);
      if (typeof v === 'number' && isFinite(v)) out.numbers[n] = v;
    });
    READY.forEach(function (n) {
      var v = lookup(n);
      if (v === undefined || v === null) return;
      out.ready.push({ name: n, type: v && typeof v.then === 'function' ? 'promise' : typeof v });
    });
    Object.keys(W).forEach(function (k) {
      var f;
      try { f = W[k]; } catch (e) { return; }
      if (/^(set|load|init|provide)[A-Z]\w*$/.test(k) && typeof f === 'function' && !/\[native code\]/.test(String(f))) {
        out.setters.push({ name: k, arity: f.length });
      }
    });
    var cs = document.querySelectorAll('canvas');
    for (var i = 0; i < cs.length && i < 8; i++) {
      var r = cs[i].getBoundingClientRect();
      out.canvases.push({ width: cs[i].width, height: cs[i].height, cssW: Math.round(r.width), cssH: Math.round(r.height), id: cs[i].id || '' });
    }
    var de = document.documentElement, b = document.body;
    var bs = b ? getComputedStyle(b) : null, hs = getComputedStyle(de);
    out.doc = {
      scrollW: Math.max(de.scrollWidth, b ? b.scrollWidth : 0), scrollH: Math.max(de.scrollHeight, b ? b.scrollHeight : 0),
      bodyW: bs ? bs.width : '', bodyH: bs ? bs.height : '', htmlW: hs.width, htmlH: hs.height,
      text: b ? (b.innerText || '').trim().length : 0,
    };
    try { out.animations = document.getAnimations ? document.getAnimations().length : 0; } catch (e) { /* ignore */ }
    // each animation's timing (ms; iterations null when it repeats forever): adopt finds a loop's period in it
    out.timing = [];
    try {
      var all = document.getAnimations ? document.getAnimations() : [];
      for (var k = 0; k < all.length && k < 300; k++) {
        var an = all[k], ef = an.effect;
        if (!ef || !ef.getComputedTiming) continue;
        if (W.CSSTransition && an instanceof W.CSSTransition) continue;
        var ct = ef.getComputedTiming();
        var tg = ef.target;
        out.timing.push({
          name: an.animationName || an.id || (tg && tg.tagName ? tg.tagName.toLowerCase() : 'animation'),
          delay: Number(ct.delay) || 0, duration: Number(ct.duration) || 0,
          iterations: isFinite(ct.iterations) ? ct.iterations : null, direction: ct.direction || 'normal',
        });
      }
    } catch (e) { /* ignore */ }
    try { var d = ST.diag(); out.timers = (d.timers && d.timers.length) || d.timerCalls || 0; } catch (e) { /* ignore */ }
    return out;
  }
})();

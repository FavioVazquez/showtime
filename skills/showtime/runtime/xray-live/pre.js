/* showtime X-ray live page, part 1 of 2 (runtime/xray-live/pre.js): runs before the stage runtime.
 *
 * `showtime export html <xray project> --interactive` packs the project's own page and puts this script right
 * before /_st/stage.js. It:
 *   1. keeps the real clocks (requestAnimationFrame, performance.now, Date) for the controls: the stage runs in
 *      render mode and replaces them with its virtual clock, so the drawing is the film's, frame for frame;
 *   2. hands the stage showtime.json (the look picked in the address, #hit4_light_split, applied first);
 *   3. answers the page's fetch() of its data files (xray.json, showtime.json, notes.json) from the packed copies:
 *      the file makes no network request;
 *   4. reports the film's size as the window's (the living-diagram runtime scales its stage by innerWidth / 1920;
 *      the controls (live.js) scale the whole film to the real window themselves).
 */
(function () {
  'use strict';
  var W = window, D = document;
  var el = D.getElementById('xl-cfg');
  if (!el) return;
  var C = JSON.parse(el.textContent), L = C.live, data = C.data;
  var real = {
    raf: W.requestAnimationFrame.bind(W), caf: W.cancelAnimationFrame.bind(W),
    now: W.performance && performance.now ? performance.now.bind(performance) : Date.now, Date: W.Date,
    dpr: W.devicePixelRatio || 1, look: {},
  };
  // A link to a moment, or a look picked on this page. Plain anchor tokens joined by "_" (hosts that frame the page,
  // like an artifact viewer, pass only a plain #anchor on): #hit4 (the 4th event, as the page counts them), #t2.5,
  // light | dark, through | split, embed (framed by <showtime-xray> or an iframe: fit the width, report the height).
  // The older #event=4&t=2.5&theme=light (event = an index into all events, skipped ones too) still opens.
  var look = real.look;
  try {
    var h = String(W.location.hash || '').replace(/^#/, '');
    try { h = decodeURIComponent(h); } catch (e) { /* keep */ }
    if (h.indexOf('=') >= 0) {
      h.split('&').forEach(function (kv) {
        var i = kv.indexOf('='); if (i < 0) { if (kv === 'embed') look.embed = true; return; }
        var k = kv.slice(0, i), v = kv.slice(i + 1);
        if (k === 't' && isFinite(parseFloat(v))) look.t = parseFloat(v);
        else if (k === 'event' && /^\d+$/.test(v)) look.event = +v;
        else if (k === 'hit' && /^\d+$/.test(v) && +v > 0) look.hit = +v;
        else if (k === 'theme' && /^(light|dark)$/.test(v)) look.theme = v;
        else if (k === 'layout' && /^(through|split)$/.test(v)) look.layout = v;
      });
    } else {
      h.split(/[_~]/).forEach(function (tk) {
        var m;
        if ((m = /^hit-?(\d+)$/.exec(tk)) && +m[1] > 0) look.hit = +m[1];
        else if ((m = /^t-?(\d+(?:\.\d+)?)$/.exec(tk))) look.t = parseFloat(m[1]);
        else if (tk === 'light' || tk === 'dark') look.theme = tk;
        else if (tk === 'through' || tk === 'split') look.layout = tk;
        else if (tk === 'embed') look.embed = true;
      });
    }
  } catch (e) { /* a host without an address */ }
  var cfg = JSON.parse(data['showtime.json']);
  cfg.xray = cfg.xray || {};
  if (look.theme) cfg.xray.theme = look.theme;
  if (look.layout && L.tracked) cfg.xray.layout = look.layout;
  data['showtime.json'] = JSON.stringify(cfg);
  real.cfg = cfg;
  W.__XL_REAL__ = real;
  W.__ST_RENDER__ = { config: cfg, override: null, alpha: false, settle: 'none', layers: false, seed: cfg.seed === undefined ? 1 : cfg.seed };
  ['innerWidth', 'innerHeight'].forEach(function (k, i) {
    try { Object.defineProperty(W, k, { configurable: true, get: function () { return i ? L.H : L.W; } }); } catch (e) { /* ignore */ }
  });
  try { Object.defineProperty(W, 'devicePixelRatio', { configurable: true, get: function () { return 1; } }); } catch (e) { /* ignore */ }
  function name(u) {
    var s = String(u && u.url ? u.url : u).split('#')[0].split('?')[0];
    try { s = decodeURIComponent(s); } catch (e) { /* keep */ }
    return s.replace(/^[a-z]+:\/\/[^/]*/i, '').replace(/^(\.?\/)+/, '');
  }
  W.fetch = function (u) {
    var n = name(u);
    if (Object.prototype.hasOwnProperty.call(data, n)) {
      return Promise.resolve(new Response(data[n], { status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    return Promise.resolve(new Response('', { status: 404, statusText: 'not packed in this page' }));
  };
})();

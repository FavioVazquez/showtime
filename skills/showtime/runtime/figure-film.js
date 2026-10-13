/* showtime living diagrams: what a live figure's steps write, and the film of a live scene (runtime/figure-film.js).
 *
 * Classic script, one global: `Figure` (runtime/figure.js adds the live page to it). Load after /_st/diagram.js.
 * A film page (the diagram template's index.html) loads only this file: Figure.film(SCENE) draws a live-first
 * scene's tour on the film's clock, so it uses no wall clock, no timer and no randomness (the same rules as
 * diagram.js). The live page's clock, timers and pointer live in figure.js.
 *
 * makeFx(api, clock, state, I) is the fx a step's run(fx, again) gets: level, count, say, hide, pulse, tone, show,
 * send, park, focus, every; each lands at the action's time plus its delay (references/workflows/diagram.md).
 */
(function (root) {
  'use strict';
  var Figure = root.Figure || {};

  /* ---------------- the actions a step writes: shared by the live page, the walk and the film ---------------- */
  // clock: {now(), reduced}; api: the Diagram.live api. Returns fx (handed to steps) and the bookkeeping.
  function makeFx(api, clock, state, I) {
    var loops = [];
    var fx = {
      state: state, reduced: !!clock.reduced, data: I.data || {}, tau: 0,
      at: function (o) { return fx.tau + (clock.reduced ? 0 : ((o && o.delay) || 0)); },
      level: function (id, v, o) { api.set(id, v, { at: fx.at(o), dur: clock.reduced ? 0.001 : (o && o.dur != null ? o.dur : 0.8) }); },
      count: function (id, n, o) { api.set(id, n, { at: fx.at(o) }); },
      say: function (tag, text, tone, o) { if (tone && typeof tone === 'object') { o = tone; tone = o.tone; } api.set(tag, text, { at: fx.at(o), tone: tone }); },
      hide: function (tag, o) { api.set(tag, null, { at: fx.at(o) }); },
      pulse: function (id, tone, o) { if (clock.reduced) return; api.fire(id, { at: fx.at(o), tone: tone || 'cold', dur: o && o.dur, amount: o && o.amount }); },
      send: function (token, moves, o) {
        o = o || {};
        if (clock.reduced) { // the end of the route, at once; a passing packet is not shown
          if (!o.stay) return;
          moves = moves.map(function (m) { return Object.assign({}, m, { at: 0, dur: 0.001 }); });
        }
        api.fire(token, { at: fx.at(o), moves: moves, stay: o.stay === true ? true : o.stay });
      },
      park: function (token, o) { api.fire(token, { at: fx.at(o), moves: [] }); },
      tone: function (id, tone, o) { api.tone(id, tone || null, { at: fx.at(o), dur: clock.reduced ? 0.001 : (o && o.dur) }); },
      show: function (id, on, o) { api.show(id, on !== false, { at: fx.at(o) }); },
      focus: function (id, o) { api.focus(id || null, { at: fx.at(o) }); },
      every: function (ms, fn, name) { clock.every(ms, fn, loops, name || ''); },
      stopLoops: function (name) {
        var stop = loops.filter(function (l) { return name == null || l.name === name; });
        clock.stop(stop); for (var i = loops.length - 1; i >= 0; i--) if (stop.indexOf(loops[i]) >= 0) loops.splice(i, 1);
      },
    };
    return fx;
  }
  function stepText(st, state) { return typeof st.text === 'function' ? st.text(state) : (st.text || ''); }
  function knobDefaults(I) { var s = {}; Object.keys(I.knobs || {}).forEach(function (k) { s[k] = I.knobs[k].default; }); return s; }
  function stepIndex(I, id) { for (var i = 0; i < I.steps.length; i++) if (I.steps[i].id === id) return i; return -1; }
  function partsOf(spec, I) {
    if (I.parts) return I.parts.slice();
    var seen = {}, out = [];
    (spec.labels || []).forEach(function (lb) { if (lb.for && !seen[lb.for]) { seen[lb.for] = 1; out.push({ id: lb.for, name: lb.title, sub: lb.sub || '' }); } });
    return out;
  }
  function normalise(spec) {
    var I = Object.assign({ steps: [], knobs: {}, tour: null }, spec.interactive || {});
    I.steps = I.steps || [];
    return I;
  }

  /* ---------------- the film of a live scene: its tour, drawn on the film's clock ---------------- */
  // index.html of a scene with interactive.film === 'tour': Figure.film(SCENE). The tour's actions are applied once,
  // at mount, at their times on the film's clock (an every() loop repeats until the next action), so every frame
  // is a pure function of t, like any film.
  function film(spec, opts) {
    opts = opts || {};
    var I = normalise(spec), state = knobDefaults(I), T = 0, loops = [], log = [];
    var SCRIPT = I.tour || I.steps.map(function (s) { return [{ step: s.id }, 7000]; });
    // the step lines of the film: one per step entered, and again when a knob changes the step's words
    var steps = [], cur = null, total = 0;
    SCRIPT.forEach(function (s) {
      var a = s[0];
      if (a && a.step != null) cur = I.steps[stepIndex(I, a.step)];
      if (a && a.knob) state[a.knob[0]] = a.knob[1];
      var txt = cur ? stepText(cur, state) : '', prev = steps[steps.length - 1];
      if (cur && (a.step != null || a.knob) && !(prev && prev.kicker === cur.kicker && prev.text === txt)) steps.push({ at: total + 0.05, kicker: cur.kicker, text: txt });
      total += s[1] / 1000;
    });
    state = knobDefaults(I);
    var filmSpec = Object.assign({}, spec, { steps: (spec.steps || []).concat(steps) });
    var clock = { reduced: false, now: function () { return T; }, manual: true,
      every: function (ms, fn, ls, name) { fn(); if (ms > 0) ls.push({ ms: ms, fn: fn, next: T + ms / 1000, name: name || '' }); }, stop: function () {} };
    var api = Diagram.live(filmSpec, Object.assign({}, opts, { live: { now: clock.now, seek: true } }));
    if (!api) return null;
    var fx = makeFx(api, clock, state, I);
    fx.every = function (ms, fn, name) { clock.every(ms, fn, loops, name); };
    fx.stopLoops = function (name) { for (var i = loops.length - 1; i >= 0; i--) if (name == null || loops[i].name === name) loops.splice(i, 1); };
    var runUntil = function (t) { // the loops' repeats before t
      loops.forEach(function (l) { while (l.next < t - 1e-9) { var keep = T; T = l.next; fx.tau = T; l.fn(); T = keep; l.next += l.ms / 1000; } });
    };
    var step = null, hover = null;
    SCRIPT.forEach(function (s) {
      var a = s[0];
      runUntil(T);
      fx.tau = T;
      if (typeof a === 'function') a(fx, state);
      else {
        if (a.knob) state[a.knob[0]] = a.knob[1];
        if (a.step != null) { step = I.steps[stepIndex(I, a.step)]; loops.length = 0; if (I.reset) I.reset(fx); if (step && step.run) step.run(fx, false); }
        else if (a.knob && step && step.knob === a.knob[0] && step.run) step.run(fx, true);
        if (a.hover !== undefined && a.hover !== hover) { hover = a.hover; api.focus(hover || null, { at: T }); }
      }
      log.push([T, a]);
      T += s[1] / 1000;
    });
    runUntil(T);
    api.filmLength = T;
    return api;
  }

  Figure.film = film;
  Figure.core = { makeFx: makeFx, stepText: stepText, knobDefaults: knobDefaults, stepIndex: stepIndex, partsOf: partsOf, normalise: normalise };
  Figure.version = '0.1.0';
  root.Figure = Figure;
})(typeof window !== 'undefined' ? window : this);

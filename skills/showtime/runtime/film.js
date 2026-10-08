/* showtime film toolkit: canvas films as pure functions of time.
 *
 * Classic script, one global: `Film`. Load after /_st/stage.js:
 *
 *   <script src="/_st/stage.js"></script>
 *   <script src="/_st/film.js"></script>
 *   <script>
 *     Film.start({
 *       look: 'dark',
 *       design: [1920, 1080],                 // author in these units; scaled to the project size
 *       scenes(T, g, F) {                     // draw the WHOLE frame for time T (seconds)
 *         F.text('Hello', F.W / 2, F.H / 2, { size: 120, weight: 800, align: 'center',
 *                                            alpha: F.seg(T, 0.2, 0.8) });
 *       },
 *     });
 *   </script>
 *
 * Rules: every frame is a pure function of T. No Math.random (use F.rng / F.hash),
 * no Date/performance clocks, no state carried between frames.
 * Full reference: references/film-api.md
 */
(function (root) {
  'use strict';

  var F = {};
  F.version = '1.0.0';

  // ------------------------------------------------------------------ state
  var S = {
    g: null, canvas: null, cfg: null, look: null,
    W: 1920, H: 1080,          // design size (what scenes draw in)
    cw: 1920, ch: 1080,        // output size in CSS px
    dpr: 1, s: 1, ox: 0, oy: 0, // design -> output transform
    T: 0, layers: null, started: false, warned: {},
  };

  function warnOnce(key, msg) {
    if (S.warned[key]) return;
    S.warned[key] = true;
    if (root.console) console.warn('[film] ' + msg);
  }

  // ================================================================== math
  function clamp(x, a, b) {
    if (a === undefined) { a = 0; b = 1; }
    return x < a ? a : x > b ? b : x;
  }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function invlerp(a, b, x) { return b === a ? 0 : (x - a) / (b - a); }
  function remap(x, a, b, c, d, doClamp) {
    var t = invlerp(a, b, x);
    if (doClamp !== false) t = clamp(t);
    return lerp(c, d, t);
  }
  function fract(x) { return x - Math.floor(x); }
  function mod(x, m) { return ((x % m) + m) % m; }
  function smoothstep(a, b, x) { var t = clamp(invlerp(a, b, x)); return t * t * (3 - 2 * t); }
  function smootherstep(a, b, x) { var t = clamp(invlerp(a, b, x)); return t * t * t * (t * (t * 6 - 15) + 10); }

  F.clamp = clamp; F.lerp = lerp; F.invlerp = invlerp; F.remap = remap;
  F.fract = fract; F.mod = mod; F.smoothstep = smoothstep; F.smootherstep = smootherstep;
  F.TAU = Math.PI * 2;
  F.deg = function (d) { return d * Math.PI / 180; };
  F.dist = function (x1, y1, x2, y2) { return Math.hypot(x2 - x1, y2 - y1); };
  /** Mix numbers, arrays of numbers, or colors. */
  F.mix = function (a, b, t) {
    if (typeof a === 'number') return lerp(a, b, t);
    if (typeof a === 'string') return mixColor(a, b, t);
    if (Array.isArray(a)) return a.map(function (v, i) { return F.mix(v, b[i], t); });
    if (a && typeof a === 'object') {
      var o = {};
      for (var k in a) o[k] = (k in b) ? F.mix(a[k], b[k], t) : a[k];
      return o;
    }
    return t < 0.5 ? a : b;
  };

  // ================================================================== easing
  function cubicBezier(x1, y1, x2, y2) {
    var cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
    var cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
    function sx(t) { return ((ax * t + bx) * t + cx) * t; }
    function sy(t) { return ((ay * t + by) * t + cy) * t; }
    function dx(t) { return (3 * ax * t + 2 * bx) * t + cx; }
    return function (p) {
      if (p <= 0) return 0;
      if (p >= 1) return 1;
      var t = p, i, x, d;
      for (i = 0; i < 8; i++) {
        x = sx(t) - p;
        if (Math.abs(x) < 1e-7) return sy(t);
        d = dx(t);
        if (Math.abs(d) < 1e-6) break;
        t -= x / d;
        if (t < 0 || t > 1) break;
      }
      var lo = 0, hi = 1;
      t = p;
      for (i = 0; i < 40; i++) {
        x = sx(t);
        if (Math.abs(x - p) < 1e-7) break;
        if (x < p) lo = t; else hi = t;
        t = (lo + hi) / 2;
      }
      return sy(t);
    };
  }

  /** Unit step response of a damped spring starting at rest (closed form, seek-safe). */
  function springRaw(t, w, z) {
    if (t <= 0) return 0;
    if (Math.abs(z - 1) < 1e-4) return 1 - Math.exp(-w * t) * (1 + w * t);
    if (z < 1) {
      var wd = w * Math.sqrt(1 - z * z);
      return 1 - Math.exp(-z * w * t) * (Math.cos(wd * t) + (z * w / wd) * Math.sin(wd * t));
    }
    var s = Math.sqrt(z * z - 1), r1 = -w * (z - s), r2 = -w * (z + s);
    return 1 + (r2 * Math.exp(r1 * t) - r1 * Math.exp(r2 * t)) / (r1 - r2);
  }
  var springCache = {};
  /**
   * Spring easing. response = seconds per undamped oscillation (0.3-0.7 typical),
   * damping = 1 no overshoot, 0.8 subtle, 0.6 playful. Returns ease(p) with .duration
   * (the natural settle time in seconds) so you can size the tween window.
   */
  function spring(response, damping) {
    response = response || 0.5;
    damping = damping === undefined ? 1 : damping;
    var key = response + '|' + damping;
    if (springCache[key]) return springCache[key];
    var w = 2 * Math.PI / response, z = Math.max(0.05, damping);
    var decay = z < 1 ? z * w : (Math.abs(z - 1) < 1e-4 ? w : w * (z - Math.sqrt(z * z - 1)));
    var span = 12 / decay, n = 4000, settle = span;
    for (var i = n; i >= 0; i--) {
      var t = span * i / n;
      if (Math.abs(1 - springRaw(t, w, z)) > 0.001) { settle = span * Math.min(n, i + 1) / n; break; }
    }
    var end = springRaw(settle, w, z);
    var f = function (p) {
      if (p <= 0) return 0;
      if (p >= 1) return 1;
      return springRaw(p * settle, w, z) + p * (1 - end);
    };
    f.duration = settle;
    springCache[key] = f;
    return f;
  }

  var E = {
    linear: function (t) { return t; },
    inSine: function (t) { return 1 - Math.cos(t * Math.PI / 2); },
    outSine: function (t) { return Math.sin(t * Math.PI / 2); },
    inOutSine: function (t) { return -(Math.cos(Math.PI * t) - 1) / 2; },
    inQuad: function (t) { return t * t; },
    outQuad: function (t) { return 1 - (1 - t) * (1 - t); },
    inOutQuad: function (t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; },
    inCubic: function (t) { return t * t * t; },
    outCubic: function (t) { return 1 - Math.pow(1 - t, 3); },
    inOutCubic: function (t) { return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; },
    inQuart: function (t) { return t * t * t * t; },
    outQuart: function (t) { return 1 - Math.pow(1 - t, 4); },
    inOutQuart: function (t) { return t < 0.5 ? 8 * t * t * t * t : 1 - Math.pow(-2 * t + 2, 4) / 2; },
    inExpo: function (t) { return t <= 0 ? 0 : Math.pow(2, 10 * t - 10); },
    outExpo: function (t) { return t >= 1 ? 1 : 1 - Math.pow(2, -10 * t); },
    inOutExpo: function (t) {
      return t <= 0 ? 0 : t >= 1 ? 1 : t < 0.5 ? Math.pow(2, 20 * t - 10) / 2 : (2 - Math.pow(2, -20 * t + 10)) / 2;
    },
    inCirc: function (t) { return 1 - Math.sqrt(1 - t * t); },
    outCirc: function (t) { return Math.sqrt(1 - Math.pow(t - 1, 2)); },
    inOutCirc: function (t) {
      return t < 0.5 ? (1 - Math.sqrt(1 - 4 * t * t)) / 2 : (Math.sqrt(1 - Math.pow(-2 * t + 2, 2)) + 1) / 2;
    },
    inBack: function (t, s) { s = s === undefined ? 1.70158 : s; return t * t * ((s + 1) * t - s); },
    outBack: function (t, s) { s = s === undefined ? 1.70158 : s; var u = t - 1; return 1 + u * u * ((s + 1) * u + s); },
    inOutBack: function (t, s) {
      s = (s === undefined ? 1.70158 : s) * 1.525;
      return t < 0.5 ? (Math.pow(2 * t, 2) * ((s + 1) * 2 * t - s)) / 2
        : (Math.pow(2 * t - 2, 2) * ((s + 1) * (t * 2 - 2) + s) + 2) / 2;
    },
    bezier: cubicBezier,
    spring: spring,
    steps: function (n) { return function (t) { return Math.min(1, Math.floor(t * n) / n); }; },
  };
  // House curves (enter = decelerate, exit = accelerate, move = standard, reveal = premium expo-like).
  E.enter = cubicBezier(0.05, 0.7, 0.1, 1.0);
  E.exit = cubicBezier(0.3, 0.0, 0.8, 0.15);
  E.move = cubicBezier(0.2, 0.0, 0.0, 1.0);
  E.reveal = cubicBezier(0.16, 1, 0.3, 1);
  E.camera = cubicBezier(0.65, 0, 0.35, 1);
  E.smooth = spring(0.5, 1);
  E.snappy = spring(0.4, 0.85);
  E.bouncy = spring(0.5, 0.65);
  F.E = E;

  /** Resolve an easing: function, name ('outExpo', 'reveal'), or [x1,y1,x2,y2] bezier. */
  function easeFn(e) {
    if (!e) return E.linear;
    if (typeof e === 'function') return e;
    if (Array.isArray(e)) return cubicBezier(e[0], e[1], e[2], e[3]);
    if (E[e] && e !== 'bezier' && e !== 'spring' && e !== 'steps') return E[e];
    warnOnce('ease:' + e, 'unknown easing "' + e + '", using linear');
    return E.linear;
  }
  F.ease = function (e, t) { return t === undefined ? easeFn(e) : easeFn(e)(clamp(t)); };
  F.spring = spring;
  F.bezier = cubicBezier;
  /** Value of a spring moving from `from` to `to`, released at t0 (time domain; may overshoot). */
  F.springTo = function (T, t0, from, to, o) {
    o = o || {};
    var w = 2 * Math.PI / (o.response || 0.5);
    return from + (to - from) * springRaw(T - t0, w, o.damping === undefined ? 1 : o.damping);
  };

  // ================================================================== timing
  /** Progress 0..1 of T through [a, b], eased. */
  F.seg = function (T, a, b, ease) {
    var p = b > a ? clamp((T - a) / (b - a)) : (T >= a ? 1 : 0);
    return ease ? easeFn(ease)(p) : p;
  };
  /** Visibility envelope: 0 before a, fades in over `fin`, holds, fades out over `fout` ending at b. */
  F.win = function (T, a, b, fin, fout, ease) {
    if (fin === undefined) fin = 0.3;
    if (fout === undefined) fout = fin;
    if (T < a || T > b) return 0;
    var e = easeFn(ease || 'inOutSine');
    var i = fin > 0 ? e(clamp((T - a) / fin)) : 1;
    var o = fout > 0 ? e(clamp((b - T) / fout)) : 1;
    return Math.min(i, o);
  };
  /**
   * Move a label from one place to another without dragging it across what lies between (a label
   * that must cross a line or another label): it dips out, moves, and comes back.
   * -> {x, y, alpha} for T; `from`/`to` are [x, y]; o.dip (default 0.85) is how far it fades mid-move.
   */
  F.relocate = function (T, t0, dur, from, to, o) {
    o = o || {};
    var p = F.seg(T, t0, t0 + dur, o.ease || 'inOutCubic');
    var q = clamp((T - t0) / Math.max(1e-6, dur));
    var dip = o.dip === undefined ? 0.85 : o.dip;
    return { x: lerp(from[0], to[0], p), y: lerp(from[1], to[1], p), alpha: 1 - dip * Math.sin(Math.PI * q) };
  };
  /** Interpolate from -> to over [t0, t0+dur]. */
  F.tween = function (T, t0, dur, from, to, ease) {
    return F.mix(from, to, F.seg(T, t0, t0 + dur, ease || 'outCubic'));
  };
  /**
   * Keyframes: [[t, value, ease?], ...] sorted by t. The ease on a key shapes the
   * segment that ARRIVES at it. Values: numbers, arrays, colors or flat objects.
   */
  F.kf = function (T, keys, ease) {
    if (!keys || !keys.length) return 0;
    if (T <= keys[0][0]) return keys[0][1];
    var last = keys[keys.length - 1];
    if (T >= last[0]) return last[1];
    for (var i = 1; i < keys.length; i++) {
      if (T <= keys[i][0]) {
        var a = keys[i - 1], b = keys[i];
        var p = (T - a[0]) / Math.max(1e-9, b[0] - a[0]);
        return F.mix(a[1], b[1], easeFn(b[2] || ease || 'inOutCubic')(p));
      }
    }
    return last[1];
  };
  /**
   * Staggered progress for item i of n. Items start `each` seconds apart (capped so the
   * whole group starts within `total` seconds) and each lasts `dur`.
   * order: 'start' | 'end' | 'center' | 'edges'.
   */
  F.stagger = function (T, i, n, t0, o) {
    o = o || {};
    var dur = o.dur === undefined ? 0.5 : o.dur;
    var total = o.total === undefined ? 0.5 : o.total;
    var each = o.each === undefined ? 0.06 : o.each;
    if (n > 1) each = Math.min(each, total / (n - 1));
    var k = i;
    if (o.order === 'end') k = n - 1 - i;
    else if (o.order === 'center') k = Math.abs(i - (n - 1) / 2);
    else if (o.order === 'edges') k = (n - 1) / 2 - Math.abs(i - (n - 1) / 2);
    return F.seg(T, t0 + k * each, t0 + k * each + dur, o.ease || 'outCubic');
  };
  /** Stagger inside a progress value: splits p (0..1) across n items. */
  F.split = function (p, i, n, overlap) {
    if (n <= 1) return clamp(p);
    var st = overlap === undefined ? Math.min(0.12, 0.6 / (n - 1)) : overlap;
    var d = Math.max(0.05, 1 - st * (n - 1));
    return clamp((p - i * st) / d);
  };

  /**
   * Named timeline. spec: {title: [0, 3], data: [3, 7.5]} or [['title', 3], ['data', 4.5]] (durations).
   * tl.p('data', T, ease), tl.local('data', T), tl.on('data', T), tl.at(T) -> name, tl.t0/t1/dur(name).
   */
  F.timeline = function (spec) {
    var list = [];
    if (Array.isArray(spec)) {
      var t = 0;
      spec.forEach(function (s) {
        var name = s[0], dur = s[1];
        list.push({ name: name, t0: t, t1: t + dur });
        t += dur;
      });
    } else {
      for (var k in spec) list.push({ name: k, t0: spec[k][0], t1: spec[k][1] });
    }
    list.sort(function (a, b) { return a.t0 - b.t0; });
    var by = {};
    list.forEach(function (s) { by[s.name] = s; });
    function get(n) {
      if (!by[n]) throw new Error('Film.timeline: unknown section "' + n + '"');
      return by[n];
    }
    return {
      list: list,
      t0: function (n) { return get(n).t0; },
      t1: function (n) { return get(n).t1; },
      dur: function (n) { var s = get(n); return s.t1 - s.t0; },
      p: function (n, T, ease) { var s = get(n); return F.seg(T, s.t0, s.t1, ease); },
      local: function (n, T) { return T - get(n).t0; },
      on: function (n, T) { var s = get(n); return T >= s.t0 && T < s.t1; },
      at: function (T) {
        for (var i = list.length - 1; i >= 0; i--) if (T >= list[i].t0) return list[i].name;
        return list.length ? list[0].name : null;
      },
      end: list.length ? list[list.length - 1].t1 : 0,
    };
  };

  /**
   * Musical grid for picture: F.beats({bpm: 96, offset: 0.25}).
   * .t(bar, beat=0, frac=0) time of a position (bars and beats are 0-based)
   * .beat(T) beats elapsed (float), .bar(T), .phase(T) 0..1 within the beat,
   * .pulse(T, decay=0.18) 1 on each beat decaying to 0, .snap(t) nearest beat time.
   */
  F.beats = function (o) {
    o = o || {};
    var bpm = o.bpm || 120, off = o.offset || 0, bpb = o.beatsPerBar || 4, spb = 60 / bpm;
    return {
      bpm: bpm, spb: spb, beatsPerBar: bpb, offset: off,
      t: function (bar, beat, frac) { return off + ((bar || 0) * bpb + (beat || 0) + (frac || 0)) * spb; },
      beat: function (T) { return (T - off) / spb; },
      bar: function (T) { return Math.floor((T - off) / (spb * bpb)); },
      phase: function (T) { return fract((T - off) / spb); },
      pulse: function (T, decay) {
        var b = (T - off) / spb;
        if (b < 0) return 0;
        return Math.exp(-fract(b) * spb / (decay || 0.18));
      },
      snap: function (t) { return off + Math.round((t - off) / spb) * spb; },
    };
  };

  // @part sequence: sequence transOf applyTransition
  /**
   * Scene sequencer with transitions centred on each cut.
   * scenes: [{t0, t1, draw(local, p, T), in: {type, dur, color, dir, blur}}]
   * types: 'cut' | 'fade' | 'dip' (through color) | 'wipe' | 'push' | 'zoom' | 'blur' | 'iris'
   * blur (any type): px at 1080p; the incoming scene pulls focus from that blur and the outgoing one
   * softens into it, so a big flat shape never reads as a hard-edged box over the other scene.
   */
  F.sequence = function (T, scenes, opts) {
    opts = opts || {};
    var g = S.g;
    for (var i = 0; i < scenes.length; i++) {
      var sc = scenes[i], nx = scenes[i + 1];
      var tin = transOf(sc.in, opts), tout = nx ? transOf(nx.in, opts) : null;
      // a dip goes through its colour: the outgoing scene is drawn only until the cut (the colour is
      // opaque there) and the incoming one only after it, so neither shows through the other
      var a = sc.t0 - (i > 0 && tin.type !== 'dip' ? tin.dur / 2 : 0);
      var b = sc.t1 + (tout && tout.type !== 'dip' ? tout.dur / 2 : 0);
      if (T < a || T >= b) continue;
      var local = T - sc.t0, p = clamp((T - sc.t0) / Math.max(1e-6, sc.t1 - sc.t0));
      g.save();
      // incoming half: this scene's own entry transition
      if (i > 0 && tin.dur > 0 && T < sc.t0 + tin.dur / 2) {
        applyTransition(tin, clamp((T - (sc.t0 - tin.dur / 2)) / tin.dur), true);
      }
      // outgoing half: the next scene's entry transition
      if (tout && tout.dur > 0 && T >= sc.t1 - tout.dur / 2) {
        applyTransition(tout, clamp((T - (sc.t1 - tout.dur / 2)) / tout.dur), false);
      }
      try { sc.draw(local, p, T); } finally { g.restore(); }
    }
    // dip overlays drawn above both
    for (var j = 1; j < scenes.length; j++) {
      var tr = transOf(scenes[j].in, opts);
      if (tr.type !== 'dip' || tr.dur <= 0) continue;
      var q = (T - (scenes[j].t0 - tr.dur / 2)) / tr.dur;
      if (q < 0 || q > 1) continue;
      g.save();
      g.globalAlpha = 1 - Math.abs(q * 2 - 1);
      g.fillStyle = tr.color || '#000';
      g.fillRect(-S.W, -S.H, S.W * 3, S.H * 3);
      g.restore();
    }
  };
  function transOf(t, opts) {
    if (!t) t = opts.transition || { type: 'cut' };
    if (typeof t === 'string') t = { type: t };
    var dur = t.dur === undefined ? ({ cut: 0, fade: 0.5, dip: 0.6, wipe: 0.6, push: 0.6, zoom: 0.6, blur: 0.5, iris: 0.8 }[t.type] || 0) : t.dur;
    return { type: t.type || 'cut', dur: dur, color: t.color, dir: t.dir || 'left', ease: t.ease, blur: Number(t.blur) || 0 };
  }
  function applyTransition(tr, q, incoming) {
    var g = S.g, W = S.W, H = S.H;
    var e = easeFn(tr.ease || 'inOutCubic')(q);
    if (tr.blur > 0) {
      var bpx = (incoming ? 1 - e : e) * tr.blur * S.s;
      if (bpx > 0.05) g.filter = (g.filter && g.filter !== 'none' ? g.filter + ' ' : '') + 'blur(' + bpx.toFixed(2) + 'px)';
    }
    switch (tr.type) {
      case 'fade':
        if (incoming) g.globalAlpha *= e;
        break;
      case 'dip':
        break;
      case 'blur':
        if (incoming) g.globalAlpha *= e;
        else g.filter = 'blur(' + (e * 16 * S.s).toFixed(2) + 'px)';
        break;
      case 'zoom':
        g.translate(W / 2, H / 2);
        if (incoming) { var si = lerp(0.94, 1, e); g.scale(si, si); g.globalAlpha *= e; }
        else { var so = lerp(1, 1.12, e); g.scale(so, so); g.globalAlpha *= 1 - e; }
        g.translate(-W / 2, -H / 2);
        break;
      case 'push': {
        var d = tr.dir, dx = d === 'left' ? -1 : d === 'right' ? 1 : 0, dy = d === 'up' ? -1 : d === 'down' ? 1 : 0;
        var off = incoming ? (1 - e) : -e;
        g.translate(-dx * off * W, -dy * off * H);
        break;
      }
      case 'wipe': {
        if (!incoming) break;
        g.beginPath();
        var d2 = tr.dir;
        if (d2 === 'right') g.rect(W * (1 - e), -H, W * 2, H * 3);
        else if (d2 === 'up') g.rect(-W, H * (1 - e), W * 3, H * 2);
        else if (d2 === 'down') g.rect(-W, -H, W * 3, H + H * e);
        else g.rect(-W, -H, W + W * e, H * 3);
        g.clip();
        break;
      }
      case 'iris': {
        if (!incoming) break;
        g.beginPath();
        g.arc(W / 2, H / 2, Math.hypot(W, H) / 2 * e, 0, Math.PI * 2);
        g.clip();
        break;
      }
      default:
        break;
    }
  }

  // @end sequence
  // ================================================================== rng / noise
  /** Integer hash -> [0, 1). Deterministic, fast. */
  function hash(n) {
    var x = (Math.floor(n) | 0) ^ 0x9e3779b9;
    x = Math.imul(x ^ (x >>> 16), 0x85ebca6b);
    x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35);
    x ^= x >>> 16;
    return (x >>> 0) / 4294967296;
  }
  function hash2(x, y) { return hash(Math.imul(Math.floor(x) | 0, 0x1f1f1f1f) ^ (Math.floor(y) * 0x5bd1e995)); }
  /** Seeded PRNG (mulberry32) with helpers. */
  function rng(seed) {
    var a = (typeof seed === 'string' ? strSeed(seed) : (seed || 1)) >>> 0;
    var next = function () {
      a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    next.float = function (lo, hi) { return lo + (hi - lo) * next(); };
    next.int = function (lo, hi) { return Math.floor(lo + (hi - lo + 1) * next()); };
    next.pick = function (arr) { return arr[Math.floor(next() * arr.length)]; };
    next.gauss = function () {
      var u = Math.max(1e-9, next()), v = next();
      return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
    };
    next.sign = function () { return next() < 0.5 ? -1 : 1; };
    return next;
  }
  function strSeed(s) {
    var h = 2166136261;
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }
  /** Smooth 1-D value noise in [-1, 1]. */
  function noise(x, seed) {
    seed = (seed || 0) * 7919;
    var i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f);
    return lerp(hash(i + seed), hash(i + 1 + seed), u) * 2 - 1;
  }
  /** Smooth 2-D value noise in [-1, 1]. */
  function noise2(x, y, seed) {
    seed = (seed || 0) * 131;
    var ix = Math.floor(x), iy = Math.floor(y), fx = x - ix, fy = y - iy;
    var ux = fx * fx * (3 - 2 * fx), uy = fy * fy * (3 - 2 * fy);
    var a = hash2(ix + seed, iy), b = hash2(ix + 1 + seed, iy);
    var c = hash2(ix + seed, iy + 1), d = hash2(ix + 1 + seed, iy + 1);
    return lerp(lerp(a, b, ux), lerp(c, d, ux), uy) * 2 - 1;
  }
  function fbm(x, y, octaves, seed) {
    var s = 0, amp = 0.5, fr = 1, norm = 0;
    for (var i = 0; i < (octaves || 4); i++) {
      s += amp * noise2(x * fr, y * fr, (seed || 0) + i * 17);
      norm += amp; amp *= 0.5; fr *= 2;
    }
    return s / norm;
  }
  F.hash = hash; F.hash2 = hash2; F.rng = rng; F.noise = noise; F.noise2 = noise2; F.fbm = fbm;

  // ================================================================== color
  var colorCache = {};
  function parseColor(c) {
    if (Array.isArray(c)) return c.length === 4 ? c : [c[0], c[1], c[2], 1];
    if (colorCache[c]) return colorCache[c];
    var r = 0, g = 0, b = 0, a = 1, m;
    var s = String(c).trim();
    if (s[0] === '#') {
      var h = s.slice(1);
      if (h.length === 3 || h.length === 4) h = h.split('').map(function (x) { return x + x; }).join('');
      r = parseInt(h.slice(0, 2), 16); g = parseInt(h.slice(2, 4), 16); b = parseInt(h.slice(4, 6), 16);
      if (h.length === 8) a = parseInt(h.slice(6, 8), 16) / 255;
    } else if ((m = s.match(/^rgba?\(([^)]+)\)$/i))) {
      var p = m[1].split(/[\s,/]+/).filter(Boolean).map(parseFloat);
      r = p[0]; g = p[1]; b = p[2]; a = p.length > 3 ? p[3] : 1;
    } else if (s === 'transparent') {
      a = 0;
    } else {
      warnOnce('color:' + s, 'color "' + s + '" not understood; use #hex or rgb()');
    }
    var out = [r, g, b, a];
    colorCache[c] = out;
    return out;
  }
  function css(rgb) {
    return 'rgba(' + Math.round(rgb[0]) + ',' + Math.round(rgb[1]) + ',' + Math.round(rgb[2]) + ',' +
      (+clamp(rgb[3]).toFixed(4)) + ')';
  }
  function mixColor(a, b, t) {
    var x = parseColor(a), y = parseColor(b);
    return css([lerp(x[0], y[0], t), lerp(x[1], y[1], t), lerp(x[2], y[2], t), lerp(x[3], y[3], t)]);
  }
  /** Color with alpha multiplied: F.rgba('#ff3366', 0.4). */
  F.rgba = function (c, a) { var x = parseColor(c); return css([x[0], x[1], x[2], x[3] * (a === undefined ? 1 : a)]); };
  F.mixColor = mixColor;
  F.parseColor = parseColor;
  F.lighten = function (c, amt) { return mixColor(c, '#ffffff', amt); };
  F.darken = function (c, amt) { return mixColor(c, '#000000', amt); };
  /** Relative luminance (WCAG) of a color, 0..1. */
  F.luminance = function (c) {
    var x = parseColor(c).slice(0, 3).map(function (v) {
      v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * x[0] + 0.7152 * x[1] + 0.0722 * x[2];
  };
  F.contrast = function (a, b) {
    var l1 = F.luminance(a), l2 = F.luminance(b);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  };

  // ================================================================== looks & palettes
  var PALETTES = {
    dark: { bg: '#0b0c10', bg2: '#15171e', ink: '#f4f5f7', muted: '#9aa1ad', faint: '#4a505c',
      accent: '#7c9cff', accent2: '#4fd1c5', accent3: '#ffb86b', good: '#4ade80', warn: '#fbbf24', bad: '#f87171',
      panel: '#161922', panel2: '#1e222d', line: 'rgba(255,255,255,0.10)', shadow: 'rgba(0,0,0,0.55)' },
    paper: { bg: '#f3eee4', bg2: '#e7dfcf', ink: '#1d1b18', muted: '#6d665c', faint: '#b9b0a0',
      accent: '#d9482b', accent2: '#2f6f73', accent3: '#c89b3c', good: '#2f8f4e', warn: '#c98a14', bad: '#c0392b',
      panel: '#fbf8f2', panel2: '#efe8da', line: 'rgba(29,27,24,0.14)', shadow: 'rgba(60,45,25,0.22)' },
    blueprint: { bg: '#0f2c4c', bg2: '#0b2240', ink: '#eaf2ff', muted: '#9db7d9', faint: '#4d6f98',
      accent: '#ffd166', accent2: '#7fdbff', accent3: '#ff8fa3', good: '#8ce99a', warn: '#ffd166', bad: '#ff8787',
      panel: '#133659', panel2: '#184068', line: 'rgba(200,225,255,0.22)', shadow: 'rgba(0,10,30,0.45)' },
    film: { bg: '#14110f', bg2: '#1f1a16', ink: '#f2e9dc', muted: '#a89a88', faint: '#5b5046',
      accent: '#e8a35a', accent2: '#c65d3b', accent3: '#8fb3a8', good: '#9cc98a', warn: '#e8a35a', bad: '#d8574a',
      panel: '#211c18', panel2: '#2b241f', line: 'rgba(242,233,220,0.12)', shadow: 'rgba(0,0,0,0.6)' },
    neon: { bg: '#07060d', bg2: '#110d22', ink: '#f5f3ff', muted: '#a59cc9', faint: '#463d6b',
      accent: '#ff3ea5', accent2: '#35e0ff', accent3: '#b388ff', good: '#3dffa2', warn: '#ffe14d', bad: '#ff4d6d',
      panel: '#120f24', panel2: '#1b1633', line: 'rgba(181,160,255,0.18)', shadow: 'rgba(0,0,0,0.6)' },
    clean: { bg: '#ffffff', bg2: '#f4f5f7', ink: '#111318', muted: '#5f6673', faint: '#c3c8d1',
      accent: '#3b5bfd', accent2: '#12b886', accent3: '#f59f00', good: '#12b886', warn: '#f59f00', bad: '#e03131',
      panel: '#ffffff', panel2: '#f1f3f5', line: 'rgba(17,19,24,0.10)', shadow: 'rgba(17,19,24,0.16)' },
  };
  var LOOKS = {
    dark: { palette: 'dark', backdrop: 'dark', grain: 0.04, vignette: 0.35, dust: 0, leak: 0, labels: false },
    paper: { palette: 'paper', backdrop: 'paper', grain: 0.07, vignette: 0.22, dust: 0.25, leak: 0, labels: false },
    blueprint: { palette: 'blueprint', backdrop: 'blueprint', grain: 0.05, vignette: 0.35, dust: 0.1, leak: 0, labels: false },
    film: { palette: 'film', backdrop: 'film', grain: 0.07, grainFps: 12, grainSize: 1.5, vignette: 0.5, dust: 0.45, leak: 0.35, weave: 0.6, labels: false },
    neon: { palette: 'neon', backdrop: 'neon', grain: 0.05, vignette: 0.45, dust: 0, leak: 0, labels: false },
    clean: { palette: 'clean', backdrop: 'flat', grain: 0, vignette: 0, dust: 0, leak: 0, labels: false },
  };
  F.PALETTES = PALETTES;
  F.LOOKS = LOOKS;

  function resolveLook(look) {
    var base, over = {};
    if (!look) look = 'dark';
    if (typeof look === 'string') base = LOOKS[look] || (warnOnce('look:' + look, 'unknown look "' + look + '", using dark'), LOOKS.dark);
    else if (typeof look === 'function') { base = LOOKS.dark; over = { backdrop: look, grain: 0, vignette: 0 }; }
    else { base = LOOKS[look.base || 'dark'] || LOOKS.dark; over = look; }
    var out = {};
    for (var k in base) out[k] = base[k];
    for (var k2 in over) if (k2 !== 'base') out[k2] = over[k2];
    return out;
  }

  // ------------------------------------------------------------------ backdrops (canvas space)
  var BACKDROPS = {
    flat: function (T, g, w, h) {
      g.fillStyle = F.pal.bg; g.fillRect(0, 0, w, h);
    },
    dark: function (T, g, w, h) {
      g.fillStyle = F.pal.bg; g.fillRect(0, 0, w, h);
      var r = Math.max(w, h);
      var gr = g.createRadialGradient(w * 0.5, h * -0.1, 0, w * 0.5, h * -0.1, r * 0.95);
      gr.addColorStop(0, F.rgba(F.pal.accent, 0.13));
      gr.addColorStop(0.45, F.rgba(F.pal.bg2, 0.6));
      gr.addColorStop(1, F.rgba(F.pal.bg, 0));
      g.fillStyle = gr; g.fillRect(0, 0, w, h);
    },
    paper: function (T, g, w, h) {
      var gr = g.createRadialGradient(w * 0.5, h * 0.42, 0, w * 0.5, h * 0.5, Math.max(w, h) * 0.75);
      gr.addColorStop(0, F.lighten(F.pal.bg, 0.35));
      gr.addColorStop(0.6, F.pal.bg);
      gr.addColorStop(1, F.pal.bg2);
      g.fillStyle = gr; g.fillRect(0, 0, w, h);
    },
    blueprint: function (T, g, w, h) {
      var gr = g.createLinearGradient(0, 0, 0, h);
      gr.addColorStop(0, F.pal.bg); gr.addColorStop(1, F.pal.bg2);
      g.fillStyle = gr; g.fillRect(0, 0, w, h);
      var step = Math.round(h / 27);
      g.lineWidth = 1;
      for (var pass = 0; pass < 2; pass++) {
        g.strokeStyle = F.rgba(F.pal.ink, pass ? 0.13 : 0.05);
        var st = pass ? step * 5 : step;
        g.beginPath();
        for (var x = (w / 2) % st; x < w; x += st) { g.moveTo(Math.round(x) + 0.5, 0); g.lineTo(Math.round(x) + 0.5, h); }
        for (var y = (h / 2) % st; y < h; y += st) { g.moveTo(0, Math.round(y) + 0.5); g.lineTo(w, Math.round(y) + 0.5); }
        g.stroke();
      }
      // registration marks
      var m = h * 0.045, L = h * 0.025;
      g.strokeStyle = F.rgba(F.pal.ink, 0.35);
      g.lineWidth = Math.max(1, h / 900);
      [[m, m], [w - m, m], [m, h - m], [w - m, h - m]].forEach(function (p) {
        g.beginPath();
        g.moveTo(p[0] - L, p[1]); g.lineTo(p[0] + L, p[1]);
        g.moveTo(p[0], p[1] - L); g.lineTo(p[0], p[1] + L);
        g.stroke();
        g.beginPath(); g.arc(p[0], p[1], L * 0.45, 0, Math.PI * 2); g.stroke();
      });
    },
    film: function (T, g, w, h) {
      var gr = g.createRadialGradient(w * 0.5, h * 0.45, 0, w * 0.5, h * 0.5, Math.max(w, h) * 0.7);
      gr.addColorStop(0, F.pal.bg2); gr.addColorStop(1, F.pal.bg);
      g.fillStyle = gr; g.fillRect(0, 0, w, h);
      // slow exposure flicker
      var fl = noise(T * 6, 3) * 0.018 + noise(T * 23, 5) * 0.008;
      if (fl > 0) { g.fillStyle = 'rgba(255,240,220,' + fl.toFixed(4) + ')'; g.fillRect(0, 0, w, h); }
    },
    neon: function (T, g, w, h) {
      g.fillStyle = F.pal.bg; g.fillRect(0, 0, w, h);
      var r = Math.max(w, h);
      [[0.15, 1.05, F.pal.accent, 0.22], [0.85, 1.1, F.pal.accent2, 0.18], [0.5, -0.2, F.pal.accent3, 0.12]].forEach(function (b, i) {
        var cx = w * (b[0] + noise(T * 0.07, 11 + i) * 0.05), cy = h * b[1];
        var gr = g.createRadialGradient(cx, cy, 0, cx, cy, r * 0.7);
        gr.addColorStop(0, F.rgba(b[2], b[3])); gr.addColorStop(1, F.rgba(b[2], 0));
        g.fillStyle = gr; g.fillRect(0, 0, w, h);
      });
    },
  };
  F.BACKDROPS = BACKDROPS;

  // ------------------------------------------------------------------ texture layers
  function makeCanvas(w, h) {
    var c;
    if (typeof OffscreenCanvas !== 'undefined') c = new OffscreenCanvas(Math.max(1, w), Math.max(1, h));
    else { c = document.createElement('canvas'); c.width = Math.max(1, w); c.height = Math.max(1, h); }
    return c;
  }
  F.makeCanvas = makeCanvas;

  function buildLayers() {
    var L = { grain: [], vignette: null, key: S.cw + 'x' + S.ch + '@' + S.dpr };
    var n = 256;
    for (var v = 0; v < 4; v++) {
      var c = makeCanvas(n, n), x = c.getContext('2d');
      var img = x.createImageData(n, n), d = img.data, r = rng(1013 + v * 77);
      for (var i = 0; i < d.length; i += 4) {
        var s = r.gauss() * 0.5;
        var val = s > 0 ? 255 : 0;
        d[i] = d[i + 1] = d[i + 2] = val;
        d[i + 3] = Math.min(255, Math.abs(s) * 255);
      }
      x.putImageData(img, 0, 0);
      L.grain.push(c);
    }
    var pw = Math.round(S.cw * S.dpr), ph = Math.round(S.ch * S.dpr);
    var vc = makeCanvas(pw, ph), vx = vc.getContext('2d');
    var gr = vx.createRadialGradient(pw / 2, ph / 2, Math.min(pw, ph) * 0.25, pw / 2, ph / 2, Math.hypot(pw, ph) / 2);
    gr.addColorStop(0, 'rgba(0,0,0,0)');
    gr.addColorStop(0.55, 'rgba(0,0,0,0.25)');
    gr.addColorStop(1, 'rgba(0,0,0,1)');
    vx.fillStyle = gr; vx.fillRect(0, 0, pw, ph);
    L.vignette = vc;
    return L;
  }

  // Grain. fps 0 (default) = static texture: removes gradient banding at almost no bitrate cost.
  // Animated grain (fps > 0) looks like film but is incompressible noise: expect 10-30x larger files.
  function drawGrain(T, amount, fps, size) {
    if (!(amount > 0)) return;
    var g = S.g, L = S.layers;
    var k = fps > 0 ? Math.floor(T * fps + 1e-6) : 0;
    var tile = L.grain[Math.floor(hash(k * 3 + 1) * L.grain.length)];
    var pat = g.createPattern(tile, 'repeat');
    var sc = Math.max(1, S.ch * S.dpr / 1080) * (size || 1);
    if (pat.setTransform && typeof DOMMatrix !== 'undefined') {
      pat.setTransform(new DOMMatrix().translate(Math.floor(hash(k * 7 + 3) * 256), Math.floor(hash(k * 11 + 5) * 256)).scale(sc));
    }
    g.save();
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.globalAlpha = clamp(amount, 0, 1);
    g.fillStyle = pat;
    g.fillRect(0, 0, g.canvas.width, g.canvas.height);
    g.restore();
  }
  function drawVignette(amount) {
    if (!(amount > 0)) return;
    var g = S.g;
    g.save();
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.globalAlpha = clamp(amount);
    g.drawImage(S.layers.vignette, 0, 0);
    g.restore();
  }
  function drawDust(T, amount) {
    if (!(amount > 0)) return;
    var g = S.g, w = S.cw, h = S.ch, k = Math.floor(T * 24 + 1e-6);
    var light = F.luminance(F.pal.bg) < 0.4;
    var count = Math.round(40 * amount);
    g.save();
    for (var i = 0; i < count; i++) {
      var hv = hash(k * 1597 + i * 31);
      if (hv > 0.35) continue;
      var x = hash(k * 733 + i * 17) * w, y = hash(k * 911 + i * 13) * h;
      var sz = (0.6 + hash(i * 97 + k) * 1.8) * h / 1080;
      g.globalAlpha = 0.25 + 0.45 * hash(k + i * 5);
      g.fillStyle = light ? '#f5efe6' : '#2a241d';
      if (hash(i * 7 + k * 3) < 0.12) {
        g.strokeStyle = g.fillStyle;
        g.lineWidth = Math.max(0.7, sz * 0.5);
        g.beginPath();
        var len = (8 + hash(i + k * 13) * 22) * h / 1080, a = hash(i * 3 + k) * Math.PI * 2;
        g.moveTo(x, y);
        g.quadraticCurveTo(x + Math.cos(a) * len * 0.6 + len * 0.3, y + Math.sin(a) * len * 0.6, x + Math.cos(a) * len, y + Math.sin(a) * len);
        g.stroke();
      } else {
        g.beginPath(); g.arc(x, y, sz, 0, Math.PI * 2); g.fill();
      }
    }
    g.restore();
  }
  function drawLeak(T, amount) {
    if (!(amount > 0)) return;
    var g = S.g, w = S.cw, h = S.ch;
    g.save();
    g.globalCompositeOperation = 'screen';
    var blobs = [[0.05, 0.2, '#ff7a3d'], [0.95, 0.85, '#ff3d6e'], [0.8, 0.1, '#ffc46b']];
    for (var i = 0; i < blobs.length; i++) {
      var b = blobs[i];
      var inten = clamp(0.25 + 0.75 * (noise(T * 0.35, 40 + i) * 0.5 + 0.5)) * amount;
      var cx = w * (b[0] + noise(T * 0.12, 50 + i) * 0.12), cy = h * (b[1] + noise(T * 0.1, 60 + i) * 0.12);
      var r = Math.max(w, h) * (0.35 + 0.1 * noise(T * 0.2, 70 + i));
      var gr = g.createRadialGradient(cx, cy, 0, cx, cy, r);
      gr.addColorStop(0, F.rgba(b[2], 0.55 * inten));
      gr.addColorStop(1, F.rgba(b[2], 0));
      g.fillStyle = gr; g.fillRect(0, 0, w, h);
    }
    g.restore();
  }

  // ================================================================== fonts & text
  F.FONTS = {
    sans: '"Inter Variable", "Inter", sans-serif',
    display: '"Space Grotesk Variable", "Inter Variable", sans-serif',
    serif: '"Instrument Serif", "Fraunces Variable", serif',
    mono: '"JetBrains Mono Variable", "JetBrains Mono", monospace',
  };
  /** Font CSS string: F.font(64, 700, 'sans') or F.font(40, 400, 'serif', 'italic'). */
  F.font = function (size, weight, family, style) {
    var fam = F.FONTS[family || 'sans'] || family || F.FONTS.sans;
    return (style ? style + ' ' : '') + (weight || 400) + ' ' + (+size).toFixed(2) + 'px ' + fam;
  };
  var SAMPLE_TEXT = 'AaBbGgQq0123456789 .,:;!?%$&@#()[]+-=/*"\'’“” →←↑↓⌘⇧⌥⌃↵⏎•·—–€£';
  /**
   * Load fonts before the first frame. items: CSS font strings ('700 1em "Inter Variable"')
   * or {family, src, weight, style} to register a font file (src relative to the page).
   */
  F.loadFonts = function (items) {
    if (typeof document === 'undefined' || !document.fonts) return Promise.resolve([]);
    var jobs = (items || []).map(function (it) {
      if (typeof it === 'string') {
        return document.fonts.load(it, SAMPLE_TEXT).then(function (faces) {
          // (an HTML export leaves out the faces no frame draws with: not worth a warning there)
          if ((!faces || !faces.length) && !root.__ST_EXPORT__) warnOnce('font:' + it, 'font "' + it + '" did not load (is its CSS linked in index.html?)');
          return faces;
        });
      }
      var face = new FontFace(it.family, 'url(' + JSON.stringify(it.src) + ')',
        { weight: String(it.weight || '100 900'), style: it.style || 'normal' });
      document.fonts.add(face);
      return face.load().catch(function (e) {
        warnOnce('fontfile:' + it.src, 'could not load font file ' + it.src + ': ' + e);
      });
    });
    return Promise.all(jobs).then(function (r) { return document.fonts.ready.then(function () { return r; }); });
  };

  function setFont(o) {
    var g = S.g;
    g.font = F.font(o.size || 48, o.weight || 400, o.family || 'sans', o.italic ? 'italic' : o.style);
    var tr = (o.tracking || 0) * (o.size || 48);
    if ('letterSpacing' in g) g.letterSpacing = tr ? tr.toFixed(2) + 'px' : '0px';
    return tr;
  }
  function nativeTracking() { return S.g && ('letterSpacing' in S.g); }

  /** Width of a string in the given text style (tracking included). */
  F.measure = function (str, o) {
    o = o || {};
    var g = S.g;
    g.save();
    var tr = setFont(o);
    var w = g.measureText(String(str)).width;
    if (!nativeTracking() && tr) w += tr * Math.max(0, Array.from(String(str)).length - 1);
    g.restore();
    return w;
  };
  /** Largest size <= o.size such that str fits maxWidth. */
  F.fit = function (str, maxWidth, o) {
    o = o || {};
    var size = o.size || 96, min = o.minSize || 8;
    var w = F.measure(str, Object.assign({}, o, { size: size }));
    if (w <= maxWidth) return size;
    size = Math.max(min, size * maxWidth / w);
    for (var i = 0; i < 6 && size > min; i++) {
      w = F.measure(str, Object.assign({}, o, { size: size }));
      if (w <= maxWidth) break;
      size *= 0.97;
    }
    return size;
  };
  /** Wrap text to lines no wider than maxWidth ('\n' forces a break). */
  F.wrap = function (str, maxWidth, o) {
    var out = [];
    String(str).split('\n').forEach(function (para) {
      var words = para.split(/\s+/).filter(function (w) { return w.length; });
      if (!words.length) { out.push(''); return; }
      var line = words[0];
      for (var i = 1; i < words.length; i++) {
        var test = line + ' ' + words[i];
        if (maxWidth && F.measure(test, o) > maxWidth) { out.push(line); line = words[i]; } else line = test;
      }
      out.push(line);
    });
    return out;
  };

  function applyShadow(sh) {
    var g = S.g;
    if (!sh) return;
    if (sh === true) sh = {};
    g.shadowColor = sh.color || F.pal.shadow || 'rgba(0,0,0,0.5)';
    g.shadowBlur = sh.blur === undefined ? 24 : sh.blur;
    g.shadowOffsetX = sh.x || 0;
    g.shadowOffsetY = sh.y === undefined ? 8 : sh.y;
  }
  F.shadow = applyShadow;

  function rawText(str, x, y, o, tr) {
    var g = S.g;
    if (nativeTracking() || !tr) {
      if (o.stroke) g.strokeText(str, x, y);
      if (o.color !== 'none') g.fillText(str, x, y);
      return;
    }
    // manual tracking fallback (browsers without ctx.letterSpacing)
    var chars = Array.from(str), total = F.measure(str, o), cx = x;
    var al = g.textAlign;
    if (al === 'center') cx = x - total / 2; else if (al === 'right' || al === 'end') cx = x - total;
    g.textAlign = 'left';
    for (var i = 0; i < chars.length; i++) {
      if (o.stroke) g.strokeText(chars[i], cx, y);
      if (o.color !== 'none') g.fillText(chars[i], cx, y);
      cx += g.measureText(chars[i]).width + tr;
    }
    g.textAlign = al;
  }

  /** A design-space rect through the current transform -> {x, y, w, h} in output CSS pixels. */
  function outRect(x0, y0, w, h, g) {
    var m = g.getTransform ? g.getTransform() : null;
    var pts = [[x0, y0], [x0 + w, y0], [x0, y0 + h], [x0 + w, y0 + h]].map(function (pt) {
      return m ? [(m.a * pt[0] + m.c * pt[1] + m.e) / S.dpr, (m.b * pt[0] + m.d * pt[1] + m.f) / S.dpr] : pt;
    });
    var xs = pts.map(function (q) { return q[0]; }), ys = pts.map(function (q) { return q[1]; });
    var bx = Math.min.apply(null, xs), by = Math.min.apply(null, ys);
    return { x: bx, y: by, w: Math.max.apply(null, xs) - bx, h: Math.max.apply(null, ys) - by, m: m };
  }
  /** Record an opaque card (callout, caption, step band) or a dim (spotlight) for QA: text drawn before it and under it is hidden or dimmed on purpose. */
  function recordCover(kind, text, x, y, w, h, g, extra) {
    if (!S.covers || S.covers.length >= 60 || g.globalAlpha < 0.5) return;
    var r = outRect(x, y, w, h, g), c = { kind: kind, text: String(text || '').slice(0, 60), x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.w), h: Math.round(r.h), z: S.drawSeq = (S.drawSeq || 0) + 1 };
    if (extra) for (var k in extra) c[k] = extra[k];
    S.covers.push(c);
  }
  // Every F.text call of the current frame, in output CSS pixels, for QA tools (Film.frameInfo()).
  function recordText(str, x, y, w, o, g) {
    var size = o.size || 48, al = g.textAlign, bl = g.textBaseline;
    var x0 = al === 'center' ? x - w / 2 : (al === 'right' || al === 'end') ? x - w : x;
    var y0 = bl === 'middle' ? y - size * 0.5 : bl === 'top' || bl === 'hanging' ? y : bl === 'bottom' ? y - size : y - size * 0.78;
    var r = outRect(x0, y0, w, size, g), m = r.m;
    S.texts.push({
      text: str.slice(0, 120), x: Math.round(r.x), y: Math.round(r.y),
      w: Math.round(r.w), h: Math.round(r.h), z: S.drawSeq = (S.drawSeq || 0) + 1,
      size: +(size * (m ? Math.hypot(m.a, m.b) / S.dpr : 1)).toFixed(1), font: g.font,
      color: typeof g.fillStyle === 'string' ? g.fillStyle : null, alpha: +g.globalAlpha.toFixed(3),
      cam: +(S.camZoom || 1).toFixed(3),
      decor: !!(o.decor || S.decor > 0),
      flash: !!o.flash,   // a flash word: texture in the showreel tone (scripts/lib/showreel.mjs)
    });
  }

  /**
   * Mark what `draw` paints as UI-mockup detail (the canvas twin of the DOM's data-st-decor): tiny
   * labels in a mock app window, a thumbnail's caption. `showtime check` reports their size, contrast
   * and overlaps as notes instead of warnings. Headlines and anything the viewer must read are never
   * decor. One text: F.text(str, x, y, {decor: true}). Returns what `draw` returns.
   */
  F.decor = function (draw) {
    S.decor = (S.decor || 0) + 1;
    try { return draw(); } finally { S.decor -= 1; }
  };

  /**
   * Draw text. o: {size, weight, family ('sans'|'serif'|'mono'|'display'|css), italic, color,
   * alpha, align ('left'|'center'|'right'), baseline ('alphabetic'|'middle'|'top'|'bottom'),
   * tracking (em, e.g. -0.02), maxWidth (shrinks to fit), stroke (color), strokeWidth,
   * shadow ({blur, x, y, color} | true), decor (UI-mockup detail, see F.decor), flash (a flash word: in the
   * showreel tone it may leave before its reading time, references/tones.md)}. Returns the drawn width.
   */
  F.text = function (str, x, y, o) {
    o = o || {};
    str = String(str);
    var g = S.g;
    var a = o.alpha === undefined ? 1 : o.alpha;
    if (a <= 0 || !str) return 0;
    if (MISSING_SYMBOLS.test(str)) {
      warnOnce('sym:' + str, 'text "' + str + '" contains symbols the bundled fonts lack (arrows, ⌘, ↵ ...): ' +
        'each OS would draw them with a different fallback font. Use F.glyph() or F.keycap() for symbols.');
    }
    if (o.maxWidth) o = Object.assign({}, o, { size: F.fit(str, o.maxWidth, o) });
    g.save();
    var tr = setFont(o);
    g.globalAlpha *= a;
    g.textAlign = o.align || 'left';
    g.textBaseline = o.baseline || 'alphabetic';
    g.fillStyle = o.color || F.pal.ink;
    if (o.stroke) {
      g.strokeStyle = o.stroke; g.lineWidth = o.strokeWidth || Math.max(2, (o.size || 48) * 0.08);
      g.lineJoin = 'round';
    }
    applyShadow(o.shadow);
    rawText(str, x, y, o, tr);
    var w = g.measureText(str).width;
    if (S.texts && S.texts.length < 400) recordText(str, x, y, w, o, g);
    g.restore();
    return w;
  };

  /** Multi-line text block (wraps at o.width). Returns {lines, height}. */
  F.paragraph = function (str, x, y, o) {
    o = o || {};
    var size = o.size || 36, lh = (o.lineHeight || 1.35) * size;
    var lines = o.width ? F.wrap(str, o.width, o) : String(str).split('\n');
    for (var i = 0; i < lines.length; i++) F.text(lines[i], x, y + i * lh, o);
    return { lines: lines, height: lines.length * lh };
  };

  /**
   * Animated reveal of a text block. p: 0..1 overall progress (use F.seg(T, a, b)).
   * o: all F.text options plus {by: 'line'|'word'|'char', effect: 'rise'|'fade'|'blur'|'scale'|'slide',
   * width (wrap), lineHeight, overlap (stagger share per unit), ease, exit (0..1 reverse fade)}.
   * 'rise' masks each line so words slide up from behind an invisible edge.
   */
  F.reveal = function (str, x, y, p, o) {
    o = o || {};
    var g = S.g;
    var size = o.size || 64, lh = (o.lineHeight || 1.12) * size;
    var by = o.by || 'word', effect = o.effect || (by === 'char' ? 'fade' : 'rise');
    var ease = easeFn(o.ease || 'reveal');
    var lines = o.width ? F.wrap(str, o.width, o) : String(str).split('\n');
    var units = [];
    lines.forEach(function (line, li) {
      var lw = F.measure(line, o);
      var x0 = o.align === 'center' ? x - lw / 2 : o.align === 'right' ? x - lw : x;
      var ly = y + li * lh;
      if (by === 'line') { units.push({ s: line, x: x0, y: ly, li: li }); return; }
      var parts = by === 'char' ? Array.from(line) : line.split(/(\s+)/);
      var acc = '';
      parts.forEach(function (part) {
        if (by !== 'char' && /^\s+$/.test(part)) { acc += part; return; }
        if (!part.length) return;
        units.push({ s: part, x: x0 + (acc ? F.measure(acc, o) : 0), y: ly, li: li });
        acc += part;
      });
    });
    var n = units.length, exit = o.exit || 0;
    var textO = Object.assign({}, o, { align: 'left', alpha: 1 });
    delete textO.maxWidth;
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha) * (1 - clamp(exit));
    for (var i = 0; i < n; i++) {
      var u = units[i];
      var q = ease(F.split(p, i, n, o.overlap));
      if (q <= 0) continue;
      g.save();
      if (effect === 'rise') {
        g.beginPath();
        g.rect(u.x - size, u.y - size * 1.05, F.measure(u.s, o) + size * 2, size * 1.4);
        g.clip();
        g.translate(0, (1 - q) * size * 1.0);
      } else if (effect === 'fade') {
        g.globalAlpha *= q;
        g.translate(0, (1 - q) * size * 0.25);
      } else if (effect === 'blur') {
        g.globalAlpha *= q;
        var b = (1 - q) * size * 0.18 * S.s;
        if (b > 0.05) g.filter = 'blur(' + b.toFixed(2) + 'px)';
      } else if (effect === 'scale') {
        g.globalAlpha *= q;
        var w = F.measure(u.s, o), sc = lerp(0.85, 1, q);
        g.translate(u.x + w / 2, u.y - size * 0.35);
        g.scale(sc, sc);
        g.translate(-(u.x + w / 2), -(u.y - size * 0.35));
      } else if (effect === 'slide') {
        g.globalAlpha *= q;
        g.translate((1 - q) * -size * 0.6, 0);
      }
      F.text(u.s, u.x, u.y, textO);
      g.restore();
    }
    g.restore();
    return { lines: lines, height: lines.length * lh, units: n };
  };

  /**
   * Typewriter: shows the first round(p * length) characters with a caret.
   * o: F.text options + {caret: true, caretColor, lineHeight, blink (s)}.
   */
  F.typewriter = function (str, x, y, p, o) {
    o = o || {};
    var chars = Array.from(String(str));
    var n = Math.round(clamp(p) * chars.length);
    var shown = chars.slice(0, n).join('');
    var size = o.size || 48, lh = (o.lineHeight || 1.3) * size;
    var lines = shown.split('\n');
    var tOpts = Object.assign({}, o);
    delete tOpts.maxWidth;
    for (var i = 0; i < lines.length; i++) F.text(lines[i], x, y + i * lh, tOpts);
    if (o.caret !== false) {
      var typing = p > 0 && p < 1;
      var blink = o.blink || 1.0;
      var on = typing || fract(S.T / blink) < 0.55;
      if (on) {
        var last = lines[lines.length - 1];
        var cw = F.measure(last, tOpts);
        var cx = (o.align === 'center' ? x + cw / 2 : o.align === 'right' ? x : x + cw) + size * 0.06;
        var g = S.g;
        g.save();
        g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
        g.fillStyle = o.caretColor || F.pal.accent;
        var base = (o.baseline === 'middle') ? y + (lines.length - 1) * lh - size * 0.4 : y + (lines.length - 1) * lh - size * 0.78;
        g.fillRect(cx, base, Math.max(2, size * 0.07), size * 0.92);
        g.restore();
      }
    }
    return n;
  };

  /**
   * Count-up number with fixed-width digits (no jitter).
   * o: F.text options + {from: 0, decimals: 0, prefix, suffix, separator: ',', suffixColor, format(v)}.
   */
  F.counter = function (value, x, y, p, o) {
    o = o || {};
    var v = lerp(o.from || 0, value, clamp(p));
    var dec = o.decimals || 0;
    var body = o.format ? o.format(v) : formatNumber(v, dec, o.separator === undefined ? ',' : o.separator);
    var str = (o.prefix || '') + body;
    var g = S.g;
    g.save();
    var tO = Object.assign({}, o, { align: 'left' });
    var digitW = F.measure('0', tO);
    // width with tabular digits
    var chars = Array.from(str);
    var widths = chars.map(function (c) { return /[0-9]/.test(c) ? digitW : F.measure(c, tO); });
    var sufW = o.suffix ? F.measure(o.suffix, Object.assign({}, tO, { size: o.suffixSize || o.size })) : 0;
    var total = widths.reduce(function (a, b) { return a + b; }, 0) + sufW;
    var cx = o.align === 'center' ? x - total / 2 : o.align === 'right' ? x - total : x;
    for (var i = 0; i < chars.length; i++) {
      var w = widths[i];
      F.text(chars[i], cx + ( /[0-9]/.test(chars[i]) ? (w - F.measure(chars[i], tO)) / 2 : 0), y, tO);
      cx += w;
    }
    if (o.suffix) F.text(o.suffix, cx, y, Object.assign({}, tO, { color: o.suffixColor || o.color, size: o.suffixSize || o.size }));
    g.restore();
    return total;
  };
  function formatNumber(v, dec, sep) {
    var s = Math.abs(v).toFixed(dec);
    var parts = s.split('.');
    if (sep) parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, sep);
    return (v < 0 && Math.abs(v) >= Math.pow(10, -dec) / 2 ? '-' : '') + parts.join('.');
  }
  F.formatNumber = formatNumber;

  // ================================================================== shapes
  /** Rounded-rect path (r number or [tl, tr, br, bl]). Does not fill. */
  F.rr = function (x, y, w, h, r) {
    var g = S.g;
    if (w < 0) { x += w; w = -w; }
    if (h < 0) { y += h; h = -h; }
    var rs = Array.isArray(r) ? r : [r || 0, r || 0, r || 0, r || 0];
    var m = Math.min(w, h) / 2;
    var tl = Math.min(rs[0], m), tr = Math.min(rs[1], m), br = Math.min(rs[2], m), bl = Math.min(rs[3], m);
    g.beginPath();
    g.moveTo(x + tl, y);
    g.lineTo(x + w - tr, y); g.arcTo(x + w, y, x + w, y + tr, tr);
    g.lineTo(x + w, y + h - br); g.arcTo(x + w, y + h, x + w - br, y + h, br);
    g.lineTo(x + bl, y + h); g.arcTo(x, y + h, x, y + h - bl, bl);
    g.lineTo(x, y + tl); g.arcTo(x, y, x + tl, y, tl);
    g.closePath();
  };
  function paint(o) {
    var g = S.g;
    if (o.fill !== undefined && o.fill !== null && o.fill !== 'none') {
      g.fillStyle = o.fill;
      g.fill();
    }
    if (o.stroke) {
      g.shadowColor = 'transparent';
      g.strokeStyle = o.stroke;
      g.lineWidth = o.lineWidth || 2;
      if (o.dash) g.setLineDash(o.dash);
      g.stroke();
    }
  }
  /** Filled/stroked rounded rect. o: {fill, stroke, lineWidth, alpha, shadow, dash}. */
  F.box = function (x, y, w, h, r, o) {
    o = o || {};
    var g = S.g;
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    applyShadow(o.shadow);
    F.rr(x, y, w, h, r);
    paint(o);
    // o.dims: this box is a scrim/overlay that dims what is under it on purpose (a modal's backdrop):
    // check does not judge the contrast of text beneath it
    if (o.dims && S.covers && g.globalAlpha >= 0.15) {
      var dr = outRect(x, y, w, h, g);
      S.covers.push({ kind: 'dim', text: '', x: Math.round(dr.x), y: Math.round(dr.y), w: Math.round(dr.w), h: Math.round(dr.h), hole: null, z: S.drawSeq = (S.drawSeq || 0) + 1 });
    }
    g.restore();
  };
  F.circle = function (x, y, r, o) {
    o = o || {};
    var g = S.g;
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    applyShadow(o.shadow);
    g.beginPath(); g.arc(x, y, Math.max(0, r), 0, Math.PI * 2);
    paint(o.fill === undefined && !o.stroke ? Object.assign({ fill: F.pal.ink }, o) : o);
    g.restore();
  };
  F.line = function (x1, y1, x2, y2, o) {
    o = o || {};
    var g = S.g;
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    g.strokeStyle = o.color || F.pal.ink;
    g.lineWidth = o.width || 2;
    g.lineCap = o.cap || 'round';
    if (o.dash) g.setLineDash(o.dash);
    g.beginPath(); g.moveTo(x1, y1); g.lineTo(x2, y2); g.stroke();
    g.restore();
  };
  /** Soft radial glow. */
  F.glow = function (x, y, r, color, alpha) {
    var g = S.g;
    var gr = g.createRadialGradient(x, y, 0, x, y, Math.max(1, r));
    gr.addColorStop(0, F.rgba(color || F.pal.accent, alpha === undefined ? 0.35 : alpha));
    gr.addColorStop(1, F.rgba(color || F.pal.accent, 0));
    g.save();
    g.fillStyle = gr;
    g.fillRect(x - r, y - r, r * 2, r * 2);
    g.restore();
  };
  /** Background grid of lines or dots. o: {step, color, alpha, dots, rect}. */
  F.grid = function (o) {
    o = o || {};
    var g = S.g, step = o.step || 60, rc = o.rect || { x: 0, y: 0, w: S.W, h: S.H };
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 0.08 : o.alpha);
    g.fillStyle = g.strokeStyle = o.color || F.pal.ink;
    g.lineWidth = o.width || 1;
    if (o.dots) {
      for (var x = rc.x; x <= rc.x + rc.w; x += step) {
        for (var y = rc.y; y <= rc.y + rc.h; y += step) { g.beginPath(); g.arc(x, y, o.dotSize || 1.6, 0, Math.PI * 2); g.fill(); }
      }
    } else {
      g.beginPath();
      for (var x2 = rc.x; x2 <= rc.x + rc.w + 0.1; x2 += step) { g.moveTo(x2, rc.y); g.lineTo(x2, rc.y + rc.h); }
      for (var y2 = rc.y; y2 <= rc.y + rc.h + 0.1; y2 += step) { g.moveTo(rc.x, y2); g.lineTo(rc.x + rc.w, y2); }
      g.stroke();
    }
    g.restore();
  };

  /** Pill label centred at (x, y). o: {size, fill, color, stroke, padX, padY, weight, icon (dot color)}. Returns {w, h}. */
  F.pill = function (label, x, y, o) {
    o = o || {};
    var size = o.size || 26;
    var tO = { size: size, weight: o.weight || 600, family: o.family || 'sans', tracking: o.tracking || 0 };
    var tw = F.measure(label, tO);
    var padX = o.padX === undefined ? size * 0.75 : o.padX, padY = o.padY === undefined ? size * 0.45 : o.padY;
    var dot = o.icon ? size * 0.7 : 0;
    var w = tw + padX * 2 + dot, h = size + padY * 2;
    var g = S.g;
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    F.box(x - w / 2, y - h / 2, w, h, h / 2, { fill: o.fill || F.rgba(F.pal.ink, 0.09), stroke: o.stroke === undefined ? F.rgba(F.pal.ink, 0.16) : o.stroke, lineWidth: o.lineWidth || 1.5, shadow: o.shadow });
    if (o.icon) F.circle(x - w / 2 + padX + size * 0.22, y, size * 0.2, { fill: o.icon });
    F.text(label, x - w / 2 + padX + dot, y, Object.assign({ color: o.color || F.pal.ink, baseline: 'middle' }, tO));
    g.restore();
    return { w: w, h: h };
  };

  /**
   * Card panel. o: {fill, stroke, radius, shadow (default soft), title, titleSize, body, bodySize,
   * alpha, pad, accent (left bar color)}.
   */
  F.card = function (x, y, w, h, o) {
    o = o || {};
    var g = S.g, r = o.radius === undefined ? 18 : o.radius, pad = o.pad === undefined ? 28 : o.pad;
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    F.box(x, y, w, h, r, {
      fill: o.fill || F.pal.panel, stroke: o.stroke === undefined ? F.pal.line : o.stroke, lineWidth: o.lineWidth || 1.5,
      shadow: o.shadow === undefined ? { blur: 40, y: 18, color: F.pal.shadow } : o.shadow,
    });
    if (o.accent) {
      g.save(); F.rr(x, y, w, h, r); g.clip();
      g.fillStyle = o.accent; g.fillRect(x, y, Math.max(4, r * 0.35), h);
      g.restore();
    }
    var cy = y + pad;
    if (o.title) {
      var ts = o.titleSize || 30;
      F.text(o.title, x + pad, cy + ts * 0.8, { size: ts, weight: 700, color: o.titleColor || F.pal.ink, maxWidth: w - pad * 2 });
      cy += ts * 1.5;
    }
    if (o.body) {
      var bs = o.bodySize || 22;
      F.paragraph(o.body, x + pad, cy + bs * 0.8, { size: bs, color: o.bodyColor || F.pal.muted, width: w - pad * 2, lineHeight: 1.4 });
    }
    g.restore();
  };

  // @part glyphs: GLYPHS GLYPH_ALIAS glyphName glyph keycap keyCombo
  // ------------------------------------------------------------------ vector glyphs
  // Keyboard and UI symbols are drawn as paths: the bundled text fonts do not contain them, and
  // the OS fallback font would make them look different on macOS, Windows and Linux.
  var GLYPH_ALIAS = {
    '⌘': 'cmd', '⇧': 'shift', '⌥': 'option', '⌃': 'ctrl', '↵': 'return', '⏎': 'return', '↩': 'return',
    '←': 'left', '→': 'right', '↑': 'up', '↓': 'down', '⌫': 'backspace', '⇥': 'tab', '✓': 'check', '✔': 'check',
  };
  var GLYPHS = {
    cmd: function (g, s) {
      var a = s * 0.13, r = s * 0.12, e = a + r;
      g.beginPath();
      g.moveTo(-e, -a); g.lineTo(e, -a); g.moveTo(-e, a); g.lineTo(e, a);
      g.moveTo(-a, -e); g.lineTo(-a, e); g.moveTo(a, -e); g.lineTo(a, e);
      [[1, -1], [-1, -1], [1, 1], [-1, 1]].forEach(function (c) {
        var cx = c[0] * e, cy = c[1] * e, a1 = Math.atan2(-c[1], 0), a2 = Math.atan2(0, -c[0]);
        g.moveTo(cx + Math.cos(a1) * r, cy + Math.sin(a1) * r);
        g.arc(cx, cy, r, a1, a2, c[0] * c[1] < 0);
      });
      g.stroke();
    },
    shift: function (g, s) {
      g.beginPath();
      g.moveTo(0, -0.36 * s); g.lineTo(0.34 * s, 0.02 * s); g.lineTo(0.16 * s, 0.02 * s); g.lineTo(0.16 * s, 0.32 * s);
      g.lineTo(-0.16 * s, 0.32 * s); g.lineTo(-0.16 * s, 0.02 * s); g.lineTo(-0.34 * s, 0.02 * s); g.closePath();
      g.stroke();
    },
    option: function (g, s) {
      g.beginPath();
      g.moveTo(-0.36 * s, -0.24 * s); g.lineTo(-0.12 * s, -0.24 * s); g.lineTo(0.13 * s, 0.26 * s); g.lineTo(0.36 * s, 0.26 * s);
      g.moveTo(0.08 * s, -0.24 * s); g.lineTo(0.36 * s, -0.24 * s);
      g.stroke();
    },
    ctrl: function (g, s) {
      g.beginPath(); g.moveTo(-0.28 * s, 0.1 * s); g.lineTo(0, -0.2 * s); g.lineTo(0.28 * s, 0.1 * s); g.stroke();
    },
    'return': function (g, s) {
      g.beginPath();
      g.moveTo(0.3 * s, -0.3 * s); g.lineTo(0.3 * s, 0.1 * s); g.lineTo(-0.3 * s, 0.1 * s);
      g.moveTo(-0.1 * s, -0.1 * s); g.lineTo(-0.3 * s, 0.1 * s); g.lineTo(-0.1 * s, 0.3 * s);
      g.stroke();
    },
    right: function (g, s) {
      g.beginPath();
      g.moveTo(-0.3 * s, 0); g.lineTo(0.3 * s, 0); g.moveTo(0.08 * s, -0.22 * s); g.lineTo(0.3 * s, 0); g.lineTo(0.08 * s, 0.22 * s);
      g.stroke();
    },
    left: function (g, s) { g.rotate(Math.PI); GLYPHS.right(g, s); },
    up: function (g, s) { g.rotate(-Math.PI / 2); GLYPHS.right(g, s); },
    down: function (g, s) { g.rotate(Math.PI / 2); GLYPHS.right(g, s); },
    backspace: function (g, s) {
      g.beginPath();
      g.moveTo(-0.4 * s, 0); g.lineTo(-0.18 * s, -0.25 * s); g.lineTo(0.38 * s, -0.25 * s); g.lineTo(0.38 * s, 0.25 * s);
      g.lineTo(-0.18 * s, 0.25 * s); g.closePath();
      g.moveTo(0.02 * s, -0.1 * s); g.lineTo(0.22 * s, 0.1 * s); g.moveTo(0.22 * s, -0.1 * s); g.lineTo(0.02 * s, 0.1 * s);
      g.stroke();
    },
    tab: function (g, s) {
      g.beginPath();
      g.moveTo(-0.34 * s, 0); g.lineTo(0.24 * s, 0); g.moveTo(0.04 * s, -0.2 * s); g.lineTo(0.24 * s, 0); g.lineTo(0.04 * s, 0.2 * s);
      g.moveTo(0.34 * s, -0.24 * s); g.lineTo(0.34 * s, 0.24 * s);
      g.stroke();
    },
    check: function (g, s) {
      g.beginPath(); g.moveTo(-0.3 * s, 0.02 * s); g.lineTo(-0.08 * s, 0.24 * s); g.lineTo(0.32 * s, -0.22 * s); g.stroke();
    },
    close: function (g, s) {
      g.beginPath(); g.moveTo(-0.24 * s, -0.24 * s); g.lineTo(0.24 * s, 0.24 * s); g.moveTo(0.24 * s, -0.24 * s); g.lineTo(-0.24 * s, 0.24 * s); g.stroke();
    },
    plus: function (g, s) {
      g.beginPath(); g.moveTo(-0.28 * s, 0); g.lineTo(0.28 * s, 0); g.moveTo(0, -0.28 * s); g.lineTo(0, 0.28 * s); g.stroke();
    },
  };
  F.GLYPHS = GLYPHS;
  /** Glyph name for a symbol character or name ('⌘' -> 'cmd'), or null. */
  F.glyphName = function (label) {
    var k = String(label);
    return GLYPH_ALIAS[k] || (GLYPHS[k] ? k : null);
  };
  /**
   * Draw a vector symbol centred at (x, y). name: 'cmd'|'shift'|'option'|'ctrl'|'return'|'left'|'right'|
   * 'up'|'down'|'backspace'|'tab'|'check'|'close'|'plus' or the symbol itself ('⌘', '↵', '→' ...).
   * o: {color, width (stroke, fraction of size), alpha}.
   */
  F.glyph = function (name, x, y, size, o) {
    o = o || {};
    var key = F.glyphName(name);
    if (!key) { warnOnce('glyph:' + name, 'unknown glyph "' + name + '"'); return; }
    var g = S.g;
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    g.translate(x, y);
    g.strokeStyle = o.color || F.pal.ink;
    g.lineWidth = size * (o.width || 0.085);
    g.lineCap = 'round'; g.lineJoin = 'round';
    GLYPHS[key](g, size);
    g.restore();
  };
  var MISSING_SYMBOLS = /[←-⇿⌀-⏿☀-➿⬀-⯿]/;

  /**
   * Keyboard key centred at (x, y). o: {size (cap height), press (0..1), dark, alpha, minWidth}.
   * Symbol labels ('⌘', '⇧', '⌥', '⌃', '↵', arrows, '⌫', '⇥') are drawn as vector glyphs.
   * Returns the key width.
   */
  F.keycap = function (label, x, y, o) {
    o = o || {};
    var g = S.g, h = o.size || 64, press = clamp(o.press || 0);
    var dark = o.dark === undefined ? F.luminance(F.pal.bg) < 0.4 : o.dark;
    var glyph = F.glyphName(label);
    var fs = h * (String(label).length > 2 ? 0.34 : 0.46);
    var tw = glyph ? h * 0.5 : F.measure(label, { size: fs, weight: 600 });
    var w = Math.max(o.minWidth || h, tw + h * 0.6);
    var depth = h * 0.09 * (1 - press * 0.75), top = y - h / 2 + press * h * 0.06;
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    var face = dark ? '#2a2e38' : '#fdfdfd', side = dark ? '#16181e' : '#c9cdd4', edge = dark ? 'rgba(255,255,255,0.14)' : 'rgba(0,0,0,0.12)';
    if (o.color) face = o.color;
    F.box(x - w / 2, top + depth, w, h - depth, h * 0.18, { fill: side, shadow: { blur: h * 0.35, y: h * 0.12, color: 'rgba(0,0,0,0.35)' } });
    var gr = g.createLinearGradient(0, top, 0, top + h - depth);
    gr.addColorStop(0, F.lighten(face, dark ? 0.06 : 0)); gr.addColorStop(1, F.darken(face, dark ? 0.1 : 0.04));
    F.box(x - w / 2, top, w, h - depth, h * 0.18, { fill: gr, stroke: edge, lineWidth: 1.2 });
    var ink = o.textColor || (dark ? '#f1f3f7' : '#1c1f26');
    if (glyph) F.glyph(glyph, x, top + (h - depth) / 2, h * 0.62, { color: ink, width: 0.075 });
    else F.text(label, x, top + (h - depth) / 2 + fs * 0.05, { size: fs, weight: 600, align: 'center', baseline: 'middle', color: ink });
    g.restore();
    return w;
  };
  /**
   * Key combo row centred at (x, y): F.keyCombo(['⌘', 'K'], x, y, {p, press}).
   * p: appear progress (staggered pop), press: 0..1 applied to all keys.
   */
  F.keyCombo = function (keys, x, y, o) {
    o = o || {};
    var size = o.size || 64, gap = o.gap === undefined ? size * 0.22 : o.gap, plus = o.plus !== false;
    var ws = keys.map(function (k) {
      if (F.glyphName(k)) return Math.max(size, size * 1.1);
      var fs = size * (String(k).length > 2 ? 0.34 : 0.46);
      return Math.max(size, F.measure(k, { size: fs, weight: 600 }) + size * 0.6);
    });
    var plusW = plus ? size * 0.42 : 0;
    var total = ws.reduce(function (a, b) { return a + b; }, 0) + (keys.length - 1) * (gap * 2 + plusW);
    var cx = x - total / 2, g = S.g, p = o.p === undefined ? 1 : o.p;
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    for (var i = 0; i < keys.length; i++) {
      var q = E.snappy(F.split(p, i, keys.length, 0.18));
      if (q > 0) {
        g.save();
        g.globalAlpha *= clamp(q * 1.5);
        var kx = cx + ws[i] / 2;
        g.translate(kx, y); g.scale(lerp(0.7, 1, q), lerp(0.7, 1, q)); g.translate(-kx, -y);
        F.keycap(keys[i], kx, y, { size: size, press: Array.isArray(o.press) ? o.press[i] : o.press, dark: o.dark });
        g.restore();
      }
      cx += ws[i];
      if (plus && i < keys.length - 1) {
        F.text('+', cx + gap + plusW / 2, y, { size: size * 0.4, weight: 500, align: 'center', baseline: 'middle', color: F.pal.muted, alpha: clamp(p * 2) });
        cx += gap * 2 + plusW;
      }
    }
    g.restore();
    return total;
  };

  // @end glyphs
  // @part pointer: cursor ripple pulse
  /**
   * Pointer at (x, y) (tip position). o: {kind: 'arrow'|'dot'|'ibeam', scale, press (0..1), color, alpha,
   * tag ('Right-click', 'Drag' ...: a small label above-left of the pointer, so it never covers what
   * the pointer is about to open), tagAlpha}.
   */
  F.cursor = function (x, y, o) {
    o = o || {};
    var g = S.g, s = (o.scale || 1.6) * (1 - 0.15 * clamp(o.press || 0));
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    g.translate(x, y);
    g.scale(s, s);
    if (o.kind === 'dot') {
      g.beginPath(); g.arc(0, 0, 11, 0, Math.PI * 2);
      g.fillStyle = F.rgba(o.color || '#111', 0.85); g.fill();
      g.lineWidth = 3; g.strokeStyle = '#fff'; g.stroke();
    } else if (o.kind === 'ibeam') {
      g.strokeStyle = o.color || '#111'; g.lineWidth = 2.2; g.lineCap = 'round';
      g.beginPath();
      g.moveTo(-5, -12); g.quadraticCurveTo(0, -12, 0, -8); g.lineTo(0, 8); g.quadraticCurveTo(0, 12, -5, 12);
      g.moveTo(5, -12); g.quadraticCurveTo(0, -12, 0, -8); g.moveTo(0, 8); g.quadraticCurveTo(0, 12, 5, 12);
      g.stroke();
    } else {
      g.shadowColor = 'rgba(0,0,0,0.35)'; g.shadowBlur = 6; g.shadowOffsetY = 2;
      g.beginPath();
      g.moveTo(0, 0); g.lineTo(0, 22); g.lineTo(5.2, 17.2); g.lineTo(9, 25.6); g.lineTo(12.6, 24); g.lineTo(8.9, 15.8);
      g.lineTo(15.8, 15.8); g.closePath();
      g.fillStyle = o.color || '#111318'; g.fill();
      g.shadowColor = 'transparent';
      g.lineWidth = 1.6; g.strokeStyle = '#ffffff'; g.lineJoin = 'round'; g.stroke();
    }
    g.restore();
    if (o.tag) {
      var ta = (o.alpha === undefined ? 1 : o.alpha) * (o.tagAlpha === undefined ? 1 : o.tagAlpha);
      if (ta > 0) {
        var ts = 15 * (o.scale || 1.6) / 1.6, tw = F.measure(o.tag, { size: ts, weight: 650 }) + ts * 1.2;
        F.box(x - tw - ts * 0.4, y - ts * 2.4, tw, ts * 1.8, ts * 0.9, { fill: 'rgba(17,19,24,0.88)', alpha: ta });
        F.text(o.tag, x - tw / 2 - ts * 0.4, y - ts * 1.5 + 1, { size: ts, weight: 650, align: 'center', baseline: 'middle', color: '#ffffff', alpha: ta });
      }
    }
  };
  /** Click ripple at (x, y); age = seconds since the click. o: {radius, dur, color, width}. */
  F.ripple = function (x, y, age, o) {
    o = o || {};
    var dur = o.dur || 0.55;
    if (!(age >= 0) || age > dur) return;
    var p = age / dur, g = S.g, r = (o.radius || 44) * E.outCubic(p);
    g.save();
    g.globalAlpha *= (1 - p) * (o.alpha === undefined ? 0.6 : o.alpha);
    g.strokeStyle = o.color || F.pal.accent;
    g.lineWidth = (o.width || 4) * (1 - p * 0.6);
    g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.stroke();
    g.globalAlpha *= 0.35;
    g.fillStyle = o.color || F.pal.accent;
    g.beginPath(); g.arc(x, y, r * 0.55, 0, Math.PI * 2); g.fill();
    g.restore();
  };

  /**
   * Attention pulse around a target (hover, "look here"): rings that grow out of the rect and fade,
   * one every `period` seconds from t0 while T < t1. rect {x, y, w, h, r}; o: {color, period (0.9),
   * spread (px, 16), width, t1}.
   */
  F.pulse = function (rect, T, t0, o) {
    o = o || {};
    if (T < t0 || (o.t1 !== undefined && T > o.t1 + 0.9)) return;
    var per = o.period || 0.9, spread = o.spread || 16, g = S.g, r0 = rect.r === undefined ? 12 : rect.r;
    for (var k = 0; k < 2; k++) {
      var age = (T - t0) - k * per / 2;
      if (age < 0) continue;
      var start = t0 + k * per / 2 + Math.floor(age / per) * per;
      if (o.t1 !== undefined && start > o.t1) continue;
      var p = fract(age / per), e = E.outCubic(p), pad = spread * e;
      g.save();
      g.globalAlpha *= (1 - p) * 0.8;
      g.strokeStyle = o.color || F.pal.accent;
      g.lineWidth = (o.width || 3) * (1 - p * 0.5);
      g.beginPath();
      F.rr(rect.x - pad, rect.y - pad, rect.w + pad * 2, rect.h + pad * 2, r0 + pad);
      g.stroke();
      g.restore();
    }
  };

  // @end pointer
  // @part annotate: quadPoint arrow callout spotlight
  function quadPoint(x1, y1, cx, cy, x2, y2, t) {
    var u = 1 - t;
    return [u * u * x1 + 2 * u * t * cx + t * t * x2, u * u * y1 + 2 * u * t * cy + t * t * y2];
  }
  /**
   * Arrow from (x1,y1) to (x2,y2) drawn up to progress p. o: {curve (-1..1 bend), color, width,
   * head (px), dash, alpha}.
   */
  F.arrow = function (x1, y1, x2, y2, o) {
    o = o || {};
    var p = o.p === undefined ? 1 : clamp(o.p);
    if (p <= 0) return;
    var g = S.g, bend = o.curve || 0;
    var mx = (x1 + x2) / 2, my = (y1 + y2) / 2, dx = x2 - x1, dy = y2 - y1;
    var cx = mx - dy * bend * 0.5, cy = my + dx * bend * 0.5;
    var N = 48, pts = [];
    for (var i = 0; i <= N * p; i++) pts.push(quadPoint(x1, y1, cx, cy, x2, y2, i / N));
    var end = quadPoint(x1, y1, cx, cy, x2, y2, p);
    pts.push(end);
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    g.strokeStyle = g.fillStyle = o.color || F.pal.ink;
    g.lineWidth = o.width || 4;
    g.lineCap = 'round'; g.lineJoin = 'round';
    if (o.dash) g.setLineDash(o.dash);
    g.beginPath();
    pts.forEach(function (q, k) { if (k) g.lineTo(q[0], q[1]); else g.moveTo(q[0], q[1]); });
    g.stroke();
    g.setLineDash([]);
    var prev = quadPoint(x1, y1, cx, cy, x2, y2, Math.max(0, p - 0.02));
    var ang = Math.atan2(end[1] - prev[1], end[0] - prev[0]);
    var hs = (o.head || 18) * clamp(p * 4);
    if (hs > 0.5) {
      g.beginPath();
      g.moveTo(end[0] + Math.cos(ang) * hs * 0.2, end[1] + Math.sin(ang) * hs * 0.2);
      g.lineTo(end[0] - Math.cos(ang - 0.45) * hs, end[1] - Math.sin(ang - 0.45) * hs);
      g.lineTo(end[0] - Math.cos(ang + 0.45) * hs, end[1] - Math.sin(ang + 0.45) * hs);
      g.closePath(); g.fill();
    }
    g.restore();
  };

  /**
   * Callout: dot at the anchor (ax, ay), leader line, and a label card at (bx, by).
   * o: {p (0..1), text, sub, size, color, fill, align ('left'|'right'|'center')}.
   */
  F.callout = function (ax, ay, bx, by, text, o) {
    o = o || {};
    var p = o.p === undefined ? 1 : clamp(o.p);
    if (p <= 0) return;
    var g = S.g, color = o.color || F.pal.accent, size = o.size || 26;
    var pl = E.outCubic(clamp(p / 0.5)), pc = E.reveal(clamp((p - 0.35) / 0.65));
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    F.circle(ax, ay, 7 * E.outBack(clamp(p * 3)), { fill: color });
    F.circle(ax, ay, 16 * clamp(p * 3), { stroke: F.rgba(color, 0.45), lineWidth: 2 });
    F.line(ax, ay, lerp(ax, bx, pl), lerp(ay, by, pl), { color: color, width: 2.5 });
    if (pc > 0) {
      var tO = { size: size, weight: 650 };
      var subO = { size: size * 0.72, weight: 450 };
      var tw = Math.max(F.measure(text, tO), o.sub ? F.measure(o.sub, subO) : 0);
      var pad = size * 0.6, w = tw + pad * 2, h = size * (o.sub ? 2.35 : 1.2) + pad;
      var al = o.align || (bx >= ax ? 'left' : 'right');
      var x0 = al === 'left' ? bx : al === 'right' ? bx - w : bx - w / 2, y0 = by - h / 2;
      g.globalAlpha *= pc;
      g.translate(0, (1 - pc) * 10);
      F.box(x0, y0, w, h, size * 0.45, { fill: o.fill || F.pal.panel, stroke: F.rgba(color, 0.6), lineWidth: 2, shadow: { blur: 24, y: 10, color: F.pal.shadow } });
      var an = outRect(ax, ay, 0, 0, g);
      recordCover('callout', text, x0, y0, w, h, g, { anchor: [Math.round(an.x), Math.round(an.y)] });
      F.text(text, x0 + pad, y0 + pad * 0.5 + size * 0.9, Object.assign({ color: o.textColor || F.pal.ink }, tO));
      if (o.sub) F.text(o.sub, x0 + pad, y0 + pad * 0.5 + size * 1.95, Object.assign({ color: F.pal.muted }, subO));
    }
    g.restore();
  };

  /**
   * Dim everything except a hole. hole: {x, y, w, h, r} (rounded rect) or {cx, cy, radius}.
   * o: {dim (0..1 opacity of the dimmer), color, ring (color|false), pad, p (fade)}.
   */
  F.spotlight = function (hole, o) {
    o = o || {};
    var p = o.p === undefined ? 1 : clamp(o.p);
    if (p <= 0) return;
    var g = S.g, pad = o.pad || 0;
    g.save();
    g.beginPath();
    g.rect(-S.W * 2, -S.H * 2, S.W * 5, S.H * 5);
    if (hole.radius !== undefined) {
      g.moveTo(hole.cx + hole.radius + pad, hole.cy);
      g.arc(hole.cx, hole.cy, hole.radius + pad, 0, Math.PI * 2, true);
    } else {
      var x = hole.x - pad, y = hole.y - pad, w = hole.w + pad * 2, h = hole.h + pad * 2, r = hole.r === undefined ? 14 : hole.r;
      g.moveTo(x + r, y); g.arcTo(x, y, x, y + r, r); g.lineTo(x, y + h - r); g.arcTo(x, y + h, x + r, y + h, r);
      g.lineTo(x + w - r, y + h); g.arcTo(x + w, y + h, x + w, y + h - r, r); g.lineTo(x + w, y + r);
      g.arcTo(x + w, y, x + w - r, y, r); g.closePath();
    }
    g.globalAlpha *= p * (o.dim === undefined ? 0.6 : o.dim);
    g.fillStyle = o.color || '#000';
    g.fill('evenodd');
    if (S.covers && g.globalAlpha >= 0.15) {
      var hr = hole.radius !== undefined ? { x: hole.cx - hole.radius - pad, y: hole.cy - hole.radius - pad, w: (hole.radius + pad) * 2, h: (hole.radius + pad) * 2 }
        : { x: hole.x - pad, y: hole.y - pad, w: hole.w + pad * 2, h: hole.h + pad * 2 };
      var hh = outRect(hr.x, hr.y, hr.w, hr.h, g);
      S.covers.push({ kind: 'dim', text: '', x: 0, y: 0, w: S.cw, h: S.ch, hole: [Math.round(hh.x), Math.round(hh.y), Math.round(hh.w), Math.round(hh.h)], z: S.drawSeq = (S.drawSeq || 0) + 1 });
    }
    g.restore();
    if (o.ring !== false) {
      g.save();
      g.globalAlpha *= p;
      g.strokeStyle = o.ring || F.pal.accent;
      g.lineWidth = o.ringWidth || 3;
      g.beginPath();
      if (hole.radius !== undefined) g.arc(hole.cx, hole.cy, hole.radius + pad, 0, Math.PI * 2);
      else F.rr(hole.x - pad, hole.y - pad, hole.w + pad * 2, hole.h + pad * 2, hole.r === undefined ? 14 : hole.r);
      g.stroke();
      g.restore();
    }
  };

  // @end annotate
  // @part questions: questionBeat choiceFit goodKey
  // ================================================================== stop-and-ask questions
  /**
   * The "pause and think" beat of a stop-and-ask question (showtime.json "questions", Film.questions),
   * which is what the MP4 shows where the HTML export stops and asks: the prompt and its choices while
   * the narrator asks, a countdown ring from the question's pause `t` for its `think` seconds, then
   * the right choice marked and its reply. q: a question id or a question from Film.questions.
   * o: {x, y (centre of the block; default the frame's centre), width, size (prompt, design px at
   * 1080p), choiceSize, label ('Pause and think'; '' for none), from (when it appears; default the
   * asking line's start), hold (fade out this many seconds after the reveal; 0 = stay), reveal,
   * reply, alpha}. -> {phase: '' | 'ask' | 'think' | 'reveal', left (countdown seconds), q}
   */
  // A choice's lines and size inside width w: words wrap (a path may also break after a slash or a
  // hyphen); while a word is wider than the box or it takes more than three lines, the type shrinks,
  // down to 0.6x or `floor` px (F.text's maxWidth shrinks a still wider word further: never clipped).
  function choiceFit(c, w, size, floor) {
    var o = { size: size, weight: 600 }, min = Math.min(size, Math.max(size * 0.6, floor || 0)), lines = [];
    var words = String(c).split(/\s+/).filter(Boolean).map(function (wd) { return wd.split(/(?<=[\/-])(?=[^\/-])/); });
    for (var pass = 0; pass < 12; pass++) {
      o.size = size;
      lines = [];
      var line = '', wide = false;
      words.forEach(function (segs) {
        segs.forEach(function (seg, si) {
          var test = line ? line + (si ? '' : ' ') + seg : seg;
          if (line && F.measure(test, o) > w) { lines.push(line); line = seg; } else line = test;
          if (F.measure(seg, o) > w) wide = true;
        });
      });
      lines.push(line);
      if ((!wide && lines.length <= 3) || size <= min) break;
      size = Math.max(min, size * 0.94);
    }
    return { lines: lines, size: size };
  }
  // the revealed answer's key: its letter is the palette's bg or ink, whichever reads better on pal.good,
  // pushed toward black or white until it clears 5.5:1 (4.5 plus room for grain and vignette); when no
  // push gets there (paper's mid green), the light one sits on the green darkened just enough
  function goodKey(pal) {
    var target = 5.5, good = pal.good;
    var cands = [pal.bg, pal.ink].sort(function (a, b) { return F.contrast(b, good) - F.contrast(a, good); });
    for (var i = 0; i < cands.length; i++) {
      var to = F.luminance(cands[i]) <= F.luminance(good) ? '#000000' : '#ffffff', c = cands[i];
      for (var t = 0.05; t <= 1.0001 && F.contrast(c, good) < target; t += 0.05) c = F.mixColor(cands[i], to, t);
      if (F.contrast(c, good) >= target) return { ink: c, fill: good };
    }
    var light = F.luminance(pal.bg) >= F.luminance(pal.ink) ? pal.bg : pal.ink, fill = good;
    for (var d = 0.05; d <= 1.0001 && F.contrast(light, fill) < target; d += 0.05) fill = F.mixColor(good, '#000000', d);
    return { ink: light, fill: fill };
  }
  F.questionBeat = function (T, q, o) {
    o = o || {};
    if (typeof q === 'string') {
      var qid = q;
      q = F.questions.filter(function (x) { return x.id === qid; })[0];
      if (!q) warnOnce('qb:' + qid, 'no question "' + qid + '" in showtime.json "questions"');
    }
    if (!q) return { phase: '', left: 0, q: null };
    var u = F.u, from = o.from !== undefined ? o.from : Math.min(q.from, q.t), R = q.resume, hold = o.hold || 0;
    var out = hold > 0 ? E.exit(clamp((T - R - hold) / 0.4)) : 0;
    var left = clamp(R - Math.max(T, q.t), 0, q.think);
    var phase = T < from || out >= 1 ? '' : T < q.t ? 'ask' : T < R ? 'think' : 'reveal';
    if (!phase) return { phase: phase, left: left, q: q };
    var g = S.g, pal = F.pal, n = q.choices.length, wide = F.W >= F.H;
    var W = o.width || Math.min(F.W * (wide ? 0.84 : 0.88), 1600 * u);
    var ps = (o.size || (wide ? 76 : 84)) * u, cs = (o.choiceSize || (wide ? 44 : 52)) * u;
    // upright, centred lines stay inside the phone safe zone (x 64-916 of 1080)
    var cw = wide ? W : Math.min(W, 2 * (F.W * 916 / 1080 - (o.x === undefined ? F.W / 2 : o.x)));
    var lines = F.wrap(q.prompt, cw, { size: ps, weight: 750 }), plh = ps * 1.12;
    var gap = 24 * u, bh0 = cs * 2.3, rr = 60 * u;
    var bw = wide ? Math.min((W - gap * (n - 1)) / n, 620 * u) : W;
    // each choice fits its own box: words wrap (a path after its slashes), then the type shrinks; the
    // box grows for a second or third line (a row of boxes shares the tallest)
    var k = bh0 * 0.56, kpad = bh0 * 0.22, tw = bw - kpad - k - cs * 1.1;
    var cx = o.x === undefined ? F.W / 2 : o.x;
    var x0 = wide ? cx - (n * bw + (n - 1) * gap) / 2 : cx - bw / 2;
    // upright: a long choice's text stays left of the phone apps' right-hand buttons (x < 916 of 1080)
    if (F.H > F.W) tw = Math.max(tw * 0.7, Math.min(tw, F.W * 916 / 1080 - (x0 + kpad + k + cs * 0.55)));
    // upright, the short side is the width: small type is held at the phone minimum (2.2% of the height)
    var floor = wide ? 0 : F.H * 0.0225;
    var fits = q.choices.map(function (c) { return choiceFit(c, tw, cs, floor); });
    var gk = goodKey(pal);
    var bhs = fits.map(function (f) { return Math.max(bh0, f.lines.length * f.size * 1.18 + cs * 1.15); });
    var bhMax = Math.max.apply(null, bhs);
    if (wide) bhs = bhs.map(function () { return bhMax; });
    var rowsH = wide ? bhMax : bhs.reduce(function (a, b) { return a + b; }, 0) + (n - 1) * gap;
    var total = lines.length * plh + 48 * u + rowsH + 56 * u + rr * 2;
    var y = (o.y === undefined ? F.H / 2 : o.y) - total / 2;
    var vis = clamp((T - from) / 0.3) * (1 - out) * (o.alpha === undefined ? 1 : o.alpha);
    g.save();
    g.globalAlpha *= vis;
    var a = E.reveal(clamp((T - from) / 0.5));
    lines.forEach(function (ln, i) {
      F.text(ln, cx, y + (i + 0.82) * plh + (1 - a) * 18 * u, { size: ps, weight: 750, align: 'center', alpha: a, color: pal.ink });
    });
    y += lines.length * plh + 48 * u;
    var shown = o.reveal !== false && T >= R, r = shown ? E.reveal(clamp((T - R) / 0.45)) : 0;
    q.choices.forEach(function (c, i) {
      var p = E.reveal(clamp((T - from - 0.25 - i * 0.07) / 0.45)), right = i === q.answer;
      var bh = bhs[i], bx = wide ? x0 + i * (bw + gap) : x0, by = y;
      if (!wide) for (var j = 0; j < i; j++) by += bhs[j] + gap;
      var alpha = p * (right ? 1 : lerp(1, 0.55, r)), on = right ? r : 0;
      g.save();
      g.globalAlpha *= alpha;
      g.translate(0, (1 - p) * 22 * u);
      F.box(bx, by, bw, bh, 18 * u, { fill: F.mixColor(pal.panel, pal.good, on * 0.22), stroke: F.mixColor(pal.line, pal.good, on), lineWidth: (2 + on * 2) * u });
      var kx = bx + kpad, f = fits[i], flh = f.size * 1.18;
      F.box(kx, by + (bh - k) / 2, k, k, 10 * u, { fill: on > 0.5 ? gk.fill : F.rgba(pal.ink, 0.1) });
      F.text(String.fromCharCode(65 + i), kx + k / 2, by + bh / 2, { size: Math.max(cs * 0.78, floor), weight: 750, align: 'center', baseline: 'middle', color: on > 0.5 ? gk.ink : pal.ink });
      f.lines.forEach(function (ln, li) {
        F.text(ln, kx + k + cs * 0.55, by + bh / 2 + (li - (f.lines.length - 1) / 2) * flh,
          { size: f.size, weight: 600, baseline: 'middle', color: pal.ink, maxWidth: tw });
      });
      g.restore();
    });
    y += rowsH + 56 * u;
    // the countdown: whole seconds left; the ring empties from the pause to the reveal
    var tIn = clamp((T - q.t + 0.2) / 0.3), tOut = clamp((T - R) / 0.3), ta = E.reveal(tIn) * (1 - tOut);
    var label = o.label === undefined ? 'Pause and think' : String(o.label), ls = Math.max(30 * u, floor);
    if (ta > 0) {
      var lw = label ? F.measure(label, { size: ls, weight: 600, tracking: 0.1 }) + 28 * u : 0;
      var rx = cx - lw / 2, ry = y + rr, sc = lerp(0.85, 1, E.smooth(tIn));
      g.save();
      g.globalAlpha *= ta;
      g.translate(rx, ry); g.scale(sc, sc); g.translate(-rx, -ry);
      g.lineCap = 'round'; g.lineWidth = 9 * u;
      g.strokeStyle = F.rgba(pal.ink, 0.16);
      g.beginPath(); g.arc(rx, ry, rr * 0.82, 0, Math.PI * 2); g.stroke();
      if (left > 0.001) {
        g.strokeStyle = pal.accent;
        g.beginPath(); g.arc(rx, ry, rr * 0.82, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * left / q.think); g.stroke();
      }
      F.text(String(Math.max(1, Math.ceil(left - 1e-6))), rx, ry, { size: rr * 0.95, weight: 750, align: 'center', baseline: 'middle', color: pal.ink });
      if (label) F.text(label.toUpperCase(), rx + rr + 28 * u, ry, { size: ls, weight: 600, tracking: 0.1, baseline: 'middle', color: pal.muted });
      g.restore();
    }
    var reply = o.reply === false ? '' : q.reply[q.answer] || '';
    if (shown && reply) {
      var rp = E.reveal(clamp((T - R - 0.25) / 0.5));
      F.paragraph(reply, cx, y + rr + 14 * u + (1 - rp) * 16 * u,   // where the countdown was
        { size: Math.max(40 * u, floor), width: wide ? W * 0.9 : cw, align: 'center', color: pal.ink, alpha: rp, lineHeight: 1.3 });
    }
    g.restore();
    return { phase: phase, left: left, q: q };
  };

  // @end questions
  // @part paths: pathUpTo catmull path
  /** Resample a polyline so progress is proportional to length. Returns [[x,y], ...] up to p. */
  function pathUpTo(pts, p, smooth) {
    var src = pts;
    if (smooth && pts.length > 2) src = catmull(pts, 12);
    var lens = [0], total = 0;
    for (var i = 1; i < src.length; i++) {
      total += Math.hypot(src[i][0] - src[i - 1][0], src[i][1] - src[i - 1][1]);
      lens.push(total);
    }
    var target = total * clamp(p), out = [src[0]];
    for (var j = 1; j < src.length; j++) {
      if (lens[j] <= target) { out.push(src[j]); continue; }
      var seg = lens[j] - lens[j - 1], f = seg > 0 ? (target - lens[j - 1]) / seg : 0;
      out.push([lerp(src[j - 1][0], src[j][0], f), lerp(src[j - 1][1], src[j][1], f)]);
      break;
    }
    return { pts: out, length: total };
  }
  function catmull(pts, steps) {
    var out = [];
    for (var i = 0; i < pts.length - 1; i++) {
      var p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
      for (var s = 0; s < steps; s++) {
        var t = s / steps, t2 = t * t, t3 = t2 * t;
        out.push([
          0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
          0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3),
        ]);
      }
    }
    out.push(pts[pts.length - 1]);
    return out;
  }
  F.pathUpTo = pathUpTo;
  /**
   * Draw a path of points up to progress p (by length). o: {smooth, color, width, dash, fill (area
   * color, closes to the baseline o.baseY), head (dot radius at the pen), alpha, glow}.
   * Returns the pen position [x, y].
   */
  F.path = function (points, p, o) {
    o = o || {};
    if (!points || points.length < 2) return null;
    var r = pathUpTo(points, p === undefined ? 1 : p, o.smooth);
    var pts = r.pts, g = S.g;
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    if (o.fill && pts.length > 1) {
      var base = o.baseY === undefined ? S.H : o.baseY;
      g.beginPath();
      g.moveTo(pts[0][0], base);
      pts.forEach(function (q) { g.lineTo(q[0], q[1]); });
      g.lineTo(pts[pts.length - 1][0], base);
      g.closePath();
      g.fillStyle = o.fill; g.fill();
    }
    g.strokeStyle = o.color || F.pal.accent;
    g.lineWidth = o.width || 4;
    g.lineCap = 'round'; g.lineJoin = 'round';
    if (o.dash) g.setLineDash(o.dash);
    if (o.glow) { g.shadowColor = o.color || F.pal.accent; g.shadowBlur = o.glow; }
    g.beginPath();
    pts.forEach(function (q, k) { if (k) g.lineTo(q[0], q[1]); else g.moveTo(q[0], q[1]); });
    g.stroke();
    var pen = pts[pts.length - 1];
    if (o.head && p > 0 && p < 1.0001) {
      g.shadowBlur = 0;
      F.circle(pen[0], pen[1], o.head, { fill: o.color || F.pal.accent });
    }
    g.restore();
    return pen;
  };

  // @end paths
  // @part particles: burst field
  // ================================================================== particles
  /**
   * One-shot burst (closed form, seek-safe). age = seconds since the burst.
   * o: {x, y, count, seed, speed: [min, max], angle (rad, default up), spread (rad), gravity,
   * life, size, colors, shape: 'circle'|'rect'|'spark'}.
   */
  F.burst = function (age, o) {
    o = o || {};
    if (!(age >= 0)) return;
    var n = o.count || 28, life = o.life || 1.2;
    if (age > life * 1.3) return;
    var g = S.g, r = rng(o.seed || 7);
    var sp = o.speed || [300, 800], ang = o.angle === undefined ? -Math.PI / 2 : o.angle, spread = o.spread === undefined ? Math.PI * 2 : o.spread;
    var grav = o.gravity === undefined ? 1200 : o.gravity, colors = o.colors || [F.pal.accent, F.pal.accent2, F.pal.accent3, F.pal.ink];
    g.save();
    for (var i = 0; i < n; i++) {
      var a = ang + (r() - 0.5) * spread, v = lerp(sp[0], sp[1], r()), l = life * lerp(0.6, 1.2, r());
      var col = colors[Math.floor(r() * colors.length)], sz = (o.size || 9) * lerp(0.5, 1.2, r()), spin = (r() - 0.5) * 14;
      if (age > l) continue;
      var drag = 1 - Math.exp(-age * 2.2);
      var x = o.x + Math.cos(a) * v * drag / 2.2, y = o.y + Math.sin(a) * v * drag / 2.2 + 0.5 * grav * age * age * 0.35;
      var fade = 1 - smoothstep(l * 0.6, l, age);
      g.globalAlpha = fade * (o.alpha === undefined ? 1 : o.alpha);
      g.fillStyle = col;
      if (o.shape === 'rect') {
        g.save(); g.translate(x, y); g.rotate(spin * age); g.fillRect(-sz / 2, -sz / 4, sz, sz / 2); g.restore();
      } else if (o.shape === 'spark') {
        g.strokeStyle = col; g.lineWidth = sz * 0.3; g.lineCap = 'round';
        var vx = Math.cos(a) * v * Math.exp(-age * 2.2), vy = Math.sin(a) * v * Math.exp(-age * 2.2) + grav * age * 0.35;
        var k = 0.03;
        g.beginPath(); g.moveTo(x, y); g.lineTo(x - vx * k, y - vy * k); g.stroke();
      } else {
        g.beginPath(); g.arc(x, y, sz / 2, 0, Math.PI * 2); g.fill();
      }
    }
    g.restore();
  };
  /**
   * Ambient drifting particles (closed form, wraps around the rect).
   * o: {count, seed, rect, speed ([vx, vy] px/s), size, color, alpha, twinkle}.
   */
  F.field = function (T, o) {
    o = o || {};
    var g = S.g, rc = o.rect || { x: 0, y: 0, w: S.W, h: S.H }, r = rng(o.seed || 3);
    var n = o.count || 60, v = o.speed || [0, -14], col = o.color || F.pal.ink;
    g.save();
    g.fillStyle = col;
    for (var i = 0; i < n; i++) {
      var x0 = r() * rc.w, y0 = r() * rc.h, sp = lerp(0.4, 1.4, r()), sz = (o.size || 2.2) * lerp(0.5, 1.4, r()), ph = r() * 10;
      var x = rc.x + mod(x0 + v[0] * sp * T + noise(T * 0.3 + ph, i) * 20, rc.w);
      var y = rc.y + mod(y0 + v[1] * sp * T + noise(T * 0.25 + ph, i + 99) * 20, rc.h);
      var tw = o.twinkle ? 0.5 + 0.5 * Math.sin(T * 2.2 + ph * 3) : 1;
      g.globalAlpha = (o.alpha === undefined ? 0.35 : o.alpha) * tw;
      g.beginPath(); g.arc(x, y, sz, 0, Math.PI * 2); g.fill();
    }
    g.restore();
  };

  // @end particles
  // @part charts: bars lineChart ring
  // ================================================================== charts
  /**
   * Bar chart inside rect {x, y, w, h}. data: numbers. p: 0..1 growth (staggered).
   * o: {labels, max, colors, color, highlight (index), gap (0..1), radius, values (true|fn),
   * decimals, prefix, suffix, labelSize, valueSize, baseline (bool), horizontal}.
   */
  F.bars = function (data, rect, p, o) {
    o = o || {};
    var g = S.g, n = data.length, max = o.max || Math.max.apply(null, data.concat([1e-9]));
    var gap = o.gap === undefined ? 0.28 : o.gap, horiz = !!o.horizontal;
    var labelSize = o.labelSize || 24, valueSize = o.valueSize || 28;
    var span = horiz ? rect.h : rect.w, slot = span / n, bw = slot * (1 - gap);
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    if (o.baseline !== false) {
      if (horiz) F.line(rect.x, rect.y, rect.x, rect.y + rect.h, { color: F.pal.line, width: 2 });
      else F.line(rect.x, rect.y + rect.h, rect.x + rect.w, rect.y + rect.h, { color: F.pal.line, width: 2 });
    }
    for (var i = 0; i < n; i++) {
      var q = E.outCubic(F.split(p, i, n, Math.min(0.08, 0.4 / Math.max(1, n - 1))));
      var hl = o.highlight === undefined ? true : (o.highlight === i || (Array.isArray(o.highlight) && o.highlight.indexOf(i) >= 0));
      var col = (o.colors && o.colors[i]) || (hl ? (o.color || F.pal.accent) : F.rgba(F.pal.muted, 0.45));
      var frac = clamp(data[i] / max) * q, r = o.radius === undefined ? Math.min(10, bw / 4) : o.radius;
      var bx, by, bwid, bh;
      if (horiz) {
        bx = rect.x; by = rect.y + i * slot + (slot - bw) / 2; bwid = rect.w * frac; bh = bw;
        if (bwid > 0.5) F.box(bx, by, bwid, bh, [0, r, r, 0], { fill: col });
      } else {
        bh = rect.h * frac; bx = rect.x + i * slot + (slot - bw) / 2; by = rect.y + rect.h - bh; bwid = bw;
        if (bh > 0.5) F.box(bx, by, bwid, bh, [r, r, 0, 0], { fill: col });
      }
      if (o.labels && o.labels[i] !== undefined) {
        if (horiz) F.text(o.labels[i], rect.x - 14, by + bh / 2, { size: labelSize, align: 'right', baseline: 'middle', color: F.pal.muted, weight: 500 });
        else F.text(o.labels[i], bx + bw / 2, rect.y + rect.h + labelSize * 1.5, { size: labelSize, align: 'center', color: F.pal.muted, weight: 500 });
      }
      if (o.values !== false && q > 0.05) {
        var val = data[i] * q;
        var s = typeof o.values === 'function' ? o.values(val, i) : (o.prefix || '') + formatNumber(val, o.decimals || 0, ',') + (o.suffix || '');
        var va = clamp((q - 0.2) / 0.5);
        if (horiz) F.text(s, bx + bwid + 12, by + bh / 2, { size: valueSize, weight: 700, baseline: 'middle', color: hl ? F.pal.ink : F.pal.muted, alpha: va });
        else F.text(s, bx + bw / 2, by - valueSize * 0.5, { size: valueSize, weight: 700, align: 'center', color: hl ? F.pal.ink : F.pal.muted, alpha: va });
      }
    }
    g.restore();
  };
  /**
   * Line chart in rect. series: [numbers] or [[numbers], ...]. p: draw progress.
   * o: {min, max, colors, width, fill (bool), dots, grid (count of guide lines), labels (x),
   * highlight (series index; others muted), endLabel (fn(v, i) | true), smooth}.
   * Returns the pen positions of every series.
   */
  F.lineChart = function (series, rect, p, o) {
    o = o || {};
    if (!Array.isArray(series[0])) series = [series];
    var all = [].concat.apply([], series);
    var mn = o.min === undefined ? Math.min.apply(null, all) : o.min, mx = o.max === undefined ? Math.max.apply(null, all) : o.max;
    if (mx === mn) mx = mn + 1;
    var g = S.g, pens = [];
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    var gl = o.grid === undefined ? 3 : o.grid;
    for (var k = 0; k <= gl && gl > 0; k++) {
      var gy = rect.y + rect.h * k / gl;
      F.line(rect.x, gy, rect.x + rect.w, gy, { color: F.pal.line, width: k === gl ? 2 : 1, alpha: clamp(p * 3) });
    }
    if (o.labels) {
      o.labels.forEach(function (lb, i) {
        var lx = rect.x + rect.w * i / Math.max(1, o.labels.length - 1);
        F.text(lb, lx, rect.y + rect.h + (o.labelSize || 22) * 1.6, { size: o.labelSize || 22, align: 'center', color: F.pal.muted, alpha: clamp(p * 3) });
      });
    }
    series.forEach(function (s, si) {
      var hl = o.highlight === undefined || o.highlight === si;
      var col = (o.colors && o.colors[si]) || (hl ? [F.pal.accent, F.pal.accent2, F.pal.accent3][si % 3] : F.rgba(F.pal.muted, 0.5));
      var pts = s.map(function (v, i) {
        return [rect.x + rect.w * i / Math.max(1, s.length - 1), rect.y + rect.h * (1 - (v - mn) / (mx - mn))];
      });
      var pen = F.path(pts, p, {
        color: col, width: o.width || (hl ? 5 : 3), smooth: o.smooth !== false, head: o.dots === false ? 0 : 7,
        fill: o.fill && hl ? F.rgba(col, 0.14) : null, baseY: rect.y + rect.h,
      });
      pens.push(pen);
      if (o.endLabel && pen && hl) {
        var idx = Math.min(s.length - 1, Math.round(p * (s.length - 1)));
        var lab = typeof o.endLabel === 'function' ? o.endLabel(s[idx], idx) : formatNumber(s[idx], o.decimals || 0, ',');
        F.text(lab, pen[0] + 14, pen[1] - 12, { size: o.valueSize || 28, weight: 700, color: col });
      }
    });
    g.restore();
    return pens;
  };
  /** Donut/ring progress at (x, y). frac 0..1 (already animated), o: {width, color, track, label}. */
  F.ring = function (x, y, radius, frac, o) {
    o = o || {};
    var g = S.g, w = o.width || radius * 0.18;
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    g.lineCap = 'round'; g.lineWidth = w;
    g.strokeStyle = o.track || F.rgba(F.pal.muted, 0.2);
    g.beginPath(); g.arc(x, y, radius, 0, Math.PI * 2); g.stroke();
    if (frac > 0.001) {
      g.strokeStyle = o.color || F.pal.accent;
      g.beginPath(); g.arc(x, y, radius, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * clamp(frac)); g.stroke();
    }
    g.restore();
    if (o.label !== undefined) F.text(o.label, x, y, { size: o.labelSize || radius * 0.5, weight: 700, align: 'center', baseline: 'middle', color: o.labelColor || F.pal.ink });
  };

  // @end charts
  // @part devices: clipContent browser phone laptop
  // ================================================================== frames (device / browser)
  function clipContent(x, y, w, h, r, content) {
    if (!content) return;
    var g = S.g;
    g.save();
    F.rr(x, y, w, h, r);
    g.clip();
    g.translate(x, y);
    content(g, w, h);
    g.restore();
  }
  /**
   * Browser window. rect {x, y, w, h}; o: {url, title, theme ('light'|'dark'), radius, shadow, bar (px)}.
   * content(g, w, h) draws in local coordinates (0,0 = top-left of the page area), clipped.
   * Returns the page rect in design coordinates.
   */
  F.browser = function (rect, o, content) {
    o = o || {};
    var dark = o.theme ? o.theme === 'dark' : F.luminance(F.pal.bg) < 0.4;
    var r = o.radius === undefined ? 14 : o.radius, bar = o.bar || Math.max(36, rect.w * 0.034);
    var chrome = dark ? '#1f2229' : '#eceef1', page = o.page || (dark ? '#111318' : '#ffffff');
    var g = S.g;
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    F.box(rect.x, rect.y, rect.w, rect.h, r, { fill: chrome, shadow: o.shadow === undefined ? { blur: 60, y: 24, color: 'rgba(0,0,0,0.35)' } : o.shadow });
    var border = o.border === undefined ? (dark ? 'rgba(255,255,255,0.12)' : 'rgba(0,0,0,0.10)') : o.border;
    var dots = ['#ff5f57', '#febc2e', '#28c840'];
    for (var i = 0; i < 3; i++) F.circle(rect.x + bar * 0.5 + i * bar * 0.42, rect.y + bar / 2, bar * 0.13, { fill: dots[i] });
    if (o.url !== false) {
      var uw = Math.min(rect.w * 0.5, rect.w - bar * 4);
      F.box(rect.x + rect.w / 2 - uw / 2, rect.y + bar * 0.2, uw, bar * 0.6, bar * 0.3, { fill: dark ? '#2b2f38' : '#ffffff' });
      F.text(o.url || 'localhost:3000', rect.x + rect.w / 2, rect.y + bar / 2 + 1, { size: bar * 0.34, align: 'center', baseline: 'middle', color: dark ? '#a3a9b5' : '#5f6673' });
    }
    var inner = { x: rect.x, y: rect.y + bar, w: rect.w, h: rect.h - bar };
    F.box(inner.x, inner.y, inner.w, inner.h, [0, 0, r, r], { fill: page });
    clipContent(inner.x, inner.y, inner.w, inner.h, [0, 0, r, r], content);
    if (border) F.box(rect.x, rect.y, rect.w, rect.h, r, { stroke: border, lineWidth: o.borderWidth || 1.5 });
    g.restore();
    return inner;
  };
  /** Phone. rect {x, y, w, h} (w:h about 9:19.5). o: {color, screen, radius}. content(g, w, h). */
  F.phone = function (rect, o, content) {
    o = o || {};
    var g = S.g, r = o.radius || rect.w * 0.16, bez = rect.w * 0.035;
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    F.box(rect.x, rect.y, rect.w, rect.h, r, { fill: o.color || '#0d0e11', stroke: 'rgba(255,255,255,0.18)', lineWidth: 2, shadow: { blur: 60, y: 28, color: 'rgba(0,0,0,0.4)' } });
    var s = { x: rect.x + bez, y: rect.y + bez, w: rect.w - bez * 2, h: rect.h - bez * 2 };
    F.box(s.x, s.y, s.w, s.h, r - bez, { fill: o.screen || '#ffffff' });
    clipContent(s.x, s.y, s.w, s.h, r - bez, content);
    F.box(rect.x + rect.w / 2 - rect.w * 0.15, s.y + rect.w * 0.03, rect.w * 0.3, rect.w * 0.085, rect.w * 0.05, { fill: '#000' });
    g.restore();
    return s;
  };
  /** Laptop: screen with bezel + base. rect is the whole device. content(g, w, h). */
  F.laptop = function (rect, o, content) {
    o = o || {};
    var g = S.g, baseH = rect.h * 0.06, sh = rect.h - baseH, inset = rect.w * 0.06;
    var scr = { x: rect.x + inset, y: rect.y, w: rect.w - inset * 2, h: sh };
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    F.box(scr.x, scr.y, scr.w, scr.h, scr.w * 0.025, { fill: o.color || '#16181d', shadow: { blur: 50, y: 20, color: 'rgba(0,0,0,0.35)' } });
    var b = scr.w * 0.022;
    var s = { x: scr.x + b, y: scr.y + b, w: scr.w - b * 2, h: scr.h - b * 1.6 };
    F.box(s.x, s.y, s.w, s.h, 4, { fill: o.screen || '#ffffff' });
    clipContent(s.x, s.y, s.w, s.h, 4, content);
    g.beginPath();
    g.moveTo(rect.x, rect.y + sh); g.lineTo(rect.x + rect.w, rect.y + sh);
    g.lineTo(rect.x + rect.w - inset * 0.3, rect.y + rect.h); g.lineTo(rect.x + inset * 0.3, rect.y + rect.h); g.closePath();
    g.fillStyle = o.base || '#c9ccd3'; g.fill();
    F.box(rect.x + rect.w / 2 - rect.w * 0.08, rect.y + sh, rect.w * 0.16, baseH * 0.35, [0, 0, 8, 8], { fill: 'rgba(0,0,0,0.18)' });
    g.restore();
    return s;
  };

  // @end devices
  // ================================================================== images
  var IMAGES = {};
  /**
   * Load an image once (cached by src). Returns a handle {img, ready, w, h, src}.
   * Call at setup (or list them in Film.start({images})) so the first frame has them.
   */
  F.image = function (src) {
    if (IMAGES[src]) return IMAGES[src];
    var h = { src: src, ready: false, w: 0, h: 0, img: null };
    IMAGES[src] = h;
    if (typeof Image === 'undefined') return h;
    var img = new Image();
    img.decoding = 'sync';
    h.img = img;
    var p = new Promise(function (resolve) {
      img.onload = function () {
        var done = function () { h.ready = true; h.w = img.naturalWidth; h.h = img.naturalHeight; resolve(h); };
        if (img.decode) img.decode().then(done, done); else done();
      };
      img.onerror = function () {
        warnOnce('img:' + src, 'image failed to load: ' + src);
        resolve(h);
      };
    });
    img.src = src;
    h.promise = p;
    if (S.framesDrawn > 0) {
      warnOnce('late:' + src, 'image "' + src + '" was first requested while drawing; list it in ' +
        'Film.start({images}) or call Film.image() at setup so the renderer waits for it');
    } else if (root.ST && typeof root.ST.waitFor === 'function') {
      try { root.ST.waitFor(p, 'image ' + src); } catch (e) { /* ignore */ }
    }
    return h;
  };
  /** Named images passed to Film.start({images: {logo: 'logo.png'}}) -> F.img.logo */
  F.img = {};
  /**
   * Draw an image into a box. o: {fit: 'cover'|'contain'|'fill', align: [0.5, 0.5], zoom, pan: [dx, dy]
   * (fractions of the box), radius, alpha, shadow}.
   */
  F.drawImage = function (im, x, y, w, h, o) {
    o = o || {};
    if (typeof im === 'string') im = F.img[im] || F.image(im);
    if (!im || !im.ready) { warnOnce('notready:' + (im && im.src), 'image not ready: ' + (im && im.src)); return; }
    var g = S.g, iw = im.w, ih = im.h, fit = o.fit || 'cover', al = o.align || [0.5, 0.5];
    var sc = fit === 'contain' ? Math.min(w / iw, h / ih) : fit === 'fill' ? 1 : Math.max(w / iw, h / ih);
    var dw = fit === 'fill' ? w : iw * sc, dh = fit === 'fill' ? h : ih * sc;
    var z = o.zoom || 1;
    dw *= z; dh *= z;
    var pan = o.pan || [0, 0];
    var dx = x + (w - dw) * al[0] + pan[0] * w, dy = y + (h - dh) * al[1] + pan[1] * h;
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    if (o.shadow) { applyShadow(o.shadow); F.rr(x, y, w, h, o.radius || 0); g.fillStyle = '#000'; g.fill(); g.shadowColor = 'transparent'; }
    F.rr(x, y, w, h, o.radius || 0);
    g.clip();
    g.imageSmoothingQuality = 'high';
    g.drawImage(im.img, dx, dy, dw, dh);
    g.restore();
  };
  /** Ken Burns move: F.kenBurns(img, rect, p, {from: {zoom: 1, pan: [0,0]}, to: {zoom: 1.15, pan: [-0.03, 0.02]}}). */
  F.kenBurns = function (im, rect, p, o) {
    o = o || {};
    var a = o.from || { zoom: 1, pan: [0, 0] }, b = o.to || { zoom: 1.12, pan: [-0.02, -0.015] };
    var q = easeFn(o.ease || 'inOutSine')(clamp(p));
    F.drawImage(im, rect.x, rect.y, rect.w, rect.h, Object.assign({}, o, {
      zoom: lerp(a.zoom || 1, b.zoom || 1, q),
      pan: [lerp((a.pan || [0, 0])[0], (b.pan || [0, 0])[0], q), lerp((a.pan || [0, 0])[1], (b.pan || [0, 0])[1], q)],
    }));
  };

  // ================================================================== camera
  /**
   * Camera from keyframes: [[t, x, y, zoom, ease?], ...] where (x, y) is the design point at the
   * centre of the frame. Zoom interpolates geometrically. Optional 6th value: rotation (rad).
   * With o.ui (F.rects) a key can name its target: [t, 'saveBtn', zoom?, ease?] centres that rect
   * (zoom omitted: framed with F.focus). o.clamp: true keeps the view inside the design frame, a
   * rect (or a ui name) keeps it inside that rect, e.g. the app window: never a sliver of backdrop.
   */
  F.camera = function (T, keys, o) {
    o = o || {};
    var def = { x: S.W / 2, y: S.H / 2, zoom: 1, rot: 0 };
    if (!keys || !keys.length) return def;
    var cam = null;
    function k2c(k) {
      if (typeof k[1] === 'string') {
        if (!o.ui) throw new Error('Film.camera: key "' + k[1] + '" names a rect: pass {ui: Film.rects(...)}');
        var r = o.ui.rect(k[1]), f = F.focus(r, { clamp: false, pad: o.pad });
        return { x: f.x, y: f.y, zoom: typeof k[2] === 'number' ? k[2] : f.zoom, rot: k[5] || 0 };
      }
      return { x: k[1], y: k[2], zoom: k[3] === undefined ? 1 : k[3], rot: k[5] || 0 };
    }
    function easeOf(k) { return typeof k[1] === 'string' ? k[3] : k[4]; }
    if (T <= keys[0][0]) cam = k2c(keys[0]);
    for (var i = 1; !cam && i < keys.length; i++) {
      if (T <= keys[i][0]) {
        var a = k2c(keys[i - 1]), b = k2c(keys[i]);
        var e = easeFn(easeOf(keys[i]) || 'camera')(clamp((T - keys[i - 1][0]) / Math.max(1e-9, keys[i][0] - keys[i - 1][0])));
        cam = { x: lerp(a.x, b.x, e), y: lerp(a.y, b.y, e), zoom: a.zoom * Math.pow(b.zoom / a.zoom, e), rot: lerp(a.rot, b.rot, e) };
      }
    }
    if (!cam) cam = k2c(keys[keys.length - 1]);
    if (o.clamp) cam = clampCam(cam, o.clamp === true ? null : (typeof o.clamp === 'string' ? o.ui.rect(o.clamp) : o.clamp));
    return cam;
  };
  /** Deterministic handheld shake: {x, y, rot}. amp in px, freq in Hz. */
  F.shake = function (T, amp, o) {
    o = o || {};
    var f = o.freq || 1.3, s = o.seed || 1;
    return {
      x: (noise(T * f, s) * 0.7 + noise(T * f * 2.7, s + 5) * 0.3) * amp,
      y: (noise(T * f, s + 11) * 0.7 + noise(T * f * 2.3, s + 17) * 0.3) * amp,
      rot: noise(T * f * 0.8, s + 23) * (o.rot === undefined ? amp * 0.0006 : o.rot),
    };
  };
  /** Camera that frames a rect {x, y, w, h}: o {pad (fraction, default 0.15), maxZoom, clamp: true}. */
  F.focus = function (rect, o) {
    o = o || {};
    var pad = o.pad === undefined ? 0.15 : o.pad;
    var z = Math.min(S.W / (rect.w * (1 + pad * 2)), S.H / (rect.h * (1 + pad * 2)));
    z = Math.min(z, o.maxZoom || 2.8);
    if (o.minZoom) z = Math.max(z, o.minZoom);
    var cam = { x: rect.x + rect.w / 2, y: rect.y + rect.h / 2, zoom: z, rot: 0 };
    return o.clamp === false ? cam : clampCam(cam);
  };
  /**
   * Keep the view inside bounds (default: the design frame) so the camera never shows what lies
   * outside it. A view larger than the bounds is centred on them.
   */
  function clampCam(cam, bounds) {
    var b = bounds ? (Array.isArray(bounds) ? { x: bounds[0], y: bounds[1], w: bounds[2], h: bounds[3] } : bounds) : null;
    if (!b && cam.zoom < 1) return cam;
    b = b || { x: 0, y: 0, w: S.W, h: S.H };
    var hw = S.W / (2 * cam.zoom), hh = S.H / (2 * cam.zoom);
    var x = b.w <= hw * 2 ? b.x + b.w / 2 : clamp(cam.x, b.x + hw, b.x + b.w - hw);
    var y = b.h <= hh * 2 ? b.y + b.h / 2 : clamp(cam.y, b.y + hh, b.y + b.h - hh);
    return { x: x, y: y, zoom: cam.zoom, rot: cam.rot || 0 };
  }
  F.clampCam = clampCam;
  /** Draw fn() through a camera ({x, y, zoom, rot}); optional o.shake {x, y, rot} added. */
  F.withCamera = function (cam, fn, o) {
    var g = S.g, sh = (o && o.shake) || { x: 0, y: 0, rot: 0 };
    g.save();
    g.translate(S.W / 2 + sh.x, S.H / 2 + sh.y);
    g.scale(cam.zoom, cam.zoom);
    g.rotate((cam.rot || 0) + (sh.rot || 0));
    g.translate(-cam.x, -cam.y);
    var prevZoom = S.camZoom || 1;
    S.camZoom = prevZoom * (cam.zoom || 1);   // recorded on texts for QA (cropped by the camera on purpose)
    try { fn(); } finally { g.restore(); S.camZoom = prevZoom; }
  };
  /** Where a world point lands on screen (design coords) through a camera. */
  F.camPoint = function (cam, x, y) {
    var c = Math.cos(cam.rot || 0), s = Math.sin(cam.rot || 0), dx = (x - cam.x) * cam.zoom, dy = (y - cam.y) * cam.zoom;
    return [S.W / 2 + dx * c - dy * s, S.H / 2 + dx * s + dy * c];
  };

  // @part tutorial: cursorPath clickZoom stepTitle stepBar caption captions stepBand rects namedKeys fold stateAt
  // ================================================================== tutorial helpers
  /**
   * Cursor path. keys: [[t, x, y, {click, move, pre}], ...]: the pointer ARRIVES by t - pre
   * (pre = 0.12 s for clicks) and clicks exactly at t, so click sounds use the same t.
   * Moves take `move` seconds (default from distance) along a gentle arc.
   * Returns {x, y, press (0..1), clickAge (s since the last click, Infinity if none), click: {x, y, t}}.
   * With o.ui (F.rects) a key can name its target: [t, 'saveBtn', {click: true, at: 'center' | 'left'
   * | [fx, fy], dx, dy}], so the pointer lands on the UI element wherever the layout puts it.
   */
  F.cursorPath = function (T, keys, o) {
    if (keys && o && o.ui) keys = F.namedKeys(keys, o.ui);
    if (!keys || !keys.length) return { x: S.W / 2, y: S.H / 2, press: 0, clickAge: Infinity, click: null };
    var x = keys[0][1], y = keys[0][2], lastClick = null;
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i], opt = k[3] || {};
      var pre = opt.pre === undefined ? (opt.click ? 0.12 : 0) : opt.pre;
      var arrive = k[0] - pre;
      if (i > 0) {
        var d = Math.hypot(k[1] - x, k[2] - y);
        var dur = opt.move || clamp(0.35 + d / 1800, 0.35, 0.95);
        var start = arrive - dur;
        if (T < start) break;
        if (T < arrive) {
          var q = E.inOutCubic((T - start) / dur);
          var ax = k[1] - x, ay = k[2] - y, bend = (opt.arc === undefined ? 0.08 : opt.arc);
          var ox = -ay * bend * Math.sin(Math.PI * q), oy = ax * bend * Math.sin(Math.PI * q);
          x = lerp(x, k[1], q) + ox; y = lerp(y, k[2], q) + oy;
          break;
        }
      }
      x = k[1]; y = k[2];
      if (opt.click && T >= k[0]) lastClick = { x: k[1], y: k[2], t: k[0] };
      if (T < k[0]) break;
    }
    var age = lastClick ? T - lastClick.t : Infinity;
    var press = 0;
    // press dips before and releases after each click
    for (var j = 0; j < keys.length; j++) {
      var kk = keys[j];
      if (!(kk[3] && kk[3].click)) continue;
      var dt = T - kk[0];
      if (dt > -0.08 && dt < 0.14) press = Math.max(press, dt < 0 ? 1 + dt / 0.08 : 1 - dt / 0.14);
    }
    return { x: x, y: y, press: clamp(press), clickAge: age, click: lastClick };
  };
  /**
   * Auto camera that zooms to each click and back out. clicks: [{t, x, y, zoom?}] or [[t, x, y, zoom]].
   * o: {zoom (1.8), lead (0.45 s before the click the zoom is complete), hold (1.4 s), base
   * ({x, y, zoom}), merge (1.6 s: closer clicks pan instead of zooming out)}.
   */
  F.clickZoom = function (T, clicks, o) {
    o = o || {};
    var base = o.base || { x: S.W / 2, y: S.H / 2, zoom: 1 };
    var list = (clicks || []).map(function (c) {
      return Array.isArray(c) ? { t: c[0], x: c[1], y: c[2], zoom: c[3] } : c;
    }).sort(function (a, b) { return a.t - b.t; });
    var keys = [[-1e9, base.x, base.y, base.zoom]];
    var lead = o.lead === undefined ? 0.45 : o.lead, hold = o.hold === undefined ? 1.4 : o.hold, merge = o.merge === undefined ? 1.6 : o.merge;
    for (var i = 0; i < list.length; i++) {
      var c = list[i], z = c.zoom || o.zoom || 1.8;
      var inDur = 0.6 + 0.55 * Math.log(Math.max(1.01, z));
      var f = clampCam({ x: c.x, y: c.y, zoom: z });
      var prev = list[i - 1];
      var merged = prev && c.t - prev.t < merge + hold;
      if (merged) {
        keys.pop(); keys.pop(); // drop the previous zoom-out
        keys.push([Math.max(prev.t + 0.2, c.t - lead - 0.6), keys[keys.length - 1][1], keys[keys.length - 1][2], keys[keys.length - 1][3]]);
        keys.push([c.t - lead, f.x, f.y, f.zoom]);
      } else {
        keys.push([c.t - lead - inDur, base.x, base.y, base.zoom]);
        keys.push([c.t - lead, f.x, f.y, f.zoom]);
      }
      var outDur = inDur * 0.9;
      keys.push([c.t + hold, f.x, f.y, f.zoom]);
      keys.push([c.t + hold + outDur, base.x, base.y, base.zoom]);
    }
    keys.sort(function (a, b) { return a[0] - b[0]; });
    return F.camera(T, keys);
  };
  /**
   * Step title card (top-left by default): big step number + title (+ sub). p: visibility (0..1),
   * e.g. F.win(T, 3, 7, 0.4). o: {x, y, size, sub, color}.
   */
  F.stepTitle = function (n, title, p, o) {
    o = o || {};
    if (p <= 0) return;
    var g = S.g, size = o.size || 44, x = o.x === undefined ? 90 : o.x, y = o.y === undefined ? 110 : o.y;
    var q = E.reveal(clamp(p));
    g.save();
    g.globalAlpha *= clamp(p * 1.4);
    g.translate((1 - q) * -30, 0);
    var badge = size * 1.35;
    F.box(x, y - badge * 0.72, badge, badge, badge * 0.3, { fill: o.color || F.pal.accent });
    F.text(String(n), x + badge / 2, y - badge * 0.72 + badge / 2 + size * 0.03, { size: size * 0.8, weight: 800, align: 'center', baseline: 'middle', color: o.badgeText || F.pal.bg });
    F.text(title, x + badge + size * 0.45, y, { size: size, weight: 750, color: F.pal.ink, shadow: o.shadow });
    if (o.sub) F.text(o.sub, x + badge + size * 0.45, y + size * 1.1, { size: size * 0.55, weight: 450, color: F.pal.muted });
    g.restore();
  };
  /**
   * Progress bar of steps. steps: count or labels array; current: step index (float allowed:
   * 1.5 = halfway from step 1 to 2). o: {x, y, w, size, alpha}.
   */
  F.stepBar = function (steps, current, o) {
    o = o || {};
    var labels = Array.isArray(steps) ? steps : null, n = labels ? labels.length : steps;
    var w = o.w || S.W * 0.5, x = o.x === undefined ? (S.W - w) / 2 : o.x, y = o.y === undefined ? S.H - 70 : o.y;
    var size = o.size || 20, g = S.g;
    g.save();
    g.globalAlpha *= (o.alpha === undefined ? 1 : o.alpha);
    var segW = w / n, gap = Math.min(10, segW * 0.1);
    for (var i = 0; i < n; i++) {
      var sx = x + i * segW + gap / 2, sw = segW - gap;
      F.box(sx, y, sw, size * 0.32, size * 0.16, { fill: F.rgba(F.pal.muted, 0.25) });
      var f = clamp(current - i);
      if (f > 0) F.box(sx, y, sw * f, size * 0.32, size * 0.16, { fill: F.pal.accent });
      if (labels) {
        F.text(labels[i], sx, y - size * 0.6, { size: size, weight: current >= i && current < i + 1 ? 700 : 500, color: current >= i ? F.pal.ink : F.pal.muted, maxWidth: sw });
      }
    }
    g.restore();
  };
  /** Lower-third caption box. p: visibility. o: {y, size, maxWidth, fill, color}. */
  F.caption = function (text, p, o) {
    o = o || {};
    if (p <= 0) return;
    var g = S.g, size = o.size || 36, mw = o.maxWidth || S.W * 0.7;
    var lines = F.wrap(text, mw, { size: size, weight: 550 });
    var lh = size * 1.3, h = lines.length * lh + size * 0.9;
    var w = Math.max.apply(null, lines.map(function (l) { return F.measure(l, { size: size, weight: 550 }); })) + size * 1.4;
    var y = o.y === undefined ? S.H * 0.84 : o.y;
    g.save();
    g.globalAlpha *= clamp(p);
    g.translate(0, (1 - E.outCubic(clamp(p))) * 16);
    F.box(S.W / 2 - w / 2, y - h / 2, w, h, size * 0.45, { fill: o.fill || 'rgba(10,11,14,0.78)' });
    recordCover('caption', text, S.W / 2 - w / 2, y - h / 2, w, h, g);
    lines.forEach(function (l, i) {
      F.text(l, S.W / 2, y - h / 2 + size * 0.45 + lh * i + size * 0.95, { size: size, weight: 550, align: 'center', color: o.color || '#ffffff' });
    });
    g.restore();
  };

  // ------------------------------------------------------------------ named UI rects
  function toRect(r) {
    if (!r) return null;
    if (Array.isArray(r)) return { x: +r[0], y: +r[1], w: +(r[2] || 0), h: +(r[3] || 0) };
    return { x: +r.x, y: +r.y, w: +(r.w || 0), h: +(r.h || 0), r: r.r };
  }
  /**
   * Named hit-rects for a UI drawn in the film, so cursors, cameras, spotlights and callouts target
   * UI by name ("the Save button", "row 3") instead of by numbers copied around:
   *   var ui = Film.rects({
   *     save: [1240, 34, 220, 58],                                   // x, y, w, h in page coordinates
   *     row: function (i) { return [320, 400 + i * 86, 1140, 66]; }, // a family: ui.rect('row', 2) or 'row:2'
   *   }, { origin: [210, 186] });                                    // page -> world (a window's content area)
   * ui.rect(name, ...args) {x, y, w, h} in world (design) coordinates; ui.local(name) in page ones;
   * ui.center(name); ui.point(name, 'right' | 'left' | 'top' | 'bottom' | 'tl' | 'tr' | 'bl' | 'br' | [fx, fy]);
   * ui.add(name, rect); ui.names(). Unknown names throw (a typo should fail loudly, not aim at 0,0).
   */
  F.rects = function (defs, o) {
    o = o || {};
    var table = {};
    for (var k in defs) table[k] = defs[k];
    var ox = o.origin ? o.origin[0] : 0, oy = o.origin ? o.origin[1] : 0, sc = o.scale || 1;
    function parse(name, args) {
      var m = /^([^:]+):(.*)$/.exec(String(name));
      if (m && args.length === 0) return { name: m[1], args: m[2].split(',').map(function (x) { return isNaN(+x) ? x : +x; }) };
      return { name: String(name), args: args };
    }
    function local(name) {
      var q = parse(name, Array.prototype.slice.call(arguments, 1)), d = table[q.name];
      if (d === undefined) throw new Error('Film.rects: no rect named "' + q.name + '" (known: ' + Object.keys(table).join(', ') + ')');
      var r = toRect(typeof d === 'function' ? d.apply(null, q.args) : d);
      if (!r) throw new Error('Film.rects: "' + name + '" gave no rect');
      return r;
    }
    var ui = {
      local: local,
      rect: function () {
        var r = local.apply(null, arguments);
        return { x: ox + r.x * sc, y: oy + r.y * sc, w: r.w * sc, h: r.h * sc, r: r.r };
      },
      center: function () { var r = ui.rect.apply(null, arguments); return [r.x + r.w / 2, r.y + r.h / 2]; },
      point: function (name, at) {
        var r = ui.rect(name), f = [0.5, 0.5];
        var named = { left: [0, 0.5], right: [1, 0.5], top: [0.5, 0], bottom: [0.5, 1], tl: [0, 0], tr: [1, 0], bl: [0, 1], br: [1, 1], center: [0.5, 0.5] };
        if (Array.isArray(at)) f = at; else if (at && named[at]) f = named[at];
        return [r.x + r.w * f[0], r.y + r.h * f[1]];
      },
      has: function (name) { return parse(name, []).name in table; },
      add: function (name, r) { table[name] = r; return ui; },
      names: function () { return Object.keys(table); },
      origin: [ox, oy], scale: sc,
    };
    return ui;
  };
  /** Keys that name rects ([t, 'name', opts]) -> [t, x, y, opts] through ui (for paths and cursors). */
  F.namedKeys = function (keys, ui) {
    return keys.map(function (k) {
      if (typeof k[1] !== 'string') return k;
      var opt = k[2] || {}, pt = ui.point(k[1], opt.at);
      return [k[0], pt[0] + (opt.dx || 0), pt[1] + (opt.dy || 0), opt];
    });
  };

  // ------------------------------------------------------------------ state from events
  function cloneState(v) {
    if (Array.isArray(v)) return v.map(cloneState);
    if (v && typeof v === 'object' && Object.getPrototypeOf(v) === Object.prototype) {
      var o = {};
      for (var k in v) o[k] = cloneState(v[k]);
      return o;
    }
    return v;
  }
  /**
   * UI state at time T as a pure function of an event list (the "stateAt(T)" pattern): start from a
   * copy of `init` and apply, in time order, every event at or before T.
   *   var st = Film.fold(T, { stop: 3, open: false, rows: [] }, [
   *     [CUE.click1, { open: true }],                                   // merge a patch
   *     [CUE.next,   function (s) { s.stop += 1; }],                    // or change the copy
   *     [CUE.type,   function (s, dt) { s.text = 'Launch'.slice(0, Math.floor(dt * 12)); }],  // dt: s since the event
   *   ]);
   * Events may be listed in any order; ties keep the listed order. Nothing leaks between frames.
   */
  F.fold = function (T, init, events) {
    var st = cloneState(init || {});
    var list = (events || []).map(function (e, i) { return { t: +e[0], f: e[1], i: i }; })
      .sort(function (a, b) { return a.t - b.t || a.i - b.i; });
    for (var j = 0; j < list.length; j++) {
      var e = list[j];
      if (e.t > T) break;
      if (typeof e.f === 'function') { var r = e.f(st, T - e.t, T); if (r !== undefined) st = r; }
      else if (e.f && typeof e.f === 'object') for (var k in e.f) st[k] = cloneState(e.f[k]);
    }
    return st;
  };
  F.stateAt = F.fold;

  // ------------------------------------------------------------------ captions and step band
  /**
   * Caption track: [[t0, t1, text], ...] (or {t0, t1, text}). Draws the caption on screen at T with
   * a short fade (o.fade, default 0.25 s), in F.caption's lower-third box (o: size, y, maxWidth,
   * fill, color). Returns the text shown, or ''.
   */
  F.captions = function (T, list, o) {
    o = o || {};
    var fade = o.fade === undefined ? 0.25 : o.fade;
    for (var i = 0; i < (list || []).length; i++) {
      var c = list[i], t0 = Array.isArray(c) ? c[0] : c.t0, t1 = Array.isArray(c) ? c[1] : c.t1, text = Array.isArray(c) ? c[2] : c.text;
      if (T < t0 || T > t1) continue;
      var v = F.win(T, t0, t1, fade, fade);
      if (v > 0) F.caption(text, v, o);
      return text;
    }
    return '';
  };
  /**
   * Step band across the top: numbered badge, the step title, "STEP n OF N" and one progress
   * segment per step. steps: [[t, title], ...] (a step lasts until the next one, the last until
   * o.end); nothing is drawn before the first step or after o.end. o: {end, y, h, fill, fade,
   * label ('Step'), size, showCount (true), accent, badgeText (default: white or the ground, whichever
   * reads better on the badge)}. Returns the current step index or -1.
   */
  F.stepBand = function (T, steps, o) {
    o = o || {};
    if (!steps || !steps.length) return -1;
    var end = o.end === undefined ? Infinity : o.end, i = -1;
    for (var k = 0; k < steps.length; k++) if (T >= steps[k][0]) i = k;
    if (i < 0 || T > end) return -1;
    var t0 = steps[i][0], t1 = i + 1 < steps.length ? steps[i + 1][0] : end;
    var fade = o.fade === undefined ? 0.35 : o.fade;
    var vis = Math.min(F.seg(T, steps[0][0], steps[0][0] + fade), end === Infinity ? 1 : 1 - F.seg(T, end - fade, end));
    if (vis <= 0) return i;
    var g = S.g, size = o.size || 30, h = o.h || size * 2.4, y = o.y === undefined ? 0 : o.y, n = steps.length;
    var titleIn = F.seg(T, t0, t0 + 0.35, 'outCubic');
    g.save();
    g.globalAlpha *= vis;
    F.box(0, y, S.W, h, 0, { fill: o.fill || F.pal.bg });   // opaque by default: a zoomed picture must not show through
    recordCover('band', steps[i][1], 0, y, S.W, h, g);
    F.line(0, y + h, S.W, y + h, { color: F.pal.line, width: 1.5 });
    var cx = 70 + size * 0.75, cy = y + h / 2;
    var badge = o.accent || F.pal.accent, dark = F.pal.bg;
    F.circle(cx, cy, size * 0.75, { fill: badge });
    // the number in whichever of white and the ground reads better on the badge (white on a light accent fails)
    var bt = o.badgeText || (F.contrast('#ffffff', badge) >= F.contrast(dark, badge) ? '#ffffff' : dark);
    F.text(String(i + 1), cx, cy + size * 0.03, { size: size * 0.8, weight: 800, align: 'center', baseline: 'middle', color: bt });
    g.save();
    g.globalAlpha *= titleIn;
    F.text(steps[i][1], cx + size * 1.4 + (1 - titleIn) * 18, cy + size * 0.02, { size: size, weight: 700, baseline: 'middle', color: F.pal.ink, maxWidth: S.W * 0.55 });
    g.restore();
    var segW = Math.min(46, (S.W * 0.28) / n), gap = 7, bw = n * segW + (n - 1) * gap, bx = S.W - 70 - bw, by = cy + size * 0.28;
    if (o.showCount !== false) {
      F.text(((o.label || 'Step') + ' ' + (i + 1) + ' of ' + n).toUpperCase(), S.W - 70, cy - size * 0.28, { size: size * 0.46, weight: 650, tracking: 0.16, align: 'right', baseline: 'middle', color: F.pal.muted });
    }
    for (var j = 0; j < n; j++) {
      var sx = bx + j * (segW + gap);
      F.box(sx, by, segW, 5, 2.5, { fill: F.rgba(F.pal.muted, 0.28) });
      var f = j < i ? 1 : j === i ? F.seg(T, t0, t1) : 0;
      if (f > 0) F.box(sx, by, segW * f, 5, 2.5, { fill: o.accent || F.pal.accent });
    }
    g.restore();
    return i;
  };
  // @end tutorial
  /** Act label: small tracked caps, bottom-left. p: visibility. */
  F.actLabel = function (label, p, o) {
    o = o || {};
    if (!label || p <= 0) return;
    F.text(String(label).toUpperCase(), o.x === undefined ? 64 : o.x, o.y === undefined ? S.H - 56 : o.y,
      { size: o.size || 18, weight: 600, tracking: 0.18, color: o.color || F.pal.muted, alpha: clamp(p) * 0.9 });
  };

  // @part motionblur: motionBlur blurScan mbRemember
  // ================================================================== shutter blur
  // Motion blur on one element of a film, for snap beats (references/film-api.md §11, Shutter blur): the
  // canvas twin of the DOM's data-st-blur. draw(t, g) draws the element at time t (with F.* or g) and returns
  // where it is: [x, y, w, h] or {x, y, w, h} (design units; [x, y] works without the % max). While it moves
  // faster than `threshold` px a frame on screen, the frame gets `samples` draws of it at sub-frame times from
  // T back to T - shutter instead of one: each on its own layer, averaged in pairs ('lighter' at half weight,
  // so 8-bit rounding stays under two levels), then smoothed along the motion (a gaussian half a step wide)
  // and laid on the frame. At rest, moving slowly, or on the frame it comes to rest, it is drawn once, sharp.
  var MB = { pool: [], scratch: null, filters: {}, defs: null };
  function mbCanvas(w, h) {
    var c = MB.pool.pop() || document.createElement('canvas');
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    var x = c.getContext('2d');
    x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = 1; x.globalCompositeOperation = 'source-over'; x.filter = 'none';
    x.clearRect(0, 0, w, h);
    return c;
  }
  function mbBox(p) {
    if (!p) return null;
    if (Array.isArray(p)) return p.length >= 4 ? [+p[0], +p[1], +p[2], +p[3]] : p.length >= 2 ? [+p[0], +p[1], 0, 0] : null;
    if (typeof p === 'object' && isFinite(p.x) && isFinite(p.y)) return [+p.x, +p.y, +(p.w || 0), +(p.h || 0)];
    return null;
  }
  function mbCorners(b, m) {
    var out = [], pts = [b[0], b[1], b[0] + b[2], b[1], b[0], b[1] + b[3], b[0] + b[2], b[1] + b[3]];
    for (var i = 0; i < 8; i += 2) out.push(m.a * pts[i] + m.c * pts[i + 1] + m.e, m.b * pts[i] + m.d * pts[i + 1] + m.f);
    return out;
  }
  function mbDist(a, b) { var d = 0; for (var i = 0; i < 8; i += 2) d = Math.max(d, Math.hypot(a[i] - b[i], a[i + 1] - b[i + 1])); return d; }
  // a draw that paints nothing visible and records no text: where the element is at t
  function mbDry(draw, t, m, record) {
    if (!MB.scratch) { var c = document.createElement('canvas'); c.width = c.height = 1; MB.scratch = c.getContext('2d'); }
    var x = MB.scratch, texts = S.texts, covers = S.covers, prev = S.g;
    x.setTransform(m.a, m.b, m.c, m.d, m.e, m.f); x.globalAlpha = 1;
    if (!record) { S.texts = null; S.covers = null; }
    S.g = x;
    try { x.save(); return draw(t, x); } finally { x.restore(); S.g = prev; S.texts = texts; S.covers = covers; }
  }
  function mbFilter(sx, sy) {
    var key = sx.toFixed(1) + '_' + sy.toFixed(1), id = 'st-film-mb-' + key.replace(/\./g, 'p');
    if (!MB.filters[key]) {
      if (!MB.defs) {
        MB.defs = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        MB.defs.setAttribute('width', '0'); MB.defs.setAttribute('height', '0'); MB.defs.setAttribute('aria-hidden', 'true');
        MB.defs.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden';
        document.body.appendChild(MB.defs);
      }
      MB.defs.insertAdjacentHTML('beforeend', '<filter id="' + id + '" filterUnits="userSpaceOnUse" x="-100000" y="-100000" width="200000" height="200000" ' +
        'color-interpolation-filters="sRGB"><feGaussianBlur stdDeviation="' + sx.toFixed(1) + ' ' + sy.toFixed(1) + '"/></filter>');
      MB.filters[key] = 'url(#' + id + ')';
    }
    return MB.filters[key];
  }
  // Each call site (o.id, else its draw's source and its turn in the frame) is remembered with the frames it was
  // drawn on, so `showtime check` can measure its motion over its whole window (Film.blurScan): the draw is a pure
  // function of t, so where it is at any frame is one dry draw away.
  function mbRemember(draw, o, m, T, opt) {
    var src = String(draw), h = 0;
    for (var i = 0; i < src.length; i++) h = (Math.imul(h, 31) + src.charCodeAt(i)) | 0;
    var base = o.id ? String(o.id) : 'f' + (h >>> 0).toString(36);
    var turns = S.mbTurns || (S.mbTurns = {});
    turns[base] = (turns[base] || 0) + 1;
    var key = base + (turns[base] > 1 ? '#' + turns[base] : '');
    var sites = S.mbSites || (S.mbSites = {});
    var site = sites[key] || (sites[key] = { id: o.id || null, frames: {}, n: 0 });
    site.draw = draw; site.m = m; site.o = o; site.opt = opt;
    var f = Math.round(T * ((S.cfg && S.cfg.fps) || 30));
    if (!site.frames[f] && site.n < 20000) { site.frames[f] = 1; site.n++; }
  }
  /** For `showtime check`: every F.motionBlur element's motion on each frame of its window (the same rows as the DOM scan). */
  F.blurScan = function () {
    var out = [], fps = (S.cfg && S.cfg.fps) || 30, dt = 1 / fps, sites = S.mbSites || {};
    var area0 = S.cw * S.ch;
    Object.keys(sites).forEach(function (key) {
      var st = sites[key], fr = Object.keys(st.frames).map(Number).sort(function (a, b) { return a - b; });
      if (!fr.length) return;
      var f0 = fr[0], f1 = fr[fr.length - 1] + 1, opt = st.opt, mx = st.o.max === undefined ? '50%' : String(st.o.max).trim();
      var texts = S.texts, rows = [], prev = null, point = false;
      S.texts = [];
      try { mbDry(st.draw, ((f0 + f1) / 2 | 0) / fps, st.m, true); } catch (e) { /* a probe only */ }
      var said = S.texts.map(function (x) { return x.text; }).join(' ').replace(/\s+/g, ' ').trim();
      var decor = S.texts.length > 0 && S.texts.every(function (x) { return x.decor; });
      var flash = S.texts.some(function (x) { return x.flash; });
      S.texts = texts;
      var Sh = opt.shutter / 360 * dt;
      for (var f = f0; f < f1; f++) {
        var t = f / fps, b = mbBox(mbDry(st.draw, t, st.m, false)), bS = mbBox(mbDry(st.draw, t - Sh, st.m, false)), bN = mbBox(mbDry(st.draw, t + dt, st.m, false));
        if (!b || !bS) { rows.push([+t.toFixed(4), 0, 0, 0, 0, 0]); prev = null; continue; }
        if (!(b[2] > 0 && b[3] > 0)) point = true;
        var c = mbCorners(b, st.m), L = mbDist(c, mbCorners(bS, st.m)) / S.dpr;
        var on = L * 360 / opt.shutter >= opt.threshold && L >= 0.5 && !(bN && mbDist(c, mbCorners(bN, st.m)) / S.dpr < 0.25);
        var ex = Math.hypot(c[2] - c[0], c[3] - c[1]) / S.dpr, ey = Math.hypot(c[4] - c[0], c[5] - c[1]) / S.dpr;
        var side = Math.min(ex, ey), maxLen = /%$/.test(mx) ? (side > 0 ? parseFloat(mx) / 100 * side : 160) : +mx > 0 ? +mx : Infinity;
        rows.push([+t.toFixed(4), prev ? +(mbDist(c, prev) / S.dpr).toFixed(2) : 0, +Math.min(L, maxLen).toFixed(2), on ? 1 : 0, +side.toFixed(1), +(ex * ey / area0).toFixed(4)]);
        prev = c;
      }
      out.push({ sel: 'F.motionBlur ' + (st.id || (said ? '"' + said.slice(0, 24) + '"' : key)), text: said.slice(0, 60), chars: said.length, nodes: 0, clip: false,
        nested: false, media: false, decor: decor, flash: flash, wholeCanvas: point, shutter: opt.shutter, samples: opt.samples, threshold: opt.threshold, max: mx,
        off: false, pose: true, from: [f0 / fps, f1 / fps], frames: rows, step: 1, why: '', probes: [] });
    });
    return out;
  };
  /** o: {shutter: 180, samples: 8, threshold: 6, max: '50%', id}. Returns what draw returned at T. */
  F.motionBlur = function (T, draw, o) {
    o = o || {};
    var g = S.g, fps = (S.cfg && S.cfg.fps) || 30, dt = 1 / fps;
    var shutter = Math.min(720, +o.shutter > 0 ? +o.shutter : 180), n = Math.min(32, Math.max(2, Math.round(+o.samples) || 8));
    var th = +o.threshold >= 0 ? +o.threshold : 6, Sh = shutter / 360 * dt, m = g.getTransform();
    mbRemember(draw, o, m, T, { shutter: shutter, samples: n, threshold: th });
    var b0 = mbBox(mbDry(draw, T, m, false)), bS = mbBox(mbDry(draw, T - Sh, m, false));
    var plain = function () { return draw(T, g); };
    if (!b0 || !bS) return plain();
    var c0 = mbCorners(b0, m), L = mbDist(c0, mbCorners(bS, m)) / S.dpr;
    if (L * 360 / shutter < th || L < 0.5) return plain();
    var bN = mbBox(mbDry(draw, T + dt, m, false));
    if (bN && mbDist(c0, mbCorners(bN, m)) / S.dpr < 0.25) return plain();   // it lands on this frame: sharp
    var side = Math.min(Math.hypot(c0[2] - c0[0], c0[3] - c0[1]), Math.hypot(c0[4] - c0[0], c0[5] - c0[1])) / S.dpr;
    var mx = o.max === undefined ? '50%' : String(o.max).trim(), maxLen = Infinity;
    if (/%$/.test(mx)) maxLen = side > 0 ? parseFloat(mx) / 100 * side : 160;
    else if (+mx > 0) maxLen = +mx;
    var S2 = L > maxLen ? Sh * maxLen / L : Sh;
    var taus = [];
    for (var k = 0; k < n; k++) taus.push(T - S2 * k / (n - 1));
    // the frame's text is recorded once, where the element is at T (check reads it from Film.frameInfo())
    var ret = mbDry(draw, T, m, true);
    // where the copies land, in canvas pixels (the whole canvas when draw gives only a point)
    var bE = mbBox(mbDry(draw, taus[n - 1], m, false)) || bS;
    var cE = mbCorners(bE, m), steps = [0, 0], cw = S.canvas.width, ch = S.canvas.height;
    for (var j = 0; j < 8; j += 2) { steps[0] = Math.max(steps[0], Math.abs(c0[j] - cE[j])); steps[1] = Math.max(steps[1], Math.abs(c0[j + 1] - cE[j + 1])); }
    var gx = 0.5 * steps[0] / (n - 1), gy = 0.5 * steps[1] / (n - 1);
    var rx = 0, ry = 0, rw = cw, rh = ch;
    if (b0[2] > 0 && b0[3] > 0) {
      var xs = c0.concat(cE).filter(function (v, i) { return i % 2 === 0; }), ys = c0.concat(cE).filter(function (v, i) { return i % 2 === 1; });
      var pad = 0.25 * side * S.dpr + 3 * Math.max(gx, gy) + 16;
      rx = Math.max(0, Math.floor(Math.min.apply(null, xs) - pad)); ry = Math.max(0, Math.floor(Math.min.apply(null, ys) - pad));
      rw = Math.min(cw, Math.ceil(Math.max.apply(null, xs) + pad)) - rx; rh = Math.min(ch, Math.ceil(Math.max.apply(null, ys) + pad)) - ry;
      if (rw <= 0 || rh <= 0) return plain();
    }
    var mix = function (a, b) {   // weighted average of two layers (weights a.w and b.w) on a fresh one
      var c = mbCanvas(rw, rh), x = c.getContext('2d');
      x.globalCompositeOperation = 'lighter';
      x.globalAlpha = a.w / (a.w + b.w); x.drawImage(a.c, 0, 0);
      x.globalAlpha = b.w / (a.w + b.w); x.drawImage(b.c, 0, 0);
      MB.pool.push(a.c, b.c);
      return { c: c, w: a.w + b.w };
    };
    var stack = [], texts = S.texts, covers = S.covers, prev = S.g;
    S.texts = null; S.covers = null;
    try {
      for (var q = 0; q < n; q++) {
        var lc = mbCanvas(rw, rh), lx = lc.getContext('2d');
        lx.setTransform(m.a, m.b, m.c, m.d, m.e - rx, m.f - ry);
        S.g = lx;
        lx.save(); try { draw(taus[q], lx); } finally { lx.restore(); }
        var e = { c: lc, w: 1 };
        while (stack.length && stack[stack.length - 1].w === e.w) e = mix(stack.pop(), e);
        stack.push(e);
      }
      while (stack.length > 1) { var bb = stack.pop(); stack.push(mix(stack.pop(), bb)); }
    } finally { S.g = prev; S.texts = texts; S.covers = covers; }
    g.save();
    g.setTransform(1, 0, 0, 1, 0, 0);
    if (gx > 0.3 || gy > 0.3) g.filter = (g.filter && g.filter !== 'none' ? g.filter + ' ' : '') + mbFilter(gx, gy);
    g.drawImage(stack[0].c, rx, ry);
    g.restore();
    MB.pool.push(stack[0].c);
    if (MB.pool.length > 12) MB.pool.length = 12;
    return ret;
  };
  // @end motionblur

  // ================================================================== offscreen helpers
  /** Draw into an offscreen canvas of w x h design units with fn(g), then return it (for caching). */
  F.offscreen = function (w, h, fn, scale) {
    var sc = scale || S.s * S.dpr;
    var c = makeCanvas(Math.ceil(w * sc), Math.ceil(h * sc));
    var x = c.getContext('2d');
    var prev = S.g;
    S.g = x;
    x.scale(sc, sc);
    try { fn(x, w, h); } finally { S.g = prev; }
    return c;
  };
  /** Run fn with another context as the current drawing target. */
  F.withContext = function (ctx, fn) {
    var prev = S.g;
    S.g = ctx;
    try { return fn(ctx); } finally { S.g = prev; }
  };

  // ================================================================== start / render
  function stageCfg() {
    var st = root.ST, c = {};
    if (!st) return c;
    try {
      if (st.cfg && typeof st.cfg === 'object') c = st.cfg;
      else if (typeof st.getConfig === 'function') c = st.getConfig() || {};
      else if (st.config && typeof st.config === 'object') c = st.config;
    } catch (e) { c = {}; }
    var out = {};
    ['width', 'height', 'fps', 'duration', 'background'].forEach(function (k) {
      if (c[k] !== undefined) out[k] = c[k];
      else if (st[k] !== undefined && typeof st[k] !== 'function') out[k] = st[k];
    });
    return out;
  }

  function normalizeCfg(opts) {
    var sc = stageCfg();
    var cfg = {};
    for (var k in opts) cfg[k] = opts[k];
    cfg.width = +(sc.width || opts.width || 1920);
    cfg.height = +(sc.height || opts.height || 1080);
    cfg.fps = +(sc.fps || opts.fps || 30);
    cfg.duration = +(sc.duration || opts.duration || 10);
    var d = opts.design;
    if (Array.isArray(d)) d = { width: d[0], height: d[1] };
    cfg.design = d ? { width: +d.width, height: +d.height, fit: d.fit || 'contain' } : { width: cfg.width, height: cfg.height, fit: 'contain' };
    return cfg;
  }

  function stageRoot() {
    var st = root.ST;
    var el = (st && (st.root || st.el)) || document.getElementById('stage') || document.querySelector('[data-st-stage]');
    return el && el.appendChild ? el : document.body;
  }

  function setupCanvas() {
    var cfg = S.cfg;
    var cw = cfg.width, ch = cfg.height;
    var dpr = cfg.pixelRatio || (root.devicePixelRatio || 1);
    if (!S.canvas) {
      var c = document.createElement('canvas');
      c.id = 'film';
      c.setAttribute('aria-label', cfg.title || 'film');
      c.style.cssText = 'position:absolute;left:0;top:0;display:block;';
      stageRoot().appendChild(c);
      S.canvas = c;
    }
    var c2 = S.canvas;
    c2.width = Math.round(cw * dpr);
    c2.height = Math.round(ch * dpr);
    c2.style.width = cw + 'px';
    c2.style.height = ch + 'px';
    S.g = c2.getContext('2d', { alpha: false });
    S.ctx = S.g;
    S.cw = cw; S.ch = ch; S.dpr = dpr;
    S.W = cfg.design.width; S.H = cfg.design.height;
    var s = cfg.design.fit === 'cover' ? Math.max(cw / S.W, ch / S.H) : Math.min(cw / S.W, ch / S.H);
    S.s = s; S.ox = (cw - S.W * s) / 2; S.oy = (ch - S.H * s) / 2;
    S.layers = buildLayers();
    S.sizeKey = cw + 'x' + ch + '@' + dpr;
    F.W = S.W; F.H = S.H; F.u = Math.min(S.W, S.H) / 1080;
    F.cx = S.W / 2; F.cy = S.H / 2;
    F.canvas = c2;
    F.width = cw; F.height = ch;
  }

  function currentAct(T) {
    var acts = S.cfg.acts;
    if (!acts || !acts.length) return null;
    var cur = null;
    for (var i = 0; i < acts.length; i++) {
      var a = Array.isArray(acts[i]) ? { t: acts[i][0], label: acts[i][1] } : acts[i];
      if (T >= a.t) cur = { t: a.t, label: a.label, next: null };
      else { if (cur) cur.next = a.t; break; }
    }
    return cur;
  }

  function drawErr(err) {
    var g = S.g;
    g.save();
    g.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
    g.fillStyle = 'rgba(160,20,30,0.92)';
    g.fillRect(0, 0, S.cw, Math.min(S.ch, 120));
    g.fillStyle = '#fff';
    g.font = '600 20px monospace';
    g.fillText('film error at T=' + S.T.toFixed(3) + ': ' + String(err && err.message || err).slice(0, 140), 16, 40);
    g.font = '400 15px monospace';
    var st = String(err && err.stack || '').split('\n').slice(1, 4).join('  ');
    g.fillText(st.slice(0, 190), 16, 72);
    g.restore();
  }

  /** Render the frame at time T. Called by the stage on every seek. */
  function render(T) {
    if (!S.cfg) throw new Error('Film.start() has not been called');
    if (!S.canvas || S.sizeKey !== (S.cfg.width + 'x' + S.cfg.height + '@' + (S.cfg.pixelRatio || root.devicePixelRatio || 1))) setupCanvas();
    T = +T || 0;
    S.T = T; F.T = T;
    S.framesDrawn = (S.framesDrawn || 0) + 1;
    S.texts = [];
    S.mbTurns = {};  // F.motionBlur call sites seen in this frame (each site's turn: see mbRemember)
    S.covers = [];   // opaque annotation cards (callouts) with their draw order: check flags text they hide
    S.drawSeq = 0;
    F.lastError = null;
    var g = S.g, look = S.look;
    g.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
    g.globalAlpha = 1;
    g.globalCompositeOperation = 'source-over';
    g.filter = 'none';
    g.shadowColor = 'transparent';
    g.setLineDash([]);
    g.imageSmoothingEnabled = true;
    // backdrop (canvas space)
    g.save();
    g.fillStyle = S.cfg.background || F.pal.bg;
    g.fillRect(0, 0, S.cw, S.ch);
    var bd = typeof look.backdrop === 'function' ? look.backdrop : BACKDROPS[look.backdrop] || BACKDROPS.flat;
    if (typeof look.backdrop === 'function') {
      g.translate(S.ox, S.oy); g.scale(S.s, S.s);
      bd(T, g, F);
    } else bd(T, g, S.cw, S.ch);
    g.restore();
    // scenes (design space)
    var err = null;
    g.save();
    g.translate(S.ox, S.oy);
    g.scale(S.s, S.s);
    if (look.weave) {
      var wv = look.weave * S.H / 1080;
      g.translate(noise(T * 9, 91) * wv, noise(T * 7, 93) * wv * 0.6);
    }
    try {
      if (S.cfg.scenes) S.cfg.scenes(T, g, F);
    } catch (e) { err = e; }
    g.restore();
    g.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
    g.globalAlpha = 1; g.globalCompositeOperation = 'source-over'; g.filter = 'none'; g.shadowColor = 'transparent';
    // overlays (canvas space)
    drawDust(T, look.dust);
    drawLeak(T, look.leak);
    drawVignette(look.vignette);
    if (typeof look.overlay === 'function') { g.save(); g.translate(S.ox, S.oy); g.scale(S.s, S.s); look.overlay(T, g, F); g.restore(); }
    drawGrain(T, look.grain, look.grainFps || 0, look.grainSize || 1);
    // act labels (design space)
    if (look.labels) {
      var act = currentAct(T);
      if (act) {
        g.save(); g.translate(S.ox, S.oy); g.scale(S.s, S.s);
        var vis = F.win(T, act.t, act.next === null || act.next === undefined ? S.cfg.duration + 1 : act.next, 0.4, 0.3);
        if (typeof look.labels === 'function') look.labels(T, act, vis, F); else F.actLabel(act.label, vis);
        g.restore();
      }
    }
    // global fades
    var fi = S.cfg.fadeIn || 0, fo = S.cfg.fadeOut || 0, fadeA = 0;
    if (fi > 0 && T < fi) fadeA = 1 - E.inOutSine(T / fi);
    if (fo > 0 && T > S.cfg.duration - fo) fadeA = Math.max(fadeA, E.inOutSine(clamp((T - (S.cfg.duration - fo)) / fo)));
    if (fadeA > 0) {
      g.fillStyle = F.rgba(S.cfg.fadeColor || '#000', fadeA);
      g.fillRect(0, 0, S.cw, S.ch);
    }
    if (err) {
      drawErr(err);
      console.error('[film] scenes() threw at T=' + T.toFixed(3) + ':', err);
      F.lastError = err;
      if (root.ST && root.ST.mode === 'render') throw err;
    }
  }
  F.render = render;

  /**
   * Start a film. opts: {scenes(T, g, F), look, palette, design: [w, h] | {width, height, fit},
   * width, height, fps, duration (defaults from showtime.json via the stage), background,
   * fonts: [...], images: {name: src}, acts: [[t, label]], fadeIn, fadeOut, score, pixelRatio, title}.
   */
  F.start = function (opts) {
    if (S.started) { warnOnce('restart', 'Film.start() called twice; ignoring the second call'); return F; }
    opts = opts || {};
    if (typeof opts.scenes !== 'function') throw new Error('Film.start({scenes(T, g, F) {...}}) needs a scenes function');
    S.started = true;
    S.opts = opts;
    S.look = resolveLook(opts.look);
    var palName = typeof S.look.palette === 'string' ? S.look.palette : 'dark';
    var pal = {};
    var basePal = PALETTES[palName] || PALETTES.dark;
    for (var k in basePal) pal[k] = basePal[k];
    if (S.look.palette && typeof S.look.palette === 'object') for (var k2 in S.look.palette) pal[k2] = S.look.palette[k2];
    if (opts.palette) for (var k3 in opts.palette) pal[k3] = opts.palette[k3];
    F.pal = pal;
    if (opts.fontFamilies) for (var f in opts.fontFamilies) F.FONTS[f] = opts.fontFamilies[f];
    S.cfg = normalizeCfg(opts);
    F.cfg = S.cfg;
    F.duration = S.cfg.duration;
    F.fps = S.cfg.fps;
    F.W = S.cfg.design.width; F.H = S.cfg.design.height; F.u = Math.min(F.W, F.H) / 1080;

    var waits = [];
    var fonts = opts.fonts || [
      '400 1em ' + F.FONTS.sans, '600 1em ' + F.FONTS.sans, '800 1em ' + F.FONTS.sans,
    ];
    if (fonts.length) waits.push(F.loadFonts(fonts));
    if (opts.images) {
      for (var name in opts.images) {
        F.img[name] = F.image(opts.images[name]);
        if (F.img[name].promise) waits.push(F.img[name].promise);
      }
    }
    S.ready = Promise.all(waits);
    var st = root.ST;
    if (st) {
      // Page-level config: showtime.json still wins for any key it sets.
      var pageCfg = {};
      ['width', 'height', 'fps', 'duration', 'background', 'title'].forEach(function (k) {
        if (opts[k] !== undefined) pageCfg[k] = opts[k];
      });
      if (Object.keys(pageCfg).length && typeof st.config === 'function') st.config(pageCfg);
      S.cfg = normalizeCfg(opts);
      F.cfg = S.cfg; F.duration = S.cfg.duration; F.fps = S.cfg.fps;
      if (typeof st.waitFor === 'function') st.waitFor(S.ready, 'film fonts/images');
      if (opts.score) st.score = opts.score;
      var handler = function (t) { S.cfg = normalizeCfg(opts); F.cfg = S.cfg; render(t); };
      if (typeof st.onSeek === 'function') st.onSeek(handler);
      else if (typeof st.adapter === 'function') st.adapter('film', handler);
    } else {
      standalone(opts);
    }
    return F;
  };
  F.ready = function () { return S.ready || Promise.resolve(); };

  // Without the stage (a plain file opened in a browser): loop in real time. ?t=3.2 freezes a frame.
  function standalone() {
    var boot = function () {
      S.ready.then(function () {
        var q = /[?&#]t=([0-9.]+)/.exec(location.search + location.hash);
        if (q) { render(parseFloat(q[1])); return; }
        var t0 = null;
        var tick = function (ts) {
          if (t0 === null) t0 = ts;
          render(((ts - t0) / 1000) % S.cfg.duration);
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      });
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else boot();
  }

  /** Seek for debugging (outside the renderer). */
  F.seek = function (t) { render(t); };

  /**
   * What the last rendered frame drew, for QA tools (check, snap): {t, width, height, design, look,
   * texts: [{text, x, y, w, h (output CSS px), size (px on screen), font, color, alpha,
   * cam (camera zoom the text was drawn under; > 1 = cropped by the framing on purpose),
   * decor (UI-mockup detail: F.decor or {decor: true}), flash (a flash word: {flash: true}), z (draw order)}], covers: [{kind ('callout' |
   * 'caption' | 'band' | 'dim'), text, x, y, w, h, z, anchor (callout), hole (dim)}] (cards drawn over the
   * picture, and spotlight dims: text drawn before one and under it is hidden or dimmed on purpose), fonts, error}.
   */
  F.frameInfo = function () {
    var fonts = {};
    (S.texts || []).forEach(function (r) { fonts[r.font.replace(/^.*?\d+(?:\.\d+)?px\s+/, '')] = true; });
    return {
      t: S.T, width: S.cw, height: S.ch, design: [S.W, S.H], look: S.opts && typeof S.opts.look === 'string' ? S.opts.look : 'custom',
      texts: (S.texts || []).slice(), covers: (S.covers || []).slice(), fonts: Object.keys(fonts), error: F.lastError ? String(F.lastError.message || F.lastError) : null,
    };
  };

  // Expose the internal state read-only for debugging.
  Object.defineProperty(F, 'g', { get: function () { return S.g; } });
  Object.defineProperty(F, 's', { get: function () { return S.s; } });
  /** showtime.json "questions", times resolved (ST.questions): [{id, t, think, resume, from, prompt, choices, answer, reply}]. */
  Object.defineProperty(F, 'questions', { get: function () { return root.ST && root.ST.questions ? root.ST.questions : []; } });
  F.pal = PALETTES.dark;
  F.W = 1920; F.H = 1080; F.u = 1; F.T = 0;

  root.Film = F;
})(typeof window !== 'undefined' ? window : globalThis);

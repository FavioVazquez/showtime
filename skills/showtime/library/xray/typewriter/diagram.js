/* A manual typewriter, inside, as a living diagram (showtime X-ray library: typewriter, the "diagram" layout).

   Registration: this file adds one builder to a global table,
       XRAY_DIAGRAM.typewriter = function (ctx) { return SCENE; }
   and the X-ray diagram page (templates/xray/diagram.html) calls it once xray.json and showtime.json are loaded, then
   mounts the result with Diagram.mount(SCENE). A builder for another object registers its own key the same way
   (XRAY_DIAGRAM.musicbox = ...) and the page picks it from showtime.json "xray": {"mechanism": "musicbox"}.

   ctx (from the page):
     events   [{i, frame, kind, ch}]: every event of xray.json; frame is the FILM frame (source frame + offset_frames),
              kind 'event' (a keystroke), 'skip' (showtime.json xray.skip: not drawn) or another kind ('return'),
              ch the character read off the paper for that keystroke (showtime.json xray.text), or null
     fps      the film's frame rate; every time below is frame / fps, so a strike PEAKS on its event's frame
     cue      CUE from cue.js (labels: when the part names arrive, endcard: when they leave)
     region   [x0, y0, x1, y1] design px (the 1920x1080 diagram canvas) the machine is fitted into
     safe     [x0, y0, x1, y1] design px the part labels stay inside;  clip [x, y, w, h]: the drawing is cut to it
     portrait true on a 9:16 page: part names only (no second line), fewer of them
     theme    the Diagram theme in use (Diagram.themes.dark or .light): colours for the pieces drawn by onFrame

   The drawing follows engineering-drawing habits: hidden lines (the key levers under the keyboard) dashed, centre
   lines dash-dot (the platen's axis, the segment's centre), the side frames cut and hatched, the cover removed and
   shown as a dashed ghost, one line weight per role, the solids shaded by the theme's three face tones.

   What moves, per keystroke (film frame f): its key goes down and lights (explode + pulse, peak on f), a packet runs
   key -> typebar -> print point arriving on f, its typebar swings up out of the basket along its drawn arc and hits
   the print point on f (rising 3 frames before, settling over 7 after, a short ghost trail behind it), the ribbon
   lifts, the print point flashes, the escapement wheel lets go one tooth and the carriage steps one letter left from
   f; the ribbon spools and the mainspring turn with the letter count. Which key: only from ctx's ch (what the paper
   in the clip shows); without it the keystroke lights the whole typebar fan, never a guessed key. A space lights the
   space bar and only steps the carriage. An event of kind 'return' winds the mainspring back and runs the carriage
   home. The parts the library has no shape for (typebars, levers, star wheel, spiral, ribbon) are drawn by the
   scene's onFrame hook as a pure function of t, under and over the library's parts. */
(function () {
  'use strict';
  var REG = window.XRAY_DIAGRAM = window.XRAY_DIAGRAM || {};
  var C30 = Math.cos(Math.PI / 6), deg = function (a) { return a * Math.PI / 180; };
  var clamp = function (x, a, b) { return Math.min(b, Math.max(a, x)); };
  var lerp = function (a, b, p) { return a + (b - a) * p; };
  var inOutSine = function (p) { return -(Math.cos(Math.PI * p) - 1) / 2; };
  var inOutCubic = function (p) { return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2; };
  var RISE = 3, FALL = 7, STEPF = 4;          // frames: a strike rises 3 before its frame, settles over 7; a carriage step takes 4

  // ---------------------------------------------------------------- the machine, in world units (x: the machine's
  // width, left to right; y: back to front, the typist at +y; z: up)
  var ROWS = [['qwertyuiop', 7.0, 24.5, 4.6], ['asdfghjkl', 8.2, 27.5, 3.8], ['zxcvbnm,.-', 9.4, 30.5, 3.0]];
  var PITCH = 3.2, KR = 1.15;
  var KEYS = [];                              // [ch, x, y, z]
  ROWS.forEach(function (r) { r[0].split('').forEach(function (ch, i) { KEYS.push([ch, r[1] + i * PITCH, r[2], r[3]]); }); });
  var BYX = KEYS.slice().sort(function (a, b) { return a[1] - b[1] || a[2] - b[2]; }), NB = BYX.length, BAR = {};
  BYX.forEach(function (k, i) { BAR[k[0]] = i; });
  var PLATEN = { x0: 7, x1: 37, y: 7, z: 8.6, r: 1.7 };
  var PP = [22, PLATEN.y + PLATEN.r, PLATEN.z];          // the print point: the front of the platen
  var SEG = { r: 4.6, z: 4.8 };                          // the typebar segment: an arc of pivots around the print point
  var LB = Math.hypot(SEG.r, PP[2] - SEG.z);            // a typebar's length (pivot to type)
  var TH_REST = deg(-8), TH_HIT = Math.atan2(PP[2] - SEG.z, -SEG.r);
  var SPACE = { at: [13, 33.0, 1.8], size: [18, 1.7, 0.7] };
  var SHIFT = [5.6, 30.5, 3.0];
  var ESC = [38.6, 0.9, 7.7];                            // the escapement star wheel (its top face), 16 teeth
  var SPRING = [4.6, 12.4, 4.4];                          // the mainspring drum (its top face)
  var SPOOLS = [[14.2, 10.8, 6.7], [29.8, 10.8, 6.7]];
  var STEP = 0.52;                                        // the carriage's step per letter, world units

  function barAngle(i) { return deg(168 - 156 * i / (NB - 1)); }
  function radial(i) { var a = barAngle(i); return [Math.cos(a), Math.sin(a)]; }
  function pivot(i) { var d = radial(i); return [PP[0] + SEG.r * d[0], PP[1] + SEG.r * d[1], SEG.z]; }
  function tip(i, s) {                                    // the typebar's type end: s = 0 at rest, 1 on the platen
    var p = pivot(i), d = radial(i), th = lerp(TH_REST, TH_HIT, s);
    return [p[0] + LB * Math.cos(th) * d[0], p[1] + LB * Math.cos(th) * d[1], p[2] + LB * Math.sin(th)];
  }
  function keyOf(ch) { for (var i = 0; i < KEYS.length; i++) if (KEYS[i][0] === ch) return KEYS[i]; return null; }
  function stemFoot(k) { return [k[1], k[2], k[3] - 2.2]; }
  function lever(k) { var pv = pivot(BAR[k[0]]); return [stemFoot(k), [pv[0], pv[1] + 1.4, 1.5], [pv[0], pv[1], pv[2] - 0.25]]; }
  function keyId(ch) { return 'k-' + ({ ',': 'comma', '.': 'period', '-': 'dash' }[ch] || ch); }

  // a horizontal cylinder along x, as faces (the library's cylinder stands on z): the body's outline and the x+ cap
  function hull2(pts) {
    var p = pts.map(function (q, i) { return [q[0], q[1], i]; }).sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var cross = function (o, a, b) { return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]); }, lo = [], up = [], i;
    for (i = 0; i < p.length; i++) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], p[i]) <= 0) lo.pop(); lo.push(p[i]); }
    for (i = p.length - 1; i >= 0; i--) { while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], p[i]) <= 0) up.pop(); up.push(p[i]); }
    up.pop(); lo.pop(); return lo.concat(up).map(function (q) { return q[2]; });
  }
  function hcyl(x0, x1, y, z, r, body, cap) {
    var circ = function (x, rr) { var a = []; for (var k = 0; k < 36; k++) { var th = k * Math.PI / 18; a.push([x, y + rr * Math.cos(th), z + rr * Math.sin(th)]); } return a; };
    var both = circ(x0, r).concat(circ(x1, r)), scr = both.map(function (p) { return [(p[0] - p[1]) * C30, (p[0] + p[1]) * 0.5 - p[2]]; });
    var out = hull2(scr).map(function (i) { return both[i]; });
    return [{ kind: 'face', pts: out, tone: body || 'left' }, { kind: 'face', pts: circ(x1, r), tone: cap || 'top' },
            { kind: 'face', pts: circ(x1, r * 0.42), tone: 'recess', lw: 0.6, stroke: 'detail' },
            { kind: 'line', pts: [[x0 + 0.3, y + r * 0.5, z + r * 0.87], [x1 - 0.1, y + r * 0.5, z + r * 0.87]], lw: 0.5 }];
  }

  REG.typewriter = function (ctx) {
    var fps = ctx.fps || 30, ev = ctx.events || [], cue = ctx.cue || {}, portrait = !!ctx.portrait, TH = ctx.theme || {};
    var dark = TH.name !== 'light' && TH.name !== 'white';
    var hotC = (TH.tones && TH.tones.hot && TH.tones.hot.flow) || '#FF6A3D', inkC = TH.ink || '#9FB4CF', detC = TH.detail || '#4E6585';
    var kept = ev.filter(function (e) { return e.kind !== 'skip'; });
    var letters = kept.filter(function (e) { return e.kind === 'event'; });
    var T = function (f) { return f / fps; };
    var t0 = cue.labels != null ? cue.labels : 1.5, tEnd = cue.endcard != null ? cue.endcard : 1e9;

    // ---- fit the machine into the region (design px): its screen box at scale 1, origin 0
    var corners = [];
    [[1, 0, 0], [43, 36, 0], [1, 36, 0], [43, 0, 0], [1, 0, 10.6], [43, 0, 10.6], [13, 4.8, 15.2], [31, 4.8, 15.2], [43, 36, 5.4]].forEach(function (p) {
      corners.push([(p[0] - p[1]) * C30, (p[0] + p[1]) * 0.5 - p[2]]);
    });
    var bx0 = Math.min.apply(null, corners.map(function (c) { return c[0]; })), bx1 = Math.max.apply(null, corners.map(function (c) { return c[0]; }));
    var by0 = Math.min.apply(null, corners.map(function (c) { return c[1]; })), by1 = Math.max.apply(null, corners.map(function (c) { return c[1]; }));
    var R = ctx.region || [1000, 230, 1790, 930];
    var S = Math.min((R[2] - R[0]) / (bx1 - bx0), (R[3] - R[1]) / (by1 - by0));
    var O = [(R[0] + R[2]) / 2 - (bx0 + bx1) / 2 * S, (R[1] + R[3]) / 2 - (by0 + by1) / 2 * S];
    var scr = function (p) { return [O[0] + (p[0] - p[1]) * C30 * S, O[1] + (p[0] + p[1]) * 0.5 * S - p[2] * S]; };

    // ---- the parts (library parts where they fit, plain shapes otherwise)
    var items = [
      // the frame: a base plate, the cover removed (a dashed ghost), the side frames cut (hatched sections), the rail
      { id: 'base', layer: 'floor', shapes: [{ kind: 'box', at: [1, 0, 0], size: [42, 36, 0.8], tone: 'padFaces' }], shadow: false },
      { id: 'cover', layer: 'floor', shapes: [{ kind: 'ghost', at: [1, 0, 0.8], size: [42, 36, 9.6] }] },
      // the side frames, cut away behind the keyboard: only their front halves stand, their cut faces hatched
      { id: 'side-l', shapes: [{ kind: 'box', at: [1, 17, 0.8], size: [1.1, 17, 4.2], tone: 'wallFaces' }, { kind: 'hatch', at: [1, 17, 0.8], size: [1.1, 17, 4.2], endFace: true }],
        bbox: [[1, 17, 0.8], [2.1, 34, 5]] },
      { id: 'side-r', shapes: [{ kind: 'box', at: [41.9, 17, 0.8], size: [1.1, 17, 4.2], tone: 'wallFaces' }, { kind: 'hatch', at: [41.9, 17, 0.8], size: [1.1, 17, 4.2], endFace: true }],
        bbox: [[41.9, 17, 0.8], [43, 34, 5]] },
      { id: 'post-l', part: 'box', at: [3.0, 2.6, 0.8], size: [1.2, 1.4, 5.4], bevel: 0 },
      { id: 'post-r', part: 'box', at: [39.8, 2.6, 0.8], size: [1.2, 1.4, 5.4], bevel: 0 },
      { id: 'rail', part: 'box', at: [2.4, 2.4, 6.2], size: [39.2, 1.8, 0.9], bevel: 0, faces: 'padFaces' },
    ];
    // the carriage: platen, knobs, the paper with its typed lines, the rack; it steps left one letter per keystroke
    var paper = [{ kind: 'face', pts: [[13, 6.1, 10.1], [31, 6.1, 10.1], [31, 4.8, 15.2], [13, 4.8, 15.2]], tone: 'blade' }];
    for (var rl = 0; rl < 5; rl++) paper.push({ kind: 'line', pts: [[15, 5.95 - rl * 0.24, 10.7 + rl * 0.95], [15 + (rl === 4 ? 6 : 13), 5.95 - rl * 0.24, 10.7 + rl * 0.95]], lw: 0.45 });
    var car = [];
    car.push({ kind: 'box', at: [7, 4.3, 7.15], size: [30, 0.5, 0.45], bevel: 0, tone: 'padFaces' });
    for (var rk = 0; rk < 30; rk++) car.push({ kind: 'line', pts: [[7.5 + rk, 4.3, 7.4], [7.9 + rk, 4.3, 7.15]], lw: 0.5 });
    car = car.concat(hcyl(4.4, 7, PLATEN.y, PLATEN.z, 1.25, 'right', 'top'), hcyl(PLATEN.x0, PLATEN.x1, PLATEN.y, PLATEN.z, PLATEN.r, 'left', 'top'),
                     hcyl(PLATEN.x1, 39.6, PLATEN.y, PLATEN.z, 1.25, 'right', 'top'));
    items.push({ id: 'paper', shapes: paper, bbox: [[13, 4.8, 10.1], [31, 6.1, 15.2]], behind: ['carriage'] });
    items.push({ id: 'carriage', shapes: car, bbox: [[4.4, 4.3, 6.9], [39.6, 8.7, 10.3]], front: ['rail'] });
    // ribbon spools, the escapement's arbor and disc, the mainspring drum (their moving faces: onFrame)
    SPOOLS.forEach(function (p, i) {
      items.push({ id: 'spool-' + 'lr'[i], shapes: [{ kind: 'cyl', at: [p[0], p[1], 0.8], r: 0.35, h: p[2] - 1.5 }, { kind: 'cyl', at: [p[0], p[1], p[2] - 0.7], r: 1.9, h: 0.7, flat: true }],
                   bbox: [[p[0] - 1.9, p[1] - 1.9, 0.8], [p[0] + 1.9, p[1] + 1.9, p[2]]], footprint: [p[0] - 0.6, p[1] - 0.6, 1.2, 1.2] });
    });
    items.push({ id: 'esc-arbor', shapes: [{ kind: 'box', at: [ESC[0] - 0.5, ESC[1] - 0.5, 0.8], size: [1.0, 1.0, ESC[2] - 1.15], bevel: 0 }], bbox: [[ESC[0] - 0.5, ESC[1] - 0.5, 0.8], [ESC[0] + 0.5, ESC[1] + 0.5, ESC[2] - 0.35]] });
    items.push({ id: 'escapement', shapes: [{ kind: 'cyl', at: [ESC[0], ESC[1], ESC[2] - 0.35], r: 1.8, h: 0.35, flat: true }], bbox: [[ESC[0] - 1.8, ESC[1] - 1.8, ESC[2] - 0.35], [ESC[0] + 1.8, ESC[1] + 1.8, ESC[2]]], front: ['esc-arbor'] });
    items.push({ id: 'mainspring', shapes: [{ kind: 'cyl', at: [SPRING[0], SPRING[1], 0.8], r: 2.1, h: SPRING[2] - 0.8, flat: true, bands: [1.1] }],
                 footprint: [SPRING[0] - 2.1, SPRING[1] - 2.1, 4.2, 4.2] });
    // the typebar basket and segment: drawn by onFrame; this empty item only tells the label layout where they are
    items.push({ id: 'basket', shapes: [], bbox: [[PP[0] - 10.5, PP[1] - 0.5, 3.6], [PP[0] + 10.5, PP[1] + 10.5, 5.4]], shadow: false, front: ['rail', 'carriage'] });
    // the keyboard: one part per key (a cap on a stem), the shift key and the space bar
    KEYS.forEach(function (k) {
      items.push({ id: keyId(k[0]), shapes: [{ kind: 'line', pts: [[k[1], k[2], k[3]], stemFoot(k)], lw: 0.9, stroke: 'ink' },
        { kind: 'cyl', at: [k[1], k[2], k[3]], r: KR, h: 0.5, cap: 0.68 }], bbox: [[k[1] - KR, k[2] - KR, k[3] - 2.2], [k[1] + KR, k[2] + KR, k[3] + 0.5]] });
    });
    items.push({ id: 'k-shift', shapes: [{ kind: 'line', pts: [SHIFT, [SHIFT[0], SHIFT[1], SHIFT[2] - 2.2]], lw: 0.9, stroke: 'ink' },
      { kind: 'cyl', at: SHIFT, r: KR * 1.15, h: 0.5, cap: 0.68 }], bbox: [[SHIFT[0] - 1.4, SHIFT[1] - 1.4, SHIFT[2] - 2.2], [SHIFT[0] + 1.4, SHIFT[1] + 1.4, SHIFT[2] + 0.5]] });
    items.push({ id: 'k-space', part: 'box', at: SPACE.at, size: SPACE.size, bevel: 0.25, shadow: false });

    // ---- per keystroke: pulses (peak on the frame), the key's travel, the packet, the carriage step
    var states = [], explode = [], tokens = [], carKeys = [];     // carKeys: [frame, dx in letters, frames] for onFrame
    var n = 0;
    function pulse(id, f, amount, tone) { states.push({ target: id, at: T(f - RISE), dur: T(2 * RISE), tone: tone || 'hot', pulse: true, amount: amount == null ? 1 : amount }); }
    kept.forEach(function (e, j) {
      var f = e.frame;
      if (e.kind === 'return') {               // a carriage return: the carriage runs home, the spring winds back
        explode.push({ at: T(f), dur: T(12), offsets: { carriage: [n * STEP, 0, 0], paper: [n * STEP, 0, 0] } });
        carKeys.push([f, n, 12]); pulse('mainspring', f, 0.8, 'warm');
        n = 0; return;
      }
      if (e.kind !== 'event') return;
      var ch = e.ch, lc = ch ? ch.toLowerCase() : null, key = lc && lc !== ' ' ? keyOf(lc) : null;
      if (ch === ' ') {
        pulse('k-space', f, 1);
        explode.push({ at: T(f - RISE), dur: T(RISE), back: T(f), offsets: { 'k-space': [0, 0, -0.5] } });
        tokens.push({ id: 'pk' + j, tone: 'hot', r: 0.7, at: T(f - 9), from: [22, 33.9, 2.6],
                      moves: [{ at: T(f - 6), dur: T(6), to: [ESC[0], ESC[1], ESC[2] + 0.2], hop: 4 }], until: T(f + 1) });
      } else if (key) {
        var id = keyId(lc), top = [key[1], key[2], key[3] + 0.5], pv = pivot(BAR[lc]), o = {};
        pulse(id, f, 1);
        o[id] = [0, 0, -0.7];
        explode.push({ at: T(f - RISE), dur: T(RISE), back: T(f), offsets: o });
        if (ch !== lc) pulse('k-shift', f, 0.9);
        tokens.push({ id: 'pk' + j, tone: 'hot', r: 0.7, at: T(f - 9), from: top,
                      moves: [{ at: T(f - 6), dur: T(3), to: [pv[0], pv[1], pv[2] + 0.3] }, { at: T(f - 3), dur: T(3), to: PP }], until: T(f + 1) });
      }
      pulse('escapement', f, 0.45);
      n++;
      explode.push({ at: T(f), dur: T(STEPF), offsets: { carriage: [-STEP, 0, 0], paper: [-STEP, 0, 0] } });
      carKeys.push([f, -1, STEPF]);
    });

    // ---- the moving pieces the part library has no shape for, drawn every frame from t (pure function of t)
    var barEv = {};                            // bar index -> its keystrokes' frames ('*' = the whole fan)
    letters.forEach(function (e) {
      var lc = e.ch ? e.ch.toLowerCase() : null;
      if (lc === ' ') return;
      var b = lc != null && BAR[lc] != null ? BAR[lc] : (e.ch == null ? '*' : null);
      if (b == null) return;
      (barEv[b] = barEv[b] || []).push(e.frame);
    });
    var stepFrames = letters.map(function (e) { return e.frame; });
    var hitFrames = letters.filter(function (e) { return e.ch !== ' '; }).map(function (e) { return e.frame; });
    function env(ft, f) {                       // 0..1, exactly 1 on the event's frame
      var d = ft - f;
      if (d < -RISE || d > FALL) return 0;
      if (d <= 0) { var a = (d + RISE) / RISE; return a * a; }
      return 1 - inOutSine(d / FALL);
    }
    function barS(i, ft) { var s = 0; (barEv[i] || []).forEach(function (f) { s = Math.max(s, env(ft, f)); }); return s; }
    function stepsAt(ft) { var s = 0; stepFrames.forEach(function (f) { s += inOutCubic(clamp((ft - f) / STEPF, 0, 1)); }); return s; }
    function carriageAt(ft) {                   // the carriage's x offset, exactly as the explode keys move it
      var x = 0; carKeys.forEach(function (c) { x += c[1] * STEP * inOutCubic(clamp((ft - c[0]) / c[2], 0, 1)); }); return x;
    }
    var NS = 'http://www.w3.org/2000/svg', gU = null, gO = null;
    function groups() {
      var w = document.getElementById('ld-world');
      if (!w) return false;
      if (!gU || !gU.isConnected) { gU = document.createElementNS(NS, 'g'); gU.setAttribute('id', 'xd-under'); w.insertBefore(gU, w.firstChild); }
      if (!gO || !gO.isConnected) { gO = document.createElementNS(NS, 'g'); gO.setAttribute('id', 'xd-over'); w.appendChild(gO); }
      return true;
    }
    var f1 = function (v) { return (Math.round(v * 10) / 10).toString(); };
    var LW = TH.lw || 1.5;                      // the theme's hairline: every weight below is a multiple of it
    var HID = ' stroke-dasharray="7 5"', CEN = ' stroke-dasharray="22 5 3 5"';
    function onFrame(t, k) {
      if (!groups()) return;
      var P = k.P, ft = t * fps, u = '', o = '';
      var path = function (pts) { return 'M' + pts.map(function (p) { var q = P(p[0], p[1], p[2]); return f1(q[0]) + ' ' + f1(q[1]); }).join('L'); };
      var stroke = function (pts, col, w, extra) { return '<path d="' + path(pts) + '" fill="none" stroke="' + col + '" stroke-width="' + f1(w) + '" stroke-linecap="round" stroke-linejoin="round"' + (extra || '') + '/>'; };
      var dot = function (p, r, col, extra) { var q = P(p[0], p[1], p[2]); return '<circle cx="' + f1(q[0]) + '" cy="' + f1(q[1]) + '" r="' + f1(r) + '" fill="' + col + '"' + (extra || '') + '/>'; };
      var steps = stepsAt(ft), cx = carriageAt(ft);
      var all = 0; (barEv['*'] || []).forEach(function (f) { all = Math.max(all, env(ft, f)); });
      // hidden lines: every key lever, dashed, under the keyboard; the struck one lit
      var lit = [];
      KEYS.forEach(function (key) {
        var s = barS(BAR[key[0]], ft);
        if (s > 0.004) lit.push([key, s]); else u += stroke(lever(key), detC, LW * 0.8, HID);
      });
      // the type rest pad and the segment (a heavy arc of pivots), its centre line through the print point
      var arc = [], pad = [];
      for (var a = 0; a <= 48; a++) {
        var th = deg(172 - 164 * a / 48);
        arc.push([PP[0] + SEG.r * Math.cos(th), PP[1] + SEG.r * Math.sin(th), SEG.z]);
        pad.push([PP[0] + (SEG.r + LB * 0.99) * Math.cos(th), PP[1] + (SEG.r + LB * 0.99) * Math.sin(th), SEG.z - LB * 0.16]);
      }
      u += stroke(pad, detC, LW * 3, ' stroke-opacity="0.9"');
      u += stroke([[PP[0], PP[1] + SEG.r + LB + 1.5, SEG.z], [PP[0], PP[1] - 0.6, SEG.z]], detC, LW * 0.8, CEN);
      // typebars at rest in the basket (thin), each with its type slug
      var moving = [];
      for (var i = 0; i < NB; i++) {
        var s = barS(i, ft);
        if (s > 0.004) { moving.push([i, s]); continue; }
        var pv = pivot(i), tp = tip(i, 0), hot = all > 0.004;
        u += stroke([pv, tp], hot ? hotC : inkC, LW * 1.1, hot ? ' stroke-opacity="' + (0.4 + 0.6 * all).toFixed(3) + '"' : ' stroke-opacity="0.85"');
        u += dot(tp, LW * 1.6, hot ? hotC : inkC);
      }
      u += stroke(arc, inkC, LW * 3.2);
      lit.forEach(function (x) { u += stroke(lever(x[0]), hotC, LW * 1.6, HID + ' stroke-opacity="' + (0.4 + 0.6 * x[1]).toFixed(3) + '"'); });
      // a struck typebar: its swing arc (thin, dashed), a short ghost trail, the bar itself, the type at its tip
      moving.forEach(function (m) {
        var i = m[0], s = m[1], pv = pivot(i), sw = [];
        for (var q = 0; q <= 24; q++) sw.push(tip(i, q / 24));
        o += stroke(sw, hotC, LW * 0.8, ' stroke-dasharray="3 5" stroke-opacity="' + (0.7 * Math.min(1, s * 2.5)).toFixed(3) + '"');
        [[2, 0.14], [1, 0.3]].forEach(function (g) { var sg = barS(i, ft - g[0]); if (Math.abs(sg - s) > 0.02) o += stroke([pv, tip(i, sg)], hotC, LW * 1.8, ' stroke-opacity="' + g[1] + '"'); });
        o += '<g filter="url(#ld-glowsoft)">' + stroke([pv, tip(i, s)], hotC, LW * 2.6) + '</g>';
        o += dot(tip(i, s), LW * 2.6, hotC) + dot(pv, LW * 1.6, hotC);
      });
      // ribbon: spool to spool through the vibrator, lifted on a strike; the spools turn with the letter count
      var lift = 0; hitFrames.forEach(function (f) { lift = Math.max(lift, env(ft, f)); });
      var vz = PP[2] - 1.1 + 0.9 * lift;
      SPOOLS.forEach(function (p, si) {
        var rot = steps * 0.32 * (si ? -1 : 1), ring = [];
        for (var q2 = 0; q2 <= 36; q2++) { var a2 = q2 * Math.PI / 18; ring.push([p[0] + 1.25 * Math.cos(a2), p[1] + 1.25 * Math.sin(a2), p[2]]); }
        o += stroke(ring, detC, LW * 0.8);
        for (var sp = 0; sp < 3; sp++) { var th2 = rot + sp * Math.PI * 2 / 3; o += stroke([p, [p[0] + 1.6 * Math.cos(th2), p[1] + 1.6 * Math.sin(th2), p[2]]], inkC, LW * 1.1); }
        o += dot(p, LW * 1.4, inkC);
      });
      o += stroke([[SPOOLS[0][0] + 1.5, SPOOLS[0][1] - 1.1, SPOOLS[0][2]], [PP[0] - 2.4, PP[1] + 0.45, vz], [PP[0] + 2.4, PP[1] + 0.45, vz], [SPOOLS[1][0] - 1.5, SPOOLS[1][1] - 1.1, SPOOLS[1][2]]],
                  lift > 0.02 ? hotC : inkC, LW * 1.5, ' stroke-opacity="' + (lift > 0.02 ? (0.55 + 0.45 * lift) : 0.8).toFixed(3) + '"');
      // the platen's centre line (dash-dot, it rides with the carriage) and the print point's mark
      o += stroke([[2.6 + cx, PLATEN.y, PLATEN.z], [41.4 + cx, PLATEN.y, PLATEN.z]], inkC, LW * 0.7, CEN + ' stroke-opacity="0.75"');
      var pq = P(PP[0], PP[1], PP[2]), mk = 9;
      o += '<path d="M' + f1(pq[0] - mk) + ' ' + f1(pq[1]) + 'H' + f1(pq[0] + mk) + 'M' + f1(pq[0]) + ' ' + f1(pq[1] - mk) + 'V' + f1(pq[1] + mk) + '" stroke="' + inkC + '" stroke-width="' + f1(LW) + '"/>';
      hitFrames.forEach(function (f) {
        var d = ft - f; if (d < 0 || d >= 6) return;
        var al = 1 - d / 6;
        o += '<circle cx="' + f1(pq[0]) + '" cy="' + f1(pq[1]) + '" r="' + f1(7 + d * 3.5) + '" fill="none" stroke="' + hotC + '" stroke-width="' + f1(LW * 1.6) + '" opacity="' + al.toFixed(3) + '"/>';
        o += '<circle cx="' + f1(pq[0]) + '" cy="' + f1(pq[1]) + '" r="' + f1(6 * al + 1.5) + '" fill="' + hotC + '" opacity="' + al.toFixed(3) + '"' + (dark ? ' filter="url(#ld-glow)"' : '') + '/>';
      });
      // escapement star wheel: one tooth (1/16 turn) per keystroke, from its frame; its arbor's centre mark
      var esc = [], rot3 = steps * Math.PI * 2 / 16;
      for (var q3 = 0; q3 <= 64; q3++) { var th3 = rot3 + q3 * Math.PI / 32, rr = q3 % 4 === 0 ? 1.62 : (q3 % 4 === 2 ? 1.1 : 1.36); esc.push([ESC[0] + rr * Math.cos(th3), ESC[1] + rr * Math.sin(th3), ESC[2]]); }
      var escHot = 0; stepFrames.forEach(function (f) { escHot = Math.max(escHot, env(ft, f)); });
      o += stroke(esc, escHot > 0.02 ? hotC : inkC, LW * 1.3);
      o += stroke([ESC, [ESC[0] + 0.9 * Math.cos(rot3), ESC[1] + 0.9 * Math.sin(rot3), ESC[2]]], inkC, LW * 1.1) + dot(ESC, LW * 1.4, inkC);
      // the pinion's link to the carriage rack (hidden behind the rail: dashed)
      o += stroke([[ESC[0], ESC[1] + 1.4, ESC[2]], [ESC[0], 4.3, 7.4]], detC, LW * 0.8, HID);
      // mainspring: a spiral that unwinds a little per letter; its band runs to the carriage's left end
      var sp2 = [], turn = -steps * 0.09;
      for (var q4 = 0; q4 <= 110; q4++) { var th4 = turn + q4 * deg(14), r4 = 0.2 + q4 * 0.0165; sp2.push([SPRING[0] + r4 * Math.cos(th4), SPRING[1] + r4 * Math.sin(th4), SPRING[2]]); }
      o += stroke(sp2, inkC, LW * 1.0);
      o += stroke([[SPRING[0] + 0.2, SPRING[1] - 2.0, SPRING[2] - 0.5], [SPRING[0] + 0.2, 5.4, 6.4], [4.4 + cx, PLATEN.y - 0.9, PLATEN.z - 0.7]], detC, LW * 1.5);
      gU.innerHTML = u; gO.innerHTML = o;
    }

    // ---- the part names: a callout system with fixed places (no leader crosses another or a part), arriving one by
    // one and leaving before the end card. Each callout's shoulder sits at a fraction of the machine's box on screen.
    var bb = (function () { var q = corners.map(function (c) { return [O[0] + c[0] * S, O[1] + c[1] * S]; });
      return [Math.min.apply(null, q.map(function (c) { return c[0]; })), Math.min.apply(null, q.map(function (c) { return c[1]; })),
              Math.max.apply(null, q.map(function (c) { return c[0]; })), Math.max.apply(null, q.map(function (c) { return c[1]; }))]; })();
    var PLACES = portrait ? {
      Typebars: [0.343, 0.15, 'left'], Carriage: [0.645, -0.005, 'left'], Escapement: [1.05, 0.08, 'left'], Keys: [0.131, 0.919, 'left'] } : {
      Mainspring: [0.27, 0.24, 'left'], Typebars: [0.29, 0.07, 'left'], Keys: [0.30, 0.93, 'left'],
      Carriage: [0.60, -0.01, 'right'], Escapement: [1.031, 0.165, 'left'] };
    var L = [];
    var lab = function (o2, title, sub, i) {
      var l = Object.assign(o2, { at: t0 + i * 0.35, until: tEnd - 0.25, title: title, sub: portrait ? '' : sub });
      var pl = (ctx.places || PLACES)[title];
      if (pl) { var a2 = scr(l.anchor); l.elbow = [Math.round(bb[0] + pl[0] * (bb[2] - bb[0]) - a2[0]), Math.round(bb[1] + pl[1] * (bb[3] - bb[1]) - a2[1])]; l.side = pl[2]; }
      L.push(l);
    };
    lab({ for: 'k-space', anchor: [SPACE.at[0], SPACE.at[1] + SPACE.size[1], SPACE.at[2] + SPACE.size[2]] }, 'Keys', 'pressed by the typist', 0);
    lab({ for: 'basket', anchor: tip(2, 0) }, 'Typebars', 'one per key', 1);
    lab({ anchor: [20, 5.3, 13.2] }, 'Carriage', 'paper and platen step left', 2);   // on the paper: it stays on it as it moves
    lab({ for: 'escapement', anchor: [ESC[0] + 1.62, ESC[1], ESC[2]] }, 'Escapement', 'one tooth per key', 3);
    if (!portrait) lab({ for: 'mainspring', anchor: [SPRING[0] - 1.45, SPRING[1] + 1.45, SPRING[2] - 1.2] }, 'Mainspring', 'pulls the carriage', 4);

    // the camera: one calm move, easing a little toward the acting parts (the basket and the print point)
    var cz = [(R[0] + R[2]) / 2, (R[1] + R[3]) / 2], act = scr([PP[0], PP[1] + 4, 6]);
    var foc = [lerp(cz[0], act[0], 0.5), lerp(cz[1], act[1], 0.5)];
    var camTo = [foc[0] + Math.round(lerp(cz[0], foc[0], 0.4) - foc[0]), foc[1] + Math.round(lerp(cz[1], foc[1], 0.4) - foc[1])];
    return {
      world: { scale: S, origin: O },
      clip: ctx.clip, safe: ctx.safe, avoid: ctx.avoid,
      leaderCost: 3,
      items: items, states: states, explode: explode, tokens: tokens, labels: L,
      // (on a phone the figure has no room to grow: it holds still). The runtime rounds a camera at rest to whole
      // pixels: the move starts from a whole-pixel pose (to - focus is whole) and ends under the end card, so no
      // frame snaps by half a pixel while the figure is in view.
      camera: portrait ? [] : [{ at: t0 + 0.4, dur: Math.max(1.5, tEnd - t0 + 0.2), zoom: 1.04, focus: foc, to: camTo }],
      onFrame: onFrame,
      xray: { bars: NB, letters: letters.length, scr: scr },
    };
  };
})();

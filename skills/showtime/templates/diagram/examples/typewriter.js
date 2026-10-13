/* "Type on it": a manual typewriter, inside, as a LIVE figure you type on (a generic machine, drawn; not a specific
   model). Every key the viewer presses goes down and lights, a packet runs along its lever to its typebar, the bar
   swings up out of the basket and strikes the print point through the lifted ribbon, the letter lands on the paper,
   the escapement lets go one tooth and the carriage steps one letter left. Space only steps; Backspace moves the
   carriage back one letter (the letter stays on the paper, as on a real machine); Return (Enter, or a click on the
   return lever) runs the carriage home against the mainspring and turns the platen up one line. Five characters
   before the margin the bell rings; at the margin the keys lock until Return. Capitals and the symbols over the
   digits take Shift: the segment drops so the upper character on the type slug strikes.

   How it is built: every keystroke is an event {t, kind, ch} in one log (seconds on the live clock); the drawing is
   a pure function of t and that log, so fast typing stacks (several bars in flight, each on its own time) and the
   film (index.html, the tour on the film's clock: interactive.film = 'tour') draws exactly what the live page does.
   The machine's drawing is the showtime X-ray library's typewriter (library/xray/typewriter/diagram.js), with a
   digit row, a backspace key, a bell and a return lever added. The line length is measured off the drawing: the
   paper's writable width (15 units, margins of 1.5) over the carriage's step (0.52) is 28 letters.
   The live page is figure.html (`showtime export html <project> --interactive`).
   To use it: `showtime new diagram <dir> --example typewriter --theme white`. */
var CUE = {
  duration: 25.2,
};

(function () {
  'use strict';
  var C30 = Math.cos(Math.PI / 6), deg = function (a) { return a * Math.PI / 180; };
  var clamp = function (x, a, b) { return Math.min(b, Math.max(a, x)); };
  var lerp = function (a, b, p) { return a + (b - a) * p; };
  var inOutSine = function (p) { return -(Math.cos(Math.PI * p) - 1) / 2; };
  var inOutCubic = function (p) { return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2; };
  var outCubic = function (p) { return 1 - Math.pow(1 - p, 3); };

  // ---------------------------------------------------------------- the machine, in world units (x: its width, left
  // to right; y: back to front, the typist at +y; z: up). The X-ray library's typewriter, plus a digit row.
  var ROWS = [['1234567890-', 5.8, 21.5, 5.4], ['qwertyuiop', 7.0, 24.5, 4.6], ['asdfghjkl;', 8.2, 27.5, 3.8], ['zxcvbnm,./', 9.4, 30.5, 3.0]];
  var UPPER = { '1': '!', '2': '"', '3': '#', '4': '$', '5': '%', '6': '_', '7': '&', '8': "'", '9': '(', '0': ')', '-': '*', ';': ':', ',': ',', '.': '.', '/': '?' };
  var PITCH = 3.2, KR = 1.15;
  var KEYS = [];                              // [ch, x, y, z]
  ROWS.forEach(function (r) { r[0].split('').forEach(function (ch, i) { KEYS.push([ch, r[1] + i * PITCH, r[2], r[3]]); }); });
  var KEY = {}; KEYS.forEach(function (k) { KEY[k[0]] = k; });
  var BYX = KEYS.slice().sort(function (a, b) { return a[1] - b[1] || a[2] - b[2]; }), NB = BYX.length, BAR = {};
  BYX.forEach(function (k, i) { BAR[k[0]] = i; });
  var SLUG = {};                              // the character typed -> [the key it is on, shifted]
  KEYS.forEach(function (k) {
    var c = k[0], up = /[a-z]/.test(c) ? c.toUpperCase() : UPPER[c];
    SLUG[c] = [c, false]; if (up && !SLUG[up]) SLUG[up] = [c, true];
  });
  var PLATEN = { x0: 7, x1: 37, y: 7, z: 8.6, r: 1.7 };
  var PP = [22, PLATEN.y + PLATEN.r, PLATEN.z];          // the print point: the front of the platen
  var SEG = { r: 4.6, z: 4.8 };                          // the segment: an arc of pivots around the print point
  var LB = Math.hypot(SEG.r, PP[2] - SEG.z);            // a typebar's length (pivot to type)
  var TH_REST = deg(-8), TH_HIT = Math.atan2(PP[2] - SEG.z, -SEG.r);
  var SHIFT_DROP = 0.5;                                  // the segment's drop for the upper case
  var SPACE = { at: [13, 33.0, 1.8], size: [18, 1.7, 0.7] };
  var SHIFTK = [5.6, 30.5, 3.0], BACKK = [2.6, 21.5, 5.4];
  var ESC = [38.6, 0.9, 7.7];                            // the escapement star wheel (its top face), 16 teeth
  var SPRING = [4.6, 12.4, 4.4];                          // the mainspring drum (its top face)
  var SPOOLS = [[14.2, 10.8, 6.7], [29.8, 10.8, 6.7]];
  var BELL = [40.4, 12.6, 0.8];                           // the bell, on the base under the carriage's right end
  // the line, measured off the drawing: the paper spans x 13..31 at rest; margins of 1.5 leave 15 units; a step is
  // 0.52, so 28 letters; at home the left margin sits on the print point (the carriage 7.5 to the right)
  var STEP = 0.52, PAPER = [13, 31], MARGIN = 1.5;
  var N = Math.floor((PAPER[1] - PAPER[0] - 2 * MARGIN) / STEP + 1e-9), BELL_AT = N - 5;
  var HOME = PP[0] - (PAPER[0] + MARGIN);
  var LF = 0.95, Z0 = 10.75;                              // the line feed (along the paper) and the typing line
  // times, in seconds from the moment the page hands a keystroke over (fx.tau, already 0.05 s after the key went down)
  var PK = 0.05, RISE = 0.09, FALL = 0.24, STEPD = 0.11, LIFE = 1.2;

  function barAngle(i) { return deg(168 - 156 * i / (NB - 1)); }
  function radial(i) { var a = barAngle(i); return [Math.cos(a), Math.sin(a)]; }
  function pivot(i, dz) { var d = radial(i); return [PP[0] + SEG.r * d[0], PP[1] + SEG.r * d[1], SEG.z - (dz || 0)]; }
  function tip(i, s, dz) {                                // the type end: s = 0 at rest, 1 on the platen
    var p = pivot(i, dz), d = radial(i), th = lerp(TH_REST, TH_HIT, s);
    return [p[0] + LB * Math.cos(th) * d[0], p[1] + LB * Math.cos(th) * d[1], p[2] + LB * Math.sin(th)];
  }
  function stemFoot(k) { return [k[1], k[2], k[3] - 2.2]; }
  function lever(k, dz) { var pv = pivot(BAR[k[0]], dz); return [stemFoot(k), [pv[0], pv[1] + 1.4, 1.5], [pv[0], pv[1], pv[2] - 0.25]]; }
  function keyId(ch) { return 'k-' + ({ ',': 'comma', '.': 'period', '-': 'dash', ';': 'semi', '/': 'slash' }[ch] || ch); }
  function paperY(z) { return 6.1 - (z - 10.1) * 0.255; }

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

  // ---------------------------------------------------------------- where it sits: fitted into the 1920x1080 stage,
  // the carriage's two ends (home, and the margin) and the paper's top included
  var R = [200, 170, 1720, 1030], pts = [];
  [[1, 0, 0], [43, 36, 0], [1, 36, 0], [43, 0, 0], [1, 0, 10.6], [43, 0, 10.6], [-3, 4.3, 12.8], [47.4, 8.7, 6.9],
   [5.9, 4.8, 15.2], [38.5, 4.8, 15.2], [31, 36, 1.8]].forEach(function (p) { pts.push([(p[0] - p[1]) * C30, (p[0] + p[1]) * 0.5 - p[2]]); });
  var bx = pts.map(function (c) { return c[0]; }), by = pts.map(function (c) { return c[1]; });
  var bx0 = Math.min.apply(null, bx), bx1 = Math.max.apply(null, bx), by0 = Math.min.apply(null, by), by1 = Math.max.apply(null, by);
  var S = Math.min((R[2] - R[0]) / (bx1 - bx0), (R[3] - R[1]) / (by1 - by0));
  var O = [Math.round((R[0] + R[2]) / 2 - (bx0 + bx1) / 2 * S), Math.round((R[1] + R[3]) / 2 - (by0 + by1) / 2 * S)];

  // ---------------------------------------------------------------- the parts
  var items = [
    { id: 'base', layer: 'floor', shapes: [{ kind: 'box', at: [1, 0, 0], size: [42, 36, 0.8], tone: 'padFaces' }], shadow: false },
    { id: 'cover', layer: 'floor', shapes: [{ kind: 'ghost', at: [1, 0, 0.8], size: [42, 36, 9.6] }] },
    { id: 'side-l', shapes: [{ kind: 'box', at: [1, 17, 0.8], size: [1.1, 17, 4.2], tone: 'wallFaces' }, { kind: 'hatch', at: [1, 17, 0.8], size: [1.1, 17, 4.2], endFace: true }],
      bbox: [[1, 17, 0.8], [2.1, 34, 5]] },
    { id: 'side-r', shapes: [{ kind: 'box', at: [41.9, 17, 0.8], size: [1.1, 17, 4.2], tone: 'wallFaces' }, { kind: 'hatch', at: [41.9, 17, 0.8], size: [1.1, 17, 4.2], endFace: true }],
      bbox: [[41.9, 17, 0.8], [43, 34, 5]] },
    { id: 'post-l', part: 'box', at: [3.0, 2.6, 0.8], size: [1.2, 1.4, 5.4], bevel: 0 },
    { id: 'post-r', part: 'box', at: [39.8, 2.6, 0.8], size: [1.2, 1.4, 5.4], bevel: 0 },
    { id: 'rail', part: 'box', at: [2.4, 2.4, 6.2], size: [39.2, 1.8, 0.9], bevel: 0, faces: 'padFaces' },
  ];
  // the carriage (its rack), the platen with its knobs, the paper, the return lever: they ride together
  var rack = [{ kind: 'box', at: [7, 4.3, 7.15], size: [30, 0.5, 0.45], bevel: 0, tone: 'padFaces' }];
  for (var rk = 0; rk < 30; rk++) rack.push({ kind: 'line', pts: [[7.5 + rk, 4.3, 7.4], [7.9 + rk, 4.3, 7.15]], lw: 0.5 });
  items.push({ id: 'carriage', shapes: rack, bbox: [[7, 4.3, 7.15], [37, 4.8, 7.6]], front: ['rail'] });
  items.push({ id: 'paper', shapes: [{ kind: 'face', pts: [[PAPER[0], 6.1, 10.1], [PAPER[1], 6.1, 10.1], [PAPER[1], 4.8, 15.2], [PAPER[0], 4.8, 15.2]], tone: 'blade' }],
               bbox: [[PAPER[0], 4.8, 10.1], [PAPER[1], 6.1, 15.2]], behind: ['platen'] });
  items.push({ id: 'platen', shapes: hcyl(4.4, 7, PLATEN.y, PLATEN.z, 1.25, 'right', 'top').concat(hcyl(PLATEN.x0, PLATEN.x1, PLATEN.y, PLATEN.z, PLATEN.r, 'left', 'top'),
                 hcyl(PLATEN.x1, 39.6, PLATEN.y, PLATEN.z, 1.25, 'right', 'top')), bbox: [[4.4, 5.3, 6.9], [39.6, 8.7, 10.3]], front: ['carriage'] });
  items.push({ id: 'retlever', shapes: [{ kind: 'line', pts: [[4.2, 7.6, 9.6], [2.6, 8.4, 11.6], [0.4, 8.8, 12.4]], lw: 2.6, stroke: 'ink' },
                 { kind: 'box', at: [-0.9, 8.3, 12.1], size: [1.6, 1.0, 0.5], bevel: 0.15 }], bbox: [[-0.9, 7.6, 9.4], [4.3, 9.3, 12.6]] });
  SPOOLS.forEach(function (p, i) {
    items.push({ id: 'spool-' + 'lr'[i], shapes: [{ kind: 'cyl', at: [p[0], p[1], 0.8], r: 0.35, h: p[2] - 1.5 }, { kind: 'cyl', at: [p[0], p[1], p[2] - 0.7], r: 1.9, h: 0.7, flat: true }],
                 bbox: [[p[0] - 1.9, p[1] - 1.9, 0.8], [p[0] + 1.9, p[1] + 1.9, p[2]]], footprint: [p[0] - 0.6, p[1] - 0.6, 1.2, 1.2] });
  });
  // the ribbon (between the spools, through the vibrator: drawn by onFrame), for hovering
  items.push({ id: 'ribbon', shapes: [], bbox: [[16.1, 8.9, 6.3], [27.9, 10.6, 7.6]], shadow: false });
  items.push({ id: 'esc-arbor', shapes: [{ kind: 'box', at: [ESC[0] - 0.5, ESC[1] - 0.5, 0.8], size: [1.0, 1.0, ESC[2] - 1.15], bevel: 0 }], bbox: [[ESC[0] - 0.5, ESC[1] - 0.5, 0.8], [ESC[0] + 0.5, ESC[1] + 0.5, ESC[2] - 0.35]] });
  items.push({ id: 'escapement', shapes: [{ kind: 'cyl', at: [ESC[0], ESC[1], ESC[2] - 0.35], r: 1.8, h: 0.35, flat: true }], bbox: [[ESC[0] - 1.8, ESC[1] - 1.8, ESC[2] - 0.35], [ESC[0] + 1.8, ESC[1] + 1.8, ESC[2]]], front: ['esc-arbor'] });
  items.push({ id: 'mainspring', shapes: [{ kind: 'cyl', at: [SPRING[0], SPRING[1], 0.8], r: 2.1, h: SPRING[2] - 0.8, flat: true, bands: [1.1] }],
               footprint: [SPRING[0] - 2.1, SPRING[1] - 2.1, 4.2, 4.2] });
  items.push({ id: 'bell', shapes: [{ kind: 'cyl', at: [BELL[0], BELL[1], BELL[2]], r: 0.3, h: 1.0 }, { kind: 'cyl', at: [BELL[0], BELL[1], BELL[2] + 1.0], r: 1.5, h: 1.1, cap: 0.55 }],
               bbox: [[BELL[0] - 1.5, BELL[1] - 1.5, BELL[2]], [BELL[0] + 1.5, BELL[1] + 1.5, BELL[2] + 2.1]], footprint: [BELL[0] - 1.3, BELL[1] - 1.3, 2.6, 2.6] });
  // the parts onFrame draws (typebars, segment, print point, key levers): empty items that say where they are
  items.push({ id: 'segment', shapes: [], bbox: [[PP[0] - 4.8, PP[1] - 0.3, 4.2], [PP[0] + 4.8, PP[1] + 4.6, 5.4]], shadow: false });
  items.push({ id: 'basket', shapes: [], bbox: [[PP[0] - 10.5, PP[1] + 4.6, 3.6], [PP[0] + 10.5, PP[1] + 10.5, 5.4]], shadow: false, front: ['rail', 'carriage'] });
  items.push({ id: 'pp', shapes: [], bbox: [[PP[0] - 0.7, PP[1] - 0.3, PP[2] - 0.7], [PP[0] + 0.7, PP[1] + 0.4, PP[2] + 0.7]], shadow: false });
  items.push({ id: 'levers', shapes: [], bbox: [[6, 19.3, 0.9], [38, 20.4, 2.4]], shadow: false });
  // the keyboard: one part per key (a cap on a stem), the shift and backspace keys and the space bar
  var cap = function (id, p, r) {
    items.push({ id: id, shapes: [{ kind: 'line', pts: [[p[0], p[1], p[2]], [p[0], p[1], p[2] - 2.2]], lw: 0.9, stroke: 'ink' }, { kind: 'cyl', at: p, r: r, h: 0.5, cap: 0.68 }],
                 bbox: [[p[0] - r, p[1] - r, p[2] - 2.2], [p[0] + r, p[1] + r, p[2] + 0.5]] });
  };
  KEYS.forEach(function (k) { cap(keyId(k[0]), [k[1], k[2], k[3]], KR); });
  cap('k-shift', SHIFTK, KR * 1.15); cap('k-back', BACKK, KR);
  items.push({ id: 'k-space', part: 'box', at: SPACE.at, size: SPACE.size, bevel: 0.25, shadow: false });
  items.push({ id: 'keyboard', shapes: [], bbox: [[1.4, 20.3, 0.8], [39.4, 31.7, 5.9]], shadow: false });

  // ================================================================ the typed log: every keystroke, in time
  var LOG = [];
  var tail = null;
  function fresh() { return { col: 0, line: 1, typed: 0, strikes: 0, cells: [], above: [] }; }
  function lineText(cells) { var s = ''; for (var i = 0; i < cells.length; i++) { var c = cells[i]; s += c ? c.charAt(c.length - 1) : ' '; } return s.replace(/\s+$/, ''); }
  // one event on the model: it fills in what the drawing needs (columns before and after, the paper after it)
  function apply(e, st) {
    e.col0 = st.col; e.line0 = st.line;
    if (e.kind === 'ch' || e.kind === 'space') {
      if (st.col >= N) e.kind = e.kind === 'ch' ? 'lockch' : 'lock';     // the margin: the keys are locked
      else {
        if (e.kind === 'ch') { st.cells = st.cells.slice(); st.cells[st.col] = (st.cells[st.col] || '') + e.ch; st.typed++; st.strikes++; }
        else st.typed++;
        st.col++;
        e.bell = st.col === BELL_AT;
      }
    } else if (e.kind === 'back') { st.col = Math.max(0, st.col - 1); }
    else if (e.kind === 'ret') { st.above = [st.cells].concat(st.above).slice(0, 5); st.cells = []; st.col = 0; st.line++; }
    e.col1 = st.col; e.line = st.line; e.typed = st.typed; e.strikes = st.strikes;
    e.cells = st.cells; e.above = st.above;
    e.mv = e.kind === 'ret' ? { at: e.t + 0.04, dur: Math.min(0.75, 0.22 + 0.016 * e.col0) } : { at: e.t + PK, dur: STEPD };
    return e;
  }
  function replay() { tail = fresh(); LOG.forEach(function (e) { apply(e, tail); }); }
  replay();
  // a keystroke typed now drops what a step had scheduled after now (a demo word stops mid-word)
  function dropAfter(fx) {
    var n = LOG.length; while (LOG.length && LOG[LOG.length - 1].demo && LOG[LOG.length - 1].t > fx.tau + 1e-6) LOG.pop();
    if (LOG.length === n) return;
    replay();
    fx.hide('ding'); fx.hide('note');
    var last = LOG[LOG.length - 1], txt = lineText(tail.cells);
    var d = last ? Math.max(0, last.t + PK - fx.tau) : 0;
    if (txt || tail.line > 1) fx.say('line', txt ? txt.replace(/ /g, '\u00a0') : '\u21b5 line ' + tail.line, 'mute', { delay: d }); else fx.hide('line', { delay: d });
  }
  var audio = null;
  // one keystroke into the log at fx.tau + delay; the page's tags follow it (the typed line, the bell, the margin)
  var demo = false;                           // true while a step or the tour types (those keystrokes may be dropped)
  function add(fx, kind, ch, delay) {
    var last = LOG[LOG.length - 1], t = fx.tau + (fx.reduced ? 0 : (delay || 0));
    if (last && t <= last.t) t = last.t + 0.001;
    var e = apply({ t: t, kind: kind, ch: ch, demo: demo }, tail);
    if (kind === 'ch' && e.kind === 'ch') { var sl = SLUG[ch]; e.key = sl[0]; e.up = sl[1]; e.bar = BAR[sl[0]]; }
    if (kind === 'ch' && e.kind === 'lockch') { var sl2 = SLUG[ch]; e.key = sl2[0]; e.up = sl2[1]; }
    LOG.push(e);
    var at = { delay: e.t - fx.tau + PK }, txt = lineText(e.cells);
    if (e.kind === 'ch' || e.kind === 'ret') {
      // a new line shows its number at once (no fade) until its first letter lands
      fx.say('line', txt ? txt.replace(/ /g, '\u00a0') : '\u21b5 line ' + e.line, 'mute', at);
    }
    if (e.bell) { fx.say('ding', 'ding! ' + (N - BELL_AT) + ' to the margin', 'warm', { delay: e.t - fx.tau + PK + 0.06 }); fx.hide('ding', { delay: e.t - fx.tau + PK + 2.4 }); }
    if (e.kind === 'lock' || e.kind === 'lockch') { fx.say('note', 'margin: keys locked, press Return', 'hot', at); fx.hide('note', { delay: e.t - fx.tau + 1.8 }); }
    if (e.kind === 'ret') fx.hide('note', at);
    if (audio) audio(e, e.t - fx.tau + PK);
    return e;
  }
  function demoLine() {                       // the typing line holds only what a step or the tour typed
    if (!tail.col) return false;
    for (var i = LOG.length - 1; i >= 0 && LOG[i].kind !== 'ret'; i--) if (!LOG[i].demo) return false;
    return true;
  }
  function none(fx, ch) {                     // a character with no type on this machine: the fan stirs, nothing prints
    var e = add(fx, 'none', ch, 0);
    fx.say('note', 'no type for "' + ch + '" on this machine', 'mute', { delay: PK }); fx.hide('note', { delay: 1.6 });
    return e;
  }
  function keystroke(fx, ch, delay) {
    if (ch === '\n' || ch === '\r') return add(fx, 'ret', null, delay);
    if (ch === '\b') return add(fx, 'back', null, delay);
    if (ch === ' ' || ch === '\t' || ch === '\u00a0') return add(fx, 'space', ' ', delay);
    if (SLUG[ch]) return add(fx, 'ch', ch, delay);
    return none(fx, ch);
  }
  function word(fx, s, from, gap) {           // a step's demo: typed at a steady pace from `from` seconds
    s.split('').forEach(function (ch, i) { keystroke(fx, ch, from + i * gap); });
    return from + s.length * gap;
  }
  function sync(state) { state.typed = tail.typed; state.col = tail.col; state.line = tail.line; state.text = lineText(tail.cells); }

  // ---- the sound (live page only, after the viewer typed: a short synthesized clack, the bell's ding; no file)
  var live = typeof document !== 'undefined' && document.documentElement.hasAttribute('data-st-live');
  function sound() {
    if (!live || audio) return;
    var ua = typeof navigator !== 'undefined' && navigator.userActivation;
    if (!ua || !ua.isActive) return;
    try {
      var AC = window.AudioContext || window.webkitAudioContext; if (!AC) return;
      var ac = new AC(), out = ac.createGain(); out.gain.value = 0.5; out.connect(ac.destination);
      var noise = ac.createBuffer(1, Math.round(ac.sampleRate * 0.05), ac.sampleRate), d = noise.getChannelData(0), seed = 7;
      for (var i = 0; i < d.length; i++) { seed = (seed * 16807) % 2147483647; d[i] = (seed / 2147483647 * 2 - 1) * Math.pow(1 - i / d.length, 3); }
      audio = function (e, inS) {
        if (ac.state === 'suspended') ac.resume();
        var t0 = ac.currentTime + Math.max(0, inS);
        if (e.kind === 'ch' || e.kind === 'space') {
          var src = ac.createBufferSource(), bp = ac.createBiquadFilter(), g = ac.createGain();
          src.buffer = noise; bp.type = 'bandpass'; bp.frequency.value = e.kind === 'ch' ? 2400 : 900; bp.Q.value = 1.4;
          g.gain.value = e.kind === 'ch' ? 0.35 : 0.18; src.connect(bp); bp.connect(g); g.connect(out); src.start(t0);
        }
        if (e.bell) [[2093, 0.12], [5250, 0.04]].forEach(function (p) {
          var o = ac.createOscillator(), g2 = ac.createGain(); o.frequency.value = p[0];
          g2.gain.setValueAtTime(0.0001, t0 + 0.06); g2.gain.exponentialRampToValueAtTime(p[1], t0 + 0.07); g2.gain.exponentialRampToValueAtTime(0.0001, t0 + 1.4);
          o.connect(g2); g2.connect(out); o.start(t0 + 0.06); o.stop(t0 + 1.5);
        });
      };
    } catch (err) { audio = null; }
  }

  // ================================================================ the drawing at t: a pure function of t and LOG
  function lastAt(t) { var lo = 0, hi = LOG.length - 1, r = -1; while (lo <= hi) { var m = (lo + hi) >> 1; if (LOG[m].t <= t) { r = m; lo = m + 1; } else hi = m - 1; } return r; }
  var F = { t: NaN };                          // what one frame needs, computed once per t
  function frame(t) {
    if (F.t === t) return F;
    var i1 = lastAt(t), i0 = lastAt(t - LIFE), col = i0 >= 0 ? LOG[i0].col1 : 0, strikes = i0 >= 0 ? LOG[i0].strikes : 0, win = [];
    for (var i = i0 + 1; i <= i1; i++) {
      var e = LOG[i], p = inOutCubic(clamp((t - e.mv.at) / e.mv.dur, 0, 1));
      col += (e.col1 - e.col0) * p;
      if (e.kind === 'ch') strikes += outCubic(clamp((t - e.t - PK) / 0.3, 0, 1));
      win.push(e);
    }
    // the next keystrokes (a key goes down 0.05 s before its event): rises that already started
    for (var j = i1 + 1; j < LOG.length && LOG[j].t - 0.06 <= t; j++) win.push(LOG[j]);
    var dips = {}, vi = lastAt(t - PK), shift = 0;
    win.forEach(function (e) {
      var down = inOutCubic(clamp((t - e.t + 0.05) / 0.05, 0, 1)) * (1 - inOutCubic(clamp((t - e.t - 0.09) / 0.12, 0, 1)));
      if (down <= 0) return;
      var id = e.kind === 'ch' || e.kind === 'lockch' ? keyId(e.key) : e.kind === 'space' || e.kind === 'lock' ? 'k-space' : e.kind === 'back' ? 'k-back' : null;
      if (id) dips[id] = Math.max(dips[id] || 0, down);
      if (e.up) { var sh = inOutCubic(clamp((t - e.t + 0.05) / 0.05, 0, 1)) * (1 - inOutCubic(clamp((t - e.t - PK - 0.1) / 0.1, 0, 1))); dips['k-shift'] = Math.max(dips['k-shift'] || 0, down); shift = Math.max(shift, sh); }
    });
    F = { t: t, col: col, cx: HOME - col * STEP, strikes: strikes, win: win, dips: dips, shift: shift, view: vi >= 0 ? LOG[vi] : null };
    return F;
  }
  var RIDES = { carriage: 1, platen: 1, paper: 1, retlever: 1 };
  function offset(id, t) {
    var f = frame(t);
    if (RIDES[id]) return [f.cx, 0, 0];
    var d = f.dips[id]; return d ? [0, 0, -(id === 'k-space' ? 0.5 : 0.7) * d] : null;
  }
  function env(t, e) {                         // 0..1, exactly 1 at the strike's peak (e.t + PK)
    var d = t - e.t - PK;
    if (d < -RISE || d > FALL) return 0;
    if (d <= 0) { var a = (d + RISE) / RISE; return a * a; }
    return 1 - inOutSine(d / FALL);
  }

  // three layers in the drawing: under the parts, over them (both redrawn every frame), and the letters (the type on
  // the paper, the legends on the caps): persistent <text> nodes whose attributes change, so the page keeps its nodes
  var NS = 'http://www.w3.org/2000/svg', gU = null, gO = null, gT = null, gKeys = null, gRows = [], pools = [], keyEls = [];
  var mkEl = function (tag, parent, attrs) { var e = document.createElementNS(NS, tag); Object.keys(attrs || {}).forEach(function (a) { e.setAttribute(a, attrs[a]); }); parent.appendChild(e); return e; };
  function groups() {
    var w = document.getElementById('ld-world');
    if (!w) return false;
    if (!gU || !gU.isConnected) { gU = document.createElementNS(NS, 'g'); gU.setAttribute('id', 'tw-under'); w.insertBefore(gU, w.firstChild); }
    if (!gO || !gO.isConnected) { gO = mkEl('g', w, { id: 'tw-over' }); if (gT && gT.isConnected) w.appendChild(gT); }
    if (!gT || !gT.isConnected) {
      gT = mkEl('g', w, { id: 'tw-type', 'data-st-decor': '', 'font-size': 1, 'font-weight': 600, 'text-anchor': 'middle' });
      var paper = mkEl('g', gT, {}); gRows = []; pools = [];
      for (var r = 0; r < 5; r++) { gRows.push(mkEl('g', paper, { 'data-paper-line': r, 'data-text': '' })); pools.push([]); }
      gKeys = mkEl('g', gT, {}); keyEls = [];
      KEYS.concat([['\u2190', BACKK[0], BACKK[1], BACKK[2], 'k-back'], ['\u21e7', SHIFTK[0], SHIFTK[1], SHIFTK[2], 'k-shift']]).forEach(function (k) {
        var e = mkEl('text', gKeys, {}); e.textContent = k[4] ? k[0] : /[a-z]/.test(k[0]) ? k[0].toUpperCase() : k[0];
        keyEls.push({ el: e, k: k, id: k[4] || keyId(k[0]) });
      });
    }
    return true;
  }
  // one letter laid on a plane: ex one world unit along the line, ey one unit "down" the glyph, size in world units
  function setGlyph(e, s, ex, ey, size, col, op) {
    e.setAttribute('transform', 'matrix(' + [ex[0] * size, ex[1] * size, ey[0] * size, ey[1] * size, s[0], s[1]].map(function (v) { return Math.round(v * 1000) / 1000; }).join(' ') + ')');
    e.setAttribute('fill', col); e.setAttribute('fill-opacity', op); e.setAttribute('visibility', 'visible');
  }
  var f1 = function (v) { return (Math.round(v * 10) / 10).toString(); }, f3 = function (v) { return (Math.round(v * 1000) / 1000).toString(); };
  var HID = ' stroke-dasharray="7 5"', CEN = ' stroke-dasharray="22 5 3 5"';
  function onFrame(t, k) {
    if (!groups()) return;
    var TH = (window.Diagram && Diagram.current && Diagram.current.theme) || {};
    var dark = /dark/.test(TH.name || '') || (TH.ground && /^#[0-3]/.test(TH.ground));
    var hotC = (TH.tones && TH.tones.hot && (TH.tones.hot.flow || TH.tones.hot.face)) || '#E8552B', warmC = (TH.tones && TH.tones.warm && (TH.tones.warm.flow || TH.tones.warm.face)) || '#D9A02B';
    var inkC = TH.ink || '#3B4656', detC = TH.detail || '#8A95A5', mono = (TH.font && TH.font.mono) || 'JetBrains Mono, monospace';
    var LW = TH.lw || 1.5;
    // the type on the paper: dark on a light sheet, the theme's ink on a dark one
    var blade = String((TH.faces && TH.faces.blade) || '#ffffff'), bl = /^#[0-9a-f]{6}$/i.test(blade) ? [1, 3, 5].reduce(function (a, i) { return a + parseInt(blade.substr(i, 2), 16); }, 0) / 765 : 1;
    var typeC = bl < 0.45 ? inkC : '#20242c';
    var P = k.P, f = frame(t), u = '', o = '';
    var fa = k.focus || { amount: 0 }, fc = fa.fc, veil = fa.amount || 0;
    var lit = function (id) { return !!fc && (fc.part === id || (fc.with || []).indexOf(id) >= 0); };
    // a piece drawn here for a part: over the veil when that part is in focus, dimmed with the rest otherwise
    var put = function (id, svg, under) {
      if (!svg) return;
      if (veil > 0.01 && lit(id)) { o += svg; return; }
      if (under) { u += svg; return; }
      o += veil > 0.01 ? '<g opacity="' + f3(1 - 0.6 * veil) + '">' + svg + '</g>' : svg;
    };
    var path = function (q) { return 'M' + q.map(function (p) { var s = P(p[0], p[1], p[2]); return f1(s[0]) + ' ' + f1(s[1]); }).join('L'); };
    var stroke = function (q, col, w, extra) { return '<path d="' + path(q) + '" fill="none" stroke="' + col + '" stroke-width="' + f1(w) + '" stroke-linecap="round" stroke-linejoin="round"' + (extra || '') + '/>'; };
    var dot = function (p, r, col, extra) { var s = P(p[0], p[1], p[2]); return '<circle cx="' + f1(s[0]) + '" cy="' + f1(s[1]) + '" r="' + f1(r) + '" fill="' + col + '"' + (extra || '') + '/>'; };
    var O0 = P(0, 0, 0), vx = P(1, 0, 0), ex = [vx[0] - O0[0], vx[1] - O0[1]];
    gT.setAttribute('font-family', mono);
    var shiftDz = SHIFT_DROP * f.shift;
    // per bar: its strike now (several bars may be in flight; the same bar struck twice keeps the stronger)
    var barS = {}, fan = 0, ribbon = 0, escHot = 0, levers = {}, flash = [], bells = [], ret = null;
    f.win.forEach(function (e) {
      var s = env(t, e), age = t - e.t;
      if (e.kind === 'ch') { barS[e.bar] = Math.max(barS[e.bar] || 0, s); ribbon = Math.max(ribbon, s); levers[e.key] = Math.max(levers[e.key] || 0, age < -0.06 ? 0 : 1 - clamp((age - PK) / 0.5, 0, 1)); }
      if (e.kind === 'none') fan = Math.max(fan, s);
      if (e.kind === 'ch' || e.kind === 'space' || e.kind === 'back') escHot = Math.max(escHot, s);
      if (e.kind === 'ch' && age >= PK && age < PK + 0.22) flash.push(age - PK);
      if (e.bell && age >= PK + 0.06 && age < PK + 1.1) bells.push(age - PK - 0.06);
      if (e.kind === 'ret' && age >= -0.05 && age < 0.9) ret = { age: age, e: e };
    });
    // hidden lines: every key lever, dashed, under the keyboard; the struck ones lit, a packet running along them
    KEYS.forEach(function (key) {
      var lv = levers[key[0]] || 0;
      if (lv <= 0.004) put('levers', stroke(lever(key, shiftDz), detC, LW * 0.8, HID), true);
    });
    // the segment (a heavy arc of pivots), the rest pad, the centre line through the print point
    var arc = [], pad = [];
    for (var a = 0; a <= 48; a++) {
      var th = deg(172 - 164 * a / 48);
      arc.push([PP[0] + SEG.r * Math.cos(th), PP[1] + SEG.r * Math.sin(th), SEG.z - shiftDz]);
      pad.push([PP[0] + (SEG.r + LB * 0.99) * Math.cos(th), PP[1] + (SEG.r + LB * 0.99) * Math.sin(th), SEG.z - LB * 0.16 - shiftDz]);
    }
    put('basket', stroke(pad, detC, LW * 3, ' stroke-opacity="0.9"'), true);
    put('segment', stroke([[PP[0], PP[1] + SEG.r + LB + 1.5, SEG.z], [PP[0], PP[1] - 0.6, SEG.z]], detC, LW * 0.8, CEN), true);
    // typebars at rest in the basket, each with its slug; a character with no type stirs the whole fan
    var rest = '';
    for (var i = 0; i < NB; i++) {
      if ((barS[i] || 0) > 0.004) continue;
      var pv = pivot(i, shiftDz), tp = tip(i, 0, shiftDz), hot = fan > 0.004;
      rest += stroke([pv, tp], hot ? hotC : inkC, LW * 1.1, hot ? ' stroke-opacity="' + f3(0.35 + 0.65 * fan) + '"' : ' stroke-opacity="0.85"') + dot(tp, LW * 1.5, hot ? hotC : inkC);
    }
    put('basket', rest, true);
    put('segment', stroke(arc, f.shift > 0.02 ? hotC : inkC, LW * 3.2), true);
    // lit levers: the path key -> lever -> typebar, a packet running along it (from the key going down to the strike)
    var litL = '';
    Object.keys(levers).forEach(function (ch) {
      var lv = levers[ch]; if (lv <= 0.004) return;
      var key = KEY[ch], L3 = lever(key, shiftDz), top = [key[1], key[2], key[3] + 0.5];
      litL += stroke(L3, hotC, LW * 1.8, HID + ' stroke-opacity="' + f3(0.3 + 0.7 * lv) + '"');
      f.win.forEach(function (e) {
        if (e.kind !== 'ch' || e.key !== ch) return;
        var q = clamp((t - (e.t - 0.05)) / (PK + 0.05), 0, 1); if (q <= 0 || t - e.t > PK + 0.06) return;
        var route = [top, L3[0], L3[1], L3[2]], seglen = [], tot = 0;
        for (var r = 1; r < route.length; r++) { var dd = Math.hypot(route[r][0] - route[r - 1][0], route[r][1] - route[r - 1][1], route[r][2] - route[r - 1][2]); seglen.push(dd); tot += dd; }
        var at = function (qq) { var want = qq * tot; for (var r2 = 0; r2 < seglen.length; r2++) { if (want <= seglen[r2] || r2 === seglen.length - 1) { var pp = clamp(want / seglen[r2], 0, 1); return [lerp(route[r2][0], route[r2 + 1][0], pp), lerp(route[r2][1], route[r2 + 1][1], pp), lerp(route[r2][2], route[r2 + 1][2], pp)]; } want -= seglen[r2]; } return route[route.length - 1]; };
        var trail = []; for (var z = 0; z <= 8; z++) trail.push(at(Math.max(0, q - 0.35 + 0.35 * z / 8)));
        litL += stroke(trail, hotC, LW * 2.6, ' stroke-opacity="0.55"') + dot(at(q), LW * 3, hotC, dark ? ' filter="url(#ld-glow)"' : '');
      });
    });
    put('levers', litL);
    // struck typebars: the swing arc (dashed), a short ghost trail, the bar, the type at its tip
    var bars = '';
    Object.keys(barS).forEach(function (bi) {
      var i2 = +bi, s = barS[bi]; if (s <= 0.004) return;
      var pv2 = pivot(i2, shiftDz), sw = [];
      for (var q2 = 0; q2 <= 24; q2++) sw.push(tip(i2, q2 / 24, shiftDz));
      bars += stroke(sw, hotC, LW * 0.8, ' stroke-dasharray="3 5" stroke-opacity="' + f3(0.7 * Math.min(1, s * 2.5)) + '"');
      [[0.066, 0.14], [0.033, 0.3]].forEach(function (g) {
        var sg = 0; f.win.forEach(function (e) { if (e.kind === 'ch' && e.bar === i2) sg = Math.max(sg, env(t - g[0], e)); });
        if (Math.abs(sg - s) > 0.02) bars += stroke([pv2, tip(i2, sg, shiftDz)], hotC, LW * 1.8, ' stroke-opacity="' + g[1] + '"');
      });
      bars += '<g filter="url(#ld-glowsoft)">' + stroke([pv2, tip(i2, s, shiftDz)], hotC, LW * 2.6) + '</g>' + dot(tip(i2, s, shiftDz), LW * 2.6, hotC) + dot(pv2, LW * 1.6, hotC);
    });
    put('basket', bars);
    // the ribbon: spool to spool through the vibrator, lifted in front of the print point on a strike
    var vz = PP[2] - 1.1 + 0.9 * ribbon, rib = '';
    SPOOLS.forEach(function (p, si) {
      var rot = f.strikes * 0.32 * (si ? -1 : 1), ring = [];
      for (var q3 = 0; q3 <= 36; q3++) { var a3 = q3 * Math.PI / 18; ring.push([p[0] + 1.25 * Math.cos(a3), p[1] + 1.25 * Math.sin(a3), p[2]]); }
      rib += stroke(ring, detC, LW * 0.8);
      for (var sp = 0; sp < 3; sp++) { var th3 = rot + sp * Math.PI * 2 / 3; rib += stroke([p, [p[0] + 1.6 * Math.cos(th3), p[1] + 1.6 * Math.sin(th3), p[2]]], inkC, LW * 1.1); }
      rib += dot(p, LW * 1.4, inkC);
    });
    rib += stroke([[SPOOLS[0][0] + 1.5, SPOOLS[0][1] - 1.1, SPOOLS[0][2]], [PP[0] - 2.4, PP[1] + 0.45, vz], [PP[0] + 2.4, PP[1] + 0.45, vz], [SPOOLS[1][0] - 1.5, SPOOLS[1][1] - 1.1, SPOOLS[1][2]]],
                  ribbon > 0.02 ? hotC : inkC, LW * 1.6, ' stroke-opacity="' + f3(ribbon > 0.02 ? 0.55 + 0.45 * ribbon : 0.8) + '"');
    put('ribbon', rib);
    // the paper: the typed lines laid on the sheet (it rides with the carriage); the line feed scrolls them up
    var view = f.view, cells = view ? view.cells : [], above = view ? view.above : [];
    var feed = 0;
    if (ret && view === ret.e) feed = 1 - inOutCubic(clamp((ret.age - PK) / 0.22, 0, 1));
    var upv = [0, -0.255, 1], Pu = P(upv[0], upv[1], upv[2]), ey = [-(Pu[0] - O0[0]), -(Pu[1] - O0[1])];
    var paperOp = veil > 0.01 && !lit('paper') ? 1 - 0.6 * veil : 1;
    [cells].concat(above).forEach(function (cl, r) {
      var z = Z0 + (r - feed) * LF, pool = pools[r], n = 0, g = gRows[r];
      if (!g) return;
      g.setAttribute('data-text', lineText(cl));
      g.setAttribute('opacity', f3(paperOp * (r >= 4 ? 0.45 : 1)));
      if (z <= 15.0) {
        var y = paperY(z) - 0.03;
        for (var c = 0; c < cl.length; c++) {
          var cc = cl[c]; if (!cc) continue;
          for (var l = 0; l < cc.length; l++) {
            var fresh2 = r === 0 && c === view.col0 && view.kind === 'ch' && t - view.t - PK < 0.3 && l === cc.length - 1;
            var e = pool[n] || (pool[n] = mkEl('text', g, {})); n++;
            if (e.textContent !== cc.charAt(l)) e.textContent = cc.charAt(l);
            setGlyph(e, P(PAPER[0] + MARGIN + c * STEP + f.cx, y, z - 0.27), ex, ey, 0.74, fresh2 ? hotC : typeC, 1);
          }
        }
      }
      for (var j = n; j < pool.length; j++) if (pool[j].getAttribute('visibility') !== 'hidden') pool[j].setAttribute('visibility', 'hidden');
    });
    for (var r2 = 1 + above.length; r2 < gRows.length; r2++) {
      gRows[r2].setAttribute('data-text', '');
      pools[r2].forEach(function (e) { if (e.getAttribute('visibility') !== 'hidden') e.setAttribute('visibility', 'hidden'); });
    }
    // the platen's centre line (dash-dot, it rides with the carriage) and the print point's mark, flashing on a strike
    var pq = P(PP[0], PP[1], PP[2]), mk = 9, ppS = '';
    ppS += '<path d="M' + f1(pq[0] - mk) + ' ' + f1(pq[1]) + 'H' + f1(pq[0] + mk) + 'M' + f1(pq[0]) + ' ' + f1(pq[1] - mk) + 'V' + f1(pq[1] + mk) + '" stroke="' + inkC + '" stroke-width="' + f1(LW) + '"/>';
    flash.forEach(function (d) {
      var al = 1 - d / 0.22;
      ppS += '<circle cx="' + f1(pq[0]) + '" cy="' + f1(pq[1]) + '" r="' + f1(7 + d * 110) + '" fill="none" stroke="' + hotC + '" stroke-width="' + f1(LW * 1.6) + '" opacity="' + f3(al) + '"/>';
      ppS += '<circle cx="' + f1(pq[0]) + '" cy="' + f1(pq[1]) + '" r="' + f1(6 * al + 1.5) + '" fill="' + hotC + '" opacity="' + f3(al) + '"' + (dark ? ' filter="url(#ld-glow)"' : '') + '/>';
    });
    put('platen', stroke([[2.6 + f.cx, PLATEN.y, PLATEN.z], [41.4 + f.cx, PLATEN.y, PLATEN.z]], inkC, LW * 0.7, CEN + ' stroke-opacity="0.75"'));
    put('pp', ppS);
    // the escapement: the star wheel turns with the carriage (1/16 turn a letter), lit as it lets go a tooth
    var esc = [], rot3 = f.col * Math.PI * 2 / 16, escS = '';
    for (var q4 = 0; q4 <= 64; q4++) { var th4 = rot3 + q4 * Math.PI / 32, rr = q4 % 4 === 0 ? 1.62 : (q4 % 4 === 2 ? 1.1 : 1.36); esc.push([ESC[0] + rr * Math.cos(th4), ESC[1] + rr * Math.sin(th4), ESC[2]]); }
    escS += stroke(esc, escHot > 0.02 ? hotC : inkC, LW * (escHot > 0.02 ? 1.8 : 1.3));
    escS += stroke([ESC, [ESC[0] + 0.9 * Math.cos(rot3), ESC[1] + 0.9 * Math.sin(rot3), ESC[2]]], inkC, LW * 1.1) + dot(ESC, LW * 1.4, inkC);
    escS += stroke([[ESC[0], ESC[1] + 1.4, ESC[2]], [ESC[0], 4.3, 7.4]], detC, LW * 0.8, HID);
    put('escapement', escS);
    // the mainspring: a spiral that unwinds as the carriage goes left, wound again by Return; its band to the carriage
    var sp2 = [], turn = -f.col * 0.09, msS = '';
    for (var q5 = 0; q5 <= 110; q5++) { var th5 = turn + q5 * deg(14), r5 = 0.2 + q5 * 0.0165; sp2.push([SPRING[0] + r5 * Math.cos(th5), SPRING[1] + r5 * Math.sin(th5), SPRING[2]]); }
    var winding = ret ? Math.sin(Math.PI * clamp((ret.age - 0.04) / ret.e.mv.dur, 0, 1)) : 0;
    msS += stroke(sp2, winding > 0.02 ? warmC : inkC, LW * (1 + 0.6 * winding));
    msS += stroke([[SPRING[0] + 0.2, SPRING[1] - 2.0, SPRING[2] - 0.5], [SPRING[0] + 0.2, 5.4, 6.4], [4.4 + f.cx, PLATEN.y - 0.9, PLATEN.z - 0.7]], winding > 0.02 ? warmC : detC, LW * 1.5);
    put('mainspring', msS);
    // the return lever: lit while pulled
    if (ret) {
      var rl = Math.sin(Math.PI * clamp((ret.age + 0.05) / 0.4, 0, 1));
      if (rl > 0.01) put('retlever', stroke([[4.2 + f.cx, 7.6, 9.6], [2.6 + f.cx, 8.4, 11.6], [0.4 + f.cx, 8.8, 12.4]], hotC, LW * 2.4, ' stroke-opacity="' + f3(rl) + '"'));
    }
    // the bell: rings (three arcs that spread) five letters before the margin
    var bS = '';
    bells.forEach(function (d) {
      var bq = P(BELL[0], BELL[1], BELL[2] + 2.0);
      for (var w = 0; w < 3; w++) {
        var dd = d - w * 0.12; if (dd < 0) continue;
        var al2 = clamp(1 - dd / 0.8, 0, 1), rr2 = 16 + dd * 70;
        bS += '<path d="M' + f1(bq[0] - rr2 * 0.9) + ' ' + f1(bq[1] - rr2 * 0.25) + 'A' + f1(rr2) + ' ' + f1(rr2 * 0.6) + ' 0 0 1 ' + f1(bq[0] + rr2 * 0.9) + ' ' + f1(bq[1] - rr2 * 0.25) +
              '" fill="none" stroke="' + warmC + '" stroke-width="' + f1(LW * 1.6) + '" stroke-linecap="round" opacity="' + f3(al2) + '"/>';
      }
    });
    put('bell', bS);
    // the keys: their legends on the caps (they go down with the key), lit while pressed
    var P1 = P(0, 1, 0), eyk = [P1[0] - O0[0], P1[1] - O0[1]], keyTx = '';
    gKeys.setAttribute('opacity', f3(veil > 0.01 && !lit('keyboard') ? 1 - 0.6 * veil : 1));
    keyEls.forEach(function (x) {
      var key = x.k, dz = f.dips[x.id] || 0, top = [key[1], key[2], key[3] + 0.5 - 0.7 * dz];
      setGlyph(x.el, P(top[0], top[1] + 0.28, top[2]), ex, eyk, 1.0, dz > 0.05 ? hotC : inkC, dz > 0.05 ? 1 : 0.8);
      if (dz > 0.05) keyTx += dot(top, KR * S * 0.75, hotC, ' fill-opacity="' + f3(0.18 * dz) + '"');
    });
    var spd = f.dips['k-space'] || 0;
    if (spd > 0.05) keyTx += stroke([[SPACE.at[0] + 0.6, SPACE.at[1] + 0.85, SPACE.at[2] + SPACE.size[2] - 0.5 * spd + 0.02], [SPACE.at[0] + SPACE.size[0] - 0.6, SPACE.at[1] + 0.85, SPACE.at[2] + SPACE.size[2] - 0.5 * spd + 0.02]], hotC, LW * 3, ' stroke-opacity="' + f3(spd) + '"');
    put('keyboard', keyTx);
    gU.innerHTML = u; gO.innerHTML = o;
  }

  // ---------------------------------------------------------------- the part names (callouts) and the tags
  var scr = function (p) { return [O[0] + (p[0] - p[1]) * C30 * S, O[1] + (p[0] + p[1]) * 0.5 * S - p[2] * S]; };
  var L = [];
  var lab = function (o2, title, sub, elbow, side) {
    var l = Object.assign(o2, { at: -3, title: title, sub: sub });
    l.elbow = elbow; l.side = side;
    L.push(l);
  };
  lab({ for: 'keyboard', anchor: [SHIFTK[0] - 1.2, SHIFTK[1] + 0.5, SHIFTK[2] + 0.5] }, 'Keys', 'one per letter', live ? [-60, 110] : [-30, 170], 'left');   // the film: under the step's words
  lab({ for: 'basket', anchor: tip(3, 0) }, 'Typebars', 'one per key, in a fan', [-40, -170], 'left');
  lab({ anchor: [PP[0] + 0.6, 4.8, 15.2] }, 'Carriage', 'a letter left per key', [80, -40], 'right');  // the paper's top edge, always on the sheet  // on the platen wherever it is
  lab({ for: 'escapement', anchor: [ESC[0] + 1.62, ESC[1], ESC[2]] }, 'Escapement', 'a tooth a letter', [40, -45], 'right');
  lab({ for: 'mainspring', anchor: [SPRING[0] - 1.45, SPRING[1] + 1.45, SPRING[2] - 1.2] }, 'Mainspring', 'pulls the carriage left', [-220, -45], 'left');
  lab({ for: 'bell', anchor: [BELL[0] + 1.3, BELL[1] + 0.6, BELL[2] + 1.6] }, 'Bell', 'rings at ' + BELL_AT + ' of ' + N, [40, 45], 'right');
  var TAGS = [
    // the typed line, readable: its right end over the print point's column, above the paper's highest corner
    { id: 'line', anchor: [PP[0], 4.8, 15.2], text: 'line', at: 1e9, tone: 'mute', off: [0, Math.round(scr([PAPER[0] + HOME - N * STEP, 4.8, 15.2])[1] - scr([PP[0], 4.8, 15.2])[1] - 34)], align: 'right', size: 30 },
    { id: 'ding', anchor: [BELL[0], BELL[1], BELL[2] + 2.4], text: 'ding', at: 1e9, tone: 'warm', off: [0, -78] },
    { id: 'note', anchor: [43, 18, 0.8], text: 'note', at: 1e9, tone: 'hot', off: [70, 72] },
  ];

  // ---------------------------------------------------------------- the steps, each typed through the same path
  var cr = function (fx, delay) { return tail.col > 0 ? (keystroke(fx, '\n', delay), delay + 0.75) : delay; };
  // the demo phrase, a keystroke at a time: step 1 types its next letter, the tour the rest; it starts again on a
  // fresh line when anything else was typed in between
  var PHRASE = 'hello world', pi = 0, pLast = null;
  function phrase(fx, delay, all) {
    if (pLast !== LOG[LOG.length - 1] || pi >= PHRASE.length || tail.col >= N) { pi = 0; delay = cr(fx, delay); }
    do { pLast = keystroke(fx, PHRASE.charAt(pi++), delay); delay += 0.14; } while (all && pi < PHRASE.length);
    return delay;
  }
  var STEPS = [
    { id: 'key', kicker: 'One keystroke', text: 'A key pulls its lever; the typebar swings up and strikes through the ribbon; the escapement lets the carriage step one letter left.',
      narr: 'Press a key: its lever pulls the typebar up out of the basket, it strikes the paper through the inked ribbon, and the escapement lets the carriage step one letter to the left.',
      run: function (fx) { phrase(fx, 0.3, false); } },
    { id: 'bell', kicker: 'A line and the bell', text: 'Five letters before the margin the bell rings; at the margin the keys lock.',
      narr: 'Type a line: five letters before the margin the bell rings, and at the margin the keys lock until you return the carriage.',
      run: function (fx) { var d = cr(fx, 0.3); d = word(fx, 'now is the time for all good', d, 0.115); keystroke(fx, 'm', d + 0.3); } },
    { id: 'return', kicker: 'Carriage return', text: 'The lever runs the carriage home against the mainspring and turns the platen up one line.',
      narr: 'Pull the return lever: the carriage runs home, winding the mainspring again, and the platen turns the paper up one line.',
      run: function (fx) { var d = 0.3; if (tail.col === 0) d = word(fx, 'men', d, 0.13) + 0.25; keystroke(fx, '\n', d); } },
  ];
  var demoed = function (fn) { return function (fx, a, b) { demo = true; try { fn(fx, a, b); } finally { demo = false; } sync(fx.state); }; };
  STEPS.forEach(function (s) { s.run = demoed(s.run); });
  var typeWord = function (s, gap) { return demoed(function (fx) { word(fx, s, 0.05, gap || 0.14); }); };

  window.SCENE = {
    page: {
      kicker: 'Fig. 1 · Live figure', figno: 'Manual typewriter',
      title: 'How a typewriter *types*',
      dek: 'A key, a lever, a typebar, a strike; then the carriage steps one letter left.',
      footL: 'A generic manual typewriter, drawn; not a specific model.', footR: 'Line: ' + N + ' letters · bell at ' + BELL_AT, steps: { at: [112, 640], width: 430 },
    },
    world: { scale: S, origin: O },
    leaderCost: 3,
    items: items, labels: L, tags: TAGS,
    offset: offset, onFrame: onFrame,
    // the film (index.html): the machine right of the page's title column
    camera: [{ at: -10, dur: 0.01, zoom: 0.8, focus: [960, 590], to: [1160, 600] }, { at: 0.4, dur: CUE.duration - 0.4, zoom: 0.82, focus: [970, 585], to: [1150, 600] }],

    interactive: {
      film: 'tour',
      kicker: 'Live figure', title: 'Type on a typewriter',
      sub: 'A manual typewriter, inside. Type on your keyboard: the machine types it. Enter returns the carriage, Backspace steps back.',
      source: 'A generic manual typewriter, drawn; not a specific model. The line length is measured off the drawing.',
      camera: [{ at: -10, dur: 0.01, zoom: 1, focus: [960, 540], to: [960, 540] }],
      crop: { desk: [96, 84, 1846, 1040], phone: [370, 130, 1550, 1040] },
      type: { hint: 'Type on it', run: function (fx, ch, state) {
        dropAfter(fx); sound();
        // the viewer's first letter on a line the demo typed: a fresh line first, so what they type stands alone
        var d = 0; if (ch !== '\n' && ch !== '\b' && demoLine()) d = keystroke(fx, '\n', 0).mv.dur + 0.03;
        keystroke(fx, ch, d); sync(state);
      } },
      parts: [
        { id: 'keyboard', name: 'Keys', sub: 'one per letter; each pulls its own lever' },
        { id: 'k-space', name: 'Space bar', sub: 'steps the carriage, prints nothing (press it)', press: function (fx, state) { dropAfter(fx); keystroke(fx, ' ', 0); sync(state); } },
        { id: 'levers', name: 'Key levers', sub: 'carry the press back to the typebar' },
        { id: 'basket', name: 'Typebars', sub: 'one per key, fanned in the basket; it swings up to strike' },
        { id: 'segment', name: 'Segment', sub: 'the arc they pivot on; it drops for Shift' },
        { id: 'pp', name: 'Print point', sub: 'where every letter lands' },
        { id: 'ribbon', name: 'Ribbon', sub: 'inked; it lifts in front of the paper for each strike' },
        { id: 'platen', name: 'Platen', sub: 'the roller the paper wraps around' },
        { id: 'carriage', name: 'Carriage', sub: 'carries platen and paper; one letter left per key' },
        { id: 'escapement', name: 'Escapement', sub: 'lets the carriage go one tooth per letter' },
        { id: 'mainspring', name: 'Mainspring', sub: 'pulls the carriage left; Return winds it' },
        { id: 'bell', name: 'Bell', sub: 'rings ' + (N - BELL_AT) + ' letters before the margin' },
        { id: 'retlever', name: 'Return lever', sub: 'carriage home, a new line (press it)', press: function (fx, state) { dropAfter(fx); keystroke(fx, '\n', 0); sync(state); } },
      ],
      reset: function (fx) { dropAfter(fx); },
      steps: STEPS,
      readouts: function (s) {
        return {
          rows: [
            { part: 'keyboard', k: 'Characters typed', v: String(s.typed || 0), u: 'spaces included' },
            { part: 'carriage', k: 'Carriage', v: (s.col || 0) + ' of ' + N, u: 'letters along the line', tone: (s.col || 0) >= BELL_AT ? 'warm' : '' },
            { part: 'platen', k: 'Line', v: String(s.line || 1), u: 'on this sheet' },
          ],
          note: 'The bell rings at ' + BELL_AT + '; at ' + N + ' the keys lock. ' + N + ' letters: 15 units of paper between the margins over a step of ' + STEP + '.',
        };
      },
      // untouched, it types by itself (also the film: interactive.film = 'tour', CUE.duration = its length)
      tour: [
        [{ step: 'key' }, 1500],
        [demoed(function (fx) { phrase(fx, 0.05, true); }), 2000],
        [{ hover: 'basket' }, 2200], [{ hover: null }, 300],
        [{ step: 'bell' }, 6200],
        [{ step: 'return' }, 3200],
        [typeWord('Type on it.'), 3000],
        [{ hover: 'escapement' }, 2200], [{ hover: 'mainspring' }, 2200], [{ hover: null }, 600],
        [demoed(function (fx) { keystroke(fx, '\n', 0.1); }), 1800],
      ],
    },
  };
})();

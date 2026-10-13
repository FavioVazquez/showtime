/* "What happens when you press a key": a computer, inside, as a LIVE figure you type on (simplified, illustrative).
   The keyboard is drawn key by key (onFrame below): the key you press goes down and lights, the key matrix finds it,
   the keyboard controller turns it into its USB HID usage id (the standard code: 'a' is 0x04), and the code waits
   for the computer's next poll, then travels down the USB cable. The CPU takes an interrupt, the OS puts the event
   in its input queue, the text editor puts the character in its text (in RAM), the GPU draws the glyph into the
   next frame, and the screen shows it at its next refresh, scanning top to bottom. Several keys are in flight at
   once when you type fast. Everything is in slow motion (SLOW below); the times are typical and illustrative, from
   one place (MS), and a real machine adds layers (drivers, a compositor) and varies.
   The live page is figure.html (`showtime export html <project> --interactive`): type anywhere on it, or click a
   key. index.html films the tour (interactive.film = 'tour': the same live actions on the film's clock), so
   CUE.duration is the tour's length. To use it: `showtime new diagram <dir> --example computer --theme white`. */
var CUE = {
  duration: 30.2,
};

(function () {
  /* ---------------- the numbers: typical, illustrative (one place) ---------------- */
  var SLOW = 30;                                         // slow motion: 1 ms is drawn as 30 ms
  var MS = { scan: 5, os: 1, app: 2, gpu: 3, show: 10 }; // scan + debounce, USB + interrupt + OS, the app, drawing, the screen showing it
  var SCREEN_HZ = 60;                                    // the screen's refresh rate
  var POLL = [['125', 'every 8 ms'], ['500', 'every 2 ms'], ['1000', 'every 1 ms']], POLLDEF = '1000';
  var sec = function (ms) { return ms * SLOW / 1000; };  // real ms -> seconds on screen
  var FRAME = sec(1000 / SCREEN_HZ), READY = sec(MS.scan), SWEEP = sec(MS.show), GPUT = sec(MS.gpu);
  var TT = 0.3, HOP = 0.16, NPK = 14, LINE = 24;        // drawn travel (not to scale), packets in flight, characters a line shows

  /* ---------------- USB HID usage ids, Keyboard/Keypad page (0x07): the codes a USB keyboard sends ---------------- */
  var HID = {};
  'abcdefghijklmnopqrstuvwxyz'.split('').forEach(function (c, i) { HID[c] = 0x04 + i; });
  '1234567890'.split('').forEach(function (c, i) { HID[c] = 0x1E + i; });
  var SPECIAL = { '\n': 0x28, '\b': 0x2A, '\t': 0x2B, ' ': 0x2C, '-': 0x2D, '=': 0x2E, '[': 0x2F, ']': 0x30, '\\': 0x31, ';': 0x33, "'": 0x34, '`': 0x35, ',': 0x36, '.': 0x37, '/': 0x38,
    caps: 0x39, ctlL: 0xE0, shiftL: 0xE1, altL: 0xE2, guiL: 0xE3, ctlR: 0xE4, shiftR: 0xE5, altR: 0xE6, guiR: 0xE7 };
  Object.keys(SPECIAL).forEach(function (k) { HID[k] = SPECIAL[k]; });
  var SHIFTED = { '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8', '(': '9', ')': '0', '_': '-', '+': '=',
    '{': '[', '}': ']', '|': '\\', ':': ';', '"': "'", '~': '`', '<': ',', '>': '.', '?': '/' };
  var NAME = { '\n': 'Enter', '\b': 'Backspace', '\t': 'Tab', ' ': 'Space', caps: 'Caps Lock', ctlL: 'Ctrl', ctlR: 'Ctrl', shiftL: 'Shift', shiftR: 'Shift',
    altL: 'Alt', altR: 'Alt', guiL: 'Cmd/Win', guiR: 'Cmd/Win' };
  var hex = function (n) { return '0x' + ('0' + n.toString(16).toUpperCase()).slice(-2); };
  // a typed character -> {key: the key's id on the board, shift, code, ch} (null: no key on a US keyboard makes it alone)
  function keyOf(ch) {
    if (HID[ch] != null) return { key: ch, shift: false, code: HID[ch], ch: ch };
    var lo = ch.toLowerCase();
    if (lo !== ch && HID[lo] != null && lo.length === 1) return { key: lo, shift: true, code: HID[lo], ch: ch };
    if (SHIFTED[ch]) return { key: SHIFTED[ch], shift: true, code: HID[SHIFTED[ch]], ch: ch };
    return null;
  }
  function codeText(k, ch) {
    if (!k) return '"' + ch + '": no single key';
    var nm = NAME[k.key] || (k.shift ? ch : k.key);
    return nm + ' → ' + hex(k.code) + (k.shift ? ' + Shift' : '');
  }

  /* ---------------- the board ---------------- */
  var S = 14, U = 2.2, KX = 0.3, KY = 30.8, KZ = 1.0, CAP = 0.6;   // world scale; key pitch, the key area, the slab top, a keycap's height
  // ANSI rows in key widths: [id, width, legend]
  var ROWS = [
    [['`', 1], ['1', 1], ['2', 1], ['3', 1], ['4', 1], ['5', 1], ['6', 1], ['7', 1], ['8', 1], ['9', 1], ['0', 1], ['-', 1], ['=', 1], ['\b', 2, 'back']],
    [['\t', 1.5, 'tab'], ['q', 1], ['w', 1], ['e', 1], ['r', 1], ['t', 1], ['y', 1], ['u', 1], ['i', 1], ['o', 1], ['p', 1], ['[', 1], [']', 1], ['\\', 1.5]],
    [['caps', 1.75, 'caps'], ['a', 1], ['s', 1], ['d', 1], ['f', 1], ['g', 1], ['h', 1], ['j', 1], ['k', 1], ['l', 1], [';', 1], ["'", 1], ['\n', 2.25, 'enter']],
    [['shiftL', 2.25, '⇧'], ['z', 1], ['x', 1], ['c', 1], ['v', 1], ['b', 1], ['n', 1], ['m', 1], [',', 1], ['.', 1], ['/', 1], ['shiftR', 2.75, '⇧']],
    [['ctlL', 1.25, ''], ['altL', 1.25, ''], ['guiL', 1.75, ''], [' ', 6.25, ''], ['guiR', 1.75, ''], ['altR', 1.25, ''], ['ctlR', 1.5, '']],
  ];
  var KEYS = [], KEY = {};
  ROWS.forEach(function (row, r) {
    var off = 0;
    row.forEach(function (k) {
      var key = { id: k[0], r: r, x: KX + off * U, y: KY + r * U, w: k[1] * U, legend: k[2] != null ? k[2] : k[0].toUpperCase() };
      KEYS.push(key); KEY[k[0]] = key; off += k[1];
    });
  });
  // the monitor's panel and its screen (the y+ face, toward the keyboard)
  var MON = { x0: 10, x1: 38, y: -3, d: 1.2, z0: 3.5, z1: 15 }, MY = MON.y + MON.d;
  var SCR = { x0: MON.x0 + 0.7, x1: MON.x1 - 0.7, z0: MON.z0 + 0.7, z1: MON.z1 - 0.7, bar: 1.5 };

  /* ---------------- the model: what was typed, when (every drawing below reads these logs at t) ---------------- */
  var M = { text: '', count: 0, last: null, k: 0, q: 0, presses: [], frames: [{ at: -1e9, text: '' }], poll: [], poke: -1e9, bytes: -1e9, demo: 0 };
  var SCHED = {};   // a tag's own schedule, so keys typed fast never drop each other's later values
  // how: 'restore' marks a value that goes back to the text (RAM after its bytes were shown); 'feed' (a key's new
  // text) updates the restores after it, up to the next key's own value
  function sayAt(fx, tag, text, tone, at, how) {
    var s = SCHED[tag] || (SCHED[tag] = []), i = s.length;
    while (i > 0 && s[i - 1].at > at) i--;
    s.splice(i, 0, { at: at, text: text, tone: tone, how: how });
    if (how === 'feed') for (var r = i + 1; r < s.length && s[r].how !== 'feed'; r++) if (s[r].how === 'restore') s[r].text = text;
    for (var j = i; j < s.length; j++) {
      var e = s[j], o = { delay: e.at - fx.tau };
      if (e.text == null) fx.hide(tag, o); else fx.say(tag, e.text, e.tone, o);
    }
    if (s.length > 80) s.splice(0, s.length - 80);
  }
  function pollAt(t) { var hz = +POLLDEF, a = -1e9; M.poll.forEach(function (p) { if (p[0] <= t) { a = p[0]; hz = p[1]; } }); return { a: a, hz: hz }; }
  // the computer asks every 1/hz s; an ask reaches the keyboard TT later; the code goes with the first ask after it is ready
  function departAfter(ready, state) {
    var p = pollAt(ready), I = sec(1000 / p.hz), a = p.a < -1e8 ? 0 : p.a;
    return a + Math.ceil((ready - a - TT - 1e-9) / I) * I + TT;
  }
  function insertFrame(f) { var i = M.frames.length; while (i > 0 && M.frames[i - 1].at > f.at) i--; M.frames.splice(i, 0, f); if (M.frames.length > 400) M.frames.splice(1, 1); }
  var shownLine = function (text) { var ls = text.split('\n'); return ls[ls.length - 1].replace(/\t/g, ' ').slice(-LINE); };
  var onScreen = function (line) { return 'on screen: ' + (line ? line.replace(/ /g, '\u00a0') : '(empty line)'); };
  var buffer = function (text) { var b = text.replace(/\n/g, '\\n').replace(/\t/g, '\\t'); return '"' + (b.length > 10 ? '…' + b.slice(-9) : b) + '"'; };
  var bytes = function (text) {
    var b = unescape(encodeURIComponent(text.slice(-5))), out = [];
    for (var i = 0; i < b.length; i++) out.push(('0' + b.charCodeAt(i).toString(16).toUpperCase()).slice(-2));
    return out.length ? out.slice(-6).join(' ') : 'empty';
  };

  // one key, through the whole path: fx.tau is the moment it is pressed
  function typeKey(fx, ch, state) {
    var k = keyOf(ch), t0 = fx.tau;
    M.count++;
    if (ch === '\b') M.text = M.text.slice(0, -1); else M.text += ch;
    if (M.text.length > 2000) M.text = M.text.slice(-1000);
    var snap = M.text, ready = t0 + READY;
    if (k) M.presses.push({ at: t0, key: k.key, shift: k.shift });
    if (M.presses.length > 300) M.presses.splice(0, 100);
    var dep = departAfter(ready, state), cpuAt = dep + TT;
    var tQ = cpuAt + HOP, tE = tQ + 0.12 + HOP, tR = tE + 0.1 + HOP, tG = tR + HOP, done = tG + GPUT;
    var vs = Math.ceil((done - 1e-9) / FRAME) * FRAME, tS = vs + HOP;
    insertFrame({ at: tS, text: snap });
    var waitMs = (dep - ready) / SLOW * 1000, frameMs = (vs - done) / SLOW * 1000;
    M.last = { ch: ch, k: k, wait: waitMs, total: MS.scan + waitMs + MS.os + MS.app + MS.gpu + frameMs + MS.show, hz: pollAt(ready).hz };
    var d = function (t) { return { delay: t - t0 }; }, tok = 'pk' + (M.k++ % NPK), slot = 'queue.slot' + (1 + (M.q++ % 4)), up = [0, 0, 0.7];
    fx.send(tok, [
      { at: READY, dur: 0.01, to: 'ctrl.top' },
      { at: dep - t0, dur: TT, along: 'usb' },
      { at: cpuAt - t0, dur: HOP, along: 'p2c', off: up },
      { at: tQ - t0, dur: HOP, along: 'c2q', off: up },
      { at: tQ - t0 + HOP, dur: 0.12, to: slot, off: [0, 0, 0.3] },
      { at: tE - t0 - HOP, dur: HOP, along: 'q2e', off: up },
      { at: tE - t0 + 0.1, dur: HOP, along: 'e2r', off: up },
      { at: tR - t0, dur: HOP, along: 'r2g', off: up },
      { at: vs - t0, dur: HOP, along: 'g2s', off: [0, 0, 0.4] },
    ]);
    fx.pulse('ctrl', 'cold', d(ready));
    sayAt(fx, 'code', codeText(k, ch), 'cold', ready);
    fx.pulse('port', 'cold', d(cpuAt - 0.05));
    fx.pulse('cpu', 'warm', Object.assign(d(cpuAt), { dur: 0.6, amount: 0.6 }));
    sayAt(fx, 'irq', 'IRQ', 'warm', cpuAt); sayAt(fx, 'irq', null, null, cpuAt + 1.0);
    fx.pulse('queue', 'cold', d(tQ + HOP));
    fx.pulse('editor', 'cold', d(tE));
    fx.pulse('ram', 'cold', d(tR));
    sayAt(fx, 'buffer', buffer(snap), 'cold', tR, 'feed');
    fx.pulse('gpu', 'warm', Object.assign(d(tG), { dur: GPUT + 0.3 }));
    sayAt(fx, 'screen', onScreen(shownLine(snap)), 'mute', tS + SWEEP);
  }
  // a key that types nothing (a modifier, Caps Lock): it is found and its code goes to the OS, no character
  function modifierKey(fx, id, state) {
    var t0 = fx.tau, ready = t0 + READY, dep = departAfter(ready, state), tok = 'pk' + (M.k++ % NPK), up = [0, 0, 0.7];
    M.presses.push({ at: t0, key: id, shift: false });
    fx.send(tok, [{ at: READY, dur: 0.01, to: 'ctrl.top' }, { at: dep - t0, dur: TT, along: 'usb' }, { at: dep + TT - t0, dur: HOP, along: 'p2c', off: up },
      { at: dep + TT + HOP - t0, dur: HOP, along: 'c2q', off: up }, { at: dep + TT + 2 * HOP - t0, dur: 0.12, to: 'queue.slot1', off: [0, 0, 0.3] }]);
    sayAt(fx, 'code', (NAME[id] || id) + ' → ' + hex(HID[id]), 'cold', ready);
    fx.pulse('ctrl', 'cold', { delay: READY });
    fx.pulse('cpu', 'warm', { delay: dep + TT - t0, dur: 0.6, amount: 0.6 });
  }

  // a click on the screen: the next refresh scans a frame in again (the same text), the caret holds still a moment
  function refresh(fx) { M.poke = fx.tau; insertFrame({ at: Math.ceil(fx.tau / FRAME) * FRAME, text: M.text }); }

  /* ---------------- clicking a key: the key under the pointer (the live page only) ---------------- */
  var PTR = null, CAM = null, KEYHIT = [], CLICKED = false;
  function bindPointer() {
    var fig = document.querySelector('.fg-fig'); if (!fig || fig.__pcBound) return; fig.__pcBound = true;
    fig.addEventListener('pointerdown', function (e) { PTR = { x: e.clientX, y: e.clientY }; }, true);
    // a key click types; it does not pin the keyboard (the veil would hide the path the key takes)
    fig.addEventListener('click', function () {
      PTR = null;   // a pointer is good for its own click only
      if (!CLICKED) return; CLICKED = false;
      var F = window.Figure && Figure.current; if (F && F.S.pin === 'keyboard') F.pin('keyboard');
    });
  }
  function keyUnderPointer() {
    if (!PTR || !CAM) return null;
    var svg = document.querySelector('#ld-world'); svg = svg && svg.ownerSVGElement; if (!svg || !svg.getScreenCTM()) return null;
    var pt = svg.createSVGPoint(); pt.x = PTR.x; pt.y = PTR.y; pt = pt.matrixTransform(svg.getScreenCTM().inverse());
    var x = (pt.x - CAM.ex) / CAM.z, y = (pt.y - CAM.ey) / CAM.z;
    for (var i = KEYHIT.length - 1; i >= 0; i--) if (inPoly(x, y, KEYHIT[i].poly)) return KEYHIT[i].key;
    return null;
  }
  function inPoly(x, y, poly) {
    var inside = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      var a = poly[i], b = poly[j];
      if (((a[1] > y) !== (b[1] > y)) && (x < (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0])) inside = !inside;
    }
    return inside;
  }
  function clickKey(fx, s) {
    var key = keyUnderPointer();
    if (key) { CLICKED = true; PTR = null; }
    if (!key) { var demo = 'hello '; typeKey(fx, demo.charAt(M.demo++ % demo.length), s); return; }   // from the parts list: a letter of "hello"
    if (key.id === 'shiftL' || key.id === 'shiftR' || key.id === 'caps' || /^(ctl|alt|gui)/.test(key.id)) modifierKey(fx, key.id, s);
    else typeKey(fx, key.id, s);
  }

  /* ---------------- drawing what the parts library has no part for (pure in t: from the logs above) ---------------- */
  var C = Math.cos(Math.PI / 6);
  var f1 = function (n) { return String(Math.round(n * 10) / 10); };
  var mix = function (a, b, p) {
    var pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16), o = '#';
    [16, 8, 0].forEach(function (sh) { var x = Math.round(((pa >> sh) & 255) * (1 - p) + ((pb >> sh) & 255) * p); o += ('0' + x.toString(16)).slice(-2); });
    return o;
  };
  function pressAmount(t, at) { var u = t - at; return u < 0 ? 0 : u < 0.05 ? u / 0.05 : u < 0.2 ? 1 : u < 0.32 ? 1 - (u - 0.2) / 0.12 : 0; }
  function onFrame(t, o) {
    var world = document.querySelector('#ld-world'), api = window.Diagram && Diagram.current;
    if (!world || !api) return;
    var g = world.querySelector('#pc-over');
    if (!g) { g = document.createElementNS('http://www.w3.org/2000/svg', 'g'); g.setAttribute('id', 'pc-over'); world.appendChild(g); }
    bindPointer();
    CAM = o.cam;
    var L = api.theme, P = o.P, pts = function (a) { return a.map(function (p) { return f1(p[0]) + ',' + f1(p[1]); }).join(' '); };
    var poly = function (a, fill, stroke, w, extra) { return '<polygon points="' + pts(a) + '" fill="' + fill + '" stroke="' + (stroke || L.ink) + '" stroke-width="' + (w || L.lw * 0.8) + '" stroke-linejoin="round"' + (extra || '') + '/>'; };
    var cold = L.tones.cold, warm = L.tones.warm, fa = o.focus || { amount: 0 }, fc = fa.fc;
    var dim = function (ids) { return fa.amount > 0 && !(fc && ids.indexOf(fc.part) >= 0) ? 1 - (1 - (L.dimTo || 0.4)) * fa.amount : 1; };
    var out = '';

    /* the keyboard: each key a cap that goes down and lights; the key matrix under them, x-rayed while it scans */
    var recent = M.presses.filter(function (p) { return p.at <= t && t - p.at < 1.4; });
    var down = {}, lit = {};
    recent.forEach(function (p) {
      down[p.key] = Math.max(down[p.key] || 0, pressAmount(t, p.at)); lit[p.key] = Math.max(lit[p.key] || 0, 1 - (t - p.at) / 1.1);
      if (p.shift) { down.shiftL = Math.max(down.shiftL || 0, pressAmount(t, p.at - 0.04)); lit.shiftL = Math.max(lit.shiftL || 0, 1 - (t - p.at) / 1.1); }
    });
    var kb = '', hits = [];
    KEYS.forEach(function (k) {
      var gp = 0.13, x0 = k.x + gp, x1 = k.x + k.w - gp, y0 = k.y + gp, y1 = k.y + U - gp, dz = -0.38 * (down[k.id] || 0), z0 = KZ, z1 = KZ + CAP + dz, sc = 0.16;
      var lv = Math.max(0, lit[k.id] || 0), top = lv > 0 ? mix(L.faces.top, cold.flow, 0.75 * lv) : L.faces.top;
      var front = lv > 0 ? mix(L.faces.left, cold.flow, 0.6 * lv) : L.faces.left, side = lv > 0 ? mix(L.faces.right, cold.flow, 0.6 * lv) : L.faces.right;
      kb += poly([P(x1, y0, z0), P(x1, y1, z0), P(x1 - sc, y1 - sc, z1), P(x1 - sc, y0 + sc, z1)], side, null, L.lw * 0.6);
      kb += poly([P(x0, y1, z0), P(x1, y1, z0), P(x1 - sc, y1 - sc, z1), P(x0 + sc, y1 - sc, z1)], front, null, L.lw * 0.6);
      kb += poly([P(x0 + sc, y0 + sc, z1), P(x1 - sc, y0 + sc, z1), P(x1 - sc, y1 - sc, z1), P(x0 + sc, y1 - sc, z1)], top, null, L.lw * 0.6);
      if (k.legend) {
        var c = P(x0 + 0.42, (y0 + y1) / 2 + 0.28, z1), big = k.legend.length === 1;
        kb += '<text transform="matrix(' + [C, 0.5, -C, 0.5].map(function (v) { return Math.round(v * 1000) / 1000; }).join(' ') + ' ' + f1(c[0]) + ' ' + f1(c[1]) + ')" font-family="' + L.font.mono + '" font-size="' + (big ? 15 : 12) +
          '" font-weight="600" data-st-decor="1" fill="' + (lv > 0.35 ? '#FFFFFF' : L.floorInk) + '">' + k.legend.replace(/&/g, '&amp;').replace(/</g, '&lt;') + '</text>';
      }
      hits.push({ key: k, poly: [P(x0, y0, z1), P(x1, y0, z1), P(x1, y0, z0), P(x1, y1, z0), P(x0, y1, z0), P(x0, y1, z1)] });
    });
    KEYHIT = hits;
    // the matrix: rows sweep while the controller scans, then the pressed key's row and column light where they cross
    var mx = '', zl = KZ + CAP + 0.05;
    recent.forEach(function (p) {
      var key = KEY[p.key], u = t - p.at; if (!key || u > READY + 0.7) return;
      var a = u < READY ? 1 : 1 - (u - READY) / 0.7, sweep = Math.min(4, Math.floor((u / READY) * 5)), ry = function (r) { return KY + (r + 0.5) * U; };
      if (u < READY) mx += '<path d="M' + pts([P(KX, ry(sweep), zl), P(KX + 15 * U, ry(sweep), zl)]).replace(/ /g, 'L') + '" stroke="' + cold.flow + '" stroke-width="2" opacity="0.45" fill="none"/>';
      var cx = key.x + key.w / 2;
      mx += '<path d="M' + pts([P(KX, ry(key.r), zl), P(KX + 15 * U, ry(key.r), zl)]).replace(/ /g, 'L') + '" stroke="' + cold.flow + '" stroke-width="3.4" opacity="' + f1(0.9 * a * Math.min(1, u / READY)) + '" fill="none"/>';
      mx += '<path d="M' + pts([P(cx, KY, zl), P(cx, KY + 5 * U, zl)]).replace(/ /g, 'L') + '" stroke="' + cold.flow + '" stroke-width="3.4" opacity="' + f1(0.9 * a * Math.min(1, u / READY)) + '" fill="none"/>';
      var q = P(cx, ry(key.r), zl);
      if (u >= READY * 0.6) mx += '<circle cx="' + f1(q[0]) + '" cy="' + f1(q[1]) + '" r="' + f1(7 + 6 * Math.min(1, (u - READY * 0.6) / 0.25)) + '" fill="none" stroke="' + cold.flow + '" stroke-width="2.4" opacity="' + f1(a) + '"/>';
    });
    out += '<g opacity="' + f1(dim(['keyboard', 'ctrl'])) + '">' + kb + (mx ? '<g filter="url(#ld-glowsoft)">' + mx + '</g>' : '') + '</g>';

    /* the polls: the computer asks the keyboard for news at the polling rate (dots running up the cable) */
    var pp = api.pipes && api.pipes.usb;
    if (pp) {
      var dots = '', at = function (s) { var c = pp.cum, i = 1; while (i < c.length - 1 && c[i] < s) i++; var q = Math.max(0, Math.min(1, (s - c[i - 1]) / ((c[i] - c[i - 1]) || 1))); return [pp.scr[i - 1][0] + (pp.scr[i][0] - pp.scr[i - 1][0]) * q, pp.scr[i - 1][1] + (pp.scr[i][1] - pp.scr[i - 1][1]) * q]; };
      var segs = [[0, +POLLDEF]].concat(M.poll);
      segs.forEach(function (s, i) {
        var a0 = s[0], a1 = i + 1 < segs.length ? segs[i + 1][0] : Infinity, I = sec(1000 / s[1]);
        if (t < a0 || t - TT > a1) return;
        for (var n = Math.max(0, Math.ceil((t - TT - a0) / I)); a0 + n * I <= Math.min(t, a1); n++) {
          var f = (t - (a0 + n * I)) / TT; if (f < 0 || f > 1) continue;
          var q = at(pp.len * (1 - f));
          dots += '<circle cx="' + f1(q[0]) + '" cy="' + f1(q[1]) + '" r="2.6" fill="' + L.ground + '" stroke="' + L.tones.mute.flow + '" stroke-width="1.8"/>';
        }
      });
      out += '<g opacity="' + f1(dim(['keyboard', 'ctrl'])) + '">' + dots + '</g>';
    }

    /* the screen: the frame it shows (lines of the text, a caret); a new frame scans in top to bottom */
    var fr = M.frames, ci = 0; for (var i = 0; i < fr.length; i++) if (fr[i].at <= t) ci = i;
    var cur = fr[ci], prev = fr[Math.max(0, ci - 1)], sweep = t < cur.at + SWEEP ? (t - cur.at) / SWEEP : 1;
    var face = function (x0, z0, x1, z1) { return [P(x0, MY, z0), P(x1, MY, z0), P(x1, MY, z1), P(x0, MY, z1)]; };
    var sc = '', ztop = SCR.z1 - SCR.bar, lh = 1.9, fs = 24, cw = fs * 0.6 / S;
    sc += poly(face(SCR.x0, SCR.z0, SCR.x1, SCR.z1), L.name === 'dark' ? '#0E1726' : '#FBFCFD', L.ink, L.lw * 0.7);
    sc += poly(face(SCR.x0, ztop, SCR.x1, SCR.z1), L.name === 'dark' ? '#16233A' : '#EEF0F3', 'none', 0);
    [0, 1, 2].forEach(function (j) { var q = P(SCR.x0 + 0.8 + j * 0.7, MY, SCR.z1 - SCR.bar / 2); sc += '<ellipse cx="' + f1(q[0]) + '" cy="' + f1(q[1] + 2.5) + '" rx="3.4" ry="3.6" fill="' + L.detail + '"/>'; });
    var lines = function (text) { var ls = text.split('\n').map(function (l) { return l.replace(/\t/g, ' ').slice(-LINE); }); return ls.slice(-4); };
    var ink = L.name === 'dark' ? '#E5ECF6' : '#111827';
    var textOf = function (text, clip) {
      var s = '', ls = lines(text);
      ls.forEach(function (ln, j) {
        var b = P(SCR.x0 + 0.9, MY, ztop - 0.5 - (j + 1) * lh + 0.35);
        s += '<text transform="matrix(' + [C, 0.5, 0, 1].map(function (v) { return Math.round(v * 1000) / 1000; }).join(' ') + ' ' + f1(b[0]) + ' ' + f1(b[1]) + ')" font-family="' + L.font.mono + '" font-size="' + fs + '" font-weight="500" data-st-decor="1" fill="' + ink + '" xml:space="preserve"' + (clip ? ' clip-path="url(#' + clip + ')"' : '') + '>' +
          ln.replace(/&/g, '&amp;').replace(/</g, '&lt;') + '</text>';
      });
      return { s: s, n: ls.length, last: ls[ls.length - 1] || '' };
    };
    var zs = ztop - (ztop - SCR.z0) * sweep, now = textOf(cur.text, sweep < 1 ? 'pc-new' : null);
    if (sweep < 1) {
      sc += '<clipPath id="pc-new"><polygon points="' + pts(face(SCR.x0, zs, SCR.x1, ztop)) + '"/></clipPath><clipPath id="pc-old"><polygon points="' + pts(face(SCR.x0, SCR.z0, SCR.x1, zs)) + '"/></clipPath>';
      sc += textOf(prev.text, 'pc-old').s + now.s;
      sc += '<path d="M' + pts([P(SCR.x0, MY, zs), P(SCR.x1, MY, zs)]).replace(/ /g, 'L') + '" stroke="' + cold.flow + '" stroke-width="2.4" opacity="0.7" fill="none"/>';
    } else sc += now.s;
    // the caret: after the last character; steady just after a new frame or a click on the screen, else it blinks
    var shownAt = Math.max(cur.at + SWEEP, M.poke), steady = t - shownAt < 0.7, on = steady || Math.floor(t * 1.7) % 2 === 0;
    if (on && sweep >= 1) {
      var cz = ztop - 0.5 - now.n * lh, cx0 = SCR.x0 + 0.95 + now.last.length * cw;
      sc += poly([P(cx0, MY, cz + 0.1), P(cx0 + cw * 0.9, MY, cz + 0.1), P(cx0 + cw * 0.9, MY, cz + lh - 0.15), P(cx0, MY, cz + lh - 0.15)], cold.flow, 'none', 0);
    }
    out += '<g>' + sc + '</g>';   // the screen is the payoff: never veiled
    g.innerHTML = out;
  }
  /* ---------------- the scene ---------------- */
  var box = function (id, at, size, o) { return Object.assign({ id: id, part: 'box', at: at, size: size, build: -3, lift: 0 }, o || {}); };
  var node = function (id, icon, x, y, o) { return Object.assign({ id: id, part: 'node', icon: icon, at: [x, y, 0], r: 3.4, build: -3, lift: 0 }, o || {}); };
  var link = function (id, a, b, o) { return Object.assign({ id: id, kind: 'link', from: a, to: b, w: 3, layer: 'floor', build: [-3, 0.01] }, o || {}); };
  var toks = []; for (var i = 0; i < NPK; i++) toks.push({ id: 'pk' + i, tone: 'cold', shape: 'chip', size: [2.2, 1.6, 0.5], moves: [] });
  var tour = [];
  var typing = function (text, gap, last) {
    text.split('').forEach(function (ch, i) { tour.push([function (fx, s) { typeKey(fx, ch, s); }, i === text.length - 1 ? last : gap]); });
  };
  // the tour (and the film): a new line if there is text already, then "hello"; slower polls; Enter; a typo fixed
  tour.push([function (fx, s) { if (M.text && M.text.slice(-1) !== '\n') typeKey(fx, '\n', s); }, 300], [{ step: 'path' }, 1500]);
  typing('he', 1400, 1400);   // two keys slowly (each code can be read), then three fast: several in flight at once
  typing('llo', 270, 2600);
  tour.push([{ hover: 'cpu' }, 2400], [{ hover: null }, 500], [{ knob: ['poll', '125'], step: 'poll' }, 1400]);
  typing(' world', 300, 2000);
  tour.push([{ hover: 'ctrl' }, 1800], [{ hover: null }, 300]);
  tour.push([{ knob: ['poll', '1000'] }, 1200]);
  typing('!', 0, 2600);
  tour.push([{ step: 'budget' }, 1600]);
  typing('\nok?', 420, 600);
  typing('\b!', 600, 2400);
  tour.push([{ hover: 'screen' }, 300], [function (fx) { refresh(fx); }, 1200], [{ hover: null }, 800]);

  window.SCENE = {
    page: {
      kicker: 'Inside a computer · a live figure', figno: 'Slow motion · typical times',
      title: 'What happens when you *press a key*',
      dek: 'From your finger to light on the screen: a code, a cable, an interrupt, a buffer, a frame.',
      footL: 'Simplified and illustrative: real machines add layers (drivers, compositor) and vary.', footR: '', steps: { at: [112, 430], width: 500 },
    },
    world: { scale: S, origin: [847, 305] },
    leaderCost: 5,
    onFrame: onFrame,
    items: [
      // the computer: a board with the CPU, the OS input queue, the text editor, RAM and the GPU
      { id: 'board', part: 'plate', at: [37, 1, -1.2], size: [28, 28, 1.2], grid: 4, faces: 'coolFaces', build: -3, lift: 0 },
      { kind: 'floortext', at: [41, 28.6, 0], text: 'COMPUTER', at0: -3, size: 42 },
      box('port', [37.4, 18.5, 0], [2.2, 3, 1.4], { faces: 'padFaces' }),
      node('cpu', 'core', 45, 20, { scale: 0.95, r: 3.6 }),
      { id: 'queue', part: 'queue', at: [50.5, 23.6, 0], n: 4, slot: 2.2, gap: 0.5, along: 'x', build: -3, lift: 0 },
      node('editor', 'hub', 59.5, 15.5, { scale: 0.95, r: 3.3 }),
      box('ram', [53, 4, 0], [7, 4.6, 0.5], { faces: 'padFaces', shapes: [0, 1, 2].map(function (j) { return { kind: 'box', at: [53.5, 4.6 + j * 1.4, 0.5], size: [6, 0.5, 2.8], bevel: 0 }; }) }),
      box('gpu', [40.5, 4.5, 0], [9, 1.8, 4.2], { bevel: 0.3, shapes: [{ kind: 'fan', face: 'y+', plane: 6.3, c: [42.9, 2.1], R: 1.6, spin: function (t) { return t * 2.2; } },
        { kind: 'fan', face: 'y+', plane: 6.3, c: [47.1, 2.1], R: 1.6, spin: function (t) { return t * 2.2 + 1; } }] }),
      // the keyboard: a slab with its controller at the back (the keys are drawn in onFrame, each on its own)
      box('keyboard', [-0.5, 27.4, 0], [34.6, 15.4, KZ], { bevel: 0.3 }),
      box('ctrl', [26, 28, KZ], [3.4, 2.2, 0.5], { bevel: 0, faces: 'padFaces' }),
      // the screen: a panel on a stand (its face is drawn in onFrame)
      box('screen', [MON.x0, MON.y, MON.z0], [MON.x1 - MON.x0, MON.d, MON.z1 - MON.z0], { bevel: 0, footprint: [20, -5, 8, 5],
        shapes: [{ kind: 'box', at: [20, -5, 0], size: [8, 5, 0.4], bevel: 0.3 }, { kind: 'box', at: [23.2, -3.4, 0.4], size: [1.6, 1, 3], bevel: 0 }],
        ports: { in: { at: [14, 0.6, -3.1], face: 'top' } } }),
      // the wires: USB from the keyboard, the path on the board, the display cable to the screen
      link('usb', 'ctrl.top', 'port.top', { layer: null, w: 3.4, via: [[27.7, 27.1, 0.3], [27.7, 24.5, 0.05], [34.5, 20, 0.05]] }),
      link('p2c', 'port.bottom', 'cpu.center'), link('c2q', 'cpu.center', 'queue.slot1'), link('q2e', 'queue.slot4', 'editor.center'),
      link('e2r', 'editor.center', 'ram.bottom'), link('r2g', 'ram.bottom', 'gpu.bottom'),
      link('g2s', 'gpu.bottom', 'screen.in', { w: 3.4, via: [[38.5, 5.4, 0], [31, -0.5, 0]] }),
    ],
    tokens: toks,
    labels: [
      { for: 'keyboard', anchor: [6, 42.8, 0.5], at: -3, title: 'Keyboard' },
      { for: 'ctrl', at: -3, title: 'Controller', elbow: [-20, -140] },
      { for: 'cpu', at: -3, title: 'CPU' },
      { for: 'queue', at: -3, title: 'OS input queue', elbow: [-170, 40] },
      { for: 'editor', at: -3, title: 'Text editor', elbow: [40, 100] },
      { for: 'ram', at: -3, title: 'RAM', elbow: [60, -70] },
      { for: 'gpu', at: -3, title: 'GPU', elbow: [30, -95] },
      { for: 'screen', at: -3, title: 'Screen' },
    ],
    tags: [
      // focus: true: the board's words stay while a part is hovered (typing with a hand on the mouse)
      { id: 'code', focus: true, for: 'ctrl', text: 'HID usage id', at: -3, tone: 'mute', off: [0, -60] },
      { id: 'usb', focus: true, pipe: 'usb', text: 'USB', at: -3, tone: 'mute', off: [10, 58] },
      { id: 'irq', focus: true, for: 'cpu', text: 'IRQ', at: 1e9, tone: 'warm', off: [-70, -40], align: 'right' },
      { id: 'buffer', focus: true, for: 'ram', text: '""', at: -3, tone: 'mute', off: [55, 18], align: 'left' },
      { id: 'screen', focus: true, for: 'screen', text: onScreen(''), at: -3, tone: 'mute', off: [-170, 150], align: 'right' },
    ],
    camera: [{ at: -10, dur: 0.01, zoom: 0.86, focus: [960, 560], to: [1205, 585] }],

    interactive: {
      film: 'tour',
      kicker: 'Live figure', title: 'What happens when you press a key',
      sub: 'Type on your keyboard (or click a key): watch the key go down, its code travel, the CPU take an interrupt, and the screen draw it. In slow motion.',
      source: 'Simplified and illustrative: real machines add layers (drivers, compositor) and vary.',
      camera: [{ at: -10, dur: 0.01, zoom: 1.0, focus: [960, 560], to: [960, 560] }],
      crop: { desk: [150, 40, 1770, 1040], phone: [290, 110, 1710, 1000] },
      type: { hint: 'Type on it', run: function (fx, ch, state) { typeKey(fx, ch, state); } },
      parts: [
        { id: 'keyboard', name: 'Keyboard', sub: 'keys over a grid of wires; click a key to type it', press: clickKey },
        { id: 'ctrl', name: 'Keyboard controller', sub: 'finds the key, sends its USB code' },
        { id: 'cpu', name: 'CPU', sub: 'takes the interrupt, runs the driver', press: function (fx) {
          fx.pulse('port', 'warm'); fx.pulse('cpu', 'warm', { delay: 0.15, dur: 0.9, amount: 0.7 });
          sayAt(fx, 'irq', 'IRQ: keyboard', 'warm', fx.tau); sayAt(fx, 'irq', null, null, fx.tau + 1.6);
          fx.tone('p2c', 'warm'); fx.tone('p2c', null, { delay: 1.4 }); fx.tone('usb', 'warm'); fx.tone('usb', null, { delay: 1.4 });
        } },
        { id: 'queue', name: 'OS input queue', sub: 'input events wait here in order' },
        { id: 'editor', name: 'Text editor', sub: 'the app: puts the character in its text' },
        { id: 'ram', name: 'RAM', sub: 'holds the text (click: its bytes)', press: function (fx) {
          M.bytes = fx.tau; fx.pulse('ram', 'cold');
          sayAt(fx, 'buffer', bytes(M.text), 'cold', fx.tau); sayAt(fx, 'buffer', buffer(M.text), 'cold', fx.tau + 2.5, 'restore');
        } },
        { id: 'gpu', name: 'GPU', sub: 'draws the glyphs into the next frame', press: function (fx) {
          var vs = Math.ceil((fx.tau + GPUT) / FRAME) * FRAME;
          fx.pulse('gpu', 'warm', { dur: GPUT + 0.3 }); fx.send('pk' + (M.k++ % NPK), [{ at: vs - fx.tau, dur: HOP, along: 'g2s', off: [0, 0, 0.4] }]);
          insertFrame({ at: vs + HOP, text: M.text });
        } },
        { id: 'screen', name: 'Screen', sub: SCREEN_HZ + ' new frames a second', press: refresh },
      ],
      knobs: { poll: { label: 'USB polling rate', hint: 'how often the computer asks the keyboard (typical rates)', options: POLL, default: POLLDEF } },
      reset: function () {},
      steps: [
        { id: 'path', kicker: '1 · Type on it', text: 'Press a key: it goes down, the keyboard finds it, and its code travels to the screen. Slowed down about 30 times.',
          run: function (fx) {
            ['keyboard', 'ctrl', 'port', 'cpu', 'queue', 'editor', 'ram', 'gpu', 'screen'].forEach(function (id, j) { fx.pulse(id, 'cold', { delay: 0.2 + j * 0.22, dur: 0.8, amount: 0.45 }); });
          } },
        { id: 'poll', kicker: '2 · The computer asks', knob: 'poll',
          text: function (s) { var o = POLL.filter(function (p) { return p[0] === String(s.poll); })[0] || POLL[2]; return 'Over USB the keyboard speaks only when asked: ' + o[1] + ' (' + o[0] + ' Hz). A pressed key waits for the next ask.'; },
          run: function (fx) {
            var hz = +fx.state.poll; M.poll.push([fx.tau, hz]); if (M.poll.length > 50) M.poll.shift();
            sayAt(fx, 'usb', 'USB · ' + hz + ' Hz', 'cold', fx.tau); fx.pulse('port', 'cold');
          } },
        { id: 'budget', kicker: '3 · Where the time goes', text: 'On this simple path a key takes about 30 ms to reach your eyes; waiting for the screen costs more than USB.',
          run: function (fx) { fx.pulse('screen', 'warm', { delay: 0.2, dur: 1.2 }); fx.pulse('keyboard', 'warm', { delay: 0.2, dur: 1.2 }); } },
      ],
      readouts: function (s, step) {
        var hz = +s.poll, poll = 1000 / hz, typical = MS.scan + poll / 2 + MS.os + MS.app + MS.gpu + 1000 / SCREEN_HZ / 2 + MS.show;
        var r1 = function (v) { return (Math.round(v * 10) / 10).toFixed(1); };
        if (step === 'budget') return { rows: [
          { part: 'keyboard', k: 'Scan + debounce', v: MS.scan + ' ms' },
          { part: 'ctrl', k: 'Wait for the poll', v: r1(poll / 2) + ' ms', u: 'on average, up to ' + r1(poll) + ' at ' + hz + ' Hz' },
          { part: 'cpu', k: 'USB, interrupt, OS', v: MS.os + ' ms' },
          { part: 'editor', k: 'The editor', v: MS.app + ' ms' },
          { part: 'gpu', k: 'The GPU draws', v: MS.gpu + ' ms' },
          { part: 'screen', k: 'Wait for a refresh', v: r1(1000 / SCREEN_HZ / 2) + ' ms', u: 'on average, at ' + SCREEN_HZ + ' Hz' },
          { part: 'screen', k: 'The screen shows it', v: MS.show + ' ms' },
          { part: 'screen', k: 'Total, about', v: Math.round(typical) + ' ms', tone: 'cold' },
        ], note: 'Typical, illustrative numbers for a simple path. Measured machines often take longer (compositors, buffering).' };
        var L0 = M.last, k = L0 && L0.k;
        return { rows: [
          { part: 'keyboard', k: 'Keys pressed', v: String(M.count) },
          { part: 'ctrl', k: L0 ? 'Last key: ' + (k ? (NAME[k.key] || L0.ch) : L0.ch) : 'Last key', v: k ? hex(k.code) : '—', u: k ? 'USB HID usage id' + (k.shift ? ', with Shift (modifier 0x02)' : '') : 'type something', tone: 'cold' },
          { part: 'ctrl', k: 'It waited for the poll', v: L0 ? r1(L0.wait) + ' ms' : '—', u: 'up to ' + r1(poll) + ' ms at ' + hz + ' Hz' },
          { part: 'screen', k: 'Press to screen, about', v: Math.round(typical) + ' ms', u: 'typical for this simple path; illustrative', tone: 'cold' },
        ], note: 'Slow motion: 1 ms is drawn as ' + SLOW + ' ms. Typical, illustrative times.' };
      },
      tour: tour,
    },
  };
})();

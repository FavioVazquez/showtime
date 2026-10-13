/* A manual typewriter, inside (showtime X-ray mechanism library: typewriter).
   Design space: about 1430 x 930 units, the machine seen from the typist's side, keys at the bottom, the platen
   at the top. Each event is a keystroke: its key goes down, its typebar swings up to the print point and the
   ribbon lifts, PEAKING on the event's frame; the escapement lets the carriage step one letter on that frame.
   An event of kind "return" (showtime.json "xray": {"kinds": {"18": "return"}}) winds the mainspring back.
   Which key: only from evidence ("xray": {"text": "..."} = what the paper in the clip shows, one character per
   keystroke); without it the keystroke lights the typebar fan, never a guessed key. */
(function () {
  var deg = function (a) { return a * Math.PI / 180; };
  var ROWS = [['qwertyuiop', 493, 773, 81], ['asdfghjkl', 500, 867, 83], ['zxcvbnm,.-', 533, 953, 85.5]];
  var KEYS = [];
  ROWS.forEach(function (r) { r[0].split('').forEach(function (ch, i) { KEYS.push([ch, r[1] + i * r[3], r[2]]); }); });
  var BYX = KEYS.slice().sort(function (a, b) { return a[1] - b[1]; }), NB = BYX.length, BAR = {};
  BYX.forEach(function (k, i) { BAR[k[0]] = i; });
  var PP = [920, 286], CB = [920, 330], RX = 330, RY = 104;            // print point, typebar segment centre and radii
  var SPACE = [[693, 1012], [1293, 1012], [1293, 1056], [693, 1056]];
  var BODY = [[440, 244], [1460, 267], [1547, 600], [1547, 1080], [260, 1080], [300, 613]];
  function pivot(i) { var th = deg(166 - 152 * i / (NB - 1)); return [CB[0] + RX * Math.cos(th), CB[1] + RY * Math.sin(th)]; }
  function rest(i) { var p = pivot(i); return [p[0] + 0.62 * (CB[0] - p[0]), p[1] + 0.62 * (CB[1] - p[1])]; }

  XRAY.mechanism({
    name: 'typewriter',
    noun: 'keystrokes', noun1: 'keystroke', one: 'a keystroke', textLabel: 'on the paper',
    box: [250, 140, 1700, 1080],
    // four points to place on the clip's reference frame (showtime.json "xray": {"place": {...}})
    anchors: { key_q: [493, 773], key_p: [1222, 773], key_m: [1046, 953], print_point: PP },
    outline: BODY,
    headline: function (n) { return '<em>' + n + '</em> keystrokes,<br>seen from inside<br>the machine.'; },
    measured: function (n, text) {
      return 'Each keystroke lit up on the frame its sound was heard' + (text ? '; which key, read from the paper in the clip.' : '.');
    },
    drawn: 'Inside view: a generic manual typewriter, drawn, not this exact machine.',
    // the live page: pads that play the next event of each kind from the real clip
    touch: { verb: 'Type on it', by: 'ch' },
    draw: function (k) {
      var C = k.C, g = k.g, s = k.s, hot = k.hot && k.kind === 'event', ch = hot ? k.ch : null;
      var n = k.n, bar = ch && ch !== ' ' && BAR[ch.toLowerCase()] != null ? BAR[ch.toLowerCase()] : -1;
      var rets = k.ev.filter(function (e) { return e.kind === 'return'; });
      var ret = 0;                                 // 0..1 while a carriage return winds the spring back
      rets.forEach(function (e) { var d = k.since(e.i); if (d >= -2 && d < 25) ret = Math.max(ret, 1 - Math.abs(d - 8) / 17); });
      var panel = k.view === 'panel';
      if (panel) {                                 // the machine's outline and its keyboard, for the panel only
        k.poly(BODY, C.faint, 2);
        KEYS.forEach(function (key) { k.ell(key[1], key[2], 26, 22, (hot && key[0] === (ch || '').toLowerCase()) ? C.hot : C.faint, 2, 0, false); });
        k.poly(SPACE, ch === ' ' && hot ? C.hot : C.faint, 2);
      }
      // key levers under the cover: every key to its typebar
      BYX.forEach(function (key, i) { if (i === bar) return; k.seg([key[1], key[2] - 30], pivot(i), panel ? C.l(.16) : C.l(.12), 1.5); });
      // the typebar fan, at rest
      for (var i = 0; i < NB; i++) { if (i === bar) continue; k.seg(pivot(i), rest(i), hot && bar < 0 && ch !== ' ' ? C.hot : C.soft, 3.5); }
      var arc = []; for (var a = 0; a < 40; a++) { var th = deg(166 - 152 * a / 39); arc.push([CB[0] + RX * Math.cos(th), CB[1] + RY * Math.sin(th)]); }
      g.strokeStyle = C.line; g.lineWidth = k.lw(3); k.path(arc); g.stroke();
      // ribbon spools (they turn a little each keystroke) and the ribbon, lifted on a strike
      k.ell(640, 352, 46, 20, C.line, 3, deg(n * 9), true); k.ell(1200, 356, 46, 20, C.line, 3, deg(n * 9), true);
      g.strokeStyle = hot ? C.hot : C.soft; g.lineWidth = k.lw(3); k.path([[640, 340], [920, 300 - (hot ? s * 12 : 0)], [1200, 344]]); g.stroke();
      // escapement star wheel (one tooth per keystroke) and the carriage rack
      k.ell(1336, 430, 40, 18, hot ? C.hot : C.line, 3.5, deg(n * 360 / 16), true);
      k.seg([700, 240], [1690, 252], C.soft, 3);
      for (var r = 0; r < 40; r++) { var x = 700 + r * 24.75, y = 240 + r * 0.3; k.seg([x, y], [x + 8, y + 9], C.faint, 2); }
      k.seg([1336, 430], [1336, 252], hot ? C.hot : C.soft, 3);
      // mainspring drum: unwinds a little per letter, winds back on a return
      var turns = n * 0.06 * (1 - ret), sp = [];
      for (var q = 0; q <= 120; q++) { var aa = deg(q * 12) + turns, rr = 6 + q * 0.32; sp.push([560 + Math.cos(aa) * rr, 430 + Math.sin(aa) * rr * 0.45]); }
      g.strokeStyle = ret > 0.05 ? C.hot : C.line; g.lineWidth = k.lw(2.5); k.path(sp); g.stroke();
      k.seg([598, 430], [700, 244], ret > 0.05 ? C.hot : C.soft, 3);
      k.seg([560, 226], [470, 150], ret > 0.05 ? C.hot : C.soft, 6);
      // the struck key, its lever and its typebar on the way up; the type hits the print point on the event frame
      if (hot) {
        g.shadowColor = C.hot; g.shadowBlur = 22 * s;
        if (ch === ' ') k.poly(SPACE, C.hot, 5, k.since(k.cur) >= 0 && k.since(k.cur) < 3 ? C.hot : null);
        else if (bar >= 0) {
          var key = BYX[bar], pv = pivot(bar), rs = rest(bar), tip = [rs[0] + (PP[0] - rs[0]) * s, rs[1] + (PP[1] - rs[1]) * s];
          k.ell(key[1], key[2], 30, 26, C.hot, 5, 0, false); k.seg([key[1], key[2] - 30], pv, C.hot, 4); k.seg(pv, tip, C.hot, 7);
        }
        if (k.since(k.cur) >= 0 && k.since(k.cur) < 3 && ch !== ' ') k.dot(PP, Math.max(6, 16 * Math.min(1.5, k.scale)), C.hot);
        g.shadowBlur = 0;
      }
      // labels (drawn where there is room for them: the panel, or in place when there is no panel)
      k.label('typebars', [1180, 330], 120, -150, hot && ch !== ' ');
      k.label('key levers', [700, 640], -180, 40, hot);
      k.label('escapement', [1376, 430], 200, 40, hot);
      k.label('mainspring', [520, 430], -160, -60, ret > 0.05);
      k.label('print point', PP, -260, -140, hot && s > 0.8);
    }
  });
})();

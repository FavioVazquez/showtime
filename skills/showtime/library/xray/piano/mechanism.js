/* A piano, written as it is heard (showtime X-ray mechanism library: piano).
   Design space: 1000 x 440 units (the 9:16 panel, about 0.95 px per unit), a grand staff on top (treble and bass,
   brace, clefs and key signature drawn as paths, no music font needed) and an 88-key keyboard below.
   The staff scrolls left past a fixed playhead on the smooth tempo map (k.beat of k.rt, the recording's time: never a jump to
   the latest note). Each event is a strike: its notes (notes.json, joined to the event by the runtime) are written
   at the playhead, red on the event's frame, with their stems, flags, beams, dots, ledger lines and accidentals;
   their keys go down and light up on the keyboard while they sound.
   Measured: strike times (xray.json), pitches, key, tempo map and eighth-note rhythm (`showtime xray notes`).
   Set in showtime.json "xray": "meter" (beats per bar, e.g. 3; bar lines and the time signature appear only when
   it is set), "downbeat" (the beat of bar 1, default 0), "key" (a key name to override the one heard, or false to
   hide it), "min_confidence" (drop notes the model is less sure of), "px_per_beat".
   Without notes.json each strike is written as a rhythm slash on the treble staff, never a guessed pitch. */
(function () {
  var W = 1000, SP = 16, TT = 64, TB = TT + 4 * SP, BT = TB + 7 * SP, BB = BT + 4 * SP;
  var KY = 362, KH = 76, PLAY = 862, RISE = 3, HR = 9.4;
  var NAT = [0, 2, 4, 5, 7, 9, 11], LET = 'CDEFGAB', SHARPS = 'FCGDAEB', FLATS = 'BEADGCF';
  var MAJ = { C: 0, G: 1, D: 2, A: 3, E: 4, B: 5, 'F#': 6, 'C#': 7, F: -1, Bb: -2, Eb: -3, Ab: -4, Db: -5, Gb: -6, Cb: -7 };
  var PCN = { C: 0, 'C#': 1, Db: 1, D: 2, 'D#': 3, Eb: 3, E: 4, F: 5, 'F#': 6, Gb: 6, G: 7, 'G#': 8, Ab: 8, A: 9, 'A#': 10, Bb: 10, B: 11, Cb: 11 };
  // clefs as calligraphic ribbons: [x, y, width] in staff spaces, y up from the clef's line (G line, F line)
  var TREBLE = [[0.95, -1.95, 0.05], [1.05, -2.4, 0.12], [1.45, -2.62, 0.15], [1.85, -2.35, 0.17], [1.95, -1.6, 0.19],
    [1.85, -0.2, 0.21], [1.6, 1.6, 0.21], [1.5, 2.9, 0.19], [1.75, 4.0, 0.15], [2.05, 4.38, 0.1], [2.25, 3.9, 0.17],
    [2.05, 3.0, 0.31], [1.3, 2.0, 0.42], [0.45, 1.05, 0.44], [0.08, 0.0, 0.4], [0.45, -0.85, 0.3], [1.3, -1.12, 0.17],
    [2.15, -0.8, 0.23], [2.55, 0.0, 0.42], [2.25, 0.85, 0.38], [1.5, 1.08, 0.25], [0.85, 0.65, 0.17], [0.82, 0.0, 0.13],
    [1.2, -0.38, 0.09], [1.6, -0.25, 0.04]];
  var BASS = [[0.3, 0.0, 0.1], [0.45, 0.62, 0.22], [1.15, 0.98, 0.19], [1.95, 0.6, 0.32], [2.1, -0.3, 0.44],
    [1.7, -1.35, 0.36], [0.9, -2.15, 0.21], [0.15, -2.6, 0.06]];
  var M = null;                                   // the score, built on the first frame

  function fifthsOf(key) {
    if (typeof key !== 'string') return null;
    var m = key.replace(/♯/g, '#').replace(/♭/g, 'b').match(/^\s*([A-G][#b]?)\s*(major|minor|maj|min|m)?\s*$/i);
    if (!m) return null;
    if (m[2] && /^(minor|min|m)$/i.test(m[2])) {
      var rel = (PCN[m[1]] + 3) % 12, best = null;
      Object.keys(MAJ).forEach(function (n) { if (PCN[n] === rel && (best === null || Math.abs(MAJ[n]) < Math.abs(best))) best = MAJ[n]; });
      return best;
    }
    return MAJ[m[1]] != null ? MAJ[m[1]] : null;
  }
  function spell(midi, fifths, keyAlt) {        // -> {li, alt, step}: the letter in this key, the way a copyist would
    var pc = ((midi % 12) + 12) % 12, cands = [];
    for (var li = 0; li < 7; li++) for (var a = -1; a <= 1; a++) if ((NAT[li] + a + 12) % 12 === pc) cands.push({ li: li, alt: a });
    var pick = cands.filter(function (c) { return (keyAlt[LET[c.li]] || 0) === c.alt; })[0] ||
               cands.filter(function (c) { return c.alt === 0; })[0] ||
               cands.filter(function (c) { return c.alt === (fifths < 0 ? -1 : 1); })[0] || cands[0];
    pick.step = (Math.floor((midi - pick.alt) / 12) - 1) * 7 + pick.li;
    return pick;
  }
  function yOf(staff, step) { return staff === 't' ? TB - (step - 30) * SP / 2 : BB - (step - 18) * SP / 2; }

  function build(k) {
    var mus = k.music || {}, cfg = k.cfg || {}, raw = mus.notes || [], q = {}, vm = {}, vb = {}, evOf = {};
    (mus.quantized || []).forEach(function (d) { q[d.i] = d; });
    ((mus.voices || {}).melody || []).forEach(function (i) { vm[i] = 1; });
    ((mus.voices || {}).bass || []).forEach(function (i) { vb[i] = 1; });
    k.ev.forEach(function (e, ei) { if (e.kind !== 'skip') (e.notes || []).forEach(function (n) { evOf[n.i] = ei; }); });
    var fifths = cfg.key === false ? 0 : fifthsOf(typeof cfg.key === 'string' ? cfg.key : mus.key);
    var keyName = cfg.key === false ? null : (typeof cfg.key === 'string' ? cfg.key : mus.key) || null;
    if (fifths == null) { fifths = 0; keyName = null; }
    var keyAlt = {};
    for (var s = 0; s < Math.abs(fifths); s++) keyAlt[fifths > 0 ? SHARPS[s] : FLATS[s]] = fifths > 0 ? 1 : -1;
    var minc = cfg.min_confidence || 0;
    var notes = raw.filter(function (n) { return n.confidence == null || n.confidence >= minc; }).map(function (n, j) {
      var i = n.i != null ? n.i : j, qd = q[i], sp = spell(n.pitch, fifths, keyAlt);
      var fr = k.frameAt(n.t), ev = evOf[i];
      return { i: i, pitch: n.pitch, t: n.t, end: n.end || n.t + 0.3, beat: qd ? qd.beat : k.beat(n.t), dur: qd ? qd.dur_beats : 1,
               li: sp.li, alt: sp.alt, step: sp.step, ev: ev, show: ev != null ? k.ev[ev].frame : fr };
    });
    var byBeat = {};
    notes.forEach(function (n) { (byBeat[n.beat] = byBeat[n.beat] || []).push(n); });
    notes.forEach(function (n) {                 // the hands: the bass voice below, the melody above, the rest by nearness
      if (vb[n.i] && n.pitch < 67) n.staff = 'b';
      else if (vm[n.i]) n.staff = n.pitch >= 55 ? 't' : 'b';
      else {
        var same = byBeat[n.beat], mel = same.filter(function (o) { return vm[o.i]; })[0], bas = same.filter(function (o) { return vb[o.i]; })[0];
        n.staff = mel && bas ? (Math.abs(n.pitch - mel.pitch) <= Math.abs(n.pitch - bas.pitch) ? 't' : 'b') : (n.pitch >= 60 ? 't' : 'b');
      }
      n.y = yOf(n.staff, n.step);
    });
    var meter = cfg.meter > 0 ? cfg.meter : 0, down = cfg.downbeat || 0, mem = {};
    notes.slice().sort(function (a, b) { return a.beat - b.beat || a.pitch - b.pitch; }).forEach(function (n) {
      var bar = meter ? Math.floor((n.beat - down) / meter + 1e-6) : n.beat, key = n.staff + '|' + bar + '|' + n.step;
      var cur = mem[key] != null ? mem[key] : (keyAlt[LET[n.li]] || 0);
      n.acc = n.alt !== cur ? n.alt : null;      // -1 flat, 0 natural, 1 sharp
      if (meter) mem[key] = n.alt;
    });
    var cols = {};
    notes.forEach(function (n) { var key = n.staff + '|' + n.beat; (cols[key] = cols[key] || { staff: n.staff, beat: n.beat, notes: [] }).notes.push(n); });
    var bpm = (mus.tempo && mus.tempo.bpm) || 120;
    M = { notes: notes, cols: Object.keys(cols).map(function (c) { return cols[c]; }), fifths: fifths, keyAlt: keyAlt, keyName: keyName,
          meter: meter, down: down, bpm: bpm, has: !!raw.length,
          pxb: cfg.px_per_beat || Math.max(56, Math.min(140, 190 / (bpm / 60))),
          first: notes.length ? Math.min.apply(null, notes.map(function (n) { return n.beat; })) : 0,
          last: notes.length ? Math.max.apply(null, notes.map(function (n) { return n.beat + n.dur; })) : 0 };
    var ks = 86 + Math.abs(fifths) * 12;
    M.tsX = ks + 6; M.hx = ks + (meter ? 40 : 6) + 10;
  }

  // ------------------------------------------------------------------ drawing helpers (design units, y down)
  function spline(pts, n) {
    var out = [];
    for (var i = 0; i < pts.length - 1; i++) {
      var p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
      for (var s = 0; s < n; s++) {
        var t = s / n, t2 = t * t, t3 = t2 * t, o = [];
        for (var d = 0; d < 3; d++) o.push(0.5 * (2 * p1[d] + (-p0[d] + p2[d]) * t + (2 * p0[d] - 5 * p1[d] + 4 * p2[d] - p3[d]) * t2 + (-p0[d] + 3 * p1[d] - 3 * p2[d] + p3[d]) * t3));
        out.push(o);
      }
    }
    out.push(pts[pts.length - 1].slice());
    return out;
  }
  function ribbon(g, pts, ox, oy, sp, fill) {   // a stroke of varying width, filled
    var c = spline(pts, 10), L = [], R = [];
    for (var i = 0; i < c.length; i++) {
      var a = c[Math.max(0, i - 1)], b = c[Math.min(c.length - 1, i + 1)], dx = b[0] - a[0], dy = b[1] - a[1];
      var l = Math.hypot(dx, dy) || 1, nx = -dy / l, ny = dx / l, w = c[i][2] / 2;
      L.push([ox + (c[i][0] + nx * w) * sp, oy - (c[i][1] + ny * w) * sp]);
      R.push([ox + (c[i][0] - nx * w) * sp, oy - (c[i][1] - ny * w) * sp]);
    }
    g.beginPath(); L.forEach(function (p, i) { if (i) g.lineTo(p[0], p[1]); else g.moveTo(p[0], p[1]); });
    for (var j = R.length - 1; j >= 0; j--) g.lineTo(R[j][0], R[j][1]);
    g.closePath(); g.fillStyle = fill; g.fill();
  }
  function disc(g, x, y, r, fill) { g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fillStyle = fill; g.fill(); }
  function line(g, x0, y0, x1, y1, col, w) { g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.strokeStyle = col; g.lineWidth = w; g.stroke(); }
  function treble(g, x, col) { ribbon(g, TREBLE, x, TB - SP, SP, col); disc(g, x + 0.82 * SP, TB - SP + 1.95 * SP, 0.36 * SP, col); }
  function bass(g, x, col) {
    var fy = BT + SP;
    ribbon(g, BASS, x, fy, SP, col); disc(g, x + 0.42 * SP, fy, 0.36 * SP, col);
    disc(g, x + 2.6 * SP, fy - 0.5 * SP, 0.15 * SP, col); disc(g, x + 2.6 * SP, fy + 0.5 * SP, 0.15 * SP, col);
  }
  function accidental(g, kind, cx, cy, col) {
    g.strokeStyle = col; g.fillStyle = col; g.lineCap = 'butt';
    if (kind === 1) {                               // sharp
      line(g, cx - 2.6, cy - 1.25 * SP, cx - 2.6, cy + 1.35 * SP, col, 1.4); line(g, cx + 2.6, cy - 1.35 * SP, cx + 2.6, cy + 1.25 * SP, col, 1.4);
      [-0.42, 0.42].forEach(function (o) { g.beginPath(); g.moveTo(cx - 6, cy + o * SP + 2.2); g.lineTo(cx + 6, cy + o * SP - 2.2);
        g.lineTo(cx + 6, cy + o * SP - 6.4); g.lineTo(cx - 6, cy + o * SP - 2); g.closePath(); g.fill(); });
    } else if (kind === -1) {                       // flat
      line(g, cx - 4, cy - 1.9 * SP, cx - 4, cy + 0.5 * SP, col, 1.5);
      g.beginPath(); g.moveTo(cx - 4, cy + 0.5 * SP); g.bezierCurveTo(cx + 9, cy - 0.15 * SP, cx + 5, cy - 0.95 * SP, cx - 4, cy - 0.2 * SP);
      g.lineWidth = 2.4; g.stroke();
    } else {                                        // natural
      line(g, cx - 3, cy - 1.4 * SP, cx - 3, cy + 0.55 * SP, col, 1.4); line(g, cx + 3, cy - 0.55 * SP, cx + 3, cy + 1.4 * SP, col, 1.4);
      [-0.42, 0.42].forEach(function (o) { g.beginPath(); g.moveTo(cx - 3, cy + o * SP + 1.6); g.lineTo(cx + 3, cy + o * SP - 0.4);
        g.lineTo(cx + 3, cy + o * SP - 4.4); g.lineTo(cx - 3, cy + o * SP - 2.4); g.closePath(); g.fill(); });
    }
    g.lineCap = 'round';
  }
  function head(g, x, y, hollow, col) {
    g.save(); g.translate(x, y); g.rotate(-0.35); g.beginPath(); g.ellipse(0, 0, HR, 6.6, 0, 0, Math.PI * 2);
    if (hollow) { g.ellipse(0, 0, 6.4, 3.0, -0.35, 0, Math.PI * 2); }
    g.fillStyle = col; g.fill(hollow ? 'evenodd' : 'nonzero'); g.restore();
  }
  function flag(g, sx, tip, up, col) {
    var d = up ? 1 : -1;
    g.beginPath(); g.moveTo(sx - 0.8, tip);
    g.bezierCurveTo(sx + 1, tip + d * 10, sx + 15, tip + d * 15, sx + 14.5, tip + d * 29);
    g.bezierCurveTo(sx + 14, tip + d * 36, sx + 11, tip + d * 42, sx + 8, tip + d * 46);
    g.bezierCurveTo(sx + 11, tip + d * 38, sx + 11.5, tip + d * 30, sx + 5, tip + d * 24);
    g.bezierCurveTo(sx + 3, tip + d * 22, sx + 1, tip + d * 20, sx - 0.8, tip + d * 18);
    g.closePath(); g.fillStyle = col; g.fill();
  }
  function text(k, s, x, y, px, col, align) {
    var g = k.g; g.save(); g.shadowBlur = 0; g.font = '600 ' + (px / k.scale).toFixed(2) + 'px "IBM Plex Mono"';
    g.fillStyle = col; g.textAlign = align || 'left'; g.textBaseline = 'alphabetic'; g.globalAlpha = k.alpha * (k.labelAlpha == null ? 1 : k.labelAlpha);
    g.fillText(s, x, y); g.restore();
  }
  // a caption: in the 9:16 panel the page sets it in its caption row at the label size (k.caption), else drawn here
  function cap(k, s, x, y, px, col, align) { if (k.caption) k.caption(s, align === 'right' ? 'right' : 'left', col); else text(k, s, x, y, px, col, align); }

  // ------------------------------------------------------------------ one column of the score (a staff, a beat)
  function geom(col, vis) {
    var mid = col.staff === 't' ? TT + 2 * SP : BT + 2 * SP, below = -1e9, above = -1e9;
    vis.forEach(function (v) { below = Math.max(below, v.n.y - mid); above = Math.max(above, mid - v.n.y); });
    return { up: below >= above, dur: Math.min.apply(null, vis.map(function (v) { return v.n.dur; })),
             top: Math.min.apply(null, vis.map(function (v) { return v.n.y; })), bot: Math.max.apply(null, vis.map(function (v) { return v.n.y; })) };
  }
  function drawColumn(k, col, x, vis, G, beamTip) {
    var g = k.g, C = k.C, hotS = 0, staffTop = col.staff === 't' ? TT : BT, staffBot = col.staff === 't' ? TB : BB;
    vis.forEach(function (v) { hotS = Math.max(hotS, v.s); });
    var colCol = hotS > 0.05 ? C.hot : C.ink;
    // ledger lines
    for (var ly = staffTop - SP; ly >= G.top - 1; ly -= SP) line(g, x - 15, ly, x + 15, ly, C.i(.8), 1.6);
    for (ly = staffBot + SP; ly <= G.bot + 1; ly += SP) line(g, x - 15, ly, x + 15, ly, C.i(.8), 1.6);
    // heads (a second steps to the other side of the stem), dots, accidentals
    var sorted = vis.slice().sort(function (a, b) { return G.up ? a.n.step - b.n.step : b.n.step - a.n.step; }), prev = null, accN = 0;
    sorted.forEach(function (v) {
      var n = v.n, side = 0;
      if (prev && Math.abs(n.step - prev.n.step) === 1 && !prev.side) side = G.up ? 1 : -1;
      v.side = side; prev = v;
      var hx = x + side * (2 * HR - 1.5), c = v.s > 0.05 ? C.hot : C.ink;
      g.save(); g.globalAlpha *= v.a;
      if (v.s > 0.05) { g.shadowColor = C.hot; g.shadowBlur = 18 * v.s; }
      head(g, hx, n.y, n.dur >= 2, c);
      var onLine = ((n.step - (col.staff === 't' ? 30 : 18)) % 2 + 2) % 2 === 0;
      if (n.dur === 1.5 || n.dur === 3 || n.dur === 0.75) disc(g, x + HR + 7 + (side > 0 ? 2 * HR : 0), n.y - (onLine ? SP / 2 : 0), 2.6, c);
      if (n.acc != null) { accidental(g, n.acc, x - HR - 11 - (accN % 2) * 12, n.y, c); accN++; }
      g.restore();
    });
    if (G.dur >= 4) return;
    // the stem, with a flag when the eighth has no partner yet
    var sx = G.up ? x + HR - 0.9 : x - HR + 0.9;
    var tip = beamTip != null ? beamTip : (G.up ? G.top - 3.5 * SP : G.bot + 3.5 * SP);
    g.save(); if (hotS > 0.05) { g.shadowColor = C.hot; g.shadowBlur = 14 * hotS; }
    line(g, sx, G.up ? G.bot : G.top, sx, tip, colCol, 1.7);
    if (G.dur <= 0.5 && beamTip == null) flag(g, sx, tip, G.up, colCol);
    g.restore();
    return sx;
  }

  XRAY.mechanism({
    name: 'piano',
    noun: 'strikes', one: 'a strike',
    box: [0, 0, 1000, 440],
    anchors: { a0: [0, KY + KH], c8: [W, KY + KH], c4: [W * 23 / 52, KY], top: [W / 2, TT] },
    outline: [[0, KY], [W, KY], [W, KY + KH], [0, KY + KH]],
    headline: function (n) { return '<em>' + n + '</em> strikes,<br>the score written<br>from the sound.'; },
    measured: function () {
      return 'Each strike lit up on the frame its sound was heard; the pitches, key and tempo were read from the clip’s sound.';
    },
    drawn: 'Drawn: the notation (rhythm fitted to eighths of the measured tempo, the hands split by register), not the printed score.',
    // the live page: pads that play the next event of each kind from the real clip
    touch: { verb: 'Play it', by: 'note' },
    draw: function (k) {
      if (k.view === 'inplace') return;
      if (!M) build(k);
      var g = k.g, C = k.C, f = k.f, now = k.rt, bNow = k.beat(now), pxb = M.pxb, hx = M.hx;
      var o = k.pr(0, 0);
      g.save(); g.translate(o[0], o[1]); g.scale(k.scale, k.scale);
      var X = function (b) { return PLAY + (b - bNow) * pxb; };
      // the grid (beats, and bars when the meter is set): it scrolls everywhere, ahead of the playhead too
      g.save(); g.beginPath(); g.rect(hx, 0, W - hx, KY - 10); g.clip(); g.shadowBlur = 0;
      var b0 = Math.ceil(bNow - (PLAY - hx) / pxb) - 1, b1 = Math.floor(bNow + (W - PLAY) / pxb) + 1;
      for (var b = b0; b <= b1; b++) {
        if (b <= Math.floor(M.first) || (M.has && b > Math.ceil(M.last) + (M.meter || 1))) continue;
        var bx = X(b), bar = M.meter && ((b - M.down) % M.meter + M.meter) % M.meter === 0;
        bx -= 0.27 * pxb;                          // a bar line sits just before its downbeat
        if (bar) line(g, bx, TT, bx, BB, C.l(.55), 1.6);
        else { line(g, bx, TT - 7, bx, TT - 1, C.l(.3), 1.2); line(g, bx, BB + 1, bx, BB + 7, C.l(.3), 1.2); }
      }
      g.restore();
      // staff lines
      g.save(); g.shadowBlur = 0;
      for (var i = 0; i < 5; i++) { line(g, 14, TT + i * SP, W, TT + i * SP, C.l(.5), 1.3); line(g, 14, BT + i * SP, W, BT + i * SP, C.l(.5), 1.3); }
      g.restore();
      // the notes heard so far, written where the tempo map puts their beat
      g.save(); g.beginPath(); g.rect(hx, 0, W - hx, KY - 8); g.clip();
      if (M.has) {
        var shown = [];
        M.cols.forEach(function (col) {
          var x = X(col.beat); if (x < hx - 40 || x > W + 40) return;
          var vis = [];
          col.notes.forEach(function (n) {
            if (f < n.show - RISE) return;
            var s = n.ev != null ? k.env(n.ev) : 0, a = f >= n.show ? 1 : Math.max(0.15, s);
            vis.push({ n: n, s: s, a: a });
          });
          if (vis.length) shown.push({ col: col, x: x, vis: vis, G: geom(col, vis) });
        });
        // eighths in pairs on one beat share a beam (written once the second one is heard)
        var byKey = {}; shown.forEach(function (c) { byKey[c.col.staff + '|' + c.col.beat] = c; });
        shown.forEach(function (c) {
          if (c.G.dur !== 0.5 || c.col.beat % 1 !== 0) return;
          var d = byKey[c.col.staff + '|' + (c.col.beat + 0.5)];
          if (!d || d.G.dur !== 0.5) return;
          var mid = c.col.staff === 't' ? TT + 2 * SP : BT + 2 * SP;
          var up = Math.max(c.G.bot, d.G.bot) - mid >= mid - Math.min(c.G.top, d.G.top);
          c.G.up = d.G.up = up;
          var ya = up ? c.G.top - 3.5 * SP : c.G.bot + 3.5 * SP, yb = up ? d.G.top - 3.5 * SP : d.G.bot + 3.5 * SP;
          var dy = Math.max(-0.75 * SP, Math.min(0.75 * SP, yb - ya)), y0 = up ? Math.min(ya, yb - dy) : Math.max(ya, yb - dy);
          c.beam = { to: d, y0: y0, dy: dy }; c.tip = y0; d.tip = y0 + dy; d.beamed = true;
        });
        g.shadowColor = C.l(.8); g.shadowBlur = C.glow;
        shown.forEach(function (c) { c.sx = drawColumn(k, c.col, c.x, c.vis, c.G, c.tip); });
        shown.forEach(function (c) {
          if (!c.beam || c.sx == null || c.beam.to.sx == null) return;
          var d = c.beam.to, hot = Math.max.apply(null, c.vis.concat(d.vis).map(function (v) { return v.s; })), th = (c.G.up ? 1 : -1) * 0.5 * SP;
          g.save(); if (hot > 0.05) { g.shadowColor = C.hot; g.shadowBlur = 14 * hot; }
          g.beginPath(); g.moveTo(c.sx - 0.8, c.beam.y0); g.lineTo(d.sx + 0.8, c.beam.y0 + c.beam.dy);
          g.lineTo(d.sx + 0.8, c.beam.y0 + c.beam.dy + th); g.lineTo(c.sx - 0.8, c.beam.y0 + th); g.closePath();
          g.fillStyle = hot > 0.05 ? C.hot : C.ink; g.fill(); g.restore();
        });
      } else {
        // no notes.json: the rhythm only, a slash on the treble staff per strike
        k.ev.forEach(function (e, ei) {
          if (e.kind === 'skip' || f < e.frame - RISE) return;
          var x = X(k.beat(e.t)), s = k.env(ei), y = TT + 2 * SP;
          if (x < hx - 20 || x > W + 20) return;
          g.save(); if (s > 0.05) { g.shadowColor = C.hot; g.shadowBlur = 18 * s; }
          line(g, x - 8, y + 8, x + 8, y - 8, s > 0.05 ? C.hot : C.ink, 5); line(g, x + 7, y - 6, x + 7, y - 3.5 * SP, s > 0.05 ? C.hot : C.ink, 1.7);
          g.restore();
        });
      }
      g.restore();
      // the notes fade out under the clefs; the staff lines run on
      g.save(); g.shadowBlur = 0;
      var gr = g.createLinearGradient(hx, 0, hx + 70, 0); gr.addColorStop(0, C.bg(1)); gr.addColorStop(1, C.bg(0));
      g.fillStyle = gr; g.fillRect(hx - 2, 0, 72, KY - 8);
      for (i = 0; i < 5; i++) { line(g, hx - 2, TT + i * SP, hx + 70, TT + i * SP, C.l(.5), 1.3); line(g, hx - 2, BT + i * SP, hx + 70, BT + i * SP, C.l(.5), 1.3); }
      // the system: brace, line, clefs, key signature, time signature
      ribbon(g, [[10, -TT, 0.6], [4, -(TT + 30), 2.4], [5, -((TT + BB) / 2 - 22), 3.4], [-1, -(TT + BB) / 2, 0.8],
                 [5, -((TT + BB) / 2 + 22), 3.4], [4, -(BB - 30), 2.4], [10, -BB, 0.6]], 0, 0, 1, C.i(.85));
      line(g, 14, TT, 14, BB, C.l(.7), 2);
      treble(g, 24, C.i(.92)); bass(g, 26, C.i(.92));
      for (var a = 0; a < Math.abs(M.fifths); a++) {
        var tStep = M.fifths > 0 ? [38, 35, 39, 36, 33, 37, 34][a] : [34, 37, 33, 36, 32, 35, 31][a];
        accidental(g, M.fifths > 0 ? 1 : -1, 90 + a * 12, yOf('t', tStep), C.i(.92));
        accidental(g, M.fifths > 0 ? 1 : -1, 90 + a * 12, yOf('b', tStep - 14), C.i(.92));
      }
      if (M.meter) {
        g.font = '800 46px "Bricolage Grotesque"'; g.fillStyle = C.i(.92); g.textAlign = 'center'; g.textBaseline = 'alphabetic';
        [[TT, TB], [BT, BB]].forEach(function (s) { g.fillText(String(M.meter), M.tsX + 14, s[0] + 2 * SP + 1); g.fillText('4', M.tsX + 14, s[1] + 1); });
      }
      g.restore();
      // the playhead: where a note is written the frame it is heard
      g.save(); g.shadowBlur = 0;
      var ph = k.hot ? k.s : 0;                     // every strike flashes the playhead, pitch known or not
      if (ph > 0.05) { g.shadowColor = C.hot; g.shadowBlur = 16 * ph; }
      line(g, PLAY, TT - 2.2 * SP, PLAY, BB + 2.2 * SP, C.h(.55 + .45 * ph), 2 + 2.5 * ph);
      g.shadowBlur = 0;
      g.beginPath(); g.moveTo(PLAY - 7, TT - 2.2 * SP - 10); g.lineTo(PLAY + 7, TT - 2.2 * SP - 10); g.lineTo(PLAY, TT - 2.2 * SP); g.closePath(); g.fillStyle = C.h(.8); g.fill();
      g.restore();
      // the keyboard: 88 keys, the sounding ones down and lit, red on their strike
      var lit = {};
      M.notes.forEach(function (n) {
        if (f < n.show - RISE || now > n.end + 0.05) return;
        var s = n.ev != null ? k.env(n.ev) : 0, v = Math.max(s, f >= n.show && now <= n.end ? 0.32 : 0);
        if (v > (lit[n.pitch] || 0)) lit[n.pitch] = v;
      });
      var whites = [], ww;
      for (var m = 21; m <= 108; m++) if ([1, 3, 6, 8, 10].indexOf(m % 12) < 0) whites.push(m);
      ww = W / whites.length;
      g.save(); g.shadowBlur = 0;
      line(g, 0, KY - 4, W, KY - 4, C.l(.35), 2);
      whites.forEach(function (m, wi) {
        var v = lit[m] || 0, x = wi * ww, dy = v > 0.05 ? 2.5 : 0;
        g.beginPath(); g.rect(x + 1, KY + dy, ww - 2, KH - dy);
        if (v > 0.05) { g.fillStyle = C.h(Math.min(1, 0.25 + 0.75 * v)); g.fill(); }
        g.strokeStyle = C.l(.5); g.lineWidth = 1.2; g.stroke();
        if (m === 60) disc(g, x + ww / 2, KY + KH - 9, 2.6, C.l(.8));
      });
      whites.forEach(function (m, wi) {
        if (m + 1 > 108 || [1, 3, 6, 8, 10].indexOf((m + 1) % 12) < 0) return;
        var v = lit[m + 1] || 0, x = (wi + 1) * ww - ww * 0.31, dy = v > 0.05 ? 2 : 0;
        g.beginPath(); g.rect(x, KY + dy, ww * 0.62, KH * 0.6);
        g.fillStyle = C.bg(1); g.fill();
        g.fillStyle = v > 0.05 ? C.h(Math.min(1, 0.35 + 0.65 * v)) : C.l(.42); g.fill();
        g.strokeStyle = C.l(.7); g.lineWidth = 1.2; g.stroke();
      });
      g.restore();
      // words: the key and tempo heard, and where the playhead is
      var info = [M.keyName ? M.keyName.toUpperCase() : null, M.has ? Math.round(M.bpm) + ' BPM' : null].filter(Boolean).join(' · ');
      if (info) cap(k, info, 0, 26, 30, C.muted, 'left');
      if (M.meter && bNow >= M.down) {
        var rel = bNow - M.down, barN = Math.floor(rel / M.meter) + 1, beatN = Math.floor(rel % M.meter) + 1;
        if (M.has && bNow > M.last + M.meter) barN = null;
        if (barN) cap(k, 'BAR ' + barN + ' · ' + beatN, PLAY + 8, 26, 30, C.ink, 'right');
      }
      g.restore();
    }
  });
})();

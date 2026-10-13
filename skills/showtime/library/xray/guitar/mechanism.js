/* A guitar, written as it is heard (showtime X-ray mechanism library: guitar).
   Design space: 1000 x 350 units (the 9:16 panel under a 4:3 clip, about 0.95 px per unit): chord names on top,
   a six-line tab (string 1, high e, on top) with the right-hand fingers (p i m a) under it, and a fretboard
   diagram below in the same orientation, nut on the left, frets 0-12 at their real spacing.
   The tab scrolls left past a fixed playhead on the smooth tempo map (k.beat of the frame's time, never a jump).
   Each event is a pluck: its notes (notes.json guitar[]: string, fret, finger) are written at the playhead, red on
   the event's frame; on the fretboard the fretted dots light while they sound and the plucked string vibrates
   from the fret to the bridge, ringing down over about a second.
   Measured: pluck times (xray.json), pitches, tempo map, chords (`showtime xray notes --instrument guitar`).
   Assigned by rule, not read from the picture: string and fret (standard tuning, open position first) and the
   finger (p for strings 6-4, i m a for 3 2 1). Set in showtime.json "xray": "min_confidence" (drop notes the
   model is less sure of), "chords" (false hides the names; a name shows when it holds for "chord_beats" beats,
   default 2), "px_per_beat". Without notes.json each pluck is a tick on the tab, never a guessed fret. */
(function () {
  var W = 1000, TY = 90, TS = 25, FY = 266, FS = 16.4, NUT = 46, PLAY = 862, RISE = 3, HX = 52;
  var NAMES = ['e', 'B', 'G', 'D', 'A', 'E'];
  var M = null;

  function fretX(n) { return NUT + (W - NUT) * (1 - Math.pow(2, -n / 12)) / 0.5; }
  function build(k) {
    var mus = k.music || {}, cfg = k.cfg || {}, q = {}, gt = {}, evOf = {}, minc = cfg.min_confidence || 0;
    (mus.quantized || []).forEach(function (d) { q[d.i] = d; });
    (mus.guitar || []).forEach(function (d) { gt[d.i] = d; });
    k.ev.forEach(function (e, ei) { if (e.kind !== 'skip') (e.notes || []).forEach(function (n) { evOf[n.i] = ei; }); });
    var notes = [];
    (mus.notes || []).forEach(function (n, j) {
      var i = n.i != null ? n.i : j, gd = gt[i];
      if (!gd || (n.confidence != null && n.confidence < minc)) return;
      var ev = evOf[i];
      notes.push({ i: i, t: n.t, end: n.end || n.t + 0.5, conf: n.confidence || 0, beat: q[i] ? q[i].beat : k.beat(n.t),
                   string: gd.string, fret: gd.fret, finger: gd.finger || '', ev: ev,
                   show: ev != null ? k.ev[ev].frame : Math.floor(n.t * k.fps + 1e-9) });
    });
    var cols = {};                                 // one column per beat; one note per string (the surer one)
    notes.forEach(function (n) {
      var c = cols[n.beat] = cols[n.beat] || { beat: n.beat, by: {} }, o = c.by[n.string];
      if (!o || n.conf > o.conf) c.by[n.string] = n;
    });
    var chords = [], need = cfg.chord_beats || 2;
    if (cfg.chords !== false) (mus.chords || []).forEach(function (c) {
      var last = chords[chords.length - 1];
      if (last && last.name === c.name && Math.abs(last.end - c.t) < 0.05) { last.end = c.end; last.n++; }
      else chords.push({ name: c.name, t: c.t, end: c.end, n: 1 });
    });
    var bpm = (mus.tempo && mus.tempo.bpm) || 120;
    M = { notes: notes, has: !!(mus.guitar && mus.guitar.length),
          cols: Object.keys(cols).map(function (b) { var c = cols[b]; c.notes = Object.keys(c.by).map(function (s) { return c.by[s]; }); return c; }),
          chords: chords.filter(function (c) { return c.n >= need; }).map(function (c) { c.beat = k.beat(c.t); return c; }),
          key: mus.key || null, bpm: bpm, pxb: cfg.px_per_beat || Math.max(56, Math.min(140, 190 / (bpm / 60))) };
  }
  function line(g, x0, y0, x1, y1, col, w) { g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.strokeStyle = col; g.lineWidth = w; g.stroke(); }
  function disc(g, x, y, r, fill) { g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fillStyle = fill; g.fill(); }
  function text(k, s, x, y, px, col, align, weight, family) {
    var g = k.g; g.save(); g.shadowBlur = 0; g.font = (weight || 600) + ' ' + (px / k.scale).toFixed(2) + 'px ' + (family || '"IBM Plex Mono"');
    g.fillStyle = col; g.textAlign = align || 'left'; g.textBaseline = 'alphabetic'; g.globalAlpha *= (k.labelAlpha == null ? 1 : k.labelAlpha);
    g.fillText(s, x, y); g.restore();
  }
  function strY(s) { return TY + (s - 1) * TS; }
  function boardY(s) { return FY + (s - 1) * FS; }

  XRAY.mechanism({
    name: 'guitar',
    noun: 'plucks', one: 'a pluck',
    box: [0, 0, 1000, 350],
    anchors: { nut_e: [NUT, boardY(1)], nut_E: [NUT, boardY(6)], fret12_e: [W, boardY(1)], fret12_E: [W, boardY(6)] },
    outline: [[NUT, boardY(1)], [W, boardY(1)], [W, boardY(6)], [NUT, boardY(6)]],
    headline: function (n) { return '<em>' + n + '</em> plucks,<br>the tab written<br>from the sound.'; },
    measured: function () {
      return 'Each pluck lit up on the frame its sound was heard; pitches, chords and tempo read from that sound.';
    },
    drawn: 'Drawn: tab and fretboard; strings, frets and fingers by rule, not read from the hands.',
    // the live page: pads that play the next event of each kind from the real clip
    touch: { verb: 'Play it', by: 'note' },
    draw: function (k) {
      if (k.view === 'inplace') return;
      if (!M) build(k);
      var g = k.g, C = k.C, f = k.f, now = f / k.fps, bNow = k.beat(now), pxb = M.pxb;
      var o = k.pr(0, 0);
      g.save(); g.translate(o[0], o[1]); g.scale(k.scale, k.scale); g.shadowBlur = 0;
      var X = function (b) { return PLAY + (b - bNow) * pxb; };
      // the beat grid, everywhere (ticks above and below the tab)
      g.save(); g.beginPath(); g.rect(HX, 0, W - HX, FY - 14); g.clip();
      for (var b = Math.ceil(bNow - (PLAY - HX) / pxb) - 1; b <= bNow + (W - PLAY) / pxb + 1; b++) {
        var bx = X(b) - 0.27 * pxb;
        line(g, bx, TY - 10, bx, TY - 3, C.l(.3), 1.2); line(g, bx, strY(6) + 3, bx, strY(6) + 10, C.l(.3), 1.2);
      }
      g.restore();
      // the six strings of the tab, their names, and the bracket
      for (var s = 1; s <= 6; s++) line(g, HX - 8, strY(s), W, strY(s), C.l(.5), 1.3);
      line(g, HX - 8, strY(1), HX - 8, strY(6), C.l(.7), 2);
      for (s = 1; s <= 6; s++) text(k, NAMES[s - 1], 14, strY(s) + 9, 26, C.muted, 'left', 600);
      // the playhead (every pluck flashes it), under the numbers
      var ph = k.hot ? k.s : 0;
      g.save(); if (ph > 0.05) { g.shadowColor = C.hot; g.shadowBlur = 16 * ph; }
      line(g, PLAY, TY - 14, PLAY, strY(6) + 14, C.h(.55 + .45 * ph), 2 + 2.5 * ph); g.restore();
      // the notes heard so far: fret numbers on their strings, the plucking finger under them
      g.save(); g.beginPath(); g.rect(HX, 0, W - HX, FY - 10); g.clip();
      var fpx = 28 / k.scale;
      if (M.has) {
        M.cols.forEach(function (c) {
          var x = X(c.beat); if (x < HX - 40 || x > W + 40) return;
          var fingers = [], hotC = 0;
          c.notes.forEach(function (n) {
            if (f < n.show - RISE) return;
            var sv = n.ev != null ? k.env(n.ev) : 0, a = f >= n.show ? 1 : Math.max(0.15, sv), y = strY(n.string), lab = String(n.fret);
            hotC = Math.max(hotC, sv);
            g.save(); g.globalAlpha *= a;
            g.font = '600 ' + fpx.toFixed(2) + 'px "IBM Plex Mono"';
            var w = g.measureText(lab).width + 8;
            g.fillStyle = C.bg(1); g.fillRect(x - w / 2, y - 11.5, w, 23);
            if (sv > 0.05) { g.shadowColor = C.hot; g.shadowBlur = 18 * sv; }
            g.fillStyle = sv > 0.05 ? C.hot : C.ink; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(lab, x, y + 1.5);
            g.restore();
            if (n.finger && fingers.indexOf(n.finger) < 0) fingers.push(n.finger);
            fingers.sort(function (a, b) { return 'pima'.indexOf(a) - 'pima'.indexOf(b); });
          });
          if (fingers.length) {
            g.save(); g.font = 'italic 600 ' + fpx.toFixed(2) + 'px "IBM Plex Mono"'; g.textAlign = 'center'; g.textBaseline = 'alphabetic';
            if (hotC > 0.05) { g.shadowColor = C.hot; g.shadowBlur = 12 * hotC; }
            g.fillStyle = hotC > 0.05 ? C.hot : C.muted; g.fillText(fingers.join(''), x, strY(6) + 36); g.restore();
          }
        });
      } else {
        k.ev.forEach(function (e, ei) {
          if (e.kind === 'skip' || f < e.frame - RISE) return;
          var x = X(k.beat(e.t)), sv = k.env(ei);
          line(g, x, strY(2), x, strY(5), sv > 0.05 ? C.hot : C.ink, 3);
        });
      }
      // chord names, written once they have held long enough to be heard as chords
      M.chords.forEach(function (c) {
        if (now < c.t) return;
        var x = X(c.beat); if (x < HX - 60 || x > W + 60) return;
        var fresh = Math.max(0, 1 - (now - c.t) * 2);
        g.save(); if (fresh > 0.05) { g.shadowColor = C.hot; g.shadowBlur = 14 * fresh; }
        g.font = '800 ' + (34 / k.scale).toFixed(2) + 'px "Bricolage Grotesque"'; g.textAlign = 'left'; g.textBaseline = 'alphabetic';
        g.fillStyle = fresh > 0.05 ? C.hot : C.ink; g.fillText(c.name, x - 8, TY - 20); g.restore();
      });
      g.restore();
      // fade the scroll out at the left edge, then re-draw the string lines there
      var gr = g.createLinearGradient(HX, 0, HX + 60, 0); gr.addColorStop(0, C.bg(1)); gr.addColorStop(1, C.bg(0));
      g.fillStyle = gr; g.fillRect(HX - 2, 0, 62, FY - 12);
      for (s = 1; s <= 6; s++) line(g, HX - 2, strY(s), HX + 60, strY(s), C.l(.5), 1.3);
      // the fretboard: nut, frets at their real spacing, inlays, strings; the sounding notes fretted and ringing
      var y1 = boardY(1), y6 = boardY(6);
      g.fillStyle = C.l(.06); g.fillRect(NUT, y1 - 7, W - NUT, y6 - y1 + 14);
      for (var fr = 1; fr <= 12; fr++) line(g, fretX(fr), y1 - 7, fretX(fr), y6 + 7, C.l(.45), 2);
      line(g, NUT, y1 - 8, NUT, y6 + 8, C.i(.85), 5);
      [3, 5, 7, 9].forEach(function (n) { disc(g, (fretX(n - 1) + fretX(n)) / 2, (y1 + y6) / 2, 4, C.l(.3)); });
      disc(g, (fretX(11) + fretX(12)) / 2, (y1 + y6) / 2 - FS * 1.5, 4, C.l(.3)); disc(g, (fretX(11) + fretX(12)) / 2, (y1 + y6) / 2 + FS * 1.5, 4, C.l(.3));
      var ring = {};                               // per string: the last pluck heard on it
      M.notes.forEach(function (n) {
        if (f < n.show - RISE) return;
        var r = ring[n.string];
        if (!r || n.show > r.show || (n.show === r.show && n.conf > r.conf)) ring[n.string] = n;
      });
      for (s = 1; s <= 6; s++) {
        var n = ring[s], y = boardY(s), w0 = 1 + (s - 1) * 0.35;
        var sounding = n && f >= n.show - RISE && now <= n.end + 0.1, age = n ? f - n.show : 999;
        var sv = n && n.ev != null ? k.env(n.ev) : 0, hot = sv > 0.05;
        var x0 = n && sounding && n.fret > 0 && n.fret <= 12 ? (fretX(n.fret - 1) + fretX(n.fret)) / 2 : NUT;
        var amp = sounding ? (age < 0 ? 6 * sv : 6 * Math.exp(-age / 14)) : 0;
        if (n && sounding && n.fret > 12) amp = 0;
        line(g, NUT, y, sounding ? x0 : W, y, C.l(.55), w0);
        if (sounding) {
          g.save(); if (hot) { g.shadowColor = C.hot; g.shadowBlur = 14 * sv; }
          g.beginPath();
          for (var u = 0; u <= 60; u++) {
            var xx = x0 + (W - x0) * u / 60, yy = y + amp * Math.sin(Math.max(0, age) * 2.3 + 0.6) * Math.sin(Math.PI * u / 60);
            if (u) g.lineTo(xx, yy); else g.moveTo(xx, yy);
          }
          g.strokeStyle = hot ? C.hot : C.i(.9); g.lineWidth = w0 + 0.8; g.stroke(); g.restore();
          if (n.fret > 0 && n.fret <= 12) {
            g.save(); if (hot) { g.shadowColor = C.hot; g.shadowBlur = 16 * sv; }
            disc(g, x0, y, 7.5, hot ? C.hot : C.i(.92)); g.restore();
          } else if (n.fret === 0) {
            g.beginPath(); g.arc(NUT - 16, y, 5.5, 0, Math.PI * 2); g.strokeStyle = hot ? C.hot : C.i(.92); g.lineWidth = 2; g.stroke();
          }
        }
      }
      // words: the key and tempo heard
      var info = [M.key ? String(M.key).toUpperCase() : null, M.has ? Math.round(M.bpm) + ' BPM' : null].filter(Boolean).join(' · ');
      if (info) text(k, info, 0, 22, 28, C.muted, 'left');
      text(k, 'p i m a: right hand', PLAY + 8, 22, 28, C.muted, 'right');
      g.restore();
    }
  });
})();

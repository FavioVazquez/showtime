/* A drum kit, written as it is heard (showtime X-ray mechanism library: drums).
   Design space: 1000 x 440 units (the 9:16 panel, about 0.95 px per unit): a percussion staff on top, a drum kit
   seen from above below it (the drummer's seat at the bottom): kick, snare, hi-hat, two mounted toms, floor tom,
   crash and ride.
   The staff scrolls left past a fixed playhead on the smooth tempo map (k.beat of the frame's time, never a jump).
   Each event is a hit: its pieces (notes.json drums[], joined to the event by the runtime) are written at the
   playhead in the usual drum key (kick in the bottom space, floor tom, snare in the third space, toms above it,
   hi-hat x above the staff with an o when open, crash x on a ledger line), red on the event's frame; on the kit
   each piece hit flashes and its skin ripples out from the centre (a cymbal sways and rings).
   Measured: hit times (xray.json), the piece of each hit sorted by its sound and its loudness (`showtime xray notes
   --instrument drums`: a classifier of sound types, not a transcription; it does not see the kit). Toms are split
   high, mid and floor by their pitch relative to the other toms in the clip. Set in showtime.json "xray":
   "px_per_beat". Without notes.json each hit is a slash on the staff and flashes the whole kit outline. */
(function () {
  var W = 1000, SP = 16, TT = 110, TB = TT + 4 * SP, PLAY = 862, RISE = 3, HX = 70;
  // the drum key: staff step (E4 bottom line = 30), notehead, stem
  var KEY = { kick: [31, 'n', 'd'], tom_floor: [33, 'n', 'u'], snare: [35, 'n', 'u'], tom_mid: [36, 'n', 'u'],
              tom_high: [37, 'n', 'u'], ride: [38, 'x', 'u'], hihat_closed: [39, 'x', 'u'], hihat_open: [39, 'x', 'u'],
              crash: [40, 'x', 'u'] };
  // the kit from above: centre, radius, kind
  var KIT = { crash: [292, 276, 52, 'cym'], ride: [738, 278, 60, 'cym'], hihat: [182, 366, 42, 'cym'],
              tom_high: [440, 278, 33, 'drum'], tom_mid: [568, 278, 36, 'drum'], snare: [326, 392, 40, 'drum'],
              tom_floor: [690, 390, 48, 'drum'], kick: [500, 356, 0, 'kick'] };
  var NAME = { crash: 'crash', ride: 'ride', hihat: 'hi-hat', tom_high: 'tom', tom_mid: 'tom', snare: 'snare', tom_floor: 'floor tom', kick: 'kick' };
  var M = null;

  function yOf(step) { return TB - (step - 30) * SP / 2; }
  function kitOf(p) { return p === 'hihat_closed' || p === 'hihat_open' ? 'hihat' : p; }
  function build(k) {
    var mus = k.music || {}, cfg = k.cfg || {}, q = {}, evOf = {}, raw = mus.drums || [];
    (mus.quantized || []).forEach(function (d) { q[d.i] = d; });
    k.ev.forEach(function (e, ei) { if (e.kind !== 'skip') (e.notes || []).forEach(function (n) { evOf[n.i] = ei; }); });
    var hz = raw.filter(function (d) { return d.piece === 'tom' && d.hz; }).map(function (d) { return d.hz; })
      .filter(function (v, i, a) { return a.indexOf(v) === i; }).sort(function (a, b) { return a - b; });
    var hits = raw.map(function (d, j) {
      var i = d.i != null ? d.i : j, p = d.piece, ev = evOf[i];
      if (p === 'tom') {                            // high, mid, floor: by pitch against the clip's other toms
        var r = hz.length > 1 && d.hz ? hz.indexOf(d.hz) / (hz.length - 1) : 0.5;
        p = r < 0.34 ? 'tom_floor' : r > 0.66 ? 'tom_high' : 'tom_mid';
      }
      if (!KEY[p]) p = 'snare';
      return { i: i, t: d.t, piece: p, vel: d.velocity == null ? 0.8 : d.velocity, beat: q[i] ? q[i].beat : k.beat(d.t), ev: ev,
               show: ev != null ? k.ev[ev].frame : Math.floor(d.t * k.fps + 1e-9) };
    });
    var cols = {};
    hits.forEach(function (h) { (cols[h.beat] = cols[h.beat] || { beat: h.beat, hits: [] }).hits.push(h); });
    var bpm = (mus.tempo && mus.tempo.bpm) || 120;
    M = { hits: hits, has: raw.length > 0, cols: Object.keys(cols).map(function (b) { return cols[b]; }), bpm: bpm,
          pxb: cfg.px_per_beat || Math.max(96, Math.min(160, 280 / (bpm / 60))) };
  }
  function line(g, x0, y0, x1, y1, col, w) { g.beginPath(); g.moveTo(x0, y0); g.lineTo(x1, y1); g.strokeStyle = col; g.lineWidth = w; g.stroke(); }
  function disc(g, x, y, r, fill) { g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fillStyle = fill; g.fill(); }
  function ring(g, x, y, rx, ry, col, w) { g.beginPath(); g.ellipse(x, y, Math.max(0.1, rx), Math.max(0.1, ry), 0, 0, Math.PI * 2); g.strokeStyle = col; g.lineWidth = w; g.stroke(); }
  function text(k, s, x, y, px, col, align) {
    var g = k.g; g.save(); g.shadowBlur = 0; g.font = '600 ' + (px / k.scale).toFixed(2) + 'px "IBM Plex Mono"';
    g.fillStyle = col; g.textAlign = align || 'left'; g.textBaseline = 'alphabetic'; g.globalAlpha *= (k.labelAlpha == null ? 1 : k.labelAlpha);
    g.fillText(s, x, y); g.restore();
  }
  function head(g, x, y, kind, col) {
    if (kind === 'x') { line(g, x - 6.5, y - 6.5, x + 6.5, y + 6.5, col, 2.4); line(g, x - 6.5, y + 6.5, x + 6.5, y - 6.5, col, 2.4); return; }
    g.save(); g.translate(x, y); g.rotate(-0.35); g.beginPath(); g.ellipse(0, 0, 9.2, 6.4, 0, 0, Math.PI * 2); g.fillStyle = col; g.fill(); g.restore();
  }

  XRAY.mechanism({
    name: 'drums',
    noun: 'hits', one: 'a hit',
    box: [0, 0, 1000, 440],
    anchors: { snare: [326, 388], kick: [500, 352], crash: [292, 268], ride: [738, 270] },
    outline: [[120, 200], [820, 200], [820, 440], [120, 440]],
    headline: function (n) { return '<em>' + n + '</em> hits,<br>written from<br>the sound.'; },
    measured: function () {
      return 'Each hit lit up on the frame its sound was heard; its piece sorted by that sound, not seen.';
    },
    drawn: 'Drawn: a generic kit and the drum part; toms by relative pitch.',
    // the live page: pads that play the next event of each kind from the real clip
    touch: { verb: 'Hit it', by: 'note' },
    draw: function (k) {
      if (k.view === 'inplace') return;
      if (!M) build(k);
      var g = k.g, C = k.C, f = k.f, now = f / k.fps, bNow = k.beat(now), pxb = M.pxb;
      var o = k.pr(0, 0);
      g.save(); g.translate(o[0], o[1]); g.scale(k.scale, k.scale); g.shadowBlur = 0;
      var X = function (b) { return PLAY + (b - bNow) * pxb; };
      // the beat grid, everywhere
      g.save(); g.beginPath(); g.rect(HX, 0, W - HX, 218); g.clip();
      for (var b = Math.ceil(bNow - (PLAY - HX) / pxb) - 1; b <= bNow + (W - PLAY) / pxb + 1; b++) {
        var bx = X(b) - 0.14 * pxb;
        line(g, bx, TT - 8, bx, TT - 1, C.l(.3), 1.2); line(g, bx, TB + 1, bx, TB + 8, C.l(.3), 1.2);
      }
      g.restore();
      for (var i = 0; i < 5; i++) line(g, 14, TT + i * SP, W, TT + i * SP, C.l(.5), 1.3);
      // the playhead, under the notes; every hit flashes it
      var ph = k.hot ? k.s : 0;
      g.save(); if (ph > 0.05) { g.shadowColor = C.hot; g.shadowBlur = 16 * ph; }
      line(g, PLAY, TT - 3 * SP, PLAY, TB + 3.5 * SP, C.h(.55 + .45 * ph), 2 + 2.5 * ph); g.restore();
      // the hits heard so far
      g.save(); g.beginPath(); g.rect(HX, 0, W - HX, 218); g.clip();
      g.shadowColor = C.l(.8); g.shadowBlur = C.glow;
      var shown = [];
      if (M.has) M.cols.forEach(function (c) {
        var x = X(c.beat); if (x < HX - 40 || x > W + 40) return;
        var vis = c.hits.filter(function (h) { return f >= h.show - RISE; });
        if (vis.length) shown.push({ c: c, x: x, vis: vis });
      });
      // one stem per column for the hands (up) and one for the feet (down); a beat's columns share beams
      var groups = {};
      shown.forEach(function (s) {
        ['u', 'd'].forEach(function (dir) {
          var hs = s.vis.filter(function (h) { return KEY[h.piece][2] === dir; });
          if (!hs.length) return;
          var ys = hs.map(function (h) { return yOf(KEY[h.piece][0]); }), hot = 0;
          hs.forEach(function (h) { hot = Math.max(hot, h.ev != null ? k.env(h.ev) : 0); });
          var col = { x: s.x, dir: dir, top: Math.min.apply(null, ys), bot: Math.max.apply(null, ys), hot: hot, beat: s.c.beat };
          col.sx = dir === 'u' ? s.x + 8.4 : s.x - 8.4;
          col.tip = dir === 'u' ? Math.min(col.top - 3.2 * SP, TT - 2.6 * SP) : col.bot + 2.6 * SP;
          var gk = dir + '|' + Math.floor(s.c.beat + 1e-6);
          (groups[gk] = groups[gk] || []).push(col);
        });
        s.vis.forEach(function (h) {
          var sv = h.ev != null ? k.env(h.ev) : 0, a = f >= h.show ? 1 : Math.max(0.15, sv), y = yOf(KEY[h.piece][0]);
          var cc = sv > 0.05 ? C.hot : C.ink;
          g.save(); g.globalAlpha *= a; if (sv > 0.05) { g.shadowColor = C.hot; g.shadowBlur = 18 * sv; }
          if (KEY[h.piece][0] >= 40) line(g, s.x - 14, yOf(40), s.x + 14, yOf(40), C.i(.8), 1.6);
          head(g, s.x, y, KEY[h.piece][1], cc);
          if (h.piece === 'hihat_open') ring(g, s.x + 8.4, TT - 4.3 * SP, 5, 5, cc, 2);
          g.restore();
        });
      });
      Object.keys(groups).forEach(function (gk) {
        var cols = groups[gk].sort(function (a, b) { return a.x - b.x; }), up = cols[0].dir === 'u';
        var hot = Math.max.apply(null, cols.map(function (c) { return c.hot; }));
        if (cols.length > 1) {                        // a beam level across the beat: 8ths, and 16ths where they are
          var tip = up ? Math.min.apply(null, cols.map(function (c) { return c.tip; })) : Math.max.apply(null, cols.map(function (c) { return c.tip; }));
          cols.forEach(function (c) { c.tip = tip; });
        }
        g.save(); if (hot > 0.05) { g.shadowColor = C.hot; g.shadowBlur = 14 * hot; }
        var colr = hot > 0.05 ? C.hot : C.ink;
        cols.forEach(function (c) { line(g, c.sx, up ? c.bot : c.top, c.sx, c.tip, c.hot > 0.05 ? C.hot : C.ink, 1.7); });
        if (cols.length > 1) {
          var th = up ? 0.5 * SP : -0.5 * SP, x0 = cols[0].sx - 0.8, x1 = cols[cols.length - 1].sx + 0.8, t0 = cols[0].tip;
          g.fillStyle = colr; g.fillRect(x0, up ? t0 : t0 + th, x1 - x0, Math.abs(th));
          for (var j = 0; j < cols.length - 1; j++) {
            var gap = cols[j + 1].beat - cols[j].beat;
            if (gap <= 0.26) g.fillRect(cols[j].sx - 0.8, up ? t0 + 1.6 * Math.abs(th) : t0 - 2.6 * Math.abs(th), cols[j + 1].sx - cols[j].sx + 1.6, Math.abs(th));
          }
        }
        g.restore();
      });
      if (!M.has) k.ev.forEach(function (e, ei) {
        if (e.kind === 'skip' || f < e.frame - RISE) return;
        var x = X(k.beat(e.t)), sv = k.env(ei), y = TT + 2 * SP;
        line(g, x - 8, y + 8, x + 8, y - 8, sv > 0.05 ? C.hot : C.ink, 5);
      });
      g.restore();
      // fade under the clef; the percussion clef (two bars)
      var gr = g.createLinearGradient(HX, 0, HX + 60, 0); gr.addColorStop(0, C.bg(1)); gr.addColorStop(1, C.bg(0));
      g.fillStyle = gr; g.fillRect(HX - 2, 0, 62, 218);
      for (i = 0; i < 5; i++) line(g, HX - 2, TT + i * SP, HX + 60, TT + i * SP, C.l(.5), 1.3);
      line(g, 14, TT, 14, TB, C.l(.7), 2);
      g.fillStyle = C.i(.92); g.fillRect(30, TT + SP, 6, 2 * SP); g.fillRect(42, TT + SP, 6, 2 * SP);
      // the kit from above: each piece flashes on its hit, its skin ripples, a cymbal sways
      var last = {};
      M.hits.forEach(function (h) {
        if (f < h.show - RISE) return;
        var kp = kitOf(h.piece), l = last[kp];
        if (!l || h.show >= l.show) last[kp] = h;
      });
      g.shadowColor = C.l(.8); g.shadowBlur = C.glow;
      // stands and the drummer's seat, faint
      ring(g, 500, 436, 34, 6, C.l(.25), 1.5);
      Object.keys(KIT).forEach(function (kp) {
        var P = KIT[kp], h = last[kp], age = h ? f - h.show : 999, sv = h && h.ev != null ? k.env(h.ev) : (h && age >= 0 && age < 6 ? 1 - age / 6 : 0);
        var hot = sv > 0.05, vel = h ? h.vel : 0, col = hot ? C.hot : C.line;
        if (!M.has && k.hot) { hot = true; sv = k.s; col = C.hot; }
        g.save(); if (hot) { g.shadowColor = C.hot; g.shadowBlur = 20 * sv; }
        if (P[3] === 'kick') {                          // the bass drum on its side: shell, batter head, pedal and beater
          var swing = hot ? sv : 0;
          g.beginPath(); g.rect(P[0] - 74, P[1] - 34, 148, 58); g.strokeStyle = col; g.lineWidth = 2.6; g.stroke();
          if (hot) { g.fillStyle = C.h(0.25 * sv); g.fill(); }
          line(g, P[0] - 74, P[1] + 24, P[0] + 74, P[1] + 24, col, 4.5);
          line(g, P[0], P[1] + 62, P[0], P[1] + 30 + 8 * (1 - swing), col, 2.4);
          disc(g, P[0], P[1] + 30 + 8 * (1 - swing), 6, col);
          if (h && age >= 0 && age < 18) { var u = age / 18; line(g, P[0] - 74 * u, P[1] + 24 - 30 * u, P[0] + 74 * u, P[1] + 24 - 30 * u, C.h(0.7 * (1 - u)), 2); }
        } else if (P[3] === 'cym') {                    // a cymbal: sways after a hit, rings out
          var sway = h && age >= 0 && age < 40 ? Math.sin(age * 0.55) * Math.exp(-age / 14) * (0.12 + 0.12 * vel) : 0;
          ring(g, P[0], P[1], P[2], P[2] * (0.92 + sway), col, 2.4);
          ring(g, P[0], P[1], P[2] * 0.22, P[2] * 0.22 * (0.92 + sway), col, 2);
          if (kp === 'hihat') ring(g, P[0] + 3, P[1] - 3, P[2] * 0.93, P[2] * 0.85 * (0.92 + sway), C.l(.45), 1.4);
          if (hot) { g.beginPath(); g.ellipse(P[0], P[1], P[2], P[2] * (0.92 + sway), 0, 0, Math.PI * 2); g.fillStyle = C.h(0.22 * sv); g.fill(); }
          for (var r = 0; r < 3; r++) ring(g, P[0], P[1], P[2] * (0.4 + r * 0.18), P[2] * (0.4 + r * 0.18) * (0.92 + sway), C.l(.15), 1);
        } else {                                        // a drum: shell, head, lugs; the skin ripples from the centre
          ring(g, P[0], P[1], P[2], P[2], col, 2.6); ring(g, P[0], P[1], P[2] - 5, P[2] - 5, C.l(.3), 1.2);
          for (var lg = 0; lg < 8; lg++) { var an = lg * Math.PI / 4; disc(g, P[0] + Math.cos(an) * (P[2] + 3), P[1] + Math.sin(an) * (P[2] + 3), 2.4, col); }
          if (hot) { g.beginPath(); g.arc(P[0], P[1], P[2] - 5, 0, Math.PI * 2); g.fillStyle = C.h(0.25 * sv); g.fill(); }
          if (kp === 'snare') for (var sw = -2; sw <= 2; sw++) line(g, P[0] + sw * 7, P[1] - P[2] * 0.7, P[0] + sw * 7, P[1] + P[2] * 0.7, C.l(.18), 1);
        }
        // ripples: rings running out over half a second, bigger for a louder hit
        if (h && age >= 0 && age < 16 && P[3] !== 'kick') {
          for (var rr = 0; rr < 2; rr++) {
            var aa = age - rr * 5; if (aa < 0) continue;
            var uu = aa / 16, rad = (P[2] - 4) * (0.15 + 0.85 * uu) * (0.7 + 0.3 * vel);
            ring(g, P[0], P[1], rad, rad * (P[3] === 'cym' ? 0.92 : 1), C.h(0.8 * (1 - uu)), 2.2 - uu);
          }
        }
        g.restore();
      });
      text(k, M.has ? 'PIECES SORTED BY THEIR SOUND' : 'HITS, NO PIECES (NO NOTES.JSON)', 0, 26, 28, C.muted, 'left');
      g.restore();
      // labels: each piece, red while it rings
      var LBL = { crash: [-60, -36], ride: [70, -36], hihat: [-60, 0], tom_high: [-30, -80], tom_mid: [30, -80], snare: [-50, 36],
                  tom_floor: [70, 30], kick: [-20, 76] };
      Object.keys(KIT).forEach(function (kp) {
        var h = last[kp], age = h ? f - h.show : 999;
        k.label(NAME[kp], [KIT[kp][0], KIT[kp][1]], LBL[kp][0], LBL[kp][1], age >= -RISE && age < 10);
      });

    }
  });
})();

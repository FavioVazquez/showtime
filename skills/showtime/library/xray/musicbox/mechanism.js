/* A disc music box, inside (showtime X-ray mechanism library: musicbox).
   Design space: the disc centred on (0, 0), radius 342, seen from above; the play line runs from the spindle to the
   right, where the star wheels sit; the comb is on the right, one tooth per pitch, bass at the top.
   Each event is a pluck: a slot of the disc reaches the play line, its star wheel turns one tooth and the comb
   tooth rings, PEAKING on the event's frame. The slot then turns away with the disc, so the disc fills with the
   slots the clip played: the disc rebuilt from the sound.
   Which tooth: from notes.json (`showtime xray notes`: the pitches heard); without it a pluck lights one of three
   registers by the sound's band (low, mid, high), never a guessed pitch. The disc's speed: "xray": {"spin": deg/s}
   (measure it from the clip; positive = clockwise as filmed, negative = anticlockwise; default 6). In place, only the
   disc is drawn (on the real disc); the comb and the links are drawn in the panel. */
(function () {
  var deg = function (a) { return a * Math.PI / 180; };
  var RIM = 342, R0 = 120, R1 = 318, COMB_X = 790, COMB_Y0 = -300, COMB_Y1 = 300;
  var BANDS = ['low', 'mid', 'high'];
  var tracks = null;                            // pitch (or band) -> track index, built on the first frame

  function build(k) {
    var keys = [];
    if (k.notes.length) {
      k.notes.forEach(function (n) { if (keys.indexOf(n.pitch) < 0) keys.push(n.pitch); });
      keys.sort(function (a, b) { return a - b; });
    } else keys = BANDS.slice();
    var names = {};
    k.notes.forEach(function (n) { names[n.pitch] = n.name; });
    tracks = { keys: keys, names: names, byNotes: !!k.notes.length };
  }
  function trackR(i) { var n = tracks.keys.length; return n < 2 ? (R0 + R1) / 2 : R0 + (R1 - R0) * i / (n - 1); }
  function toothY(i) { var n = tracks.keys.length; return n < 2 ? 0 : COMB_Y0 + (COMB_Y1 - COMB_Y0) * i / (n - 1); }
  function toothLen(i) { var n = tracks.keys.length; return 190 - 110 * (n < 2 ? 0.5 : i / (n - 1)); }
  function plucks(k, e) {                       // the track indexes event e plays
    if (e.kind !== 'event') return [];
    if (tracks.byNotes) return (e.notes || []).map(function (n) { return tracks.keys.indexOf(n.pitch); }).filter(function (i) { return i >= 0; });
    return [Math.max(0, BANDS.indexOf(e.band || 'mid'))];
  }

  XRAY.mechanism({
    name: 'musicbox',
    noun: 'plucks', noun1: 'pluck', one: 'a pluck',
    box: [-370, -370, 820, 370],
    // four points on the rim (no three in a line): the disc's top, right, bottom and left edges as filmed, rim_e being
    // where the play line meets the rim
    anchors: { rim_n: [0, -RIM], rim_e: [RIM, 0], rim_s: [0, RIM], rim_w: [-RIM, 0] },
    outline: [[-RIM, -RIM], [RIM, -RIM], [RIM, RIM], [-RIM, RIM]],
    headline: function (n) { return '<em>' + n + '</em> plucks,<br>the disc rebuilt<br>from its sound.'; },
    measured: function (n, text, hasNotes) {
      return hasNotes
        ? 'Each slot is a note heard in the clip: its track from its pitch, its place on the disc from its time.'
        : 'Each pluck lit up on the frame its sound was heard; its register from the sound’s band.';
    },
    drawn: 'Inside view: a generic disc music box, drawn; the slots are rebuilt from the sound, not read off this disc.',
    // the live page: pads that play the next event of each kind from the real clip
    touch: { verb: 'Play it', by: 'note' },
    draw: function (k) {
      if (!tracks) build(k);
      var C = k.C, g = k.g, spin = (k.cfg.spin || 6) / k.fps;              // degrees per frame, + = clockwise
      var panel = k.view === 'panel', nT = tracks.keys.length;
      // the disc: rim, drive holes turning with it, faint tracks, the hub
      k.ell(0, 0, RIM, RIM, C.line, 4, 0, false);
      for (var h = 0; h < 72; h++) { var a = deg(h * 5 + spin * k.f); k.dot([Math.cos(a) * (RIM - 14), Math.sin(a) * (RIM - 14)], Math.max(1.5, 3 * k.scale), C.l(.4)); }
      for (var i = 0; i < nT; i++) k.ell(0, 0, trackR(i), trackR(i), i % 2 ? C.l(.07) : C.l(.13), 1.2, 0, false);
      k.ell(0, 0, R0 - 44, R0 - 44, C.line, 3, 0, false);
      k.dot([0, 0], Math.max(3, 8 * k.scale), C.line);
      // the play line, to the right
      g.setLineDash([6, 8]); k.seg([R0 - 40, 0], [RIM + 24, 0], C.i(.55), 2); g.setLineDash([]);
      // slots: a pluck at frame fe reached the play line on fe and has turned with the disc since
      var hotTracks = {};
      k.ev.forEach(function (e) {
        if (e.frame > k.f + 3) return;
        var age = k.f - e.frame, s = k.env(e.i);
        plucks(k, e).forEach(function (ti) {
          if (s > 0.05) hotTracks[ti] = Math.max(hotTracks[ti] || 0, s);
          var a = deg(spin * Math.max(0, age)), r = trackR(ti), p = [Math.cos(a) * r, Math.sin(a) * r];
          var big = panel ? 1 : 1.5, q = k.pr(p[0], p[1]), w = Math.max(3, 8 * big * k.scale), hgt = Math.max(6, 18 * big * k.scale);
          g.save(); g.translate(q[0], q[1]); g.rotate(a + Math.PI / 2);
          if (s > 0.05) { g.shadowColor = C.hot; g.shadowBlur = 18 * s; }
          g.fillStyle = s > 0.05 ? C.hot : (age < 0 ? C.i(0) : C.i(.8));
          g.fillRect(-w / 2, -hgt / 2, w, hgt);
          if (!panel && age >= 0) { g.shadowBlur = 0; g.strokeStyle = C.bg(.9); g.lineWidth = 1.5; g.strokeRect(-w / 2, -hgt / 2, w, hgt); }
          g.restore();
        });
      });
      // star wheels on the play line, one per track; each turns a tooth when its slot passes
      for (var t = 0; t < nT; t++) {
        var on = hotTracks[t] || 0, turned = 0;
        k.ev.forEach(function (e) { if (e.frame <= k.f && plucks(k, e).indexOf(t) >= 0) turned++; });
        k.ell(trackR(t), 0, 13, 13, on ? C.hot : C.soft, 2, deg(turned * 30 + on * 30), true);
        if (!panel) continue;
        // the comb tooth it plucks, and the link between them
        var y = toothY(t), len = toothLen(t), ring = 0, last = -1;
        k.ev.forEach(function (e) { if (e.frame <= k.f && plucks(k, e).indexOf(t) >= 0) last = e.frame; });
        if (last >= 0) { var d = k.f - last; ring = d < 18 ? 1 - d / 18 : 0; }
        if (on > ring) ring = on;
        var wob = Math.sin((k.f - last) * 2.1) * 9 * ring;
        k.seg([trackR(t) + 13, 0], [COMB_X - len, y], ring > 0.05 ? C.h(.6) : C.l(.1), 1.2);
        g.strokeStyle = ring > 0.05 ? C.hot : C.line; g.lineWidth = k.lw(panel ? 5 : 4);
        if (ring > 0.05) { g.shadowColor = C.hot; g.shadowBlur = 14 * ring; }
        k.path([[COMB_X, y], [COMB_X - len * 0.5, y + wob * 0.4], [COMB_X - len, y + wob]]); g.stroke(); g.shadowBlur = 0;
      }
      if (panel) k.seg([COMB_X, COMB_Y0 - 30], [COMB_X, COMB_Y1 + 30], C.line, 8);
      // labels
      k.label('disc', [-RIM * 0.7, -RIM * 0.7], -60, -40, false);
      k.label('play line', [RIM + 10, 0], 40, -150, Object.keys(hotTracks).length > 0);
      k.label('star wheels', [trackR(0), 0], -40, 150, Object.keys(hotTracks).length > 0);
      if (panel) k.label(tracks.byNotes ? 'comb · one tooth per pitch' : 'comb · low, mid, high', [COMB_X, COMB_Y1], -80, 70, false);
    }
  });
})();

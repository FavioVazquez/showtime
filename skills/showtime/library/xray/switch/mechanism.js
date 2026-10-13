/* A snap-action switch, inside (showtime X-ray mechanism library: switch): the kind under an old keyboard key, a
   microswitch, a light switch. Design space: the switch seen from the side, about 1000 x 600 units: the base along
   the bottom, the post with the lever's pivot in the middle, the over-centre spring from the lever's tail to the
   contact blade, the fixed contact on the right.
   Each event is a CLICK: the spring's line of action crosses the pivot (dead centre) and the blade snaps, closing
   the contacts on a press and opening them on a release, PEAKING on the event's frame. Presses and releases
   alternate from a press; "xray": {"kinds": {"3": "release"}} overrides one. When the switch itself is visible in
   the clip (as in a cut-away), the in-place view does not redraw its moving parts over the real ones: it marks the
   pivot, the spring's line of action and the contact, which flashes on each snap; the panel draws the schematic and
   a circuit whose lamp lights while the contacts are closed. */
(function () {
  var PIV = [840, 460], TAIL_UP = [450, 375], TAIL_DN = [480, 570], TIP_UP = [1190, 345], TIP_DN = [1040, 240];
  var BLADE0 = [880, 560], CONTACT = [1150, 575], FIXED = [[1050, 532], [1280, 532], [1280, 562], [1050, 562]];
  var BASE = [[330, 700], [1460, 700], [1460, 760], [330, 760]], POST = [[820, 360], [860, 360], [860, 710], [820, 710]];
  function lerp(a, b, s) { return [a[0] + (b[0] - a[0]) * s, a[1] + (b[1] - a[1]) * s]; }
  function presses(k) {                        // pressed (1) or not (0) after each event, and the snap around it
    var st = 0, out = [];
    k.ev.forEach(function (e) {
      if (e.kind === 'skip') { out.push(null); return; }
      var kind = e.kind === 'event' ? (st ? 'release' : 'press') : e.kind;
      st = kind === 'press' ? 1 : 0; out.push(st);
    });
    return out;
  }
  function state(k) {                          // 0 released .. 1 pressed at this frame: steps over the 3 frames before each click
    var p = presses(k), s = 0;
    k.ev.forEach(function (e, i) {
      if (p[i] == null) return;
      var d = k.since(i);
      if (d >= 0) s = p[i];
      else if (d > -3) { var prev = s, a = (d + 3) / 3; s = prev + (p[i] - prev) * a * a; }
    });
    return s;
  }

  XRAY.mechanism({
    name: 'switch',
    noun: 'clicks', noun1: 'click', one: 'a click',
    box: [300, 160, 1700, 780],
    anchors: { pivot: PIV, contact: CONTACT, base_left: [330, 700], base_right: [1460, 700] },
    outline: BASE.concat([[1460, 200], [330, 200]]),
    headline: function (n) { return '<em>' + n + '</em> clicks,<br>each one a spring<br>passing dead centre.'; },
    measured: function () { return 'Each click lit up on the frame its sound was heard; presses and releases alternate.'; },
    drawn: 'Inside view: a generic snap-action switch, drawn; the parts are marked on the real switch, not measured.',
    // the live page: pads that play the next event of each kind from the real clip
    touch: { verb: 'Click it', by: 'one' },
    draw: function (k) {
      var C = k.C, g = k.g, s = state(k), panel = k.view === 'panel';
      var tail = lerp(TAIL_DN, TAIL_UP, s), tip = lerp(TIP_DN, TIP_UP, s);
      var blade = [CONTACT[0], CONTACT[1] + (1 - s) * 34];        // the blade's contact end: up against the fixed contact when pressed
      var closed = s > 0.5, snap = k.hot ? k.s : 0;
      if (panel) {
        k.poly(BASE, C.soft, 2, C.l(.06)); k.poly(POST, C.line, 2.5);
        k.poly(FIXED, closed ? C.hot : C.line, 3);
        k.seg(tail, PIV, C.line, 6); k.seg(PIV, tip, C.line, 6);                 // the lever
        k.seg(BLADE0, blade, closed ? C.hot : C.line, 5);                        // the contact blade
        k.dot(blade, Math.max(4, 9 * k.scale), closed ? C.hot : C.line);
        // the circuit: terminals -> lamp -> back; lit while closed
        var L = [1560, 300];
        k.seg([1280, 520], [1560, 520], C.soft, 2); k.seg([1560, 520], [1560, 330], C.soft, 2);
        k.seg([1460, 730], [1600, 730], C.soft, 2); k.seg([1600, 730], [1600, 300], C.soft, 2);
        k.ell(L[0] + 20, L[1], 34, 34, closed ? C.hot : C.soft, 3, 0, false);
        if (closed) { g.save(); g.shadowColor = C.hot; g.shadowBlur = 30; k.dot([L[0] + 20, L[1]], Math.max(6, 22 * k.scale), C.h(.85)); g.restore(); }
        k.label(closed ? 'circuit closed' : 'circuit open', [L[0] + 20, L[1] - 34], -40, -60, closed);
      }
      // the spring and its line of action through dead centre (both views)
      var coils = [], n = 14;
      for (var i = 0; i <= n * 2; i++) { var q = lerp(tail, BLADE0, i / (n * 2)), dx = BLADE0[0] - tail[0], dy = BLADE0[1] - tail[1], L2 = Math.hypot(dx, dy), w = (i % 2 ? 1 : -1) * 16; coils.push([q[0] - dy / L2 * w, q[1] + dx / L2 * w]); }
      g.strokeStyle = snap > 0.05 ? C.hot : (panel ? C.line : C.l(.75)); g.lineWidth = k.lw(panel ? 3 : 2.5); k.path(coils); g.stroke();
      g.setLineDash([10, 10]); k.seg([tail[0] - (BLADE0[0] - tail[0]) * 0.15, tail[1] - (BLADE0[1] - tail[1]) * 0.15], [BLADE0[0] + (BLADE0[0] - tail[0]) * 0.25, BLADE0[1] + (BLADE0[1] - tail[1]) * 0.25], snap > 0.05 ? C.hot : C.l(.6), 2); g.setLineDash([]);
      k.ell(PIV[0], PIV[1], 16, 16, snap > 0.05 ? C.hot : C.line, 3, 0, false);
      if (snap > 0.05) { g.save(); g.shadowColor = C.hot; g.shadowBlur = 26 * snap; k.dot(CONTACT, Math.max(6, 18 * snap * Math.min(1.6, k.scale + 0.4)), C.h(.9)); g.restore(); }
      k.label('pivot', PIV, panel ? -40 : -200, panel ? -190 : -150, false);
      k.label('over-centre spring', [(tail[0] + BLADE0[0]) / 2, (tail[1] + BLADE0[1]) / 2], -160, panel ? 150 : 170, snap > 0.05);
      k.label('contacts', CONTACT, 120, panel ? -150 : 150, closed);
    }
  });
})();

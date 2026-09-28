/* Series kit: what every episode of this tutorial series shares. Edit it HERE (the series root),
 * then run `showtime series sync <series>` to copy it into every episode.
 *
 *   KIT.brand / KIT.palette / KIT.look / KIT.fonts   the series look
 *   KIT.state(), KIT.drawApp(T, st), KIT.rects(st)   the product, drawn procedurally, with named
 *                                                    hit-rects so cursors, cameras, spotlights and
 *                                                    callouts target UI by name ('add:0', 'card:c2')
 *   KIT.intro / band / captions / keycaps / recap / outro     the series chrome
 *   KIT.sound.signature / click / key / enter / success / snap / whoosh / step / bed   the series sound
 *   KIT.episode(spec)                                 one call: an episode from its timeline table
 *
 * Everything is a pure function of T (no clocks, no randomness, no state kept between frames).
 * Reference: references/series.md (the pattern), references/film-api.md, references/synth-score.md.
 */
'use strict';

var KIT = (function () {
  var F = Film;
  var K = {};

  // ================================================================== series look
  K.brand = {
    series: 'Planner How-to',            // the series name (intro kicker, start card)
    product: 'Planner',                  // the product being taught
    url: 'planner.example.com/boards/launch',
    key: 'D',                             // the signature motif and the music are in this key
    closing: 'Small steps, every day.',  // last line of every outro
  };
  K.palette = {
    bg: '#eef0f6', bg2: '#e3e6ef', ink: '#171a23', muted: '#555c6b', faint: '#b8bdc9',
    accent: '#5046e5', accent2: '#0f9f6e', accent3: '#e5484d',
    panel: '#ffffff', panel2: '#f6f7fb', line: 'rgba(23,26,35,0.10)', shadow: 'rgba(23,26,35,0.16)',
  };
  K.look = { base: 'clean', backdrop: 'flat', grain: 0.012, vignette: 0.12 };
  K.fonts = ['400 1em "Inter Variable"', '500 1em "Inter Variable"', '650 1em "Inter Variable"', '800 1em "Inter Variable"'];
  // one label colour per kind of card
  K.labels = { design: '#8b5cf6', copy: '#f59e0b', launch: '#e5484d', web: '#0ea5e9', ops: '#10b981' };

  // ================================================================== layout
  // The app window in design coordinates, and the page area inside it (below the title bar).
  // The band sits above the window and the captions below it, so they never cover the UI.
  var WIN = { x: 150, y: 100, w: 1620, h: 846 };
  var BAR = 52;
  var PAGE = { x: WIN.x, y: WIN.y + BAR, w: WIN.w, h: WIN.h - BAR };
  var COL = { x0: 280, y: 118, w: 404, gap: 26, head: 58, card: 96, cardGap: 14 };
  K.WIN = WIN; K.PAGE = PAGE;
  K.CAPTION_Y = 1012;

  // ================================================================== the product: state
  /** The board as the series starts it. Episodes change it with state events (Film.fold). */
  K.state = function () {
    return {
      cols: [['c1', 'c2', 'c3'], ['c4'], ['c5']],
      names: ['To do', 'Doing', 'Done'],
      cards: {
        c1: { title: 'Write launch announcement', label: 'copy', due: 'Mon' },
        c2: { title: 'Pricing page review', label: 'web', due: 'Tue' },
        c3: { title: 'Record product demo', label: 'launch', due: 'Wed' },
        c4: { title: 'Final logo exports', label: 'design', due: 'Today' },
        c5: { title: 'Set up status page', label: 'ops', due: '' },
      },
      composing: -1,          // column index with the "new card" composer open
      draft: '',              // text typed into the composer
      born: {},               // card id -> time it was created (for the pop-in)
      hover: '',              // rect name under the pointer (highlight)
      pressed: '',            // rect name being pressed
      pressT: -1,             // when it was pressed
      toast: '', toastT: -1,  // message + time
      selected: '',           // card id with a focus ring
    };
  };

  // ================================================================== the product: named rects
  /**
   * Named hit-rects of the board for a state (card positions depend on it). World coordinates.
   * Names: board, sidebar, search, share, title, col:i, head:i, card:<id>, add:i, input, save, cancel, nav:i.
   */
  K.rects = function (st) {
    st = st || K.state();
    var colX = function (i) { return COL.x0 + i * (COL.w + COL.gap); };
    var cardTop = function (i, k) { return COL.y + COL.head + k * (COL.card + COL.cardGap); };
    var nCards = function (i) { return st.cols[i].length; };
    var defs = {
      board: [COL.x0 - 16, COL.y - 16, 3 * COL.w + 2 * COL.gap + 32, PAGE.h - COL.y],
      sidebar: [0, 0, 232, PAGE.h],
      title: [COL.x0, 26, 420, 56],
      search: [PAGE.w - 520, 34, 250, 44],
      share: [PAGE.w - 250, 34, 120, 44],
      col: function (i) { return [colX(i), COL.y, COL.w, PAGE.h - COL.y - 24]; },
      head: function (i) { return [colX(i), COL.y, COL.w, COL.head - 8]; },
      card: function (id) {
        for (var i = 0; i < st.cols.length; i++) {
          var k = st.cols[i].indexOf(id);
          if (k >= 0) return [colX(i) + 12, cardTop(i, k), COL.w - 24, COL.card];
        }
        return null;
      },
      add: function (i) {
        var y = cardTop(i, nCards(i)) + (st.composing === i ? COL.card + 64 : 0);
        return [colX(i) + 12, y, COL.w - 24, 46];
      },
      input: function () { var i = Math.max(0, st.composing); return [colX(i) + 12, cardTop(i, nCards(i)), COL.w - 24, COL.card]; },
      save: function () { var i = Math.max(0, st.composing), y = cardTop(i, nCards(i)) + COL.card + 12; return [colX(i) + 12, y, 96, 40]; },
      cancel: function () { var i = Math.max(0, st.composing), y = cardTop(i, nCards(i)) + COL.card + 12; return [colX(i) + 120, y, 84, 40]; },
      nav: function (i) { return [16, 108 + i * 50, 200, 42]; },
    };
    return F.rects(defs, { origin: [PAGE.x, PAGE.y] });
  };

  // ================================================================== the product: drawing
  function pressScale(st, name, T) {
    if (st.pressed !== name || st.pressT < 0) return 1;
    return 1 - 0.05 * F.win(T, st.pressT - 0.06, st.pressT + 0.16, 0.05, 0.1);
  }
  function scaled(r, s, fn) {
    var g = F.g;
    if (s === 1) return fn();
    g.save();
    g.translate(r.x + r.w / 2, r.y + r.h / 2); g.scale(s, s); g.translate(-(r.x + r.w / 2), -(r.y + r.h / 2));
    fn();
    g.restore();
  }
  /** The app window at time T for state st (world coordinates: draw it under the camera). */
  K.drawApp = function (T, st) {
    var ui = K.rects(st), P = F.pal;
    F.browser(WIN, { url: K.brand.url, theme: 'light', page: '#ffffff', bar: BAR }, function (g, w, h) {
      var L = function (name) { return ui.local.apply(null, arguments); };
      // sidebar
      F.box(0, 0, 232, h, 0, { fill: '#f6f7fb' });
      F.line(232, 0, 232, h, { color: P.line, width: 1.5 });
      F.box(24, 30, 34, 34, 10, { fill: P.accent });
      F.box(33, 39, 16, 5, 2, { fill: '#fff' }); F.box(33, 47, 11, 5, 2, { fill: '#fff' });
      F.text(K.brand.product, 70, 55, { size: 24, weight: 750 });
      ['Boards', 'My tasks', 'Calendar', 'Settings'].forEach(function (label, i) {
        var r = L('nav', i);
        if (i === 0) F.box(r.x, r.y, r.w, r.h, 10, { fill: F.rgba(P.accent, 0.1) });
        F.box(r.x + 16, r.y + 13, 16, 16, 5, { fill: i === 0 ? P.accent : 'rgba(23,26,35,0.18)' });
        F.text(label, r.x + 44, r.y + 27, { size: 19, weight: i === 0 ? 650 : 500, color: i === 0 ? P.ink : P.muted });
      });
      // header
      var tr = L('title');
      F.text('Launch plan', tr.x, tr.y + 40, { size: 34, weight: 780 });
      var sr = L('search');
      F.box(sr.x, sr.y, sr.w, sr.h, 12, { fill: '#f3f4f8', stroke: P.line });
      F.circle(sr.x + 22, sr.y + 20, 7, { stroke: P.muted, lineWidth: 2 });
      F.text('Search cards', sr.x + 40, sr.y + 28, { size: 17, color: P.faint });
      var sh = L('share');
      scaled(sh, pressScale(st, 'share', T), function () {
        F.box(sh.x, sh.y, sh.w, sh.h, 12, { fill: P.accent });
        F.text('Share', sh.x + sh.w / 2, sh.y + sh.h / 2 + 1, { size: 18, weight: 650, align: 'center', baseline: 'middle', color: '#fff' });
      });
      ['#f59e0b', '#0ea5e9', '#8b5cf6'].forEach(function (c, i) {
        F.circle(w - 96 + i * 26, 56, 17, { fill: c, stroke: '#fff', lineWidth: 3 });
      });
      // columns
      st.cols.forEach(function (ids, i) {
        var c = L('col', i), hd = L('head', i);
        F.box(c.x, c.y, c.w, c.h, 16, { fill: '#f3f4f8' });
        F.text(st.names[i], hd.x + 20, hd.y + 34, { size: 20, weight: 700 });
        F.pill(String(ids.length), hd.x + 34 + F.measure(st.names[i], { size: 20, weight: 700 }) + 14, hd.y + 27,
          { size: 15, fill: 'rgba(23,26,35,0.08)', color: P.muted, weight: 650 });
        ids.forEach(function (id) { drawCard(T, st, id, L('card', id)); });
        if (st.composing === i) drawComposer(T, st, L('input'), L('save'), L('cancel'));
        var ad = L('add', i), hot = st.hover === 'add:' + i;
        scaled(ad, pressScale(st, 'add:' + i, T), function () {
          F.box(ad.x, ad.y, ad.w, ad.h, 12, { fill: hot ? 'rgba(80,70,229,0.10)' : 'rgba(23,26,35,0.04)' });
          F.text('+  Add card', ad.x + 18, ad.y + 30, { size: 18, weight: 600, color: hot ? P.accent : P.muted });
        });
      });
      // toast
      if (st.toast && st.toastT >= 0) {
        var a = F.win(T, st.toastT, st.toastT + 2.2, 0.2, 0.3);
        if (a > 0) {
          // top right of the page: never under the captions or the pointer's work
          var tw = F.measure(st.toast, { size: 19, weight: 600 }) + 80, tx = w - tw - 28, ty = 96 - (1 - F.E.outCubic(a)) * 20;
          g.save(); g.globalAlpha *= a;
          F.box(tx, ty, tw, 54, 27, { fill: '#171a23', shadow: { blur: 24, y: 8, color: 'rgba(0,0,0,0.25)' } });
          F.circle(tx + 30, ty + 27, 9, { fill: P.accent2 });
          F.text(st.toast, tx + 50, ty + 28, { size: 19, weight: 600, baseline: 'middle', color: '#fff' });
          g.restore();
        }
      }
    });
  };
  function drawCard(T, st, id, r) {
    var c = st.cards[id], P = F.pal, g = F.g;
    if (!c || !r) return;
    var born = st.born[id], a = born === undefined ? 1 : F.seg(T, born, born + 0.45);
    var q = F.E.snappy ? F.E.snappy(a) : a;
    g.save();
    g.globalAlpha *= F.clamp(a * 1.6);
    scaled(r, (born === undefined ? 1 : F.lerp(0.92, 1, q)) * pressScale(st, 'card:' + id, T), function () {
      F.box(r.x, r.y, r.w, r.h, 12, { fill: '#ffffff', stroke: st.selected === id ? P.accent : 'rgba(23,26,35,0.08)', lineWidth: st.selected === id ? 2.5 : 1.2,
        shadow: { blur: 14, y: 4, color: 'rgba(23,26,35,0.08)' } });
      var lc = K.labels[c.label] || P.accent;
      F.box(r.x + 16, r.y + 16, 46, 8, 4, { fill: lc });
      F.text(c.title, r.x + 16, r.y + 56, { size: 19, weight: 600, maxWidth: r.w - 32 });
      if (c.due) F.text(c.due, r.x + 16, r.y + 82, { size: 15, weight: 500, color: P.muted });
      F.circle(r.x + r.w - 26, r.y + 76, 11, { fill: F.mixColor(lc, '#ffffff', 0.35) });
    });
    g.restore();
  }
  function drawComposer(T, st, r, save, cancel) {
    var P = F.pal;
    F.box(r.x, r.y, r.w, r.h, 12, { fill: '#ffffff', stroke: P.accent, lineWidth: 2.5, shadow: { blur: 18, y: 6, color: 'rgba(80,70,229,0.18)' } });
    if (!st.draft) F.text('Card title...', r.x + 16, r.y + 40, { size: 19, color: P.faint });
    var tw = F.text(st.draft || '', r.x + 16, r.y + 40, { size: 19, weight: 600, maxWidth: r.w - 32 }) || 0;
    // caret: blinks on a 1 s cycle, solid while typing
    if (st.caret !== false && (F.fract(F.T) < 0.55 || st.typing)) F.box(r.x + 18 + tw, r.y + 22, 2.5, 24, 1, { fill: P.accent });
    scaled(save, pressScale(st, 'save', T), function () {
      F.box(save.x, save.y, save.w, save.h, 10, { fill: P.accent });
      F.text('Save', save.x + save.w / 2, save.y + save.h / 2 + 1, { size: 17, weight: 650, align: 'center', baseline: 'middle', color: '#fff' });
    });
    F.text('Cancel', cancel.x + cancel.w / 2, cancel.y + cancel.h / 2 + 1, { size: 17, weight: 550, align: 'center', baseline: 'middle', color: P.muted });
  }

  // ================================================================== series chrome
  /** Episode intro card over the backdrop: series name, rule, episode number, title, subtitle. */
  K.intro = function (T, t0, t1, ep) {
    var P = F.pal, g = F.g;
    var out = 1 - F.seg(T, t1 - 0.45, t1, 'inOutSine');
    if (out <= 0) return;
    g.save();
    g.globalAlpha *= out;
    F.box(0, 0, F.W, F.H, 0, { fill: P.bg });
    var cx = F.W / 2, y = F.H / 2 - 40;
    var a1 = F.seg(T, t0 + 0.15, t0 + 0.7, 'outCubic'), a2 = F.seg(T, t0 + 0.35, t0 + 1.0, 'outCubic');
    var a3 = F.seg(T, t0 + 0.55, t0 + 1.25, 'outCubic'), a4 = F.seg(T, t0 + 0.8, t0 + 1.5, 'outCubic');
    F.text(K.brand.series.toUpperCase(), cx, y - 150, { size: 22, weight: 650, tracking: 0.3, align: 'center', color: P.muted, alpha: a1 });
    F.box(cx - 45 * a2, y - 118, 90 * a2, 6, 3, { fill: P.accent });
    F.text('Episode ' + (ep.number < 10 ? '0' : '') + ep.number, cx, y - 58, { size: 30, weight: 600, align: 'center', color: P.accent, alpha: a2 });
    F.text(ep.title, cx, y + 30 + (1 - a3) * 16, { size: 84, weight: 800, align: 'center', tracking: -0.02, alpha: a3, maxWidth: F.W * 0.86 });
    if (ep.subtitle) F.text(ep.subtitle, cx, y + 100 + (1 - a4) * 12, { size: 32, weight: 450, align: 'center', color: P.muted, alpha: a4, maxWidth: F.W * 0.7 });
    g.restore();
  };
  /** Step band across the top (numbered steps with progress). */
  // opaque: zoomed shots slide the app under the band, and nothing of it may show through
  K.band = function (T, steps, end) { return F.stepBand(T, steps, { end: end, h: 72, size: 28, fill: F.pal.bg }); };
  /** Captions under the window: [[t0, t1, text], ...]. */
  K.captions = function (T, list) {
    return F.captions(T, list, { y: K.CAPTION_Y, size: 30, maxWidth: F.W * 0.78, fill: 'rgba(23,26,35,0.86)' });
  };
  /** Keycap overlay: presses [[t, ['⇧', '↓'], label?], ...]; each shows from t-0.5 to t+1.2. */
  K.keycaps = function (T, presses) {
    for (var i = 0; i < (presses || []).length; i++) {
      var k = presses[i], t = k[0];
      var v = F.win(T, t - 0.5, t + 1.2, 0.15, 0.3);
      if (v <= 0) continue;
      var y = 872;
      F.box(F.W / 2 - 170, y - 58, 340, 116, 26, { fill: 'rgba(23,26,35,0.82)', alpha: v });
      F.keyCombo(k[1], F.W / 2, y - (k[2] ? 10 : 0), {
        size: 62, alpha: v, p: F.seg(T, t - 0.5, t - 0.2), press: F.win(T, t - 0.04, t + 0.14, 0.04, 0.08),
      });
      if (k[2]) F.text(k[2], F.W / 2, y + 44, { size: 17, weight: 600, align: 'center', color: '#e8e9ee', alpha: v });
    }
  };
  /** Recap card: items [[keys | '', 'what it does'], ...] listed one by one. */
  K.recap = function (T, t0, t1, items) {
    var P = F.pal, g = F.g;
    var v = Math.min(F.seg(T, t0, t0 + 0.45, 'inOutSine'), 1 - F.seg(T, t1 - 0.4, t1, 'inOutSine'));
    if (v <= 0) return;
    g.save();
    g.globalAlpha *= v;
    F.box(0, 0, F.W, F.H, 0, { fill: P.bg });
    F.text('RECAP', F.W / 2, 250, { size: 24, weight: 700, tracking: 0.3, align: 'center', color: P.accent });
    var n = items.length, rowH = 96, y0 = F.H / 2 - (n - 1) * rowH / 2 + 30;
    items.forEach(function (it, i) {
      var a = F.seg(T, t0 + 0.35 + i * 0.28, t0 + 0.8 + i * 0.28, 'outCubic'), y = y0 + i * rowH;
      g.save(); g.globalAlpha *= a; g.translate((1 - a) * -24, 0);
      if (it[0] && it[0].length) F.keyCombo(it[0], F.W / 2 - 170, y, { size: 54, press: 0 });
      else F.circle(F.W / 2 - 170, y, 10, { fill: P.accent });
      F.text(it[1], F.W / 2 - 40, y + 2, { size: 36, weight: 600, baseline: 'middle' });
      g.restore();
    });
    g.restore();
  };
  /** Outro: what comes next + the series closing line, then fade to the backdrop. */
  K.outro = function (T, t0, t1, next) {
    var P = F.pal, g = F.g;
    var v = F.seg(T, t0, t0 + 0.5, 'inOutSine');
    if (v <= 0) return;
    g.save();
    g.globalAlpha *= v;
    F.box(0, 0, F.W, F.H, 0, { fill: P.bg });
    var a1 = F.seg(T, t0 + 0.3, t0 + 0.9, 'outCubic'), a2 = F.seg(T, t0 + 0.8, t0 + 1.5, 'outCubic');
    if (next) {
      F.text('NEXT', F.W / 2, F.H / 2 - 110, { size: 22, weight: 700, tracking: 0.3, align: 'center', color: P.accent, alpha: a1 });
      F.text(next, F.W / 2, F.H / 2 - 40 + (1 - a1) * 14, { size: 54, weight: 750, align: 'center', alpha: a1, maxWidth: F.W * 0.84 });
    }
    F.box(F.W / 2 - 40 * a2, F.H / 2 + 40, 80 * a2, 5, 2.5, { fill: P.accent });
    F.text(K.brand.closing, F.W / 2, F.H / 2 + 110, { size: 34, weight: 450, align: 'center', color: P.muted, alpha: a2 });
    F.text(K.brand.product.toUpperCase(), F.W / 2, F.H - 120, { size: 20, weight: 750, tracking: 0.35, align: 'center', color: P.faint, alpha: a2 });
    g.restore();
  };

  // ================================================================== series sound
  var S = K.sound = {};
  function keyScale() { return Synth.scale(K.brand.key + '5', 'major'); }
  /** The series signature: four bell notes over a swelling chord. resolve: the outro's falling answer. */
  S.signature = function (m, t, o) {
    o = o || {};
    var sc = keyScale(), degs = o.resolve ? [7, 4, 2, 0] : [0, 4, 2, 7], step = o.resolve ? 0.2 : 0.16;
    m.pad(Synth.chord(K.brand.key + 'add9', 3), t - 0.35, o.resolve ? 3.2 : 2.4, { vel: 0.3, attack: 0.5, release: 1.6, cutoff: 1800, bus: 'sfx' });
    degs.forEach(function (d, i) { m.bell(sc.degree(d), t + i * step, { vel: 0.42 - i * 0.04, decay: 2.2, send: 0.5, bus: 'sfx' }); });
    m.bass(Synth.noteName(sc.degree(0) - 36), t, 1.2, { vel: 0.35, cutoff: 220, bus: 'sfx' });
  };
  S.click = function (m, t) { m.click(t, { vel: 0.62 }); m.thock(t + 0.008, { vel: 0.22 }); };
  S.key = function (m, t) { m.keyClick(t, { vel: 0.5, release: true }); };
  S.enter = function (m, t) { m.keyClick(t - 0.01, { vel: 0.55, release: false }); m.thock(t, { vel: 0.5 }); };
  S.success = function (m, t) { var sc = keyScale(); m.chime([sc.degree(0), sc.degree(2), sc.degree(4), sc.degree(7)], t, { vel: 0.3 }); };
  S.snap = function (m, t) { m.thock(t, { vel: 0.35, tone: 240 }); m.tick(t + 0.012, { tone: 3100, vel: 0.22 }); };
  S.whoosh = function (m, t) { m.whoosh(t, { vel: 0.22, dur: 0.8, lo: 400, hi: 2600 }); };
  S.step = function (m, t) { m.tick(t, { tone: 2300, vel: 0.35 }); m.bell(keyScale().degree(4), t + 0.02, { vel: 0.16, decay: 1.2, bus: 'sfx' }); };
  /** Music bed over [t0, t1): one chord a bar (pads resume mid-chord on any seek), bass, soft pulse. */
  S.bed = function (m, t0, t1, o) {
    o = o || {};
    var g = m.grid({ bpm: o.bpm || 84, offset: t0 });
    var chords = Synth.progression(K.brand.key + '3', 'major', o.numerals || ['I', 'vi7', 'IVmaj7', 'V'], { range: [50, 72] });
    for (var b = 0; g.t(b) < t1 - 0.1; b++) {
      var c = chords[b % chords.length], t = g.t(b), len = Math.min(g.barDur * 1.02, t1 - t + 0.4);
      m.pad(c, t, len, { vel: 0.3, attack: b === 0 ? 0.6 : 0.4, cutoff: 1300 });
      m.bass(Synth.noteName(c[0] - 12), t, Math.min(g.barDur * 0.95, t1 - t), { vel: 0.26, cutoff: 280 });
      if (b > 0 && o.pulse !== false) m.arp(c, t, Math.min(t + g.barDur, t1), { grid: g, div: 2, inst: 'marimba', vel: 0.12, pattern: 'up' });
    }
    m.level('music', o.db === undefined ? -13 : o.db);
    m.fade('music', t1 - 1.2, t1, -40);
  };

  // ================================================================== one-call episode
  /**
   * Build and start an episode from its timeline table (every time below is also what the score
   * uses: picture and sound come from the same numbers).
   * spec: {number, title, subtitle, duration,
   *   intro: [t0, t1],  steps: [[t, 'title'], ...],  stepsEnd: t,
   *   recap: {t0, t1, items: [[keys, 'what'], ...]},  outro: {t0, next},
   *   state: [[t, patch | fn(s, dt)], ...]            UI changes (Film.fold on KIT.state())
   *   cursor: [[t, 'rect name' | x, y, {click, at, dx, dy}], ...]   named targets resolve at t
   *   camera: [[t, 'rect name' | [x, y], zoom?, {whoosh}], ...]
   *   captions: [[t0, t1, 'text'], ...],  keys: [[t, ['⌘', '↵'], 'label?', 'enter'|'key'], ...],
   *   typing: [[t, 'text', cps], ...]     typed into the composer, one key sound per character
   *   spots: [[t0, t1, 'rect name', pad?], ...],  callouts: [[t0, t1, 'rect name', 'text', 'left'|'right'|'above'|'below', 'sub?'], ...],
   *   pulses: [[t0, t1, 'rect name'], ...]  an attention ring around a target (hover, "look here")
   *   success: [t, ...],  snaps: [t, ...] (something clicks into place),  music: {bpm, numerals, db},
   *   draw(T, st, ui): extra drawing (world)}.  A cursor key's {tag: 'Right-click'} labels the pointer.
   */
  K.episode = function (spec) {
    var ep = spec;
    var intro = ep.intro || [0, 3.4], end = ep.stepsEnd || (ep.recap ? ep.recap.t0 : ep.duration);
    var events = [];
    (ep.state || []).forEach(function (e) { events.push(e); });
    (ep.typing || []).forEach(function (ty) {
      var t = ty[0], text = ty[1], cps = ty[2] || 12;
      events.push([t, function (s, dt) {
        var n = Math.min(text.length, Math.floor(dt * cps + 1e-6));
        s.draft = text.slice(0, n);
        s.typing = n < text.length;
      }]);
    });
    function stateAt(T) { return F.fold(T, K.state(), events); }
    // named cursor targets resolve with the UI as it is at each key's time
    var cursorKeys = (ep.cursor || []).map(function (k) {
      if (typeof k[1] !== 'string') return k;
      var st = stateAt(k[0] - 0.001), opt = k[2] || {}, pt = K.rects(st).point(k[1], opt.at);
      return [k[0], pt[0] + (opt.dx || 0), pt[1] + (opt.dy || 0), opt];
    });
    var camKeys = (ep.camera || []).map(function (k) {
      var target = k[1], zoom = k[2] === undefined || k[2] === null ? 1 : k[2];
      if (typeof target === 'string') {
        var r = K.rects(stateAt(k[0])).rect(target), f = F.focus(r, { pad: 0.2, clamp: false });
        var z = k[2] === undefined || k[2] === null ? f.zoom : zoom;
        // aim a little above the target's centre: the step band covers the top of the frame
        return [k[0], f.x, f.y - 36 / z, z, (k[3] && k[3].ease) || undefined];
      }
      if (Array.isArray(target)) return [k[0], target[0], target[1], zoom, (k[3] && k[3].ease) || undefined];
      return [k[0], F.W / 2, F.H / 2, 1];
    });
    var bounds = { x: WIN.x - 40, y: WIN.y - 90, w: WIN.w + 80, h: WIN.h + 180 };
    var chapters = [[intro[0], 'Intro']].concat((ep.steps || []).map(function (s) { return [s[0], s[1]]; }));
    if (ep.recap) chapters.push([ep.recap.t0, 'Recap']);

    function scenes(T, g) {
      var st = stateAt(T), ui = K.rects(st);
      var cam = camKeys.length ? F.camera(T, camKeys, { clamp: bounds }) : { x: F.W / 2, y: F.H / 2, zoom: 1 };
      var cur = F.cursorPath(T, cursorKeys);
      // hover: the rect under the pointer (drawn highlighted by the app)
      st.hover = '';
      ['add:0', 'add:1', 'add:2', 'share', 'save'].forEach(function (n) {
        try { var r = ui.rect(n); if (cur.x >= r.x && cur.x <= r.x + r.w && cur.y >= r.y && cur.y <= r.y + r.h) st.hover = n; } catch (e) { /* not on screen */ }
      });
      if (T >= intro[1] - 0.5 && T < (ep.recap ? ep.recap.t0 + 0.5 : ep.duration)) {
        F.withCamera(cam, function () {
          K.drawApp(T, st);
          (ep.spots || []).forEach(function (s) {
            var v = F.win(T, s[0], s[1], 0.3, 0.3);
            if (v > 0) { var r = ui.rect(s[2]); F.spotlight({ x: r.x, y: r.y, w: r.w, h: r.h, r: 14 }, { p: v, pad: s[3] === undefined ? 10 : s[3], dim: 0.45 }); }
          });
          (ep.callouts || []).forEach(function (c) {
            var v = F.seg(T, c[0], c[0] + 0.7) * (1 - F.seg(T, c[1] - 0.3, c[1]));
            if (v <= 0) return;
            var side = c[4] || 'right', a = ui.point(c[2], side === 'above' ? 'top' : side === 'below' ? 'bottom' : side);
            var d = side === 'left' ? [-150, -60] : side === 'above' ? [40, -120] : side === 'below' ? [40, 110] : [150, -60];
            F.callout(a[0], a[1], a[0] + d[0], a[1] + d[1], c[3], { p: v, size: 24, sub: c[5] });
          });
          (ep.pulses || []).forEach(function (pl) {
            if (T >= pl[0] && T <= pl[1] + 1) { var r = ui.rect(pl[2]); F.pulse({ x: r.x, y: r.y, w: r.w, h: r.h, r: 12 }, T, pl[0], { t1: pl[1] }); }
          });
          if (ep.draw) ep.draw(T, st, ui);
          if (cur.click) F.ripple(cur.click.x, cur.click.y, cur.clickAge, { radius: 30, color: F.pal.accent });
          // a key's {tag: 'Right-click'} labels the pointer from 0.8 s before that key until 0.9 s after it
          var tag = '', tagA = 0;
          cursorKeys.forEach(function (k) {
            var o = k[3] || {};
            if (o.tag) { var a = F.win(T, k[0] - 0.8, k[0] + 0.9, 0.2, 0.25); if (a > tagA) { tagA = a; tag = o.tag; } }
          });
          if (T < (ep.recap ? ep.recap.t0 : ep.duration)) F.cursor(cur.x, cur.y, { press: cur.press, scale: 1.45, color: '#171a23', tag: tag, tagAlpha: tagA });
        });
        K.band(T, ep.steps || [], end);
        K.keycaps(T, ep.keys);
        K.captions(T, ep.captions || []);
      }
      if (T < intro[1]) K.intro(T, intro[0], intro[1], ep);
      if (ep.recap) K.recap(T, ep.recap.t0, ep.outro ? ep.outro.t0 + 0.5 : ep.duration, ep.recap.items || []);
      if (ep.outro) K.outro(T, ep.outro.t0, ep.duration, ep.outro.next);
    }

    var score = Synth.score(function (m) {
      S.signature(m, intro[0] + 0.5);
      S.bed(m, intro[1] - 0.6, ep.recap ? ep.recap.t0 + 0.4 : ep.duration - 1, ep.music);
      (ep.steps || []).forEach(function (s) { S.step(m, s[0]); });
      cursorKeys.forEach(function (k) { if (k[3] && k[3].click) S.click(m, k[0]); });
      (ep.keys || []).forEach(function (k) { if (k[3] === 'enter' || /↵|⏎|Enter/.test(String(k[1][k[1].length - 1]))) S.enter(m, k[0]); else S.key(m, k[0]); });
      (ep.typing || []).forEach(function (ty) {
        for (var i = 0; i < ty[1].length; i++) if (ty[1][i] !== ' ') m.keyClick(ty[0] + (i + 1) / (ty[2] || 12) - 0.012, { vel: 0.4, seed: i + 3, release: false });
      });
      (ep.camera || []).forEach(function (k) { if (k[3] && k[3].whoosh) S.whoosh(m, k[0] - 0.25); });
      (ep.success || []).forEach(function (t) { S.success(m, t); });
      (ep.snaps || []).forEach(function (t) { S.snap(m, t); });
      if (ep.recap) (ep.recap.items || []).forEach(function (it, i) { m.tick(ep.recap.t0 + 0.5 + i * 0.28, { tone: 1900, vel: 0.25 }); });
      if (ep.outro) S.signature(m, ep.outro.t0 + 0.4, { resolve: true });
      m.end(ep.duration, { fade: 1.2 });
    }, { bpm: (ep.music && ep.music.bpm) || 84, seed: 11 + (ep.number || 0), reverb: { seconds: 2.4, wet: 0.7 }, master: { gain: 7 } });

    return Film.start({
      look: K.look, palette: K.palette, fonts: K.fonts, design: [1920, 1080],
      acts: chapters, subtitle: ep.subtitle || '', kicker: K.brand.series + ' · Episode ' + (ep.number < 10 ? '0' : '') + ep.number,
      fadeOut: 0.6, scenes: scenes, score: score,
    });
  };

  /**
   * The series opener (the root project of the series): the series name, a tagline and the
   * episode list, on the signature motif. spec: {duration, motif (time of the motif), tagline,
   * episodes: ['01 · Title', ...]}.
   */
  K.opener = function (spec) {
    var D = spec.duration || 8, eps = spec.episodes || [];
    function scenes(T) {
      var P = F.pal, cx = F.W / 2;
      var a1 = F.seg(T, 0.3, 1.0, 'outCubic'), a2 = F.seg(T, 0.7, 1.4, 'outCubic'), a3 = F.seg(T, 1.1, 1.8, 'outCubic');
      F.box(cx - 60 * a1, 300, 120 * a1, 7, 3.5, { fill: P.accent });
      F.text(K.brand.series, cx, 420 + (1 - a2) * 18, { size: 104, weight: 800, align: 'center', tracking: -0.025, alpha: a2 });
      if (spec.tagline) F.text(spec.tagline, cx, 500 + (1 - a3) * 12, { size: 36, weight: 450, align: 'center', color: P.muted, alpha: a3 });
      eps.forEach(function (e, i) {
        var a = F.seg(T, 2.0 + i * 0.35, 2.5 + i * 0.35, 'outCubic');
        F.pill(e, cx, 620 + i * 64, { size: 24, fill: F.rgba(P.accent, 0.1), color: P.ink, weight: 600, alpha: a });
      });
    }
    var score = Synth.score(function (m) {
      var t0 = spec.motif === undefined ? 0.6 : spec.motif;
      S.signature(m, t0);
      S.bed(m, t0 + 0.8, D - 0.5, { pulse: false, db: -15 });
      eps.forEach(function (e, i) { m.tick(2.05 + i * 0.35, { tone: 2000, vel: 0.25 }); });
      m.end(D, { fade: 1.5 });
    }, { seed: 5, reverb: { seconds: 2.4, wet: 0.7 }, master: { gain: 7 } });
    return Film.start({
      look: K.look, palette: K.palette, fonts: K.fonts, design: [1920, 1080], fadeIn: 0.4, fadeOut: 0.8,
      subtitle: spec.tagline || '', kicker: K.brand.product, scenes: scenes, score: score,
    });
  };

  return K;
})();

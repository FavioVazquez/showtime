/* The demo app, drawn procedurally. Everything is a pure function of T.
 * WIN is the browser window in design coordinates; UI rects below are in page coordinates
 * (0,0 = top-left of the page area) and APP.world() converts them for the camera and cursor. */
'use strict';

var WIN = { x: 210, y: 150, w: 1500, h: 840 };
// primary buttons carry white text: a deeper blue than the accent keeps it at >= 4.5:1 contrast
var BTN = '#3d56c0';
var BAR = Math.max(36, WIN.w * 0.034);            // browser title-bar height used by Film.browser

var UI = {
  sidebar: { x: 0, y: 0, w: 280 },
  newBtn: { x: 1240, y: 34, w: 220, h: 58 },
  cards: [
    { x: 320, y: 130, w: 360, h: 210, title: 'Onboarding tour', meta: 'Edited 2 days ago', hue: '#f59f00' },
    { x: 710, y: 130, w: 360, h: 210, title: 'Pricing explainer', meta: 'Edited last week', hue: '#35c79a' },
  ],
  newCard: { x: 1100, y: 130, w: 360, h: 210 },
  modal: { x: 450, y: 230, w: 600, h: 320 },
  input: { x: 490, y: 340, w: 520, h: 62 },
};
UI.renderBtn = { x: UI.newCard.x + UI.newCard.w - 142, y: UI.newCard.y + UI.newCard.h - 60, w: 120, h: 42 };

var APP = {
  /** Page rect -> design (world) rect. */
  world: function (r) {
    return { x: WIN.x + r.x, y: WIN.y + BAR + r.y, w: r.w || 0, h: r.h || 0 };
  },
  center: function (r) {
    var w = APP.world(r);
    return [w.x + w.w / 2, w.y + w.h / 2];
  },
};

/** Everything that changes in the app, derived from T. */
function appState(T) {
  var F = Film;
  return {
    modal: F.seg(T, CUE.modal, CUE.modal + 0.35) * (1 - F.seg(T, CUE.combo + 0.12, CUE.combo + 0.36)),
    typed: F.seg(T, CUE.typeStart, CUE.typeEnd),
    cardIn: F.seg(T, CUE.combo + 0.2, CUE.combo + 0.75),
    render: F.seg(T, CUE.click2 + 0.15, CUE.renderEnd, 'inOutSine'),
    done: T >= CUE.renderEnd,
    toastCreated: F.win(T, CUE.combo + 0.35, CUE.combo + 2.1, 0.25, 0.3),
    toastDone: F.win(T, CUE.renderEnd + 0.1, CUE.duration + 1, 0.25, 0),
    pressNew: F.win(T, CUE.click1 - 0.06, CUE.click1 + 0.14, 0.05, 0.1),
    pressRender: F.win(T, CUE.click2 - 0.06, CUE.click2 + 0.14, 0.05, 0.1),
  };
}

/** Draw the app window at time T (in world coordinates, under the camera). */
function drawApp(T, st) {
  var F = Film;
  F.browser(WIN, { url: 'studio.example.com/projects', theme: 'dark', page: '#12141a' }, function (g, w, h) {
    // sidebar
    F.box(0, 0, UI.sidebar.w, h, 0, { fill: '#171a21' });
    F.line(UI.sidebar.w, 0, UI.sidebar.w, h, { color: 'rgba(255,255,255,0.06)', width: 1.5 });
    F.box(30, 36, 34, 34, 9, { fill: F.pal.accent });
    F.text('Studio', 78, 61, { size: 26, weight: 700 });
    ['Projects', 'Assets', 'Brand kit', 'Settings'].forEach(function (label, i) {
      var y = 130 + i * 56;
      if (i === 0) F.box(18, y - 32, UI.sidebar.w - 36, 46, 10, { fill: 'rgba(109,139,255,0.14)' });
      F.box(38, y - 18, 18, 18, 5, { fill: i === 0 ? F.pal.accent : 'rgba(255,255,255,0.22)' });
      F.text(label, 70, y - 3, { size: 21, weight: i === 0 ? 650 : 500, color: i === 0 ? F.pal.ink : F.pal.muted });
    });
    // header
    F.text('Projects', 320, 76, { size: 38, weight: 750 });
    var b = UI.newBtn, s = 1 - 0.04 * st.pressNew;
    g.save();
    g.translate(b.x + b.w / 2, b.y + b.h / 2); g.scale(s, s); g.translate(-(b.x + b.w / 2), -(b.y + b.h / 2));
    F.box(b.x, b.y, b.w, b.h, 12, { fill: F.mixColor(BTN, '#ffffff', 0.08 * st.pressNew) });
    F.text('+  New project', b.x + b.w / 2, b.y + b.h / 2 + 1, { size: 22, weight: 650, align: 'center', baseline: 'middle', color: '#ffffff' });
    g.restore();
    // existing cards
    UI.cards.forEach(function (c) { projectCard(c, c.title, c.meta, c.hue, null); });
    // the new card
    if (st.cardIn > 0) {
      var q = F.E.snappy(st.cardIn), nc = UI.newCard;
      g.save();
      g.globalAlpha *= F.clamp(st.cardIn * 2);
      g.translate(nc.x + nc.w / 2, nc.y + nc.h / 2); g.scale(F.lerp(0.9, 1, q), F.lerp(0.9, 1, q)); g.translate(-(nc.x + nc.w / 2), -(nc.y + nc.h / 2));
      projectCard(nc, CUE.text, st.done ? 'Rendered just now' : (st.render > 0 ? 'Rendering…' : 'Created just now'), F.pal.accent, st);
      g.restore();
    }
    // list rows below the cards (quiet texture)
    for (var r = 0; r < 4; r++) {
      var ry = 400 + r * 86;
      F.box(320, ry, 1140, 66, 12, { fill: 'rgba(255,255,255,0.03)' });
      F.box(344, ry + 22, 22, 22, 6, { fill: 'rgba(255,255,255,0.12)' });
      F.box(384, ry + 26, 220 + (r * 53) % 140, 14, 7, { fill: 'rgba(255,255,255,0.10)' });
      F.box(1300, ry + 26, 120, 14, 7, { fill: 'rgba(255,255,255,0.06)' });
    }
    // modal
    if (st.modal > 0) drawModal(g, w, h, st);
    // toasts
    toast(g, w, h, 'Project created', st.toastCreated, F.pal.accent2);
    toast(g, w, h, 'Rendered in 12 s', st.toastDone, F.pal.accent2);
  });
}

function projectCard(c, title, meta, hue, st) {
  var F = Film;
  F.card(c.x, c.y, c.w, c.h, { fill: '#1a1d25', radius: 16, shadow: { blur: 30, y: 12, color: 'rgba(0,0,0,0.4)' } });
  var g = F.g;
  g.save();
  F.rr(c.x, c.y, c.w, 96, [16, 16, 0, 0]); g.clip();
  var gr = g.createLinearGradient(c.x, c.y, c.x + c.w, c.y + 96);
  gr.addColorStop(0, F.rgba(hue, 0.55)); gr.addColorStop(1, F.rgba(hue, 0.12));
  g.fillStyle = gr; g.fillRect(c.x, c.y, c.w, 96);
  g.restore();
  F.text(title, c.x + 22, c.y + 136, { size: 24, weight: 650, maxWidth: c.w - 44 });
  F.text(meta, c.x + 22, c.y + 170, { size: 18, color: F.pal.muted });
  if (!st) return;
  var rb = UI.renderBtn;
  if (st.render > 0 && !st.done) {
    F.box(c.x + 22, c.y + 186, c.w - 44, 8, 4, { fill: 'rgba(255,255,255,0.08)' });
    F.box(c.x + 22, c.y + 186, (c.w - 44) * st.render, 8, 4, { fill: F.pal.accent });
  }
  if (!(st.render > 0)) {
    var s = 1 - 0.05 * st.pressRender;
    var g2 = F.g;
    g2.save();
    g2.translate(rb.x + rb.w / 2, rb.y + rb.h / 2); g2.scale(s, s); g2.translate(-(rb.x + rb.w / 2), -(rb.y + rb.h / 2));
    F.box(rb.x, rb.y, rb.w, rb.h, 10, { fill: 'rgba(109,139,255,0.18)', stroke: F.rgba(F.pal.accent, 0.7), lineWidth: 1.5 });
    F.text('Render', rb.x + rb.w / 2, rb.y + rb.h / 2 + 1, { size: 18, weight: 650, align: 'center', baseline: 'middle', color: '#dfe5ff' });
    g2.restore();
  } else if (st.done) {
    F.circle(rb.x + rb.w - 20, rb.y + rb.h / 2, 16, { fill: F.pal.accent2 });
    F.path([[rb.x + rb.w - 28, rb.y + rb.h / 2], [rb.x + rb.w - 22, rb.y + rb.h / 2 + 6], [rb.x + rb.w - 11, rb.y + rb.h / 2 - 7]],
      F.seg(F.T, CUE.renderEnd, CUE.renderEnd + 0.3, 'outCubic'), { color: '#0b0c10', width: 4 });
  }
}

function drawModal(g, w, h, st) {
  var F = Film, m = UI.modal, q = F.E.reveal(st.modal);
  g.save();
  g.globalAlpha *= st.modal;
  g.fillStyle = 'rgba(5,6,9,0.55)';
  g.fillRect(0, 0, w, h);
  var cx = m.x + m.w / 2, cy = m.y + m.h / 2, s = F.lerp(0.96, 1, q);
  g.translate(cx, cy + (1 - q) * 16); g.scale(s, s); g.translate(-cx, -cy);
  F.card(m.x, m.y, m.w, m.h, { fill: '#1c1f28', radius: 18, shadow: { blur: 60, y: 24, color: 'rgba(0,0,0,0.5)' } });
  F.text('New project', m.x + 40, m.y + 64, { size: 30, weight: 750 });
  F.text('Name', m.x + 40, m.y + 100, { size: 18, weight: 600, color: F.pal.muted });
  var ip = UI.input;
  F.box(ip.x, ip.y, ip.w, ip.h, 12, { fill: '#12141a', stroke: F.rgba(F.pal.accent, 0.85), lineWidth: 2 });
  if (st.typed <= 0) F.text('Untitled project', ip.x + 20, ip.y + 40, { size: 24, color: 'rgba(255,255,255,0.28)' });
  F.typewriter(CUE.text, ip.x + 20, ip.y + 40, st.typed, { size: 24, weight: 500, caret: true, caretColor: F.pal.accent });
  // shortcut hint: symbols are vector keycaps (the bundled fonts have no ⌘ or ↵ glyphs)
  var kw = F.keyCombo(['⌘', '↵'], m.x + 86, m.y + m.h - 50, { size: 30 });
  F.text('to create', m.x + 40 + kw + 14, m.y + m.h - 44, { size: 18, color: F.pal.muted });
  F.box(m.x + m.w - 170, m.y + m.h - 72, 130, 48, 10, { fill: BTN });
  F.text('Create', m.x + m.w - 105, m.y + m.h - 47, { size: 20, weight: 650, align: 'center', baseline: 'middle', color: '#fff' });
  g.restore();
}

function toast(g, w, h, label, a, color) {
  var F = Film;
  if (a <= 0) return;
  var tw = F.measure(label, { size: 22, weight: 600 }) + 90, x = w / 2 - tw / 2, y = h - 110 + (1 - F.E.outCubic(a)) * 24;
  g.save();
  g.globalAlpha *= a;
  F.box(x, y, tw, 60, 30, { fill: '#232733', stroke: 'rgba(255,255,255,0.08)', shadow: { blur: 30, y: 10, color: 'rgba(0,0,0,0.45)' } });
  F.circle(x + 34, y + 30, 11, { fill: color });
  F.text(label, x + 58, y + 31, { size: 22, weight: 600, baseline: 'middle' });
  g.restore();
}

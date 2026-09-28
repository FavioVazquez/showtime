/* Picture for the tutorial template: camera, cursor, step titles, step bar and keycaps.
 * The app itself lives in app.js. Everything is a pure function of T. */
'use strict';

var STEPS = ['Create a project', 'Give it a name', 'Render it'];

function camKeys() {
  var F = Film, home = [F.W / 2, F.H / 2 + 10];
  var btn = APP.center(UI.newBtn), modal = APP.center(UI.modal), card = APP.center(UI.newCard);
  return [
    [0, home[0], home[1], 1.0],
    [1.25, home[0], home[1], 1.02, 'inOutSine'],           // slow drift while the viewer orients
    [CUE.click1 - 0.25, btn[0] - 120, btn[1] + 60, 1.75],   // arrive before the click
    [CUE.modal + 0.45, btn[0] - 120, btn[1] + 60, 1.75],
    [CUE.modal + 1.15, modal[0], modal[1] + 10, 1.45],      // follow the dialog
    [CUE.combo + 0.45, modal[0] + 30, modal[1] + 16, 1.56, 'inOutSine'],   // keep pushing in while the name is typed
    [CUE.combo + 1.25, home[0], home[1], 1.0],              // zoom out to show the result
    [CUE.click2 - 0.95, home[0], home[1], 1.0],
    [CUE.click2 - 0.25, card[0], card[1] + 20, 1.9],
    [CUE.renderEnd + 0.6, card[0] - 20, card[1] + 24, 2.02, 'inOutSine'],  // a slow push while it renders
    [CUE.outro + 0.4, home[0], home[1], 1.0],
  ];
}

function cursorKeys() {
  var W = function (x, y) { return [WIN.x + x, WIN.y + BAR + y]; };
  var start = W(860, 620), btn = APP.center(UI.newBtn), aside = W(1120, 470), rb = APP.center(UI.renderBtn), rest = W(1280, 700);
  return [
    [0, start[0], start[1]],
    [CUE.click1, btn[0], btn[1], { click: true }],
    [CUE.modal + 1.2, aside[0], aside[1]],                  // get out of the way of the text field
    [CUE.click2, rb[0], rb[1], { click: true }],
    [CUE.duration - 0.6, rest[0], rest[1]],
  ];
}

function drawTutorial(T, g, F) {
  var st = appState(T);
  var cam = F.camera(T, camKeys());
  var cur = F.cursorPath(T, cursorKeys());

  // --- world: the app, the click ripple and the cursor all move with the camera
  F.withCamera(cam, function () {
    // light behind the window (the ground is never a flat dark void)
    F.glow(WIN.x + WIN.w * 0.3, WIN.y + WIN.h * 0.2, 900, F.pal.accent, 0.22);
    F.glow(WIN.x + WIN.w * 0.85, WIN.y + WIN.h * 0.95, 760, F.pal.accent2, 0.14);
    drawApp(T, st);
    if (cur.click) F.ripple(cur.click.x, cur.click.y, cur.clickAge, { radius: 34, color: F.pal.accent });
    F.cursor(cur.x, cur.y, { press: cur.press, scale: 1.5, color: '#0d0f14' });
  });

  // --- screen space overlays
  var step = T < CUE.step2 ? 0 : T < CUE.step3 ? 1 : 2;
  var t0 = [CUE.step1, CUE.step2, CUE.step3][step], t1 = [CUE.step2, CUE.step3, CUE.outro][step];
  var vis = F.win(T, t0, t1 - 0.05, 0.35, 0.3);
  if (vis > 0) {
    var tw = F.measure(STEPS[step], { size: 40, weight: 750 }) + 150;
    F.box(60, 58, tw, 92, 22, { fill: 'rgba(11,12,16,0.78)', alpha: vis, shadow: { blur: 30, y: 10, color: 'rgba(0,0,0,0.4)' } });
    F.stepTitle(step + 1, STEPS[step], vis, { x: 84, y: 118, size: 40, badgeText: '#ffffff' });   // white digit: >= 4.5:1 on the accent badge
  }
  var cur01 = step + F.seg(T, t0, t1);
  // step bar, top right opposite the step title: readable labels, clear of the app's own toasts at the
  // bottom and of the player's control strip (bottom 8 %)
  F.box(F.W - 900, 58, 840, 92, 22, { fill: 'rgba(11,12,16,0.8)', alpha: 1 - F.seg(T, CUE.outro, CUE.outro + 0.4), shadow: { blur: 30, y: 10, color: 'rgba(0,0,0,0.4)' } });
  F.stepBar(STEPS, cur01, { x: F.W - 870, y: 122, w: 780, size: 28, alpha: 1 - F.seg(T, CUE.outro, CUE.outro + 0.4) });

  // keycap overlay for the shortcut (bottom centre, inside the safe area)
  var kv = F.win(T, CUE.combo - 0.55, CUE.combo + 1.1, 0.15, 0.3);
  if (kv > 0) {
    F.box(F.W - 440, 874, 300, 110, 26, { fill: 'rgba(11,12,16,0.8)', alpha: kv });
    F.keyCombo(['⌘', '↵'], F.W - 290, 929, {
      size: 70, alpha: kv, p: F.seg(T, CUE.combo - 0.55, CUE.combo - 0.25),
      press: F.win(T, CUE.combo - 0.04, CUE.combo + 0.14, 0.04, 0.08),
    });
  }

  // outro line
  var ov = F.seg(T, CUE.outro, CUE.outro + 0.5);
  if (ov > 0) {
    g.save();
    g.globalAlpha = ov * 0.55;
    g.fillStyle = '#07080b';
    g.fillRect(0, 0, F.W, F.H);
    g.restore();
    F.reveal('Three steps. That’s it.', F.W / 2, F.H / 2 + 20, F.seg(T, CUE.outro + 0.1, CUE.outro + 0.9), {
      size: 96, weight: 800, align: 'center', tracking: -0.02,
    });
  }
}

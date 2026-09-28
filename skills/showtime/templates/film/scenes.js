/* Picture for the film template. drawFilm(T, g, F) draws the whole frame for time T.
 * Rules: pure function of T (no Math.random, no clocks, no state kept between frames).
 * Replace the words; keep the structure. Numbers on screen are illustrative: label them. */
'use strict';

var TITLE = 'Builds, minus the wait.';
var PROMISE = 'What changes, in one line.';
var PRODUCT = 'Your Product';
var URL_TEXT = 'yourproduct.dev';

function drawFilm(T, g, F) {
  F.sequence(T, [
    { t0: CUE.title, t1: CUE.metaphor, draw: titleScene },
    { t0: CUE.metaphor, t1: CUE.data, draw: metaphorScene, in: { type: 'wipe', dur: 0.5, dir: 'left' } },
    { t0: CUE.data, t1: CUE.end, draw: dataScene, in: 'cut' },
    { t0: CUE.end, t1: CUE.duration, draw: endScene, in: { type: 'fade', dur: 0.6 } },
  ]);
}

// ------------------------------------------------------------------ 1. title
function titleScene(local, p, T) {
  var F = Film;
  // slow push-in across the whole shot
  var cam = { x: F.W / 2, y: F.H / 2 + 20, zoom: F.lerp(1.0, 1.04, F.seg(T, 0, CUE.metaphor, 'inOutSine')) };
  F.withCamera(cam, function () {
    F.text('A SHORT FILM', F.W / 2, 392, {
      size: 32, weight: 650, tracking: 0.22, align: 'center', color: F.pal.muted, alpha: F.seg(T, 0.05, 0.5),
    });
    var o = { family: 'serif', size: 176, align: 'center' };
    F.reveal(TITLE, F.W / 2, 590, F.seg(T, 0.15, 1.25), Object.assign({ by: 'word' }, o));
    // hand-drawn underline under the last word
    var full = F.measure(TITLE, o), x0 = F.W / 2 - full / 2;
    var wx = x0 + F.measure('Builds, minus the ', o), ww = F.measure('wait', o);
    var pts = [];
    for (var i = 0; i <= 24; i++) {
      var u = i / 24;
      pts.push([wx + ww * u, 628 + Math.sin(u * Math.PI) * 10 + F.noise(u * 6, 4) * 4]);
    }
    F.path(pts, F.seg(T, 1.05, 1.6, 'outCubic'), { color: F.pal.accent, width: 8, smooth: true });
    F.text(PROMISE, F.W / 2, 740, {
      size: 50, weight: 450, align: 'center', color: F.pal.muted, alpha: F.seg(T, 0.9, 1.35),
    });
  });
}

// ------------------------------------------------------------------ 2. metaphor
var LINE_Y = 610, LINE_X0 = 330, LINE_X1 = 1590;

function tangle(q) {
  var F = Film, pts = [], n = 150;
  for (var i = 0; i < n; i++) {
    var u = i / (n - 1);
    var sx = F.lerp(LINE_X0, LINE_X1, u);
    var a = u * Math.PI * 2 * 6.5 + F.noise(u * 3, 2) * 2.5;
    var r = 200 * Math.pow(Math.sin(Math.PI * u), 0.6) * (0.7 + 0.3 * F.noise(u * 4, 5));
    var tx = sx + Math.cos(a) * r * 0.9;
    var ty = LINE_Y + Math.sin(a) * r * 0.75 + F.noise(u * 2.5, 9) * 50 * Math.sin(Math.PI * u);
    var k = F.E.inOutCubic(F.clamp(q * 1.7 - u * 0.7));   // straightens left to right
    pts.push([F.lerp(tx, sx, k), F.lerp(ty, LINE_Y, k)]);
  }
  return pts;
}

function metaphorScene(local, p, T) {
  var F = Film;
  var q = F.seg(T, CUE.untangle, CUE.untangle + 1.3, 'inOutCubic');
  // two short lines: each must stay up long enough to read (about 1 s + 0.04 s per character)
  F.text('Usually:', F.W / 2, 250, {
    family: 'serif', size: 96, align: 'center', alpha: F.win(T, CUE.metaphor + 0.1, CUE.untangle + 0.3, 0.3, 0.25),
  });
  F.text('Ideally:', F.W / 2, 250, {
    family: 'serif', size: 96, align: 'center', color: F.pal.accent, alpha: F.win(T, CUE.untangle + 0.3, CUE.data + 1, 0.3, 0),
  });
  var draw = F.seg(T, CUE.metaphor + 0.1, CUE.metaphor + 1.0, 'inOutSine');
  var pen = F.path(tangle(q), draw, {
    color: F.mixColor(F.pal.ink, F.pal.accent, q), width: F.lerp(5, 9, q), smooth: false, head: 8,
  });
  // end points
  var pop = F.E.snappy(F.seg(T, CUE.metaphor + 0.05, CUE.metaphor + 0.6));
  F.circle(LINE_X0, LINE_Y, 16 * pop, { fill: F.pal.ink });
  var endA = F.seg(T, CUE.metaphor + 0.9, CUE.metaphor + 1.3);
  F.circle(LINE_X1, LINE_Y, 16 * F.E.snappy(endA), { fill: q > 0.95 ? F.pal.accent : F.pal.ink });
  // labels sit under the end points, where the loops are already small
  var labelA = F.seg(T, CUE.metaphor + 1.0, CUE.metaphor + 1.4);
  F.text('Idea', LINE_X0, LINE_Y + 76, { size: 40, weight: 650, align: 'center', color: F.pal.muted, alpha: labelA });
  F.text('Shipped', LINE_X1, LINE_Y + 76, { size: 40, weight: 650, align: 'center', color: F.pal.muted, alpha: labelA });
  if (q >= 1 && pen) F.glow(LINE_X1, LINE_Y, 140, F.pal.accent, 0.25 * F.seg(T, CUE.untangle + 1.3, CUE.untangle + 1.8));
}

// ------------------------------------------------------------------ 3. data
function dataScene(local, p, T) {
  var F = Film, t0 = CUE.data;
  F.reveal('Build time per change', 220, 262, F.seg(T, t0 + 0.05, t0 + 0.8), { size: 88, weight: 800, tracking: -0.025 });
  // the unit and an honest label for sample numbers, right under the claim (never in a corner)
  F.text('minutes per change · illustrative', 224, 336, { size: 34, weight: 500, color: F.pal.muted, alpha: F.seg(T, t0 + 0.5, t0 + 1.0) });
  F.bars([11.2, 2.9], { x: 420, y: 440, w: 640, h: 400 }, F.seg(T, t0 + 0.35, t0 + 1.6), {
    horizontal: true, labels: ['Before', 'After'], colors: [F.rgba(F.pal.muted, 0.55), F.pal.accent],
    decimals: 1, suffix: ' min', labelSize: 42, valueSize: 48, gap: 0.36, radius: 14,
  });
  var cp = F.seg(T, t0 + 1.0, t0 + 2.2, 'outCubic');
  F.counter(74, 1575, 680, cp, {
    prefix: '−', suffix: '%', size: 220, weight: 800, align: 'center', suffixSize: 116,
    color: F.mixColor(F.pal.accent, F.pal.ink, 0.34),   // a deeper accent: >= 4.5:1 on the paper, vignette included
    alpha: F.seg(T, t0 + 0.95, t0 + 1.2),
  });
  F.text('less waiting', 1575, 775, { size: 50, weight: 600, align: 'center', color: F.pal.ink, alpha: F.seg(T, t0 + 1.8, t0 + 2.3) });
}

// ------------------------------------------------------------------ 4. end card
function endScene(local, p, T) {
  var F = Film, t0 = CUE.end;
  F.field(T, { count: 40, seed: 11, color: F.pal.accent, alpha: 0.18, speed: [0, -10], size: 2.4 });
  var cx = F.W / 2, cy = 380;
  var ring = [];
  for (var i = 0; i <= 64; i++) {
    var a = -Math.PI / 2 + (i / 64) * Math.PI * 2;
    ring.push([cx + Math.cos(a) * 62, cy + Math.sin(a) * 62]);
  }
  F.path(ring, F.seg(T, t0 + 0.05, t0 + 0.9, 'inOutCubic'), { color: F.pal.ink, width: 10 });
  // the logo dot pulses on the final musical hit (CUE.button), with a ripple
  var bump = T >= CUE.button ? 0.45 * Math.exp(-(T - CUE.button) / 0.14) : 0;
  F.circle(cx, cy, 26 * F.E.snappy(F.seg(T, t0 + 0.6, t0 + 1.0)) * (1 + bump), { fill: F.pal.accent });
  F.ripple(cx, cy, T - CUE.button, { radius: 150, dur: 0.9, width: 5, alpha: 0.5 });
  F.reveal(PRODUCT, cx, 590, F.seg(T, t0 + 0.4, t0 + 1.2), { size: 140, weight: 800, align: 'center', tracking: -0.02, by: 'char', effect: 'fade' });
  F.text(TITLE, cx, 676, { family: 'serif', italic: true, size: 60, align: 'center', color: F.pal.muted, alpha: F.seg(T, t0 + 1.0, t0 + 1.6) });
  F.pill(URL_TEXT, cx, 800, { size: 42, alpha: F.seg(T, t0 + 1.3, t0 + 1.8), fill: F.pal.ink, color: F.pal.bg, icon: F.pal.accent });
}

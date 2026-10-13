/* xray.js: the X-ray page's runtime. It reads xray.json (from `showtime xray analyze`) and showtime.json "xray",
   lays the page out (the clip, the inside drawn in place on the tracked object and/or in a panel, the counters,
   the sound strip, the end card) and draws the sync marker `showtime xray verify` reads. Your object's drawing
   is mechanism.js (from skills/showtime/library/xray/<object>/), the beats are cue.js: edit those, not this.

   Frames, never seconds: an event's film frame is its `frame` in xray.json (the clip starts at film frame 0); a
   strike PEAKS on that frame and starts 3 frames before it (the sound is the impact). */
(function () {
  'use strict';
  var X = window.XRAY = { mech: null, ready: false };
  X.mechanism = function (m) { X.mech = m; };

  // palettes: dark = the radiograph (cyan lines on night), light = a blueprint on paper (navy lines); red = acting now
  var THEMES = {
    dark: { l: [143, 211, 255], i: [233, 243, 255], bg: [7, 11, 22], h: [255, 74, 61], muted: '#a9bdd6', glow: 8,
            filter: 'grayscale(1) invert(1) brightness(.62) contrast(1.7) sepia(1) hue-rotate(165deg) saturate(2.6)' },
    light: { l: [24, 62, 120], i: [18, 30, 52], bg: [244, 240, 231], h: [214, 40, 57], muted: '#55627a', glow: 0,
             filter: 'grayscale(1) brightness(1.55) contrast(.62) sepia(.25)' }
  };
  function palette(name) {
    var P = THEMES[name] || THEMES.dark, f = function (c) { return function (a) { return 'rgba(' + c.join(',') + ',' + a + ')'; }; };
    var C = { name: THEMES[name] ? name : 'dark', l: f(P.l), i: f(P.i), bg: f(P.bg), h: f(P.h), muted: P.muted, glow: P.glow, filter: P.filter };
    C.line = C.l(1); C.soft = C.l(name === 'light' ? .55 : .5); C.faint = C.l(name === 'light' ? .22 : .2); C.hot = C.h(1); C.ink = C.i(1);
    C.ground = C.bg(1);
    return C;
  }
  var C = palette('dark');
  var RISE = 3, FALL = 7;                     // frames before / after an event's frame

  // ------------------------------------------------------------------ 3x3 maths (row-major arrays of 9)
  function solve(A, b) {
    var n = b.length, M = A.map(function (r, i) { return r.concat([b[i]]); });
    for (var c = 0; c < n; c++) {
      var p = c;
      for (var r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
      var tmp = M[c]; M[c] = M[p]; M[p] = tmp;
      for (r = 0; r < n; r++) {
        if (r === c) continue;
        var f = M[r][c] / M[c][c];
        for (var k = c; k <= n; k++) M[r][k] -= f * M[c][k];
      }
    }
    return M.map(function (r, i) { return r[n] / r[i]; });
  }
  function hom(src, dst) {                     // the homography taking 4 points onto 4 points
    var A = [], b = [];
    for (var i = 0; i < 4; i++) {
      var x = src[i][0], y = src[i][1], u = dst[i][0], v = dst[i][1];
      A.push([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.push(u);
      A.push([0, 0, 0, x, y, 1, -v * x, -v * y]); b.push(v);
    }
    var h = solve(A, b); h.push(1); return h;
  }
  function mul(a, b) {
    var o = [];
    for (var r = 0; r < 3; r++) for (var c = 0; c < 3; c++) o.push(a[r * 3] * b[c] + a[r * 3 + 1] * b[3 + c] + a[r * 3 + 2] * b[6 + c]);
    return o;
  }
  function apply(h, x, y) { var w = h[6] * x + h[7] * y + h[8]; return [(h[0] * x + h[1] * y + h[2]) / w, (h[3] * x + h[4] * y + h[5]) / w]; }
  function affine(sx, sy, tx, ty) { return [sx, 0, tx, 0, sy, ty, 0, 0, 1]; }
  function fit(box, r, pad) {                  // box [x0,y0,x1,y1] into rect {x,y,w,h}, aspect kept, centred
    var bw = box[2] - box[0], bh = box[3] - box[1], s = Math.min((r.w - 2 * pad) / bw, (r.h - 2 * pad) / bh);
    return affine(s, s, r.x + (r.w - bw * s) / 2 - box[0] * s, r.y + (r.h - bh * s) / 2 - box[1] * s);
  }
  function bbox(pts) {
    var xs = pts.map(function (p) { return p[0]; }), ys = pts.map(function (p) { return p[1]; });
    return [Math.min.apply(null, xs), Math.min.apply(null, ys), Math.max.apply(null, xs), Math.max.apply(null, ys)];
  }
  X.math = { hom: hom, mul: mul, apply: apply, fit: fit, bbox: bbox };

  // ------------------------------------------------------------------ loading
  function getJSON(url) { return fetch(url, { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }); }
  var cue = function (k, d) { return (window.CUE && typeof window.CUE[k] === 'number') ? window.CUE[k] : d; };

  function load() {
    var fonts = document.fonts ? Promise.all([
      document.fonts.load('800 60px "Bricolage Grotesque"'), document.fonts.load('500 24px "IBM Plex Mono"'),
      document.fonts.load('600 24px "IBM Plex Mono"')]).catch(function () {}) : Promise.resolve();
    var notes = getJSON('notes.json').catch(function () { return null; });   // optional: `showtime xray notes`
    return Promise.all([getJSON('xray.json'), getJSON('showtime.json'), fonts, notes]).then(function (r) {
      if (!r[0] || !r[0].events) throw new Error('xray.json is missing or has no events: run `showtime xray analyze <clip> --job <job>` and copy <job>/xray/xray.json next to index.html');
      if (!X.mech) throw new Error('no mechanism: mechanism.js must call XRAY.mechanism({...})');
      setup(r[0], (r[1] && r[1].xray) || {}, r[3]);
    });
  }

  // ------------------------------------------------------------------ layout and events
  var S = {};                                  // everything setup() works out
  function setup(doc, cfg, notesDoc) {
    C = palette(cfg.theme || 'dark');
    var info = ST.info(), W = info.width, H = info.height, fps = info.fps || 30;
    var src = doc.source || {}, sw = src.width || 1920, sh = src.height || 1080, sfps = src.fps || fps;
    var m = X.mech, track = doc.track && doc.track.H && doc.track.H.length ? doc.track : null;
    var portrait = H > W * 1.2, inplace = cfg.layout !== 'split' && !!track;
    var clip, panel = null, hud, lay = null;
    if (portrait) {                            // phone: the clip on top, the inside below, all text in the reels safe box
      var ch = W * sh / sw, cw = W;
      if (ch > H * 0.36) { ch = H * 0.36; cw = ch * sw / sh; }
      clip = { x: (W - cw) / 2, y: 0, w: cw, h: ch };
      var top = Math.max(H * 0.115, ch + 28), hudTop = H * 0.75 - 172;
      lay = { brand: top, tag: top + 76, panelTop: top + 150, hud: hudTop };
      panel = { x: 40, y: lay.panelTop, w: W - 80, h: hudTop - 16 - lay.panelTop };
      hud = 'portrait';
    } else if (inplace && cfg.panel) {         // 16:9 see-through with the panel beside it ("xray": {"panel": true})
      var w3 = W * 0.6, h3 = w3 * sh / sw;
      if (h3 > H - 300) { h3 = H - 300; w3 = h3 * sw / sh; }
      clip = { x: 40, y: (H - h3) / 2, w: w3, h: h3 };
      panel = { x: clip.x + w3 + 40, y: 150, w: W - w3 - 120, h: H - 150 - 230 };
      hud = 'side';
    } else if (inplace) {
      var s = Math.max(W / sw, H / sh);
      clip = { x: (W - sw * s) / 2, y: (H - sh * s) / 2, w: sw * s, h: sh * s };
      hud = 'over';
    } else {
      var w2 = W * 0.56, h2 = w2 * sh / sw;
      clip = { x: 0, y: (H - h2) / 2, w: w2, h: h2 };
      panel = { x: w2 + 40, y: 150, w: W - w2 - 80, h: H - 150 - 230 };
      hud = 'side';
    }
    // design space (the mechanism's own coordinates) -> the clip's reference frame -> each frame -> the film
    var place = null;
    if (cfg.place && m.anchors) {
      var names = Object.keys(m.anchors).filter(function (k) { return cfg.place[k]; });
      if (names.length >= 4) {
        names = names.slice(0, 4);
        place = hom(names.map(function (k) { return m.anchors[k]; }), names.map(function (k) { return cfg.place[k]; }));
      }
    }
    if (!place && track && track.region) place = fitInto(m.box, bbox(track.region));
    var toFilm = affine(clip.w / sw, clip.h / sh, clip.x, clip.y);
    var off = Math.round(Number(cfg.offset_frames) || 0);
    if (off) ['clip', 'clipx'].forEach(function (id) {       // the clip starts at film frame `off`: its clock runs behind the film's
      el(id).setAttribute('data-offset', String(-off / fps));
    });
    // events: film frames, kinds (skip / return / ... from showtime.json), characters read off the clip
    var kinds = {}, skip = cfg.skip || [];
    skip.forEach(function (i) { kinds[i] = 'skip'; });
    Object.keys(cfg.kinds || {}).forEach(function (i) { kinds[i] = cfg.kinds[i]; });
    var text = cfg.text || '', ti = 0;
    var ev = doc.events.map(function (e, i) {
      // the film frame: the clip's own frame when the film runs at the clip's rate, else floor(t * film fps)
      // + "xray".offset_frames (a trimmed or shifted clip), the same arithmetic as `showtime xray verify`
      var fr = (Math.abs(sfps - fps) > 0.01 ? Math.floor(e.t * fps + 1e-9) : e.frame) + off;
      var kind = kinds[i] || 'event', o = { i: i, frame: fr, t: e.t, strength: e.strength, band: e.band, kind: kind, ch: null };
      if (kind === 'event' && ti < text.length) o.ch = text[ti++];
      return o;
    });
    S = { off: off, W: W, H: H, fps: fps, sfps: sfps, sw: sw, sh: sh, doc: doc, cfg: cfg, m: m, track: track, inplace: inplace,
          clip: clip, panel: panel, hud: hud, lay: lay, place: place, toFilm: toFilm, ev: ev, text: text, portrait: portrait,
          panelMap: panel ? fit(m.box, panel, 24) : null, dur: info.duration, notes: [] };
    attachNotes(notesDoc);
    build();
    X.ready = true;
  }
  // notes.json (pitches, from `showtime xray notes`): each note joins the event within 3 frames of it, so a
  // mechanism can say WHICH tooth, string or key, from the sound itself
  function attachNotes(nd) {
    S.ev.forEach(function (e) { e.notes = []; });
    S.music = nd || null;                      // the whole notes.json: tempo map, quantized, voices, guitar, drums
    if (!nd) return;
    var src = (nd.notes && nd.notes.length ? nd.notes : (nd.drums || []));
    S.notes = src.map(function (n, j) {
      return { i: n.i != null ? n.i : j, pitch: n.pitch, name: n.name || n.piece, piece: n.piece, t: n.t,
               frame: Math.floor(n.t * S.fps + 1e-9) + S.off, end: n.end, velocity: n.velocity, confidence: n.confidence, hz: n.hz };
    });
    S.notes.forEach(function (n) {
      var best = null, bd = 4;
      S.ev.forEach(function (e) { var d = Math.abs(e.frame - n.frame); if (d < bd) { bd = d; best = e; } });
      if (best) best.notes.push(n);
    });
  }
  function fitInto(box, b) {                   // the design box stretched onto the region's bounding box
    return affine((b[2] - b[0]) / (box[2] - box[0]), (b[3] - b[1]) / (box[3] - box[1]),
                  b[0] - box[0] * (b[2] - b[0]) / (box[2] - box[0]), b[1] - box[1] * (b[3] - b[1]) / (box[3] - box[1]));
  }

  // ------------------------------------------------------------------ the page
  function px(v) { return v.toFixed(1) + 'px'; }
  function el(id) { return document.getElementById(id); }
  function build() {
    var c = S.clip;
    ['clip', 'clipx'].forEach(function (id) {
      var v = el(id); v.style.left = px(c.x); v.style.top = px(c.y); v.style.width = px(c.w); v.style.height = px(c.h);
    });
    el('scan').hidden = !S.inplace;
    var st = el('stage'); st.className = 'stage ' + S.hud + (S.inplace ? ' inplace' : '') + ' ' + C.name;
    [['--line', C.line], ['--ink', C.ink], ['--muted', C.muted], ['--hot', C.hot], ['--ground', C.ground],
     ['--card', C.bg(.84)], ['--edge', C.l(.35)], ['--tagbg', C.bg(.74)]].forEach(function (v) { st.style.setProperty(v[0], v[1]); });
    el('clipx').style.filter = C.filter;
    var cv = el('cv'); cv.width = S.W; cv.height = S.H;
    el('brand-tag').textContent = S.cfg.tag || (S.inplace ? 'your clip · seen through' : 'your clip · the inside, in sync');
    el('noun').textContent = (S.m.noun || 'events') + (S.portrait ? '' : ' heard');
    var tc = el('textcard');
    if (S.text) el('textlabel').textContent = S.m.textLabel || 'read from the clip'; else tc.hidden = true;
    var n = S.ev.filter(function (e) { return e.kind === 'event'; }).length;
    el('end-h').innerHTML = S.cfg.headline || (S.m.headline ? S.m.headline(n) : '<em>' + n + '</em> ' + (S.m.noun || 'events') + ',<br>seen from inside.');
    el('end-measured').textContent = S.cfg.measured || (S.m.measured ? S.m.measured(n, !!S.text, S.notes.length > 0) : 'Each event lit up on the frame its sound was heard.');
    el('receipt').textContent = S.cfg.receipt || (n + ' ' + (S.m.noun || 'events') + ' measured from the clip’s sound');
    el('end-drawn').textContent = [S.cfg.drawn || S.m.drawn || 'The inside is drawn: a generic mechanism of this kind of object.',
                                   S.cfg.credit || ''].join(' ').trim();
    if (S.lay) {
      el('brand').style.top = px(S.lay.brand); el('brand-tag').style.top = px(S.lay.tag); el('hud').style.top = px(S.lay.hud);
    }
    var mk = el('xmark'); mk.style.left = px(S.W - 10); mk.style.top = px(S.H - 10);
  }

  // the track's frame for a film frame; "xray".track_until (seconds of the clip) holds the last good one, for a clip
  // whose end the tracker loses (the object turned over, a hand covering it)
  function trackFrame(f) {
    var sf = Math.round((f - S.off) * S.sfps / S.fps), last = S.track.H.length - 1;
    if (typeof S.cfg.track_until === 'number') last = Math.min(last, Math.floor(S.cfg.track_until * S.sfps));
    return Math.max(0, Math.min(last, sf));
  }

  // ------------------------------------------------------------------ drawing kit handed to the mechanism
  function kit(g, view, f, t, alpha) {
    var map;
    if (view === 'panel') map = S.panelMap;
    else {
      map = mul(S.toFilm, mul(S.track.H[trackFrame(f)], S.place));
    }
    var pr = function (x, y) { return apply(map, x, y); };
    var scale = Math.sqrt(Math.abs(map[0] * map[4] - map[1] * map[3]));
    var K = { g: g, view: view, f: f, t: t, alpha: alpha, C: C, ease: ST.ease, pr: pr, scale: scale, ev: S.ev, text: S.text, notes: S.notes, music: S.music, cfg: S.cfg, fps: S.fps, panel: S.panel,
              labels: view === 'panel' || !S.panel };
    K.env = function (i) {                     // 0..1: the motion of event i, 1 exactly on its frame
      var d = f - S.ev[i].frame;
      if (d < -RISE || d > FALL) return 0;
      if (d <= 0) { var a = (d + RISE) / RISE; return a * a; }
      return 1 - ST.ease.inOutSine(d / FALL);
    };
    K.since = function (i) { return f - S.ev[i].frame; };
    K.beat = function (tt) {                   // the smooth tempo map (notes.json tempo.map): beat at time tt, never a jump
      var m = S.music && S.music.tempo && S.music.tempo.map;
      if (!m || m.length < 2) return tt * ((S.music && S.music.tempo && S.music.tempo.bpm) || 120) / 60;
      if (tt <= m[0][0]) return m[0][1] + (tt - m[0][0]) * (m[1][1] - m[0][1]) / (m[1][0] - m[0][0]);
      for (var q = 1; q < m.length; q++) if (tt <= m[q][0]) return m[q - 1][1] + (tt - m[q - 1][0]) * (m[q][1] - m[q - 1][1]) / (m[q][0] - m[q - 1][0]);
      var a = m[m.length - 2], b = m[m.length - 1]; return b[1] + (tt - b[0]) * (b[1] - a[1]) / (b[0] - a[0]);
    };
    K.count = function (kind) { var n = 0; S.ev.forEach(function (e) { if (e.frame <= f && e.kind === (kind || 'event')) n++; }); return n; };
    K.cur = -1; K.s = 0;
    S.ev.forEach(function (e, i) { if (e.kind === 'skip') return; var s = K.env(i); if (s > K.s) { K.s = s; K.cur = i; } });
    K.hot = K.s > 0.05; K.ch = K.cur >= 0 ? S.ev[K.cur].ch : null; K.kind = K.cur >= 0 ? S.ev[K.cur].kind : null;
    K.n = K.count('event');
    var lw = function (w) { return Math.max(1, w * (view === 'panel' ? Math.min(1.6, scale) : Math.min(1.4, scale * 1.2))); };
    K.lw = lw;
    K.path = function (pts, close) { g.beginPath(); pts.forEach(function (p, i) { var q = pr(p[0], p[1]); if (i) g.lineTo(q[0], q[1]); else g.moveTo(q[0], q[1]); }); if (close) g.closePath(); };
    K.seg = function (a, b, col, w) { g.strokeStyle = col; g.lineWidth = lw(w); K.path([a, b]); g.stroke(); };
    K.poly = function (pts, col, w, fill) { K.path(pts, true); if (fill) { g.fillStyle = fill; g.fill(); } if (col) { g.strokeStyle = col; g.lineWidth = lw(w); g.stroke(); } };
    K.ell = function (cx, cy, rx, ry, col, w, rot, teeth) {
      var pts = [];
      for (var k = 0; k <= 72; k++) { var a = k * Math.PI / 36, r = teeth && k % 2 ? 0.8 : 1; pts.push([cx + Math.cos(a + (rot || 0)) * rx * r, cy + Math.sin(a + (rot || 0)) * ry * r]); }
      g.strokeStyle = col; g.lineWidth = lw(w); K.path(pts, true); g.stroke();
    };
    K.dot = function (p, r, col) { var q = pr(p[0], p[1]); g.fillStyle = col; g.beginPath(); g.arc(q[0], q[1], r, 0, Math.PI * 2); g.fill(); };
    K.label = function (text, at, dx, dy, on) {
      if (!K.labels) return;
      var p = pr(at[0], at[1]), r = view === 'panel' ? (S.portrait ? { x: S.W * 0.06, y: S.panel.y, w: S.W * 0.79, h: S.panel.h } : S.panel) : { x: 40, y: 170, w: S.W - 80, h: S.H - 400 };
      if (p[0] < r.x - 20 || p[0] > r.x + r.w + 20 || p[1] < r.y - 20 || p[1] > r.y + r.h + 20) return;
      var size = S.portrait ? 34 : 28;
      g.save(); g.font = '600 ' + size + 'px "IBM Plex Mono"'; g.shadowBlur = 0;
      var label = String(text).toUpperCase(), w = g.measureText(label).width + 22, hgt = size + 16;
      var x = Math.max(r.x + (dx < 0 ? w : 0), Math.min(r.x + r.w - (dx < 0 ? 0 : w), p[0] + dx));
      var y = Math.max(r.y + hgt / 2, Math.min(r.y + r.h - hgt / 2, p[1] + dy));
      g.globalAlpha = alpha * (K.labelAlpha == null ? 1 : K.labelAlpha);
      g.strokeStyle = on ? C.hot : C.i(.7); g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(p[0], p[1]); g.lineTo(x, y); g.stroke();
      g.fillStyle = C.bg(.86); g.fillRect(dx < 0 ? x - w : x, y - hgt / 2, w, hgt);
      g.fillStyle = on ? C.hot : C.ink; g.textBaseline = 'middle'; g.textAlign = dx < 0 ? 'right' : 'left';
      g.fillText(label, dx < 0 ? x - 11 : x + 11, y + 1);
      g.restore();
    };
    return K;
  }

  // ------------------------------------------------------------------ per frame
  function drawView(g, view, f, t, alpha, clipRect) {
    var K = kit(g, view, f, t, alpha);
    K.labelAlpha = ST.progress(t, cue('labels', 1.4), cue('labels', 1.4) + 0.6, ST.ease.inOutCubic);
    g.save();
    if (clipRect) { g.beginPath(); g.rect(clipRect.x, clipRect.y, clipRect.w, clipRect.h); g.clip(); }
    g.globalAlpha = alpha; g.lineCap = 'round'; g.lineJoin = 'round';
    g.shadowColor = C.l(.8); g.shadowBlur = C.glow;
    S.m.draw(K);
    g.restore();
  }

  function strip(g, f, t, alpha) {
    var portrait = S.hud === 'portrait', x0, w, y0, h = portrait ? 150 : 50;
    if (portrait) { x0 = 64; w = S.W * 0.79; y0 = S.H * 0.75 + 70; }
    else if (S.hud === 'side') { x0 = S.panel.x; w = S.panel.w; y0 = S.H - 100; }
    else { x0 = S.W - 900; w = 852; y0 = S.H - 90; }
    var dur = (S.doc.source && S.doc.source.duration) || S.dur;
    g.save(); g.globalAlpha = alpha;
    g.fillStyle = C.bg(.8); g.fillRect(x0 - 16, y0 - 38, w + 32, h + 54);
    S.ev.forEach(function (e) {
      var x = x0 + (e.frame / S.fps) / dur * w, hh = Math.max(6, (0.35 + 0.65 * (e.strength || 0.5)) * h);
      var on = e.frame <= f, col = e.kind === 'skip' ? (on ? C.i(.55) : C.i(.2)) : (on ? C.hot : C.h(.32));
      g.fillStyle = col; g.fillRect(x - 2, y0 + h / 2 - hh / 2, 4, hh);
    });
    // now: a small caret over the ticks (no axis line, no full-height playhead: it must not read as a player's bar)
    var cx = x0 + Math.min(1, (f / S.fps) / dur) * w;
    g.fillStyle = C.ink; g.beginPath(); g.moveTo(cx - 9, y0 - 8); g.lineTo(cx + 9, y0 - 8); g.lineTo(cx, y0 + 4); g.closePath(); g.fill();
    g.font = '500 ' + (portrait ? 24 : 18) + 'px "IBM Plex Mono"'; g.fillStyle = C.muted; g.textBaseline = 'bottom'; g.textAlign = 'left';
    g.fillText(('the clip’s sound · red = ' + (S.m.one || 'an event')).toUpperCase(), x0, y0 - 12);
    g.restore();
  }

  function frame(t, fr) {
    if (!X.ready) return;
    var f = typeof fr === 'number' ? fr : Math.round(t * S.fps);
    var g = el('cv').getContext('2d');
    g.clearRect(0, 0, S.W, S.H);
    var a = cue('scan', 0.3), b = cue('scan_end', 1.3), p = ST.progress(t, a, b, ST.ease.inOutCubic);
    var show = ST.progress(t, a + 0.2, b, ST.ease.inOutCubic);
    // in place: the radiograph inside the object's outline, revealed by a scan line
    if (S.inplace) {
      var hf = mul(S.toFilm, S.track.H[trackFrame(f)]);
      // the see-through window: "xray".window (reference-frame pixels), else the tracked region
      var poly = (S.cfg.window || S.track.region || []).map(function (q) { var v = apply(hf, q[0], q[1]); return px(v[0]) + ' ' + px(v[1]); });
      el('xbody').style.clipPath = poly.length > 2 ? 'polygon(' + poly.join(', ') + ')' : 'none';
      var sy = S.clip.y + S.clip.h * p;
      el('scan').style.clipPath = 'inset(0 0 ' + px(Math.max(0, S.H - sy)) + ' 0)';
      // past "xray".track_until the see-through fades out instead of sliding off the object
      var hold = typeof S.cfg.track_until === 'number' ? 1 - ST.progress(f / S.fps, S.cfg.track_until, S.cfg.track_until + 0.3, ST.ease.inOutCubic) : 1;
      el('scan').style.opacity = hold.toFixed(3);
      drawView(g, 'inplace', f, t, show * hold, { x: 0, y: 0, w: S.W, h: Math.max(0, sy) });
      if (p > 0 && p < 1) scanline(g, S.clip.x, S.clip.w, sy);
    }
    if (S.panel) {
      var P = S.panel, py = P.y + P.h * p;
      g.save(); g.globalAlpha = ST.progress(t, a, a + 0.3);
      g.strokeStyle = C.l(.25); g.lineWidth = 1.5; g.strokeRect(P.x, P.y, P.w, P.h);
      g.restore();
      drawView(g, 'panel', f, t, show, { x: P.x, y: P.y, w: P.w, h: py - P.y });
      if (p > 0 && p < 1) scanline(g, P.x, P.w, py);
    }
    strip(g, f, t, ST.progress(t, a + 0.4, b + 0.4, ST.ease.inOutCubic));
    var K = kit(g, S.panel ? 'panel' : 'inplace', f, t, 1);
    el('nk').textContent = K.n;
    if (S.m.noun1) el('noun').textContent = (K.n === 1 ? S.m.noun1 : S.m.noun) + (S.portrait ? '' : ' heard');
    if (S.text) {
      var typed = S.ev.filter(function (e) { return e.kind === 'event' && e.ch != null && e.frame <= f; });
      var s = typed.map(function (e) { return e.ch; }).join(''), last = typed.length && f - typed[typed.length - 1].frame < 12;
      var pp = el('pp'); pp.textContent = '';
      if (!s) pp.innerHTML = '&nbsp;';
      else { pp.appendChild(document.createTextNode(last ? s.slice(0, -1) : s)); if (last) { var i = document.createElement('i'); i.textContent = s.slice(-1); pp.appendChild(i); } }
    }
    el('hud').style.opacity = ST.progress(t, a + 0.4, b + 0.4, ST.ease.inOutCubic);
    var e0 = cue('endcard', S.dur - 3);
    el('end').style.opacity = ST.progress(t, e0, e0 + 0.6, ST.ease.inOutCubic);   // eased: no dead stop
    // the sync marker: white exactly on an event's film frame, black otherwise (showtime xray verify reads it)
    var on = S.ev.some(function (e) { return e.frame === f && e.kind !== 'skip'; });
    el('xmark').style.background = on ? '#fff' : '#000';
  }
  function scanline(g, x, w, y) {
    var gr = g.createLinearGradient(0, y - 40, 0, y + 3);
    gr.addColorStop(0, C.l(0)); gr.addColorStop(1, C.l(.9));
    g.fillStyle = gr; g.fillRect(x, y - 40, w, 43);
  }

  // the live page (`showtime export html <project> --interactive`): the same events set up again with another look,
  // {theme: 'light' | 'dark', layout: 'through' | 'split'}; the caller seeks to draw the frame
  X.restyle = function (over) {
    if (!X.ready) return false;
    setup(S.doc, Object.assign({}, S.cfg, over || {}), S.music);
    return true;
  };

  ST.waitFor(load(), 'xray.json');
  ST.onSeek(function (t, fr) { frame(t, fr); });
})();

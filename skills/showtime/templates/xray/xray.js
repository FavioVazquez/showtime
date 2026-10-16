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

  // 9:16: the sound strip (tick height; the plate's room over the ticks for the caret; the whole plate's height), the
  // HUD's height (index.html .portrait.reels .card) and the gaps; its labels are S.lpx (the phone floor, 2.2% of the
  // height, and a pixel: 44 px at 1920)
  var PSTRIP = { h: 56, pad: 22 }, PHUD = 136, PGAP = 12;
  // the reels safe box as fractions of the frame (check's: x 64-916, y 220-1440 at 1080x1920)
  var BOX = { x: 64 / 1080, r: 916 / 1080, y: 220 / 1920, b: 1440 / 1920 };
  PSTRIP.block = PSTRIP.pad + PSTRIP.h + 16;

  // palettes: dark = the radiograph (cyan lines on night), light = a blueprint on paper (navy lines); red = acting now
  // (hotink: the red for text, 4.5:1 on the cards and the end card)
  var THEMES = {
    dark: { l: [143, 211, 255], i: [233, 243, 255], bg: [7, 11, 22], h: [255, 74, 61], hotink: '#ff7468', muted: '#a9bdd6', glow: 8,
            filter: 'grayscale(1) invert(1) brightness(.62) contrast(1.7) sepia(1) hue-rotate(165deg) saturate(2.6)' },
    light: { l: [24, 62, 120], i: [18, 30, 52], bg: [244, 240, 231], h: [214, 40, 57], hotink: '#a81b2b', muted: '#465267', glow: 0,
             filter: 'grayscale(1) brightness(1.55) contrast(.62) sepia(.25)' }
  };
  function palette(name) {
    var P = THEMES[name] || THEMES.dark, f = function (c) { return function (a) { return 'rgba(' + c.join(',') + ',' + a + ')'; }; };
    var C = { name: THEMES[name] ? name : 'dark', l: f(P.l), i: f(P.i), bg: f(P.bg), h: f(P.h), hotink: P.hotink, muted: P.muted, glow: P.glow, filter: P.filter };
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
    var bw = box[2] - box[0], bh = box[3] - box[1], s = Math.max(1e-3, Math.min((r.w - 2 * pad) / bw, (r.h - 2 * pad) / bh));
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
    // reels: a frame at least 1.6 times as tall as wide (9:16) gets the reels box's layout; 4:5 keeps the portrait one
    var portrait = H > W * 1.2, reels = H >= W * 1.6, inplace = cfg.layout !== 'split' && !!track;
    var clip, panel = null, hud, lay = null;
    if (portrait) {                            // phone: the clip on top, the inside below, all text in the reels safe box
      var ch = W * sh / sw, cw = W;
      if (ch > H * 0.36) { ch = H * 0.36; cw = ch * sw / sh; }
      clip = { x: (W - cw) / 2, y: 0, w: cw, h: ch };
      var top = Math.max(H * 0.115, ch + 28);
      if (reels) {
        // the sound strip sits above the HUD, inside the safe box too: its plate ends PGAP px over the HUD (see strip());
        // the panel (its frame too) ends at the safe box's right edge: right of it the platform's buttons cover the frame.
        // A hand-set size too short for this layout gets a thin panel, never a negative (mirrored) one
        var hudTop = H * 0.75 - PHUD, stripTop = hudTop - PGAP - PSTRIP.block;
        lay = { brand: top, tag: top + 76, panelTop: top + 150, hud: hudTop, strip: stripTop };
        panel = { x: 40 * W / 1080, y: lay.panelTop, w: BOX.r * W - 40 * W / 1080, h: Math.max(1, stripTop - PGAP - lay.panelTop) };
      } else {
        lay = { brand: top, tag: top + 76, panelTop: top + 150, hud: H * 0.75 - 172 };
        panel = { x: 40, y: lay.panelTop, w: W - 80, h: lay.hud - 16 - lay.panelTop };
      }
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
    // 9:16: a first fit; reelsLayout() then makes room for the part labels' columns and the captions
    var pm = panel ? fit(m.box, panel, reels ? 12 : 24) : null;
    if (pm && reels) pm[2] += BOX.r * W - 8 * W / 1080 - (m.box[2] * pm[0] + pm[2]);
    S = { off: off, W: W, H: H, fps: fps, sfps: sfps, sw: sw, sh: sh, doc: doc, cfg: cfg, m: m, track: track, inplace: inplace,
          clip: clip, panel: panel, hud: hud, lay: lay, place: place, toFilm: toFilm, ev: ev, text: text, portrait: portrait, reels: reels,
          panelMap: pm, dur: info.duration, notes: [], lpx: Math.ceil(H * 0.022) + 1 };
    attachNotes(notesDoc);
    if (reels) reelsLayout();
    build();
    X.ready = true;
  }
  // the recording's clock: the clip starts at film frame "xray".offset_frames, so a time of the recording (xray.json,
  // notes.json and its tempo map, track_until) sits at film frame floor(t * fps) + off, and film frame f at (f - off) / fps
  function recTime(f) { return (f - S.off) / S.fps; }
  function filmFrame(t) { return Math.floor(t * S.fps + 1e-9) + S.off; }
  // notes.json (pitches, from `showtime xray notes`): each note joins the event within 3 frames of it, so a
  // mechanism can say WHICH tooth, string or key, from the sound itself
  function attachNotes(nd) {
    S.ev.forEach(function (e) { e.notes = []; });
    S.music = nd || null;                      // the whole notes.json: tempo map, quantized, voices, guitar, drums
    if (!nd) return;
    var src = (nd.notes && nd.notes.length ? nd.notes : (nd.drums || []));
    S.notes = src.map(function (n, j) {
      return { i: n.i != null ? n.i : j, pitch: n.pitch, name: n.name || n.piece, piece: n.piece, t: n.t,
               frame: filmFrame(n.t), end: n.end, velocity: n.velocity, confidence: n.confidence, hz: n.hz };
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
    var st = el('stage'); st.className = 'stage ' + S.hud + (S.reels ? ' reels' : '') + (S.inplace ? ' inplace' : '') + ' ' + C.name;
    [['--line', C.line], ['--ink', C.ink], ['--muted', C.muted], ['--hot', C.hot], ['--hotink', C.hotink], ['--ground', C.ground],
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
              labels: view === 'panel' || !S.panel,
              // the recording's clock (notes.json times and its tempo map are seconds of the recording, not the film):
              // rt is this frame's time on it, frameAt(t) the film frame of a recording time t
              rt: recTime(f), frameAt: filmFrame, off: S.off };
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
    // 9:16 panel: heavier lines, so the drawing outweighs its 44 px labels
    var lw = function (w) { return view === 'panel' && S.reels ? Math.max(1.5, w * scale * 1.6) : Math.max(1, w * (view === 'panel' ? Math.min(1.6, scale) : Math.min(1.4, scale * 1.2))); };
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
    // 9:16 panel: the labels sit in one column, each in the row the frame's dry run gave it (labelSlots), and each is
    // drawn when the mechanism calls it, like at 16:9 (the live page reads a label's plate and dims it on that call)
    var col = view === 'panel' && S.reels;
    K.reels = col;                             // the 9:16 panel: labels in a column beside the drawing (keep names short)
    // a mechanism's caption (its key, tempo, bar): in the 9:16 panel it goes to the caption row over the drawing, at
    // the label size (the mechanism draws its own text when this is null, as at 16:9)
    K.caption = col ? function (text, side, ink) {
      if (K.collect) { K.caps.push({ s: String(text), side: side }); return; }
      var px = S.lpx, right = side === 'right';
      g.save(); g.setTransform(1, 0, 0, 1, 0, 0); g.shadowBlur = 0; g.globalAlpha = alpha * (K.labelAlpha == null ? 1 : K.labelAlpha);
      g.font = '600 ' + px + 'px "IBM Plex Mono"'; g.fillStyle = ink; g.textBaseline = 'middle'; g.textAlign = right ? 'right' : 'left';
      g.fillText(String(text), right ? BOX.r * S.W : BOX.x * S.W, S.panel.y + (S.capRow[right ? 'right' : 'left'] + 0.5) * (px + 12) + 1);
      g.restore();
    } : null;
    // opts.keepCase: the label as written (guitar strings: e and E), else in capitals
    K.label = function (text, at, dx, dy, on, opts) {
      if (!K.labels) return;
      var p = pr(at[0], at[1]), r = view === 'panel' ? (S.reels ? { x: BOX.x * S.W, y: S.panel.y, w: (BOX.r - BOX.x) * S.W, h: S.panel.h } : S.portrait ? { x: S.W * 0.06, y: S.panel.y, w: S.W * 0.79, h: S.panel.h } : S.panel) : { x: 40, y: 170, w: S.W - 80, h: S.H - 400 };
      if (p[0] < r.x - 20 || p[0] > r.x + r.w + 20 || p[1] < r.y - 20 || p[1] > r.y + r.h + 20) return;
      if (col) {
        var name = opts && opts.keepCase ? String(text) : String(text).toUpperCase(), key = name + '@' + Math.round(p[0]) + ',' + Math.round(p[1]);
        if (K.collect) K.collect.push({ label: name, p: p, at: at, key: key });
        else if (K.slots && K.slots[key]) colLabel(K.slots[key], name, p, on);
        return;
      }
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
    // a label in its column: its leader (grey, so the only red lines are the mechanism's own) runs from the label to
    // the column's edge, then to its part; the part acting now gets a red dot and its label turns red and bold (the
    // mono font keeps one width in both weights, so a label never shifts when it turns red); at rest, the muted ink.
    // A right column's plates end at the safe box's right edge; a two-line label is one plate
    var colLabel = function (q, name, p, on) {
      var px = S.lpx, x = q.side === 'right' ? BOX.r * S.W - q.w : BOX.x * S.W, edge = q.side === 'right' ? x : x + q.w;
      g.save(); g.shadowBlur = 0; g.globalAlpha = alpha * (K.labelAlpha == null ? 1 : K.labelAlpha);
      g.strokeStyle = C.i(on ? .6 : .45); g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(edge, q.y); g.lineTo(q.ex, q.y); g.lineTo(p[0], p[1]); g.stroke();
      if (on) { g.fillStyle = C.hot; g.beginPath(); g.arc(p[0], p[1], 5, 0, Math.PI * 2); g.fill(); }
      g.fillStyle = C.bg(.86); g.fillRect(x, q.y - q.h / 2, q.w, q.h);
      g.font = (on ? '600' : '500') + ' ' + px + 'px "IBM Plex Mono"'; g.fillStyle = on ? C.hot : C.muted;
      g.textBaseline = 'middle'; g.textAlign = 'left';
      q.lines.forEach(function (l, i) { g.fillText(l, x + 11, q.y + 1 + (i - (q.lines.length - 1) / 2) * (px + 2)); });
      g.restore();
    };
    return K;
  }

  // 9:16 panel: a dry run of the mechanism's drawing on a context that draws nothing collects the labels and captions
  // it calls (only measureText is real)
  var dry = null;
  function dryContext() {
    if (dry) return dry;
    var c = document.createElement('canvas').getContext('2d'), st = {}, none = function () { return stub; };
    var stub = new Proxy(function () {}, { get: function () { return none; }, apply: function () { return stub; } });
    dry = new Proxy(c, {
      get: function (o, k) { if (k === 'measureText') return o.measureText.bind(o); if (k in st) return st[k]; return typeof o[k] === 'function' ? none : o[k]; },
      set: function (o, k, v) { st[k] = v; if (k === 'font') o.font = v; return true; },
      deleteProperty: function (o, k) { delete st[k]; return true; }
    });
    return dry;
  }
  function dryRun(f) {
    var K = kit(dryContext(), 'panel', f, f / S.fps, 1), n = {};
    K.collect = []; K.caps = [];
    S.m.draw(K);
    // a label's id: its name and which call of that name it is in the frame (drums names two parts TOM)
    K.collect.forEach(function (q) { n[q.label] = (n[q.label] || 0) + 1; q.id = q.label + '#' + n[q.label]; });
    return K;
  }
  // a label's plate: its lines plus `pad` (16 px; 8 or 4 when a column would not hold its labels otherwise, with the
  // gap between two plates 8, 4 or 2: the text stays 44 px)
  var PADS = [[16, 8], [8, 4], [4, 2]];
  function rowH(n, pad) { return S.lpx + pad + (n - 1) * (S.lpx + 2); }
  // a label's lines: one, or two when it is wider than the layout's limit (split at a space); null when it can't fit
  function wrapLabel(name, lim) {
    var g = dryContext(), words = name.split(' '), lines = [], cur = '';
    g.font = '500 ' + S.lpx + 'px "IBM Plex Mono"';
    words.forEach(function (w) { var t = cur ? cur + ' ' + w : w; if (cur && g.measureText(t).width > lim) { lines.push(cur); cur = w; } else cur = t; });
    lines.push(cur);
    return lines.length <= 2 && lines.every(function (l) { return g.measureText(l).width <= lim; }) ? lines : null;
  }
  function labInfo(name, side, lim, pad) {
    var g = dryContext(), lines = wrapLabel(name, lim) || [name];
    g.font = '500 ' + S.lpx + 'px "IBM Plex Mono"';
    var w = Math.max.apply(null, lines.map(function (l) { return g.measureText(l).width; })) + 22;
    return { lines: lines, w: w, h: rowH(lines.length, pad), side: side };
  }

  // 9:16 panel, once at setup: the part labels' columns and the captions' rows, from dry runs of sampled frames (every
  // event's frame and 4 frames after it, and every half second), so the drawing never moves between frames. Labels go
  // in one column at the reels box's left edge, or in two (left and right, by which half of the drawing their part is
  // in); a long label wraps to two lines; captions get a row at the panel's top, and a column starts under the rows
  // whose captions reach over it. Of the layouts whose columns hold every sampled frame's labels, the one with the
  // largest drawing wins (then fewer columns, then fewer wrapped labels); no column covers the drawing's box
  function reelsLayout() {
    var P = S.panel, px = S.lpx, x0 = BOX.x * S.W, xr = BOX.r * S.W, box = S.m.box, bw = box[2] - box[0], bh = box[3] - box[1];
    var frames = [0], per = [], at = {}, caps = { left: 0, right: 0 }, g = dryContext(), step = Math.max(1, Math.round(S.fps / 2));
    S.ev.forEach(function (e) { frames.push(e.frame, e.frame + 4); });
    for (var f = step; f < Math.round(S.dur * S.fps); f += step) frames.push(f);
    S.capRow = { left: 0, right: 0 };
    frames.forEach(function (f) {
      var K = dryRun(f);
      g.font = '600 ' + px + 'px "IBM Plex Mono"';
      K.caps.forEach(function (c) { caps[c.side] = Math.max(caps[c.side], g.measureText(c.s).width); });
      per.push(K.collect.map(function (q) { (at[q.id] = at[q.id] || []).push(q.at[0]); return q.id; }));
    });
    // captions: left and right on one row when both fit, else the right one on a second row
    var both = caps.left && caps.right, two = both && caps.left + caps.right + 24 > xr - x0;
    S.capRow = { left: 0, right: two ? 1 : 0 };
    var rows = [];                               // per caption row, the x span its captions take
    if (caps.left) rows[0] = [[x0, x0 + caps.left]];
    if (caps.right) (rows[S.capRow.right] = rows[S.capRow.right] || []).push([xr - caps.right, xr]);
    var crow = px + 12, band = rows.length * crow;
    var colTop = function (a, b) {               // a column spanning x a..b starts under the last caption row over it
      var top = P.y;
      rows.forEach(function (r, i) { if (r && r.some(function (sp) { return sp[0] < b + 10 && sp[1] > a - 10; })) top = P.y + (i + 1) * crow; });
      return top;
    };
    var names = Object.keys(at).sort(), cx = (box[0] + box[2]) / 2, bot = P.y + P.h, nm = function (id) { return id.slice(0, id.lastIndexOf('#')); };
    var mid = {}; names.forEach(function (n) { mid[n] = at[n].reduce(function (a, b) { return a + b; }, 0) / at[n].length; });
    var lims = [Infinity];                       // wrap limits worth trying: every run of words' width
    g.font = '500 ' + px + 'px "IBM Plex Mono"';
    names.forEach(function (n) { var w = nm(n).split(' '); for (var i = 0; i < w.length; i++) for (var j = i + 1; j <= w.length; j++) lims.push(Math.ceil(g.measureText(w.slice(i, j).join(' ')).width)); });
    lims = lims.filter(function (v, i) { return lims.indexOf(v) === i; }).sort(function (a, b) { return b - a; });
    var best = null;
    [1, 2].forEach(function (cols) {
      lims.forEach(function (lim) { PADS.some(function (pg) {
        var info = {}, wd = { left: 0, right: 0 }, wraps = 0, ok = true;
        names.forEach(function (n) {
          if (!wrapLabel(nm(n), lim)) ok = false;
          var q = info[n] = labInfo(nm(n), cols === 2 && mid[n] >= cx ? 'right' : 'left', lim, pg[0]);
          wd[q.side] = Math.max(wd[q.side], q.w); if (q.lines.length > 1) wraps++;
        });
        if (!ok || (cols === 2 && !wd.right)) return true;
        var top = { left: colTop(x0, x0 + wd.left), right: colTop(xr - wd.right, xr) }, over = 0;
        per.forEach(function (list) {
          ['left', 'right'].forEach(function (side) {
            var mine = list.filter(function (n) { return info[n].side === side; });
            var h = mine.reduce(function (a, n) { return a + info[n].h; }, 0) + pg[1] * Math.max(0, mine.length - 1);
            over = Math.max(over, h - (bot - top[side]));
          });
        });
        var l = wd.left ? x0 + wd.left + 16 : P.x + 12, r = wd.right ? xr - wd.right - 16 : xr - 8;
        var s = Math.max(1e-3, Math.min((r - l) / bw, (P.h - band - 24) / bh));
        var c = { cols: cols, lim: lim, info: info, wd: wd, top: top, l: l, r: r, s: s, over: Math.max(0, over), wraps: wraps, pad: pg[0], gap: pg[1] };
        var better = !best || (c.over < best.over - 0.5) || (Math.abs(c.over - best.over) <= 0.5 &&
          (c.s > best.s + 1e-9 || (Math.abs(c.s - best.s) <= 1e-9 && (c.cols < best.cols || (c.cols === best.cols && c.wraps < best.wraps)))));
        if (better) best = c;
        return over <= 0;                        // it fits: no tighter plates
      }); });
    });
    var top = P.y + band, h = P.h - band;
    if (!names.length) {                         // no labels: the drawing fills the panel under the captions, at its right edge
      S.panelMap = fit(box, { x: P.x, y: top, w: P.w, h: h }, 12);
      S.panelMap[2] += xr - 8 - (box[2] * S.panelMap[0] + S.panelMap[2]);
      S.lay2 = { cols: 0, info: {}, wd: { left: 0, right: 0 }, top: { left: P.y, right: P.y }, lim: Infinity, pad: 16, gap: 8 };
      return;
    }
    var s = best.s, x = best.wd.right ? (best.l + best.r - bw * s) / 2 : best.r - bw * s;   // one column: at the right edge
    S.panelMap = affine(s, s, x - box[0] * s, top + (h - bh * s) / 2 - box[1] * s);
    S.lay2 = best;
  }
  // this frame's rows: the labels of each column sorted by their part's height and spread so none sit on each other;
  // two slanted leaders that cross swap places (equal rows swap their heights: each swap makes the leaders shorter in
  // total, so this ends)
  function labelSlots(view, f, t, alpha) {
    var K = dryRun(f), list = K.collect, L = S.lay2, slots = {}, bot = S.panel.y + S.panel.h;
    var side = function (q) {
      if (L.info[q.id]) return L.info[q.id].side;
      return L.cols === 2 && q.at[0] >= (S.m.box[0] + S.m.box[2]) / 2 ? 'right' : 'left';
    };
    ['left', 'right'].forEach(function (sd) {
      var mine = list.filter(function (q) { return side(q) === sd; }), n = mine.length, i, top = L.top[sd];
      if (!n) return;
      mine.forEach(function (q) { var o = L.info[q.id] || labInfo(q.label, sd, L.lim, L.pad); q.lines = o.lines; q.w = o.w; q.h = o.h; });
      mine.sort(function (a, b) { return a.p[1] - b.p[1]; });
      var place = function () {
        for (i = 0; i < n; i++) {
          var q = mine[i], pv = mine[i - 1];
          q.y = Math.max(top + q.h / 2, Math.min(bot - q.h / 2, q.p[1]), i ? pv.y + pv.h / 2 + L.gap + q.h / 2 : -Infinity);
        }
        for (i = n - 1; i >= 0; i--) { var nx = mine[i + 1]; mine[i].y = Math.min(mine[i].y, nx ? nx.y - nx.h / 2 - L.gap - mine[i].h / 2 : bot - mine[i].h / 2); }
      };
      place();
      var ex = sd === 'right' ? BOX.r * S.W - L.wd.right - 10 : BOX.x * S.W + L.wd.left + 10;
      var cross = function (a, b) {
        var a0 = [ex, a.y], b0 = [ex, b.y];
        return sideOf(a0, a.p, b0) * sideOf(a0, a.p, b.p) < 0 && sideOf(b0, b.p, a0) * sideOf(b0, b.p, a.p) < 0;
      };
      for (var pass = 0, swapped = true; swapped && pass < n * n; pass++) {
        swapped = false;
        for (i = 0; i < n && !swapped; i++) for (var j = i + 1; j < n && !swapped; j++) if (cross(mine[i], mine[j])) {
          if (mine[i].h === mine[j].h) { var y = mine[i].y; mine[i].y = mine[j].y; mine[j].y = y; }
          else { var tq = mine[i]; mine[i] = mine[j]; mine[j] = tq; place(); }
          swapped = true;
        }
      }
      mine.forEach(function (q) { slots[q.key] = { y: q.y, w: q.w, h: q.h, lines: q.lines, side: sd, ex: ex }; });
    });
    return slots;
  }
  function sideOf(a, b, c) { return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]); }

  // ------------------------------------------------------------------ per frame
  function drawView(g, view, f, t, alpha, clipRect) {
    var K = kit(g, view, f, t, alpha);
    K.labelAlpha = ST.progress(t, cue('labels', 1.4), cue('labels', 1.4) + 0.6, ST.ease.inOutCubic);
    if (view === 'panel' && S.reels) K.slots = labelSlots(view, f, t, alpha);
    g.save();
    if (clipRect) { g.beginPath(); g.rect(clipRect.x, clipRect.y, clipRect.w, clipRect.h); g.clip(); }
    g.globalAlpha = alpha; g.lineCap = 'round'; g.lineJoin = 'round';
    g.shadowColor = C.l(.8); g.shadowBlur = C.glow;
    S.m.draw(K);
    g.restore();
  }

  function strip(g, f, t, alpha) {
    var reels = S.hud === 'portrait' && S.reels, x0, w, y0, h = reels ? PSTRIP.h : S.hud === 'portrait' ? 150 : 50, pad = reels ? PSTRIP.pad : 38;
    if (reels) { x0 = BOX.x * S.W + 16; w = BOX.r * S.W - 16 - x0; y0 = S.lay.strip + PSTRIP.pad; }   // its plate (16 px round the ticks) fills the safe box's width
    else if (S.hud === 'portrait') { x0 = 64; w = S.W * 0.79; y0 = S.H * 0.75 + 70; }
    else if (S.hud === 'side') { x0 = S.panel.x; w = S.panel.w; y0 = S.H - 100; }
    else { x0 = S.W - 900; w = 852; y0 = S.H - 90; }
    // with no measured length, the recording is taken to run from its start to the film's end
    var dur = (S.doc.source && S.doc.source.duration) || Math.max(0.1, S.dur - S.off / S.fps);
    // where a film frame sits on the recording: the clip starts at film frame "xray".offset_frames, so the strip's
    // clock is the recording's (frame - off), not the film's; before the clip starts the caret waits at 0
    var at = function (fr) { return Math.max(0, Math.min(1, recTime(fr) / dur)); };
    // the label fits its room: a long mechanism word shrinks it to the readable floor (2.2% of the frame height: 24 px
    // at 1080, 43 px at 1920), then drops "the clip's sound", then cuts the word with an ellipsis; it never runs past
    // the plate. At 9:16 it sits on the ticks' row, left of them, in at most 56% of the strip
    var one = String(S.m.one || 'an event'), px = reels ? S.lpx : S.hud === 'portrait' ? 24 : 26, floor = Math.ceil((reels ? S.H : Math.min(S.W, S.H)) * 0.022), room = reels ? w * 0.56 : w;
    var label = ('the clip’s sound · red = ' + one).toUpperCase(), fits = function () { return g.measureText(label).width <= room; };
    var fitLabel = function () {
      g.font = '500 ' + px + 'px "IBM Plex Mono"';
      while (!fits() && px > floor) { px--; g.font = '500 ' + px + 'px "IBM Plex Mono"'; }
      if (!fits()) label = ('red = ' + one).toUpperCase();
      while (!fits() && one.length > 1) { one = one.slice(0, -1); label = ('red = ' + one.replace(/\s+$/, '') + '…').toUpperCase(); }
    };
    g.save(); g.globalAlpha = alpha;
    var bx = x0, bw = w;   // the ticks' span: the whole strip, or at 9:16 what the label leaves
    if (reels) { fitLabel(); bx = x0 + g.measureText(label).width + 28; bw = x0 + w - bx; }
    g.fillStyle = C.bg(.8); g.fillRect(x0 - 16, y0 - pad, w + 32, h + pad + 16);
    S.ev.forEach(function (e) {
      var x = bx + at(e.frame) * bw, hh = Math.max(6, (0.35 + 0.65 * (e.strength || 0.5)) * h);
      var on = e.frame <= f, col = e.kind === 'skip' ? (on ? C.i(.55) : C.i(.2)) : (on ? C.hot : C.h(.32));
      g.fillStyle = col; g.fillRect(x - 2, y0 + h / 2 - hh / 2, 4, hh);
    });
    // now: a small caret over the ticks (no axis line, no full-height playhead: it must not read as a player's bar)
    var cx = bx + at(f) * bw;
    g.fillStyle = C.ink; g.beginPath(); g.moveTo(cx - 9, y0 - 8); g.lineTo(cx + 9, y0 - 8); g.lineTo(cx, y0 + 4); g.closePath(); g.fill();
    if (reels) { g.fillStyle = C.muted; g.textBaseline = 'middle'; g.textAlign = 'left'; g.fillText(label, x0, y0 + h / 2); }
    else { fitLabel(); g.fillStyle = C.muted; g.textBaseline = 'bottom'; g.textAlign = 'left'; g.fillText(label, x0, y0 - 12); }
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
      // past "xray".track_until (the clip's seconds, so on the recording's clock) the see-through fades out instead
      // of sliding off the object
      var hold = typeof S.cfg.track_until === 'number' ? 1 - ST.progress(recTime(f), S.cfg.track_until, S.cfg.track_until + 0.3, ST.ease.inOutCubic) : 1;
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

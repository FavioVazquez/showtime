/* showtime X-ray live page, part 2 of 2 (runtime/xray-live/live.js): the controls around the film's own page.
 *
 * The page underneath is the project's index.html, unchanged: xray.js and mechanism.js (or the diagram layout's
 * page and its scene) draw every frame through ST.onSeek, exactly as in the film. This script only picks the
 * frame: from the clip while it plays (its own sound is the clock), or the one the viewer jumps to.
 *   - the clip: packed once, one blob: URL; a second copy of it (the radiograph) is a canvas mirror of the first
 *   - play / pause with the clip's sound; a timeline with every event as a tick (red kept, grey skipped); a click on
 *     a tick, or the arrow keys, jumps to that event's exact frame (where its strike peaks)
 *   - 0.25x around the current event; light / dark; see-through / split when the clip is tracked
 *   - part labels: hover or tap one (or pick it in the list) and it lights up
 *   - touch: pads under the picture, one per kind of event (a typewriter's keys, an instrument's notes, a kit's
 *     drums); a pad, or its key on the keyboard, plays the next such event from the real clip with its sound.
 *     The picture: drag sideways to scrub; a click plays the next event (or pauses while playing)
 *   - links to a hit (#hit4) copied from the page; an embed snippet (<showtime-xray> or an iframe with #embed)
 *   - the line that made it (the prompt and the commands, showtime.json "xray".made / export --prompt)
 *   - the receipt line (showtime.json "xray".receipt) and the credit line; no sync marker (it is for verify only)
 * The timeline stops at the clip's end: the film's end card is the receipt and credit under the picture here.
 * window.xrayLive: state(), seek(t), jump(i), play(), pause(), slow(), strike(pad), theme(name), layout(name),
 * hover(name), link().
 */
(function () {
  'use strict';
  var W = window, D = document, R = W.__XL_REAL__, ST = W.ST;
  var cfgEl = D.getElementById('xl-cfg');
  if (!R || !ST || !cfgEl) return;
  var C = JSON.parse(cfgEl.textContent), L = C.live, CFG = R.cfg || {}, XCFG = CFG.xray || {};
  var FPS = L.fps || 30, FW = L.W, FH = L.H, DIAGRAM = L.layout === 'diagram';
  var $ = function (s, r) { return (r || D).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || D).querySelectorAll(s)); };
  function mk(tag, attrs, parent, text) {
    var e = D.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { if (attrs[k] != null) e.setAttribute(k, attrs[k]); });
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }

  // ------------------------------------------------------------------ media: one blob: URL per packed file
  var urls = {};
  $$('script[data-xl-media]').forEach(function (s) {
    var b = atob(s.textContent.trim()), n = b.length, u = new Uint8Array(n);
    for (var i = 0; i < n; i++) u[i] = b.charCodeAt(i);
    urls[s.getAttribute('data-xl-media')] = URL.createObjectURL(new Blob([u], { type: s.getAttribute('data-type') || 'video/webm' }));
    s.textContent = '';
  });
  var vids = $$('video[data-xl-src]');
  vids.forEach(function (v) { v.src = urls[v.getAttribute('data-xl-src')]; v.preload = 'auto'; v.playsInline = true; v.muted = true; });
  var master = D.getElementById('clip') || vids[0];
  var followers = vids.filter(function (v) { return v !== master; });
  var mirrors = $$('canvas[data-xl-mirror]');

  // ------------------------------------------------------------------ the page's own drawing, observed
  // The mechanism's draw(k) is wrapped (never replaced): it records the events the page uses (k.ev), the kit's
  // state on each frame (which event acts, its 0..1 motion) and where each part label landed (the hit list), and
  // draws the hovered label as acting. The diagram layout: its scene builder hands over the same events.
  var X = W.XRAY, hot = null, pending = [], hits = [], kitState = null, events = null, partNames = [];
  function evCopy(list) {
    return list.map(function (e) {
      var nn = (e.notes || []).filter(function (q) { return q && q.name; });
      var notes = nn.map(function (q) { return String(q.name); });
      var pitches = nn.map(function (q) { return typeof q.pitch === 'number' ? q.pitch : null; });
      return { i: e.i, frame: e.frame, kind: e.kind, ch: e.ch == null ? null : e.ch, strength: e.strength, notes: notes, pitches: pitches };
    });
  }
  if (X && X.mech && typeof X.mech.draw === 'function') {
    var draw0 = X.mech.draw;
    X.mech.draw = function (k) {
      if (!events && k.ev) events = evCopy(k.ev);
      var label0 = k.label, mine = [], g = k.g;
      k.label = function (text, at, dx, dy, on) {
        var nm = String(text), isHot = !!hot && nm.toLowerCase() === hot, la = k.labelAlpha, rect = null;
        if (partNames.indexOf(nm) < 0) partNames.push(nm);
        if (hot && !isHot) k.labelAlpha = (la == null ? 1 : la) * 0.35;
        var own = Object.prototype.hasOwnProperty.call(g, 'fillRect'), fr = g.fillRect;
        g.fillRect = function (x, y, w, h) { if (!rect) rect = { x: x, y: y, w: w, h: h }; return fr.apply(g, arguments); };
        try { return label0.call(this, text, at, dx, dy, on || isHot); } finally {
          if (own) g.fillRect = fr; else delete g.fillRect;
          var shown = (la == null ? 1 : la) * (k.alpha == null ? 1 : k.alpha);
          k.labelAlpha = la;
          if (rect && shown > 0.5) { var p = k.pr(at[0], at[1]); mine.push({ name: nm, x: rect.x, y: rect.y, w: rect.w, h: rect.h, ax: p[0], ay: p[1] }); }
        }
      };
      try { draw0.call(this, k); } finally { k.label = label0; }
      mine.forEach(function (h) {
        pending.push(h);
        if (hot && h.name.toLowerCase() === hot) {     // a ring on the part the hovered label names
          g.save(); g.globalAlpha = k.alpha == null ? 1 : k.alpha; g.shadowBlur = 0; g.strokeStyle = k.C.hot; g.lineWidth = 3;
          g.beginPath(); g.arc(h.ax, h.ay, 18, 0, Math.PI * 2); g.stroke(); g.restore();
        }
      });
      kitState = { f: k.f, cur: k.cur, s: k.s, hot: !!k.hot, n: k.n, view: k.view, kind: k.kind, ch: k.ch };
    };
  }
  var XD = W.XRAY_DIAGRAM;
  if (XD) Object.keys(XD).forEach(function (n) {
    var b = XD[n];
    if (typeof b !== 'function') return;
    XD[n] = function (ctx) { if (ctx && ctx.events) events = evCopy(ctx.events); return b.apply(this, arguments); };
  });
  // after the page's own handlers (registered first): this frame's labels are complete
  ST.onSeek(function () { if (!DIAGRAM) { hits = pending; pending = []; } });

  // ------------------------------------------------------------------ the layout: the film scaled, controls under it
  var root = D.documentElement;
  // framed by <showtime-xray> or an iframe with #embed: fit the width and tell the host how tall the page is
  var EMBED = !!R.look.embed && W.self !== W.top;
  root.setAttribute('data-xl', '');
  if (EMBED) root.setAttribute('data-xl-embed', '');
  root.setAttribute('data-xl-theme', XCFG.theme === 'light' ? 'light' : 'dark');
  var stage = D.getElementById('stage') || D.body.firstElementChild;
  var app = mk('div', { 'class': 'xl-app', 'data-st-free': '' });
  D.body.insertBefore(app, D.body.firstChild);
  var head = mk('header', { 'class': 'xl-head' }, app);
  mk('h1', { 'class': 'xl-title' }, head, L.title);
  var nowEl = mk('p', { 'class': 'xl-now', 'aria-live': 'polite' }, head, '');
  var view = mk('div', { 'class': 'xl-view' }, app);
  var scaler = mk('div', { 'class': 'xl-scale' }, view);
  scaler.appendChild(stage);
  stage.style.setProperty('width', FW + 'px', 'important');
  stage.style.setProperty('height', FH + 'px', 'important');
  var hitLayer = mk('div', { 'class': 'xl-hit', 'aria-hidden': 'true' }, view);
  var veil = mk('div', { 'class': 'xl-veil' }, view, 'Loading the clip…');

  var bar = mk('div', { 'class': 'xl-bar' }, app);
  var row = mk('div', { 'class': 'xl-row' }, bar);
  function btn(cls, label, text, parent) { var b = mk('button', { type: 'button', 'class': 'xl-btn ' + cls, 'aria-label': label, title: label }, parent || row); b.innerHTML = text; return b; }
  var ICON_PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M7.5 4.8v14.4c0 .8.9 1.3 1.6.9l11.2-7.2c.6-.4.6-1.3 0-1.7L9.1 3.9c-.7-.4-1.6.1-1.6.9z"/></svg>';
  var ICON_PAUSE = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect fill="currentColor" x="6" y="4.5" width="4.2" height="15" rx="1.2"/><rect fill="currentColor" x="13.8" y="4.5" width="4.2" height="15" rx="1.2"/></svg>';
  var playB = btn('xl-play', 'Play (space)', ICON_PLAY);
  var prevB = btn('xl-prev', 'Previous event (←)', '<span aria-hidden="true">←</span> Event');
  var nextB = btn('xl-next', 'Next event (→)', 'Event <span aria-hidden="true">→</span>');
  var slowB = btn('xl-slow', 'This event at 0.25x (Shift+S)', '0.25×');
  var timeEl = mk('span', { 'class': 'xl-time' }, row, '');
  var spacer = mk('span', { 'class': 'xl-grow' }, row);
  var themeB = btn('xl-theme', 'Light or dark (Shift+T)', 'Light');
  var layoutB = btn('xl-layout', 'See-through or split (Shift+L)', 'Split');
  layoutB.hidden = !L.tracked;
  var linkB = btn('xl-link', 'Copy a link to this moment', 'Link');
  var embedB = btn('xl-embed', 'Embed this page on yours', 'Embed');
  embedB.setAttribute('aria-expanded', 'false');
  var track = mk('div', { 'class': 'xl-track', role: 'slider', tabindex: '0', 'aria-label': 'Clip time', 'aria-valuemin': '0' }, bar);
  var ticks = mk('div', { 'class': 'xl-ticks' }, track);
  var headEl = mk('div', { 'class': 'xl-playhead' }, track);
  var legend = mk('p', { 'class': 'xl-legend' }, bar);
  var padsEl = mk('div', { 'class': 'xl-pads', role: 'group' }, bar);
  var parts = mk('div', { 'class': 'xl-parts', role: 'group', 'aria-label': 'Parts' }, bar);
  var shareEl = mk('div', { 'class': 'xl-share', hidden: '' }, bar);
  var meta = mk('div', { 'class': 'xl-meta' }, app);
  var toast = mk('p', { 'class': 'xl-toast', role: 'status', 'aria-live': 'polite' }, view, '');
  void spacer;

  // ------------------------------------------------------------------ state
  // pass: a stretch of the clip played and stopped on purpose: 'slow' (0.25x around an event, ends on its frame) or
  // 'hit' (a pad: 1x from just before the event to its settle, with its sound)
  var S = { f: -1, playing: false, rate: 1, pass: null, ready: false, busy: false, want: null, going: null, goWant: null };
  var OFF = 0, SFPS = FPS, CLIPDUR = L.clipDur || 0, LAST = 0, kept = [];
  function noun(n) {
    var m = X && X.mech;
    if (m && m.noun) return n === 1 ? (m.noun1 || m.noun.replace(/s$/, '')) : m.noun;
    // the diagram page's own words: a typewriter's keystrokes, else showtime.json "xray" one / noun
    var one = DIAGRAM && (XCFG.mechanism || 'typewriter') === 'typewriter' ? 'keystroke' : (XCFG.one || 'event');
    return n === 1 ? one : (XCFG.noun && one === XCFG.one ? XCFG.noun : one + 's');
  }
  function fmt(t) { return (Math.max(0, t)).toFixed(2) + ' s'; }

  // the clip's time for a film time, as the stage itself seeks a <video> (data-offset, the middle of the frame)
  function clipTime(t) {
    var local = OFF + Math.max(0, t), dur = master.duration;
    if (isFinite(dur) && dur > 0) local = Math.min(local, Math.max(0, dur - 0.5 / SFPS));
    return local + 0.5 / SFPS;
  }
  function frameOfClip(ct) { return Math.max(0, Math.min(LAST, Math.floor((ct - OFF) * FPS + 0.01))); }

  function drawMirrors() {
    if (!master.videoWidth) return;
    mirrors.forEach(function (cv) {
      if (cv.width !== master.videoWidth) { cv.width = master.videoWidth; cv.height = master.videoHeight; }
      try { cv.getContext('2d').drawImage(master, 0, 0, cv.width, cv.height); } catch (e) { /* not decodable yet */ }
    });
  }

  // draw film frame f (the stage seeks one at a time; a newer frame asked meanwhile is drawn next)
  function stageTo(f) {
    if (S.busy) { S.want = f; return S.busyP; }
    S.busy = true; S.f = f;
    S.busyP = ST.seek(f / FPS).catch(function (e) { console.error('[xray live] ' + (e && e.message || e)); }).then(function () {
      S.busy = false;
      if (DIAGRAM) collectDiagramHits();
      paint();
      if (S.want != null && S.want !== S.f) { var w = S.want; S.want = null; return stageTo(w); }
      S.want = null;
    });
    return S.busyP;
  }
  function seeked(v, ct) {
    return new Promise(function (res) {
      if (Math.abs(v.currentTime - ct) < 1e-4 && v.readyState >= 2) return res();
      var done = false, fin = function () { if (done) return; done = true; v.removeEventListener('seeked', ok); res(); };
      var ok = function () {
        if (v.requestVideoFrameCallback) { v.requestVideoFrameCallback(fin); W.setTimeout(fin, 250); } else fin();
      };
      v.addEventListener('seeked', ok);
      W.setTimeout(fin, 3000);
      v.currentTime = ct;
    });
  }
  // paused: the exact frame, the clip seeked to it first, then the inside drawn on it
  function go(f) {
    f = Math.max(0, Math.min(LAST, Math.round(f)));
    S.goWant = f;
    if (S.going) return S.going;
    S.going = (async function () {
      while (S.goWant != null) {
        var g = S.goWant; S.goWant = null;
        var ct = clipTime(g / FPS);
        await Promise.all([master].concat(followers).map(function (v) { if (!v.paused) v.pause(); return seeked(v, ct); }));
        drawMirrors();
        await stageTo(g);
      }
      S.going = null;
    })();
    return S.going;
  }

  // playing: the clip's presented frame is the clock (its sound plays with it)
  function onVideoFrame(now, md) {
    if (!S.playing) return;
    tickPlay(md && typeof md.mediaTime === 'number' ? md.mediaTime : master.currentTime);
    master.requestVideoFrameCallback(onVideoFrame);
  }
  function rafLoop() { if (!S.playing) return; tickPlay(master.currentTime); R.raf(rafLoop); }
  function tickPlay(ct) {
    var f = frameOfClip(ct);
    drawMirrors();
    followers.forEach(function (v) { if (Math.abs(v.currentTime - master.currentTime) > 0.08) v.currentTime = master.currentTime; });
    if (S.pass && f >= S.pass.to) {
      // a slow pass ends on the event's own frame; a pad's pass rests where it stopped (no jump back)
      var ps = S.pass, rest = ps.kind === 'slow' ? ps.ev.frame : ps.to;
      endPass(); S.ending = ps.kind;
      go(rest).then(function () { S.ending = false; paint(); });
      return;
    }
    if (f >= LAST && master.currentTime >= clipTime(LAST / FPS) - 0.5 / SFPS) { pause(); return; }
    stageTo(f);
  }
  function play() {
    if (!S.ready) return;
    if (S.f >= LAST) { S.f = 0; master.currentTime = clipTime(0); }
    S.playing = true;
    master.muted = false;
    master.playbackRate = S.rate;
    followers.forEach(function (v) { v.muted = true; v.playbackRate = S.rate; var q = v.play(); if (q && q.catch) q.catch(function () {}); });
    var p = master.play();
    if (p && p.catch) p.catch(function (e) {
      // no sound allowed yet (a host without a user gesture): play muted rather than not at all
      master.muted = true; master.play().catch(function () { pause(); });
      console.warn('[xray live] ' + (e && e.message || e));
    });
    if (master.requestVideoFrameCallback) master.requestVideoFrameCallback(onVideoFrame); else R.raf(rafLoop);
    paint();
  }
  function pause() {
    var was = S.playing;
    S.playing = false;
    master.pause(); followers.forEach(function (v) { v.pause(); });
    if (S.pass) endPass();
    paint();
    if (was) return go(frameOfClip(master.currentTime));
    return Promise.resolve();
  }
  function endPass() { S.pass = null; S.rate = 1; master.playbackRate = 1; followers.forEach(function (v) { v.playbackRate = 1; }); if (S.playing) { S.playing = false; master.pause(); followers.forEach(function (v) { v.pause(); }); } }
  function toggle() { if (S.playing) pause(); else play(); }
  function isSlow() { return !!S.pass && S.pass.kind === 'slow'; }
  // play [from, to] of the clip at rate, then stop (tickPlay ends it); a newer pass replaces one under way
  var passGen = 0;
  function runPass(kind, e, from, to, rate) {
    // typed in the clip's own order: the next hit is just ahead of the one playing, so the clip plays on to it (no
    // seek, no cut back): typing the clip's words plays the clip straight through
    if (kind === 'hit' && S.playing && S.pass && S.pass.kind === 'hit' && S.rate === rate) {
      var cur = frameOfClip(master.currentTime);
      if (cur < e.frame && from - cur <= 12) { ++passGen; S.pass.ev = e; S.pass.to = Math.max(S.pass.to, to); return Promise.resolve(); }
    }
    var gen = ++passGen;
    return pause().then(function () { return go(from); }).then(function () {
      if (gen !== passGen) return;                 // a newer press already took over
      S.pass = { kind: kind, ev: e, to: to }; S.rate = rate;
      master.preservesPitch = true;
      play();
    });
  }

  // ------------------------------------------------------------------ events
  function eventAt(f) { for (var i = kept.length - 1; i >= 0; i--) if (kept[i].frame <= f) return kept[i]; return null; }
  function nearEvent(f) {                       // the event acting now (its motion spans 3 frames before, 7 after)
    var best = null, bd = 1e9;
    kept.forEach(function (e) { var d = f - e.frame; if (d >= -3 && d <= 7 && Math.abs(d) < bd) { bd = Math.abs(d); best = e; } });
    return best;
  }
  function stepEvent(dir) {
    if (!kept.length) return;
    var f = S.f, e = null;
    if (dir > 0) { for (var i = 0; i < kept.length; i++) if (kept[i].frame > f) { e = kept[i]; break; } }
    else { for (var j = kept.length - 1; j >= 0; j--) if (kept[j].frame < f) { e = kept[j]; break; } }
    if (!e) e = dir > 0 ? kept[kept.length - 1] : kept[0];
    jumpTo(e);
  }
  function jumpTo(e) { var p = S.playing ? pause() : Promise.resolve(); return p.then(function () { return go(e.frame); }); }
  function slow() {
    if (!S.ready || !kept.length) return Promise.resolve();
    var f = S.f, e = nearEvent(f);
    if (!e) { for (var i = 0; i < kept.length; i++) if (kept[i].frame >= f) { e = kept[i]; break; } }
    if (!e) e = kept[kept.length - 1];
    var from = Math.max(0, e.frame - 8), to = Math.min(LAST, e.frame + 15);   // its rise (3 frames) and settle (7), with room
    return runPass('slow', e, from, to, 0.25);
  }
  // a pad or a click on the picture: the event heard and seen, at 1x, from just before its rise to its settle
  function strikeEvent(e) {
    if (!S.ready || !e) return Promise.resolve();
    touched();
    var to = Math.min(LAST, e.frame + 10);
    S.lastHit = { ev: e, rest: to };
    return runPass('hit', e, Math.max(0, e.frame - 6), to, 1);
  }
  // where "next" counts from: the struck event while its pass plays or rests where it stopped (events can be closer
  // than a pass is long), else the frame on screen
  function refFrame() {
    var lh = S.lastHit;
    if (lh && (S.pass && S.pass.ev === lh.ev || S.f === lh.rest || S.going)) return lh.ev.frame;
    return lh ? S.f : S.f - 1;                  // before the first strike, the event on the frame shown counts as next
  }
  function nextAfter(list, f) {                 // the first event after frame f (wraps to the first)
    if (!list.length) return null;
    for (var i = 0; i < list.length; i++) if (list[i].frame > f) return list[i];
    return list[0];
  }

  // ------------------------------------------------------------------ look: theme and layout
  // In place when the page can set itself up again (XRAY.restyle), else the page reloads on the same frame.
  function relook(over) {
    var t = S.f >= 0 ? S.f / FPS : 0;
    var theme = over.theme || root.getAttribute('data-xl-theme');
    var layout = over.layout || curLayout;
    if (!DIAGRAM && X && typeof X.restyle === 'function') {
      X.restyle({ theme: theme, layout: layout });
      root.setAttribute('data-xl-theme', theme); curLayout = layout;
      writeHash(); S.f = -1; stageTo(Math.round(t * FPS)); paint();
      return true;
    }
    try {
      W.location.hash = hashFor({ t: t, theme: theme, layout: layout, embed: R.look.embed }); W.location.reload();
      return true;
    } catch (e) { console.warn('[xray live] this host cannot reload the page: ' + (e && e.message || e)); return false; }
  }
  var curLayout = (R.look.layout && L.tracked) ? R.look.layout : (L.layout === 'split' ? 'split' : 'through');
  // a link to a moment: plain tokens joined by "_" (#hit4, #t2.533_light_split; pre.js reads them back). A frame
  // that is an event's own frame is named by the event (hit N, as the page counts them), any other by its time.
  function hashFor(o) {
    var tk = [];
    if (o.hit) tk.push('hit' + o.hit); else if (o.t != null) tk.push('t' + (+o.t).toFixed(3).replace(/\.?0+$/, ''));
    if (o.theme && o.theme !== L.theme) tk.push(o.theme);
    if (L.tracked && o.layout && o.layout !== (L.layout === 'split' ? 'split' : 'through')) tk.push(o.layout);
    if (o.embed) tk.push('embed');
    return '#' + tk.join('_');
  }
  function hereHash(embed) {
    var f = Math.max(0, S.f), k = -1;
    for (var i = 0; i < kept.length; i++) if (kept[i].frame === f) { k = i; break; }
    return hashFor({ hit: k >= 0 ? k + 1 : 0, t: f / FPS, theme: root.getAttribute('data-xl-theme'), layout: curLayout, embed: embed });
  }
  function writeHash() {
    try { if (W.history && history.replaceState) history.replaceState(null, '', hereHash(R.look.embed)); } catch (e) { /* a sandboxed host */ }
  }

  // ------------------------------------------------------------------ part labels: the hit list
  function collectDiagramHits() {
    var vr = scaler.getBoundingClientRect(), k = scale || 1;
    hits = $$('[data-ld-label]', stage).map(function (g) {
      var t = g.querySelector('text'), plate = g.querySelector('rect');
      var op = parseFloat((plate && plate.getAttribute('opacity')) || '1');
      var vis = g.getAttribute('visibility') !== 'hidden' && getComputedStyle(g).visibility !== 'hidden' && op > 0.5;
      var r = (plate || g).getBoundingClientRect();
      if (!vis || !t || !(r.width > 0)) return null;
      var nm = t.textContent.trim();
      return { name: nm, x: (r.left - vr.left) / k, y: (r.top - vr.top) / k, w: r.width / k, h: r.height / k, g: g };
    }).filter(Boolean);
    $$('[data-ld-label]', stage).forEach(function (g) {
      var t = g.querySelector('text'), nm = t && t.textContent.trim();
      if (nm && partNames.indexOf(nm) < 0) partNames.push(nm);     // every part the diagram names, shown or not yet
      var on = !!hot && t && t.textContent.trim().toLowerCase() === hot;
      g.classList.toggle('xl-on', on); g.classList.toggle('xl-off', !!hot && !on);
    });
  }
  function setHot(name) {
    var n = name ? String(name).toLowerCase() : null;
    if (n === hot) return;
    hot = n;
    $$('.xl-part', parts).forEach(function (b) { b.setAttribute('aria-pressed', String(!!hot && b.textContent.toLowerCase() === hot)); });
    if (DIAGRAM) collectDiagramHits();
    else if (!S.playing && S.f >= 0 && !S.going) { var f = S.f; S.f = -1; stageTo(f); }
    hitLayer.classList.toggle('is-on', !!hot);
  }
  function hitAt(cx, cy) {
    var r = scaler.getBoundingClientRect(), k = scale || 1, x = (cx - r.left) / k, y = (cy - r.top) / k, pad = 8;
    for (var i = hits.length - 1; i >= 0; i--) {
      var h = hits[i];
      if (x >= h.x - pad && x <= h.x + h.w + pad && y >= h.y - pad && y <= h.y + h.h + pad) return h.name;
    }
    return null;
  }
  // The picture itself. Drag sideways: scrub (the picture's width is the whole clip). A click or tap that does not
  // drag: on a part label, light that part; elsewhere, pause while playing, else play the next event with its sound.
  // A mouse that only moves lights the label under it. Vertical drags stay the page's (touch-action: pan-y).
  var grab = null;
  view.addEventListener('pointerdown', function (e) {
    if (!S.ready || (e.pointerType === 'mouse' && e.button !== 0)) return;
    grab = { id: e.pointerId, x: e.clientX, y: e.clientY, f0: Math.max(0, S.f), scrub: false };
  });
  view.addEventListener('pointermove', function (e) {
    // a button let go outside the picture: the grab is over (no scrub without a button held)
    if (grab && e.pointerType === 'mouse' && !(e.buttons & 1)) { grab = null; view.classList.remove('is-scrub'); }
    if (grab && grab.id === e.pointerId) {
      var dx = e.clientX - grab.x, dy = e.clientY - grab.y;
      if (!grab.scrub && Math.abs(dx) > 6 && Math.abs(dx) > Math.abs(dy)) {
        grab.scrub = true; touched();
        try { view.setPointerCapture(e.pointerId); } catch (err) { /* already released */ }
        view.classList.add('is-scrub');
        if (S.playing) pause();
      }
      if (grab.scrub) { go(grab.f0 + dx / Math.max(1, view.clientWidth) * LAST); return; }
    }
    if (e.pointerType === 'mouse' && !grab) { var n = hitAt(e.clientX, e.clientY); view.classList.toggle('on-label', !!n); setHot(n); }
  });
  function ungrab(e, act) {
    if (!grab || grab.id !== e.pointerId) return;
    var g = grab; grab = null;
    view.classList.remove('is-scrub');
    if (g.scrub) { writeHash(); return; }
    if (!act) return;
    var n = hitAt(e.clientX, e.clientY);
    if (n) { setHot(e.pointerType === 'mouse' ? n : (n.toLowerCase() !== hot ? n : null)); return; }
    if (e.pointerType !== 'mouse') setHot(null);
    if (S.playing && !S.pass) { pause(); return; }
    strikeEvent(nextAfter(kept, refFrame()));
  }
  view.addEventListener('pointerup', function (e) { ungrab(e, true); });
  view.addEventListener('pointercancel', function (e) { ungrab(e, false); });
  view.addEventListener('pointerleave', function (e) { if (e.pointerType === 'mouse' && !grab) { setHot(null); view.classList.remove('on-label'); } });
  // ------------------------------------------------------------------ pads: play it from the real clip
  // One pad per kind of event, read from the events themselves: a typewriter's keys (laid out as a keyboard), an
  // instrument's notes (in pitch order), a kit's drums, else one pad. A mechanism may say how: XRAY.mechanism({...,
  // touch: {verb: 'Type on it', by: 'ch' | 'note' | 'kind' | 'one'}}). A pad, or its key, plays the next event of
  // its kind after the one on screen, with the clip's own sound; while the clip plays, the acting event's pad lights.
  var pads = [], padBy = 'one', padVerb = '';
  var KEYROWS = ['1234567890', 'qwertyuiop', 'asdfghjkl', 'zxcvbnm'];
  var PADKEYS = 'asdfghjkl;qwertyuiopzxcvbnm';
  function chKey(c) {
    if (c == null) return null;
    if (c === ' ') return 'space';
    if (c === '\n' || c === '\r') return 'return';
    return String(c).toLowerCase();
  }
  function noteOf(e) {                           // the event's top note (the melody line): name and pitch
    if (!e.notes || !e.notes.length) return null;
    var best = 0;
    for (var i = 1; i < e.notes.length; i++) if ((e.pitches[i] || -1) > (e.pitches[best] || -1)) best = i;
    return { name: e.notes[best], pitch: e.pitches[best] };
  }
  function pitchOfName(n) {                      // "C♯4" / "Db3" -> MIDI; null for a drum's name
    var m = /^([A-Ga-g])([#♯b♭]?)(-?\d+)$/.exec(String(n));
    if (!m) return null;
    var base = { c: 0, d: 2, e: 4, f: 5, g: 7, a: 9, b: 11 }[m[1].toLowerCase()];
    return 12 * (+m[3] + 1) + base + (m[2] === '#' || m[2] === '♯' ? 1 : m[2] === 'b' || m[2] === '♭' ? -1 : 0);
  }
  function prettyName(n) {                       // a drum's name as people say it: hihat_open -> open hi-hat
    var t = String(n).replace(/hi-?hat/i, 'hi-hat').replace(/_/g, ' ');
    var m = /^(hi-hat|ride|crash|tom|cymbal) (open|closed|bell|high|low|floor)$/i.exec(t);
    if (m) t = m[2].toLowerCase() === 'closed' ? m[1] : m[2] + ' ' + m[1];
    return t;
  }
  function buildPads() {
    padsEl.textContent = ''; pads = [];
    var T = (X && X.mech && X.mech.touch) || {};
    var withCh = kept.filter(function (e) { return (e.ch != null && e.ch !== '') || e.kind === 'return'; }).length;
    var withNote = kept.filter(function (e) { return e.notes && e.notes.length; }).length;
    var kinds = {}; kept.forEach(function (e) { kinds[e.kind || 'event'] = 1; });
    padBy = T.by || (withCh >= kept.length / 2 && withCh ? 'ch' : withNote >= kept.length / 3 && withNote ? 'note' : Object.keys(kinds).length > 1 ? 'kind' : 'one');
    padVerb = T.verb || { ch: 'Type on it', note: 'Play it', kind: 'Hit it', one: 'Try it' }[padBy] || 'Try it';
    var groups = {}, order = [];
    kept.forEach(function (e) {
      var k, label, pitch = null;
      if (padBy === 'ch') { k = e.kind === 'return' ? 'return' : chKey(e.ch); label = k; }
      else if (padBy === 'note') { var n = noteOf(e); if (!n) return; k = n.name; pitch = n.pitch != null ? n.pitch : pitchOfName(n.name); label = pitch == null ? prettyName(n.name) : n.name; }
      else if (padBy === 'kind') { k = e.kind || 'event'; label = k === 'event' ? noun(1) : k; }
      else { k = 'one'; label = padVerb; }
      if (k == null) return;
      if (!groups[k]) { groups[k] = { key: k, label: label, pitch: pitch, list: [] }; order.push(k); }
      groups[k].list.push(e);
    });
    var list = order.map(function (k) { return groups[k]; });
    // notes without a pitch are a kit's pieces: hit them
    if (padBy === 'note' && !T.verb && list.length && list.every(function (g) { return g.pitch == null; })) padVerb = 'Hit it';
    if (padBy === 'note') {
      if (list.length > 24) list = list.slice().sort(function (a, b) { return b.list.length - a.list.length; }).slice(0, 24);
      if (list.every(function (g) { return g.pitch != null; })) list.sort(function (a, b) { return a.pitch - b.pitch; });
    }
    if (!list.length) { padsEl.hidden = true; return; }
    padsEl.hidden = false;
    padsEl.setAttribute('aria-label', padVerb);
    padsEl.setAttribute('data-by', padBy);
    var head = mk('p', { 'class': 'xl-pads-head' }, padsEl);
    mk('span', { 'class': 'xl-k' }, head, padVerb);
    mk('span', { 'class': 'xl-pads-help' }, head, padBy === 'one' ? 'or click the picture' : 'click a pad or press its key: the real clip plays it');
    function pad(g, parent, keyName) {
      var b = mk('button', { type: 'button', 'class': 'xl-pad' + (g ? '' : ' is-off'), 'data-key': keyName || '' }, parent);
      if (!g) { b.disabled = true; b.textContent = keyName; b.setAttribute('aria-hidden', 'true'); return b; }
      mk('span', { 'class': 'xl-pad-l' }, b, g.label);
      if (g.list.length > 1) mk('span', { 'class': 'xl-pad-n' }, b, '×' + g.list.length);
      if (keyName && padBy !== 'ch' && padBy !== 'one') mk('kbd', {}, b, keyName === ';' ? ';' : keyName.toUpperCase());
      b.setAttribute('aria-label', padVerb + ': the next ' + (padBy === 'one' ? noun(1) : '“' + g.label + '”') + (keyName ? ' (key ' + keyName + ')' : '') +
        ', ' + g.list.length + ' in the clip');
      b.addEventListener('click', function () { strike(g); });
      g.el = b; g.keyName = keyName || null;
      pads.push(g);
      return b;
    }
    if (padBy === 'ch') {                          // a keyboard: the keys the clip typed, the rest dimmed
      var used = {}; list.forEach(function (g) { used[g.key] = g; });
      KEYROWS.forEach(function (rowKeys, ri) {
        var any = rowKeys.split('').some(function (c) { return used[c]; });
        if (ri === 0 && !any) return;              // the digit row only when a digit was typed
        var r = mk('div', { 'class': 'xl-keyrow xl-keyrow-' + ri }, padsEl);
        rowKeys.split('').forEach(function (c) { pad(used[c] || null, r, c); delete used[c]; });
      });
      var rest = Object.keys(used);
      if (rest.length) {
        var r2 = mk('div', { 'class': 'xl-keyrow xl-keyrow-x' }, padsEl);
        rest.forEach(function (k) { var b = pad(used[k], r2, k === 'space' || k === 'return' ? k : k); if (k === 'space') b.classList.add('is-wide'); else if (k.length > 1) b.classList.add('is-word'); });
      }
    } else {
      var strip = mk('div', { 'class': 'xl-padrow' }, padsEl);
      list.forEach(function (g, i) { pad(g, strip, padBy === 'one' ? null : PADKEYS.charAt(i) || null); });
    }
  }
  function strike(g) {
    if (!g || !S.ready) return Promise.resolve();
    var e = nextAfter(g.list, refFrame());
    pads.forEach(function (p) { if (p.el && p !== g) p.el.classList.remove('is-hit'); });
    if (g.el) {
      g.el.classList.remove('is-hit'); void g.el.offsetWidth; g.el.classList.add('is-hit');
      W.clearTimeout(g.hitT); g.hitT = W.setTimeout(function () { g.el.classList.remove('is-hit'); }, 450);
    }
    return strikeEvent(e);
  }
  function padForKey(e) {
    if (!pads.length || e.repeat) return null;
    var k = e.key;
    if (padBy === 'ch') {
      var want = k === 'Enter' ? 'return' : k.length === 1 ? k.toLowerCase() : null;
      if (!want || want === ' ') return null;      // space stays play / pause
      for (var i = 0; i < pads.length; i++) if (pads[i].key === want) return pads[i];
      return null;
    }
    if (k.length !== 1) return null;
    for (var j = 0; j < pads.length; j++) if (pads[j].keyName && pads[j].keyName === k.toLowerCase()) return pads[j];
    return null;
  }

  function buildParts() {
    parts.textContent = '';
    if (!partNames.length) { parts.hidden = true; return; }
    parts.hidden = false;
    mk('span', { 'class': 'xl-k' }, parts, 'Parts');
    partNames.forEach(function (nm) {
      var b = mk('button', { type: 'button', 'class': 'xl-part', 'aria-pressed': 'false' }, parts, nm);
      b.addEventListener('mouseenter', function () { setHot(nm); });
      b.addEventListener('mouseleave', function () { setHot(null); });
      b.addEventListener('focus', function () { setHot(nm); });
      b.addEventListener('blur', function () { setHot(null); });
      b.addEventListener('click', function () { setHot(hot === nm.toLowerCase() ? null : nm); });
    });
  }

  // ------------------------------------------------------------------ timeline
  function buildTimeline() {
    ticks.textContent = '';
    var n = (events || []).length, span = Math.max(1, LAST);
    (events || []).forEach(function (e) {
      if (e.frame > LAST) return;
      var skip = e.kind === 'skip', h = Math.round(30 + 70 * Math.max(0, Math.min(1, e.strength == null ? 0.5 : e.strength)));
      var what = skip ? 'skipped sound' : (e.kind && e.kind !== 'event' ? e.kind : noun(1));
      var b = mk('button', { type: 'button', 'class': 'xl-tick' + (skip ? ' is-skip' : ''), tabindex: '-1',
        'aria-label': what + ' ' + (e.i + 1) + ' at ' + fmt(e.frame / FPS) + (e.ch && e.ch !== ' ' ? ' (' + e.ch + ')' : ''),
        title: what + ' · frame ' + e.frame + ' · ' + fmt(e.frame / FPS) });
      b.style.left = (100 * e.frame / span).toFixed(3) + '%';
      b.style.setProperty('--h', h + '%');
      b.addEventListener('click', function (ev) { ev.stopPropagation(); jumpTo(e); });
      ticks.appendChild(b);
    });
    track.setAttribute('aria-valuemax', (LAST / FPS).toFixed(2));
    var nk = kept.length, ns = n - nk, kinds = {}, order = [];
    kept.forEach(function (e) { var k = e.kind || 'event'; if (!kinds[k]) { kinds[k] = 0; order.push(k); } kinds[k]++; });
    legend.innerHTML = '';
    mk('span', { 'class': 'xl-key-hot' }, legend, order.map(function (k) {
      return kinds[k] + ' ' + (k === 'event' ? noun(kinds[k]) : k + (kinds[k] === 1 ? '' : 's'));
    }).join(', ') || '0 ' + noun(0));
    if (ns) mk('span', { 'class': 'xl-key-skip' }, legend, ns + ' skipped (not the object’s)');
    mk('span', { 'class': 'xl-key-help' }, legend, '← → event to event · space plays · drag the picture to scrub · Shift+S 0.25×');
  }
  var dragging = false;
  function trackFrame(cx) { var r = track.getBoundingClientRect(); return Math.round(Math.max(0, Math.min(1, (cx - r.left) / Math.max(1, r.width))) * LAST); }
  track.addEventListener('pointerdown', function (e) {
    if (!S.ready || e.target.classList.contains('xl-tick')) return;
    dragging = true; track.setPointerCapture(e.pointerId);
    (S.playing ? pause() : Promise.resolve()).then(function () { go(trackFrame(e.clientX)); });
  });
  track.addEventListener('pointermove', function (e) { if (dragging) go(trackFrame(e.clientX)); });
  track.addEventListener('pointerup', function () { dragging = false; writeHash(); });
  track.addEventListener('pointercancel', function () { dragging = false; });

  // ------------------------------------------------------------------ paint the controls
  function paint() {
    var f = Math.max(0, S.f);
    playB.innerHTML = S.playing ? ICON_PAUSE : ICON_PLAY;
    playB.setAttribute('aria-label', S.playing ? 'Pause (space)' : 'Play (space)');
    playB.title = playB.getAttribute('aria-label');
    slowB.setAttribute('aria-pressed', String(isSlow()));
    themeB.textContent = root.getAttribute('data-xl-theme') === 'dark' ? 'Light' : 'Dark';
    themeB.setAttribute('aria-label', 'Switch to the ' + themeB.textContent.toLowerCase() + ' theme (Shift+T)');
    layoutB.textContent = curLayout === 'split' ? 'See-through' : 'Split';
    layoutB.setAttribute('aria-label', curLayout === 'split' ? 'Draw the inside on the object (Shift+L)' : 'Draw the inside beside the clip (Shift+L)');
    headEl.style.left = (100 * f / Math.max(1, LAST)).toFixed(3) + '%';
    track.setAttribute('aria-valuenow', (f / FPS).toFixed(2));
    track.setAttribute('aria-valuetext', fmt(f / FPS) + ', frame ' + f);
    timeEl.textContent = fmt(f / FPS) + ' · frame ' + f;
    var e = nearEvent(f), done = kept.filter(function (x) { return x.frame <= f; }).length;
    var words;
    if (e) {
      var k = kept.indexOf(e) + 1;
      words = (e.kind && e.kind !== 'event' ? e.kind.charAt(0).toUpperCase() + e.kind.slice(1) : noun(1).charAt(0).toUpperCase() + noun(1).slice(1)) +
        ' ' + k + ' of ' + kept.length + (e.ch && e.ch !== ' ' ? ' · “' + e.ch + '”' : e.ch === ' ' ? ' · space' : '') +
        (e.notes && e.notes.length ? ' · ' + e.notes.slice(0, 4).join(' ') : '') +
        (f === e.frame ? ' · on its frame (' + e.frame + ')' : ' · ' + (f < e.frame ? (e.frame - f) + ' frames before' : (f - e.frame) + ' frames after') + ' its frame');
    } else words = done + ' of ' + kept.length + ' ' + noun(kept.length) + ' so far';
    if (isSlow()) words += ' · 0.25×';
    nowEl.textContent = words;
    $$('.xl-tick', ticks).forEach(function (b, i) { var ev = events[i]; if (ev) b.classList.toggle('is-past', ev.frame <= f); });
    // the acting event's pad lights: the keyboard types itself while the clip plays
    var act = e && f >= e.frame - 1 && f <= e.frame + 5 ? e : null;
    pads.forEach(function (g) { g.el.classList.toggle('is-on', !!act && g.list.indexOf(act) >= 0); });
    if (!S.playing && S.ready && f !== hashFrame) { hashFrame = f; writeHash(); }   // the address names the moment on screen
  }
  var hashFrame = -1;

  // ------------------------------------------------------------------ fit the film to the window
  var scale = 1;
  function fit() {
    var cw = Math.min(D.documentElement.clientWidth, 1600) - 32;
    if (EMBED) {                                   // framed: the frame's width sets the size, the page sets the height
      cw = D.documentElement.clientWidth - (cw + 32 < 700 ? 24 : 32);
      scale = Math.max(0.05, cw / FW);
      scaler.style.transform = 'scale(' + scale + ')';
      view.style.width = Math.round(FW * scale) + 'px';
      view.style.height = Math.round(FH * scale) + 'px';
      app.style.setProperty('--xl-w', Math.round(FW * scale) + 'px');
      if (DIAGRAM && S.ready) collectDiagramHits();
      postHeight();
      return;
    }
    var ch = D.documentElement.clientHeight;
    var phone = cw < 700;
    // the controls under the picture count, the pads, parts and share fields below them scroll (never shrink the film)
    var under = bar.offsetHeight - padsEl.offsetHeight - parts.offsetHeight - shareEl.offsetHeight;
    var room = phone ? ch * 0.62 : ch - under - head.offsetHeight - 64;
    scale = Math.max(0.05, Math.min(cw / FW, Math.max(160, room) / FH));
    if (phone) scale = Math.min(cw / FW, (ch * 0.62) / FH);
    scaler.style.transform = 'scale(' + scale + ')';
    view.style.width = Math.round(FW * scale) + 'px';
    view.style.height = Math.round(FH * scale) + 'px';
    app.style.setProperty('--xl-w', Math.round(FW * scale) + 'px');
    if (DIAGRAM && S.ready) collectDiagramHits();
  }
  W.addEventListener('resize', fit);
  var lastH = 0, lastGrow = -1e9;
  function postHeight() {
    if (!EMBED) return;
    var h = Math.ceil(app.getBoundingClientRect().height), now = R.now();
    if (Math.abs(h - lastH) < 2) return;
    // a host's scrollbar coming and going changes the width and so the height: a small shrink right after a grow is
    // that flip, not a change of the page; ignore it
    if (h < lastH && lastH - h < 24 && now - lastGrow < 1200) return;
    if (h > lastH) lastGrow = now;
    lastH = h;
    try { W.parent.postMessage({ type: 'showtime-xray:size', height: h }, '*'); } catch (e) { /* no host to tell */ }
  }
  if (EMBED && W.ResizeObserver) new ResizeObserver(function () { postHeight(); }).observe(app);

  // ------------------------------------------------------------------ hints, links, embed
  var hinted = false;
  function say(text, ms) {
    toast.textContent = text; toast.classList.add('is-on');
    W.clearTimeout(say.t); say.t = W.setTimeout(function () { toast.classList.remove('is-on'); }, ms || 2600);
  }
  function touched() { if (!hinted) { hinted = true; toast.classList.remove('is-on'); } }
  function pageUrl() {                           // this page without its #moment
    var u = String(W.location.href || '').split('#')[0];
    return /^https?:/.test(u) ? u : null;
  }
  function fileName() { var m = /([^/?#]+\.html?)(?:[?#]|$)/i.exec(String(W.location.href || '')); return m ? m[1] : 'xray-live.html'; }
  // copy on the click itself (clipboard needs the gesture); a host that refuses: the text is selected for the viewer
  function copyText(text, field) {
    var done = function () { say('Copied'); }, fail = function () { if (field) { field.focus(); field.select(); } say('Press Ctrl+C or ⌘C to copy'); };
    try {
      if (W.navigator.clipboard && W.navigator.clipboard.writeText) W.navigator.clipboard.writeText(text).then(done, fail);
      else fail();
    } catch (e) { fail(); }
  }
  function field(parent, label, text, rows) {
    var w = mk('div', { 'class': 'xl-field' }, parent);
    var top = mk('div', { 'class': 'xl-field-top' }, w);
    mk('span', { 'class': 'xl-k' }, top, label);
    var b = mk('button', { type: 'button', 'class': 'xl-btn xl-copy' }, top, 'Copy');
    var ta = mk('textarea', { readonly: '', rows: String(rows || 1), spellcheck: 'false', 'aria-label': label }, w);
    ta.value = text;
    b.addEventListener('click', function () { copyText(ta.value, ta); });
    return ta;
  }
  function openShare(what) {
    var open = !shareEl.hidden && shareEl.getAttribute('data-what') === what;
    shareEl.textContent = ''; shareEl.hidden = open; shareEl.setAttribute('data-what', what);
    embedB.setAttribute('aria-expanded', String(!open && what === 'embed'));
    if (open) { postHeight(); return; }
    var base = pageUrl(), src = base || ('https://your.site/' + fileName());
    if (what === 'link') {
      field(shareEl, base ? 'A link to this moment' : 'A link to this moment (once the page is on the web)', src + hereHash(false), 1);
    } else {
      var t = (L.title || 'X-ray').replace(/"/g, '&quot;');
      // the snippets are text for another page (written so this offline page never names a file to fetch)
      var at = function (name, v) { return ' ' + name + '="' + v + '"'; };
      field(shareEl, 'Embed: one tag (loads when the viewer clicks)', '<script' + at('src', L.embedJs || 'https://faviovazquez.github.io/showtime/xray/embed.js') + '></' + 'script>\n' +
        '<showtime-xray' + at('src', src) + at('ratio', FW + '/' + FH) + at('title', t) + '></showtime-xray>', 2);
      var ew = FW >= FH ? 960 : 420, eh = Math.round(ew * FH / FW + 320);       // the film at that width, and its controls
      field(shareEl, 'Or an iframe', '<iframe' + at('src', src + '#embed') + at('title', t) + at('style', 'width:100%;max-width:' + ew + 'px;height:' + eh + 'px;border:0') +
        ' loading="lazy" allow="autoplay; fullscreen; clipboard-write"></iframe>', 2);
      mk('p', { 'class': 'xl-note' }, shareEl, (base ? '' : 'Put this file on your site first; the snippets point at where it is served. ') +
        'embed.js is one small file with no dependencies: link the showtime site’s copy, or host your own (showtime’s runtime/xray-live/embed.js).');
    }
    postHeight();
  }
  linkB.addEventListener('click', function () {
    var base = pageUrl();
    if (base) copyText(base + hereHash(false), null);
    openShare('link');
  });
  embedB.addEventListener('click', function () { openShare('embed'); });

  // ------------------------------------------------------------------ keys and buttons
  playB.addEventListener('click', toggle);
  prevB.addEventListener('click', function () { stepEvent(-1); });
  nextB.addEventListener('click', function () { stepEvent(1); });
  slowB.addEventListener('click', function () { if (isSlow()) pause(); else slow(); });
  themeB.addEventListener('click', function () { relook({ theme: root.getAttribute('data-xl-theme') === 'dark' ? 'light' : 'dark' }); });
  layoutB.addEventListener('click', function () { relook({ layout: curLayout === 'split' ? 'through' : 'split' }); });
  D.addEventListener('keydown', function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey || !S.ready) return;
    var tg = e.target && e.target.tagName;
    if (tg === 'INPUT' || tg === 'TEXTAREA' || tg === 'SELECT') return;
    var k = e.key, used = true;
    // letters are the pads' (a typewriter's keys, an instrument's notes); the page's own shortcuts take Shift
    // a focused control keeps its own Space and Enter (a button, a link, a summary, the time slider)
    var ownKeys = tg === 'BUTTON' || tg === 'A' || tg === 'SUMMARY' || (e.target && e.target.getAttribute && e.target.getAttribute('role') === 'slider');
    if ((k === 'Enter' || k === ' ') && ownKeys && !(k === ' ' && e.target === track)) return;
    var pd = !e.shiftKey && padForKey(e);
    if (pd) { e.preventDefault(); strike(pd); return; }
    if (k === ' ') toggle();
    else if (k === 'ArrowRight') { if (e.shiftKey) (S.playing ? pause() : Promise.resolve()).then(function () { go(S.f + 1); }); else stepEvent(1); }
    else if (k === 'ArrowLeft') { if (e.shiftKey) (S.playing ? pause() : Promise.resolve()).then(function () { go(S.f - 1); }); else stepEvent(-1); }
    else if (k === '.' || k === ',') { var d = k === '.' ? 1 : -1; (S.playing ? pause() : Promise.resolve()).then(function () { go(S.f + d); }); }
    else if (k === 'Home') { pause().then(function () { go(0); }); }
    else if (k === 'End') { pause().then(function () { go(LAST); }); }
    else if (e.shiftKey && (k === 'S' || k === 's')) { if (isSlow()) pause(); else slow(); }
    else if (e.shiftKey && (k === 'T' || k === 't')) themeB.click();
    else if (e.shiftKey && (k === 'L' || k === 'l') && L.tracked) layoutB.click();
    else if (k === 'Escape') setHot(null);
    else used = false;
    if (used) e.preventDefault();
  });
  master.addEventListener('ended', function () { if (S.playing) pause(); });

  // ------------------------------------------------------------------ meta: receipt and credit
  function trimEnd(s) { s = String(s); var n = s.length; while (n > 0 && /[.\s]/.test(s.charAt(n - 1))) n--; return s.slice(0, n); }
  function fillMeta() {
    meta.textContent = '';
    var n = kept.length;
    var rc = mk('p', { 'class': 'xl-receipt' }, meta);
    var det = L.detector || {}, fromData = det.engine === 'data';   // events from a data stream (xray import), not the sound
    rc.textContent = L.receipt || (n + ' ' + noun(n) + (fromData ? ' measured from the data' : ' measured from the clip’s sound') + ' (this page carries no verify receipt yet).');
    var drawn = L.drawn || (X && X.mech && X.mech.drawn) || 'The inside is drawn: a generic mechanism of this kind of object, not this exact one.';
    var how = L.measured || ('Measured: each ' + noun(1) + '’s frame, ' + (fromData
      ? 'from a data stream, not from the sound' + (det.note ? ' (' + trimEnd(det.note) + ')' : '') + '.'
      : 'from the clip’s own sound.'));
    mk('p', { 'class': 'xl-drawn' }, meta, how + ' ' + drawn);
    if (L.credit) mk('p', { 'class': 'xl-credit' }, meta, L.credit);
    mk('p', { 'class': 'xl-credit' }, meta, 'Sharing a live page shares what is in it: the prompt and the commands it shows, the whole xray block of showtime.json (its made.prompt and made.commands travel with the page even when --prompt shows another prompt), the source recording’s file name and fingerprint (sha256) and, for a film made from data, the events file’s name and fingerprint with its column names, labels and values.');
    // the line that made it: what to ask an agent, and the commands it runs (no local paths: placeholders)
    var made = L.made || {};
    if (made.prompt || (made.commands && made.commands.length)) {
      var box = mk('div', { 'class': 'xl-made' }, meta);
      mk('p', { 'class': 'xl-k' }, box, 'Make your own');
      if (made.prompt) field(box, 'Make your own with one line', made.prompt, 1);
      if (made.commands && made.commands.length) {
        var dt = mk('details', { 'class': 'xl-cmds' }, box);
        mk('summary', {}, dt, 'The commands it runs');
        field(dt, 'Commands', made.commands.join('\n'), made.commands.length);
        dt.addEventListener('toggle', postHeight);
      }
    }
  }

  // ------------------------------------------------------------------ start
  function metadata(v) {
    return new Promise(function (res) {
      if (v.readyState >= 1) return res();
      v.addEventListener('loadedmetadata', function () { res(); }, { once: true });
      v.addEventListener('error', function () { res(); }, { once: true });
      W.setTimeout(res, 15000);
    });
  }
  var readyResolve;
  var readyP = new Promise(function (r) { readyResolve = r; });
  fit();
  Promise.all([ST.ready(), metadata(master)]).then(function () {
    OFF = parseFloat(master.getAttribute('data-offset')) || 0;
    SFPS = parseFloat(master.getAttribute('data-fps')) || FPS;
    if (isFinite(master.duration) && master.duration > 0) CLIPDUR = master.duration;
    var filmLast = Math.max(0, Math.round((ST.info().duration || L.duration) * FPS) - 1);
    LAST = CLIPDUR > 0 ? Math.min(filmLast, Math.max(0, Math.floor((CLIPDUR - OFF) * FPS) - 1)) : filmLast;
    events = events || [];
    kept = events.filter(function (e) { return e.kind !== 'skip' && e.frame <= LAST; });
    buildTimeline(); fillMeta();
    var start;
    if (R.look.hit != null && kept[R.look.hit - 1]) start = kept[R.look.hit - 1].frame;
    else if (R.look.event != null && events[R.look.event]) start = events[R.look.event].frame;
    else if (R.look.t != null) start = Math.round(R.look.t * FPS);
    else {
      // the first event after the part names arrive (the inside is drawn and labelled), else the first one
      var labelsAt = ((W.CUE && W.CUE.labels) || 1.5) + 0.6;
      var e0 = kept.filter(function (e) { return e.frame / FPS >= labelsAt; })[0] || kept[0];
      start = e0 ? e0.frame : Math.round((L.poster || 0) * FPS);
    }
    fit();
    return go(start).then(function () {
      S.ready = true; veil.hidden = true;            // controls answer once the first frame is drawn
      buildParts(); buildPads(); fit(); paint(); readyResolve(state());
      if (kept.length && (!EMBED || !R.look.hit)) say(padBy === 'one' ? 'Click the picture to hear the next ' + noun(1) + ' · drag it to scrub'
        : padVerb + ': ' + (padBy === 'ch' ? 'press a key' : 'press a pad') + ' · drag the picture to scrub', 4200);
    });
  }).catch(function (e) {
    veil.hidden = false;
    veil.textContent = 'This page could not start: ' + (e && e.message || e);
    console.error('[xray live] ' + (e && e.message || e));
  });

  function state() {
    return { ready: S.ready, frame: S.f, t: S.f / FPS, playing: S.playing, rate: S.rate, slow: isSlow() || S.ending === 'slow', strike: (!!S.pass && S.pass.kind === 'hit') || S.ending === 'hit', last: LAST, fps: FPS,
      theme: root.getAttribute('data-xl-theme'), layout: DIAGRAM ? 'diagram' : curLayout, tracked: !!L.tracked, hot: hot,
      events: (events || []).map(function (e) { return { i: e.i, frame: e.frame, kind: e.kind, ch: e.ch }; }), kept: kept.map(function (e) { return e.i; }),
      kit: kitState, labels: hits.map(function (h) { return { name: h.name, x: h.x, y: h.y, w: h.w, h: h.h }; }), parts: partNames.slice(),
      clipTime: master.currentTime, restyle: !!(X && typeof X.restyle === 'function'), embed: EMBED,
      pads: { by: padBy, verb: padVerb, keys: pads.map(function (g) { return { key: g.key, label: g.label, n: g.list.length, keyName: g.keyName }; }) } };
  }
  W.xrayLive = {
    get ready() { return readyP; },
    state: state,
    seek: function (t) { return (S.playing ? pause() : Promise.resolve()).then(function () { return go(Math.round(t * FPS)); }).then(state); },
    jump: function (i) { var e = (events || [])[i]; return e ? jumpTo(e).then(state) : Promise.resolve(state()); },
    play: function () { play(); return state(); },
    pause: function () { return pause().then(state); },
    slow: function () { return slow().then(state); },
    strike: function (key) { var g = pads.filter(function (p) { return p.key === key; })[0] || pads[0]; return strike(g).then(state); },
    link: function () { return (pageUrl() || '') + hereHash(false); },
    theme: function (n) { return relook({ theme: n }); },
    layout: function (n) { return relook({ layout: n }); },
    hover: function (n) { setHot(n || null); return (S.going || S.busyP || Promise.resolve()).then(function () { return S.busyP; }).then(state); },
  };
})();

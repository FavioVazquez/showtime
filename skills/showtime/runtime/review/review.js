/* showtime review page (runtime/review/review.js): notes on a finished video.
 *
 * Plays the render (an MP4 in a <video>, or an HTML export in a same-origin frame through its
 * window.showtimePlayer API) under a notes layer: pause, then click a spot or drag a box on the picture and
 * type a note. Notes are saved through the local server (POST /api/note) into the job's
 * review/notes/notes.json; the agent reads them with `showtime review notes <job> --new` and replies there.
 * A note's time is the middle of the frame it was written on, so the page and the agent's frame image
 * show the same frame. Regions are in 0-1 units of the picture: {x, y} (a spot) or {x, y, w, h} (a box).
 * A note can also be about a stretch of time ({t, to}): Shift + drag on the bar, or [ at its start and ] at
 * its end (the Mark stretch button on a phone); it shows on the bar as a band.
 */
(function () {
  'use strict';
  var D = document, W = window;
  var $ = function (id) { return D.getElementById(id); };
  var clamp = function (x, a, b) { return x < a ? a : x > b ? b : x; };
  var CFG = JSON.parse($('rv-config').textContent);
  var notes = Array.isArray(CFG.notes) ? CFG.notes : [];
  var fps = Number(CFG.fps) || 30;
  var stage = $('stage'), layer = $('layer'), hint = $('hint'), scrub = $('scrub'), fillEl = $('fill'), knob = $('knob'), ticks = $('ticks');
  var timeEl = $('time'), composer = $('composer'), cText = $('cText'), cTitle = $('cTitle'), cWhere = $('cWhere'), cWhole = $('cWhole');
  var list = $('list'), empty = $('empty'), countEl = $('count'), summary = $('nSummary'), saved = $('saved'), banner = $('banner');

  $('title').textContent = CFG.title || 'Notes';
  var coarse = !!(W.matchMedia && W.matchMedia('(pointer: coarse)').matches);
  if (coarse) hint.textContent = 'Pause, then tap a spot or drag a box to add a note';
  $('media').textContent = CFG.media + (CFG.kind === 'export' ? ' (HTML export)' : '');

  // ------------------------------------------------------------------ the video (two kinds, one interface)
  function setAspect(w, h) { if (w > 0 && h > 0) stage.style.setProperty('--ar', String(w / h)); }
  setAspect(CFG.width, CFG.height);
  function containBox(w, h) {
    var sw = stage.clientWidth, sh = stage.clientHeight;
    if (!(w > 0 && h > 0)) return { x: 0, y: 0, w: sw, h: sh };
    var ar = w / h, bw = Math.min(sw, sh * ar), bh = bw / ar;
    return { x: (sw - bw) / 2, y: (sh - bh) / 2, w: bw, h: bh };
  }
  function videoSource() {
    var v = D.createElement('video');
    v.preload = 'auto'; v.playsInline = true; v.setAttribute('playsinline', ''); v.setAttribute('aria-hidden', 'true');
    v.src = '/video/' + encodeURIComponent(String(CFG.media || ''));   // the server's own route, never a URL from the page
    stage.insertBefore(v, layer);
    var s = {
      kind: 'video', el: v,
      ready: new Promise(function (res) {
        if (v.readyState >= 1) res();
        else v.addEventListener('loadedmetadata', function () { res(); }, { once: true });
      }),
      duration: function () { return isFinite(v.duration) && v.duration > 0 ? v.duration : (CFG.duration || 0); },
      t: function () { return v.currentTime || 0; },
      paused: function () { return v.paused || v.ended; },
      play: function () { if (v.ended) v.currentTime = 0; var p = v.play(); if (p && p.catch) p.catch(function () {}); },
      pause: function () { v.pause(); },
      seek: function (t) { v.currentTime = clamp(t, 0, Math.max(0, s.duration() - 0.25 / fps)); },
      box: function () { return containBox(v.videoWidth || CFG.width, v.videoHeight || CFG.height); },
    };
    v.addEventListener('loadedmetadata', function () { setAspect(v.videoWidth, v.videoHeight); update(); });
    ['play', 'pause', 'seeked', 'ended', 'timeupdate'].forEach(function (ev) { v.addEventListener(ev, update); });
    v.addEventListener('error', function () {
      showBanner('This browser could not play ' + CFG.media + '. Try another browser (Chrome, Edge, Safari or Firefox), or ask your agent for the HTML export (showtime review open <job> --html).');
    });
    return s;
  }
  function exportSource() {
    var f = D.createElement('iframe');
    f.title = 'video'; f.setAttribute('tabindex', '-1'); f.setAttribute('aria-hidden', 'true');
    f.src = '/export/' + encodeURIComponent(String(CFG.media || ''));   // the server's own route, never a URL from the page
    stage.insertBefore(f, layer);
    var P = null;
    var s = {
      kind: 'export', el: f,
      ready: new Promise(function (res, rej) {
        f.addEventListener('load', function () {
          var w, doc;
          try { w = f.contentWindow; doc = f.contentDocument; } catch (e) { rej(e); return; }
          if (!doc) { rej(new Error('the HTML export did not load')); return; }
          // the review page draws its own controls: the player's chrome stays hidden
          var st = doc.createElement('style');
          st.textContent = '.stp-bar,.stp-start,.stp-cover,.stp-unmute,.stp-info,.stp-toast,.stp-q,.stp-help,.stp-dev{display:none!important}';
          (doc.head || doc.documentElement).appendChild(st);
          var t0 = Date.now();
          (function wait() {
            if (w.showtimePlayer && w.showtimePlayer.ready && w.showtimePlayer.on) {
              P = w.showtimePlayer;
              P.ready.then(function () {
                ['play', 'pause', 'seek', 'ended', 'frame'].forEach(function (ev) { P.on(ev, update); });
                // a question stops the export: here it plays on through its own pause and think beat
                P.on('question', function () { P.play(); });
                P.seek(0).then(function () { res(); update(); });
              }, rej);
            } else if (Date.now() - t0 > 20000) rej(new Error('the HTML export has no player'));
            else setTimeout(wait, 50);
          })();
        });
      }),
      duration: function () { return P ? P.duration : (CFG.duration || 0); },
      t: function () { return P ? P.currentTime : 0; },
      paused: function () { return !P || P.paused; },
      play: function () { if (P) { if (P.ended) P.currentTime = 0; P.play(); } },
      pause: function () { if (P) P.pause(); },
      seek: function (t) { if (P) P.currentTime = clamp(t, 0, Math.max(0, P.duration - 0.25 / fps)); },
      box: function () {
        try {
          var h = f.contentDocument.querySelector('.stp-holder');
          var r = h.getBoundingClientRect();
          if (r.width > 0) return { x: r.left, y: r.top, w: r.width, h: r.height };
        } catch (e) { /* not ready */ }
        return containBox(CFG.width, CFG.height);
      },
    };
    return s;
  }
  var src = CFG.kind === 'export' ? exportSource() : videoSource();
  src.ready.then(function () { update(); renderTicks(); }, function (e) { showBanner('The video could not start: ' + (e && e.message || e)); });

  // ------------------------------------------------------------------ small helpers
  function fmt(t, tenths) {
    t = Math.max(0, t || 0);
    var m = Math.floor(t / 60), s = t - m * 60;
    var ss = tenths ? s.toFixed(1) : String(Math.floor(s));
    if (s < 10) ss = '0' + ss;
    return m + ':' + ss;
  }
  function frameOf(t) { return Math.floor(t * fps + 1e-4); }
  /** The middle of the frame shown at t: the page and the agent's frame image agree on it. */
  function frameMid(t) { return Math.round(((frameOf(t) + 0.5) / fps) * 1000) / 1000; }
  function num(n) { return String(n.id).replace(/^n/, ''); }
  function isRange(n) { return !!n && n.to !== undefined && n.to !== null; }
  function spanLabel(n) { return isRange(n) ? fmt(n.t, true) + '–' + fmt(n.to, true) : fmt(n.t, true); }
  function regionText(r) {
    if (!r) return 'whole frame';
    return r.w === undefined ? 'a spot' : 'a box';
  }
  function el(tag, cls, text) {
    var e = D.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function showBanner(text) { banner.textContent = text; banner.hidden = !text; }
  function toast(text, isError) {
    var t = el('div', 'toast' + (isError ? ' error' : ''), text);
    $('toasts').appendChild(t);
    setTimeout(function () { t.remove(); }, isError ? 6000 : 2200);
  }
  function setSaved(state, text) {
    saved.setAttribute('data-state', state);
    saved.lastChild.textContent = text;
  }

  // ------------------------------------------------------------------ server
  function api(body) {
    setSaved('busy', 'Saving...');
    return fetch('/api/note', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), credentials: 'same-origin' })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
          return j;
        });
      })
      .then(function (j) {
        notes = j.notes || notes;
        setSaved('ok', 'Saved on this computer');
        showBanner('');
        renderAll();
        return j;
      }, function (e) {
        var msg = String(e && e.message || e);
        if (/Failed to fetch|NetworkError|Load failed/i.test(msg)) {
          msg = 'The notes server is not running, so this was not saved. Ask your agent to run: showtime review open ' + (CFG.job || '<job>') + ', then reload.';
          showBanner(msg);
        }
        setSaved('error', 'Not saved');
        toast(msg, true);
        throw e;
      });
  }
  function refresh() {
    if (editing) return;
    fetch('/api/notes', { credentials: 'same-origin' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (j) {
      if (j && Array.isArray(j.notes) && JSON.stringify(j.notes) !== JSON.stringify(notes)) { notes = j.notes; renderAll(); }
    }, function () { /* offline: keep what is shown */ });
  }
  D.addEventListener('visibilitychange', function () { if (D.visibilityState === 'visible') refresh(); });
  W.addEventListener('focus', refresh);

  // ------------------------------------------------------------------ boxes on the picture
  var sel = null;           // selected note id
  var draft = null;         // {t, region} of the note being written
  var editing = null;       // id of the note being edited in the list
  function place(e, r, b) {
    if (r.w === undefined) {
      e.classList.add('spot');
      e.style.left = (b.x + r.x * b.w) + 'px'; e.style.top = (b.y + r.y * b.h) + 'px';
    } else {
      e.style.left = (b.x + r.x * b.w) + 'px'; e.style.top = (b.y + r.y * b.h) + 'px';
      e.style.width = Math.max(4, r.w * b.w) + 'px'; e.style.height = Math.max(4, r.h * b.h) + 'px';
    }
  }
  function drawBoxes() {
    while (layer.firstChild) layer.removeChild(layer.firstChild);
    var b = src.box();
    if (draft && draft.region) {
      var d = el('div', 'box draft');
      place(d, draft.region, b);
      layer.appendChild(d);
    }
    if (!src.paused()) return;
    var f = frameOf(src.t());
    notes.forEach(function (n) {
      if (!n.region || frameOf(n.t) !== f || (draft && draft.editId === n.id)) return;
      var e = el('div', 'box' + (n.video && n.video !== CFG.media ? ' old' : ''));
      e.appendChild(el('b', null, num(n)));
      place(e, n.region, b);
      layer.appendChild(e);
    });
  }

  // ------------------------------------------------------------------ transport
  var lastUI = '';
  function update() {
    var t = src.t(), dur = src.duration(), playing = !src.paused();
    D.body.classList.toggle('is-playing-ui', playing);
    stage.classList.toggle('is-playing', playing);
    $('playBtn').setAttribute('aria-label', playing ? 'Pause (space)' : 'Play (space)');
    var p = dur > 0 ? clamp(t / dur, 0, 1) : 0;
    fillEl.style.width = (p * 100) + '%';
    knob.style.left = (p * 100) + '%';
    timeEl.firstChild.textContent = fmt(t, true);
    timeEl.lastChild.textContent = '/ ' + fmt(dur);
    scrub.setAttribute('aria-valuemax', dur.toFixed(1));
    scrub.setAttribute('aria-valuenow', t.toFixed(1));
    scrub.setAttribute('aria-valuetext', fmt(t, true) + ' of ' + fmt(dur));
    var key = [frameOf(t), playing, stage.clientWidth, stage.clientHeight, notes.length, draft ? JSON.stringify(draft) : ''].join('|');
    if (key !== lastUI) { lastUI = key; drawBoxes(); }
    drawDraftBand();
    if (playStop !== null && playing && t >= playStop - 0.5 / fps) { playStop = null; src.pause(); seek(t); }
  }
  (function loop() { if (!src.paused()) update(); W.requestAnimationFrame(loop); })();
  if (W.ResizeObserver) new ResizeObserver(function () { lastUI = ''; update(); }).observe(stage);
  function toggle() { playStop = null; if (src.paused()) src.play(); else src.pause(); update(); }
  function seek(t) { src.seek(t); setTimeout(update, 0); }
  function stepFrame(k) { if (!src.paused()) src.pause(); seek((frameOf(src.t()) + k + 0.5) / fps); }
  $('playBtn').addEventListener('click', toggle);
  $('backBtn').addEventListener('click', function () { stepFrame(-1); });
  $('fwdBtn').addEventListener('click', function () { stepFrame(1); });
  $('addBtn').addEventListener('click', function () { newNote(draft && draft.region || null); });

  function scrubT(e) { var r = scrub.getBoundingClientRect(); return clamp((e.clientX - r.left) / r.width, 0, 1) * src.duration(); }
  var scrubbing = false;
  var pick = null;          // shift + drag on the bar: {from, to, at, x, moved} (as the HTML player's range links)
  scrub.addEventListener('pointerdown', function (e) {
    try { scrub.setPointerCapture(e.pointerId); } catch (x) { /* ignore */ }
    playStop = null;
    if (!src.paused()) src.pause();
    if (e.shiftKey) { var t0 = scrubT(e); pick = { from: t0, to: t0, at: src.t(), x: e.clientX, moved: false }; return; }
    scrubbing = true;
    seek(scrubT(e));
  });
  scrub.addEventListener('pointermove', function (e) {
    if (pick) { pick.to = scrubT(e); if (Math.abs(e.clientX - pick.x) > 4) pick.moved = true; drawDraftBand(); return; }
    if (scrubbing) seek(scrubT(e));
  });
  ['pointerup', 'pointercancel'].forEach(function (ev) {
    scrub.addEventListener(ev, function (e) {
      scrubbing = false;
      if (!pick) return;
      var p = pick;
      pick = null;
      if (e.type === 'pointercancel') { drawDraftBand(); return; }
      // dragged: that stretch; a shift + click: from the playhead to the click
      var a = p.moved ? Math.min(p.from, p.to) : Math.min(p.at, p.from);
      var b = p.moved ? Math.max(p.from, p.to) : Math.max(p.at, p.from);
      if (b - a >= MIN_STRETCH) newStretch(a, b);
      else { drawDraftBand(); toast('Drag along the bar for a stretch of ' + MIN_STRETCH.toFixed(2) + ' s or more', true); }
    });
  });
  function renderTicks() {
    var dur = src.duration();
    ticks.innerHTML = '';
    if (!(dur > 0)) return;
    var pc = function (t) { return (100 * clamp(t / dur, 0, 1)).toFixed(3) + '%'; };
    notes.forEach(function (n) {
      if (isRange(n)) {   // a stretch: a band under the frame notes' ticks
        var bd = el('span', 'band' + (n.status === 'open' ? '' : ' ' + n.status));
        bd.style.left = pc(n.t);
        bd.style.width = (100 * clamp((n.to - n.t) / dur, 0.004, 1)).toFixed(3) + '%';
        bd.title = '#' + num(n) + ' from ' + fmt(n.t, true) + ' to ' + fmt(n.to, true);
        ticks.insertBefore(bd, ticks.firstChild);
        return;
      }
      var i = el('i', n.status === 'open' ? '' : n.status);
      i.style.left = pc(n.t);
      i.title = '#' + num(n) + ' at ' + fmt(n.t, true);
      ticks.appendChild(i);
    });
    ticks.appendChild(dband);
    drawDraftBand();
  }

  // ------------------------------------------------------------------ stretches of time
  var MIN_STRETCH = Math.max(0.25, 2 / fps);
  var mark = null;          // {from}: a stretch's start ([ or Mark stretch), waiting for its end
  var playStop = null;      // Play stretch: pause at this time
  var dband = el('span', 'band draft');
  dband.hidden = true;
  /** The stretch being picked or written: a dashed band on the bar. */
  function drawDraftBand() {
    var dur = src.duration(), r = null;
    if (pick && pick.moved) r = [Math.min(pick.from, pick.to), Math.max(pick.from, pick.to)];
    else if (mark) r = [Math.min(mark.from, src.t()), Math.max(mark.from, src.t())];
    else if (draft && isRange(draft)) r = [draft.t, draft.to];
    if (!r || !(dur > 0)) { dband.hidden = true; return; }
    if (dband.parentNode !== ticks) ticks.appendChild(dband);
    dband.hidden = false;
    dband.style.left = (100 * clamp(r[0] / dur, 0, 1)).toFixed(3) + '%';
    dband.style.width = Math.max(0.4, 100 * clamp((r[1] - r[0]) / dur, 0, 1)).toFixed(3) + '%';
  }
  function syncMarkBtn() {
    var b = $('rangeBtn');
    b.textContent = mark ? 'End stretch' : 'Mark stretch';
    b.classList.toggle('is-marking', !!mark);
    b.title = mark ? 'End the stretch here and write a note on it (])' : 'Mark the start of a stretch of time ([)';
  }
  function markStart() {   // playing on is fine: the band grows with the playhead, and End stretch pauses
    mark = { from: src.t() };
    syncMarkBtn();
    toast('Stretch starts at ' + fmt(mark.from, true) + '. Go to where it ends, then End stretch' + (coarse ? '' : ' (or ])'));
    update();
  }
  function markEnd() {
    if (!mark) { toast('Mark where the stretch starts first ([ or Mark stretch)', true); return; }
    var a = Math.min(mark.from, src.t()), b = Math.max(mark.from, src.t());
    if (b - a < MIN_STRETCH) { toast('Go to where the stretch ends first (' + MIN_STRETCH.toFixed(2) + ' s or more from its start)', true); return; }
    newStretch(a, b);
  }
  function cancelMark() { mark = null; syncMarkBtn(); update(); }
  /** Open the composer for a note on the stretch from a to b (each the middle of its frame). */
  function newStretch(a, b) {
    if (!src.paused()) src.pause();
    mark = null;
    syncMarkBtn();
    var A = frameMid(a), B = Math.max(A + MIN_STRETCH, frameMid(b));
    var dur = src.duration();
    if (dur > 0) B = Math.min(B, dur);
    draft = { t: A, to: B, region: null };
    cTitle.textContent = 'New note from ' + fmt(A, true) + ' to ' + fmt(B, true);
    cWhere.textContent = '· a stretch of ' + (B - A).toFixed(1) + ' s';
    cWhole.hidden = true;
    composer.hidden = false;
    stage.classList.add('has-draft');
    seek(A);
    lastUI = ''; update();
    cText.focus({ preventScroll: true });
    if (composer.scrollIntoView && W.innerWidth < 900) composer.scrollIntoView({ block: 'nearest' });
  }
  $('rangeBtn').addEventListener('click', function () { if (mark) markEnd(); else markStart(); });

  // ------------------------------------------------------------------ pointing at the picture
  var drag = null;
  function at(e) {
    var r = layer.getBoundingClientRect(), b = src.box();
    return { x: clamp((e.clientX - r.left - b.x) / b.w, 0, 1), y: clamp((e.clientY - r.top - b.y) / b.h, 0, 1), px: e.clientX, py: e.clientY };
  }
  layer.addEventListener('pointerdown', function (e) {
    if (e.button) return;
    if (!src.paused()) { src.pause(); update(); return; }   // a click on a playing video pauses it
    e.preventDefault();
    drag = { a: at(e), moved: false, id: e.pointerId };
    try { layer.setPointerCapture(e.pointerId); } catch (x) { /* ignore */ }
    stage.classList.add('is-drawing');
  });
  function dragRegion(a, b) {
    var x = Math.min(a.x, b.x), y = Math.min(a.y, b.y);
    return { x: x, y: y, w: Math.max(0.005, Math.abs(a.x - b.x)), h: Math.max(0.005, Math.abs(a.y - b.y)) };
  }
  layer.addEventListener('pointermove', function (e) {
    if (!drag || e.pointerId !== drag.id) return;
    var p = at(e);
    if (!drag.moved && Math.abs(p.px - drag.a.px) + Math.abs(p.py - drag.a.py) < 7) return;
    drag.moved = true;
    var r = dragRegion(drag.a, p);
    draft = draft || { t: frameMid(src.t()) };
    draft.region = r;
    update();
  });
  function endDrag(e) {
    if (!drag || (e && e.pointerId !== drag.id)) return;
    var p = e && e.type === 'pointerup' ? at(e) : drag.a;
    var region = drag.moved ? dragRegion(drag.a, p) : { x: drag.a.x, y: drag.a.y };
    drag = null;
    stage.classList.remove('is-drawing');
    if (e && e.type === 'pointercancel') { update(); return; }
    newNote(round(region));
  }
  layer.addEventListener('pointerup', endDrag);
  layer.addEventListener('pointercancel', endDrag);
  function round(r) {
    if (!r) return null;
    var o = {};
    Object.keys(r).forEach(function (k) { o[k] = Math.round(r[k] * 10000) / 10000; });
    return o;
  }

  // ------------------------------------------------------------------ writing a note
  /** Open the composer at the current frame (keeps typed text when the region changes). */
  function newNote(region) {
    if (!src.paused()) src.pause();
    var t = frameMid(src.t());
    var keep = !composer.hidden && draft && !draft.editId;
    if (keep && isRange(draft)) draft = { t: t, region: null };   // pointing at the picture: a note on this frame
    mark = null; syncMarkBtn();
    draft = { t: keep ? draft.t : t, region: region || null };
    if (keep && Math.abs(draft.t - t) > 0.5 / fps) draft.t = t;
    cTitle.textContent = 'New note at ' + fmt(draft.t, true);
    cWhere.textContent = '· ' + regionText(draft.region);
    cWhole.hidden = !draft.region;
    composer.hidden = false;
    stage.classList.add('has-draft');
    update();
    cText.focus({ preventScroll: true });
    if (composer.scrollIntoView && W.innerWidth < 900) composer.scrollIntoView({ block: 'nearest' });
  }
  function closeComposer() {
    draft = null;
    composer.hidden = true;
    cText.value = '';
    stage.classList.remove('has-draft');
    lastUI = ''; update();
  }
  cWhole.addEventListener('click', function () { if (draft) { draft.region = null; cWhere.textContent = '· whole frame'; cWhole.hidden = true; lastUI = ''; update(); cText.focus(); } });
  $('cCancel').addEventListener('click', closeComposer);
  composer.addEventListener('submit', function (e) {
    e.preventDefault();
    var text = cText.value.trim();
    if (!text) { toast('Type what should change first', true); cText.focus(); return; }
    if (!draft) return;
    var body = { op: 'add', t: draft.t, region: draft.region, text: text };
    if (isRange(draft)) body.to = draft.to;
    $('cSave').disabled = true;
    api(body).then(function (j) {
      closeComposer();
      sel = j.note && j.note.id;
      renderAll();
      toast('Note #' + num(j.note) + ' saved');
    }, function () { /* kept in the composer */ }).then(function () { $('cSave').disabled = false; });
  });
  cText.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); composer.requestSubmit ? composer.requestSubmit() : composer.dispatchEvent(new Event('submit', { cancelable: true })); }
    else if (e.key === 'Escape') { e.preventDefault(); closeComposer(); }
  });

  // ------------------------------------------------------------------ the list
  var confirming = null;
  function renderAll() { renderList(); renderTicks(); lastUI = ''; update(); }
  function statusLabel(s) { return s === 'done' ? 'Done' : s === 'wontfix' ? 'Kept as is' : 'Open'; }
  function renderList() {
    // a re-render (a late save reply, a refresh) keeps the note being edited as it is: its text, caret and focus
    var old = editing ? list.querySelector('[data-id="' + editing + '"] textarea') : null;
    var kept = old ? { v: old.value, a: old.selectionStart, b: old.selectionEnd, focus: D.activeElement === old } : null;
    list.innerHTML = '';
    countEl.textContent = String(notes.length);
    empty.hidden = notes.length > 0;
    var open = notes.filter(function (n) { return n.status === 'open'; }).length;
    var answered = notes.filter(function (n) { return n.reply; }).length;
    summary.textContent = notes.length ? open + ' open' + (answered ? ' · ' + answered + ' answered' : '') : '';
    notes.forEach(function (n) {
      var li = el('li', 'note st-' + n.status + (n.id === sel ? ' sel' : ''));
      li.tabIndex = 0;
      li.setAttribute('data-id', n.id);
      li.setAttribute('aria-label', 'Note ' + num(n) + (isRange(n) ? ' from ' + fmt(n.t, true) + ' to ' + fmt(n.to, true) : ' at ' + fmt(n.t, true)));
      var h = el('div', 'nh');
      h.appendChild(el('span', 'num', '#' + num(n)));
      var at = el('button', 'at', spanLabel(n));
      at.type = 'button'; at.title = isRange(n) ? 'Go to the start of this stretch' : 'Go to this frame'; at.setAttribute('data-act', 'go');
      h.appendChild(at);
      h.appendChild(el('span', 'where', isRange(n) ? 'a stretch of ' + (n.to - n.t).toFixed(1) + ' s' + (n.region ? ' · ' + regionText(n.region) : '') : regionText(n.region)));
      if (n.author === 'agent') h.appendChild(el('span', 'chip agent', 'From your agent'));
      h.appendChild(el('span', 'chip' + (n.status === 'done' ? ' done' : ''), statusLabel(n.status)));
      li.appendChild(h);
      if (n.video && n.video !== CFG.media) li.appendChild(el('div', 'other', 'Written on ' + n.video + ' (an earlier render)'));
      if (editing === n.id) {
        var ta = el('textarea');
        ta.value = kept ? kept.v : n.text; ta.maxLength = 2000; ta.setAttribute('aria-label', 'Edit note ' + num(n));
        li.appendChild(ta);
        var ea = el('div', 'na');
        ea.appendChild(btn('Save', 'save-edit', 'primary small'));
        ea.appendChild(btn('Cancel', 'cancel-edit', 'ghost small'));
        li.appendChild(ea);
        ta.addEventListener('keydown', function (e) {
          if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); saveEdit(n.id, ta.value); }
          else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); editing = null; renderList(); focusNote(n.id); }
        });
        // after this render has put the textarea in the page (a detached element cannot take focus)
        if (kept) { if (kept.focus) Promise.resolve().then(function () { ta.focus({ preventScroll: true }); ta.setSelectionRange(kept.a, kept.b); }); }
        else setTimeout(function () { ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); }, 0);
      } else li.appendChild(el('p', 'nt', n.text));
      if (n.reply) {
        var rp = el('div', 'reply');
        rp.appendChild(el('strong', null, 'Your agent replied'));
        rp.appendChild(D.createTextNode(n.reply));
        li.appendChild(rp);
      }
      if (editing !== n.id) {
        var a = el('div', 'na');
        if (confirming === n.id) {
          a.appendChild(el('span', 'confirm', 'Delete this note?'));
          a.appendChild(btn('Delete', 'delete-yes', 'small danger'));
          a.appendChild(btn('Keep', 'delete-no', 'ghost small'));
        } else {
          if (isRange(n)) a.appendChild(btn('Play stretch', 'play-range', 'ghost small'));
          if (n.author === 'person') a.appendChild(btn('Edit', 'edit', 'ghost small'));
          a.appendChild(n.status === 'open' ? btn('Mark done', 'done', 'ghost small') : btn('Reopen', 'reopen', 'ghost small'));
          if (n.author === 'person') a.appendChild(btn('Delete', 'delete', 'ghost small danger'));
        }
        li.appendChild(a);
      }
      list.appendChild(li);
    });
  }
  function btn(text, act, cls) {
    var b = el('button', 'btn ' + (cls || ''), text);
    b.type = 'button'; b.setAttribute('data-act', act);
    return b;
  }
  function noteById(id) { for (var i = 0; i < notes.length; i++) if (notes[i].id === id) return notes[i]; return null; }
  function focusNote(id) { var e = list.querySelector('[data-id="' + id + '"]'); if (e) e.focus({ preventScroll: false }); }
  function selectNote(id, go) {
    sel = id;
    Array.prototype.forEach.call(list.children, function (li) { li.classList.toggle('sel', li.getAttribute('data-id') === id); });
    var n = noteById(id);
    if (n && go) { if (!src.paused()) src.pause(); seek(n.t); }
  }
  function saveEdit(id, text) {
    if (!text.trim()) { toast('A note needs some words (or delete it)', true); return; }
    api({ op: 'edit', id: id, text: text }).then(function () { editing = null; renderList(); focusNote(id); toast('Note #' + id.replace(/^n/, '') + ' changed'); }, function () {});
  }
  list.addEventListener('click', function (e) {
    var li = e.target.closest('.note');
    if (!li) return;
    var id = li.getAttribute('data-id');
    var b = e.target.closest('[data-act]');
    var act = b ? b.getAttribute('data-act') : 'select';
    if (act === 'select' || act === 'go') { if (!(e.target.closest('textarea'))) selectNote(id, true); return; }
    if (act === 'edit') { editing = id; confirming = null; selectNote(id, true); renderList(); }
    else if (act === 'cancel-edit') { editing = null; renderList(); focusNote(id); }
    else if (act === 'save-edit') saveEdit(id, li.querySelector('textarea').value);
    else if (act === 'delete') { confirming = id; renderList(); var y = list.querySelector('[data-act="delete-yes"]'); if (y) y.focus(); }
    else if (act === 'delete-no') { confirming = null; renderList(); focusNote(id); }
    else if (act === 'delete-yes') api({ op: 'delete', id: id }).then(function () { confirming = null; if (sel === id) sel = null; renderAll(); toast('Note deleted'); }, function () {});
    else if (act === 'play-range') { var pr = noteById(id); if (pr && isRange(pr)) { selectNote(id, false); seek(pr.t); playStop = pr.to; src.play(); update(); } }
    else if (act === 'done' || act === 'reopen') api({ op: 'status', id: id, status: act === 'done' ? 'done' : 'open' }).then(function () { focusNote(id); }, function () {});
  });

  // ------------------------------------------------------------------ keys
  function moveSel(k) {
    if (!notes.length) return;
    var i = -1;
    for (var j = 0; j < notes.length; j++) if (notes[j].id === sel) i = j;
    if (i < 0) {   // nothing selected: the next note after (or the last before) the playhead
      var t = src.t();
      i = k > 0 ? notes.findIndex(function (n) { return n.t > t + 0.5 / fps; }) : -1;
      if (k < 0) for (var q = notes.length - 1; q >= 0; q--) if (notes[q].t < t - 0.5 / fps) { i = q; break; }
      if (i < 0) i = k > 0 ? 0 : notes.length - 1;
    } else i = clamp(i + k, 0, notes.length - 1);
    selectNote(notes[i].id, true);
    focusNote(notes[i].id);
  }
  D.addEventListener('keydown', function (e) {
    if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
    var tg = e.target && e.target.tagName;
    if (tg === 'TEXTAREA' || tg === 'INPUT' || $('keysDlg').open) return;
    var k = e.key, lower = k.length === 1 ? k.toLowerCase() : k, handled = true;
    if (k === ' ' || lower === 'k') { if (k === ' ' && tg === 'BUTTON') return; toggle(); }
    else if (k === 'ArrowLeft') seek(src.t() - (e.shiftKey ? 5 : 1));
    else if (k === 'ArrowRight') seek(src.t() + (e.shiftKey ? 5 : 1));
    else if (k === ',' || k === '<') stepFrame(-1);
    else if (k === '.' || k === '>') stepFrame(1);
    else if (lower === 'n') newNote(draft && draft.region || null);
    else if (k === '[') markStart();
    else if (k === ']') markEnd();
    else if (lower === 'j') moveSel(-1);
    else if (lower === 'l') moveSel(1);
    else if (lower === 'e' && sel) { var n = noteById(sel); if (n && n.author === 'person') { editing = sel; renderList(); } }
    else if ((k === 'Delete' || k === 'Backspace') && sel && tg !== 'BUTTON') { var m = noteById(sel); if (m && m.author === 'person') { confirming = sel; renderList(); var y = list.querySelector('[data-act="delete-yes"]'); if (y) y.focus(); } }
    else if (k === 'Enter' && e.target.classList && e.target.classList.contains('note')) selectNote(e.target.getAttribute('data-id'), true);
    else if (k === '?') $('keysDlg').showModal();
    else if (k === 'Escape') { if (!composer.hidden) closeComposer(); else if (mark) cancelMark(); else if (confirming) { confirming = null; renderList(); } else if (sel) { sel = null; renderList(); } else handled = false; }
    else handled = false;
    if (handled) e.preventDefault();
  });
  $('keysBtn').addEventListener('click', function () { $('keysDlg').showModal(); });

  // ------------------------------------------------------------------ start
  renderList();
  update();
  W.reviewPage = {   // for tests and for a person who wants to script it from the console
    get notes() { return notes.slice(); },
    get time() { return src.t(); },
    get paused() { return src.paused(); },
    get box() { return src.box(); },
    ready: src.ready,
    seek: function (t) { src.pause(); seek(t); },
    get marking() { return mark ? mark.from : null; },
    refresh: refresh,
    render: renderAll,
  };
})();

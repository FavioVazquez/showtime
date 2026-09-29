/* showtime studio board: page script. Plain JS, no dependencies, nothing loaded from the network.
 * Fixed template: the agent fills board.json; this file is never edited per job.
 *
 * Modes (meta st-mode):
 *   live    served by `showtime studio open`: clicks POST to ./api/feedback, updates arrive over ./api/events (SSE)
 *   static  board.html opened from disk: reactions stay in this browser (localStorage) + "Copy for your agent"
 *   export  single-file copy for publishing: like static, never touches the network
 */
(function () {
  'use strict';
  var Core = window.StudioCore;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var META_MODE = (document.querySelector('meta[name="st-mode"]') || {}).content || 'static';
  var META_JOB = (document.querySelector('meta[name="st-job"]') || {}).content || '';
  // hosted: shown inside a host's sandboxed frame (an HTML artifact viewer), where file downloads are
  // blocked; `studio export --target artifact` bakes it in, otherwise it is detected
  var HOSTED = (document.querySelector('meta[name="st-host"]') || {}).content === 'artifact' || detectHosted();
  function detectHosted() {
    var inFrame = true;
    try { inFrame = window.self !== window.top; } catch (e) { inFrame = true; }
    if (!inFrame) return false;
    var origin = '';
    try { origin = String(window.origin !== undefined ? window.origin : location.origin); } catch (e) { origin = 'null'; }   // 'null' when sandboxed
    if (origin === 'null') return true;
    var names = [];
    try { names.push(location.hostname); } catch (e) { /* ignore */ }
    try { var ao = location.ancestorOrigins; for (var i = 0; ao && i < ao.length; i++) names.push(ao[i]); } catch (e) { /* ignore */ }
    try { names.push(document.referrer); } catch (e) { /* ignore */ }
    return names.some(function (n) { return /(^|[./])(claude\.ai|claudeusercontent\.com|anthropic\.com)(?=$|[:/])/i.test(String(n || '')); });
  }

  var ICON = {
    heart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1.1L12 21l7.8-7.5 1-1.1a5.5 5.5 0 0 0 0-7.8z"/></svg>',
    star: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.8l2.8 5.9 6.4.8-4.7 4.4 1.2 6.4L12 17.2l-5.7 3.1 1.2-6.4-4.7-4.4 6.4-.8z"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>',
    chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    mix: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5"/></svg>',
    play: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 4v16l13-8z"/></svg>',
    pause: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></svg>',
    left: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg>',
    right: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" aria-hidden="true"><path d="m9 18 6-6-6-6"/></svg>'
  };
  var PHASE_LABEL = { discover: 'Discover', concepts: 'Concepts', look: 'Look', sound: 'Sound', storyboard: 'Storyboard', animatic: 'Animatic', lock: 'Lock', build: 'Build', review: 'Review' };

  var S = {
    board: null, events: [], state: Core.reduce([]), live: false, rev: 0, client: null,
    ui: { focus: 0, frame: {}, sb: null, an: null, cmpA: null, cmpB: null, wipe: 50 },
    audio: {}, activeGroup: null, anim: null, lostAt: 0, lostTimer: null
  };

  // ---------------------------------------------------------------- utils
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function isMissing(src) { return !src || /^missing:/.test(src); }
  // A file left out of a shared copy (over the 16 MB page budget). Inside a host's frame (an artifact
  // viewer) nothing can be downloaded or opened from the page, so name the file and where it lives on
  // the computer that made the board; local and served boards keep the short note.
  function missingText(src, short) {
    var p = String(src || '').replace(/^missing:/, '');
    if (!HOSTED || !/^media\//.test(p)) return short;
    return p.split('/').pop() + ' is not in this shared copy (too large for one page). It is in the job folder on the computer that made the board: studio/' + p;
  }
  // Inline video/audio (a shared single-file board) plays from a blob: URL: iOS Safari refuses or stalls on
  // large data: media sources, and some hosts' frames block them. Images stay data: (they work everywhere).
  var BLOBS = {};
  function blobFor(src) {
    if (BLOBS[src]) return BLOBS[src];
    try {
      var m = /^data:([^;,]+)(;base64)?,/.exec(src), body = src.slice(m[0].length), bin = m[2] ? atob(body) : decodeURIComponent(body);
      var u8 = new Uint8Array(bin.length); for (var i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
      return (BLOBS[src] = URL.createObjectURL(new Blob([u8], { type: m[1] })));
    } catch (e) { return src; }
  }
  function media(src) {
    if (isMissing(src)) return '';
    if (/^data:(video|audio)\//.test(src)) return blobFor(src);
    if (/^(data:|blob:)/.test(src)) return src;
    if (!/^media\//.test(src)) return ''; // the page only loads files from studio/media/
    return S.live ? src + (src.indexOf('?') < 0 ? '?' : '&') + 'r=' + S.rev : src;
  }
  function fmt(t) { return Core.fmtT(t); }
  function storageWorks() {
    try { var k = '__st_probe'; localStorage.setItem(k, '1'); var ok = localStorage.getItem(k) === '1'; localStorage.removeItem(k); return ok; } catch (e) { return false; }
  }
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } return null; }
  function sstore(k, v) { try { if (v === undefined) return sessionStorage.getItem(k); sessionStorage.setItem(k, v); } catch (e) { return null; } return null; }
  function toast(msg) {
    var el = document.createElement('div'); el.className = 'toast'; el.textContent = msg;
    $('#toasts').appendChild(el); setTimeout(function () { el.remove(); }, 2800);
  }
  function concepts() { return (S.board && Array.isArray(S.board.concepts)) ? S.board.concepts : []; }
  function conceptById(id) { return concepts().filter(function (c) { return c.id === id; })[0]; }
  function tag(c) { return Core.tagOf(c, concepts().indexOf(c)); }
  function labelOf(id) { var idx = Core.index(S.board); return idx[id] ? idx[id].label : id; }
  // text fields take the keys; a range (the Compare wipe), checkbox or radio keeps focus after a click
  // but types nothing, so the board's shortcuts still work there
  var NON_TEXT_INPUTS = /^(range|checkbox|radio|button|submit|reset|color|file|image)$/i;
  function isTyping(e) {
    var t = e.target;
    if (!t) return false;
    if (t.tagName === 'INPUT') return !NON_TEXT_INPUTS.test(t.type || 'text');
    return t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || !!t.isContentEditable;
  }
  function clientId() {
    var id = sstore('st-client');
    if (!id) {
      id = (matchMedia('(pointer: coarse)').matches ? 'phone-' : 'desk-') + Math.random().toString(36).slice(2, 6);
      sstore('st-client', id);
    }
    return id;
  }
  function jobName() { return (S.board && S.board.job) || META_JOB || 'board'; }

  // ---------------------------------------------------------------- data flow
  function localKey() { return 'st-studio:' + jobName(); }
  function setEvents(evs) { S.events = evs || []; S.state = Core.reduce(S.events); syncState(); }

  function send(input) {
    input.rev = S.rev; input.client = S.client;
    var ev;
    try { ev = Core.makeEvent(input, { board: S.board }); } catch (err) { toast(err.message); return null; }
    S.events.push(ev); S.state = Core.reduce(S.events); syncState();
    if (!S.live) { store(localKey(), JSON.stringify(S.events)); return ev; }
    setConn('saving', 'Saving');
    post(ev).then(function () { setConn('live', 'Live'); flushOutbox(); })
      .catch(function (err) {
        if (err && err.status && err.status < 500) { toast('Not saved: ' + err.message); dropLocal(ev.id); setConn('live', 'Live'); return; }
        queue(ev); setConn('offline', 'Offline, will retry');
      });
    return ev;
  }
  function dropLocal(id) { setEvents(S.events.filter(function (e) { return e.id !== id; })); }
  function post(ev) {
    return fetch('api/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(ev), credentials: 'same-origin' })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (j) {
          if (!r.ok) { var e = new Error(j.error || ('HTTP ' + r.status)); e.status = r.status; throw e; }
          return j;
        });
      });
  }
  function outboxKey() { return 'st-outbox:' + jobName(); }
  function queue(ev) { var q = []; try { q = JSON.parse(store(outboxKey()) || '[]'); } catch (e) {} q.push(ev); store(outboxKey(), JSON.stringify(q)); }
  function flushOutbox() {
    var q = []; try { q = JSON.parse(store(outboxKey()) || '[]'); } catch (e) {}
    if (!q.length) return;
    store(outboxKey(), '[]');
    q.reduce(function (p, ev) { return p.then(function () { return post(ev).catch(function (e) { if (!e.status || e.status >= 500) throw e; }); }); }, Promise.resolve())
      .catch(function () { q.forEach(queue); });
  }
  function setConn(state, text) { var c = $('#conn'); c.dataset.state = state; c.lastElementChild.textContent = text; }
  function banner(html) { var b = $('#banner'); if (!html) { b.hidden = true; b.innerHTML = ''; return; } b.innerHTML = '<div>' + html + '</div>'; b.hidden = false; }

  function loadBoardEmbedded() { try { return JSON.parse($('#board-data').textContent); } catch (e) { return null; } }
  function fetchJSON(u) {
    return fetch(u, { cache: 'no-store', credentials: 'same-origin' }).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); });
  }

  function boot() {
    S.client = clientId();
    applyTheme(store('st-theme'));
    S.board = loadBoardEmbedded();
    var probe = META_MODE === 'live' && /^https?:$/.test(location.protocol)
      ? fetchJSON('api/health').then(function (h) { return !!(h && h.studio === true); }).catch(function () { return false; })
      : Promise.resolve(false);
    probe.then(function (live) {
      S.live = live;
      if (!live) return startStatic();
      $('#modeNote').textContent = 'Live: every click is saved to studio/feedback.json on this computer. Your agent reads it when you say you are done (or runs: showtime studio feedback).';
      return resync().then(function () { setConn('live', 'Live'); flushOutbox(); listen(); });
    });
  }
  function startStatic() {
    S.rev = (S.board && S.board.rev) || 0;
    var saved = null; try { saved = JSON.parse(store(localKey()) || 'null'); } catch (e) {}
    renderAll(); setEvents(Array.isArray(saved) ? saved : []);
    setConn('static', META_MODE === 'export' ? 'Shared copy' : 'Static');
    var note = 'Your reactions are kept in this browser only. When you are done, press "Copy for your agent" and paste the text into your chat.';
    // the marked regions below hold the feedback-file download; `studio export --target artifact` removes them from the file
    /*ST:DL*/
    if (!HOSTED) note = 'Your reactions are kept in this browser only. Press "Copy for your agent" and paste the text into your chat, or download feedback.json and give it to your agent (showtime studio feedback <job> --import feedback.json).';
    if ($('#dlBtn')) $('#dlBtn').hidden = HOSTED;   // downloads do not work inside a host's sandboxed frame
    /*ST:/DL*/
    // a host's frame may not keep this page's storage: then reactions last only until a reload
    if (HOSTED && !storageWorks()) note = 'This viewer does not keep your reactions if the page reloads: press "Copy for your agent" and paste the text into your chat before you leave.';
    $('#modeNote').textContent = (META_MODE === 'export' ? 'Shared copy of the board. ' : 'Offline copy. ') + note;
    if (HOSTED) document.documentElement.setAttribute('data-hosted', '');
    if (META_MODE === 'live') banner('The studio server is not running, so this page is a read-only snapshot. Restart it with <code>showtime studio open ' + esc(jobName()) + '</code>');
  }
  function resync() {
    return Promise.all([fetchJSON('board.json'), fetchJSON('api/feedback')]).then(function (r) {
      var first = !S.board || S.rev !== (r[0].rev || 0) || !$('#main').children.length;
      S.board = r[0]; S.rev = S.board.rev || 0;
      if (first) renderAll();
      setEvents(r[1].events || []);
    });
  }

  function listen() {
    var es = new EventSource('api/events');
    var wasLost = false;
    es.addEventListener('board', function (m) {
      var info = {}; try { info = JSON.parse(m.data); } catch (e) {}
      if (info.errors && info.errors.length) { toast('Board update not shown (it has problems): ' + info.errors[0]); return; }
      fetchJSON('board.json').then(function (b) {
        var v = Core.validateBoard(b);
        if (v.errors.length) { toast('Board update not shown: ' + v.errors[0]); return; }
        var old = S.rev;
        S.board = b; S.rev = b.rev || 0;
        renderAll(); syncState();
        var h = (b.history || [])[0];
        if (S.rev !== old) toast('Board updated to rev ' + S.rev + (h && h.rev === S.rev ? ': ' + h.note : ''));
        else toast('Board refreshed');
      });
    });
    es.addEventListener('feedback', function (m) {
      var info = {}; try { info = JSON.parse(m.data); } catch (e) {}
      if (info.count === S.events.length && (!info.id || S.events.some(function (e) { return e.id === info.id; }))) return;
      fetchJSON('api/feedback').then(function (f) { setEvents(f.events || []); });
    });
    es.addEventListener('reload', function () { location.reload(); });
    es.onopen = function () {
      clearTimeout(S.lostTimer); S.lostTimer = null;
      setConn('live', 'Live'); banner('');
      if (wasLost) { wasLost = false; resync().then(flushOutbox); toast('Reconnected'); }
    };
    es.onerror = function () {
      wasLost = true;
      setConn('offline', 'Reconnecting');
      if (!S.lostTimer) S.lostTimer = setTimeout(function () {
        banner('Lost the connection to the studio server. Clicks are kept and sent when it is back. To restart it, run <code>showtime studio open ' + esc(jobName()) + '</code>');
      }, 15000);
    };
  }

  // ---------------------------------------------------------------- theme
  function applyTheme(t) { if (t === 'light' || t === 'dark') document.documentElement.dataset.theme = t; }
  function toggleTheme() {
    var cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    var next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next; store('st-theme', next);
  }

  // ---------------------------------------------------------------- render
  function fontFaces() {
    var css = ((S.board && S.board.fonts) || []).map(function (f) {
      var u = media(f.src); if (!u || !f.family) return '';
      return '@font-face{font-family:"' + String(f.family).replace(/["\\<]/g, '') + '";src:url("' + u.replace(/["\\\s<]/g, '') + '");font-weight:' +
        String(f.weight || '100 900').replace(/[^0-9 ]/g, '') + ';font-display:swap}';
    }).join('');
    var el = $('#st-fonts');
    if (!el) { el = document.createElement('style'); el.id = 'st-fonts'; var nn = document.querySelector('script[nonce]'); if (nn) el.nonce = nn.nonce; document.head.appendChild(el); }
    el.textContent = css;
  }
  function fam(f) { return String(f || '').replace(/["'\\<>;{}]/g, ''); }

  // the showtime mark for page-level empty states (brand chrome), cloned from the top bar's
  function stMark() {
    var m = document.getElementById('stMark');
    return '<span class="st-empty-mark" aria-hidden="true">' + (m ? m.innerHTML : '') + '</span>';
  }

  function renderAll() {
    if (!S.board) { $('#main').innerHTML = '<div class="empty page">' + stMark() + 'No board data found.</div>'; return; }
    stopAll();
    var b = S.board, cs = concepts();
    document.title = (b.title || 'Studio') + ' · studio';
    $('#title').textContent = b.title || 'Studio board';
    $('#rev').textContent = 'rev ' + (b.rev || 0);
    // open on the picked (or approved) concept; else the first one that has the thing the tab shows
    var apT = S.state.approved && S.state.approved.target;
    var picked = (S.state.picks.concept && conceptById(S.state.picks.concept)) ? S.state.picks.concept
      : (apT && conceptById(apT)) ? apT : null;
    var withSb = cs.filter(function (c) { return (c.storyboard || []).length; })[0];
    var withAn = cs.filter(function (c) { return c.animatic && c.animatic.src; })[0];
    if (!S.ui.sb || !conceptById(S.ui.sb)) S.ui.sb = picked || (withSb && withSb.id) || (cs[0] && cs[0].id);
    if (!S.ui.an || !conceptById(S.ui.an)) {
      var pc = picked && conceptById(picked);
      S.ui.an = (pc && ((pc.animatic && pc.animatic.src) || (pc.storyboard || []).length)) ? picked : (withAn ? withAn.id : S.ui.sb);
    }
    if (!S.ui.cmpA || !conceptById(S.ui.cmpA)) S.ui.cmpA = cs[0] && cs[0].id;
    if (!S.ui.cmpB || !conceptById(S.ui.cmpB)) S.ui.cmpB = (cs[1] || cs[0] || {}).id;
    fontFaces();
    var secs = [
      ['concepts', 'Concepts', cs.length],
      ['storyboard', 'Storyboard', cs.some(function (c) { return (c.storyboard || []).length; })],
      ['animatic', S.board.blind ? 'Watch' : 'Animatic', cs.some(function (c) { return (c.animatic && c.animatic.src) || (c.storyboard || []).length; })],
      ['sound', 'Sound', (b.audio || []).length],
      ['compare', 'Compare', cs.length > 1],
      ['decide', 'Decide', cs.length || (b.questions || []).length]
    ].filter(function (s) { return s[2]; });
    $('#nav').innerHTML = secs.map(function (s) { return '<a href="#' + s[0] + '" data-sec="' + s[0] + '">' + s[1] + '</a>'; }).join('');
    var html = renderIntro();
    if (!cs.length && !(b.questions || []).length) html += '<div class="empty-round">' + stMark() + '<h2>Your agent is preparing the first round</h2><p>This page updates by itself when the concepts are ready.</p></div>';
    secs.forEach(function (s) {
      html += ({ concepts: renderConcepts, storyboard: renderStoryboard, animatic: renderAnimatic, sound: renderSound, compare: renderCompare, decide: renderDecide })[s[0]]();
    });
    $('#main').innerHTML = html;
    setupSound(); setupAnimatic(); scrollSpy(); focusCard(S.ui.focus, false);
  }

  function renderPhases() {
    var b = S.board; if (!b.phase) return '';
    var at = Core.PHASES.indexOf(b.phase);
    var skip = b.skip || [];
    return '<ol class="phases" aria-label="Studio phases">' + Core.PHASES.map(function (p, i) {
      var st = i < at ? 'done' : i === at ? 'current' : 'todo';
      if (skip.indexOf(p) >= 0) st = 'skipped';
      return '<li data-state="' + st + '"' + (st === 'current' ? ' aria-current="step"' : '') + '>' + esc(PHASE_LABEL[p]) + '</li>';
    }).join('') + '</ol>';
  }
  function renderIntro() {
    var b = S.board, r = b.round || {};
    var hist = (b.history || []).slice(0, 4);
    return '<section class="intro"><div>' + renderPhases() + '<div class="eyebrow">' + esc(r.label || ('Round ' + (r.n || 1))) + '</div><h2>' + esc(r.prompt || b.brief || b.title) + '</h2>' +
      '<p>' + esc(b.brief && r.prompt ? b.brief : (r.note || '')) + '</p>' +
      (b.brief && r.prompt && r.note ? '<p style="margin-top:8px">' + esc(r.note) + '</p>' : '') + '</div>' +
      (hist.length ? '<div class="changes"><h3>What changed</h3><ol>' + hist.map(function (h) { return '<li><b>r' + esc(h.rev) + '</b><span>' + esc(h.note) + '</span></li>'; }).join('') + '</ol></div>' : '<div></div>') +
      '</section>';
  }

  function frameList(c) { return (c.frames || []); }
  function renderFrame(c) {
    var fr = frameList(c), k = S.ui.frame[c.id] || 0, f = fr[k];
    var inner = !f ? '' : isMissing(f.src) ? '<div class="missing">' + esc(missingText(f.src, 'Frame not included in this copy')) + '</div>'
      : '<img src="' + esc(media(f.src)) + '" alt="' + esc(c.title + ', style frame: ' + (f.caption || (k + 1))) + '" loading="lazy">';
    var flags = (c.recommended && !S.board.blind ? '<span class="flag rec">Recommended</span>' : '') + (c.wildcard ? '<span class="flag wild">Wildcard</span>' : '');
    return '<div class="frame" data-frame="' + esc(c.id) + '">' + inner +
      '<span class="badge" aria-hidden="true">' + esc(tag(c)) + '</span>' + (flags ? '<span class="flags">' + flags + '</span>' : '') + '<span class="picked-tag">Picked</span>' +
      (f && f.placeholder ? '<span class="ph">placeholder</span>' : '') +
      (f ? '<div class="fcap"><span>' + esc(f.caption || '') + '</span><span>' + (k + 1) + ' / ' + fr.length + '</span></div>' : '') +
      (fr.length > 1 ? '<button class="fbtn prev" data-act="fprev" data-c="' + esc(c.id) + '" aria-label="Previous frame">' + ICON.left + '</button><button class="fbtn next" data-act="fnext" data-c="' + esc(c.id) + '" aria-label="Next frame">' + ICON.right + '</button>' : '') +
      '</div>';
  }
  function conceptMeta(c) {
    var t = c.type || {}, d = t.display || {}, bd = t.body || {};
    var pal = (c.palette || []).map(function (s) {
      var hex = /^#[0-9a-f]{3,8}$/i.test(s.hex || '') ? s.hex : '#000000';
      return '<button style="background:' + hex + '" data-act="swatch" data-hex="' + esc(hex) + '" title="' + esc((s.name ? s.name + ' ' : '') + hex + ' (click to copy)') + '" aria-label="Copy ' + esc((s.name ? s.name + ' ' : '') + hex) + '"><span>' + esc(hex) + '</span></button>';
    }).join('');
    var music = c.music || {};
    var total = (c.structure || []).reduce(function (a, s) { return a + (Number(s.dur) || 1); }, 0) || 1;
    return '<dl class="meta">' +
      (pal ? '<dt>Palette</dt><dd><div class="swatches">' + pal + '</div></dd>' : '') +
      (d.family ? '<dt>Type</dt><dd><div class="specimen"><span class="aa" style="font-family:\'' + esc(fam(d.family)) + '\',var(--ui)">Aa</span><span class="spx"><b style="font-family:\'' + esc(fam(d.family)) + '\',var(--ui)">' + esc(d.sample || c.title) + '</b><small>' + esc(d.family) + (bd.family ? ' + ' + esc(bd.family) : '') + '</small></span></div></dd>' : '') +
      (music.vibe ? '<dt>Music</dt><dd><div class="vibe">' + (music.ref && groupOf(music.ref) ? '<button class="play-s" data-act="vibe" data-v="' + esc(music.ref) + '" aria-pressed="false" aria-label="Play the music sketch">' + ICON.play + '</button>' : '') + '<span>' + esc(music.vibe) + (music.bpm ? ' <span class="muted mono">' + esc(music.bpm) + ' bpm</span>' : '') + '</span></div></dd>' : '') +
      ((c.structure || []).length ? '<dt>Shape</dt><dd><div class="struct">' + c.structure.map(function (s) { return '<div style="flex:' + ((Number(s.dur) || 1) / total) + '" title="' + esc(s.label + ' · ' + (s.dur || '') + 's') + '">' + esc(s.label) + '</div>'; }).join('') + '</div></dd>' : '') +
      '</dl>';
  }
  function renderConcepts() {
    var cards = concepts().map(function (c) {
      var fr = frameList(c), k = S.ui.frame[c.id] || 0;
      return '<article class="card" id="c-' + esc(c.id) + '" data-cid="' + esc(c.id) + '" aria-labelledby="ct-' + esc(c.id) + '">' +
        renderFrame(c) +
        (fr.length > 1 ? '<div class="thumbs" role="group" aria-label="Style frames">' + fr.map(function (f, j) { return '<button data-act="frame" data-c="' + esc(c.id) + '" data-i="' + j + '" aria-current="' + (j === k) + '" aria-label="Frame ' + (j + 1) + '">' + (isMissing(f.thumb || f.src) ? '' : '<img src="' + esc(media(f.thumb || f.src)) + '" alt="" loading="lazy">') + '</button>'; }).join('') + '</div>' : '') +
        '<div class="cbody"><div class="ctitle"><h3 id="ct-' + esc(c.id) + '"><span class="sr">' + esc(tag(c)) + ': </span>' + esc(c.title) + '</h3>' + (c.duration ? '<span class="dur">' + esc(c.duration) + 's</span>' : '') + '</div>' +
        (c.logline ? '<p class="logline">' + esc(c.logline) + '</p>' : '') +
        (c.recommended && c.why && !S.board.blind ? '<p class="why"><b>Why recommended:</b> ' + esc(c.why) + '</p>' : '') +
        (c.hook ? '<p class="hook"><small>Hook, first 3 seconds</small>' + esc(c.hook) + '</p>' : '') +
        ((c.tone || []).length ? '<div class="chips">' + c.tone.map(function (t) { return '<span class="chip">' + esc(t) + '</span>'; }).join('') + '</div>' : '') +
        conceptMeta(c) +
        (c.risk ? '<p class="risk"><b>Risk:</b> ' + esc(c.risk) + '</p>' : '') +
        (c.unlocks ? '<p class="risk"><b>Needs:</b> ' + esc(c.unlocks) + '</p>' : '') + '</div>' +
        '<div class="cactions">' +
        (c.animatic && c.animatic.src && !isMissing(c.animatic.src) ? '<button class="btn primary" data-act="watch" data-c="' + esc(c.id) + '">' + ICON.play + '<span>Watch</span></button>' : '') +
        '<button class="btn pick" data-act="pick" data-slot="concept" data-target="' + esc(c.id) + '" aria-pressed="false">' + ICON.check + '<span>Pick</span></button>' +
        '<button class="btn icon like" data-act="like" data-target="' + esc(c.id) + '" aria-pressed="false" aria-label="Like ' + esc(c.title) + '">' + ICON.heart + '</button>' +
        stars(c.id, c.title) + '<span class="spacer"></span>' +
        '<button class="btn ghost icon" data-act="comment" data-target="' + esc(c.id) + '" aria-label="Comment on ' + esc(c.title) + '" title="Comment (c)">' + ICON.chat + '</button>' +
        (concepts().length > 1 ? '<button class="btn ghost icon" data-act="mix" data-target="' + esc(c.id) + '" aria-label="Mix ' + esc(c.title) + ' with another concept" title="Mix (m)">' + ICON.mix + '</button>' : '') +
        '</div></article>';
    }).join('');
    return '<section class="blk" id="concepts" aria-labelledby="h-concepts"><div class="blk-h"><h2 id="h-concepts">Concepts</h2><p>' + concepts().length + ' direction' + (concepts().length === 1 ? '' : 's') + '. Pick one, like parts of others, or ask to mix them.<span class="keyhint"> Keys: <span class="kbd">j</span> <span class="kbd">k</span> <span class="kbd">p</span> <span class="kbd">l</span> <span class="kbd">1-5</span></span></p></div><div class="concepts">' + cards + '</div></section>';
  }
  function stars(id, title) {
    var h = '<span class="stars" role="group" aria-label="Rate ' + esc(title) + '">';
    for (var i = 1; i <= 5; i++) h += '<button data-act="rate" data-target="' + esc(id) + '" data-v="' + i + '" data-on="false" aria-pressed="false" aria-label="' + i + ' of 5">' + ICON.star + '</button>';
    return h + '</span>';
  }
  function segConcepts(act, cur) {
    return '<div class="seg" role="group" aria-label="Concept">' + concepts().map(function (c) {
      return '<button data-act="' + act + '" data-c="' + esc(c.id) + '" aria-pressed="' + (c.id === cur) + '">' + esc(tag(c)) + '<span class="hide-s"> · ' + esc(c.title) + '</span></button>';
    }).join('') + '</div>';
  }
  function shotTimes(c) {
    var t = 0;
    return ((c && c.storyboard) || []).map(function (s) { var st = s.t != null ? Number(s.t) : t; t = st + (Number(s.dur) || 2); return { s: s, t: st, end: t }; });
  }
  function renderStoryboard() {
    var c = conceptById(S.ui.sb) || concepts()[0];
    var shots = shotTimes(c);
    var strip = shots.length ? shots.map(function (x, i) {
      var s = x.s;
      return '<div class="shot" id="s-' + esc(s.id) + '"><div class="sthumb">' + (s.thumb ? (isMissing(s.thumb) ? '<div class="missing">' + esc(missingText(s.thumb, 'Not in this copy')) + '</div>' : '<img src="' + esc(media(s.thumb)) + '" alt="' + esc('Shot ' + (i + 1) + ': ' + (s.title || '')) + '" loading="lazy">') : '') +
        '<span class="no">' + esc(tag(c)) + '.' + (i + 1) + '</span><span class="tc">' + fmt(x.t) + ' - ' + fmt(x.end) + '</span></div>' +
        '<div class="sb">' + (s.title ? '<b>' + esc(s.title) + '</b>' : '') + (s.vo ? '<span class="vo">' + esc(s.vo) + '</span>' : '') + (s.text ? '<span class="note">On screen: ' + esc(s.text) + '</span>' : '') + (s.note ? '<span class="note">' + esc(s.note) + '</span>' : '') + '</div>' +
        '<div class="sa"><button class="btn icon like" data-act="like" data-target="' + esc(s.id) + '" aria-pressed="false" aria-label="Like shot ' + (i + 1) + '">' + ICON.heart + '</button>' +
        '<button class="btn" data-act="comment" data-target="' + esc(s.id) + '">' + ICON.chat + 'Note</button>' +
        '<button class="btn ghost" data-act="seek" data-c="' + esc(c.id) + '" data-t="' + x.t + '">' + ICON.play + 'Play here</button></div></div>';
    }).join('') : '<p class="empty">No storyboard for this concept yet.</p>';
    return '<section class="blk" id="storyboard" aria-labelledby="h-storyboard"><div class="blk-h"><h2 id="h-storyboard">Storyboard</h2><p>Shot by shot, with timing and voice-over.</p>' + segConcepts('sb', c.id) + '</div><div class="strip" tabindex="0" aria-label="Storyboard shots">' + strip + '</div></section>';
  }
  function notesFor(c) {
    var ids = {}; ids[c.id] = 1; (c.storyboard || []).forEach(function (s) { ids[s.id] = 1; });
    return S.state.comments.filter(function (m) { return m.at != null && ids[m.target]; });
  }
  function renderAnimatic() {
    var c = conceptById(S.ui.an) || concepts()[0];
    var shots = shotTimes(c);
    var a = c.animatic || {};
    var dur = Number(a.duration) || (shots.length ? shots[shots.length - 1].end : 0) || Number(c.duration) || 0;
    var stage = a.src && !isMissing(a.src)
      ? '<video id="anVideo" src="' + esc(media(a.src)) + '"' + (a.poster && !isMissing(a.poster) ? ' poster="' + esc(media(a.poster)) + '"' : '') + ' playsinline preload="auto"></video>' + (S.board.blind ? '' : '<span class="mode">DRAFT VIDEO</span>')
      : '<div class="slides" id="anSlides">' + shots.map(function (x, i) { return isMissing(x.s.thumb) ? '<span data-i="' + i + '"></span>' : '<img src="' + esc(media(x.s.thumb)) + '" alt="" data-i="' + i + '" data-on="' + (i === 0) + '">'; }).join('') + '</div><span class="mode">LIVE SLIDES</span>' +
        (a.src && isMissing(a.src) && HOSTED ? '<div class="missing an-missing">' + esc(missingText(a.src, '')) + '</div>' : '');
    var ticks = shots.map(function (x) { return '<i style="left:' + (dur ? x.t / dur * 100 : 0) + '%"></i>'; }).join('');
    var list = shots.map(function (x, i) { return '<button data-act="seek" data-c="' + esc(c.id) + '" data-t="' + x.t + '" data-shot="' + i + '"><span class="t">' + fmt(x.t) + '</span><span>' + esc(x.s.title || ('Shot ' + (i + 1))) + '</span></button>'; }).join('');
    return '<section class="blk" id="animatic" aria-labelledby="h-animatic"><div class="blk-h"><h2 id="h-animatic">' + (S.board.blind ? 'Watch' : 'Animatic') + '</h2><p>' + (S.board.blind ? 'Pick a version below, then press play or tap the picture. Leave notes at any moment.' : 'A rough cut to judge pace before anything is rendered. Leave notes at any moment.') + '<span class="keyhint"> <span class="kbd">space</span> plays, <span class="kbd">n</span> adds a note.</span></p>' + segConcepts('an', c.id) + '</div>' +
      '<div class="anim"><div><div class="stage" id="anStage" data-dur="' + dur + '">' + stage + '<div class="cap" id="anCap" aria-live="off"></div></div>' +
      '<div class="transport"><button class="btn icon primary" id="anPlay" aria-label="Play animatic">' + ICON.play + '</button>' +
      '<div class="scrub"><div class="ticks" aria-hidden="true">' + ticks + '</div><div class="notes" id="anNotes"></div><input type="range" id="anScrub" min="0" max="' + dur + '" step="0.01" value="0" aria-label="Animatic position"></div>' +
      '<span class="tt" id="anTime">0:00.0 / ' + fmt(dur) + '</span>' +
      '<button class="btn ghost" data-act="note-at" data-target="' + esc(c.id) + '">' + ICON.chat + '<span class="hide-s">Note at this moment</span></button></div></div>' +
      '<div class="shotlist" id="anList" aria-label="Shots">' + list + '</div></div></section>';
  }
  function paintNotes() {
    var box = $('#anNotes'), stage = $('#anStage'); if (!box || !stage) return;
    var c = conceptById(S.ui.an); if (!c) return;
    var dur = +stage.dataset.dur || 0;
    box.innerHTML = notesFor(c).map(function (m) {
      return '<button data-act="note-seek" data-t="' + m.at + '" style="left:' + (dur ? Math.min(100, m.at / dur * 100) : 0) + '%" title="' + esc(fmt(m.at) + ': ' + m.text) + '" aria-label="' + esc('Note at ' + fmt(m.at) + ': ' + m.text) + '"></button>';
    }).join('');
  }
  function renderSound() {
    var groups = (S.board.audio || []).map(function (g) {
      var rows = (g.variants || []).map(function (v, i) {
        return '<div class="variant" data-g="' + esc(g.id) + '" data-v="' + esc(v.id) + '" data-active="false">' +
          '<button class="vplay" data-act="vplay" data-g="' + esc(g.id) + '" data-v="' + esc(v.id) + '" aria-label="Play ' + esc(v.label) + '"' + (isMissing(v.src) ? ' disabled' : '') + '>' + ICON.play + '</button>' +
          '<div class="vl"><b><span class="mono muted">' + String.fromCharCode(65 + i) + '</span>&nbsp; ' + esc(v.label) + '</b><small>' + esc(isMissing(v.src) ? missingText(v.src, 'not included in this copy') : (v.meta || '')) + '</small><div class="bar"><i></i></div></div>' +
          '<div class="va"><button class="btn icon like" data-act="like" data-target="' + esc(v.id) + '" aria-pressed="false" aria-label="Like ' + esc(v.label) + '">' + ICON.heart + '</button>' +
          '<button class="btn pick" data-act="pick" data-slot="' + esc(g.id) + '" data-target="' + esc(v.id) + '" aria-pressed="false">Use</button></div></div>';
      }).join('');
      return '<div class="group" data-group="' + esc(g.id) + '"><h3>' + esc(g.label || g.id) + '</h3><p>' + esc(g.hint || '') + '</p><div class="ab">' + rows + '</div>' +
        '<div class="abhint">Switching keeps the playhead, so you hear the same moment in each.<span class="keyhint"> Keys: <span class="kbd">a</span> <span class="kbd">b</span></span></div></div>';
    }).join('');
    return '<section class="blk" id="sound" aria-labelledby="h-sound"><div class="blk-h"><h2 id="h-sound">Sound</h2><p>Music beds and voices, side by side.</p></div><div class="sound">' + groups + '</div></section>';
  }
  function cmpSide(c) {
    if (!c) return '<div class="side"></div>';
    var th = frameList(c).map(function (f) { return isMissing(f.thumb || f.src) ? '' : '<span class="tb"><img src="' + esc(media(f.thumb || f.src)) + '" alt="" loading="lazy"></span>'; }).join('');
    return '<div class="side"><div class="cbody"><div class="ctitle"><h3>' + esc(tag(c) + ' · ' + c.title) + '</h3>' + (c.duration ? '<span class="dur">' + esc(c.duration) + 's</span>' : '') + '</div>' +
      (th ? '<div class="thumbs">' + th + '</div>' : '') + '<p class="logline" style="margin:0">' + esc(c.logline || '') + '</p>' +
      ((c.tone || []).length ? '<div class="chips">' + c.tone.map(function (t) { return '<span class="chip">' + esc(t) + '</span>'; }).join('') + '</div>' : '') + conceptMeta(c) + '</div></div>';
  }
  function renderCompare() {
    var A = conceptById(S.ui.cmpA), B = conceptById(S.ui.cmpB);
    var opts = function (cur) { return concepts().map(function (c) { return '<option value="' + esc(c.id) + '"' + (c.id === cur ? ' selected' : '') + '>' + esc(tag(c) + ' · ' + c.title) + '</option>'; }).join(''); };
    var fa = A && frameList(A)[0], fb = B && frameList(B)[0];
    var wipe = fa && fb && !isMissing(fa.src) && !isMissing(fb.src);
    return '<section class="blk" id="compare" aria-labelledby="h-compare"><div class="blk-h"><h2 id="h-compare">Compare</h2><p>Drag across the frame to wipe between two looks.</p></div>' +
      '<div class="cmp-bar"><label class="sr" for="cmpA">Left</label><select id="cmpA" data-act="cmpsel" data-side="A">' + opts(S.ui.cmpA) + '</select><span class="muted">vs</span><label class="sr" for="cmpB">Right</label><select id="cmpB" data-act="cmpsel" data-side="B">' + opts(S.ui.cmpB) + '</select></div>' +
      (wipe ? '<div class="wipe" style="--x:' + S.ui.wipe + '%"><img src="' + esc(media(fa.src)) + '" alt="' + esc(A.title) + '"><img class="over" src="' + esc(media(fb.src)) + '" alt="' + esc(B.title) + '"><span class="line"></span><span class="wl">' + esc(tag(A)) + '</span><span class="wr">' + esc(tag(B)) + '</span><input type="range" id="wipe" min="0" max="100" value="' + S.ui.wipe + '" aria-label="Wipe between ' + esc(A.title) + ' and ' + esc(B.title) + '"></div>' : '') +
      '<div class="cmp">' + cmpSide(A) + cmpSide(B) + '</div>' +
      '<div class="mixbox"><label class="sr" for="cmpNote">What to take from each</label><input id="cmpNote" maxlength="2000" placeholder="Mix these: e.g. story of ' + esc(A ? tag(A) : 'C1') + ', look of ' + esc(B ? tag(B) : 'C2') + '"><button class="btn primary" data-act="cmpmix">' + ICON.mix + 'Ask your agent to mix</button></div></section>';
  }
  function renderDecide() {
    var b = S.board;
    var qs = (b.questions || []).map(function (q, qi) {
      return '<div class="q" data-q="' + esc(q.id) + '"><div class="qt" id="q-' + esc(q.id) + '">' + (qi + 1) + '. ' + esc(q.text) + '</div>' + (q.why ? '<div class="why">' + esc(q.why) + '</div>' : '') +
        '<div class="opts" role="group" aria-labelledby="q-' + esc(q.id) + '">' + (q.options || []).map(function (o) {
          return '<button class="opt" data-act="opt" data-q="' + esc(q.id) + '" data-o="' + esc(o.id) + '" aria-pressed="false">' + esc(o.label) + (!b.blind && String(q.recommended) === String(o.id) ? '<span class="rec">Recommended</span>' : '') + '</button>';
        }).join('') + '</div>' +
        (q.allowText ? '<label class="sr" for="qt-' + esc(q.id) + '">Your own answer to: ' + esc(q.text) + '</label><textarea id="qt-' + esc(q.id) + '" data-q="' + esc(q.id) + '" class="qtext" maxlength="2000" placeholder="Or say it in your words, then press Ctrl+Enter"></textarea>' : '') + '</div>';
    }).join('');
    var dials = Core.dialsOf(b).map(function (sl) {
      var d = sl['default'] != null ? sl['default'] : 50;
      return '<div class="dial"><label for="sl-' + esc(sl.id) + '">' + esc(sl.label) + ' <output id="so-' + esc(sl.id) + '">' + d + '</output></label>' +
        '<div class="rng"><span class="proposed" style="left:calc(' + d + '% + ' + (8 - d * 0.16) + 'px)" title="Your agent\'s proposal"></span><input type="range" min="0" max="100" value="' + d + '" id="sl-' + esc(sl.id) + '" data-dial="' + esc(sl.id) + '" aria-describedby="se-' + esc(sl.id) + '"></div>' +
        '<div class="ends" id="se-' + esc(sl.id) + '"><span>' + esc(sl.left || '') + '</span><span>' + esc(sl.right || '') + '</span></div></div>';
    }).join('');
    var copts = concepts().map(function (c) { return '<option value="' + esc(c.id) + '">' + esc(tag(c) + ' · ' + c.title) + '</option>'; }).join('');
    return '<section class="blk" id="decide" aria-labelledby="h-decide"><div class="blk-h"><h2 id="h-decide">Decide</h2><p>' + (b.blind ? 'Answer each question, or skip any you don\'t care about.' : 'A few choices that change the video. Each has a recommended default; skip any you don\'t care about.') + '</p></div>' +
      '<div class="dec"><div class="panel"><h3>Questions</h3>' + (qs || '<p class="muted">No open questions.</p>') + '</div>' +
      '<div class="panel"><h3>Dials</h3>' + (dials || '<p class="muted">No dials this round.</p>') +
      (copts ? '<div class="approve"><label for="apC"><b>Ready?</b> <span class="muted">Approve a concept to move on.</span></label><select id="apC">' + copts + '</select>' +
        '<label class="sr" for="apNote">Final notes</label><textarea id="apNote" maxlength="2000" placeholder="Final notes (optional)"></textarea>' +
        '<button class="btn primary" data-act="approve">' + ICON.check + 'Approve</button><div id="apState" class="muted" style="font-size:13px" role="status"></div>' +
        '<div class="next" id="apNext" hidden><span><b>Last step:</b> copy this for your agent, then paste it in your chat. Nothing reaches your agent until you do.</span><button class="btn primary big" data-act="handoff">Copy for your agent</button></div></div>' : '') + '</div></div></section>';
  }

  // ---------------------------------------------------------------- state -> DOM (cheap, never re-creates media)
  function syncState() {
    var st = S.state;
    $$('[data-act="pick"]').forEach(function (b) {
      var on = st.picks[b.dataset.slot] === b.dataset.target;
      b.setAttribute('aria-pressed', String(on));
      var sp = b.querySelector('span'); if (sp && b.dataset.slot === 'concept') sp.textContent = on ? 'Picked' : 'Pick';
    });
    $$('.card').forEach(function (c) { c.dataset.picked = String(st.picks.concept === c.dataset.cid); });
    $$('.variant').forEach(function (v) { v.dataset.picked = String(st.picks[v.dataset.g] === v.dataset.v); });
    $$('[data-act="like"]').forEach(function (b) { b.setAttribute('aria-pressed', String(!!st.likes[b.dataset.target])); });
    $$('[data-act="rate"]').forEach(function (b) { b.dataset.on = String((st.ratings[b.dataset.target] || 0) >= +b.dataset.v); b.setAttribute('aria-pressed', String((st.ratings[b.dataset.target] || 0) === +b.dataset.v)); });
    $$('[data-act="opt"]').forEach(function (b) { var a = st.answers[b.dataset.q]; b.setAttribute('aria-pressed', String(!!a && a.value === b.dataset.o)); });
    $$('[data-dial]').forEach(function (inp) { var v = st.dials[inp.dataset.dial]; if (v != null && document.activeElement !== inp) { inp.value = v; var o = $('#so-' + inp.dataset.dial); if (o) o.textContent = v; } });
    // live studio: the server already has every click, so the agent only needs to be told. Anywhere else
    // (a shared copy, an artifact, a file from disk) nothing reaches the agent: the reviewer copies the text and pastes it.
    var ap = $('#apState');
    if (ap) ap.textContent = !st.approved ? '' : 'Approved: ' + labelOf(st.approved.target) + (S.live ? '. Tell your agent you are done.' : '.');
    var an = $('#apNext'); if (an) an.hidden = S.live || !st.approved;
    var ho = $('#handoff'); if (ho) { ho.hidden = S.live || !(st.count > 0 || st.approved); if (ho.hidden) $('#hoFallback').hidden = true; }
    if (st.picks.concept && $('#apC') && !st.approved && document.activeElement !== $('#apC')) $('#apC').value = st.picks.concept;
    var n = st.count; $('#fbCount').textContent = n; $('#mFbCount').textContent = n;
    $('#digest').textContent = digestText();
    paintNotes();
  }
  function digestText() { return Core.digest(S.board, { job: jobName(), events: S.events }); }

  // ---------------------------------------------------------------- concept focus & frames
  function focusCard(i, scroll) {
    var cards = $$('.card'); if (!cards.length) return;
    S.ui.focus = Math.max(0, Math.min(cards.length - 1, i));
    cards.forEach(function (c, j) { c.dataset.focus = String(j === S.ui.focus); });
    if (scroll) cards[S.ui.focus].scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
  function focusedConcept() { return concepts()[S.ui.focus]; }
  function setFrame(cid, k) {
    var c = conceptById(cid); var n = frameList(c).length; if (!n) return;
    S.ui.frame[cid] = (k + n) % n;
    $$('[data-frame="' + cid + '"]').forEach(function (el) { el.outerHTML = renderFrame(c); });
    $$('.thumbs button[data-c="' + cid + '"]').forEach(function (b) { b.setAttribute('aria-current', String(+b.dataset.i === S.ui.frame[cid])); });
    syncState();
  }

  // ---------------------------------------------------------------- audio A/B (shared playhead)
  function setupSound() {
    S.audio = {};
    ((S.board && S.board.audio) || []).forEach(function (g) {
      S.audio[g.id] = { active: null, playing: false, els: {} };
      (g.variants || []).forEach(function (v) {
        var a = new Audio(); a.preload = 'none'; a.loop = true;
        var u = media(v.src); if (u) a.src = u;
        S.audio[g.id].els[v.id] = a;
      });
    });
    if (!S.tickOn) { S.tickOn = true; requestAnimationFrame(tickSound); }
  }
  function groupOf(vid) {
    var r = null;
    ((S.board && S.board.audio) || []).forEach(function (g) { (g.variants || []).forEach(function (v) { if (v.id === vid) r = g.id; }); });
    return r;
  }
  function playVariant(gid, vid, toggle) {
    var G = S.audio[gid]; if (!G || !G.els[vid] || !G.els[vid].src) return;
    var prev = G.active && G.els[G.active];
    var el = G.els[vid];
    if (toggle && G.active === vid && G.playing) { el.pause(); G.playing = false; paintSound(); return; }
    stopAll(gid);
    var t = prev ? prev.currentTime : 0;
    if (prev && prev !== el) prev.pause();
    G.active = vid; S.activeGroup = gid;
    var go = function () { try { el.currentTime = el.duration ? t % el.duration : t; } catch (e) {} el.play().catch(function () {}); };
    if (el.readyState >= 1) go(); else { el.preload = 'auto'; el.addEventListener('loadedmetadata', go, { once: true }); el.load(); }
    G.playing = true; paintSound();
  }
  function paintSound() {
    $$('.variant').forEach(function (row) {
      var G = S.audio[row.dataset.g]; var on = G && G.active === row.dataset.v;
      row.dataset.active = String(!!on);
      var b = row.querySelector('.vplay'); var playing = on && G.playing;
      b.innerHTML = playing ? ICON.pause : ICON.play; b.setAttribute('aria-label', (playing ? 'Pause ' : 'Play ') + row.querySelector('b').textContent.replace(/^\S+\s+/, '').trim());
    });
    $$('[data-act="vibe"]').forEach(function (b) { var g = groupOf(b.dataset.v); var G = g && S.audio[g]; var on = !!(G && G.active === b.dataset.v && G.playing); b.setAttribute('aria-pressed', String(on)); b.innerHTML = on ? ICON.pause : ICON.play; });
  }
  function tickSound() {
    Object.keys(S.audio).forEach(function (g) {
      var G = S.audio[g]; if (!G.active) return; var el = G.els[G.active];
      var row = $('.variant[data-g="' + g + '"][data-v="' + G.active + '"] .bar i');
      if (row && el.duration) row.style.width = (el.currentTime / el.duration * 100) + '%';
    });
    requestAnimationFrame(tickSound);
  }
  function stopAll(exceptGroup) {
    Object.keys(S.audio || {}).forEach(function (g) {
      if (g === exceptGroup) return;
      var G = S.audio[g]; Object.keys(G.els).forEach(function (k) { G.els[k].pause(); }); G.playing = false;
    });
    if (S.anim && exceptGroup !== '__anim') S.anim.pause();
    if (S.audio) paintSound();
  }

  // ---------------------------------------------------------------- animatic (draft video or live slides + bed)
  function setupAnimatic() {
    if (S.anim && S.anim.dispose) S.anim.dispose();
    S.anim = null;
    var stage = $('#anStage'); if (!stage) return;
    var c = conceptById(S.ui.an); var shots = shotTimes(c); var dur = +stage.dataset.dur || 0;
    var video = $('#anVideo'), slides = $('#anSlides');
    var bed = null;
    if (!video && c.music && c.music.ref) {
      var src = null;
      (S.board.audio || []).forEach(function (gg) { (gg.variants || []).forEach(function (v) { if (v.id === c.music.ref) src = media(v.src); }); });
      if (src) { bed = new Audio(src); bed.preload = 'auto'; }
    }
    var clock = { t: 0, playing: false, t0: 0, w0: 0 };
    function now() {
      if (video) return video.currentTime;
      if (!clock.playing) return clock.t;
      return Math.min(dur, clock.t0 + (performance.now() - clock.w0) / 1000);
    }
    function shotAt(t) { var k = 0; shots.forEach(function (x, i) { if (t >= x.t - 1e-6) k = i; }); return k; }
    var lastShot = -1;
    function paint() {
      if (!document.body.contains(stage)) return;
      var t = now();
      if (!video && clock.playing && t >= dur) { api.pause(); clock.t = 0; t = 0; }
      $('#anScrub').value = t; $('#anTime').textContent = fmt(t) + ' / ' + fmt(dur);
      var k = shotAt(t);
      if (k !== lastShot) {
        lastShot = k;
        if (slides) $$('[data-i]', slides).forEach(function (im) { im.dataset.on = String(+im.dataset.i === k); });
        $$('#anList button').forEach(function (b) { b.setAttribute('aria-current', String(+b.dataset.shot === k)); });
        var s = shots[k] && shots[k].s; var cap = (c.animatic && c.animatic.captions === false) ? '' : (s && s.vo) || '';
        $('#anCap').textContent = cap;
      }
      if (api.playing()) requestAnimationFrame(paint);
    }
    var api = {
      concept: c.id,
      playing: function () { return video ? !video.paused : clock.playing; },
      play: function () {
        stopAll('__anim');
        if (video) { if (video.ended) video.currentTime = 0; video.play().catch(function () {}); }
        else { clock.playing = true; clock.w0 = performance.now(); clock.t0 = clock.t >= dur ? 0 : clock.t; if (bed) { try { bed.currentTime = clock.t0; } catch (e) {} bed.play().catch(function () {}); } }
        $('#anPlay').innerHTML = ICON.pause; $('#anPlay').setAttribute('aria-label', 'Pause animatic'); requestAnimationFrame(paint);
      },
      pause: function () {
        if (video) video.pause(); else { clock.t = now(); clock.playing = false; if (bed) bed.pause(); }
        var b = $('#anPlay'); if (b) { b.innerHTML = ICON.play; b.setAttribute('aria-label', 'Play animatic'); }
        paint();
      },
      seek: function (t) {
        t = Math.max(0, Math.min(dur, t));
        if (video) video.currentTime = t; else { clock.t = t; clock.t0 = t; clock.w0 = performance.now(); if (bed) try { bed.currentTime = t; } catch (e) {} }
        lastShot = -1; paint();
      },
      toggle: function () { if (api.playing()) api.pause(); else api.play(); },
      time: now,
      shotAt: function (t) { var k = shotAt(t); return shots[k] ? shots[k].s.id : null; },
      dispose: function () { if (bed) bed.pause(); if (video) video.pause(); }
    };
    if (video) { video.addEventListener('pause', function () { api.pause(); }); video.addEventListener('seeked', paint); video.addEventListener('loadedmetadata', paint); }
    $('#anPlay').addEventListener('click', api.toggle);
    if (video) video.addEventListener('click', api.toggle); // tapping the picture plays/pauses, as people expect
    $('#anScrub').addEventListener('input', function (e) { api.seek(+e.target.value); });
    S.anim = api; paint(); paintNotes();
  }

  // ---------------------------------------------------------------- dialogs
  var pending = null;
  function openComment(target, at) {
    pending = { target: target, at: at == null ? null : Math.round(at * 100) / 100 };
    $('#cdTarget').textContent = 'On ' + labelOf(target) + (pending.at != null ? ' at ' + fmt(pending.at) + ' in the animatic' : '');
    $('#cdText').value = ''; $('#commentDlg').showModal(); $('#cdText').focus();
  }
  function noteAtNow() {
    if (!S.anim) return;
    var t = S.anim.time(); S.anim.pause();
    openComment(S.anim.shotAt(t) || S.anim.concept, t);
  }
  function openMix(a) {
    var opts = concepts().map(function (c) { return '<option value="' + esc(c.id) + '">' + esc(tag(c) + ' · ' + c.title) + '</option>'; }).join('');
    $('#mdA').innerHTML = opts; $('#mdB').innerHTML = opts;
    $('#mdA').value = a; var other = concepts().filter(function (c) { return c.id !== a; })[0]; if (other) $('#mdB').value = other.id;
    $('#mdText').value = ''; $('#mixDlg').showModal(); $('#mdText').focus();
  }
  var lastFocus = null;
  function openDrawer(open) {
    var d = $('#drawer');
    if (open) lastFocus = document.activeElement;
    d.dataset.open = String(open); $('#scrim').dataset.open = String(open); d.setAttribute('aria-hidden', String(!open));
    if (open) setTimeout(function () { (matchMedia('(pointer: coarse)').matches ? $('#drawerClose') : $('#generalNote')).focus(); }, 50);
    else if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  // Copy the digest. Returns nothing; `after` (optional) gets the outcome: 'copied' or 'manual'.
  function copyDigest(auto) {
    var text = digestText();
    function done() {
      toast(auto === 'approve' ? 'Approved and copied. Now paste it in your chat with your agent.' : 'Copied. Paste it into your chat with your agent.');
      if (!S.live) { $('#hoFallback').hidden = true; flashCopied(); }
    }
    function manual() {
      if (S.live) { toast('Select the text in the panel and copy it.'); openDrawer(true); return; }
      showManualCopy(text);
    }
    function fallback() {
      var ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'; document.body.appendChild(ta); ta.select();
      var ok = false; try { ok = document.execCommand('copy'); } catch (e) {}
      ta.remove();
      if (ok) done(); else manual();
    }
    if (navigator.clipboard && window.isSecureContext) {
      try { navigator.clipboard.writeText(text).then(done, fallback); } catch (e) { fallback(); }
    } else fallback();
  }
  // the browser refused to copy: show the text, selected, right at the next step
  function showManualCopy(text) {
    var ho = $('#handoff'); ho.hidden = false;
    $('#hoFallback').hidden = false;
    var ta = $('#hoText'); ta.value = text;
    ho.scrollIntoView({ block: 'nearest' });
    ta.focus(); ta.select();
    toast('Copying was blocked. The text is selected: press Ctrl+C, then paste it in your chat.');
  }
  var copiedTimer = null;
  function flashCopied() {
    $$('[data-act="handoff"]').forEach(function (b) { b.textContent = 'Copied. Now paste it in your chat'; });
    clearTimeout(copiedTimer);
    copiedTimer = setTimeout(function () { $$('[data-act="handoff"]').forEach(function (b) { b.textContent = 'Copy for your agent'; }); }, 6000);
  }
  /*ST:DL*/
  function downloadFeedback() {
    var data = { schema: Core.FEEDBACK_SCHEMA, job: jobName(), board_rev: S.rev, updated: new Date().toISOString(), events: S.events, state: S.state };
    var a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    a.download = 'feedback.json'; document.body.appendChild(a); a.click(); a.remove();
  }
  /*ST:/DL*/

  // ---------------------------------------------------------------- scroll spy
  var spy = null;
  function scrollSpy() {
    if (spy) spy.disconnect();
    if (!('IntersectionObserver' in window)) return;
    spy = new IntersectionObserver(function (ents) {
      ents.forEach(function (e) { if (e.isIntersecting) $$('#nav a').forEach(function (a) { a.setAttribute('aria-current', String(a.dataset.sec === e.target.id)); }); });
    }, { rootMargin: '-45% 0px -50% 0px' });
    $$('section.blk').forEach(function (s) { spy.observe(s); });
  }

  // ---------------------------------------------------------------- events
  function rerender(id, fn) { var el = $('#' + id); if (!el) return; el.outerHTML = fn(); syncState(); scrollSpy(); }
  document.addEventListener('click', function (e) {
    var card = e.target.closest('.card'); if (card) focusCard($$('.card').indexOf(card), false);
    var b = e.target.closest('[data-act]'); if (!b) return;
    var act = b.dataset.act, d = b.dataset;
    switch (act) {
      case 'pick':
        if (S.state.picks[d.slot] === d.target) send({ type: 'unpick', slot: d.slot });
        else if (send({ type: 'pick', slot: d.slot, target: d.target })) toast('Picked ' + labelOf(d.target));
        break;
      case 'like': send({ type: 'like', target: d.target, value: !S.state.likes[d.target] }); break;
      case 'rate': send({ type: 'rate', target: d.target, value: S.state.ratings[d.target] === +d.v ? 0 : +d.v }); break;
      case 'comment': openComment(d.target, null); break;
      case 'note-at': noteAtNow(); break;
      case 'note-seek': if (S.anim) S.anim.seek(+d.t); break;
      case 'mix': openMix(d.target); break;
      case 'frame': setFrame(d.c, +d.i); break;
      case 'fprev': setFrame(d.c, (S.ui.frame[d.c] || 0) - 1); break;
      case 'fnext': setFrame(d.c, (S.ui.frame[d.c] || 0) + 1); break;
      case 'swatch':
        if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(d.hex).then(function () { toast('Copied ' + d.hex); }, function () { toast(d.hex); }); else toast(d.hex);
        break;
      case 'sb': S.ui.sb = d.c; rerender('storyboard', renderStoryboard); break;
      case 'an': S.ui.an = d.c; if (S.anim) S.anim.pause(); rerender('animatic', renderAnimatic); setupAnimatic(); break;
      case 'watch':
        if (S.anim) S.anim.pause();
        if (S.ui.an !== d.c || !S.anim) { S.ui.an = d.c; rerender('animatic', renderAnimatic); setupAnimatic(); }
        $('#animatic').scrollIntoView({ behavior: 'smooth' }); S.anim.seek(0); S.anim.play();
        break;
      case 'seek':
        if (S.ui.an !== d.c) { S.ui.an = d.c; rerender('animatic', renderAnimatic); setupAnimatic(); }
        S.anim.seek(+d.t);
        if (!b.closest('#anList')) { $('#animatic').scrollIntoView({ behavior: 'smooth' }); S.anim.play(); }
        break;
      case 'vplay': playVariant(d.g, d.v, true); break;
      case 'vibe': var g = groupOf(d.v); if (g) playVariant(g, d.v, true); break;
      case 'opt':
        var cur = S.state.answers[d.q];
        send({ type: 'answer', target: d.q, value: cur && cur.value === d.o ? null : d.o, text: cur && cur.text || null });
        break;
      case 'cmpmix':
        if (S.ui.cmpA === S.ui.cmpB) { toast('Choose two different concepts'); break; }
        if (send({ type: 'mix', target: S.ui.cmpA, 'with': S.ui.cmpB, text: $('#cmpNote').value })) { $('#cmpNote').value = ''; toast('Mix request saved'); }
        break;
      case 'approve':
        if (send({ type: 'approve', target: $('#apC').value, text: $('#apNote').value })) {
          if (S.live) toast('Approved. Tell your agent you are done.');
          else copyDigest('approve');   // still inside the click, so the browser lets it copy; falls back to selected text
        }
        break;
      case 'handoff': copyDigest(); break;
    }
  });
  document.addEventListener('change', function (e) {
    var t = e.target;
    if (t.dataset && t.dataset.dial) send({ type: 'dial', target: t.dataset.dial, value: +t.value });
    if (t.dataset && t.dataset.act === 'cmpsel') { S.ui[t.dataset.side === 'A' ? 'cmpA' : 'cmpB'] = t.value; rerender('compare', renderCompare); }
  });
  document.addEventListener('input', function (e) {
    var t = e.target;
    if (t.dataset && t.dataset.dial) { var o = $('#so-' + t.dataset.dial); if (o) o.textContent = t.value; }
    if (t.id === 'wipe') { S.ui.wipe = +t.value; t.parentNode.style.setProperty('--x', t.value + '%'); }
  });
  document.addEventListener('keydown', function (e) {
    var ctrlEnter = e.key === 'Enter' && (e.ctrlKey || e.metaKey);
    if (e.target.classList && e.target.classList.contains('qtext') && ctrlEnter) {
      var q = e.target.dataset.q, cur = S.state.answers[q];
      if (e.target.value.trim() && send({ type: 'answer', target: q, value: cur && cur.value || null, text: e.target.value })) toast('Answer saved');
      e.preventDefault(); return;
    }
    if (e.target.id === 'cdText' && ctrlEnter) { e.preventDefault(); $('#cdSend').click(); return; }
    if (e.target.id === 'mdText' && ctrlEnter) { e.preventDefault(); $('#mixForm button[value="ok"]').click(); return; }
    if (e.target.id === 'generalNote' && ctrlEnter) { e.preventDefault(); $('#sendNote').click(); return; }
    if (e.key === 'Escape' && $('#drawer').dataset.open === 'true') { openDrawer(false); return; }
    if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey || document.querySelector('dialog[open]')) return;
    var c = focusedConcept();
    switch (e.key) {
      case 'j': document.body.dataset.kbd = 'true'; focusCard(S.ui.focus + 1, true); break;
      case 'k': document.body.dataset.kbd = 'true'; focusCard(S.ui.focus - 1, true); break;
      case 'p': if (c) { var pb = $('.card[data-cid="' + c.id + '"] [data-act="pick"]'); if (pb) pb.click(); } break;
      case 'l': if (c) send({ type: 'like', target: c.id, value: !S.state.likes[c.id] }); break;
      case '0': case '1': case '2': case '3': case '4': case '5': if (c) send({ type: 'rate', target: c.id, value: +e.key }); break;
      case 'c': if (c) { openComment(c.id, null); e.preventDefault(); } break;
      case 'm': if (c && concepts().length > 1) { openMix(c.id); e.preventDefault(); } break;
      case 'f': if (c) setFrame(c.id, (S.ui.frame[c.id] || 0) + 1); break;
      case 'n': if (S.anim) { noteAtNow(); e.preventDefault(); } break;
      case ' ': if (S.anim && !(e.target.closest && e.target.closest('button, a, input, select'))) { e.preventDefault(); S.anim.toggle(); } break;
      case 'a': case 'b':
        var gid = S.activeGroup || Object.keys(S.audio)[0]; var grp = ((S.board && S.board.audio) || []).filter(function (g) { return g.id === gid; })[0];
        var v = grp && grp.variants[e.key.charCodeAt(0) - 97]; if (v) playVariant(gid, v.id, false); break;
      case 't': toggleTheme(); break;
      case '.': openDrawer($('#drawer').dataset.open !== 'true'); break;
      case '?': $('#helpDlg').showModal(); break;
    }
  });

  $('#commentForm').addEventListener('submit', function (e) {
    if (e.submitter && e.submitter.value === 'cancel') return;
    var text = $('#cdText').value.trim(); if (!text || !pending) return;
    if (send({ type: 'comment', target: pending.target, text: text, at: pending.at })) toast('Note saved');
  });
  $('#mixForm').addEventListener('submit', function (e) {
    if (e.submitter && e.submitter.value === 'cancel') return;
    if ($('#mdA').value === $('#mdB').value) { e.preventDefault(); toast('Choose two different concepts'); return; }
    if (send({ type: 'mix', target: $('#mdA').value, 'with': $('#mdB').value, text: $('#mdText').value })) toast('Mix request saved');
  });
  $('#themeBtn').addEventListener('click', toggleTheme);
  $('#helpBtn').addEventListener('click', function () { $('#helpDlg').showModal(); });
  $('#fbBtn').addEventListener('click', function () { openDrawer(true); });
  $('#mFb').addEventListener('click', function () { openDrawer(true); });
  $('#drawerClose').addEventListener('click', function () { openDrawer(false); });
  $('#scrim').addEventListener('click', function () { openDrawer(false); });
  $('#copyBtn').addEventListener('click', function () { copyDigest(); });
  $('#mCopy').addEventListener('click', function () { copyDigest(); });
  /*ST:DL*/
  if ($('#dlBtn')) $('#dlBtn').addEventListener('click', downloadFeedback);
  /*ST:/DL*/
  $('#sendNote').addEventListener('click', function () {
    var t = $('#generalNote').value.trim(); if (!t) return;
    if (send({ type: 'comment', target: null, text: t })) { $('#generalNote').value = ''; toast('Note saved'); }
  });

  window.StudioBoard = { state: function () { return S; }, send: send, digest: digestText };
  boot();
})();

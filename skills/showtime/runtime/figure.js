/* showtime living diagrams: the live figure page around Diagram.live (runtime/figure.js + figure.css).
 *
 * Classic script: adds Figure.mount to the global `Figure` of /_st/figure-film.js. Load after diagram.js and it:
 *
 *   <html data-theme="white">
 *   <link rel="stylesheet" href="/_st/diagram.css"> <link rel="stylesheet" href="/_st/figure.css">
 *   <script src="/_st/diagram.js"></script> <script src="/_st/figure-film.js"></script> <script src="/_st/figure.js"></script>
 *   <div id="figure"></div> <script src="scene.js"></script> <script>Figure.mount(SCENE);</script>
 *
 * The board is there and moving from the first frame (no play button, no timeline). The viewer hovers or tabs to a
 * part (the film's focus veil lights it and its own wires; a card says what it is and its value), picks a step
 * (an experiment that runs on the board), turns a knob (the step runs again with the new value: fills, stacks and
 * tags answer at once). Untouched, an idle tour of the same live actions plays; any input stops it and it comes
 * back after 20 s. Keys, deep links (#step=...&<knob>=...&part=...), reduced motion (still, input still works),
 * a pause when off screen or hidden, and a phone layout (the words leave the drawing for the panel).
 *
 * The scene says what is interactive in SCENE.interactive (references/workflows/diagram.md, Interactive):
 *   { title, sub, parts: [{id, name, sub}], steps: [{id, kicker, text | fn(state), knob, narr, run(fx, again)}],
 *     reset(fx), knobs: {name: {label, hint, options: [[value, words]] | min, max, step, format(v)}, default},
 *     readouts(state, stepId) -> {rows: [{part, k, v, u, tone}], note}, source, tour: [[action, ms]],
 *     agree(state, stepId, {board, step, readouts}) -> [contradictions] (the walk reports them),
 *     crop: {desk: [x0, y0, x1, y1], phone: [...]}, start: t (the live clock starts here: a film-first scene starts
 *     after its build), film: 'tour' (index.html draws the tour as the film: Figure.film) }
 * Touch (the viewer acts on the board itself):
 *   type: fn(fx, ch, state, stepId) | {hint, run}: every character the viewer types (Enter '\n', Backspace '\b'),
 *     also from the "Type" field (a phone's own keyboard); with it, letters and digits are the scene's (the page's R,
 *     L and 1-9 shortcuts are buttons only; arrows and Esc stay)
 *   parts[].press: fn(fx, state, stepId): a click or tap on that part (or its button in the parts list) runs it
 *   parts[].drag: {knob, axis: 'x' | 'y', span: px for the knob's whole range}: dragging that part turns the knob
 * A step's run(fx, again) writes keys through fx: level(id, v), count(id, n), say(tag, text, tone), hide(tag),
 * pulse(part, tone), tone(part, tone | null), show(part, on), send(token, moves, {stay}), park(token), focus(part),
 * every(ms, fn, name); each takes {delay, dur} where it
 * applies; `again` is true when only a knob moved (retarget, no new shock). fx.state holds the knobs' values.
 * Every call lands at the action's time plus its delay, so a figure is a pure function of its clock and its log.
 */
(function (root) {
  'use strict';
  var D = root.document;
  var W = 1920, H = 1080, SAFE = [64, 58, 1856, 990];
  var esc = function (s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); };
  var el = function (tag, cls, html) { var e = D.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
  var warn = function (m) { if (root.console) console.warn('[showtime] figure: ' + m); };

  var C = root.Figure && root.Figure.core;
  if (!C) { if (root.console) console.warn('[showtime] figure: load /_st/figure-film.js before /_st/figure.js'); return; }
  var makeFx = C.makeFx, stepText = C.stepText, knobDefaults = C.knobDefaults, stepIndex = C.stepIndex, partsOf = C.partsOf, normalise = C.normalise;

  /* ---------------- the live page ---------------- */
  function mount(spec, opts) {
    opts = opts || {};
    var I = normalise(spec), host = typeof opts.host === 'string' ? D.querySelector(opts.host) : (opts.host || D.querySelector('#figure'));
    if (!host) { warn('no host element (#figure) on the page'); return null; }
    var theme = opts.theme || D.documentElement.getAttribute('data-theme') || spec.theme || 'white';
    var mq = function (q) { try { return root.matchMedia && root.matchMedia(q).matches; } catch (e) { return false; } };
    var RM = opts.reduced != null ? !!opts.reduced : mq('(prefers-reduced-motion: reduce)');
    var parts = partsOf(spec, I), PART = {}; parts.forEach(function (p) { PART[p.id] = p; });
    var TYPE = typeof I.type === 'function' ? { run: I.type } : (I.type && typeof I.type.run === 'function' ? I.type : null);
    var typeHint = TYPE ? (TYPE.hint || 'Type on it') : '';
    var state = Object.assign(knobDefaults(I), opts.state || {}), S = { step: 0, hover: '', pin: '' };

    /* ---- DOM ---- */
    host.classList.add('fg');
    var title0 = String(I.title || (spec.page && spec.page.title) || '').replace(/\*/g, '').trim();
    if (title0 && /^\s*(living diagram)?\s*$/i.test(D.title)) D.title = title0;   // the template page's placeholder title
    host.innerHTML = '';
    var main = el('main', 'fg-main'), fig = el('div', 'fg-fig'), stage = el('div', 'ld-stage'), ldHost = el('div', 'fg-ld');
    var card = el('div', 'fg-card', '<span class="n"></span><span class="s"></span><span class="v"></span>'); card.hidden = true;
    fig.setAttribute('role', 'img'); fig.tabIndex = -1;
    stage.appendChild(ldHost); stage.appendChild(card); fig.appendChild(stage); main.appendChild(fig);
    var strip = el('section', 'fg-strip');
    strip.setAttribute('aria-label', 'Step, controls and readouts');
    strip.innerHTML = '<div class="fg-step"><span class="k"></span><span class="t"></span></div><div class="fg-board" aria-hidden="true"></div>' +
      '<div class="fg-ctrl"><div class="fg-knob" hidden></div></div><div class="fg-reads"><h2>Readouts</h2><div class="fg-ro"></div><p class="fg-note"></p>' +
      (I.source ? '<p class="fg-src">' + esc(I.source) + '</p>' : '') + '</div>' +
      '<div class="fg-tour" hidden><span class="dot"></span><span>Showing you around: touch anything to take over</span><button type="button">Take over</button></div>';
    main.appendChild(strip);
    if (TYPE) {
      var typeEl = el('label', 'fg-type', '<span class="fg-type-k"></span><input type="text" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" enterkeyhint="enter">');
      typeEl.querySelector('.fg-type-k').textContent = typeHint;
      typeEl.querySelector('input').setAttribute('aria-label', typeHint + ': what you type here is typed on the figure');
      typeEl.querySelector('input').placeholder = 'type here or anywhere';
      main.insertBefore(typeEl, strip);
    }
    var rail = el('aside', 'fg-rail');
    rail.setAttribute('aria-label', 'Steps and parts');
    rail.innerHTML = '<div class="fg-brand">' + esc(I.kicker || 'Live figure') + '</div><h1>' + esc(I.title || (spec.page && spec.page.title || '').replace(/\*/g, '') || 'Living diagram') + '</h1>' +
      (I.sub ? '<p class="fg-sub">' + esc(I.sub) + '</p>' : '') +
      (I.steps.length ? '<section class="fg-sec"><h2 id="fg-h-steps">Steps</h2><nav class="fg-steps" aria-labelledby="fg-h-steps"></nav></section>' : '') +
      (parts.length ? '<section class="fg-sec"><h2 id="fg-h-parts">Parts</h2><div class="fg-parts" role="group" aria-labelledby="fg-h-parts"></div></section>' : '') +
      '<section class="fg-sec fg-narr-sec" hidden><details><summary>Narration for this step</summary><p class="fg-narr"></p></details></section>' +
      '<section class="fg-sec fg-row">' + (I.steps.length ? '<button type="button" class="fg-btn fg-again">Run this step again</button>' : '') + '<button type="button" class="fg-btn fg-copy">Copy a link to this state</button></section>' +
      (TYPE ? '<div class="fg-keys">' + esc(typeHint) + ': type on your keyboard · ' + (I.steps.length ? '<kbd>←</kbd> <kbd>→</kbd> steps · ' : '') + '<kbd>Tab</kbd> parts and controls · <kbd>Esc</kbd> clear</div>'
        : '<div class="fg-keys">' + (I.steps.length ? '<kbd>←</kbd> <kbd>→</kbd> steps · <kbd>1</kbd>-<kbd>9</kbd> jump · <kbd>R</kbd> run again · ' : '') + '<kbd>Tab</kbd> parts and controls · <kbd>Esc</kbd> clear · <kbd>L</kbd> copy link</div>') +
      '<div class="fg-live" aria-live="polite"></div>';
    var app = el('div', 'fg-app'); app.appendChild(main); app.appendChild(rail); host.appendChild(app);
    var $ = function (s) { return host.querySelector(s); };

    /* ---- clock: real time, frozen under reduced motion (each action then jumps it past its own keys) ---- */
    var t0 = (root.performance ? performance.now() : Date.now()) / 1000, start = I.start || 0, frozen = start;
    var clock = {
      reduced: RM,
      now: function () { return RM || clock.manual ? frozen : start + (root.performance ? performance.now() : Date.now()) / 1000 - t0; },
      every: function (ms, fn, loops, name) { fn(); if (ms > 0 && !RM && !clock.manual) loops.push({ name: name, id: setInterval(function () { if (!D.hidden && onscreen) { fx.tau = clock.now() + 0.05; fn(); dirty = true; } }, ms) }); },
      stop: function (ls) { ls.forEach(function (l) { clearInterval(l.id); }); },
      manual: false,
    };
    // the live page may frame the board on its own (interactive.camera: no title column beside it)
    var api = Diagram.live(I.camera ? Object.assign({}, spec, { camera: I.camera }) : spec, { host: ldHost, theme: theme, look: opts.look, live: { now: clock.now } });
    if (!api) return null;
    var fx = makeFx(api, clock, state, I);
    var act = function (fn) { fx.tau = clock.now() + (RM || clock.manual ? 0 : 0.05); fn(); if (RM || clock.manual) frozen += 6; dirty = true; };

    /* ---- fit: the stage to the figure box, cropped (desktop and phone crops) ---- */
    var phone = false, k = 1, crop = [0, 0, W, H], hullsCache = null;
    function fit() {
      phone = (root.innerWidth || W) < 820; D.documentElement.classList.toggle('fg-phone', phone);
      var cr = I.crop || {}; crop = (phone ? cr.phone || cr.desk : cr.desk) || [0, 0, W, H];
      var w = fig.clientWidth || 1; k = w / (crop[2] - crop[0]);
      stage.style.transformOrigin = '0 0';
      stage.style.transform = 'translate(' + (-crop[0] * k) + 'px,' + (-crop[1] * k) + 'px) scale(' + k + ')';
      fig.style.height = Math.round((crop[3] - crop[1]) * k) + 'px';
      dirty = true; hullsCache = null;
    }
    root.addEventListener('resize', fit);

    /* ---- steps ---- */
    function reset() { fx.stopLoops(); if (I.reset) I.reset(fx); }
    function enter(i, o) {
      o = o || {};
      if (!I.steps.length) return;
      S.step = Math.max(0, Math.min(I.steps.length - 1, i));
      act(function () { reset(); var st = I.steps[S.step]; if (st.run) st.run(fx, false); });
      ui(); sync();
    }
    function setKnob(name, v, fromTour) {
      state[name] = v;
      var cur = I.steps[S.step], own = stepIndex(I, (I.steps.filter(function (s) { return s.knob === name; })[0] || {}).id);
      if (!cur || cur.knob !== name) { if (own >= 0) { enter(own); } }
      else act(function () { if (cur.run) cur.run(fx, true); });
      if (!fromTour) touched();
      ui(); sync();
    }

    /* ---- drawing ---- */
    var dirty = true, raf = 0, onscreen = true, last = 0, cost = { n: 0, ms: 0 };
    function draw() {
      var t = clock.now(), a = root.performance ? performance.now() : 0;
      api.render(t);
      cost.n++; cost.ms += (root.performance ? performance.now() : 0) - a;
      placeCard(t);
      if (phone) board();
    }
    function loop(ts) {
      raf = 0;
      if (D.hidden || !onscreen) return;
      if (RM || clock.manual) { if (dirty) { draw(); dirty = false; } }
      else if (ts - last > 32 || dirty) { last = ts; draw(); dirty = false; }  // gentle motion: about 30 fps is plenty
      raf = root.requestAnimationFrame(loop);
    }
    function wake() { if (!raf) raf = root.requestAnimationFrame(loop); }
    D.addEventListener('visibilitychange', wake);
    if ('IntersectionObserver' in root) new IntersectionObserver(function (e) { onscreen = e[0].isIntersecting; wake(); }).observe(fig);

    /* ---- hover, the card, the parts ---- */
    function current() { return S.pin || S.hover; }
    function setHover(id, from) {
      id = id || '';
      if (S.hover === id) return;
      S.hover = id;
      api.focus(current() || null, { at: clock.now() });
      if (RM || clock.manual) frozen += 0.5;
      dirty = true; ui();
      if (id && from !== 'tour') say(PART[id].name + ', ' + (PART[id].sub || '') + (valueFor(id) ? '. ' + valueFor(id).text : ''));
    }
    function pin(id) { S.pin = S.pin === id ? '' : id; api.focus(current() || null, { at: clock.now() }); if (RM || clock.manual) frozen += 0.5; dirty = true; ui(); sync(); }
    function valueFor(id) {
      var R = readouts(), row = R.rows.filter(function (r) { return r.part === id; })[0];
      return row ? { text: row.k + ' ' + row.v + (row.u ? ' ' + row.u : ''), tone: row.tone || '' } : null;
    }
    function placeCard(t) {
      var p = current();
      if (!p || phone || !PART[p]) { card.hidden = true; return; }
      card.hidden = false;
      card.querySelector('.n').textContent = PART[p].name; card.querySelector('.s').textContent = PART[p].sub || '';
      var v = valueFor(p), ve = card.querySelector('.v');
      ve.textContent = v ? v.text : ''; ve.hidden = !v; ve.className = 'v' + (v && v.tone ? ' fg-tone-' + v.tone : '');
      var pos = I.card || [crop[0] + 36, crop[1] + 36];
      card.style.left = pos[0] + 'px'; card.style.top = pos[1] + 'px';
    }
    function hit(cx, cy) {
      var r = fig.getBoundingClientRect(), x = (cx - r.left) / k + crop[0], y = (cy - r.top) / k + crop[1];
      return api.hit(x, y, clock.now(), parts.map(function (p) { return p.id; }));
    }

    /* ---- the panel ---- */
    var stepsEl = $('.fg-steps'), partsEl = $('.fg-parts'), knobEl = $('.fg-knob'), roEl = $('.fg-ro'), noteEl = $('.fg-note'), liveEl = $('.fg-live');
    I.steps.forEach(function (st, i) {
      var b = el('button', 'fg-stepb', '<span class="n">' + (i + 1) + '</span><span class="k"></span>'); b.type = 'button';
      b.querySelector('.k').textContent = st.kicker || st.id;
      b.addEventListener('click', function () { touched(); enter(i); });
      stepsEl.appendChild(b);
    });
    parts.forEach(function (p) {
      var b = el('button', 'fg-part', '<span class="n"></span><span class="s"></span>'); b.type = 'button'; b.setAttribute('data-part', p.id);
      b.querySelector('.n').textContent = p.name; b.querySelector('.s').textContent = p.sub || '';
      b.addEventListener('focus', function () { setHover(p.id); });
      b.addEventListener('blur', function () { setHover(''); });
      b.addEventListener('mouseenter', function () { setHover(p.id); });
      b.addEventListener('mouseleave', function () { setHover(''); });
      b.addEventListener('click', function () { touched(); if (p.press) pressPart(p.id); else pin(p.id); });
      if (p.press) b.classList.add('fg-pressable');
      partsEl.appendChild(b);
    });
    var shownKnob = null;
    function knobUI() {
      var st = I.steps[S.step] || {}, name = st.knob, K = name && I.knobs[name];
      var key = name ? name + '|' + state[name] : '';
      if (key === shownKnob) return;
      var focused = knobEl.contains(D.activeElement);
      shownKnob = key; knobEl.innerHTML = ''; knobEl.hidden = !K;
      strip.classList.toggle('fg-noknob', !K);
      if (!K) return;
      if (K.options) {
        knobEl.innerHTML = '<div class="kh" id="fg-kh">' + esc(K.label) + (K.hint ? '<span>' + esc(K.hint) + '</span>' : '') + '</div><div class="seg" role="radiogroup" aria-labelledby="fg-kh"></div>';
        var seg = knobEl.querySelector('.seg'), vals = K.options.map(function (o) { return o[0]; });
        K.options.forEach(function (o) {
          var b = el('button', '', '<b>' + esc(o[0]) + '</b>' + (o[1] ? '<span>' + esc(o[1]) + '</span>' : '')); b.type = 'button';
          var on = String(state[name]) === String(o[0]);
          b.setAttribute('role', 'radio'); b.setAttribute('aria-checked', String(on)); b.tabIndex = on ? 0 : -1;
          b.addEventListener('click', function () { setKnob(name, o[0]); });
          seg.appendChild(b);
        });
        seg.addEventListener('keydown', function (e) {
          var i = vals.map(String).indexOf(String(state[name])), d = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[e.key];
          if (d == null) return; e.preventDefault(); e.stopPropagation();
          setKnob(name, vals[Math.max(0, Math.min(vals.length - 1, i + d))]);
        });
        if (focused) { var q = seg.querySelector('[aria-checked="true"]'); if (q) q.focus(); }
      } else {
        var fmt = K.format || function (v) { return String(v); };
        knobEl.innerHTML = '<label class="kh" for="fg-range">' + esc(K.label) + ' <b></b>' + (K.hint ? '<span>' + esc(K.hint) + '</span>' : '') + '</label><input id="fg-range" type="range">';
        var r = knobEl.querySelector('input'); r.min = K.min; r.max = K.max; r.step = K.step || 1; r.value = state[name];
        knobEl.querySelector('b').textContent = fmt(state[name]);
        r.setAttribute('aria-valuetext', fmt(state[name]));
        r.addEventListener('input', function () { var v = Number(r.value); shownKnob = name + '|' + v; setKnob(name, v); knobEl.querySelector('b').textContent = fmt(v); r.setAttribute('aria-valuetext', fmt(v)); });
        r.addEventListener('keydown', function (e) { e.stopPropagation(); });
        if (focused) r.focus();
      }
    }
    function readouts() {
      var st = I.steps[S.step] || {}, R = I.readouts ? I.readouts(state, st.id) : null;
      return R && R.rows ? R : { rows: [], note: (R && R.note) || '' };
    }
    function ui() {
      var st = I.steps[S.step] || {}, text = stepText(st, state), hp = current();
      if (stepsEl) Array.prototype.forEach.call(stepsEl.children, function (b, i) { b.setAttribute('aria-current', i === S.step ? 'step' : 'false'); });
      if (partsEl) Array.prototype.forEach.call(partsEl.children, function (b) { var id = b.getAttribute('data-part'); b.setAttribute('aria-pressed', String(S.pin === id)); b.classList.toggle('on', hp === id); });
      $('.fg-step .k').textContent = st.kicker || ''; $('.fg-step .t').textContent = text;
      $('.fg-step').hidden = !st.kicker && !text;
      knobUI(); keyButtons();
      var R = readouts();
      roEl.innerHTML = '';
      R.rows.forEach(function (r) {
        var d = el('div', 'ro' + (r.tone ? ' fg-tone-' + r.tone : '') + (hp && r.part === hp ? ' on' : '') + (/^[×+−-]?[0-9]/.test(String(r.v)) ? '' : ' txt'),
          '<span class="k"></span><span class="v"></span><span class="u"></span>');
        d.querySelector('.k').textContent = r.k; d.querySelector('.v').textContent = r.v; d.querySelector('.u').textContent = r.u || '';
        roEl.appendChild(d);
      });
      noteEl.textContent = R.note || (R.rows.length ? '' : (I.steps.length ? 'No numbers on this step: hover a part, or pick another step.' : 'Hover a part to see what it does.'));
      var narr = typeof st.narr === 'function' ? st.narr(state) : st.narr;
      $('.fg-narr').textContent = narr || ''; $('.fg-narr-sec').hidden = !narr;
      fig.setAttribute('aria-label', (I.title || 'Live figure') + (st.kicker ? '. ' + st.kicker + ': ' + text : ''));
      if (!tour.on) say((st.kicker ? st.kicker + '. ' : '') + text + (R.rows.length ? ' ' + R.rows.map(function (r) { return r.k + ' ' + r.v + (r.u ? ' ' + r.u : ''); }).join('; ') : ''));
    }
    var sayT = 0;
    function say(s) { if (tour.on) return; clearTimeout(sayT); sayT = setTimeout(function () { liveEl.textContent = s; }, 400); }

    /* ---- the phone: what the board shows, as chips in their own colours ---- */
    var boardEl = $('.fg-board'), lastBoard = '';
    function board() {
      var out = [];
      ldHost.querySelectorAll('[data-ld-tag]').forEach(function (g) {
        if (g.getAttribute('visibility') !== 'visible' || +g.getAttribute('opacity') < 0.5) return;
        var r = g.querySelector('rect'), bg = r ? r.getAttribute('fill') : '';
        g.querySelectorAll('text').forEach(function (tx) { if (tx.getAttribute('visibility') === 'visible') out.push([tx.textContent, bg, tx.getAttribute('fill')]); });
      });
      var key = JSON.stringify(out); if (key === lastBoard) return; lastBoard = key;
      boardEl.innerHTML = '';
      out.forEach(function (x) { var c = el('span'); c.textContent = x[0]; if (x[1]) c.style.background = x[1]; if (x[2]) c.style.color = x[2]; boardEl.appendChild(c); });
    }

    /* ---- pointer and keys ---- */
    // a part with drag turns its knob while dragged; a part with press acts on a click; any other part pins its card
    var dragging = null, dragged = false, dragRaf = 0;
    if (parts.some(function (p) { return p.drag; })) fig.style.touchAction = 'pan-y';
    fig.addEventListener('pointerdown', function (e) {
      var id = hit(e.clientX, e.clientY), p = id && PART[id], d = p && p.drag, K = d && I.knobs[d.knob];
      dragged = false;
      if (!K || K.options) return;
      dragging = { id: id, d: d, K: K, x: e.clientX, y: e.clientY, v0: Number(state[d.knob]), pid: e.pointerId, moved: false };
    });
    fig.addEventListener('pointermove', function (e) {
      if (dragging && dragging.pid === e.pointerId) {
        var g = dragging, dist = g.d.axis === 'y' ? g.y - e.clientY : e.clientX - g.x;
        if (!g.moved && Math.abs(dist) > 4) { g.moved = true; touched(); try { fig.setPointerCapture(e.pointerId); } catch (err) { /* gone */ } fig.classList.add('fg-dragging'); setHover(g.id); }
        if (g.moved) {
          var step = g.K.step || 1, v = g.v0 + dist / (g.d.span || 320) * (g.K.max - g.K.min);
          v = Math.max(g.K.min, Math.min(g.K.max, Math.round((v - g.K.min) / step) * step + g.K.min));
          v = +v.toFixed(6);
          if (v !== state[g.d.knob] && !dragRaf) { dragRaf = (root.requestAnimationFrame || setTimeout)(function () { dragRaf = 0; if (dragging) setKnob(dragging.d.knob, dragging.want); }); }
          g.want = v;
          return;
        }
      }
      var id = hit(e.clientX, e.clientY), pp = id && PART[id];
      fig.style.cursor = !id ? 'default' : pp && pp.drag ? 'grab' : 'pointer';
      if (e.pointerType === 'mouse') { touched(); setHover(id); }
    });
    function endDrag(e) {
      if (!dragging || dragging.pid !== e.pointerId) return;
      var g = dragging; dragging = null; fig.classList.remove('fg-dragging');
      if (g.moved) { dragged = true; if (g.want != null && g.want !== state[g.d.knob]) setKnob(g.d.knob, g.want); }
    }
    fig.addEventListener('pointerup', endDrag);
    fig.addEventListener('pointercancel', endDrag);
    fig.addEventListener('pointerleave', function () { if (!dragging) setHover(''); });
    fig.addEventListener('click', function (e) {
      touched();
      if (dragged) { dragged = false; return; }
      var id = hit(e.clientX, e.clientY);
      if (id && PART[id] && PART[id].press) pressPart(id);
      else if (id) pin(id); else if (S.pin) pin(S.pin);
    });
    function pressPart(id) {
      var p = PART[id], sid = (I.steps[S.step] || {}).id;
      if (!p || !p.press) return;
      act(function () { p.press(fx, state, sid); });
      if (S.pin !== id) { S.pin = id; api.focus(id, { at: clock.now() }); }
      ui(); sync();
    }
    // typing: a character on the board (the scene's type.run), from anywhere on the page or from the Type field
    function typeCh(ch) {
      if (!TYPE) return;
      var sid = (I.steps[S.step] || {}).id;
      touched();
      act(function () { TYPE.run(fx, ch, state, sid); });
      ui();
    }
    if (TYPE) {
      var tin = $('.fg-type input');
      tin.addEventListener('input', function (e) {
        var v = tin.value; tin.value = '';
        for (var i = 0; i < v.length; i++) typeCh(v.charAt(i));
      });
      tin.addEventListener('keydown', function (e) {
        e.stopPropagation();
        if (e.key === 'Enter') { e.preventDefault(); typeCh('\n'); }
        else if (e.key === 'Backspace' && !tin.value) { e.preventDefault(); typeCh('\b'); }
        else if (e.key === 'Escape') tin.blur();
      });
    }
    root.addEventListener('keydown', function (e) {
      var tag = (e.target && e.target.tagName) || '';
      touched();
      if (e.key === 'Escape') { S.pin = ''; setHover(''); api.focus(null, { at: clock.now() }); dirty = true; ui(); sync(); return; }
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'ArrowRight' || e.key === 'PageDown') { if (I.steps.length) { e.preventDefault(); enter(S.step + 1); } }
      else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { if (I.steps.length) { e.preventDefault(); enter(S.step - 1); } }
      else if (I.keys && I.keys[e.key.toLowerCase()]) pressKey(e.key.toLowerCase());
      else if (TYPE) {
        if (e.repeat && e.key.length !== 1) return;
        if (e.key === 'Enter') { if (tag === 'BUTTON' || tag === 'A') return; e.preventDefault(); typeCh('\n'); }
        else if (e.key === 'Backspace') { e.preventDefault(); typeCh('\b'); }
        else if (e.key.length === 1) { if (e.key === ' ' && (tag === 'BUTTON' || tag === 'A')) return; e.preventDefault(); typeCh(e.key); }
      }
      else if (/^[1-9]$/.test(e.key) && +e.key <= I.steps.length) enter(+e.key - 1);
      else if (e.key === 'r' || e.key === 'R') enter(S.step);
      else if (e.key === 'l' || e.key === 'L') copyLink();
      else if (I.keys && I.keys[e.key.toLowerCase()]) pressKey(e.key.toLowerCase());
    });
    ['pointerdown', 'wheel', 'touchstart'].forEach(function (ev) { root.addEventListener(ev, function () { touched(); }, { passive: true }); });
    host.addEventListener('focusin', function () { touched(); });
    var againB = $('.fg-again'); if (againB) againB.addEventListener('click', function () { touched(); enter(S.step); });
    var copyB = $('.fg-copy');
    copyB.addEventListener('click', copyLink);
    function copyLink() {
      sync(true);
      var done = function () { copyB.textContent = 'Link copied'; setTimeout(function () { copyB.textContent = 'Copy a link to this state'; }, 1600); };
      try { if (root.navigator && navigator.clipboard) navigator.clipboard.writeText(root.location.href).then(done, function () {}); } catch (e) { /* a host without a clipboard */ }
    }

    /* ---- the scene's keys: {k: fn(fx, state, stepId)} or {k: {label, step, when(state), run}}: a button too, on that
       step while when() holds (a phone has no keys) ---- */
    var keyRun = function (k) { var v = I.keys && I.keys[k]; return typeof v === 'function' ? v : v && v.run; };
    function pressKey(k) { var f = keyRun(k), sid = (I.steps[S.step] || {}).id; if (!f) return; act(function () { f(fx, state, sid); }); ui(); sync(); }
    var keysEl = el('div', 'fg-keybtns'); $('.fg-step').appendChild(keysEl);
    function keyButtons() {
      var sid = (I.steps[S.step] || {}).id, want = Object.keys(I.keys || {}).filter(function (k) { var v = I.keys[k]; return v && v.label && (!v.step || v.step === sid) && (!v.when || v.when(state)); });
      var key = want.join(',') + '|' + sid; if (keysEl.getAttribute('data-k') === key) return;
      keysEl.setAttribute('data-k', key); keysEl.innerHTML = '';
      want.forEach(function (k) {
        var b = el('button', 'fg-btn', ''); b.type = 'button'; b.textContent = I.keys[k].label + ' (' + k.toUpperCase() + ')';
        b.addEventListener('click', function () { touched(); pressKey(k); });
        keysEl.appendChild(b);
      });
      keysEl.hidden = !want.length;
    }

    /* ---- deep links: #step=<id>&<knob>=<value>&part=<id> ---- */
    function hashOf() {
      var st = I.steps[S.step], q = [];
      if (st) q.push('step=' + encodeURIComponent(st.id));
      if (st && st.knob) q.push(encodeURIComponent(st.knob) + '=' + encodeURIComponent(state[st.knob]));
      if (S.pin) q.push('part=' + encodeURIComponent(S.pin));
      return q.join('&');
    }
    function sync(force) {
      if (tour.on && !force) return;
      try { root.history.replaceState(null, '', '#' + hashOf()); } catch (e) { /* a sandboxed host */ }
    }
    function parseHash(str) { // '#a=1&b=2' -> {a: '1', b: '2'}; a pair that does not decode (a link cut after a %) is left out
      var h = {}, dec = function (x) { try { return decodeURIComponent(x); } catch (e) { return null; } };
      String(str || '').replace(/^#/, '').split('&').forEach(function (kv) {
        var i = kv.indexOf('='), k = dec(i < 0 ? kv : kv.slice(0, i)), v = dec(i < 0 ? '' : kv.slice(i + 1));
        if (k && v != null) h[k] = v;
      });
      return h;
    }
    function fromHash(str) {
      var h = parseHash(str == null ? root.location.hash : str);
      if (!h.step && !h.part) return false;
      Object.keys(I.knobs || {}).forEach(function (n) {
        if (h[n] == null) return;
        var K = I.knobs[n];
        if (K.options) { var o = K.options.filter(function (x) { return String(x[0]) === h[n]; })[0]; if (o) state[n] = o[0]; }
        else { var v = Number(h[n]); if (isFinite(v) && v >= K.min && v <= K.max) state[n] = v; }
      });
      var i = stepIndex(I, h.step);
      if (I.steps.length) enter(i >= 0 ? i : 0);
      if (PART[h.part]) { S.pin = h.part; api.focus(h.part, { at: clock.now() }); }
      return true;
    }

    /* ---- the idle tour: a script of live actions; any input stops it, it comes back after 20 s ---- */
    var tour = { on: false, i: 0, timer: 0, idle: 0 };
    var SCRIPT = I.tour || (I.steps.length ? I.steps.map(function (s) { return [{ step: s.id }, 7000]; }) : parts.map(function (p) { return [{ hover: p.id }, 2400]; }).concat([[{ hover: null }, 1200]]));
    function run(a) {
      if (typeof a === 'function') { act(function () { a(fx, state); }); ui(); return; }
      if (a.step != null) { if (a.knob) state[a.knob[0]] = a.knob[1]; enter(stepIndex(I, a.step)); }
      else if (a.knob) setKnob(a.knob[0], a.knob[1], true);
      if (a.hover !== undefined) setHover(a.hover || '', 'tour');
    }
    function next() { if (!tour.on || !SCRIPT.length) return; var s = SCRIPT[tour.i % SCRIPT.length]; tour.i++; run(s[0]); tour.timer = setTimeout(next, s[1]); }
    function startTour() { if (RM || tour.on || clock.manual) return; tour.on = true; $('.fg-tour').hidden = false; next(); }
    function stopTour() { if (!tour.on) return; tour.on = false; clearTimeout(tour.timer); $('.fg-tour').hidden = true; setHover(''); ui(); sync(); }
    function touched() { if (tour.on) stopTour(); clearTimeout(tour.idle); if (!RM && !clock.manual) tour.idle = setTimeout(startTour, 20000); }
    $('.fg-tour button').addEventListener('click', function () { touched(); });

    /* ---- walk: every state, at rest, for showtime check (and the tests) ---- */
    function walk() {
      clock.manual = true; stopTour(); clearTimeout(tour.idle);
      var probs = [], states = 0;
      var visibleTexts = function () {
        var out = [], base = stage.getBoundingClientRect(), kk = k;
        var add = function (sel, kind) {
          ldHost.querySelectorAll(sel).forEach(function (g) {
            if (g.getAttribute('visibility') !== 'visible' || +g.getAttribute('opacity') < 0.5) return;
            // the plate (a label) or the pill (a tag): the leader of a label is not text
            var plate = g.querySelector('rect'), r = (plate || g).getBoundingClientRect(); if (!r.width) return;
            var t = [].slice.call(g.querySelectorAll('text')).filter(function (x) { return x.getAttribute('visibility') !== 'hidden' && +(x.getAttribute('opacity') || 1) > 0.5 && x.textContent; }).map(function (x) { return x.textContent; }).join(' / ');
            out.push({ kind: kind, text: t, x: (r.left - base.left) / kk, y: (r.top - base.top) / kk, w: r.width / kk, h: r.height / kk });
          });
        };
        add('[data-ld-tag]', 'tag'); add('[data-ld-label]', 'label');
        return out;
      };
      var check = function (where) {
        states++;
        draw();
        var tx = visibleTexts(), box = [Math.max(crop[0], SAFE[0]), Math.max(crop[1], SAFE[1]), Math.min(crop[2], SAFE[2]), Math.min(crop[3], SAFE[3])];
        tx.forEach(function (a, i) {
          if (a.x < box[0] - 1 || a.y < box[1] - 1 || a.x + a.w > box[2] + 1 || a.y + a.h > box[3] + 1) probs.push({ code: 'figure_text_cut', where: where, text: a.text, message: '"' + a.text + '" is cut by the figure\'s frame' });
          for (var j = i + 1; j < tx.length; j++) {
            var b = tx[j], ox = Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x), oy = Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y);
            if (ox > 4 && oy > 4) probs.push({ code: 'figure_text_overlap', where: where, text: a.text + ' | ' + b.text, message: '"' + a.text + '" and "' + b.text + '" overlap' });
          }
        });
        var R = readouts();
        R.rows.forEach(function (r) { if (/NaN|undefined|Infinity|null/.test(String(r.v) + ' ' + String(r.u == null ? '' : r.u))) probs.push({ code: 'figure_readout', where: where, text: r.k, message: 'readout "' + r.k + '" shows ' + r.v }); });
        // the scene's own story check: what the board, the step and the readouts say must agree (interactive.agree)
        if (I.agree) {
          var st0 = I.steps[S.step] || {}, said = tx.filter(function (x) { return x.kind === 'tag'; }).map(function (x) { return x.text; });
          (I.agree(state, st0.id, { board: said, step: stepText(st0, state), readouts: R.rows }) || []).forEach(function (m) {
            probs.push({ code: 'figure_story', where: where, text: String(m), message: String(m) });
          });
        }
      };
      // the link of a state, followed: it must open the same step, knob value and pinned part
      var linkBack = function (where) {
        var st0 = I.steps[S.step], want = { step: S.step, knob: st0 && st0.knob ? String(state[st0.knob]) : null, pin: S.pin }, h = hashOf();
        var keep = st0 && st0.knob ? state[st0.knob] : null;
        fromHash('#' + h);
        var st1 = I.steps[S.step], got = { step: S.step, knob: st1 && st1.knob ? String(state[st1.knob]) : null, pin: S.pin };
        if (got.step !== want.step || got.knob !== want.knob || got.pin !== want.pin) {
          probs.push({ code: 'figure_link', where: where, text: h, message: 'the link #' + h + ' opens another state (step ' + ((I.steps[got.step] || {}).id) + (got.knob != null ? ', ' + got.knob : '') + ')' });
          S.step = want.step; if (st0 && st0.knob) state[st0.knob] = keep;
        }
      };
      var seenIds = {};
      I.steps.forEach(function (st) { if (seenIds['s' + st.id]) probs.push({ code: 'figure_link', where: 'steps', text: 'step ' + st.id, message: 'two steps share the id "' + st.id + '": a link to the second opens the first' }); seenIds['s' + st.id] = 1; });
      parts.forEach(function (p) { if (seenIds['p' + p.id]) probs.push({ code: 'figure_link', where: 'parts', text: 'part ' + p.id, message: 'two parts share the id "' + p.id + '"' }); seenIds['p' + p.id] = 1; });
      // a knob's values: every option; a range of up to 25 values all of them, a longer one 9 points across it
      var valuesOf = function (K) {
        if (!K) return [null];
        if (K.options) return K.options.map(function (o) { return o[0]; });
        var step = K.step || 1, n = Math.floor((K.max - K.min) / step + 1e-9) + 1, out = [];
        if (n <= 25) for (var j = 0; j < n; j++) out.push(+(K.min + j * step).toFixed(6));
        else { for (var q = 0; q <= 8; q++) out.push(+(K.min + Math.round(q * (n - 1) / 8) * step).toFixed(6)); if (out.indexOf(K.default) < 0) out.push(K.default); }
        return out;
      };
      var keyNames = Object.keys(I.keys || {});
      var safely = function (where, fn) { try { fn(); } catch (e) { probs.push({ code: 'figure_error', where: where, message: String(e && e.message || e) }); } };
      safely('start', function () { check('start'); });
      I.steps.forEach(function (st, i) {
        var K = st.knob && I.knobs[st.knob], vals = valuesOf(K);
        vals.forEach(function (v) {
          var where = 'step ' + st.id + (v != null ? ' ' + st.knob + '=' + v : '');
          safely(where, function () {
            if (v != null) state[st.knob] = v;
            enter(i); check(where); linkBack(where);
            parts.forEach(function (p) { setHover(p.id); check(where + ', ' + p.id + ' hovered'); });
            setHover('');
            // the scene's keys (an answer it asks for), each from this state
            keyNames.forEach(function (kn) {
              safely(where + ', key ' + kn, function () {
                if (v != null) state[st.knob] = v;
                enter(i);
                act(function () { keyRun(kn)(fx, state, st.id); }); ui();
                check(where + ', key ' + kn.toUpperCase());
              });
            });
          });
        });
        if (K) state[st.knob] = K.default;
      });
      if (!I.steps.length) parts.forEach(function (p) { safely(p.id, function () { setHover(p.id); check(p.id + ' hovered'); }); });
      setHover('');
      // touch: a typed line (letters, a digit, a space, Return, Backspace) and every pressable part, from the first step
      if (TYPE) safely('typing', function () { if (I.steps.length) enter(0); 'Hi 2\n\bok.'.split('').forEach(function (ch) { act(function () { TYPE.run(fx, ch, state, (I.steps[S.step] || {}).id); }); }); ui(); check('typed "Hi 2", Return, Backspace, "ok."'); });
      parts.forEach(function (p) { if (p.press) safely(p.id + ' pressed', function () { if (I.steps.length) enter(0); pressPart(p.id); check(p.id + ' pressed'); }); });
      S.pin = '';
      var seen = {}; probs = probs.filter(function (p) { var key = p.code + '|' + p.text; if (seen[key]) return false; seen[key] = 1; return true; });
      return { states: states, problems: probs, keys: keyNames.length, typing: !!TYPE, presses: parts.filter(function (p) { return p.press; }).length, steps: I.steps.length, parts: parts.length, knobs: Object.keys(I.knobs || {}).length, theme: api.report.theme, warnings: api.report.warnings.slice() };
    }

    /* ---- start: the board is already there and moving ---- */
    var fig0 = { api: api, enter: enter, setKnob: setKnob, setHover: setHover, pin: pin, walk: walk, state: state, S: S, cost: cost, readouts: readouts,
      tour: function () { return tour.on; }, hash: hashOf, phone: function () { return phone; }, type: typeCh, press: pressPart };
    api.ready.then(function () {
      fit();
      // the tour's first wait: opts.tourAfter, or window.SHOWTIME_TEST_TOUR_AFTER (tests), else 2.5 s
      var after = opts.tourAfter != null ? opts.tourAfter : (typeof root.SHOWTIME_TEST_TOUR_AFTER === 'number' ? root.SHOWTIME_TEST_TOUR_AFTER : 2500);
      if (!fromHash()) { if (I.steps.length) enter(0); if (!RM) tour.idle = setTimeout(startTour, after); }
      else if (!RM) tour.idle = setTimeout(startTour, 20000);
      ui(); wake();
    });
    fit(); ui(); wake();
    // framed with #embed (an iframe, or <showtime-xray> from embed.js): tell the host how tall the page is
    var EMBED = false;
    try { EMBED = root.self !== root.top && /(^#|[&_])embed([&_]|$)/.test(root.location.hash || ''); } catch (e) { EMBED = false; }
    if (EMBED && root.ResizeObserver) {
      D.documentElement.setAttribute('data-fg-embed', '');
      var lastH = 0, lastGrow = -1e9;
      new ResizeObserver(function () {
        var h = Math.ceil(app.getBoundingClientRect().height + 24), now = root.performance ? performance.now() : 0;
        if (Math.abs(h - lastH) < 2 || (h < lastH && lastH - h < 24 && now - lastGrow < 1200)) return;   // a host's scrollbar flip
        if (h > lastH) lastGrow = now;
        lastH = h;
        try { root.parent.postMessage({ type: 'showtime-xray:size', height: h }, '*'); } catch (e) { /* no host */ }
      }).observe(app);
    }
    Figure.current = fig0;
    return fig0;
  }

  var Figure = root.Figure;
  Figure.mount = mount;
})(typeof window !== 'undefined' ? window : this);

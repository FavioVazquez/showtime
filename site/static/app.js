/* showtime site: theme, menu, gallery previews and players, filters, copy buttons, docs search and contents.
   No trackers, no network requests beyond this site's own files. */
(function () {
  var root = document.documentElement;
  var base = document.body.getAttribute('data-root') || '';
  if (!/^(?:\.\.?\/|[\w.-]+\/)*$/.test(base)) base = '';
  // media and script URLs from data-* attributes: http(s) only (or file: when the site itself is opened from disk)
  function safeSrc(u) {
    try {
      var x = new URL(u, location.href);
      return x.protocol === 'http:' || x.protocol === 'https:' || (x.protocol === 'file:' && location.protocol === 'file:') ? x.href : '';
    } catch (e) { return ''; }
  }
  var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  var canHover = matchMedia('(hover: hover) and (pointer: fine)').matches;
  function store(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } }

  // ---------- theme: saved choice, else the system; diagrams follow it
  function current() { return root.getAttribute('data-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'); }
  function swapArt() {
    var t = current();
    document.querySelectorAll('[data-themed]').forEach(function (el) {
      ['src', 'srcset'].forEach(function (a) {
        var v = el.getAttribute(a); if (!v) return;
        var n = v.replace(/-(light|dark)\.svg/, '-' + t + '.svg'); if (n !== v) el.setAttribute(a, n);
      });
    });
    var b = document.querySelector('.theme-btn'); if (b) b.setAttribute('aria-label', t === 'dark' ? 'Switch to light theme' : 'Switch to dark theme');
  }
  var saved = store('st-theme'); if (saved === 'light' || saved === 'dark') root.setAttribute('data-theme', saved);
  swapArt();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', swapArt);
  document.addEventListener('click', function (e) {
    if (!e.target.closest('.theme-btn')) return;
    var next = current() === 'dark' ? 'light' : 'dark'; root.setAttribute('data-theme', next); store('st-theme', next); swapArt();
  });

  // ---------- menus
  document.querySelectorAll('.menu-btn').forEach(function (b) {
    b.addEventListener('click', function () { var o = document.querySelector('.nav').classList.toggle('open'); b.setAttribute('aria-expanded', o); });
  });
  document.querySelectorAll('.side-toggle').forEach(function (b) {
    b.addEventListener('click', function () {
      var o = document.querySelector('.side').classList.toggle('open'); b.setAttribute('aria-expanded', o);
      b.lastElementChild.textContent = o ? '−' : '+';
    });
  });

  // ---------- copy buttons
  document.querySelectorAll('.copy').forEach(function (box) {
    var b = document.createElement('button'); b.type = 'button'; b.textContent = 'Copy';
    b.addEventListener('click', function () {
      var txt = box.querySelector('code').innerText.split('\n').filter(function (l) { return l.charAt(0) !== '#'; }).join('\n').trim();
      (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject()).then(function () { b.textContent = 'Copied'; }, function () { b.textContent = 'Select to copy'; });
      setTimeout(function () { b.textContent = 'Copy'; }, 1600);
    });
    box.appendChild(b);
  });

  // ---------- the film on the landing page: a silent teaser loops (poster only when motion is reduced);
  // "Watch the film" swaps in the full film with sound
  var teaser = document.querySelector('.screen video.teaser');
  if (teaser) {
    if (reduce) { teaser.removeAttribute('autoplay'); teaser.pause(); teaser.preload = 'none'; }
    else { teaser.autoplay = true; teaser.play().catch(function () {}); }
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('button.watch'); if (!b) return;
    var screen = b.closest('.screen');
    var v = document.createElement('video'); v.controls = true; v.playsInline = true; v.preload = 'auto';
    v.src = safeSrc(b.getAttribute('data-film')); v.poster = safeSrc(b.getAttribute('data-poster')); v.setAttribute('aria-label', b.getAttribute('data-label') || 'The showtime film');
    if (teaser) teaser.remove();
    screen.classList.add('playing'); screen.insertBefore(v, b); v.play().catch(function () {}); v.focus();
  });

  // ---------- gallery: silent preview on hover, the full video with sound on click
  function stopOthers(except) { document.querySelectorAll('.frame video').forEach(function (v) { if (v !== except && !v.muted) v.pause(); }); }
  function preview(frame, on) {
    var clip = frame.getAttribute('data-clip'); if (!clip || frame.classList.contains('playing')) return;
    var el = frame.querySelector('.loop');
    if (on) {
      if (!el) {
        if (/\.mp4$/.test(clip)) { el = document.createElement('video'); el.muted = true; el.loop = true; el.playsInline = true; el.setAttribute('aria-hidden', 'true'); el.preload = 'auto'; }
        else { el = document.createElement('img'); el.alt = ''; }
        el.className = 'loop'; el.src = safeSrc(clip); frame.insertBefore(el, frame.querySelector('.open'));
        var show = function () { if (frame.matches(':hover') || frame.contains(document.activeElement)) frame.classList.add('previewing'); };
        if (el.tagName === 'VIDEO') el.addEventListener('playing', show); else el.addEventListener('load', show);
      }
      if (el.tagName === 'VIDEO') { el.play().catch(function () {}); } else frame.classList.add('previewing');
    } else {
      frame.classList.remove('previewing');
      if (el && el.tagName === 'VIDEO') setTimeout(function () { if (!frame.classList.contains('previewing')) el.pause(); }, 350);
    }
  }
  if (canHover && !reduce) {
    document.querySelectorAll('.frame[data-clip]').forEach(function (f) {
      f.addEventListener('mouseenter', function () { preview(f, true); });
      f.addEventListener('mouseleave', function () { preview(f, false); });
      f.addEventListener('focusin', function () { preview(f, true); });
      f.addEventListener('focusout', function () { preview(f, false); });
    });
  }
  document.addEventListener('click', function (e) {
    var b = e.target.closest('button.open'); if (!b) return;
    var frame = b.parentNode, still = frame.querySelector('.still');
    var v = document.createElement('video'); v.controls = true; v.playsInline = true; v.preload = 'auto'; v.src = safeSrc(b.getAttribute('data-full'));
    if (still) v.poster = safeSrc(still.getAttribute('src'));
    v.setAttribute('aria-label', b.getAttribute('aria-label').replace(/^Play /, ''));
    frame.classList.remove('previewing'); frame.classList.add('playing');
    frame.querySelectorAll('.loop,.hint,.open').forEach(function (n) { n.remove(); });
    frame.appendChild(v); stopOthers(v); v.play().catch(function () {}); v.focus();
  });

  // filters (tabs), with the choice kept in the address
  var tabs = document.querySelectorAll('.tab[data-filter]');
  function applyFilter(tag) {
    tabs.forEach(function (c) { c.setAttribute('aria-pressed', c.getAttribute('data-filter') === tag); });
    var shown = 0;
    document.querySelectorAll('.film[data-tags]').forEach(function (c) {
      var on = tag === 'all' || c.getAttribute('data-tags').split(' ').indexOf(tag) >= 0; c.hidden = !on; if (on) shown++;
    });
    var s = document.querySelector('.count'); if (s) s.textContent = shown + (shown === 1 ? ' video' : ' videos');
  }
  if (tabs.length) {
    tabs.forEach(function (c) { c.addEventListener('click', function () { var t = c.getAttribute('data-filter'); applyFilter(t); try { history.replaceState(null, '', t === 'all' ? location.pathname : '#' + t); } catch (e) {} }); });
    var h = (location.hash || '').slice(1); applyFilter(document.querySelector('.tab[data-filter="' + h + '"]') ? h : 'all');
  }

  // ---------- docs: contents that follow the reading position
  var toc = document.querySelectorAll('.toc a');
  if (toc.length && 'IntersectionObserver' in window) {
    var map = {}; toc.forEach(function (a) { map[a.getAttribute('href').slice(1)] = a; });
    var visible = {};
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { visible[en.target.id] = en.isIntersecting; });
      var heads = document.querySelectorAll('.prose h2[id]'), cur = null;
      for (var i = 0; i < heads.length; i++) { if (heads[i].getBoundingClientRect().top < 140) cur = heads[i].id; }
      if (!cur && heads.length) cur = heads[0].id;
      toc.forEach(function (a) { a.classList.toggle('on', a.getAttribute('href') === '#' + cur); });
    }, { rootMargin: '-80px 0px -60% 0px' });
    document.querySelectorAll('.prose h2[id]').forEach(function (h) { io.observe(h); });
    window.addEventListener('scroll', function () { io.takeRecords(); }, { passive: true });
  }

  // ---------- docs search: the index is a script (so it also works from disk), loaded on first use.
  // Each page is {t: title, u: page, s: [[heading, anchor, text], ...]}, one section per h2/h3 (site/build.py
  // search_entry); a hit links to the section that matches best.
  var input = document.querySelector('.search input'), box = document.querySelector('.results');
  if (!input) return;
  var index = null, sel = -1;
  // The one normalisation rule, shared with plain() in site/build.py (SEARCH_SEPARATORS; change both together):
  // runs of ` * _ > | # - become one space, so pr-video, SHOWTIME_MCP_TOOLS and #t= match the indexed text.
  var SEP = /[`*_>|#-]+/g;
  function norm(s) { return s.toLowerCase().replace(SEP, ' ').replace(/\s+/g, ' ').trim(); }
  var avg = 1;   // the mean section length, so a long section (a whole release in the changelog) does not win on bulk
  function prep(list) {
    var n = 0, len = 0;
    list.forEach(function (d) { d.nt = norm(d.t); d.s.forEach(function (c) { c.nh = norm(c[0]); c.nx = c[2].toLowerCase(); n++; len += c.nx.length; }); });
    avg = Math.max(1, len / Math.max(1, n));
    return list;
  }
  function load(cb) {
    if (index) return cb();
    if (window.SHOWTIME_SEARCH) { index = prep(window.SHOWTIME_SEARCH); return cb(); }
    var s = document.createElement('script'); s.src = safeSrc(base + 'search-index.js');
    s.onload = function () { index = prep(window.SHOWTIME_SEARCH || []); cb(); }; document.head.appendChild(s);
  }
  function esc(s) { return s.replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  // matches of w in x, up to 10; one inside a word (review in previewing) counts a quarter
  function count(x, w) {
    var i = x.indexOf(w), n = 0, k = 0;
    while (i >= 0 && k < 10) { k++; n += i && /[a-z0-9]/.test(x.charAt(i - 1)) ? 0.25 : 1; i = x.indexOf(w, i + w.length); }
    return n;
  }
  function run() {
    var q = norm(input.value); sel = -1;
    if (q.length < 2) { box.hidden = true; box.innerHTML = ''; return; }
    var terms = q.split(' '), phrase = terms.length > 1 ? q : '', hits = [];
    var mark = new RegExp('(' + terms.slice().sort(function (a, b) { return b.length - a.length; })
      .map(function (w) { return w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }).join('|') + ')', 'i');
    index.forEach(function (d) {
      // every term must be somewhere on the page (title, a heading or the text)
      var ok = terms.every(function (w) { return d.nt.indexOf(w) >= 0 || d.s.some(function (c) { return c.nh.indexOf(w) >= 0 || c.nx.indexOf(w) >= 0; }); });
      if (!ok) return;
      // the best section: the most terms, then its score (a heading match, then the text matches weighed by the
      // section's length, then the whole phrase); the page ranks by its best section plus its title
      var best = d.s[0], bestHas = -1, bestScore = -1, total = 0;
      d.s.forEach(function (c) {
        var has = 0, s = 0, k = 1.2 * (0.5 + 0.5 * c.nx.length / avg);
        terms.forEach(function (w) {
          var h = count(c.nh, w), n = count(c.nx, w); if (h || n) has++;
          s += 3 * Math.min(h, 1) + n * 2.2 / (n + k); total += n;
        });
        if (phrase && (c.nh.indexOf(phrase) >= 0 || c.nx.indexOf(phrase) >= 0)) s += 3;
        if (has > bestHas || (has === bestHas && s > bestScore)) { best = c; bestHas = has; bestScore = s; }
      });
      var inTitle = 0; terms.forEach(function (w) { inTitle += Math.min(count(d.nt, w), 1); });
      var score = bestScore + 6 * inTitle + (phrase && d.nt.indexOf(phrase) >= 0 ? 4 : 0) + (bestHas === terms.length ? 2 : 0)
        + Math.log(1 + Math.min(total, 30)) / 2;   // a page that keeps coming back to the words
      // a page whose title holds every term opens at its top
      if (inTitle === terms.length) best = d.s[0];
      hits.push([score, d, best]);
    });
    hits.sort(function (a, b) { return b[0] - a[0]; });
    box.innerHTML = hits.slice(0, 10).map(function (r) {
      var d = r[1], c = r[2], x = c[2], lx = c.nx, i = lx.indexOf(phrase || terms[0]);
      if (i < 0) terms.some(function (w) { i = lx.indexOf(w); return i >= 0; });
      var snip = i >= 0 ? x.slice(Math.max(0, i - 50), i + 110) : x.slice(0, 140);
      var s = snip.split(mark).map(function (part, k) { return k % 2 ? '<mark>' + esc(part) + '</mark>' : esc(part); }).join('');
      var title = esc(d.t) + (c[1] ? ' <span class="muted">›</span> ' + esc(c[0]) : '');
      return '<a href="' + esc(base + d.u + (c[1] ? '#' + c[1] : '')) + '"><b>' + title + '</b><small>' + (i > 50 ? '…' : '') + s + '…</small></a>';
    }).join('') || '<p class="muted" style="padding:10px 11px;margin:0;font-size:.9rem">No guide mentions that.</p>';
    box.hidden = false;
  }
  input.addEventListener('focus', function () { load(function () {}); });
  input.addEventListener('input', function () { load(run); });
  input.addEventListener('keydown', function (e) {
    var items = box.querySelectorAll('a'); if (!items.length) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length; items.forEach(function (a, i) { a.classList.toggle('sel', i === sel); }); items[sel].scrollIntoView({ block: 'nearest' }); }
    if (e.key === 'Enter' && sel >= 0) { location.href = items[sel].href; }
    if (e.key === 'Escape') { box.hidden = true; input.blur(); }
  });
  document.addEventListener('click', function (e) { if (!e.target.closest('.search')) box.hidden = true; });
  document.addEventListener('keydown', function (e) { if (e.key === '/' && !/INPUT|TEXTAREA/.test(document.activeElement.tagName)) { e.preventDefault(); input.focus(); } });
})();

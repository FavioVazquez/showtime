/* <showtime-xray>: an X-ray's live page on any web page, with one tag (runtime/xray-live/embed.js).
 *
 *   <script src="https://faviovazquez.github.io/showtime/xray/embed.js"></script>
 *   <showtime-xray src="typewriter-live.html" ratio="16/9" title="A typewriter, seen through"
 *                  poster="typewriter.jpg" hit="4"></showtime-xray>
 *
 * The live page (`showtime export html <xray project> --interactive`) is one offline file; this element shows its
 * poster (or a plain plate) with a "Play it live" button and loads the page in a frame only when the viewer asks,
 * so a page with many X-rays stays light. With `autoload` it loads at once. The frame opens on the page's embed
 * layout (#embed: the film fits the width) at hit N when `hit` is set, and takes the height the page reports
 * (postMessage {type: 'showtime-xray:size', height}). No dependencies; nothing is fetched until the frame loads.
 * Style hooks (light DOM): .stx, .stx-poster, .stx-play, .stx-frame. el.load() loads it from script.
 */
(function () {
  'use strict';
  var W = window, D = document;
  if (!W.customElements || W.customElements.get('showtime-xray')) return;

  var CSS = 'showtime-xray{display:block;max-width:100%}' +
    '.stx{position:relative;width:100%;border-radius:8px;overflow:hidden;background:#070b16;color:#e9f3ff;font:600 15px/1.3 system-ui,-apple-system,"Segoe UI",sans-serif}' +
    '.stx-poster{position:relative;width:100%;background:#070b16 center/cover no-repeat;display:flex;align-items:center;justify-content:center}' +
    '.stx-plate{position:absolute;left:16px;top:14px;right:16px;display:flex;flex-direction:column;gap:4px;text-shadow:0 1px 8px rgba(0,0,0,.6)}' +
    '.stx-mark{font:700 12px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.14em;text-transform:uppercase;color:#ff4a3d}' +
    '.stx-play{appearance:none;border:0;border-radius:999px;padding:12px 20px 12px 16px;background:#ff4a3d;color:#fff;font:700 15px/1 system-ui,-apple-system,"Segoe UI",sans-serif;' +
    'display:inline-flex;align-items:center;gap:8px;cursor:pointer;box-shadow:0 6px 24px rgba(0,0,0,.35)}' +
    '.stx-play:hover{background:#ff6a5e}.stx-play:focus-visible{outline:3px solid #8fd3ff;outline-offset:3px}' +
    '.stx-play svg{width:18px;height:18px}' +
    '.stx-frame{display:block;width:100%;border:0;background:#070b16}';

  function style() {
    if (D.getElementById('stx-css')) return;
    var s = D.createElement('style'); s.id = 'stx-css'; s.textContent = CSS;
    (D.head || D.documentElement).appendChild(s);
  }
  function ratioOf(v) {                          // "16/9", "16:9", "1.777" -> width / height
    var m = /^\s*(\d+(?:\.\d+)?)\s*[/:x]\s*(\d+(?:\.\d+)?)\s*$/.exec(String(v || ''));
    if (m && +m[2] > 0) return +m[1] / +m[2];
    var n = parseFloat(v);
    return n > 0 ? n : 16 / 9;
  }

  // one listener for every frame on the page: the page in each frame reports its height
  var frames = [];
  W.addEventListener('message', function (ev) {
    var d = ev.data;
    if (!d || d.type !== 'showtime-xray:size' || !(d.height > 0)) return;
    for (var i = 0; i < frames.length; i++) {
      if (frames[i].contentWindow === ev.source) { frames[i].style.height = Math.min(20000, Math.ceil(d.height)) + 'px'; return; }
    }
  });

  class ShowtimeXray extends HTMLElement {
    connectedCallback() {
      if (this._built) return;
      this._built = true;
      style();
      var self = this, r = ratioOf(this.getAttribute('ratio'));
      var box = D.createElement('div'); box.className = 'stx';
      var poster = D.createElement('div'); poster.className = 'stx-poster';
      poster.style.aspectRatio = String(r);
      var pic = this.getAttribute('poster');
      if (pic) poster.style.backgroundImage = 'url("' + pic.replace(/["\\\n]/g, '') + '")';
      var plate = D.createElement('div'); plate.className = 'stx-plate';
      var mark = D.createElement('span'); mark.className = 'stx-mark'; mark.textContent = 'X-ray · live';
      var ttl = D.createElement('span'); ttl.textContent = this.getAttribute('title') || '';
      plate.appendChild(mark); if (ttl.textContent) plate.appendChild(ttl);
      var b = D.createElement('button'); b.type = 'button'; b.className = 'stx-play';
      b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M7.5 4.8v14.4c0 .8.9 1.3 1.6.9l11.2-7.2c.6-.4.6-1.3 0-1.7L9.1 3.9c-.7-.4-1.6.1-1.6.9z"/></svg>';
      b.appendChild(D.createTextNode('Play it live'));
      b.setAttribute('aria-label', 'Play it live' + (ttl.textContent ? ': ' + ttl.textContent : ''));
      b.addEventListener('click', function () { self.load(true); });
      poster.appendChild(plate); poster.appendChild(b);
      box.appendChild(poster);
      this.textContent = '';
      this.appendChild(box);
      this._box = box; this._ratio = r;
      if (this.hasAttribute('autoload')) this.load(false);
    }
    load(focus) {
      if (!this._box || this._frame) return this._frame || null;
      var src = this.getAttribute('src');
      if (!src) return null;
      var hit = parseInt(this.getAttribute('hit'), 10);
      var f = D.createElement('iframe');
      f.className = 'stx-frame';
      f.title = this.getAttribute('title') || 'X-ray, live';
      f.setAttribute('allow', 'autoplay; fullscreen; clipboard-write');
      f.src = src.split('#')[0] + '#embed' + (hit > 0 ? '_hit' + hit : '');
      // until the page reports its height: the film plus room for its controls
      var w = this._box.clientWidth || 640;
      f.style.height = Math.round(w / this._ratio + (w < 700 ? 360 : 300)) + 'px';
      frames.push(f);
      this._box.textContent = '';
      this._box.appendChild(f);
      this._frame = f;
      if (focus) f.addEventListener('load', function () { try { f.focus(); } catch (e) { /* cross-origin */ } }, { once: true });
      this.dispatchEvent(new CustomEvent('showtime-xray:load', { bubbles: true }));
      return f;
    }
  }
  W.customElements.define('showtime-xray', ShowtimeXray);
})();

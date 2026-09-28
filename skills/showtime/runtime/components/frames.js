// browser-frame and device-frame: put a screenshot, a video or live DOM inside original,
// brand-free browser chrome or a phone / tablet / laptop body, then scroll through it,
// push the camera into a region, and enter with a gentle 3D settle. Pure CSS, no images.
//
//   <div data-st="browser-frame" data-url="northwind.dev/pricing" data-src="shots/pricing-full.png"
//        data-scroll='[{"at":1.5,"to":0.6,"dur":2.2}]'></div>
//   <div data-st="device-frame" data-model="phone" data-src="shots/app.png" data-tilt="[8,-14]"></div>
//   <div data-st="device-frame" data-model="laptop"><video data-st src="demo.webm" muted></video></div>
//
// scroll `to`: 0..1 = fraction of the scrollable height, a number > 1 = pixels of the page
// image at its displayed size, or "#id" = bring that element (inside live DOM) to the top.
// zoom: [{at, scale, x, y, dur}] pushes the camera toward x/y (% of the view) and back.
// drift: a still screenshot (data-src image, no scroll/zoom steps) gets a slow push-in so the
// shot never reads as a frozen frame ("auto", the default); "none" turns it off, a number is the
// scale gained per second (auto = 0.012, capped at +8 %).
// camera: "page" (default: zoom pushes into the page under fixed chrome) or "frame" (the whole
// window scales, chrome included, and its edges leave the picture).
// Children next to a data-src screenshot/video stay as an overlay on top of it (a highlight ring,
// a cursor target), scrolling and zooming with the page.
import { define, h, clamp, ease, lerp, token } from './core.js';

function mountContent(el, o, host) {
  const kids = Array.from(el.childNodes);
  let media = null;
  if (o.src) {
    const isVideo = /\.(mp4|webm|mov|m4v)(\?|$)/i.test(o.src);
    media = isVideo ? h('video', { src: o.src, muted: true, playsinline: true, 'data-st': '' }) : h('img', { src: o.src, alt: '', decoding: 'sync' });
    host.append(media);
    // children given with a src are kept as an overlay above the media (they used to vanish)
    const real = kids.filter((k) => k.nodeType === 1 || (k.nodeType === 3 && k.nodeValue.trim()));
    if (real.length) host.append(h('div', { class: 'st-frame-overlay' }, ...kids));
  } else {
    for (const k of kids) host.append(k);
    media = host.querySelector('img, video');
  }
  return media;
}

function driftRate(o) {
  if (o.drift === 'none' || o.drift === false || o.drift === 'off') return 0;
  if (o.drift == null || o.drift === 'auto' || o.drift === true) {
    const still = !!o.src && !/\.(mp4|webm|mov|m4v)(\?|$)/i.test(o.src);
    const steps = (Array.isArray(o.scroll) && o.scroll.length) || (Array.isArray(o.zoom) && o.zoom.length);
    return still && !steps ? 0.012 : 0;
  }
  return Math.max(0, Number(o.drift) || 0);
}

async function decodeAll(root) {
  for (const img of root.querySelectorAll('img')) {
    if (img.decode) { try { await img.decode(); } catch { /* broken image: layout still works */ } }
  }
}

function scroller(o, view, page, motion, frameEl) {
  const M = ease(motion.easeMove);
  const drift = driftRate(o);
  const steps = (Array.isArray(o.scroll) ? o.scroll : []).map((s) => ({ at: Number(s.at) || 0, to: s.to, dur: Number(s.dur) || 1.4 }));
  const zooms = (Array.isArray(o.zoom) ? o.zoom : []).map((z) => ({ at: Number(z.at) || 0, scale: Number(z.scale) || 1.6, x: Number(z.x ?? 50), y: Number(z.y ?? 50), dur: Number(z.dur) || 0.9 }));
  const resolve = (to) => {
    const max = Math.max(0, page.scrollHeight - view.clientHeight);
    if (typeof to === 'string' && to.startsWith('#')) {
      const t = page.querySelector(to);
      return t ? clamp(t.offsetTop, 0, max) : 0;
    }
    const v = Number(to) || 0;
    return v <= 1 ? v * max : clamp(v, 0, max);
  };
  let targets = null;
  // scroll targets need the page's real height: measured in setup (clip forced visible, images
  // decoded), and again later if that measurement saw no scrollable height
  const prime = () => {
    const max = Math.max(0, page.scrollHeight - view.clientHeight);
    if (view.clientHeight > 0 && page.scrollHeight > 0) targets = steps.map((s) => resolve(s.to));
    return max;
  };
  const fn = (lt) => {
    if (!targets || (targets.every((v) => v === 0) && steps.some((s) => s.to !== 0 && s.to !== '0'))) prime();
    if (!targets) targets = steps.map(() => 0);
    let y = 0;
    steps.forEach((s, i) => { if (lt >= s.at) y = lerp(y, targets[i], M(clamp((lt - s.at) / s.dur))); });
    page.style.transform = `translateY(${(-y).toFixed(2)}px)`;
    // camera push: scale about the chosen point, eased in and held until the next zoom step
    let sc = drift ? 1 + Math.min(0.08, drift * Math.max(0, lt)) : 1, zx = 50, zy = drift ? 42 : 50;
    for (const z of zooms) {
      if (lt < z.at) break;
      const p = M(clamp((lt - z.at) / z.dur));
      sc = lerp(sc, z.scale, p); zx = lerp(zx, z.x, p); zy = lerp(zy, z.y, p);
    }
    if (o.camera === 'frame' && frameEl) {
      // the whole window moves: scale the frame (after its entrance transform), not the page
      view.style.transform = '';
      if (sc !== 1) {
        frameEl.style.transformOrigin = `${zx.toFixed(2)}% ${zy.toFixed(2)}%`;
        frameEl.style.transform = `${frameEl.style.transform || ''} scale(${sc.toFixed(4)})`.trim();
      }
    } else {
      view.style.transformOrigin = `${zx.toFixed(2)}% ${zy.toFixed(2)}%`;
      view.style.transform = sc !== 1 ? `scale(${sc.toFixed(4)})` : '';
    }
    return steps.length || zooms.length ? Math.max(0, ...steps.map((s) => s.at + s.dur), ...zooms.map((z) => z.at + z.dur)) : 0;
  };
  fn.prime = prime;
  fn.steps = steps;
  fn.targets = () => targets;
  return fn;
}

/** Measure scroll targets now; say so when a scroll step cannot move (the page is not taller). */
async function primeScroll(name, el, content, scroll) {
  await decodeAll(content);
  const max = scroll.prime();
  const t = scroll.targets() || [];
  scroll.steps.forEach((s, i) => {
    if ((Number(s.to) > 0 || (typeof s.to === 'string' && s.to !== '0')) && !(t[i] > 0.5)) {
      console.warn(`[showtime] ${name}: scroll step at ${s.at}s (to ${JSON.stringify(s.to)}) moves 0 px: the page is only ${Math.round(max)} px taller than the view (use a full-page capture, or a zoom step instead)`);
    }
  });
}

function entrance(el, o, motion) {
  const E = ease('spring(0.9,0.82)');
  const tilt = Array.isArray(o.tilt) ? o.tilt : [0, 0];
  return (lt) => {
    if (o.enter === 'none') { el.style.transform = tilt[0] || tilt[1] ? `perspective(1400px) rotateX(${tilt[0]}deg) rotateY(${tilt[1]}deg)` : ''; return; }
    const p = E(clamp(lt / Math.max(0.3, motion.durIn * 1.6)));
    const rx = lerp(tilt[0] + 14, tilt[0], p), ry = lerp(tilt[1] * 1.3, tilt[1], p);
    let bob = 0;
    if (o.float) bob = Math.sin((lt - 1) * (Math.PI * 2) / 4.5) * 0.5 * clamp(lt - 1);
    el.style.opacity = clamp(lt / 0.25).toFixed(3);
    el.style.transform = `perspective(1400px) translateY(${((1 - p) * 8 + bob).toFixed(3)}cqmin) rotateX(${rx.toFixed(3)}deg) rotateY(${ry.toFixed(3)}deg) scale(${lerp(0.94, 1, p).toFixed(4)})`;
  };
}

const isDark = (el) => {
  const bg = token(el, '--bg', '#000');
  const m = bg.match(/^#([0-9a-f]{6})$/i);
  if (!m) return true;
  const n = parseInt(m[1], 16);
  return ((n >> 16) * 0.299 + ((n >> 8) & 255) * 0.587 + (n & 255) * 0.114) < 128;
};

export const BrowserFrame = define({
  name: 'browser-frame',
  defaults: { at: 0, url: '', title: '', src: '', theme: 'auto', typeUrl: false, scroll: [], zoom: [], tilt: null, enter: 'rise', float: false, drift: 'auto', camera: 'page' },
  async setup(el, o, { motion }) {
    const dark = o.theme === 'dark' || (o.theme === 'auto' && isDark(el));
    el.classList.add(dark ? 'st-bw-dark' : 'st-bw-light');
    const content = h('div', { class: 'st-bw-page' });
    mountContent(el, o, content);
    el.textContent = '';
    const urlText = h('span', { class: 'st-bw-urltext' }, o.url);
    // window chrome is UI detail, not copy: exempt from the tiny-text rule in `showtime check`
    const bar = h('div', { class: 'st-bw-bar', 'data-st-decor': '' },
      h('div', { class: 'st-bw-dots' }, h('i'), h('i'), h('i')),
      h('div', { class: 'st-bw-nav' }, h('span', {}, '‹'), h('span', {}, '›')),
      h('div', { class: 'st-bw-url' }, h('span', { class: 'st-bw-lock' }), urlText),
      h('div', { class: 'st-bw-actions' }, h('i'), h('i')));
    if (o.title) bar.prepend(h('div', { class: 'st-bw-tab' }, o.title));
    const view = h('div', { class: 'st-bw-view' }, content);
    el.append(bar, h('div', { class: 'st-bw-viewport' }, view));
    const scroll = scroller(o, view, content, motion, el);
    await primeScroll('browser-frame', el, content, scroll);
    const enter = entrance(el, o, motion);
    const url = String(o.url || '');
    return {
      duration: 1.2,
      update(lt) {
        enter(lt);
        if (o.typeUrl) {
          const n = Math.floor(clamp((lt - 0.35) / 0.9) * url.length);
          const s = url.slice(0, n);
          if (urlText.textContent !== s) urlText.textContent = s;
        }
        scroll(lt);
      },
    };
  },
});

export const DeviceFrame = define({
  name: 'device-frame',
  defaults: { at: 0, model: 'phone', src: '', color: 'graphite', scroll: [], zoom: [], tilt: null, enter: 'rise', float: false, notch: true, drift: 'auto', camera: 'page' },
  async setup(el, o, { motion }) {
    const model = ['phone', 'tablet', 'laptop'].includes(o.model) ? o.model : 'phone';
    el.classList.add('st-dev-' + model, 'st-dev-' + o.color);
    const content = h('div', { class: 'st-dev-page' });
    mountContent(el, o, content);
    el.textContent = '';
    const view = h('div', { class: 'st-dev-view' }, content);
    const screen = h('div', { class: 'st-dev-screen' }, view);
    if (model === 'phone' && o.notch) screen.append(h('div', { class: 'st-dev-island' }));
    const body = h('div', { class: 'st-dev-body' }, screen);
    el.append(body);
    if (model === 'laptop') el.append(h('div', { class: 'st-dev-base' }));
    const scroll = scroller(o, view, content, motion, el);
    await primeScroll('device-frame', el, content, scroll);
    const enter = entrance(el, o, motion);
    return { duration: 1.2, update(lt) { enter(lt); scroll(lt); } };
  },
});

export default BrowserFrame;

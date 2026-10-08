// What `showtime adopt` reads from a designed page: a Claude Design export (its artboard size and
// logic class), the length of a requestAnimationFrame clock or of looping CSS animations, the artboard
// fit at the output size, and the Google Fonts links to make local.
//
// Pure functions over text and numbers (no browser): adopt.mjs feeds them the page and the timings
// the bridge (runtime/adopt.js) read under the virtual clock.

const even = (n) => Math.max(2, Math.round(n / 2) * 2);
const NUM = '[0-9]+(?:\\.[0-9]+)?';

function decodeEntities(s) {
  return String(s).replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
}

/**
 * A Claude Design export: an <x-dc> template, a <script type="text/x-dc" data-dc-script> logic class
 * (class Component extends DCLogic) and the runtime that renders it (support.js, vendor/react*.js).
 * -> null | {artboard: {width, height} | null, logic, runtime}
 */
export function scanClaudeDesign(html) {
  if (!/<x-dc[\s>]/i.test(html) || !/\bdata-dc-script\b/i.test(html)) return null;
  const sm = /<script\b([^>]*\bdata-dc-script\b[^>]*)>([\s\S]*?)<\/script\s*>/i.exec(html);
  const attrs = sm ? sm[1] : '', logic = sm ? sm[2] : '';
  const runtime = /<script\b[^>]*\bsrc\s*=\s*["'][^"']*support\.js["']/i.test(html);
  if (!runtime && !/\bextends\s+DCLogic\b/.test(logic)) return null;
  let artboard = null;
  const pm = /\bdata-props\s*=\s*(?:'([^']*)'|"([^"]*)")/i.exec(attrs);
  if (pm) {
    try {
      const p = JSON.parse(decodeEntities(pm[1] !== undefined ? pm[1] : pm[2]));
      const pv = p && p.$preview;
      if (pv && Number(pv.width) > 0 && Number(pv.height) > 0) artboard = { width: Math.round(pv.width), height: Math.round(pv.height) };
    } catch { /* no size: the caller falls back */ }
  }
  return { artboard, logic, runtime };
}

function stripComments(s) {
  return String(s).replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/(^|[^:\\])\/\/[^\n]*/g, '$1');
}

/**
 * The length of an animation whose time comes from performance.now()/Date.now() in a
 * requestAnimationFrame loop: `((now - start) / 1000) % 13` loops every 13 s, `Math.min(t, 12)` stops
 * it at 12 s. The video ends where the animation ends (the clamp), not where the loop restarts.
 * -> null | {seconds, loop: bool, how}
 */
export function jsClockLength(text) {
  const code = stripComments(text);
  if (!/performance\.now\s*\(|Date\.now\s*\(|requestAnimationFrame\s*\(/.test(code)) return null;
  const consts = {};
  for (const m of code.matchAll(new RegExp(`(?:\\b(?:const|let|var|static)\\s+|this\\.|^\\s*|,\\s*)([A-Za-z_$][\\w$]*)\\s*=\\s*(${NUM})(?=\\s*[;,\\n])`, 'gm'))) {
    if (!(m[1] in consts)) consts[m[1]] = Number(m[2]);
  }
  const value = (tok) => (new RegExp(`^${NUM}$`).test(tok) ? Number(tok) : (tok.replace(/^this\./, '') in consts ? consts[tok.replace(/^this\./, '')] : null));
  const lineAt = (i) => { const ls = code.lastIndexOf('\n', i) + 1, le = code.indexOf('\n', i); return [code.slice(ls, le < 0 ? undefined : le), ls]; };
  // the clock line: the elapsed time from now() (a `% 2` blink on t elsewhere is not the loop)
  const CLOCK = /now|start|elapsed|stamp|performance|1000|1e3|clock/i;
  let loop = null, loopTok = '';
  for (const m of code.matchAll(new RegExp(`%\\s*(${NUM}|(?:this\\.)?[A-Za-z_$][\\w$]*)`, 'g'))) {
    const [line, ls] = lineAt(m.index);
    if (!CLOCK.test(line)) continue;
    // a cursor blink, `Math.floor(performance.now() / 530) % 2`: now() divided by a constant (not 1000),
    // with no start subtracted, counts ticks, not seconds of a loop
    const lhs = code.slice(ls, m.index);
    const expr = lhs.slice(Math.max(lhs.lastIndexOf(';'), lhs.lastIndexOf('{'), lhs.lastIndexOf('=')) + 1);
    const div = /\/\s*([0-9]+(?:\.[0-9]+)?|[A-Za-z_$][\w$]*)\s*\)*\s*$/.exec(expr);
    if (div && !/-/.test(expr) && !/^(1000|1e3)$/.test(div[1]) && value(div[1]) !== 1000) continue;
    let v = value(m[1]);
    if (!(v > 0)) continue;
    // `(now - start) % 13000` is milliseconds; `(... / 1000) % 13` seconds
    if (!/\/\s*1000\b|\*\s*0?\.001\b|\/\s*1e3\b/.test(code.slice(ls, m.index)) && v >= 100) v /= 1000;
    loop = v; loopTok = m[0].replace(/\s+/g, ' ');
    break;
  }
  // the clamp that holds the last frame: on the clock line or where the time is stored (setState, this.t);
  // the largest such value is where the animation ends
  const TIME = '(?:this\\.state\\.|this\\.)?(?:t|tt|ts|s|sec|secs|seconds|time|elapsed|local|[A-Za-z_$]*(?:Time|time|Elapsed|elapsed)[\\w$]*)';
  const cands = [];
  for (const re of [new RegExp(`Math\\.min\\(\\s*${TIME}\\s*,\\s*(${NUM}|(?:this\\.)?[A-Za-z_$][\\w$]*)\\s*\\)`, 'g'),
    new RegExp(`Math\\.min\\(\\s*(${NUM}|(?:this\\.)?[A-Z_$][\\w$]*)\\s*,\\s*${TIME}\\s*\\)`, 'g')]) {
    for (const m of code.matchAll(re)) {
      const v = value(m[1]);
      if (!(v > 0) || (loop && v > loop + 1e-9)) continue;
      const [line] = lineAt(m.index);
      cands.push({ v, tok: m[0].replace(/\s+/g, ' '), strong: CLOCK.test(line) || /setState|this\.t\b|state\.t\b|%/.test(line) });
    }
  }
  const pool = cands.some((c) => c.strong) ? cands.filter((c) => c.strong) : cands;
  const best = pool.sort((x, y) => y.v - x.v)[0];
  const end = best ? best.v : null, endTok = best ? best.tok : '';
  if (end && loop && end < loop) {
    return { seconds: end, loop: false, how: `\`${endTok}\` stops the animation at ${end} s inside its ${loop} s loop (\`${loopTok}\`): the video ends where the animation ends` };
  }
  if (end) return { seconds: end, loop: false, how: `\`${endTok}\` stops the animation at ${end} s` };
  if (loop) return { seconds: loop, loop: true, how: `\`${loopTok}\` repeats the animation every ${loop} s: one loop` };
  return null;
}

function gcd(a, b) { while (b) [a, b] = [b, a % b]; return a; }

/**
 * Looping CSS/Web Animations -> one seamless period. `timing` is what the bridge read from
 * document.getAnimations() under the virtual clock: [{name, delay, duration, iterations, direction}] (ms;
 * iterations null for infinite). An alternating animation takes two durations to come back.
 * -> null (nothing repeats forever) | {seconds, loop, how, periods}
 */
export function cssLoopLength(timing, { maxSeconds = 60 } = {}) {
  const inf = (timing || []).filter((a) => a && !(Number.isFinite(a.iterations)) && a.duration > 0);
  if (!inf.length) return null;
  const fin = (timing || []).filter((a) => a && Number.isFinite(a.iterations) && a.duration > 0);
  const per = (a) => Math.round(a.duration * (/alternate/.test(a.direction || '') ? 2 : 1));
  const byPeriod = new Map();
  for (const a of inf) {
    const p = per(a);
    if (!byPeriod.has(p)) byPeriod.set(p, []);
    byPeriod.get(p).push(a.name || 'animation');
  }
  const periods = [...byPeriod.keys()].sort((x, y) => y - x);
  // the shortest length after which every looping animation is back where it started
  let L = periods.reduce((acc, p) => (acc / gcd(acc, p)) * p, 1);
  const longest = periods[0];
  const finEnd = fin.reduce((m, a) => Math.max(m, (a.delay || 0) + a.duration * a.iterations), 0);
  const delayed = inf.filter((a) => (a.delay || 0) > 0).map((a) => a.name || 'animation');
  const names = (p) => { const n = byPeriod.get(p); return n.slice(0, 3).join(', ') + (n.length > 3 ? ` and ${n.length - 3} more` : ''); };
  const group = (p) => {
    const anims = inf.filter((a) => per(a) === p);
    const many = anims.length > 1;
    if (anims.every((a) => /alternate/.test(a.direction || ''))) return `${names(p)} ${many ? 'go' : 'goes'} there and back every ${p / 1000} s (alternate)`;
    return `${names(p)} ${many ? 'repeat' : 'repeats'} every ${p / 1000} s`;
  };
  let how;
  let seamless = true;
  if (L > maxSeconds * 1000 || L > longest * 6) {
    how = `the looping animations repeat every ${periods.map((p) => p / 1000).join(', ')} s and only line up again after ${L / 1000} s: ` +
      `one ${longest / 1000} s period of the longest (${names(longest)}); the others jump at the seam`;
    L = longest; seamless = false;
  } else if (periods.length === 1) {
    how = `${group(L)}: one loop`;
  } else {
    const short = periods[periods.length - 1];
    how = `${periods.map(group).join('; ')}: one loop is ${L / 1000} s, when all of them are back at the start ` +
      `(--duration ${short / 1000} plays one ${short / 1000} s cycle, and ${names(longest)} ${byPeriod.get(longest).length > 1 ? 'jump' : 'jumps'} at the seam)`;
  }
  let seconds = L / 1000;
  if (finEnd > L) { seconds = finEnd / 1000; seamless = false; how += `; finite animations run to ${finEnd / 1000} s, so the video runs that long`; }
  else if (finEnd > 0) { seamless = false; how += '; the animations that play once make the first loop differ from the next'; }
  if (delayed.length) seamless = false;
  return { seconds, loop: seamless, how, periods: periods.map((p) => p / 1000) };
}

/**
 * The output frame for an artboard: the aspect stays, the short side is 1080 unless `size` says
 * otherwise, and the artboard is scaled with CSS zoom (laid out again at the new size, so text and
 * vectors stay sharp; no bitmap upscale), centred when `size` has another aspect.
 * -> {width, height, zoom, x, y}   x, y: the artboard's offset in its own pixels
 */
export function fitArtboard(art, size = null) {
  let W, H;
  if (size) ({ width: W, height: H } = size);
  else if (art.width >= art.height) { H = 1080; W = even((1080 * art.width) / art.height); }
  else { W = 1080; H = even((1080 * art.height) / art.width); }
  W = even(W); H = even(H);
  const zoom = Math.min(W / art.width, H / art.height);
  const r = (x) => Math.round(x * 1000) / 1000;
  return { width: W, height: H, zoom: r(zoom), x: r((W / zoom - art.width) / 2), y: r((H / zoom - art.height) / 2) };
}

/**
 * CSS for fitArtboard's result, or '' when the artboard already is the frame. The zoom scales the
 * stage's own `body{width:W;height:H;overflow:hidden}` too, so the body is pinned to the frame in
 * zoomed pixels (W/zoom x H/zoom): below zoom 1 it would otherwise clip the artboard at zoom*W x zoom*H.
 */
export function fitCss(fit) {
  if (!fit || (Math.abs(fit.zoom - 1) < 1e-6 && !fit.x && !fit.y)) return '';
  const r = (x) => Math.round(x * 1000) / 1000;
  let css = `html{zoom:${fit.zoom}}`;
  const pos = Math.abs(fit.x) >= 0.01 || Math.abs(fit.y) >= 0.01 ? `left:${fit.x}px!important;top:${fit.y}px!important;` : '';
  if (fit.width > 0 && fit.height > 0) css += `body{${pos}width:${r(fit.width / fit.zoom)}px!important;height:${r(fit.height / fit.zoom)}px!important}`;
  else if (pos) css += `body{${pos.slice(0, -1)}}`;
  return css;
}

/**
 * Why `showtime assets font --css` failed, from its stderr (`error: ...` then `fix: ...`):
 * -> {code: 'fonts_license' | 'fonts_offline' | 'fonts_failed', why}
 */
export function fontFetchFailure(stderr, exitCode = 1) {
  const lines = String(stderr || '').split('\n').map((l) => l.trim()).filter(Boolean);
  const why = (lines.filter((l) => /^error:/i.test(l)).pop() || lines.pop() || `exit ${exitCode}`).replace(/^error:\s*/i, '');
  const code = / is licensed /.test(why) ? 'fonts_license'
    : /offline mode|network error|cannot fetch|timed out/i.test(why) ? 'fonts_offline' : 'fonts_failed';
  return { code, why };
}

const GF_HOST =/^https?:\/\/fonts\.googleapis\.com\/css2?\?/i;

/** Google Fonts stylesheets a page loads (<link href> or @import) -> [{url, raw}] (url with &amp; decoded). */
export function googleFontLinks(html) {
  const out = [];
  const add = (raw) => { const url = decodeEntities(raw); if (GF_HOST.test(url) && !out.some((x) => x.url === url)) out.push({ url, raw }); };
  for (const m of html.matchAll(/<link\b[^>]*>/gi)) {
    const h = /\bhref\s*=\s*(["'])([^"']+)\1/i.exec(m[0]);
    if (h && /stylesheet/i.test(m[0])) add(h[2]);
  }
  for (const m of html.matchAll(/@import\s+(?:url\(\s*)?["']?(https?:\/\/fonts\.googleapis\.com\/[^"')\s]+)["']?\s*\)?\s*;?/gi)) add(m[1]);
  return out;
}

/**
 * The page with its Google Fonts links taken out (and the preconnect hints to the font hosts): the
 * local stylesheets go in the head instead. `done` = the URLs that were made local.
 */
export function dropFontLinks(html, done) {
  const urls = new Set(done);
  let out = html.replace(/<link\b[^>]*>/gi, (tag) => {
    const h = /\bhref\s*=\s*(["'])([^"']+)\1/i.exec(tag);
    if (!h) return tag;
    const url = decodeEntities(h[2]);
    if (/stylesheet/i.test(tag) && urls.has(url)) return '';
    if (/preconnect|dns-prefetch/i.test(tag) && /^https?:\/\/fonts\.(googleapis|gstatic)\.com\/?$/i.test(url) && urls.size) return '';
    return tag;
  });
  out = out.replace(/@import\s+(?:url\(\s*)?["']?(https?:\/\/fonts\.googleapis\.com\/[^"')\s]+)["']?\s*\)?\s*;?/gi,
    (m, u) => (urls.has(decodeEntities(u)) ? '' : m));
  return out;
}

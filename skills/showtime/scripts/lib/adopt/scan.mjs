// Static detection for `showtime adopt`: which file in a folder is the video, which contract it
// follows (a page with a time function, a Python frame generator, a page on a clock), and what
// its own render driver says about size, fps, duration, audio and setup calls.
//
// Pure functions over file text (no browser, no Python): the browser probe and the Python harness
// confirm or correct what this finds.
import fs from 'node:fs';
import path from 'node:path';

export const SKIP_DIRS = new Set(['node_modules', '.git', '.hg', '.svn', '.venv', 'venv', 'env', '.env', '__pycache__',
  'showtime-out', '.frames', '.preview', '.cache', '.pytest_cache', '.mypy_cache', 'dist-newstyle', '.next', '.idea', '.vscode']);
export const VIDEO_EXT = /\.(mp4|m4v|mov|mkv|webm|avi)$/i;
export const AUDIO_EXT = /\.(wav|mp3|m4a|aac|ogg|opus|flac)$/i;
const IMG_EXT = /\.(png|jpe?g|webp|bmp|tiff?)$/i;

// Time functions a page exposes, in the order we prefer them when several exist.
export const TIME_FNS = ['seek', '__seek', 'seekTo', 'renderAt', 'render', 'renderFrame', 'draw', 'drawFrame', 'drawAt',
  'setTime', 'setFrame', 'gotoTime', 'goto', '__render', '__draw', '__setTime', 'frame', 'update', 'paint', 'tick'];
const FN_ALT = TIME_FNS.map((n) => n.replace(/[\\$]/g, '\\$&')).join('|');

/** Walk a folder (skipping dependency and output folders) -> [relative posix paths]. */
export function listFiles(root, { max = 4000 } = {}) {
  const out = [];
  const walk = (dir, rel, depth) => {
    if (out.length >= max || depth > 8) return;
    let ents;
    try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    // a folder of hundreds of numbered images is a frame dump, not source
    const imgs = ents.filter((e) => e.isFile() && IMG_EXT.test(e.name)).length;
    if (rel && imgs > 200) return;
    for (const e of ents) {
      if (out.length >= max) return;
      const r = rel ? `${rel}/${e.name}` : e.name;
      if (e.isDirectory()) { if (!SKIP_DIRS.has(e.name)) walk(path.join(dir, e.name), r, depth + 1); }
      else if (e.isFile()) out.push(r);
    }
  };
  walk(root, '', 0);
  return out;
}

function read(file, max = 2e6) {
  try {
    const st = fs.statSync(file);
    if (st.size > max) return fs.readFileSync(file, 'utf8').slice(0, max);
    return fs.readFileSync(file, 'utf8');
  } catch { return ''; }
}

/** The script text of an HTML page (inline scripts only; external classic scripts are appended by the caller). */
export function inlineScripts(html) {
  const out = [];
  const re = /<script\b([^>]*)>([\s\S]*?)<\/script[^>]*>/gi;
  let m;
  while ((m = re.exec(html))) out.push({ attrs: m[1], text: m[2] });
  return out;
}

/** Local script/style/media references of a page -> [{ref, kind}] (relative URLs only). */
export function pageRefs(html) {
  const out = [];
  const re = /\b(src|href|poster|data)\s*=\s*(["'])([^"']+)\2/gi;
  let m;
  while ((m = re.exec(html))) {
    const u = m[3].trim();
    if (!u || /^(https?:|data:|blob:|#|mailto:|javascript:|\/\/|about:)/i.test(u)) continue;
    out.push({ ref: u.split(/[?#]/)[0], kind: m[1].toLowerCase() });
  }
  const css = /url\(\s*(["']?)([^"')]+)\1\s*\)/gi;
  while ((m = css.exec(html))) {
    const u = m[2].trim();
    if (!u || /^(https?:|data:|blob:|#|\/\/)/i.test(u)) continue;
    out.push({ ref: u.split(/[?#]/)[0], kind: 'css' });
  }
  const fetchRe = /\bfetch\(\s*(["'`])([^"'`$]+)\1/g;
  while ((m = fetchRe.exec(html))) if (!/^(https?:|\/\/)/i.test(m[2])) out.push({ ref: m[2].split(/[?#]/)[0], kind: 'fetch' });
  return out;
}

/** Remote URLs a page loads (fonts, CDNs): these are blocked in renders. */
export function remoteRefs(html) {
  const out = new Set();
  const re = /\b(?:src|href)\s*=\s*(["'])(https?:\/\/[^"']+)\1|@import\s+url\(\s*["']?(https?:\/\/[^"')]+)/gi;
  let m;
  while ((m = re.exec(html))) out.add(m[2] || m[3]);
  return [...out];
}

/**
 * Score an HTML page as a video page. -> {score, fns: [{name, param, line}], durations: {name: value},
 *   fps, size, canvas, clock: {css, raf, waapi, timers}, ready: [names], setters: [names], hints: []}
 */
export function scanPage(html) {
  const scripts = inlineScripts(html).map((s) => s.text).join('\n;\n');
  const all = scripts;
  const fns = [];
  const seen = new Set();
  const addFn = (name, param, idx) => {
    if (seen.has(name)) return;
    seen.add(name);
    fns.push({ name, param: param || '', line: lineOf(all, idx) });
  };
  let m;
  // window.seek = function (t) / window.render = (t) => / window.draw = t =>
  const assignRe = new RegExp(`(?:window|globalThis|self)\\.(${FN_ALT})\\s*=\\s*(?:async\\s*)?(?:function\\s*\\w*\\s*\\(\\s*([\\w$]*)|\\(\\s*([\\w$]*)|([\\w$]+)\\s*=>)`, 'g');
  while ((m = assignRe.exec(all))) addFn(m[1], m[2] || m[3] || m[4], m.index);
  // window.render = render;  (assigned from a named function)
  const aliasRe = new RegExp(`(?:window|globalThis|self)\\.(${FN_ALT})\\s*=\\s*([A-Za-z_$][\\w$]*)\\s*[;\\n]`, 'g');
  while ((m = aliasRe.exec(all))) {
    const decl = new RegExp(`function\\s+${m[2].replace(/[\\$]/g, '\\$&')}\\s*\\(\\s*([\\w$]*)`).exec(all);
    addFn(m[1], decl ? decl[1] : '', m.index);
  }
  // top-level function render(t) { ... } in a classic script (a global too)
  const declRe = new RegExp(`(?:^|\\n)\\s*(?:async\\s+)?function\\s+(${FN_ALT})\\s*\\(\\s*([\\w$]*)`, 'g');
  while ((m = declRe.exec(all))) addFn(m[1], m[2], m.index);
  // const render = (t) => ...  at top level
  const constRe = new RegExp(`(?:^|\\n)(?:const|let|var)\\s+(${FN_ALT})\\s*=\\s*(?:async\\s*)?(?:function\\s*\\w*\\s*\\(\\s*([\\w$]*)|\\(\\s*([\\w$]*)|([\\w$]+)\\s*=>)`, 'g');
  while ((m = constRe.exec(all))) addFn(m[1], m[2] || m[3] || m[4], m.index);
  // module scripts: only window.* is global
  const isModuleOnly = inlineScripts(html).every((s) => /type\s*=\s*["']module/i.test(s.attrs)) && inlineScripts(html).length > 0;
  const durations = {};
  const durRe = /(?:window\.|const\s+|let\s+|var\s+|^\s*)(DURATION|TOTAL_DURATION|TOTAL|totalDuration|VIDEO_DURATION|DUR|LENGTH|__duration)\s*=\s*([0-9]+(?:\.[0-9]+)?)\b/gm;
  while ((m = durRe.exec(all))) if (!(m[1] in durations)) durations[m[1]] = Number(m[2]);
  const fpsM = /(?:const|let|var|window\.)\s*(FPS|fps|FRAME_RATE)\s*=\s*([0-9]+(?:\.[0-9]+)?)/.exec(all);
  const wM = /(?:const|let|var)\s*(?:W|WIDTH)\s*=\s*([0-9]{3,4})\b/.exec(all);
  const hM = /(?:const|let|var)\s*(?:H|HEIGHT)\s*=\s*([0-9]{3,4})\b/.exec(all);
  const canvasM = /<canvas\b[^>]*\bwidth\s*=\s*["']?(\d{3,4})["']?[^>]*\bheight\s*=\s*["']?(\d{3,4})/i.exec(html);
  const bodyM = /(?:html|body)[^{]*\{[^}]*\bwidth\s*:\s*(\d{3,4})px[^}]*\bheight\s*:\s*(\d{3,4})px/i.exec(html);
  let size = null;
  if (canvasM) size = { width: +canvasM[1], height: +canvasM[2], from: 'canvas' };
  else if (bodyM) size = { width: +bodyM[1], height: +bodyM[2], from: 'page css' };
  else if (wM && hM) size = { width: +wM[1], height: +hM[1], from: 'W/H constants' };
  const clock = {
    css: /@keyframes\b/.test(html),
    raf: /requestAnimationFrame\s*\(/.test(all),
    waapi: /\.animate\s*\(\s*\[|\.animate\s*\(\s*\{/.test(all),
    timers: /\bset(?:Timeout|Interval)\s*\(/.test(all),
    realtime: /performance\.now\s*\(|Date\.now\s*\(/.test(all),
    gsap: /\bgsap\b/.test(html),
  };
  const ready = [];
  const readyRe = /window\.(ready|__ready|isReady|READY|fontsReady|loaded)\s*=/g;
  while ((m = readyRe.exec(all))) if (!ready.includes(m[1])) ready.push(m[1]);
  const setters = [];
  const setRe = /window\.((?:set|load|init|provide)[A-Z]\w*)\s*=/g;
  while ((m = setRe.exec(all))) if (!setters.includes(m[1]) && !TIME_FNS.includes(m[1])) setters.push(m[1]);
  let score = 0;
  if (fns.length) score += 50;
  if (Object.keys(durations).length) score += 15;
  if (/<canvas\b/i.test(html)) score += 5;
  if (clock.css || clock.waapi || clock.raf) score += 8;
  if (size) score += 5;
  return {
    score, fns, durations, fps: fpsM ? Number(fpsM[2]) : null, size, clock, ready, setters,
    moduleOnly: isModuleOnly, canvas: /<canvas\b/i.test(html), hasStage: /\/_st\/stage\.js/.test(html),
    remote: remoteRefs(html), base: /<base\b/i.test(html),
  };
}

function lineOf(text, idx) { return text.slice(0, idx).split('\n').length; }

/**
 * A render driver the model wrote next to its page (puppeteer, playwright, raw CDP, selenium):
 * what it evaluates per frame and the numbers it uses. -> null when the file is not a driver.
 */
export function scanDriver(text, file = '') {
  const isBrowser = /puppeteer|playwright|chrome-remote-interface|Page\.captureScreenshot|captureScreenshot|Runtime\.evaluate|webdriver|pyppeteer|selenium|headless/i.test(text);
  if (!isBrowser) return null;
  const out = { file, calls: [], unit: null, fps: null, duration: null, size: null, pages: [], setup: [], audio: [], ready: null };
  let m;
  // expressions evaluated per frame: `render(${t})`, window.seek(t), `__seek(${f / FPS})`
  const callRe = new RegExp(`(?:window\\.)?(${FN_ALT})\\s*\\(\\s*(\\$\\{[^}]*\\}|[\\w$.*/+\\s()-]*)\\)`, 'g');
  while ((m = callRe.exec(text))) {
    const arg = m[2] || '';
    if (/^(?:set|load)/.test(m[1]) && !/time|frame|t\b/i.test(arg)) continue;
    let unit = 's';
    if (/\*\s*1000|1000\s*\*|\bms\b/.test(arg)) unit = 'ms';
    else if (/^\$?\{?\s*(?:i|f|n|k|frame|fi|idx|index)\s*\}?$/.test(arg.replace(/[${}\s]/g, '')) && !/\//.test(arg)) unit = 'frame';
    out.calls.push({ name: m[1], arg: arg.slice(0, 60), unit, line: lineOf(text, m.index) });
  }
  const fpsM = /\b(?:FPS|fps|FRAME_RATE|framerate)\s*[=:]\s*(\d+(?:\.\d+)?)/.exec(text) || /['"]-(?:r|framerate)['"]\s*,\s*['"]?(\d+)/.exec(text);
  if (fpsM) out.fps = Number(fpsM[1]);
  const durM = /\b(?:DURATION|duration|TOTAL|DUR)\s*[=:]\s*(\d+(?:\.\d+)?)/.exec(text);
  if (durM) out.duration = Number(durM[1]);
  const vpM = /width\s*:\s*(\d{3,4})\s*,\s*height\s*:\s*(\d{3,4})/.exec(text) || /window-size[=,]\s*(\d{3,4})\s*,\s*(\d{3,4})/.exec(text) ||
    /\b(?:W|WIDTH)\s*=\s*(\d{3,4})\s*,\s*(?:H|HEIGHT)\s*=\s*(\d{3,4})/.exec(text);
  if (vpM) out.size = { width: +vpM[1], height: +vpM[2], from: path.basename(file) };
  const pageRe = /([\w./-]+\.html?)\b/g;
  while ((m = pageRe.exec(text))) if (!out.pages.includes(path.basename(m[1]))) out.pages.push(path.basename(m[1]));
  // setup calls the driver makes once before the frames: window.setData(rows), setConfig(...)
  const setRe = /(?:window\.)?((?:set|load|init|provide)[A-Z]\w*)\s*\(/g;
  while ((m = setRe.exec(text))) {
    if (TIME_FNS.includes(m[1]) || /^(setTimeout|setInterval|setViewport|setContent|setDefault|setExtraHTTPHeaders|setUserAgent|setRequestInterception|setCacheEnabled|setDeviceMetricsOverride|setJavaScriptEnabled)$/.test(m[1])) continue;
    if (!out.setup.find((s) => s.name === m[1])) out.setup.push({ name: m[1], line: lineOf(text, m.index) });
  }
  const readyM = /evaluate\(\s*['"`](?:window\.)?(ready|__ready|isReady|fontsReady)['"`]/.exec(text) || /window\.(ready|__ready|isReady)\b/.exec(text);
  if (readyM) out.ready = readyM[1];
  out.audio = audioRefs(text);
  out.data = dataRefs(text);
  return out;
}

/** Data files a driver reads (CSV, JSON ...): named in the needs_setup advice. */
export function dataRefs(text) {
  const out = [];
  const re = /["'`]([^"'`\s$]+\.(?:csv|tsv|json|geojson|txt|xlsx?))["'`]/gi;
  let m;
  while ((m = re.exec(text))) if (!out.includes(m[1]) && !/package(-lock)?\.json$/.test(m[1])) out.push(m[1]);
  return out;
}

/** Audio files a script muxes or plays: ffmpeg `-i x.wav`, open('x.wav'), "vo/final_1.wav". */
export function audioRefs(text) {
  const out = [];
  const re = /["'`]([^"'`\s$]+\.(?:wav|mp3|m4a|aac|ogg|opus|flac))["'`]|(?:^|[\s=])((?:\.{0,2}\/)?[\w][\w./-]*\.(?:wav|mp3|m4a|aac|ogg|opus|flac))(?=[\s;)]|$)/gim;
  let m;
  while ((m = re.exec(text))) { const f = m[1] || m[2]; if (!out.includes(f)) out.push(f); }
  return out;
}

/** Score a Python file as a frame generator (the harness confirms). */
export function scanPython(text) {
  let score = 0;
  const imgLib = /\bfrom\s+PIL\b|\bimport\s+PIL\b|\bimport\s+numpy\b|\bimport\s+cairo\b|\bmatplotlib\b|\bimport\s+skia\b|\bpygame\b|\bmoviepy\b|\bimport\s+cv2\b/.test(text);
  if (imgLib) score += 20;
  if (/ffmpeg/.test(text)) score += 15;
  if (/rawvideo|image2pipe|stdin\.write|\.save\(\s*f?["'][^"']*%0?\d*d|frame_?\d|:05d|:06d/.test(text)) score += 15;
  if (/\b(?:FPS|fps)\s*=/.test(text)) score += 5;
  if (/\bdef\s+(render|render_frame|draw|draw_frame|make_frame|frame)\s*\(/.test(text)) score += 20;
  if (/manim|Scene\)/.test(text) && /from\s+manim/.test(text)) score -= 40;    // Manim: `showtime manim` owns it
  return { score, imgLib, manim: /from\s+manim(gl)?\s+import|import\s+manim/.test(text) };
}

/**
 * Pick the video source in a folder. -> {kind: 'page'|'python'|null, file, candidates: [...], drivers: [...]}
 */
export function pickSource(root, files) {
  const pages = [], pys = [], drivers = [];
  for (const rel of files) {
    const f = path.join(root, ...rel.split('/'));
    if (/\.html?$/i.test(rel)) {
      const html = read(f);
      const s = scanPage(html);
      if (/(^|\/)(index\.orig|preview|player)\.html?$/i.test(rel)) s.score -= 5;
      pages.push({ rel, ...s });
    } else if (/\.(mjs|cjs|js|ts|py)$/i.test(rel)) {
      const text = read(f, 5e5);
      const d = scanDriver(text, rel);
      if (d) { drivers.push(d); continue; }
      if (/\.py$/i.test(rel)) { const s = scanPython(text); pys.push({ rel, ...s }); }
    }
  }
  // a page named by a driver is the video page
  for (const p of pages) if (drivers.some((d) => d.pages.includes(path.basename(p.rel)))) p.score += 30;
  pages.sort((a, b) => b.score - a.score);
  pys.sort((a, b) => b.score - a.score);
  const bestPage = pages[0] && pages[0].score >= 20 ? pages[0] : null;
  const bestPy = pys[0] && pys[0].score >= 30 ? pys[0] : null;   // e.g. ffmpeg + raw frames on stdin
  let kind = null, file = null;
  if (bestPage && (!bestPy || bestPage.score >= bestPy.score)) { kind = 'page'; file = bestPage.rel; }
  else if (bestPy) { kind = 'python'; file = bestPy.rel; }
  else if (pages[0]) { kind = 'page'; file = pages[0].rel; }
  const candidates = [...pages.map((p) => ({ kind: 'page', rel: p.rel, score: p.score })), ...pys.map((p) => ({ kind: 'python', rel: p.rel, score: p.score }))]
    .sort((a, b) => b.score - a.score);
  return { kind, file, candidates, drivers, pages, pys };
}

/** Drivers that belong to a page (they name it, or sit next to it with a matching call). */
export function driversFor(pageRel, drivers) {
  const base = path.basename(pageRel);
  const dir = path.posix.dirname(pageRel);
  return drivers.filter((d) => d.pages.includes(base) || (path.posix.dirname(d.file) === dir && d.calls.length));
}

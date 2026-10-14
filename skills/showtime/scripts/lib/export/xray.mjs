// `showtime export html <xray project> --interactive`: the X-ray's live page, one offline file.
//
// The project's own page (index.html: xray.js + mechanism.js, or the diagram layout's page) is packed as it is and
// driven by the scrub time instead of the renderer: the same stage runtime in render mode (runtime/xray-live/pre.js
// sets it up before stage.js), the same ST.onSeek drawing, at the frame the viewer picks. Around it,
// runtime/xray-live/live.js draws the controls: play with the clip's own sound, a timeline of every event (red kept,
// grey skipped), jump to an event's exact frame, 0.25x around one, light/dark, see-through/split, part labels.
//
// Media: each clip is packed once, as base64, and turned into one blob: URL in the page (a second <video> of the
// same file becomes a canvas mirror of the first, so the radiograph never drifts from the clip). The page's data
// files (xray.json, showtime.json, notes.json) travel inline and answer its fetch() calls. A Content-Security-Policy
// blocks every network request. Over --max-mb because of the clip, the clip is re-encoded for this export only
// (fit.mjs), as the film export does.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { skillDir, nodeModulesDir } from '../deps.mjs';
import { UserError, c, fmtBytes } from '../cli.mjs';
import { showCard, openHint } from '../delight.mjs';
import { figureFile, FIGURE_CSP } from './figure.mjs';
import { addCodePoints, pruneFontFaces } from './collect.mjs';
import { minifyJs, minifyCss } from './minify.mjs';
import { notices, stageForExport, showtimeVersion, safeJson } from './build.mjs';
import { fitFootage } from './fit.mjs';

const MB = 1000 * 1000;
const FONT_MIME = { '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf', '.otf': 'font/otf' };
const IMG_MIME = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.svg': 'image/svg+xml', '.webp': 'image/webp', '.gif': 'image/gif' };
const MEDIA_MIME = { '.webm': 'video/webm', '.mp4': 'video/mp4', '.m4v': 'video/mp4', '.mov': 'video/quicktime', '.ogv': 'video/ogg' };
// what the page reads from showtime.json: the stage's keys and the X-ray's own block (no audio paths or local details)
const PUBLIC_KEYS = ['width', 'height', 'fps', 'duration', 'background', 'title', 'poster', 'seed', 'template', 'xray'];

/** An X-ray project: showtime.json "xray" and the measured events (xray.json) next to the page. */
export function isXrayProject(dir, cfg) {
  return !!(cfg && cfg.xray && typeof cfg.xray === 'object' && !Array.isArray(cfg.xray)) && fs.existsSync(path.join(dir, 'xray.json'));
}

function liveFile(name) { return fs.readFileSync(path.join(skillDir(), 'runtime', 'xray-live', name), 'utf8'); }
// inside an inlined script the HTML parser ends it at `</script` and enters its escaped state at `<!--`: both are
// written with an escape that means the same characters in a JS string, template or regex (as figure.mjs does)
const jsSafe = (t) => t.replace(/<\/(script)/gi, (m, w) => '<\\/' + w).replace(/<!--/g, '<\\x21--');
const attrEsc = (v) => String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
const getAttr = (attrs, name) => { const m = new RegExp(`\\b${name}\\s*=\\s*"([^"]*)"`, 'i').exec(attrs) || new RegExp(`\\b${name}\\s*=\\s*'([^']*)'`, 'i').exec(attrs); return m ? m[1] : null; };

/**
 * The line that made it: { prompt, commands }. The prompt is explicit only (--prompt, else showtime.json
 * xray.made.prompt, else none); the commands are showtime.json xray.made.commands when the project lists the steps
 * that made it (own: true), else written with placeholders, never the project's own paths: `xray import` for events
 * from a data stream (xray.json detector.engine "data"), `xray analyze` of a clip or a recording otherwise.
 */
export function madeWith(xr, live, prompt, fromProject, doc = {}) {
  const made = xr.made && typeof xr.made === 'object' ? xr.made : {};
  const word = (v, d) => (typeof v === 'string' && /^[\w-]{1,40}$/.test(v) ? v : d);
  // xray.made.mechanism, else xray.mechanism, else the name the project's own mechanism.js declares; the
  // typewriter only as a last guess (live.made.guessed, and the export report says so)
  const named = word(made.mechanism, word(xr.mechanism, word(fromProject, '')));
  const mech = named || 'typewriter';
  const layout = word(made.layout, live.layout === 'through' ? 'through' : live.layout);
  const theme = word(made.theme, live.theme);
  const text = typeof prompt === 'string' && prompt.trim() ? prompt.trim() : (typeof made.prompt === 'string' ? made.prompt.trim() : '');
  const job = `xray-${mech}`;
  const own = Array.isArray(made.commands) ? made.commands.filter((v) => typeof v === 'string' && v.trim()).map((v) => v.trim()) : [];
  if (own.length) return { prompt: text, guessed: false, own: true, mechanism: mech, commands: own };
  const det = (doc && doc.detector) || {}, src = (doc && doc.source) || {};
  const tm = det.time_map && Number.isFinite(det.time_map.slow) && Number.isFinite(det.time_map.t0) ? det.time_map : null;
  const sound = src.audio_only ? 'sound.wav' : 'clip.mp4';
  const first = det.engine === 'data'
    ? `showtime xray import events.csv --job ${job}${tm ? ` --time-map ${tm.slow},${tm.t0}` : ''}${src.file ? ` --source ${sound}` : ''}`
    : `showtime xray analyze ${sound} --job ${job}${live.tracked ? ' --track' : ''}`;
  return { prompt: text, guessed: !named, own: false, mechanism: mech, commands: [
    first,
    `showtime new xray ${job}/project --mechanism ${mech} --layout ${layout} --theme ${theme}`,
    `showtime render ${job}/project --job ${job}`,
    `showtime xray verify ${job}`,
  ] };
}

/** The --mechanism names the page's commands use that library/xray does not have (a drawing written for this film). */
export function unknownMechanisms(made) {
  const names = made.own ? [...made.commands.join('\n').matchAll(/--mechanism[\s=]+([^\s'"]+)/g)].map((m) => m[1]) : (made.guessed ? [] : [made.mechanism]);
  const lib = path.join(skillDir(), 'library', 'xray');
  return [...new Set(names)].filter((n) => !/^[\w-]{1,40}$/.test(n) || !fs.existsSync(path.join(lib, n, 'mechanism.js')));
}

/** True when a command carries a local path: /abs, ~/x, C:\x at the start of a word or after = ' ". One pass per word. */
function hasLocalPath(v) {
  for (const w of v.split(/\s+/)) {
    let lastWord = -1;
    for (let i = w.length - 1; i >= 0; i--) if (/\w/.test(w[i])) { lastWord = i; break; }
    for (let i = 0; i < w.length; i++) {
      if (i > 0 && !'=\'"'.includes(w[i - 1])) continue;
      const c = w[i], n = w[i + 1];
      if (c === '/' && n !== '/' && lastWord > i) return true;
      if (c === '~' && (n === '/' || n === '\\')) return true;
      if (/[A-Za-z]/.test(c) && n === ':' && (w[i + 2] === '\\' || w[i + 2] === '/')) return true;
    }
  }
  return false;
}

/** The lines of xray.made.commands that carry a local path (the page is shared; commands use placeholders). */
export function localPathLines(made) {
  return made.own ? made.commands.filter(hasLocalPath) : [];
}

/**
 * Pack the live page. -> { render(): html, media: Map(src -> {mime, bytes}), files, missing, remote, page, live }
 * render() writes the page with the media as they are now (fit.mjs may have re-encoded them in between).
 * @param o.projectDir
 * @param o.config     showtime.json (the project's)
 * @param o.title      the page title
 * @param o.prompt     the request that made the film (shown on the page; default: showtime.json xray.made.prompt)
 * @param o.page       the film page (default index.html)
 * @param o.allFonts   keep every font face
 * @param o.minify     shrink scripts and styles (default true)
 * @param o.noCsp      leave out the Content-Security-Policy
 */
export function packXrayLive(o) {
  const projectDir = path.resolve(o.projectDir);
  const page = o.page || 'index.html';
  const pagePath = path.join(projectDir, page);
  if (!fs.existsSync(pagePath)) throw new UserError(`the X-ray project has no ${page}`, 'export the project folder `showtime new xray` made');
  let html = fs.readFileSync(pagePath, 'utf8');
  const cfg = o.config || {};
  const mini = o.minify !== false;
  const files = [], missing = [], remote = [];
  const base = '/' + page;
  const read = (url, from, binary) => {
    const f = figureFile(url, { projectDir, base: from || base });
    if (f.inline) return null;
    if (f.remote) { remote.push(f.remote); return null; }
    if (f.escapes || !fs.existsSync(f.file) || !fs.statSync(f.file).isFile()) { missing.push(f.escapes || f.url); return null; }
    const buf = fs.readFileSync(f.file);
    return { buf, text: binary ? null : buf.toString('utf8'), url: f.url, ext: path.extname(f.file).toLowerCase() };
  };

  // ---- the page's data files: they answer its fetch() calls (pre.js)
  const data = {};
  for (const n of ['xray.json', 'notes.json']) {
    const p = path.join(projectDir, n);
    if (!fs.existsSync(p)) continue;
    const t = fs.readFileSync(p, 'utf8');
    try { data[n] = JSON.stringify(JSON.parse(t)); } catch { throw new UserError(`${n} is not valid JSON`, `run \`showtime xray ${n === 'xray.json' ? 'analyze' : 'notes'}\` again and copy it next to ${page}`); }
    files.push({ url: '/' + n, bytes: Buffer.byteLength(data[n]), kind: 'data' });
  }
  const pub = {};
  for (const k of PUBLIC_KEYS) if (cfg[k] !== undefined) pub[k] = cfg[k];
  data['showtime.json'] = JSON.stringify(pub);
  const doc = JSON.parse(data['xray.json']);
  const xr = cfg.xray || {};
  const isDiagram = xr.layout === 'diagram' || /\bXRAY_DIAGRAM\b/.test(html);

  // ---- videos: one packed copy per file; a second <video> of the same file becomes a canvas mirror of the first
  const media = new Map();                       // src url -> {key, mime, bytes}
  const masters = new Map();                     // src url -> id of its first <video>
  html = html.replace(/<video\b([^>]*)>([\s\S]*?)<\/video>/gi, (m, attrs) => {
    const src = getAttr(attrs, 'src');
    if (!src) return m;
    const r = read(src, base, true);
    if (!r) return m;
    if (!MEDIA_MIME[r.ext]) { missing.push(r.url + ' (not a video this page can pack)'); return m; }
    if (!media.has(r.url)) { media.set(r.url, { key: 'm' + media.size, mime: MEDIA_MIME[r.ext], bytes: r.buf }); files.push({ url: r.url, bytes: r.buf.length, kind: 'video' }); }
    const key = media.get(r.url).key, id = getAttr(attrs, 'id'), cls = getAttr(attrs, 'class');
    if (masters.has(r.url)) {
      return `<canvas${id ? ` id="${attrEsc(id)}"` : ''}${cls ? ` class="${attrEsc(cls)}"` : ''} data-xl-mirror="${attrEsc(masters.get(r.url))}"></canvas>`;
    }
    masters.set(r.url, id || key);
    const rest = attrs.replace(/\s\bsrc\s*=\s*("[^"]*"|'[^']*')/i, '').replace(/\s\bdata-st\s*=\s*("[^"]*"|'[^']*')/i, '');
    return `<video${rest}${id ? '' : ` id="${key}"`} data-st="off" data-xl-src="${key}" preload="auto"></video>`;
  });
  if (!media.size) throw new UserError(`${page} shows no clip (<video src="media/...">) to pack`, 'the X-ray page plays the clip it was made from: put it in media/clip.webm');

  // ---- scripts (stage.js: the render-only cut, after pre.js) and styles, in page order
  const scripts = [], styles = [];
  let stageSeen = false;
  html = html.replace(/<script\b([^>]*)\bsrc="([^"]+)"([^>]*)>\s*<\/script>/gi, (m, a1, src) => {
    const r = read(src, base);
    if (!r) return m;
    files.push({ url: r.url, bytes: r.buf.length, kind: 'script' });
    let text = r.text;
    if (r.url === '/_st/stage.js') { stageSeen = true; text = stageForExport(text); }
    const k = `\u0000S${scripts.length}\u0000`;
    scripts.push({ text, stage: r.url === '/_st/stage.js' });
    return k;
  });
  if (!stageSeen) throw new UserError(`${page} does not load the stage runtime (/_st/stage.js)`, 'the live page drives the same ST.onSeek drawing as the film: keep <script src="/_st/stage.js"> in the page');
  html = html.replace(/<link\b[^>]*\brel="stylesheet"[^>]*>/gi, (m) => {
    const href = (/\bhref="([^"]+)"/i.exec(m) || [])[1];
    if (!href) return m;
    const r = read(href, base);
    if (!r) return m;
    files.push({ url: r.url, bytes: r.buf.length, kind: 'style' });
    const k = `\u0000C${styles.length}\u0000`;
    styles.push({ text: r.text, url: r.url });
    return k;
  });

  // ---- the live page's own parts
  const pre = liveFile('pre.js'), liveJs = liveFile('live.js'), liveCss = liveFile('live.css');
  const W = Math.round(Number(cfg.width) || 1920), H = Math.round(Number(cfg.height) || 1080), fps = Number(cfg.fps) || 30;
  const src = doc.source || {};
  const live = {
    W, H, fps, duration: Number(cfg.duration) || 0, title: o.title || cfg.title || 'X-ray',
    layout: isDiagram ? 'diagram' : (xr.layout === 'split' ? 'split' : 'through'),
    tracked: !isDiagram && !!(doc.track && Array.isArray(doc.track.H) && doc.track.H.length),
    theme: xr.theme === 'light' ? 'light' : 'dark', clipDur: Number(src.duration) || 0,
    receipt: typeof xr.receipt === 'string' ? xr.receipt : '', credit: typeof xr.credit === 'string' ? xr.credit : '',
    drawn: typeof xr.drawn === 'string' ? xr.drawn : '', poster: Number(cfg.poster) || 0,
    // what was measured, in a sentence: "xray".measured, else the page says it from the detector (sound or data)
    measured: typeof xr.measured === 'string' ? xr.measured.trim() : '',
    detector: { engine: String((doc.detector && doc.detector.engine) || ''), note: typeof (doc.detector && doc.detector.note) === 'string' ? doc.detector.note : '' },
    generator: `showtime ${showtimeVersion()}`,
  };
  let declared = '';
  try { declared = (/XRAY\.mechanism\(\s*\{[^]*?\bname\s*:\s*['"]([\w-]{1,40})['"]/.exec(fs.readFileSync(path.join(projectDir, 'mechanism.js'), 'utf8')) || [])[1] || ''; } catch { /* no mechanism.js */ }
  live.made = madeWith(xr, live, o.prompt, declared, doc);

  // ---- fonts: faces for scripts no text uses are dropped (the page, its scripts, the data's words, the controls)
  const used = new Set();
  addCodePoints(used, html.replace(/<[^>]+>/g, ' '));
  scripts.forEach((s) => addCodePoints(used, s.text));
  addCodePoints(used, liveJs);
  Object.values(data).forEach((t) => addCodePoints(used, t));   // showtime.json, xray.json, notes.json (note names: ♯ ♭)
  let fontsDropped = 0;
  const cssOut = styles.map((st) => {
    let css = st.text;
    if (!o.allFonts) { const r = pruneFontFaces(css, used); css = r.text; fontsDropped += r.dropped; }
    css = css.replace(/url\(\s*(['"]?)([^'")]+)\1\s*\)/g, (m, q, u) => {
      const r = read(u, st.url, true);
      if (!r) return m;
      const mime = FONT_MIME[r.ext] || IMG_MIME[r.ext];
      if (!mime) { missing.push(r.url + ' (not a font or an image)'); return m; }
      files.push({ url: r.url, bytes: r.buf.length, kind: FONT_MIME[r.ext] ? 'font' : 'image' });
      return `url(data:${mime};base64,${r.buf.toString('base64')})`;
    });
    return mini ? minifyCss(css) : css;
  });
  const js = (t) => jsSafe(mini ? minifyJs(t).text : t);
  const cfgTag = `<script type="application/json" id="xl-cfg">${safeJson({ data, live })}</script>`;
  const jsOut = scripts.map((s) => (s.stage ? `${cfgTag}\n<script>\n${js(pre)}\n</script>\n<script>\n${js(s.text)}\n</script>` : `<script>\n${js(s.text)}\n</script>`));
  html = html.replace(/\u0000S(\d+)\u0000/g, (m, i) => jsOut[+i]);
  html = html.replace(/\u0000C(\d+)\u0000/g, (m, i) => `<style>\n${cssOut[+i].replace(/<\/style/gi, '<\\/style')}\n</style>`);

  // ---- head: charset, the notice, the policy, the title and the link-preview words
  const title = live.title;
  html = html.replace(/<title>[^<]*<\/title>/i, () => `<title>${attrEsc(title)}</title>`);
  if (!/<title>/i.test(html)) html = html.replace(/<head([^>]*)>/i, (m, a) => `<head${a}>\n<title>${attrEsc(title)}</title>`);
  const desc = 'An X-ray of a real clip: play it with its sound, jump from event to event and see the inside drawn on each frame.';
  const fontPkgs = [...new Set(files.filter((f) => f.kind === 'font').map((f) => (/^\/_lib\/((?:@[^/]+\/)?[^/]+)\//.exec(f.url) || [])[1]).filter(Boolean))];
  const ofl = fontPkgs.filter((p) => {
    try { return /OFL/i.test(JSON.parse(fs.readFileSync(path.join(nodeModulesDir(), ...p.split('/'), 'package.json'), 'utf8')).license || ''); } catch { return false; }
  });
  const credits = [live.credit, ofl.length ? `Fonts: ${ofl.join(', ')}, under the SIL Open Font License 1.1 (https://openfontlicense.org)` : ''].filter(Boolean);
  const notice = (`An X-ray's live page, exported with ${live.generator}; every file it uses is packed inside.\n` +
    notices(new Map(files.map((f) => [f.url, f])), { projDir: projectDir, extraCredits: credits }))
    .replace('Third-party packages (their own license headers are kept in the packed files):', 'Third-party packages packed in this file:');
  html = html.replace(/<meta\s+charset="[^"]*"\s*\/?>\s*/i, '');
  const head = `\n<meta charset="utf-8">\n<!--\n${notice.replace(/--/g, '- -')}\n-->` +
    (o.noCsp ? '' : `\n<meta http-equiv="Content-Security-Policy" content="${FIGURE_CSP}">`) +
    '\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">' +
    `\n<meta name="description" content="${attrEsc(desc)}">\n<meta property="og:title" content="${attrEsc(title)}">` +
    `\n<meta property="og:description" content="${attrEsc(desc)}">\n<meta property="og:type" content="website">\n<meta name="twitter:card" content="summary">`;
  html = html.replace(/<meta\s+name="viewport"[^>]*>\s*/gi, '');
  html = html.replace(/<head([^>]*)>/i, (m, a) => `<head${a}>${head}`);

  // any remaining reference to a file is a page that would reach the network or miss a file offline
  for (const m of html.matchAll(/(?<![\w-])(?:src|href)="([^"#][^"]*)"/gi)) {
    const f = figureFile(m[1], { projectDir, base });
    if (!f.inline) (f.remote ? remote : missing).push(f.remote || f.url || m[1]);
  }
  const tail = `<style data-xl>\n${mini ? minifyCss(liveCss) : liveCss}\n</style>\n`;
  const render = () => {
    const mediaTags = [...media].map(([u, m]) => `<script type="text/plain" data-xl-media="${m.key}" data-type="${m.mime}" data-src="${attrEsc(u)}">${m.bytes.toString('base64')}</script>`).join('\n');
    const end = `${tail}${mediaTags}\n<script>\n${js(liveJs)}\n</script>\n`;
    return /<\/body>/i.test(html) ? html.replace(/<\/body>/i, () => `${end}</body>`) : html + end;
  };
  return { render, media, files, fontsDropped, missing: [...new Set(missing)], remote: [...new Set(remote)], page, live };
}

/** The command: pack, fit the clip under --max-mb when it is the reason, write, report. */
export async function exportXrayLive({ a, proj, out, title, target, maxMb, warnings, addWarn, T0 }) {
  const quiet = !!a.quiet;
  const say = (m) => { if (!quiet) console.error(c.dim(m)); };
  const p = packXrayLive({ projectDir: proj.dir, config: proj.config || {}, title, prompt: a.prompt, page: a.page, allFonts: !!a['all-fonts'],
    minify: String(a.minify || 'auto').toLowerCase() !== 'off', noCsp: !!a['no-csp'] });
  if (p.remote.length) throw new UserError(`the X-ray page loads ${p.remote.slice(0, 3).join(', ')} from the network; the live page is offline`, 'use a local copy (fonts: /_st/themes/fonts/*.css)');
  if (p.missing.length) throw new UserError(`the X-ray page needs files that are not there: ${p.missing.slice(0, 6).join(', ')}`, `fix the paths in ${p.page} (relative to the project; /_st/ is built in)`);
  let html = p.render();
  const refit = [];
  const fitMode = String(a.fit || 'auto').toLowerCase();
  if (maxMb > 0 && Buffer.byteLength(html) > maxMb * MB && fitMode !== 'off') {
    const workDir = fs.mkdtempSync(path.join(os.tmpdir(), 'showtime-xray-live-'));
    try {
      const map = new Map([...p.media].map(([u, m]) => [u, m]));     // fit.mjs re-encodes {mime, bytes} in place
      for (let k = 0; k < 3 && Buffer.byteLength(html) > maxMb * MB; k++) {
        const r = await fitFootage(map, { over: Buffer.byteLength(html) - maxMb * MB, workDir, say: (m) => say(`  fit: ${m}`) });
        for (const it of r.items) { const i = refit.findIndex((x) => x.path === it.path); if (i >= 0) refit[i] = it; else refit.push(it); }
        if (!r.items.length) { if (r.reason) addWarn(`could not fit the clip under ${maxMb} MB: ${r.reason}`); break; }
        html = p.render();
      }
    } finally { fs.rmSync(workDir, { recursive: true, force: true }); }
  }
  const bytes = Buffer.byteLength(html);
  if (maxMb > 0 && bytes > maxMb * MB) {
    const big = p.files.slice().sort((x, y) => y.bytes - x.bytes).slice(0, 4).map((f) => `${f.url} ${fmtBytes(f.bytes)}`).join(', ');
    throw new UserError(`the live page is ${fmtBytes(bytes)}, over --max-mb ${maxMb}; largest: ${big}`,
      'trim the clip to the part that matters (showtime footage trim), or raise --max-mb (an artifact is limited to 16 MB)');
  }
  const unknown = unknownMechanisms(p.live.made);
  if (unknown.length) addWarn(p.live.made.own
    ? `xray.made.commands name --mechanism ${unknown.join(', ')}, which the mechanism library (library/xray) does not have: the page would show a command that does not run; write the steps that made it`
    : `the page's commands say \`new xray --mechanism ${unknown.join(', ')}\`, which the mechanism library (library/xray) does not have; list the steps that made it in showtime.json xray.made.commands`);
  const local = localPathLines(p.live.made);
  if (local.length) addWarn(`xray.made.commands carry a local path (${local.slice(0, 2).join(' | ')}): the live page is shared; write placeholders (clip.mp4, <job>)`);
  if (p.live.made.guessed) addWarn('the project names no mechanism (showtime.json xray.made.mechanism, or XRAY.mechanism({name}) in mechanism.js): the page\'s commands say typewriter; set xray.made = {mechanism, layout, theme}');
  if (refit.length) addWarn(`the clip was re-encoded for this export only (${refit.map((r) => `${r.kbps} kb/s`).join(', ')}) to stay under ${maxMb} MB; the project's files are unchanged`);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, html);
  const report = { output: out, interactive: true, kind: 'xray-live', layout: p.live.layout, tracked: p.live.tracked, page: p.page, bytes,
    mb: +(bytes / MB).toFixed(2), max_mb: maxMb, title: p.live.title, target, files: p.files.length, fonts_dropped: p.fontsDropped,
    media: [...p.media].map(([u, m]) => ({ path: u, bytes: m.bytes.length })), footage_refit: refit, made: { prompt: p.live.made.prompt, commands: p.live.made.commands, guessed: p.live.made.guessed, own: p.live.made.own, unknown_mechanisms: unknown },
    largest: p.files.slice().sort((x, y) => y.bytes - x.bytes).slice(0, 6), warnings, seconds: +((Date.now() - T0) / 1000).toFixed(1) };
  if (a.json) process.stdout.write(JSON.stringify(report, null, 2) + '\n');
  else {
    console.log(`${c.green('exported')} ${out}`);
    console.log(`  the X-ray live page: ${fmtBytes(bytes)} of ${maxMb || 'unlimited'} MB, one file; it makes no network request`);
    console.log('  play the clip with its sound, click a tick or press the arrow keys to jump event to event, 0.25x around one;');
    console.log(`  links like #hit4 (the 4th event) or #t2.5 open a moment; add _light or _dark${p.live.tracked ? ', _through or _split' : ''} (#hit4_light)`);
    console.log(p.live.made.prompt ? `  the page shows this prompt as the line that made it: "${p.live.made.prompt}"` : '  no prompt is embedded (pass --prompt "<the request>" to show the line that made it); the page lists the commands');
    showCard({ title: `${path.basename(out)} is ready`, file: out, facts: ['X-ray live page', fmtBytes(bytes)], next: openHint(out) });
  }
  return 0;
}

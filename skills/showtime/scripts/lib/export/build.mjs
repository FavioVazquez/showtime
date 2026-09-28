// Assemble an exported HTML video: one self-contained .html (default), or a folder
// (index.html + assets/) for large projects and web hosting.
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { skillDir, nodeModulesDir, showtimeHome } from '../deps.mjs';
import { isText, isMedia, isJs, isCss, VORIGIN } from './collect.mjs';
import { minifyJs, minifyCss } from './minify.mjs';

// Text files (scripts, styles, data, the page, the stage boot) travel gzip-compressed in the single
// file and are unpacked by the player with the browser's DecompressionStream (2023+ browsers);
// the player itself is compressed the same way behind a few lines of loader.
const GZ_TYPE = 'application/x-showtime-gzip';
function gz(text) { return zlib.gzipSync(Buffer.from(text, 'utf8'), { level: 9 }); }
/** Tiny loader: unpack #st-player and run it (as a blob: script, so stack traces name it). */
const LOADER = `(function(){var D=document,z=D.getElementById('st-player');if(!z)return;
var R;window.showtimePlayer={__stub:1,ready:new Promise(function(r){R=r})};window.__stpReady=R;
function fail(m){var s=D.getElementById('stp');if(s)s.insertAdjacentHTML('beforeend','<div class="stp-noscript">'+m+'</div>')}
if(typeof DecompressionStream!=='function'){fail('This video needs a current browser (Chrome, Edge, Firefox or Safari from 2023 on).');return}
var b=atob(z.textContent.trim()),u=new Uint8Array(b.length);for(var i=0;i<b.length;i++)u[i]=b.charCodeAt(i);z.textContent='';
new Response(new Blob([u]).stream().pipeThrough(new DecompressionStream('gzip'))).text().then(function(t){
var s=D.createElement('script');s.src=URL.createObjectURL(new Blob([t],{type:'text/javascript'}));D.body.appendChild(s)},
function(e){fail('This video could not start: '+e)})})();`;

export const CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' blob: data:",
  "style-src 'unsafe-inline' blob: data:",
  'img-src blob: data:', 'font-src blob: data:', 'media-src blob: data:', 'connect-src blob: data:',
  'worker-src blob: data:', "frame-src 'self' blob: data: about:", 'child-src blob: data: about:',
  "object-src 'none'", `base-uri ${VORIGIN}`, "form-action 'none'",
].join('; ');

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
/** JSON that is safe inside <script type="application/json"> (and a classic script). */
export const safeJson = (o) => JSON.stringify(o).replace(/</g, '\\u003c').replace(/[\u2028\u2029]/g, (ch) => (ch === '\u2028' ? '\\u2028' : '\\u2029'));

export function category(mime, p) {
  if (/^font\//.test(mime) || /\.(woff2?|ttf|otf)$/i.test(p)) return 'fonts';
  if (/javascript/.test(mime)) return 'scripts';
  if (/^text\/css/.test(mime)) return 'styles';
  if (/^video\//.test(mime)) return 'video';
  if (/^audio\//.test(mime)) return 'audio';
  if (/^image\//.test(mime)) return 'images';
  return 'data';
}

function readRuntime(rel) { return fs.readFileSync(path.join(skillDir(), 'runtime', ...rel.split('/')), 'utf8'); }
/**
 * The stage runtime as an export runs it: always in render mode (boot.js sets __ST_RENDER__), so
 * everything after `if (RENDER) { ...; return; }` (the preview loop and the preview player UI) is
 * never reached and is left out. The cut is made only when that exact shape is found.
 */
export function stageForExport(t) {
  const m = /\n  if \(RENDER\) \{\n    installShim\(RENDER\.seed\);\n    return;\n  \}\n/.exec(t);
  const end = t.lastIndexOf('\n})();');
  if (!m || end < m.index) return t;
  return t.slice(0, m.index + m[0].length) + '  // (preview and preview player: not used in an export)\n' + t.slice(end + 1);
}
/** A runtime file, minified when asked (the tests compare frames and sound with and without). */
function runtimeText(rel, mini) {
  let t = readRuntime(rel);
  if (rel === 'stage.js' && mini) t = stageForExport(t);
  if (!mini) return t;
  return /\.css$/.test(rel) ? minifyCss(t) : minifyJs(t).text;
}

export function showtimeVersion() {
  try { return JSON.parse(fs.readFileSync(path.join(skillDir(), 'setup', 'package.json'), 'utf8')).version || '0'; } catch { return '0'; }
}

/** Third-party notices for the packed files (packages, asset sidecars, project credits). */
export function notices(files, { projDir, extraCredits = [] } = {}) {
  const lines = [];
  const pkgs = new Map();
  for (const p of files.keys()) {
    const m = /^\/_lib\/((?:@[^/]+\/)?[^/]+)\//.exec(p);
    if (!m || pkgs.has(m[1])) continue;
    try {
      const j = JSON.parse(fs.readFileSync(path.join(nodeModulesDir(), ...m[1].split('/'), 'package.json'), 'utf8'));
      pkgs.set(m[1], `${j.name}@${j.version} (${typeof j.license === 'string' ? j.license : (j.license && j.license.type) || 'see package'})`);
    } catch { pkgs.set(m[1], `${m[1]} (see its package)`); }
  }
  if (pkgs.size) lines.push('Third-party packages (their own license headers are kept in the packed files):', ...[...pkgs.values()].map((s) => `  ${s}`));
  const credits = new Set(extraCredits.filter(Boolean));
  const sidecar = (abs) => {
    for (const f of [`${abs}.license.json`, abs.replace(/\.[^.]+$/, '.license.json')]) {
      try { const j = JSON.parse(fs.readFileSync(f, 'utf8')); if (j.credit) return j.credit; if (j.license) return `${path.basename(abs)} (${j.license})`; } catch { /* none */ }
    }
    return null;
  };
  const assets = path.join(showtimeHome(), 'assets');
  for (const p of files.keys()) {
    if (p.startsWith('/_assets/')) { const c = sidecar(path.join(assets, ...p.slice(9).split('/'))); if (c) credits.add(c); }
    else if (p.startsWith('/_st/emoji/')) { const f = findEmoji(path.join(assets, 'emoji'), p.slice(11).replace(/\.svg$/i, '')); const c = f && sidecar(f); if (c) credits.add(c); }
  }
  if (projDir) {
    for (const n of ['CREDITS.txt', 'credits.txt']) {
      try { for (const l of fs.readFileSync(path.join(projDir, n), 'utf8').split(/\r?\n/)) if (l.trim()) credits.add(l.trim()); } catch { /* none */ }
    }
  }
  if (credits.size) lines.push('Credits:', ...[...credits].map((s) => `  ${s}`));
  lines.push('The showtime runtime and player are MIT licensed.');
  return lines.join('\n').replace(/--/g, '- -');
}

function findEmoji(dir, code) {
  const want = [code, code.replace(/-fe0f/g, '')];
  for (const set of ['noto', 'fluent', 'fluent-flat', 'twemoji', 'openmoji']) {
    let names;
    try { names = fs.readdirSync(path.join(dir, set)); } catch { continue; }
    for (const w of want) {
      const hit = names.find((n) => /\.svg$/i.test(n) && (n.toLowerCase() === `${w}.svg` || (n.toLowerCase().startsWith(`${w}-`) &&
        !/^[0-9a-f]{2,6}$/.test(n.slice(w.length + 1).split(/[-.]/)[0]))));
      if (hit) return path.join(dir, set, hit);
    }
  }
  return null;
}

/**
 * Write the export.
 * @param o.files     Map(path -> {mime, bytes, text?})   (the page itself is not in it)
 * @param o.manifest  player manifest (without html/files)
 * @param o.html      page source
 * @param o.poster    JPEG Buffer | null
 * @param o.audio     {path, mime, file} | null   (embed mode)
 * @param o.out       output .html (single) or folder (folder mode)
 * @param o.folder    boolean
 * @param o.notice    text for the header comment
 * @param o.mediaInline  single-file: always inline (default); folder: media and big images become files
 * -> { output, bytes, breakdown: [{path, category, bytes}], totals: {category: bytes}, files: n }
 */
export function writeExport(o) {
  const mini = o.minify !== false;
  const pack = !o.folder && o.compress !== false;      // gzip the text files (single file only)
  const entries = {};        // what the stage frame reads: {path: {t, s | b | u}}
  const zEntries = {};       // text entries that travel compressed
  const breakdown = [];
  const folderFiles = [];
  const addEntry = (p, mime, bytes, text) => {
    const cat = category(mime, p);
    const externalize = o.folder && (isMedia(mime) || (/^image\//.test(mime) && !/svg/.test(mime) && bytes.length > 1024 * 1024));
    if (externalize) {
      const rel = 'assets/media' + p.split('/').map((s) => encodeURIComponent(s)).join('/');
      folderFiles.push({ rel: 'assets/media' + p, bytes });
      entries[p] = { t: mime, u: rel, n: bytes.length };
      breakdown.push({ path: p, category: cat, bytes: bytes.length, external: true });
      return;
    }
    if (text !== undefined && isText(mime)) {
      if (pack) zEntries[p] = { t: mime, s: text };
      else entries[p] = { t: mime, s: text };
      breakdown.push({ path: p, category: cat, bytes: jsonBytes(text), text: pack });
    } else {
      const b64 = bytes.toString('base64');
      entries[p] = { t: mime, b: b64 };
      breakdown.push({ path: p, category: cat, bytes: b64.length });
    }
  };
  for (const [p, f] of o.files) addEntry(p, f.mime, f.bytes, f.text);
  const boot = runtimeText('player/boot.js', mini);
  const stage = runtimeText('stage.js', mini);
  addEntry('/_st/stage.js', 'text/javascript', Buffer.from(stage), stage);

  const manifest = { ...o.manifest, html: o.html, stage: '/_st/stage.js', bootSrc: boot, folder: !!o.folder };
  let audioTag = '';
  if (o.audio) {
    const bytes = fs.readFileSync(o.audio.file);
    if (o.folder) {
      const rel = 'assets/media' + o.audio.path;
      folderFiles.push({ rel, bytes });
      manifest.audio = { ...manifest.audio, url: rel };
      breakdown.push({ path: o.audio.path, category: 'audio', bytes: bytes.length, external: true });
    } else {
      const b64 = bytes.toString('base64');
      audioTag = `<script type="application/json" id="st-audio">${safeJson({ t: o.audio.mime, b: b64 })}</script>`;
      breakdown.push({ path: o.audio.path, category: 'audio', bytes: b64.length });
    }
  }
  const css = runtimeText('player/player.css', mini);
  const player = runtimeText('player/limiter.js', mini) + '\n' + runtimeText('player/player.js', mini);
  let posterSrc = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
  if (o.poster) {
    if (o.folder) { folderFiles.push({ rel: 'assets/poster.jpg', bytes: o.poster }); posterSrc = 'assets/poster.jpg'; }
    else posterSrc = `data:image/jpeg;base64,${o.poster.toString('base64')}`;
  }
  // the packed files are read by the stage frame (boot.js): inline, or assets/vfs.js next to index.html
  let filesTag = '', playerTag, zBytes = 0, zText = 0;
  if (pack) {
    // the page, the stage boot and every text file, compressed together; the player unpacks them
    const z = { files: zEntries, html: manifest.html, boot: manifest.bootSrc };
    delete manifest.html; delete manifest.bootSrc;
    manifest.packed = true;
    const zjson = safeJson(z);
    const zb = gz(zjson).toString('base64');
    zText = Buffer.byteLength(zjson); zBytes = zb.length;
    // the player's stylesheet travels in its bundle too (only the page background is needed before it runs)
    const zp = gz(`(function(){var s=document.createElement('style');s.textContent=${JSON.stringify(css).replace(/</g, '\\u003c')};document.head.appendChild(s)})();\n` + player).toString('base64');
    filesTag = `<script type="application/json" id="st-files">${safeJson(entries)}</script>\n` +
      `<script type="${GZ_TYPE}" id="st-zfiles">${zb}</script>\n${audioTag}`;
    playerTag = `<script type="${GZ_TYPE}" id="st-player">${zp}</script>\n<script>\n${LOADER}\n</script>`;
    zBytes += zp.length;
  } else {
    filesTag = o.folder ? '' : `<script type="application/json" id="st-files">${safeJson(entries)}</script>\n${audioTag}`;
    playerTag = `<script>\n${player}\n</script>`;
  }
  // the page around the picture is the film's own ground from the first paint (no black flash)
  const ground = /^(#[0-9a-f]{3,8}|rgba?\([\d\s.,%/]+\))$/i.test(String(manifest.background || '').trim()) ? String(manifest.background).trim() : '#000';
  const fill = {
    LANG: o.lang || 'en',
    CSP: o.folder || o.noCsp ? '' : `<meta http-equiv="Content-Security-Policy" content="${CSP}">`,
    TITLE: esc(manifest.title || 'video'),
    GENERATOR: esc(manifest.generator),
    DESCRIPTION: esc(o.description || `${manifest.title || 'Video'}: ${manifest.width}x${manifest.height}, ${manifest.duration.toFixed(1)} s, made with showtime`),
    NOTICE: String(o.notice || '').replace(/--/g, '- -'),
    CSS: pack ? `html,body{margin:0;height:100%;background:${ground};overflow:hidden}.stp{position:fixed;inset:0;background:${ground}}.stp-poster{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}.stp-noscript{position:absolute;left:50%;bottom:12%;transform:translateX(-50%);padding:10px 14px;border-radius:10px;background:rgba(18,19,23,.82);color:#f4f5f8;font:500 13px/1.3 system-ui,sans-serif}` : css,
    POSTER: esc(posterSrc),
    MANIFEST: safeJson(manifest),
    FILES: filesTag,
    PLAYER: playerTag,
  };
  const shell = readRuntime('player/shell.html');
  const html = shell.replace(/\{\{([A-Z]+)\}\}/g, (all, k) => (k in fill ? fill[k] : all));

  let output, bytes;
  if (o.folder) {
    fs.mkdirSync(path.join(o.out, 'assets'), { recursive: true });
    output = path.join(o.out, 'index.html');
    fs.writeFileSync(output, html);
    const vfs = `/* packed files of a showtime HTML video */\nwindow.__ST_FILES__ = ${safeJson(entries)};\n`;
    fs.writeFileSync(path.join(o.out, 'assets', 'vfs.js'), vfs);
    for (const f of folderFiles) {
      const dst = path.join(o.out, ...f.rel.split('/'));
      fs.mkdirSync(path.dirname(dst), { recursive: true });
      fs.writeFileSync(dst, f.bytes);
    }
    bytes = Buffer.byteLength(html) + Buffer.byteLength(vfs) + folderFiles.reduce((s, f) => s + f.bytes.length, 0);
  } else {
    output = o.out;
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, html);
    bytes = Buffer.byteLength(html);
  }
  // sizes as they are in the file: compressed text files count their share of the compressed pack
  if (pack && zText > 0) {
    const ratio = zBytes / (zText + Buffer.byteLength(player));
    for (const b of breakdown) if (b.text) b.bytes = Math.round(b.bytes * ratio);
  }
  const player_ = pack ? 400 + LOADER.length + Math.round((Buffer.byteLength(css) + Buffer.byteLength(player) + jsonBytes(boot) + jsonBytes(o.html)) * (zBytes / Math.max(1, zText + Buffer.byteLength(player))))
    : Buffer.byteLength(css) + Buffer.byteLength(player) + jsonBytes(boot) + jsonBytes(o.html);
  breakdown.push({ path: '(player, page)', category: 'player', bytes: player_ });
  if (o.poster) breakdown.push({ path: '(poster frame)', category: 'poster', bytes: o.folder ? o.poster.length : Math.ceil(o.poster.length * 4 / 3) });
  const totals = {};
  for (const b of breakdown) { totals[b.category] = (totals[b.category] || 0) + b.bytes; delete b.text; }
  breakdown.sort((a, b) => b.bytes - a.bytes);
  return { output, bytes, html: Buffer.byteLength(html), breakdown, totals, files: Object.keys(entries).length + Object.keys(zEntries).length, compressed: pack, minified: mini };
}

/** Bytes a text takes inside the file (JSON string, with the escapes safeJson adds). */
export function jsonBytes(text) { return Buffer.byteLength(safeJson(String(text))); }

// compressed text (minified, gzip, base64) is typically a third of its plain size; estimates use a
// conservative 0.5 so the pre-check never refuses what would fit (the written file is checked too)
const Z_EST = 0.5;
/** Bytes of the player itself: shell, CSS, player + limiter, boot (JSON) and stage.js (JSON). */
export function playerBytes(html = '', { compress = true } = {}) {
  let n = 0;
  for (const f of ['player/shell.html', 'player/player.css', 'player/limiter.js', 'player/player.js']) n += Buffer.byteLength(readRuntime(f));
  n += jsonBytes(readRuntime('player/boot.js')) + jsonBytes(readRuntime('stage.js')) + jsonBytes(html);
  return Math.round(n * (compress ? Z_EST : 1)) + 2048; // + manifest, notice
}

/** Size of the single file before writing (same arithmetic as writeExport, compression estimated). */
export function estimateSingle(files, { poster, audioBytes = 0, html = '', compress = true }) {
  let n = playerBytes(html, { compress });
  for (const [, f] of files) n += f.text !== undefined && isText(f.mime) ? Math.round(jsonBytes(f.text) * (compress ? Z_EST : 1)) : Math.ceil(f.bytes.length * 4 / 3);
  if (poster) n += Math.ceil(poster.length * 4 / 3);
  n += Math.ceil(audioBytes * 4 / 3);
  return n;
}

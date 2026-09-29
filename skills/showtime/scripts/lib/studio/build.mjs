// Assemble the board page from the fixed templates in runtime/studio/ plus a board snapshot.
// The agent never edits the templates: it writes board.json and the page renders it.
//
//   buildPage(board, {mode, nonce, target})   mode 'live' (served by the studio server; scripts carry a CSP nonce),
//                                     'static' (board.html next to board.json; media are relative files),
//                                     'export' (single self-contained file; media inlined as data: URIs);
//                                     target 'artifact' marks an export for a sandboxed host (no download button)
//   inlineMedia(board, studioDir)     -> {board, bytes, skipped: [{path, bytes, why}]}
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { safeMediaFile, mimeOf } from './paths.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
export const Core = require('./core.cjs');

export function runtimeDir() {
  const skill = process.env.SHOWTIME_SKILL || path.resolve(HERE, '..', '..', '..');
  return path.join(skill, 'runtime', 'studio');
}

export const TEMPLATE_FILES = () => ['board.html', 'board.css', 'board.js'].map((f) => path.join(runtimeDir(), f)).concat(path.join(HERE, 'core.cjs'));

function read(name) { return fs.readFileSync(path.join(runtimeDir(), name), 'utf8'); }

/** JSON inside <script type="application/json"> must never contain "</script", "<!--" or raw U+2028/9. */
export function embedJSON(obj) {
  return JSON.stringify(obj).replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
}
const scriptSafe = (s) => s.replace(/<\/script/gi, '<\\/script').replace(/<!--/g, '<\\!--');
const attr = (s) => String(s).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

// Used only in exports: the file must never touch the network, wherever it is opened.
const EXPORT_CSP = "default-src 'none'; img-src data: blob:; media-src data: blob:; font-src data:; style-src 'unsafe-inline'; " +
  "script-src 'unsafe-inline'; connect-src 'none'; base-uri 'none'; form-action 'none'";

/** Remove the feedback-file download (the regions between ST:DL markers) from a template. */
export function stripDownload(text) {
  return text.replace(/<!--ST:DL-->[\s\S]*?<!--ST:\/DL-->/g, '').replace(/\/\*ST:DL\*\/[\s\S]*?\/\*ST:\/DL\*\//g, '');
}

export function buildPage(board, { mode = 'static', nonce = null, job = null, target = null } = {}) {
  const n = nonce ? ` nonce="${attr(nonce)}"` : '';
  // an artifact export carries no file-download code at all (hosts' sandboxed frames block downloads,
  // and some viewers warn about pages that try): the ST:DL regions of the templates are cut out
  const strip = target === 'artifact' ? stripDownload : (s) => s;
  // nonce the template's own script tags before any content goes in
  let html = strip(read('board.html')).replace(/<script(?=[ >])/g, `<script${n}`);
  const title = attr(`${(board && board.title) || 'Studio board'} · studio`);
  const parts = {
    '<!--ST:CSP-->': mode === 'export' ? `<meta http-equiv="Content-Security-Policy" content="${EXPORT_CSP}">` : '',
    '<!--ST:MODE-->': `<meta name="st-mode" content="${attr(mode)}">` + (job ? `<meta name="st-job" content="${attr(job)}">` : '') +
      (target === 'artifact' ? '<meta name="st-host" content="artifact">' : ''),
    '/*ST:CSS*/': read('board.css').replace(/<\/style/gi, '<\\/style'),
    '/*ST:BOARD*/': embedJSON(board || {}),
    '/*ST:CORE*/': scriptSafe(fs.readFileSync(path.join(HERE, 'core.cjs'), 'utf8')),
    '/*ST:APP*/': scriptSafe(strip(read('board.js'))),
  };
  html = html.replace('<title>Studio board</title>', `<title>${title}</title>`);
  // one pass, so inserted content is never scanned for placeholders again
  return html.replace(/<!--ST:(CSP|MODE)-->|\/\*ST:(CSS|BOARD|CORE|APP)\*\//g, (m) => parts[m]);
}

/**
 * Replace every media path in the board with a data: URI (single-file export).
 * Files that would push the page past `maxTotal` are left out, largest (video) first, and listed.
 */
export function inlineMedia(board, studioDir, { maxTotal = 15.5e6, maxFile = 12e6 } = {}) {
  const refs = Core.mediaRefs(board);
  const files = new Map();
  for (const r of refs) {
    if (/^data:/.test(r.value) || files.has(r.value)) continue;
    const f = safeMediaFile(studioDir, r.value);
    const mime = mimeOf(r.value);
    files.set(r.value, f.error || !mime ? { error: f.error || 'unknown file type' } : { abs: f.abs, size: f.stat.size, mime });
  }
  const skipped = [];
  // base64 grows 4/3; keep the HTML itself (~120 KB) in the budget
  const cost = (sz) => Math.ceil(sz / 3) * 4 + 40;
  const pageBudget = maxTotal - 200e3;
  let total = 0;
  const priority = (m) => (m.startsWith('image/') ? 0 : m.startsWith('font/') ? 1 : m.startsWith('audio/') ? 2 : 3);
  const order = [...files.entries()].filter(([, v]) => !v.error)
    .sort((a, b) => priority(a[1].mime) - priority(b[1].mime) || a[1].size - b[1].size);
  const keep = new Map();
  for (const [rel, v] of order) {
    const c = cost(v.size);
    if (v.size > maxFile) { skipped.push({ path: rel, bytes: v.size, why: 'file too large for a single-file page' }); continue; }
    if (total + c > pageBudget) { skipped.push({ path: rel, bytes: v.size, why: 'over the 16 MB page budget' }); continue; }
    total += c;
    keep.set(rel, `data:${v.mime.split(';')[0]};base64,${fs.readFileSync(v.abs).toString('base64')}`);
  }
  for (const [rel, v] of files) if (v.error) skipped.push({ path: rel, bytes: 0, why: v.error });
  const walk = (v, key) => {
    if (Array.isArray(v)) return v.map((x) => walk(x, key));
    if (v && typeof v === 'object') { const o = {}; for (const k of Object.keys(v)) o[k] = walk(v[k], k); return o; }
    if (typeof v === 'string' && ['src', 'thumb', 'poster'].includes(key) && !/^data:/.test(v)) return keep.get(v) || `missing:${v}`;
    return v;
  };
  return { board: walk(board), bytes: total, skipped };
}

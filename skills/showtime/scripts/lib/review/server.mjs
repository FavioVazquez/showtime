// The local review server (Node stdlib only): plays one finished video (the MP4, or the HTML export) with a
// notes layer, and keeps the notes in <job>/review/notes/notes.json. One process per notes folder.
//
// Same security model as the studio server (lib/studio/server.mjs), because what people type here ends up
// in front of an agent that can run tools:
//   - binds 127.0.0.1 only; Host must be 127.0.0.1:<port> or localhost:<port> (DNS rebinding -> 421)
//   - per-session key: `/?k=<key>` sets an HttpOnly SameSite=Strict cookie (named per port) and the page
//     drops the key from the address bar; every other request needs the cookie or the X-Review-Key header (CLI)
//   - POST needs Content-Type application/json and an Origin equal to http://<Host> (or the key header);
//     Sec-Fetch-Site cross-site requests are refused
//   - serves only the page, the one video file (byte ranges) and, for an HTML export, the files of that
//     export (no dotfiles, "..", symlinks); .state/ is never reachable
//   - CSP with a per-response nonce for the page; request bodies <= 64 KB, text <= 2000 characters
// Lifecycle: .state/server-info.json while running, .state/server-stopped.json on exit; the same port and key
// across restarts (an open tab keeps working); exits after an idle period (default 240 min).
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { sameKey, newKey, isKey, keyCookie } from '../sessionkey.mjs';
import { readJSON, writeJSONAtomic, writeJSONAtomicSync, ensureStateDir, mimeOf, slugOf } from '../studio/paths.mjs';
import { layout, load, apply, NOTICE, NotesError } from './notes.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
export function runtimeDir() {
  const skill = process.env.SHOWTIME_SKILL || path.resolve(HERE, '..', '..', '..');
  return path.join(skill, 'runtime', 'review');
}
export const TEMPLATE_FILES = () => ['review.html', 'review.css', 'review.js'].map((f) => path.join(runtimeDir(), f));

const CSP = (nonce) => `default-src 'self' data: blob:; script-src 'nonce-${nonce}'; style-src 'self' 'unsafe-inline'; ` +
  "img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; " +
  "base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
// the exported player runs its own inline scripts; it may only be framed by the review page
const EXPORT_CSP = "default-src 'self' data: blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' blob: data:; " +
  "style-src 'self' 'unsafe-inline' blob: data:; img-src 'self' blob: data:; font-src 'self' blob: data:; media-src 'self' blob: data:; " +
  "connect-src 'self' blob: data:; worker-src blob: data:; frame-src 'self' blob: data: about:; object-src 'none'; form-action 'none'; frame-ancestors 'self'";
const BASE_HEADERS = {
  'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
  'Cross-Origin-Resource-Policy': 'same-origin', 'Cross-Origin-Opener-Policy': 'same-origin',
};
const DENIED_PAGE = '<!doctype html><meta charset="utf-8"><title>review: key needed</title>' +
  '<body style="font:16px/1.5 system-ui,sans-serif;max-width:36em;margin:4em auto;padding:0 1em">' +
  '<h1 style="font-size:20px">This page needs its key</h1><p>Open the full link that your agent (or ' +
  '<code>showtime review open &lt;job&gt;</code>) printed. It ends in <code>?k=...</code>.</p></body>';

const attr = (s) => String(s).replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const embedJSON = (o) => JSON.stringify(o).replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026')
  .replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
const scriptSafe = (s) => s.replace(/<\/script/gi, '<\\/script').replace(/<!--/g, '<\\!--');
function read(name) { return fs.readFileSync(path.join(runtimeDir(), name), 'utf8'); }

/** The page: fixed templates (runtime/review/) + the config and the notes as JSON. */
export function buildPage(cfg, notes, nonce) {
  const n = ` nonce="${attr(nonce)}"`;
  let html = read('review.html').replace(/<script(?=[ >])/g, `<script${n}`);
  const parts = {
    '/*RV:CSS*/': read('review.css').replace(/<\/style/gi, '<\\/style'),
    '/*RV:CONFIG*/': embedJSON({ ...cfg, notes, notice: NOTICE }),
    '/*RV:APP*/': scriptSafe(read('review.js')),
  };
  html = html.replace('<title>Notes</title>', `<title>${attr(`Notes · ${cfg.title || cfg.media || 'video'}`)}</title>`);
  return html.replace(/\/\*RV:(CSS|CONFIG|APP)\*\//g, (m) => parts[m]);
}

/** A file of the HTML export folder: no dot segments, no symlinks, inside the folder. -> {abs, stat} | null */
function exportFile(root, rel) {
  const segs = String(rel).split('/');
  if (!segs.length || segs.some((s) => !s || s === '.' || s === '..' || s.startsWith('.') || s.includes('\\') || s.includes('\0') ||
    (process.platform === 'win32' && s.includes(':')))) return null;
  let cur = root;
  for (const s of segs) {
    cur = path.join(cur, s);
    let st;
    try { st = fs.lstatSync(cur); } catch { return null; }
    if (st.isSymbolicLink()) return null;
  }
  let st;
  try { st = fs.statSync(cur); } catch { return null; }
  if (!st.isFile()) return null;
  const inside = path.relative(fs.realpathSync(root), fs.realpathSync(cur));
  if (!inside || inside.startsWith('..') || path.isAbsolute(inside)) return null;
  return { abs: cur, stat: st };
}

/**
 * Start serving. o: {target (resolveTarget's result), info: {duration, fps, width, height}, port, idleMinutes,
 * tickMs, instance, log, onClose} -> {info, close(reason), server, token}
 */
export async function serveReview(o) {
  const T = o.target;
  const L = layout(T.notesDir);
  fs.mkdirSync(L.dir, { recursive: true });
  ensureStateDir(L);
  const log = o.log || (() => {});
  const instance = o.instance || crypto.randomBytes(8).toString('hex');
  const idleMs = Math.max(1000, (Number(o.idleMinutes) > 0 ? Number(o.idleMinutes) : 240) * 60e3);
  const tickMs = Math.max(50, Number(o.tickMs) || 1000);
  const meta = o.info || {};
  const jobName = T.job ? path.basename(T.job) : null;
  const media = path.basename(T.media);
  const exportRoot = T.kind === 'export' ? path.dirname(T.media) : null;
  const folderExport = !!exportRoot && path.basename(T.media).toLowerCase() === 'index.html';   // index.html + assets/
  const cfg = {
    job: jobName, title: jobName ? slugOf(jobName) : media, media, kind: T.kind, duration: Number(meta.duration) || 0, fps: Number(meta.fps) || 30,
    width: Number(meta.width) || 0, height: Number(meta.height) || 0,
    src: T.kind === 'video' ? `/video/${encodeURIComponent(media)}` : `/export/${encodeURIComponent(media)}`,
  };

  const prev = readJSON(L.session, null) || {};
  let token = isKey(prev.token) ? prev.token : newKey();
  const want = Number(o.port) || Number(prev.port) || 0;
  let lastActivity = Date.now();
  let closed = false;
  const tick = setInterval(() => { if (Date.now() - lastActivity > idleMs) close('idle'); }, tickMs);

  let port = 0;
  const cookieName = () => `st_review_${port}`;
  const hostOk = (req) => { const h = String(req.headers.host || '').toLowerCase(); return h === `127.0.0.1:${port}` || h === `localhost:${port}`; };
  function keyOf(req) {
    const hdr = req.headers['x-review-key'];
    if (typeof hdr === 'string') return { key: hdr, via: 'header' };
    const m = new RegExp(`(?:^|;\\s*)${cookieName()}=([0-9a-f]{64})`).exec(req.headers.cookie || '');
    return m ? { key: m[1], via: 'cookie' } : { key: null, via: null };
  }
  function send(res, code, body, type = 'application/json; charset=utf-8', extra = {}) {
    const buf = Buffer.isBuffer(body) ? body : Buffer.from(typeof body === 'string' ? body : JSON.stringify(body));
    res.writeHead(code, { ...BASE_HEADERS, 'X-Frame-Options': 'DENY', 'Content-Type': type, 'Content-Length': buf.length, ...extra });
    res.end(buf);
  }
  async function readBody(req, limit = 64 * 1024) {
    let size = 0; const chunks = [];
    for await (const ch of req) {
      size += ch.length;
      if (size > limit) { const e = new Error('request body too large (64 KB max)'); e.status = 413; throw e; }
      chunks.push(ch);
    }
    return Buffer.concat(chunks).toString('utf8');
  }
  function sendFile(req, res, abs, type, extra) {
    let size;
    try { size = fs.statSync(abs).size; } catch { return send(res, 404, { error: 'not found' }); }
    const headers = { ...BASE_HEADERS, 'Content-Type': type, 'Accept-Ranges': 'bytes', ...extra };
    const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '');
    if (m && (m[1] !== '' || m[2] !== '')) {
      let start, end;
      if (m[1] === '') { start = Math.max(0, size - Number(m[2])); end = size - 1; } else {
        start = Number(m[1]); end = m[2] === '' ? size - 1 : Math.min(Number(m[2]), size - 1);
      }
      if (start >= size || start > end) { res.writeHead(416, { ...headers, 'Content-Range': `bytes */${size}` }); return res.end(); }
      res.writeHead(206, { ...headers, 'Content-Range': `bytes ${start}-${end}/${size}`, 'Content-Length': end - start + 1 });
      if (req.method === 'HEAD') return res.end();
      return fs.createReadStream(abs, { start, end }).on('error', () => res.destroy()).pipe(res);
    }
    res.writeHead(200, { ...headers, 'Content-Length': size });
    if (req.method === 'HEAD') return res.end();
    fs.createReadStream(abs).on('error', () => res.destroy()).pipe(res);
  }
  const notesView = () => { const d = load(L.dir); return { notes: d.notes, updated: d.updated }; };

  const server = http.createServer(async (req, res) => {
    try {
      if (!hostOk(req)) return send(res, 421, { error: 'unexpected Host header' });
      const url = new URL(req.url, `http://127.0.0.1:${port}`);
      let p;
      try { p = decodeURIComponent(url.pathname); } catch { return send(res, 400, { error: 'bad path' }); }
      const method = req.method;
      const k = url.searchParams.get('k');
      if (k !== null && method === 'GET' && p === '/') {
        if (!sameKey(k, token)) return send(res, 403, DENIED_PAGE, 'text/html; charset=utf-8');
        lastActivity = Date.now();
        const nonce = crypto.randomBytes(16).toString('base64');
        return send(res, 200, `<!doctype html><meta charset="utf-8"><title>notes</title><script nonce="${nonce}">location.replace('/')</script>` +
          '<noscript><meta http-equiv="refresh" content="0;url=/"></noscript><p style="font:14px system-ui,sans-serif">Opening the video...</p>',
        'text/html; charset=utf-8', { 'Set-Cookie': keyCookie(cookieName(), token), 'Content-Security-Policy': CSP(nonce) });
      }
      const auth = keyOf(req);
      if (!sameKey(auth.key, token)) {
        return /text\/html/.test(req.headers.accept || '') && method === 'GET'
          ? send(res, 403, DENIED_PAGE, 'text/html; charset=utf-8') : send(res, 403, { error: 'missing or wrong key' });
      }
      const site = req.headers['sec-fetch-site'];
      if (site && site !== 'same-origin' && site !== 'none') return send(res, 403, { error: 'cross-site request refused' });
      if (method !== 'GET' && method !== 'HEAD') {
        const origin = req.headers.origin;
        if (origin !== undefined ? origin !== `http://${req.headers.host}` : auth.via !== 'header') return send(res, 403, { error: 'cross-origin request refused' });
      }
      lastActivity = Date.now();

      if (method === 'GET' && (p === '/' || p === '/index.html')) {
        const nonce = crypto.randomBytes(16).toString('base64');
        return send(res, 200, buildPage(cfg, load(L.dir).notes, nonce), 'text/html; charset=utf-8', { 'Content-Security-Policy': CSP(nonce) });
      }
      if (method === 'GET' && p === '/api/health') {
        return send(res, 200, { review: true, job: jobName, media: T.media, kind: T.kind, notes_dir: L.dir, pid: process.pid, instance });
      }
      if (method === 'GET' && p === '/api/notes') return send(res, 200, notesView());
      if (method === 'POST' && p === '/api/note') {
        if (!/^application\/json\s*(;|$)/i.test(req.headers['content-type'] || '')) return send(res, 415, { error: 'send application/json' });
        let input;
        try { input = JSON.parse(await readBody(req)); } catch (e) { if (e.status) throw e; return send(res, 400, { error: 'body is not valid JSON' }); }
        // the page speaks for the person (the agent writes through `showtime review notes`, under the same lock)
        const r = await apply(L.dir, input, { by: 'person', duration: cfg.duration, job: jobName, video: T.media });
        log(`note ${r.op} ${r.note ? r.note.id : ''}`);
        return send(res, 200, { ok: true, op: r.op, note: r.note, notes: r.notes });
      }
      if (method === 'POST' && p === '/api/shutdown') {
        if (auth.via !== 'header') return send(res, 403, { error: 'shutdown needs the key header' });
        const body = await readBody(req, 4096).catch(() => '');
        let want2 = null; try { want2 = JSON.parse(body || '{}').instance; } catch { /* none */ }
        if (want2 && want2 !== instance) return send(res, 409, { error: 'instance mismatch', instance });
        send(res, 200, { ok: true, pid: process.pid, instance });
        setTimeout(() => close('stop'), 20);
        return;
      }
      if ((method === 'GET' || method === 'HEAD') && T.kind === 'video' && p === `/video/${media}`) {
        return sendFile(req, res, T.media, mimeOf(T.media) || 'video/mp4', { 'Content-Security-Policy': "default-src 'none'; sandbox", 'X-Frame-Options': 'DENY' });
      }
      if ((method === 'GET' || method === 'HEAD') && exportRoot && p.startsWith('/export/')) {
        const f = exportFile(exportRoot, p.slice('/export/'.length));
        const isPage = f && path.resolve(f.abs) === path.resolve(T.media);
        // the export's own page, or files of a folder export (assets/...); never another page beside it
        if (!f || (!isPage && !(folderExport && /^assets\//.test(p.slice('/export/'.length))))) return send(res, 404, { error: 'not found' });
        const type = isPage ? 'text/html; charset=utf-8' : (mimeOf(f.abs) || ({ '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json' }[path.extname(f.abs).toLowerCase()]) || 'application/octet-stream');
        return sendFile(req, res, f.abs, type, { 'Content-Security-Policy': EXPORT_CSP, 'X-Frame-Options': 'SAMEORIGIN' });
      }
      return send(res, 404, { error: 'not found' });
    } catch (e) {
      const code = e instanceof NotesError ? e.status : (e.status || 500);
      if (code === 500) log(`error ${req.method} ${req.url}: ${e.stack || e}`);
      if (!res.headersSent) return send(res, code, { error: code === 500 ? 'internal error' : e.message });
      try { res.end(); } catch { /* gone */ }
    }
  });
  server.keepAliveTimeout = 5000;
  server.requestTimeout = 30000;
  server.headersTimeout = 15000;

  const listen = (pt) => new Promise((resolve, reject) => {
    const onErr = (e) => { server.off('listening', onOk); reject(e); };
    const onOk = () => { server.off('error', onErr); resolve(server.address().port); };
    server.once('error', onErr); server.once('listening', onOk);
    server.listen(pt, '127.0.0.1');
  });
  try { port = await listen(want); } catch (e) {
    if (e.code !== 'EADDRINUSE' && e.code !== 'EACCES') throw e;
    log(`port ${want} is taken; using a new port and a new key`);
    token = newKey();
    port = await listen(0);
  }
  await writeJSONAtomic(L.session, { port, token }, { mode: 0o600 });
  try { fs.chmodSync(L.session, 0o600); } catch { /* Windows */ }
  const base = `http://127.0.0.1:${port}/`;
  const info = {
    review: true, pid: process.pid, instance, port, job: jobName, media: T.media, kind: T.kind, url: `${base}?k=${token}`, base,
    notes_dir: L.dir, started: new Date().toISOString(), idle_timeout_min: idleMs / 60e3, log: L.log,
  };
  fs.rmSync(L.serverStopped, { force: true });
  await writeJSONAtomic(L.serverInfo, info, { mode: 0o600 });

  function close(reason = 'stop') {
    if (closed) return; closed = true;
    clearInterval(tick);
    try { server.closeAllConnections && server.closeAllConnections(); } catch { /* old node */ }
    server.close();
    try {
      const cur = readJSON(L.serverInfo, {});
      if (cur.instance === instance) fs.rmSync(L.serverInfo, { force: true });
      writeJSONAtomicSync(L.serverStopped, { reason, at: new Date().toISOString(), pid: process.pid, instance });
    } catch { /* best effort */ }
    log(`stopped (${reason})`);
    if (o.onClose) o.onClose(reason);
  }
  log(`serving ${T.media} with notes in ${L.dir} at ${base} (instance ${instance})`);
  return { info, close, server, get token() { return token; } };
}

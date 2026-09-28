// The local studio server (Node stdlib only). One process per job, bound to 127.0.0.1.
//
// Security model: the feedback it collects ends up in front of an agent that can run tools, so every
// request must come from the person the agent gave the link to.
//   - binds 127.0.0.1 only; Host must be 127.0.0.1:<port> or localhost:<port> (DNS rebinding -> 421)
//   - per-session random key: `/?k=<key>` sets an HttpOnly SameSite=Strict cookie (named per port)
//     and replaces the URL with `/` so the key leaves the address bar; every other request needs the cookie
//     (or the X-Studio-Key header, used by the CLI). Keys are compared in constant time.
//   - POST needs Content-Type application/json (forces a CORS preflight that is never granted) and an
//     Origin equal to http://<Host> (browsers) or the key header (CLI); cross-site fetches are refused
//   - only board-referenced media under studio/media/ are served: no dotfiles, "..", symlinks or hard
//     links; state (.state/: key, logs, pid) is never reachable
//   - CSP default-src 'self' data: blob: (scripts need the per-response nonce), no framing, no referrer
//   - request bodies capped at 64 KB, text fields at 2000 characters, 5000 events per job
// Lifecycle: writes .state/server-info.json while running and .state/server-stopped.json on exit;
// keeps the same port + key across restarts (open tabs reconnect by themselves); exits after an idle
// period (SHOWTIME_STUDIO_IDLE_MIN, default 240 min); `stop` asks it to exit through an authenticated
// endpoint and checks the instance id first, so it never kills an unrelated process.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { buildPage, Core, TEMPLATE_FILES } from './build.mjs';
import { readJSON, writeJSONAtomic, writeJSONAtomicSync, layout, ensureStateDir, safeMediaFile, mimeOf } from './paths.mjs';

export function emptyFeedback(job) {
  const now = new Date().toISOString();
  return { schema: Core.FEEDBACK_SCHEMA, job, created: now, updated: now, board_rev: null, events: [], state: Core.reduce([]) };
}

export function sameKey(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || !a || !b) return false;
  const ha = crypto.createHash('sha256').update(a).digest();
  const hb = crypto.createHash('sha256').update(b).digest();
  return crypto.timingSafeEqual(ha, hb) && a.length === b.length;
}

const CSP = (nonce) => `default-src 'self' data: blob:; script-src 'nonce-${nonce}'; style-src 'self' 'unsafe-inline'; ` +
  "img-src 'self' data: blob:; media-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; " +
  "base-uri 'none'; form-action 'self'; frame-ancestors 'none'";
const BASE_HEADERS = {
  'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
  'X-Frame-Options': 'DENY', 'Cross-Origin-Resource-Policy': 'same-origin', 'Cross-Origin-Opener-Policy': 'same-origin',
};
const DENIED_PAGE = '<!doctype html><meta charset="utf-8"><title>studio: key needed</title>' +
  '<body style="font:16px/1.5 system-ui,sans-serif;max-width:36em;margin:4em auto;padding:0 1em">' +
  '<h1 style="font-size:20px">This studio board needs its key</h1><p>Open the full link that Claude (or ' +
  '<code>showtime studio open &lt;job&gt;</code>) printed. It ends in <code>?k=...</code>.</p></body>';

/**
 * Start serving a studio folder.
 * o: { studioDir, port (preferred; default: last one used), idleMinutes, tickMs, instance, log, quiet }
 * -> { info, close(reason), server }
 */
export async function serveStudio(o) {
  const L = layout(o.studioDir);
  ensureStateDir(L);
  const log = o.log || (() => {});
  const instance = o.instance || crypto.randomBytes(8).toString('hex');
  const idleMs = Math.max(1000, (Number(o.idleMinutes) > 0 ? Number(o.idleMinutes) : 240) * 60e3);
  const tickMs = Math.max(50, Number(o.tickMs) || 1000);

  let board = readJSON(L.board, null);
  if (!board) throw new Error(`no readable board.json in ${L.studio}`);
  const job = board.job || path.basename(path.dirname(L.studio));
  fs.mkdirSync(L.media, { recursive: true });
  const mediaReal = fs.realpathSync(L.media);

  // ---- stable port + key: reuse the last pair so an open tab reconnects after a restart
  const prev = readJSON(L.session, null) || {};
  let token = typeof prev.token === 'string' && /^[0-9a-f]{64}$/.test(prev.token) ? prev.token : crypto.randomBytes(32).toString('hex');
  const want = Number(o.port) || Number(prev.port) || 0;

  const clients = new Set();
  let lastActivity = Date.now();
  let writeChain = Promise.resolve();
  let closed = false;

  const stamp = (p) => { try { const s = fs.statSync(p); return `${s.mtimeMs}:${s.size}`; } catch { return null; } };
  const hash = (p) => { try { return crypto.createHash('sha1').update(fs.readFileSync(p)).digest('hex'); } catch { return null; } };
  let boardStamp = stamp(L.board), boardHash = hash(L.board);
  let fbStamp = stamp(L.feedback), fbHash = hash(L.feedback);
  const loadFeedback = () => {
    const fb = readJSON(L.feedback, null);
    return fb && Array.isArray(fb.events) ? fb : emptyFeedback(job);
  };

  function broadcast(event, data) {
    const msg = `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
    for (const res of clients) { try { res.write(msg); } catch { /* closed */ } }
  }
  function checkBoard(force) {
    const s = stamp(L.board);
    if (!force && s === boardStamp) return;
    boardStamp = s;
    const h = hash(L.board);
    if (!h || h === boardHash) return;
    const next = readJSON(L.board, null);
    if (!next) return; // mid-write; the next poll sees the finished file
    boardHash = h;
    const v = Core.validateBoard(next);
    if (!v.errors.length) board = next;
    log(`board.json changed -> rev ${next.rev}${v.errors.length ? ' (not published: ' + v.errors[0] + ')' : ''}`);
    broadcast('board', { rev: next.rev, errors: v.errors.slice(0, 5) });
  }
  function checkFeedback() {
    const s = stamp(L.feedback);
    if (s === fbStamp) return;
    fbStamp = s;
    const h = hash(L.feedback);
    if (h === fbHash) return;
    fbHash = h;
    broadcast('feedback', { count: loadFeedback().events.length });
  }
  let debounce = null;
  let watcher = null;
  try {
    watcher = fs.watch(L.studio, (_ev, name) => {
      if (!name || name === 'board.json' || name === 'feedback.json') {
        clearTimeout(debounce); debounce = setTimeout(() => { checkBoard(true); checkFeedback(); }, 80);
      }
    });
    watcher.on('error', () => {});
  } catch { /* the poll below still works */ }
  const tplStamp = () => TEMPLATE_FILES().map(stamp).join(',');
  let tpl = tplStamp();
  let pingAt = Date.now();
  const tick = setInterval(() => {
    checkBoard(false); checkFeedback();
    const t = tplStamp(); if (t !== tpl) { tpl = t; broadcast('reload', {}); }
    if (Date.now() - pingAt > 15000) { pingAt = Date.now(); broadcast('ping', { t: pingAt }); }
    if (Date.now() - lastActivity > idleMs) close('idle');
  }, tickMs);

  // ---- request guards
  let port = 0;
  const cookieName = () => `st_studio_${port}`;
  const hostOk = (req) => { const h = String(req.headers.host || '').toLowerCase(); return h === `127.0.0.1:${port}` || h === `localhost:${port}`; };
  function keyOf(req) {
    const hdr = req.headers['x-studio-key'];
    if (typeof hdr === 'string') return { key: hdr, via: 'header' };
    const m = new RegExp(`(?:^|;\\s*)${cookieName()}=([0-9a-f]{64})`).exec(req.headers.cookie || '');
    return m ? { key: m[1], via: 'cookie' } : { key: null, via: null };
  }
  function send(res, code, body, type = 'application/json; charset=utf-8', extra = {}) {
    const buf = Buffer.isBuffer(body) ? body : Buffer.from(typeof body === 'string' ? body : JSON.stringify(body));
    res.writeHead(code, { ...BASE_HEADERS, 'Content-Type': type, 'Content-Length': buf.length, ...extra });
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
  function serveMedia(req, res, rel) {
    const f = safeMediaFile(L.studio, rel, { mediaReal });
    const type = mimeOf(rel);
    if (f.error || !type) return send(res, 404, { error: 'not found' });
    const size = f.stat.size;
    const headers = { ...BASE_HEADERS, 'Content-Type': type, 'Accept-Ranges': 'bytes', 'Content-Security-Policy': "default-src 'none'; sandbox" };
    const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '');
    if (m && (m[1] !== '' || m[2] !== '')) {
      let start, end;
      if (m[1] === '') { start = Math.max(0, size - Number(m[2])); end = size - 1; } else {
        start = Number(m[1]); end = m[2] === '' ? size - 1 : Math.min(Number(m[2]), size - 1);
      }
      if (start >= size || start > end) { res.writeHead(416, { ...headers, 'Content-Range': `bytes */${size}` }); return res.end(); }
      res.writeHead(206, { ...headers, 'Content-Range': `bytes ${start}-${end}/${size}`, 'Content-Length': end - start + 1 });
      if (req.method === 'HEAD') return res.end();
      return fs.createReadStream(f.abs, { start, end }).on('error', () => res.destroy()).pipe(res);
    }
    res.writeHead(200, { ...headers, 'Content-Length': size });
    if (req.method === 'HEAD') return res.end();
    fs.createReadStream(f.abs).on('error', () => res.destroy()).pipe(res);
  }

  const server = http.createServer(async (req, res) => {
    try {
      if (!hostOk(req)) return send(res, 421, { error: 'unexpected Host header' });
      const url = new URL(req.url, `http://127.0.0.1:${port}`);
      let p;
      try { p = decodeURIComponent(url.pathname); } catch { return send(res, 400, { error: 'bad path' }); }
      const method = req.method;

      // bootstrap: the printed link carries the key once; trade it for a cookie and drop it from the URL
      const k = url.searchParams.get('k');
      if (k !== null && method === 'GET' && p === '/') {
        if (!sameKey(k, token)) return send(res, 403, DENIED_PAGE, 'text/html; charset=utf-8');
        lastActivity = Date.now();
        // A page (not a 302): the follow-up navigation then starts from our own origin, so the
        // SameSite=Strict cookie is sent even when the link was clicked on another site.
        const nonce = crypto.randomBytes(16).toString('base64');
        return send(res, 200, `<!doctype html><meta charset="utf-8"><title>studio</title><script nonce="${nonce}">location.replace('/')</script>` +
          '<noscript><meta http-equiv="refresh" content="0;url=/"></noscript><p style="font:14px system-ui,sans-serif">Opening the board...</p>',
        'text/html; charset=utf-8', { 'Set-Cookie': `${cookieName()}=${token}; Path=/; HttpOnly; SameSite=Strict`, 'Content-Security-Policy': CSP(nonce) });
      }
      const auth = keyOf(req);
      if (!sameKey(auth.key, token)) {
        return /text\/html/.test(req.headers.accept || '') && method === 'GET'
          ? send(res, 403, DENIED_PAGE, 'text/html; charset=utf-8') : send(res, 403, { error: 'missing or wrong studio key' });
      }
      const site = req.headers['sec-fetch-site'];
      if (site && site !== 'same-origin' && site !== 'none') return send(res, 403, { error: 'cross-site request refused' });
      if (method !== 'GET' && method !== 'HEAD') {
        const origin = req.headers.origin;
        if (origin !== undefined ? origin !== `http://${req.headers.host}` : auth.via !== 'header') {
          return send(res, 403, { error: 'cross-origin request refused' });
        }
      }
      lastActivity = Date.now();

      if (method === 'GET' && (p === '/' || p === '/index.html' || p === '/board.html')) {
        const nonce = crypto.randomBytes(16).toString('base64');
        return send(res, 200, buildPage(board, { mode: 'live', nonce, job }), 'text/html; charset=utf-8', { 'Content-Security-Policy': CSP(nonce) });
      }
      if (method === 'GET' && p === '/board.json') return send(res, 200, board);
      if (method === 'GET' && p === '/api/health') return send(res, 200, { studio: true, job, rev: board.rev, pid: process.pid, instance, clients: clients.size });
      if (method === 'GET' && p === '/api/feedback') return send(res, 200, loadFeedback());
      if (method === 'GET' && p === '/api/digest') return send(res, 200, Core.digest(board, loadFeedback()), 'text/plain; charset=utf-8');
      if (method === 'POST' && p === '/api/feedback') {
        if (!/^application\/json\s*(;|$)/i.test(req.headers['content-type'] || '')) return send(res, 415, { error: 'send application/json' });
        let input;
        try { input = JSON.parse(await readBody(req)); } catch (e) { if (e.status) throw e; return send(res, 400, { error: 'body is not valid JSON' }); }
        const ev = Core.makeEvent(input, { ts: new Date().toISOString(), board });
        if (ev.rev == null) ev.rev = Number(board.rev) || 0;
        let count = 0, dup = false;
        writeChain = writeChain.catch(() => {}).then(async () => {
          const fb = loadFeedback();
          if (fb.events.some((e) => e.id === ev.id)) { dup = true; count = fb.events.length; return; } // retried from the outbox
          if (fb.events.length >= Core.MAX_EVENTS) { const e = new Error('too many feedback events for one job'); e.status = 429; throw e; }
          fb.events.push(ev); fb.updated = ev.ts; fb.board_rev = board.rev; fb.job = job;
          fb.state = Core.reduce(fb.events);
          await writeJSONAtomic(L.feedback, fb);
          fbStamp = stamp(L.feedback); fbHash = hash(L.feedback); count = fb.events.length;
        });
        await writeChain;
        if (!dup) broadcast('feedback', { count, id: ev.id });
        return send(res, 200, { ok: true, event: ev, count, duplicate: dup });
      }
      if (method === 'POST' && p === '/api/import') { // CLI only: merge events from a downloaded feedback.json
        if (auth.via !== 'header') return send(res, 403, { error: 'import needs the key header' });
        let body;
        try { body = JSON.parse(await readBody(req, 8 * 1024 * 1024)); } catch (e) { if (e.status) throw e; return send(res, 400, { error: 'body is not valid JSON' }); }
        const incoming = [];
        for (const e of (body && Array.isArray(body.events) ? body.events : []).slice(0, Core.MAX_EVENTS)) {
          try {
            const ts = typeof e.ts === 'string' && /^\d{4}-\d\d-\d\dT[\d:.]+Z$/.test(e.ts) ? e.ts : new Date().toISOString();
            incoming.push(Core.makeEvent(e, { ts, board }));
          } catch { /* skip invalid */ }
        }
        let added = 0;
        writeChain = writeChain.catch(() => {}).then(async () => {
          const fb = loadFeedback();
          const seen = new Set(fb.events.map((e) => e.id));
          for (const ev of incoming) if (!seen.has(ev.id) && fb.events.length < Core.MAX_EVENTS) { fb.events.push(ev); seen.add(ev.id); added++; }
          fb.events.sort((x, y) => (x.ts < y.ts ? -1 : x.ts > y.ts ? 1 : 0));
          fb.state = Core.reduce(fb.events); fb.updated = new Date().toISOString(); fb.board_rev = board.rev; fb.job = job;
          await writeJSONAtomic(L.feedback, fb);
          fbStamp = stamp(L.feedback); fbHash = hash(L.feedback);
        });
        await writeChain;
        if (added) broadcast('feedback', { count: loadFeedback().events.length });
        return send(res, 200, { ok: true, added });
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
      if (method === 'GET' && p === '/api/events') {
        res.writeHead(200, { ...BASE_HEADERS, 'Content-Type': 'text/event-stream', Connection: 'keep-alive', 'X-Accel-Buffering': 'no' });
        res.write(`retry: 2000\nevent: hello\ndata: ${JSON.stringify({ rev: board.rev, instance })}\n\n`);
        clients.add(res);
        req.on('close', () => clients.delete(res));
        return;
      }
      if ((method === 'GET' || method === 'HEAD') && p.startsWith('/media/')) return serveMedia(req, res, p.slice(1));
      return send(res, 404, { error: 'not found' });
    } catch (e) {
      const code = e.status || 500;
      if (code === 500) log(`error ${req.method} ${req.url}: ${e.stack || e}`);
      if (!res.headersSent) return send(res, code, { error: code === 500 ? 'internal error' : e.message });
      try { res.end(); } catch { /* gone */ }
    }
  });
  server.keepAliveTimeout = 5000;
  server.requestTimeout = 30000;
  server.headersTimeout = 15000;

  const listen = (p) => new Promise((resolve, reject) => {
    const onErr = (e) => { server.off('listening', onOk); reject(e); };
    const onOk = () => { server.off('error', onErr); resolve(server.address().port); };
    server.once('error', onErr); server.once('listening', onOk);
    server.listen(p, '127.0.0.1');
  });
  try { port = await listen(want); } catch (e) {
    if (e.code !== 'EADDRINUSE' && e.code !== 'EACCES') throw e;
    log(`port ${want} is taken; using a new port and a new key`);
    token = crypto.randomBytes(32).toString('hex');
    port = await listen(0);
  }
  await writeJSONAtomic(L.session, { port, token }, { mode: 0o600 });
  try { fs.chmodSync(L.session, 0o600); } catch { /* Windows */ }

  const base = `http://127.0.0.1:${port}/`;
  const info = {
    studio: true, pid: process.pid, instance, port, job, url: `${base}?k=${token}`, base,
    studio_dir: L.studio, started: new Date().toISOString(), idle_timeout_min: idleMs / 60e3, log: L.log,
  };
  fs.rmSync(L.serverStopped, { force: true });
  await writeJSONAtomic(L.serverInfo, info, { mode: 0o600 });

  function close(reason = 'stop') {
    if (closed) return; closed = true;
    clearInterval(tick); clearTimeout(debounce);
    try { if (watcher) watcher.close(); } catch { /* ignore */ }
    for (const r of clients) { try { r.end(); } catch { /* ignore */ } }
    clients.clear();
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
  log(`serving ${L.studio} at ${base} (instance ${instance})`);
  return { info, close, server, get token() { return token; } };
}

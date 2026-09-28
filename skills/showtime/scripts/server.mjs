// Serve a showtime project over http://127.0.0.1 (byte ranges, /_st runtime, /_lib packages, live reload)
//
//   showtime server <project> [--port 4800] [--host 127.0.0.1] [--watch]
//
// Library use (render/check/snap/preview all share it):
//   import { startServer } from './server.mjs';
//   const srv = await startServer({ root: '/path/to/project', port: 0 });
//   srv.url  -> 'http://127.0.0.1:53211'   srv.close()
//
// Mounts:
//   /            the project folder
//   /_st/...     SKILL/runtime (stage.js, film.js, components, ...)
//   /_lib/<pkg>/ ~/.showtime/node/node_modules/<pkg>/ (animejs, three, lottie-web, fonts ...)
//   /_assets/... ~/.showtime/assets (fonts, icons, media fetched by `showtime assets`)
//   /_st/preview?page=/index.html   preview player wrapping the page in an iframe
//   /_st/project   JSON: config, audio file for the player, title
//   /_st/events    server-sent events: `reload` when a project file changes (with watch)
//   /_st/lab       blank page used by check/snap for image analysis
import http from 'node:http';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { skillDir, nodeModulesDir, showtimeHome } from './lib/deps.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));

export const MIME = {
  '.html': 'text/html; charset=utf-8', '.htm': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8', '.cjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.map': 'application/json; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8', '.md': 'text/plain; charset=utf-8', '.csv': 'text/csv; charset=utf-8',
  '.xml': 'application/xml', '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
  '.gif': 'image/gif', '.webp': 'image/webp', '.avif': 'image/avif', '.ico': 'image/x-icon', '.bmp': 'image/bmp',
  '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf', '.otf': 'font/otf',
  '.mp4': 'video/mp4', '.m4v': 'video/mp4', '.webm': 'video/webm', '.mov': 'video/quicktime', '.ogv': 'video/ogg',
  '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.m4a': 'audio/mp4', '.aac': 'audio/aac', '.ogg': 'audio/ogg',
  '.opus': 'audio/ogg', '.flac': 'audio/flac', '.wasm': 'application/wasm', '.glsl': 'text/plain; charset=utf-8',
  '.lottie': 'application/zip', '.riv': 'application/octet-stream', '.cube': 'text/plain; charset=utf-8',
  '.vtt': 'text/vtt; charset=utf-8', '.srt': 'text/plain; charset=utf-8', '.ass': 'text/plain; charset=utf-8',
};

const WATCH_IGNORE = /(^|[\\/])(\.git|node_modules|showtime-out|work|\.showtime|\.cache|__pycache__|\.DS_Store)([\\/]|$)/;

/** Resolve `rel` (URL path, already decoded) under `root`; null if it escapes. */
export function safeJoin(root, rel) {
  const clean = rel.replace(/\\/g, '/').split('/').filter((s) => s && s !== '.');
  if (clean.some((s) => s === '..' || s.includes('\0'))) return null;
  // on Windows "C:" (or "C:foo") in a segment would switch drives inside path.resolve
  if (process.platform === 'win32' && clean.some((s) => s.includes(':'))) return null;
  const abs = path.resolve(root, ...clean);
  const r = path.relative(path.resolve(root), abs);
  if (r.startsWith('..') || path.isAbsolute(r)) return null;
  return abs;
}

function readConfig(root) {
  try { return JSON.parse(fs.readFileSync(path.join(root, 'showtime.json'), 'utf8').replace(/^\uFEFF/, '')); } catch { return {}; }
}

/** The audio file the preview player should play, if any (built by `showtime preview`). */
function previewAudio(root) {
  for (const rel of ['work/mix.wav', 'work/preview-mix.wav']) {
    if (fs.existsSync(path.join(root, rel))) return '/' + rel;
  }
  const cfg = readConfig(root);
  if (typeof cfg.audio === 'string' && /\.(wav|mp3|m4a|ogg|flac|aac)$/i.test(cfg.audio) && fs.existsSync(path.join(root, cfg.audio))) {
    return '/' + cfg.audio.replace(/\\/g, '/').replace(/^\.?\//, '');
  }
  return null;
}

function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }

function playerHTML(root, page) {
  const cfg = readConfig(root);
  const P = { page, mix: previewAudio(root), title: cfg.title || path.basename(root) };
  return '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' +
    `<title>${esc(P.title)} - showtime preview</title>` +
    `<script>window.__ST_PLAYER__=${JSON.stringify(P).replace(/</g, '\\u003c')};</script>` +
    '<script src="/_st/stage.js"></script></head><body><div id="st-app"></div></body></html>';
}

const LAB_HTML = '<!doctype html><html><head><meta charset="utf-8"><title>showtime lab</title></head>' +
  '<body style="margin:0;background:#000"></body></html>';

/** An installed emoji SVG for code points "1f680" / "2764-fe0f" (Noto first, then Fluent). */
function findEmoji(dir, code) {
  const want = [code, code.replace(/-fe0f/g, '')];
  for (const set of ['noto', 'fluent', 'fluent-flat', 'twemoji', 'openmoji']) {
    let names;
    try { names = fs.readdirSync(path.join(dir, set)); } catch { continue; }
    for (const w of want) {
      const hit = names.find((n) => /\.svg$/i.test(n) && (n.toLowerCase() === `${w}.svg` || n.toLowerCase().startsWith(`${w}-`) &&
        !/^[0-9a-f]{2,6}$/.test(n.slice(w.length + 1).split(/[-.]/)[0])));
      if (hit) return path.join(dir, set, hit);
    }
  }
  return null;
}

/** Insert <script src="/_st/stage.js"> as the first script of an HTML page that lacks it. */
export function injectStage(html) {
  if (/\/_st\/stage\.js/.test(html)) return html;
  const tag = '<script src="/_st/stage.js"></script>';
  if (/<head[^>]*>/i.test(html)) return html.replace(/<head[^>]*>/i, (m) => m + tag);
  if (/<html[^>]*>/i.test(html)) return html.replace(/<html[^>]*>/i, (m) => m + '<head>' + tag + '</head>');
  return tag + html;
}

async function sendFile(req, res, file, { inject = false } = {}) {
  let st;
  try { st = await fsp.stat(file); } catch { return notFound(res, req.url); }
  if (st.isDirectory()) {
    const idx = path.join(file, 'index.html');
    if (fs.existsSync(idx)) return sendFile(req, res, idx, { inject });
    return notFound(res, req.url);
  }
  const ext = path.extname(file).toLowerCase();
  const type = MIME[ext] || 'application/octet-stream';
  const headers = {
    'Content-Type': type, 'Accept-Ranges': 'bytes', 'Cache-Control': 'no-store',
    'Access-Control-Allow-Origin': '*', 'Cross-Origin-Resource-Policy': 'cross-origin',
  };
  if (inject && ext.startsWith('.htm')) {
    const body = Buffer.from(injectStage(await fsp.readFile(file, 'utf8')), 'utf8');
    res.writeHead(200, { ...headers, 'Content-Length': body.length });
    return res.end(req.method === 'HEAD' ? undefined : body);
  }
  const size = st.size;
  const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '');
  if (m && (m[1] !== '' || m[2] !== '')) {
    let start, end;
    if (m[1] === '') { start = Math.max(0, size - Number(m[2])); end = size - 1; } else {
      start = Number(m[1]); end = m[2] === '' ? size - 1 : Math.min(Number(m[2]), size - 1);
    }
    if (start >= size || start > end) {
      res.writeHead(416, { ...headers, 'Content-Range': `bytes */${size}` });
      return res.end();
    }
    res.writeHead(206, { ...headers, 'Content-Range': `bytes ${start}-${end}/${size}`, 'Content-Length': end - start + 1 });
    if (req.method === 'HEAD') return res.end();
    return fs.createReadStream(file, { start, end }).on('error', () => res.destroy()).pipe(res);
  }
  res.writeHead(200, { ...headers, 'Content-Length': size });
  if (req.method === 'HEAD') return res.end();
  fs.createReadStream(file).on('error', () => res.destroy()).pipe(res);
}

function notFound(res, url) {
  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(`404 not found: ${url}\n`);
}

/**
 * Start the server.
 * @param {object} o
 * @param {string} o.root           project folder
 * @param {number} [o.port=0]       0 = ephemeral; otherwise first free port from here (up to +50)
 * @param {string} [o.host='127.0.0.1']
 * @param {boolean} [o.watch=false] emit `reload` events when project files change
 * @param {boolean} [o.inject=true] add /_st/stage.js to HTML pages that lack it
 * @param {(file:string)=>boolean|Promise<boolean>} [o.onChange] called on a change (with watch); return true to skip the reload
 * @param {(line:string)=>void} [o.log]
 */
export async function startServer(o) {
  const root = path.resolve(o.root);
  const host = o.host || '127.0.0.1';
  const runtimeDir = path.join(skillDir(), 'runtime');
  const libDir = nodeModulesDir();
  const assetsDir = path.join(showtimeHome(), 'assets');
  const clients = new Set();
  const log = o.log || (() => {});
  const inject = o.inject !== false;

  const server = http.createServer(async (req, res) => {
    try {
      // Only local pages may talk to us (protects against DNS rebinding).
      const h = String(req.headers.host || '').replace(/:\d+$/, '').replace(/^\[|\]$/g, '');
      if (h && !['127.0.0.1', 'localhost', '::1'].includes(h)) {
        res.writeHead(403); return res.end('forbidden host\n');
      }
      if (req.method !== 'GET' && req.method !== 'HEAD') { res.writeHead(405); return res.end(); }
      const u = new URL(req.url, 'http://127.0.0.1');
      let p;
      try { p = decodeURIComponent(u.pathname); } catch { res.writeHead(400); return res.end('bad path\n'); }
      if (p === '/_st/ping') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ app: 'showtime', root }));
      }
      if (p === '/_st/preview') {
        const page = u.searchParams.get('page') || '/index.html';
        const body = playerHTML(root, page.startsWith('/') ? page : '/' + page);
        res.writeHead(200, { 'Content-Type': MIME['.html'], 'Cache-Control': 'no-store' });
        return res.end(body);
      }
      if (p === '/_st/lab') {
        res.writeHead(200, { 'Content-Type': MIME['.html'], 'Cache-Control': 'no-store' });
        return res.end(LAB_HTML);
      }
      if (p === '/_st/project') {
        res.writeHead(200, { 'Content-Type': MIME['.json'], 'Cache-Control': 'no-store' });
        return res.end(JSON.stringify({ root, config: readConfig(root), mix: previewAudio(root) }));
      }
      if (p === '/_st/events') {
        res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', Connection: 'keep-alive' });
        res.write('retry: 1000\n\n');
        clients.add(res);
        req.on('close', () => clients.delete(res));
        return;
      }
      if (p.startsWith('/_st/emoji/')) {
        // emoji images for stage.js (Noto SVGs installed by `showtime assets emoji <char>`)
        const code = p.slice(11).replace(/\.svg$/i, '').toLowerCase();
        const f = /^[0-9a-f]{2,6}(-[0-9a-f]{2,6})*$/.test(code) ? findEmoji(path.join(assetsDir, 'emoji'), code) : null;
        if (!f) {
          const ch = code.split('-').map((h) => { try { return String.fromCodePoint(parseInt(h, 16)); } catch { return ''; } }).join('');
          res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
          return res.end(`emoji ${ch} (${code}) is not installed: run  showtime assets emoji ${ch}\n`);
        }
        res.writeHead(200, { 'Content-Type': 'image/svg+xml', 'Cache-Control': 'no-cache' });
        return fs.createReadStream(f).pipe(res);
      }
      if (p === '/favicon.ico' && !fs.existsSync(path.join(root, 'favicon.ico'))) {
        // browsers ask for it on every page; answer "nothing" instead of a noisy 404
        res.writeHead(204, { 'Cache-Control': 'max-age=86400' });
        return res.end();
      }
      let file = null;
      if (p.startsWith('/_st/')) file = safeJoin(runtimeDir, p.slice(5));
      else if (p.startsWith('/_lib/')) file = safeJoin(libDir, p.slice(6));
      else if (p.startsWith('/_assets/')) file = safeJoin(assetsDir, p.slice(9));
      else file = safeJoin(root, p === '/' ? 'index.html' : p);
      if (!file) { res.writeHead(403); return res.end('forbidden path\n'); }
      await sendFile(req, res, file, { inject: inject && !p.startsWith('/_') });
    } catch (err) {
      log(`server error ${req.url}: ${err.message}`);
      if (!res.headersSent) res.writeHead(500);
      res.end();
    }
  });
  server.keepAliveTimeout = 5000;

  const listen = (port) => new Promise((resolve, reject) => {
    const onErr = (e) => { server.off('listening', onOk); reject(e); };
    const onOk = () => { server.off('error', onErr); resolve(server.address().port); };
    server.once('error', onErr);
    server.once('listening', onOk);
    server.listen(port, host);
  });
  let port = null;
  const want = Number(o.port || 0);
  if (!want) port = await listen(0);
  else {
    let lastErr;
    for (let p = want; p < want + 50; p++) {
      try { port = await listen(p); break; } catch (e) { lastErr = e; if (e.code !== 'EADDRINUSE') throw e; }
    }
    if (port === null) throw new Error(`no free port in ${want}-${want + 49} (${lastErr && lastErr.code})`);
  }

  let watcher = null;
  if (o.watch) {
    let timer = null, lastFile = '';
    const fire = async () => {
      if (o.onChange) { try { if (await o.onChange(lastFile)) return; } catch (e) { log(`onChange: ${e.message}`); } }
      const data = `event: reload\ndata: ${JSON.stringify({ file: lastFile })}\n\n`;
      for (const c of clients) { try { c.write(data); } catch { /* gone */ } }
      log(`changed: ${lastFile}`);
    };
    try {
      watcher = fs.watch(root, { recursive: true }, (ev, name) => {
        const n = String(name || '');
        if (!n || WATCH_IGNORE.test(n)) return;
        lastFile = n.replace(/\\/g, '/');
        clearTimeout(timer);
        timer = setTimeout(fire, 150);
      });
      watcher.on('error', () => {});
    } catch (e) {
      log(`live reload unavailable: ${e.message}`);
    }
  }
  const heartbeat = setInterval(() => { for (const c of clients) { try { c.write(': ping\n\n'); } catch { /* gone */ } } }, 20000);
  heartbeat.unref();

  return {
    url: `http://${host === '0.0.0.0' ? '127.0.0.1' : host}:${port}`,
    port, root,
    notify(file) { for (const c of clients) { try { c.write(`event: reload\ndata: ${JSON.stringify({ file })}\n\n`); } catch { /* gone */ } } },
    close() {
      clearInterval(heartbeat);
      if (watcher) watcher.close();
      for (const c of clients) { try { c.end(); } catch { /* gone */ } }
      return new Promise((r) => { server.closeAllConnections?.(); server.close(() => r()); });
    },
  };
}

// ------------------------------------------------------------------- CLI
const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const { parseCli, fail, resolveProject } = await import('./lib/cli.mjs');
  const args = parseCli({
    name: 'server',
    usage: 'showtime server <project> [--port 4800] [--watch]',
    summary: 'Serve a project folder for a browser (what render, check and preview use internally).',
    options: {
      port: { type: 'string', default: '4800', help: 'first port to try (default 4800; 0 = any free port)' },
      host: { type: 'string', default: '127.0.0.1', help: 'interface to bind (default 127.0.0.1, local only)' },
      watch: { type: 'boolean', help: 'send live-reload events to open preview players' },
      json: { type: 'boolean', help: 'print {url, port, root} as JSON' },
    },
    examples: ['showtime server my-video', 'showtime server my-video --port 0 --json'],
  });
  // a plain static site (no showtime.json) is captured with `site capture --serve`, not served as a project
  const target = path.resolve(args._[0] || '.');
  const tdir = fs.existsSync(target) && fs.statSync(target).isFile() ? path.dirname(target) : target;
  const notProject = fs.existsSync(tdir) && !fs.existsSync(path.join(tdir, 'showtime.json'));
  const siteHint = `to capture a static site use \`showtime site capture --serve ${args._[0] || '.'}\``;
  let proj;
  try { proj = resolveProject(args._[0] || '.'); } catch (e) {
    if (notProject) fail(`${e.message} (not a showtime project)`, siteHint);
    throw e;
  }
  if (notProject) console.error(`not a showtime project: ${siteHint}`);
  const srv = await startServer({ root: proj.dir, port: Number(args.port), host: args.host, watch: args.watch, log: (l) => console.error(l) }).catch((e) => fail(e.message));
  if (args.json) console.log(JSON.stringify({ url: srv.url, port: srv.port, root: srv.root, page: srv.url + '/' + proj.page }));
  else {
    console.log(`serving ${proj.dir}`);
    console.log(`  page:    ${srv.url}/${proj.page}`);
    console.log(`  preview: ${srv.url}/_st/preview?page=/${proj.page}`);
    console.log('press Ctrl+C to stop');
  }
  const stop = () => { srv.close().then(() => process.exit(0)); };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
}

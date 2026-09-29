// Loaded into every Node process a test file starts while run_all.py records which repository files that
// test file uses (run_all adds `--import <this file>` to NODE_OPTIONS and sets ST_TRACE_DIR / ST_TRACE_ROOT).
//
// Records each file under ST_TRACE_ROOT the process imports (a module resolve hook) or reads through `fs`
// (open, readFile, createReadStream: the files a server hands to the browser) and appends it at once to
// ST_TRACE_DIR/node-<pid>.txt, so a server that is killed still leaves what it used. Never prints, never
// throws: any problem only stops the recording.
import fs from 'node:fs';
import path from 'node:path';
import * as nodeModule from 'node:module';
import { fileURLToPath } from 'node:url';

const OUT = process.env.ST_TRACE_DIR;
const ROOT = process.env.ST_TRACE_ROOT;

if (OUT && ROOT) {
  try {
    const roots = [...new Set([path.resolve(ROOT), safeReal(ROOT)])].map((r) => norm(r.endsWith(path.sep) ? r : r + path.sep));
    const log = path.join(OUT, `node-${process.pid}.txt`);
    const append = fs.appendFileSync;
    const seen = new Set();
    const note = (p) => {
      try {
        if (p instanceof URL) p = p.protocol === 'file:' ? fileURLToPath(p) : null;
        else if (Buffer.isBuffer(p)) p = p.toString();
        if (typeof p !== 'string' || !p) return;
        if (p.startsWith('file:')) p = fileURLToPath(p);
        const a = path.resolve(p);
        if (seen.has(a)) return;
        seen.add(a);
        const n = norm(a);
        if (!roots.some((r) => n.startsWith(r))) return;
        append(log, a + '\n');
      } catch { /* recording must never break the test */ }
    };
    const wrap = (obj, name) => {
      const orig = obj && obj[name];
      if (typeof orig !== 'function') return;
      obj[name] = function (p, ...rest) { note(p); return orig.call(this, p, ...rest); };
    };
    fs.mkdirSync(OUT, { recursive: true });
    for (const n of ['openSync', 'open', 'readFileSync', 'readFile', 'createReadStream']) wrap(fs, n);
    for (const n of ['open', 'readFile']) wrap(fs.promises, n);
    if (typeof nodeModule.syncBuiltinESMExports === 'function') nodeModule.syncBuiltinESMExports();
    if (typeof nodeModule.register === 'function') {
      const hooks = `
        import fs from 'node:fs';
        import path from 'node:path';
        import { fileURLToPath } from 'node:url';
        let log = null, roots = [], seen = new Set();
        export async function initialize(data) { log = data.log; roots = data.roots; }
        export async function resolve(spec, ctx, next) {
          const r = await next(spec, ctx);
          try {
            if (log && r && typeof r.url === 'string' && r.url.startsWith('file:') && !seen.has(r.url)) {
              seen.add(r.url);
              const a = fileURLToPath(r.url);
              const n = process.platform === 'win32' ? a.toLowerCase() : a;
              if (roots.some((x) => n.startsWith(x))) fs.appendFileSync(log, a + '\\n');
            }
          } catch {}
          return r;
        }`;
      nodeModule.register('data:text/javascript,' + encodeURIComponent(hooks), { data: { log, roots } });
    }
  } catch { /* no recording */ }
}

function norm(p) { return process.platform === 'win32' ? p.toLowerCase() : p; }
function safeReal(p) { try { return fs.realpathSync(p); } catch { return path.resolve(p); } }

// Studio folder layout, job resolution (shared with render.mjs) and small file helpers (Node stdlib only).
//
//   showtime-out/<job>/studio/
//     brief.md  decisions.md          Claude's notes (current truth / append-only log)
//     board.json                      the board Claude authors (schema showtime.studio.board/1)
//     feedback.json                   reactions from the page (append-only events + derived state)
//     board.html                      static copy of the board (works from disk, no server)
//     media/                          CONTENT: everything the page may load (frames, thumbs, audio, animatic, fonts)
//     comps/                          style-frame compositions (HTML) rendered by `studio frame`
//     boards/                         board.json snapshot per revision (never overwritten)
//     exports/                        single-file exports for publishing
//     .state/                         STATE, never served: session (port + key), server-info, server-stopped, log, cursor
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';

export const MEDIA_DIRS = ['frames', 'thumbs', 'audio', 'animatic', 'fonts'];

export function readJSON(p, fallback = null) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return fallback; }
}

/** Atomic replace (tmp + rename). Retries cover Windows EPERM/EBUSY while a reader holds the file. */
export async function writeJSONAtomic(p, obj, { mode } = {}) {
  const tmp = `${p}.${process.pid}.${Date.now()}.${Math.random().toString(36).slice(2, 6)}.tmp`;
  await fsp.writeFile(tmp, JSON.stringify(obj, null, 2) + '\n', { encoding: 'utf8', ...(mode ? { mode } : {}) });
  for (let i = 0; ; i++) {
    try { await fsp.rename(tmp, p); return; } catch (e) {
      if (i >= 10 || !['EPERM', 'EBUSY', 'EACCES'].includes(e.code)) { await fsp.rm(tmp, { force: true }); throw e; }
      await new Promise((r) => setTimeout(r, 25 * (i + 1)));
    }
  }
}

export function writeJSONAtomicSync(p, obj, { mode } = {}) {
  const tmp = `${p}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(obj, null, 2) + '\n', { encoding: 'utf8', ...(mode ? { mode } : {}) });
  for (let i = 0; ; i++) {
    try { fs.renameSync(tmp, p); return; } catch (e) {
      if (i >= 10 || !['EPERM', 'EBUSY', 'EACCES'].includes(e.code)) { fs.rmSync(tmp, { force: true }); throw e; }
      const until = Date.now() + 25 * (i + 1); while (Date.now() < until) { /* short spin; sync path is only used at shutdown */ }
    }
  }
}

function outRoot() {
  let root = path.resolve(process.env.SHOWTIME_OUT || process.cwd());
  if (path.basename(root) !== 'showtime-out') root = path.join(root, 'showtime-out');
  return root;
}

// ------------------------------------------------------------------ job folders
// The same rules as the Python ledger (lib/st/job/ledger.py resolve()), so `showtime studio open launch`
// and `showtime status launch` always land in the same folder.

const JOB_NAME_RE = /^(.+?)-(\d{8}-\d{6})(?:-(\d+))?$/;

/** Folders that may hold showtime-out/: an explicit base, $SHOWTIME_OUT, the current folder. */
export function outRoots(base) {
  const roots = [];
  for (const c0 of [base, process.env.SHOWTIME_OUT, process.cwd()]) {
    if (!c0) continue;
    const c = path.resolve(c0);
    const r = path.basename(c) === 'showtime-out' ? c : path.join(c, 'showtime-out');
    if (isDir(r) && !roots.includes(r)) roots.push(r);
  }
  // run from inside a job (or deeper): the showtime-out/ folder above the current folder
  let d = process.cwd();
  for (let i = 0; i < 8; i++) {
    if (path.basename(d) === 'showtime-out') { if (!roots.includes(d)) roots.push(d); break; }
    const up = path.dirname(d);
    if (up === d) break;
    d = up;
  }
  return roots;
}

function isDir(p) { try { return fs.statSync(p).isDirectory(); } catch { return false; } }
function isFile(p) { try { return fs.statSync(p).isFile(); } catch { return false; } }
export function isJob(d) { return isDir(d) && (isFile(path.join(d, 'job.json')) || isFile(path.join(d, 'render.json'))); }

/** `launch-20260926-101500(-2)` -> `launch`. */
export function slugOf(name) { const m = JOB_NAME_RE.exec(name); return m ? m[1] : name; }

function mtimeOf(d) {
  let t = 0;
  for (const f of ['job.json', 'render.json', 'SHOWTIME.md']) { try { t = Math.max(t, fs.statSync(path.join(d, f)).mtimeMs); } catch { /* none */ } }
  if (!t) { try { t = fs.statSync(d).mtimeMs; } catch { /* gone */ } }
  return t;
}
/** Newest-created first: folder timestamp, then -N suffix, then mtime. */
function newestFirst(a, b) {
  const ka = JOB_NAME_RE.exec(path.basename(a)), kb = JOB_NAME_RE.exec(path.basename(b));
  const ta = ka ? ka[2] : '', tb = kb ? kb[2] : '';
  if (ta !== tb) return ta < tb ? 1 : -1;
  const na = ka ? Number(ka[3] || 1) : 0, nb = kb ? Number(kb[3] || 1) : 0;
  if (na !== nb) return nb - na;
  return mtimeOf(b) - mtimeOf(a);
}
function slugify(s) {
  return String(s).normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^A-Za-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '').toLowerCase().slice(0, 48).replace(/-+$/, '');
}

/** The job folder containing `p` (itself or up to `levels` parents; stops at showtime-out/), or null. */
export function enclosingJob(p, levels = 4) {
  let d = path.resolve(String(p));
  if (!isDir(d)) d = path.dirname(d);
  for (let i = 0; i <= levels; i++) {
    if (path.basename(d) === 'showtime-out') return null;
    if (isFile(path.join(d, 'job.json')) || (isFile(path.join(d, 'render.json')) && path.basename(path.dirname(d)) === 'showtime-out')) return d;
    const up = path.dirname(d);
    if (up === d) break;
    d = up;
  }
  return null;
}

function listDirs(r) {
  try { return fs.readdirSync(r, { withFileTypes: true }).filter((e) => e.isDirectory()).map((e) => path.join(r, e.name)); } catch { return []; }
}

/** Jobs matching a bare name, newest first: { hits, how: 'exact'|'slug'|'prefix'|'' }. */
export function findJobs(name, base) {
  const names = [String(name)];
  const sl = slugify(name);
  if (sl && sl !== names[0]) names.push(sl);
  const roots = outRoots(base);
  for (const n of names) for (const r of roots) {
    const d = path.join(r, n);
    if (isDir(d) && (isJob(d) || isDir(path.join(d, 'studio')))) return { hits: [d], how: 'exact' };
  }
  for (const n of names) {
    const hits = roots.flatMap(listDirs).filter((d) => isJob(d) && slugOf(path.basename(d)) === n);
    if (hits.length) return { hits: hits.sort(newestFirst), how: 'slug' };
  }
  for (const n of names) {
    const hits = roots.flatMap(listDirs).filter((d) => isJob(d) && path.basename(d).startsWith(n));
    if (hits.length) return { hits: hits.sort(newestFirst), how: 'prefix' };
  }
  return { hits: [], how: '' };
}

export class JobError extends Error {
  constructor(message, hint) { super(message); this.hint = hint; this.userError = true; }
}

/**
 * A <job> argument -> its folder, or null when a bare name matches nothing.
 *   existing folder (or a file/folder inside a job)  -> that job folder
 *   bare name/slug ("launch")                        -> newest showtime-out/launch-<timestamp>/
 *   prefix shared by several job names               -> JobError listing them
 */
export function resolveJobDir(arg, { base } = {}) {
  const raw = String(arg);
  const bare = !/[\\/]/.test(raw) && !raw.startsWith('.') && !raw.startsWith('~');
  const abs = path.resolve(raw);
  const byName = () => {
    const { hits, how } = findJobs(raw, base);
    if (!hits.length) return null;
    if (how === 'prefix') {
      const slugs = [...new Set(hits.map((h) => slugOf(path.basename(h))))].sort();
      if (slugs.length > 1) {
        const newest = slugs.map((sl) => path.basename(hits.find((h) => slugOf(path.basename(h)) === sl)));
        throw new JobError(`"${raw}" matches more than one job: ${newest.slice(0, 8).join(', ')}`, `pass the full name or the folder, e.g. ${hits[0]}`);
      }
    }
    return hits[0];
  };
  if (fs.existsSync(abs)) {
    if (isDir(abs) && isJob(abs)) return abs;
    if (bare && !enclosingJob(abs)) { const j = byName(); if (j) return j; }
    if (isDir(abs) && (path.basename(abs) === 'showtime-out' || isDir(path.join(abs, 'showtime-out')))) {
      const hits = outRoots(abs).flatMap(listDirs).filter(isJob).sort((x, y) => mtimeOf(y) - mtimeOf(x));
      if (hits.length) return hits[0];
    }
    const enc = enclosingJob(abs);
    if (enc) return enc;
    return abs; // a plain folder (e.g. a studio-only job from an older release): the caller decides
  }
  if (!bare) throw new JobError(`not found: ${abs}`, 'pass an existing job folder, or a job name (showtime job list)');
  return byName();
}

/**
 * Resolve a <job> argument to its studio folder.
 *   an existing folder            -> <job>/studio (a studio folder itself -> its job)
 *   a bare name ("launch-v2")     -> the newest showtime-out/launch-v2-<timestamp>/studio
 *   a name with no job yet        -> { found: false } with jobDir = showtime-out/<name> (studio init creates the job)
 * -> { jobDir, studioDir, job, found }
 */
export function resolveJob(arg) {
  if (!arg) return null;
  let dir = path.resolve(String(arg));
  let found = true;
  if (fs.existsSync(dir) && path.basename(dir) === 'studio' && (fs.existsSync(path.join(dir, 'board.json')) || fs.existsSync(path.join(dir, 'brief.md')))) {
    dir = path.dirname(dir);
  } else {
    const j = resolveJobDir(arg);
    if (j) dir = j;
    else { dir = path.join(outRoot(), slugify(arg) || String(arg)); found = false; }
  }
  const studioDir = path.join(dir, 'studio');
  return { jobDir: dir, studioDir, job: path.basename(dir), found };
}

export function layout(studioDir) {
  const s = path.resolve(studioDir);
  const state = path.join(s, '.state');
  return {
    studio: s,
    board: path.join(s, 'board.json'),
    feedback: path.join(s, 'feedback.json'),
    brief: path.join(s, 'brief.md'),
    decisions: path.join(s, 'decisions.md'),
    html: path.join(s, 'board.html'),
    media: path.join(s, 'media'),
    comps: path.join(s, 'comps'),
    boards: path.join(s, 'boards'),
    exports: path.join(s, 'exports'),
    state,
    session: path.join(state, 'session.json'),        // {port, token}: kept across restarts so open tabs reconnect
    serverInfo: path.join(state, 'server-info.json'), // present while a server runs
    serverStopped: path.join(state, 'server-stopped.json'),
    log: path.join(state, 'server.log'),
    cursor: path.join(state, 'feedback-cursor'),
  };
}

export function ensureStateDir(L) {
  fs.mkdirSync(L.state, { recursive: true });
  try { fs.chmodSync(L.state, 0o700); } catch { /* not supported (Windows) */ }
}

/** A path that does not exist yet: foo.jpg, foo-2.jpg, ... */
export function freshPath(p, taken = null) {
  const used = (q) => fs.existsSync(q) || (taken ? taken(q) : false);
  if (!used(p)) return p;
  const ext = path.extname(p), base = p.slice(0, p.length - ext.length);
  let n = 2;
  while (used(`${base}-${n}${ext}`)) n++;
  return `${base}-${n}${ext}`;
}

/** Forward-slash path of `abs` relative to `from` (for board.json). */
export function relPosix(from, abs) {
  return path.relative(from, abs).split(path.sep).join('/');
}

/**
 * Resolve a board media path ("media/frames/a.jpg") to a real file inside studio/media/.
 * Refuses dot segments, symlinks anywhere on the way, hard links and anything whose real path leaves media/.
 * -> { abs, stat } or { error }
 */
export function safeMediaFile(studioDir, rel, { mediaReal } = {}) {
  const segs = String(rel).split('?')[0].split('/');
  if (segs[0] !== 'media' || segs.length < 2) return { error: 'outside media/' };
  if (segs.some((s) => !s || s === '.' || s === '..' || s.startsWith('.') || s.includes('\\') || s.includes('\0') ||
    (process.platform === 'win32' && s.includes(':')))) return { error: 'bad path segment' };
  const mediaDir = path.join(studioDir, 'media');
  let real = mediaReal;
  try { if (!real) real = fs.realpathSync(mediaDir); } catch { return { error: 'no media folder' }; }
  let cur = mediaDir;
  for (const s of segs.slice(1)) {
    cur = path.join(cur, s);
    let st;
    try { st = fs.lstatSync(cur); } catch { return { error: 'not found' }; }
    if (st.isSymbolicLink()) return { error: 'symlink refused' };
  }
  let st;
  try { st = fs.statSync(cur); } catch { return { error: 'not found' }; }
  if (!st.isFile()) return { error: 'not a file' };
  if (st.nlink > 1) return { error: 'hard link refused' };
  let r;
  try { r = fs.realpathSync(cur); } catch { return { error: 'not found' }; }
  const inside = path.relative(real, r);
  if (!inside || inside.startsWith('..') || path.isAbsolute(inside)) return { error: 'outside media/' };
  return { abs: cur, stat: st };
}

export const MIME = {
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif',
  '.avif': 'image/avif', '.svg': 'image/svg+xml',
  '.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.aac': 'audio/aac', '.ogg': 'audio/ogg', '.opus': 'audio/ogg', '.flac': 'audio/flac',
  '.mp4': 'video/mp4', '.m4v': 'video/mp4', '.webm': 'video/webm',
  '.ttf': 'font/ttf', '.otf': 'font/otf', '.woff': 'font/woff', '.woff2': 'font/woff2',
  '.vtt': 'text/vtt; charset=utf-8',
};
export function mimeOf(p) { return MIME[path.extname(String(p).split('?')[0]).toLowerCase()] || null; }

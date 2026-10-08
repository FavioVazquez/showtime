// What a note points at: its spot or box resolved to the scene and the elements under it at its time, read
// from the project the video was rendered from, with the same headless page and audit code `showtime check`
// uses (scripts/lib/audit.mjs elementSnapshot). A note about a stretch of time gets the scenes it covers.
//
//   project       the video's render report (render.json beside it, or <stem>.work/render.json) names it; a
//                 video without one (footage, an edit, an imported clip) is a footage frame: time only
//   cache         <notes>/.state/where/<key>.json, one snapshot per frame, keyed on the project's files
//                 (path, size, mtime), its page, the frame size and the frame number
//   stale         a project file newer than the video: the elements are the project's as it is now
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { readJSON, writeJSONAtomic } from '../studio/paths.mjs';
import { layout, fmtT } from './notes.mjs';

const VIDEO = /\.(mp4|mov|webm|m4v|mkv)$/i;
const SKIP_DIRS = new Set(['node_modules', 'work', 'showtime-out', 'review', 'studio']);

/** The render report of a video file, when it names the video as its output. */
export function renderReport(video) {
  const dir = path.dirname(video), stem = path.basename(video).replace(/\.[^.]+$/, '');
  for (const rj of [path.join(dir, `${stem}.work`, 'render.json'), path.join(dir, 'render.json')]) {
    const r = readJSON(rj, null);
    if (r && r.output && path.basename(String(r.output)) === path.basename(video)) return r;
  }
  return null;
}

/** -> {dir, page, width, height, fps, duration} of the project the video was rendered from, or null (footage). */
export function projectFor(video) {
  if (!video) return null;
  const r = renderReport(video);
  if (!r || !r.project) return null;
  const dir = path.resolve(String(r.project)), page = String(r.page || 'index.html');
  if (!fs.existsSync(path.join(dir, page))) return null;
  return { dir, page, width: Number(r.width) || 0, height: Number(r.height) || 0, fps: Number(r.fps) || 0, duration: Number(r.duration) || 0 };
}

/** The project folder a video's render.json names when it is no longer there (moved or deleted), else null. */
export function missingProjectFor(video) {
  const r = video ? renderReport(video) : null;
  if (!r || !r.project) return null;
  const dir = path.resolve(String(r.project));
  return fs.existsSync(path.join(dir, String(r.page || 'index.html'))) ? null : dir;
}

/** A fingerprint of the project's files (path, size, mtime) and the newest of them (renders left out). */
export function projectSignature(dir) {
  const h = crypto.createHash('sha1');
  let n = 0, newest = 0, newestFile = null;
  (function walk(d, depth) {
    let ents;
    try { ents = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
    ents.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
    for (const e of ents) {
      if (n >= 5000 || e.name.startsWith('.')) continue;
      const p = path.join(d, e.name);
      if (e.isDirectory()) {
        if (depth < 5 && !SKIP_DIRS.has(e.name) && !e.name.endsWith('.work') && !e.name.endsWith('.review')) walk(p, depth + 1);
        continue;
      }
      if (!e.isFile() || /^render\.json$|\.log$/i.test(e.name)) continue;
      if (VIDEO.test(e.name) && /^(final|preview|draft|span-)/i.test(e.name)) continue;   // renders, not sources
      let st;
      try { st = fs.statSync(p); } catch { continue; }
      n++;
      h.update(`${path.relative(dir, p)}|${st.size}|${Math.round(st.mtimeMs)}\n`);
      if (st.mtimeMs > newest) { newest = st.mtimeMs; newestFile = path.relative(dir, p); }
    }
  })(dir, 0);
  return { sig: h.digest('hex').slice(0, 16), newest, newestFile };
}

// ------------------------------------------------------------------ resolving a region (pure, testable)
const area = (b) => Math.max(0, b.w) * Math.max(0, b.h);
function inter(a, b) {
  const x = Math.max(a.x, b.x), y = Math.max(a.y, b.y);
  const r = Math.min(a.x + a.w, b.x + b.w), btm = Math.min(a.y + a.h, b.y + b.h);
  return r > x && btm > y ? (r - x) * (btm - y) : 0;
}
function isAncestor(els, a, b) {   // a above b in the listed tree
  for (let p = b.parent; p >= 0 && els[p]; p = els[p].parent) if (p === a.i) return true;
  return false;
}
const pick = (e, extra = {}) => ({ selector: e.sel, kind: e.kind, tag: e.tag, component: e.comp || null, text: e.text || '',
  scene: e.scene || null, box: { x: e.x, y: e.y, w: e.w, h: e.h }, ...extra });

/**
 * The elements under a spot or a box of a snapshot (elementSnapshot). region in 0-1 frame units; null: none.
 * spot: what contains the point (within 1 % of the frame), the most specific first, ending with at most one
 * backdrop. box: what lies mostly inside it (half or more of the element), or the element the box sits inside;
 * a plain wrapper of something listed is left out. -> {elements: [...], more: n}
 */
export function resolveRegion(snap, region, { max = 8 } = {}) {
  if (!region || !snap) return { elements: [], more: 0 };
  const W = snap.width, H = snap.height, els = snap.elements || [];
  if (region.w === undefined) {
    const px = region.x * W, py = region.y * H, tol = 0.01 * Math.min(W, H);
    const hits = els.filter((e) => px >= e.x - tol && px <= e.x + e.w + tol && py >= e.y - tol && py <= e.y + e.h + tol);
    const fg = hits.filter((e) => e.kind !== 'backdrop').sort((a, b) => area(a) - area(b) || b.i - a.i);
    const bg = hits.filter((e) => e.kind === 'backdrop').sort((a, b) => area(a) - area(b) || b.i - a.i);
    const out = [...fg.slice(0, 4), ...bg.slice(0, 1)];
    return { elements: out.map((e) => pick(e)), more: Math.max(0, fg.length - 4) };
  }
  const box = { x: region.x * W, y: region.y * H, w: region.w * W, h: region.h * H };
  const scored = els.map((e) => {
    const i = inter(e, box);
    return { e, inside: area(e) > 0 ? i / area(e) : 0, fill: area(box) > 0 ? i / area(box) : 0 };
  }).filter((s) => s.inside > 0);
  let kept = scored.filter((s) => s.e.kind !== 'backdrop' && (s.inside >= 0.5 || s.fill >= 0.5));
  // a wrapper (a box with a fill) around something listed says less than what it holds; a component's own
  // parts (its number, its ring) are the component's: it is listed, they are not
  kept = kept.filter((s) => !(s.e.kind === 'shape' && kept.some((o) => o !== s && isAncestor(els, s.e, o.e))));
  kept = kept.filter((s) => !kept.some((o) => o !== s && o.e.kind === 'component' && isAncestor(els, o.e, s.e)));
  if (!kept.length) {
    // nothing mostly inside and no element under most of it: the smallest one holding the box's centre
    const cx = box.x + box.w / 2, cy = box.y + box.h / 2;
    const c = scored.filter((s) => cx >= s.e.x && cx <= s.e.x + s.e.w && cy >= s.e.y && cy <= s.e.y + s.e.h)
      .sort((a, b) => (a.e.kind === 'backdrop') - (b.e.kind === 'backdrop') || area(a.e) - area(b.e));
    kept = c.slice(0, 1);
  }
  const row = Math.max(1, 0.02 * H);
  kept.sort((a, b) => Math.round(a.e.y / row) - Math.round(b.e.y / row) || a.e.x - b.e.x);
  return { elements: kept.slice(0, max).map((s) => pick(s.e, { inside: Math.round(s.inside * 100) / 100 })), more: Math.max(0, kept.length - max) };
}

/** The top-level scenes a note is on: those on screen at its frame, or, for a stretch, every one it overlaps. */
export function scenesOf(snap, n, elements = []) {
  if (!snap) return [];
  const all = snap.scenes || [];
  const fmt = (s) => ({ id: s.id, name: s.name, start: s.start, end: s.end });
  if (n.to !== undefined && n.to !== null) {
    return all.filter((s) => s.start < n.to - 1e-6 && (s.end === null || s.end > n.t + 1e-6)).map((s) => ({
      ...fmt(s), covered: [Math.max(n.t, s.start), s.end === null ? n.to : Math.min(n.to, s.end)].map((x) => Math.round(x * 1000) / 1000),
    }));
  }
  const named = [...new Set(elements.map((e) => e.scene).filter(Boolean))];
  const on = all.filter((s) => s.on);
  const pickd = named.length ? all.filter((s) => named.includes(s.name)) : on;
  return (pickd.length ? pickd : on).map(fmt);
}

// ------------------------------------------------------------------ snapshots (browser, cached)
const SNAPSHOT_VERSION = 1;   // bump when elementSnapshot's output changes: older cached snapshots are not read
function cacheKey(proj, size, frame, fps, sig) {
  return crypto.createHash('sha1').update(JSON.stringify([SNAPSHOT_VERSION, proj.dir, proj.page, size, frame, fps, sig])).digest('hex').slice(0, 20);
}
function prune(dir, keep = 400) {
  try {
    const fsx = fs.readdirSync(dir).filter((f) => f.endsWith('.json')).map((f) => ({ f, m: fs.statSync(path.join(dir, f)).mtimeMs }));
    if (fsx.length <= keep) return;
    for (const x of fsx.sort((a, b) => a.m - b.m).slice(0, fsx.length - keep)) fs.rmSync(path.join(dir, x.f), { force: true });
  } catch { /* best effort */ }
}

/** One browser page per project, opened on the first snapshot that is not cached; close() ends them all. */
function sessions() {
  const open = new Map();
  let shared = null;
  async function get(proj) {
    if (open.has(proj.dir + '|' + proj.page)) return open.get(proj.dir + '|' + proj.page);
    const p = (async () => {
      const { resolveProject } = await import('../cli.mjs');
      const { startServer } = await import('../../server.mjs');
      const { openBrowser, openStage } = await import('../stagehost.mjs');
      const P = resolveProject(proj.dir, { page: proj.page });
      if (!shared) shared = openBrowser({ gpu: 'auto' });
      const b = await shared;
      const server = await startServer({ root: P.dir, port: 0 });
      try {
        let sess = await openStage(b.browser, { url: server.url, page: P.page, config: P.config });
        // a render at another aspect (render --size): open the page at the video's size
        const va = proj.width > 0 && proj.height > 0 ? proj.width / proj.height : 0;
        if (va && Math.abs(sess.info.width / sess.info.height - va) > 0.01) {
          await sess.close();
          sess = await openStage(b.browser, { url: server.url, page: P.page, config: P.config, size: `${proj.width}x${proj.height}` });
        }
        return { sess, server };
      } catch (e) { await server.close().catch(() => {}); throw e; }
    })();
    open.set(proj.dir + '|' + proj.page, p);
    return p;
  }
  async function close() {
    for (const p of open.values()) {
      try { const { sess, server } = await p; await sess.close(); await server.close().catch(() => {}); } catch { /* failed to open */ }
    }
    if (shared) { try { (await shared).browser.close().catch(() => {}); } catch { /* never opened */ } }
  }
  return { get, close };
}

/**
 * Resolve notes. notes: [note]; videoFor(note) -> the video file it was written on (or null).
 * -> Map id -> {kind: 'project'|'footage'|'unknown'|'error', ...}
 *   project: {project, page, frame, t, stale, scenes: [{id, name, start, end, covered?}], elements, more, size}
 *   footage: {t, to?, missing?} (no project: the time only; missing: the project folder render.json names, gone);
 *   unknown: no video file to look up; error: {error}
 */
export async function whereNotes(notesDir, notes, videoFor, { log = () => {} } = {}) {
  const L = layout(notesDir);
  const cacheDir = path.join(L.state, 'where');
  const out = new Map();
  const S = sessions();
  const sigs = new Map();
  try {
    for (const n of notes) {
      const video = videoFor(n);
      if (!video) { out.set(n.id, { kind: 'unknown', reason: 'no video file of this note to find its project' }); continue; }
      const proj = projectFor(video);
      if (!proj) {
        // a footage frame, or a render whose project was moved or deleted (then the time only, and where it was)
        const gone = missingProjectFor(video);
        out.set(n.id, { kind: 'footage', t: n.t, ...(n.to !== undefined ? { to: n.to } : {}), ...(gone ? { missing: gone } : {}) });
        continue;
      }
      if (!sigs.has(proj.dir)) sigs.set(proj.dir, projectSignature(proj.dir));
      const sig = sigs.get(proj.dir);
      const fps = proj.fps || 30;
      const frame = Math.floor(n.t * fps + 1e-4);
      const size = proj.width && proj.height ? `${proj.width}x${proj.height}` : null;
      const file = path.join(cacheDir, `${cacheKey(proj, size, frame, fps, sig.sig)}.json`);
      let snap = readJSON(file, null);
      if (!snap || !Array.isArray(snap.elements)) {
        try {
          const { sess } = await S.get(proj);
          const { elementSnapshot } = await import('../audit.mjs');
          await sess.seek(frame / fps);
          snap = await sess.page.evaluate(elementSnapshot, { width: sess.info.width, height: sess.info.height, t: frame / fps, duration: sess.info.duration });
          fs.mkdirSync(cacheDir, { recursive: true });
          await writeJSONAtomic(file, snap);
          prune(cacheDir);
        } catch (e) {
          const msg = String(e && e.message || e).split('\n')[0];
          log(`could not open ${proj.dir} to see what note ${n.id} points at: ${msg}`);
          out.set(n.id, { kind: 'error', project: proj.dir, error: msg });
          continue;
        }
      }
      const r = resolveRegion(snap, n.region);
      let vm = 0;
      try { vm = fs.statSync(video).mtimeMs; } catch { /* gone */ }
      out.set(n.id, {
        kind: 'project', project: proj.dir, page: proj.page, frame, t: Math.round((frame / fps) * 1000) / 1000, size: { width: snap.width, height: snap.height },
        stale: vm > 0 && sig.newest > vm + 1000 ? sig.newestFile : null,
        scenes: scenesOf(snap, n, r.elements), elements: r.elements, more: r.more,
      });
    }
  } finally { await S.close(); }
  return out;
}

// ------------------------------------------------------------------ text
const q = (s, n = 60) => { const x = String(s || ''); return JSON.stringify(x.length > n ? x.slice(0, n - 1) + '…' : x); };
export function sceneText(s) {
  const span = `${fmtT(s.start)}-${s.end === null || s.end === undefined ? 'end' : fmtT(s.end)}`;
  return s.covered ? `${s.name} (${span}; the note covers ${fmtT(s.covered[0])}-${fmtT(s.covered[1])})` : `${s.name} (${span})`;
}
export function elementText(e) {
  const b = e.box;
  return [e.selector, e.component && !e.selector.includes(`data-st="${e.component}"`) ? `[data-st=${e.component}]` : null,
    e.text ? q(e.text) : null, `${e.kind}${e.inside !== undefined && e.inside < 0.99 ? `, ${Math.round(e.inside * 100)}% inside` : ''}`,
    `${b.w}x${b.h} at ${b.x},${b.y}`].filter(Boolean).join('  ');
}
/** Lines for `review notes` (no indentation). */
export function whereLines(w, n) {
  if (!w) return [];
  if (w.kind === 'footage') {
    const when = n.to !== undefined ? `from ${fmtT(n.t)} to ${fmtT(n.to)}` : `at ${fmtT(n.t)}`;
    if (w.missing) return [`on screen: project not found at ${w.missing} (moved or deleted since this render), ${when}`];
    return [`on screen: footage frame (no project), ${when}`];
  }
  if (w.kind === 'unknown') return [`on screen: unknown (${w.reason})`];
  if (w.kind === 'error') return [`on screen: could not be read (${w.error})`];
  const L = [];
  const range = n.to !== undefined && n.to !== null;
  if (w.scenes.length) L.push(`${range ? 'scenes' : w.scenes.length > 1 ? 'scenes (a transition)' : 'scene'}: ${w.scenes.map(sceneText).join(', ')}`);
  else L.push('scene: none found (no top-level clips with data-start)');
  if (n.region) {
    if (!w.elements.length) L.push('under it: nothing but the background');
    w.elements.forEach((e, i) => L.push(`${i ? '          ' : 'under it: '}${elementText(e)}`));
    if (w.more) L.push(`          ... and ${w.more} more`);
  }
  if (w.stale) L.push(`(the project changed after this render, ${w.stale} among others: these are its elements as it is now)`);
  return L;
}

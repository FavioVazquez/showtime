// Tutorial series: one shared kit (the series root's kit.js: chrome, sound motif, product UI and its
// named hit-rects) used by several episode projects. Each episode is a normal project (render,
// preview, export, retime all work on it) holding a synced copy of the kit; `showtime series sync`
// refreshes the copies and `showtime export` warns when an episode's copy is stale.
import fs from 'node:fs';
import path from 'node:path';

export const BANNER = '/* Synced copy of the series kit (../kit.js) by `showtime series sync`. Edit the series kit, not this file. */\n';

/** The series a folder is (or an episode folder belongs to), or null. -> {root, cfg, kitPath} */
export function findSeries(dir) {
  for (const d of [dir, path.dirname(dir)]) {
    const f = path.join(d, 'series.json');
    if (fs.existsSync(f)) {
      let cfg = {};
      try { cfg = JSON.parse(fs.readFileSync(f, 'utf8')) || {}; } catch (e) { throw new Error(`${f} is not valid JSON: ${e.message}`); }
      return { root: d, cfg, kitPath: path.join(d, cfg.kit || 'kit.js') };
    }
  }
  return null;
}

/** Episode folders: the ones series.json lists, then any other subfolder with a showtime.json that loads kit.js. */
export function episodes(series) {
  const out = [];
  const seen = new Set();
  const add = (name) => {
    const d = path.join(series.root, name);
    if (seen.has(d) || !fs.existsSync(path.join(d, 'showtime.json'))) return;
    seen.add(d);
    out.push(d);
  };
  for (const e of series.cfg.episodes || []) add(String(e));
  for (const e of fs.readdirSync(series.root, { withFileTypes: true })) {
    if (!e.isDirectory() || e.name.startsWith('.') || /^(showtime-out|work|node_modules)$/.test(e.name)) continue;
    const idx = path.join(series.root, e.name, 'index.html');
    if (fs.existsSync(idx) && /src=["']kit\.js["']/.test(fs.readFileSync(idx, 'utf8'))) add(e.name);
  }
  return out;
}

/** A path as a user would type it from here: relative when below the current folder, else absolute. */
export function shown(p) { const r = path.relative(process.cwd(), p); return !r ? '.' : r.startsWith('..') || path.isAbsolute(r) ? p : r; }

const strip = (t) => (t.startsWith(BANNER) ? t.slice(BANNER.length) : t).replace(/\r\n/g, '\n');

/** State of one episode's kit copy: 'ok' | 'stale' | 'missing' | 'nokit' (the series has no kit). */
export function kitState(series, epDir) {
  if (!fs.existsSync(series.kitPath)) return 'nokit';
  const copy = path.join(epDir, path.basename(series.kitPath));
  if (!fs.existsSync(copy)) return 'missing';
  return strip(fs.readFileSync(copy, 'utf8')) === strip(fs.readFileSync(series.kitPath, 'utf8')) ? 'ok' : 'stale';
}

/** Copy the series kit into an episode. -> true when the file changed */
export function syncKit(series, epDir) {
  const kit = strip(fs.readFileSync(series.kitPath, 'utf8'));
  const dst = path.join(epDir, path.basename(series.kitPath));
  const want = BANNER + kit;
  if (fs.existsSync(dst) && fs.readFileSync(dst, 'utf8') === want) return false;
  fs.writeFileSync(dst, want);
  return true;
}

/** Warning text when a project is an episode whose kit copy differs from its series kit, else null. */
export function staleKitWarning(projDir) {
  let s;
  try { s = findSeries(projDir); } catch { return null; }
  if (!s || s.root === projDir) return null;
  const st = kitState(s, projDir);
  if (st === 'stale') return `this episode's kit.js differs from the series kit (${path.relative(projDir, s.kitPath)}): run \`showtime series sync ${shown(s.root)}\` first, or the export shows the old kit`;
  if (st === 'missing') return `this episode has no kit.js: run \`showtime series sync ${shown(s.root)}\``;
  return null;
}

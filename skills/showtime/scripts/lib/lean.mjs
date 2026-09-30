// Lean mode helpers shared by check, look and render: the look budget and "was this checked since the last edit?".
import fs from 'node:fs';
import path from 'node:path';
import { workName } from './cli.mjs';

export const LOOK_BUDGET = 12;        // images per job in the agent's own context

/** Newest modification time of a project's own sources (work/, out/, node_modules and videos are not sources). */
export function sourcesMtime(dir, { limit = 4000 } = {}) {
  let newest = 0, newestFile = null, seen = 0;
  const SKIP = new Set(['work', 'node_modules', '.git', 'out', 'showtime-out']);
  const walk = (d, depth) => {
    let ents = [];
    try { ents = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
    for (const e of ents) {
      if (seen >= limit) return;
      const p = path.join(d, e.name);
      if (e.isDirectory()) { if (!SKIP.has(e.name) && !e.name.startsWith('.') && depth < 6) walk(p, depth + 1); continue; }
      if (!/\.(html?|css|m?js|json|svg|md)$/i.test(e.name)) continue;
      seen++;
      try { const m = fs.statSync(p).mtimeMs; if (m > newest) { newest = m; newestFile = p; } } catch { /* gone */ }
    }
  };
  walk(dir, 0);
  return { mtime: newest, file: newestFile };
}

/**
 * Is there a `showtime check` report newer than the project's sources (for this page and size)?
 * -> { state: 'fresh' | 'stale' | 'none', report, changed, minutes }
 */
export function checkFreshness(projDir, page, size) {
  const report = path.join(projDir, 'work', workName('check', page, size), 'report.json');
  let rm = 0;
  try { rm = fs.statSync(report).mtimeMs; } catch { return { state: 'none', report }; }
  const src = sourcesMtime(projDir);
  if (src.mtime > rm + 1000) {
    return { state: 'stale', report, changed: src.file, minutes: Math.max(0, Math.round((src.mtime - rm) / 60000)) };
  }
  return { state: 'fresh', report };
}

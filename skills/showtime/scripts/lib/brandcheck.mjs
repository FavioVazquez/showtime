// Brand first (launch, promo, trailer, teaser, release projects): is the film in the product's look, and when
// there is no brand kit, has the job said why? Used by `showtime check`; the pure part (brandVerdict) is tested.
import fs from 'node:fs';
import path from 'node:path';

export const BRAND_KINDS = ['launch', 'promo', 'trailer', 'teaser', 'release'];

const readJson = (p) => { try { return JSON.parse(fs.readFileSync(p, 'utf8').replace(/^﻿/, '')); } catch { return null; } };

/** brand.json as `showtime` finds it: $SHOWTIME_BRAND, then the project, its brand/ folder and up to 4
 *  parents (stopping at a repository root). */
export function findBrand(projectDir, env = process.env) {
  if (env.SHOWTIME_BRAND) {
    let p = env.SHOWTIME_BRAND;
    try { if (fs.statSync(p).isDirectory()) p = path.join(p, 'brand.json'); } catch { return null; }
    return fs.existsSync(p) ? p : null;
  }
  let d = path.resolve(projectDir);
  for (let i = 0; i <= 4; i++) {
    for (const c of [path.join(d, 'brand.json'), path.join(d, 'brand', 'brand.json')]) if (fs.existsSync(c)) return c;
    if (fs.existsSync(path.join(d, '.git'))) break;
    const up = path.dirname(d);
    if (up === d) break;
    d = up;
  }
  return null;
}

/** The job folder holding the project (job.json within 4 levels up, never past showtime-out/). */
export function findJob(projectDir) {
  let d = path.resolve(projectDir);
  for (let i = 0; i <= 4; i++) {
    if (path.basename(d) === 'showtime-out') return null;
    if (fs.existsSync(path.join(d, 'job.json'))) return d;
    const up = path.dirname(d);
    if (up === d) break;
    d = up;
  }
  return null;
}

export function palette(kit) {
  const out = {};
  for (const c of (kit && kit.colors) || []) if (c && c.role && c.hex && c.role !== 'other' && !(c.role in out)) out[c.role] = String(c.hex).toLowerCase();
  for (const [k, v] of Object.entries((kit && kit.palette) || {})) if (typeof v === 'string' && k !== 'other') out[k] = v.toLowerCase();
  return out;
}

const rgbOf = (hex) => { const h = String(hex || '').replace('#', ''); if (!/^[0-9a-f]{6}$/i.test(h)) return null; return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)); };
const dist = (a, b) => { const x = rgbOf(a), y = rgbOf(b); return x && y ? Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]) : Infinity; };

/** Findings from what was found: {kind, kit, kitFile, job, jobBrand, page: {accent, bg}} -> [{severity, code, message, fix}]. */
export function brandVerdict({ kind, kit, kitFile, job, jobBrand, page }) {
  if (!BRAND_KINDS.includes(String(kind || '').toLowerCase())) return [];
  const out = [];
  if (!kit) {
    if (jobBrand && jobBrand.none) {
      out.push({ severity: 'info', code: 'brand_none', message: `no brand kit, as the job records: "${jobBrand.none}"` });
    } else if (job) {
      out.push({ severity: 'warning', code: 'brand_missing',
        message: 'a launch film without a brand kit, and the job does not say why: it will look like the template, not the product',
        fix: `capture the product first: showtime brand capture <repo|url> --job ${path.basename(job)} (then showtime brand apply <project>); or record why not: showtime brand skip ${path.basename(job)} --why "..."` });
    } else {
      out.push({ severity: 'info', code: 'brand_missing', message: 'no brand kit found for this launch film (the template look is used)',
        fix: 'showtime brand capture <repo|url> -o <folder above the project>/brand, then showtime brand apply <project>' });
    }
    return out;
  }
  const pal = palette(kit);
  const brandColors = Object.values(pal);
  const near = (c) => c && brandColors.some((b) => dist(c, b) < 40);
  const name = kit.name || 'the brand';
  const off = [];
  if (page && page.bg && pal.bg && !near(page.bg)) off.push(`ground ${page.bg} (brand bg ${pal.bg})`);
  if (page && page.accent && (pal.accent || pal.accent2) && !near(page.accent)) off.push(`accent ${page.accent} (brand accent ${pal.accent || pal.accent2})`);
  if (off.length && !(page && page.applied)) {
    out.push({ severity: 'warning', code: 'brand_not_applied',
      message: `${name} has a brand kit (${path.basename(path.dirname(kitFile || ''))}/${path.basename(kitFile || 'brand.json')}) but the page uses ${off.join(' and ')}: a generic look`,
      fix: 'showtime brand apply <project> (or set --bg/--accent from brand.json by hand; the user\'s words still win: say why in the plan if they asked for another look)' });
  } else {
    out.push({ severity: 'info', code: 'brand', message: `in ${name}'s look (${kitFile ? path.relative(process.cwd(), kitFile) || kitFile : 'brand.json'}${kit.status === 'draft' ? ', draft' : ''}): ground ${page && page.bg || pal.bg}, accent ${page && page.accent || pal.accent}` });
  }
  return out;
}

/** Everything for check: finds the kit and the job, reads the page's resolved tokens. */
export async function brandFindings({ projectDir, config, page }) {
  const kind = String((config && config.kind) || '').toLowerCase();
  if (!BRAND_KINDS.includes(kind)) return [];
  const kitFile = findBrand(projectDir);
  const kit = kitFile ? readJson(kitFile) : null;
  const job = findJob(projectDir);
  const jobData = job ? readJson(path.join(job, 'job.json')) : null;
  let tokens = null;
  if (kit && page) {
    tokens = await page.evaluate(() => {
      const cv = document.createElement('canvas'); cv.width = cv.height = 1;
      const cx = cv.getContext('2d', { willReadFrequently: true });
      const hex = (c) => {
        if (!c) return null;
        const probe = document.createElement('i'); probe.style.color = c; document.body.appendChild(probe);
        const rgb = getComputedStyle(probe).color; probe.remove();
        cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = rgb; cx.fillRect(0, 0, 1, 1);
        const d = cx.getImageData(0, 0, 1, 1).data;
        return d[3] < 128 ? null : '#' + [d[0], d[1], d[2]].map((x) => x.toString(16).padStart(2, '0')).join('');
      };
      const cs = getComputedStyle(document.documentElement);
      return { accent: hex(cs.getPropertyValue('--accent').trim()), bg: hex(cs.getPropertyValue('--bg').trim()), applied: !!document.getElementById('st-brand') };
    }).catch(() => null);
  }
  return brandVerdict({ kind, kit, kitFile, job, jobBrand: jobData && jobData.brand, page: tokens });
}

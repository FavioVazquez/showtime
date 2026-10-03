// Icon packages on demand: /_lib/<icon package>/<file> without installing the packages.
//
// The icon sets (lucide-static, @tabler/icons, @phosphor-icons/core, simple-icons, heroicons) are no
// longer part of the Node install (~175 MB on disk). A page that asks for /_lib/lucide-static/icons/zap.svg
// gets the file from ~/.showtime/cache/icons/<package>@<version>/ (the same cache `showtime assets icon`
// fills), fetched once from jsDelivr at the version pinned in setup/manifest.json ("icon_packs").
// An older install that still has the package in node_modules is served from there by the caller.
//
//   import { iconFile, iconPackageDir, isIconPackage } from './lib/iconcache.mjs';
//   const f = await iconFile('lucide-static/icons/zap.svg');   // absolute path, or null
import fs from 'node:fs';
import path from 'node:path';
import { showtimeHome, skillDir } from './deps.mjs';

const CDN = 'https://cdn.jsdelivr.net/npm';
let pins = null;

function versions() {
  if (pins) return pins;
  pins = {};
  try {
    const man = JSON.parse(fs.readFileSync(path.join(skillDir(), 'setup', 'manifest.json'), 'utf8'));
    for (const p of man.icon_packs || []) pins[p.package] = p.version;
  } catch { /* no manifest: nothing is an icon package */ }
  return pins;
}

const offline = () => !['', '0', 'false', 'no'].includes(String(process.env.SHOWTIME_OFFLINE || '').toLowerCase());

export function isIconPackage(pkg) { return Object.prototype.hasOwnProperty.call(versions(), pkg); }

/** ~/.showtime/cache/icons/<package>@<version> (the scoped package's "/" becomes "+"). */
export function iconPackageDir(pkg) {
  const v = versions()[pkg];
  return v ? path.join(showtimeHome(), 'cache', 'icons', `${pkg.replace('/', '+')}@${v}`) : null;
}

async function download(url, dest) {
  const res = await fetch(url, { headers: { 'User-Agent': 'showtime-icons' } });
  if (!res.ok) return false;
  const buf = Buffer.from(await res.arrayBuffer());
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  const tmp = `${dest}.${process.pid}-${Math.random().toString(36).slice(2, 8)}.part`;
  fs.writeFileSync(tmp, buf);
  fs.renameSync(tmp, dest);
  return true;
}

/** Absolute path of an icon package file, fetching it (and the package.json, for notices) on first use. */
export async function iconFile(libPath) {
  const m = /^((?:@[^/]+\/)?[^/]+)\/(.+)$/.exec(String(libPath || ''));
  if (!m || !isIconPackage(m[1])) return null;
  const [, pkg, rel] = m;
  if (rel.split('/').some((s) => s === '..' || s === '') || !/^[\w@+./-]+$/.test(rel)) return null;
  const dir = iconPackageDir(pkg);
  const file = path.join(dir, ...rel.split('/'));
  if (fs.existsSync(file)) return file;
  if (offline()) return null;
  // a package name and a pinned version from setup/manifest.json, nothing else, before they go into the CDN URL
  const ver = versions()[pkg];
  if (!/^[\w.+-]+$/.test(String(ver)) || !/^(?:@[\w.-]+\/)?[\w.-]+$/.test(pkg)) return null;
  const base = `${CDN}/${pkg}@${ver}`;
  try {
    if (!(await download(`${base}/${rel}`, file))) return null;
    const pj = path.join(dir, 'package.json');
    if (!fs.existsSync(pj)) await download(`${base}/package.json`, pj).catch(() => false);
    return file;
  } catch {
    return null;
  }
}

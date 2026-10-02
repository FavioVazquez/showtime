// Shared symlink-escape guard for the static file servers (server.mjs, lib/capture.mjs).
//
// A path can pass a purely lexical containment check (no "..", no absolute path) and still point
// outside the served root when one of its segments is a symlink: `ln -s /etc/passwd project/evil`
// makes `/evil` resolve lexically under `project/`, but the real file it reads is not. fs.realpathSync
// follows every symlink on the way, so comparing real paths catches that a plain string comparison
// cannot.
import fs from 'node:fs';
import path from 'node:path';

/**
 * True when `abs`'s real (symlink-resolved) path is under `root`'s real path.
 * A path that does not exist (ENOENT, or any other lookup error) passes here -- there is nothing to
 * escape yet, and the caller's own 404 (file not found) handles it instead of a misleading 403.
 */
export function realpathUnderRoot(root, abs) {
  let realAbs;
  try { realAbs = fs.realpathSync(abs); } catch { return true; }
  let realRoot;
  try { realRoot = fs.realpathSync(path.resolve(root)); } catch { return true; }
  const rel = path.relative(realRoot, realAbs);
  return !(rel.startsWith('..') || path.isAbsolute(rel));
}

/** The 403 body for a path that resolves outside the served root through a symlink: says what to do. */
export function symlinkRefusal(name) {
  return `forbidden path: ${name} is a symlink to something outside the project folder, and showtime does ` +
    'not serve files from outside it (a security rule). Copy the file into the project instead.\n';
}

/** True when `rel` stays inside `root` as text but a symlink on the way leads outside it. */
export function escapesBySymlink(root, rel) {
  const parts = String(rel).replace(/\\/g, '/').split('/').filter((s) => s && s !== '.');
  if (parts.some((s) => s === '..' || s.includes('\0'))) return false;
  const abs = path.resolve(root, ...parts);
  const r = path.relative(path.resolve(root), abs);
  if (r.startsWith('..') || path.isAbsolute(r)) return false;
  return !realpathUnderRoot(root, abs);
}

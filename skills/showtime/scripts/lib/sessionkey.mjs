// Per-session keys for showtime's local servers (studio boards, preview player, `showtime server`).
//
// A server bound to 127.0.0.1 is still reachable by every web page open in the user's browser: a
// page on any site can ask http://127.0.0.1:<port>/... for project files. The key closes that door.
// The printed link carries it once (`?k=<key>`); the server trades it for an HttpOnly SameSite=Strict
// cookie named per port (cookies are shared across ports of one host), and every other request must
// carry that cookie, the `?k=` parameter or a header (CLI and tests). Keys are compared in constant time.
import crypto from 'node:crypto';

/** A fresh random key: 64 hex characters (256 bits). */
export function newKey() {
  return crypto.randomBytes(32).toString('hex');
}

/** Does this look like a key we issued? */
export function isKey(s) {
  return typeof s === 'string' && /^[0-9a-f]{64}$/.test(s);
}

/** Constant-time comparison of two keys (false for anything empty or not a string). */
export function sameKey(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || !a || !b) return false;
  const ha = crypto.createHash('sha256').update(a).digest();
  const hb = crypto.createHash('sha256').update(b).digest();
  return crypto.timingSafeEqual(ha, hb) && a.length === b.length;
}

/** The key carried by a request's cookie `name`, or null. */
export function cookieKey(req, name) {
  const m = new RegExp(`(?:^|;\\s*)${name}=([0-9a-f]{64})(?:;|$)`).exec(req.headers.cookie || '');
  return m ? m[1] : null;
}

/** The Set-Cookie value that stores `key` for this server (session cookie, never sent cross-site). */
export function keyCookie(name, key) {
  return `${name}=${key}; Path=/; HttpOnly; SameSite=Strict`;
}

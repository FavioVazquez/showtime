// Link previews of an exported HTML video (og: and twitter: tags), and the warnings about names
// that show in them: a default title, chapters named after scene ids.
import fs from 'node:fs';
import path from 'node:path';

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const isUrl = (s) => /^https?:\/\/[^\s/]+/i.test(String(s || ''));

/** The base a relative image path is resolved against: the page's folder. */
function pageBase(url) {
  const u = new URL(url);
  if (!u.pathname.endsWith('/') && !/\.html?$/i.test(u.pathname)) u.pathname += '/';
  return u.href;
}

/**
 * Where the share tags come from: --share-url / --share-image, else showtime.json "share": {url, image,
 * description}. Without an image the poster frame is used: with --folder it is written as
 * assets/poster.jpg; a single file with a share URL gets it beside the file (<name>.share.jpg).
 * Relative image paths become absolute when the page's URL is known (most link previews need that).
 * @param o.flags   {url, image} from the command line
 * @param o.cfg     showtime.json
 * @param o.folder  folder export
 * @param o.out     output (.html file, or the folder)
 * @param o.dirs    folders a local image path is looked up in (project, cwd)
 * @param o.poster  JPEG Buffer of the poster frame, or null
 * @param o.width, o.height  the frame size (the poster's size)
 * @param o.fresh   (path) -> a path that does not exist yet (exports never overwrite)
 * -> { url, description, image: {href, width?, height?} | null, card, files: [{rel, bytes}] (folder),
 *      beside: {file, bytes} | null (single file), notes: [string], warnings: [string] }
 * Throws Error(.user = true) for a share URL that is not http(s).
 */
export function resolveShare(o) {
  const sh = o.cfg && o.cfg.share && typeof o.cfg.share === 'object' ? o.cfg.share : {};
  const flags = o.flags || {};
  const warnings = [], notes = [], files = [];
  let beside = null;
  const url = flags.url !== undefined ? String(flags.url).trim() : (sh.url ? String(sh.url).trim() : '');
  if (url && !isUrl(url)) throw Object.assign(new Error(`the share URL must start with https:// or http:// (got ${url})`), { user: true });
  const description = sh.description ? String(sh.description).trim() : (o.cfg && o.cfg.subtitle ? String(o.cfg.subtitle).trim() : '');
  const spec = flags.image !== undefined ? String(flags.image).trim() : (sh.image ? String(sh.image).trim() : '');
  let image = null;
  if (spec) {
    if (isUrl(spec)) image = { href: spec };
    else {
      const local = (o.dirs || []).map((d) => path.resolve(d, spec)).find((f) => { try { return fs.statSync(f).isFile(); } catch { return false; } });
      if (local && o.folder) {
        const rel = `assets/share${path.extname(local).toLowerCase() || '.jpg'}`;
        files.push({ rel, bytes: fs.readFileSync(local) });
        image = { href: rel };
      } else {
        if (local) warnings.push(`share image ${spec} is a local file: a single-file export cannot carry it; host it and give its URL, or use --folder (which copies it)`);
        image = { href: spec };
      }
    }
  } else if (o.poster && o.folder) {
    files.push({ rel: 'assets/poster.jpg', bytes: o.poster });
    image = { href: 'assets/poster.jpg', width: o.width, height: o.height };
  } else if (o.poster && url) {
    const file = (o.fresh || ((f) => f))(path.join(path.dirname(o.out), path.basename(o.out).replace(/\.html?$/i, '') + '.share.jpg'));
    beside = { file, bytes: o.poster };
    image = { href: path.basename(file), width: o.width, height: o.height };
    notes.push(`share image: the poster frame, ${path.basename(file)} beside the page (host it with the page)`);
  }
  if (image && !isUrl(image.href)) {
    if (url) image.href = new URL(image.href, pageBase(url)).href;
    else notes.push(`share image ${image.href} is a relative path; most link previews need an absolute https URL: give --share-url (or showtime.json "share": {"url"}) and it is made absolute`);
  }
  return { url, description, image, card: image ? 'summary_large_image' : 'summary', files, beside, notes, warnings };
}

/** The <meta> tags of a link preview. */
export function shareMeta({ title, description, url, image, card }) {
  const m = (k, v, attr = 'property') => `<meta ${attr}="${k}" content="${esc(v)}">`;
  const out = [m('og:type', 'website'), m('og:title', title)];
  if (description) out.push(m('og:description', description));
  if (url) out.push(m('og:url', url));
  if (image) {
    out.push(m('og:image', image.href));
    if (image.width && image.height) out.push(m('og:image:width', String(image.width)), m('og:image:height', String(image.height)));
    out.push(m('og:image:alt', title));
  }
  out.push(m('twitter:card', card || (image ? 'summary_large_image' : 'summary'), 'name'));
  return out.join('\n');
}

/** A title that is a default (the folder name "project", a template's name): it shows in link previews. */
export function genericTitle(title) {
  return /^\s*(project|untitled|video|my[ -]?video|new[ -]?project|film|.*\btemplate)\s*$/i.test(String(title || ''));
}

/** Chapters that fell back to scene ids ("Shot 1", "Scene 2", "S 3" or no name): at least half of 2+. */
export function genericChapters(chapters) {
  const list = chapters || [];
  if (list.length < 2) return false;
  const n = list.filter((c) => /^\s*((shot|scene|clip|part|section|slide|s)\s*\d+[a-z]?)?\s*$/i.test(String(c.label || ''))).length;
  return n * 2 >= list.length;
}

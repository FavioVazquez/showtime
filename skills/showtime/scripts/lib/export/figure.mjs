// `showtime export html <project> --interactive`: a living diagram's live figure (figure.html) as one offline file.
//
// No player and no virtual clock: the page runs its own (runtime/figure.js). Every stylesheet and script the page
// links is inlined, fonts become data: URLs (faces for scripts no text uses are dropped), and a
// Content-Security-Policy blocks any network request. A project without a figure.html uses the diagram template's.
import fs from 'node:fs';
import path from 'node:path';
import { skillDir, nodeModulesDir } from '../deps.mjs';
import { UserError } from '../cli.mjs';
import { addCodePoints, pruneFontFaces } from './collect.mjs';
import { minifyJs, minifyCss } from './minify.mjs';
import { notices } from './build.mjs';

export const FIGURE_CSP = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; font-src data:; img-src data: blob:; media-src data: blob:";
const FONT_MIME = { '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf', '.otf': 'font/otf' };
const IMG_MIME = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.svg': 'image/svg+xml', '.webp': 'image/webp', '.gif': 'image/gif' };

// the diagram template's showtime.json title: a project still named that takes its scene's title
export const TEMPLATE_TITLE = 'Living Diagram';

/**
 * The scene's own words: {title, description} from SCENE.interactive (title, sub), else SCENE.page (title without
 * its *accent* marks, dek), read as string literals from scene.js. Nothing in the project is run here: project code
 * only ever runs inside the browser.
 */
/**
 * The string-valued keys of the first `block: { ... }` object literal in a script, its own keys only (not those of
 * nested objects), skipping comments and strings: {key: raw text}. A value that is not a plain string literal is
 * left out. Nothing is run.
 */
export function blockLiterals(src, block) {
  const n = src.length;
  let i = 0;
  const str = (q) => { let j = i + 1, raw = ''; while (j < n && src[j] !== q) { if (src[j] === '\\') { raw += src.slice(j, j + 2); j += 2; continue; } if (q !== '`' && src[j] === '\n') break; raw += src[j]; j++; } return { end: j + 1, raw }; };
  const comment = () => {
    if (src[i] === '/' && src[i + 1] === '/') { const e = src.indexOf('\n', i); i = e < 0 ? n : e; return true; }
    if (src[i] === '/' && src[i + 1] === '*') { const e = src.indexOf('*/', i + 2); i = e < 0 ? n : e + 2; return true; }
    return false;
  };
  const readObject = () => {
    const out = {}; let depth = 1, key = null;
    while (i < n && depth > 0) {
      if (comment()) continue;
      const c = src[i];
      if (c === '"' || c === "'" || c === '`') { const v = str(c); if (depth === 1 && key && c !== '`' && !(key in out) && /^\s*[,}\n]/.test(src.slice(v.end, v.end + 2) || '}')) out[key] = v.raw; key = null; i = v.end; continue; }
      if (c === '{' || c === '[' || c === '(') { depth++; key = null; i++; continue; }
      if (c === '}' || c === ']' || c === ')') { depth--; i++; continue; }
      if (depth === 1 && /[A-Za-z_$]/.test(c)) { const m = /^([A-Za-z_$][\w$]*)\s*:/.exec(src.slice(i, i + 120)); if (m) { key = m[1]; i += m[0].length; continue; } }
      if (!/\s/.test(c)) key = null;   // anything but a string literal after the colon: not a literal value
      i++;
    }
    return out;
  };
  while (i < n) {
    if (comment()) continue;
    const c = src[i];
    if (c === '"' || c === "'" || c === '`') { i = str(c).end; continue; }
    if (/[A-Za-z_$]/.test(c) && !/[\w$.]/.test(src[i - 1] || '')) {
      const w = /^[A-Za-z_$][\w$]*/.exec(src.slice(i, i + 64))[0]; i += w.length;
      if (w === block) { const m = /^\s*:\s*\{/.exec(src.slice(i, i + 64)); if (m) { i += m[0].length; return readObject(); } }
      continue;
    }
    i++;
  }
  return {};
}

/** A JS string literal's escapes, decoded (\n, \', \u2019, \u{1F600}, \x41). */
function unescapeJs(raw) {
  return String(raw || '').replace(/\\(u\{[0-9a-fA-F]+\}|u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|[\s\S])/g, (all, e) => {
    if (e[0] === 'u' && e.length > 1) return String.fromCodePoint(parseInt(e[1] === '{' ? e.slice(2, -1) : e.slice(1), 16));
    if (e[0] === 'x' && e.length === 3) return String.fromCharCode(parseInt(e.slice(1), 16));
    return { n: '\n', t: '\t', r: '' }[e] != null ? { n: '\n', t: '\t', r: '' }[e] : e;
  });
}

/**
 * The scene's own words: {title, description} from SCENE.interactive (title, sub), else SCENE.page (title without
 * its *accent* marks, dek), read as string literals from scene.js. Nothing in the project is run here: project code
 * only ever runs inside the browser.
 */
export function sceneInfo(projectDir) {
  const out = { title: '', description: '' };
  let src = '';
  try { src = fs.readFileSync(path.join(projectDir, 'scene.js'), 'utf8'); } catch { /* no scene */ }
  const I = blockLiterals(src, 'interactive'), P = blockLiterals(src, 'page');
  out.title = unescapeJs(I.title || P.title || '').replace(/\*/g, '').trim();
  out.description = unescapeJs(I.sub || P.dek || '').trim();
  if (!out.title || !out.description) { // the film page's own title block (a scene that keeps its words in index.html)
    try {
      const html = fs.readFileSync(path.join(projectDir, 'index.html'), 'utf8');
      const text = (re) => { const m = re.exec(html); return m ? m[1].replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim() : ''; };
      out.title = out.title || text(/<h1\b[^>]*class="[^"]*\bld-title\b[^"]*"[^>]*>([\s\S]*?)<\/h1>/i);
      out.description = out.description || text(/<div\b[^>]*class="[^"]*\bld-dek\b[^"]*"[^>]*>([\s\S]*?)<\/div>/i);
    } catch { /* no index.html */ }
  }
  return out;
}

/** A URL the page uses -> the file on disk (the same mapping as the showtime server), or null. */
export function figureFile(url, { projectDir, base = '/' }) {
  const u = String(url).trim().replace(/[?#].*$/, '');
  if (!u || /^(data|blob):/i.test(u)) return { inline: true };
  if (/^[a-z][a-z0-9+.-]*:/i.test(u) || u.startsWith('//')) return { remote: u };
  const abs = u.startsWith('/') ? u : path.posix.join(path.posix.dirname(base), u);
  const rel = decodeURIComponent(abs);
  let root, sub;
  if (rel.startsWith('/_st/')) { root = path.join(skillDir(), 'runtime'); sub = rel.slice(5); }
  else if (rel.startsWith('/_lib/')) { root = nodeModulesDir(); sub = rel.slice(6); }
  else { root = projectDir; sub = rel.slice(1); }
  const file = path.resolve(root, ...sub.split('/'));
  if (file !== root && !file.startsWith(root + path.sep)) return { escapes: rel };
  return { file, url: rel };
}

/**
 * Pack the live figure. -> {html, bytes, page, files: [{url, bytes, kind}], fontsDropped, missing: [url], remote: [url]}
 * @param o.projectDir
 * @param o.title       the page title (default: the page's own)
 * @param o.allFonts    keep every font face
 * @param o.minify      shrink scripts and styles (default true)
 * @param o.noCsp       leave out the Content-Security-Policy
 */
export function packFigure(o) {
  const projectDir = path.resolve(o.projectDir);
  let pagePath = path.join(projectDir, 'figure.html'), own = true;
  if (!fs.existsSync(pagePath)) { pagePath = path.join(skillDir(), 'templates', 'diagram', 'figure.html'); own = false; }
  if (!fs.existsSync(path.join(projectDir, 'scene.js'))) {
    throw new UserError('--interactive packs a living diagram: this project has no scene.js', 'start one with `showtime new diagram <dir>` (references/workflows/diagram.md)');
  }
  let html = fs.readFileSync(pagePath, 'utf8');
  if (!own) { // the template's page takes the project's theme (showtime.json) when it has one
    let cfg = {};
    try { cfg = JSON.parse(fs.readFileSync(path.join(projectDir, 'showtime.json'), 'utf8')); } catch { /* none */ }
    if (cfg.theme && /^[\w-]+$/.test(cfg.theme)) html = html.replace(/(<html\b[^>]*\bdata-theme=")[\w-]+(")/, (m, a, b) => a + cfg.theme + b);
  }
  const files = [], missing = [], remote = [];
  const read = (url, base, binary) => {
    const f = figureFile(url, { projectDir, base });
    if (f.inline) return null;
    if (f.remote) { remote.push(f.remote); return null; }
    if (f.escapes || !fs.existsSync(f.file) || !fs.statSync(f.file).isFile()) { missing.push(f.escapes || f.url); return null; }
    const buf = fs.readFileSync(f.file);
    return { buf, text: binary ? null : buf.toString('utf8'), url: f.url, ext: path.extname(f.file).toLowerCase() };
  };
  // scripts and styles, in page order
  const scripts = [], styles = [];
  html = html.replace(/<script\b([^>]*)\bsrc="([^"]+)"([^>]*)>\s*<\/script>/gi, (m, a, src) => {
    const r = read(src, '/figure.html'); if (!r) return m;
    files.push({ url: r.url, bytes: r.buf.length, kind: 'script' });
    const k = `\u0000S${scripts.length}\u0000`; scripts.push(r.text); return k;
  });
  html = html.replace(/<link\b[^>]*\brel="stylesheet"[^>]*>/gi, (m) => {
    const href = (/\bhref="([^"]+)"/i.exec(m) || [])[1]; if (!href) return m;
    const r = read(href, '/figure.html'); if (!r) return m;
    files.push({ url: r.url, bytes: r.buf.length, kind: 'style' });
    const k = `\u0000C${styles.length}\u0000`; styles.push({ text: r.text, url: r.url }); return k;
  });
  // the characters any text can show: the page, its scripts (the scene's words, the figure's own) and styles
  const used = new Set();
  addCodePoints(used, html.replace(/<[^>]+>/g, ' '));
  scripts.forEach((s) => addCodePoints(used, s));
  let fontsDropped = 0;
  const cssOut = styles.map((st) => {
    let css = st.text;
    if (!o.allFonts) { const r = pruneFontFaces(css, used); css = r.text; fontsDropped += r.dropped; }
    css = css.replace(/url\(\s*(['"]?)([^'")]+)\1\s*\)/g, (m, q, u) => {
      const r = read(u, st.url, true); if (!r) return m;
      const mime = FONT_MIME[r.ext] || IMG_MIME[r.ext];
      if (!mime) { missing.push(r.url + ' (not a font or an image)'); return m; }
      files.push({ url: r.url, bytes: r.buf.length, kind: FONT_MIME[r.ext] ? 'font' : 'image' });
      return `url(data:${mime};base64,${r.buf.toString('base64')})`;
    });
    return o.minify === false ? css : minifyCss(css);
  });
  // inside an inlined script the HTML parser looks for `</script` (it ends the script) and `<!--` (its "escaped" state,
  // the only way into the "double escaped" state where the next `</script>` no longer ends it): both are written with
  // an escape that means the same characters in a JS string, template or regex, in the text's own case. `<script` is
  // left alone: without `<!--` it is harmless, and it can be code (`i<scriptSteps`)
  const jsSafe = (t) => t.replace(/<\/(script)/gi, (m, w) => '<\\/' + w).replace(/<!--/g, '<\\x21--');
  const jsOut = scripts.map((s) => jsSafe(o.minify === false ? s : minifyJs(s).text));
  html = html.replace(/\u0000S(\d+)\u0000/g, (m, i) => `<script>\n${jsOut[+i]}\n</script>`);
  html = html.replace(/\u0000C(\d+)\u0000/g, (m, i) => `<style>\n${cssOut[+i].replace(/<\/style/gi, '<\\/style')}\n</style>`);
  const attr = (v) => String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
  // function replacers throughout: a title with $& or $' is text, never a replacement pattern
  if (o.title) html = html.replace(/<title>[^<]*<\/title>/i, () => `<title>${attr(o.title)}</title>`);
  // link previews: the title (and the scene's line under it) when the file is shared
  const og = (o.title ? `\n<meta property="og:title" content="${attr(o.title)}">\n<meta name="twitter:title" content="${attr(o.title)}">` : '') +
    (o.description ? `\n<meta name="description" content="${attr(o.description)}">\n<meta property="og:description" content="${attr(o.description)}">` : '') +
    (o.title ? '\n<meta property="og:type" content="website">\n<meta name="twitter:card" content="summary">' : '');
  html = html.replace(/<head([^>]*)>/i, (m, a) => `<head${a}>${o.noCsp ? '' : `\n<meta http-equiv="Content-Security-Policy" content="${FIGURE_CSP}">`}${og}`);
  // third-party notices, as the film export writes them: the packages packed (the fonts' OFL), project credits
  // the font files are packed as data: URLs (their CSS headers are minified away): name them and their licence here
  const fontPkgs = [...new Set(files.filter((f) => f.kind === 'font').map((f) => (/^\/_lib\/((?:@[^/]+\/)?[^/]+)\//.exec(f.url) || [])[1]).filter(Boolean))];
  const ofl = fontPkgs.filter((p) => {
    try { return /OFL/i.test(JSON.parse(fs.readFileSync(path.join(nodeModulesDir(), ...p.split('/'), 'package.json'), 'utf8')).license || ''); } catch { return false; }
  });
  const fontCredit = ofl.length ? [`Fonts: ${ofl.join(', ')}, under the SIL Open Font License 1.1 (https://openfontlicense.org)`] : [];
  // (no scene words in it: the comment is about the file's parts, and nothing a scene says can end it early)
  const notice = (`A living diagram's live figure, exported with showtime; every file it uses is packed inside.\n` +
    notices(new Map(files.map((f) => [f.url, f])), { projDir: projectDir, extraCredits: fontCredit }))
    .replace('Third-party packages (their own license headers are kept in the packed files):', 'Third-party packages packed in this file:');
  // the charset first in <head> (browsers look for it in the first 1024 bytes), then this notice
  html = html.replace(/<meta\s+charset="[^"]*"\s*\/?>\s*/i, '');
  html = html.replace(/<head([^>]*)>/i, (m, a) => `<head${a}>\n<meta charset="utf-8">\n<!--\n${notice.replace(/--/g, '- -')}\n-->`);
  // any remaining reference to a file is a page that would reach the network or miss a file offline
  for (const m of html.matchAll(/\b(?:src|href)="([^"#][^"]*)"/gi)) { const f = figureFile(m[1], { projectDir }); if (!f.inline) (f.remote ? remote : missing).push(f.remote || f.url || m[1]); }
  return { html, bytes: Buffer.byteLength(html), page: own ? 'figure.html' : 'the diagram template\'s figure.html', files, fontsDropped, missing: [...new Set(missing)], remote: [...new Set(remote)] };
}

// Collect the files an exported HTML video needs, keyed by the URL path the page uses on the
// showtime server ('/scenes.js', '/_st/film.js', '/_lib/<pkg>/...', '/_assets/...', '/_st/emoji/...').
//
// Sources: what the page requested while it played through (probe.mjs), then a closure over
// the text files: module imports, CSS @import/url(), path-like strings in the project's own files
// and emoji in its text. Module sources get their relative specifiers and import.meta.url
// rewritten to absolute URLs on the export's virtual origin (the player maps those to blobs).
// Font faces whose unicode-range covers no character used anywhere are dropped.

import { minifyJs } from './minify.mjs';

export const VORIGIN = 'http://st.invalid';

const SKIP = new Set(['/favicon.ico', '/_st/ping', '/_st/events', '/_st/project', '/_st/lab', '/_st/preview']);
const TEXT_RE = /^(text\/|application\/(json|javascript|xml|ld\+json|manifest\+json)|image\/svg\+xml)/;
const JS_RE = /javascript/;
const FONT_EXT = /\.(woff2?|ttf|otf)$/i;
const MEDIA_RE = /^(video|audio)\//;
const PATHLIKE = /(["'`(=\s,])((?:\.{1,2}\/|\/)?[A-Za-z0-9_@~%+-][^"'`()\s<>{}|\\^]*?\.(?:png|jpe?g|webp|avif|gif|svg|json|geojson|topojson|mp4|m4v|webm|mov|ogv|m4a|mp3|wav|ogg|opus|flac|woff2?|ttf|otf|css|js|mjs|txt|csv|tsv|glsl|frag|vert|lottie|vtt|srt|bin|wasm))(?=["'`)?#\s,])/gi;
let EMOJI_RE = null;
try {
  EMOJI_RE = new RegExp('[\\u{1F1E6}-\\u{1F1FF}]{2}|(?:\\p{Emoji_Presentation}|\\p{Extended_Pictographic}\\uFE0F)' +
    '(?:\\uFE0F|[\\u{1F3FB}-\\u{1F3FF}]|\\u200D\\p{Extended_Pictographic}\\uFE0F?[\\u{1F3FB}-\\u{1F3FF}]?)*', 'gu');
} catch { EMOJI_RE = null; }

export const isText = (mime) => TEXT_RE.test(mime || '');
export const isJs = (mime) => JS_RE.test(mime || '');
export const isCss = (mime) => /^text\/css/.test(mime || '');
export const isMedia = (mime) => MEDIA_RE.test(mime || '');
const isProjectPath = (p) => !/^\/_(st|lib|assets)\//.test(p);

function abs(spec, fromPath) {
  try {
    const u = new URL(spec, VORIGIN + fromPath);
    if (u.origin !== VORIGIN) return null;
    return decodeURIComponent(u.pathname);
  } catch { return null; }
}

/** Rewrite relative/root import specifiers and import.meta.url to absolute virtual URLs. -> {text, deps} */
export function rewriteJs(text, filePath) {
  const deps = new Set();
  const fix = (spec) => {
    if (!/^(\.{1,2}\/|\/(?!\/))/.test(spec)) return null;
    const p = abs(spec, filePath);
    if (!p) return null;
    deps.add(p);
    return VORIGIN + encodeURI(p);
  };
  let out = text.replace(/\bimport\.meta\.url\b/g, JSON.stringify(VORIGIN + encodeURI(filePath)));
  out = out.replace(/(\bfrom\s*)(['"])([^'"\r\n]+)\2/g, (all, pre, q, spec) => { const f = fix(spec); return f ? `${pre}${q}${f}${q}` : all; });
  out = out.replace(/(\bimport\s*)(['"])([^'"\r\n]+)\2/g, (all, pre, q, spec) => { const f = fix(spec); return f ? `${pre}${q}${f}${q}` : all; });
  out = out.replace(/(\bimport\s*\(\s*)(['"])([^'"\r\n]+)\2(\s*\))/g, (all, pre, q, spec, post) => { const f = fix(spec); return f ? `${pre}${q}${f}${q}${post}` : all; });
  return { text: out, deps: [...deps] };
}

/** url() and @import targets of a stylesheet at `filePath` -> [{path, font}] */
export function cssRefs(text, filePath) {
  const out = [];
  const re = /@import\s+(?:url\(\s*)?(['"]?)([^'")\s;]+)\1|url\(\s*(['"]?)([^'")]*?)\3\s*\)/gi;
  let m;
  while ((m = re.exec(text))) {
    const u = m[2] || m[4];
    if (!u || /^(data:|blob:|#|about:)/i.test(u)) continue;
    const p = abs(u, filePath);
    if (p) out.push({ path: p, font: FONT_EXT.test(p) });
  }
  return out;
}

/** Path-like strings in a project text file, resolved against it. */
export function pathRefs(text, filePath) {
  const out = new Set();
  PATHLIKE.lastIndex = 0;
  let m;
  while ((m = PATHLIKE.exec(text))) {
    const s = m[2];
    if (/^[a-z][a-z0-9+.-]*:/i.test(s) || s.startsWith('//')) continue;
    const p = abs(s, filePath);
    if (p) out.add(p);
  }
  return [...out];
}

/** Emoji the stage runtime would swap for SVGs -> ['/_st/emoji/1f680.svg', ...] */
export function emojiRefs(text) {
  if (!EMOJI_RE) return [];
  const out = new Set();
  EMOJI_RE.lastIndex = 0;
  let m;
  while ((m = EMOJI_RE.exec(text))) out.add('/_st/emoji/' + [...m[0]].map((ch) => ch.codePointAt(0).toString(16)).join('-') + '.svg');
  return [...out];
}

const ENTITIES = { nbsp: 0xa0, mdash: 0x2014, ndash: 0x2013, rarr: 0x2192, larr: 0x2190, uarr: 0x2191, darr: 0x2193,
  hellip: 0x2026, middot: 0xb7, copy: 0xa9, reg: 0xae, trade: 0x2122, bull: 0x2022, times: 0xd7, rsquo: 0x2019,
  lsquo: 0x2018, ldquo: 0x201c, rdquo: 0x201d, euro: 0x20ac, pound: 0xa3, deg: 0xb0, laquo: 0xab, raquo: 0xbb };

/** Every code point in a text, including \\u escapes and HTML character references. */
export function addCodePoints(set, text) {
  for (const ch of text) set.add(ch.codePointAt(0));
  const re = /\\u\{([0-9a-fA-F]{1,6})\}|\\u([0-9a-fA-F]{4})|&#x([0-9a-fA-F]+);|&#(\d+);|&([a-zA-Z]+);/g;
  let m;
  while ((m = re.exec(text))) {
    const cp = m[1] ? parseInt(m[1], 16) : m[2] ? parseInt(m[2], 16) : m[3] ? parseInt(m[3], 16) : m[4] ? parseInt(m[4], 10) : ENTITIES[m[5]];
    if (cp) set.add(cp);
  }
}

function parseRanges(str) {
  const out = [];
  for (const part of String(str).split(',')) {
    const m = part.trim().match(/^U\+([0-9A-F?]+)(?:-([0-9A-F]+))?$/i);
    if (!m) continue;
    if (m[1].includes('?')) out.push([parseInt(m[1].replace(/\?/g, '0'), 16), parseInt(m[1].replace(/\?/g, 'F'), 16)]);
    else out.push([parseInt(m[1], 16), parseInt(m[2] || m[1], 16)]);
  }
  return out;
}

/** Drop @font-face blocks whose unicode-range covers none of `used`. -> {text, dropped} */
export function pruneFontFaces(css, used) {
  let dropped = 0;
  const text = css.replace(/@font-face\s*\{[^{}]*\}/gi, (block) => {
    const m = /unicode-range\s*:\s*([^;}]+)/i.exec(block);
    if (!m) return block;
    const ranges = parseRanges(m[1]);
    if (!ranges.length) return block;
    for (const cp of used) for (const [a, b] of ranges) if (cp >= a && cp <= b) return block;
    dropped++;
    return '';
  });
  return { text, dropped };
}

/**
 * Gather the files.
 * @param o.serverUrl  showtime server base URL
 * @param o.pagePath   '/index.html'
 * @param o.pageHtml   the page source (from disk)
 * @param o.requests   paths the page requested during the probe
 * @param o.allFonts   keep every font face
 * @param o.domText    every character the page showed during the probe
 * @param o.exclude    project paths packed only when the page requests them (the audio mix sources)
 * @param o.warn       (msg) => void
 * -> { files: Map(path -> {mime, bytes: Buffer, text?: string, source}), missing: [path], droppedFaces }
 */
export async function collectFiles(o) {
  const files = new Map();
  const missing = [];
  const queue = [];
  const queued = new Set();
  const exclude = new Set(o.exclude || []);
  const enqueue = (p, source, optional = false) => {
    if (!p || SKIP.has(p) || p === o.pagePath || p === '/_st/stage.js' || queued.has(p)) return;
    // the soundtrack's sources (the mix spec and its files) and build folders: only when the page itself asks
    if (optional && (exclude.has(p) || /^\/(work|showtime-out|node_modules|\.git)\//.test(p))) return;
    queued.add(p);
    queue.push({ p, source, optional });
  };
  for (const p of o.requests) enqueue(p, 'requested');
  // comments name files without using them (a note about a folder once packed 14 MB of WAVs): scan code only
  for (const p of pathRefs(o.pageHtml.replace(/<!--[\s\S]*?-->/g, ' '), o.pagePath)) enqueue(p, 'page', true);
  for (const p of emojiRefs(o.pageHtml)) enqueue(p, 'emoji', true);
  enqueue('/showtime.json', 'config', true);

  const get = async (p) => {
    const r = await fetch(o.serverUrl + encodeURI(p), { headers: { 'Cache-Control': 'no-store' } });
    if (!r.ok) return { status: r.status };
    const mime = (r.headers.get('content-type') || 'application/octet-stream').split(';')[0].trim();
    return { status: r.status, mime, bytes: Buffer.from(await r.arrayBuffer()) };
  };
  while (queue.length) {
    const batch = queue.splice(0, 16);
    const got = await Promise.all(batch.map(async (it) => ({ it, r: await get(it.p).catch((e) => ({ status: 0, err: e.message })) })));
    for (const { it, r } of got) {
      if (r.status !== 200) { if (!it.optional) missing.push(it.p); continue; }
      const f = { mime: r.mime, bytes: r.bytes, source: it.source };
      files.set(it.p, f);
      if (!isText(r.mime)) continue;
      f.text = r.bytes.toString('utf8');
      if (isJs(r.mime)) {
        const rw = rewriteJs(f.text, it.p);
        f.text = rw.text;
        for (const d of rw.deps) enqueue(d, `import in ${it.p}`);
      } else if (isCss(r.mime)) {
        for (const ref of cssRefs(f.text, it.p)) enqueue(ref.path, `css ${it.p}`, ref.font);
      }
      if (isProjectPath(it.p) && it.p !== '/showtime.json' && !exclude.has(it.p)) {
        const code = isJs(r.mime) ? minifyJs(f.text, { module: /\.mjs$/.test(it.p), keepLicense: false }).text : f.text;
        for (const d of pathRefs(code, it.p)) enqueue(d, `referenced in ${it.p}`, true);
        for (const d of emojiRefs(f.text)) enqueue(d, 'emoji', true);
      }
    }
  }

  // font faces nobody can use
  let droppedFaces = 0;
  if (!o.allFonts) {
    const used = new Set();
    for (let c = 0x20; c < 0x7f; c++) used.add(c);
    addCodePoints(used, o.pageHtml);
    // text drawn by the video: what the page showed while it played through (DOM text), plus the
    // page source and the project's own files (canvas text lives in their strings)
    addCodePoints(used, o.domText || '');
    for (const [p, f] of files) {
      if (f.text === undefined || isCss(f.mime) || /\.svg$/i.test(p) || !isProjectPath(p)) continue;
      addCodePoints(used, f.text);
    }
    for (const [, f] of files) {
      if (!isCss(f.mime)) continue;
      const r = pruneFontFaces(f.text, used);
      f.text = r.text;
      droppedFaces += r.dropped;
    }
    dropUnreferencedFonts(files, o.pageHtml, o.pagePath);
  }
  return { files, missing, droppedFaces };
}

/** Delete font files that no stylesheet, script or the page mentions any more. -> count */
export function dropUnreferencedFonts(files, pageHtml, pagePath) {
  const refs = new Set();
  for (const [p, f] of files) {
    if (f.text === undefined) continue;
    if (isCss(f.mime)) for (const r of cssRefs(f.text, p)) refs.add(r.path);
    else for (const r of pathRefs(f.text, p)) refs.add(r);
  }
  for (const r of pathRefs(pageHtml, pagePath)) refs.add(r);
  for (const r of cssRefs(pageHtml, pagePath)) refs.add(r.path);
  let n = 0;
  for (const p of [...files.keys()]) if (FONT_EXT.test(p) && !refs.has(p)) { files.delete(p); n++; }
  return n;
}

/**
 * Every browser the export supports reads WOFF2: drop the older formats listed after it in a
 * @font-face src (fontsource lists woff2, then woff) and the files only they used. -> files dropped
 */
export function preferWoff2(files, pageHtml, pagePath) {
  let changed = false;
  for (const [, f] of files) {
    if (!isCss(f.mime) || f.text === undefined) continue;
    const t = f.text.replace(/(@font-face\s*\{[^{}]*?\bsrc\s*:\s*)([^;{}]+)/gi, (all, pre, list) => {
      const items = list.split(/,(?=\s*(?:url|local)\()/i);
      const w2 = items.filter((x) => /format\(\s*['"]?woff2/i.test(x) || /\.woff2(['")?#]|$)/i.test(x));
      if (!w2.length || w2.length === items.length) return all;
      return pre + w2.join(',').trim();
    });
    if (t !== f.text) { f.text = t; f.bytes = Buffer.from(t); changed = true; }
  }
  return changed ? dropUnreferencedFonts(files, pageHtml, pagePath) : 0;
}

/**
 * Canvas films: drop @font-face rules of families that no frame drew text with (a template may load
 * a face "just in case"). used: Set of family names (unquoted, lower case). -> {faces, files}
 */
export function pruneFontFamilies(files, used, pageHtml, pagePath) {
  let faces = 0;
  for (const [, f] of files) {
    if (!isCss(f.mime) || f.text === undefined) continue;
    f.text = f.text.replace(/@font-face\s*\{[^{}]*\}/gi, (block) => {
      const m = /font-family\s*:\s*([^;}]+)/i.exec(block);
      if (!m) return block;
      const fam = m[1].trim().replace(/^['"]|['"]$/g, '').toLowerCase();
      if (used.has(fam)) return block;
      faces++;
      return '';
    });
    f.bytes = Buffer.from(f.text);
  }
  return { faces, files: faces ? dropUnreferencedFonts(files, pageHtml, pagePath) : 0 };
}

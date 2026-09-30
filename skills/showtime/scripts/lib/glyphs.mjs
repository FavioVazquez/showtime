// Characters the page's fonts do not have, and the exact fix for them.
//
// `check` sees text that falls back to a system font (CDP reports the font each node was painted
// with). Which characters did that is a guess from the text; this module narrows the guess to the
// characters that no loaded @font-face of the element's font stack covers (its unicode-range), and
// writes the fix for exactly those: sub/superscript digits as <sub>/<sup> markup the theme font draws,
// arrows as an inline SVG icon, anything else as an @font-face with that unicode-range.
//
// showtime's bundled fonts are the fontsource subsets (latin, latin-ext, ...): none of them has
// sub/superscript digits (U+2070-209F) or most arrows (only U+2191 and U+2193), so the fix never
// names a bundled font for those.
//
//   import { uncovered, glyphFix } from './lib/glyphs.mjs';

const SYMBOLS_FILE = 'noto-sans-symbols-2/noto-sans-symbols-2-symbols-400-normal.woff2';
const SUBS = '₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎';
const SUPS = '⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾';
const PLAIN = '0123456789+−=()';

/** "U+0-FF, U+131, U+2000-206F" -> [[0, 255], [305, 305], [8192, 8303]] */
export function parseRanges(s) {
  const out = [];
  for (const part of String(s || 'U+0-10FFFF').split(',')) {
    const m = /U\+([0-9a-f?]+)(?:-([0-9a-f]+))?/i.exec(part.trim());
    if (!m) continue;
    if (m[1].includes('?')) {
      out.push([parseInt(m[1].replace(/\?/g, '0'), 16), parseInt(m[1].replace(/\?/g, 'F'), 16)]);
      continue;
    }
    const a = parseInt(m[1], 16);
    out.push([a, m[2] ? parseInt(m[2], 16) : a]);
  }
  return out;
}

const GENERIC = new Set(['serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui', 'ui-monospace', 'ui-sans-serif', 'ui-serif', 'ui-rounded', 'emoji', 'math']);
const famKey = (f) => String(f || '').trim().replace(/^["']|["']$/g, '').toLowerCase();

/** The families of a CSS font-family value, in order ("'Inter', system-ui" -> ['inter', 'system-ui']). */
export function families(stack) {
  return String(stack || '').split(',').map(famKey).filter(Boolean);
}

/**
 * The characters of `chars` that no loaded face of the `stack` families covers.
 * faces: [{family, unicodeRange, status}] (document.fonts). When the stack names no loaded face at
 * all, nothing can be said: all chars are returned.
 */
export function loadedFaces(stack, faces) {
  const fams = new Set(families(stack));
  return (faces || []).filter((f) => f.status === 'loaded' && fams.has(famKey(f.family)));
}

export function uncovered(chars, stack, faces) {
  const mine = loadedFaces(stack, faces);
  if (!mine.length) return [...chars];
  const ranges = mine.flatMap((f) => parseRanges(f.unicodeRange));
  return [...chars].filter((ch) => {
    const c = ch.codePointAt(0);
    return !ranges.some(([a, b]) => c >= a && c <= b);
  });
}

const hex = (ch) => 'U+' + ch.codePointAt(0).toString(16).toUpperCase().padStart(4, '0');

/** The sample with sub/superscript characters written as <sub>/<sup> markup. */
export function asMarkup(text) {
  let out = '';
  for (const ch of text) {
    const i = SUBS.indexOf(ch), j = SUPS.indexOf(ch);
    if (i >= 0) out += `<sub>${PLAIN[i]}</sub>`;
    else if (j >= 0) out += `<sup>${PLAIN[j]}</sup>`;
    else out += ch;
  }
  return out.replace(/<\/sub><sub>/g, '').replace(/<\/sup><sup>/g, '');
}

/**
 * {message part, fix} for characters a page's fonts lack. chars: the missing characters; stack: the
 * element's font-family value; sample: a text that uses them.
 */
export function glyphFix(chars, stack, sample) {
  const list = [...new Set(chars)];
  const scripts = list.filter((ch) => SUBS.includes(ch) || SUPS.includes(ch));
  const arrows = list.filter((ch) => { const c = ch.codePointAt(0); return c >= 0x2190 && c <= 0x21ff; });
  const rest = list.filter((ch) => !scripts.includes(ch) && !arrows.includes(ch));
  const fixes = [];
  if (scripts.length) {
    const words = String(sample || '').split(/\s+/).filter((w) => [...w].some((ch) => scripts.includes(ch)));
    const eg = words.length ? `"${asMarkup(words[0])}" for "${words[0]}"` : '"CO<sub>2</sub>" for "CO₂"';
    fixes.push(`write ${scripts.join(' ')} as markup the theme font draws: ${eg}, with sub, sup { font-size: .62em; ` +
      'line-height: 0; position: relative; vertical-align: baseline } sub { bottom: -.25em } sup { top: -.5em }');
  }
  if (arrows.length) {
    fixes.push(`draw ${arrows.join(' ')} as an inline SVG icon (e.g. /_lib/lucide-static/icons/arrow-right.svg, ` +
      'stroke="currentColor") or write the words ("to", "up")');
  }
  if (rest.length) {
    // the fallback goes right after the named families, before the first generic one (system-ui would
    // otherwise pick a system font first)
    const items = String(stack || '').split(',').map((x) => x.trim()).filter(Boolean);
    const gi = items.findIndex((x) => GENERIC.has(famKey(x)));
    const named = items.filter((x) => !GENERIC.has(famKey(x)));
    items.splice(gi < 0 ? items.length : gi, 0, "'Glyph Fallback'");
    fixes.push(`add a font that has ${rest.join(' ')} for just those characters, e.g. \`showtime assets font "Noto Sans Symbols 2" ` +
      `--subsets symbols --copy-to <project>/fonts\` (OFL; most symbols and dingbats), then @font-face { font-family: 'Glyph Fallback'; ` +
      `src: url('fonts/${SYMBOLS_FILE}'); unicode-range: ${rest.map(hex).join(', ')} } and font-family: ${items.join(', ')}` +
      (named.length ? ` (${named[0]} stays in charge of every other character); run check again to confirm the font has them` : ''));
  }
  return {
    chars: list.map((ch) => `${ch} (${hex(ch)})`).join(', '),
    fix: fixes.join('; ') + (scripts.length || arrows.length ? " (showtime's bundled fonts have no sub/superscript digits or arrows other than ↑ ↓)" : ''),
  };
}

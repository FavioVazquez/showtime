// Shrink scripts and stylesheets packed into an exported HTML video.
//
// A careful whitespace-and-comments pass, not a renaming minifier: it tokenizes JavaScript (strings,
// template literals, regular expressions, comments) and keeps every token and every line break
// (so automatic semicolon insertion never changes meaning), dropping comments, indentation, blank
// lines and the spaces a token boundary does not need. The result is checked by compiling it
// (node:vm); anything that does not compile, or that the tokenizer is unsure about, is left as it was.
//
// Leaf sections of the film runtime that a project never calls are dropped first (see pruneParts):
// runtime/film.js and runtime/synth.js mark them with  // @part <name>: api names ... // @end <name>
import vm from 'node:vm';

const KEYWORDS_BEFORE_EXPR = new Set(['return', 'typeof', 'instanceof', 'in', 'of', 'new', 'delete', 'void', 'throw',
  'case', 'do', 'else', 'yield', 'await']);
const ID_CHAR = /[A-Za-z0-9_$\u0080-￿]/;
// characters next to which a space is never needed (a space between two of + - / or before . is kept)
const TIGHT = new Set('{}()[],;:=<>?!&|*%^~'.split(''));

/**
 * Minify JavaScript. -> {text, ok, saved} (ok false = returned unchanged)
 * @param {string} src
 * @param {{module?: boolean, keepLicense?: boolean}} o
 */
export function minifyJs(src, o = {}) {
  let out;
  try { out = squeeze(src, o.keepLicense !== false); } catch { return { text: src, ok: false, saved: 0 }; }
  if (out.length >= src.length) return { text: src, ok: false, saved: 0 };
  if (!compiles(out, o.module)) return { text: src, ok: false, saved: 0 };
  return { text: out, ok: true, saved: src.length - out.length };
}

function compiles(code, module) {
  try {
    if (module || /(^|[\s;])(import|export)[\s{*]/.test(code)) {
      if (typeof vm.SourceTextModule === 'function') { new vm.SourceTextModule(code); return true; } // eslint-disable-line no-new
      // no module compiler in this Node: accept only when the original also had no chance to be checked
      new Function(code.replace(/^\s*(import|export)\b[^\n]*$/gm, '')); // eslint-disable-line no-new, no-new-func
      return true;
    }
    new vm.Script(code); // eslint-disable-line no-new
    return true;
  } catch { return false; }
}

function squeeze(src, keepLicense, onToken) {
  const n = src.length;
  let i = 0;
  const lines = [];
  let cur = '';                 // the output line being built
  let last = '';                // last significant token (for regex vs division)
  let lastKind = '';            // 'id' | 'num' | 'str' | 'punct' | 'regex' | 'tmpl'
  let pendingSpace = false;
  const tmplStack = [];         // brace depth inside each open ${ ... }
  let braceDepth = 0;

  const emit = (tok, kind) => {
    if (pendingSpace && cur) {
      const a = cur[cur.length - 1], b = tok[0];
      const needs = !(TIGHT.has(a) || TIGHT.has(b)) || ((a === '+' || a === '-') && (b === '+' || b === '-')) || (a === '/' || b === '/');
      if (needs) cur += ' ';
    }
    pendingSpace = false;
    cur += tok;
    if (kind !== 'comment') { last = tok; lastKind = kind; }
    if (onToken) onToken(tok, kind);
  };
  const newline = () => {
    if (cur.trim()) lines.push(cur);
    cur = '';
    pendingSpace = false;
  };
  const regexAllowed = () => {
    if (!lastKind) return true;
    if (lastKind === 'num' || lastKind === 'str' || lastKind === 'regex' || lastKind === 'tmpl') return false;
    if (lastKind === 'id') return KEYWORDS_BEFORE_EXPR.has(last);
    return !(last === ')' || last === ']' || last === '}');
  };

  while (i < n) {
    const c = src[i];
    // whitespace
    if (c === '\n' || c === '\r' || c === '\u2028' || c === '\u2029') { newline(); i++; continue; }
    if (c === ' ' || c === '\t' || c === '\f' || c === '\v' || c === ' ' || c === '﻿') { pendingSpace = true; i++; continue; }
    // comments
    if (c === '/' && src[i + 1] === '/') {
      let j = i + 2;
      while (j < n && src[j] !== '\n' && src[j] !== '\r') j++;
      i = j;
      pendingSpace = true;
      continue;
    }
    if (c === '/' && src[i + 1] === '*') {
      const j = src.indexOf('*/', i + 2);
      if (j < 0) throw new Error('unterminated comment');
      const body = src.slice(i, j + 2);
      if (keepLicense && /^\/\*!|@license|@preserve/.test(body)) { emit(body, 'comment'); }
      else if (/[\n\r\u2028\u2029]/.test(body)) newline();  // a comment with a line break counts as one
      else pendingSpace = true;
      i = j + 2;
      continue;
    }
    // strings
    if (c === '"' || c === "'") {
      let j = i + 1;
      while (j < n && src[j] !== c) {
        if (src[j] === '\\') j += 2;
        else if (src[j] === '\n') throw new Error('newline in string');
        else j++;
      }
      if (j >= n) throw new Error('unterminated string');
      emit(src.slice(i, j + 1), 'str');
      i = j + 1;
      continue;
    }
    // template literals (with nested ${ })
    if (c === '`' || (c === '}' && tmplStack.length && tmplStack[tmplStack.length - 1] === braceDepth)) {
      let j = i + 1;
      if (c === '}') tmplStack.pop();
      let open = false;
      while (j < n) {
        if (src[j] === '\\') { j += 2; continue; }
        if (src[j] === '`') { j++; break; }
        if (src[j] === '$' && src[j + 1] === '{') { j += 2; open = true; break; }
        j++;
      }
      if (j > n) throw new Error('unterminated template');
      // template text keeps its line breaks: emit it verbatim, splitting output lines is not allowed here
      emit(src.slice(i, j), 'tmpl');
      if (open) { tmplStack.push(braceDepth); last = '${'; lastKind = 'punct'; }
      i = j;
      continue;
    }
    // regular expression literal
    if (c === '/' && regexAllowed()) {
      let j = i + 1, inClass = false;
      while (j < n) {
        const d = src[j];
        if (d === '\\') { j += 2; continue; }
        if (d === '\n' || d === '\r') throw new Error('newline in regex');
        if (inClass) { if (d === ']') inClass = false; }
        else if (d === '[') inClass = true;
        else if (d === '/') break;
        j++;
      }
      if (j >= n) throw new Error('unterminated regex');
      j++;
      while (j < n && /[a-z]/i.test(src[j])) j++;
      emit(src.slice(i, j), 'regex');
      i = j;
      continue;
    }
    // identifiers / keywords
    if (ID_CHAR.test(c) && !/[0-9]/.test(c)) {
      let j = i + 1;
      while (j < n && ID_CHAR.test(src[j])) j++;
      emit(src.slice(i, j), 'id');
      i = j;
      continue;
    }
    // numbers (incl. .5, 1e-9, 0x1f, 1_000, 10n)
    if (/[0-9]/.test(c) || (c === '.' && /[0-9]/.test(src[i + 1] || ''))) {
      let j = i + 1;
      while (j < n && /[0-9A-Za-z_.]/.test(src[j])) {
        if ((src[j] === 'e' || src[j] === 'E') && (src[j + 1] === '-' || src[j + 1] === '+') && !/^0[xX]/.test(src.slice(i, j))) j += 2;
        else j++;
      }
      emit(src.slice(i, j), 'num');
      i = j;
      continue;
    }
    // punctuation
    if (c === '{') braceDepth++;
    else if (c === '}') braceDepth--;
    // keep multi-char operators together so spacing rules see them whole
    const three = src.slice(i, i + 4);
    const op = (/^(>>>=|\.\.\.|===|!==|\*\*=|<<=|>>=|>>>|&&=|\|\|=|\?\?=|=>|==|!=|<=|>=|&&|\|\||\?\?|\?\.|\+\+|--|\+=|-=|\*=|\/=|%=|&=|\|=|\^=|\*\*|<<|>>)/.exec(three) || [c])[0];
    emit(op, 'punct');
    i += op.length;
  }
  newline();
  if (tmplStack.length) throw new Error('unbalanced template');
  return lines.join('\n') + '\n';
}

/** Minify CSS (comments, whitespace, spaces around punctuation that never need one). */
export function minifyCss(src) {
  const parts = [];
  let i = 0;
  const n = src.length;
  let buf = '';
  while (i < n) {
    const c = src[i];
    if (c === '/' && src[i + 1] === '*') {
      const j = src.indexOf('*/', i + 2);
      const body = j < 0 ? '' : src.slice(i, j + 2);
      if (/^\/\*!/.test(body)) buf += body;
      i = j < 0 ? n : j + 2;
      buf += ' ';
      continue;
    }
    if (c === '"' || c === "'") {
      let j = i + 1;
      while (j < n && src[j] !== c) j += src[j] === '\\' ? 2 : 1;
      parts.push(squeezeCss(buf)); buf = '';
      parts.push(src.slice(i, j + 1));
      i = j + 1;
      continue;
    }
    buf += c;
    i++;
  }
  parts.push(squeezeCss(buf));
  // inside declaration blocks (innermost braces) a space before ':' is never needed
  const text = parts.join('').trim().replace(/\{([^{}"']*)\}/g, (all, body) => '{' + body.replace(/\s+:/g, ':') + '}');
  return text.length < src.length ? text : src;
}
function squeezeCss(s) {
  return s.replace(/\s+/g, ' ')
    .replace(/\s*([{};,>])\s*/g, '$1')      // never before ':' (a descendant selector's space matters)
    .replace(/:\s+/g, ':')
    .replace(/;}/g, '}');
}

/** Identifier words of a script (and the words inside its strings when `strings`), comments excluded. */
export function codeWords(src, { strings = false } = {}) {
  const out = new Set();
  try {
    squeeze(src, false, (tok, kind) => {
      if (kind === 'id') out.add(tok);
      else if (strings && (kind === 'str' || kind === 'tmpl')) for (const w of tok.match(/[A-Za-z_$][A-Za-z0-9_$]*/g) || []) out.add(w);
    });
  } catch {
    for (const w of src.match(/[A-Za-z_$][A-Za-z0-9_$]*/g) || []) out.add(w);   // cannot tokenize: every word counts
  }
  return out;
}

/**
 * Drop marked leaf sections of a runtime file that the video never uses.
 * A section is  // @part <name>: <names it defines>  ...  // @end <name>.  It is kept when one of its
 * names is a word in `usedText` (the project's own pages, scripts and data, comments included, so
 * a doubt keeps code), in the code of the runtime outside every section, or in a kept section
 * (strings included: instruments are also called by name). -> {text, dropped: [names], kept: [names]}
 */
export function pruneParts(src, usedText) {
  const re = /^[ \t]*\/\/ @part ([\w-]+): ([^\n]*)\n([\s\S]*?)^[ \t]*\/\/ @end \1[ \t]*\n/gm;
  const parts = [];
  let m;
  while ((m = re.exec(src))) {
    // the names a section defines: the listed ones, plus every declaration and API assignment at
    // its top level (so a helper added later cannot be dropped while code outside still uses it)
    const api = new Set(m[2].trim().split(/\s+/).filter(Boolean));
    for (const d of m[3].matchAll(/^ {2}(?:var|let|const|function)\s+([A-Za-z_$][\w$]*)/gm)) api.add(d[1]);
    for (const d of m[3].matchAll(/^ {2}[A-Za-z_$][\w$]*\.([A-Za-z_$][\w$]*)\s*=[^=]/gm)) api.add(d[1]);
    parts.push({ name: m[1], api: [...api], body: m[3] });
  }
  if (!parts.length) return { text: src, dropped: [], kept: [] };
  const words = new Set(String(usedText || '').match(/[A-Za-z_$][A-Za-z0-9_$]*/g) || []);
  for (const w of codeWords(src.replace(re, '\n'))) words.add(w);
  const kept = new Set();
  for (let changed = true; changed;) {
    changed = false;
    for (const p of parts) {
      if (kept.has(p.name) || !p.api.some((w) => words.has(w))) continue;
      kept.add(p.name);
      changed = true;
      for (const w of codeWords(p.body, { strings: true })) words.add(w);
    }
  }
  const dropped = parts.filter((p) => !kept.has(p.name)).map((p) => p.name);
  const text = src.replace(re, (all, name) => (kept.has(name) ? all : `// (${name}: not used by this video)\n`));
  return { text, dropped, kept: [...kept] };
}

// Syntax-highlight source code into token JSON for the code-block component (offline, shiki).
//
// usage: showtime code <file|-> [-o tokens.json] [--lang ts] [--theme github-dark]
//                      [--to <new-file>] [--marks] [--list-themes] [--list-langs] [--json]
//
//   showtime code src/app.ts -o scene/code.json                 # highlight one file
//   showtime code old.py --to new.py -o scene/diff.json         # line diff (removed/added lines)
//   showtime code snippet.txt --marks --lang rust -o c.json     # lines starting "+ " / "- " are diff marks
//
// Output: {"version":1,"lang","theme","fg","bg","lines":[{"tokens":[{"c":"const","color":"#F97583","s":0}],
//          "diff":"+"|"-"|undefined}]}   (s = font style bitmask: 1 italic, 2 bold, 4 underline)
import fs from 'node:fs';
import path from 'node:path';
import { importDep } from './lib/deps.mjs';

const EXT = {
  '.js': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript', '.jsx': 'jsx', '.ts': 'typescript', '.tsx': 'tsx',
  '.py': 'python', '.rb': 'ruby', '.go': 'go', '.rs': 'rust', '.java': 'java', '.kt': 'kotlin', '.swift': 'swift',
  '.c': 'c', '.h': 'c', '.cc': 'cpp', '.cpp': 'cpp', '.hpp': 'cpp', '.cs': 'csharp', '.php': 'php', '.sh': 'bash',
  '.bash': 'bash', '.zsh': 'bash', '.ps1': 'powershell', '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml', '.toml': 'toml',
  '.md': 'markdown', '.html': 'html', '.css': 'css', '.scss': 'scss', '.sql': 'sql', '.lua': 'lua', '.dart': 'dart',
  '.ex': 'elixir', '.exs': 'elixir', '.hs': 'haskell', '.scala': 'scala', '.vue': 'vue', '.svelte': 'svelte', '.zig': 'zig',
  '.dockerfile': 'dockerfile', '.txt': 'text',
};

const HELP = `showtime code: syntax-highlight code into token JSON for the code-block component.

usage: showtime code <file|-> [options]

options:
  -o, --out FILE      write JSON here (default: print to stdout)
  --lang NAME         language (default: from the file extension, else "text")
  --theme NAME        shiki theme (default: github-dark). --list-themes to see all
  --to FILE           diff mode: compare <file> (before) with FILE (after), mark removed/added lines
  --marks             lines starting with "+ " / "- " / "  " are diff marks (marker is stripped)
  --tab N             expand tabs to N spaces (default 2)
  --list-themes       print theme names
  --list-langs        print language names
  --json              print a JSON summary (paths, counts) instead of text
  -h, --help          this help

examples:
  showtime code src/app.ts -o code.json
  showtime code before.py --to after.py -o diff.json --theme vitesse-dark
`;

function parse(argv) {
  const a = { file: null, out: null, lang: null, theme: 'github-dark', to: null, marks: false, tab: 2, json: false };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    const v = () => { if (i + 1 >= argv.length) throw new Error(`${k} needs a value`); return argv[++i]; };
    if (k === '-h' || k === '--help') a.help = true;
    else if (k === '-o' || k === '--out') a.out = v();
    else if (k === '--lang') a.lang = v();
    else if (k === '--theme') a.theme = v();
    else if (k === '--to') a.to = v();
    else if (k === '--marks') a.marks = true;
    else if (k === '--tab') a.tab = parseInt(v(), 10) || 2;
    else if (k === '--list-themes') a.listThemes = true;
    else if (k === '--list-langs') a.listLangs = true;
    else if (k === '--json') a.json = true;
    else if (k.startsWith('-') && k !== '-') throw new Error(`unknown option ${k} (see --help)`);
    else if (!a.file) a.file = k;
    else throw new Error(`unexpected argument ${k}`);
  }
  return a;
}

const read = (f) => (f === '-' ? fs.readFileSync(0, 'utf8') : fs.readFileSync(f, 'utf8'));

/** Line diff by longest common subsequence: [{text, diff: ' '|'-'|'+'}]. */
export function lineDiff(a, b) {
  const A = a.split('\n'), B = b.split('\n');
  const n = A.length, m = B.length;
  const L = Array.from({ length: n + 1 }, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { out.push({ text: A[i], diff: ' ' }); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) out.push({ text: A[i++], diff: '-' });
    else out.push({ text: B[j++], diff: '+' });
  }
  while (i < n) out.push({ text: A[i++], diff: '-' });
  while (j < m) out.push({ text: B[j++], diff: '+' });
  return out;
}

async function main() {
  const a = parse(process.argv.slice(2));
  if (a.help) { console.log(HELP); return 0; }
  const shiki = await importDep('shiki');
  if (a.listThemes) { console.log(Object.keys(shiki.bundledThemes).join('\n')); return 0; }
  if (a.listLangs) { console.log(Object.keys(shiki.bundledLanguages).join('\n')); return 0; }
  if (!a.file) { console.error('showtime code: missing <file> (use - for stdin). See --help.'); return 2; }
  if (a.file !== '-' && !fs.existsSync(a.file)) { console.error(`showtime code: file not found: ${a.file}`); return 2; }
  if (!shiki.bundledThemes[a.theme]) { console.error(`showtime code: unknown theme "${a.theme}" (see --list-themes)`); return 2; }
  const lang = a.lang || EXT[path.extname(a.file === '-' ? '' : a.file).toLowerCase()] || (path.basename(a.file).toLowerCase() === 'dockerfile' ? 'dockerfile' : 'text');
  if (lang !== 'text' && !shiki.bundledLanguages[lang]) { console.error(`showtime code: unknown language "${lang}" (see --list-langs)`); return 2; }
  const tab = ' '.repeat(a.tab);
  const clean = (s) => s.replace(/\r\n?/g, '\n').replace(/\t/g, tab).replace(/\s+$/, '');
  let rows;
  if (a.to) {
    if (!fs.existsSync(a.to)) { console.error(`showtime code: file not found: ${a.to}`); return 2; }
    rows = lineDiff(clean(read(a.file)), clean(read(a.to)));
  } else if (a.marks) {
    rows = clean(read(a.file)).split('\n').map((l) => {
      const m = l.match(/^([+\- ]) ?(.*)$/);
      return m ? { text: m[2], diff: m[1] } : { text: l, diff: ' ' };
    });
  } else {
    rows = clean(read(a.file)).split('\n').map((text) => ({ text, diff: ' ' }));
  }
  const code = rows.map((r) => r.text).join('\n');
  const res = await shiki.codeToTokens(code, { lang: lang === 'text' ? 'text' : lang, theme: a.theme });
  const lines = res.tokens.map((toks, i) => {
    const line = { tokens: toks.map((t) => ({ c: t.content, color: t.color || res.fg, s: t.fontStyle || 0 })) };
    if (rows[i] && rows[i].diff !== ' ') line.diff = rows[i].diff;
    return line;
  });
  const doc = { version: 1, lang, theme: a.theme, fg: res.fg, bg: res.bg, lines };
  const text = JSON.stringify(doc);
  if (a.out) {
    fs.mkdirSync(path.dirname(path.resolve(a.out)), { recursive: true });
    fs.writeFileSync(a.out, text);
    const added = lines.filter((l) => l.diff === '+').length, removed = lines.filter((l) => l.diff === '-').length;
    if (a.json) console.log(JSON.stringify({ ok: true, out: path.resolve(a.out), lang, theme: a.theme, lines: lines.length, added, removed }));
    else console.log(`wrote ${path.resolve(a.out)}  (${lines.length} lines, ${lang}, ${a.theme}${a.to || a.marks ? `, +${added} -${removed}` : ''})`);
  } else {
    process.stdout.write(text + '\n');
  }
  return 0;
}

// exitCode, not process.exit(): exiting while shiki's handles are still closing aborts Node on Windows
// ("Assertion failed: !(handle->flags & UV_HANDLE_CLOSING), file src\win\async.c") with exit code -1
main().then((c) => { process.exitCode = c || 0; }).catch((e) => {
  console.error(`showtime code: ${e.message}${e.code === 'SHOWTIME_DEP_MISSING' ? '' : '\n  (run with SHOWTIME_DEBUG=1 for details)'}`);
  if (process.env.SHOWTIME_DEBUG) console.error(e.stack);
  process.exitCode = 1;
});

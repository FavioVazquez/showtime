// Small touches for a person at a terminal: the brand mark, a completion card, an opt-in sound.
// The Node twin of lib/st/delight.py (same rules, same look). All of it is decoration and steps aside by
// itself: nothing prints or plays unless the stream is an interactive terminal, and never with --json,
// NO_COLOR, TERM=dumb, CI, SHOWTIME_COLOR=never or SHOWTIME_PROGRESS=json.
import fs from 'node:fs';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { showtimeHome, skillDir } from './deps.mjs';

const VELVET = [0xB3, 0x12, 0x1F];   // shapes only: never text on a dark terminal
const GOLD = [0xE9, 0xB9, 0x49];
const PROGRAMME = [0xB6, 0xA7, 0x95];
const C256 = new Map([[VELVET, 124], [GOLD, 179], [PROGRAMME, 181]]);
const C16 = new Map([[VELVET, '31'], [GOLD, '33'], [PROGRAMME, '2']]);
const TRUECOLOR_APPS = new Set(['iTerm.app', 'WezTerm', 'vscode', 'ghostty', 'Hyper', 'Tabby', 'rio']);
const MARK_U = ['▐█▀▀▀█▌', '▐█', '▄▄▄', '█▌'];
const MARK_A = ['|"""""|', '|_', '===', '_|'];
export const LONG_JOB_MS = 20000;

const off = (v) => /^(0|false|no|off|never)$/i.test(String(v || '').trim());
const on = (v) => /^(1|true|yes|on)$/i.test(String(v || '').trim());

export function inCi(env = process.env) { return !!env.CI && !off(env.CI); }

/** True when decoration (mark, card, sound) may go to `stream` (default stdout). */
export function decorOk(stream = process.stdout, argv = process.argv.slice(2), env = process.env) {
  if (argv.includes('--json')) return false;
  if (env.NO_COLOR || env.TERM === 'dumb' || inCi(env)) return false;
  if (off(env.SHOWTIME_COLOR) || String(env.SHOWTIME_PROGRESS || '').toLowerCase() === 'json') return false;
  return !!(stream && stream.isTTY);   // libuv turns on VT handling for Windows consoles
}

export function colorDepth(env = process.env, platform = process.platform) {
  if (/^(truecolor|24bit)$/i.test(env.COLORTERM || '')) return 24;
  if (platform === 'win32' || env.WT_SESSION) return 24;
  if (TRUECOLOR_APPS.has(env.TERM_PROGRAM)) return 24;
  return /256/.test(env.TERM || '') ? 8 : 4;
}

/** Block glyphs are fine on Windows (UTF-16 console writes) and in UTF-8 locales; else ASCII. */
export function unicodeOk(env = process.env, platform = process.platform) {
  if (platform === 'win32') return true;
  const loc = env.LC_ALL || env.LC_CTYPE || env.LANG || '';
  return !loc || /utf-?8/i.test(loc);
}

const fg = (rgb, depth) => (depth >= 24 ? `38;2;${rgb.join(';')}` : depth >= 8 ? `38;5;${C256.get(rgb)}` : C16.get(rgb));
const sgr = (text, code, depth) => (depth && code ? `\x1b[${code}m${text}\x1b[0m` : String(text));

export function mark(depth = 24, unicode = true) {
  const [top, l, pool, r] = unicode ? MARK_U : MARK_A;
  const v = fg(VELVET, depth), g = fg(GOLD, depth);
  return [sgr(top, v, depth), sgr(l, v, depth) + sgr(pool, g, depth) + sgr(r, v, depth)];
}

export function displayPath(p, cwd = process.cwd()) {
  const ap = path.resolve(String(p));
  const rel = path.relative(cwd, ap);
  return !rel || rel.startsWith('..') || path.isAbsolute(rel) ? ap : rel;
}

/** A path ready to paste into a command: relative when inside the current folder, quoted when needed. */
export function shellPath(p) {
  const d = displayPath(p);
  return /[\s'&()]/.test(d) ? `"${d}"` : d;
}

/** The shell command that opens a file or folder with its default app. */
export function openHint(p, platform = process.platform) {
  const q = shellPath(p);
  if (platform === 'win32') return `start "" ${q.startsWith('"') ? q : `"${q}"`}`;
  return `${platform === 'darwin' ? 'open' : 'xdg-open'} ${q}`;
}

export function fmtLen(sec) {
  if (sec === null || sec === undefined || !isFinite(sec)) return null;
  if (sec < 60) return `${Number(sec).toFixed(1)} s`;
  const s = Math.round(sec), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  const p = (n) => String(n).padStart(2, '0');
  return h ? `${h}:${p(m)}:${p(r)}` : `${m}:${p(r)}`;
}

const QA_CODE = { PASS: '32', WARN: '33', FAIL: '31' };

/** The completion card (see lib/st/delight.py format_card). depth 0 = plain text. */
export function formatCard({ title, file, facts = [], next, qa, depth = 24, unicode = true, cwd } = {}) {
  const dot = unicode ? '·' : '-';
  const sep = `  ${sgr(dot, fg(PROGRAMME, depth), depth)}  `;
  const bits = [sgr(title, '1', depth), ...facts.filter(Boolean).map((f) => sgr(f, fg(PROGRAMME, depth), depth))];
  if (qa) { const v = String(qa).toUpperCase(); bits.push(`qa ${sgr(v, QA_CODE[v] || '', depth)}`); }
  const [m1, m2] = mark(depth, unicode);
  const lines = [`${m1}  ${bits.join(sep)}`, `${m2}  ${file ? displayPath(file, cwd) : ''}`];
  if (next) lines.push(`${' '.repeat(7)}  ${sgr('next', fg(GOLD, depth), depth)}  ${next}`);
  return lines.map((l) => l.trimEnd()).join('\n');
}

/** Print the card on stdout when decoration is on. */
export function showCard(opts) {
  if (!decorOk(process.stdout)) return false;
  try {
    process.stdout.write(`\n${formatCard({ ...opts, depth: colorDepth(), unicode: unicodeOk() })}\n`);
    return true;
  } catch { return false; }
}

// ---- opt-in sound logo ---------------------------------------------------------------------------

export const SOUND_FILE = path.join(skillDir(), 'lib', 'st', 'sounds', 'sound-logo-short.wav');

export function soundEnabled(env = process.env, argv = process.argv.slice(2)) {
  return on(env.SHOWTIME_SOUND) && decorOk(process.stdout, argv, env) && decorOk(process.stderr, argv, env);
}

function which(name) {
  const r = spawnSync(process.platform === 'win32' ? 'where' : 'which', [name], { encoding: 'utf8', windowsHide: true });
  return r.status === 0 ? String(r.stdout).split(/\r?\n/)[0].trim() || null : null;
}

export function playerCommand(file, platform = process.platform, find = which) {
  const ffArgs = ['-nodisp', '-autoexit', '-loglevel', 'quiet', file];
  const local = path.join(showtimeHome(), 'bin', platform === 'win32' ? 'ffplay.exe' : 'ffplay');
  if (fs.existsSync(local)) return [local, ...ffArgs];
  if (platform === 'darwin' && find('afplay')) return ['afplay', file];
  if (platform === 'win32') {
    const ps = find('powershell') || find('pwsh');
    if (ps) return [ps, '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', `(New-Object System.Media.SoundPlayer '${file.replace(/'/g, "''")}').PlaySync()`];
  }
  if (platform === 'linux') {
    for (const [n, a] of [['paplay', []], ['pw-play', []], ['aplay', ['-q']]]) { const e = find(n); if (e) return [e, ...a, file]; }
  }
  const ff = find('ffplay');
  return ff ? [ff, ...ffArgs] : null;
}

export function playSound(file = SOUND_FILE) {
  try {
    if (!fs.existsSync(file)) return false;
    const cmd = playerCommand(file);
    if (!cmd) return false;
    const ch = spawn(cmd[0], cmd.slice(1), { detached: true, stdio: 'ignore', windowsHide: true });
    ch.on('error', () => {});
    ch.unref();
    return true;
  } catch { return false; }
}

/** The short sound logo after a successful job longer than LONG_JOB_MS, when enabled. */
export function maybeChime(elapsedMs, ok = true) {
  if (!ok || elapsedMs < LONG_JOB_MS || !soundEnabled()) return false;
  return playSound();
}

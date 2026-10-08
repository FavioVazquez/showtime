// Shared command-line helpers for the node scripts (render, check, snap, preview, server).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { parseArgs } from 'node:util';
import { showtimeHome, skillDir } from './deps.mjs';
import { maybeChime } from './delight.mjs';
import { readQuestions, publicQuestions } from './questions.mjs';

export const IS_WIN = process.platform === 'win32';
const COLOR = process.stderr.isTTY && !process.env.NO_COLOR && process.env.TERM !== 'dumb';
const paint = (code) => (s) => (COLOR ? `\x1b[${code}m${s}\x1b[0m` : String(s));
export const c = { dim: paint('2'), bold: paint('1'), red: paint('31'), green: paint('32'), yellow: paint('33'), cyan: paint('36') };

let DEBUG = process.env.SHOWTIME_DEBUG === '1';
let CMD = 'showtime';
const T_START = Date.now();   // when this command started: a file changed after it was not the agent's (sinceLastLooked)

export class UserError extends Error {
  constructor(message, hint) { super(message); this.hint = hint; this.userError = true; }
}

/** Print an error with an optional fix line and exit(1). */
export function fail(message, hint, code = 1) {
  process.stderr.write(`${c.red(`${CMD}: error:`)} ${message}\n`);
  if (hint) process.stderr.write(`  ${c.bold('fix:')} ${hint}\n`);
  process.exit(code);
}

/**
 * Brief output (lean mode): a few lines per command (paths + verdict), details in a file. On by default
 * when nobody watches a terminal (agents, pipes, the MCP server); a terminal keeps the full report.
 * --verbose or SHOWTIME_OUTPUT=full forces the full report; SHOWTIME_OUTPUT=brief forces brief.
 */
export function briefOutput() {
  const mode = String(process.env.SHOWTIME_OUTPUT || '').toLowerCase();
  if (process.env.SHOWTIME_VERBOSE === '1' || mode === 'full' || mode === 'verbose') return false;
  if (mode === 'brief') return true;
  return process.env.SHOWTIME_MCP === '1' || !process.stdout.isTTY;
}

export function warn(message) { process.stderr.write(`${c.yellow(`${CMD}: warning:`)} ${message}\n`); }
export function info(message) { process.stderr.write(`${message}\n`); }

// ---- progress log -----------------------------------------------------------------------------
// Long commands append one JSON line per milestone (start, every 10%, output, end) to
// <SHOWTIME_HOME>/logs/progress.jsonl. The optional plugin monitor (mcp/progress-monitor.mjs) tails it so
// Claude hears about renders that run in the background. SHOWTIME_PROGRESS_LOG=0 turns it off.
const PLOG = { file: null, started: false, t0: 0, error: null };
const PLOG_MAX = 1024 * 1024;

function plogWrite(obj) {
  try {
    if (!PLOG.file) {
      const dir = path.join(showtimeHome(), 'logs');
      fs.mkdirSync(dir, { recursive: true });
      PLOG.file = path.join(dir, 'progress.jsonl');
      try { if (fs.statSync(PLOG.file).size > PLOG_MAX) fs.renameSync(PLOG.file, PLOG.file + '.1'); } catch { /* new file */ }
    }
    fs.appendFileSync(PLOG.file, JSON.stringify({ ts: Date.now(), pid: process.pid, cmd: CMD, cwd: process.cwd(), ...obj }) + '\n');
  } catch { /* never let the log break a command */ }
}

/** Record a progress milestone (the first call also records the start and, at exit, the end). */
export function progressLog(event) {
  if (/^(0|off|false|no)$/i.test(process.env.SHOWTIME_PROGRESS_LOG || '')) return;
  if (!PLOG.started) {
    PLOG.started = true;
    PLOG.t0 = Date.now();
    plogWrite({ ev: 'start' });
    process.once('exit', (code) => {
      const rc = typeof process.exitCode === 'number' ? process.exitCode : code;
      plogWrite({ ev: 'end', code: rc, seconds: Math.round((Date.now() - PLOG.t0) / 100) / 10, ...(PLOG.error && rc ? { error: PLOG.error } : {}) });
    });
  }
  plogWrite(event);
}

/** Run main() and turn exceptions into readable errors (stack only with --debug). */
export async function runMain(main) {
  const t0 = Date.now();
  try {
    const rc = await main();
    process.exitCode = typeof rc === 'number' ? rc : 0;
    maybeChime(Date.now() - t0, process.exitCode === 0);   // opt-in (SHOWTIME_SOUND=1), terminals only
  } catch (e) {
    if (DEBUG) process.stderr.write(`${e && e.stack ? e.stack : e}\n`);
    const msg = e && e.message ? e.message : String(e);
    PLOG.error = msg.split('\n')[0].slice(0, 300);
    process.stderr.write(`${c.red(`${CMD}: error:`)} ${msg}\n`);
    const hint = e && e.hint ? e.hint : hintFor(msg);
    if (hint) process.stderr.write(`  ${c.bold('fix:')} ${hint}\n`);
    if (!DEBUG) process.stderr.write(c.dim('  (run with --debug for details)\n'));
    process.exitCode = 1;
    // after an error the command is over: a crashed browser or a half-closed child must not keep it alive
    setTimeout(() => process.exit(1), 3000).unref();
  }
}

/** Known failure patterns -> one-line fixes. */
export function hintFor(msg) {
  const m = String(msg);
  if (/SHOWTIME_DEP_MISSING|is not installed in/.test(m)) return 'run `showtime setup`, then `showtime doctor`';
  if (/no Chrome, Edge or Chromium/.test(m)) return 'install Google Chrome, or run `showtime setup --with chromium`';
  if (/Target (page, context or browser )?(has been )?closed|browser has disconnected|Page crashed/i.test(m)) return 'the browser crashed; retry with fewer workers (--workers 1) or --gpu off';
  if (/no working ffmpeg|ffmpeg.*(not found|ENOENT)/i.test(m)) return 'run `showtime setup` to install ffmpeg into ~/.showtime/bin';
  if (/timed out/.test(m)) return 'something in the page never finished loading; run `showtime check <project>` to see what';
  if (/has no duration/.test(m)) return 'add "duration": <seconds> to showtime.json';
  return null;
}

/**
 * Parse argv with node:util parseArgs and handle --help / --debug.
 * spec: { name, usage, summary, options: {name: {type, short, default, help, multiple}}, examples: [], positionals: 'desc' }
 * Returns values plus `_` (positionals).
 * --help-json prints the spec itself (usage and options) and exits: lib/st/clispec.py reads the Node
 * commands' options that way, so the MCP tool schemas can be checked against them (tests/test_mcp.py).
 */
export function parseCli(spec, argv = process.argv.slice(2)) {
  CMD = `showtime ${spec.name}`;
  if (argv.includes('--help-json')) {
    const options = Object.fromEntries(Object.entries(spec.options || {}).map(([k, o]) => [k, {
      type: o.type || 'string', ...(o.short ? { short: o.short } : {}), ...(o.multiple ? { multiple: true } : {}), help: o.help || '' }]));
    process.stdout.write(JSON.stringify({ name: spec.name, usage: spec.usage, options }) + '\n');
    process.exit(0);
  }
  const options = { help: { type: 'boolean', short: 'h' }, debug: { type: 'boolean' }, verbose: { type: 'boolean' } };
  for (const [k, v] of Object.entries(spec.options || {})) {
    options[k] = { type: v.type || 'string' };
    if (v.short) options[k].short = v.short;
    if (v.multiple) options[k].multiple = true;
  }
  // allow negative numbers as values: `--lufs -16` -> `--lufs=-16`
  const shortMap = Object.fromEntries(Object.entries(options).filter(([, o]) => o.short).map(([k, o]) => [o.short, k]));
  const args = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i], nx = argv[i + 1];
    const name = a.startsWith('--') ? a.slice(2) : (/^-[A-Za-z]$/.test(a) ? shortMap[a[1]] : null);
    if (name && options[name] && options[name].type === 'string' && !a.includes('=') && nx !== undefined && /^-\d|^-\.\d/.test(nx)) {
      args.push(`--${name}=${nx}`); i++;
    } else args.push(a);
  }
  let parsed;
  try {
    parsed = parseArgs({ args, options, allowPositionals: true, strict: true });
  } catch (e) {
    const msg = String(e.message || e).replace(/\. To specify a positional argument.*$/s, '');
    process.stderr.write(`${c.red(`${CMD}: error:`)} ${msg}\n  ${c.bold('fix:')} run \`${CMD} --help\` for every option, with examples\n`);
    process.exit(2);
  }
  const v = parsed.values;
  if (v.debug) { DEBUG = true; process.env.SHOWTIME_DEBUG = '1'; }
  if (v.verbose) process.env.SHOWTIME_VERBOSE = '1';
  if (v.help) { printHelp(spec); process.exit(0); }
  for (const [k, o] of Object.entries(spec.options || {})) {
    if (v[k] === undefined && o.default !== undefined) v[k] = o.default;
  }
  v._ = parsed.positionals;
  return v;
}

export function printHelp(spec) {
  const out = [];
  out.push(`usage: ${spec.usage}`, '');
  if (spec.summary) out.push(spec.summary, '');
  if (spec.description) out.push(spec.description, '');
  const rows = [];
  for (const [k, o] of Object.entries(spec.options || {})) {
    const flag = (o.short ? `-${o.short}, ` : '    ') + `--${k}` + (o.type === 'boolean' ? '' : ` ${o.metavar || k.toUpperCase().replace(/-/g, '_')}`);
    rows.push([flag, o.help || '']);
  }
  rows.push(['-h, --help', 'show this help'], ['    --debug', 'show stack traces on errors']);
  if (spec.brief && !(spec.options || {}).verbose) rows.push(['    --verbose', 'full report on stdout (default when a terminal is attached; agents get a short summary)']);
  const w = Math.min(34, Math.max(...rows.map((r) => r[0].length)) + 2);
  out.push('options:');
  for (const [f, h] of rows) out.push(`  ${f.padEnd(w)}${h}`);
  if (spec.examples && spec.examples.length) {
    out.push('', 'examples:');
    for (const e of spec.examples) out.push(`  ${e}`);
  }
  if (spec.footer) out.push('', spec.footer);
  process.stdout.write(out.join('\n') + '\n');
}

/** Parse "1,2.5,00:03.2" -> [1, 2.5, 3.2] */
export function parseTimes(s) {
  if (s === undefined || s === null || s === '') return [];
  return String(s).split(',').map((x) => parseTime(x.trim())).filter((x) => x !== null);
}

/** "12", "12.5s", "1:02.5", "500ms" -> seconds */
export function parseTime(x) {
  const s = String(x).trim();
  if (!s) return null;
  let m;
  if ((m = /^(-?\d*\.?\d+)\s*ms$/i.exec(s))) return Number(m[1]) / 1000;
  if ((m = /^(-?\d*\.?\d+)\s*s?$/i.exec(s))) return Number(m[1]);
  if ((m = /^(\d+):(\d{1,2}(?:\.\d+)?)$/.exec(s))) return Number(m[1]) * 60 + Number(m[2]);
  if ((m = /^(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$/.exec(s))) return Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]);
  throw new UserError(`not a time: "${s}"`, 'use seconds (2.5), a suffix (500ms, 2s) or m:ss (1:02.5)');
}

export function fmtTime(sec) {
  if (!isFinite(sec)) return '?';
  const neg = sec < 0; sec = Math.abs(sec);
  const m = Math.floor(sec / 60), s = sec - m * 60;
  return `${neg ? '-' : ''}${m}:${s < 10 ? '0' : ''}${s.toFixed(2)}`;
}

export function fmtDuration(ms) {
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m${String(Math.round(s - m * 60)).padStart(2, '0')}s`;
}

export function fmtBytes(n) {
  if (!isFinite(n)) return '?';
  // decimal units (1 MB = 1,000,000 bytes), the unit platform upload limits use
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n >= 1000 && i < u.length - 1) { n /= 1000; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}

function readJSON(p) {
  // a UTF-8 byte-order mark (Windows PowerShell 5.1, some Windows editors) is not JSON: drop it
  const txt = fs.readFileSync(p, 'utf8').replace(/^\uFEFF/, '');
  try { return JSON.parse(txt); } catch (e) {
    throw new UserError(`${p} is not valid JSON: ${e.message}`, 'fix the syntax (trailing commas and comments are not allowed)');
  }
}

/**
 * Resolve a project argument: a folder with showtime.json/index.html, or an .html file.
 * -> { dir, page (URL path relative to dir, forward slashes), config, configPath, title, slug }
 */
export function resolveProject(arg, { page: pageOpt } = {}) {
  const p = path.resolve(arg || '.');
  if (!fs.existsSync(p)) throw new UserError(`project not found: ${p}`, 'pass a project folder (with showtime.json and index.html) or an .html file');
  let dir = p, page = pageOpt || 'index.html';
  if (fs.statSync(p).isFile()) {
    if (!/\.html?$/i.test(p)) throw new UserError(`not an HTML page: ${p}`, 'pass the project folder or its index.html');
    dir = path.dirname(p);
    page = path.basename(p);
  }
  page = page.replace(/\\/g, '/').replace(/^\/+/, '');
  if (!fs.existsSync(path.join(dir, page))) {
    throw new UserError(`${path.join(dir, page)} does not exist`, `create it, or start from a template: showtime new dom ${path.basename(dir)}`);
  }
  const configPath = path.join(dir, 'showtime.json');
  const config = fs.existsSync(configPath) ? readJSON(configPath) : {};
  if (typeof config !== 'object' || Array.isArray(config) || config === null) {
    throw new UserError(`${configPath} must contain a JSON object`);
  }
  for (const k of ['width', 'height', 'fps', 'duration']) {
    if (config[k] !== undefined && !(Number(config[k]) > 0)) throw new UserError(`showtime.json: "${k}" must be a positive number (got ${JSON.stringify(config[k])})`);
  }
  const title = config.title || path.basename(dir);
  // stop-and-ask questions: voice cues resolved to times here, so the stage (ST.questions), the
  // export and check all see the same seconds; `questions` keeps the issues for check and export
  const questions = readQuestions(dir, config, { fps: Number(config.fps) || 30 });
  const cfgOut = questions.off ? config : { ...config, questions: publicQuestions(questions.list) };
  return { dir, page, config: cfgOut, configPath: fs.existsSync(configPath) ? configPath : null, title, slug: slugify(title), questions };
}

export function slugify(s, max = 48) {
  const t = String(s).normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^A-Za-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '').toLowerCase().slice(0, max).replace(/-+$/, '');
  return t || 'video';
}

export function timestamp(d = new Date()) {
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

/** New job folder: <base>/showtime-out/<slug>-<timestamp>[-n]/ (base = $SHOWTIME_OUT or cwd). */
/**
 * Scratch folder name for a tool run: `base` (work/check, work/snap), or base-<page>[-<WxH>] for a page
 * other than index.html or a --size run, so two pages or sizes never overwrite each other's report.
 */
export function workName(base, page, size) {
  const name = page ? String(page).split(/[\\/]/).pop() : '';
  const stem = name && !/^index\.html?$/i.test(name) ? name.replace(/\.html?$/i, '').replace(/[^\w.-]+/g, '-') : '';
  const sz = size && size.width ? `${size.width}x${size.height}` : '';
  return [base, stem, sz].filter(Boolean).join('-');
}

export function jobDir(slug, base) {
  let root = path.resolve(base || process.env.SHOWTIME_OUT || process.cwd());
  if (path.basename(root) !== 'showtime-out') root = path.join(root, 'showtime-out');
  const stem = `${slug}-${timestamp()}`;
  fs.mkdirSync(root, { recursive: true });
  // claimed by an exclusive mkdir: two renders started in the same second never get the same folder
  for (let n = 1; ; n++) {
    const d = path.join(root, n === 1 ? stem : `${stem}-${n}`);
    try {
      fs.mkdirSync(d);
      return d;
    } catch (e) {
      if (e.code !== 'EEXIST') throw e;
    }
  }
}

/** A path that does not exist yet: foo.mp4, foo-2.mp4, ... */
export function freshPath(p) {
  if (!fs.existsSync(p)) return p;
  const ext = path.extname(p), base = p.slice(0, p.length - ext.length);
  let n = 2;
  while (fs.existsSync(`${base}-${n}${ext}`)) n++;
  return `${base}-${n}${ext}`;
}

/** The showtime venv python, or null. */
export function venvPython() {
  if (process.env.SHOWTIME_PYTHON && fs.existsSync(process.env.SHOWTIME_PYTHON)) return process.env.SHOWTIME_PYTHON;
  const v = path.join(showtimeHome(), 'venv');
  const p = IS_WIN ? path.join(v, 'Scripts', 'python.exe') : path.join(v, 'bin', 'python');
  return fs.existsSync(p) ? p : null;
}

/** Environment for child processes that call back into showtime's Python package. */
export function pyEnv() {
  const env = { ...process.env };
  const lib = path.join(skillDir(), 'lib');
  env.PYTHONPATH = lib + (env.PYTHONPATH ? path.delimiter + env.PYTHONPATH : '');
  env.SHOWTIME_HOME = showtimeHome();
  env.SHOWTIME_SKILL = skillDir();
  env.PYTHONUTF8 = '1';
  env.PYTHONIOENCODING = 'utf-8';
  const bin = path.join(showtimeHome(), 'bin');
  if (!(env.PATH || '').split(path.delimiter).includes(bin)) env.PATH = bin + path.delimiter + (env.PATH || '');
  return env;
}

/** Is a Python sub-command module present (e.g. 'audio' -> lib/st/cli_audio.py)? */
export function hasPyModule(rel) {
  return fs.existsSync(path.join(skillDir(), 'lib', 'st', ...rel.split('/')));
}

/**
 * Run `python -m st.cli <args>` (the showtime Python CLI).
 * -> { code, stdout, stderr }. Never throws for a non-zero exit.
 */
export function runPyCli(args, { timeout = 30 * 60 * 1000, cwd } = {}) {
  const py = venvPython();
  if (!py) return Promise.resolve({ code: 127, stdout: '', stderr: 'showtime venv not found (run `showtime setup`)' });
  // SHOWTIME_INTERNAL: a step of this command, not the agent's own (no "since you last looked" line of its own)
  return runProc(py, ['-m', 'st.cli', ...args], { env: { ...pyEnv(), SHOWTIME_INTERNAL: '1' }, timeout, cwd });
}

/**
 * "Since you last looked" for a job-scoped command (render, check, snap, look): what the person changed in the
 * job while the agent was away (files edited by hand, unread notes, new board events, open critic findings;
 * lib/st/job/catchup.py). -> {count, line, files, notes, board, findings} or null (nothing unseen, no job, or
 * it could not be read). It marks nothing seen: `showtime status <job>` does. Put it in a --json result as
 * "since_last_looked"; otherwise print it last with printSince (one line, never more).
 */
export async function sinceLastLooked(job) {
  if (!job || process.env.SHOWTIME_INTERNAL === '1' || /^(0|off|false|no)$/i.test(process.env.SHOWTIME_CATCHUP || '')) return null;
  try {
    const r = await runPyCli(['job', 'catchup', job, '--footer', '--json', '--started', (T_START / 1000).toFixed(3)], { timeout: 60000 });
    if (r.code !== 0) return null;
    const s = JSON.parse(r.stdout || 'null');
    return s && s.count ? s : null;
  } catch { return null; }
}
export function printSince(s) { if (s && s.line) process.stderr.write(`${s.line}\n`); }

/** Spawn with an argument list (no shell), capture output. */
export function runProc(cmd, args, { env, timeout = 0, cwd, onStderr, input } = {}) {
  return new Promise((resolve) => {
    let out = '', err = '', done = false, timer = null;
    let child;
    try {
      child = spawn(cmd, args, { env: env || process.env, cwd, windowsHide: true, stdio: [input ? 'pipe' : 'ignore', 'pipe', 'pipe'] });
    } catch (e) {
      return resolve({ code: 127, stdout: '', stderr: String(e.message || e) });
    }
    child.stdout.on('data', (d) => { out += d; if (out.length > 8e6) out = out.slice(-4e6); });
    child.stderr.on('data', (d) => { err += d; if (err.length > 4e6) err = err.slice(-2e6); if (onStderr) onStderr(String(d)); });
    if (input) { child.stdin.on('error', () => {}); child.stdin.end(input); }
    child.on('error', (e) => { if (!done) { done = true; clearTimeout(timer); resolve({ code: 127, stdout: out, stderr: err + String(e.message || e) }); } });
    child.on('close', (code, sig) => { if (!done) { done = true; clearTimeout(timer); resolve({ code: code === null ? 128 : code, signal: sig, stdout: out, stderr: err }); } });
    // on timeout: SIGTERM, then SIGKILL 5 s later (a deadlocked ffmpeg ignores SIGTERM: it waits for its own threads)
    if (timeout > 0) {
      timer = setTimeout(() => {
        err += `\n(timed out after ${timeout} ms)`;
        try { child.kill(); } catch { /* gone */ }
        const k = setTimeout(() => { if (!done) { try { child.kill('SIGKILL'); } catch { /* gone */ } } }, 5000);
        if (k.unref) k.unref();
      }, timeout);
    }
  });
}

/** Progress line: rewrites itself on a TTY; prints every ~10% otherwise. */
export class Progress {
  constructor(label, total, { quiet = false } = {}) {
    this.label = label; this.total = total; this.done = 0; this.t0 = Date.now();
    this.tty = process.stderr.isTTY; this.lastPrint = 0; this.lastPct = -1; this.quiet = quiet;
    this.etaNoted = false;
    this.logPct = -1;
    progressLog({ ev: 'progress', label, done: 0, total, pct: 0 });
  }
  // The rate is measured from the first tick, not from the start: an encoder's lookahead or a
  // browser's warm-up delays the first unit, and counting that wait made early ETAs several times too long.
  rate() {
    if (this.tFirst === undefined) return 0;
    const s = (Date.now() - this.tFirst) / 1000;
    return s > 0.5 ? (this.done - this.doneFirst) / s : 0;
  }
  tick(n = 1, extra = '') {
    if (this.tFirst === undefined) { this.tFirst = Date.now(); this.doneFirst = this.done + n; }
    this.done += n;
    const now = Date.now();
    const pct = Math.floor((100 * this.done) / Math.max(1, this.total));
    const r = this.rate();
    const eta = r > 0 ? (this.total - this.done) / r : NaN;
    if (pct >= this.logPct + 10 || (this.done >= this.total && this.logPct < 100)) {
      this.logPct = this.done >= this.total ? 100 : pct - (pct % 10);
      progressLog({ ev: 'progress', label: this.label, done: this.done, total: this.total, pct, ...(isFinite(eta) ? { eta_s: Math.round(eta) } : {}) });
    }
    if (this.quiet) return;
    // announce once, after enough work to be a real estimate (5 s and 8% done)
    if (!this.etaNoted && now - this.tFirst > 5000 && this.done >= 0.08 * this.total && isFinite(eta) && eta > 30) {
      this.etaNoted = true;
      this.clear();
      info(c.dim(`  estimated ${fmtDuration(eta * 1000)} left for ${this.label}`));
    }
    const line = `  ${this.label} ${this.done}/${this.total} ${String(pct).padStart(3)}%  ${r.toFixed(1)}/s  ETA ${isFinite(eta) ? fmtDuration(eta * 1000) : '?'}${extra ? '  ' + extra : ''}`;
    if (this.tty) {
      if (now - this.lastPrint > 100 || this.done >= this.total) {
        process.stderr.write(`\r\x1b[2K${line}`);
        this.lastPrint = now;
      }
    } else if (pct >= this.lastPct + this.step() || this.done >= this.total) {
      this.lastPct = pct - (pct % this.step());
      process.stderr.write(line + '\n');
    }
  }
  /** Without a terminal, a line every 10% (every 25% in brief output: agents read every line). */
  step() { return briefOutput() ? 25 : 10; }
  clear() { if (this.tty && !this.quiet) process.stderr.write('\r\x1b[2K'); }
  end() { if (this.tty && !this.quiet) process.stderr.write('\n'); }
}

export function cpuCount() {
  try { return os.availableParallelism ? os.availableParallelism() : os.cpus().length; } catch { return 2; }
}

/** Open a URL or file with the desktop's default handler (no shell strings). */
export function openDefault(target) {
  let cmd, args;
  if (process.platform === 'darwin') { cmd = 'open'; args = [target]; }
  else if (IS_WIN) { cmd = 'rundll32'; args = ['url.dll,FileProtocolHandler', target]; }
  else { cmd = 'xdg-open'; args = [target]; }
  try {
    const ch = spawn(cmd, args, { detached: true, stdio: 'ignore', windowsHide: true });
    ch.on('error', () => {});
    ch.unref();
    return true;
  } catch { return false; }
}

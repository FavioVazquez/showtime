// Open a project in the preview player (scrubber, frame step, loop, synced audio); live-reloads on save
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { startServer } from './server.mjs';
import { parseCli, runMain, resolveProject, info, warn, c, openDefault, UserError } from './lib/cli.mjs';
import { findSystemBrowsers } from './lib/chrome.mjs';
import { showtimeHome } from './lib/deps.mjs';
import { mixFromConfig, audioInputs } from './lib/audio.mjs';

const HERE = fileURLToPath(import.meta.url);

const SPEC = {
  name: 'preview',
  usage: 'showtime preview <project> [--port 4800] [--no-open] [--stop] [--status]',
  summary: 'Serve a project and open the preview player in Chrome (or the default browser).',
  description: [
    'The player shows the video at its real size (fit to the window) with a scrubber, play/pause (Space),',
    'frame stepping (Left/Right, Shift for 1 s), loop (L), mute (M), safe-zone guides (S) and clip markers.',
    'Audio: ST.score is rendered offline and played in sync; the showtime.json "audio" mix is built into',
    'work/mix.wav. Saving any project file reloads the page at the same time position.',
    'When the output is not a terminal (e.g. run by an agent), the server starts in the background and',
    'the command returns; stop it with --stop.',
  ].join('\n'),
  options: {
    port: { help: 'first port to try (default 4800)' },
    'no-open': { type: 'boolean', help: 'do not open a browser; just print the URL' },
    browser: { help: 'chrome (default: system Chrome/Edge in an app window) or default (the system default browser)' },
    detach: { type: 'boolean', help: 'run the server in the background and return' },
    foreground: { type: 'boolean', help: 'keep the server in this terminal until Ctrl+C' },
    stop: { type: 'boolean', help: 'stop the background preview server of this project' },
    status: { type: 'boolean', help: 'show whether a preview server is running for this project' },
    'no-audio': { type: 'boolean', help: 'do not build the showtime.json audio mix' },
    page: { help: 'page inside the project (default index.html)' },
    json: { type: 'boolean', help: 'print {url, pid, log} as JSON' },
  },
  examples: [
    'showtime preview my-video',
    'showtime preview my-video --no-open      # print the URL only',
    'showtime preview my-video --stop',
  ],
};

function sessionFile(root) {
  const h = crypto.createHash('sha256').update(path.resolve(root).toLowerCase()).digest('hex').slice(0, 16);
  const d = path.join(showtimeHome(), 'cache', 'preview');
  fs.mkdirSync(d, { recursive: true });
  return path.join(d, `${h}.json`);
}

function ping(url) {
  return new Promise((resolve) => {
    const req = http.get(`${url}/_st/ping`, { timeout: 800 }, (res) => {
      let body = '';
      res.on('data', (d) => { body += d; if (body.length > 4096) req.destroy(); });
      res.on('end', () => { try { resolve(JSON.parse(body)); } catch { resolve(null); } });
    });
    req.on('error', () => resolve(null));
    req.on('timeout', () => { req.destroy(); resolve(null); });
  });
}

async function running(root) {
  const f = sessionFile(root);
  if (!fs.existsSync(f)) return null;
  let rec;
  try { rec = JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return null; }
  const p = await ping(rec.url);
  if (p && p.app === 'showtime' && path.resolve(p.root) === path.resolve(root)) return rec;
  fs.rmSync(f, { force: true });
  return null;
}

function openBrowserWindow(url, which) {
  if (which !== 'default') {
    const b = findSystemBrowsers()[0];
    if (b) {
      const profile = path.join(showtimeHome(), 'cache', 'preview-profile');
      fs.mkdirSync(profile, { recursive: true });
      try {
        const ch = spawn(b.path, [`--app=${url}`, `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check',
          '--autoplay-policy=no-user-gesture-required', '--window-size=1440,960', '--disable-features=Translate'],
        { detached: true, stdio: 'ignore', windowsHide: false });
        ch.on('error', () => openDefault(url));
        ch.unref();
        return b.kind;
      } catch { /* fall through */ }
    }
  }
  return openDefault(url) ? 'default browser' : null;
}

/** Build <project>/work/mix.wav from showtime.json "audio" when missing or stale. */
async function ensureMix(proj, quiet) {
  const aud = proj.config.audio;
  if (aud === undefined || aud === null || aud === false || aud === '') return null;
  if (typeof aud === 'string' && /\.(wav|mp3|m4a|ogg|flac|aac)$/i.test(aud)) return null; // played directly
  const out = path.join(proj.dir, 'work', 'mix.wav');
  const inputs = [proj.configPath, ...audioInputs(aud, proj.dir)].filter(Boolean);
  const newest = Math.max(0, ...inputs.map((f) => { try { return fs.statSync(f).mtimeMs; } catch { return 0; } }));
  if (fs.existsSync(out) && fs.statSync(out).mtimeMs >= newest) return out;
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const tmpDir = path.join(proj.dir, 'work', 'preview-audio');
  fs.mkdirSync(tmpDir, { recursive: true });
  const dur = Number(proj.config.duration) || 0;
  if (!quiet) info(c.dim('  building the audio mix for the player...'));
  const r = await mixFromConfig(aud, proj.dir, dur, out, tmpDir, (m) => warn(m));
  return r ? out : null;
}

async function main() {
  const a = parseCli(SPEC);
  const proj = resolveProject(a._[0] || '.', { page: a.page });
  const rec = await running(proj.dir);

  if (a.status) {
    if (a.json) console.log(JSON.stringify(rec || { running: false }));
    else console.log(rec ? `running: ${rec.url}/_st/preview?page=/${proj.page} (pid ${rec.pid}, log ${rec.log})` : 'not running');
    return 0;
  }
  if (a.stop) {
    if (!rec) { console.log('no preview server is running for this project'); return 0; }
    try { process.kill(rec.pid); } catch (e) { warn(`could not stop pid ${rec.pid}: ${e.message}`); }
    fs.rmSync(sessionFile(proj.dir), { force: true });
    console.log(`stopped the preview server (pid ${rec.pid})`);
    return 0;
  }

  const playerUrl = (base) => `${base}/_st/preview?page=/${encodeURI(proj.page)}`;
  if (rec) {
    const url = playerUrl(rec.url);
    const how = a['no-open'] ? null : openBrowserWindow(url, a.browser);
    if (a.json) console.log(JSON.stringify({ url, pid: rec.pid, log: rec.log, reused: true }));
    else console.log(`preview already running: ${url}${how ? `  (opened in ${how})` : ''}\n  stop: showtime preview ${quote(proj.dir)} --stop`);
    return 0;
  }

  const background = a.detach || (!a.foreground && !process.stdout.isTTY);
  if (background) {
    const logFile = sessionFile(proj.dir).replace(/\.json$/, '.log');
    const fd = fs.openSync(logFile, 'a');
    const args = [HERE, proj.dir, '--foreground', '--no-open'];
    if (a.port) args.push('--port', String(a.port));
    if (a.page) args.push('--page', a.page);
    if (a['no-audio']) args.push('--no-audio');
    const ch = spawn(process.execPath, args, { detached: true, stdio: ['ignore', fd, fd], windowsHide: true, env: process.env });
    ch.unref();
    let r2 = null;
    const alive = () => { try { process.kill(ch.pid, 0); return true; } catch { return false; } };
    // the server first builds the audio mix for the player (20-60 s for a long mix): wait while the
    // process is alive, and never call a slow start a failure
    for (let i = 0; i < 400 && !r2; i++) {
      await new Promise((r) => setTimeout(r, 150));
      r2 = await running(proj.dir);
      if (!r2 && i > 20 && !alive()) break;
    }
    if (!r2 && alive()) {
      const msg = `the preview server is still starting (it builds the audio mix for the player first; pid ${ch.pid})`;
      if (a.json) console.log(JSON.stringify({ starting: true, pid: ch.pid, log: logFile }));
      else console.log(`${msg}\n  check: showtime preview ${quote(proj.dir)} --status   (log ${logFile})`);
      return 0;
    }
    if (!r2) throw new UserError(`the preview server did not start; see ${logFile}`);
    const url = playerUrl(r2.url);
    const how = a['no-open'] ? null : openBrowserWindow(url, a.browser);
    if (a.json) console.log(JSON.stringify({ url, pid: r2.pid, log: logFile }));
    else {
      console.log(`preview: ${url}${how ? `  (opened in ${how})` : ''}`);
      console.log(`  running in the background (pid ${r2.pid}); live reload on save`);
      console.log(`  stop:  showtime preview ${quote(proj.dir)} --stop`);
    }
    return 0;
  }

  // ---- foreground server
  if (!a['no-audio']) await ensureMix(proj, false).catch((e) => warn(`audio mix: ${e.message}`));
  let srv;
  const onChange = async (file) => {
    if (a['no-audio']) return false;
    if (file === 'showtime.json' || /\.(json|wav|mp3|m4a|ogg|flac|aac)$/i.test(file)) {
      try {
        const p2 = resolveProject(proj.dir, { page: a.page });
        const out = await ensureMix(p2, true);
        if (out && srv) srv.notify('work/mix.wav');
      } catch (e) { warn(`audio mix: ${e.message}`); }
    }
    return false;
  };
  srv = await startServer({ root: proj.dir, port: Number(a.port || 4800), watch: true, onChange, log: (l) => info(c.dim(`  ${l}`)) });
  fs.writeFileSync(sessionFile(proj.dir), JSON.stringify({ pid: process.pid, url: srv.url, port: srv.port, root: proj.dir,
    log: sessionFile(proj.dir).replace(/\.json$/, '.log'), started: new Date().toISOString() }));
  const url = playerUrl(srv.url);
  const how = a['no-open'] ? null : openBrowserWindow(url, a.browser);
  console.log(`preview: ${url}${how ? `  (opened in ${how})` : ''}`);
  console.log('  live reload on save; press Ctrl+C to stop');
  const stop = () => {
    try { fs.rmSync(sessionFile(proj.dir), { force: true }); } catch { /* ignore */ }
    srv.close().finally(() => process.exit(0));
  };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
  if (process.platform === 'win32') process.on('SIGBREAK', stop);
  return new Promise(() => {}); // run until stopped
}

function quote(p) { return /[\s'"]/.test(p) ? JSON.stringify(p) : p; }

runMain(main);

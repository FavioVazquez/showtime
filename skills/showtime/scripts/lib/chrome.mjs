// Launch a Chromium-family browser for deterministic capture.
//
//   import { launchBrowser } from './lib/chrome.mjs';
//   const { browser, executablePath, kind, flags } = await launchBrowser({ gpu: 'auto', headless: true });
//
// Preference order: $SHOWTIME_CHROME / $CHROME_PATH, system Google Chrome, Microsoft Edge,
// Chromium (major version >= MIN_CHROME_MAJOR; SHOWTIME_SYSTEM_BROWSER=0 skips them), then the
// Chrome Headless Shell showtime setup installs when no browser is found (headless runs), then a
// Playwright-managed full Chromium in ~/.showtime/browsers. When none of them can start, the
// headless shell (or, for --headed, full Chromium) is fetched once through `showtime setup --fetch`,
// announced with its size, and the launch is retried.
// Flags come from chrome-flags.json (shared with lib/st/platform.py):
//   gpu 'auto'|'on'  -> per-OS hardware path (ANGLE Metal on macOS, D3D11 on Windows,
//                       default GL with a SwiftShader fallback on Linux)
//   gpu 'off'|'software' -> SwiftShader (slower; most reproducible across machines)
//
// Run directly for a self-test:  node chrome.mjs --probe [--gpu auto|off] [--prefer playwright]
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { importDep, showtimeHome } from './deps.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FLAGS = JSON.parse(fs.readFileSync(path.join(HERE, 'chrome-flags.json'), 'utf8'));

export function osName() {
  if (process.platform === 'darwin') return 'mac';
  if (process.platform === 'win32') return 'windows';
  return 'linux';
}

/** Extra flags for `showtime render`'s browsers only (chrome-flags.json "render"). */
export function renderFlags() {
  return Array.isArray(FLAGS.render) ? [...FLAGS.render] : [];
}

/** Launch flags for the given GPU mode on this OS. */
export function chromeFlags(gpu = 'auto', os_ = osName()) {
  const software = ['off', 'software', 'swiftshader', false].includes(gpu);
  return [...FLAGS.common, ...(software ? FLAGS.software : (FLAGS.gpu[os_] || []))];
}

function isFile(p) {
  try { return fs.statSync(p).isFile(); } catch { return false; }
}

function which(name) {
  const exts = process.platform === 'win32' ? (process.env.PATHEXT || '.EXE').split(';') : [''];
  for (const dir of (process.env.PATH || '').split(path.delimiter)) {
    if (!dir) continue;
    for (const ext of exts) {
      const p = path.join(dir, name + ext.toLowerCase());
      if (isFile(p)) return p;
      const q = path.join(dir, name + ext);
      if (isFile(q)) return q;
    }
  }
  return null;
}

function systemCandidates() {
  const o = osName();
  const out = [];
  if (o === 'mac') {
    const apps = [
      ['chrome', 'Google Chrome.app/Contents/MacOS/Google Chrome'],
      ['chrome', 'Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta'],
      ['chrome', 'Google Chrome Dev.app/Contents/MacOS/Google Chrome Dev'],
      ['chrome', 'Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary'],
      ['edge', 'Microsoft Edge.app/Contents/MacOS/Microsoft Edge'],
      ['chromium', 'Chromium.app/Contents/MacOS/Chromium'],
      ['chrome-for-testing', 'Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'],
    ];
    for (const root of ['/Applications', path.join(os.homedir(), 'Applications')]) {
      for (const [kind, rel] of apps) out.push([kind, path.join(root, rel)]);
    }
  } else if (o === 'windows') {
    const roots = ['PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA', 'PROGRAMW6432']
      .map((v) => process.env[v]).filter(Boolean);
    const rels = [
      ['chrome', 'Google/Chrome/Application/chrome.exe'],
      ['chrome', 'Google/Chrome Beta/Application/chrome.exe'],
      ['chrome', 'Google/Chrome SxS/Application/chrome.exe'],
      ['edge', 'Microsoft/Edge/Application/msedge.exe'],
      ['chromium', 'Chromium/Application/chrome.exe'],
    ];
    for (const [kind, rel] of rels) for (const root of roots) out.push([kind, path.join(root, rel)]);
  } else {
    for (const [kind, name] of [['chrome', 'google-chrome-stable'], ['chrome', 'google-chrome'],
      ['chromium', 'chromium'], ['chromium', 'chromium-browser'],
      ['edge', 'microsoft-edge-stable'], ['edge', 'microsoft-edge']]) {
      const p = which(name);
      if (p) out.push([kind, p]);
    }
    out.push(['chrome', '/opt/google/chrome/chrome'], ['edge', '/opt/microsoft/msedge/msedge'],
      ['chromium', '/usr/lib/chromium/chromium'], ['chromium', '/snap/bin/chromium']);
  }
  return out;
}

// An installed browser older than this is skipped (rendering and CDP features differ too much).
export const MIN_CHROME_MAJOR = 120;

const systemAllowed = () => !['0', 'false', 'no', 'off'].includes(String(process.env.SHOWTIME_SYSTEM_BROWSER || '1').toLowerCase());

function browsersDir() {
  const env = process.env.PLAYWRIGHT_BROWSERS_PATH;
  return env && env !== '0' ? env : path.join(showtimeHome(), 'browsers');
}

/** Chrome Headless Shell installed by showtime setup (newest revision), or null. */
export function findHeadlessShell(dir = browsersDir()) {
  let best = null;
  let bestRev = -1;
  let entries = [];
  try { entries = fs.readdirSync(dir); } catch { return null; }
  for (const d of entries) {
    const m = /^chromium_headless_shell-(\d+)$/.exec(d);
    if (!m) continue;
    let subs = [];
    try { subs = fs.readdirSync(path.join(dir, d)); } catch { continue; }
    for (const sub of subs) {
      if (!sub.startsWith('chrome-headless-shell-')) continue;
      for (const exe of ['chrome-headless-shell', 'chrome-headless-shell.exe']) {
        const p = path.join(dir, d, sub, exe);
        if (isFile(p) && Number(m[1]) > bestRev) { best = p; bestRev = Number(m[1]); }
      }
    }
  }
  return best;
}

/** Fetch a browser through the installer (resumable, sha256-verified for the headless shell). */
function fetchBrowser(name) {
  const py = process.env.SHOWTIME_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const setupPy = path.join(HERE, '..', '..', 'setup', 'setup.py');
  process.stderr.write(`showtime: fetching ${name === 'chromium' ? 'Chromium (full browser, ~190-205 MB)' : 'Chrome Headless Shell (~100-120 MB)'} ` +
    'for rendering (one time; `showtime setup --plan` lists it)\n');
  const r = spawnSync(py, [setupPy, '--fetch', name], { stdio: ['ignore', 2, 2], windowsHide: true, env: process.env });
  return r.status === 0;
}

/** System browsers found on this machine, best first: [{kind, path, source}] */
export function findSystemBrowsers() {
  const seen = new Set();
  const res = [];
  const add = (kind, p, source) => {
    if (!p || !isFile(p)) return;
    let key = p;
    try { key = fs.realpathSync(p); } catch { /* keep */ }
    if (seen.has(key)) return;
    seen.add(key);
    res.push({ kind, path: p, source });
  };
  const env = process.env.SHOWTIME_CHROME || process.env.CHROME_PATH;
  if (env) add('custom', env, 'env');
  const cands = systemAllowed() ? systemCandidates() : [];
  for (const kind of ['chrome', 'edge', 'chromium', 'chrome-for-testing']) {
    for (const [k, p] of cands) if (k === kind) add(k, p, 'system');
  }
  return res;
}

async function playwright() {
  if (!process.env.PLAYWRIGHT_BROWSERS_PATH) {
    process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(showtimeHome(), 'browsers');
  }
  return importDep('playwright');
}

/**
 * Launch a browser.
 * @param {object} [o]
 * @param {'auto'|'on'|'off'|'software'} [o.gpu='auto']
 * @param {boolean} [o.headless=true]
 * @param {string} [o.executablePath]  force a specific browser binary
 * @param {'system'|'playwright'} [o.prefer='system']
 * @param {string[]} [o.args]          extra flags
 * @param {number} [o.timeout=60000]
 * @param {boolean} [o.ownSignals=false]  the caller handles SIGINT/SIGTERM and closes the browser itself
 * @returns {Promise<{browser, executablePath, kind, flags, version}>}
 */
export async function launchBrowser(o = {}) {
  const { gpu = 'auto', headless = true, prefer = 'system', args = [], timeout = 60000, ownSignals = false } = o;
  const { chromium } = await playwright();
  const flags = [...chromeFlags(gpu), ...args];
  const bundledCandidates = () => {
    const out = [];
    // SHOWTIME_HEADLESS_SHELL=0: skip the shell (it rasterizes small text edges slightly differently from
    // full Chrome: PSNR 37-45 dB on text-heavy frames, identical elsewhere; see references/render.md)
    const useShell = headless && !['0', 'false', 'no', 'off'].includes(String(process.env.SHOWTIME_HEADLESS_SHELL || '1').toLowerCase());
    const shell = useShell ? findHeadlessShell() : null;
    if (shell) out.push({ kind: 'headless-shell', path: shell, source: 'showtime' });
    try {
      const p = chromium.executablePath();
      if (isFile(p)) out.push({ kind: 'playwright', path: null, source: 'playwright', resolved: p });
    } catch { /* not installed */ }
    return out;
  };
  const system = o.executablePath ? [{ kind: 'custom', path: o.executablePath, source: 'option' }] : findSystemBrowsers();
  const errors = [];
  const tried = new Set();
  const attempt = async (order) => {
    for (const cand of order) {
      const id = cand.path || cand.resolved;
      if (tried.has(id)) continue;
      tried.add(id);
      let browser = null;
      try {
        browser = await chromium.launch({
          headless,
          // Full bundled Chromium: channel 'chromium' = new-headless mode (same code path as system
          // Chrome). The headless shell and system browsers are launched by path.
          ...(cand.path ? { executablePath: cand.path } : { channel: 'chromium' }),
          args: flags,
          // ownSignals: the caller handles Ctrl-C and SIGTERM (render removes its frames first); Playwright's own
          // handlers would close the browser and exit at once
          ...(ownSignals ? { handleSIGINT: false, handleSIGTERM: false } : {}),
          timeout,
        });
        const version = browser.version();
        const major = Number(String(version).split('.')[0]);
        if (cand.source === 'system' && major && major < MIN_CHROME_MAJOR) {
          await browser.close().catch(() => {});
          errors.push(`${cand.kind} ${version} (${id}): older than ${MIN_CHROME_MAJOR}, skipped`);
          continue;
        }
        return { browser, executablePath: id, kind: cand.kind, flags, version };
      } catch (err) {
        if (browser) await browser.close().catch(() => {});
        errors.push(`${cand.kind} (${id}): ${String(err.message || err).split('\n')[0]}`);
      }
    }
    return null;
  };
  let order = o.executablePath ? system : (prefer === 'playwright' ? [...bundledCandidates(), ...system] : [...system, ...bundledCandidates()]);
  let res = await attempt(order);
  if (res) return res;
  if (!o.executablePath) {
    // Nothing usable yet: fetch the headless shell (or full Chromium for a headed run, or when the shell is
    // here but cannot start, or is switched off) once, then retry.
    const shellOff = ['0', 'false', 'no', 'off'].includes(String(process.env.SHOWTIME_HEADLESS_SHELL || '1').toLowerCase());
    const want = headless && !shellOff && !findHeadlessShell() ? 'chromium-headless-shell' : 'chromium';
    const offline = !['', '0', 'false', 'no'].includes(String(process.env.SHOWTIME_OFFLINE || '').toLowerCase());
    if (!offline && fetchBrowser(want)) {
      res = await attempt(bundledCandidates());
      if (res) return res;
    } else if (offline) {
      errors.push(`${want} is not installed and showtime is offline (run \`showtime setup --full\` on a connected machine, or \`showtime setup --seed DIR --fetch ${want}\`)`);
    }
  }
  if (!errors.length) {
    throw new Error('showtime: no Chrome, Edge or Chromium found.\n' +
      '  Install Google Chrome, or run: showtime setup   (installs the Chrome Headless Shell)');
  }
  throw new Error('showtime: could not launch a browser:\n  ' + errors.join('\n  ') +
    (osName() === 'linux' ? '\n  hint: missing system libraries? run: sudo npx playwright install-deps chromium' : ''));
}

/** Launch, render a small WebGL + text page, screenshot it, report details. */
export async function probe(o = {}) {
  const t0 = Date.now();
  const { browser, executablePath, kind, version } = await launchBrowser(o);
  try {
    const page = await browser.newPage({ viewport: { width: 320, height: 180 }, deviceScaleFactor: 1 });
    await page.setContent(`<!doctype html><html><body style="margin:0;background:#123">
      <canvas id="c" width="320" height="180"></canvas>
      <script>
        const gl = document.getElementById('c').getContext('webgl');
        let renderer = 'none';
        if (gl) {
          const ext = gl.getExtension('WEBGL_debug_renderer_info');
          renderer = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
          gl.clearColor(0.9, 0.3, 0.1, 1); gl.clear(gl.COLOR_BUFFER_BIT);
        }
        window.__probe = { renderer, webgl: !!gl };
      </script></body></html>`);
    const info = await page.evaluate(() => window.__probe);
    const cdp = await page.context().newCDPSession(page);
    const shot = await cdp.send('Page.captureScreenshot', { format: 'jpeg', quality: 80 });
    return {
      ok: true, kind, executablePath, version,
      webgl: info.webgl, renderer: info.renderer,
      screenshotBytes: Buffer.from(shot.data, 'base64').length,
      ms: Date.now() - t0,
      gpu: o.gpu || 'auto',
    };
  } finally {
    await browser.close();
  }
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const argv = process.argv.slice(2);
  const opt = (name, def) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : def; };
  if (argv.includes('--help') || argv.includes('-h')) {
    console.log('usage: node chrome.mjs [--list] [--probe] [--gpu auto|off] [--prefer system|playwright] [--headed]');
    process.exit(0);
  }
  if (argv.includes('--list')) {
    console.log(JSON.stringify(findSystemBrowsers(), null, 2));
    process.exit(0);
  }
  probe({ gpu: opt('--gpu', 'auto'), prefer: opt('--prefer', 'system'), headless: !argv.includes('--headed') })
    .then((r) => { console.log(JSON.stringify(r)); })
    .catch((e) => { console.log(JSON.stringify({ ok: false, error: String(e.message || e) })); process.exit(1); });
}

#!/usr/bin/env node
// Load a single-file HTML deliverable in headless Chrome with the network blocked and report what it does.
//
//   node benchmarks/scoring/html_probe.mjs <file.html> <out-dir>
//
// Needs Playwright: BENCH_PLAYWRIGHT_DIR (a node_modules folder that contains playwright), else the one
// showtime's setup installs (<showtime home>/node/node_modules). Chrome: BENCH_CHROME, else the usual
// install locations. Prints JSON: requests the page attempted (any non-file URL counts as a network
// request; any other local file counts as "not single file"), console errors, media elements, whether
// pixels change after pressing play, phone-width overflow, and screenshots for the judges.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const [file, outDir] = process.argv.slice(2);
if (!file || !outDir) {
  console.error('usage: html_probe.mjs <file.html> <out-dir>');
  process.exit(2);
}
fs.mkdirSync(outDir, { recursive: true });
const home = process.env.SHOWTIME_HOME || path.join(os.homedir(), '.showtime');
const pwDir = process.env.BENCH_PLAYWRIGHT_DIR || path.join(home, 'node', 'node_modules');
const require = createRequire(path.join(pwDir, 'noop.js'));
const { chromium } = require('playwright');

function findChrome() {
  if (process.env.BENCH_CHROME) return process.env.BENCH_CHROME;
  const c = {
    darwin: ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Chromium.app/Contents/MacOS/Chromium'],
    linux: ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'],
    win32: [path.join(process.env.PROGRAMFILES || 'C:\\Program Files', 'Google/Chrome/Application/chrome.exe')],
  }[process.platform] || [];
  return c.find((p) => fs.existsSync(p));
}

const abs = path.resolve(file);
const selfUrl = pathToFileURL(abs).href;
const report = { file: path.basename(abs), bytes: fs.statSync(abs).size, network_requests: [], local_refs: [],
  console_errors: [], page_errors: [], media: {}, animates: false, played_via: null, phone_overflow: null, shots: [] };

const browser = await chromium.launch({ executablePath: findChrome(), headless: true });
try {
  for (const vp of [{ name: 'desktop', width: 1280, height: 720 }, { name: 'phone', width: 390, height: 844 }]) {
    const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    await ctx.route('**/*', (route) => {
      const u = route.request().url();
      if (u === selfUrl || u.startsWith('data:') || u.startsWith('blob:')) return route.continue();
      if (u.startsWith('file:')) { if (vp.name === 'desktop') report.local_refs.push(u.slice(0, 200)); return route.abort(); }
      if (vp.name === 'desktop') report.network_requests.push(u.slice(0, 200));
      return route.abort();
    });
    if (vp.name === 'desktop') {
      page.on('console', (m) => { if (m.type() === 'error') report.console_errors.push(m.text().slice(0, 300)); });
      page.on('pageerror', (e) => report.page_errors.push(String(e).slice(0, 300)));
    }
    await page.goto(selfUrl, { waitUntil: 'load', timeout: 30000 }).catch((e) => report.page_errors.push('load: ' + e.message.slice(0, 200)));
    await page.waitForTimeout(800);
    if (vp.name === 'phone') {
      report.phone_overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      const p = path.join(outDir, 'phone.png');
      await page.screenshot({ path: p });
      report.shots.push('phone.png');
      await ctx.close();
      continue;
    }
    report.media = await page.evaluate(() => ({
      video: document.querySelectorAll('video').length,
      audio: document.querySelectorAll('audio').length,
      canvas: document.querySelectorAll('canvas').length,
      svg: document.querySelectorAll('svg').length,
      animations: document.getAnimations ? document.getAnimations().length : null,
      buttons: [...document.querySelectorAll('button,[role=button]')].map((b) => (b.getAttribute('aria-label') || b.title || b.textContent || '').trim().slice(0, 40)).filter(Boolean).slice(0, 20),
      range_inputs: document.querySelectorAll('input[type=range],[role=slider]').length,
      title: document.title,
    }));
    const a = await page.screenshot();
    fs.writeFileSync(path.join(outDir, 'desktop-0.png'), a);
    report.shots.push('desktop-0.png');
    // Try to start playback the way a person would: a play control, else Space, else a click in the middle.
    const play = page.locator('button, [role=button]').filter({ hasText: /play|start|watch|▶/i }).first();
    const aria = page.locator('[aria-label*="play" i], [title*="play" i]').first();
    if (await aria.count()) { await aria.click({ timeout: 2000 }).catch(() => {}); report.played_via = 'aria-label'; }
    else if (await play.count()) { await play.click({ timeout: 2000 }).catch(() => {}); report.played_via = 'button'; }
    else { await page.keyboard.press('Space'); report.played_via = 'space'; }
    for (const t of [1500, 3000, 6000]) {
      await page.waitForTimeout(t === 1500 ? 1500 : t === 3000 ? 1500 : 3000);
      const b = await page.screenshot();
      const name = `desktop-${t / 1000}s.png`;
      fs.writeFileSync(path.join(outDir, name), b);
      report.shots.push(name);
      if (Buffer.compare(a, b) !== 0) report.animates = true;
    }
    await ctx.close();
  }
} finally {
  await browser.close();
}
report.single_file = report.local_refs.length === 0;
report.offline = report.network_requests.length === 0;
fs.writeFileSync(path.join(outDir, 'html_probe.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report));

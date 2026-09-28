#!/usr/bin/env node
// Screen-record a single-file HTML video deliverable as an MP4, the same way for every candidate.
//
//   node benchmarks/scoring/html_record.mjs <file.html> <out.mp4> [--width 1920] [--height 1080] [--cap 60] [--ceiling 180]
//
// Used by human_board.py so HTML deliverables can sit on a blind board next to each other. The procedure
// is identical for every page and does not depend on how the page was built:
//   1. headless Chrome, fixed viewport (default 1920x1080, DPR 1), network blocked (as html_probe.mjs);
//   2. wait 1 s, then start playback the way a person would: a control labelled play (aria-label/title),
//      else a button whose text says play/start/watch, else Space; if the page has a <video>/<audio>
//      element and none is playing after that, the largest visible <video> (else the first <audio>) is
//      started as if its own play control were pressed, and scrolled into view;
//   3. length: the longest playing media element's duration, else a seek slider's max (a range input or
//      role=slider labelled position/seek/progress/time/timeline/scrub), else --cap seconds; never more
//      than --ceiling seconds; recording stops 1 s after a media element ends;
//   4. picture, from 0.5 s before play to 1 s after the end, 30 fps: on Linux with Xvfb, a headed Chrome
//      window on a private virtual display grabbed by ffmpeg (x11grab; the page renders as if nobody were
//      recording); elsewhere headless Chrome's CDP screencast (every painted frame, wall-clock timestamps);
//      the backend depends only on the machine, never on the page;
//   5. sound: an in-page tap installed before any page script copies what the page sends to its speakers
//      (every <audio>/<video> element through captureStream() at its own volume/mute, and every Web Audio
//      graph connected to its destination) into one MediaRecorder; aligned by wall clock.
// Prints JSON: {ok, backend, duration, duration_source, played_via, audio: {sources, captured, max_volume_db}, why?}
// Needs Playwright (BENCH_PLAYWRIGHT_DIR, else <showtime home>/node/node_modules) and Chrome (BENCH_CHROME),
// ffmpeg (BENCH_FFMPEG, else <showtime home>/bin/ffmpeg, else PATH).
import { createRequire } from 'node:module';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const argv = process.argv.slice(2);
const pos = [];
const opt = { width: 1920, height: 1080, cap: 60, ceiling: 180 };
for (let i = 0; i < argv.length; i++) {
  if (argv[i].startsWith('--')) opt[argv[i].slice(2)] = Number(argv[++i]);
  else pos.push(argv[i]);
}
const [file, outFile] = pos;
if (!file || !outFile) {
  console.error('usage: html_record.mjs <file.html> <out.mp4> [--width W --height H --cap S --ceiling S]');
  process.exit(2);
}
const home = process.env.SHOWTIME_HOME || path.join(os.homedir(), '.showtime');
const pwDir = process.env.BENCH_PLAYWRIGHT_DIR || path.join(home, 'node', 'node_modules');
const require = createRequire(path.join(pwDir, 'noop.js'));
const { chromium } = require('playwright');
const exe = process.platform === 'win32' ? '.exe' : '';
const FFMPEG = process.env.BENCH_FFMPEG || [path.join(home, 'bin', 'ffmpeg' + exe)].find((p) => fs.existsSync(p)) || 'ffmpeg';

function findChrome() {
  if (process.env.BENCH_CHROME) return process.env.BENCH_CHROME;
  const c = {
    darwin: ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Chromium.app/Contents/MacOS/Chromium'],
    linux: ['/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser'],
    win32: [path.join(process.env.PROGRAMFILES || 'C:\\Program Files', 'Google/Chrome/Application/chrome.exe')],
  }[process.platform] || [];
  return c.find((p) => fs.existsSync(p));
}

// Runs in the page before any page script. Never changes what the page plays or how loud: it only adds
// a copy of each sound path into a private mixer that is recorded.
const TAP = `(() => {
  if (window.top !== window || window.__benchTap) return;
  const T = window.__benchTap = { sources: 0, chunks: [], mix: null, dest: null, rec: null, pending: [] };
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC || !window.MediaRecorder) return;
  const origConnect = AudioNode.prototype.connect;
  const mixer = () => {
    if (!T.mix) { T.mix = new AC(); T.dest = T.mix.createMediaStreamDestination(); }
    return T.mix;
  };
  const addStream = (stream, gainFn) => {
    try {
      const m = mixer();
      const src = m.createMediaStreamSource(stream);
      const g = m.createGain();
      g.gain.value = gainFn ? gainFn() : 1;
      origConnect.call(src, g); origConnect.call(g, T.dest);
      T.sources++;
      return g;
    } catch (e) { T.errors = (T.errors || []).concat(String(e).slice(0, 120)); return null; }
  };
  const taps = new WeakMap();
  AudioNode.prototype.connect = function (dst, ...rest) {
    const r = origConnect.call(this, dst, ...rest);
    try {
      if (dst instanceof AudioDestinationNode && dst.context !== T.mix && typeof dst.context.createMediaStreamDestination === 'function') {
        let tap = taps.get(dst.context);
        if (!tap) { tap = dst.context.createMediaStreamDestination(); taps.set(dst.context, tap); addStream(tap.stream); }
        origConnect.call(this, tap);
      }
    } catch (e) { /* the page's own connect already happened */ }
    return r;
  };
  const routed = new WeakSet();
  const gains = new WeakMap();
  const level = (el) => (routed.has(el) || el.muted ? 0 : el.volume);
  const origMES = AC.prototype.createMediaElementSource;
  if (origMES) AC.prototype.createMediaElementSource = function (el) {
    routed.add(el);  // its sound now reaches the speakers through the Web Audio graph (tapped above)
    const g = gains.get(el); if (g) g.gain.value = 0;
    return origMES.call(this, el);
  };
  document.addEventListener('play', (ev) => {
    const el = ev.target;
    if (!(el instanceof HTMLMediaElement) || gains.has(el)) return;
    let stream = null;
    try { stream = el.captureStream ? el.captureStream() : null; } catch (e) { T.errors = (T.errors || []).concat(String(e).slice(0, 120)); }
    if (!stream) return;
    const hook = () => {
      if (gains.has(el) || !stream.getAudioTracks().length) return;
      const g = addStream(stream, () => level(el));
      if (g) { gains.set(el, g); el.addEventListener('volumechange', () => { g.gain.value = level(el); }); }
    };
    hook();
    stream.addEventListener('addtrack', hook);
  }, true);
  T.start = async () => {
    const m = mixer();
    try { await m.resume(); } catch (e) {}
    T.rec = new MediaRecorder(T.dest.stream, { mimeType: 'audio/webm;codecs=opus', audioBitsPerSecond: 192000 });
    T.rec.ondataavailable = (e) => { if (e.data && e.data.size) T.chunks.push(e.data); };
    T.rec.start(250);
    return Date.now();
  };
  T.stop = () => new Promise((res) => {
    if (!T.rec || T.rec.state === 'inactive') return res('');
    T.rec.onstop = async () => {
      const b = new Blob(T.chunks, { type: 'audio/webm' });
      const u8 = new Uint8Array(await b.arrayBuffer());
      let s = ''; for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
      res(btoa(s));
    };
    T.rec.stop();
  });
})();`;

function ff(args) {
  const r = spawnSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', ...args], { encoding: 'utf8', maxBuffer: 64 << 20 });
  if (r.status !== 0) throw new Error('ffmpeg failed: ' + (r.stderr || '').slice(-600));
  return r;
}

function maxVolume(f) {
  const r = spawnSync(FFMPEG, ['-hide_banner', '-nostats', '-i', f, '-af', 'volumedetect', '-f', 'null', '-'], { encoding: 'utf8', maxBuffer: 64 << 20 });
  const m = /max_volume:\s*(-?[\d.]+|-inf) dB/.exec(r.stderr || '');
  return m ? (m[1] === '-inf' ? -200 : Number(m[1])) : null;
}

const abs = path.resolve(file);
const selfUrl = pathToFileURL(abs).href;
const W = opt.width, H = opt.height;
// x11: a real (headed) Chrome window on a private Xvfb display, grabbed by ffmpeg at 30 fps; the page renders
// exactly as when nobody records it. screencast: headless Chrome's CDP screencast (any OS; the frame
// read-back slows down pages that are expensive to composite). The backend depends only on the machine.
const XVFB = process.platform === 'linux' && process.env.BENCH_REC_BACKEND !== 'screencast'
  && (process.env.PATH || '').split(path.delimiter).map((d) => path.join(d, 'Xvfb')).find((p) => fs.existsSync(p));
const backend = XVFB ? 'x11' : 'screencast';
const report = { ok: false, file: path.basename(abs), backend, viewport: `${W}x${H}`, duration: 0, duration_source: null, played_via: null,
  audio: { sources: 0, captured: false, max_volume_db: null } };
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bench-rec-'));
const frames = [];
const writes = [];
let browser, xvfb, grab;

function startXvfb(sw, sh) {
  return new Promise((resolve, reject) => {
    const p = spawn(XVFB, ['-displayfd', '3', '-screen', '0', `${sw}x${sh}x24`, '-nolisten', 'tcp'], { stdio: ['ignore', 'ignore', 'pipe', 'pipe'] });
    let out = '', err = '';
    const timer = setTimeout(() => reject(new Error('Xvfb did not start: ' + err.slice(-300))), 15000);
    p.stderr.on('data', (d) => { err += d; });
    p.stdio[3].on('data', (d) => {
      out += d;
      if (out.includes('\n')) { clearTimeout(timer); resolve({ proc: p, display: ':' + out.trim() }); }
    });
    p.on('exit', (code) => { clearTimeout(timer); reject(new Error(`Xvfb exited (${code}): ` + err.slice(-300))); });
  });
}

// Where the page's viewport sits on the X screen: paint it magenta and find the rectangle.
function locateViewport(display, sw, sh) {
  const r = spawnSync(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-f', 'x11grab', '-video_size', `${sw}x${sh}`, '-i', display,
    '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], { maxBuffer: sw * sh * 3 + 1024 });
  if (r.status !== 0 || !r.stdout || r.stdout.length < sw * sh * 3) throw new Error('x11grab failed: ' + String(r.stderr || '').slice(-300));
  const px = r.stdout;
  let x0 = sw, y0 = sh, x1 = -1, y1 = -1;
  for (let y = 0; y < sh; y++) {
    for (let x = 0; x < sw; x++) {
      const i = (y * sw + x) * 3;
      if (px[i] > 245 && px[i + 1] < 10 && px[i + 2] > 245) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    }
  }
  if (x1 - x0 + 1 !== W || y1 - y0 + 1 !== H) throw new Error(`viewport not found on the X screen (found ${x1 - x0 + 1}x${y1 - y0 + 1} at ${x0},${y0})`);
  return { x: x0, y: y0 };
}

try {
  let env;
  if (backend === 'x11') {
    const sw = W + 96, sh = H + 320;
    const x = await startXvfb(sw, sh);
    xvfb = x.proc;
    env = { ...process.env, DISPLAY: x.display };
    report.screen = { display: x.display, width: sw, height: sh };
  }
  browser = await chromium.launch({ executablePath: findChrome(), headless: backend !== 'x11', ignoreDefaultArgs: ['--mute-audio'],
    args: backend === 'x11' ? ['--window-position=0,0'] : [], env });
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, deviceScaleFactor: 1 });
  await ctx.route('**/*', (route) => {
    const u = route.request().url();
    if (u === selfUrl || u.startsWith('data:') || u.startsWith('blob:') || u === 'about:blank') return route.continue();
    return route.abort();
  });
  await ctx.addInitScript(TAP);
  const page = await ctx.newPage();
  let t0 = null;  // wall-clock time of the grab's first frame (x11)
  let cdp = null;
  if (backend === 'x11') {
    // headed Chrome without a window manager can size its window a few pixels short of the viewport:
    // make the window taller than needed so the whole viewport is on screen
    const wc = await ctx.newCDPSession(page);
    const { windowId, bounds } = await wc.send('Browser.getWindowForTarget');
    await wc.send('Browser.setWindowBounds', { windowId, bounds: { left: 0, top: 0, width: (bounds.width || W) + 16, height: (bounds.height || H) + 60 } });
    await wc.detach().catch(() => {});
    await page.setContent(`<body style="margin:0;background:#000"><div style="position:fixed;left:0;top:0;width:${W}px;height:${H}px;background:#ff00ff"></div></body>`);
    await page.waitForTimeout(500);
    const at = locateViewport(env.DISPLAY, report.screen.width, report.screen.height);
    await page.goto(selfUrl, { waitUntil: 'load', timeout: 30000 });
    grab = spawn(FFMPEG, ['-hide_banner', '-loglevel', 'error', '-y', '-f', 'x11grab', '-draw_mouse', '0', '-framerate', '30',
      '-video_size', `${W}x${H}`, '-i', `${env.DISPLAY}+${at.x},${at.y}`, '-copyts', '-c:v', 'libx264', '-preset', 'ultrafast',
      '-crf', '6', path.join(tmp, 'grab.mkv')], { stdio: ['pipe', 'ignore', 'pipe'] });
    grab.err = '';
    grab.stderr.on('data', (d) => { grab.err += d; });
    grab.done = new Promise((res) => grab.on('exit', res));
  } else {
    cdp = await ctx.newCDPSession(page);
    let n = 0;
    cdp.on('Page.screencastFrame', (f) => {
      cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
      const name = path.join(tmp, `f${String(n++).padStart(6, '0')}.jpg`);
      frames.push({ t: f.metadata.timestamp || Date.now() / 1000, name });
      writes.push(fs.promises.writeFile(name, Buffer.from(f.data, 'base64')));
    });
    await page.goto(selfUrl, { waitUntil: 'load', timeout: 30000 });
    await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 90, maxWidth: W, maxHeight: H, everyNthFrame: 1 });
  }
  await page.waitForTimeout(1000);

  const tStart = Date.now() / 1000 - 0.5;
  const play = page.locator('button, [role=button]').filter({ hasText: /play|start|watch|▶/i }).first();
  const aria = page.locator('[aria-label*="play" i], [title*="play" i]').first();
  if (await aria.count()) { await aria.click({ timeout: 2000 }).catch(() => {}); report.played_via = 'aria-label'; }
  else if (await play.count()) { await play.click({ timeout: 2000 }).catch(() => {}); report.played_via = 'button'; }
  else { await page.keyboard.press('Space'); report.played_via = 'space'; }
  const tAudio = await page.evaluate(() => (window.__benchTap && window.__benchTap.start ? window.__benchTap.start() : 0)) / 1000;
  await page.waitForTimeout(700);
  const kicked = await page.evaluate(() => {
    const media = [...document.querySelectorAll('video, audio')];
    if (!media.length || media.some((m) => !m.paused)) return null;
    const vis = (m) => { const r = m.getBoundingClientRect(); return r.width * r.height; };
    const vids = media.filter((m) => m.tagName === 'VIDEO').sort((a, b) => vis(b) - vis(a));
    const el = vids[0] || media[0];
    if (el.tagName === 'VIDEO') el.scrollIntoView({ block: 'center' });
    el.play().catch(() => {});
    return el.tagName.toLowerCase();
  });
  if (kicked) report.played_via += '+' + kicked + '.play()';
  await page.waitForTimeout(800);
  const found = await page.evaluate(() => {
    const media = [...document.querySelectorAll('video, audio')].filter((m) => !m.paused || m.currentTime > 0);
    const withDur = media.filter((m) => isFinite(m.duration) && m.duration > 0).sort((a, b) => b.duration - a.duration);
    if (withDur.length) {
      const m = withDur[0];
      if (m.tagName === 'VIDEO') m.scrollIntoView({ block: 'center' });
      return { src: m.tagName.toLowerCase() + ' element', total: m.duration, left: m.duration - m.currentTime };
    }
    const re = /position|seek|progress|time|timeline|scrub/i;
    for (const s of document.querySelectorAll('input[type=range], [role=slider]')) {
      const lb = s.getAttribute('aria-labelledby');
      const label = [s.getAttribute('aria-label'), s.title, s.id, s.name, lb && (document.getElementById(lb) || {}).textContent].filter(Boolean).join(' ');
      const max = Number(s.max || s.getAttribute('aria-valuemax'));
      const val = Number(s.value || s.getAttribute('aria-valuenow') || 0);
      if (re.test(label) && max > 1) return { src: 'seek slider max', total: max, left: max - (isFinite(val) ? val : 0) };
    }
    return null;
  });
  const elapsed = Date.now() / 1000 - (tStart + 0.5);
  let left;
  if (found && found.total <= opt.ceiling) { report.duration_source = found.src; left = Math.max(0, found.left); }
  else { report.duration_source = found ? `${found.src} (${Math.round(found.total)} s, over the ceiling): cap` : 'cap'; left = Math.max(0, opt.cap - elapsed); }
  const deadline = Date.now() + (left + 1.0) * 1000;
  while (Date.now() < deadline) {
    await page.waitForTimeout(Math.min(500, Math.max(0, deadline - Date.now())));
    const ended = await page.evaluate(() => [...document.querySelectorAll('video, audio')].some((m) => m.ended)).catch(() => false);
    if (ended) { await page.waitForTimeout(1000); break; }
  }
  const tEnd = Date.now() / 1000;
  const b64 = await page.evaluate(() => (window.__benchTap && window.__benchTap.stop ? window.__benchTap.stop() : '')).catch(() => '');
  report.audio.sources = await page.evaluate(() => (window.__benchTap ? window.__benchTap.sources : 0)).catch(() => 0);
  report.audio.errors = await page.evaluate(() => (window.__benchTap && window.__benchTap.errors) || []).catch(() => []);
  const dur = Math.max(0.5, tEnd - tStart);
  const args = [];
  if (backend === 'x11') {
    await new Promise((r) => setTimeout(r, 300));
    grab.stdin.end('q');
    const code = await grab.done;
    grab = null;
    const gm = path.join(tmp, 'grab.mkv');
    if (!fs.existsSync(gm)) throw new Error(`x11grab wrote nothing (exit ${code})`);
    const pr = spawnSync(FFMPEG.replace(/ffmpeg(\.exe)?$/, 'ffprobe$1'), ['-v', 'error', '-show_entries', 'format=start_time', '-of', 'csv=p=0', gm], { encoding: 'utf8' });
    t0 = Number((pr.stdout || '').trim());
    if (!(t0 > 1e9)) throw new Error('could not read the grab start time: ' + (pr.stdout || pr.stderr || '').slice(0, 200));
    if (t0 > tStart) throw new Error(`the grab started ${(t0 - tStart).toFixed(2)} s after play was pressed`);
    args.push('-ss', (tStart - t0).toFixed(3), '-i', gm);
    report.frames = null;
  } else {
    await cdp.send('Page.stopScreencast').catch(() => {});
    await page.waitForTimeout(200);
    await Promise.all(writes);
    // every painted frame from tStart to tEnd, held until the next one
    const inWin = frames.filter((f) => f.t > tStart && f.t < tEnd);
    const before = frames.filter((f) => f.t <= tStart).pop();
    const seq = (before ? [{ ...before, t: tStart }] : []).concat(inWin);
    if (!seq.length) throw new Error('no frames were painted');
    seq[0].t = tStart;
    let list = '';
    for (let i = 0; i < seq.length; i++) {
      const next = i + 1 < seq.length ? seq[i + 1].t : tEnd;
      list += `file '${seq[i].name.replace(/'/g, "'\\''")}'\nduration ${Math.max(0.001, next - seq[i].t).toFixed(4)}\n`;
    }
    list += `file '${seq[seq.length - 1].name.replace(/'/g, "'\\''")}'\n`;
    fs.writeFileSync(path.join(tmp, 'list.txt'), list);
    report.frames = seq.length;
    report.painted_fps = Number((inWin.length / dur).toFixed(1));
    args.push('-f', 'concat', '-safe', '0', '-i', path.join(tmp, 'list.txt'));
  }
  await ctx.close();
  let haveAudio = false;
  if (b64) {
    const aw = path.join(tmp, 'audio.webm');
    fs.writeFileSync(aw, Buffer.from(b64, 'base64'));
    const mv = maxVolume(aw);
    report.audio.max_volume_db = mv;
    if (mv != null && mv > -70) {
      haveAudio = true;
      const off = tAudio - tStart;  // the recorder started this long after the first picture frame
      args.push('-i', aw);
      args.push('-filter_complex', `[1:a]aresample=48000,${off >= 0 ? `adelay=${Math.round(off * 1000)}:all=1` : `atrim=start=${(-off).toFixed(3)},asetpts=PTS-STARTPTS`},apad[a]`);
    }
  }
  report.audio.captured = haveAudio;
  args.push('-map', '0:v:0');
  if (haveAudio) args.push('-map', '[a]', '-c:a', 'aac', '-b:a', '192k', '-ac', '2');
  args.push('-vf', `fps=30,scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2,format=yuv420p`,
    '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-t', dur.toFixed(3), '-map_metadata', '-1', '-map_chapters', '-1',
    '-movflags', '+faststart', path.resolve(outFile));
  fs.mkdirSync(path.dirname(path.resolve(outFile)), { recursive: true });
  ff(args);
  report.duration = Number(dur.toFixed(2));
  report.ok = true;
} catch (e) {
  report.why = String(e && e.message || e).slice(0, 500);
} finally {
  if (grab) { try { grab.kill('SIGKILL'); } catch (e) { /* gone */ } }
  if (browser) await browser.close().catch(() => {});
  if (xvfb) { try { xvfb.kill('SIGTERM'); } catch (e) { /* gone */ } }
  fs.rmSync(tmp, { recursive: true, force: true });
}
console.log(JSON.stringify(report));
process.exit(report.ok ? 0 : 1);

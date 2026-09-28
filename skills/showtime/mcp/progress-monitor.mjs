#!/usr/bin/env node
// showtime progress monitor: a plugin monitor that tells Claude how long-running showtime commands
// (renders, exports, transcriptions, music) are doing when they run in the background.
//
// It follows <SHOWTIME_HOME>/logs/progress.jsonl, which those commands append to (start, every 10%,
// output, end), and prints one short line per milestone. Every printed line reaches Claude as a
// notification, so it stays quiet about anything that finishes within QUIET_S seconds (Claude is
// already waiting on those), then reports at 25% steps and at the end. Only commands started in
// this session's folder (or below it) are reported. Pure Node polling: works the same on macOS,
// Linux and Windows. Stop it by ending the session.
//
//   node progress-monitor.mjs [--quiet-s 45] [--poll-ms 2000] [--all] [--once]

import fs from 'node:fs';
import path from 'node:path';
import { showtimeHome } from './server.mjs';

const args = process.argv.slice(2);
const flag = (name, dflt) => { const i = args.indexOf(name); return i >= 0 && args[i + 1] !== undefined ? Number(args[i + 1]) : dflt; };
const QUIET_S = flag('--quiet-s', Number(process.env.SHOWTIME_MONITOR_QUIET_S) || 45);
const POLL_MS = flag('--poll-ms', 2000);
const ALL = args.includes('--all') || process.env.SHOWTIME_MONITOR_ALL === '1';
const FILE = path.join(showtimeHome(), 'logs', 'progress.jsonl');
const CASE_FOLD = process.platform === 'win32' || process.platform === 'darwin';
const real = (p) => { try { return fs.realpathSync.native(p); } catch { return path.resolve(p); } };
const norm = (p) => { const r = real(path.resolve(p || '.')); return CASE_FOLD ? r.toLowerCase() : r; };
const HERE = norm(process.cwd());

const jobs = new Map(); // pid -> {cmd, t0, last, lastTs, announced, bucket, output}
let offset = 0;
let partial = '';

const say = (line) => { try { process.stdout.write(line + '\n'); } catch { process.exit(0); } };

function fmt(sec) {
  sec = Math.max(0, Math.round(sec));
  if (sec < 60) return `${sec} s`;
  const m = Math.floor(sec / 60);
  return m < 60 ? `${m} min ${sec % 60} s` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

function progressText(j) {
  const p = j.last;
  if (!p) return 'working';
  const eta = p.eta_s !== undefined ? `, about ${fmt(p.eta_s)} left` : '';
  return `${p.label} ${Math.round(p.done)}/${Math.round(p.total)} (${p.pct}%)${eta}`;
}

function inScope(ev) {
  if (ALL || !ev.cwd) return true;
  const c = norm(ev.cwd);
  return c === HERE || c.startsWith(HERE.endsWith(path.sep) ? HERE : HERE + path.sep);
}

function alive(pid) {
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; }
}

function onEvent(ev) {
  if (!ev || typeof ev !== 'object' || !ev.pid || !inScope(ev)) return;
  let j = jobs.get(ev.pid);
  if (ev.ev === 'start' || !j) {
    j = { cmd: ev.cmd || 'showtime', t0: ev.ts || Date.now(), last: null, lastTs: ev.ts || Date.now(), announced: false, bucket: 0, output: null };
    jobs.set(ev.pid, j);
  }
  j.lastTs = ev.ts || Date.now();
  if (ev.ev === 'progress' && ev.total) {
    j.last = ev;
    const b = Math.floor((ev.pct || 0) / 25);
    if (j.announced && b > j.bucket && ev.pct < 100) say(`${j.cmd}: ${progressText(j)}`);
    j.bucket = Math.max(j.bucket, b);
  } else if (ev.ev === 'output' && ev.path) {
    j.output = ev.path;
  } else if (ev.ev === 'end') {
    const secs = ((ev.ts || Date.now()) - j.t0) / 1000;
    if (j.announced || secs >= QUIET_S) {
      if (ev.code === 0) say(`${j.cmd} finished in ${fmt(secs)}${j.output ? `: ${j.output}` : ''}`);
      else say(`${j.cmd} failed after ${fmt(secs)} (exit ${ev.code})${ev.error ? `: ${ev.error}` : ''}`);
    }
    jobs.delete(ev.pid);
  }
}

function tick() {
  let st;
  try { st = fs.statSync(FILE); } catch { st = null; }
  if (st) {
    if (st.size < offset) { offset = 0; partial = ''; } // rotated
    if (st.size > offset) {
      const fd = fs.openSync(FILE, 'r');
      try {
        const len = Math.min(st.size - offset, 4 * 1024 * 1024);
        const buf = Buffer.alloc(len);
        fs.readSync(fd, buf, 0, len, offset);
        offset += len;
        const lines = (partial + buf.toString('utf8')).split('\n');
        partial = lines.pop();
        for (const l of lines) { if (l.trim()) { try { onEvent(JSON.parse(l)); } catch { /* skip a torn line */ } } }
      } finally { fs.closeSync(fd); }
    }
  }
  const now = Date.now();
  for (const [pid, j] of jobs) {
    if (!j.announced && now - j.t0 >= QUIET_S * 1000) {
      j.announced = true;
      say(`${j.cmd} is still running after ${fmt((now - j.t0) / 1000)}: ${progressText(j)}`);
    }
    if (now - j.lastTs > 60000 && !alive(pid)) {
      if (j.announced) say(`${j.cmd} stopped without finishing (process ${pid} is gone)`);
      jobs.delete(pid);
    }
  }
}

try { offset = fs.statSync(FILE).size; } catch { offset = 0; } // only what happens from now on
if (args.includes('--once')) { offset = 0; tick(); process.exit(0); }
setInterval(tick, POLL_MS);

// ffmpeg / ffprobe for the node scripts. Never runs a bare `ffmpeg` from PATH without
// checking that it works (a broken system build must not be picked).
//
// Order: $SHOWTIME_FFMPEG, ~/.showtime/bin/ffmpeg(.exe), the Python resolver (st.ff), then
// every ffmpeg on PATH that answers `-version`.
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { showtimeHome } from './deps.mjs';
import { IS_WIN, runProc, venvPython, pyEnv, UserError } from './cli.mjs';

const exe = (n) => (IS_WIN && !n.toLowerCase().endsWith('.exe') ? n + '.exe' : n);
let cached = null;

function works(p) {
  if (!p) return false;
  try {
    const r = spawnSync(p, ['-hide_banner', '-version'], { stdio: ['ignore', 'pipe', 'ignore'], timeout: 20000, windowsHide: true });
    return r.status === 0;
  } catch { return false; }
}
function sibling(p, name) {
  const s = path.join(path.dirname(p), exe(name));
  return fs.existsSync(s) ? s : null;
}
function onPath(name) {
  const out = [];
  for (const d of (process.env.PATH || '').split(path.delimiter)) {
    if (!d) continue;
    const p = path.join(d, exe(name));
    if (fs.existsSync(p) && !out.includes(p)) out.push(p);
  }
  return out;
}

/** -> { ffmpeg, ffprobe|null, source } ; throws UserError if nothing works. */
export function resolveFF() {
  if (cached) return cached;
  const tried = [];
  const env = process.env.SHOWTIME_FFMPEG;
  if (env) {
    if (!works(env)) throw new UserError(`SHOWTIME_FFMPEG=${env} does not run`, 'unset it or point it at a working ffmpeg');
    const pr = process.env.SHOWTIME_FFPROBE || sibling(env, 'ffprobe');
    return (cached = { ffmpeg: env, ffprobe: pr && works(pr) ? pr : null, source: 'env' });
  }
  const ours = path.join(showtimeHome(), 'bin', exe('ffmpeg'));
  tried.push(ours);
  if (fs.existsSync(ours) && works(ours)) return (cached = { ffmpeg: ours, ffprobe: sibling(ours, 'ffprobe'), source: 'showtime' });
  const py = venvPython();
  if (py) {
    const r = spawnSync(py, ['-c', 'import json;from st import ff;print(json.dumps(ff.resolve().as_dict()))'],
      { env: pyEnv(), encoding: 'utf8', timeout: 60000, windowsHide: true });
    if (r.status === 0) {
      try {
        const j = JSON.parse(String(r.stdout).trim().split('\n').pop());
        if (j.ffmpeg && works(j.ffmpeg)) return (cached = { ffmpeg: j.ffmpeg, ffprobe: j.ffprobe || null, source: `python:${j.source}` });
      } catch { /* fall through */ }
    }
  }
  for (const cand of onPath('ffmpeg')) {
    tried.push(cand);
    if (works(cand)) {
      const pr = sibling(cand, 'ffprobe') || onPath('ffprobe').find(works) || null;
      return (cached = { ffmpeg: cand, ffprobe: pr, source: 'system' });
    }
  }
  throw new UserError(`no working ffmpeg found (tried: ${tried.join(', ')})`, 'run `showtime setup` to install a static ffmpeg into ~/.showtime/bin');
}

// Optional log file: every ffmpeg call and its stderr are appended to it (render sets
// <work>/logs/render.log so `showtime report` and a failed render leave the full story).
let LOG_FILE = null;
export function setLogFile(file) {
  LOG_FILE = file || null;
  if (LOG_FILE) { try { fs.mkdirSync(path.dirname(LOG_FILE), { recursive: true }); } catch { LOG_FILE = null; } }
}
export function logLine(text) {
  if (!LOG_FILE) return;
  try { fs.appendFileSync(LOG_FILE, `[${new Date().toISOString()}] ${String(text).replace(/\s+$/, '')}\n`); } catch { /* logging never breaks a render */ }
}

/** Run ffmpeg with an argument list. Resolves {code, stderr}; rejects with the stderr tail on failure. */
export async function ffmpeg(args, { timeout = 0, loglevel = 'error', onStderr, allowFail = false } = {}) {
  const { ffmpeg: bin } = resolveFF();
  const full = ['-hide_banner', '-nostdin', '-loglevel', loglevel, '-y', ...args.map(String)];
  const r = await runProc(bin, full, { timeout, onStderr });
  if (LOG_FILE) {
    const q = (x) => (/[\s"'$;&|<>()]/.test(x) ? JSON.stringify(x) : x);
    const err = String(r.stderr || '').split('\n').filter((l) => l && !/^(frame|fps|stream_\d|bitrate|total_size|out_time|dup_frames|drop_frames|speed|progress)=/.test(l)).join('\n');
    logLine(`$ ffmpeg ${full.map(q).join(' ')}\n  exit ${r.code}${err ? '\n' + err.split('\n').slice(-60).map((l) => '  ' + l).join('\n') : ''}`);
  }
  if (r.code !== 0 && !allowFail) {
    const tail = String(r.stderr || '').trim().split('\n').slice(-8).join('\n');
    const e = new Error(`ffmpeg failed (exit ${r.code}): ${tail || '(no output)'}`);
    e.stderr = r.stderr;
    throw e;
  }
  return r;
}

/** ffprobe JSON (format + streams), falling back to `ffmpeg -i` parsing without ffprobe. */
export async function probe(file) {
  const ff = resolveFF();
  if (ff.ffprobe) {
    const r = await runProc(ff.ffprobe, ['-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', '-count_packets', String(file)], { timeout: 120000 });
    if (r.code !== 0) throw new Error(`ffprobe could not read ${file}: ${r.stderr.trim().slice(-300)}`);
    const j = JSON.parse(r.stdout || '{}');
    const v = (j.streams || []).find((s) => s.codec_type === 'video');
    const a = (j.streams || []).find((s) => s.codec_type === 'audio');
    const fr = (s) => { if (!s) return null; const [n, d] = String(s).split('/').map(Number); return d ? n / d : n || null; };
    return {
      duration: Number(j.format && j.format.duration) || null,
      size: Number(j.format && j.format.size) || null,
      video: v ? {
        codec: v.codec_name, width: v.width, height: v.height, pix_fmt: v.pix_fmt,
        fps: fr(v.avg_frame_rate) || fr(v.r_frame_rate), frames: Number(v.nb_read_packets || v.nb_frames) || null,
        duration: Number(v.duration) || null, color_space: v.color_space, color_primaries: v.color_primaries,
        color_transfer: v.color_transfer, color_range: v.color_range, profile: v.profile,
      } : null,
      audio: a ? { codec: a.codec_name, sample_rate: Number(a.sample_rate), channels: a.channels, duration: Number(a.duration) || null } : null,
    };
  }
  const r = await runProc(ff.ffmpeg, ['-hide_banner', '-i', String(file)], { timeout: 60000 });
  const t = r.stderr || '';
  const d = /Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)/.exec(t);
  const vm = /Video:\s*(\w+).*?(\d{2,5})x(\d{2,5})/.exec(t);
  const fm = /([\d.]+)\s*fps/.exec(t);
  return {
    duration: d ? Number(d[1]) * 3600 + Number(d[2]) * 60 + Number(d[3]) : null, size: fs.statSync(file).size,
    video: vm ? { codec: vm[1], width: Number(vm[2]), height: Number(vm[3]), fps: fm ? Number(fm[1]) : null, frames: null } : null,
    audio: /Audio:/.test(t) ? { codec: (/Audio:\s*(\w+)/.exec(t) || [])[1] } : null,
  };
}

/** Integrated loudness etc. via loudnorm's analysis pass (null when silent / no audio). */
export async function measureLoudness(file, { I = -14, TP = -1, LRA = 11 } = {}) {
  const r = await ffmpeg(['-i', file, '-vn', '-af', `loudnorm=I=${I}:TP=${TP}:LRA=${LRA}:print_format=json`, '-f', 'null', '-'],
    { loglevel: 'info', allowFail: true });
  const m = /\{[^{}]*"input_i"[^{}]*\}/s.exec(r.stderr || '');
  if (!m) return null;
  const j = JSON.parse(m[0]);
  const out = {};
  for (const k of ['input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset']) out[k] = Number(j[k]);
  if (!isFinite(out.input_i) || out.input_i < -70) return null; // silence
  return out;
}

/** Second-pass (linear) loudnorm filter from measureLoudness() values. */
export function loudnormFilter(m, { I = -14, TP = -1, LRA = 11 } = {}) {
  const f = (x) => (isFinite(x) ? x.toFixed(2) : '0.00');
  return `loudnorm=I=${I}:TP=${TP}:LRA=${LRA}:measured_I=${f(m.input_i)}:measured_TP=${f(m.input_tp)}:` +
    `measured_LRA=${f(m.input_lra)}:measured_thresh=${f(m.input_thresh)}:offset=${f(m.target_offset)}:linear=true:print_format=summary`;
}

/** Write interleaved Float32 samples as a 32-bit float WAV. */
export function writeWavFloat(file, channels, sampleRate) {
  const n = channels[0].length, ch = channels.length;
  const data = Buffer.alloc(n * ch * 4);
  let o = 0;
  for (let i = 0; i < n; i++) for (let c = 0; c < ch; c++) { data.writeFloatLE(channels[c][i], o); o += 4; }
  const h = Buffer.alloc(44);
  h.write('RIFF', 0); h.writeUInt32LE(36 + data.length, 4); h.write('WAVE', 8); h.write('fmt ', 12);
  h.writeUInt32LE(16, 16); h.writeUInt16LE(3, 20); h.writeUInt16LE(ch, 22); h.writeUInt32LE(sampleRate, 24);
  h.writeUInt32LE(sampleRate * ch * 4, 28); h.writeUInt16LE(ch * 4, 32); h.writeUInt16LE(32, 34);
  h.write('data', 36); h.writeUInt32LE(data.length, 40);
  fs.writeFileSync(file, Buffer.concat([h, data]));
}

/** "30" or "30000/1001" for ffmpeg -r / -framerate. */
export function fpsArg(fps) {
  if (Number.isInteger(fps)) return String(fps);
  for (const den of [1001, 1000, 100]) {
    const num = Math.round(fps * den);
    if (Math.abs(num / den - fps) < 1e-9) return `${num}/${den}`;
  }
  return String(fps);
}

/** EBU R128 integrated loudness, loudness range and true peak. -> {I, LRA, TP} (I = null when silent) */
export async function ebur128(file) {
  const r = await ffmpeg(['-i', file, '-vn', '-af', 'ebur128=peak=true:framelog=quiet', '-f', 'null', '-'], { loglevel: 'info', allowFail: true });
  const t = String(r.stderr || '');
  const tail = t.slice(t.lastIndexOf('Summary:'));
  const num = (re) => { const m = re.exec(tail); return m ? Number(m[1]) : null; };
  let I = num(/\bI:\s*(-?[\d.]+|-inf)\s*LUFS/);
  if (I === null || !isFinite(I) || I < -70) I = null;
  const TP = num(/True peak:\s*[\r\n]+\s*Peak:\s*(-?[\d.]+)/);
  return { I, LRA: num(/LRA:\s*(-?[\d.]+)\s*LU\b/), TP: TP === null || !isFinite(TP) ? -120 : TP };
}

let encCache = null;
/** Is an encoder compiled into the resolved ffmpeg? (e.g. 'libvpx-vp9', 'prores_ks') */
export function hasEncoder(name) {
  if (!encCache) {
    const { ffmpeg: bin } = resolveFF();
    const r = spawnSync(bin, ['-hide_banner', '-encoders'], { encoding: 'utf8', timeout: 30000, windowsHide: true });
    encCache = new Set();
    for (const line of String(r.stdout || '').split('\n')) {
      const m = /^\s*[VAS][.A-Z]{5}\s+(\S+)/.exec(line);
      if (m) encCache.add(m[1]);
    }
  }
  return encCache.has(name);
}

/** A tiny grayscale thumbnail (w x h bytes) of an image or of a video at time t. */
export async function grayThumb(file, { t = null, w = 64, h = 36 } = {}) {
  const tmp = path.join(path.dirname(String(file)), `.gray-${process.pid}-${Math.random().toString(36).slice(2)}.raw`);
  try {
    await ffmpeg([...(t !== null ? ['-ss', String(t)] : []), '-i', String(file), '-frames:v', '1',
      '-vf', `scale=${w}:${h}:flags=area,format=gray`, '-f', 'rawvideo', tmp]);
    return fs.readFileSync(tmp);
  } finally { fs.rmSync(tmp, { force: true }); }
}

/** Mean absolute difference (0-255) between two images, on 64x36 grayscale thumbnails. */
export async function meanFrameDiff(a, b) {
  const [x, y] = await Promise.all([grayThumb(a), grayThumb(b)]);
  const n = Math.min(x.length, y.length);
  if (!n) return null;
  let s = 0;
  for (let i = 0; i < n; i++) s += Math.abs(x[i] - y[i]);
  return s / n;
}

// Chapter mode (issue #22): render a film in named, frame-exact pieces and join them with one audio pass.
// The chapter table, the tiling rules, the piece join (one piece in memory at a time) and the seam checks
// that compare the joined file with the master soundtrack and the page itself.
import fs from 'node:fs';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { ffmpeg, resolveFF } from './ff.mjs';
import { readStream, toAnnexB, sameParamSets } from './splice.mjs';
import { UserError } from './cli.mjs';

/** The plan's first line: chapters are not a speed feature on one machine (measured in #22). */
export const ONE_MACHINE = 'on one machine a whole render is faster (#22)';
export const MIN_CHAPTER_S = 1;
export const SEAM_PSNR_DB = 40;
// a seam may sit this far below a frame inside the same piece (grain, a high CRF: encode noise, not a join error)
export const SEAM_PSNR_REL_DB = 3;
// ...but never below this: a wholly wrong piece lowers its own baseline too
export const SEAM_PSNR_FLOOR_DB = 25;
/** The PSNR a seam frame must reach, given a frame inside the same piece captured the same way. */
export const seamThreshold = (baseline) => +Math.max(SEAM_PSNR_FLOOR_DB, Math.min(SEAM_PSNR_DB, baseline - SEAM_PSNR_REL_DB)).toFixed(2);
export const SEAM_LOUDNESS_DB = 0.1;
export const SEAM_LAG_SAMPLES = 1;

const norm = (a) => (Array.isArray(a) ? { t: Number(a[0]), label: String(a[1] ?? '') }
  : a && typeof a === 'object' ? { t: Number(a.t ?? a.at ?? a.start ?? a.s), label: String(a.label ?? a.title ?? a.name ?? '') }
    : { t: NaN, label: '' });

const CHAPTERS_LINE = '"chapters": [[0, "Intro"], [42.5, "How it works"]]';

/**
 * The chapters to render: showtime.json "chapters" (the list the HTML export and review-pack use), else the
 * film's acts (Film.start({acts})); never the top-level clips. Chapter N is the frames
 * [round(t_N * fps), round(t_N+1 * fps)), the last one ends at total = round(duration * fps).
 * transitions: [[from, to], ...] seconds of data-transition windows (a chapter starting inside one warns).
 * -> { source, total, chapters: [{n, label, t, frames: [s, e]}], warnings }; throws a UserError when there is
 * no table, it is not in order, or a chapter is shorter than 1 s.
 */
export function chapterTable({ cfgChapters, acts, duration, fps, transitions = [] }) {
  let source = null, raw = null;
  if (Array.isArray(cfgChapters) && cfgChapters.length) { source = 'showtime.json "chapters"'; raw = cfgChapters; }
  else if (Array.isArray(acts) && acts.length) { source = 'the film\'s acts'; raw = acts; }
  if (!raw) {
    throw new UserError('this project has no chapters: chapter mode needs showtime.json "chapters" or a film\'s acts (the top-level scenes are not used)',
      `add a line to showtime.json such as ${CHAPTERS_LINE} (one entry per chapter start, on a scene start, each at least ${MIN_CHAPTER_S} s)`);
  }
  if (!(fps > 0) || !(duration > 0)) throw new UserError(`cannot plan chapters for a ${duration}s video at ${fps} fps`);
  const total = Math.round(duration * fps);
  const warnings = [];
  const list = raw.map(norm);
  list.forEach((c, i) => {
    if (!isFinite(c.t) || c.t < 0) {
      throw new UserError(`chapter ${i + 1} in ${source} has no valid time: ${JSON.stringify(raw[i])}`,
        'each chapter is [seconds, "label"] or {"t": seconds, "label": "..."}, e.g. ' + CHAPTERS_LINE);
    }
  });
  for (let i = 1; i < list.length; i++) {
    if (!(list[i].t > list[i - 1].t)) {
      throw new UserError(`${source} is not in order: chapter ${i + 1} (${list[i].t}s) does not come after chapter ${i} (${list[i - 1].t}s)`,
        'list the chapters by time, each one later than the one before');
    }
  }
  const kept = [];
  for (const c of list) {
    if (Math.round(c.t * fps) >= total) warnings.push(`chapter "${c.label}" at ${c.t}s starts past the end of the ${duration}s video: dropped`);
    else kept.push(c);
  }
  if (!kept.length) throw new UserError(`every chapter in ${source} starts past the end (${duration}s)`, `start the first chapter at 0: ${CHAPTERS_LINE}`);
  if (Math.round(kept[0].t * fps) !== 0) {
    warnings.push(`the first chapter ("${kept[0].label}") starts at ${kept[0].t}s: it renders from 0 (chapters tile the whole video)`);
  }
  const starts = kept.map((c, i) => (i === 0 ? 0 : Math.round(c.t * fps)));
  const chapters = kept.map((c, i) => ({ n: i + 1, label: c.label, t: +(starts[i] / fps).toFixed(6), frames: [starts[i], i + 1 < kept.length ? starts[i + 1] : total] }));
  for (const ch of chapters) {
    const [s, e] = ch.frames;
    if (e - s < Math.round(MIN_CHAPTER_S * fps)) {
      throw new UserError(`chapter ${ch.n} ("${ch.label}", ${(s / fps).toFixed(3)}-${(e / fps).toFixed(3)}s) is shorter than ${MIN_CHAPTER_S} s: a piece's warm-up costs more than it draws`,
        `merge it with a neighbour in ${source}, or move its start`);
    }
  }
  for (const ch of chapters.slice(1)) {
    const at = ch.frames[0] / fps;
    const win = (transitions || []).find(([a, b]) => at > a + 1e-6 && at < b - 1e-6);
    if (win) {
      warnings.push(`chapter ${ch.n} ("${ch.label}") starts at ${at.toFixed(3)}s, inside a data-transition (${win[0].toFixed(2)}-${win[1].toFixed(2)}s): ` +
        'a fix to that transition touches two chapters; start chapters on scene starts');
    }
  }
  return { source, total, chapters, warnings };
}

/** ch-01.mp4 ... : a piece's file name. */
export const pieceName = (n) => `ch-${String(n).padStart(2, '0')}.mp4`;
/** <job>/work/chapters/<W>x<H>/ : where the pieces of one size live. */
export const piecesDir = (job, W, H) => path.join(job, 'work', 'chapters', `${W}x${H}`);

/**
 * Do the pieces tile [0, total) exactly, at one size and frame rate, as the chapter table says?
 * pieces: [{n, file, frames: [s, e], width, height, fps, timeline_frames}]; cmd(n) -> the render command for
 * chapter n. -> {ok, errors: [message], missing: [n], fix} (fix: the commands that would complete it)
 */
export function checkTiling(pieces, { chapters, total, W, H, fps }, cmd) {
  const errors = [];
  const redo = new Set();
  for (const p of pieces) {
    const name = path.basename(String(p.file || pieceName(p.n)));
    if (p.timeline_frames !== total) { errors.push(`${name} was rendered for a ${p.timeline_frames}-frame video; this one has ${total} frames (the length changed)`); redo.add(p.n); }
    if (p.width !== W || p.height !== H) { errors.push(`${name} is ${p.width}x${p.height}; this join is ${W}x${H}`); redo.add(p.n); }
    if (Math.abs(Number(p.fps) - fps) > 1e-6) { errors.push(`${name} is ${p.fps} fps; this join is ${fps} fps`); redo.add(p.n); }
  }
  const sorted = pieces.slice().sort((x, y) => x.frames[0] - y.frames[0] || x.frames[1] - y.frames[1]);
  let at = 0;
  for (const p of sorted) {
    const [s, e] = p.frames;
    if (s > at) errors.push(`frames ${at}-${s - 1} (${(at / fps).toFixed(3)}-${(s / fps).toFixed(3)}s) are in no piece (a gap)`);
    else if (s < at) { errors.push(`${path.basename(String(p.file || pieceName(p.n)))} overlaps the piece before it (frames ${s}-${Math.min(at, e) - 1})`); redo.add(p.n); }
    at = Math.max(at, e);
  }
  if (at < total) errors.push(`frames ${at}-${total - 1} (${(at / fps).toFixed(3)}-${(total / fps).toFixed(3)}s) are in no piece (a gap)`);
  const missing = [];
  for (const ch of chapters) {
    const p = pieces.find((x) => x.n === ch.n);
    if (!p) { missing.push(ch.n); continue; }
    if (p.frames[0] !== ch.frames[0] || p.frames[1] !== ch.frames[1]) {
      errors.push(`${path.basename(String(p.file || pieceName(p.n)))} covers frames ${p.frames[0]}-${p.frames[1] - 1}, chapter ${ch.n} is now frames ${ch.frames[0]}-${ch.frames[1] - 1}`);
      redo.add(ch.n);
    }
  }
  for (const n of missing) {
    const ch = chapters.find((x) => x.n === n);
    errors.push(`chapter ${n} ("${ch.label}", frames ${ch.frames[0]}-${ch.frames[1] - 1}) has no piece`);
  }
  for (const p of pieces) if (!chapters.some((ch) => ch.n === p.n)) errors.push(`${path.basename(String(p.file))} is chapter ${p.n}, which the chapter table no longer has`);
  const todo = [...new Set([...missing, ...redo])].filter((n) => chapters.some((ch) => ch.n === n)).sort((x, y) => x - y);
  return { ok: errors.length === 0, errors, missing, redo: todo, fix: todo.map(cmd) };
}

/**
 * Join pieces (H.264 .mp4 or Annex B .h264, in timeline order) into one Annex B stream at `out`, writing piece
 * after piece: only one piece's stream is in memory at a time. Each piece must start with an IDR frame and
 * have `frames` frames; its SPS/PPS must equal the first piece's (else nothing is joined and `why` says so).
 * -> {ok, out, frames, seams: [first frame of each piece after the first], why, peakBytes, maxHeld}
 */
export async function joinPieces(pieces, out, { workDir = path.dirname(out) } = {}) {
  const fd = fs.openSync(out, 'w');
  let first = null, frames = 0, held = 0, maxHeld = 0, peakBytes = 0, why = null, bad = null;
  const seams = [];
  try {
    for (const [k, p] of pieces.entries()) {
      let h264 = p.file, tmp = null;
      if (!/\.(h264|264)$/i.test(h264)) { tmp = path.join(workDir, `join-${k}.h264`); h264 = await toAnnexB(p.file, tmp); }
      let st = readStream(h264);
      held++; maxHeld = Math.max(maxHeld, held); peakBytes = Math.max(peakBytes, st.buf.length);
      const name = path.basename(String(p.file));
      if (p.frames !== undefined && st.aus.length !== p.frames) { why = `${name} parsed as ${st.aus.length} frames, expected ${p.frames}`; bad = p.n ?? k + 1; }
      else if (!st.aus.length || !st.aus[0].idr) { why = `${name} does not start with a keyframe (IDR)`; bad = p.n ?? k + 1; }
      else if (first && !sameParamSets(first, st.params)) why = `${name} was encoded with other settings or another ffmpeg than ${path.basename(String(pieces[0].file))} (its SPS/PPS differ)`;
      if (!why) {
        if (!first) first = st.params;
        if (k > 0) seams.push(frames);
        fs.writeSync(fd, st.buf, 0, st.buf.length);
        frames += st.aus.length;
      }
      st = null; held--;
      if (tmp) fs.rmSync(tmp, { force: true });
      if (why) break;
    }
  } finally { fs.closeSync(fd); }
  if (why) fs.rmSync(out, { force: true });
  return { ok: !why, out, frames, seams, why, ...(bad !== null ? { bad } : {}), peakBytes, maxHeld };
}

/**
 * Every piece's video packets, read before choosing a byte join or a re-encode: the count the report promised and
 * a keyframe first. -> {n, why} of the first damaged piece, else null (null too when there is no ffprobe).
 */
export function checkPieces(pieces) {
  const { ffprobe } = resolveFF();
  if (!ffprobe) return null;
  for (const [k, p] of pieces.entries()) {
    const r = spawnSync(ffprobe, ['-v', 'error', '-select_streams', 'v:0', '-show_entries', 'packet=flags', '-of', 'csv=p=0', p.file],
      { encoding: 'utf8', maxBuffer: 1 << 28, windowsHide: true });
    const name = path.basename(String(p.file)), n = p.n ?? k + 1;
    if (r.status !== 0) return { n, why: `${name} cannot be read (${String(r.stderr || '').trim().split('\n').pop()})` };
    const fl = r.stdout.split('\n').filter((l) => l.trim());
    if (p.frames !== undefined && fl.length !== p.frames) return { n, why: `${name} has ${fl.length} frames, expected ${p.frames}` };
    if (!fl.length || !fl[0].includes('K')) return { n, why: `${name} does not start with a keyframe` };
  }
  return null;
}

/**
 * The fallback join: decode every piece and encode the whole video once (another ffmpeg, CRF or preset made
 * pieces whose bytes cannot be joined). codecArgs: the render's x264 arguments; keyframes are forced at the
 * seams so they stay cut points for a later --chapter fix.
 */
export async function reencodePieces({ pieces, fps, codecArgs, out, onStderr, fpsStr }) {
  const inputs = pieces.flatMap((p) => ['-i', p.file]);
  const g = pieces.map((_, k) => `[${k}:v]setpts=PTS-STARTPTS,setsar=1[p${k}]`);
  g.push(`${pieces.map((_, k) => `[p${k}]`).join('')}concat=n=${pieces.length}:v=1:a=0[v]`);
  const seams = [];
  let at = 0;
  for (const p of pieces.slice(0, -1)) { at += p.frames; seams.push(at); }
  await ffmpeg([...inputs, '-filter_complex', g.join(';'), '-map', '[v]', ...withForcedKeys(codecArgs, seams), '-r', fpsStr || String(fps), '-an',
    '-progress', 'pipe:2', '-nostats', out], onStderr ? { onStderr } : {});
  return out;
}

/** x264 arguments plus forced IDR frames at these frame numbers (none: the arguments unchanged). */
export function withForcedKeys(codecArgs, frames) {
  const ks = [...new Set((frames || []).filter((f) => f > 0))].sort((x, y) => x - y);
  if (!ks.length) return codecArgs.slice();
  return [...codecArgs, '-force_key_frames', `expr:${ks.map((f) => `eq(n,${f})`).join('+')}`, '-forced-idr', '1'];
}

// ---- seam checks: the joined file against the master soundtrack (never against the neighbouring chapter)

/**
 * f32 stereo windows [[s0, s1), ...] (samples at `rate`) of a file's audio, sliced from one decode that stops at
 * the last window: sample exact, and one pass per file however many seams (an input seek on AAC is not exact).
 */
function pcmWindows(file, wins, rate = 48000) {
  const { ffmpeg: bin } = resolveFF();
  const end = Math.max(...wins.map((w) => w[1]));
  return new Promise((resolve, reject) => {
    const p = spawn(bin, ['-v', 'error', '-nostdin', '-i', file, '-vn', '-af', `aresample=${rate},atrim=end_sample=${end}`,
      '-ac', '2', '-f', 'f32le', 'pipe:1'], { windowsHide: true });
    const bufs = wins.map(([s0, s1]) => Buffer.alloc(Math.max(0, s1 - Math.max(0, s0)) * 8));
    const got = wins.map(() => 0);
    let pos = 0, err = '';
    p.stdout.on('data', (chunk) => {
      const c0 = pos, c1 = pos + chunk.length;
      wins.forEach(([s0, s1], i) => {
        const b0 = Math.max(0, s0) * 8, lo = Math.max(b0, c0), hi = Math.min(s1 * 8, c1);
        if (hi > lo) { chunk.copy(bufs[i], lo - b0, lo - c0, hi - c0); got[i] = Math.max(got[i], hi - b0); }
      });
      pos = c1;
    });
    p.stderr.on('data', (d) => { err += d; });
    p.on('error', reject);
    p.on('close', (code) => {
      if (code !== 0) reject(new Error(`could not decode the audio of ${path.basename(file)}: ${err.trim().split('\n').pop()}`));
      else resolve(bufs.map((b, i) => new Float32Array(b.buffer, b.byteOffset, Math.floor(got[i] / 4))));
    });
  });
}

// BS.1770 K-weighting at 48 kHz (the two biquads of ITU-R BS.1770-4)
const K1 = { b: [1.53512485958697, -2.69169618940638, 1.19839281085285], a: [-1.69065929318241, 0.73248077421585] };
const K2 = { b: [1.0, -2.0, 1.0], a: [-1.99004745483398, 0.99007225036621] };
function biquad(x, { b, a }) {
  const y = new Float64Array(x.length);
  let x1 = 0, x2 = 0, y1 = 0, y2 = 0;
  for (let i = 0; i < x.length; i++) {
    const v = b[0] * x[i] + b[1] * x1 + b[2] * x2 - a[0] * y1 - a[1] * y2;
    x2 = x1; x1 = x[i]; y2 = y1; y1 = v; y[i] = v;
  }
  return y;
}

/** Loudness (LUFS, ungated: BS.1770 short-term when the window is 3 s) of interleaved stereo samples. */
export function shortTermLoudness(st) {
  let sum = 0;
  const n = Math.floor(st.length / 2);
  for (let ch = 0; ch < 2; ch++) {
    const x = new Float64Array(n);
    for (let i = 0; i < n; i++) x[i] = st[2 * i + ch];
    const y = biquad(biquad(x, K1), K2);
    let ms = 0;
    for (let i = 0; i < n; i++) ms += y[i] * y[i];
    sum += ms / Math.max(1, n);
  }
  return sum > 0 ? -0.691 + 10 * Math.log10(sum) : -Infinity;
}

/** The lag (samples) of b against a that correlates best, within +-maxLag, or null for silence. */
export function bestLag(a, b, maxLag) {
  const n = Math.min(a.length, b.length);
  let ea = 0;
  for (let i = 0; i < n; i++) ea += a[i] * a[i];
  if (ea < 1e-9) return null;
  let best = -Infinity, at = 0;
  for (let L = -maxLag; L <= maxLag; L++) {
    let s = 0;
    const i0 = Math.max(0, -L), i1 = Math.min(n, n - L);
    for (let i = i0; i < i1; i++) s += a[i] * b[i + L];
    if (s > best) { best = s; at = L; }
  }
  return at;
}

const mono = (st) => { const n = st.length >> 1; const m = new Float32Array(n); for (let i = 0; i < n; i++) m[i] = 0.5 * (st[2 * i] + st[2 * i + 1]); return m; };

/**
 * Loudness step and sync at each seam: the final's decoded audio against the master soundtrack it should
 * carry (the render's master.m4a). seams: seconds. -> [{t, loudness_final, loudness_master, delta_db, lag_samples, ok}]
 */
export async function seamAudio(final, masterFile, seams, { rate = 48000, maxLag = 2048 } = {}) {
  const out = [];
  const wins = seams.map((t) => { const c = Math.round(t * rate); return [Math.max(0, c - Math.round(1.5 * rate)), c + Math.round(1.5 * rate)]; });
  if (!wins.length) return out;
  const [FA, MA] = await Promise.all([pcmWindows(final, wins, rate), pcmWindows(masterFile, wins, rate)]);
  for (const [i, t] of seams.entries()) {
    const c = Math.round(t * rate);
    const s0 = wins[i][0];
    const fa = FA[i], ma = MA[i];
    const lf = shortTermLoudness(fa), lm = shortTermLoudness(ma);
    const delta = isFinite(lf) && isFinite(lm) ? lf - lm : (lf === lm ? 0 : Infinity);
    // sync: 1 s around the seam
    const h = Math.round(0.5 * rate), mid = c - s0;
    const mf = mono(fa).subarray(Math.max(0, mid - h), mid + h), mm = mono(ma).subarray(Math.max(0, mid - h), mid + h);
    const lag = bestLag(mm, mf, maxLag);
    const ok = Math.abs(delta) <= SEAM_LOUDNESS_DB && (lag === null || Math.abs(lag) <= SEAM_LAG_SAMPLES);
    out.push({ t: +t.toFixed(6), loudness_final: isFinite(lf) ? +lf.toFixed(3) : null, loudness_master: isFinite(lm) ? +lm.toFixed(3) : null,
      delta_db: isFinite(delta) ? +delta.toFixed(4) : null, lag_samples: lag, ok });
  }
  return out;
}

/** PSNR (dB, Y'CbCr 4:2:0 as encoded; Infinity when equal) of a captured frame image against frame k of a video. */
export async function framePsnr(image, video, k, fps, vf) {
  const at = Math.max(0, (k - 0.5) / fps);
  const r = await ffmpeg(['-i', image, '-ss', at.toFixed(6), '-i', video, '-filter_complex',
    `[0:v]${vf},format=yuv420p[a];[1:v]format=yuv420p,trim=end_frame=1[b];[a][b]psnr`, '-frames:v', '1', '-f', 'null', '-'],
  { loglevel: 'info', allowFail: true });
  const m = /PSNR .*average:(inf|[\d.]+)/.exec(String(r.stderr || ''));
  if (r.code !== 0 || !m) throw new Error(`could not compare frame ${k} of ${path.basename(video)}: ${String(r.stderr || '').trim().split('\n').pop()}`);
  return m[1] === 'inf' ? Infinity : Number(m[1]);
}

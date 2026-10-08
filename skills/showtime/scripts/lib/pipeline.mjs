// Render pipeline helpers: who captures which frames, and one encoder fed the frames in order while the
// capture runs.
//
// CaptureQueue: every worker starts on its own contiguous part of the plan (as before: one warm-up per
// part), and a worker that runs out of frames takes the back half of the largest part still left, so no
// worker runs alone at the end. A frame's pixels do not depend on which worker drew it: each run that does
// not continue the worker's last frame is preceded by the usual 1 s warm-up replay.
//
// OrderedFeed: the frames land on disk as they are captured (as before, so --keep-frames, the poster and a
// failed render behave the same); one ffmpeg reads them from its stdin in frame order as soon as each one
// and every frame before it are there. The encoder sees the same frames in the same order as an encode
// that starts after the capture, so the file is the same, byte for byte. Memory stays small: frames wait
// on disk, never in memory, and the pipe's back-pressure holds the reader.
import fs from 'node:fs';
import os from 'node:os';
import { ffmpegPipe } from './ff.mjs';

/**
 * The automatic worker count, and why. Measured (0.4.1 speed lab, build box and review):
 * - with a GPU, 3 browsers were best on a 6-core machine (4 and 6 were slower);
 * - without one (SwiftShader and the like) every browser already spreads its drawing over many cores. On
 *   a 6-core machine a WebGL showreel was about 10 % faster with 1 browser than with 3, but a DOM page was
 *   about 50 % slower with 1 (35 s against 23.5 s for 150 frames); a 64-core machine was best at 4-16
 *   (8 within 3-30 % of the best for each test film). So: one browser per 8 CPU threads, never fewer than
 *   the 3 of 0.4.0 (CPU threads - 2 on 3-4 threads), at most 8.
 * Then never more than CPU threads - 2, one per 45 frames, one per 3 GB of RAM (half of it), and `cap`
 * ($SHOWTIME_MAX_WORKERS).
 * -> {workers, why}
 */
export function autoWorkers({ cpus, memGB, software, frames, cap = 0, renderer = '' }) {
  const base = software ? Math.min(8, Math.max(1, Math.min(3, cpus - 2), Math.floor(cpus / 8))) : 3;
  const what = software
    ? `no GPU (${shortRenderer(renderer) || 'software GL'}): one browser per 8 of ${cpus} CPU threads, at least 3, at most 8`
    : `GPU${renderer && renderer !== 'unknown' ? ` (${shortRenderer(renderer)})` : ''}: 3`;
  const limits = [
    [Math.max(1, cpus - 2), `${cpus} CPU threads`],
    [Math.max(1, Math.floor(frames / 45)), `${frames} frames`],
    [Math.max(1, Math.floor((memGB * 0.5) / 1.5)), `${Math.round(memGB)} GB of memory`],
  ];
  if (cap > 0) limits.push([cap, `SHOWTIME_MAX_WORKERS=${cap}`]);
  let workers = base, by = null;
  for (const [n, why] of limits) if (n < workers) { workers = n; by = why; }
  return { workers, why: by ? `${what}; ${workers} because of ${by}` : what };
}

/**
 * Memory and CPU limits of this process (containers): os.totalmem() is the host's, so the memory a cgroup
 * allows (process.constrainedMemory) caps it; the cgroup v2 CPU quota (/sys/fs/cgroup/cpu.max, Linux) is
 * reported, since the CPU count may or may not follow it. -> {memGB, quotaCpus|null, note ('' when unlimited)}
 */
export function machineLimits({ totalBytes = os.totalmem(), constrained, cpuMax } = {}) {
  if (constrained === undefined) {
    try { constrained = typeof process.constrainedMemory === 'function' ? process.constrainedMemory() : 0; } catch { constrained = 0; }
  }
  if (cpuMax === undefined) {
    cpuMax = null;
    if (process.platform === 'linux') { try { cpuMax = fs.readFileSync('/sys/fs/cgroup/cpu.max', 'utf8'); } catch { /* no cgroup v2 */ } }
  }
  const notes = [];
  let bytes = totalBytes;
  if (constrained > 0 && constrained < totalBytes) {
    bytes = constrained;
    notes.push(`memory limit ${(constrained / 2 ** 30).toFixed(1)} GB of ${(totalBytes / 2 ** 30).toFixed(1)} GB`);
  }
  let quotaCpus = null;
  const m = /^\s*(\d+)\s+(\d+)/.exec(String(cpuMax || ''));
  if (m && Number(m[2]) > 0) {
    quotaCpus = +(Number(m[1]) / Number(m[2])).toFixed(2);
    notes.push(`cgroup cpu.max ${m[1]} ${m[2]} (${quotaCpus} CPUs)`);
  }
  return { memGB: bytes / 2 ** 30, quotaCpus, note: notes.join(', ') };
}

/** "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) ...), SwiftShader driver)" -> "SwiftShader". */
function shortRenderer(r) {
  const s = String(r || '');
  const m = /swiftshader|llvmpipe|softpipe|basic render driver|warp/i.exec(s);
  if (m) return m[0].toLowerCase() === 'swiftshader' ? 'SwiftShader' : m[0];
  const inner = /^ANGLE \(([^,]+),\s*([^,(]+)/.exec(s);
  return (inner ? inner[2] : s).trim().slice(0, 60);
}

/** Frames left in a lane: its current run and the runs it has not started. */
function laneLeft(lane) {
  return (lane.cur ? lane.cur.end - lane.cur.next : 0) + lane.pending.reduce((n, [s, e]) => n + e - s, 0);
}

export class CaptureQueue {
  /**
   * @param parts   one list of [s, e) runs per worker (splitPlan's output)
   * @param minSteal  a lane must have at least this many frames left to be split (the thief replays a
   *                  warm-up first: splitting less than about twice that costs more than it saves)
   */
  constructor(parts, { minSteal = 64 } = {}) {
    this.lanes = parts.map((runs) => ({ pending: runs.map(([s, e]) => [s, e]), cur: null, started: false }));
    this.minSteal = Math.max(2, minSteal);
    this.steals = 0;
    this.handed = [];          // [from worker, to worker, s, e] of every hand-over (for the log)
  }

  get workers() { return this.lanes.length; }

  /** Frames not yet claimed by any worker. */
  left() { return this.lanes.reduce((n, l) => n + laneLeft(l), 0); }

  /**
   * The next run for worker w: a live {s, next, end} that the worker walks with `claim` (another worker may
   * lower its `end` meanwhile), or null when there is nothing left worth taking.
   */
  take(w) {
    const lane = this.lanes[w];
    lane.cur = null;
    if (!lane.pending.length) this.steal(w);
    if (!lane.pending.length) return null;
    const [s, e] = lane.pending.shift();
    lane.cur = { s, next: s, end: e };
    lane.started = true;
    return lane.cur;
  }

  /** Claim the next frame of worker w's current run: a frame index, or null when the run is done. */
  claim(w) {
    const r = this.lanes[w].cur;
    if (!r || r.next >= r.end) return null;
    return r.next++;
  }

  /** Give frame i back to worker w's current run (a capture that failed and is retried). */
  unclaim(w, i) {
    const r = this.lanes[w].cur;
    if (r && i === r.next - 1) r.next = i;
  }

  /**
   * Move the back half of the fullest other lane to worker w's lane; all of it when that lane's worker has not
   * started yet (its page is still loading, or never will: its frames go to a worker that can draw them).
   */
  steal(w) {
    let victim = null, most = 0, vk = -1;
    this.lanes.forEach((l, k) => { if (k !== w) { const n = laneLeft(l); if (n > most) { most = n; victim = l; vk = k; } } });
    if (!victim || (victim.started && most < this.minSteal)) return false;
    let want = victim.started ? Math.floor(most / 2) : most;
    const got = [];
    // from the end: whole runs it has not started, then the tail of its current run
    while (want > 0 && victim.pending.length) {
      const last = victim.pending[victim.pending.length - 1];
      const n = last[1] - last[0];
      if (n <= want) { got.unshift(victim.pending.pop()); want -= n; } else { got.unshift([last[1] - want, last[1]]); last[1] -= want; want = 0; }
    }
    if (want > 0 && victim.cur) {
      const r = victim.cur;
      const n = Math.min(want, r.end - r.next);
      if (n > 0) { got.unshift([r.end - n, r.end]); r.end -= n; }
    }
    if (!got.length) return false;
    this.lanes[w].pending.push(...got);
    this.steals++;
    for (const [s, e] of got) this.handed.push([vk, w, s, e]);
    return true;
  }
}

/**
 * One ffmpeg fed the frames of `order` (frame indexes, in output order) through stdin, each as soon as it
 * is on disk. `ready(i)` says frame i is written; `hold(i, fn)` makes position i wait for fn() -> the file
 * to send instead (the poster bake). start() spawns ffmpeg; finish() resolves when the encode is done.
 */
export class OrderedFeed {
  constructor({ order, pathOf, args, onStderr }) {
    this.order = order;
    this.pathOf = pathOf;
    this.args = args;
    this.onStderr = onStderr;
    this.done = new Set();
    this.waiters = new Map();
    this.holds = new Map();
    this.fed = 0;
    this.failed = null;
    this.proc = null;
  }

  ready(i) {
    this.done.add(i);
    const w = this.waiters.get(i);
    if (w) { this.waiters.delete(i); w(); }
  }

  /** Resolves when frame i is on disk (or the feed failed). */
  wait(i) {
    if (this.done.has(i) || this.failed || this.dead) return Promise.resolve();
    return new Promise((r) => {
      const prev = this.waiters.get(i);
      this.waiters.set(i, prev ? () => { prev(); r(); } : r);
    });
  }

  hold(i, fn) { this.holds.set(i, fn); }

  start() {
    this.t0 = Date.now();
    this.proc = ffmpegPipe(this.args, { onStderr: this.onStderr });
    // an encoder that dies early stops the capture (finish() then says why)
    this.proc.done.then((r) => {
      if (r.code === 0) return;
      this.dead = true;
      for (const w of this.waiters.values()) w();
      this.waiters.clear();
    });
    this.pump = this.run().catch((e) => { this.fail(e); });
    return this;
  }

  async run() {
    const stdin = this.proc.stdin;
    let broken = null;
    stdin.on('error', (e) => { broken = e; });
    // an encoder can exit between two frames (after reading everything, so no EPIPE): Node has then closed its
    // stdin already, and a write would wait for a drain or close that never comes. Every await is followed
    // by a check, and the drain wait also ends when the pipe is gone or the encoder has exited.
    const gone = () => this.failed || this.dead || broken || stdin.destroyed || stdin.writableEnded;
    for (const i of this.order) {
      await this.wait(i);
      if (gone()) break;
      const fn = this.holds.get(i);
      const file = fn ? await fn() : this.pathOf(i);
      if (gone()) break;
      const buf = await fs.promises.readFile(file);
      if (gone()) break;
      if (!stdin.write(buf)) {
        await new Promise((r) => {
          let done = false;
          const go = () => {
            if (done) return;
            done = true;
            stdin.off('drain', go); stdin.off('close', go); stdin.off('error', go);
            r();
          };
          stdin.on('drain', go);
          stdin.on('close', go);
          stdin.on('error', go);
          this.proc.done.then(go);
          if (stdin.destroyed) go();
        });
      }
      this.fed++;
    }
    if (!stdin.destroyed) stdin.end();
  }

  /** Stop: kill the encoder and release every wait. */
  fail(e) {
    if (!this.failed) this.failed = e || new Error('stopped');
    for (const w of this.waiters.values()) w();
    this.waiters.clear();
    if (this.proc) this.proc.kill();
  }

  /** Wait for the encode to end. Rejects with ffmpeg's error, or with the reason the feed stopped. */
  async finish() {
    await this.pump;
    const r = await this.proc.done;
    if (this.failed && r.code === 0) throw this.failed;
    if (r.code !== 0) {
      const tail = String(r.stderr || '').trim().split('\n').slice(-8).join('\n');
      const e = new Error(`ffmpeg failed (exit ${r.code}): ${tail || '(no output)'}`);
      e.stderr = r.stderr;
      throw e;
    }
    if (this.fed !== this.order.length) throw new Error(`the encoder took ${this.fed} of ${this.order.length} frames`);
    return r;
  }
}

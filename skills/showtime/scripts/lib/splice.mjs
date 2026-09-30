// Splice a re-rendered span into a copy of an earlier full render (render --from/--to --job).
//
// A full render is H.264 with no B-frames, a closed GOP and an IDR frame at least every 2 s, so its
// bitstream can be cut at any IDR frame without touching the frames around the cut. The span is widened
// to the IDR frames around it, those frames are captured again and encoded with the same settings as a
// full render, and the new frames replace exactly that run of the old stream: every other frame is the
// old render's bytes, unchanged (no second encode, no quality loss). When the new encode's parameter sets
// differ from the old one's (another ffmpeg, other encode settings), the pieces cannot be joined as they
// are: the whole video is encoded once instead (old frames decoded, new frames from the capture).
import fs from 'node:fs';
import { ffmpeg, fpsArg } from './ff.mjs';

const START = Buffer.from([0, 0, 1]);
const NON_VCL_OPENERS = new Set([6, 7, 8, 9, 14, 15, 16, 17, 18]);

/** NAL units of an Annex B buffer: {pos (start code, with a 4-byte code's leading zero), hdr, end, type}. */
export function nalUnits(buf) {
  const out = [];
  let p = buf.indexOf(START, 0);
  while (p !== -1) {
    const hdr = p + 3;
    if (hdr >= buf.length) break;
    out.push({ pos: p > 0 && buf[p - 1] === 0 ? p - 1 : p, hdr, type: buf[hdr] & 0x1f });
    p = buf.indexOf(START, hdr);
  }
  for (let i = 0; i < out.length; i++) out[i].end = i + 1 < out.length ? out[i + 1].pos : buf.length;
  return out;
}

/** Access units (one per frame, in decode order) with their byte range and whether they hold an IDR slice. */
export function accessUnits(buf, nals = nalUnits(buf)) {
  const aus = [];
  let cur = null;
  let vcl = false;
  for (const n of nals) {
    const isVcl = n.type === 1 || n.type === 5;
    // a slice whose first_mb_in_slice is 0 (ue(v) '1' -> the first bit is set) starts a new picture
    const opens = isVcl ? (buf[n.hdr + 1] & 0x80) !== 0 : NON_VCL_OPENERS.has(n.type);
    if (!cur || (vcl && opens)) { cur = { start: n.pos, end: n.end, idr: false }; aus.push(cur); vcl = false; }
    cur.end = n.end;
    if (isVcl) vcl = true;
    if (n.type === 5) cur.idr = true;
  }
  return aus;
}

function nalBytes(buf, n) {
  let e = n.end;
  while (e > n.hdr && buf[e - 1] === 0) e--;
  return buf.subarray(n.hdr, e);
}

/** The distinct SPS and PPS payloads (hex) of a stream. */
export function paramSets(buf, nals = nalUnits(buf)) {
  const sps = new Set(), pps = new Set();
  for (const n of nals) {
    if (n.type === 7) sps.add(nalBytes(buf, n).toString('hex'));
    else if (n.type === 8) pps.add(nalBytes(buf, n).toString('hex'));
  }
  return { sps: [...sps], pps: [...pps] };
}

/** True when every parameter set of `seg` is the one parameter set pair of `base` (the pieces can be joined). */
export function sameParamSets(base, seg) {
  return base.sps.length === 1 && base.pps.length === 1 && seg.sps.length >= 1 && seg.pps.length >= 1
    && seg.sps.every((s) => s === base.sps[0]) && seg.pps.every((s) => s === base.pps[0]);
}

/** A stream read from disk: {buf, aus, params}. */
export function readStream(file) {
  const buf = fs.readFileSync(file);
  const nals = nalUnits(buf);
  return { buf, aus: accessUnits(buf, nals), params: paramSets(buf, nals) };
}

/** The .mp4's video as an Annex B .h264 file (stream copy, SPS/PPS in front of every IDR frame). */
export async function toAnnexB(mp4, out) {
  await ffmpeg(['-i', mp4, '-map', '0:v:0', '-c:v', 'copy', '-bsf:v', 'h264_mp4toannexb', '-f', 'h264', out]);
  return out;
}

/** Sorted, merged [s, e) frame ranges (touching ranges join). */
export function mergeRanges(ranges) {
  const rs = ranges.filter(([s, e]) => e > s).map(([s, e]) => [s, e]).sort((x, y) => x[0] - y[0]);
  const out = [];
  for (const r of rs) {
    const l = out[out.length - 1];
    if (l && r[0] <= l[1]) l[1] = Math.max(l[1], r[1]);
    else out.push(r);
  }
  return out;
}

/** [s, e) widened to the IDR frames around it: s down to an IDR frame, e up to the next one (or the end). */
export function gopRange(idr, total, s, e) {
  let a = 0;
  for (const k of idr) if (k <= s && k > a) a = k;
  let b = total;
  for (const k of idr) if (k >= e && k < b) b = k;
  return [a, b];
}

/** The capture plan ([s, e) runs) cut into `workers` lists of contiguous runs of about equal length. */
export function splitPlan(plan, workers) {
  const total = plan.reduce((n, [s, e]) => n + e - s, 0);
  const chunk = Math.ceil(total / Math.max(1, workers));
  const out = [];
  let cur = [], room = chunk;
  for (const [s0, e0] of plan) {
    let s = s0;
    while (s < e0) {
      const e = Math.min(e0, s + room);
      cur.push([s, e]);
      room -= e - s;
      s = e;
      if (room === 0) { out.push(cur); cur = []; room = chunk; }
    }
  }
  if (cur.length) out.push(cur);
  return out;
}

/** Indexes of the IDR frames. */
export function idrFrames(aus) {
  const out = [];
  aus.forEach((u, i) => { if (u.idr) out.push(i); });
  return out;
}

/** Write the joined stream: the base's frames outside `segments`, each segment's own frames inside.
 *  segments: [{range: [s, e), stream}] with stream.aus.length === e - s. */
export function joinStreams(base, segments, total, outFile) {
  const fd = fs.openSync(outFile, 'w');
  try {
    let at = 0;
    const put = (st, i0, i1) => {
      if (i1 <= i0) return;
      fs.writeSync(fd, st.buf, st.aus[i0].start, st.aus[i1 - 1].end - st.aus[i0].start);
    };
    for (const seg of segments.slice().sort((x, y) => x.range[0] - y.range[0])) {
      const [s, e] = seg.range;
      put(base, at, s);
      put(seg.stream, 0, e - s);
      at = e;
    }
    put(base, at, total);
  } finally { fs.closeSync(fd); }
  return outFile;
}

/** Mux an Annex B stream (constant fps) and an optional audio file into an .mp4, streams copied. The frame
 *  times are set from the frame count (N / fps, in the input's time base), so the file has exactly the
 *  timestamps of a full render: raw H.264 has none of its own, and ffmpeg's guesses drift by a few ticks. */
export async function muxAnnexB(h264, fps, audioFile, out) {
  const r = fpsArg(fps);
  const t = `N/((${r})*TB)`;
  await ffmpeg(['-f', 'h264', '-framerate', r, '-i', h264, ...(audioFile ? ['-i', audioFile] : []),
    '-map', '0:v:0', ...(audioFile ? ['-map', '1:a:0'] : []), '-c', 'copy',
    '-bsf:v', `setts=pts=${t}:dts=${t}:duration=1/((${r})*TB)`,
    '-video_track_timescale', '90000', '-movflags', '+faststart', out]);
  return out;
}

/** The fallback: one encode of the whole video, old frames decoded from `baseMp4` outside the segments and the
 *  captured frames inside them. segments: [{range: [s, e), pattern (image2 pattern), start (its first number)}].
 *  vf: the filter chain a full render applies to captured frames; codecArgs: its encoder arguments. */
export async function reencodeJoin({ baseMp4, segments, total, fps, vf, codecArgs, out, onStderr }) {
  const r = fpsArg(fps);
  const segs = segments.slice().sort((x, y) => x.range[0] - y.range[0]);
  const inputs = ['-i', baseMp4];
  const baseRanges = [];
  const order = [];
  let at = 0;
  segs.forEach((sg, k) => {
    if (sg.range[0] > at) { order.push(['base', baseRanges.length]); baseRanges.push([at, sg.range[0]]); }
    inputs.push('-framerate', r, '-start_number', String(sg.start), '-i', sg.pattern);
    order.push(['seg', k]);
    at = sg.range[1];
  });
  if (total > at) { order.push(['base', baseRanges.length]); baseRanges.push([at, total]); }
  const g = [];
  if (baseRanges.length) g.push(`[0:v]split=${baseRanges.length}${baseRanges.map((_, i) => `[b${i}]`).join('')}`);
  baseRanges.forEach(([s, e], i) => g.push(`[b${i}]trim=start_frame=${s}:end_frame=${e},setpts=PTS-STARTPTS,setsar=1[pb${i}]`));
  segs.forEach((sg, k) => g.push(`[${k + 1}:v]trim=end_frame=${sg.range[1] - sg.range[0]},setpts=PTS-STARTPTS,${vf},setsar=1[ps${k}]`));
  g.push(`${order.map(([w, i]) => (w === 'base' ? `[pb${i}]` : `[ps${i}]`)).join('')}concat=n=${order.length}:v=1:a=0[v]`);
  await ffmpeg([...inputs, '-filter_complex', g.join(';'), '-map', '[v]', ...codecArgs, '-r', r, '-an',
    '-progress', 'pipe:2', '-nostats', out], onStderr ? { onStderr } : {});
  return out;
}

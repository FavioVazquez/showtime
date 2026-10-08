// Fit a single-file export under its size limit by re-encoding the embedded footage (for this export
// only: the project's files are never touched). Used by `showtime export html` when the page's video
// clips push the file over --max-mb (16 MB for an HTML artifact).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ffmpeg, probe } from '../ff.mjs';

const MIN_VIDEO_KBPS = 150;     // below this footage turns to mush: fail with the breakdown instead
const AUDIO_KBPS = 64;          // a clip's own sound (page clips are usually muted; kept when present)
// x264's 2-pass rate control misses its bitrate on a short clip split over many frame threads (a 6 s clip at
// 1656 kb/s: 1.30 MB with 8 threads, 1.56 MB with 32, 1.85 MB with 64), and every miss costs another encode
const ENC_THREADS = String(Math.max(1, Math.min(8, (os.availableParallelism ? os.availableParallelism() : os.cpus().length) || 1)));
// a clip already re-encoded in this export -> { before, src, log, dur, audio, kbps, want }: a later pass (the
// first one landed over) encodes the project's own clip again from pass 1's stats, never the re-encoded copy
const fitted = new WeakMap();

/**
 * files: the export's file map (path -> {mime, bytes}). over: bytes (as packed, base64) to lose.
 * -> { items: [{path, before, after, kbps}], saved } ; items is empty when nothing could be shrunk.
 * Called again on the same map it re-encodes each clip from the project's original (before stays its size).
 */
export async function fitFootage(files, { over, workDir, say = () => {} }) {
  const vids = [...files].filter(([, f]) => /^video\//.test(f.mime) && f.bytes && f.bytes.length > 100 * 1000);
  const total = vids.reduce((n, [, f]) => n + f.bytes.length, 0);
  const out = { items: [], saved: 0, reason: null };
  if (!vids.length) { out.reason = 'no embedded footage to re-encode'; return out; }
  // base64 packs 3 bytes as 4; aim 6 % under the cut so the rewritten file lands inside the limit
  const cutRaw = Math.ceil((over * 3) / 4 * 1.06) + 32 * 1024;
  const scale = (total - cutRaw) / total;
  if (!(scale > 0.05)) { out.reason = `the footage would have to shrink to ${Math.max(0, Math.round(scale * 100))} % of its size`; return out; }
  fs.mkdirSync(workDir, { recursive: true });
  let k = 0;
  for (const [p, f] of vids) {
    const ext = (path.extname(p) || '.mp4').toLowerCase();
    const dst = path.join(workDir, `fit-out-${k}${ext}`);
    let prev = fitted.get(f);
    if (!prev) {
      const src = path.join(workDir, `fit-src-${k}${ext}`);
      fs.writeFileSync(src, f.bytes);
      let info;
      try { info = await probe(src); } catch { k++; continue; }
      const dur = Number(info.duration || (info.video && info.video.duration)) || 0;
      if (!(dur > 0.2) || !info.video) { k++; continue; }
      prev = { before: f.bytes.length, src, log: path.join(workDir, `fit-pass-${k}`), dur, audio: !!info.audio, kbps: 0 };
    }
    k++;
    const { src, log, dur, audio: hasAudio } = prev;
    const want = f.bytes.length * scale;
    // first time: the bitrate that fills `want`; again: the last bitrate scaled by how far its file must shrink,
    // and lower still by part of the last miss (an encoder that overshot overshoots more as the bitrate drops)
    const miss = prev.kbps ? Math.max(1, f.bytes.length / prev.want) : 1;
    const kbps = prev.kbps
      ? Math.floor((prev.kbps + (hasAudio ? AUDIO_KBPS : 0)) * (want / f.bytes.length) / Math.sqrt(miss) - (hasAudio ? AUDIO_KBPS : 0))
      : Math.floor((want * 8) / dur / 1000 - (hasAudio ? AUDIO_KBPS : 0));
    if (kbps < MIN_VIDEO_KBPS) { out.reason = `${p} would need ${Math.max(0, kbps)} kb/s (below ${MIN_VIDEO_KBPS})`; continue; }
    const vp9 = ext === '.webm';
    const venc = vp9
      ? ['-c:v', 'libvpx-vp9', '-b:v', `${kbps}k`, '-row-mt', '1', '-deadline', 'good', '-cpu-used', '2']
      : ['-c:v', 'libx264', '-preset', 'slow', '-b:v', `${kbps}k`, '-pix_fmt', 'yuv420p'];
    venc.push('-threads', ENC_THREADS);
    const aenc = hasAudio ? (vp9 ? ['-c:a', 'libopus', '-b:a', `${AUDIO_KBPS}k`] : ['-c:a', 'aac', '-b:a', `${AUDIO_KBPS}k`]) : ['-an'];
    const mux = vp9 ? [] : ['-movflags', '+faststart'];
    const timeout = Math.max(120000, dur * 30000);
    try {
      // pass 1 reads the source, not the bitrate: its stats serve every later pass of the same clip
      if (!prev.kbps) await ffmpeg(['-i', src, '-map', '0:v:0', ...venc, '-pass', '1', '-passlogfile', log, '-an', '-f', 'null', '-'], { timeout });
      await ffmpeg(['-i', src, '-map', '0:v:0', ...(hasAudio ? ['-map', '0:a:0'] : []), ...venc, '-pass', '2', '-passlogfile', log, ...aenc, ...mux, dst], { timeout });
    } catch (e) {
      out.reason = `re-encoding ${p} failed: ${String(e.message).split('\n')[0]}`;
      continue;
    }
    const nb = fs.readFileSync(dst);
    if (nb.length >= f.bytes.length) continue;
    fitted.set(f, { ...prev, kbps, want });
    out.items.push({ path: p, before: prev.before, after: nb.length, kbps });
    out.saved += f.bytes.length - nb.length;
    f.bytes = nb;
    say(`${p}: ${(prev.before / 1e6).toFixed(1)} MB -> ${(nb.length / 1e6).toFixed(1)} MB at ${kbps} kb/s`);
  }
  return out;
}

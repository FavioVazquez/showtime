// Fit a single-file export under its size limit by re-encoding the embedded footage (for this export
// only: the project's files are never touched). Used by `showtime export html` when the page's video
// clips push the file over --max-mb (16 MB for an HTML artifact).
import fs from 'node:fs';
import path from 'node:path';
import { ffmpeg, probe } from '../ff.mjs';

const MIN_VIDEO_KBPS = 150;     // below this footage turns to mush: fail with the breakdown instead
const AUDIO_KBPS = 64;          // a clip's own sound (page clips are usually muted; kept when present)

/**
 * files: the export's file map (path -> {mime, bytes}). over: bytes (as packed, base64) to lose.
 * -> { items: [{path, before, after, kbps}], saved } ; items is empty when nothing could be shrunk.
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
    const src = path.join(workDir, `fit-src-${k}${ext}`);
    const dst = path.join(workDir, `fit-out-${k}${ext}`);
    const log = path.join(workDir, `fit-pass-${k}`);
    k++;
    fs.writeFileSync(src, f.bytes);
    let info;
    try { info = await probe(src); } catch { continue; }
    const dur = Number(info.duration || (info.video && info.video.duration)) || 0;
    if (!(dur > 0.2) || !info.video) continue;
    const hasAudio = !!info.audio;
    const want = f.bytes.length * scale;
    const kbps = Math.floor((want * 8) / dur / 1000 - (hasAudio ? AUDIO_KBPS : 0));
    if (kbps < MIN_VIDEO_KBPS) { out.reason = `${p} would need ${Math.max(0, kbps)} kb/s (below ${MIN_VIDEO_KBPS})`; continue; }
    const vp9 = ext === '.webm';
    const venc = vp9
      ? ['-c:v', 'libvpx-vp9', '-b:v', `${kbps}k`, '-row-mt', '1', '-deadline', 'good', '-cpu-used', '2']
      : ['-c:v', 'libx264', '-preset', 'slow', '-b:v', `${kbps}k`, '-pix_fmt', 'yuv420p'];
    const aenc = hasAudio ? (vp9 ? ['-c:a', 'libopus', '-b:a', `${AUDIO_KBPS}k`] : ['-c:a', 'aac', '-b:a', `${AUDIO_KBPS}k`]) : ['-an'];
    const mux = vp9 ? [] : ['-movflags', '+faststart'];
    const timeout = Math.max(120000, dur * 30000);
    try {
      await ffmpeg(['-i', src, '-map', '0:v:0', ...venc, '-pass', '1', '-passlogfile', log, '-an', '-f', 'null', '-'], { timeout });
      await ffmpeg(['-i', src, '-map', '0:v:0', ...(hasAudio ? ['-map', '0:a:0'] : []), ...venc, '-pass', '2', '-passlogfile', log, ...aenc, ...mux, dst], { timeout });
    } catch (e) {
      out.reason = `re-encoding ${p} failed: ${String(e.message).split('\n')[0]}`;
      continue;
    }
    const nb = fs.readFileSync(dst);
    if (nb.length >= f.bytes.length) continue;
    out.items.push({ path: p, before: f.bytes.length, after: nb.length, kbps });
    out.saved += f.bytes.length - nb.length;
    f.bytes = nb;
    say(`${p}: ${(out.items.at(-1).before / 1e6).toFixed(1)} MB -> ${(nb.length / 1e6).toFixed(1)} MB at ${kbps} kb/s`);
  }
  return out;
}

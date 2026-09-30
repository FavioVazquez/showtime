// Frame sources shared by `showtime snap` and `showtime look`: a project (captured exactly like the
// renderer does) or a rendered video file (decoded with showtime's own ffmpeg).
import fs from 'node:fs';
import path from 'node:path';
import { startServer } from '../server.mjs';
import { resolveProject, info, c, UserError } from './cli.mjs';
import { openStage } from './stagehost.mjs';
import { resolveFF, ffmpeg, probe } from './ff.mjs';

export const VIDEO_EXT = /\.(mp4|mov|m4v|webm|mkv)$/i;

export const isVideo = (p) => VIDEO_EXT.test(String(p)) && fs.existsSync(p) && fs.statSync(p).isFile();

/** A source of frames: {kind, name, title, info: {duration, fps, width, height}, grab(t) -> png, close()} */
export async function openSource(arg, a, shared) {
  if (isVideo(arg)) {
    const file = path.resolve(arg);
    resolveFF();
    const pr = await probe(file);
    if (!pr.video) throw new UserError(`${file} has no video stream`);
    const fps = pr.video.fps || 30;
    const duration = pr.duration || pr.video.duration || 0;
    const tmp = path.join(shared.tmpDir, `grab-${path.basename(file)}.png`);
    return {
      kind: 'video', file, name: path.basename(file), title: path.basename(file), dir: path.dirname(file),
      info: { duration, fps, width: pr.video.width, height: pr.video.height, frames: pr.video.frames },
      async grab(t) {
        // accurate seek to half a frame before the wanted frame: the first frame decoded is that frame
        // the container can run longer than the video stream (audio tail): step back until a frame decodes
        for (let back = 0; back <= 1.0 + 1e-9 && !fs.existsSync(tmp); back += back < 0.2 ? 1 / fps : 0.25) {
          await ffmpeg(['-ss', Math.max(0, t - 0.5 / fps - back).toFixed(6), '-i', file, '-frames:v', '1', '-update', '1', tmp]);
          if (t - back <= 0) break;
        }
        if (!fs.existsSync(tmp)) throw new UserError(`could not decode a frame of ${path.basename(file)} at ${t.toFixed(3)} s`);
        const b = fs.readFileSync(tmp);
        fs.rmSync(tmp, { force: true });
        return b;
      },
      async close() {},
    };
  }
  const proj = resolveProject(arg || '.', { page: a.page });
  const server = await startServer({ root: proj.dir, port: 0 });
  const b = await shared.browser();
  const sess = await openStage(b.browser, { url: server.url, page: proj.page, config: proj.config, size: a.size });
  shared.serverUrl = shared.serverUrl || server.url;
  return {
    kind: 'project', dir: proj.dir, name: path.basename(proj.dir), title: proj.title, proj, sess, info: sess.info,
    async grab(t) {
      await sess.seek(t);
      // a <video> that did not reach its frame (seek timed out, codec error) shows the wrong picture: say so
      const d = await sess.diag().catch(() => null);
      const bad = d && d.videos ? Object.entries(d.videos) : [];
      for (const [k, v] of bad) if (!this.warned.has(k)) { this.warned.add(k); info(c.yellow(`snap: warning: video ${k}: ${v} (the still at ${t.toFixed(3)}s may show the wrong frame)`)); }
      return sess.shot({ format: 'png' });
    },
    warned: new Set(),
    async close() { await sess.close().catch(() => {}); await server.close().catch(() => {}); },
  };
}


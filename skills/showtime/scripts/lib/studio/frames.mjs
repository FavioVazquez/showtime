// Style frames for the studio board, captured through the same stage host + server that `showtime
// render` and `showtime snap` use, so a frame on the board matches the pixels of the final video.
//
//   captureFrames({root, page, config, override, shots: [{t, query, out, thumbOut}], width, thumbWidth})
//
// `root` is served at / (so a composition inside studio/comps/ can use ../media/fonts/...), `page` is
// the page path under it. A shot may add a query string (e.g. ?shot=hook) for compositions that draw
// several named frames, and/or a time t (seconds) for pages that animate on the stage clock.
import fs from 'node:fs';
import path from 'node:path';
import { startServer } from '../../server.mjs';
import { openBrowser, openPage } from '../stagehost.mjs';

export async function captureFrames({ root, page, config = {}, override = null, shots, width = 1280, thumbWidth = 480, quality = 90, gpu = 'auto' }) {
  const server = await startServer({ root, port: 0 });
  const b = await openBrowser({ gpu });
  const written = [];
  try {
    // group by query so each distinct page is opened once
    const groups = new Map();
    for (const s of shots) { const k = s.query || ''; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(s); }
    for (const [query, list] of groups) {
      const sess = await openPage(b, { url: server.url, page: page + query, config, override });
      try {
        const W = sess.width;
        for (const s of list) {
          await sess.seek(Math.max(0, s.t || 0));
          const main = await sess.shot({ format: /\.png$/i.test(s.out) ? 'png' : 'jpeg', quality, scale: Math.min(1, width / W) });
          fs.mkdirSync(path.dirname(s.out), { recursive: true });
          fs.writeFileSync(s.out, main);
          written.push(s.out);
          if (s.thumbOut) {
            const th = await sess.shot({ format: 'jpeg', quality: 82, scale: Math.min(1, thumbWidth / W) });
            fs.mkdirSync(path.dirname(s.thumbOut), { recursive: true });
            fs.writeFileSync(s.thumbOut, th);
            written.push(s.thumbOut);
          }
        }
        if (sess.log.errors.length) written.errors = (written.errors || []).concat(sess.log.errors.map((e) => e.message));
        if (sess.log.blocked.length) written.blocked = (written.blocked || []).concat(sess.log.blocked);
      } finally { await sess.close(); }
    }
  } finally {
    await b.browser.close().catch(() => {});
    await server.close();
  }
  return written;
}

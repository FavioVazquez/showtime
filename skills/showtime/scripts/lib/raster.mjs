// Rasterize SVG files to PNG with headless Chrome (transparent background by default).
//
//   node raster.mjs in.svg out.png [--size 512] [--background "#fff"]
//   node raster.mjs --batch jobs.json          # [{"in": "a.svg", "out": "a.png", "size": 256}, ...]
//
// --size is the longer side in pixels; the aspect ratio comes from the SVG viewBox.
// Used by `showtime assets icon --png` and `showtime assets emoji --format png`.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { launchGuarded, openGuarded, closeSoon } from './stagehost.mjs';

function aspectOf(svg) {
  const vb = /viewBox\s*=\s*"([^"]+)"/i.exec(svg);
  if (vb) {
    const p = vb[1].trim().split(/[\s,]+/).map(Number);
    if (p.length === 4 && p[2] > 0 && p[3] > 0) return p[2] / p[3];
  }
  const w = /\swidth\s*=\s*"([\d.]+)/i.exec(svg), h = /\sheight\s*=\s*"([\d.]+)/i.exec(svg);
  if (w && h && Number(h[1]) > 0) return Number(w[1]) / Number(h[1]);
  return 1;
}

export async function rasterize(jobs, { background = null } = {}) {
  const b = await launchGuarded({ gpu: 'off' });
  try {
    // the context and the tab under the page-open deadline (once more in a new browser)
    const { page } = await openGuarded(b, async (browser, track) => {
      track.step = 'creating the browser context';
      const ctx = await browser.newContext({ deviceScaleFactor: 1 });
      track.step = 'opening a tab';
      return { page: await ctx.newPage(), close: () => ctx.close() };
    }, { label: 'opening the drawing page' });
    const out = [];
    for (const job of jobs) {
      const svg = fs.readFileSync(job.in, 'utf8');
      const size = Math.max(8, Math.min(8192, Number(job.size) || 512));
      const a = aspectOf(svg);
      const w = Math.round(a >= 1 ? size : size * a), h = Math.round(a >= 1 ? size / a : size);
      await page.setViewportSize({ width: w, height: h });
      const bg = job.background || background;
      const data = 'data:image/svg+xml;base64,' + Buffer.from(svg).toString('base64');
      await page.setContent(`<!doctype html><html><head><style>html,body{margin:0;padding:0;width:${w}px;height:${h}px;` +
        `background:${bg ? bg : 'transparent'};overflow:hidden}img{display:block;width:${w}px;height:${h}px}</style></head>` +
        `<body><img id="i" src="${data}"></body></html>`);
      await page.evaluate(() => document.getElementById('i').decode().catch(() => {}));
      fs.mkdirSync(path.dirname(path.resolve(job.out)), { recursive: true });
      await page.screenshot({ path: job.out, omitBackground: !bg, type: 'png' });
      out.push({ in: job.in, out: job.out, width: w, height: h });
    }
    return out;
  } finally {
    await closeSoon(b.browser.close());
  }
}

const isMain = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const argv = process.argv.slice(2);
  const opt = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
  if (!argv.length || argv.includes('--help') || argv.includes('-h')) {
    console.log('usage: node raster.mjs in.svg out.png [--size 512] [--background COLOR] | --batch jobs.json');
    process.exit(argv.length ? 0 : 2);
  }
  let jobs;
  if (argv.includes('--batch')) jobs = JSON.parse(fs.readFileSync(opt('--batch'), 'utf8'));
  else jobs = [{ in: argv[0], out: argv[1], size: Number(opt('--size', 512)) }];
  rasterize(jobs, { background: opt('--background', null) })
    .then((r) => { console.log(JSON.stringify(r)); })
    .catch((e) => { console.error(`raster: ${e.message || e}`); process.exit(1); });
}

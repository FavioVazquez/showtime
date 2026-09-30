// Stills at chosen times and a labelled contact sheet: of a project (captured exactly like the
// renderer does) or of a rendered video file (decoded with showtime's own ffmpeg), plus
// before/after pairs against another video or project (--compare).
import fs from 'node:fs';
import path from 'node:path';
import { startServer } from './server.mjs';
import { parseCli, runMain, info, c, fmtTime, parseTimes, parseTime, jobDir, workName, UserError } from './lib/cli.mjs';
import { openBrowser, openLab, parseSize } from './lib/stagehost.mjs';
import { enclosingJob } from './lib/studio/paths.mjs';
import { VIDEO_EXT, openSource } from './lib/frames.mjs';

const SPEC = {
  name: 'snap',
  usage: 'showtime snap <project or video> [--at 1,2.5] [--sheet] [--every 1s | --count 12] [--compare OTHER] [-o DIR]',
  summary: 'Capture still frames of a project or a rendered video, a contact sheet, or before/after pairs.',
  description: [
    'Without --at, makes a contact sheet of --count evenly spaced frames (default 12, plus the last frame).',
    'With --at, writes one image per time; add --sheet to also put those times on a sheet.',
    'A time snaps to the nearest frame; files are named by the time you asked for (t0002.500s.png) and',
    'the frame each one shows is printed when it differs.',
    'A project is captured pixel-identical to the render; a video file (.mp4/.mov/.webm) is decoded with',
    "showtime's ffmpeg (a footage edit, the shipped final, an export).",
    '--compare OTHER (a video or a project) snaps the same --at times there too and writes compare.jpg:',
    'OTHER (before) on the left, the main input (after) on the right.',
    'Output: <project>/work/snap/, <job>/work/snap/<video name>/ for a video inside a job, else a new',
    './showtime-out/snap-<name>-<time>/ (a --page other than index.html or a --size gets its own',
    'work/snap-<page>[-<size>]/); -o picks a folder, or with one --at a file (-o media/map.jpg).',
    'A page that sets its own size with ST.config is captured at that size; --size 1080x1920 (or 9:16)',
    'captures one page at another size for this run.',
  ].join('\n'),
  options: {
    at: { help: 'comma-separated times in seconds (e.g. 0.5,2,3.75 or 1:02.5)' },
    sheet: { type: 'boolean', help: 'make a contact sheet (default when --at is not given)' },
    every: { help: 'sheet: one frame every S seconds (e.g. 1 or 0.5s)', metavar: 'S' },
    count: { help: 'sheet: number of evenly spaced frames (default 12)', metavar: 'N' },
    compare: { help: 'before/after: the same --at times of this video or project, side by side', metavar: 'OTHER' },
    cols: { help: 'sheet: columns (default: 3-6 depending on count and aspect)' },
    thumb: { help: 'sheet: thumbnail width in px (default 400; 270 for vertical)' },
    width: { help: 'stills: output width in px (default: full size)' },
    format: { help: 'stills: png (default) or jpg' },
    output: { short: 'o', help: 'output folder (default: see above)', metavar: 'DIR' },
    page: { help: 'page inside the project (default index.html)' },
    size: { help: 'project: capture at this size for this run: WxH (1080x1920) or an aspect (9:16, 1:1)', metavar: 'SIZE' },
    gpu: { help: 'auto (default) or off' },
    json: { type: 'boolean', help: 'print {stills, sheet, compare} as JSON' },
  },
  examples: [
    'showtime snap my-video                          # contact sheet of 12 frames',
    'showtime snap my-video --every 1                # one frame per second on a sheet',
    'showtime snap my-video --at 2.5,7 --width 960   # two stills',
    'showtime snap my-video --at 0,1,2,3 --sheet',
    'showtime snap showtime-out/launch-20260926-101500/final-3.mp4 --at 12.9,13.0',
    'showtime snap final-3.mp4 --at 4.2,9.5 --compare final-2.mp4    # before|after sheet',
    'showtime snap clip.mp4 --at 7.5 --width 1920 -o media/map.jpg    # one still, named',
    'showtime snap my-video --page square.html --size 1:1 --at 3'
  ],
};

function defaultOut(src, a) {
  if (src.kind === 'project') return path.join(src.dir, 'work', workName('snap', src.proj.page, parseSize(a.size)));
  const job = enclosingJob(src.file);
  const stem = path.basename(src.file).replace(VIDEO_EXT, '');
  if (job) return path.join(job, 'work', 'snap', stem);
  return jobDir(`snap-${stem}`);
}

async function main() {
  const a = parseCli(SPEC);
  const fmtOf = a.output && /\.(png|jpe?g)$/i.test(String(a.output)) ? String(a.output).split('.').pop() : null;
  const fmt = (a.format || fmtOf || 'png').toLowerCase().replace('jpeg', 'jpg');
  if (!['png', 'jpg'].includes(fmt)) throw new UserError('--format must be png or jpg');
  const atTimes = parseTimes(a.at);
  if (a.compare && !atTimes.length) throw new UserError('--compare needs --at (the times to compare)', 'e.g. showtime snap final-3.mp4 --at 4.2,9.5 --compare final-2.mp4');
  const wantSheet = a.sheet || !atTimes.length;

  let browser = null;
  let lab = null;
  let labServer = null;
  const shared = {
    tmpDir: null,
    serverUrl: null,
    async browser() { if (!browser) browser = await openBrowser({ gpu: a.gpu || 'auto' }); return browser; },
  };
  const tmpRoot = fs.mkdtempSync(path.join((await import('node:os')).tmpdir(), 'st-snap-'));
  shared.tmpDir = tmpRoot;
  const sources = [];
  try {
    const src = await openSource(a._[0] || '.', a, shared);
    sources.push(src);
    const other = a.compare ? await openSource(a.compare, a, shared) : null;
    if (other) sources.push(other);
    // -o picture.jpg with one --at: that file
    const toFile = a.output && /\.(png|jpe?g)$/i.test(String(a.output)) ? path.resolve(a.output) : null;
    if (toFile && (atTimes.length !== 1 || wantSheet || a.compare)) throw new UserError('-o <file.png|.jpg> takes exactly one --at time (no --sheet or --compare)', 'give a folder to -o for several stills');
    const outDir = toFile ? path.dirname(toFile) : path.resolve(a.output || defaultOut(src, a));
    fs.mkdirSync(outDir, { recursive: true });
    const { duration: D, fps, width: W, height: H } = src.info;
    const nFrames = Math.max(1, Math.round(D * fps));
    const lastK = nFrames - 1;
    const lastT = lastK / fps;
    // nearest frame (a render samples frame k at k/fps)
    const kOf = (x) => Math.min(lastK, Math.max(0, Math.round(x * fps - 1e-9)));
    const q = (x) => kOf(x) / fps;
    for (const x of atTimes) if (x < 0 || x > D + 1e-6) throw new UserError(`--at ${x} is outside the video (0-${D}s)`);
    let sheetTimes = [];
    if (wantSheet && !a.compare) {
      if (atTimes.length) sheetTimes = atTimes.map(q);
      else if (a.every) {
        const ev = parseTime(a.every);
        if (!(ev > 0)) throw new UserError('--every must be > 0');
        if (ev < 1 / fps) info(c.yellow(`  --every ${ev} is shorter than one frame (${(1 / fps).toFixed(3)} s): one frame per step instead`));
        const step = Math.max(ev, 1 / fps);
        for (let x = 0; x <= lastT + 1e-9 && sheetTimes.length < 200; x += step) sheetTimes.push(q(x));
        if (sheetTimes.length >= 200) info(c.yellow('  (capped at 200 frames; use a larger --every)'));
      } else {
        const n = Math.max(1, Math.min(200, Number(a.count || 12)));
        for (let i = 0; i < n; i++) sheetTimes.push(q(((i + 0.5) / n) * D));
        sheetTimes.push(lastT);
      }
      sheetTimes = [...new Set(sheetTimes.map((x) => +x.toFixed(6)))].sort((x, y) => x - y);
    }
    const all = [...new Set([...atTimes.map(q), ...sheetTimes].map((x) => +x.toFixed(6)))].sort((x, y) => x - y);
    // the lab page (sheets, resizing) is served by the project server, or a tiny one for video files
    if (!shared.serverUrl) { labServer = await startServer({ root: tmpRoot, port: 0 }); shared.serverUrl = labServer.url; }
    lab = await openLab((await shared.browser()).browser, shared.serverUrl);
    const shots = new Map();
    // keys are rounded to 6 decimals; seek the exact frame time (k / fps): a rounded time can fall a hair
    // before the frame boundary, and the stage floors it to the previous frame
    for (const t of all) shots.set(t, await src.grab(Math.round(t * fps) / fps));
    const stills = [];
    const notes = [];
    const seen = new Map();
    for (const x of atTimes) {
      const t = +q(x).toFixed(6);
      const k = kOf(x);
      const file = toFile || path.join(outDir, `t${x.toFixed(3).padStart(8, '0')}s.${fmt}`);
      let out = shots.get(t);
      const w = a.width ? Number(a.width) : null;
      // --width larger than the source upscales (high-quality smoothing); say so, it adds no detail
      if (w && w > W) notes.push(`upscaled ${W} -> ${w} px wide (no new detail)`);
      if (w && w !== W) out = await lab.resize(out, w, fmt === 'png' ? 'image/png' : 'image/jpeg', 0.92);
      else if (fmt === 'jpg') out = await lab.resize(out, W, 'image/jpeg', 0.92);
      fs.writeFileSync(file, out);
      stills.push({ at: x, t, frame: k, file });
      if (Math.abs(t - x) > 1e-4) notes.push(`${x} -> frame ${k} (${t.toFixed(3)} s)`);
      if (seen.has(k)) notes.push(`${x} shows the same frame as ${seen.get(k)} (frame ${k})`);
      else seen.set(k, x);
    }
    let sheet = null;
    if (sheetTimes.length) {
      const n = sheetTimes.length;
      const vertical = H > W;
      const cols = a.cols ? Number(a.cols) : n <= 4 ? n : vertical ? Math.min(6, Math.ceil(Math.sqrt(n * 1.8))) : n <= 9 ? 3 : n <= 16 ? 4 : 5;
      const thumb = Number(a.thumb) || (vertical ? 270 : 400);
      // shrink each frame to its thumbnail first, one at a time: a hundred full-size frames sent to the
      // lab page in one message can exhaust the browser's memory (1080p masters, --every 1)
      const items = [];
      for (const t of sheetTimes) {
        let b = shots.get(t);
        if (n > 12 && thumb * 1.5 < W) b = await lab.resize(b, Math.round(thumb * 1.5), 'image/jpeg', 0.9);
        items.push({ buf: b, label: fmtTime(t), sub: `f${Math.round(t * fps)}` });
      }
      const buf = await lab.sheet(items, { cols, thumb, title: `${src.title}  ${W}x${H} ${+fps.toFixed(3)}fps ${D.toFixed(2)}s` });
      sheet = path.join(outDir, 'sheet.jpg');
      fs.writeFileSync(sheet, buf);
    }
    let compare = null;
    if (other) {
      const ofps = other.info.fps;
      const oLast = Math.max(0, Math.round(other.info.duration * ofps) - 1);
      const items = [];
      for (const x of atTimes) {
        const ok = Math.min(oLast, Math.max(0, Math.round(x * ofps - 1e-9)));
        const before = await other.grab(ok / ofps);
        items.push({ buf: before, label: `before ${fmtTime(x)}`, sub: other.name });
        items.push({ buf: shots.get(+q(x).toFixed(6)), label: `after ${fmtTime(x)}`, sub: src.name });
      }
      const vertical = H > W;
      const buf = await lab.sheet(items, { cols: 2, thumb: Number(a.thumb) || (vertical ? 360 : 640), title: `before: ${other.name}   after: ${src.name}` });
      compare = path.join(outDir, 'compare.jpg');
      fs.writeFileSync(compare, buf);
    }
    const errs = src.kind === 'project' ? src.sess.log.errors : [];
    if (a.json) {
      process.stdout.write(JSON.stringify({ source: src.kind === 'project' ? src.dir : src.file, kind: src.kind, stills, sheet, compare, notes, pageErrors: errs.map((e) => e.message) }, null, 2) + '\n');
    } else {
      for (const s of stills) console.log(`still  ${fmtTime(s.at)}  ${s.file}`);
      for (const n of notes) console.log(c.dim(`  ${n}`));
      if (sheet) console.log(`sheet  ${sheetTimes.length} frames  ${sheet}`);
      if (compare) console.log(`compare  ${atTimes.length} pair(s)  ${compare}`);
      if (errs.length) console.log(c.yellow(`  ${errs.length} page error(s), first: ${errs[0].message} (run \`showtime check\`)`));
    }
    return 0;
  } finally {
    if (lab) await lab.close();
    for (const s of sources) await s.close();
    if (browser) await browser.browser.close().catch(() => {});
    if (labServer) await labServer.close().catch(() => {});
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  }
}

runMain(main);

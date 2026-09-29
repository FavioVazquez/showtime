// Render a project to MP4: frames from headless Chrome, H.264 BT.709 encode, offline audio, loudness, poster
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { startServer } from './server.mjs';
import {
  parseCli, runMain, resolveProject, jobDir, freshPath, Progress, info, warn, c, cpuCount, fmtDuration, fmtBytes,
  parseTime, runPyCli, hasPyModule, UserError, progressLog,
} from './lib/cli.mjs';
import { openBrowser, openStage, writeDiagnostics, pullScore, parseSize } from './lib/stagehost.mjs';
import { resolveFF, ffmpeg, probe, ebur128, writeWavFloat, fpsArg, hasEncoder, setLogFile, logLine, meanFrameDiff } from './lib/ff.mjs';
import { mixFromConfig, master } from './lib/audio.mjs';
import { resolveJobDir, enclosingJob } from './lib/studio/paths.mjs';
import { showCard, fmtLen, openHint, shellPath } from './lib/delight.mjs';

const AAC_HEADROOM_DB = 0.5;
// mean grayscale difference (0-255, 64x36) above which a baked poster would visibly flash at frame 0
const POSTER_FLASH_DIFF = 12;
const SIZE_HINT_BYTES = 20e6;
const HIGH_MBPS = 25;   // a 1080p final above this is almost always animated grain or noise (a typical final: 2-12 Mb/s)

const SPEC = {
  name: 'render',
  usage: 'showtime render <project> [-o out.mp4 | --job JOB] [--preview] [--from S --to S] [--workers N] [--scale X] [--alpha prores|animation|webm]',
  summary: 'Render a showtime project (a folder with showtime.json + index.html) to a video file.',
  description: [
    'Every frame is captured in order from headless Chrome after ST.seek(t), encoded once with',
    'H.264 (BT.709, yuv420p, +faststart), and muxed with the audio: ST.score (rendered offline) and',
    'the showtime.json "audio" mix, loudness-normalised to -14 LUFS / -1 dBTP by default.',
    'Output goes to ./showtime-out/<title>-<timestamp>/ (final.mp4 or preview.mp4, poster.jpg, render.json, work/).',
    'With --job (a job folder or name) it goes into that job: final.mp4 / preview.mp4, or final-2.mp4 ... when',
    'one exists (renders never overwrite). A render into a job (--job, or -o inside a job folder) records',
    'itself in job.json "outputs" (final/preview, poster, credits), so `showtime qa <job>` checks the newest',
    'file. credits.txt is written next to the video whenever the mix used CC-BY material.',
    'Encode defaults can live in showtime.json "render": {"crf": 22, "x264_preset": "slow", "format": "png",',
    '"quality": 92, "poster": "none"}; flags override them, so every re-render keeps the same settings.',
  ].join('\n'),
  options: {
    output: { short: 'o', help: 'output file (default: a new folder under ./showtime-out/)', metavar: 'FILE' },
    'out-dir': { help: 'base folder for the showtime-out/ job folder (default: $SHOWTIME_OUT or cwd)', metavar: 'DIR' },
    job: { short: 'j', help: 'render into this job (folder, or name -> newest showtime-out/<name>-<ts>/)', metavar: 'JOB' },
    preview: { type: 'boolean', short: 'p', help: 'fast draft: <=720p, veryfast encode, no poster bake' },
    fps: { help: 'frames per second (default: showtime.json fps, else 30)' },
    from: { help: 'start time in seconds (default 0)', metavar: 'S' },
    to: { help: 'end time in seconds (default: the full duration)', metavar: 'S' },
    workers: { short: 'w', help: 'parallel browsers, 1-3 (default: auto, at most $SHOWTIME_MAX_WORKERS when set)' },
    scale: { help: 'output scale, e.g. 0.5 for half size or 2 for supersampled 4K (default 1; --preview: fit 720p)' },
    alpha: { help: 'transparent output: prores (.mov ProRes 4444, large), animation (.mov QuickTime Animation: lossless RGBA, far smaller for flat graphics such as lower thirds and stingers) or webm (VP9 with alpha, web)', metavar: 'KIND' },
    format: { help: 'frame capture format: jpeg (default, fast) or png (lossless, ~3x slower)' },
    quality: { help: 'jpeg capture quality 1-100 (default 92)' },
    crf: { help: 'x264 CRF (default 16 final, 23 preview; lower = better/larger)' },
    'x264-preset': { help: 'x264 preset (default medium final, veryfast preview)', metavar: 'NAME' },
    poster: { help: 'bake the frame at S seconds into frame 0 (default: showtime.json "poster"); "none" to skip', metavar: 'S' },
    lufs: { help: 'loudness target in LUFS (default: showtime.json "loudness" or -14)' },
    'no-loudnorm': { type: 'boolean', help: 'keep the audio level as mixed' },
    'no-audio': { type: 'boolean', help: 'video only' },
    'allow-silent': { type: 'boolean', help: 'finish without audio when the soundtrack fails (default: a project with ST.score or an "audio" mix fails the render instead)' },
    'poster-bake': { help: 'auto (default: bake only when the poster frame looks like the opening frame), force, or off', metavar: 'MODE' },
    gpu: { help: 'auto (default, hardware GPU) or off (software, slower, most reproducible)' },
    page: { help: 'page inside the project to render (default index.html)' },
    size: { help: 'render at this size for this run: WxH (1080x1920) or an aspect (9:16, 1:1, 4:5); beats showtime.json and ST.config. With --job the file is <job>/<W>x<H>.mp4, a variant that leaves the job\'s final alone', metavar: 'SIZE' },
    settle: { help: 'paint wait per frame: raf1 (default), raf2 (extra safe), none (fastest, can miss paints)' },
    'keep-frames': { type: 'boolean', help: 'keep work/frames after a successful render' },
    'no-check': { type: 'boolean', help: 'with --size: skip the layout check at that size (it stops the render when text is cut off or off frame there)' },
    json: { type: 'boolean', help: 'print a JSON report on stdout' },
    quiet: { type: 'boolean', short: 'q', help: 'no progress output' },
  },
  examples: [
    'showtime render my-video                      # final render -> showtime-out/my-video-<ts>/final.mp4',
    'showtime render my-video --preview            # quick 720p draft',
    'showtime render my-video --from 12 --to 18    # re-render one section',
    'showtime render my-video -o launch.mp4 --workers 2',
    'showtime render my-video --job launch-teaser        # -> <job>/final.mp4 (final-2.mp4 on a re-render)',
    'showtime render my-video --job launch-teaser --size 9:16   # the same page in 9:16 -> <job>/1080x1920.mp4',
    'showtime render overlay --alpha prores        # transparent lower third for an editor',
    'showtime render sting --alpha animation       # same for flat graphics, a fraction of the ProRes size',
  ],
};

const even = (n) => Math.max(2, 2 * Math.round(n / 2));
const WARMUP_S = Number(process.env.SHOWTIME_WARMUP || 1); // seconds replayed before each chunk

async function main() {
  const a = parseCli(SPEC);
  const T0 = Date.now();
  const timings = {};
  const warnings = [];
  const addWarn = (m) => { warnings.push(m); warn(m); logLine(`warning: ${m}`); };
  const quiet = !!a.quiet;
  const say = (m) => { if (!quiet) info(m); };

  if (a._.length > 1) throw new UserError(`expected one project, got: ${a._.join(' ')}`, 'showtime render <project-folder>');
  const proj = resolveProject(a._[0] || '.', { page: a.page });
  const cfg = { ...proj.config };
  // encode defaults from showtime.json "render" (flags win), so a re-render keeps the shipped settings
  const rcfg = cfg.render && typeof cfg.render === 'object' ? cfg.render : {};
  const RENDER_KEYS = { crf: 'crf', x264_preset: 'x264-preset', 'x264-preset': 'x264-preset', format: 'format', quality: 'quality', poster: 'poster', settle: 'settle', workers: 'workers', lufs: 'lufs', 'poster_bake': 'poster-bake' };
  const fromCfg = [];
  if (!a.preview) {
    for (const [k, v] of Object.entries(rcfg)) {
      const flag = RENDER_KEYS[k];
      if (!flag) { warn(`showtime.json "render": unknown key "${k}" (known: ${Object.keys(RENDER_KEYS).filter((x) => !x.includes('-')).join(', ')})`); continue; }
      if (a[flag] === undefined && v !== null && v !== undefined) { a[flag] = String(v); fromCfg.push(`${k} ${v}`); }
    }
  }
  const override = {};
  // --size: one page, another size for this run (a 9:16 cut of a 16:9 page reads the frame aspect)
  const size = parseSize(a.size);
  if (size) { cfg.width = size.width; cfg.height = size.height; override.width = size.width; override.height = size.height; }
  // Another size re-lays the page: text that fits at 16:9 can be cut off at 9:16. Check the layout at THIS
  // size first, so a clipped line never ships silently (--no-check skips it).
  if (size && !a.preview && !a['no-check']) {
    const checkJs = path.join(path.dirname(fileURLToPath(import.meta.url)), 'check.mjs');
    if (!a.quiet) info(`checking the layout at ${size.width}x${size.height} before rendering (--no-check skips this)`);
    const r = spawnSync(process.execPath, [checkJs, proj.dir, '--size', `${size.width}x${size.height}`, '--no-determinism', '--json'],
      { encoding: 'utf8', env: process.env, maxBuffer: 64 * 1024 * 1024 });
    let rep = null;
    try { rep = JSON.parse(r.stdout); } catch { rep = null; }
    const LAYOUT = new Set(['text_clipped', 'text_off_canvas', 'safe_zone', 'text_overlap', 'overflow']);
    const bad = rep ? rep.findings.filter((f) => f.severity === 'error' && (LAYOUT.has(f.code) || /clip|off_canvas|overflow/.test(f.code))) : [];
    if (bad.length) {
      throw new UserError(`the layout breaks at ${size.width}x${size.height} (the page re-lays itself for this size and some text no longer fits): ${bad.slice(0, 4).map((f) => f.message).join('; ')}`,
        `showtime check ${path.relative(process.cwd(), proj.dir) || '.'} --size ${a.size}, fix the layout for that size (terminals and code lines: data-st="fit"), or --no-check to render anyway`);
    }
  }
  if (a.fps !== undefined) { const f = Number(a.fps); if (!(f > 0 && f <= 240)) throw new UserError(`--fps must be between 1 and 240 (got ${a.fps})`); override.fps = f; }
  const alpha = a.alpha ? String(a.alpha).toLowerCase() : null;
  if (alpha && !['prores', 'webm', 'animation'].includes(alpha)) throw new UserError(`--alpha must be prores, animation or webm (got ${a.alpha})`);
  const format = alpha ? 'png' : (a.format || 'jpeg').toLowerCase();
  if (!['jpeg', 'jpg', 'png'].includes(format)) throw new UserError(`--format must be jpeg or png (got ${a.format})`);
  const capFormat = format === 'jpg' ? 'jpeg' : format;
  const quality = a.quality ? Math.max(1, Math.min(100, Number(a.quality))) : 92;
  const gpu = a.gpu || 'auto';
  const settle = a.settle || 'raf1';
  if (!['raf2', 'raf1', 'none'].includes(settle)) throw new UserError('--settle must be raf2, raf1 or none');
  resolveFF(); // fail early if ffmpeg is missing
  const needEnc = alpha === 'prores' ? 'prores_ks' : alpha === 'webm' ? 'libvpx-vp9' : alpha === 'animation' ? 'qtrle' : 'libx264';
  if (!hasEncoder(needEnc)) {
    throw new UserError(`this ffmpeg build has no ${needEnc} encoder`, alpha ? `use --alpha ${alpha === 'webm' ? 'prores' : 'webm'} instead, or install a full build with \`showtime setup\`` : 'run `showtime setup` to install a full ffmpeg build');
  }

  // ---- output location (never overwrite an earlier render)
  const stemName = a.preview ? 'preview' : 'final';
  let outFile, outDir, workDir;
  const ext = alpha === 'prores' || alpha === 'animation' ? '.mov' : alpha === 'webm' ? '.webm' : '.mp4';
  if (a.output && a.job) throw new UserError('pass either -o or --job, not both', 'use --job <job> to render into the job folder');
  let jobFolder = null;
  let renamedFrom = null;
  if (a.job) {
    jobFolder = resolveJobDir(a.job);
    if (!jobFolder || !fs.existsSync(jobFolder)) throw new UserError(`no job named "${a.job}"`, 'list jobs with `showtime job list`, or create one: showtime job init <slug>');
    a.output = path.join(jobFolder, (size && !a.preview ? `${size.width}x${size.height}` : stemName) + ext);
  }
  if (a.output) {
    const want = path.resolve(a.output);
    outFile = freshPath(path.extname(want) ? want : want + ext);
    // an intended re-render: an info line, not a warning (renders never overwrite)
    if (outFile !== want && path.extname(want)) { renamedFrom = want; logLine(`${want} exists; writing ${path.basename(outFile)} instead`); }
    outDir = path.dirname(outFile);
    fs.mkdirSync(outDir, { recursive: true });
    workDir = path.join(outDir, `${path.basename(outFile, path.extname(outFile))}.work`);
    // studio media (animatics, look tests) keep studio/ small: their scratch goes to <job>/work/renders/
    const sj = enclosingJob(outFile);
    if (sj && !path.relative(path.join(sj, 'studio'), outFile).startsWith('..')) {
      workDir = path.join(sj, 'work', 'renders', `${path.basename(outFile, path.extname(outFile))}.work`);
    }
  } else {
    outDir = jobDir(proj.slug, a['out-dir']);
    outFile = path.join(outDir, stemName + ext);
    workDir = path.join(outDir, 'work');
  }
  const framesDir = path.join(workDir, 'frames');
  const audioDir = path.join(workDir, 'audio');
  const diagDir = path.join(workDir, 'diagnostics');
  fs.rmSync(framesDir, { recursive: true, force: true });
  fs.mkdirSync(framesDir, { recursive: true });
  fs.mkdirSync(audioDir, { recursive: true });
  // the full ffmpeg / browser story of this render (read by `showtime report` and when a render fails)
  const logFile = path.join(workDir, 'logs', 'render.log');
  setLogFile(logFile);
  logLine(`showtime render ${proj.dir} -> ${outFile}${a.preview ? ' (preview)' : ''}; node ${process.version} ${process.platform}-${process.arch}`);

  say(`${c.bold('showtime render')} ${proj.dir}${a.preview ? c.dim('  (preview)') : ''}`);
  if (fromCfg.length) say(c.dim(`  settings from showtime.json "render": ${fromCfg.join(', ')}`));
  if (renamedFrom) say(c.dim(`  ${path.basename(renamedFrom)} exists: writing ${path.basename(outFile)} (renders never overwrite)`));

  // ---- server + first browser: learn the real config from the page
  let t = Date.now();
  const server = await startServer({ root: proj.dir, port: 0 });
  const browsers = [];
  const sessions = [];
  let interrupted = false;
  const cleanup = async () => {
    await Promise.all(sessions.map((s) => s && s.close().catch(() => {})));
    await Promise.all(browsers.map((b) => b && b.browser.close().catch(() => {})));
    await server.close().catch(() => {});
  };
  process.once('SIGINT', () => { interrupted = true; info('\ninterrupted; cleaning up (partial work kept in ' + workDir + ')'); cleanup().finally(() => process.exit(130)); });

  try {
    const b0 = await openBrowser({ gpu });
    browsers.push(b0);
    const base = cfg.width ? Number(cfg.width) : 1920;
    const baseH = cfg.height ? Number(cfg.height) : 1080;
    let scale = a.scale !== undefined ? Number(a.scale) : (a.preview ? Math.min(1, 720 / Math.min(base, baseH)) : 1);
    if (!(scale > 0 && scale <= 4)) throw new UserError(`--scale must be between 0 and 4 (got ${a.scale})`);
    // followPageSize off: the size check below does it with the right output scale
    const openOpts = { url: server.url, page: proj.page, config: cfg, override, alpha: !!alpha, settle, followPageSize: false };
    // keep the output width even: adjust the device scale factor slightly if needed
    const outW = even(base * scale);
    scale = outW / base;
    openOpts.scale = scale;
    const s0 = await openStage(b0.browser, openOpts);
    sessions.push(s0);
    const inf = s0.info;
    if (inf.width !== base || inf.height !== baseH) {
      // the page set its own size via ST.config and showtime.json has none: follow the page
      await s0.close();
      sessions.length = 0;
      cfg.width = inf.width; cfg.height = inf.height;
      const outW2 = even(inf.width * (a.scale !== undefined ? Number(a.scale) : (a.preview ? Math.min(1, 720 / Math.min(inf.width, inf.height)) : 1)));
      openOpts.scale = outW2 / inf.width;
      openOpts.config = cfg;
      sessions.push(await openStage(b0.browser, openOpts));
    }
    const info0 = sessions[0].info;
    timings.load = Date.now() - t;
    for (const cf of info0.conflicts || []) addWarn(`showtime.json "${cf.key}"=${JSON.stringify(cf.file)} overrides ST.config(${JSON.stringify(cf.page)}) in the page`);

    const fps = info0.fps;
    const duration = info0.duration;
    const from = a.from !== undefined ? parseTime(a.from) : 0;
    const to = a.to !== undefined ? parseTime(a.to) : duration;
    if (!(from >= 0) || !(to > from)) throw new UserError(`bad range --from ${from} --to ${to}`, 'use 0 <= from < to');
    if (from >= duration - 1e-9) throw new UserError(`--from ${from} is past the end (${duration}s)`);
    const first = Math.round(from * fps);
    const last = Math.min(Math.round(to * fps), Math.round(duration * fps)); // exclusive
    const nFrames = last - first;
    if (nFrames <= 0) throw new UserError('nothing to render: the range is shorter than one frame');
    const partial = first > 0 || last < Math.round(duration * fps);
    const outDur = nFrames / fps;
    const W = even(info0.width * openOpts.scale), H = Math.round(info0.height * openOpts.scale);

    // ---- workers
    const cpus = cpuCount();
    const memCap = Math.max(1, Math.floor((os.totalmem() / 2 ** 30) * 0.5 / 1.5));
    // SHOWTIME_MAX_WORKERS (plugin setting "max_workers") caps the automatic choice; --workers overrides it
    const workerCap = Math.floor(Number(process.env.SHOWTIME_MAX_WORKERS)) > 0 ? Math.floor(Number(process.env.SHOWTIME_MAX_WORKERS)) : 3;
    let workers = a.workers !== undefined ? Math.round(Number(a.workers)) : Math.min(3, workerCap, Math.max(1, cpus - 2), Math.max(1, Math.floor(nFrames / 45)), memCap);
    if (!(workers >= 1)) throw new UserError('--workers must be >= 1');
    if (workers > 3 && a.workers !== undefined) addWarn(`${workers} workers requested; more than 3 rarely helps and can crash Chrome on smaller machines`);
    workers = Math.min(workers, nFrames);

    say(`  ${info0.width}x${info0.height}${openOpts.scale !== 1 ? ` -> ${W}x${H}` : ''} @ ${fps} fps, ${outDur.toFixed(2)}s` +
      `${partial ? ` (${from.toFixed(2)}-${(last / fps).toFixed(2)}s)` : ''}, ${nFrames} frames, ${workers} worker${workers > 1 ? 's' : ''}, ` +
      `${b0.kind} ${b0.version}, ${capFormat}`);

    // ---- audio in parallel with capture
    // the soundtrack is built in parallel; a failure is retried once (a busy machine can close the
    // offline score page), and a project that has audio never ships silent unless --allow-silent
    const expectsAudio = !!(info0.hasScore || (cfg.audio !== undefined && cfg.audio !== null && cfg.audio !== false && cfg.audio !== ''));
    const audioArgs = { proj, cfg, info: info0, browser: b0.browser, openOpts, audioDir, from: first / fps, dur: outDur, noLoudnorm: a['no-loudnorm'], lufsArg: a.lufs, addWarn, say };
    const audioJob = a['no-audio'] ? Promise.resolve(null)
      : buildAudio(audioArgs).catch(async (e) => {
        warn(`audio failed (${String(e.message).split('\n')[0]}); retrying once`);
        logLine(`audio failed: ${e && e.stack ? e.stack : e}`);
        try {
          const b = await openBrowser({ gpu });
          browsers.push(b);
          return await buildAudio({ ...audioArgs, browser: b.browser });
        } catch (e2) {
          if (expectsAudio && !a['allow-silent']) {
            throw new UserError(`the soundtrack failed twice: ${String(e2.message).split('\n')[0]}`,
              'this project has audio (ST.score or an "audio" mix), so no silent video was written; re-run when the machine is less busy (--workers 1 helps), or pass --allow-silent / --no-audio');
          }
          addWarn(`audio failed, rendering without it: ${e2.message}`);
          return null;
        }
      });
    audioJob.catch(() => {});   // awaited after the encode; avoid an unhandled rejection meanwhile

    // ---- capture
    t = Date.now();
    const chunk = Math.ceil(nFrames / workers);
    const ranges = [];
    for (let w = 0; w < workers; w++) {
      const s = first + w * chunk, e = Math.min(last, s + chunk);
      if (e > s) ranges.push([s, e]);
    }
    const prog = new Progress('frames', nFrames, { quiet });
    const frameExt = capFormat === 'png' ? 'png' : 'jpg';
    const framePath = (i) => path.join(framesDir, `f_${String(i - first).padStart(6, '0')}.${frameExt}`);
    const stats = { seekMs: 0, shotMs: 0, frames: 0, retries: 0 };

    const captureRange = async (w, [s, e]) => {
      let attempt = 0;
      for (;;) {
        let sess = w === 0 && attempt === 0 ? sessions[0] : null;
        try {
          if (!sess) {
            if (!browsers[w] || !browsers[w].browser.isConnected()) browsers[w] = await openBrowser({ gpu });
            sess = await openStage(browsers[w].browser, openOpts);
            sessions.push(sess);
          }
          // warm-up: replay (without capturing) the second of frames before this chunk, so the first
          // captured frame has the same recent history as in a single-worker render. Chrome keeps some
          // raster/compositing state from earlier frames (e.g. an element that was blurred), and a
          // cold start could otherwise differ by a few antialiasing levels at the chunk join.
          const warm = Math.min(s, Math.max(2, Math.round(fps * WARMUP_S)));
          for (let k = warm; k >= 1; k--) await sess.seek((s - k) / fps);
          const pending = [];
          for (let i = s; i < e; i++) {
            if (interrupted) return;
            const f = framePath(i);
            if (attempt > 0 && fs.existsSync(f) && fs.statSync(f).size > 8) continue;
            const t1 = performance.now();
            await sess.seek(i / fps);
            const t2 = performance.now();
            const buf = await sess.shot({ format: capFormat, quality });
            stats.seekMs += t2 - t1; stats.shotMs += performance.now() - t2; stats.frames++;
            pending.push(fs.promises.writeFile(f, buf));
            if (pending.length > 16) await pending.shift();
            prog.tick();
          }
          await Promise.all(pending);
          return;
        } catch (err) {
          if (interrupted) return;
          attempt++;
          stats.retries++;
          if (sess) await writeDiagnostics(sess, diagDir, `worker${w}-attempt${attempt}`);
          const msg = String(err.message || err).split('\n')[0];
          const pageErr = sess && sess.log.errors.length ? ` (page error: ${sess.log.errors[sess.log.errors.length - 1].message})` : '';
          if (attempt > 2 || /onSeek|at t=|ST\.waitFor|has no duration/.test(msg)) {
            throw new UserError(`capture failed in worker ${w}: ${msg}${pageErr}`,
              `see ${diagDir} (screenshot, DOM, console) and run \`showtime check ${path.relative(process.cwd(), proj.dir) || '.'}\``);
          }
          prog.clear();
          warn(`worker ${w}: ${msg}; retrying (${attempt}/2)`);
          if (sess) await sess.close();
          if (browsers[w] && !browsers[w].browser.isConnected()) browsers[w] = null;
        }
      }
    };
    // extra browsers start while worker 0 already captures
    const jobs = ranges.map(async (r, w) => {
      if (w > 0 && !browsers[w]) browsers[w] = await openBrowser({ gpu });
      return captureRange(w, r);
    });
    await Promise.all(jobs);
    if (interrupted) return 130;
    prog.end();
    // verify: every frame present and non-empty (ffmpeg stops silently at a gap)
    const missing = [];
    for (let i = first; i < last; i++) { const f = framePath(i); if (!fs.existsSync(f) || fs.statSync(f).size <= 8) missing.push(i); }
    if (missing.length) {
      addWarn(`${missing.length} frame(s) missing after capture; re-capturing`);
      const b = await openBrowser({ gpu });
      browsers.push(b);
      const sess = await openStage(b.browser, openOpts);
      sessions.push(sess);
      for (const i of missing) { await sess.seek(i / fps); fs.writeFileSync(framePath(i), await sess.shot({ format: capFormat, quality })); }
    }
    timings.capture = Date.now() - t;
    const capFps = nFrames / (timings.capture / 1000);
    const pageLog = { errors: [], console: [], blocked: [], http: [] };
    for (const s of sessions) for (const k of Object.keys(pageLog)) for (const x of s.log[k]) pageLog[k].push(x);
    for (const e of pageLog.errors.slice(0, 50)) logLine(`browser page error: ${e.message}`);
    for (const m of pageLog.console.filter((x) => x.type === 'error' || x.type === 'warning').slice(0, 100)) logLine(`browser console ${m.type}: ${m.text}${m.url ? ` (${m.url}:${m.line})` : ''}`);
    for (const u of pageLog.blocked.slice(0, 20)) logLine(`browser blocked request: ${u}`);
    for (const h of pageLog.http.filter((x) => x.status >= 400).slice(0, 50)) logLine(`browser http ${h.status}: ${h.url}`);
    const diag = await sessions[0].diag().catch(() => null);
    for (const s of sessions) await s.close();
    sessions.length = 0;
    // worker browsers can go; the first one may still be rendering ST.score offline for the
    // soundtrack (closing it mid-score used to ship silent finals on a busy machine)
    const scoreBrowser = browsers[0];
    await Promise.all(browsers.filter((b) => b && b !== scoreBrowser).map((b) => b.browser.close().catch(() => {})));
    say(`  captured ${nFrames} frames in ${fmtDuration(timings.capture)} (${capFps.toFixed(1)} fps; seek ${(stats.seekMs / Math.max(1, stats.frames)).toFixed(0)} ms + shot ${(stats.shotMs / Math.max(1, stats.frames)).toFixed(0)} ms per frame per worker)`);
    if (pageLog.errors.length) addWarn(`${pageLog.errors.length} page error(s) during render, first: ${pageLog.errors[0].message}`);
    if (pageLog.blocked.length) addWarn(`blocked ${pageLog.blocked.length} network request(s) outside localhost (renders are offline), e.g. ${pageLog.blocked[0]}`);
    const http404 = pageLog.http.filter((h) => h.status === 404);
    if (http404.length) addWarn(`${http404.length} missing file(s) (404), e.g. ${http404[0].url.replace(server.url, '')}`);
    if (diag && (diag.timers.setTimeout + diag.timers.setInterval) > 0) {
      addWarn(`the page used setTimeout/setInterval ${diag.timers.setTimeout + diag.timers.setInterval} time(s) during playback; timers run in real time, so frames may not match the preview` +
        (diag.timers.where[0] ? ` (e.g. ${diag.timers.where[0].split(server.url + '/').join('')})` : ''));
    }
    if (diag && Object.keys(diag.videos || {}).length) addWarn(`video problems: ${JSON.stringify(diag.videos)}`);

    // ---- poster: the chosen frame becomes poster.jpg and, for full renders, also frame 0 of the video
    //      (feeds and chat apps show frame 0 before playback). Doing it before the single encode means
    //      no second encoding pass: every other frame, the duration and the audio are untouched.
    const posterOff = String(a.poster || '').toLowerCase() === 'none';
    let posterT = null;
    if (a.poster !== undefined && !posterOff) posterT = parseTime(a.poster);
    else if (a.poster === undefined && cfg.poster !== undefined && cfg.poster !== null && cfg.poster !== false) posterT = Number(cfg.poster);
    // poster.jpg beside the job's main video (final.mp4), <stem>.poster.jpg beside any other name
    const posterFile = path.join(outDir, a.output && path.basename(outFile, ext) !== 'final' ? `${path.basename(outFile, ext)}.poster.jpg` : 'poster.jpg');
    let posterInfo = null;
    const writePoster = async (src) => {
      if (frameExt === 'jpg') fs.copyFileSync(src, posterFile);
      else await ffmpeg(['-i', src, '-q:v', '2', posterFile]);
    };
    // Baking a frame that does not look like the opening makes a one-frame flash on autoplay and on
    // every loop (frame 0 = poster, frame 1 = the real opening). --poster-bake auto (default) bakes only
    // when the poster frame is close to frame 1; force always bakes; off never does.
    const bakeMode = String(a['poster-bake'] || 'auto').toLowerCase();
    if (!['auto', 'force', 'off'].includes(bakeMode)) throw new UserError(`--poster-bake must be auto, force or off (got ${a['poster-bake']})`);
    if (!a.preview && !alpha && !posterOff && posterT !== null) {
      const idx = Math.round(posterT * fps);
      if (!isFinite(posterT) || idx < first || idx >= last) {
        addWarn(`poster time ${posterT}s is outside the rendered range; no poster baked`);
      } else {
        await writePoster(framePath(idx));
        let bake = !partial && bakeMode !== 'off';
        let flash = null;
        if (bake && idx !== first && bakeMode === 'auto' && last - first > 1) {
          flash = await meanFrameDiff(framePath(idx), framePath(first + 1)).catch(() => null);
          if (flash !== null && flash > POSTER_FLASH_DIFF) {
            bake = false;
            say(c.dim(`  poster ${(idx / fps).toFixed(2)}s not baked into frame 0: it differs from the opening frame (mean diff ${flash.toFixed(1)}/255), ` +
              'so a baked frame 0 would flash on autoplay and loops. Start the video in the poster\'s state (poster 0), or --poster-bake force'));
          }
        }
        posterInfo = { file: posterFile, time: idx / fps, baked: bake || (!partial && idx === first), ...(flash !== null ? { opening_diff: +flash.toFixed(1) } : {}) };
        if (bake && idx !== first) fs.copyFileSync(framePath(idx), framePath(first));
      }
    }

    // ---- encode
    t = Date.now();
    const videoOnly = path.join(workDir, `video${ext}`);
    const crf = a.crf !== undefined ? Number(a.crf) : (a.preview ? 23 : 16);
    const x264Preset = a['x264-preset'] || (a.preview ? 'veryfast' : 'medium');
    const inArgs = ['-framerate', fpsArg(fps), '-start_number', '0', '-i', path.join(framesDir, `f_%06d.${frameExt}`)];
    const evenCrop = 'crop=trunc(iw/2)*2:trunc(ih/2)*2';
    // every output (H.264, ProRes, VP9) is BT.709 tv-range: converted with that matrix and tagged with it
    const TO_709 = 'scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int';
    const TAG_709 = 'setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709';
    const TAGS_709 = ['-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv'];
    let vArgs;
    if (alpha === 'prores') {
      // the RGB frames are converted with the BT.709 matrix that the tags declare (swscale's default is
      // BT.601: tagged 709, an editor would shift the colours, e.g. brand red #B3121F decoding as #C1221D)
      vArgs = ['-vf', `${evenCrop},${TO_709},format=yuva444p10le,${TAG_709}`, '-c:v', 'prores_ks', '-profile:v', '4444', '-vendor', 'apl0',
        '-pix_fmt', 'yuva444p10le', '-alpha_bits', '16', ...TAGS_709];
    } else if (alpha === 'animation') {
      // QuickTime Animation (run-length RGBA): lossless like PNG, tiny for flat graphics with still runs; RGB, so
      // there is no matrix to tag (editors read it as sRGB/BT.709 RGB)
      vArgs = ['-vf', `${evenCrop},format=argb`, '-c:v', 'qtrle', '-pix_fmt', 'argb'];
    } else if (alpha === 'webm') {
      vArgs = ['-vf', `${evenCrop},${TO_709},format=yuva420p,${TAG_709}`, '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-b:v', '0', '-crf', String(a.crf || 30),
        '-row-mt', '1', '-auto-alt-ref', '0', '-deadline', 'good', '-cpu-used', a.preview ? '5' : '2', '-metadata:s:v:0', 'alpha_mode=1', ...TAGS_709];
    } else {
      vArgs = ['-vf', `${evenCrop},${TO_709},format=yuv420p,${TAG_709}`,
        '-c:v', 'libx264', '-preset', x264Preset, '-crf', String(crf), '-profile:v', 'high', '-bf', '0',
        ...(a.preview ? [] : ['-x264-params', 'aq-mode=3']), '-g', String(Math.max(1, Math.round(fps * 2))),
        '-pix_fmt', 'yuv420p', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
        '-video_track_timescale', '90000', '-movflags', '+faststart'];
    }
    const encProg = new Progress('encode', nFrames, { quiet });
    let lastFrame = 0;
    await ffmpeg([...inArgs, ...vArgs, '-r', fpsArg(fps), '-an', '-progress', 'pipe:2', '-nostats', videoOnly], {
      onStderr: (s) => {
        const m = s.match(/frame=\s*(\d+)/g);
        if (m) { const n = Number(m[m.length - 1].replace(/\D/g, '')); if (n > lastFrame) { encProg.tick(n - lastFrame); lastFrame = n; } }
      },
    });
    encProg.end();
    timings.encode = Date.now() - t;
    say(`  encoded in ${fmtDuration(timings.encode)} (${alpha ? alpha : `x264 ${x264Preset} crf ${crf}`})`);

    // ---- audio + mux
    t = Date.now();
    const audio = await audioJob;   // throws when the soundtrack failed twice (see above)
    await Promise.all(browsers.map((b) => b && b.browser.close().catch(() => {})));
    timings.audio_wait = Date.now() - t;
    t = Date.now();
    const tmpOut = path.join(workDir, `mux${ext}`);
    if (audio && audio.file) {
      const aCodec = alpha === 'webm' ? ['-c:a', 'libopus', '-b:a', '160k'] : (alpha === 'prores' || alpha === 'animation') ? ['-c:a', 'pcm_s16le'] : ['-c:a', 'copy'];
      const aIn = alpha ? audio.wav : audio.file;
      await ffmpeg(['-i', videoOnly, '-i', aIn, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', ...aCodec,
        ...(ext === '.mp4' ? ['-movflags', '+faststart'] : []), tmpOut]);
    } else {
      fs.copyFileSync(videoOnly, tmpOut);
    }
    fs.renameSync(tmpOut, outFile);
    timings.mux = Date.now() - t;

    // ---- poster: frame image from the captured frames; bake into frame 0 when asked
    const report = {
      ok: true, output: outFile, folder: outDir, project: proj.dir, page: proj.page, preview: !!a.preview, log: logFile,
      width: W, height: H, fps, duration: outDur, frames: nFrames, range: [first / fps, last / fps],
      workers, browser: { kind: b0.kind, version: b0.version, gpu }, capture: { format: capFormat, quality, settle },
      encode: alpha ? { codec: alpha } : { codec: 'libx264', preset: x264Preset, crf },
      audio: audio ? audio.report : null, poster: null, warnings, timings, fps_capture: +capFps.toFixed(2),
    };
    report.poster = posterInfo;
    if (!posterInfo && !a.preview && !alpha && !posterOff) {
      // no poster time given: let the deliver module pick a sharp, representative frame
      t = Date.now();
      let picked = null;
      if (hasPyModule('cli_deliver.py')) {
        const r = await runPyCli(['deliver', 'poster', outFile, '--out', posterFile, '--json']);
        if (r.code === 0 && fs.existsSync(posterFile)) {
          try { picked = JSON.parse(r.stdout).time; } catch { picked = null; }
          report.poster = { file: posterFile, time: picked, baked: false, method: 'auto' };
        }
      }
      if (!report.poster) {
        const idx = first + Math.round(nFrames * 0.4);
        await writePoster(framePath(Math.min(last - 1, idx)));
        report.poster = { file: posterFile, time: Math.min(last - 1, idx) / fps, baked: false, method: '40%' };
      }
      timings.poster = Date.now() - t;
    }

    // ---- verify the result
    const pr = await probe(outFile);
    report.probe = pr;
    if (pr.video) {
      if (pr.video.frames && pr.video.frames !== nFrames) addWarn(`output has ${pr.video.frames} frames, expected ${nFrames}`);
      if (Math.abs((pr.duration || 0) - outDur) > 1.5 / fps + 0.03) addWarn(`output duration ${pr.duration}s differs from ${outDur.toFixed(3)}s`);
    }
    if (!a['keep-frames']) fs.rmSync(framesDir, { recursive: true, force: true });
    const creditLines = collectCredits(audio, proj.dir);
    if (creditLines.length) {
      // lowercase credits.txt for the job's main video, <stem>.credits.txt for any other name (final-2.mp4, launch.mp4)
      const stem = path.basename(outFile, ext);
      const credFile = path.join(outDir, !a.output || stem === 'final' ? 'credits.txt' : `${stem}.credits.txt`);
      fs.writeFileSync(credFile, creditLines.join('\n') + '\n');
      report.credits = credFile;
    }
    if (audio && audio.mixReport && audio.creditItems && hasPyModule('cli_audio.py')) {
      // the full credits: exact attributions, courtesy credits, end-card line, the description block in share.txt
      // (finals only) and the Content ID note for music whose owner claims uncredited videos
      const stem = path.basename(outFile, ext);
      const credName = !a.output || stem === 'final' ? 'credits.txt' : `${stem}.credits.txt`;
      const cargs = ['audio', 'credits', '--report', audio.mixReport, '--out-dir', outDir, '--name', credName, '--json'];
      if (report.credits) cargs.push('--merge', report.credits);
      if (a.preview || partial) cargs.push('--no-share');
      const cr = await runPyCli(cargs, { timeout: 120000 });
      if (cr.code === 0) {
        try {
          const cj = JSON.parse(cr.stdout);
          if (cj.credits_file) report.credits = cj.credits_file;
          if (cj.share_file) report.share = cj.share_file;
          report.credit_notes = cj.notes || [];
          if ((cj.end_card || []).length) report.end_card = cj.end_card;
        } catch { /* the credits file from above stays */ }
      } else {
        const why = (cr.stderr || '').trim().split('\n').filter(Boolean).pop() || `exit ${cr.code}`;
        addWarn(`credits: ${why}`);
      }
    }
    timings.total = Date.now() - T0;
    report.fps_overall = +(nFrames / (timings.total / 1000)).toFixed(2);
    const reportFile = a.output ? path.join(workDir, 'render.json') : path.join(outDir, 'render.json');
    fs.writeFileSync(reportFile, JSON.stringify(report, null, 2));
    report.report = reportFile;
    // latest pointers: job.json "outputs" says which file is current (qa/review-pack/deliver read it).
    // Studio media (animatics, look tests under <job>/studio/) are logged but never become the latest.
    const ledgerJob = jobFolder || enclosingJob(outFile);
    const studioMedia = !!ledgerJob && !path.relative(path.join(ledgerJob, 'studio'), outFile).startsWith('..') && !path.isAbsolute(path.relative(path.join(ledgerJob, 'studio'), outFile));
    if (ledgerJob && !partial && studioMedia) {
      const r = await runPyCli(['job', 'note', ledgerJob, '--event', `studio render ${path.relative(ledgerJob, outFile)} (not a latest ${a.preview ? 'preview' : 'final'})`], { timeout: 120000 });
      if (r.code === 0) report.job = ledgerJob;
    } else if (ledgerJob && !partial) {
      const outs = [`${a.preview ? 'preview' : 'final'}=${outFile}`];
      if (report.poster && report.poster.file && fs.existsSync(report.poster.file)) outs.push(`poster=${report.poster.file}`);
      if (report.credits) outs.push(`credits=${report.credits}`);
      // --auto: an alpha overlay (.webm/.mov) or an .mp4 not named final*/preview* (a bumper, a second aspect)
      // is logged as a variant and does not become the job's latest final/preview
      const args = ['job', 'note', ledgerJob, '--stage', a.preview ? 'preview' : 'render', '--seconds', String((timings.total / 1000).toFixed(1)),
        ...outs.flatMap((o) => ['--output', o]), '--auto', '--json',
        '--event', `render ${path.basename(outFile)}${report.poster && report.poster.baked ? ` (poster ${report.poster.time}s baked into frame 0)` : ''}`];
      const r = await runPyCli(args, { timeout: 120000 });
      if (r.code === 0) {
        report.job = ledgerJob;
        try {
          const rec = (JSON.parse(r.stdout)._recorded || []).find((o) => path.basename(String(o.path)) === path.basename(outFile));
          if (rec && rec.variant) report.job_variant = rec.why;
        } catch { /* the pointer note is a convenience */ }
      } else addWarn(`could not record the render in ${path.join(ledgerJob, 'job.json')}: ${(r.stderr || '').trim().split('\n').pop()}`);
    }

    await server.close();
    const size = fs.statSync(outFile).size;
    const mbps = (size * 8) / 1e6 / Math.max(0.001, outDur);
    report.size_bytes = size;
    // a re-render much larger than the one before usually means different encode settings
    const prev = previousFinal(outFile, ext);
    if (prev && !a.preview && size > 2 * prev.size) {
      const ps = prev.settings ? ` (it used ${prev.settings})` : '';
      addWarn(`${path.basename(outFile)} is ${fmtBytes(size)}, ${(size / prev.size).toFixed(1)}x ${path.basename(prev.file)} (${fmtBytes(prev.size)})${ps}; ` +
        'put the settings you ship with in showtime.json "render" so every re-render keeps them');
    }
    progressLog({ ev: 'output', path: outFile, preview: !!a.preview });
    if (a.json) {
      process.stdout.write(JSON.stringify(report, null, 2) + '\n');
    } else {
      const aTxt = audio && audio.report ? `, audio ${audio.report.sources.join(' + ')}${audio.report.lufs !== null && audio.report.lufs !== undefined ? ` at ${audio.report.lufs.toFixed(1)} LUFS` : ''}` : ', no audio';
      console.log(`${c.green('done')} ${path.basename(outFile)}  ${W}x${H} ${fps}fps ${outDur.toFixed(2)}s, ${nFrames} frames${aTxt}`);
      console.log(`  time    capture ${fmtDuration(timings.capture)} (${capFps.toFixed(1)} fps) | encode ${fmtDuration(timings.encode)} | total ${fmtDuration(timings.total)} (${report.fps_overall} fps overall)`);
      console.log(`  output  ${outFile} (${fmtBytes(size)}, ${mbps.toFixed(1)} Mb/s)`);
      if (renamedFrom) console.log(c.dim(`          ${path.basename(renamedFrom)} exists, so this is ${path.basename(outFile)} (renders never overwrite)`));
      if (size > SIZE_HINT_BYTES && !a.preview) console.log(c.dim(`          for a size cap (repos, chat, email): showtime deliver exports ${outFile} --targets original --max-mb 20`));
      if (!alpha && !a.preview && mbps > HIGH_MBPS * Math.max(1, (W * H) / (1920 * 1080))) console.log(c.dim(`          ${mbps.toFixed(0)} Mb/s is very high: animated film grain (a film look with grainFps above 0), dust or noisy textures change every pixel of every frame; grainFps: 0 (static grain) or "render": {"crf": 18} shrinks it`));
      if (alpha === 'prores' && size > SIZE_HINT_BYTES) console.log(c.dim(`          ProRes 4444 is large; for flat graphics --alpha animation (lossless RGBA) is usually a fraction of the size`));
      if (report.poster) console.log(`  poster  ${report.poster.file}${report.poster.baked ? ` (${report.poster.time}s baked into frame 0)` : ''}`);
      if (report.credits) console.log(`  credits ${report.credits}`);
      if (report.share) console.log(`  share   ${report.share} (credits block for the video description)`);
      for (const n of report.credit_notes || []) console.log(c.yellow(`  note    ${n}`));
      console.log(`  report  ${reportFile}`);
      console.log(`  log     ${logFile}`);
      if (report.job) console.log(`  job     ${report.job}${studioMedia ? ' (studio media: the latest final/preview is unchanged)' : report.job_variant ? ` (logged as a variant, ${report.job_variant}: the latest ${a.preview ? 'preview' : 'final'} is unchanged; to make it the latest: showtime job note ${report.job} --output ${a.preview ? 'preview' : 'final'}=${outFile})` : ` (latest ${a.preview ? 'preview' : 'final'} -> ${path.basename(outFile)})`}`);
      if (warnings.length) console.log(`  ${c.yellow(`${warnings.length} warning(s)`)}, see above`);
      // terminals only: what was made and the one next step (a preview: look at it; a final: qa)
      const qaTarget = report.job && !report.job_variant && !studioMedia ? report.job : outFile;
      showCard({
        title: `${path.basename(outFile)} is ready`, file: outFile, facts: [fmtLen(outDur), `${W}x${H}`, fmtBytes(size)],
        next: a.preview ? openHint(outFile) : `showtime qa ${shellPath(qaTarget)}`,
      });
    }
    return 0;
  } catch (e) {
    logLine(`render failed: ${e && e.stack ? e.stack : e}`);
    if (e && e.stderr) logLine(`stderr:\n${String(e.stderr).split('\n').slice(-80).join('\n')}`);
    await cleanup();
    if (e && typeof e === 'object') e.message = `${e.message}\n  log: ${logFile}`;
    throw e;
  } finally {
    setLogFile(null);
  }
}

/** The newest other final*.mp4 beside outFile: {file, size, settings} or null. */
function previousFinal(outFile, ext) {
  const dir = path.dirname(outFile);
  let best = null;
  let names = [];
  try { names = fs.readdirSync(dir); } catch { return null; }
  for (const n of names) {
    const f = path.join(dir, n);
    if (f === outFile || path.extname(n) !== ext || !/^final(-\d+)?$/.test(path.basename(n, ext))) continue;
    const st = fs.statSync(f);
    if (!best || st.mtimeMs > best.mtime) best = { file: f, size: st.size, mtime: st.mtimeMs };
  }
  if (!best) return null;
  for (const rj of [path.join(dir, `${path.basename(best.file, ext)}.work`, 'render.json'), path.join(dir, 'render.json')]) {
    try {
      const r = JSON.parse(fs.readFileSync(rj, 'utf8'));
      if (r.output && path.basename(r.output) !== path.basename(best.file)) continue;
      const e = r.encode || {}, cap = r.capture || {};
      best.settings = [e.crf !== undefined ? `crf ${e.crf}` : null, e.preset ? `preset ${e.preset}` : null, cap.format ? `${cap.format} capture` : null].filter(Boolean).join(', ');
      break;
    } catch { /* no report */ }
  }
  return best;
}

/** Credit lines for the video: the mix's CC-BY items plus the project's credits file (asset sidecars). */
function collectCredits(audio, projDir) {
  const lines = [];
  const add = (l) => { const t = String(l || '').trim(); if (t && !lines.some((x) => x.toLowerCase() === t.toLowerCase())) lines.push(t); };
  for (const l of (audio && audio.credits) || []) add(l);
  let names = [];
  try { names = fs.readdirSync(projDir); } catch { /* none */ }
  const f = names.find((n) => n.toLowerCase() === 'credits.txt');
  if (f) {
    // `showtime assets credits` format: a header, then one "- <credit>" line per item
    for (const l of fs.readFileSync(path.join(projDir, f), 'utf8').split(/\r?\n/)) if (/^\s*[-*] /.test(l)) add(l.replace(/^\s*[-*] /, ''));
  }
  return lines;
}

// --------------------------------------------------------------------- audio

/**
 * Build the soundtrack for [from, from+dur): ST.score (offline) + the showtime.json "audio" mix,
 * padded/trimmed to the exact length, loudness-normalised (two-pass), AAC in .m4a.
 * -> { file (m4a), wav (pre-AAC master), report: {sources, lufs, tp}, credits } | null when silent
 */
async function buildAudio({ proj, cfg, info, browser, openOpts, audioDir, from, dur, noLoudnorm, lufsArg, addWarn, say }) {
  const inputs = [];
  const sources = [];
  let credits = [];
  let mixReport = null;
  let creditItems = 0;
  const fullDur = info.duration;
  // 1) ST.score, rendered offline in its own page
  if (info.hasScore) {
    const t = Date.now();
    const sess = await openStage(browser, { ...openOpts, scale: 1 });
    try {
      const sc = await pullScore(sess.page, { duration: fullDur, sampleRate: 48000 });
      if (sc) {
        const f = path.join(audioDir, 'score.wav');
        writeWavFloat(f, sc.channels, sc.sampleRate);
        inputs.push({ file: f, channels: 2 });
        sources.push('score');
        if (sc.peak > 1.0) addWarn(`ST.score peaks at ${(20 * Math.log10(sc.peak)).toFixed(1)} dBFS (clips before mastering); lower the score's gain`);
        say(c.dim(`  score audio rendered offline in ${fmtDuration(Date.now() - t)}`));
      }
    } finally { await sess.close(); }
  }
  // 2) the showtime.json "audio" entry
  const aud = cfg.audio;
  if (aud !== undefined && aud !== null && aud !== false && aud !== '') {
    const mixOut = path.join(audioDir, 'mix.wav');
    const r = await mixFromConfig(aud, proj.dir, fullDur, mixOut, audioDir, addWarn);
    if (r) { inputs.push({ file: mixOut, channels: 2 }); sources.push(r.kind); credits = r.credits || []; mixReport = r.reportFile || null; creditItems = r.creditItems || 0; }
  }
  if (!inputs.length) return null;

  // voice over an ST.score bed: the mix report cannot see the score, so measure the gap here
  // (the mix is mastered on its own, the score is raw; render sums them and masters the total)
  let voiceOverScore = null;
  if (sources.includes('score') && inputs.length > 1) {
    let rep = null;
    for (const f of [path.join(audioDir, 'mix.report.json'), path.join(audioDir, 'mix.wav').replace(/\.wav$/, '.report.json')]) {
      try { rep = JSON.parse(fs.readFileSync(f, 'utf8')); break; } catch { /* next */ }
    }
    const kinds = new Set(((rep && rep.tracks) || []).map((t) => t.kind));
    if (kinds.has('voice') && !kinds.has('music')) {
      try {
        const [mv, ms] = await Promise.all([ebur128(inputs[1].file), ebur128(inputs[0].file)]);
        if (mv.I !== null && ms.I !== null && isFinite(mv.I) && isFinite(ms.I)) {
          voiceOverScore = +(mv.I - ms.I).toFixed(1);
          if (voiceOverScore > 22) addWarn(`the ST.score bed sits ${voiceOverScore} dB under the voice (score ${ms.I.toFixed(1)} LUFS raw): it will be barely audible; aim for 12-18 dB (raise the score's master gain)`);
          else if (voiceOverScore < 8) addWarn(`the ST.score bed is only ${voiceOverScore} dB under the voice: it will compete with the words; aim for 12-18 dB (lower the music bus or m.duckUnder the voice lines)`);
          else say(c.dim(`  voice over score: ${voiceOverScore} dB (score ${ms.I.toFixed(1)} LUFS raw)`));
        }
      } catch { /* measuring is a convenience */ }
    }
  }

  // 3) combine, cut to the rendered range, exact length
  const combined = path.join(audioDir, 'combined.wav');
  const args = [];
  inputs.forEach((i) => args.push('-i', i.file));
  const chains = inputs.map((_, k) => `[${k}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,atrim=start=${from.toFixed(6)},asetpts=PTS-STARTPTS[a${k}]`);
  let graph = chains.join(';');
  const last = inputs.length > 1
    ? `;${inputs.map((_, k) => `[a${k}]`).join('')}amix=inputs=${inputs.length}:duration=longest:dropout_transition=0:normalize=0[m];[m]`
    : ';[a0]';
  graph += `${last}apad,atrim=0:${dur.toFixed(6)}[out]`;
  await ffmpeg([...args, '-filter_complex', graph, '-map', '[out]', '-c:a', 'pcm_f32le', '-ar', '48000', '-ac', '2', combined]);

  // 4) loudness: exact gain, or gain into a limiter when peaks are in the way; then AAC in .m4a
  //    (.m4a keeps the AAC encoder delay in an edit list, so audio stays in sync)
  const target = lufsArg !== undefined ? Number(lufsArg)
    : (cfg.loudness !== undefined ? Number(cfg.loudness) : (cfg.master && cfg.master.lufs !== undefined ? Number(cfg.master.lufs) : -14));
  const tp = cfg.master && cfg.master.true_peak !== undefined ? Number(cfg.master.true_peak) : -1;
  if (!(target < 0 && target > -40)) throw new UserError(`loudness target must be between -40 and 0 LUFS (got ${target})`);
  const masterWav = path.join(audioDir, 'master.wav');
  let mres;
  if (noLoudnorm) {
    fs.copyFileSync(combined, masterWav);
    const m = await ebur128(masterWav);
    mres = { mode: 'as mixed', lufs: m.I, true_peak: m.TP, reached: null };
  } else {
    // master 0.5 dB under the ceiling: AAC adds 0.2-0.4 dB of true-peak overshoot
    mres = await master(combined, masterWav, { target, tp: tp - AAC_HEADROOM_DB });
    if (mres.mode === 'silent') addWarn('the soundtrack is silent');
    else if (!mres.reached) {
      addWarn(`the soundtrack reached ${mres.lufs === null ? '?' : mres.lufs.toFixed(1)} LUFS instead of ${target}: its peaks are very sharp, and more loudness would need heavy limiting`);
    }
  }
  const m4a = path.join(audioDir, 'master.m4a');
  // AAC changes the master: its low-pass costs bright mixes 0.2-0.4 LU and its true-peak overshoot
  // is content dependent and not monotonic in gain (ffmpeg's coders have burst up to +3.9 dBTP on
  // dense, limited material at 192k, and 1 dB on some material at 256k). So: encode a few
  // candidates (coder x gain, and one louder master), measure each, keep the one closest to the
  // target that stays under the ceiling.
  const CODERS = [['-aac_coder', 'fast'], ['-aac_coder', 'twoloop']];
  let seq = 0;
  const cands = [];
  const tryEncode = async (wavIn, gainDb, coder) => {
    const f = path.join(audioDir, `aac-try${seq++}.m4a`);
    await ffmpeg(['-i', wavIn, ...(gainDb ? ['-af', `volume=${gainDb.toFixed(2)}dB`] : []),
      '-c:a', 'aac', ...coder, '-b:a', '256k', '-ar', '48000', '-ac', '2', '-t', dur.toFixed(6), f]);
    const m = await ebur128(f);
    const c = { f, wav: wavIn, gainDb, coder, m };
    cands.push(c);
    return c;
  };
  const leveled = !noLoudnorm && mres.lufs !== null;
  const ok = (c) => !leveled || c.m.TP <= tp + 0.05;
  const err = (c) => (c.m.I === null ? 99 : Math.abs(c.m.I - target));
  const best = () => {
    const valid = cands.filter(ok);
    if (valid.length) return valid.sort((a, b) => err(a) - err(b))[0];
    return cands.slice().sort((a, b) => a.m.TP - b.m.TP)[0];
  };
  for (const coder of CODERS) {
    const c = await tryEncode(masterWav, 0, coder);
    if (!leveled || (ok(c) && err(c) <= 0.15)) break;
  }
  if (leveled) {
    // over the ceiling everywhere: step the gain down on the cleaner coder
    for (let k = 0; k < 3 && !cands.some(ok); k++) {
      const c = cands.slice().sort((a, b) => a.m.TP - b.m.TP)[0];
      await tryEncode(c.wav, c.gainDb - (c.m.TP - tp + 0.15 + 0.3 * k), c.coder);
    }
    // valid but short: use the headroom that is left
    let b = best();
    if (ok(b) && b.m.I !== null && b.m.I < target - 0.15 && tp - b.m.TP > 0.15) {
      await tryEncode(b.wav, b.gainDb + Math.min(target - b.m.I, tp - b.m.TP - 0.1), b.coder);
      b = best();
    }
    // still short with no headroom (the encoder ate loudness at the peaks): master once more,
    // aiming higher by the shortfall with the same ceiling
    if (b.m.I !== null && b.m.I < target - 0.2) {
      const alt = path.join(audioDir, 'master2.wav');
      try {
        await master(combined, alt, { target: target + (target - b.m.I), tp: tp - AAC_HEADROOM_DB });
        for (const coder of CODERS) await tryEncode(alt, 0, coder);
      } catch (e) { addWarn(`second mastering pass failed: ${e.message}`); }
    }
  }
  const pick = best();
  fs.copyFileSync(pick.f, m4a);
  if (pick.wav !== masterWav) fs.copyFileSync(pick.wav, masterWav);
  for (const c of cands) fs.rmSync(c.f, { force: true });
  fs.rmSync(path.join(audioDir, 'master2.wav'), { force: true });
  const mOut = pick.m;
  if (leveled && !ok(pick)) addWarn(`the AAC audio peaks at ${mOut.TP} dBTP, above the ${tp} dBTP ceiling`);
  return {
    file: m4a, wav: masterWav, credits, mixReport, creditItems,
    report: { sources, lufs: mOut.I, true_peak: mOut.TP, target: noLoudnorm ? null : target, ceiling: tp, mode: mres.mode, gain_db: mres.gain_db ?? null, voice_over_score_db: voiceOverScore },
  };
}

runMain(main);

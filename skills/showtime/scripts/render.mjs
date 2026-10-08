// Render a project to MP4: frames from headless Chrome, H.264 BT.709 encode, offline audio, loudness, poster
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { startServer } from './server.mjs';
import {
  parseCli, runMain, resolveProject, jobDir, freshPath, Progress, info, warn, c, cpuCount, fmtDuration, fmtBytes,
  parseTime, runPyCli, hasPyModule, UserError, progressLog, briefOutput, sinceLastLooked, printSince,
} from './lib/cli.mjs';
import { checkFreshness } from './lib/lean.mjs';
import { openBrowser, openStage, writeDiagnostics, pullScore, parseSize, glRenderer, withTimeout, withPacedTimeout, newPace, paceSummary } from './lib/stagehost.mjs';
import { resolveFF, ffmpeg, probe, ebur128, writeWavFloat, fpsArg, hasEncoder, setLogFile, logLine, meanFrameDiff, JPEG_VF } from './lib/ff.mjs';
import { CaptureQueue, OrderedFeed, autoWorkers, machineLimits } from './lib/pipeline.mjs';
import { renderFlags } from './lib/chrome.mjs';
import { audioCacheOn, audioKey, restoreAudio, saveAudio } from './lib/audiocache.mjs';
import { mixFromConfig, master } from './lib/audio.mjs';
import { resolveJobDir, enclosingJob, readJSON } from './lib/studio/paths.mjs';
import { toAnnexB, readStream, idrFrames, gopRange, mergeRanges, splitPlan, sameParamSets, joinStreams, muxAnnexB, reencodeJoin } from './lib/splice.mjs';
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
    '--from/--to with --job, when the job has a full render of this project at the same size, fps and length:',
    'only those seconds (widened to the keyframes around them) are rendered and spliced into a copy of that',
    'render, giving the next full final-N.mp4 (audio mixed again for the whole video). Otherwise the result is',
    'a span clip, <job>/work/span-A-B.mp4 (without a job: span-A-B.mp4 in a new folder; -o clip.mp4: that file),',
    'never a final.',
    'Encode defaults can live in showtime.json "render": {"crf": 22, "x264_preset": "slow", "format": "png",',
    '"quality": 92, "poster": "none"}; flags override them, so every re-render keeps the same settings.',
  ].join('\n'),
  options: {
    output: { short: 'o', help: 'output file (default: a new folder under ./showtime-out/)', metavar: 'FILE' },
    'out-dir': { help: 'base folder for the showtime-out/ job folder (default: $SHOWTIME_OUT or cwd)', metavar: 'DIR' },
    job: { short: 'j', help: 'render into this job (folder, or name -> newest showtime-out/<name>-<ts>/)', metavar: 'JOB' },
    preview: { type: 'boolean', short: 'p', help: 'fast draft: <=720p, veryfast encode, no poster bake' },
    fps: { help: 'frames per second (default: showtime.json fps, else 30)' },
    from: { help: 'start time in seconds (default 0); with --job: spliced into the job\'s full render, else a span clip', metavar: 'S' },
    to: { help: 'end time in seconds (default: the full duration)', metavar: 'S' },
    workers: { short: 'w', help: 'parallel browsers (default: auto: 3 with a GPU; without one, 1 per 8 CPU threads, 3-8; at most $SHOWTIME_MAX_WORKERS when set)' },
    scale: { help: 'output scale, e.g. 0.5 for half size or 2 for supersampled 4K (default 1; --preview: fit 720p)' },
    alpha: { help: 'transparent output: prores (.mov ProRes 4444, large), animation (.mov QuickTime Animation: lossless RGBA, far smaller for flat graphics such as lower thirds and stingers) or webm (VP9 with alpha, web)', metavar: 'KIND' },
    format: { help: 'frame capture format: jpeg (default, fast) or png (lossless, ~3x slower)' },
    quality: { help: 'jpeg capture quality 1-100 (default 92)' },
    crf: { help: 'x264 CRF (default 16 final, 23 preview; lower = better/larger)' },
    'x264-preset': { help: 'x264 preset (default veryfast: 2-3x faster to encode than medium at the same size and look; medium was the default before 0.4.1)', metavar: 'NAME' },
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
    'keep-frames': { type: 'boolean', help: 'keep the captured frames (work/frames), after a finished, failed or interrupted render' },
    'keep-work': { type: 'boolean', help: 'keep the whole work folder after the render: the silent video copy and the WAV stems too (default: render.json, logs/, diagnostics/ and the small audio files stay)' },
    'no-check': { type: 'boolean', help: 'with --size: skip the layout check at that size (it stops the render when text is cut off or off frame there)' },
    json: { type: 'boolean', help: 'print a JSON report on stdout' },
    quiet: { type: 'boolean', short: 'q', help: 'no progress output' },
  },
  examples: [
    'showtime render my-video                      # final render -> showtime-out/my-video-<ts>/final.mp4',
    'showtime render my-video --preview            # quick 720p draft',
    'showtime render my-video --from 12 --to 18    # just those seconds: a span clip to look at (span-12-18.mp4)',
    'showtime render my-video --from 12 --to 18 --job launch-teaser   # fix 12-18 s in the job\'s video -> final-2.mp4 (full length)',
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
  const sizeFlag = !!size;   // (a later block-scoped `size` holds the file size)
  if (size) { cfg.width = size.width; cfg.height = size.height; override.width = size.width; override.height = size.height; }
  // Lean mode: a full render is the expensive step. When the project changed after the last `showtime check`
  // (or was never checked), say so before spending minutes on it; --preview, --from/--to and --size (which
  // checks the layout itself) are cheap or already checked. A nudge, never a stop.
  const nudges = [];
  const partialRange = a.from !== undefined || a.to !== undefined;
  if (!a.preview && !partialRange && !size && !a['no-check']) {
    const fr = checkFreshness(proj.dir, proj.page, null);
    const rel = path.relative(process.cwd(), proj.dir) || '.';
    if (fr.state === 'none') nudges.push(`no \`showtime check\` has run on this project: run \`showtime check ${rel}\` and \`showtime look ${rel}\` first (a full render that needs a fix costs another one)`);
    else if (fr.state === 'stale') nudges.push(`${path.relative(proj.dir, fr.changed)} changed ${fr.minutes ? `${fr.minutes} min ` : ''}after the last \`showtime check\`: check again before a full render (\`showtime check ${rel}\`)`);
    // a note, not a warning: the render is fine to run, it is only the costly way to find a problem
    for (const m of nudges) { info(c.yellow(`showtime render: note: ${m}`)); logLine(`nudge: ${m}`); }
  }
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
  const ext = alpha === 'prores' || alpha === 'animation' ? '.mov' : alpha === 'webm' ? '.webm' : '.mp4';
  if (a.output && a.job) throw new UserError('pass either -o or --job, not both', 'use --job <job> to render into the job folder');
  let jobFolder = null;
  let renamedFrom = null;
  if (a.job) {
    jobFolder = resolveJobDir(a.job);
    if (!jobFolder || !fs.existsSync(jobFolder)) throw new UserError(`no job named "${a.job}"`, 'list jobs with `showtime job list`, or create one: showtime job init <slug>');
    a.output = path.join(jobFolder, (size && !a.preview ? `${size.width}x${size.height}` : stemName) + ext);
  }
  // the file a whole-video render writes (null: a new job folder), and where a span render (--from/--to)
  // goes instead: a span is never named final*/preview* and never lands where `showtime qa <job>` looks.
  // A span that can be spliced into the job's last full render becomes the next final after the page
  // loaded (see "span or splice" below); until then the render is laid out as a span.
  const wholeTarget = a.output ? (path.extname(a.output) ? path.resolve(a.output) : path.resolve(a.output) + ext) : null;
  const spanName = partialRange ? `span-${spanNum(a.from !== undefined ? parseTime(a.from) : 0)}-${a.to !== undefined ? spanNum(parseTime(a.to)) : 'end'}` : null;
  const spanJob = partialRange && wholeTarget ? (jobFolder || enclosingJob(wholeTarget)) : null;
  // -o with a name of its own (not final*/preview*/draft*): the span clip goes exactly there, inside a job too
  // (it used to become <job>/work/span-A-B.mp4), and it is never spliced into the job's final
  const ownName = !!(partialRange && wholeTarget && !jobFolder && !/^(final|preview|draft)/i.test(path.basename(wholeTarget)));
  let target = wholeTarget;
  if (partialRange && wholeTarget && !ownName) {
    if (spanJob) target = path.join(spanJob, 'work', spanName + ext);
    else if (/^(final|preview|draft)/i.test(path.basename(wholeTarget))) target = path.join(path.dirname(wholeTarget), spanName + ext);
  }
  let outFile, outDir, workDir, framesDir, audioDir, diagDir, logFile;
  // where: 'file' (want is a path), 'newjob' (want is a name in a new showtime-out/<title>-<time>/ folder),
  // 'samejob' (a name in that folder)
  const place = (want, where = 'file') => {
    renamedFrom = null;
    if (where === 'file') {
      outFile = freshPath(want);
      // an intended re-render: an info line, not a warning (renders never overwrite)
      if (outFile !== want) { renamedFrom = want; logLine(`${want} exists; writing ${path.basename(outFile)} instead`); }
      outDir = path.dirname(outFile);
      fs.mkdirSync(outDir, { recursive: true });
      workDir = path.join(outDir, `${path.basename(outFile, path.extname(outFile))}.work`);
      // studio media (animatics, look tests) keep studio/ small: their scratch goes to <job>/work/renders/
      const sj = enclosingJob(outFile);
      if (sj && !path.relative(path.join(sj, 'studio'), outFile).startsWith('..')) {
        workDir = path.join(sj, 'work', 'renders', `${path.basename(outFile, path.extname(outFile))}.work`);
      }
    } else {
      if (where === 'newjob') outDir = jobDir(proj.slug, a['out-dir']);
      outFile = path.join(outDir, want);
      workDir = path.join(outDir, 'work');
    }
    framesDir = path.join(workDir, 'frames');
    audioDir = path.join(workDir, 'audio');
    diagDir = path.join(workDir, 'diagnostics');
    fs.rmSync(framesDir, { recursive: true, force: true });
    fs.mkdirSync(framesDir, { recursive: true });
    fs.mkdirSync(audioDir, { recursive: true });
    // the full ffmpeg / browser story of this render (read by `showtime report` and when a render fails)
    logFile = path.join(workDir, 'logs', 'render.log');
    setLogFile(logFile);
  };
  if (target) place(target);
  else place(partialRange ? spanName + ext : stemName + ext, 'newjob');
  // after the page loaded: move to the final name (a splice, or a "span" that covers the whole video)
  const replace = (want) => {
    const oldWork = workDir, oldLog = logFile;
    setLogFile(null);
    if (want) place(want);
    else place(stemName + ext, 'samejob');
    if (workDir !== oldWork) {
      try { fs.appendFileSync(logFile, fs.readFileSync(oldLog)); } catch { /* nothing logged yet */ }
      fs.rmSync(oldWork, { recursive: true, force: true });
      if (path.basename(path.dirname(oldWork)) === 'work') { try { fs.rmdirSync(path.dirname(oldWork)); } catch { /* not empty */ } }
    }
    logLine(`output is now ${outFile}`);
  };
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
  let feed = null;           // the encoder fed while the capture runs (a full render)
  const early = [];          // browsers launched while the first one loads the page
  let audioBrowser = null;   // the soundtrack's retry browser (never one of the workers' browsers[w])
  // a page or browser that stopped answering must not hold the render up while it closes
  const closeSoon = (p, ms = 20000) => withTimeout(Promise.resolve(p), ms, 'closing a browser').catch(() => {});
  const cleanup = async () => {
    if (feed) feed.fail(new Error('the render stopped'));
    await Promise.all(sessions.map((s) => s && closeSoon(s.close())));
    await Promise.all([...browsers, audioBrowser].map((b) => b && closeSoon(b.browser.close())));
    await Promise.all(early.map((p) => p.then((b) => closeSoon(b.browser.close()), () => {})));
    await server.close().catch(() => {});
  };
  // an interrupted or failed render leaves its log and diagnostics, not its frames (a long one is gigabytes)
  const dropFrames = () => {
    if (a['keep-frames']) return;
    try { fs.rmSync(framesDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 }); } catch { /* best effort */ }
    try { fs.rmSync(path.join(workDir, 'splice'), { recursive: true, force: true }); } catch { /* best effort */ }
  };
  const onStop = (sig) => {
    interrupted = true;
    info(`\ninterrupted; cleaning up (frames ${a['keep-frames'] ? 'kept: --keep-frames' : 'removed'}; log: ${logFile})`);
    // browsers first (they make the frames), at most 3 s: a host sends SIGKILL a few seconds after SIGTERM;
    // then a moment for frame writes already on their way, which would otherwise land in a removed folder
    const settle = (ms) => new Promise((r) => setTimeout(r, ms));
    Promise.race([cleanup(), settle(3000)]).then(() => settle(300))
      .finally(() => { dropFrames(); process.exit(sig === 'SIGTERM' ? 143 : 130); });
  };
  process.once('SIGINT', () => onStop('SIGINT'));
  process.once('SIGTERM', () => onStop('SIGTERM'));

  try {
    const b0 = await openBrowser({ gpu, ownSignals: true, args: renderFlags() });
    browsers.push(b0);
    // GPU or not decides the automatic worker count: a CPU rasteriser (SwiftShader, llvmpipe, WARP) already
    // spreads one browser over many cores, so fewer browsers per core are faster there
    const gl = await glRenderer(b0.browser);
    const software = gpu === 'off' || gl.software === true || (b0.flags || []).includes('--use-angle=swiftshader');
    const cpus = cpuCount();
    // in a container the cgroup's memory limit, not the host's memory (os.totalmem), caps the workers
    const limits = machineLimits();
    const memGB = limits.memGB;
    // SHOWTIME_MAX_WORKERS (plugin setting "max_workers") caps the automatic choice; --workers overrides it
    const envCap = Math.floor(Number(process.env.SHOWTIME_MAX_WORKERS)) > 0 ? Math.floor(Number(process.env.SHOWTIME_MAX_WORKERS)) : 0;
    const wantW = a.workers !== undefined ? Math.round(Number(a.workers)) : null;
    if (wantW !== null && !(wantW >= 1)) throw new UserError('--workers must be >= 1');
    // a whole video: the other browsers start now, while this one loads the page (a span is usually short
    // enough for one browser: its others start once the page says how many frames there are)
    if (!partialRange) {
      const pre = wantW !== null ? wantW : autoWorkers({ cpus, memGB, software, frames: Infinity, cap: envCap }).workers;
      for (let k = 1; k < pre; k++) { const p = openBrowser({ gpu, ownSignals: true, args: renderFlags() }); p.catch(() => {}); early.push(p); }
    }
    const base = cfg.width ? Number(cfg.width) : 1920;
    const baseH = cfg.height ? Number(cfg.height) : 1080;
    let scale = a.scale !== undefined ? Number(a.scale) : (a.preview ? Math.min(1, 720 / Math.min(base, baseH)) : 1);
    if (!(scale > 0 && scale <= 4)) throw new UserError(`--scale must be between 0 and 4 (got ${a.scale})`);
    // followPageSize off: the size check below does it with the right output scale
    const openOpts = { url: server.url, page: proj.page, config: cfg, override, alpha: !!alpha, settle, followPageSize: false };
    // the looks' no-GPU detail (fluted-glass and liquid-metal draw at 0.75 on a CPU rasteriser) is decided once
    // for the render and passed to every page (__ST_RENDER__.softwareGL), so a worker whose browser fell back to
    // software draws like the others; a span spliced into a job's full render takes that render's decision, so
    // its frames match the video around them
    const baseSoftware = partialRange && !a.preview ? spliceBaseSoftware({ job: spanJob, beside: spanJob ? null : wholeTarget, proj }) : null;
    const pageSoftware = typeof baseSoftware === 'boolean' ? baseSoftware : software;
    if (pageSoftware !== software) logLine(`looks draw as with${pageSoftware ? 'out' : ''} a GPU, as the full render this span goes into did`);
    openOpts.softwareGL = pageSoftware;
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
    const total = Math.round(duration * fps);
    const partial = first > 0 || last < total;
    const W = even(info0.width * openOpts.scale), H = Math.round(info0.height * openOpts.scale);

    // ---- poster settings (the poster frame is captured with the rest; a splice may re-render frame 0 for it)
    const posterOff = String(a.poster || '').toLowerCase() === 'none';
    let posterT = null;
    if (a.poster !== undefined && !posterOff) posterT = parseTime(a.poster);
    else if (a.poster === undefined && cfg.poster !== undefined && cfg.poster !== null && cfg.poster !== false) posterT = Number(cfg.poster);
    // Baking a frame that does not look like the opening makes a one-frame flash on autoplay and on
    // every loop (frame 0 = poster, frame 1 = the real opening). --poster-bake auto (default) bakes only
    // when the poster frame is close to frame 1; force always bakes; off never does.
    const bakeMode = String(a['poster-bake'] || 'auto').toLowerCase();
    if (!['auto', 'force', 'off'].includes(bakeMode)) throw new UserError(`--poster-bake must be auto, force or off (got ${a['poster-bake']})`);

    // ---- span or splice. A span (--from/--to) rendered into a job that already has a full render of this
    //      project at the same size, frame rate and length becomes the job's next final: the span, widened to
    //      the keyframes around it, re-rendered and spliced into a copy of that render (every other frame is
    //      the old render's bytes). Otherwise it is a span clip (<job>/work/span-A-B.mp4), never a final.
    let splice = null;
    let spanWhy = null;
    let needGop0 = false;
    const posterIdx = !a.preview && !alpha && !posterOff && posterT !== null && isFinite(posterT) ? Math.round(posterT * fps) : null;
    if (partialRange && !partial) {
      // the range covers the whole video: an ordinary render
      replace(wholeTarget);
    } else if (partial) {
      const into = ownName ? null : spanJob || (wholeTarget && target !== wholeTarget ? wholeTarget : null);
      if (a.preview) spanWhy = 'a --preview span is a draft of those seconds';
      else if (alpha || sizeFlag) spanWhy = `a span with --${alpha ? 'alpha' : 'size'} is not spliced into the final`;
      else if (ownName && spanJob) spanWhy = `-o names a clip of its own (render with --job ${path.basename(spanJob)} to splice the fix into the job's final)`;
      else if (!into) spanWhy = 'it is not rendered into a job (--job <job>), so there is no full render to splice it into';
      else {
        const found = await findSpliceBase({ job: spanJob, beside: spanJob ? null : wholeTarget, proj, W, H, fps, total });
        if (!found.file) spanWhy = found.reason;
        else {
          replace(wholeTarget);
          const dir = path.join(workDir, 'splice');
          fs.mkdirSync(dir, { recursive: true });
          let stream = null;
          try {
            stream = readStream(await toAnnexB(found.file, path.join(dir, 'base.h264')));
            if (stream.aus.length !== total || !stream.aus[0].idr) {
              logLine(`splice: ${found.file} parsed as ${stream.aus.length} frames (expected ${total}); re-encoding instead of cutting`);
              stream = null;
            }
          } catch (e) { logLine(`splice: could not read ${found.file} as H.264: ${e.message}`); stream = null; }
          // cut points: the IDR frames (with no readable stream, any frame: the whole video is encoded once)
          const cuts = stream ? idrFrames(stream.aus) : Array.from({ length: total }, (_, i) => i);
          const inSpan = (i) => i >= first && i < last;
          // frame 0 carries a baked poster: re-render its GOP too unless the old render's frame 0 is still right
          const bp = found.report.poster && typeof found.report.poster === 'object' ? found.report.poster : null;
          const mayBake = posterIdx !== null && posterIdx >= 0 && posterIdx < total && bakeMode !== 'off';
          const frame0Same = mayBake
            ? !!bp && Math.abs(Number(bp.time) - posterIdx / fps) < 0.5 / fps && (bp.bake_mode || 'auto') === bakeMode && !inSpan(1) && !inSpan(posterIdx)
            : !bp || !bp.baked;
          needGop0 = !inSpan(0) && !frame0Same;
          const segs = [gopRange(cuts, total, first, last)];
          if (needGop0) segs.push(gopRange(cuts, total, 0, 1));
          splice = { base: found.file, baseReport: found.report, stream, dir, total, segments: mergeRanges(segs), frame0Same, basePoster: bp };
        }
      }
    }
    const isSpan = partial && !splice;
    const nOut = splice ? total : nFrames;
    const outDur = nOut / fps;
    // the frames to capture: the span (a splice: its GOP-aligned segments, plus the poster frame and frame 1
    // when the poster bake is decided again)
    let plan = splice ? splice.segments.slice() : [[first, last]];
    if (splice && posterIdx !== null && posterIdx >= 0 && posterIdx < total) plan.push([posterIdx, posterIdx + 1]);
    if (splice && posterIdx !== null && (needGop0 || first === 0) && total > 1) plan.push([1, 2]);
    plan = mergeRanges(plan);
    const capFirst = plan[0][0];
    const nCap = plan.reduce((n, [s, e]) => n + e - s, 0);

    // ---- workers
    const auto = autoWorkers({ cpus, memGB, software, frames: nCap, cap: envCap, renderer: gl.renderer });
    let workers = wantW !== null ? wantW : auto.workers;
    const workersWhy = (wantW !== null ? `--workers ${wantW}` : auto.why) + (limits.note ? `; ${limits.note}` : '');
    if (wantW !== null && wantW > Math.max(3, auto.workers)) {
      addWarn(`${wantW} workers requested; the automatic count on this machine is ${auto.workers} (${auto.why}): more browsers rarely help and can crash Chrome on smaller machines`);
    }
    workers = Math.min(workers, nCap);
    // browsers started early that this render does not need
    for (const p of early.splice(Math.max(0, workers - 1))) p.then((b) => b.browser.close().catch(() => {}), () => {});
    logLine(`workers: ${workers} (${workersWhy}); WebGL renderer: ${gl.renderer}`);

    if (renamedFrom && splice) say(c.dim(`  ${path.basename(renamedFrom)} exists: writing ${path.basename(outFile)} (renders never overwrite)`));
    if (splice) {
      say(`  splice: ${from.toFixed(2)}-${(last / fps).toFixed(2)}s into a copy of ${path.basename(splice.base)} -> ${path.basename(outFile)} (the full ${outDur.toFixed(2)}s video); ` +
        `re-rendering ${splice.segments.map(([s, e]) => `${(s / fps).toFixed(2)}-${(e / fps).toFixed(2)}s`).join(' and ')} (whole GOPs)`);
    } else if (isSpan) {
      say(`  span: only ${from.toFixed(2)}-${(last / fps).toFixed(2)}s -> ${path.basename(outFile)}, not a full video (${spanWhy})`);
    }
    say(`  ${info0.width}x${info0.height}${openOpts.scale !== 1 ? ` -> ${W}x${H}` : ''} @ ${fps} fps, ${outDur.toFixed(2)}s` +
      `${isSpan ? ` (${from.toFixed(2)}-${(last / fps).toFixed(2)}s)` : ''}, ${nCap} frames${splice ? ' to capture' : ''}, ${workers} worker${workers > 1 ? 's' : ''}, ` +
      `${b0.kind} ${b0.version}, ${capFormat}`);
    say(c.dim(`  workers: ${workersWhy}`));

    // ---- audio in parallel with capture
    // the soundtrack is built in parallel; a failure is retried once (a busy machine can close the
    // offline score page), and a project that has audio never ships silent unless --allow-silent
    const expectsAudio = !!(info0.hasScore || (cfg.audio !== undefined && cfg.audio !== null && cfg.audio !== false && cfg.audio !== ''));
    const audioArgs = { proj, cfg, info: info0, browser: b0.browser, openOpts, audioDir, from: splice ? 0 : first / fps, dur: outDur, noLoudnorm: a['no-loudnorm'], lufsArg: a.lufs, addWarn, say };
    const audioJob = a['no-audio'] ? Promise.resolve(null)
      : buildAudio(audioArgs).catch(async (e) => {
        warn(`audio failed (${String(e.message).split('\n')[0]}); retrying once`);
        logLine(`audio failed: ${e && e.stack ? e.stack : e}`);
        try {
          // its own browser, kept apart from the workers' browsers[w] (pushed there, it could become a worker's
          // browser and be closed with them after the capture while it still renders the score)
          audioBrowser = await openBrowser({ gpu, ownSignals: true, args: renderFlags() });
          return await buildAudio({ ...audioArgs, browser: audioBrowser.browser });
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

    // ---- encode settings (a full render's encoder starts with the capture)
    const videoOnly = path.join(workDir, `video${ext}`);
    // a splice joins its new frames to the old render's bytes only when both were encoded alike: unless asked
    // otherwise, it uses the old render's preset and CRF (a render from before 0.4.1 used medium)
    const baseEnc = splice && splice.baseReport && splice.baseReport.encode && splice.baseReport.encode.codec === 'libx264' ? splice.baseReport.encode : null;
    const crf = a.crf !== undefined ? Number(a.crf) : (baseEnc && baseEnc.crf !== undefined ? Number(baseEnc.crf) : (a.preview ? 23 : 16));
    const x264Preset = a['x264-preset'] || (baseEnc && baseEnc.preset ? String(baseEnc.preset) : 'veryfast');
    const frameExt = capFormat === 'png' ? 'png' : 'jpg';
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
    const encFrames = splice ? (splice.stream ? splice.segments.reduce((n, [s0, e0]) => n + e0 - s0, 0) : total) : nFrames;
    let encProg = null;
    let lastFrame = 0;
    const onEncode = (s) => {
      const m = s.match(/frame=\s*(\d+)/g);
      if (m) { const n = Number(m[m.length - 1].replace(/\D/g, '')); if (n > lastFrame) { if (encProg) encProg.tick(n - lastFrame); lastFrame = n; } }
    };
    // a whole render is encoded while it is captured: one encoder reads the frames in order as they land
    // (SHOWTIME_PIPE_ENCODE=0: encode after the capture, as before 0.4.1; the file is the same either way)
    const pipeEnc = !splice && !['0', 'false', 'no', 'off'].includes(String(process.env.SHOWTIME_PIPE_ENCODE || '').toLowerCase());

    // ---- capture
    t = Date.now();
    // each worker starts on a contiguous part of the frames (a span: one run split in parts); one that is done
    // takes the back half of the largest part left, so no worker runs alone at the end.
    // SHOWTIME_RENDER_PARTS=N (an experiment) gives each worker N parts, its second one after all the first
    // ones and so on: the encoder, which reads the frames in order, gets the start of the video earlier, for
    // one more warm-up replay and one more join per worker. Measured on a busy 6-core Mac with a GPU (0.4.1):
    // no clear gain, and more frames at joins that differ by GPU antialiasing noise, so 1 by default.
    const WARM = Math.max(2, Math.round(fps * WARMUP_S));
    const envParts = Math.floor(Number(process.env.SHOWTIME_RENDER_PARTS));
    const perWorker = envParts >= 1 ? envParts : 1;
    const allParts = splitPlan(plan, workers * perWorker);
    const lanes = Array.from({ length: workers }, (_, w) => allParts.filter((_, k) => k % workers === w).flat());
    const queue = new CaptureQueue(lanes, { minSteal: 2 * WARM + 4 });
    const prog = new Progress('frames', nCap, { quiet });
    const framePath = (i) => path.join(framesDir, `f_${String(i - capFirst).padStart(6, '0')}.${frameExt}`);
    const stats = { seekMs: 0, shotMs: 0, frames: 0, retries: 0 };

    // ---- poster: the chosen frame becomes poster.jpg and, for full renders, also frame 0 of the video
    //      (feeds and chat apps show frame 0 before playback). Doing it before the single encode means
    //      no second encoding pass: every other frame, the duration and the audio are untouched.
    //      A span clip gets no poster (it is not a video to publish); a splice is a full video and gets one.
    // poster.jpg beside the job's main video (final.mp4), <stem>.poster.jpg beside any other name
    const posterFile = path.join(outDir, a.output && path.basename(outFile, ext) !== 'final' ? `${path.basename(outFile, ext)}.poster.jpg` : 'poster.jpg');
    let posterInfo = null;
    const posterNotes = [];
    // the poster frame is chosen during the capture, before the video exists: it waits in the work folder
    // and goes beside the video after the mux, so a failed render leaves no poster.jpg without a video
    const posterStage = path.join(workDir, 'poster.staged.jpg');
    let posterStaged = false;
    const writePoster = async (src, dst = posterFile) => {
      if (frameExt === 'jpg') fs.copyFileSync(src, dst);
      else await ffmpeg(['-i', src, '-vf', JPEG_VF, '-q:v', '2', dst], { timeout: 120000 });   // one still: a hung ffmpeg never holds the render
    };
    const wantPoster = !a.preview && !alpha && !posterOff && posterT !== null && !isSpan;
    // a splice is a whole video: its poster can be any frame (the poster frame was captured) and its
    // frame 0 is the video's frame 0
    const pf0 = splice ? 0 : first;
    const pf1 = splice ? total : last;
    const pIdx = wantPoster ? Math.round(posterT * fps) : null;
    const posterInRange = wantPoster && isFinite(posterT) && pIdx >= pf0 && pIdx < pf1;
    if (wantPoster && !posterInRange) addWarn(`poster time ${posterT}s is outside the rendered range; no poster baked`);
    let posterJob = null;
    // needs the poster frame and frame 1 on disk; bakes by copying the poster frame over frame 0
    const decidePoster = () => posterJob || (posterJob = (async () => {
      const idx = pIdx;
      await writePoster(framePath(idx), posterStage);
      posterStaged = true;
      if (splice && splice.frame0Same) {
        // the old render's frame 0 stays: same poster frame, same bake decision, neither frame 0, 1 nor the
        // poster frame re-rendered
        const bp = splice.basePoster || {};
        posterInfo = { file: posterFile, time: idx / fps, baked: !!bp.baked, bake_mode: bakeMode, ...(bp.opening_diff !== undefined ? { opening_diff: bp.opening_diff } : {}) };
        return;
      }
      let bake = bakeMode !== 'off';
      let flash = null;
      if (bake && idx !== pf0 && bakeMode === 'auto' && pf1 - pf0 > 1) {
        flash = await meanFrameDiff(framePath(idx), framePath(pf0 + 1)).catch(() => null);
        if (flash !== null && flash > POSTER_FLASH_DIFF) {
          bake = false;
          posterNotes.push(`  poster ${(idx / fps).toFixed(2)}s not baked into frame 0: it differs from the opening frame (mean diff ${flash.toFixed(1)}/255), ` +
            'so a baked frame 0 would flash on autoplay and loops. Start the video in the poster\'s state (poster 0), or --poster-bake force');
        }
      }
      posterInfo = { file: posterFile, time: idx / fps, baked: bake || idx === pf0, bake_mode: bakeMode, ...(flash !== null ? { opening_diff: +flash.toFixed(1) } : {}) };
      if (bake && idx !== pf0) fs.copyFileSync(framePath(idx), framePath(pf0));
    })());

    if (pipeEnc) {
      const order = [];
      for (const [s, e] of plan) for (let i = s; i < e; i++) order.push(i);
      const pipeIn = ['-f', 'image2pipe', '-framerate', fpsArg(fps), '-c:v', frameExt === 'png' ? 'png' : 'mjpeg', '-i', '-'];
      feed = new OrderedFeed({ order, pathOf: framePath, args: [...pipeIn, ...vArgs, '-r', fpsArg(fps), '-an', '-progress', 'pipe:2', '-nostats', videoOnly], onStderr: onEncode });
      // frame 0 waits for the poster decision (it may become the poster frame)
      if (posterInRange) {
        feed.hold(pf0, async () => {
          await feed.wait(pIdx);
          if (pf1 - pf0 > 1) await feed.wait(pf0 + 1);
          await decidePoster();
          return framePath(pf0);
        });
      }
      feed.start();
    }

    // SHOWTIME_PREWARM=1 (an experiment): each new page draws the first frame of every clip once before it
    // captures, so the shaders of WebGL scenes compile before the clock starts
    const prewarm = workers > 1 && ['1', 'true', 'yes', 'on'].includes(String(process.env.SHOWTIME_PREWARM || '').toLowerCase());
    const prewarmScenes = async (sess) => {
      const starts = await sess.page.evaluate(() => (window.ST && typeof window.ST.clips === 'function' ? window.ST.clips().map((x) => x.start) : [])).catch(() => []);
      const ts = [...new Set(starts.filter((x) => typeof x === 'number' && isFinite(x) && x >= 0 && x < duration))].sort((x, y) => x - y);
      for (const x of ts) await sess.seek(x);
    };

    const wsess = [sessions[0]];   // one page per worker, kept across its runs
    const drawn = [];              // per worker: the frame after the last one its page drew (null: a new page)
    // a worker's page. A browser that never answers while it opens one (seen on a very busy machine: the
    // render waited 14 minutes) is closed after 5 minutes (longer than the page load and ready timeouts
    // inside; times the page's pace factor, which the page reports while it gets ready) and replaced; frames
    // go only to a worker whose page is open, so a stuck one never holds frames
    const OPEN_MS = 300000;
    // (SHOWTIME_SHOT_TIMEOUT=S shortens it: the stuck-browser test)
    const SHOT_MS = Number(process.env.SHOWTIME_SHOT_TIMEOUT) > 0 ? Number(process.env.SHOWTIME_SHOT_TIMEOUT) * 1000 : 600000;
    // a frame whose write failed (disk full, an I/O error) may leave a partial file: it is re-captured after
    // the capture, so the encoder's feed is never left waiting for it (SHOWTIME_TEST_FAIL_WRITE=<frame> makes
    // that frame's first write fail halfway: the test)
    const failedWrites = new Set();
    let failWrite = /^\d+$/.test(process.env.SHOWTIME_TEST_FAIL_WRITE || '') ? Number(process.env.SHOWTIME_TEST_FAIL_WRITE) : null;
    const writeFrame = (i, buf) => {
      if (failWrite === i) {
        failWrite = null;
        return fs.promises.writeFile(framePath(i), buf.subarray(0, Math.min(buf.length, 100))).then(() => { throw new Error('write failed (test)'); });
      }
      return fs.promises.writeFile(framePath(i), buf);
    };
    const openWorkerPage = async (w) => {
      if (!browsers[w] || !browsers[w].browser.isConnected()) browsers[w] = await openBrowser({ gpu, ownSignals: true, args: renderFlags() });
      const pace = newPace();
      const p = openStage(browsers[w].browser, { ...openOpts, pace });
      let sess;
      try {
        sess = await withPacedTimeout(p, OPEN_MS, `opening the page in worker ${w}`, pace);
      } catch (e) {
        p.then((x) => x.close(), () => {});
        const b = browsers[w];
        browsers[w] = null;
        if (b) b.browser.close().catch(() => {});
        throw e;
      }
      sessions.push(sess);
      wsess[w] = sess;
      drawn[w] = null;
      if (prewarm) await prewarmScenes(sess);
      return sess;
    };
    const captureRun = async (w, run) => {
      let attempt = 0;
      for (;;) {
        let sess = wsess[w] || null;
        let drawing = null;        // the frame being drawn: captured again on a retry
        try {
          if (!sess) sess = await openWorkerPage(w);
          // warm-up: replay (without capturing) the second of frames before this run, so the first
          // captured frame has the same recent history as in a single-worker render. Chrome keeps some
          // raster/compositing state from earlier frames (e.g. an element that was blurred), and a
          // cold start could otherwise differ by a few antialiasing levels at the join. A run that
          // continues the frame this page drew last needs none.
          if (drawn[w] !== run.next) {
            const s = run.next;
            for (let k = Math.min(s, WARM); k >= 1; k--) await sess.seek((s - k) / fps);
          }
          const pending = [];
          for (;;) {
            if (interrupted) { await Promise.allSettled(pending); return; }   // no write may outlive the frames folder
            if (feed && feed.dead) break;      // the encoder failed: finish() below says why
            const i = queue.claim(w);
            if (i === null) break;
            drawing = i;
            const t1 = performance.now();
            await sess.seek(i / fps);
            const t2 = performance.now();
            // only a browser that stopped answering hits this: without a GPU the first frame of a WebGL scene
            // (its shaders compile while the screenshot waits) took over a minute on a busy 6-core machine
            const buf = await withTimeout(sess.shot({ format: capFormat, quality }), SHOT_MS, `screenshot at ${(i / fps).toFixed(3)}s`);
            stats.seekMs += t2 - t1; stats.shotMs += performance.now() - t2; stats.frames++;
            drawn[w] = i + 1;
            drawing = null;
            const wr = writeFrame(i, buf).then(() => { if (feed) feed.ready(i); }, (e) => {
              // captured again after the capture (the missing check reads failedWrites; a partial file is removed)
              failedWrites.add(i);
              logLine(`frame ${i}: the write failed (${String(e && e.message || e).split('\n')[0]}); it is captured again`);
              return fs.promises.rm(framePath(i), { force: true }).catch(() => {});
            });
            pending.push(wr);
            if (pending.length > 16) await pending.shift();
            prog.tick();
          }
          await Promise.all(pending);
          return;
        } catch (err) {
          if (interrupted) return;
          if (drawing !== null) queue.unclaim(w, drawing);
          drawn[w] = null;
          attempt++;
          stats.retries++;
          const msg = String(err.message || err).split('\n')[0];
          // a timeout means the browser stopped answering: no diagnostics from it, no waiting for its close,
          // and the retry starts a fresh browser instead of opening a page on the stuck one
          const stuck = /timed out after/.test(msg);
          if (sess && !stuck) await withTimeout(writeDiagnostics(sess, diagDir, `worker${w}-attempt${attempt}`), 30000, 'diagnostics').catch(() => {});
          const pageErr = sess && sess.log.errors.length ? ` (page error: ${sess.log.errors[sess.log.errors.length - 1].message})` : '';
          if (attempt > 2 || /onSeek|at t=|ST\.waitFor|has no duration/.test(msg)) {
            throw new UserError(`capture failed in worker ${w}: ${msg}${pageErr}`,
              `see ${diagDir} (screenshot, DOM, console) and run \`showtime check ${path.relative(process.cwd(), proj.dir) || '.'}\``);
          }
          prog.clear();
          warn(`worker ${w}: ${msg}; retrying (${attempt}/2)`);
          logLine(`worker ${w}: ${msg}${pageErr}; retrying (${attempt}/2)`);
          wsess[w] = null;
          if (stuck) {
            const b = browsers[w];
            browsers[w] = null;
            if (sess) closeSoon(sess.close(), 5000);
            if (b) closeSoon(b.browser.close(), 10000);
          } else {
            if (sess) await closeSoon(sess.close());
            if (browsers[w] && !browsers[w].browser.isConnected()) browsers[w] = null;
          }
        }
      }
    };
    // every browser was started before the capture (whole videos); a worker opens its page, then takes runs
    // until none is left
    const started = new Array(workers).fill(false);
    const jobs = Array.from({ length: workers }, async (_, w) => {
      if (w > 0 && !browsers[w]) {
        const pre = early[w - 1];
        browsers[w] = pre ? await pre.catch(() => openBrowser({ gpu, ownSignals: true, args: renderFlags() })) : await openBrowser({ gpu, ownSignals: true, args: renderFlags() });
      }
      for (let k = 1; !wsess[w]; k++) {
        if (interrupted || queue.left() === 0) return;
        try {
          await openWorkerPage(w);
        } catch (e) {
          if (interrupted) return;
          const msg = String(e.message || e).split('\n')[0];
          logLine(`worker ${w}: ${msg}`);
          if (k >= 3) { prog.clear(); warn(`worker ${w} could not open the page (${msg}); the other workers take its frames`); return; }
        }
      }
      for (;;) {
        if (interrupted || (feed && feed.dead)) return;
        const run = queue.take(w);
        if (!run) return;
        started[w] = true;
        await captureRun(w, run);
      }
    });
    // a worker still opening its page when the others have taken and drawn every frame is not waited for
    await new Promise((resolve, reject) => {
      const done = new Array(workers).fill(false);
      const check = () => { if (done.every((d, w) => d || (!started[w] && queue.left() === 0))) resolve(); };
      jobs.forEach((j, w) => j.then(() => { done[w] = true; check(); }, reject));
    });
    if (interrupted) return 130;
    if (feed && feed.dead) await feed.finish();   // throws the encoder's error
    prog.end();
    // verify: every frame present and non-empty (ffmpeg stops silently at a gap)
    const missing = [];
    for (const [s, e] of plan) for (let i = s; i < e; i++) { const f = framePath(i); if (failedWrites.has(i) || !fs.existsSync(f) || fs.statSync(f).size <= 8) missing.push(i); }
    if (missing.length) {
      addWarn(`${missing.length} frame(s) missing after capture; re-capturing`);
      const b = await openBrowser({ gpu, ownSignals: true, args: renderFlags() });
      browsers.push(b);
      const sess = await openStage(b.browser, openOpts);
      sessions.push(sess);
      for (const i of missing) {
        await sess.seek(i / fps);
        fs.writeFileSync(framePath(i), await sess.shot({ format: capFormat, quality }));
        if (feed) feed.ready(i);
      }
    }
    timings.capture = Date.now() - t;
    const capEnd = Date.now();
    // the waits were scaled by the page's measured cost (stagehost.mjs pace): the slowest page says by how much
    const paceReport = paceSummary(sessions);
    if (paceReport.factor > 1) logLine(`waits x${paceReport.factor} for this page's pace (frames ${paceReport.frame_ms ?? '-'} ms apart while it got ready, seeks ${paceReport.seek_ms ?? '-'} ms)`);
    const capFps = nCap / (timings.capture / 1000);
    const pageLog = { errors: [], console: [], blocked: [], http: [] };
    for (const s of sessions) for (const k of Object.keys(pageLog)) for (const x of s.log[k]) pageLog[k].push(x);
    for (const e of pageLog.errors.slice(0, 50)) logLine(`browser page error: ${e.message}`);
    for (const m of pageLog.console.filter((x) => x.type === 'error' || x.type === 'warning').slice(0, 100)) logLine(`browser console ${m.type}: ${m.text}${m.url ? ` (${m.url}:${m.line})` : ''}`);
    for (const u of pageLog.blocked.slice(0, 20)) logLine(`browser blocked request: ${u}`);
    for (const h of pageLog.http.filter((x) => x.status >= 400).slice(0, 50)) logLine(`browser http ${h.status}: ${h.url}`);
    const diag = await sessions[0].diag().catch(() => null);
    await Promise.all(sessions.map((s) => closeSoon(s.close())));
    sessions.length = 0;
    // worker browsers can go; the first one may still be rendering ST.score offline for the
    // soundtrack (closing it mid-score used to ship silent finals on a busy machine)
    const scoreBrowser = browsers[0];
    await Promise.all(browsers.filter((b) => b && b !== scoreBrowser).map((b) => closeSoon(b.browser.close())));
    say(`  captured ${nCap} frames in ${fmtDuration(timings.capture)} (${capFps.toFixed(1)} fps; seek ${(stats.seekMs / Math.max(1, stats.frames)).toFixed(0)} ms + shot ${(stats.shotMs / Math.max(1, stats.frames)).toFixed(0)} ms per frame per worker)`);
    logLine(`capture: ${workers} worker(s), ${perWorker} part(s) each, ${queue.steals} hand-over(s) at the end${queue.handed.length ? ` (${queue.handed.map(([f, w, s, e]) => `frames ${s}-${e - 1} from worker ${f} to ${w}`).join(', ')})` : ''}, ` +
      `${stats.retries} retr${stats.retries === 1 ? 'y' : 'ies'}`);
    if (pageLog.errors.length) addWarn(`${pageLog.errors.length} page error(s) during render, first: ${pageLog.errors[0].message}`);
    if (pageLog.blocked.length) addWarn(`blocked ${pageLog.blocked.length} network request(s) outside localhost (renders are offline), e.g. ${pageLog.blocked[0]}`);
    const http404 = pageLog.http.filter((h) => h.status === 404);
    if (http404.length) addWarn(`${http404.length} missing file(s) (404), e.g. ${http404[0].url.replace(server.url, '')}`);
    if (diag && (diag.timers.setTimeout + diag.timers.setInterval) > 0) {
      addWarn(`the page used setTimeout/setInterval ${diag.timers.setTimeout + diag.timers.setInterval} time(s) during playback; timers run in real time, so frames may not match the preview` +
        (diag.timers.where[0] ? ` (e.g. ${diag.timers.where[0].split(server.url + '/').join('')})` : ''));
    }
    if (diag && Object.keys(diag.videos || {}).length) addWarn(`video problems: ${JSON.stringify(diag.videos)}`);

    // ---- poster (decided during the capture when the encoder already runs)
    if (posterInRange) await decidePoster();
    for (const n of posterNotes) say(c.dim(n));

    // ---- encode
    // (the encoder that ran during the capture: what is left of it after the capture, counted from its end)
    t = feed ? capEnd : Date.now();
    if (feed) {
      encProg = new Progress('encode', encFrames, { quiet });
      if (lastFrame > 0) encProg.tick(Math.min(lastFrame, encFrames));
      await feed.finish();
    } else if (!splice) {
      encProg = new Progress('encode', encFrames, { quiet });
      await ffmpeg([...inArgs, ...vArgs, '-r', fpsArg(fps), '-an', '-progress', 'pipe:2', '-nostats', videoOnly], { onStderr: onEncode });
    } else {
      encProg = new Progress('encode', encFrames, { quiet });
      // each segment is encoded exactly as a full render encodes (same filter chain and x264 settings), then its
      // frames replace the old ones between the same two keyframes; parameter sets that differ from the old
      // render's (another ffmpeg or other settings) cannot be joined, so the whole video is encoded once instead
      const pattern = path.join(framesDir, `f_%06d.${frameExt}`);
      const joined = [];
      let why = splice.stream ? null : `${path.basename(splice.base)} could not be cut at its keyframes`;
      for (const [k, [s0, e0]] of (splice.stream ? splice.segments : []).entries()) {
        const segMp4 = path.join(splice.dir, `seg-${k}.mp4`);
        lastFrame = 0;
        await ffmpeg(['-framerate', fpsArg(fps), '-start_number', String(s0 - capFirst), '-i', pattern, '-frames:v', String(e0 - s0),
          ...vArgs, '-r', fpsArg(fps), '-an', '-progress', 'pipe:2', '-nostats', segMp4], { onStderr: onEncode });
        const st = readStream(await toAnnexB(segMp4, path.join(splice.dir, `seg-${k}.h264`)));
        if (st.aus.length !== e0 - s0 || !st.aus[0].idr) { why = `the new segment parsed as ${st.aus.length} frames, expected ${e0 - s0}`; break; }
        if (!sameParamSets(splice.stream.params, st.params)) {
          why = `${path.basename(splice.base)} was encoded with other settings or another ffmpeg (${describeEncode(splice.baseReport)}), so the new frames cannot be joined to its bytes`;
          break;
        }
        joined.push({ range: [s0, e0], stream: st });
      }
      if (!why) {
        await muxAnnexB(joinStreams(splice.stream, joined, total, path.join(splice.dir, 'joined.h264')), fps, null, videoOnly);
        splice.mode = 'cut';
      } else {
        encProg.end();
        say(c.dim(`  splice: ${why}; encoding the whole video once (old frames decoded, new frames from this capture)`));
        logLine(`splice: re-encoding: ${why}`);
        encProg = new Progress('encode', total, { quiet });
        lastFrame = 0;
        await reencodeJoin({ baseMp4: splice.base, total, fps, vf: vArgs[1], codecArgs: vArgs.slice(2), out: videoOnly, onStderr: onEncode,
          segments: splice.segments.map(([s0, e0]) => ({ range: [s0, e0], pattern, start: s0 - capFirst })) });
        splice.mode = 'reencode';
        splice.why = why;
      }
    }
    encProg.end();
    timings.encode = Date.now() - t;
    if (feed) timings.encode_with_capture = Date.now() - feed.t0;
    say(`  encoded in ${fmtDuration(timings.encode)}${feed ? ' after the capture (the encoder ran during it)' : ''} (${alpha ? alpha : `x264 ${x264Preset} crf ${crf}`}${splice ? (splice.mode === 'cut' ? `, ${encFrames} new frames spliced into ${path.basename(splice.base)}` : ', the whole video') : ''})`);

    // ---- audio + mux
    t = Date.now();
    const audio = await audioJob;   // throws when the soundtrack failed twice (see above)
    await Promise.all([...browsers, audioBrowser].map((b) => b && closeSoon(b.browser.close())));
    timings.audio_wait = Date.now() - t;
    t = Date.now();
    const tmpOut = path.join(workDir, `mux${ext}`);
    if (audio && audio.file) {
      const aCodec = alpha === 'webm' ? ['-c:a', 'libopus', '-b:a', '160k'] : (alpha === 'prores' || alpha === 'animation') ? ['-c:a', 'pcm_s16le'] : ['-c:a', 'copy'];
      const aIn = alpha ? audio.wav : audio.file;
      // a stream copy (and at most an audio encode): minutes for hours of video; a hung ffmpeg fails the render
      await ffmpeg(['-i', videoOnly, '-i', aIn, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', ...aCodec,
        ...(ext === '.mp4' ? ['-movflags', '+faststart'] : []), tmpOut], { timeout: Math.max(600000, Math.round((total / fps) * 2000)) });
    } else {
      fs.copyFileSync(videoOnly, tmpOut);
    }
    fs.renameSync(tmpOut, outFile);
    if (posterStaged) fs.renameSync(posterStage, posterFile);
    timings.mux = Date.now() - t;

    // ---- poster: frame image from the captured frames; bake into frame 0 when asked
    const report = {
      ok: true, output: outFile, folder: outDir, project: proj.dir, page: proj.page, preview: !!a.preview, log: logFile,
      width: W, height: H, fps, duration: outDur, frames: nOut, range: splice ? [0, total / fps] : [first / fps, last / fps],
      kind: a.preview ? 'preview' : isSpan ? 'span' : splice ? 'spliced' : 'full',
      // a span clip is only those seconds: never the job's final (qa, look and the ledger skip it)
      ...(isSpan ? { span: [+from.toFixed(3), +(last / fps).toFixed(3)], deliverable: false, span_reason: spanWhy } : {}),
      ...(splice ? { splice: {
        base: splice.base, span: [+from.toFixed(3), +(last / fps).toFixed(3)], mode: splice.mode, ...(splice.why ? { why: splice.why } : {}),
        rerendered: splice.segments.map(([s0, e0]) => [+(s0 / fps).toFixed(3), +(e0 / fps).toFixed(3)]), frames_captured: nCap,
      } } : {}),
      workers, workers_why: workersWhy, browser: { kind: b0.kind, version: b0.version, gpu, webgl: gl.renderer, software_gl: software, page_software_gl: pageSoftware },
      pace: paceReport,
      capture: { format: capFormat, quality, settle, handed_over: queue.steals },
      encode: { ...(alpha ? { codec: alpha } : { codec: 'libx264', preset: x264Preset, crf }), ...(feed ? { during_capture: true } : {}) },
      audio: audio ? audio.report : null, poster: null, warnings, timings, fps_capture: +capFps.toFixed(2),
      ...(nudges.length ? { nudges } : {}),
    };
    report.poster = posterInfo;
    if (!posterInfo && !a.preview && !alpha && !posterOff && !isSpan) {
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
      if (!report.poster && splice) {
        // most frames of a splice were not captured: take the frame from the video
        const tt = Math.floor(total * 0.4) / fps;
        await ffmpeg(['-ss', tt.toFixed(6), '-i', outFile, '-frames:v', '1', '-vf', JPEG_VF, '-q:v', '2', posterFile], { timeout: 120000 });
        report.poster = { file: posterFile, time: tt, baked: false, method: '40%' };
      } else if (!report.poster) {
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
      if (pr.video.frames && pr.video.frames !== nOut) addWarn(`output has ${pr.video.frames} frames, expected ${nOut}`);
      if (Math.abs((pr.duration || 0) - outDur) > 1.5 / fps + 0.03) addWarn(`output duration ${pr.duration}s differs from ${outDur.toFixed(3)}s`);
    }
    dropFrames();                                    // the frames, and a splice's copies of the old render's stream
    const freed = a['keep-work'] ? 0 : tidyWork(workDir, audioDir);
    if (freed) logLine(`work folder: removed ${fmtBytes(freed)} of intermediates (silent video, WAV stems); --keep-work keeps them`);
    const creditLines = collectCredits(audio, proj.dir, jobFolder || enclosingJob(outFile));
    if (creditLines.length) {
      // lowercase credits.txt for the job's main video, <stem>.credits.txt for any other name (final-2.mp4, launch.mp4)
      const stem = path.basename(outFile, ext);
      const credFile = path.join(outDir, !isSpan && (!a.output || stem === 'final') ? 'credits.txt' : `${stem}.credits.txt`);
      fs.writeFileSync(credFile, creditLines.join('\n') + '\n');
      report.credits = credFile;
    }
    if (audio && audio.mixReport && audio.creditItems && hasPyModule('cli_audio.py')) {
      // the full credits: exact attributions, courtesy credits, end-card line, the description block in share.txt
      // (finals only) and the Content ID note for music whose owner claims uncredited videos
      const stem = path.basename(outFile, ext);
      const credName = !isSpan && (!a.output || stem === 'final') ? 'credits.txt' : `${stem}.credits.txt`;
      const cargs = ['audio', 'credits', '--report', audio.mixReport, '--out-dir', outDir, '--name', credName, '--json'];
      if (report.credits) cargs.push('--merge', report.credits);
      if (a.preview || isSpan) cargs.push('--no-share');
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
    report.fps_overall = +(nCap / (timings.total / 1000)).toFixed(2);
    const reportFile = a.output ? path.join(workDir, 'render.json') : path.join(outDir, 'render.json');
    fs.writeFileSync(reportFile, JSON.stringify(report, null, 2));
    report.report = reportFile;
    // latest pointers: job.json "outputs" says which file is current (qa/review-pack/deliver read it).
    // Studio media (animatics, look tests under <job>/studio/) are logged but never become the latest.
    const ledgerJob = jobFolder || enclosingJob(outFile);
    const studioMedia = !!ledgerJob && !path.relative(path.join(ledgerJob, 'studio'), outFile).startsWith('..') && !path.isAbsolute(path.relative(path.join(ledgerJob, 'studio'), outFile));
    if (ledgerJob && !partial && studioMedia) {
      const r = await runPyCli(['job', 'note', ledgerJob, '--event', `studio render ${path.relative(ledgerJob, outFile)} (not a latest ${a.preview ? 'preview' : 'final'})`,
        '--render', `preview=${path.basename(outFile)}`, '--seconds', String((timings.total / 1000).toFixed(1))], { timeout: 120000 });
      if (r.code === 0) report.job = ledgerJob;
    } else if (ledgerJob && isSpan) {
      // a span clip: no latest pointer changes, but the receipt counts it as a partial render
      await runPyCli(['job', 'note', ledgerJob, '--render', `partial=${path.basename(outFile)}`, '--render-span', `${from.toFixed(2)}-${(last / fps).toFixed(2)}`,
        '--seconds', String((timings.total / 1000).toFixed(1)),
        '--event', `span render ${path.relative(ledgerJob, outFile)} (${from.toFixed(2)}-${(last / fps).toFixed(2)}s only; the latest final is unchanged)`], { timeout: 120000 });
    } else if (ledgerJob) {
      const outs = [`${a.preview ? 'preview' : 'final'}=${outFile}`];
      if (report.poster && report.poster.file && fs.existsSync(report.poster.file)) outs.push(`poster=${report.poster.file}`);
      if (report.credits) outs.push(`credits=${report.credits}`);
      // --auto: an alpha overlay (.webm/.mov) or an .mp4 not named final*/preview* (a bumper, a second aspect)
      // is logged as a variant and does not become the job's latest final/preview
      const args = ['job', 'note', ledgerJob, '--stage', a.preview ? 'preview' : 'render', '--seconds', String((timings.total / 1000).toFixed(1)),
        ...outs.flatMap((o) => ['--output', o]), '--auto', '--json',
        // a splice is a full final whose frames were rendered for one span: the receipt counts it as a partial render
        ...(splice ? ['--render', `partial=${path.basename(outFile)}`, '--render-span', `${from.toFixed(2)}-${(last / fps).toFixed(2)}`, '--render-base', path.basename(splice.base)]
          : ['--render', `${a.preview ? 'preview' : 'full'}=${path.basename(outFile)}`]),
        '--event', `render ${path.basename(outFile)}${splice ? ` (spliced ${from.toFixed(2)}-${(last / fps).toFixed(2)}s from ${path.basename(splice.base)})` : ''}` +
          `${report.poster && report.poster.baked ? ` (poster ${report.poster.time}s baked into frame 0)` : ''}`];
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
    const since = ledgerJob ? await sinceLastLooked(ledgerJob) : null;   // what the person changed meanwhile
    if (ledgerJob) report.since_last_looked = since;
    if (a.json) {
      process.stdout.write(JSON.stringify(report, null, 2) + '\n');
    } else {
      const aTxt = audio && audio.report ? `, audio ${audio.report.sources.join(' + ')}${audio.report.lufs !== null && audio.report.lufs !== undefined ? ` at ${audio.report.lufs.toFixed(1)} LUFS` : ''}` : ', no audio';
      console.log(`${c.green('done')} ${path.basename(outFile)}  ${W}x${H} ${fps}fps ${outDur.toFixed(2)}s, ${nOut} frames${aTxt}`);
      const projRel = shellPath(path.relative(process.cwd(), proj.dir) || '.');
      const spanTxt = `${from.toFixed(2)}-${(last / fps).toFixed(2)}s`;
      if (isSpan) {
        // a span clip is easy to mistake for the video: say what it is and how to get the full one
        console.log(c.yellow(`  span    only ${spanTxt} of the ${(total / fps).toFixed(2)}s video: a clip to look at, not the video to deliver (${spanWhy})`));
        const jobArg = spanJob ? shellPath(spanJob) : '<job>';
        if (a.preview && spanJob) console.log(`          the fix in the full video: showtime render ${projRel} --from ${a.from ?? 0} --to ${a.to ?? total / fps} --job ${jobArg} (spliced into the job's last full render)`);
        else console.log(`          the full video with this fix: showtime render ${projRel} --job ${jobArg}; once a job has a full render, --from/--to --job splices a fix into it`);
      } else if (splice) {
        console.log(`  splice  ${spanTxt} re-rendered (${splice.segments.map(([s0, e0]) => `${(s0 / fps).toFixed(2)}-${(e0 / fps).toFixed(2)}s`).join(', ')}, whole GOPs) ` +
          `into a copy of ${path.basename(splice.base)}${splice.mode === 'reencode' ? ' (encoded once as a whole)' : ''}: ${path.basename(outFile)} is the full video`);
      }
      const brief = briefOutput();
      if (!brief) console.log(`  time    capture ${fmtDuration(timings.capture)} (${capFps.toFixed(1)} fps) | encode ${fmtDuration(timings.encode)} | total ${fmtDuration(timings.total)} (${report.fps_overall} fps overall)`);
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
      if (!brief) console.log(`  log     ${logFile}`);
      if (report.job) console.log(`  job     ${report.job}${studioMedia ? ' (studio media: the latest final/preview is unchanged)' : report.job_variant ? ` (logged as a variant, ${report.job_variant}: the latest ${a.preview ? 'preview' : 'final'} is unchanged; to make it the latest: showtime job note ${report.job} --output ${a.preview ? 'preview' : 'final'}=${outFile})` : ` (latest ${a.preview ? 'preview' : 'final'} -> ${path.basename(outFile)})`}`);
      if (warnings.length) console.log(`  ${c.yellow(`${warnings.length} warning(s)`)}, see above`);
      // a second full render in the same place: the next fix is cheaper as a section render
      if (prev && !a.preview && !partialRange) console.log(c.dim(`  next fix: prove it on the changed seconds first (showtime render ${path.relative(process.cwd(), proj.dir) || '.'} --from S --to S), then one full render`));
      // terminals only: what was made and the one next step (a preview: look at it; a final: qa)
      const qaTarget = report.job && !report.job_variant && !studioMedia ? report.job : outFile;
      showCard({
        title: `${path.basename(outFile)} is ready${isSpan ? ` (a ${spanTxt} span, not the full video)` : ''}`, file: outFile, facts: [fmtLen(outDur), `${W}x${H}`, fmtBytes(size)],
        next: isSpan ? `showtime look ${shellPath(outFile)}` : a.preview ? openHint(outFile) : `showtime qa ${shellPath(qaTarget)}`,
      });
      printSince(since);
    }
    return 0;
  } catch (e) {
    logLine(`render failed: ${e && e.stack ? e.stack : e}`);
    if (e && e.stderr) logLine(`stderr:\n${String(e.stderr).split('\n').slice(-80).join('\n')}`);
    await cleanup();
    dropFrames();                                    // the log and diagnostics/ say what went wrong
    if (e && typeof e === 'object') e.message = `${e.message}\n  log: ${logFile}`;
    throw e;
  } finally {
    setLogFile(null);
  }
}

/**
 * A finished render's work folder, tidied: the silent video copy (video.<ext>, about the size of the final), a
 * leftover mux file and the WAV stems in audio/ (score, mix, combined, master) go. What later commands read
 * stays: render.json, logs/, diagnostics/, and in audio/ master.m4a, mix.json, mix.report.json (review-pack,
 * qa's credits check) and the 16 kHz narration stem *.voice.wav (`showtime transcribe` prefers it to the
 * final mix). Only these names are touched: in a new job folder the work folder is <job>/work, shared with
 * qa, snap and check. Returns the bytes removed.
 */
function tidyWork(workDir, audioDir) {
  let freed = 0;
  const drop = (f) => {
    try {
      const st = fs.lstatSync(f);
      if (!st.isFile()) return;
      fs.rmSync(f, { force: true });
      freed += st.size;
    } catch { /* gone already */ }
  };
  for (const ext of ['.mp4', '.mov', '.webm']) { drop(path.join(workDir, `video${ext}`)); drop(path.join(workDir, `mux${ext}`)); }
  let names = [];
  try { names = fs.readdirSync(audioDir); } catch { /* no audio */ }
  for (const n of names) {
    if (/\.wav$/i.test(n) && !/\.voice\.wav$/i.test(n)) drop(path.join(audioDir, n));
    else if (/^aac-try\d+\.m4a$/.test(n)) drop(path.join(audioDir, n));
  }
  return freed;
}

/** "12", "2.5": a time in a span file name. */
function spanNum(x) { return String(+Number(x).toFixed(2)); }

/** render.json of a rendered video (<stem>.work/render.json, or render.json beside it), or null. */
function renderReportFor(file) {
  const dir = path.dirname(file), stem = path.basename(file, path.extname(file));
  for (const rj of [path.join(dir, `${stem}.work`, 'render.json'), path.join(dir, 'render.json')]) {
    const r = readJSON(rj, null);
    if (r && r.output && path.basename(String(r.output)) === path.basename(file)) return r;
  }
  return null;
}

function describeEncode(rep) {
  const e = (rep && rep.encode) || {};
  return [e.crf !== undefined ? `crf ${e.crf}` : null, e.preset ? `preset ${e.preset}` : null].filter(Boolean).join(', ') || 'settings unknown';
}

/**
 * The full render a span can be spliced into: the job's latest final (else its newest final*.mp4) or, for -o
 * outside a job, the newest final*.mp4 beside the requested file. It must come from `showtime render` of this
 * project and page (its render.json says so), be a whole video (not a span or preview) and have exactly this
 * render's size, frame rate and frame count. -> {file, report} or {reason}.
 */
/** The full renders a span could be spliced into, newest first (the job's final first). */
function spliceCandidates(job, beside) {
  const dir = job || path.dirname(beside);
  const cands = [];
  if (job) {
    const ptr = ((readJSON(path.join(job, 'job.json'), null) || {}).outputs || {}).final;
    if (ptr) cands.push(path.isAbsolute(ptr) ? ptr : path.join(job, ptr));
  }
  let names = [];
  try { names = fs.readdirSync(dir); } catch { /* none */ }
  cands.push(...names.filter((n) => /^final.*\.mp4$/i.test(n)).map((n) => path.join(dir, n))
    .filter((f) => fs.existsSync(f)).sort((x, y) => fs.statSync(y).mtimeMs - fs.statSync(x).mtimeMs));
  return { dir, cands };
}

/**
 * Before the page opens: the GPU-or-not decision the full render a span goes into drew its looks with
 * (render.json browser.page_software_gl, else its software_gl), or null (no such render, or it does not say).
 * findSpliceBase checks the candidate fully later; this reads only its report.
 */
function spliceBaseSoftware({ job, beside, proj }) {
  if (!job && !beside) return null;
  for (const file of spliceCandidates(job, beside).cands) {
    if (!fs.existsSync(file) || path.extname(file).toLowerCase() !== '.mp4') continue;
    const rep = renderReportFor(file);
    if (!rep || rep.span || rep.preview || rep.kind === 'span' || rep.kind === 'preview') continue;
    if (!rep.project || path.resolve(String(rep.project)) !== path.resolve(proj.dir) || (rep.page && rep.page !== proj.page)) continue;
    const b = rep.browser || {};
    const v = typeof b.page_software_gl === 'boolean' ? b.page_software_gl : b.software_gl;
    return typeof v === 'boolean' ? v : null;
  }
  return null;
}

async function findSpliceBase({ job, beside, proj, W, H, fps, total }) {
  const { dir, cands } = spliceCandidates(job, beside);
  const seen = new Set();
  let reason = `there is no full render of this project in ${path.basename(dir)} to splice it into`;
  for (const file of cands) {
    if (seen.has(file) || !fs.existsSync(file) || path.extname(file).toLowerCase() !== '.mp4') continue;
    seen.add(file);
    const rep = renderReportFor(file);
    const name = path.basename(file);
    if (!rep) { reason = `${name} has no render report (it was not made by showtime render)`; continue; }
    // (a render from before 0.3.0 wrote a span as final-N.mp4: its range starts after 0)
    if (rep.span || rep.preview || rep.kind === 'span' || rep.kind === 'preview' || (Array.isArray(rep.range) && Number(rep.range[0]) > 0)) {
      reason = `${name} is not a full render`;
      continue;
    }
    if (!rep.project || path.resolve(String(rep.project)) !== path.resolve(proj.dir) || (rep.page && rep.page !== proj.page)) {
      reason = `${name} was rendered from another project or page`;
      continue;
    }
    let pr = null;
    try { pr = await probe(file); } catch { pr = null; }
    const v = pr && pr.video;
    if (!v || v.codec !== 'h264' || v.pix_fmt !== 'yuv420p') { reason = `${name} is not an H.264 render`; continue; }
    if (v.width !== W || v.height !== H || Math.abs((v.fps || 0) - fps) > 1e-3 || v.frames !== total) {
      // the newest full render decides: an older one at the old size would splice into a stale video
      return { reason: `${name} is ${v.width}x${v.height} ${+(v.fps || 0).toFixed(3)} fps ${v.frames} frames and this render is ${W}x${H} ${fps} fps ${total} frames ` +
        '(the size, frame rate or length changed), so the span cannot be spliced into it' };
    }
    return { file, report: rep };
  }
  return { reason };
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

/** Credit lines for the video: the mix's CC-BY items, the project's credits file (asset sidecars) and the
 *  job's style references ("Style reference: <title>", written by `showtime reference`). */
function collectCredits(audio, projDir, jobDir) {
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
  if (jobDir) {
    let refs = [];
    try { refs = fs.readdirSync(path.join(jobDir, 'references')); } catch { /* none */ }
    for (const r of refs.sort()) {
      try { const j = JSON.parse(fs.readFileSync(path.join(jobDir, 'references', r, 'reference.json'), 'utf8')); if (j.credit) add(j.credit); } catch { /* not a reference */ }
    }
  }
  return lines;
}

// --------------------------------------------------------------------- audio

/**
 * Build the soundtrack for [from, from+dur): ST.score (offline) + the showtime.json "audio" mix,
 * padded/trimmed to the exact length, loudness-normalised (two-pass), AAC in .m4a.
 * -> { file (m4a), wav (pre-AAC master), report: {sources, lufs, tp}, credits } | null when silent
 */
async function buildAudio({ proj, cfg, info, browser, openOpts, audioDir, from, dur, noLoudnorm, lufsArg, addWarn: warnOut, say: sayOut }) {
  const inputs = [];
  let addWarn = warnOut, say = sayOut;
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
  // the rest depends only on files, the score's samples and the settings: a soundtrack made from the same
  // inputs before is reused (a --from/--to fix of the pictures does not mix and master the audio again)
  const aud = cfg.audio;
  const cacheKey = audioCacheOn() ? await audioKey({
    projDir: proj.dir, aud, scoreFile: sources.includes('score') ? inputs[0].file : null, ffmpeg: resolveFF().ffmpeg,
    settings: { from: +from.toFixed(6), dur: +dur.toFixed(6), fullDur, noLoudnorm: !!noLoudnorm, lufs: lufsArg === undefined ? null : String(lufsArg),
      loudness: cfg.loudness === undefined ? null : cfg.loudness, master: cfg.master === undefined ? null : cfg.master,
      module: hasPyModule('cli_audio.py'), headroom: AAC_HEADROOM_DB },
  }) : null;
  if (cacheKey) {
    const hit = restoreAudio(cacheKey, audioDir);
    if (hit) {
      for (const n of hit.notes) sayOut(n);
      for (const w of hit.warnings) warnOut(w);
      sayOut(c.dim(`  soundtrack reused: its inputs are the same as for a render at ${String(hit.made || '').replace('T', ' ').slice(0, 16)} (SHOWTIME_AUDIO_CACHE=0 mixes it again)`));
      logLine(`audio: reused cache entry ${cacheKey}`);
      return hit.result;
    }
  }
  const recorded = { warnings: [], notes: [] };
  addWarn = (m) => { recorded.warnings.push(m); warnOut(m); };
  say = (m) => { recorded.notes.push(m); sayOut(m); };
  // 2) the showtime.json "audio" entry
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
    mres = { mode: 'as mixed', lufs: m.I, true_peak: m.TP, reached: null, error: m.error };
    if (m.error) addWarn(`loudness not measured (render.json says null): ${m.error}`);
  } else {
    // master 0.5 dB under the ceiling: AAC adds 0.2-0.4 dB of true-peak overshoot
    mres = await master(combined, masterWav, { target, tp: tp - AAC_HEADROOM_DB });
    if (mres.error) addWarn(`loudness not measured, the soundtrack is not leveled to ${target} LUFS: ${mres.error} (an ffmpeg older than 6.0? \`showtime doctor\` checks; \`showtime setup --ffmpeg static\` installs showtime's own)`);
    else if (mres.mode === 'silent') addWarn('the soundtrack is silent');
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
  if (mOut.error && !mres.error) addWarn(`loudness of the encoded soundtrack not measured (render.json says null): ${mOut.error}`);
  if (leveled && !ok(pick)) addWarn(`the AAC audio peaks at ${mOut.TP} dBTP, above the ${tp} dBTP ceiling`);
  const result = {
    file: m4a, wav: masterWav, credits, mixReport, creditItems,
    report: { sources, lufs: mOut.I, true_peak: mOut.TP, target: noLoudnorm ? null : target, ceiling: tp, mode: mres.mode, gain_db: mres.gain_db ?? null, voice_over_score_db: voiceOverScore },
  };
  if (cacheKey && saveAudio(cacheKey, audioDir, result, recorded)) logLine(`audio: kept as cache entry ${cacheKey}`);
  return result;
}

runMain(main);

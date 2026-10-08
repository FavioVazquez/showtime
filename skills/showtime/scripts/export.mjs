// Export a project as a shareable interactive HTML video (one self-contained file, or a folder)
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { startServer } from './server.mjs';
import { parseCli, runMain, resolveProject, jobDir, freshPath, info, warn, c, fmtBytes, fmtDuration, parseTime, UserError } from './lib/cli.mjs';
import { resolveFF } from './lib/ff.mjs';
import { audioInputs } from './lib/audio.mjs';
import { resolveJobDir } from './lib/studio/paths.mjs';
import { probeProject } from './lib/export/probe.mjs';
import { collectFiles, isMedia, isText, isJs, isCss, pruneFontFamilies, preferWoff2 } from './lib/export/collect.mjs';
import { minifyJs, minifyCss, pruneParts } from './lib/export/minify.mjs';
import { staleKitWarning } from './lib/export/series.mjs';
import { resolveAudioMode, buildEmbedAudio, scoreGain, hasMix } from './lib/export/audio.mjs';
import { showCard, fmtLen, openHint } from './lib/delight.mjs';
import { writeExport, estimateSingle, notices, showtimeVersion, category, jsonBytes, playerBytes } from './lib/export/build.mjs';
import { fitFootage } from './lib/export/fit.mjs';
import { timeIssues, socraticDoc } from './lib/questions.mjs';
import { resolveShare, shareMeta, genericTitle, genericChapters } from './lib/export/share.mjs';

const SPEC = {
  name: 'export',
  usage: 'showtime export html <project|job> [-o out.html] [--audio auto|embed|score|none] [--folder] [--controls full|minimal|none] [--target file|artifact] [--lang CODE] [--no-questions] [--auto-continue S]',
  summary: 'Export a project as an interactive HTML video that plays in any browser, offline, from one file.',
  description: [
    'The page is packed with everything it uses (runtime, scripts, styles, fonts, images, emoji, data,',
    'libraries) and plays in a small player: a start screen over the poster frame (title, subtitle and',
    'a Play button with the length, in the film\'s colours and title font, placed where the frame has no',
    'text), play/pause, scrubber with chapter ticks and a chapter menu, volume, loop,',
    'fullscreen, deep links (#t=1:05, #chapter=2, and #t=1:05-1:20: that part on a loop), "copy a link to',
    'this moment" (or to a range picked with shift + drag on the scrubber), and keys: space/k,',
    'arrows -/+1 s (shift: one frame), j/l -/+5 s, 1-9 chapters, [ ] prev/next chapter, r restart,',
    'm mute, f fullscreen, c copy link, ? all keys.',
    'Frames are drawn by the same stage runtime as `showtime render`, so they match the MP4.',
    'On a phone held upright the picture sits full width on the film\'s own ground, with the title, the',
    'chapters and thumb-height controls under it.',
    'Questions (showtime.json "questions"): the video stops at each one and asks it (a card with the',
    'choices, A-C or 1-3, a right/wrong mark and the reply, then Continue); it goes on from the end of the',
    'MP4\'s "pause and think" beat. socratic.json (the same questions, for pages that drive the player from',
    'outside) is written next to the export. --no-questions exports a plain player.',
    'The file makes no network request. Default output: ./showtime-out/<title>-<timestamp>/<title>.html',
    'A job (folder or name, as qa takes it) exports its project/ folder into the job folder;',
    '`<job> --folder out` writes the folder version to ./out/.',
    '',
    'Audio: auto = the procedural score played live (streamed from the first second, tiny file) when',
    'that is all the sound, otherwise',
    'embed = the rendered soundtrack (score + mix, loudness-matched) packed as AAC (or --codec opus).',
    'The whole file must stay under --max-mb (default 16, the artifact limit); --folder writes',
    'index.html + assets/ instead (no size limit, media stays as real files, for hosting), with an empty',
    '.nojekyll so GitHub Pages serves assets/media/_export/ (the mixed audio).',
    '',
    'Link previews: the page carries og:title, og:description, og:url, og:image and twitter:card, from',
    'showtime.json "share": {"url", "image", "description"} or --share-url / --share-image. Without an',
    'image the poster frame is used (--folder: assets/poster.jpg; one file with a share URL:',
    '<name>.share.jpg beside it). Most previews need an absolute image URL: give the share URL.',
    'The export warns when the title is a default ("Project") or the chapters are scene ids ("Shot 1").',
    'A project file the page needs that cannot be read stops the export.',
  ].join('\n'),
  options: {
    output: { short: 'o', help: 'output .html file (with --folder: output folder)', metavar: 'FILE' },
    'out-dir': { help: 'base folder for the showtime-out/ job folder (default: $SHOWTIME_OUT or cwd)', metavar: 'DIR' },
    job: { short: 'j', help: 'write into this job folder (or name); with -o NAME, as that name inside it', metavar: 'JOB' },
    audio: { help: 'auto (default), embed, score or none', metavar: 'MODE' },
    lang: { help: 'language of the page and the player\'s words (en, es, fr, pt, de; others fall back to English); default: showtime.json "lang", the page\'s <html lang>, the narration\'s lang, else en', metavar: 'CODE' },
    'audio-file': { help: 'embed exactly this sound (a WAV, or the rendered MP4 whose soundtrack you ship) instead of the score and the mix; for a project whose voice files are gone', metavar: 'FILE' },
    bitrate: { help: 'embedded audio bitrate (default 96k)', metavar: 'RATE' },
    codec: { help: 'embedded audio codec: aac (default, plays everywhere) or opus (smaller)', metavar: 'NAME' },
    folder: { type: 'boolean', help: 'write a folder (index.html + assets/) instead of one file' },
    controls: { help: 'player chrome: full (default), minimal, or none (for embedding)', metavar: 'KIND' },
    target: { help: 'file (default) or artifact: for a host that shows the page in a sandboxed frame (an HTML artifact): one file under 16 MB, no "copy link" or other file-address features (the player also detects such hosts by itself)', metavar: 'KIND' },
    'autoplay-muted': { type: 'boolean', help: 'start playing muted as soon as it loads (browsers allow that without a click)' },
    loop: { type: 'boolean', help: 'loop by default' },
    'no-questions': { type: 'boolean', help: 'a plain player: do not stop at the showtime.json "questions" (the video still shows its own pause and think beats)' },
    'auto-continue': { help: 'after a question is answered, go on by itself after S seconds (default: wait for Continue)', metavar: 'S' },
    poster: { help: 'time (s) of the frame shown behind the start screen, and packed as an image with --start poster (default: showtime.json "poster"); none for no poster', metavar: 'T' },
    start: { help: 'what shows before playing: card (default: the start screen over the poster frame drawn live) or poster (the same, with the frame also packed as an image shown while the page loads)', metavar: 'KIND' },
    title: { help: 'title of the page and the start screen (default: showtime.json "title")' },
    subtitle: { help: 'start-card subtitle (default: showtime.json "subtitle" or Film.start({subtitle}))' },
    kicker: { help: 'small line above the start-card title, e.g. a series and episode (default: showtime.json "kicker")' },
    'share-url': { help: 'the address the page will have once hosted, for link previews (og:url; makes a relative share image absolute); default: showtime.json "share": {"url"}', metavar: 'URL' },
    'share-image': { help: 'the image of link previews: an https URL, or a file (copied into the folder with --folder); default: showtime.json "share": {"image"}, else the poster frame (--folder, or a single file with a share URL)', metavar: 'URL|FILE' },
    minify: { help: 'shrink the runtime and scripts: auto (default: on), off', metavar: 'MODE' },
    'max-mb': { help: 'size limit of the single file in MB (default 16; 0 = no limit)', metavar: 'MB' },
    fit: { help: 'auto (default): a single file over --max-mb because of embedded video clips gets those clips re-encoded at the bitrate that fits (for this export only; the project is unchanged); off: stop with the size breakdown instead', metavar: 'MODE' },
    lufs: { help: 'loudness target (default: showtime.json "loudness" or -14)' },
    'no-loudnorm': { type: 'boolean', help: 'keep the audio level as mixed' },
    'all-fonts': { type: 'boolean', help: 'keep every font face (default: drop faces for scripts the video never uses)' },
    'no-csp': { type: 'boolean', help: 'leave out the Content-Security-Policy that blocks all network access' },
    page: { help: 'page inside the project (default index.html)' },
    gpu: { help: 'auto (default) or off, for the probe browser' },
    'keep-work': { type: 'boolean', help: 'keep the work folder (audio intermediates)' },
    json: { type: 'boolean', help: 'print a JSON report on stdout' },
    quiet: { type: 'boolean', short: 'q', help: 'no progress output' },
  },
  examples: [
    'showtime export html my-video                         # -> showtime-out/<title>-<ts>/<title>.html',
    'showtime export html my-video -o launch.html          # one file, plays offline in any browser',
    'showtime export html my-video --job launch -o embed.html   # into the job folder, with that name',
    'showtime export html launch                            # a job: its project/, into the job folder',
    'showtime export html launch --folder out               # a job as a folder: ./out/index.html + assets/',
    'showtime export html my-film --audio score            # procedural score rendered live: tiny file',
    'showtime export html my-film --audio-file final.mp4   # the shipped video\'s soundtrack, nothing rebuilt',
    'showtime export html my-video --bitrate 64k --max-mb 8',
    'showtime export html my-video --max-mb 10 --fit off    # fail instead of re-encoding the clips to fit',
    'showtime export html my-video --folder -o site/launch  # index.html + assets/ for hosting',
    'showtime export html my-video --folder --share-url https://me.github.io/launch/   # link previews with the poster',
    'showtime export html my-video --controls none --autoplay-muted --loop   # for embedding in a page',
    'showtime export html my-video --target artifact -o launch.html   # to publish as an HTML artifact',
    'showtime export html my-film --subtitle "Fix the cuts" --kicker "Studio how-to · 01"',
    'showtime export html my-explainer --auto-continue 6    # questions go on 6 s after an answer',
    '# open at a moment: my-film.html#t=1:05  or  my-film.html#chapter=3',
  ],
};

const MB = 1000 * 1000;   // decimal MB, like fmtBytes and platform limits

/**
 * A job argument -> { job, project } (its project/ folder), or null for a project folder or page. A job without
 * a project/ folder is an error that says so (never "start a new project": the job has one somewhere else).
 */
export function jobProject(arg, page) {
  const has = (d) => fs.existsSync(path.join(d, page || 'index.html'));
  const abs = path.resolve(String(arg));
  if (fs.existsSync(abs) && (fs.statSync(abs).isFile() || has(abs))) return null;
  let job = null;
  try { job = resolveJobDir(arg); } catch (e) { if (!fs.existsSync(abs)) throw new UserError(e.message, e.hint); }
  if (!job || !fs.existsSync(job) || !fs.statSync(job).isDirectory()) return null;
  const project = path.join(job, 'project');
  if (has(project)) return { job, project };
  if (fs.existsSync(path.join(job, 'job.json')) || fs.existsSync(path.join(job, 'render.json'))) {
    throw new UserError(`the job ${job} has no project/${page || 'index.html'} to export`,
      'pass the project folder the job was rendered from: showtime export html <project-folder> (render.json "project" names it)');
  }
  return null;
}

/** --lang, showtime.json "lang"/"language", <html lang>, narration.md front matter (lang: es), else "en". */
export function projectLang(flag, cfg, pageHtml, dir) {
  const ok = (v) => (typeof v === 'string' && /^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$/.test(v.trim()) ? v.trim() : null);
  if (flag !== undefined) {
    const v = ok(String(flag));
    if (!v) throw new UserError(`--lang must be a language code such as es or pt-BR (got ${flag})`);
    return v;
  }
  const fromCfg = ok(cfg && (cfg.lang || cfg.language));
  if (fromCfg) return fromCfg;
  const fromPage = ok((/<html[^>]*\slang=["']?([A-Za-z0-9-]{2,20})/i.exec(pageHtml || '') || [])[1]);
  if (fromPage) return fromPage;
  for (const f of ['narration.md', path.join('voice', 'narration.md')]) {
    try {
      const txt = fs.readFileSync(path.join(dir, f), 'utf8');
      const fm = /^---\s*\n([\s\S]*?)\n---/.exec(txt);
      const m = fm && /^lang:\s*["']?([A-Za-z0-9-]+)/m.exec(fm[1]);
      if (m && ok(m[1])) return m[1];
    } catch { /* no narration */ }
  }
  return 'en';
}

async function main() {
  const a = parseCli(SPEC);
  const T0 = Date.now();
  const pos = a._.slice();
  if (pos[0] === 'html') pos.shift();
  else if (pos.length && fs.existsSync(pos[0])) { /* `showtime export <project>` means html */ }
  else if (pos.length && /^(mp4|mov|webm|gif|video)$/i.test(pos[0])) throw new UserError(`"${pos[0]}" is not an export format here`, 'video files come from `showtime render <project>`, platform versions from `showtime deliver exports <video>`');
  else throw new UserError(pos.length ? `unknown export format "${pos[0]}"` : 'missing the export format', 'showtime export html <project>');
  // `<job> --folder out`: --folder takes no value, so the word after it is the output folder
  if (pos.length === 2 && a.folder && a.output === undefined) a.output = pos.pop();
  if (pos.length > 1) throw new UserError(`expected one project, got: ${pos.join(' ')}`, 'showtime export html <project-folder|job> [--folder -o OUT]');
  const quiet = !!a.quiet;
  const say = (m) => { if (!quiet) info(m); };
  const warnings = [];
  const addWarn = (m) => { if (!warnings.includes(m)) { warnings.push(m); warn(m); } };

  // a job (as qa and review take it) exports its project/ folder, into the job folder by default
  const fromJob = jobProject(pos[0] || '.', a.page);
  const proj = resolveProject(fromJob ? fromJob.project : (pos[0] || '.'), { page: a.page });
  { const w = staleKitWarning(proj.dir); if (w) addWarn(w); }
  const cfg = { ...proj.config };
  const folder = !!a.folder;
  const controls = String(a.controls || 'full').toLowerCase();
  if (!['full', 'minimal', 'none'].includes(controls)) throw new UserError(`--controls must be full, minimal or none (got ${a.controls})`);
  const target = String(a.target || 'file').toLowerCase();
  if (!['file', 'artifact'].includes(target)) throw new UserError(`--target must be file or artifact (got ${a.target})`);
  if (target === 'artifact' && folder) throw new UserError('--target artifact writes one file; leave out --folder');
  let maxMb = a['max-mb'] === undefined ? 16 : Number(a['max-mb']);
  if (!(maxMb >= 0)) throw new UserError(`--max-mb must be a number >= 0 (got ${a['max-mb']})`);
  if (target === 'artifact' && (maxMb === 0 || maxMb > 16)) { addWarn('--target artifact: the file must stay under 16 MB (the artifact limit); --max-mb set to 16'); maxMb = 16; }
  const fitMode = String(a.fit || 'auto').toLowerCase();
  if (!['auto', 'off'].includes(fitMode)) throw new UserError(`--fit must be auto or off (got ${a.fit})`);
  const title = String(a.title || cfg.title || proj.title);
  if (!a.title && genericTitle(title)) addWarn(`the title is "${title}", a default: it shows on the start screen, in the browser tab, on a phone's home screen and in link previews; set "title" in showtime.json (or --title)`);
  const shareFlags = { url: a['share-url'], image: a['share-image'] };
  const shareCfg = cfg.share && typeof cfg.share === 'object' ? cfg.share : {};
  const shareUrl = shareFlags.url !== undefined ? String(shareFlags.url).trim() : String(shareCfg.url || '').trim();
  if (shareUrl && !/^https?:\/\/[^\s/]+/i.test(shareUrl)) throw new UserError(`the share URL must start with https:// or http:// (got ${shareUrl})`, '--share-url https://example.com/my-video/ (or showtime.json "share": {"url"})');
  const shareImageGiven = !!String(shareFlags.image ?? shareCfg.image ?? '').trim();
  const startKind = String(a.start || 'card').toLowerCase();
  if (!['card', 'poster'].includes(startKind)) throw new UserError(`--start must be card or poster (got ${a.start})`);
  const cardMode = startKind === 'card' && !a['autoplay-muted'];
  // stop-and-ask questions: their words and voice cues are checked before anything is built
  const qs = proj.questions || { list: [], issues: [], off: true };
  const askQuestions = !qs.off && !a['no-questions'];
  const autoContinue = a['auto-continue'] === undefined ? 0 : Number(a['auto-continue']);
  if (!(autoContinue >= 0)) throw new UserError(`--auto-continue must be seconds >= 0 (got ${a['auto-continue']})`);
  if (askQuestions) questionErrors(qs.issues, addWarn);
  resolveFF();

  // ---- output location (never overwrite)
  let out;
  let jobBase = null;
  if (a.output && a.job) {
    // --job J -o name.html: that name inside the job folder
    jobBase = resolveJobDir(a.job);
    if (!jobBase || !fs.existsSync(jobBase)) throw new UserError(`no job named "${a.job}"`, 'list jobs with `showtime job list`');
    if (path.isAbsolute(String(a.output)) && path.resolve(path.dirname(String(a.output))) !== path.resolve(jobBase)) {
      throw new UserError(`with --job, -o is a name inside the job folder (got ${a.output})`,
        `use -o ${path.basename(String(a.output))} --job ${a.job}, or -o ${a.output} without --job`);
    }
  }
  if (a.output) {
    const o = String(a.output);
    let want = jobBase && !path.isAbsolute(o) ? path.join(jobBase, o) : path.resolve(o);
    const isDir = /[\\/]$/.test(String(a.output)) || (fs.existsSync(want) && fs.statSync(want).isDirectory());
    if (folder) {
      out = fs.existsSync(want) && fs.readdirSync(want).length ? freshPath(want) : want;
    } else if (isDir) {
      // -o an existing folder (or one ending in /): the file goes inside it
      want = path.join(want, `${proj.slug}.html`);
      out = freshPath(want);
    } else {
      if (!path.extname(want)) want += '.html';
      out = freshPath(want);
    }
    if (out !== want) addWarn(`${want} exists; writing ${path.basename(out)} instead (exports never overwrite)`);
  } else {
    const dir = a.job ? resolveJobDir(a.job) : (fromJob && !a['out-dir'] ? fromJob.job : jobDir(proj.slug, a['out-dir']));
    if (!dir || !fs.existsSync(dir)) throw new UserError(`no job named "${a.job}"`, 'list jobs with `showtime job list`');
    out = freshPath(path.join(dir, folder ? `${proj.slug}-html` : `${proj.slug}.html`));
  }
  const workDir = fs.mkdtempSync(path.join(os.tmpdir(), 'showtime-export-'));

  const server = await startServer({ root: proj.dir, port: 0 });
  try {
    // ---- 1) play the page through once in the render runtime
    say(c.dim(`  probing ${proj.page} (${cfg.width || 1920}x${cfg.height || 1080})...`));
    const posterArg = a.poster !== undefined ? String(a.poster).trim() : null;
    const noPoster = !!posterArg && posterArg.toLowerCase() === 'none';
    let posterT = 'auto';                        // no time given: a representative frame at 40%
    if (noPoster) posterT = null;
    else if (posterArg) posterT = parseTime(posterArg);
    else if (cfg.poster !== undefined && cfg.poster !== null && cfg.poster !== false && isFinite(Number(cfg.poster))) posterT = Number(cfg.poster);
    const wantAudio = String(a.audio || 'auto').toLowerCase() !== 'none';
    // the start screen draws the poster frame live: an image only for --start poster (or a --poster given)
    const posterImage = !cardMode || (posterArg !== null && !noPoster);
    // the poster frame is also the link-preview image when none is given (a folder, or a file with a share URL)
    const sharePoster = !shareImageGiven && (folder || !!shareUrl);
    const t1 = Date.now();
    const pr = await probeProject({ url: server.url, page: proj.page, config: cfg, gpu: a.gpu, posterT, wantScore: wantAudio, posterImage: posterImage || sharePoster });
    const D = pr.info.duration;
    if (askQuestions) questionErrors(timeIssues(qs.list, D), addWarn);
    say(c.dim(`  played ${pr.samples} frames through in ${fmtDuration(Date.now() - t1)}; ${pr.requests.length} files requested`));
    for (const e of pr.errors.slice(0, 3)) addWarn(`page error: ${e}`);
    for (const u of pr.blocked.slice(0, 5)) addWarn(`the page requests ${u} from the internet; it cannot be packed (use a local copy)`);
    const poster = posterImage ? pr.poster : null, posterTime = pr.posterT;
    if (!(Array.isArray(cfg.chapters) && cfg.chapters.length) && genericChapters(pr.chapters)) {
      const names = pr.chapters.slice(0, 2).map((x) => `"${x.label || '(no name)'}"`).join(', ');
      addWarn(`the chapters are named after the scenes (${names}, ...): they show in the chapter menu and on the scrubber; name them in showtime.json "chapters": [[0, "Intro"], [12.5, "How it works"]]`);
    }

    // ---- 2) files
    const pageHtml = fs.readFileSync(path.join(proj.dir, ...proj.page.split('/')), 'utf8');
    const pagePath = '/' + proj.page;
    const exclude = audioInputs(cfg.audio, proj.dir).map((f) => '/' + path.relative(proj.dir, f).split(path.sep).join('/')).filter((p) => !p.startsWith('/..'));
    const col = await collectFiles({ serverUrl: server.url, pagePath, pageHtml, requests: pr.requests, domText: pr.domText, allFonts: a['all-fonts'], exclude, warn: addWarn });
    missingFiles(col.failures, addWarn);
    if (col.droppedFaces) say(c.dim(`  dropped ${col.droppedFaces} font faces for scripts the video never uses (--all-fonts keeps them)`));
    preferWoff2(col.files, pageHtml, pagePath);
    // canvas films: font families no frame draws with (and no project script names) are left out
    if (pr.canvasFonts && !a['all-fonts']) {
      const used = new Set(pr.canvasFonts);
      const projText = [...col.files].filter(([p, f]) => !/^\/_(st|lib|assets)\//.test(p) && f.text !== undefined && isJs(f.mime)).map(([, f]) => f.text).join('\n').toLowerCase();
      for (const [, f] of col.files) {
        if (!isCss(f.mime) || f.text === undefined) continue;
        for (const m of f.text.matchAll(/font-family\s*:\s*['"]?([^;'"}]+)/gi)) { const fam = m[1].trim().toLowerCase(); if (projText.includes(fam)) used.add(fam); }
      }
      const r = pruneFontFamilies(col.files, used, pageHtml, pagePath);
      if (r.files) say(c.dim(`  left out ${r.files} font file(s) of families no frame draws with (--all-fonts keeps them)`));
    }
    // smaller runtime: film/synth sections the project never calls, then comments and whitespace
    const minify = String(a.minify || 'auto').toLowerCase() !== 'off';
    const shrink = { before: 0, after: 0, parts: [] };
    if (minify) {
      const usedText = [pageHtml, ...[...col.files].filter(([p, f]) => !/^\/_(st|lib|assets)\//.test(p) && f.text !== undefined).map(([, f]) => f.text)].join('\n');
      for (const [p, f] of col.files) {
        if (f.text === undefined) continue;
        const before = f.text.length;
        let t = f.text;
        if (p === '/_st/film.js' || p === '/_st/synth.js') {
          const r = pruneParts(t, usedText);
          t = r.text;
          if (r.dropped.length) shrink.parts.push(`${p.slice(5)}: ${r.dropped.join(', ')}`);
        }
        if (isJs(f.mime) && !p.startsWith('/_lib/')) t = minifyJs(t, { module: /\.mjs$/.test(p) }).text;
        else if (isCss(f.mime)) t = minifyCss(t);
        else if (/json/.test(f.mime) && !/\.(geo|topo)json$/i.test(p)) { try { t = JSON.stringify(JSON.parse(t)); } catch { /* keep */ } }
        if (t !== f.text) { f.text = t; f.bytes = Buffer.from(t); }
        shrink.before += before; shrink.after += f.text.length;
      }
      if (shrink.before > shrink.after) say(c.dim(`  runtime and scripts ${fmtBytes(shrink.before)} -> ${fmtBytes(shrink.after)}${shrink.parts.length ? ' (not used: ' + shrink.parts.join('; ') + ')' : ''}`));
    }
    if (!folder) {
      for (const [p, f] of col.files) {
        if (isMedia(f.mime) && f.bytes.length > 4 * MB) addWarn(`${p} is ${fmtBytes(f.bytes.length)} of footage packed as base64 (+33%); consider --folder`);
      }
    }

    // ---- 3) audio
    const audioFile = a['audio-file'] ? path.resolve(String(a['audio-file'])) : null;
    if (audioFile && a.audio && !['auto', 'embed'].includes(String(a.audio).toLowerCase())) throw new UserError('--audio-file embeds a file: leave out --audio, or use --audio embed');
    const am = audioFile ? { mode: 'embed' } : resolveAudioMode(a.audio, { hasScore: !!pr.info.hasScore, mix: hasMix(cfg) });
    if (am.dropsMix) addWarn('--audio score plays only ST.score: the showtime.json "audio" mix is not included (use --audio embed for both)');
    let audioManifest = { mode: 'none' };
    let audioPack = null;
    let audioReport = { mode: am.mode };
    let credits = [];
    if (am.mode === 'score') {
      const g = pr.score && !a['no-loudnorm'] ? await scoreGain({ score: pr.score, cfg, workDir, lufsArg: a.lufs }) : { gainDb: 0, ceilDb: 0 };
      audioManifest = { mode: 'score', gainDb: g.gainDb, ceilDb: g.ceilDb };
      audioReport = { mode: 'score', gain_db: g.gainDb, lufs: g.lufs ?? null, true_peak: g.true_peak ?? null };
      if (g.reached === false && g.lufs !== null && g.lufs !== undefined) addWarn(`the live score plays at ${g.lufs} LUFS (target ${g.target}): its peaks are too sharp for more gain`);
      say(c.dim(`  audio: ST.score rendered live in the browser (gain ${g.gainDb >= 0 ? '+' : ''}${g.gainDb} dB -> ${g.lufs ?? '?'} LUFS)`));
    } else if (am.mode === 'embed') {
      const t = Date.now();
      const r = await buildEmbedAudio({ proj, cfg, duration: D, score: pr.score, workDir, codec: a.codec, bitrate: a.bitrate || '96k', lufsArg: a.lufs, noLoudnorm: a['no-loudnorm'], warn: addWarn, file: audioFile });
      if (r) {
        const apath = `/_export/soundtrack${r.ext}`;
        audioPack = { path: apath, mime: r.mime, file: r.file };
        audioManifest = { mode: 'file', file: apath, type: r.mime };
        audioReport = { mode: 'embed', codec: r.codec, bitrate: r.bitrate, bytes: r.bytes, lufs: r.lufs, true_peak: r.true_peak, sources: r.sources };
        credits = r.credits || [];
        say(c.dim(`  audio: ${r.sources.join(' + ')} -> ${r.codec.toUpperCase()} ${r.bitrate}, ${fmtBytes(r.bytes)}, ${r.lufs === null ? '?' : r.lufs.toFixed(1)} LUFS (${fmtDuration(Date.now() - t)})`));
      } else audioReport = { mode: 'none' };
    }

    // ---- 4) size budget (single file): over it because of footage -> re-encode the clips to fit
    const sizeHints = { mode: am.mode, html: pageHtml, scoreOnly: !!pr.info.hasScore && !hasMix(cfg) };
    const refit = [];
    const fit = async (over) => {
      if (fitMode === 'off') return false;
      const r = await fitFootage(col.files, { over, workDir: path.join(workDir, 'fit'), say: (m) => say(c.dim(`  fit: ${m}`)) });
      // one entry per clip: a later pass re-encodes the same clip again (its original size, its last encode)
      for (const it of r.items) {
        const i = refit.findIndex((x) => x.path === it.path);
        if (i >= 0) refit[i] = it; else refit.push(it);
      }
      if (!r.items.length && r.reason) addWarn(`could not fit the footage under ${maxMb} MB: ${r.reason}`);
      return r.items.length > 0;
    };
    if (!folder && maxMb > 0) {
      const estimate = () => estimateSingle(col.files, { poster, audioBytes: audioPack ? fs.statSync(audioPack.file).size : 0, html: pageHtml, compress: minify });
      let est = estimate();
      // an encoder lands near, not on, the bitrate it is given: shave again while it helps (at most 3 passes)
      for (let k = 0; k < 3 && est > maxMb * MB && await fit(est - maxMb * MB); k++) est = estimate();
      if (est > maxMb * MB) throw sizeError(est, maxMb, col.files, poster, audioPack, sizeHints, fitMode);
    }

    // ---- 5) write
    // only what the stage reads from showtime.json travels (no audio paths or other local details)
    const pubCfg = {};
    for (const k of ['width', 'height', 'fps', 'duration', 'background', 'title', 'poster', 'seed', 'chapters', 'subtitle', 'kicker']) if (cfg[k] !== undefined) pubCfg[k] = cfg[k];
    // the page reads its questions (ST.questions) to draw its pause and think beats, as in the MP4,
    // whether or not the player stops for them
    if (Array.isArray(cfg.questions)) pubCfg.questions = cfg.questions;
    if (col.files.has('/showtime.json')) {
      const txt = JSON.stringify(pubCfg, null, 2);
      col.files.set('/showtime.json', { mime: 'application/json', bytes: Buffer.from(txt), text: txt, source: 'config' });
    }
    // the page's language: --lang, else showtime.json "lang", the page's <html lang>, the narration's
    // front matter (lang: es), else en. It sets <html lang> and the player's own words (Play, Chapters ...)
    const lang = projectLang(a.lang, cfg, pageHtml, proj.dir);
    let share;
    try {
      share = resolveShare({ flags: shareFlags, cfg, folder, out, dirs: [proj.dir, process.cwd()], poster: sharePoster ? pr.poster : null,
        width: pr.info.width, height: pr.info.height, fresh: freshPath });
    } catch (e) { if (e.user) throw new UserError(e.message); throw e; }
    for (const w of share.warnings) addWarn(w);
    for (const n of share.notes) say(c.dim(`  ${n}`));
    const manifest = {
      v: 1, generator: `showtime ${showtimeVersion()}`, title, page: pagePath,
      width: pr.info.width, height: pr.info.height, fps: pr.info.fps, duration: D, background: pr.info.background || cfg.background || '#000',
      seed: cfg.seed === undefined ? 1 : cfg.seed, config: pubCfg, chapters: pr.chapters, lang,
      poster: posterTime, audio: audioManifest, controls, autoplayMuted: !!a['autoplay-muted'], loop: !!a.loop,
      ...(target === 'artifact' ? { host: 'artifact' } : {}),
      // the player asks them (with --controls none an embedding page asks them, from socratic.json)
      ...(askQuestions && qs.list.length && controls !== 'none' ? { questions: playerQuestions(qs.list), autoContinue } : {}),
      start: startCard({ card: cardMode, title, look: pr.look, cfg, subtitle: a.subtitle, kicker: a.kicker }),
    };
    const write = () => writeExport({
      files: col.files, manifest, html: pageHtml, poster, audio: audioPack, out, folder, noCsp: !!a['no-csp'], lang, minify, compress: minify,
      description: share.description || undefined, shareFiles: share.files,
      // a preview without a written description still says what the link opens
      share: shareMeta({ title, ...share, description: share.description || `An interactive video, ${fmtLen(D)}${pr.chapters.length > 1 ? `, in ${pr.chapters.length} chapters` : ''}${manifest.questions ? ', that stops and asks' : ''}.` }),
      notice: `${title}\nExported with ${manifest.generator}: an interactive HTML video; every file it uses is packed inside.\n` + notices(col.files, { projDir: proj.dir, extraCredits: credits }),
    });
    let res = write();
    if (!folder && maxMb > 0 && res.bytes > maxMb * MB) {
      // the estimate was a little short: shave the difference off the footage once more
      fs.rmSync(res.output, { force: true });
      if (await fit(res.bytes - maxMb * MB)) res = write();
      if (res.bytes > maxMb * MB) {
        fs.rmSync(res.output, { force: true });
        throw sizeError(res.bytes, maxMb, col.files, poster, audioPack, sizeHints, fitMode);
      }
    }
    if (share.beside) fs.writeFileSync(share.beside.file, share.beside.bytes);
    // socratic.json beside the export: the same questions for a page that drives the player from outside
    let socratic = null;
    if (askQuestions && qs.list.length) {
      const want = path.join(path.dirname(res.output), 'socratic.json');
      socratic = freshPath(want);
      if (socratic !== want) addWarn(`${want} exists; writing ${path.basename(socratic)} instead`);
      fs.writeFileSync(socratic, JSON.stringify(socraticDoc(title, qs.list), null, 2) + '\n');
    }
    if (refit.length) {
      const kb = [...new Set(refit.map((r) => r.kbps))].join('/');
      addWarn(`embedded footage re-encoded for this export only (${refit.length} clip${refit.length > 1 ? 's' : ''} at ${kb} kb/s) to stay under ${maxMb} MB; the project's files are unchanged (--fit off to stop instead, --folder to keep full quality)`);
    }

    const report = {
      output: res.output, folder, bytes: res.bytes, mb: +(res.bytes / MB).toFixed(2), max_mb: folder ? null : maxMb,
      title, target, width: manifest.width, height: manifest.height, fps: manifest.fps, duration: D,
      audio: audioReport, poster: posterTime, chapters: pr.chapters.length, chapter_list: pr.chapters, files: res.files,
      start: manifest.start.card ? 'card' : 'poster', minified: res.minified, compressed: res.compressed, unused_parts: shrink.parts,
      totals: res.totals, largest: res.breakdown.slice(0, 8), footage_refit: refit, warnings, seconds: +((Date.now() - T0) / 1000).toFixed(1),
      questions: askQuestions ? qs.list.map((q) => ({ id: q.id, t: q.t, resume: q.resume })) : [], socratic,
      share: { url: share.url || null, image: share.image ? share.image.href : null, card: share.card, description: share.description || null, image_file: share.beside ? share.beside.file : null },
    };
    if (a.json) process.stdout.write(JSON.stringify(report, null, 2) + '\n');
    else {
      const aTxt = audioReport.mode === 'embed' ? `embedded ${audioReport.codec.toUpperCase()} ${audioReport.bitrate}` : audioReport.mode === 'score' ? 'live score' : 'no sound';
      console.log(`${c.green('exported')} ${res.output}`);
      console.log(`  ${fmtBytes(res.bytes)}${folder ? ' (folder)' : ` of ${maxMb || 'unlimited'} MB`}, ${manifest.width}x${manifest.height} ${manifest.fps} fps ${D.toFixed(2)} s, ${aTxt}, ${pr.chapters.length} chapters, ${res.files} files packed`);
      console.log(`  open it in any browser (double-click); it makes no network request${folder ? '. Serve the folder from a host with byte ranges (GitHub Pages, most web hosts), or open index.html' : ''}`);
      if (socratic) console.log(`  ${qs.list.length} question${qs.list.length > 1 ? 's' : ''}: the video stops and asks${controls === 'none' ? ' (from the embedding page)' : ''}; ${path.basename(socratic)} beside it`);
      showCard({
        title: `${path.basename(res.output)} is ready`, file: res.output,
        facts: [fmtLen(D), `${manifest.width}x${manifest.height}`, fmtBytes(res.bytes)],
        next: openHint(folder ? path.join(res.output, 'index.html') : res.output),
      });
    }
    return 0;
  } finally {
    await server.close().catch(() => {});
    if (!a['keep-work']) fs.rmSync(workDir, { recursive: true, force: true });
    else info(c.dim(`  work folder: ${workDir}`));
  }
}

/**
 * Files the page needs that could not be read. A project file that is not there, or any file the
 * server did not answer for, stops the export (a page with scenes left out must not ship); a missing
 * emoji or runtime file is a warning, as before.
 */
function missingFiles(failures, addWarn) {
  const stop = [];
  for (const f of failures || []) {
    const p = f.path;
    if (p === '/showtime.json') continue;                 // the stage asks for it; a project may have none
    if (f.status === 0) stop.push(`${p} (the server did not answer: ${f.err || 'no response'})`);
    else if (p.startsWith('/_st/emoji/')) addWarn(`emoji ${p.slice(11)} is not installed (it shows as a broken image): run \`showtime assets emoji <char>\``);
    else if (/^\/_(st|lib|assets)\//.test(p)) addWarn(`the page asks for ${p}, which does not exist (${f.status})`);
    else stop.push(`${p} (${f.status === 404 ? 'not found' : `HTTP ${f.status}`}${f.source && f.source !== 'requested' ? `, ${f.source}` : ''})`);
  }
  if (!stop.length) return;
  const shown = stop.slice(0, 12).map((s) => `  ${s}`).join('\n') + (stop.length > 12 ? `\n  ... and ${stop.length - 12} more` : '');
  throw new UserError(`the page needs ${stop.length} file${stop.length > 1 ? 's' : ''} that could not be packed, so the export would play without ${stop.length > 1 ? 'them' : 'it'}:\n${shown}`,
    'add the file or fix the path in the page (`showtime check <project>` loads it the same way); if the server did not answer, run the export again');
}

/** Question issues: errors stop the export (the fix is in showtime.json), warnings are passed on. */
function questionErrors(issues, addWarn) {
  const errs = issues.filter((x) => x.severity === 'error');
  for (const w of issues.filter((x) => x.severity !== 'error')) addWarn(w.message);
  if (!errs.length) return;
  throw new UserError(`showtime.json "questions": ${errs.map((x) => x.message).join('; ')}`,
    `${errs[0].fix}; \`showtime check\` lists every question problem; --no-questions exports a plain player`);
}

/** What the player needs to ask a question (the pause and resume times, the words). */
function playerQuestions(list) {
  return list.map((q) => ({ id: q.id, t: q.t, resume: q.resume, prompt: q.prompt, choices: q.choices, answer: q.answer, reply: q.reply }));
}

/** The start screen: what it says (title, subtitle, kicker) and how it looks (the page's colours and fonts). */
function startCard({ card, title, look, cfg, subtitle, kicker }) {
  const lk = look || {};
  const str = (x) => (x === undefined || x === null ? '' : String(x)).slice(0, 200);
  const colors = {};
  for (const [k, v] of Object.entries(lk.colors || {})) if (/^(#[0-9a-f]{3,8}|rgba?\([\d\s.,%]+\)|hsla?\([\d\s.,%deg]+\))$/i.test(String(v).trim())) colors[k] = String(v).trim();
  const font = (f) => String(f || '').replace(/[;{}<>]/g, '').slice(0, 200);
  return {
    card: !!card, title: str(title),
    // showtime.json "startTitle": false -> the poster frame already says it: only the Play row sits over it
    showTitle: cfg.startTitle !== false,
    subtitle: str(subtitle ?? cfg.subtitle ?? lk.subtitle), kicker: str(kicker ?? cfg.kicker ?? lk.kicker),
    colors, font: font(lk.font), bodyFont: font(lk.bodyFont), fontWeight: Math.min(900, Math.max(300, Number(lk.fontWeight) || 700)),
  };
}

function sizeError(total, maxMb, files, poster, audioPack, { mode, html, scoreOnly }, fitMode = 'auto') {
  const rows = [];
  for (const [p, f] of files) rows.push({ p, cat: category(f.mime, p), n: f.text !== undefined && isText(f.mime) ? jsonBytes(f.text) : Math.ceil(f.bytes.length * 4 / 3) });
  if (audioPack) rows.push({ p: 'soundtrack', cat: 'audio', n: Math.ceil(fs.statSync(audioPack.file).size * 4 / 3) });
  if (poster) rows.push({ p: 'poster frame', cat: 'poster', n: Math.ceil(poster.length * 4 / 3) });
  rows.push({ p: 'player, stage runtime and page', cat: 'player', n: playerBytes(html) });
  const cats = {};
  for (const r of rows) cats[r.cat] = (cats[r.cat] || 0) + r.n;
  rows.sort((x, y) => y.n - x.n);
  const lines = [`the export would be ${fmtBytes(total)}, over the ${maxMb} MB limit.`, '  by kind: ' +
    Object.entries(cats).sort((x, y) => y[1] - x[1]).map(([k, v]) => `${k} ${fmtBytes(v)}`).join(', '), '  largest:'];
  for (const r of rows.slice(0, 6)) lines.push(`    ${fmtBytes(r.n).padStart(9)}  ${r.p}`);
  const tips = [];
  if (cats.video) tips.push(fitMode === 'off' ? '--fit auto re-encodes the clips for this export at the bitrate that fits' : '--folder keeps footage as real files (for hosting), or shorten the clips');
  if (cats.audio && mode === 'embed') tips.push('--bitrate 64k (or --codec opus --bitrate 48k)');
  if (mode === 'embed' && cats.audio && scoreOnly) tips.push('--audio score (the score is rendered in the browser: no audio bytes at all)');
  if (cats.images) tips.push('smaller images (WebP/JPEG at the size they are shown)');
  if (cats.fonts) tips.push('fewer font families/weights');
  tips.push('--folder for hosting, or --max-mb N to allow a bigger file');
  return new UserError(lines.join('\n'), tips.join('; '));
}

runMain(main);

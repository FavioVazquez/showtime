// Adopt a video someone wrote as a function of time (HTML seek/draw page, Python frame generator) into a showtime project
//
//   showtime adopt <folder | page.html | script.py> [-o DIR | --job JOB] [--seek NAME] [--duration S] ...
//
// The original files are never changed: the folder is copied into <project>/src/ and a small
// index.html around the page (or a video layer for Python frames) makes it a normal showtime
// project, so check, snap, render (with --from/--to), qa, captions, the audio mix, export html and
// review-pack all work on it. See references/adopt.md.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { startServer } from './server.mjs';
import {
  parseCli, runMain, UserError, info, warn, c, slugify, jobDir, venvPython, pyEnv, runPyCli, runProc, cpuCount,
  fmtDuration, IS_WIN,
} from './lib/cli.mjs';
import { openBrowser, openStage, openLab, parseSize } from './lib/stagehost.mjs';
import { resolveFF, ffmpeg, probe, hasEncoder } from './lib/ff.mjs';
import { skillDir } from './lib/deps.mjs';
import { resolveJobDir } from './lib/studio/paths.mjs';
import {
  listFiles, pickSource, scanPage, scanDriver, scanPython, driversFor, pageRefs, audioRefs, inlineScripts,
  SKIP_DIRS, VIDEO_EXT, AUDIO_EXT, TIME_FNS,
} from './lib/adopt/scan.mjs';
import {
  scanClaudeDesign, jsClockLength, cssLoopLength, fitArtboard, fitCss, googleFontLinks, dropFontLinks, fontFetchFailure,
} from './lib/adopt/design.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HARNESS = () => path.join(skillDir(), 'lib', 'st', 'adopt_harness.py');
const COPY_LIMIT = 2 * 1024 ** 3;

const spec = {
  name: 'adopt',
  usage: 'showtime adopt <folder | page.html | export.zip | script.py> [options]',
  summary: 'Adopt a video written as a function of time (HTML page with seek/render/draw(t), canvas, CSS animations, a Claude Design export, or a Python frame generator) into a showtime project, unchanged.',
  description: [
    'Detects the contract, copies the folder into <project>/src/ (the originals are never touched), writes',
    'index.html + showtime.json around it and checks that frames are deterministic. Then every showtime',
    'command works on it: check, snap, render (--from/--to), qa, captions, audio mix, export html, review-pack.',
    '',
    'Contracts:',
    '  page    an HTML page with a time function: window.seek(t), __seek(t), render(t), draw(t) (canvas),',
    '          setTime(t) ... (seconds; --unit ms|frame otherwise) and a duration (DURATION global, --duration)',
    '  clock   an HTML page animated only by CSS/Web Animations/requestAnimationFrame: driven by the virtual clock',
    '  python  a Python script with a frame function (render(t), make_frame(t), render_frame(i) ...) returning a',
    '          Pillow image, a numpy array or RGB bytes: frames are generated in a separate process',
    '  capture a Python script without a frame function: its own main() runs on the copy and its video is ingested',
    '',
    'A Claude Design export (the zip, or its folder) is a clock page: its artboard fills the frame (1080 on the',
    'short side unless --size), its Google Fonts are copied into the project, and its length is read from the',
    'animation (a looping design renders exactly one loop).',
    '',
    'Network: a page that links Google Fonts needs the internet once. adopt fetches the stylesheet and its files',
    '(fonts.googleapis.com, fonts.gstatic.com) and their licences (api.fontsource.org, raw.githubusercontent.com).',
    'Nothing else is sent. With SHOWTIME_OFFLINE=1 it skips them and says what to run later (--refresh).',
    '',
    'Output: <job>/project/ (a new job under ./showtime-out/ unless -o or --job), adopt.json (what was found),',
    'work/adopt/ (logs). `showtime adopt <project> --refresh` copies the source again after you edit it.',
  ].join('\n'),
  options: {
    output: { short: 'o', help: 'project folder to create (default: <new job>/project)', metavar: 'DIR' },
    job: { short: 'j', help: 'put the project in this job (folder or name) as <job>/project', metavar: 'JOB' },
    'out-dir': { help: 'base folder for the showtime-out/ job folder (default: $SHOWTIME_OUT or cwd)', metavar: 'DIR' },
    page: { help: 'the page to adopt, relative to the folder (default: detected)', metavar: 'FILE' },
    script: { help: 'the Python script to adopt, relative to the folder (default: detected)', metavar: 'FILE' },
    mode: { help: 'force the contract: page | clock | python | capture', metavar: 'MODE' },
    seek: { help: 'the page\'s time function (global name or dotted path, e.g. render, app.seekTo)', metavar: 'NAME' },
    fn: { help: 'the Python frame function (e.g. render, make_frame)', metavar: 'NAME' },
    unit: { help: 'what the time function takes: s (default) | ms | frame', metavar: 'UNIT' },
    ready: { help: 'a global the page sets when it is ready (a promise or a flag), e.g. ready', metavar: 'NAME' },
    setup: { help: 'a JS file run in the page once before the first frame (await allowed), for data the driver injected', metavar: 'FILE' },
    duration: { short: 'd', help: 'length in seconds (default: the page/script DURATION, else its driver)', metavar: 'S' },
    fps: { help: 'frames per second (default: the page/script FPS, else 30)', metavar: 'N' },
    size: { help: 'WIDTHxHEIGHT (default: the page/script size, its driver\'s viewport, else 1920x1080; a Claude Design artboard: 1080 on the short side)', metavar: 'WxH' },
    python: { help: 'Python interpreter for a script (default: the folder\'s .venv, else showtime\'s, else python3)', metavar: 'PATH' },
    workers: { short: 'w', help: 'processes for Python frames (default: up to 8)', metavar: 'N' },
    timeout: { help: 'minutes a Python script may run (default 30)', metavar: 'MIN' },
    root: { help: 'folder to copy when a page or script is given (default: its folder)', metavar: 'DIR' },
    refresh: { type: 'boolean', help: 're-adopt an adopted project from its source (after you edited the original)' },
    'allow-network': { type: 'boolean', help: 'let an adopted Python script use the network (blocked by default)' },
    'allow-license': { type: 'boolean', help: 'copy the page\'s Google Fonts even when their license is not OFL/Apache/MIT/UFL (you must be allowed to use them)' },
    'no-check': { type: 'boolean', help: 'skip `showtime check` at the end' },
    json: { type: 'boolean', help: 'print the result as JSON on stdout' },
  },
  examples: [
    'showtime adopt launch-video/                      # finds video.html + render(t) + DURATION',
    'showtime adopt story.html --seek draw --setup setup.js   # a canvas page whose driver injected data',
    'showtime adopt odd_squares.py --job math          # Python render(t) -> Pillow frames',
    'showtime adopt promo/ --mode capture              # run the script\'s own main() and ingest its video',
    'showtime adopt "Launch (12s)-html.zip"            # a Claude Design export: unpacked into the project',
    'showtime adopt showtime-out/math-20260929-101500/project --refresh',
    'showtime check <project>; showtime render <project> --job <job>; showtime qa <job>',
  ],
};

// ------------------------------------------------------------------------------------------ helpers
function readText(f) { try { return fs.readFileSync(f, 'utf8'); } catch { return ''; } }
function readJSON(f) { try { return JSON.parse(fs.readFileSync(f, 'utf8').replace(/^\uFEFF/, '')); } catch { return null; } }
function writeJSON(f, o) { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, JSON.stringify(o, null, 2) + '\n'); }
const posix = (p) => p.split(path.sep).join('/');
/** A path as written into the project's own files (adopt.json, showtime.json): relative to the project folder,
 * with forward slashes, so a project copied or shared names no machine path; absolute only when there is no
 * relative way (another drive). fromProject() reads both forms back. */
const toProject = (dest, p) => {
  if (!p) return p;
  const r = path.relative(dest, path.resolve(p));
  return r === '' ? '.' : path.isAbsolute(r) ? p : posix(r);
};
// an absolute path (written by 0.4.0 and earlier) stays as it is: split on '/', its leading '' would drop the root
const fromProject = (dest, p) => (!p ? p : path.isAbsolute(String(p)) ? String(p) : path.resolve(dest, ...String(p).split('/')));
const rel = (p) => { const r = path.relative(process.cwd(), p); return r && !r.startsWith('..') && !path.isAbsolute(r) ? r : p; };
const sha = (buf) => crypto.createHash('sha256').update(buf).digest('hex');
const even = (n) => Math.max(2, Math.round(n / 2) * 2);

class Findings {
  constructor() { this.items = []; }
  add(level, code, what, why, fix) { this.items.push({ level, code, what, why: why || '', fix: fix || '' }); }
  get errors() { return this.items.filter((f) => f.level === 'error'); }
}

/** Copy a folder into dest, skipping dependency/output folders and videos nobody references. */
function copyTree(src, dest, { keep = new Set() } = {}) {
  let bytes = 0, files = 0;
  const skipped = [];
  const walk = (s, d, relp) => {
    let ents;
    try { ents = fs.readdirSync(s, { withFileTypes: true }); } catch { return; }
    const imgs = ents.filter((e) => e.isFile() && /\.(png|jpe?g|webp|bmp)$/i.test(e.name)).length;
    if (relp && imgs > 200) { skipped.push(`${relp}/ (${imgs} images: a frame dump)`); return; }
    fs.mkdirSync(d, { recursive: true });
    for (const e of ents) {
      const r = relp ? `${relp}/${e.name}` : e.name;
      const sp = path.join(s, e.name), dp = path.join(d, e.name);
      if (e.isDirectory()) {
        if (SKIP_DIRS.has(e.name)) { skipped.push(`${r}/`); continue; }
        walk(sp, dp, r);
      } else if (e.isFile()) {
        if (VIDEO_EXT.test(e.name) && !keep.has(r)) { skipped.push(r); continue; }
        const st = fs.statSync(sp);
        if (bytes + st.size > COPY_LIMIT) { skipped.push(`${r} (over the ${COPY_LIMIT / 1024 ** 3} GB copy limit)`); continue; }
        fs.copyFileSync(sp, dp);
        try { fs.utimesSync(dp, st.atime, st.mtime); } catch { /* keep going */ }
        bytes += st.size; files++;
      }
    }
  };
  walk(src, dest, '');
  return { bytes, files, skipped };
}

function findPython(root, entryDir, forced) {
  if (forced) {
    if (!fs.existsSync(forced) && !/^[\w.-]+$/.test(forced)) throw new UserError(`--python ${forced} does not exist`);
    return { exe: forced, from: '--python' };
  }
  // the project's own virtualenv: the folder of the script and its parents up to the adopted root
  let d = entryDir;
  for (let i = 0; i < 6; i++) {
    for (const v of ['.venv', 'venv', 'env']) {
      const p = IS_WIN ? path.join(d, v, 'Scripts', 'python.exe') : path.join(d, v, 'bin', 'python');
      if (fs.existsSync(p)) return { exe: p, from: path.join(d, v) };
    }
    if (path.resolve(d) === path.resolve(root)) break;
    const up = path.dirname(d);
    if (up === d) break;
    d = up;
  }
  const sv = venvPython();
  if (sv) return { exe: sv, from: 'showtime venv' };
  return { exe: IS_WIN ? 'python' : 'python3', from: 'PATH' };
}

/** Environment for adopted Python: showtime's ffmpeg first on PATH (bare `ffmpeg` calls work), UTF-8. */
function scriptEnv(allowNet) {
  const env = pyEnv();
  delete env.PYTHONPATH;          // the script sees its own imports, not showtime's package
  env.PYTHONDONTWRITEBYTECODE = '1';
  env.MPLBACKEND = env.MPLBACKEND || 'Agg';
  env.SDL_VIDEODRIVER = env.SDL_VIDEODRIVER || 'dummy';
  if (allowNet) env.SHOWTIME_ADOPT_NET = '1';
  return env;
}

// ---------------------------------------------------------------------------------------- main
async function main() {
  const a = parseCli(spec);
  if (!a._[0]) throw new UserError('nothing to adopt', 'pass a folder, an .html page or a .py script: showtime adopt launch-video/');
  if (a._.length > 1) throw new UserError(`one source at a time (got ${a._.length})`, 'adopt the folder, or pass --page/--script to pick the file');
  const t0 = Date.now();
  const findings = new Findings();
  let src = path.resolve(a._[0]);
  if (!fs.existsSync(src)) throw new UserError(`not found: ${src}`, 'pass the folder or file the video was written in');

  // --refresh: an adopted project -> its recorded source and options
  let prev = null, dest = null;
  const cfgAt = path.join(fs.statSync(src).isDirectory() ? src : path.dirname(src), 'showtime.json');
  const existing = readJSON(cfgAt);
  if (existing && existing.adopt) {
    if (!a.refresh) {
      throw new UserError(`${rel(path.dirname(cfgAt))} is already an adopted project (from ${existing.adopt.source})`,
        `run \`showtime adopt ${rel(path.dirname(cfgAt))} --refresh\` to copy the source again, or work on it directly: showtime check ${rel(path.dirname(cfgAt))}`);
    }
    prev = existing.adopt;
    dest = path.dirname(cfgAt);
    src = fromProject(dest, prev.source);          // relative to the project (absolute before 0.4.1)
    if (!fs.existsSync(src)) throw new UserError(`the source of this project is gone: ${src}`, 'adopt the new location instead: showtime adopt <folder> -o <new project>');
    for (const k of ['mode', 'seek', 'fn', 'unit', 'ready', 'duration', 'fps', 'size', 'python', 'workers', 'timeout']) {
      if (a[k] === undefined && prev.options && prev.options[k] !== undefined) a[k] = String(prev.options[k]);
    }
    if (!a['allow-license'] && prev.options && prev.options.allow_license) a['allow-license'] = true;
    if (!a.page && prev.entry && prev.kind !== 'python' && prev.kind !== 'capture') a.page = prev.entry;
    if (!a.script && prev.entry && (prev.kind === 'python' || prev.kind === 'capture')) a.script = prev.entry;
    if (!a.root && prev.root && !prev.zip) a.root = fromProject(dest, prev.root);
  } else if (existing && !a.refresh && fs.statSync(src).isDirectory() &&
             (fs.existsSync(path.join(src, 'index.html')) && /\/_st\/stage\.js|ST\.onSeek|Film\./.test(readText(path.join(src, 'index.html'))))) {
    throw new UserError(`${rel(src)} is already a showtime project`, `use it directly: showtime check ${rel(src)}`);
  } else if (a.refresh) {
    throw new UserError(`${rel(src)} is not an adopted project (no "adopt" block in showtime.json)`, 'drop --refresh to adopt it');
  }

  // what to adopt: root folder + entry file
  let root, entry, job = null, zip = null;
  if (fs.statSync(src).isFile() && /\.zip$/i.test(src)) {
    // an export zip: the project is made first and the zip is unpacked into its src/ (the zip is the original)
    zip = src;
    if (!dest) ({ dest, job } = await chooseDest(a, slugify(path.basename(src).replace(/\.zip$/i, '').replace(/[-_ ]html$/i, '')) || 'adopted', src, null));
    root = await unzipInto(zip, path.join(dest, 'src'));
    entry = a.page || null;
  } else if (fs.statSync(src).isFile()) {
    root = path.resolve(a.root || path.dirname(src));
    entry = posix(path.relative(root, src));
    if (entry.startsWith('..')) throw new UserError(`--root ${a.root} does not contain ${src}`);
  } else {
    root = src;
    entry = a.page || a.script || null;
  }
  const files = listFiles(root);
  const pick = pickSource(root, files);
  if (!entry) entry = pick.file;
  if (!entry) {
    throw new UserError(`no video source found in ${rel(root)}`,
      'adopt looks for an .html page with a time function (seek/render/draw(t)) or animations, or a .py script that ' +
      'draws frames; pass the file itself (showtime adopt <folder>/video.html) or --page/--script');
  }
  const entryAbs = path.join(root, ...entry.split('/'));
  if (!fs.existsSync(entryAbs)) throw new UserError(`${entry} does not exist in ${rel(root)}`);
  let kind = a.mode || (/\.py$/i.test(entry) ? 'python' : /\.html?$/i.test(entry) ? 'page' : null);
  if (!['page', 'clock', 'python', 'capture'].includes(kind)) {
    throw new UserError(`cannot adopt ${entry}: not an .html page or a .py script`, 'pass --mode page|clock|python|capture with a page or a script');
  }
  if ((kind === 'python' || kind === 'capture') && scanPython(readText(entryAbs)).manim) {
    throw new UserError(`${entry} is a Manim scene`, 'showtime has a Manim path: showtime manim new <name> (references/manim.md), or render it with Manim and bring the video in as footage');
  }

  // where the project goes
  if (!dest) {
    const base = path.basename(entry).replace(/\.(dc\.)?\w+$/, '');
    ({ dest, job } = await chooseDest(a, slugify(/^(index|main)$/i.test(base) ? path.basename(root) : base), src, root));
  }
  fs.mkdirSync(dest, { recursive: true });
  const workDir = path.join(dest, 'work', 'adopt');
  fs.mkdirSync(workDir, { recursive: true });

  // copy the source (never touch the original)
  const srcDir = path.join(dest, 'src');
  if (prev && !zip) fs.rmSync(srcDir, { recursive: true, force: true });
  const keep = new Set();
  if (kind === 'page' || kind === 'clock') {
    const pageDir = path.posix.dirname(entry);
    for (const r of pageRefs(readText(entryAbs))) {
      const j = path.posix.normalize(path.posix.join(pageDir === '.' ? '' : pageDir, r.ref));
      if (VIDEO_EXT.test(j)) keep.add(j);
    }
  }
  if (kind === 'python' || kind === 'capture') {
    // footage the script reads (a video it writes is skipped: the copy makes its own)
    const text = readText(entryAbs);
    for (const f of files) if (VIDEO_EXT.test(f) && text.includes(path.posix.basename(f))) keep.add(f);
    for (const f of [...keep]) {
      const b = path.posix.basename(f);
      // named as the output (`out = "x.mp4"`, the last ffmpeg argument): not an input
      if (new RegExp(`(?:out\\w*|output\\w*|OUT\\w*)\\s*=\\s*[^\\n]*["'\`]${b.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}["'\`]`).test(text)) keep.delete(f);
    }
  }
  let copied;
  if (zip) {
    copied = { files: files.length, bytes: files.reduce((n, f) => n + fs.statSync(path.join(root, ...f.split('/'))).size, 0), skipped: [] };
    info(c.dim(`  unpacked ${copied.files} files from ${path.basename(zip)} into ${rel(root)}`));
  } else {
    copied = copyTree(root, srcDir, { keep });
    info(c.dim(`  copied ${copied.files} files from ${rel(root)} into ${rel(srcDir)}${copied.skipped.length ? ` (skipped ${copied.skipped.slice(0, 4).join(', ')}${copied.skipped.length > 4 ? ', ...' : ''})` : ''}`));
  }

  const ctx = { a, root, entry, entryAbs, dest, srcDir, workDir, findings, pick, files, prev, zip };
  let res;
  if (kind === 'page' || kind === 'clock') res = await adoptPage(ctx, kind);
  else res = await adoptPython(ctx, kind);

  // showtime.json: keep whatever the user added (audio, poster, captions), refresh what adopt owns
  const cfgPath = path.join(dest, 'showtime.json');
  const cfg = readJSON(cfgPath) || {};
  const source = zip || (src === root ? root : path.resolve(src));
  const adoptBlock = {
    source: toProject(dest, source), root: toProject(dest, root), entry,
    kind: res.kind, contract: res.contract, adopted: new Date().toISOString(), options: res.options,
    ...(zip ? { zip: true } : {}), ...(res.made ? { made: res.made } : {}),
  };
  const outCfg = {
    title: cfg.title || res.title || path.basename(entry).replace(/\.\w+$/, ''),
    width: res.width, height: res.height, fps: res.fps, duration: res.duration,
    background: cfg.background || res.background || '#000000',
    ...Object.fromEntries(Object.entries(cfg).filter(([k]) => !['width', 'height', 'fps', 'duration', 'adopt'].includes(k))),
    adopt: adoptBlock,
  };
  if (!cfg.audio && res.audio) outCfg.audio = res.audio;
  if (outCfg.poster === undefined) outCfg.poster = null;
  if (outCfg.poster === null) delete outCfg.poster;
  writeJSON(cfgPath, outCfg);
  if (res.mix && !fs.existsSync(path.join(dest, 'audio', 'mix.json'))) writeJSON(path.join(dest, 'audio', 'mix.json'), res.mix);

  // determinism
  const det = res.determinism;

  // check
  let check = null;
  if (!a['no-check'] && !findings.errors.length) check = await runCheck(dest);

  const report = {
    ok: !findings.errors.length && (!check || check.errors === 0) && (!det || det.verdict !== 'differs'),
    project: dest, job, source, entry, kind: res.kind, contract: res.contract,
    ...(res.made ? { made: res.made, design: res.design } : {}),
    width: res.width, height: res.height, fps: res.fps, duration: res.duration, loop: res.loop || null, sources: res.sources,
    fonts: res.fonts || [],
    audio: res.audioFiles || [], determinism: det, check, findings: findings.items, copied: { files: copied.files, bytes: copied.bytes, skipped: copied.skipped },
    seconds: Math.round((Date.now() - t0) / 100) / 10,
  };
  // on disk, paths relative to the project (as in showtime.json); the printed report keeps them absolute
  writeJSON(path.join(dest, 'adopt.json'), {
    ...report, project: '.', job: toProject(dest, job), source: toProject(dest, source),
    ...(check ? { check: { ...check, report: toProject(dest, check.report), sheet: toProject(dest, check.sheet) } } : {}),
  });
  if (job) await noteJob(job, dest, report);
  printSummary(report, a);
  if (findings.errors.length || (check && check.errors) || (det && det.verdict === 'differs')) return 1;
  return 0;
}

function isInside(child, parent) {
  const r = path.relative(parent, child);
  return r === '' || (!r.startsWith('..') && !path.isAbsolute(r));
}

/** The project folder (and its job) for a new adoption. -> {dest, job} */
async function chooseDest(a, slug, src, root) {
  let dest, job = null;
  if (a.output) dest = path.resolve(a.output);
  else {
    job = a.job ? resolveJobDir(a.job) : await newJob(slug, a, src);
    dest = path.join(job, 'project');
    for (let n = 2; fs.existsSync(dest); n++) dest = path.join(job, `project-${n}`);
  }
  if (fs.existsSync(dest) && fs.readdirSync(dest).length) {
    throw new UserError(`${rel(dest)} already exists and is not empty`, 'pick another -o folder (adopt never overwrites)');
  }
  if (root && isInside(dest, root)) throw new UserError(`the project folder ${rel(dest)} would be inside the folder being adopted`, 'pass -o outside it, or run from another folder');
  return { dest, job };
}

// unpacked into <out>.new first: the old folder is replaced only once every entry is out and checked
// (a zip that fails its CRC halfway leaves the project as it was)
const UNZIP_PY = `
import sys, zipfile, shutil, os
src, out = sys.argv[1], sys.argv[2]
cap = int(sys.argv[3]) if len(sys.argv) > 3 else 20000
z = zipfile.ZipFile(src)
total = 0
names = []
infos = z.infolist()
if len(infos) > cap:
    sys.exit("the zip has %d entries (more than %d)" % (len(infos), cap))
for i in infos:
    n = i.filename.replace("\\\\", "/")
    parts = [p for p in n.split("/") if p]
    if n.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
        sys.exit("unsafe path in the zip: " + n)
    if not parts or parts[0] == "__MACOSX" or parts[-1] in (".DS_Store", "Thumbs.db"):
        continue
    total += i.file_size
    if total > 2 << 30:
        sys.exit("the zip unpacks to more than 2 GB")
    names.append(i)
tmp = out.rstrip("/\\\\") + ".new"
if os.path.isdir(tmp):
    shutil.rmtree(tmp)
os.makedirs(tmp)
try:
    for i in names:
        z.extract(i, tmp)
except Exception as e:
    shutil.rmtree(tmp, ignore_errors=True)
    sys.exit("%s (nothing was replaced)" % e)
if os.path.isdir(out):
    shutil.rmtree(out)
os.replace(tmp, out)
print(len(names))
`;
const ZIP_MAX_ENTRIES = 20000;

/** Unpack an export zip into dir (replacing it); a zip holding one top folder -> that folder. */
async function unzipInto(zip, dir) {
  const py = venvPython() || (IS_WIN ? 'python' : 'python3');
  const r = await runProc(py, ['-c', UNZIP_PY, zip, dir, String(ZIP_MAX_ENTRIES)], { timeout: 10 * 60 * 1000 });
  if (r.code !== 0) throw new UserError(`could not unpack ${path.basename(zip)}: ${lastLine(r.stderr) || `exit ${r.code}`}`, 'unpack it yourself and adopt the folder');
  const ents = fs.readdirSync(dir, { withFileTypes: true });
  if (ents.length === 1 && ents[0].isDirectory()) return path.join(dir, ents[0].name);
  return dir;
}

async function newJob(slug, a, src) {
  const r = await runPyCli(['job', 'init', slug || 'adopted', '--goal', `Adopted ${path.basename(src)} (showtime adopt)`, '--json',
    ...(a['out-dir'] ? ['--base', a['out-dir']] : [])], { timeout: 60000 });
  if (r.code === 0) {
    try { return JSON.parse(r.stdout.slice(r.stdout.indexOf('{'))).job; } catch { /* fall back */ }
  }
  return jobDir(slug || 'adopted', a['out-dir']);
}

async function noteJob(job, dest, rep) {
  const args = ['job', 'note', job, '--stage', 'adopt', '--project', dest,
    '--verified', `adopted ${rep.entry} (${rep.made ? `${rep.made}, ` : ''}${rep.contract}), ${rep.width}x${rep.height} ${rep.fps} fps, ${rep.duration} s`];
  if (rep.determinism) args.push('--verified', `determinism: ${rep.determinism.verdict}`);
  if (rep.check) args.push('--verified', `check: ${rep.check.errors} errors, ${rep.check.warnings} warnings`);
  args.push('--next', `showtime render ${dest} --job ${job}`);
  await runPyCli(args, { timeout: 60000 }).catch(() => null);
}

// ------------------------------------------------------------------------------------------- pages
async function adoptPage(ctx, kind) {
  const { a, entry, entryAbs, dest, srcDir, findings, pick } = ctx;
  const html = readText(entryAbs);
  // scan the page with its local classic scripts (the time function often lives in app.js)
  let scanText = html;
  const pageDir = path.dirname(entryAbs);
  for (const m of html.matchAll(/<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>/gi)) {
    const u = m[1];
    if (/^(https?:|\/\/|data:)/i.test(u)) continue;
    const f = path.resolve(pageDir, u.split(/[?#]/)[0]);
    if (fs.existsSync(f) && fs.statSync(f).size < 3e6) scanText += `\n<script>${readText(f)}</script>`;
  }
  const s = scanPage(scanText);
  if (s.hasStage) findings.add('info', 'already_showtime', `${entry} already loads the showtime stage`, '', 'it may work as a showtime project directly');
  if (s.base) findings.add('error', 'base_element', `${entry} has its own <base> element`, 'adopt points <base> at the copied folder so relative files resolve', 'remove the <base> element from a copy and adopt that');
  const drivers = driversFor(entry, pick.drivers.length ? pick.drivers : scanDrivers(ctx.root, ctx.files));
  const drv = mergeDrivers(drivers);

  // references that leave the adopted folder cannot be served
  for (const r of pageRefs(html)) {
    const j = path.posix.normalize(path.posix.join(path.posix.dirname(entry), r.ref));
    if (j.startsWith('..') || r.ref.startsWith('/')) {
      findings.add('error', 'outside_ref', `${entry} loads ${r.ref}, which is outside ${path.basename(ctx.root)}/`,
        'only the adopted folder is copied and served', `adopt the parent folder instead: showtime adopt ${rel(path.dirname(ctx.root))} --page ${posix(path.relative(path.dirname(ctx.root), entryAbs))}`);
    }
  }
  // a Claude Design export: its artboard size and logic class
  const dc = scanClaudeDesign(html);
  // Google Fonts: the same files, copied into the project with their licenses (renders are offline)
  const fonts = await localizeFonts(ctx, html);
  const fontHosts = /^https?:\/\/fonts\.(googleapis|gstatic)\.com\//i;
  const remote = s.remote.filter((u) => !(fonts.report.length && fontHosts.test(u.replace(/&amp;/g, '&') + (/\.com$/.test(u) ? '/' : ''))));
  if (remote.length) {
    findings.add('warning', 'remote', `${entry} loads ${remote.length} file(s) from the internet (${remote[0]}${remote.length > 1 ? ', ...' : ''})`,
      'renders block the network, so these fonts/scripts will be missing', 'download them into the folder, or use installed ones (/_lib/@fontsource/..., `showtime assets font <name>`)');
  }

  // the time function
  let seek = a.seek || null, unit = a.unit || null, why = '';
  // a Claude Design export runs on its runtime's animation frames: a clock page (its runtime's own functions are not a time function)
  if (!seek && kind === 'page' && !dc) {
    const called = drv.calls.map((x) => x.name);
    const inPage = s.fns.map((f) => f.name);
    const fromDriver = called.find((n) => inPage.includes(n)) || called[0];
    if (fromDriver) { seek = fromDriver; why = `${path.basename(drv.files[0] || 'driver')} calls it per frame`; }
    else if (s.fns.length) {
      const pref = [...s.fns].sort((x, y) => TIME_FNS.indexOf(x.name) - TIME_FNS.indexOf(y.name))[0];
      seek = pref.name; why = 'the page defines it';
    }
    if (!unit && seek) {
      const dc = drv.calls.find((x) => x.name === seek);
      const f = s.fns.find((x) => x.name === seek);
      unit = dc ? dc.unit : f && /^(ms|millis|msec)$/i.test(f.param) ? 'ms' : f && /^(i|f|n|frame|fi|idx|index|frameIndex|frameNo)$/.test(f.param) ? 'frame' : 's';
    }
  }
  if (a.mode === 'clock') seek = null;
  unit = unit || 's';
  if (!['s', 'ms', 'frame'].includes(unit)) throw new UserError(`--unit must be s, ms or frame (got ${unit})`);
  if (seek && !/^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*$/.test(seek)) throw new UserError(`--seek must be a global name or dotted path (got ${seek})`);

  const ready = a.ready || s.ready[0] || drv.ready || null;
  // setup the driver did before the frames (data injected from Node/Python)
  let setup = null;
  if (a.setup) {
    const f = path.resolve(a.setup);
    if (!fs.existsSync(f)) throw new UserError(`--setup ${a.setup} does not exist`);
    fs.mkdirSync(path.join(dest, 'adopt'), { recursive: true });
    fs.copyFileSync(f, path.join(dest, 'adopt', 'setup.js'));
    setup = '/adopt/setup.js';
  } else if (ctx.prev && ctx.prev.options && ctx.prev.options.setup && fs.existsSync(path.join(dest, 'adopt', 'setup.js'))) {
    setup = '/adopt/setup.js';
  }
  const needSetup = drv.setup.filter((x) => s.setters.includes(x.name) && !new RegExp(`[^.\\w]${x.name}\\s*\\(`).test(stripDefs(scanText, x.name)));
  if (needSetup.length && !setup) {
    const x = needSetup[0];
    // where the driver's data lives: inside the adopted folder, or one level up (then adopt the parent)
    let dataRel = null, outside = false;
    for (const d of drv.data) {
      const base = path.posix.basename(d.name);
      const inRoot = ctx.files.find((f) => path.posix.basename(f) === base);
      if (inRoot) { dataRel = path.posix.relative(path.posix.dirname(entry), inRoot) || base; break; }
      if (fs.existsSync(path.join(path.dirname(ctx.root), base))) { dataRel = base; outside = true; break; }
    }
    const ex = dataRel && /\.json$/i.test(dataRel) ? `${x.name}(await (await fetch('${outside ? '../' : ''}${dataRel}')).json());`
      : dataRel ? `const text = await (await fetch('${outside ? '../' : ''}${dataRel}')).text();  ${x.name}(/* parse it as ${x.file} does */);`
        : `${x.name}(await (await fetch('data.json')).json());`;
    const cmd = outside
      ? `showtime adopt ${rel(path.dirname(ctx.root))} --page ${posix(path.relative(path.dirname(ctx.root), ctx.entryAbs))} --setup setup.js`
      : `showtime adopt ${rel(ctx.root)} --setup setup.js${ctx.entry !== ctx.pick.file ? ` --page ${entry}` : ''}`;
    findings.add('error', 'needs_setup', `the page expects \`${x.name}(...)\` before its first frame`,
      `its driver ${x.file}:${x.line} calls it with data the page does not load itself${dataRel ? ` (${dataRel}${outside ? `, one folder up from ${path.basename(ctx.root)}/` : ''})` : ''}`,
      `write a small JS file that makes the same call (it runs in the page, relative to ${path.basename(entry)}, and may await fetch), e.g.\n` +
      `         ${ex}\n       then: ${cmd}`);
  }

  // write index.html in probe mode, look at the page for real, then write the final one
  const copyAbs = ctx.zip ? entryAbs : path.join(srcDir, ...entry.split('/'));
  const baseHref = posix(path.relative(dest, path.dirname(copyAbs))) + '/';
  // an artboard (a Claude Design $preview, or the page's own fixed size when --size asks for another) fills
  // the frame: CSS zoom lays it out again at the output size, so text stays sharp
  const asked = parseSize(a.size);
  const art = dc && dc.artboard ? dc.artboard : asked && s.size && s.size.from === 'page css' &&
    (s.size.width !== asked.width || s.size.height !== asked.height) ? { width: s.size.width, height: s.size.height } : null;
  const fit = art ? fitArtboard(art, asked) : null;
  const head = fonts.done.map((f) => `<link rel="stylesheet" href="${f.href}">`).join('') +
    (fitCss(fit) ? `<style data-st-adopt-fit>${fitCss(fit)}</style>` : '');
  const pageHtml = fonts.done.length ? dropFontLinks(html, fonts.done.map((f) => f.url)) : html;
  const writeIndex = (conf) => fs.writeFileSync(path.join(dest, 'index.html'), wrapHtml(pageHtml, baseHref, conf, head));
  const guess = {
    size: (fit ? { width: fit.width, height: fit.height } : null) || asked || (drv.size ? { width: drv.size.width, height: drv.size.height } : null) || (s.size ? { width: s.size.width, height: s.size.height } : null),
    fps: Number(a.fps) || s.fps || drv.fps || null,
    duration: Number(a.duration) || null,
  };
  const w0 = guess.size ? guess.size.width : 1920, h0 = guess.size ? guess.size.height : 1080;
  writeJSON(path.join(dest, 'showtime.json'), { ...(readJSON(path.join(dest, 'showtime.json')) || {}), width: w0, height: h0, fps: guess.fps || 30, duration: guess.duration || 1 });
  writeIndex({ seek: null, ready, setup, probe: true });
  // no length yet: let the stage infer it (clips, finite CSS animations); only if it cannot, probe with a placeholder
  let pr = null;
  if (!findings.errors.length) {
    const base = { width: w0, height: h0, fps: guess.fps || 30 };
    if (!guess.duration) {
      writeJSON(path.join(dest, 'showtime.json'), { ...(readJSON(path.join(dest, 'showtime.json')) || {}), duration: undefined });
      pr = await probePage(dest, base, new Findings(), entry, true);
    }
    if (!pr) pr = await probePage(dest, { ...base, duration: guess.duration || 1 }, findings, entry);
  }

  // decide
  const nums = pr ? pr.probe && pr.probe.numbers || {} : {};
  const pfns = pr && pr.probe ? pr.probe.functions.map((f) => f.name) : s.fns.map((f) => f.name);
  if (pr && seek && !pfns.includes(seek) && !a.seek && !dc) {
    const alt = pfns.find((n) => TIME_FNS.includes(n) && n !== 'update' && n !== 'tick' && n !== 'frame');
    if (alt) { why = `\`${seek}\` is not a global in the page; \`${alt}\` is`; seek = alt; }
  }
  if (pr && !seek && kind === 'page' && pfns.length && !a.mode && !dc) {
    seek = pfns.slice().sort((x, y) => TIME_FNS.indexOf(x.split('.').pop()) - TIME_FNS.indexOf(y.split('.').pop()))[0];
    why = 'the page defines it';
  }
  if (pr && seek && !pfns.includes(seek)) {
    findings.add('error', 'no_time_function', `the page has no global function \`${seek}\``,
      pfns.length ? `it defines ${pfns.join(', ')}` : 'functions inside a module script or a closure are not visible to the renderer',
      pfns.length ? `pass --seek ${pfns[0]}` : 'expose it on window (window.seek = seek) in a copy, or adopt as --mode clock if it animates with CSS');
  }
  const DURS = ['DURATION', 'TOTAL_DURATION', 'duration', 'VIDEO_DURATION', 'totalDuration', 'TOTAL', 'LENGTH', 'DUR', '__duration', 'TOTAL_TIME', 'totalTime', 'END', 'T_END'];
  let duration = guess.duration, durFrom = duration ? '--duration' : '';
  if (!duration) {
    const k = DURS.find((n) => Number(nums[n]) > 0) || Object.keys(nums).find((n) => /\.(duration|DURATION|length)$/.test(n) && nums[n] > 0);
    if (k) { duration = Number(nums[k]); durFrom = `page \`${k}\``; }
  }
  if (!duration) {
    const k = Object.keys(s.durations)[0];
    if (k) { duration = s.durations[k]; durFrom = `page \`${k}\``; }
  }
  if (!duration && drv.duration) { duration = drv.duration; durFrom = `${path.basename(drv.files[0])} DURATION`; }
  // a requestAnimationFrame clock (performance.now): its loop `% 13` and clamp `Math.min(t, 12)`
  let loop = null;
  const jsClock = (text) => {
    const jc = jsClockLength(text);
    if (jc) { duration = jc.seconds; durFrom = `inferred: ${jc.how}`; if (jc.loop) loop = { period: jc.seconds, how: jc.how }; }
  };
  if (!duration && !seek && dc) jsClock(dc.logic);
  // CSS/Web Animations that repeat forever: one period, when all of them are back at the start
  if (!duration && !seek && pr && pr.probe) {
    const cl = cssLoopLength(pr.probe.timing);
    if (cl) { duration = cl.seconds; durFrom = `inferred: ${cl.how}`; loop = { period: cl.seconds, how: cl.how, aligned: cl.loop }; }
  }
  if (!duration && pr && pr.info && pr.info.durationSource && pr.info.durationSource !== 'config' && pr.info.duration > 0) {
    duration = pr.info.duration; durFrom = pr.info.durationSource;
  }
  if (!duration && !seek && pr && pr.probe) {
    // finite animations of a page that builds itself on its first frame (the stage read the length before)
    const end = (pr.probe.timing || []).filter((x) => Number.isFinite(x.iterations)).reduce((m, x) => Math.max(m, x.delay + x.duration * x.iterations), 0);
    if (end > 0) { duration = Math.round(end) / 1000; durFrom = 'css animations (their end)'; }
  }
  if (!duration && !seek && !dc) jsClock(inlineScripts(html).map((x) => x.text).join('\n;\n'));
  if (duration && a.duration && !seek && !loop) {
    // --duration wins; a loop the page has is still worth checking at that length
    const cl = pr && pr.probe ? cssLoopLength(pr.probe.timing) : null;
    if (cl && Math.abs(cl.seconds - duration) < 1e-6) loop = { period: cl.seconds, how: cl.how, aligned: cl.loop };
  }
  if (duration && unit === 'ms' && duration > 600 && /page|DURATION/.test(durFrom)) { duration /= 1000; durFrom += ' (ms)'; }
  if (!duration && !findings.errors.length) {
    findings.add('error', 'no_duration', 'the video length is not stated anywhere adopt can read',
      'no DURATION-like global in the page, none in its driver, and no finite CSS animation', 'pass --duration <seconds>');
  }
  let fps = guess.fps || Number(nums.FPS || nums.fps || nums.FRAME_RATE || nums.frameRate) || 30;
  let size = guess.size, sizeFrom = fit ? `${dc && dc.artboard ? 'Claude Design artboard' : 'the page\'s own size'} ${art.width}x${art.height}` +
    `${a.size ? ' fitted to --size' : ''}, scaled ${fit.zoom}x with CSS zoom (laid out again: text stays sharp)` :
    a.size ? '--size' : drv.size ? `${drv.size.from} viewport` : s.size ? s.size.from : '';
  if (!size && pr && pr.probe) {
    const cv = pr.probe.canvases.find((x) => x.width >= 320 && x.height >= 240 && Math.abs(x.width / x.height - x.cssW / Math.max(1, x.cssH)) < 0.02) || null;
    const nW = Number(nums.WIDTH || nums.W || nums.VIDEO_WIDTH), nH = Number(nums.HEIGHT || nums.H || nums.VIDEO_HEIGHT);
    if (nW >= 320 && nH >= 240) { size = { width: nW, height: nH }; sizeFrom = 'page W/H'; }
    else if (cv) { size = { width: cv.width, height: cv.height }; sizeFrom = 'canvas'; }
  }
  if (!size) { size = { width: 1920, height: 1080 }; sizeFrom = 'default (nothing in the page or its driver says otherwise)'; }
  size = { width: even(size.width), height: even(size.height) };

  const conf = { seek: kind === 'page' ? seek : null, unit, ready, setup };
  writeIndex(conf);
  const contract = seek ? `page: ${seek}(${unit === 's' ? 't' : unit === 'ms' ? 'ms' : 'frame'})` : 'clock: CSS/Web Animations/requestAnimationFrame on the virtual clock';
  if (!seek && kind === 'page' && !a.mode) {
    const anim = pr && pr.probe ? pr.probe.animations : 0;
    if (!anim && !s.clock.css && !s.clock.raf && !s.clock.waapi) {
      findings.add('error', 'no_contract', `${entry} has no time function and no animations`,
        'adopt needs a function of time (seek/render/draw(t)) or CSS/Web Animations/requestAnimationFrame it can drive',
        'pass --seek <name> if the function has another name; a static page is a still, not a video');
    } else if (s.clock.timers && !s.clock.css && !s.clock.waapi) {
      findings.add('warning', 'timers', `${entry} animates with setTimeout/setInterval`,
        'timers run in real time, so frames depend on how fast the machine is', 'drive the animation from a time function (window.seek = t => ...) in a copy; check reports it as `timers`');
    }
  }
  if (s.clock.gsap && !seek) findings.add('warning', 'gsap_clock', 'the page uses GSAP on its own ticker', 'GSAP tweens only follow the virtual clock when paused and seeked', 'expose a seek function (window.seek = t => tl.seek(t)) or register it with ST.gsap in a copy');

  const res = {
    kind: seek ? 'page' : 'clock', contract, width: size.width, height: size.height, fps, duration: duration || 1,
    title: htmlTitle(html), background: null, loop, fonts: fonts.report,
    ...(dc ? { made: 'Claude Design export', design: { artboard: dc.artboard, zoom: fit ? fit.zoom : 1, offset: fit && (fit.x || fit.y) ? { x: fit.x, y: fit.y } : null } } : {}),
    sources: { time_function: seek ? `${seek} (${why || '--seek'})` : null, unit, size: sizeFrom, duration: durFrom, fps: guess.fps ? (a.fps ? '--fps' : 'page/driver') : 'default 30', ready, setup: setup ? a.setup || 'kept' : null, drivers: drv.files },
    options: { mode: a.mode, seek: a.seek, unit: a.unit, ready: a.ready, duration: a.duration, fps: a.fps, size: a.size, setup: !!setup,
      ...(a['allow-license'] ? { allow_license: true } : {}) },
  };
  // sound the driver or a build script muxed next to the page
  // sound the driver muxed, or a build/audio script next to the page wrote (audio.mjs -> sting.wav)
  const sib = ctx.files.filter((f) => path.posix.dirname(f) === path.posix.dirname(entry) && /\.(mjs|cjs|js|py|sh|bat|ps1)$/i.test(f))
    .flatMap((f) => audioRefs(readText(path.join(ctx.root, ...f.split('/')))));
  const aud = audioFor(ctx, [...drv.audio, ...audioRefs(scanText), ...sib]);
  if (aud.length) Object.assign(res, audioConfig(aud));
  // final probe: determinism on the real settings
  writeJSON(path.join(dest, 'showtime.json'), { ...(readJSON(path.join(dest, 'showtime.json')) || {}), width: res.width, height: res.height, fps: res.fps, duration: res.duration });
  if (!findings.errors.length) res.determinism = await determinismPage(dest, res, findings);
  return res;
}

/**
 * Copy the page's Google Fonts into <project>/fonts/ (the files the link serves, with their licenses) and
 * say how to link them. Offline: a warning with the command to run later; the page keeps its link.
 * -> {done: [{url, href}], report: [{url, css, families} | {url, error}]}
 */
async function localizeFonts(ctx, html) {
  const links = googleFontLinks(html);
  const out = { done: [], report: [] };
  if (!links.length) return out;
  const dir = path.join(ctx.dest, 'fonts');
  for (let i = 0; i < links.length; i++) {
    const name = links.length > 1 ? `fonts-${i + 1}.css` : 'fonts.css';
    info(c.dim(`  copying the Google Fonts it links into ${rel(dir)} ...`));
    const r = await runPyCli(['assets', 'font', '--css', links[i].url, '--copy-to', dir, '--css-name', name, '--json',
      ...(ctx.a['allow-license'] ? ['--allow-license'] : [])], { timeout: 5 * 60 * 1000 });
    let m = null;
    try { m = r.code === 0 ? JSON.parse(r.stdout.slice(r.stdout.indexOf('{'))) : null; } catch { /* not json */ }
    if (m && m.css) {
      out.done.push({ url: links[i].url, href: `/fonts/${m.css}` });
      out.report.push({ url: links[i].url, css: `fonts/${m.css}`, families: (m.families || []).map((f) => ({ family: f.family, license: f.license, files: f.files.length })) });
    } else {
      const { code, why } = fontFetchFailure(r.stderr, r.code);
      out.report.push({ url: links[i].url, error: why });
      const fallback = 'renders block the network, so the text falls back to a system font until the fonts are in the project';
      if (code === 'fonts_license') {
        ctx.findings.add('warning', 'fonts_license', `the Google Fonts the page links were not copied: ${why}`,
          'adopt copies OFL/Apache/MIT/UFL fonts only; ' + fallback,
          `use a font with one of those licenses in the page, or, if you may use this one: showtime adopt ${rel(ctx.dest)} --refresh --allow-license`);
      } else if (code === 'fonts_offline') {
        ctx.findings.add('warning', 'fonts_offline', `could not copy the Google Fonts the page links (${why})`, fallback,
          `when you are online, run: showtime adopt ${rel(ctx.dest)} --refresh`);
      } else {
        ctx.findings.add('warning', 'fonts_failed', `could not copy the Google Fonts the page links (${why})`, fallback,
          'download the fonts into the folder and link them from the page, or use installed ones (`showtime assets font <name>`)');
      }
    }
  }
  return out;
}

function stripDefs(text, name) {
  return text.replace(new RegExp(`(window\\.)?${name}\\s*=\\s*(function|\\(|[\\w$]+\\s*=>)`, 'g'), '').replace(new RegExp(`function\\s+${name}\\s*\\(`, 'g'), '');
}

function htmlTitle(html) { const m = /<title>([^<]{1,120})<\/title>/i.exec(html); return m ? m[1].trim() : null; }

function scanDrivers(root, files) {
  const out = [];
  for (const r of files) {
    if (!/\.(mjs|cjs|js|ts|py)$/i.test(r)) continue;
    const d = scanDriver(readText(path.join(root, ...r.split('/'))), r);
    if (d) out.push(d);
  }
  return out;
}

function mergeDrivers(ds) {
  const out = { files: ds.map((d) => d.file), calls: [], fps: null, duration: null, size: null, setup: [], audio: [], data: [], ready: null };
  for (const d of ds) {
    out.calls.push(...d.calls);
    out.fps = out.fps || d.fps;
    out.duration = out.duration || d.duration;
    out.size = out.size || d.size;
    out.ready = out.ready || d.ready;
    for (const x of d.setup) out.setup.push({ ...x, file: d.file });
    out.audio.push(...d.audio.map((f) => path.posix.join(path.posix.dirname(d.file), f)));
    for (const f of d.data || []) out.data.push({ name: f, dir: path.posix.dirname(d.file) });
  }
  return out;
}

/** index.html around the original page: <base> into the copy, the stage runtime and the bridge first. */
export function wrapHtml(html, baseHref, conf, extraHead = '') {
  const head = `<base href="${baseHref.replace(/"/g, '&quot;')}">` +
    '<script src="/_st/stage.js"></script>' +
    `<script>window.__ST_ADOPT__=${JSON.stringify(conf).replace(/</g, '\\u003c')};</script>` +
    '<script src="/_st/adopt.js"></script>' + extraHead;
  const note = '<!-- written by `showtime adopt`: the page below is a copy of the original, which is unchanged. -->\n';
  if (/<head\b[^>]*>/i.test(html)) return note + html.replace(/<head\b[^>]*>/i, (m) => `${m}${head}`);
  if (/<html\b[^>]*>/i.test(html)) return note + html.replace(/<html\b[^>]*>/i, (m) => `${m}<head>${head}</head>`);
  if (/^\s*<!doctype[^>]*>/i.test(html)) return note + html.replace(/^\s*<!doctype[^>]*>/i, (m) => `${m}<head>${head}</head>`);
  return `${note}<!doctype html><head>${head}</head>${html}`;
}

async function probePage(dest, cfg, findings, entry, quietNoDuration = false) {
  let srv = null, b = null, sess = null;
  try {
    srv = await startServer({ root: dest, port: 0 });
    b = await openBrowser({});
    sess = await openStage(b.browser, { url: srv.url, page: 'index.html', config: cfg, followPageSize: false, readyTimeout: 60000 });
    const probe = await sess.page.evaluate(() => (window.__stAdoptProbe ? window.__stAdoptProbe() : null));
    const errs = sess.log.errors.slice(0, 3);
    for (const e of errs) findings.add('warning', 'page_error', `the page threw while loading: ${e.message}`, '', 'showtime check lists every page error with its time');
    return { probe, info: sess.info };
  } catch (e) {
    if (quietNoDuration) return null;
    findings.add('error', 'page_failed', `${entry} did not load: ${String(e.message || e).split('\n')[0]}`,
      e.hint || '', 'run the page in a browser to see the error; adopt passes the page through unchanged');
    return null;
  } finally {
    if (sess) await sess.close();
    if (b) await b.browser.close().catch(() => {});
    if (srv) await srv.close();
  }
}

/** Seek four frames in order, then in reverse (each reached after other frames) and after 150 ms: same pixels? */
async function determinismPage(dest, res, findings) {
  let srv = null, b = null, sess = null, lab = null;
  const n = Math.max(1, Math.round(res.duration * res.fps));
  const ks = [...new Set([0, Math.floor(n * 0.31), Math.floor(n * 0.62), n - 1].map((k) => Math.max(0, Math.min(n - 1, k))))];
  try {
    srv = await startServer({ root: dest, port: 0 });
    b = await openBrowser({});
    const cfg = readJSON(path.join(dest, 'showtime.json'));
    // a loop is also seeked one frame past its end (frame n must be frame 0 again)
    sess = await openStage(b.browser, { url: srv.url, page: 'index.html', config: res.loop ? { ...cfg, duration: cfg.duration + 2 / res.fps } : cfg, followPageSize: false });
    const shot = async (k) => { await sess.seek(k / res.fps); return sess.shot({ format: 'png' }); };
    const p1 = [];
    for (const k of ks) p1.push(await shot(k));
    const p2 = new Array(ks.length);
    for (let i = ks.length - 1; i >= 0; i--) p2[i] = await shot(ks[i]);
    await new Promise((r) => setTimeout(r, 150));
    const again = await sess.shot({ format: 'png' });   // still on ks[0]: nothing may move in real time
    lab = await openLab(b.browser, srv.url);
    const frames = [];
    let verdict = 'deterministic';
    for (let i = 0; i < ks.length; i++) {
      const same = sha(p1[i]) === sha(p2[i]);
      const f = { frame: ks[i], t: +(ks[i] / res.fps).toFixed(3), sha256: sha(p1[i]).slice(0, 16), same };
      if (!same) {
        const d = await lab.diff(p1[i], p2[i]);
        f.changedPct = +d.changedPct.toFixed(3); f.solidPct = +d.solidPct.toFixed(3);
        if (d.solidPct > 0.01) verdict = 'differs'; else if (verdict === 'deterministic') verdict = 'raster noise';
      }
      frames.push(f);
    }
    let stable = sha(again) === sha(p2[0]);
    if (!stable) {
      // a late paint settles once; real-time motion keeps changing: look once more before calling it
      await new Promise((r) => setTimeout(r, 150));
      const again2 = await sess.shot({ format: 'png' });
      if (sha(again2) === sha(again)) stable = true;
    }
    if (!stable) {
      const d = await lab.diff(p2[0], again);
      if (d.solidPct > 0.01) verdict = 'differs';
      frames.push({ frame: ks[0], t: 0, note: 'captured again after 150 ms of real time', same: false, solidPct: +d.solidPct.toFixed(3) });
    }
    if (res.loop) {
      // the seam: the frame after the last is where the next play of the loop starts
      const after = await shot(n);
      const same = sha(after) === sha(p1[0]);
      const d = same ? { changedPct: 0, solidPct: 0 } : await lab.diff(p1[0], after);
      res.loop.seam = { t: +(n / res.fps).toFixed(3), against: 0, same, changedPct: +d.changedPct.toFixed(3), solidPct: +d.solidPct.toFixed(3) };
      res.loop.seamless = same || d.solidPct <= 0.01;
      if (!res.loop.seamless) {
        findings.add('warning', 'loop_seam', `the frame after the last (${res.loop.seam.t} s) is not frame 0 again (${res.loop.seam.changedPct}% of the picture differs)`,
          'played on repeat, the video jumps at the seam', 'pass --duration <the length after which every animation is back at its start>');
      }
    }
    if (verdict === 'differs') {
      const bad = frames.filter((f) => !f.same).map((f) => `${f.t}s`).join(', ');
      findings.add('error', 'nondeterministic', `frames differ when reached in another order or after a pause (${bad})`,
        'the page keeps state between frames (x += v, a counter) or animates in real time (timers, Date without the clock)',
        'compute every value from t in the time function; `showtime check` names the frames and the timers');
    }
    return { verdict, method: 'each frame captured twice: in order, then in reverse after other frames; frame 0 again after 150 ms', frames };
  } catch (e) {
    findings.add('error', 'seek_failed', `seeking the page failed: ${String(e.message || e).split('\n')[0]}`, '', 'run `showtime check <project>` for the page errors');
    return { verdict: 'not measured', error: String(e.message || e).split('\n')[0] };
  } finally {
    if (lab) await lab.close();
    if (sess) await sess.close();
    if (b) await b.browser.close().catch(() => {});
    if (srv) await srv.close();
  }
}

// ------------------------------------------------------------------------------------------- audio
/** Audio files (relative to the adopted root) that exist in the copy. */
function audioFor(ctx, refs) {
  const out = [];
  const entryDir = path.posix.dirname(ctx.entry);
  for (const r of refs) {
    for (const cand of [r, path.posix.join(entryDir, r)]) {
      const n = path.posix.normalize(cand);
      if (n.startsWith('..') || !AUDIO_EXT.test(n)) continue;
      if (fs.existsSync(path.join(ctx.srcDir, ...n.split('/'))) && !out.includes(n)) { out.push(n); break; }
    }
  }
  return out;
}

function audioConfig(files) {
  const kindOf = (f) => (/(^|[\/_-])(vo|voice|narr|narration|speech|voiceover)/i.test(f) ? 'voice' : /sfx|whoosh|click|hit/i.test(f) ? 'sfx' : 'music');
  // several voice clips a script placed itself (final_1.wav ...) need their times: only a full mix file is safe to add
  const full = files.filter((f) => !/_\d+\.\w+$/.test(f) || files.length === 1);
  const tracks = full.map((f) => ({ id: path.posix.basename(f).replace(/\.\w+$/, ''), kind: kindOf(f), file: `src/${f}`, start: 0, level: 'raw' }));
  if (!tracks.length) return { audioFiles: files };
  return {
    audio: 'audio/mix.json', audioFiles: files,
    mix: { _comment: 'Sound the adopted video already had (its own files, at their own levels). Add music, effects or a voice-over as more tracks: references/audio.md.', sample_rate: 48000, tracks, master: { lufs: -14, true_peak: -1 } },
  };
}

// ------------------------------------------------------------------------------------------ python
async function adoptPython(ctx, kind) {
  const { a, entry, dest, srcDir, workDir, findings } = ctx;
  const script = path.join(srcDir, ...entry.split('/'));
  const py = findPython(ctx.root, path.dirname(ctx.entryAbs), a.python);
  const env = scriptEnv(!!a['allow-network']);
  const log = path.join(workDir, 'python.log');
  fs.writeFileSync(log, `interpreter: ${py.exe} (${py.from})\nscript: ${script}\n`);
  const insp = await runProc(py.exe, [HARNESS(), 'inspect', script], { env, cwd: path.dirname(script), timeout: 10 * 60 * 1000 });
  fs.appendFileSync(log, `\n$ inspect (exit ${insp.code})\n${insp.stderr.slice(-4000)}\n`);
  if (insp.code === 127 || /ENOENT/.test(insp.stderr)) throw new UserError(`no Python to run ${entry} (${py.exe})`, 'pass --python <interpreter> (the one you ran the script with)');
  let I = null;
  try { I = JSON.parse(insp.stdout.trim().split('\n').pop()); } catch {
    throw new UserError(`could not inspect ${entry}: ${lastLine(insp.stderr) || `exit ${insp.code}`}`, `see ${rel(log)}; run the script once yourself with ${py.exe}`);
  }
  if (I.static && I.static.syntax_error) throw new UserError(`${entry} does not parse: ${I.static.syntax_error}`, 'fix the syntax (adopt runs the script as it is)');
  if (I.import_error) {
    const miss = /No module named '([\w.]+)'/.exec(I.import_error);
    throw new UserError(`${entry} failed on import: ${I.import_error}`,
      miss ? `install ${miss[1].split('.')[0]} for ${py.exe}, or pass --python <the interpreter you ran it with>` : `see ${rel(log)}; the script's top-level code must run on this machine (fonts, files it opens)`);
  }
  const st = I.static || {};
  const nums = I.numbers || {};
  const ff = (st.ffmpeg || [])[0] || [];
  const ffArg = (flag) => { const i = ff.indexOf(flag); return i >= 0 ? ff[i + 1] : null; };
  const pick = (names) => { for (const n of names) if (nums[n] !== undefined) return [n, nums[n]]; return [null, null]; };
  let mode = kind === 'capture' ? 'capture' : (I.fn && a.mode !== 'capture' ? 'frames' : 'capture');
  let fnName = a.fn || (I.fn && I.fn.name) || null;
  let unit = a.unit || (I.fn && I.fn.unit) || 's';
  if (a.fn && !(I.static.functions || []).some((f) => f.name === a.fn)) throw new UserError(`${entry} has no top-level function ${a.fn}`, `its functions: ${(I.static.functions || []).map((f) => f.name).join(', ')}`);
  if (a.fn && mode !== 'capture') mode = 'frames';
  if (mode === 'frames' && !I.import_safe) mode = 'capture';
  const why = I.fn ? `returns ${I.fn.returns}${I.fn.size ? ` ${I.fn.size.join('x')}` : ''}, ${I.fn.ms} ms for frame 0` : '';
  if (kind === 'python' && mode === 'capture') {
    findings.add('info', 'capture_mode', `${entry} has no frame function adopt can call (${I.import_safe ? 'none of its functions takes only t or a frame number and returns an image' : 'it has no `if __name__ == "__main__":` guard, so importing it would run it'})`,
      'its own main() runs once on the copy and its video is ingested', 'for per-frame renders (render --from/--to regenerating only those frames, a per-frame determinism check) expose def render(t) -> image and a main guard in a copy');
  }

  let width, height, fps, duration, sizeFrom, durFrom, fpsFrom, determinism = null, audioFiles = [], mix = null, audio = null;
  const media = path.join(dest, 'media');
  fs.mkdirSync(media, { recursive: true });
  const picture = path.join(media, 'frames.webm');
  if (mode === 'frames') {
    // size: the frame itself, else W/H constants, else the ffmpeg -s argument
    const [, sz] = pick(['SIZE', 'RES', 'RESOLUTION', 'FRAME_SIZE']);
    const [wn, wv] = pick(['W', 'WIDTH', 'VIDEO_W', 'VIDEO_WIDTH', 'OUT_W', 'FRAME_W', 'w']);
    const [, hv] = pick(['H', 'HEIGHT', 'VIDEO_H', 'VIDEO_HEIGHT', 'OUT_H', 'FRAME_H', 'h']);
    if (a.size) { const s2 = parseSize(a.size); width = s2.width; height = s2.height; sizeFrom = '--size'; }
    else if (I.fn.size) { [width, height] = I.fn.size; sizeFrom = 'frame 0'; }
    else if (wv && hv) { width = wv; height = hv; sizeFrom = `${wn}/H`; }
    else if (sz) { [width, height] = sz; sizeFrom = 'SIZE'; }
    else if (ffArg('-s')) { [width, height] = ffArg('-s').split('x').map(Number); sizeFrom = 'ffmpeg -s'; }
    if (!(width > 0 && height > 0)) throw new UserError(`cannot tell the frame size of ${entry}`, 'pass --size WIDTHxHEIGHT');
    if (I.fn.nbytes && I.fn.nbytes !== width * height * 3 && I.fn.nbytes !== width * height * 4) {
      throw new UserError(`${fnName}(0) returned ${I.fn.nbytes} bytes, which is not ${width}x${height} RGB`, 'pass --size WIDTHxHEIGHT');
    }
    const [fpn, fpv] = pick(['FPS', 'fps', 'FRAME_RATE', 'FRAMERATE', 'RATE']);
    fps = Number(a.fps) || fpv || Number(ffArg('-r') || ffArg('-framerate')) || 30;
    fpsFrom = a.fps ? '--fps' : fpv ? fpn : ffArg('-r') ? 'ffmpeg -r' : 'default 30';
    const [dn, dv] = pick(['DURATION', 'DUR', 'TOTAL', 'TOTAL_DURATION', 'LENGTH', 'T_TOTAL', 'TOTAL_TIME', 'VIDEO_DURATION', 'duration', 'END', 'T_END']);
    const [fn2, fv2] = pick(['N_FRAMES', 'NFRAMES', 'FRAMES', 'TOTAL_FRAMES', 'NUM_FRAMES', 'FRAME_COUNT']);
    duration = Number(a.duration) || dv || (fv2 ? fv2 / fps : null);
    durFrom = a.duration ? '--duration' : dv ? dn : fv2 ? `${fn2}/fps` : '';
    if (!duration) throw new UserError(`cannot tell how long ${entry} runs`, 'pass --duration <seconds> (no DURATION/TOTAL/N_FRAMES in the script)');
    width = even(width); height = even(height);
    const n = Math.round(duration * fps);
    // determinism: the same frames twice, in two orders
    const ks = [...new Set([0, Math.floor(n * 0.33), Math.floor(n * 0.66), n - 1].map((k) => Math.max(0, Math.min(n - 1, k))))];
    const hr = await runProc(py.exe, [HARNESS(), 'hash', script, '--fn', fnName, '--unit', unit, '--fps', String(fps), '--size', `${width}x${height}`, '--frames', ks.join(',')],
      { env, cwd: path.dirname(script), timeout: 10 * 60 * 1000 });
    fs.appendFileSync(log, `\n$ hash (exit ${hr.code})\n${hr.stderr.slice(-4000)}\n`);
    try {
      const h = JSON.parse(hr.stdout.trim().split('\n').pop());
      const frames = h.frames.map((k, i) => ({ frame: k, t: +(k / fps).toFixed(3), sha256: h.pass1[i].slice(0, 16), same: h.pass1[i] === h.pass2[i] }));
      determinism = { verdict: frames.every((f) => f.same) ? 'deterministic' : 'differs', method: `${fnName}() called twice per frame: in order, then in reverse after other frames (same process)`, frames };
      if (determinism.verdict === 'differs') {
        findings.add('error', 'nondeterministic', `${fnName}() draws different pixels for the same frame (${frames.filter((f) => !f.same).map((f) => `${f.t}s`).join(', ')})`,
          'it keeps state between calls or uses unseeded randomness', 'compute everything from t (seed random.Random(frame) per frame); re-rendering a range would not match the rest');
      }
    } catch {
      throw new UserError(`${fnName}() failed: ${lastLine(hr.stderr) || `exit ${hr.code}`}`, `see ${rel(log)}`);
    }
    // frames -> an intermediate VP9 the page plays frame-exactly
    const workers = Math.max(1, Math.min(Number(a.workers) || Math.min(8, cpuCount() - 1), 32));
    info(c.dim(`  drawing ${n} frames with ${fnName}() (${workers} process${workers > 1 ? 'es' : ''})...`));
    const tf = Date.now();
    await pipeFrames(py.exe, [HARNESS(), 'frames', script, '--fn', fnName, '--unit', unit, '--fps', String(fps), '--size', `${width}x${height}`,
      '--from', '0', '--to', String(n), '--workers', String(workers)], { env, cwd: path.dirname(script), width, height, fps, out: picture, log, n,
      timeout: (Number(a.timeout) || 30) * 60 * 1000 });
    info(c.dim(`  frames done in ${fmtDuration(Date.now() - tf)}`));
    audioFiles = audioFor(ctx, audioRefs(readText(ctx.entryAbs)));
    if (audioFiles.length) ({ mix, audio } = audioConfig(audioFiles));
  } else {
    // capture: run the script's own main on the copy, ingest what it wrote
    const before = snapshotMedia(srcDir);
    const tr = Date.now();
    info(c.dim(`  running ${entry} (its own main) on the copy with ${path.basename(py.exe)}...`));
    const r = await runProc(py.exe, [HARNESS(), 'run', script], { env, cwd: path.dirname(script), timeout: (Number(a.timeout) || 30) * 60 * 1000 });
    fs.appendFileSync(log, `\n$ run (exit ${r.code}, ${Math.round((Date.now() - tr) / 1000)} s)\n--- stdout\n${r.stdout.slice(-6000)}\n--- stderr\n${r.stderr.slice(-8000)}\n`);
    if (r.code !== 0) {
      throw new UserError(`${entry} failed (exit ${r.code}): ${lastLine(r.stderr) || lastLine(r.stdout)}`,
        /network access is blocked/.test(r.stderr) ? 'it tried to use the network: pass --allow-network if that is intended' : `full output in ${rel(log)}`);
    }
    const made = newMedia(srcDir, before);
    const printed = [...(r.stdout + '\n' + r.stderr).matchAll(/(?:wrote|saved|written|->)\s+([^\s'"]+\.(?:mp4|mov|mkv|webm|m4v))/gi)].map((m) => path.resolve(path.dirname(script), m[1]));
    const vids = made.filter((f) => VIDEO_EXT.test(f)).sort((x, y) => fs.statSync(y).size - fs.statSync(x).size);
    const vid = printed.find((p) => vids.includes(p)) || vids[0];
    if (!vid) throw new UserError(`${entry} ran but wrote no video file`, `adopt looks for a new .mp4/.mov/.mkv/.webm in the copy; see ${rel(log)}`);
    const pv = await probe(vid);
    if (!pv.video) throw new UserError(`${rel(vid)} has no video stream`);
    width = even(pv.video.width); height = even(pv.video.height); fps = Math.round((pv.video.fps || 30) * 1000) / 1000;
    duration = Math.round((pv.video.duration || pv.duration) * 1000) / 1000;
    sizeFrom = durFrom = fpsFrom = `the video it wrote (${path.relative(srcDir, vid)})`;
    await ffmpeg(['-i', vid, '-an', ...vp9Args(fps), picture], { timeout: Math.max(600000, duration * 20000) });
    if (pv.audio) {
      const wav = path.join(media, 'original-audio.wav');
      await ffmpeg(['-i', vid, '-vn', '-c:a', 'pcm_s16le', '-ar', '48000', '-ac', '2', wav]);
      audioFiles = [path.relative(dest, wav)];
      mix = { _comment: 'The sound track of the video the adopted script wrote, at its own level. Add music, effects or a voice-over as more tracks: references/audio.md.', sample_rate: 48000, tracks: [{ id: 'original', kind: 'music', file: 'media/original-audio.wav', start: 0, level: 'raw' }], master: { lufs: -14, true_peak: -1 } };
      audio = 'audio/mix.json';
    }
    const extras = made.filter((f) => /\.(srt|vtt|ass)$/i.test(f));
    if (extras.length) findings.add('info', 'script_captions', `the script also wrote ${extras.map((f) => path.relative(srcDir, f)).join(', ')}`, '', 'showtime captions can make captions from the audio too (showtime captions --help)');
    determinism = { verdict: 'not measured', method: 'no frame function: the script ran once as a whole (adopt with a render(t) function for a per-frame check)' };
    unit = null; fnName = null;
  }
  const index = `<!doctype html>
<!-- written by \`showtime adopt\`: frames drawn by ${entry.replace(/--!?>/g, '')} (${mode === 'frames' ? `${fnName}()` : 'its own main'}), played frame-exactly -->
<html><head><meta charset="utf-8"><title>${escapeHtml(path.basename(entry))}</title>
<script src="/_st/stage.js"></script>
<style>html,body{margin:0;background:#000;overflow:hidden}#frames,#frames-still{position:absolute;inset:0;width:100%;height:100%;object-fit:contain}</style>
</head><body>
<video id="frames" src="media/frames.webm" data-start="0" muted playsinline preload="auto"></video>
<!-- renders draw each frame here (data-st-video): a paused video's own frame can reach the capture late -->
<canvas id="frames-still" data-st-video="frames"></canvas>
</body></html>
`;
  fs.writeFileSync(path.join(dest, 'index.html'), index);
  return {
    kind: mode === 'frames' ? 'python' : 'capture',
    contract: mode === 'frames' ? `python: ${fnName}(${unit === 'frame' ? 'frame' : 't'}) -> ${I.fn.returns}` : 'python: its own main() writes a video (captured)',
    width, height, fps, duration, title: path.basename(entry).replace(/\.py$/, ''), background: '#000000',
    sources: { frame_function: fnName ? `${fnName} (${why})` : null, unit, size: sizeFrom, duration: durFrom, fps: fpsFrom, python: `${py.exe} (${py.from})`, network: a['allow-network'] ? 'allowed' : 'blocked' },
    options: { mode: a.mode, fn: a.fn, unit: a.unit, duration: a.duration, fps: a.fps, size: a.size, python: a.python, workers: a.workers, timeout: a.timeout },
    determinism, audioFiles, mix, audio,
  };
}

function escapeHtml(s) { return String(s).replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch])); }
function lastLine(s) { return String(s || '').trim().split('\n').filter((l) => l.trim()).pop() || ''; }

function vp9Args(fps) {
  // near-lossless and quick to seek: every frame the renderer asks for decodes from a keyframe <= 0.5 s back
  if (!hasEncoder('libvpx-vp9')) throw new UserError('this ffmpeg has no VP9 encoder (libvpx-vp9)', 'run `showtime setup` for showtime\'s own ffmpeg');
  const g = Math.max(1, Math.round(fps / 2));
  return ['-c:v', 'libvpx-vp9', '-pix_fmt', 'yuv420p', '-crf', '12', '-b:v', '0', '-g', String(g), '-keyint_min', String(g),
    '-deadline', 'good', '-cpu-used', '4', '-row-mt', '1', '-threads', String(Math.min(16, cpuCount())),
    '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv'];
}

/** Python harness stdout (raw RGB24) -> ffmpeg -> VP9 webm. */
function pipeFrames(pyExe, args, o) {
  const { ffmpeg: ffBin } = resolveFF();
  return new Promise((resolve, reject) => {
    const ff = spawn(ffBin, ['-hide_banner', '-nostdin', '-loglevel', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
      '-s', `${o.width}x${o.height}`, '-r', String(o.fps), '-i', '-', '-vf', 'scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int',
      ...vp9Args(o.fps), o.out], { windowsHide: true, stdio: ['pipe', 'ignore', 'pipe'] });
    const py = spawn(pyExe, args, { env: o.env, cwd: o.cwd, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let ffErr = '', pyErr = '', bytes = 0, done = false;
    const frameBytes = o.width * o.height * 3;
    let lastPct = -1;
    const timer = setTimeout(() => { pyErr += `\n(timed out after ${o.timeout / 60000} min)`; try { py.kill(); } catch { /* gone */ } }, o.timeout);
    py.stdout.on('data', (d) => {
      bytes += d.length;
      const pct = Math.floor((100 * bytes) / (frameBytes * o.n));
      if (pct >= lastPct + 10 && !process.stderr.isTTY) { lastPct = pct - (pct % 10); info(c.dim(`  frames ${Math.floor(bytes / frameBytes)}/${o.n}`)); }
      if (!ff.stdin.write(d)) { py.stdout.pause(); ff.stdin.once('drain', () => py.stdout.resume()); }
    });
    py.stdout.on('end', () => ff.stdin.end());
    py.stderr.on('data', (d) => { pyErr += d; if (pyErr.length > 2e5) pyErr = pyErr.slice(-1e5); });
    ff.stderr.on('data', (d) => { ffErr += d; });
    ff.stdin.on('error', () => {});
    let pyCode = null, ffCode = null;
    const finish = () => {
      if (done || pyCode === null || ffCode === null) return;
      done = true; clearTimeout(timer);
      fs.appendFileSync(o.log, `\n$ frames (python exit ${pyCode}, ffmpeg exit ${ffCode}, ${bytes} bytes)\n${pyErr.slice(-6000)}\n${ffErr.slice(-3000)}\n`);
      if (pyCode !== 0) return reject(new UserError(`the frame generator failed (exit ${pyCode}): ${lastLine(pyErr)}`, `see ${rel(o.log)}`));
      if (bytes !== frameBytes * o.n) return reject(new UserError(`the generator wrote ${Math.floor(bytes / frameBytes)} of ${o.n} frames`, `see ${rel(o.log)}`));
      if (ffCode !== 0) return reject(new Error(`ffmpeg failed while encoding the frames: ${lastLine(ffErr)}`));
      resolve();
    };
    py.on('close', (code) => { pyCode = code === null ? 128 : code; finish(); });
    ff.on('close', (code) => { ffCode = code === null ? 128 : code; finish(); });
    py.on('error', (e) => { pyCode = 127; pyErr += String(e.message || e); ff.stdin.end(); finish(); });
  });
}

function snapshotMedia(dir) {
  const m = new Map();
  for (const r of listFiles(dir, { max: 20000 })) {
    try { m.set(r, fs.statSync(path.join(dir, ...r.split('/'))).mtimeMs); } catch { /* gone */ }
  }
  return m;
}
function newMedia(dir, before) {
  const out = [];
  for (const r of listFiles(dir, { max: 20000 })) {
    const f = path.join(dir, ...r.split('/'));
    let mt;
    try { mt = fs.statSync(f).mtimeMs; } catch { continue; }
    if (!before.has(r) || before.get(r) !== mt) out.push(f);
  }
  return out;
}

// ------------------------------------------------------------------------------------------- check
async function runCheck(dest) {
  info(c.dim('  showtime check ...'));
  const r = await runProc(process.execPath, [path.join(HERE, 'check.mjs'), dest, '--json'], { timeout: 30 * 60 * 1000 });
  let j = null;
  try { j = JSON.parse(r.stdout.slice(r.stdout.indexOf('{'))); } catch { /* not json */ }
  if (!j) return { errors: r.code ? 1 : 0, warnings: 0, exit: r.code, note: lastLine(r.stderr) };
  const items = j.findings || j.issues || [];
  const sev = (x) => x.severity || x.level;
  return {
    exit: r.code, errors: items.filter((x) => sev(x) === 'error').length, warnings: items.filter((x) => sev(x) === 'warning').length,
    report: j.report || path.join(dest, 'work', 'check', 'report.json'), sheet: j.sheet || path.join(dest, 'work', 'check', 'sheet.jpg'),
    // one line per code (a typed terminal line is hundreds of short_text notes): count + the first one
    top: groupFindings(items.filter((x) => sev(x) === 'error' || sev(x) === 'warning')).slice(0, 6),
  };
}

function groupFindings(items) {
  const by = new Map();
  for (const x of items) {
    const k = `${x.severity || x.level} ${x.code}`;
    if (!by.has(k)) by.set(k, { first: x, n: 0 });
    by.get(k).n++;
  }
  return [...by.entries()].map(([k, { first: x, n }]) =>
    `${k}${n > 1 ? ` x${n}` : ''}${x.t !== undefined ? ` (first @${Number(x.t).toFixed(2)}s)` : ''}: ${String(x.message || x.msg || '').slice(0, 130)}`);
}

// ----------------------------------------------------------------------------------------- summary
function printSummary(r, a) {
  if (a.json) { process.stdout.write(JSON.stringify(r, null, 2) + '\n'); return; }
  const L = [];
  const bad = r.findings.filter((f) => f.level === 'error');
  L.push(`${bad.length ? c.red('adopt: not ready') : c.green('adopted')} ${r.entry} -> ${rel(r.project)}`);
  if (r.made) L.push(`  made with   ${r.made}${r.design && r.design.artboard ? ` (artboard ${r.design.artboard.width}x${r.design.artboard.height})` : ''}`);
  L.push(`  contract    ${r.contract}`);
  L.push(`  video       ${r.width}x${r.height}, ${r.fps} fps, ${r.duration} s`);
  L.push(`  size        ${r.sources.size || '?'}`);
  L.push(`  length      ${r.sources.duration || '?'}`);
  if (r.loop) L.push(`  loop        ${r.loop.seamless === undefined ? 'not measured' : r.loop.seamless ? `seamless (frame ${Math.round(r.duration * r.fps)} at ${r.loop.seam.t} s is frame 0 again)` : `not seamless (${r.loop.seam.changedPct}% differs at the seam)`}`);
  for (const f of r.fonts || []) L.push(`  fonts       ${f.css ? `${f.families.map((x) => `${x.family} (${x.license})`).join(', ')} -> ${f.css}` : `not copied: ${f.error}`}`);
  if (r.audio.length) L.push(`  sound       ${r.audio.join(', ')} -> audio/mix.json`);
  if (r.determinism) L.push(`  determinism ${r.determinism.verdict}${r.determinism.frames ? ` (${r.determinism.frames.filter((f) => f.same).length}/${r.determinism.frames.length} frames identical)` : ''}`);
  if (r.check) L.push(`  check       ${r.check.errors} error(s), ${r.check.warnings} warning(s)${r.check.sheet ? `   sheet: ${rel(r.check.sheet)}` : ''}`);
  for (const t of (r.check && r.check.top) || []) L.push(c.dim(`              ${t}`));
  for (const f of r.findings.filter((x) => x.level !== 'info')) {
    L.push(`${f.level === 'error' ? c.red('  error') : c.yellow('  warning')} ${f.what}`);
    if (f.why) L.push(`    why: ${f.why}`);
    if (f.fix) L.push(`    ${c.bold('fix:')} ${f.fix}`);
  }
  for (const f of r.findings.filter((x) => x.level === 'info')) L.push(c.dim(`  note: ${f.what}${f.fix ? ` (${f.fix})` : ''}`));
  L.push(`  report      ${rel(path.join(r.project, 'adopt.json'))}`);
  const p = rel(r.project);
  const j = r.job ? rel(r.job) : null;
  if (!bad.length) {
    L.push(c.dim('next:'));
    L.push(`  showtime snap ${p}            # contact sheet`);
    L.push(`  showtime render ${p}${j ? ` --job ${j}` : ''}${j ? `\n  showtime qa ${j}` : ''}`);
    L.push(`  showtime export html ${p}     # a shareable page; sound: ${p}/audio/mix.json`);
  }
  process.stderr.write(L.join('\n') + '\n');
  process.stdout.write(r.project + '\n');
}

runMain(main);

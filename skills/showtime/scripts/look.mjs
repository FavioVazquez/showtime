// One small composite of a project's or video's key frames for a visual check, plus a reviewer brief (lean looks).
// A "look" is one image the agent (or a disposable reviewer) opens once, answers in text, and never re-opens:
// scene frames from `showtime check`'s scene table (else evenly spaced), downscaled to --width, numbered per job.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { startServer } from './server.mjs';
import { parseCli, runMain, c, fmtTime, parseTimes, jobDir, UserError, sinceLastLooked, printSince } from './lib/cli.mjs';
import { openBrowser, openLab, parseSize } from './lib/stagehost.mjs';
import { enclosingJob, readJSON, resolveJobDir } from './lib/studio/paths.mjs';
import { VIDEO_EXT, isVideo, openSource } from './lib/frames.mjs';
import { LOOK_BUDGET, checkFreshness } from './lib/lean.mjs';

const MAX_FRAMES = 16;

const SPEC = {
  name: 'look',
  usage: 'showtime look <project | video | job> [--at 1,2.5] [--count N] [--width 1280] [--stills] [--note "what to check"] [--json]',
  summary: 'One downscaled composite of the key frames for a visual check, and a brief for a reviewer sub-agent.',
  description: [
    'Lean looks: every image an agent opens stays in its context and is paid for on every later call. A look is',
    'ONE composite (default 1280 px wide, about 1.2k tokens) of the frames that matter: the opening frame, each',
    "scene's settled frame from `showtime check`'s report (when it is current), and the last frame; without a",
    'report, evenly spaced frames. --at picks the times yourself (up to 16).',
    '',
    'Each look is numbered per job (<job>/work/look/look-N.jpg; a project outside a job: <project>/work/look/)',
    `and counted against a budget of ${LOOK_BUDGET} looks per job. It also writes look-N.md, a ready brief for a`,
    'disposable reviewer sub-agent (it opens the image, answers in text with timestamps, appends the answer to',
    'verdicts.md), and creates verdicts.md, where the verdict of every look goes (yours when there is no',
    'sub-agent). --stills adds the same frames at full size in look-N/ for a type detail pass by the reviewer.',
    '',
    'A job argument looks at its latest final (else its latest preview, else its project).',
  ].join('\n'),
  brief: true,
  options: {
    at: { help: 'comma-separated times in seconds (default: scene frames from the check report, else evenly spaced)' },
    count: { help: `evenly spaced frames when there is no scene table (default 8, at most ${MAX_FRAMES})`, metavar: 'N' },
    width: { help: 'composite width in px (default 1280; 960 is enough for a layout check)', metavar: 'PX' },
    stills: { type: 'boolean', help: 'also write the frames at full size in look-N/ (for a reviewer)' },
    note: { help: 'what the reviewer should check (goes into look-N.md)', metavar: 'TEXT' },
    output: { short: 'o', help: 'folder for the looks (default: see above)', metavar: 'DIR' },
    page: { help: 'page inside the project (default index.html)' },
    size: { help: 'project: look at this size for this run: WxH or an aspect (9:16, 1:1)', metavar: 'SIZE' },
    gpu: { help: 'auto (default) or off' },
    json: { type: 'boolean', help: 'print {look, image, frames, brief, verdicts} as JSON' },
  },
  examples: [
    'showtime look my-video                         # first look: scene frames on one 1280 px image',
    'showtime look my-video --at 0,4.2,9.5 --note "is the chart label readable?"',
    'showtime look launch                           # the job\'s latest final',
    'showtime look my-video --size 9:16 --stills    # the vertical cut, full-size frames for a reviewer',
  ],
};

const isDir = (p) => { try { return fs.statSync(p).isDirectory(); } catch { return false; } };
const isFile = (p) => { try { return fs.statSync(p).isFile(); } catch { return false; } };

/** A job folder's latest video (final, else preview), else its project folder, else null. */
export function jobTarget(job) {
  const data = readJSON(path.join(job, 'job.json'), {}) || {};
  const outs = data.outputs && typeof data.outputs === 'object' ? data.outputs : {};
  for (const kind of ['final', 'preview']) {
    const v = outs[kind];
    if (typeof v === 'string' && v) {
      const p = path.isAbsolute(v) ? v : path.join(job, v);
      if (isFile(p)) return { target: p, why: `latest ${kind}` };
    }
  }
  const vids = fs.readdirSync(job).filter((n) => VIDEO_EXT.test(n)).map((n) => path.join(job, n))
    .sort((x, y) => fs.statSync(y).mtimeMs - fs.statSync(x).mtimeMs);
  const fin = vids.find((v) => !/^(preview|draft)/i.test(path.basename(v)));
  if (fin) return { target: fin, why: 'newest final' };
  if (vids.length) return { target: vids[0], why: 'newest preview' };
  const proj = path.join(job, 'project');
  if (isFile(path.join(proj, 'showtime.json'))) return { target: proj, why: 'project' };
  return null;
}

// transition energy (runtime/transitions/catalog.json "energy"), to find the fastest window
const TX_ENERGY = { 'zoom-through': 3, 'whip-pan': 3, glitch: 3, flash: 3, 'cross-zoom': 3, 'ridged-burn': 3, 'chromatic-split': 3,
  'whip-blur': 3, 'signal-glitch': 3, push: 2, slide: 2, iris: 2, wipe: 2, stagger: 2, pan: 2, 'sdf-iris': 2, 'pixel-dissolve': 2 };

/** The middle of the fastest scene transition (highest energy, then the shortest window): stray artifacts
 * (doubled text, smears, half-drawn elements) hide there, between the evenly spaced frames. */
export function fastestTransition(transitions) {
  const list = (transitions || []).filter((w) => w && Number.isFinite(w.start) && Number.isFinite(w.dur) && w.dur > 0);
  if (!list.length) return null;
  return list.slice().sort((x, y) => (TX_ENERGY[y.type] || 1) - (TX_ENERGY[x.type] || 1) || x.dur - y.dur || x.start - y.start)[0];
}

/** Key times: the opening frame, each scene's settled frame (60% in), the middle of the fastest
 * transition (with a check report), the last frame. */
export function keyTimes({ duration: D, fps }, scenes, count, transitions = null) {
  const lastT = Math.max(0, Math.round(D * fps) - 1) / fps;
  const q = (x) => Math.min(lastT, Math.max(0, Math.round(x * fps - 1e-9) / fps));
  const out = [{ t: 0, label: 'first' }];
  const fx = fastestTransition(transitions);
  const room = MAX_FRAMES - (fx ? 3 : 2);
  if (scenes && scenes.length) {
    let list = scenes.filter((s) => Number.isFinite(s.start) && Number.isFinite(s.end) && s.end > s.start);
    if (list.length > room) {
      const step = list.length / room;
      list = Array.from({ length: room }, (_, i) => list[Math.floor(i * step)]);
    }
    for (const s of list) out.push({ t: q(s.start + 0.6 * (s.end - s.start)), label: String(s.id || s.name || '').slice(0, 18) });
  } else {
    const n = Math.max(1, Math.min(room, count));
    for (let i = 0; i < n; i++) out.push({ t: q(((i + 0.5) / n) * D), label: '' });
  }
  if (fx && fx.start + fx.dur / 2 < lastT) out.push({ t: q(fx.start + fx.dur / 2), label: 'mid ' + String(fx.type || 'transition').slice(0, 13) });
  out.push({ t: lastT, label: 'last' });
  const seen = new Set();
  return out.filter((x) => { const k = x.t.toFixed(4); if (seen.has(k)) return false; seen.add(k); return true; })
    .sort((a, b) => a.t - b.t);
}

export function reviewerBrief({ n, title, image, stills, frames, note, verdicts }) {
  return [
    `# Look ${n}: ${title}`,
    '',
    'You are a disposable visual reviewer for a video job. Open the image below, answer in text, and stop.',
    'Do not edit the project, run showtime, render or re-open images you have already judged.',
    '',
    `- Image: ${image} (${frames.length} frames; each label is its timestamp)`,
    stills ? `- Full-size frames: ${stills} (open one only to confirm a suspected problem in small text)` : null,
    `- The director asks: ${note || 'a general first look: is anything wrong, unreadable or weak?'}`,
    '',
    'Check in this order: (1) broken: blank or black frames, text cut off or outside the frame, overlaps,',
    'wrong aspect; (2) readable on a phone: text too small or low contrast; (3) the first frame already shows',
    'what the video is about; (4) craft: alignment, spacing, one type system and accent, empty or crowded',
    'frames; (5) anything that looks like a placeholder or an invented number, logo or UI. A frame labelled',
    '"mid <transition>" is the middle of the fastest scene change: look there for doubled or smeared text and',
    'half-drawn elements that the settled frames never show.',
    '',
    'Answer in at most 12 lines, most serious first:',
    '',
    '```',
    'VERDICT: ok | fix',
    '- 0:04.2 <what is wrong> -> <the fix>',
    '```',
    '',
    `Append the same lines under "## look ${n}" to ${verdicts}, then reply with them.`,
    '',
  ].filter((l) => l !== null).join('\n');
}

async function main() {
  const a = parseCli(SPEC);
  let arg = a._[0] || '.';
  let why = null;
  const abs = path.resolve(arg);
  if (!fs.existsSync(abs) && !/[\\/]/.test(arg)) {
    // a bare job name (launch -> the newest launch-* job)
    const j = resolveJobDir(arg);
    if (!j) throw new UserError(`not found: ${arg}`, 'pass a project folder, a video file or a job (folder or name)');
    arg = j;
  }
  const argAbs = path.resolve(arg);
  if (isDir(argAbs) && !isFile(path.join(argAbs, 'showtime.json')) && (isFile(path.join(argAbs, 'job.json')) || isFile(path.join(argAbs, 'render.json')))) {
    const jt = jobTarget(argAbs);
    if (!jt) throw new UserError(`${argAbs} has no video or project yet`, 'render a preview first, or pass the project folder');
    arg = jt.target; why = jt.why;
  }
  const video = isVideo(arg);
  const tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'st-look-'));
  let browser = null, lab = null, labServer = null, src = null;
  const shared = {
    tmpDir: tmpRoot, serverUrl: null,
    async browser() { if (!browser) browser = await openBrowser({ gpu: a.gpu || 'auto' }); return browser; },
  };
  try {
    src = await openSource(arg, a, shared);
    const info0 = src.info;
    const W = info0.width, H = info0.height, fps = info0.fps;
    // scenes from a current check report (project only; older than the sources = stale, not used)
    let scenes = null, sceneNote = '', txWindows = null;
    if (!video && !a.at) {
      const fr = checkFreshness(src.dir, src.proj.page, parseSize(a.size));
      const r = fr.state === 'fresh' ? readJSON(fr.report, null) : null;
      if (r && Array.isArray(r.scenes) && r.scenes.length) scenes = r.scenes;
      if (r && Array.isArray(r.transitions)) txWindows = r.transitions;
      else if (fr.state === 'stale') sceneNote = 'the check report is older than the project (run showtime check for scene frames)';
    }
    const count = Number(a.count || 8);
    if (!(count >= 1)) throw new UserError('--count must be >= 1');
    let frames;
    if (a.at) {
      const ts = parseTimes(a.at);
      if (!ts.length) throw new UserError('--at needs at least one time');
      if (ts.length > MAX_FRAMES) throw new UserError(`--at takes at most ${MAX_FRAMES} times (one look is one small image)`, 'split them over two looks, or use --count');
      for (const x of ts) if (x < 0 || x > info0.duration + 1e-6) throw new UserError(`--at ${x} is outside the video (0-${info0.duration}s)`);
      const lastK = Math.max(0, Math.round(info0.duration * fps) - 1);
      frames = ts.map((x) => ({ t: Math.min(lastK, Math.max(0, Math.round(x * fps - 1e-9))) / fps, label: '' }));
    } else frames = keyTimes(info0, scenes, count, txWindows);

    // where looks go: the job (one budget per job), else the project, else a new folder for a loose video
    const job = enclosingJob(video ? src.file : src.dir);
    const outDir = path.resolve(a.output || (job ? path.join(job, 'work', 'look')
      : !video ? path.join(src.dir, 'work', 'look') : jobDir(`look-${path.basename(src.file).replace(VIDEO_EXT, '')}`)));
    fs.mkdirSync(outDir, { recursive: true });
    const taken = fs.readdirSync(outDir).map((f) => /^look-(\d+)\.jpg$/.exec(f)).filter(Boolean).map((m) => Number(m[1]));
    const n = (taken.length ? Math.max(...taken) : 0) + 1;
    const image = path.join(outDir, `look-${n}.jpg`);

    if (!shared.serverUrl) { labServer = await startServer({ root: tmpRoot, port: 0 }); shared.serverUrl = labServer.url; }
    lab = await openLab(await shared.browser(), shared.serverUrl);
    const width = Math.max(320, Math.min(3840, Number(a.width || 1280)));
    const k = frames.length;
    const vertical = H > W;
    const cols = k <= 3 ? k : vertical ? Math.min(8, Math.ceil(k / 2)) : k <= 4 ? 2 : k <= 9 ? 3 : k <= 12 ? 4 : 5;
    const pad = 10;
    const thumb = Math.max(80, Math.floor((width - pad) / cols - pad));
    const stillsDir = a.stills ? path.join(outDir, `look-${n}`) : null;
    if (stillsDir) fs.mkdirSync(stillsDir, { recursive: true });
    const items = [];
    for (const f of frames) {
      const full = await src.grab(Math.round(f.t * fps) / fps);
      if (stillsDir) fs.writeFileSync(path.join(stillsDir, `t${f.t.toFixed(3).padStart(8, '0')}s.jpg`), await lab.resize(full, W, 'image/jpeg', 0.92));
      // shrink first: the lab page gets small frames (memory), and the sheet draws them at thumb size anyway
      const small = thumb * 2 < W ? await lab.resize(full, thumb * 2, 'image/jpeg', 0.9) : full;
      items.push({ buf: small, label: fmtTime(f.t), sub: f.label || '' });
    }
    let buf = await lab.sheet(items, { cols, thumb, title: `${src.title}  ${W}x${H}  look ${n}` });
    fs.writeFileSync(image, buf);
    const verdicts = path.join(outDir, 'verdicts.md');
    if (!isFile(verdicts)) fs.writeFileSync(verdicts, '# Look verdicts\n\nOne section per look: `## look N`, then one line per problem: `- 0:04.2 <what> -> <fix>`, or `ok`.\n\n');
    const brief = path.join(outDir, `look-${n}.md`);
    fs.writeFileSync(brief, reviewerBrief({ n, title: src.title, image, stills: stillsDir, frames, note: a.note, verdicts }));
    const res = {
      look: n, budget: LOOK_BUDGET, image, width, source: video ? src.file : src.dir, kind: src.kind, why,
      frames: frames.map((f) => ({ t: +f.t.toFixed(3), label: f.label || null })),
      scenes_from: scenes ? 'check report' : null, stills: stillsDir, brief, verdicts,
      page_errors: src.kind === 'project' ? src.sess.log.errors.map((e) => e.message) : [],
    };
    const since = job ? await sinceLastLooked(job) : null;   // what the person changed in the job meanwhile
    if (job) res.since_last_looked = since;
    if (a.json) { process.stdout.write(JSON.stringify(res, null, 2) + '\n'); return 0; }
    if (why) console.log(`using ${res.source} (${why})`);
    console.log(`look ${n}/${LOOK_BUDGET}  ${image}  (${k} frames: ${frames.map((f) => fmtTime(f.t) + (f.label ? ' ' + f.label : '')).join(', ')})`);
    console.log(`  reviewer brief ${brief}`);
    console.log(`  verdicts       ${verdicts}  (write this look's verdict there; do not re-open the image)`);
    if (stillsDir) console.log(`  stills         ${stillsDir}`);
    if (sceneNote) console.log(c.dim(`  ${sceneNote}`));
    if (n > LOOK_BUDGET) console.log(c.yellow(`  look ${n} is past the budget of ${LOOK_BUDGET} per job: hand looks to a reviewer sub-agent (the brief above), or rely on check/qa text`));
    if (res.page_errors.length) console.log(c.yellow(`  ${res.page_errors.length} page error(s), first: ${res.page_errors[0]} (run \`showtime check\`)`));
    printSince(since);
    return 0;
  } finally {
    if (lab) await lab.close();
    if (src) await src.close();
    if (browser) await browser.browser.close().catch(() => {});
    if (labServer) await labServer.close().catch(() => {});
    fs.rmSync(tmpRoot, { recursive: true, force: true });
  }
}

// run only as a command (tests import the helpers)
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) runMain(main);

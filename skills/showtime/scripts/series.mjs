// Tutorial series: keep one kit (chrome, sound motif, product UI, named hit-rects) across episodes.
//   showtime new series my-series                 # the series root (opener + kit.js) and episode-01
//   showtime series add my-series --title "Move cards between columns"
//   showtime series sync my-series                # copy the edited kit into every episode
//   showtime series check my-series               # exit 1 when an episode has a stale kit copy
//   showtime series export my-series -o site/     # every episode (and the opener) as HTML + an index page
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseCli, runMain, info, warn, c, UserError, runProc, freshPath } from './lib/cli.mjs';
import { findSeries, episodes, kitState, syncKit, shown } from './lib/export/series.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));

const SPEC = {
  name: 'series',
  usage: 'showtime series <sync|check|add|list|export> <series-folder> [options]',
  summary: 'Tutorial series: one shared kit (chrome, sound motif, product UI) used by every episode project.',
  description: [
    'A series folder holds series.json, kit.js (the shared kit: edit it there), an opener project and one',
    'folder per episode. Each episode is a normal project with a synced copy of the kit, so render,',
    'preview, check, retime and export work on it as on any project. Start one with `showtime new series <dir>`.',
    '',
    '  sync     copy the series kit into every episode (after editing kit.js)',
    '  check    report episodes whose kit copy is stale or missing (exit 1 if any)',
    '  add      create the next episode (episode-NN) from a short skeleton, synced to the kit',
    '  list     episodes with their title, length and kit state',
    '  export   every episode and the opener as single-file HTML videos plus an index.html',
  ].join('\n'),
  options: {
    title: { short: 't', help: 'add: the new episode\'s title' },
    output: { short: 'o', help: 'export: output folder (default <series>/showtime-out/html)', metavar: 'DIR' },
    json: { type: 'boolean', help: 'print a JSON report' },
  },
  examples: [
    'showtime new series planner-howto',
    'showtime series add planner-howto --title "Move cards between columns"',
    'showtime series sync planner-howto',
    'showtime series check planner-howto',
    'showtime series export planner-howto -o planner-site/',
  ],
};

function load(dir) {
  const d = path.resolve(dir || '.');
  const s = findSeries(d);
  if (!s || s.root !== d) {
    if (s) throw new UserError(`${d} is an episode of the series in ${s.root}`, `pass the series folder: showtime series <cmd> ${shown(s.root)}`);
    throw new UserError(`${d} is not a series folder (no series.json)`, 'start one with `showtime new series <dir>`');
  }
  if (!fs.existsSync(s.kitPath)) throw new UserError(`the series kit ${s.kitPath} does not exist`, 'series.json "kit" names the shared kit file (default kit.js)');
  return s;
}

function readCfg(dir) { try { return JSON.parse(fs.readFileSync(path.join(dir, 'showtime.json'), 'utf8').replace(/^\uFEFF/, '')); } catch { return {}; } }

function episodeSkeleton(n, title, series) {
  const nn = String(n).padStart(2, '0');
  return `/* Episode ${nn}: ${title}.
 * One timeline table drives the picture AND the sound (KIT.episode builds both). Times in seconds.
 * The UI is the series kit's product (../kit.js): target it by name (KIT.rects: 'add:0', 'card:c1',
 * 'save', 'col:1', ...), change it with state events, and add steps, captions and keys below. */
'use strict';

var CUE = {
  intro: 3.6,
  s1: 4.0,
  click1: 6.4,
  s2: 9.0,
  recap: 14.0,
  outro: 18.0,
  duration: 22.0,
};

KIT.episode({
  number: ${n},
  title: ${JSON.stringify(title)},
  subtitle: '',
  duration: CUE.duration,
  intro: [0, CUE.intro],
  steps: [[CUE.s1, 'First step'], [CUE.s2, 'Second step']],
  stepsEnd: CUE.recap,
  recap: { t0: CUE.recap, items: [['', 'What this episode showed']] },
  outro: { t0: CUE.outro, next: '' },
  state: [
    [CUE.click1, { composing: 0, pressed: 'add:0', pressT: CUE.click1 }],
  ],
  cursor: [
    [0, 'board', { at: [0.8, 0.85] }],
    [CUE.click1, 'add:0', { click: true, at: [0.3, 0.5] }],
    [CUE.click1 + 1.2, 'col:0', { at: [0.92, 0.55] }],
  ],
  camera: [[CUE.intro, [960, 540], 1], [CUE.s1 + 1.0, 'col:0', 1.5, { whoosh: true }], [CUE.s2 + 0.6, [960, 540], 1]],
  captions: [
    [CUE.s1 + 0.3, CUE.s2 - 0.3, 'Say what the viewer should do, in one short line.'],
    [CUE.s2 + 0.2, CUE.recap - 0.4, 'One caption per beat; keep it under two lines.'],
  ],
});
`;
}

function addEpisode(s, title) {
  const eps = episodes(s);
  let n = eps.length + 1;
  let dir;
  for (; ; n++) { dir = path.join(s.root, `episode-${String(n).padStart(2, '0')}`); if (!fs.existsSync(dir)) break; }
  const nn = String(n).padStart(2, '0');
  const t = String(title || `Episode ${nn}`);
  const rootCfg = readCfg(s.root);
  fs.mkdirSync(dir, { recursive: true });
  const cfg = {
    title: `${nn} · ${t}`, subtitle: '', kicker: `${s.cfg.name || rootCfg.title || 'Series'} · Episode ${nn}`,
    width: rootCfg.width || 1920, height: rootCfg.height || 1080, fps: rootCfg.fps || 30, duration: 22,
    background: rootCfg.background || '#000', score: true, poster: 10,
  };
  fs.writeFileSync(path.join(dir, 'showtime.json'), JSON.stringify(cfg, null, 2) + '\n');
  // the page loads the same runtime and fonts as the series opener
  let page = fs.readFileSync(path.join(s.root, 'index.html'), 'utf8');
  page = page.replace(/<title>[^<]*<\/title>/, `<title>${cfg.title.replace(/[<&]/g, '')}</title>`)
    .replace(/\s*<script src="cues\.js"><\/script>/, '')        // the opener's cue table: the episode has its own
    .replace(/<script src="opener\.js"><\/script>/, '<script src="episode.js"></script>')
    .replace(/<script src="kit\.js"><\/script>/, '<!-- kit.js is the series kit, copied here by `showtime series sync` (edit ../kit.js, not this copy) -->\n  <script src="kit.js"></script>');
  if (!/episode\.js/.test(page)) throw new UserError('could not make the episode page from the series index.html', 'it must load kit.js and opener.js with <script src="..."> tags');
  fs.writeFileSync(path.join(dir, 'index.html'), page);
  fs.writeFileSync(path.join(dir, 'episode.js'), episodeSkeleton(n, t, s));
  syncKit(s, dir);
  const list = (s.cfg.episodes || []).slice();
  list.push(path.basename(dir));
  s.cfg.episodes = list;
  fs.writeFileSync(path.join(s.root, 'series.json'), JSON.stringify(s.cfg, null, 2) + '\n');
  return dir;
}

async function exportAll(s, outArg) {
  const out = path.resolve(outArg || path.join(s.root, 'showtime-out', 'html'));
  fs.mkdirSync(out, { recursive: true });
  const node = process.execPath, script = path.join(HERE, 'export.mjs');
  const items = [];
  const projects = [s.root, ...episodes(s)];
  for (const dir of projects) {
    const name = dir === s.root ? 'opener' : path.basename(dir);
    const file = freshPath(path.join(out, `${name}.html`));
    info(c.dim(`  exporting ${name}...`));
    const r = await runProc(node, [script, 'html', dir, '-o', file, '--json', '-q'], { timeout: 30 * 60 * 1000 });
    if (r.code !== 0) throw new UserError(`export of ${name} failed:\n${(r.stderr || '').trim().split('\n').slice(-6).join('\n')}`);
    const rep = JSON.parse(r.stdout);
    const cfg = readCfg(dir);
    items.push({ name, file: path.basename(rep.output), title: cfg.title || name, subtitle: cfg.subtitle || '', duration: rep.duration, bytes: rep.bytes, chapters: rep.chapters });
  }
  const esc = (x) => String(x).replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
  const fmt = (t) => `${Math.floor(t / 60)}:${String(Math.round(t % 60)).padStart(2, '0')}`;
  const name = s.cfg.name || readCfg(s.root).title || 'Series';
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>${esc(name)}</title><style>
:root{color-scheme:light dark;--bg:#f4f5f9;--fg:#15171d;--muted:#5d6370;--card:#fff;--line:rgba(0,0,0,.08)}
@media (prefers-color-scheme:dark){:root{--bg:#101217;--fg:#eef0f4;--muted:#9aa1ad;--card:#181b22;--line:rgba(255,255,255,.1)}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:760px;margin:0 auto;padding:48px 16px}h1{font-size:32px;margin:0 0 6px}p{color:var(--muted);margin:0 0 28px}
a.ep{display:flex;gap:16px;align-items:baseline;padding:16px 18px;margin:10px 0;border-radius:14px;background:var(--card);border:1px solid var(--line);color:inherit;text-decoration:none}
a.ep:hover{border-color:currentColor}.t{font-weight:650}.s{color:var(--muted);font-size:14px}.d{margin-left:auto;color:var(--muted);font-variant-numeric:tabular-nums}
</style></head><body><main><h1>${esc(name)}</h1><p>${items.length - 1} episode${items.length === 2 ? '' : 's'}. Each one plays offline in the browser; keys: space, arrows, 1-9 for chapters, ? for all.</p>
${items.map((it) => `<a class="ep" href="${encodeURI(it.file)}"><div><div class="t">${esc(it.title)}</div>${it.subtitle ? `<div class="s">${esc(it.subtitle)}</div>` : ''}</div><div class="d">${fmt(it.duration)}</div></a>`).join('\n')}
</main></body></html>
`;
  const index = path.join(out, 'index.html');
  fs.writeFileSync(index, html);
  return { output: out, index, items };
}

async function main() {
  const a = parseCli(SPEC);
  const [cmd, dir] = a._;
  if (!cmd) throw new UserError('missing the command', SPEC.usage);
  const s = load(dir);
  if (cmd === 'sync') {
    const res = episodes(s).map((d) => ({ episode: path.basename(d), changed: syncKit(s, d) }));
    if (a.json) process.stdout.write(JSON.stringify({ series: s.root, kit: s.kitPath, episodes: res }, null, 2) + '\n');
    else {
      for (const r of res) info(`  ${r.episode}: ${r.changed ? c.green('updated') : 'up to date'}`);
      console.log(`${c.green('synced')} ${shown(s.kitPath)} -> ${res.length} episode(s)`);
    }
    return 0;
  }
  if (cmd === 'check' || cmd === 'list') {
    const res = episodes(s).map((d) => { const cfg = readCfg(d); return { episode: path.basename(d), title: cfg.title || '', duration: cfg.duration || null, kit: kitState(s, d) }; });
    const bad = res.filter((r) => r.kit !== 'ok');
    if (a.json) process.stdout.write(JSON.stringify({ series: s.root, ok: !bad.length, episodes: res }, null, 2) + '\n');
    else {
      for (const r of res) info(`  ${r.episode.padEnd(12)} ${String(r.duration || '?').padStart(5)} s  kit ${r.kit === 'ok' ? c.green('ok') : c.yellow(r.kit)}  ${r.title}`);
      if (bad.length) warn(`${bad.length} episode(s) have a ${bad.map((b) => b.kit).join('/')} kit copy: run \`showtime series sync ${shown(s.root)}\``);
      else if (cmd === 'check') console.log(`${c.green('ok')} every episode uses the current kit`);
    }
    return cmd === 'check' && bad.length ? 1 : 0;
  }
  if (cmd === 'add') {
    const d = addEpisode(s, a.title);
    if (a.json) process.stdout.write(JSON.stringify({ episode: d }, null, 2) + '\n');
    else {
      console.log(`${c.green('created')} ${d}`);
      const rel = path.relative(process.cwd(), d);
      info(c.dim(`  edit ${path.join(path.basename(d), 'episode.js')} (the timeline table), then: showtime preview ${rel.startsWith('..') ? d : rel}`));
    }
    return 0;
  }
  if (cmd === 'export') {
    const r = await exportAll(s, a.output);
    if (a.json) process.stdout.write(JSON.stringify(r, null, 2) + '\n');
    else {
      for (const it of r.items) info(`  ${it.file.padEnd(18)} ${(it.bytes / 1024).toFixed(0).padStart(5)} KB  ${it.title}`);
      console.log(`${c.green('exported')} ${r.index}`);
    }
    return 0;
  }
  throw new UserError(`unknown series command "${cmd}"`, SPEC.usage);
}

runMain(main);

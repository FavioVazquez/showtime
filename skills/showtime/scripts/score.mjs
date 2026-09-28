// Render only a project's procedural score (ST.score) to WAV and report its levels per section
import fs from 'node:fs';
import path from 'node:path';
import { startServer } from './server.mjs';
import { parseCli, runMain, resolveProject, jobDir, freshPath, info, warn, c, fmtDuration, UserError } from './lib/cli.mjs';
import { enclosingJob } from './lib/studio/paths.mjs';
import { openBrowser, openStage, pullScore } from './lib/stagehost.mjs';
import { measureLoudness, writeWavFloat } from './lib/ff.mjs';

const SPEC = {
  name: 'score',
  usage: 'showtime score <project> [-o score.wav] [--sections 0,3,6,9] [--json]',
  summary: 'Render just the ST.score of a project (no frames) and report loudness, peaks and per-section levels.',
  description: [
    'Use it to iterate on music and sound design in seconds. The score is rendered offline exactly as',
    '`showtime render` does. Sections come from --sections, else from Film.start({acts}), else 4 equal parts.',
    'Levels are the RAW score: `showtime render` later normalises the final mix to -14 LUFS. With narration\n' +
    '(a voice track in the "audio" mix) it reports the voice-over-bed gap instead (aim for 12-18 dB).',
  ].join('\n'),
  options: {
    output: { short: 'o', help: 'output WAV (default: <job>/work/score/score.wav for a project in a job, else showtime-out/<title>-score-<time>/score.wav beside the project)', metavar: 'FILE' },
    sections: { help: 'comma-separated section start times in seconds for the level report', metavar: 'TIMES' },
    'sample-rate': { help: 'sample rate (default 48000)', metavar: 'HZ' },
    page: { help: 'page inside the project (default index.html)' },
    json: { type: 'boolean', help: 'print the report as JSON on stdout' },
    quiet: { type: 'boolean', short: 'q', help: 'no progress output' },
  },
  examples: [
    'showtime score my-film                      # WAV + level report',
    'showtime score my-film -o /tmp/take2.wav --sections 0,3,6,9',
    'showtime score my-film --json               # machine-readable report',
  ],
};

const db = (x) => (x > 0 ? 20 * Math.log10(x) : -Infinity);
const r1 = (x) => (isFinite(x) ? Math.round(x * 10) / 10 : null);

function levels(ch, sr, a, b) {
  const i0 = Math.max(0, Math.floor(a * sr)), i1 = Math.min(ch[0].length, Math.floor(b * sr));
  let peak = 0, sum = 0, n = 0;
  for (const d of ch) {
    for (let i = i0; i < i1; i++) { const v = d[i]; const av = Math.abs(v); if (av > peak) peak = av; sum += v * v; n++; }
  }
  return { rms_db: r1(db(Math.sqrt(sum / Math.max(1, n)))), peak_db: r1(db(peak)) };
}
function firstLast(ch, sr, thr = 0.001) {
  let first = -1, last = -1;
  const n = ch[0].length;
  for (let i = 0; i < n && first < 0; i++) for (const d of ch) if (Math.abs(d[i]) > thr) { first = i; break; }
  for (let i = n - 1; i >= 0 && last < 0; i--) for (const d of ch) if (Math.abs(d[i]) > thr) { last = i; break; }
  return { first: first < 0 ? null : first / sr, last: last < 0 ? null : last / sr };
}

/** Does the project's showtime.json "audio" mix have a voice track? */
function hasVoiceTrack(proj) {
  let aud = proj.config.audio;
  try {
    if (typeof aud === 'string' && /\.json$/i.test(aud)) aud = JSON.parse(fs.readFileSync(path.resolve(proj.dir, aud), 'utf8').replace(/^\uFEFF/, ''));
  } catch { return false; }
  const tracks = Array.isArray(aud) ? aud : (aud && aud.tracks) || [];
  return tracks.some((t) => t && typeof t === 'object' && (t.kind === 'voice' || /(^|\/)(vo|voice)[^/]*\.wav$/i.test(String(t.file || ''))));
}

async function main() {
  const a = parseCli(SPEC);
  if (!a._[0]) throw new UserError('missing project folder', 'showtime score my-film');
  const proj = resolveProject(a._[0], { page: a.page });
  const sr = a['sample-rate'] ? Number(a['sample-rate']) : 48000;
  if (!(sr >= 8000 && sr <= 192000)) throw new UserError(`--sample-rate must be 8000-192000 (got ${a['sample-rate']})`);
  const note = (m) => { if (!a.quiet && !a.json) info(m); };
  let outFile;
  if (a.output) {
    outFile = freshPath(path.resolve(a.output));
    fs.mkdirSync(path.dirname(outFile), { recursive: true });
  } else {
    const job = enclosingJob(proj.dir);
    if (job) {
      outFile = freshPath(path.join(job, 'work', 'score', 'score.wav'));
      fs.mkdirSync(path.dirname(outFile), { recursive: true });
    } else {
      // never a showtime-out/ inside the project (it would be published with the source)
      const cwd = path.resolve(process.cwd());
      const inside = cwd === proj.dir || cwd.startsWith(proj.dir + path.sep);
      outFile = path.join(jobDir(`${proj.slug}-score`, inside ? path.dirname(proj.dir) : undefined), 'score.wav');
    }
  }
  const t0 = Date.now();
  const server = await startServer({ root: proj.dir, port: 0 });
  let b = null, s = null;
  let report;
  try {
    b = await openBrowser({ gpu: 'auto' });
    s = await openStage(b.browser, { url: server.url, page: proj.page, config: proj.config });
    const dur = s.info.duration;
    if (!s.info.hasScore) {
      throw new UserError('this project has no ST.score',
        'add one: ST.score = Synth.score(function (m) { ... }) or Film.start({score: ...}); see references/synth-score.md');
    }
    note(`${c.bold('showtime score')} ${proj.dir}  (${dur}s)`);
    const tr = Date.now();
    const sc = await pullScore(s.page, { duration: dur, sampleRate: sr });
    if (!sc) throw new UserError('ST.score rendered nothing');
    const renderMs = Date.now() - tr;
    writeWavFloat(outFile, sc.channels, sc.sampleRate);
    // sections
    let starts = [];
    if (a.sections) starts = String(a.sections).split(',').map((x) => Number(x.trim())).filter((x) => x >= 0 && x < dur);
    let labels = [];
    if (!starts.length) {
      const acts = await s.page.evaluate(() => {
        const F = window.Film;
        const acts = F && F.cfg && F.cfg.acts;
        return Array.isArray(acts) ? acts.map((x) => (Array.isArray(x) ? { t: x[0], label: x[1] } : x)) : null;
      }).catch(() => null);
      if (acts && acts.length) { starts = acts.map((x) => Number(x.t)); labels = acts.map((x) => String(x.label || '')); }
    }
    if (!starts.length) starts = [0, dur / 4, dur / 2, (3 * dur) / 4];
    starts = [...new Set(starts)].sort((x, y) => x - y);
    const sections = starts.map((st, i) => {
      const en = i + 1 < starts.length ? starts[i + 1] : dur;
      return { start: Math.round(st * 1000) / 1000, end: Math.round(en * 1000) / 1000, label: labels[i] || '', ...levels(sc.channels, sc.sampleRate, st, en) };
    });
    const whole = levels(sc.channels, sc.sampleRate, 0, dur);
    const fl = firstLast(sc.channels, sc.sampleRate);
    const loud = await measureLoudness(outFile).catch(() => null);
    const warnings = [];
    const notes = [];
    if (fl.first === null) warnings.push('the score is silent');
    else if (fl.first > 0.25) warnings.push(`first sound at ${fl.first.toFixed(2)}s: music usually starts on frame 1`);
    if (sc.peak > 1) warnings.push(`sample peak ${db(sc.peak).toFixed(1)} dBFS clips: lower bus levels or master gain`);
    const narrated = hasVoiceTrack(proj);
    if (loud && narrated) {
      // with narration the raw score is summed with the voice mix (about -14 LUFS) before mastering
      const gap = -14 - loud.input_i;
      if (gap > 22) warnings.push(`with the voice at about -14 LUFS this bed sits ${gap.toFixed(0)} dB under it: barely audible; aim for 12-18 dB (raise master gain)`);
      else if (gap < 8) warnings.push(`with the voice at about -14 LUFS this bed sits only ${gap.toFixed(0)} dB under it: it will compete with the words; aim for 12-18 dB`);
      else notes.push(`voice over this bed: about ${gap.toFixed(0)} dB (aim 12-18 for a sparse bed under an explainer voice)`);
    } else if (loud && loud.input_i < -32) warnings.push(`very quiet (${loud.input_i.toFixed(1)} LUFS): render will add a lot of gain; raise master gain`);
    for (const sec of sections) if (sec.rms_db !== null && sec.rms_db < -55) warnings.push(`section at ${sec.start}s is nearly silent (${sec.rms_db} dB RMS)`);
    report = {
      ok: true, output: outFile, duration: dur, sample_rate: sc.sampleRate,
      lufs: loud ? r1(loud.input_i) : null, true_peak_db: loud ? r1(loud.input_tp) : null, lra: loud ? r1(loud.input_lra) : null,
      sample_peak_db: r1(db(sc.peak)), rms_db: whole.rms_db, first_sound: fl.first === null ? null : Math.round(fl.first * 1000) / 1000,
      sections, warnings, notes, narrated, render_ms: renderMs, total_ms: Date.now() - t0,
    };
  } finally {
    if (s) await s.close().catch(() => {});
    if (b) await b.browser.close().catch(() => {});
    await server.close().catch(() => {});
  }
  fs.writeFileSync(outFile.replace(/\.wav$/i, '') + '.json', JSON.stringify(report, null, 2));
  if (a.json) { process.stdout.write(JSON.stringify(report, null, 2) + '\n'); return 0; }
  note(`  rendered offline in ${fmtDuration(report.render_ms)}`);
  note(`  loudness ${report.lufs} LUFS  true peak ${report.true_peak_db} dBTP  LRA ${report.lra} LU  first sound ${report.first_sound}s`);
  for (const sec of report.sections) {
    note(`  ${String(sec.start).padStart(6)}-${String(sec.end).padEnd(6)} ${(sec.label || '').padEnd(12)} rms ${String(sec.rms_db).padStart(6)} dB  peak ${String(sec.peak_db).padStart(6)} dB`);
  }
  for (const w of report.warnings) warn(w);
  for (const n of report.notes || []) note(`  ${n}`);
  note(c.dim('  (raw score levels; `showtime render` normalises the final mix to -14 LUFS)'));
  info(`${c.green('done')} ${outFile}`);
  return 0;
}

runMain(main);

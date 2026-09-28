// Soundtrack helpers shared by render and preview: the showtime.json "audio" value -> a WAV.
//
// "audio" may be: an audio file ("music/bed.mp3"), a mix spec path ("audio/mix.json"), an inline
// mix object ({"tracks": [...]}) or a list of files/tracks. Mix specs go to `showtime audio mix`
// (the audio module: ducking, synth/compose tracks, hit alignment); when that module is missing
// or fails, a simple built-in ffmpeg mixer handles file tracks.
import fs from 'node:fs';
import path from 'node:path';
import { runPyCli, hasPyModule, UserError } from './cli.mjs';
import { ffmpeg } from './ff.mjs';

/** Files a mix depends on (for cache freshness checks). */
export function audioInputs(aud, dir) {
  const out = [];
  const add = (f) => { if (f) out.push(path.resolve(dir, f)); };
  if (typeof aud === 'string') {
    add(aud);
    if (/\.json$/i.test(aud)) {
      try { const j = JSON.parse(fs.readFileSync(path.resolve(dir, aud), 'utf8').replace(/^\uFEFF/, '')); for (const t of j.tracks || []) add(t.file); } catch { /* ignore */ }
    }
  } else if (Array.isArray(aud)) {
    for (const t of aud) add(typeof t === 'string' ? t : t.file);
  } else if (aud && typeof aud === 'object') {
    for (const t of aud.tracks || []) add(t.file);
  }
  return out;
}

/** Mix the showtime.json "audio" value into out (48 kHz stereo WAV). -> {kind, credits} | null */
export async function mixFromConfig(aud, dir, duration, out, audioDir, addWarn) {
  // a plain audio file
  if (typeof aud === 'string' && !/\.json$/i.test(aud)) {
    const f = path.resolve(dir, aud);
    if (!fs.existsSync(f)) { addWarn(`showtime.json audio file not found: ${aud}`); return null; }
    await ffmpeg(['-i', f, '-vn', '-af', 'aresample=48000', '-c:a', 'pcm_f32le', '-ar', '48000', '-ac', '2', out]);
    return { kind: path.basename(f) };
  }
  // a mix spec: file path, inline object, or a list of files/tracks
  let spec, specPath;
  if (typeof aud === 'string') {
    specPath = path.resolve(dir, aud);
    if (!fs.existsSync(specPath)) { addWarn(`showtime.json audio mix not found: ${aud}`); return null; }
    try { spec = JSON.parse(fs.readFileSync(specPath, 'utf8').replace(/^\uFEFF/, '')); } catch (e) { addWarn(`${aud} is not valid JSON: ${e.message}`); return null; }
  } else if (Array.isArray(aud)) {
    spec = { tracks: aud.map((x) => (typeof x === 'string' ? { file: x } : x)) };
  } else if (typeof aud === 'object') {
    spec = aud;
  } else { addWarn(`showtime.json "audio" must be a file, a mix.json path or a list of tracks`); return null; }
  if (!spec.duration) spec.duration = duration;
  if (!specPath) {
    specPath = path.join(audioDir, 'mix.json');
    // relative track paths stay relative to the project folder
    const abs = { ...spec, tracks: (spec.tracks || []).map((t) => (t.file ? { ...t, file: path.resolve(dir, t.file) } : t)) };
    fs.writeFileSync(specPath, JSON.stringify(abs, null, 2));
  }
  // preferred: the audio module (ducking, synth/compose tracks, hit alignment, reports)
  if (hasPyModule('cli_audio.py')) {
    let r = null;
    for (let attempt = 1; attempt <= 2; attempt++) {
      r = await runPyCli(['audio', 'mix', specPath, '-o', out], { cwd: dir, timeout: MIX_TIMEOUT_MS });
      if (r.code === 0 && fs.existsSync(out)) {
        let credits = [];
        const rep = out.replace(/\.wav$/i, '.report.json');
        for (const cand of [rep, path.join(path.dirname(out), 'mix.report.json')]) {
          try { const j = JSON.parse(fs.readFileSync(cand, 'utf8')); credits = (j.credits || []).map((x) => (typeof x === 'string' ? x : x.text || x.credit || JSON.stringify(x))); break; } catch { /* none */ }
        }
        return { kind: 'mix', credits };
      }
      if (/timed out/.test(r.stderr || '')) break;          // a hang does not get a second 20 minutes
    }
    const lines = (r.stderr || '').trim().split('\n').map((l) => l.trim()).filter(Boolean);
    const why = ([...lines].reverse().find((l) => /error:|timed out/i.test(l)) || lines.pop() || `exit ${r.code}`).replace(/^.*?error:\s*/i, '');
    // the simple mixer can only play plain files: shipping it for a mix with synth/compose/typewriter
    // tracks, ducking or hit alignment would silently change the soundtrack, so the render stops instead
    const lost = (spec.tracks || []).filter((t) => !t.file).length;
    if (lost || (spec.tracks || []).some((t) => t.duck)) {
      throw new UserError(`the audio mix failed: ${why}`,
        `run \`showtime audio mix ${path.relative(process.cwd(), specPath) || specPath}\` to see the whole error; the simple mixer is not used because it would drop ${lost ? `${lost} synth/compose track(s)` : 'the ducking'}`);
    }
    addWarn(`AUDIO FALLBACK: \`showtime audio mix\` failed (${why}); the soundtrack was mixed by the simple built-in mixer (plain files only, no ducking or level matching). Fix the mix and render again for the real soundtrack`);
  }
  return simpleMix(spec, dir, duration, out, addWarn);
}

const MIX_TIMEOUT_MS = 20 * 60 * 1000;

/**
 * Fallback mixer: file tracks with start/at, offset, dur, gain, fades, loop; no ducking.
 *
 * Each track is rendered on its own to a stem that spans the whole mix, then the equal-length stems
 * are summed. One ffmpeg graph with every file as an input (tracks that start 50 s apart, the same
 * file twice) deadlocks intermittently in ffmpeg's threaded scheduler; aligned stems do not.
 */
export async function simpleMix(spec, dir, duration, out, addWarn) {
  const tracks = (spec.tracks || []).filter((t) => {
    if (t.file) return true;
    addWarn(`simple mixer: skipped a ${t.kind || 'track'} without "file" (synth/compose tracks need the audio module)`);
    return false;
  });
  if (!tracks.length) return null;
  const total = Number(spec.duration) || duration;
  const timeout = Math.max(120000, total * 3000);
  const stems = [];
  let ducked = false;
  const tag = `${process.pid}-${Date.now().toString(36)}`;
  try {
    for (const t of tracks) {
      const f = path.resolve(dir, t.file);
      if (!fs.existsSync(f)) { addWarn(`audio track not found: ${t.file}`); continue; }
      if (t.duck) ducked = true;
      const args = [];
      if (t.loop) args.push('-stream_loop', '-1');
      args.push('-i', f);
      let start = Number(t.at !== undefined ? t.at : t.start) || 0;
      if (t.align === 'hit' && t.hit !== undefined) start -= Number(t.hit) || 0;
      const offset = Number(t.offset) || 0;
      const parts = ['aresample=48000', 'aformat=sample_fmts=fltp:channel_layouts=stereo'];
      if (offset > 0 || start < 0) parts.push(`atrim=start=${(offset + Math.max(0, -start)).toFixed(6)}`, 'asetpts=PTS-STARTPTS');
      let len = Math.max(0.01, total - Math.max(0, start));
      if (Number(t.dur) > 0) len = Math.min(len, Number(t.dur));
      parts.push(`atrim=0:${len.toFixed(6)}`);
      if (t.gain_db) parts.push(`volume=${Number(t.gain_db)}dB`);
      if (t.fade_in) parts.push(`afade=t=in:st=0:d=${Number(t.fade_in)}`);
      if (t.fade_out) {
        const fo = Number(t.fade_out);
        parts.push(`afade=t=out:st=${Math.max(0, len - fo).toFixed(6)}:d=${fo}`);
      }
      if (start > 0) { const ms = Math.round(start * 1000); parts.push(`adelay=${ms}|${ms}`); }
      parts.push('apad', `atrim=0:${total.toFixed(6)}`);
      const stem = path.join(path.dirname(out), `.simple-${tag}-${stems.length}.wav`);
      await ffmpeg([...args, '-vn', '-af', parts.join(','), '-c:a', 'pcm_f32le', '-ar', '48000', '-ac', '2', stem], { timeout });
      stems.push(stem);
    }
    if (!stems.length) return null;
    if (ducked) addWarn('simple mixer: "duck" is ignored (install the audio module for ducking)');
    const n = stems.length;
    const args = [];
    for (const s of stems) args.push('-i', s);
    const graph = n > 1
      ? `${stems.map((_, k) => `[${k}:a]`).join('')}amix=inputs=${n}:duration=longest:dropout_transition=0:normalize=0,atrim=0:${total.toFixed(6)}[out]`
      : `[0:a]atrim=0:${total.toFixed(6)}[out]`;
    await ffmpeg([...args, '-filter_complex', graph, '-map', '[out]', '-c:a', 'pcm_f32le', '-ar', '48000', '-ac', '2', out], { timeout });
    return { kind: `mix(${n} file${n > 1 ? 's' : ''})` };
  } finally {
    for (const s of stems) { try { fs.rmSync(s, { force: true }); } catch { /* best effort */ } }
  }
}


/**
 * Master a WAV to a loudness target: exact linear gain when the peaks allow it, otherwise gain into an
 * oversampled limiter (at most `maxLimitDb` of limiting, up to 3 passes). The audio module's
 * `showtime audio master` is used instead when it is installed.
 * -> { mode: 'linear'|'limited'|'audio-module'|'silent', lufs, true_peak, gain_db, reached }
 */
export async function master(inWav, outWav, { target = -14, tp = -1, maxLimitDb = 6, useModule = true } = {}) {
  const { ebur128: meter } = await import('./ff.mjs');
  if (useModule && hasPyModule('cli_audio.py')) {
    const r = await runPyCli(['audio', 'master', inWav, '-o', outWav, '--lufs', String(target), '--tp', String(tp)]);
    if (r.code === 0 && fs.existsSync(outWav)) {
      const m = await meter(outWav);
      return { mode: 'audio-module', lufs: m.I, true_peak: m.TP, gain_db: null, reached: m.I !== null && Math.abs(m.I - target) <= 1 };
    }
  }
  const m0 = await meter(inWav);
  if (m0.I === null) { fs.copyFileSync(inWav, outWav); return { mode: 'silent', lufs: null, true_peak: m0.TP, gain_db: 0, reached: false }; }
  const want = target - m0.I;
  const headroom = tp - m0.TP;
  if (want <= headroom + 0.05) {
    await ffmpeg(['-i', inWav, '-af', `volume=${want.toFixed(3)}dB`, '-c:a', 'pcm_f32le', outWav]);
    const m = await meter(outWav);
    return { mode: 'linear', lufs: m.I, true_peak: m.TP, gain_db: +want.toFixed(2), reached: true };
  }
  const ceiling = Math.pow(10, (tp - 0.4) / 20).toFixed(4);
  const maxGain = headroom + maxLimitDb;
  let cur = inWav, I = m0.I, total = 0, m = m0;
  const tmp = (k) => outWav.replace(/\.wav$/i, `.pass${k}.wav`);
  for (let k = 1; k <= 3; k++) {
    const g = Math.min(target - I, maxGain - total);
    if (g < 0.1) break;
    const dst = tmp(k);
    await ffmpeg(['-i', cur, '-af', `aresample=192000,volume=${g.toFixed(3)}dB,alimiter=limit=${ceiling}:attack=0.3:release=40:level=false,aresample=48000`,
      '-c:a', 'pcm_f32le', dst]);
    if (cur !== inWav) fs.rmSync(cur, { force: true });
    cur = dst; total += g;
    m = await meter(cur);
    I = m.I === null ? I : m.I;
    if (Math.abs(target - I) <= 0.3) break;
  }
  fs.renameSync(cur, outWav);
  return { mode: 'limited', lufs: m.I, true_peak: m.TP, gain_db: +total.toFixed(2), reached: m.I !== null && Math.abs(m.I - target) <= 1 };
}

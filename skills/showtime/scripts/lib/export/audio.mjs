// Soundtrack of an exported HTML video.
//
//   embed: the same soundtrack as `showtime render` (ST.score rendered offline + the showtime.json
//          "audio" mix via `showtime audio mix`, combined, cut to the exact length, brought to the
//          loudness target), encoded small (AAC in .m4a, or Opus in .webm) to be packed in the file.
//   score: nothing is packed; the browser renders ST.score itself. We only measure it here, so the
//          player can apply the same loudness gain the render would (plain gain, never above the ceiling).
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { skillDir } from '../deps.mjs';
import { ffmpeg, ebur128, writeWavFloat, hasEncoder } from '../ff.mjs';
import { mixFromConfig, master } from '../audio.mjs';
import { UserError } from '../cli.mjs';

export function hasMix(cfg) {
  const a = cfg.audio;
  return !(a === undefined || a === null || a === false || a === '' || (Array.isArray(a) && !a.length));
}

/** auto -> score (score-only project), embed (a mix), none (silent). */
export function resolveAudioMode(want, { hasScore, mix }) {
  const w = String(want || 'auto').toLowerCase();
  if (!['auto', 'embed', 'score', 'none'].includes(w)) throw new UserError(`--audio must be auto, embed, score or none (got ${want})`);
  if (w === 'none') return { mode: 'none' };
  if (w === 'score') {
    if (!hasScore) throw new UserError('--audio score needs a project with ST.score (a procedural score)', 'use --audio embed for a project whose sound is a mix or a file');
    return { mode: 'score', dropsMix: mix };
  }
  if (w === 'embed') return hasScore || mix ? { mode: 'embed' } : { mode: 'none' };
  if (hasScore && !mix) return { mode: 'score' };
  if (hasScore || mix) return { mode: 'embed' };
  return { mode: 'none' };
}

function loudTarget(cfg, lufsArg) {
  const target = lufsArg !== undefined ? Number(lufsArg)
    : (cfg.loudness !== undefined ? Number(cfg.loudness) : (cfg.master && cfg.master.lufs !== undefined ? Number(cfg.master.lufs) : -14));
  const tp = cfg.master && cfg.master.true_peak !== undefined ? Number(cfg.master.true_peak) : -1;
  if (!(target < 0 && target > -40)) throw new UserError(`loudness target must be between -40 and 0 LUFS (got ${target})`);
  return { target, tp };
}

let limiter = null;
/** The player's limiter (runtime/player/limiter.js), evaluated here so export and playback match. */
export function stLimit(...args) {
  if (!limiter) {
    const box = {};
    vm.runInNewContext(fs.readFileSync(path.join(skillDir(), 'runtime', 'player', 'limiter.js'), 'utf8'), box);
    limiter = box.__stLimit;
  }
  return limiter(...args);
}

/**
 * Score mode: the gain (dB) and ceiling the player applies to the score it renders, chosen like the
 * render's mastering: exact gain when the peaks allow it, else gain into the limiter (at most 6 dB of
 * limiting), measured on the same limiter the browser runs.
 */
export async function scoreGain({ score, cfg, workDir, lufsArg }) {
  const { target, tp } = loudTarget(cfg, lufsArg);
  const ceilDb = tp - 0.5;
  const f = path.join(workDir, 'score.wav');
  writeWavFloat(f, score.channels, score.sampleRate);
  const m0 = await ebur128(f);
  if (m0.I === null) return { gainDb: 0, ceilDb, lufs: null, target, reached: false };
  let peak = 0;
  for (const ch of score.channels) for (let i = 0; i < ch.length; i++) { const a = Math.abs(ch[i]); if (a > peak) peak = a; }
  const maxGain = (ceilDb - 20 * Math.log10(Math.max(peak, 1e-9))) + 6;
  let gainDb = Math.min(target - m0.I, maxGain), I = m0.I, TP = m0.TP;
  for (let k = 0; k < 3; k++) {
    const lim = stLimit(score.channels, score.sampleRate, gainDb, ceilDb);
    const g = path.join(workDir, `score-lim${k}.wav`);
    writeWavFloat(g, lim, score.sampleRate);
    const m = await ebur128(g);
    I = m.I; TP = m.TP;
    if (I === null || Math.abs(target - I) <= 0.3) break;
    const next = Math.min(gainDb + (target - I), maxGain);
    if (Math.abs(next - gainDb) < 0.05) break;
    gainDb = next;
  }
  return { gainDb: +gainDb.toFixed(2), ceilDb, lufs: I === null ? null : +I.toFixed(1), true_peak: TP, target, reached: I !== null && Math.abs(target - I) <= 1 };
}

/**
 * Embed mode: build and encode the soundtrack.
 * -> { file, mime, ext, bytes, lufs, true_peak, sources, credits } | null (silent)
 */
export async function buildEmbedAudio({ proj, cfg, duration, score, workDir, codec, bitrate, lufsArg, noLoudnorm, warn, file: given }) {
  const inputs = [];
  const sources = [];
  let credits = [];
  if (given) {
    // --audio-file: exactly this sound (a shipped MP4's soundtrack, a WAV), instead of the score and the mix
    if (!fs.existsSync(given)) throw new UserError(`--audio-file not found: ${given}`);
    inputs.push(given);
    sources.push(path.basename(given));
  }
  if (score && !given) {
    const f = path.join(workDir, 'score.wav');
    writeWavFloat(f, score.channels, score.sampleRate);
    inputs.push(f);
    sources.push('score');
  }
  if (hasMix(cfg) && !given) {
    const out = path.join(workDir, 'mix.wav');
    const r = await mixFromConfig(cfg.audio, proj.dir, duration, out, workDir, warn);
    if (r) { inputs.push(out); sources.push(r.kind); credits = r.credits || []; }
  }
  if (!inputs.length) return null;
  const combined = path.join(workDir, 'combined.wav');
  const args = [];
  inputs.forEach((f) => args.push('-i', f));
  const chains = inputs.map((_, k) => `[${k}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a${k}]`);
  const mixPart = inputs.length > 1
    ? `;${inputs.map((_, k) => `[a${k}]`).join('')}amix=inputs=${inputs.length}:duration=longest:dropout_transition=0:normalize=0[m];[m]`
    : ';[a0]';
  await ffmpeg([...args, '-filter_complex', `${chains.join(';')}${mixPart}apad,atrim=0:${duration.toFixed(6)}[out]`,
    '-map', '[out]', '-c:a', 'pcm_f32le', '-ar', '48000', '-ac', '2', combined]);

  const { target, tp } = loudTarget(cfg, lufsArg);
  const masterWav = path.join(workDir, 'master.wav');
  if (noLoudnorm) fs.copyFileSync(combined, masterWav);
  else {
    // a lossy encode at a low bitrate overshoots true peak more than 256k AAC: keep 1 dB of headroom
    const r = await master(combined, masterWav, { target, tp: tp - 1.0 });
    if (r.error) warn(`loudness not measured, the soundtrack is not leveled: ${r.error}`);
    else if (r.mode === 'silent') warn('the soundtrack is silent');
    else if (!r.reached) warn(`the soundtrack reached ${r.lufs === null ? '?' : r.lufs.toFixed(1)} LUFS instead of ${target}`);
  }
  const c = String(codec || 'aac').toLowerCase();
  const br = String(bitrate || '96k');
  if (!/^\d+(\.\d+)?k$/i.test(br)) throw new UserError(`--bitrate must look like 96k (got ${bitrate})`);
  let file, mime, ext;
  if (c === 'opus') {
    if (!hasEncoder('libopus')) throw new UserError('this ffmpeg has no Opus encoder', 'use --codec aac (the default)');
    ext = '.webm'; mime = 'audio/webm';
    file = path.join(workDir, 'soundtrack.webm');
    await ffmpeg(['-i', masterWav, '-c:a', 'libopus', '-b:a', br, '-vbr', 'on', '-application', 'audio', '-ar', '48000', '-ac', '2',
      '-t', duration.toFixed(6), '-f', 'webm', file]);
  } else if (c === 'aac') {
    ext = '.m4a'; mime = 'audio/mp4';
    file = path.join(workDir, 'soundtrack.m4a');
    // .m4a keeps the encoder delay in an edit list, so browsers start the sound on time
    await ffmpeg(['-i', masterWav, '-c:a', 'aac', '-b:a', br, '-ar', '48000', '-ac', '2', '-t', duration.toFixed(6),
      '-movflags', '+faststart', file]);
  } else throw new UserError(`--codec must be aac or opus (got ${codec})`);
  const m = await ebur128(file);
  return { file, mime, ext, bytes: fs.statSync(file).size, lufs: m.I, true_peak: m.TP, sources, credits, codec: c, bitrate: br };
}

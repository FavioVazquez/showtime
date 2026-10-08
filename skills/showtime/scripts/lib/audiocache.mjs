// The soundtrack of a render, kept by a hash of everything it is made from, so a render whose audio inputs did
// not change (a `--from/--to` fix of the pictures, a re-render after a page edit) reuses it instead of mixing,
// mastering and encoding it again (10-15 s on a 15-30 s video, more for longer ones).
//
// The key covers: the mix spec and every file it names (inside or outside the project) with the sidecars beside
// each (license, beats, words, hit point), every file of the project that is not part of the picture
// (showtime.json, mix specs, voice takes and their timings, music, sound files, question cues; not the page's
// HTML/JS/CSS, images, fonts or unnamed videos), the music vetoes and look history when a track is a catalog
// query, the offline ST.score's samples (rendered every time: it is page code), the range and length, the
// loudness settings, the ffmpeg binary, the library and catalog settings, and the audio code itself (a
// showtime update changes it). Anything it cannot read whole makes the render mix as before.
// SHOWTIME_AUDIO_CACHE=0 turns it off.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import { showtimeHome, skillDir } from './deps.mjs';

const VERSION = 1;
const KEEP = 12;                                  // entries kept (newest first)
const KEEP_BYTES = 1024 * 1024 * 1024;            // and at most this much in all
const ENTRY_MAX_BYTES = 256 * 1024 * 1024;        // a longer soundtrack is not kept
const MAX_FILES = 4000;
const HASH_MAX_BYTES = 32 * 1024 * 1024;         // bigger files count by size and time
const SKIP_DIRS = new Set(['showtime-out', 'node_modules', '.git', '.svn', '__pycache__']);
// the picture: these never feed the soundtrack unless the mix names them
const PICTURE_EXT = /\.(html?|m?js|cjs|ts|css|map|svg|png|jpe?g|webp|gif|avif|ico|bmp|tiff?|woff2?|ttf|otf|eot|mp4|mov|m4v|webm|mkv|avi|glb|gltf|obj|hdr|exr|ktx2?|md|pdf|psd)$/i;

export function audioCacheOn() {
  return !['0', 'false', 'no', 'off'].includes(String(process.env.SHOWTIME_AUDIO_CACHE || '').toLowerCase());
}

// SHOWTIME_AUDIO_CACHE_DIR moves it (the tests keep theirs in a scratch folder)
export function cacheRoot() { return process.env.SHOWTIME_AUDIO_CACHE_DIR || path.join(showtimeHome(), 'cache', 'render-audio'); }

// read asynchronously, one file at a time: hashing hundreds of MB of voice and music must not stop the event
// loop (the capture and the encoder feed run on it meanwhile)
async function fileSig(f, h) {
  const st = await fs.promises.stat(f);
  h.update(`${st.size}:${Math.round(st.mtimeMs)}\0`);
  if (st.size <= HASH_MAX_BYTES) h.update(crypto.createHash('sha1').update(await fs.promises.readFile(f)).digest());
}

/** A file's size and time only (code, binaries); a missing file counts as missing. */
function statSig(f, h) {
  try { const st = fs.statSync(f); h.update(`${f}:${st.size}:${Math.round(st.mtimeMs)}\0`); } catch { h.update(`${f}:none\0`); }
}

/** Files of the project that may feed the soundtrack (sorted, relative), or null when there are too many. */
function projectFiles(dir) {
  const out = [];
  const walk = (d, rel) => {
    let ents;
    try { ents = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
    for (const e of ents) {
      if (out.length > MAX_FILES) return;
      const r = rel ? `${rel}/${e.name}` : e.name;
      if (e.isDirectory()) {
        if (SKIP_DIRS.has(e.name) || e.name.endsWith('.work') || e.name.startsWith('.')) continue;
        walk(path.join(d, e.name), r);
      } else if (e.isFile() && !PICTURE_EXT.test(e.name) && !e.name.startsWith('.')) out.push(r);
    }
  };
  walk(dir, '');
  return out.length > MAX_FILES ? null : out.sort();
}

/** The mix spec: showtime.json "audio" itself, or the mix.json it names (parsed), and the folders paths resolve in. */
function mixSpec(aud, projDir) {
  let spec = aud;
  const bases = [projDir];
  if (typeof aud === 'string' && /\.json$/i.test(aud)) {
    const sp = path.resolve(projDir, aud);
    bases.push(path.dirname(sp));
    try { spec = JSON.parse(fs.readFileSync(sp, 'utf8').replace(/^﻿/, '')); } catch { spec = null; }
  }
  return { spec, bases };
}

/**
 * Every string in the mix spec that names an existing file (relative to the project or the spec's folder), and
 * the files beside each one that the mix reads with it: the audio module looks for <file>.license.json (license
 * and credit), <stem>.beats.json, <stem>.words.json (ducking under speech), <stem>.sfx.json (the hit point) and
 * <stem>.musicgen.json, so every non-picture file in that folder whose name starts with the file's stem counts.
 */
function namedFiles(aud, projDir) {
  const found = new Set();
  const { spec, bases } = mixSpec(aud, projDir);
  const visit = (v) => {
    if (typeof v === 'string') {
      if (v.length > 1024 || /^[a-z]+:\/\//i.test(v)) return;
      for (const b of bases) {
        const f = path.resolve(b, v);
        try { if (fs.statSync(f).isFile()) { found.add(f); break; } } catch { /* not a file */ }
      }
    } else if (Array.isArray(v)) v.forEach(visit);
    else if (v && typeof v === 'object') Object.values(v).forEach(visit);
  };
  visit(aud);
  if (spec !== aud) visit(spec);
  for (const f of [...found]) {
    const dir = path.dirname(f), name = path.basename(f), stem = name.replace(/\.[^.]+$/, '');
    let names = [];
    try { names = fs.readdirSync(dir); } catch { /* unreadable: the file itself still counts */ }
    for (const n of names) {
      if (n === name || !n.startsWith(stem) || PICTURE_EXT.test(n)) continue;
      const g = path.join(dir, n);
      try { if (fs.statSync(g).isFile()) found.add(g); } catch { /* gone */ }
    }
  }
  return [...found].sort();
}

/**
 * Inputs of a catalog query track ({"catalog": {"use": ...}} without an id): the pick skips vetoed tracks
 * (`audio music veto`) and keeps the track the look history recorded for the job, so those files (or their
 * absence) are part of the key. An id is fixed by itself.
 */
function catalogQueryFiles(aud, projDir) {
  const { spec } = mixSpec(aud, projDir);
  const tracks = Array.isArray(spec) ? spec : (spec && Array.isArray(spec.tracks) ? spec.tracks : []);
  const query = tracks.some((t) => t && typeof t === 'object' && t.catalog && typeof t.catalog === 'object' && !t.catalog.id);
  if (!query) return [];
  const home = showtimeHome();
  const musicDir = process.env.SHOWTIME_MUSIC_CACHE ? path.resolve(process.env.SHOWTIME_MUSIC_CACHE.replace(/^~(?=$|[\\/])/, os.homedir())) : path.join(home, 'music');
  const histDir = process.env.SHOWTIME_HISTORY_DIR ? path.resolve(process.env.SHOWTIME_HISTORY_DIR.replace(/^~(?=$|[\\/])/, os.homedir())) : path.join(home, 'history');
  return [path.join(musicDir, 'vetoes.json'), path.join(histDir, 'looks.json'), path.join(histDir, 'OFF')];
}

/** The code that makes the soundtrack: a change (an update, a fix) makes a new key. */
function codeFiles() {
  const sk = skillDir();
  const out = [path.join(sk, 'scripts', 'render.mjs'), path.join(sk, 'scripts', 'lib', 'audio.mjs'), path.join(sk, 'scripts', 'lib', 'ff.mjs'),
    path.join(sk, 'lib', 'st', 'cli_audio.py'), path.join(sk, 'lib', 'st', 'questions.py'), path.join(sk, 'lib', 'st', 'common.py'),
    path.join(sk, 'lib', 'st', 'ff.py'), path.join(sk, 'lib', 'st', 'variety', 'history.py')];
  try { for (const n of fs.readdirSync(path.join(sk, 'lib', 'st', 'audio')).sort()) out.push(path.join(sk, 'lib', 'st', 'audio', n)); } catch { /* none */ }
  return out.filter((f) => { try { return fs.statSync(f).isFile(); } catch { return false; } });
}

// environment that changes what the audio module reads or picks
const ENV_KEYS = ['SHOWTIME_LIBRARY', 'SHOWTIME_MUSIC_CATALOG', 'SHOWTIME_MUSIC_CACHE', 'SHOWTIME_MUSIC_ROTATION', 'SHOWTIME_HISTORY', 'SHOWTIME_HISTORY_DIR'];

/**
 * The cache key for a soundtrack, or null when it cannot be computed safely.
 * @param o.projDir, o.aud (showtime.json "audio"), o.scoreFile (score.wav or null), o.settings (plain values),
 *        o.ffmpeg (the ffmpeg binary render uses: its path, size and time count)
 */
export async function audioKey({ projDir, aud, scoreFile, settings, ffmpeg = null }) {
  try {
    const h = crypto.createHash('sha256');
    h.update(`showtime-render-audio ${VERSION}\0${JSON.stringify(settings)}\0${JSON.stringify(aud === undefined ? null : aud)}\0`);
    h.update(`env:${JSON.stringify(ENV_KEYS.map((k) => [k, process.env[k] ?? null]))}\0`);
    if (ffmpeg) { h.update('ff\0'); statSig(ffmpeg, h); }
    const files = projectFiles(projDir);
    if (!files) return null;
    for (const r of files) { h.update(`p:${r}\0`); await fileSig(path.join(projDir, r), h); }
    for (const f of namedFiles(aud, projDir)) { h.update(`n:${f}\0`); await fileSig(f, h); }
    for (const f of catalogQueryFiles(aud, projDir)) {
      h.update(`q:${f}\0`);
      if (fs.existsSync(f)) await fileSig(f, h); else h.update('none\0');
    }
    for (const f of codeFiles()) { h.update(`c:${path.basename(f)}\0`); statSig(f, h); }
    if (scoreFile) { h.update('s\0'); await fileSig(scoreFile, h); }
    return h.digest('hex').slice(0, 40);
  } catch { return null; }
}

// the files of audioDir an entry keeps: what later steps read (the master, the mix report and spec, the
// narration stem) and nothing that is only an intermediate (score, mix and combined WAVs)
const KEEP_FILE = (n) => !/^(score|mix|combined|master2)\.wav$/i.test(n) && !/^aac-try\d+\.m4a$/i.test(n) && !/\.pass\d+\.wav$/i.test(n) && !n.startsWith('.');

/** Restore an entry into audioDir: -> {result, warnings, notes} with paths in audioDir, or null. */
export function restoreAudio(key, audioDir) {
  const dir = path.join(cacheRoot(), key);
  let entry;
  try { entry = JSON.parse(fs.readFileSync(path.join(dir, 'entry.json'), 'utf8')); } catch { return null; }
  try {
    for (const n of entry.files || []) fs.copyFileSync(path.join(dir, n), path.join(audioDir, n));
    const now = new Date();
    fs.utimesSync(path.join(dir, 'entry.json'), now, now);
  } catch { return null; }
  const abs = (n) => (n ? path.join(audioDir, n) : null);
  const r = entry.result;
  return { result: { ...r, file: abs(r.file), wav: abs(r.wav), mixReport: abs(r.mixReport), report: { ...r.report, reused: true } }, warnings: entry.warnings || [], notes: entry.notes || [], made: entry.made };
}

/** Keep audioDir's soundtrack under `key` (best effort; never fails a render). */
export function saveAudio(key, audioDir, result, { warnings = [], notes = [] } = {}) {
  const root = cacheRoot();
  const tmp = path.join(root, `.tmp-${process.pid}-${Date.now().toString(36)}`);
  try {
    const rel = (f) => (f && path.dirname(path.resolve(f)) === path.resolve(audioDir) ? path.basename(f) : null);
    if (!rel(result.file) || !rel(result.wav)) return false;
    if (result.mixReport && !rel(result.mixReport)) return false;
    fs.mkdirSync(tmp, { recursive: true });
    const files = fs.readdirSync(audioDir).filter((n) => KEEP_FILE(n) && fs.statSync(path.join(audioDir, n)).isFile());
    if (files.reduce((n, f) => n + fs.statSync(path.join(audioDir, f)).size, 0) > ENTRY_MAX_BYTES) return false;
    for (const n of files) fs.copyFileSync(path.join(audioDir, n), path.join(tmp, n));
    const entry = { version: VERSION, made: new Date().toISOString(), files, warnings, notes,
      result: { ...result, file: rel(result.file), wav: rel(result.wav), mixReport: rel(result.mixReport) } };
    fs.writeFileSync(path.join(tmp, 'entry.json'), JSON.stringify(entry, null, 2));
    const dst = path.join(root, key);
    fs.rmSync(dst, { recursive: true, force: true });
    fs.renameSync(tmp, dst);
    prune(root);
    return true;
  } catch {
    try { fs.rmSync(tmp, { recursive: true, force: true }); } catch { /* best effort */ }
    return false;
  }
}

function prune(root) {
  let ents = [];
  try {
    ents = fs.readdirSync(root).filter((n) => !n.startsWith('.')).map((n) => {
      let t = 0, size = 0;
      try {
        t = fs.statSync(path.join(root, n, 'entry.json')).mtimeMs;
        for (const f of fs.readdirSync(path.join(root, n))) size += fs.statSync(path.join(root, n, f)).size;
      } catch { /* broken entry: oldest */ }
      return { n, t, size };
    });
  } catch { return; }
  ents.sort((x, y) => y.t - x.t);
  let bytes = 0;
  ents.forEach((e, k) => {
    bytes += e.size;
    if (k >= KEEP || bytes > KEEP_BYTES || !e.t) { try { fs.rmSync(path.join(root, e.n), { recursive: true, force: true }); } catch { /* best effort */ } }
  });
}
